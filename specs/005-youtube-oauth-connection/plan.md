# Implementation Plan: Conexión segura de cuentas de YouTube mediante OAuth 2.0

**Branch**: `005-youtube-oauth-connection` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-youtube-oauth-connection/spec.md`

## Summary

Conectar una `Account` YouTube existente con su canal real mediante OAuth 2.0, guardar las
credenciales solo en el almacén seguro del sistema y dejar la conexión lista para la futura
subida de vídeos. No se sube nada.

**Flujo OAuth**:

- Cliente Google de tipo **Desktop app**.
- *Authorization Code* + **PKCE `S256`** + `state` de un solo uso.
- Redirección loopback al propio backend:
  `http://127.0.0.1:8000/api/youtube/oauth/callback`.
- Scopes mínimos verificados en el discovery document oficial: `youtube.readonly`
  (identificar el canal) + `youtube.upload` (siguiente feature).
- Connect y Reconnect piden **siempre** `access_type=offline` + `prompt=consent` (más
  `select_account`), para obtener un refresh token nuevo aunque el grant siga vivo en Google
  tras un `Disconnect`. El usuario ve el consentimiento cada vez, de forma intencionada. Sin
  refresh token, la conexión no se completa.
- Los intentos pendientes (`state`, `code_verifier`, credenciales a la espera de
  confirmación) viven solo en memoria, con validez de 10 min.

**Backend**:

- Tabla `youtube_connections` (migración `0004`) con datos públicos del canal, `status`
  (`connected` | `reconnect_required`) y un `credential_ref` no secreto.
  - `UNIQUE(account_id)`.
  - `UNIQUE(project_id, channel_id)`: un canal por proyecto, incluidas las cuentas
    inactivas.
- Credenciales en `keyring` (**nueva dependencia**; Secret Service / Keychain / Credential
  Locker). Antes de guardar, leer o borrar se comprueba que el backend efectivo está en una
  lista blanca de backends seguros. Si no lo está, o está bloqueado o no disponible, falla
  con `credential_store_unavailable`, nunca con un archivo plano como alternativa.
- Gateway HTTP propio y pequeño sobre `httpx2` para tres llamadas a Google:
  1. intercambio de código;
  2. refresh;
  3. `channels.list?mine=true`.
- El canal efectivo se acepta solo si `channels.list` devuelve exactamente uno.
- `Disconnect` elimina siempre, de forma local, las credenciales del almacén y la referencia
  en SQLite, **sin revocar** el permiso en Google: la revocación afecta al grant completo y
  podría romper otras conexiones. La UI explica cómo retirarlo manualmente.
- Router `youtube_connections.py` con:
  - estado;
  - `authorize`;
  - callback HTML;
  - sondeo de intentos;
  - `confirm` / `cancel` de cambio de canal;
  - `verify`;
  - `disconnect`.

**Frontend**:

- Panel de conexión en cada cuenta YouTube de la lista de cuentas. Carga su propio estado
  con `GET /api/accounts/{id}/youtube-connection`, solo para cuentas YouTube; el núcleo de
  cuentas (`AccountRead`, `Account`, `accounts.py`) no cambia. Incluye:
  - estado (`Not connected` / `Connected` / `Reconnect required`);
  - si `oauth_configured` es `false`: instrucciones de configuración, sin abrir pestañas;
  - canal real (título, channel ID, handle, miniatura);
  - botones **Connect** / **Reconnect** / **Verify connection** / **Disconnect**;
  - sondeo del intento;
  - advertencia de cambio de canal con confirmación explícita.

Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**:

- Existentes: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic; React + Vite.
- **Nuevas (backend)**:
  - **`keyring` (≥ 25)**: **dependencia nueva** para el almacén seguro del SO. En Linux
    instala automáticamente `SecretStorage` y `jeepney` (Python puro) y requiere un
    proveedor de Secret Service en la sesión (GNOME Keyring o KWallet) con D-Bus de sesión.
    Requisitos detallados en research §8.
  - `httpx2`: pasa de dependencia de desarrollo a dependencia de ejecución, para el gateway
    de Google.
- Ningún SDK de Google (research §2).
- **Frontend**: ninguna dependencia nueva.

**Storage**:

- SQLite: tabla nueva `youtube_connections`.
- Almacén seguro del SO: secretos por conexión.
- Archivo local no versionado con el cliente OAuth (`backend/data/google-oauth-client.json`
  o `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`).

**Testing**:

