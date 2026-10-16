# API Contract: Feature 017

Formato de error común sin cambios estructurales:
`{"error": {"code": str, "message": str, "fields": [{"field": str, "message": str, "account_id"?: int}]}}`.
`account_id` es **nuevo y opcional** (aditivo).

---

## POST /api/contents/{content_id}/publications (ampliado, retrocompatible)

### Request

```json
{
  "account_ids": [11, 12, 13],
  "scheduled_at": "2026-11-01T18:00:00+01:00",
  "auto_publish_enabled": false,

  "description_override": "Common caption",
  "hashtags_override": ["shorts", "ai"],

  "targets": {
    "11": { "title_override": "YouTube title", "description_override": "Longer YT text" },
    "13": { "hashtags_override": [] }
  }
}
```

| Campo | Requerido | Notas |
|---|---|---|
| `account_ids` | sí | sin cambios (1..50; repetidos se cuentan una vez) |
| `scheduled_at` | no | sin cambios; null/omitido → `UNSCHEDULED` |
| `auto_publish_enabled` | no | sin cambios (compatibilidad); la UI de Distribute no lo envía |
| `title_override` | no | común; aceptado, la UI no lo envía |
| `description_override` | no | común |
| `hashtags_override` | no | común |
| `targets` | no | objeto `{ "<account_id>": PublicationOverrides }`; claves ⊆ `account_ids` |

`PublicationOverrides` = `{title_override?, description_override?, hashtags_override?}`,
`extra` prohibido (no admite opciones de plataforma).

**Semántica por campo**: omitido ≡ `null` = sin override en ese nivel; `""`/`[]` = override
explícito vacío. Precedencia: destino > común > Content.

Un request válido antes de la Feature 017 produce exactamente el mismo resultado.

### Response 201

Sin cambios: `PublicationRead[]`, una por cuenta, en el orden de `account_ids`.

### Errores (nada se crea en ningún caso)

| Situación | Status | code | fields |
|---|---|---|---|
| Override común inválido | 422 | `validation_error` | `[{field: "description_override", …}]` |
| Override de destino inválido | 422 | `validation_error` | `[{field: "targets.12.title_override", …}]` |
| Campo desconocido en un destino | 422 | `validation_error` | `[{field: "targets.12.privacy", message: "This field cannot be set."}]` |
| Clave de `targets` no numérica | 422 | `validation_error` | `[{field: "targets.x", …}]` |
| Clave de `targets` no seleccionada | 422 | `validation_error` | `[{field: "targets.12", message: "This destination is not selected."}]` |
| Cuenta no encontrada / de otro proyecto | 422 | `validation_error` | `[{field: "account_ids", account_id: 12, …}]` |
| Cuenta inactiva | 409 | `account_inactive` | `[{field: "account_ids", account_id: 12, …}]` |
| Publication activa del par | 409 | `duplicate` | `[{field: "account_ids", account_id: 12, …}]` |
| No armable (`auto_publish_enabled`) | 409 | código del publisher | `[{field: "account_ids", account_id: 12, …}]` |
| Carrera en el commit | 409 | `duplicate` | `[]` (sin cambios) |
| Proyecto inactivo / archivo no disponible / fecha pasada | sin cambios | | |

Cambio transversal en `_handle_validation_error`:

- **Errores del body** (`loc` empieza por `"body"`): `field` une con `.` los segmentos de
  texto que siguen a `"body"`, hasta el primer índice, descartando `[key]`. Ejemplos:
  `targets.11.title_override`, `targets.11`. Para los modelos planos existentes el `field`
  resultante no cambia (`description_override`, `hashtags_override`, `account_ids`…).
- **Errores de `path` y `query`**: sin cambios, `field: "path"` / `field: "query"`. Nunca
  `path.content_id` ni `query.code`.
- **`account_id`**: en los 422 generados con `field_errors` se guarda en el `ctx` del error y
  el handler lo copia a la entrada de `fields`; en los 409 va directamente en `fields`.

---

## Presets de destinos

### DistributionPresetRead

```json
{
  "id": 3,
  "project_id": 1,
  "name": "Short video",
  "account_ids": [11, 12, 13],
  "created_at": "2026-10-16T10:00:00Z",
  "updated_at": "2026-10-16T10:00:00Z"
}
```

`account_ids` ordenados por id ascendente.

### GET /api/projects/{project_id}/distribution-presets

200 → `DistributionPresetRead[]` ordenados por `name_key`. 404 si el proyecto no existe.

### POST /api/projects/{project_id}/distribution-presets

```json
{ "name": "Short video", "account_ids": [11, 12, 13] }
```

- `name`: obligatorio, recortado, 1..100.
- `account_ids`: 1..50, sin repetidos; todas del proyecto (pueden estar inactivas).

201 → `DistributionPresetRead`.

| Situación | Status | code | fields |
|---|---|---|---|
| Nombre vacío / largo | 422 | `validation_error` | `name` |
| `account_ids` vacío, >50 o con repetidos | 422 | `validation_error` | `account_ids` |
| Cuenta inexistente o de otro proyecto | 422 | `validation_error` | `[{field: "account_ids", account_id, …}]` |
| Nombre duplicado en el proyecto | 409 | `duplicate` | `name` |
| Proyecto inexistente | 404 | `not_found` | |

### PATCH /api/distribution-presets/{preset_id}

```json
{ "name": "Shorts", "account_ids": [11, 13] }
```

Ambos opcionales (al menos uno, patrón `UpdateModel`); `account_ids` reemplaza el conjunto.
Mismas validaciones y errores que POST. 200 → `DistributionPresetRead`. 404 si no existe.

### DELETE /api/distribution-presets/{preset_id}

204 sin cuerpo. 404 si no existe. No afecta a cuentas ni Publications.

---

## Endpoints reutilizados sin cambios

- `GET /api/contents/{id}/usage` — publicaciones del Content (estado + cuenta) para
  deshabilitar destinos.
- `GET /api/projects/{id}/accounts`, `GET /api/projects/{id}/publications`.
- `GET /api/publications/{id}/publish-check`, `POST /api/publications/{id}/publish`.
- `PATCH /api/publications/{id}` (auto-publish, fecha, overrides).
- Endpoints de opciones de YouTube / Instagram / Threads / TikTok y consentimiento de TikTok.
