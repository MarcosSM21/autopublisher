# API Contract: conexión de cuentas YouTube

**Feature**: `005-youtube-oauth-connection` | **Fecha**: 2026-10-06

Amplía la API REST bajo `/api`. Sin autenticación propia (app local de un usuario).

- Fechas en ISO 8601 UTC (`...Z`).
- Se mantiene el formato de error existente:
  `{"error": {"code", "message", "fields": []}}` (ver
  `specs/002-projects-accounts/contracts/api.md#error`).

**Regla transversal**: ninguna respuesta (JSON o HTML) contiene nunca:

- access tokens ni refresh tokens;
- códigos de autorización;
- `code_verifier`;
- client secret;
- la ruta del archivo de configuración.

Ninguna de estas rutas elimina una `Account` ni sus `Publication`.

---

## Representaciones

### YouTubeConnection

```json
{
  "status": "connected",
  "channel": {
    "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "title": "Cyber Channel",
    "handle": "@cyberchannel",
    "thumbnail_url": "https://yt3.ggpht.com/..."
  },
  "connected_at": "2026-10-06T18:00:00Z",
  "last_verified_at": "2026-10-06T18:00:00Z",
  "oauth_configured": true
}
```

- `status`: `not_connected` | `connected` | `reconnect_required`.
- `oauth_configured`: booleano **no sensible**. Vale `true` si el archivo de cliente OAuth
  existe y es un cliente Desktop válido, y `false` en caso contrario. Se calcula leyendo la
  configuración en cada petición, sin reiniciar el backend. Nunca expone la ruta, el client
  ID ni el client secret. Con `false`, la interfaz no abre ninguna pestaña y muestra cómo
  configurar YouTube OAuth.
- Con `not_connected`, los campos `channel`, `connected_at` y `last_verified_at` valen
  `null`.
- `handle` y `thumbnail_url` pueden ser `null`.

### Account (sin cambios)

`AccountRead` (Feature 002) **no cambia**: no incluye información de conexión. El núcleo de
cuentas no conoce YouTube (Constitution III). El frontend obtiene el estado con
`GET /api/accounts/{id}/youtube-connection`, solo para las cuentas con
`platform = "youtube"`.

### OAuthAttempt

```json
{
  "attempt_id": "pM8m3…",
  "account_id": 3,
  "status": "awaiting_confirmation",
  "expires_at": "2026-10-06T18:10:00Z",
  "error": null,
  "current_channel": { "id": "UCaaa…", "title": "Cyber Channel", "handle": "@cyberchannel", "thumbnail_url": null },
  "new_channel":     { "id": "UCbbb…", "title": "Other Channel", "handle": "@other", "thumbnail_url": null },
  "connection": null
}
```

- `status`: `pending` | `awaiting_confirmation` | `completed` | `failed` | `cancelled` |
  `expired`.
- `error`: `{code, message}` cuando el estado es `failed`. Puede ser cualquier código de la
  tabla de errores marcado como "intento", o `internal_error` ante un fallo inesperado
  durante el callback o la confirmación (mensaje genérico, sin detalles internos).
- `connection`: el `YouTubeConnection` resultante cuando el estado es `completed`.
- `current_channel` / `new_channel`: presentes cuando se conocen.
- **Caducidad y retención** (regla única, ver [data-model.md](../data-model.md)):
  - un intento `pending` o `awaiting_confirmation` que supera `expires_at` pasa a
    `expired`;
  - todo intento terminal (`completed`, `failed`, `cancelled`, `expired`) se conserva, sin
    secretos, 10 minutos adicionales desde que terminó, y `GET` lo devuelve con su estado;
  - después se purga y `GET` devuelve `404 oauth_attempt_not_found`.

---

## Rutas

### `GET /api/accounts/{account_id}/youtube-connection`

Estado de conexión, información no sensible del canal y `oauth_configured`. Permitido con
la cuenta o el proyecto inactivos. El frontend la llama solo para cuentas YouTube.

