# UI Contract: Library Search, Filters & Organization (Feature 025)

Contrato observable de la UI y la URL. El razonamiento está en [research.md](../research.md).
La API del backend NO cambia (no hay contrato de API).

## 1. URL

```text
/p/:projectId/library/{all | unsorted | folders/:folderId}[/:mediaId][?q=&type=&usage=&imported=&sort=]
/p/:projectId/library/:mediaId                  (enlace antiguo: detail sobre All media; acepta los mismos params)
/p/:projectId/library/:mediaId/publish[?posts=…][&from=…]
```

| Param | Valores válidos | Default (se omite) | Inválido → |
|---|---|---|---|
| `q` | texto; se omite si está vacío o solo tiene espacios | — | — |
| `type` | `images`, `videos` | All | All |
| `usage` | `used`, `unused` | All | All |
| `imported` | `7d`, `30d`, `90d` | Any time | Any time |
| `sort` | `oldest`, `name-asc`, `name-desc` | Newest | Newest |

- Orden de serialización fijo: `q`, `type`, `usage`, `imported`, `sort`.
- Toda escritura de búsqueda, filtros u orden usa `replace`: nunca crea entradas de historial.
- Cargar una URL no la reescribe; los params inválidos se limpian en el siguiente cambio del
  usuario.
- La raíz `/p/:projectId/library` ignora estos params.
- `from` (solo Publish): `encodeURIComponent("<all|unsorted|folders/<id>>[?<query de Library>]")`.
  Se valida contra esa gramática y se reconstruye; si no es válido, se ignora.

## 2. Semántica de resultados

```text
resultados = sort( universo_de_la_vista.filter(type ∧ usage ∧ imported ∧ search) )
```

- **Universo**: All media = todo el proyecto; Unsorted = sin carpeta; carpeta = sus Media
  directos.
- **search**: tokens = `q` normalizado (NFD sin marcas, minúsculas), separado por espacios, sin
  `#` iniciales y sin tokens vacíos. Cada token debe ser subcadena literal de title, filename,
  description o algún hashtag (normalizados).
- **type**: `media_type` es `image` o `video`.
- **usage**: `used` ⇔ `publication_count > cancelled_count`; `unused` en otro caso.
- **imported**: `created_at ≥ now − N × 24 h`, límite inclusivo.
- **sort**:
  - Newest: `created_at` desc, `id` desc.
  - Oldest: el inverso exacto.
  - Name A–Z y Z–A: collator del navegador (base, numeric) sobre `title ?? original_filename`;
    empate según Newest.

## 3. Toolbar

### Desktop y tablet (≥ 768 px)

```text
[h1 Title] [N media]                         [Import media] [Select] [⋯]
[Search media______________] [Type ▾] [Usage ▾] [Imported ▾] [Sort ▾]
[Videos ✕] [Unused ✕] [Clear all]                  ← solo con filtros activos
```

- Búsqueda: `input type="search"`, nombre accesible "Search media", placeholder "Search title,
  file name, caption or #hashtag". `Clear search` es una acción explícita mientras haya texto.
- Type, Usage, Imported y Sort: `select` dentro de `Field`, con etiquetas visibles "Type",
  "Usage", "Imported" y "Sort".

| Control | Opciones |
|---|---|
| Type | All · Images · Videos |
| Usage | All · Used · Unused |
| Imported | Any time · Last 7 days · Last 30 days · Last 90 days |
| Sort | Newest · Oldest · Name A–Z · Name Z–A |

- El recuento "N media" de la vista sigue igual que hoy. No hay contador de resultados visible.

### Móvil (< 768 px)

```text
[h1 Title] [N media]                  [Import media] [Select] [⋯]
[Search media_____________________________________]
[Filters · 2]                              [Sort ▾]
[Videos ✕] [Unused ✕] [Clear all] →   (una fila desplazable horizontalmente)
```

- El botón `Filters` muestra "Filters" o "Filters · N"; su nombre accesible es "Filters" o
  "Filters, N active".
