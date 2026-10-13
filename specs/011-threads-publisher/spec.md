# Feature Specification: Publicación real de texto, imagen y vídeo en Threads

**Feature Branch**: `011-threads-publisher`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Feature 011 — Threads Publisher. Permitir publicar contenido real en Threads desde AutoPublisher usando la conexión oficial de la Feature 010: publicación individual de texto, imagen y vídeo; `Publish now`; scheduler genérico existente; historial y resultado remoto; protección estricta contra duplicados (write-ahead antes de `threads_publish`, nunca repetirlo ante un resultado ambiguo, reconciliación solo de lectura del container original); media delivery temporal reutilizando el provider genérico S3-compatible / R2; preflight completo antes de cualquier efecto remoto; consulta de `threads_publishing_limit`; cleanup best-effort tras persistir el resultado; UI mínima; tests offline con fakes; quickstart de validación real. Sin carousels, replies, quotes, polls, GIFs, topic tags, ubicación, ghost posts, spoilers, reply approvals, insights, moderación, búsqueda, borrado ni cross-posting."

## Contexto

Desde la Feature 010, una `Account` de plataforma Threads puede estar vinculada (`Connected`)
a una cuenta real de Threads mediante la Threads API oficial de Meta, con la credencial de
larga duración guardada solo en el almacén seguro del sistema operativo, el Threads user ID
como identidad autoritativa y servicios internos para obtener una credencial válida
(renovándola cuando corresponda) y la identidad vinculada. Todavía no se puede publicar nada en
Threads.

Desde las Features 006, 007 y 009, AutoPublisher tiene una ejecución de publicaciones
**genérica**: preflight, estados `PUBLISHING` / `PUBLISHED` / `FAILED`, `PublicationAttempt`
con origen (`manual` / `scheduled`), fases genéricas, progreso, errores seguros, resultado
remoto (con identificador y enlace opcionales), resultado determinado/ambiguo, reconocimiento
manual antes de reintentar un intento ambiguo, un punto de extensión neutral de reconciliación
de solo lectura, recuperación genérica de intentos interrumpidos al arrancar, un scheduler
local que ejecuta publicaciones programadas y armadas, y un sistema genérico de media delivery
temporal (bucket privado S3-compatible / Cloudflare R2 con URLs firmadas temporales y
lifecycle del proveedor como red de seguridad). Hoy están registrados los publishers de
YouTube e Instagram.

Esta feature registra un **publisher de Threads real** dentro de esa arquitectura genérica, de
modo que una `Publication` destinada a una `Account` Threads conectada pueda publicarse:

- manualmente, mediante `Publish now`;
- automáticamente, mediante el scheduler genérico existente;

conservando historial, intentos, progreso, errores y enlace remoto igual que YouTube e
Instagram. No se crea un scheduler, ejecutor ni sistema de media delivery específicos de
Threads, ni se rediseña la conexión de la Feature 010.

Flujo conceptual (idéntico para los tres tipos, salvo el media):

`Publication` → preflight genérico + preflight de Threads → (solo imagen/vídeo: hacer el media
temporalmente accesible a Meta) → crear container → comprobar que está en condición publicable
(espera acotada solo cuando el tipo lo requiera, FR-032) → registrar de
forma persistente la fase final (write-ahead) → `threads_publish` → guardar Threads post ID,
permalink y resultado → `PUBLISHED` / intento `succeeded` → (solo imagen/vídeo) limpiar el
media temporal best-effort, fuera de la decisión de éxito.

Alcance de esta versión:

1. **Texto** sin media → post de texto (`TEXT`).
2. **Imagen individual** → post de imagen (`IMAGE`).
3. **Vídeo individual** → post de vídeo (`VIDEO`).

Principios rectores:

- **Nunca publicar duplicados**: ante un resultado incierto de `threads_publish`, AutoPublisher
  no repite la llamada; solo consulta el container original en modo lectura y, si no puede
  demostrar el resultado, pide revisión manual.
- **El texto y el media del usuario no se transforman**: no se añaden hashtags, enlaces, topic
  tags ni otros elementos; no se modifica creativamente ningún archivo; el original nunca cambia.
- **Ningún secreto sale de donde debe**: ni tokens de Threads, ni credenciales del proveedor de
  media delivery, ni URLs firmadas aparecen en logs, base de datos, respuestas al frontend o
  mensajes de error.
- **Exposición mínima**: el media solo es accesible el tiempo necesario para que Meta lo
  obtenga, y solo ese archivo; los posts de texto no crean ningún recurso de media delivery.

## Restricciones de la plataforma (documentación oficial de Meta, consultada 2026-10-13)

Estos hechos condicionan el comportamiento del producto. El plan DEBE reconfirmarlos y fijar
los detalles técnicos (host, versión, parámetros exactos, uso de `/me` o del Threads user ID
en la ruta) en `research.md`.

- **Publicación en dos pasos**: se crea un container (`POST /{threads-user-id}/threads`, con
  `media_type` = `TEXT`, `IMAGE` o `VIDEO`) y se publica con
  `POST /{threads-user-id}/threads_publish` y `creation_id`; la respuesta de publicación es
  `{"id": "<THREADS_MEDIA_ID>"}`. Meta recomienda esperar "de media 30 segundos" antes de
  publicar un container. La documentación consultada usa el Threads user ID en la ruta; el uso
  del alias `/me` lo decidirá el plan.
- **`auto_publish_text`**: existe para posts de texto y publica al crear el container, sin paso
  de publicación. **No se utiliza** en esta versión (ver FR-030).
- **Texto**: máximo **500 caracteres**; la documentación indica que los emojis cuentan como su
  longitud en bytes UTF-8. `text` es obligatorio para `TEXT` y opcional para `IMAGE`/`VIDEO`.
  Como máximo **5 enlaces** por post (URLs únicas del texto más un `link_attachment` distinto);
  desde 2025-12-22 un exceso falla al crear el container (`THREADS_API__LINK_LIMIT_EXCEEDED`).
  En posts de texto sin `link_attachment`, **Threads usa automáticamente la primera URL del
  texto como vista previa del enlace** (comportamiento de Meta, no una transformación de
  AutoPublisher).
- **Topic tags**: un post solo admite un topic tag; además del parámetro `topic_tag`, Threads
  convierte la **primera etiqueta válida `#…` del texto** en topic tag (método mantenido por
  compatibilidad; `#` seguido solo de números no se convierte). Relevante para la composición
  del texto (FR-018).
- **Imagen**: JPEG y PNG oficialmente soportados; máximo 8 MB; relación de aspecto límite
  10:1; ancho entre 320 y 1440 (Meta escala fuera de ese rango); espacio de color sRGB (Meta
  convierte otros). Meta descarga la imagen desde la URL indicada (`image_url`), que debe ser
  accesible públicamente.
