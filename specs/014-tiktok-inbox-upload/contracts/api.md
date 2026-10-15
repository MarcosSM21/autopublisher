# API Contract: TikTok Upload to Inbox

**Feature**: `014-tiktok-inbox-upload` | **Fecha**: 2026-10-15

Cambios sobre [013 contracts/api.md](../../013-tiktok-direct-post/contracts/api.md) y los
endpoints genéricos. Fechas ISO 8601 UTC. Formato de error existente
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal (sin cambios)**: ninguna respuesta contiene tokens, client secret,
`Authorization`, `upload_url` (ni partes), `publish_id` ni respuestas crudas de TikTok.

---

## 1. Estado genérico `awaiting_user_action`

Todas las lecturas de publicaciones (`PublicationRead`, cola, listas) pueden devolver
`"status": "awaiting_user_action"` con `published_at: null`. Para ese estado:

| Endpoint existente | Respuesta |
|---|---|
| `POST /api/publications/{id}/publish` | 409 `publication_not_eligible` |
| `PATCH /api/publications/{id}` (metadata, fecha) | 409 `publication_not_editable` |
| `POST /api/publications/{id}/cancel` | 409 `publication_not_editable` |
| `PUT /api/publications/{id}/tiktok-options` | 409 `publication_not_editable` |
| armado de auto-publish | 409 (no está `scheduled`) |
| `GET /api/publications/{id}/publish-check` | `eligible: false`, problema `publication_not_eligible` |
| crear otra publicación del mismo `Content` y cuenta | 409 `duplicate` (sigue activa) |

## 2. `POST /api/publications/{id}/check-status` (nuevo, genérico)

Una sola consulta de solo lectura a la plataforma para una publicación en
`awaiting_user_action`. Nunca crea intentos ni modifica el intento de entrega.

Cuerpo: vacío. Respuesta 200:

```json
{
  "result": "awaiting",
  "message": "TikTok is still waiting for you to open the inbox notification.",
  "checked_at": "2026-10-15T18:04:12Z",
  "publication": { "...": "PublicationRead", "status": "awaiting_user_action" }
}
```

- `result`: `awaiting` (sigue `awaiting_user_action`) | `published` (→ `published`,
  `published_at` = momento de la observación) | `failed` (→ `failed`; `message` seguro con el
  motivo).

Errores (estado intacto):

| Código | HTTP | Cuándo |
|---|---|---|
| `not_found` | 404 | publicación inexistente |
| `publication_not_awaiting` | 409 | el estado no es `awaiting_user_action` |
| `tiktok_unavailable` | 503 | red / 5xx de TikTok |
| `tiktok_rate_limited` | 503 | 429 |
| `tiktok_status_unavailable` | 409 | `invalid_publish_id` o `token_not_authorized_for_specified_publish_id` (p. ej. otra cuenta conectada) |
| `tiktok_not_connected` / `tiktok_reconnect_required` | 409 | conexión no utilizable (reglas 012) |
| `platform_not_supported` | 409 | el publisher no tiene seguimiento (defensivo) |

## 3. `GET/PUT /api/publications/{id}/tiktok-options` (ampliado)

`TikTokPublicationOptionsWrite` gana el campo **obligatorio** `mode`:

```json
{ "mode": "INBOX_UPLOAD", "privacy_level": null, "allow_comment": false, "allow_duet": false,
  "allow_stitch": false, "commercial_disclosure_enabled": false, "brand_organic_toggle": false,
  "brand_content_toggle": false, "is_aigc": null }
```

- `mode`: `null` | `"DIRECT_POST"` | `"INBOX_UPLOAD"`. Las opciones de Direct Post se guardan
  igual en ambos modos y solo se validan en `DIRECT_POST`.

`TikTokPublicationOptionsRead` gana:

