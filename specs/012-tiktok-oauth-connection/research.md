# Research: Conexión de cuentas TikTok (Login Kit for Desktop)

**Feature**: `012-tiktok-oauth-connection` | **Fecha**: 2026-10-14

Fuentes oficiales consultadas el 2026-10-14 (TikTok for Developers): *Login Kit for Desktop*,
*Login Kit overview*, *Manage User Access Tokens*, *OAuth Error Handling*, *Get User Info*,
*API v2 Error Handling*, *Add a Sandbox*, *Content Posting API — Get Started*. Confirmación
externa de la codificación PKCE: PR de n8n que añade una credencial OAuth2 específica de TikTok
porque el challenge debe ir en hex.

Lo que la documentación no garantiza se valida en el **gate temprano G** del quickstart (antes de
implementar en profundidad) o en las validaciones posteriores, con condiciones de STOP.

---

## 1. Tipo de integración: Login Kit for Desktop + callback de loopback del backend

**Decisión**: Login Kit for **Desktop** (OAuth v2) con un callback HTTP servido por el propio
backend FastAPI, siguiendo el patrón de YouTube (Feature 005): página HTML mínima en la pestaña
de TikTok y consulta periódica del intento desde el frontend.

**Rationale**: Desktop admite redirect URIs `http` de loopback con puerto y exige PKCE; el flujo
Web exige HTTPS y dominio público. AutoPublisher ya resuelve un callback de loopback idéntico
para Google (`/api/youtube/oauth/callback`), con filtro de access log y página limpia.

**Alternativas**: Login Kit for Web (requiere dominio HTTPS público: descartado); patrón "pegar la
redirect URL" de Threads (innecesario: Desktop acepta loopback; peor UX y la spec lo descarta).

## 2. Endpoints y versión

| Uso | Método | URL |
|---|---|---|
| Autorización | GET (navegador) | `https://www.tiktok.com/v2/auth/authorize/` |
| Intercambio y renovación | POST form | `https://open.tiktokapis.com/v2/oauth/token/` |
| Revocación | POST form | `https://open.tiktokapis.com/v2/oauth/revoke/` |
| Identidad | GET + Bearer | `https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url` |

Constantes únicas en `tiktok_gateway.py` / `tiktok_oauth.py`. Sin endpoints legacy
(`open-api.tiktok.com`, `/oauth/access_token/`). Timeout por petición: 10 s (constante
`TIKTOK_TIMEOUT_SECONDS`, mismo valor que Meta).

## 3. Redirect URI y estrategia de puerto

**Decisión**:

- Valor por defecto: `http://127.0.0.1:8000/api/tiktok/oauth/callback` (sin barra final),
  configurable en el archivo local de TikTok (`redirect_uri`).
- Validación al cargar la configuración: scheme `http`; host **exactamente** `127.0.0.1` o
  `localhost` (reglas Desktop); **puerto explícito** (no comodín en el valor configurado); path
  **exactamente** `/api/tiktok/oauth/callback` (la ruta que atiende el backend); sin userinfo,
  query ni fragment; < 512 caracteres. Si no cumple → `tiktok_oauth_not_configured`.
- Se registra en el dashboard **exactamente ese URI con puerto fijo**. El puerto comodín
  (`http://127.0.0.1:*/api/tiktok/oauth/callback`) se documenta como alternativa admitida por
  TikTok, pero no se recomienda: el backend usa un puerto estable (8000, el que espera el proxy
  de Vite y el callback de YouTube) y un registro exacto es más estricto. En ambos casos el
  `redirect_uri` enviado (autorización e intercambio) es el valor concreto configurado.