- Backend: pytest + `TestClient`, con `create_app(...)` inyectando:
  - un `httpx2.MockTransport` que simula a Google;
  - un `InMemoryCredentialStore`;
  - un archivo de cliente ficticio en `tmp_path`.

  Sin Internet ni llavero real.
- Frontend: Vitest + Testing Library con `FakeApi` ampliado y temporizadores falsos para el
  sondeo.

**Quality tooling**: sin cambios (Ruff, mypy strict; Oxlint, Prettier, `tsc -b`). Workflow de
CI sin cambios: los tests no necesitan Secret Service.

**Target Platform**: uso local en Linux con Secret Service (Ubuntu Desktop: `gnome-keyring`
incluido; otras variantes: `sudo apt install gnome-keyring`), macOS o Windows. No se soportan
sesiones Linux sin D-Bus ni Secret Service. CI en `ubuntu-latest`, sin llavero: los tests
inyectan un almacén en memoria.

**Project Type**: aplicación web local (frontend + backend separados).

**Performance Goals**: conexión visible en AutoPublisher < 10 s tras conceder el permiso
(SC-002). El sondeo cada 2 s más el tiempo del callback lo cumplen.

**Constraints**:

- Ningún token, código, `code_verifier` ni client secret en SQLite, logs, respuestas, HTML ni
  `localStorage` (FR-023).
- Sin almacenamiento alternativo inseguro (FR-024).
- Nunca una fila sin secreto (FR-025).
- Sin sustitución silenciosa de canal (FR-018).
- Unicidad canal–proyecto garantizada en la base (FR-020).
- Fallos transitorios ≠ `reconnect_required` (FR-029).
- Tests sin Internet (FR-041).

**Scale/Scope**:

- 1 tabla nueva.
- 8 rutas nuevas. `AccountRead` y las rutas de cuentas no cambian.
- 4 módulos backend nuevos.
- 1 componente de interfaz nuevo.

No quedan `NEEDS CLARIFICATION`. Todas las decisiones que la spec difería al plan quedan
resueltas en [research.md](research.md):

| Decisión | Dónde |
|----------|-------|
| Flujo y callback | §1, §6 |
| Librerías | §2 |
| Scopes | §3 |
| Almacén seguro y Linux | §8 |
| Unicidad en base de datos | §9 |
| Sin revocación al desconectar | §13 |
| Canal efectivo | §7 |
| PKCE | §5 |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Dos dependencias justificadas: `keyring` la exige el principio IV; `httpx2` ya estaba en el árbol. Se evita el SDK de Google y sus dependencias transitivas. Intentos en memoria, sin tablas ni infraestructura extra. Sondeo HTTP en lugar de WebSocket/SSE. Sin capa de servicios genérica. Nada del alcance excluido: subida, scheduler, `PublicationAttempt`, otras plataformas. | ✅ |
| II. Spec-Driven Development | El plan implementa la spec ajustada (PKCE y canal inequívoco incluidos). Las decisiones diferidas por la spec quedan justificadas en research. Los defaults de la spec se respetan: sin confirmación extra en la primera conexión, desactivar no desconecta, intentos de unos 10 min. | ✅ |
| III. Arquitectura modular | Lo específico de YouTube y Google queda aislado en `youtube_oauth.py`, `youtube_gateway.py` y `youtube_connections.py`. Los secretos, en `credential_store.py`, independiente de la plataforma. El núcleo de cuentas no conoce YouTube: `accounts.py` no importa módulos de YouTube, `AccountRead` no cambia y el modelo `Account` no declara la relación inversa. La conexión es una tabla aparte con FK hacia `accounts`, consultada solo desde el módulo de YouTube y por un endpoint específico (decisión C1 del análisis, opción A). El gateway es el embrión del futuro *publisher adapter* de YouTube. | ✅ |
| IV. Seguridad (repositorio público) | Tokens solo en el almacén seguro del SO. Client secret en un archivo bajo `data/` (ignorado), más patrones extra en `.gitignore`. Sin archivo de ejemplo con valores falsos. PKCE + `state`. Tokens enviados en cuerpo o cabecera, nunca en URL. Logs sin datos sensibles, verificado por tests. Lista blanca de backends de `keyring`, sin alternativa en claro. `Disconnect` elimina siempre los secretos locales; retirar el permiso en Google queda en manos del usuario, con instrucciones. OAuth oficial de Google, sin scraping. | ✅ |
| V. Calidad y verificabilidad | Tests para todos los casos pedidos, con el gateway real sobre un transporte falso. Los errores son visibles: el intento conserva el error y la UI lo muestra. Los fallos no pierden datos: las desconexiones fallidas mantienen la fila y las sustituciones no confirmadas mantienen la conexión anterior. | ✅ |
| VI. Git y trazabilidad | Rama `005-youtube-oauth-connection`. Commits pequeños en inglés. README con la sección "Connecting YouTube" (configuración de Google Cloud, archivo de cliente, almacén seguro, limitaciones). | ✅ |
| Arquitectura tecnológica base | FastAPI + SQLite + REST. "Almacenamiento seguro del sistema operativo para tokens", exactamente como prevé la Constitution. | ✅ |
| Idioma y convenciones | Código, mensajes de API, UI y HTML del callback, README y commits en inglés. Artefactos Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS. El diseño de Fase 1 no
añade dependencias ni estructura más allá de lo listado.

