# Tasks: Visual Refresh

**Input**: `specs/023-visual-refresh/` — [spec.md](spec.md), [visual-design-brief.md](visual-design-brief.md),
[plan.md](plan.md), [research.md](research.md), [contracts/ui.md](contracts/ui.md),
[quickstart.md](quickstart.md), y `docs/design-system.md` (estado 018 a actualizar en F).

**Regla**: *Same product, new presentation.* Ningún cambio de rutas, DOM accesible, copy
funcional, pasos, confirmaciones, datos ni backend. Todas las rutas de archivo son relativas a
la raíz del repo.

**Tests**: la spec no pide TDD. Se ejecutan **tests dirigidos existentes** por checkpoint
(quickstart §1) y solo se añaden tests nuevos donde cambia lógica/typing (status map, prop
`EmptyState.icon`). Sin snapshots, sin pixel tests, sin full suite local, sin backend. Un test
existente solo se ajusta si dependía de una clase/DOM puramente visual **no** listada en
contracts/ui.md §9.5 — nunca para ocultar una regresión funcional.

**Formato**: `- [ ] T### [P?] [US?] Descripción con ruta`. `[P]` = archivos distintos y sin
dependencia de tareas incompletas. Etiquetas de historia según spec.md: US1 sistema coherente,
US2 shell, US3 Library, US4 Login, US5 Home, US6 Posts/Calendar, US7 Accounts/Settings/
onboarding, US8 responsive/polish.

---

## Checkpoint A — Foundation (tokens + Geist + status + estados globales)

**Objetivo**: toda la app cambia de paleta, fuente y tonos de estado sin tocar CSS de página.
**Bloquea**: todo lo demás.

- [X] T001 Añadir `@fontsource-variable/geist` con versión exacta (sin `^`; `5.3.0` o la estable vigente comprobada con `npm view`) a `frontend/package.json` y `frontend/package-lock.json` vía `npm install --save-exact` en `frontend/`
- [X] T002 Importar la fuente una sola vez (`import "@fontsource-variable/geist";`) antes de los CSS en `frontend/src/main.tsx`
- [X] T003 Sustituir los primitivos `--gray-* / --blue-* / --green-* / --yellow-* / --red-* / --sky-*` por `--stone-* / --night-* / --moss-* / --leaf-* / --amber-* / --clay-*` con los valores de contracts/ui.md §1.1 en `frontend/src/ui/tokens.css`
- [X] T004 Redefinir los semánticos existentes conservando nombres (`--color-bg`, `--color-surface`, `--color-surface-muted`, `--color-text`, `--color-text-secondary` = `#666962`, `--color-border`, `--color-border-control` = `#85877F`, `--color-overlay`, `--color-action` / `-hover` / `-subtle`, `--color-selected`, `--color-focus`, `--color-danger-action` / `-hover`) según contracts §1.2 en `frontend/src/ui/tokens.css`
- [X] T005 Añadir los semánticos nuevos `--color-surface-elevated`, `--color-sidebar`, `--color-sidebar-hover`, `--color-sidebar-active`, `--color-sidebar-border`, `--color-sidebar-text`, `--color-sidebar-text-secondary`, `--color-focus-on-dark`, `--color-focus-ring-soft`, `--color-media-overlay` (contracts §1.2) en `frontend/src/ui/tokens.css`
- [X] T006 Sustituir los status tones por `--status-{neutral,active,success,warning,danger}-{text,bg,solid}` y eliminar `--status-info-*` (contracts §1.3) en `frontend/src/ui/tokens.css`
- [X] T007 Actualizar tipografía: `--font-sans` con `"Geist Variable"` + system stack de fallback, escala `--text-xs…3xl` (12/13/15/16/20/24/30/34 en `rem`), `--text-button`, pesos `400/500/550/600`, `--leading-*`, `--tracking-title` (contracts §1.5) en `frontend/src/ui/tokens.css`
- [X] T008 Añadir radios (`--radius-sm/control/menu/surface/overlay/pill` = 6/10/12/16/20/999), sombras (`--shadow-raised/overlay/modal`), motion (`--motion-fast` 140ms, `--motion-medium` 200ms, `--motion-easing`, `--motion-easing-out`), `--page-gutter`, `--section-gap` y `--control-height` (44px; 40px bajo `@media (min-width:1024px) and (hover:hover) and (pointer:fine)`) manteniendo `--target-min: 44px` y la regla global de reduced motion (contracts §1.6) en `frontend/src/ui/tokens.css`
- [X] T009 Reasignar los usos de tamaños tras el cambio de escala en `frontend/src/**/*.css` (mismo commit que T007). Usos actuales: `--text-lg` **13**, `--text-md` **7**, `--text-sm` **14** (más `--text-xl` 3, `--text-2xl` 3, `--text-3xl` 1). **No sustituir por nombre**: cada consumidor se reasigna por su rol real (page/section heading, card title, navigation, input/control, body, metadata) al token de contracts §1.5. **Excepción controlada al orden A→F**: este remapeo toca CSS de páginas durante Foundation solo para conservar los tamaños por rol; no se rediseña ninguna página ni se cambia layout
- [X] T010 Reemplazar `--status-info-*` por `--status-active-*` en `frontend/src/components/delete-confirm-dialog.css` y `.ap-badge--info` por `.ap-badge--active` en `frontend/src/ui/ui.css`
- [X] T011 Cambiar el tipo `Tone` a `"neutral" | "active" | "success" | "warning" | "danger"` en `frontend/src/ui/Badge.tsx`
- [X] T012 Actualizar solo los `tone` del mapa (scheduled_automatic → neutral, publishing → active, needs_review → warning; resto según contracts §5), sin tocar labels ni iconos, en `frontend/src/ui/status.ts`
- [X] T013 [P] Alinear tonos fuera del mapa: attention → warning, scheduled → neutral (labels/iconos intactos) en `frontend/src/pages/library/usage-indicator.ts`
- [X] T014 [P] Añadir test dirigido del mapa: cada estado conserva label e icono actuales y su tono es el de contracts §5 (incl. `needs_review` = warning, `publishing` = active) en `frontend/src/ui/status.test.ts`
- [X] T015 Pasar la base a canvas en `frontend/src/index.css`: `:root`/`body` con `background: var(--color-bg)`, `color: var(--color-text)`, `font-family: var(--font-sans)`, `-webkit-font-smoothing: antialiased`; y explícitamente `html { font-size: 100%; }` (respeta el text-size del navegador) + `body { font-size: var(--text-base); }` (body final = 15px equivalente por token; nunca 16px por accidente)
- [X] T016 Estados de interacción globales: `:focus-visible` con `--color-focus`, `.ap-nav :focus-visible` con `--color-focus-on-dark`, utilidad `.ap-tabular` (`font-variant-numeric: tabular-nums`) en `frontend/src/ui/tokens.css` / `frontend/src/ui/ui.css` — *Nota A: `.ap-nav :focus-visible` con `--color-focus-on-dark` se aplaza a T049: con la nav aún clara daría 1.74:1 (< 3:1); el token ya existe*
- [X] T017 Ejecutar tests dirigidos (quickstart §1 A): `npx vitest run src/ui src/shell/shell.test.tsx` en `frontend/` (verde sin cambiar asserts funcionales)
- [X] T018 Revisión visual A en instancia segura (quickstart §2 A): canvas cálido, Geist cargada, ningún azul `#1D4ED8`, 0 peticiones externas en Network (el `woff2` sale del propio origen), Needs review en ámbar, Publishing active, Scheduled neutral
- [X] T019 Commit lógico "foundation" (solo cuando el usuario lo autorice): `feat(frontend): visual refresh foundation tokens, Geist and status tones`

