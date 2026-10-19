# AutoPublisher design system

The visual and interaction foundation of the AutoPublisher web app (Feature 018).
Tokens live in `frontend/src/ui/tokens.css`, primitives in `frontend/src/ui/`.

## Principles

1. **A productivity tool, not a marketing page.** Flat, calm surfaces; no
   decorative gradients, glassmorphism, heavy shadows or showcase layouts.
2. **Hierarchy comes from size, weight and spacing**, not from colour.
3. **Colour reinforces, never carries, meaning.** Every state has visible text and
   an icon; colour is the third signal.
4. **One primary action per view** (and exactly one in an empty state).
5. **Accessible by default:** WCAG 2.2 AA contrast, visible keyboard focus,
   44 px targets, nothing reachable only by hover, reduced motion respected.
6. **If making it prettier makes it harder to understand, reject it.**

## Tokens

Two layers. Components use **only semantic tokens**; a future dark theme only has
to redefine the semantic layer.

| Layer | Examples |
|---|---|
| Primitive | `--gray-50…900`, `--blue-50/100/700/800`, `--green-*`, `--yellow-*`, `--red-*`, `--sky-*`, `--space-1…7`, `--radius-*`, `--text-sm…3xl` |
| Semantic | `--color-bg`, `--color-surface`, `--color-text`, `--color-text-secondary`, `--color-border`, `--color-border-control`, `--color-action`, `--color-focus`, `--status-{success,info,warning,danger,neutral}-{text,bg,solid}` |

| Group | Values |
|---|---|
| Spacing | 4 · 8 · 12 · 16 · 24 · 32 · 48 px (`--space-1…7`) |
| Radii | 6 px controls · 10 px surfaces · pill for badges |
| Shadow | only floating surfaces (`--shadow-overlay`: dialog, drawer, sheet) |
| Touch | `--target-min: 44px` |
| Motion | `--motion-fast` 150 ms, `--motion-medium` 200 ms; both 0 under reduced motion |
| Breakpoints | `sm < 768px`, `md 768–1023px`, `lg 1024–1279px`, `xl ≥ 1280px` (mirrored in `src/ui/breakpoints.ts`; `xl` lets a page keep a drawer until there is room for a side panel) |

No dark mode yet.

## Colour and contrast

Measured with the WCAG 2.x relative-luminance formula.

| Pair | Ratio | Target |
|---|---|---|
| Text `#1F2328` on surface `#FFFFFF` / background `#F6F8FA` | 15.8 / 14.8 | 4.5 |
| Secondary text `#57606A` on surface / background | 6.4 / 6.0 | 4.5 |
| White on action `#1D4ED8` (hover `#1E40AF`) | 6.7 (8.7) | 4.5 |
| Action `#1D4ED8` as text/link on surface / background | 6.7 / 6.3 | 4.5 |
| Focus ring `#1D4ED8` against surface / background | 6.7 / 6.3 | 3.0 |
| Control border `#6E7781` on surface | 4.6 | 3.0 |
| White on danger action `#CF222E` | 5.4 | 4.5 |
| Badge success `#116329` on `#DAFBE1` | 6.6 | 4.5 |
| Badge info `#0550AE` on `#DDF4FF` | 6.7 | 4.5 |
| Badge warning `#7D4E00` on `#FFF8C5` | 6.6 | 4.5 |
| Badge danger `#A40E26` on `#FFEBE9` | 6.9 | 4.5 |
| Badge neutral `#424A53` on `#EAEEF2` | 7.7 | 4.5 |

Decorative separators (`--color-border` `#D0D7DE`, 1.45:1) never carry meaning;
input and secondary-button borders use `--color-border-control` (≥ 3:1).

## Typography

System font stack (`system-ui, -apple-system, "Segoe UI", Roboto, …`); no remote
fonts. Base 16 px, line height 1.5, sizes in `rem` so the browser text-size
setting is respected. Weights 400 and 600 only.

| Role | Size | Class |
|---|---|---|
| Page title | 24 px (30 px from `lg`) | `.ap-page-title` |
| Section heading | 20 px | `.ap-section-title` |
| Card title | 18 px | — |
| Body | 16 px | — |
| Meta / badges | 14 px | `.ap-meta` |
| Technical value | 14 px monospace, only where the value is technical | `.ap-mono` |

## Primitives (`frontend/src/ui/`)

