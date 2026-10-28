# Implementation Plan: Library Search, Filters & Organization

**Branch**: `025-library-search-filters` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-library-search-filters/spec.md`

## Summary

Convertir la búsqueda y el filtro excluyente actuales de Library en una consulta tipada que vive
**solo en la URL** (`q`, `type`, `usage`, `imported`, `sort`). Sobre la lista que la vista ya
carga se aplica un pipeline de helpers puros: búsqueda sin acentos y por tokens con AND, filtros
combinables, Used/Unused desde los recuentos de uso existentes y cuatro órdenes estables.

Sobre esa base:
- todas las navegaciones de la vista (detail, Move, Delete, redirecciones) y el viaje a Publish
  (param `from` validado) preservan el contexto;
- la selección se deriva de la consulta, así que nunca contiene Media ocultos;
- la toolbar muestra los controles inline en escritorio y `Filters` + Sheet en móvil, con chips
  de filtros activos, estados vacíos diferenciados y anuncio accesible del número de resultados.

Sin cambios de backend, API, modelos ni migraciones. Detalle en [research.md](research.md) y
contrato en [contracts/ui.md](contracts/ui.md).

## Technical Context

**Language/Version**: TypeScript 6 + React 19, React Router 8 (frontend). Backend Python + FastAPI, sin
cambios.

**Primary Dependencies**: React Router (`useSearchParams`, `useNavigate`), `@radix-ui/react-dialog`
(vía `ui/Dialog.tsx`: `Sheet`, `Drawer`) y `Intl.Collator`. Ninguna dependencia nueva.

**Storage**: N/A (la URL es el estado; no hay `localStorage`).

**Testing**: Vitest + Testing Library, con `test-utils.tsx` (`renderRoute`, `setViewport`) y
`test-fake-api.ts`. Sin tests de backend.

**Target Platform**: navegadores modernos (escritorio y móvil) contra la instalación local.

**Project Type**: aplicación web (frontend + backend); la feature solo toca el frontend.

**Performance Goals**: resultados en menos de 100 ms por tecla con 1.000 Media (SC-003); se
esperan menos de 5 ms de cálculo.

**Constraints**:
- `GET /api/projects/{id}/contents` sin cambios.
- Sin paginación, virtualización ni miniaturas.
- Mismos breakpoints (`md` 768, `lg` 1024, `xl` 1280).
- Sin overflow horizontal entre 375 y 1280 px.

**Scale/Scope**:
- Un solo usuario; hasta miles de Media por vista.
- Unos 10 archivos de frontend tocados, 3 nuevos de lógica y UI, y 2 nuevos de tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación |
|---|---|
| I. Simplicidad y alcance | ✅ Sin backend, sin dependencias, sin componentes genéricos nuevos en `ui/` salvo un prop opcional `returnFocus` en `DetailSurface`, que reutiliza el de `Modal`. URL como única fuente de verdad (menos estado). Scope fijado por la spec; las mejoras opcionales (contador visible) no se planifican. |
| II. Spec-Driven | ✅ Cada decisión se traza a FR-xxx. La interpretación de FR-062 (R12) está confirmada, sin ampliar el alcance. |
| III. Arquitectura modular | ✅ Solo frontend. Lógica pura en `library-filters.ts` y `library-query.ts`, separada de los componentes. Sin lógica de plataformas. |
| IV. Seguridad | ✅ Sin secretos. `from` se valida contra una gramática cerrada y la ruta se reconstruye: nada de open redirect. La URL solo contiene la consulta que escribió el usuario. |
| V. Calidad | ✅ Tests unitarios de helpers con tablas, integración por historia y regresión del filtro sustituido. `docs/asset-library.md` se actualiza. |
| VI. Git | ✅ Commits pequeños por checkpoint, en inglés, en la rama de la feature, con PR. |

**Post-design re-check**: ✅ sin violaciones; no se necesita Complexity Tracking.

## Arquitectura

### Estado (R1, R2)

```text
URL ──parseLibraryQuery──▶ LibraryQuery ──libraryResults(contents, query, now)──▶ results
 ▲                              │
 └──serializeLibraryQuery◀── update(patch) / withoutFilter / clearFilters  (replace: true)
