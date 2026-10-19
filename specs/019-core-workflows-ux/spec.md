# Feature Specification: Core Workflows UX Redesign

**Feature Branch**: `019-core-workflows-ux`

**Created**: 2026-10-18

**Status**: Draft

**Input**: User description: "Feature 019 — Core Workflows UX Redesign. Rediseñar sobre la foundation de 018 los workflows centrales que conservan UX legacy: Library, Media detail, Publish (ruta propia, Compose → Review, snapshot explícito de contenido en los drafts nuevos, Resume sin inventar common content, Platform details con autosave, una única declaración TikTok, When = Now | Schedule con auto-publish implícito, Finish later, error summary, resultado por destino), Posts (Needs you / Upcoming / Drafts / History), Calendar read-only, Post detail con panel de estado/acción, reprogramación de Failed sin resultado incierto, Published como historial de lo realmente enviado, Text-only Posts y ampliación pequeña del read-model de uso de Media. Sin Feature 020 (deployment, auth, LAN, HTTPS, PWA, push, backups), sin Republish, sin calendar editable, sin bulk management, sin paginación backend, sin sorting en Library, sin borrado de Posts."

## Contexto

Feature 018 estableció la foundation: URLs y deep links, App Shell responsive, Home /
Attention, contexto de proyecto, Accounts, Settings, design system, `DetailSurface`,
primitivas responsive y base de accesibilidad. Las pantallas de Library, Media detail,
Distribute, cola de publicaciones y detalle de publicación se integraron en las nuevas rutas
con cambios mínimos (018 FR-007) y siguen teniendo UX legacy.

Feature 019 rediseña esos workflows para que el uso diario

`Media → Publish → Scheduled/Published`

sea obvio, coherente y cómodo en escritorio y móvil, sin rehacer capacidades que ya existen
(creación multi-destino atómica, presets, publish-check, opciones de plataforma, scheduler,
consentimiento TikTok, display state, read-models de 018).

### Principio rector

> The interface should explain itself.

Prioridad de decisión, en este orden: claridad, accesibilidad, coherencia, eficiencia,
calidad visual. Sin decoración innecesaria.

### Terminología visible

- Se usan: **Media**, **Library**, **Publish**, **Post**, **Draft**, **Scheduled**,
  **Published**, **Needs attention** / **Needs details** / **Needs you** según contexto,
  **Calendar**, **History**.
- NO DEBEN aparecer en la UI normal: Publication, Asset, Queue, Distribute, Prepare,
  Unscheduled, attempt, scheduler state, armed ni códigos internos. Pueden aparecer
  únicamente dentro de disclosures técnicos explícitos ("Technical details").
- Los nombres internos (modelos, API, base de datos) no se renombran (018 FR-048).

## Relación con specs anteriores y refinamientos deliberados

Feature 019 refina de forma explícita los siguientes comportamientos. Todo lo no listado aquí
se mantiene exactamente como lo definen las specs anteriores (en particular: lifecycle de
Publication salvo la transición de R6, regla de duplicados activos, ventana de 10 minutos y overdue de 007, huella e
invalidación del consentimiento TikTok de 013 FR-025, anti-duplicados y "nunca reenviar" de
013/014, pausa global, display state de 018).

| # | Comportamiento anterior | Refinamiento en 019 |
|---|---|---|
| R1 | 017 FR-022a / Assumptions: un campo común no modificado no genera override y la Publication sigue heredando cambios posteriores del Content. | Los drafts creados por el nuevo Publish flow guardan un **snapshot explícito** por destino (caption, hashtags y, cuando aplica, title) como overrides explícitos, aunque el valor coincida con el de la Media. La capacidad backend de crear sin overrides se mantiene para otros clientes y los drafts legacy siguen heredando. |
| R2 | 017 FR-010 / FR-023: la creación ofrece Prepare (sin fecha) o Schedule (fecha común). | En el nuevo flujo la creación (Continue) produce siempre Drafts; la fecha y la ejecución se deciden después, en Review. La capacidad backend de crear con fecha se mantiene. |
| R3 | 017 FR-031 / Fuera de alcance: no existe "Publish all" ni armado masivo de auto-publish. | Review tiene un único CTA que publica o programa los N destinos (`Publish to N destinations` / `Schedule N posts`). Cada Post sigue siendo independiente: se valida todo antes de iniciar nada, pero se ejecuta, progresa y falla por separado; no existe entidad de lote. |
| R4 | 007 FR-015: debe poder guardarse una programación sin armar la publicación automática. | En las superficies de 019, **Schedule implica auto-publish**: programar (en Publish, Reschedule o Edit schedule) siempre deja el Post en "Scheduled · automatic" (o "Scheduled · paused"). No se ofrece crear programaciones manuales nuevas. Los Posts "Scheduled · manual" legacy siguen siendo compatibles y ofrecen `Publish automatically`. El backend conserva la capacidad de programar sin armar. |
| R5 | 013 FR-024: `Publish now` exige confirmar la declaración en su diálogo aunque exista un consentimiento guardado con la misma huella. | En el nuevo flujo existe **una única declaración TikTok**, dentro de la card de TikTok, que empieza sin confirmar para cada nueva acción relevante, representa exactamente la configuración visible y se registra al ejecutar el CTA final. Se elimina la segunda confirmación redundante del diálogo antiguo de Publish now. La regla de fondo se mantiene: cada acción que publica o arma un Post TikTok requiere una confirmación expresa en esa acción; la huella y su invalidación (013 FR-025) no cambian. |
| R6 | 006 / reglas de edición actuales: la fecha de un Post `FAILED` no puede cambiarse ("Cancel and reactivate it to schedule it again"). | Un Post Failed cuyo último intento **no** tiene resultado incierto puede `Retry now`, `Reschedule` o `Move to drafts` directamente, conservando su historial de intentos. Con resultado incierto (Needs review) se rechazan con "Check the result first." mientras siga la incertidumbre; la vía de resolución existente de 006 FR-041 (comprobar el resultado y, tras confirmar explícitamente que no se publicó, `Publish again`) se conserva dentro de `Check result` (FR-073a). Es el único cambio funcional de lifecycle de 019. 007 FR-011 se mantiene: un Post Failed nunca se ejecuta automáticamente; al reprogramarse deja de estar Failed. |
| R7 | 017 FR-024: el botón final está deshabilitado mientras no haya destinos. | Los CTAs de Publish permanecen accionables; si falta algo muestran un error summary accesible en lugar de deshabilitarse silenciosamente. |
| R8 | 017 FR-037: aplicar un preset preselecciona sus cuentas utilizables. | Aplicar un preset **sustituye** la selección actual; los destinos no utilizables aparecen como skipped con motivo. |
| R9 | 018 FR-004: Calendar no se implementa. | Calendar v1 read-only dentro de Posts. |
| R10 | 017 FR-016: la acción se llama Distribute y vive en el detalle del asset. | La acción se llama `Publish…` y Publish tiene ruta propia. |

## Clarifications

### Session 2026-10-18 (plan)

- Q: ¿Un Post Needs review queda sin vía de reintento? → A: No. Mientras el resultado sea incierto, `Retry now` directo, `Reschedule` y `Move to drafts` están bloqueados ("Check the result first.") y la acción principal es `Check result`. Ese Dialog conserva la vía histórica de 006 FR-041: comprobar/reconciliar el resultado cuando la plataforma lo permita y, si el usuario confirma explícitamente que el Post no se publicó, `Publish again` con el mecanismo existente `confirm_remote_checked`. No es un lifecycle nuevo (FR-073a).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicar una Media en varios destinos como una única tarea (Priority: P1)

Desde Library abro una Media, pulso `Publish…` y llego a la página Publish. Elijo destinos
(o aplico un preset), reviso el caption y los hashtags comunes, personalizo solo lo que
necesito y pulso `Continue`. En la misma página paso a Review: veo qué necesita cada
plataforma, lo completo, elijo `Now` o `Schedule` y pulso un único CTA. Si publico ahora, veo
el resultado por destino; si programo, AutoPublisher los publicará automáticamente.

**Why this priority**: es el journey principal de la aplicación (journey A) y el criterio de
primer uso que 018 delegó en 019.

**Independent Test**: con un proyecto con cuentas Ready de YouTube, Instagram y TikTok y una
Media de vídeo, completar Library → Media → Publish → Continue → completar Platform details
→ Schedule → `Schedule 3 posts`, y comprobar que existen 3 Posts "Scheduled · automatic" con
la fecha elegida y el contenido confirmado, y que aparecen en Posts → Upcoming.

**Acceptance Scenarios**:

