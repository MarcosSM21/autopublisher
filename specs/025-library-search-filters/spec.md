# Feature Specification: Library Search, Filters & Organization

**Feature Branch**: `025-library-search-filters`

**Created**: 2026-10-27

**Status**: IMPLEMENTED (2026-10-28, checkpoints A–E)

**Input**: User description: "Feature 025 — Library Search, Filters & Organization. Convertir la
búsqueda y los filtros existentes de Library (búsqueda local, filtros excluyentes All / Images /
Videos / Not used yet) en un sistema coherente de búsqueda mejorada, filtros combinables,
ordenación y estado en URL; conservar el contexto al abrir Media detail y Publish; eliminar el
riesgo de acciones bulk sobre Media seleccionados que han quedado ocultos. MVP frontend-first:
sin endpoints, parámetros backend, paginación, FTS, modelos ni migraciones nuevas."

## Regla de producto

**Find any asset in seconds.**

La feature amplía la Library existente. NO crea búsqueda, filtros, carpetas ni selección desde
cero, NO rediseña Library y NO cambia el modelo de carpetas, de Media ni de Posts.

**Sustitución explícita** de contratos anteriores:

- Feature 019 FR-001 ("filtros All, Images, Videos y Not used yet. NO DEBE haber filtro "Used"
  ni sorting") queda sustituido por FR-010–FR-030 de esta spec. El resto de FR-001 (ubicación,
  header, `Import media`) sigue vigente.
- La decisión "search y filter son estado local, sin URL" (Feature 019/021, comentario de
  `filterMedia`) queda sustituida por FR-031–FR-038.
- Feature 019 FR-002 (campos de búsqueda) y FR-003 (semántica de "Not used yet") siguen
  vigentes y se precisan en FR-001–FR-009 y FR-014–FR-016.

## Contexto (estado actual verificado en el código)

Contexto para la planificación; el comportamiento exigido está en Requirements.

- **Vistas**: `/p/:projectId/library` (raíz: entradas de carpetas de primer nivel, Unsorted y
  All media; nunca grid), `library/all`, `library/unsorted`, `library/folders/:folderId`, cada una
  con `/:mediaId` opcional para el detail; `library/:mediaId` es el enlace antiguo (detail sobre
  All media); `library/:mediaId/publish` es la tarea Publish.
- **Datos**: la vista pide al backend su lista completa (todo el proyecto, solo Unsorted o solo
  los Media directos de una carpeta), ordenada por fecha de importación descendente con
  desempate por id descendente, con un resumen de uso por Media. No hay paginación.
- **Búsqueda actual**: subcadena única, sin distinguir mayúsculas, sobre title, filename,
  description y hashtags; quita una `#` inicial; NO ignora acentos; NO separa palabras.
- **Filtros actuales**: una única opción excluyente: All, Images, Videos, Not used yet.
- **Estado**: búsqueda, filtro y selección viven solo en la instancia de la vista; se conservan
  al abrir y cerrar el detail dentro de la misma vista y se pierden al recargar, al cambiar de
  vista y al ir a Publish.
- **Publish**: "Back to media" lleva siempre al enlace antiguo (detail sobre All media), así que
  pierde carpeta, búsqueda y filtro.
- **Selección**: cambiar la búsqueda o el filtro NO limpia la selección; Move y Delete actúan
  también sobre Media seleccionados que ya no se ven. Delete muestra un preview del alcance;
  Move no.
- **Uso**: existen dos semánticas. El indicador y el filtro "Not used yet" significan "sin
  ningún Post salvo los cancelados". El booleano de uso del backend significa "publicado o
  esperando acción del usuario en la plataforma". Solo los Posts referencian Media; los Posts
  borrados desaparecen.
- **Patrón existente**: Posts ya persiste búsqueda y destino en query params, actualizados sin
  añadir entradas al historial, y propaga esos params a los enlaces de sus filas.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Encontrar un Media escribiendo parte de su nombre (Priority: P1)

El usuario recuerda vagamente un asset ("cafe verano") y lo escribe en la búsqueda sin acentos
ni mayúsculas y en otro orden. La Library muestra el Media "Café de verano.jpg".

**Why this priority**: es el núcleo de "Find any asset in seconds"; la búsqueda actual falla con
acentos y con varias palabras.

**Independent Test**: con Media de nombres acentuados y varias palabras, escribir consultas sin
acentos, en mayúsculas y con las palabras en otro orden, y comprobar los resultados.

**Acceptance Scenarios**:

1. **Given** un Media titulado "Café de verano", **When** el usuario busca `cafe verano`,
   **Then** el Media aparece en los resultados.
2. **Given** el mismo Media, **When** el usuario busca `VERANO café`, **Then** aparece.
3. **Given** el mismo Media, **When** el usuario busca `cafe invierno`, **Then** NO aparece
   (todas las palabras deben estar).
4. **Given** un Media con el hashtag `summer`, **When** el usuario busca `#summer` o `summer`,
   **Then** aparece.
5. **Given** un Media sin title cuyo filename es `IMG_2045.mov`, **When** el usuario busca
   `img_2045`, **Then** aparece.
