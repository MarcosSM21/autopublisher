# Data Model: Publicaciones y programación

**Feature**: `004-publication-scheduling` | **Fecha**: 2026-10-06

Amplía el modelo de las Features 002 (`projects`, `accounts`) y 003 (`contents`) con una
tabla nueva. Las tablas existentes no cambian. Migración Alembic `0003_create_publications`.

## Publication (`publications`)

| Columna | Tipo | Nulo | Notas |
|---------|------|------|-------|
| `id` | INTEGER PK | no | |
| `project_id` | INTEGER FK → `projects.id` (`RESTRICT`) | no | Inmutable. Igual a `content.project_id` y `account.project_id`. |
| `content_id` | INTEGER FK → `contents.id` (`RESTRICT`) | no | Inmutable. |
| `account_id` | INTEGER FK → `accounts.id` (`RESTRICT`) | no | Inmutable. |
| `status` | VARCHAR(20) | no | `unscheduled` \| `scheduled` \| `cancelled` (`PublicationStatus`). |
| `scheduled_at` | DATETIME (`UTCDateTime`) | sí | Instante UTC con precisión de minuto. |
| `title_override` | VARCHAR(200) | sí | `NULL` = usar el título del contenido; `""` = override vacío. |
| `description_override` | VARCHAR(5000) | sí | `NULL` = usar la descripción del contenido; `""` = override vacío. |
| `hashtags_override` | `JSON(none_as_null=True)` (lista de texto) | sí | SQL `NULL` = usar los hashtags del contenido; `[]` = override vacío. `none_as_null` garantiza que Python `None` se guarda como SQL `NULL` y no como JSON `null`. |
| `created_at` | DATETIME (`UTCDateTime`) | no | |
| `updated_at` | DATETIME (`UTCDateTime`) | no | Solo cambia con modificaciones efectivas. |

`project_id` se guarda (aunque se podría deducir del contenido) para listar la Queue de un
proyecto con una condición simple e indexada, y porque la spec lo trata como atributo
inmutable de la publicación.

### Restricciones e índices

- `CHECK (status IN ('unscheduled', 'scheduled', 'cancelled'))`.
- `CHECK` de coherencia estado/fecha:
  `status = 'cancelled' OR (status = 'scheduled' AND scheduled_at IS NOT NULL) OR
  (status = 'unscheduled' AND scheduled_at IS NULL)`.
- **Índice único parcial** `uq_publications_active_content_account` sobre
  `(content_id, account_id) WHERE status != 'cancelled'`: como máximo una publicación activa
  por pareja contenido + cuenta (FR-008); las canceladas no cuentan (FR-009).
- Índice `ix_publications_project_id_status_scheduled_at` sobre
  `(project_id, status, scheduled_at)` para la Queue.

### Relaciones

- `Project 1 — N Publication`, `Content 1 — N Publication`, `Account 1 — N Publication`.
- Sin borrado en cascada: no existe borrado físico de ninguna de estas entidades.

## Estados y transiciones

```text
               create (sin fecha)          create (con fecha futura)
                     │                               │
                     ▼          set date             ▼
              ┌─────────────┐ ───────────────▶ ┌───────────┐
              │ UNSCHEDULED │                  │ SCHEDULED │ ◀─┐ change date
              └─────────────┘ ◀─────────────── └───────────┘ ──┘
                     │          remove date          │
                     │ cancel                 cancel │
                     ▼                               ▼
              ┌─────────────────────────────────────────┐
              │               CANCELLED                 │
              └─────────────────────────────────────────┘
                 reactivate: → SCHEDULED si conserva fecha futura
                             → UNSCHEDULED si no tiene fecha o ya pasó (se descarta)
```

