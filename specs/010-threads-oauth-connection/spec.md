# Feature Specification: Conexión de cuentas reales de Threads mediante OAuth oficial

**Feature Branch**: `010-threads-oauth-connection`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "Feature 010 — Threads Account Connection & OAuth. Permitir conectar una cuenta real de Threads a una Account de AutoPublisher mediante la API oficial de Threads de Meta: configuración local de la aplicación Threads, OAuth propio de Threads, conexión, almacenamiento seguro de credenciales, Verify, Reconnect, Disconnect local y UI mínima. Solicitar solo los scopes mínimos para la futura publicación (`threads_basic`, `threads_content_publish`). Identificar la cuenta por su ID oficial. Reutilizar los patrones de Connect/Verify/Reconnect/Disconnect y el flujo de pegar la redirect URL de la Feature 008 si sigue siendo compatible, sin forzar Threads dentro de la implementación de Instagram. Sin publicar contenido (Feature 011)."

## Contexto

Desde las Features 005 y 008, las `Account` de YouTube e Instagram pueden vincularse con
cuentas reales mediante OAuth. Las `Account` de plataforma Threads siguen siendo registros
locales (plataforma, handle y nombre visible) sin relación con ninguna cuenta real.

Esta feature introduce la **conexión real con Threads**: una `Account` de plataforma Threads
puede vincularse, mediante el flujo de autorización oficial de la **Threads API** de Meta en el
navegador del usuario, con una cuenta de Threads real. AutoPublisher identifica la cuenta
autorizada por su **Threads user ID**, guarda de forma segura las credenciales necesarias para
actuar en su nombre más adelante y muestra en la interfaz qué cuenta real está vinculada.

Ejemplo:

`Threads @cyber.studio` → `Connect Threads` → login y consentimiento en Threads → cuenta
identificada (`cyber.studio`, ID `2584…`) → `Connected`

El objetivo es dejar la conexión lista para que la Feature 011 pueda publicar en Threads a
través del sistema genérico de publishers existente. **En esta feature no se publica nada.**

La conexión no crea un sistema paralelo de cuentas: siempre se vincula a una `Account`
existente cuya plataforma es Threads. El núcleo común de Accounts permanece independiente de
Threads, igual que de YouTube e Instagram. Threads es una integración **independiente** de
Instagram: comparte proveedor (Meta) y patrones de producto, pero tiene su propia aplicación,
su propio OAuth, sus propios tokens, su propia configuración local y su propio espacio en el
almacén seguro. YouTube e Instagram conservan su comportamiento actual; TikTok, X y Telegram
siguen sin conexión.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login propio.

## Restricciones de la plataforma (documentación oficial de Meta, consultada 2026-10-12)

Estos hechos condicionan el comportamiento del producto. El plan DEBE reconfirmarlos y fijar
los detalles técnicos (hosts, versión de API, parámetros exactos) en `research.md`.

- **Aplicación**: una Meta App con el caso de uso *Access the Threads API*; el caso de uso
  aporta su **propio Threads App ID y Threads App Secret**, distintos de los de Instagram.
- **Permisos**: `threads_basic` es obligatorio para cualquier llamada; `threads_content_publish`
  es necesario para publicar. Otros permisos (`threads_read_replies`, `threads_manage_replies`,
  `threads_manage_insights`, búsqueda, menciones, etc.) existen pero **no** se solicitan.
- **Autorización**: ventana de autorización de Threads con `client_id`, `redirect_uri`,
  `scope`, `response_type=code` y `state` opcional (que Meta devuelve en la redirección). La
  documentación **no** menciona PKCE.
- **Código de autorización**: válido **1 hora** y de **un solo uso**. Meta añade `#_` al final
  de la redirect URL; ese sufijo no forma parte del código.
- **Redirect URI**: debe coincidir exactamente con uno de los registrados en la app (el
  dashboard puede añadir una barra final). La app de ejemplo oficial de Meta indica que las
  redirecciones OAuth solo se admiten sobre **HTTPS**, también en local.
- **Tokens**: el código se intercambia (en servidor, con el app secret) por un token de
  **corta duración (1 h)** y el `user_id` de Threads; este se intercambia por un token de
  **larga duración (60 días)** que devuelve `expires_in`. Un token largo **vigente** con
  **al menos 24 h** de antigüedad puede renovarse (si se concedió `threads_basic`) por otros
  60 días desde la renovación. Un token no renovado en 60 días caduca y **ya no puede
  renovarse**. Un token corto caducado no puede intercambiarse. No existe refresh token
  separado.
- **Duración de la concesión de permisos**: las concesiones de usuarios con perfil **público**
  duran 90 días y se extienden 90 días al renovar el token largo; los usuarios con perfil
  **privado** no pueden extenderla y deben volver a conceder permisos al expirar.
- **Comprobación de permisos**: la respuesta del intercambio de código **no** incluye la
  lista de permisos (a diferencia de Instagram Login). La documentación describe una operación
  de inspección de token (*Debug Access Token*) que devuelve, entre otros, validez, `user_id`,
  `scopes`, `expires_at` y `data_access_expires_at`. El endpoint exacto, el host/versionado y
  **qué credencial autoriza la llamada** (credencial de usuario, Threads App Access Token u
  otra) NO se dan por fijados en esta spec: los verificará el plan (FR-008).
- **Identidad**: la consulta de perfil del usuario autenticado devuelve `id` (Threads user ID),
  `username`, `name`, `threads_profile_picture_url`, entre otros. Solo puede consultarse el
  perfil del usuario de la app.
- **Development Mode**: los **Threads testers** (invitados desde el App Dashboard y que
  aceptan la invitación en *Account Settings → Website permissions* de Threads) pueden conceder
  `threads_basic` y `threads_content_publish` sin App Review. Usuarios sin rol solo tras App
  Review y publicación de la app.
- **Configuración adicional del dashboard**: el caso de uso menciona además una *Deauthorize
  callback URL* y una *Data Deletion Requests URL*. Qué exige exactamente Meta para ellas en
  Development Mode se verificará en el plan (ver Assumptions).
- **Revocación remota**: la documentación consultada no ofrece una operación de revocación de
  la autorización por parte de la app; el usuario retira el acceso desde *Website permissions*
  en la configuración de Threads.

Fuentes: Threads API — *Get Access Tokens and Permissions*, *Long-Lived Access Tokens*,
*Get Started*, *Threads Profiles*, *Debug Access Token*, *Threads use case* y la app de ejemplo
oficial de publicación de Threads.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conectar una Account de Threads con una cuenta de Threads real (Priority: P1)

Como usuario, quiero pulsar `Connect Threads` en una cuenta Threads de un proyecto, iniciar
sesión y autorizar a AutoPublisher en la página oficial de Threads, copiar la dirección
(redirect URL) a la que Threads lleva al navegador, pegarla en AutoPublisher y ver la cuenta
de Threads real vinculada, para que la aplicación quede preparada para publicar en ella.

**Why this priority**: es el núcleo de la feature; sin una primera conexión no existe nada que
verificar, reconectar ni desconectar.

**Independent Test**: con la configuración local de la aplicación Threads preparada, en un
proyecto activo abrir la cuenta activa `Threads @cyber.studio` (estado `Not connected`), pulsar
`Connect Threads`, completar la autorización en Threads, copiar la redirect URL
`https://localhost/...` que muestra el navegador, pegarla en AutoPublisher y enviarla, y
comprobar que la cuenta aparece como `Connected` con username, nombre visible de Threads y
Threads user ID, y que la base de datos local no contiene ningún token.