## Project Structure

### Documentation (this feature)

```text
specs/005-youtube-oauth-connection/
├── plan.md              # Este archivo
├── research.md          # Fase 0: flujo, librerías, scopes, PKCE, canal, almacén, desconexión…
├── data-model.md        # Fase 1: YouTubeConnection, credenciales, OAuthAttempt, estados
├── quickstart.md        # Fase 1: validación automática y manual con Google real
├── contracts/
│   └── api.md           # Fase 1: contrato REST + callback HTML
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
.gitignore                           # + client_secret*.json, google-oauth-client*.json

backend/
├── pyproject.toml                   # + keyring (nueva dependencia); httpx2 pasa a
│                                    #   dependencies
├── migrations/versions/
│   └── 0004_create_youtube_connections.py
├── app/
│   ├── config.py                    # + get_google_oauth_client_file(),
│   │                                #   get_oauth_redirect_uri() (validada: http loopback)
│   ├── main.py                      # create_app(..., credential_store=None,
│   │                                #   google_transport=None); registro de intentos y
│   │                                #   gateway en app.state; + include_router
│   ├── errors.py                    # + AppError(status_code, code, message) y su manejador;
│   │                                #   ConflictCode + platform_not_supported,
│   │                                #   channel_already_connected, connection_changed,
│   │                                #   not_connected, reconnect_required,
│   │                                #   oauth_attempt_not_confirmable
│   ├── models.py                    # + YouTubeConnectionStatus (StrEnum), YouTubeConnection
│   │                                #   (FK a accounts; Account sin relación inversa;
│   │                                #   nombres de constraints = migración)
│   ├── schemas.py                   # + YouTubeChannelRead, YouTubeConnectionRead
│   │                                #   (incl. oauth_configured), AuthorizeRead,
│   │                                #   OAuthAttemptRead; AccountRead SIN cambios
│   │                                # (accounts.py NO cambia: sin imports de YouTube)
│   ├── credential_store.py          # CredentialStore (Protocol), KeyringCredentialStore,
│   │                                #   CredentialStoreUnavailable; ensure_secure_backend()
│   │                                #   con lista blanca (incl. chainer) antes de cada
│   │                                #   set/get/delete; KeyringError/Locked → unavailable
│   ├── youtube_oauth.py             # Funciones puras: generate_state, generate_pkce_pair,
│   │                                #   build_authorization_url, load_client_config,
│   │                                #   SCOPES; OAuthAttemptRegistry (memoria + Lock, TTL
│   │                                #   10 min → expired; retención 10 min sin secretos)
│   ├── youtube_gateway.py           # GoogleGateway(httpx2.Client): exchange_code,
│   │                                #   refresh, list_my_channels; TokenSet,
│   │                                #   ChannelInfo; excepciones InvalidGrant,
│   │                                #   GoogleUnavailable, GoogleRejected
│   └── youtube_connections.py       # Router y reglas: estado, authorize, callback (HTML),
│                                    #   attempts (get/confirm/cancel), verify, disconnect;
│                                    #   get_valid_credentials (refresh con lock por cuenta)
└── tests/
    ├── conftest.py                  # + fixtures fake_google (MockTransport programable),
    │                                #   credential_store (InMemory), oauth_client_file,
    │                                #   youtube_client; helper connect_youtube(...)
    ├── fakes.py                     # FakeGoogle, InMemoryCredentialStore
    ├── test_youtube_oauth.py        # PKCE (longitud, alfabeto, S256), URL de
    │                                #   autorización (siempre access_type=offline y
    │                                #   prompt con consent), registro (un solo uso, TTL, la más
    │                                #   reciente gana), config ausente/inválida, redirect
    ├── test_credential_store.py     # Lista blanca aceptada; fail/null/keyrings.alt/
    │                                #   desconocido/chainer con inseguro rechazados;
    │                                #   Locked/KeyringError → unavailable sin escribir nada
    ├── test_youtube_gateway.py      # Mapeo de respuestas: invalid_grant vs 5xx/timeout,
    │                                #   scopes, sin refresh_token
    ├── test_youtube_connect.py      # Iniciar, no YouTube, inexistente, inactivos, sin
    │                                #   config, callback OK, canal identificado, 0/2 canales,
    │                                #   state válido/inválido/reusado/caducado, cancelado,
    │                                #   intercambio fallido, YouTube caído, desactivar
    │                                #   durante el intento
    ├── test_youtube_reconnect.py    # Mismo canal (sustituye y borra secreto viejo), canal
    │                                #   distinto → confirm/cancel/caducidad/connection_changed,
    │                                #   duplicado en proyecto (incl. inactiva), otro proyecto
    ├── test_youtube_refresh.py      # verify con token vigente, refresh OK (persistido),
    │                                #   invalid_grant → reconnect_required, transitorio sin
    │                                #   cambio, secreto ausente, channel ID distinto
    ├── test_youtube_disconnect.py   # Borra secreto y fila, cuenta y publicaciones intactas,
    │                                #   ninguna petición a Google, sin config OAuth,
    │                                #   idempotente, inactivos, almacén caído conserva la fila
    ├── test_youtube_secrets.py      # Ningún valor sensible del fake en SQLite (.dump),
    │                                #   respuestas JSON/HTML ni caplog
    ├── test_accounts.py             # + AccountRead sin campos de YouTube; accounts.py no
    │                                #   importa módulos youtube_*
    ├── test_persistence.py          # + conexión sobrevive al reinicio (mismo store)
    └── test_migrations.py           # + 0004 sobre base con datos de 0003; restricciones

frontend/src/
├── types.ts                         # + YouTubeConnectionStatus, YouTubeChannel,
│                                    #   YouTubeConnection (incl. oauth_configured),
│                                    #   OAuthAttempt, etiquetas; Account SIN cambios
├── api.ts                           # + getYouTubeConnection, authorizeYouTube, getOAuthAttempt,
│                                    #   confirmOAuthAttempt, cancelOAuthAttempt,
│                                    #   verifyYouTubeConnection, disconnectYouTube
├── test-fake-api.ts                 # + conexiones e intentos en memoria
├── index.css                        # + estilos del panel y badges de conexión
└── components/
    ├── AccountList.tsx              # Renderiza YouTubeConnectionPanel solo si
    │                                #   platform === "youtube"; recibe projectActive
    ├── ProjectDetail.tsx            # Pasa project.is_active a AccountList
    ├── YouTubeConnectionPanel.tsx   # Carga su estado (getYouTubeConnection), canal,
    │                                #   instrucciones si !oauth_configured, botones,
    │                                #   apertura/cierre de pestaña, sondeo, advertencia de
    │                                #   cambio de canal, errores
    └── YouTubeConnectionPanel.test.tsx  # Not connected/Connected/Reconnect required,
                                     #   oauth_configured=false (sin pestaña), cierre de
                                     #   pestaña si authorize falla, otras plataformas sin
                                     #   panel ni peticiones, inactivos,
                                     #   connect→completed, failed, cambio de
                                     #   canal (replace/keep), verify, disconnect

README.md                            # + "Connecting YouTube": Google Cloud, archivo de
                                     #   cliente, almacén seguro (keyring; requisitos
                                     #   Linux/Ubuntu: gnome-keyring/KWallet, D-Bus, llavero
                                     #   desbloqueado; comprobación del backend), Disconnect
                                     #   sin revocación y cómo retirar el permiso a mano,
                                     #   consentimiento en cada Connect/Reconnect
                                     #   (prompt=consent, intencionado),
                                     #   limitaciones (Testing 7 días), rutas de la API
```

