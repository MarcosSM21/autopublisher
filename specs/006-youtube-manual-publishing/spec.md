# Feature Specification: Publicación manual real de vídeos en YouTube

**Feature Branch**: `006-youtube-manual-publishing`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "Crear la Feature 006 de AutoPublisher: publicación manual real de vídeos en YouTube. Permitir ejecutar manualmente (`Publish now`, con confirmación) una `Publication` existente cuyo destino sea una Account YouTube conectada, subir realmente su vídeo al canal mediante el protocolo oficial de subida resumible de YouTube y conservar de forma fiable el resultado (video ID, URL, privacidad real). Introduce los estados `PUBLISHING`, `PUBLISHED` y `FAILED`, la entidad genérica `PublicationAttempt`, opciones específicas de YouTube (privacidad, Made for Kids, synthetic media) fuera del modelo común, preflight completo antes de cualquier efecto externo, verificación del canal, progreso visible, recuperación limitada dentro del mismo intento, tratamiento seguro de reinicios durante la subida y protección frente a ejecuciones concurrentes. Sin scheduler automático, sin retries entre intentos, sin `publishAt`, sin otras plataformas ni imágenes en YouTube."

## Contexto

Hasta ahora una `Publication` (Feature 004) es solo una **intención** de publicar un
`Content` (Feature 003) en una `Account`, con fecha opcional y overrides de metadata. Ninguna
operación contacta con una red social. La Feature 005 permitió conectar una `Account` YouTube
con un canal real y obtener credenciales válidas sin pedir login, pero sin subir nada.

Esta feature introduce la **primera ejecución real** de una `Publication`: el usuario pulsa
`Publish now` sobre una publicación destinada a una cuenta YouTube conectada, confirma qué va
a subirse y a qué canal, y AutoPublisher sube el vídeo al canal, muestra el progreso y guarda
de forma persistente el resultado (video ID y enlace directo).

Flujo de referencia:

`Content` → `Publication` → `YouTube Account conectada` → `Publish now` → confirmación →
upload real → `Published` → URL del vídeo en YouTube

Principios rectores de esta feature:

- **Nunca publicar sin intención explícita**: no hay ejecución automática por fecha; toda
  ejecución empieza con una confirmación del usuario.
- **Nunca publicar en el canal equivocado**: el canal se verifica justo antes de subir.
- **Nunca duplicar un vídeo automáticamente**: ante un resultado ambiguo, AutoPublisher se
  detiene y pide revisión manual en lugar de volver a subir.
- **Nunca perder el resultado ni filtrar secretos**: el resultado se persiste; tokens y
  URLs de sesión de subida nunca salen de la memoria del proceso.

**No se introduce todavía el scheduler automático**: una `Publication` con fecha futura NO
se ejecuta sola cuando llega su hora.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicar ahora un vídeo en YouTube (Priority: P1)

Como usuario, quiero abrir una `Publication` de un vídeo destinada a mi cuenta YouTube
conectada, revisar su metadata y sus opciones, pulsar `Publish now`, confirmar el canal y la
privacidad, y ver cómo el vídeo se sube y queda publicado con un enlace directo a YouTube.

**Why this priority**: es el núcleo de la feature y el primer valor real de AutoPublisher:
publicar de verdad. Todo lo demás protege o complementa este flujo.

**Independent Test**: con un simulador de YouTube (sin Internet), en un proyecto activo con
una cuenta YouTube activa y conectada y una `Publication` `UNSCHEDULED` de un vídeo, con
privacidad `private` y Made for Kids y synthetic media declarados, pulsar `Publish now`,
confirmar, y comprobar que la publicación pasa a `PUBLISHING`, muestra progreso, termina
`PUBLISHED` con video ID y enlace `Open on YouTube`, que existe un `PublicationAttempt`
exitoso persistido y que el archivo local no ha cambiado.

**Acceptance Scenarios**:

1. **Given** una `Publication` `UNSCHEDULED` o `SCHEDULED` de un `Content` de tipo vídeo,
   destinada a una cuenta YouTube activa y `Connected` de un proyecto activo, con metadata y
   opciones YouTube válidas y completas, **When** el usuario la abre, **Then** ve la acción
   `Publish now` disponible junto al título, descripción, hashtags efectivos y opciones
   YouTube.
2. **Given** esa publicación, **When** el usuario pulsa `Publish now`, **Then** antes de
   cualquier efecto externo se muestra una confirmación con: título efectivo, canal YouTube
   real (título y channel ID), privacidad solicitada, si se notificará a los suscriptores y
   archivo/contenido que se va a subir;
   nada se envía a YouTube hasta que el usuario confirma.
3. **Given** la confirmación, **When** el usuario cancela, **Then** no se contacta con
   YouTube, no se crea ningún intento y la publicación conserva su estado.
4. **Given** la confirmación, **When** el usuario confirma, **Then** AutoPublisher ejecuta el
   preflight completo; si pasa, la publicación pasa a `PUBLISHING`, se crea un
   `PublicationAttempt` y la interfaz recibe respuesta inmediata sin esperar a que termine la
   subida.
5. **Given** una publicación `PUBLISHING`, **When** el usuario la observa (detalle o Queue),
   **Then** ve el estado `Publishing` y el progreso (bytes enviados o porcentaje) actualizado
   de forma razonablemente frecuente, y no puede lanzar otra ejecución ni editarla.
6. **Given** una subida en curso, **When** YouTube acepta el vídeo y devuelve un video ID
   válido, **Then** AutoPublisher persiste el resultado, marca el intento como exitoso, deja
   la publicación `PUBLISHED` con su fecha de publicación y muestra el enlace directo
   `Open on YouTube`.
7. **Given** una publicación `PUBLISHED`, **When** se reinician backend y frontend, **Then**
   la publicación sigue `PUBLISHED` con el mismo video ID, URL, privacidad real y su intento.
8. **Given** una publicación `PUBLISHED`, **When** el usuario pulsa `Open on YouTube`,
   **Then** se abre la URL directa del vídeo identificada por su video ID (nunca por título).
