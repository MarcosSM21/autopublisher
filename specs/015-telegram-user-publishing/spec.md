# Feature Specification: Cuenta de usuario de Telegram y publicación en canales

**Feature Branch**: `015-telegram-user-publishing`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "Feature 015 — Telegram User Account & Publishing. Añadir Telegram usando una cuenta real de usuario mediante MTProto (no Bot API, sin bots), con Telethon estable como punto de partida. Conectar la cuenta normal del usuario (teléfono → código → 2FA opcional), guardar la sesión solo en el secure store del sistema operativo, Verify / Disconnect reales, listar los broadcast channels donde el usuario puede publicar y elegir uno como destino con identidad estable. Publicar texto, una imagen + caption o un vídeo + caption, con Publish Now y con el scheduler genérico existente (sin native scheduling de Telegram). Anti-duplicados aprovechando `random_id` sin reconciliación compleja; reutilizar resultado incierto genérico solo si hace falta. Conservar message ID y enlace solo si es fiable. Errores mapeados de forma sencilla, incluido FloodWait. Checkpoint real temprano V1a (cuenta) y V1b (publicación). Testing ligero con fakes en el límite Telegram/Telethon. Cero cambios en el núcleo salvo justificación. Fuera de alcance: Bot API, bots, grupos, supergrupos, forums/topics, DMs, albums, stories, polls, edición/borrado remoto, native scheduling, `send_as` avanzado, forwarding, scraping, lectura de chats, Features 016 y 017."

## Contexto

AutoPublisher ya tiene una arquitectura genérica de publicación (Features 004, 006, 007, 009,
011, 013, 014): `Account` por proyecto y plataforma, `Publication` con estados
`SCHEDULED` / `PUBLISHING` / `PUBLISHED` / `FAILED`, `PublicationAttempt` con origen
(`manual` / `scheduled`), fases, progreso, errores seguros, resultado remoto (identificador y
enlace opcionales), semántica genérica de resultado incierto, recuperación de intentos
interrumpidos al arrancar, un scheduler local genérico y un almacén seguro de credenciales del
sistema operativo. La plataforma `telegram` ya existe como valor válido de `Account`, pero no
tiene conexión ni publisher.

Esta feature añade Telegram **como cuenta de usuario real**, no como bot:

- el usuario conecta su cuenta normal de Telegram con su número de teléfono, el código que
  Telegram le envía y, si la tiene activada, su contraseña de verificación en dos pasos;
- AutoPublisher obtiene una sesión de usuario autorizada y la guarda únicamente en el almacén
  seguro del sistema operativo;
- el usuario elige uno de los **canales broadcast** donde tiene permiso para publicar;
- AutoPublisher publica en ese canal texto, una imagen con caption o un vídeo con caption,
  manualmente (`Publish now`) o mediante el scheduler genérico.

Flujo conceptual de publicación:

`Publication` → preflight genérico + preflight de Telegram → identidad de envío estable del
intento → envío del mensaje (Telegram transfiere el archivo si lo hay) → guardar message ID y,
si es fiable, enlace → `PUBLISHED` / intento `succeeded`.

Principios rectores:

- **Usuario real, nunca bot**: no se usa la Bot API ni se crea o exige un bot. La publicación
  debe verse en el canal igual que una publicación manual hecha con esa cuenta.
- **Pequeña y aislada**: reutilizar `Account`, `Publication`, `PublicationAttempt`, el
  protocolo de publisher, el scheduler, el almacén seguro y los errores genéricos. Preferir
  cero cambios en el núcleo; cualquier cambio en el núcleo debe justificarse en el plan.
- **Nunca duplicar deliberadamente**: un intento tiene una identidad de envío estable y un
  reintento seguro la reutiliza cuando Telegram lo permite.
- **La sesión es tan sensible como un access token**: nunca sale del almacén seguro.
- **El contenido del usuario no se transforma**: ni el texto ni los archivos se modifican, no
  se añaden marcas de AutoPublisher.

## Restricciones de la plataforma (punto de partida; reconfirmar en `/speckit-plan`)

Estos hechos condicionan el producto. El plan DEBE reconfirmarlos y fijar los detalles en
`research.md`:

