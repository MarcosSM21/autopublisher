# Feature Specification: TikTok Upload to Inbox (envío de vídeo a la bandeja de entrada de TikTok)

**Feature Branch**: `014-tiktok-inbox-upload`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Feature 014 — TikTok Upload to Inbox. Añadir un segundo modo oficial de TikTok, Upload to TikTok / Send to Inbox: AutoPublisher sube un vídeo local mediante `video.upload` (`POST /v2/post/publish/inbox/video/init/`, `FILE_UPLOAD`, chunks oficiales), TikTok lo procesa y envía una notificación al inbox del creador, que abre el editor de TikTok, revisa/edita y decide cuándo publicar. Envío manual y programado con el scheduler genérico. No sustituye Feature 013 (Direct Post). Ampliar el OAuth existente a `user.info.basic`, `video.publish` y `video.upload` sin crear otro OAuth. Checkpoint V1 real muy temprano con la cuenta pública (STOP si TikTok exige cuenta privada, audit u otra condición). Reutilizar la infraestructura de Feature 013 (validación, MIME, SHA-256, chunk planner, streaming, Content-Range, progreso, reintentos de chunks intermedios, política 416, `upload_url` secreto, polling, taxonomía de errores) extrayendo solo abstracciones neutrales y manteniendo separada la semántica de ambos modos. No enviar opciones de Direct Post que el endpoint Inbox no admita. `SEND_TO_USER_INBOX` = éxito del envío (Ready in TikTok), no publicado; detener polling; `Check status` posterior acotado al mismo `publish_id`; `PUBLISH_COMPLETE` = el usuario publicó al menos un post desde ese contenido; no asumir un post por `publish_id`, no `video.list`. `spam_risk_too_many_pending_share` = fallo determinado sin reintento. Anti-duplicados: un `inbox/video/init` y un `publish_id` por intento, nunca reenviar. Persistencia generalizando `tiktok_publish_runs` con modo. Seguridad de Feature 013. Fuera de alcance: automatización móvil, scraping, Direct Post público, App Audit, `video.list`, borrado remoto, analytics, sincronización de metadata editada en TikTok, fotos, cross-posting (Feature 015)."

## Clarifications

### Session 2026-10-15

- Q: ¿Qué estado genérico de `Publication` refleja "Ready in TikTok" sin afirmar que está
  publicado? → A: Un nuevo estado genérico neutral `AWAITING_USER_ACTION`. El attempt cuenta como
  `succeeded` y el scheduler deja de actuar. `SEND_TO_USER_INBOX` mantiene ese estado,
  `PUBLISH_COMPLETE` pasa a `PUBLISHED` y `FAILED` pasa a `FAILED`.
- Q: ¿Cómo se distinguen los scopes? → A: `user.info.basic` + `video.publish` son los scopes base
  de la conexión (Direct Post); `video.upload` es una capacidad adicional para Upload to Inbox.
  Nuevos `Connect`/`Reconnect` piden los tres; una conexión antigua con dos sigue `Connected` (solo
  Inbox no disponible + `Reconnect`); un `Reconnect` que no concede los tres falla de forma segura
  y conserva la conexión anterior; perder `video.upload` en refresh deshabilita solo Inbox; perder
  `video.publish` sigue las reglas de la Feature 012.
- Q: ¿Qué modo tienen las publicaciones TikTok? → A: Las existentes se migran como `DIRECT_POST`;
  las nuevas empiezan sin modo (`NULL`), sin default en base de datos; sin modo elegido no se puede
  publicar, enviar ni programar.
- Q: ¿`AWAITING_USER_ACTION` es terminal? → A: Terminal para la ejecución de AutoPublisher, no
  terminal para el ciclo de vida de la `Publication`. El intento de entrega `succeeded` nunca se
  reescribe; `Check status` no crea intentos; la UI distingue resultado de entrega y estado final.

## Contexto

Desde la Feature 012, una `Account` TikTok puede estar `Connected` mediante TikTok Login Kit for
Desktop con los permisos `user.info.basic` y `video.publish`, con tokens solo en el almacén seguro
del sistema operativo y el `open_id` como identidad autoritativa.

Desde la Feature 013, AutoPublisher publica vídeos en TikTok mediante **Direct Post**
(`FILE_UPLOAD`), manualmente o con el scheduler genérico, con: Creator Info, opciones obligatorias
y consentimiento expreso; validación local del vídeo; subida por chunks con `upload_url` tratado
como secreto efímero en memoria; `publish_id` persistido antes de subir; write-ahead antes del
último chunk; polling acotado; reconciliación de solo lectura con el `publish_id` original; y un
estado de ejecución propio de TikTok (`tiktok_publish_runs`). En el entorno actual (cliente no
auditado), Direct Post queda restringido a `SELF_ONLY` y a una cuenta privada.

Esta feature añade un **segundo modo de TikTok**, **Upload to Inbox** ("Send to TikTok"), sin
sustituir Direct Post:

| | Direct Post (Feature 013) | Upload to Inbox (Feature 014) |
|---|---|---|
| Quién publica | AutoPublisher, automáticamente | El usuario, dentro de la app TikTok |
| Permiso | `video.publish` | `video.upload` |
| Configuración del post | En AutoPublisher (privacidad, interacciones, divulgación, AIGC, caption) | En el editor de TikTok |
| Éxito de AutoPublisher | `PUBLISH_COMPLETE` | `SEND_TO_USER_INBOX` ("Ready in TikTok") |

Flujo conceptual de Upload to Inbox:

`Publication` de vídeo en modo Upload to Inbox → `Send to TikTok` (manual) o hora programada
(scheduler genérico) → preflight → inicializar el upload a inbox (`FILE_UPLOAD`) → persistir
`publish_id` → subir chunks intermedios → write-ahead → último chunk → consulta acotada de estado →
`SEND_TO_USER_INBOX` → **Ready in TikTok** (se detiene el polling) → el usuario abre la
notificación del inbox de TikTok, edita y publica él mismo → más tarde, `Check status` sobre el
mismo `publish_id` puede observar `PUBLISH_COMPLETE` → **Published**.

Principios rectores:

- **El usuario termina la publicación en TikTok**: AutoPublisher solo transfiere el vídeo; no
  abre la notificación, no edita, no pulsa Publish, no automatiza el móvil ni hace scraping.
- **Nunca reenviar**: un intento crea como máximo un upload a inbox y un `publish_id`; esperar al
  usuario no es un fallo y nunca provoca un nuevo envío automático.