- **Vídeo**: contenedor MOV o MP4 sin edit lists y con `moov` al inicio; vídeo HEVC o H.264,
  progresivo, closed GOP, 4:2:0; audio AAC, ≤ 48 kHz, mono o estéreo, 128 kbps; 23–60 FPS;
  ancho máximo 1920 px; relación de aspecto entre 0,01:1 y 10:1 (9:16 recomendado); bitrate
  VBR ≤ 100 Mbps; duración > 0 y ≤ 300 s; tamaño ≤ 1 GB. Se obtiene mediante `video_url`.
- **`alt_text`**: opcional para imagen y vídeo, máximo 1000 caracteres.
- **Estado del container**: `GET /{container-id}?fields=status,error_message` devuelve
  `IN_PROGRESS`, `FINISHED` (listo para publicar), `PUBLISHED` (su media object se ha
  publicado), `ERROR` (con `error_message`, p. ej. `FAILED_DOWNLOADING_VIDEO`,
  `FAILED_PROCESSING_VIDEO`, `INVALID_DURATION`, `INVALID_FRAME_RATE`, `UNKNOWN`…) o `EXPIRED`
  (no publicado en **24 horas**). Meta recomienda consultar el estado **una vez por minuto
  durante no más de 5 minutos**. Para el caso "`threads_publish` no devolvió un media ID", la
  guía oficial de troubleshooting indica consultar el estado del container. La documentación
  consultada **no** describe ningún campo del container que devuelva el Threads media ID
  publicado, ni la idempotencia de `threads_publish`.
- **Límite de publicación**: `GET /{threads-user-id}/threads_publishing_limit` devuelve el uso
  (`quota_usage`) y la configuración (`config` con `quota_total` y `quota_duration`); hoy el
  límite documentado es de **250 posts publicados por la API en una ventana móvil de 24 h**
  (un carousel cuenta como uno). Meta recomienda que las apps respeten el límite, en especial
  para posts programados. No documenta si crear containers consume cuota ni el retraso del
  contador.
- **Resultado publicado**: `GET /{threads-media-id}` ofrece, entre otros, `permalink`,
  `shortcode`, `timestamp`, `media_type` y `username`; `permalink` **se omite** si el media
  contiene material con copyright o ha sido marcado por infracción.
- **Permisos**: publicar exige `threads_basic` y `threads_content_publish`, ya solicitados y
  verificados por la Feature 010. La API no expone un parámetro de declaración de contenido
  generado por IA para Threads.

Fuentes: Threads API — *Posts*, *Publishing reference*, *Overview* (límites y especificaciones
de media), *Troubleshooting* (estado del container), *Threads Media* y la referencia de topic
tags.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicar ahora un post de texto en Threads (Priority: P1)

Como usuario, quiero pulsar `Publish now` en una publicación de texto destinada a una cuenta
Threads conectada y ver cómo se publica en Threads, con su enlace, sabiendo exactamente qué
texto se ha enviado.

**Why this priority**: es el camino más corto que demuestra el flujo completo de publicación
en Threads (container → write-ahead → `threads_publish` → resultado) sin depender del media
delivery.

**Independent Test**: con un fake de Threads, crear una publicación de texto para una
`Account` Threads `Connected`, ejecutar `Publish now` y comprobar: la publicación queda
`PUBLISHED`, el intento `succeeded` con origen `manual`, se guardan Threads post ID y
permalink, el texto enviado coincide carácter a carácter con el mostrado, se creó un único
container `TEXT`, `threads_publish` se llamó exactamente una vez, no se creó ningún recurso de
media delivery y no hay secretos en base de datos, logs ni respuestas de la API.

**Acceptance Scenarios**:

1. **Given** una publicación de texto `UNSCHEDULED` o `SCHEDULED` destinada a una `Account`
   Threads `Connected`, con cuenta y proyecto activos y texto válido, **When** el usuario pulsa
   `Publish now` y confirma, **Then** se ejecuta el preflight completo y, si pasa, la
   publicación pasa a `PUBLISHING` y se crea un `PublicationAttempt` con origen `manual`.
2. **Given** la ejecución en curso, **When** avanza, **Then** se crea un container de texto,
   se persiste su identificador, se comprueba que está en condición publicable según la
   documentación oficial (sin esperas artificiales si Meta no exige consultar el estado,
   FR-032), se registra de forma persistente la fase final y solo después se ejecuta
   `threads_publish`; no se usa la publicación automática al crear el container.
3. **Given** que Threads devuelve el post ID, **When** termina la ejecución, **Then** se
   persisten el post ID, el permalink oficial si puede recuperarse y el resultado remoto; la
   publicación queda `PUBLISHED`, el intento `succeeded` y la interfaz muestra
   `Open on Threads`.
4. **Given** una publicación de texto, **When** se ejecuta, **Then** no se crea, sube, expone
   ni limpia ningún recurso de media delivery, y el preflight no exige configuración de media
   delivery.
5. **Given** un texto con URLs, **When** se publica, **Then** se envía tal cual, sin añadir,
   quitar ni reescribir enlaces, hashtags o topic tags; la interfaz informa de que Threads
   puede mostrar la primera URL como vista previa.

---

### User Story 2 - Publicar ahora una imagen en Threads (Priority: P1)

Como usuario, quiero publicar una imagen de mi biblioteca en Threads, opcionalmente con texto
y texto alternativo, sin que mi archivo original cambie y sin dejar copias accesibles.

**Why this priority**: valida la reutilización del media delivery genérico con Threads y que
Meta acepta las URLs firmadas actuales.

**Independent Test**: con fakes de Threads y del proveedor de media delivery, publicar una
imagen JPEG con `alt_text`; comprobar: referencia del recurso temporal persistida antes de
subirlo, container `IMAGE` con la URL temporal y el `alt_text`, `threads_publish` una vez,
`PUBLISHED` con post ID y permalink, cleanup ejecutado después de persistir el resultado,
archivo original idéntico byte a byte y URL firmada ausente de base de datos, logs y API.

**Acceptance Scenarios**:

1. **Given** una publicación de un Content imagen compatible destinada a una `Account` Threads
   `Connected` y media delivery configurado, **When** el usuario ejecuta `Publish now`,
   **Then** tras el preflight se persiste la referencia no sensible del recurso temporal, se
   sube la imagen al bucket privado, se genera una URL temporal firmada, se crea el container
   `IMAGE` y se publica.
2. **Given** un `alt_text` configurado, **When** se crea el container, **Then** se envía
   exactamente ese texto; si está vacío, no se envía.
3. **Given** una imagen en un formato no soportado oficialmente por Threads, **When** se
   publica, **Then** se aplica la política técnica documentada (copia temporal convertida sin
   alteración creativa, o rechazo en preflight); el original nunca cambia.
4. **Given** una publicación confirmada, **When** termina, **Then** la limpieza del recurso
   temporal se ejecuta solo después de persistir el resultado, `PUBLISHED` y `succeeded`.

---

### User Story 3 - Publicar ahora un vídeo en Threads (Priority: P1)

Como usuario, quiero publicar un vídeo de mi biblioteca en Threads, esperando a que Threads lo
procese, sin que AutoPublisher lo transcodifique.