- Antes de crear un intento, `authorize` compara el puerto real del socket del backend
  (`request.scope["server"]`) con el puerto del `redirect_uri`; si difieren →
  `tiktok_oauth_not_configured` con un mensaje que lo explica (edge case "backend en otro
  puerto"). No se usa la cabecera `Host` (llega desde el proxy de Vite).
- `127.0.0.1` y no `localhost` por defecto: el backend escucha en `127.0.0.1` y se evita la
  resolución a `::1`.

**Barra final**: los ejemplos de TikTok terminan en `/`, pero no es obligatorio. Se usa sin barra
para no depender de la redirección automática de FastAPI (que repetiría `code` y `state` en otra
URL). Si el dashboard la exige o la altera, el gate G-6 lo detecta y se ajusta la constante de
ruta y el filtro de logs antes de implementar (cambio de una constante).

**Alternativas**: puerto aleatorio por intento con comodín (exigiría un servidor temporal propio:
complejidad innecesaria); `localhost` por defecto (ambigüedad IPv4/IPv6).

## 4. PKCE

**Decisión**:

- `code_verifier = secrets.token_urlsafe(48)` → 64 caracteres del conjunto `[A-Za-z0-9-_]`,
  subconjunto del permitido (`[A-Z] [a-z] [0-9] - . _ ~`), dentro de 43–128. Nuevo por intento.
- `code_challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()` → **hex en
  minúsculas, 64 caracteres**. `code_challenge_method=S256`.
- **No** se reutiliza `generate_pkce_pair` de YouTube (base64url, RFC 7636): TikTok Desktop
  documenta explícitamente hex ("You must use hex encoding of SHA256…"), confirmado por la
  integración de n8n. Función propia `generate_tiktok_pkce_pair` con test de vector conocido.
- El verifier vive solo en el intento en memoria; se borra al consumirse el `state`
  (antes del intercambio) y en cualquier fin del intento.

**Riesgo**: si TikTok rechazara el challenge hex (`invalid_grant`/error en la autorización), el
gate G-8 lo detecta → STOP (spec FR-059).

## 5. Autorización: parámetros

`client_key`, `scope=user.info.basic,video.publish` (coma, sin espacios, en ese orden),
`response_type=code`, `redirect_uri`, `state`, `code_challenge`, `code_challenge_method=S256`.
Ningún parámetro no documentado. `state = secrets.token_urlsafe(32)`.

## 6. Callback: validación estricta

Algoritmo de `parse_callback(scope_server, client_host, path, query_items)`:

1. Solo se atiende la ruta exacta del `redirect_uri` (enrutado de FastAPI) y solo si el socket
   local es loopback y el cliente (`request.client.host`) es `127.0.0.1` o `::1`; si no →
   página "no válida" sin efectos.
2. Se leen los parámetros con `request.query_params.multi_items()` (no con parámetros de
   FastAPI, que se quedan con un valor silenciosamente). Parámetros documentados: `code`,
   `scopes`, `state`, `error`, `error_description`. Cualquiera de ellos **duplicado** → inválido.
   Parámetros no documentados se ignoran y nunca se registran.
3. Sin `state` o `state` que no corresponde a un intento `pending` → `tiktok_oauth_state_invalid`
   (página segura; nada cambia). El `state` se busca por igualdad exacta en un diccionario.
4. Con `state` válido, el intento se **consume** (pasa a "en proceso", verifier extraído) antes de
   cualquier otra cosa: un segundo callback con el mismo `state` no encuentra intento.
5. `code` y `error` a la vez, o ninguno, o `code` vacío / > 1024 caracteres →
   `tiktok_oauth_callback_invalid` y el intento termina en `failed`.
6. `error=access_denied` → `tiktok_oauth_denied`; cualquier otro `error` →
   `tiktok_oauth_provider_error`. `error_description` **nunca** se muestra ni se registra.
7. Con `code`: comprobaciones de entidades activas, después intercambio (§7).
8. **Respuesta**: el callback **nunca** sirve contenido en su propia URL. Siempre responde
   `303 See Other` con `Location: /api/tiktok/oauth/result?outcome=<valor>` (ruta relativa,
   mismo origen), cabeceras `Cache-Control: no-store` y `Referrer-Policy: no-referrer`. Así la
   URL con `code`/`state` no queda en la barra de direcciones y el redirect sustituye la
   entrada en el historial del navegador.

### 6.1 Ruta limpia de resultado

`GET /api/tiktok/oauth/result?outcome=<valor>` sirve la página HTML mínima. `outcome` es un
**enumerado cerrado** (`TikTokCallbackOutcome`):

| `outcome` | Cuándo | Título de la página |
|---|---|---|
| `connected` | conexión completada | "TikTok account connected" |
| `confirm_required` | `open_id` distinto del vinculado (`awaiting_confirmation`) | "Confirm the TikTok account" |
| `cancelled` | `error=access_denied` | "Connection cancelled" |
| `failed` | cualquier fallo con intento válido (el detalle seguro está en el intento) | "Connection failed" |
| `invalid` | `state` ausente/desconocido/usado/caducado, cliente no loopback | "Authorization not valid" |

- El título y el mensaje salen de un diccionario fijo en código; el texto de la página nunca
  se construye a partir de la query. Un `outcome` ausente, desconocido o repetido se trata como
  `invalid`. Cualquier otro parámetro se ignora.
- La ruta no recibe nunca `code`, `state`, tokens, verifier, `attempt_id` ni errores crudos;
  el detalle del fallo lo muestra el panel de AutoPublisher a partir del intento.
- Responde siempre 200 con `Cache-Control: no-store`, `Referrer-Policy: no-referrer` y sin
  scripts.
- La URL entrante del callback no se registra (filtro de access log, §15); la de la ruta de
  resultado solo contiene el enumerado y puede registrarse.

El `code` se pasa al gateway tal como lo entrega Starlette (ya decodificado de URL), que es lo
que la documentación exige ("should be URL decoded").

## 7. Intercambio de código

`POST /v2/oauth/token/`, `Content-Type: application/x-www-form-urlencoded`, cuerpo:
`client_key`, `client_secret`, `code`, `grant_type=authorization_code`, `redirect_uri`,
`code_verifier`. Cabecera `Cache-Control: no-cache` (como el ejemplo oficial). Sin reintentos.

Respuesta válida (todas obligatorias): `access_token` (str no vacío), `expires_in` (int > 0),
`refresh_token` (str no vacío), `refresh_expires_in` (int > 0), `open_id` (str no vacío),
`scope` (str), `token_type` (`Bearer`, sin distinguir mayúsculas). Si falta algo o el tipo no
encaja → `tiktok_unexpected_response`. Una respuesta HTTP 200 con cuerpo `{"error": …}` se trata
como error (TikTok puede devolver errores con 200).

Scopes: `scope` se separa por comas y se recortan espacios. Conexión solo si
`{"user.info.basic", "video.publish"} ⊆ scopes` (FR-008). El `scopes` del callback se ignora
para decidir (solo se comprueba que no esté duplicado).

`obtained_at = clock()` al recibir la respuesta; `access_expires_at = obtained_at + expires_in`;
`refresh_expires_at = obtained_at + refresh_expires_in`. Nunca se usan 24 h / 365 días fijos.

## 8. Identidad y campos de `user.info.basic`

`GET /v2/user/info/?fields=open_id,display_name,avatar_url` con `Authorization: Bearer`.
Respuesta: `data.user.{open_id, display_name, avatar_url}` y `error.code == "ok"`.

- `open_id` obligatorio y **igual** al del intercambio (si no → `tiktok_unexpected_response` en
  Connect; `tiktok_identity_mismatch` en Verify/renovación).
- `display_name` y `avatar_url` opcionales (cadena vacía → `null`).
- No se piden `union_id` (identificador entre apps del mismo desarrollador: sin valor para el
  producto), `avatar_url_100` ni `avatar_large_url`. `username` no existe bajo
  `user.info.basic`: la UI muestra nombre visible + avatar + handle local.
- El `open_id` no se muestra en la UI (no aporta valor al usuario; queda en la API como dato no
  sensible para tests y Feature 013). En la advertencia de cambio de cuenta se muestran nombre
  y avatar de ambas cuentas más los 6 últimos caracteres del `open_id` para desambiguar.

## 9. Fuente de los scopes y semántica de Verify

TikTok no tiene inspección de token. **Fuente oficial** de los scopes concedidos: la lista
`scope` de la última respuesta correcta de intercambio o renovación, guardada en el secreto
(`scopes`). Verify:

- **Señales vivas**: access token utilizable (tras renovar si toca), `user/info` correcto,
  `open_id` coincidente → implica `user.info.basic` funcional.
- **Scopes conocidos**: si no hubo renovación, `video.publish` se informa "según la última
  autorización/renovación de TikTok" (`scopes_source`: `token_exchange` | `token_refresh` y
  `scopes_confirmed_at`), nunca como comprobación en vivo. Si hubo renovación, se evalúan sus
  scopes (sin `video.publish` → `reconnect_required`).