**Checkpoint A listo**: app con la nueva paleta/fuente; CSS de página intacto.

---

## Checkpoint B — Shared UI (US1, P1)

**Objetivo**: primitives y patrones compartidos con el nuevo lenguaje; la mayor parte del
refresh se propaga desde aquí. **Test independiente**: recorrer cualquier pantalla y ver
botones, campos, badges, cards, diálogos y empty states renovados sin cambio de flujo.

### Controles y tamaños (D1)

- [ ] T020 [US1] Button: `min-height: var(--control-height)`, radio `--radius-control`, `--text-button`/550, primary moss, secondary surface + `--color-border-control`, ghost con texto `--color-text` y hover `surface-muted`, danger clay, `ap-delete-entry` secondary con texto danger, transiciones 140ms (fondo/borde/sombra), disabled/loading intactos, clases `ap-button--*` conservadas; IconButton cuadrado `var(--control-height)` y `.ap-link` a `--control-height`, en `frontend/src/ui/ui.css`
- [ ] T021 [US1] Revisar todos los usos de `--target-min` como **altura de control** y pasarlos a `--control-height` donde son controles (no targets táctiles puros) en `frontend/src/ui/ui.css`, `frontend/src/shell/shell.css`, `frontend/src/pages/library/library.css`, `frontend/src/pages/posts/posts.css`, `frontend/src/pages/publish/publish.css`, `frontend/src/pages/accounts/accounts.css`, `frontend/src/pages/settings/settings.css`, `frontend/src/pages/home/home.css`, `frontend/src/pages/project/project.css`, `frontend/src/components/platform/platform.css` (incluye los `line-height: var(--target-min)` del breadcrumb)
- [ ] T022 [US1] Recalcular el `scroll-padding-bottom` de `.ap-page-actions--sticky` (una y dos filas) con `--control-height` en vez de `--target-min` en `frontend/src/ui/ui.css` (en `sm` ambos valen 44px: sin cambio de comportamiento; verificación manual en T032, jsdom no evalúa CSS)

### Controles nativos y formularios

- [ ] T023 [US1] Crear `.ap-input` (input/select/textarea): altura `--control-height`, radio 10, borde control, fondo surface, placeholder secundario, foco `border-color: var(--color-action)` + halo `--color-focus-ring-soft`, sin inset, 16px en `sm`, select con flecha nativa; checkbox/radio 18px con `accent-color: var(--color-action)`; aplicar el mismo bloque a `.ap-field input/select/textarea` en `frontend/src/ui/ui.css`
- [ ] T024 [US1] Field: label 14/550 arriba, hint 13 secundario, error 13 danger, `[aria-invalid]` con borde danger, `.ap-field` max-width conservado en `frontend/src/ui/ui.css`
- [ ] T025 [US1] ChoiceGroup: opciones como tiles con el patrón de selección compartido (contracts §4) y `switch` segmented neutro (track `surface-muted`, seleccionado surface + `--shadow-raised` + 550, sin fondo accent) en `frontend/src/ui/ui.css`
- [ ] T026 [US1] Patrón de selección compartido (`outline 2px --color-action` + `outline-offset 2px` + fondo `--color-action-subtle`) como selectores agrupados reutilizables en `frontend/src/ui/ui.css`
- [ ] T027 [US1] Crear `.ap-actions` (flex wrap, gap `--space-2`) en `frontend/src/ui/ui.css` (sustituirá a `.actions` legacy en E)

### Superficies y estados

