# Implementation Plan: Visual Refresh

**Branch**: `023-visual-refresh` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/023-visual-refresh/spec.md` + [visual-design-brief.md](visual-design-brief.md)

## Summary

Refresh visual **solo de frontend** ("Same product, new presentation") aplicado como sistema
en seis capas: tokens → shared UI → shell → core (Home, Library, Login) → secondary (Posts,
Calendar, Accounts/connections, Settings, project chrome, Publish heredado) → responsive,
legacy cleanup y validación. La palanca principal es `ui/tokens.css`: se sustituyen los
primitivos azules/grises por la paleta cálida del brief (con los ajustes AA ya medidos) y se
redefinen los semánticos **conservando sus nombres**, de modo que la fase A cambia el aspecto
de toda la app sin tocar CSS de página. Geist se sirve localmente con
`@fontsource-variable/geist` (OFL, sin CDN). D1 se resuelve con un token
`--control-height` (44px por defecto, 40px en `lg` + puntero fino) sin duplicar `Button`. El
status map cambia solo de tono (`info` → `active`; Needs review → warning). Se eliminan
duplicaciones reales (6 menús, 3 headers, 5 controles nativos, 2 `.ap-technical`) con
modificadores CSS compartidos (`.ap-menu`, `.ap-page-header`, `.ap-input`), sin primitives
nuevos. El CSS legacy de `index.css` (reglas globales de elemento + clases de los 5 connection
panels) se migra a `ap-connection*` en la fase E. Ningún cambio de rutas, DOM accesible,
copy funcional, pasos ni backend.

Detalle y alternativas: [research.md](research.md). Valores y reglas: [contracts/ui.md](contracts/ui.md).
Validación: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: TypeScript ~6.0 / React 19 (frontend). Python backend sin cambios.

**Primary Dependencies**: React Router 8.4, `@radix-ui/react-dialog` 1.1.23 (sin cambios).
**Nueva**: `@fontsource-variable/geist` (versión exacta, `5.3.0` o la estable vigente al
implementar, sin `^`; OFL-1.1). Ninguna librería de UI, iconos ni animación.

**Storage**: N/A (sin datos).

**Testing**: Vitest + Testing Library (jsdom; CSS no procesado). Tests dirigidos por
checkpoint ([quickstart.md §1](quickstart.md)); suites completas solo en la CI del PR.

**Target Platform**: navegadores evergreen de escritorio y móvil (app local servida por el
backend; acceso remoto/móvil de Feature 020).

**Project Type**: web application (frontend + backend); solo se toca `frontend/` y `docs/`.

**Performance Goals**: sin JS nuevo para efectos; CSS total ≤ ~+10 % (los duplicados
eliminados compensan los estados nuevos); fuente ~30–40 KB por subset descargado; sin
bloqueo de render perceptible (`font-display: swap`).

**Constraints**: 0 peticiones externas (SC-008); WCAG 2.2 AA (contracts §1.4); targets ≥ 44px
en táctil; reduced motion; sin cambio de rutas/DOM accesible/copy (FR-001…006).

**Scale/Scope**: 14 archivos CSS (3 964 líneas), ~20 primitives/shared, 9 diálogos, 10
pantallas/áreas.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Solo CSS + cambios mínimos de marcado (clases, `EmptyState.icon?`, paths de `Icon`, `Tone`). Sin primitives nuevos, sin framework UI, sin JS para efectos. Scope = spec (D1–D9 cerradas) | ✅ |
| II. Spec-Driven | Spec + brief aprobados como fuente de verdad; este plan no añade comportamiento | ✅ |
| III. Arquitectura modular | Sin cambios backend/adapters; capas frontend respetadas (tokens → ui → shell → pages) | ✅ |
| IV. Seguridad | Fuente vía paquete npm con licencia OFL; ningún secreto/medio privado; la instancia de validación es scratch (memoria del proyecto) | ✅ |
| V. Calidad | Tests dirigidos por checkpoint; asserts funcionales intactos; checks estáticos y build al cierre; doc `design-system.md` actualizada (DR-001) | ✅ |
| VI. Git | Commits pequeños por capa en inglés; sin big-bang; sin mezclar refactors funcionales | ✅ |
| Arquitectura base (React + Vite) | Se mantiene; nueva dependencia mínima justificada (D2) | ✅ |

**Post-design re-check**: sin violaciones. La única dependencia nueva es un paquete de fuente
estático (sin JS en runtime). No hay Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/023-visual-refresh/
├── spec.md
├── visual-design-brief.md
├── plan.md              # este archivo
├── research.md          # Phase 0 (R0 inventario, R1–R22 decisiones)
├── contracts/ui.md      # Phase 1: tokens, componentes, status map, shell, pantallas, invariantes
├── quickstart.md        # Phase 1: validación por checkpoint
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (no creado aquí)
```