- **Acceso como usuario**: Telegram permite a aplicaciones de terceros actuar como cuenta de
  usuario mediante MTProto, usando credenciales de aplicación (`api_id`, `api_hash`) obtenidas
  en `my.telegram.org`. `api_hash` es un secreto.
- **Librería**: Telethon estable como punto de partida. El plan DEBE reconfirmar versión,
  compatibilidad con la versión de Python del backend, login de usuario (código + 2FA),
  manejo de sesiones serializables (para guardarlas fuera de archivos `.session`),
  descubrimiento de canales y permisos, envío de texto / imagen / vídeo, callback de progreso
  de subida y cómo controlar o reutilizar `random_id`.
- **Deduplicación**: los envíos MTProto llevan un `random_id` elegido por el cliente que
  Telegram usa para descartar reenvíos del mismo mensaje. El plan DEBE confirmar si la API de
  alto nivel de Telethon permite fijarlo o si hace falta la petición de bajo nivel, y durante
  cuánto tiempo / en qué condiciones Telegram aplica la deduplicación.
- **Límites** (valores habituales, a reconfirmar): texto de mensaje hasta 4096 caracteres;
  caption de media hasta 1024 caracteres para cuentas normales (mayor para Premium); archivos
  de hasta 2 GB para cuentas normales (mayor para Premium).
- **Rate limiting**: Telegram puede responder con FloodWait indicando los segundos que hay que
  esperar.
- **Enlaces**: los canales públicos (con username) tienen enlaces de mensaje estables; los
  canales privados solo tienen enlaces válidos para miembros y su forma debe confirmarse.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Checkpoint V1a: conectar la cuenta real y ver el canal de prueba (Priority: P1)

Antes de construir la UI completa y la integración con el scheduler, el usuario configura las
credenciales de aplicación, conecta su cuenta real de Telegram (teléfono, código, 2FA si
procede), verifica la identidad obtenida y comprueba que su canal de prueba aparece entre los
destinos disponibles.

**Why this priority**: si la sesión no puede guardarse de forma segura o el canal no puede
identificarse de forma estable, el resto de la feature no tiene sentido (stop condition).

**Independent Test**: con `api_id` / `api_hash` reales configurados y una cuenta real, completar
el login, ejecutar Verify y listar canales; comprobar que la identidad y el canal de prueba son
correctos y que la sesión solo está en el almacén seguro.

**Acceptance Scenarios**:

1. **Given** credenciales de aplicación configuradas y una `Account` Telegram sin conectar,
   **When** el usuario introduce su teléfono, el código recibido y (si se le pide) su
   contraseña 2FA, **Then** la cuenta queda `Connected` con su Telegram user ID, nombre visible
   y username (si existe).
2. **Given** una cuenta conectada, **When** el usuario ejecuta Verify, **Then** AutoPublisher
   comprueba de forma real que la sesión sigue autorizada y muestra la identidad actual.
3. **Given** una cuenta conectada que administra el canal de prueba, **When** el usuario
   consulta los canales disponibles, **Then** el canal de prueba aparece y los grupos,
   supergrupos, chats privados y canales sin permiso de publicación no aparecen.
4. **Given** una conexión completada, **When** se inspeccionan la base de datos, los logs, las
   respuestas de la API, el frontend, `.env` y el workspace, **Then** no aparece la sesión, el
   `api_hash`, el código de login ni la contraseña 2FA, y no existe ningún archivo `.session`.

---

### User Story 2 - Checkpoint V1b: publicar texto, imagen y vídeo reales en el canal (Priority: P1)

Con la cuenta conectada y el canal de prueba elegido, el usuario envía un texto inocuo, una
imagen pequeña con caption y un vídeo pequeño con caption, y comprueba en Telegram que aparecen
como publicaciones normales del canal.

**Why this priority**: valida el objetivo central (usuario real, sin bot, igual que manual)
antes de añadir más arquitectura.

**Independent Test**: tres publicaciones reales con `Publish now`; inspección visual en la app
de Telegram. Si los tres tipos funcionan: **V1 PASS**. Los mensajes de prueba se eliminan
manualmente en Telegram al terminar.

**Acceptance Scenarios**:

1. **Given** un canal elegido, **When** el usuario publica un texto, **Then** el mensaje aparece
   en el canal, no aparece ningún bot ni marca de AutoPublisher y se ve igual que una
   publicación manual según la configuración normal del canal.
2. **Given** un canal elegido, **When** el usuario publica una imagen con caption, **Then** la
   imagen aparece con el caption exacto, sin recompresión o transformación por parte de
   AutoPublisher.
3. **Given** un canal elegido, **When** el usuario publica un vídeo con caption, **Then** el
   vídeo aparece reproducible con el caption exacto.
4. **Given** cualquiera de los tres envíos confirmados, **Then** el intento queda `succeeded`, la
   `Publication` queda `PUBLISHED` y se conserva el Telegram message ID.

---

### User Story 3 - Elegir y cambiar el canal destino (Priority: P1)

El usuario elige, entre los canales broadcast donde puede publicar, el único canal destino de
su `Account` Telegram en AutoPublisher, y puede cambiarlo más adelante siempre que no haya
publicaciones Telegram pendientes (`SCHEDULED` o `PUBLISHING`) en ese `Account`.

**Why this priority**: sin destino no se puede publicar.

**Independent Test**: con fakes, listar canales con distintos permisos, elegir uno, reiniciar y
comprobar que la publicación localiza el mismo canal aunque haya cambiado su nombre visible.

**Acceptance Scenarios**:

1. **Given** varios canales disponibles, **When** el usuario elige uno, **Then** AutoPublisher
   guarda una identidad estable suficiente para volver a localizarlo y muestra su nombre.
2. **Given** un canal elegido cuyo nombre visible cambia en Telegram, **When** se ejecuta una
   publicación, **Then** se publica en el mismo canal.
3. **Given** un `Account` con una publicación Telegram en `SCHEDULED` o `PUBLISHING`, **When**
   el usuario intenta cambiar el canal destino, **Then** el cambio se rechaza con un mensaje que
   indica que primero debe completarse o cancelarse la publicación pendiente, y el canal sigue
   siendo el mismo.
4. **Given** un `Account` sin publicaciones Telegram en `SCHEDULED` ni `PUBLISHING`, **When** el
   usuario cambia el canal destino, **Then** las publicaciones futuras usan el nuevo canal.
5. **Given** un canal elegido en el que el usuario pierde el permiso de publicar o que deja de
   ser accesible, **When** se ejecuta una publicación, **Then** falla con un error comprensible
   y no se publica en ningún otro sitio.

---

### User Story 4 - Programar la publicación en Telegram (Priority: P2)

El usuario programa una publicación de Telegram para una fecha/hora; el scheduler genérico la
ejecuta con el mismo publisher que `Publish now`.

**Why this priority**: reutiliza el valor central de AutoPublisher; depende de US2.

**Independent Test**: con fakes, una publicación programada y armada vence y pasa por
`SCHEDULED → PUBLISHING → PUBLISHED / FAILED` con un intento de origen `scheduled`.

**Acceptance Scenarios**:

1. **Given** una `Publication` Telegram programada y armada, **When** llega su hora, **Then** el
   scheduler la publica con el mismo servicio que la publicación manual.
2. **Given** una ejecución programada que falla, **Then** el fallo queda registrado y visible
   igual que en el resto de plataformas.
3. **Given** cualquier publicación de Telegram, **Then** nunca se usa el scheduling nativo de
   Telegram.

---

### User Story 5 - Verificar y desconectar la cuenta (Priority: P2)

El usuario puede comprobar en cualquier momento que la conexión sigue viva y desconectar la
cuenta de forma segura.

**Why this priority**: necesario para operar con seguridad una credencial crítica.

**Independent Test**: con fakes, Verify con sesión válida y revocada; Disconnect con y sin
conexión con Telegram disponible.

**Acceptance Scenarios**:

1. **Given** una sesión revocada desde otro dispositivo, **When** el usuario ejecuta Verify,
   **Then** la cuenta deja de mostrarse como `Connected` y se indica que hay que reconectar.
2. **Given** una cuenta conectada, **When** el usuario desconecta, **Then** AutoPublisher cierra
   la sesión en Telegram y elimina la credencial local según la semántica segura del plan.
3. **Given** una desconexión, **Then** las demás plataformas y cuentas no se ven afectadas.

---

