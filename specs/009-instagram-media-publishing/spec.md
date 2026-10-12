# Feature Specification: Publicación real de imágenes y Reels en Instagram

**Feature Branch**: `009-instagram-media-publishing`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Crear la Feature 009 de AutoPublisher: publicación real de imágenes individuales y Reels en Instagram usando la conexión Instagram Professional implementada en Feature 008. Registrar un `InstagramPublisher` real dentro de la arquitectura genérica de publishers, publicable mediante `Publish now` y mediante el scheduler genérico de la Feature 007, con preflight completo, media temporal públicamente accesible mediante una abstracción genérica de media delivery (proveedor elegido en el plan), media containers, espera de procesamiento, `media_publish` protegido con write-ahead, recuperación segura tras reinicio sin duplicados, cleanup del media temporal, opciones específicas de Instagram (`is_ai_generated`, `share_to_feed`, `alt_text`), caption determinista sin truncado, errores seguros y tests sin servicios reales."

## Contexto

Desde la Feature 008, una `Account` de plataforma Instagram puede estar vinculada (`Connected`)
a una cuenta Instagram Professional real (Business o Creator) mediante Instagram API with
Instagram Login, con la credencial de larga duración guardada solo en el almacén seguro del
sistema operativo y el Instagram account ID como identidad autoritativa. Sin embargo, todavía
no se puede publicar nada en Instagram.

Desde las Features 006 y 007, AutoPublisher tiene una ejecución de publicaciones **genérica**:
preflight, estados `PUBLISHING` / `PUBLISHED` / `FAILED`, `PublicationAttempt` con origen
(`manual` / `scheduled`), progreso, errores seguros, resultado remoto, protección frente a
ejecuciones duplicadas, recuperación de intentos interrumpidos y un scheduler local que
ejecuta automáticamente publicaciones programadas y armadas. Hoy el único publisher registrado
es el de YouTube.

Esta feature registra un **publisher de Instagram real** dentro de esa arquitectura genérica,
de forma que una `Publication` destinada a una `Account` Instagram conectada pueda publicarse:

- manualmente, mediante `Publish now`;
- automáticamente, mediante el scheduler genérico existente;

conservando historial, intentos, progreso, errores y enlace remoto igual que YouTube. No se
crea un scheduler ni un ejecutor específicos de Instagram.

Flujo conceptual:

`Publication` → preflight genérico + preflight de Instagram → preparar media compatible →
hacer el media temporalmente accesible a Meta → crear media container → esperar
procesamiento → `media_publish` → confirmar publicación → guardar media ID, permalink y
resultado → `PUBLISHED` / intento `succeeded` → limpiar el media temporal (best-effort, fuera
de la decisión de éxito).

Alcance de media en esta versión:

1. **Imagen individual** (Content de tipo imagen) → publicación normal en el feed.
2. **Vídeo individual** (Content de tipo vídeo) → publicación como **Reel**.

Principios rectores de la feature:

- **Nunca publicar duplicados**: ante un resultado incierto de la acción final de
  publicación, AutoPublisher se detiene y pide revisión manual en lugar de volver a intentarlo.
- **El original nunca se modifica**: cualquier archivo derivado es temporal y se elimina.
- **Ningún secreto sale de donde debe**: ni tokens de Instagram, ni credenciales del
  proveedor de media temporal, ni URLs temporales firmadas aparecen en logs, base de datos,
  respuestas al frontend o mensajes de error.
- **Exposición mínima**: el media solo es públicamente accesible el tiempo estrictamente
  necesario para que Meta lo obtenga, y solo ese archivo.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicar ahora una imagen en Instagram (Priority: P1)

Como usuario, quiero pulsar `Publish now` en una publicación de una imagen destinada a una
cuenta Instagram conectada y ver cómo se publica en el feed real, con su enlace a Instagram,
sin que mi archivo original cambie.

**Why this priority**: es el camino más corto que demuestra el flujo completo de publicación
en Instagram (media temporal → container → publicación → resultado → cleanup).

**Independent Test**: con fakes de Meta y del proveedor de media temporal, crear una
publicación de una imagen JPEG para una cuenta Instagram `Connected`, declarar la opción
AI-generated, ejecutar `Publish now` y comprobar: la publicación queda `PUBLISHED`, el
intento `succeeded` con origen `manual`, se guardan media ID y permalink, el media temporal se
ha eliminado, el archivo original es idéntico byte a byte y no hay secretos en base de datos,
logs ni respuestas de la API.

**Acceptance Scenarios**:

1. **Given** una publicación `UNSCHEDULED` o `SCHEDULED` de un Content imagen destinada a una
   `Account` Instagram `Connected`, con cuenta y proyecto activos, opciones de Instagram
   válidas y media delivery configurado, **When** el usuario pulsa `Publish now` y confirma,
   **Then** se ejecuta el preflight completo y, si pasa, la publicación pasa a `PUBLISHING` y
   se crea un `PublicationAttempt` con origen `manual`.
2. **Given** una ejecución en curso, **When** avanza, **Then** el usuario ve fases
   reconocibles (preparar media, hacerla disponible para Instagram, crear el container,
   procesamiento, publicar, verificar) y nunca un porcentaje inventado.
3. **Given** que Instagram confirma inequívocamente la publicación, **When** termina la
   ejecución, **Then** primero se persisten el Instagram media ID como identificador remoto,
   el permalink como enlace remoto cuando la API lo proporcione y el resultado remoto; después
   la publicación queda `PUBLISHED` y el intento `succeeded`; la interfaz muestra
   `Open on Instagram`. Solo a continuación se ejecuta la limpieza como operación
   best-effort, que no forma parte de la decisión de éxito.
4. **Given** una imagen PNG o WebP, **When** se publica, **Then** se genera una copia técnica
   temporal en el formato aceptado por Instagram sin recortar, reencuadrar ni redimensionar
   creativamente; el Content original permanece intacto y la copia temporal se elimina al
   terminar.
5. **Given** una publicación terminada (con éxito o con fallo), **When** se inspecciona el
   proveedor de media temporal, **Then** el recurso público temporal ya no existe (salvo fallo
   de limpieza, que queda registrado como aviso y pendiente de limpieza posterior sin alterar
   el estado `PUBLISHED` ni el intento `succeeded`).
6. **Given** una publicación `PUBLISHED`, **When** el usuario consulta su detalle, **Then** ve
   el tipo de publicación (`Image Post`), el caption enviado, las opciones usadas, el
   historial de intentos y `Open on Instagram`.

---

### User Story 2 - Publicar ahora un vídeo como Reel (Priority: P1)

Como usuario, quiero publicar un vídeo de mi biblioteca como Reel en Instagram con
`Publish now`, esperando a que Instagram termine de procesarlo antes de publicarlo.

**Why this priority**: los Reels son el segundo tipo de media del alcance y requieren el
procesamiento asíncrono del container, la parte más delicada del flujo.

**Independent Test**: con fakes, publicar un vídeo compatible; simular que el container pasa
por estado "en progreso" varias consultas antes de `FINISHED`; comprobar que la espera usa
intervalos y un tiempo máximo acotados, que solo después se ejecuta `media_publish`, y que el
resultado queda `PUBLISHED` con media ID, permalink y media temporal eliminado.

**Acceptance Scenarios**:

1. **Given** una publicación de un Content vídeo destinada a una `Account` Instagram
   `Connected`, **When** el usuario ejecuta `Publish now`, **Then** el preflight comprueba el
   vídeo contra los requisitos vigentes de Reels **antes** de hacer público ningún archivo y,
   si cumple, se publica como Reel.
2. **Given** un container de Reel en procesamiento, **When** AutoPublisher espera, **Then**
   consulta su estado con un intervalo y un tiempo máximo acotados, sin espera activa
   continua, y solo ejecuta `media_publish` cuando el container está listo (`FINISHED`).
