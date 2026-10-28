# Research: Library Search, Filters & Organization (Feature 025)

Decisiones de diseño verificadas contra el código actual de `main` (2026-10-27). Cada sección:
Decision / Rationale / Alternatives considered.

## R1 — Fuente de verdad del estado de consulta

**Decision**: la URL es la única fuente de verdad (opción A). Un hook `useLibraryQuery()` lee
`useSearchParams()`, deriva un `LibraryQuery` tipado con `parseLibraryQuery()` (memo por el
string de `location.search`) y expone `update(patch)`, que escribe con
`serializeLibraryQuery()` y `{ replace: true }`. No hay `useState` para `q`, filtros ni orden.

**Rationale**:
- Es el patrón vigente de Posts (`PostsPage.tsx`: `q` controlado desde `params`, `setParam`
  con `replace`). Ya demostró que un input controlado desde la URL funciona sin lag.
- Back/forward, deep links y recarga son correctos por construcción: el render es una función
  de la URL.
- No hay sincronización bidireccional, así que no hay loops ni "estado local va un paso por
  detrás".
- Tests deterministas: `renderRoute("/p/1/library/all?q=cafe&type=videos")`.

**Alternatives considered**:
- **B — estado local + sync con la URL**: dos fuentes que pueden divergir; exige efectos de
  URL→estado y estado→URL, con riesgo de loops y de pisar back/forward. Solo aporta si escribir
  la URL por tecla fuera costoso, y no lo es (replace, sin red).
- Debounce de la escritura en la URL: innecesario (Posts no lo hace) y rompe la regla "la
  primera tecla vacía la selección" de forma no determinista.

**Detalles**:
- Ningún efecto normaliza la URL al cargar (evita navegaciones automáticas). Los valores
  inválidos se ignoran al parsear; la URL se reescribe limpia en el siguiente cambio del
  usuario.
- `update()` serializa solo las claves de Library. La URL de una vista no tiene otros params
  hoy; el estado de navegación (`flash`) va en `location.state` y no se toca.
- El valor del input es `query.q` en crudo (lo que el usuario escribió, con acentos y
  mayúsculas); la normalización solo se aplica al comparar.

## R2 — Contrato de params

**Decision**:

| Param | Valores | Default (omitido) |
|---|---|---|
| `q` | texto libre; se omite si `q.trim() === ""` | `""` |
| `type` | `images` \| `videos` | all |
| `usage` | `used` \| `unused` | all |
| `imported` | `7d` \| `30d` \| `90d` | any |
| `sort` | `oldest` \| `name-asc` \| `name-desc` | newest |

Valores desconocidos → default. Repeticiones → primera ocurrencia (`URLSearchParams.get`).
El orden de serialización es fijo (`q, type, usage, imported, sort`) para que las URLs y los
tests sean estables.

**Rationale**: nombres cortos y legibles; `q` coincide con Posts; ningún nombre choca con
`posts` (Publish) ni con `from` (R10).

**Alternatives considered**: `filter=videos,unused` en un solo param (más difícil de validar y de
quitar por dimensión); valores por defecto explícitos en la URL (URLs más ruidosas sin ventaja).

## R3 — Normalización y búsqueda

**Decision** (`library-filters.ts`):
- `normalizeText(s) = s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase()`.
- `tokenize(q) = normalizeText(q).split(/\s+/).map(t => t.replace(/^#+/, "")).filter(Boolean)`.
- Texto buscable de un Media: los campos `title ?? ""`, `original_filename`,
  `description ?? ""` y cada hashtag, normalizados y unidos con `"\n"`. Como los tokens nunca
  contienen espacios, un token no puede casar entre dos campos.
- Coincide si `tokens.every(t => text.includes(t))`. Sin tokens → coincide todo.
- El resto de caracteres (`_ - . % ( )`, emojis) se comparan literalmente con `includes`;
  nunca son regex.