- `scope_not_authorized` en `user/info` → `reconnect_required` (falta `user.info.basic`).
- Sin llamadas a Content Posting / `creator_info` en esta feature. La Feature 013 aplicará la
  misma regla si recibe `scope_not_authorized` para `video.publish`.

## 10. Política de renovación (on-demand)

Constantes internas (`tiktok_connections.py`):

- `REFRESH_MARGIN = 1 h`: se renueva si al access token le queda ≤ 1 h. Con ~24 h de vida deja
  23 h de uso sin renovar y un margen holgado para que la Feature 013 complete una subida sin
  que el token caduque a mitad.
- `EXPIRY_MARGIN = 5 min`: por debajo, el access token ya no se considera utilizable (fallback
  ante fallo temporal de renovación).

Algoritmo `get_valid_credentials` (bajo candado por cuenta):

1. Leer secreto (almacén no disponible → `credential_store_unavailable`; ausente o ilegible →
   `reconnect_required`). Reparar el espejo SQLite si difiere (idempotente).
2. `refresh_expires_at <= now` → `reconnect_required` sin llamar a TikTok (valor oficial del
   secreto, autoritativo).
3. `access_expires_at - now > REFRESH_MARGIN` → devolver tal cual.
4. Si no, renovar (`grant_type=refresh_token`). Resultados:
   - Éxito → validar respuesta completa, `open_id` igual al vinculado (si no →
     `tiktok_identity_mismatch` + `reconnect_required`), scopes ⊇ requeridos (si no →
     `reconnect_required`, permiso que falta). Guardar y devolver.
   - `invalid_grant` (refresh token inválido, caducado o revocado) → `reconnect_required`.
   - `invalid_client`, `unauthorized_client`, `invalid_request` → error de configuración: no es
     evidencia sobre el usuario; se trata como **no temporal pero sin cambio de estado**
     (`tiktok_unexpected_response` / `tiktok_oauth_not_configured`).
   - Red, timeout, 5xx, 429, `server_error`, `temporarily_unavailable` → temporal: si
     `access_expires_at - now > EXPIRY_MARGIN` se devuelve el token actual; si no →
     `tiktok_unavailable`. Nunca `reconnect_required`.