3. **Given** un container que termina en estado de error o caducado, **When** se detecta,
   **Then** la ejecución falla con un error seguro de procesamiento o caducidad, no se ejecuta
   `media_publish`, la publicación queda `FAILED` con resultado determinado (no se publicó
   nada) y el media temporal se limpia.
4. **Given** un container que no termina dentro del tiempo máximo, **When** se alcanza,
   **Then** la ejecución falla con un error seguro de tiempo de procesamiento agotado, sin
   ejecutar `media_publish`.
5. **Given** un vídeo que no cumple algún requisito (contenedor, codec, duración, resolución,
   relación de aspecto, frame rate, bitrate, tamaño u otro), **When** se ejecuta el preflight,
   **Then** falla indicando qué requisito no se cumple, sin hacer público el archivo, sin crear
   container y sin transcodificar ni modificar el vídeo.
6. **Given** un Reel, **When** el usuario configura `share_to_feed` (si la API vigente lo
   soporta), **Then** el valor elegido se envía y se conserva en el historial; si no lo
   configura, se aplica el valor por defecto documentado y visible en la interfaz.

---

### User Story 3 - Configurar caption y opciones de Instagram (Priority: P1)

Como usuario, quiero ver exactamente el caption que se enviará a Instagram y configurar las
opciones propias de Instagram (declaración de contenido generado por IA, compartir el Reel en
el feed, texto alternativo de imágenes) antes de publicar o programar.

**Why this priority**: la declaración de contenido IA es una decisión explícita del usuario
que no puede inferirse, y el caption es lo que verá el público; ambos deben estar resueltos
antes de cualquier publicación real.

**Independent Test**: crear publicaciones Instagram de imagen y de vídeo; comprobar que el
caption mostrado coincide carácter a carácter con el enviado al fake de Meta; que la
declaración IA debe elegirse explícitamente; que `alt_text` solo aparece en imágenes y
`share_to_feed` solo en Reels; que las opciones persisten tras reiniciar; y que las
publicaciones de otras plataformas no muestran estas opciones.

**Acceptance Scenarios**:

1. **Given** una publicación Instagram, **When** el usuario abre su detalle, **Then** ve el
   caption final exacto, construido de forma determinista a partir de la descripción efectiva
   y los hashtags efectivos de la publicación (el título efectivo no se envía).
2. **Given** un caption que excede algún límite vigente de Instagram (longitud, número de
   hashtags o menciones), **When** se intenta publicar, programar con publicación automática
   armada o se consulta la validez, **Then** se informa del límite excedido y la publicación no
   se ejecuta; el caption nunca se trunca silenciosamente.
3. **Given** una publicación Instagram sin declaración AI-generated, **When** se intenta
   ejecutar, **Then** el preflight falla pidiendo que el usuario declare explícitamente si el
   contenido está generado por IA (Sí/No); AutoPublisher nunca lo infiere.
4. **Given** una publicación de imagen, **When** el usuario escribe un texto alternativo
   dentro del límite vigente, **Then** se guarda y se envía a Instagram; si excede el límite, se
   rechaza con un error claro; si lo deja vacío, no se envía.
5. **Given** una publicación de vídeo (Reel), **When** el usuario consulta las opciones,
   **Then** puede configurar `share_to_feed` (si está soportado) y no se ofrece `alt_text`
   salvo que la API vigente lo admita para Reels.
6. **Given** una publicación de otra plataforma, **When** el usuario la consulta, **Then** no
   aparece ninguna opción de Instagram.
7. **Given** una publicación Instagram en `PUBLISHING` o `PUBLISHED`, **When** el usuario
   intenta editar sus opciones o metadata, **Then** la edición se rechaza (mismas reglas que
   el resto de la metadata en esos estados).

---

### User Story 4 - Validar todo antes de cualquier efecto remoto de publicación (Priority: P1)

Como usuario, quiero que cualquier problema detectable (cuenta desconectada, archivo
desaparecido, media incompatible, caption inválido, falta de media delivery, cuota agotada…)
se detecte antes de que AutoPublisher haga público ningún archivo o cree nada en Instagram.

En esta spec, "antes de cualquier efecto externo" significa **antes de cualquier efecto
remoto de publicación o de media delivery**. Durante el preflight sí se permiten operaciones
necesarias y seguras: obtener o renovar la credencial mediante la Feature 008, consultas de
solo lectura a Meta, comprobar la identidad, consultar la cuota (`content_publishing_limit`)
e inspeccionar localmente el media. Antes de superar el preflight NO se permite subir ni
exponer el media en el proveedor de media delivery, crear un media container, ejecutar
`media_publish` ni ningún otro efecto remoto que pueda producir o preparar material público
de la publicación.

**Why this priority**: un fallo a mitad de flujo deja recursos públicos o containers
huérfanos; un preflight completo evita efectos remotos de publicación innecesarios.

**Independent Test**: para cada condición de preflight, preparar el fallo con fakes y
comprobar que la publicación no pasa a `PUBLISHING`, que no se ha subido nada al proveedor de
media temporal, que no se ha creado ningún container y que el usuario ve un error seguro y
comprensible.

**Acceptance Scenarios**:

1. **Given** cualquiera de estas condiciones: proyecto o cuenta inactivos, cuenta no
   Instagram, cuenta `Not connected` o `Reconnect required`, credencial no utilizable,
   identidad no disponible según las reglas de la Feature 008, Content o archivo inexistente,
   tipo de media no soportado, media incompatible y no convertible, caption inválido, opciones
   de Instagram sin declarar, media delivery no configurado, cuota de publicación
   agotada (cuando pueda consultarse) o ejecución ya en curso, **When** se intenta ejecutar,
   **Then** el preflight falla con un error específico, la publicación no pasa a
   `PUBLISHING`, no se hace público ningún archivo y no se crea ningún container.
2. **Given** que no existe una configuración válida de media delivery, **When** se intenta
   publicar, **Then** el preflight falla con un error claro de configuración que indica dónde
   está la documentación para configurarlo.
3. **Given** que la credencial requiere reconexión, **When** se ejecuta el preflight, **Then**
   falla con el error de reconexión requerida de la Feature 008, sin efectos remotos de
   publicación ni de media delivery.
6. **Given** un preflight que obtiene o renueva la credencial, comprueba la identidad y
   consulta la cuota en Meta, **When** termina (con éxito o con fallo), **Then** solo se han
   realizado esas operaciones seguras: nada se ha subido al proveedor de media delivery y no
   existe ningún container.
4. **Given** que la cuota de publicación de la cuenta está agotada según Meta, **When** se
   ejecuta el preflight, **Then** falla con un error seguro de cuota agotada; AutoPublisher usa
   el valor devuelto por Meta como fuente de verdad, no un número fijo propio.
5. **Given** una publicación válida, **When** el usuario consulta su comprobación de
   publicación (la comprobación local existente), **Then** ve los problemas detectables
   localmente de Instagram (caption, opciones, compatibilidad del media, configuración de
   media delivery) igual que hoy ve los de YouTube.

---

### User Story 5 - Publicación automática programada en Instagram (Priority: P2)

Como usuario, quiero programar una publicación Instagram con publicación automática armada y
que el scheduler genérico la publique a su hora, exactamente una vez, igual que hace con
YouTube.

**Why this priority**: la automatización es el valor principal de AutoPublisher, pero
depende de que la publicación manual (P1) funcione.

**Independent Test**: con reloj inyectable y fakes, programar una publicación Instagram
armada, avanzar el reloj y comprobar que el scheduler genérico la ejecuta una sola vez con
origen `scheduled`; repetir con la automatización pausada y comprobar que no se ejecuta; y
comprobar mediante un test de arquitectura que el scheduler no contiene código de Instagram.

**Acceptance Scenarios**:

