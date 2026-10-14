# Data Model: Conexión de cuentas TikTok

**Feature**: `012-tiktok-oauth-connection` | **Fecha**: 2026-10-14

`Account`, `Project` y `Publication` **no cambian**. La conexión vive en tablas propias de TikTok
(migración `0011`), como `youtube_connections`, `instagram_connections` y `threads_connections`.

---

## TikTokConnection (tabla `tiktok_connections`)

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK → `accounts.id` (`RESTRICT`) | **único** |
| `project_id` | integer FK → `projects.id` (`RESTRICT`) | copia del proyecto de la `Account`, para la unicidad |
| `open_id` | string(128) | identidad autoritativa (intercambio = `user/info`) |
| `display_name` | string(255), nullable | `user/info.display_name`; informativo |
| `avatar_url` | string(2000), nullable | `user/info.avatar_url`; puede caducar |
| `status` | string(20) | `connected` \| `reconnect_required` (CHECK) |
| `credential_ref` | string(64) | **único**; UUID hex opaco; clave en el keyring (servicio `autopublisher.tiktok`) |
| `access_expires_at` | datetime UTC | espejo informativo del secreto (reparable) |
| `refresh_expires_at` | datetime UTC | espejo informativo del secreto (reparable) |
| `connected_at` | datetime UTC | última conexión/reconexión completada |
| `last_verified_at` | datetime UTC, nullable | último Verify correcto |
| `updated_at` | datetime UTC | |

**Restricciones**: `UNIQUE(account_id)`; `UNIQUE(project_id, open_id)` (incluye `Account`
inactivas; `IntegrityError` → `tiktok_account_already_connected`); `UNIQUE(credential_ref)`;
`CHECK status IN ('connected','reconnect_required')`. Sin fila = `Not connected`. Sin relación
ORM desde `Account`. Nunca contiene tokens, códigos, `state`, verifier, client secret ni scopes.
Independiente de las tablas de otras plataformas. Validación: `Account.platform = tiktok`.

Las fechas de SQLite son **solo informativas**: las decisiones (renovar, caducado) se toman con
el secreto. Excepción para no llamar al keyring en cada `GET`: si el espejo dice
`refresh_expires_at <= now`, el `GET` lee el secreto; si este confirma la caducidad o falta →
`reconnect_required`; si el secreto tiene una fecha futura → repara el espejo; almacén no
disponible → sin cambio.

## TikTokCredentialOrphan (tabla `tiktok_credential_orphans`)

| Campo | Tipo | Reglas |
|---|---|---|
| `credential_ref` | string(64) PK | referencia opaca cuyo secreto debe borrarse |
| `account_id` | integer, nullable | solo para logs (sin FK: la `Account` podría no existir en el futuro) |
| `created_at` | datetime UTC | |

Nunca contiene secretos. Una fila se inserta **en la misma transacción** que cambia
`credential_ref` en Reconnect/cambio de cuenta; se borra tras borrar el secreto. Limpieza
idempotente y oportunista (research §12); antes de borrar un secreto huérfano se comprueba que
ninguna `tiktok_connections.credential_ref` lo usa.

## Credencial de TikTok (keyring, servicio `autopublisher.tiktok`, clave `credential_ref`)

JSON único, sustituido completo en cada escritura:

```json
{
  "version": 1,
  "open_id": "…",
  "access_token": "…",
  "refresh_token": "…",
  "access_expires_at": "2026-10-15T10:00:00+00:00",
  "refresh_expires_at": "2027-10-14T10:00:00+00:00",
  "scopes": ["user.info.basic", "video.publish"],
  "scopes_source": "token_exchange",
  "obtained_at": "2026-10-14T10:00:00+00:00"
}
```

- `access_expires_at = obtained_at + expires_in`; `refresh_expires_at = obtained_at +
  refresh_expires_in` (valores devueltos por esa misma respuesta).