| Primitive | Contract |
|---|---|
| `Button` | `primary` (max one per view), `secondary`, `ghost`, `danger`; ≥ 44 px; `loading` disables and sets `aria-busy`; `as="link"` renders a router `Link` |
| `IconButton` | 44×44 px, `label` required by type (its accessible name), icon hidden |
| `Icon` | Own inline SVG set (24 grid, 2 px stroke, outline, `aria-hidden`): home, library, posts, accounts, settings, more, back, close, alert, check, clock, plus, pause, circle |
| `Badge` | Text always present + optional icon; tone only reinforces |
| `StatusBadge` | Post, account or platform state → label, tone and icon from **one map** (`src/ui/status.ts`) |
| `Card` | Bordered surface, no shadow |
| `EmptyState` | Title, optional description, exactly one primary `action` (required), optional secondary link |
| `ErrorState` | `role="alert"`, safe message and "Retry" |
| `Skeleton` | `role="status"` + `aria-busy`, hidden blocks, visually hidden label |
| `Dialog` / `Drawer` / `Sheet` | One accessible foundation (`@radix-ui/react-dialog` 1.1.23): required title, focus trapped, Escape and overlay close, background inert, focus returned to the element that opened it |
| `Disclosure` | `button[aria-expanded][aria-controls]` + region; Escape closes and returns focus; click/tap only |
| `DetailSurface` | Side panel (not modal) from `panelFrom`, `md` `Drawer`, `sm` full page with "Back"; closing navigates to the parent URL. `panelFrom`: `lg` (default: Accounts, Posts list), `xl` (Library: the grid needs the width) or `never` (Calendar: the week stays readable, the detail is always a drawer from `md`). `actions` renders the detail's main actions in the panel/drawer footer or, on `sm`, a sticky `PageActions` bar. Its content is rendered once (portal into a persistent node), so crossing a breakpoint never remounts it (e.g. a connection panel keeps polling). Selecting another item remounts the detail (keyed by id), so focus moves to the new heading. `sectionTitle` (Library, Posts): as a full page the hidden list's h1 is kept (visually hidden) and the detail's title is an h2, so the detail's h3 sections never skip a level; without it (Accounts) the title stays the page's h1 |
| `Field` | Label, optional hint, required marker and inline error around one control (render prop): the control gets its name from the label and `aria-describedby` from hint and error, plus `aria-invalid` |
| `ChoiceGroup` | Native radios in a `fieldset` with a `legend` (optionally visually hidden); `orientation` `vertical` (with descriptions) or `horizontal`; `variant="switch"` is a segmented view switch (Posts `List \| Calendar`) that stays a radio group (arrow keys); `value: null` invents no default |
| `PageActions` | A page's or task's actions (one primary, at most one secondary) in a named `group`. `sticky` makes it a bar stuck to the bottom of the viewport on `sm` (above the bottom navigation, or at the bottom in task mode); from `md` it stays inline. The DOM and keyboard order are the same at every width |
| `useMediaQuery` | `matchMedia` with a safe `false` fallback (mobile first) |

Radix is used only for modality, focus trapping, Escape and focus restoration; it
brings no styles. Radix returns focus only to its own `Trigger`, so our shared
`Modal` remembers the opener and restores focus to it (covered by
`src/ui/detail-surface.test.tsx`).

### StatusBadge map

| Tone | Post | Account | Platform |
|---|---|---|---|
| success | Published | Ready | Configured |
| info | Scheduled · automatic, Publishing | — | — |
| neutral | Draft, Scheduled · manual, Cancelled | Not connected, Inactive | Coming soon |
| warning | Scheduled · paused, Needs action | Finish setup | Partially configured |
| danger | Failed, Needs review, Missed | Reconnect needed | Not configured |

Badges are not live regions: a state change is announced once by the view that
caused it, never by every badge.

## Focus, motion and interaction

- `:focus-visible` everywhere: 2 px solid `--color-focus`, 2 px offset (≥ 3:1).
  Outlines are never removed without this replacement.
- Hover, active and disabled states for every control; pressed feedback uses
  colour only (no layout shift).
- Nothing is available only on hover: menus and disclosures open on click/tap;
  `IconButton` gets its name from `aria-label` only; an optional `title` is for
  extra information, never a copy of the name, and no action depends on a tooltip.
- Motion: only the loading spinner animates (continuous motion is reserved for
  loading). `prefers-reduced-motion: reduce` sets motion tokens to 0 and stops
  animations and transitions globally.