1. **Given** una publicación Instagram `SCHEDULED`, armada y vencida dentro de la ventana de
   la Feature 007, **When** el scheduler hace su ciclo, **Then** la ejecuta a través del mismo
   servicio de ejecución que `Publish now`, con origen `scheduled`, y el resultado se refleja
   igual que en una ejecución manual.
2. **Given** la automatización global en pausa, **When** vence una publicación Instagram
   armada, **Then** no se ejecuta automáticamente; `Publish now` sigue disponible y una
   ejecución Instagram ya en curso no se cancela.
3. **Given** un `Publish now` y un ciclo del scheduler sobre la misma publicación, o dos
   ciclos concurrentes, **When** coinciden, **Then** como máximo una ejecución comienza.
4. **Given** que el preflight de Instagram falla a la hora programada, **When** el scheduler
   lo detecta, **Then** se aplica el comportamiento genérico de la Feature 007 para fallos de
   preflight (sin `PUBLISHING`, sin efectos remotos de publicación ni de media delivery,
   motivo visible).

---

### User Story 6 - Nunca publicar un duplicado ante fallos, cortes o reinicios (Priority: P2)

Como usuario, quiero la garantía de que, aunque se corte la red, Meta no responda o
AutoPublisher se reinicie a mitad de una publicación, nunca aparecerán dos posts iguales en
mi Instagram por culpa de AutoPublisher.

**Why this priority**: un post duplicado en una cuenta real es el fallo más visible y dañino
(Constitution, principio V).

**Independent Test**: con fakes, interrumpir la ejecución en cada fase (antes del container,
con container creado, justo antes y durante `media_publish`, tras `media_publish`) y comprobar
en cada caso: el estado final, si el resultado está determinado o es ambiguo, que nunca se
ejecuta `media_publish` dos veces automáticamente, que no se crean containers sin límite y que
el media temporal termina limpiándose o queda registrado para limpieza.

**Acceptance Scenarios**:

1. **Given** una ejecución que falla o se interrumpe antes de crear el container, **When**
   termina o el backend se reinicia, **Then** la publicación queda `FAILED` con resultado
   determinado (no se publicó nada) y el media temporal se limpia (o se detecta y limpia como
   abandonado).
2. **Given** una ejecución con container creado y sin haber iniciado `media_publish`, **When**
   falla o se interrumpe, **Then** la publicación queda `FAILED` con resultado determinado; un
   reintento posterior puede reutilizar ese container si sigue siendo válido y el plan
   demuestra que es seguro, sin crear otro innecesariamente.
3. **Given** que AutoPublisher va a ejecutar `media_publish`, **When** lo hace, **Then** antes
   ha registrado y confirmado de forma persistente la fase de publicación final
   (write-ahead).
4. **Given** una llamada a `media_publish` sin respuesta concluyente (timeout, corte de
   conexión, fin del proceso o respuesta inesperada), **When** se evalúa el resultado, **Then**
   AutoPublisher NO crea otro container ni repite `media_publish`; si un mecanismo oficial
   permite demostrar inequívocamente el resultado (por ejemplo, el estado del container), lo
   usa para recuperar el resultado; si no, marca la ejecución como ambigua y pide al usuario
   comprobar Instagram.
5. **Given** una publicación `FAILED` cuyo último intento es ambiguo y llegó a la fase final
   con un container conocido, **When** el usuario consulta la comprobación de publicación o
   pulsa `Publish now`, **Then** AutoPublisher consulta primero, solo en lectura, el estado
   del container original: si Instagram confirma `PUBLISHED`, la publicación pasa a
   `PUBLISHED` y el intento a `succeeded` (resultado determinado, sin identidad remota
   inferida, con aviso) sin pedir ninguna confirmación y sin permitir nuevos intentos.
5a. **Given** esa misma publicación, **When** el container no confirma `PUBLISHED` (otro
   estado o consulta fallida), **Then** el intento sigue ambiguo y cualquier nueva ejecución
   manual exige que el usuario reconozca explícitamente que ha comprobado en Instagram que el
   post no se publicó (mismo modelo que la Feature 006); el scheduler nunca la reintenta.
6. **Given** una publicación `PUBLISHED`, **When** ocurre cualquier reinicio o ciclo del
   scheduler, **Then** nunca se vuelve a publicar.
7. **Given** que la limpieza del media temporal falla después de que Instagram haya publicado
   (la limpieza siempre ocurre después de persistir `PUBLISHED` y el intento `succeeded`),
   **When** termina la ejecución, **Then** la publicación sigue `PUBLISHED` (nunca vuelve a
   `PUBLISHING` ni pasa a `FAILED`), el intento sigue `succeeded`, se registra un aviso seguro
   y la limpieza queda registrada como pendiente para un intento posterior best-effort.
8. **Given** un crash entre la creación/exposición del recurso temporal y el registro de su
   referencia, **When** el backend vuelve a arrancar, **Then** el recurso no queda públicamente
   accesible indefinidamente: o bien su referencia no sensible ya estaba persistida y se limpia,
   o bien el proveedor lo expira de forma automática e independiente de AutoPublisher (FR-016a).

---

### User Story 7 - Entender los fallos y la pérdida de conexión (Priority: P3)

Como usuario, quiero que cualquier fallo de una publicación Instagram me explique qué ha
pasado y qué puedo hacer, y que una credencial invalidada por Meta marque la cuenta para
reconexión sin confundirla con un fallo temporal.

**Why this priority**: mejora la recuperabilidad y la confianza, sobre flujos ya cubiertos.

**Independent Test**: con fakes, provocar cada categoría de error (temporal, definitivo,
credencial, media incompatible, cuota, entrega del media, procesamiento, resultado ambiguo) y
comprobar el código seguro, el mensaje, el estado de la publicación, el estado de la conexión
de Instagram y la ausencia de respuestas crudas de Meta.

**Acceptance Scenarios**:

1. **Given** que Meta invalida definitivamente la credencial durante una ejecución, **When**
   se detecta, **Then** la conexión pasa a `Reconnect required` según las reglas de la Feature
   008, la ejecución falla de forma segura y no se reintenta ningún efecto no idempotente.
2. **Given** un error temporal de red o de disponibilidad de Meta, **When** ocurre, **Then** la
   conexión NO pasa a `Reconnect required`.
3. **Given** cualquier fallo, **When** se muestra o registra, **Then** usa un código estable y
   seguro y un mensaje comprensible, sin respuestas crudas de Meta, tokens, URLs temporales ni
   credenciales del proveedor de media temporal.
4. **Given** una publicación `FAILED`, **When** el usuario la consulta, **Then** ve el último
   error, si el resultado remoto está determinado o es ambiguo, y el historial de intentos con
   su origen.

---

### Edge Cases

- **Archivo del Content eliminado o modificado entre programación y ejecución**: el preflight
  falla con archivo no disponible, sin efectos remotos de publicación ni de media delivery.
- **Imagen fuera de los límites vigentes de Instagram** (relación de aspecto, dimensiones,
  tamaño) que no puede resolverse con una conversión técnica de formato: el preflight falla
  explicando el requisito; nunca se recorta ni redimensiona creativamente en silencio.
- **Conversión técnica a JPEG imposible o con pérdida de información visual significativa
  inaceptable** (por ejemplo, imágenes animadas o perfiles de color no convertibles de forma
  segura según la política del plan): el preflight falla con explicación.
- **Imagen con transparencia**: la política de conversión (por ejemplo, fondo aplicado) se
  define y documenta en el plan; nunca se aplica silenciosamente una transformación no
  documentada.
- **Herramienta de inspección de vídeo no disponible**: el preflight sigue el patrón de la
  Feature 003; si no se puede verificar un requisito obligatorio, falla con un mensaje claro en
  lugar de publicar a ciegas.
- **Caption vacío** (sin descripción ni hashtags): se permite si Instagram lo permite; la
  interfaz lo muestra claramente como vacío.
