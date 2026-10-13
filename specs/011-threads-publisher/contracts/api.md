# API Contract: publicación real de texto, imagen y vídeo en Threads

**Feature**: `011-threads-publisher` | **Fecha**: 2026-10-13

Amplía la API REST bajo `/api`. Fechas en ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene tokens de Threads, cabeceras
`Authorization`, credenciales o configuración del proveedor de media delivery, URLs
temporales (firmadas o no), claves de objeto temporales ni respuestas crudas de Meta.

---

## 1. Cambios neutrales en publicaciones

### `PublicationRead` (todas las plataformas)

- `content_id`: `int | null` — `null` en publicaciones sin media (hoy solo Threads texto).
- `content`: `PublicationContentSummary | null`.
- `title`, `description`, `hashtags`: sin `Content`, los overrides de la publicación o
  `null`/`null`/`[]`.
- YouTube e Instagram siempre devuelven `content_id` y `content` como hasta ahora.

### `POST /api/projects/{project_id}/text-publications` (nuevo)

Crea una publicación **sin `Content`** por cuenta, todo o nada.

Request:

```json
{
  "account_ids": [7],
  "description": "Validation post — please ignore https://example.com",
  "hashtags": ["autopublisher"],
  "scheduled_at": null,
  "auto_publish_enabled": false
}
```

- `account_ids`: 1–50, deduplicados; cada cuenta del proyecto, activa y de una plataforma
  cuyo publisher acepta publicaciones sin media.
- `description`: texto (máx. 5000, como `description_override`); se guarda en
  `description_override`. `hashtags`: normalizados como `hashtags_override`.
- `scheduled_at` / `auto_publish_enabled`: mismas reglas que
  `POST /api/contents/{id}/publications`.
- Los límites de Threads **no** se validan aquí (se muestran en `threads-options` y en el
  preflight), igual que el caption de Instagram.

Respuestas:

| Código | Cuándo |
|---|---|
| `201` + `list[PublicationRead]` | Creadas (`content_id = null`). |
| `404` | Proyecto inexistente. |
| `409 project_inactive` / `409 account_inactive` | Como en la creación existente. |
| `422 validation_error` | Cuenta inexistente o de otro proyecto; fecha pasada; `auto_publish_enabled` sin fecha. |
| `422 text_publication_not_supported` | Alguna cuenta es de una plataforma que no admite publicaciones sin media (YouTube, Instagram, sin publisher…); `fields[]` por cuenta. |

### Otros endpoints existentes

| Endpoint | Cambio |
|---|---|
| `GET /api/projects/{id}/publications` | Incluye publicaciones sin `Content` (`content = null`), en el orden de la cola. |
| `PATCH /api/publications/{id}` | Sin cambios de forma. En publicaciones sin `Content`, `description_override`/`hashtags_override` son el texto. Programar o armar no comprueba archivo cuando no hay `Content`. |
| `POST /api/publications/{id}/cancel` / `reactivate` | `reactivate` no comprueba duplicados ni archivo cuando no hay `Content`. |
| `GET /api/publications/{id}/publish-check` | Nuevo problema neutral `publication_media_required` (409) si la publicación no tiene `Content` y su plataforma no lo admite. `requires_remote_check` sin `Content` se calcula con los intentos de la propia publicación. |

---

## 2. Opciones y texto de Threads

### `GET /api/publications/{id}/threads-options`

Sin red. `409 platform_not_supported` si la cuenta no es Threads.

```json
{
  "media_kind": "text",
  "text": "Validation post — please ignore https://example.com\n\n#autopublisher",
  "text_length": 66,
  "text_links": 1,
  "alt_text": null,
  "editable": true,
  "media_delivery_required": false,
  "media_delivery_configured": true,
  "problems": [],
  "limits": {
    "text_characters": 500,
    "text_links": 5,
    "alt_text_characters": 1000
  }
}
```

- `media_kind`: `"text" | "image" | "video" | null` (`null` si el `Content` no es soportado).
- `text`: texto final exacto que se enviará (FR-018/FR-020). `text_length` usa el conteo
  conservador de research §4.
- `alt_text`: `null` en texto.
- `media_delivery_required`: `false` en texto.
- `problems`: problemas locales de Threads (sin los de conexión), mismo formato que
  `publish-check`.

### `PUT /api/publications/{id}/threads-options`

Request: `{"alt_text": "A red square on a white background"}` (`null` o vacío = sin alt
text). Respuesta: la misma forma que el `GET`.

| Código | Cuándo |
|---|---|
| `409 platform_not_supported` | Cuenta no Threads. |
| `409 publication_not_editable` / `publication_cancelled` | Estado no editable (reglas existentes). |
| `422 threads_option_not_applicable` | `alt_text` en una publicación de texto. |
| `422 threads_alt_text_invalid` | `alt_text` > 1000 caracteres. |

---

## 3. Ejecución (endpoints genéricos existentes)

| Endpoint | Threads |
|---|---|
| `GET /api/publications/{id}/publish-check` | Problemas de Threads (tabla 4) y `summary`. Puede reconciliar antes un último intento ambiguo. |
| `POST /api/publications/{id}/publish` | 202 + `PublicationRead`; mismos errores de preflight y `remote_check_required`. |
| `GET /api/publications/{id}/attempts` | `platform = "threads"`. |
| Scheduler / automatización | Sin cambios: mismo servicio, origen `scheduled`. |

`summary` de `publish-check`:

```json
[
  {"label": "Post type", "value": "Text"},
  {"label": "Threads account", "value": "cyber.studio (2584...)"},
  {"label": "Text", "value": "<texto final exacto o '(empty)'>"}
]
```