- El panel Filters es un `Sheet` titulado "Filters", con tres grupos de radios (legend "Type",
  "Usage", "Imported"). Los cambios se aplican al momento. Footer: `Clear filters`
  (deshabilitado sin filtros activos) y `Done`. Escape, `Done` y Close lo cierran y devuelven el
  foco a `Filters`.
- Con el panel cerrado, la búsqueda, la fila `Filters`/Sort y la fila de chips ocupan como
  máximo ~1/3 de 667 px. Ningún ancho entre 375 y 1280 px produce scroll horizontal de página.

## 4. Filtros activos

- Un chip por dimensión distinta del default, en el orden Type, Usage, Imported. Texto: la
  etiqueta del valor ("Videos", "Unused", "Last 30 days"). Nombre accesible: "Remove filter:
  <etiqueta>".
- Quitar un chip devuelve esa dimensión a su default. El foco pasa al siguiente chip, al
  anterior si era el último, o, si no queda ninguno, al `select` de la dimensión (escritorio) o
  a `Filters` (móvil).
- `Clear all` aparece con ≥ 1 chip: resetea Type, Usage e Imported y conserva `q` y `sort`. El
  foco va al `select` de Type (escritorio) o a `Filters` (móvil).
- El orden y la carpeta nunca aparecen como chip.
- El contenedor es `role="group"` con nombre "Active filters".

## 5. Selección

- La selección efectiva es el conjunto marcado ∩ los resultados visibles. Está vacía si `q`,
  `type`, `usage` o `imported` cambiaron desde que se marcó, sea cual sea el origen del cambio
  (input, chip, `Clear all`, `Clear search`, Sheet, back/forward).
- Cambiar solo `sort` la conserva. Select sigue activo con 0 marcados (Move y Delete
  deshabilitados, "0 selected" anunciado por la barra existente).
- Move y Delete en bloque reciben exactamente la selección efectiva.

## 6. Detail

- Los enlaces de las cards, `ImportPanel`, el cierre del detail y las navegaciones de Move y
  Delete añaden el search de Library a la ruta de vista de destino.
- Ir a la raíz de Library no lo hace.
- Un `mediaId` del universo de la vista abre el detail aunque no esté en los resultados. Uno de
  otra vista redirige a `library/all/:mediaId` conservando el search. Uno inexistente da Not
  found (como hoy).
- Al cerrar el detail, el foco va a la card de origen si está en los resultados; si no, a
  el `<main>` del shell (`id="main-content"`, `tabIndex={-1}`), en panel, drawer y página. Nunca al `body`.
- Editar el Media o actuar sobre él desde el detail nunca cierra el detail por dejar de coincidir.

## 7. Publish

- El botón principal del detail enlaza a `…/library/:mediaId/publish?from=<retorno>` con la
  vista y la consulta actuales.
- "Back to media" navega a `libraryViewPath(from.view)/:mediaId?<query>` si `from` es válido. Si
  no (entrada desde Posts, URL directa, valor manipulado), a `/p/:projectId/library/:mediaId`,
  como hoy.
- Las escrituras de `?posts=` del task conservan `from`.

## 8. Estados vacíos (excluyentes)

| Condición | Se muestra |
|---|---|
| Library sin Media (raíz) | Dropzone actual |
| Vista sin Media | Mensaje actual ("No media in this folder yet." / "No media without a folder." / "No media yet."); sin búsqueda, filtros ni orden |
| Media en la vista, 0 resultados, solo búsqueda | `EmptyState` "No media match "<q>"": `Clear search` (+ link `Search all media` en Folder/Unsorted) |
| Ídem, solo filtros | `EmptyState` "No media match these filters": `Clear filters` |
| Ídem, búsqueda + filtros | `EmptyState` "No media match the search and filters": `Clear search` (principal), `Clear filters` (secundaria) (+ link `Search all media` en Folder/Unsorted) |

- `Search all media` lleva a `library/all` con `q`, filtros y orden.
- Las entradas de subcarpetas siguen visibles encima, sin filtrar.

## 9. Anuncio de resultados

- Una región `role="status"` visualmente oculta. Su texto es vacío sin búsqueda ni filtros, y
  "N media" o "No media" con ellos.
- Solo cambia cuando cambia el número, así que cambiar el orden no anuncia nada.