5. Un `access_token_invalid` (401) en una llamada con token supuestamente vigente fuerza **una**
   renovación y un único reintento de esa llamada; si la renovación da `invalid_grant` →
   `reconnect_required`.

Sin scheduler ni renovación en segundo plano.

## 11. Rotación del refresh token y orden crash-safe

- Todos los valores sensibles de la credencial (access, refresh, ambas caducidades, scopes,
  fuente de scopes, `open_id`, `obtained_at`) forman **un único JSON** en una entrada del keyring:
  una escritura (`store.set`) los sustituye juntos y de forma consistente.
- Renovación: TikTok responde → `store.set(misma credential_ref, nuevo JSON)` → actualizar el
  espejo SQLite → commit. Si el commit falla: no se restaura el token anterior, se registra un
  aviso y se devuelve la credencial nueva; el espejo se repara en el siguiente acceso (garantía
  de la Feature 010). El refresh token anterior desaparece con la sobrescritura y no vuelve a
  usarse.
- Si `store.set` falla tras recibir una renovación: se reintenta **una vez**; si vuelve a fallar
  → `credential_store_unavailable`. El secreto anterior queda intacto, pero si TikTok rotó el
  refresh token, el anterior puede haber quedado invalidado: la siguiente renovación podría dar
  `invalid_grant` → `reconnect_required`. Riesgo aceptado y documentado (no existe forma de
  hacerlo atómico con TikTok); nunca se escribe el token en otro sitio.
- Lo mismo aplica si el proceso muere entre la respuesta de TikTok y `store.set`.
- Las renovaciones de una cuenta se serializan con un candado en memoria por cuenta, compartido
  con Verify y Disconnect, de modo que nunca se envía un refresh token ya rotado.
- **Supuesto explícito (único proceso)**: AutoPublisher local se ejecuta con **un único
  proceso/worker** de backend (`uv run uvicorn app.main:app`, sin `--workers`). El candado en
  memoria garantiza exclusión solo dentro de ese proceso; **no** hay garantía multi-worker ni
  se añade infraestructura distribuida. Ejecutar varios workers queda fuera de lo soportado y
  se documenta en `docs/tiktok-accounts.md`.