**Rationale**: `NFD` + `\p{M}` es el método estándar soportado por los navegadores objetivo
(ES2018 Unicode property escapes; el proyecto ya compila a ES moderno con Vite). `toLowerCase()`
tras quitar marcas cubre `Ñ → n`. Cumple FR-001–FR-007 sin dependencias.

**Alternatives considered**: `localeCompare` con `sensitivity: "base"` por subcadena (no existe
para `includes`); `NFKD` (pliega también compatibilidades como `ﬁ → fi`, que nadie escribe;
innecesario); librerías de búsqueda aproximada (fuera de alcance).

**Edge**: `##summer` → `summer`; `#` solo → token vacío descartado; la consulta `"   "` equivale
a no buscar.

## R4 — Used / Unused

**Decision**: `usageOf(content) = content.usage.publication_count > content.usage.cancelled_count
? "used" : "unused"`, en `usage-indicator.ts` junto a `isNotUsedYet` (que pasa a ser
`usageOf(c) === "unused"`; misma fórmula que hoy).

**Rationale**: `publication_count` cuenta todas las Publications con `content_id` del Media y
`cancelled_count` las canceladas (`usage_by_content`, `backend/app/asset_library.py`). Su
diferencia es el número de Posts no cancelados en cualquier estado y cuenta. Es una partición
exhaustiva por definición y no toca el backend. `usage.used` (published + awaiting) NO se usa.
Los Posts borrados ya no están en la tabla. El default `ContentUsageRead()` (sin Posts) da
`0 > 0 = false` → unused.

**Alternatives considered**: `draft_count + upcoming_count + attention_count + published_count
+ awaiting_count > 0` (más campos, mismo resultado y más frágil si aparece un estado nuevo).

## R5 — Imported

**Decision**: `importedWithin(content, days, now) = Date.parse(content.created_at) >= now -
days * 86_400_000`. Límite **inclusivo**: un Media importado exactamente hace N × 24 h está
dentro. `now` (ms) se pasa al pipeline; el componente lo toma con `Date.now()` dentro del
`useMemo` de resultados. Una fecha futura (reloj desfasado) siempre está dentro.

**Rationale**: ventana continua confirmada en la spec; independiente de la zona horaria. Con
`now` inyectado, los tests usan instantes fijos sin `sleep` ni fake timers.

**Alternatives considered**: días naturales en la zona local (dependen de la zona y del DST;
descartado por la spec); refresco periódico de `now` (nadie deja la Library abierta 7 días
esperando que un Media salga del rango; recalcula en cada cambio de datos o consulta).

## R6 — Orden

**Decision**:
- `newest`: `created_at` desc y `id` desc, igual que `list_contents` (`order_by(created_at.desc(),
  id.desc())`).
- `oldest`: exactamente el inverso (`created_at` asc y `id` asc).
- `name-asc` / `name-desc`: `collator.compare(nameA, nameB)` con
  `new Intl.Collator(undefined, { sensitivity: "base", numeric: true })` sobre
  `title ?? original_filename`. Empate → comparador `newest` (en ambos sentidos, FR-028).
- Las fechas se comparan con `Date.parse` (ISO con zona del backend). El collator se crea una
  vez a nivel de módulo.
- El orden siempre se aplica sobre una copia (`[...list].sort`); `Array.prototype.sort` es
  estable, aunque el desempate explícito ya hace el orden total.

**Rationale**: el locale del navegador (`undefined`) es "el idioma del usuario"; `base` ignora
mayúsculas y acentos; `numeric` da `a2 < a10`. `id` es único, así que el orden es total y
determinista.

**Alternatives considered**: `localeCompare` por par (crea un collator por llamada; más lento con
miles de Media); locale fijo `"en"` (peor para nombres en español).

## R7 — Pipeline

**Decision**: `libraryResults(contents, query, now): Content[]`:

