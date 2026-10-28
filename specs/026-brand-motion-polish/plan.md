# Implementation Plan: Brand & Motion Polish

**Branch**: `026-brand-motion-polish` | **Date**: 2026-10-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/026-brand-motion-polish/spec.md`

## Summary

Añadir identidad y feedback en seis momentos concretos con CSS y estado React mínimo y efímero:

- Login y Auth loading: entrada de marca, monograma y glow estático.
- Indicador acotado en los badges Publishing.
- Énfasis único en la transición observada Publishing → Published.
- Highlight de los Media recién importados.
- Highlight del Post reprogramado en el Calendar.
- Favicon.

Además:

- un único token `--motion-emphasis` (360 ms), con una política "bounded": ningún `infinite`
  nuevo, todo termina antes de 5 s;
- un guard `(hover: hover) and (pointer: fine)` para los dos lifts existentes.

Sin backend, sin dependencias, sin page transitions. Decisiones en [research.md](research.md),
contrato en [contracts/ui.md](contracts/ui.md) y validación en [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: TypeScript 6 + React 19, React Router 8. Backend Python + FastAPI, sin cambios.

**Primary Dependencies**: las existentes (`@radix-ui/react-dialog`, Geist). Ninguna nueva.

**Storage**: N/A. Todo el estado es efímero, de componente; nada de `localStorage` ni
`sessionStorage`.

**Testing**: Vitest + Testing Library (`test-utils.tsx`, `test-fake-api.ts`). Se usa
`fireEvent.animationEnd` para la limpieza. La verificación visual y de motion se hace por
Chrome/CDP.

**Target Platform**: navegadores modernos, escritorio y móvil, contra la instalación local.

**Project Type**: aplicación web; solo cambia el frontend.

**Performance Goals**:
- Solo se animan `opacity`, `transform`/`translate`/`scale` y `box-shadow`.
- Sin bucles JS ni RAF.
- Unos 1–2 KB de CSS más.
- El Login sigue interactivo desde el primer frame.

**Constraints**:
- Ninguna animación nueva indefinida (< 5 s).
- La regla global de reduced motion es el único mecanismo.
- Sin cambio de foco ni de layout.
- WCAG 2.2 AA.

**Scale/Scope**: unos 14 archivos de frontend tocados, 3 nuevos de código/asset y 3 nuevos de
tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación |
|---|---|
| I. Simplicidad y alcance | ✅ Un token, 4 keyframes nuevos y uno reutilizado. Un hook de 15 líneas y dos props opcionales en `Badge`. No hay framework de motion, ni contexto global, ni timers de respaldo (R2). El scope es el de la spec corregida; nada de empty states, Flash ni Home. |
| II. Spec-Driven | ✅ Cada decisión remite a FR/SC (tabla abajo). Las tres correcciones previas (FR-005a, FR-015a, FR-049) se aplicaron antes de planificar. |
| III. Arquitectura modular | ✅ Solo frontend. Las primitives quedan en `ui/` (`Badge`, `StatusBadge`, `usePublishedEmphasis`) y la lógica de cada flujo en su página (`MediaView`, `CalendarView`). No hay lógica de plataformas. |
| IV. Seguridad | ✅ Sin secretos ni datos nuevos. El favicon es un asset estático público y no hay persistencia. |
| V. Calidad | ✅ Tests de estado por historia, un test de contrato "no infinite" y revisión por CDP con reduced motion. Se actualiza `docs/design-system.md`. |
| VI. Git | ✅ Commits pequeños por checkpoint, en inglés, en la rama de la feature, con PR. |

**Post-design re-check**: ✅ sin violaciones. No hace falta Complexity Tracking.

## Arquitectura

### Motion foundation (R1, R2; contrato §1)

- **`tokens.css`**: `--motion-emphasis: 360ms`, que pasa a `0ms` en el bloque reduced-motion.
  Token de color `--color-auth-glow`.
- **`ui.css`**: keyframes `ap-pulse`, `ap-badge-emphasis` y `ap-highlight`.
- **`login.css`**: el keyframe `ap-mark-bar`, solo para el Login.
- Duraciones derivadas con `calc()`:
  - pulso: × 3, 3 iteraciones;
  - highlight: × 4.
- Keyframes solo con `from` y sin `forwards`. El estado final es el natural, así que un
  atributo residual es inerte.
- Limpieza por `onAnimationEnd` filtrado por `animationName`. Funciona con reduced motion,
  porque la regla global deja 0,01 ms y el evento sigue llegando.

### Login / Auth (R3–R5; contrato §2)

```text
AuthGate ──loading──▶ <AuthLoading/>      LoginPage ──loading──▶ <AuthLoading/>
   └──error──▶ <main.ap-auth-loading> ErrorState (sin motion)