```

- `useLibraryQuery()` es el único punto de lectura y escritura. No hay `useState` para la
  consulta.
- `search` (string serializado con `?` o vacío) se usa para construir todas las rutas de vista.

### Para que `MediaView.tsx` no crezca

`MediaView.tsx` (681 líneas) ya concentra carga, selección, diálogos y navegación. La feature
**extrae** en lugar de añadir:

| Pieza | Responsabilidad | Tipo |
|---|---|---|
| `library-query.ts` (nuevo) | Tipo `LibraryQuery`, defaults, `parseLibraryQuery`, `serializeLibraryQuery`, `selectionKey`, `libraryReturnParam`, `parseLibraryReturn` | puro |
| `library-filters.ts` (reescrito) | `normalizeText`, `tokenize`, `searchIndex`, `matchesQuery`, `importedWithin`, `sortMedia`, `libraryResults`, `FILTER_DIMENSIONS`, `activeFilters`, `withoutFilter`, `clearFilters`, `emptyResultsKind` | puro |
| `usage-indicator.ts` | `usageOf()` (+ `isNotUsedYet` en función de él) | puro |
| `useLibraryQuery.ts` (nuevo) | Adaptador de `useSearchParams`: `{ query, search, update, clearSearch, clearFilters, removeFilter }` | hook |
| `LibraryFilters.tsx` (nuevo) | Controles por viewport: `select` inline (≥ md) o `Filters` + Sheet + Sort (< md); chips; región `status` | UI |
| `EmptyResults.tsx` (nuevo) | Matriz de estados vacíos con resultados 0 | UI |
| `LibraryToolbar.tsx` | Se queda en el header (title, count, Import, Select, actions) y recibe los filtros como `children`; pierde search, filter y `ChoiceGroup` | UI |
| `MediaView.tsx` | Pasa de `useState(query/filter)` a `useLibraryQuery`; selección derivada; `withSearch()` en sus navegaciones; foco de fallback; `libraryReturn` al detail | orquestación |

### Pipeline (R7)

1. Universo de la vista (`loaded.contents`).
2. Un solo `filter`: type → usage → imported → search, usando el índice de texto memorizado.
3. `sort` (copia).

`results` y `visibleIds` salen de un `useMemo([contents, search])`. `searchIndex` sale de un
`useMemo([contents])`.

### Selección (R8)

`checked: { key, ids } | null`; efectiva = `key !== selectionKey(query) ? ∅ : ids ∩ visibleIds`.
No hay efectos. `toggle`, Move y Delete usan la efectiva. La poda de `load()` se mantiene.

### Navegación y foco (R9, R11)

- `withSearch(path)` en: `mediaPath`, `parentPath`, `<Navigate to /all/:id>`, `handleMoved`,
  `moveChecked`, `mediaDeleted`, `selectionDeleted`, `selectionMissing` y `folderDeleted` (solo
  hacia la carpeta padre).
- `focusTargetAfterDetail(id)` = card o el `<main>` del shell. Lo usan el efecto de cierre actual y el nuevo
  prop `DetailSurface.returnFocus` → `Drawer.returnFocus`.

### Publish (R10)

- `MediaDetail` recibe `libraryReturn` y enlaza a `…/publish?from=…`.
- `PublishTask` resuelve "Back to media" con `parseLibraryReturn`, con el fallback actual.
- `usePublishTask.replaceIds` conserva los params existentes al escribir `posts`.

### UI (R12–R16)

- Escritorio: búsqueda + 4 `select` en `Field`, en un `flex-wrap`, más la fila de chips.
- Móvil: búsqueda; `Filters · N` + Sort; chips con scroll horizontal; `Sheet` con 3
  `ChoiceGroup`.
- `FILTER_DIMENSIONS` es la única definición de dimensiones, opciones y etiquetas.
- Estados vacíos excluyentes con `EmptyState`.
- Región `role="status"` con "N media" solo con búsqueda o filtros.

## Project Structure

### Documentation (this feature)

```text
specs/025-library-search-filters/
├── spec.md
├── plan.md              # este archivo
├── research.md          # R1–R19
├── quickstart.md        # validación manual y comandos dirigidos
├── contracts/
│   └── ui.md            # URL, semántica, toolbar, chips, selección, detail, Publish, vacíos
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks (no creado aquí)
```

Sin `data-model.md` (no hay cambios de modelo) ni contrato de API (no hay cambios de API).

### Source Code (repository root)

```text
frontend/src/
├── pages/library/
│   ├── library-query.ts          # NEW  URL ⇄ LibraryQuery, selectionKey, from (Publish)
│   ├── library-query.test.ts     # NEW
│   ├── library-filters.ts        # REWRITE  search/filter/sort/pipeline/dimensions/chips/empty kind
│   ├── library-helpers.test.ts   # EXTEND (+ update "Not used yet" cases)
│   ├── usage-indicator.ts        # + usageOf()
│   ├── useLibraryQuery.ts        # NEW  hook over useSearchParams
│   ├── LibraryFilters.tsx        # NEW  desktop selects / mobile Filters+Sheet / chips / status
│   ├── EmptyResults.tsx          # NEW
│   ├── LibraryToolbar.tsx        # header only; filters as children
│   ├── MediaView.tsx             # query from URL, derived selection, withSearch, focus fallback
│   ├── MediaDetail.tsx           # libraryReturn → Publish link; returnFocus pass-through
│   ├── LibraryRoot.tsx           # drop showSearch usage if the prop goes away
│   ├── library.css               # filters row, chips row, mobile row
│   ├── search-filters.test.tsx   # NEW  integration: US1–US8
│   └── library.test.tsx          # update assertions of the replaced filter
├── pages/publish/
│   ├── PublishTask.tsx           # Back to media from `from`
│   ├── usePublishTask.ts         # replaceIds keeps other params
│   └── publish-page.test.tsx     # + return context cases
└── ui/
    └── DetailSurface.tsx         # optional returnFocus → Drawer