1. Universo: la lista de la vista tal como la devuelve el backend (All media, Unsorted o los
   Media directos de la carpeta). No se reinterpreta.
2. Un único `filter` con un predicado: tipo → uso → imported → búsqueda (del más barato al más
   caro, con cortocircuito).
3. `sort` sobre el resultado del filtro (ya es una lista nueva).

El texto buscable de cada Media se precalcula en un `Map<id, string>` memorizado por `contents`
(`searchIndex(contents)`), así que escribir no vuelve a normalizar 4 campos × N por tecla.

Helpers adicionales: `hasActiveFilters(query)`, `activeFilters(query)` (lista ordenada para los
chips), `withoutFilter(query, key)`, `clearFilters(query)` (conserva `q` y `sort`),
`emptyResultsKind(query, scope)`.

**Rationale**: funciones puras sin React, testeables con tablas (FR-079); un solo punto de
verdad para qué es "visible".

**Alternatives considered**: filtrar por pasos con varias listas intermedias (más asignación sin
ganancia); `useMemo` por dimensión (complejidad sin beneficio medible).

## R8 — Seguridad de la selección (un solo punto de control)

**Decision**: la selección se guarda junto con la clave de la consulta que la produjo:
`checked: { key: string; ids: ReadonlySet<number> } | null`, donde
`key = selectionKey(query)` = serialización de `q`, `type`, `usage` e `imported` (sin `sort`).
La selección efectiva se **deriva** en el render:

```text
effective = checked === null ? null              // fuera de Select
          : checked.key !== currentKey ? ∅       // la consulta cambió → vacía
          : checked.ids ∩ visibleIds             // nunca un id no visible
```

`toggle(id)` parte de `effective` y guarda `currentKey`. La poda actual de `load()` se mantiene
(es compatible).

**Move y Delete congelan la selección al pulsarse** (corrección del analyze, 2026-10-28):
- Pulsar Move guarda `movingIds = [...effective]`. El título del `FolderPicker` y
  `moveContents` usan esa copia, nunca la selección recalculada al confirmar.
- Delete ya lo hace con la copia `bulkDelete`.
- Así, un back/forward o un cambio de consulta con el picker o el diálogo abiertos no altera
  los Media afectados: son exactamente los que el usuario veía y tenía marcados al pulsar
  (FR-055, "en el momento de pulsarlos").

**Rationale**:
- Ningún `useEffect`: chips, `Clear all`, `Clear search`, el panel Filters, back/forward y la
  escritura caen todos en el mismo caso "la clave cambió", sea cual sea el origen del cambio.
- Escribir: la primera tecla cambia la clave → ∅; las siguientes no tienen más efecto
  (FR-051 sin debounce).
- Cambiar solo `sort` no cambia la clave → la selección se conserva (FR-053).
- La intersección con los visibles también cubre el caso "un Media seleccionado deja de
  coincidir tras recargar" (p. ej. editado en el detail mientras estaba marcado), así que
  FR-055 se cumple sin depender del orden de los efectos.
- Select sigue activo con 0 marcados (`checked !== null`), FR-052.
- `Search all media` cambia de vista: la instancia nueva empieza sin selección, como hoy
  (FR-054).

**Alternatives considered**: `useEffect([q, type, usage, imported]) → setChecked(new Set())`
(un render con la selección vieja visible, efectos en competencia con `load()`, y depende de
que todas las rutas de cambio pasen por el mismo estado); limpiar en cada handler (se olvida
back/forward).

## R9 — Detail, deep links y navegaciones con params

**Decision**: `MediaView` obtiene `search = serializeLibraryQuery(query)` (con `?` o vacío) y lo
añade a **todas** las rutas de vista que construye. Reparto por checkpoints: `mediaPath` y
`parentPath` (N1, N2, N3, N11) entran en B junto con la URL como fuente de verdad, para que abrir
y cerrar el detail nunca pierda la consulta; el resto (N4–N10 y Publish), en C:

- `mediaPath(id) = viewPath + "/" + id + search` (cards e `ImportPanel`).
- `parentPath = viewPath + search` (cierre del detail en panel, drawer y página).
- `<Navigate to={base + "/all/" + id + search}>` para un Media de otra vista.
- `handleMoved` (sigue al Media), `moveChecked` (cierra el detail), `mediaDeleted`,
  `selectionDeleted` y `selectionMissing` (`navigate({ pathname, search }, …)`) y
  `folderDeleted` hacia la carpeta padre. Ir a la raíz de Library descarta los params
  (FR-042).

Un helper `withSearch(path)` evita repetir la concatenación.

**Deep link a un Media excluido por los filtros (FR-080)**: ya funciona. `selected` se busca en
`loaded.contents` (el universo de la vista), no en los resultados. Solo hay que garantizar que
`MediaGrid` reciba los resultados filtrados y que el detail siga montado. Ninguna card queda
marcada porque no está en el grid.

**Media que deja de coincidir (FR-081)**: ya funciona. `MediaDetail.onChanged → handleChanged →
load()` recarga la lista; `selected` sigue existiendo en `contents`, así que el detail no se
cierra. La card desaparece del grid en el mismo render.

**Rationale**: cambios mínimos y localizados en el único componente que construye esas rutas.

**Alternatives considered**: que cada enlace lea `location.search` en crudo (arrastraría params
inválidos o ajenos); un contexto de "Library location" (abstracción para un solo componente).

## R10 — Contexto de vuelta desde Publish

Flujo actual verificado:
- Entradas a `library/:mediaId/publish`: el botón primario de `MediaDetail`
  (`${base}/${id}/publish`), `PostDetail` (Posts, `navigate(.../library/{content_id}/publish)`)
  y la URL directa.
- `PublishTask` "Back to media" → `/p/:id/library/:mediaId` (ruta antigua, detail sobre All
  media): hoy pierde la carpeta y todo el estado.
- `usePublishTask.replaceIds` reescribe la URL como `{ pathname, search: "?posts=…" }` con
  `replace` y **sin state**: borra cualquier otro param y el `location.state`.

**Decision**: opción A, una **ubicación de retorno codificada y validada** en un param propio de
Publish: `?from=<vista>[?<query de Library>]`, relativa a `/p/:projectId/library/`, p. ej.
`from=folders%2F12%3Fq%3Dcafe%26type%3Dvideos`.

- `MediaDetail` recibe de `MediaView` `libraryReturn = libraryReturnParam(scope, query)` y lo
  añade a su enlace de Publish.
- `parseLibraryReturn(from)` acepta solo `all`, `unsorted` o `folders/<id positivo>`, seguidos
  opcionalmente de `?` y una query que se **re-parsea** con `parseLibraryQuery` y se
  re-serializa. Cualquier otra cosa → `null`. El destino final se **reconstruye** con
  `libraryViewPath(project.id, scope) + "/" + mediaId + search`: nunca se navega a una cadena
  recibida, ni a otro proyecto ni a un origen externo.
- `PublishTask` usa ese destino para "Back to media" si `from` es válido; si no (entrada desde
  Posts, URL directa, valor manipulado), conserva el destino actual.
- `replaceIds` pasa a actualizar solo `posts` sobre los params actuales
  (`next = new URLSearchParams(location.search); next.set("posts", …)`), de modo que `from`
  sobrevive a Continue, Review y Results.

**Rationale**:
- Sobrevive a recargar Publish, a abrirlo en otra pestaña y a copiar su URL (ventaja sobre el
  state).
- No hay open redirect: el valor se valida contra la gramática de vistas y se reconstruye.
- No rompe la entrada directa (sin `from`, sin cambios).
- Cambio pequeño: un helper puro, un prop, un enlace y una línea en `replaceIds`.