LoginPage ──ready──▶ <main.ap-login> <form.ap-login__card [ap-rise-in]> h1 .ap-mark::after [ap-mark-bar]
```

- El glow es una capa de `background` en `.ap-login` y `.ap-auth-loading`, que solo usan las
  superficies de autenticación. El contraste mínimo calculado es 5,6:1 (R3).
- No hay timers, ni estado, ni cambios en `handleSubmit`, en `autoFocus` ni en las redirecciones.

### Publishing y Published (R6–R8; contrato §3)

```text
Badge(activity, emphasis, onEmphasisEnd)
  ▲                      ▲
StatusBadge(post)        ResultsSection › ResultBadge(post, view)
  activity = state==="publishing"     activity = view.outcome==="publishing"
  usePublishedEmphasis(state)          usePublishedEmphasis(post.display_state)
```

- **Inventario**: 6 superficies vía `StatusBadge` (PostRow, CalendarView, StatusActionPanel,
  UpNext, AttentionList, MediaUsage) y una vía `Badge` (ResultsSection).
- "Processing" de Results comparte el indicador porque es el mismo `display_state`.
  "Processing in TikTok" queda fuera.
- **Detección**: estado derivado durante el render. Inicializado = montaje.
  - **Vía A** (todas las vistas): la misma instancia pasa de `publishing` a `published`. Se
    observa en Post detail, Calendar y Publish Results, que hacen poll con el badge montado.
  - **Vía B** (solo Publish Results, FR-020a): la fila es de la operación actual
    (`steps[id].run === "now"`, `status === "done"`, sin `emphasized`) y monta ya en
    `published`.
  - En Results, el énfasis mostrado despacha `emphasis_shown`, que marca `steps[id].emphasized`.
    Así no se repite al re-montar. `run_start` reinicia la operación.

```text
usePublishTask.steps (efímero, por operación) ──initiallyEmphasized──▶ ResultBadge
ResultBadge ──emphasis_shown(id)──▶ reducer: steps[id].emphasized = true
```

### Import highlight (R9; contrato §4)

```text
importFiles ─▶ ids(imported) ─▶ onImported(ids) ─▶ MediaView: await load()
   ─▶ setJustImported({ ids, key: keyRef.current, loadedAt })
   ─▶ MediaGrid ▶ MediaCard[data-just-imported]  (key ∧ loadedAt match ∧ id ∈ ids ∧ visible)
   ─▶ animationend(ap-highlight) ─▶ remove id ─▶ null
```

### Calendar highlight (R10; contrato §5)

```text
ActionDialog.onDone(result) ─▶ await onChanged() ─▶ rescheduled.current = id; announcement (sin cambios)
   ─▶ if result.scheduled_at ≠ previous ∧ nueva fecha ∈ semana visible: setLanded({ id, week })
render: data-just-rescheduled ⇔ landed.id = post.id ∧ landed.week = week actual
   ─▶ animationend ─▶ setLanded(null)