- [ ] T028 [P] [US1] Badge: pill, 12–13px/550, padding 2×8, clases `.ap-badge--{neutral,active,success,warning,danger}` con status tokens en `frontend/src/ui/ui.css`
- [ ] T029 [P] [US1] Card radio `--radius-surface` + borde decorativo sin sombra; ErrorState con fondo danger-bg, borde izquierdo 3px danger e icono; Skeleton estático `surface-muted` radio `--radius-sm` en `frontend/src/ui/ui.css`
- [ ] T030 [US1] EmptyState: prop opcional `icon?: IconName` (círculo 40px `surface-muted`, icono 20px `aria-hidden`), título 18/600, descripción meta, centrado en vista completa; contrato "exactamente una acción" intacto en `frontend/src/ui/EmptyState.tsx` y `frontend/src/ui/ui.css`
- [ ] T031 [P] [US1] Test dirigido de EmptyState: con `icon` el icono es `aria-hidden`, título/descripción/acción iguales; sin `icon` el render no cambia en `frontend/src/ui/empty-state.test.tsx`
- [ ] T032 [US1] PageActions sticky en `sm`: surface + borde superior sutil + safe-area; comprobar manualmente a 375px que el foco no queda tapado (una y dos filas) en `frontend/src/ui/ui.css`
- [ ] T033 [P] [US1] Añadir paths `folder`, `image`, `inbox`, `grid` (24 grid, stroke 2, outline, misma familia) en `frontend/src/ui/Icon.tsx`

### Dialog / Drawer / Sheet / DetailSurface

- [ ] T034 [US1] Modal: radio `--radius-overlay`, padding 24 (sm) / 28 (md+), header título 20/600 + close, descripción meta, footer separado 24px con acciones a la derecha (orden DOM; en `sm` a ancho completo en el mismo orden), overlay `--color-overlay`, `--shadow-modal`; clases `ap-modal--{dialog,drawer,sheet}` conservadas en `frontend/src/ui/ui.css`
- [ ] T035 [US1] Sheet en `sm` como **bottom sheet**: `inset: auto 0 0 0`, `max-height: calc(100dvh - 24px)`, radios superiores 20px, `overflow-y: auto` en el contenedor, padding inferior + `env(safe-area-inset-bottom)`, asa decorativa 36×4 `aria-hidden` vía pseudo-elemento; desde `md` sigue centrado; Drawer con radios izquierdos en `frontend/src/ui/ui.css`
- [ ] T036 [US1] Motion de modales con `@keyframes` sobre `[data-state="open"|"closed"]` de Radix (overlay fade; dialog fade+translateY 8px; sheet translateY 16px; drawer translateX 16px; 200/160ms) — sin JS, anulado por la regla global de reduced motion, en `frontend/src/ui/ui.css`
- [ ] T037 [US1] DetailSurface hereda: panel con borde izquierdo sutil, header 20/600, footer separado; sin tocar `DetailSurface.tsx` en `frontend/src/ui/ui.css`
- [ ] T038 [US1] DeleteConfirmDialog: solo el botón de confirmación en `danger` sólido, resumen/blocker/changed con tokens nuevos; clases `ap-delete-dialog*` conservadas en `frontend/src/components/delete-confirm-dialog.css`

### Menús y header

- [ ] T039 [US1] Crear `.ap-menu > .ap-disclosure__region` (surface elevated, `--radius-menu`, `--shadow-overlay`, padding 4, items a `--control-height` alineados a la izquierda, hover muted, `.ap-delete-entry` con texto danger, entrada fade+translateY(-4px) 160ms) incluyendo `.ap-new-post__menu` en la misma lista de selectores; el botón de Disclosure hereda el ghost de T020 (sin cambios de API/comportamiento de `Disclosure`), en `frontend/src/ui/ui.css`
- [ ] T040 [US1] Crear `.ap-page-header` (título + contexto + acciones, wrap en `sm`, margen inferior `--space-6`) y `.ap-page-title`/`.ap-section-title` con la escala nueva (2xl→3xl, lg→xl, `--tracking-title`) en `frontend/src/ui/ui.css`
- [ ] T041 [US1] Flash: ink, `--radius-menu`, `--shadow-overlay`, fade-in; posición intacta en `frontend/src/shell/shell.css`

### Verificación B

- [ ] T042 [US1] Tests dirigidos: `npx vitest run src/ui src/components/DeleteConfirmDialog.test.tsx src/pages/library/bulk-delete.test.tsx src/pages/project/project-delete.test.tsx src/onboarding.test.tsx` en `frontend/`
- [ ] T043 [US1] **HIGH — sesión manual única del checkpoint B** (instancia segura, quickstart §2 B). (a) Overlays largos a 375px y texto al 200 %: AddAccountSheet (con connection panel abierto), ActionDialog, CheckResultDialog, FolderPicker (árbol largo), ChangePasswordDialog, DeleteConfirmDialog (Sheet en móvil) y PresetsDialog, EditContentDialog, MediaContentEditor (siguen siendo Dialog en móvil): scroll interno correcto, header/título y acciones alcanzables, safe-area respetada, foco visible, Tab/teclado nunca deja contenido fuera de vista ni atrapado, Escape y close funcionan, sin overflow horizontal, **modalidad actual intacta** (no se cambia Sheet↔Dialog). (b) Alturas 40/44px medidas en DevTools (1280 con ratón, 375 táctil). (c) Menús unificados (More, Media actions, New post, acciones de proyecto). (d) Un Delete con una sola confirmación. Corregir con `max-height`/overflow/sticky header-footer en `frontend/src/ui/ui.css`; no volver a fullscreen salvo necesidad demostrada (registrar el motivo en research.md)
- [ ] T044 [US1] Commit lógico "shared UI" (cuando el usuario lo autorice)

---

## Checkpoint C — Shell (US2, P1)

**Objetivo**: navegación con identidad. **Test independiente**: navegar Home → Library → Posts
→ Accounts → Settings en lg/md/sm con mismos destinos, orden y comportamiento.

