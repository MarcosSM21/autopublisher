# API Contract: publicación manual real en YouTube

**Feature**: `006-youtube-manual-publishing` | **Fecha**: 2026-10-07

Amplía la API REST bajo `/api`. Fechas en ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene tokens, cabeceras `Authorization`, la URI
de sesión resumible ni su `upload_id`, ni respuestas crudas de Google.

---

## Representaciones

### PublicationAttempt

```json
{
  "id": 7,
  "publication_id": 42,
  "platform": "youtube",
  "status": "running",
  "stage": "uploading",
  "started_at": "2026-10-07T18:00:00Z",
  "finished_at": null,
  "bytes_sent": 4194304,
  "total_bytes": 10485760,
  "progress": 0.4,
  "error": null,
  "outcome_determined": null,
  "requires_manual_review": false,
  "external_id": null,
  "external_url": null,
  "submitted": { "title": "...", "privacy_status": "private", "notify_subscribers": false },
  "details": {},
  "warnings": []
}
```

- `status`: `running` | `succeeded` | `failed`.
- `stage`: `preparing` | `uploading` | `final_chunk` | `done`. `final_chunk` se confirma en
  la base antes de enviar el último fragmento (write-ahead, research §5).
- `progress`: `0.0`–`1.0`, calculado.
- `error`: `null` o `{"code", "message"}` con los códigos de
  [research.md §6](../research.md#6-clasificación-de-errores-de-youtube-códigos-seguros).
- `requires_manual_review`: `status = "failed"` y `outcome_determined = false`. La UI pide
  revisar YouTube Studio identificando el vídeo por canal (`submitted.channel_title`,
  `submitted.channel_id`), título (`submitted.title`) y momento aproximado (`started_at`,
  `finished_at`).
- `external_id` / `external_url`: solo en `succeeded`. Nunca se conservan si el resultado no
  pudo persistirse (`result_not_saved`).
- `submitted` / `details` / `warnings`: [data-model.md §2](../data-model.md#2-publication_attempts-nueva-núcleo-genérico).

### Publication (ampliada)

`PublicationRead` de la Feature 004 añade:

```json
{
  "status": "published",
  "published_at": "2026-10-07T18:03:10Z",
  "latest_attempt": { "...": "PublicationAttempt" },
  "attempt_count": 1
}
```

- `status` admite además `publishing`, `published`, `failed`.
- `latest_attempt`: el intento más reciente o `null`.
- Para `published`, `latest_attempt.external_url` es el enlace `Open on YouTube`.

### YouTubePublicationOptions

```json
{
  "privacy_status": "private",
  "made_for_kids": null,
  "contains_synthetic_media": null,
  "notify_subscribers": false,
  "complete": false,
  "editable": true
}
```

- `made_for_kids` / `contains_synthetic_media`: `true` | `false` | `null` (sin declarar).
- `complete`: ambas declaraciones respondidas.
- `editable`: según la matriz de [research.md §13](../research.md#13-política-de-failed-edición-y-duplicados).

### PublishCheck

```json
{
  "eligible": true,
  "problems": [],
  "requires_remote_check": false,
  "summary": [
    { "label": "Title", "value": "Cybersecurity basics" },
    { "label": "Channel", "value": "Cyber Channel (UCxxxxxxxxxxxxxxxxxxxxxx)" },
    { "label": "Privacy", "value": "private" },
    { "label": "Notify subscribers", "value": "No" },
    { "label": "Made for kids", "value": "No" },
    { "label": "Altered or synthetic content", "value": "No" },
    { "label": "File", "value": "intro.mp4 (10.0 MB)" }
  ],
  "scheduled_at": "2026-10-08T09:00:00Z"
}
```

- Comprobaciones **locales, sin red**: estado, proyecto/cuenta activos, plataforma,
  conexión, configuración OAuth, tipo de contenido, archivo, metadata, opciones y ejecución
  en curso.
- `problems`: `[{"code", "message", "field"?}]` con los mismos códigos que devolvería
  `POST /publish`; con problemas, `eligible = false`.
- `summary`: pares etiqueta/valor que construye el adaptador para el diálogo de
  confirmación (spec FR-011). El frontend los muestra sin interpretarlos.
- `scheduled_at`: no nulo si la publicación está `scheduled`; la UI avisa de que se publica
  antes de esa hora.
- `requires_remote_check`: el último intento de la pareja contenido + cuenta requiere
  revisión manual; la UI muestra la casilla obligatoria.

---

## Endpoints

### `GET /api/publications/{id}/youtube-options`

`200` → `YouTubePublicationOptions`. Errores: `404 not_found`; `409 platform_not_supported`
si la cuenta no es YouTube.

### `PUT /api/publications/{id}/youtube-options`

Cuerpo (todos los campos obligatorios):

```json
{
  "privacy_status": "unlisted",
  "made_for_kids": false,
  "contains_synthetic_media": false,
  "notify_subscribers": false
}
```

`made_for_kids` y `contains_synthetic_media` aceptan `null` (volver a "sin declarar").
`200` → `YouTubePublicationOptions`. Idempotente.

Errores:

- `422 validation_error`: valor de privacidad desconocido, tipos inválidos, campos ausentes
  o extra;
- `404 not_found`; `409 platform_not_supported`;
- `409 publication_not_editable`: `publishing`, `published` o `cancelled`.

### `GET /api/publications/{id}/publish-check`

`200` → `PublishCheck`. Errores: `404 not_found`.

### `POST /api/publications/{id}/publish`

Cuerpo:

```json
{ "confirm_remote_checked": false }
```

Orden del preflight (el primero que falla responde). Los pasos 1–10 son locales
(`publisher.check`, los mismos que `publish-check`); 12–13 usan la red (`publisher.prepare`):

1. publicación existente → `404 not_found`;
2. estado `unscheduled` | `scheduled` | `failed` → si `publishing`:
   `409 publication_in_progress`; si no: `409 publication_not_eligible`;
3. proyecto activo → `409 project_inactive`; cuenta activa → `409 account_inactive`;
4. plataforma con publisher → `409 platform_not_supported`;
5. contenido de tipo vídeo → `409 content_not_video`;
6. archivo disponible y del tamaño esperado → `409 media_unavailable`;
7. metadata válida → `409 invalid_metadata` (con `fields`: `title`, `description`);
8. opciones completas → `409 youtube_options_incomplete` (con `fields`);
9. configuración OAuth → `503 oauth_not_configured`;
10. conexión `connected` → `409 not_connected` | `409 reconnect_required`;
11. revisión manual pendiente sin `confirm_remote_checked: true` → `409 remote_check_required`;
12. credenciales válidas o renovables → `409 reconnect_required` |
    `503 credential_store_unavailable` | `503 youtube_unavailable`;
13. canal efectivo = canal vinculado (`channels.list?mine=true`) → si no:
    `409 reconnect_required` (la conexión pasa a `reconnect_required`, Feature 005);
14. transición atómica a `publishing` + intento `running` → si pierde la carrera:
    `409 publication_in_progress`.

Respuesta `202 Accepted` → `Publication` con `status = "publishing"` y `latest_attempt` en
`running`/`preparing`. La subida continúa en segundo plano; la interfaz sondea
`GET /api/publications/{id}`.

Ningún error de esta lista cambia el estado ni crea una sesión de subida.

### `GET /api/publications/{id}/attempts`

`200` → `PublicationAttempt[]`, del más reciente al más antiguo. Errores: `404 not_found`.

### Endpoints existentes con comportamiento nuevo

| Endpoint | Cambio |
|----------|--------|
| `GET /api/projects/{id}/publications` | Incluye los estados nuevos. Orden: `publishing`, `failed`, `scheduled` (fecha ↑), `unscheduled` (creación ↑), `published` (`published_at` ↓), `cancelled` (`updated_at` ↓), desempate por `id` |
| `GET /api/publications/{id}` | Incluye `published_at`, `latest_attempt`, `attempt_count` |
| `PATCH /api/publications/{id}` | `409 publication_not_editable` en `publishing`/`published`; en `failed`, solo overrides (cambiar `scheduled_at` → `409 publication_not_editable`) |
| `POST /api/publications/{id}/cancel` | `409 publication_not_editable` en `publishing`/`published` |
| `POST /api/contents/{id}/publications` | `publishing` y `failed` cuentan como activas para duplicados; `published` no |
| `POST /api/publications/{id}/reactivate` | Igual criterio de duplicados |
| `POST /api/accounts/{id}/youtube-connection/authorize` | `409 publication_in_progress` si la cuenta tiene una publicación `publishing` |
| `POST /api/accounts/{id}/youtube-connection/disconnect` | Ídem |

## Códigos de error nuevos

| Código | HTTP | Cuándo |
|--------|------|--------|
| `publication_not_eligible` | 409 | Estado que no admite `Publish now` |
| `publication_in_progress` | 409 | Ya hay una ejecución activa (publicación o cuenta) |
| `publication_not_editable` | 409 | Edición/cancelación no permitida en el estado actual |
| `content_not_video` | 409 | El contenido es una imagen |
| `invalid_metadata` | 409 | Título o descripción final no válidos para YouTube |
| `youtube_options_incomplete` | 409 | Made for Kids o synthetic media sin declarar |
| `remote_check_required` | 409 | Falta confirmar la revisión de YouTube Studio tras un resultado ambiguo |

Los códigos existentes (`project_inactive`, `account_inactive`, `media_unavailable`,
`platform_not_supported`, `not_connected`, `reconnect_required`, `oauth_not_configured`,
`credential_store_unavailable`, `youtube_unavailable`) se reutilizan.
