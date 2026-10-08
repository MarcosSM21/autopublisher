# Feature Specification: Scheduler y ejecución automática de publicaciones programadas

**Feature Branch**: `007-scheduler-automatic-execution`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "Crear la Feature 007 de AutoPublisher: Scheduler & Automatic Execution. Convertir las `Publication` programadas en ejecuciones automáticas reales mediante un scheduler local que vive dentro del backend, detecta publicaciones `SCHEDULED` vencidas y armadas (`auto_publish_enabled`) dentro de una ventana segura de 10 minutos y ejecuta el mismo servicio genérico `start_publication` de la Feature 006, sin conocer detalles de YouTube. Incluye consentimiento explícito (las publicaciones programadas preexistentes NO quedan armadas), `Pause automation` global persistente, orden de arranque seguro tras la recuperación de ejecuciones interrumpidas, protección frente a duplicados respaldada por persistencia, concurrencia limitada, preflight reutilizado sin efectos externos cuando falla, origen del intento (`manual` / `scheduled`), condición derivada overdue sin nuevo estado y Queue ampliada. Sin retries automáticos entre intentos, sin cron/systemd/cloud, sin Calendar, sin otras plataformas."

## Contexto

Hasta ahora una `Publication` (Feature 004) puede tener una fecha programada (`scheduled_at`),
pero llegar a esa fecha no provoca ninguna acción. La Feature 006 introdujo la primera
ejecución real (`Publish now`) a través de un servicio genérico de publicación, un registro de
publishers por plataforma (hoy solo YouTube), el preflight completo, `PublicationAttempt`, las
garantías frente a ejecuciones concurrentes y la recuperación de ejecuciones interrumpidas al
arrancar. La Feature 006 prohibía explícitamente la ejecución automática por fecha (su FR-004
y SC-012).

Esta feature **sustituye esa prohibición** de forma controlada: añade un scheduler local que,
mientras el backend de AutoPublisher está en ejecución, detecta las publicaciones programadas
que el usuario ha **armado explícitamente** para publicación automática y, cuando llega su
hora, invoca exactamente el mismo servicio genérico que usa `Publish now`.

Flujo de referencia:

`SCHEDULED` (armada) → llega `scheduled_at` → scheduler local → servicio genérico de
publicación → `PUBLISHING` → `PUBLISHED` / `FAILED`

Principios rectores de esta feature:

- **Nunca automatizar sin consentimiento explícito**: solo se ejecutan automáticamente las
  publicaciones que el usuario ha armado de forma explícita; actualizar AutoPublisher nunca
  arma publicaciones existentes.
- **Nunca publicar muy tarde**: si AutoPublisher no estaba en marcha a la hora indicada, solo
  se recupera una ventana corta de 10 minutos; después, decide el usuario.
- **Nunca duplicar**: como máximo una ejecución por publicación, también frente a ticks
  concurrentes y a `Publish now`.
- **Una sola lógica de publicación**: el scheduler no publica ni valida por su cuenta; solo
  decide *cuándo* llamar al servicio genérico existente, sin conocer ninguna plataforma.
- **Solo local**: sin backend en ejecución no hay automatización.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicación automática a la hora programada (Priority: P1)

Como usuario, quiero programar una publicación, habilitar explícitamente su publicación
automática, dejar AutoPublisher funcionando y que, sin hacer nada más, el vídeo se publique
cuando llegue la hora indicada.

**Why this priority**: es el objetivo principal de la feature y del producto: programar y
olvidarse. Todo lo demás protege este flujo.

**Independent Test**: con reloj simulado y publisher simulado (sin Internet), crear una
publicación `SCHEDULED` armada para dentro de 5 minutos, avanzar el reloj hasta antes de la
hora y comprobar que nada ocurre; avanzar hasta la hora y comprobar que el scheduler inicia la
ejecución mediante el servicio genérico, que la publicación pasa a `PUBLISHING` y termina
`PUBLISHED`, y que su único `PublicationAttempt` indica origen `scheduled`.

**Acceptance Scenarios**:

1. **Given** una publicación `SCHEDULED` armada, válida y con fecha futura, **When** el reloj
   aún no ha llegado a `scheduled_at`, **Then** la publicación permanece `SCHEDULED` y el
   scheduler no la inicia ni ejecuta su preflight.
2. **Given** esa publicación, **When** llega `scheduled_at` con el backend en ejecución y la
   automatización no pausada, **Then** el scheduler la detecta e inicia su ejecución en un
   plazo máximo de 60 segundos en condiciones normales.
3. **Given** que el scheduler inicia la ejecución, **When** se crea el intento, **Then** se
   hace a través del mismo servicio genérico de la Feature 006 (preflight completo incluido),
   el intento queda registrado con origen `scheduled` y la publicación pasa a `PUBLISHING`.
4. **Given** una ejecución iniciada por el scheduler, **When** termina, **Then** el resultado
   (`PUBLISHED` o `FAILED`), los datos remotos y el progreso siguen exactamente las reglas de
   la Feature 006.
5. **Given** una publicación iniciada por el scheduler, **When** el usuario tiene abierta la
   Queue o el detalle, **Then** ve el cambio a `Publishing`, el progreso y el resultado sin
   recargar manualmente.
6. **Given** el historial de intentos de una publicación, **When** se consulta, **Then** cada
   intento indica `Started by scheduler` o `Started manually` según su origen.

---

### User Story 2 - Consentimiento explícito para la publicación automática (Priority: P1)

