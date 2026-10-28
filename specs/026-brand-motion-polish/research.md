# Research: Feature 026 — Brand & Motion Polish

Decisiones técnicas que resuelven la spec contra el código real (`main` en `a0c5ca5`). Cada
apartado: Decision / Rationale / Alternatives considered.

## R1. Nivel de énfasis y política de motion

- **Decision**:
  - Añadir solo `--motion-emphasis: 360ms` en `ui/tokens.css`, que pasa a `0ms` en el bloque
    reduced-motion existente.
  - **No** se añade `--motion-easing-emphasis`: el `--motion-easing-out` actual
    (`cubic-bezier(0, 0, 0.2, 1)`) ya es una salida suave sin overshoot.
  - Duraciones derivadas, siempre como `calc()` del token (así reduced motion las lleva a 0 sin
    reglas nuevas):
    - pulso acotado: ciclo `calc(var(--motion-emphasis) * 3)` ≈ 1,08 s, **3 iteraciones** ≈ 3,2 s;
    - highlight: `calc(var(--motion-emphasis) * 4)` ≈ 1,44 s.
  - Política "bounded": ninguna animación nueva usa `infinite`; el único `infinite` del
    producto sigue siendo `ap-spin` (spinner de botón, preexistente y fuera de alcance).
- **Rationale**: un solo nivel nuevo (spec FR-002). Derivar de un token mantiene una única
  fuente y un único interruptor de reduced motion. 3 ciclos < 5 s cumple FR-005a / WCAG 2.2.2.
- **Alternatives**:
  - Un token por uso (`--motion-pulse`, `--motion-highlight`): rechazado, es un "framework".
  - Curva propia con overshoot: prohibido por la spec.

## R2. Reduced motion y `animationend`

- **Decision**:
  - Toda animación nueva usa keyframes solo con `from` (o con `50%` en el pulso). Sin
    `animation-fill-mode: forwards`, así el estado final es el estilo natural del elemento.
  - La limpieza del estado efímero (énfasis, highlights) se hace en `onAnimationEnd`, filtrando
    por `animationName`.
  - **Sin timeout de respaldo.**
- **Rationale**:
  - La regla global (`tokens.css`) fuerza `animation-duration: 0.01ms !important` e
    `iteration-count: 1`. La animación sigue existiendo, así que el navegador sigue emitiendo
    `animationend`: la limpieza funciona igual con reduced motion.
  - Si una animación no llega a correr (elemento con `hidden` o `display: none`, CSS no
    cargado), el atributo `data-*` queda puesto. Como los keyframes terminan en el estilo
    natural, un atributo residual es **visualmente inerte**; desaparece al desmontar la vista o
    con el siguiente cambio de estado.
  - Un timeout atado a la duración CSS duplicaría la fuente de verdad y fallaría al cambiar el
    token.
- **Alternatives**: timeout de respaldo (rechazado por lo anterior); Web Animations API
  (innecesaria, más JS).

## R3. Iluminación ambiental de Login/Auth

- **Decision**:
  - Una capa de fondo en las clases que solo existen en las superficies de autenticación:
    `.ap-login` y `.ap-auth-loading` (la segunda también la usa el `<main>` del error de sesión
    en `AuthGate`).
  - Forma: `radial-gradient(<elipse> at 50% 30%, var(--color-auth-glow), transparent 70%)` sobre
    `var(--color-sidebar)`.
  - Token semántico nuevo `--color-auth-glow: rgb(66 99 78 / 0.28)` (moss-600 al 28 %).
  - Ni pseudo-elemento ni JS.
- **Rationale**:
  - Las dos clases se definen solo en `pages/login/login.css` y solo las usan `LoginPage` y
    `AuthGate`, así que no hay fuga al AppShell, que usa `.ap-shell`. El fondo se pinta en la
    propia capa del marco: sin stacking context ni `z-index` nuevos.
  - Contraste calculado contra la mezcla en el punto más brillante, con moss-600 sobre night-900:

    | Texto | 0 % | 20 % | 30 % | 40 % |
    |---|---|---|---|---|
    | Secundario `--night-300` | 7,15 | 6,13 | 5,61 | 5,09 |
    | Wordmark `--night-50` | 16,2 | 13,9 | 12,7 | 11,5 |
    | Foco `--moss-200` | 9,27 | 7,96 | 7,28 | 6,61 |

    Con 28 % todo queda ≥ 5,6:1 (AA 4,5). El panel blanco del Login es opaco: su contraste no
    cambia.
- **Alternatives**:
  - Pseudo-elemento `::before`: equivalente, pero añade posicionamiento.
  - Gradiente animado: prohibido (FR-006).

