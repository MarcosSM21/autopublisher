# Data Model: Conexión de cuentas Threads

**Feature**: `010-threads-oauth-connection` | **Fecha**: 2026-10-12

`Account`, `Project` y `Publication` **no cambian**. La conexión vive en una tabla propia de la
plataforma, como `youtube_connections` (Feature 005) e `instagram_connections` (Feature 008).

---

## ThreadsConnection (tabla `threads_connections`, migración `0009`)

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK → `accounts.id` (`RESTRICT`) | **único**: como máximo una conexión por `Account` |
| `project_id` | integer FK → `projects.id` (`RESTRICT`) | copia del proyecto de la `Account` (las cuentas no cambian de proyecto), para la unicidad |
| `threads_user_id` | string(64) | Threads user ID (`/me.id` = `user_id` del intercambio = `debug_token.user_id`); identidad autoritativa |
| `username` | string(100) | username actual; se actualiza en Verify/Reconnect |
| `display_name` | string(255), nullable | `/me.name`; informativo |
| `profile_picture_url` | string(2000), nullable | `/me.threads_profile_picture_url`; puede caducar |
| `status` | string(20) | `connected` \| `reconnect_required` (CHECK) |
| `credential_ref` | string(64) | **único**; UUID hex opaco; clave en el keyring (servicio `autopublisher.threads`) |
| `token_obtained_at` | datetime UTC | momento en que AutoPublisher recibió la credencial larga actual (conexión o última renovación correcta); reflejo del valor del secreto (reparable); solo para la condición de 24 h de Meta |
| `credential_expires_at` | datetime UTC | `token_obtained_at + expires_in` de esa misma respuesta oficial; reflejo del secreto (reparable); se expone en la API como `access_expires_at` |
| `data_access_expires_at` | datetime UTC, nullable | último valor oficial conocido de `debug_token.data_access_expires_at` (> 0; `null` si desconocido). Se actualiza al conectar, en Verify y tras cada renovación inspeccionada con éxito. **Solo informativo**: puede estar desfasado y nunca provoca por sí solo `reconnect_required`. Nunca se calcula sumando 90 días |
| `connected_at` | datetime UTC | última conexión/reconexión completada |
| `last_verified_at` | datetime UTC, nullable | última comprobación correcta contra Meta |
| `updated_at` | datetime UTC | |

**Restricciones**:

- `UNIQUE(account_id)`.
- `UNIQUE(project_id, threads_user_id)`: una cuenta Threads real solo en una `Account` por
  proyecto, incluidas `Account` inactivas (spec FR-024). Una violación concurrente
  (`IntegrityError`) se traduce en `threads_account_already_connected`.
- `UNIQUE(credential_ref)`.
- `CHECK status IN ('connected', 'reconnect_required')`.
- Ausencia de fila = `Not connected`.
- Sin relación ORM desde `Account`; el modelo `ThreadsConnection` se define en `models.py`
  junto a los de YouTube e Instagram.
- Nunca contiene tokens, códigos, `state`, app secret ni scopes.
- Independiente de `instagram_connections`: la misma persona puede tener su Instagram y su
  Threads conectados a `Account` distintas del mismo proyecto.

**Validación**: la `Account` debe tener `platform = threads`.

### Transiciones de estado

```text
(sin fila) ──Connect OK (permisos confirmados)───────────────► connected
connected ──token rechazado (190) / debug_token is_valid=false / permiso ausente o retirado /
            secreto ausente o ilegible / token caducado según su propio expires_at /
            mismatch de ID (Verify o inspección tras renovar) ─────────────────► reconnect_required
connected ──error temporal (red, 5xx, 429, límites)──► connected (sin cambio)
connected | reconnect_required ──Reconnect misma cuenta──► connected (nuevo secreto)
connected | reconnect_required ──Reconnect otra cuenta + confirmación──► connected (nueva identidad)
connected | reconnect_required ──Reconnect otra cuenta + cancelar/caducar──► (sin cambio)
connected | reconnect_required ──Disconnect──► (sin fila)
```