- [ ] T045 [US2] `lg`: `.ap-nav` sidebar `--color-sidebar` en columna flex de altura completa, lista principal con gap 2px, `.ap-nav__settings` al pie con `margin-top: auto` + separador `--color-sidebar-border` (orden DOM intacto) en `frontend/src/shell/shell.css`
- [ ] T046 [US2] Items: sin caja, texto `--color-sidebar-text-secondary`, hover `--color-sidebar-hover`, activo `--color-sidebar-active` + `--color-sidebar-text` + 550 (se retira el indicador `::before` en lg/md), disabled legible; `aria-current` intacto en `frontend/src/shell/shell.css`
- [ ] T047 [US2] Wordmark: monograma decorativo (`aria-hidden`, SVG/forma inline) + "AutoPublisher" 15/600 tracking −0.01em dentro de `.ap-nav__brand` (mismo texto) en `frontend/src/shell/PrimaryNav.tsx` y `frontend/src/shell/shell.css`
- [ ] T048 [US2] Project selector en la sidebar: `select` sobre `--color-sidebar-hover`, texto claro, borde `--color-sidebar-border`, label secundario claro; en TopBar mantiene estilo claro (`.ap-input`) en `frontend/src/shell/shell.css`
- [ ] T049 [US2] Foco sobre oscuro: `.ap-nav :focus-visible { outline-color: var(--color-focus-on-dark) }` (incluye selector) en `frontend/src/shell/shell.css`
- [ ] T050 [US2] `md`: rail oscuro con el mismo tratamiento (labels cortas 12px), TopBar canvas con borde inferior sutil en `frontend/src/shell/shell.css`
- [ ] T051 [US2] `sm`: bottom bar clara (`--color-surface`, borde superior sutil), activo texto ink + 550 + pill accent-soft tras el icono, labels envolventes como hoy; "More" con `.ap-menu` y su estado current intacto en `frontend/src/shell/shell.css` y `frontend/src/shell/TopBar.tsx` (solo clase `ap-menu` en el `className` del Disclosure)
- [ ] T052 [US2] Main y gutters: `.ap-shell` en canvas, `.ap-shell__main` con `--page-gutter`; skip link con el nuevo estilo; task mode intacto en `frontend/src/shell/shell.css`
- [ ] T053 [US2] Tests dirigidos: `npx vitest run src/shell src/routes.test.tsx src/auth.test.tsx` en `frontend/` (navegación, More, task mode, project selector, `aria-current`, Skip to content)
- [ ] T054 [US2] **STOP — validación manual del shell** en instancia segura a 375 / 768 / 1024 / ≥1280: sidebar, rail, TopBar, bottom nav, branding, activo/foco (Tab por toda la nav), project selector usable, task mode (Publish media a 375). Objetivo: aprobar el **shell visual**, no las páginas. Regla: corregir HIGH visual/funcional y MEDIUM claros; registrar los LOW para el checkpoint F; continuar (sin iterar hasta la perfección estética). **El usuario aprueba antes de empezar D.**
- [ ] T055 [US2] Commit lógico "shell" (cuando el usuario lo autorice)

---

## Checkpoint D — Core screens (US5 Home, US3 Library, US4 Login)

### Home (US5, P2)

**Test independiente**: Home con/sin attention, con/sin posts programados, filtrada y sin
proyectos; misma información, mismas acciones.

- [ ] T056 [US5] Header de Home con `.ap-page-header` (título + filtro "Showing … / Show all projects" igual) en `frontend/src/pages/HomePage.tsx` (solo clases) y `frontend/src/pages/home/home.css`
- [ ] T057 [US5] Attention como superficie única con filas separadas (icono de tono, título 15/550, meta, acción a la derecha; urgente con barra izquierda danger 3px + icono) y banner de automatización pausada compacto en warning en `frontend/src/pages/home/home.css`
- [ ] T058 [US5] "Everything looks good" como línea tranquila (icono check en círculo accent-soft + texto), sin caja grande, en `frontend/src/pages/home/home.css`
- [ ] T059 [US5] Up next como timeline: columna de hora `.ap-tabular` 13px, contenido, badge; filas sin caja con separadores en `frontend/src/pages/home/home.css`
- [ ] T060 [US5] Projects como tiles (2–3 columnas desde `md`, lista en `sm`): nombre 16/600, "Next: …" meta, badges al pie; sin cifras grandes; botón "New project" igual en `frontend/src/pages/home/home.css`
- [ ] T061 [US5] Layout `lg`+ de dos columnas por CSS grid (Attention + Up next | Projects) sin reordenar el DOM; una columna `<lg` en `frontend/src/pages/home/home.css`
- [ ] T062 [US5] Tests dirigidos: `npx vitest run src/pages/home.test.tsx` en `frontend/`

### Library (US3, P1 — prioridad visual alta)

**Test independiente**: Library con media y folders; hover/foco; Select mode, Move y Bulk
Delete (cancelando); todo igual que hoy.