## R4. Entrada del Login y gesto del monograma

- **Decision**:
  - El panel (`.ap-login__card`) reutiliza el keyframe existente `ap-rise-in` (fade + 0,5 rem)
    con `var(--motion-emphasis) var(--motion-easing-out)`, sin delay.
  - Monograma: solo dentro del Login (`.ap-login__title .ap-mark::after`), keyframe nuevo
    `ap-mark-bar`: `from { scale: 0 1; }` con `transform-origin: left center`, la misma
    duración y sin delay. La barra crece desde la izquierda hasta su sitio.
  - Total ≤ 360 ms (SC-001 pide ≤ 400 ms).
- **Rationale**:
  - El `autoFocus` del input no depende de la opacidad: el foco y la escritura funcionan desde
    el primer frame.
  - No hay timers ni estado React: CSS al montar, una sola vez (el Login no se re-monta mientras
    el usuario escribe; el error se renderiza dentro del mismo `form`).
  - El monograma del sidebar no se anima (FR-047: nada en la navegación).
- **Alternatives**: escalonar panel y monograma con delay (supera 400 ms); animar `inset` de
  `::after` (propiedad de layout, prohibida por FR-004).

## R5. Auth loading de marca

Texto confirmado por producto: exactamente "Loading AutoPublisher…", sin copy nuevo.

- **Decision**:
  - Componente nuevo `shell/AuthLoading.tsx`, usado por `AuthGate` y `LoginPage` (hoy los dos
    duplican el mismo `<p role="status">`).
  - Mantiene el `<p className="ap-auth-loading" role="status">` y el texto exacto
    "Loading AutoPublisher…" (los tests existentes lo buscan).
  - Añade el `.ap-mark` (`aria-hidden`) en tamaño mayor, encima del texto.
  - El monograma hace un pulso de opacidad acotado (`ap-pulse`, 3 ciclos ≈ 3,2 s) y queda
    estático.
  - Sin duración mínima ni delay.
- **Rationale**: es un único punto de verdad para un estado que hoy está duplicado. El texto
  sigue siendo el que se anuncia y el monograma es decorativo.
- **Alternatives**: delay antes de mostrar el loading para evitar parpadeo en cargas rápidas.
  Rechazado: dejaría un marco vacío y la spec pide no añadir ni quitar tiempo.

## R6. Inventario real del estado `publishing`

`display_state === "publishing"` es el único estado de trabajo activo de publicación.
`attempt.stage` (preparing / uploading / processing / finalizing / final_chunk) describe la fase
**dentro** de ese mismo estado.

| Superficie | Componente | Fuente | Label | Primitive |
|---|---|---|---|---|
| Posts: lista diaria e History | `posts/PostRow.tsx` | `post.display_state` | "Publishing" | `StatusBadge` |
| Calendar (semana y agenda) | `posts/CalendarView.tsx` | `post.display_state` | "Publishing" | `StatusBadge` |
| Post detail | `posts/StatusActionPanel.tsx` | `post.display_state` | "Publishing" | `StatusBadge` |
| Home, Up next | `home/UpNext.tsx` | `post.display_state` | "Publishing" | `StatusBadge` |
| Home, Attention | `home/AttentionList.tsx` | `item.post.display_state` | "Publishing" (si aparece) | `StatusBadge` |
| Media detail, Usage | `library/MediaUsage.tsx` | `publication.display_state` | "Publishing" | `StatusBadge` |
| Publish Results | `publish/review/ResultsSection.tsx` + `publish/results.ts` | `post.display_state` + `attempt.stage` | "Publishing…" o "Processing" (stage processing/finalizing) | `Badge` directo |

Fuera del indicador, porque no son badges de estado o son otro proceso:

- texto de sección "Publishing now" (`DailyList`);
- motivo "Publishing now" en la elección de destinos (`publish/destinations.ts`);
- `PostWhen` (frase de fase);
- copy de `CheckResultDialog`;
- "Processing in TikTok" de `TikTokInboxDelivery`, que es la entrega a la bandeja de TikTok
  (proceso distinto, FR-015a).

- **Decision**:
  - El "Processing" de Publish Results **sí** comparte el indicador: es el mismo
    `display_state = publishing` en fase de plataforma.
  - Seis superficies usan `StatusBadge` y una usa `Badge`. La mínima reutilización es una
    capacidad opcional en `Badge` (`activity`, `emphasis`), que `StatusBadge` activa para Posts y
    `ResultsSection` activa con la misma regla.