| Operación | Desde | Hacia | Requiere |
|-----------|-------|-------|----------|
| Crear sin fecha | — | `unscheduled` | Proyecto activo, cuenta activa del mismo proyecto, archivo disponible, sin otra activa para la pareja. |
| Crear con fecha | — | `scheduled` | Lo anterior + fecha futura. |
| Asignar / cambiar fecha | `unscheduled`, `scheduled` | `scheduled` | Fecha futura, proyecto activo, cuenta activa, archivo disponible (solo si la fecha cambia). |
| Quitar fecha | `scheduled` | `unscheduled` | Nada (permitido con proyecto/cuenta inactivos o archivo no disponible). |
| Editar overrides | `unscheduled`, `scheduled` | (sin cambio) | Nada. |
| Cancelar | `unscheduled`, `scheduled` | `cancelled` | Nada. Conserva fecha y overrides. Idempotente sobre `cancelled`. |
| Reactivar | `cancelled` | `scheduled` / `unscheduled` | Proyecto activo, cuenta activa, archivo disponible, sin otra activa para la pareja. |
| Cualquier edición | `cancelled` | — | Rechazada (`409 publication_cancelled`). |

No existe ninguna transición automática por el paso del tiempo (FR-013): una publicación
`scheduled` con fecha pasada sigue `scheduled` (la interfaz la marca como *Overdue*).

## Reglas de validación

### Creación (`POST /api/contents/{content_id}/publications`)

- `account_ids`: lista de enteros, 1–50 elementos; los repetidos se tratan como uno solo.
- `scheduled_at`: opcional; ISO 8601 con zona horaria; se trunca al minuto; debe ser
  posterior al momento actual.
- Cada cuenta: existe, pertenece al proyecto del contenido, está activa y no tiene ya una
  publicación activa del contenido.
- Proyecto del contenido activo; archivo del contenido disponible.
- Atómica: si cualquier comprobación falla no se crea nada (orden y códigos en
  [research.md §6](research.md#6-errores-de-la-creación-múltiple-fr-006-fr-007)).
- Las publicaciones nuevas no tienen overrides (todos `NULL`).

### Edición (`PATCH /api/publications/{id}`)

- Cuerpo parcial con al menos un campo: `scheduled_at`, `title_override`,
  `description_override`, `hashtags_override`. Cualquier otro campo (`content_id`,
  `account_id`, `project_id`, `status`…) se rechaza con `422` (`extra="forbid"`).
- `scheduled_at: null` quita la fecha; un valor la asigna o cambia (reglas de la tabla).
- `*_override: null` vuelve a "usar metadata global"; un valor define el override:
  - textos: se recortan; vacío o solo espacios → `""`; máximo 200 (título) y 5000
    (descripción);
  - hashtags: `normalize_hashtags` (Feature 003): sin `#`, sin espacios, sin repetidos sin
    distinguir mayúsculas, máximo 30 de hasta 100 caracteres.
- Publicación `cancelled` → `409 publication_cancelled`.

### Regla de `updated_at` (FR-021)

`updated_at` cambia solo si cambia efectivamente `status`, `scheduled_at` o algún override
(comparando valores normalizados, y distinguiendo `NULL` de `""`/`[]`). Un `PATCH` que deja
todo igual, o cancelar una publicación ya cancelada, no lo modifica.

## Metadata efectiva

Para cada campo `f ∈ {title, description, hashtags}`:

```text
effective_f = publication.f_override  si no es NULL
            = content.f               en otro caso
```

Se calcula al serializar; nunca se guarda. Por tanto, editar la metadata del contenido se
refleja al instante en todas sus publicaciones sin override para ese campo (FR-015).

## Representación en la API (`PublicationRead`)

Ver [contracts/api.md](contracts/api.md#publication). Incluye los ids inmutables, `status`,
`scheduled_at`, los tres overrides en bruto (`null` = hereda), los tres valores efectivos,
`created_at`, `updated_at` y dos resúmenes embebidos:

- `content`: `id`, `title`, `original_filename`, `media_type`, `file_url`,
  `file_available`;
- `account`: `id`, `platform`, `handle`, `display_name`, `is_active`;

además de `project_active` para que la interfaz pueda deshabilitar acciones sin otra
petición.
