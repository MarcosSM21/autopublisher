# Feature Specification: Visual Refresh

**Feature Branch**: `023-visual-refresh`

**Created**: 2026-10-25

**Status**: Ready for planning

**Input**: User description: "Feature 023 — Visual Refresh. Transformar la presentación de
AutoPublisher en una aplicación moderna, cuidada y con identidad propia (dirección *Creative
Editorial Workspace*: calm, creative, intentional, premium, functional) SIN alterar
funcionalidad, workflows, rutas ni comportamiento de producto. Refresh transversal mediante
design system, shared components, app shell/navigation, pantallas principales, pantallas
secundarias, login/onboarding y responsive/polish. Fundamentalmente frontend. Incluye
`visual-design-brief.md` como fuente de verdad visual."

**Documentos fuente de verdad**: esta specification + [visual-design-brief.md](./visual-design-brief.md).
El brief fija los valores visuales (paleta, tipografía, spacing, geometry, motion, referencias);
esta spec fija el alcance, los requisitos verificables y los límites.

## Regla de producto

**Same product, new presentation.** Todo lo que el usuario puede hacer hoy lo hace igual
después de 023: mismas rutas, mismos pasos, mismas confirmaciones, misma información, mismo
copy funcional. Solo cambia cómo se ve.

**Delete → exactly one confirmation** se mantiene sin excepción.

## Contexto (estado actual relevante)

Contexto para la planificación; el comportamiento exigido está en Requirements.

- Feature 018 creó el design system vigente (`docs/design-system.md`): tokens en dos capas
  (primitivos + semánticos), primitives en `frontend/src/ui/` (`Button`, `IconButton`, `Icon`,
  `Badge`, `StatusBadge`, `Card`, `EmptyState`, `ErrorState`, `Skeleton`, `Dialog`/`Drawer`/
  `Sheet`, `Disclosure`, `DetailSurface`, `Field`, `ChoiceGroup`, `PageActions`), paleta azul
  `#1D4ED8`, system font stack, targets de 44px en todos los controles y motion limitado al
  spinner.
- Shell único responsive (`frontend/src/shell/`): sidebar (`lg`+), rail con TopBar (`md`) y
  bottom bar fija con "More" (`sm`); task mode en Publish media y Text post; "Skip to content".
- Pantallas existentes (no se inventan otras):
  - **Login** (`/login`, fuera del shell): wordmark, campo Password, `Sign in`, nota de reset.
  - **Home** (`/`): attention list / "Everything looks good", banner de automatización pausada,
    `Up next` (≤ 5 posts: fecha, título o extracto, proyecto · cuenta, estado), `Projects`
    (nombre, próximo post, badges), filtro por proyecto, empty state "Create your first project".
    Home **no recibe thumbnails ni media reciente** del backend.
  - **Project layout**: ProjectHeader, ProjectStatusStrip, OnboardingChecklist ("Get started").
  - **Library**: raíz (entradas Unsorted / All media / Folders), vistas de Media con grid,
    MediaCard, folders, Breadcrumb, Select mode + SelectionBar, Move (FolderPicker), Bulk Delete,
    import (ImportPanel, dropzone), Media detail (preview, FileDetails, MediaContentEditor,
    MediaUsage, InheritanceWarning), FolderNameDialog.
  - **Publish media / Text post** (task mode): compose (destinations, presets, customize) y
    review (content by destination, when, final actions, results).
  - **Posts**: List (secciones, PostRow, DailyList, HistoryList, Activity) | Calendar
    (CalendarView), Post detail (PostContent, PostWhen, StatusActionPanel), ActionDialog,
    CheckResultDialog, menú `New post`.
  - **Accounts**: AccountCard, AccountDetail, AddAccountSheet y connection panels por plataforma
    (YouTube, Instagram, Threads, TikTok, Telegram) y TikTok Inbox delivery.
  - **Settings** (`/settings`): Automation, Installation status (host-only), Platform
    integrations, Sign-in (ChangePasswordDialog).
  - **Errores**: NotFound, ProjectNotFound, RouteError, ErrorState, Flash.
- Diálogos compartidos: DeleteConfirmDialog, CreateProjectDialog, ChangePasswordDialog,
  FolderNameDialog, EditContentDialog, PresetsDialog, ActionDialog, CheckResultDialog,
  AddAccountSheet.
- No existe primitive genérico de Dropdown/Menu, Select, Checkbox, Textarea ni Loader: los menús
  son disclosures pequeños (p. ej. `New post`, acciones de Media) y los campos son controles
  nativos dentro de `Field`; el loader es el spinner de `Button` + `Skeleton`.