6. **Given** un Media cuya description contiene "atardecer en la playa", **When** el usuario
   busca `playa atardecer`, **Then** aparece.

---

### User Story 2 - Combinar filtros para acotar resultados (Priority: P1)

El usuario quiere "los vídeos que todavía no ha usado y que importó este mes". Elige Videos,
Unused y Last 30 days, y la Library muestra solo los Media que cumplen las tres condiciones,
además de la búsqueda si la hay.

**Why this priority**: los filtros excluyentes actuales no permiten esta pregunta, que es
habitual al preparar contenido.

**Independent Test**: con un conjunto conocido de imágenes y vídeos, usados y no usados, y con
distintas fechas de importación, aplicar combinaciones y comprobar los resultados.

**Acceptance Scenarios**:

1. **Given** Media de ambos tipos, usados y no usados, importados en distintas fechas, **When**
   el usuario elige Videos + Unused + Last 30 days, **Then** solo se ven los vídeos sin ningún
   Post no cancelado importados en los últimos 30 días.
2. **Given** esa combinación activa, **When** el usuario además busca `playa`, **Then** se
   aplican la búsqueda y los tres filtros a la vez.
3. **Given** un Media cuyo único Post está cancelado, **When** el filtro es Unused, **Then**
   aparece; **When** es Used, **Then** no aparece.
4. **Given** un Media con un borrador, un Post programado o un Post fallido, **When** el filtro
   es Used, **Then** aparece; **When** es Unused, **Then** no aparece.
5. **Given** filtros activos, **When** el usuario quita uno desde su chip, **Then** solo esa
   dimensión vuelve a su valor por defecto y los resultados se actualizan.
6. **Given** filtros activos y una búsqueda, **When** el usuario pulsa `Clear all`, **Then** los
   filtros vuelven a sus valores por defecto y la búsqueda se conserva.

---

### User Story 3 - Seleccionar en bloque sin afectar a Media ocultos (Priority: P1)

El usuario está en Select, ha marcado varios Media y cambia la búsqueda o un filtro. La
selección se vacía, así que Move y Delete nunca actúan sobre Media que ya no ve.

**Why this priority**: es un riesgo de seguridad UX que existe hoy (Move sin preview sobre Media
ocultos) y que se agravaría con más filtros.

**Independent Test**: seleccionar Media, cambiar cada control que altera el conjunto visible y
comprobar que la selección queda vacía; cambiar solo el orden y comprobar que se conserva.

**Acceptance Scenarios**:

1. **Given** Select activo con 3 Media marcados, **When** el usuario cambia la búsqueda,
   **Then** la selección queda vacía y Move y Delete se deshabilitan.
2. **Given** lo mismo, **When** cambia Media type, Usage o Imported, quita un chip o pulsa
   `Clear all` o `Clear search`, **Then** la selección queda vacía.
3. **Given** Select activo con 3 Media marcados, **When** el usuario cambia solo el orden,
   **Then** los 3 siguen marcados.
4. **Given** Select activo, **When** los params de la URL cambian por back/forward, **Then** se
   aplica la misma regla: la selección se vacía si cambian la búsqueda o los filtros.
5. **Given** cualquier secuencia de cambios, **When** el usuario pulsa Move o Delete, **Then**
   los Media afectados son exactamente los marcados y visibles en ese momento.

---

### User Story 4 - Volver a los mismos resultados tras abrir un Media o ir a Publish (Priority: P2)

El usuario filtra y busca, abre un Media, lo revisa, entra en Publish y vuelve. Encuentra la
misma vista, la misma búsqueda, los mismos filtros y el mismo orden.

**Why this priority**: sin esto, cada consulta a un asset obliga a rehacer la búsqueda.

**Independent Test**: con búsqueda, filtros y orden no por defecto en una carpeta, abrir un
Media, cerrarlo, abrir otro, ir a Publish, volver con "Back to media" y cerrar el detail.

**Acceptance Scenarios**:

1. **Given** una carpeta con búsqueda, filtros y orden aplicados, **When** el usuario abre un
   Media, **Then** la URL del detail conserva la vista y todos esos params.
2. **Given** el detail abierto, **When** el usuario lo cierra (Close, Back o Escape según el
   viewport), **Then** vuelve a la misma vista con los mismos params y el foco en la card de
   origen.
3. **Given** el detail abierto desde una carpeta filtrada, **When** el usuario entra en Publish
   y pulsa "Back to media", **Then** vuelve al detail en esa carpeta con los mismos params.
4. **Given** la URL de una vista filtrada, **When** el usuario recarga o la abre en otra
   pestaña, **Then** ve la misma vista con la misma búsqueda, filtros y orden.
5. **Given** cambios sucesivos de búsqueda y filtros, **When** el usuario pulsa back, **Then**
   el navegador vuelve a la página anterior a la Library, no a cada estado intermedio.

---

### User Story 5 - Ordenar los resultados (Priority: P2)

El usuario ordena la vista por Newest, Oldest, Name A–Z o Name Z–A.

**Why this priority**: localizar por nombre o por antigüedad es frecuente; hoy el orden es fijo.