9. **Given** una subida completada, **When** se compara el archivo multimedia local con el de
   antes de publicar, **Then** es idéntico: no se ha duplicado, modificado ni transcodificado.

---

### User Story 2 - Configurar las opciones de YouTube de una publicación (Priority: P1)

Como usuario, quiero elegir la privacidad y declarar explícitamente si el vídeo es para niños
y si contiene contenido sintético o alterado realista, antes de publicar, para cumplir con
YouTube y no publicar con valores que yo no haya decidido.

**Why this priority**: sin estas declaraciones la publicación no puede ejecutarse; son
requisito previo del flujo P1 y tienen implicaciones legales y de visibilidad.

**Independent Test**: en una publicación YouTube, comprobar que la privacidad por defecto es
`private`, cambiarla a `unlisted`, declarar Made for Kids = No y synthetic media = No,
reiniciar la aplicación y comprobar que los valores persisten; comprobar que con alguna
declaración sin responder `Publish now` se rechaza indicando qué falta.

**Acceptance Scenarios**:

1. **Given** una publicación destinada a una cuenta YouTube, **When** el usuario la abre,
   **Then** ve las opciones YouTube: privacidad (`private`, `unlisted`, `public`),
   Made for Kids (Yes / No), synthetic/altered media (Yes / No) y `Notify subscribers`
   (Yes / No).
2. **Given** una publicación YouTube sin opciones configuradas, **When** se consulta, **Then**
   la privacidad es `private`, `Notify subscribers` es `No` y Made for Kids y synthetic media
   aparecen como "sin declarar" (no se presupone ningún valor).
3. **Given** una publicación YouTube en estado editable, **When** el usuario cambia y guarda
   cualquiera de las opciones, **Then** se persisten asociadas a esa publicación sin afectar a
   otras publicaciones ni al contenido.
4. **Given** una publicación con Made for Kids o synthetic media sin declarar, **When** el
   usuario pulsa `Publish now`, **Then** se rechaza en el preflight indicando qué declaración
   falta, sin contactar con YouTube.
5. **Given** una publicación destinada a una cuenta de otra plataforma, **When** se consulta,
   **Then** no muestra opciones YouTube.
6. **Given** la interfaz de opciones de privacidad, **When** se muestra, **Then** incluye una
   nota indicando que YouTube puede restringir a `private` los vídeos subidos desde proyectos
   API no verificados.

---

### User Story 3 - Validar todo antes de cualquier efecto externo (Priority: P1)

Como usuario, quiero que AutoPublisher compruebe todo lo que puede comprobar antes de subir
nada, para que los errores evitables se detecten sin tocar YouTube y sin dejar la publicación
en un estado intermedio.

**Why this priority**: un preflight completo evita subidas a medias, uploads al canal
equivocado y consumo innecesario de cuota; es la principal salvaguarda de la feature.

**Independent Test**: para cada condición del preflight (proyecto inactivo, cuenta inactiva,
plataforma no YouTube, cuenta `Not connected` o `Reconnect required`, canal efectivo distinto
del vinculado, contenido imagen, archivo inexistente, título vacío o demasiado largo,
descripción final demasiado larga, opciones sin declarar, ejecución ya activa) comprobar que
`Publish now` se rechaza con un error claro y específico, que la publicación no cambia de
estado, que no se crea sesión de subida y que el simulador de YouTube no recibe ninguna
petición de subida.

**Acceptance Scenarios**:

1. **Given** una publicación cuyo proyecto o cuenta está inactivo, **When** se solicita
   `Publish now`, **Then** se rechaza indicando qué debe reactivarse.
2. **Given** una publicación cuya cuenta no es YouTube, **When** se solicita `Publish now`,
   **Then** se rechaza como plataforma no soportada para publicación real.
3. **Given** una publicación de un `Content` de tipo imagen destinada a YouTube, **When** se
   consulta, **Then** `Publish now` no está disponible y se explica que YouTube solo acepta
   vídeos en AutoPublisher; si se fuerza, se rechaza.
4. **Given** una publicación cuyo archivo multimedia almacenado no está disponible, **When**
   se solicita `Publish now`, **Then** se rechaza indicando que el archivo no está disponible,
   antes de contactar con YouTube.
5. **Given** una cuenta YouTube `Not connected` o `Reconnect required`, **When** se solicita
   `Publish now`, **Then** se rechaza indicando que la cuenta debe conectarse o reconectarse.
6. **Given** una cuenta `Connected` cuyas credenciales no pueden renovarse (revocadas o
   ausentes), **When** se solicita `Publish now`, **Then** se rechaza, la cuenta pasa a
   `Reconnect required` según la Feature 005 y no se sube nada.
7. **Given** una cuenta `Connected` cuyas credenciales corresponden ahora a un channel ID
   distinto del vinculado, **When** se solicita `Publish now`, **Then** no se sube nada, se
   aplica el comportamiento de reconexión segura de la Feature 005 (la cuenta pasa a
   `Reconnect required`) y el usuario recibe un mensaje claro.
8. **Given** un título efectivo vacío, de más de 100 caracteres o con caracteres que YouTube
   rechaza, **When** se solicita `Publish now`, **Then** se rechaza indicando el problema del
   título; nunca se usa el nombre del archivo como sustituto.
9. **Given** una descripción final (descripción efectiva + hashtags) que supera el límite de
   YouTube o contiene caracteres que YouTube rechaza, **When** se solicita `Publish now`,
   **Then** se rechaza indicando el problema antes de crear ninguna sesión de subida.
10. **Given** cualquier fallo de preflight, **When** se rechaza, **Then** la publicación no
    pasa a `PUBLISHING`, no se crea ningún `PublicationAttempt` en ejecución y no se inicia
    ninguna subida.

---

### User Story 4 - Ver y entender los fallos de una ejecución (Priority: P2)

Como usuario, quiero que si una subida empieza pero no puede completarse, la publicación quede
`FAILED` con un mensaje comprensible que me diga qué ha pasado y qué puedo hacer, y que
AutoPublisher se recupere solo de cortes transitorios sin duplicar el vídeo.

