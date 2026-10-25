# Research — Feature 022: Bulk Media Delete

Decisiones de diseño tomadas tras inspeccionar el código real de Feature 021
(`backend/app/deletion.py`, `deletion_routes.py`, `content_files.py`, `cleanup.py`,
`library_folders.py`, `publishing.py`; `frontend/src/components/DeleteConfirmDialog.tsx`,
`pages/library/MediaView.tsx`, `SelectionBar.tsx`, `api.ts`, `types.ts`,
`test-fake-api.ts`). Formato: Decision / Rationale / Alternatives.

## §1. Estado de partida relevante

- `DeletionScope` es un dataclass genérico: `kind`, `target_id`, `name`, `posts:
  tuple[PostEntry]`, `content_ids`, `file_paths` (y otros vacíos para Media). Media ya se
  representa con `content_ids=(id,)` y `file_paths=(original[, clean])`.
- `_post_entries(session, where)` recibe una condición sobre `Publication` y resuelve
  estado, `needs_review` e `in_progress` con **dos** consultas por conjunto (posts + attempts),
  sin N+1.
- `confirmation_token(scope)` ya es canónico: `kind`, `id`, posts `[id, status,
  needs_review]` ordenados, `contents` ordenados, resto de listas ordenadas; SHA-256 de JSON
  con `sort_keys`. No incluye nombres, rutas ni tiempos.
- `execute(ctx, kind, id, confirmation)`: `_held_contents` (guard `deleting`) →
  `write_transaction` (`BEGIN IMMEDIATE`) → `collect` → `held ⊇ scope.content_ids` (solo
  project) → `in_progress` → token → `_delete` → COMMIT → liberar guard → log → limpieza
  post-commit (`run_file_cleanup`).
- `ContentFileGuard.deleting(ids)` ya es all-or-none, ordena ids, no espera nunca, y falla
  con `metadata_removal_in_progress` (algún id saneándose) o `deletion_changed` (otro borrado
  lo retiene). `sanitizing()` rechaza con `content_deleting` si el id está retenido.
  `claiming()` rechaza si el id se está saneando → **un mismo Media no puede estar a la vez
  publicándose y saneándose**; los dos bloqueos solo coinciden entre Media distintos.
- `build_preview` hoy da precedencia a `metadata_removal_in_progress` sobre
  `post_in_progress` (relevante solo para Project, donde pueden coincidir en Media
  distintos).
- Move (`POST /api/projects/{id}/contents/move`, `ContentMove`) valida 1–500 ids sin
  repetidos (`MAX_CONTENTS_PER_MOVE`, `_unique_content_ids`) y da `404` si algún id falta o
  es ajeno.
- Frontend: `MediaView.load()` ya poda la selección a los Media presentes en la vista;
  `DeleteConfirmDialog` trata un `404` del preview o del DELETE como "ya borrado" →
  `onDeleted`, y `409 deletion_changed` → recarga preview y espera otro clic.
- SQLite del entorno: 3.51 (límite de parámetros 32 766).

## §2. Representación de `media_selection`

**Decision**: nuevo `DeletionKind = "media_selection"` que reutiliza `DeletionScope` sin
campos nuevos: `target_id = project_id`, `name = ""` (no se muestra), `posts` = todos los
Posts de los Media seleccionados, `content_ids` = ids seleccionados existentes (ordenados),
`file_paths` = originales + clean copies. El preview devuelve `id = null`, `name = null`.

**Rationale**: el mismo dataclass, el mismo token, el mismo `_counts`, la misma cola de
archivos; solo cambian collect, summary y mensajes. `target_id = project_id` aporta
aislamiento por Project al token sin añadir campos.

**Alternatives**: un `BulkDeletionScope` propio (duplica token/counts/preview, rechazado);
un servicio paralelo `bulk_deletion.py` (rechazado por la spec: "no rediseñar deletion").

## §3. Collect de la selección

**Decision**: `collect_media_selection(session, project_id, content_ids) -> DeletionScope`:

1. `Project` inexistente → `NotFoundError("Project not found.")`.
2. Una consulta: `id, storage_path, sanitized_storage_path` de `Content` con
   `id IN (:ids) AND project_id = :project_id`, ordenado por id.
3. Posts: `_post_entries(session, Publication.content_id.in_(found_ids))` (2 consultas).
4. **No lanza** si falta algún Media: devuelve solo los encontrados. Quien llama decide:
   preview → `404` agregado; delete → `409 deletion_changed`.