- **Honestidad sobre lo que se sabe**: AutoPublisher no afirma conocer el caption, la privacidad,
  el sonido, los efectos, los hashtags, la portada ni ninguna configuración final del post, ni
  cuántos posts se crearon, ni cuándo aparecerá la notificación.
- **Máxima reutilización, semántica separada**: se comparte la mecánica neutral de transferencia
  de Feature 013; Direct Post e Inbox mantienen reglas, estados y textos propios.
- **Ningún secreto sale de donde debe**: garantías de seguridad de la Feature 013 sin cambios.

## Restricciones de la plataforma (punto de partida; reconfirmar en `/speckit-plan`)

Hechos a reconfirmar contra la documentación oficial vigente de TikTok for Developers
(*Content Posting API — Upload*, *Media Transfer Guide*, *Get Post Status*, *Content Sharing
Guidelines*, *Scopes*) y fijar en `research.md`:

- **Inicialización**: `POST /v2/post/publish/inbox/video/init/` con permiso `video.upload` y
  `source_info.source = FILE_UPLOAD` (`video_size`, `chunk_size`, `total_chunk_count`). Respuesta:
  `publish_id` y `upload_url`. El plan DEBE confirmar qué campos acepta el endpoint (en
  particular, si admite algún dato de post como caption) y su rate limit.
- **Subida**: mismo mecanismo oficial de chunks que Direct Post (reglas de tamaño, `Content-Range`,
  `206`/`201`, `403` URL caducada, `416`, `5xx`, validez del `upload_url`).
- **Estado**: `POST /v2/post/publish/status/fetch/`. Estados relevantes para Upload:
  `PROCESSING_UPLOAD`, `SEND_TO_USER_INBOX` (TikTok ha enviado una notificación al inbox del
  creador para continuar en el editor de TikTok; **no** significa publicado), `PUBLISH_COMPLETE`
  (el usuario abrió el contenido y publicó desde el flujo de edición de TikTok) y `FAILED`.
- **Varios posts por `publish_id`**: la documentación indica que en el flujo Upload el usuario
  puede crear potencialmente más de un post desde el contenido de un único `publish_id`. El plan
  DEBE investigar qué identidad remota, si alguna, devuelve el estado en este flujo.
- **Pending shares**: error documentado `spam_risk_too_many_pending_share`; actualmente como
  máximo 5 shares pendientes en una ventana de 24 horas. TikTok es la fuente de verdad.
- **Vídeo**: mismas restricciones de formato, codec, FPS, dimensiones, tamaño y duración de la API
  que en Feature 013, salvo que la documentación del flujo Upload indique otras.
- **Cliente no auditado**: el plan DEBE reconfirmar si las restricciones de clientes no auditados
  (cuenta privada, `SELF_ONLY`) afectan al flujo Upload. La hipótesis de esta feature es que la
  cuenta puede permanecer **pública**; el checkpoint V1 lo valida con TikTok real.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Checkpoint V1: enviar un vídeo real al inbox de TikTok con la cuenta pública (Priority: P1)

Como usuario, quiero comprobar cuanto antes, con mi cuenta TikTok pública y el cliente Sandbox/no
auditado actual, que AutoPublisher puede enviar un vídeo pequeño a mi inbox de TikTok y que puedo
abrirlo en el editor de TikTok, antes de invertir en scheduler, interfaz avanzada o recuperación.

**Why this priority**: si TikTok exige cuenta privada, App Audit u otra condición inesperada, el
resto de la feature carece de sentido; el checkpoint responde explícitamente: **¿Upload to Inbox
funciona realmente con nuestra cuenta pública y nuestro cliente Sandbox/no auditado?**

**Independent Test**: con la conexión ampliada a tres permisos, ejecutar un envío manual mínimo
de un vídeo pequeño e inocuo (un único chunk) y verificar en TikTok real los pasos de FR-040.

**Acceptance Scenarios**:

1. **Given** la cuenta TikTok pública y la conexión reautorizada con `user.info.basic`,
   `video.publish` y `video.upload`, **When** el usuario envía un vídeo pequeño en modo Upload to
   Inbox, **Then** TikTok acepta la inicialización con `FILE_UPLOAD`, la subida termina y el estado
   alcanza `SEND_TO_USER_INBOX`.
2. **Given** el estado `SEND_TO_USER_INBOX`, **When** el usuario revisa su móvil, **Then** aparece
   la notificación en el inbox de TikTok; al pulsarla, TikTok abre el editor con el vídeo cargado
   y editable (no es necesario publicar en V1).
3. **Given** que TikTok rechaza el envío por exigir cuenta privada, App Audit u otra condición no
   prevista, **When** se observa, **Then** se detiene la implementación y se revisa spec/plan
   antes de construir nada más.

---

### User Story 2 - Elegir el modo y enviar ahora un vídeo a TikTok (Priority: P1)

Como usuario, quiero elegir para una publicación TikTok de vídeo el modo **Upload to Inbox** y
pulsar `Send to TikTok` para que AutoPublisher transfiera el vídeo y me avise de que está listo en
TikTok para que yo lo revise, edite y publique.

**Why this priority**: es el flujo manual completo y la base sobre la que se apoya la
programación.

**Independent Test**: con fakes de TikTok, crear una publicación de vídeo para una `Account`
TikTok `Connected` con `video.upload`, elegir Upload to Inbox, enviar y comprobar: una única
inicialización de inbox con `FILE_UPLOAD`; `publish_id` persistido antes del primer chunk;
write-ahead antes del último chunk; polling hasta `SEND_TO_USER_INBOX`; estado Ready in TikTok;
polling detenido; ninguna opción de Direct Post enviada; y ausencia de `upload_url` y tokens en
base de datos, logs y respuestas de la API.

**Acceptance Scenarios**:

1. **Given** una publicación TikTok de vídeo, **When** el usuario abre su revisión TikTok,
   **Then** puede elegir explícitamente entre `Direct Post` y `Upload to Inbox`; cada modo muestra
   solo sus propios controles y explicaciones.
2. **Given** el modo Upload to Inbox, **When** se muestra la revisión, **Then** no aparecen
   privacidad, interacciones, divulgación comercial, AIGC, declaración de Direct Post ni Creator
   Info como requisito, y se explica que el caption, la privacidad, el sonido y el resto de la
   configuración final se deciden en el editor de TikTok.
3. **Given** una publicación válida en modo Upload to Inbox, **When** el usuario pulsa
   `Send to TikTok` y confirma, **Then** la ejecución usa el ejecutor genérico con origen `manual`
   y la interfaz muestra sucesivamente `Uploading` (con progreso) y `Processing in TikTok`.