- **Media delivery configurado pero inaccesible** (red, credenciales del proveedor
  rechazadas): la ejecución falla con error de entrega del media antes de crear el container;
  no se crea nada en Instagram.
- **Meta no puede descargar el media** (URL no accesible, tipo/longitud de contenido
  incorrecto): el container falla con un error seguro de entrega/procesamiento; no se ejecuta
  `media_publish`.
- **Container caducado** antes de `media_publish` (por ejemplo, reintento tardío tras un
  fallo): no se usa; se trata como caducado y, si procede, un nuevo intento crea un container
  nuevo desde el principio.
- **Cuota agotada entre el preflight y `media_publish`**: la ejecución falla con cuota
  agotada sin publicar; si Meta rechaza `media_publish` por cuota, el resultado es determinado
  (no se publicó).
- **Cuota no consultable temporalmente**: la política (continuar o fallar) se decide en el
  plan; nunca se inventa un valor.
- **Reinicio con media temporal público y sin container**: al arrancar se detecta el recurso
  abandonado y se limpia (best-effort).
- **Crash entre crear/exponer el recurso temporal y persistir su referencia**: el diseño no
  puede depender únicamente de "crear recurso público → después guardar cómo encontrarlo";
  la protección crash-safe se define en FR-016a.
- **Fallo de limpieza tras una publicación confirmada**: la publicación sigue `PUBLISHED` y
  el intento `succeeded`; solo se registra un aviso y la limpieza pendiente.
- **Reinicio con container en procesamiento**: la publicación queda `FAILED` (interrumpida,
  resultado determinado porque `media_publish` no se inició); el media temporal y el container
  se gestionan según la política de reutilización/caducidad del plan.
- **Reinicio con la fase de publicación final registrada**: resultado ambiguo salvo que un
  mecanismo oficial lo resuelva de forma inequívoca; nunca se repite `media_publish`
  automáticamente.
- **AutoPublisher lleva horas encendido**: el media delivery debe seguir funcionando para
  publicaciones programadas sin intervención del usuario (sin sesiones o túneles que caduquen
  en silencio).
- **Desconexión de Instagram mientras hay una ejecución en curso**: se aplica la regla
  genérica existente (no se permite desconectar una cuenta con publicaciones en `PUBLISHING`).
- **Cambio de identidad de la cuenta Instagram** (ID distinto del vinculado): el preflight
  falla con el error de identidad de la Feature 008; nunca se publica en otra cuenta.
- **Content de tipo no soportado o publicación con varios archivos**: no existe en esta
  versión; cualquier tipo distinto de imagen o vídeo individual se rechaza en preflight.
- **App de Meta en Development Mode**: la publicación con la cuenta propia como tester se
  valida en el quickstart; si Meta exige App Review para publicar incluso en pruebas, se
  documenta y se detiene la validación correspondiente sin intentar eludirlo.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance e integración con la arquitectura genérica

- **FR-001**: El sistema DEBE registrar un publisher de Instagram en el registro genérico de
  publishers existente, de modo que una `Publication` destinada a una `Account` Instagram se
  ejecute mediante el mismo servicio de ejecución, preflight genérico, estados,
  `PublicationAttempt`, progreso, errores y resultado remoto que YouTube.
- **FR-002**: Solo DEBEN poder publicarse en Instagram: Content de tipo imagen como
  publicación de imagen individual en el feed (`Image Post`) y Content de tipo vídeo como
  Reel. Cualquier otro caso se rechaza en preflight.
- **FR-003**: El núcleo genérico de ejecución y el scheduler NO DEBEN importar ni contener
  lógica específica de Instagram ni de ningún proveedor concreto de media delivery; solo
  interactúan con el publisher a través de la interfaz/registro genéricos existentes. DEBE
  existir un test de arquitectura que lo garantice.
- **FR-004**: NO DEBE crearse un scheduler, ejecutor, estado de `Publication` ni modelo de
  intentos específicos de Instagram. Cualquier extensión de la interfaz genérica necesaria
  (por ejemplo, nuevas fases internas o un punto de extensión de recuperación) DEBE ser
  neutral respecto a la plataforma y no romper el publisher de YouTube.
- **FR-005**: El publisher DEBE reutilizar exclusivamente la conexión y los servicios
  internos de la Feature 008 (credencial válida, identidad autoritativa, reglas de
  `Reconnect required`). Esta feature NO DEBE introducir un nuevo flujo OAuth ni otro sistema
  de credenciales de Instagram.
- **FR-006**: La versión de Graph API y la configuración base de Instagram DEBEN proceder de
  una única fuente común compartida con la Feature 008, sin duplicarse. La versión vigente y
  los endpoints exactos DEBEN verificarse en el plan contra la documentación oficial.

#### Media delivery temporal

- **FR-007**: El sistema DEBE definir una abstracción genérica de media delivery,
  independiente de Instagram, responsable de: recibir un archivo local, publicarlo en una
  ubicación HTTPS temporal accesible por Meta, devolver su URL, mantenerla disponible mientras
  Meta la necesite y eliminarla/revocarla al terminar, incluida la limpieza tras errores cuando
  sea segura.
- **FR-008**: La implementación concreta del proveedor de media delivery DEBE elegirse y
  justificarse en el plan tras comparar, como mínimo, almacenamiento temporal de objetos con
  URLs públicas/temporales (Cloudflare R2 o equivalente), un túnel público controlado hacia un
  servidor local y otras alternativas razonables, evaluando: fiabilidad para publicaciones
  programadas, funcionamiento con AutoPublisher encendido durante horas, seguridad,
  caducidad, cleanup, comportamiento HTTP que Meta requiera (GET/HEAD/Range, redirecciones,
  `Content-Type`, `Content-Length`), tamaño de vídeo, coste, configuración y credenciales
  adicionales, comportamiento tras reinicio y la filosofía local-first. Como la Constitution
  excluye infraestructura cloud salvo requisito explícito, esta especificación reconoce
  explícitamente el requisito de media públicamente accesible y el plan DEBE justificar la
  opción elegida en su Constitution Check.
- **FR-009**: Los Quick Tunnels anónimos u otras herramientas documentadas como solo de
  desarrollo/pruebas NO DEBEN usarse como solución de producción.
- **FR-010**: El recurso temporal DEBE: servirse por HTTPS; usar identificadores/rutas
  impredecibles; exponer únicamente el archivo de esa publicación; no permitir listados de
  directorios ni escritura pública; existir el mínimo tiempo necesario; no revelar rutas
  locales; y no contener tokens de Instagram.
- **FR-011**: Si la URL temporal contiene firmas, credenciales temporales o parámetros
  sensibles, DEBE tratarse completa como secreto: no DEBE aparecer en logs, mensajes de error,
  respuestas al frontend ni almacenarse permanentemente en la base de datos salvo que el plan
  demuestre que es necesario y seguro. Cualquier aparición accidental DEBE redactarse.
- **FR-012**: El sistema NO DEBE mantener ninguna copia pública permanente del contenido.
- **FR-013**: Las credenciales y configuración del proveedor de media delivery DEBEN cargarse
  desde configuración local no versionada (o el almacén seguro, si procede), nunca enviarse al
  frontend, y `.gitignore` DEBE cubrir sus archivos. DEBE documentarse cómo configurarlo.
- **FR-014**: Si no existe configuración válida de media delivery, el preflight DEBE fallar
  antes de cualquier efecto remoto de publicación o de media delivery con un error claro de
  configuración; la publicación NO DEBE pasar a `PUBLISHING`.
- **FR-015**: El media temporal DEBE eliminarse/revocarse en cuanto Meta deje de necesitarlo
  (momento exacto a verificar en el plan), tanto tras éxito como tras fallo cuando sea seguro.
- **FR-016**: El sistema DEBE poder detectar y limpiar (best-effort) recursos temporales
  abandonados tras reinicios o fallos de limpieza, de forma que ninguna URL pública quede
  disponible indefinidamente. El mecanismo concreto (registro persistente no sensible de
  recursos pendientes, caducidad nativa del proveedor u otro) se decide en el plan.