Sin `data-model.md` (la feature no toca datos).

### Source Code (repository root)

```text
frontend/
├── package.json                      # + @fontsource-variable/geist (exacta)
└── src/
    ├── main.tsx                      # import de la fuente (1 línea)
    ├── index.css                     # A: base a tokens · E: legacy fuera (queda base o se elimina)
    ├── ui/
    │   ├── tokens.css                # A: primitivos + semánticos + control-height + motion
    │   ├── ui.css                    # B: primitives, .ap-menu, .ap-page-header, .ap-input, .ap-actions, motion de modales
    │   ├── status.ts / Badge.tsx     # A: Tone (info → active), Needs review → warning
    │   ├── Icon.tsx                  # B/D: paths folder, image, inbox, grid
    │   └── EmptyState.tsx            # B: icon? opcional
    ├── shell/
    │   ├── shell.css                 # C: sidebar/rail oscuros, bottom bar clara, TopBar, Flash
    │   └── PrimaryNav.tsx            # C: marcado del wordmark (monograma decorativo)
    ├── components/
    │   ├── delete-confirm-dialog.css # B
    │   ├── connection.css            # E: nuevo, sustituye legacy de index.css
    │   ├── *ConnectionPanel.tsx      # E: solo nombres de clase legacy → ap-connection*
    │   ├── MediaPreview.tsx          # D: sin cambios de clase (.preview se recolorea)
    │   └── platform/platform.css     # E
    └── pages/
        ├── login/login.css           # D
        ├── home/home.css (+ .tsx solo clases)   # D
        ├── library/library.css (+ MediaCard/Entries/Toolbar clases) # D
        ├── posts/posts.css           # E
        ├── accounts/accounts.css     # E
        ├── settings/settings.css     # E
        ├── project/project.css       # E
        └── publish/publish.css       # E (solo heredado/limpieza)
docs/design-system.md                 # F (DR-001)
backend/                              # sin cambios
```

**Structure Decision**: web application existente; la feature vive en `frontend/src` (estilos
y marcado de presentación) y `docs/design-system.md`.

## Design

### 1. Arquitectura visual final

```text
tokens.css (primitivos → semánticos, control-height, motion, focus)
   │
   ├── ui.css  (primitives + patrones compartidos: .ap-menu, .ap-page-header, .ap-input,
   │            .ap-actions, selección, modales con motion)
   │      │
   │      ├── shell.css (sidebar/rail/bottom bar/TopBar/Flash)
   │      └── pages/*.css (solo composición/layout propio de la pantalla)
   └── index.css (base :root/body; legacy eliminado en E)
```

Regla: una pantalla solo define **layout y composición**; color, tipografía, radios, sombras,
motion y estados vienen de tokens y de `ui.css`.

### 2. Token system final

Ver [contracts/ui.md §1](contracts/ui.md): primitivos `stone/night/moss/leaf/amber/clay`,
semánticos con nombres existentes + `sidebar-*`, `focus-on-dark`, `focus-ring-soft`,
`surface-elevated`, `media-overlay`, status tones `neutral/active/success/warning/danger`,
tipografía 12–34px con 400/500/550/600, radios 6/10/12/16/20/pill, 3 sombras, motion 140/200ms,
`--target-min` 44 y `--control-height` 44/40, `--page-gutter`, `--section-gap`.

Renombres necesarios en fase A (búsqueda/reemplazo controlada, mismo commit que tokens):
- tamaños: `--text-md` (body 16 → 15) → los usos de body pasan a `--text-base`; los usos de
  "card title 18" (`--text-lg`) se revisan;
- `--status-info-*` → `--status-active-*` (2 archivos);
- `--color-border-control` mantiene nombre (cambia valor).

### 3. Typography / font strategy

