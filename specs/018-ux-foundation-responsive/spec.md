# Feature Specification: UX Foundation & Responsive App

**Feature Branch**: `018-ux-foundation-responsive`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "Feature 018 — UX Foundation & Responsive App. Establecer la nueva arquitectura UX de AutoPublisher: information architecture (Home y Settings globales; Library, Posts y Accounts por proyecto), routing real con URLs persistentes y deep links, app shell responsive (sidebar / navigation rail / bottom navigation), Home orientada a atención, read-models backend de solo lectura (atención, salud de cuentas, disponibilidad de configuración de plataformas), franja de estado del proyecto, rediseño de Accounts con flujo `Add account → choose platform → Connect`, Settings global (automatización y configuración de plataformas), onboarding mediante empty states encadenados, transición de terminología visible, sistema de estados que dice qué va a ocurrir, design system propio con primitivas base, patrón común de navegación de detalles y accesibilidad. Sin rediseño profundo de Library, Publish/Distribute, Posts ni Post detail (Feature 019). Sin dark mode, deployment, LAN, autenticación, PWA, keyring headless, backup, Republish ni bulk actions."

## Contexto

AutoPublisher ya cubre el ciclo completo: proyectos, cuentas conectadas a seis integraciones
(YouTube, Instagram, Threads, TikTok —Direct Post e Inbox— y Telegram), biblioteca de
contenidos con metadata, publicaciones programadas o inmediatas, distribución multiplataforma
con presets (Feature 017) y un scheduler local con consentimiento explícito de
auto-publicación y pausa global.

La interfaz, sin embargo, creció feature a feature:

- no hay URLs: recargar la página o usar "atrás" pierde el contexto; no se puede enlazar a un
  post o a un medio concretos;
- no existe un lugar que responda "¿hay algo roto y qué pasa después?": los fallos, las
  publicaciones que esperan acción del usuario, las vencidas, las revisiones manuales y las
  cuentas que requieren reconexión están repartidas entre proyectos y pantallas;
- la gestión de cuentas pide escribir a mano una identidad (handle) que después se obtiene de
  la conexión, mezcla detalles técnicos (scopes, IDs) con el estado principal y muestra
  plataformas sin integración (X) como si fueran conectables;
- el control global de automatización vive dentro de la cola de un proyecto;
- la terminología expone conceptos internos (`Publication`, `Asset`, `Queue`, `Prepare`,
  `Unscheduled`, `preflight`, `reconcile`, `attempt`, `checksum`);
- no hay un sistema visual coherente ni una adaptación real a móvil o tablet.

Feature 018 establece la **foundation**: navegación, URLs, shell responsive, design system,
lenguaje de estados, read-models de atención y salud, Home, Accounts, Settings y onboarding.
Feature 019 rediseñará en profundidad Library, Media detail, Publish, Posts (List/Calendar) y
Post detail sobre esta base, sin rehacer navegación, estados, responsive ni componentes base.

### Principio rector

> The interface of an application is like a joke: if you have to explain it, it is not good.

Una persona nueva debe poder usar AutoPublisher sin formación previa. Prioridad de decisión,
en este orden: claridad, simplicidad, jerarquía, feedback, prevención de errores, velocidad,
accesibilidad responsive, estética.

## Clarifications

### Session 2026-10-16

- Q: ¿El detalle de cuenta tiene URL propia? → A: Sí, `/p/:projectId/accounts/:accountId`, con deep link, reload, back/forward y verificación de pertenencia al proyecto (not found si no pertenece); respalda el patrón de detalle.
- Q: ¿A dónde enlaza "N need attention" de la franja? → A: `/?project=<projectId>`: Home con "Needs attention" filtrado temporalmente; sin query, Home es global. No hay Project Overview.
- Q: ¿Cuál es la landing de un proyecto? → A: `/p/:projectId/library`.
- Q: ¿"Up next" necesita "See more"? → A: No. Hasta 5 posts globales, cada uno enlazando a su post; no hay Posts global.
- Q: ¿`ui-ux-pro-max-skill` es requisito funcional? → A: No; es guía de proceso (sección "Design process / implementation guidance"), sin vendorizar código de terceros salvo aprobación en el plan.
- Q: ¿Qué valida el criterio de primer uso en 018? → A: Hasta "identify and reach Publish…"; el journey completo con Publish se valida en 019.

### Session 2026-10-16 (aprobación del plan)

- Q: ¿Cómo se crea una cuenta sin identidad conocida? → A: `handle`/`handle_key` pasan a ser opcionales (migración `0017`); el alta puede enviar solo la plataforma; tras una conexión correcta se adopta la identidad conectada; nunca se sobrescriben handles existentes.
- Q: ¿Qué pasa con un alta abandonada? → A: Se puede descartar con una operación restringida que solo borra cuentas provisionales (sin identidad adoptada, sin conexión, sin posts); no es un borrado general de cuentas (FR-039a).
- Q: ¿Cómo se muestra una conexión válida pero incompleta (Telegram sin canal)? → A: Quinto estado de cuenta "Finish setup" (`setup_required`), distinto de "Reconnect needed".
- Q: ¿Estados de post adicionales? → A: "Needs review" (resultado incierto) y "Scheduled · paused" (automático con la automatización global en pausa: no se ejecutará mientras siga así).
- Q: ¿Generan atención los proyectos inactivos? → A: Solo por problemas ya existentes (manual review, failed, needs action); nunca por reconexión, caducidad, requisitos de próximos posts ni planificación futura.
- Q: ¿Y si no se pueden verificar los requisitos de un post próximo (keyring/configuración local no disponible)? → A: Se trata como requisitos incompletos con el mensaje "Couldn't verify requirements" y enlace al post; nunca se considera listo ni se oculta.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Saber en segundos qué necesita atención (Priority: P1)

Como usuario diario abro AutoPublisher y la pantalla inicial (Home) me dice, sin buscar, si
hay algo que requiere mi acción en cualquier proyecto, qué es exactamente, qué hacer y cuál
es la siguiente publicación. Cada problema tiene una única acción principal que me lleva
directamente al lugar donde se resuelve.

**Why this priority**: es la razón de ser de la nueva arquitectura. Un fallo silencioso o
una publicación que espera al usuario sin que este lo sepa es el fallo más grave de la
aplicación (Constitution V). La Home convierte datos ya existentes en acción.

