# Feature Specification: Brand & Motion Polish

**Feature Branch**: `026-brand-motion-polish`

**Created**: 2026-10-28

**Status**: Draft

**Input**: User description: "Feature 026 — Brand & Motion Polish. Añadir identidad y feedback
visual únicamente en unos pocos momentos memorables: Login / Auth loading, estado Publishing,
transición Publishing → Published observada, Media recién importado, Calendar reschedule y
favicon. Extender mínimamente el sistema de motion existente con un nivel de énfasis, mantener
reduced motion y corregir los hover lifts pegajosos en táctil. NO es otro rediseño (Feature 023
ya hizo el Visual Refresh)."

## Regla de producto

**Brand in memorable moments. Motion only when it communicates or rewards.**

La feature NO rediseña nada, NO crea branding nuevo, NO cambia flujos, datos, backend ni
navegación. Solo añade identidad y feedback en los momentos enumerados en esta spec; todo lo
demás queda exactamente como está.

**Sustitución explícita** de reglas anteriores (docs/design-system.md, Feature 023):

- La regla "no gradients" sigue vigente para todo el producto **excepto** una única iluminación
  radial estática sobre el marco oscuro de Login / Auth loading (FR-006–FR-008).
- La regla "Motion: fast 140 ms (controles), medium 200 ms (overlays)" se amplía con un único
  nivel de énfasis (FR-001–FR-004). El resto de reglas de motion (sin page transitions, sin
  scroll reveals, sin librerías) sigue vigente.
- La decisión de Feature 024 "drag del Calendar sin animación" sigue vigente: el highlight de
  FR-030 ocurre solo después de confirmar el reschedule, nunca durante el drag.

## Contexto (estado actual verificado en el código)

Contexto para la planificación; el comportamiento exigido está en Requirements.

- **Motion actual**: dos duraciones compartidas (fast 140 ms para controles, medium 200 ms para
  overlays) y dos curvas (standard, out). Dialog, Sheet, Drawer y menús se animan al abrir y
  cerrar; Flash entra con fade; las cards de Media y las tiles de proyecto de Home se elevan 1 px
  con sombra al hover/focus; el spinner de botón gira. No hay page transitions.
- **Reduced motion**: una política global reduce toda animación y transición a prácticamente
  cero y a una sola iteración; las duraciones compartidas pasan a 0.
- **Marca**: existe un monograma decorativo (cuadrado moss con una barra clara interior, oculto a
  tecnologías de asistencia) junto al texto "AutoPublisher" en Login y en el sidebar (`lg`). No
  existe favicon: el navegador muestra su icono genérico. No hay logo, imágenes ni SVG de marca.
- **Login**: marco oscuro (mismo tono que el sidebar) con un panel claro centrado; título
  "AutoPublisher" con monograma; campo de contraseña con foco automático; aparece de golpe.
- **Auth loading**: mientras se conoce la sesión, tanto la puerta de la app como /login muestran
  el texto plano "Loading AutoPublisher…" sobre el marco oscuro (con `role="status"`). El mismo
  marco aloja el error "Couldn't reach AutoPublisher" con Retry.
- **Publishing**: el estado se muestra con un badge (tono active/moss, icono reloj, texto
  "Publishing" o "Publishing…/Processing" en Results) en Posts (lista y detail), Calendar, Home
  (Up next / Attention) y Publish Results. Posts y Publish Results releen los datos
  periódicamente mientras hay Posts publicando; Home no relee sola.
- **Publish Results**: una línea agregada `aria-live="polite"`; cada fila cambia su badge al
  estado real tras cada relectura, sin transición.
- **Import**: una petición por archivo; panel con progreso por archivo, resumen agregado y
  resultado por archivo (Imported / Duplicate / Rejected); cada resultado importado trae el Media
  creado. Al terminar se relee la lista. Las cards nuevas aparecen sin ninguna marca. Desde la
  raíz de Library (que no muestra grid) los Media van a Unsorted.
- **Calendar reschedule** (Feature 024): tras confirmar el diálogo, se relee la lista, el foco va
  al Post reprogramado (o al encabezado si salió de la semana) y una región `role="status"`
  oculta anuncia "<título> rescheduled for <fecha>." No hay feedback visual del item.