- Parte de los connection panels y `MediaPreview` siguen usando CSS legacy (`index.css`).
- Iconos: set SVG propio inline (24 grid, 2px stroke, outline), sin librería.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Un sistema visual coherente en toda la app (Priority: P1)

Como usuario de AutoPublisher, quiero que todos los controles compartidos (botones, campos,
badges, superficies, diálogos, sheets, menús, empty states, alerts, loaders, estados de
selección) tengan un lenguaje visual nuevo, sobrio y consistente, para que la app se perciba
como un producto terminado y no como una herramienta interna.

**Why this priority**: es la base de todo el refresh; la mayor parte del cambio visible se
propaga desde aquí y el resto de historias dependen de ello.

**Independent Test**: tras aplicar solo tokens + shared components, recorrer cualquier pantalla
existente y comprobar que botones, campos, badges, cards, diálogos y empty states usan el nuevo
lenguaje (paleta, tipografía, radios, estados) sin que cambie ningún flujo.

**Acceptance Scenarios**:

1. **Given** cualquier pantalla, **When** la abro, **Then** veo la paleta neutral cálida, la
   tipografía Geist (o fallback) y los radios del brief, y la acción primaria se distingue
   inmediatamente de las secundarias.
2. **Given** un formulario existente, **When** navego con teclado, **Then** cada control muestra
   foco visible con accent + soft ring, y hover/active/disabled/error son distinguibles sin
   depender solo del color.
3. **Given** un post en cualquier estado, **When** veo su badge, **Then** conserva el mismo texto
   e icono que hoy y la mayoría de estados se ven neutrales; solo error, warning, attention y
   success significativo usan color fuerte.
4. **Given** una acción que hoy pide una confirmación (p. ej. Delete), **When** la ejecuto,
   **Then** aparece exactamente una confirmación, con estilo destructive solo si la acción es
   destructiva.

---

### User Story 2 - App shell y navegación con identidad (Priority: P1)

Como usuario, quiero una navegación con personalidad (sidebar oscura, branding cuidado, item
activo claro y tranquilo) que me diga siempre dónde estoy, sin cambiar dónde están las cosas.

**Why this priority**: la sidebar es el elemento de mayor identidad y está presente en todas las
pantallas del workspace.

**Independent Test**: en `lg`, `md` y `sm`, navegar Home → Library → Posts → Accounts → Settings
y comprobar sidebar/rail/bottom bar renovados, item activo identificable, branding visible y los
mismos destinos, orden y comportamiento que hoy.

**Acceptance Scenarios**:

1. **Given** desktop (`lg`+), **When** abro cualquier sección, **Then** la sidebar es oscura,
   muestra el branding AutoPublisher cuidado, separa navegación principal de utilidades
   (Settings) y marca el activo con una surface ligeramente más clara + peso, no con un bloque
   verde.
2. **Given** la sidebar, **When** la recorro con teclado, **Then** el foco es visible sobre el
   fondo oscuro con contraste ≥ 3:1.
3. **Given** `md` o `sm`, **When** navego, **Then** rail, TopBar, bottom bar y "More" conservan
   destinos, orden y comportamiento, con el nuevo lenguaje visual.
4. **Given** una pantalla del workspace, **When** la abro, **Then** su header (título, contexto,
   breadcrumb cuando ya existe) responde de inmediato "dónde estoy / qué veo / cuál es la acción
   principal".
5. **Given** task mode (Publish media, Text post), **When** entro, **Then** el shell se comporta
   igual que hoy (bottom nav oculta en `sm`, sticky actions).

---

### User Story 3 - Library como creative asset library (Priority: P1)

Como usuario que gestiona imágenes y vídeos, quiero que la Library ponga mi contenido en primer
plano (thumbnails protagonistas, metadata subordinada, folders con identidad propia, selección
clara) para trabajar con mis assets como en una herramienta creativa y no en un file manager.

**Why this priority**: es la pantalla donde más tiempo se trabaja con contenido visual y una de
las prioridades explícitas de la feature.

**Independent Test**: abrir Library con media y folders, pasar el puntero/foco por las cards,
entrar en Select mode, seleccionar varias, abrir Move y Bulk Delete y cancelar; comprobar que todo
funciona igual que hoy y que el nuevo tratamiento visual cumple los requisitos de Library.

**Acceptance Scenarios**:

1. **Given** una vista de Media con elementos, **When** la miro, **Then** en cada Media card el
   thumbnail ocupa la mayor parte del área visual y nombre/carpeta/duración quedan subordinados.
