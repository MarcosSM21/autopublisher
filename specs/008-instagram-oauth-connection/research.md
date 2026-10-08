# Research: Conexión de cuentas Instagram mediante Instagram Login

**Feature**: `008-instagram-oauth-connection` | **Fecha**: 2026-10-08

Todas las decisiones de protocolo se han contrastado con la documentación oficial vigente de
Meta (consultada el 2026-10-08). Donde la documentación es ambigua o no cubre un caso, se
indica explícitamente y se convierte en una comprobación obligatoria del `quickstart.md`. Lo
que no está confirmado no se da por supuesto.

Fuentes principales:

- Business Login for Instagram:
  <https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login>
- OAuth Authorize reference:
  <https://developers.facebook.com/docs/instagram-platform/reference/oauth-authorize/>
- Get started (Instagram API with Instagram Login):
  <https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started>
- Instagram Platform overview (access levels, tokens):
  <https://developers.facebook.com/docs/instagram-platform/overview>
- Content Publishing:
  <https://developers.facebook.com/docs/instagram-platform/content-publishing>
- IG User Media reference:
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media>

---

## 1. API elegida: Instagram API with Instagram Login

**Decision**: usar exclusivamente **Instagram API with Instagram Login** (host
`graph.instagram.com`, permisos `instagram_business_*`).

**Rationale**: conecta directamente cuentas Professional (Business y Creator) sin Facebook
Page. Los permisos para publicar con esta variante son exactamente
`instagram_business_basic` + `instagram_business_content_publish`, mientras que la variante
con Facebook Login exige `instagram_basic`, `instagram_content_publish` y
`pages_read_engagement` y una Page vinculada.

**Alternatives considered**: Instagram API with Facebook Login. Rechazada: no se ha
encontrado ninguna necesidad técnica que la justifique; ambas variantes soportan Content
Publishing según la documentación. Nota para la Feature 009: la subida reanudable de vídeo
(`upload_type=resumable`) está documentada solo para Facebook Login for Business (ver §16);
no basta por sí sola para cambiar de variante en esta feature.

---

## 2. Endpoints y parámetros de autorización

**Decision**:

- Autorización (navegador): `GET https://www.instagram.com/oauth/authorize` con
  - `client_id` = Instagram App ID (no el Facebook App ID; aparece en *Instagram > API setup
    with Instagram login* del App Dashboard);
  - `redirect_uri` = el valor configurado (ver §3), exactamente igual al registrado;
  - `response_type=code`;
  - `scope=instagram_business_basic,instagram_business_content_publish` (lista separada por
    comas, formato documentado);
  - `state` = 32 bytes aleatorios (`secrets.token_urlsafe(32)`);
  - `force_reauth=true`, para que el usuario introduzca conscientemente las credenciales de
    la cuenta Professional que quiere conectar en cada Connect/Reconnect (equivalente al
    `select_account` usado con Google; evita reconectar en silencio la sesión de Instagram
    abierta en el navegador).
- No se envía `enable_fb_login` (se deja el comportamiento por defecto de Meta).
- Respuestas al `redirect_uri`:
  - éxito: `?code=…&state=…` y Meta añade `#_` al final; `#_` **no** forma parte del código
    y se elimina;
  - cancelación: `?error=access_denied&error_reason=user_denied&error_description=…&state=…`.
- El código de autorización es válido 1 hora y de un solo uso.

**Rationale**: valores literales de la documentación de Business Login y OAuth Authorize.

**Alternatives considered**: los antiguos scopes (`business_basic`, etc.) quedaron obsoletos
el 27-01-2025; no se usan.

---

## 3. Redirect URI para una aplicación local (decisión principal del plan)