- New 018 forms use `.ap-field`: full width on phones, at most 32 rem from `md`.
- Sticky action area: while a sticky `PageActions` bar is on the page, the
  document's `scroll-padding-bottom` reserves its height (one row, or two when a
  secondary action wraps), so a focused element is never hidden behind it.
- Menus are small disclosures (e.g. Posts `New post`): they close when an item
  is chosen, on a click outside, when the focus leaves them and on Escape (which
  returns the focus to the button). There is no generic menu primitive.
- Lists hidden behind a phone's full-page detail use the `hidden` attribute; a
  list class that sets `display` must also restore `[hidden] { display: none }`.

## Legacy CSS

`frontend/src/index.css` keeps only the classes still used by the platform
connection panels and `MediaPreview`; Feature 019 removed the Library, Publish…,
Posts and Post detail rules with their screens. Its `:root` and `body` consume
tokens. New styles live in `src/ui/*.css`, `src/shell/shell.css` and the page
folders (`src/pages/*/*.css`, `src/components/platform/platform.css`) with the
`ap-` prefix.

## App shell

One shell for every breakpoint (`src/shell/`): one `<nav aria-label="Main">`, one
`<main>` and a "Skip to content" link. CSS lays the navigation out as a fixed
bottom bar (`sm`, Home · Library · Posts · Accounts; Settings in the TopBar's
"More"), an icon rail with short labels plus TopBar (`md`) or a sidebar (`lg`).
JS (`useMediaQuery`) only places the project selector (sidebar on `lg`, TopBar
otherwise) and renders "More" on `sm`. Active items use `aria-current="page"`
plus weight, an indicator bar and a tint, never colour alone. The shell owns the
page gutters; legacy screens are wrapped, not restyled.