2. **Given** una Media card, **When** paso el puntero o le doy foco, **Then** hay una ligera
   elevación o cambio de surface sin zoom agresivo, y sus acciones siguen accesibles por teclado
   y táctil (nunca solo en hover).
3. **Given** folders y media en la misma Library, **When** los veo, **Then** un folder se
   distingue de un Media a simple vista sin iconografía exagerada.
4. **Given** Select mode, **When** selecciono elementos, **Then** cada seleccionado muestra
   outline accent, fondo accent muy suave y checkbox visible, y la barra de selección ofrece las
   mismas acciones (Move, Delete, salir) que hoy.
5. **Given** una vista vacía, **When** la abro, **Then** veo un empty state con icono pequeño,
   título, una línea de explicación y la acción primaria existente.

---

### User Story 4 - Login con personalidad (Priority: P2)

Como usuario que entra en su instalación, quiero un login con branding visible y composición
cuidada, centrado en la contraseña y con una sola acción `Sign in`.

**Why this priority**: es la primera impresión del producto, pero es una pantalla aislada y
pequeña que puede abordarse independientemente.

**Independent Test**: abrir `/login`, introducir contraseña incorrecta y correcta, comprobar
errores, redirección a `next` y que la pantalla tiene la nueva composición.

**Acceptance Scenarios**:

1. **Given** `/login`, **When** se carga, **Then** veo el branding AutoPublisher destacado, un
   único campo Password con foco y un único botón `Sign in`, sin OAuth, marketing ni imágenes
   stock.
2. **Given** una contraseña incorrecta o demasiados intentos, **When** envío, **Then** los
   mensajes de error son los mismos de hoy, anunciados igual y visualmente claros.
3. **Given** un móvil (375px), **When** abro el login, **Then** la composición se adapta sin
   scroll horizontal y el botón tiene ≥ 44px de altura.

---

### User Story 5 - Home como workspace overview (Priority: P2)

Como usuario, quiero que Home se sienta como una visión general del workspace (lo que necesita
atención, lo que viene, mis proyectos) con jerarquía clara, y no como una colección de cajas
administrativas.

**Why this priority**: es la pantalla de entrada del workspace; depende de US1 y US2.

**Independent Test**: abrir Home con y sin attention items, con y sin posts programados, con
varios proyectos, filtrada por proyecto y sin proyectos; comprobar jerarquía, ausencia de KPI
cards idénticas y que enlaces/acciones son los de hoy.

**Acceptance Scenarios**:

1. **Given** Home con attention items y posts programados, **When** la abro, **Then** la
   actividad relevante (attention) tiene el mayor peso, `Up next` se lee como una secuencia
   temporal y `Projects` como accesos útiles, sin convertir cada dato en una KPI card.
2. **Given** que nada necesita atención, **When** abro Home, **Then** el estado "Everything looks
   good" es tranquilo y no ocupa el espacio de una alerta.
3. **Given** Home filtrada por proyecto o sin proyectos, **When** la abro, **Then** filtro,
   "Show all projects", empty state y `Create project` se comportan como hoy.

---

### User Story 6 - Posts y Calendar más legibles (Priority: P2)

Como usuario que programa y revisa publicaciones, quiero que Posts tenga mejor jerarquía,
presentación de contenido y statuses más tranquilos, y que el Calendar sea más claro, sin
cambiar lifecycle ni workflow.

**Why this priority**: uso frecuente, pero tratamiento conservador.

**Independent Test**: abrir Posts en List y Calendar, abrir un Post detail, ejecutar y cancelar
una acción (ActionDialog), revisar History/Activity; comprobar mismo comportamiento con nuevo
aspecto.

**Acceptance Scenarios**:

1. **Given** la lista de Posts, **When** la miro, **Then** cada fila separa claramente contenido,
   cuándo, destino y estado, y los grupos/secciones existentes se distinguen por jerarquía.
2. **Given** el Calendar, **When** lo abro en `xl` y por debajo, **Then** conserva el layout
   actual (semana desde `xl`, agenda por día debajo, detalle en drawer) con eventos
   distinguibles, hoy marcado sin depender solo de color y ruido mínimo.
3. **Given** un Post detail, **When** lo abro, **Then** las mismas acciones aparecen en el mismo
   orden y con la misma semántica.

---

### User Story 7 - Accounts, Settings y onboarding coherentes (Priority: P3)

Como usuario, quiero que Accounts, Settings, connection panels y Get started compartan el mismo
sistema, con secciones agrupadas (título, explicación breve, controles) y estados de conexión
muy claros, sin cambiar pasos ni lógica.

**Why this priority**: pantallas de uso esporádico; tratamiento coherente pero conservador.

