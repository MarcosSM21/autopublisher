# Research — Feature 023 Visual Refresh

**Fecha**: 2026-10-25 · **Spec**: [spec.md](spec.md) · **Brief**: [visual-design-brief.md](visual-design-brief.md)

Formato: Decision / Rationale / Alternatives. Todas las incógnitas del Technical Context quedan
resueltas aquí; no hay NEEDS CLARIFICATION.

---

## R0 — Inventario real del frontend (base del plan)

Inspeccionado en `frontend/src` (rama `023-visual-refresh`, sobre `main` `0dba8a6`).

### CSS (3 964 líneas, 14 archivos)

| Archivo | Líneas | Capa | Observaciones |
|---|---|---|---|
| `ui/tokens.css` | 147 | Foundation | Primitivos gray/blue/green/yellow/red/sky + semánticos; `--target-min`, motion, focus global, reduced motion global |
| `index.css` | 173 | **Legacy** + base | `:root` (font, color, `background: surface`), `body`; **reglas de elemento globales** `form`, `label`, `fieldset`; clases `.badge .error .actions .account .muted .preview .preview.placeholder .youtube-/instagram-/threads-connection .channel .avatar-placeholder .instagram-/threads-paste .connection-connected .connection-reconnect_required .channel-change .notice`; **16 colores literales** y 12 radios/tamaños literales |
| `ui/ui.css` | 618 | Shared | Todas las primitives `ap-`; solo tokens (2 literales estructurales) |
| `shell/shell.css` | 418 | Shell | bottom nav / rail / sidebar, TopBar, More, project selector, Flash, skip link |
| `pages/library/library.css` | 669 | Core | grid, MediaCard, entries, breadcrumb, select mode, folder picker, import, detail; 1 color literal (`rgb(31 35 40 / .8)` duración) |
| `pages/posts/posts.css` | 463 | Secondary | list/rows/sections, `New post` menu, detail, status panel, activity, `.ap-technical`, calendar |
| `pages/publish/publish.css` | 386 | Inherited | compose/review |
| `pages/accounts/accounts.css` | 321 | Secondary | cards, detail, add account, `.ap-technical` (duplicado con posts.css), estilos para botones nativos dentro de `.ap-technical__body` |
| `pages/home/home.css` | 246 | Core | banner, attention, ok, rows, filter |
| `pages/project/project.css` | 148 | Secondary | header, status strip, onboarding |
| `components/platform/platform.css` | 138 | Secondary | platform cards, `.ap-check`, `.ap-notice`, `.ap-caption` |
| `pages/settings/settings.css` | 138 | Secondary | secciones, automation, platform rows, installation, change password |
| `components/delete-confirm-dialog.css` | 53 | Shared | cuerpo/footers del DeleteConfirmDialog; usa `--status-info-*` |
| `pages/login/login.css` | 46 | Core | card centrada sobre `--color-bg` |

### Duplicación real detectada

- **Región de menú desplegable** declarada 6 veces con variaciones: `.ap-topbar__more`,
  `.ap-library__more`, `.ap-breadcrumb__more`, `.ap-media-card__actions`,
  `.ap-project-header__actions` (todas `... .ap-disclosure__region`) y `.ap-new-post__menu`.
- **`.ap-technical`** (disclosure de datos técnicos) en `accounts.css` y `posts.css`.
- **Item seleccionable** (borde + `:has(input:checked)`): `.ap-choice--selected`,
  `.ap-folder-picker__row:has(input:checked)`, `.ap-platform-option:has(input:checked)`,
  `.ap-media-card--checked`, `.ap-media-card--selected`.
- **Fila enlazable** (hover + título): `.ap-home-row`, `.ap-post-row`, `.ap-usage-row`,
  `.ap-strip__item`, `.ap-library-entry`.
- **Notice**: `.notice` (legacy) y `.ap-notice` (platform.css).
- **Controles nativos**: `.ap-field input/select/textarea`, `.ap-project-selector__select`,
  `.ap-library__search`, `.ap-posts__search`, `.ap-technical__body textarea/button`.

### Primitives y su estado