**Independent Test**: con nombres y fechas conocidos, cambiar el orden y comprobar la secuencia,
incluidos los empates.

**Acceptance Scenarios**:

1. **Given** el orden por defecto, **When** se abre la vista, **Then** el orden es Newest e
   idéntico al actual.
2. **Given** Media llamados "b", "Á", "a10" y "a2", **When** el orden es Name A–Z, **Then** el
   orden es alfabético según el idioma del usuario, sin distinguir mayúsculas ni penalizar
   acentos.
3. **Given** dos Media con el mismo nombre visible, **When** se ordena por nombre, **Then** su
   orden relativo es estable y predecible entre recargas.
4. **Given** búsqueda y filtros activos, **When** el usuario cambia el orden, **Then** el
   conjunto de resultados no cambia, solo su orden.

---

### User Story 6 - Ampliar a All media cuando la carpeta no tiene el asset (Priority: P2)

El usuario busca dentro de una carpeta o de Unsorted y no hay resultados. Se le ofrece `Search
all media`, que repite la misma búsqueda, filtros y orden en All media.

**Why this priority**: la búsqueda es por vista y no recursiva; sin esta salida, el usuario cree
que el asset no existe.

**Independent Test**: buscar en una carpeta un Media que está en otra carpeta y seguir `Search
all media`.

**Acceptance Scenarios**:

1. **Given** una carpeta donde la búsqueda `playa` no tiene resultados, **When** el usuario
   pulsa `Search all media`, **Then** navega a All media con `playa` y los mismos filtros y
   orden.
2. **Given** All media, **When** una búsqueda no tiene resultados, **Then** NO se ofrece `Search
   all media`.
3. **Given** una carpeta con subcarpetas, **When** el usuario busca, **Then** solo se buscan los
   Media directos de la carpeta y las entradas de las subcarpetas siguen visibles sin filtrar.

---

### User Story 7 - Buscar y filtrar en el móvil sin perder el grid (Priority: P2)

En un móvil de 375–390 px el usuario tiene la búsqueda a ancho completo, un control `Filters`
que abre un panel inferior con Media type, Usage e Imported, el orden accesible y los filtros
activos como chips en una sola fila desplazable.

**Why this priority**: añadir dimensiones a la toolbar actual la saturaría en móvil.

**Independent Test**: a 375 px, aplicar y quitar filtros, ordenar y buscar, y comprobar que no
hay overflow horizontal y que el grid sigue en la primera pantalla.

**Acceptance Scenarios**:

1. **Given** un viewport de 375 px, **When** se abre una vista con Media, **Then** se ven la
   búsqueda a ancho completo y una sola fila de controles (`Filters` y orden), sin scroll
   horizontal de la página.
2. **Given** el panel Filters abierto, **When** el usuario cambia Media type, Usage o Imported,
   **Then** los resultados se actualizan y puede cerrar el panel o pulsar `Clear filters`.
3. **Given** filtros activos, **When** el panel está cerrado, **Then** el control `Filters`
   indica cuántos hay activos y los chips aparecen en una fila desplazable.
4. **Given** el panel abierto, **When** el usuario lo cierra, **Then** el foco vuelve al control
   `Filters`.

---

### User Story 8 - Entender por qué no hay resultados (Priority: P3)

Cuando no hay nada que mostrar, la Library distingue entre "no hay Media aquí", "la búsqueda no
encuentra nada" y "los filtros no dejan nada", y ofrece la acción adecuada.

**Why this priority**: mejora la comprensión; depende de las historias anteriores.

**Independent Test**: provocar cada estado vacío y comprobar mensaje y acciones.

**Acceptance Scenarios**:

1. **Given** una Library sin Media, **When** se abre la raíz, **Then** se mantiene la dropzone
   actual.
2. **Given** una carpeta o Unsorted sin Media, **When** se abre, **Then** se mantiene el mensaje
   actual sin acciones de búsqueda ni filtro.
3. **Given** una búsqueda sin resultados y filtros por defecto, **When** se muestra el estado
   vacío, **Then** ofrece `Clear search` y, en carpeta o Unsorted, `Search all media`.
4. **Given** filtros sin resultados y sin búsqueda, **When** se muestra el estado vacío,
   **Then** ofrece `Clear filters`.
5. **Given** búsqueda y filtros sin resultados, **When** se muestra el estado vacío, **Then**
   ofrece `Clear search` y `Clear filters` y, en carpeta o Unsorted, `Search all media`.

### Edge Cases

- **Consulta solo con espacios o con `#` sueltas**: equivale a no buscar.
- **Caracteres especiales** (`_`, `-`, `.`, `%`, `(`, emojis): se buscan literalmente como
  texto; nunca se interpretan como comodines ni rompen la búsqueda.
- **Consulta muy larga**: se acepta sin error; su longitud no la limita la feature, más allá de
  lo que admita el navegador en la URL.
- **Media sin title**: el nombre visible y el orden por nombre usan el filename.
- **Dos Media con el mismo nombre visible o la misma fecha de importación**: el desempate es
  estable.
- **Params inválidos o desconocidos** en la URL (`?type=gif`, `?sort=size`, `?imported=365`):
  se ignoran y se usan los valores por defecto, sin error.
