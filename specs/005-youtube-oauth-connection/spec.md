# Feature Specification: Conexión segura de cuentas de YouTube mediante OAuth 2.0

**Feature Branch**: `005-youtube-oauth-connection`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "Crear la Feature 005 de AutoPublisher: conexión segura de cuentas de YouTube mediante OAuth 2.0. Permitir que una Account existente de plataforma YouTube se conecte realmente con un canal de YouTube del usuario mediante autorización en el navegador, identificando el canal por su channel ID, guardando los tokens únicamente en el almacén seguro de credenciales del sistema operativo (SQLite solo guarda una referencia no secreta), con estados Not connected / Connected / Reconnect required, refresh de credenciales, desconexión, reconexión, protección contra conectar el canal equivocado o un canal ya vinculado a otra Account del proyecto, y reglas para proyectos y cuentas inactivos. Sin subida ni publicación de vídeos, scheduler, PublicationAttempt, retries ni OAuth de otras plataformas."

## Contexto

Hasta ahora una `Account` (Feature 002) de AutoPublisher es solo un registro local: una
plataforma, un handle y un nombre visible. Nada la une a una cuenta real de la red social.

Esta feature introduce la primera **conexión real** con una plataforma: una `Account` de
plataforma YouTube puede vincularse, mediante la autorización OAuth 2.0 de Google en el
navegador del usuario, con un canal de YouTube concreto. AutoPublisher identifica el canal
autorizado, guarda de forma segura las credenciales necesarias para actuar en su nombre más
adelante y muestra en la interfaz qué canal real está vinculado.

Ejemplo:

`YouTube @CyberChannel` → `Connect` → autorización en Google → canal identificado
("Cyber Channel", `UC…`) → `Connected`

El objetivo es dejar la conexión lista para que una feature futura pueda subir vídeos sin
volver a pedir login. **En esta feature no se sube ni se publica nada.**

La conexión no crea un sistema paralelo de cuentas: siempre se vincula a una `Account`
existente cuya plataforma es YouTube. Las cuentas de Instagram, TikTok, X, Threads y Telegram
siguen funcionando exactamente como hasta ahora, sin conexión.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login propio.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conectar una cuenta YouTube con su canal real (Priority: P1)

Como usuario, quiero pulsar `Connect` en una cuenta YouTube de un proyecto, autorizar a
AutoPublisher en la página de Google con mi cuenta y volver a AutoPublisher viendo el canal
real vinculado, para que la aplicación quede preparada para publicar en ese canal.

**Why this priority**: es el núcleo de la feature; sin una primera conexión no existe nada
que mantener, refrescar ni desconectar.

**Independent Test**: con la configuración OAuth local preparada, en un proyecto activo abrir
la cuenta activa `YouTube @CyberChannel` (estado `Not connected`), pulsar `Connect`, completar
la autorización en Google y comprobar que la cuenta aparece como `Connected`, mostrando el
título y el channel ID del canal autorizado, y que la base de datos local no contiene ningún
token.

**Acceptance Scenarios**:

1. **Given** una cuenta YouTube activa de un proyecto activo en estado `Not connected` y la
   configuración OAuth local presente, **When** el usuario pulsa `Connect`, **Then** se abre
   en su navegador la página de autorización de Google para AutoPublisher, solicitando
   únicamente los permisos necesarios y acceso renovable (offline).
2. **Given** una autorización iniciada, **When** el usuario elige su cuenta de Google y
   concede los permisos, **Then** AutoPublisher recibe la respuesta, comprueba que corresponde
   a una autorización que él mismo inició para esa cuenta, obtiene las credenciales, consulta
   YouTube para identificar el canal autorizado y lo vincula con la cuenta.
3. **Given** una conexión completada, **When** el usuario vuelve a AutoPublisher, **Then** la
   cuenta se muestra como `Connected` con, al menos, el título del canal y su channel ID, y la
   fecha de conexión; cuando esté disponible, también su miniatura y su handle/URL pública.
4. **Given** una conexión completada, **When** se inspeccionan la base de datos local, los
   logs y las respuestas que recibe la interfaz, **Then** ninguno contiene access tokens,
   refresh tokens ni el client secret; la base de datos solo contiene información pública del
   canal y una referencia no secreta a las credenciales.
5. **Given** una cuenta conectada, **When** se reinician el backend y el frontend, **Then** la
   cuenta sigue apareciendo como `Connected` con el mismo canal, sin pedir de nuevo la
   autorización.
6. **Given** una cuenta de plataforma distinta de YouTube (Instagram, TikTok, X, Threads o
   Telegram), **When** el usuario la consulta, **Then** no se ofrece `Connect` ni ningún
   estado de conexión, y si se intenta iniciar la conexión igualmente se rechaza indicando que
   solo las cuentas YouTube pueden conectarse.
7. **Given** que falta la configuración OAuth local de AutoPublisher, **When** el usuario
   pulsa `Connect`, **Then** no se abre el navegador y el usuario recibe un mensaje claro que
   indica que la integración con YouTube no está configurada y dónde está la documentación
   para configurarla.

---

### User Story 2 - Manejar cancelaciones y errores de la autorización (Priority: P1)

Como usuario, quiero que cualquier fallo o cancelación durante la autorización me muestre un
mensaje comprensible y deje mi cuenta en un estado coherente, para poder reintentar sin
quedarme con conexiones a medias.