`Button` (4 variantes, `loading`, `as="link"`), `IconButton` (44×44), `Icon` (14 paths propios,
24 grid, stroke 2), `Badge` (`Tone = success|info|neutral|warning|danger`), `StatusBadge` + mapa
único `ui/status.ts`, `Card`, `EmptyState` (título, descripción, una acción, link secundario;
**sin icono**), `ErrorState`, `Skeleton`, `Dialog/Drawer/Sheet` (Radix 1.1.23; header con
`IconButton` Close, description, body, footer), `Disclosure` (botón ghost + region, Escape),
`DetailSurface` (panel/drawer/page), `Field`, `ChoiceGroup` (radios, `switch`), `PageActions`
(sticky en `sm`), `Flash` (shell). **No existen** primitives de Menu/Dropdown, Select,
Checkbox, Textarea ni Loader: son controles nativos, disclosures y `.ap-spinner`/`Skeleton`.

### Estados reales (confirmados en `types.ts` / `ui/status.ts`)

- Post (`PostDisplayState`): `draft`, `scheduled_automatic`, `scheduled_manual`,
  `scheduled_paused`, `publishing`, `published`, `failed`, `needs_review`, `needs_action`,
  `missed`, `cancelled`.
- Account (`AccountHealthState`): `ready`, `reconnect_needed`, `setup_required`,
  `not_connected`, `inactive`.
- Platform (`PlatformStatus`): `configured`, `partial`, `not_configured`, `coming_soon`.
- Además, tonos fuera del mapa único: `pages/library/usage-indicator.ts` (attention → `danger`,
  scheduled → `info`, drafts/not used → `neutral`, published → `success`), badges de
  `ProjectsList` (Inactive neutral, "need attention" warning, "All good" success),
  `ap-attention--urgent`, `ap-strip__item--warning`, `delete-confirm-dialog __changed` (info).

### Tests acoplados a clases (no a comportamiento)

`toHaveClass` / `querySelector('.ap-…')` sobre: `ap-button--primary|secondary|danger`,
`ap-delete-entry`, `ap-modal--dialog|sheet`, `ap-page-actions--sticky`,
`ap-calendar-week|agenda`, `ap-delete-dialog__name`, `.ap-delete-dialog p`,
`ap-media-grid > li`, `ap-selection-bar__count`, `ap-media-card__title`, `.ap-media-grid`,
`.ap-library`. Archivos: `project-delete`, `onboarding`, `publish-page`, `calendar-view`,
`DeleteConfirmDialog`, `page-actions`, `post-detail`, `bulk-delete`, `library`, `folders`.
Estas clases **expresan contrato** (variante, superficie, layout) y se conservan
(ver [contracts/ui.md §9](contracts/ui.md)). Vitest no procesa CSS (`css` desactivado por
defecto): los cambios de estilo no afectan a jsdom.

---

## R1 — Arquitectura de tokens

**Decision**: mantener dos capas en `ui/tokens.css`. Se **sustituyen** los primitivos
(`--gray-*`, `--blue-*`, `--sky-*`… → `--stone-*`, `--ink-*`, `--moss-*`, `--clay-*`,
`--amber-*`) y se **redefinen** los semánticos existentes manteniendo sus nombres siempre que
el rol no cambia (`--color-bg`, `--color-surface`, `--color-text`, `--color-action`,
`--color-focus`…), añadiendo los que faltan (`--color-sidebar-*`, `--color-focus-on-dark`,
`--color-surface-elevated`, `--status-active-*`). Valores finales en
[contracts/ui.md §1](contracts/ui.md).

**Rationale**: renombrar todos los semánticos obligaría a tocar los 14 CSS a la vez (big-bang).
Conservar los nombres permite que la **fase A cambie el aspecto de toda la app** sin tocar CSS
de página, y que las fases siguientes solo refinen composición.

**Alternatives**: renombrado completo a un esquema nuevo (`--canvas`, `--ink`…) — rechazado por
big-bang y diff ilegible; mantener primitivos azules y solo añadir — rechazado (VR-001, deja
restos del estilo anterior, SC-001).

## R2 — Ajustes de contraste (fijados)

**Decision**: secondary text `#666962`; control border `#85877F`; focus-on-dark `#A9C2B1`;
sidebar secondary text `#A3A69E`; sidebar active `#2A2B28`; sidebar hover `#222320`;
destructive `#B44747` (hover `#9A3A3A`); accent hover `#36523F`. Tabla completa de ratios en
[contracts/ui.md §1.4](contracts/ui.md).

**Rationale**: los valores del brief fallaban AA en tres pares (secondary text sobre canvas y
muted; accent como foco sobre sidebar). Los ajustes son mínimos y mantienen la dirección.

**Alternatives**: oscurecer el canvas en lugar del texto — rechazado (pierde la calidez
"warm off-white"); usar blanco como foco sobre la sidebar — válido (16:1) pero pierde la
relación con el accent.

## R3 — Geist servida localmente

