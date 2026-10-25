# Implementation Plan: Bulk Media Delete

**Branch**: `022-bulk-media-delete` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/022-bulk-media-delete/spec.md`

## Summary

Extender el borrado individual de Media de Feature 021 a selecciones de 1–500 Media del
mismo Project, **dentro del servicio de borrado existente** (`app/deletion.py`): un nuevo
`DeletionKind = "media_selection"` reutiliza `DeletionScope`, `PostEntry`,
`confirmation_token`, `_post_entries`, `_delete_posts`, `_delete_contents`, la cola
`pending_file_deletions`, `ContentFileGuard.deleting(ids)` y `write_transaction`
(`BEGIN IMMEDIATE`). Una única transacción borra todos los Posts y todos los Media o nada.
La única lógica nueva de backend es: collect por conjunto, resumen agregado, precedencia
`post_in_progress` > `metadata_removal_in_progress` y dos rutas `POST` anidadas en el
Project. En el frontend, `SelectionBar` gana Delete y `MediaView` abre el
`DeleteConfirmDialog` existente con el preview agregado (dos cambios opcionales y
retrocompatibles en el diálogo). Sin migraciones ni cambios de modelo.

Detalle y alternativas: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.1; React Router, Radix Dialog. **Ninguna
dependencia nueva.**

**Storage**: SQLite (sin migración; tablas de 021 incluida `pending_file_deletions`),
Media en disco (sin cambios de layout)

**Testing**: pytest + TestClient (backend), Vitest + Testing Library (frontend); tests
dirigidos; barreras deterministas existentes (`pause_before_commit`,
`statement_reached`, `pause_in_prepare`, `Gate`, `Background`) para carreras; suites
completas solo en CI

**Target Platform**: Linux, navegador de escritorio y móvil en LAN

**Project Type**: web application (backend + frontend)

**Performance Goals**: preview y borrado de 500 Media con un número constante de consultas
por conjunto (4 en collect); confirmación visible en < 2 s en la instalación de referencia
(SC-008)

**Constraints**: un proceso; nada de disco antes del COMMIT; guards all-or-none sin esperas;
borrado individual de 021 y Move sin cambios observables

**Scale/Scope**: decenas, ocasionalmente cientos de Media por operación; máximo 500

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Notas |
|---|---|---|
| I. Simplicidad y alcance | ✅ | Un kind nuevo en el servicio existente; sin framework de bulk, sin servicio paralelo, sin migración, sin chunking. |
| II. Spec-Driven | ✅ | Spec "Ready for planning", D1–D5 confirmadas; nada fuera de alcance. |
| III. Arquitectura modular | ✅ | Ningún publisher implicado; el borrado no contacta plataformas. |
| IV. Seguridad | ✅ | Rutas nuevas tras sesión + Host/Origin; token sin rutas/nombres; logs solo con recuentos. |
| V. Calidad | ✅ | Tests dirigidos de carreras, rollback, precedencia y limpieza; ningún borrado sin confirmación explícita. |
| VI. Git | ✅ | Commits pequeños por fase; README actualizado (bulk delete). |
| Arquitectura base | ✅ | Sin cambios. |

Re-check post-diseño: ✅ sin violaciones. **Complexity Tracking** vacío.

## Architecture

```text
 deletion_routes.py
   POST /projects/{pid}/contents/deletion-preview  ─► deletion.preview_media_selection
   POST /projects/{pid}/contents/delete            ─► deletion.execute_media_selection
                                   │
 deletion.py                       ▼
   collect_media_selection(session, pid, ids)   4 set queries, never raises for a
                                                missing media (caller decides 404/409)
   build_preview(scope, sanitizing)             media_selection: post_in_progress first
   confirmation_token(scope)                    unchanged (kind + project id + sorted ids
                                                + sorted posts)
   _hold_selection(ctx, pid, ids)               guard.deleting(ids); on
                                                metadata_removal_in_progress → read-only
                                                in_progress check → post_in_progress
   _delete_confirmed(ctx, read, held, kind, c)  extracted from execute (shared)
   _after_commit(ctx, scope)                    extracted from execute (shared)
```

### Orden exacto del Delete

```text
0. Body validated (422): 1–500 ids, unique, confirmation present.
1. _hold_selection: ContentFileGuard.deleting(sorted ids)  — all-or-none, never waits
     ├─ some id held by another delete       → 409 deletion_changed
     ├─ some id sanitizing                   → short read-only session:
     │     any dependent post in_progress?   → 409 post_in_progress
     │     otherwise                         → 409 metadata_removal_in_progress
     └─ acquired → continue (held = ids)
2. write_transaction (BEGIN IMMEDIATE: scheduler/manual claims serialized)
   2.1 scope = collect_media_selection(session, pid, ids)   (404 if project gone)
   2.2 set(scope.content_ids) != set(ids)                   → 409 deletion_changed
   2.3 held ⊇ scope.content_ids                             (generalized 021 check)
   2.4 scope.in_progress                                    → 409 post_in_progress
   2.5 confirmation != confirmation_token(scope)            → 409 deletion_changed
   2.6 _delete_posts(subquery: posts of ids)
   2.7 _delete_contents(ids, file_paths) → enqueue_files (write-ahead) + DELETE contents
   2.8 COMMIT                                   (any error → full rollback)