**Why this priority**: el vídeo requiere procesamiento asíncrono del container, la parte más
delicada del flujo.

**Independent Test**: con fakes, publicar un vídeo compatible; simular varias consultas
`IN_PROGRESS` antes de `FINISHED`; comprobar intervalo y tiempo máximo acotados, que
`threads_publish` solo se ejecuta tras `FINISHED` y que el resultado queda `PUBLISHED` con el
media temporal limpiado. Repetir con `ERROR`, `EXPIRED` y tiempo agotado.

**Acceptance Scenarios**:

1. **Given** un Content vídeo, **When** se ejecuta el preflight, **Then** se inspecciona
   localmente (patrón de la Feature 003) contra los requisitos vigentes de Threads **antes** de
   subir o exponer el archivo, indicando qué requisito no se cumple si falla, sin transcodificar.
2. **Given** un container de vídeo en procesamiento, **When** AutoPublisher espera, **Then**
   consulta su estado con intervalo y tiempo máximo acotados, sin espera activa continua, y
   solo ejecuta `threads_publish` cuando el estado es `FINISHED`.
3. **Given** un container que termina en `ERROR` o `EXPIRED` antes de `threads_publish`,
   **When** se detecta, **Then** la ejecución falla con un error seguro (incluido el motivo de
   Meta traducido a un mensaje comprensible cuando exista), resultado determinado, sin
   `threads_publish`, y el media temporal se limpia.
4. **Given** un container que no está listo dentro del tiempo máximo, **When** se alcanza,
   **Then** la ejecución falla con un error seguro de procesamiento agotado, sin
   `threads_publish`.

---

### User Story 4 - Ver el texto exacto y configurar las opciones de Threads (Priority: P1)

Como usuario, quiero ver exactamente el texto que se enviará a Threads, saber si es válido y
configurar solo las opciones imprescindibles (texto alternativo para imagen/vídeo).

**Why this priority**: el texto es lo que verá el público y no puede truncarse ni alterarse.

**Independent Test**: crear publicaciones Threads de texto, imagen y vídeo; comprobar que el
texto mostrado coincide con el enviado al fake; que un texto que excede los límites se rechaza
sin truncar; que `alt_text` solo aparece en imagen/vídeo, persiste tras reiniciar y respeta su
límite; y que las publicaciones de otras plataformas no muestran opciones de Threads.

**Acceptance Scenarios**:

1. **Given** una publicación Threads, **When** el usuario abre su detalle, **Then** ve el texto
   final exacto que se enviará, construido de forma determinista (FR-018).
2. **Given** un texto final (tras la composición de FR-018) que excede algún límite vigente
   (longitud según la regla de conteo de Meta, número de enlaces), **When** se consulta la validez, se intenta publicar o se arma la
   publicación automática, **Then** se informa del límite y del valor real; el texto nunca se
   trunca.
3. **Given** una publicación de texto cuyo texto final queda vacío, **When** se comprueba,
   **Then** se marca como no publicable; en imagen y vídeo un texto final vacío se permite.
4. **Given** una publicación de imagen o vídeo, **When** el usuario escribe un `alt_text`
   dentro del límite, **Then** se guarda y se envía; si excede el límite, se rechaza; nunca se
   genera automáticamente.
5. **Given** una publicación Threads en `PUBLISHING` o `PUBLISHED`, **When** se intenta editar
   su texto u opciones, **Then** se rechaza (mismas reglas que el resto de la metadata).

---

### User Story 5 - Validar todo antes de cualquier efecto remoto de publicación (Priority: P1)

Como usuario, quiero que cualquier problema detectable se detecte antes de que AutoPublisher
exponga ningún archivo o cree nada en Threads.

"Antes de cualquier efecto remoto" significa antes de subir/exponer media en el proveedor de
media delivery, crear un container o ejecutar `threads_publish`. Durante el preflight SÍ se
permiten: lecturas locales, inspección local del media, obtención/renovación segura de la
credencial mediante la Feature 010, consultas de solo lectura a Meta y la consulta de cuota.

**Why this priority**: un fallo a mitad de flujo deja recursos o containers huérfanos.

**Independent Test**: para cada condición de preflight, preparar el fallo con fakes y
comprobar que la publicación no pasa a `PUBLISHING`, que no se subió nada al proveedor, que no
se creó ningún container y que el usuario ve un error seguro.

**Acceptance Scenarios**:

1. **Given** cualquiera de estas condiciones: proyecto o cuenta inactivos, cuenta no Threads,
   cuenta `Not connected` o `Reconnect required`, credencial no utilizable, identidad o
   permisos no disponibles según la Feature 010, Content o archivo inexistente (cuando hay
   media), tipo de media no soportado, media incompatible, texto inválido, opciones inválidas,
   media delivery no configurado (solo imagen/vídeo), cuota agotada según Meta o ejecución ya
   en curso, **When** se intenta ejecutar, **Then** el preflight falla con un error específico,
   la publicación no pasa a `PUBLISHING`, no se expone ningún archivo y no se crea ningún
   container.
2. **Given** que la cuota de publicación está agotada según Meta, **When** se ejecuta el
   preflight, **Then** falla con un error seguro de cuota agotada, usando los valores de Meta
   como fuente de verdad, no un número fijo propio.
3. **Given** una publicación válida, **When** el usuario consulta su comprobación local de
   publicación, **Then** ve los problemas detectables localmente de Threads (texto, opciones,
   compatibilidad del media, configuración de media delivery) igual que en YouTube e Instagram.

---

### User Story 6 - Publicación automática programada en Threads (Priority: P2)

Como usuario, quiero programar una publicación Threads armada y que el scheduler genérico la
publique a su hora, exactamente una vez.

**Why this priority**: la automatización es el valor principal de AutoPublisher, pero depende
de la publicación manual (P1).

**Independent Test**: con reloj inyectable y fakes, programar una publicación Threads armada,
avanzar el reloj y comprobar una sola ejecución con origen `scheduled`; repetir con la
automatización pausada; y comprobar con un test de arquitectura que scheduler, núcleo de
publicación y núcleo de Accounts no importan código de Threads.

**Acceptance Scenarios**:

1. **Given** una publicación Threads `SCHEDULED`, armada y vencida dentro de la ventana de la
   Feature 007, **When** el scheduler hace su ciclo, **Then** la ejecuta mediante el mismo
   servicio que `Publish now`, con origen `scheduled`.
2. **Given** la automatización global en pausa, **When** vence una publicación Threads
   armada, **Then** no se ejecuta; `Publish now` sigue disponible y una ejecución en curso no
   se cancela.
3. **Given** un `Publish now` y un ciclo del scheduler sobre la misma publicación, o dos
   ciclos concurrentes, **When** coinciden, **Then** como máximo una ejecución comienza y se
   respeta la concurrencia máxima existente.
4. **Given** que el preflight de Threads falla a la hora programada, **When** el scheduler lo
   detecta, **Then** se aplica el comportamiento genérico de la Feature 007 para fallos de
   preflight.

---