**Independent Test**: recorrer Accounts (lista, detalle, Add account, un connection panel),
Settings (todas sus secciones y Change password) y el Get started de un proyecto nuevo;
comprobar mismos pasos y nuevo lenguaje.

**Acceptance Scenarios**:

1. **Given** Settings, **When** lo abro, **Then** cada sección muestra título, explicación breve
   y controles, sin una card alrededor de cada input, labels encima y help text debajo, y la
   navegación y el comportamiento de Settings son exactamente los de hoy (sin índice, anchors ni
   navegación secundaria nuevos).
2. **Given** una cuenta en cualquier estado de conexión, **When** veo su card o detalle,
   **Then** su estado y siguiente paso son inequívocos (texto + icono + tono).
3. **Given** un proyecto nuevo, **When** veo Get started, **Then** los pasos y su lógica son los
   mismos, con mejor composición visual.

---

### User Story 8 - Responsive y polish sin regresiones (Priority: P3)

Como usuario en móvil y desktop, quiero que el refresh funcione igual de bien en ambos, con
diálogos convertidos en sheets en móvil, targets táctiles suficientes y motion sutil que respeta
mis preferencias.

**Why this priority**: cierre transversal de calidad sobre las historias anteriores.

**Independent Test**: revisar las pantallas prioritarias a 375, 768, 1024 y ≥1280px, con 200 %
de texto y con `prefers-reduced-motion: reduce`.

**Acceptance Scenarios**:

1. **Given** 375px, **When** abro cualquier pantalla, **Then** el padding es ~16px, no hay
   scroll horizontal, los controles tienen ≥ 44px y los diálogos aparecen como bottom sheets.
2. **Given** `prefers-reduced-motion: reduce`, **When** abro diálogos, menús o sheets, **Then** no
   hay animación de movimiento.
3. **Given** 200 % de texto, **When** navego, **Then** nada queda recortado ni oculto.

### Edge Cases

- **Media sin thumbnail** (vídeo sin poster, archivo en proceso, error de preview): la card
  mantiene sus proporciones con un placeholder sobrio en surface muted y la metadata sigue
  legible; nada colapsa.
- **Thumbnails con proporciones extremas** (panorámicas, verticales 9:16): el recorte/encaje es
  consistente y no deforma la imagen ni rompe la rejilla.
- **Nombres muy largos** (media, folders, proyectos, cuentas): se truncan o envuelven sin romper
  layout; el nombre completo sigue disponible (detalle o texto accesible).
- **Imágenes muy claras u oscuras** bajo badges/duración superpuestos: los overlays mantienen
  contraste AA (fondo propio) sobre cualquier imagen.
- **Selección grande** en Select mode (decenas de elementos): la barra de selección y el estado
  seleccionado siguen siendo claros; el rendimiento percibido no empeora.
- **Fuente no disponible** (fallo al cargar Geist): la app se ve correctamente con el fallback
  del sistema, sin texto invisible ni saltos de layout graves.
- **Sin conexión a internet**: la app se ve igual; ningún recurso visual depende de servicios
  remotos.
- **Texto al 200 %** y **zoom del navegador**: sidebar, TopBar, badges y bottom nav envuelven sin
  ocultar contenido (comportamiento ya conseguido en 018 que no debe regresar).
- **Ventanas cruzando breakpoints** con un detalle abierto: no se remonta el contenido (contrato
  de DetailSurface intacto).
- **Estados de error/warning sobre fondo oscuro** (sidebar, login con dark framing): contraste
  AA mantenido.
- **Host-only notices** y pantallas de Settings ocultas en remoto: la agrupación visual no deja
  secciones vacías ni huecos.
- **Pantallas de error** (NotFound, RouteError, ErrorState): usan el nuevo sistema y siguen
  ofreciendo la misma salida (Retry / volver).

## Requirements *(mandatory)*

### Functional Requirements — preservación de comportamiento

- **FR-001**: El refresh MUST NOT añadir, quitar ni modificar rutas, pasos de workflow,
  confirmaciones, acciones disponibles, orden de acciones, información mostrada ni modelos de
  datos.
- **FR-002**: Todas las capacidades existentes MUST seguir funcionando igual: Projects, Accounts,
  Library, folders, Move, Bulk Delete, Posts, Calendar, History/Activity, publishing,
  connections, Settings, Login, task mode y comportamiento responsive.
- **FR-003**: Toda acción de borrado MUST mantener exactamente una confirmación.
- **FR-004**: El copy funcional MUST mantenerse; solo se permite microcopy presentacional (p. ej.
  la línea de explicación de un empty state) que no cambie el significado.