La validación de forma (1–500, sin repetidos) vive en el esquema de entrada (`422`), como
Move. Total: 4 consultas por conjunto, independientemente del tamaño.

**Rationale**: separar "qué existe" de "cómo se informa" permite que la misma función sirva
a preview (404, D2) y a delete (409, D2) sin flags.

**Alternatives**: lanzar `NotFoundError` dentro de collect y convertirlo a 409 en delete
(frágil: confunde Project inexistente con Media inexistente).

## §4. Precedencia de bloqueos (FR-017a)

**Decision**:

- **Preview**: `build_preview` evalúa `post_in_progress` antes que
  `metadata_removal_in_progress` **solo para `media_selection`** (conjunto
  `IN_PROGRESS_FIRST = {"media_selection"}`). Los kinds de 021 conservan su orden.
- **Delete**: la retención de guards se hace en `_hold_selection(ctx, project_id, ids)`.
  Si `file_guard.deleting(ids)` falla con `metadata_removal_in_progress`, antes de propagar
  se abre una sesión corta de solo lectura y se mira si algún Post de los Media
  seleccionados está `in_progress` (`collect_media_selection(...).in_progress`); si lo está
  → `409 post_in_progress`, si no → se re-lanza `metadata_removal_in_progress`. La
  adquisición se separa del cuerpo con `ExitStack` para que esta conversión **solo** se
  aplique al fallo de adquisición, nunca a errores del cuerpo.
- Si los guards se adquieren, la transacción comprueba `in_progress` con el writer lock
  (autoritativo), como en 021.

**Rationale**: la exclusión no cambia (el guard sigue siendo all-or-none y no espera); la
consulta extra solo se paga en el camino de fallo. La precedencia se aplica sobre el estado
observado, no sobre el orden de ids ni de consultas. Si la publicación termina entre la
adquisición fallida y la consulta, la respuesta es `metadata_removal_in_progress`, que
también es correcta para ese instante; en ningún caso se borra nada.

**Alternatives**: comprobar Publishing (solo lectura) **antes** de adquirir guards (paga una
consulta extra en el camino feliz y deja la misma ventana de carrera); cambiar la
precedencia global de `build_preview` (alteraría el borrado de Project de 021, prohibido por
FR-034).

## §5. Token

**Decision**: sin cambios en `confirmation_token`. Para `media_selection` el canónico es:

```json
{"kind":"media_selection","id":<project_id>,
 "posts":[[id,"status",needs_review],...ordenados],
 "contents":[ids ordenados],
 "accounts":[],"folders":[],"to_unsorted":[],"presets":[],"connections":[]}
```

`v1:` + SHA-256 del JSON con `sort_keys` y separadores compactos.

- Independiente del orden de `content_ids` (se ordenan), de nombres, rutas, carpeta
  (`folder_id` no entra) y tiempos.
- Un token bulk nunca valida un borrado individual (`kind` distinto, `id` = project vs
  content) ni al revés.
- Cambia si aparece/desaparece un Media seleccionado (`contents`), un Post dependiente
  (`posts`), su `status` persistido o `needs_review`.

**Alternatives**: añadir un campo `selection` explícito (redundante con `contents`).

## §6. Ejecución: refactor mínimo de `execute`

**Decision**: extraer de `execute` dos piezas internas sin cambiar su comportamiento:

- `_delete_confirmed(ctx, read_scope, held, kind, confirmation) -> DeletionScope`: la
  `write_transaction` con `scope = read_scope(session)` → `held ⊇ scope.content_ids`
  (`deletion_changed`) → `in_progress` (`post_in_progress`) → token (`deletion_changed`) →
  `_delete(session, scope)`.
- `_after_commit(ctx, scope)`: log, invalidación de intentos, `run_file_cleanup`, secretos,
  directorio de Project (lo que hoy hay tras el `with`).

`execute` queda como `_held_contents` + `_delete_confirmed` + `_after_commit`.
`execute_media_selection(ctx, project_id, content_ids, confirmation)` es:

```text
with _hold_selection(ctx, project_id, ids) as held:        # §4
    scope = _delete_confirmed(ctx, read, held, "media_selection", confirmation)
       where read(session) = collect_media_selection(session, project_id, ids)
             and, before the generic checks, set(scope.content_ids) != set(ids)
             → deletion_changed
_after_commit(ctx, scope)
```