**Decision**: dependencia npm **`@fontsource-variable/geist`** (OFL-1.1, versión estable
actual `5.3.0`, a fijar exacta sin `^`) importada una vez en `main.tsx`
(`import "@fontsource-variable/geist";`). Vite empaqueta los `woff2` con hash en `dist/assets`
y los sirve el propio backend junto al frontend: **0 peticiones externas**. Familia
`"Geist Variable"`, eje `wght` (se usan 400–600, incluido 550). El CSS de Fontsource ya
declara `font-display: swap` y `unicode-range` por subset (el navegador solo descarga `latin`
para texto inglés). Stack:
`--font-sans: "Geist Variable", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;`.
Sin Geist Mono (se mantiene `--font-mono` del sistema).

**Rationale**: cumple D2 (sin CDN, sin request runtime), sin binarios en el repo, licencia en
el paquete, una sola línea de integración, actualizable. Un único archivo variable por subset
(~30–40 KB latin) cubre todos los pesos.

**Alternatives**:
- Paquete oficial `geist` (Vercel) — orientado a `next/font`; habría que referenciar
  `node_modules/geist/dist/fonts/...` a mano en `@font-face`. Rechazado por fragilidad de rutas.
- Copiar `woff2` en `frontend/src/assets/fonts/` + `@font-face` propio — válido, pero añade
  binarios y licencia al repo; reservado como plan B si el paquete desaparece.
- Google Fonts / CDN — prohibido (D2, SC-008).
- `font-display: optional` — evita swap pero en primera carga puede quedarse en el fallback;
  rechazado: `swap` + fuente local cacheada hace el swap imperceptible tras la primera visita.
- Fallback metrics (`size-adjust`/`ascent-override` sobre Arial) — **no** en 023: Geist y
  system-ui tienen métricas cercanas, la app es local (descarga casi instantánea) y añade
  complejidad para un beneficio marginal. Revisable si el checkpoint visual muestra un salto
  molesto.

## R4 — Escala tipográfica

**Decision**: base `html` a 100 % (16px) para respetar el text-size del navegador; cuerpo de la
app 15px (`0.9375rem`); todos los tamaños en `rem`. Escala:
`--text-xs 0.75rem (12)`, `--text-sm 0.8125rem (13)`, `--text-base 0.9375rem (15)`,
`--text-md 1rem (16)`, `--text-lg 1.25rem (20)`, `--text-xl 1.5rem (24)`,
`--text-2xl 1.875rem (30)`, `--text-3xl 2.125rem (34)`. Pesos `400/500/550/600`.
Page title 30 (sm) → 34 (lg); section 20 (sm) → 24 (lg); card title 15–16/550; body 15;
meta 13 (12 solo para captions muy secundarias: duración, contadores); buttons 14/550.
Inputs a 16px en `sm` (evita el zoom de iOS al enfocar). `font-variant-numeric: tabular-nums`
en tiempos y contadores (Calendar, Up next, PostRow, selección).

**Rationale**: fija la jerarquía del brief; los títulos ganan presencia (24/30 → 30/34) y el
cuerpo baja a 15 como en productos SaaS densos. Los nombres de token cambian de significado
(`--text-md` deja de ser body) → se renombran en la fase A con búsqueda/reemplazo controlada.

**Alternatives**: cambiar el `font-size` raíz a 15px — rechazado (rompe la escala del usuario
y todos los `rem` estructurales).

## R5 — Altura de controles y touch targets (D1)

**Decision**: un único `Button` con dos tokens:
`--target-min: 44px` (target táctil, no cambia; lo usan scroll-padding y elementos táctiles) y
`--control-height` = `44px` por defecto, **`40px`** bajo
`@media (min-width: 1024px) and (hover: hover) and (pointer: fine)`. `Button`, `IconButton`,
inputs, select, `.ap-link`, items de menú y `ChoiceGroup` usan `min-height: var(--control-height)`.
`IconButton` = `var(--control-height)` cuadrado. Densidad compacta opcional
(`--control-height-sm: 32px` solo para pills de filtro dentro de toolbars en desktop fino) —
**no** se crea en 023 salvo que el checkpoint B lo pida.

**Rationale**: CSS puro, sin JS ni segundo sistema de botones; móviles, tablets y portátiles
táctiles (primary pointer coarse) mantienen 44px; WCAG 2.2 AA (24px) siempre cumplido.

**Alternatives**: `useMediaQuery` + prop de tamaño — rechazado (JS para algo visual, re-render);
`any-pointer: coarse` — rechazado: un portátil con pantalla táctil y ratón tendría 44px siempre;
se acepta 40px para él (puntero primario fino).

