# Feature Specification: Conexión de cuentas reales de TikTok mediante OAuth oficial (Login Kit for Desktop)

**Feature Branch**: `012-tiktok-oauth-connection`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Feature 012 — TikTok Account Connection & OAuth. Permitir conectar una `Account` de plataforma TikTok a una cuenta TikTok real mediante el OAuth oficial de TikTok Login Kit (preferentemente Login Kit for Desktop, OAuth v2, PKCE obligatorio y callback HTTP local automático del backend): Connect, callback real, Verify, renovación segura on-demand del access token con rotación del refresh token, Reconnect crash-safe, Disconnect con revocación oficial, identidad `open_id`, persistencia de identidad pública y almacenamiento de access/refresh token solo en el almacén seguro. Solicitar únicamente `user.info.basic` y `video.publish`. Desarrollo con TikTok Developer Sandbox sin App Review. Sin publicar contenido (Feature 013)."

## Contexto

Desde las Features 005, 008 y 010, las `Account` de YouTube, Instagram y Threads pueden
vincularse con cuentas reales mediante OAuth. Las `Account` de plataforma TikTok siguen siendo
registros locales (plataforma, handle y nombre visible) sin relación con ninguna cuenta real.

Esta feature introduce la **conexión real con TikTok**: una `Account` de plataforma TikTok puede
vincularse, mediante la autorización oficial de **TikTok Login Kit** en el navegador del usuario,
con una cuenta de TikTok real. AutoPublisher identifica la cuenta autorizada por su **`open_id`**,
guarda de forma segura las credenciales necesarias para actuar en su nombre más adelante y
muestra en la interfaz qué cuenta real está vinculada.

Ejemplo:

`TikTok @cyber.studio` → `Connect TikTok` → login y consentimiento en TikTok → vuelta automática
a AutoPublisher → cuenta identificada (`Cyber Studio`, avatar) → `Connected`

El objetivo es dejar la conexión lista para que la Feature 013 pueda publicar en TikTok a través
del sistema genérico de publishers existente. **En esta feature no se publica nada.**

La conexión no crea un sistema paralelo de cuentas: siempre se vincula a una `Account` existente
cuya plataforma es TikTok. El núcleo común de Accounts permanece independiente de TikTok, igual
que de YouTube, Instagram y Threads. TikTok tiene su propia aplicación, su propio OAuth, sus
propios tokens, su propia configuración local y su propio espacio en el almacén seguro. YouTube,
Instagram y Threads conservan su comportamiento actual.

A diferencia de Threads (Feature 010), TikTok Login Kit for Desktop admite redirect URIs HTTP de
loopback con puerto, por lo que **el usuario no copia ni pega ninguna URL**: TikTok redirige el
navegador al backend local de AutoPublisher, que completa la conexión automáticamente (patrón más
próximo al de YouTube, Feature 005).

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login propio.

## Restricciones de la plataforma (documentación oficial de TikTok, consultada 2026-10-14)

Estos hechos condicionan el comportamiento del producto. El plan DEBE reconfirmarlos y fijar los
detalles técnicos (parámetros exactos, formatos, clasificación de errores) en `research.md`.

- **Tipo de integración**: Login Kit for **Desktop**, OAuth v2. Ventana de autorización
  `https://www.tiktok.com/v2/auth/authorize/` con `client_key`, `scope` (lista separada por comas),
  `response_type=code`, `redirect_uri`, `state`, `code_challenge` y `code_challenge_method=S256`.
  No se usan endpoints OAuth legacy.
- **Redirect URI Desktop**: absoluto, `http` o `https`, estático (sin parámetros ni fragmento),
  host **solo** `localhost` o `127.0.0.1`, **puerto obligatorio**; se admite **puerto comodín**
  (`*`). Máximo 10 URIs registrados, cada uno < 512 caracteres. El `redirect_uri` enviado debe
  coincidir exactamente con uno registrado y con el usado en el intercambio del código.
- **PKCE (obligatorio en Desktop)**: `code_verifier` nuevo por autorización, de 43 a 128
  caracteres del conjunto `[A-Z] [a-z] [0-9] - . _ ~`; solo `S256`. La documentación de Desktop
  indica que el `code_challenge` es el SHA256 del verifier **codificado en hexadecimal**, lo que
  **difiere** de RFC 7636 (base64url). Los ejemplos oficiales contienen además errores evidentes
  (generación con `Math.random()`, challenge igual al verifier). El plan DEBE fijar la codificación
  exacta y el quickstart DEBE confirmarla con TikTok real.
- **Callback**: TikTok redirige a `redirect_uri` con `code`, `scopes` (concedidos, separados por
  comas), `state`, o bien `error` y `error_description`. Los scopes pueden ser **opcionales para el
  usuario**: puede conceder solo un subconjunto. La validez del `code` no está documentada en la
  página de Desktop.
- **Intercambio y renovación**: `POST https://open.tiktokapis.com/v2/oauth/token/` con
  `application/x-www-form-urlencoded`. Intercambio: `client_key`, `client_secret`, `code`,
  `grant_type=authorization_code`, `redirect_uri` y, en Desktop, `code_verifier`. Renovación:
  `client_key`, `client_secret`, `grant_type=refresh_token`, `refresh_token`. Ambas respuestas
  devuelven `open_id`, `scope`, `access_token`, `expires_in`, `refresh_token`,
  `refresh_expires_in` y `token_type`. Valores de referencia documentados: access token 24 h y
  refresh token 365 días desde la emisión inicial — **solo orientativos**: AutoPublisher usa los
  valores devueltos. **El refresh token devuelto en una renovación puede ser distinto** del
  enviado y, en ese caso, debe usarse el nuevo.
- **Revocación**: `POST https://open.tiktokapis.com/v2/oauth/revoke/` con `client_key`,
  `client_secret` y `token` (= **access token** del usuario). Éxito: respuesta vacía, y la app
  desaparece de *Manage app permissions* del usuario.
- **Errores OAuth**: JSON con `error`, `error_description` y `log_id`. Errores de la API v2:
  `error.code`, `error.message`, `error.log_id`, con códigos documentados como
  `access_token_invalid` (401), `scope_not_authorized` (401), `scope_permission_missed` (400),
  `rate_limit_exceeded` (429), `invalid_params` (400) e `internal_error` (500). Los códigos OAuth
  concretos de grant inválido/caducado no figuran en las páginas consultadas: el plan DEBE
  verificarlos.
- **Identidad** (`GET https://open.tiktokapis.com/v2/user/info/` con `fields`): con
  `user.info.basic` están disponibles `open_id`, `union_id`, `avatar_url`, `avatar_url_100`,
  `avatar_large_url` y `display_name`. **`username` NO está bajo `user.info.basic`** (requiere
  `user.info.profile`, que no se solicita). No existe operación oficial de inspección de token
  equivalente a `debug_token` de Meta.
- **Sandbox**: hasta 5 sandboxes por app, sin App Review; hasta 10 **target users** (cuentas
  propias) añadidos en *Sandbox settings → Target users*, que aceptan los términos de TikTok
  Developer (pueden tardar hasta 1 h en aparecer). La documentación indica que el Sandbox **no
  ofrece Content Posting API para vídeos públicos**; no aclara si `video.publish` puede
  autorizarse en Sandbox. Content Posting API puede exigir verificación de URL o dominio incluso
  en Sandbox. El contenido de clientes no auditados queda restringido a visibilidad privada
  (relevante para la Feature 013, no para esta). Estas incógnitas se resuelven en el gate
  temprano de viabilidad (FR-058a/FR-058b).

Fuentes: TikTok for Developers — *Login Kit for Desktop*, *Manage User Access Tokens*,
*Get User Info*, *Error Handling (API v2)*, *Add a Sandbox*, *Content Posting API — Get Started*.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conectar una Account de TikTok con una cuenta TikTok real (Priority: P1)

Como usuario, quiero pulsar `Connect TikTok` en una cuenta TikTok de un proyecto, iniciar sesión
y autorizar a AutoPublisher en la página oficial de TikTok y volver automáticamente a
AutoPublisher con la cuenta real vinculada, sin copiar ni pegar nada, para que la aplicación
quede preparada para publicar en ella.

**Why this priority**: es el núcleo de la feature; sin una primera conexión no existe nada que
verificar, renovar, reconectar ni desconectar.

**Independent Test**: con la configuración local de la aplicación TikTok preparada, en un
proyecto activo abrir la cuenta activa `TikTok @cyber.studio` (estado `Not connected`), pulsar
`Connect TikTok`, completar la autorización concediendo ambos permisos y comprobar que, sin pasos
manuales adicionales, la cuenta aparece como `Connected` con nombre visible, avatar y caducidades
conocidas, y que ni la base de datos ni el navegador contienen tokens.

**Acceptance Scenarios**:

1. **Given** una cuenta TikTok activa de un proyecto activo en estado `Not connected` y la
   configuración local de TikTok presente, **When** el usuario pulsa `Connect TikTok`, **Then**
   se abre en su navegador la página oficial de autorización de TikTok para AutoPublisher,
   solicitando únicamente `user.info.basic` y `video.publish`, con un `state` y un desafío PKCE
   nuevos, y la interfaz muestra el estado `Connecting` con opción de cancelar.
2. **Given** una autorización iniciada, **When** el usuario concede ambos permisos, **Then** TikTok
   redirige el navegador al callback local de AutoPublisher, que valida la respuesta, intercambia
   el código con el `code_verifier` del intento, confirma los permisos y la identidad mediante la
   API oficial y vincula la cuenta, sin intervención adicional del usuario.
3. **Given** el callback procesado, **When** el navegador termina, **Then** muestra una página
   local mínima o una ruta limpia de AutoPublisher con el resultado, sin `code`, `state`, tokens
   ni errores crudos en esa URL final ni en el contenido (la URL entrante del callback, que sí
   los contiene por exigencia de TikTok, se consume y se sustituye de inmediato); y la vista de la `Account` en AutoPublisher
   pasa por sí sola de `Connecting` a `Connected`.