## 12. Reconnect y credenciales huérfanas

Orden (FR-034): `store.set(new_ref)` → en **una** transacción: actualizar la fila
(`credential_ref = new_ref`, identidad, fechas) **e insertar `old_ref` en
`tiktok_credential_orphans`** → commit → `store.delete(old_ref)` → si tiene éxito, borrar la fila
del huérfano (best-effort).

- Commit fallido → rollback, `store.delete(new_ref)` (si también falla, se registra en un commit
  aparte como huérfano best-effort), conexión anterior intacta.
- Borrado del secreto viejo fallido o caída del proceso tras el commit → el huérfano ya está
  registrado; la nueva conexión es válida.
- Limpieza de huérfanos: idempotente (`store.delete` de una entrada inexistente no es error),
  ejecutada de forma oportunista al inicio de cada operación de escritura de TikTok
  (completar conexión, Disconnect, Remove locally) y una vez en el arranque de la aplicación. Una
  `credential_ref` huérfana nunca puede ser la de una conexión (comprobado antes de borrar).
- La primera conexión no tiene `old_ref`.

**Alternativa descartada**: solo registrar en log como en 005/008/010 — la spec 012 exige
registro de limpieza pendiente (FR-034).

## 13. Revocación y semántica de Disconnect

`POST /v2/oauth/revoke/` (form): `client_key`, `client_secret`, `token=<access_token>`. Éxito
documentado: respuesta vacía (HTTP 200, cuerpo vacío o `{}` sin `error`).

Flujo (bajo el candado de la cuenta):

1. Almacén inaccesible → `credential_store_unavailable` (503), nada cambia.
2. Secreto ausente/ilegible → `tiktok_credential_missing` (409), sin llamar a TikTok, nada se
   borra; se ofrece `remove-local`.
3. Configuración ausente/ inválida → `tiktok_revoke_failed` (sin borrar).
4. Obtener access token utilizable: si `refresh_expires_at` pasó → **inválida según TikTok**. Si
   el access token está dentro de `EXPIRY_MARGIN`, renovar (permitido aunque la cuenta o el
   proyecto estén inactivos): `invalid_grant` → inválida según TikTok; temporal →
   `tiktok_revoke_failed`.
5. Revocar: éxito → `revoked`; `invalid_grant` o `access_token_invalid` → `already_invalid`;
   cualquier otra cosa (red, 5xx, 429, `invalid_request`, `invalid_client`, cuerpo inesperado) →
   `tiktok_revoke_failed` (ambiguo = no confirmado).
6. `revoked` / `already_invalid` → `store.delete(ref)` → borrar fila → commit. Si el borrado del
   secreto falla → `credential_store_unavailable` sin borrar la fila (en `revoked` la credencial
   ya no sirve; el siguiente uso pasará a `reconnect_required`).

El semántico exacto de error al revocar un token ya revocado no está documentado → validación
real (quickstart V-16) con STOP si contradice lo anterior.

`remove-local`: permitido solo si la conexión existe; borra secreto (si existe) y fila; si el
almacén está inaccesible → `credential_store_unavailable`. Respuesta con `revocation:
"not_revoked"`.

Credenciales descartadas: abstracción única `discard_credential(credential)` (en
`tiktok_connections.py`, inyectada también en el registro de intentos) que (1) carga la
configuración TikTok, (2) llama a `gateway.revoke(credential.access_token, config)`, (3) captura
**cualquier** excepción (incluida configuración ausente), (4) nunca cambia el resultado de la
operación principal, (5) registra solo `account_id`, el resultado (`revoked` / `failed`) y el
`log_id` de TikTok si existe, y (6) nunca persiste la credencial. Se usa en: scopes parciales,
`open_id` incoherente o distinto del vinculado sin confirmación posible, OAuth completado pero
conexión rechazada (duplicado en proyecto, entidades desactivadas, almacén no disponible, commit
fallido) y cambio de cuenta cancelado o caducado.

## 14. Clasificación de errores de TikTok

Gateway (`tiktok_gateway.py`), excepciones sin URL, cuerpo ni token, lanzadas `from None`:

