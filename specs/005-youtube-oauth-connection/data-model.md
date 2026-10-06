# Data Model: Conexión segura de cuentas de YouTube

**Feature**: `005-youtube-oauth-connection` | **Fecha**: 2026-10-06

Esta feature tiene tres tipos de datos:

| Tipo de dato | Dónde vive | Secreto |
|--------------|------------|---------|
| `YouTubeConnection` | SQLite (tabla nueva `youtube_connections`, migración `0004`) | No |
| Credenciales de cuenta | Almacén seguro del sistema operativo (`keyring`) | **Sí** |
| `OAuthAttempt` | Memoria del proceso backend (efímero) | Contiene secretos temporales |
| Configuración OAuth de la app | Archivo local no versionado | **Sí** (client secret) |

`Account`, `Project` y `Publication` **no cambian** en base de datos.

---

## YouTubeConnection (`youtube_connections`)

Vínculo entre una `Account` de plataforma YouTube y un canal real. Existe mientras la cuenta
está `connected` o `reconnect_required`. La ausencia de fila equivale a `not_connected`.

| Columna | Tipo | Nulo | Descripción |
|---------|------|------|-------------|
| `id` | integer PK | no | |
| `account_id` | integer FK → `accounts.id` (`RESTRICT`) | no | **Único**: una conexión por cuenta. |
| `project_id` | integer FK → `projects.id` (`RESTRICT`) | no | Copia del `project_id` de la cuenta, para la unicidad por proyecto. Una cuenta nunca cambia de proyecto. |
| `channel_id` | string(64) | no | Channel ID de YouTube (`UC…`). Identidad autoritativa. |
| `channel_title` | string(200) | no | `snippet.title`. |
| `channel_handle` | string(100) | sí | `snippet.customUrl` (p. ej. `@cyberchannel`). |
| `channel_thumbnail_url` | string(500) | sí | `snippet.thumbnails.default.url` (pública). |
| `status` | string(20) | no | `connected` \| `reconnect_required`. |
| `credential_ref` | string(64) | no | Referencia **no secreta** al almacén seguro (`uuid4().hex`). Única. |
| `connected_at` | UTCDateTime | no | Momento de la última autorización completada (conexión o reconexión). |
| `last_verified_at` | UTCDateTime | sí | Última verificación correcta del canal. |
| `updated_at` | UTCDateTime | no | Último cambio de la fila. |

**Restricciones**:

- `UNIQUE (account_id)`.
- `UNIQUE (project_id, channel_id)`: FR-020. Incluye cuentas inactivas porque la fila
  existe independientemente de `accounts.is_active`.
- `UNIQUE (credential_ref)`.
- `CHECK (status IN ('connected', 'reconnect_required'))`.
- Nombres según la convención de `models.py`, **idénticos en el modelo y en la migración
  `0004`** (el test de deriva lo comprueba):

  | Restricción | Nombre |
  |-------------|--------|
  | PK | `pk_youtube_connections` |
  | FK cuenta | `fk_youtube_connections_account_id_accounts` |
  | FK proyecto | `fk_youtube_connections_project_id_projects` |
  | Único cuenta | `uq_youtube_connections_account_id` |
  | Único canal–proyecto | `uq_youtube_connections_project_id_channel_id` |
  | Único referencia | `uq_youtube_connections_credential_ref` |
  | CHECK estado | `ck_youtube_connections_status` |

**Relación con `Account`**: solo la FK `account_id` desde `youtube_connections`. El modelo
común `Account` **no** declara una relación inversa ni conoce la conexión (Constitution
III). Las consultas se hacen siempre desde el módulo de YouTube.

**Validaciones de dominio** (en código):

- Solo se crea una fila para cuentas con `platform = 'youtube'`. Las demás plataformas nunca
  tienen fila.
- Crear o sustituir requiere cuenta y proyecto activos (FR-013). Borrar (desconectar), no.
- `project_id` se toma siempre de la cuenta; nunca viene del cliente.
- La información del canal se actualiza al reconectar y al verificar. El `channel_id` solo
  cambia mediante una sustitución confirmada.

**Nunca se guarda en esta tabla**: access token, refresh token, código de autorización,
`code_verifier`, `state`, client secret, scopes concedidos ni caducidad del token.

### Estados y transiciones

```text
                 authorize + callback OK (canal libre en el proyecto)
 not_connected ─────────────────────────────────────────────────────▶ connected
 (sin fila)    ◀───────────────────── disconnect ──────────────────── │  ▲
      ▲                                                                │  │ reconnect OK
      │ disconnect                     refresh invalid_grant /         │  │ (mismo canal o
      │                                secreto ausente / canal         ▼  │  cambio confirmado)
      └──────────────────────────────  distinto al verificar ──▶ reconnect_required
```

| Desde | Evento | Hacia | Notas |
|-------|--------|-------|-------|
| `not_connected` | Callback válido, canal único y libre | `connected` | Inserta la fila. |
| `connected` / `reconnect_required` | Callback válido, mismo channel ID | `connected` | Nuevas credenciales; se borra el secreto antiguo. |
| `connected` / `reconnect_required` | Callback válido, otro channel ID | *(sin cambio)* | El intento queda `awaiting_confirmation`. |
| `connected` / `reconnect_required` | Sustitución confirmada | `connected` | Actualiza el canal y las credenciales. |
| `connected` | Refresh `invalid_grant`, secreto ausente, `401` tras refresh, scopes insuficientes o channel ID distinto al verificar | `reconnect_required` | |
| `connected` | Error transitorio (red, `5xx`, `429`) | `connected` | Responde `youtube_unavailable`. |
| `connected` / `reconnect_required` | Disconnect | `not_connected` | Borra el secreto y la fila. No contacta con Google ni revoca el permiso (research §13). |
| `not_connected` | Disconnect | `not_connected` | Idempotente. |

