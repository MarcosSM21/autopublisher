# Feature Specification: Conexión de cuentas reales de Instagram mediante Instagram Login

**Feature Branch**: `008-instagram-oauth-connection`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Crear la Feature 008 de AutoPublisher: conexión de cuentas reales de Instagram mediante la Instagram API oficial (Instagram API with Instagram Login). Permitir conectar una Account existente de plataforma Instagram con una cuenta real Instagram Professional (Business o Creator) mediante OAuth en el navegador, solicitando solo `instagram_business_basic` e `instagram_business_content_publish`, identificando la cuenta por su Instagram account ID, guardando los tokens únicamente en el almacén seguro del sistema operativo (SQLite solo guarda una referencia opaca), con estados Not connected / Connected / Reconnect required, ciclo de vida de tokens propio de Meta, Verify connection, Disconnect, Reconnect con confirmación ante cambio de cuenta, unicidad por proyecto, reglas para proyectos y cuentas inactivos, protección de logs y aislamiento del núcleo de Accounts. Sin publicación de contenido (Feature 009), pero documentando en el research el modelo de Content Publishing de Instagram."

## Contexto

Desde la Feature 005, una `Account` de plataforma YouTube puede vincularse con un canal real
mediante OAuth. Las `Account` de Instagram siguen siendo registros locales: una plataforma, un
handle y un nombre visible, sin relación con ninguna cuenta real.

Esta feature introduce la **conexión real con Instagram**: una `Account` de plataforma
Instagram puede vincularse, mediante el flujo oficial **Instagram API with Instagram Login**
de Meta en el navegador del usuario, con una cuenta Instagram **Professional** (Business o
Creator). AutoPublisher identifica la cuenta autorizada, guarda de forma segura las
credenciales necesarias para actuar en su nombre más adelante y muestra en la interfaz qué
cuenta real está vinculada.

Ejemplo:

`Instagram @cyber.studio` → `Connect Instagram` → login y consentimiento en Instagram →
cuenta Professional identificada (`cyber.studio`, `BUSINESS`, ID `1784…`) → `Connected`

Se elige Instagram Login (y no Instagram API with Facebook Login) porque permite conectar
directamente cuentas Professional, admite Business y Creator y no exige una Facebook Page
vinculada. Solo se reconsiderará si el plan demuestra una necesidad técnica concreta.

El objetivo es dejar la conexión lista para que la Feature 009 pueda publicar imágenes y
vídeos/Reels a través del sistema genérico de publishers existente. **En esta feature no se
publica nada.**

La conexión no crea un sistema paralelo de cuentas: siempre se vincula a una `Account`
existente cuya plataforma es Instagram. El núcleo común de Accounts permanece independiente
de Instagram, igual que quedó independiente de YouTube. Las cuentas de YouTube conservan su
comportamiento actual y las de TikTok, X, Threads y Telegram siguen sin conexión.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login propio.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conectar una cuenta Instagram con una cuenta Professional real (Priority: P1)

Como usuario, quiero pulsar `Connect Instagram` en una cuenta Instagram de un proyecto,
iniciar sesión y autorizar a AutoPublisher en la página oficial de Instagram, copiar la
dirección (redirect URL) a la que Instagram lleva al navegador, pegarla en AutoPublisher y
ver la cuenta Professional real vinculada, para que la aplicación quede preparada para
publicar en ella.

**Why this priority**: es el núcleo de la feature; sin una primera conexión no existe nada
que mantener, verificar ni desconectar.

**Independent Test**: con la configuración local de la Meta App preparada, en un proyecto
activo abrir la cuenta activa `Instagram @cyber.studio` (estado `Not connected`), pulsar
`Connect Instagram`, completar la autorización en Instagram con una cuenta Professional,
copiar la redirect URL `https://localhost/...` que muestra el navegador, pegarla en
AutoPublisher y enviarla (`complete`), y comprobar que la cuenta aparece como `Connected`,
mostrando username, tipo de cuenta e Instagram account ID, y que la base de datos local no
contiene ningún token.

**Acceptance Scenarios**:

1. **Given** una cuenta Instagram activa de un proyecto activo en estado `Not connected` y la
   configuración local de la Meta App presente, **When** el usuario pulsa `Connect Instagram`,
   **Then** se abre en su navegador la página oficial de autorización de Instagram para
   AutoPublisher, solicitando únicamente `instagram_business_basic` e
   `instagram_business_content_publish`.
2. **Given** una autorización iniciada, **When** el usuario inicia sesión con una cuenta
   Professional (Business o Creator), concede los permisos, el navegador llega a la redirect
   URL `https://localhost/...` y el usuario la copia, la pega en AutoPublisher y la envía,
   **Then** AutoPublisher comprueba que corresponde a una autorización que él mismo inició para esa
   cuenta, obtiene las credenciales, consulta la API oficial para identificar la cuenta
   autorizada, verifica que es Professional y la vincula con la `Account`.
3. **Given** una conexión completada, **When** el usuario vuelve a AutoPublisher, **Then** la
   cuenta se muestra como `Connected` con, al menos, username, tipo de cuenta, Instagram
   account ID y fecha de última verificación; cuando esté disponible, también la foto de
   perfil.
4. **Given** una conexión completada, **When** se inspeccionan la base de datos local, los
   logs, las respuestas que recibe la interfaz y el almacenamiento del navegador, **Then**
   ninguno contiene access tokens, códigos de autorización, `state` ni el app secret; la base
   de datos solo contiene información pública de la cuenta, el estado, timestamps y una
   referencia opaca a las credenciales.
5. **Given** una cuenta conectada, **When** se reinician el backend y el frontend, **Then** la
   cuenta sigue apareciendo como `Connected` con la misma cuenta Instagram, sin pedir de nuevo
   la autorización.
6. **Given** una cuenta de plataforma distinta de Instagram, **When** el usuario la consulta,
   **Then** no se muestra el panel de conexión de Instagram, y si se intenta iniciar una
   conexión de Instagram igualmente se rechaza indicando que solo las cuentas Instagram pueden
   conectarse por esta vía.
7. **Given** que falta o está incompleta la configuración local de la Meta App, **When** el
   usuario pulsa `Connect Instagram`, **Then** no se abre el navegador y el usuario recibe un
   mensaje claro (`instagram_oauth_not_configured`) que indica que la integración con
   Instagram no está configurada y dónde está la documentación para configurarla.

---