4. **Given** que TikTok devuelve `SEND_TO_USER_INBOX`, **When** se observa, **Then** se detiene el
   polling automático, el intento queda `succeeded`, la publicación pasa a `AWAITING_USER_ACTION`, se registra el momento de entrega y la interfaz muestra **Ready in TikTok** con la instrucción **"Open your TikTok
   inbox to review, edit and publish the video."**
5. **Given** que durante el polling inicial TikTok ya devuelve `PUBLISH_COMPLETE` (el usuario fue
   muy rápido), **When** se observa, **Then** la publicación pasa directamente a `PUBLISHED`.
6. **Given** que TikTok devuelve `FAILED`, **When** se observa, **Then** la publicación queda `FAILED` con un motivo seguro y comprensible.

---

### User Story 3 - Ampliar la conexión TikTok a `video.upload` (Priority: P1)

Como usuario, quiero reconectar mi cuenta TikTok una vez para conceder también `video.upload`, sin
un segundo OAuth y sin perder Direct Post.

**Why this priority**: sin `video.upload` no puede enviarse nada al inbox; es prerrequisito de V1.

**Independent Test**: con fakes de OAuth, completar `Connect`/`Reconnect` y comprobar que se
solicitan los tres permisos, que se acepta una concesión completa, que la renovación conserva y
valida los tres, y que una conexión antigua con solo dos permisos sigue publicando con Direct Post.

**Acceptance Scenarios**:

1. **Given** una cuenta TikTok, **When** el usuario pulsa `Connect` o `Reconnect`, **Then** el
   flujo OAuth existente solicita `user.info.basic`, `video.publish` y `video.upload`.
2. **Given** una concesión con los tres permisos, **When** se completa, **Then** la conexión queda
   `Connected` con los tres permisos registrados como concedidos.
3. **Given** una conexión existente con solo `user.info.basic` y `video.publish`, **When** el
   usuario la usa, **Then** Direct Post sigue funcionando y el modo Upload to Inbox aparece como no
   disponible con la indicación de reconectar para conceder `video.upload`; la cuenta NO pasa a
   `Reconnect required` por esa sola causa.
4. **Given** una renovación del token, **When** TikTok devuelve los permisos, **Then** se conservan
   y validan los tres; si `video.upload` desaparece, Upload to Inbox deja de estar disponible
   (Direct Post no se ve afectado mientras conserve `video.publish`).

---

### User Story 4 - Programar el envío a TikTok (Priority: P2)

Como usuario, quiero programar "Send to TikTok at 18:00" para que el scheduler genérico inicie el
envío a esa hora exactamente una vez, sabiendo que la notificación puede no aparecer exactamente a
esa hora.

**Why this priority**: la automatización es el valor central de AutoPublisher, pero depende del
flujo manual.

**Independent Test**: con reloj inyectable y fakes, programar y armar una publicación en modo
Upload to Inbox; avanzar el reloj y comprobar una sola ejecución `scheduled`; repetir con pausa
global, carrera con `Send to TikTok` manual y ciclos concurrentes.

**Acceptance Scenarios**:

1. **Given** una publicación en modo Upload to Inbox, **When** el usuario la programa, **Then** la
   interfaz muestra `Scheduled` y deja claro que la hora es la de inicio del envío, no la de
   aparición de la notificación ni la de publicación.
2. **Given** una publicación programada, armada y vencida, **When** el scheduler hace su ciclo,
   **Then** la ejecuta con el mismo servicio que el envío manual, origen `scheduled`, aplicando el
   preflight completo.
3. **Given** la automatización global en pausa, **When** vence, **Then** no se ejecuta; el envío
   manual sigue disponible.
4. **Given** un envío manual y un ciclo del scheduler simultáneos, o dos ciclos concurrentes,
   **When** coinciden, **Then** como máximo una ejecución comienza.

---

### User Story 5 - Comprobar después si publiqué desde TikTok (Priority: P2)

Como usuario, tras ver Ready in TikTok y publicar (o no) desde el editor de TikTok, quiero pulsar
`Check status` en AutoPublisher para saber si TikTok ya registra la publicación.

**Why this priority**: cierra el ciclo sin polling infinito ni listado de posts.

**Independent Test**: con un envío en Ready in TikTok y fakes de estado, pulsar `Check status` y
comprobar cada resultado posible, que solo se consulta el mismo `publish_id` y que no se usa
`video.list`.

**Acceptance Scenarios**:

1. **Given** un envío Ready in TikTok, **When** el usuario pulsa `Check status` y TikTok devuelve
   `SEND_TO_USER_INBOX`, **Then** sigue en `AWAITING_USER_ACTION` (Ready in TikTok), indicando que TikTok sigue esperando su acción.
2. **Given** lo anterior y `PUBLISH_COMPLETE`, **When** se observa, **Then** la publicación pasa a `PUBLISHED`, se registra el momento observado y se explica que el usuario publicó al menos un
   post desde ese contenido en TikTok; no se muestra ni se inventa un enlace o post concreto.
3. **Given** lo anterior y `FAILED`, **When** se observa, **Then** la publicación pasa a `FAILED` con un motivo seguro.
4. **Given** lo anterior y un error temporal (red, `5xx`, rate limit), **When** ocurre, **Then** el
   estado anterior se mantiene y se informa de que no pudo comprobarse.
5. **Given** cualquier comprobación, **When** se ejecuta, **Then** consulta únicamente el
   `publish_id` de ese intento, una vez por pulsación, sin iniciar polling continuo.

---

### User Story 6 - Nunca reenviar ni duplicar ante esperas, cortes o reinicios (Priority: P2)

Como usuario, quiero la garantía de que AutoPublisher nunca enviará dos veces el mismo vídeo a mi
inbox por cortes, reinicios o porque yo tarde horas o días en abrir la notificación.

**Why this priority**: los envíos pendientes cuentan contra el límite de TikTok y un duplicado
confunde al usuario (Constitution, principio V).

**Independent Test**: con fakes, interrumpir antes de la inicialización, con `publish_id`
persistido, durante chunks, tras el write-ahead, durante el último chunk, durante el polling y
tras Ready in TikTok; reiniciar y comprobar que la inicialización de inbox se llama como máximo una
vez por intento y que nunca se crea otro `publish_id` automáticamente.

**Acceptance Scenarios**:

1. **Given** una ejecución interrumpida antes del write-ahead del último chunk, **When** termina o
   se reinicia, **Then** queda `Failed` determinada, igual que en la Feature 013, sin reanudar la
   subida ni crear otro upload.
2. **Given** un último chunk sin respuesta concluyente, **When** se evalúa, **Then** no se reenvía
   y solo se consulta el `publish_id` original: `SEND_TO_USER_INBOX` → Ready in TikTok;
   `PUBLISH_COMPLETE` → Published; `FAILED` → fallo determinado; sin conclusión → resultado
   ambiguo, reconciliable después solo con ese `publish_id`.
3. **Given** un envío Ready in TikTok, **When** AutoPublisher se reinicia, pasan horas o días o el
   usuario ignora la notificación, **Then** sigue en `AWAITING_USER_ACTION` (Ready in TikTok), el scheduler y la recuperación al arrancar no actúan sobre ella y nunca se reenvía.
4. **Given** un resultado ambiguo, **When** el usuario intenta reenviar, **Then** aplica la regla
   genérica existente: debe reconocerse explícitamente antes de crear un nuevo intento.

---

### User Story 7 - Entender los fallos, incluido el límite de envíos pendientes (Priority: P3)

Como usuario, quiero mensajes claros cuando TikTok rechaza el envío, en particular cuando tengo
demasiados uploads pendientes de revisar o publicar en TikTok.

**Why this priority**: mejora la comprensión; el núcleo funcional ya existe.

**Independent Test**: con fakes, provocar `spam_risk_too_many_pending_share`, permiso ausente,
token inválido, vídeo inválido, URL caducada y errores temporales; comprobar mensajes seguros,
resultado determinado o ambiguo correcto y ausencia de reintentos indebidos.

**Acceptance Scenarios**:

1. **Given** que TikTok devuelve `spam_risk_too_many_pending_share`, **When** se observa, **Then**
   el envío falla de forma determinada, sin reintento automático, explicando que hay demasiados
   uploads pendientes de revisión/publicación en TikTok y que debe completarlos o descartarlos en
   TikTok antes de enviar otro.
2. **Given** cualquier otro error, **When** se clasifica, **Then** se reutiliza la taxonomía de
   errores de la Feature 013 con mensajes adaptados al modo Upload to Inbox.

---

### User Story 8 - Vídeos grandes en varios chunks (Priority: P3)

Como usuario, quiero enviar al inbox vídeos que requieren varios chunks con la misma fiabilidad y
progreso que en Direct Post.

**Why this priority**: amplía el alcance a vídeos reales más grandes; la mecánica ya existe.

**Independent Test**: con fakes, enviar un vídeo multi-chunk y comprobar plan de chunks,
`Content-Range`, progreso, reintento de chunks intermedios ante `5xx` y política de `416`
idénticos a la Feature 013.

**Acceptance Scenarios**:

1. **Given** un vídeo que requiere varios chunks, **When** se envía, **Then** se suben
   secuencialmente con progreso por bytes confirmados y las mismas reglas de reintento y
   write-ahead que en Direct Post.

### Edge Cases

- **Cuenta pública**: el modo Upload to Inbox no exige cuenta privada según la hipótesis de esta
  feature; si TikTok la exige, aplica la stop condition (FR-042).
- **Conexión con solo dos permisos**: Upload to Inbox no disponible con indicación de reconectar;
  Direct Post intacto.
- **Usuario que nunca abre la notificación**: la publicación permanece en `AWAITING_USER_ACTION` indefinidamente; no es un fallo, no se reenvía y no se hace polling automático.
- **Contenido descartado en TikTok mientras TikTok sigue devolviendo `SEND_TO_USER_INBOX`**:
  AutoPublisher mantiene la publicación en `AWAITING_USER_ACTION`. En esta feature no existe
  ninguna salida manual local (ni cancelar ni descartar), no se crea otro upload automáticamente y
  la publicación sigue contando como activa, por lo que las garantías anti-duplicado pueden
  mantener bloqueada la combinación contenido/cuenta. AutoPublisher no puede eliminar el envío
  pendiente en TikTok: ninguna acción local actúa sobre el pending share remoto. Una salida
  manual segura queda fuera de alcance (ver Assumptions).
- **Acciones sobre una publicación en `AWAITING_USER_ACTION`**: editar, reprogramar, cancelar o `Send to TikTok` se rechazan con un motivo claro; solo está disponible `Check status`.
- **Notificación no visible como push**: la interfaz habla de "TikTok inbox notification" y no
  garantiza una notificación push del sistema operativo.
- **Varios posts desde un `publish_id`**: `PUBLISH_COMPLETE` significa al menos un post; no se
  asocia a un único identificador externo ni se infieren posts concretos.
- **`SEND_TO_USER_INBOX` tras `PUBLISH_COMPLETE`** u otra transición inesperada: no se retrocede de `PUBLISHED`; se trata como estado inesperado registrado de forma segura.
- **`FAILED` observado después de Ready in TikTok**: la publicación pasa de `AWAITING_USER_ACTION` a `FAILED` con motivo seguro; el intento original conserva su resultado `succeeded` de entrega y no se reenvía automáticamente.
- **Estado no aplicable a Upload (`PROCESSING_DOWNLOAD`) o desconocido**: se trata como
  inconcluso; nunca como éxito.
- **Límite de 5 envíos pendientes en 24 h**: no existe contador local autoritativo; solo se
  reacciona al error de TikTok.
- **Cambio de modo tras un envío**: un intento conserva el modo con el que se ejecutó; el modo de
  la publicación no puede cambiarse mientras está `PUBLISHING` o tras un envío entregado.
- **Content de imagen**: se rechaza en preflight; fotos fuera de alcance.
- **Reconexión con otra cuenta TikTok (`open_id` distinto)**: reglas de identidad de la Feature
  012; un `Check status` posterior con una credencial que TikTok no autoriza para ese `publish_id`
  produce un error seguro sin cambiar el estado.
- **Desconexión con publicaciones en `AWAITING_USER_ACTION`**: conservan su estado;
  `Check status` requiere conexión utilizable.

## Requirements *(mandatory)*

### Functional Requirements

#### Modos de TikTok e integración con la arquitectura genérica