Como usuario, quiero que AutoPublisher solo publique automáticamente las publicaciones que yo
he armado explícitamente, y que al actualizar la aplicación ninguna publicación programada
antigua empiece a publicarse por sorpresa.

**Why this priority**: las publicaciones programadas existentes se crearon cuando la fecha no
tenía efectos reales; armarlas implícitamente podría publicar contenido no deseado en canales
reales. Es una salvaguarda imprescindible del flujo P1.

**Independent Test**: partir de una base de datos con publicaciones `SCHEDULED` creadas antes
de esta feature, aplicar la migración y comprobar que todas quedan desarmadas, que ninguna se
ejecuta al llegar su hora y que la migración no contacta con ninguna plataforma; después
armar una explícitamente y comprobar que solo esa se ejecuta.

**Acceptance Scenarios**:

1. **Given** publicaciones `SCHEDULED` existentes antes de esta feature, **When** se aplica la
   migración, **Then** todas quedan con la publicación automática deshabilitada y la migración
   no inicia ejecuciones ni contacta con ninguna plataforma.
2. **Given** una publicación `SCHEDULED` desarmada, **When** llega y pasa su hora, **Then**
   nunca se ejecuta automáticamente y permanece `SCHEDULED`.
3. **Given** que el usuario programa una publicación (al crearla o al asignar o cambiar su
   fecha), **When** guarda la programación, **Then** la interfaz deja inequívocamente claro si
   AutoPublisher publicará automáticamente al llegar la hora: la acción que arma la
   publicación se presenta como `Schedule & enable auto-publish` (o una confirmación
   equivalente) y la opción de guardar sin armar está igualmente disponible.
4. **Given** una publicación `SCHEDULED` desarmada con fecha futura, **When** el usuario
   habilita explícitamente `Enable auto-publish`, **Then** queda armada y se ejecutará al
   llegar su hora.
5. **Given** una publicación `SCHEDULED` armada, **When** el usuario deshabilita la publicación
   automática, **Then** queda desarmada y no se ejecutará automáticamente.
6. **Given** una publicación armada, **When** el usuario la cancela y después la reactiva,
   **Then** la publicación reactivada queda desarmada y el usuario debe armarla de nuevo
   explícitamente.
7. **Given** una publicación armada, **When** el usuario elimina su fecha y pasa a
   `UNSCHEDULED`, **Then** queda desarmada y nunca se ejecutará automáticamente.

---

### User Story 3 - Ventana segura tras apagados y reinicios (Priority: P1)

Como usuario, quiero que, si mi ordenador estaba apagado, suspendido o con AutoPublisher
cerrado a la hora programada, la publicación solo se ejecute automáticamente si vuelve a
arrancar poco después (10 minutos), y que en caso contrario quede visible como perdida para
que yo decida.

**Why this priority**: AutoPublisher es local; sin esta ventana, encender el ordenador por la
mañana podría publicar de golpe contenido programado para la noche anterior.

**Independent Test**: con reloj simulado, para una publicación armada a las 18:00, arrancar el
backend a las 17:55, 18:03, 18:09, exactamente 18:10 y 18:11, y comprobar que se ejecuta
automáticamente en los cuatro primeros casos (a su hora en el primero) y no en el último, donde
queda `SCHEDULED` y mostrada como overdue.

**Acceptance Scenarios**:

1. **Given** una publicación armada, **When** `scheduled_at <= ahora <= scheduled_at + 10
   minutos` (ambos límites incluidos), **Then** es elegible para ejecución automática.
2. **Given** una publicación armada programada a las 18:00, **When** el backend arranca a las
   18:03 o a las 18:09, **Then** el scheduler puede ejecutarla automáticamente.
3. **Given** la misma publicación, **When** el backend arranca a las 18:11, **Then** no se
   ejecuta automáticamente, permanece `SCHEDULED` y se muestra como overdue con el mensaje
   `Missed automatic publishing window` y la indicación `Publish now or reschedule`.
4. **Given** una publicación overdue, **When** el usuario pulsa `Publish now`, **Then** se
   aplica el flujo manual de la Feature 006 (confirmación incluida) y el intento queda con
   origen `manual`.
5. **Given** una publicación overdue, **When** el usuario la reprograma a una fecha futura,
   **Then** deja de estar overdue y la ventana se calcula desde la nueva fecha, aplicando las
   reglas de consentimiento de la User Story 2.
6. **Given** una publicación overdue, **When** el usuario deshabilita explícitamente su
   publicación automática, **Then** deja inmediatamente de considerarse overdue y se muestra
   como programada con `Auto-publish disabled`.
7. **Given** una publicación `SCHEDULED` desarmada cuya fecha ya pasó, **When** se consulta,
   **Then** NO se considera overdue ni muestra `Missed automatic publishing window` (nunca se
   esperaba que AutoPublisher la ejecutase); se muestra como programada con
   `Auto-publish disabled` y puede publicarse con `Publish now` o reprogramarse.
8. **Given** que el backend se reinicia antes de `scheduled_at`, **When** vuelve a arrancar,
   **Then** la programación y su estado armado siguen intactos y se ejecuta normalmente al
   llegar la hora.
9. **Given** una ejecución que había quedado `PUBLISHING` al apagarse, **When** el backend
   arranca, **Then** primero se completa la recuperación de ejecuciones interrumpidas de la
   Feature 006 y solo después empieza a trabajar el scheduler.

---

