# API Contract: conexión de cuentas Instagram

**Feature**: `008-instagram-oauth-connection` | **Fecha**: 2026-10-08

Amplía la API REST bajo `/api`. Sin autenticación propia (app local de un usuario).

- Fechas en ISO 8601 UTC (`...Z`).
- Formato de error existente: `{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta (ni mensaje de error) contiene nunca access tokens,
códigos de autorización, `state`, app secret, permisos internos del secreto, la ruta del
archivo de configuración ni respuestas crudas de Meta. **Única excepción** (spec FR-026): el
`state` aparece dentro de la `authorization_url` que devuelve `authorize`, porque el protocolo
OAuth lo exige. La redirect URL pegada (con `code` y `state`) solo viaja en el cuerpo del POST
de `complete`; nunca se persiste, se registra ni se devuelve.

**Terminología**: "redirect URL" es la URL a la que Meta lleva el navegador tras el
consentimiento. No existe ninguna ruta de callback HTTPS en el backend: el usuario la pega y
el frontend la envía a `complete`.

**Intentos**: `complete`, `confirm` y `cancel` devuelven de forma síncrona el resultado
actual del intento. **No existe** `GET /api/instagram/oauth/attempts/{id}`; los intentos son
efímeros y viven en memoria.

Ninguna de estas rutas elimina ni modifica una `Account` ni sus `Publication`. `AccountRead`
(Feature 002) **no cambia**.

---

## Representaciones

### InstagramConnection

```json
{
  "status": "connected",
  "identity": {
    "instagram_user_id": "17841400000000000",
    "username": "cyber.studio",
    "account_type": "BUSINESS",
    "profile_picture_url": "https://scontent.cdninstagram.com/..."
  },
  "connected_at": "2026-10-08T18:00:00Z",
  "last_verified_at": "2026-10-08T18:00:00Z",
  "access_expires_at": "2026-12-07T18:00:00Z",
  "oauth_configured": true
}
```

- `status`: `not_connected` | `connected` | `reconnect_required`.
- `account_type`: `BUSINESS` | `MEDIA_CREATOR`.
- Con `not_connected`: `identity`, `connected_at`, `last_verified_at` y `access_expires_at`
  valen `null`.
- `profile_picture_url` puede ser `null`.
- `oauth_configured`: booleano no sensible, calculado en cada petición.

### InstagramOAuthAttempt

```json
{
  "attempt_id": "Yp3…",
  "account_id": 7,
  "status": "awaiting_confirmation",
  "expires_at": "2026-10-08T18:10:00Z",
  "error": null,
  "current_identity": { "instagram_user_id": "1784…A", "username": "old.account", "account_type": "BUSINESS", "profile_picture_url": null },
  "new_identity": { "instagram_user_id": "1784…B", "username": "new.account", "account_type": "MEDIA_CREATOR", "profile_picture_url": null },
  "connection": null
}
```

- `status`: `pending` | `awaiting_confirmation` | `completed` | `failed` | `cancelled` |
  `expired`.
- `connection`: `InstagramConnection` cuando `completed`.

---

## Rutas

### `GET /api/accounts/{account_id}/instagram-connection`

`200` → `InstagramConnection`. Permitido con cuenta o proyecto inactivos. Si el token
guardado ya ha caducado (según `credential_expires_at`), marca `reconnect_required` sin
llamar a Meta.

Errores: `404 not_found`, `409 platform_not_supported`.

### `POST /api/accounts/{account_id}/instagram-connection/authorize`

Inicia Connect o Reconnect. Expira cualquier intento previo de la misma cuenta.

`201`:

```json
{
  "attempt_id": "Yp3…",
  "authorization_url": "https://www.instagram.com/oauth/authorize?client_id=…&redirect_uri=…&response_type=code&scope=instagram_business_basic%2Cinstagram_business_content_publish&state=…&force_reauth=true",
  "expires_at": "2026-10-08T18:10:00Z"
}
```

(La URL de autorización contiene el `state` por necesidad del protocolo —única excepción
permitida—; el frontend solo la abre en una pestaña y no la guarda.)

Errores: `404 not_found`, `409 platform_not_supported`, `409 project_inactive`,
`409 account_inactive`, `503 instagram_oauth_not_configured`.

### `POST /api/instagram/oauth/attempts/{attempt_id}/complete`

Cuerpo:

```json
{ "redirect_url": "https://localhost/autopublisher/instagram/callback?code=…&state=…#_" }
```

Envía la **redirect URL pegada** por el usuario. El frontend vacía el campo y descarta la URL
tras enviarla. Proceso: valida que `redirect_url` empieza por el `redirect_uri` configurado (comparación de
esquema, host, puerto y ruta, tolerando una barra final); extrae `state`, `code` o `error`;
compara `state` con el del intento (tiempo constante); comprueba que la `Account` y el
proyecto siguen activos; intercambia el código; obtiene el token largo; verifica permisos;
consulta `/me`; comprueba tipo Professional; aplica la regla de cambio de cuenta y la de
unicidad; guarda el secreto y la conexión.

`200` → `InstagramOAuthAttempt` con `status` `completed` (misma cuenta o primera conexión) o
`awaiting_confirmation` (cuenta distinta de la vinculada).

Errores (el intento queda `failed` salvo donde se indica):

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `validation_error` | cuerpo ausente o mal formado (el intento sigue `pending`) |
| 400 | `instagram_oauth_redirect_url_invalid` | la redirect URL pegada no corresponde al redirect URI o no trae `code`/`error` (el intento sigue `pending`) |
| 400 | `instagram_oauth_state_invalid` | `state` ausente o distinto (no consume el intento), o intento ya terminado/usado |
| 410 | `instagram_oauth_attempt_expired` | intento caducado o inexistente (p. ej. tras reiniciar) |
| 400 | `instagram_oauth_denied` | `error=access_denied` (el usuario canceló) |
| 400 | `instagram_oauth_provider_error` | otro `error` devuelto por Meta (p. ej. cuenta no autorizada como tester/rol); nunca se muestran datos crudos de Meta |
| 409 | `project_inactive` / `account_inactive` | desactivados durante el flujo |
| 503 | `instagram_oauth_not_configured` | configuración ausente o inválida |
| 502 | `instagram_token_exchange_failed` | Meta rechazó el intercambio de código o de token largo |
| 422 | `instagram_permission_missing` | falta algún permiso requerido (el mensaje indica cuál) |
| 422 | `instagram_account_not_professional` | cuenta no Business/Creator; el mensaje explica que solo se admiten cuentas Professional Business o Creator y que debe convertirse a Professional desde Instagram antes de reintentar |
| 409 | `instagram_account_already_connected` | la cuenta Instagram ya está en otra `Account` del proyecto |
| 503 | `instagram_unavailable` | red o Meta no disponibles, límites temporales |
| 502 | `instagram_unexpected_response` | respuesta de Meta sin los campos esperados |
| 503 | `credential_store_unavailable` | almacén seguro no disponible |

### `POST /api/instagram/oauth/attempts/{attempt_id}/confirm`

Confirma el cambio de cuenta Instagram de un intento `awaiting_confirmation`. Vuelve a
comprobar que la conexión actual sigue siendo la mostrada, que cuenta y proyecto están
activos y la unicidad; guarda el nuevo secreto, actualiza la identidad y borra el secreto
anterior.

`200` → `InstagramOAuthAttempt` (`completed`).

Errores: `404 instagram_oauth_attempt_not_found`, `409 instagram_oauth_attempt_not_confirmable`,
`409 instagram_connection_changed`, `409 project_inactive`, `409 account_inactive`,
`409 instagram_account_already_connected`, `503 credential_store_unavailable`.

### `POST /api/instagram/oauth/attempts/{attempt_id}/cancel`

Cancela un intento `pending` o `awaiting_confirmation`; descarta las credenciales pendientes.
Idempotente si ya está `cancelled`.

`200` → `InstagramOAuthAttempt` (`cancelled`).

Errores: `404 instagram_oauth_attempt_not_found`, `409 instagram_oauth_attempt_not_confirmable`.

### `POST /api/accounts/{account_id}/instagram-connection/verify`

Solo disponible en `connected` y con `Account` y proyecto **activos** (Verify puede renovar
credenciales y modificar datos y el almacén seguro: es una operación activa). Obtiene una
credencial válida (renovando si procede), consulta `/me`, compara `instagram_user_id`,
comprueba el tipo Professional y que la conexión conserva los permisos requeridos, y
actualiza `username`, `account_type`, `profile_picture_url` y `last_verified_at`.

**Orden de precedencia de errores** (determinista cuando coinciden varias condiciones; cada
paso se evalúa solo si el anterior se supera):

1. `Account` inexistente → `404 not_found`.
2. Plataforma distinta de Instagram → `409 platform_not_supported`.
3. `Account` o proyecto inactivo → `409 project_inactive` si el proyecto está inactivo; si no,
   `409 account_inactive` (mismo orden que `authorize`).
4. Sin conexión Instagram → `409 instagram_not_connected`.
5. Conexión en `reconnect_required` → `409 instagram_reconnect_required`.
6. Solo entonces se obtiene la credencial (almacén seguro, renovación si procede) y se
   contacta con Meta; los errores restantes de la lista siguiente solo pueden producirse en
   este paso.

Los pasos 1–5 no leen el almacén seguro ni contactan con Meta.

`200` → `InstagramConnection`.

Errores: `404 not_found`, `409 platform_not_supported`, `409 project_inactive`,
`409 account_inactive` (sin contactar con Meta), `409 instagram_not_connected`,
`409 instagram_reconnect_required` (si ya estaba en `reconnect_required`, sin llamar a Meta;
o pasa a `reconnect_required` si la causa es definitiva: token caducado/revocado/no
renovable, renovación rechazada definitivamente, o permiso requerido ausente/retirado —en
este caso el mensaje indica que falta o se retiró un permiso necesario y cuál, si puede
determinarse de forma segura—; la identidad pública se conserva),
`409 instagram_identity_mismatch` (pasa a `reconnect_required`; no cambia la identidad),
`409 instagram_account_not_professional` (pasa a `reconnect_required`),
`503 instagram_unavailable` (fallo temporal de red/renovación/límite; sin cambio de estado), `502 instagram_unexpected_response`,
`503 credential_store_unavailable`. Verify no exige la configuración de la Meta App: la
renovación documentada (`ig_refresh_token`) no usa el app secret.

### `POST /api/accounts/{account_id}/instagram-connection/disconnect`

Borra el secreto del almacén seguro y después la fila; expira intentos de la cuenta. No
contacta con Meta. Idempotente. Permitido con cuenta/proyecto inactivos.

`200` → `InstagramConnection` (`not_connected`).

Errores: `404 not_found`, `409 platform_not_supported`, `503 credential_store_unavailable`
(la conexión se conserva para reintentar).

---

## Servicios internos para la Feature 009 (no son rutas)

En `instagram_connections.py`:

- `get_valid_credentials(session, store, gateway, account_id) -> InstagramToken` (el reloj
  es el del gateway)

No existe el código público `instagram_token_refresh_failed`: un fallo de renovación
temporal devuelve `instagram_unavailable` y uno definitivo `instagram_reconnect_required`.
- `fetch_identity(gateway, access_token) -> InstagramIdentity`
- `verify_identity(session, store, gateway, account_id) -> InstagramConnection`
  (misma lógica que la ruta `verify`).