## R6 — Spacing, radios, sombras, motion

**Decision** (valores en contracts §1):
- Spacing: escala existente `--space-1…7` = 4/8/12/16/24/32/48 (sin cambios de nombre).
  Nuevos alias de layout: `--page-gutter` (16 sm / 24 md / 32 lg), `--section-gap` (32 sm / 40 lg).
- Radios: `--radius-control 10px`, `--radius-surface 16px` (cards), `--radius-overlay 20px`
  (dialogs/sheets), `--radius-inner 10px` (thumbnail dentro de card), `--radius-pill 999px`,
  `--radius-sm 6px` (badges no-pill, kbd, duración).
- Sombras: `--shadow-raised` (hover de card: `0 1px 2px rgb(25 26 24 / .06), 0 4px 12px rgb(25 26 24 / .06)`),
  `--shadow-overlay` (menús/flash: `0 8px 24px rgb(25 26 24 / .14)`),
  `--shadow-modal` (dialogs/sheets: `0 24px 64px rgb(25 26 24 / .22)`). Ninguna superficie en
  reposo lleva sombra.
- Motion: `--motion-fast 140ms` (hover/focus), `--motion-medium 200ms` (overlays),
  `--motion-easing cubic-bezier(.2,0,0,1)`, `--motion-easing-out cubic-bezier(0,0,.2,1)`;
  overlays: fade + translate 4–8px (dialog `translateY(8px)`, sheet `translateY(16px)`,
  drawer `translateX(16px)`, menú `translateY(-4px)`). Reduced motion: se mantiene la regla
  global existente (duraciones 0.01ms) → solo cambia la opacidad instantánea.
- Valores estructurales (`0`, `%`, `fr`, `minmax`, anchos de layout como
  `--shell-sidebar-width`, `aspect-ratio`, `max-width: 60ch`) **son legítimos** y no se
  tokenizan; la regla (SC-003) aplica a color, radio, sombra, duración, tamaño de fuente y
  espaciado de componentes.

**Rationale**: brief §4–§6, §18; la escala de spacing ya coincidía.

**Alternatives**: librería de animación — rechazada (CSS basta, rendimiento, constitución).

## R7 — Motion en Radix

**Decision**: animar con CSS sobre `data-state` de Radix:
`.ap-modal[data-state="open"] { animation: ap-modal-in var(--motion-medium) var(--motion-easing-out) }`
y `[data-state="closed"]` con `ap-modal-out`; igual para `.ap-overlay` (fade). Radix `Presence`
espera a `animationend` antes de desmontar, por lo que no hace falta JS. Menús (`Disclosure`)
usan `hidden`: solo animación de entrada (`@keyframes` en `.ap-menu:not([hidden])`), sin salida.

**Rationale**: cero JS nuevo; jsdom no carga CSS → tests sin cambios; reduced motion lo anula.

**Alternatives**: transiciones con `forceMount` — más código; rechazadas.

## R8 — Status system

**Decision**: `Tone = "neutral" | "active" | "success" | "warning" | "danger"` (desaparece
`info`). Mapa único `ui/status.ts` (labels e iconos intactos):

| Tone | Post | Account | Platform |
|---|---|---|---|
| neutral | Draft, Scheduled · automatic, Scheduled · manual, Cancelled | Not connected, Inactive | Coming soon |
| active | Publishing | — | — |
| success | Published | Ready | Configured |
| warning | Scheduled · paused, Needs action, **Needs review** | Finish setup | Partially configured |
| danger | Failed, Missed | Reconnect needed | Not configured |

Tonos fuera del mapa alineados con el mismo criterio: `usage-indicator.ts` "N need(s)
attention" `danger → warning` (es atención, coherente con el badge de Projects en Home que ya
es warning) y "Scheduled …" `info → neutral`; `delete-confirm-dialog __changed`
`info → active`. Badges: fondo tenue + texto AA; **neutral sin fondo saturado**; success,
warning y danger con fondo suave.

**Rationale**: D5 y brief §10: mayoría neutral, color reservado para atención/error/éxito.
`active` (accent-soft) señala lo que está ocurriendo ahora sin alarmar.

**Alternatives**: mantener `info` como alias de `neutral` — rechazado (nombre engañoso).

## R9 — Menús (Disclosure)