| Señal | Excepción | Efecto típico |
|---|---|---|
| Red, timeout, 5xx, 429, `rate_limit_exceeded`, `internal_error`, `server_error`, `temporarily_unavailable` | `TikTokUnavailable` | temporal |
| OAuth `invalid_grant` | `TikTokGrantInvalid` | definitivo (código/refresh) |
| OAuth `access_denied` (no esperado fuera del callback) | `TikTokRejected` | definitivo |
| OAuth `invalid_client`, `unauthorized_client`, `invalid_request`, `invalid_scope`, `unsupported_*` | `TikTokClientError` | configuración; sin cambio de estado |
| API `access_token_invalid` | `TikTokTokenInvalid` | renovar una vez |
| API `scope_not_authorized`, `scope_permission_missed` | `TikTokScopeMissing(scope)` | `reconnect_required` |
| JSON inválido, campos ausentes, `token_type` ≠ Bearer, `invalid_params` | `TikTokUnexpectedResponse` | sin cambio de estado |

Los `log_id` de TikTok **sí** pueden registrarse (no son secretos y sirven para soporte).

## 15. Redacción de logs

- `RedactTikTokCallbackQuery` en `uvicorn.access`: cualquier ruta que empiece por
  `/api/tiktok/oauth/callback` (con o sin barra, con `?`) se registra como
  `/api/tiktok/oauth/callback?[redacted]`.
- `RedactTikTokSecrets` en `HTTP_LOGGERS` (httpx2/httpcore2): valores de `access_token`,
  `refresh_token`, `client_secret`, `code`, `code_verifier`, `code_challenge`, `state` y
  `token` en query o cuerpo; `Bearer …`; query de URLs de `www.tiktok.com/v2/auth/authorize/`.
  `client_key` no es secreto y no se redacta.
- Excepciones del gateway sin `__cause__` (`from None`) y sin `str` del cuerpo.
- No se registran respuestas OAuth crudas.

## 16. Configuración local

Archivo `backend/data/tiktok-app.json` (override `AUTOPUBLISHER_TIKTOK_APP_FILE`), ignorado por
Git (`data/` ya lo está; se añade `tiktok-app*.json` explícito):

```json
{ "client_key": "…", "client_secret": "…", "redirect_uri": "http://127.0.0.1:8000/api/tiktok/oauth/callback" }
```

`redirect_uri` opcional (por defecto el de §3). `client_secret` con `repr=False`. Nunca se
devuelve al frontend; `GET` de conexión solo expone `oauth_configured: bool`.

## 17. Sandbox, Content Posting API y `video.publish` (gate G)

Documentado: Sandbox sin App Review, ≤ 10 target users propios; Sandbox **no** ofrece Content
Posting API para vídeos públicos; clientes no auditados publican solo en privado; Direct Post
requiere aprobación del scope `video.publish` y activar la configuración Direct Post; los
vídeos por URL requieren dominio/prefijo verificado (solo `PULL_FROM_URL`, fuera de alcance).

No documentado: si `video.publish` es autorizable en Sandbox y si añadir Content Posting API al
Sandbox exige verificar URL/dominio para guardar la configuración. → **Gate G** del quickstart,
antes de implementar en profundidad, con STOP según spec FR-058b. No se inventan sitios, Privacy
Policy, Terms ni dominios.

## 18. Reglas de entidades inactivas (alineadas con 010)

| Operación | Account/Project inactivos |
|---|---|
| GET estado | permitido |
| authorize / callback (completar) / confirm | rechazado (`account_inactive`/`project_inactive`), sin contactar con TikTok |
| cancel intento | permitido |
| verify | rechazado |
| disconnect (incl. renovación previa solo para revocar) | permitido |
| remove-local | permitido |

## 19. Frontend: conocer el resultado del intento

Igual que YouTube: `authorize` devuelve `attempt_id` y `authorization_url`; el panel abre la
pestaña (`window.open` síncrono al clic para evitar bloqueos) y consulta
`GET /api/tiktok/oauth/attempts/{attempt_id}` cada 2 s hasta estado terminal o
`awaiting_confirmation`. El estado del intento nunca incluye `state`, verifier, código ni tokens.
La pestaña de TikTok termina, tras el `303` del callback, en la ruta limpia
`/api/tiktok/oauth/result?outcome=…` del backend (§6.1); no se redirige a la UI del frontend,
que corre en otro origen en desarrollo y conoce el resultado por el intento.