**Independent Test**: con datos de prueba que incluyan una publicación fallida, una en
espera de acción del usuario, una vencida, una con revisión manual pendiente y una cuenta
que requiere reconexión, abrir Home y comprobar que aparecen todas en "Needs attention", con
problema, contexto, una acción principal y un enlace que abre la pantalla correcta. Con
datos sin problemas, comprobar el estado "Everything OK" con la próxima publicación.

**Acceptance Scenarios**:

1. **Given** una publicación fallida en el proyecto A, **When** abro Home, **Then** veo un
   elemento en "Needs attention" que indica el problema ("Failed"), el contexto (proyecto,
   cuenta/plataforma, medio o texto, momento) y una acción principal ("Check status" o
   equivalente) cuyo destino es la URL de ese post.
2. **Given** una publicación de TikTok Inbox entregada que espera que el usuario termine el
   post en la plataforma, **When** abro Home, **Then** aparece como "Needs action" con la
   acción principal correspondiente y deep link al post.
3. **Given** una publicación programada automática cuya hora ya pasó sin ejecutarse,
   **When** abro Home, **Then** aparece como vencida ("Missed") con una acción principal
   ("Publish now" o "Reschedule") que lleva al post.
4. **Given** una publicación cuyo último intento terminó en un estado incierto que requiere
   revisión manual, **When** abro Home, **Then** aparece con la acción "Review" y deep link
   al post.
5. **Given** una cuenta con estado de reconexión requerida, **When** abro Home, **Then**
   aparece con la acción "Reconnect" y deep link a esa cuenta en Accounts.
6. **Given** una cuenta cuya credencial caduca en los próximos días, **When** abro Home,
   **Then** aparece un aviso de caducidad próxima con acción "Reconnect".
7. **Given** una publicación programada próxima a la que le faltan requisitos para poder
   publicarse (según comprobación local), **When** abro Home, **Then** aparece con la
   acción "Complete" y deep link al post.
8. **Given** que no hay ningún problema, **When** abro Home, **Then** veo un estado
   positivo explícito y la próxima publicación programada (o, si no hay ninguna, que no hay
   publicaciones programadas).
9. **Given** publicaciones programadas futuras, **When** abro Home, **Then** la sección
   "Up next" muestra hasta 5 de forma compacta en orden cronológico, indicando para cada una
   si se publicará automáticamente o requiere acción manual, y cada una enlaza a su post.
10. **Given** varios proyectos, **When** abro Home, **Then** la sección "Projects" los lista
    de forma compacta con un indicador de atención por proyecto que enlaza a ese proyecto.
11. **Given** una pantalla de 375 px de ancho, **When** abro Home, **Then** "Needs attention"
    es lo primero visible, cada elemento muestra problema y acción principal sin scroll
    horizontal.

---

### User Story 2 - Navegar con URLs persistentes en cualquier dispositivo (Priority: P1)

Como usuario navego entre Home, Settings y las secciones de cada proyecto (Library, Posts,
Accounts) mediante una navegación adaptada a mi dispositivo, y cada sección, medio y post
tiene una URL propia que sobrevive a una recarga, funciona con atrás/adelante del navegador
y puede abrirse directamente.

**Why this priority**: sin URLs persistentes no existen deep links desde Home, y sin shell
responsive la aplicación no es utilizable fuera del escritorio. Es la base sobre la que se
apoya todo lo demás de 018 y todo 019.

**Independent Test**: abrir directamente cada URL de la tabla de rutas, recargar, navegar
adelante y atrás, y comprobar que se muestra el contenido correcto; repetir a 375 px,
tablet y escritorio comprobando el tipo de navegación y la ausencia de scroll horizontal.

**Acceptance Scenarios**:

1. **Given** la URL de la Library de un proyecto, **When** recargo la página, **Then** sigo
   en la Library de ese proyecto con el proyecto seleccionado.
2. **Given** que navego Home → Posts del proyecto A → un post, **When** pulso "atrás" dos
   veces en el navegador, **Then** vuelvo a Posts y después a Home; "adelante" rehace el
   recorrido.
3. **Given** la URL de un post concreto copiada en otra pestaña, **When** la abro, **Then**
   se muestra ese post dentro del contexto de su proyecto.
4. **Given** la URL de un medio concreto de la Library, **When** la abro, **Then** se
   muestra ese medio dentro del contexto de su proyecto.
5. **Given** una URL con un proyecto, medio, post o cuenta inexistente (o de otro proyecto),
   **When** la abro, **Then** veo un estado de error claro ("not found") con una única
   acción para volver a un lugar válido, nunca una pantalla en blanco.
6. **Given** un ancho de escritorio, **When** uso la app, **Then** veo una sidebar con Home,
   selector de proyecto, Library, Posts, Accounts y Settings.
7. **Given** un ancho de tablet, **When** uso la app, **Then** veo una navigation rail
   compacta con los mismos destinos.
8. **Given** un ancho de móvil (~375 px), **When** uso la app, **Then** veo una bottom
   navigation con Home, Library, Posts y Accounts, el selector de proyecto en la parte
   superior y Settings en un menú secundario; no aparece una sidebar comprimida.
9. **Given** que cambio de proyecto con el selector estando en Posts, **When** selecciono
   otro proyecto, **Then** paso a Posts del nuevo proyecto y la URL lo refleja.
10. **Given** que estoy en Home o Settings (globales) sin proyecto en la URL, **When** pulso
    Library, Posts o Accounts, **Then** se abre la sección del último proyecto usado o, si
    no lo hay, del primer proyecto disponible; si no hay proyectos, el empty state de
    creación de proyecto.
11. **Given** que pulso un proyecto como destino genérico (p. ej. en "Projects" de Home),
    **When** navego, **Then** se abre su Library (`/p/:projectId/library`).
12. **Given** la URL de detalle de una cuenta, **When** la abro directamente o recargo,
    **Then** se muestra el detalle de esa cuenta (drawer/panel en escritorio, overlay drawer
    en tablet, pantalla completa con "Back" en móvil); si la cuenta no pertenece al
    proyecto, se muestra "not found".

---

### User Story 3 - Conectar cuentas y ver su salud sin ruido técnico (Priority: P1)

Como usuario añado una cuenta eligiendo primero la plataforma y conectando directamente; la
identidad se obtiene de la conexión. En la lista de cuentas veo de un vistazo, para cada
una, plataforma, identidad conectada, estado (Ready / Reconnect needed / Finish setup /
Not connected / Inactive), qué puede hacer, el problema si lo hay y un aviso si caduca pronto. Los detalles
técnicos están disponibles pero plegados.