### User Story 4 - Pausar y reanudar la automatización (Priority: P2)

Como usuario, quiero un interruptor global `Pause automation` / `Resume automation` que
detenga todas las nuevas ejecuciones automáticas, persista tras reinicios y no afecte a las
subidas en curso ni a `Publish now`.

**Why this priority**: es el "freno de emergencia" del usuario (p. ej. antes de revisar
contenido o al detectar un problema con una cuenta) y complementa el consentimiento por
publicación.

**Independent Test**: pausar la automatización, avanzar el reloj más allá de la hora de una
publicación armada y comprobar que no se inicia ni se contacta con ninguna plataforma;
reiniciar el backend y comprobar que sigue pausada; reanudar dentro de la ventana y comprobar
que se ejecuta; repetir reanudando fuera de la ventana y comprobar que queda overdue.

**Acceptance Scenarios**:

1. **Given** la automatización en marcha, **When** el usuario pulsa `Pause automation`,
   **Then** el scheduler deja de iniciar nuevas ejecuciones automáticas y no ejecuta preflights
   que puedan contactar con plataformas.
2. **Given** la automatización pausada, **When** se reinicia el backend, **Then** sigue
   pausada.
3. **Given** la automatización pausada y una publicación `PUBLISHING`, **When** se pausa,
   **Then** la subida en curso continúa normalmente hasta su resultado.
4. **Given** la automatización pausada, **When** el usuario pulsa `Publish now` sobre una
   publicación elegible, **Then** la ejecución manual funciona con normalidad.
5. **Given** una publicación armada cuya hora llegó durante la pausa, **When** el usuario
   reanuda dentro de su ventana de 10 minutos, **Then** puede ejecutarse automáticamente.
6. **Given** una publicación armada cuya ventana terminó durante la pausa, **When** el usuario
   reanuda, **Then** no se ejecuta y queda overdue; reanudar nunca ejecuta en bloque
   publicaciones antiguas.
7. **Given** la interfaz, **When** el usuario la consulta, **Then** ve claramente si la
   automatización está en marcha o pausada (y, opcionalmente, la hora de la última comprobación
   correcta del scheduler) y tiene una acción clara para pausar o reanudar.

---

### User Story 5 - Ninguna ejecución duplicada (Priority: P2)

Como usuario, quiero la garantía de que una publicación nunca se sube dos veces aunque el
scheduler la detecte en varios ciclos, aunque coincidan dos ciclos o aunque yo pulse
`Publish now` justo cuando el scheduler la inicia.

**Why this priority**: un vídeo duplicado en un canal real es el fallo más grave de la
aplicación (Constitution, principio V).

**Independent Test**: con publisher simulado, lanzar simultáneamente dos ciclos del scheduler
y una solicitud `Publish now` sobre la misma publicación armada y vencida, y comprobar que
existe exactamente un `PublicationAttempt` y una sola subida simulada.

**Acceptance Scenarios**:

1. **Given** una publicación vencida y armada, **When** el scheduler la detecta en ciclos
   consecutivos, **Then** como máximo se inicia una ejecución.
2. **Given** dos ciclos del scheduler concurrentes (o dos instancias internas del worker),
   **When** ambos intentan iniciar la misma publicación, **Then** como máximo uno lo consigue;
   la garantía la aplica el backend con respaldo de la persistencia, no solo la memoria.
3. **Given** el scheduler y un `Publish now` compitiendo por la misma publicación, **When**
   ambos intentan iniciarla, **Then** solo una ejecución comienza y la otra se rechaza o se
   descarta sin efectos externos.
4. **Given** una publicación ya `PUBLISHING`, `PUBLISHED`, `FAILED` o `CANCELLED`, **When** el
   scheduler la evalúa, **Then** nunca la inicia.

---

### User Story 6 - Fallos de preflight a la hora programada (Priority: P2)

Como usuario, quiero que si al llegar la hora una publicación no puede iniciarse (cuenta que
requiere reconexión, archivo ausente, metadata inválida, proyecto inactivo…), no se suba nada,
permanezca programada y yo pueda ver por qué no se publicó automáticamente.

**Why this priority**: sin esta visibilidad el usuario descubriría tarde que su publicación no
salió; y un preflight fallido nunca debe producir efectos externos ni intentos fantasma.

**Independent Test**: para cada causa de preflight (proyecto inactivo, cuenta inactiva,
conexión que requiere reconexión, archivo ausente, metadata inválida, opciones incompletas,
publisher no disponible, error temporal de red), dejar vencer una publicación armada y
comprobar que no pasa a `PUBLISHING`, que no se inicia subida ni sesión, que se muestra un
motivo seguro y comprensible, que las re-comprobaciones dentro de la ventana están limitadas y
que al terminar la ventana el scheduler deja de intentarlo.

**Acceptance Scenarios**:

1. **Given** una publicación armada vencida cuyo preflight falla, **When** el scheduler intenta
   iniciarla, **Then** permanece `SCHEDULED`, no se crea subida ni sesión de subida y no se crea
   un `PublicationAttempt` en los casos en que la Feature 006 tampoco lo crea para ese mismo
   fallo de preflight.
2. **Given** ese fallo, **When** el usuario consulta la publicación (detalle o Queue),
   **Then** ve un resumen seguro y comprensible de por qué no pudo iniciarse automáticamente,
   sin secretos ni respuestas crudas de la plataforma.