docs/asset-library.md             # search, filters, sort and URL behaviour
```

**Structure Decision**: aplicación web existente (`frontend/` y `backend/`); solo cambia
`frontend/src` y la documentación.

## Checkpoints

Cada checkpoint termina con sus tests dirigidos en verde y un commit.

### A — Modelo de consulta (puro)

`library-query.ts`, `library-filters.ts` reescrito, `usageOf`.

- Tests: `library-query.test.ts` y `library-helpers.test.ts`, incluidos diacríticos, AND, `#`,
  campos, caracteres especiales, las 36 combinaciones, la partición Used/Unused, los límites
  7/30/90 con `now` fijo, los órdenes y los empates.
- Sin UI.

### B — Controles de escritorio, URL y selección segura

`useLibraryQuery`, `LibraryFilters` (rama ≥ md + chips + status), `LibraryToolbar` reducida,
`MediaView` conectado a la URL, selección derivada (Move congelado al pulsar), y `withSearch` en
`mediaPath`/`parentPath` (abrir y cerrar el detail conserva la consulta).

- Tests: controles ⇄ URL, `replace`, deep link y recarga, back/forward, chips, `Clear all`,
  `Clear search`, las reglas de selección (incluido Move congelado con back/forward), abrir y
  cerrar el detail con params (N1, N2, N3, N11), y la regresión del filtro "Not used yet" (pasa
  a Usage) en `library.test.tsx`, con `setViewport(1300)` explícito.

### C — Contexto de navegación

`withSearch` en el resto de navegaciones (N4–N10), deep link a un Media excluido, Media que deja de
coincidir, foco de fallback (efecto + `DetailSurface.returnFocus`), Publish `from` + `replaceIds`
+ "Back to media".