**Why this priority**: las subidas reales fallan por red, cuota o permisos; sin un
tratamiento claro el usuario no sabe si su vídeo está o no en YouTube.

**Independent Test**: con el simulador de YouTube, provocar: corte de red recuperable,
respuesta 5xx recuperable, respuesta de reanudación incompleta, error 4xx definitivo, cuota
agotada, límite de uploads del canal, permisos insuficientes, sesión de subida caducada y
respuesta inesperada; comprobar que los recuperables se completan dentro del mismo intento y
que los demás dejan la publicación `FAILED` con un error específico y comprensible, sin
secretos.

**Acceptance Scenarios**:

1. **Given** una subida en curso, **When** se produce un corte de red o un error temporal de
   YouTube recuperable, **Then** AutoPublisher consulta el estado de la sesión, reanuda desde
   el último byte confirmado por YouTube con espera progresiva limitada y, si lo consigue,
   completa la publicación dentro del **mismo** `PublicationAttempt`.
2. **Given** una subida en curso, **When** YouTube indica que ha recibido solo parte del
   archivo, **Then** AutoPublisher continúa desde el último byte confirmado, sin reenviar ni
   saltarse datos.
3. **Given** fallos transitorios repetidos que agotan la recuperación limitada, **When** se
   agota, **Then** el intento termina como fallido, la publicación queda `FAILED` y el mensaje
   indica un error temporal de red o de YouTube.
4. **Given** una subida en curso, **When** YouTube responde con un error definitivo (cuota
   agotada, límite de uploads del canal, permiso insuficiente, metadata rechazada, otro error
   4xx definitivo, sesión de subida caducada o respuesta inesperada), **Then** no se reintenta,
   el intento termina fallido con un código de error seguro y un mensaje comprensible
   específico, y la publicación queda `FAILED`.
5. **Given** que durante la subida las credenciales dejan de ser válidas de forma definitiva,
   **When** ocurre, **Then** la publicación queda `FAILED` con un error de reconexión requerida
   y la cuenta pasa a `Reconnect required`.
6. **Given** una publicación `FAILED`, **When** el usuario la consulta (detalle o Queue),
   **Then** ve un resumen comprensible del último error y el historial de sus intentos.
7. **Given** cualquier error mostrado o registrado, **When** se inspecciona, **Then** no
   contiene tokens, cabeceras de autorización, URLs de sesión de subida ni respuestas crudas de
   Google con información sensible.

---

### User Story 5 - Evitar ejecuciones duplicadas y resultados ambiguos (Priority: P2)

Como usuario, quiero tener la garantía de que AutoPublisher nunca subirá dos veces el mismo
vídeo por accidente: ni por doble clic, ni por peticiones simultáneas, ni por un reinicio a
mitad de subida.

**Why this priority**: un vídeo duplicado en un canal real es el fallo más visible y dañino
de la aplicación (Constitution, principio V).

**Independent Test**: enviar dos `Publish now` simultáneos para la misma publicación y
comprobar que solo uno inicia una subida; dejar una publicación en `PUBLISHING`, reiniciar el
backend y comprobar que queda `FAILED` como interrumpida, marcada como pendiente de revisión
manual si el resultado es incierto, y que no se vuelve a subir nada automáticamente.

**Acceptance Scenarios**:

1. **Given** una publicación elegible, **When** llegan dos o más solicitudes `Publish now`
   simultáneas (doble clic, dos pestañas o peticiones directas), **Then** como máximo una pasa
   a `PUBLISHING` e inicia una subida; las demás se rechazan con un error de ejecución ya en
   curso. Esta garantía la aplica el backend con respaldo de la persistencia, no solo la
   interfaz.
2. **Given** una publicación `PUBLISHING`, **When** el backend se reinicia, **Then** al
   arrancar detecta el intento en ejecución, lo marca como interrumpido, deja la publicación
   `FAILED` e indica si el resultado remoto pudo determinarse; si no pudo determinarse, indica
   claramente que debe revisarse manualmente en YouTube Studio.
3. **Given** una ejecución interrumpida por reinicio, **When** el backend arranca, **Then**
   NUNCA reanuda ni vuelve a subir el archivo automáticamente.
4. **Given** una publicación `FAILED` cuyo resultado remoto es ambiguo, **When** el usuario la
   consulta, **Then** no se le ofrece un reintento silencioso: cualquier nueva ejecución
   requiere, como mínimo, que el usuario reconozca explícitamente que ha comprobado YouTube.
5. **Given** una publicación `SCHEDULED` con fecha pasada o futura, **When** llega o pasa su
   fecha, **Then** no se ejecuta ni cambia de estado automáticamente.

---

### User Story 6 - Publicar antes de hora una publicación programada (Priority: P2)

Como usuario, quiero poder pulsar `Publish now` sobre una publicación `SCHEDULED`,
sabiendo claramente que se publicará antes de su hora, y que después el futuro scheduler no
la vuelva a ejecutar.

**Why this priority**: es un caso natural del flujo manual y evita que el futuro scheduler
duplique publicaciones ya ejecutadas.

**Independent Test**: con una publicación `SCHEDULED` para mañana, pulsar `Publish now` y
comprobar que la confirmación avisa de que se publica antes de su hora programada; tras el
éxito, comprobar que está `PUBLISHED`, que conserva la fecha programada como información
histórica y que ya no es elegible para ninguna ejecución.

**Acceptance Scenarios**:

1. **Given** una publicación `SCHEDULED`, **When** el usuario pulsa `Publish now`, **Then** la
   confirmación indica explícitamente la fecha programada y que se va a publicar ahora, antes
   de esa hora.
2. **Given** una publicación `SCHEDULED` publicada con éxito, **When** se consulta, **Then**
   está `PUBLISHED`, puede mostrar la fecha programada original como dato histórico y ningún
   proceso la considera pendiente de ejecución.