4. **Given** una conexión completada, **When** el usuario consulta la cuenta, **Then** ve, al
   menos, nombre visible de TikTok, avatar si está disponible, estado, fecha de conexión, fecha de
   última verificación, caducidad del access token y caducidad de la autorización renovable.
5. **Given** una conexión completada, **When** se inspeccionan la base de datos local, los logs,
   las respuestas que recibe la interfaz, las URLs finales del navegador y el almacenamiento del
   navegador, **Then** ninguno contiene access token, refresh token, código de autorización,
   `code_verifier`, `state` completo ni client secret; `code` y `state` solo existieron en la URL
   entrante del callback exigida por TikTok, que no se persiste, no se registra y es sustituida de
   inmediato por una URL limpia.
6. **Given** una cuenta conectada, **When** se reinician backend y frontend, **Then** la cuenta
   sigue `Connected` con la misma cuenta de TikTok, sin pedir de nuevo la autorización.
7. **Given** una cuenta de plataforma distinta de TikTok, **When** el usuario la consulta,
   **Then** no se muestra el panel de conexión de TikTok, y si se fuerza una operación de conexión
   de TikTok se rechaza como plataforma no soportada.
8. **Given** que falta o está incompleta la configuración local de TikTok, **When** el usuario
   pulsa `Connect TikTok`, **Then** no se abre el navegador y recibe un mensaje claro
   (`tiktok_oauth_not_configured`) que indica dónde está la documentación para configurarla.

---

### User Story 2 - Manejar errores de autorización, PKCE y permisos parciales (Priority: P1)

Como usuario, quiero que cualquier cancelación, fallo, callback inválido o concesión parcial de
permisos me muestre un mensaje comprensible y deje mi cuenta en un estado coherente, para poder
reintentar sin quedarme con conexiones a medias.

**Why this priority**: el flujo OAuth con callback automático y permisos opcionales tiene muchos
caminos de fallo; sin manejarlos la conexión no es segura ni fiable.

**Independent Test**: simulando (sin TikTok real) rechazo del consentimiento, error de TikTok,
callback sin parámetros o con parámetros duplicados/contradictorios, `state` desconocido,
reutilizado, caducado o sustituido por un intento más reciente, callback repetido, fallo del
intercambio, concesión de un solo scope, `open_id` incoherente entre respuestas y TikTok
inaccesible, comprobar en cada caso que el usuario ve un mensaje claro, que la cuenta conserva
exactamente su estado anterior y que no queda ninguna credencial almacenada.

**Acceptance Scenarios**:

1. **Given** una autorización iniciada, **When** el usuario cancela o rechaza el consentimiento
   en TikTok, **Then** AutoPublisher informa de que la conexión se canceló (`tiktok_oauth_denied`),
   no guarda credenciales y la cuenta mantiene su estado previo.
2. **Given** un callback cuyo `state` es desconocido, ya usado, pertenece a un intento sustituido
   por otro más reciente o a un intento perdido por reinicio del backend, **When** llega, **Then**
   se rechaza (`tiktok_oauth_state_invalid`) sin intercambiar ningún código ni modificar ninguna
   cuenta, y el navegador muestra una página segura que invita a iniciar de nuevo `Connect`.
3. **Given** un callback cuyo intento ha caducado, **When** llega, **Then** se rechaza
   (`tiktok_oauth_attempt_expired`) sin efectos.
4. **Given** un callback sin `code` ni `error`, con parámetros documentados duplicados, con `code`
   y `error` a la vez o con valores mal formados, **When** llega, **Then** se rechaza
   (`tiktok_oauth_callback_invalid`) sin contactar con TikTok; si el `state` era válido, el intento
   queda invalidado.
5. **Given** un callback con un error de TikTok distinto de la cancelación, **When** llega,
   **Then** se informa como error seguro del proveedor (`tiktok_oauth_provider_error`) sin mostrar
   `error_description` ni otros datos crudos de TikTok.
6. **Given** un callback válido ya procesado, **When** el navegador lo repite (recarga, atrás) o
   llega un segundo callback con el mismo `state`, **Then** no se vuelve a intercambiar el código y
   el resultado de la cuenta no cambia.
7. **Given** un callback válido, **When** el intercambio del código falla (código usado, caducado,
   PKCE rechazado, `redirect_uri` no coincidente u otro error definitivo), **Then** el usuario ve
   `tiktok_token_exchange_failed` indicando que debe iniciar una nueva autorización; no se guarda
   ninguna credencial y el código nunca se reintenta.
8. **Given** credenciales obtenidas, **When** los scopes finalmente concedidos no incluyen
   **ambos** `user.info.basic` y `video.publish`, **Then** la conexión no se completa
   (`tiktok_permission_missing`, indicando qué permiso falta), las credenciales se descartan sin
   guardarse (y se intenta revocarlas en TikTok de forma best-effort) y se explica que deben
   concederse todos los permisos solicitados mediante un nuevo `Connect`/`Reconnect`.
9. **Given** credenciales obtenidas, **When** el `open_id` de la respuesta del intercambio no
   coincide con el de la consulta oficial de identidad, o falta en alguna de ellas, **Then** la
   conexión no se completa (`tiktok_unexpected_response`) y las credenciales se descartan.
10. **Given** credenciales obtenidas, **When** TikTok no responde o no está accesible al consultar
    la identidad, **Then** la conexión no se completa, las credenciales se descartan y el usuario
    ve un error temporal (`tiktok_unavailable`) que indica que debe iniciar una nueva autorización.
11. **Given** una autorización iniciada, **When** el usuario pulsa `Cancel` en AutoPublisher,
    **Then** el intento se invalida, un callback posterior con su `state` se rechaza y la cuenta
    conserva su estado previo.
12. **Given** cualquiera de los errores anteriores, **When** se muestra o se registra en logs,
    **Then** sigue el formato estructurado de errores existente y no contiene tokens, códigos,
    `code_verifier`, `state` completo, client secret, cabeceras `Authorization`, URLs o cuerpos de
    formulario con secretos ni respuestas crudas de TikTok.

---

### User Story 3 - Mantener la credencial válida y verificar la conexión (Priority: P1)

Como usuario, quiero que AutoPublisher renueve el access token de TikTok solo cuando lo necesite,
aplicando correctamente la rotación del refresh token, que pueda verificar la conexión bajo
demanda de forma de solo lectura y que me avise claramente cuando el acceso se haya perdido
definitivamente.

**Why this priority**: el access token de TikTok es de corta duración; sin renovación fiable la
conexión deja de ser útil en horas y la Feature 013 no podría publicar.

**Independent Test**: con un fake de TikTok y un reloj controlable: un access token con vida
suficiente se usa sin renovar; uno dentro del margen de renovación o caducado, con refresh token
vigente, se renueva; una renovación que devuelve un refresh token nuevo lo sustituye y el viejo
no vuelve a usarse; una que devuelve el mismo lo conserva; un fallo temporal con access token aún
utilizable lo mantiene; un refresh token caducado o rechazado definitivamente lleva a `Reconnect
required`; `Verify connection` con identidad correcta, datos públicos cambiados, `open_id`
distinto, sin renovación (scopes conocidos mantenidos, sin afirmar comprobación en vivo de
`video.publish`) y con renovación que devuelve scopes sin `video.publish`.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` cuyo access token tiene vida restante superior al margen de
   renovación, **When** AutoPublisher necesita una credencial válida, **Then** la usa tal cual sin
   contactar con el endpoint de tokens.
2. **Given** una cuenta `Connected` cuyo access token está dentro del margen de renovación o ya ha
   caducado y cuyo refresh token sigue vigente, **When** AutoPublisher necesita una credencial
   válida, **Then** la renueva sin intervención del usuario y guarda de forma consistente el nuevo
   access token, el refresh token devuelto (nuevo o el mismo), sus caducidades derivadas de
   `expires_in` / `refresh_expires_in` y los scopes devueltos, y la cuenta sigue `Connected`.
3. **Given** una renovación que devuelve un refresh token distinto del almacenado, **When** se
   guarda correctamente, **Then** el refresh token anterior no vuelve a usarse jamás.
4. **Given** una renovación cuyo `open_id` difiere del vinculado, o cuyos scopes ya no incluyen
   ambos permisos requeridos, **When** se recibe, **Then** la cuenta pasa a `Reconnect required`
   (`tiktok_identity_mismatch` o `tiktok_reconnect_required` indicando el permiso que falta) y la
   credencial nueva no se usa para operar.
5. **Given** una cuenta cuyo refresh token ha caducado según la caducidad almacenada en el almacén
   seguro, o que TikTok rechaza definitivamente (revocado, inválido), **When** AutoPublisher
   necesita una credencial, **Then** la cuenta pasa a `Reconnect required`, conserva la identidad
   pública conocida y la interfaz muestra una explicación segura y `Reconnect`.
6. **Given** una renovación que falla por un problema transitorio (sin Internet, timeout, 5xx,
   límite temporal), **When** el access token actual sigue siendo utilizable, **Then** se conserva
   y la operación continúa con él; **When** ya no es utilizable de forma segura, **Then** la
   operación falla con `tiktok_unavailable`. En ningún caso la cuenta pasa a `Reconnect required`.
7. **Given** una cuenta `Connected` de una `Account` y un proyecto activos, **When** el usuario
   pulsa `Verify connection`, **Then** AutoPublisher obtiene una credencial válida (renovándola
   solo si procede), consulta la identidad oficial y comprueba en vivo que el access token es
   utilizable, que `user.info.basic` funciona y que el `open_id` coincide con el vinculado;
   actualiza nombre visible, avatar y caducidades si han cambiado, registra la fecha de
   verificación y muestra el resultado. Verify no crea, sube, modifica ni borra contenido en
   TikTok.
8. **Given** una verificación que no necesitó renovar, **When** se muestra el resultado, **Then**
   `video.publish` se presenta como concedido **según la última autorización o renovación de
   TikTok**, nunca como comprobado en vivo; **Given** una verificación que sí renovó y cuya lista
   de scopes ya no incluye `video.publish`, **Then** la cuenta pasa a `Reconnect required`
   (`tiktok_reconnect_required`).
9. **Given** una verificación, **When** el `open_id` devuelto es distinto del vinculado, **Then**
   NO se sustituye la identidad; la cuenta pasa a `Reconnect required` y el usuario ve
   `tiktok_identity_mismatch`.
10. **Given** una verificación o un uso de la credencial, **When** TikTok responde
   `access_token_invalid` con un access token que debería ser vigente, **Then** AutoPublisher
   intenta una única renovación; si la renovación falla definitivamente, la cuenta pasa a
   `Reconnect required`.
11. **Given** una cuenta `Connected` cuya credencial ya no existe en el almacén seguro, **When**
    AutoPublisher la necesita, **Then** la cuenta pasa a `Reconnect required` en lugar de producir
    un error interno.
12. **Given** que el almacén seguro contiene una credencial renovada más reciente que los
    metadatos de SQLite (por ejemplo, tras un fallo entre ambos pasos), **When** AutoPublisher
    accede a la cuenta, **Then** toma el almacén seguro como fuente de verdad, repara los metadatos
    no sensibles de forma idempotente y nunca vuelve al token anterior ni renueva de nuevo por
    culpa de metadatos desfasados.

---

### User Story 4 - Desconectar una cuenta TikTok con revocación oficial (Priority: P2)

Como usuario, quiero desconectar una cuenta TikTok de modo que AutoPublisher revoque su acceso en
TikTok y elimine sus credenciales locales, sin perder la `Account` ni sus publicaciones, y sin que
la aplicación me diga que se revocó algo que no pudo confirmar.

**Why this priority**: retirar el acceso de forma fiable y honesta es indispensable para manejar
credenciales reales; depende de que exista una conexión.

**Independent Test**: con fakes, desconectar una cuenta con revocación correcta, con credencial
definitivamente inválida según TikTok, con fallo temporal de TikTok, con el secreto ausente del
almacén seguro y con el almacén seguro inaccesible, y comprobar en cada caso el estado final, el
contenido del almacén seguro y el mensaje mostrado.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Disconnect` y confirma, **Then** AutoPublisher intenta la revocación oficial en TikTok con la
   credencial actual (obteniendo antes un access token utilizable si hace falta y es posible).