- `Verify connection` solo en `connected` con `Account` y proyecto activos; sobre
  `reconnect_required` responde `409 threads_reconnect_required` sin llamar a Meta. No existe
  `reconnect_required → connected` mediante Verify.
- **Regla fundamental**: `reconnect_required` solo se alcanza con una señal oficial actual
  (`debug_token.is_valid = false`, permiso requerido ausente, error definitivo de
  autenticación/autorización de Meta, mismatch de identidad), con el token caducado según el
  `expires_at` del propio secreto, o con la credencial ausente/ilegible. Una fecha local pasada
  de `data_access_expires_at` **no** es una señal suficiente: puede ser metadata no actualizada.
- Al leer el estado (`GET`), sin red:
  - `data_access_expires_at` se muestra tal cual, pero **nunca** cambia el estado;
  - si `status = connected` y la metadata SQLite indica `credential_expires_at ≤ now`, antes de
    marcar nada se lee el secreto (fuente de verdad): si su `expires_at` es posterior y vigente,
    se repara SQLite y sigue `connected` (caso de renovación con commit SQLite fallido); si el
    secreto confirma la caducidad o falta → `reconnect_required`; si el almacén no está
    disponible → sin cambio de estado.

---

## Credencial de Threads (solo en el almacén seguro)

Servicio `autopublisher.threads`, usuario = `credential_ref`, valor JSON:

| Campo | Descripción |
|---|---|
| `access_token` | token de larga duración |
| `token_obtained_at` | ISO 8601 UTC; momento de recepción del token (fuente de verdad para la condición de 24 h de Meta) |
| `expires_at` | ISO 8601 UTC; `token_obtained_at + expires_in` |
| `scopes` | permisos confirmados por `debug_token` en la conexión, la última verificación o la última inspección tras renovar |

Un JSON ilegible, sin zona horaria o ausente equivale a credencial perdida →
`reconnect_required`. El token corto nunca se guarda.

El secreto es la **fuente de verdad** de token, `token_obtained_at`, `expires_at` y `scopes`.
Las columnas `token_obtained_at` y `credential_expires_at` de `threads_connections` son un
reflejo no sensible que puede quedar desfasado y se repara desde el secreto.

### Política de `get_valid_credentials(session, store, gateway, account_id) -> ThreadsToken`

El reloj es el del gateway (`ThreadsGateway.clock`). La política trabaja con la clasificación
semántica del gateway, nunca con números de error.

Constantes: `RENEWAL_WINDOW = 7 días` (decisión de producto, constante interna; no es una
regla de Meta), `REFRESH_MIN_AGE = 24 h` (condición técnica de Meta), `EXPIRY_MARGIN = 5 min`
(vigente = `expires_at - now > EXPIRY_MARGIN`).

1. Sin conexión → `threads_not_connected`; `reconnect_required` → `threads_reconnect_required`.
2. Bajo el candado de la cuenta, leer el secreto (almacén no disponible →
   `credential_store_unavailable`; ausente/ilegible → `reconnect_required`).
3. **Reparación**: si `token_obtained_at` o `credential_expires_at` de SQLite difieren de los
   del secreto, copiar los del secreto a SQLite y hacer commit (idempotente). Si este commit
   falla, se registra un aviso y se continúa: la política siguiente solo usa el secreto.
4. `remaining = expires_at - now`; `age = now - token_obtained_at`.
5. `remaining ≤ 0` (caducado) → `reconnect_required`.
6. `remaining > RENEWAL_WINDOW` → devolver el token actual, **sin** renovar.
7. `remaining ≤ RENEWAL_WINDOW` y `age < REFRESH_MIN_AGE` → devolver el token actual si es
   vigente; si está dentro de `EXPIRY_MARGIN` (no renovable y a punto de caducar) →
   `reconnect_required` (consecuencia de combinar la condición oficial de 24 h con el margen
   interno de seguridad; no es una regla de Meta).
