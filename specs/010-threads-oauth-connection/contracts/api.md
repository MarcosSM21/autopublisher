# API Contract: conexión de cuentas Threads

**Feature**: `010-threads-oauth-connection` | **Fecha**: 2026-10-12

Amplía la API REST bajo `/api`. Sin autenticación propia (app local de un usuario).

- Fechas en ISO 8601 UTC (`...Z`).
- Formato de error existente: `{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta ni mensaje de error contiene access tokens, códigos de
autorización, `state`, app secret, scopes internos del secreto, la ruta del archivo de
configuración ni respuestas crudas de Meta. **Única excepción** (spec FR-027): el `state`
aparece dentro de la `authorization_url` que devuelve `authorize`. La redirect URL pegada solo
viaja en el cuerpo del POST de `complete`; nunca se persiste, se registra ni se devuelve.

**Intentos**: `complete`, `confirm` y `cancel` devuelven el resultado del intento de forma
síncrona. **No existe** `GET /api/threads/oauth/attempts/{id}`.

Ninguna ruta elimina ni modifica una `Account` ni sus `Publication`. `AccountRead` no cambia.
Las rutas de YouTube e Instagram no cambian.

---

## Representaciones

### ThreadsConnection

```json
{
  "status": "connected",
  "identity": {
    "threads_user_id": "25841234567890123",
    "username": "cyber.studio",
    "display_name": "Cyber Studio",
    "profile_picture_url": "https://scontent.cdninstagram.com/..."
  },
  "connected_at": "2026-10-12T18:00:00Z",
  "last_verified_at": "2026-10-12T18:00:00Z",
  "token_obtained_at": "2026-10-12T18:00:00Z",
  "access_expires_at": "2026-12-11T18:00:00Z",
  "data_access_expires_at": "2027-01-10T18:00:00Z",
  "oauth_configured": true
}
```

- `status`: `not_connected` | `connected` | `reconnect_required`.
- Con `not_connected`, todos los campos salvo `status` y `oauth_configured` valen `null`.
- `display_name`, `profile_picture_url` y `data_access_expires_at` pueden ser `null`.
- `access_expires_at`: caducidad del token largo (columna `credential_expires_at` en SQLite;
  mismo valor, nombres distintos por convención).
- `data_access_expires_at`: último valor oficial conocido de `debug_token`; **informativo**.
  Puede estar desfasado y nunca cambia el estado por sí solo.
- `oauth_configured`: booleano no sensible, calculado en cada petición.

### ThreadsOAuthAttempt

```json
{
  "attempt_id": "Yp3…",
  "account_id": 9,
  "status": "awaiting_confirmation",
  "expires_at": "2026-10-12T18:10:00Z",
  "error": null,
  "current_identity": { "threads_user_id": "2584…A", "username": "old.account", "display_name": null, "profile_picture_url": null },
  "new_identity": { "threads_user_id": "2584…B", "username": "new.account", "display_name": "New", "profile_picture_url": null },
  "connection": null
}
```

- `status`: `pending` | `awaiting_confirmation` | `completed` | `failed` | `cancelled` |
  `expired`.
- `connection`: `ThreadsConnection` cuando `completed`.

---

## Rutas

### `GET /api/accounts/{account_id}/threads-connection`

`200` → `ThreadsConnection`. Permitido con cuenta o proyecto inactivos. Nunca llama a Meta.
`data_access_expires_at` se devuelve tal cual y **nunca** provoca `reconnect_required`, aunque
la fecha haya pasado (puede ser metadata no actualizada). Si la metadata SQLite indica
`credential_expires_at` vencido, consulta antes el secreto (fuente de verdad): si su caducidad
es posterior y vigente, repara SQLite y la conexión sigue `connected`; si lo confirma o falta,
marca `reconnect_required`; si el almacén no está disponible, no cambia el estado (sin error).

Errores: `404 not_found`, `409 platform_not_supported`.

### `POST /api/accounts/{account_id}/threads-connection/authorize`

Inicia Connect o Reconnect. Expira cualquier intento previo de la misma cuenta.

`201`:

```json
{
  "attempt_id": "Yp3…",
  "authorization_url": "https://threads.com/oauth/authorize?client_id=…&redirect_uri=…&scope=threads_basic%2Cthreads_content_publish&response_type=code&state=…",
  "expires_at": "2026-10-12T18:10:00Z"
}
```

Errores: `404 not_found`, `409 platform_not_supported`, `409 project_inactive`,
`409 account_inactive`, `503 threads_oauth_not_configured`.

### `POST /api/threads/oauth/attempts/{attempt_id}/complete`

Cuerpo:

```json
{ "redirect_url": "https://localhost/autopublisher/threads/callback?code=…&state=…#_" }
```

Proceso:

1. Intento inexistente o caducado → `410`.
2. Parseo estricto de la redirect URL (research §4): scheme, hostname, puerto efectivo y path
   **exactamente** iguales a los del `redirect_uri` configurado; sin credenciales de usuario;
   parámetros solo desde la query; `#_` ignorado. Nunca comparación por prefijo.