**Acceptance Scenarios**:

1. **Given** una cuenta Threads activa de un proyecto activo en estado `Not connected` y la
   configuración local de la aplicación Threads presente, **When** el usuario pulsa
   `Connect Threads`, **Then** se abre en su navegador la página oficial de autorización de
   Threads para AutoPublisher, solicitando únicamente `threads_basic` y
   `threads_content_publish`.
2. **Given** una autorización iniciada, **When** el usuario concede los permisos, el navegador
   llega a la redirect URL y el usuario la copia, la pega en AutoPublisher y la envía,
   **Then** AutoPublisher comprueba que corresponde a una autorización que él mismo inició para
   esa cuenta, obtiene la credencial de larga duración, comprueba los permisos concedidos,
   consulta la identidad real mediante la API oficial y la vincula con la `Account`.
3. **Given** una conexión completada, **When** el usuario vuelve a AutoPublisher, **Then** la
   cuenta se muestra como `Connected` con, al menos, username, Threads user ID, fecha de
   conexión, fecha de última verificación y fecha de caducidad del acceso; cuando estén
   disponibles, también el nombre visible de Threads y la foto de perfil.
4. **Given** una conexión completada, **When** se inspeccionan la base de datos local, los
   logs, las respuestas que recibe la interfaz y el almacenamiento del navegador, **Then**
   ninguno contiene access tokens, códigos de autorización, `state` ni el app secret.
5. **Given** una cuenta conectada, **When** se reinician backend y frontend, **Then** la cuenta
   sigue `Connected` con la misma cuenta de Threads, sin pedir de nuevo la autorización.
6. **Given** una cuenta de plataforma distinta de Threads, **When** el usuario la consulta,
   **Then** no se muestra el panel de conexión de Threads, y si se fuerza una operación de
   conexión de Threads se rechaza como plataforma no soportada.
7. **Given** que falta o está incompleta la configuración local de la aplicación Threads,
   **When** el usuario pulsa `Connect Threads`, **Then** no se abre el navegador y recibe un
   mensaje claro (`threads_oauth_not_configured`) que indica dónde está la documentación para
   configurarla.

---

### User Story 2 - Manejar errores de autorización y permisos insuficientes (Priority: P1)

Como usuario, quiero que cualquier cancelación, fallo o concesión incompleta durante la
autorización me muestre un mensaje comprensible y deje mi cuenta en un estado coherente, para
poder reintentar sin quedarme con conexiones a medias.

**Why this priority**: el flujo OAuth tiene muchos caminos de fallo; sin manejarlos la conexión
no es segura ni fiable.

**Independent Test**: simulando (sin Meta real) rechazo del consentimiento, error de Meta,
redirect URL mal formada, `state` desconocido/reutilizado/caducado/de otra cuenta, fallo del
intercambio de código, fallo del intercambio a larga duración, permisos insuficientes,
`user_id` incoherente entre respuestas y Meta inaccesible, comprobar en cada caso que el
usuario ve un mensaje claro, que la cuenta conserva exactamente su estado anterior y que no
queda ninguna credencial almacenada.

**Acceptance Scenarios**:

1. **Given** una autorización iniciada, **When** el usuario cancela o rechaza el
   consentimiento, **Then** AutoPublisher informa de que la conexión se canceló
   (`threads_oauth_denied`), no guarda credenciales y la cuenta mantiene su estado previo.
2. **Given** una redirect URL pegada que no puede parsearse como URL, cuyo scheme, hostname,
   port efectivo o path no coinciden exactamente con los del redirect URI configurado (por
   ejemplo, `https://localhost.evil.example/...`, `https://localhost:8443/...` si el configurado
   no usa ese puerto, o un path que solo comparte prefijo), o que no contiene ni código ni error
   reconocible en query/fragment, **When** se envía, **Then** se rechaza
   (`threads_oauth_redirect_url_invalid`) sin contactar con Meta.
3. **Given** una redirect URL cuyo `state` es desconocido, ya usado o pertenece a un intento de
   otra `Account`, **When** se envía, **Then** se rechaza (`threads_oauth_state_invalid`) sin
   intercambiar ningún código ni modificar ninguna cuenta.
4. **Given** una redirect URL cuyo intento pendiente ha caducado, **When** se envía, **Then** se
   rechaza (`threads_oauth_attempt_expired`) sin efectos y el usuario puede iniciar otro.
5. **Given** una redirect URL que contiene un error devuelto por Meta distinto de la
   cancelación, **When** se envía, **Then** se informa como error seguro del proveedor
   (`threads_oauth_provider_error`) sin mostrar datos crudos de Meta.
6. **Given** una respuesta válida, **When** falla el intercambio del código o el intercambio a
   credencial de larga duración (incluido un código ya usado o caducado), **Then** el usuario ve
   `threads_token_exchange_failed` indicando que debe iniciar una nueva autorización; no se
   guarda ninguna credencial y el código nunca se reintenta.
7. **Given** credenciales obtenidas, **When** los permisos efectivamente concedidos no incluyen
   `threads_basic` y `threads_content_publish`, o no pueden confirmarse mediante el mecanismo
   oficial, **Then** la conexión no se completa (`threads_permission_missing` indicando qué
   falta cuando pueda determinarse), las credenciales se descartan sin guardarse y se explica
   que deben concederse todos los permisos solicitados.
8. **Given** credenciales obtenidas, **When** el Threads user ID devuelto por el intercambio no
   coincide con el de la identidad consultada o con el del token inspeccionado, **Then** la
   conexión no se completa (`threads_unexpected_response`) y las credenciales se descartan.
9. **Given** credenciales obtenidas, **When** Meta no responde o no está accesible al verificar
   permisos o identidad, **Then** la conexión no se completa, las credenciales se descartan y
   el usuario ve un error temporal (`threads_unavailable`) que indica que debe iniciar una nueva
   autorización.
10. **Given** cualquiera de los errores anteriores, **When** se muestra o se registra en logs,
    **Then** sigue el formato estructurado de errores existente y no contiene tokens, códigos,
    `state`, app secret, cabeceras `Authorization`, URLs con secretos ni respuestas crudas
    sensibles de Meta.

---

### User Story 3 - Desconectar una cuenta Threads (Priority: P1)

Como usuario, quiero desconectar una cuenta Threads para que AutoPublisher deje de usarla y
elimine las credenciales que guarda localmente, sin perder la cuenta ni sus publicaciones.

**Why this priority**: eliminar de forma fiable las credenciales locales es indispensable para
manejar credenciales reales de forma segura.

