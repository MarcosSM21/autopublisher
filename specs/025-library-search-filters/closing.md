# Cierre: Feature 025 — Library Search, Filters & Organization

**Fecha**: 2026-10-28 · **Rama**: `025-library-search-filters` · **Tasks**: T001–T056 completadas

## Commits

| Checkpoint | Commit | Contenido |
|---|---|---|
| A | `2aa8690` | Modelo puro: búsqueda, Used/Unused, Imported, sort, pipeline, URL, `selectionKey`, `from` |
| B | `e880c48` | Controles desktop, URL como única fuente, chips, selección derivada, Move congelado |
| C | `8dba960` | N4–N14, foco de fallback a `main`, `DetailSurface.returnFocus`, retorno desde Publish |
| D | `20d0285` | Toolbar móvil, Sheet Filters, `EmptyResults`, Search all media |
| E | este commit | Pulido CSS, documentación, verificación final |

## Verificación

- Tests dirigidos por checkpoint (nunca la suite completa en local): A 139, B 84 (+37 de
  regresión), C 118 (+67), D 89, E 68 (`search-filters` tras el último cambio de TSX).
- Checks estáticos una sola vez en E: `lint`, `format:check`, `typecheck` (`tsc -b`), build de
  producción con `vite build` hacia el scratch (el servicio real sirve `frontend/dist` de este
  checkout) y `git diff --check`.
- Revisión responsive automatizada con Chrome headless (CDP) sobre una copia scratch, a 375, 390,
  768, 1024, 1280 y 1440 px, con título de 100+ caracteres sin espacios y carpeta de nombre
  largo:
  - sin overflow horizontal de página en ningún escenario;
  - controles en ≤ 2 filas a ancho normal (1 fila desde 1280);
  - chrome persistente en móvil de 125–185 px (≤ 1/3 de 667);
  - chips con scroll propio, sin desbordar la página.
- Teclado (CDP): orden búsqueda → Clear search → Type → Usage → Imported → Sort → chips →
  Clear all → grid, con indicador de foco visible en todos.

## Correcciones durante la feature

- C (MEDIUM, preexistente): un Move en bloque que incluía el Media abierto acababa en
  `/all/:id`. La recarga se aplicaba antes que la navegación (transición). Se cubre con la
  misma guarda que Delete (`closedId`).
- E (overflow real, preexistente): en móvil, el título largo sin espacios del detail en página
  completa ensanchaba la página. `.ap-detail-page__title` recibe `overflow-wrap: anywhere`,
  como el panel y el drawer.
- E (pulido): `Clear search` ya no parte su etiqueta; separación entre grupos del Sheet.

## Pendiente

- Revisión visual humana en un navegador real y con lector de pantalla. Las comprobaciones de
  este cierre son automáticas: métricas, capturas y teclado por CDP.
- En el Sheet, `Done` queda al final del scroll del Sheet (patrón actual de `Sheet`, sin footer
  fijo). No se cambió el componente compartido.