- [ ] T063 [US3] Header de Library con `.ap-page-header` (título, acciones, `.ap-menu` en `.ap-library__more`) y toolbar/filtros/búsqueda con `.ap-input`; `.ap-library` conservada en `frontend/src/pages/library/LibraryToolbar.tsx`, `frontend/src/pages/library/LibraryRoot.tsx`, `frontend/src/pages/library/MediaView.tsx` (solo clases) y `frontend/src/pages/library/library.css`
- [ ] T064 [US3] Root entries: Unsorted / All media / folders como tarjetas horizontales bajas en `surface-muted` con icono `inbox` / `grid` / `folder` (20px), nombre 15/550, hover surface; `--virtual` diferenciado; mismos enlaces en `frontend/src/pages/library/LibraryRoot.tsx` (iconos) y `frontend/src/pages/library/library.css`
- [ ] T065 [US3] Folder rows/subfolders con la misma identidad (sin carpeta amarilla) y breadcrumb con el nuevo estilo (`.ap-menu` en `.ap-breadcrumb__more`, `aria-current` intacto) en `frontend/src/pages/library/Breadcrumb.tsx` (solo clase) y `frontend/src/pages/library/library.css`
- [ ] T066 [US3] MediaCard: preview a sangre (sin padding, radio superior = radio de card), `aspect-ratio: 4 / 5` como dirección inicial (ajustable a 1:1 si genera problemas visuales; registrar en research.md R14), `object-fit: cover`, cuerpo compacto (title 1 línea ellipsis 14/550, folder meta 12–13, badge de uso pequeño), borde decorativo en reposo, hover/focus `--shadow-raised` + `translateY(-1px)` sin zoom; `ap-media-card__title` conservada en `frontend/src/pages/library/library.css`
- [ ] T067 [US3] Overlays sobre thumbnail: duración con `--color-media-overlay` + `--radius-sm` + `.ap-tabular`; menú de acciones `IconButton` circular siempre visible (surface + sombra overlay, opacidad 0.85→1 en hover/focus) con `.ap-menu` en `frontend/src/pages/library/MediaCard.tsx` (solo clase) y `frontend/src/pages/library/library.css`
- [ ] T068 [US3] Grid: `minmax(clamp(150px, 20vw, 220px), 1fr)`, gap `--space-3` (sm) / `--space-4` (md+), 2 columnas a 375px; misma arquitectura `auto-fill`; `ap-media-grid` conservada en `frontend/src/pages/library/library.css`
- [ ] T069 [US3] Selección: `--selected` y `--checked` con el patrón compartido (outline accent + cuerpo accent-soft), checkbox 22px sobre chip blanco arriba-izquierda siempre visible en Select mode en `frontend/src/pages/library/library.css`
- [ ] T070 [US3] SelectionBar oscura (fondo `--color-text`, texto claro, botones ghost-on-dark, Delete `danger`, conteo `.ap-tabular`), misma posición sticky; `ap-selection-bar__count` conservada en `frontend/src/pages/library/library.css`
- [ ] T071 [P] [US3] Import: dropzone con borde discontinuo `--color-border-control` y fondo `--color-action-subtle` al arrastrar; ImportPanel como superficie elevada (`--radius-surface`, `--shadow-overlay`) en `frontend/src/pages/library/library.css`
- [ ] T072 [US3] Media detail: preview sobre `surface-muted` con `object-fit: contain` y `max-height: 60vh` (imagen completa, no deformada); FileDetails como lista definicional compacta; MediaContentEditor con `Field`/`.ap-input`; MediaUsage como filas; secciones con títulos 15/600; inheritance warning con tokens warning en `frontend/src/pages/library/library.css`
- [ ] T073 [US3] Folder picker (Move) y FolderNameDialog con el patrón de selección y `.ap-input` en `frontend/src/pages/library/library.css`
- [ ] T074 [US3] MediaPreview `.preview` / `.preview.placeholder` a tokens (placeholder `surface-muted` + texto meta; sin literales) sin renombrar clases en `frontend/src/index.css` (bloque `.preview`)
- [ ] T075 [US3] Eliminar el literal `rgb(31 35 40 / 0.8)` y cualquier valor suelto restante de `frontend/src/pages/library/library.css`
- [ ] T076 [US3] Tests dirigidos: `npx vitest run src/pages/library src/components/MediaPreview.test.tsx` en `frontend/` (Select, Move, Bulk Delete, folders, breadcrumb, import, detail)

### Login (US4, P2)

**Test independiente**: `/login` con contraseña incorrecta y correcta; mismos errores y
redirección.

- [ ] T077 [P] [US4] `.ap-login` y `.ap-auth-loading` con marco `--color-sidebar` a pantalla completa; panel `.ap-login__card` surface ~400px, `--radius-overlay`, `--shadow-modal`, padding 40px (md+) / 24px (sm) en `frontend/src/pages/login/login.css`
- [ ] T078 [US4] Wordmark: h1 "AutoPublisher" dentro del panel con tratamiento de wordmark 24/600 + monograma decorativo `aria-hidden` (sin copy nuevo, `aria-labelledby` intacto) en `frontend/src/pages/login/LoginPage.tsx` y `frontend/src/pages/login/login.css`
- [ ] T079 [US4] Password (16px, `.ap-input`), `Sign in` primary a ancho completo (≥ 44px en sm), error con icono alert + texto danger (`role="alert"` y mensajes intactos), nota de reset meta al pie; foco sobre el marco con `--color-focus-on-dark` si aplica en `frontend/src/pages/login/login.css`
- [ ] T080 [US4] Tests dirigidos: `npx vitest run src/pages/login src/auth.test.tsx` en `frontend/` (sin repetir `auth.test` si no cambió nada relevante desde T053)

### STOP D

- [ ] T081 **STOP — validación manual del usuario** (dirección *Creative Editorial Workspace*) en instancia segura. **1) Library primero** a 375 / 768 / 1024 / 1280: edge cases (sin thumbnail / archivo no disponible, 9:16, panorámica, nombre muy largo, imagen muy clara y muy oscura con duración y menú legibles, asset claramente dominante ~70 % como target, no umbral), Unsorted, All media, folder, Media detail, Select mode, Move y Bulk Delete. **2) Home** (375 + 1280). **3) Login** (375 + 1280). Regla: corregir HIGH y MEDIUM claros; registrar los LOW para F; continuar. **El usuario aprueba antes de empezar E.**
- [ ] T082 Commit lógico "core screens" (cuando el usuario lo autorice)

---

## Checkpoint E — Secondary screens (US6, US7) + Publish heredado + legacy

### Posts / Calendar (US6, P2)

**Test independiente**: List y Calendar, Post detail, una ActionDialog cancelada, History/
Activity; mismo comportamiento.