**Independent Test**: conectar una cuenta (con fakes), desconectarla y comprobar que el
almacén seguro ya no contiene sus credenciales, que la referencia local ha desaparecido, que la
cuenta y sus publicaciones siguen existiendo y que la cuenta se muestra `Not connected`.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Disconnect` y confirma, **Then** se eliminan primero sus credenciales del almacén seguro,
   después la conexión local, y la cuenta vuelve a `Not connected`.
2. **Given** una desconexión, **When** termina, **Then** la `Account` conserva plataforma,
   handle, nombre visible y estado activo/inactivo, y sus publicaciones no cambian.
3. **Given** una desconexión, **When** termina, **Then** AutoPublisher no revoca la
   autorización en Meta y el usuario es informado de cómo retirar manualmente el acceso desde
   *Website permissions* en la configuración de Threads.
4. **Given** una cuenta conectada inactiva o de un proyecto inactivo, **When** el usuario la
   desconecta, **Then** se permite igual que en una cuenta activa.
5. **Given** una cuenta ya `Not connected`, **When** se solicita desconectarla, **Then** la
   operación es idempotente.
6. **Given** una cuenta conectada y el almacén seguro no disponible, **When** se solicita
   desconectarla, **Then** falla con `credential_store_unavailable`, la conexión y su
   referencia se conservan y no se informa de una desconexión que no ha ocurrido.

---

### User Story 4 - Mantener la credencial válida y verificar la conexión (Priority: P2)

Como usuario, quiero que AutoPublisher renueve la credencial de Threads según las reglas
oficiales de Meta, que pueda verificar la conexión bajo demanda de forma de solo lectura y que
me avise claramente cuando el acceso se haya perdido definitivamente.

**Why this priority**: es lo que permitirá a la Feature 011 publicar sin pedir login; no es
necesario para la primera conexión, pero sí para que la conexión sea útil.

**Independent Test**: con un fake de Meta y la ventana interna de renovación de AutoPublisher
(`RENEWAL_WINDOW`, política de producto configurable, no una regla de Meta): una credencial
dentro de la ventana y con al menos 24 h (condición técnica de Meta) se renueva y se sustituye
en el almacén seguro; una credencial fuera de la ventana no se renueva aunque tenga más de
24 h; una credencial dentro de la ventana pero con menos de 24 h se usa sin renovar mientras
siga vigente; simular credencial caducada/revocada y comprobar que la cuenta pasa a
`Reconnect required`; simular un fallo de red y comprobar que sigue `Connected`;
ejecutar `Verify connection` con identidad correcta, con datos públicos cambiados, con un ID
distinto y con un permiso retirado.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` cuya credencial es renovable según las reglas oficiales
   (vigente y con al menos 24 h desde el momento en que AutoPublisher la obtuvo o la renovó) y
   la política de renovación definida en el plan indica que conviene renovarla, **When**
   AutoPublisher necesita una credencial válida, **Then** la renueva sin intervención del
   usuario, sustituye de forma segura la credencial almacenada, actualiza el momento de
   obtención de la credencial y su fecha de caducidad conocida (derivada de la respuesta
   oficial), y la cuenta sigue `Connected`.
2. **Given** una credencial vigente obtenida o renovada hace menos de 24 h, **When**
   AutoPublisher la necesita, **Then** la usa tal cual sin intentar renovarla.
3. **Given** una cuenta `Connected` cuya credencial ha caducado, ha sido revocada, cuya
   concesión de permisos ha expirado o que Meta rechaza definitivamente, **When**
   AutoPublisher intenta usarla o renovarla, **Then** la cuenta pasa a `Reconnect required`,
   conserva la identidad pública conocida y la interfaz muestra una explicación y `Reconnect`.
4. **Given** una cuenta `Connected`, **When** la renovación o una consulta fallan por un
   problema transitorio (sin Internet, Meta no disponible, límite temporal), **Then** la cuenta
   NO pasa a `Reconnect required`; el usuario ve un error temporal (`threads_unavailable`) y la
   cuenta sigue `Connected`. Si la credencial actual sigue vigente, puede seguir usándose.
5. **Given** una cuenta `Connected` de una `Account` y un proyecto activos, **When** el usuario
   pulsa `Verify connection`, **Then** AutoPublisher obtiene una credencial válida
   (renovándola si procede), comprueba mediante la API oficial que es válida, que el Threads
   user ID coincide con el vinculado y que conserva `threads_basic` y
   `threads_content_publish`; actualiza username, nombre visible, foto de perfil y fechas de
   caducidad conocidas si han cambiado, registra la fecha de verificación y muestra el
   resultado. Verify no crea, modifica ni borra contenido en Threads.
6. **Given** una verificación, **When** el Threads user ID devuelto es distinto del vinculado,
   **Then** NO se sustituye la identidad; la cuenta pasa a `Reconnect required` y el usuario ve
   `threads_identity_mismatch`.
7. **Given** una verificación, **When** Meta indica que falta o se ha retirado alguno de los
   permisos requeridos, **Then** la operación falla con `threads_reconnect_required`, la cuenta
   pasa a `Reconnect required` y el mensaje indica qué permiso falta cuando pueda determinarse
   de forma segura.
8. **Given** una cuenta `Connected` cuyas credenciales ya no existen en el almacén seguro,
   **When** AutoPublisher las necesita, **Then** la cuenta pasa a `Reconnect required` en lugar
   de producir un error interno.
9. **Given** una cuenta en `Reconnect required`, **When** se consulta, **Then** conserva su
   identidad pública, su estado activo/inactivo, sus datos y sus publicaciones; `Verify
   connection` no está disponible y se exige `Reconnect`.

---

### User Story 5 - Reconectar y proteger contra la cuenta Threads equivocada (Priority: P2)

Como usuario, quiero poder volver a autorizar una cuenta desconectada, conectada o que requiere
reconexión, con la seguridad de que AutoPublisher nunca sustituirá en silencio la cuenta de
Threads vinculada por otra distinta.

**Why this priority**: la reconexión es el camino de recuperación de `Reconnect required` (por
ejemplo, tras los 60 días de token o la expiración de la concesión de un perfil privado), y la
protección frente a la cuenta equivocada evita publicar donde no se desea.

**Independent Test**: con fakes, reconectar con la misma cuenta y comprobar que las nuevas
credenciales sustituyen a las anteriores; después reconectar devolviendo otro Threads user ID y
comprobar que no se sustituye nada hasta que el usuario confirma, y que si cancela la conexión
anterior queda intacta.

**Acceptance Scenarios**:

1. **Given** una cuenta `Not connected`, **When** el usuario completa `Connect Threads`,
   **Then** la cuenta pasa a `Connected` sin paso extra de confirmación.
2. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Reconnect` y autoriza la **misma** cuenta (mismo Threads user ID), **Then** las nuevas
   credenciales sustituyen a las anteriores, la información pública se actualiza y la cuenta
   queda `Connected`.
3. **Given** una cuenta con identidad vinculada, **When** la nueva autorización devuelve un
   Threads user ID **distinto**, **Then** no se modifica la conexión existente; el usuario ve
   una advertencia con la cuenta actual y la nueva (username e ID de ambas) y debe elegir
   explícitamente entre sustituir o cancelar.
4. **Given** esa advertencia, **When** el usuario confirma, **Then** la `Account` queda
   vinculada a la nueva cuenta de Threads con las nuevas credenciales y las anteriores se
   eliminan del almacén seguro.
5. **Given** esa advertencia, **When** el usuario cancela o no responde dentro del tiempo de
   validez del intento, **Then** las nuevas credenciales se descartan sin haberse guardado y la
   conexión anterior queda exactamente como estaba.
6. **Given** el flujo de conexión, **When** se muestra el resultado o la advertencia, **Then**
   queda identificada la `Account` afectada (plataforma, handle, nombre visible y proyecto)
   junto a la cuenta de Threads autorizada.

---

### User Story 6 - Evitar la misma cuenta Threads en dos Accounts del proyecto (Priority: P2)

Como usuario, quiero que AutoPublisher me impida vincular la misma cuenta real de Threads a dos
`Account` distintas del mismo proyecto, para no duplicar publicaciones en el futuro.

**Why this priority**: protege la integridad de futuras publicaciones; depende de la conexión
básica.

**Independent Test**: con fakes, conectar una cuenta al Threads user ID `2584A`, intentar
conectar otra cuenta Threads del mismo proyecto devolviendo `2584A` y comprobar que se rechaza
indicando qué `Account` la tiene, sin guardar credenciales para la segunda.

**Acceptance Scenarios**:

1. **Given** una `Account` del proyecto (activa o inactiva) vinculada a `2584A`, **When** otra
   `Account` del mismo proyecto completa una autorización que devuelve `2584A`, **Then** se
   rechaza (`threads_account_already_connected`), las nuevas credenciales se descartan y el
   usuario ve qué `Account` la tiene y que debe desconectarla primero.
2. **Given** `2584A` vinculada en el proyecto A, **When** una `Account` del proyecto B la
   conecta, **Then** se permite.
3. **Given** `2584A` vinculada a una `Account` que después se desconecta, **When** otra `Account`
   del mismo proyecto la conecta, **Then** se permite.
4. **Given** dos completados simultáneos que devuelven `2584A` para dos `Account` del mismo
   proyecto, **When** ambos intentan completarse, **Then** como máximo uno se completa.
5. **Given** dos cuentas de Threads con el mismo username en momentos distintos, **When** se
   evalúa la unicidad, **Then** solo cuenta el Threads user ID.
6. **Given** una `Account` Instagram vinculada a una cuenta de Instagram, **When** una `Account`
   Threads del mismo proyecto se conecta a la cuenta de Threads del mismo propietario, **Then**
   se permite: las identidades de Threads e Instagram son independientes.

---

### User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

Como usuario, quiero que una cuenta inactiva o de un proyecto inactivo muestre su estado de
conexión pero no permita nuevas autorizaciones ni operaciones activas contra Threads (incluida
`Verify connection`), aunque sí desconectarla.

**Why this priority**: regla de coherencia sobre flujos ya cubiertos.

**Independent Test**: desactivar una cuenta conectada y comprobar que muestra identidad y
estado, que `Connect`/`Reconnect`/`Verify connection`/completar la autorización se rechazan si
se fuerzan y que `Disconnect` funciona; repetir con el proyecto desactivado.

**Acceptance Scenarios**:

1. **Given** una cuenta Threads inactiva, o activa de un proyecto inactivo, **When** el usuario
   la consulta, **Then** ve su estado de conexión y la identidad vinculada si la hay.
2. **Given** esa cuenta, **When** se intenta `Connect`, `Reconnect` o `Verify connection`,
   **Then** la acción no está disponible en la interfaz y, si se fuerza, se rechaza
   (`account_inactive` / `project_inactive`) sin contactar con Meta ni tocar el almacén seguro.
3. **Given** una autorización iniciada con cuenta y proyecto activos, **When** la cuenta o el
   proyecto se desactivan antes de enviar la redirect URL o de confirmar un cambio de cuenta,
   **Then** el envío o la confirmación se rechazan, no se guardan credenciales y la cuenta
   mantiene su estado previo.
4. **Given** una cuenta conectada, **When** ella o su proyecto se desactivan, **Then** su
   conexión NO se elimina.

---

### Edge Cases

- **Configuración de la aplicación Threads ausente o incompleta**: `Connect`/`Reconnect`
  devuelven `threads_oauth_not_configured`; las cuentas ya conectadas siguen mostrando su
  estado y pueden desconectarse.
- **Configuración de Instagram presente pero no la de Threads (o al revés)**: cada integración
  se evalúa por separado; la falta de una no afecta a la otra.
- **Redirect URI HTTPS local rechazado por el dashboard de Meta**: el quickstart lo valida en
  el primer paso; si Meta no lo acepta, se detiene la validación y se revisa la decisión antes
  de continuar (no se usa un dominio de terceros ni un túnel sin aprobación).
- **Sufijo `#_` en la redirect URL**: se ignora; no forma parte del código.
- **Redirect URL que solo comparte prefijo textual con el redirect URI** (otro host, otro
  puerto, subdominio, path más largo o con credenciales de usuario en la URL): se rechaza como
  `threads_oauth_redirect_url_invalid`; la comparación es por componentes, nunca por prefijo.
- **Código de autorización usado o caducado (> 1 h)**: el intercambio falla de forma definitiva
  para ese intento; el usuario inicia una nueva autorización. El intento pendiente caduca antes
  que el código, por lo que normalmente se detecta como intento caducado.
- **Almacén seguro no disponible al conectar**: la conexión no se completa
  (`credential_store_unavailable`); nunca se recurre a guardar tokens en base de datos,
  archivos, `.env`, logs ni almacenamiento del navegador.
- **Fallo al registrar la conexión tras guardar el secreto**: se intenta eliminar el secreto de
  inmediato; nunca queda una conexión sin credencial utilizable.
- **Referencia local sin credencial en el almacén**: la cuenta pasa a `Reconnect required`.
- **Autorización abandonada**: el intento pendiente caduca y la cuenta conserva su estado.
- **Varios intentos para la misma cuenta**: solo el más reciente puede completarse.
- **Redirect URL reutilizada**: no puede procesarse de nuevo.
- **Reinicio del backend durante la autorización**: el intento se pierde; la redirect URL
  posterior se rechaza y el usuario reinicia el flujo.
- **Credencial caducada mientras AutoPublisher estaba apagado (≥ 60 días sin renovar)**: al
  detectarse, la cuenta pasa a `Reconnect required`.
- **Concesión de permisos expirada (perfil privado tras 90 días, o perfil público sin
  renovación)**: Meta rechaza la credencial o la inspección la marca sin acceso a datos; la
  cuenta pasa a `Reconnect required`.
- **Perfil cambiado de público a privado o viceversa**: no rompe la conexión; solo afecta a si
  la concesión puede extenderse. La interfaz muestra la caducidad conocida.
- **Usuario no añadido como Threads tester o invitación sin aceptar (Development Mode)**: Meta
  puede rechazar el flujo en su propia página o volver con un error; en el segundo caso se trata
  como `threads_oauth_provider_error`. La documentación explica cómo añadir y aceptar el rol.
- **Cambio de username en Threads**: no rompe la conexión; se actualiza al verificar o
  reconectar.
- **Handle de la `Account` distinto del username real**: no bloquea ni modifica la `Account`;
  la interfaz muestra ambos.
- **Foto de perfil o nombre visible no disponibles**: no es un error; se muestra un marcador
  neutro.
- **Límite de peticiones o error temporal de Meta**: error temporal; no cambia el estado.
- **Respuesta de Meta inesperada o incompleta** (por ejemplo, sin ID o sin `expires_in`): la
  operación falla con `threads_unexpected_response`, sin datos crudos ni cambios indebidos.
- **Revocación desde la configuración de Threads o *Deauthorize callback* de Meta**:
  AutoPublisher no recibe ese aviso (es local); lo detecta en el siguiente uso o Verify y pasa a
  `Reconnect required`.
- **Cuentas de otras plataformas o `Account` inexistente**: error de plataforma no soportada o
  de cuenta no encontrada.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance y vinculación con Accounts