La comprobación `held ⊇ scope.content_ids` pasa a ser general (hoy solo project): para
post/account/folder `content_ids` es vacío y para media es `{id}`, así que no cambia nada.

`_delete` para `media_selection`: `_delete_posts(session, select(Publication.id).where(
Publication.content_id.in_(ids)))` (subconsulta) + `_delete_contents(session, ids,
file_paths)`.

**Rationale**: una sola transacción, mismas primitivas, sin llamar N veces al borrado
individual; el refactor es mecánico y queda cubierto por los tests de 021 existentes de
media/project.

**Alternatives**: duplicar `execute` (~25 líneas) en una función bulk (menos riesgo
inmediato, pero dos caminos que pueden divergir).

## §7. Escala 500

**Decision**: sin chunking.

- `IN (:ids)` con ≤ 500 parámetros en collect y en `_delete_contents`.
- Posts: subconsulta en `_delete_posts` (no se construye una lista de ids de Posts).
- `_post_entries`: condición `content_id IN (≤500)`; dos consultas.
- `enqueue_files`: `executemany` de ≤ 1000 filas (sin límite de parámetros por sentencia).
- `run_file_cleanup(paths)`: `IN (≤1000)` + una consulta de referencia por ruta tras el
  COMMIT (fuera de la transacción; ya ocurre igual en el borrado de Project).

Muy por debajo del límite de 32 766 parámetros; ninguna consulta escala con N salvo la
limpieza post-commit, que no bloquea al escritor. SC-008 se valida con un test de 500
Media (dirigido, sin microbenchmark).

**Alternatives**: chunking de ids (innecesario a esta escala).

## §8. API

**Decision** (D1): rutas en `deletion_routes.py`, junto al resto de borrados:

- `POST /api/projects/{project_id}/contents/deletion-preview` — body
  `ContentSelection {content_ids}`.
- `POST /api/projects/{project_id}/contents/delete` — body `ContentSelectionDelete
  {content_ids, confirmation}`.

`ContentSelection` reutiliza `MAX_CONTENTS_PER_MOVE` y `_unique_content_ids`.
`DeletionPreviewRead.id` y `.name` pasan a `int | None` / `str | None`.

**Rationale**: coherente con Move y con los contratos de 021; el preview por `POST` es
necesario por el body (sigue siendo de solo lectura).

## §9. Frontend

**Decision**:

- `DeleteConfirmDialog`: (a) no renderiza el nombre si `preview.name` es `null`;
  (b) prop opcional `onMissing?: () => void`: si existe, un `404` (preview o delete) lo
  llama en lugar de `onDeleted`. Sin otros cambios; usos actuales intactos.
- `SelectionBar`: prop `onDelete`; botón Delete secundario con estilo destructivo de texto
  (`ap-delete-entry`), deshabilitado con 0. Move sigue siendo el primario.
- `MediaView`: estado `bulkDelete: number[] | null` (instantánea de la selección al pulsar
  Delete). `onDeleted` → salir de Select mode, cerrar el detalle si su Media estaba en la
  selección, flash "N media deleted.", `handleChanged()`. `onMissing` → cerrar diálogo,
  `load()` (poda la selección), flash "Some selected media no longer exist. Review your
  selection.". `onClose` → conserva la selección.
- `api.ts`: `getMediaSelectionDeletionPreview(projectId, ids)` y
  `deleteMediaSelection(projectId, ids, confirmation)`; `DELETION_PATHS` se tipa sobre los
  kinds individuales.
- Fake API de tests: dos rutas nuevas que agregan el `deletionScope("media", id)` existente
  y aplican la precedencia de bloqueos.

**Rationale**: `deletion_changed` por Media desaparecido ya compone: el diálogo recarga el
preview → `404` → `onMissing` → refresco y poda, sin estado parcial.

## §10. Move concurrente y vistas

- `folder_id` no está en el token: un Move de otra pestaña no invalida el borrado.
- Tras el éxito, `load()` relee lista y árbol (contadores de Folder/Unsorted/All media).
  Posts y Home: `reloadOverview()`; la página de Posts relee al montarse (sin caché
  compartida), como en 021.
- Un Media movido fuera de la vista mientras el diálogo estaba abierto se borra igual (forma
  parte de la selección confirmada) y simplemente no reaparece al refrescar.