- [ ] T083 [P] [US6] Posts header con `.ap-page-header`; búsqueda/cuenta con `.ap-input`; switch `List | Calendar` hereda el segmented neutro; `New post` con `.ap-menu` (posición propia) en `frontend/src/pages/PostsPage.tsx` / `frontend/src/pages/posts/NewPostMenu.tsx` (solo clases) y `frontend/src/pages/posts/posts.css`
- [ ] T084 [US6] PostRow y secciones: filas en superficie única con separadores, columna when `.ap-tabular` 13px, título 15/550, meta de destino, badge a la derecha, thumbnail 40px `--radius-sm`; títulos de sección/día 13px/600 secundarios con espacio superior `--space-6`; DailyList/HistoryList igual en `frontend/src/pages/posts/posts.css`
- [ ] T085 [US6] Post detail: secciones 15/600, StatusActionPanel en `surface-muted` (mismo orden de acciones), PostContent como lista definicional, ActionDialog/CheckResultDialog heredan modal; Activity con filas tranquilas; `.ap-technical` consolidado en una única definición en `frontend/src/ui/ui.css` (preservando como modificador, p. ej. `.ap-technical--controls`, la variante de Accounts que estila buttons/textarea si sigue haciendo falta) y eliminado de `frontend/src/pages/posts/posts.css` y `frontend/src/pages/accounts/accounts.css`
- [ ] T086 [US6] Calendar: layout y breakpoints intactos (`ap-calendar-week` / `ap-calendar-agenda`), líneas `--color-border`, cabeceras 13/600 secundarias, hoy = chip accent-soft + texto "Today" existente, eventos surface con borde izquierdo de tono 3px, hora `.ap-tabular`, seleccionado con outline accent; drawer heredado en `frontend/src/pages/posts/posts.css`
- [ ] T087 [US6] Tests dirigidos: `npx vitest run src/pages/posts` en `frontend/`

### Accounts / connections (US7, P3)

- [ ] T088 [US7] Accounts header con `.ap-page-header`; AccountCard como tile/fila (avatar, nombre 15/550, plataforma meta, StatusBadge), selección compartida; AccountDetail con banda de estado (`surface-muted`, icono + label + siguiente paso existente); AddAccountSheet con platform options como tiles seleccionables en `frontend/src/pages/AccountsPage.tsx` (solo clases) y `frontend/src/pages/accounts/accounts.css`
- [ ] T089 [US7] Crear `frontend/src/components/connection.css` con `.ap-connection`, `--connected`, `--reconnect`, `__channel`, `__avatar-placeholder`, `__paste`, `__channel-change` usando solo tokens (borde izquierdo de tono + fondo suave; texto/estado sin cambios) e importarlo desde los panels
- [ ] T090 [US7] Migrar nombres de clase legacy → `ap-connection*`, `.badge` → `ap-badge ap-badge--neutral`, `.muted` → `ap-meta`, `.notice` → `ap-notice`, `.actions` → `ap-actions` (sin tocar lógica, polling, estados ni botones) en `frontend/src/components/YouTubeConnectionPanel.tsx`, `frontend/src/components/InstagramConnectionPanel.tsx`, `frontend/src/components/ThreadsConnectionPanel.tsx`, `frontend/src/components/TikTokConnectionPanel.tsx`, `frontend/src/components/TelegramConnectionPanel.tsx`, `frontend/src/components/TikTokInboxDelivery.tsx`, `frontend/src/components/HostOnlyNotice.tsx`, `frontend/src/components/ProjectForm.tsx`, `frontend/src/pages/ProjectLayout.tsx`
- [ ] T091 [P] [US7] Platform cards/forms (`.ap-platform-card`, `.ap-check`, `.ap-caption`, TikTok declaration) con tokens nuevos en `frontend/src/components/platform/platform.css`; **mover `.ap-notice`** (consumido por platform/connections, Posts y Publish) a una única definición compartida en `frontend/src/ui/ui.css` y borrarlo de `platform.css` (sin componente React nuevo)
- [ ] T092 [US7] Botones/inputs nativos dentro de `.ap-technical__body` pasan a `.ap-input`/estilo de Button sin cambiar DOM ni comportamiento en `frontend/src/pages/accounts/accounts.css`
- [ ] T093 [US7] Tests dirigidos: `npx vitest run src/pages/accounts.test.tsx src/components/YouTubeConnectionPanel.test.tsx src/components/InstagramConnectionPanel.test.tsx src/components/ThreadsConnectionPanel.test.tsx src/components/TikTokConnectionPanel.test.tsx src/components/TelegramConnectionPanel.test.tsx src/components/TikTokInboxDelivery.test.tsx src/components/platform` en `frontend/`
- [ ] T094 [US7] Revisión manual de los **5 connection panels** (YouTube, Instagram, Threads, TikTok, Telegram) en instancia segura, en cada estado reproducible sin OAuth real (not connected / setup / connected / reconnect si hay fixture), a 375 y 1280: legibles, sin estilos legacy, mismos botones y flujos

### Settings (US7)

- [ ] T095 [US7] Secciones `.ap-settings__section` de dos columnas desde `lg` (`minmax(12rem,18rem) minmax(0,1fr)`: título 16/600 + descripción **existente** | contenido en una única superficie), una columna `<lg`, separadores sutiles; platform rows con separadores dentro de la superficie; installation/sign-in/automation con tokens; **sin anchors, índice ni navegación secundaria**, sin card por input; eliminar `transition: none` suelto si ya no aplica en `frontend/src/pages/settings/settings.css`
- [ ] T096 [US7] Tests dirigidos: `npx vitest run src/pages/settings.test.tsx` en `frontend/`

### Project chrome / onboarding (US7)