3. **Given** la subida a YouTube, **When** se envía, **Then** no se usa la programación nativa
   de YouTube: la privacidad solicitada se aplica directamente.

---

### User Story 7 - Ver el estado real de las publicaciones en la Queue (Priority: P3)

Como usuario, quiero que la Queue muestre también las publicaciones en curso, publicadas y
fallidas, con su progreso, su enlace o su error, para tener una visión completa del proyecto.

**Why this priority**: mejora la visibilidad sobre información que ya está disponible en el
detalle de cada publicación.

**Independent Test**: con publicaciones en todos los estados, abrir la Queue del proyecto y
comprobar que cada una muestra su estado, que las `PUBLISHING` muestran progreso, las
`PUBLISHED` un enlace `Open on YouTube` y las `FAILED` un resumen del último error.

**Acceptance Scenarios**:

1. **Given** publicaciones en `UNSCHEDULED`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`, `FAILED`
   y `CANCELLED`, **When** el usuario abre la Queue, **Then** todas aparecen con su estado
   claramente distinguible y un orden estable y sencillo.
2. **Given** una publicación `PUBLISHING` en la Queue, **When** avanza la subida, **Then** su
   progreso se actualiza sin recargar manualmente.
3. **Given** una publicación `PUBLISHED`, **When** se muestra, **Then** incluye `Open on
   YouTube` y, si la privacidad real difiere de la solicitada, una advertencia.
4. **Given** una publicación `FAILED`, **When** se muestra, **Then** incluye un resumen
   comprensible del último error y, si procede, la indicación de revisión manual.

---

### Edge Cases

- **Privacidad real distinta de la solicitada** (p. ej. proyecto API no verificado que
  restringe a `private`): la publicación queda `PUBLISHED`, se guarda y muestra la privacidad
  real devuelta por YouTube con una advertencia; AutoPublisher no intenta cambiarla ni
  saltarse la restricción.
- **YouTube acepta el vídeo pero falla la persistencia local del resultado**: YouTube
  devuelve un video ID válido pero AutoPublisher no consigue guardar el resultado en la base
  de datos local. El vídeo puede existir remotamente, por lo que el resultado local se trata
  como ambiguo y pendiente de revisión manual: nunca se inicia otra subida automáticamente,
  tampoco tras un reinicio (el intento se trata como interrumpido según FR-044/FR-045), y se
  informa al usuario de que debe comprobar YouTube Studio antes de cualquier nueva ejecución.
  No se recurre a almacenamientos alternativos inseguros ni a logs con datos sensibles.
- **YouTube acepta el vídeo pero aún lo está procesando**: la publicación se considera
  `PUBLISHED` en cuanto se obtiene un video ID válido; el estado de procesamiento inicial se
  muestra si está disponible, sin esperar a que termine.
- **Comprobación posterior al upload falla** (la consulta ligera de privacidad/procesamiento
  no responde): la publicación sigue `PUBLISHED` con los datos devueltos por la propia subida;
  el fallo de la comprobación no convierte el resultado en `FAILED`.
- **Respuesta final de YouTube sin video ID válido**: el intento termina fallido como
  respuesta inesperada y se marca como resultado ambiguo que requiere revisión manual.
- **Corte durante el envío del último fragmento**: AutoPublisher consulta el estado de la
  sesión antes de decidir; si YouTube confirma la subida completa con video ID, es éxito; si
  no puede determinarse, el intento queda fallido y ambiguo, nunca se crea una sesión nueva.
- **Sesión de subida caducada o desconocida para YouTube**: el intento termina fallido; no se
  inicia automáticamente una sesión nueva dentro del mismo intento si eso pudiera duplicar el
  vídeo.
- **Archivo eliminado o modificado durante la subida**: el intento termina fallido con error de
  archivo no disponible; si YouTube podría haber recibido el vídeo completo, se marca como
  ambiguo.
- **Edición del contenido global durante o después de la publicación**: los valores enviados a
  YouTube quedan registrados en el intento; editar después la metadata global del `Content`
  no altera lo que se muestra como enviado en una publicación `PUBLISHED`.
- **Desactivar el proyecto o la cuenta durante `PUBLISHING`**: no cancela la subida en curso
  (no existe cancelación de subidas en esta feature); el resultado se registra normalmente.
- **Desconectar o reconectar la cuenta YouTube durante `PUBLISHING`**: se rechaza con un
  mensaje claro mientras haya una ejecución en curso de esa cuenta.
- **Cancelar una publicación `PUBLISHING` o `PUBLISHED`**: no está permitido.
- **Dos publicaciones distintas de la misma cuenta ejecutándose a la vez**: se permite (la
  restricción de una ejecución activa es por publicación); cada una tiene su propio intento.
- **Publicación `SCHEDULED` cuya fecha ya pasó**: es elegible para `Publish now` igual que una
  `UNSCHEDULED`.
- **Configuración OAuth ausente**: `Publish now` se rechaza indicando que la integración con
  YouTube no está configurada.
- **Almacén seguro de credenciales no disponible**: `Publish now` se rechaza en el preflight
  con el error correspondiente de la Feature 005; no se sube nada.
- **Sin conexión a Internet al iniciar**: si no puede contactarse con Google/YouTube para
  validar credenciales o canal, `Publish now` se rechaza sin pasar a `PUBLISHING`.
- **Hashtags sin descripción**: la descripción enviada contiene solo la línea de hashtags,
  sin línea en blanco inicial.
- **Sin hashtags**: la descripción enviada es exactamente la descripción efectiva.
- **Vídeo muy grande**: se sube por streaming desde disco sin cargarlo completo en memoria; el
  consumo de memoria no crece con el tamaño del archivo.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance

- **FR-001**: El sistema DEBE permitir ejecutar manualmente una `Publication` existente cuyo
  destino sea una `Account` YouTube conectada, subiendo realmente su vídeo al canal vinculado
  mediante la API oficial de YouTube.
- **FR-002**: En esta feature, solo las publicaciones de `Content` de tipo vídeo DEBEN poder
  ejecutarse en YouTube; las de tipo imagen DEBEN rechazarse con un mensaje claro.
- **FR-003**: El archivo multimedia existente DEBE reutilizarse tal cual: NO DEBE duplicarse,
  modificarse, transcodificarse, comprimirse ni cargarse completo en memoria, y NO DEBEN
  escribirse copias temporales innecesarias.
- **FR-004**: Ninguna publicación DEBE ejecutarse ni cambiar de estado automáticamente por
  llegar o pasar su fecha programada (se mantiene FR-013 de la Feature 004).

#### Estados de Publication

- **FR-005**: Los estados de `Publication` DEBEN ampliarse con `PUBLISHING`, `PUBLISHED` y
  `FAILED`, manteniendo `UNSCHEDULED`, `SCHEDULED` y `CANCELLED`.
- **FR-006**: Las únicas transiciones introducidas por esta feature DEBEN ser:
  - `UNSCHEDULED`/`SCHEDULED` → `PUBLISHING` (al iniciar una ejecución tras pasar el
    preflight);
  - `FAILED` → `PUBLISHING`, únicamente mediante un reintento manual sujeto a FR-041 (con
    confirmación y preflight completos y, si el último resultado aplicable es ambiguo, la
    confirmación explícita de revisión en YouTube);
  - `PUBLISHING` → `PUBLISHED` (al obtener un video ID válido y persistir el resultado);
  - `PUBLISHING` → `FAILED` (al no poder completar la ejecución o al detectar una ejecución
    interrumpida);
  - `FAILED` → `CANCELLED` (cancelación manual de una publicación fallida).
- **FR-007**: `PUBLISHED` DEBE significar que YouTube aceptó la subida y AutoPublisher obtuvo un
  video ID válido; no implica que YouTube haya terminado de procesar el vídeo ni que sea
  público.
- **FR-008**: Una publicación `PUBLISHED` DEBE conservar su fecha programada original, si la
  tenía, solo como información histórica; NUNCA DEBE volver a ser elegible para ejecución.
- **FR-009**: Para la regla de duplicados de la Feature 004 (FR-008), las publicaciones
  `PUBLISHING` y `FAILED` DEBEN contar como activas para su pareja contenido + cuenta; las
  `PUBLISHED`, igual que las `CANCELLED`, NO DEBEN impedir crear una nueva publicación.

#### Publish now y confirmación

- **FR-010**: La interfaz DEBE ofrecer una acción explícita `Publish now` en las publicaciones
  YouTube elegibles y DEBE ocultarla o deshabilitarla, explicando el motivo, cuando no lo sean.
- **FR-011**: Antes de cualquier efecto externo, el sistema DEBE requerir una confirmación del
  usuario que muestre: título efectivo, canal YouTube real (título y channel ID), privacidad
  solicitada, valor de `Notify subscribers`, contenido/archivo a subir y, si la publicación
  está `SCHEDULED`, su fecha programada indicando que se publicará antes de esa hora.
- **FR-012**: Iniciar una ejecución DEBE devolver una respuesta a la interfaz sin esperar a
  que termine la subida; la interfaz DEBE poder consultar después el estado y progreso.
- **FR-013**: El servicio de ejecución DEBE ser invocable de forma independiente de la
  interfaz, para que un futuro scheduler pueda reutilizarlo.

#### Preflight

- **FR-014**: Antes de cambiar la publicación a `PUBLISHING` o contactar con el endpoint de
  subida, el sistema DEBE validar como mínimo: publicación existente; estado elegible
  (`UNSCHEDULED`, `SCHEDULED`, o `FAILED` únicamente cuando se cumplen las condiciones de
  reintento manual de FR-041, incluida la confirmación de revisión en YouTube cuando el
  último resultado aplicable sea ambiguo); proyecto activo; cuenta activa; plataforma
  YouTube; configuración OAuth disponible; conexión `Connected`; credenciales válidas u
  obtenibles por renovación; channel ID efectivo igual al vinculado; `Content` de tipo vídeo;
  archivo multimedia disponible; metadata válida para YouTube; opciones YouTube completas; y
  ausencia de otra ejecución activa para esa publicación.
- **FR-015**: Si cualquier comprobación del preflight falla, la publicación NO DEBE cambiar de
  estado, NO DEBE crearse ninguna sesión de subida y el usuario DEBE recibir un error
  estructurado que identifique la causa concreta.

#### Verificación del canal

- **FR-016**: Inmediatamente antes de la subida, el sistema DEBE verificar, reutilizando la
  infraestructura de la Feature 005, que las credenciales que se usarán actúan sobre el
  channel ID vinculado a la cuenta.
- **FR-017**: Si el canal efectivo no coincide, el sistema NO DEBE subir nada, DEBE aplicar el
  comportamiento de la Feature 005 (cuenta a `Reconnect required`) e informar al usuario. El
  sistema NUNCA DEBE subir un vídeo a un canal distinto del vinculado.

#### Opciones específicas de YouTube

- **FR-018**: Cada publicación destinada a YouTube DEBE poder tener opciones YouTube
  persistentes asociadas, almacenadas fuera del modelo común de `Publication` (sin campos
  específicos de YouTube en él) y gestionadas por el módulo/adaptador de YouTube.
- **FR-019**: La privacidad DEBE admitir `private`, `unlisted` y `public`, con `private` como
  valor por defecto, y DEBE poder cambiarse antes de publicar.
- **FR-020**: El usuario DEBE declarar explícitamente Made for Kids (Yes / No), que se envía a
  YouTube como la autodeclaración correspondiente del vídeo; el sistema NO DEBE decidirlo
  automáticamente ni asumir un valor por defecto.
- **FR-021**: El usuario DEBE declarar explícitamente si el vídeo contiene contenido sintético
  o alterado realista (Yes / No), que se envía a YouTube como la declaración correspondiente;
  el sistema NO DEBE inferirlo ni asumir un valor por defecto.
- **FR-021a**: El usuario DEBE decidir explícitamente si YouTube notificará la subida a los
  suscriptores del canal (`Notify subscribers`: Yes / No), con `No` como valor seguro por
  defecto. El valor DEBE persistirse junto con las demás opciones YouTube y enviarse siempre
  explícitamente a YouTube como el parámetro de notificación a suscriptores de la subida, de
  modo que nunca se aplique silenciosamente el valor por defecto de YouTube.
- **FR-022**: Las opciones YouTube DEBEN poder editarse mientras la publicación esté
  `UNSCHEDULED` o `SCHEDULED` (con proyecto y cuenta activos) y NO DEBEN poder editarse en
  `PUBLISHING`, `PUBLISHED` ni `CANCELLED`. Su edición en `FAILED` sigue la política de FR-041.

#### Metadata enviada a YouTube

- **FR-023**: El sistema DEBE usar los valores efectivos de título, descripción y hashtags de
  la publicación definidos en la Feature 004.
- **FR-024**: El título efectivo DEBE ser no vacío, tener como máximo 100 caracteres y no
  contener caracteres que YouTube rechace en títulos; el sistema NO DEBE sustituir un título
  ausente por el nombre del archivo ni por ningún otro valor.
- **FR-025**: La descripción enviada DEBE construirse como: descripción efectiva, una línea en
  blanco y los hashtags efectivos en formato `#tag1 #tag2 #tag3`; sin descripción, solo la
  línea de hashtags; sin hashtags, solo la descripción.