### User Story 2 - Rechazar cuentas no compatibles y manejar errores de autorización (Priority: P1)

Como usuario, quiero que cualquier cancelación, fallo o cuenta no compatible durante la
autorización me muestre un mensaje comprensible y deje mi cuenta en un estado coherente,
para poder reintentar sin quedarme con conexiones a medias.

**Why this priority**: el flujo OAuth tiene muchos caminos de fallo (rechazo, respuestas
manipuladas, cuentas personales, Meta inaccesible); sin manejarlos la conexión no es segura
ni fiable.

**Independent Test**: simulando (sin Meta real) rechazo del consentimiento, `state`
desconocido, reutilizado y caducado, intercambio de código fallido, permisos insuficientes,
cuenta personal/consumer y Meta inaccesible, comprobar en cada caso que el usuario ve un
mensaje claro, que la cuenta conserva exactamente su estado anterior y que no queda ninguna
credencial almacenada.

**Acceptance Scenarios**:

1. **Given** una autorización iniciada, **When** el usuario cancela o rechaza el
   consentimiento en Instagram, **Then** AutoPublisher informa de que la conexión se canceló
   (`instagram_oauth_denied`), no se guarda ninguna credencial y la cuenta mantiene su estado
   previo.
2. **Given** una respuesta de autorización cuyo `state` es desconocido, ya fue usado o no
   corresponde a la cuenta que inició el flujo, **When** llega, **Then** se rechaza
   (`instagram_oauth_state_invalid`) sin intercambiar ningún código ni modificar ninguna
   cuenta.
3. **Given** una respuesta de autorización cuyo intento pendiente ha caducado, **When**
   llega, **Then** se rechaza (`instagram_oauth_attempt_expired`) sin efectos y el usuario
   puede iniciar un nuevo intento.
4. **Given** una respuesta válida, **When** el intercambio del código por credenciales falla,
   **Then** el usuario ve un mensaje claro (`instagram_token_exchange_failed`) indicando que
   puede reintentar, sin credenciales guardadas.
5. **Given** credenciales obtenidas, **When** la cuenta autorizada no es Professional
   (cuenta personal/consumer o tipo no admitido), **Then** la conexión no se completa
   (`instagram_account_not_professional`), las credenciales se descartan sin guardarse y el
   usuario ve un mensaje que explica que solo se admiten cuentas Business o Creator y cómo
   convertir la cuenta.
6. **Given** credenciales obtenidas, **When** no se concedieron todos los permisos
   solicitados, **Then** la conexión no se completa (`instagram_permission_missing`), las
   credenciales se descartan y se indica qué permiso falta.
7. **Given** credenciales obtenidas, **When** Meta no responde o no está accesible al
   identificar la cuenta, **Then** la conexión no se completa, las credenciales se descartan
   y el usuario ve un error temporal de conectividad con Meta.
8. **Given** una respuesta de Meta con un formato inesperado, **When** se procesa, **Then** la
   conexión no se completa y se devuelve un error de respuesta inesperada sin incluir el
   contenido crudo de Meta.
9. **Given** cualquiera de los errores anteriores, **When** se muestra al usuario o se
   registra en logs, **Then** sigue el formato estructurado de errores existente y no
   contiene tokens, códigos de autorización, `state`, app secret, cabeceras `Authorization`,
   URLs con secretos ni respuestas crudas sensibles de Meta.

---

### User Story 3 - Desconectar una cuenta Instagram (Priority: P1)

Como usuario, quiero desconectar una cuenta Instagram para que AutoPublisher deje de usarla
y elimine las credenciales sensibles que guarda localmente, sin perder la cuenta ni sus
publicaciones.

**Why this priority**: eliminar de forma fiable las credenciales locales es parte
indispensable de manejar credenciales reales de forma segura.

**Independent Test**: conectar una cuenta (con fakes), desconectarla y comprobar que el
almacén seguro ya no contiene sus credenciales, que la referencia local ha desaparecido, que
la cuenta y sus publicaciones siguen existiendo y que la cuenta se muestra como
`Not connected`.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Disconnect` y confirma, **Then** se eliminan primero sus credenciales del almacén seguro,
   después la conexión local, y la cuenta vuelve a mostrarse como `Not connected`.
2. **Given** una desconexión, **When** termina, **Then** la cuenta sigue existiendo en su
   proyecto con su plataforma, handle, nombre visible y estado activo/inactivo intactos, y
   todas sus publicaciones existentes se conservan sin cambios.
3. **Given** una desconexión, **When** termina, **Then** AutoPublisher NO revoca
   automáticamente permisos en Meta (salvo que el plan demuestre una revocación aislada y
   segura para esa conexión) y el usuario es informado de cómo retirar manualmente el acceso
   de AutoPublisher desde la configuración de Instagram/Meta.
4. **Given** una cuenta inactiva o de un proyecto inactivo que está conectada, **When** el
   usuario la desconecta, **Then** la desconexión se permite igual que en una cuenta activa.
5. **Given** una cuenta ya `Not connected`, **When** se solicita desconectarla, **Then** la
   operación es idempotente: no da error y la cuenta sigue `Not connected`.
6. **Given** una cuenta conectada y el almacén seguro no disponible, **When** se solicita
   desconectarla, **Then** la operación falla con `credential_store_unavailable`, la conexión
   y su referencia se conservan para reintentar y no se informa de una desconexión que no ha
   ocurrido.

---

### User Story 4 - Mantener la credencial válida y verificar la conexión (Priority: P2)

Como usuario, quiero que AutoPublisher mantenga válida la credencial de Instagram
renovándola antes de que caduque según las reglas oficiales de Meta, que pueda verificar la
conexión bajo demanda y que me avise claramente cuando el acceso se haya perdido
definitivamente.

**Why this priority**: es lo que permitirá a la Feature 009 publicar sin pedir login; no es
necesario para la primera conexión, pero sí para que la conexión sea útil.

**Independent Test**: con un fake de Meta, simular una credencial próxima a caducar y
comprobar que se renueva y se actualiza en el almacén seguro; simular una credencial
caducada/revocada y comprobar que la cuenta pasa a `Reconnect required`; simular un fallo
de red y comprobar que la cuenta sigue `Connected`; ejecutar `Verify connection` con
identidad correcta, con datos públicos cambiados y con un ID distinto.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` cuya credencial se acerca a su caducidad y es renovable
   según las reglas oficiales vigentes, **When** AutoPublisher necesita una credencial válida,
   **Then** la renueva sin intervención del usuario, sustituye de forma segura la credencial
   almacenada y la cuenta sigue `Connected`.