### User Story 6 - No duplicar ante cortes y reintentos (Priority: P2)

Si se pierde la respuesta de un envío o la aplicación se interrumpe, un reintento seguro no
genera un segundo mensaje cuando Telegram permite deduplicarlo.

**Why this priority**: una publicación duplicada sin aviso es el fallo más grave (Constitution V).

**Independent Test**: con fakes, simular respuesta perdida y reintento; comprobar que se
reutiliza la misma identidad de envío y que solo existe un mensaje.

**Acceptance Scenarios**:

1. **Given** un intento que ha generado su identidad de envío, **When** se reintenta de forma
   segura, **Then** se reutiliza la misma identidad.
2. **Given** una situación realmente ambigua que no puede resolverse de forma sencilla, **Then**
   se aplica la semántica genérica existente de resultado incierto y no se reenvía
   automáticamente.

---

### User Story 7 - Entender los errores, incluido FloodWait (Priority: P3)

Cuando algo falla, el usuario ve un mensaje comprensible y sin secretos.

**Why this priority**: mejora la operación, pero no bloquea el flujo principal.

**Independent Test**: con fakes, provocar cada categoría de error y comprobar código y mensaje.

**Acceptance Scenarios**:

1. **Given** un FloodWait, **Then** el usuario ve cuántos segundos pide esperar Telegram y
   AutoPublisher no vuelve a intentarlo antes de ese tiempo.
2. **Given** un texto o caption demasiado largo, un archivo inválido o demasiado grande, **Then**
   el error se detecta en preflight cuando sea posible, antes de cualquier envío.

---

### Edge Cases

- El backend se reinicia en mitad de un login (tras pedir el código): se exige reiniciar la
  conexión; no hay recuperación de login parcial.
- Código incorrecto o caducado, contraseña 2FA incorrecta, número inválido o FloodWait durante
  el login: error comprensible; no se almacena nada.
- Credenciales de aplicación ausentes o inválidas: Connect no se inicia y se explica qué falta.
- La cuenta no administra ningún canal donde pueda publicar: lista vacía con explicación.
- Cambio de canal destino con publicaciones `SCHEDULED` o `PUBLISHING` en el `Account`:
  rechazado con explicación; el destino no cambia.
- Canal elegido borrado, convertido o con permisos retirados: fallo comprensible, sin publicar.
- `Publication` sin texto ni media, o con media que no es una sola imagen o un solo vídeo:
  rechazada en preflight.
- Archivo local borrado o modificado entre la programación y la ejecución: falla como archivo no
  disponible, reutilizando el comportamiento genérico.
- Caption que excede el límite aplicable: rechazado en preflight; nunca se trunca en silencio.
- Corte de red durante la subida antes de enviar el mensaje: no existe mensaje; error temporal.
- Corte tras enviar el mensaje y antes de recibir confirmación: reintento con la misma identidad
  de envío si es seguro; si no, resultado incierto genérico.
- La aplicación se reinicia con un intento Telegram en curso: la recuperación genérica de
  intentos interrumpidos lo trata sin reenviar a ciegas.
- Sesión revocada justo antes de una publicación programada: fallo de sesión inválida y cuenta
  marcada como necesitando reconexión.
- Canal privado sin enlace público: se guarda el message ID y no se inventa una URL.

## Requirements *(mandatory)*

### Functional Requirements

#### Credenciales de aplicación y conexión

- **FR-001**: El sistema DEBE autenticarse como **cuenta de usuario** de Telegram mediante
  MTProto usando una librería cliente estable (Telethon como punto de partida). NO DEBE usar la
  Bot API ni crear o exigir un bot. NO DEBE implementar MTProto ni la transferencia por chunks
  manualmente.
- **FR-002**: Las credenciales de aplicación (`api_id`, `api_hash`) DEBEN configurarse siguiendo
  los patrones locales existentes de configuración de plataformas; `api_hash` DEBE tratarse
  como secreto y nunca versionarse. Solo se versionan plantillas sin valores reales.
- **FR-003**: El usuario DEBE poder conectar una `Account` Telegram con el flujo: iniciar
  Connect → número de teléfono → código enviado por Telegram → contraseña 2FA solo si Telegram
  la exige → sesión autorizada.