- **FR-026**: La descripción final DEBE validarse contra los límites vigentes de YouTube
  (incluido el máximo de 5000 bytes) y contra los caracteres que YouTube rechace.
- **FR-027**: Los hashtags NO DEBEN enviarse como tags internos de YouTube.
- **FR-028**: Todos los errores de metadata DEBEN detectarse antes de crear una sesión de
  subida.

#### Subida resumible

- **FR-029**: La subida DEBE usar el protocolo oficial de subida resumible de YouTube:
  iniciar una sesión, enviar el archivo desde disco por streaming, interpretar correctamente
  las respuestas de subida incompleta, consultar el estado de la sesión tras una interrupción
  y reanudar desde el último byte confirmado por YouTube.
- **FR-030**: Ante fallos transitorios de red o respuestas recuperables de YouTube, el sistema
  DEBE aplicar una recuperación limitada (número de reintentos y espera progresiva acotados)
  dentro de la misma sesión y del mismo `PublicationAttempt`. Esta recuperación NO DEBE
  considerarse un retry de la publicación ni crear nuevos intentos.
- **FR-031**: Ante errores definitivos, el sistema NO DEBE reintentar y DEBE terminar el
  intento como fallido.
- **FR-032**: La URL de la sesión de subida resumible DEBE tratarse como secreta: NO DEBE
  aparecer en logs, en la base de datos, en respuestas al frontend ni en mensajes de error, y
  solo DEBE existir en memoria durante la ejecución.