3. **Given** un fallo de preflight dentro de la ventana, **When** pasa el tiempo, **Then** el
   scheduler puede volver a comprobar la publicación con una frecuencia limitada (sin bucles
   agresivos ni contactos repetidos innecesarios con la plataforma) y, si el problema se ha
   resuelto dentro de la ventana, iniciarla.
4. **Given** un fallo de preflight persistente, **When** termina la ventana de 10 minutos,
   **Then** el scheduler deja de intentarlo y la publicación queda overdue, conservando el
   último motivo de fallo automático.
5. **Given** una publicación con un fallo automático registrado, **When** el usuario la
   reprograma, la publica manualmente con éxito o la desarma, **Then** el motivo anterior deja
   de mostrarse como vigente.

---

### User Story 7 - Varias publicaciones vencen a la vez (Priority: P3)

Como usuario, quiero poder programar varias publicaciones a la misma hora (o que varias venzan
mientras el backend estaba cerrado) y que se procesen de forma ordenada, sin saturar el
ordenador ni perder o duplicar ninguna.

**Why this priority**: es un caso real (campañas en varias cuentas) pero menos frecuente que
el flujo individual.

**Independent Test**: con reloj simulado y publisher simulado, armar varias publicaciones con
la misma hora y otras con horas cercanas, llegar a esa hora y comprobar el orden de inicio,
que nunca se supera el límite de ejecuciones automáticas simultáneas, que todas las que siguen
dentro de su ventana al llegar su turno se inician exactamente una vez y que ninguna se pierde
silenciosamente.

**Acceptance Scenarios**:

1. **Given** varias publicaciones armadas vencidas, **When** el scheduler las procesa,
   **Then** las inicia en orden determinista: primero la de `scheduled_at` más antiguo, con un
   desempate estable.
2. **Given** más publicaciones vencidas que el límite de ejecuciones automáticas simultáneas,
   **When** el scheduler las procesa, **Then** nunca hay más ejecuciones automáticas
   simultáneas que el límite; las restantes esperan a ciclos posteriores sin duplicarse.
3. **Given** una publicación que espera capacidad, **When** llega su turno, **Then** se vuelve
   a evaluar su elegibilidad en ese momento: si sigue dentro de su ventana se inicia; si su
   ventana ya terminó, no se inicia y queda overdue de forma visible (nunca se pierde en
   silencio).

---

### User Story 8 - Ver el estado de la automatización en la Queue (Priority: P3)

Como usuario, quiero que la Queue me diga, para cada publicación programada, cuándo está
programada, si se publicará sola, si está esperando su hora, si perdió la ventana automática o
si la automatización global está pausada.

**Why this priority**: mejora la confianza y la visibilidad sobre información disponible en el
detalle de cada publicación; no es imprescindible para que la automatización funcione.

**Independent Test**: con publicaciones `SCHEDULED` armadas y desarmadas, futuras, dentro de la
ventana, armadas overdue y desarmadas con fecha pasada, con la automatización en marcha y
pausada, abrir la Queue y comprobar que cada una muestra la fecha y la indicación correcta, y
que al iniciar el scheduler una publicación la Queue se actualiza sola.

**Acceptance Scenarios**:

1. **Given** una publicación `SCHEDULED`, **When** aparece en la Queue, **Then** muestra su
   fecha programada en la hora local del usuario y si la publicación automática está
   habilitada (`Auto-publish enabled`) o no.
2. **Given** una publicación armada futura con la automatización en marcha, **When** se
   muestra, **Then** indica que está esperando su hora.
3. **Given** la automatización pausada, **When** se muestran publicaciones armadas, **Then**
   indican `Automation paused`.
4. **Given** una publicación armada que perdió su ventana automática (overdue), **When** se
   muestra, **Then** indica `Missed automatic publishing window` y `Publish now or
   reschedule`.
5. **Given** una publicación desarmada cuya fecha ya pasó, **When** se muestra, **Then** NO
   indica `Missed automatic publishing window`; aparece como programada con
   `Auto-publish disabled`, con `Publish now` y la opción de reprogramar disponibles.
6. **Given** la Queue abierta, **When** el scheduler inicia una publicación, **Then** la Queue
   refleja el cambio sin recarga manual.
7. **Given** la interfaz, **When** se muestra la información de automatización, **Then** deja
   claro que AutoPublisher debe estar en ejecución para publicar automáticamente.

---

### Edge Cases

- **Límite exacto de la ventana**: con `scheduled_at` = 18:00:00, a las 18:10:00 exactas la
  publicación sigue siendo elegible; un instante después ya no.
- **Exactamente a la hora**: a las 18:00:00 exactas la publicación es elegible.
- **Fecha introducida en hora local y cambios de horario (DST)**: las fechas se guardan y
  comparan en UTC; un cambio de horario local no adelanta, retrasa ni duplica ninguna
  ejecución ni altera la ventana de 10 minutos.
- **Reloj del sistema ajustado hacia atrás o hacia delante**: las decisiones se toman con la
  hora UTC actual en cada ciclo; un salto hacia delante que deja una publicación fuera de su
  ventana la convierte en overdue en lugar de ejecutarla tarde.
- **Publicación armada con fecha ya pasada**: no puede armarse una publicación cuya fecha no
  sea futura en el momento de armarla (coherente con la regla de la Feature 004 de no asignar
  fechas pasadas); una publicación con fecha pasada se publica con `Publish now` o se
  reprograma.