- **FR-005**: El backend MUST NOT cambiar, salvo necesidad técnica imprescindible y no funcional,
  que debe justificarse en planning.
- **FR-006**: La semántica accesible existente MUST mantenerse o mejorar: landmarks, headings,
  nombres accesibles, `aria-current`, roles `alert`/`status`, focus trap y restauración de foco
  en diálogos, "Skip to content".

### Visual Requirements — design foundation (A)

- **VR-001**: El sistema MUST definir tokens globales para colors, typography, spacing, radius,
  shadows, motion, focus e interactive states, con los valores de dirección del brief (§2–§6,
  §18) y los ajustes de contraste de §17.
- **VR-002**: Las pantallas y componentes MUST consumir solo tokens semánticos; no se introducen
  valores arbitrarios (colores, radios, sombras, duraciones, espaciados fuera de la escala) por
  pantalla.
- **VR-003**: La paleta MUST ser predominantemente neutral; el accent se reserva para acción
  primaria, foco, selección y estados activos puntuales.
- **VR-004**: La tipografía MUST usar Geist (o equivalente justificado) servida por la propia
  aplicación sin peticiones a servicios remotos, con fallback al system stack y la jerarquía del
  brief §3.
- **VR-005**: La escala de spacing MUST ser múltiplos de 4 (`4/8/12/16/24/32/48`), con ~32px de
  padding horizontal de página en desktop, ~32–40px entre secciones mayores y ~16px en móvil.
- **VR-006**: Las sombras MUST reservarse para superficies elevadas (dialogs, menus, sheets,
  floating elements); ningún elemento combina border fuerte y shadow fuerte; sin glassmorphism
  ni gradientes decorativos.
- **VR-007**: El motion MUST ser sutil (hover/focus ~120–160ms; overlays ~180–240ms; fade, small
  translate, surface transitions), sin bounce, zoom pronunciado ni parallax, y MUST desactivarse
  el movimiento con `prefers-reduced-motion: reduce`.

### Visual Requirements — shared components (B)

- **VR-010**: Button MUST ofrecer Primary, Secondary, Ghost y Destructive según el brief §16,
  con altura habitual de 40px en desktop con puntero fino y ≥ 44px de target en móvil/táctil
  (Decisión D1), y
  no todos pill-shaped.
- **VR-011**: Input, Textarea y Select MUST ser ligeramente más cómodos, con superficie limpia,
  borde de control con contraste ≥ 3:1, placeholder secundario, focus accent + soft ring y sin
  inset shadows; Checkbox MUST mostrar checked en accent y foco visible.
- **VR-012**: Badge/StatusBadge MUST conservar texto e icono de cada estado y aplicar el status
  system del brief §10: mayoría neutral, color fuerte solo para error, warning, attention y
  success significativo.
- **VR-013**: Card/Surface MUST seguir la jerarquía background → surface → elevated, agrupando
  más con superficie y espacio que con bordes.
- **VR-014**: Dialog, Drawer y Sheet MUST tener padding generoso, título claro, explicación,
  contenido y zona de acciones claramente separada; en móvil, bottom sheet touch-friendly; su
  semántica (modalidad, foco, Escape, overlay) no cambia.
- **VR-015**: Los menús existentes (disclosures tipo `New post` y acciones de Media) MUST
  compartir un mismo estilo de dropdown elevado, sin cambiar su comportamiento.
- **VR-016**: EmptyState MUST poder mostrar icono pequeño, título, una línea de explicación y la
  acción primaria; sin ilustraciones grandes genéricas.
- **VR-017**: Flash/Alert, ErrorState, Skeleton y spinner MUST adoptar el nuevo lenguaje
  conservando roles y anuncios.
- **VR-018**: Los estados de selección (Library, choices, filtros) MUST usar outline accent +
  fondo accent suave + indicador visible (checkbox/marca), nunca solo color.
- **VR-019**: Todo componente interactivo MUST definir default, hover, focus-visible, active,
  selected, disabled, loading y error cuando aplique.

### Visual Requirements — app shell & navigation (C)

- **VR-020**: La sidebar (`lg`+) MUST seguir el brief §7: fondo oscuro, iconos outline de una
  familia (~18–20px), texto secundario claro, respiración vertical, separación entre navegación
  principal y utilidades, item normal sin caja, item activo con surface ligeramente más clara +
  peso (no bloque verde) y branding AutoPublisher con tratamiento tipográfico cuidado.
- **VR-021**: Rail (`md`), TopBar, bottom bar (`sm`), "More" y project selector MUST adoptar el
  mismo lenguaje sin cambiar destinos, orden ni comportamiento.