- **FR-033**: El sistema NO DEBE usar la programación nativa de YouTube (`publishAt`).

#### PublicationAttempt

- **FR-034**: El sistema DEBE introducir una entidad persistente y genérica `PublicationAttempt`
  (reutilizable por el futuro scheduler y otras plataformas, sin lógica específica de YouTube
  en el núcleo común) que registre como mínimo: identificador; publicación; inicio;
  finalización; estado del intento; bytes enviados; tamaño total; progreso; código de error
  seguro; mensaje de error comprensible; identificador externo y URL externa cuando existan;
  e indicador de si el resultado final pudo determinarse inequívocamente.
- **FR-035**: Cada ejecución iniciada DEBE crear exactamente un `PublicationAttempt`; las
  reanudaciones dentro de la misma ejecución NO DEBEN crear intentos nuevos.
- **FR-036**: El intento DEBE registrar de forma no sensible los valores enviados a la
  plataforma (al menos título, descripción final, privacidad solicitada y valor de
  `Notify subscribers` solicitado) para que el historial refleje lo que realmente se envió.
- **FR-037**: `PublicationAttempt` NO DEBE almacenar access tokens, refresh tokens, cabeceras
  de autorización, URLs de sesión de subida ni respuestas completas de Google.
- **FR-038**: Una publicación DEBE tener como máximo un intento en ejecución en cada momento,
  garantizado por el backend con respaldo de la capa de persistencia ante solicitudes
  concurrentes.

#### Resultado remoto

- **FR-039**: Tras una subida exitosa, el sistema DEBE persistir como mínimo: video ID de
  YouTube, URL directa al vídeo, fecha de publicación/subida y privacidad realmente devuelta
  por YouTube. La ubicación exacta de cada dato entre `Publication`, `PublicationAttempt` y
  las opciones YouTube se decidirá en el plan, priorizando un modelo reutilizable.
- **FR-040**: Tras el éxito, el sistema PUEDE realizar una comprobación ligera para obtener la
  privacidad real y el estado inicial de procesamiento; su fallo NO DEBE cambiar el resultado
  `PUBLISHED`. Si la privacidad real difiere de la solicitada, la interfaz DEBE mostrar el
  valor real con una advertencia.
- **FR-040a**: El sistema DEBE intentar persistir el video ID y el resultado remoto
  inmediatamente después de recibirlos de YouTube. Si esa persistencia falla, el sistema DEBE
  considerar que el vídeo puede existir remotamente y tratar el resultado como ambiguo y
  pendiente de revisión manual: NUNCA DEBE iniciar automáticamente otra subida (tampoco tras
  un reinicio, donde aplican FR-044 y FR-045) y DEBE informar al usuario de que compruebe
  YouTube Studio antes de cualquier nueva ejecución. NO DEBE recurrir a almacenamientos
  alternativos inseguros ni registrar en logs datos sensibles para resolver este caso.

#### Fallos y reintento manual

