# UI Contract — Feature 023 Visual Refresh

**Spec**: [../spec.md](../spec.md) · **Brief**: [../visual-design-brief.md](../visual-design-brief.md) ·
**Research**: [../research.md](../research.md)

Este contrato fija lo que la implementación debe respetar: tokens finales, reglas de
componentes, mapa de estados, shell y pantallas, y lo que **no cambia** (§9). Los valores son
finales para 023; cualquier ajuste posterior se registra aquí y en `docs/design-system.md`.

---

## 1. Tokens (`frontend/src/ui/tokens.css`)

Dos capas. Los componentes usan **solo** semánticos. Los nombres semánticos existentes se
conservan cuando el rol no cambia (R1).

### 1.1 Primitivos (sustituyen gray/blue/green/yellow/red/sky)

| Token | Valor | Uso semántico |
|---|---|---|
| `--stone-0` | `#FFFFFF` | surface |
| `--stone-50` | `#F6F5F1` | canvas |
| `--stone-100` | `#EFEEE9` | surface muted, neutral bg |
| `--stone-200` | `#DEDDD7` | subtle border |
| `--stone-400` | `#85877F` | control border |
| `--stone-500` | `#666962` | secondary text |
| `--stone-700` | `#4D504A` | neutral badge text |
| `--stone-900` | `#191A18` | primary text, ink |
| `--night-900` | `#181917` | sidebar |
| `--night-800` | `#222320` | sidebar hover |
| `--night-700` | `#2A2B28` | sidebar active |
| `--night-600` | `#3A3B37` | sidebar border / control border on dark |
| `--night-300` | `#A3A69E` | sidebar secondary text |
| `--night-50` | `#F6F5F1` | sidebar text |
| `--moss-50` | `#E5ECE7` | accent soft |
| `--moss-200` | `#A9C2B1` | focus on dark |
| `--moss-600` | `#42634E` | accent |
| `--moss-700` | `#36523F` | accent hover |
| `--leaf-50` | `#E3EEE5` | success bg |
| `--leaf-700` | `#2F5A3B` | success text |
| `--amber-50` | `#F7EBD3` | warning bg |
| `--amber-600` | `#B7791F` | warning solid (iconos/bordes, ≥ 3:1) |
| `--amber-800` | `#7A4E0E` | warning text |
| `--clay-50` | `#F7E3E1` | danger bg |
| `--clay-600` | `#B44747` | destructive |
| `--clay-700` | `#9A3A3A` | destructive hover |
| `--clay-800` | `#9A3434` | danger text |

### 1.2 Semánticos

| Token | → | Notas |
|---|---|---|
| `--color-bg` | stone-50 | canvas (body y shell) |
| `--color-surface` | stone-0 | cards, paneles, panel de login |
| `--color-surface-muted` | stone-100 | zonas secundarias, placeholders |
| `--color-surface-elevated` | stone-0 | menús, dialogs, sheets (con sombra) |
| `--color-text` | stone-900 | |
| `--color-text-secondary` | stone-500 | |
| `--color-text-on-action` | stone-0 | |
| `--color-border` | stone-200 | solo decorativo |
| `--color-border-control` | stone-400 | inputs, checkbox, secondary button (≥ 3:1) |
| `--color-overlay` | `rgb(25 26 24 / 0.48)` | fondo de modal |
| `--color-action` | moss-600 | primary, links, selección |
| `--color-action-hover` | moss-700 | |
| `--color-action-subtle` | moss-50 | accent soft: fondo seleccionado, `active` |
| `--color-selected` | moss-50 | alias de compatibilidad |
| `--color-focus` | moss-600 | anillo sobre claro |
| `--color-focus-on-dark` | moss-200 | anillo dentro de sidebar/rail/login frame |
| `--color-focus-ring-soft` | `rgb(66 99 78 / 0.18)` | halo de inputs con foco |
| `--color-danger-action` | clay-600 | destructive |
| `--color-danger-action-hover` | clay-700 | |
| `--color-sidebar` | night-900 | |
| `--color-sidebar-hover` | night-800 | |
| `--color-sidebar-active` | night-700 | |
| `--color-sidebar-border` | night-600 | separadores en oscuro |
| `--color-sidebar-text` | night-50 | |
| `--color-sidebar-text-secondary` | night-300 | |
| `--color-media-overlay` | `rgb(25 26 24 / 0.72)` | duración y chips sobre thumbnails |