- **Publicación desarmada con fecha pasada**: no es overdue ni muestra `Missed automatic
  publishing window`; se muestra como programada con `Auto-publish disabled` y puede
  publicarse con `Publish now` o reprogramarse.
- **Desarmar una publicación overdue**: deja de ser overdue inmediatamente. Para volver a
  armarla debe reprogramarse a una fecha futura; la nueva ventana se calcula desde esa fecha.
- **Cambio de fecha mientras está armada**: el scheduler usa exclusivamente la nueva fecha; la
  pantalla de edición de la programación muestra el control de publicación automática con su
  valor actual, de modo que guardar con él habilitado es una decisión explícita.
- **Edición de metadata u opciones de una publicación armada**: se permite mientras esté
  `SCHEDULED`; el preflight al llegar la hora usa los valores vigentes en ese momento.
- **`Publish now` antes de la hora**: se mantiene la Feature 006; si termina `PUBLISHED`,
  conserva `scheduled_at` como dato histórico y el scheduler nunca la ejecuta después. Si
  termina `FAILED`, el scheduler tampoco la vuelve a ejecutar.
- **Ejecución automática que termina `FAILED`**: no se crea automáticamente ningún intento
  nuevo; solo cabe el reintento manual de la Feature 006, con origen `manual`.
- **Proyecto o cuenta desactivados tras armar**: al llegar la hora el preflight falla, la
  publicación sigue `SCHEDULED` y se muestra el motivo; nunca se sube nada.
- **Error temporal de red durante el preflight automático**: se trata como fallo de preflight
  (sin `PUBLISHING`, sin subida) y puede volver a comprobarse de forma limitada dentro de la
  ventana.
- **Backend cerrado durante toda la ventana**: la publicación armada queda overdue; no existe
  ninguna ejecución fuera del backend.
- **Pausa activada mientras el scheduler está procesando un ciclo**: las publicaciones aún no
  iniciadas no se inician; las que ya pasaron a `PUBLISHING` continúan.
- **Desarmar o cancelar mientras el scheduler la evalúa**: la decisión final de inicio
  comprueba de nuevo, de forma atómica, el estado armado y el estado de la publicación; si ya
  no cumple, no se inicia.
- **Publisher de la plataforma no disponible o no registrado**: el preflight falla con un
  motivo seguro; el scheduler no necesita conocer la plataforma.
- **Fallo inesperado del propio scheduler en un ciclo**: se registra de forma segura, no detiene
  el backend y el siguiente ciclo continúa; no provoca ejecuciones duplicadas.
- **Apagado del backend durante un ciclo**: el worker se detiene limpiamente; una ejecución
  que llegó a `PUBLISHING` se trata al arrancar con la recuperación de la Feature 006.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance y relación con la Feature 006

- **FR-001**: El sistema DEBE ejecutar automáticamente las publicaciones `SCHEDULED` armadas
  cuando llegue su hora, mientras el backend esté en ejecución. Esta feature sustituye la
  prohibición de ejecución automática de la Feature 006 (FR-004 y SC-012) únicamente en los
  términos definidos aquí.
- **FR-002**: El scheduler DEBE iniciar las ejecuciones exclusivamente a través del servicio
  genérico de publicación de la Feature 006, invocado directamente dentro del backend (no a
  través de la API HTTP), y NO DEBE duplicar lógica de publicación, preflight ni subida.
- **FR-003**: El núcleo del scheduler NO DEBE depender de ninguna plataforma concreta ni
  conocer detalles de YouTube; DEBE poder servir a futuras plataformas registradas sin cambios
  en su arquitectura.
- **FR-004**: La automatización DEBE ser local: NO DEBEN usarse cron, systemd, servicios
  externos ni infraestructura cloud. Con el backend detenido no existe automatización.

#### Worker y ciclo de vida

- **FR-005**: El scheduler DEBE arrancar con el backend, consultar periódicamente la base de
  datos (frecuencia de referencia ~30 segundos, fijada en el plan) y detenerse limpiamente
  cuando se detiene el backend.
- **FR-006**: Todas las decisiones temporales del scheduler DEBEN tomarse en UTC.
- **FR-007**: El reloj y la espera del scheduler DEBEN ser inyectables para poder probarse sin
  esperas reales.
- **FR-008**: El arranque DEBE seguir este orden: migraciones; inicialización de publishers;
  recuperación de ejecuciones `PUBLISHING` interrumpidas (Feature 006); inicialización del
  scheduler; búsqueda de publicaciones vencidas. El scheduler NUNCA DEBE ejecutarse en paralelo
  con la recuperación de ejecuciones interrumpidas.
- **FR-009**: Un fallo inesperado en un ciclo del scheduler NO DEBE detener el backend ni el
  scheduler; DEBE registrarse de forma segura y el siguiente ciclo DEBE continuar.

#### Elegibilidad automática

- **FR-010**: Una publicación DEBE ser candidata a ejecución automática solo si se cumplen
  todas estas condiciones: estado `SCHEDULED`; tiene `scheduled_at`; está armada para
  publicación automática; la automatización global no está pausada;
  `scheduled_at <= ahora <= scheduled_at + 10 minutos` (ambos límites incluidos); no existe
  otra ejecución activa para ella; y pasa el preflight completo de la Feature 006.
- **FR-011**: Las publicaciones `UNSCHEDULED`, `PUBLISHING`, `PUBLISHED`, `FAILED` y
  `CANCELLED` NUNCA DEBEN ejecutarse automáticamente. Una publicación `FAILED` solo puede
  volver a ejecutarse mediante la política manual de la Feature 006.