- **Hover lifts**: cards de Media y tiles de proyecto se elevan con `:hover` sin distinguir
  dispositivo; en táctil el estado hover se queda "pegado" tras tocar.
- **Flash**: el live region se monta a la vez que su mensaje (algunos lectores de pantalla no lo
  anuncian). Problema preexistente, documentado y fuera de alcance (FR-052).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Entrar en AutoPublisher se siente como un producto propio (Priority: P1)

Como usuario que abre AutoPublisher, quiero que la pantalla de carga y el Login tengan una
identidad reconocible (monograma, nombre, una iluminación ambiental discreta y una entrada suave)
sin que eso me haga esperar ni me impida escribir la contraseña de inmediato.

**Why this priority**: Es el único momento puramente de marca, lo ve cada visita y no toca
ningún flujo crítico. Es el mayor impacto con el menor riesgo.

**Independent Test**: Abrir la app sin sesión: el loading muestra monograma + nombre; el Login
aparece con entrada suave, la contraseña tiene foco y se puede escribir y enviar al instante.

**Acceptance Scenarios**:

1. **Given** una sesión que aún se está comprobando, **When** la app arranca, **Then** se ve el
   monograma, el nombre AutoPublisher y un texto de carga, anunciado una vez como estado, sin
   desplazamiento continuo.
2. **Given** el Login, **When** aparece, **Then** el panel entra una sola vez (fade + pequeño
   desplazamiento vertical) y la barra interior del monograma se coloca en su sitio una sola vez.
3. **Given** el Login apareciendo, **When** el usuario escribe y pulsa Enter antes de que termine
   la entrada, **Then** el texto se recibe completo y el envío ocurre sin espera adicional.
4. **Given** el marco oscuro de Login / Auth loading / error de sesión, **Then** hay una única
   iluminación radial moss estática de muy baja intensidad y todo el texto mantiene su contraste.
5. **Given** `prefers-reduced-motion: reduce`, **When** aparece el Login, **Then** se muestra
   directamente en su estado final, con el monograma completo y la iluminación estática.

---

### User Story 2 - Ver que una publicación está en curso y celebrar cuando sale (Priority: P1)

Como usuario que publica, quiero ver que una publicación está activamente en curso y, si veo
cómo termina, recibir una confirmación visual breve de que se publicó, sin que las publicaciones
que ya estaban publicadas "celebren" cada vez que abro una vista.

**Why this priority**: Es el feedback de la acción más importante del producto; comunica estado
real (actividad y éxito), no decoración.

**Independent Test**: Publicar un Post y mirar Publish Results / Posts: el badge Publishing
muestra un indicador de actividad; cuando la relectura trae Published, ese badge recibe un
énfasis único. Recargar la vista: el Post Published aparece estático.

**Acceptance Scenarios**:

1. **Given** un Post en estado Publishing en cualquier vista que muestre su estado, **Then** su
   badge muestra un pequeño indicador de actividad además del texto y el icono existentes; su
   pulso termina en menos de 5 s y el indicador queda estático.
2. **Given** una vista abierta que muestra un Post en Publishing, **When** una relectura trae ese
   Post como Published, **Then** su badge Published recibe un énfasis visual único.
3. **Given** un Post que ya estaba Published al abrir, recargar o volver a una vista, **Then** no
   recibe ningún énfasis.
4. **Given** un Post que ya recibió su énfasis, **When** la vista se relee de nuevo sin nueva
   transición, **Then** no se repite el énfasis.
4a. **Given** Publish Results, **When** el usuario pulsa la acción final "publicar ahora" y una
   publicación de esa misma operación aparece ya como Published en su primer estado observable
   (plataforma rápida, nunca se vio Publishing), **Then** su badge Published recibe el mismo
   énfasis una sola vez.
4b. **Given** una publicación Published en Calendar, Home, Post detail o History, o en Publish
   Results tras recargar o volver a entrar, **Then** no recibe énfasis por el solo hecho de estar
   Published.
5. **Given** `prefers-reduced-motion: reduce`, **Then** el badge Publishing muestra su
   indicador estático y el badge Published aparece sin animación; texto e icono no cambian.

---

### User Story 3 - Encontrar al instante lo que acabo de importar (Priority: P2)

Como usuario que importa archivos a Library, quiero que las cards de los Media que acabo de crear
se distingan brevemente en el grid, para confirmar de un vistazo qué entró y dónde está.