**Why this priority**: conectar una cuenta es el segundo paso del onboarding y la fuente de
gran parte de los problemas de atención. Depende directamente del read-model de salud de
cuentas.

**Independent Test**: con la configuración de una plataforma disponible, completar
`Add account → choose platform → Connect` sin escribir manualmente la identidad y comprobar
que la cuenta aparece como Ready con su identidad real; con cuentas en distintos estados,
comprobar estado, capacidades, problema y aviso de caducidad, y que scopes/IDs/Test
connection/Disconnect solo aparecen al desplegar los detalles.

**Acceptance Scenarios**:

1. **Given** un proyecto, **When** pulso "Add account", **Then** se me pide primero elegir
   plataforma, no escribir un handle.
2. **Given** que elijo una plataforma con integración funcional y configuración local
   disponible, **When** pulso "Connect" y completo el flujo de la plataforma, **Then** la
   cuenta queda creada y conectada mostrando la identidad obtenida de la plataforma.
3. **Given** que elijo una plataforma con integración funcional pero sin configuración
   local disponible, **When** la selecciono, **Then** se me explica que falta configuración
   y se me ofrece una única acción que lleva a Settings; no se inicia un flujo que fallará.
4. **Given** plataformas sin integración funcional (p. ej. X), **When** abro el selector de
   plataforma, **Then** aparecen claramente como "Coming soon" y no son seleccionables, u
   ocultas; nunca parecen conectables.
5. **Given** una cuenta conectada sin problemas, **When** veo Accounts, **Then** muestra
   plataforma, identidad, estado "Ready" y capacidades en lenguaje de producto.
6. **Given** una cuenta con reconexión requerida, **When** veo Accounts, **Then** muestra
   "Reconnect needed", el problema en lenguaje claro y una acción principal "Reconnect".
7. **Given** una cuenta cuya credencial caduca pronto, **When** veo Accounts, **Then**
   muestra un aviso de caducidad con la fecha relativa y la acción "Reconnect".
8. **Given** una cuenta desactivada, **When** veo Accounts, **Then** aparece como
   "Inactive", visualmente secundaria respecto a las activas.
9. **Given** cualquier cuenta, **When** despliego sus detalles, **Then** puedo ver scopes,
   IDs, ejecutar "Test connection" y "Disconnect"; plegados, no se muestran.
10. **Given** cuentas legadas creadas con el flujo anterior y aún no conectadas, **When**
    veo Accounts, **Then** aparecen como "Not connected" con una acción principal "Connect".
11. **Given** una cuenta con conexión válida pero incompleta para publicar (p. ej. Telegram
    conectado sin canal seleccionado), **When** veo Accounts, **Then** aparece como "Finish
    setup" con una acción principal que completa la configuración; no aparece como
    "Reconnect needed" ni como "Ready".
12. **Given** que empiezo "Add account" y abandono el flujo antes de completar la conexión,
    **When** cancelo, **Then** la cuenta provisional se descarta y no queda ninguna cuenta
    "Not connected" residual; **Given** una cuenta con posts o con conexión, **Then** no se
    ofrece descartarla (solo desactivarla).

---

### User Story 4 - Empezar desde cero sin documentación (Priority: P2)

Como persona nueva, con la configuración de plataforma ya preparada, la aplicación me guía
mediante estados vacíos encadenados por el camino
`create project → connect account → import media → identify and reach Publish…`,
cada uno con exactamente una acción principal, y una checklist compacta de progreso mientras
el proyecto está incompleto.

**Why this priority**: es el criterio de éxito de primer uso; depende de navegación (US2) y
Accounts (US3).

**Independent Test**: partir de una base de datos vacía y completar el recorrido hasta tener
un medio listo para publicar siguiendo solo las acciones principales de cada empty state;
comprobar que cada empty state tiene exactamente una acción principal y que la checklist
desaparece al completar el proyecto.

**Acceptance Scenarios**:

1. **Given** que no hay proyectos, **When** abro la app, **Then** veo un único CTA principal
   "Create your first project".
2. **Given** un proyecto sin cuentas, **When** abro el proyecto, **Then** el empty state
   principal propone "Connect an account".
3. **Given** un proyecto con cuentas pero sin medios, **When** abro Library, **Then** el
   empty state propone "Import your first media".
4. **Given** medios que aún no se han usado en ningún post, **When** veo la Library, **Then**
   la acción "Publish…" es evidente en esos medios.
5. **Given** un proyecto incompleto (sin cuenta lista, sin medios o sin ningún post), **When**
   estoy en su contexto, **Then** veo una checklist compacta con los pasos completados y el
   siguiente; **Given** un proyecto completo, **Then** la checklist no aparece.
6. **Given** cualquier empty state de la aplicación, **When** lo veo, **Then** tiene
   exactamente una acción principal (puede haber como mucho enlaces secundarios).

---

### User Story 5 - Ver el estado del proyecto en una línea (Priority: P2)

Como usuario, dentro de cualquier sección de un proyecto, veo una franja compacta con el
estado del proyecto, equivalente a `3/4 accounts ready · 2 need attention · Next: tomorrow
10:00`, donde cada elemento enlaza al lugar correspondiente.

**Why this priority**: sustituye una página "Project Overview" (descartada) dando contexto
permanente sin duplicar la Home.

**Independent Test**: con un proyecto con cuentas en distintos estados, problemas y
programaciones, comprobar los tres valores de la franja y que cada uno navega al lugar
correcto.

**Acceptance Scenarios**:

1. **Given** un proyecto con 4 cuentas activas de las que 3 están Ready, **When** veo la
   franja, **Then** indica "3/4 accounts ready" y enlaza a Accounts.
2. **Given** 2 elementos de atención en el proyecto, **When** veo la franja, **Then** indica
   "2 need attention" y enlaza a `/?project=<projectId>` (Home con la atención filtrada a ese
   proyecto).
3. **Given** una próxima publicación programada, **When** veo la franja, **Then** indica
   "Next:" con fecha relativa legible y enlaza a ese post.
4. **Given** sin problemas ni programaciones, **When** veo la franja, **Then** omite los
   elementos vacíos o los muestra en estado neutro, sin ceros alarmantes.