8. `remaining ≤ RENEWAL_WINDOW` y `age ≥ REFRESH_MIN_AGE` → renovar:
   - OK → (a) escribir el secreto con el mismo `credential_ref` (nuevo `access_token`,
     `token_obtained_at = now`, `expires_at = now + expires_in`, mismos `scopes`); si falla →
     `credential_store_unavailable` y el secreto anterior sigue intacto. (b) Actualizar en SQLite
     `token_obtained_at`, `credential_expires_at` y `updated_at`; si este commit falla:
     rollback de la sesión, aviso en log sin datos sensibles, **no** restaurar el token antiguo
     y continuar con el token nuevo (el paso 3 lo reparará en el siguiente acceso).
     (c) **Inspección tras renovar**: `debug_token` sobre el token nuevo (ver abajo).
     Después se devuelve el token nuevo.
   - `ThreadsUnavailable`/`ThreadsUnexpectedResponse` → si el token actual es vigente,
     devolverlo y registrar un aviso sin datos sensibles; si está dentro de `EXPIRY_MARGIN`,
     `threads_unavailable`/`threads_unexpected_response`. Nunca cambia el estado.
   - `ThreadsTokenInvalid`, `ThreadsPermissionDenied` u otro rechazo definitivo →
     `reconnect_required` (`threads_reconnect_required`).

No existe ninguna renovación fuera de esta función: sin scheduler ni renovación periódica.

### Inspección tras una renovación correcta (paso 8c)

Una renovación puede extender la concesión de permisos (perfiles públicos), así que tras
guardar el token renovado se intenta inspeccionarlo con `debug_token`:

- **Éxito** (`is_valid = true`, `user_id` = `threads_user_id`, ambos scopes requeridos): si
  los scopes confirmados difieren de los del secreto, reescribir el secreto conservando
  exactamente `access_token`, `token_obtained_at` y `expires_at`; actualizar en SQLite
  `data_access_expires_at` con el valor oficial devuelto (o `null` si es 0/ausente). Las dos
  escrituras son independientes: si falla la del secreto (scopes), se conserva el token nuevo
  ya guardado, no se restaura el antiguo, no cambia el estado, se registra un aviso sin
  secretos y aun así se actualiza en SQLite la metadata no sensible de fuente oficial
  (`data_access_expires_at`); los scopes se reintentarán en el siguiente Verify o inspección. Un
  fallo del commit de SQLite tampoco invalida el token nuevo. **Diferencia con Verify**: allí la
  reescritura del secreto es el resultado explícito de la operación, así que su fallo devuelve
  `credential_store_unavailable`; aquí la renovación ya se completó y la inspección es
  complementaria.
- **Señal oficial definitiva** (`is_valid = false`, permiso requerido ausente,
  `ThreadsTokenInvalid`/`ThreadsPermissionDenied`, `user_id` distinto) →
  `reconnect_required` (`threads_reconnect_required` o `threads_identity_mismatch`).
- **Fallo temporal** (`ThreadsUnavailable`, `ThreadsUnexpectedResponse`): **no** se descarta el
  token nuevo, **no** se restaura el antiguo, **no** cambia el estado; se conserva la última
  metadata conocida (`data_access_expires_at`, `scopes`) hasta la siguiente verificación y se
  registra un aviso sin datos sensibles.

Nunca se calcula una nueva `data_access_expires_at` sumando 90 días.

### Secreto durante `Verify connection`

Orden: `get_valid_credentials` → `debug_token` → `/me`.

- Permiso requerido ausente, `is_valid = false` o `user_id` distinto → `reconnect_required`
  según el contrato; esa transición **no** depende de poder guardar nada en el secreto.
- Si `debug_token` confirma los scopes requeridos: comparar los scopes confirmados con los del
  secreto y **solo** reescribir el secreto si han cambiado, conservando exactamente
  `access_token`, `token_obtained_at`, `expires_at` y cualquier otro campo que Verify no
  actualiza. La escritura es un único `set` del valor completo sobre la misma `credential_ref`
  (sin escrituras parciales).
- Si esa escritura falla → `503 credential_store_unavailable`; el secreto anterior se conserva
  intacto; no se hace commit de la metadata de Verify y el estado **no** pasa a
  `reconnect_required` por ese fallo.
- Después se actualizan en SQLite solo datos de fuente oficial: `username`, `display_name`,
  `profile_picture_url` (`/me`), `data_access_expires_at` (`debug_token`) y `last_verified_at`.