- **Alternatives**: un componente `PostStateBadge` nuevo que sustituya a `StatusBadge` en las
  seis superficies. Rechazado: más cambios para lo mismo.

## R7. Indicador de actividad (Publishing)

- **Decision**:
  - `Badge` acepta `activity`. Pinta un punto `span.ap-badge__activity` (`aria-hidden`) de
    ~6 px, en `--status-active-solid`, **superpuesto a la esquina del icono** (posición
    absoluta). Así no cambia el ancho del badge, ni en las columnas estrechas de la semana del
    Calendar.
  - El punto hace `ap-pulse` (opacidad 1 → 0,35 → 1, 3 ciclos) al montarse y queda sólido.
  - Texto ("Publishing"), icono (reloj) y tono no cambian. El punto es una forma estática
    visible, no un color.
- **Rationale**:
  - Las relecturas periódicas re-renderizan pero no re-montan el badge (las listas tienen
    `key = post.id`), así que el pulso no se reinicia con cada poll.
  - Solo se reproduce al entrar en el estado o al entrar en una vista que lo muestra (FR-005a).
- **Alternatives**: sustituir el reloj por un spinner (más llamativo, y además `infinite`);
  shimmer (prohibido); punto inline (cambia el ancho).

## R8. Detección Publishing → Published

- **Decision**: hook efímero `ui/usePublishedEmphasis.ts`, con el patrón "estado derivado de
  props durante el render" que ya usa `Flash`:

  ```text
  seen := estado con el que montó el componente      (inicialización = montaje)
  cada render con estado actual S:
    si S ≠ seen:
      emphasis := (seen = publishing ∧ S = published)
      seen := S
  onEmphasisEnd → emphasis := false
  ```

  - **Inicializada** = el primer render del badge (su montaje). Lo que se ve al montar nunca es
    una transición.
  - Lo consumen `StatusBadge` (solo la variante `post`) y una fila de `ResultsSection`.
  - Sin `localStorage`, `sessionStorage`, backend ni contexto global: el estado muere con el
    componente.
- **Casos**:
  - `published` inicial → seen = published → sin énfasis.
  - Recarga o remontaje → nuevo montaje → sin énfasis.
  - Poll con `published` → `published` → S = seen → sin re-énfasis.
  - `publishing` → `failed` → `emphasis := false`.
  - `publishing` → `published` → énfasis una vez; `animationend` lo limpia y siguientes polls
    no lo reactivan.
- **Dónde puede observarse de verdad**: solo donde hay relectura mientras el badge sigue
  montado:
  - Publish Results (`usePublishTask` hace poll mientras hay miembros publicando);
  - Post detail y Calendar (`usePostsData` hace poll cada 2 s mientras hay algún Post
    publicando).
  - En la lista diaria de Posts el Post publicado **sale** de la sección (pasa a History), así
    que no hay énfasis.
  - Home y MediaUsage no releen: solo tendrán el indicador. Es correcto según la spec (FR-048).
- **Fast-path de Publish Results (FR-020a)**:
  - Contexto que ya existe: `usePublishTask` mantiene `state.steps: Record<id, PostStep>`. Es
    estado React de la tarea: el reducer lo **reinicia en cada `run_start`** y se pierde al
    recargar. `PostStep.run` es `"now"` o `"schedule"`, y `status` es
    `"running" | "done" | "error"`. Solo contiene las publicaciones que inició la última acción
    final de **esta** vista.
  - Regla: una fila de Results es elegible si `steps[id]?.run === "now"`,
    `steps[id].status === "done"`, `steps[id].emphasized !== true` y el **primer estado con el que
    monta su badge** es `published`.
  - El hook acepta una opción `initiallyEmphasized: boolean`, que solo `ResultsSection` calcula y
    pasa. `StatusBadge` nunca la pasa, así que el fast-path no se mezcla con la regla general.
  - "Una sola vez", incluso si la sección se re-monta: en cuanto `emphasis` pasa a `true` por
    cualquiera de las dos vías dentro de Results, un efecto despacha
    `{ type: "emphasis_shown", id }` y el reducer marca `steps[id].emphasized = true`. Un
    re-montaje deja de ser elegible. Un nuevo `run_start` reinicia `steps` (nueva operación).
  - Recarga o re-entrada: `steps` está vacío, así que no hay fast-path. History, Calendar, Home,
    Post detail y MediaUsage no tienen `steps`.
  - `run === "schedule"` nunca es elegible (no publica en el acto).