### User Story 7 - Nunca publicar un duplicado ante fallos, cortes o reinicios (Priority: P2)

Como usuario, quiero la garantía de que, aunque se corte la red, Meta no responda o
AutoPublisher se reinicie, nunca aparecerán dos posts iguales en mi Threads por culpa de
AutoPublisher.

**Why this priority**: un post duplicado en una cuenta real es el fallo más grave
(Constitution, principio V).

**Independent Test**: con fakes, interrumpir la ejecución en cada fase (antes del container,
con container creado, en procesamiento, tras el write-ahead, durante y después de
`threads_publish`) y comprobar: estado final, resultado determinado o ambiguo, que
`threads_publish` se llama como máximo una vez por intento y nunca se repite automáticamente,
que no se buscan posts recientes y que el media temporal se limpia o queda registrado.

**Acceptance Scenarios**:

1. **Given** una ejecución que falla o se interrumpe antes del write-ahead, **When** termina o
   el backend se reinicia, **Then** la publicación queda `FAILED` con resultado determinado (no
   se publicó nada).
2. **Given** que AutoPublisher va a ejecutar `threads_publish`, **When** lo hace, **Then** antes
   ha confirmado de forma persistente la fase final irreversible (write-ahead); si no puede
   persistirla, no publica.
3. **Given** una llamada a `threads_publish` sin respuesta concluyente, **When** se evalúa,
   **Then** no se repite la llamada ni se crea otro container; solo se consulta en modo lectura
   el container original: si Meta confirma `PUBLISHED`, la publicación queda `PUBLISHED`
   (sin post ID ni enlace inventados si no pueden obtenerse de forma oficial e inequívoca); en
   cualquier otro caso, el intento queda ambiguo y exige revisión manual.
4. **Given** una publicación `FAILED` con intento ambiguo y container conocido, **When** el
   usuario consulta la comprobación o pulsa `Publish now`, **Then** primero se reconcilia en
   modo lectura el container original mediante el punto de extensión existente; si no se
   confirma `PUBLISHED`, un nuevo intento exige que el usuario reconozca que ha comprobado en
   Threads que no se publicó; el scheduler nunca la reintenta.
5. **Given** una publicación `PUBLISHED`, **When** ocurre cualquier reinicio o ciclo del
   scheduler, **Then** nunca se vuelve a publicar.
6. **Given** que la limpieza del media temporal falla tras una publicación confirmada, **When**
   termina la ejecución, **Then** la publicación sigue `PUBLISHED`, el intento `succeeded` y se
   registra un aviso seguro y la limpieza pendiente.

---

### User Story 8 - Entender los fallos y la pérdida de conexión (Priority: P3)

Como usuario, quiero que cualquier fallo de una publicación Threads me explique qué ha pasado y
qué puedo hacer, y que una credencial invalidada por Meta marque la cuenta para reconexión sin
confundirla con un fallo temporal.

**Why this priority**: mejora la recuperabilidad y la confianza sobre flujos ya cubiertos.

**Independent Test**: con fakes, provocar cada categoría de error y comprobar código seguro,
mensaje, estado de la publicación, estado de la conexión y ausencia de respuestas crudas de
Meta.

**Acceptance Scenarios**:

1. **Given** que Meta invalida definitivamente la credencial o retira un permiso durante una
   ejecución, **When** se detecta, **Then** la conexión pasa a `Reconnect required` según las
   reglas de la Feature 010 y la ejecución falla de forma segura.
2. **Given** un error temporal de red, disponibilidad o límite de peticiones, **When** ocurre,
   **Then** la conexión NO pasa a `Reconnect required`.
3. **Given** una publicación `FAILED`, **When** el usuario la consulta, **Then** ve el último
   error, si el resultado remoto está determinado o es ambiguo y el historial de intentos con su
   origen.

---

### Edge Cases

- **Texto con muchos emojis cerca del límite**: la validación aplica la regla de conteo
  documentada por Meta (emojis según su longitud en bytes UTF-8, a concretar en el plan) de
  forma conservadora; si aun así Meta rechaza el texto al crear el container, el fallo es
  determinado (no se publicó).
- **Texto con más de 5 enlaces**: se rechaza en preflight; nunca se eliminan enlaces.
- **Texto que contiene `#etiqueta`**: Threads puede convertir la primera etiqueta válida en
  topic tag; AutoPublisher no la añade, quita ni modifica, y la interfaz lo indica.
- **Imagen/vídeo sin texto**: se permite (el texto es opcional en `IMAGE`/`VIDEO`).
- **Imagen WebP u otro formato no listado por Threads**: política técnica documentada en el
  plan (conversión temporal sin alteración creativa o rechazo); nunca silenciosa.
- **Imagen con ancho fuera de 320–1440**: Meta la escala; no es motivo de rechazo. Relación de
  aspecto > 10:1 o tamaño > 8 MB (tras cualquier conversión técnica): se rechaza en preflight.
- **Vídeo WebM, más de 5 minutos, > 1 GB, fuera de 23–60 FPS, codec o audio no soportados**: se
  rechaza en preflight indicando el requisito; no se transcodifica.
- **Requisitos de vídeo no comprobables localmente** (closed GOP, edit lists, posición de
  `moov`): el plan decide cuáles se validan localmente; los no verificables los valida Meta y
  su rechazo en el container es un fallo determinado.
- **Herramienta de inspección de vídeo no disponible**: el preflight falla con un mensaje claro
  en lugar de publicar a ciegas (patrón de la Feature 003).
- **Meta no puede descargar el media** (URL rechazada o caducada): el container falla con un
  error seguro de entrega/procesamiento; no se ejecuta `threads_publish`. Si ocurre en la
  validación real con URLs firmadas, es una stop condition.
- **URL firmada que caduca antes de que Meta termine de descargar el vídeo**: la validez de la
  URL DEBE cubrir el tiempo máximo de procesamiento definido.
- **Cuota no consultable temporalmente o con forma inesperada**: la política (continuar o
  fallar) se decide en el plan; nunca se inventa un valor y nunca se usa como anti-duplicado.
- **Cuota agotada entre el preflight y `threads_publish`**: si Meta rechaza explícitamente,
  fallo determinado.
- **Container caducado (24 h)**: no se usa; un nuevo intento crea un container nuevo.
- **Reinicio con container en procesamiento**: `FAILED` determinado (no se inició
  `threads_publish`); el media temporal se limpia o queda pendiente.
- **Reinicio con la fase final registrada**: ambiguo salvo reconciliación de solo lectura que
  confirme `PUBLISHED`; nunca se repite `threads_publish`.
- **Permalink omitido por Meta** (p. ej. por copyright): la publicación sigue `PUBLISHED` sin
  enlace; no se construye un enlace a partir del ID o del username.
- **Cambio de identidad de la cuenta Threads**: el preflight falla con el error de identidad de
  la Feature 010; nunca se publica en otra cuenta.
- **Publicación sin `Content` en YouTube, Instagram u otra plataforma que no lo admite**: se
  rechaza; esas plataformas mantienen exactamente su comportamiento actual (FR-003).