**Structure Decision**: se mantienen `backend/` y `frontend/` con el paquete plano `app/`.

- La integración de YouTube se reparte en tres módulos con responsabilidades separadas:
  - lógica pura de OAuth y registro de intentos;
  - HTTP con Google;
  - router y reglas de dominio.
- El almacén de secretos queda en un módulo independiente de la plataforma, reutilizable
  por futuras integraciones.
- No se introduce una capa de servicios genérica ni una jerarquía de adaptadores todavía
  (Constitution I). Esa interfaz común llegará con la feature de publicación, cuando exista
  una segunda operación real.

## Design Notes

- **Inyección para tests**: `create_app(db_path, media_dir, *, credential_store=None,
  google_transport=None)`. Por defecto usa `KeyringCredentialStore()` y el transporte HTTP
  real. `GoogleGateway` recibe un `httpx2.Client(transport=..., timeout=10)` que se crea en
  el `lifespan` y se cierra al terminar.
- **Endpoints síncronos** (`def`), como el resto del proyecto. Se ejecutan en el
  *threadpool*, de ahí:
  - el `threading.Lock` del registro de intentos;
  - un `dict[int, Lock]` por cuenta para el refresh.
- **Callback**:
  1. Si `state` no existe en el registro, se devuelve HTML `400` sin tocar nada.
  2. Si existe, se **consume primero** y después se procesa, de modo que cualquier error
     queda en el intento.
  3. Las validaciones siguen el orden del contrato. La comprobación de cuenta y proyecto
     activos (`ensure_account_connectable`) forma parte del callback **desde su primera
     implementación (US1)** y se hace antes del intercambio del código.
  4. Un fallo inesperado termina el intento como `failed` / `internal_error`, con un mensaje
     genérico.
  5. Estado HTTP de la página: `200` en `completed` y `awaiting_confirmation`; `400` en
     errores OAuth o de validación esperados; `500` solo en `internal_error`.
  6. El HTML se genera con una plantilla mínima en código, con `html.escape` del mensaje,
     sin scripts ni recursos externos.