- `200` → `YouTubeConnection`.
- `404 not_found`: la cuenta no existe.
- `409 platform_not_supported`: la cuenta no es YouTube.

No contacta con Google.

### `POST /api/accounts/{account_id}/youtube-connection/authorize`

Inicia la conexión o la reconexión. Sin cuerpo.

- Genera `state` y PKCE.
- Invalida las autorizaciones pendientes anteriores de la cuenta (pasan a `expired`).

`201`:

```json
{
  "attempt_id": "pM8m3…",
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?response_type=code&client_id=…&redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fyoutube%2Foauth%2Fcallback&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.readonly+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload&state=…&code_challenge=…&code_challenge_method=S256&access_type=offline&prompt=select_account+consent",
  "expires_at": "2026-10-06T18:10:00Z"
}
```

`authorization_url` contiene el `code_challenge`, pero nunca el `code_verifier`.

`authorization_url` incluye **siempre** `access_type=offline` y `prompt=select_account
consent`, tanto en conexión como en reconexión (research §4). El usuario verá siempre la
pantalla de consentimiento de Google; es intencionado, para obtener un refresh token nuevo
aunque el permiso ya estuviera concedido. Si aun así Google no devuelve refresh token, el
intento termina en `failed` / `oauth_offline_access_missing`.

Errores:

- `404 not_found`;
- `409 platform_not_supported`;
- `409 project_inactive`;
- `409 account_inactive`;
- `503 oauth_not_configured`.

### `GET /api/youtube/oauth/callback`

Destino de la redirección de Google; lo abre el **navegador**, no el frontend.

- Query: `state`, y además `code` + `scope`, o `error`.
- Responde siempre `text/html`: una página mínima con el resultado y la indicación de volver
  a AutoPublisher. Estado HTTP:
  - `200`: éxito (`completed`) y `awaiting_confirmation`;
  - `400`: errores OAuth o de validación esperados (todos los códigos de la tabla
    marcados como "intento", además de `oauth_state_invalid`, `not_found`,
    `platform_not_supported`, `account_inactive`, `project_inactive`,
    `oauth_not_configured`, `channel_already_connected` y
    `credential_store_unavailable`);
  - `500`: el resultado es `internal_error` (fallo inesperado). La página muestra un
    mensaje genérico, sin detalles internos.
- El resultado detallado se guarda en el intento.

Orden de validación:

1. **`state` ausente, desconocido, ya usado o caducado** → página de error
   `oauth_state_invalid`. No se intercambia ningún código y no cambia ninguna cuenta.
2. El `state` se consume. A partir de aquí todo resultado queda en el intento.
3. **`error=access_denied`** → `failed` / `oauth_cancelled`. **Otro `error`** → `failed` /
   `oauth_provider_error`.
4. **Sin `code`** → `failed` / `oauth_callback_invalid`.
5. La cuenta ya no existe, no es YouTube o la cuenta o el proyecto están inactivos →
   `failed` con `not_found`, `platform_not_supported`, `account_inactive` o
   `project_inactive`.
6. Configuración ausente → `failed` / `oauth_not_configured`.
7. **Intercambio** del código con `code_verifier`:
   - error de Google → `oauth_exchange_failed`;
   - fallo de red → `youtube_unavailable`.
8. Scopes concedidos incompletos → `oauth_scope_insufficient`. Sin `refresh_token` →
   `oauth_offline_access_missing`.
9. **`channels.list?mine=true`**:
   - red o `5xx` → `youtube_unavailable`;
   - 0 canales → `youtube_no_channel`;
   - más de 1 → `youtube_channel_ambiguous`.
10. El canal ya está vinculado a **otra** cuenta del proyecto → `channel_already_connected`.
11. La cuenta tenía otro channel ID vinculado → `awaiting_confirmation`. La conexión no se
    modifica.
12. En otro caso → se guardan las credenciales y la fila → `completed`.