```json
{
  "mode": "INBOX_UPLOAD",
  "modes": {
    "DIRECT_POST": { "available": true, "reason": null },
    "INBOX_UPLOAD": { "available": false,
      "reason": "Upload to Inbox needs the video.upload permission. Reconnect the TikTok account." }
  },
  "problems": [ { "code": "tiktok_upload_permission_missing", "message": "...", "field": "mode" } ]
}
```

- Con `mode = null`: problema `tiktok_mode_required` (`field: "mode"`).
- Con `INBOX_UPLOAD`: `problems` solo incluye conexión/capacidad/vídeo; `declaration`,
  `consent`, `caption` siguen presentes (informativos para Direct Post) pero no generan
  problemas.
- `GET /tiktok-creator-info` no se llama desde la UI en modo Inbox (sin cambios de contrato).
- `POST /tiktok-consent` en modo Inbox → 409 `tiktok_consent_not_applicable`.

## 4. `GET /api/publications/{id}/tiktok-delivery` (nuevo, sin red)

Estado de entrega Inbox para el panel TikTok (derivado; ver data-model).

```json
{
  "mode": "INBOX_UPLOAD",
  "state": "ready",
  "delivered_at": "2026-10-15T18:01:40Z",
  "user_published_at": null,
  "after_delivery_failure": null,
  "instruction": "Open your TikTok inbox to review, edit and publish the video.",
  "can_check_status": true
}
```

- `state`: `not_sent` | `scheduled` | `uploading` | `processing` | `ready` | `published` |
  `failed`; `null` si el modo no es `INBOX_UPLOAD` y no hay run de Upload to Inbox.
  `not_sent` es un valor derivado de la API (nada enviado todavía) y **no** se presenta como
  etiqueta de estado en la UI; los estados visibles son los de spec FR-034.
- `after_delivery_failure`: `null` o `{"code", "message"}` cuando TikTok informó `FAILED` tras
  la entrega (el intento de entrega sigue `succeeded`).
- Solo `can_check_status = true` en `ready`.

## 5. Intentos (`GET /api/publications/{id}/attempts`, sin cambio de forma)

- Intento Inbox entregado: `status: "succeeded"`, `external_id: null`, `external_url: null`,
  `details: {"tiktok_mode": "INBOX_UPLOAD", "delivered_to_inbox": true}`.
- `submitted`: `{"mode": "INBOX_UPLOAD", "source_info": {...}, "video": {...}}`; sin
  `post_info`.
- Fallos con los códigos de research §9 (p. ej. `tiktok_too_many_pending_shares`,
  `tiktok_upload_permission_missing`).

## 6. Conexión TikTok (`GET /api/accounts/{id}/tiktok-connection`, ampliado)

`permissions` gana `capabilities`:

```json
"permissions": {
  "granted": ["user.info.basic", "video.publish"],
  "source": "token_exchange",
  "confirmed_at": "2026-10-14T09:00:00Z",
  "capabilities": { "direct_post": true, "inbox_upload": false }
}
```

- `Connect`/`Reconnect` solicitan `user.info.basic,video.publish,video.upload`.
- Callback sin los tres → intento OAuth `failed` con `tiktok_permission_missing` ("TikTok did
  not grant every requested permission (missing: video.upload). Connect again and grant every
  permission."); la conexión previa (si existía) queda exactamente igual.
- `status` de la conexión no cambia por la falta de `video.upload`.

## 7. Frontend (contrato de UI)

- `PUBLICATION_STATUS_LABELS.awaiting_user_action = "Awaiting your action"`; para TikTok,
  `publicationStatusLabel` devuelve **"Ready in TikTok"**.
- Panel TikTok: selector de modo obligatorio; en Inbox, textos de research §12; botón
  **Send to TikTok** (mismo `POST /publish`); `Check status` → `POST /check-status`.
- Historial: "Delivered to TikTok inbox" (intento) separado de "Published in TikTok" / "Failed
  in TikTok" (estado final de la publicación).