- **Completar la conexión** (función compartida por el callback y `confirm`), dentro de una
  sesión:
  1. recargar la cuenta y comprobar que está activa, igual que su proyecto;
  2. comprobar el conflicto de canal en el proyecto (consulta por `project_id`,
     `channel_id`, `account_id != ...`);
  3. `store.set(new_ref, json)`;
  4. insertar o actualizar la fila y hacer `commit`. Ante cualquier fallo posterior a
     `store.set` (incluido un `IntegrityError` → `channel_already_connected`), rollback e
     intento inmediato de `store.delete(new_ref)`. Si ese borrado también falla porque el
     almacén no está disponible, queda una entrada huérfana sin referencia, que no se
     detecta ni limpia después (spec FR-025, research §10);
  5. `store.delete(old_ref)` sin bloquear (mismo caso: si falla, entrada huérfana).
- **Descartar credenciales** (canal 0/ambiguo, scopes, conflicto, cancelar, caducar con
  credenciales pendientes): se olvidan en memoria. Nunca se escriben en el almacén y no se
  revocan en Google (research §13).
- **`get_valid_credentials`**: devuelve un `TokenSet` con el access token vigente. Usa un
  margen de 60 s antes de `expires_at`. Las excepciones del gateway se traducen así:
  - `InvalidGrant` → marca `reconnect_required` (commit) y lanza
    `ConflictError("reconnect_required")`;
  - `GoogleUnavailable` → `AppError(503, "youtube_unavailable")`.
- **Verify**:
  1. `get_valid_credentials`;
  2. `list_my_channels`;
  3. resultado:
     - el mismo `channel_id` (único) → actualizar los datos públicos y
       `last_verified_at`;
     - un `401` → un refresh forzado y un reintento;
     - si persiste, o hay un `403` de permisos o un channel ID distinto →
       `reconnect_required`.
- **Disconnect** (local, sin contactar con Google):
  1. cargar la fila (si no existe → devolver `not_connected`, idempotente);
  2. `store.delete(credential_ref)` (un secreto ya ausente no es error; almacén no seguro o
     no disponible → `credential_store_unavailable` y la fila **se conserva** para poder
     reintentar);
  3. **solo tras borrar el secreto con éxito**, borrar la fila y hacer `commit`;
  4. expirar los intentos de la cuenta.

  No requiere el archivo de cliente ni red.
- **Independencia del núcleo de cuentas**:
  - `accounts.py`, `AccountRead` y el modelo `Account` no cambian;
  - `youtube_connections.py` consulta `YouTubeConnection` por `account_id`;
  - un test comprueba que `AccountRead` no tiene campos de YouTube y que `app.accounts` no
    importa módulos `app.youtube_*`.
- **`oauth_configured`**: `GET .../youtube-connection` (y el resto de respuestas
  `YouTubeConnectionRead`) lo calcula intentando `load_client_config()` en cada petición, y
  solo expone el booleano.