3. release guards (finally, whatever happened)
4. _after_commit: log counts; run_file_cleanup(file_paths) — failures stay queued
```

No hay deadlock: el guard nunca espera (registra o falla bajo su mutex) y el writer lock se
toma después; `claiming` retiene el mutex del guard solo durante el UPDATE del claim, que no
depende del guard de borrado (patrón de 021).

### Preview (read-only)

`collect_media_selection` con la sesión de la petición → si faltan Media → `404`
agregado; `sanitizing = any(guard.is_sanitizing(id))`; `build_preview` con precedencia
`post_in_progress` primero para `media_selection`; `id`/`name` nulos.

### Token

Sin cambios en `confirmation_token`. Canónico para la selección:
`{"kind":"media_selection","id":<project_id>,"posts":[[id,status,needs_review]…ordenados],
"contents":[ids ordenados], resto vacío}` → `v1:` + SHA-256. Detalle en research §5.

## Backend changes

| Archivo | Cambio |
|---|---|
| `app/schemas.py` | `DeletionKind` + `"media_selection"`; `DeletionPreviewRead.id: int \| None`, `name: str \| None`; `ContentSelection` y `ContentSelectionDelete` (reutilizan `MAX_CONTENTS_PER_MOVE`, `_unique_content_ids`). |
| `app/deletion.py` | Mensajes `NOT_FOUND`/`IN_PROGRESS`/`METADATA_REMOVAL` de `media_selection`; `collect_media_selection`; `_selection_summary` (3 líneas, research §3/contrato); precedencia `IN_PROGRESS_FIRST` en `build_preview` e `id`/`name` nulos; `preview_media_selection`; extracción de `_delete_confirmed` y `_after_commit` desde `execute` (sin cambio de comportamiento); `_hold_selection`; `execute_media_selection`; rama `media_selection` en `_delete` (posts por subconsulta). |
| `app/deletion_routes.py` | Dos rutas `POST` (preview `200`, delete `204`). |
| `README.md` | Una línea en la sección de borrado: bulk delete desde Select mode. |

Sin cambios en: `content_files.py`, `cleanup.py`, `library_folders.py`, scheduler,
publishers, modelos, migraciones.

## Frontend changes

| Archivo | Cambio |
|---|---|
| `src/types.ts` | `DeletionKind` + `"media_selection"`; `DeletionPreview.id: number \| null`, `name: string \| null`. |
| `src/api.ts` | `getMediaSelectionDeletionPreview`, `deleteMediaSelection`; `DELETION_PATHS` tipado sobre los kinds individuales. |
| `src/components/DeleteConfirmDialog.tsx` | No pinta `name` nulo; prop opcional `onMissing` para `404`. |
| `src/pages/library/SelectionBar.tsx` | Prop `onDelete`; botón Delete (secundario, `ap-delete-entry`), deshabilitado con 0. |
| `src/pages/library/MediaView.tsx` | Estado `bulkDelete: number[] \| null`; diálogo con título pluralizado; `onDeleted` / `onMissing` / `onClose` (contracts/ui.md §3). |
| `src/pages/library/library.css` | Teléfono: contador en fila propia, tres botones en la segunda. |
| `src/test-fake-api.ts` | Rutas bulk que agregan `deletionScope("media", id)`; precedencia de blockers; `404` si falta algún id; token por conjunto ordenado. |

## Stale selection

- **Preview `404`** → `onMissing`: cerrar diálogo, `load()` (ya poda la selección a lo que
  sigue en la vista), flash breve; no se borra nada; el usuario vuelve a pulsar Delete.
- **Delete `409 deletion_changed`** → el diálogo recarga el preview (021). Si la causa fue un
  Media desaparecido, ese preview da `404` → mismo camino `onMissing`. Si fue otro cambio, se
  muestra el preview nuevo y se exige otro clic.
- La selección del diálogo es una instantánea (`bulkDelete`); la de la vista solo cambia
  tras recargar del backend: sin estado parcial.

## Scale (500)

Sin chunking (research §7): `IN` ≤ 500 parámetros; Posts por subconsulta; `enqueue_files`
por `executemany`; límite de SQLite 3.51 = 32 766. La limpieza de archivos post-COMMIT hace
una consulta por ruta fuera de la transacción (como el borrado de Project).

## Implementation phases

| Fase | Contenido | Checkpoint |
|---|---|---|
| **A. Backend** | Esquemas, refactor `_delete_confirmed`/`_after_commit`, collect, preview, precedencia, execute, rutas, tests backend | Tests nuevos `test_delete_media_selection.py` + `test_delete_media.py`, `test_delete_project.py` (refactor) + `test_media_move.py` en verde |
| **B. Frontend** | Tipos/API, diálogo, SelectionBar, MediaView, CSS, fake API, tests | `vitest` de `src/pages/library` y `DeleteConfirmDialog` en verde |
| **C. Cierre** | Validación manual (quickstart), lint/format/mypy/tsc/build, `git diff --check`, revisión de seguridad del diff, README | Todo verde; PR |

## Tests (dirigidos)

### Backend — `tests/test_delete_media_selection.py` (helpers de `test_delete_media.py`)

| Test | Verifica |
|---|---|
| un Media; varios Media; Media sin Posts; Media con varios Posts en estados mezclados | 204; Media, Posts, attempts y opciones borrados; summary/counts exactos |
| original + clean copy de todos | encolados antes del COMMIT y eliminados tras él |
| fallo de unlink | 204; filas pendientes; reintento en arranque (`_restart`) |
| un Post Publishing en uno | preview blocker + 409 `post_in_progress`; nada borrado; guards liberados |
| Remove metadata en uno | preview blocker + 409 `metadata_removal_in_progress`; nada borrado |
| **Publishing en A + Remove metadata en B**, parametrizado por orden de ids | `post_in_progress` en preview **y** delete; nada borrado |
| delete primero → claim (scheduler) | barreras de 021: el claim no arranca; Posts no existen |
| claim primero (scheduler y publish-now, parametrizado) | 409; ningún Media borrado |
| bulk retiene → Remove metadata | `content_deleting` |
| token independiente del orden de ids; token bulk ≠ token individual | determinismo y aislamiento |
| Post nuevo / borrado / cambio de `status` / `needs_review` tras preview (parametrizado) | 409 `deletion_changed`; nada borrado |
| Media desaparece antes del preview | 404 agregado |
| Media desaparece tras el preview | 409 `deletion_changed`; los demás intactos |
| otro borrado retiene uno | 409 `deletion_changed` |
| vacío, > 500, repetidos, cross-project, Project inexistente | 422 / 422 / 422 / 404 / 404 |
| fallo en `DELETE FROM contents` | 500; rollback total; sin pending rows; guards liberados |
| sin llamadas a publishers | `fake_publisher` sin llamadas |
| ids no reutilizados | Media importado después tiene id mayor |
| 500 Media | preview y delete correctos (SC-008) |
| rutas privadas y con guards | sesión + Origin |

Regresión dirigida por el refactor: `test_delete_media.py`, `test_delete_project.py`,
`test_media_move.py`.

### Frontend

| Test | Verifica |
|---|---|
| `SelectionBar` | Move + Delete + Cancel; Delete deshabilitado con 0 |
| bulk en `media-delete.test.tsx` (o `bulk-delete.test.tsx`), parametrizado Folder/Unsorted/All media | preview agregado; una confirmación; éxito quita todas las tarjetas; Select mode sale; contadores |
| blocker | solo Close; nada cambia |
| `deletion_changed` | aviso + preview nuevo + segundo clic requerido |
| preview 404 | diálogo cerrado, selección podada, flash |
| fallo de red | selección conservada, ninguna tarjeta desaparece |
| móvil | `Sheet` en viewport de teléfono |
| `DeleteConfirmDialog.test.tsx` | usos existentes intactos (sin `onMissing`, con nombre) |

## Risks

| Nivel | Riesgo | Mitigación |
|---|---|---|
| HIGH | Refactor de `execute` altera el borrado de 021 | Extracción mecánica; regresión dirigida de media/project/post/account; la comprobación `held ⊇ content_ids` generalizada es trivialmente cierta para los kinds sin Media |
| HIGH | Conversión de precedencia captura errores del cuerpo | Adquisición separada con `ExitStack`; test que fuerza `deletion_changed` del cuerpo con un Media saneándose ajeno |
| MEDIUM | `DeletionPreviewRead.id/name` nullable rompe tipos del frontend | `tsc` en fase C; el único consumidor de `name` es el diálogo |
| MEDIUM | `DeleteConfirmDialog` `404` → `onDeleted` borra visualmente la selección obsoleta | `onMissing` explícito; test de preview 404 |
| MEDIUM | Barra en móvil con tres botones desborda | CSS de dos filas; test de viewport + validación manual |

## Pending decisions

Ninguna de producto. Una decisión técnica tomada sin consulta (research §4): la precedencia
`post_in_progress` primero se aplica solo a `media_selection`; el preview de Project de 021
conserva su orden actual.

## Project Structure

### Documentation (this feature)

```text
specs/022-bulk-media-delete/
├── spec.md
├── plan.md
├── research.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   └── ui.md
└── checklists/requirements.md
```

Sin `data-model.md`: no cambia el modelo de datos.

### Source Code (repository root)

```text
backend/app/{schemas.py, deletion.py, deletion_routes.py}
backend/tests/test_delete_media_selection.py
frontend/src/{types.ts, api.ts, test-fake-api.ts}
frontend/src/components/DeleteConfirmDialog.tsx
frontend/src/pages/library/{SelectionBar.tsx, MediaView.tsx, library.css, *.test.tsx}
```

**Structure Decision**: aplicación web existente (backend + frontend); sin módulos nuevos
salvo el archivo de tests backend.

## Complexity Tracking

Vacío.