En los pasos 8–10, las credenciales obtenidas se descartan: se olvidan en memoria, no se
escriben en el almacén y **no** se revocan en Google (research §13).

### `GET /api/youtube/oauth/attempts/{attempt_id}`

Sondeo del frontend.

- `200` → `OAuthAttempt`.
- `404 oauth_attempt_not_found`: id desconocido, intento purgado (más de 10 minutos
  después de llegar a un estado terminal) o backend reiniciado.

Un intento caducado dentro de su periodo de retención devuelve `200` con
`status: "expired"`, nunca `404`.

### `POST /api/youtube/oauth/attempts/{attempt_id}/confirm`

Confirma la sustitución de canal. Solo es válido en `awaiting_confirmation`.

Antes de aplicar, vuelve a comprobar que:

- la cuenta y el proyecto siguen activos;
- el canal nuevo sigue libre en el proyecto;
- el canal vinculado sigue siendo el `current_channel` mostrado.

Respuestas:

- `200` → `OAuthAttempt` con `completed` y `connection`.
- `404 oauth_attempt_not_found`.
- `409 oauth_attempt_not_confirmable`: el intento no está en `awaiting_confirmation`
  (incluido un intento ya `expired` durante su periodo de retención); la conexión no
  cambia.
- `409 project_inactive` / `account_inactive` / `channel_already_connected` /
  `connection_changed`. El intento pasa a `failed` y se descartan las credenciales.
- `503 credential_store_unavailable`.

### `POST /api/youtube/oauth/attempts/{attempt_id}/cancel`

Cancela la sustitución (`awaiting_confirmation` → `cancelled`) o una autorización todavía
`pending` (→ `cancelled`).

- Descarta las credenciales nuevas (solo en memoria, sin revocarlas en Google) y deja
  intacta la conexión anterior.
- `200` → `OAuthAttempt`. Es idempotente sobre un intento ya `cancelled`.
- `404 oauth_attempt_not_found`.
- `409 oauth_attempt_not_confirmable`: el intento está en otro estado terminal.

### `POST /api/accounts/{account_id}/youtube-connection/verify`

Obtiene credenciales válidas sin login (refresca si hace falta), vuelve a consultar
`channels.list?mine=true` y actualiza `channel_title`, `channel_handle`,
`channel_thumbnail_url` y `last_verified_at`. Permitido aunque la cuenta o el proyecto estén
inactivos: no crea vínculos nuevos.

Respuestas:

- `200` → `YouTubeConnection` (`connected`).
- `404 not_found`.
- `409 platform_not_supported`.
- `409 not_connected`: no hay conexión.
- `409 reconnect_required`: refresh rechazado definitivamente, secreto ausente, `401`/`403`
  de permisos, o channel ID distinto del vinculado. El estado queda `reconnect_required` y
  el cuerpo incluye el motivo en `message`.
- `503 youtube_unavailable`: error transitorio; el estado no cambia.
- `503 oauth_not_configured`: el refresh necesita client ID y client secret.
- `503 credential_store_unavailable`.

### `POST /api/accounts/{account_id}/youtube-connection/disconnect`

Desconecta. Permitido aunque la cuenta o el proyecto estén inactivos, y sin configuración
OAuth. Es idempotente.

Orden estricto:

1. borrar el secreto del almacén seguro (un secreto ya ausente no es error);
2. **solo si el paso 1 tiene éxito**, borrar la fila (la referencia local); la cuenta pasa
   a `not_connected`;
3. las autorizaciones pendientes de la cuenta pasan a `expired`.

Otros aspectos:
- **No contacta con Google** y **no revoca** el permiso OAuth (research §13): la revocación
  afecta al grant completo de la aplicación para esa identidad de Google y podría invalidar
  otras conexiones. La interfaz indica cómo retirar el permiso manualmente en
  <https://myaccount.google.com/connections>.

`200` → `YouTubeConnection`:

```json
{ "status": "not_connected", "channel": null, "connected_at": null, "last_verified_at": null, "oauth_configured": true }
```

