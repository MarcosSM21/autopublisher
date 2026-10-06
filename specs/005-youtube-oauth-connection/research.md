# Research: Conexión segura de cuentas de YouTube mediante OAuth 2.0

**Feature**: `005-youtube-oauth-connection` | **Fecha**: 2026-10-06

Fuentes oficiales consultadas el 2026-10-06:

- [OAuth 2.0 for iOS & Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)
  (caducidad de refresh tokens)
- [YouTube Data API – channels.list](https://developers.google.com/youtube/v3/docs/channels/list)
  y [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- Discovery document oficial de YouTube Data API v3
  (`https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest`, revisión `20261005`),
  campo `scopes` de cada método.

---

## 1. Flujo OAuth para una aplicación local

**Decision**: flujo *Authorization Code* para **aplicaciones instaladas** (cliente OAuth de
tipo **Desktop app**) con **PKCE `S256`**, `state` y **redirección loopback** al propio
backend: `http://127.0.0.1:8000/api/youtube/oauth/callback`.

**Rationale**:

- Es el método que Google recomienda para aplicaciones de escritorio en Linux, macOS y
  Windows. La autorización ocurre en el navegador del usuario.
- Los clientes Desktop aceptan cualquier puerto loopback sin registrarlo, y la ruta es
  opcional y libre. Así el backend FastAPI, que ya escucha en `127.0.0.1:8000`, recibe el
  callback sin levantar otro servidor.
- Se usa `127.0.0.1` y no `localhost`, como recomienda Google (evita problemas de firewall y
  de resolución).
- La URI es configurable (`AUTOPUBLISHER_OAUTH_REDIRECT_URI`) para quien arranque el backend
  en otro puerto. Se valida que sea `http` sobre `127.0.0.1` o `[::1]`.

**Alternatives considered**:

- *Copiar y pegar el código (OOB)*: deprecado por Google.
- *Esquema de URI personalizado*: ya no soportado por Google.
- *Servidor loopback temporal con puerto dinámico por autorización* (estilo
  `run_local_server` de `google-auth-oauthlib`): es lo que Google sugiere en general, pero
  añade un segundo servidor, hilos y ciclo de vida propios. El backend ya es un servidor
  loopback, así que no aporta nada.
- *Cliente de tipo Web application*: exige registrar URIs de redirección exactas y no es el
  tipo pensado para una app local.

## 2. Librerías

**Decision**: **sin SDK de Google**. Un *gateway* propio y pequeño (`app/youtube_gateway.py`)
hace las tres llamadas HTTP necesarias con **`httpx2`**:

1. intercambio de código;
2. refresh;
3. `channels.list`.

No hay llamada de revocación (decisión 13).

Dependencias de ejecución del backend que cambian:

- **`keyring`** (≥ 25): **dependencia nueva** para el almacén seguro (decisión 8).
- **`httpx2`**: pasa de dependencia de desarrollo a dependencia de ejecución.

**Rationale**:

- Son tres peticiones de formulario/JSON bien documentadas. Un cliente propio permite
  mapear con precisión cada respuesta a los errores de la spec, en particular distinguir un
  `invalid_grant` definitivo de un fallo transitorio (FR-029).
- `httpx2` ya está en el árbol: Starlette lo usa para `TestClient`. Su `MockTransport`
  permite probar el gateway **real** sin Internet (FR-041). Los fakes simulan a Google a
  nivel HTTP, no sustituyen nuestro código.
- Evita `requests` + `oauthlib`:
  - `oauthlib` exige HTTPS en la URI de redirección salvo con
    `OAUTHLIB_INSECURE_TRANSPORT`;
  - lanza excepciones cuando el usuario concede menos scopes (consentimiento granular);
  - oculta los detalles del error de Google.
- PKCE, `state` y la URL de autorización son funciones puras que se prueban directamente.

**Alternatives considered**:

- *`google-auth-oauthlib` + `google-auth`*: oficiales, pero arrastran `requests`,
  `requests-oauthlib` y `oauthlib`. El problema de HTTPS y de cambio de scopes obliga a
  variables de entorno globales, y los tests necesitarían parchear internos.
- *`google-api-python-client`*: pesado (discovery dinámico) para una sola llamada de
  lectura. La feature de subida de vídeos podrá reconsiderarlo para la subida *resumable*.
- *`httpx` (0.28)*: equivalente, pero sería una segunda librería HTTP cuando `httpx2` ya
  está presente.

## 3. Scopes mínimos

**Decision**: solicitar exactamente:

- `https://www.googleapis.com/auth/youtube.readonly`: identificar el canal con
  `channels.list?mine=true`;
- `https://www.googleapis.com/auth/youtube.upload`: preparar `videos.insert` para la
  siguiente feature.

Al completar la autorización se comprueba el campo `scope` de la respuesta de token. Si
falta cualquiera de los dos (el usuario desmarcó un permiso en el consentimiento granular),
la conexión no se completa (`oauth_scope_insufficient`).

**Rationale** (discovery document, revisión `20261005`):

- `channels.list` admite `youtube`, `youtube.force-ssl`, `youtube.readonly`,
  `youtubepartner` y `youtubepartner-channel-audit`. **No** admite `youtube.upload`.
- `videos.insert` admite `youtube`, `youtube.force-ssl`, `youtube.upload` y
  `youtubepartner`.
- Ningún scope cubre ambas operaciones salvo `youtube` ("Manage your YouTube account") o
  `youtube.force-ssl` ("See, edit, and permanently delete your YouTube videos, ratings,
  comments and captions"), mucho más amplios.
- La combinación mínima es, por tanto, `youtube.readonly` + `youtube.upload`.

**Alternatives considered**:

- *Solo `youtube`*: un único scope, pero concede gestión completa de la cuenta.
- *`youtube.force-ssl`*: permite borrar vídeos y comentarios; innecesario.
- *Solo `youtube.upload`*: no permite identificar el canal.
- *`include_granted_scopes=true`*: no se usa, para no acumular scopes de autorizaciones
  anteriores en el mismo token.

**Nota para la siguiente feature**: los vídeos subidos desde proyectos de API no
verificados (creados después del 28-07-2020) quedan restringidos a visibilidad privada
hasta superar la auditoría de Google. Es una limitación de la subida, no de esta feature;
se menciona en `quickstart.md`.

## 4. Parámetros de autorización

**Decision**: la URL de autorización
(`https://accounts.google.com/o/oauth2/v2/auth`) lleva:

- `response_type=code`;
- `client_id`;
- `redirect_uri`;
- `scope` (los dos de la decisión 3);
- `state`;
- `code_challenge`;
- `code_challenge_method=S256`;
- `access_type=offline`;
- `prompt=select_account consent`.

**Regla**: **todo** flujo de **Connect** o **Reconnect** que busque obtener un nuevo conjunto
persistente de credenciales solicita **siempre** `access_type=offline` y `prompt=consent`
(junto con `select_account`). No hay ninguna variante del flujo sin ellos. Esto incluye la
primera conexión, la reconexión tras `Reconnect required`, la reconexión de una cuenta
conectada y la conexión tras un `Disconnect`.

**Rationale**:

- `Disconnect` borra el refresh token local pero **no** revoca el grant en Google
  (decisión 13). Si el usuario ya concedió esos scopes al mismo cliente OAuth, Google puede
  completar una autorización posterior **sin** emitir un refresh token nuevo. AutoPublisher
  se quedaría sin credencial renovable, porque la anterior ya no existe localmente.
- `access_type=offline` pide explícitamente acceso renovable.
- `prompt=consent` obliga a Google a mostrar de nuevo el consentimiento y, con ello, a emitir
  un refresh token nuevo aunque los scopes ya estuvieran concedidos. Cubre todos los casos
  en que el refresh token local se eliminó o se perdió: desconexión, secreto borrado fuera
  de AutoPublisher o `invalid_grant`.
- **Efecto visible e intencionado**: el usuario verá **siempre** la pantalla de
  consentimiento de Google en Connect y Reconnect, aunque ya hubiera autorizado antes la
  aplicación. Es el precio de garantizar credenciales renovables; se menciona en el README y
  en `quickstart.md`.
- `prompt=select_account` fuerza el selector de cuenta, que con scopes de YouTube permite
  elegir también **cuentas de marca/canales** (decisión 7).
- **Se mantiene la regla existente**: si, aun así, la respuesta de token no trae
  `refresh_token`, la conexión no se completa (`oauth_offline_access_missing`).

**Alternatives considered**:

- *Pedir `prompt=consent` solo cuando no haya credenciales locales*: AutoPublisher no puede
  saber si Google conserva un grant previo (p. ej. tras un `Disconnect` en otro proyecto o
  una reinstalación), así que fallaría de forma intermitente.
- *Revocar al desconectar para forzar un refresh token nuevo*: descartado en la
  decisión 13.

## 5. `state`, PKCE y autorizaciones pendientes

**Decision**:

- `state = secrets.token_urlsafe(32)`.
- `code_verifier = secrets.token_urlsafe(64)`: 86 caracteres del alfabeto permitido, dentro
  del rango 43–128.
- `code_challenge = base64url(sha256(code_verifier))` sin relleno.
- Las autorizaciones pendientes viven **solo en memoria**, en un registro
  (`OAuthAttemptRegistry`) en `app.state` protegido por un `threading.Lock`. Cada una
  guarda:
  - `attempt_id` (aleatorio, distinto del `state`, usado por el frontend para consultar);
  - `state`;
  - `code_verifier`;
  - `account_id`;
  - `expires_at` (creación + **10 min**);
  - su resultado.
- **Un solo uso**: el `state` se consume (se elimina del índice) al recibir el callback,
  tanto si el resultado es éxito como error.
- **La más reciente gana**: al iniciar una autorización para una cuenta, las pendientes
  anteriores de esa cuenta pasan a `expired`.
- El `code_verifier` y cualquier credencial nueva a la espera de confirmación se borran del
  registro al llegar a un estado terminal.
- **Caducidad y retención**: al superar `expires_at`, un intento no terminal pasa a
  `expired`. Todo intento terminal se conserva **sin secretos** 10 minutos adicionales
  desde que terminó, para que la interfaz pueda consultar su resultado (incluido
  `expired`). Después se purga y su consulta devuelve `404`. En cada operación, el registro
  evalúa primero las caducidades y después purga lo que ha superado la retención. Regla
  completa en [data-model.md](data-model.md).

**Rationale**: cumple FR-008, FR-009a y la spec ("no sobreviven a un reinicio"). El
`code_verifier` nunca toca SQLite, logs ni respuestas. La memoria es suficiente para una app
local de un único proceso.

**Alternatives considered**:

- *Persistir los intentos en SQLite*: lo prohíbe la spec para el `code_verifier` y las
  credenciales pendientes.
- *Firmar el `state` (JWT/HMAC) sin registro*: necesitaría otro secreto y seguiría
  necesitando guardar el verifier.

## 6. Experiencia del callback y comunicación con el frontend

**Decision**:

1. El panel de cada cuenta YouTube obtiene su estado con
   `GET /api/accounts/{id}/youtube-connection`, que incluye `oauth_configured`. Si es
   `false`, **no** ofrece iniciar la autorización ni abre ninguna pestaña: muestra cómo
   configurar YouTube OAuth (FR-014).
2. Con `oauth_configured = true`, el frontend llama a
   `POST /api/accounts/{id}/youtube-connection/authorize`, que devuelve `attempt_id`,
   `authorization_url` y `expires_at`.
3. Para evitar bloqueadores de pop-ups, el frontend abre una pestaña en blanco **de forma
   síncrona** en el clic y le asigna la URL al recibir la respuesta. Si el navegador la
   bloquea, muestra un enlace "Open Google authorization".
   - **Defensa secundaria**: si `authorize` falla antes de poder navegar la pestaña (por
     ejemplo, la configuración desapareció entre la carga del estado y el clic), el
     frontend la cierra (`tab.close()`) y muestra el error.
4. Google redirige al callback del backend. Este procesa la respuesta y devuelve una
   **página HTML mínima**, sin secretos y con texto escapado, con el resultado ("YouTube
   channel connected. You can close this tab and return to AutoPublisher." o el error).
5. La pestaña original de AutoPublisher **consulta** `GET /api/youtube/oauth/attempts/{id}`
   cada 2 s hasta un estado terminal o `awaiting_confirmation`, y entonces actualiza la
   cuenta o muestra la advertencia de cambio de canal.

**Rationale**:

- No requiere conocer la URL del frontend en el backend.
- Funciona con el proxy de Vite actual (el callback va directo al backend en `:8000`).
- El estado autoritativo queda en la pestaña de AutoPublisher.
- El sondeo es trivial y limitado: como máximo 10 min, y se detiene al cerrar el panel.

**Alternatives considered**:

- *Redirigir del callback al frontend*: obliga a configurar la URL del frontend (que cambia
  entre `vite dev` y `preview`) y abre una segunda instancia de la SPA.
- *`webbrowser.open` desde el backend*: el backend puede ejecutarse sin entorno gráfico, y
  quien interactúa es el frontend.
- *WebSocket/SSE*: infraestructura innecesaria para un evento puntual.

## 7. Identificación inequívoca del canal efectivo

**Decision**: tras el intercambio, una única llamada:

```
GET https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=50
```

con el access token recién obtenido:

- **exactamente 1** elemento: es el canal efectivo. Se guardan `id`, `snippet.title`,
  `snippet.customUrl` (si existe) y `snippet.thumbnails.default.url` (si existe);
- **0** elementos: `youtube_no_channel`;
- **más de 1** elemento, o un elemento sin `id`: `youtube_channel_ambiguous`. Nunca se elige
  uno.

En ambos errores se descartan las credenciales recién obtenidas: solo se olvidan en
memoria, nunca se escriben en el almacén y no se revocan en Google (decisión 13). El mensaje
pide seleccionar el canal correcto en el selector de
Google (incluidas las cuentas de marca) y reintentar.

**Rationale**:

- Con YouTube, cada canal de marca es una identidad propia que el usuario elige en el
  selector de cuentas (`prompt=select_account`). El token queda ligado a esa identidad, y
  `mine=true` devuelve los canales **propiedad del usuario autenticado**: el canal sobre el
  que actuarán las credenciales.
- El caso normal es un elemento. Si Google devolviera varios, AutoPublisher no puede saber
  sobre cuál actuaría `videos.insert`, así que rechaza (FR-016a).
- Coste: 1 unidad de cuota.

**Verificación manual**: [quickstart.md](quickstart.md) incluye un escenario con una cuenta
de Google que administra varios canales (principal y de marca), cuando exista una
disponible.

## 8. Almacén seguro de credenciales

**Decision**: **`keyring`** (≥ 25), **nueva dependencia de ejecución del backend**, con el
backend nativo del sistema:

- Linux: Secret Service (GNOME Keyring / KWallet) vía `SecretStorage`;
- macOS: Keychain;
- Windows: Credential Locker.

Formato de cada entrada:

- servicio: `autopublisher.youtube`;
- usuario: `credential_ref`, un `uuid4().hex` nuevo **en cada conexión**;
- secreto: JSON `{"access_token", "refresh_token", "expires_at", "scopes"}`.

El client ID y el client secret **no** se guardan ahí (decisión 12).

**Comprobación del backend antes de usarlo**: `KeyringCredentialStore` comprueba el backend
efectivo (`keyring.get_keyring()`) **antes de cada `set`, `get` y `delete`**, y en particular
antes de guardar credenciales. Usa una **lista blanca** de backends seguros del sistema:

| Backend aceptado | Sistema |
|------------------|---------|
| `keyring.backends.SecretService.Keyring` | Linux (Secret Service vía `SecretStorage`/`jeepney`) |
| `keyring.backends.libsecret.Keyring` | Linux (libsecret vía PyGObject, si está instalado) |
| `keyring.backends.kwallet.DBusKeyring` | Linux (KWallet vía D-Bus, si está instalado) |
| `keyring.backends.macOS.Keyring` | macOS (Keychain) |
| `keyring.backends.Windows.WinVaultKeyring` | Windows (Credential Locker) |

- Si el backend efectivo es un `ChainerBackend`, **todos** sus backends encadenados deben
  estar en la lista blanca.
- Cualquier otro backend se rechaza, incluidos:
  - `keyring.backends.fail.Keyring` (no hay ninguno disponible);
  - `keyring.backends.null.Keyring`;
  - cualquier backend de `keyrings.alt` (`PlaintextKeyring`, `EncryptedKeyring`…, en claro o
    cifrados con clave en disco);
  - un backend forzado con `PYTHON_KEYRING_BACKEND` o con el archivo de configuración de
    `keyring` que no esté en la lista.
- Se usa una lista blanca y no una lista negra porque ningún backend desconocido debe
  aceptarse por omisión.

**Fallo claro, sin plan B**: si no hay un backend seguro, o si el backend falla
(`KeyringError`, `KeyringLocked`, `InitError`: llavero bloqueado y desbloqueo cancelado,
D-Bus de sesión ausente, daemon no arrancado…), la operación se aborta con
`credential_store_unavailable` (`503`) y un mensaje que remite a la sección de requisitos del
README. **Nunca** se recurre a un archivo plano, a SQLite ni a ningún otro almacenamiento
alternativo.

**Requisitos en Linux / Ubuntu** (documentados en el README y en `quickstart.md`):

- **Dependencias Python**: `keyring` instala automáticamente en Linux `SecretStorage` y
  `jeepney`, ambos en Python puro. No se necesita ninguna librería de sistema para el
  backend Secret Service.
- **Servicio del sistema**: un proveedor de **Secret Service** en la sesión del usuario:
  - **GNOME Keyring** (`gnome-keyring`), incluido por defecto en Ubuntu Desktop;
  - o **KWallet** con su puente Secret Service (Kubuntu / KDE Plasma).

  En otros sabores o instalaciones mínimas: `sudo apt install gnome-keyring`.
- **Bus de sesión D-Bus** activo (`DBUS_SESSION_BUS_ADDRESS` definido), lo normal en una
  sesión gráfica.
- **Llavero desbloqueado**: el llavero "Login" se desbloquea al iniciar sesión. Si está
  bloqueado, el sistema puede pedir la contraseña; si se cancela, la operación falla con
  `credential_store_unavailable`.
- **Opcional, solo para inspección manual**: `libsecret-tools` (comando `secret-tool`) o
  `seahorse` ("Passwords and Keys").
- **No soportado**: sesiones sin entorno gráfico ni D-Bus (SSH sin sesión, servidores,
  contenedores, WSL sin Secret Service). Allí la conexión falla de forma explícita.

Comprobación rápida para el usuario:

```bash
uv run python -c "import keyring; print(keyring.get_keyring())"
```

Debe mostrar un backend de la lista blanca, por ejemplo `SecretService Keyring`.

Abstracción `CredentialStore` (Protocol): `get(ref)`, `set(ref, value)` y `delete(ref)`.

- `KeyringCredentialStore` en producción.
- `InMemoryCredentialStore` en los tests, inyectado mediante `create_app`.

**Rationale**:

- La Constitution exige "almacenamiento seguro del sistema operativo para tokens"; `keyring`
  es la abstracción estándar y multiplataforma de Python para ello.
- Una referencia nueva por conexión permite sustituir credenciales de forma ordenada:
  escribir la nueva, confirmar en base de datos y borrar la vieja (decisión 10).

**Alternatives considered**:

- *Archivo cifrado propio*: la clave tendría que guardarse en algún sitio, lo que es
  circular.
- *Columnas cifradas en SQLite*: prohibido por la spec.
- *`keyrings.alt` como respaldo*: guarda en claro u ofusca; prohibido por FR-024.
- *Lista negra de backends inseguros*: un backend de terceros desconocido se aceptaría por
  omisión.

**Limitación documentada**: en Linux sin sesión gráfica ni Secret Service (servidores,
contenedores, CI) la conexión no está disponible. Los tests no dependen de ello.

## 9. Persistencia de la conexión y unicidad

**Decision**: nueva tabla `youtube_connections` (migración `0004`), detallada en
[data-model.md](data-model.md):

- `UNIQUE(account_id)`: como máximo una conexión por cuenta.
- `UNIQUE(project_id, channel_id)`: un canal por proyecto, garantizado en base de datos e
  inmune a carreras (FR-020).
  - `project_id` se desnormaliza desde la cuenta, que nunca cambia de proyecto (no existe
    API para ello).
  - La fila existe mientras la cuenta está conectada **o** requiere reconexión, sea la
    cuenta activa o inactiva, de modo que las cuentas inactivas también bloquean.
- `Not connected` = ausencia de fila.
- La desconexión **borra la fila**: es la referencia a las credenciales, no la `Account`.

La comprobación se hace primero en código, para dar un mensaje con la cuenta que ya tiene el
canal. Un `IntegrityError` posterior (carrera) se traduce también a
`channel_already_connected`.

**Alternatives considered**:

- *Columnas nuevas en `accounts`*: mezclaría datos de una sola plataforma en la entidad
  común (Constitution III) y no permitiría la unicidad parcial sin un índice condicional
  más frágil.
- *Relación inversa `Account.youtube_connection` y campo en `AccountRead`*: el núcleo común
  de cuentas conocería YouTube (Constitution III). La tabla solo tiene la FK hacia
  `accounts`. El estado se consulta con el endpoint específico, que el frontend llama solo
  para cuentas YouTube.
- *Mantener filas "desconectadas" como historial*: nadie lo pide (Constitution I).

## 10. Orden de operaciones y consistencia almacén ↔ base de datos

**Decision**:

- **Conectar / sustituir**:
  1. `store.set(new_ref)`;
  2. insertar o actualizar la fila y hacer `commit`;
  3. si el `commit` falla, `store.delete(new_ref)` como compensación;
  4. tras el éxito, `store.delete(old_ref)` sin bloquear (si falla se registra en el log,
     sin datos sensibles).
- **Desconectar** (sin contactar con Google, decisión 13):
  1. `store.delete(ref)` (si el secreto ya no existe, no es error);
  2. borrar la fila y hacer `commit`.

  La fila solo se borra **después** de que el secreto se haya borrado correctamente. Si el
  almacén no está disponible, se responde `credential_store_unavailable` y **no** se borra
  la fila: la conexión sigue visible con su estado y el usuario puede reintentar sin que
  quede un secreto sin referencia.

**Rationale** (FR-025):

- Nunca queda una fila sin secreto utilizable.
- Si una operación falla después de guardar un secreto, AutoPublisher intenta borrarlo en
  el momento (compensación). Si ese borrado también falla porque el almacén no está
  disponible, puede quedar una entrada huérfana en el llavero, sin referencia en SQLite y
  sin uso posible.
- Con referencias aleatorias **no** es posible detectar ni limpiar esas entradas después,
  y AutoPublisher no lo promete. El usuario puede borrarlas con las herramientas del sistema
  (servicio `autopublisher.youtube`; en Linux, `seahorse` o `secret-tool clear service
  autopublisher.youtube username <ref>`).
- Se acepta porque requiere un doble fallo del almacén y no expone nada nuevo: el secreto
  sigue en el almacén seguro.

## 11. Estados y transiciones

**Decision**: columna `status` con valores `connected` y `reconnect_required`;
`not_connected` es la ausencia de fila. La API expone los tres valores.

Se pasa a `reconnect_required` cuando:

- el refresh responde `invalid_grant` (revocado, caducado, 7 días en modo Testing…);
- el secreto falta en el almacén;
- la verificación devuelve un channel ID distinto del vinculado;
- YouTube responde `401` con un token recién refrescado;
- el token concedido no tiene los scopes necesarios (`403 insufficientPermissions`).

**No** cambian el estado: los timeouts, errores de red, respuestas `5xx` y `429` de Google o
YouTube. Se responden como `youtube_unavailable` (`503`).

Ver el diagrama en [data-model.md](data-model.md).

## 12. Configuración OAuth de AutoPublisher

**Decision**: el usuario descarga el JSON del cliente **Desktop app** desde Google Cloud
Console y lo guarda en `backend/data/google-oauth-client.json`. `data/` ya está ignorado por
Git. La ruta es configurable con `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`.

- El archivo se lee **en cada operación que lo necesita**, de modo que configurarlo no
  requiere reiniciar el backend.
- Debe contener la clave `installed` con `client_id` y `client_secret`. Si falta, es
  ilegible o es de otro tipo (`web`), la respuesta es `oauth_not_configured` (`503`) con un
  mensaje que remite a la documentación.
- `.gitignore` añade `client_secret*.json` y `google-oauth-client*.json` como defensa
  adicional (el JSON que descarga Google se llama `client_secret_<id>.json`).
- El repositorio **no** incluye un archivo de ejemplo con valores ficticios. La
  documentación describe la estructura sin valores que parezcan reales.

**Rationale**:

- Es el formato que Google entrega, y evita que el usuario copie secretos a variables de
  entorno o a un `.env` (el proyecto no carga `.env`).
- Google indica que el secreto de un cliente Desktop no se considera confidencial, pero
  AutoPublisher lo trata igualmente como secreto: no se versiona, no se registra en logs y
  no se expone.

**Alternatives considered**:

- *Variables de entorno `CLIENT_ID` / `CLIENT_SECRET`*: obligan a exportar secretos en el
  shell o a introducir carga de `.env`.
- *Guardar el client secret en el llavero*: complica el primer arranque sin beneficio real
  para una app local.

## 13. Sin revocación automática al desconectar

**Decision**: `Disconnect` **no** revoca el permiso OAuth en Google. Siempre hace lo
siguiente, de forma local y sin contactar con Google:

1. eliminar las credenciales de la cuenta del almacén seguro;
2. eliminar la referencia local (la fila de `youtube_connections`);
3. dejar la cuenta en `Not connected`.

La interfaz muestra, tras desconectar y en el diálogo de confirmación, cómo retirar
manualmente el permiso si el usuario lo desea:

1. abrir <https://myaccount.google.com/connections> (*Cuenta de Google → Seguridad →
   Tus conexiones con apps y servicios de terceros*);
2. elegir la app (el nombre configurado en la pantalla de consentimiento del proyecto de
   Google Cloud);
3. pulsar *Eliminar todas las conexiones* / *Delete all connections*.

El mismo criterio se aplica a las credenciales **descartadas** durante una autorización
(canal ausente o ambiguo, scopes incompletos, canal ya vinculado, sustitución cancelada o
caducada): se olvidan en memoria y nunca se escriben en el almacén, pero no se revocan.

**Rationale**:

- La revocación de Google (`https://oauth2.googleapis.com/revoke`) no afecta solo a un
  token: "Revocation removes all OAuth 2.0 scopes previously granted to a project". Invalida
  el **grant completo** de esa identidad de Google para el cliente OAuth de AutoPublisher.
  Revocar al desconectar una cuenta podría invalidar otras conexiones que compartan esa
  identidad y ese cliente:
  - el mismo canal en otro proyecto (FR-021);
  - la conexión existente de otra cuenta cuando se descarta un intento que devolvió un canal
    ya vinculado;
  - la conexión actual cuando se cancela una reconexión.
- Esas cuentas pasarían a `Reconnect required` sin que el usuario lo entienda.
- No contactar con Google hace la desconexión determinista: siempre se completa localmente,
  aunque no haya red ni configuración OAuth.
- El usuario conserva el control total: puede retirar el permiso cuando quiera desde su
  cuenta de Google, y AutoPublisher se lo indica.

**Consecuencias asumidas**:

- Tras desconectar, el refresh token sigue siendo válido en Google hasta que el usuario lo
  revoque manualmente o caduque, pero AutoPublisher ya no lo conserva en ningún sitio.
- Google limita a 100 los refresh tokens vivos por cuenta de Google y client ID. Al
  superarse, invalida los más antiguos sin aviso. En un uso local normal (pocas
  reconexiones) no es relevante; si ocurriera, una conexión antigua pasaría a
  `Reconnect required`.

**Alternatives considered**:

- *Revocar siempre*: rompe silenciosamente otras conexiones que comparten el grant.
- *Revocar salvo si el mismo canal está conectado en otro proyecto*: no cubre todos los
  casos de grant compartido (intentos descartados, reconexiones canceladas), y hace que
  `Disconnect` dependa de la red y tenga resultados variables.
- *Ofrecer un botón "Revoke in Google" en AutoPublisher*: amplía el alcance y reintroduce el
  efecto sobre otras conexiones. Se descarta en esta feature.

## 14. Renovación de credenciales

**Decision**: función `get_valid_credentials(session, account_id)` en
`app/youtube_connections.py`. Bajo un lock por cuenta:

1. carga el secreto (si falta → `reconnect_required`);
2. si `expires_at` está a más de 60 s, devuelve el access token;
3. si no, hace `POST https://oauth2.googleapis.com/token` con `grant_type=refresh_token`:
   - **éxito**: guarda el nuevo access token y la caducidad (y el nuevo refresh token si
     Google lo rota) con `store.set(ref)`;
   - **`400 invalid_grant`**: marca `reconnect_required` y devuelve `reconnect_required`
     (`409`);
   - **fallo de red, `5xx` o `429`**: `youtube_unavailable` (`503`), sin cambiar el estado.

La usan la verificación bajo demanda (`POST .../verify`) y la usará la futura subida.

**Rationale**: FR-028–FR-030. El lock evita dos refresh simultáneos de la misma cuenta.

## 15. Errores

**Decision**: se añade en `errors.py` una excepción genérica `AppError(status_code, code,
message)` con su manejador, que usa el mismo `error_response`. Las existentes no cambian. Se
reutiliza `ConflictError` para los `409` de dominio (`project_inactive`,
`account_inactive`…). Códigos completos en [contracts/api.md](contracts/api.md).

- Los errores producidos dentro del callback no se devuelven como JSON al navegador de
  Google: se guardan en el intento con el mismo formato `{code, message}` y se muestran en
  la página HTML.
- **Logs**: solo `code`, `account_id`, `attempt_id` y el estado HTTP de Google. Nunca:
  tokens, códigos de autorización, `code_verifier`, client secret, cuerpos de respuesta de
  Google ni URLs con query.

Un test con `caplog` comprueba que ningún valor sensible del fake aparece en los logs, la
base de datos ni las respuestas.

## 16. Estrategia de tests

**Decision**:

- **Backend**:
  - Fixture `fake_google`: un `httpx2.MockTransport` que simula los endpoints de token,
    refresh y `channels.list`, con respuestas programables (éxito,
    `access_denied`, `invalid_grant`, `5xx`, timeout, 0/1/2 canales, scopes parciales, sin
    refresh token).
  - `InMemoryCredentialStore`, que puede simular "no disponible".
  - Archivo de cliente OAuth ficticio en `tmp_path`.
  - Todo se inyecta mediante `create_app(...)`; el gateway real se ejecuta contra el
    transporte falso, sin Internet.
- **Tests puros**: PKCE (longitud y alfabeto del verifier; `challenge == S256(verifier)`) y
  la URL de autorización (parámetros exactos).
- **Aislamiento del llavero real**: un fixture `autouse` hace
  `keyring.set_keyring(keyring.backends.fail.Keyring())` antes de cada test y restaura el
  backend original al terminar. Así ningún test toca el llavero del sistema por accidente.
  Los tests del almacén seguro sustituyen ese backend dentro del propio test con otra
  llamada a `keyring.set_keyring(...)`, y la restauración del fixture lo deshace todo al
  final.
- **Selección del backend de `keyring`**: tests con backends falsos para verificar:
  - que se aceptan los de la lista blanca;
  - que se rechazan `fail`, `null`, los de `keyrings.alt`, los desconocidos y un chainer con
    alguno inseguro;
  - que un `KeyringLocked` o `KeyringError` produce `credential_store_unavailable` sin
    escribir nada en otro sitio.
- **Desconexión**: el fake de Google comprueba que `Disconnect` no realiza **ninguna**
  petición a Google.
- **Frontend**: `FakeApi` ampliado con conexión, intentos y sondeo controlado. Tests de
  `Not connected` / `Connected` / `Reconnect required`, advertencia de cambio de canal,
  errores, `oauth_configured = false` (sin abrir pestaña), cierre de la pestaña si
  `authorize` falla, y que solo se consulta el estado de las cuentas YouTube.

**Rationale**: FR-041 y SC-009. Cubre todos los casos de la sección de tests de la petición
original.

## 17. Limitaciones de Google a documentar

- **Modo Testing**: con la pantalla de consentimiento en "Testing" y usuarios externos, el
  refresh token **caduca a los 7 días**, y la cuenta pasará a `Reconnect required`. Para uso
  continuado, publicar la app ("In production"); una app personal no verificada muestra una
  advertencia en el consentimiento, pero funciona.
- **Límite de 100 refresh tokens** por cuenta de Google y client ID: los más antiguos se
  invalidan sin aviso (ver decisión 13).
- **Revocación manual**: el permiso concedido a AutoPublisher se retira desde
  <https://myaccount.google.com/connections>. Hacerlo afecta a todas las conexiones de
  AutoPublisher que usen esa identidad de Google.
- Los refresh tokens caducan si no se usan durante 6 meses.
- Los vídeos subidos desde proyectos no verificados serán privados (relevante para la
  siguiente feature).