### 1.3 Status tones (`--status-{tone}-{text,bg,solid}`)

| Tone | text | bg | solid |
|---|---|---|---|
| neutral | stone-700 | stone-100 | stone-500 |
| active | moss-600 | moss-50 | moss-600 |
| success | leaf-700 | leaf-50 | leaf-700 |
| warning | amber-800 | amber-50 | amber-600 |
| danger | clay-800 | clay-50 | clay-600 |

`--status-info-*` desaparece.

### 1.4 Contraste (WCAG 2.x, medido)

| Par | Ratio | Objetivo |
|---|---|---|
| text `#191A18` / surface · canvas | 17.5 · 16.0 | 4.5 |
| secondary `#666962` / surface · canvas · muted · accent soft | 5.58 · 5.12 · 4.81 · 4.65 | 4.5 |
| white / accent `#42634E` (hover `#36523F`) | 6.72 (8.62) | 4.5 |
| accent como texto/foco / surface · canvas | 6.72 · 6.16 | 4.5 / 3 |
| accent / accent soft (badge active, selección) | 5.59 | 4.5 |
| white / destructive `#B44747` (hover `#9A3A3A`) | 5.34 (6.91) | 4.5 |
| destructive como texto / canvas | 4.89 | 4.5 |
| control border `#85877F` / surface · canvas | 3.64 · 3.34 | 3 |
| sidebar text `#F6F5F1` / sidebar · active | 16.2 · 13.0 | 4.5 |
| sidebar secondary `#A3A69E` / sidebar · hover | 7.15 · 6.4 | 4.5 |
| focus-on-dark `#A9C2B1` / sidebar · active | 9.27 · 7.49 | 3 |
| badge success · warning · danger · neutral | 6.66 · 6.08 · 5.84 · 7.06 | 4.5 |
| warning solid `#B7791F` / surface (iconos) | 3.64 | 3 |
| white / media overlay sobre blanco puro (peor caso) | 6.93 | 4.5 |
| flash: `#F6F5F1` / ink | 16.0 | 4.5 |

`--color-border` (1.36:1) y `accent soft` como fondo (1.2:1) **nunca** son el único
indicador: van acompañados de outline, texto, icono o checkbox.

### 1.5 Tipografía

| Token | Valor |
|---|---|
| `--font-sans` | `"Geist Variable", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` |
| `--font-mono` | sin cambios (system mono) |
| `--text-xs` / `sm` / `base` / `md` / `lg` / `xl` / `2xl` / `3xl` | 0.75 / 0.8125 / 0.9375 / 1 / 1.25 / 1.5 / 1.875 / 2.125 rem (12/13/15/16/20/24/30/34) |
| `--weight-regular` / `medium` / `strong` / `semibold` | 400 / 500 / 550 / 600 |
| `--leading-body` / `tight` / `title` | 1.5 / 1.3 / 1.15 |
| `--tracking-title` | -0.015em (solo ≥ 24px) |

| Rol | sm | lg+ |
|---|---|---|
| Page title | 2xl/600 | 3xl/600, tracking-title |
| Section title | lg/600 | xl/600 |
| Card title | base/550 | md/550 |
| Body | base | base |
| Meta | sm | sm |
| Caption (duración, contadores) | xs | xs |
| Button | `--text-button` 0.875rem (14)/550 | ídem |
| Input text | md (16, evita zoom iOS) | base |

### 1.6 Spacing, layout, radios, sombras, motion, targets