1. **Given** una Media sin drafts, **When** pulso `Publish…` en su detail, **Then** navego a
   `/p/:projectId/library/:mediaId/publish` en fase Compose, con un resumen compacto de la
   Media (preview, title, type, duración si aplica) y `Back to media`.
2. **Given** Compose, **When** miro Destinations, **Then** veo las cuentas activas del
   proyecto como filas seleccionables completas, primero las disponibles y después las no
   disponibles, estas deshabilitadas con su motivo ("Video only", "Reconnect account",
   "Finish account setup", "Choose a channel", "Configure in Settings", "Coming soon",
   "Already scheduled · View post"…); las cuentas inactivas no aparecen.
3. **Given** Compose, **When** cambio destinos, caption o hashtags, **Then** no se crea ni
   modifica ningún Post en el backend.
4. **Given** varios destinos seleccionados, **When** miro Content, **Then** veo un caption y
   unos hashtags comunes prellenados desde la Media con el texto "Used for all selected
   destinations unless customized." y puedo personalizar un destino concreto sin que se
   rendericen a la vez los formularios completos de todos los destinos.
5. **Given** un preset con una cuenta no utilizable, **When** lo aplico, **Then** la
   selección actual se sustituye por las cuentas utilizables del preset y la no utilizable
   aparece como skipped con su motivo.
6. **Given** 3 destinos seleccionados, **When** pulso `Continue`, **Then** se crean 3 Drafts
   de una vez (o ninguno si alguno es inválido, señalando el destino a corregir), cada uno
   con caption, hashtags y —en YouTube— title guardados explícitamente; no se programa, no
   se arma auto-publish y no se publica nada.
7. **Given** que acabo de pulsar `Continue`, **When** la página entra en Review, **Then** veo
   Destinations y Content plegados en resumen, un mensaje claro de que los drafts ya están
   guardados y pueden terminarse más tarde, Platform details, When y el CTA final; nunca un
   mensaje tipo "Created N publications" como si la tarea hubiese terminado.