### Orden seguro al conectar, reconectar y confirmar (`complete_connection`)

Cada conexión completada usa una **`credential_ref` nueva**:

1. `store.set(new_ref, secreto nuevo)`; si falla → `credential_store_unavailable`, nada cambia.
2. Crear o actualizar la fila (identidad, `credential_ref = new_ref`, fechas) y hacer commit.
3. Si el commit falla (cualquier error, no solo `IntegrityError`): rollback, borrar
   inmediatamente `new_ref` (best-effort) y propagar el error. En una primera conexión no queda
   fila; en una reconexión la fila anterior sigue apuntando a `old_ref`, cuyo secreto **no** se
   ha tocado: la conexión anterior sigue intacta y utilizable.
4. Solo tras el commit correcto (la nueva credencial ya es autoritativa) se borra `old_ref`
   (best-effort). Si ese borrado falla, queda una entrada huérfana sin referencia, registrada en
   log sin datos sensibles; la conexión nueva es correcta.

Nunca se elimina la única credencial anterior utilizable antes de que la nueva sea
autoritativa. La renovación (paso 8) es el único caso que reutiliza la `credential_ref`; ahí se
aplica la reconciliación secreto → SQLite y nunca se restaura un token antiguo.

---

## Intento OAuth pendiente (solo en memoria)

`ThreadsOAuthAttempt` en `ThreadsAttemptRegistry`:

| Campo | Descripción |
|---|---|
| `attempt_id` | identificador aleatorio público |
| `account_id` | `Account` que inició el flujo |
| `state` | 32 bytes aleatorios; nunca sale del backend salvo dentro de la URL de autorización |
| `created_at`, `expires_at` | TTL 10 min |
| `status` | `pending` → `awaiting_confirmation` → `completed` \| `failed` \| `cancelled` \| `expired` |
| `error` | `{code, message}` seguro si falla |
| `current_identity` / `new_identity` | identidades públicas para la advertencia de cambio |
| `pending_credentials` | token largo + metadatos a la espera de confirmación (memoria, nunca serializado) |
| `connection` | lectura pública de la conexión resultante |
| `finished_at`, `consumed`, `claimed` | retención y protección de uso único |

Reglas: un intento nuevo expira los no terminales de la misma `Account`; los terminales se
conservan 10 min sin secretos; `state`, código y credenciales nunca se persisten; un reinicio
pierde los intentos.

---

## Configuración de la app Threads (archivo local)

`ThreadsAppConfig(app_id, app_secret [fuera de repr], redirect_uri)` leído de
`backend/data/threads-app.json` (o `AUTOPUBLISHER_THREADS_APP_FILE`). Reglas en
[research.md](research.md) §4 y §11.

---

## Objetos de dominio (no persistidos)

- `ThreadsIdentity(threads_user_id, username, display_name?, profile_picture_url?)`.
- `ThreadsTokenInfo(is_valid, user_id, scopes, data_access_expires_at?)` — resultado
  normalizado de `debug_token`.
- `ThreadsToken(access_token [fuera de repr], token_obtained_at, expires_at, scopes)` con
  `to_json`/`from_json`.

---

## Lecturas públicas (API)

- `ThreadsIdentityRead`: `threads_user_id`, `username`, `display_name`, `profile_picture_url`.
- `ThreadsConnectionRead`: `status`, `identity`, `connected_at`, `last_verified_at`,
  `token_obtained_at`, `access_expires_at`, `data_access_expires_at`, `oauth_configured`.
- **Correspondencia de nombres**: la columna `threads_connections.credential_expires_at` se
  expone en la API como `access_expires_at` (mismo valor: caducidad del token largo). El
  nombre de la columna sigue la convención de Instagram; el de la API, el del contrato de 008.
  Ambos se mantienen y la correspondencia se documenta en el modelo y en el schema.
- `ThreadsAuthorizeRead`, `ThreadsOAuthAttemptRead`, `ThreadsCompleteWrite`: ver
  [contracts/api.md](contracts/api.md).

Ninguna incluye tokens, scopes internos, `state`, código ni configuración.