| Token | Valor |
|---|---|
| `--space-1…7` | 4 / 8 / 12 / 16 / 24 / 32 / 48 px (sin cambios) |
| `--page-gutter` | 16 (sm) · 24 (md) · 32 (lg+) |
| `--section-gap` | 32 (sm/md) · 40 (lg+) |
| `--radius-sm` | 6px (duración, chips pequeños) |
| `--radius-control` | 10px (buttons, inputs, nav items) |
| `--radius-menu` | 12px (menús, flash) |
| `--radius-surface` | 16px (cards) |
| `--radius-overlay` | 20px (dialogs, sheets, drawer, panel de login) |
| `--radius-pill` | 999px (badges, chips de filtro, segmented track) |
| `--shadow-raised` | `0 1px 2px rgb(25 26 24 / .06), 0 4px 12px rgb(25 26 24 / .06)` |
| `--shadow-overlay` | `0 8px 24px rgb(25 26 24 / .14)` |
| `--shadow-modal` | `0 24px 64px rgb(25 26 24 / .22)` |
| `--motion-fast` / `--motion-medium` | 140ms / 200ms (0 con reduced motion) |
| `--motion-easing` / `--motion-easing-out` | `cubic-bezier(.2,0,0,1)` / `cubic-bezier(0,0,.2,1)` |
| `--target-min` | 44px (táctil; scroll-padding) |
| `--control-height` | 44px; **40px** en `(min-width:1024px) and (hover:hover) and (pointer:fine)` |
| `--focus-ring-width` / `offset` | 2px / 2px |
| Breakpoints | sin cambios: sm < 768 · md 768–1023 · lg 1024–1279 · xl ≥ 1280 |

**Regla de literales (SC-003)**: en CSS de componentes/pantallas no aparecen colores, radios,
sombras, duraciones, tamaños de fuente ni espaciados de componente literales. Son legítimos:
`0`, `%`, `fr`, `minmax`, `auto`, `aspect-ratio`, `ch`, anchos/altos de layout propios
(p. ej. `--shell-sidebar-width`, `min(32rem, …)`), `1px` de borde y `env()`.

---

## 2. Fuente

- Paquete `@fontsource-variable/geist` con versión exacta, importado una vez en `main.tsx`.
- Sin `<link>` externo, sin CDN, sin preconnect. `font-display: swap` (del paquete).
- Ningún archivo de fuente fuera del bundle; el build lo sirve el propio backend.

---

## 3. Componentes compartidos