**Why this priority**: OAuth tiene muchos caminos de fallo (rechazo, respuestas
manipuladas, Google o YouTube inaccesibles); sin manejarlos la conexión no es segura ni
fiable.

**Independent Test**: simulando (sin Google real) rechazo del consentimiento, una respuesta
con `state` desconocido, un intercambio de código fallido, YouTube inaccesible y una cuenta de
Google sin canal, comprobar en cada caso que el usuario ve un mensaje claro, que la cuenta
conserva exactamente su estado anterior y que no queda ninguna credencial almacenada.

**Acceptance Scenarios**:

1. **Given** una autorización iniciada, **When** el usuario cancela o rechaza el
   consentimiento en Google, **Then** AutoPublisher informa de que la conexión se canceló, no
   se guarda ninguna credencial y la cuenta mantiene su estado previo.
2. **Given** una respuesta de autorización cuyo `state` no corresponde a ninguna autorización
   pendiente iniciada por AutoPublisher (desconocido, ya usado, caducado o de otra cuenta),
   **When** llega, **Then** se rechaza sin intercambiar ningún código ni modificar ninguna
   cuenta, y el usuario ve un mensaje de autorización inválida o caducada.
3. **Given** una respuesta de autorización mal formada (sin código, sin `state` o con un error
   no reconocido), **When** llega, **Then** se rechaza con un mensaje comprensible y sin
   cambios en la cuenta.
4. **Given** una respuesta válida, **When** el intercambio del código por credenciales falla,
   **Then** el usuario ve un mensaje claro indicando que Google no completó la autorización y
   que puede reintentar, sin credenciales guardadas.
5. **Given** credenciales obtenidas, **When** YouTube no responde o no está accesible al
   identificar el canal, **Then** la conexión no se completa, las credenciales obtenidas se
   descartan y el usuario ve un mensaje indicando que no se pudo contactar con YouTube.
6. **Given** credenciales obtenidas, **When** la cuenta de Google autorizada no tiene ningún
   canal de YouTube válido, **Then** la conexión no se completa, las credenciales se
   descartan y el usuario ve un mensaje indicando que esa cuenta de Google no tiene canal de
   YouTube.
7. **Given** credenciales obtenidas, **When** no puede determinarse de forma inequívoca un
   único canal efectivo sobre el que actuarán (por ejemplo, la consulta devuelve varios
   canales), **Then** la conexión no se completa, no se elige ningún canal arbitrariamente,
   las credenciales se descartan y el usuario ve un mensaje claro indicando que debe
   seleccionar/configurar correctamente el canal de YouTube durante la autorización y volver
   a intentarlo.
8. **Given** cualquiera de los errores anteriores, **When** se muestra al usuario o se
   registra en logs, **Then** sigue el formato estructurado de errores existente y no contiene
   tokens, códigos de autorización, client secret ni detalles internos sensibles.

---

### User Story 3 - Desconectar una cuenta YouTube (Priority: P1)

Como usuario, quiero desconectar una cuenta YouTube para que AutoPublisher deje de usar mi
canal y elimine las credenciales sensibles que guarda localmente, sin perder la cuenta ni sus
publicaciones.

**Why this priority**: eliminar de forma fiable las credenciales locales es parte
indispensable de manejar credenciales reales de forma segura.