- **VR-022**: El layout principal MUST aplicar el page spacing del brief y un tratamiento de
  header común (título de página, contexto y acción principal, solo con los elementos que cada
  pantalla ya muestra) en las pantallas del workspace; el
  Breadcrumb existente de Library adopta el nuevo estilo. No se añaden breadcrumbs nuevos.
- **VR-023**: El foco de teclado MUST ser visible sobre la sidebar oscura con contraste ≥ 3:1.

### Visual Requirements — core screens (D)

- **VR-030 (Home)**: Home MUST presentarse como workspace overview con jerarquía: actividad
  relevante (attention / automation paused / "Everything looks good") primero, `Up next` como
  secuencia temporal y `Projects` como accesos útiles; MUST NOT convertir cada dato en KPI cards
  idénticas. Usa solo la información que Home ya muestra.
- **VR-031 (Library – Media card)**: El thumbnail MUST ocupar la mayor parte del área visual de
  la card; la metadata (nombre, folder, duración) MUST quedar subordinada; badges y acciones
  secundarias MUST ser discretos.
- **VR-032 (Library – hover/focus)**: hover/focus MUST producir ligera elevación o cambio de
  surface, sin zoom agresivo; las acciones que aparezcan en hover MUST ser también accesibles
  por teclado y táctil.
- **VR-033 (Library – folders)**: los folders MUST tener identidad visual distinta de Media sin
  iconografía genérica exagerada.
- **VR-034 (Library – selección)**: seleccionado = outline accent + fondo accent muy suave +
  checkbox visible; Select mode y SelectionBar MUST conservar exactamente su funcionalidad.
- **VR-035 (Library – densidad y vacíos)**: la rejilla MUST equilibrar densidad y protagonismo
  del thumbnail en cada breakpoint conservando las columnas/estructura responsive acordadas en
  019; Library root, import y empty states MUST seguir el sistema.
- **VR-036 (Library – detalle)**: Media detail (preview, file details, content editor, usage)
  MUST adoptar el sistema dando protagonismo a la preview.
- **VR-037 (Posts)**: Posts MUST mejorar jerarquía, presentación del contenido, statuses y
  agrupación (secciones, filas, Post detail, History/Activity) sin cambiar lifecycle ni
  workflow.
- **VR-038 (Publish)**: Publish media y Text post MUST heredar el sistema vía shared components y
  tokens, sin rediseñar su estructura ni pasos.

### Visual Requirements — secondary screens (E)

- **VR-040 (Calendar)**: refresh conservador: claridad de tiempo, eventos distinguibles, hoy
  identificable sin depender solo de color, ruido mínimo; sin cambiar layout ni breakpoints.
- **VR-041 (Settings)**: Settings MUST conservar exactamente su navegación y comportamiento
  actuales y conseguir la jerarquía solo mediante section titles, descriptions, spacing,
  grouping, surfaces y typography: cada sección con title, explicación breve y controls, sin card
  por input, labels arriba y help text debajo. MUST NOT añadir rutas, anchors navegables ni
  navegación secundaria (Decisión D4).
- **VR-042 (Accounts / connections)**: AccountCard, AccountDetail, AddAccountSheet y connection
  panels MUST mostrar estados de conexión muy claros y adoptar el sistema, migrando su
  presentación legacy a tokens sin cambiar estructura ni lógica (Decisión D6).
- **VR-043 (Onboarding / project chrome)**: OnboardingChecklist, ProjectHeader y
  ProjectStatusStrip MUST mejorar composición sin cambiar pasos, enlaces ni lógica.
- **VR-044 (Errores)**: NotFound, ProjectNotFound, RouteError y ErrorState MUST usar el sistema.

### Visual Requirements — special experiences (F)

- **VR-050 (Login)**: Login MUST tener branding AutoPublisher visible y más personalidad que el
  workspace (dark framing + light panel, Decisión D7), password como
  elemento central, una sola acción `Sign in`, y MUST NOT incluir OAuth, marketing copy ni stock
  imagery. Mensajes de error, nota de reset y redirección no cambian.
- **VR-051 (Dialogs / Sheets)**: todos los diálogos compartidos MUST seguir VR-014; el estilo
  destructive MUST aplicarse solo a acciones realmente destructivas.

### Responsive Requirements

- **RR-001**: MUST preservarse la arquitectura responsive existente (breakpoints `sm/md/lg/xl`,
  sidebar/rail/bottom bar, DetailSurface, drawers, sticky PageActions, task mode).
- **RR-002**: En móvil MUST aplicarse padding ~16px, targets ≥ 44px, dialogs como bottom sheets,
  cards adaptadas, tipografía proporcional y navegación accesible.