5. **Given** 375 px, **When** veo la franja, **Then** cabe sin scroll horizontal (puede
   abreviarse o partirse en líneas).

---

### User Story 6 - Settings global: automatización y configuración de plataformas (Priority: P2)

Como usuario tengo una pantalla Settings global donde veo y cambio el estado global de la
automatización (activa / en pausa) y compruebo qué plataformas tienen disponible la
configuración local necesaria para conectarse, sin que se muestre ningún secreto.

**Why this priority**: la pausa global no pertenece a la cola de un proyecto, y la ausencia
de configuración es la primera causa de un onboarding bloqueado.

**Independent Test**: pausar y reanudar la automatización desde Settings y comprobar que el
cambio se refleja en el comportamiento existente; retirar la configuración de una plataforma
y comprobar que Settings lo indica y que Accounts no ofrece conectar esa plataforma.

**Acceptance Scenarios**:

1. **Given** la automatización activa, **When** la pauso desde Settings, **Then** queda en
   pausa globalmente con el mismo efecto que el control actual, y Settings lo indica.
2. **Given** la automatización en pausa, **When** veo Home o Posts, **Then** se indica que
   las publicaciones automáticas no se ejecutarán y se enlaza a Settings para reanudar.
3. **Given** la vista Posts de un proyecto, **When** la abro, **Then** ya no contiene el
   control global de pausa (como mucho, un indicador enlazado a Settings).
4. **Given** una plataforma cuya configuración local falta o no es válida, **When** veo
   Settings, **Then** se indica "Not configured" con una explicación breve de qué falta, sin
   mostrar rutas con secretos, contenidos de ficheros, tokens ni credenciales.
5. **Given** una plataforma configurada, **When** veo Settings, **Then** se indica
   "Configured".

---

### User Story 7 - Estados que dicen qué va a ocurrir y lenguaje de producto (Priority: P3)

Como usuario, cada estado visible de un post me dice qué va a ocurrir (p. ej. "Scheduled ·
automatic" frente a "Scheduled · manual"), y la aplicación usa términos de producto (Post,
Media, Library, Posts, Draft) en lugar de términos internos.

**Why this priority**: establece el vocabulario y los componentes que 019 usará en
profundidad; en 018 se aplica en las pantallas nuevas y en los lugares visibles del shell.

**Independent Test**: revisar Home, Accounts, Settings, navegación, empty states y la franja
de estado comprobando que no aparecen términos internos como lenguaje principal y que los
estados de post usan el sistema de estados definido.

**Acceptance Scenarios**:

1. **Given** un post programado con auto-publicación armada, **When** se muestra su estado,
   **Then** es "Scheduled · automatic"; sin ella, "Scheduled · manual"; si está armado pero
   la automatización global está en pausa, "Scheduled · paused"; nunca "Scheduled" a secas.
5. **Given** un post cuyo último intento terminó con resultado incierto, **When** se muestra
   su estado, **Then** es "Needs review" y comunica que hay que comprobarlo en la plataforma
   antes de reintentar.
2. **Given** un post sin fecha, **When** se muestra su estado, **Then** es "Draft".
3. **Given** las pantallas nuevas o rehechas por 018, **When** las recorro, **Then** no
   aparecen como lenguaje principal "preflight", "reconcile", "attempt", "checksum",
   "Publication", "Asset", "Asset Library", "Queue", "Prepare" ni "Unscheduled".
4. **Given** las etiquetas de navegación, **When** las veo, **Then** son Home, Library,
   Posts, Accounts y Settings.

---

### Edge Cases

- **Proyecto eliminado o inexistente en la URL**: estado "not found" con una acción para
  volver a Home; si era el último proyecto usado, se olvida.
- **Medio o post de otro proyecto en la URL**: se trata como no encontrado en ese proyecto
  (no se cambia de proyecto silenciosamente).
- **Un mismo post con varios problemas** (p. ej. vencido y con requisitos incompletos):
  aparece una sola vez en "Needs attention", con el problema más prioritario y su acción.
- **Muchos elementos de atención**: la Home muestra primero los más prioritarios y permite
  ver el resto sin perder el orden; nunca se ocultan sin indicarlo.
- **Cuenta inactiva con problemas**: no genera elementos de atención de reconexión ni de
  caducidad (está fuera de uso), pero sus posts fallidos, con revisión manual o que esperan
  acción siguen apareciendo; sus posts programados próximos aparecen como requisitos
  incompletos (la cuenta inactiva impide publicarlos).
- **Proyecto inactivo**: solo genera atención por problemas ya existentes (revisión manual,
  fallidos, acción del usuario pendiente); nunca por reconexión, caducidad, requisitos de
  próximos posts ni planificación futura. Sus posts no aparecen en "Up next".
- **Requisitos no verificables**: si la comprobación local de un post próximo no puede
  completarse (p. ej. almacén seguro o configuración local no disponibles), el post aparece
  como requisitos incompletos con "Couldn't verify requirements" y enlace al post; nunca se
  da por listo ni se oculta.
- **Alta abandonada durante una conexión en curso**: al descartar, cualquier intento de
  conexión pendiente de esa cuenta se invalida; si el proveedor redirige después, la
  autorización se rechaza como no válida y no se crea ninguna conexión.
- **Credencial ya caducada** frente a **caducidad próxima**: la caducada es "Reconnect
  needed"; la próxima es un aviso.
- **Plataforma sin dato de caducidad**: no se muestra aviso de caducidad.
- **Automatización en pausa**: los posts automáticos próximos se muestran como
  "Scheduled · paused" (no se ejecutarán mientras siga en pausa); los que llegan a su hora
  durante la pausa aparecen en atención con la acción "Resume automation".
- **Read-model no disponible o error de red**: Home muestra un ErrorState con acción
  "Retry", nunca "Everything OK" por defecto.
- **Carga**: mientras se cargan datos se muestra un estado de carga (skeleton) y no un estado
  vacío ni "Everything OK" prematuro.
- **Zona horaria**: "Next" y "Up next" se muestran en la hora local del navegador con fecha
  relativa legible ("tomorrow 10:00").
- **Ventana muy estrecha (<375 px) o zoom de texto al 200 %**: el contenido crítico sigue
  siendo usable sin scroll horizontal del documento.
- **Recarga durante un flujo OAuth de conexión**: al volver del proveedor, la app aterriza en
  la URL de Accounts del proyecto correspondiente con el resultado de la conexión visible.