- **FR-001**: El sistema DEBE permitir vincular una `Account` existente de plataforma Threads
  con una cuenta real de Threads mediante el flujo de autorización oficial de la Threads API en
  el navegador del usuario, sin crear un sistema de cuentas paralelo.
- **FR-002**: El sistema DEBE rechazar cualquier operación de conexión, reconexión,
  verificación o desconexión de Threads sobre una `Account` inexistente o cuya plataforma no
  sea Threads, con un error estructurado comprensible.
- **FR-003**: Cada `Account` Threads DEBE tener como máximo una conexión, vinculada a una única
  cuenta de Threads.
- **FR-004**: El modelo común de `Account`, su esquema y el núcleo común de Accounts, el
  scheduler y el núcleo de publishing NO DEBEN incluir campos, dependencias ni lógica
  específica de Threads. La información de conexión DEBE vivir en módulos aislados de Threads.
  DEBE existir un test de arquitectura que lo garantice, como para YouTube e Instagram.
- **FR-005**: La integración de Threads DEBE ser independiente de la de Instagram: configuración
  propia, credenciales propias, conexión propia y espacio de nombres propio en el almacén
  seguro. PUEDE reutilizar utilidades genéricas existentes (almacén seguro, formato de errores,
  redacción de logs, patrones de intentos pendientes) siempre que no introduzca dependencias de
  Threads en código de Instagram ni viceversa.
- **FR-006**: Esta feature NO DEBE registrar un publisher de Threads ni crear, modificar o borrar
  contenido en Threads.

#### Permisos

- **FR-007**: El sistema DEBE solicitar únicamente `threads_basic` y `threads_content_publish`.
  NO DEBE solicitar permisos de respuestas, insights, búsqueda, menciones, borrado ni otros.
- **FR-008**: La conexión solo DEBE completarse si se confirma, mediante un mecanismo oficial
  documentado, que la credencial obtenida tiene concedidos ambos permisos. Si falta alguno o no
  puede confirmarse, la conexión NO DEBE completarse (`threads_permission_missing`) y las
  credenciales NO DEBEN guardarse. El candidato es la inspección oficial del token (*Debug
  Access Token*), pero esta spec NO fija con qué credencial se autentica. El plan DEBE
  verificar en la documentación oficial vigente: endpoint exacto, host y versionado, credencial
  necesaria para autorizar la llamada, si requiere un Threads App Access Token y cómo se
  obtiene, campos realmente devueltos (`is_valid`, `user_id`, `scopes`, caducidades, etc.) e
  implicaciones de seguridad y almacenamiento. Si se necesita un App Access Token (o cualquier
  credencial de aplicación), NUNCA DEBE llegar al frontend, a logs ni a la base de datos. El
  quickstart DEBE validar el mecanismo real antes de dar por buena una conexión; si los
  permisos no pueden comprobarse de forma inequívoca, se detiene la validación y se revisa la
  decisión, sin degradar silenciosamente este requisito.

#### Estados de conexión

- **FR-009**: Una `Account` Threads DEBE encontrarse en uno de estos estados: `Not connected`
  (sin conexión ni credencial usable), `Connected` (identidad persistida y credencial segura
  usable con los permisos requeridos) o `Reconnect required` (identidad conocida conservada,
  pero las credenciales ya no permiten operar de forma segura).
- **FR-010**: Estos estados NO DEBEN aplicarse a cuentas de otras plataformas y DEBEN ser
  independientes del estado activo/inactivo de la cuenta y del proyecto.

#### Flujo de autorización

- **FR-011**: Cada autorización iniciada DEBE asociarse a una `Account` concreta y protegerse
  con un `state` criptográficamente seguro, de un solo uso y con caducidad limitada (inferior a
  la validez de 1 h del código). El sistema DEBE rechazar sin efectos cualquier respuesta cuyo
  `state` sea desconocido, ya usado, caducado o de otra `Account`.
- **FR-012**: Para cada `Account` solo DEBE poder completarse el intento más reciente.
- **FR-013**: Los intentos pendientes DEBEN ser efímeros y mantenerse solo en memoria. Código,
  `state`, tokens temporales y secretos NUNCA DEBEN persistirse en la base de datos. Un reinicio
  del backend PUEDE invalidar los intentos en curso.
- **FR-014**: Se DEBE reutilizar el patrón de la Feature 008: un redirect URI **HTTPS** local
  registrado en la aplicación de Meta en el que no escucha ningún servidor; el usuario copia la
  redirect URL final del navegador y la envía a AutoPublisher. AutoPublisher NO DEBE requerir
  túneles, servidores HTTPS locales ni dominios de terceros. El sistema DEBE parsear la URL
  pegada como URL (nunca validarla por prefijo textual ni `startswith`) y comprobar que
  **scheme**, **hostname**, **port efectivo** y **path** coinciden exactamente con los del
  redirect URI configurado; solo query y fragment pueden diferir y contener los parámetros
  OAuth devueltos por Meta. Únicamente tras esa validación PUEDEN extraerse `code`, `state`,
  `error` y los demás parámetros OAuth documentados. El sistema DEBE ignorar el sufijo `#_`
  documentado por Threads y distinguir: consentimiento concedido, denegado/cancelado, error de
  Meta y respuesta mal formada.
- **FR-015**: Tras una autorización válida, el sistema DEBE, en el backend: intercambiar el
  código (una sola vez, sin reintentos) por la credencial de corta duración, intercambiarla
  inmediatamente por la credencial de larga duración, descartar la de corta duración, confirmar
  los permisos (FR-008), consultar la identidad real y comprobar que el Threads user ID es
  coherente entre todas las respuestas; solo entonces completar la vinculación.
- **FR-016**: NO DEBE implementarse PKCE ni enviarse parámetros no documentados por la Threads
  API.
- **FR-017**: Ninguna autorización fallida, cancelada, rechazada o incompleta DEBE modificar el
  estado de conexión previo de la `Account` ni dejar credenciales almacenadas.
- **FR-018**: El sistema DEBE rechazar iniciar una conexión o reconexión, completar una
  autorización pendiente, confirmar un cambio de cuenta y `Verify connection` cuando la
  `Account` o su proyecto estén inactivos, sin contactar con Meta. Con entidades inactivas solo
  se permiten consultar el estado, cancelar un intento pendiente y `Disconnect`.

#### Identidad

- **FR-019**: Al completar una conexión, el sistema DEBE persistir únicamente información no
  sensible: Threads user ID, username, nombre visible y URL de foto de perfil si están
  disponibles, fechas de conexión y de última verificación, momento en que AutoPublisher
  obtuvo la credencial de larga duración almacenada actualmente (p. ej. `token_obtained_at`;
  nombre final en el plan), fecha de caducidad de la credencial y, si se obtiene oficialmente,
  fecha de caducidad del acceso a datos, estado y referencia opaca a la credencial.
- **FR-020**: El Threads user ID devuelto por la API DEBE ser la identidad autoritativa; el
  sistema NUNCA DEBE identificar la cuenta por username ni por nombre visible.
- **FR-021**: La conexión NO DEBE modificar el handle ni el nombre visible de la `Account`.

#### Protección contra la cuenta equivocada y duplicados

- **FR-022**: Si una `Account` con identidad vinculada completa una autorización con un Threads
  user ID distinto, el sistema NO DEBE sustituir la conexión: DEBE mostrar ambas cuentas
  (username e ID) y requerir confirmación explícita.