- **FR-012**: La ventana de recuperación automática DEBE ser de 10 minutos tras
  `scheduled_at`. Fuera de ella el scheduler NO DEBE iniciar ni volver a comprobar la
  publicación.

#### Consentimiento (publicación automática armada)

- **FR-013**: Cada publicación DEBE tener un indicador persistente y genérico (no específico de
  ninguna plataforma) de publicación automática habilitada (`auto_publish_enabled`). Su
  ubicación exacta se decide en el plan.
- **FR-014**: La migración DEBE dejar deshabilitada la publicación automática de todas las
  publicaciones existentes, en particular las `SCHEDULED`. Ninguna migración DEBE provocar
  efectos externos, contactar con plataformas ni iniciar publicaciones.
- **FR-015**: Al programar una publicación (crearla con fecha, asignar fecha o cambiarla), la
  interfaz DEBE presentar de forma inequívoca si se habilitará la publicación automática:
  la acción que arma DEBE expresarse como `Schedule & enable auto-publish` o mediante una
  confirmación igualmente explícita, y DEBE poder guardarse la programación sin armarla. NO
  DEBE existir automatización silenciosa.
- **FR-016**: El usuario DEBE poder habilitar y deshabilitar explícitamente la publicación
  automática de una publicación `SCHEDULED` editable. Solo DEBE poder habilitarse si su
  `scheduled_at` es futura en ese momento, el proyecto y la cuenta están activos y el archivo
  multimedia gestionado del contenido existe y es utilizable, con la misma regla de
  disponibilidad heredada de las Features 004/006 para programar publicaciones (sin una
  regla nueva).
- **FR-017**: Al pasar a `UNSCHEDULED`, al cancelarse o al reactivarse una publicación, la
  publicación automática DEBE quedar deshabilitada; reactivar NUNCA DEBE armarla de nuevo
  automáticamente.
- **FR-018**: Al cambiar `scheduled_at` de una publicación `SCHEDULED`, el scheduler DEBE usar
  exclusivamente la nueva fecha, la condición overdue anterior DEBE desaparecer y la ventana
  DEBE calcularse desde la nueva fecha. El estado armado resultante DEBE ser el que el usuario
  confirma explícitamente al guardar (FR-015).

#### Overdue

- **FR-019**: NO DEBE introducirse un nuevo estado persistente. "Overdue" DEBE ser una
  condición derivada que solo se cumple cuando se dan a la vez: estado `SCHEDULED`;
  publicación automática habilitada (`auto_publish_enabled` verdadero); y
  `ahora > scheduled_at + 10 minutos`. Una publicación desarmada NUNCA DEBE considerarse
  overdue, aunque su fecha haya pasado; deshabilitar la publicación automática de una
  publicación overdue DEBE hacer que deje de serlo inmediatamente.
- **FR-020**: Una publicación overdue DEBE permanecer `SCHEDULED`, NO DEBE ejecutarse
  automáticamente, DEBE mostrarse con `Missed automatic publishing window` y DEBE poder
  publicarse con `Publish now` o reprogramarse; si se rearma tras reprogramarla a una fecha
  futura, la nueva ventana se calcula desde esa fecha. Una publicación desarmada con fecha
  pasada DEBE mostrarse como programada con `Auto-publish disabled`, sin indicación de
  ventana perdida, y DEBE poder publicarse con `Publish now` o reprogramarse.

#### Pausa global

- **FR-021**: El sistema DEBE ofrecer un ajuste global persistente de pausa de la
  automatización, con acciones `Pause automation` y `Resume automation`, que sobreviva a
  reinicios. Su ubicación exacta se decide en el plan.
- **FR-022**: Mientras está pausada, el scheduler NO DEBE iniciar ejecuciones ni ejecutar
  preflights que contacten con plataformas; las ejecuciones ya `PUBLISHING` DEBEN continuar
  normalmente y `Publish now` DEBE seguir permitido.
- **FR-023**: Al reanudar, solo las publicaciones todavía dentro de su ventana PUEDEN
  ejecutarse; las demás DEBEN permanecer overdue. Reanudar NUNCA DEBE provocar la ejecución en
  bloque de publicaciones antiguas.

#### Duplicados y concurrencia

- **FR-024**: Como máximo una ejecución DEBE poder comenzar por publicación, incluso ante ciclos
  consecutivos o concurrentes del scheduler, varias instancias internas del worker o una
  solicitud `Publish now` simultánea. La garantía final DEBE residir en el backend con respaldo
  de la persistencia (reutilizando las garantías transaccionales de la Feature 006), no solo en
  memoria.
- **FR-025**: La decisión final de iniciar una ejecución automática DEBE re-verificar de forma
  atómica el estado, el estado armado, la pausa global y la ventana en el momento del inicio.
  La estrategia exacta de reclamación se decide en el plan.
- **FR-026**: Cuando varias publicaciones sean elegibles, el scheduler DEBE procesarlas en orden
  determinista (`scheduled_at` más antiguo primero, con desempate estable) y con un número
  limitado de ejecuciones automáticas simultáneas (límite fijado en el plan).
- **FR-027**: Una publicación que espera capacidad NO DEBE duplicarse; DEBE re-evaluarse al
  llegar su turno y, si su ventana ha terminado, quedar overdue de forma visible sin
  ejecutarse.

#### Preflight y fallos