Task mode: a route with `handle: { taskMode: true }` (Publish media
`library/:mediaId/publish`, Text post `posts/new`) hides the bottom navigation on
`sm` (`AppShell` reads `useMatches()`), so the task's sticky `PageActions` sit at
the bottom of the viewport, and the project layout leaves out its header, status
strip and Get started (the TopBar and the task's Back stay). From `md` the rail or
sidebar stays visible.

Responsive choices of Feature 019: Library grid 2 columns on `sm` and 5–6 on
`xl` without a detail; Media detail is a drawer until `xl`; Posts uses a side
panel from `lg`; the Calendar shows a 7-column week only from `xl` (an agenda
by day below, because seven columns at 1024–1279 px are unreadable) and opens
the Post detail in a drawer; Publish keeps one readable column at every width.

## UI UX Pro Max recommendations

Tool: `ui-ux-pro-max-skill` v2.15.0 (official repository
`nextlevelbuilder/ui-ux-pro-max-skill`, MIT), installed as local tooling in
`.claude/skills/ui-ux-pro-max/` and ignored by Git. Its scripts are stdlib only
and run with `python3 -s -E` (no network). Recommendations are advice, never
requirements.

### Adopted

| Recommendation | Where |
|---|---|
| Style "Minimalism & Swiss" / "Flat": clear hierarchy, functional colour, single accent | Overall direction |
| Semantic colour tokens, no raw hex in components | Two-layer tokens |
| Base 16 px, line height 1.5, consistent type scale | Typography |
| Text contrast ≥ 4.5:1 | Every token pair above |
| Visible focus ring on every control, ≥ 2 px perimeter, 3:1 | `:focus-visible` |
| Touch targets ≥ 44 px and ≥ 8 px between targets | `--target-min`, action gaps of 12 px |
| Colour never alone: text + icon | `Badge`, `StatusBadge` |
| Badges are not competing live regions | `StatusBadge` |
| Empty states: helpful message + action | `EmptyState` (exactly one primary) |
| Error recovery: clear next step; errors announced | `ErrorState` (`role="alert"`, Retry) |
| Loading: skeleton or spinner, accessible busy status | `Skeleton`, `Button loading` |
| Modal focus trap and focus return | `Dialog`/`Drawer`/`Sheet` |
| Visible labels, errors next to the field | Existing form pattern, `.ap-field` |
| Reduced motion; animate 1–2 elements per view at most; continuous motion only for loading | Motion tokens, global rule |
| Shared motion tokens instead of one hard-coded duration | `--motion-fast`, `--motion-medium` |
| Deep links and predictable Back | Router; `DetailSurface` closes to the parent URL |
| SVG icons, one family and stroke, decorative icons hidden | `Icon` |
| Text reflow: no clipped fixed-size boxes | Badges may wrap; `min-width: 0` on cards |
| Disabled: native `disabled`, reduced emphasis, not-allowed cursor | Buttons |
| Pressed feedback without layout shift | `:active` colour states |
| Breakpoints 375 / 768 / 1024 / 1440 | `sm`/`md`/`lg`/`xl` tokens |
| Forms: visible labels, hint and error tied to the control; grouped choices in fieldsets | `Field`, `ChoiceGroup` (Feature 019) |
| One primary action per view, kept reachable on phones | `PageActions` sticky bar |

### Rejected

| Recommendation | Why |
|---|---|
| Design-system pattern "Product Demo + Features" (hero, video, CTA sections) | Landing-page structure; AutoPublisher is a tool, not a marketing site |
| Palette teal `#0D9488` primary + orange `#EA580C` accent, teal-tinted background | Two accents compete; teal with white text fails 4.5:1; tinted backgrounds add noise. We keep one AA blue (`#1D4ED8`) and functional status colours |
| Plus Jakarta Sans / Fira Sans via Google Fonts | Local-first app, no remote dependencies; the system stack is fast and familiar |
| Scroll-reveal animations (GSAP) | Decorative motion that delays content; no animation library |
| Glassmorphism, Soft UI, "Vibrant & Block-based" | Hurt contrast and calm; contradict the principles |
| Radius 0 (pure Swiss) | Small radii (6/10 px) read better as controls; still flat |
| Icon libraries (Phosphor/Heroicons/Lucide packages) | 14 icons are enough; an own inline set avoids a dependency |
| Breadcrumbs | The app has at most two levels (section → detail) |

### Modified

| Recommendation | Adjustment |
|---|---|
| Web target size (WCAG 2.2 AA asks 24 px) | We use the stricter 44 px of the spec |
| "No shadows unless necessary" | Shadow only on floating surfaces (dialog, drawer, sheet) |
| Hover transitions 150–300 ms | 150–200 ms tokens, removed under reduced motion |
| "Focus not obscured" by sticky UI | `scroll-padding-bottom` for the bottom navigation and for sticky `PageActions` bars (one or two rows) |

## Final review (T044)

| Check | Result |
|---|---|
| Hierarchy | Sizes 30/24/20/18/16/14 with weights 600/400; colour not used for hierarchy |
| Contrast AA | All token pairs pass (table above) |
| Focus | 2 px ring, 2 px offset, 6.3–6.7:1 against surfaces |
| Targets ≥ 44 px | `Button`, `IconButton` (44×44), `.ap-link`, form fields; badges are not interactive |
| Forms full width on `sm` | `.ap-field` 100 % (max 32 rem from `md`) |
| No hover-only | Disclosure and dialogs open by click/tap; no action depends on a tooltip |
| Reduced motion | Motion tokens 0, global animation/transition stop; only the spinner animates |
| Status not colour-only | Text + icon in every badge (tested) |
| SVG icons, no emoji | Own `Icon` set, `aria-hidden` (tested) |
| Labels and accessibility | `IconButton` label required by type; modal title required; detail page heading; `role="alert"`/`role="status"` where appropriate |
| Adjustments made after the review | Badges may wrap instead of overflowing; `:active` pressed states for touch |
| Product review on real screens (T063–T065) | Buttons and form controls use `border-box` (full-width controls overflowed by their border/padding); 8px kept between status-strip pills; the TopBar wraps so the project selector stays usable with 200 % text; bottom-nav labels wrap (hyphenated where the browser supports it), never hidden; no colour transition when a button swaps variant (Pause ↔ Resume); "Name saved." confirms an otherwise silent save |
| Fixed bottom navigation (Phase 5) | Content reserves its height + `env(safe-area-inset-bottom)`; `scroll-padding-bottom` keeps focus above it (checked by keyboard at 375 px, also with 200 % text) |
| Feature 019 review (375 / 768 / 1024–1279 / ≥1280 px, real browser) | Phone details are full pages (lists hidden with `[hidden]` restored); focus returns to the Post row on close; Calendar week from `xl` and its detail in a drawer; Calendar badges keep their width; `New post` menu closes outside/on choice/on Tab away and opens under the header on phones; `Cancel post` is a secondary danger action (danger text, not a solid red bar); sticky bars reserve two rows of scroll padding; each `Customize` names its destination when several sit side by side |