- **FR-023**: Si el usuario cancela o no confirma dentro del tiempo de validez del intento, las
  nuevas credenciales DEBEN descartarse sin persistirse y la conexión anterior DEBE quedar
  intacta.
- **FR-024**: Dentro de un mismo proyecto, un mismo Threads user ID NO DEBE estar vinculado a la
  vez a dos `Account` distintas, activas o inactivas. La regla DEBE estar respaldada por la capa
  de persistencia y resistir operaciones concurrentes; una violación DEBE rechazarse con
  `threads_account_already_connected` indicando qué `Account` la tiene.
- **FR-025**: El mismo Threads user ID PUEDE vincularse a `Account` de proyectos distintos. La
  unicidad de Threads es independiente de la de Instagram y YouTube.

#### Credenciales y configuración

- **FR-026**: Los tokens de Threads DEBEN almacenarse exclusivamente en el almacén seguro del
  sistema operativo, reutilizando la infraestructura existente con un espacio de nombres propio
  de Threads. La base de datos SOLO PUEDE contener la referencia opaca, información pública,
  estado y timestamps.
- **FR-027**: Tokens, códigos, `state`, app secret, cabeceras `Authorization`, URLs con secretos
  y respuestas crudas sensibles de Meta NUNCA DEBEN aparecer en la base de datos, archivos
  versionados, logs, mensajes de error, respuestas de la API, `localStorage` ni
  `sessionStorage`, con la misma excepción estricta que la Feature 008: el `state` puede
  aparecer solo dentro de la URL de autorización devuelta para abrir Threads, y la redirect URL
  pegada puede existir temporalmente en la memoria del formulario y viajar solo en el cuerpo
  del POST de completado; el frontend DEBE descartarla tras enviarla.
- **FR-028**: Si el almacén seguro no está disponible, es inseguro o falla, el sistema DEBE
  abortar con `credential_store_unavailable` sin recurrir a almacenamiento alternativo.
- **FR-029**: La conexión DEBE registrarse en la base de datos únicamente si la credencial se ha
  guardado correctamente; si una operación falla tras guardar un secreto, el sistema DEBE
  intentar eliminarlo inmediatamente.
- **FR-030**: La configuración de la aplicación Threads (Threads App ID, Threads App Secret y
  redirect URI) DEBE cargarse desde configuración local propia de Threads, fuera de Git y de la
  base de datos, nunca enviarse al frontend, y `.gitignore` DEBE cubrirla. El estado de conexión
  PUEDE indicar, sin datos sensibles, si la configuración está disponible.
- **FR-031**: DEBE existir documentación que explique cómo crear la Meta App con el caso de uso
  de Threads, obtener el Threads App ID/Secret, registrar el redirect URI, tratar los campos de
  *Deauthorize callback URL* y *Data Deletion Requests URL* según lo que verifique el plan (ver
  Assumptions), añadir y aceptar la cuenta propia como Threads tester y preparar la
  configuración local sin secretos en el repositorio.

#### Ciclo de vida de la credencial

- **FR-032**: El sistema DEBE ofrecer una capacidad interna, reutilizable por la Feature 011,
  para obtener una credencial válida de una `Account` conectada, renovándola según las reglas
  oficiales (vigente y con al menos 24 h de antigüedad) y sustituyendo de forma segura la
  credencial almacenada. La antigüedad se calcula a partir del momento de obtención de la
  credencial (FR-019), que DEBE registrarse al obtener inicialmente la credencial de larga
  duración y actualizarse cada vez que una renovación devuelva una credencial renovada. Que la
  credencial **pueda** renovarse desde las 24 h NO significa que AutoPublisher DEBA renovarla
  automáticamente cada 24 h; el margen y la política concreta de renovación se decidirán en el
  plan. Renovaciones concurrentes de la misma cuenta NO DEBEN producirse.
- **FR-033**: Las fechas de caducidad persistidas DEBEN derivarse exclusivamente de datos
  devueltos por Meta (por ejemplo, `expires_in` en el momento de recibir el token, `expires_at`
  o fechas devueltas por la inspección oficial del token) o de reglas documentadas; NO DEBEN
  inventarse. El momento de obtención de la credencial NO DEBE usarse para calcular ni suponer
  la caducidad; solo sirve para aplicar la regla de antigüedad mínima de renovación.
- **FR-034**: Cuando la credencial esté caducada, revocada, no sea renovable, su concesión de
  permisos haya expirado, Meta la rechace definitivamente o falte en el almacén seguro, el
  sistema DEBE marcar la `Account` como `Reconnect required` conservando la identidad pública,
  la `Account` y sus publicaciones. "La concesión de permisos haya expirado" significa una
  expiración o invalidez **confirmada por una señal oficial actual de Meta**: por ejemplo, que
  la inspección oficial del token indique que el token o el acceso ya no es válido, que falte un
  permiso requerido, que Meta devuelva un error definitivo de autenticación o autorización, u
  otra respuesta oficial inequívoca equivalente. El `data_access_expires_at` persistido
  localmente es **informativo** y NO PUEDE, por sí solo, provocar `Reconnect required`: una
  fecha local pasada puede estar desactualizada tras una renovación y DEBE confirmarse con Meta
  antes de cambiar el estado.
- **FR-035**: AutoPublisher solo DEBE intentar renovar una credencial cuando esta entra en la
  ventana interna de renovación definida por producto (política interna configurable de
  AutoPublisher, actualmente 7 días antes de la caducidad; no es un requisito de Meta). La regla
  oficial de Meta de al menos 24 h de antigüedad es únicamente una condición técnica para que la
  renovación sea posible, no un motivo para renovar. Los errores temporales de red,
  disponibilidad o límite de peticiones NO DEBEN cambiar el estado de conexión: si la
  renovación falla temporalmente y la credencial actual sigue siendo utilizable fuera del margen
  de expiración, se conserva y PUEDE seguir usándose; si está dentro del margen de expiración y
  no puede renovarse por un fallo temporal, la operación DEBE devolver `threads_unavailable` sin
  pasar a `Reconnect required`. Solo una credencial caducada o un error definitivo de
  autenticación o permisos PUEDEN llevar a `Reconnect required` (FR-034).
- **FR-036**: Esta feature NO DEBE introducir renovación periódica en segundo plano ni lógica de
  Threads en el scheduler. La renovación ocurre cuando AutoPublisher necesita la credencial
  (Verify y, en la Feature 011, publicar). La interfaz DEBE mostrar la caducidad conocida del
  acceso para que el usuario sepa cuándo debe verificar o reconectar.

#### Verificación

- **FR-037**: El usuario DEBE poder ejecutar `Verify connection` sobre una `Account`
  `Connected` con `Account` y proyecto activos. La operación DEBE ser de solo lectura respecto
  a Threads (no crea, modifica ni borra contenido) y DEBE comprobar: credencial válida
  (renovándola si procede), Threads user ID coincidente con el vinculado y permisos
  `threads_basic` y `threads_content_publish` vigentes. DEBE actualizar username, nombre
  visible, foto de perfil y caducidades conocidas si han cambiado y registrar la fecha de
  verificación.
- **FR-038**: Si la verificación detecta un permiso requerido ausente o retirado, DEBE fallar con
  `threads_reconnect_required`, pasar la `Account` a `Reconnect required` y mostrar un mensaje
  seguro con el permiso que falta cuando pueda determinarse. La clasificación de respuestas de
  Meta como temporal, definitiva o de permisos corresponde a la capa de integración con Threads.