**Alternatives considered**:
- **B — `location.state`**: `replaceIds` lo borra hoy (habría que propagarlo igual), no
  sobrevive a abrir en otra pestaña ni a copiar la URL, y es invisible en los tests de URL.
- **C — repetir los params de Library en Publish** (`?view=…&q=…&type=…`): mezcla dos espacios
  de nombres en la URL de Publish y obliga a Publish a conocer cada clave de Library.
- Historial de navegación global: fuera de alcance.

**Edge**: si la carpeta de `from` se borró entretanto, la vista responde Not found con "Back to
Library" (comportamiento actual de una carpeta inexistente). Si el Media se movió, la vista
redirige al detail sobre All media conservando los params (R9).

## R11 — Foco al cerrar el detail si su card ya no está (FR-082)

Estado actual:
- Panel (≥1280) y página (<768): un efecto de `MediaView` enfoca
  `[data-detail-id=<cerrado>]` si existe; si no, el foco se pierde.
- Drawer (768–1279): Radix `onCloseAutoFocus` devuelve el foco a `opener` (la card) si está
  conectada; si no, el foco cae al `body`.

**Decision**: un solo helper en `MediaView`, `focusTargetAfterDetail(id) = card
[data-detail-id=id] ?? <main> del shell` (`<main id="main-content" tabIndex={-1}>` en `AppShell`, buscado con `document.querySelector("main")` como `cardLeaving`), usado por:

- el efecto actual de cierre (panel y página), que pasa a enfocar siempre ese destino;
- `DetailSurface`, que acepta un prop opcional `returnFocus` y lo pasa al `Drawer` (el patrón
  `Modal.returnFocus` ya existe en `ui/Dialog.tsx` y lo usa Calendar). `MediaView` pasa
  `() => focusTargetAfterDetail(selectedId)`.

El destino de fallback es el **contenido principal** (`main`), confirmado el 2026-10-28. Ya tiene `tabIndex={-1}` en `AppShell`: es enfocable por programa sin entrar en el orden de Tab.
- Es el fallback que `MediaView` ya usa cuando una card sale de la vista
  (`cardLeaving` → vecina, si no `main`).
- Existe siempre, sea cual sea el estado del grid (también vacío) y del toolbar.
- En móvil no abre el teclado (a diferencia de la búsqueda).
- No requiere añadir `tabIndex` a elementos nuevos.

**Alternatives considered**:
- El `h1` de la vista: requiere `tabIndex={-1}` nuevo y diverge del fallback existente.
- El grid (`ul`): no es enfocable y puede no existir con 0 resultados.
- La búsqueda: abre el teclado en móvil y anuncia un campo de formulario en lugar del contexto.
- Una card vecina: no hay "vecina" significativa cuando el Media nunca estuvo en el grid (deep
  link).

## R12 — Toolbar desktop

Medidas: a 1024 px el shell tiene sidebar de 16rem, así que el contenido mide ~720 px. A ≥1280
con el detail en panel lateral, la lista mide ~480–560 px.

**Decision**:
- Fila 1 (desde `md`): búsqueda (`flex: 1 1 14rem`) + cuatro `select` nativos compactos dentro de
  `Field` (Type, Usage, Imported, Sort), en un `flex-wrap`. Etiquetas cortas visibles, igual que
  el filtro "Destination" de Posts.
- Fila 2: los filtros activos, solo cuando existan.

Los pills actuales (`ChoiceGroup` horizontal) se retiran de la toolbar de escritorio: 3 + 3 + 4
pills no caben en dos filas a 1024. Todas las dimensiones como `select` sí caben, en ~720 px
(224 + 4 × ~120 + gaps).

**Rationale**: reutiliza `Field` + `select` (`.ap-input`) del design system; un `select` es el
control más compacto y accesible por teclado; mismo patrón que Posts.

**Alternatives considered**:
- Mantener los pills de Type y usar `select` en el resto: más alto y más ancho; no cabe a 1024
  junto a la búsqueda.