- **Publicación Threads de imagen o vídeo cuyo `Content` no es del tipo esperado**: se rechaza en
  preflight.
- **Desconexión mientras hay una ejecución en curso**: regla genérica existente (no se permite
  desconectar una cuenta con publicaciones en `PUBLISHING`).

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance e integración con la arquitectura genérica

- **FR-001**: El sistema DEBE registrar un publisher de Threads en el registro genérico de
  publishers existente, de modo que una `Publication` destinada a una `Account` Threads se
  ejecute con el mismo servicio de ejecución, preflight genérico, estados,
  `PublicationAttempt`, fases, progreso, errores y resultado remoto que YouTube e Instagram.
- **FR-002**: Solo DEBEN poder publicarse en Threads: un post de texto sin media, una imagen
  individual y un vídeo individual. Cualquier otro caso se rechaza en preflight.
- **FR-003**: El modelo común de `Publication` DEBE permitir, de forma neutral respecto a la
  plataforma, que el `Content` asociado sea opcional. Reglas funcionales:
  - Threads texto: publicación sin `Content` permitida.
  - Threads imagen: `Content` de tipo imagen obligatorio.
  - Threads vídeo: `Content` de tipo vídeo obligatorio.
  - YouTube e Instagram DEBEN seguir exigiendo `Content` exactamente como hasta ahora.
  - El resto de plataformas mantienen su comportamiento actual.
  La ausencia de `Content` NO convierte cualquier publicación en válida: cada publisher o
  plataforma DEBE validar si admite publicaciones sin media, y una publicación sin `Content` de
  una plataforma que no lo admite DEBE rechazarse. NO DEBE crearse un tipo de `Content` de
  texto ni ningún archivo ficticio, y `Publication` NO DEBE recibir campos específicos de
  Threads. El plan DEBE determinar los cambios neutrales necesarios en modelo y migración,
  schemas/API, creación y edición de publicaciones, preflight genérico, frontend y tests de
  regresión.
- **FR-003a**: El tipo de una publicación Threads DEBE derivarse de forma determinista: sin
  `Content` → texto (`TEXT`); `Content` imagen → imagen (`IMAGE`); `Content` vídeo → vídeo
  (`VIDEO`). El plan DEBE revisar si hace falta persistir algún discriminador neutral; no se
  añade salvo necesidad demostrada.
- **FR-004**: El scheduler, el núcleo genérico de publicación y el núcleo de Accounts NO DEBEN
  importar ni contener lógica de Threads ni de ningún proveedor concreto de media delivery.
  DEBE existir un test de arquitectura que lo garantice.
- **FR-005**: NO DEBE crearse un scheduler, ejecutor, estado de `Publication`, modelo de
  intentos ni sistema de media delivery específicos de Threads. Cualquier extensión necesaria
  de las interfaces genéricas DEBE ser neutral y no romper YouTube ni Instagram.
- **FR-006**: El publisher DEBE reutilizar exclusivamente la conexión y los servicios internos
  de la Feature 010 (credencial válida con renovación, identidad vinculada, reglas de
  `Reconnect required`). NO DEBE introducir otro flujo OAuth ni otro sistema de credenciales.
- **FR-007**: El host, la versión de la Threads API y la configuración base DEBEN proceder de la
  única fuente común definida en la Feature 010, sin duplicarse.

#### Media delivery (solo imagen y vídeo)

- **FR-008**: Para imagen y vídeo, el sistema DEBE reutilizar el `MediaDeliveryProvider`
  genérico existente (bucket privado, URL temporal firmada, lifecycle del proveedor como última
  red de seguridad). NO DEBE crearse otro mecanismo de entrega para Threads.
- **FR-009**: La referencia no sensible del recurso temporal DEBE persistirse (con commit)
  **antes** de subirlo o exponerlo, conforme a la garantía crash-safe de la Feature 009.
- **FR-010**: La URL firmada DEBE tratarse completa como secreto: nunca persistirse, registrarse
  en logs, incluirse en errores ni enviarse al frontend. Su validez DEBE cubrir el tiempo
  máximo durante el que Meta puede necesitar descargar el media.
- **FR-011**: Si no existe configuración válida de media delivery, el preflight de imagen y
  vídeo DEBE fallar con un error claro de configuración. Las publicaciones de texto NO DEBEN
  requerir ni crear ningún recurso de media delivery.
- **FR-012**: La validación real DEBE confirmar que Threads acepta las URLs firmadas actuales
  del proveedor; si las rechaza, se detiene la validación y se revisa el diseño.

#### Imagen

- **FR-013**: El preflight DEBE validar la imagen contra los requisitos vigentes de Threads
  (formato, tamaño, relación de aspecto) antes de cualquier efecto remoto, y el plan DEBE
  fijar una política explícita para JPEG, PNG y WebP.
- **FR-014**: Si hace falta una conversión técnica (por ejemplo, de un formato no soportado),
  DEBE generarse una copia temporal sin recortar, reencuadrar ni redimensionar creativamente,
  documentada en el plan, y eliminarse al terminar. Si la conversión segura no es posible, el
  preflight DEBE fallar con explicación. El original NUNCA DEBE modificarse.

#### Vídeo

- **FR-015**: El preflight DEBE inspeccionar localmente el vídeo (inspección de media
  existente) contra los requisitos vigentes de Threads (contenedor, codecs, audio, resolución,
  relación de aspecto, duración, frame rate, bitrate, tamaño) antes de cualquier efecto remoto,
  e indicar qué requisito no se cumple.
- **FR-016**: El sistema NO DEBE transcodificar ni modificar vídeos en esta versión.

#### Texto

- **FR-017**: El texto enviado DEBE ser el texto efectivo definido en AutoPublisher, enviado sin
  transformaciones: el sistema NO DEBE añadir hashtags, enlaces, topic tags, menciones ni
  ningún otro elemento que el usuario no haya escrito, ni truncar, normalizar o reescribir el
  texto.
- **FR-018**: El texto final de Threads DEBE construirse de forma determinista así: (1) la
  descripción efectiva; (2) si existen hashtags efectivos, una línea en blanco y después los
  hashtags efectivos formateados exactamente según el mecanismo de metadata existente. El
  título efectivo NUNCA DEBE enviarse. Los hashtags solo se incluyen porque son metadata
  configurada por el usuario; AutoPublisher no genera hashtags nuevos ni añade `topic_tag`,
  enlaces, menciones ni ninguna otra transformación. Threads puede interpretar la primera
  etiqueta válida del texto como topic tag por comportamiento propio de la plataforma;
  AutoPublisher no la transforma, y la documentación DEBE indicarlo.
- **FR-019**: El texto final (después de la composición de FR-018) DEBE validarse antes de
  cualquier efecto remoto contra todos los límites vigentes de Threads: longitud máxima según la
  regla de conteo documentada por Meta (verificada en el plan), número máximo de enlaces y
  cualquier otra regla vigente. Para un post de texto, el texto final NO PUEDE quedar vacío;
  para imagen y vídeo PUEDE quedar vacío. Un texto inválido NUNCA DEBE truncarse ni corregirse
  automáticamente.