Imagen: `"Post type": "Image"`, más `"Alt text"` (o `None`) y `"File"`
(`"poster.webp (1.2 MB) → sent as PNG"` si hubo conversión). Vídeo: `"Post type": "Video"`,
`"Alt text"`, `"File"`.

### `PublicationAttempt` de Threads

- `stage`: texto `preparing` → `processing` → `finalizing` → `done`; imagen/vídeo con
  `uploading` (bytes reales) antes de `processing`.
- `progress`: regla genérica existente (`1.0` solo `succeeded`; texto `0.0` hasta entonces).
- `external_id`: Threads post ID; `external_url`: permalink oficial o `null` (nunca uno
  construido). Si `threads_publish` devolvió el post ID pero el permalink no pudo obtenerse
  (fallo temporal, ausente u omitido por Meta): `status = "succeeded"`, publicación
  `published`, `external_id` = post ID, `external_url = null` y aviso
  `permalink_unavailable`; sin `Open on Threads`. `null`/`null` + aviso
  `remote_identity_unavailable` cuando solo el container confirmó la publicación.
- `submitted`: ver [data-model.md](../data-model.md) §4.
- `submitted.delegated_checks` (vídeo): requisitos no verificados localmente y delegados a
  Meta (`closed_gop`, `edit_lists` y, si `ffprobe` no los reporta, `video_bitrate`,
  `audio_bitrate`, `progressive_scan`).
- `warnings[].code`: `remote_identity_unavailable`, `permalink_unavailable`,
  `quota_unavailable`, `temporary_media_cleanup_failed`. Un aviso nunca cambia `status`.

### Reconciliación (FR-040)

Igual que Instagram: si la publicación está `failed` y su último intento es ambiguo,
`publish-check` y `publish` hacen primero **una** lectura del container original (solo si el
run alcanzó `publishing` con `container_id`). `PUBLISHED` → publicación `published`, intento
`succeeded` sin identidad remota y con aviso; cualquier otro resultado → sin cambios
(`requires_remote_check = true`). Nunca llama a `threads_publish`, nunca crea containers y
nunca lista posts.

---

## 4. Códigos de error y avisos de Threads

| Código | HTTP (preflight) | Dónde |
|---|---|---|
| `threads_not_connected` | 409 | check / prepare |
| `threads_reconnect_required` | 409 | check / prepare / ejecución |
| `threads_identity_mismatch` | 409 | prepare (Feature 010) |
| `threads_unavailable` | 503 | prepare / ejecución |
| `credential_store_unavailable` | 503 | prepare / ejecución |
| `publication_media_required` | 409 | check genérico |
| `threads_media_unsupported` | 409 | check |
| `media_unavailable` | 409 | check |
| `threads_text_invalid` | 409 (`field: "text"`) | check / container |
| `threads_alt_text_invalid` | 409 (`field: "alt_text"`) | check (valor antiguo) |
| `threads_image_incompatible` | 409 (`field: "media"`) | check / prepare |
| `threads_video_incompatible` | 409 (`field: "media"`) | check: requisito incumplido o dato obligatorio indeterminado |
| `threads_media_unverifiable` | 409 | check (sin ffprobe) |
| `media_delivery_not_configured` | 503 | check / ejecución |
| `threads_publishing_limit_reached` | 409 | prepare / ejecución |
| `threads_unexpected_response` | 502 | prepare: cuota con forma no entendida (posible cambio de contrato de Meta) |
| `threads_already_published` | 409 | prepare |
| `media_delivery_failed` | — | ejecución, determinado |
| `threads_container_failed` | — | ejecución, determinado |
| `threads_media_fetch_failed` | — | ejecución, determinado |
| `threads_media_rejected` | — | ejecución, determinado |
| `threads_processing_failed` | — | ejecución, determinado |
| `threads_processing_timeout` | — | ejecución, determinado |
| `threads_container_expired` | — | ejecución, determinado |
| `threads_publish_failed` | — | ejecución, determinado |
| `threads_publish_uncertain` | — | ejecución, **ambiguo** (`requires_manual_review`) |
| `interrupted`, `internal_error`, `result_not_saved` | — | genéricos existentes |

Mensajes en inglés, sin respuestas crudas de Meta. `threads_publish_uncertain` indica la
cuenta, la hora UTC del write-ahead y el inicio del texto para la revisión manual.

---

## 5. Contrato con Meta (gateway, resumen)

Detalle en [research.md](../research.md) §1, §9–§13. Métodos nuevos de `ThreadsGateway`:

| Método | Llamada | Devuelve |
|---|---|---|
| `create_container(user_id, token, *, media_type, text, image_url, video_url, alt_text)` | `POST /{user_id}/threads`, cuerpo `application/x-www-form-urlencoded` (UTF-8), sin query | container ID |
| `container_status(container_id, token)` | `GET /{container_id}?fields=id,status,error_message` | `(status, error_message)` normalizados |
| `publish(user_id, container_id, token)` | `POST /{user_id}/threads_publish`, `creation_id` y `access_token` en el mismo cuerpo de formulario | post ID |
| `published_media(media_id, token)` | `GET /{media_id}?fields=id,permalink,timestamp` | `(permalink \| None, timestamp \| None)` |
| `publishing_limit(user_id, token)` | `GET /{user_id}/threads_publishing_limit?fields=quota_usage,config` | `(usage, total, duration)`; forma no entendida → `ThreadsUnexpectedResponse` |

Errores: las excepciones semánticas existentes (`ThreadsUnavailable`, `ThreadsTokenInvalid`,
`ThreadsPermissionDenied`, `ThreadsRejected`, `ThreadsUnexpectedResponse`), más un indicador
seguro en `ThreadsRejected` para `THREADS_API__LINK_LIMIT_EXCEEDED` (sin texto de Meta).