- **Matriz de casos**:

  | # | Caso | Resultado |
  |---|---|---|
  | 1 | La vista monta con Published existente | sin énfasis |
  | 2 | Transición observada `publishing` → `published` | énfasis una vez (vía A) |
  | 3 | Results: publicación de la operación actual cuyo primer estado es `published` | énfasis una vez (vía B) |
  | 4 | Un poll vuelve a traer `published` | sin repetición |
  | 5 | Re-montaje o recarga con `published` | sin énfasis (Results: `emphasized` o `steps` vacío) |
  | 6 | `publishing` → `failed`, `needs_action`, `needs_review` u otro | sin énfasis de éxito |
- **Rationale**: una sola solución para todas las pantallas, sin estado compartido. "Perder una
  transición real" solo ocurre si el badge se desmonta entre polls, que es justo el caso en que
  el usuario no la observa.
- **Alternatives**:
  - Fast-path con un set de ids local en `ResultsSection`: se pierde si la sección se re-monta
    y duplica el contexto que `steps` ya tiene.
  - Mapa `id → estado previo` en `usePostsData` / `usePublishTask`: dos implementaciones
    divergentes y estado fuera de la vista.
  - `useRef` + `useEffect`: un render extra y un riesgo con el doble montaje de `StrictMode`;
    el patrón de estado derivado es idempotente.

## R9. Importar: ids y ciclo de vida del highlight

- **Decision**:
  1. `useMediaImport` reúne, durante el bucle, los `content.id` de los resultados con
     `status === "imported"` y `content !== null`. Duplicate, Rejected, los errores por archivo
     y los imports cortados no aportan ids.
  2. Al terminar, llama `onImported(importedIds)` (cambio de firma; `LibraryRoot` ignora el
     argumento).
  3. `MediaView`: `handleChanged()` (que ya relee) y, cuando la relectura resuelve, si hay ids,
     `setJustImported({ ids, key, loadedAt })`.
     - `key` = scope + `selectionKey(query)` leídos de un ref con el valor **actual**, no el
       capturado al empezar el import.
     - `loadedAt` = el `loadedAt` del snapshot que fijó **esa** relectura. Ya existe en el
       estado `loaded` de `MediaView`; `load()` pasa a resolver con él.
  4. El grid marca `data-just-imported` en una card solo si se cumple todo esto:
     - `justImported.key === currentKey`;
     - `justImported.loadedAt === loaded.loadedAt`;
     - el id está en `ids`;
     - la card está en `results` (visible).
  5. `onAnimationEnd` (`ap-highlight`) quita ese id; con el set vacío vuelve a `null`.
  6. Un cambio de búsqueda, filtros u orden (key distinta) invalida el set. **Cualquier
     recarga posterior** (edición desde el detail, Move, Delete u otra) produce un `loadedAt`
     nuevo e invalida el set, aunque la carpeta y la consulta sean las mismas. Un id oculto en
     el snapshot del import nunca se marca, ni aunque luego pase a ser visible.
- **Casos**:
  - Éxito parcial: solo los creados.
  - Todo rechazado o duplicado: `ids = []`, no se fija nada.
  - Raíz de Library: `LibraryRoot` no tiene grid ni highlight; la confirmación es el panel.
  - El usuario cambia de carpeta o de consulta durante el import: la key ya no coincide, o
    `MediaView` se desmonta y el estado muere.
  - Imports solapados: `busyRef` ya los impide por vista.
  - Recarga por otra causa (edición, Move, Delete): cambia `loadedAt`, así que no hay highlight
    tardío. Por ejemplo, un Media importado oculto por `q` que pasa a coincidir tras editar su
    título no se resalta.
- **Rationale**: los ids salen del propio resultado del import, que es la única fuente fiable.
  El highlight se aplica sobre la lista ya releída (FR-027) y nada se persiste.
- **Alternatives**:
  - Comparar la lista antes y después: confunde Media de otras fuentes.
  - Marcar en `MediaCard` vía contexto: más acoplamiento.

## R10. Calendar: highlight tras reschedule

- **Decision**:
  - `CalendarView` añade el estado `landed: { id: number; week: string } | null`. `week` es el
    lunes de la semana visible (`dayKey(monday)`, el mismo valor que el parámetro `?week=`).
  - En el `onDone` existente, después de `await onChanged()` y de fijar `rescheduled.current` y
    el anuncio, hace `setLanded({ id: result.id, week })` **solo si** se cumplen las dos:
    - `result.scheduled_at !== scheduling.post.scheduled_at` (excluye un no-op con la misma
      fecha);
    - la nueva fecha cae dentro de la semana visible (`[monday, monday + 7 días)` en hora local).
  - El `Link.ap-calendar-item` del Post lleva `data-just-rescheduled` solo si
    `landed.id === post.id` **y** `landed.week === week` (la semana actual), en la semana y en
    la agenda.
  - Cualquier cambio de semana (Next/Previous, Back, Forward, URL editada, navegación externa)
    invalida el highlight **por derivación**, sin depender de handlers. Un Post reprogramado
    fuera de la semana nunca fija `landed`, así que no puede aparecer un highlight tardío.
  - `onAnimationEnd` (`ap-highlight`) → `setLanded(null)`; `openDialog` también lo pone a
    `null`.
  - Cancelar (`onClose`) y fallar (`onFailed` / 409) no tocan `landed`.
