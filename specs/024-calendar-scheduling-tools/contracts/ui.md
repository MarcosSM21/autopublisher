# UI contract — Calendar (Feature 024)

Extends the Calendar of Feature 019 (`contracts/ui.md` there) and the visuals of Feature 023.
Everything not listed here stays as it is.

## 1. Preserved (must not change)

- Route `/p/:projectId/posts[/:postId]?view=calendar&week=YYYY-MM-DD`; invalid/missing week is
  rewritten with `replace`; Previous week / Today / Next week; range heading; "Times in <zone>".
- Data: the Posts list of `usePostsData` (same request, same poller, same filters `q` and
  `account`). No Calendar-specific request.
- Week view from 1280 px (7 day sections, list by time, no hour grid); agenda below (only days
  with Posts). Breakpoints unchanged.
- Item: one `<Link>` to the Post detail with `data-detail-id`, `aria-current` when selected,
  time, title, destination, `StatusBadge`; click and Enter open the detail (Drawer from `md`,
  page on phones, `panelFrom="never"`); closing returns focus to the item.
- Drafts and Cancelled never shown; the moment of each Post (`calendarMoment`) unchanged.

## 2. Schedule action per Post

| `display_state` | Control | Opens | Draggable (week view) |
|---|---|---|---|
| `scheduled_automatic` | *Edit schedule* | `ActionDialog` `edit_schedule` | Yes |
| `scheduled_paused` | *Edit schedule* | `ActionDialog` `edit_schedule` | Yes |
| `scheduled_manual` | *Edit schedule* | `ActionDialog` `edit_schedule` | No |
| `missed` | *Reschedule* | `ActionDialog` `reschedule` | No |
| `failed` | *Reschedule* | `ActionDialog` `reschedule` | No |
| `needs_review`, `needs_action`, `publishing`, `published` | none | — | No |

- The control is a **sibling** of the item's `<Link>` inside the same `<li>` (never nested).
- Week view: `IconButton` (`clock`, 44×44) in the card's top-right corner; the link reserves
  that space on its first row. Agenda: `Button` `variant="ghost"` with the visible label.
- Accessible name: `"<Edit schedule|Reschedule>: <post title>"`. Tab order: link, then control.

## 3. `ActionDialog` (reused)

New optional props only; existing callers unchanged.

| Prop | Type | Meaning |
|---|---|---|
| `initialAt` | `string` (ISO instant), optional | Initial date and time; overrides the default (current date if future for `edit_schedule`, empty otherwise) |
| `onFailed` | `() => void`, optional | Called after an error is shown (Calendar reloads its list) |

Calendar passes: `action`, `post`, `posts` (the unfiltered list), `paused`, `onClose`, `onDone`,
and `initialAt` only after a drop. Title, copy, validation, TikTok declaration, Dialog/Sheet,
double-send guard and error mapping are the existing ones.

Initial value:

| Origin | Value |
|---|---|
| Quick, `scheduled_*` with future `scheduled_at` | current `scheduled_at` |
| Quick, `scheduled_*` with past `scheduled_at` | empty |
| Quick, `missed` / `failed` | empty |
| Drop of `scheduled_automatic` / `scheduled_paused` | target day + original local time |

## 4. Drag & drop (week view only)

- Source: the `<Link>` of a draggable Post (`draggable`); the browser's link data is replaced
  by `application/x-autopublisher-post` = post id; `effectAllowed = "move"`.
- Targets: the 7 day sections of the visible week. Classification per day, computed from the
  Post's `scheduled_at` and the current time:
  - `source` — the Post's own day: drop allowed, does nothing;
  - `valid` — target day + original local time is strictly in the future;
  - `invalid` — otherwise: drop not allowed (`dropEffect = "none"`).
- Feedback (attributes on the day section, styled with existing tokens):
  `data-drop="valid|invalid|source"` while dragging, `data-drop-over` on the day under the
  pointer, `data-dragging` on the source item. Invalid days under the pointer show the visible
  text "Can't move here — that time has already passed." Not colour alone; no new animation.
- Drop on a `valid` day: re-validate against the current list (Post still present, still
  draggable, same `scheduled_at`, still `valid`) → focus the source link → open
  `ActionDialog` `edit_schedule` with `initialAt`. **No request on drop.**
- `dragend`, Escape, drop outside: clear all drag state; nothing else.
- No drag in agenda, on phones or with touch; non-draggable links keep the browser default.

## 5. After the dialog

| Outcome | Calendar |
|---|---|
| Confirmed (200) | Close dialog → reload list → focus the Post's link in its new position, or the range heading if it left the week → polite status: "`<title> rescheduled for <when>.`" |
| Error (409/422/other) | Dialog stays open with the existing message → list reloaded in the background |
| Cancelled / closed | Nothing sent; focus back to the opener (control, or source link after a drop) |

## 6. Project summaries

After any list reload in which a Post's `scheduled_at` changed, the project overview is read
again (same signal as a visible state change), so "Next: …" in `ProjectStatusStrip` never shows
the old date. Home (`Up next`, projects list) reads its own overview when opened.