- Menú `.ap-menu` con todos los filtros: obliga a abrir un panel en escritorio (FR-061 lo
  prohíbe).

**FR-062 (confirmado 2026-10-28)**: el límite de dos filas se evalúa con el ancho normal de
contenido de la Library. Con el detail como panel lateral, la toolbar puede envolver de forma
natural a más filas, sin comprimir los controles hasta hacerlos ilegibles y sin un breakpoint
nuevo; nunca hay overflow horizontal. Los pills actuales de Media type se eliminan (confirmado).

## R13 — Móvil y panel Filters

**Decision**:
- Por debajo de `md` (`isMedium === false`, el mismo `useMediaQuery(MEDIA_MD_UP)` que
  `MediaView` ya usa):
  - fila 1: búsqueda a ancho completo;
  - fila 2: botón `Filters` (con el recuento "Filters · 2" en texto visible y nombre accesible
    "Filters, 2 active") y el `select` de Sort;
  - fila 3: chips en `overflow-x: auto` con `flex-wrap: nowrap`, solo con filtros activos.
- `Filters` abre el `Sheet` existente (`ui/Dialog.tsx`, variante `sheet`: pantalla completa en
  teléfonos). Dentro, tres `ChoiceGroup` verticales (radios nativos con legend: Media type,
  Usage, Imported). Los cambios se aplican al momento (escriben la URL). Footer con `Clear
  filters` (deshabilitado sin filtros) y `Done` (cierra). Radix gestiona el foco y lo devuelve
  a `Filters` (FR-073).

**Compartir reglas**: una tabla `FILTER_DIMENSIONS` (clave, etiqueta, opciones y etiqueta de
chip) en `library-filters.ts` alimenta los `select` de escritorio, los `ChoiceGroup` del panel y
los chips. Las transiciones de estado son siempre `update(patch)`, `withoutFilter` y
`clearFilters`. Desktop y móvil solo cambian la presentación.

**Rationale**: no hay un componente "bottom sheet" parcial en el design system; el `Sheet`
existente es la superficie móvil de referencia (Add account), y la spec excluye el panel abierto
del límite de altura.

**Alternatives considered**:
- `select` también en móvil, sin panel: 4 `select` + búsqueda superan el tercio de la altura y la
  spec pide `Filters` + Sheet.
- Montar ambos layouts y ocultar uno con CSS: duplica nombres accesibles en el árbol y en los
  tests.

## R14 — Filtros activos (chips)

**Decision**: un componente local `ActiveFilters.tsx` (solo Library) que pinta, por cada
dimensión no por defecto, un `Button` pequeño con texto "Videos" y un icono de cerrar, y nombre
accesible `Remove filter: Videos`, más `Clear all` cuando hay al menos uno. Está dentro de un
`role="group"` con `aria-label="Active filters"`.

Al quitar un chip, el foco pasa al siguiente chip (o al anterior si era el último). Si no queda
ninguno, va al control visible de filtros: en escritorio, el `select` de la dimensión quitada;
en móvil, el botón `Filters`. Tras `Clear all`, el mismo destino (el `select` de Type en
escritorio, `Filters` en móvil).

**Rationale**: FR-071/FR-072; reutiliza `Button` e `Icon`; sin componente genérico de chips
porque solo lo usa Library. El destino final es un control estable, visible y relacionado con
la acción; nunca el inicio del documento.

**Alternatives considered**:
- `Badge` (no es interactivo).
- Un `ChipGroup` genérico en `ui/` (abstracción prematura, Constitution I).
- La búsqueda como destino: puede abrir el teclado en móvil y no se relaciona con la acción.

## R15 — Anuncio de resultados (FR-074)

**Decision**: una región `role="status"` (`aria-live="polite"` implícito) visualmente oculta
dentro de la toolbar, cuyo texto es:

- `""` (vacío) sin búsqueda ni filtros;
- `"N media"` o `"No media"` con búsqueda o filtros activos.