**Why this priority**: Refuerza una confirmación que hoy solo vive en el panel de resultados;
valor funcional claro, coste bajo, pero menos central que Login y Publish.

**Independent Test**: Importar 3 archivos (2 válidos, 1 rechazado) en una carpeta con Media
previos: solo las 2 cards nuevas reciben el highlight temporal; las previas no; el panel de
resultados sigue igual.

**Acceptance Scenarios**:

1. **Given** un import que termina con Media creados, **When** la lista se relee, **Then** las
   cards de esos Media visibles en la vista actual reciben un highlight temporal que se desvanece
   en aproximadamente 1–1,5 s.
2. **Given** un import con resultados Duplicate o Rejected, **Then** ninguna card recibe
   highlight por esos resultados (tampoco el Media existente enlazado por un duplicado).
3. **Given** filtros o búsqueda activos que ocultan un Media recién importado, **Then** los
   filtros no se resetean ni el Media se fuerza a aparecer.
4. **Given** el highlight en curso, **Then** el layout no cambia, no hay auto-scroll nuevo y el
   foco no se mueve.

---

### User Story 4 - Localizar visualmente un Post reprogramado en el Calendar (Priority: P2)

Como usuario que reprograma un Post en el Calendar, quiero que el item aparezca brevemente
resaltado en su nueva posición, para ver dónde ha quedado sin tener que buscarlo.

**Why this priority**: Complementa el anuncio y la restauración de foco de Feature 024 con una
confirmación visual; útil pero acotada a un flujo.

**Independent Test**: Reprogramar un Post (por diálogo o drag) a otro día de la semana visible:
el item recibe un highlight breve en su nuevo día, el foco y el anuncio siguen igual que hoy.
Cancelar o fallar el diálogo: ningún highlight.

**Acceptance Scenarios**:

1. **Given** un reschedule confirmado con éxito, **When** la lista se relee, **Then** el item
   reprogramado recibe un highlight único y breve en su posición nueva, sin mover geometría.
2. **Given** el mismo reschedule, **Then** el foco va al mismo elemento que hoy y el anuncio
   accesible es el mismo que hoy.
3. **Given** un diálogo cancelado o un reschedule fallido, **Then** ningún item recibe highlight.
4. **Given** un Post reprogramado fuera de la semana visible, **Then** no hay highlight y el
   comportamiento de foco/anuncio es el actual.

---

### User Story 5 - Reconocer la pestaña de AutoPublisher (Priority: P3)

Como usuario con muchas pestañas abiertas, quiero que la pestaña de AutoPublisher tenga un icono
propio derivado del monograma.

**Why this priority**: Detalle de marca muy barato y permanente, pero no afecta a ningún flujo.

**Independent Test**: Abrir la app en el navegador: la pestaña muestra el monograma y es
reconocible a 16 px.

**Acceptance Scenarios**:

1. **Given** la app abierta, **Then** la pestaña muestra un icono derivado del monograma actual
   (mismas formas y colores), reconocible a tamaño pequeño.

---

### User Story 6 - Sin hover pegado en táctil (Priority: P3)

Como usuario de tablet o móvil, quiero que las cards de Media y las tiles de proyecto no se
queden "elevadas" después de tocarlas.

**Why this priority**: Corrección de pulido de bajo coste; no cambia el diseño desktop.

**Independent Test**: En un dispositivo táctil (o emulación sin hover / pointer coarse), tocar
una card y volver: no queda elevada. En desktop con ratón, el hover se ve igual que hoy.

**Acceptance Scenarios**:

1. **Given** un dispositivo sin hover o con puntero no fino, **When** toco una card de Media o
   una tile de proyecto, **Then** no aparece el lift (sombra + 1 px).
2. **Given** un dispositivo con hover y puntero fino, **When** paso el ratón, **Then** el lift
   es idéntico al actual.
3. **Given** foco por teclado en cualquier dispositivo, **Then** el estado de foco visible actual
   se conserva.

---

### Edge Cases

- **Login muy rápido**: la sesión se resuelve antes de que termine la entrada del Login → el
  usuario puede escribir y enviar durante la entrada; nada espera a la animación.
- **Sesión ya iniciada**: /login redirige como hoy; no se muestra entrada ni loading adicional.
- **Error de sesión**: el marco con "Couldn't reach AutoPublisher" usa la misma iluminación
  estática; Retry vuelve al loading de marca.