- **FR-020**: La interfaz DEBE mostrar el texto exacto que se enviará y su validez.

#### Opciones específicas de Threads

- **FR-021**: Las opciones de Threads DEBEN persistirse en una estructura propia de Threads,
  separada del modelo común de `Publication` (mismo patrón que YouTube e Instagram).
- **FR-022**: La única opción de esta versión es `alt_text`, opcional, solo para imagen y
  vídeo, validada con el límite vigente (1000 caracteres). NUNCA DEBE generarse
  automáticamente. Vacío → no se envía.
- **FR-023**: NO DEBEN exponerse ni enviarse otros parámetros opcionales de la API
  (`reply_control`, `topic_tag`, `link_attachment`, `allowlisted_country_codes`, `location_id`,
  `quote_post_id`, `poll_attachment`, `gif_attachment`, `is_spoiler_media`, `text_entities`,
  `text_attachment`, `is_ghost_post`, `enable_reply_approvals`, `crossreshare_to_ig*`); se
  aplican los valores por defecto de Meta. Si el plan demuestra que alguno es imprescindible
  para publicar correctamente, DEBE justificarlo y revisarse antes de incluirlo.
- **FR-024**: Las opciones y el texto DEBEN poder editarse mientras la publicación sea editable y
  NO DEBEN poder editarse en `PUBLISHING` ni `PUBLISHED`. No DEBEN mostrarse ni aceptarse en
  publicaciones de otras plataformas.

#### Preflight

- **FR-025**: Antes de cualquier efecto remoto, el sistema DEBE validar como mínimo:
  publicación ejecutable; `Account` y proyecto activos; plataforma Threads; conexión
  `Connected`; credencial utilizable, identidad coincidente y permisos necesarios según la
  Feature 010; Content y archivo existentes cuando hay media; tipo de media soportado; media
  compatible (o convertible según la política); texto válido; opciones válidas; media delivery
  configurado para imagen/vídeo; cuota disponible cuando pueda comprobarse de forma fiable;
  ninguna ejecución activa; y cualquier condición genérica existente.
- **FR-026**: Durante el preflight SÍ se permiten: lecturas locales, inspección local del media
  (incluida la preparación de derivados técnicos temporales no expuestos), obtención/renovación
  de la credencial mediante la Feature 010, consultas de solo lectura a Meta y la consulta de
  cuota. Antes de superarlo NO se permite subir/exponer media, crear un container ni ejecutar
  `threads_publish`.
- **FR-027**: Las reglas comunes del preflight DEBEN reutilizarse sin duplicarse; el publisher
  de Threads solo añade sus comprobaciones específicas. Si el preflight falla, la publicación NO
  DEBE pasar a `PUBLISHING`.

#### Límite de publicación

- **FR-028**: El plan DEBE verificar el contrato real de `threads_publishing_limit` (forma de la
  respuesta, campos, ventana, qué operaciones consumen cuota, retraso del contador). Cuando Meta
  devuelva la cuota y su configuración, el sistema DEBE usarlas como fuente de verdad y NO DEBE
  depender de una cifra fija propia.
- **FR-029**: Si Meta indica que no hay cuota disponible, el preflight DEBE fallar con un error
  seguro. La cuota NUNCA DEBE usarse como mecanismo transaccional de anti-duplicado. Una
  respuesta inesperada o un error temporal en la consulta DEBEN tratarse según una política
  explícita del plan, sin inventar valores. No se crea ningún sistema de analytics de uso.

#### Containers y procesamiento

- **FR-030**: Para los tres tipos (incluido texto) DEBE seguirse la secuencia
  `crear container → persistir fase → threads_publish`. `auto_publish_text` NO DEBE usarse,
  salvo que el plan demuestre que mantiene exactamente las mismas garantías de write-ahead y
  anti-duplicado y se revise antes.
- **FR-031**: Tras crear el container, el sistema DEBE persistir de forma no sensible su
  identificador y su último estado conocido antes de esperar o publicar.
- **FR-032**: `threads_publish` SOLO DEBE ejecutarse cuando el container esté en una condición
  que la documentación oficial vigente considere publicable. La spec NO asume que texto,
  imagen y vídeo requieran la misma espera; el plan DEBE verificarlo por tipo:
  - **Texto**: si, con el flujo explícito sin `auto_publish_text`, puede llamarse a
    `threads_publish` directamente tras crear correctamente el container o si Meta exige
    comprobar `FINISHED`.
  - **Imagen**: si requiere consultar el estado antes de `threads_publish`.
  - **Vídeo**: DEBE esperarse al estado oficial listo para publicar (`FINISHED`) consultando el
    estado con intervalo y tiempo máximo acotados basados en las recomendaciones oficiales
    vigentes, sin espera activa continua y respetando el cierre ordenado de la aplicación.
  Si un tipo no necesita consultar el estado, NO DEBEN introducirse esperas artificiales. En
  todos los tipos se mantienen la persistencia del container antes de la publicación final
  (FR-031), el write-ahead (FR-035), `threads_publish` como máximo una vez (FR-036) y la
  reconciliación mediante el container ante resultados ambiguos (FR-038, FR-040).
- **FR-033**: `ERROR` o `EXPIRED` observados **antes** de invocar `threads_publish` DEBEN
  tratarse como fallo determinado, sin publicar. El `error_message` de Meta DEBE traducirse a un
  código/mensaje seguro.
- **FR-034**: Cada intento DEBE crear como máximo un container. La reutilización de un container
  de un intento anterior solo se permite si el plan demuestra que es segura (no publicado, no
  caducado, mismos media, texto y opciones).

#### Publicación final (`threads_publish`), write-ahead y resultado ambiguo

- **FR-035**: Antes de llamar a `threads_publish`, el sistema DEBE persistir y confirmar
  (commit) la fase final irreversible mediante el mecanismo genérico existente; si no puede
  confirmarla, NO DEBE publicar (fallo determinado).
- **FR-036**: `threads_publish` DEBE llamarse como máximo una vez por container y NUNCA DEBE
  repetirse automáticamente.
- **FR-037**: Si `threads_publish` devuelve claramente el Threads post ID, la ejecución es un
  éxito normal (FR-045).
- **FR-038**: Si el resultado no es concluyente (timeout, corte, 5xx, fin del proceso,
  respuesta inesperada), el sistema NO DEBE repetir la llamada ni crear otro container. Solo
  DEBE consultar, en modo lectura y mediante mecanismos oficiales, el container original. La
  única señal aceptada para resolver automáticamente es que el container figure como
  `PUBLISHED`; cualquier otro estado, error de consulta o ausencia de respuesta deja el intento
  `FAILED` ambiguo y exige revisión manual. El plan DEBE investigar qué estados oficiales
  permiten demostrarlo inequívocamente.
