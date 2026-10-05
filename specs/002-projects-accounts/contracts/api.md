# API Contract: proyectos y cuentas

**Feature**: `002-projects-accounts` | **Fecha**: 2026-10-05

API REST JSON bajo el prefijo `/api`. Sin autenticación (FR-026). Todas las fechas en
ISO 8601 UTC (p. ej. `"2026-10-05T10:15:00Z"`). `GET /health` se mantiene sin cambios
(ver `specs/001-technical-bootstrap/contracts/health.md`).

No existe ninguna ruta `DELETE` (FR-008, FR-017); un `DELETE` sobre estas rutas devuelve
`405 method_not_allowed`.

## Representaciones

### Project

```json
{
  "id": 1,
  "name": "L4i4",
  "description": null,
  "is_active": true,
  "created_at": "2026-10-05T10:15:00Z",
  "updated_at": "2026-10-05T10:15:00Z"
}
```

### Account

```json
{
  "id": 7,
  "project_id": 1,
  "platform": "instagram",
  "handle": "l4i4",
  "display_name": "L4i4 Official",
  "is_active": true,
  "created_at": "2026-10-05T10:16:00Z",
  "updated_at": "2026-10-05T10:16:00Z"
}
```

`platform` ∈ `youtube | instagram | tiktok | x | threads | telegram`. `handle` se devuelve
sin `@` inicial.

### Error

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request contains invalid data.",
    "fields": [
      { "field": "name", "message": "Name must not be empty." }
    ]
  }
}
```

| `code` | HTTP | Cuándo |
|--------|------|--------|
| `validation_error` | 422 | Cuerpo inválido: campo obligatorio ausente o vacío, longitud excedida, plataforma no reconocida, campo desconocido o no editable, tipo incorrecto. `fields` lista cada problema. |
| `not_found` | 404 | El proyecto o la cuenta del path no existe, o la ruta no existe. `fields` vacío. |
| `duplicate` | 409 | Nombre de proyecto o (plataforma, handle) en el proyecto ya en uso. `fields` indica el campo. |
| `project_inactive` | 409 | Se intenta añadir una cuenta a un proyecto inactivo. |
| `method_not_allowed` | 405 | Método no soportado en una ruta existente (p. ej. cualquier `DELETE`). |
| `internal_error` | 500 | Error inesperado del servidor o del almacenamiento (incluida cualquier violación de integridad que no sea de unicidad). Mensaje neutro: "An unexpected error occurred. Please try again." |

Los mensajes son legibles para el usuario (en inglés, como el resto de la interfaz) y nunca
incluyen trazas, SQL ni rutas internas. Los errores de longitud indican el máximo permitido
(p. ej. "Must be at most 100 characters."). Todas las respuestas de error, incluidas `404`
de rutas inexistentes, `405` y `500`, usan este mismo formato.

## Proyectos

### `GET /api/projects`

Lista todos los proyectos, activos e inactivos, ordenados por nombre (sin distinguir
mayúsculas).

- `200` → `Project[]` (array vacío si no hay ninguno).

### `POST /api/projects`

Cuerpo:

| Campo | Tipo | Obligatorio | Reglas |
|-------|------|-------------|--------|
| `name` | string | sí | Recortado; 1–100 caracteres; único sin distinguir mayúsculas |
| `description` | string \| null | no | Recortado; ≤ 1000; vacío → `null` |

- `201` → `Project` (activo, `created_at == updated_at`).
- `422 validation_error`, `409 duplicate`.

### `GET /api/projects/{project_id}`

- `200` → `Project`.
- `404 not_found`.

### `PATCH /api/projects/{project_id}`

Cuerpo con uno o más de los campos siguientes (los omitidos no cambian):

| Campo | Tipo | Reglas |
|-------|------|--------|
| `name` | string | Mismas reglas que en la creación; no admite `null` |
| `description` | string \| null | `null` o vacío borran la descripción |
| `is_active` | boolean | Activa o desactiva el proyecto; no afecta a sus cuentas |

- `200` → `Project` actualizado. Si ningún valor cambia de forma efectiva, `updated_at` no
  se modifica (FR-018).
- `404 not_found`, `422 validation_error` (incluye cuerpo vacío `{}` y campos no
  editables), `409 duplicate`.

## Cuentas

### `GET /api/projects/{project_id}/accounts`

Lista las cuentas del proyecto, activas e inactivas, ordenadas por `platform` y después por
`handle` (sin distinguir mayúsculas). Funciona también si el proyecto está inactivo.

- `200` → `Account[]`.
- `404 not_found` si el proyecto no existe.

### `POST /api/projects/{project_id}/accounts`

Cuerpo:

| Campo | Tipo | Obligatorio | Reglas |
|-------|------|-------------|--------|
| `platform` | string | sí | Uno de los valores reconocidos |
| `handle` | string | sí | Recortado; se elimina un `@` inicial; 1–100 caracteres |
| `display_name` | string \| null | no | Recortado; ≤ 100; vacío → `null` |

- `201` → `Account` (activa).
- `404 not_found` (proyecto inexistente; no se crea nada), `409 project_inactive`,
  `409 duplicate` (misma plataforma y handle en el proyecto, aunque la existente esté
  inactiva), `422 validation_error`.

### `PATCH /api/accounts/{account_id}`

Cuerpo con uno o más de:

| Campo | Tipo | Reglas |
|-------|------|--------|
| `handle` | string | Mismas reglas que en la creación |
| `display_name` | string \| null | `null` o vacío lo borran |
| `is_active` | boolean | Activa o desactiva la cuenta |

`platform` y `project_id` no son editables: enviarlos devuelve `422 validation_error`.

- `200` → `Account` actualizada; `updated_at` solo cambia si hay modificación efectiva.
- `404 not_found`, `422 validation_error`, `409 duplicate`.
- Permitido aunque el proyecto de la cuenta esté inactivo.