2. **Given** esa desconexión, **When** TikTok confirma la revocación, **Then** se elimina la
   credencial del almacén seguro, después la conexión local, la cuenta vuelve a `Not connected` y
   el usuario ve que el acceso fue **revocado en TikTok**.
3. **Given** esa desconexión, **When** la credencial es definitivamente inválida **según TikTok**
   (refresh token caducado según la caducidad oficial guardada o rechazado definitivamente, o
   TikTok confirma de forma inequívoca que el token es inválido o está revocado), **Then** se
   eliminan la credencial y la conexión locales, la cuenta vuelve a `Not connected` y el usuario
   ve que la credencial **ya no era válida en TikTok** y que se ha eliminado localmente, sin
   afirmar que AutoPublisher ejecutó una revocación.
4. **Given** esa desconexión, **When** la revocación falla por un problema transitorio, la
   respuesta es ambigua o la configuración local de TikTok falta, **Then** NO se elimina nada: la
   conexión y su credencial se conservan, el usuario ve `tiktok_revoke_failed` explicando que no
   se pudo confirmar la revocación y puede reintentar `Disconnect` más tarde.
5. **Given** ese fallo, **When** el usuario elige explícitamente la opción separada `Remove
   locally without revoking` y la confirma tras una advertencia clara, **Then** se eliminan la
   credencial y la conexión locales, la cuenta vuelve a `Not connected` y el mensaje indica que el
   acceso **no** se ha revocado en TikTok y cómo retirarlo manualmente desde *Manage app
   permissions* en TikTok.
6. **Given** cualquier desconexión, **When** termina, **Then** la `Account` conserva plataforma,
   handle, nombre visible y estado activo/inactivo, y sus publicaciones no cambian.
7. **Given** una cuenta conectada inactiva o de un proyecto inactivo, **When** el usuario la
   desconecta, **Then** se permite igual que en una cuenta activa, incluida la renovación previa
   estrictamente necesaria para poder revocar.
8. **Given** una cuenta ya `Not connected`, **When** se solicita desconectarla, **Then** la
   operación es idempotente.
9. **Given** una cuenta conectada cuyo secreto **falta** en el almacén seguro (el almacén está
   accesible pero no contiene la credencial referenciada), **When** el usuario pulsa
   `Disconnect`, **Then** no se contacta con TikTok ni se elimina nada automáticamente; el usuario
   ve `tiktok_credential_missing`, que explica que no puede confirmarse la revocación remota y que
   la autorización en TikTok **puede seguir existiendo**, y se le ofrece la acción explícita
   `Remove locally without revoking` con la misma advertencia e indicaciones para retirarla
   manualmente desde *Manage app permissions*. En ningún caso se afirma que TikTok quedó revocado
   ni que la credencial era inválida en TikTok.
10. **Given** una cuenta conectada y el almacén seguro inaccesible o fallando, **When** se
    solicita desconectarla (o eliminarla localmente), **Then** falla con
    `credential_store_unavailable`, sin contactar con TikTok, la conexión se conserva sin
    modificaciones y no se informa de una desconexión que no ha ocurrido.

---

### User Story 5 - Reconectar de forma segura y proteger contra la cuenta equivocada (Priority: P2)

Como usuario, quiero poder volver a autorizar una cuenta conectada o que requiere reconexión, de
modo que la nueva credencial sustituya a la anterior de forma segura y AutoPublisher nunca cambie
en silencio la cuenta de TikTok vinculada por otra distinta.

**Why this priority**: la reconexión es el camino de recuperación de `Reconnect required` (refresh
token caducado, permiso retirado, revocación externa) y la protección frente a la cuenta
equivocada evita publicar donde no se desea.

**Independent Test**: con fakes, reconectar con la misma cuenta y comprobar el orden "nuevo
secreto → commit → borrar el viejo"; inyectar un fallo de SQLite y comprobar que la conexión
anterior queda intacta y el secreto nuevo se elimina; inyectar un fallo al borrar el secreto
viejo y comprobar que la nueva conexión sigue válida; reconectar con otro `open_id` y comprobar
que nada cambia sin confirmación explícita.

**Acceptance Scenarios**:

1. **Given** una cuenta `Not connected`, **When** el usuario completa `Connect TikTok`, **Then** la
   cuenta pasa a `Connected` sin paso extra de confirmación.
2. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa `Reconnect`
   y autoriza la **misma** cuenta (mismo `open_id`) con ambos permisos, **Then** la nueva
   credencial se guarda bajo una referencia opaca **nueva**, se confirma la conexión local y solo
   después se elimina la credencial anterior; la información pública se actualiza y la cuenta
   queda `Connected`.
3. **Given** una reconexión, **When** falla la actualización de la conexión local tras guardar la
   credencial nueva, **Then** se elimina la credencial nueva y la conexión anterior queda
   exactamente como estaba.
4. **Given** una reconexión confirmada localmente, **When** falla la eliminación de la credencial
   anterior, **Then** la nueva conexión sigue siendo válida y utilizable, la credencial anterior
   queda registrada como huérfana pendiente de limpieza segura y nunca vuelve a usarse.
5. **Given** una cuenta con identidad vinculada, **When** la nueva autorización devuelve un
   `open_id` **distinto**, **Then** no se modifica la conexión existente; el usuario ve una
   advertencia con la cuenta actual y la nueva (nombre visible y avatar de ambas, y un
   identificador no sensible abreviado) y debe elegir explícitamente entre sustituir o cancelar.
6. **Given** esa advertencia, **When** el usuario confirma, **Then** la `Account` queda vinculada a
   la nueva cuenta de TikTok siguiendo el mismo orden seguro de sustitución.
7. **Given** esa advertencia, **When** el usuario cancela o no responde dentro del tiempo de
   validez del intento, **Then** la nueva credencial se descarta sin haberse guardado (con intento
   best-effort de revocarla en TikTok) y la conexión anterior queda exactamente como estaba.

---

### User Story 6 - Evitar la misma cuenta TikTok en dos Accounts del proyecto (Priority: P2)

Como usuario, quiero que AutoPublisher me impida vincular la misma cuenta real de TikTok a dos
`Account` distintas del mismo proyecto, para no duplicar publicaciones en el futuro.

**Why this priority**: protege la integridad de futuras publicaciones; depende de la conexión
básica.

**Independent Test**: con fakes, conectar una cuenta al `open_id` `oid-A`, intentar conectar otra
cuenta TikTok del mismo proyecto devolviendo `oid-A` y comprobar que se rechaza indicando qué
`Account` la tiene, sin guardar credenciales para la segunda; repetir en otro proyecto y
comprobar que se permite.

**Acceptance Scenarios**:

1. **Given** una `Account` del proyecto (activa o inactiva) vinculada a `oid-A`, **When** otra
   `Account` del mismo proyecto completa una autorización que devuelve `oid-A`, **Then** se
   rechaza (`tiktok_account_already_connected`), la nueva credencial se descarta y el usuario ve
   qué `Account` la tiene y que debe desconectarla primero.
2. **Given** `oid-A` vinculada en el proyecto A, **When** una `Account` del proyecto B la conecta,
   **Then** se permite.