- **FR-039**: Si Meta confirma la publicación pero ningún mecanismo oficial e inequívoco
  devuelve el post ID, el sistema NUNCA DEBE inferirlo (por ejemplo, buscando posts recientes
  por texto, hora o media): DEBE registrar la publicación como confirmada sin identidad remota
  e informar al usuario, bloqueando cualquier nuevo intento.
- **FR-040**: Una publicación con resultado ambiguo NUNCA DEBE reintentarse automáticamente.
  Antes de exigir el reconocimiento manual, el sistema DEBE intentar la reconciliación de solo
  lectura del container original mediante el punto de extensión neutral existente; si no
  confirma `PUBLISHED`, una nueva ejecución manual DEBE requerir que el usuario reconozca
  explícitamente que ha comprobado en Threads que el post no se publicó (modelo de las Features
  006/009).

#### Reintentos, errores y conexión

- **FR-041**: Los errores DEBEN clasificarse al menos en: temporales, definitivos,
  credencial/reconexión, permisos, texto inválido, media incompatible, cuota/límite de
  peticiones, fallo de entrega del media, fallo de procesamiento, tiempo agotado, container
  caducado y resultado ambiguo.
- **FR-042**: Los reintentos automáticos dentro de una ejecución SOLO DEBEN aplicarse a
  operaciones sin efecto de publicación (consultas de estado, subida al proveedor), con número
  y espera acotados. No existen reintentos automáticos entre intentos.
- **FR-043**: Si Meta invalida definitivamente la credencial o retira un permiso durante una
  ejecución, el sistema DEBE marcar `Reconnect required` mediante los servicios de la Feature
  010. Los errores temporales NO DEBEN cambiar el estado de conexión.

#### Reinicios y recuperación

- **FR-044**: Al arrancar, la recuperación genérica DEBE seguir aplicándose sin red y sin
  lógica de Threads: ninguna ejecución se reanuda; la publicación queda `FAILED` determinada si
  no se había alcanzado la fase final, y ambigua si se había alcanzado (resoluble después solo
  mediante la reconciliación de FR-040). Los recursos temporales pendientes DEBEN limpiarse
  best-effort con el mecanismo genérico existente.

#### Resultado publicado y cleanup

- **FR-045**: Cuando Meta confirme la publicación, el sistema DEBE, en este orden: (1)
  persistir el Threads post ID (si se conoce), el permalink oficial (si puede recuperarse de
  forma inequívoca mediante el mecanismo oficial), timestamps y el resultado remoto seguro,
  conservando el texto y las opciones usados; (2) marcar la publicación `PUBLISHED`; (3) marcar
  el intento `succeeded`; y (4) solo después ejecutar el cleanup best-effort del media temporal
  y de los derivados locales. Los pasos (1)–(3) PUEDEN ir en una misma transacción; el cleanup
  nunca.
- **FR-046**: El permalink NUNCA DEBE inventarse ni construirse a partir del ID o del username.
  Si no puede obtenerse, la publicación sigue `PUBLISHED` sin enlace y se informa al usuario.
  `Open on Threads` solo DEBE mostrarse si existe una URL oficial conocida.
- **FR-047**: Un fallo de cleanup NUNCA DEBE cambiar `PUBLISHED` a `FAILED` ni un intento
  `succeeded` a `failed`; DEBE registrarse como aviso seguro y limpieza pendiente. Los posts de
  texto no tienen cleanup de media.

#### Scheduler, pausa y concurrencia

- **FR-048**: Las publicaciones Threads DEBEN ejecutarse con el ejecutor genérico: origen
  `manual` para `Publish now` y `scheduled` para el scheduler. La pausa global, la protección
  frente a carreras manual/scheduler, los ciclos concurrentes y la concurrencia máxima
  existentes DEBEN reutilizarse sin reimplementarse ni añadir lógica de Threads al scheduler.

#### API, errores e interfaz

- **FR-049**: La API DEBE permitir consultar y editar las opciones de Threads, consultar el texto
  final y la compatibilidad del media, y exponer intentos, fases, errores y resultado remoto
  mediante los endpoints genéricos existentes. Ninguna respuesta DEBE incluir tokens,
  credenciales del proveedor ni URLs firmadas.
- **FR-050**: Los errores DEBEN seguir el formato estructurado existente con códigos estables y
  seguros que distingan al menos: Threads no conectado, reconexión requerida, permiso ausente,
  media delivery no configurado, fallo de entrega del media, media incompatible (imagen/vídeo),
  texto inválido, cuota agotada, límite de peticiones/temporal, creación de container fallida,
  procesamiento fallido, procesamiento agotado, container caducado, `threads_publish` fallido,
  resultado ambiguo, ejecución interrumpida y limpieza fallida (como aviso). Nunca DEBEN
  devolverse respuestas crudas de Meta.
- **FR-051**: Para una publicación Threads, la interfaz DEBE mostrar, reutilizando los
  componentes existentes y sin rediseño: tipo (texto, imagen o vídeo), texto final y su
  validez, `alt_text` cuando aplique, compatibilidad/preflight, `Publish now`, programación y
  publicación automática existentes, progreso por fases reales (sin porcentajes inventados),
  errores, historial de intentos y `Open on Threads` cuando corresponda.

#### Seguridad, persistencia, documentación y calidad

- **FR-052**: Se DEBEN mantener todas las garantías de seguridad de las Features 005–010. El
  redactor de logs existente DEBE cubrir los nuevos valores sensibles y DEBEN existir tests que
  verifiquen la ausencia de secretos y URLs firmadas en base de datos, logs, respuestas de la
  API y almacenamiento del navegador.
- **FR-053**: Las opciones de Threads y los datos de recuperación no sensibles DEBEN persistir
  mediante migraciones versionadas.
- **FR-054**: La documentación (README y `quickstart.md`) DEBE explicar la publicación de texto,
  imagen y vídeo en Threads, los límites de texto y media, `alt_text`, el tratamiento de
  resultados ambiguos y la reutilización del media delivery.
- **FR-055**: Los tests automatizados DEBEN ejecutarse offline, sin Meta real, sin proveedor de
  media real y sin keyring real, con fakes, y cubrir como mínimo los casos enumerados en la
  descripción de la feature: texto (container `TEXT`, publish, sin media delivery, texto
  exacto); imagen (preflight, media delivery, container `IMAGE`, `alt_text`, publish, cleanup);
  vídeo (inspección local, media delivery, polling, publish, timeout/error, cleanup); cuota
  (forma válida, agotada, error temporal, respuesta inesperada); seguridad y duplicados
  (write-ahead, `threads_publish` como máximo una vez, ambigüedad, reconciliación, reinicio en
  cada fase relevante, carrera manual/scheduler, ausencia de secretos y de URLs firmadas); y
  regresión (YouTube, Instagram, conexión Threads, scheduler/núcleo sin imports de Threads).