- **FR-001**: TikTok DEBE ofrecer dos modos para una publicación de vídeo: **Direct Post**
  (Feature 013, sin cambios de comportamiento) y **Upload to Inbox** (esta feature). El modo se
  persiste en las opciones específicas de TikTok, nunca en el modelo común `Publication`, con los
  valores `DIRECT_POST` e `INBOX_UPLOAD`. Reglas:
  - las publicaciones/opciones TikTok existentes antes de esta feature DEBEN migrarse como
    `DIRECT_POST`, preservando todas las publicaciones existentes (el plan decide la migración
    exacta);
  - en nuevas publicaciones TikTok el modo empieza **sin decidir** (`NULL` o equivalente); NO DEBE
    usarse `DIRECT_POST` (ni ningún otro valor) como default de base de datos para filas nuevas;
  - el usuario DEBE elegir explícitamente `DIRECT_POST` o `INBOX_UPLOAD`; sin modo elegido no puede
    ejecutarse `Publish now`/`Send to TikTok` ni `Schedule` (ni armarse), y la interfaz explica el
    motivo.
- **FR-002**: Upload to Inbox DEBE ejecutarse mediante el publisher de TikTok registrado en el
  registro genérico y el ejecutor genérico existentes, sin crear scheduler, ejecutor ni modelo de
  intentos específicos. Scheduler, núcleo genérico y núcleo de Accounts NO DEBEN contener lógica de
  TikTok (test de arquitectura existente). La única extensión del núcleo aprobada es el estado
  genérico neutral `AWAITING_USER_ACTION` (FR-019a), junto con el mecanismo neutral mínimo para
  que un publisher indique "entregado, pendiente de acción del usuario" y para aplicar las
  transiciones posteriores observadas (FR-019, FR-021).
- **FR-003**: Solo DEBE poder enviarse al inbox un **vídeo individual** local con `FILE_UPLOAD`.
  Publicaciones sin `Content` o con imagen DEBEN rechazarse en preflight.
- **FR-004**: El sistema DEBE extraer de la Feature 013 únicamente las abstracciones neutrales
  necesarias para compartir la transferencia `FILE_UPLOAD` (validación de vídeo, MIME, SHA-256,
  plan de chunks, streaming, `Content-Range`, progreso, reintentos de chunks intermedios, política
  de `416`, tratamiento del `upload_url`, polling y taxonomía de errores), sin duplicarlas y sin
  cambiar el comportamiento observable de Direct Post.
- **FR-005**: La semántica de Direct Post y de Upload to Inbox (inicialización, interpretación de
  estados, éxito, textos de interfaz) DEBE mantenerse separada.

#### Autorización (`video.upload`)

Semántica de permisos: `user.info.basic` + `video.publish` siguen siendo los **scopes base** que
hacen utilizable una conexión TikTok (y Direct Post), exactamente como en la Feature 012.
`video.upload` es una **capacidad adicional** necesaria solo para Upload to Inbox; su ausencia
nunca degrada la conexión base. El plan DEBE inspeccionar la implementación actual de la Feature
012 antes de decidir cómo separar conceptualmente scopes base, scopes solicitados y capacidades
por feature.

- **FR-006**: Todo `Connect`/`Reconnect` nuevo DEBE solicitar, mediante el flujo OAuth existente
  de la Feature 012, `user.info.basic`, `video.publish` y `video.upload`. NO DEBE crearse otro
  flujo OAuth.
- **FR-007**: Un `Connect`/`Reconnect` DEBE completarse solo si TikTok concede los tres scopes
  solicitados (regla de la Feature 012 de rechazar concesiones parciales). Si un `Reconnect` sobre
  una conexión existente no concede los tres, DEBE fallar de forma segura y conservar intacta la
  conexión anterior (credenciales, scopes concedidos, identidad y estado), sin pasarla a
  `Reconnect required`.
- **FR-008**: Una conexión existente con solo los scopes base (`user.info.basic` + `video.publish`)
  DEBE seguir `Connected` y utilizable para Direct Post. No tener `video.upload` NO DEBE implicar
  `Reconnect required`: únicamente Upload to Inbox se muestra **no disponible** con la acción
  `Reconnect` para concederlo.
- **FR-009**: La renovación del token DEBE conservar y validar los scopes concedidos. Si tras una
  renovación se pierde `video.upload`, Upload to Inbox DEBE quedar deshabilitado (no disponible +
  `Reconnect`) sin afectar a Direct Post ni al estado de la conexión. Si se pierde
  `video.publish`, se aplican exactamente las reglas existentes de la Feature 012.

#### Preflight

- **FR-010**: Antes de inicializar el upload a inbox o enviar cualquier byte, el preflight DEBE
  validar como mínimo: proyecto y cuenta activos, cuenta TikTok, conexión utilizable, credencial
  obtenible, `video.upload` concedido, identidad coincidente, modo Upload to Inbox elegido, Content
  de vídeo existente, archivo existente, inspección disponible, vídeo compatible con los límites de
  la API y ausencia de ejecución en curso. Si falla, la publicación no pasa a `PUBLISHING`.
- **FR-011**: El preflight de Upload to Inbox NO DEBE exigir Creator Info, privacidad,
  interacciones, divulgación comercial, AIGC ni la declaración/consentimiento de Direct Post,
  salvo que la documentación oficial vigente del endpoint Inbox lo requiera; en ese caso el plan
  DEBE justificarlo.
- **FR-012**: El sistema NO DEBE transcodificar, recortar ni modificar el vídeo original.

#### Inicialización, subida y opciones enviadas

- **FR-013**: Cada intento DEBE llamar a la inicialización de upload a inbox **como máximo una
  vez** y obtener como máximo un `publish_id`, que DEBE persistirse y confirmarse antes de enviar
  ningún chunk.
- **FR-014**: La inicialización NO DEBE incluir opciones de Direct Post (privacidad, comentarios,
  duet, stitch, divulgación comercial, AIGC, caption de Direct Post, portada) salvo que la
  documentación oficial vigente del endpoint Inbox lo permita explícitamente y el plan lo decida.
- **FR-015**: La subida DEBE reutilizar las reglas de la Feature 013: chunks secuenciales,
  `Content-Range` real, progreso por bytes confirmados, reintento acotado de chunks intermedios,
  política de `416`, `upload_url` solo en memoria y write-ahead persistido antes del último chunk;
  tras el write-ahead, el último chunk se intenta exactamente una vez.

#### Estado, entrega y `Check status`

- **FR-016**: Tras el último chunk, el sistema DEBE consultar el estado del `publish_id` de forma
  acotada (mismos límites que la Feature 013 o los que fije el plan) hasta observar
  `SEND_TO_USER_INBOX`, `PUBLISH_COMPLETE` o `FAILED`, o agotar el tiempo.