3. `state` comparado en tiempo constante; un `state` distinto no consume el intento.
4. `error` → denegado o error del proveedor.
5. `Account` y proyecto siguen activos.
6. Intercambio de código (una vez, sin reintentos) → token corto + `user_id`.
7. Intercambio a larga duración → token largo + `expires_in`.
8. `debug_token` con el token largo (research §7): `is_valid`, `user_id`, `scopes` con los
   dos permisos, `data_access_expires_at`.
9. `/me` → identidad; `id` debe coincidir con `user_id` del paso 6 y del paso 8.
10. Regla de cambio de cuenta y de unicidad; guardar el secreto con una `credential_ref`
    nueva y después la conexión (orden seguro de data-model: si el commit falla, se borra el
    secreto nuevo y la conexión anterior —si existía— queda intacta; el secreto anterior solo
    se borra tras el commit correcto).

`200` → `ThreadsOAuthAttempt` con `status` `completed` (primera conexión o misma cuenta) o
`awaiting_confirmation` (cuenta distinta).

| HTTP | `code` | Cuándo |
|---|---|---|
| 422 | `validation_error` | cuerpo ausente o mal formado (intento sigue `pending`) |
| 400 | `threads_oauth_redirect_url_invalid` | URL no parseable, con credenciales de usuario, scheme/host/puerto/path distintos, parámetros duplicados o sin `code`/`error` (intento sigue `pending`) |
| 400 | `threads_oauth_state_invalid` | `state` ausente o distinto (no consume), o intento ya usado/terminado |
| 410 | `threads_oauth_attempt_expired` | intento caducado o inexistente (p. ej. tras reiniciar) |
| 400 | `threads_oauth_denied` | `error=access_denied` |
| 400 | `threads_oauth_provider_error` | otro `error` de Meta (p. ej. cuenta no tester); sin datos crudos |
| 409 | `project_inactive` / `account_inactive` | desactivados durante el flujo |
| 503 | `threads_oauth_not_configured` | configuración ausente o inválida |
| 502 | `threads_token_exchange_failed` | Meta rechazó el intercambio de código o a larga duración |
| 422 | `threads_permission_missing` | `debug_token` no confirma ambos permisos, `is_valid=false` o Meta deniega la inspección por permisos (el mensaje indica cuáles faltan si se sabe) |
| 409 | `threads_account_already_connected` | el Threads user ID ya está en otra `Account` del proyecto |
| 503 | `threads_unavailable` | red o Meta no disponibles, límites temporales (iniciar nueva autorización) |
| 502 | `threads_unexpected_response` | respuesta sin campos esperados o `user_id` incoherente entre respuestas |
| 503 | `credential_store_unavailable` | almacén seguro no disponible |
| 500 | `internal_error` | error inesperado de persistencia o interno: las credenciales nuevas no quedan activas, se intenta borrar el secreto nuevo, la conexión anterior (si existía) se conserva; mensaje genérico sin detalles internos ni secretos (formato de la Feature 008) |

Salvo donde se indica, el intento queda `failed` y no se guarda ninguna credencial.

### `POST /api/threads/oauth/attempts/{attempt_id}/confirm`

Confirma el cambio de cuenta de un intento `awaiting_confirmation`. Vuelve a comprobar que la
conexión actual sigue siendo la mostrada, que cuenta y proyecto están activos y la unicidad;
guarda el nuevo secreto, actualiza la identidad y, solo tras el commit correcto, borra el
secreto anterior (mismo orden seguro que `complete`).

`200` → `ThreadsOAuthAttempt` (`completed`).

Errores: `404 threads_oauth_attempt_not_found`, `409 threads_oauth_attempt_not_confirmable`,
`409 threads_connection_changed`, `409 project_inactive`, `409 account_inactive`,
`409 threads_account_already_connected`, `503 credential_store_unavailable`,
`500 internal_error` (error inesperado de persistencia o interno: el intento queda `failed`,
las credenciales nuevas no quedan activas, se intenta borrar el secreto nuevo, la conexión
anterior se conserva intacta y el mensaje es genérico, sin detalles internos ni secretos;
mismo formato que en la Feature 008).

### `POST /api/threads/oauth/attempts/{attempt_id}/cancel`