- **FR-004**: Tras autorizar, el sistema DEBE verificar la identidad mediante la propia API y
  persistir solo metadata pública: Telegram user ID, nombre visible, username si existe y
  estado de conexión.
- **FR-005**: El código de login y la contraseña 2FA NUNCA DEBEN persistirse ni registrarse.
- **FR-006**: Un login incompleto NO necesita sobrevivir a un reinicio del backend; en ese caso
  el usuario DEBE poder reiniciar la conexión desde el principio.

#### Sesión y seguridad

- **FR-007**: La sesión MTProto autorizada DEBE almacenarse únicamente en el almacén seguro del
  sistema operativo ya usado por AutoPublisher. NUNCA en SQLite, frontend, logs, `.env`,
  respuestas de API ni archivos `.session` persistentes en el repositorio o el workspace.
- **FR-008**: El `.gitignore` DEBE cubrir los patrones necesarios para evitar versionar
  accidentalmente archivos de sesión de Telegram.
- **FR-009**: Logs, errores y respuestas NO DEBEN exponer sesión, auth key, `api_hash`, códigos
  ni contraseñas.

#### Verify / Disconnect

- **FR-010**: Verify DEBE comprobar de forma real que la sesión sigue autorizada y obtener la
  identidad actual; si la sesión no es válida, la cuenta DEBE dejar de figurar como
  `Connected` y pedir reconexión.
- **FR-011**: Disconnect DEBE cerrar/revocar la sesión en Telegram cuando sea posible y eliminar
  después la credencial local. El plan DEBE definir la semántica segura cuando Telegram no es
  alcanzable (p. ej. si la credencial local se borra igualmente y cómo se informa).
- **FR-012**: Conectar, verificar o desconectar Telegram NO DEBE afectar a otras plataformas ni
  a otras cuentas.

#### Canal destino

- **FR-013**: El sistema DEBE listar únicamente los **canales broadcast** accesibles por la
  cuenta en los que el usuario tiene permiso para publicar. Grupos básicos, supergrupos,
  forums/topics y chats privados NO DEBEN ofrecerse.
- **FR-014**: Cada `Account` Telegram DEBE tener un único canal broadcast seleccionado como
  destino, elegido a nivel de `Account` (no por `Publication`). El usuario DEBE poder elegirlo y
  cambiarlo después, salvo lo indicado en FR-014a.
- **FR-014a**: El sistema NO DEBE permitir cambiar el canal destino mientras ese `Account` tenga
  alguna publicación Telegram en estado `SCHEDULED` o `PUBLISHING`. La UI y la API DEBEN
  rechazar el cambio explicando que primero debe completarse o cancelarse la publicación
  pendiente. Así una publicación ya preparada nunca cambia silenciosamente de destino.
- **FR-015**: El sistema DEBE persistir una identidad estable del canal suficiente para volver a
  localizarlo en una ejecución programada, sin depender solo del nombre visible. El plan DEBE
  decidir dónde se guarda, evitando cambios innecesarios en el modelo común.
- **FR-016**: Si el canal no es accesible o el usuario ya no puede publicar en él, la
  publicación DEBE fallar con un error comprensible y NUNCA publicar en otro destino.

#### Publicación

- **FR-017**: El sistema DEBE soportar tres tipos de publicación: **texto** (mensaje de texto),
  **una imagen** con caption opcional y **un vídeo** con caption opcional.
- **FR-018**: El texto del mensaje (texto) o el caption (imagen/vídeo) DEBE tomarse del texto ya
  existente de la `Publication` siguiendo el patrón usado por otras plataformas de texto; NO se
  diseña metadata común multi-plataforma (Feature 017).
- **FR-019**: El texto y los archivos NO DEBEN transformarse: no se transcodifica, no se
  recomprime deliberadamente, no se añaden hashtags, enlaces ni marcas de AutoPublisher.
- **FR-020**: La transferencia del archivo la DEBE realizar la librería cliente. El sistema PUEDE
  exponer progreso si la librería lo ofrece de forma sencilla.
- **FR-021**: El preflight DEBE rechazar antes de cualquier envío: cuenta no conectada, sin canal
  elegido, contenido vacío, media que no sea una sola imagen o un solo vídeo, texto/caption por
  encima del límite aplicable y archivo no disponible o por encima del tamaño máximo aplicable.
