# API Contract: publicaciones y programación

**Feature**: `004-publication-scheduling` | **Fecha**: 2026-10-06

Amplía la API REST bajo `/api` de las Features 002 y 003. Sin autenticación. Fechas en
ISO 8601; las respuestas siempre en UTC (`...Z`). Se mantiene el formato de error existente
(ver `specs/002-projects-accounts/contracts/api.md#error`) y se añaden códigos `409`.

No existe ninguna ruta `DELETE` para publicaciones (FR-022): un `DELETE` devuelve
`405 method_not_allowed`. Ninguna operación contacta con plataformas externas.

## Nuevos códigos de error

| `code` | HTTP | Cuándo |
|--------|------|--------|
| `account_inactive` | 409 | Crear, programar o reactivar con una cuenta inactiva. |
| `media_unavailable` | 409 | Crear, programar o reactivar cuando el archivo multimedia del contenido no está disponible. Mensaje: "The media file of this content is not available." |
| `publication_cancelled` | 409 | `PATCH` sobre una publicación cancelada. |
| `publication_not_cancelled` | 409 | Reactivar una publicación que no está cancelada. |

Los existentes se usan así:

- `duplicate` (409): ya existe una publicación activa para la pareja contenido + cuenta (al
  crear o reactivar).
- `project_inactive` (409): crear, programar o reactivar en un proyecto inactivo.
- `validation_error` (422): cuerpo inválido, fecha sin zona horaria, fecha pasada, cuenta
  inexistente o de otro proyecto en `account_ids`.
- `not_found` (404): contenido, proyecto o publicación del path inexistente.

## Representaciones

### Publication

```json
{
  "id": 7,
  "project_id": 1,
  "content_id": 12,
  "account_id": 3,
  "status": "scheduled",
  "scheduled_at": "2026-10-10T16:00:00Z",
  "title_override": null,
  "description_override": "Summer is here ☀️ Link in bio.",
  "hashtags_override": null,
  "title": "Summer teaser",
  "description": "Summer is here ☀️ Link in bio.",
  "hashtags": ["l4i4", "summer"],
  "content": {
    "id": 12,
    "title": "Summer teaser",
    "original_filename": "reel-01.mp4",
    "media_type": "video",
    "file_url": "/api/contents/12/file",
    "file_available": true
  },
  "account": {
    "id": 3,
    "platform": "instagram",
    "handle": "l4i4",
    "display_name": "L4i4",
    "is_active": true
  },
  "project_active": true,
  "created_at": "2026-10-06T09:00:00Z",
  "updated_at": "2026-10-06T09:05:00Z"
}
```

- `status` ∈ `unscheduled | scheduled | cancelled`.
- `scheduled_at` es `null` en `unscheduled`; en `cancelled` conserva la fecha que tuviera
  (o `null`).
- `*_override`: `null` = usa la metadata global del contenido; cualquier otro valor
  (incluidos `""` y `[]`) es un override.
- `title`, `description`, `hashtags`: valores **efectivos** (override o global actual).
- `content.title` es el título global del contenido (para identificarlo en la Queue).

## Rutas

### `GET /api/projects/{project_id}/publications`

Queue del proyecto: todas sus publicaciones, incluidas canceladas y las de cuentas
inactivas. Orden:

1. `scheduled` por `scheduled_at` ascendente, después `id`;
2. `unscheduled` por `created_at` ascendente, después `id`;
3. `cancelled` por `updated_at` descendente, después `id`.

- `200` → `Publication[]` (vacío si no hay ninguna). Válido también con el proyecto inactivo.
- `404 not_found`.

### `POST /api/contents/{content_id}/publications`

Crea una publicación por cuenta, de forma atómica.

```json
{ "account_ids": [3, 4, 5], "scheduled_at": "2026-10-10T18:00:00+02:00" }
```

| Campo | Tipo | Reglas |
|-------|------|--------|
| `account_ids` | `int[]` | Obligatorio, 1–50 elementos; repetidos se tratan como uno. |
| `scheduled_at` | `string \| null` | Opcional. ISO 8601 con zona horaria; se trunca al minuto; debe ser futura. |

- `201` → `Publication[]` en el orden de `account_ids` (sin repetidos). Todas `scheduled` si
  se indicó fecha, o `unscheduled` si no; sin overrides.
