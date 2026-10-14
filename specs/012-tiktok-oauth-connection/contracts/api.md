# API Contract: Conexión TikTok

**Feature**: `012-tiktok-oauth-connection` | **Fecha**: 2026-10-14

- Prefijo `/api`. Formato de error existente: `{"error": {"code", "message", "fields": []}}`.
- Ninguna respuesta contiene tokens, código, `code_verifier`, client secret ni `credential_ref`.
  `state` y `code_challenge` aparecen **solo** dentro de `authorization_url`.
- Precedencia de errores comunes: `not_found` (404, cuenta inexistente) →
  `platform_not_supported` (409, cuenta no TikTok) → `project_inactive` / `account_inactive`
  (409, solo en operaciones activas) → errores propios.

---

## `GET /accounts/{account_id}/tiktok-connection`

Nunca llama a TikTok. Puede leer el secreto (data-model, "Lectura pública").

```json
{
  "status": "connected",
  "identity": { "open_id": "…", "display_name": "Cyber Studio", "avatar_url": "https://…" },
  "connected_at": "…", "last_verified_at": "…",
  "access_expires_at": "…", "refresh_expires_at": "…",
  "permissions": {
    "granted": ["user.info.basic", "video.publish"],
    "source": "token_refresh",
    "confirmed_at": "…"
  },
  "oauth_configured": true
}
```

- `status`: `not_connected` | `connected` | `reconnect_required`. Con `not_connected`, el resto
  es `null` salvo `oauth_configured`.
- `permissions` es `null` si el secreto no puede leerse. `source` indica la respuesta oficial de
  la que procede (`token_exchange` | `token_refresh`): no es una comprobación en vivo.

## `POST /accounts/{account_id}/tiktok-connection/authorize` → 201

Sirve para Connect y Reconnect. Crea un intento (expira los anteriores de la cuenta).