3. **Given** `oid-A` vinculada a una `Account` que después se desconecta, **When** otra `Account`
   del mismo proyecto la conecta, **Then** se permite.
4. **Given** dos completados simultáneos que devuelven `oid-A` para dos `Account` del mismo
   proyecto, **When** ambos intentan completarse, **Then** como máximo uno se completa.
5. **Given** cuentas de YouTube, Instagram o Threads vinculadas en el mismo proyecto, **When** se
   evalúa la unicidad de TikTok, **Then** solo se comparan `open_id` de TikTok; las identidades de
   otras plataformas nunca se mezclan.

---

### User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

Como usuario, quiero que una cuenta inactiva o de un proyecto inactivo muestre su estado de
conexión pero no permita nuevas autorizaciones ni operaciones activas contra TikTok (incluida
`Verify connection`), aunque sí desconectarla.

**Why this priority**: regla de coherencia sobre flujos ya cubiertos, alineada con la Feature 010.

**Independent Test**: desactivar una cuenta conectada y comprobar que muestra identidad y estado,
que `Connect`/`Reconnect`/`Verify connection`/completar un callback/confirmar un cambio de cuenta
se rechazan si se fuerzan y que `Disconnect` funciona; repetir con el proyecto desactivado.

**Acceptance Scenarios**:

1. **Given** una cuenta TikTok inactiva, o activa de un proyecto inactivo, **When** el usuario la
   consulta, **Then** ve su estado de conexión y la identidad vinculada si la hay.
2. **Given** esa cuenta, **When** se intenta `Connect`, `Reconnect` o `Verify connection`, **Then**
   la acción no está disponible en la interfaz y, si se fuerza, se rechaza (`account_inactive` /
   `project_inactive`) sin contactar con TikTok ni tocar el almacén seguro.
3. **Given** una autorización iniciada con cuenta y proyecto activos, **When** la cuenta o el
   proyecto se desactivan antes de que llegue el callback o de confirmar un cambio de cuenta,
   **Then** el callback o la confirmación se rechazan sin intercambiar el código (o descartando la
   credencial ya obtenida), no se guardan credenciales y la cuenta mantiene su estado previo.
4. **Given** una cuenta conectada, **When** ella o su proyecto se desactivan, **Then** su conexión
   NO se elimina ni se revoca.

---

### Edge Cases

- **Configuración de TikTok ausente o incompleta**: `Connect`/`Reconnect` devuelven
  `tiktok_oauth_not_configured`; las cuentas conectadas siguen mostrando su estado; `Verify` y la
  renovación fallan de forma segura sin cambiar el estado; `Disconnect` no puede revocar y ofrece
  la eliminación local explícita (US4-5).
- **Configuración de otras plataformas presente pero no la de TikTok (o al revés)**: cada
  integración se evalúa por separado.
- **Redirect URI local rechazado por el dashboard de TikTok, o puerto/host del callback distinto
  del registrado**: el quickstart lo valida al principio; si TikTok no lo acepta, se detiene la
  validación y se revisa la decisión (no se usan túneles, dominios de terceros ni URLs inventadas).
- **Backend escuchando en un puerto distinto del configurado para el callback**: `Connect` lo
  detecta o la documentación lo explica; nunca se genera una URL de autorización con un redirect
  URI que no coincida con el registrado.
- **Peticiones al callback que no proceden del flujo** (sin `state`, `state` inventado, otra
  ruta, otro host): se rechazan sin efectos; no se interpreta ningún parámetro fuera de la ruta y
  el host de loopback registrados.
- **Parámetros no documentados en el callback**: no se interpretan ni se registran sus valores.
- **Codificación del `code_challenge`**: si la codificación real aceptada por TikTok contradice la
  implementada, se detiene la validación y se corrige primero la especificación/plan.
- **Concesión parcial de scopes** (solo `user.info.basic` o solo `video.publish`): nunca
  `Connected`; error recuperable y `Reconnect`/`Connect` disponible.
- **Scopes en el callback distintos de los de la respuesta de tokens**: manda la respuesta del
  intercambio de tokens; si no incluye ambos, no se conecta.
- **Varios intentos para la misma cuenta**: solo el más reciente puede completarse; los anteriores
  se invalidan al iniciar uno nuevo.
- **Pestañas o ventanas de autorización abandonadas**: el intento caduca y la cuenta conserva su
  estado; la interfaz sale de `Connecting`.
- **Reinicio del backend durante la autorización**: el intento (incluido el `code_verifier`) se
  pierde; el callback posterior se rechaza y el usuario reinicia `Connect`.
- **Access token caducado mientras AutoPublisher estaba apagado, con refresh token vigente**: se
  renueva en el siguiente uso sin intervención.
- **Refresh token caducado mientras AutoPublisher estaba apagado (≈ 1 año sin uso)**: la cuenta pasa
  a `Reconnect required` en el siguiente acceso.
- **Secreto ausente del almacén seguro** (borrado externo del keyring, cambio de equipo o de
  usuario del sistema): la cuenta pasa a `Reconnect required` al usarse; `Disconnect` no puede
  revocar ni afirma revocación, devuelve `tiktok_credential_missing` y ofrece `Remove locally
  without revoking` advirtiendo que el permiso remoto puede seguir existiendo.
- **Almacén seguro inaccesible o fallando**: distinto del secreto ausente; toda operación que lo
  necesite devuelve `credential_store_unavailable` sin modificar la conexión.
- **Revocación externa desde *Manage app permissions* de TikTok**: AutoPublisher no recibe aviso
  (es local); lo detecta en el siguiente uso, renovación o Verify y pasa a `Reconnect required`.
- **Fallo entre guardar una credencial renovada y actualizar SQLite**: el almacén seguro es
  autoritativo; los metadatos se reparan en el siguiente acceso.
- **Renovaciones concurrentes de la misma cuenta** (p. ej. Verify y una futura publicación a la
  vez): solo se produce una; la otra usa su resultado, de modo que nunca se envía un refresh token
  ya rotado.
- **Avatar o nombre visible no disponibles**: no es un error; se muestra un marcador neutro.
- **Cambio de nombre visible o avatar en TikTok**: no rompe la conexión; se actualiza al verificar
  o reconectar.
- **URLs de avatar de TikTok con caducidad**: se tratan como información pública cambiante; una
  imagen rota no es un error de conexión.
- **Handle de la `Account` distinto de la identidad real**: no bloquea ni modifica la `Account`
  (TikTok no proporciona `username` con `user.info.basic`); la interfaz muestra el nombre visible
  real junto al handle local.
- **Límite de peticiones o error temporal de TikTok**: error temporal; no cambia el estado.
- **Respuesta de TikTok inesperada o incompleta** (sin `open_id`, sin `expires_in`, sin
  `refresh_token`, `token_type` distinto de `Bearer`): la operación falla con
  `tiktok_unexpected_response`, sin datos crudos ni cambios indebidos.
- **Usuario no añadido como target user del Sandbox**: TikTok puede rechazar el flujo en su
  propia página o devolver un error; en el segundo caso se trata como
  `tiktok_oauth_provider_error`. La documentación explica cómo añadir el target user.
- **Cuentas de otras plataformas o `Account` inexistente**: error de plataforma no soportada o de
  cuenta no encontrada.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance y vinculación con Accounts

- **FR-001**: El sistema DEBE permitir vincular una `Account` existente de plataforma TikTok con
  una cuenta real de TikTok mediante la autorización oficial de TikTok Login Kit (OAuth v2) en el
  navegador del usuario, sin crear un sistema de cuentas paralelo.
- **FR-002**: El sistema DEBE rechazar cualquier operación de conexión, reconexión, verificación
  o desconexión de TikTok sobre una `Account` inexistente o cuya plataforma no sea TikTok, con un
  error estructurado comprensible.
- **FR-003**: Cada `Account` TikTok DEBE tener como máximo una conexión, vinculada a una única
  cuenta de TikTok.
- **FR-004**: El modelo común de `Account`, su esquema, el núcleo común de Accounts, el scheduler y
  el núcleo de publishing NO DEBEN incluir campos, dependencias ni lógica específica de TikTok. La
  información de conexión DEBE vivir en módulos aislados de TikTok. DEBE existir un test de
  arquitectura que lo garantice, como para YouTube, Instagram y Threads.
- **FR-005**: La integración de TikTok DEBE ser independiente de YouTube, Instagram y Threads:
  configuración, credenciales, conexión y espacio de nombres propios en el almacén seguro. PUEDE
  reutilizar utilidades genéricas existentes (almacén seguro, formato de errores, redacción de
  logs, patrones de intentos pendientes) sin introducir dependencias cruzadas entre plataformas.
- **FR-006**: Esta feature NO DEBE registrar un publisher de TikTok ni crear, subir, modificar o
  borrar contenido en TikTok, ni consultar `creator_info` u otras operaciones de Content Posting.

#### Permisos

- **FR-007**: El sistema DEBE solicitar únicamente `user.info.basic` y `video.publish`. NO DEBE
  solicitar `video.upload`, `video.list`, `user.info.profile`, `user.info.stats` ni ningún otro.
- **FR-008**: La conexión solo DEBE completarse si la lista de scopes devuelta por el intercambio
  oficial de tokens incluye **ambos** permisos requeridos. Los `scopes` del callback son
  informativos y no bastan por sí solos. Si falta alguno, la conexión NO DEBE completarse
  (`tiktok_permission_missing`, indicando el permiso que falta), las credenciales NO DEBEN
  guardarse y NO DEBE degradarse la conexión a un solo permiso.