Errores:

- `404 not_found`;
- `409 platform_not_supported`;
- `503 credential_store_unavailable`: no hay un backend seguro de `keyring` o está
  bloqueado/no disponible, y no se pudo borrar el secreto. La fila **no** se borra para
  poder reintentar cuando el almacén esté disponible. Nunca se recurre a otro
  almacenamiento.

---

## Códigos de error nuevos

| `code` | HTTP | Cuándo (mensaje orientativo para el usuario) |
|--------|------|------------------------------------------------|
| `platform_not_supported` | 409 | Operación de conexión sobre una cuenta que no es YouTube. "Only YouTube accounts can be connected." |
| `oauth_not_configured` | 503 | Falta el archivo de cliente OAuth, es ilegible o no es de tipo Desktop app. "YouTube integration is not configured. See the README section 'Connecting YouTube'." |
| `oauth_state_invalid` | 400 | `state` ausente, desconocido, usado o caducado (solo en el callback). "This authorization is invalid or has expired. Start the connection again from AutoPublisher." |
| `oauth_callback_invalid` | — (intento) | Respuesta sin `code` ni `error` reconocible. |
| `oauth_cancelled` | — (intento) | El usuario canceló o rechazó el consentimiento. "The connection was cancelled in Google." |
| `oauth_provider_error` | — (intento) | Google devolvió otro `error` en la redirección. |
| `oauth_exchange_failed` | — (intento) | Google rechazó el intercambio del código. "Google did not complete the authorization. Try again." |
| `oauth_scope_insufficient` | — (intento) | No se concedieron todos los permisos. "Grant all requested permissions to connect the channel." |
| `oauth_offline_access_missing` | — (intento) | Google no devolvió credencial renovable. |
| `youtube_unavailable` | 503 / intento | Google o YouTube no responden, o responden `5xx`/`429`. "Could not reach YouTube. Check your connection and try again." |
| `youtube_no_channel` | — (intento) | La identidad autorizada no tiene canal. "This Google account has no YouTube channel." |
| `youtube_channel_ambiguous` | — (intento) | No se puede determinar un único canal efectivo. "Could not determine which YouTube channel to connect. Select the right channel in Google's account chooser and try again." |
| `channel_already_connected` | 409 / intento | El canal ya está vinculado a otra cuenta del proyecto. El mensaje nombra la cuenta (`@handle`). |
| `connection_changed` | 409 | Al confirmar, la conexión actual ya no es la mostrada en la advertencia. |
| `not_connected` | 409 | Verificar una cuenta sin conexión. |
| `reconnect_required` | 409 | Las credenciales ya no sirven; hay que reconectar. |
| `credential_store_unavailable` | 503 | No hay un backend de `keyring` de la lista blanca (research §8), o está bloqueado o no disponible. Se comprueba antes de guardar, leer o borrar credenciales. "The system's secure credential storage is not available. See the README section 'Connecting YouTube'." |
| `internal_error` | 500 / intento | Fallo inesperado. En un intento (callback o `confirm`), el intento termina `failed` con este código y un mensaje genérico; la página HTML del callback responde `500`. Se registra en el log sin secretos. Código existente del proyecto. |
| `oauth_attempt_not_found` | 404 | Intento desconocido o caducado. |
| `oauth_attempt_not_confirmable` | 409 | Confirmar o cancelar un intento en un estado que no lo permite. |

Se reutilizan:

- `not_found` (404);
- `project_inactive` (409);
- `account_inactive` (409);
- `validation_error` (422), que no aplica a estas rutas sin cuerpo salvo en el path.

"— (intento)" significa que el error se entrega en `OAuthAttempt.error` y en la página HTML
del callback, no como respuesta HTTP de una ruta del frontend.

## Rutas sin cambios

Las demás rutas existentes no cambian, y `AccountRead` tampoco.
`PATCH /api/accounts/{id}` con `is_active: false` **no** desconecta.