- **FR-016a**: El media delivery DEBE ser crash-safe frente a un fallo entre crear/exponer el
  recurso temporal y persistir cómo encontrarlo: el diseño NUNCA DEBE depender únicamente de
  la secuencia "crear recurso público → después guardar su referencia" sin protección frente a
  un crash intermedio. La solución elegida DEBE garantizar al menos una de estas propiedades:
  - existe una referencia no sensible y recuperable persistida (con commit) **antes** de que
    el recurso quede públicamente accesible; o
  - el proveedor aplica una expiración/lifecycle automático e independiente de AutoPublisher
    que garantiza que el recurso deja de existir o de ser accesible aunque el proceso muera
    antes de registrar la referencia; o
  - otro mecanismo equivalente cuya seguridad frente a crashes se demuestre en el plan.
  Las URLs firmadas completas siguen sin persistirse (FR-011). El mecanismo concreto se decide
  en el plan según el proveedor de media delivery elegido.

#### Preparación de imágenes

- **FR-017**: El plan DEBE verificar los requisitos vigentes de Meta para imágenes (formatos,
  dimensiones, relación de aspecto, tamaño, perfil de color) y fijar una política explícita
  para JPEG, PNG y WebP.
- **FR-018**: Cuando Instagram no acepte el formato original, el sistema PUEDE generar una
  copia técnica temporal en un formato aceptado (por ejemplo JPEG) solo si no altera
  intencionadamente la composición: NO DEBE recortar, reencuadrar ni redimensionar
  creativamente de forma silenciosa. Si la conversión segura no es posible, el preflight DEBE
  fallar con explicación.
- **FR-019**: El Content original NUNCA DEBE modificarse ni convertirse permanentemente. Las
  copias derivadas DEBEN existir solo durante la publicación y eliminarse después.

#### Preparación de vídeo / Reel

- **FR-020**: El plan DEBE verificar los requisitos vigentes de Reels (contenedores, codecs,
  audio, duración, resolución, relación de aspecto, frame rate, bitrate, tamaño máximo).
- **FR-021**: El preflight DEBE comprobar el vídeo contra esos requisitos usando la inspección
  de media existente (patrón de la Feature 003) antes de hacer público el archivo, e indicar
  qué requisito no se cumple.
- **FR-022**: El sistema NO DEBE transcodificar ni modificar vídeos en esta versión.

#### Caption

- **FR-023**: El caption DEBE construirse de forma simple y determinista a partir de la
  metadata efectiva existente de la `Publication`: descripción efectiva y hashtags efectivos
  (el formato exacto de unión se fija en el plan, siguiendo el precedente de la descripción de
  YouTube). El título efectivo NO DEBE enviarse a Instagram.
- **FR-024**: El caption DEBE validarse contra los límites vigentes de Instagram (longitud,
  hashtags, menciones), verificados en el plan. Un caption inválido DEBE detectarse en el
  preflight, antes de cualquier efecto remoto de publicación o de media delivery, y NUNCA DEBE truncarse silenciosamente.
- **FR-025**: La interfaz DEBE mostrar el caption exacto que se enviará.

#### Opciones específicas de Instagram

- **FR-026**: Cada `Publication` destinada a Instagram DEBE poder tener opciones específicas
  de Instagram persistidas en una estructura propia de Instagram, separada del modelo común
  de `Publication` (mismo patrón que las opciones de YouTube). El modelo común NO DEBE recibir
  campos de Instagram.
- **FR-027**: El usuario DEBE declarar explícitamente si el contenido está generado por IA
  (`is_ai_generated`, Sí/No), que se envía como el parámetro oficial de self-disclosure de Meta
  para imágenes y Reels cuando la API vigente lo soporte. El sistema NUNCA DEBE inferirlo. Sin
  declaración, la publicación no puede ejecutarse (preflight falla) y la comprobación local
  existente de la publicación DEBE mostrarlo como problema pendiente, igual que la
  declaración de contenido sintético de YouTube.
- **FR-028**: Para Reels, si la API vigente soporta `share_to_feed`, DEBE exponerse como opción
  con un valor por defecto explícito, documentado y visible en la interfaz (elegido en el
  plan, sin asumir el default de Meta sin documentarlo). NO DEBE aplicarse a imágenes.
- **FR-029**: Para imágenes, si la API vigente lo permite, DEBE soportarse un `alt_text`
  opcional, validado con el límite vigente de Meta. NUNCA DEBE generarse automáticamente.
- **FR-030**: Las opciones de Instagram DEBEN poder editarse mientras la publicación sea
  editable y NO DEBEN poder editarse en `PUBLISHING` ni `PUBLISHED`, igual que la metadata
  común. No DEBEN mostrarse ni aceptarse en publicaciones de otras plataformas.

#### Preflight

- **FR-031**: Antes de cualquier efecto remoto de publicación o de media delivery, el sistema
  DEBE validar como mínimo: publicación válida y ejecutable; `Account` y
  proyecto activos; `Account` de plataforma Instagram; conexión `Connected`; credencial
  utilizable e identidad disponible según la Feature 008; Content y archivo existentes; tipo de
  media soportado; media compatible o convertible según la política; caption válido; opciones
  de Instagram válidas y declaradas; media delivery configurado; cuota de publicación
  disponible cuando pueda consultarse; ninguna ejecución activa; y cualquier condición
  genérica existente.
- **FR-031a**: Durante el preflight SÍ se permiten operaciones necesarias y seguras: obtener
  o renovar la credencial mediante los servicios de la Feature 008, consultas de solo lectura
  a Meta, comprobar la identidad de la cuenta, consultar la cuota (`content_publishing_limit`)
  e inspeccionar localmente el media (incluida la preparación local de derivados temporales
  no expuestos). Antes de superar el preflight NO se permite: subir o exponer el media en el
  proveedor de media delivery, crear un media container, ejecutar `media_publish` ni ningún
  otro efecto remoto que pueda producir o preparar material público de la publicación.
- **FR-032**: Las reglas comunes del preflight DEBEN reutilizarse de las Features 006/007 sin
  duplicarse; el publisher de Instagram solo añade sus comprobaciones específicas.
- **FR-033**: Si el preflight falla, la publicación NO DEBE pasar a `PUBLISHING`, NO DEBE
  subirse ni exponerse ningún archivo en el proveedor de media delivery, NO DEBE crearse ningún
  container ni producirse ningún otro efecto remoto de publicación. Las operaciones seguras de
  FR-031a que ya se hubieran realizado (por ejemplo, una renovación de credencial) no se
  consideran efectos de publicación.

#### Límite de publicación

- **FR-034**: El plan DEBE verificar el contrato vigente de `content_publishing_limit`. Cuando
  exista un endpoint autoritativo, el sistema DEBE consultar el uso/configuración real cuando
  sea necesario y tratar el valor de Meta como fuente de verdad; NO DEBE depender únicamente
  de un número fijo propio.
- **FR-035**: Si no hay cuota disponible, la ejecución DEBE fallar con un error seguro antes de
  `media_publish` siempre que sea posible. Esta comprobación NO DEBE convertirse en un sistema
  propio de analytics ni de histórico de uso.

#### Containers y procesamiento

- **FR-036**: La publicación DEBE seguir el modelo oficial vigente de containers: crear el
  container con la URL temporal y los parámetros del tipo de media; consultar su estado cuando
  requiera procesamiento; esperar al estado listo (`FINISHED`); ejecutar `media_publish`;
  obtener el Instagram media ID; y obtener el permalink cuando la API lo permita.
- **FR-037**: La espera del procesamiento DEBE usar un intervalo y un tiempo máximo acotados
  (valores basados en las recomendaciones oficiales vigentes, verificados en el plan), sin
  espera activa continua, y DEBE respetar el cierre ordenado de la aplicación.