- **Deep link al detail de un Media que la búsqueda o los filtros excluyen** (p. ej.
  `?type=videos` con una imagen): el detail se abre igualmente (FR-080); el grid muestra solo los
  resultados filtrados y ninguna card aparece marcada; al cerrar se vuelve a la misma vista con
  los mismos params y el foco va a un destino predecible de Library (FR-082).
- **Editar el title, la description o los hashtags en el detail** de forma que el Media deje de
  coincidir (p. ej. búsqueda `summer` y se quita "summer" del title): la edición se completa con
  normalidad, la lista puede refrescarse, el detail NO se cierra; al cerrarlo, el Media ya no
  aparece en el grid filtrado y el foco va a un destino predecible (FR-081, FR-082).
- **Mover desde el detail a otra carpeta**: el detail sigue al Media a su nueva carpeta (como
  hoy) y conserva búsqueda, filtros y orden.
- **Media de otra vista**: abrir el detail de un Media que no pertenece a la vista sigue
  llevando al detail sobre All media (como hoy) y conserva los params.
- **Borrar o mover desde una vista filtrada**: los avisos, el foco y la recarga funcionan como
  hoy y la vista conserva sus params.
- **Imported con un Media importado justo en el límite**: el rango es continuo hasta el
  instante actual (ver Assumptions); un Media importado hace exactamente 7 días está en el
  límite inclusivo.
- **Reloj o zona horaria del usuario**: el rango se calcula desde el instante actual, no por
  días naturales, así que la zona horaria no cambia el resultado.
- **Un Media importado mientras hay filtros activos**: tras el import, la vista se recarga y el
  Media aparece solo si cumple los filtros; el panel de import sigue enlazando a su detail.
- **Import en una vista con búsqueda**: no limpia la búsqueda ni los filtros.
- **Raíz de Library**: no tiene búsqueda, filtros ni orden (como hoy); llegar con params a la
  raíz no tiene efecto.
- **Entrar en Publish sin contexto de Library** (enlace directo, onboarding, otra sección):
  "Back to media" conserva su destino actual (detail sobre All media).
- **Media con datos de uso incompletos** (sin Posts): es Unused.

## Requirements *(mandatory)*

### Functional Requirements

#### Búsqueda

- **FR-001**: La búsqueda DEBE cubrir title, filename original, description y hashtags de cada
  Media, y NO otros campos.
- **FR-002**: La búsqueda DEBE ignorar mayúsculas y minúsculas.
- **FR-003**: La búsqueda DEBE ignorar diacríticos en la consulta y en el texto (`cafe`
  encuentra `Café`, `nino` encuentra `Niño`).
- **FR-004**: La consulta DEBE dividirse en palabras separadas por espacios; un Media coincide
  solo si TODAS las palabras aparecen como subcadena en alguno de sus campos buscables, sin
  importar el orden ni que estén en campos distintos.
- **FR-005**: Una `#` al inicio de una palabra DEBE ignorarse, de modo que `#summer` y `summer`
  den el mismo resultado; las palabras vacías tras quitarla se descartan.
- **FR-006**: Una consulta sin palabras útiles DEBE equivaler a no buscar.
- **FR-007**: Los caracteres especiales DEBEN tratarse como texto literal.
- **FR-008**: Los resultados DEBEN actualizarse mientras el usuario escribe, sin pulsar ningún
  botón.
- **FR-009**: NO DEBE haber búsqueda aproximada, corrección de errores, sinónimos ni búsqueda
  semántica.

#### Filtros y combinación

- **FR-010**: La Library DEBE ofrecer tres dimensiones de filtro independientes: **Media type**
  (All, Images, Videos), **Usage** (All, Used, Unused) e **Imported** (Any time, Last 7 days,
  Last 30 days, Last 90 days).
- **FR-011**: En cada dimensión DEBE haber exactamente un valor activo; el valor por defecto es
  All, All y Any time.
- **FR-012**: Las dimensiones DEBEN combinarse entre sí y con la búsqueda mediante AND. La
  vista actual (All media, Unsorted o carpeta) delimita el universo sobre el que se aplican.
- **FR-013**: Media type DEBE filtrar por el tipo del Media (imagen o vídeo).
- **FR-014**: **Used** DEBE significar "el Media tiene al menos un Post no cancelado" en
  cualquier estado (borrador, programado, publicando, publicado, fallido, esperando acción o
  que necesita atención), en cualquier cuenta.
- **FR-015**: **Unused** DEBE significar "el Media no tiene ningún Post salvo los cancelados",
  la misma semántica del indicador "Not used yet" (Feature 019 FR-003). Used y Unused DEBEN
  formar una partición completa: cada Media es exactamente uno de los dos.
- **FR-016**: Used/Unused NO DEBE derivarse del indicador "publicado" del resumen de uso; DEBE
  calcularse con los recuentos de Posts existentes. Los Posts cancelados no cuentan; los Posts
  borrados no existen.
- **FR-017**: Imported DEBE filtrar por la fecha de importación del Media: Last N days incluye
  los Media importados en las últimas N × 24 horas hasta el instante actual.