- **FR-009**: TikTok no ofrece inspección independiente de tokens ni de scopes. Por tanto:
  - **Scopes conocidos**: el conjunto autorizado DEBE ser la lista devuelta por la última
    respuesta oficial correcta de intercambio de código o de renovación, almacenada junto a la
    credencial. Mientras no haya una respuesta posterior que lo contradiga, `video.publish` se
    considera concedido **según esa última respuesta oficial**, no por una comprobación en vivo.
  - **Señales que invalidan los scopes conocidos**: una renovación cuya lista no incluya ambos
    permisos, o un error oficial de la API que indique permiso no autorizado
    (`scope_not_authorized` o equivalente) para un permiso requerido —por ejemplo, en la Feature
    013 al usar `video.publish`— DEBEN llevar a `Reconnect required`.
  - NO DEBE inventarse un mecanismo de inspección inexistente, ni añadirse en esta feature
    ninguna llamada de publishing, Content Posting o `creator_info` con el único fin de comprobar
    `video.publish`. El plan DEBE documentar esta fuente en `research.md`.

#### Estados de conexión

- **FR-010**: Una `Account` TikTok DEBE encontrarse en uno de estos estados: `Not connected` (sin
  conexión ni credencial usable), `Connected` (identidad persistida y credencial segura usable con
  ambos permisos) o `Reconnect required` (identidad conocida conservada, pero la credencial ya no
  permite operar de forma segura). `Connecting` es un estado transitorio de interfaz asociado a un
  intento pendiente y NO se persiste.
- **FR-011**: Estos estados NO DEBEN aplicarse a cuentas de otras plataformas y DEBEN ser
  independientes del estado activo/inactivo de la cuenta y del proyecto.
- **FR-012**: Solo DEBE pasarse a `Reconnect required` ante evidencia definitiva: refresh token
  caducado según la caducidad guardada en el almacén seguro, refresh token rechazado
  definitivamente por TikTok, credencial ausente del almacén seguro, permiso requerido ausente en
  una respuesta oficial, `open_id` distinto del vinculado u otro error de autenticación o
  autorización definitivo documentado por TikTok. Errores de red, timeouts, respuestas 5xx y
  límites temporales NUNCA DEBEN provocarlo. Una credencial **ausente** del almacén seguro hace
  la conexión inutilizable y justifica `Reconnect required`, pero NO es evidencia de que la
  autorización remota haya sido revocada ni de que la credencial sea inválida en TikTok; se trata
  de forma distinta en `Disconnect` (FR-046). Un almacén seguro inaccesible o fallando NO es
  credencial ausente: produce `credential_store_unavailable` sin cambiar el estado.

#### Flujo de autorización y PKCE

- **FR-013**: Cada autorización iniciada DEBE asociarse a una `Account` concreta y generar un
  `state` criptográficamente seguro y un `code_verifier` criptográficamente seguro, ambos nuevos,
  de un solo uso y con caducidad corta definida en el plan. El `code_verifier` DEBE cumplir el
  formato oficial (43–128 caracteres del conjunto permitido) y el `code_challenge` DEBE derivarse
  con `S256` en la codificación que exija TikTok Desktop, confirmada por el plan y validada por el
  quickstart.
- **FR-014**: Para cada `Account` solo DEBE poder completarse el intento más reciente; iniciar uno
  nuevo invalida los anteriores. Los intentos DEBEN poder cancelarse y DEBEN invalidarse tras
  éxito o fallo definitivo.
- **FR-015**: Los intentos pendientes DEBEN ser efímeros y mantenerse solo en memoria. `state`,
  `code_verifier`, código y tokens temporales NUNCA DEBEN persistirse en la base de datos,
  archivos ni almacenamiento del navegador. Un reinicio del backend invalida los intentos en
  curso.
- **FR-016**: La autorización DEBE completarse automáticamente mediante un callback HTTP local
  servido por el backend en un redirect URI de loopback conforme a las reglas de Desktop (host
  `127.0.0.1` o `localhost`, puerto explícito o comodín registrado, ruta estática). El usuario NO
  DEBE copiar ni pegar URLs. El plan DEBE elegir el host, la ruta y la estrategia de puerto
  (puerto fijo frente a puerto comodín) a partir del puerto real/configurable del backend; el
  `redirect_uri` enviado a TikTok y en el intercambio DEBE ser idéntico.
- **FR-017**: El callback DEBE: atenderse solo en la ruta y el host de loopback configurados;
  validar el `state` por igualdad exacta contra un intento vigente de la `Account`; interpretar
  únicamente los parámetros documentados (`code`, `scopes`, `state`, `error`,
  `error_description`); rechazar parámetros documentados duplicados, combinaciones contradictorias
  (`code` y `error`) y ausencia de `code` y `error`; marcar el intento como consumido **antes** de
  intercambiar el código, de modo que un segundo callback con el mismo `state` no intercambie
  nada; y tratar `error`/`error_description` como datos no confiables que nunca se reflejan al
  navegador ni a la interfaz.
- **FR-018**: Tras consumir los parámetros de la URL entrante del callback (FR-031), el navegador
  DEBE terminar en una página local mínima y segura o en una ruta limpia de la interfaz de
  AutoPublisher que indique el resultado mediante un mensaje genérico, sin `code`, `state`,
  tokens, `code_verifier` ni texto crudo de TikTok en la URL ni en el contenido.
- **FR-019**: La interfaz DEBE poder conocer el resultado de un intento (pendiente, completado,
  fallido con código de error seguro, pendiente de confirmación de cambio de cuenta, cancelado,
  caducado) sin acceder a ningún secreto, mediante el mecanismo que defina el plan (por ejemplo,
  consulta periódica de un estado no sensible).
- **FR-020**: Tras un callback válido, el sistema DEBE, en el backend: intercambiar el código una
  sola vez, sin reintentos, enviando `code_verifier` y el `redirect_uri` idéntico en un cuerpo
  `application/x-www-form-urlencoded`; comprobar los scopes (FR-008); consultar la identidad
  oficial con `user.info.basic`; comprobar que el `open_id` es coherente entre el intercambio y la
  identidad; y solo entonces completar la vinculación.
- **FR-021**: En las peticiones que AutoPublisher envía a TikTok, client secret, código,
  `code_verifier` y tokens NUNCA DEBEN enviarse en query strings; solo en cuerpos de formulario o
  cabeceras según el contrato oficial. (La presencia de `code` y `state` en la URL entrante del
  callback la impone TikTok y se rige por FR-031.)
- **FR-022**: Ninguna autorización fallida, cancelada, rechazada, parcial o incompleta DEBE
  modificar el estado de conexión previo de la `Account` ni dejar credenciales almacenadas. Si se
  obtuvo una credencial que se descarta, el sistema DEBERÍA intentar revocarla en TikTok de forma
  best-effort sin afectar al resultado mostrado.
- **FR-023**: El sistema DEBE rechazar iniciar una conexión o reconexión, completar un callback,
  confirmar un cambio de cuenta y `Verify connection` cuando la `Account` o su proyecto estén
  inactivos, sin contactar con TikTok. Con entidades inactivas solo se permiten consultar el
  estado, cancelar un intento pendiente y `Disconnect` (incluida la renovación previa
  estrictamente necesaria para revocar), alineado con la Feature 010.

#### Identidad

- **FR-024**: El `open_id` de TikTok DEBE ser la identidad autoritativa de la cuenta vinculada; el
  sistema NUNCA DEBE identificar la cuenta por nombre visible ni por handle.
- **FR-025**: Al completar una conexión, el sistema DEBE persistir únicamente información no
  sensible: `open_id`, nombre visible y URL de avatar si están disponibles (solo campos de
  `user.info.basic`; el plan decide si `union_id` aporta valor real), fechas de conexión y de
  última verificación, caducidad del access token y caducidad del refresh token como metadatos
  informativos, estado y referencia opaca a la credencial.
- **FR-026**: La conexión NO DEBE modificar el handle ni el nombre visible de la `Account`.

#### Protección contra la cuenta equivocada y duplicados

- **FR-027**: Si una `Account` con identidad vinculada completa una autorización con un `open_id`
  distinto, el sistema NO DEBE sustituir la conexión: DEBE mostrar ambas cuentas y requerir
  confirmación explícita. Si el usuario cancela o no confirma dentro del tiempo de validez del
  intento, la nueva credencial DEBE descartarse sin persistirse y la conexión anterior DEBE quedar
  intacta.
- **FR-028**: Dentro de un mismo proyecto, un mismo `open_id` NO DEBE estar vinculado a la vez a
  dos `Account` distintas, activas o inactivas. La regla DEBE estar respaldada por la capa de
  persistencia y resistir operaciones concurrentes; una violación DEBE rechazarse con
  `tiktok_account_already_connected` indicando qué `Account` la tiene.
- **FR-029**: El mismo `open_id` PUEDE vincularse a `Account` de proyectos distintos. La unicidad
  de TikTok es independiente de la de YouTube, Instagram y Threads.

#### Credenciales y configuración

- **FR-030**: Access token, refresh token, sus caducidades y los scopes concedidos DEBEN
  almacenarse exclusivamente en el almacén seguro del sistema operativo, reutilizando la
  infraestructura existente con un espacio de nombres propio de TikTok. El almacén seguro es la
  **fuente de verdad** de la credencial. La base de datos SOLO PUEDE contener la referencia opaca
  (`credential_ref`), información pública, estado y timestamps informativos.
- **FR-031**: Client secret, access token, refresh token, código de autorización,
  `code_verifier`, `state` completo, cabeceras `Authorization`, URLs, cuerpos de formulario y
  respuestas crudas de TikTok con secretos NUNCA DEBEN aparecer en la base de datos, archivos
  versionados, logs, mensajes de error, excepciones, respuestas de la API, URLs finales del
  navegador, `localStorage` ni `sessionStorage`. Presencia en URLs:
  - Client secret, access token, refresh token y `code_verifier` NUNCA DEBEN aparecer en ninguna
    URL.
  - `state` y `code_challenge` PUEDEN aparecer en la URL de autorización devuelta para abrir
    TikTok (única respuesta de la API que puede contenerlos).
  - `code`, `state` (y, en su caso, `scopes`, `error`, `error_description`) aparecen
    necesariamente en la query string de la **URL entrante del callback**, porque así lo exige el
    protocolo de TikTok. Esa URL entrante completa NUNCA DEBE persistirse, registrarse en logs
    (incluidos los access logs del servidor), devolverse mediante la API al frontend ni guardarse
    en el almacenamiento del navegador por AutoPublisher. El backend DEBE consumir sus parámetros
    de inmediato y responder con una redirección o página local limpia sin `code`, `state`,
    tokens ni texto crudo del proveedor (FR-018).