- **Auth loading muy breve**: aparece y desaparece sin parpadeos añadidos; no se impone duración
  mínima (no es splash).
- **Publishing que pasa a Failed / Needs action / Needs review**: solo Publishing → Published
  dispara énfasis; cualquier otro destino se muestra como hoy, sin énfasis.
- **Publishing → Published entre dos relecturas sin que la vista lo viera en Publishing** (p. ej.
  la vista se abrió cuando ya era Published) → sin énfasis, salvo el fast-path de Publish Results
  (FR-020a) para publicaciones iniciadas en esa misma operación.
- **Fast-path y re-montaje**: si la sección Results se re-monta dentro de la misma operación, una
  publicación que ya recibió su énfasis no lo repite.
- **Fast-path con programar**: la acción final "programar" nunca produce Published inmediato;
  el fast-path no aplica.
- **Varias transiciones a la vez**: cada Post observado que pasa a Published recibe su propio
  énfasis una vez.
- **Misma publicación visible en dos sitios de la misma vista** (p. ej. lista y detail): el
  énfasis puede aparecer en cada representación observada, una vez cada una; nunca en bucle.
- **Home**: no relee sola; si una recarga trae un Post ya Published, no hay énfasis.
- **Auth loading**: el texto se mantiene exactamente "Loading AutoPublisher…"; no hay copy nuevo.
- **Publicación que permanece mucho tiempo en Publishing** (procesamiento de plataforma): el
  pulso termina en < 5 s y el indicador queda estático el resto del tiempo; nunca se vuelve más
  llamativo.
- **"Processing" de otro proceso** (p. ej. la entrega a la bandeja de TikTok): no recibe el
  indicador de actividad.
- **Import desde la raíz de Library** (sin grid visible): no hay cards que resaltar; el panel de
  resultados sigue siendo la confirmación.
- **Import a una carpeta mientras el usuario navega a otra vista**: solo se resaltan cards de la
  vista donde aparecen tras la relectura y solo si siguen siendo Media de ese import; nunca otras.
- **Import con todos los archivos rechazados o duplicados**: ningún highlight.
- **Selección activa durante el import**: el highlight no altera ni se confunde con el estado
  seleccionado (ambos se distinguen sin depender solo del color).
- **Reschedule en vista agenda (móvil)**: el highlight aplica igual si el item es visible en la
  nueva posición; foco y anuncio como hoy.
- **Relectura periódica durante un highlight**: el highlight no se reinicia ni se duplica.
- **Highlight tardío**: un Media importado que quedó oculto y se vuelve visible tras otra
  recarga, o un Post reprogramado fuera de la semana visible al que se navega después (botones,
  Back/Forward o URL), no reciben highlight.
- **Reduced motion**: los highlights pueden mostrarse como un breve estado estático o no
  mostrarse; la confirmación semántica (panel de import, anuncio, badge) es siempre la existente.
- **Pestaña en segundo plano**: un énfasis o highlight ocurrido mientras la pestaña estaba
  oculta puede no verse; no se reproduce al volver.

## Requirements *(mandatory)*

### Functional Requirements

#### Sistema de motion

- **FR-001**: El sistema MUST conservar sin cambios los niveles de motion existentes (rápido
  ~140 ms para controles, medio ~200 ms para overlays) y sus curvas.
- **FR-002**: El sistema MUST añadir un único nivel de **énfasis** (~320–400 ms) y, si hace
  falta, una única curva de énfasis de salida suave sin overshoot ni rebote.
- **FR-003**: El nivel de énfasis MUST usarse exclusivamente para: la entrada de marca del Login,
  el énfasis de Published y los highlights de import y reschedule.
- **FR-004**: Toda animación nueva MUST limitarse a opacidad, transformaciones (desplazamiento,
  escala), color/contorno y sombras puntuales; MUST NOT animar propiedades que cambien el layout
  ni introducir dependencias, bucles de animación por script ni librerías de animación.
- **FR-005**: Toda animación nueva MUST ser no bloqueante: ninguna acción, envío, navegación,
  actualización de estado ni cambio de foco espera a que termine.