2. **Given** una cuenta `Connected` cuya credencial ha caducado, ha sido revocada, ya no es
   renovable o Meta la rechaza definitivamente, **When** AutoPublisher intenta usarla o
   renovarla, **Then** la cuenta pasa a `Reconnect required`, conserva la identidad pública
   conocida y la interfaz muestra una explicación y la acción `Reconnect`.
3. **Given** una cuenta `Connected`, **When** la renovación o una consulta fallan por un
   problema transitorio (sin Internet, Meta no disponible, límite temporal), **Then** la
   cuenta NO pasa a `Reconnect required`; el usuario ve un error temporal y la cuenta sigue
   `Connected`.
4. **Given** una cuenta `Connected` de una `Account` y un proyecto activos, **When** el
   usuario pulsa `Verify connection`, **Then** AutoPublisher obtiene una credencial válida
   (renovándola si procede), consulta la identidad real mediante la API oficial, comprueba
   que el Instagram account ID coincide con el vinculado y que la conexión conserva los
   permisos requeridos, actualiza username, tipo de cuenta y foto de perfil si han cambiado, registra la
   fecha de verificación y muestra el resultado.
5. **Given** una verificación, **When** el Instagram account ID devuelto es distinto del
   vinculado, **Then** NO se sustituye la identidad; la cuenta pasa a `Reconnect required` y el
   usuario ve un error `instagram_identity_mismatch` que explica que debe reconectar (con
   confirmación explícita si quiere cambiar de cuenta).
6. **Given** una verificación, **When** la cuenta ha dejado de ser Professional, **Then** la
   cuenta pasa a `Reconnect required` con un mensaje que explica que solo se admiten cuentas
   Business o Creator.
6a. **Given** una verificación, **When** Meta indica que falta o se ha retirado
   `instagram_business_basic` o `instagram_business_content_publish`, **Then** la operación
   falla con `instagram_reconnect_required`, la cuenta pasa a `Reconnect required`, conserva
   su identidad pública y el mensaje indica que falta o se retiró un permiso necesario (y
   cuál, cuando pueda determinarse de forma segura).
7. **Given** una cuenta `Connected` cuyas credenciales ya no existen en el almacén seguro
   (borradas externamente), **When** AutoPublisher las necesita, **Then** la cuenta pasa a
   `Reconnect required` en lugar de producir un error interno.
8. **Given** una cuenta en `Reconnect required`, **When** se consulta, **Then** conserva su
   identidad pública conocida, su estado activo/inactivo, sus datos y sus publicaciones;
   `Verify connection` no está disponible y la interfaz/API exige `Reconnect` (no existe
   transición `Reconnect required → Connected` mediante Verify).

---

### User Story 5 - Reconectar y proteger contra la cuenta Instagram equivocada (Priority: P2)

Como usuario, quiero poder volver a autorizar una cuenta desconectada, conectada o que
requiere reconexión, con la seguridad de que AutoPublisher nunca sustituirá en silencio la
cuenta Instagram vinculada por otra distinta.

**Why this priority**: la reconexión es el camino de recuperación de `Reconnect required`, y
la protección frente a la cuenta equivocada evita publicar en el futuro donde no se desea.

**Independent Test**: con fakes, reconectar con la misma cuenta y comprobar que las nuevas
credenciales sustituyen a las anteriores; después reconectar devolviendo otro Instagram
account ID y comprobar que no se sustituye nada hasta que el usuario confirma
explícitamente, y que si cancela la conexión anterior queda intacta.

**Acceptance Scenarios**:

1. **Given** una cuenta `Not connected` (por ejemplo, tras desconectarla), **When** el usuario
   pulsa `Connect Instagram` y completa la autorización, **Then** la cuenta vuelve a
   `Connected`.
2. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Reconnect` y autoriza la **misma** cuenta (mismo Instagram account ID), **Then** las nuevas
   credenciales sustituyen a las anteriores, la información pública se actualiza y la cuenta
   queda `Connected`.
3. **Given** una cuenta con identidad vinculada, **When** la nueva autorización devuelve un
   Instagram account ID **distinto**, **Then** no se modifica la conexión existente; el usuario
   ve una advertencia con la cuenta actual y la nueva (username e Instagram account ID de
   ambas) y debe elegir explícitamente entre sustituir o cancelar.
4. **Given** la advertencia de cuenta distinta, **When** el usuario confirma la sustitución,
   **Then** la `Account` queda vinculada a la nueva cuenta Instagram con las nuevas
   credenciales y las credenciales anteriores se eliminan.
5. **Given** la advertencia de cuenta distinta, **When** el usuario cancela o no responde
   dentro del tiempo de validez del intento pendiente, **Then** las nuevas credenciales se
   descartan sin haberse guardado y la conexión anterior queda exactamente como estaba.
6. **Given** el flujo de conexión, **When** se muestra el resultado o la advertencia, **Then**
   queda claramente identificada la `Account` de AutoPublisher afectada (plataforma, handle,
   nombre visible y proyecto) junto a la cuenta Instagram autorizada.

---

### User Story 6 - Evitar la misma cuenta Instagram en dos Accounts del proyecto (Priority: P2)

Como usuario, quiero que AutoPublisher me impida vincular por error la misma cuenta
Instagram real a dos `Account` distintas del mismo proyecto, para no duplicar publicaciones
en el futuro.

**Why this priority**: protege la integridad de futuras publicaciones; depende de que la
conexión básica ya funcione.

**Independent Test**: con fakes, conectar `Instagram @cyber.studio` a la cuenta con ID `1784A`,
intentar conectar otra cuenta Instagram del mismo proyecto devolviendo también `1784A` y
comprobar que se rechaza indicando qué cuenta la tiene vinculada, sin guardar credenciales
para la segunda.

**Acceptance Scenarios**:

1. **Given** una `Account` del proyecto ya vinculada al Instagram account ID `1784A` (activa o
   inactiva), **When** otra `Account` del mismo proyecto completa una autorización que
   devuelve `1784A`, **Then** la vinculación se rechaza
   (`instagram_account_already_connected`), las nuevas credenciales se descartan y el usuario
   ve qué `Account` del proyecto la tiene ya y que debe desconectarla primero.
2. **Given** `1784A` vinculada en el proyecto A, **When** una `Account` del proyecto B la
   conecta, **Then** se permite (la restricción es por proyecto, igual que en YouTube).
3. **Given** `1784A` vinculada a una `Account` que después se desconecta, **When** otra
   `Account` del mismo proyecto la conecta, **Then** se permite.
4. **Given** dos conexiones simultáneas que devuelven `1784A` para dos `Account` del mismo
   proyecto, **When** ambas intentan completarse, **Then** como máximo una se completa; la otra
   se rechaza con el conflicto anterior.
5. **Given** dos cuentas Instagram distintas con el mismo username en momentos distintos
   (username reutilizado), **When** se evalúa la unicidad, **Then** solo cuenta el Instagram
   account ID, nunca el username.

---

### User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

Como usuario, quiero que una cuenta inactiva o de un proyecto inactivo muestre su estado de
conexión pero no permita nuevas autorizaciones ni operaciones activas contra Instagram
(incluida `Verify connection`), aunque sí desconectarla.

**Why this priority**: regla de coherencia sobre flujos ya cubiertos por historias
anteriores.

**Independent Test**: desactivar una cuenta conectada, comprobar que sigue mostrando su
identidad y estado, que `Connect`/`Reconnect`/`Verify connection` no están disponibles y se
rechazan si se fuerzan, y que `Disconnect` funciona; repetir con el proyecto desactivado.

**Acceptance Scenarios**:

1. **Given** una cuenta Instagram inactiva, o una cuenta activa de un proyecto inactivo,
   **When** el usuario la consulta, **Then** ve su estado de conexión y la identidad vinculada
   si la hay.
2. **Given** esa misma cuenta, **When** se intenta `Connect`, `Reconnect` o
   `Verify connection`, **Then** la acción no está disponible en la interfaz y, si se fuerza, se rechaza indicando que la cuenta o el
   proyecto deben reactivarse primero.
3. **Given** una autorización iniciada con la cuenta y el proyecto activos, **When** la cuenta
   o el proyecto se desactivan antes de que el usuario envíe la redirect URL pegada, **Then**
   el envío se rechaza, no se guardan credenciales y la cuenta mantiene su estado previo.
4. **Given** una cuenta conectada que se desactiva (o cuyo proyecto se desactiva), **When** se
   desactiva, **Then** su conexión NO se elimina automáticamente.
5. **Given** una cuenta Instagram inactiva o de un proyecto inactivo, **When** se intenta
   `Verify connection`, **Then** se rechaza indicando que la cuenta o el proyecto deben
   reactivarse primero, sin contactar con Meta ni modificar el almacén seguro (Verify puede
   renovar credenciales y actualizar datos, lo que es una operación activa).

---

### Edge Cases

- **Configuración de la Meta App ausente o incompleta**: `Connect`/`Reconnect` devuelven
  `instagram_oauth_not_configured`; las cuentas ya conectadas siguen mostrando su estado y
  pueden desconectarse.
- **Almacén seguro no disponible al conectar**: la conexión no se completa
  (`credential_store_unavailable`); AutoPublisher NUNCA recurre a guardar tokens en la base
  de datos, archivos, `.env`, logs ni almacenamiento del navegador.
- **Fallo al registrar la conexión tras guardar el secreto**: AutoPublisher intenta eliminar
  inmediatamente el secreto; nunca queda una conexión en la base de datos sin credencial
  utilizable. Si la eliminación también falla, puede quedar una entrada huérfana en el
  almacén, sin referencia ni uso posible, que el usuario puede borrar con las herramientas del
  sistema (comportamiento equivalente al de YouTube).
- **Referencia local sin credencial en el almacén**: la cuenta pasa a `Reconnect required`
  cuando se detecta.
- **Autorización abandonada**: el intento pendiente caduca tras un tiempo limitado y la
  cuenta conserva su estado.
- **Varios intentos para la misma cuenta**: solo el más reciente puede completarse
  (latest-attempt-wins); los anteriores quedan invalidados.
- **Redirect URL reutilizada**: una redirect URL ya procesada no puede procesarse de nuevo.
- **Redirect URL de un intento de otra cuenta distinta de la que inició el flujo**: se rechaza como `state`
  inválido.
- **Reinicio del backend durante la autorización**: el intento pendiente se pierde y la
  respuesta posterior se rechaza como inválida/caducada; el usuario reinicia el flujo.
- **Cuenta Instagram personal/consumer**: se rechaza sin guardar credenciales.
- **Cuenta Creator vs Business**: ambas se admiten y su tipo se muestra.
- **Cambio de username en Instagram**: no rompe la conexión porque la identidad es el
  Instagram account ID; el username se actualiza al verificar o reconectar.
- **Handle de la `Account` distinto del username real**: no bloquea la conexión ni modifica
  la `Account`; la interfaz muestra ambos para que el usuario detecte discrepancias.
- **Foto de perfil no disponible o URL caducada**: no es un error; la interfaz muestra un
  marcador neutro.
- **Credencial caducada mientras AutoPublisher estaba apagado**: al detectarse, si ya no es
  renovable según las reglas oficiales, la cuenta pasa a `Reconnect required`.
- **Límite de peticiones o error temporal de Meta**: se trata como error temporal; no cambia
  el estado de conexión.
- **Respuesta de Meta inesperada o incompleta** (por ejemplo, sin ID): la operación falla con
  error de respuesta inesperada, sin datos crudos ni cambios de estado indebidos.
- **App de Meta en modo de desarrollo y cuenta no autorizada como tester/rol**: Meta puede
  rechazar el flujo directamente en su propia página (no se llega a la redirect URL) o volver a
  la redirect URL con un error OAuth. En el segundo caso AutoPublisher lo trata como error
  seguro del proveedor (`instagram_oauth_provider_error`), sin interpretar ni mostrar datos
  crudos de Meta. La documentación explica cómo añadir la cuenta como tester.
- **Cuentas de otras plataformas**: cualquier operación de conexión de Instagram sobre ellas
  se rechaza como plataforma no soportada.
- **Cuenta inexistente**: cualquier operación devuelve un error de cuenta no encontrada.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance y vinculación con Accounts

- **FR-001**: El sistema DEBE permitir vincular una `Account` existente de plataforma
  Instagram con una cuenta Instagram Professional real mediante el flujo oficial Instagram
  API with Instagram Login en el navegador del usuario, sin crear un sistema de cuentas
  paralelo.
- **FR-002**: El sistema DEBE rechazar cualquier operación de conexión, reconexión,
  verificación o desconexión de Instagram sobre una `Account` inexistente o cuya plataforma no
  sea Instagram, con un error estructurado comprensible.
- **FR-003**: Cada `Account` Instagram DEBE tener como máximo una conexión, vinculada a una
  única cuenta Instagram, en cada momento.
- **FR-004**: El modelo común de `Account`, su esquema común y el núcleo común de Accounts NO
  DEBEN incluir campos ni dependencias específicas de Instagram; la información de conexión
  DEBE vivir en un módulo aislado de plataforma. DEBE existir un test de arquitectura que lo
  garantice, igual que para YouTube.

#### Cuentas admitidas y permisos

- **FR-005**: Solo DEBEN poder conectarse cuentas Instagram Professional (Business o
  Creator). Si la autorización devuelve una cuenta de otro tipo, la conexión NO DEBE
  completarse, las credenciales NO DEBEN guardarse y el usuario DEBE recibir
  `instagram_account_not_professional`.
- **FR-006**: El sistema DEBE solicitar únicamente los permisos `instagram_business_basic` e
  `instagram_business_content_publish` (mínimo privilegio). NO DEBE solicitar permisos de
  mensajes, comentarios, insights, publicidad ni otras capacidades.
- **FR-007**: Si los permisos concedidos no incluyen ambos permisos requeridos, la conexión NO
  DEBE completarse y el usuario DEBE recibir `instagram_permission_missing` indicando qué
  falta. El mecanismo exacto para comprobar los permisos/scopes efectivamente concedidos DEBE
  verificarse durante el plan contra la documentación oficial vigente de Instagram API with
  Instagram Login; NO DEBE asumirse de antemano ningún endpoint ni herramienta concretos no
  confirmados (por ejemplo, `/me/permissions`, Access Token Debugger o mecanismos propios de
  Facebook Login).

#### Estados de conexión

- **FR-008**: Una `Account` Instagram DEBE encontrarse en uno de estos estados: `Not connected`
  (sin conexión ni credencial usable), `Connected` (identidad persistida, credencial segura
  usable y cuenta Professional verificada) o `Reconnect required` (identidad conocida
  conservada, pero las credenciales ya no permiten operar de forma segura).
- **FR-009**: Los estados de conexión de Instagram NO DEBEN aplicarse a cuentas de otras
  plataformas y DEBEN ser independientes del estado activo/inactivo de la cuenta y del
  proyecto.

#### Flujo de autorización

- **FR-010**: Cada autorización iniciada DEBE asociarse a una `Account` concreta y protegerse
  con un `state` criptográficamente seguro, de un solo uso y con caducidad limitada. El
  sistema DEBE rechazar sin efectos cualquier respuesta cuyo `state` sea desconocido, ya
  usado, caducado o no corresponda a la `Account` que inició el flujo.
- **FR-011**: Para cada `Account` solo DEBE poder completarse el intento de autorización más
  reciente (latest-attempt-wins).
- **FR-012**: Los intentos de autorización pendientes DEBEN ser efímeros y mantenerse solo en
  memoria. El código de autorización, el `state`, los tokens temporales y los secretos OAuth
  NUNCA DEBEN persistirse en la base de datos. Un reinicio del backend PUEDE invalidar los
  intentos en curso. La duración, la conservación de resultados terminales y la purga se
  definirán en el plan.
- **FR-013**: En esta feature, "respuesta de autorización", "callback" o "redirect" se
  refieren a la redirect URL que produce Meta tras el consentimiento. AutoPublisher no la
  recibe mediante un servidor HTTPS de callback: el usuario la copia desde el navegador y la
  envía mediante `complete`. El sistema DEBE validar esa redirect URL antes de usarla y
  distinguir: consentimiento concedido, denegado/cancelado por el usuario, error de Meta y
  respuesta mal formada.
- **FR-014**: Tras una autorización válida, el sistema DEBE obtener las credenciales según el
  mecanismo oficial vigente (incluido el intercambio a credencial de larga duración si
  procede), consultar la identidad real de la cuenta mediante la API oficial, verificar tipo
  de cuenta y permisos, y solo entonces completar la vinculación.
- **FR-015**: Ninguna autorización fallida, cancelada, rechazada o no compatible DEBE
  modificar el estado de conexión previo de la `Account` ni dejar credenciales almacenadas.
- **FR-016**: El sistema DEBE rechazar el inicio de una conexión o reconexión, el completado
  de una autorización pendiente y `Verify connection` cuando la `Account` o su proyecto estén
  inactivos. Con entidades inactivas solo se permiten consultar el estado y `Disconnect`.
  Desactivar no desconecta.
- **FR-017**: Los detalles del protocolo (endpoints de autorización y token, redirect URI
  admitido para una aplicación local, soporte o necesidad de PKCE, intercambio del token
  inicial, credencial de larga duración, reglas de renovación, caducidades reales y versión de
  Graph API) DEBEN verificarse en el plan contra la documentación oficial vigente de Meta; NO
  DEBEN inventarse ni copiarse de la integración con Google.

#### Identidad de la cuenta Instagram

- **FR-018**: Al completar una conexión, el sistema DEBE persistir únicamente información
  pública/no sensible: Instagram account ID autoritativo, username, tipo de cuenta, foto de
  perfil si está disponible, fechas de conexión y de última verificación, estado de conexión y
  referencia opaca a la credencial.
- **FR-019**: El Instagram account ID devuelto por la API DEBE ser la identidad autoritativa;
  el sistema NUNCA DEBE identificar la cuenta únicamente por username.
- **FR-020**: La conexión NO DEBE modificar el handle ni el nombre visible de la `Account`.

#### Protección contra la cuenta equivocada y duplicados

- **FR-021**: Si una `Account` con identidad vinculada completa una autorización que devuelve
  un Instagram account ID distinto, el sistema NO DEBE sustituir la conexión; DEBE mostrar la
  cuenta actual y la nueva (username e ID de ambas) y requerir confirmación explícita.
- **FR-022**: Si el usuario cancela la sustitución o no confirma dentro de un tiempo limitado,
  el sistema DEBE descartar las nuevas credenciales pendientes y dejar intacta la conexión
  anterior. Las credenciales pendientes de confirmación NO DEBEN persistirse en la base de
  datos.
- **FR-023**: Dentro de un mismo proyecto, un mismo Instagram account ID NO DEBE estar
  vinculado a la vez a dos `Account` distintas, activas o inactivas. La regla DEBE estar
  respaldada por la capa de persistencia y resistir operaciones concurrentes; un intento que
  la violaría DEBE rechazarse con `instagram_account_already_connected` indicando qué `Account`
  la tiene.
- **FR-024**: El mismo Instagram account ID PUEDE vincularse a `Account` de proyectos
  distintos.

#### Credenciales y configuración

- **FR-025**: Todos los tokens de Instagram DEBEN almacenarse exclusivamente en el almacén
  seguro del sistema operativo, reutilizando la infraestructura de almacenamiento seguro de
  la Feature 005 y sus backends permitidos. La base de datos SOLO PUEDE contener la
  referencia opaca, información pública, estado y timestamps.
- **FR-026**: Tokens, códigos de autorización, `state`, app secret, cabeceras
  `Authorization`, URLs que incluyan secretos y respuestas crudas sensibles de Meta NUNCA
  DEBEN aparecer en la base de datos, archivos versionados, logs, mensajes de error,
  respuestas de la API al frontend, `localStorage` ni `sessionStorage`, con una única
  excepción estricta impuesta por el protocolo OAuth:
  - el `state` PUEDE aparecer únicamente dentro de la `authorization_url` generada que
    devuelve la API para abrir la página de Instagram;
  - la redirect URL que pega el usuario (que contiene `code` y `state`) PUEDE existir
    temporalmente en la memoria del formulario del frontend y viajar únicamente en el cuerpo
    del POST de `complete`; el frontend DEBE descartarla en cuanto la envía.
  En ningún caso `code` ni `state` DEBEN persistirse, registrarse en logs, guardarse en
  `localStorage`/`sessionStorage` ni incluirse en mensajes de error.
- **FR-027**: Si el almacén seguro no está disponible, es inseguro o falla, el sistema DEBE
  abortar con `credential_store_unavailable` y NO DEBE recurrir a ningún almacenamiento
  alternativo inseguro.
- **FR-028**: La conexión DEBE registrarse en la base de datos únicamente si la credencial se
  ha guardado correctamente; nunca DEBE quedar una conexión sin credencial utilizable. Si una
  operación falla tras guardar un secreto, el sistema DEBE intentar eliminarlo inmediatamente.
- **FR-029**: La configuración de la Meta App (identificadores y secretos de la aplicación)
  DEBE cargarse desde configuración local, fuera de Git, fuera de la base de datos si contiene
  secretos y nunca enviarse al frontend. `.gitignore` DEBE cubrir específicamente los archivos
  de configuración/secretos de Meta. La ubicación exacta se decidirá en el plan.
- **FR-030**: DEBE existir documentación que explique cómo crear y configurar la Meta App,
  añadir el producto Instagram con Instagram Login, configurar el redirect URI, autorizar la
  cuenta propia como tester y preparar la configuración local sin introducir secretos en el
  repositorio.

#### Ciclo de vida de la credencial

- **FR-031**: El sistema DEBE ofrecer una capacidad interna, reutilizable por el futuro
  publisher de Instagram, para obtener una credencial válida de una `Account` conectada,
  renovándola antes de caducar cuando el flujo oficial lo permita y sustituyendo de forma
  segura la credencial almacenada. Esta estrategia DEBE ser propia de Instagram, basada en la
  documentación de Meta.
- **FR-032**: Cuando la credencial esté caducada, revocada, no sea renovable, Meta la rechace
  definitivamente o falte en el almacén seguro, el sistema DEBE marcar la `Account` como
  `Reconnect required` conservando la identidad pública conocida, la `Account` y sus
  publicaciones.
- **FR-033**: Los errores temporales de red, de disponibilidad o de límite de peticiones de
  Meta NO DEBEN cambiar el estado de conexión.

#### Verificación

- **FR-034**: El usuario DEBE poder ejecutar `Verify connection` sobre una `Account`
  `Connected` cuya `Account` y proyecto estén activos (en `Reconnect required` se exige
  `Reconnect`; con entidades inactivas se rechaza, FR-016): el sistema obtiene una credencial
  válida (renovándola si procede), consulta la identidad real mediante la API oficial,
  comprueba que el ID coincide con el vinculado, que la cuenta sigue siendo Professional y que
  la conexión conserva los permisos requeridos, actualiza username, tipo de cuenta y foto de
  perfil si han cambiado y registra la fecha de verificación.
- **FR-034a**: Si Meta indica que falta o se ha retirado `instagram_business_basic` o
  `instagram_business_content_publish`, `Verify connection` DEBE fallar con
  `instagram_reconnect_required`, pasar la `Account` a `Reconnect required` conservando la
  identidad pública, y mostrar un mensaje seguro que indique que falta o se retiró un permiso
  necesario y, cuando pueda determinarse de forma segura, cuál. La clasificación de las
  respuestas de Meta como "permiso ausente/retirado" corresponde al gateway; la lógica de
  servicio trabaja con esa clasificación semántica, no con números de error concretos.
- **FR-035**: Si la verificación devuelve un ID distinto del vinculado, el sistema NO DEBE
  reemplazar la identidad: DEBE devolver `instagram_identity_mismatch` y pasar la `Account` a
  `Reconnect required`; el cambio de cuenta solo puede hacerse mediante una reconexión con
  confirmación explícita (FR-021).
- **FR-036**: El sistema DEBE exponer internamente, para la Feature 009, servicios claros para
  obtener credencial válida, consultar la identidad y verificar el Instagram account ID de una
  `Account` conectada. Esta feature NO DEBE registrar un publisher de Instagram operativo.

#### Desconexión y reconexión

- **FR-037**: El usuario DEBE poder ejecutar `Disconnect Instagram` sobre una `Account`
  `Connected` o `Reconnect required`, también si la cuenta o el proyecto están inactivos. La
  operación DEBE eliminar primero la credencial del almacén seguro y, solo después, la
  conexión local, dejando la `Account` en `Not connected`. Si el almacén no está disponible,
  DEBE fallar con `credential_store_unavailable` y conservar conexión y referencia.
- **FR-038**: La desconexión NO DEBE eliminar ni modificar la `Account` ni sus publicaciones, y
  DEBE ser idempotente.
- **FR-039**: Al desconectar, el sistema NO DEBE revocar automáticamente permisos en Meta
  salvo que el plan demuestre que la API garantiza una revocación aislada y segura para esa
  conexión. La interfaz o la documentación DEBEN indicar cómo retirar manualmente el acceso.
- **FR-040**: El usuario DEBE poder iniciar de nuevo la autorización sobre una `Account`
  `Not connected`, `Connected` o `Reconnect required` (con cuenta y proyecto activos). Con la
  misma cuenta Instagram, las nuevas credenciales DEBEN sustituir a las anteriores y la
  información pública actualizarse.
- **FR-041**: Desactivar una `Account` o un proyecto NO DEBE desconectar Instagram.

#### API, errores e interfaz

- **FR-042**: La API DEBE permitir, mediante endpoints específicos de Instagram: consultar el
  estado de conexión y la identidad pública (incluyendo, sin datos sensibles, si la
  configuración de Meta está disponible), iniciar conexión o reconexión, completar la
  autorización enviando la redirect URL pegada, confirmar o cancelar un cambio de cuenta,
  verificar la conexión y desconectar. `complete`, `confirm` y `cancel` DEBEN devolver
  directamente, de forma síncrona, el resultado actual del intento; no existe una ruta para
  consultar intentos, que siguen siendo efímeros y en memoria. Ninguna respuesta DEBE incluir
  credenciales.
- **FR-043**: Los errores DEBEN seguir el formato estructurado existente con códigos estables
  y seguros, distinguiendo al menos: `instagram_oauth_not_configured`,
  `instagram_account_not_professional`, `instagram_permission_missing`,
  `instagram_oauth_denied`, `instagram_oauth_state_invalid`,
  `instagram_oauth_attempt_expired`, `instagram_token_exchange_failed`,
  `instagram_reconnect_required`,
  `instagram_identity_mismatch`, `instagram_account_already_connected`,
  `credential_store_unavailable`, error temporal de Meta/red, respuesta inesperada, cuenta
  inexistente, plataforma no soportada y cuenta o proyecto inactivos. Política de renovación:
  un fallo temporal (red, disponibilidad, límite de peticiones) mientras la situación sea
  recuperable DEBE devolver el error temporal de Meta sin cambiar el estado; una credencial
  caducada, revocada, no renovable o una renovación rechazada definitivamente DEBE devolver
  `instagram_reconnect_required`. "Refresh fallido" puede existir como causa interna segura,
  pero no es un código público de la API. Los nombres exactos pueden ajustarse en el plan.
- **FR-044**: Para una `Account` Instagram, la interfaz DEBE mostrar un panel específico:
  en `Not connected`, `Connect Instagram`; en `Connected`, username, tipo de cuenta, foto de
  perfil si existe, Instagram account ID, `Verify connection`, `Reconnect` y `Disconnect`; en
  `Reconnect required`, una explicación clara, `Reconnect` y `Disconnect` (sin
  `Verify connection`). Las acciones DEBEN
  respetar las reglas de cuentas y proyectos inactivos.
- **FR-045**: El panel de Instagram NO DEBE mostrarse en cuentas de otras plataformas, y los
  componentes genéricos NO DEBEN contener lógica de Instagram salvo puntos de extensión
  neutrales.
- **FR-046**: La interfaz DEBE mostrar los resultados y errores del flujo de forma
  comprensible, incluida la advertencia de cambio de cuenta con sus dos opciones explícitas.
- **FR-047**: La información no sensible de la conexión DEBE persistir mediante una migración
  versionada, de forma que reiniciar backend y frontend conserve las conexiones.

#### Logs

- **FR-048**: Las protecciones de logging existentes DEBEN extenderse para impedir que
  aparezcan tokens de acceso, códigos de autorización, app secret, `state`, cabeceras
  `Authorization`, URLs con secretos y respuestas crudas sensibles de Meta, con tests
  específicos.

#### Investigación para la Feature 009

- **FR-049**: El research del plan DEBE documentar, sin implementarlo, el modelo vigente de
  Content Publishing de Instagram: creación de media container, espera hasta que esté listo,
  `media_publish`, imágenes, vídeos/Reels, necesidad de media públicamente accesible o
  mecanismos oficiales alternativos de subida, límites de formato/tamaño/duración, límites de
  publicación, caducidad de containers, diferencias Business vs Creator y restricciones de
  App Review / modo de desarrollo.
- **FR-050**: La documentación DEBE explicar la diferencia entre probar con cuentas/roles
  autorizados en modo de desarrollo, distribuir AutoPublisher a otros usuarios y los permisos
  que requieren App Review o acceso avanzado, priorizando la vía oficial mínima para que el
  usuario pruebe con su propia cuenta como tester/role autorizado de la Meta App. Durante el
  plan y la validación real DEBE comprobarse qué permisos requeridos pueden usarse actualmente
  en Development Mode sin App Review; si Meta exige App Review/Advanced Access para alguno de
  ellos incluso en el flujo real de prueba, DEBE documentarse y detenerse la validación
  correspondiente. AutoPublisher NUNCA DEBE intentar eludir App Review ni restricciones de
  Meta.

#### Calidad

- **FR-051**: Los tests automatizados NO DEBEN depender de Meta real, de Internet ni del
  keyring real; DEBEN usar fakes de Meta/Instagram y del almacén seguro, y cubrir como mínimo
  los casos enumerados en la descripción de la feature (cuentas Business/Creator/no
  profesional, configuración ausente, `state` válido/inválido/reutilizado/caducado, pasted redirect
  URL de un intento de otra `Account`, pasted redirect URL inválida, permisos insuficientes, intercambio y ciclo de vida del token, refresh
  temporal y definitivamente fallido, identidad correcta y mismatch, Connect, Verify,
  Disconnect, Reconnect, cambio de cuenta confirmado y cancelado, duplicado en proyecto y
  proyecto distinto, cuentas/proyectos inactivos, almacén no disponible, reinicio durante
  OAuth, ausencia de secretos en base de datos, logs y frontend/storage, e independencia del
  núcleo de Accounts).
- **FR-052**: `quickstart.md` DEBE incluir una validación manual contra una cuenta Instagram
  Professional real propia o de prueba, cubriendo: Meta App configurada, `Account` Instagram
  local, `Connect Instagram`, consentimiento real, estado `Connected`, ID y username correctos,
  credencial solo en el keyring, reinicio con conexión conservada, `Verify connection`,
  renovación real cuando sea comprobable sin riesgo, `Disconnect`, credencial eliminada del
  keyring, `Account`/publicaciones preservadas y `Reconnect`. No DEBE publicarse contenido
  real.

### Key Entities *(include if feature involves data)*

- **Instagram Connection**: vínculo entre una `Account` de plataforma Instagram y una cuenta
  Instagram Professional real. Atributos no sensibles: `Account` a la que pertenece (máximo
  una conexión por `Account`), proyecto (para la unicidad), Instagram account ID (identidad
  autoritativa), username, tipo de cuenta, URL de foto de perfil opcional, estado
  (`Connected` / `Reconnect required`; la ausencia equivale a `Not connected`), fecha de
  conexión, fecha de última verificación y referencia opaca a la credencial. Un Instagram
  account ID solo puede vincularse a una `Account` por proyecto.
- **Credencial de Instagram**: token(s) de acceso y su caducidad según el modelo oficial de
  Meta. Vive solo en el almacén seguro del sistema operativo, localizada mediante la
  referencia opaca; nunca en la base de datos ni expuesta a la interfaz.
- **Intento de autorización pendiente**: estado efímero en memoria de una autorización
  iniciada: `Account` destino, `state`, caducidad y, si aplica, la identidad y credenciales
  nuevas a la espera de confirmación de cambio de cuenta. De un solo uso; no se persiste.
- **Configuración de la Meta App**: identificador y secreto de la aplicación de Meta y
  redirect URI, cargados desde configuración local no versionada; distinta de las
  credenciales de cada cuenta.
- **Account** (existente, Feature 002): no cambia su modelo ni su esquema; su plataforma
  determina si puede tener conexión de Instagram.
- **Publication** (existente, Feature 004): no cambia; la conexión, reconexión o desconexión no
  la afecta.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real de `quickstart.md` (`Account` Instagram
  local → `Connect Instagram` → login y consentimiento oficiales → identidad Professional
  verificada → reiniciar → seguir `Connected` → `Verify connection` → `Disconnect` →
  `Reconnect`) sin editar archivos de datos ni la base de datos a mano.
- **SC-002**: Desde que el usuario envía en AutoPublisher la redirect URL pegada
  correctamente hasta que la cuenta aparece como `Connected` transcurren menos de 10 segundos
  en condiciones normales de red. No se mide desde el consentimiento en Instagram, porque el
  flujo incluye una acción manual intermedia (copiar y pegar la URL).
- **SC-003**: En el 100 % de las conexiones, la base de datos, los logs, los mensajes de error
  y el almacenamiento del navegador contienen 0 tokens, códigos de autorización, valores
  `state` o app secrets, y las respuestas de la API contienen 0 de estos valores salvo el
  `state` dentro de la `authorization_url` (FR-026); el frontend descarta la redirect URL
  pegada tras enviarla (verificado por tests automatizados y por inspección manual en el
  quickstart).
- **SC-004**: El 100 % de las conexiones válidas sobreviven a un reinicio completo de la
  aplicación sin pedir una nueva autorización.
- **SC-005**: Tras desconectar, el almacén seguro contiene 0 credenciales de esa `Account` y la
  `Account` y el 100 % de sus publicaciones siguen existiendo sin cambios.
- **SC-006**: El 100 % de las respuestas de autorización con `state` inválido, reutilizado,
  caducado o de otra `Account` se rechazan sin modificar ninguna cuenta.
- **SC-007**: 0 cuentas no Professional quedan conectadas, 0 cambios de cuenta Instagram se
  producen sin confirmación explícita y 0 cuentas Instagram quedan vinculadas a dos `Account`
  del mismo proyecto.
- **SC-008**: 0 errores temporales de red provocan un paso a `Reconnect required`.
- **SC-009**: Cada error listado en FR-043 produce un mensaje comprensible que indica qué ha
  pasado y qué puede hacer el usuario, dejando la cuenta en un estado coherente.
- **SC-010**: La suite de tests automatizados de la feature se ejecuta completa sin acceso a
  Internet, a Meta real ni al keyring real, y el núcleo común de Accounts no contiene ninguna
  referencia a Instagram.

## Assumptions

- **Alcance**: esta feature solo conecta, mantiene, verifica y desconecta cuentas Instagram.
  Quedan fuera: publicación de imágenes, Reels, vídeos, Stories y carousels, media containers,
  hosting temporal de media, `InstagramPublisher`, scheduler específico de Instagram,
  comentarios, mensajes, insights, analytics, etiquetado, colaboraciones, música, filtros y
  edición/borrado remoto.
- **Decisiones diferidas al plan**: endpoints, redirect URI local, PKCE, intercambio y
  renovación de tokens, caducidades, versión de Graph API, ubicación de la configuración de
  Meta, duración y purga de intentos pendientes, política de revocación remota y garantía de
  unicidad en la persistencia. Todas se verificarán contra la documentación oficial vigente de
  Meta.
- **Paralelismo con YouTube**: salvo donde Instagram exija otra cosa, se reutilizan las
  decisiones de producto de la Feature 005 (estados, unicidad por proyecto incluyendo cuentas
  inactivas, misma cuenta permitida en proyectos distintos, primera conexión sin paso extra de
  confirmación, confirmación solo ante cambio de identidad, desactivar no desconecta,
  intentos pendientes del orden de 10 minutos en memoria, configuración leída en cada operación
  que la necesita). Las decisiones de protocolo de Google NO se reutilizan automáticamente.
- **Mismatch en verificación**: si `Verify connection` devuelve otro ID, la política por
  defecto es pasar a `Reconnect required` (como en YouTube) y exigir una reconexión con
  confirmación explícita para cambiar de cuenta.
- **Usuario y entorno**: un único usuario local con una cuenta Instagram Professional propia,
  una Meta App propia y un navegador en la misma máquina que AutoPublisher.
- **App Review / Development Mode**: para el desarrollo local se prioriza usar la cuenta
  Instagram Professional propia como tester/role autorizado de la Meta App. Durante el plan y
  la validación real se comprobará qué permisos pueden utilizarse actualmente en Development
  Mode sin App Review. Si Meta exige App Review/Advanced Access para alguno de los permisos
  requeridos incluso en el flujo real de prueba, se documentará y se detendrá la validación
  correspondiente. AutoPublisher nunca intentará eludir App Review ni las restricciones de
  Meta.
- **Dependencias**: reutiliza `Project` y `Account` (Feature 002), `Publication` (Feature 004)
  sin cambios, el almacén seguro de credenciales y los patrones de conexión de la Feature 005,
  el formato estructurado de errores, las migraciones existentes y la vista de cuentas del
  frontend con puntos de extensión neutrales por plataforma.
