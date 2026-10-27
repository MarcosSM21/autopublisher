# AutoPublisher design system

The visual and interaction system of the AutoPublisher web app. Feature 018 laid
the accessible foundation (tokens, primitives, focus, targets); Feature 023
(Visual Refresh) gave it its current direction. Tokens live in
`frontend/src/ui/tokens.css`, shared primitives and patterns in
`frontend/src/ui/` (`ui.css`), the shell in `frontend/src/shell/`.

## Direction: Creative Editorial Workspace

A professional tool for working with creative content: **calm, creative,
intentional, premium, functional**. Never corporate, generic, flashy,
decorative or an admin-dashboard template.

## Principles

1. **Content first.** Images and videos are the content; the UI frames them and
   never competes with them.
2. **Quiet chrome.** Navigation, secondary buttons, borders and controls stay
   calm; one accent, used sparingly.
3. **Strong hierarchy** from size, weight and spacing, not from colour: where am
   I, what am I looking at, what is the main action, what is secondary.
4. **Spacious, not empty.** Generous space for reading; grouping by space and by
   one surface with separators rather than a box around everything.
5. **Colour reinforces, never carries, meaning.** Every state has visible text
   and an icon; colour is the third signal.
6. **One primary action per view** (and exactly one in an empty state).
7. **Accessible by default:** WCAG 2.2 AA contrast, visible keyboard focus,
   comfortable targets, nothing reachable only by hover, reduced motion
   respected.
8. **If making it prettier makes it harder to understand, reject it.** No
   gradients, glassmorphism, decorative imagery, parallax, glow or page
   transitions.

## Tokens

Two layers. Components use **only semantic tokens**; a future dark theme only
redefines the semantic layer. Light theme only for now.

| Layer | Examples |
|---|---|
| Primitive | warm neutrals `--stone-0…900`, dark navigation `--night-900…50`, accent `--moss-50/200/600/700`, status `--leaf-*`, `--amber-*`, `--clay-*` |
| Semantic | `--color-bg`, `--color-surface`, `--color-surface-muted`, `--color-surface-elevated`, `--color-text`, `--color-text-secondary`, `--color-border`, `--color-border-control`, `--color-action(-hover/-subtle)`, `--color-danger-action(-hover)`, `--color-focus`, `--color-focus-on-dark`, `--color-sidebar-*`, `--color-overlay`, `--color-media-overlay`, `--status-{neutral,active,success,warning,danger}-{text,bg,solid}` |

### Palette

| Role | Token → value |
|---|---|
| Canvas | `--color-bg` stone-50 `#F6F5F1` (warm off-white) |
| Surface / elevated | `--color-surface` `#FFFFFF` |
| Muted surface | `--color-surface-muted` stone-100 `#EFEEE9` |
| Text / secondary | stone-900 `#191A18` / stone-500 `#666962` |
| Decorative border / control border | stone-200 `#DEDDD7` / stone-400 `#85877F` |
| Accent (action, links, focus) | moss-600 `#42634E`, hover moss-700 `#36523F`, soft moss-50 `#E5ECE7` |
| Destructive | clay-600 `#B44747`, hover clay-700 `#9A3A3A` |
| Sidebar | night-900 `#181917`, hover night-800, active night-700, border night-600; text `#F6F5F1`, secondary night-300 `#A3A69E` |
| Focus on dark | moss-200 `#A9C2B1` |

### Scales