`@fontsource-variable/geist` importado en `main.tsx`; familia `"Geist Variable"` primero en
`--font-sans`; `font-display: swap`; subsets por `unicode-range`; pesos vía eje `wght`;
fallback system stack; sin fallback metrics en 023 (R3); `html` a 100 % (text-size del usuario),
cuerpo 15px en `rem`; inputs a 16px en `sm`; `tabular-nums` en tiempos/contadores (R4).

### 4. Status mapping final

[contracts/ui.md §5](contracts/ui.md). Solo cambia `tone`; labels/iconos idénticos.
`needs_review` = **warning**. `Tone` pierde `info` y gana `active` (Publishing). Alineados
fuera del mapa: `usage-indicator.ts` y `DeleteConfirmDialog __changed`.

### 5. Shared-component strategy

[contracts/ui.md §3–§4](contracts/ui.md). Principios:
- Todo en `ui.css`; ninguna primitive nueva. Tres patrones compartidos como **clases**
  (`.ap-menu`, `.ap-page-header`, `.ap-input`) y uno como regla (§4 selección).
- Únicos cambios de API: `EmptyState.icon?` (opcional), `Tone` (`info`→`active`), paths
  nuevos en `Icon`.
- Sheet en `sm` pasa a bottom sheet (solo CSS; misma clase `ap-modal--sheet`).
- `scroll-padding-bottom` de `PageActions` se recalcula con `--control-height`.
- Tests en riesgo por selectores (se conservan esas clases): `ap-button--*`, `ap-delete-entry`,
  `ap-modal--*`, `ap-page-actions--sticky`, `ap-delete-dialog__name`, `.ap-delete-dialog p`.

### 6. Shell strategy

[contracts/ui.md §6](contracts/ui.md), research R12. Solo CSS + monograma decorativo en
`PrimaryNav` (`aria-hidden`). `lg`: sidebar oscura en columna flex, Settings al pie con
`margin-top:auto` (mismo orden DOM), activo = pill `sidebar-active` + 550, foco
`--color-focus-on-dark` scoped a `.ap-nav`; selector oscuro. `md`: rail oscuro + TopBar
clara. `sm`: bottom bar clara con activo ink + 550 + pill accent-soft tras el icono; More
con `.ap-menu`. `body`/shell en canvas. Sin cambios en `AppShell`, `useMediaQuery`, rutas,
task mode.

### 7. Library strategy

Research R14, contracts §7:
- **Root**: entries Unsorted / All media / folders como tarjetas horizontales en
  `surface-muted` con iconos `inbox` / `grid` / `folder` (misma familia), nombre 15/550.
- **Media card**: preview a sangre `aspect-ratio: 4/5`, `cover`; cuerpo compacto (title 1
  línea, meta, badge sm); ~75 % del área en cards estándar (target, no umbral); borde
  decorativo en reposo; hover/focus `--shadow-raised` + `translateY(-1px)`; menú `IconButton`
  circular siempre visible (nada solo en hover).
- **Folders**: forma horizontal sin thumbnail + superficie muted + icono outline → identidad
  distinta sin carpeta amarilla.
- **Selected / checked**: patrón §4; checkbox 22px sobre chip blanco, siempre visible en
  Select mode.
- **Select mode**: SelectionBar ink con botones on-dark; Move/Delete/Cancel y su lógica
  intactos; `ap-selection-bar__count` se conserva.
- **Import**: dropzone con borde discontinuo control + fondo accent-soft al arrastrar;
  ImportPanel superficie elevada.
- **Detail**: preview `contain` sobre muted (máx. 60vh), FileDetails como lista definicional,
  editor con `Field`/`.ap-input`, usage como filas.
- **Edge cases**: placeholder con icono `image` en muted; 9:16/panorama `cover` en grid y
  `contain` en detalle; nombres 1 línea con ellipsis; overlays con `--color-media-overlay`.
- **Grid**: misma arquitectura `auto-fill`; `minmax(clamp(150px, 20vw, 220px), 1fr)`; 2
  columnas a 375px; gap 12/16.

### 8. Home strategy

Research R15. Misma información y orden DOM; jerarquía por tamaño, superficie y composición:
attention en superficie única con filas (urgente: barra danger + icono), ok-state como línea
tranquila, banner pausado compacto, Up next como timeline con hora `tabular-nums`, Projects
como tiles sin cifras grandes. `lg`+: grid de dos columnas por CSS (Attention + Up next |
Projects); `<lg`: una columna. Sin datos nuevos, sin backend, sin KPI cards.