- `404 not_found`: el contenido no existe.
- `409 project_inactive` · `409 media_unavailable`.
- `422 validation_error`: cuerpo inválido, lista vacía o demasiado larga, fecha inválida, sin
  zona horaria o pasada (`field: "scheduled_at"`).
- Problemas por cuenta (se evalúan todas las cuentas y se informa de todas): un único error
  con `fields` = una entrada `{"field": "account_ids", "message": ...}` por cuenta
  problemática; el `code` es el más grave presente:
  `validation_error` (422, cuenta inexistente o de otro proyecto) >
  `account_inactive` (409) > `duplicate` (409). Mensajes por cuenta:

  | Problema | Mensaje |
  |----------|---------|
  | Inexistente | `Account {id} not found.` |
  | De otro proyecto | `Account {id} does not belong to this project.` |
  | Inactiva | `{Platform} @{handle} is inactive.` |
  | Con publicación activa | `{Platform} @{handle} already has an active publication of this content.` |

- **Orden de validación**: FastAPI valida primero el cuerpo de la petición (tipos, lista
  vacía o demasiado larga, `scheduled_at` mal formada o sin zona horaria, campos
  desconocidos). Por tanto, un cuerpo inválido puede devolver `422` antes de comprobar si el
  contenido existe (`404`) o el estado del proyecto (`409`). Las comprobaciones que dependen
  de la base (contenido, proyecto, archivo, fecha futura, cuentas) siguen el orden descrito
  en [research.md §6](../research.md#6-errores-de-la-creación-múltiple-fr-006-fr-007).
  Lo mismo aplica al `PATCH`.

```json
{
  "error": {
    "code": "duplicate",
    "message": "Some accounts already have an active publication of this content.",
    "fields": [
      {
        "field": "account_ids",
        "message": "Instagram @l4i4 already has an active publication of this content."
      }
    ]
  }
}
```

### `GET /api/publications/{publication_id}`

- `200` → `Publication`. · `404 not_found`.

### `PATCH /api/publications/{publication_id}`

Cuerpo con uno o más campos (los omitidos no cambian):

| Campo | Tipo | Efecto |
|-------|------|--------|
| `scheduled_at` | `string \| null` | Valor: asigna/cambia la fecha (→ `scheduled`). `null`: quita la fecha (→ `unscheduled`). |
| `title_override` | `string \| null` | Valor: override (máx. 200; vacío → `""`). `null`: usar el título global. |
| `description_override` | `string \| null` | Valor: override (máx. 5000; vacío → `""`). `null`: usar la descripción global. |
| `hashtags_override` | `string[] \| null` | Valor: override normalizado (máx. 30 × 100, sin espacios). `null`: usar los hashtags globales. |

Reglas:

- Solo si la fecha **cambia** a un valor no nulo se exige: fecha futura (`422`), proyecto
  activo (`409 project_inactive`), cuenta activa (`409 account_inactive`) y archivo
  disponible (`409 media_unavailable`).
- Quitar la fecha y editar overrides se permiten siempre que la publicación no esté
  cancelada.
- `updated_at` solo cambia si algo cambia efectivamente.
- `200` → `Publication`.
- `404 not_found` · `409 publication_cancelled` · `422 validation_error` (incluye cuerpo
  vacío y campos no editables como `content_id`, `account_id`, `project_id` o `status`).

### `POST /api/publications/{publication_id}/cancel`

Sin cuerpo. `unscheduled`/`scheduled` → `cancelled`, conservando fecha y overrides. Permitido
con proyecto o cuenta inactivos y con el archivo no disponible. Sobre una publicación ya
cancelada no hace nada.

- `200` → `Publication`. · `404 not_found`.

### `POST /api/publications/{publication_id}/reactivate`

Sin cuerpo. `cancelled` → `scheduled` si conserva una fecha futura; si no tiene fecha o ya
pasó → `unscheduled` con `scheduled_at: null`.

- `200` → `Publication`.
- `404 not_found`.
- `409 publication_not_cancelled` · `409 project_inactive` · `409 account_inactive` ·
  `409 media_unavailable` · `409 duplicate` (ya existe otra publicación activa para la misma
  pareja contenido + cuenta).

### `DELETE /api/publications/{publication_id}`

- `405 method_not_allowed`.

## Cambios en rutas existentes

Ninguno. `GET /api/contents/{id}`, `PATCH /api/contents/{id}` y las rutas de cuentas y
proyectos no cambian; la metadata efectiva de las publicaciones refleja los cambios del
contenido automáticamente.