- **FR-005a**: Ninguna animación nueva MUST ejecutarse indefinidamente: cada una se reproduce al
  entrar en su estado (o al ocurrir su evento), dura como mucho unos pocos ciclos, termina antes
  de 5 s y queda después en una representación estática igualmente comprensible. Esto aplica
  especialmente al Auth loading y al indicador de Publishing.

#### Login y Auth loading

- **FR-006**: El marco oscuro de Login, Auth loading y error de sesión MUST mostrar una única
  iluminación radial estática en moss de muy baja intensidad, puramente ambiental y sin animación.
- **FR-007**: La iluminación MUST NOT reducir el contraste de ningún texto o control por debajo
  de los valores registrados en el design system (WCAG 2.2 AA).
- **FR-008**: Ninguna otra superficie del producto (Home, Library, cards, sidebar, diálogos, etc.)
  MUST usar gradientes; la excepción se documenta como tal en el design system.
- **FR-009**: El panel de Login MUST entrar una sola vez al montarse con un fade y un pequeño
  desplazamiento vertical usando el nivel de énfasis.
- **FR-010**: El monograma del Login MUST mantener su diseño y, una sola vez al cargar, su barra
  interior MUST aparecer/deslizarse suavemente hasta su posición final; sin bucle.
- **FR-011**: El campo de contraseña MUST seguir recibiendo el foco automáticamente al aparecer
  el Login, y el usuario MUST poder escribir y enviar durante la entrada.
- **FR-012**: El Auth loading (puerta de la app y /login) MUST sustituir el texto plano por un
  estado de carga de marca con el monograma existente y el texto exacto actual
  "Loading AutoPublisher…" (sin copy nuevo), anunciado como estado una sola vez.
- **FR-013**: El Auth loading MAY usar un pulso de opacidad muy sutil y acotado (FR-005a) que
  termina en el estado estático; MUST NOT usar movimiento indefinido, desplazamiento, spinner
  grande ni duración mínima (no es splash screen) y MUST NOT retrasar la resolución de la sesión.
- **FR-014**: El monograma MUST seguir siendo decorativo (oculto a tecnologías de asistencia) en
  todas sus apariciones; el nombre accesible y los títulos actuales no cambian.

#### Publishing

- **FR-015**: Todo badge que represente el estado real de Post **Publishing** (trabajo activo de
  publicación) MUST mostrar un pequeño indicador de actividad, de forma consistente allí donde se
  muestre ese estado (Posts, Post detail, Calendar, Home, Publish Results y cualquier otra vista
  que use la misma representación de estado).
- **FR-015a**: Un label o estado llamado "Processing" MUST recibir el indicador solo si
  representa ese mismo proceso de publicación activo (p. ej. una variante visual de Publishing en
  Publish Results); "Processing" que represente otro proceso queda fuera. El plan identifica los
  estados reales y sus componentes antes de generalizar el indicador.
- **FR-016**: El indicador MUST ser mínimo (punto o equivalente) con, como mucho, un pulso de
  opacidad/escala muy suave y acotado al entrar en el estado (FR-005a), tras el cual queda
  estático; MUST NOT mover la card o fila, rebotar, girar a gran tamaño ni usar shimmer.
- **FR-017**: El estado Publishing MUST seguir siendo comprensible sin movimiento y sin color:
  texto e icono actuales se mantienen; el indicador tiene una forma estática visible.
- **FR-018**: El indicador MUST NOT generar anuncios para tecnologías de asistencia (es
  decorativo), cambios de foco ni nuevas regiones vivas.
- **FR-019**: El movimiento del indicador MUST ser discreto, de baja amplitud y terminar antes de
  5 s (WCAG 2.2.2: sin movimiento automático prolongado); con reduced motion se muestra
  directamente estático.

#### Transición Publishing → Published

- **FR-020**: El badge Published de un Post MUST recibir un énfasis visual único (aparición del
  check, escala/fade sutil del badge o anillo de énfasis breve) usando el nivel de énfasis en
  exactamente dos casos:
  - **(A) Transición observada**, en cualquier vista: la vista mostraba el Post en Publishing y la
    relectura que ya existe lo trae como Published, durante la vida de esa vista.
  - **(B) Fast-path de Publish Results** (FR-020a).