- [ ] T097 [P] [US7] ProjectHeader (nombre como eyebrow 13/600 secundario, acciones con `.ap-menu`), ProjectStatusStrip (pills neutras, warning con icono), OnboardingChecklist (superficie única, pasos numerados en círculo, actual accent, hechos con check y texto secundario); mismos links/acciones/orden en `frontend/src/pages/project/ProjectHeader.tsx` (solo clase) y `frontend/src/pages/project/project.css`
- [ ] T098 [US7] Tests dirigidos: `npx vitest run src/onboarding.test.tsx src/pages/project` en `frontend/` (no repetir si no cambió nada relevante desde T042)

### Publish heredado

- [ ] T099 [P] Publish: solo herencia y limpieza (literales → tokens, inputs → `.ap-input`, selección compartida en destinations/presets); sin rediseñar compose, review, destinations, presets, customize ni scheduling en `frontend/src/pages/publish/publish.css`
- [ ] T100 Tests dirigidos: `npx vitest run src/pages/publish` en `frontend/`

### Errores

- [ ] T101 [P] NotFound / ProjectNotFound / RouteError con `.ap-page-header`/EmptyState del sistema (mismo copy y salidas) en `frontend/src/shell/NotFound.tsx` y `frontend/src/shell/RouteError.tsx` (solo clases/icono)

### Legacy CSS migration (HIGH — reglas globales)

- [ ] T102 Inventario de los **25 consumidores reales** de las reglas globales `form`, `label` y/o `fieldset` de `frontend/src/index.css` (confirmar con grep de `<form|<label|<fieldset` en `frontend/src/**/*.tsx`) y anotar cuáles dependen visualmente de `display:grid / gap / max-width:28rem / margin` o del borde de `fieldset`. `components/`: `InstagramConnectionPanel`, `TelegramConnectionPanel`, `ThreadsConnectionPanel`, `ProjectForm`, `platform/InstagramDetails`, `platform/TikTokDeclaration`, `platform/TikTokDetails`, `platform/YouTubeDetails`. `pages/`: `accounts/AccountDetail`, `accounts/AddAccountSheet`, `library/FolderNameDialog`, `library/FolderPicker`, `library/MediaCard`, `library/MediaContentEditor`, `login/LoginPage`, `posts/CheckResultDialog`, `posts/PostContent`, `publish/compose/CommonContent`, `publish/compose/DestinationList`, `publish/compose/PresetsDialog`, `publish/review/EditContentDialog`, `settings/ChangePasswordDialog`. `shell/` y `ui/`: `shell/ProjectSelector`, `ui/ChoiceGroup`, `ui/Field`. Regla: **todos** los consumidores dependientes reciben styling explícito (tokens/patrones compartidos) en T103 antes de retirar los globales en T104
- [ ] T103 Dar clase/patrón explícito a cada consumidor dependiente (`.ap-form` en `ui.css` = grid + gap; `max-width` solo donde hoy se ve; `fieldset` con borde solo donde se usa como grupo visible) en los archivos identificados por T102 y `frontend/src/ui/ui.css`
- [ ] T104 Retirar de `frontend/src/index.css` las reglas globales `form`, `label`, `fieldset` y las clases legacy ya reemplazadas (`.badge`, `.muted`, `.actions`, `.notice`, `.youtube-/instagram-/threads-connection*`, `.channel*`, `.avatar-placeholder`, `.*-paste`, `.connection-*`, `.channel-change*`) y la no usada `.account`; mantener `.error` como alias recoloreado con tokens (consumido hoy por **20 archivos**, con `role="alert"`)
- [ ] T105 Revisión manual específica (Vitest no la detecta) a 375 y 1280 de cada consumidor de T102: Create project, Add account + los 5 panels, Account detail, Move, New folder, Media content editor, Login, Post content, Publish compose (common content, destinations, presets), **Publish Customize / Review con detalles por plataforma**, **CheckResultDialog**, **EditContentDialog**, Change password y **Project selector (sidebar y TopBar)**; sin cambios de layout no intencionados
- [ ] T106 Tests dirigidos de los archivos tocados en T103 que no se hayan ejecutado ya tras su último cambio (p. ej. `npx vitest run src/pages/library/folders.test.tsx src/pages/library/move.test.tsx src/pages/publish/compose.test.tsx src/pages/settings.test.tsx` según corresponda) en `frontend/`
- [ ] T107 Commit lógico "secondary screens + legacy migration" (cuando el usuario lo autorice; preferible dividir en "secondary screens" y "legacy CSS migration")

---

## Checkpoint F — Responsive / polish / accesibilidad / documentación / validación final (US8)