- **FR-039**: Si la verificación devuelve un ID distinto del vinculado, el sistema NO DEBE
  reemplazar la identidad: DEBE devolver `threads_identity_mismatch` y pasar la `Account` a
  `Reconnect required`.
- **FR-040**: El plan DEBE confirmar contra la documentación vigente si existe algún otro
  requisito imprescindible para que la Feature 011 pueda publicar con la cuenta conectada (por
  ejemplo, restricciones del tipo de perfil) y, si lo hay y es comprobable de forma de solo
  lectura, incluirlo en Verify; si no lo hay, documentarlo en `research.md`.
- **FR-041**: El sistema DEBE exponer internamente, para la Feature 011, servicios claros para
  obtener una credencial válida y la identidad vinculada de una `Account` conectada.

#### Desconexión y reconexión

- **FR-042**: El usuario DEBE poder ejecutar `Disconnect` sobre una `Account` `Connected` o
  `Reconnect required`, también si la cuenta o el proyecto están inactivos. DEBE eliminar
  primero la credencial del almacén seguro y después la conexión local. Si el almacén no está
  disponible, DEBE fallar con `credential_store_unavailable` y conservar conexión y referencia.
- **FR-043**: La desconexión NO DEBE modificar la `Account` ni sus publicaciones y DEBE ser
  idempotente.
- **FR-044**: La desconexión es solo local: NO DEBE revocarse la autorización en Meta. La
  interfaz o la documentación DEBEN indicar cómo retirar manualmente el acceso desde *Website
  permissions* en Threads.
- **FR-045**: El usuario DEBE poder iniciar de nuevo la autorización sobre una `Account`
  `Not connected`, `Connected` o `Reconnect required` (con cuenta y proyecto activos). Con la
  misma cuenta de Threads, las nuevas credenciales DEBEN sustituir a las anteriores.
- **FR-046**: Desactivar una `Account` o un proyecto NO DEBE desconectar Threads.

#### API, errores e interfaz

- **FR-047**: La API DEBE ofrecer endpoints específicos de Threads para: consultar el estado de
  conexión y la identidad pública, iniciar conexión o reconexión, completar la autorización
  enviando la redirect URL pegada, confirmar o cancelar un cambio de cuenta, verificar y
  desconectar. Completar, confirmar y cancelar DEBEN devolver de forma síncrona el resultado del
  intento; no existe ruta para consultar intentos. Ninguna respuesta DEBE incluir credenciales.
- **FR-048**: Los errores DEBEN seguir el formato estructurado existente con códigos estables y
  seguros propios de Threads, distinguiendo al menos: `threads_oauth_not_configured`,
  `threads_oauth_denied`, `threads_oauth_provider_error`, `threads_oauth_redirect_url_invalid`,
  `threads_oauth_state_invalid`, `threads_oauth_attempt_expired`,
  `threads_oauth_attempt_not_found`, `threads_oauth_attempt_not_confirmable`,
  `threads_connection_changed`, `threads_token_exchange_failed`,
  `threads_permission_missing`, `threads_reconnect_required`, `threads_identity_mismatch`,
  `threads_account_already_connected`, `threads_not_connected`, `threads_unavailable`
  (temporal), `threads_unexpected_response`, `credential_store_unavailable`, cuenta
  inexistente, plataforma no soportada, `account_inactive` y `project_inactive`. Los nombres
  exactos pueden ajustarse en el plan manteniendo el prefijo `threads_`.
- **FR-049**: Para una `Account` Threads, la interfaz DEBE mostrar un panel mínimo específico: en
  `Not connected`, `Connect Threads`; durante la autorización, el campo para pegar la redirect
  URL y, si procede, la advertencia de cambio de cuenta con sus dos opciones; en `Connected`,
  username, nombre visible y foto si existen, Threads user ID, caducidad conocida del acceso,
  fecha de última verificación, `Verify connection`, `Reconnect` y `Disconnect`; en
  `Reconnect required`, una explicación clara, `Reconnect` y `Disconnect`. Las acciones DEBEN
  respetar las reglas de entidades inactivas y los errores DEBEN mostrarse de forma segura.
- **FR-050**: El panel de Threads NO DEBE mostrarse en cuentas de otras plataformas, los
  componentes genéricos NO DEBEN contener lógica de Threads salvo puntos de extensión neutrales
  y esta feature NO DEBE rediseñar la interfaz existente.
- **FR-051**: La información no sensible de la conexión DEBE persistir mediante una migración
  versionada, de forma que reiniciar backend y frontend conserve las conexiones.

#### Logs

- **FR-052**: Las protecciones de logging existentes DEBEN cubrir también los valores de Threads
  (tokens, códigos, app secret de Threads, `state`, cabeceras `Authorization`, URLs con
  secretos, redirect URLs pegadas y respuestas crudas de Meta), con tests específicos.

#### Calidad y validación

- **FR-053**: Los tests automatizados NO DEBEN depender de Meta real, Internet ni del keyring
  real; DEBEN usar fakes y cubrir como mínimo: OAuth happy path; configuración ausente;
  redirect URL inválida (no parseable, scheme distinto, hostname distinto o que solo comparte
  prefijo, port efectivo distinto, path distinto o con prefijo común, sin `code` ni `error`) y
  redirect URL válida con sufijo `#_`; `state` incorrecto, reutilizado, caducado y de otra
  `Account`; error OAuth y cancelación; intercambio de código y a larga duración (éxito y
  fallo); permisos ausentes o no confirmables; `user_id` incoherente; registro del momento de
  obtención de la credencial al conectar y al renovar; renovación (antes de 24 h, renovable,
  fallo temporal, fallo definitivo, caducada) sin derivar la caducidad de ese momento; Verify (éxito, datos cambiados, mismatch,
  permiso retirado, error temporal); Reconnect con misma cuenta y con cambio confirmado y
  cancelado; Disconnect e idempotencia; duplicado en proyecto y proyecto distinto; concurrencia;
  cuentas y proyectos inactivos; almacén no disponible; reinicio durante OAuth; ausencia de
  secretos en base de datos, logs, API y almacenamiento del navegador; e independencia del
  núcleo de Accounts, scheduler, publishing e Instagram.
- **FR-054**: `quickstart.md` DEBE incluir una validación manual con una cuenta real de Threads,
  sin publicar nada: configuración del caso de uso de Threads y del tester; verificación de qué
  exige el dashboard para *Deauthorize callback URL* y *Data Deletion Requests URL* (con la
  condición de detención descrita en Assumptions); registro del redirect URI HTTPS local;
  OAuth real; validación del mecanismo real de comprobación de permisos (FR-008) antes de dar
  la conexión por PASS; scopes realmente concedidos (solo los dos solicitados);
  identidad devuelta (ID y username); credencial de larga duración solo en el keyring y
  caducidad mostrada; reinicio con conexión conservada; `Verify connection`; renovación real
  solo si es comprobable sin riesgo (token con ≥ 24 h); `Disconnect` con credencial eliminada
  del keyring y `Account` preservada; y `Reconnect`.

### Key Entities *(include if feature involves data)*