**Decision**: un modificador compartido **`.ap-menu`** en `ui.css` para la región de cualquier
disclosure que actúa como menú (superficie elevada, `--radius-surface` reducido a 12px vía
`--radius-menu`, `--shadow-overlay`, padding 4px, items a `--control-height`, alineación
izquierda, hover `surface-muted`, item destructivo con texto danger). Cada uso conserva solo
su **posicionamiento** (top/right/left). Se aplica a las 6 regiones duplicadas.
Implementación: los callers añaden `ap-menu` al `className` que ya pasan a `Disclosure` y el
CSS apunta a `.ap-menu > .ap-disclosure__region`; `.ap-new-post__menu` (implementación propia)
se añade a la misma lista de selectores. Sin cambio de API de `Disclosure`, de su
comportamiento ni de su DOM accesible.

**Rationale**: elimina duplicación real (VR-015) sin crear un primitive de menú nuevo (la
decisión de 018 "no generic menu primitive" se mantiene).

## R10 — Controles nativos

**Decision**: estilos base compartidos en `ui.css` por **clase utilitaria** `.ap-input`
(aplicada a `input`, `select`, `textarea`) y por el selector existente `.ap-field
input/select/textarea`; `.ap-project-selector__select`, `.ap-library__search`,
`.ap-posts__search` y `.ap-technical__body textarea` pasan a reutilizarla. `select` conserva
la flecha nativa (`appearance` por defecto): solo cambian borde, radio, altura, fuente y
fondo; sin chevron propio (evita data URIs con colores literales). Checkbox/radio nativos con `accent-color: var(--color-action)` y tamaño 18px
(se mantiene nativo: accesible y sin JS). Placeholder `--color-text-secondary`. Focus:
`border-color: var(--color-action)` + `box-shadow: 0 0 0 3px var(--color-focus-ring-soft)`
además del outline global.

**Rationale**: VR-011 sin primitives nuevos; reduce 5 duplicaciones.

**Alternatives**: checkbox custom dibujado — rechazado (complejidad, riesgo a11y).

## R11 — Legacy CSS (`index.css`) y connection panels (D6)

**Decision**: migración en la fase E, en dos pasos:
1. **Reglas de elemento globales** (`form`, `label`, `fieldset`): se sustituyen por clases con
   scope (`.ap-legacy-form` no; mejor: el panel raíz `.ap-connection` las aplica a sus
   descendientes) para que dejen de afectar a formularios nuevos. Antes de quitarlas se
   comprueba qué formularios dependen de `form { display:grid; gap; max-width:28rem }`
   (ProjectForm, connection panels, TikTok inbox) y se les da la clase equivalente.
2. **Clases legacy de los 5 panels** se reescriben como `ap-connection*` en
   `components/connection.css` (nuevo, junto a los panels) usando tokens y `StatusBadge`
   visual (sin cambiar el componente): `.youtube-/instagram-/threads-connection` →
   `.ap-connection`; `.connection-connected` / `.connection-reconnect_required` → modificadores
   `--connected` / `--reconnect` con borde izquierdo de tono + fondo suave (texto/estado no
   cambia); `.channel`, `.avatar-placeholder`, `.*-paste`, `.channel-change`, `.notice`
   (→ `.ap-notice` existente), `.badge` (→ `.ap-badge ap-badge--neutral`), `.muted`
   (→ `.ap-meta`), `.error` (→ se mantiene `.error` como alias de `.ap-field__error`/texto
   danger porque lo usan 17 archivos con `role="alert"`; solo cambia su color a token),
   `.actions` (→ `.ap-actions` en ui.css). `.account` **no se usa** → se borra.
   `.preview` / `.preview.placeholder` (MediaPreview, usado por Library, Posts, Publish)
   pasan a tokens en la fase D (no se renombran: los usa `MediaPreview.test`).
Tras la fase E, `index.css` queda solo con `:root`/`body` base (o desaparece y la base pasa a
`tokens.css`).

**Rationale**: D6; quitar reglas globales de elemento es el mayor riesgo de regresión visual
silenciosa, por eso va tarde, con inventario y checkpoint.

**Alternatives**: dejar legacy y solo recolorear — rechazado (D6 ya cerrada).

## R12 — Shell