- **Seguridad de logs**:
  - el gateway no registra cuerpos ni URLs con query;
  - las excepciones propias tienen mensajes fijos;
  - `httpx2` registra la URL de la petición en nivel INFO, pero ninguna URL lleva secretos:
    el intercambio y el refresh van en el cuerpo, y `channels.list` usa la cabecera
    `Authorization`.
- **`.gitignore`**: se añaden `client_secret*.json` y `google-oauth-client*.json`, además de
  `data/`, que ya está ignorado.
- **Frontend `YouTubeConnectionPanel`**:
  - **Carga**: al montarse, `getYouTubeConnection(account.id)`. `AccountList` solo monta el
    panel para cuentas YouTube, así que las demás plataformas no hacen ninguna petición.
  - **Sin configuración** (`oauth_configured === false`): **Connect**/**Reconnect** no
    abren nada. Se muestra "YouTube OAuth is not configured. See 'Connecting YouTube' in the
    README", con los pasos clave.
  - **Connect/Reconnect** (solo con `oauth_configured === true`). **Reconnect**, tanto desde
    `reconnect_required` como acción secundaria desde `connected`, usa el **mismo handler**
    que **Connect**, con exactamente las mismas protecciones:
    1. `const tab = window.open("", "_blank")` de forma síncrona en el clic;
    2. `authorizeYouTube`;
    3. `tab.location.href = authorization_url`. Si `tab` es `null`, se muestra el enlace.
    4. **Defensa secundaria**: si `authorizeYouTube` falla, `tab?.close()` y se muestra el
       error.
  - **Sondeo**: `getOAuthAttempt` cada 2 s hasta `completed` / `failed` / `cancelled` /
    `expired` / `awaiting_confirmation`. Se limpia al desmontar o al cambiar de cuenta.
  - **Retención del intento** (regla de [data-model.md](data-model.md)): un intento que
    supera su validez pasa a `expired` y se sigue devolviendo 10 minutos más, sin
    secretos; después `GET` responde `404`, que el panel trata como `expired`.
  - Al llegar a `completed` (y tras confirm, verify o disconnect), el panel vuelve a
    cargar su propio estado con `getYouTubeConnection`.
  - **Advertencia de cambio de canal**: tarjeta con "Current channel" y "New channel"
    (título + channel ID) y los botones **Replace with this channel** / **Keep current
    channel**.
  - **Botones**:
    - **Connect** / **Reconnect**: deshabilitados con explicación si la cuenta o el
      proyecto están inactivos;
    - **Disconnect**: siempre disponible con conexión, pide confirmación
      (`window.confirm`). Tras desconectar muestra la nota: "AutoPublisher deleted its stored
      credentials. To fully remove AutoPublisher's access to your Google account, go to
      myaccount.google.com/connections." (con enlace). La nota advierte de que esa retirada
      afecta a todas las conexiones de AutoPublisher que usen esa cuenta de Google;
    - **Verify connection**: solo en `connected`.
  - Los errores usan `toApiError(...).message` o `attempt.error.message`.
- **Migración `0004`**: crea la tabla con FKs `RESTRICT`, las tres restricciones únicas y el
  `CHECK`, con **exactamente los mismos nombres** que genera la convención del modelo
  ([data-model.md](data-model.md), tabla de nombres). El test de deriva de modelos frente a
  migraciones existente la cubre.
- **CI**: sin cambios. `keyring` se instala pero no se usa en tests (el store se inyecta), y
  CI no necesita Secret Service.
  - Un fixture `autouse` en `conftest.py` hace `keyring.set_keyring(fail.Keyring())` y
    restaura el backend original al terminar.
  - `test_credential_store.py` sustituye ese backend dentro de cada test con
    `keyring.set_keyring(...)`.
- **mypy**: `keyring` incluye anotaciones. Si alguna API carece de tipos, se añade un
  override `ignore_missing_imports` acotado a `keyring.*`, nunca global.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.

| Elemento | Por qué es necesario | Alternativa más simple descartada |
|----------|----------------------|------------------------------------|
| Dependencia `keyring` | Principio IV y FR-022: tokens en el almacén seguro del SO. | Archivo o SQLite cifrados: la clave no tendría un lugar seguro donde guardarse; además, prohibido por la spec. |
| Registro de intentos en memoria con lock | `state`/PKCE de un solo uso, caducidad y confirmación de cambio de canal sin persistir secretos. | Persistir en SQLite: prohibido para el `code_verifier` y las credenciales pendientes. |