openDialog ─▶ setLanded(null)
cambio de semana (botones, Back/Forward, URL) ─▶ week ≠ landed.week ─▶ sin atributo (derivado)
```

### Favicon y hover guard (R12, R13; contrato §6, §7)

- Favicon: `public/favicon.svg` y un `<link rel="icon">` en `index.html`.
- Hover guard: solo `.ap-media-card:hover` y `.ap-home-tile:hover` pasan a
  `@media (hover: hover) and (pointer: fine)`. `:focus-visible` mantiene el lift.

## Trazabilidad FR → diseño

| FR | Diseño |
|---|---|
| FR-001–005a | R1, R2; contrato §1; test "no infinite" |
| FR-006–008 | R3; contrato §2 (marco) |
| FR-009–011 | R4 |
| FR-012–014 | R5 |
| FR-015–019 | R6, R7; contrato §3 |
| FR-020–024 | R8; contrato §3 |
| FR-025–029 | R9; contrato §4 |
| FR-030–033 | R10; contrato §5 |
| FR-034–035 | R12 |
| FR-036–037 | R13 |
| FR-038–046 | R2, R11; quickstart (CDP, reduced motion, anchos) |
| FR-047–052 | §8 del contrato (sin cambios) |
| FR-053 | `docs/design-system.md` (checkpoint E) |

## Checkpoints

Cada checkpoint es estable y se puede commitear por separado. Se ejecutan solo los tests
dirigidos de cada uno (quickstart).

| Checkpoint | Contenido | Tests dirigidos |
|---|---|---|
| **A — Motion foundation + Auth** | Token `--motion-emphasis` y su valor reduced; `--color-auth-glow`; keyframes base; hover guard; favicon; glow; entrada del Login y monograma; `AuthLoading` en `AuthGate` y `LoginPage`. | `login.test.tsx` (marcadores, `aria-hidden`, autofocus, envío inmediato); `shell.test.tsx` (Auth loading con marca y error de sesión); nuevo `motion-policy.test.ts` (sin `infinite` salvo `ap-spin`; el token existe y pasa a 0 con reduced) |
| **B — Publishing feedback** | Props `activity`/`emphasis` en `Badge`; `usePublishedEmphasis` (vías A y B); `StatusBadge`; `ResultBadge` en `ResultsSection`; `emphasized` + `emphasis_shown` en `usePublishTask`. | Nuevo `published-emphasis.test.tsx` (los 6 casos de R8 con `rerender`, incluido el fast-path propio de Results; el punto solo en publishing; "Processing" de Results sí; `animationend` limpia; otro `animationend` no limpia); `usePublishTask.test.tsx` (`emphasis_shown`; `run_start` reinicia); regresión dirigida en `post-detail.test.tsx` y `final-action.test.tsx` (texto y anuncio sin cambios) |
| **C — Import highlight** | `onImported(ids)`; `justImported` en `MediaView`; prop en `MediaGrid`/`MediaCard`; CSS. | Nuevo `import-highlight.test.tsx` (solo los importados; duplicados, rechazados y fallidos excluidos; oculto por filtro sin marcar ni mostrar, filtros intactos; cambio de consulta invalida; `animationend` limpia; raíz sin highlight); `search-filters.test.tsx` como regresión directa |
| **D — Calendar highlight** | Estado `landed: { id, week }`, fijado solo si la fecha cae en la semana visible; atributo solo si coincide la semana (semana y agenda); limpieza en `openDialog` y `animationend`. | `calendar-view.test.tsx`: éxito marca el item correcto; cancel, 409/error y misma fecha no; fuera de rango no; foco y anuncio idénticos a la 024 |
| **E — Docs + verificación** | `docs/design-system.md` (token de énfasis, política bounded, excepción de glow, hover guard, reduced motion); revisión CDP completa (quickstart); checks estáticos una vez. | lint, `format:check`, typecheck, build y `git diff --check`; sin suites completas en local |

## Archivos previstos

```text
frontend/
├── index.html                               # A: <link rel="icon">
├── public/favicon.svg                       # A: nuevo
└── src/
    ├── ui/
    │   ├── tokens.css                       # A: --motion-emphasis, --color-auth-glow, reduced
    │   ├── ui.css                           # A/B/C: ap-pulse, ap-badge-emphasis, ap-highlight, .ap-badge__activity, [data-emphasis]
    │   ├── Badge.tsx                        # B: activity, emphasis, onEmphasisEnd
    │   ├── StatusBadge.tsx                  # B: actividad + énfasis (variante post)
    │   ├── usePublishedEmphasis.ts          # B: nuevo
    │   ├── motion-policy.test.ts            # A: nuevo
    │   └── published-emphasis.test.tsx      # B: nuevo
    ├── shell/
    │   ├── AuthLoading.tsx                  # A: nuevo
    │   ├── AuthGate.tsx                     # A: usa AuthLoading
    │   └── shell.test.tsx                   # A: amplía
    ├── pages/
    │   ├── login/LoginPage.tsx              # A: usa AuthLoading
    │   ├── login/login.css                  # A: glow, entrada, ap-mark-bar, estilos del loading
    │   ├── login/login.test.tsx             # A: amplía
    │   ├── home/home.css                    # A: hover guard de la tile
    │   ├── publish/review/ResultsSection.tsx # B: ResultBadge (vía B)
    │   ├── publish/usePublishTask.ts         # B: PostStep.emphasized, acción emphasis_shown
    │   ├── library/library.css              # A/C: hover guard de la card, [data-just-imported]
    │   ├── library/useMediaImport.ts        # C: onImported(ids)
    │   ├── library/MediaView.tsx            # C: justImported
    │   ├── library/LibraryRoot.tsx          # C: firma de onImported (ignora ids)
    │   ├── library/MediaGrid.tsx            # C: prop
    │   ├── library/MediaCard.tsx            # C: data-just-imported + onAnimationEnd
    │   ├── library/import-highlight.test.tsx # C: nuevo
    │   ├── posts/CalendarView.tsx           # D: landed
    │   ├── posts/posts.css                  # D: [data-just-rescheduled]
    │   └── posts/calendar-view.test.tsx     # D: amplía