Desactivar una cuenta o un proyecto **no** cambia el estado de conexión.

---

## Credenciales de cuenta (almacén seguro)

- Entrada `keyring`: servicio `autopublisher.youtube`, usuario `credential_ref`.
- Solo se escribe, lee o borra tras comprobar que el backend efectivo de `keyring` está en
  la lista blanca de backends seguros (research §8). Si no lo está, o está bloqueado o no
  disponible, la operación falla con `credential_store_unavailable`, sin almacenamiento
  alternativo.
- Valor: JSON compacto.

| Campo | Descripción |
|-------|-------------|
| `access_token` | Token de acceso vigente. |
| `refresh_token` | Credencial renovable. Obligatoria para completar una conexión. |
| `expires_at` | ISO 8601 UTC de caducidad del access token. |
| `scopes` | Scopes concedidos según la respuesta de token. |

Ciclo de vida (research §10):

- Se crea antes del `commit` de la fila.
- Se actualiza en cada refresh.
- Se borra al desconectar, al sustituir (la antigua) o como compensación si falla el
  `commit`.

---

## OAuthAttempt (en memoria)

Estado temporal de una autorización iniciada. Lo gestiona `OAuthAttemptRegistry` en
`app.state`. **No se persiste** y no sobrevive a un reinicio.

| Campo | Descripción | ¿Expuesto en la API? |
|-------|-------------|----------------------|
| `attempt_id` | `secrets.token_urlsafe(16)`; identificador para el sondeo del frontend. | Sí |
| `account_id` | Cuenta destino. | Sí |
| `state` | `secrets.token_urlsafe(32)`; de un solo uso. | No (solo va en la URL de autorización) |
| `code_verifier` | PKCE, 86 caracteres; se borra en cuanto el intento termina. | **Nunca** |
| `created_at` / `expires_at` | Validez de 10 minutos. | `expires_at` sí |
| `finished_at` / `retain_until` | Momento en que el intento llegó a un estado terminal, y `finished_at` + 10 min. | No |
| `status` | Ver abajo. | Sí |
| `error` | `{code, message}` si `failed`. | Sí |
| `current_channel` | Canal vinculado al iniciar (para la advertencia). | Sí, sin secretos |
| `new_channel` | Canal identificado por la autorización. | Sí, sin secretos |
| `pending_credentials` | Credenciales nuevas a la espera de confirmar la sustitución. | **Nunca** |

### Estados del intento

| Estado | Significado | Terminal |
|--------|-------------|----------|
| `pending` | Esperando el callback de Google. | No |
| `awaiting_confirmation` | Canal distinto del vinculado; esperando confirmar o cancelar. | No |
| `completed` | Conexión creada o actualizada. | Sí |
| `failed` | Error (incluida la cancelación por el usuario en Google, `oauth_cancelled`). | Sí |
| `cancelled` | El usuario canceló la sustitución en AutoPublisher. | Sí |
| `expired` | Superó los 10 minutos o lo invalidó una autorización más reciente de la misma cuenta. | Sí |

Transiciones:

- `pending` → `completed` | `failed` | `awaiting_confirmation` | `expired`.
- `awaiting_confirmation` → `completed` | `failed` | `cancelled` | `expired`.

**Regla única de caducidad y retención**:

1. Un intento `pending` o `awaiting_confirmation` que supera su `expires_at` (creación +
   10 min) pasa a `expired`. Su `state` deja de ser utilizable.
2. Al llegar a cualquier estado terminal (`completed`, `failed`, `cancelled` o `expired`)
   se registra `finished_at`. En ese momento se borran sus secretos (`code_verifier`,
   credenciales pendientes).
3. El intento terminal se **conserva** en memoria, sin secretos, durante **10 minutos
   adicionales** (`retain_until = finished_at + 10 min`). Durante ese periodo,
   `GET /api/youtube/oauth/attempts/{id}` lo devuelve con su estado (por ejemplo
   `expired`).
4. Pasado `retain_until`, el intento se purga y `GET` devuelve
   `404 oauth_attempt_not_found`. Lo mismo ocurre tras un reinicio del backend.

Al llegar a un estado terminal se borran `code_verifier` y `pending_credentials`. Las
credenciales pendientes sin usar se olvidan en memoria y no se revocan en Google
(research §13).

---

## Configuración OAuth de AutoPublisher

- Archivo JSON descargado de Google Cloud Console para un cliente **Desktop app**.
- Ruta por defecto: `backend/data/google-oauth-client.json`.
- Ruta configurable con `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`.
- Se usan `installed.client_id` e `installed.client_secret`. Los endpoints de Google son
  constantes del código.
- URI de redirección: `AUTOPUBLISHER_OAUTH_REDIRECT_URI`, por defecto
  `http://127.0.0.1:8000/api/youtube/oauth/callback`. Debe ser `http` sobre `127.0.0.1` o
  `[::1]`.
- Se lee en cada operación que lo necesita. Si no se puede usar, la respuesta es
  `oauth_not_configured`.

---

## Información expuesta por la API (no sensible)

`YouTubeConnectionRead` (ver [contracts/api.md](contracts/api.md)):

- `status`;
- `channel` (`id`, `title`, `handle`, `thumbnail_url`), o `null`;
- `connected_at`;
- `last_verified_at`;
- `oauth_configured`: booleano no sensible que indica si la configuración OAuth local es
  utilizable. Se calcula en cada petición.

Solo la devuelve el endpoint específico `GET /api/accounts/{id}/youtube-connection` (y las
respuestas de `verify`, `disconnect` y `OAuthAttempt.connection`). `AccountRead` **no
cambia** y no incluye nada de YouTube.