| Componente | Cambia visualmente | Contrato que NO cambia | CSS centralizado |
|---|---|---|---|
| `Button` | radios 10px, altura `--control-height`, texto 14/550; primary moss; secondary surface + border-control; ghost texto `--color-text` (no accent) y hover `surface-muted`; danger clay; `ap-delete-entry` = secondary con texto danger; transiciones 140ms de fondo/borde/sombra; loading spinner igual | variantes, `as="link"`, `loading` + `aria-busy`, clases `ap-button--{variant}` y `ap-delete-entry` | `ui.css` |
| `IconButton` | cuadrado `--control-height`, radio 10px, hover surface-muted | `label` obligatorio, icono `aria-hidden` | `ui.css` |
| `Icon` | se añaden paths de la misma familia: `folder`, `image`, `inbox`, `grid` (y los que el checkpoint requiera, mismo stroke 2 / 24 grid); tamaño por defecto 20, 18 en nav compacta | API, `aria-hidden`, sin librería | `Icon.tsx` |
| `Badge` / `StatusBadge` | pill, 12–13px/550, padding 2×8, fondo tenue por tono (§1.3); `Tone` = neutral/active/success/warning/danger | texto + icono siempre; no live regions; mapa único | `ui.css`, `status.ts` |
| `Card` | radio 16px, borde decorativo, sin sombra en reposo | elemento/semántica | `ui.css` |
| `EmptyState` | icono opcional (prop `icon?`), título 18/600, descripción meta 1 línea, centrado en vista completa | exactamente una acción primaria, link secundario | `ui.css` |
| `ErrorState` | superficie `clay-50`, borde izquierdo 3px danger, icono alert | `role="alert"`, mensaje seguro, Retry | `ui.css` |
| `Skeleton` | bloques `surface-muted`, radio 6px, shimmer **no** (estático) | `role="status"`, `aria-busy`, label oculto | `ui.css` |
| `Dialog/Drawer/Sheet` | radio 20px, padding 24/28, overlay 48 %, sombra modal, fade+translate 200ms; Sheet en `sm` = **bottom sheet** (max-height `100dvh − 24px`, radios superiores, safe-area) | Radix: modal, focus trap, Escape, overlay close, restauración de foco, título requerido; clases `ap-modal--{variant}` | `ui.css` |
| `Disclosure` | botón ghost; región con `.ap-menu` cuando es menú | `aria-expanded/controls`, Escape, click/tap only | `ui.css` (`.ap-menu`) |
| `DetailSurface` | panel con borde izquierdo sutil sobre surface, header 20/600, footer separado | portal persistente, `panelFrom`, cierre a URL padre, foco al título | `ui.css` |
| `Field` | label 14/550 arriba, hint 13 meta debajo, error 13 danger con icono | `aria-describedby`, `aria-invalid`, required | `ui.css` |
| Controles nativos (`.ap-input`, `.ap-field input/select/textarea`) | altura `--control-height`, radio 10, borde control, placeholder secundario, foco accent + halo `--color-focus-ring-soft`, sin inset; select con flecha nativa; checkbox/radio 18px `accent-color` | controles nativos, mismos atributos | `ui.css` |
| `ChoiceGroup` | opciones como tiles con patrón de selección (§4); `switch` = segmented neutro (track `surface-muted`, seleccionado surface + `--shadow-raised` + 550) | radios nativos, `fieldset/legend`, flechas | `ui.css` |
| `PageActions` | barra sticky `sm` con surface + borde superior sutil + safe-area | sticky en `sm`, orden DOM, scroll-padding (recalculado con `--control-height`) | `ui.css` |
| `Flash` | ink, radio 12px, sombra overlay, fade-in | posición, un mensaje | `shell.css` |
| `.ap-menu` (nuevo modificador, no primitive) | superficie elevated, radio 12, sombra overlay, padding 4, items `--control-height` alineados a la izquierda, hover muted, destructivo texto danger | — | `ui.css` |
| `.ap-page-header` (nueva clase) | título + contexto + acciones en una fila (wrap en sm) | DOM de cada header | `ui.css` |
| `.ap-actions` (sustituye `.actions` legacy) | flex wrap gap 8 | — | `ui.css` |

---

## 4. Patrón de selección (único)

`outline: 2px solid var(--color-action); outline-offset: 2px` (o `box-shadow` inset en filas)
+ fondo `--color-action-subtle` + indicador visible (checkbox, radio o marca). Aplica a:
Media card `--selected`/`--checked`, `ap-choice--selected`, filas del folder picker,
platform options, post/account/calendar item con `aria-current`.

---

## 5. Status map final (`ui/status.ts`)

Labels e iconos **idénticos** a hoy.

| Estado | Label | Icono | Tone |
|---|---|---|---|
| draft | Draft | circle | neutral |
| scheduled_automatic | Scheduled · automatic | clock | neutral |
| scheduled_manual | Scheduled · manual | clock | neutral |
| scheduled_paused | Scheduled · paused | pause | warning |
| publishing | Publishing | clock | active |
| published | Published | check | success |
| failed | Failed | alert | danger |
| needs_review | Needs review | alert | **warning** |
| needs_action | Needs action | alert | warning |
| missed | Missed | alert | danger |
| cancelled | Cancelled | close | neutral |
| ready | Ready | check | success |
| reconnect_needed | Reconnect needed | alert | danger |
| setup_required | Finish setup | alert | warning |
| not_connected | Not connected | circle | neutral |
| inactive | Inactive | pause | neutral |
| configured | Configured | check | success |
| partial | Partially configured | alert | warning |
| not_configured | Not configured | alert | danger |
| coming_soon | Coming soon | clock | neutral |

Fuera del mapa (mismo criterio): `usage-indicator.ts` attention → warning, scheduled → neutral,
drafts/not used → neutral, published → success; `DeleteConfirmDialog __changed` → active.

---

## 6. Shell