- **FR-020a**: En Publish Results, una publicación iniciada por el usuario con la acción final de
  publicar ahora **en esa misma operación y vista** cuyo primer estado observable ya es Published
  MUST recibir el mismo énfasis una sola vez. La pertenencia a la operación MUST derivarse del
  contexto efímero que la tarea de publicación ya mantiene para la última acción final, sin
  identificación persistente nueva. Este caso MUST NOT aplicarse en ninguna otra vista.
- **FR-021**: La detección MUST basarse exclusivamente en (A) comparar el estado previo observado
  (Publishing) y el estado actual (Published) del mismo Post durante la vida de esa vista, o (B)
  el contexto de la operación en curso de Publish Results.
- **FR-022**: El énfasis MUST NOT ocurrir al cargar, recargar o volver a entrar en una vista donde
  el Post ya era Published; en History; en Calendar, Home o Post detail por el solo hecho de que el
  estado inicial sea Published; en publicaciones que no pertenecen a la operación actual de
  Publish Results; ni más de una vez por publicación y transición u operación.
- **FR-023**: El estado observado MUST NOT persistirse (ni almacenamiento del navegador, ni
  backend, ni modelos nuevos); se pierde al abandonar la vista.
- **FR-024**: El estado Published normal MUST permanecer estático; el énfasis no altera texto,
  icono, tono ni el anuncio agregado existente de Publish Results.

#### Import highlight

- **FR-025**: Tras un import, las cards de los Media **creados** en esa operación (resultados
  Imported) que sean visibles en la vista actual tras la relectura MUST recibir un highlight
  temporal (contorno/anillo moss que se desvanece en aproximadamente 1–1,5 s).
- **FR-026**: MUST NOT recibir highlight: Media previos, Media existentes enlazados por un
  resultado Duplicate, resultados Rejected, ni Media que reaparecen por cambiar filtros, búsqueda
  o vista.
- **FR-027**: El highlight MUST sobrevivir a la relectura de la lista que ya ocurre tras el
  import (aplica a las cards tal como quedan tras ella) y MUST ocurrir una sola vez por import.
- **FR-028**: El highlight MUST NOT cambiar layout, filtros, búsqueda, orden, selección ni foco,
  y MUST NOT añadir auto-scroll ni progreso por bytes.
- **FR-029**: La confirmación del import MUST seguir siendo el panel de resultados existente; el
  highlight es un refuerzo, nunca la única confirmación.

#### Calendar reschedule highlight

- **FR-030**: Tras un reschedule confirmado con éxito en el Calendar, el item reprogramado MUST
  recibir un highlight único y breve en su nueva posición si es visible en la vista actual.
- **FR-031**: El highlight MUST usar contorno/fondo, opacidad o sombra leve; MUST NOT mover
  geometría ni animar el movimiento del item entre días ni el drag.
- **FR-032**: El foco tras el reschedule y el anuncio accesible existentes (Feature 024) MUST
  mantenerse exactamente igual.
- **FR-033**: Un diálogo cancelado, un reschedule fallido o un Post que sale de la vista visible
  MUST NOT producir highlight.

#### Favicon

- **FR-034**: La app MUST declarar un favicon propio derivado del monograma actual (mismas
  formas y colores), preferentemente vectorial, reconocible a 16 px.
- **FR-035**: La feature MUST NOT rediseñar el logo ni crear un sistema de assets de marca.

#### Hover en dispositivos táctiles

- **FR-036**: Los lifts de hover (sombra + elevación de 1 px) de las cards de Media y las tiles
  de proyecto MUST aplicarse solo en dispositivos con hover y puntero fino.
- **FR-037**: El aspecto del hover en desktop MUST ser idéntico al actual, y los estados de foco
  visible existentes MUST conservarse en todos los dispositivos.

#### Reduced motion

- **FR-038**: Toda animación nueva MUST quedar cubierta por la política global existente de
  `prefers-reduced-motion: reduce` (duración prácticamente cero, una sola iteración).
- **FR-039**: Toda animación nueva MUST terminar de forma natural en el estado estático correcto,
  de modo que con reduced motion se vea directamente el estado final.
- **FR-040**: Con reduced motion, ninguna información MUST depender de la animación: Login
  completo, loading con monograma y texto, badge Publishing con indicador estático, badge
  Published normal; los highlights pueden ser un breve estado estático o no verse, y la
  confirmación semántica existente (panel, anuncio, badge) se mantiene.

#### Accesibilidad