- **FR-017**: Interpretación para Upload to Inbox: `PROCESSING_UPLOAD` → `Processing in TikTok`;
  `SEND_TO_USER_INBOX` → **Ready in TikTok** (éxito del envío, pendiente de acción del usuario; NO
  publicado); `PUBLISH_COMPLETE` → **Published** (el usuario creó al menos un post desde ese
  contenido); `FAILED` → `Failed` con `fail_reason` seguro; estados no aplicables o desconocidos →
  inconclusos, nunca éxito.
- **FR-018**: Al observar `SEND_TO_USER_INBOX`, el sistema DEBE detener el polling automático,
  marcar el envío como entregado correctamente, registrar `delivered_to_inbox_at`, finalizar la
  ejecución genérica y mostrar "Ready in TikTok" con "Open your TikTok inbox to review, edit and
  publish the video.". NO DEBE esperarse indefinidamente a `PUBLISH_COMPLETE`.
- **FR-019**: Al observar `SEND_TO_USER_INBOX`, la `Publication` DEBE pasar al nuevo estado
  genérico neutral **`AWAITING_USER_ACTION`** (FR-019a) y el `PublicationAttempt` DEBE quedar
  `succeeded`. Transiciones posteriores observadas sobre el mismo `publish_id`:
  `SEND_TO_USER_INBOX` → se mantiene `AWAITING_USER_ACTION`; `PUBLISH_COMPLETE` → `PUBLISHED`;
  `FAILED` → `FAILED` (con `fail_reason` seguro). Ninguna otra transición sale de
  `AWAITING_USER_ACTION`. Si `PUBLISH_COMPLETE` se observa ya durante el polling inicial, la
  publicación pasa directamente a `PUBLISHED`.