| Group | Values |
|---|---|
| Spacing | 4 · 8 · 12 · 16 · 24 · 32 · 48 px (`--space-1…7`); page gutter 16 / 24 (`md`) / 32 (`lg`); section gap 32 / 40 (`lg`) |
| Radii | 6 px small chips/thumbnails (`--radius-sm`) · 10 px controls (`--radius-control`) · 12 px menus, flash · 16 px surfaces/cards · 20 px dialogs, sheets, drawer · pill for badges and status pills |
| Shadows | `--shadow-raised` (hover of cards, selected segment, buttons over media) · `--shadow-overlay` (menus, flash, import panel) · `--shadow-modal` (dialogs, sheets, drawer, login panel); surfaces at rest have none |
| Sizes | `--control-height` 44 px, **40 px only with a fine pointer from `lg`**; `--target-min` 44 px always (rows and tiles that are pure touch targets) |
| Motion | `--motion-fast` 140 ms, `--motion-medium` 200 ms; easing `cubic-bezier(0.2, 0, 0, 1)` / out `(0, 0, 0.2, 1)` |
| Breakpoints | `sm < 768px`, `md 768–1023px`, `lg 1024–1279px`, `xl ≥ 1280px` (mirrored in `src/ui/breakpoints.ts`) |

## Typography

**Geist Variable**, bundled locally (`@fontsource-variable/geist`,
`font-display: swap`, no remote request) with the system stack as fallback;
`ui-monospace` for technical values. Sizes in `rem`, so the browser text-size
setting is respected.

| Role | Size / weight | Class |
|---|---|---|
| Page title | 30 px (34 from `lg`) / 600, tracking −0.015em | `.ap-page-title` |
| Section title | 20 px (24 from `lg`) / 600 | `.ap-section-title` |
| Card / detail title | 16–20 px / 600 | — |
| Body, navigation | 15 px / 400, line height 1.5 | — |
| Row and card titles | 15 px / 550 | — |
| Buttons, labels | 14 px / 550 | `.ap-button`, `.ap-field__label` |
| Meta, badges, hints, group headings | 13 px / 400–600 | `.ap-meta` |
| Captions (durations, counters) | 12 px | — |
| Times and counts | tabular figures | `.ap-tabular` |
| Technical value | 13 px monospace | `.ap-mono` |

Inputs use 16 px on phones (no iOS zoom) and 15 px from `md`.

## Surfaces and layout

- Canvas warm off-white; content on white surfaces with a decorative 1 px border
  and 16 px radius; muted surfaces for quiet panels (status band, status panel,
  captions).
- Lists are **one surface with separators** (Posts, Accounts, Attention,
  Destinations, Settings rows), not a card per row.
- Settings: each section is title (left column from `lg`) + its content on
  **one** surface; never a card around each field.
- `.ap-page-header`: title, then actions on the same line (wraps on `sm`).

## Shell

One shell for every breakpoint: one `<nav aria-label="Main">`, one `<main>`, a
"Skip to content" link.