- **Rationale**: reutiliza el punto de éxito que ya existe y sobrevive a la relectura, porque
  se fija tras ella. El foco (`focusAfterDialog`, ref `rescheduled`) y el anuncio quedan
  idénticos. El highlight usa `box-shadow` y el foco usa `outline`, así que conviven. El drag no
  cambia.
- **Alternatives**: reutilizar el ref `rescheduled` como fuente del highlight. Rechazado: un ref
  no re-renderiza y su ciclo de vida es el del foco.

## R11. Keyframes del énfasis y del highlight

- **Decision**:
  - `ap-badge-emphasis`: `from { scale: 0.9; box-shadow: 0 0 0 0.375rem var(--color-focus-ring-soft); }`
    con `var(--motion-emphasis)` y easing-out. Va en `.ap-badge[data-emphasis]`.
  - `ap-highlight`:
    `from { box-shadow: 0 0 0 3px var(--color-action), 0 0 0 7px var(--color-focus-ring-soft); }`
    con `calc(var(--motion-emphasis) * 4)` y easing-out. Va en
    `.ap-media-card[data-just-imported]` y `.ap-calendar-item[data-just-rescheduled]`.
  - Interpola hacia la sombra natural del elemento (ninguna, o la de hover).
- **Rationale**:
  - `box-shadow` no afecta al layout.
  - El anillo moss frente al canvas es ≥ 3:1 (`--color-action` es el color de foco, ya
    validado).
  - El `scale` del badge no desplaza a los vecinos.
- **Alternatives**: `outline` animado (estilo discreto: el cambio salta a mitad de la
  animación); fondo tintado en la card (choca con `--selected`).

## R12. Favicon

- **Decision**:
  - `frontend/public/favicon.svg` (Vite lo copia a la raíz de `dist`; `backend/app/spa.py` ya
    sirve como archivo cualquier ruta regular dentro de `dist`).
  - Contenido: `viewBox 0 0 32 32`; `rect` completo `rx=8` (25 %, como `--radius-sm` en el
    monograma de 24 px) en `#42634e`; barra `x=13.4 y=8 w=10.6 h=16 rx=1` en `#f6f5f1`, la
    misma proporción `inset: 25% 25% 25% 42%`.
  - En `index.html`: `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />`.
  - Una sola variante.
- **Rationale**: a 16 px la barra mide unos 5 × 8 px y sigue reconocible. Sin PNG ni manifest
  (asunción de la spec).
- **Alternatives**: data URI inline en `index.html` (menos legible para mantener); un set
  PNG/ICO (no hace falta).

## R13. Guard de hover en táctil

- **Decision**: inventario exacto de los lifts (sombra + `translate: 0 -1px`):
  - `library.css`: `.ap-media-card:hover, .ap-media-card:focus-visible`.
  - `home.css`: `.ap-home-tile:hover`.

  Se separan en dos reglas:
  - `:focus-visible` **sigue** aplicando el lift en todos los dispositivos (feedback de
    teclado, FR-037).
  - `:hover` pasa a estar dentro de `@media (hover: hover) and (pointer: fine)`.

  Los hovers que solo cambian color o fondo (filas, entradas, nav, botones) no se tocan.
- **Rationale**: mínimo cambio. En desktop el resultado es idéntico.
- **Alternatives**: guardar todos los `:hover` del producto (fuera de alcance).

## R14. Tests sin timing

- **Decision**:
  - jsdom no ejecuta CSS ni emite `animationend`: los tests comprueban atributos `data-*` y
    clases, y llaman a `fireEvent.animationEnd(el, { animationName })` para la limpieza.
  - Un test de contrato barato lee los `.css` de `src` y exige que `infinite` aparezca solo en
    la regla de `ap-spin` (regresión de FR-005a).
  - El comportamiento real (duraciones, reduced motion, hover guard, `getAnimations()`) se
    verifica por CDP (quickstart).
- **Alternatives**: tests de snapshots de estilos computados (frágiles en jsdom).