Cancela un intento `pending` o `awaiting_confirmation` y descarta las credenciales pendientes.
Idempotente si ya está `cancelled`. Permitido con entidades inactivas.

`200` → `ThreadsOAuthAttempt` (`cancelled`).

Errores: `404 threads_oauth_attempt_not_found`, `409 threads_oauth_attempt_not_confirmable`.

### `POST /api/accounts/{account_id}/threads-connection/verify`

Operación de solo lectura respecto a Threads (no crea, modifica ni borra contenido).

Precedencia de errores (cada paso solo si el anterior se supera; 1–5 no leen el almacén seguro
ni contactan con Meta):

1. `Account` inexistente → `404 not_found`.
2. Plataforma distinta de Threads → `409 platform_not_supported`.
3. Proyecto inactivo → `409 project_inactive`; si no, cuenta inactiva → `409 account_inactive`.
4. Sin conexión → `409 threads_not_connected`.
5. `reconnect_required` → `409 threads_reconnect_required`.
6. `get_valid_credentials`: lee el secreto, repara la metadata SQLite si está desfasada y
   aplica la política de renovación de [data-model.md](../data-model.md) (renovar solo si quedan
   ≤ 7 días y el token tiene ≥ 24 h) → `debug_token` (`is_valid`, `user_id`, ambos scopes) →
   `/me` (`id`).

Si durante el paso 6 se renueva el token, `get_valid_credentials` ya inspecciona el token
nuevo (data-model, paso 8c); Verify vuelve a llamar a `debug_token` igualmente.

Actualiza en SQLite, solo con datos de fuente oficial, `username`, `display_name`,
`profile_picture_url`, `data_access_expires_at` y `last_verified_at`. Los `scopes` del secreto
solo se reescriben si los confirmados por `debug_token` han cambiado, conservando exactamente
`access_token`, `token_obtained_at` y `expires_at`. Si esa escritura falla →
`503 credential_store_unavailable`, el secreto anterior queda intacto, no se guarda la
metadata de Verify y el estado no cambia. Un permiso requerido ausente lleva a
`reconnect_required` sin depender de esa escritura.

`200` → `ThreadsConnection`.

Errores del paso 6: `409 threads_reconnect_required` (pasa a `reconnect_required`: token
caducado/revocado/no renovable, `is_valid=false`, permiso ausente o retirado —mensaje con el
permiso si se sabe—, secreto ausente), `409 threads_identity_mismatch` (pasa a
`reconnect_required`; la identidad no cambia), `503 threads_unavailable` (sin cambio de
estado), `502 threads_unexpected_response`, `503 credential_store_unavailable`. Verify no
exige la configuración de la app (ni la renovación ni `debug_token` usan el app secret).

### `POST /api/accounts/{account_id}/threads-connection/disconnect`

Borra el secreto del almacén seguro y después la fila; expira intentos de la cuenta. No
contacta con Meta. Idempotente. Permitido con cuenta/proyecto inactivos.

`200` → `ThreadsConnection` (`not_connected`).

Errores: `404 not_found`, `409 platform_not_supported`, `503 credential_store_unavailable`
(la conexión se conserva).

---

## Servicios internos para la Feature 011 (no son rutas)

En `threads_connections.py`:

- `get_valid_credentials(session, store, gateway, account_id) -> ThreadsToken`
- `get_linked_identity(session, account_id) -> ThreadsIdentity`
- `verify_identity(session, store, gateway, account_id) -> ThreadsConnection` (misma lógica que
  la ruta `verify`).

`get_valid_credentials` aplica la política de data-model: sin renovación si quedan más de 7
días (`RENEWAL_WINDOW`, decisión de producto); renovación si quedan ≤ 7 días y el token tiene
≥ 24 h (condición de Meta); fallo temporal con token vigente → devuelve el token actual; token
caducado o fallo definitivo → `threads_reconnect_required`. Lee siempre primero el secreto y
repara la metadata SQLite desfasada. Tras una renovación correcta inspecciona el token nuevo
con `debug_token` y actualiza `scopes` y `data_access_expires_at` con los valores oficiales; si
la inspección falla temporalmente, conserva el token nuevo y la última metadata conocida sin
cambiar el estado; si devuelve una señal definitiva (`is_valid=false`, permiso ausente,
`user_id` distinto) → `reconnect_required`. Nunca calcula una fecha de acceso a datos.

No existe código público `threads_token_refresh_failed`: un fallo temporal de renovación sin
token vigente devuelve `threads_unavailable` y uno definitivo `threads_reconnect_required`.

Esta feature **no** registra ningún publisher de Threads en `app.state.publishers`.