docs/design-system.md                        # E
```

Backend: sin cambios y sin tareas.

## Riesgos

| Nivel | Riesgo | Mitigación |
|---|---|---|
| MEDIUM | **Detección de Published**: falsos positivos al montar o énfasis repetidos con el poll | Inicialización = montaje (estado derivado; con `StrictMode` es idempotente); comparación solo ante cambio de estado; tests con `rerender` para los 5 casos |
| MEDIUM | **Fast-path de Published** (FR-020a): que se filtre fuera de Results o se repita al re-montar | La opción solo la pasa `ResultsSection`; la elegibilidad sale de `steps`, que se reinicia por operación y se pierde al recargar; la marca `emphasized` se pone en el reducer; casos 3 y 5 con tests propios |
| MEDIUM | **Highlight de import sobre las cards equivocadas** tras la relectura o un cambio de consulta | ids del propio resultado; key leída de un ref en el momento de fijar; la invalidación por key y por visibilidad se testean |
| MEDIUM | **Contraste del glow** | Alfa 0,28 calculada (≥ 5,6:1 en el peor punto); comprobación visual por CDP |
| MEDIUM | **Atributo residual si la animación no corre** (`hidden`/`display: none`) | Keyframes solo con `from`: el atributo es visualmente inerte; se re-evalúa al desmontar o cambiar de estado (R2) |

No hay riesgos HIGH: no hay backend, no cambia el foco y la regla de reduced motion ya es global.

## Decisiones cerradas

1. **Published instantáneo**: se admite el fast-path de Publish Results (FR-020a), basado en el
   contexto efímero `steps` de la operación actual.
2. **Texto del Auth loading**: exactamente "Loading AutoPublisher…".

## Complexity Tracking

Sin violaciones de la Constitution.