- **RR-003**: Desktop MUST NOT ser una versión simplemente ensanchada de móvil, ni móvil una
  versión estrechada de desktop.
- **RR-004**: No se introduce rediseño específico de tablet.

### Accessibility Requirements

- **AR-001**: Todo texto MUST cumplir WCAG 2.2 AA (≥ 4.5:1, ≥ 3:1 en texto grande) sobre su
  fondo real, incluidos sidebar oscura, login, badges y overlays sobre thumbnails.
- **AR-002**: Los bordes que identifican controles y el foco MUST tener ≥ 3:1.
- **AR-003**: Foco de teclado visible siempre; navegación por teclado igual o mejor que hoy.
- **AR-004**: Ningún estado o significado MUST depender solo del color.
- **AR-005**: `prefers-reduced-motion` MUST respetarse en todas las transiciones nuevas.
- **AR-006**: Texto de cuerpo ≥ 14px y metadata ≥ 12px, en unidades que respetan el text-size
  del navegador; sin pérdida de contenido al 200 %.
- **AR-007**: Nada interactivo MUST estar disponible solo en hover.

### Documentation Requirements

- **DR-001**: `docs/design-system.md` MUST actualizarse para reflejar los nuevos tokens,
  tipografía, reglas de targets, motion, status map y principios de este refresh.

### Key Entities

No aplica: la feature no introduce ni modifica datos. Los "elementos" del sistema son de
presentación:

- **Design tokens**: valores globales (color, tipografía, spacing, radius, shadow, motion, focus)
  que todas las pantallas consumen.
- **Status map**: correspondencia única estado → label, icono, tono (ya existente; cambia solo el
  tono visual).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El 100 % de las pantallas listadas en Contexto se renderizan con el nuevo sistema
  (paleta, tipografía, controles) sin restos visibles del estilo anterior (azul `#1D4ED8`,
  system font como fuente principal, controles legacy) en una revisión pantalla a pantalla.
- **SC-002**: 0 cambios en rutas, pasos de workflow, número de confirmaciones o información
  mostrada: todos los tests de comportamiento existentes del frontend pasan sin modificar sus
  aserciones de comportamiento (solo se permiten ajustes de selectores puramente visuales).
- **SC-003**: 0 colores, radios, sombras o duraciones literales en estilos de pantalla fuera de
  los tokens, verificable por búsqueda en el diff.
- **SC-004**: En revisión visual de Library (Unsorted, All media y un folder) en `sm`, `md`, `lg`
  y `xl`, el asset visual es claramente la región dominante de cada Media card y la metadata
  queda subordinada en tamaño, color y posición. Como target de diseño, en las cards estándar el
  área del asset ronda el 70 % cuando la geometría de la vista lo permite; no es un umbral
  rígido para todos los breakpoints, aspect ratios o estados (sin thumbnail, seleccionada,
  nombres largos).
- **SC-005**: El 100 % de los pares texto/fondo y foco/fondo del sistema cumplen AA, registrados
  en la tabla de contraste de `docs/design-system.md`.
- **SC-006**: A 375px ninguna pantalla prioritaria presenta scroll horizontal y todos sus
  controles interactivos miden ≥ 44px.
- **SC-007**: Con `prefers-reduced-motion: reduce` ninguna transición nueva produce movimiento.
- **SC-008**: La app no realiza ninguna petición de red a terceros para fuentes u otros recursos
  visuales.
- **SC-009**: Home no contiene una rejilla de KPI cards idénticas; sus secciones tienen al menos
  dos niveles de jerarquía visual distinguibles.
- **SC-010**: El tiempo hasta ver contenido en Home y Library no empeora de forma perceptible
  respecto a la versión anterior (sin bloqueo visible por carga de fuentes o estilos).
- **SC-011**: En revisión manual del usuario, AutoPublisher se percibe como un producto distinto y
  más terminado, con todas las pantallas pertenecientes al mismo sistema, sin necesidad de
  reaprender ningún workflow.

## Non-goals

- Nuevas funcionalidades, workflows, rutas o información.
- Cambios en modelos de datos, scheduler o semántica de publicación.
- Rediseño de la creación de Posts (Publish media / Text post) o de la arquitectura de Library.
- Dark mode completo, theme selector o personalización de colores.
- Branding/logo profesional completo; ilustraciones custom.
- Animaciones avanzadas o efectos visuales experimentales.
- Rediseño específico de tablet.
- Rediseño del backend.
- Cambios de copy funcional.
- Nuevas fuentes de datos para Home (p. ej. media reciente con thumbnails).

## Decisiones cerradas