- **FR-028**: El scheduler DEBE reutilizar el preflight completo de la Feature 006 (proyecto y
  cuenta activos, publisher disponible, conexión y credenciales válidas o renovables, canal
  correcto, archivo disponible, metadata válida, opciones específicas completas y ausencia de
  otra ejecución); NO DEBE existir una segunda implementación.
- **FR-029**: Si el preflight falla, la publicación NO DEBE pasar a `PUBLISHING`, NO DEBE
  crearse subida ni sesión de subida, NO DEBE crearse un `PublicationAttempt` salvo que la
  Feature 006 lo cree para ese mismo fallo, y la publicación DEBE permanecer `SCHEDULED`.
- **FR-030**: El sistema DEBE conservar, por publicación, información genérica y no sensible
  sobre el último fallo de inicio automático (al menos código seguro, mensaje comprensible y
  momento) para mostrarla en la interfaz. Su ubicación exacta se decide en el plan. DEBE dejar
  de mostrarse como vigente cuando la publicación se reprograma, se desarma o se ejecuta.
- **FR-031**: Dentro de la ventana, el scheduler PUEDE volver a comprobar una publicación cuyo
  preflight falló, con una frecuencia limitada que evite bucles agresivos y contactos
  innecesarios con la plataforma (política exacta en el plan). Al terminar la ventana DEBE
  dejar de intentarlo.
- **FR-032**: Una vez creado el `PublicationAttempt` y con la publicación en `PUBLISHING`,
  DEBEN aplicarse exactamente las reglas de la Feature 006. Esta feature NO DEBE crear
  automáticamente un nuevo intento tras `FAILED` ni implementar retries automáticos entre
  intentos; la recuperación dentro de una sesión de subida sigue perteneciendo a la Feature
  006.

#### Origen del intento

- **FR-033**: `PublicationAttempt` DEBE registrar de forma genérica su origen, con al menos los
  valores `manual` y `scheduled`. Los intentos existentes antes de esta feature DEBEN quedar
  como `manual`. Su ubicación exacta se decide en el plan.
- **FR-034**: El historial DEBE mostrar el origen de cada intento (`Started manually` /
  `Started by scheduler`).

#### Queue e interfaz

- **FR-035**: La Queue DEBE mostrar para cada publicación `SCHEDULED`: fecha programada en hora
  local; si la publicación automática está habilitada; si espera su hora; si está overdue según
  FR-019 (`Missed automatic publishing window`, `Publish now or reschedule`); si la automatización
  global está pausada (`Automation paused`); y, si existe, el último motivo vigente de fallo de
  inicio automático. NO DEBE introducirse una vista Calendar.
- **FR-036**: La interfaz DEBE mostrar de forma sencilla el estado global de la automatización
  (en marcha / pausada y, opcionalmente, la última comprobación correcta del scheduler), las
  acciones `Pause automation` / `Resume automation` y un aviso de que AutoPublisher debe estar
  en ejecución para publicar automáticamente.
- **FR-037**: La Queue y el detalle DEBEN reflejar sin recarga manual el inicio de una
  ejecución por el scheduler y su evolución posterior.

#### Seguridad

- **FR-038**: Se DEBEN mantener todas las garantías de las Features 005 y 006. El scheduler NO
  DEBE almacenar ni recibir en su estado persistente tokens, URLs de sesión de subida, cabeceras
  de autorización, secretos ni respuestas crudas sensibles, ni registrarlos en logs.
- **FR-039**: Los errores del scheduler y los fallos de inicio automático DEBEN contener solo
  información segura. El frontend NO DEBE recibir ni guardar datos sensibles.

#### Persistencia, API y documentación

- **FR-040**: Los nuevos datos (publicación automática habilitada, ajuste de pausa, último
  fallo de inicio automático, origen del intento) DEBEN persistir mediante el sistema de
  migraciones versionado existente, sin perder datos previos y cumpliendo FR-014.
- **FR-041**: La API DEBE permitir: habilitar y deshabilitar la publicación automática de una
  publicación (incluido al programarla); consultar y cambiar la pausa global; consultar el
  estado de la automatización; y obtener en las publicaciones e intentos los datos derivados
  necesarios para la interfaz (armada, overdue, último fallo automático, origen). Los errores
  DEBEN seguir el formato estructurado existente.
- **FR-042**: La documentación (README y `quickstart.md`) DEBE explicar: que AutoPublisher debe
  estar en ejecución para publicar automáticamente; el consentimiento explícito y que las
  publicaciones programadas antiguas no quedan armadas; la ventana de 10 minutos y la
  condición overdue; y `Pause automation`.
- **FR-043**: `quickstart.md` DEBE incluir una prueba real segura (canal ya conectado, vídeo
  pequeño, privacidad `private`, `Notify subscribers = No`) en la que una publicación armada se
  publica sola sin pulsar `Publish now`, verificando `PUBLISHING`, progreso, `PUBLISHED`,
  vídeo privado en YouTube, origen `scheduled`, persistencia tras reinicio y ausencia de
  secretos; y validaciones sin subida real de Pause/Resume, publicación overdue y publicación
  preexistente/desarmada no ejecutada. No DEBEN incluirse video IDs ni URLs reales.
- **FR-044**: Los tests automatizados DEBEN funcionar sin Internet, con reloj y espera
  simulados, publishers simulados y el simulador de YouTube existente cuando sea necesario, sin
  esperas reales largas, y cubrir como mínimo los escenarios de tiempo, arranque,
  consentimiento, pausa, duplicados, preflight, ejecución, varias publicaciones, Queue/UI y
  seguridad enumerados en la descripción de la feature.