- **URLs antiguas o raíz**: la raíz `/` es Home; no existen URLs previas que preservar.

## Requirements *(mandatory)*

### Functional Requirements

#### Information architecture y routing

- **FR-001**: La aplicación DEBE organizarse en dos niveles: global (Home, Settings) y
  proyecto (Library, Posts, Accounts). NO DEBE existir una página "Project Overview".
- **FR-002**: La aplicación DEBE exponer URLs conceptualmente equivalentes a:
  `/` (Home), `/p/:projectId/library`, `/p/:projectId/library/:mediaId`,
  `/p/:projectId/posts`, `/p/:projectId/posts/:postId`, `/p/:projectId/accounts`,
  `/p/:projectId/accounts/:accountId` y `/settings`, además de `/?project=<projectId>`
  (Home con "Needs attention" filtrado temporalmente a ese proyecto; la Home sin query
  sigue siendo global).
- **FR-003**: Cada URL de FR-002 DEBE sobrevivir a una recarga, admitir atrás/adelante del
  navegador y poder abrirse directamente (deep link) mostrando el contenido correcto.
- **FR-004**: La sección Posts DEBE dejar preparada en la navegación la existencia de dos
  vistas, List y Calendar; en 018 solo List DEBE ser funcional (con la vista de cola
  existente) y Calendar NO DEBE implementarse ni aparecer como opción operativa.
- **FR-005**: Las URLs con identificadores inexistentes o que no pertenecen al proyecto de la
  URL (proyecto, medio, post o cuenta) DEBEN mostrar un estado de error "not found" con una
  única acción de recuperación. En particular, `/p/:projectId/accounts/:accountId` DEBE
  verificar que la cuenta pertenece al proyecto.
- **FR-005a**: La landing de un proyecto es su Library: cuando se navega a un proyecto como
  destino genérico (sin sección concreta), DEBE abrirse `/p/:projectId/library`.
- **FR-005b**: `/?project=<projectId>` DEBE mostrar la Home con "Needs attention" filtrado a
  ese proyecto, indicando visiblemente el filtro y ofreciendo quitarlo; un `projectId`
  inexistente DEBE mostrar el filtro como no válido con la acción de volver a la Home global.
  Este filtro NO es una página "Project Overview".
- **FR-006**: La aplicación DEBE recordar localmente el último proyecto usado para resolver
  la navegación a secciones de proyecto desde contextos globales; ese recuerdo es una
  comodidad de la interfaz, no estado persistente del backend.
- **FR-007**: Las pantallas existentes (Library, detalle de medio, Distribute, cola de
  publicaciones, detalle de publicación) DEBEN integrarse en las nuevas rutas con cambios
  mínimos de contenido: mismo comportamiento funcional, nuevo contenedor de navegación.

#### App shell responsive

- **FR-008**: En escritorio, la app DEBE mostrar una sidebar con Home, selector de proyecto,
  Library, Posts, Accounts y Settings.
- **FR-009**: En tablet, la app DEBE mostrar una navigation rail compacta con los mismos
  destinos.
- **FR-010**: En móvil, la app DEBE mostrar una bottom navigation con Home, Library, Posts y
  Accounts; el selector de proyecto en la parte superior; Settings en un menú secundario.
  NO DEBE mostrarse una versión comprimida de la sidebar de escritorio.
- **FR-011**: La navegación DEBE indicar visualmente y de forma accesible la sección activa.
- **FR-012**: La app DEBE diseñarse y validarse al menos para ~375 px, tablet y escritorio,
  con cero scroll horizontal del documento en todos ellos.
- **FR-013**: Todos los objetivos táctiles interactivos DEBEN medir al menos 44×44 px.
- **FR-014**: En móvil, los formularios DEBEN ocupar el ancho completo disponible.
- **FR-015**: DEBE existir un patrón común de navegación de detalles: side panel/drawer en
  escritorio, overlay drawer en tablet y pantalla completa con "Back" en móvil, en todos los
  casos respaldado por la URL del detalle. En 018 el patrón DEBE crearse y usarse en el
  detalle de cuenta (`/p/:projectId/accounts/:accountId`); la migración de los detalles de medio y post corresponde
  a 019.

#### Home / Attention

- **FR-016**: Home DEBE responder "What needs my attention, and what is happening next?"
  mostrando, en este orden: Needs attention, Up next, Projects. Cuando no hay problemas,
  DEBE sustituir Needs attention por un estado positivo explícito ("Everything OK") con la
  próxima publicación.
- **FR-017**: "Needs attention" DEBE derivarse de datos existentes e incluir: posts fallidos;
  posts que esperan acción del usuario en la plataforma; posts vencidos (automáticos cuya
  ventana pasó sin ejecutarse, manuales cuya hora pasó, o automáticos cuya hora llega con la
  automatización en pausa); posts cuyo último intento requiere revisión
  manual; cuentas activas que requieren reconexión; cuentas activas con credencial que caduca
  en los próximos 7 días; y posts programados en los próximos 7 días con requisitos
  incompletos o no verificables según comprobación local.
- **FR-017a**: Los proyectos inactivos DEBEN generar atención únicamente por problemas ya
  existentes que aún hay que conocer o resolver (revisión manual, fallidos, acción del
  usuario pendiente) y NO DEBEN generarla por reconexión, caducidad de credenciales,
  requisitos de próximos posts ni planificación futura.
- **FR-017b**: Si la comprobación local de requisitos de un post próximo no puede
  completarse, el post DEBE aparecer como requisitos incompletos con el mensaje
  "Couldn't verify requirements" y enlace al post; NUNCA DEBE considerarse listo ni ocultarse.
- **FR-018**: Cada elemento de atención DEBE mostrar: el problema en lenguaje claro, su
  contexto (proyecto, plataforma/cuenta y post o medio afectado, y cuándo), exactamente UNA
  acción primaria (p. ej. Review, Check status, Reconnect, Complete, Publish now /
  Reschedule) y un deep link a la pantalla donde se resuelve.
- **FR-019**: Los elementos de atención DEBEN ordenarse por gravedad y después por urgencia
  temporal: (1) revisión manual, (2) fallidos, (3) vencidos, (4) acción del usuario
  pendiente, (5) reconexión requerida, (6) requisitos incompletos de próximos posts,
  (7) caducidad próxima. Un mismo post DEBE aparecer una sola vez, con su problema más grave.