- **FR-041**: Una publicación `FAILED` DEBE mostrar su último error y el historial de sus
  intentos. El sistema NO DEBE implementar retries automáticos entre intentos. La política
  exacta para volver a ejecutar manualmente una publicación `FAILED` se decidirá en el plan
  con estas restricciones obligatorias: si el resultado del último intento es ambiguo, NUNCA
  DEBE ofrecerse un reintento silencioso, y cualquier nueva ejecución DEBE requerir que el
  usuario reconozca explícitamente que ha verificado en YouTube que el vídeo no se publicó;
  toda nueva ejecución DEBE pasar de nuevo por confirmación y preflight y crear un intento
  nuevo.
- **FR-042**: Los errores de ejecución DEBEN distinguir, con códigos seguros y mensajes
  comprensibles, al menos: reconexión requerida, archivo no disponible, metadata inválida,
  permiso insuficiente, cuota de API agotada, límite de uploads del canal, error permanente
  de YouTube, error temporal de YouTube, error de red, sesión de subida caducada, respuesta
  inesperada y ejecución interrumpida por reinicio.
- **FR-043**: Ningún error mostrado o registrado DEBE incluir respuestas crudas de Google que
  puedan contener información sensible.

#### Reinicio durante PUBLISHING

- **FR-044**: Al arrancar, el backend DEBE detectar los intentos que quedaron en ejecución,
  marcarlos como interrumpidos y fallidos, dejar sus publicaciones en `FAILED` e indicar si el
  resultado remoto pudo determinarse; si no pudo, DEBE indicar que requiere revisión manual.
- **FR-045**: El sistema NUNCA DEBE reanudar ni reiniciar automáticamente una subida
  interrumpida por reinicio ni volver a subir un archivo tras un resultado ambiguo.

#### Edición y acciones según estado

- **FR-046**: En `PUBLISHING`, el sistema NO DEBE permitir cambiar contenido, cuenta, fecha,
  metadata ni opciones YouTube, ni cancelar, ni lanzar otra ejecución.
- **FR-047**: Una publicación `PUBLISHED` DEBE ser un registro histórico: NO DEBE permitirse
  editar su fecha, overrides de metadata ni opciones YouTube, ni cancelarla. La edición y el
  borrado remotos quedan fuera de alcance.
- **FR-048**: Mientras una cuenta tenga alguna publicación en `PUBLISHING`, el sistema DEBE
  rechazar su desconexión y su reconexión con un mensaje claro.

#### Queue e interfaz

- **FR-049**: La Queue DEBE mostrar también las publicaciones `PUBLISHING` (con progreso),
  `PUBLISHED` (con `Open on YouTube` y advertencia de privacidad si procede) y `FAILED` (con
  resumen comprensible del último error e indicación de revisión manual si procede),
  manteniendo los estados anteriores, con un orden estable y sencillo que se definirá en el
  plan.
- **FR-050**: El detalle de publicación DEBE mostrar, según el estado: opciones YouTube,
  `Publish now`, progreso, resultado (video ID, enlace, privacidad real, estado de
  procesamiento si existe) o error, y el historial de intentos.
- **FR-051**: La interfaz DEBE impedir lanzar una segunda ejecución mientras otra esté en
  curso o pendiente de respuesta (además de la garantía del backend de FR-038).

#### Seguridad

- **FR-052**: Se DEBEN mantener todas las garantías de seguridad de la Feature 005. Además,
  NUNCA DEBEN registrarse en logs ni enviarse al frontend cabeceras de autorización, tokens ni
  URLs de sesión de subida.

#### Persistencia, API y errores

- **FR-053**: Los nuevos estados, intentos, opciones YouTube y resultados DEBEN persistir en la
  base de datos local mediante el mecanismo versionado de migraciones existente, sin perder
  datos previos.
- **FR-054**: La API DEBE permitir: consultar y editar las opciones YouTube de una
  publicación; iniciar una ejecución; consultar estado, progreso y resultado; y consultar el
  historial de intentos. Todos los errores DEBEN seguir el formato estructurado existente.

#### Documentación y calidad

- **FR-055**: La documentación (README y `quickstart.md`) DEBE explicar: la publicación
  manual; que los proyectos API no verificados pueden ver sus subidas restringidas a `private`
  y que hacerlas públicas puede requerir la auditoría de YouTube; y el coste de cuota vigente
  de la subida según la documentación oficial en el momento de implementar, sin codificarlo
  como constante de negocio.
- **FR-056**: Los tests automatizados NO DEBEN subir vídeos reales ni depender de Internet;
  DEBEN usar un simulador de YouTube que cubra, como mínimo, los escenarios listados en la
  sección de tests de la descripción de la feature (éxito, sesión resumible, streaming,
  progreso, subida incompleta y reanudación, corte de red recuperado, 4xx definitivo, 5xx
  recuperable, cuota/límite de uploads, reconexión requerida, canal inesperado, privacidad
  distinta, concurrencia, reinicio en `PUBLISHING`, ausencia de secretos, persistencia de
  intentos, estados, Queue, validación de metadata, hashtags, Made for Kids, synthetic media,
  proyecto/cuenta inactivos, archivo inexistente y contenido imagen).
- **FR-057**: `quickstart.md` DEBE incluir una prueba manual contra YouTube real con un vídeo
  pequeño en `private`, verificando channel ID, aparición real en YouTube, video ID y URL
  guardados, archivo local intacto, ausencia de secretos, persistencia tras reinicio y
  apertura mediante `Open on YouTube`; el borrado del vídeo de prueba se hace manualmente en
  YouTube Studio.

### Key Entities *(include if feature involves data)*

- **Publication** (existente, Feature 004): amplía sus estados con `PUBLISHING`, `PUBLISHED` y
  `FAILED`. Sigue siendo común a todas las plataformas, sin campos específicos de YouTube.
  Puede conservar su fecha programada como dato histórico tras publicarse y referencia (o
  permite derivar) su resultado remoto.
- **PublicationAttempt** (nueva, genérica): una ejecución real de una publicación. Pertenece a
  una publicación (que puede tener varios a lo largo del tiempo, como máximo uno en
  ejecución). Registra inicio, fin, estado del intento, bytes enviados, tamaño total,
  progreso, código y mensaje de error seguros, identificador y URL externos, indicador de
  resultado determinado/ambiguo y los valores no sensibles enviados. Nunca contiene secretos
  ni URLs de sesión.