- [ ] T108 [US8] Búsqueda de literales (SC-003, contracts §1.6): colores, radios, sombras, duraciones, tamaños de fuente y espaciados fuera de `frontend/src/ui/tokens.css` en `frontend/src/**/*.css`; corregir los que no sean estructurales legítimos
- [ ] T109 [US8] **Sesión manual final única con checklist** en instancia segura. Pantallas: Login, Shell, Home, Library, Posts, Calendar, Settings, Accounts. Anchos: 375 / 768 / 1024 / ≥1280. En la misma pasada: texto al 200 % (nav, TopBar, badges, bottom nav, filas y cards envuelven sin ocultar), reduced motion emulado (dialogs, sheets, drawer, menús y hover de cards sin desplazamiento), foco de teclado (recorrido completo de shell + Library + un Dialog), safe-area, labels/nombres largos, sticky PageActions, bottom nav, overlays largos (repetir solo si cambió CSS de modales desde T043), sin overflow horizontal; y accesibilidad acotada a 023: tabla de contraste (contracts §1.4) sobre los tokens finales, texto AA, foco ≥ 3:1 (claro y `focus-on-dark`), bordes de control ≥ 3:1, ningún estado solo por color, ninguna acción solo en hover, targets 40/44 (1280 con ratón, 375 táctil)
- [ ] T110 [US8] Rendimiento: comparar tamaño de `frontend/dist/assets/*.css` y `*.woff2` con `main` (CSS ≤ ~+10 %), confirmar 0 peticiones externas y ausencia de JS nuevo para efectos
- [ ] T111 [US8] Corregir los LOW anotados en T054/T081 que sigan siendo relevantes (sin abrir alcance nuevo) en los CSS afectados
- [ ] T112 Actualizar `docs/design-system.md` como fuente documentada de 023: dirección *Creative Editorial Workspace*, paleta final, Geist local, tipografía, controles y regla de tamaño (40/44, `--control-height` vs `--target-min`), status map final, sidebar oscura/rail/bottom bar, motion de overlays, tabla de contraste, patrones `.ap-menu`/`.ap-page-header`/`.ap-input`/`.ap-actions`/selección, principios de Library; eliminar reglas de 018 contradictorias (44px universal, motion solo spinner, paleta azul, "breadcrumbs rechazados", legacy `index.css`) y mantener las vigentes (colour never alone, una primary por vista, no hover-only, DetailSurface, PageActions, task mode)
- [ ] T113 Checks estáticos y build **una sola vez**: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build` en `frontend/` y `git diff --check` en la raíz; confirmar `git diff main --stat` sin cambios en `backend/`
- [ ] T114 Revisión final del usuario (SC-011) y comprobación de SC-001…SC-010 según quickstart §3
- [ ] T115 Commit lógico "polish + docs" (cuando el usuario lo autorice) y apertura del PR (la CI ejecuta las suites completas)

---

## Dependencies & Execution Order

```text
A (T001–T019) ─► B (T020–T044) ─► C (T045–T055) ─► STOP T054
                                             │
                                             ▼
                         D: Home (T056–T062) ∥ Library (T063–T076) ∥ Login (T077–T080)
                                             │
                                             ▼  STOP T081
                         E: Posts/Calendar ∥ Accounts/connections ∥ Settings ∥ Project chrome ∥ Publish ∥ Errores
                                             │  (T102–T106 legacy después de T089–T090 y T095–T099)
                                             ▼
                                         F (T108–T115)
```

- A bloquea todo (tokens, Tone, escala).
- B depende de A; C depende de B (`.ap-menu`, `.ap-input`, foco).
- T054 (STOP shell) bloquea D; T081 (STOP core) bloquea E.
- Dentro de D, Home, Library y Login son independientes entre sí.
- Dentro de E, Posts, Accounts/connections, Settings, project chrome, Publish y errores son
  independientes; la retirada de legacy (T102–T106) va **al final de E**, después de migrar
  los panels (T089–T090) y de que los demás consumidores tengan su estilo final.
- F depende de E.

## Parallel Opportunities (reales)

- A: T013 ∥ T014 (archivos distintos, tras T011–T012).
- B: T028 ∥ T029 ∥ T031 ∥ T033 (bloques/archivos distintos); el resto toca `ui.css` en
  secuencia.
- D: el bloque Home (T056–T061, secuencial en `home.css`) ∥ T071 Library import ∥ T077 Login;
  Home, Library y Login pueden avanzar en paralelo como bloques.
- E: bloque Posts (T083–T086, secuencial en `posts.css`) ∥ T091 (platform) ∥ T097 (project) ∥
  T099 (publish) ∥ T101 (errores).

## STOP / manual tasks

T018 (A), T043 (B, sesión única), **T054 STOP shell**, **T081 STOP core** (incluye edge cases de Library),
T094 (5 panels), T105 (legacy forms), T109 (sesión final única) y T110 (rendimiento) (F), T114 (revisión final).

## HIGH risks → tasks

| Riesgo HIGH (plan §15) | Tasks |
|---|---|
| CSS global `form/label/fieldset` | T102 inventario → T103 clases explícitas → T104 retirada → T105 revisión manual → T106 tests |
| Fragmentación de CSS | T003–T009 (tokens con nombres conservados), T023/T026/T027/T039/T040 (patrones compartidos), T075, T085 (`.ap-technical` único), T091 (`.ap-notice` único en `ui.css`), T108 (búsqueda de literales), commits por capa |
| Sheets/diálogos largos en móvil | T035 (bottom sheet con scroll interno y safe-area), T043 (verificación 375 + 200 % + teclado), T109 (repetición condicional) |

## Implementation Strategy

1. A + B dan el MVP visible (US1): la app entera ya se percibe nueva.
2. C entrega la identidad (US2) y se aprueba en STOP antes de tocar pantallas.
3. D entrega las pantallas prioritarias (US5, US3, US4) y se aprueba la dirección visual.
4. E extiende el sistema a secundarias y elimina legacy.
5. F valida, documenta y cierra con un único pase de checks estáticos.

## Requirements coverage

| Requisito | Tasks |
|---|---|
| FR-001…FR-006 (preservación) | tests dirigidos por checkpoint (T017, T042, T053, T062, T076, T080, T087, T093, T096, T098, T100, T106), clases-contrato conservadas, T113 (sin `backend/`) |
| VR-001…VR-007 (foundation) | T001–T016, T036 |
| VR-010…VR-019 (shared) | T020–T041 |
| VR-020…VR-023 (shell) | T045–T052 |
| VR-030 Home | T056–T061 |
| VR-031…VR-036 Library | T063–T076, T081 |
| VR-037 Posts | T083–T085 |
| VR-038 Publish | T099–T100 |
| VR-040 Calendar | T086 |
| VR-041 Settings | T095 |
| VR-042 Accounts/connections | T088–T094, T102–T105 |
| VR-043 project chrome | T097 |
| VR-044 errores | T101 |
| VR-050 Login | T077–T079 |
| VR-051 dialogs | T034–T038, T043 |
| RR-001…RR-004 | T035, T043, T109 |
| AR-001…AR-007 | T016, T049, T109 |
| DR-001 | T112 |
| SC-001…SC-011 | T018, T081, T108, T109, T110, T114 |