- **FR-020**: "Up next" DEBE mostrar de forma compacta hasta 5 próximas publicaciones
  programadas de todos los proyectos, indicando proyecto, cuenta/plataforma, hora y su estado
  (automático, manual o automático en pausa); cada elemento DEBE enlazar directamente a su post. NO
  DEBE existir una vista global de Posts ni un "See more" global.
- **FR-021**: "Projects" DEBE listar los proyectos de forma compacta con un indicador del
  número de elementos de atención de cada uno, enlazando a la landing del proyecto (Library).
- **FR-022**: Home NO DEBE incluir métricas decorativas (totales, gráficas o contadores que
  no conduzcan a una acción).
- **FR-023**: Mientras los datos cargan o si fallan, Home DEBE mostrar un estado de carga o
  de error con "Retry"; NUNCA DEBE mostrar "Everything OK" sin datos confirmados.

#### Read-models (backend, solo lectura)

- **FR-024**: El backend DEBE ofrecer read-models de solo lectura que permitan obtener
  eficientemente, de forma global y filtrada por proyecto, los elementos de atención de
  FR-017, las próximas programaciones y los resúmenes necesarios para la franja de estado.
- **FR-025**: Los read-models NO DEBEN crear persistencia nueva (tablas, columnas o datos
  almacenados) y NO DEBEN modificar ningún dato.
- **FR-026**: Los read-models NO DEBEN realizar llamadas remotas a plataformas ni ejecutar
  reconciliación remota; la comprobación de requisitos de un post DEBE usar únicamente la
  lógica local existente, que puede leer recursos locales necesarios (p. ej. el almacén
  seguro del sistema) pero NUNCA DEBE usar la red ni modificar estado.
- **FR-027**: El backend DEBE ofrecer un read-model de salud de cuenta que, para cada cuenta,
  indique: estado de producto (Ready / Reconnect needed / Finish setup / Not connected /
  Inactive), identidad conectada, fecha de caducidad de la credencial cuando se conozca, capacidades de
  publicación en lenguaje de producto y el problema actual si existe. "Finish setup"
  (`setup_required`) representa una conexión válida pero incompleta para poder publicar
  (p. ej. Telegram conectado sin canal seleccionado) y NO DEBE confundirse con
  "Reconnect needed" (conexión que ya no es válida o credencial caducada).
- **FR-028**: El backend DEBE ofrecer un read-model de disponibilidad de configuración por
  plataforma que indique si existe la configuración local necesaria para conectarla y, si
  no, una explicación breve de qué falta. NO DEBE devolver secretos, tokens, contenido de
  ficheros de configuración, credenciales ni datos que permitan reconstruirlos.
- **FR-029**: Los read-models DEBEN incluir, para cada plataforma, si tiene integración
  funcional en AutoPublisher, de modo que la interfaz distinga plataformas conectables de
  plataformas "Coming soon".

#### Project status strip

- **FR-030**: Dentro del contexto de un proyecto DEBE mostrarse una franja compacta con:
  cuentas listas sobre cuentas activas, número de elementos de atención del proyecto y
  próxima publicación programada; cada elemento DEBE enlazar a su destino (Accounts,
  `/?project=<projectId>`, el post).
- **FR-031**: La franja NO DEBE crecer hasta convertirse en un dashboard: sin gráficas, sin
  listas, sin más de los tres elementos de FR-030 (más, opcionalmente, un indicador de
  automatización en pausa).

#### Accounts

- **FR-032**: Cada cuenta DEBE mostrar principalmente: plataforma, identidad conectada,
  estado de producto (Ready / Reconnect needed / Finish setup / Not connected / Inactive,
  FR-027), capacidades, problema actual y aviso de caducidad cuando corresponda, con una
  única acción principal según el estado (Reconnect, Finish setup, Connect o ninguna).
- **FR-033**: Scopes, IDs técnicos, "Test connection" y "Disconnect" DEBEN estar bajo
  progressive disclosure (plegados por defecto).
- **FR-034**: El flujo de alta DEBE ser `Add account → choose platform → Connect`; la
  identidad de la cuenta DEBE obtenerse de la conexión y NO DEBE pedirse al usuario que la
  escriba antes de conectar.
- **FR-035**: Para plataformas cuya conexión requiere datos del usuario como parte del
  propio flujo (p. ej. número de teléfono y código en Telegram), esos datos DEBEN pedirse
  dentro del paso "Connect", no como paso previo de identidad.
- **FR-036**: Las plataformas sin integración funcional DEBEN ocultarse o mostrarse
  claramente como "Coming soon" no seleccionables.
- **FR-037**: Si la plataforma elegida no tiene la configuración local disponible, el flujo
  DEBE explicarlo y ofrecer una única acción que lleve a Settings, sin iniciar la conexión.
- **FR-038**: Las cuentas existentes (incluidas las creadas con el flujo anterior sin
  conexión) DEBEN seguir funcionando y mostrarse con el estado correcto; NO DEBE requerirse
  migración de datos (solo un cambio de esquema compatible: la identidad de una cuenta pasa a
  poder ser desconocida hasta su primera conexión). La identidad conectada DEBE adoptarse
  tras una conexión correcta solo si la cuenta aún no tiene identidad; los handles
  existentes NUNCA DEBEN sobrescribirse automáticamente.
- **FR-039**: Las acciones existentes sobre cuentas (activar/desactivar, editar nombre
  visible, conectar, reconectar, probar conexión, desconectar) DEBEN seguir disponibles.
- **FR-039a**: DEBE existir una operación "Discard" cuya única finalidad es descartar un alta
  abandonada. Solo DEBE permitirse sobre cuentas provisionales: sin identidad adoptada, sin
  ninguna conexión registrada (válida o que requiera reconexión) y sin posts; en cualquier
  otro caso DEBE rechazarse indicando que la cuenta puede desactivarse. Al descartar, DEBEN
  invalidarse los intentos de conexión pendientes de esa cuenta (que solo existen en memoria)
  de forma que una redirección posterior del proveedor no cree ninguna conexión. NO DEBE
  ofrecerse como borrado general de cuentas.

#### Settings

- **FR-040**: DEBE existir una pantalla Settings global con: estado y control de la
  automatización global (activa/en pausa) y disponibilidad de configuración por plataforma.
