# Implementation Plan: Calendar & Scheduling Power Tools

**Branch**: `024-calendar-scheduling-tools` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/024-calendar-scheduling-tools/spec.md`

Companion artifacts: [research.md](research.md) (decisions R1–R15),
[contracts/api.md](contracts/api.md), [contracts/ui.md](contracts/ui.md),
[quickstart.md](quickstart.md). No `data-model.md`: there is no model, schema or migration
change (the only entity, `Publication`, is used as it is).

## Summary

Calendar becomes the place to reschedule Posts quickly and safely:

1. **Backend (P1, correctness)**: `PATCH /api/publications/{id}` runs its whole decision and
   all its writes inside the existing `write_transaction` (`BEGIN IMMEDIATE`, Feature 021).
   That removes the lost update against the scheduler claim; request, response and error
   codes stay the same (R1–R4).
2. **Quick Reschedule**: each reschedulable Calendar item gets a sibling control that opens the
   existing `ActionDialog` (*Edit schedule* for Scheduled, *Reschedule* for Missed/Failed).
   The dialog's current initial-value rule already gives the required preload (R5–R7).
3. **Drag between days** (week view ≥1280 px, `scheduled_automatic` / `scheduled_paused`
   only): native HTML5 drag & drop; the drop only opens *Edit schedule* with
   `initialAt` = target day + original local time, computed by a pure function (R8, R9, R11).
4. **Refresh and FR-042**: after success the shared Posts list is reloaded; `statesChanged`
   also compares `scheduled_at`, so the project overview ("Next: …") is reloaded through the
   existing signal (R10, R12).
5. **Focus and announcements** reuse the `Modal`'s opener restoration plus a small post-success
   focus step and a polite status line (R13).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript ~6.0 + React 19.2 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, Alembic; React Router 8.4,
`@radix-ui/react-dialog` 1.1.23. **No new dependencies** (no drag & drop library).

**Storage**: SQLite (journal mode, pysqlite timeout 5 s) + local filesystem. No migration.

**Testing**: pytest with the deterministic thread/event helpers of `tests/barriers.py`;
Vitest + Testing Library + jsdom with `FakeApi`.

**Target Platform**: local web app, single user; desktop browsers for drag, any browser
(including phones and touch) for Quick Reschedule.

**Project Type**: web application (`backend/` + `frontend/`).

**Performance Goals**: no measurable change. The PATCH holds SQLite's writer lock for its own
DB work (milliseconds), as other writers already do.

**Constraints**: no new endpoint, model, migration, store, cache, timezone persistence or DnD
library; scheduler interval, window, claim and publishing semantics unchanged; breakpoints
unchanged; `POST …/cancel` untouched.

**Scale/Scope**: one backend handler; ~6 frontend files; tests in 2 backend and 4 frontend
files.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Simplicidad y control de alcance | ✅ | Reuses `write_transaction`, `ActionDialog`, `IconButton`/`Button`, `usePostsData`, `Modal` focus return. Two optional props, three small pure functions. `/cancel` race registered, not fixed. |
| II. Spec-Driven Development | ✅ | Spec READY FOR PLANNING; it explicitly supersedes 019 FR-066's "read-only". |
| III. Arquitectura modular | ✅ | No platform logic enters the core; arming rules stay in each publisher. Calendar stays a view of the Posts list. |
| IV. Seguridad | ✅ | No secrets touched; the only keyring read (TikTok Inbox arming) is unchanged and already ran under the writer lock. Errors keep their safe messages. |
| V. Calidad y verificabilidad | ✅ | Deterministic race tests (no sleeps); targeted frontend tests; regression test for the lost update. A failed reschedule never loses the existing schedule (rollback). |
| VI. Git y trazabilidad | ✅ | Small checkpoints A–E; branch + PR (main unprotected, CI on PR). |
| Idioma | ✅ | Code, identifiers, UI copy and docs in English; Spec Kit artifacts in Spanish/English. |

No violations → no Complexity Tracking.

## Design

### Backend (checkpoint A)

`backend/app/publications.py::update_publication`:

- Dependencies: `session_factory: SessionFactoryDep` (`get_session_factory`, as in
  `library_folders.py`) in addition to the request `session`, `storage`, `clock`, `request`.
- Body: the current code, unchanged, inside
  `with write_transaction(session_factory) as tx:` using `tx` wherever it used `session`
  (`get_publication_or_404`, `ensure_editable(..., session=tx)`, `_related(tx, …)`,
  `_arming_problems(request, tx, …)`). The explicit `session.commit()` disappears: the context
  manager commits on success and rolls back on any exception (so every existing `raise`
  keeps its HTTP response).
- After the block: `publication = get_publication_or_404(session, id)` and
  `publication_read(session, publication, storage, clock)` with the request session (no
  pending writes there; reads the committed state).
- Nothing else changes: helpers, schema, claim, scheduler, runner, `/cancel`.

Why this is enough (R2): `BEGIN IMMEDIATE` is the first statement, so the read that feeds
`ensure_editable` and the final `UPDATE` happen under one writer lock. A claim that committed
earlier is seen (`publishing` → 409); a claim that comes later waits and re-checks its
conditions on the committed result. Two PATCHes serialize (last committed wins).

### Frontend

**`calendar.ts`** — pure helpers (unit-tested):

- `scheduleAction(post): "edit_schedule" | "reschedule" | null` (R6).
- `canDrag(post): boolean` — `scheduled_automatic` / `scheduled_paused` (R6).
- `moveToDay(scheduledAt, target, now): { at: string; kind: "source" | "valid" | "invalid" }`
  — local wall time preserved; month/year/DST by the browser's `Date` (R9).

**`ActionDialog.tsx`** — two optional props (R5, contracts/ui.md §3):

- `initialAt?: string` → initial `at` = `toDateTimeLocalValue(initialAt)` when given;
  otherwise today's rule (`edit_schedule` + future → current date; else empty).
- `onFailed?: () => void` → called in the existing `catch`, after the error is set.

Post detail keeps calling it exactly as today.

**`CalendarView.tsx`**:

- New props: `allPosts` (unfiltered list, for the dialog's guard), `paused`,
  `onChanged: () => Promise<void>` (`data.reload`).
- State: `dialog: { post, action, initialAt? } | null`, `drag: { postId, scheduledAt, now } |
  null`, `over: string | null`, `announcement: string`, `focusAfter: number | null`.
- `Day` renders each `<li>` as `<Link …/>` + `<ScheduleControl …/>` (sibling; IconButton in
  week view, ghost Button with text in agenda) when `scheduleAction(post)` is not null (R7).
- Week view only: draggable Links (`canDrag`) with `onDragStart`/`onDragEnd`; day sections
  with `onDragOver`/`onDrop`; `data-drop`, `data-drop-over`, `data-dragging` attributes
  (R8, contracts/ui.md §4). Drop re-validates against the current `posts` (R11), focuses the
  source link and opens `edit_schedule` with `initialAt`. No request on drop.
- An effect clears `drag` if the dragged Post left the list or stopped being draggable (R11).
- `onDone` → close dialog → `await onChanged()` → focus `[data-detail-id=<id>]` or the range
  heading (`tabIndex={-1}`) → announce (R13). `onFailed` → `void onChanged()`.
- A visually hidden `role="status"` paragraph holds the announcement.

**`PostsPage.tsx`** — passes `allPosts={posts ?? []}`, `paused`, `onChanged={data.reload}` to
`CalendarView`. Nothing else changes.

**`usePostsData.ts`** — `statesChanged` also returns true when a Post's `scheduled_at` differs
(R12). Polling cadence unchanged.

**`posts.css`** — only: the control's position in the card and the link's reserved space;
`[data-dragging]`, `[data-drop="valid"]`, `[data-drop-over]`, `[data-drop="invalid"]` and the
invalid-day hint; existing tokens only; no animation (R14).

### Docs

- `README.md`: Calendar paragraph — no longer "read-only": *Edit schedule* / *Reschedule* from
  Calendar and, on wide screens, dragging a scheduled Post to another day of the week.
- `docs/design-system.md`: Calendar line — drop-target feedback (outline + text, never colour
  alone).

## Testing strategy

Targeted per checkpoint; full suites only in PR CI (CLAUDE.md, quickstart.md).

**Backend** — new `backend/tests/test_publications_update_concurrency.py` (barriers, no
sleeps):

1. Claim wins: `FakePublisher.upload_gate` keeps the runner in `upload` (Post stays
   `publishing`, attempt `running`; released in a `finally`);
   `pause_before_commit(session_factory, is_claim)` holds the claim with its writes
   executed; PATCH in `Background`; `statement_reached(engine, "BEGIN IMMEDIATE")` confirms it
   waits; release → tick `started == [id]`, PATCH `409 publication_not_editable`, row
   `publishing`, one `running` attempt, `scheduled_at` unchanged.
2. Reschedule wins: PATCH paused inside its transaction by `pause_after_call` on
   `_set_consent` (new barrier helper; no `session.dirty` predicate, an autoflush can empty it); tick in `Background`; `statement_reached(engine, "UPDATE publications")` confirms
   the claim waits; release → PATCH 200 with the new date, tick `started == []`, no attempt.
3. Lost-update regression: PATCH paused right after its read (gate in `ensure_editable` via
   monkeypatch); tick in `Background`; release → never `scheduled` with a `running` attempt;
   either (PATCH 200 + not claimed) or (claim + 409), asserted as the deterministic outcome of
   the lock order.
4. Two concurrent valid PATCHes (second waits on `BEGIN IMMEDIATE`): both 200; the stored date
   is the second one.
5. Error contract preserved inside the transaction (parametrized): cancelled, published,
   publishing, awaiting user action, `check_result_first`, past date 422, inactive
   project/account, media unavailable, arming problem → same status/code as before and no row
   change. Most already exist in `test_publications_update.py`,
   `test_publications_states.py`, `test_auto_publish_consent.py`, `test_publish_arming.py`,
   `test_tiktok_consent.py`; they run unchanged as the regression set of checkpoint A. New
   cases only where a combination is missing (Missed reschedule armed; TikTok Direct Post
   arming without consent through PATCH).
6. `test_scheduler_concurrency.py::test_changes_during_the_preflight_prevent_the_start` stays
   green (PATCH during the claim's preflight).

**Frontend**:

- `calendar.test.ts`: `scheduleAction` and `canDrag` for all 11 states; `moveToDay` — same day,
  next day, Friday→Monday of the same week (past vs future week), month and year boundaries,
  today with past time, DST spring-forward and fall-back with `process.env.TZ` set in the test.
- `action-dialog.test.tsx`: `initialAt` preload; `onFailed` called on 409/422; existing cases
  unchanged.
- `calendar-view.test.tsx`:
  - week view and agenda: control present only for the 5 states, accessible name, Tab order;
  - Edit schedule on a future Scheduled → preloaded; past Scheduled → empty; Missed/Failed →
    *Reschedule* empty; titles;
  - nothing sent until confirm; cancel sends nothing and returns focus to the control;
  - success → list reloaded, Post on the new day, no ghost, focus on the Post (or range heading
    when it left the week), status announced;
  - 409 (Publishing meanwhile) / 422 → message in the dialog and the list reloaded;
  - drag (≥1280): valid day opens *Edit schedule* with the target date; past day and today with
    passed time → no dialog; same day → no dialog, no request; `dragend` clears feedback;
    non-draggable states do not set `draggable`; Post changed by a reload during the drag →
    drop ignored; drop → cancel → focus on the source link;
  - click and Enter on an item still open the detail; `data-detail-id` intact;
  - <1280: no `draggable`, controls present.
- `posts-data.test.ts`: `statesChanged` true when only `scheduled_at` changes; the overview
  callback fires after a reschedule.

No pixel tests.

## Checkpoints

Each leaves the branch coherent and green on its targeted tests.

| # | Scope | Targeted tests |
|---|---|---|
| **A — Backend atomicity** | `update_publication` in `write_transaction`; new concurrency test file; missing contract cases | new file + `test_publications_update.py`, `test_publications_states.py`, `test_auto_publish_consent.py`, `test_publish_arming.py`, `test_scheduler_concurrency.py` |
| **B — Quick Reschedule + refresh** | `scheduleAction`; `ActionDialog.initialAt` + `onFailed`; `CalendarView` control (week + agenda), dialog hosting, reload on success/error; `PostsPage` props; `statesChanged` + `scheduled_at` (FR-042) | `calendar.test.ts`, `action-dialog.test.tsx`, `calendar-view.test.tsx` (quick cases), `posts-data.test.ts` |
| **C — Desktop drag & drop** | `canDrag`, `moveToDay`; drag handlers (drop uses B's `initialAt`), re-validation, feedback attributes and CSS | `calendar.test.ts`, `calendar-view.test.tsx` (drag cases), `action-dialog.test.tsx` |
| **D — Focus & announcements** | post-success focus, drop opener focus, range heading target, status line | `calendar-view.test.tsx` (focus cases) |
| **E — Polish & close** | narrow-column layout with long titles, reduced motion, docs (README, design-system); static checks once; `git diff --check`; security review of the diff | lint, format, mypy, typecheck, build |

FR-042 moves into B (instead of D) because the success path of B already needs the reload, and
the fix is one comparison in the same hook.

## Project Structure

### Documentation (this feature)

```text
specs/024-calendar-scheduling-tools/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R15
├── contracts/
│   ├── api.md           # PATCH: unchanged shape + concurrency guarantee
│   └── ui.md            # Calendar UI contract
├── quickstart.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (files expected to change)