- **Opciones YouTube de una publicación** (nueva, específica de YouTube): privacidad
  solicitada (por defecto `private`), Made for Kids (sin declarar / sí / no), synthetic media
  (sin declarar / sí / no) y `Notify subscribers` (por defecto `No`). Pertenece al módulo
  YouTube; como máximo una por publicación.
- **Resultado remoto**: video ID, URL directa, fecha de subida, privacidad real devuelta y, si
  está disponible, estado inicial de procesamiento. Su ubicación exacta se decide en el plan.
- **Sesión de subida resumible** (efímera, no persistida): URL de sesión y último byte
  confirmado; vive solo en memoria durante la ejecución.
- **YouTube Connection, credenciales** (existentes, Feature 005): se reutilizan para obtener
  credenciales válidas y verificar el canal.
- **Content** (existente, Feature 003): su tipo determina la elegibilidad; su archivo se lee
  sin modificarse.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real de `quickstart.md` (abrir una
  publicación YouTube de un vídeo → configurar `private`, Made for Kids y synthetic media →
  `Publish now` → confirmar → ver `Publishing` y progreso → ver `Published` con video ID →
  abrir el vídeo → reiniciar → resultado intacto) sin editar archivos ni bases de datos a
  mano.
- **SC-002**: Tras confirmar `Publish now`, la interfaz muestra el estado `Publishing` en
  menos de 2 segundos (excluyendo la validación de credenciales con Google en condiciones
  normales de red) y el progreso visible se actualiza al menos cada 5 segundos mientras la
  subida avanza.
- **SC-003**: 0 subidas iniciadas cuando falla cualquier comprobación del preflight (100 % de
  los casos de preflight rechazados sin contactar con el endpoint de subida).
- **SC-004**: Ante cualquier número de solicitudes `Publish now` simultáneas para la misma
  publicación, se inicia como máximo 1 subida.
- **SC-005**: 0 subidas automáticas tras un reinicio o un resultado ambiguo; el 100 % de las
  ejecuciones interrumpidas por reinicio quedan `FAILED` con indicación clara.
- **SC-006**: 0 vídeos subidos a un canal distinto del vinculado.
- **SC-007**: En el 100 % de las ejecuciones, la base de datos, los logs y las respuestas al
  frontend contienen 0 tokens, cabeceras de autorización y URLs de sesión de subida
  (verificado por tests automáticos y por inspección manual en el quickstart).
- **SC-008**: El 100 % de las publicaciones `PUBLISHED` conservan tras un reinicio su video
  ID, URL, privacidad real e intento.
- **SC-009**: El archivo multimedia local es idéntico byte a byte antes y después de publicar,
  y el consumo de memoria durante la subida no crece proporcionalmente al tamaño del vídeo.
- **SC-010**: Un corte de red transitorio durante la subida se recupera dentro del mismo
  intento sin intervención del usuario y sin duplicar el vídeo.
- **SC-011**: Cada tipo de error de FR-042 produce un mensaje que indica qué ha pasado y qué
  puede hacer el usuario.
- **SC-012**: 0 publicaciones programadas se ejecutan automáticamente al llegar su hora.
- **SC-013**: La suite de tests automatizados se ejecuta completa sin Internet ni YouTube real
  y todos los quality gates existentes pasan.

## Assumptions

- **Alcance**: quedan fuera el scheduler automático, la ejecución al llegar `scheduled_at`,
  los retries entre intentos, otras plataformas, imágenes en YouTube, `publishAt`, edición y
  borrado remotos, thumbnails, playlists, comentarios, analytics, categorías configurables,
  `snippet.tags`, monetización, subtítulos, música, transcodificación, compresión, generación
  de metadata con IA y la cancelación por el usuario de una subida en curso.
- **Decisiones diferidas al plan**: modelo exacto y estados internos de `PublicationAttempt`;
  ubicación de los datos del resultado remoto; mecanismo de ejecución en segundo plano y de
  consulta de progreso; librería o implementación del protocolo resumible; tamaño de
  fragmento, número de reintentos y política de espera; política exacta de reintento manual
  de `FAILED` (dentro de FR-041); orden y agrupación de la Queue; categoría de YouTube por
  defecto requerida por la API; y lista exacta de caracteres no válidos en metadata, que se
  verificará contra la documentación oficial vigente.
- **Made for Kids y synthetic media sin valor por defecto**: se requieren declaraciones
  explícitas para evitar publicar con una declaración que el usuario no haya tomado; el
  preflight las exige.
- **Opciones YouTube creadas bajo demanda**: las publicaciones YouTube existentes antes de
  esta feature se comportan como si tuvieran privacidad `private` y declaraciones sin
  responder.
- **Duplicados**: `PUBLISHING` y `FAILED` cuentan como activas para la regla de duplicados de
  la Feature 004, para que no puedan existir en paralelo dos intenciones pendientes para el
  mismo vídeo y cuenta; `PUBLISHED` no bloquea, ya que crear otra publicación es una decisión
  explícita del usuario.
- **Instantánea de lo enviado**: los valores enviados se registran en el intento, de modo que
  una publicación `PUBLISHED` muestra lo que realmente se subió aunque la metadata global del
  contenido cambie después.
- **Un único usuario local**: la concurrencia relevante es la de varias pestañas o peticiones
  del mismo usuario; dos publicaciones distintas pueden ejecutarse en paralelo.
- **Proyecto API de Google**: el proyecto del usuario puede estar sin verificar; en ese caso
  las subidas pueden quedar `private`, y AutoPublisher lo muestra sin intentar evitarlo.
- **Dependencias**: reutiliza `Project`, `Account` (Feature 002), `Content` y su archivo
  (Feature 003), `Publication`, metadata efectiva y Queue (Feature 004), conexión, credenciales,
  renovación y verificación de canal de YouTube (Feature 005), el formato estructurado de
  errores y el sistema de migraciones existentes.