### 9. Login strategy

Research R16. Marco `--color-sidebar` a pantalla completa; panel claro centrado 400px, radio
20, sombra modal; h1 "AutoPublisher" como wordmark dentro del panel con monograma decorativo;
Password (16px), `Sign in` primary a ancho completo, error con icono, nota de reset en meta al
pie. `sm`: margen 16px, mismo orden, sin animación. Sin copy nuevo, OAuth ni imágenes.

### 10. Secondary-screen strategy

Research R17–R18:
- **Posts**: filas en superficie única, when tabular, secciones por espacio, switch segmented
  neutro, `New post` con `.ap-menu`, Post detail con StatusActionPanel en muted.
- **Calendar**: layout/breakpoints intactos; líneas sutiles; hoy = chip + "Today"; eventos con
  borde de tono y outline al seleccionar.
- **Settings**: secciones de dos columnas en `lg` (título/descr. existente | contenido en una
  superficie), una columna en `<lg`; sin anchors/navegación; filas con separadores.
- **Accounts / connections**: cards/tiles con StatusBadge; banda de estado en el detalle;
  legacy → `ap-connection*` (R11).
- **Project chrome**: eyebrow + `.ap-menu`, strip de pills, onboarding con pasos numerados.
- **Publish**: hereda; solo se limpian literales y se adoptan `.ap-input`/selección.
- **Errores**: ErrorState/NotFound/RouteError con el sistema.

### 11. CSS migration strategy

Por capas, cada una deja la app **coherente y funcional** (sin big-bang):

| Capa | Qué cambia | Qué desaparece | Qué permanece temporalmente |
|---|---|---|---|
| A tokens | primitivos y semánticos, font, control-height, motion, status | primitivos azules, `--status-info-*` | todo el CSS de página (ya consume semánticos → hereda paleta) |
| B shared | `ui.css`, delete dialog, `.ap-menu`, `.ap-page-header`, `.ap-input`, `.ap-actions` | estilos de región duplicados en 6 archivos (reemplazados por `.ap-menu` + posicionamiento) | headers de página antiguos hasta que su pantalla migre |
| C shell | `shell.css`, wordmark | indicador `::before` en lg/md | — |
| D core | home/library/login CSS; `.preview` a tokens | `rgb(31 35 40 / .8)` literal; headers `ap-library__header` → `.ap-page-header` | — |
| E secondary | posts/accounts/settings/project/platform/publish CSS; `connection.css` nuevo | legacy de `index.css` (`form/label/fieldset` globales, `.badge .muted .actions .account .notice .channel-change …`); `.ap-technical` duplicado (queda uno en `ui.css`) | `.error` (alias de texto danger, 17 usos con `role="alert"`, recoloreado) |
| F cleanup | revisión de literales, tamaños, docs | restos detectados por la búsqueda de literales | — |

Las reglas globales de elemento (`form`, `label`, `fieldset`) se retiran **después** de dar
clase explícita a los formularios que dependen de ellas (ProjectForm, connection panels,
TikTok inbox), dentro de E y con checkpoint propio.

### 12. Responsive / visual-validation strategy

Arquitectura responsive intacta (breakpoints, DetailSurface, drawers, sticky PageActions,
task mode, bottom nav + safe-area). Checkpoints visuales A–F en la instancia segura a 375 y
1280 (768/1024 cuando el checkpoint toca layout), y en F: 375/768/1024/≥1280 + 200 % texto +
reduced motion + safe-area + labels largos sobre las 8 pantallas prioritarias
([quickstart.md §2](quickstart.md)). No se revisan todas las combinaciones.

### 13. Implementation checkpoints