- **FR-041**: El control global de automatización DEBE retirarse de la vista Posts/cola de
  proyecto; en su lugar puede mostrarse un indicador de pausa enlazado a Settings.
- **FR-042**: Settings NO DEBE exponer secretos ni permitir editarlos. Deployment,
  autenticación LAN y almacenamiento de secretos headless quedan fuera de alcance.

#### Onboarding

- **FR-043**: El onboarding DEBE implementarse mediante empty states encadenados, sin
  wizard multipaso: sin proyectos → "Create your first project"; proyecto sin cuentas →
  "Connect an account"; proyecto sin medios → "Import your first media"; medios sin usar →
  acción "Publish…" evidente.
- **FR-044**: Cada empty state DEBE tener exactamente una acción primaria.
- **FR-045**: Mientras un proyecto esté incompleto, su contexto DEBE mostrar una checklist
  compacta de progreso con los pasos: cuenta conectada y lista, primer medio importado,
  primer post creado. Al completarse todos, la checklist DEBE desaparecer.

#### Terminología y estados

- **FR-046**: Los textos visibles nuevos o rehechos en 018 (shell, Home, franja, Accounts,
  Settings, empty states, checklist) DEBEN usar: Post (no Publication), Media (no Asset),
  Library (no Asset Library), Posts (no Queue), Draft / Save as draft (no Unscheduled /
  Prepare).
- **FR-047**: Los términos técnicos "preflight", "reconcile", "attempt" y "checksum" NO
  DEBEN aparecer como lenguaje principal del producto en las pantallas de 018; pueden
  aparecer solo dentro de detalles técnicos plegados.
- **FR-048**: Los nombres internos (modelos, API, base de datos) NO DEBEN renombrarse salvo
  que sea necesario por otra razón.
- **FR-049**: DEBE existir un sistema de estados de post, con etiqueta y semántica visual
  definidas, que exprese qué va a ocurrir: "Draft", "Scheduled · automatic",
  "Scheduled · manual", "Scheduled · paused", "Publishing", "Published", "Failed",
  "Needs review", "Needs action", "Missed" y "Cancelled". "Scheduled · paused" DEBE comunicar
  que el post está programado para publicación automática pero la automatización global está
  en pausa y no se ejecutará mientras siga así; "Needs review" DEBE comunicar que la última
  ejecución tuvo un resultado incierto que requiere revisión humana antes de reintentar.
  NUNCA DEBE mostrarse "Scheduled" sin indicar automático, manual o en pausa.
- **FR-050**: El estado de un post NO DEBE comunicarse solo mediante color: DEBE incluir
  texto (y opcionalmente icono).

#### Design system

- **FR-051**: DEBE definirse un sistema visual propio con tokens de tipografía, color,
  espaciado, radios, sombras (si se usan), semántica de estados, breakpoints responsive,
  foco y estados de interacción (hover, active, disabled, focus).
- **FR-052**: DEBEN existir primitivas reutilizables, al menos: Button, IconButton,
  Badge/StatusBadge, Card, EmptyState, ErrorState, Loading/Skeleton, y primitivas de
  dialog/drawer/sheet; menu/popover cuando lo requieran las pantallas de 018.
- **FR-053**: Puede usarse una librería headless accesible para primitivas complejas
  (dialog, menu, popover); NO DEBE adoptarse un kit visual completo que determine el estilo.
- **FR-054**: Los tokens DEBEN organizarse de forma que añadir un tema oscuro en el futuro
  no requiera reescribir componentes; en 018 solo se implementa y valida el tema claro.

#### Progressive disclosure

- **FR-055**: En las pantallas de 018 DEBEN estar siempre visibles el estado, el problema
  actual, la siguiente acción y la acción principal de la pantalla; DEBEN ser contextuales
  la configuración de plataforma, los requisitos y las acciones de recuperación; y DEBEN
  estar plegados por defecto scopes, IDs, checksums, actividad técnica y configuración de
  baja frecuencia.

#### Accesibilidad

- **FR-056**: La aplicación DEBE cumplir contraste WCAG 2.1 AA en el tema principal.
- **FR-057**: Toda la funcionalidad del shell y de las pantallas de 018 DEBE ser operable
  solo con teclado, con foco siempre visible y orden de foco lógico.
- **FR-058**: Los controles DEBEN ser semánticos y tener etiquetas accesibles; los diálogos
  y drawers DEBEN gestionar el foco (atraparlo mientras están abiertos y devolverlo al
  cerrarse) y cerrarse con Escape.
- **FR-059**: Ninguna información o acción DEBE depender exclusivamente de hover.
- **FR-060**: Las animaciones y transiciones DEBEN respetar la preferencia de movimiento
  reducido del sistema.

### Key Entities *(include if feature involves data)*

Ninguna entidad persistente nueva. Se definen vistas de solo lectura derivadas de datos
existentes:

- **Attention item**: problema que requiere acción del usuario. Atributos: tipo de problema
  (manual review, failed, missed, needs action, reconnect required, expiring credential,
  incomplete requirements — incluye requisitos no verificables), gravedad, proyecto, cuenta/plataforma, post o medio afectado
  (si aplica), momento relevante, acción primaria y destino del deep link. Derivado de
  publicaciones, sus intentos, conexiones de cuenta y la comprobación local de requisitos.
- **Upcoming post**: publicación programada futura con proyecto, cuenta/plataforma, hora y
  modo de ejecución (automático/manual).
- **Account health**: vista de una cuenta con estado de producto (Ready / Reconnect needed /
  Finish setup / Not connected / Inactive), identidad, caducidad de credencial, capacidades y problema.
  Derivada de `Account` y de la conexión específica de su plataforma.
- **Platform availability**: por plataforma, si tiene integración funcional y si la
  configuración local necesaria está disponible (con motivo si no). Sin secretos.
- **Project status summary**: cuentas listas / cuentas activas, número de elementos de
  atención y próxima publicación de un proyecto.
- **Onboarding progress**: pasos completados de un proyecto (cuenta lista, medio importado,
  post creado), derivado de los datos existentes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (First use, alcance 018)**: con la configuración de plataforma preparada, una
  persona nueva completa `create project → connect account → import media → identify and
  reach Publish…` sin consultar documentación, siguiendo únicamente las acciones principales
  y los empty states. El journey completo `… → Publish… → configure destinations →
  schedule/publish` sin documentación se valida en Feature 019; 018 NO rediseña Publish para
  cumplirlo prematuramente.
