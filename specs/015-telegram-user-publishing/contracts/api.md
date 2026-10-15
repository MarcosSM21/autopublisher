# API Contract: Telegram User Account & Publishing

**Feature**: `015-telegram-user-publishing` | **Fecha**: 2026-10-15

Amplía la API REST bajo `/api`. Fechas ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene la sesión de Telegram, auth keys,
`api_hash`, `access_hash`, códigos de login, contraseñas 2FA, el teléfono completo ni
respuestas crudas de Telegram.

Errores comunes de todas las rutas `telegram-connection`:

| Código | Cuándo |
|---|---|
| `404` | Cuenta inexistente. |
| `409 platform_not_supported` | La cuenta no es de plataforma `telegram` (código existente). |
| `503 telegram_not_configured` | Falta o es inválido `telegram-app.json` (rutas que contactan Telegram). |
| `503 credential_store_unavailable` | Almacén seguro no disponible. |
| `503 telegram_unavailable` | Red/Telegram no disponible. |
| `429 telegram_rate_limited` | FloodWait; el mensaje incluye los segundos. |
| `409 telegram_busy` | Otra operación de esa cuenta Telegram está usando la sesión (publicación, Verify, canales, Disconnect o login). No aplica a `GET .../telegram-connection`. |

---

## `TelegramConnectionRead`

```json
{
  "account_id": 12,
  "configured": true,
  "status": "connected",
  "identity": { "telegram_user_id": "123456789", "display_name": "Marcos S.", "username": "marcos" },
  "channel": { "channel_id": "1987654321", "title": "My channel", "username": "mychannel" },
  "channel_change_blocked": false,
  "login": null,
  "connected_at": "2026-10-15T10:00:00Z",
  "last_verified_at": "2026-10-15T10:00:05Z",
  "rate_limited_until": null
}
```

- `status`: `not_connected` \| `connected` \| `reconnect_required`.
- `identity`: `null` si `not_connected`. `channel`: `null` si no hay canal elegido.
- `channel_change_blocked`: `true` si hay publicaciones de la cuenta en `scheduled` o
  `publishing`.
- `login`: `null` o `{"step": "code" | "password", "phone_hint": "+34 ••• •• 12", "expires_at": "..."}`.

## `GET /api/accounts/{account_id}/telegram-connection`

`200 TelegramConnectionRead`. Sin red.

## Login

### `POST /api/accounts/{account_id}/telegram-connection/login/start`

Request `{"phone": "+34600000000"}` → `200 TelegramConnectionRead` con `login.step = "code"`.
Reemplaza cualquier login pendiente de la cuenta.

| Código | Cuándo |
|---|---|
| `422 validation_error` | Teléfono vacío o con formato no válido (`+` y dígitos). |
| `422 telegram_login_invalid` | Telegram rechaza el número (inválido, baneado). |

### `POST .../telegram-connection/login/code`

Request `{"code": "12345"}` → `200 TelegramConnectionRead`:
- con `login.step = "password"` si la cuenta tiene 2FA;
- con `status = "connected"` y `login = null` si no.

### `POST .../telegram-connection/login/password`

Request `{"password": "..."}` → `200 TelegramConnectionRead` (`connected`).

Errores de `code` / `password`:

| Código | Cuándo |
|---|---|
| `409 telegram_login_not_pending` | No hay login pendiente, expiró, o el paso no corresponde. |
| `422 telegram_login_invalid` | Código incorrecto/caducado o contraseña incorrecta. |
| `409 telegram_identity_mismatch` | Reconexión con otra cuenta de Telegram; desconectar primero. |

### `POST .../telegram-connection/login/cancel`

`200 TelegramConnectionRead`. Descarta el login pendiente (idempotente).

## `POST .../telegram-connection/verify`

`200 TelegramConnectionRead`. Comprobación real. Si la sesión ya no es válida responde
`200` con `status = "reconnect_required"`. `409 telegram_not_connected` sin conexión.

## `POST .../telegram-connection/disconnect`

`200 TelegramConnectionRead` (`not_connected`). Revoca la sesión en Telegram y luego borra el
secreto y la fila (research §6). Idempotente sin conexión. Con Telegram inalcanzable:
`503 telegram_unavailable` y no se borra nada.

## Canales

### `GET .../telegram-connection/channels`

`200 {"channels": [{"channel_id": "1987654321", "title": "My channel", "username": "mychannel"}]}`.
Solo canales broadcast donde la cuenta puede publicar. `409 telegram_not_connected` /
`409 telegram_reconnect_required`.

### `PUT .../telegram-connection/channel`

Request `{"channel_id": "1987654321"}` → `200 TelegramConnectionRead`.

| Código | Cuándo |
|---|---|
| `409 telegram_channel_change_blocked` | Hay publicaciones Telegram de la cuenta en `scheduled` o `publishing`: "Finish or cancel the pending Telegram publications of this account before changing its channel." |
| `422 telegram_channel_not_eligible` | El canal no está entre los canales donde puede publicar. |

---

## Publicaciones (sin endpoints nuevos)

- Texto: `POST /api/projects/{project_id}/text-publications` existente; Telegram pasa a
  aceptar publicaciones sin media (`accepts_text_only = True`).
- Imagen/vídeo: `POST /api/contents/{content_id}/publications` existente.
- `GET /api/publications/{id}/publish-check`, `POST /api/publications/{id}/publish`,
  intentos y scheduler: genéricos, sin cambios.

### Resumen del publish-check (Telegram)

`summary`: `Post type` (Text/Image/Video), `Telegram channel`, `Text` (o `Caption`), `File`.

### Problemas de preflight (Telegram)

| Código | Cuándo |
|---|---|
| `telegram_not_connected` / `telegram_reconnect_required` | Sin conexión / sesión inválida. |
| `telegram_channel_required` | Sin canal elegido. |
| `telegram_media_unsupported` | Media que no es una imagen JPEG/PNG/WEBP válida para foto o un vídeo MP4. |
| `telegram_file_too_large` | Imagen > 10 MB o vídeo > 2000 MiB. |
| `telegram_text_too_long` | Texto > 4096 o caption > 1024 (UTF-16). |
| `telegram_text_invalid` | Publicación de texto vacía. |
| `telegram_rate_limited` | `flood_wait_until` todavía no ha pasado. |
| `media_unavailable` | Archivo local no disponible (genérico). |

### Errores de ejecución (intento)

`telegram_reconnect_required`, `telegram_channel_unavailable`, `telegram_text_too_long`,
`telegram_text_invalid`, `telegram_media_rejected`, `telegram_rate_limited`,
`telegram_unavailable` (antes de enviar; determinado), `telegram_unconfirmed` (tras
`finalizing` sin confirmación de Telegram con message ID; **incierto**, requiere el remote check
genérico), más los genéricos existentes
(`interrupted`, `internal_error`, `result_not_saved`).

### Resultado

`external_id` = message ID (siempre presente en un intento `succeeded`); `external_url` solo para canales públicos
(`https://t.me/<username>/<id>`).