**Hallazgo**: el App Dashboard de Meta **exige HTTPS** en los *OAuth redirect URIs* de
Instagram Login; rechaza `http://localhost`/`http://127.0.0.1` ("your new URL must use SSL
and start with https"). Por tanto, **no** puede reutilizarse el callback loopback HTTP de la
Feature 005 (`http://127.0.0.1:8000/api/youtube/oauth/callback`). El URI debe coincidir
exactamente con uno registrado (el dashboard puede añadir una barra final; las mayúsculas
importan).

**Decision**: flujo **"pegar la dirección de redirección"** (manual paste) con un redirect URI
HTTPS en `localhost` en el que no escucha nada:

1. El usuario registra en la Meta App un redirect URI HTTPS local, por defecto
   `https://localhost/autopublisher/instagram/callback`, y lo pone en la configuración local
   (§7). Terminología: en esta feature "callback"/"redirect" designa la **redirect URL**
   producida por Meta; AutoPublisher no la recibe mediante un servidor HTTPS de callback.
2. `Connect Instagram` abre la URL de autorización en una pestaña nueva.
3. Tras el consentimiento, Instagram redirige a `https://localhost/...?code=…&state=…#_`.
   Como no hay ningún servidor HTTPS ahí, el navegador muestra una página de error de
   conexión, pero **la barra de direcciones contiene la URL completa**.
4. El panel de AutoPublisher muestra un campo "Paste the address of the page Instagram
   opened". El usuario pega la URL y pulsa *Complete connection*.
5. El frontend envía la redirect URL pegada **en el cuerpo de un POST** (nunca en la URL de
   la petición) a `POST /api/instagram/oauth/attempts/{attempt_id}/complete`, limpia el campo
   y descarta la URL; nunca la guarda en ningún almacenamiento. `complete` devuelve el
   resultado del intento de forma síncrona (no hay ruta para consultar intentos).
6. El backend comprueba que la URL pegada empieza por el redirect URI configurado, extrae
   `state`, `code` o `error`, valida el `state` contra ese intento y continúa el flujo.

**Rationale**:

- Sin TLS local, sin certificados autofirmados, sin dependencias nuevas, sin túneles ni
  servidores públicos: la solución correcta más sencilla (Constitution I).
- El código solo sirve junto con el app secret, que nunca sale del backend, y es de un solo
  uso con caducidad de 1 hora; el `state` sigue protegiendo contra CSRF y contra callbacks
  reutilizados o de otra cuenta.
- Ningún tercero recibe el código: `localhost` no sale de la máquina.

**Riesgo pendiente de validación real**: la documentación no dice expresamente si
`https://localhost/...` se acepta como redirect URI de Instagram Login (hay informes de
desarrolladores que usan `https://localhost:<port>/...`). El `quickstart.md` lo valida en el
primer paso. **Si Meta lo rechaza, se detiene la validación y se revisa esta decisión antes de
continuar** (no se usará un redirect URI en un dominio de terceros).

**Alternatives considered**:

- *Listener HTTPS local con certificado autofirmado* (p. ej. `https://localhost:8443`):
  redirección automática sin pegar nada, pero requiere generar y gestionar certificados, un
  segundo servidor y aceptar avisos de certificado no confiable en el navegador. Más
  complejo; puede añadirse en una feature futura sin cambiar el modelo de datos.
- *mkcert / CA local*: instala una CA en el sistema; demasiado intrusivo.
- *Túnel público (ngrok, Cloudflare Tunnel)* o *página puente en un dominio público*:
  introduce servicios externos que podrían ver el código; contrario a la naturaleza local.
- *Callback HTTP loopback como en YouTube*: no admitido por Meta.

---

## 4. PKCE

**Decision**: **no** se usa PKCE. Seguridad del flujo: `state` aleatorio de un solo uso
ligado a un intento y una `Account`, código de un solo uso, intercambio en el backend con el
app secret.

**Rationale**: ni la referencia de OAuth Authorize ni la guía de Business Login documentan
`code_challenge`/`code_verifier`. No se envían parámetros no documentados (spec FR-017).

**Alternatives considered**: enviar PKCE "por si acaso": rechazado, comportamiento no
documentado.

---

## 5. Intercambio de tokens y ciclo de vida

**Decision**:

1. **Código → token de corta duración** (1 h):
   `POST https://api.instagram.com/oauth/access_token` con cuerpo de formulario
   `client_id`, `client_secret`, `grant_type=authorization_code`, `redirect_uri`, `code`.
   Respuesta documentada: `{"data": [{"access_token", "user_id", "permissions"}]}`.
   El parser acepta esa forma documentada y, de forma tolerante, el mismo objeto sin el
   envoltorio `data` (forma observada habitualmente); cualquier otra forma es
   `instagram_unexpected_response`. El `quickstart.md` registra qué forma devuelve Meta.
2. **Corta → larga duración** (60 días):
   `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=…&access_token=…`.
   Respuesta: `{"access_token", "token_type": "bearer", "expires_in"}`. Debe hacerse en el
   backend y con el token corto aún válido; se hace inmediatamente después del paso 1.
   El token corto se descarta: **solo el token largo se guarda**.
3. **Renovación**:
   `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=…`.
   Condiciones oficiales: el token largo tiene **al menos 24 h**, sigue **vigente** y la
   cuenta concedió `instagram_business_basic`. Devuelve un nuevo token largo de 60 días. Un
   token que no se renueva en 60 días caduca y **ya no puede renovarse**.

No existe refresh token separado: el propio token largo se renueva (estrategia distinta de
Google, que no se reutiliza).

**Política de renovación** (en `get_valid_credentials`, ver data-model):

- `REFRESH_MIN_AGE = 24 h` (mínimo oficial) y `EXPIRY_MARGIN = 5 min`.
- Si el token ha caducado o le quedan menos de `EXPIRY_MARGIN` → se intenta renovar; si no
  puede renovarse → `Reconnect required`.
- Si tiene ≥ 24 h de antigüedad → se renueva de forma oportunista (como mucho una vez al día
  por cuenta). Si la renovación falla **temporalmente** y el token actual sigue vigente, se
  devuelve el token actual y se registra un aviso sin datos sensibles; la cuenta sigue
  `Connected`.
- Si tiene < 24 h → se usa tal cual (renovar fallaría).
- Cada renovación correcta sustituye el secreto en el almacén seguro y actualiza
  `credential_expires_at` en SQLite. Un candado por cuenta evita renovaciones concurrentes.

**Sin renovación en segundo plano**: esta feature solo renueva cuando AutoPublisher necesita
la credencial (Verify y, en la Feature 009, publicar). Si una cuenta no se usa durante ~60
días, su token caduca y pasa a `Reconnect required`. La interfaz muestra la fecha de
caducidad del acceso para que el usuario lo sepa. Un mantenimiento periódico se puede
añadir en la Feature 009 si el scheduler lo requiere; aquí añadiría infraestructura sin
necesidad real (Constitution I).

**Rationale**: reglas literales de la documentación; maximiza la vida útil sin llamadas
innecesarias.

**Alternatives considered**: renovar en cada uso (falla las primeras 24 h y escribe en el
keyring constantemente); refresco periódico en el scheduler (acopla el núcleo del scheduler
a Instagram).

---

## 6. Comprobación de permisos efectivos (FR-007)

**Decision**: el mecanismo documentado para Instagram Login es el campo **`permissions`**
(cadena separada por comas) de la respuesta del intercambio código → token (§5.1). La
conexión solo se completa si contiene `instagram_business_basic` **y**
`instagram_business_content_publish`; si falta alguno → `instagram_permission_missing`
indicando cuál. Si la respuesta no trae el campo `permissions`, no puede verificarse y la
conexión **no** se completa (`instagram_unexpected_response`).

**No** se usan `/me/permissions`, Access Token Debugger (`debug_token`) ni mecanismos de
Facebook Login: no están documentados para esta variante. Los permisos verificados se guardan
dentro del secreto (no son sensibles, pero no se necesitan en SQLite).

En la renovación y en Verify no hay un mecanismo documentado para re-consultar la lista de
permisos concedidos. `Verify connection` comprueba los permisos de forma indirecta: si Meta
responde a `/me` o a la renovación con un error de permisos (clasificado por el gateway como
`MetaPermissionDenied`), la conexión pasa a `Reconnect required` y la API devuelve
`409 instagram_reconnect_required` con un mensaje seguro que indica que falta o se retiró un
permiso necesario (y cuál, si Meta lo indica de forma segura y es uno de los dos
requeridos). La identidad pública se conserva.

**Validación real**: el `quickstart.md` comprueba que el campo `permissions` llega y contiene
ambos permisos. Si Meta no lo devolviera, se detiene la validación y se revisa esta decisión.

---

## 7. Configuración local de la Meta App

**Decision**:

- Archivo JSON local, por defecto `backend/data/instagram-app.json`, sobreescribible con
  `AUTOPUBLISHER_INSTAGRAM_APP_FILE`:

  ```json
  {
    "app_id": "<Instagram App ID>",
    "app_secret": "<Instagram App Secret>",
    "redirect_uri": "https://localhost/autopublisher/instagram/callback"
  }
  ```

- Validación: `app_id` cadena numérica no vacía, `app_secret` no vacía, `redirect_uri`
  `https`, con host, sin fragmento. Si falta o no es válido → `instagram_oauth_not_configured`.
- Se lee en cada operación que la necesita (no requiere reiniciar), igual que YouTube.
- Nunca se envía al frontend; `GET …/instagram-connection` solo expone el booleano
  `oauth_configured`.
- `backend/data/` ya está ignorado; además `.gitignore` añade patrones específicos:
  `instagram-app*.json` y `meta-app*.json`.
- No se versiona ningún ejemplo con valores que parezcan reales; la documentación muestra
  marcadores `<…>`.

**Rationale**: mismo patrón que `google-oauth-client.json` (Feature 005), fuera de SQLite y
de Git.

**Alternatives considered**: variables de entorno con el secret (se filtran fácilmente a
procesos hijos y a historiales de shell); guardar el app secret en el keyring (complica la
configuración inicial sin beneficio claro para un archivo ya fuera de Git y del repositorio).

---

## 8. Identidad de la cuenta y tipo Professional

**Decision**: tras obtener el token largo, se consulta
`GET https://graph.instagram.com/v26.0/me?fields=user_id,id,username,account_type,profile_picture_url`.

- `user_id` = **Instagram professional account ID** → identidad autoritativa
  (`instagram_user_id`), base de la unicidad por proyecto y de la comparación en Verify.
- `id` = ID *app-scoped* → se guarda como dato público auxiliar (`app_scoped_id`); no se usa
  para la unicidad.
- `account_type`: documentado como `Business` o `Media_Creator`; se normaliza a mayúsculas
  (`BUSINESS` / `MEDIA_CREATOR`). Cualquier otro valor o su ausencia →
  `instagram_account_not_professional`, sin guardar credenciales.
- `profile_picture_url`: opcional; es una URL de CDN firmada que caduca. Se guarda y se
  muestra si está; si la imagen no carga, la interfaz muestra un marcador neutro.
- No se compara el `user_id` de la respuesta del intercambio de código con el de `/me`: la
  documentación lo describe como "Instagram-scoped user ID" sin precisar a cuál de los dos
  IDs de `/me` corresponde. La identidad autoritativa sale siempre de `/me`.
- Si `/me` no devuelve `user_id` o `username` → `instagram_unexpected_response`.

**Graph API version**: `v26.0`, la versión más reciente de Graph API (publicada por Meta el
29-07-2026); al ser una integración nueva se usa la última versión y no la `v25.0` que
aparece en algunos ejemplos anteriores de la documentación. Se define como constante única
(`GRAPH_API_VERSION`) en `instagram_gateway.py` y solo se aplica a los endpoints versionados
(`/me`). Los endpoints
de token (`/access_token`, `/refresh_access_token`) se documentan sin versión y se usan así.

**Rationale**: la documentación distingue `id` (app-scoped) de `user_id` ("Instagram
professional account ID"), que es el ID usado en Content Publishing (`/<IG_ID>/media`).

---

## 9. Clasificación de errores de Meta

**Decision** (en `instagram_gateway.py`):

| Situación | Excepción interna | Resultado |
|---|---|---|
| Error de transporte/timeout, HTTP 5xx, HTTP 429 | `MetaUnavailable` | error temporal (`instagram_unavailable`), sin cambio de estado |
| Graph error `code` 1, 2, 4, 17, 32, 613 (límites/temporales) | `MetaUnavailable` | ídem |
| Graph error `code` 190 (token inválido, caducado o revocado) | `MetaTokenInvalid` | `Reconnect required` |
| Graph error `code` 10 o 200–299 (permiso) | `MetaPermissionDenied` (con el permiso afectado si Meta lo indica de forma segura) | en `complete`: `instagram_permission_missing`; en Verify y uso posterior: `instagram_reconnect_required` + `Reconnect required`, mensaje "falta o se retiró un permiso necesario" |
| Intercambio de código rechazado (`OAuthException`, código usado/no encontrado, redirect URI distinto) | `MetaRejected` | `instagram_token_exchange_failed` |
| Renovación rechazada con 190 | `MetaTokenInvalid` | `instagram_reconnect_required` + `Reconnect required` (causa interna "refresh fallido"; no es un código público) |
| Otro 4xx | `MetaRejected` | según operación (exchange failed / unexpected) |
| JSON no válido o sin los campos esperados | `MetaUnexpectedResponse` | `instagram_unexpected_response` |

Ninguna excepción incluye el cuerpo de la respuesta, la URL ni ningún token; se lanzan con
`from None` para no encadenar excepciones de `httpx` que contienen la URL.

Los números de error solo se interpretan en el gateway; el servicio trabaja con la
clasificación semántica (`MetaUnavailable`, `MetaTokenInvalid`, `MetaPermissionDenied`, …).
Un fallo de renovación temporal y recuperable nunca produce `Reconnect required`; uno
definitivo produce `instagram_reconnect_required`. No existe el código público
`instagram_token_refresh_failed`.

**Rationale**: códigos de error estándar de Graph API (190 = OAuthException de token,
4/17/32/613 = rate limiting, 10/2xx = permisos). Solo los errores definitivos de token o
permiso pasan a `Reconnect required`; los temporales nunca (FR-033).

---

## 10. Revocación remota

**Decision**: `Disconnect` **no** contacta con Meta. Elimina el secreto del almacén seguro y
luego la fila local. La interfaz y la documentación indican cómo retirar el acceso
manualmente: Instagram → *Settings and activity* → *Website permissions* → *Apps and
websites* → quitar la app.

**Rationale**: Instagram Login no documenta un endpoint de revocación aislado para una
conexión (el *Deauthorize callback* es un webhook entrante, no una acción del cliente). No se
ejecutan acciones con efectos no garantizados (spec FR-039).

---

## 11. Intentos OAuth pendientes

**Decision**:

- Registro en memoria propio de Instagram (`InstagramAttemptRegistry` en
  `instagram_oauth.py`), con la misma semántica que el de YouTube:
  - TTL del intento: **10 minutos** (el código vale 1 h, pero el intento caduca antes);
  - latest-attempt-wins: crear un intento expira los no terminales de la misma cuenta;
  - el `state` se consume una sola vez y solo si coincide (comparación en tiempo constante);
  - un `state` que no coincide **no** consume el intento (un pegado erróneo no lo invalida);
  - resultados terminales (`completed`, `failed`, `cancelled`, `expired`) se conservan sin
    secretos **10 minutos** y después se purgan;
  - las credenciales pendientes de confirmación de cambio de cuenta viven solo en el
    intento, en memoria, y se borran al terminar.
- Reinicio del backend: todos los intentos se pierden. Completar uno inexistente devuelve
  `instagram_oauth_attempt_expired` y el usuario empieza de nuevo.

**Rationale**: reutiliza las decisiones de producto de la Feature 005.

**Alternatives considered**: generalizar el registro de YouTube (`youtube_oauth.py`) en un
módulo común. Rechazado en esta feature: obligaría a modificar código de YouTube ya validado
(PKCE, `ChannelInfo`) fuera del alcance. La duplicación es acotada (~150 líneas) y se anota
como posible refactor futuro.

---

## 12. Almacenamiento seguro

**Decision**: reutilizar `KeyringCredentialStore` de `credential_store.py` con un servicio
propio, `autopublisher.instagram` (constante `INSTAGRAM_SERVICE`), sin cambiar su allow-list
de backends ni su política de no-fallback. `create_app` recibe un parámetro nuevo
`instagram_credential_store`; los tests inyectan siempre un `InMemoryCredentialStore`, de modo
que nunca se toca el keyring real.

Secreto guardado (JSON, solo en el keyring):

```json
{"access_token": "…", "issued_at": "…", "expires_at": "…",
 "permissions": ["instagram_business_basic", "instagram_business_content_publish"]}
```

SQLite guarda solo `credential_ref` (UUID hex aleatorio) y `credential_expires_at`
(timestamp no sensible para mostrar la caducidad).

**Rationale**: FR-025; servicio separado para que el usuario identifique y borre entradas
huérfanas de Instagram con las herramientas del sistema.

---

## 13. Logging

**Decision**:

- Las URLs de `graph.instagram.com` llevan `access_token` y `client_secret` en la query
  (así están documentados los endpoints de token), y `httpx2` registra cada URL a nivel INFO.
  Se añade un filtro `RedactInstagramSecrets` a los mismos loggers HTTP que YouTube
  (`HTTP_LOGGERS`) que sustituye los valores de `access_token`, `client_secret`, `code`,
  `state` y `Authorization: Bearer …` por `[redacted]`.
- Para `/me` también se envía el token como parámetro `access_token` (forma documentada), por
  lo que queda cubierto por el mismo filtro.
- No hay callback HTTP en el backend, así que no aparece ninguna URL con `code`/`state` en el
  access log de uvicorn; la URL pegada viaja en el cuerpo del POST, que uvicorn no registra.
- Los mensajes de log propios solo incluyen `account_id`, tipo de error y nombres de
  excepción.
- Tests específicos capturan los logs (incluido nivel DEBUG de los loggers HTTP) y comprueban
  la ausencia de todos los valores secretos de los fakes.

---

## 14. Frontend

**Decision**: `InstagramConnectionPanel.tsx`, montado desde `AccountList.tsx` con la misma
condición por plataforma que `YouTubeConnectionPanel` (punto de extensión ya existente).
Estados `Not connected` / `Connected` / `Reconnect required`, el flujo de pegado de la URL,
la advertencia de cambio de cuenta (actual vs nueva, username e ID) y la fecha de caducidad
del acceso. El campo de pegado se vacía tras enviarlo y nunca se persiste; el test existente
`storage-safety.test.tsx` sigue garantizando que no se usa almacenamiento del navegador.

---

## 15. App Review, Development Mode y acceso

**Hallazgos**:

- Meta ofrece **Standard Access** (por defecto, sin App Review) y **Advanced Access** (con App
  Review y Business Verification).
- Standard Access está pensado para apps que solo sirven cuentas **propias o gestionadas** por
  quien tiene un rol en la app, y para desarrollo/pruebas.
- Advanced Access es necesario para servir cuentas de usuarios que no tienen rol en la app (o
  en el Business propietario de la app).
- La app debe ser de tipo **Business** en el App Dashboard.

**Decision**:

- Desarrollo local: el usuario crea su propia Meta App (tipo Business), añade el producto
  Instagram con *API setup with Instagram login* y añade su cuenta Instagram Professional
  como **Instagram tester / rol** de la app (y acepta la invitación desde Instagram).
- Durante el `quickstart.md` se comprueba qué permisos funcionan en Development Mode con
  Standard Access. Si Meta exige App Review/Advanced Access para alguno de los dos permisos
  incluso con la propia cuenta, se documenta y **se detiene la validación**
  correspondiente.
- Distribuir AutoPublisher a otros usuarios significa que cada usuario crea su propia Meta App
  (modelo de app local). Usar una única app para cuentas de terceros requeriría Advanced
  Access, App Review y Business Verification, fuera de alcance.
- AutoPublisher nunca intenta eludir App Review ni restricciones de Meta.

---

## 16. Investigación para la Feature 009 (sin implementar)

Modelo vigente de **Content Publishing** con Instagram Login (`graph.instagram.com`):

1. **Crear container**: `POST /<IG_ID>/media`.
   - Imagen: `image_url` (JPEG).
   - Reel: `media_type=REELS` + `video_url`.
   - Otros (fuera de alcance): `STORIES`, `CAROUSEL`, `VIDEO` en carrusel.
   - Reels admiten `cover_url` o `thumb_offset` (ms); si van ambos, gana `cover_url`.
2. **Esperar a que esté listo**: `GET /<IG_CONTAINER_ID>?fields=status_code` →
   `IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, `PUBLISHED`. Recomendación oficial:
   consultar **una vez por minuto durante un máximo de 5 minutos**.
3. **Publicar**: `POST /<IG_ID>/media_publish` con `creation_id=<container>`.
4. **Media accesible (conclusión provisional para Instagram Login)**:
   - Imágenes (`image_url`): Meta descarga el archivo desde la URL, que "must be on a public
     server". Requieren **URL pública**.
   - Vídeos/Reels (`video_url`): con Instagram Login deben considerarse también
     **dependientes de una URL pública**.
   - La subida reanudable (`upload_type=resumable` + `POST
     https://rupload.facebook.com/ig-api-upload/<IG_MEDIA_CONTAINER_ID>`, que admite un
     archivo local) está documentada en Content Publishing **"Only for apps that have
     implemented Facebook Login for Business"**. Como esta integración usa Instagram Login,
     **no se cuenta con ella**. No se ha encontrado documentación oficial vigente que confirme
     un mecanismo de subida binaria/local compatible con Instagram Login.
   - Consecuencia: la Feature 009 deberá probablemente resolver un **mecanismo seguro de
     hosting temporal** accesible por Meta para **imágenes y vídeos**. Esta feature no lo
     elige ni lo implementa; la decisión y su verificación contra la documentación vigente
     corresponden a la Feature 009 (incluida, si procede, la reevaluación de la variante de
     login).
5. **Límites de formato**:
   - Imagen: solo **JPEG**, máx. **8 MB**, relación de aspecto **4:5 a 1.91:1**, ancho
     320–1440 px; Meta convierte a sRGB.
   - Reel: **MOV o MP4** (sin edit lists, `moov` al principio), **H.264 o HEVC**, progresivo,
     closed GOP, 4:2:0, **23–60 fps**, audio **AAC** ≤ 48 kHz 1–2 canales a 128 kbps, vídeo
     ≤ 25 Mbps, duración **3 s – 15 min**, máx. **300 MB**, recomendado **9:16**.
6. **Límite de publicación**: **100 publicaciones por API en 24 h móviles** por cuenta (un
   carrusel cuenta como una); consultable con `GET /<IG_ID>/content_publishing_limit`.
7. **Caducidad del container**: **24 horas**; después pasa a `EXPIRED`.
8. **Business vs Creator**: la documentación de Content Publishing y de especificaciones de
   media no distingue entre ambos tipos; los dos son "Instagram professional accounts".
9. **App Review / Development Mode**: ver §15; para publicar en la propia cuenta basta,
   previsiblemente, Standard Access con la cuenta como tester (a confirmar en esta feature).

**Implicaciones para 009** (no se resuelven aquí): idempotencia ante fallos entre container y
`media_publish` (estado remoto ambiguo), conversión/validación de formatos, mecanismo seguro
de hosting temporal para imágenes y vídeos, y uso de `content_publishing_limit` en la preflight. Esta
feature deja preparado `get_valid_credentials` y `fetch_identity`/`verify_identity` para el
futuro `InstagramPublisher`.