- **Threads Connection**: vínculo entre una `Account` de plataforma Threads y una cuenta real de
  Threads. Atributos no sensibles: `Account` (máximo una conexión), proyecto (para la
  unicidad), Threads user ID (identidad autoritativa), username, nombre visible y URL de foto
  opcionales, estado (`Connected` / `Reconnect required`; la ausencia equivale a
  `Not connected`), fecha de conexión, fecha de última verificación, momento de obtención de la
  credencial larga actual (p. ej. `token_obtained_at`; se fija al conectar y se actualiza en
  cada renovación correcta; solo sirve para la regla de 24 h), caducidad conocida de la
  credencial (derivada de información oficial), caducidad conocida del acceso a datos
  (opcional) y referencia opaca a la credencial. Un Threads user ID solo puede vincularse a una
  `Account` por proyecto.
- **Credencial de Threads**: token de larga duración, su momento de obtención, su caducidad y
  los permisos confirmados.
  Vive solo en el almacén seguro, en un espacio de nombres propio de Threads; nunca en la base
  de datos ni expuesta a la interfaz.
- **Intento de autorización pendiente**: estado efímero en memoria: `Account` destino, `state`,
  caducidad y, si aplica, la identidad y credenciales nuevas a la espera de confirmación de
  cambio de cuenta. De un solo uso; no se persiste.
- **Configuración de la aplicación Threads**: Threads App ID, Threads App Secret y redirect URI,
  cargados desde configuración local no versionada y separada de la de Instagram.
- **Account** (existente, Feature 002) y **Publication** (existente, Feature 004): no cambian.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real del quickstart (`Account` Threads local →
  `Connect Threads` → consentimiento oficial → identidad verificada → reiniciar → seguir
  `Connected` → `Verify connection` → `Disconnect` → `Reconnect`) sin editar a mano archivos de
  datos ni la base de datos y sin publicar nada en Threads.
- **SC-002**: Desde que el usuario envía la redirect URL pegada correctamente hasta que la cuenta
  aparece como `Connected` transcurren menos de 10 segundos en condiciones normales de red.
- **SC-003**: En el 100 % de las conexiones, la base de datos, los logs, los mensajes de error y
  el almacenamiento del navegador contienen 0 tokens, códigos, valores `state` o app secrets, y
  las respuestas de la API contienen 0 de estos valores salvo el `state` dentro de la URL de
  autorización.
- **SC-004**: El 100 % de las conexiones válidas sobreviven a un reinicio completo de la
  aplicación sin pedir una nueva autorización mientras la credencial siga vigente.
- **SC-005**: Tras desconectar, el almacén seguro contiene 0 credenciales de esa `Account` y la
  `Account` y el 100 % de sus publicaciones siguen existiendo sin cambios.
- **SC-006**: El 100 % de las redirect URLs con `state` inválido, reutilizado, caducado o de otra
  `Account` se rechazan sin modificar ninguna cuenta ni contactar con Meta.
- **SC-007**: 0 conexiones se completan sin ambos permisos requeridos confirmados, 0 cambios de
  cuenta de Threads se producen sin confirmación explícita y 0 cuentas de Threads quedan
  vinculadas a dos `Account` del mismo proyecto.
- **SC-008**: 0 errores temporales de red o de Meta provocan un paso a `Reconnect required`.
- **SC-009**: Cada error listado en FR-048 produce un mensaje comprensible que indica qué ha
  pasado y qué puede hacer el usuario, dejando la cuenta en un estado coherente.
- **SC-010**: La suite automatizada de la feature se ejecuta completa sin Internet, Meta real ni
  keyring real; las conexiones de YouTube e Instagram existentes siguen funcionando sin cambios
  (sus tests siguen pasando) y el núcleo de Accounts, el scheduler y el núcleo de publishing no
  contienen referencias a Threads.
- **SC-011**: La conexión solicita exactamente 2 permisos (`threads_basic` y
  `threads_content_publish`), verificado por tests y en la validación real.

## Assumptions

- **Alcance**: solo se conecta, mantiene, verifica, reconecta y desconecta. Quedan fuera:
  creación de posts, imágenes, vídeos, carousels, cross-post Threads/Instagram, respuestas,
  insights, búsqueda, menciones, moderación, borrado, `ThreadsPublisher`, scheduler y rediseño
  de UI.
- **Redirect local**: se reutiliza el patrón de pegar la redirect URL de la Feature 008 con un
  redirect URI HTTPS en `localhost` propio de Threads (por ejemplo,
  `https://localhost/autopublisher/threads/callback`, valor final en el plan). La aceptación de
  ese URI por el dashboard de Threads se valida en el primer paso del quickstart.
- **Mecanismo de permisos**: no se asume con qué credencial se autentica la inspección oficial
  del token (*Debug Access Token*); el plan lo verificará (credencial de usuario, Threads App
  Access Token u otra) junto con sus implicaciones de seguridad, y el quickstart lo validará
  con la cuenta real. Si no permite confirmar los permisos de forma inequívoca, se detiene y se
  revisa (FR-008).
- **Decisiones diferidas al plan**: hosts y versión de la API (la documentación usa
  `threads.com`/`threads.net` y `graph.threads.com`/`graph.threads.net`), parámetros exactos,
  formato y ubicación de la configuración local, nombre del espacio de nombres del almacén
  seguro, duración y purga de intentos pendientes (del orden de 10 minutos, como en 005/008),
  margen de renovación, clasificación de errores de Meta y garantía de unicidad en
  persistencia.
- **Paralelismo con Instagram/YouTube**: salvo donde Threads exija otra cosa, se reutilizan las
  decisiones de producto de las Features 005 y 008 (estados, unicidad por proyecto incluyendo
  cuentas inactivas, misma cuenta permitida en proyectos distintos, primera conexión sin
  confirmación extra, confirmación solo ante cambio de identidad, mismatch en Verify →
  `Reconnect required`, desactivar no desconecta, sin revocación remota). Las decisiones de
  protocolo de Instagram Login NO se reutilizan automáticamente.
- **Sin perfil profesional**: a diferencia de Instagram, la documentación consultada no exige
  un tipo de cuenta concreto para usar la Threads API; no se filtra por tipo de cuenta salvo que
  el plan encuentre un requisito oficial (FR-040).
- **Callbacks de Meta**: el plan DEBE verificar qué exige actualmente el caso de uso de Threads
  para la *Deauthorize callback URL* y la *Data Deletion Requests URL* (si son obligatorias, si
  se validan, si deben ser públicas y alcanzables en Development Mode). Si Meta exige durante
  Development Mode URLs públicas, funcionales y alcanzables que AutoPublisher local no puede
  proporcionar correctamente, se detiene la configuración y se revisa la arquitectura antes de
  continuar. NO se usarán URLs ficticias, endpoints falsos ni túneles o dominios de terceros
  como workaround automático. En cualquier caso, AutoPublisher no recibe ni procesa esos avisos
  en esta feature; una revocación se detecta en el siguiente uso o Verify.
- **Usuario y entorno**: un único usuario local con una cuenta de Threads propia añadida como
  Threads tester, una Meta App propia y un navegador en la misma máquina.
- **App Review**: no se solicita; AutoPublisher nunca intentará eludir App Review ni
  restricciones de Meta.
- **Dependencias**: reutiliza `Project` y `Account` (Feature 002), `Publication` (Feature 004)
  sin cambios, el almacén seguro de credenciales (Feature 005), el formato estructurado de
  errores, las migraciones existentes y los puntos de extensión por plataforma de la vista de
  cuentas.