**Independent Test**: conectar una cuenta (con fakes), desconectarla y comprobar que el
almacén seguro ya no contiene sus credenciales, que la referencia local ha desaparecido, que
la cuenta y sus publicaciones siguen existiendo y que la cuenta se muestra como
`Not connected`.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` o `Reconnect required`, **When** el usuario pulsa
   `Disconnect` y confirma, **Then** se eliminan sus credenciales del almacén seguro, se
   elimina la referencia local a ellas y la cuenta vuelve a mostrarse como `Not connected`.
2. **Given** una desconexión, **When** termina, **Then** la cuenta sigue existiendo en su
   proyecto con su plataforma, handle, nombre visible y estado activo/inactivo intactos, y
   todas sus publicaciones existentes se conservan sin cambios.
3. **Given** una desconexión, **When** termina, **Then** AutoPublisher NO revoca
   automáticamente el permiso en Google (la revocación afecta al permiso completo concedido a
   la aplicación y podría romper otras conexiones que usen la misma identidad de Google), la
   eliminación local se completa sin depender de Google y el usuario es informado de que, si
   quiere retirar por completo el permiso concedido a AutoPublisher, puede hacerlo
   manualmente desde la configuración de seguridad de su cuenta de Google.
4. **Given** una cuenta inactiva o una cuenta de un proyecto inactivo que está conectada,
   **When** el usuario la desconecta, **Then** la desconexión se permite y elimina las
   credenciales igual que en una cuenta activa.
5. **Given** una cuenta ya `Not connected`, **When** se solicita desconectarla, **Then** la
   operación es idempotente: no da error y la cuenta sigue `Not connected`.

---

### User Story 4 - Mantener la conexión válida y detectar cuándo hay que reconectar (Priority: P2)

Como usuario, quiero que AutoPublisher pueda seguir obteniendo acceso válido a mi canal cuando
el acceso temporal caduque, y que me avise claramente cuando el acceso se haya perdido
definitivamente, para saber cuándo debo volver a autorizar.

**Why this priority**: es lo que permitirá a la siguiente feature publicar sin pedir login;
no es necesario para la primera conexión, pero sí para que la conexión sea útil.

**Independent Test**: con un fake de Google, forzar la caducidad del acceso temporal y
comprobar que AutoPublisher obtiene uno nuevo con la credencial renovable y persiste cualquier
actualización; después simular una credencial renovable revocada y comprobar que la cuenta
pasa a `Reconnect required`.

**Acceptance Scenarios**:

1. **Given** una cuenta `Connected` cuyo acceso temporal ha caducado, **When** AutoPublisher
   necesita credenciales válidas para ella, **Then** las renueva usando la credencial
   renovable sin intervención del usuario, persiste en el almacén seguro cualquier credencial
   actualizada y la cuenta sigue `Connected`.
2. **Given** una cuenta `Connected` cuya credencial renovable ha sido revocada, ha caducado o
   Google la rechaza definitivamente, **When** AutoPublisher intenta renovar el acceso,
   **Then** la cuenta pasa a `Reconnect required` y la interfaz lo muestra con la acción
   `Reconnect`.
3. **Given** una cuenta `Connected`, **When** la renovación falla por un problema transitorio
   (sin conexión a Internet, Google no disponible), **Then** la cuenta NO pasa a
   `Reconnect required`; el usuario ve un error de conectividad y la cuenta sigue `Connected`.
4. **Given** una cuenta `Connected`, **When** el usuario solicita verificar la conexión,
   **Then** AutoPublisher obtiene credenciales válidas (renovándolas si hace falta) sin pedir
   login, vuelve a consultar el canal y muestra el resultado; si la información pública del
   canal (título, miniatura, handle) ha cambiado, se actualiza.
5. **Given** una cuenta `Connected` cuyas credenciales ya no existen en el almacén seguro
   (borradas externamente), **When** AutoPublisher las necesita, **Then** la cuenta pasa a
   `Reconnect required` en lugar de producir un error interno.
6. **Given** una cuenta en `Reconnect required`, **When** se consulta, **Then** sigue siendo
   una cuenta normal de AutoPublisher: conserva su estado activo/inactivo, sus datos y sus
   publicaciones.

---

### User Story 5 - Reconectar y proteger contra el canal equivocado (Priority: P2)

Como usuario, quiero poder volver a autorizar una cuenta desconectada o que requiere
reconexión, con la seguridad de que AutoPublisher no sustituirá en silencio el canal vinculado
por otro distinto.

**Why this priority**: la reconexión es el camino de recuperación de `Reconnect required`, y
la protección frente al canal equivocado evita publicar en el futuro en un canal no deseado.

**Independent Test**: con fakes, reconectar una cuenta con el mismo canal y comprobar que las
nuevas credenciales sustituyen a las anteriores; después reconectar devolviendo otro channel
ID y comprobar que no se sustituye nada hasta que el usuario confirma explícitamente, y que si
cancela la conexión original queda intacta.

**Acceptance Scenarios**:

1. **Given** una cuenta `Not connected` (por ejemplo, tras desconectarla), **When** el usuario
   pulsa `Connect` y completa la autorización, **Then** la cuenta vuelve a `Connected` con el
   canal autorizado.
2. **Given** una cuenta `Reconnect required` o `Connected`, **When** el usuario pulsa
   `Reconnect` y autoriza el **mismo** canal (mismo channel ID), **Then** las nuevas
   credenciales sustituyen a las anteriores, se eliminan las antiguas del almacén seguro y la
   cuenta queda `Connected`.
3. **Given** una cuenta con un canal vinculado (`Connected` o `Reconnect required`), **When**
   la nueva autorización devuelve un channel ID **distinto**, **Then** no se modifica la
   conexión existente; el usuario ve una advertencia clara con el canal actual y el nuevo
   (título y channel ID de ambos) y debe elegir explícitamente entre sustituir o cancelar.
4. **Given** la advertencia de canal distinto, **When** el usuario confirma la sustitución,
   **Then** la cuenta queda vinculada al nuevo canal con las nuevas credenciales y las
   credenciales del canal anterior se eliminan.
5. **Given** la advertencia de canal distinto, **When** el usuario cancela, o no responde
   dentro del tiempo de validez de la autorización pendiente, **Then** las nuevas credenciales
   se descartan y la conexión anterior queda exactamente como estaba.
6. **Given** el flujo de conexión, **When** se muestra el resultado o la advertencia, **Then**
   queda claramente identificada la cuenta de AutoPublisher afectada (plataforma, handle,
   nombre visible y proyecto) junto al canal autorizado.

---

### User Story 6 - Evitar el mismo canal en dos cuentas del proyecto (Priority: P2)

Como usuario, quiero que AutoPublisher me impida vincular por error el mismo canal de YouTube
a dos cuentas distintas del mismo proyecto, para no duplicar publicaciones en el futuro.

**Why this priority**: protege la integridad de las futuras publicaciones; depende de que la
conexión básica ya funcione.

**Independent Test**: con fakes, conectar `YouTube @CyberChannel` al canal `UC123`, intentar
conectar otra cuenta YouTube del mismo proyecto devolviendo también `UC123` y comprobar que se
rechaza indicando qué cuenta lo tiene vinculado, sin guardar credenciales para la segunda.

**Acceptance Scenarios**:

1. **Given** una cuenta del proyecto ya vinculada al canal `UC123`, **When** otra cuenta del
   mismo proyecto completa una autorización que devuelve `UC123`, **Then** la vinculación se
   rechaza, las nuevas credenciales se descartan y el usuario ve qué cuenta del proyecto tiene
   ya ese canal y que debe desconectarla primero si quiere moverlo.
2. **Given** el canal `UC123` vinculado a una cuenta del proyecto A, **When** una cuenta del
   proyecto B lo conecta, **Then** se permite (la restricción es por proyecto).
3. **Given** el canal `UC123` vinculado a una cuenta que después se desconecta, **When** otra
   cuenta del mismo proyecto lo conecta, **Then** se permite.
4. **Given** dos operaciones de conexión simultáneas que devuelven el mismo canal para dos
   cuentas del mismo proyecto, **When** ambas intentan completarse, **Then** como máximo una
   se completa; la otra se rechaza con el conflicto anterior.

---

### User Story 7 - Respetar proyectos y cuentas inactivos (Priority: P3)

Como usuario, quiero que una cuenta inactiva o de un proyecto inactivo muestre su estado de
conexión pero no permita iniciar nuevas autorizaciones, aunque sí desconectarla, para
mantener la coherencia con el resto de la aplicación sin impedir retirar credenciales.

**Why this priority**: es una regla de coherencia sobre flujos ya cubiertos por historias
anteriores.

**Independent Test**: desactivar una cuenta conectada, comprobar que sigue mostrando su canal
y estado, que `Connect`/`Reconnect` no están disponibles y se rechazan si se fuerzan, y que
`Disconnect` funciona; repetir con el proyecto desactivado.

**Acceptance Scenarios**:

1. **Given** una cuenta YouTube inactiva, o una cuenta activa de un proyecto inactivo,
   **When** el usuario la consulta, **Then** ve su estado de conexión y el canal vinculado
   si lo hay.
2. **Given** esa misma cuenta, **When** se intenta iniciar `Connect` o `Reconnect`, **Then**
   la acción no está disponible en la interfaz y, si se fuerza, se rechaza indicando que la
   cuenta o el proyecto deben reactivarse primero.
3. **Given** una autorización iniciada mientras la cuenta y el proyecto estaban activos,
   **When** la cuenta o el proyecto se desactivan antes de que la respuesta de Google llegue,
   **Then** la respuesta se rechaza, no se guardan credenciales y la cuenta mantiene su
   estado previo.
4. **Given** una cuenta conectada que se desactiva, **When** se desactiva, **Then** su
   conexión NO se elimina automáticamente; sigue mostrando su canal y puede desconectarse.

---

### Edge Cases

- **Configuración OAuth ausente o incompleta**: `Connect`/`Reconnect` informan de que la
  integración no está configurada; las cuentas ya conectadas siguen mostrando su estado y
  pueden desconectarse (la eliminación local de credenciales no depende de la configuración).
- **Desconectar con el almacén seguro no disponible**: la desconexión falla con un error
  claro y la conexión se conserva (sigue mostrándose con su estado) hasta que pueda
  reintentarse con el almacén disponible.
- **Almacén seguro de credenciales no disponible** (por ejemplo, el sistema no ofrece un
  servicio de secretos o está bloqueado): la conexión no se completa y el usuario recibe un
  mensaje claro; AutoPublisher NUNCA recurre a guardar los tokens en la base de datos, en
  archivos en claro ni en logs como alternativa.
- **Fallo al guardar credenciales tras identificar el canal**: no se registra la conexión en
  la base de datos; nunca queda una conexión en la base de datos sin credenciales
  utilizables.
- **Referencia local sin credenciales en el almacén** (borradas fuera de AutoPublisher): la
  cuenta pasa a `Reconnect required` cuando se detecta.
- **Credenciales huérfanas en el almacén**: si una operación falla después de haber guardado
  un secreto (por ejemplo, al registrar la conexión en la base de datos), AutoPublisher
  intenta eliminar ese secreto inmediatamente. Si esa eliminación también falla porque el
  almacén seguro no está disponible, puede quedar una entrada huérfana en el almacén, sin
  referencia desde la base de datos. AutoPublisher no puede usarla ni la detecta ni limpia
  después; el usuario puede borrarla con las herramientas del sistema (servicio
  `autopublisher.youtube`). Esto nunca deja una conexión registrada sin credenciales.
- **Autorización abandonada**: si el usuario cierra la pestaña de Google sin completar, la
  autorización pendiente caduca tras un tiempo limitado y la cuenta conserva su estado; el
  usuario puede volver a pulsar `Connect`.
- **Varias autorizaciones pendientes para la misma cuenta**: solo la más reciente puede
  completarse; las anteriores quedan invalidadas.
- **Respuesta reutilizada**: una respuesta de autorización ya procesada no puede procesarse
  de nuevo.
- **Reinicio de AutoPublisher con una autorización en curso**: la autorización pendiente se
  pierde y su respuesta posterior se rechaza como caducada; el usuario debe reiniciar el
  flujo.
- **Google no concede acceso renovable** (no devuelve credencial renovable): la conexión no se
  completa, porque no podría mantenerse sin pedir login de nuevo; el usuario ve un mensaje
  indicando que debe volver a autorizar concediendo acceso completo.
- **Permisos concedidos parcialmente**: si el usuario no concede todos los permisos
  solicitados, la conexión no se completa y se explica qué permiso falta.
- **Cuenta de Google que administra varios canales**: no se asume que una cuenta de Google
  representa un único canal. AutoPublisher debe identificar de forma inequívoca el canal
  efectivo sobre el que actuarán las credenciales obtenidas; si existe ambigüedad, nunca
  selecciona el primero devuelto ni ningún otro arbitrariamente: la conexión no se completa y
  se pide al usuario que seleccione/configure correctamente el canal y reintente. Cuando se
  identifica un único canal, la interfaz muestra cuál es para que el usuario lo verifique.
- **El handle de la Account no coincide con el del canal**: no bloquea la conexión ni
  modifica la Account; la interfaz muestra ambos (handle de la Account y datos del canal)
  para que el usuario detecte discrepancias.
- **Cambio de título o handle del canal en YouTube**: no rompe la conexión, porque la
  identidad es el channel ID; la información pública se actualiza al verificar o reconectar.
- **Verificación que devuelve un channel ID distinto del vinculado**: la cuenta pasa a
  `Reconnect required` y se informa al usuario; nunca se cambia el canal vinculado sin su
  confirmación.
- **Cuentas de otras plataformas**: no tienen estado de conexión; cualquier operación de
  conexión sobre ellas se rechaza como plataforma no soportada.
- **Cuenta inexistente**: cualquier operación de conexión devuelve un error de cuenta no
  encontrada.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance y vinculación con Accounts

- **FR-001**: El sistema DEBE permitir vincular una `Account` existente de plataforma YouTube
  con un canal de YouTube real mediante autorización OAuth 2.0 en el navegador del usuario,
  sin crear un sistema de cuentas paralelo.
- **FR-002**: El sistema DEBE rechazar cualquier operación de conexión, reconexión,
  verificación o desconexión sobre una cuenta inexistente o sobre una cuenta cuya plataforma
  no sea YouTube, con un error estructurado comprensible.
- **FR-003**: Cada cuenta YouTube DEBE tener como máximo una conexión vinculada a un único
  canal en cada momento.

#### Estados de conexión

- **FR-004**: Una cuenta YouTube DEBE encontrarse en uno de estos estados de conexión:
  `Not connected` (sin conexión ni credenciales), `Connected` (canal vinculado y credenciales
  utilizables) o `Reconnect required` (canal vinculado conocido, pero sus credenciales ya no
  permiten obtener acceso sin una nueva autorización).
- **FR-005**: Los estados de conexión NO DEBEN aplicarse a cuentas de otras plataformas, que
  siguen funcionando como antes.
- **FR-006**: El estado de conexión DEBE ser independiente del estado activo/inactivo de la
  cuenta y del proyecto.

#### Flujo de autorización

- **FR-007**: Al iniciar una conexión, el sistema DEBE abrir (o proporcionar para abrir) la
  página de autorización de Google en el navegador del usuario, solicitando acceso renovable
  (offline) con consentimiento explícito en cada conexión o reconexión, de modo que Google
  emita siempre una credencial renovable nueva aunque los permisos ya se hubieran concedido
  antes (por ejemplo, tras una desconexión que no revoca el permiso en Google), y únicamente
  los permisos mínimos necesarios para identificar el canal y, en la
  siguiente feature, subir vídeos. La combinación exacta de permisos se verificará en el plan
  contra la documentación oficial vigente.
- **FR-008**: Cada autorización iniciada DEBE asociarse a una cuenta concreta y protegerse
  con un valor `state` (o mecanismo equivalente) impredecible, de un solo uso y con caducidad
  limitada; el sistema DEBE rechazar sin efectos cualquier respuesta cuyo `state` sea
  desconocido, ya usado, caducado o no corresponda a la cuenta.
- **FR-009**: El sistema DEBE validar la respuesta de autorización antes de usarla y
  distinguir: consentimiento concedido, cancelado/rechazado por el usuario, error de Google y
  respuesta mal formada.
- **FR-009a**: Además de `state`, cada autorización DEBE usar PKCE con método `S256`: el
  sistema DEBE generar para cada autorización un `code_verifier` criptográficamente aleatorio
  y enviar su `code_challenge` derivado, y DEBE presentar ese `code_verifier` al intercambiar
  el código. El `code_verifier` DEBE ser efímero, estar asociado únicamente a esa autorización
  pendiente, descartarse al completarla, cancelarla o caducar, y NUNCA almacenarse en la base
  de datos, en logs ni en respuestas al frontend.
- **FR-010**: Tras una autorización válida, el sistema DEBE obtener las credenciales,
  consultar YouTube para identificar el canal autorizado y solo entonces completar la
  vinculación.
- **FR-011**: El sistema NO DEBE completar una conexión si no obtiene una credencial
  renovable, si faltan permisos necesarios, si la cuenta de Google no tiene un canal de
  YouTube válido o si no puede determinarse un único canal efectivo (FR-016a); en esos casos
  DEBE descartar las credenciales obtenidas.
- **FR-012**: Ninguna autorización fallida, cancelada o rechazada DEBE modificar el estado de
  conexión previo de la cuenta ni dejar credenciales almacenadas.
- **FR-013**: El sistema DEBE rechazar el inicio de una conexión o reconexión, y el
  completado de una autorización pendiente, cuando la cuenta o su proyecto estén inactivos.
- **FR-014**: El sistema DEBE informar con un mensaje claro, sin abrir el navegador, cuando
  falte la configuración OAuth local de AutoPublisher, indicando cómo configurarla. El estado
  de conexión de una cuenta YouTube DEBE indicar (sin datos sensibles) si la configuración
  OAuth está disponible, para que la interfaz no inicie la autorización si no lo está.

#### Identidad del canal

- **FR-015**: Al completar una conexión, el sistema DEBE persistir de forma no sensible, como
  mínimo: el channel ID de YouTube, el título del canal, la fecha de conexión y el estado de
  conexión; y, cuando YouTube los proporcione, la miniatura pública y el handle/URL
  personalizada del canal.
- **FR-016**: El channel ID DEBE ser la identidad autoritativa del canal; el sistema NO DEBE
  identificar el canal únicamente por su título o handle.
- **FR-016a**: El sistema NO DEBE asumir que una cuenta de Google representa un único canal
  de YouTube. Tras completar la autorización, DEBE identificar de forma inequívoca el channel
  ID efectivo sobre el que actuarán esas credenciales y NUNCA DEBE seleccionar arbitrariamente
  el primer canal (ni ningún otro) cuando exista ambigüedad. Si no puede determinarse un único
  canal efectivo, la conexión NO DEBE completarse y el usuario DEBE recibir un mensaje claro
  indicando que debe seleccionar/configurar correctamente el canal de YouTube y volver a
  intentarlo.
- **FR-017**: La conexión NO DEBE modificar el handle ni el nombre visible de la `Account`.

#### Protección contra el canal equivocado y duplicados

- **FR-018**: Si una cuenta con un canal ya vinculado (`Connected` o `Reconnect required`)
  completa una autorización que devuelve un channel ID distinto, el sistema NO DEBE sustituir
  la conexión; DEBE presentar una advertencia con el canal actual y el nuevo (título y
  channel ID) y requerir una confirmación explícita del usuario para sustituirla.
- **FR-019**: Si el usuario cancela la sustitución, o no confirma dentro de un tiempo
  limitado, el sistema DEBE descartar las nuevas credenciales y dejar intacta la conexión
  anterior. Las credenciales pendientes de confirmación NO DEBEN persistirse en la base de
  datos.
- **FR-020**: Dentro de un mismo proyecto, un mismo channel ID NO DEBE estar vinculado a la
  vez a dos cuentas distintas, sean activas o inactivas; un intento de vinculación que
  violaría esta regla DEBE rechazarse indicando qué cuenta tiene ya el canal. Esta garantía
  DEBE mantenerse también ante operaciones concurrentes y DEBE estar respaldada por la capa de
  persistencia.
- **FR-021**: El mismo channel ID PUEDE vincularse a cuentas de proyectos distintos.

#### Credenciales y configuración

- **FR-022**: Las credenciales OAuth de cada cuenta (access token, refresh token y
  equivalentes) DEBEN almacenarse exclusivamente en el almacén seguro de credenciales del
  sistema operativo (o una abstracción equivalente adecuada para una aplicación local); la
  base de datos local SOLO PUEDE contener una referencia no secreta que permita localizarlas.
- **FR-023**: Las credenciales, los códigos de autorización y el client secret NUNCA DEBEN
  aparecer en la base de datos, en archivos versionados, en logs, en mensajes de error, en
  respuestas de la API al frontend ni en el almacenamiento del navegador.
- **FR-024**: Antes de guardar credenciales, el sistema DEBE comprobar que dispone de un
  almacén seguro adecuado. Si no existe, no es seguro, está bloqueado, no está disponible o
  falla, el sistema DEBE abortar la operación con un error comprensible y NO DEBE recurrir a
  ningún almacenamiento alternativo inseguro (por ejemplo, un archivo en claro).
- **FR-025**: La conexión DEBE registrarse en la base de datos únicamente si las credenciales
  se han guardado correctamente: nunca DEBE quedar una conexión válida en la base de datos sin
  credenciales utilizables. Si una operación falla después de guardar un secreto, el sistema
  DEBE intentar eliminarlo inmediatamente; si esa eliminación también falla por
  indisponibilidad del almacén seguro, puede quedar una entrada huérfana sin referencia y sin
  uso posible por AutoPublisher (ver Edge Cases). No se garantiza su detección ni limpieza
  posterior.
- **FR-026**: La configuración OAuth propia de AutoPublisher (client ID y client secret) DEBE
  cargarse desde configuración local no versionada y DEBE mantenerse separada de las
  credenciales de cada cuenta. El repositorio NO DEBE contener credenciales reales ni valores
  de ejemplo que puedan confundirse con secretos válidos.
- **FR-027**: DEBE existir documentación que explique cómo crear y configurar el proyecto de
  Google Cloud / YouTube Data API y la configuración local de AutoPublisher sin introducir
  secretos en el repositorio.

#### Renovación y verificación

- **FR-028**: El sistema DEBE ofrecer una capacidad interna para obtener credenciales válidas
  de una cuenta conectada, renovándolas con la credencial renovable cuando hayan caducado y
  persistiendo en el almacén seguro cualquier credencial actualizada.
- **FR-029**: Cuando Google rechace definitivamente la credencial renovable (revocada,
  caducada o inválida) o las credenciales falten en el almacén seguro, el sistema DEBE marcar
  la cuenta como `Reconnect required`. Los fallos transitorios de red o de disponibilidad NO
  DEBEN cambiar el estado de conexión.
- **FR-030**: El usuario DEBE poder verificar bajo demanda una conexión: el sistema obtiene
  credenciales válidas sin pedir login, vuelve a consultar el canal, actualiza su información
  pública y muestra el resultado. Si el channel ID devuelto difiere del vinculado, la cuenta
  DEBE pasar a `Reconnect required`.

#### Desconexión y reconexión

- **FR-031**: El usuario DEBE poder desconectar una cuenta YouTube en estado `Connected` o
  `Reconnect required`, también si la cuenta o el proyecto están inactivos. La desconexión
  DEBE eliminar las credenciales del almacén seguro y, solo después de eliminarlas
  correctamente, la referencia local, dejando la cuenta en `Not connected`. Si el almacén
  seguro no está disponible y no se pueden eliminar las credenciales, la desconexión DEBE
  fallar con un error claro (`credential_store_unavailable`) y conservar la conexión y su
  referencia para poder reintentar.
- **FR-032**: La desconexión NO DEBE eliminar la `Account`, modificar sus datos ni eliminar o
  modificar sus publicaciones. No se implementa la eliminación física de cuentas.
- **FR-033**: Al desconectar, el sistema NO DEBE revocar automáticamente el permiso OAuth en
  Google, porque la revocación afecta al permiso completo concedido a la aplicación para esa
  identidad de Google y podría invalidar otras conexiones que lo compartan. La desconexión
  DEBE completarse siempre de forma local, sin depender de Google, y la interfaz DEBE indicar
  al usuario cómo retirar manualmente el permiso desde su cuenta de Google si lo desea.
- **FR-034**: Desconectar una cuenta ya `Not connected` DEBE ser idempotente.
- **FR-035**: El usuario DEBE poder iniciar de nuevo el flujo de autorización sobre una cuenta
  `Not connected`, `Connected` o `Reconnect required` (si la cuenta y el proyecto están
  activos). Tras una reconexión con el mismo canal, las nuevas credenciales DEBEN sustituir a
  las anteriores, que se eliminan, y el canal DEBE volver a verificarse.

#### API e interfaz

- **FR-036**: La API DEBE permitir: consultar el estado de conexión y la información no
  sensible del canal de una cuenta YouTube; iniciar una conexión o reconexión; procesar y
  validar la respuesta de autorización; confirmar o cancelar una sustitución de canal;
  verificar la conexión; y desconectar. Ninguna respuesta DEBE incluir credenciales.
- **FR-037**: Todos los errores de esta feature DEBEN seguir el formato estructurado de
  errores existente, con códigos distinguibles al menos para: configuración ausente, cuenta
  inexistente, plataforma no soportada, cuenta o proyecto inactivos, autorización cancelada,
  `state` inválido o caducado, respuesta de autorización inválida, intercambio fallido,
  YouTube inaccesible, cuenta sin canal, canal efectivo ambiguo, permisos o acceso renovable
  insuficientes, reconexión requerida, canal ya vinculado a otra cuenta, sustitución de canal
  pendiente de confirmación y almacén seguro no disponible.
- **FR-038**: En la vista de cuentas, cada cuenta YouTube DEBE mostrar claramente su estado de
  conexión y, si existe, el canal vinculado (título y channel ID como mínimo); DEBE ofrecer
  `Connect` cuando esté `Not connected`, `Reconnect` cuando esté `Reconnect required` (y como
  acción secundaria cuando esté `Connected`) y `Disconnect` cuando tenga una conexión, respetando
  las reglas de cuentas y proyectos inactivos.
- **FR-039**: La interfaz DEBE mostrar los resultados y errores del flujo OAuth de forma
  comprensible para el usuario, incluyendo la advertencia de sustitución de canal con sus
  dos opciones explícitas.
- **FR-040**: La información no sensible de la conexión DEBE persistir en la base de datos
  local mediante una migración versionada, de forma que reiniciar backend y frontend conserve
  las conexiones válidas.

#### Calidad

- **FR-041**: Los tests automatizados NO DEBEN depender de Google real ni de acceso a
  Internet; DEBEN usar dobles (fakes/mocks) para OAuth, YouTube y el almacén seguro. La
  validación con Google real se documentará como procedimiento manual (`quickstart.md`), que
  DEBE incluir una comprobación específica con una cuenta de Google que administre varios
  canales, cuando exista una disponible para pruebas.

### Key Entities *(include if feature involves data)*

- **YouTube Connection (conexión de cuenta)**: vínculo entre una `Account` de plataforma
  YouTube y un canal real. Atributos no sensibles: cuenta a la que pertenece (como máximo una
  conexión por cuenta), channel ID (identidad autoritativa), título del canal, miniatura y
  handle/URL pública opcionales, estado (`Connected` / `Reconnect required`; la ausencia de
  conexión equivale a `Not connected`), fecha de conexión, fecha de última verificación y
  referencia no secreta a las credenciales. Un channel ID solo puede estar vinculado a una
  cuenta por proyecto.
- **Credenciales de cuenta**: secretos OAuth de una conexión (acceso temporal, credencial
  renovable y su caducidad). Viven solo en el almacén seguro del sistema operativo, localizados
  mediante la referencia de la conexión; nunca en la base de datos ni expuestos a la interfaz.
- **Autorización pendiente**: estado temporal de una autorización iniciada: cuenta destino,
  `state`, `code_verifier` de PKCE, caducidad y, si aplica, el canal y credenciales nuevos a
  la espera de confirmación de sustitución. Es efímera, de un solo uso y no se persiste en la base de datos.
- **Configuración OAuth de AutoPublisher**: client ID y client secret de la aplicación en
  Google Cloud, cargados desde configuración local no versionada; distinta de las
  credenciales de cada cuenta.
- **Account** (existente, Feature 002): no cambia su modelo de datos visible; su plataforma
  determina si puede tener conexión.
- **Publication** (existente, Feature 004): no cambia; la desconexión de una cuenta no afecta
  a sus publicaciones.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real descrito en `quickstart.md` (abrir
  proyecto activo → cuenta YouTube activa → `Connect` → autorizar en Google → volver y ver
  título y channel ID → reiniciar → seguir conectado → obtener credenciales válidas sin login
  → desconectar → comprobar que las credenciales han desaparecido y la cuenta existe →
  reconectar) sin editar archivos ni bases de datos a mano.
- **SC-002**: Desde que el usuario concede el permiso en Google, la cuenta aparece como
  conectada con su canal en AutoPublisher en menos de 10 segundos en condiciones normales de
  red.
- **SC-003**: En el 100 % de las conexiones, la base de datos, los logs y las respuestas
  enviadas a la interfaz contienen 0 tokens, códigos de autorización o client secrets
  (verificado por tests automatizados y por inspección manual en el quickstart).
- **SC-004**: El 100 % de las conexiones válidas sobreviven a un reinicio completo de la
  aplicación sin pedir una nueva autorización.
- **SC-005**: Tras desconectar, el almacén seguro contiene 0 credenciales de esa cuenta y la
  cuenta y el 100 % de sus publicaciones siguen existiendo sin cambios.
- **SC-006**: El 100 % de las respuestas de autorización con `state` inválido, reutilizado o
  caducado se rechazan sin modificar ninguna cuenta.
- **SC-007**: 0 sustituciones de canal se producen sin confirmación explícita del usuario, y
  0 canales quedan vinculados a dos cuentas del mismo proyecto.
- **SC-008**: Cada escenario de error listado en FR-037 produce un mensaje comprensible para
  el usuario, que indica qué ha pasado y qué puede hacer, y deja la cuenta en un estado
  coherente.
- **SC-009**: La suite de tests automatizados de la feature se ejecuta completa sin acceso a
  Internet ni a Google real.

## Assumptions

- **Alcance**: esta feature solo conecta, mantiene, verifica y desconecta cuentas YouTube.
  Quedan fuera: subida de vídeos (`videos.insert`), publicación de una `Publication`,
  scheduler, `PublicationAttempt`, retries, analytics, edición/borrado de vídeos remotos,
  thumbnails propias, playlists, comentarios, OAuth de otras plataformas, SaaS/multiusuario y
  sincronización automática de cuentas.
- **Decisiones diferidas al plan**: el tipo concreto de flujo OAuth para aplicación local, el
  mecanismo de callback local, las librerías, la combinación mínima exacta de permisos de
  YouTube, el almacén seguro concreto y su comportamiento en Linux, la garantía en base de
  datos de unicidad del canal por proyecto. Todas se decidirán en `/speckit-plan` usando la documentación oficial vigente de Google.
- **Primera conexión sin paso extra de confirmación**: cuando una cuenta `Not connected`
  completa la autorización (o una cuenta conectada reautoriza el mismo canal), la vinculación
  se completa directamente y el resultado muestra claramente el canal y la cuenta. La
  confirmación explícita solo se exige cuando el canal cambia respecto al vinculado. Si el
  canal resultante no es el deseado, el usuario puede desconectarlo inmediatamente.
- **Unicidad por proyecto incluyendo cuentas inactivas**: la regla de un canal por proyecto se
  aplica a toda cuenta con conexión (`Connected` o `Reconnect required`), activa o inactiva,
  para que reactivar una cuenta nunca produzca dos cuentas con el mismo canal. Es coherente
  con la Feature 002, donde las cuentas inactivas cuentan para la detección de duplicados.
- **Sin revocación automática al desconectar**: desconectar solo elimina las credenciales
  locales y la referencia. El permiso concedido en Google se retira, si el usuario lo desea,
  manualmente desde su cuenta de Google (decisión tomada en el plan, FR-033).
- **Desactivar no desconecta**: desactivar una cuenta o un proyecto conserva su conexión y
  credenciales; el usuario debe desconectar explícitamente si quiere eliminarlas.
- **Autorizaciones pendientes en memoria**: las autorizaciones pendientes y las sustituciones
  de canal a la espera de confirmación tienen una validez limitada (del orden de 10 minutos) y
  no sobreviven a un reinicio del backend.
- **Lectura de la configuración**: la configuración OAuth se lee en cada operación que la
  necesita, de modo que crearla o cambiarla no requiere reiniciar el backend.
- **Usuario y entorno**: un único usuario local que dispone de una cuenta de Google con un
  canal de YouTube, de un proyecto propio en Google Cloud con la YouTube Data API habilitada
  (en modo de pruebas es aceptable) y de un navegador en la misma máquina que AutoPublisher.
- **Dependencias**: reutiliza `Project` y `Account` (Feature 002), el formato estructurado de
  errores existente, las migraciones de base de datos existentes y la vista de cuentas del
  frontend. `Publication` (Feature 004) no se modifica.
