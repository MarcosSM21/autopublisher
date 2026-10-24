# Data Model — Feature 021

Migración única: `0019_deletion_library_folders` (ver [research.md §18](research.md)).
Nombres de constraints según `NAMING_CONVENTION` de `app/models.py`.

## Nuevas tablas

### `library_folders` — `LibraryFolder`

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | INTEGER PK **AUTOINCREMENT** | Nunca reutilizado. |
| `project_id` | INTEGER NOT NULL | FK → `projects.id` RESTRICT. |
| `parent_id` | INTEGER NULL | NULL = primer nivel. |
| `name` | VARCHAR(100) NOT NULL | 1–100 tras `strip()`. |
| `name_key` | VARCHAR NOT NULL | `normalize_key(name)` (NFKC + casefold). |
| `depth` | INTEGER NOT NULL | 1 en la raíz; `parent.depth + 1`. |
| `created_at`, `updated_at` | UTCDateTime NOT NULL | Como el resto de entidades editables. |

Constraints:

- `UNIQUE(id, project_id)` — destino de las FK compuestas.
- FK compuesta `(parent_id, project_id) → library_folders(id, project_id)` RESTRICT (padre
  del mismo proyecto; no aplicada cuando `parent_id` es NULL).
- `CHECK(depth BETWEEN 1 AND 5)` → `ck_library_folders_depth_range`.
- `CHECK((parent_id IS NULL) = (depth = 1))` → `ck_library_folders_root_depth`.
- Índice único parcial `uq_library_folders_root_name`: `(project_id, name_key) WHERE
  parent_id IS NULL`.
- Índice único parcial `uq_library_folders_child_name`: `(parent_id, name_key) WHERE
  parent_id IS NOT NULL`.

Ciclo de vida: crear (raíz o hija, `depth ≤ 5`), renombrar (recalcula `name_key`), borrar
(subárbol; su Media → Unsorted). No se mueve: `parent_id`, `project_id` y `depth` son
inmutables.

### `pending_file_deletions` — `PendingFileDeletion` (interno)

| Columna | Tipo | Reglas |
|---|---|---|
| `storage_path` | VARCHAR(255) PK | Relativa a la raíz de Media (`projects/{id}/…`). |
| `created_at` | UTCDateTime NOT NULL | Solo diagnóstico. |

Insertada en la transacción del borrado (write-ahead); eliminada cuando el archivo ya no
existe. Nunca expuesta por la API.

### `pending_credential_deletions` — `PendingCredentialDeletion` (interno)

| Columna | Tipo | Reglas |
|---|---|---|
| `credential_ref` | VARCHAR(64) PK | Ref UUID del secreto. |
| `platform` | VARCHAR(20) NOT NULL | Selecciona el servicio de keyring. `CHECK platform IN (…plataformas con conexión…)`. |
| `account_id` | INTEGER NULL | Solo para logs; **sin FK**. |
| `created_at` | UTCDateTime NOT NULL | |

Sustituye a `tiktok_credential_orphans` (filas migradas con `platform='tiktok'`; tabla
eliminada). Nunca contiene secretos. Escritores:

- la transacción de borrado (write-ahead, una fila por conexión borrada);
- el paso final de un flujo de conexión cuya Account desapareció y cuyo secreto no pudo
  borrarse (`INSERT OR IGNORE`, idempotente: el ref puede estar ya en la cola, p. ej. en
  la renovación de Telegram);
- los reemplazos de credencial de TikTok, como hoy.

## Tablas modificadas

| Tabla | Cambio |
|---|---|
| `projects` | AUTOINCREMENT. |
| `accounts` | AUTOINCREMENT. |
| `distribution_presets` | AUTOINCREMENT. |
| `contents` | AUTOINCREMENT; `folder_id INTEGER NULL` (NULL = Unsorted); FK compuesta `(folder_id, project_id) → library_folders(id, project_id)` RESTRICT; índice `ix_contents_folder_id`. |
| `publications` | AUTOINCREMENT; índices parciales recreados idénticos. |
| `temporary_media_objects` | `attempt_id` pasa a NULL-able (NULL = intento borrado; el objeto remoto sigue pendiente de limpieza). La limpieza solo necesita `object_key` + la configuración global de entrega: nunca Account, Connection ni keyring. |

Datos existentes: todas las filas conservan su id; `contents.folder_id = NULL` (Unsorted).
`sqlite_sequence` queda en el máximo id actual de cada tabla.

## Relaciones tras 021 (lo que arrastra cada borrado)

```text
Project ─┬─ Account ─┬─ Connection (1 por plataforma) ── credential_ref → pending_credential_deletions
         │           ├─ DistributionPresetAccount
         │           └─ Post*
         ├─ DistributionPreset ── DistributionPresetAccount
         ├─ LibraryFolder ── LibraryFolder (hijas, ≤5 niveles)
         │        └······ Content.folder_id (SET NULL lógico al borrar carpeta)
         ├─ Content ─┬─ Post*
         │           └─ archivos (original, copia limpia) → pending_file_deletions
         └─ Post* ─┬─ PublicationAttempt ─┬─ {Instagram,Threads,TikTok}PublishRun
                   │                      └─ TemporaryMediaObject (attempt_id → NULL si pendiente; DELETE si ya limpiado)
                   └─ {YouTube,Instagram,Threads,TikTok}PublicationOptions
```

`Post*` = mismo conjunto de primitivas (`_delete_posts`).

## Estados y buckets usados por el borrado

| Estado visible del Post | Bucket de resumen | ¿Bloquea? |
|---|---|---|
| Draft (`unscheduled`), Scheduled (auto/manual/paused), Missed, Cancelled, Failed | `unpublished` | No |
| Needs review (`failed` + último intento `outcome_determined = False`) | `needs_review` | No |
| Published, Awaiting user action | `remote` | No |
| Publishing (`publishing` o intento `running`) | — | **Sí** → `post_in_progress` |
| Media con Remove metadata en curso (memoria) | — | **Sí** → `metadata_removal_in_progress` |

## Validaciones (mensajes humanos)

| Regla | Dónde | Error |
|---|---|---|
| Nombre 1–100 tras recorte | Pydantic + servicio | 422 (formato de validación existente) |
| Hermana con el mismo `name_key` | Servicio (consulta) + índice único parcial | 409 `folder_name_taken` "A folder with this name already exists here." |
| Profundidad > 5 | Servicio + CHECK | 409 `folder_too_deep` "Folders can be nested up to 5 levels." |
| Padre/carpeta/Media de otro proyecto o inexistente | Servicio + FK compuesta | 404 |
| Mover a carpeta de otro proyecto | Servicio + FK compuesta | 404, nada cambia |

`IntegrityError` nunca llega al cliente: se traduce al código estable correspondiente o al
error interno genérico.