- **FR-019a**: `AWAITING_USER_ACTION` DEBE añadirse al conjunto de estados genéricos de
  `Publication` como estado **neutral de plataforma** ("AutoPublisher completó su parte; la
  publicación depende de una acción del usuario en la plataforma"), sin nombres ni lógica de
  TikTok en el núcleo, mediante migración versionada y manteniendo sincronizados backend y
  frontend. Reglas genéricas:
  - el scheduler NO DEBE seleccionar, ejecutar ni recuperar publicaciones en este estado;
  - NO es un estado en ejecución: no ocupa concurrencia ni lo trata la recuperación genérica al
    arrancar como interrumpido;
  - NO permite `Publish now`/`Send to TikTok`, reprogramar, editar contenido/metadata/modo ni
    cancelar (evita reenvíos); las únicas salidas son las de FR-019 a partir de la plataforma;
  - las vistas y filtros genéricos DEBEN mostrarlo como estado distinto de `PUBLISHED` y de
    `FAILED`; en publicaciones TikTok Inbox se presenta como **Ready in TikTok**;
  - YouTube, Instagram, Threads y Direct Post NUNCA producen este estado y su comportamiento no
    cambia.
- **FR-019b**: `AWAITING_USER_ACTION` es **terminal para la ejecución** de AutoPublisher y **no
  terminal para el ciclo de vida** de la `Publication`. El `PublicationAttempt` `succeeded`
  representa que AutoPublisher entregó el contenido a TikTok y NO DEBE reescribirse después: si un
  `Check status` posterior lleva la `Publication` a `PUBLISHED` o a `FAILED`, el intento de
  entrega permanece `succeeded`. `Check status` NO DEBE crear un segundo intento. La interfaz y el
  historial DEBEN distinguir el **resultado del intento de entrega** del **estado final de la
  Publication** (p. ej., "Delivered to TikTok inbox" frente a "Failed in TikTok").
- **FR-020**: Si el polling inicial se agota en procesamiento o sin conclusión, el resultado DEBE
  ser ambiguo y reconciliable solo con el mismo `publish_id`; nunca se reenvía automáticamente.
- **FR-021**: Para una publicación en `AWAITING_USER_ACTION`, la interfaz DEBE ofrecer
  `Check status`, que consulta una sola vez el `publish_id` de ese intento: `SEND_TO_USER_INBOX` →
  sigue `AWAITING_USER_ACTION`; `PUBLISH_COMPLETE` → `PUBLISHED` y se registra `published_at`
  observado; `FAILED` → `FAILED`; error temporal → se mantiene el estado anterior y se informa. NO
  DEBE iniciar polling continuo ni crear un nuevo `PublicationAttempt`.
- **FR-022**: Una publicación `PUBLISHED` NO DEBE retroceder a `AWAITING_USER_ACTION` por una
  consulta posterior; `Check status` solo está disponible desde `AWAITING_USER_ACTION`.
- **FR-023**: El sistema NO DEBE asumir que un `publish_id` corresponde a exactamente un post, NO
  DEBE mapearlo a un único identificador o enlace externo, NO DEBE inferir posts concretos y NO
  DEBE usar `video.list`. El plan DEBE investigar qué identidad remota devuelve el estado en este
  flujo; cualquier identificador devuelto solo podrá conservarse como dato informativo no
  autoritativo si el plan lo justifica.
- **FR-024**: AutoPublisher NO DEBE mostrar ni afirmar conocer el caption, la privacidad, el
  sonido, los efectos, los hashtags, la portada ni la configuración final del post en TikTok, ni
  sincronizar metadata editada en TikTok.

#### Anti-duplicados, reinicio y recuperación

- **FR-025**: NUNCA DEBE crearse automáticamente otro upload a inbox para el mismo intento ni para
  la misma publicación porque el usuario ignore la notificación, el estado siga en
  `SEND_TO_USER_INBOX`, AutoPublisher se reinicie, pasen horas o días, o el usuario no haya
  publicado todavía.
- **FR-026**: Antes del punto irreversible, una interrupción o reinicio DEBE tener el mismo
  comportamiento seguro de la Feature 013 (fallo determinado, sin reanudar la subida).
- **FR-027**: Tras un reinicio, un envío que ya alcanzó `SEND_TO_USER_INBOX` DEBE seguir Ready in
  TikTok sin consultas automáticas ni reenvíos. Un intento con `publish_id` y resultado incierto
  DEBE reconciliarse únicamente consultando ese `publish_id`, siguiendo la recuperación genérica
  existente.
- **FR-028**: Un resultado ambiguo DEBE requerir el reconocimiento manual genérico existente antes
  de permitir un nuevo intento.

#### Errores

- **FR-029**: `spam_risk_too_many_pending_share` DEBE tratarse como fallo determinado, sin
  reintento automático, con un mensaje que explique que existen demasiados uploads pendientes de
  revisión/publicación en TikTok. NO DEBE mantenerse un contador local autoritativo de envíos
  pendientes.
- **FR-030**: El resto de errores DEBEN clasificarse con la taxonomía de la Feature 013 (permiso no
  concedido, token inválido, rate limit, vídeo inválido, URL caducada, errores temporales, estado
  inválido para el `publish_id`), con códigos estables y mensajes seguros adaptados al modo. Un
  error temporal posterior al punto irreversible NUNCA DEBE convertirse en fallo determinado ni en
  reenvío.

#### Persistencia

- **FR-031**: El estado de ejecución DEBE persistirse generalizando la estructura existente de la
  Feature 013 (`tiktok_publish_runs`) mediante una migración versionada para que represente ambos
  modos, distinguiendo explícitamente Direct Post y Upload to Inbox (`INBOX_UPLOAD`), salvo que el plan justifique que
  no puede hacerse limpiamente. NO DEBE crearse una segunda tabla casi idéntica.
- **FR-032**: Para Upload to Inbox DEBE registrarse como mínimo: publicación, intento, modo,
  `publish_id`, progreso de subida no sensible, último estado remoto, `delivered_to_inbox_at`,
  `published_at` si se observa, `fail_reason` seguro y timestamps. NUNCA `upload_url`, tokens ni
  respuestas crudas.
- **FR-033**: Las ejecuciones Direct Post existentes DEBEN seguir siendo legibles y conservar su
  semántica tras la migración.

#### Interfaz y API

- **FR-034**: Para una publicación TikTok de vídeo, la interfaz DEBE permitir elegir el modo,
  integrada con los componentes existentes. En modo Upload to Inbox DEBE mostrar: preview del
  vídeo; la explicación de que la configuración final se hace en TikTok; `Send to TikTok` y
  `Schedule`; el motivo de cualquier acción deshabilitada (incluido "Reconnect to grant
  `video.upload`"); y los estados `Scheduled`, `Uploading` (con progreso), `Processing in TikTok`,
  `Ready in TikTok`, `Published` y `Failed`, junto con `Check status` cuando corresponda.
- **FR-035**: La interfaz DEBE hablar de **"TikTok inbox notification"**, no garantizar una
  notificación push del sistema operativo y dejar claro que la hora programada es la hora de
  inicio del envío, no la de aparición de la notificación ni la de publicación.
- **FR-036**: La API DEBE permitir consultar y editar el modo, ejecutar el envío mediante los
  endpoints genéricos existentes, solicitar `Check status` y exponer el estado de entrega. Ninguna
  respuesta DEBE incluir tokens ni `upload_url`; el `publish_id` no se expone salvo justificación
  diagnóstica en el plan.
- **FR-037**: AutoPublisher NO DEBE automatizar la apertura de la notificación, la edición ni la
  pulsación de Publish en TikTok (sin automatización móvil ni scraping).

#### Seguridad, documentación y calidad

- **FR-038**: Se DEBEN mantener todas las garantías de seguridad de la Feature 013: `upload_url`
  solo en memoria y redactado completamente; access/refresh tokens solo en el almacén seguro; sin
  secretos en SQLite, API, frontend, almacenamiento del navegador ni logs; sin respuestas crudas
  sensibles. DEBEN existir tests que lo verifiquen para el modo Inbox.
- **FR-039**: La documentación (README y `quickstart.md`) DEBE explicar los dos modos de TikTok,
  la reautorización para `video.upload`, el flujo Upload to Inbox, Ready in TikTok frente a
  Published, `Check status`, el límite de envíos pendientes y los resultados del checkpoint V1
  sobre la cuenta pública.

#### Validación real por etapas y stop conditions

- **FR-040**: **Checkpoint V1 (muy temprano, antes de scheduler, interfaz avanzada o
  recuperación)**: manteniendo la cuenta TikTok **pública**, `quickstart.md` DEBE validar con
  TikTok real: ampliación del OAuth a `video.upload`; `Reconnect`; concesión de los tres permisos;
  envío de un vídeo pequeño e inocuo mediante la inicialización de inbox con `FILE_UPLOAD`;
  consulta de estado hasta `SEND_TO_USER_INBOX`; aparición física de la notificación en el móvil;
  apertura del editor de TikTok con el vídeo cargado; y posibilidad de editarlo (sin necesidad de
  publicar). Debe responder explícitamente: "¿Upload to Inbox funciona realmente con nuestra
  cuenta pública y nuestro cliente Sandbox/no auditado?".
- **FR-041**: **Checkpoint V2 (tras V1 PASS)**: DEBE validar multi-chunk, scheduler,
  pausa/reanudación, reinicio, `Check status`, error de envíos pendientes (con fakes; no provocarlo
  deliberadamente en la cuenta real), interfaz completa, seguridad y regresiones, y con TikTok
  real: programar un envío con la cuenta pública, alcanzar `SEND_TO_USER_INBOX`, comprobar la
  notificación, abrir el editor, realizar alguna edición sencilla si procede, publicar manualmente
  desde TikTok, volver a AutoPublisher, `Check status`, observar `PUBLISH_COMPLETE`, confirmar que
  Direct Post (Feature 013) sigue funcionando y seguridad PASS.
- **FR-042**: La implementación DEBE detenerse y revisarse spec/plan si: TikTok exige cuenta
  privada, App Audit o cualquier condición inesperada para Upload to Inbox; no se conceden los tres
  permisos; el endpoint Inbox no admite `FILE_UPLOAD` como se espera; `SEND_TO_USER_INBOX` o
  `PUBLISH_COMPLETE` no significan lo esperado; la notificación no llega o no abre el editor;
  Direct Post deja de funcionar; o aparece algún secreto en base de datos, logs, API o frontend.
- **FR-043**: Los tests automatizados DEBEN ejecutarse offline con fakes y cubrir como mínimo:
  OAuth con tres permisos, conexiones antiguas de dos permisos, `Reconnect` parcial que conserva
  la conexión anterior y renovación; migración del modo (`DIRECT_POST` en existentes, sin default
  en nuevas), modo obligatorio y separación de opciones; intento de entrega `succeeded` no
  reescrito tras `Check status`; preflight; inicialización única sin opciones de Direct Post; subida
  (un chunk, multi-chunk, reintentos, `416`, URL caducada, último chunk ambiguo sin reenvío);
  estados (`SEND_TO_USER_INBOX` detiene el polling, `PUBLISH_COMPLETE`, `FAILED`, desconocidos,
  agotamiento); `Check status`; `spam_risk_too_many_pending_share`; anti-duplicados y reinicio;
  scheduler (programada, pausa, carreras, `AWAITING_USER_ACTION` ignorado por scheduler y recuperación); transiciones y acciones bloqueadas del nuevo estado genérico; seguridad; migración de `tiktok_publish_runs`; y
  regresión de Direct Post, YouTube, Instagram, Threads y la conexión TikTok. Durante el
  desarrollo se ejecutan tests dirigidos; los quality gates completos una vez al final.

### Key Entities *(include if feature involves data)*

- **TikTok Publication Options** (existente, ampliada): añade el **modo** TikTok de la publicación
  (`Direct Post` / `Upload to Inbox`). Las opciones de Direct Post solo aplican a ese modo.
- **TikTok Publish Run** (existente, generalizado): estado remoto de un intento TikTok con su
  **modo**: `publish_id`, plan de subida no sensible, bytes confirmados, fase, write-ahead, último
  estado remoto, `fail_reason` seguro, timestamps y, para Upload to Inbox, `delivered_to_inbox_at` y
  `published_at` observado. Nunca contiene `upload_url` ni credenciales.
- **Inbox delivery state** (derivado, presentación): `Scheduled`, `Uploading`, `Processing in
  TikTok`, `Ready in TikTok` (= `AWAITING_USER_ACTION`), `Published`, `Failed`, calculado a partir de la `Publication`, el
  intento y el TikTok Publish Run.
- **TikTok Connection** (existente, Feature 012): ahora con los permisos concedidos
  `user.info.basic`, `video.publish` y, opcionalmente en conexiones antiguas, `video.upload`.
- **Publication** (existente): sin campos de TikTok; su conjunto de estados genéricos se amplía con el estado neutral `AWAITING_USER_ACTION` (FR-019a), con salidas solo a `PUBLISHED` o `FAILED`.
- **PublicationAttempt** (existente): se reutilizan origen, fases, progreso, errores y resultado determinado/ambiguo; la entrega al inbox lo deja `succeeded`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El checkpoint V1 se completa con la cuenta TikTok pública: un vídeo enviado desde
  AutoPublisher aparece como notificación en el inbox de TikTok y abre el editor con el vídeo
  cargado, o se documenta un STOP con la causa exacta.
- **SC-002**: El usuario puede enviar un vídeo a TikTok en modo Upload to Inbox (manual o
  programado) y verlo en Ready in TikTok sin abrir ninguna herramienta externa aparte de TikTok.
- **SC-003**: Una publicación programada en modo Upload to Inbox inicia su envío una sola vez en la
  ventana de ejecución del scheduler en el 100 % de los ciclos de prueba.
- **SC-004**: 0 envíos duplicados al inbox en todos los escenarios de corte, reinicio, espera del
  usuario y resultado incierto; como máximo un `publish_id` por intento.
- **SC-005**: En el 100 % de los casos en que TikTok indica `SEND_TO_USER_INBOX`, el polling automático se detiene, la publicación queda en `AWAITING_USER_ACTION` (nunca `PUBLISHED`) y el scheduler no vuelve a actuar sobre ella.
- **SC-006**: Tras publicar manualmente desde TikTok, una sola pulsación de `Check status` refleja
  Published cuando TikTok indica `PUBLISH_COMPLETE`.
- **SC-007**: 0 identificadores o enlaces de post inventados y 0 afirmaciones sobre la
  configuración final del post en TikTok.
- **SC-008**: Base de datos, logs, errores, respuestas de la API y almacenamiento del navegador
  contienen 0 tokens y 0 `upload_url` en todos los tests y en la validación real.
- **SC-009**: Ninguna publicación de YouTube, Instagram, Threads o Direct Post alcanza `AWAITING_USER_ACTION`, y Direct Post (Feature 013), YouTube, Instagram, Threads y la conexión TikTok siguen
  pasando sus suites de regresión sin cambios de comportamiento, y Direct Post se valida de nuevo
  con TikTok real tras la reautorización.
- **SC-010**: El 100 % de los rechazos por envíos pendientes muestran un mensaje que explica la
  causa y no se reintentan automáticamente.

## Assumptions

- **Cuenta pública**: hipótesis principal de esta feature; la cuenta TikTok de pruebas permanece
  pública. Para volver a validar Direct Post (restringido a cuenta privada en el entorno no
  auditado) puede ser necesario cambiar temporalmente la cuenta a privada; el plan lo documenta.
- **Modo sin valor por defecto**: el usuario elige explícitamente el modo de cada nueva
  publicación TikTok (sin default en base de datos); las publicaciones TikTok existentes se migran
  como `DIRECT_POST` y conservan su comportamiento (FR-001).
- **Sin consentimiento de Direct Post**: Music Usage Confirmation, privacidad y el resto de
  decisiones del post ocurren en el editor de TikTok; el armado genérico de la Feature 007 y la
  confirmación de `Send to TikTok` son suficientes, salvo que la documentación oficial del flujo
  Upload exija otra UX (el plan lo reconfirma).
- **Caption**: no se envía caption en modo Upload to Inbox salvo que el endpoint lo admita (FR-014);
  mostrar o copiar el caption de AutoPublisher para pegarlo en TikTok queda fuera de alcance.
- **Duración**: sin Creator Info, la duración se valida contra los límites generales de la API; el
  límite propio de la cuenta lo aplica TikTok en su editor.
- **Rate limits** de inicialización y estado: los que fije el plan según la documentación vigente;
  suficientes para un único usuario local.
- **Limitación aceptada — publicación atascada en `AWAITING_USER_ACTION`**: si el usuario descarta
  el contenido dentro de TikTok y TikTok sigue devolviendo `SEND_TO_USER_INBOX`, la publicación
  permanece en `AWAITING_USER_ACTION` sin salida manual local, sin nuevo upload automático y
  pudiendo bloquear la combinación contenido/cuenta. Ninguna acción local elimina el pending share
  remoto de TikTok. Diseñar una salida manual segura (p. ej. "Dismiss") queda fuera de alcance y
  podrá estudiarse en una feature posterior.
- **Fuera de alcance**: automatización móvil o clic automático en TikTok, scraping, Direct Post
  público, App Audit, `video.list`, borrado remoto, analytics, sincronización de metadata editada
  en TikTok, fotos y cross-posting (Feature 015).
- **Dependencias**: Feature 003 (Content e inspección), 004/006/007 (publicación genérica,
  scheduler y armado), 012 (conexión TikTok), 013 (publisher TikTok, transferencia `FILE_UPLOAD` y
  `tiktok_publish_runs`).