| Fase | Contenido | Checkpoint |
|---|---|---|
| **A — Foundation** | tokens finales, Geist, `Tone`/status map, base `:root`/`body` en canvas, focus/motion globales | vitest `src/ui` + shell; revisión: paleta, fuente local, badges |
| **B — Shared UI** | Button/IconButton/inputs (control-height), Badge, Card, EmptyState(icon), ErrorState, Skeleton, Dialog/Drawer/Sheet (bottom sheet + motion), Field, ChoiceGroup, PageActions, `.ap-menu`, `.ap-page-header`, `.ap-input`, delete dialog | vitest ui + DeleteConfirmDialog + bulk-delete; revisión dialogs/sheet/menus/alturas |
| **C — Shell** | sidebar/rail oscuros, wordmark, bottom bar clara, TopBar, More, selector, Flash | vitest shell + routes; revisión 375/768/1280 + teclado |
| **D — Core** | Home, Library (root, grid, cards, folders, select, import, detail), Login, MediaPreview | vitest home/library/login/MediaPreview; revisión Library a fondo |
| **E — Secondary** | Posts, Calendar, Accounts + connections (legacy → `ap-connection*`), Settings, project chrome, Publish heredado, errores | vitest posts/accounts/settings/onboarding/project/connection panels/publish; revisión |
| **F — Responsive / cleanup / final** | literales, retirada final de legacy, `docs/design-system.md`, revisión completa, checks estáticos y build una vez | lint, format, typecheck, build, `git diff --check`; revisión final del usuario |

### 14. Tests críticos

Comportamiento que **debe** seguir verde sin tocar asserts funcionales:
- navegación y shell (`shell.test.tsx`, `routes.test.tsx`): destinos, More, task mode, selector;
- diálogos (`DeleteConfirmDialog.test.tsx`, `detail-surface.test.tsx`): variante por
  breakpoint, foco, exactly-one-confirmation;
- Library (`library`, `folders`, `move`, `bulk-delete`, `media-delete`, `media-content`,
  `media-usage`, `FileDetails`): Select mode, Move, Bulk Delete, breadcrumb;
- Posts (`posts`, `post-detail`, `calendar-view`, `action-dialog`, `activity`, `check-result`);
- Publish (`publish-page`, `compose`, `review`, `final-action`, `finish-later`…);
- Accounts/connections (`accounts.test`, `*ConnectionPanel.test`, `TikTokInboxDelivery.test`);
- forms (`field-choice.test`, `settings.test`, `auth.test`, `login.test`, `onboarding.test`);
- `page-actions.test` (sticky), `home.test`.
Solo se ajusta un test si dependía de una clase **no** listada en contracts §9.5 y la clase
desaparece por motivos puramente visuales (previsto: ninguno).

### 15. Riesgos

| Nivel | Riesgo | Mitigación |
|---|---|---|
| HIGH | Retirar `form/label/fieldset` globales de `index.css` rompe layout de formularios legacy sin aviso de tests | Inventario de dependientes, clase explícita antes de retirar, checkpoint E dedicado con todos los connection panels |
| HIGH | Alcance amplio → deriva a CSS por pantalla o big-bang | Capas A–F, regla "pantalla = layout", búsqueda de literales (SC-003), commits por capa |
| HIGH | Bottom sheet en `sm` con contenido largo (Add account + connection panel, Presets) | `max-height` + scroll interno, safe-area, revisión específica en B/E |
| MEDIUM | Cambio de escala tipográfica (`--text-md` deja de ser body) produce tamaños inesperados | Renombre controlado en A y revisión visual inmediata |
| MEDIUM | 40px en desktop: `scroll-padding` y layouts que asumían `--target-min` | `--target-min` se conserva para táctil; recalcular cálculos que usan alturas de control |
| MEDIUM | Sidebar oscura: elementos heredados (select, focus, disclosures) ilegibles sobre oscuro | Tokens `sidebar-*` y `focus-on-dark` scoped a `.ap-nav`; revisión C |
| MEDIUM | Swap de fuente visible en la primera carga | Fuente local (rápida), `swap`; fallback metrics solo si el checkpoint A lo justifica |
| MEDIUM | Tests acoplados a clases | Clases-contrato conservadas (contracts §9.5) |
| MEDIUM | Overlays sobre thumbnails con contraste insuficiente | `--color-media-overlay` (≥ 6.9:1 peor caso) |

### 16. Decisiones pendientes

Ninguna de producto (D1–D9 cerradas). Decisiones técnicas tomadas en este plan y abiertas
solo a ajuste en checkpoint, sin cambiar dirección: aspect-ratio 4:5 de las Media cards,
`minmax` de la grid, fallback metrics de la fuente (no por defecto).

## Complexity Tracking

Sin violaciones de la constitución; no aplica.