- `scopes_source`: `token_exchange` | `token_refresh`; `obtained_at` es también el momento de
  confirmación de los scopes. Se exponen como `permissions.source` y
  `permissions.confirmed_at` (sin tokens).
- Fechas con zona horaria obligatoria; JSON ilegible o incompleto = secreto ausente.
- Dataclass `TikTokCredential` con `access_token`/`refresh_token` `repr=False`.
- Fuente de verdad. Nunca en SQLite, archivos, logs, API ni navegador.

## Intento de autorización (memoria, `TikTokAttemptRegistry`)

| Campo | Notas |
|---|---|
| `attempt_id` | `token_urlsafe(16)`; lo único que conoce el frontend |
| `account_id` | |
| `state` | `token_urlsafe(32)`; índice exacto `state → attempt_id`; se quita al consumir |
| `code_verifier` | `repr=False`; se borra al consumir el `state` (antes del intercambio) |
| `created_at`, `expires_at` | TTL `TIKTOK_ATTEMPT_TTL = 10 min` |
| `status` | `pending` → `processing` → `completed` \| `failed` \| `awaiting_confirmation`; `cancelled`, `expired` |
| `error` | `{code, message}` seguro |
| `current_identity`, `new_identity` | `TikTokIdentity` pública (nombre, avatar, sufijo de `open_id`) |
| `pending_credential` | `repr=False`; solo en `awaiting_confirmation`; se borra al terminar |
| `connection` | vista pública al completar |
| `finished_at`, `claimed` | retención `TIKTOK_ATTEMPT_RETENTION = 10 min` sin secretos |

Reglas: crear un intento expira los no terminales de la misma cuenta (el último gana); `state`
de un solo uso; cancelación permitida en `pending` y `awaiting_confirmation`; un intento en
`awaiting_confirmation` que caduca descarta (y revoca best-effort) la credencial pendiente;
reinicio del backend = registro vacío.

Nuevo estado `processing` (respecto a YouTube): marca el consumo del `state` para que un segundo
callback y el frontend vean que hay un intercambio en curso.

## Configuración (`backend/data/tiktok-app.json`)

`TikTokAppConfig(client_key, client_secret[repr=False], redirect_uri)` — research §3 y §16.

## Transiciones de estado de la conexión

```text
(sin fila) ──callback OK (ambos scopes, open_id coherente, open_id libre en el proyecto)──► connected
connected ──refresh_expires_at pasado (secreto) / invalid_grant al renovar / secreto ausente o
            ilegible / scopes de renovación sin un requerido / scope_not_authorized /
            open_id distinto (renovación o Verify) ─────────────────────────► reconnect_required
connected ──error temporal (red, timeout, 5xx, 429)──► connected (sin cambio)
connected | reconnect_required ──Reconnect misma cuenta──► connected (nueva credential_ref)
connected | reconnect_required ──Reconnect otra cuenta + confirmar──► connected (nueva identidad)
connected | reconnect_required ──Reconnect otra cuenta + cancelar/caducar──► (sin cambio)
connected | reconnect_required ──Disconnect: revoked | already_invalid──► (sin fila)
connected | reconnect_required ──Disconnect: revoke_failed | credential_missing──► (sin cambio)
connected | reconnect_required ──remove-local (confirmado)──► (sin fila)
```

Desactivar `Account` o `Project` no cambia el estado.

## Lectura pública (`TikTokConnectionRead`)

`status` (`not_connected` | `connected` | `reconnect_required`), `identity` (`open_id`,
`display_name`, `avatar_url`), `connected_at`, `last_verified_at`, `access_expires_at`,
`refresh_expires_at`, `permissions` (`granted`: lista de scopes requeridos presentes según el
secreto; `source`; `confirmed_at`) — solo cuando el secreto es legible; si no, `null` —,
`oauth_configured`. Nunca tokens, `credential_ref` ni `state`.

Para no leer el keyring en cada listado, `permissions` se obtiene del secreto solo en `GET` de la
conexión individual (no en listados de cuentas), con fallo silencioso a `null` si el almacén no
está disponible.