- **FR-038**: Los estados terminales de error del container (por ejemplo `ERROR`, `EXPIRED`)
  observados **antes** de invocar `media_publish` DEBEN tratarse como fallo determinado sin
  ejecutar `media_publish`. Una vez invocado `media_publish` con resultado no concluyente,
  esos estados NO prueban que no se publicó (FR-044a). La caducidad vigente de
  los containers DEBE verificarse en el plan y el diseño DEBE tenerla en cuenta.
- **FR-039**: El sistema NO DEBE crear containers repetidamente sin límite: cada intento crea
  como máximo un container, salvo que el plan justifique un caso concreto y acotado.

#### Fases internas y progreso

- **FR-040**: `PublicationAttempt` DEBE registrar fases internas suficientemente explícitas
  para una recuperación segura (por ejemplo: preparación, entrega del media, creación del
  container, procesamiento, publicación final, verificación del resultado). Los nombres
  exactos se deciden en el plan; las fases DEBEN ser genéricas o extensibles sin acoplar el
  núcleo a Instagram. La limpieza NO es una fase que decida el resultado: ocurre después de
  que el intento haya terminado (`succeeded` o `failed`) y su estado (pendiente, completada,
  fallida) se registra aparte, sin alterar el estado del intento ni de la publicación.
- **FR-041**: El sistema DEBE persistir de forma no sensible lo necesario para recuperar sin
  duplicar (por ejemplo, el identificador del container creado y la referencia no secreta del
  recurso temporal), sin almacenar tokens ni URLs firmadas. La referencia del recurso temporal
  DEBE persistirse de forma compatible con la garantía crash-safe de FR-016a.
- **FR-042**: El progreso mostrado DEBE reflejar fases reales: PUEDE combinar progreso real de
  subida al proveedor de media delivery con fases discretas durante el procesamiento. NO DEBEN
  inventarse porcentajes precisos que Meta no proporciona, y el 100 % solo DEBE mostrarse
  cuando la publicación queda realmente `PUBLISHED`, con independencia de que la limpieza
  posterior haya terminado o fallado. La interfaz PUEDE mostrar información de limpieza por
  separado. La representación pública del intento (API) DEBE aplicar la misma regla de forma
  neutral para todas las plataformas: un intento que no está `succeeded` (en curso o fallido)
  expone como máximo `0.99`, y `1.0` solo corresponde a un intento `succeeded` con la
  publicación `PUBLISHED`.

#### Publicación final (`media_publish`) y resultado ambiguo

- **FR-043**: Antes de llamar a `media_publish`, el sistema DEBE persistir y confirmar
  (commit) una fase que indique que se va a ejecutar el efecto final (write-ahead, equivalente
  a la Feature 006); solo después llama a Meta.
- **FR-044**: Si `media_publish` no produce una respuesta concluyente (timeout, pérdida de
  conexión, fin del proceso, respuesta inesperada), el sistema NO DEBE crear otro container ni
  repetir `media_publish` automáticamente.
- **FR-044a**: Una vez invocado `media_publish` con resultado no concluyente, la única señal
  aceptada para resolver automáticamente el resultado, tanto durante la ejecución como en la
  reconciliación posterior (FR-046a), es que el container original figure como `PUBLISHED`:
  publicación `PUBLISHED`, intento `succeeded`, resultado determinado. Cualquier otro estado
  (`ERROR`, `EXPIRED`, `IN_PROGRESS`, desconocido), un fallo temporal al consultar o la
  ausencia de respuesta NO DEBEN interpretarse como prueba de que el post no se publicó: el
  resultado sigue `FAILED` ambiguo y exige el reconocimiento manual de FR-046 antes de un
  nuevo intento, salvo que la documentación oficial vigente de Meta garantice
  inequívocamente lo contrario.
- **FR-045**: El plan DEBE investigar si el estado del container u otra consulta oficial
  permite demostrar inequívocamente el resultado. Tras un `media_publish` no concluyente, el
  sistema DEBE usar únicamente consultas de lectura (sin efectos de publicación) y solo puede
  resolver automáticamente el resultado hacia `PUBLISHED`, cuando el container original
  confirma `status_code = PUBLISHED` (FR-044a). Cualquier otro resultado (`ERROR`, `EXPIRED`,
  `IN_PROGRESS`, desconocido o fallo de consulta) NO DEBE completar automáticamente un
  `FAILED` determinado: la ejecución queda `FAILED` con resultado ambiguo que requiere
  revisión manual en Instagram.
- **FR-045a**: Si una consulta oficial de solo lectura confirma que la publicación ocurrió
  pero ningún mecanismo oficial e inequívoco permite recuperar el Instagram media ID, el
  sistema NUNCA DEBE inferirlo (por ejemplo, buscando publicaciones recientes por caption,
  fecha o tipo, aunque haya un único candidato). DEBE registrar la publicación como
  confirmada sin identidad remota (sin media ID ni enlace inventados) e informar al usuario,
  bloqueando siempre cualquier reintento o nuevo container que pudiera duplicar el post. Una
  búsqueda manual en el perfil puede sugerirse al usuario como ayuda, nunca como prueba
  automática.
- **FR-046**: Una publicación con resultado ambiguo NUNCA DEBE reintentarse automáticamente
  (ni por el scheduler ni por recuperación tras reinicio). Una nueva ejecución manual DEBE
  requerir que el usuario reconozca explícitamente que ha comprobado en Instagram que el post
  no se publicó, y pasar de nuevo por confirmación y preflight (modelo de la Feature 006).
- **FR-046a**: Antes de exigir ese reconocimiento manual (tanto en la comprobación de
  publicación como al iniciar `Publish now`), si el último intento es ambiguo, alcanzó la fase
  de publicación final y su container es conocido, el sistema DEBE intentar una
  reconciliación de solo lectura del estado del container original:
  - si Instagram confirma `PUBLISHED`, DEBE dar por determinada la publicación sin pedir
    confirmación: publicación `PUBLISHED`, intento original `succeeded` con resultado
    determinado, sin media ID ni enlace inferidos (FR-045a) y con un aviso seguro; quedan
    bloqueados definitivamente cualquier reintento y cualquier container nuevo;
  - en cualquier otro caso (otro estado, error o sin respuesta) NO DEBE asumir que no se
    publicó: el intento sigue ambiguo y se mantiene el reconocimiento manual de FR-046.
  La reconciliación nunca llama a `media_publish`, nunca crea containers y nunca consulta
  publicaciones recientes. Se implementa mediante un punto de extensión neutral del
  publisher, sin lógica de Instagram en el núcleo genérico.

#### Reintentos y clasificación de errores

- **FR-047**: Los errores DEBEN clasificarse al menos en: temporales, definitivos,
  credencial/reconexión, media incompatible, cuota/límite de peticiones, fallo de entrega del
  media, fallo de procesamiento y resultado remoto ambiguo.
- **FR-048**: Los reintentos automáticos dentro de una ejecución SOLO DEBEN aplicarse a
  operaciones claramente idempotentes o sin efecto de publicación (por ejemplo, consultas de
  estado o subida al proveedor de media temporal), con número y espera acotados. `media_publish`
  NUNCA DEBE reintentarse automáticamente tras un resultado no concluyente. No existen
  reintentos automáticos entre intentos (política de la Feature 006).
- **FR-049**: Si Meta invalida definitivamente la credencial durante una ejecución, el sistema
  DEBE marcar la conexión `Reconnect required` usando los servicios de la Feature 008 y fallar
  de forma segura. Los errores temporales NO DEBEN cambiar el estado de conexión.

#### Reinicios y recuperación