**Decision**: misma estructura DOM (`PrimaryNav` único). Cambios CSS + mínimos de marcado:
- `lg`: `.ap-nav` fondo `--color-sidebar`, columna flex de altura completa; brand como
  wordmark (`.ap-nav__brand`: monograma cuadrado 28px con "AP" o glifo geométrico SVG inline
  + "AutoPublisher" 15px/600, tracking −0.01em); lista principal con gap 2px; **Settings
  empujado al pie** (`.ap-nav__settings { margin-top: auto }` con la lista como flex column y
  separador sutil) — mismo orden DOM/teclado; project selector en superficie oscura
  (`select` con fondo `--color-sidebar-hover`, texto claro, borde `#3A3B37`).
  Item: sin caja; hover `--color-sidebar-hover`; activo `--color-sidebar-active` + texto
  `--color-sidebar-text` + peso 550 + icono a color pleno (indicador ::before se elimina en lg:
  la pill + peso + `aria-current` bastan; no solo color). Foco: `outline-color:
  var(--color-focus-on-dark)` dentro de `.ap-nav`.
- `md`: rail oscuro (mismo tratamiento), labels cortas 12px; TopBar clara (canvas) con
  project selector claro.
- `sm`: bottom bar **clara** (`--color-surface`, borde superior sutil, sombra mínima opcional
  no), activo = icono+texto en `--color-text` + peso + pill accent-soft detrás del icono
  (no solo color); "More" igual que hoy, con `.ap-menu`.
- Main: fondo `--color-bg` (canvas) aplicado en `body`/`.ap-shell` (hoy `:root` pinta
  surface blanca); gutters `--page-gutter`.
- `ap-flash`: sin cambios de posición; superficie `--color-text` (ink) con radio 12px.

**Rationale**: VR-020…023, D8; no se tocan destinos, rutas, task mode ni selector.

## R13 — Header de página común

**Decision**: clase compartida `.ap-page-header` en `ui.css` (título + meta/contexto + zona de
acciones a la derecha, wrap en `sm`) que sustituye las variantes `ap-library__header`,
`ap-posts__header`, `ap-accounts__header` (mismos hijos, mismo DOM salvo la clase). Sin
componente nuevo: solo CSS y nombre de clase. `.ap-page-title` 30/34px, margen inferior a
cargo del header.

**Rationale**: VR-022 sin primitive nuevo; elimina 3 headers casi iguales.

## R14 — Library

**Decision** (detalle en contracts §5):
- Media card: **thumbnail a sangre** (sin padding alrededor del preview; radio superior =
  radio de card), `aspect-ratio: 4 / 5` en la grid estándar (más presencia vertical que 1:1
  sin volver la grid irregular) con `object-fit: cover`; cuerpo compacto (title 14/550 1
  línea con ellipsis + meta 12–13 secundaria; badge de uso inline al final, `size sm`).
  Área visual ≈ 75–80 % en cards estándar. En reposo: surface blanca + borde decorativo
  `--color-border` 1px (blanco sobre canvas solo da ~1.05:1, el borde sutil separa sin pesar)
  y sin sombra; hover/focus:
  `--shadow-raised` + `translateY(-1px)` (anulado en reduced motion), sin zoom.
- Duración: pill `--radius-sm` sobre fondo `rgb(25 26 24 / .72)` (≥ 6.9:1 sobre blanco puro).
- Menú de acciones: `IconButton` circular sobre el preview, **siempre visible** (como hoy:
  nada solo en hover), con fondo surface 90 % + sombra overlay leve; opacidad 0.85 → 1 al
  hover/focus (sigue visible y accesible).
- Selected (detalle abierto, `--selected`) y checked (Select mode): `outline: 2px solid
  var(--color-action)` + `outline-offset: 2px`, fondo cuerpo `--color-action-subtle`;
  checkbox 22px arriba-izquierda sobre chip blanco, siempre visible en Select mode.
- Root entries / folders: tarjeta horizontal baja en `surface-muted` (no surface blanca) con
  icono **folder** outline 20px de la misma familia (nuevo path en `Icon`), nombre 15/550 y
  conteo/meta si ya existe; "Unsorted" y "All media" (`--virtual`) con icono `inbox` /
  `grid` respectivamente (nuevos paths) — se distinguen de Media por forma (horizontal, sin
  thumbnail) y superficie.
- Grid: se conserva `auto-fill` y las reglas de columnas de 019; solo cambia `minmax` a
  `clamp(150px, 20vw, 220px)` y gap `--space-4` (≥ md) / `--space-3` (sm), manteniendo 2
  columnas a 375px.
- SelectionBar: superficie ink (`--color-text`) con texto claro y botones ghost-on-dark;
  conteo `tabular-nums`; Delete como `danger` (como hoy); misma posición sticky.
- Import/dropzone: borde discontinuo `--color-border-control`, fondo `--color-action-subtle`
  al arrastrar; ImportPanel como superficie elevada lateral/inferior igual que hoy.