Todas las decisiones de producto están confirmadas por el usuario (2026-10-25). No quedan
decisiones abiertas.

- **D1 ✅ — Altura de controles.** 40px habitual en desktop con puntero fino; ≥ 44px en móvil
  (`sm`/`md`) y siempre que el puntero sea táctil. WCAG 2.2 AA (24px) se sigue cumpliendo. La
  regla universal de 44px de `docs/design-system.md` se revisa al implementar.
- **D2 ✅ — Geist local.** La fuente (licencia OFL) se empaqueta con la app, sin CDN ni
  peticiones remotas; variable font con pesos 400–600 (permite 550) y fallback al system stack.
- **D3 ✅ — Home solo con datos existentes.** Attention, automation paused, Up next y Projects;
  sin thumbnails ni media reciente (sería nueva información).
- **D4 ✅ — Settings sin navegación secundaria nueva.** Settings conserva exactamente su
  navegación y comportamiento; la jerarquía sale de section titles, descriptions, spacing,
  grouping, surfaces y typography. Sin rutas nuevas, anchors navegables ni secondary navigation.
- **D5 ✅ — Status mapping.** Mapeo del brief §10: Scheduled · automatic pasa de info a neutral;
  Publishing usa neutral activo; **Needs review pasa a warning/attention** (requiere atención,
  no implica error); danger se reserva para estados realmente fallidos/críticos (Failed,
  Missed, Reconnect needed, Not configured). Labels e iconos no cambian.
- **D6 ✅ — Connection panels legacy.** Su presentación migra de `index.css` a tokens dentro de
  023, sin tocar estructura ni lógica.
- **D7 ✅ — Login.** Dark framing + light panel.
- **D8 ✅ — Navegación móvil.** Rail `md` oscuro como la sidebar; bottom bar `sm` en surface clara
  con separador sutil.
- **D9 ✅ — Motion.** Fade/small translate en dialogs, sheets y menus y transiciones de surface,
  dentro de los rangos del brief y anulados con `prefers-reduced-motion`.

## Riesgos y contradicciones detectadas

- **Contraste de la paleta de dirección**: secondary text `#70736C` falla AA sobre canvas (4.42)
  y surface muted (4.15); el accent como focus ring falla sobre la sidebar (2.63); el subtle
  border (1.36) no sirve como borde de control. Ajustes propuestos en el brief §17.
- **Conflicto con `docs/design-system.md` (018)**: regla de 44px universal, "no remote fonts"
  (compatible si se empaqueta), motion solo spinner, "Breadcrumbs rechazados" (ya existen en
  Library desde 021), paleta azul. Se resuelve con D1, D2, D9 y DR-001.
- **"Contenido reciente" vs "no nueva información"** en Home: resuelto por D3.
- **"Secondary navigation" en Settings (brief original) vs "Same product, new presentation"**:
  resuelto por D4 (no se añade navegación).
- **Tests acoplados a clases/estructura**: el refresh puede romper tests que dependan de clases
  CSS o estructura DOM; MUST mantenerse la semántica que los tests de comportamiento consultan
  (roles, nombres accesibles, texto).
- **Sin regresión visual automatizada**: la calidad visual se valida por revisión manual en
  navegador real a varios anchos; conviene acotar esa revisión en planning.
- **CSS legacy y por página**: riesgo de "page → arbitrary CSS"; mitigado por VR-002 y SC-003.
- **Peso de la fuente**: impacto en carga; mitigado por SC-010 y fallback (Edge Cases).
- **Overlays sobre thumbnails**: badges/duración sobre imágenes arbitrarias necesitan fondo propio
  para mantener AA.
- **Alcance amplio**: la feature toca casi todos los archivos de estilos; debe entregarse por
  capas (tokens → components → shell → core → secondary → polish) en commits pequeños.

## Assumptions

- Instalación de un único usuario; no hay preferencias de tema por usuario.
- Los navegadores objetivo son los mismos que hoy (evergreen de escritorio y móvil).
- La fuente se empaqueta con la app; si no carga, el system stack es aceptable.
- La revisión visual final la realiza el usuario en navegador real (como en 018/019).
- Los valores hexadecimales del brief son dirección; planning puede ajustarlos para AA sin
  cambiar la dirección (neutral cálido + sidebar oscura + verde desaturado).
- El set de iconos propio se mantiene y puede ampliarse con iconos de la misma familia si una
  pantalla lo necesita (p. ej. folder, image), sin introducir librerías.
- La estructura de rejilla de Library (2 columnas en `sm`, 5–6 en `xl`) puede ajustarse
  ligeramente en densidad sin cambiar su comportamiento.