- **FR-018**: NO DEBE haber selector de fechas ni rangos desde/hasta.
- **FR-019**: El indicador de uso de cada card ("Not used yet", Drafts, etc.) NO DEBE cambiar.

#### Filtros activos

- **FR-020**: Cuando alguna dimensión tenga un valor distinto del por defecto, la Library DEBE
  mostrar cada filtro activo como un elemento identificable (p. ej. "Videos", "Unused", "Last 30
  days").
- **FR-021**: Cada filtro activo DEBE poder quitarse de forma individual, lo que devuelve solo
  esa dimensión a su valor por defecto.
- **FR-022**: Con al menos un filtro activo DEBE haber `Clear all`, que devuelve las tres
  dimensiones a su valor por defecto y conserva la búsqueda y el orden.
- **FR-023**: Con una búsqueda no vacía DEBE haber una acción separada para limpiar la búsqueda,
  que conserva filtros y orden.
- **FR-024**: Ni el orden ni la vista (carpeta, Unsorted, All media) DEBEN aparecer como filtros
  activos.
- **FR-025**: *(Retirado.)* El recuento de la vista se mantiene como hoy. Mostrar "X of Y
  media" con búsqueda o filtros es una mejora opcional que el planning puede adoptar si encaja de
  forma natural; NO es requisito, NO genera tasks y NO bloquea la aceptación.

#### Ordenación

- **FR-026**: La Library DEBE ofrecer los órdenes **Newest**, **Oldest**, **Name A–Z** y **Name
  Z–A**. El valor por defecto es Newest.
- **FR-027**: Newest DEBE reproducir el orden actual: fecha de importación descendente y
  desempate por identidad descendente. Oldest DEBE ser exactamente su inverso.
- **FR-028**: Name A–Z y Z–A DEBEN ordenar por el nombre visible (title, o filename si no hay
  title), de forma alfabética según el idioma del usuario, sin distinguir mayúsculas, con acentos
  junto a su letra base y con los números en orden natural ("a2" antes que "a10"). Los empates
  DEBEN resolverse según Newest.
- **FR-029**: Cambiar el orden NO DEBE cambiar el conjunto de resultados.
- **FR-030**: NO DEBE haber orden por uso reciente, más usados, tamaño ni duración.

#### Estado en URL

- **FR-031**: La búsqueda, Media type, Usage, Imported y el orden DEBEN persistirse en query
  params de la URL de la vista: `q`, `type` (`images` | `videos`), `usage` (`used` | `unused`),
  `imported` (`7d` | `30d` | `90d`) y `sort` (`oldest` | `name-asc` | `name-desc`).
- **FR-032**: Los valores por defecto DEBEN omitirse de la URL; una vista sin búsqueda, filtros
  ni orden no por defecto tiene una URL sin estos params.
- **FR-033**: Los cambios de búsqueda, filtros y orden DEBEN actualizar la URL sustituyendo la
  entrada actual del historial, sin crear una entrada por tecla ni por cambio, siguiendo el
  patrón existente de Posts.
- **FR-034**: Cargar o recargar una URL con estos params DEBE restaurar la búsqueda, los filtros
  y el orden; la URL DEBE ser compartible dentro de la misma instalación.
- **FR-035**: Los valores inválidos o desconocidos DEBEN ignorarse y tratarse como el valor por
  defecto, sin error visible.
- **FR-036**: Back y forward DEBEN restaurar el estado de la URL a la que se llega, incluida la
  búsqueda, los filtros y el orden.
- **FR-037**: El path DEBE seguir representando la vista (All media, Unsorted, carpeta) y el
  Media del detail; búsqueda, filtros y orden NO DEBEN codificarse en el path.
- **FR-038**: Los params DEBEN ser independientes de la vista: el mismo `q`, `type`, `usage`,
  `imported` y `sort` significan lo mismo en All media, Unsorted y cualquier carpeta.

#### Detail y Publish

- **FR-039**: Abrir un Media desde el grid DEBE conservar la vista y todos los params.
- **FR-040**: Cerrar el detail (Close, Back o Escape, según el viewport) DEBE volver a la misma
  vista con los mismos params, manteniendo la restauración de foco actual en la card de origen
  cuando esa card siga en los resultados (si no, FR-082).
- **FR-041**: El comportamiento actual de scroll al volver del detail DEBE mantenerse; NO DEBE
  añadirse persistencia de scroll nueva.
- **FR-042**: Las navegaciones existentes desde la vista (mover el Media abierto, mover o borrar
  desde una card, borrar desde el detail, borrar en bloque, borrar o renombrar carpeta dentro de
  la vista, redirección al detail sobre All media) DEBEN conservar los params cuando el destino
  sea una vista de Media. Ir a la raíz de Library (p. ej. tras borrar una carpeta de primer
  nivel) puede descartarlos.
- **FR-043**: El viaje Library → Publish → "Back to media" DEBE restaurar la vista o carpeta
  original, la búsqueda, los filtros y el orden, y volver al detail del Media en esa vista. El
  mecanismo para transportar ese contexto (query params, ubicación de retorno o estado de
  navegación) lo decide el planning, eligiendo el patrón existente más pequeño y robusto. La
  entrada directa a Publish sin contexto de Library DEBE conservar su destino actual de "Back to
  media".
- **FR-044**: Publish NO DEBE rediseñarse; sus propios params (p. ej. `posts`) DEBEN seguir
  funcionando y no colisionar con el contexto de Library.
- **FR-080**: Una URL con un Media válido de la vista DEBE abrir su detail aunque el Media no
  coincida con la búsqueda, Media type, Usage o Imported. La búsqueda y los filtros solo deciden
  qué cards muestra el grid; NUNCA invalidan ni redirigen un enlace directo a un Media. Si el
  Media no pertenece a la vista por su carpeta, se mantiene la redirección actual al detail sobre
  All media, conservando los params de Library.
- **FR-081**: El detail NO DEBE cerrarse automáticamente porque su Media deje de coincidir con
  la búsqueda o los filtros, ya sea por una edición (title, description, hashtags) o por otra
  operación desde el detail (p. ej. un cambio de uso). La operación se completa con normalidad y
  la lista puede refrescarse; al cerrar el detail, el grid muestra solo los resultados que
  coinciden en ese momento.
- **FR-082**: Si al cerrar el detail su card de origen no está en los resultados (excluida por
  un deep link, por una edición o por otra operación), el foco DEBE ir a un destino predecible de
  Library (p. ej. el encabezado, los resultados o la toolbar, según el patrón existente que fije
  el planning) y NUNCA al inicio del documento ni al `body`.

#### Carpetas y Search all media

- **FR-045**: La búsqueda y los filtros DEBEN aplicarse solo a la vista actual: All media (todo
  el proyecto), Unsorted (solo Unsorted) o una carpeta (solo sus Media directos).
- **FR-046**: NO DEBE haber búsqueda recursiva en subcarpetas ni un selector permanente de
  alcance.
- **FR-047**: Las entradas de subcarpetas de una carpeta DEBEN seguir visibles y sin filtrar
  mientras haya búsqueda o filtros.
- **FR-048**: Cuando en Unsorted o en una carpeta haya una búsqueda no vacía con cero
  resultados, DEBE ofrecerse la acción secundaria `Search all media`, que navega a All media
  conservando la búsqueda, los tres filtros y el orden.
- **FR-049**: `Search all media` NO DEBE ofrecerse en All media ni cuando no hay búsqueda.
- **FR-050**: Root, All media, Unsorted, carpetas anidadas, profundidad máxima, breadcrumbs,
  Move, import y crear/renombrar/borrar carpetas DEBEN comportarse como hoy. Las carpetas NO
  DEBEN representarse como filtro activo.

#### Selección

- **FR-051**: Con Select activo, cualquier cambio de la búsqueda, Media type, Usage o Imported
  (escribir, borrar, quitar un chip, `Clear all`, `Clear search`, el panel Filters, back/forward
  o `Search all media`) DEBE vaciar la selección por completo.
- **FR-052**: Vaciar la selección NO DEBE salir de Select: el modo sigue activo con 0
  seleccionados y Move y Delete quedan deshabilitados, como hoy con 0 seleccionados.
- **FR-053**: Cambiar solo el orden NO DEBE modificar la selección.
- **FR-054**: Cambiar de vista DEBE seguir reiniciando la selección, como hoy.
- **FR-055**: Move y Delete en bloque NUNCA DEBEN incluir un Media que no esté visible en los
  resultados en el momento de pulsarlos. Se mantiene el comportamiento actual por el que, tras
  una recarga, los Media que salieron de la vista dejan de estar seleccionados.
- **FR-056**: NO DEBE añadirse contador de ocultos, selección global ni acciones bulk nuevas.

#### Estados vacíos

- **FR-057**: La Library vacía DEBE mantener la dropzone actual; una carpeta o Unsorted vacíos
  DEBEN mantener su mensaje actual, sin acciones de búsqueda ni filtro.
- **FR-058**: Si la vista tiene Media pero la búsqueda y los filtros no dejan ninguno, DEBE
  mostrarse un estado vacío que diga qué lo provoca (búsqueda, filtros o ambos) y ofrezca las
  acciones pertinentes: `Clear search` si hay búsqueda, `Clear filters` si hay filtros, y
  `Search all media` según FR-048. Con varias acciones, una es la principal y el resto
  secundarias.
- **FR-059**: Los estados vacíos DEBEN reutilizar el componente de estado vacío existente del
  design system y NO DEBEN confundirse con "Library vacía".
- **FR-060**: Mientras la vista no tenga Media, la búsqueda, los filtros y el orden NO DEBEN
  mostrarse (como hoy), aunque la URL traiga params.

#### Desktop

- **FR-061**: En viewports a partir del breakpoint medio existente, la búsqueda, Media type,
  Usage, Imported y el orden DEBEN ser accesibles directamente en la toolbar, sin abrir paneles.
- **FR-062**: La toolbar NO DEBE crecer más de dos filas de controles (búsqueda y filtros, y
  filtros activos cuando existan) en viewports de 1024 px o más, y el grid DEBE seguir siendo el
  elemento principal.
- **FR-063**: Los controles DEBEN reutilizar patrones existentes del design system (campo de
  búsqueda, grupo de opciones o control segmentado, select o menú, badges o botones); NO DEBE
  crearse un lenguaje visual nuevo.

#### Mobile

- **FR-064**: Por debajo del breakpoint medio existente, la búsqueda DEBE ocupar el ancho
  completo en su propia fila, seguida de una sola fila con un control `Filters` y el orden.
- **FR-065**: `Filters` DEBE abrir un panel inferior (sheet) del design system con Media type,
  Usage e Imported, que aplica los cambios al momento y permite cerrarlo y `Clear filters`.
- **FR-066**: Con filtros activos, `Filters` DEBE indicar cuántos hay y los filtros activos
  DEBEN mostrarse en una única fila desplazable horizontalmente, sin desplazar la página.
- **FR-067**: El orden DEBE poder cambiarse sin abrir el panel Filters.
- **FR-068**: El chrome persistente de búsqueda y filtros de la Library (la búsqueda, la fila
  `Filters`/orden y la fila de filtros activos) NO DEBE ocupar más de aproximadamente un tercio
  de la altura de un viewport de 375 × 667 px, y con el panel Filters cerrado el grid DEBE ser el
  contenido visual dominante. Esta restricción NO aplica al panel Filters abierto, que es una
  superficie temporal y puede ocupar la altura normal de un sheet del design system.
- **FR-069**: Ningún viewport entre 375 y 1280 px DEBE tener scroll horizontal de página por
  culpa de estos controles.

#### Accesibilidad

- **FR-070**: La búsqueda, cada dimensión de filtro y el orden DEBEN tener un nombre accesible
  visible o equivalente; cada dimensión DEBE presentarse como un grupo con su nombre.
- **FR-071**: Cada filtro activo DEBE poder quitarse con teclado y su acción DEBE tener un
  nombre accesible que indique qué quita (p. ej. "Remove filter: Videos").
- **FR-072**: Al quitar un filtro activo, el foco DEBE pasar al siguiente filtro activo, o a un
  control estable de la toolbar si no queda ninguno; nunca al inicio del documento.
- **FR-073**: El panel Filters DEBE comportarse como un diálogo modal: foco dentro mientras está
  abierto, cierre con Escape y foco de vuelta a `Filters`.
- **FR-074**: Los cambios en el número de resultados DEBEN anunciarse a lectores de pantalla sin
  robar el foco ni anunciar cada tecla de forma redundante.
- **FR-075**: Vaciar la selección por un cambio de búsqueda o filtro DEBE reflejarse en el
  recuento de seleccionados anunciado por la barra de selección existente.
- **FR-076**: Todos los controles nuevos DEBEN ser operables con teclado y respetar el tamaño
  táctil y los estilos de foco existentes.

#### Arquitectura y alcance

- **FR-077**: La búsqueda, los filtros y el orden DEBEN calcularse en el cliente sobre la lista
  que la vista ya carga; el contrato de la API de listado NO DEBE cambiar.
- **FR-078**: NO DEBE añadirse ningún endpoint, parámetro de backend, modelo, migración, índice,
  búsqueda de texto completo, caché, paginación, virtualización, miniaturas, carga diferida de
  vídeos ni "Show more".
- **FR-079**: La lógica de coincidencia, filtrado, uso y orden DEBE poder verificarse de forma
  aislada, sin interfaz.

### Key Entities

- **Media**: asset de la Library. Atributos relevantes: title, filename original, description,
  hashtags, tipo (imagen o vídeo), fecha de importación, carpeta (o Unsorted) y resumen de uso.
- **Resumen de uso de un Media**: recuentos de sus Posts por estado, incluido cuántos hay y
  cuántos están cancelados; base de Used/Unused.
- **Estado de consulta de la Library**: búsqueda, Media type, Usage, Imported y orden; vive en
  la URL, es independiente de la vista y tiene valores por defecto omitibles.
- **Vista de Library**: All media, Unsorted o una carpeta; delimita el universo de la consulta y
  vive en el path.
- **Selección**: conjunto de Media marcados en Select, siempre un subconjunto de los resultados
  visibles.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En un conjunto de prueba con nombres acentuados y de varias palabras, el 100 % de
  las consultas sin acentos, en cualquier combinación de mayúsculas y con las palabras en
  cualquier orden, encuentran el Media buscado.
- **SC-002**: Un usuario localiza un Media conocido en una Library de 1.000 Media en menos de
  10 segundos escribiendo parte de su nombre, sin cambiar de vista si el Media está en ella.
- **SC-003**: Los resultados se actualizan de forma perceptiblemente inmediata (menos de 100 ms
  por tecla) con 1.000 Media cargados en la vista.
- **SC-004**: El 100 % de las combinaciones de Media type × Usage × Imported (36) devuelven
  exactamente los Media que cumplen todas sus condiciones en el conjunto de prueba.
- **SC-005**: Used y Unused suman exactamente el total de la vista en el 100 % de los casos de
  prueba.
- **SC-006**: Recargar, abrir en otra pestaña o navegar con back/forward a una URL de vista con
  búsqueda, filtros y orden restaura el mismo resultado en el 100 % de los casos de prueba.
- **SC-007**: Abrir y cerrar un Media, y el viaje detail → Publish → "Back to media" → cerrar,
  vuelven a la misma vista y los mismos resultados en el 100 % de los casos de prueba, incluidos
  los deep links a Media excluidos por los filtros y los Media que dejan de coincidir tras
  editarlos; en ningún caso el foco termina en el inicio del documento.
- **SC-008**: Cero acciones Move o Delete en bloque incluyen un Media no visible tras cualquier
  secuencia de cambios de búsqueda o filtro.
- **SC-009**: A 375 y 390 px no hay scroll horizontal de página y, con el panel Filters cerrado,
  el chrome persistente (búsqueda, fila `Filters`/orden y filtros activos) ocupa como máximo
  aproximadamente un tercio de la altura de 667 px.
- **SC-010**: Las regresiones existentes de carpetas, detail, import, move y delete siguen
  pasando, con cambios solo en las aserciones de los controles sustituidos (p. ej. el filtro
  "Not used yet" pasa a Usage = Unused).

## Testing y criterios de aceptación

Las pruebas verifican nuestro contrato, no el navegador ni librerías externas.

- **Lógica aislada**: búsqueda sin mayúsculas y sin acentos; varias palabras con AND; hashtags
  con y sin `#`; description; title y filename; caracteres especiales; consulta vacía; Media
  type; partición exhaustiva Used/Unused (sin Posts, solo cancelados, borrador, programado,
  fallido, publicado, mezcla); límites de Imported; filtros combinados; los cuatro órdenes;
  desempates estables; nombre visible sin title.
- **URL**: lectura y escritura; omisión de valores por defecto; valores inválidos; sustitución
  de la entrada de historial; deep link y recarga; back/forward.
- **Library**: el detail conserva los params al abrirse y al cerrarse; deep link a un Media
  excluido por los filtros abre el detail; editar un Media para que deje de coincidir no cierra
  el detail y al cerrarlo la card ya no está y el foco va a un destino predecible; "Back to media"
  desde Publish devuelve el contexto y sin contexto conserva su destino actual; `Search all media`; filtros activos; quitar uno; `Clear all`
  conserva la búsqueda; `Clear search` conserva los filtros; estado vacío por búsqueda, por
  filtros y por ambos; las navegaciones de mover y borrar conservan los params.
- **Selección**: cambiar la búsqueda, el tipo, el uso, la fecha, un chip, `Clear all` y
  back/forward vacía la selección; el orden la conserva; cambiar de vista mantiene el reinicio
  actual; Move y Delete reciben solo ids visibles.
- **Responsive**: estructura de controles en escritorio (inline) y en móvil (búsqueda, `Filters`
  con panel, orden, chips), sin tests de píxeles; revisión manual a 375, 390, 768, 1024 y 1280
  px.

## Non-goals

Tags; smart folders; búsquedas guardadas; búsqueda recursiva en subcarpetas; búsqueda global
permanente desde cualquier carpeta o selector de alcance; búsqueda aproximada, semántica,
embeddings o IA; filtro de metadata completa, de duración, de orientación o de plataforma; orden
por uso reciente, más usados, tamaño o duración; selector de fechas; paginación, virtualización,
miniaturas, carga diferida de vídeos o "Show more"; cambios de backend; detección de duplicados;
acciones bulk nuevas o selección global; analytics; persistencia de scroll nueva; cambios en la
raíz de Library, el modelo de carpetas, Publish o el indicador de uso de las cards; cambios en la
semántica de uso del onboarding ("primer Media sin usar"), que sigue usando su propia definición.

## Assumptions

- La Library es de un solo usuario local; "compartible" significa abrir la misma URL en la misma
  instalación (otra pestaña, otro dispositivo de la misma red, marcador).
- Last N days es un rango continuo de N × 24 horas hasta el instante de evaluación, no días
  naturales; se evalúa al calcular los resultados, sin refresco periódico.
- El valor del filtro se llama "Unused" y el indicador de las cards sigue siendo "Not used yet";
  ambos significan lo mismo.
- El orden por nombre usa las capacidades de comparación según idioma del navegador; la
  ordenación natural de números es razonable y no requiere configuración.
- Los cambios en el panel Filters de móvil se aplican al momento (como en escritorio), así que
  basta con cerrarlo; no hay botón "Apply" que confirme.
- La raíz de Library no recibe búsqueda, filtros ni orden.
- El rendimiento de render con 10.000 Media (cards completas, previews de vídeo) es un problema
  conocido y anterior, fuera de esta feature; la búsqueda y los filtros no lo empeoran.
- Se reutilizan los breakpoints actuales de Library y Media detail; si el planning demuestra que
  falta uno, se justificará allí.
- "X of Y media" no forma parte del alcance obligatorio (FR-025 retirado); puede añadirse en el
  planning o la implementación solo si encaja de forma natural.
- El nombre exacto de los params de URL (FR-031) puede ajustarse en el planning si choca con un
  param existente, manteniendo sus valores y su semántica.