Solo cambia cuando cambia el número; el orden no lo cambia.

**Rationale**: los lectores no re-anuncian un texto idéntico, lo que deduplica las teclas que no
cambian el número. No hay contador visible (FR-025 retirado). Sin temporizadores.

**Alternatives considered**:
- Debounce del anuncio (más código; escribir ya es progresivo y polite no interrumpe).
- Anunciar siempre, también sin filtros (ruido al cargar la vista).

## R16 — Estados vacíos

**Decision**: `emptyResultsKind(query, scope)` devuelve uno de `search`, `filters` o `both` (solo
se usa cuando la vista tiene Media y los resultados son 0). Un componente `EmptyResults` lo
traduce a `EmptyState` (`headingLevel={2}`, icono `search`):

| Caso | Título | Acción principal | Otras acciones |
|---|---|---|---|
| search | No media match "…" | `Clear search` | `Search all media` (link secundario, solo Folder/Unsorted) |
| filters | No media match these filters | `Clear filters` | — |
| both | No media match the search and filters | `Clear search` | `Clear filters` (botón secundario), `Search all media` (link, solo Folder/Unsorted) |

- `Search all media` es navegación, así que usa el `secondary` link de `EmptyState` con
  `to = libraryViewPath(all) + search`.
- En el caso `both`, `action` es un fragmento con el botón primario y el secundario: sigue
  habiendo una sola acción principal.
- La Library vacía (dropzone) y la vista vacía (mensaje actual) no cambian. Las ramas son
  excluyentes: `empty` (vista sin Media) → mensaje actual; si no, resultados 0 →
  `EmptyResults`; si no, el grid.

**Alternatives considered**: ampliar `EmptyState` con un array de acciones (cambia un
componente compartido para un solo uso).

## R17 — Import con filtros activos

**Decision**: sin cambios de comportamiento. Tras importar, `load()` recarga y el pipeline decide.
Un Media recién importado siempre cumple `imported` (fecha actual) y `usage = unused`; puede
quedar fuera por `type`, `usage = used` o `q`. El `ImportPanel` existente ya enlaza cada Media
importado a su detail (`mediaPath`, que ahora lleva los params), y el detail se abre aunque el
grid lo excluya (R9). No se limpian params ni se cambia el orden.

## R18 — Rendimiento

**Decision**:
- `useMemo` para `searchIndex(contents)` (por `contents`) y para
  `libraryResults(contents, query, now)` (por `contents` y el string de la query).
- `visibleIds` (Set) se deriva de los resultados en el mismo memo.
- El `Intl.Collator` es de módulo.

Coste esperado con 1.000 Media: <5 ms por tecla (filtro O(N·tokens) con `includes` sobre cadenas
ya normalizadas, y sort O(N log N)).

Fuera de alcance (registrado): virtualización, miniaturas y vídeos diferidos; el coste de render
de 10k cards es previo a esta feature.

## R19 — Tests

Se prueba nuestro contrato, no `Intl` ni `URLSearchParams`.
- Unitarios puros:
  - `library-helpers.test.ts`, ampliado: búsqueda, uso, imported, orden, pipeline, chips y
    `emptyResultsKind`;
  - nuevo `library-query.test.ts`: parse, serialize, inválidos, defaults, `selectionKey`,
    `parseLibraryReturn` y `libraryReturnParam`.
- Integración, con `renderRoute` y `test-fake-api` existentes:
  - nuevo `pages/library/search-filters.test.tsx`: controles, URL, chips, estados vacíos,
    `Search all media`, detail y foco, selección y móvil;
  - el retorno de Publish en `pages/publish/publish-page.test.tsx`.
  - Se actualizan las aserciones de `library.test.tsx` y `library-helpers.test.ts` que usan el
    filtro "Not used yet" (SC-010).
- Backend: sin cambios, sin tareas de tests de backend.