- **FR-050**: Al arrancar, la recuperación genérica de intentos interrumpidos DEBE seguir
  aplicándose: ninguna ejecución Instagram se reanuda automáticamente y la publicación queda
  `FAILED`. El resultado DEBE ser:
  - determinado (no publicado) si el intento no había alcanzado la fase de publicación final;
  - ambiguo si la había alcanzado, salvo que un mecanismo oficial de solo lectura lo resuelva
    inequívocamente (FR-045); esa resolución puede ocurrir después, mediante la
    reconciliación de FR-046a, nunca reanudando la ejecución.
- **FR-051**: Si un intento falló o se interrumpió con un container creado, válido y no
  publicado, un nuevo intento PUEDE reutilizarlo en lugar de crear otro, solo si el plan
  demuestra que es seguro (estado verificable, no caducado, mismo media y parámetros).
- **FR-052**: Una publicación `PUBLISHED` NUNCA DEBE volver a publicarse automáticamente.
- **FR-053**: Tras un reinicio, los recursos temporales públicos que hubieran quedado
  pendientes DEBEN limpiarse best-effort (FR-016, FR-016a).

#### Cleanup

- **FR-054**: El media temporal y los archivos derivados locales DEBEN eliminarse cuando Meta
  ya no los necesite, tanto tras éxito como tras error cuando sea seguro. Tras una publicación
  confirmada, la limpieza DEBE ejecutarse siempre **después** de persistir el resultado,
  `PUBLISHED` y el intento `succeeded` (FR-056), como operación best-effort que no forma parte
  de la decisión de si Instagram publicó correctamente.
- **FR-055**: Un fallo de limpieza posterior a una publicación confirmada NUNCA DEBE devolver
  la publicación a `PUBLISHING`, cambiar `PUBLISHED` a `FAILED` ni cambiar un intento
  `succeeded` a `failed`. DEBE registrar un aviso seguro y dejar registrada la necesidad de
  limpieza posterior best-effort (FR-016). La interfaz PUEDE mostrar información de limpieza.

#### Resultado publicado

- **FR-056**: Cuando Meta confirme inequívocamente la publicación, el sistema DEBE, en este
  orden: (1) persistir el Instagram media ID como identificador remoto (cuando Meta lo haya
  devuelto o pueda recuperarse por un mecanismo oficial e inequívoco; si no, FR-045a), el
  permalink como URL remota cuando esté disponible y el resultado remoto, conservando de forma no sensible el
  caption y las opciones usadas en el intento; (2) marcar la publicación `PUBLISHED`; (3)
  marcar el intento `succeeded`; y (4) solo después ejecutar la limpieza best-effort del media
  temporal y de los derivados locales (FR-054/FR-055). Los pasos (1)–(3) PUEDEN confirmarse
  en una misma transacción; la limpieza nunca forma parte de ella.
- **FR-057**: Si el permalink no puede obtenerse tras una publicación confirmada, la
  publicación DEBE seguir `PUBLISHED` (sin enlace o con un enlace alternativo seguro definido
  en el plan) y el usuario DEBE ser informado.
- **FR-058**: El registro en logs de identificadores remotos DEBE seguir el precedente de la
  política de seguridad de YouTube.

#### Scheduler, pausa y concurrencia

- **FR-059**: Una publicación Instagram manual DEBE ejecutarse con el mismo ejecutor y origen
  `manual`; una programada y armada, mediante el scheduler genérico con origen `scheduled`. NO
  DEBE añadirse código de Instagram al scheduler.
- **FR-060**: La pausa global existente DEBE bloquear las nuevas ejecuciones automáticas de
  Instagram, sin bloquear `Publish now` ni cancelar ejecuciones en curso. Esta lógica NO DEBE
  reimplementarse.
- **FR-061**: Las protecciones genéricas de concurrencia DEBEN reutilizarse: una publicación no
  puede ejecutarse dos veces a la vez, ni por manual vs scheduler ni por ciclos concurrentes.
  Además, los efectos remotos de Instagram DEBEN protegerse frente a reintentos inseguros
  (FR-043 a FR-046).

#### API, errores e interfaz

- **FR-062**: La API DEBE permitir consultar y editar las opciones de Instagram de una
  publicación, consultar el caption final y la compatibilidad del media, y DEBE exponer los
  intentos, fases, errores y resultado remoto mediante los endpoints genéricos existentes.
  Ninguna respuesta DEBE incluir tokens, credenciales del proveedor ni URLs temporales.
- **FR-063**: Los errores DEBEN seguir el formato estructurado existente con códigos estables y
  seguros que distingan al menos: Instagram no conectado, reconexión requerida, media delivery
  no configurado, fallo de entrega del media, media incompatible (imagen/vídeo), caption
  inválido, opciones de Instagram sin declarar (las combinaciones inválidas se rechazan al
  guardarlas con el error de validación correspondiente), cuota de publicación agotada,
  límite de peticiones/temporal de Meta, creación de container fallida, procesamiento fallido,
  tiempo de procesamiento agotado, container caducado, `media_publish` fallido, resultado de
  publicación ambiguo, ejecución interrumpida y limpieza del media temporal fallida (como aviso).
  Los nombres exactos se concretan en el plan. Nunca DEBEN devolverse respuestas crudas de
  Meta.
- **FR-064**: Para una publicación Instagram, la interfaz DEBE mostrar: tipo de publicación
  (`Image Post` o `Reel`), caption final, opciones específicas (declaración AI-generated,
  `share_to_feed` si aplica, `alt_text` si aplica), compatibilidad del media, estado y
  progreso, errores, historial de intentos, `Publish now`, programación y publicación
  automática existentes y `Open on Instagram` tras el éxito.
- **FR-065**: Los componentes comunes de la interfaz DEBEN reutilizarse donde sea posible y no
  contener lógica de Instagram salvo puntos de extensión neutrales por plataforma; las
  opciones de Instagram NO DEBEN mostrarse en otras plataformas.

#### Seguridad y logging

- **FR-066**: Se DEBEN mantener todas las garantías de las Features 005–008. Nunca DEBEN
  registrarse ni exponerse: token de acceso de Instagram, cabeceras `Authorization`,
  credenciales del proveedor de media delivery, URLs temporales firmadas completas, parámetros
  de consulta secretos ni respuestas crudas sensibles de Meta.
- **FR-067**: El redactor de logs existente DEBE extenderse para cubrir los nuevos secretos y
  DEBEN existir tests de seguridad que lo verifiquen en base de datos, logs, respuestas de la
  API y frontend/almacenamiento del navegador.

#### Persistencia, documentación y calidad

- **FR-068**: Las opciones de Instagram, las nuevas fases y los datos de recuperación no
  sensibles DEBEN persistir mediante migraciones versionadas.
- **FR-069**: La documentación (README y `quickstart.md`) DEBE explicar: la publicación de
  imágenes y Reels en Instagram, la configuración del proveedor de media delivery elegido, el
  caption, las opciones de Instagram, el tratamiento de resultados ambiguos y los requisitos
  de App Review / Development Mode aplicables.
- **FR-070**: Los tests automatizados NO DEBEN depender de Internet, de Meta real, del keyring
  real ni de un proveedor cloud real; DEBEN usar fakes y cubrir como mínimo los casos
  enumerados en la descripción de la feature (imagen JPEG válida; PNG/WebP según la política;
  Reel válido; imagen y vídeo incompatibles; archivo desaparecido; caption válido e inválido;
  `alt_text`; AI disclosure Sí/No; `share_to_feed`; cuenta no conectada; reconexión requerida;
  proyecto/cuenta inactivos; media delivery no configurado; subida temporal; URL temporal no
  filtrada; creación de container; polling; `FINISHED`; `ERROR`; `EXPIRED`; tiempo agotado;
  cuota disponible y agotada; `media_publish`; media ID y permalink; cleanup con éxito y con
  fallo; fallo antes y después del container; ambigüedad durante `media_publish`; reinicio en
  cada fase relevante; publicación manual y programada; pausa; manual vs scheduler;
  concurrencia; ausencia de secretos en base de datos, logs, API y frontend; y scheduler y
  ejecutor genéricos sin imports de Instagram).