- **Dark navigation** (`--color-sidebar`): a fixed bottom bar on `sm`
  (Home · Library · Posts · Accounts; Settings in the TopBar's "More"), an icon
  rail with short labels plus a light TopBar on `md`, a sidebar with the
  wordmark and monogram on `lg`. Focus on the dark surfaces uses
  `--color-focus-on-dark`.
- Active item: `aria-current="page"` plus weight, an indicator and a tint,
  never colour alone.
- Project selector in the sidebar (dark select, `color-scheme: dark`) on `lg`,
  in the TopBar otherwise.
- Task mode (`handle: { taskMode: true }`: Publish media, Text post) hides the
  bottom bar on `sm`, so the task's sticky `PageActions` sit at the bottom.
- Flash: ink surface, 12 px radius, overlay shadow, fade in.
- The fixed bottom bar reserves its height + `env(safe-area-inset-bottom)`;
  `scroll-padding-bottom` keeps the focused element above it.

## Primitives and shared patterns

| Primitive / pattern | Contract |
|---|---|
| `Button` | `primary` (max one per view), `secondary` (surface + control border), `ghost` (text colour, muted hover), `danger`; `.ap-delete-entry` = secondary weight with danger text (the solid danger is the confirmation); `loading` keeps label and width and sets `aria-busy`; `as="link"` |
| `IconButton` | Square `--control-height`, `label` required by type, icon hidden |
| `Icon` | Own inline SVG set (24 grid, 2 px stroke, `aria-hidden`), 20 px default: home, library, posts, accounts, settings, more, back, close, alert, check, clock, plus, pause, circle, folder, image, inbox, grid |
| `Badge` / `StatusBadge` | Pill, 13 px / 550, soft tone background; text always + icon; one map (`src/ui/status.ts`); not live regions |
| `Card` | 16 px radius, decorative border, no shadow at rest |
| `EmptyState` | Optional icon in a muted circle, title 20/600, one-line description, exactly one primary action |
| `ErrorState` | Danger-soft surface, 3 px danger edge, alert icon, `role="alert"`, Retry |
| `Skeleton` | Static muted blocks (no shimmer), `role="status"` |
| `Dialog` / `Drawer` / `Sheet` | Radix foundation (modality, focus trap, Escape, focus returned to the opener); 20 px radius, 24/28 px padding, overlay 48 %, modal shadow; `Sheet` is a **bottom sheet** on `sm` (own scroll, safe area, decorative handle), centred from `md`; footer actions full width on `sm` in DOM order; optional `returnFocus` picks where focus goes on close when the opener may have been replaced or removed (falls back to the opener) |
| `Disclosure` / `.ap-menu` | `aria-expanded/controls`, click/tap only, Escape returns focus; as a menu: elevated surface, 12 px radius, overlay shadow, left-aligned items `--control-height`, destructive item in danger text. Posts `New post` uses the same look |
| `DetailSurface` | Side panel (subtle left border on surface) from `panelFrom`, drawer on `md`, full page on `sm`; closes to the parent URL, focus to its title |
| `Field`, `.ap-input` | Label 14/550 above, hint 13 below, error 13 danger; control `--control-height`, 10 px radius, control border, focus = accent edge + soft halo (`--color-focus-ring-soft`) |
| `ChoiceGroup` | Native radios in a fieldset; options as tiles with the selection pattern; `switch` = neutral segmented control (muted track, selected segment raised: surface + shadow + 550) |
| `PageActions` | Sticky bar on `sm` (surface, top border, safe area, scroll padding for one or two rows) |
| `.ap-actions`, `.ap-form`, `.ap-form-label` | Action row; form grid; a label that wraps its text and control |
| `.ap-notice` | The one warning notice: warning-soft, 3 px warning edge |
| `.ap-technical` | Term/value list for raw values; `--controls` is the bordered disclosure around the connection panels |
| `.ap-connection*` | Connection panels (`components/connection.css`): tone edge + soft background repeat the status badge's text |

There is no global `form`, `label` or `fieldset` styling: every form styles
itself. `index.css` keeps only the base, the `.error` alias (danger text) and
`.preview` (MediaPreview).

### Selection pattern (one for everything)

Accent edge (2 px; `box-shadow` inset on rows) + `--color-action-subtle` fill +
a visible checkbox, radio or mark. Used by media cards (`--selected`,
`--checked`), `ap-choice--selected`, folder picker rows, platform options,
checked destinations, and Post/Account/Calendar items with `aria-current`.

### StatusBadge map

| Tone | Post | Account | Platform |
|---|---|---|---|
| success | Published | Ready | Configured |
| active | Publishing | — | — |
| neutral | Draft, Scheduled · automatic, Scheduled · manual, Cancelled | Not connected, Inactive | Coming soon |
| warning | Scheduled · paused, Needs action, Needs review | Finish setup | Partially configured |
| danger | Failed, Missed | Reconnect needed | Not configured |

## Screens

- **Home**: workspace overview, not a KPI dashboard. Attention as one surface of
  rows (urgent rows with a 3 px danger edge + icon), "Everything looks good" as a
  calm line, Up next as a timeline (time column, content, badge), Projects as
  tiles; two columns from `lg` by CSS only.
- **Library** (content first): thumbnails full-bleed at 4:5 with
  `object-fit: cover` (the asset dominates the card), compact meta, a small usage
  badge; duration chip on `--color-media-overlay`; the card's actions button is
  always visible on its own opaque surface with a hairline border (readable on
  white and black images); folders and entries as low horizontal cards with
  their own icon (no yellow folder); breadcrumb for nested folders; dark
  SelectionBar; Media detail with the preview `contain`ed on a muted surface.
- **Posts / Calendar**: rows on one surface, `tabular-nums` times, section
  headings by space; Calendar week only from `xl` (agenda below), today = soft
  accent chip + the "Today" text, events with a 3 px edge of their status tone.
  An action on an item is a sibling of its link, never inside it (icon button
  in the item's corner, labelled ghost button in the agenda). Drop targets:
  dashed outline (solid under the pointer) when allowed; muted surface plus a
  short text saying why when not; never colour alone.
- **Accounts / connections**: one surface of rows; detail with a status band
  (state, problem, next step).
- **Project chrome**: project name as a 13 px eyebrow, neutral status pills
  (warnings add an icon), onboarding as one surface with numbered steps.
- **Login**: dark frame, light 400 px panel with the wordmark.

## Focus, motion and interaction

- `:focus-visible` everywhere: 2 px solid `--color-focus`, 2 px offset;
  `--color-focus-on-dark` on the sidebar, rail and login frame. Inputs show an
  accent edge + soft halo. Outlines are never removed without a replacement.
- Nothing is available only on hover: menus open on click/tap, card actions are
  always visible, no action depends on a tooltip.
- Motion is short and purposeful: overlay fade 200 ms; dialog fade + 8 px rise;
  bottom sheet 16 px rise; drawer 16 px slide; menu fade + 4 px drop; card hover
  shadow + 1 px lift; control colour/border/shadow 140 ms. No page transitions,
  scroll reveals or animation libraries.
- `prefers-reduced-motion: reduce` sets the motion tokens to 0 and stops
  animations and transitions globally (state changes become instant).
- Lists hidden behind a phone's full-page detail use the `hidden` attribute; a
  class that sets `display` restores `[hidden] { display: none }`.
- CSS order: page CSS loads before `ui.css`, so a page that specialises a shared
  class does it with explicit, minimal extra specificity (never by order, no
  `!important`).

## Responsive

- Mobile first; nothing scrolls horizontally from 375 px to ≥ 1280 px, also with
  the text at 200 %.
- Side panels and sidebars sized in `rem` are capped with `min(…, %)` so large
  text never pushes the page wider than the viewport.
- Library grid 2 columns on `sm`, `auto-fill` above; Media detail a drawer until
  `xl`; Posts side panel from `lg`; Calendar week from `xl`; Publish one readable
  column.

## Colour and contrast

Measured with the WCAG 2.x relative-luminance formula on the final tokens.

| Pair | Ratio | Target |
|---|---|---|
| Text on surface / canvas | 17.5 / 16.0 | 4.5 |
| Secondary text on surface / canvas / muted | 5.6 / 5.1 / 4.8 | 4.5 |
| Secondary text on accent-soft / success-soft / warning-soft | 4.65 / 4.7 / 4.7 | 4.5 |
| Accent as text/link on surface / canvas | 6.7 / 6.2 | 4.5 |
| White on primary (hover) | 6.7 (8.6) | 4.5 |
| White on danger / danger text on surface | 5.3 / 5.3 | 4.5 |
| Control border on surface / canvas / muted | 3.6 / 3.3 / 3.1 | 3.0 |
| Focus ring on surface / canvas / accent-soft | 6.7 / 6.2 / 5.6 | 3.0 |
| Focus-on-dark on sidebar | 9.3 | 3.0 |
| Sidebar text / secondary on sidebar; text on active item | 16.2 / 7.2; 13.1 | 4.5 |
| Status text on its soft background: neutral / active / success / warning / danger | 7.1 / 5.6 / 6.7 / 6.1 / 5.8 | 4.5 |
| Warning solid (icons, edges) on warning-soft | 3.1 | 3.0 |
| White on media overlay (over a white image) | 6.9 | 4.5 |

Decorative borders (`--color-border`, 1.4:1; sidebar border 1.6:1) never carry
meaning; controls use `--color-border-control` (≥ 3:1).

## Performance

- Geist is local (one `woff2` subset per script, Latin ~29 KB loaded); the app
  makes no third-party requests.
- CSS only for visual effects; no animation, UI or icon libraries.
- Built CSS after 023: 83 KB (13 KB gzip), up from 58 KB (9.4 KB gzip) before the
  refresh; first paint on Home/Library stays in the tens of milliseconds with no
  perceptible layout shift.

## UI UX Pro Max recommendations

Tool: `ui-ux-pro-max-skill` v2.15.0 (MIT), local tooling in
`.claude/skills/ui-ux-pro-max/`, ignored by Git; stdlib scripts run with
`python3 -s -E` (no network). Recommendations are advice, never requirements.

### Adopted

| Recommendation | Where |
|---|---|
| Semantic colour tokens, no raw hex in components | Two-layer tokens |
| Consistent type scale, line height 1.5 | Typography |
| Text contrast ≥ 4.5:1, focus ring ≥ 3:1 | Contrast table |
| Colour never alone: text + icon | `Badge`, `StatusBadge`, Calendar today, Calendar drop targets |
| Badges are not competing live regions | `StatusBadge` |
| Empty states with one action; error recovery with Retry | `EmptyState`, `ErrorState` |
| Modal focus trap and focus return | `Dialog`/`Drawer`/`Sheet` |
| Visible labels, errors next to the field; grouped choices in fieldsets | `Field`, `ChoiceGroup` |
| Reduced motion; short shared motion tokens | Motion |
| SVG icons, one family and stroke, decorative icons hidden | `Icon` |
| Text reflow: no clipped fixed-size boxes | Badges wrap; `min-width: 0`; capped `rem` columns |
| Breadcrumbs for nested content | Library folders (Feature 020 added nesting) |
| One primary action per view, reachable on phones | `PageActions` sticky bar |

### Rejected

| Recommendation | Why |
|---|---|
| Landing-page structures (hero, video, CTA sections) | AutoPublisher is a tool |
| Remote fonts (Google Fonts) | Local-first: Geist is bundled |
| Scroll-reveal animations, animation libraries | Decorative motion that delays content |
| Glassmorphism, Soft UI, vibrant block palettes, gradients | Hurt contrast and calm |
| Icon libraries | An own inline set covers the app without a dependency |

### Modified

| Recommendation | Adjustment |
|---|---|
| Target size (WCAG 2.2 AA asks 24 px) | 44 px controls and targets on touch; 40 px controls only with a fine pointer from `lg`; rows and tiles keep 44 px. Links inside a sentence keep the line (WCAG inline exception) |
| "No shadows unless necessary" | Three elevation tokens; nothing at rest |
| "Focus not obscured" by sticky UI | `scroll-padding-bottom` for the bottom bar and sticky `PageActions` |

## Final review (Feature 023, T109)

| Check | Result |
|---|---|
| Responsive | Login, shell, Home (with attention and Up next data), Library, Posts, Calendar, Settings, Accounts and their details at 375 / 768 / 1024 / 1280 px: no horizontal overflow |
| 200 % text | Same screens and widths: no page overflow (side panels capped); at 1024 px with a detail open the panel is narrow but usable — browser zoom (which moves to the `sm`/`md` layouts) reads better there |
| Keyboard | Skip link first; visible focus on every stop through the shell, Library, card menu (Escape returns to its button), dialogs (focus returns to the opener), Publish compose and the Add account sheet |
| Reduced motion | Dialog, sheet and menu animations at ~0 ms; no movement |
| Safe area / sticky | Bottom bar, sticky `PageActions` and bottom sheets reserve `env(safe-area-inset-bottom)` |
| Contrast | All pairs above pass |