- **FR-056**: `quickstart.md` DEBE incluir una validación real con la cuenta Threads ya
  conectada, usando solo contenido inocuo creado para la prueba, en este orden: texto, imagen,
  vídeo y publicación programada. DEBE comprobar: forma real de la cuota, containers y estados
  observados, aceptación de las URLs firmadas, post ID, permalink, tiempos, cleanup, reinicio,
  scheduler y ausencia de secretos; NO DEBE provocar deliberadamente timeouts ni resultados
  ambiguos en producción; y DEBE indicar borrar manualmente los posts de prueba en Threads.
- **FR-057**: La validación real DEBE detenerse y el diseño revisarse si: Threads rechaza las
  URLs firmadas; la forma real de la cuota es incompatible; los estados reales del container
  contradicen el modelo; no puede mantenerse la garantía de no duplicar; aparece cualquier
  secreto en almacenamiento, logs o API; o el publisher necesita permisos distintos de los ya
  concedidos.

### Key Entities *(include if feature involves data)*

- **Threads Publication Options**: opciones específicas de Threads de una `Publication` Threads,
  separadas del modelo común: `alt_text` (opcional, solo imagen/vídeo).
- **Texto de Threads**: valor derivado y determinista (no un campo editable nuevo): descripción
  efectiva y, si existen, una línea en blanco y los hashtags efectivos (FR-018).
- **Tipo de publicación Threads**: derivado de forma determinista del `Content` asociado (sin
  `Content` → texto; imagen → imagen; vídeo → vídeo), sin campo propio salvo necesidad
  demostrada en el plan (FR-003a).
- **Threads Media Container**: objeto remoto de Meta creado por intento antes de publicar;
  atributos persistidos no sensibles: identificador, tipo (`TEXT`/`IMAGE`/`VIDEO`), último
  estado conocido y momento de creación, para recuperación y reconciliación sin duplicados.
- **Temporary Media Resource** (existente, Feature 009): se reutiliza para imagen/vídeo con su
  referencia no secreta persistida antes de la subida y su estado de limpieza independiente.
- **PublicationAttempt** (existente): se reutiliza con origen, fases, progreso, error,
  resultado determinado/ambiguo y resultado remoto (post ID y enlace opcionales).
- **Publication** (existente): no recibe campos de Threads; su `Content` pasa a ser opcional de
  forma neutral (FR-003) y cada plataforma decide si admite publicaciones sin `Content`.
- **Threads Connection** (existente, Feature 010): fuente de la credencial, la identidad y los
  permisos; sin cambios de modelo salvo lo necesario para marcar `Reconnect required`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real de `quickstart.md` (publicación Threads →
  `Publish now` → post real → `Open on Threads`) para texto, imagen y vídeo sin editar archivos
  de datos ni la base de datos a mano.
- **SC-002**: Una publicación Threads programada y armada se publica exactamente una vez
  mediante el scheduler genérico en la validación real y en el 100 % de los tests de
  concurrencia.
- **SC-003**: 0 posts duplicados en todos los escenarios de fallo, corte e interrupción
  simulados: `threads_publish` se ejecuta como máximo una vez por container y nunca se repite
  automáticamente.
- **SC-004**: En el 100 % de los fallos de preflight no se expone ningún archivo ni se crea
  ningún container.
- **SC-005**: El 100 % de las publicaciones de texto se ejecutan sin crear ningún recurso de
  media delivery.
- **SC-006**: Tras el 100 % de las ejecuciones de imagen/vídeo terminadas y la limpieza de
  pendientes, no queda ningún recurso temporal accesible; el 100 % de los archivos originales
  permanecen idénticos byte a byte.
- **SC-007**: El texto mostrado coincide en el 100 % de los casos con el enviado a Threads, y 0
  textos se truncan o alteran.
- **SC-008**: Base de datos, logs, errores, respuestas de la API y almacenamiento del navegador
  contienen 0 tokens de Threads, 0 credenciales del proveedor y 0 URLs firmadas.
- **SC-009**: 0 enlaces `Open on Threads` mostrados sin una URL oficial devuelta por Meta.
- **SC-010**: 0 errores temporales provocan `Reconnect required`; cada error de FR-050 produce un
  mensaje comprensible que indica qué hacer y si el resultado está determinado o requiere
  revisión manual.
- **SC-011**: La suite de la feature se ejecuta sin Internet ni servicios reales, y scheduler,
  núcleo de publicación y núcleo de Accounts no contienen referencias a Threads.
- **SC-012**: YouTube, Instagram y la conexión de Threads siguen funcionando sin cambios de
  comportamiento (suites existentes en verde).

## Assumptions

- **Alcance**: solo texto, imagen individual y vídeo individual. Quedan fuera: carousels,
  replies, quote posts, polls, GIFs, topic tags explícitos, ubicaciones, ghost posts, spoilers,
  reply approvals, control de respuestas, restricción por países, insights, moderación,
  búsqueda, borrado remoto, cross-posting con Instagram, transcoding de vídeo y rediseño de UI.
- **Sin declaración de IA**: a diferencia de Instagram, la Threads API vigente no expone un
  parámetro de self-disclosure de contenido generado por IA; no se añade ninguna opción
  equivalente.
- **Publicaciones sin `Content`**: los cambios neutrales del modelo común (migración, API,
  creación y edición, preflight genérico, frontend y regresión) los determina el plan (FR-003).
- **Comportamientos automáticos de Meta**: la vista previa del primer enlace y la conversión de
  la primera etiqueta `#` en topic tag son comportamientos de Threads sobre el texto del
  usuario, no transformaciones de AutoPublisher; se informan en la interfaz y la documentación.
- **Decisiones diferidas al plan** (verificadas en documentación oficial vigente): host,
  versión y uso de `/me` o del Threads user ID; regla exacta de conteo del texto; política de
  formatos de imagen (en particular WebP); qué requisitos de vídeo se validan localmente;
  necesidad de consultar el estado del container por tipo (FR-032) e intervalos y tiempos
  máximos donde se requiera; validez de la URL firmada; contrato y
  política de error de `threads_publishing_limit`; forma de obtener el permalink; reutilización
  o no de containers; nombres de códigos de error y de fases (reutilizando las genéricas).
- **Precedentes reutilizados**: confirmación de `Publish now`, preflight, estados, write-ahead,
  reconocimiento manual ante resultado ambiguo y recuperación de intentos interrumpidos
  (Features 006/009); elegibilidad, consentimiento, ventana, pausa y concurrencia (Feature
  007); media delivery crash-safe, reconciliación de solo lectura, resultado sin identidad
  remota y orden resultado → cleanup (Feature 009); credencial, identidad y permisos (Feature
  010).
- **Usuario y entorno**: un único usuario local, con su cuenta Threads conectada como Threads
  tester de su propia Meta App en Development Mode (sin App Review), el proveedor de media
  delivery ya configurado para Instagram y AutoPublisher encendido a la hora de las
  publicaciones programadas.
- **Dependencias**: Content y su inspección de media (Feature 003), `Publication` y metadata
  efectiva (Feature 004), ejecución genérica y `PublicationAttempt` (Feature 006), scheduler
  (Feature 007), media delivery y reconciliación (Feature 009), conexión Threads (Feature 010),
  formato de errores, redactor de logs y migraciones existentes.