- **FR-022**: La publicación DEBE realizarse con el comportamiento normal del canal/remitente que
  Telegram aplica a una publicación manual con esa cuenta; NO se implementa configuración
  avanzada de `send_as`.
- **FR-023**: Al confirmar Telegram el mensaje, el sistema DEBE dejar el intento `succeeded`, la
  `Publication` `PUBLISHED`, conservar el Telegram message ID y conservar un enlace solo cuando
  pueda derivarse de forma fiable; NUNCA DEBE inventar URLs.

#### Scheduler e integración genérica

- **FR-024**: Telegram DEBE integrarse como un publisher más dentro de la arquitectura genérica
  existente, reutilizando `Account`, `Publication`, `PublicationAttempt`, el protocolo de
  publisher, el scheduler, el almacén seguro y los errores genéricos.
- **FR-025**: `Publish now` y la ejecución programada DEBEN usar exactamente el mismo
  publisher/servicio y seguir `SCHEDULED → PUBLISHING → PUBLISHED / FAILED`.
- **FR-026**: NO DEBE usarse el scheduling nativo de Telegram (puede documentarse como mejora
  futura).
- **FR-027**: Cualquier cambio en el núcleo común DEBE justificarse en el plan explicando por qué
  no puede resolverse dentro del adaptador Telegram.

#### Anti-duplicados

- **FR-028**: Cada `PublicationAttempt` que puede producir un mensaje DEBE tener una identidad de
  envío estable (basada en `random_id`), persistida antes del envío.
- **FR-029**: Un reintento o recuperación segura del mismo intento DEBE reutilizar esa identidad
  cuando la API lo permita; el sistema NUNCA DEBE generar deliberadamente un segundo mensaje
  por una respuesta perdida.
- **FR-030**: NO se DEBE construir un sistema de reconciliación complejo. Si existe una situación
  realmente ambigua no resoluble de forma sencilla, DEBE usarse la semántica genérica de
  resultado incierto existente.

#### Errores

- **FR-031**: El sistema DEBE mapear de forma sencilla, reutilizando errores genéricos cuando sea
  posible: sesión inválida/revocada, sin permiso para publicar, canal inexistente/no accesible,
  texto/caption inválido, archivo no válido/no disponible, archivo demasiado grande,
  FloodWait/rate limiting y error temporal de red/API. NO se DEBE crear una taxonomía amplia
  específica de Telegram.
- **FR-032**: Ante FloodWait, el sistema DEBE mostrar un error comprensible con el tiempo de
  espera indicado y NO DEBE volver a intentar la operación antes de ese tiempo.

#### Interfaz

- **FR-033**: La UI DEBE permitir, con el mínimo necesario: Connect (teléfono, código, 2FA),
  ver identidad y estado, Verify, Disconnect, listar y elegir canal, y crear/publicar/programar
  publicaciones Telegram de texto, imagen o vídeo reutilizando las pantallas existentes.

#### Validación real y calidad

- **FR-034**: Antes de construir toda la UI y la integración con el scheduler DEBE completarse el
  checkpoint real **V1a** (configurar credenciales, Connect, código, 2FA si procede, Verify,
  identidad correcta, canal de prueba listado). **STOP** si la sesión no puede guardarse de
  forma segura o el canal no puede identificarse correctamente.
- **FR-035**: Después DEBE completarse **V1b** con el canal real: texto inocuo, imagen pequeña +
  caption, vídeo pequeño + caption, comprobando en Telegram que aparecen, que no aparece ningún
  bot, que coinciden visualmente con una publicación manual normal y que no aparece ninguna
  marca de AutoPublisher. Los tres tipos funcionando = **V1 PASS**. No se añade arquitectura
  adicional antes de V1 PASS.
- **FR-036**: Los tests DEBEN cubrir **nuestro código** con fakes en el límite Telegram/librería:
  conexión completa y con 2FA, sesión segura, Verify/Disconnect, listado y selección de canal
  permitido, texto, imagen, vídeo, caption, resultado remoto/message ID, anti-duplicado/
  reintento, FloodWait, manual + scheduler y ausencia de secretos. NO se DEBEN escribir tests
  del protocolo MTProto, chunking, internals de sesión de la librería ni de cada error RPC.