- **FR-032**: Si el almacén seguro no está disponible, es inseguro o falla, el sistema DEBE
  abortar con `credential_store_unavailable` sin recurrir a almacenamiento alternativo.
- **FR-033**: En una primera conexión, la conexión DEBE registrarse en la base de datos solo si la
  credencial se ha guardado correctamente; si el registro falla, el sistema DEBE eliminar de
  inmediato la credencial recién guardada. Nunca queda una conexión parcial.
- **FR-034**: Toda sustitución de credencial por una nueva autorización (Reconnect o cambio de
  cuenta confirmado) DEBE seguir este orden: guardar la nueva credencial bajo una
  `credential_ref` **nueva** → confirmar la conexión local → solo entonces eliminar la credencial
  anterior. Si la confirmación local falla, se elimina la nueva y la anterior queda intacta. Si la
  eliminación de la anterior falla tras la confirmación, la nueva conexión se mantiene válida y la
  referencia anterior queda registrada para una limpieza posterior segura e idempotente; nunca se
  revierte a la credencial anterior.
- **FR-035**: La configuración de la aplicación TikTok (client key, client secret y los datos de
  callback necesarios) DEBE cargarse desde configuración local propia de TikTok, separada de la de
  otras plataformas, fuera de Git y de la base de datos, cubierta por `.gitignore`. El client
  secret NUNCA DEBE enviarse al frontend. El estado de conexión PUEDE indicar, sin datos
  sensibles, si la configuración está disponible.
- **FR-036**: DEBE existir documentación que explique cómo crear la app en TikTok for Developers,
  crear un Sandbox, añadir Login Kit (Desktop) y Content Posting API con Direct Post solo para
  disponer de `video.publish`, registrar el redirect URI local, añadir la cuenta propia como target
  user y preparar la configuración local sin secretos en el repositorio. NO DEBEN inventarse
  sitios web, URLs de Privacy Policy/Terms, dominios ni ninguna otra URL para superar
  validaciones. Durante el Gate G, TikTok for Developers exigió completar *Basic information*
  (incluidas Terms of Service URL, Privacy Policy URL y Web/Desktop URL). AutoPublisher dispone
  ahora de documentos reales y versionados, que describen su comportamiento verdadero y no son
  placeholders ni información ficticia: `docs/privacy-policy.md` y `docs/terms-of-service.md`
  (Web/Desktop URL: el repositorio público del proyecto). La documentación de configuración DEBE
  remitir a ellos y mantenerlos veraces si cambia el tratamiento de datos.

#### Ciclo de vida de la credencial

- **FR-037**: El sistema DEBE ofrecer una capacidad interna, reutilizable por la Feature 013, para
  obtener una credencial válida de una `Account` conectada, renovándola on-demand según esta
  política: si al access token le queda más vida que el margen de renovación, se usa; si está
  dentro del margen o caducado y el refresh token sigue vigente, se renueva; si la renovación
  falla temporalmente y el access token sigue siendo utilizable, se conserva; si ya no es
  utilizable, la operación falla con `tiktok_unavailable`; si el refresh token ha caducado o es
  rechazado definitivamente, `Reconnect required`. El margen de renovación DEBE ser conservador y
  lo fija el plan.
- **FR-038**: Las caducidades DEBEN derivarse exclusivamente de `expires_in` y
  `refresh_expires_in` devueltos por TikTok en el momento de recibirlos; las duraciones
  documentadas (24 h, 365 días) NO DEBEN codificarse como fuente de verdad.
- **FR-039**: Tras una renovación correcta, access token, refresh token devuelto, ambas caducidades
  y scopes DEBEN sustituirse juntos y de forma consistente en el almacén seguro. Si el refresh
  token devuelto es distinto, el anterior NO DEBE volver a usarse. Toda renovación DEBE validar que
  el `open_id` devuelto coincide con el vinculado y que los scopes siguen incluyendo ambos
  permisos; en caso contrario se aplica FR-012.
- **FR-040**: El orden entre almacén seguro y base de datos en la renovación DEBE ser crash-safe
  con las mismas garantías que la Feature 010: guardada la credencial renovada en el almacén
  seguro, un fallo posterior al actualizar los metadatos no sensibles NO DEBE provocar pérdida de
  la credencial, vuelta al token anterior ni una renovación adicional; los metadatos se reparan de
  forma idempotente en el siguiente acceso tomando el almacén seguro como fuente de verdad.
- **FR-041**: Renovaciones concurrentes de la misma cuenta NO DEBEN producirse.
- **FR-042**: Esta feature NO DEBE introducir renovación periódica en segundo plano ni lógica de
  TikTok en el scheduler. La renovación ocurre solo cuando AutoPublisher necesita la credencial
  (Verify, `Disconnect` para poder revocar y, en la Feature 013, publicar).

#### Verificación