- **SC-002 (Daily use)**: desde Home, en 5 segundos o menos, un usuario identifica si existe
  algún problema, qué necesita acción y cuál es la siguiente publicación.
- **SC-003 (Recovery)**: el 100 % de los elementos de atención llevan a la pantalla donde se
  resuelve el problema con una única interacción principal.
- **SC-004 (Navigation)**: el 100 % de las secciones, medios y posts tienen una URL que
  muestra el mismo contenido tras recarga, apertura directa y atrás/adelante del navegador.
- **SC-005 (Empty states)**: el 100 % de los empty states tienen exactamente una acción
  principal.
- **SC-006 (Responsive)**: cero scroll horizontal del documento a 375 px en todas las rutas
  de FR-002; lo crítico de Attention (problema y acción) visible sin scroll horizontal.
- **SC-007 (Touch)**: el 100 % de los objetivos interactivos del shell y de las pantallas de
  018 miden al menos 44×44 px.
- **SC-008 (Accessibility)**: todas las pantallas de 018 son operables por completo con
  teclado, con foco visible, y cumplen contraste WCAG AA.
- **SC-009 (Safety)**: ninguna respuesta de los read-models contiene secretos, tokens,
  contenido de ficheros de configuración ni credenciales, y ninguna provoca llamadas remotas
  a plataformas ni modifica datos.
- **SC-010 (No regression)**: todos los flujos existentes (importar, distribuir, programar,
  publicar ahora, auto-publicar, conectar y reconectar cuentas) siguen funcionando desde la
  nueva navegación.
- **SC-011 (Clarity)**: ningún estado de post programado se muestra sin indicar si será
  automático o manual.

## Design process / implementation guidance

No es comportamiento verificable del producto ni criterio de éxito; es guía del proceso:

- Al comenzar el trabajo de design system se verifica el repositorio oficial de
  `ui-ux-pro-max-skill` y se instala como skill de proyecto para Claude Code.
- Se consulta para productividad/SaaS y dashboard, navegación, responsive, formularios,
  jerarquía y accesibilidad.
- Sus recomendaciones no se aceptan automáticamente: esta spec y los principios de producto
  prevalecen. Solo se documentan las recomendaciones adoptadas (y, cuando aporte, las
  rechazadas con su motivo).
- No se vendoriza ni publica automáticamente código de terceros en el repositorio salvo que
  sea realmente necesario y se apruebe durante el plan.

## Testing Strategy

Siguiendo CLAUDE.md y la Constitution: tests dirigidos durante la implementación, checks
estáticos una vez antes del PR, suites completas solo en la CI del PR. Sin snapshots masivos
ni asserts de CSS visual. Se priorizan:

- contrato de routing y deep links (apertura directa, recarga simulada, atrás/adelante,
  not found);
- estado de navegación responsive donde exista comportamiento (qué navegación se presenta
  por breakpoint, menú secundario de Settings en móvil);
- agregación de atención en backend (cada tipo de problema, prioridad, deduplicación por
  post, filtro por proyecto, ausencia de llamadas remotas y de secretos);
- salud de cuenta por estado y plataforma, y disponibilidad de configuración sin secretos;
- empty states de onboarding (una acción principal cada uno) y checklist;
- comportamiento crítico de accesibilidad (gestión de foco en dialog/drawer, Escape,
  etiquetas accesibles de la navegación).

No se duplican tests existentes de workflows que 018 no cambia; los tests existentes solo se
adaptan donde cambie la navegación o la terminología visible.

## Out of Scope

- Rediseño profundo de Library (cards, flujo de contenido), Media detail, flujo
  Publish/Distribute, Posts List, Post detail e implementación de Calendar (Feature 019).
- Migración de los detalles de medio y post al patrón común de detalles (Feature 019).
- Finalización completa de la terminología en pantallas no rehechas por 018 (Feature 019).
- Dark mode, deployment, LAN, autenticación, PWA, keyring headless, backup, Republish y
  bulk actions.
- Edición de configuración de plataformas o secretos desde la interfaz.
- Notificaciones push, email o cualquier canal fuera de la aplicación.
- Nuevas integraciones de plataforma (X sigue sin integración).

## Assumptions

- **Breakpoints**: móvil < 768 px (diseñado para ~375 px), tablet 768–1023 px,
  escritorio ≥ 1024 px; el plan puede ajustarlos ligeramente sin cambiar el comportamiento.
- **Router**: se usará un router React mantenido y adecuado al stack actual (React 19 +
  Vite); la elección concreta corresponde al plan. El servidor de desarrollo y el backend
  sirven la app de forma que las rutas profundas resuelvan a la aplicación.
- **Umbral de caducidad próxima**: 7 días; mismo horizonte para "posts próximos con
  requisitos incompletos".
- **Vencido ("Missed")**: corresponde al estado de auto-publicación vencida ya existente;
  los posts programados manuales cuya hora pasó también se muestran como "Missed" con acción
  "Publish now / Reschedule".
- **Requisitos incompletos**: se determinan con la comprobación local previa a publicar ya
  existente, sin red y sin modificar estado; si no puede completarse, el post se trata como
  requisitos no verificables dentro de la misma categoría.
- **Capacidades de cuenta**: se expresan en lenguaje de producto a partir de lo que cada
  publisher ya declara (p. ej. imágenes, vídeos, texto, entrega a bandeja de TikTok).
- **Estados de cuenta** (en orden de evaluación): "Inactive": cuenta desactivada,
  independientemente de su conexión; "Not connected": activa sin conexión; "Reconnect
  needed": conexión que requiere reconexión o credencial caducada; "Finish setup": conexión
  válida pero incompleta para publicar (hoy solo Telegram sin canal); "Ready": activa con
  conexión válida y completa.
- **Cuenta provisional**: cuenta creada por el nuevo flujo cuya identidad aún no se conoce;
  es la única que puede descartarse.
- **Último proyecto usado**: se recuerda en el navegador; si el almacenamiento no está
  disponible, se usa el primer proyecto.
- **Plataformas sin integración**: actualmente solo X; se muestra como "Coming soon".
- **Single user, local**: se mantiene el modelo de la Constitution; no hay permisos ni
  múltiples usuarios.
- **Tamaño de datos**: volúmenes de un usuario individual (decenas de proyectos y cuentas,
  miles de posts); los read-models deben responder de forma inmediata a esa escala.