- Tests: redirect a All media con params (N4), deep link oculto (foco en panel, drawer y página),
  edición → card fuera y foco en `main`, Move/Delete conservan params, Publish ida y vuelta con y
  sin `from`, `from` manipulado.

### D — Móvil y estados vacíos

Rama < md (`Filters` + `Sheet` + Sort + chips desplazables), `EmptyResults`, `Search all media`.

- Tests: estructura móvil con `setViewport(375)`, apertura, cambios y cierre del panel con el foco
  de vuelta, la matriz de vacíos, `Search all media` conserva la consulta, y que no aparece en
  All media.

### E — Pulido, documentación y cierre

- CSS fino y revisión manual a 375, 390, 768, 1024 y 1280 px, incluido el detail lateral.
- `docs/asset-library.md`.
- Una sola vez: lint, format, typecheck, build del frontend y `git diff --check`.
- Revisión del diff.
- Las suites completas van en la CI del PR.

## Testing policy

- Durante la implementación: solo los archivos de test del checkpoint (p. ej.
  `npx vitest run src/pages/library/library-query.test.ts`). No repetir los que ya pasaron si su
  código no cambió.
- Las regresiones adicionales solo donde haya riesgo directo: `folders.test.tsx`,
  `move.test.tsx` y `bulk-delete.test.tsx` en el checkpoint B (selección) y C (navegaciones);
  `publish-page.test.tsx` y `usePublishTask.test.tsx` en C.
- Sin tests ni tareas de backend.
- Los checks estáticos van una sola vez, en E. Las suites completas, solo en la CI del PR.

## Riesgos

| Nivel | Riesgo | Mitigación |
|---|---|---|
| HIGH | Una navegación de `MediaView` sin `withSearch` pierde el contexto | Inventario cerrado en R9; un test por navegación en C; `withSearch` como único camino |
| HIGH | El foco cae al `body` al cerrar el drawer cuando la card ya no existe (Radix) | `DetailSurface.returnFocus` → `Drawer`; tests en los tres modos del detail |
| MEDIUM | `replaceIds` deja de borrar params ajenos: un `from` manipulado sobrevive | `from` se valida en cada lectura; inválido → fallback |
| MEDIUM | La toolbar de escritorio pasa de dos filas a 1024 o con el detail lateral | `select` compactos (R12); verificación manual en E; FR-062 confirmado: envolver con el panel lateral está permitido, sin overflow |
| MEDIUM | Input controlado desde la URL con un caret que salta o lag | Mismo patrón que Posts (ya funciona); test de escritura continua |
| MEDIUM | Regresión de tests que usan el radio "Not used yet" | Actualizar en B (SC-010 lo prevé) |
| MEDIUM | 10k Media: render previo a la feature | Fuera de alcance, registrado |

## Decisiones confirmadas (2026-10-28)

1. **FR-062 — toolbar de escritorio**: el máximo de dos filas se evalúa con el ancho normal de
   contenido de la Library. Con el detail como panel lateral, la toolbar puede envolver de forma
   natural a más filas, sin comprimir los controles hasta hacerlos poco legibles y sin un
   breakpoint nuevo. Nunca hay overflow horizontal.
2. **Filtros de escritorio con `select`**: búsqueda + `select` de Media type, Usage, Imported y
   Sort, con `Field` y los controles existentes. Se eliminan los pills actuales de Media type; no
   se crea un control visual nuevo.
3. **Foco de fallback**: el `<main>` del shell (`<main id="main-content" tabIndex={-1}>` en `AppShell`; la decisión lo llamaba `id="main"`)
   (enfocable por programa y fuera del orden de Tab). Reutiliza el fallback actual de
   `cardLeaving`. El foco nunca termina en `<body>`.

No quedan decisiones abiertas.

## Complexity Tracking

No aplica: sin violaciones de la Constitution.
