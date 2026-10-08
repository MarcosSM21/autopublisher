# Data Model: Conexión de cuentas Instagram

**Feature**: `008-instagram-oauth-connection` | **Fecha**: 2026-10-08

`Account`, `Project` y `Publication` **no cambian**. La conexión vive en una tabla propia de
la plataforma, como `youtube_connections` (Feature 005).

---

## InstagramConnection (tabla `instagram_connections`, migración `0007`)

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK → `accounts.id` (`RESTRICT`) | **único**: como máximo una conexión por `Account` |
| `project_id` | integer FK → `projects.id` (`RESTRICT`) | copia del proyecto de la `Account`, para la unicidad |
| `instagram_user_id` | string(64) | Instagram professional account ID (`/me.user_id`); identidad autoritativa |
| `app_scoped_id` | string(64), nullable | `/me.id` (app-scoped); informativo |
| `username` | string(100) | username actual; se actualiza en Verify/Reconnect |
| `account_type` | string(20) | `BUSINESS` \| `MEDIA_CREATOR` (CHECK) |
| `profile_picture_url` | string(2000), nullable | URL pública de CDN, puede caducar |
| `status` | string(20) | `connected` \| `reconnect_required` (CHECK) |
| `credential_ref` | string(64) | **único**; UUID hex opaco; clave en el keyring (servicio `autopublisher.instagram`) |
| `credential_expires_at` | datetime UTC | caducidad del token largo; no sensible; se muestra en la interfaz |
| `connected_at` | datetime UTC | fecha de la última conexión/reconexión completada |
| `last_verified_at` | datetime UTC, nullable | última identidad comprobada contra Meta |
| `updated_at` | datetime UTC | |

**Restricciones**:

- `UNIQUE(account_id)`.
- `UNIQUE(project_id, instagram_user_id)`: una cuenta Instagram real solo en una `Account`
  por proyecto, incluidas `Account` inactivas (spec FR-023). Una violación concurrente se
  traduce en `instagram_account_already_connected`.
- `UNIQUE(credential_ref)`.
- Ausencia de fila = `Not connected`.
- Sin relación ORM en `Account` (el núcleo no conoce Instagram); el modelo
  `InstagramConnection` se define en `models.py` junto a `YouTubeConnection`.
- Nunca contiene tokens, códigos, `state`, app secret ni permisos.

**Validación**:

- La `Account` debe tener `platform = instagram`.
- `account_type` normalizado a mayúsculas; cualquier otro valor impide la conexión.

### Transiciones de estado

```text
(sin fila) ──Connect OK──────────────────────────► connected
connected ──token rechazado definitivamente / permiso retirado / secreto ausente /
            caducado sin renovación posible / mismatch en Verify /
            ya no Professional / permiso requerido ausente o retirado ───────────────────► reconnect_required
connected ──error temporal (red, 5xx, 429, límites)─► connected (sin cambio)
connected | reconnect_required ──Reconnect misma cuenta──► connected (nuevo secreto)
connected | reconnect_required ──Reconnect otra cuenta + confirmación──► connected (nueva identidad)
connected | reconnect_required ──Reconnect otra cuenta + cancelar/caducar──► (sin cambio)
connected | reconnect_required ──Disconnect──► (sin fila)
```

Reglas de `Verify connection`:

- Solo está disponible en `connected` y con `Account` y proyecto activos.
- Sobre `reconnect_required`, la API responde `409 instagram_reconnect_required` sin llamar a
  Meta y la interfaz ofrece `Reconnect`.
- **No existe** transición `reconnect_required → connected` mediante Verify; solo mediante
  Reconnect (o Disconnect + Connect).

Al leer el estado (`GET`), si `status = connected` y `credential_expires_at` ya pasó, se
marca `reconnect_required` localmente (sin red): un token caducado no puede renovarse.

---

## Credencial de Instagram (solo en el almacén seguro)

Servicio `autopublisher.instagram`, usuario = `credential_ref`, valor JSON:

| Campo | Descripción |
|---|---|
| `access_token` | token de larga duración |
| `issued_at` | momento en que se obtuvo/renovó (para la regla de 24 h) |
| `expires_at` | `issued_at + expires_in` |
| `permissions` | permisos verificados en la conexión |

Un JSON ilegible o ausente equivale a credencial perdida → `reconnect_required`.

### Política de `get_valid_credentials(session, store, gateway, account_id)`

El reloj es el del gateway (`InstagramGateway.clock`); no hay parámetro `clock` separado.
La política trabaja con la clasificación semántica del gateway, nunca con números de error.

1. Sin conexión → `instagram_not_connected`; `reconnect_required` → `instagram_reconnect_required`.
2. Leer secreto (almacén no disponible → `credential_store_unavailable`; ausente/ilegible →
   `reconnect_required`).
3. Si `expires_at - now ≤ 5 min`: renovar si `now - issued_at ≥ 24 h`; si no es posible o Meta
   lo rechaza definitivamente (`MetaTokenInvalid`) → `reconnect_required`
   (`instagram_reconnect_required`); si el fallo es temporal (`MetaUnavailable`) →
   `instagram_unavailable` sin cambio de estado.
4. Si `now - issued_at ≥ 24 h`: renovar de forma oportunista; fallo temporal → devolver el
   token actual (sigue vigente); rechazo definitivo (`MetaTokenInvalid`) o permiso retirado
   (`MetaPermissionDenied`) → `reconnect_required` (`instagram_reconnect_required`).
5. Si no, devolver el token actual.
6. Toda renovación correcta reescribe el secreto con el mismo `credential_ref` y actualiza
   `credential_expires_at`. Candado por cuenta.

---

## Intento OAuth pendiente (solo en memoria)

`InstagramOAuthAttempt` en `InstagramAttemptRegistry`:

| Campo | Descripción |
|---|---|
| `attempt_id` | identificador aleatorio público (no es secreto de autorización) |
| `account_id` | `Account` que inició el flujo |
| `state` | 32 bytes aleatorios; nunca sale del backend salvo dentro de la URL de autorización |
| `created_at`, `expires_at` | TTL 10 min |
| `status` | `pending` → `awaiting_confirmation` → `completed` \| `failed` \| `cancelled` \| `expired` |
| `error` | `{code, message}` seguro si falla |
| `current_identity` / `new_identity` | identidades públicas para la advertencia de cambio |
| `pending_credentials` | token largo a la espera de confirmación (memoria, nunca serializado) |
| `connection` | lectura pública de la conexión resultante |
| `finished_at`, `claimed` | retención y protección de confirmación única |

Reglas: un intento nuevo expira los no terminales de la misma `Account`; los terminales se
conservan 10 min sin secretos; `state`, credenciales y código nunca se persisten.

---

## Configuración de la Meta App (archivo local)

`backend/data/instagram-app.json` (o `AUTOPUBLISHER_INSTAGRAM_APP_FILE`): `app_id`,
`app_secret`, `redirect_uri` (https). Ver `research.md` §7.

---

## Lecturas públicas (API)

- `InstagramIdentityRead`: `instagram_user_id`, `username`, `account_type`,
  `profile_picture_url`.
- `InstagramConnectionRead`: `status`, `identity`, `connected_at`, `last_verified_at`,
  `access_expires_at`, `oauth_configured`.
- `InstagramOAuthAttemptRead`: `attempt_id`, `account_id`, `status`, `expires_at`, `error`,
  `current_identity`, `new_identity`, `connection`.

Detalle en [contracts/api.md](contracts/api.md).
