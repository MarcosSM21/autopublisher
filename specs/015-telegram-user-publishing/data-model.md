# Data Model: Telegram User Account & Publishing

**Feature**: `015-telegram-user-publishing` | **Fecha**: 2026-10-15

Cero cambios en las tablas comunes (`accounts`, `publications`, `publication_attempts`).
Se añade **una tabla** propia del adaptador y un secreto en el almacén seguro.

## TelegramConnection (`telegram_connections`, nueva)

Migración `0014_create_telegram_connections`. "not_connected" significa que no hay fila.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int PK | |
| `account_id` | FK `accounts.id` (RESTRICT), **unique** | Una conexión por `Account` Telegram. |
| `project_id` | FK `projects.id` (RESTRICT) | Copiado de la cuenta, como Threads. |
| `telegram_user_id` | str(32) | Identidad autoritativa (`get_me().id`). |
| `display_name` | str(255) | Nombre + apellido. |
| `username` | str(100) null | Sin `@`. |
| `status` | str(20) | `connected` \| `reconnect_required` (CHECK). |
| `credential_ref` | str(64) **unique** | Localiza la sesión en el almacén seguro. |
| `channel_id` | str(32) null | Canal destino (id MTProto, sin prefijo `-100`). |
| `channel_access_hash` | str(32) null | Interno; nunca sale por la API (research §7). |
| `channel_title` | str(255) null | Solo para mostrar; se refresca al publicar. |
| `channel_username` | str(100) null | Solo si es público; deriva el enlace. |
| `flood_wait_until` | UTC datetime null | Fin del último FloodWait de publicación. |
| `connected_at` | UTC datetime | |
| `last_verified_at` | UTC datetime null | |
| `updated_at` | UTC datetime | |

Reglas:

- `channel_id`, `channel_access_hash` y `channel_title` son todos nulos o todos no nulos
  (CHECK).
- Sin restricción de unicidad por `telegram_user_id`: varias `Account` pueden conectar la
  misma cuenta de Telegram (cada una con su propia sesión y canal).
- No hay relación ORM desde `Account` (patrón existente).

### Transiciones

```text
(sin fila) --login completo--> connected
connected --Verify/publicación detecta sesión inválida--> reconnect_required
reconnect_required --login completo (mismo user ID)--> connected
connected | reconnect_required --Disconnect--> (sin fila)
```

### Canal destino

- `set_channel(channel_id)`: solo si no existe ninguna `Publication` con ese `account_id` en
  `scheduled` o `publishing`; si no → `409 telegram_channel_change_blocked`.
- El canal debe estar en el listado actual de canales elegibles (research §7).

## Secreto en el almacén seguro

- Servicio `autopublisher.telegram`, clave `credential_ref`.
- Valor JSON: `{"v": 1, "session": "<StringSession>", "user_id": "<telegram_user_id>"}`.
- Se escribe al completar el login; se borra en Disconnect. Nunca en SQLite, logs, API ni
  archivos.

## Lock de sesión por cuenta (solo memoria)

Un `threading.Lock` por `account_id` en `telegram_connections.py`: como máximo un cliente
MTProto activo por `Account` Telegram (research §2). No se persiste.

## Login pendiente (solo memoria, no persistido)

`TelegramLoginRegistry` (por `account_id`, TTL 10 min):

| Campo | Notas |
|---|---|
| `step` | `code` \| `password` |
| `partial_session` | `StringSession` parcial (secreto, solo memoria). |
| `phone` | Solo memoria; la API devuelve una versión enmascarada. |
| `phone_code_hash` | Solo memoria. |
| `expires_at` | |

Se descarta al completar, cancelar, expirar o reiniciar el backend.

## PublicationAttempt (existente, sin cambios de esquema)

- `submitted` (snapshot persistido al crear el intento) incluye:
  `post_type` (`text` \| `image` \| `video`), `channel_id`, `channel_title`, `text_length`,
  `telegram_random_id` (int; identidad de envío estable, research §8). Se reutiliza en el
  siguiente intento de la misma publicación si este queda incierto; nunca se regenera para
  resolver una duda. Telegram no olvida los `random_id` usados.
- `external_id`: `message_id` como string. Siempre presente en un intento `succeeded` (sin
  confirmación con ID el intento queda incierto, research §8).
- `external_url`: `https://t.me/<channel_username>/<message_id>` solo para canales públicos.
- `details`: `{"channel_id", "channel_title"}`.

## Publication (existente, sin cambios)

- Texto: `content_id = null`, texto en `description_override` + `hashtags_override`
  (endpoint existente `POST /api/projects/{id}/text-publications`).
- Imagen/vídeo: `content_id` → `Content` con `media_type` image/video.
- Estados genéricos `scheduled → publishing → published | failed`.