- **FR-037**: La documentación DEBE actualizarse con la configuración de credenciales de
  aplicación, el flujo de conexión y las limitaciones de V1.

### Key Entities *(include if feature involves data)*

- **Account (Telegram)**: `Account` existente con plataforma `telegram`; representa el destino de
  publicación de un proyecto.
- **Conexión Telegram**: estado de conexión de una `Account` Telegram con metadata pública
  (Telegram user ID, nombre visible, username opcional, estado, fechas) y el canal destino
  elegido. Sin secretos.
- **Sesión Telegram**: credencial crítica de la cuenta de usuario; solo en el almacén seguro del
  sistema operativo, referenciada por la conexión.
- **Canal destino**: canal broadcast elegido; identidad estable para relocalizarlo, más título y
  username público (si existe) solo para mostrar y derivar enlaces. Exactamente uno por
  `Account` Telegram; no modificable con publicaciones Telegram pendientes.
- **PublicationAttempt (Telegram)**: intento genérico existente; guarda la identidad de envío
  estable, el message ID y el enlace fiable cuando exista.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario conecta su cuenta real de Telegram (incluyendo 2FA si la tiene) en menos
  de 3 minutos sin crear ningún bot.
- **SC-002**: En la validación real, el 100 % de los tres tipos (texto, imagen, vídeo) aparecen en
  el canal de prueba como publicaciones normales del canal, sin bot ni marca de AutoPublisher.
- **SC-003**: Una publicación programada se ejecuta dentro de la ventana normal del scheduler
  genérico, con el mismo resultado que `Publish now`.
- **SC-004**: En todos los escenarios de reintento simulados, se produce como máximo un mensaje
  por intento cuando Telegram permite deduplicar.
- **SC-005**: Cero secretos (sesión, `api_hash`, código, contraseña 2FA) en base de datos, logs,
  respuestas de API, frontend, `.env` o archivos del workspace tras conectar y publicar.
- **SC-006**: Toda publicación Telegram fallida muestra un motivo comprensible; ningún fallo deja
  una publicación en estado silencioso o perdido.
- **SC-007**: La integración no modifica el comportamiento de las demás plataformas (sus tests
  existentes siguen pasando).

## Assumptions

- **Un canal destino por `Account` Telegram** (decisión confirmada): el canal se elige a nivel
  de `Account` (como el canal de YouTube o la cuenta de Instagram en otras plataformas) y se
  puede cambiar solo si el `Account` no tiene publicaciones Telegram en `SCHEDULED` ni
  `PUBLISHING` (FR-014a). Quedan fuera de la Feature 015: elegir canal por `Publication`,
  múltiples canales simultáneos y varios destinos Telegram desde un mismo `Account`; podrá
  revisarse en la Feature 017 — Multi-platform Distribution & Presets.
- El usuario dispone de `api_id` / `api_hash` propios de `my.telegram.org` y de un canal
  broadcast que administra para las pruebas.
- El texto del mensaje/caption reutiliza los campos de texto ya existentes de la `Publication`
  (como en Threads); los límites aplicados son los de una cuenta normal salvo que el plan
  decida detectar Premium de forma sencilla.
- La imagen y el vídeo proceden de la biblioteca de contenido existente (un solo archivo).
- No se requiere media delivery público: el archivo se transfiere directamente desde la máquina
  local a Telegram.
- La recuperación de un login parcial tras un reinicio no es necesaria.
- Los mensajes de prueba de la validación real se eliminan manualmente en Telegram.
- Fuera de alcance: Bot API, bots, grupos, supergrupos, forums/topics, DMs, albums, stories,
  polls, canal por `Publication`, múltiples canales o destinos desde un mismo `Account`,
  edición y borrado remoto, scheduling nativo, `send_as` avanzado, varios mensajes en
  una sola `Publication`, forwarding, scraping, lectura de chats, recepción de mensajes,
  automatización anti-spam, Feature 016 (Asset Library) y Feature 017 (Multi-platform
  Distribution & Presets).
- Los quality gates completos se ejecutan una sola vez al final de la feature (salvo cambio
  amplio en código compartido); CI realiza la verificación final.