- Media detail: preview sobre `surface-muted` con `object-fit: contain` y altura máx. 60vh;
  facts en lista definicional compacta; secciones separadas por espacio + títulos de sección
  15/600 (sentence case).
- Edge cases: placeholder `.preview.placeholder` en `surface-muted` con icono `image` y texto
  meta; 9:16 y panorama → `cover` en grid, `contain` en detalle; nombres → 1 línea ellipsis +
  nombre completo en `title` del detalle (ya está en el detalle); overlays siempre con fondo
  propio.

**Rationale**: VR-031…036, SC-004 (dominancia, ~70 % target).

**Alternatives**: masonry/aspect real — rechazado (cambia arquitectura de grid y rompe
lectura); thumbnail 1:1 — válido pero menos protagonismo; 4:5 elegido.

## R15 — Home

**Decision**: misma información y orden DOM (banner → attention/ok → Up next → Projects):
- Header: título "Home" 34px + filtro como línea meta (igual).
- **Attention** como bloque principal: lista de filas sobre una superficie blanca única con
  separadores (no una card por item), icono de tono a la izquierda, título 15/550, meta,
  acción a la derecha; urgente con barra izquierda danger 3px + icono (no solo color).
- **Everything looks good**: una línea tranquila (icono check en accent-soft + texto), sin
  caja grande.
- **Automation paused**: banner warning compacto encima.
- **Up next**: timeline vertical — columna de fecha/hora `tabular-nums` 13px a la izquierda,
  contenido, badge; filas sin caja, separadores sutiles.
- **Projects**: grid de "project tiles" (2–3 columnas desde md) en `surface` con nombre 16/600,
  meta "Next: …" y badges al pie; **no** son KPI cards (no hay números grandes; mismo
  contenido que las filas actuales). En `sm`, lista.
- Layout `lg`+: dos columnas `minmax(0,1.6fr) minmax(0,1fr)` — izquierda Attention + Up next,
  derecha Projects — **solo con CSS grid** (el DOM no cambia; el orden de lectura sigue
  siendo el del DOM). En `<lg`, una columna.

**Rationale**: VR-030, D3; jerarquía con tamaño, superficie y composición, sin datos nuevos.

**Alternatives**: KPI row con contadores — prohibido por spec.

## R16 — Login (D7)

**Decision**: `.ap-login` a pantalla completa con fondo `--color-sidebar` (dark framing);
panel claro central (`surface`, `--radius-overlay`, `--shadow-modal`, 400px máx., padding 40px
desktop / 24px móvil). Encima del panel, **fuera** de él, el wordmark AutoPublisher en claro
(solo el monograma decorativo, `aria-hidden`). El `h1` "AutoPublisher" **sigue dentro del
panel** (lo referencia `aria-labelledby` del form) con tratamiento de wordmark 24px/600; no se
añade ninguna línea de copy nueva. Campo Password 16px,
botón `Sign in` primary a ancho completo, error con icono alert + texto danger, nota de reset
en meta 13px al pie separada por espacio. En `sm`: el marco oscuro se reduce a una franja
superior (el panel ocupa casi toda la anchura con 16px de margen); sin animaciones.

**Rationale**: VR-050; personalidad por contraste y composición, sin copy nuevo.

## R17 — Posts y Calendar

**Decision**:
- Posts list: filas sobre superficie única con separadores; columna "when" `tabular-nums`
  13px; título 15/550 + meta (cuenta/destino) secundaria; badge a la derecha; thumbnail
  existente (`ap-post-detail__thumb`) 40px con `--radius-sm`; secciones con título 13px/600
  en color secundario + espacio superior 32px (agrupación por espacio, no por cajas). Switch
  `List | Calendar` como segmented control neutro (seleccionado = surface blanca con sombra
  mínima sobre track `surface-muted`, peso 550 — no fondo accent).
- Post detail: secciones con títulos 15/600, StatusActionPanel como superficie
  `surface-muted` con la frase de estado y sus acciones (mismo orden).
- `New post` menu → `.ap-menu`.
- Calendar: rejilla con líneas `--color-border` 1px, cabeceras de día 13px/600 secundaria;
  hoy: chip accent-soft con número en `--color-action` **+ texto "Today" existente**; eventos
  como bloques `surface` con borde izquierdo de tono 3px, hora `tabular-nums`, cuenta meta;
  seleccionado = outline accent. Breakpoints y modos (week `xl`, agenda debajo, drawer) intactos.

**Rationale**: VR-037, VR-040.

## R18 — Settings, Accounts, onboarding

