# UI contracts — Feature 019

## 1. Route map

| Route | Page | Notes |
|---|---|---|
| `/p/:pid/library` | Library | Search and filters are local state (not in the URL). |
| `/p/:pid/library/:mid` | Library + Media detail (`DetailSurface`, `panelFrom="xl"`) | Library stays mounted. |
| `/p/:pid/library/:mid/publish[?posts=…]` | Publish task (media) | `handle.taskMode` → no bottom nav on `sm`. Declared **before** `library/:mediaId?`. |
| `/p/:pid/posts` | Posts List (daily) | `?q=`, `?account=<id>`. |
| `/p/:pid/posts?view=history` | Posts History | `?show=<n>` optional (client "Show more"). |
| `/p/:pid/posts?view=calendar&week=YYYY-MM-DD` | Posts Calendar | Monday (local). Invalid/missing → current week (`replace`). |
| `/p/:pid/posts/:postId[?view=…]` | Posts + Post detail (`DetailSurface`, List `panelFrom="lg"`, Calendar `panelFrom="never"` — drawer from `md`, T068) | Query of the list kept when opening/closing the detail. |
| `/p/:pid/posts/new[?posts=…]` | Publish task (text) | `handle.taskMode`. Declared **before** `posts/:postId?`. |

Not found (018 FR-005) applies to `:mid`, `:postId` and to a Publish task whose Media is not
in the project.

## 2. Publish set URL (`?posts=`)

- Format: comma-separated positive integers (`parseId` per item). Order preserved;
  duplicates removed (first wins); max 50 items (rest dropped).
- Written with `replace` after `Continue`, after add/remove destination, after `Add to this
  task` (an active Draft of this Media outside the set: its id is added, no write), after
  dropping invalid ids, and when Resume (no `posts`) resolves the Media's drafts.
- Re-adding an account reactivates only an id removed in this task session (React state);
  after a reload a new Draft is created. Historical Cancelled Posts are never looked up.
- Back from the task goes to the previous history entry (Media detail / Posts), not to an
  intermediate task state.
- Media mode without `posts`: drafts of the Media (from `GET /contents/{mid}/usage`,
  `display_state == "draft"`) → if any, `replace` to `?posts=<their ids>`; else Compose.
- Text mode without `posts`: Compose.
- With `posts`: load each id (`GET /publications/{id}`), keep only valid members
  (data-model §4). Empty after validation → notice + Compose.

## 3. Publish task rendering

```text
phase = loading | composing | creating | task
task  = { review: Draft[], results: Post[] }   # partition by display_state
```
- `composing`: MediaSummary · Destinations · Presets · Content · [Continue] (Back to media).
- `creating`: same view, Continue busy, inputs read-only.
- `task` with `review.length > 0`: collapsed Destinations + Content-by-destination summary,
  "Your drafts are saved…" message, Platform details, When, error summary slot, CTA
  `Publish to N destinations` | `Schedule N posts` (N = `review.length`), `Finish later`.
- `task` with `results.length > 0`: "Results" section (aggregate line + one row per Post:
  human state, message, `Open post` for problems; `View posts`, `Back to Library`). When the
  set is mixed both sections are on the page: Results first, then Review ("Still to finish ·
  N"). With no Review part the page is a result page only.

## 4. Posts sections (precedence; a Post is in exactly one)

1. History (`view=history` only): `published`, `cancelled`.
2. Needs you: `needs_review` > `failed` > `missed` > `needs_action` > scheduled with known
   problem (overview `incomplete` id, or account not `ready`) — then by date ascending.
3. Upcoming: `publishing` (top, "Publishing now"), then `scheduled_*` grouped Today /
   Tomorrow / date.
4. Drafts: `draft`.

## 5. Post detail action table (FR-071 mapping)

| display_state / condition | Primary | Secondary | Tertiary |
|---|---|---|---|
| draft + media | Continue in Publish → `/library/:mid/publish` | — | Cancel post |
| draft + text | Continue setup → `/posts/new?posts=:id` | — | Cancel post |
| scheduled_* + known problem | Complete details (opens Platform details) | Edit schedule | — |
| scheduled_automatic | Edit schedule | Publish now | — |
| scheduled_paused | Edit schedule | Open Settings | — |
| scheduled_manual | Publish automatically | Publish now | — |
| missed | Reschedule | Publish now | — |
| failed | Retry now | Reschedule | Move to drafts |
| needs_review | Check result (Dialog: reconcile → if still uncertain, acknowledgement → `Publish again`) | — | — |
| needs_action | Check status | — | — |
| publishing | (progress, no action) | — | — |
| published | Open on <platform> | — | — |
| cancelled | Reactivate | — | — |

Actions that publish or arm a TikTok Direct Post open the action Dialog with the single
declaration (§6).

## 6. Shared components (new or adapted)

| Component | Contract |
|---|---|
| `ui/Field` | Label, hint, inline error (`aria-describedby`, `aria-invalid`), required marker. |
| `ui/ChoiceGroup` | Radio group (`fieldset`/`legend`), vertical or `horizontal`; `variant="switch"` = view switch (List \| Calendar), 44 px targets. |
| `ui/PageActions` | Page header actions; on `sm` a sticky bottom bar with the primary and at most one secondary action that never covers the focused element (scroll-padding). No generic overflow menu unless a concrete surface needs it. |
| `ui/DetailSurface` | + `panelFrom?: "lg" \| "xl" \| "never"` (default `lg`; `never` = Calendar, always a drawer from `md`, T068), + `actions?: ReactNode` (sticky footer), own scroll area, focus to heading on open, unchanged portal (no remount across breakpoints). Accounts unchanged. |
| `ErrorSummary` | `role="alert"`, receives focus, list of links to `#field-id` / card ids. |
| `PlatformDetails` | Card per Post: header with human state (Ready / Details needed / Blocked / Checking), required fields visible, `More options` disclosure, autosave status line. |
| `TikTokDeclaration` | Text + links + one checkbox bound to `{fingerprint, version}`. |
| `ActionDialog` | Post detail confirmation for Publish now / Retry now / Reschedule / Edit schedule / Publish automatically: summary, date/time (when needed), TikTok declaration (when needed), remote-check acknowledgement only in Check result. |

## 7. Accessibility hooks

- Library grid and Posts lists: `<ul>`/`<li>`; each row/card is one `<a>` (Link).
- Calendar: `<section aria-label="Week of …">` → one `<section>` per day with `<h3>` and a
  `<ul>` of Posts; no `role=grid`.
- Status always `StatusBadge` (icon + text).
- Loading: `Skeleton` + `aria-busy`; errors: `ErrorState` + Retry.
- Result and autosave status changes announced via a polite live region.