```json
{ "attempt_id": "…", "authorization_url": "https://www.tiktok.com/v2/auth/authorize/?client_key=…&scope=user.info.basic%2Cvideo.publish&response_type=code&redirect_uri=…&state=…&code_challenge=…&code_challenge_method=S256", "expires_at": "…" }
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `project_inactive` / `account_inactive` | entidades inactivas |
| 503 | `tiktok_oauth_not_configured` | config ausente/ inválida o puerto del backend ≠ puerto del `redirect_uri` |

## `GET /tiktok/oauth/callback` (navegador; siempre `303 See Other`)

Destino del redirect de TikTok. Lee `query_params.multi_items()`; parámetros documentados:
`code`, `scopes`, `state`, `error`, `error_description`. **Nunca** sirve contenido en su propia
URL: responde siempre `303` con `Location: /api/tiktok/oauth/result?outcome=<outcome>`,
`Cache-Control: no-store` y `Referrer-Policy: no-referrer`, sin cuerpo útil. La URL entrante
(con `code`/`state`) no se registra (access log redactado) ni se devuelve por API, y el redirect
la saca de la barra de direcciones.

| Caso | `outcome` | Efecto en el intento |
|---|---|---|
| petición no loopback | `invalid` | ninguno |
| `state` ausente, desconocido, usado, de intento sustituido/cancelado o tras reinicio | `invalid` | ninguno |
| intento caducado | `invalid` | ya `expired` |
| parámetro documentado duplicado, `code`+`error`, ninguno, `code` vacío o > 1024 | `failed` | `failed` `tiktok_oauth_callback_invalid` |
| `error=access_denied` | `cancelled` | `failed` `tiktok_oauth_denied` |
| otro `error` | `failed` | `failed` `tiktok_oauth_provider_error` |
| entidades inactivas | `failed` | `failed` `project_inactive`/`account_inactive` (sin intercambio) |
| intercambio rechazado (`invalid_grant`, PKCE, redirect) | `failed` | `failed` `tiktok_token_exchange_failed` |
| scopes sin ambos requeridos | `failed` | `failed` `tiktok_permission_missing` (descarte + revocación best-effort) |
| `open_id` ausente o distinto entre intercambio y `user/info` | `failed` | `failed` `tiktok_unexpected_response` |
| TikTok no disponible | `failed` | `failed` `tiktok_unavailable` |
| `open_id` en otra `Account` del proyecto (consulta o violación de `UNIQUE(project_id, open_id)`) | `failed` | `failed` `tiktok_account_already_connected` |
| almacén seguro no disponible | `failed` | `failed` `credential_store_unavailable` |
| `open_id` distinto del vinculado | `confirm_required` | `awaiting_confirmation` |
| éxito | `connected` | `completed` |
| error inesperado | `failed` | `failed` `internal_error` |

## `GET /tiktok/oauth/result?outcome=<outcome>` (navegador; HTML)

Ruta limpia final. `outcome` ∈ {`connected`, `confirm_required`, `cancelled`, `failed`,
`invalid`} (enumerado cerrado); ausente, desconocido o repetido → `invalid`; cualquier otro
parámetro se ignora. Título y mensaje salen de un diccionario fijo: la query nunca se refleja en
la página. Siempre 200, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, sin scripts,
con "You can close this tab and return to AutoPublisher.". Nunca recibe `code`, `state`, tokens,
verifier, `attempt_id` ni errores crudos; el detalle lo muestra el panel desde el intento.

## `GET /tiktok/oauth/attempts/{attempt_id}`

```json
{
  "attempt_id": "…", "account_id": 7,
  "status": "pending",
  "expires_at": "…",
  "error": null,
  "current_identity": null, "new_identity": null,
  "connection": null
}
```

- `status`: `pending` | `processing` | `awaiting_confirmation` | `completed` | `failed` |
  `cancelled` | `expired`.
- Identidades: `{ "display_name", "avatar_url", "open_id_suffix" }` (6 últimos caracteres).
- `connection`: `TikTokConnectionRead` al completar.
- 404 `tiktok_oauth_attempt_not_found` (inexistente, purgado o tras reinicio).

## `POST /tiktok/oauth/attempts/{attempt_id}/confirm`

Solo en `awaiting_confirmation`. Revalida entidades activas y unicidad; aplica el orden seguro
de sustitución. Respuesta: intento (`completed`).

| HTTP | `code` |
|---|---|
| 404 | `tiktok_oauth_attempt_not_found` |
| 409 | `tiktok_oauth_attempt_not_confirmable` (otro estado o ya reclamado) |
| 410 | `tiktok_oauth_attempt_expired` |
| 409 | `project_inactive` / `account_inactive` / `tiktok_account_already_connected` |
| 409 | `tiktok_connection_changed` (la conexión cambió desde que se mostró la advertencia) |
| 503 | `credential_store_unavailable` |

## `POST /tiktok/oauth/attempts/{attempt_id}/cancel`

`pending` o `awaiting_confirmation` → `cancelled` (credencial pendiente descartada y revocada
best-effort). Idempotente sobre `cancelled`. Permitido con entidades inactivas. Errores: 404
`tiktok_oauth_attempt_not_found`, 409 `tiktok_oauth_attempt_not_confirmable` (terminal o
`processing`).

## `POST /accounts/{account_id}/tiktok-connection/verify`

Solo lectura frente a TikTok. Respuesta: `TikTokConnectionRead` actualizado. `permissions.source`
refleja si hubo renovación.

| HTTP | `code` |
|---|---|
| 409 | `project_inactive` / `account_inactive` |
| 409 | `tiktok_not_connected` / `tiktok_reconnect_required` |
| 409 | `tiktok_identity_mismatch` (pasa a `reconnect_required`) |
| 409 | `tiktok_reconnect_required` (refresh caducado/rechazado, scope ausente, secreto ausente) |
| 503 | `tiktok_unavailable` (temporal; sin cambio de estado) |
| 502 | `tiktok_unexpected_response` (sin cambio de estado) |
| 503 | `tiktok_oauth_not_configured` (no se puede renovar; sin cambio de estado) |
| 503 | `credential_store_unavailable` |

## `POST /accounts/{account_id}/tiktok-connection/disconnect`

Revoca y desconecta. Permitido con entidades inactivas. Idempotente.

```json
{ "connection": { "status": "not_connected", "…": null }, "revocation": "revoked" }
```

- `revocation`: `revoked` (TikTok confirmó) | `already_invalid` (credencial inválida según
  TikTok; no se afirma revocación) | `not_connected` (ya estaba desconectada).

| HTTP | `code` | Efecto |
|---|---|---|
| 503 | `tiktok_revoke_failed` | fallo temporal, respuesta ambigua o configuración ausente; nada se borra |
| 409 | `tiktok_credential_missing` | secreto ausente/ilegible; sin llamar a TikTok; nada se borra |
| 503 | `credential_store_unavailable` | almacén inaccesible; nada se borra |

## `POST /accounts/{account_id}/tiktok-connection/remove-local`

Acción explícita tras `tiktok_revoke_failed` o `tiktok_credential_missing` (el frontend solo la
ofrece entonces; el backend la permite sobre cualquier conexión existente). Sin llamar a TikTok.
Borra el secreto (si existe) y la fila. Respuesta: `{ "connection": {…not_connected}, "revocation":
"not_revoked" }`; sobre una cuenta sin conexión: `revocation: "not_connected"`. Error: 503
`credential_store_unavailable` (nada se borra).

## Servicios internos para la Feature 013 (`tiktok_connections.py`)

- `get_valid_credentials(session, store, gateway, account_id) -> TikTokCredential`
- `get_linked_identity(session, account_id) -> TikTokIdentity` (incluye `open_id`)
- `mark_scope_not_authorized(session, account_id, scope)` → `reconnect_required` (para reaccionar
  a `scope_not_authorized` de `video.publish`).