- **FR-071**: `quickstart.md` DEBE incluir validación real con la cuenta Instagram ya
  conectada usando contenido inocuo preparado específicamente para la prueba (nunca contenido
  real existente del usuario): publicación manual de una imagen (media temporal, container,
  publicación, permalink, cleanup); publicación manual de un Reel corto (procesamiento,
  publicación, permalink, cleanup); y una publicación programada unos minutos en el futuro
  ejecutada una sola vez por el scheduler genérico, advirtiendo de que en Instagram no existen
  publicaciones privadas y toda prueba publica realmente. Debe indicar borrar manualmente los
  posts de prueba y verificar `is_ai_generated`, `share_to_feed`, persistencia, logs, base de
  datos, ausencia de tokens/URLs temporales y limpieza del proveedor temporal.

### Key Entities *(include if feature involves data)*

- **Instagram Publication Options**: opciones específicas de Instagram de una `Publication`
  (una por publicación Instagram), separadas del modelo común: declaración AI-generated
  (obligatoria y explícita), `share_to_feed` (solo Reels, si está soportado, con default
  documentado) y `alt_text` (solo imágenes, opcional, si está soportado).
- **Caption de Instagram**: valor derivado (no un nuevo campo editable) construido de forma
  determinista a partir de la descripción y los hashtags efectivos de la `Publication`.
- **Temporary Media Resource**: recurso temporal públicamente accesible por HTTPS que
  representa una copia (original o derivada técnica) del archivo de un Content durante una
  ejecución. Atributos no sensibles: referencia no secreta del recurso, intento al que
  pertenece, momento de creación y estado de limpieza (independiente del estado del intento).
  Su ciclo de vida debe ser crash-safe (FR-016a). Su URL firmada, si existe, es secreta y no
  se persiste salvo justificación del plan.
- **Media Delivery Provider**: capacidad genérica, configurada localmente, que publica,
  mantiene y elimina recursos temporales; la implementación concreta se elige en el plan.
- **Instagram Media Container**: objeto remoto de Meta creado por intento antes de publicar;
  atributos persistidos no sensibles: identificador del container, tipo de media y último
  estado conocido, para recuperación sin duplicados.
- **PublicationAttempt** (existente, Features 006/007): se reutiliza con su origen, progreso,
  error, resultado determinado/ambiguo y resultado remoto; se amplía con las fases internas
  necesarias y la información de recuperación no sensible.
- **Publication** (existente, Feature 004): no recibe campos de Instagram; usa sus estados
  existentes y su metadata efectiva.
- **Instagram Connection** (existente, Feature 008): fuente de la credencial y de la identidad
  autoritativa; sin cambios de modelo salvo los estrictamente necesarios para marcar
  `Reconnect required`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real de `quickstart.md` (Content local →
  publicación Instagram → `Publish now` → post real en Instagram → `Open on Instagram`) para
  una imagen y para un Reel sin editar archivos de datos ni la base de datos a mano.
- **SC-002**: Una publicación Instagram programada y armada se publica exactamente una vez
  mediante el scheduler genérico en la validación real y en el 100 % de los tests de
  concurrencia (manual vs scheduler, ciclos concurrentes).
- **SC-003**: 0 posts duplicados en todos los escenarios de fallo, corte e interrupción
  simulados: `media_publish` se ejecuta como máximo una vez por container y nunca se repite
  automáticamente tras un resultado no concluyente.
- **SC-004**: En el 100 % de los fallos de preflight no se hace público ningún archivo ni se
  crea ningún container.
- **SC-005**: Tras el 100 % de las ejecuciones terminadas (éxito o fallo), y tras la limpieza
  posterior de recursos abandonados, no queda ningún recurso temporal públicamente accesible
  en el proveedor de media delivery.
- **SC-006**: El 100 % de los archivos originales de Content permanecen idénticos byte a byte
  después de publicar.
- **SC-007**: La base de datos, los logs, los mensajes de error, las respuestas de la API y el
  almacenamiento del navegador contienen 0 tokens de Instagram, 0 credenciales del proveedor
  de media delivery y 0 URLs temporales firmadas (tests automatizados e inspección en el
  quickstart).
- **SC-008**: El caption mostrado al usuario coincide en el 100 % de los casos con el enviado a
  Instagram, y 0 captions se truncan silenciosamente.
- **SC-009**: Cada error listado en FR-063 produce un mensaje comprensible que indica qué ha
  pasado y qué puede hacer el usuario, y si el resultado remoto está determinado o requiere
  revisión manual.
- **SC-010**: 0 errores temporales de red provocan un paso a `Reconnect required`.
- **SC-011**: La suite de tests automatizados de la feature se ejecuta completa sin Internet,
  sin Meta real, sin keyring real y sin proveedor cloud real, y el scheduler y el ejecutor
  genéricos no contienen ninguna referencia a Instagram ni al proveedor concreto.
- **SC-012**: Las publicaciones de YouTube siguen funcionando sin cambios de comportamiento
  (suite existente en verde).

## Assumptions

- **Alcance**: solo imagen individual (feed) y vídeo individual como Reel. Quedan fuera:
  carousels, Stories, múltiples archivos por publicación, colaboraciones, product tags, user
  tags, ubicación, branded content, música licenciada, encuestas, trial Reels, filtros,
  comentarios, DMs, analytics/insights, edición o borrado remoto, generación de contenido o
  captions y transcoding de vídeo.
- **Decisiones diferidas al plan** (con verificación en documentación oficial vigente de
  Meta): endpoints y versión de Graph API; requisitos de imagen y Reel; límites de caption,
  hashtags, menciones y `alt_text`; soporte de `is_ai_generated` y `share_to_feed` y default de
  este último; estados de container, polling recomendado y caducidad; contrato de
  `content_publishing_limit`; semántica e idempotencia de `media_publish` y recuperación del
  resultado; cuándo deja Meta de necesitar la URL y qué comportamiento HTTP exige; proveedor
  de media delivery y su lifecycle; política de conversión de imágenes (transparencia, perfil
  de color, animación); formato exacto de unión del caption; nombres de fases y códigos de
  error; requisitos de App Review / Development Mode para publicar con la cuenta tester.
- **Precedentes reutilizados**: confirmación de `Publish now`, preflight, estados,
  transiciones, reintento manual con reconocimiento explícito ante resultado ambiguo,
  recuperación de intentos interrumpidos y bloqueo de edición en `PUBLISHING`/`PUBLISHED` de la
  Feature 006; elegibilidad, consentimiento (publicación automática armada), ventana, pausa y
  concurrencia de la Feature 007; servicios de credencial e identidad de la Feature 008.
- **Declaración AI-generated obligatoria**: por analogía con la declaración de contenido
  sintético de YouTube (Feature 006), se asume que el usuario debe elegir explícitamente Sí/No
  antes de ejecutar; no existe valor por defecto implícito.
- **Media delivery con dependencia externa**: publicar en Instagram con Instagram Login exige
  que Meta obtenga el media desde una URL pública; por tanto esta feature acepta, como
  excepción justificada a la filosofía local-first, una dependencia externa mínima para el
  media temporal, cuya elección y justificación corresponde al plan.
- **Usuario y entorno**: un único usuario local con la cuenta Instagram Professional ya
  conectada (Feature 008), su propia Meta App y AutoPublisher encendido a la hora de las
  publicaciones programadas.
- **Dependencias**: `Content` y su inspección de media (Feature 003), `Publication` y su
  metadata efectiva (Feature 004), ejecución genérica y `PublicationAttempt` (Feature 006),
  scheduler genérico (Feature 007), conexión Instagram y almacén seguro de credenciales
  (Features 005 y 008), formato estructurado de errores, redactor de logs y migraciones
  existentes.