### Key Entities *(include if feature involves data)*

- **Publication** (existente, Features 004/006): gana el indicador genérico de publicación
  automática habilitada y la información del último fallo de inicio automático (ubicación
  exacta en el plan). Conserva sus estados; overdue es una condición derivada, no un estado.
- **PublicationAttempt** (existente, Feature 006): gana el origen del intento (`manual` /
  `scheduled`). Las reglas de creación, estados y seguridad no cambian.
- **Ajustes de automatización** (nuevo, global, persistente): estado de pausa de la
  automatización. Opcionalmente, información no sensible del estado del scheduler (p. ej.
  última comprobación correcta), que puede no persistirse.
- **Scheduler** (nuevo componente del backend, sin datos propios sensibles): ciclo periódico
  que selecciona candidatas, las ordena, respeta la concurrencia limitada y delega en el
  servicio genérico de publicación.
- **Publishers y servicio genérico de publicación** (existentes, Feature 006): se reutilizan
  sin cambios de responsabilidad.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo `importar vídeo → crear Publication → elegir
  fecha → habilitar publicación automática → dejar AutoPublisher en marcha → sin ninguna acción
  a la hora → PUBLISHED` contra YouTube real siguiendo `quickstart.md`, sin editar archivos ni
  bases de datos a mano.
- **SC-002**: En condiciones normales, una publicación armada y válida comienza su ejecución en
  menos de 60 segundos desde su `scheduled_at`.
- **SC-003**: 0 ejecuciones automáticas antes de la hora programada.
- **SC-004**: 0 ejecuciones automáticas de publicaciones desarmadas, incluidas el 100 % de las
  publicaciones programadas existentes antes de la migración.
- **SC-005**: 0 ejecuciones automáticas iniciadas mientras la automatización está pausada; la
  pausa se conserva en el 100 % de los reinicios.
- **SC-006**: 0 ejecuciones automáticas iniciadas más de 10 minutos después de su
  `scheduled_at`.
- **SC-007**: Ante cualquier combinación de ciclos concurrentes del scheduler y solicitudes
  `Publish now` para la misma publicación, se crea como máximo 1 `PublicationAttempt` y se
  inicia como máximo 1 subida.
- **SC-008**: 0 intentos nuevos creados automáticamente tras un `FAILED`.
- **SC-009**: 0 subidas, sesiones de subida o cambios a `PUBLISHING` cuando falla el preflight
  automático, y el 100 % de esos fallos muestran un motivo comprensible al usuario.
- **SC-010**: Nunca se superan las ejecuciones automáticas simultáneas permitidas, y el 100 % de
  las publicaciones vencidas a la vez terminan iniciadas exactamente una vez u overdue (según
  FR-019) de forma visible (ninguna perdida en silencio).
- **SC-011**: `Publish now` manual sigue funcionando en el 100 % de los casos elegibles,
  también con la automatización pausada.
- **SC-012**: La base de datos, los logs y las respuestas al frontend contienen 0 secretos
  nuevos (verificado por tests automáticos y por inspección manual en el quickstart).
- **SC-013**: La suite completa se ejecuta sin Internet, sin esperas reales largas, y todos los
  quality gates existentes siguen pasando.

## Assumptions

- **Alcance**: quedan fuera los retries automáticos entre intentos, el scheduler cloud,
  daemons/systemd/cron, la ejecución con el backend cerrado, despertar el equipo, las
  notificaciones push/email, las recurrencias y publicaciones periódicas, nuevo bulk
  scheduling, Calendar, Dashboard, otras plataformas (Instagram, TikTok, X, Threads, Telegram),
  analytics, generación de contenido y edición o borrado remotos.
- **Decisiones diferidas al plan**: frecuencia exacta del ciclo (~30 s de referencia); límite
  de ejecuciones automáticas simultáneas; estrategia de reclamación atómica; ubicación de
  `auto_publish_enabled`, del ajuste de pausa, del último fallo automático y del origen del
  intento; política de re-comprobación del preflight dentro de la ventana; mecanismo de
  actualización automática de la interfaz; y si se expone la última comprobación correcta.
- **Ventana inclusiva**: el límite `scheduled_at + 10 minutos` se considera dentro de la
  ventana; cualquier instante posterior queda fuera.
- **Armar requiere fecha futura**: coherente con la Feature 004 (no se asignan fechas pasadas),
  solo puede armarse una publicación cuya fecha sea futura en ese momento; así armar nunca
  dispara una publicación inmediata.
- **Reactivación siempre desarmada**: la forma más sencilla y segura de cumplir que reactivar no
  arme silenciosamente es dejar siempre desarmada la publicación reactivada.
- **Proceso único**: AutoPublisher se ejecuta como un único backend local; aun así, la
  protección frente a duplicados se apoya en la persistencia, no en la memoria.
- **Reloj del sistema fiable**: se asume que el reloj del ordenador es razonablemente correcto;
  los saltos de reloj se tratan con la regla de la ventana.
- **Dependencias**: reutiliza `Publication`, programación, cancelación/reactivación y Queue
  (Feature 004), conexión y credenciales (Feature 005), servicio genérico de publicación,
  registro de publishers, preflight, `PublicationAttempt`, garantías de concurrencia,
  recuperación al arrancar y simulador de YouTube (Feature 006), y el sistema de migraciones y
  el formato estructurado de errores existentes.