```text
backend/
├── app/publications.py                              # update_publication → write_transaction
└── tests/test_publications_update_concurrency.py    # new

frontend/src/pages/
├── PostsPage.tsx                 # props to CalendarView
└── posts/
    ├── calendar.ts               # scheduleAction, canDrag, moveToDay
    ├── CalendarView.tsx          # control, dialog, drag, focus, status
    ├── ActionDialog.tsx          # initialAt?, onFailed?
    ├── usePostsData.ts           # statesChanged + scheduled_at
    ├── posts.css                 # control position, drag/drop feedback
    ├── calendar.test.ts
    ├── calendar-view.test.tsx
    ├── action-dialog.test.tsx
    └── posts-data.test.ts

README.md, docs/design-system.md  # Calendar behaviour
```

**Structure Decision**: existing `backend/` + `frontend/` web layout; no new modules.

## Risks

| Level | Risk | Mitigation |
|---|---|---|
| HIGH | The PATCH is shared by Publish/Review, Post detail and Content by destination: a mistake in moving it into the transaction changes their behaviour | Body moved verbatim (session swap only); existing PATCH test files run unchanged in checkpoint A; error contract test |
| HIGH | Drag handlers break the item link (navigation, focus return, `aria-current`) | Link content/attributes untouched; drag attributes only on draggable Links in week view; click/Enter/focus tests |
| MEDIUM | Writer lock held during the TikTok Inbox keyring read when arming | Already the case today (autoflush); keyring failure is immediate; claim waits ≤ 5 s by driver timeout |
| MEDIUM | HTML5 DnD differences between browsers (link data, `dragend` after node removal) | `clearData` + custom type; state cleared on `dragend` and by an effect on the list; manual check in Chromium and Firefox |
| MEDIUM | Narrow week columns with long titles plus the control | Reserved space on the first row only; manual check at 1280 px |
| MEDIUM | `statesChanged` also used for the overview of any list change | `scheduled_at` changes only by edits; polling cadence unchanged |
| LOW | Scheduler not woken after a PATCH: a near reschedule may start up to one cycle (30 s) later, inside the window | Accepted by the spec |

## Open decisions

None. UI copy closed (2026-10-26):

- Invalid-day hint: "Can't move here — that time has already passed."
- Success announcement: "`<title> rescheduled for <when>.`"

## Post-design Constitution Check

Re-evaluated after Phase 1: unchanged, all ✅. No new dependency, model, endpoint or store; the
backend change reuses the 021 pattern; scope matches the spec.