**Decision**:
- Settings: cada `.ap-settings__section` = bloque de dos columnas desde `lg`
  (`minmax(12rem, 18rem) minmax(0, 1fr)`): izquierda título 16/600 + descripción meta
  (si la sección ya tiene texto descriptivo; **sin copy nuevo**), derecha contenido sobre una
  **única** superficie blanca por sección; separador horizontal sutil entre secciones;
  una columna en `<lg`. Sin anchors ni navegación (D4). Platform rows: filas con separadores
  dentro de la superficie.
- Accounts: AccountCard como fila/tile con avatar, nombre 15/550, plataforma meta y
  `StatusBadge`; estado de conexión en el detalle como banda de estado (`surface-muted`,
  icono + label + siguiente paso) arriba del detalle. AddAccountSheet: platform options como
  tiles con selección accent (patrón de selección compartido).
- Project chrome: ProjectHeader (nombre 13px/600 secundario tipo "eyebrow" + acciones
  `.ap-menu`), status strip como pills neutras (warning con icono), OnboardingChecklist como
  superficie única con pasos numerados (número en círculo, paso actual accent, hechos con
  check y texto secundario) — mismos pasos/enlaces.

**Rationale**: VR-041…043; D4/D6.

## R19 — Dialogs / Sheets

**Decision**: `--radius-overlay 20px`, padding 24px (sm) / 28px (md+), header título 20/600 +
close `IconButton`, descripción meta debajo, body, footer separado por 24px con acciones a la
derecha (primary al final); en `sm`, acciones a ancho completo apiladas en el orden del DOM
(orden visual = orden de teclado; sin `column-reverse`).
Overlay `rgb(25 26 24 / .48)`. **Sheet en `sm`** pasa de pantalla completa a **bottom sheet**:
`inset: auto 0 0 0`, `max-height: calc(100dvh - 24px)`, radios superiores 20px, padding
inferior + `env(safe-area-inset-bottom)`, asa visual decorativa 36×4px (no interactiva).
Drawer: radios izquierdos 20px. Delete: el único botón `danger` sólido es la confirmación;
el resto secondary/ghost.

**Rationale**: VR-014, VR-051, brief §14; semántica Radix intacta (solo CSS).

**Riesgo**: sheets largos (AddAccountSheet con connection panel) → scroll interno del sheet;
se verifica en checkpoint.

## R20 — EmptyState

**Decision**: prop opcional `icon?: IconName` (visual pequeño 20px en un círculo
`surface-muted` 40px); layout centrado en vistas vacías completas y alineado a la izquierda
en secciones (modificador `align`); título 18/600; descripción 1 línea meta. La línea
explicativa usa el `description` existente; donde hoy no hay descripción, **no** se inventa
(microcopy solo si ya existe o es claramente presentacional; ninguno planificado).

**Rationale**: VR-016 con un cambio retrocompatible mínimo.

## R21 — Validación visual y tests

**Decision**: revisión manual por checkpoint (A–F) sobre la **instancia segura** (copia con
`AUTOPUBLISHER_CONFIG` + keyring fail, memoria del proyecto) con datos de prueba, a 375 / 768
/ 1024 / ≥1280, más 200 % de texto y reduced motion en el checkpoint F. Tests: solo los
dirigidos de los componentes tocados; las clases-contrato se conservan; ningún assert
funcional se modifica. Detalle en [quickstart.md](quickstart.md).

**Alternatives**: Playwright screenshots — rechazado en 023 (infraestructura nueva, frágil).

## R22 — Rendimiento

**Decision**: CSS puro; 0 JS nuevo para efectos; 1 dependencia (fuente, ~30–40 KB por subset
descargado); sin librerías de iconos ni animación; el CSS total no debe crecer > ~10 % (la
eliminación de duplicados compensa los estados nuevos). Se compara `dist/assets/*.css` y
`*.woff2` antes/después en el checkpoint F.

**Resultado F (T110)**: CSS compilado 58,3 kB (9,4 kB gzip) en `main` → 83,3 kB (13,1 kB gzip)
con 023 (+43 % / +40 % gzip): la eliminación de legacy no compensó los patrones nuevos
(menús, selección, conexiones, motion, estados de Library/Home). **Accepted deviation** (aceptada por el usuario en T114) como
coste absoluto pequeño (+3,7 kB gzip) sin impacto medido; volver artificialmente al ~10 % añadiría complejidad sin beneficio práctico. FCP 24–32 ms en Home/Library,
CLS ≤ 0,03, 0 peticiones externas, Geist local (solo el subset latino, ~29 kB).