- **FR-043**: El usuario DEBE poder ejecutar `Verify connection` sobre una `Account` `Connected`
  con `Account` y proyecto activos. La operación DEBE ser de solo lectura respecto a TikTok y DEBE:
  obtener una credencial válida (renovando solo si procede), consultar la identidad oficial,
  comprobar que el `open_id` coincide con el vinculado, actualizar nombre visible, avatar y
  caducidades si han cambiado y registrar la fecha de verificación. Verify distingue:
  - **Señales vivas** (confirmadas en esa ejecución): access token utilizable, consulta de
    identidad correcta, `open_id` coincidente y `user.info.basic` funcional.
  - **Scopes conocidos** (FR-009): si Verify no necesitó renovar, `video.publish` se mantiene como
    concedido según la última respuesta oficial de tokens; si renovó, se evalúa la lista devuelta
    por esa renovación, y si no incluye ambos permisos se aplica FR-044.
  La interfaz, los mensajes y la documentación NO DEBEN presentar `video.publish` como
  comprobado en vivo cuando solo procede de la última respuesta de tokens (p. ej. "Permisos
  según la última autorización/renovación de TikTok").
- **FR-044**: Si la verificación detecta un permiso requerido ausente (en la lista de una
  renovación realizada durante Verify o mediante un error oficial de permiso), DEBE fallar con
  `tiktok_reconnect_required` y pasar a `Reconnect required`; si detecta un `open_id` distinto,
  NO DEBE reemplazar la identidad: DEBE devolver `tiktok_identity_mismatch` y pasar a `Reconnect
  required`. La clasificación de respuestas de TikTok como temporal, definitiva o de permisos
  corresponde a la capa de integración con TikTok.
- **FR-045**: El sistema DEBE exponer internamente, para la Feature 013, servicios claros para
  obtener una credencial válida y la identidad (`open_id`) vinculada de una `Account` conectada.

#### Desconexión y reconexión

- **FR-046**: El usuario DEBE poder ejecutar `Disconnect` sobre una `Account` `Connected` o
  `Reconnect required`, también si la cuenta o el proyecto están inactivos. `Disconnect` DEBE
  intentar primero la revocación oficial con el access token actual (renovándolo antes si es
  necesario y posible) y distinguir estos resultados:
  - **Revocación confirmada**: eliminar la credencial del almacén seguro, después la conexión
    local, y comunicar que el acceso fue revocado en TikTok.
  - **Credencial definitivamente inválida según TikTok** (refresh token caducado según la
    caducidad oficial guardada o rechazado definitivamente, o TikTok confirma token inválido o
    revocado): eliminar credencial y conexión locales y comunicar que la credencial ya no era
    válida en TikTok, sin afirmar que AutoPublisher ejecutó una revocación.
  - **Fallo temporal, respuesta ambigua o configuración ausente**: NO eliminar nada, conservar
    conexión y credencial y devolver `tiktok_revoke_failed` para que el usuario pueda reintentar.
  - **Secreto ausente del almacén seguro** (almacén accesible, credencial referenciada
    inexistente): NO contactar con TikTok ni eliminar nada automáticamente; devolver
    `tiktok_credential_missing` indicando que la revocación remota no puede confirmarse y que la
    autorización en TikTok puede seguir existiendo. NO DEBE afirmarse revocación ni invalidez
    remota.
  - **Almacén seguro inaccesible o fallando**: devolver `credential_store_unavailable` sin
    contactar con TikTok y sin modificar la conexión.
- **FR-047**: Tras `tiktok_revoke_failed` o `tiktok_credential_missing`, el usuario DEBE poder
  elegir explícitamente, como acción separada con confirmación y advertencia clara, `Remove
  locally without revoking`, que elimina la credencial local (si existe) y la conexión local e
  informa de que el acceso NO se ha revocado en TikTok, de que el permiso remoto puede seguir
  existiendo y de cómo retirarlo manualmente desde *Manage app permissions*. El sistema NUNCA
  DEBE eliminar silenciosamente la única credencial necesaria para reintentar la revocación.
- **FR-048**: La desconexión NO DEBE modificar ni borrar la `Account` ni sus publicaciones y DEBE
  ser idempotente. Si el almacén seguro está inaccesible o falla, tanto `Disconnect` como `Remove
  locally without revoking` DEBEN fallar con `credential_store_unavailable` y conservar la
  conexión sin cambios.
- **FR-049**: El usuario DEBE poder iniciar de nuevo la autorización sobre una `Account`
  `Not connected`, `Connected` o `Reconnect required` (con cuenta y proyecto activos). Con la misma
  cuenta de TikTok, la nueva credencial DEBE sustituir a la anterior según FR-034.
- **FR-050**: Desactivar una `Account` o un proyecto NO DEBE desconectar ni revocar TikTok.

#### API, errores e interfaz

- **FR-051**: La API DEBE ofrecer endpoints específicos de TikTok para: consultar el estado de
  conexión y la identidad pública, iniciar conexión o reconexión, recibir el callback OAuth,
  consultar el estado no sensible de un intento, cancelar un intento, confirmar o cancelar un
  cambio de cuenta, verificar, desconectar con revocación y eliminar localmente sin revocar.
  Ninguna respuesta DEBE incluir credenciales.
- **FR-052**: Los errores DEBEN seguir el formato estructurado existente con códigos estables y
  seguros propios de TikTok, distinguiendo al menos: `tiktok_oauth_not_configured`,
  `tiktok_oauth_denied`, `tiktok_oauth_provider_error`, `tiktok_oauth_callback_invalid`,
  `tiktok_oauth_state_invalid`, `tiktok_oauth_attempt_expired`, `tiktok_oauth_attempt_not_found`,
  `tiktok_oauth_attempt_not_confirmable`, `tiktok_connection_changed`,
  `tiktok_token_exchange_failed`, `tiktok_permission_missing`, `tiktok_reconnect_required`,
  `tiktok_identity_mismatch`, `tiktok_account_already_connected`, `tiktok_not_connected`,
  `tiktok_revoke_failed`, `tiktok_credential_missing`, `tiktok_unavailable` (temporal), `tiktok_unexpected_response`,
  `credential_store_unavailable`, cuenta inexistente, plataforma no soportada, `account_inactive`
  y `project_inactive`. Los nombres exactos pueden ajustarse en el plan manteniendo el prefijo
  `tiktok_`.
- **FR-053**: Para una `Account` TikTok, la interfaz DEBE mostrar un panel mínimo específico: en
  `Not connected`, `Connect TikTok`; en `Connecting`, un estado claro, el enlace para reabrir la
  autorización y `Cancel`, esperando el resultado del callback; si procede, la advertencia de
  cambio de cuenta con sus dos opciones; en `Connected`, nombre visible y avatar si existen,
  estado, caducidad del access token, caducidad de la autorización renovable, fecha de última
  verificación, `Verify connection`, `Reconnect` y `Disconnect`; en `Reconnect required`, una
  explicación segura, `Reconnect` y `Disconnect`; tras `tiktok_revoke_failed`, `Retry` y
  `Remove locally without revoking`; tras `tiktok_credential_missing`, la explicación de que la
  autorización remota puede seguir existiendo y `Remove locally without revoking`. Los permisos solo se muestran de forma comprensible cuando
  aporten información útil (p. ej. cuál falta) y sin sugerir una comprobación en vivo inexistente
  de `video.publish` (FR-043). Las acciones DEBEN respetar las reglas de
  entidades inactivas.
- **FR-054**: El panel de TikTok NO DEBE mostrarse en cuentas de otras plataformas, los
  componentes genéricos NO DEBEN contener lógica de TikTok salvo puntos de extensión neutrales y
  esta feature NO DEBE rediseñar la interfaz existente.
- **FR-055**: La información no sensible de la conexión (y, si el plan la necesita, la de
  credenciales huérfanas pendientes de limpieza) DEBE persistir mediante una migración versionada,
  de forma que reiniciar backend y frontend conserve las conexiones.

#### Logs

- **FR-056**: Las protecciones de logging existentes DEBEN cubrir también los valores de TikTok
  (access y refresh tokens, códigos, `code_verifier`, `state`, client secret, cabeceras
  `Authorization`, URLs y cuerpos de formulario con secretos, URLs entrantes de callback completas
  —también en los access logs del servidor— y respuestas crudas de TikTok), con tests
  específicos. No DEBEN registrarse respuestas OAuth
  crudas.

#### Calidad y validación

- **FR-057**: Los tests automatizados NO DEBEN depender de TikTok real, Internet ni del keyring
  real; DEBEN usar fakes y cubrir como mínimo:
  - OAuth/PKCE: `state` y `code_verifier` nuevos y de un solo uso, formato del verifier y
    derivación del challenge, el intento más reciente gana, intento caducado, callback duplicado,
    código de un solo uso, callback tras reinicio, error y cancelación del usuario, parámetros
    duplicados/contradictorios, cancelación desde AutoPublisher, URL final limpia.
  - Intercambio: ambos scopes, subconjunto de scopes, `open_id`, identidad, mismatch, respuestas
    inesperadas y seguridad del cuerpo de formulario.
  - Renovación: access vigente, dentro del margen, caducado, renovación correcta, refresh token
    rotado y no rotado, SQLite desfasado respecto al almacén seguro, fallo temporal, rechazo
    definitivo, refresh token caducado, scopes reducidos, `open_id` distinto, concurrencia.
  - Verify: señales vivas correctas; sin renovación, `video.publish` mantenido según los scopes
    conocidos y sin presentarse como comprobado en vivo; con renovación sin `video.publish` →
    `Reconnect required`; ausencia de llamadas de publishing, Content Posting o `creator_info`.
  - Reconnect: misma cuenta, identidad distinta (confirmar/cancelar), orden nuevo secreto → commit
    → borrar viejo, fallo de SQLite que conserva la conexión anterior, fallo al borrar el secreto
    viejo que no rompe la nueva.
  - Disconnect: revocación confirmada, credencial definitivamente inválida según TikTok, fallo
    temporal sin borrado y sin afirmar revocación, secreto ausente del almacén seguro (sin
    contactar con TikTok, sin borrado automático, sin afirmar revocación ni invalidez remota y con
    `Remove locally without revoking` disponible), almacén seguro inaccesible
    (`credential_store_unavailable` sin cambios), eliminación local explícita, idempotencia y
    limpieza del almacén seguro; los tres casos secreto ausente / credencial inválida según TikTok
    / almacén inaccesible DEBEN distinguirse explícitamente en tests.
  - Unicidad en el mismo proyecto y en proyectos distintos; reglas de entidades inactivas.
  - Seguridad: ausencia de secretos en base de datos, logs, API, almacenamiento del navegador,
    configuración versionada, excepciones y cuerpos de formulario; la URL entrante del callback no
    se persiste, no aparece en logs (incluidos access logs) ni en respuestas de la API, y la
    respuesta del callback no contiene `code`, `state`, tokens ni texto crudo del proveedor;
    client secret, tokens y `code_verifier` no aparecen en ninguna URL.
  - Regresión: YouTube, Instagram y Threads sin cambios; núcleo de Accounts, scheduler y
    publishing sin referencias a TikTok.
- **FR-058a (gate temprano de viabilidad)**: `quickstart.md` DEBE comenzar con una comprobación
  manual en TikTok for Developers que se ejecute **antes de implementar en profundidad** la
  feature (antes de la lógica de OAuth, renovación, Reconnect y Disconnect), sin escribir código
  de producto y sin publicar nada, que confirme:
  1. se puede crear o utilizar un Sandbox;
  2. Login Kit for Desktop puede añadirse al Sandbox;
  3. Content Posting API puede añadirse al Sandbox;
  4. Direct Post puede configurarse;
  5. `video.publish` está disponible y es autorizable por el target user sin App Review de
     producción ni auditoría pública;
  6. el redirect URI de loopback elegido puede registrarse;
  7. queda identificado cualquier requisito de verificación de URL o dominio que Content Posting
     API exija para la configuración (TikTok documenta que puede exigirse incluso en Sandbox).
  El resultado de cada punto DEBE registrarse (PASS / STOP) antes de continuar.
- **FR-058b (STOP de viabilidad)**: si para obtener `video.publish` TikTok exige App Review de
  producción, auditoría pública, un dominio o URL pública que el usuario no posee, Privacy
  Policy / Terms / Website inventados o cualquier otro requisito externo que no pueda satisfacerse
  legítimamente en el entorno local actual, la feature DEBE detenerse y revisarse el alcance
  antes de seguir implementando. NO DEBE degradarse silenciosamente la conexión a
  `user.info.basic`, ni crearse URLs ficticias, dominios de terceros, túneles u otros
  workarounds.
- **FR-058**: Superado el gate (FR-058a), `quickstart.md` DEBE incluir la validación manual
  completa con una cuenta real de TikTok, sin publicar nada, en este orden: Sandbox; Login Kit;
  Content Posting API / Direct Post solo para disponer de `video.publish`; target user; redirect
  URI Desktop real; confirmación de PKCE y de la codificación del challenge; `Connect` real; consentimiento que muestre exactamente
  `user.info.basic` y `video.publish`; callback automático; intercambio; identidad; `Verify`;
  reinicio; renovación real cuando sea razonablemente comprobable; `Reconnect`; `Disconnect` con
  revocación remota comprobada en *Manage app permissions*; reconexión final para dejar la cuenta
  lista para la Feature 013; y revisión de seguridad (DB, logs, API, navegador).
- **FR-059**: La validación real DEBE detenerse y revisarse la especificación antes de adaptar
  código si: TikTok Desktop no acepta el callback local elegido; el Sandbox no permite probar
  Login Kit; `video.publish` no puede autorizarse en el entorno de desarrollo; TikTok exige App
  Review o auditoría pública para completar la conexión; se da cualquier condición de FR-058b;
  el PKCE real contradice el contrato
  implementado; la respuesta real de tokens tiene una forma incompatible; los scopes reales no
  pueden confirmarse; la renovación o la revocación contradicen la documentación; aparece
  cualquier secreto en DB/log/API/frontend; o la integración requiere publicar para confirmar la
  cuenta.

### Key Entities *(include if feature involves data)*

- **TikTok Connection**: vínculo entre una `Account` de plataforma TikTok y una cuenta real de
  TikTok. Atributos no sensibles: `Account` (máximo una conexión), proyecto (para la unicidad),
  `open_id` (identidad autoritativa), nombre visible y URL de avatar opcionales, estado
  (`Connected` / `Reconnect required`; la ausencia equivale a `Not connected`), fecha de conexión,
  fecha de última verificación, caducidad informativa del access token y del refresh token y
  referencia opaca a la credencial. Un `open_id` solo puede vincularse a una `Account` por
  proyecto.
- **Credencial de TikTok**: access token, refresh token, sus caducidades absolutas derivadas de
  la respuesta oficial, scopes concedidos y `open_id` asociado. Vive solo en el almacén seguro, en
  un espacio de nombres propio de TikTok; es la fuente de verdad; nunca en la base de datos ni
  expuesta a la interfaz.
- **Intento de autorización pendiente**: estado efímero en memoria: `Account` destino, `state`,
  `code_verifier`, caducidad, estado del intento y, si aplica, identidad y credencial nuevas a la
  espera de confirmación de cambio de cuenta. De un solo uso; no se persiste.
- **Credencial huérfana pendiente de limpieza**: referencia opaca a una credencial anterior que no
  pudo eliminarse tras una sustitución confirmada; no contiene secretos y nunca se usa para operar.
- **Configuración de la aplicación TikTok**: client key, client secret y datos del callback local,
  cargados desde configuración local no versionada y separada de la de otras plataformas.
- **Account** (existente, Feature 002) y **Publication** (existente, Feature 004): no cambian.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real del quickstart (`Account` TikTok local →
  `Connect TikTok` → consentimiento oficial → vuelta automática → identidad verificada → reiniciar
  → seguir `Connected` → `Verify connection` → `Reconnect` → `Disconnect` con revocación → conectar
  de nuevo) sin copiar URLs, sin editar a mano archivos de datos ni la base de datos y sin publicar
  nada en TikTok.
- **SC-002**: Desde que TikTok redirige al callback hasta que la cuenta aparece como `Connected` en
  la interfaz transcurren menos de 10 segundos en condiciones normales de red.
- **SC-003**: En el 100 % de las conexiones, la base de datos, los logs, los mensajes de error,
  las URLs finales del navegador y el almacenamiento del navegador contienen 0 tokens, códigos,
  `code_verifier`, valores `state` o client secrets; las respuestas de la API contienen 0 de estos
  valores salvo `state` y `code_challenge` dentro de la URL de autorización; y `code`/`state` solo
  aparecen en la URL entrante del callback exigida por TikTok, que se registra 0 veces.
- **SC-004**: El 100 % de las conexiones válidas sobreviven a un reinicio completo de la aplicación
  sin pedir una nueva autorización mientras el refresh token siga vigente, incluso si el access
  token caducó durante el apagado.
- **SC-005**: 0 conexiones quedan `Connected` sin ambos permisos requeridos confirmados, 0 cambios
  de cuenta de TikTok se producen sin confirmación explícita y 0 cuentas de TikTok quedan
  vinculadas a dos `Account` del mismo proyecto.
- **SC-006**: El 100 % de los callbacks con `state` inválido, reutilizado, caducado, sustituido o
  de un intento perdido por reinicio se rechazan sin modificar ninguna cuenta ni contactar con
  TikTok.
- **SC-007**: 0 errores temporales de red o de TikTok provocan un paso a `Reconnect required`, y
  0 refresh tokens rotados se reutilizan tras haberse confirmado uno nuevo.
- **SC-008**: Tras una desconexión, el almacén seguro contiene 0 credenciales de esa `Account`, la
  `Account` y el 100 % de sus publicaciones siguen existiendo, y en el 100 % de los casos el
  mensaje mostrado afirma la revocación remota solo si TikTok la confirmó; con el secreto ausente
  del almacén seguro, 0 mensajes afirman revocación o invalidez remota.
- **SC-009**: Cada error listado en FR-052 produce un mensaje comprensible que indica qué ha
  pasado y qué puede hacer el usuario, dejando la cuenta en un estado coherente.
- **SC-010**: La suite automatizada de la feature se ejecuta completa sin Internet, TikTok real ni
  keyring real; las conexiones de YouTube, Instagram y Threads siguen funcionando sin cambios (sus
  tests siguen pasando) y el núcleo de Accounts, el scheduler y el núcleo de publishing no
  contienen referencias a TikTok.
- **SC-011**: La autorización solicita exactamente 2 permisos (`user.info.basic` y
  `video.publish`), verificado por tests y en la validación real.

## Assumptions

- **Alcance**: solo se conecta, mantiene, verifica, reconecta y desconecta. Quedan fuera: Direct
  Post, borradores (upload), publicación de vídeo o fotos, `creator_info`, controles de
  privacidad, captions, divulgación AIGC, subida de media, `PULL_FROM_URL`, verificación de
  dominio (salvo que el dashboard la exija para configurar el producto), scheduler, TikTok
  Publisher, analytics, `video.list`, moderación, App Review, auditoría pública y rediseño de UI.
- **Callback local**: se usa Login Kit for Desktop con un callback HTTP de loopback servido por el
  backend, siguiendo el precedente del callback local de YouTube (Feature 005) y no el patrón de
  pegar la URL de Threads. Host, ruta y estrategia de puerto (fijo o comodín) se deciden en el plan
  a partir del puerto configurable del backend; la aceptación por el dashboard se valida al inicio
  del quickstart.
- **PKCE**: se asume la codificación hexadecimal del challenge que indica la página de Desktop
  hasta que el plan la reconfirme; el quickstart la valida con TikTok real (FR-059).
- **Identidad visible**: como `username` requiere `user.info.profile` (no solicitado), la interfaz
  identifica la cuenta por nombre visible y avatar; el `open_id` puede mostrarse abreviado solo si
  el plan considera que aporta valor y no es sensible.
- **Revocación de credenciales descartadas** (scopes parciales, mismatch cancelado): best-effort,
  sin afectar al resultado ni al estado; su fallo no se muestra como error.
- **Disconnect en entidades inactivas**: se permite incluida la renovación previa necesaria solo
  para revocar, porque reduce el acceso en lugar de ampliarlo; `Verify` sigue bloqueado.
- **Caducidad del refresh token**: la caducidad absoluta guardada en el almacén seguro (derivada
  de `refresh_expires_in` y actualizada en cada renovación) se considera evidencia definitiva; los
  timestamps de SQLite son solo informativos y nunca deciden por sí solos.
- **Decisiones diferidas al plan**: redirect URI exacto y estrategia de puerto, codificación del
  challenge, duración del intento (del orden de 10 minutos, como en 005/008/010), margen de
  renovación, mecanismo para que la interfaz conozca el resultado del intento, página/ruta final
  tras el callback, clasificación de errores OAuth y de la API v2, formato y ubicación de la
  configuración local, espacio de nombres del almacén seguro, registro de credenciales huérfanas y
  garantía de unicidad en persistencia.
- **Paralelismo con features anteriores**: salvo donde TikTok exija otra cosa, se reutilizan las
  decisiones de producto de 005/008/010 (estados, unicidad por proyecto incluyendo cuentas
  inactivas, misma cuenta en proyectos distintos, primera conexión sin confirmación extra,
  confirmación solo ante cambio de identidad, mismatch en Verify → `Reconnect required`, desactivar
  no desconecta, orden crash-safe de credenciales). Las decisiones de protocolo de Meta NO se
  reutilizan automáticamente. A diferencia de 010, `Disconnect` sí revoca remotamente porque
  TikTok ofrece un endpoint oficial.
- **Sandbox y `video.publish`**: no está documentado si el Sandbox permite autorizar
  `video.publish` (solo que no ofrece Content Posting API para vídeos públicos), y Content Posting
  API puede exigir verificación de URL incluso en Sandbox. Por eso la viabilidad se comprueba en
  un gate manual temprano (FR-058a) antes de implementar en profundidad; si aparece cualquier
  condición de STOP (FR-058b), se detiene la feature y se revisa el alcance; nunca se degrada la
  conexión a `user.info.basic` ni se recurre a URLs ficticias o workarounds.
- **Gate G (hechos validados el 2026-10-14 en TikTok for Developers, evidencia en
  `quickstart.md`)**:
  - Sandbox creado y editable.
  - Login Kit con plataforma Desktop disponible.
  - Redirect URI Desktop aceptado y conservado exactamente:
    `http://127.0.0.1:8000/api/tiktok/oauth/callback`.
  - Content Posting API añadida al Sandbox y Direct Post activado.
  - `video.publish` incluido en el Sandbox sin App Review.
  - No se exigió auditoría.
  - No se exigió verificación de dominio ni de URL prefix.
  - *Basic information* satisfecha con Privacy Policy y Terms reales (FR-036).
  - Target user (cuenta propia) añadido y activo.

  **Gate G passed — Feature 012 scope remains viable.**

  Siguen siendo **incertidumbres** que se validan en V1 (quickstart) y NO se dan por
  confirmadas: que el consentimiento real conceda `video.publish` al target user; que TikTok real
  acepte PKCE `S256` con challenge SHA-256 hexadecimal; y la forma real de las respuestas OAuth y
  de tokens.
- **Usuario y entorno**: un único usuario local con una cuenta de TikTok propia añadida como
  target user del Sandbox, una app propia en TikTok for Developers y un navegador en la misma
  máquina que el backend.
- **Dependencias**: reutiliza `Project` y `Account` (Feature 002), `Publication` (Feature 004)
  sin cambios, el almacén seguro de credenciales (Feature 005), las garantías crash-safe de la
  Feature 010, el formato estructurado de errores, las migraciones existentes y los puntos de
  extensión por plataforma de la vista de cuentas.