8. **Given** Review con When = `Now` y todos los destinos Ready, **When** pulso
   `Publish to 3 destinations`, **Then** se inicia la publicación de cada destino, veo el
   progreso y el resultado por destino y un resumen agregado (p. ej. "2 published · 1
   failed").
9. **Given** Review con When = `Schedule`, **When** elijo fecha y hora futuras, **Then** veo
   la zona horaria, una vista legible de la fecha y el texto "AutoPublisher will publish
   these posts automatically at this time."; al pulsar `Schedule 3 posts` los 3 Posts quedan
   "Scheduled · automatic" a esa hora.
10. **Given** la automatización global en pausa, **When** elijo Schedule, **Then** puedo
    programar, pero se me advierte de que no se publicarán hasta reanudarla, con enlace a
    Settings; tras programar quedan "Scheduled · paused".
11. **Given** un destino con detalles pendientes, **When** pulso el CTA final, **Then** no se
    publica ni programa ningún destino, aparece un error summary que recibe el foco y enlaza
    a cada plataforma/campo problemático, y los errores inline siguen junto a cada campo.
12. **Given** que en el resultado un destino falló y los demás se publicaron, **When** veo el
    resumen, **Then** nunca dice "Publish failed"; indica el recuento por resultado y ofrece
    `Open post` en el destino con problema, además de `View posts` y `Back to Library`.
13. **Given** Review con Schedule y todos los destinos validados, **When** pulso
    `Schedule 4 posts` y la programación de un destino falla después de que los otros 3 hayan
    quedado programados (p. ej. su cuenta se desactivó en otra pestaña), **Then** veo
    "3 scheduled · 1 still a draft" con el resultado por destino, los 3 siguen Scheduled, el
    cuarto sigue Draft con su motivo y la opción de corregir y reintentar, y no se navega
    automáticamente a Posts.
14. **Given** una publicación en curso, **When** salgo de la página, **Then** se me ha
    indicado "Publishing continues in the background. Track it in Posts." y la publicación
    continúa.

---

### User Story 2 - Guardar y continuar más tarde (Resume / Finish later) (Priority: P1)

Puedo dejar una publicación a medias tras `Continue` con `Finish later` y retomarla desde
Posts → Drafts o desde la Media; Publish se abre directamente en Review con el contenido que
confirmé, por destino, sin inventar un "contenido común".

**Why this priority**: Publish crea los Drafts a mitad de la tarea; sin un Resume fiel, el
usuario pierde trabajo o ve contenido distinto del que confirmó (journey B).

**Independent Test**: crear 3 drafts con Continue, editar un detalle de plataforma, pulsar
`Finish later`, abrir Posts → Drafts → `Continue in Publish` y comprobar que Review muestra
exactamente los 3 destinos, el contenido confirmado por destino con su procedencia y el
detalle editado.

**Acceptance Scenarios**:

1. **Given** Review, **When** pulso `Finish later`, **Then** no se crea, programa, arma ni
   publica nada, no cambia ningún estado y navego a Posts → Drafts.
2. **Given** una edición local pendiente (p. ej. un autosave en curso o fallido), **When**
   pulso `Finish later`, **Then** la edición termina de guardarse antes de salir o, si no
   puede guardarse, se me pregunta si reintentar o descartarla; nunca se pierde en silencio.
3. **Given** una Media con Drafts activos, **When** abro su `/publish` (desde Media detail
   `Continue publishing · N drafts`, desde Posts o por URL), **Then** entro directamente en
   Review con todos los Drafts activos de esa Media.
4. **Given** Resume, **When** veo el contenido, **Then** se titula "Content by destination";
   los destinos con exactamente el mismo valor y la misma procedencia se agrupan
   visualmente, sin afirmar que ese contenido era "common"; cada campo indica su
   procedencia cuando es relevante ("Custom text" / "Uses the media's caption").
5. **Given** un draft legacy que hereda el caption de la Media, **When** lo veo en Resume,
   **Then** se indica "Uses the media's caption" y no se convierte en snapshot hasta que yo
   lo edite.
6. **Given** Resume, **When** uso `Customize` en un destino, **Then** solo cambia ese
   destino; **When** uso `Edit for these destinations`, **Then** elijo explícitamente el
   conjunto, veo exactamente qué destinos se modificarán y solo esos cambian.
7. **Given** un destino con texto propio, **When** elijo `Use the media's caption`, **Then**
   ese destino vuelve a heredar de la Media.
8. **Given** Review tras Continue, **When** añado un destino, **Then** se crea un nuevo Draft
   para esa cuenta; **When** quito un destino y confirmo, **Then** su Draft se cancela y pasa
   a History como Cancelled; **When** vuelvo a añadir esa cuenta, **Then** se reactiva ese
   mismo Post cuando es seguro (o se crea uno nuevo si no puede reactivarse).

---

### User Story 3 - Saber qué necesita atención y qué viene después en Posts (Priority: P1)

Posts me muestra el trabajo diario por significado: lo que me necesita, lo que se publicará
pronto y mis drafts, con History separado. Cada fila me dice qué es, dónde va, cuándo, su
estado y, si me necesita, qué hacer.

**Why this priority**: es la vista de control diario; un Missed o un Failed escondido es el
fallo más grave de la aplicación (Constitution V).

**Independent Test**: con Posts en todos los estados visibles, abrir Posts y comprobar
secciones, orden, contenido de filas, ocultación de secciones vacías, banner único de pausa
y que History contiene solo Published y Cancelled agrupados por mes.

**Acceptance Scenarios**:

1. **Given** Posts Failed, Needs review, Needs action, Missed y Scheduled con detalles
   incompletos en los próximos 7 días, **When** abro Posts, **Then** aparecen en "Needs you",
   ordenados por gravedad y después por fecha, cada uno con una pista de próxima acción
   ("Retry or reschedule", "Finish in TikTok", "Add 2 details"…).
2. **Given** que nada necesita al usuario, **When** abro Posts, **Then** la sección "Needs
   you" no aparece.
3. **Given** Posts publicándose y programados, **When** miro "Upcoming", **Then** los que se
   publican ahora aparecen arriba ("Publishing now") y los programados (automáticos, manuales
   legacy y en pausa) agrupados por día: Today, Tomorrow y fecha.
4. **Given** la automatización en pausa, **When** abro Posts, **Then** veo un único banner de
   proyecto con enlace a Settings, no un aviso repetido por cada Post.
5. **Given** drafts con Media y drafts de texto, **When** miro "Drafts", **Then** cada uno
   enlaza a su detalle, cuya acción principal es `Continue in Publish` o `Continue setup`.
6. **Given** Posts Published y Cancelled, **When** abro History (`?view=history`), **Then**
   aparecen agrupados por mes, con una carga inicial limitada y `Show more`; no aparecen en
   la lista diaria.
7. **Given** una búsqueda o una cuenta elegida en la toolbar, **When** filtro, **Then** todas
   las secciones respetan el filtro.
8. **Given** una fila, **When** la activo, **Then** se abre Post detail en `DetailSurface`
   con URL propia, la lista sigue montada (scroll, búsqueda y filtro intactos) y el detalle no
   se remonta cuando cambia el estado del Post.
9. **Given** `New post`, **When** lo abro, **Then** puedo elegir `Publish media…` o
   `Text post`.

---

### User Story 4 - Entender un Post y recuperarse de un problema (Priority: P1)

Al abrir un Post sé inmediatamente qué es, dónde va, cuándo, en qué estado está, qué
necesita de mí y qué puedo hacer ahora, con una acción principal clara. Si falló, puedo
reintentarlo, reprogramarlo o devolverlo a drafts sin pasar por Cancel → Reactivate.

**Why this priority**: es donde se resuelve todo lo que Home y Posts señalan (journey C).

**Independent Test**: abrir Posts en cada estado visible y comprobar la frase del panel de
estado, la acción principal y la secundaria; reprogramar un Failed sin resultado incierto y
comprobar que queda "Scheduled · automatic" con su historial de intentos intacto; intentar
reprogramar un Needs review y comprobar "Check the result first.".

**Acceptance Scenarios**:

1. **Given** cualquier Post, **When** abro su detail, **Then** veo en este orden: header
   (qué es y dónde va), panel de estado/acción (siempre visible, una frase, una acción
   principal y como mucho una secundaria), When, Content, Platform details, Activity
   (plegado) y la acción destructiva.
2. **Given** cada estado, **When** veo el panel, **Then** la acción principal y secundaria
   son las de la tabla de FR-071.
3. **Given** un Post Failed cuyo último intento terminó con resultado determinado, **When**
   elijo `Reschedule` con una fecha futura, **Then** queda "Scheduled · automatic" (o
   "Scheduled · paused") y sus intentos anteriores se conservan; **When** elijo
   `Move to drafts`, **Then** queda Draft; **When** elijo `Retry now`, **Then** se inicia un
   intento nuevo.
4. **Given** un Post Needs review, **When** intento reprogramarlo, reintentarlo
   directamente o moverlo a drafts, **Then** se rechaza con "Check the result first." y la
   acción principal es `Check result`.
4a. **Given** un Post Needs review, **When** abro `Check result`, **Then** AutoPublisher
   intenta comprobar el resultado en la plataforma cuando es posible; si queda resuelto, el
   Post pasa a su estado determinado (Published, o Failed con R6 disponible); si sigue
   incierto, puedo confirmar explícitamente que lo comprobé y que no se publicó, y entonces
   `Publish again` inicia un intento nuevo; sin esa confirmación no se ofrece reintento.
5. **Given** un Post Missed, **When** abro su detail, **Then** la acción principal es
   `Reschedule` y la secundaria `Publish now`.
6. **Given** un Post Published, **When** veo Content, **Then** se muestra el contenido que
   realmente se envió cuando está registrado; el contenido efectivo actual, si difiere, solo
   aparece como información secundaria.
7. **Given** Activity, **When** lo despliego, **Then** veo eventos en lenguaje humano
   ("Tue 18:00 · Started automatically", "Tue 18:01 · Failed: Instagram rejected the video
   format"); códigos de error, ids de intento, rutas técnicas y checksums solo aparecen bajo
   un segundo disclosure "Technical details".
8. **Given** un Post cancelable, **When** pulso `Cancel post`, **Then** un Dialog me pide
   confirmación y explica que puede reactivarse; tras confirmar pasa a Cancelled y nunca se
   elimina.
9. **Given** un Post con detalles de plataforma pendientes, **When** abro su detail, **Then**
   Platform details está abierto y es accionable con autosave; si está Ready o Published,
   aparece plegado.

---

### User Story 5 - Encontrar Media y entender cómo se ha usado (Priority: P2)

Library me permite encontrar Media rápidamente, importar sin fricción y ver en cada card un
único indicador de uso. El detail de una Media muestra preview, identidad, la acción
principal (`Publish…` o `Continue publishing · N drafts`), contenido editable, su uso
agrupado y los detalles de archivo bajo disclosure.

**Why this priority**: es el punto de entrada del journey principal y del journey E; hoy ya
es usable, por eso va detrás de Publish y Posts.

**Independent Test**: con Media de distintos tipos y usos, buscar por hashtag, filtrar
"Not used yet", importar varios archivos (uno inválido), abrir una Media con drafts, editar
su caption con Posts heredando y comprobar el aviso, y abrir un Post Published desde Usage.

**Acceptance Scenarios**:

1. **Given** Library con Media, **When** la abro, **Then** veo `Library`, el número de Media,
   búsqueda, `Import media` y los filtros All / Images / Videos / Not used yet.
2. **Given** una búsqueda, **When** escribo, **Then** se filtran las Media por title,
   filename, description y hashtags.
3. **Given** Library con Media, **When** pulso `Import media`, **Then** se abre directamente
   el selector de archivos; en escritorio/tablet también puedo soltar archivos sobre la
   página; el progreso y el resultado aparecen en un panel inline descartable con resumen
   agregado y detalle por archivo.
4. **Given** Library vacía, **When** la abro, **Then** veo un EmptyState con una dropzone
   grande y una única acción principal para importar; en móvil no depende de drag & drop.
5. **Given** las cards, **When** las veo, **Then** muestran preview, duración si es vídeo,
   title o filename y un único indicador de uso con prioridad Needs attention > Scheduled >
   Drafts > Published > Not used yet, sin metadata técnica.
6. **Given** una card, **When** la activo, **Then** la URL cambia, se abre Media detail en
   `DetailSurface` (nunca debajo del grid), la Library sigue montada con búsqueda, filtro y
   scroll, y la card seleccionada queda claramente marcada.
7. **Given** una Media con 2 drafts, **When** abro su detail, **Then** la acción principal es
   `Continue publishing · 2 drafts`, indicando sus destinos cuando es útil.
8. **Given** un proyecto inactivo o una Media cuyo archivo no está disponible, **When** abro
   su detail, **Then** la acción de publicar aparece deshabilitada con el motivo visible.
9. **Given** que edito el caption de una Media con Posts que lo heredan, **When** voy a
   guardar, **Then** veo un aviso inline con cuántos Posts, qué destinos y qué estados se
   verán afectados (sin contar Published ni Cancelled); si el cambio invalidaría el
   consentimiento de un TikTok programado automáticamente, se me pide confirmación explícita
   antes de guardar.
10. **Given** Usage, **When** lo veo, **Then** los Posts asociados se agrupan en Needs you,
    Upcoming, Drafts y Published (Cancelled solo como recuento o información secundaria);
    cada fila enlaza a su Post detail; Published muestra inicialmente los últimos y ofrece
    `Show all`.
11. **Given** File details, **When** lo despliego, **Then** veo filename, formato,
    dimensiones, duración, tamaño, archivo/versión publicada, estado de metadata,
    inspección/eliminación de metadata y checksums, sin que estos dominen el detail.

---

### User Story 6 - Ver lo programado y publicado en un Calendar (Priority: P2)

Dentro de Posts puedo cambiar a Calendar para ver la semana: en escritorio de lunes a
domingo con los Posts de cada día ordenados por hora; en tablet y móvil como agenda por
días. Es de solo lectura; pulsar un Post abre su detail.

**Why this priority**: aporta visión temporal (journey D) sobre datos existentes, sin nuevas
capacidades de edición.

**Independent Test**: con Posts programados, publicados, fallidos y vencidos en la semana
actual y la siguiente, abrir Calendar, navegar semanas, recargar y comprobar que la semana se
conserva en la URL, que no aparecen Drafts ni Cancelled y que abrir un Post muestra su
detail.

**Acceptance Scenarios**:

1. **Given** escritorio con ancho suficiente, **When** abro Calendar, **Then** veo la semana
   de lunes a domingo sin eje de horas, cada día con sus Posts como bloques compactos
   ordenados por hora; dos Posts a la misma hora se apilan.
2. **Given** tablet o móvil, **When** abro Calendar, **Then** veo una agenda agrupada por día.
3. **Given** Calendar, **When** uso previous / Today / next, **Then** cambia el rango, la URL
   refleja la semana elegida y la zona horaria es visible.
4. **Given** Posts Scheduled, Publishing, Published, Missed, Failed, Needs review y Needs
   action, **When** los veo en Calendar, **Then** aparecen en su momento relevante con icono
   y texto de estado, nunca solo con color; Drafts y Cancelled no aparecen.
5. **Given** Calendar, **When** intento arrastrar, redimensionar o crear en un hueco,
   **Then** no existe esa capacidad.

---

### User Story 7 - Publicar o programar un Post solo de texto (Priority: P2)

Desde Posts → New post → Text post escribo el texto, elijo destinos compatibles con texto y
sigo el mismo modelo Compose → Review → Now/Schedule que con Media.

**Why this priority**: capacidad existente que debe sentirse parte del mismo producto
(journey F).

**Independent Test**: crear un Text post para dos cuentas compatibles, comprobar que las
incompatibles aparecen como "Needs media", programarlo y verlo en Upcoming; crear otro,
pulsar `Finish later` y retomarlo desde Drafts con `Continue setup`.

**Acceptance Scenarios**:

1. **Given** Posts, **When** elijo `New post → Text post`, **Then** se abre la ruta
   conceptual `/p/:projectId/posts/new` en Compose, sin Media y con el texto obligatorio.
2. **Given** destinos sin soporte de solo texto, **When** miro Destinations, **Then**
   aparecen deshabilitados con "Needs media".
3. **Given** texto y destinos, **When** pulso `Continue`, **Then** se crean los Drafts de
   texto con la capacidad existente y paso a Review; Review, When, readiness y resultado
   se comportan como en Publish con Media.
4. **Given** un Text draft, **When** lo retomo desde Posts → Drafts o desde su detail
   (`Continue setup`), **Then** vuelvo a su Review mediante una URL enlazable.

---

### Edge Cases

- **Continue con un destino que deja de ser válido** (cuenta desactivada, post activo creado
  en otra pestaña): no se crea ningún Draft; el destino se marca para corregir y el resto del
  estado local se conserva.
- **Continue sin destinos**: el CTA sigue accionable y muestra un error summary ("Choose at
  least one destination").
- **Destino bloqueado por un Post activo de la misma Media**: aparece deshabilitado con el
  motivo y un enlace al Post ("Already scheduled · View post", "Publishing now · View post",
  "Has a failed post · View post"…). Los Drafts de esa Media no bloquean: forman parte de
  Resume; si un Draft de esa Media no está en el Publish set actual, la cuenta muestra que ya
  tiene un Draft y ofrece `Add to this task` (FR-035), nunca un segundo Draft.
- **Abrir `/publish` con Posts de esa Media publicándose y sin drafts**: se abre Compose; esas
  cuentas aparecen bloqueadas con enlace a su Post.
- **Autosave de Platform details fallido**: el campo muestra "Couldn't save · Retry"; el CTA
  final y `Finish later` no ignoran el fallo.
- **TikTok Direct Post sin Creator Info** (carga o fallo): estado Checking/skeleton y, si
  falla, error con `Retry` y alternativa `Send to inbox instead`; nunca se ofrecen opciones de
  privacidad inventadas. Si el cliente actual solo permite `SELF_ONLY`, se indica claramente.
- **TikTok Inbox sin permiso de envío a inbox**: el modo aparece no disponible con el motivo
  (reconectar), sin bloquear Direct Post.
- **Telegram sin canal**: bloqueado antes de crear con enlace para completar el setup.
- **Cambio de configuración TikTok tras marcar la declaración**: la declaración vuelve a
  quedar sin confirmar, porque debe representar exactamente la configuración visible.
- **Fecha de Schedule que pasa a estar en el pasado** antes de confirmar: se rechaza con el
  error en el campo de fecha y nada se programa.
- **Validación previa correcta pero fallo en el inicio de un destino** (Publish now): ese
  destino se muestra "Didn't start" con motivo; los demás siguen su curso.
- **Fallo remoto parcial**: solo afecta a su Post; el resumen muestra recuentos por
  resultado.
- **Fallo de programación tras validación correcta**: distinto de un error de validación
  previo (donde no empieza ninguno): los destinos ya programados se mantienen y el fallido
  queda en su estado real con opción de reintentar (FR-052a).
- **Recarga durante la publicación o la programación**: con la identidad del Publish set
  (FR-031a) se reconstruyen exactamente esos Posts en su estado real; sin identidad (p. ej. al
  entrar desde Media detail tras haber terminado) se aplican FR-031 o Compose, nunca un
  resultado inferido de Posts históricos.
- **Quitar un destino cuyo Draft ya no es Draft** (p. ej. publicado desde otra pestaña): no se
  cancela; se informa del estado actual con enlace al Post.
- **Re-añadir un destino cuyo Post cancelado no puede reactivarse** (p. ej. existe otro
  activo): se informa del motivo; nunca se crea un duplicado activo.
- **Re-añadir tras una recarga**: no se reactiva ningún Cancelled histórico (podría tener
  fecha); se crea un Draft nuevo con el snapshot actual (FR-035).
- **Editar la Media mientras hay drafts nuevos de 019**: los drafts con snapshot no cambian;
  el aviso de Media detail solo cuenta los Posts que heredan.
- **Media eliminada o archivo no disponible con drafts existentes**: Resume muestra el
  problema y bloquea publicar/programar con motivo; `Finish later` sigue disponible.
- **URL de Publish de una Media de otro proyecto o inexistente**: "not found" con una acción
  de recuperación (018 FR-005).
- **Proyecto inactivo**: Publish bloqueado con motivo; Posts y Calendar siguen consultables.
- **Readiness más allá de 7 días**: no se promete "Ready" ni "Needs details" basado en la
  comprobación local; el Post se muestra como Scheduled sin indicador de readiness.
- **Readiness no verificable** dentro del horizonte: se trata como detalles incompletos con
  "Couldn't verify requirements" (018 FR-017b).
- **Published sin contenido enviado registrado** (Posts antiguos): se muestra el contenido
  efectivo indicando que puede no coincidir exactamente con lo enviado.
- **History muy largo**: carga inicial limitada con `Show more`; sin paginación backend.
- **Calendar en una semana sin Posts**: estado vacío neutro con navegación disponible.
- **Zona horaria**: fechas en la zona horaria local del navegador, visible en Schedule y
  Calendar.
- **Post que cambia de estado con el detail abierto**: el detail se actualiza sin remontarse
  ni perder el foco ni el scroll.

## Requirements *(mandatory)*

### Functional Requirements

#### Library

- **FR-001**: Library DEBE seguir en `/p/:projectId/library/:mediaId?` y mostrar en su
  header: `Library`, número de Media, búsqueda, `Import media` y los filtros All, Images,
  Videos y Not used yet. NO DEBE haber filtro "Used" ni sorting.
- **FR-002**: La búsqueda DEBE cubrir title, filename, description y hashtags.
- **FR-003**: "Not used yet" DEBE mostrar las Media que no tienen ningún Post salvo
  Cancelled.
- **FR-004**: Con Media existente, `Import media` DEBE abrir directamente el selector de
  archivos; en escritorio y tablet DEBE admitirse además soltar archivos sobre la página. El
  progreso y el resultado DEBEN mostrarse en un panel inline descartable con resumen agregado
  y detalle por archivo.
- **FR-005**: Con Library vacía DEBE mostrarse un EmptyState con una dropzone grande y una
  única acción principal de importar; en móvil NO DEBE depender de drag & drop.
- **FR-006**: Cada card DEBE mostrar preview, duración si es vídeo, title o filename y un único
  indicador principal de uso con prioridad: Needs attention, Scheduled, Drafts, Published,
  Not used yet. NO DEBE mostrar metadata técnica.
- **FR-007**: Activar una card DEBE actualizar la URL y abrir Media detail en `DetailSurface`;
  NO DEBE renderizar el detail debajo del grid. La Library DEBE seguir montada conservando
  búsqueda, filtro y scroll, y la card seleccionada DEBE quedar claramente marcada.

#### Media detail

- **FR-008**: Media detail DEBE presentar, en este orden: preview, identidad, acción
  principal, Content, Usage y File details.
- **FR-009**: La acción principal DEBE ser `Publish…` si la Media no tiene Drafts, o
  `Continue publishing · N drafts` si los tiene, indicando sus destinos cuando sea útil.
  Ambas navegan a la ruta Publish de la Media.
- **FR-010**: Si la Media no puede publicarse por el estado del proyecto o de la Media, la
  acción DEBE aparecer deshabilitada con el motivo visible.
- **FR-011**: Content DEBE mostrar title, caption/description y hashtags y permitir editarlos
  en un único bloque.
- **FR-012**: Antes de guardar un cambio de Content que modifique Posts que heredan ese campo
  de la Media, DEBE mostrarse un aviso inline con el número de Posts afectados, sus destinos y
  sus estados. Published y Cancelled NO DEBEN contarse como afectados.
- **FR-013**: Si el cambio invalidaría el consentimiento de un Post TikTok programado
  automáticamente, DEBE pedirse confirmación explícita antes de guardar, indicando la
  consecuencia (dejará de publicarse automáticamente hasta volver a confirmar la
  declaración).
- **FR-014**: Usage DEBE agrupar los Posts de la Media en Needs you, Upcoming, Drafts y
  Published, con la misma semántica que Posts (FR-055–FR-060). Cancelled solo como recuento o
  información secundaria. Cada fila DEBE enlazar a su Post detail. Published PUEDE mostrar
  inicialmente los más recientes con `Show all`.
- **FR-015**: File details DEBE ser un disclosure secundario con filename, formato,
  dimensiones, duración, tamaño, archivo/versión publicada, estado de metadata,
  inspección/eliminación de metadata y checksums; los checksums NUNCA DEBEN dominar el
  detail.

#### Publish — ruta y modelo

- **FR-016**: Publish DEBE tener ruta propia `/p/:projectId/library/:mediaId/publish`, con
  deep link, recarga y atrás/adelante. NO DEBE vivir inline dentro de Media detail.
- **FR-017**: Publish DEBE tener dos fases conceptuales, Compose y Review, en la misma
  página, sin un wizard/stepper visual pesado. Desde la perspectiva del usuario es una única
  tarea aunque los Drafts se creen al pasar a Review.
- **FR-018**: En móvil Publish DEBE funcionar como task mode y DEBE ocultar la bottom
  navigation (FR-086), manteniendo una salida clara (`Back to media`, o su equivalente en
  Text post) y las acciones propias del task mode.

#### Publish — Compose

- **FR-019**: Antes de `Continue`, todo el estado de Publish DEBE ser local: NO DEBE crearse
  ni modificarse ningún Post.
- **FR-020**: Compose DEBE mostrar un resumen compacto de la Media (preview, title, type,
  duración cuando aplique) y `Back to media`, sin repetir el Media detail.
- **FR-021**: Destinations DEBE mostrar todas las cuentas activas del proyecto como filas
  seleccionables completas (no cards grandes): primero las disponibles; las no disponibles
  visibles pero deshabilitadas con su motivo. Las cuentas inactivas NO DEBEN aparecer.
- **FR-022**: La disponibilidad de cada destino DEBE derivarse de la salud de cuenta, la
  disponibilidad de la plataforma, las capacidades del publisher, el tipo de Media y los Posts
  activos existentes, bloqueando antes de crear las incompatibilidades conocidas. Los motivos
  DEBEN ser accionables cuando sea posible (enlace a la cuenta, a Settings o al Post que
  bloquea).
- **FR-023**: Presets DEBE ser un selector compacto. Aplicar un preset DEBE sustituir la
  selección actual por sus cuentas utilizables y mostrar las no utilizables como skipped con
  motivo, sin modificar el preset. DEBEN ofrecerse `Save as preset` y `Manage presets`; la
  gestión DEBE ocurrir en un Dialog secundario.
- **FR-024**: Content DEBE ofrecer caption y hashtags comunes locales, prellenados desde la
  Media, con el texto "Used for all selected destinations unless customized.", y
  personalización por destino (caption, hashtags y title en plataformas que lo consumen,
  hoy YouTube) mediante progressive disclosure. NO DEBEN renderizarse simultáneamente los
  formularios completos de todos los destinos. NO DEBE mostrarse un title común.
- **FR-025**: Los textos NO DEBEN truncarse ni adaptarse automáticamente (017 FR-026).

#### Publish — Continue y snapshot

- **FR-026**: `Continue` DEBE crear un Draft por destino seleccionado mediante la creación
  multi-destino existente, que DEBE seguir siendo todo o nada. Ante un rechazo DEBE
  conservarse todo el estado local y señalarse el destino o campo a corregir.
- **FR-027**: Los Drafts creados por `Continue` NO DEBEN tener fecha, NO DEBEN armar
  auto-publish y NO DEBEN publicarse.
- **FR-028**: Para cada Draft creado por el nuevo flujo DEBE guardarse como override
  explícito el contenido confirmado: caption, hashtags y, cuando la plataforma lo consume,
  title; aunque coincida con el valor de la Media (R1). Consecuencia: esos Drafts no cambian
  si después se edita la Media, y Resume reproduce exactamente lo confirmado.
- **FR-029**: NO DEBE persistirse ningún concepto de "common content", lote ni agrupación.

#### Publish — Review

- **FR-030**: Tras `Continue`, la página DEBE pasar a Review mostrando: resumen plegado de
  Destinations, resumen plegado de Content, un mensaje claro de que los Drafts ya existen y
  pueden terminarse más tarde, Platform details, When y la acción final. NO DEBE presentarse
  como una tarea terminada.
- **FR-031**: Si `/publish` se abre sin identidad de Publish set (FR-031a) y la Media tiene
  Drafts activos, DEBE entrarse directamente en Review con todos ellos como conjunto
  resumible, sin entidad de lote.
- **FR-031a**: Desde que existen Drafts (tras `Continue` o al entrar en Review por Resume),
  el Publish set DEBE tener una identidad estable ante recarga basada en los ids reales de
  sus Posts, representada en la URL/deep link u otro mecanismo sin entidad persistente
  (conceptualmente `…/publish?posts=12,13,14`; el encoding exacto lo decide el plan). Añadir
  o quitar destinos DEBE actualizar esa identidad. Con identidad presente, recarga,
  atrás/adelante y apertura directa DEBEN reconstruir únicamente esos Posts en su estado real:
  Review si siguen siendo Drafts, resultado por destino si ya se están publicando o
  programando, o ambos si el conjunto es mixto. NUNCA DEBE inferirse el conjunto ni el
  resultado seleccionando Posts históricos de la Media por heurística. Ids inexistentes o
  que no pertenecen a esa Media/proyecto DEBEN excluirse indicándolo.
- **FR-032**: En Review, el contenido DEBE presentarse como "Content by destination". Los
  destinos con exactamente el mismo valor y la misma procedencia PUEDEN agruparse
  visualmente, pero la UI NUNCA DEBE afirmar ni reconstruir un "common content".
- **FR-033**: La procedencia de cada campo DEBE ser visible cuando sea relevante: "Custom
  text" (override explícito) o "Uses the media's caption" (heredado).
- **FR-034**: `Customize` DEBE editar un único destino. `Edit for these destinations` DEBE
  aplicar un cambio solo a un conjunto elegido explícitamente, mostrando exactamente qué
  destinos se modificarán. NUNCA DEBE inferirse que varios Posts siguen vinculados entre sí.
  DEBE poder volverse explícitamente a `Use the media's caption` en un destino.
- **FR-035**: Tras `Continue`, añadir un destino DEBE crear un nuevo Draft para esa cuenta;
  quitarlo DEBE pedir confirmación y cancelar su Draft (pasa a History como Cancelled); volver
  a añadir, dentro de la misma sesión de la tarea y sin recarga, una cuenta cuyo Draft se quitó
  en esa sesión DEBE reactivar exactamente ese Post con las reglas existentes de Reactivate (al
  ser un Draft sin fecha, vuelve como Draft). Tras una recarga, o si no se conoce un Post
  quitado en esta sesión, NUNCA DEBEN buscarse Posts Cancelled históricos: se crea un Draft
  nuevo con el snapshot actual si las reglas de duplicados lo permiten. Si la cuenta ya tiene
  un Draft activo de esa Media que no está en el Publish set, NO DEBE crearse un segundo Draft:
  se indica que ya existe y se ofrece `Add to this task`, que añade su id al set sin crear ni
  modificar el Post. Cambiar de cuenta equivale a quitar + añadir. NO DEBE introducirse
  borrado, soft-delete ni lote.

#### Platform details

- **FR-036**: Cada destino DEBE mostrar un estado humano: Ready, Details needed, Blocked o
  Checking, con un resumen concreto de lo que falta (p. ej. "TikTok needs 3 details:
  Privacy, AI-generated content and declaration."), nunca "Needs N" sin contexto.
- **FR-037**: Por defecto: Ready plegado; Details needed abierto; Blocked claramente
  explicado; Checking con skeleton/aria-busy. Los campos obligatorios DEBEN mostrarse
  directamente; los secundarios bajo `More options`.
- **FR-038**: Los cambios de opciones de plataforma DEBEN guardarse conforme se editan, con
  estados visibles "Saving…", "Saved" y "Couldn't save · Retry", sin Save general por
  plataforma.
- **FR-039**: El estado de cada destino DEBE derivarse del publish-check existente y de las
  reglas de plataforma existentes; 019 NO DEBE duplicar validaciones de plataforma en el
  frontend.

#### Requisitos por plataforma

- **FR-040 (YouTube)**: Solo vídeo. Obligatorios: "Made for kids?" y "Altered or synthetic
  content?". Otros: personalización de title, privacy y notify subscribers.
- **FR-041 (Instagram)**: Obligatorio: "AI-generated content?". Otros: share to feed cuando
  aplique y alt text en imágenes.
- **FR-042 (Threads)**: Sin requisitos obligatorios adicionales en el caso normal; alt text
  opcional.
- **FR-043 (Telegram)**: Ready cuando la cuenta tiene canal configurado; sin canal, bloqueado
  antes de crear con enlace a completar el setup.
- **FR-044 (TikTok — modo)**: Primero DEBE preguntarse "How should this reach TikTok?" con
  `Post directly` y `Send to my TikTok inbox`.
- **FR-045 (TikTok — Inbox)**: PUEDE quedar Ready cuando la cuenta tiene el permiso
  necesario, explicando "You'll get a TikTok inbox notification to finish the post." NO DEBE
  mostrar opciones exclusivas de Direct Post (014).
- **FR-046 (TikTok — Direct Post)**: DEBE obtener Creator Info mostrando carga, fallo,
  `Retry` y la alternativa `Send to inbox instead`; DEBE configurar privacy, interactions,
  commercial content, AI-generated y declaración con las reglas de 013 (privacidad sin valor
  por defecto, interacciones desactivadas por defecto). Si el cliente actual solo permite
  `SELF_ONLY`, DEBE mostrarse claramente en lugar de simular más opciones.
- **FR-047 (TikTok — declaración única)**: En el nuevo flujo DEBE existir una sola
  declaración TikTok por Post y acción, situada en la card de TikTok, que: empieza sin
  confirmar en cada nueva acción relevante (publicar ahora, programar, armar, reintentar);
  vuelve a quedar sin confirmar si cambia la configuración que representa; representa
  exactamente la configuración visible; y se registra como consentimiento al ejecutar el CTA
  final. NO DEBE pedirse una segunda confirmación en un diálogo posterior (R5). Las acciones de
  Post detail que publican o arman un Post TikTok (Publish now, Retry now, Reschedule, Edit
  schedule —que vuelve a armar, por lo que siempre pide la declaración en Direct Post—,
  Publish automatically) DEBEN presentar igualmente una única declaración en esa acción. La huella y su invalidación siguen 013 FR-025 sin cambios.

#### Acción final (When + CTA)

- **FR-048**: When DEBE ofrecer `Now` (por defecto) y `Schedule`. Con Schedule DEBEN
  mostrarse fecha y hora, la zona horaria y una vista legible de la fecha, junto al texto
  "AutoPublisher will publish these posts automatically at this time."
- **FR-049**: Programar desde Publish DEBE dejar los Posts programados con auto-publish
  armado (R4). Si la automatización global está en pausa DEBE permitirse programar,
  advirtiendo de que no se ejecutarán hasta reanudarla, con enlace a Settings. NO DEBE
  ofrecerse programar sin publicación automática.
- **FR-050**: Review DEBE tener un único CTA primario: `Publish to N destinations` (Now) o
  `Schedule N posts` (Schedule), y una salida terciaria `Finish later`. NO DEBE usarse "Save
  as draft".
- **FR-051**: `Finish later` NO DEBE crear nada, cambiar estados, programar, armar ni
  publicar; DEBE navegar a Posts → Drafts; y antes de salir DEBE terminar de guardar las
  ediciones locales pendientes o, si no pueden guardarse, ofrecer reintentar o descartarlas
  explícitamente.

#### Validación

- **FR-052**: El CTA final DEBE permanecer accionable. Si a algún destino le falta algo, NO
  DEBE publicarse ni programarse ninguno: DEBE mostrarse un error summary que recibe el foco
  y enlaza a cada plataforma/campo problemático; los errores inline DEBEN seguir junto a cada
  campo. Para continuar con menos destinos, el usuario DEBE quitar explícitamente los que
  sobran.

#### Resultado de Schedule

- **FR-052a**: La validación previa de FR-052 es todo o nada: si un destino tiene detalles
  pendientes conocidos, no se programa ninguno. Pero una vez iniciadas las operaciones reales
  de programación (independientes por Post), un destino PUEDE fallar por una carrera o error
  después de que otros hayan quedado programados. En ese caso la UI NO DEBE afirmar que todos
  quedaron programados ni navegar automáticamente a Posts; DEBE mostrar el resultado por
  destino y un resumen agregado (p. ej. "3 scheduled · 1 still a draft"); los ya programados
  DEBEN permanecer Scheduled; el que falló DEBE permanecer en su estado real (normalmente
  Draft) con su motivo y la opción de corregirlo y reintentar. NO DEBE hacerse rollback
  artificial de los ya programados, salvo que el plan demuestre una operación atómica segura.

#### Resultado de Publish now

- **FR-053**: `Publish to N destinations` DEBE iniciar la publicación de cada destino de
  forma independiente con los mecanismos existentes, seguir su progreso y mostrar el
  resultado por destino con estados humanos: Publishing…, Processing, Published, Failed,
  Needs review, Ready in TikTok y Didn't start. Los fallos durante la ejecución PUEDEN ser
  parciales.
- **FR-054**: El resultado DEBE incluir un resumen agregado por resultado (p. ej. "3
  published · 1 failed") y NUNCA DEBE decir "Publish failed" si solo falló una parte. DEBE
  ofrecer `View posts`, `Back to Library` y `Open post` en los destinos con problemas. Salir
  durante la publicación DEBE estar permitido, explicando "Publishing continues in the
  background. Track it in Posts." No hace falta una pantalla de éxito separada.

#### Posts — lista diaria

- **FR-055**: Posts (`/p/:projectId/posts`) DEBE mostrar en su header `Posts`, el selector
  `List | Calendar` y `New post` (con `Publish media…` y `Text post`), y una toolbar mínima con
  búsqueda y selector de cuenta/destino. NO DEBE haber filtro adicional de estado.
- **FR-056**: La sección "Needs you" DEBE incluir los Posts Failed, Needs review, Needs
  action y Missed, y los programados que el read-model existente identifica como con
  detalles incompletos o no verificables dentro del horizonte de 7 días; ordenados por
  gravedad y después por fecha; oculta si está vacía. Un Post DEBE aparecer en una sola
  sección.
- **FR-057**: La sección "Upcoming" DEBE mostrar arriba los Posts publicándose ahora y
  después los programados (automáticos, manuales legacy y en pausa) agrupados por día
  (Today, Tomorrow, fecha).
- **FR-058**: Con la automatización en pausa DEBE mostrarse un único banner de proyecto con
  enlace a Settings, sin repetir el aviso en cada Post.
- **FR-059**: La sección "Drafts" DEBE mostrar los Drafts; oculta si está vacía.
- **FR-060**: History DEBE estar separado de la lista diaria (p. ej. `?view=history`),
  contener solo Published y Cancelled agrupados por mes, con carga inicial limitada en
  cliente y `Show more`. NO DEBE implementarse paginación backend.
- **FR-061**: Las secciones DEBEN derivarse del display state que calcula el backend
  (018 FR-049) y del read-model de readiness existente; el frontend NO DEBE recalcular la
  semántica de estado a partir de estados internos.

#### Posts — filas y selección

- **FR-062**: Cada fila DEBE ser un único enlace a Post detail, sin múltiples botones
  internos, y mostrar: thumbnail o icono de texto, title/caption, plataforma/cuenta, fecha,
  StatusBadge y, en Needs you, una pista de próxima acción. NO DEBE mostrar códigos de
  intento, detalles técnicos ni información exhaustiva.
- **FR-063**: Abrir una fila DEBE actualizar la URL y abrir Post detail en `DetailSurface`
  manteniendo la lista montada; el detail NO DEBE remontarse por cada cambio de estado.

#### Readiness

- **FR-064**: La readiness de Posts programados DEBE reutilizar la evaluación local de solo
  lectura que ya alimenta el overview de 018, con un horizonte de 7 días; dentro de él puede
  mostrarse Needs details, Blocked o Ready. Más allá de 7 días NO DEBE prometerse readiness.
- **FR-065**: NO DEBE ejecutarse la comprobación local indiscriminadamente sobre todos los
  Posts. Un Draft se considera no listo por definición; su readiness detallada solo se evalúa
  en Publish/Review o en su detail.

#### Calendar

- **FR-066**: Calendar DEBE vivir dentro de Posts (`List | Calendar`), ser por proyecto y de
  solo lectura: sin drag & drop, sin creación por hueco, sin resize y sin backend específico
  de calendario.
- **FR-067**: En escritorio con ancho suficiente DEBE mostrar una semana de lunes a domingo
  sin eje vertical de horas, con los Posts de cada día como bloques compactos ordenados por
  hora (los coincidentes se apilan). En tablet y móvil DEBE mostrar una agenda agrupada por
  día.
- **FR-068**: DEBE ofrecer previous, Today, next, el rango de fechas y la zona horaria
  visible. La semana seleccionada DEBE vivir en la URL.
- **FR-069**: DEBE mostrar Scheduled, Publishing, Published, Missed, Failed, Needs review y
  Needs action anclados a su momento relevante según su tipo; NO DEBE mostrar Drafts ni
  Cancelled:
  - Published → momento real de publicación (`published_at`), nunca su `scheduled_at`
    histórico;
  - Scheduled (automatic, manual, paused) → `scheduled_at`;
  - Publishing → la ejecución que realmente está ocurriendo: `scheduled_at` si el intento
    actual lo disparó el scheduler; si se inició manualmente (Publish now), el inicio del
    intento (p. ej. un Post programado para el viernes y publicado a mano el martes aparece el
    martes); si falta, el mejor timestamp operativo existente;
  - Missed → `scheduled_at`;
  - Failed / Needs review → `scheduled_at` cuando represente la ejecución intentada; si no
    existe, momento del último intento;
  - Needs action (TikTok Inbox) → momento de entrega al inbox cuando esté disponible; si no,
    el momento operativo existente más apropiado.
  El plan decide qué campos existentes usa en cada fallback. El estado NO DEBE depender solo
  del color (icono + texto + estilo secundario). Activar un Post DEBE abrir su Post detail.

#### Post detail

- **FR-070**: Post detail DEBE usar `DetailSurface` y presentar, en este orden: header (qué
  Post es y dónde va), panel de estado/acción, When, Content, Platform details, Activity y
  acción destructiva.
- **FR-071**: El panel de estado/acción DEBE estar siempre visible con una frase, una acción
  principal y como mucho una secundaria:

  | Estado visible | Acción principal | Secundaria |
  |---|---|---|
  | Draft con Media | `Continue in Publish` | — |
  | Draft de texto | `Continue setup` | — |
  | Scheduled · automatic | `Edit schedule` | `Publish now` |
  | Scheduled con detalles incompletos (también si está en pausa) | `Complete details` | `Edit schedule` |
  | Scheduled · paused | `Edit schedule` (con la explicación de que Automation está en pausa y no se publicará hasta reanudarla) | `Open Settings` |
  | Scheduled · manual (legacy) | `Publish automatically` (explicando que hoy requiere acción manual) | `Publish now` |
  | Missed | `Reschedule` | `Publish now` |
  | Failed | `Retry now` | `Reschedule` |
  | Needs review | `Check result` (Dialog de FR-073a; incluye `Publish again` tras confirmar que no se publicó) | — |
  | Needs action | `Check status` | — |
  | Published | `Open on [platform]` | — |
  | Cancelled | `Reactivate` | — |

  `Move to drafts` de un Failed (FR-073) PUEDE ofrecerse como acción terciaria. Si un Post
  en pausa tiene además detalles incompletos conocidos, prevalece la necesidad específica
  del Post (`Complete details`); la pausa sigue comunicándose como contexto (frase y banner
  de proyecto), sin crear nuevos display states.
- **FR-072**: `Edit schedule` y `Reschedule` DEBEN dejar el Post con publicación automática
  armada (R4), con las mismas reglas de fecha futura, disponibilidad y consentimiento TikTok
  existentes.

#### Reprogramación de Failed (cambio funcional backend aceptado)

- **FR-073**: Un Post Failed DEBE poder `Retry now`, `Reschedule` (a fecha futura, armado) o
  `Move to drafts` únicamente si su último intento NO tiene resultado incierto. Si necesita
  revisión, estas acciones DEBEN rechazarse con "Check the result first." El historial de
  intentos DEBE conservarse. NO DEBE exigirse Cancel → Reactivate → Schedule.
- **FR-073a**: "Check the result first." significa que Retry directo, Reschedule y Move to
  drafts NO pueden ejecutarse **mientras siga existiendo incertidumbre**; no deja el Post sin
  salida. El Dialog `Check result` DEBE conservar la vía existente de 006 FR-041:
  (1) intentar comprobar/reconciliar el resultado cuando la plataforma lo permita;
  (2) si sigue incierto, permitir que el usuario confirme explícitamente que ha comprobado la
  plataforma y que el Post no se publicó; (3) solo tras esa confirmación, ofrecer
  `Publish again` usando el mecanismo existente `confirm_remote_checked`, que crea un intento
  nuevo con confirmación y preflight. Si la comprobación resuelve el resultado, deja de
  aplicar el bloqueo: Published si se publicó, o Failed determinado con las acciones de
  FR-073. Esto NO introduce lifecycle nuevo; Reschedule y Move to drafts siguen bloqueados
  mientras el resultado sea incierto, también después de confirmar.

#### Published como historial

- **FR-074**: Para Posts Published, Content DEBE mostrar prioritariamente el contenido
  realmente enviado registrado en el último intento cuando exista. El contenido efectivo
  actual PUEDE mostrarse solo como información secundaria. Si no hay contenido enviado
  registrado, DEBE indicarse que lo mostrado es el contenido actual.

#### Platform details y Activity en Post detail

- **FR-075**: Platform details DEBE aparecer plegado si el Post está Ready o Published, y
  abierto y accionable si falta algo, con el mismo autosave de FR-038; no DEBE dominar el
  detail.
- **FR-076**: Activity DEBE estar plegado y mostrar primero eventos en lenguaje humano. Códigos
  de error, ids de intento, rutas técnicas y checksums solo DEBEN aparecer bajo un segundo
  disclosure "Technical details".

#### Cancel

- **FR-077**: `Cancel post` DEBE ser una acción de peligro secundaria con confirmación en
  Dialog que explique que puede reactivarse. Los Posts NUNCA DEBEN eliminarse.
- **FR-078**: `Reactivate` DEBE mantener exactamente las reglas existentes (duplicados,
  disponibilidad, estado resultante y nunca rearmar auto-publish, 007 FR-017); 019 no cambia
  su semántica.

#### Text-only Posts

- **FR-079**: La entrada DEBE ser `Posts → New post → Text post`, en la ruta conceptual
  `/p/:projectId/posts/new`; NO DEBE ofrecerse desde Library.
- **FR-080**: El modo texto DEBE reutilizar el modelo Compose → Review: sin Media, texto
  obligatorio, destinos compatibles con solo texto y los incompatibles visibles deshabilitados
  con "Needs media". `Continue` DEBE usar la capacidad existente de creación de text posts.
- **FR-081**: Review, When, readiness, validación y resultado DEBEN comportarse igual que en
  Publish con Media, incluida la identidad estable del Publish set ante recarga (FR-031a).
  Los Text drafts DEBEN poder reanudarse con una URL enlazable, sin crear
  una entidad de lote.

#### Read-model de uso de Media

- **FR-082**: El resumen de uso por Media DEBE ampliarse de forma pequeña para que las cards
  de Library puedan pintarse sin cargar todos los Posts: número de Drafts, número de Posts que
  requieren atención y próxima hora programada.
- **FR-083**: El recuento de atención DEBE basarse en el significado de producto (display
  state): Failed, Needs review, Needs action y Missed, no en estados internos.
- **FR-084**: Las filas de Usage de Media detail DEBEN incluir el display state calculado por
  el backend para que el frontend no recalcule la semántica.
- **FR-085**: Estas ampliaciones NO DEBEN modificar datos ni hacer llamadas remotas.

#### Responsive

- **FR-086 (375 px)**: Library a 2 columnas; Media y Post detail a pantalla completa; filas de
  Posts a ancho completo; Calendar como agenda; acciones de página mediante `PageActions`;
  objetivos táctiles ≥ 44 px. La bottom navigation DEBE mantenerse en superficies de consulta
  (Media/Post detail) y ocultarse en el task mode de Publish.
- **FR-087 (768 px)**: navigation rail; Library ~4 columnas; details generalmente en Drawer;
  Posts en una columna; Calendar como agenda.
- **FR-088 (escritorio)**: sidebar; `DetailSurface` lateral cuando no perjudique a la
  superficie principal; Calendar semanal; Library más densa (5–6 columnas sin detail
  abierto).
- **FR-089**: En el rango aproximado 1024–1279 px, Posts PUEDE usar panel lateral; Library y
  Calendar DEBEN preferir Drawer si el panel reduce demasiado su legibilidad. Cada página
  DEBE poder declarar su preferencia; no se aplica una estrategia única a todas.
- **FR-090**: Cero scroll horizontal del documento en todas las rutas de 019 a 375 px, 768 px
  y escritorio.

#### Visual

- **FR-091**: Las superficies de 019 DEBEN migrar fuera del CSS legacy a los tokens y
  convenciones de 018: superficies planas, bordes sutiles, un acento, jerarquía clara,
  densidad media, previews donde aporten, estados seleccionados fuertes, hover/focus
  pulidos y ritmo de espaciado claro. NO DEBEN usarse gradients, glass, dashboards
  decorativos, metric cards grandes, sombras excesivas ni animación decorativa.

#### Accesibilidad

- **FR-092**: Todas las superficies de 019 DEBEN tener URL/deep linking, navegación por
  teclado completa, foco visible, devolución del foco al cerrar details y dialogs, objetivos
  táctiles ≥ 44 px, estado como icono + texto (nunca solo color), Skeleton / aria-busy en
  carga, ErrorState con Retry, error summaries accesibles, Dialog/Drawer/Sheet reales,
  confirmaciones para acciones destructivas, acciones sticky que nunca tapan el elemento con
  foco y soporte de reduced motion.
- **FR-093**: El grid de Library PUEDE usar semántica de lista. Calendar NO DEBE usar
  `role=grid`; DEBE usar estructura semántica de listas por día.
- **FR-094**: Contraste WCAG 2.1 AA (018 FR-056).

#### Design system

- **FR-095**: 019 PUEDE añadir como máximo extensiones pequeñas al sistema de 018: `Field`,
  `ChoiceGroup` (incluida variante horizontal / view switch), `PageActions`, una opción de
  ruta para ocultar la bottom navigation en móvil y mejoras de `DetailSurface` (scroll
  propio, área de acciones sticky y preferencia de Drawer por página). NO DEBEN crearse
  Stepper genérico, sistema de Toast, componente Table, componentes de dashboard ni
  DateTimePicker propio, salvo necesidad técnica imprescindible justificada en el plan.

### Key Entities *(include if feature involves data)*

Sin entidades persistentes nuevas.

- **Post** (existente: `Publication`): unidad persistente y de ejecución. 019 añade una
  transición desde Failed sin resultado incierto hacia Scheduled (armado) o Draft (R6). Sus
  overrides almacenan el snapshot de contenido de los drafts nuevos (R1).
- **Post display state** (existente, 018): estado visible calculado por el backend; base de
  las secciones de Posts, Usage, Calendar y del panel de Post detail.
- **Media** (existente: `Content`): entrada de Publish; su metadata se hereda solo en los
  Posts sin override.
- **Media usage summary** (existente, ampliado): por Media, recuentos de uso más número de
  Drafts, número de Posts en atención y próxima hora programada (FR-082).
- **Publish set** (concepto, no entidad): los Posts que Review presenta juntos (los Drafts
  activos de una Media al reanudar, o los creados por `Continue`, incluidos Text posts); se
  identifica por los ids de sus Posts en la URL u otro mecanismo sin persistencia (FR-031a).
- **Attempt submitted content** (existente): contenido enviado registrado en el intento; base
  de FR-074.
- **Destination preset** (existente, 017): sin cambios de modelo.
- **TikTok consent** (existente, 013): sin cambios de huella; cambia solo dónde y cuántas
  veces se presenta la declaración (R5).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (First use completo)**: con la configuración de plataforma preparada, una persona
  nueva completa `create project → connect account → import media → Publish… → configure
  destinations → schedule/publish` sin documentación, siguiendo solo las acciones
  principales.
- **SC-002 (Journeys)**: los journeys A–F (Library → Media → Publish → Schedule → Posts;
  Posts → Draft → Continue in Publish → Finish setup; Posts → Failed → Post detail →
  Reschedule; Calendar → Scheduled Post → Post detail; Media detail → Usage → Published
  Post; Posts → New post → Text post → Publish/Schedule) se completan correctamente a
  375 px, 768 px y escritorio.
- **SC-003 (Eficiencia)**: publicar o programar una Media en 3 destinos con detalles
  obligatorios ya conocidos requiere un único `Continue` y un único CTA final, en menos de 2
  minutos.
- **SC-004 (Fidelidad)**: el 100 % de los drafts creados por el nuevo flujo muestran en Resume
  exactamente el contenido confirmado en Continue, aunque la Media se edite después.
- **SC-005 (Seguridad de ejecución)**: 0 publicaciones o programaciones parciales por elección
  previa: si un destino no está listo al pulsar el CTA final, no se inicia ninguno.
- **SC-006 (Atención)**: el 100 % de los Posts Failed, Needs review, Needs action y Missed
  aparecen en Posts → Needs you y cuentan en el indicador de atención de su Media.
- **SC-007 (Claridad)**: en Posts, desde la carga, el usuario identifica en 5 segundos o menos
  qué Posts le necesitan y cuál es el siguiente programado.
- **SC-008 (Recovery)**: el 100 % de los Post detail muestran una acción principal coherente con
  su estado; un Failed sin incertidumbre se reprograma sin cancelar ni reactivar.
- **SC-009 (TikTok)**: cada acción que publica o arma un Post TikTok en las superficies de 019
  presenta exactamente una declaración, y 0 ejecuciones ocurren sin consentimiento vigente.
- **SC-010 (Historial)**: el 100 % de los Posts Published con contenido enviado registrado
  muestran ese contenido como principal.
- **SC-011 (Responsive/Accesibilidad)**: cero scroll horizontal a 375 px en todas las rutas de
  019; todas las superficies operables solo con teclado, con foco visible, contraste AA y
  objetivos táctiles ≥ 44 px.
- **SC-012 (No regresión)**: importar, crear drafts multi-destino, presets, opciones de
  plataforma, Publish now, auto-publish, pausa, consentimiento TikTok, cancelar y reactivar
  siguen funcionando; los Posts legacy (manuales, drafts heredando de la Media) siguen siendo
  compatibles.

## Out of Scope

- **Feature 020**: deployment, autenticación, LAN, HTTPS, PWA, push notifications, servicio en
  background y backups.
- Republish / plantillas de republicación.
- Calendar editable, drag & drop, creación por hueco, resize y calendario global entre
  proyectos.
- Analytics y dashboards.
- Gestión masiva de Posts (bulk management) fuera del CTA único de Publish.
- Paginación backend.
- Sorting en Library.
- Pipeline de generación de thumbnails.
- Borrado de Posts.
- Readiness exhaustiva de todos los Drafts o de Scheduled a más de 7 días.
- Entidad de lote/batch/"common content".
- Nuevas integraciones de plataforma o cambios en publishers y scheduler; los únicos cambios
  de lifecycle es R6 (Failed).
- Crear programaciones manuales nuevas desde la UI.

## Assumptions

- **Breakpoints**: los de 018 (móvil < 768 px, tablet 768–1023 px, escritorio ≥ 1024 px);
  el plan decide el umbral exacto a partir del cual Calendar muestra la semana y cada página
  prefiere Drawer o panel.
- **Zona horaria**: la local del navegador, visible donde se elige o muestra una fecha.
- **Semana**: lunes a domingo.
- **"Not used yet"**: Media sin Posts salvo Cancelled.
- **Momento relevante en Calendar**: según el tipo de Post (FR-069); en particular un
  Published se ancla siempre a su momento real de publicación, no a su hora programada.
- **Recuento de atención por Media**: basado en display state (Failed, Needs review, Needs
  action, Missed); los programados con detalles incompletos cuentan como Scheduled en la card
  y aparecen en Needs you de Posts. El plan puede incluirlos si el coste es bajo, sin
  contradecir Posts.
- **Bloqueo por Posts activos**: las cuentas con un Post activo no Draft de la Media aparecen
  bloqueadas en Destinations con enlace al Post; los Drafts forman parte de Resume.
- **Resume de Text drafts**: el mecanismo concreto (ids en URL u otro) se decide en el plan,
  preservando deep linking.
- **Ejecución de Publish now multi-destino**: el plan decide cómo iniciar y seguir cada
  destino reutilizando el servicio existente de Publish now; no se añade un endpoint de lote
  salvo necesidad justificada.
- **Snapshot de Media sin caption**: el snapshot de un campo vacío se guarda como override
  vacío explícito, con la semántica existente (vacío ≠ heredar).
- **Escala**: volúmenes de un usuario individual (miles de Posts); la carga en cliente de
  History limitada con `Show more` es suficiente.
- **Single user, local**: se mantiene el modelo de la Constitution.