| | lg+ | md | sm |
|---|---|---|---|
| Nav | sidebar oscura 16rem | rail oscuro 6rem | bottom bar clara |
| Brand | monograma + "AutoPublisher" | oculto | oculto |
| Item | sin caja; hover sidebar-hover; activo sidebar-active + 550 + texto pleno | ídem, icono + label corta | icono + label; activo texto ink + 550 + pill accent-soft tras el icono |
| Settings | separado al pie (`margin-top:auto`), mismo orden DOM | al pie | en "More" (igual que hoy) |
| Project selector | en la sidebar, select oscuro | en TopBar clara | en TopBar clara |
| Foco | `--color-focus-on-dark` | `--color-focus-on-dark` | `--color-focus` |
| TopBar | — | canvas, borde inferior sutil | ídem |

No cambian: destinos, orden, rutas, `aria-current`, "Skip to content", task mode,
`useMediaQuery` (dónde vive el selector, si existe "More").

---

## 7. Pantallas (resumen contractual; detalle en research R14–R18)

- **Home**: misma información y orden DOM; `lg`+ en dos columnas por CSS (Attention + Up next |
  Projects); attention en superficie única con filas; ok como línea tranquila; Up next como
  timeline; Projects como tiles sin cifras grandes. Prohibido KPI cards.
- **Library**: media card con thumbnail a sangre 4:5 (asset dominante, ~75 % en cards
  estándar; target, no umbral), meta subordinada, badge discreto, menú siempre visible;
  folders/entries horizontales en surface-muted con icono propio; selección §4; SelectionBar
  ink; detalle con preview `contain`. Clases `ap-media-grid`, `ap-media-card__title`,
  `ap-selection-bar__count`, `ap-library` se conservan.
- **Login**: marco `--color-sidebar` a pantalla completa, panel claro 400px, h1 wordmark dentro
  del panel, Password, `Sign in`, error, nota de reset; sin copy nuevo.
- **Posts**: filas sobre superficie única, when `tabular-nums`, secciones por espacio, switch
  segmented neutro, `New post` con `.ap-menu`. **Calendar**: layout y breakpoints intactos,
  hoy = chip + texto "Today" existente, eventos con borde de tono.
- **Settings**: sección = título/descr. a la izquierda (lg) + contenido en una superficie; sin
  navegación nueva; sin card por input.
- **Accounts / connections**: legacy migrado a `ap-connection*`; banda de estado clara.
- **Project chrome**: header con eyebrow, strip de pills, onboarding con pasos numerados.
- **Publish**: hereda tokens/primitives; sin cambios estructurales.
- **Errores**: ErrorState/NotFound con el sistema.

---

## 8. Motion

| Elemento | Entrada | Salida |
|---|---|---|
| Overlay | fade 200ms | fade 160ms |
| Dialog | fade + translateY(8px→0) 200ms | fade 160ms |
| Sheet (sm) | translateY(16px→0) + fade 220ms | fade 160ms |
| Drawer | translateX(16px→0) + fade 220ms | fade 160ms |
| Menú (`.ap-menu`) | fade + translateY(-4px→0) 160ms | — (`hidden`) |
| Card hover | sombra + translateY(-1px) 140ms | — |
| Controles | color/fondo/borde/sombra 140ms | — |

Con `prefers-reduced-motion: reduce`: ningún desplazamiento (regla global existente).

---

## 9. Lo que NO cambia (verificable)

1. Rutas (`routes.tsx`) y `handle.taskMode`.
2. Árbol de componentes y props públicas, salvo: `EmptyState.icon?` (opcional), `Tone`
   (`info` → `active`), paths nuevos en `Icon`.
3. Textos funcionales, labels, nombres accesibles, roles, `aria-*`.
4. Número de pasos y confirmaciones (Delete = una).
5. Clases-contrato consultadas por tests: `ap-button--primary|secondary|danger|ghost`,
   `ap-delete-entry`, `ap-modal--dialog|drawer|sheet`, `ap-page-actions--sticky`,
   `ap-calendar-week|agenda`, `ap-delete-dialog`, `ap-delete-dialog__name`, `ap-media-grid`,
   `ap-media-card__title`, `ap-selection-bar__count`, `ap-library`, `preview`.
6. Backend: sin cambios.