- **FR-041**: Ninguna animación MUST mover, robar ni retrasar el foco; el foco automático del
  Login y la restauración de foco de Calendar y diálogos se mantienen.
- **FR-042**: Las regiones vivas existentes MUST conservar su contenido y comportamiento; la
  feature MUST NOT añadir anuncios repetidos.
- **FR-043**: Ningún highlight o énfasis MUST ser la única señal de un estado o resultado, ni
  depender solo del color.
- **FR-044**: Todo nuevo contraste (iluminación, indicador, highlights) MUST cumplir WCAG 2.2 AA
  (texto ≥ 4.5:1; indicadores y contornos con significado ≥ 3:1 frente a su fondo).

#### Mobile

- **FR-045**: Todo lo anterior MUST funcionar en 375, 390, tablet (768) y desktop (1280/1440)
  sin overflow horizontal nuevo.
- **FR-046**: Ningún feedback MUST requerir hover, seguimiento del ratón, parallax ni gestos.

#### Fuera del alcance explícito

- **FR-047**: La feature MUST NOT añadir page transitions, fades de ruta, transiciones nuevas de
  sidebar ni motion de navegación global; Dialog, Drawer y Sheet mantienen su motion actual.
- **FR-048**: Home MUST NOT recibir animación de entrada ni motion exclusivo; solo hereda el
  indicador de Publishing (FR-015) y, si llegara a observar una transición, el énfasis (FR-020).
- **FR-049**: Los empty states MUST quedar sin cambios (sin ilustraciones, sin motion, sin
  monograma; incluido "Create your first project").
- **FR-050**: Skeletons, spinners y el resto de loading states (salvo Auth loading) MUST quedar
  sin cambios.
- **FR-051**: El drag del Calendar MUST quedar sin animación (Feature 024).
- **FR-052**: Flash MUST NOT modificarse en el MVP. Su problema preexistente de live region queda
  documentado para mantenimiento futuro; si una dependencia real obligara a tocarlo, el cambio
  no puede empeorar la accesibilidad y se reporta antes de ampliar el alcance.

#### Documentación

- **FR-053**: El design system MUST documentar el nivel de énfasis, sus usos permitidos, la
  excepción de la iluminación de Login/Auth, el guard de hover y la política de reduced motion
  para animaciones nuevas.

### Motion semantics

| Momento | Disparador | Una vez / continuo | Nivel | Reduced motion |
|---|---|---|---|---|
| Entrada del panel de Login | Montaje del Login | Una vez | Énfasis | Estado final directo |
| Barra del monograma (Login) | Montaje del Login | Una vez | Énfasis | Monograma completo |
| Iluminación de marco | — | Estática | — | Igual (estática) |
| Auth loading | Sesión en carga | Pulso sutil opcional, pocos ciclos, < 5 s, luego estático | Lento, baja amplitud | Estático |
| Indicador Publishing | Post entra (o se muestra) en Publishing | Pocos ciclos, < 5 s, luego indicador estático | Lento, baja amplitud | Estático visible |
| Énfasis Published | Transición observada Publishing → Published | Una vez por transición | Énfasis | Badge Published normal |
| Highlight de import | Relectura tras import con Media creados | Una vez por import | Énfasis + fade ~1–1,5 s | Estado estático breve o nada |
| Highlight de reschedule | Reschedule confirmado | Una vez | Énfasis + fade breve | Estado estático breve o nada |
| Lift de hover | Hover con puntero fino | Por interacción | Rápido (actual) | Instantáneo (actual) |

### Key Entities

- **Transición observada**: relación efímera, por vista abierta, entre un Post y el último estado
  en que esa vista lo mostró; solo vive mientras la vista existe.
- **Operación de Publish Results**: el contexto efímero de la última acción final de la tarea de
  publicación (qué publicaciones inició y cómo); determina el fast-path y recuerda qué
  publicaciones ya recibieron su énfasis en esa operación.
- **Media recién importados**: conjunto efímero de los Media creados por el último import de la
  vista; se consume al aplicar el highlight.
- **Post recién reprogramado**: referencia efímera al Post del último reschedule confirmado en el
  Calendar (ya existe para la restauración de foco).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En el 100 % de las cargas del Login, el usuario puede escribir en la contraseña
  desde el primer frame visible y enviar sin espera atribuible a la animación; la entrada
  completa dura ≤ 400 ms.
- **SC-002**: El Auth loading muestra monograma y nombre en el 100 % de los casos y no añade
  ningún tiempo de espera respecto a hoy.
- **SC-003**: Un revisor identifica sin explicación previa que un Post en Publishing "está en
  curso" en todas las vistas donde aparece ese estado (Posts, Post detail, Calendar, Home,
  Publish Results).
- **SC-004**: El énfasis de Published aparece en el 100 % de las transiciones observadas y de las
  publicaciones instantáneas de la operación actual de Publish Results, y en el 0 % de las cargas,
  recargas o entradas a vistas con Posts ya Published (incluido Publish Results tras recargar).
- **SC-005**: Tras un import, el usuario identifica qué cards son las recién importadas en menos
  de 2 s, y el 0 % de cards previas, duplicadas o rechazadas se resaltan.
- **SC-006**: Tras un reschedule correcto, el item es localizable visualmente en su nueva
  posición en menos de 2 s; cancelar o fallar no produce highlight en el 100 % de los casos.
- **SC-007**: Con `prefers-reduced-motion: reduce`, el 100 % de la información (estados, textos,
  confirmaciones) sigue presente y no hay movimiento perceptible.
- **SC-007a**: 0 animaciones nuevas indefinidas: todo motion nuevo termina en menos de 5 s y deja
  una representación estática comprensible.
- **SC-008**: 0 cambios de foco causados por motion: foco automático del Login, restauración de
  foco del Calendar y de diálogos idénticos a los actuales.
- **SC-009**: 0 overflows horizontales nuevos en 375, 390, 768 y 1280/1440 px en Login, Auth
  loading, Posts, Calendar, Library y Publish Results.
- **SC-010**: 0 dependencias nuevas en el proyecto.
- **SC-011**: En emulación táctil (sin hover / puntero no fino) ninguna card o tile queda
  elevada tras tocarla; en desktop el hover es idéntico al actual.

### Testing and acceptance

- Los tests verifican estado y estructura, no frames ni duraciones:
  - **Login/Auth**: presencia del marcador de entrada; monograma presente y oculto a tecnologías
    de asistencia; foco automático intacto; Auth loading con marca y anuncio de estado.
  - **Publishing**: el estado Publishing lleva indicador; Publishing → Published observado
    recibe énfasis; Published inicial no; sin re-énfasis sin nueva transición.
  - **Import**: los Media creados reciben highlight; los demás, duplicados y rechazados no; los
    filtros no se resetean.
  - **Calendar**: reschedule correcto marca el item correcto; cancelar/fallar no; foco y anuncio
    iguales.
  - **Reduced motion**: la estructura y el estado final siguen siendo válidos.
- La aceptación final incluye revisión visual en navegador (Chrome/CDP) a 375, 390, 768 y
  1280/1440 px, y con `prefers-reduced-motion: reduce`, de: Login, Auth loading, Publishing,
  Published, highlight de import, highlight de Calendar, favicon y guard de hover táctil.

## Non-goals

Nuevo branding completo; nuevo logo; rediseño visual; dark mode; themes; gradientes fuera de
Login/Auth; page transitions; scroll reveals; parallax; 3D; WebGL; canvas; partículas; confetti;
sonido; Lottie; Framer Motion o cualquier dependencia de animación; revisión de skeletons o de
loading en general; animación del drag del Calendar; revisión de Flash; pack de ilustraciones;
marca en la TopBar de `sm`/`md`; gamificación.

## Assumptions

- Los datos de estado de Posts, la relectura periódica de Posts y Publish Results, el resultado
  por archivo del import (con el Media creado) y la referencia al Post reprogramado ya existen;
  la feature no necesita backend, endpoints, modelos ni migraciones.
- Home no relee sola; por tanto, en la práctica solo hereda el indicador de Publishing.
- "Visible en la vista actual" significa presente en la lista renderizada tras la relectura, con
  los filtros y la búsqueda que el usuario tenga activos.
- El favicon vectorial es suficiente para los navegadores objetivo (los mismos que ya soporta la
  app); no se requieren variantes PNG ni manifest.
- La política global de reduced motion existente se mantiene como mecanismo único; no se crea
  otra.
- Las duraciones exactas (dentro de los rangos dados) y la forma concreta del indicador y del
  énfasis se fijan en planning respetando esta spec.
