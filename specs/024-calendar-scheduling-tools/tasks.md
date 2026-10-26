---

description: "Task list for Feature 024 — Calendar & Scheduling Power Tools"
---

# Tasks: Calendar & Scheduling Power Tools

**Input**: Design documents from `specs/024-calendar-scheduling-tools/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[contracts/api.md](contracts/api.md), [contracts/ui.md](contracts/ui.md),
[quickstart.md](quickstart.md). No `data-model.md` (no model change).

**Tests**: required by the spec ("Testing requirements"). Tests are written first in each
checkpoint and must fail (or not exist yet) before the implementation tasks.

**Organization**: by checkpoint (A–E), which is the required technical order. Each checkpoint
maps to a user story:

| Checkpoint | User Story | Priority |
|---|---|---|
| A — Backend atomicity | US3 — Reprogramar sin riesgo frente al scheduler | P1 |
| B — Quick Reschedule | US1 — Quick Reschedule desde Calendar | P1 |
| C — Desktop drag & drop | US2 — Arrastrar un Post a otro día | P2 |
| D — Focus & accessibility | US1 + US2 (FR-060–FR-064) | P1/P2 |
| E — Polish, docs & final verification | cross-cutting | — |

A goes first although US1 is listed first in the spec: the backend correctness fix must exist
before Calendar makes rescheduling due Posts easy (plan.md, Checkpoints).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1, US2, US3 (spec.md)

## UI copy (closed)

- Invalid drop target: `Can't move here — that time has already passed.`
- Success announcement: `<title> rescheduled for <when>.` (`<when>` = `formatWhen(scheduled_at)`)

## Testing policy (CLAUDE.md)

Targeted tests only, once per checkpoint; no full backend/frontend suites locally (PR CI runs
them); static checks once, in E. Backend concurrency tests use `tests/barriers.py` (threads +
`threading.Event`), never `sleep`.

---

## Phase 1: Setup

**Purpose**: a known-green baseline of the tests the feature touches, so checkpoint
regressions are attributable.

- [X] T001 Run once, before any change, the existing targeted backend tests: `cd backend && uv run pytest tests/test_publications_update.py tests/test_publications_states.py tests/test_auto_publish_consent.py tests/test_publish_arming.py tests/test_tiktok_consent.py tests/test_scheduler_concurrency.py tests/test_write_transaction.py -q`; record the result (they are the regression set of checkpoint A)
- [ ] T002 [P] Run once, before any change, the existing targeted frontend tests: `cd frontend && npx vitest run src/pages/posts/calendar.test.ts src/pages/posts/calendar-view.test.tsx src/pages/posts/action-dialog.test.tsx src/pages/posts/posts-data.test.ts src/pages/posts/post-detail.test.tsx`; record the result

---

## Phase 2: Checkpoint A — Backend atomicity (US3, P1) 🎯 prerequisite

**Goal**: `PATCH /api/publications/{id}` decides and writes under one SQLite writer lock
(`write_transaction`, `BEGIN IMMEDIATE`), so it can never overwrite `publishing` after a
concurrent scheduler claim. Request, response and error codes unchanged
([contracts/api.md](contracts/api.md)).

**Independent Test**: the new concurrency tests pass deterministically in both race orders;
every existing PATCH test passes unchanged.

### Tests for Checkpoint A (write first)

- [X] T003 [US3] Create `backend/tests/test_publications_update_concurrency.py` with its fixtures: a due armed publication via `scheduled_publication(client, db_path, in_minutes(fake_clock, 0))` on `fake_scheduler_client` (FakePublisher), a far-future reschedule body `{"scheduled_at": "2100-01-01T10:00:00Z", "auto_publish_enabled": true}` (real `utc_now()` is used by `ensure_future`), helpers reading the row (`get_publication`, `attempt_rows`) and an `assert_no_scheduled_with_running_attempt(db_path)` invariant helper
- [X] T004 [US3] Add a context manager `pause_after_call(monkeypatch, module, name) -> Gate` to `backend/tests/barriers.py`: it wraps `module.name` so that its **first** call runs the original and then waits on the `Gate` (later calls pass through), and it always calls `gate.release()` on exit (even when an assertion fails). Used on `app.publications.ensure_editable` (pause right after the PATCH's read, inside `write_transaction`, i.e. after `BEGIN IMMEDIATE` holds the writer lock) and on `app.publications._set_consent` (pause after the PATCH's mutations, before arming checks and commit). No predicate on `session.dirty` (an autoflush can empty it)
- [X] T005 [US3] Test "claim wins" in `backend/tests/test_publications_update_concurrency.py`: set `fake_publisher.upload_gate = threading.Event()` (unset) so the runner stays in `upload` and the Post stays `publishing` with its attempt `running`; `pause_before_commit(session_factory, is_claim)` holds the claim with its `UPDATE`+`INSERT` executed (writer lock held); PATCH in `Background`; `statement_reached(engine, "BEGIN IMMEDIATE")` confirms the PATCH waits for the lock; release the claim → tick `started == [id]`; PATCH answers `409` code `publication_not_editable`; row still `publishing`, `scheduled_at`/`auto_publish_enabled` unchanged, exactly one attempt still `running` with the same id and stage; invariant holds. Release `upload_gate` and wait for the runner (`wait_idle`) in a `finally`
- [X] T006 [US3] Test "reschedule wins" in the same file: `pause_after_call(monkeypatch, app.publications, "_set_consent")` holds the PATCH inside its transaction (writer lock held since `BEGIN IMMEDIATE`, mutations done, not committed); tick in `Background`; `statement_reached(engine, "UPDATE publications")` confirms the claim's `UPDATE` is waiting for the lock; release → PATCH `200` with the new date (armed), tick `started == []`, no attempt row, invariant holds. Set `fake_publisher.upload_gate` as in T005 and release it in a `finally` so an unexpected start cannot finish behind the test
- [X] T007 [US3] Test "claim between the PATCH's read and write" (lost-update regression) in the same file: `pause_after_call(monkeypatch, app.publications, "ensure_editable")` holds the PATCH right after its read; tick in `Background`; `statement_reached(engine, "UPDATE publications")` confirms the claim competes; release → PATCH `200`, claim not started, no attempt, invariant holds; `fake_publisher.upload_gate` set and released in a `finally` as in T005. Docstring: before the fix, this window let the claim commit and the PATCH then wrote `scheduled` over `publishing`
- [X] T008 [US3] Test "two concurrent reschedules" in the same file: the first PATCH held by `pause_after_call(monkeypatch, app.publications, "ensure_editable")` (first call only); second PATCH in `Background`; `statement_reached(engine, "BEGIN IMMEDIATE")` confirms it waits; release → both `200`, stored `scheduled_at` is the second date, still armed
- [X] T009 [P] [US3] Add only the missing contract cases to existing files (check before adding): Missed (armed, past window) rescheduled to a future date returns `200` armed `scheduled_automatic` in `backend/tests/test_publications_update.py`; TikTok Direct Post armed through PATCH without a valid consent returns the existing arming code with no row change in `backend/tests/test_tiktok_consent.py`

### Implementation for Checkpoint A

- [X] T010 [US3] In `backend/app/publications.py::update_publication`: add `session_factory` (`Depends(get_session_factory)`, same alias pattern as `library_folders.py`), run the whole current body inside `with write_transaction(session_factory) as tx:` using `tx` everywhere it used `session` (`get_publication_or_404`, `ensure_editable(..., session=tx)`, `_related`, `_set_consent`, `_arming_problems`), remove the explicit `session.commit()` (the context manager commits/rolls back), and keep every `raise` unchanged
- [X] T011 [US3] In the same handler, build the response after the transaction with the request session: `publication_read(session, get_publication_or_404(session, publication_id), storage, clock)`; confirm the request session has no pending writes (021 usage rule in `backend/app/db.py::write_transaction`)
- [X] T012 [US3] Keyring / lock-scope verification (no refactor): list every operation now inside the transaction and confirm none is new external/slow I/O compared with today's autoflush path; confirm the TikTok Inbox `arming_problems` keyring read (`tiktok_inbox.inbox_problems` → `can_upload_to_inbox`) already ran under RESERVED before the change and is not worse; write the conclusion as a short comment in the PR notes. **If a significant NEW blocking operation appears, stop checkpoint A and report before redesigning**
- [X] T013 [US3] Run checkpoint A targeted tests: `cd backend && uv run pytest tests/test_publications_update_concurrency.py tests/test_publications_update.py tests/test_publications_states.py tests/test_auto_publish_consent.py tests/test_publish_arming.py tests/test_tiktok_consent.py tests/test_scheduler_concurrency.py tests/test_text_publications.py -q`

**⛔ STOP A — manual review**: the PATCH contract is exactly the previous one (request,
response, codes; diff limited to the session swap) and both race orders, the read/write window
and concurrent reschedules are covered. Logical commit: *A backend atomicity*.

---

## Phase 3: Checkpoint B — Quick Reschedule (US1, P1)

**Goal**: every reschedulable Post in Calendar (week view and agenda) has a sibling control
that opens the existing `ActionDialog` (*Edit schedule* for Scheduled, *Reschedule* for
Missed/Failed); success and errors reload the shared list; "Next: …" never keeps the old date
(FR-001–FR-007, FR-040–FR-043, FR-052).

**Independent Test**: without drag, reschedule a Post from Calendar on desktop and phone width
and see it on its new day, with the strip updated.

### Tests for Checkpoint B (write first)

- [ ] T014 [P] [US1] In `frontend/src/pages/posts/calendar.test.ts`: `scheduleAction` for all 11 display states (`edit_schedule` for `scheduled_automatic`/`scheduled_paused`/`scheduled_manual`, `reschedule` for `missed`/`failed`, `null` otherwise)
- [ ] T015 [P] [US1] In `frontend/src/pages/posts/action-dialog.test.tsx`: `initialAt` replaces the default initial value; without it the existing rule holds; `onFailed` is called after a 409 and a 422 and not after success; existing cases unchanged
- [ ] T016 [P] [US1] In `frontend/src/pages/posts/posts-data.test.ts`: `statesChanged` is true when only `scheduled_at` of a Post changes and false for identical lists; `usePostsData` calls `onStatusChange` exactly once after a reload that only changed a date, and not at all after a poll with no change (no reload loop)
- [ ] T017 [US1] In `frontend/src/pages/posts/calendar-view.test.tsx` (week view via `setViewport(1280)` and agenda): the control exists only for the 5 reschedulable states, as a sibling of the item link (not inside it), with the visible/accessible label `Edit schedule: <title>` / `Reschedule: <title>`; Needs review, Needs action, Publishing, Published have none
- [ ] T018 [US1] In `calendar-view.test.tsx`: dialog title and preload — future Scheduled → *Edit schedule* with its date; Scheduled whose date already passed (armed, in window) → *Edit schedule* empty; Missed and Failed → *Reschedule* empty; `scheduled_manual` → *Edit schedule* and the PATCH body is `{scheduled_at, auto_publish_enabled: true}`; `scheduled_paused` (automation paused) → *Edit schedule* shows the existing paused notice, can be confirmed, and the Post is still `scheduled_paused` afterwards; no request before confirm; Cancel sends nothing (`api.requests`)
- [ ] T019 [US1] In `calendar-view.test.tsx`: after confirm the list is reloaded and the Post is shown on its new day with nothing left on the old one; moving to another week removes it from the visible week
- [ ] T020 [US1] In `calendar-view.test.tsx`: a 409 `publication_not_editable` (Post became Publishing meanwhile) and a 422 past date show the existing message in the dialog and the list is reloaded (Post shown as Publishing in the 409 case)
- [ ] T021 [US1] FR-042 test in `calendar-view.test.tsx` (route-level render, so `ProjectLayout` owns the overview): count `GET /overview?project_id=<id>` in `api.requests` — after a successful *Edit schedule* and after a successful *Reschedule* from Calendar exactly **one** new overview request is made; after a poll with no change (advance fake timers by `AUTOMATION_POLL_INTERVAL_MS`) none is made. Do not assert the "Next: …" text (`FakeApi.overview()` returns `next_post: null`); `FakeApi` is not extended. Existing `frontend/src/pages/home.test.tsx` keeps loading Home's overview (run, no change expected)

### Implementation for Checkpoint B

- [ ] T022 [P] [US1] Add `scheduleAction(post)` to `frontend/src/pages/posts/calendar.ts` (research R6)
- [ ] T023 [P] [US1] Add optional props `initialAt?: string` (ISO; initial value `toDateTimeLocalValue(initialAt)`) and `onFailed?: () => void` (called in the existing `catch` after the error is set) to `frontend/src/pages/posts/ActionDialog.tsx`; Post detail untouched
- [ ] T024 [P] [US1] Extend `statesChanged` in `frontend/src/pages/posts/usePostsData.ts` to also compare `scheduled_at` per id; update its doc comment (FR-042, research R12)
- [ ] T025 [US1] Add props `allPosts`, `paused`, `onChanged: () => Promise<void>` to `CalendarView` in `frontend/src/pages/posts/CalendarView.tsx` and pass `allPosts={posts ?? []}`, `paused`, `onChanged={data.reload}` from `frontend/src/pages/PostsPage.tsx`
- [ ] T026 [US1] In `CalendarView.tsx`, render each `<li>` as the unchanged `<Link>` plus a sibling schedule control when `scheduleAction(post)` is not null: `IconButton` (`clock`) in week view, `Button variant="ghost"` with the visible label in agenda; accessible name `<Edit schedule|Reschedule>: <title>`
- [ ] T027 [US1] In `CalendarView.tsx`, host the dialog: state `{ post, action, initialAt? } | null`; render `ActionDialog` with `post`, `posts={allPosts}`, `paused`, `onClose`; `onDone` → close and `await onChanged()`; `onFailed` → `void onChanged()`
- [ ] T028 [US1] In `frontend/src/pages/posts/posts.css`: position the week-view control in the card's top-right corner with the link reserving that space on its first row; agenda control after the link; existing tokens only, 44 px target
- [ ] T029 [US1] Run checkpoint B targeted tests: `cd frontend && npx vitest run src/pages/posts/calendar.test.ts src/pages/posts/action-dialog.test.tsx src/pages/posts/posts-data.test.ts src/pages/posts/calendar-view.test.tsx src/pages/posts/post-detail.test.tsx src/pages/home.test.tsx`

**⛔ STOP B — manual review** (scratch instance per `quickstart.md`, backend + frontend left
running with the link): Quick Reschedule on desktop (week view) and on a phone-width window
(agenda, Sheet) before any drag work. Logical commit: *B quick reschedule*.

---

## Phase 4: Checkpoint C — Desktop drag & drop (US2, P2)

**Goal**: in the week view (≥1280 px) a `scheduled_automatic` / `scheduled_paused` Post can be
dragged to another day of the visible week; the drop only opens *Edit schedule* with target day
+ original local time; native HTML5 DnD, no library (FR-010–FR-021).

**Independent Test**: drag Tuesday 18:30 → Thursday, see *Edit schedule* with Thursday 18:30,
nothing sent until confirm; invalid/same-day/cancelled drags do nothing.

### Tests for Checkpoint C (write first)

- [ ] T030 [P] [US2] In `calendar.test.ts`: `canDrag` true only for `scheduled_automatic` and `scheduled_paused`
- [ ] T031 [P] [US2] In `calendar.test.ts`: `moveToDay` — same day → `source`; next day → `valid` with the same local hour/minute; Friday → Monday of the same week (past week `invalid`, future week `valid`); month boundary (e.g. 30 Oct → 2 Nov) and year boundary (31 Dec → 1 Jan); today with a passed time → `invalid`, today with a future time → `valid`; injected `now`
- [ ] T032 [P] [US2] In `calendar.test.ts`: DST with `process.env.TZ = "Europe/Madrid"` set and restored in the test — a 02:30 Post moved onto the spring-forward day yields the browser-normalized time; a fall-back day keeps a valid ISO; nothing else depends on the host time zone
- [ ] T033 [US2] In `calendar-view.test.tsx` (week view): `dragStart` on a draggable item with a fake `dataTransfer` (pattern of `library.test.tsx`) calls `clearData` and sets `application/x-autopublisher-post`; `dragOver` + `drop` on a valid day opens *Edit schedule* preloaded with the target date; no PATCH in `api.requests` until confirm; confirm sends `{scheduled_at, auto_publish_enabled: true}`
- [ ] T034 [US2] In `calendar-view.test.tsx`: drop on a past day and on today with a passed time → no dialog, no request; drop on the same day → no dialog, no request; `dragEnd` without drop (Escape / outside) clears `data-drop*` and `data-dragging`
- [ ] T035 [US2] In `calendar-view.test.tsx`: items in other states have no `draggable` and start no drag; below 1280 px (agenda) no item is draggable and no day has drop handlers
- [ ] T036 [US2] In `calendar-view.test.tsx`: the dragged Post changes (`scheduled_at` or state) or disappears through a list reload between `dragStart` and `drop` → the drop is ignored and the feedback cleared
- [ ] T037 [US2] In `calendar-view.test.tsx`: click and Enter on a draggable item still open the Post detail (Drawer), `data-detail-id` and `aria-current` intact

### Implementation for Checkpoint C

- [ ] T038 [P] [US2] Add `canDrag(post)` and `moveToDay(scheduledAt, target, now)` to `frontend/src/pages/posts/calendar.ts` (research R6, R9)
- [ ] T039 [US2] In `CalendarView.tsx` (week view only): `draggable` on Links where `canDrag`; `onDragStart` → `clearData()`, `setData("application/x-autopublisher-post", id)`, `effectAllowed = "move"`, state `drag = { postId, scheduledAt, now }`; `onDragEnd` → clear `drag` and `over`; non-draggable Links unchanged
- [ ] T040 [US2] In `CalendarView.tsx`: day sections get `onDragOver` (classify with `moveToDay`; `preventDefault` for `valid`/`source`; `dropEffect` `move`/`none`; update `over` only when it changes) and the attributes `data-drop="valid|invalid|source"` and `data-drop-over`; source item gets `data-dragging`
- [ ] T041 [US2] In `CalendarView.tsx`: `onDrop` re-validates against the current `posts` (present, `canDrag`, same `scheduled_at`, still `valid` with `new Date()`) and opens the dialog with `action: "edit_schedule"` and `initialAt`; never calls the API; plus an effect that clears `drag` when the dragged Post left the list or stopped being draggable (research R11)
- [ ] T042 [US2] In `CalendarView.tsx`: the invalid day under the pointer shows the visible text `Can't move here — that time has already passed.`
- [ ] T043 [US2] In `posts.css`: `[data-dragging]` (reduced opacity + dashed border), `[data-drop="valid"]` (dashed `--color-action` outline), `[data-drop-over]` (solid outline), `[data-drop="invalid"]` (`--color-surface-muted` background) and the hint; existing tokens only; no animation, transitions via `--motion-fast`
- [ ] T044 [US2] Run checkpoint C targeted tests: `cd frontend && npx vitest run src/pages/posts/calendar.test.ts src/pages/posts/calendar-view.test.tsx src/pages/posts/action-dialog.test.tsx`

**⛔ STOP C — manual drag review** (Chromium and Firefox, 1280 px): click vs drag, feedback of
valid/invalid/source days, same-day no-op, invalid day hint, Escape/cancel, long titles in
narrow columns. Logical commit: *C calendar drag and drop*.

---

## Phase 5: Checkpoint D — Focus & accessibility (US1 + US2)

**Goal**: predictable focus and announcements for every path; feedback never colour-only;
reduced motion respected; keyboard and touch flows intact (FR-044, FR-060–FR-064).

**Independent Test**: complete Quick Reschedule with keyboard only and with a screen reader
announcement; cancel and success paths land focus where contracts/ui.md §5 says.

### Tests for Checkpoint D (write first)

- [ ] T045 [US1] In `calendar-view.test.tsx`: Tab order per Post is link → schedule control; both focusable; control's accessible name as in T017; Quick Reschedule opened, cancelled with Escape → focus back on the control
- [ ] T046 [US2] In `calendar-view.test.tsx`: drop → dialog → Cancel → focus on the source item's link
- [ ] T047 [US1] In `calendar-view.test.tsx`: success with the Post still in the week → focus on its link (`[data-detail-id]`) in the new day; success moving it to another week → focus on the range heading; the `role="status"` region contains exactly `<title> rescheduled for <when>.`; **vanished opener**: open *Edit schedule* from Calendar, change the Post in `FakeApi` to `publishing` while the dialog is open, confirm → `409` shown in the dialog → the list reload removes the control that opened it → close the dialog → focus is on the range heading, never on `<body>`
- [ ] T048 [US1] In `calendar-view.test.tsx`: keyboard regression — Enter on an item opens the detail and closing it returns focus to the item; agenda: the control works with `userEvent` pointer (touch) input and the dialog is a Sheet below `md`

### Implementation for Checkpoint D

- [ ] T049 [US2] In `CalendarView.tsx`: before opening the dialog from a drop, focus the source link (`[data-detail-id=<id>]`) so the `Modal` (`frontend/src/ui/Dialog.tsx`) records it as opener
- [ ] T050 [US1] In `CalendarView.tsx`: range heading gets a ref and `tabIndex={-1}`; after `await onChanged()` on success, focus `[data-detail-id=<id>]` if present, else the heading (state `focusAfter` + effect after render). On close after an error, record the opener (control or source link) when the dialog opens and, in an effect that runs **after the dialog has unmounted**, focus the heading if that opener is no longer connected — do not rely only on the `Modal`'s implicit restoration (`frontend/src/ui/Dialog.tsx`), which does nothing when its opener is gone
- [ ] T051 [US1] In `CalendarView.tsx`: add a `<p role="status" className="ap-visually-hidden">` with `<title> rescheduled for <when>.` (`publicationTitle`, `formatWhen`) after success; do not reuse the range's `aria-live`
- [ ] T052 [US2] Verify in `posts.css` that valid/invalid/source differ by outline style and text, not colour alone; that no new animation exists and transitions use `--motion-fast` (0 under `prefers-reduced-motion`, `frontend/src/ui/tokens.css`); `:focus-visible` of the control uses the existing focus ring
- [ ] T053 [US1] Run checkpoint D targeted tests: `cd frontend && npx vitest run src/pages/posts/calendar-view.test.tsx src/pages/posts/post-detail.test.tsx`

**⛔ STOP D — keyboard / focus / accessibility review**: keyboard-only flow, focus after cancel
and success (visible and out of week), screen reader announcement, non-colour feedback,
reduced motion. Logical commit: *D focus/accessibility*.

---

## Phase 6: Checkpoint E — Polish, docs & final verification

**Purpose**: responsive and long-content polish, documentation, the single round of static
checks and the final approval.

- [ ] T054 Manual responsive check at 375 / 768 / 1024 / 1280 px on the scratch instance: long titles and destinations, narrow week columns with the control, no horizontal overflow; fix only in `frontend/src/pages/posts/posts.css`
- [ ] T055 Regression check of preserved contracts (contracts/ui.md §1): week navigation and `?week=` rewrite, filters `q`/`account`, Post detail as Drawer (md+) and page (phone), status indicators. Re-run `cd frontend && npx vitest run src/pages/posts/calendar-view.test.tsx src/pages/posts/posts.test.tsx src/routes.test.tsx` **only if** a `.ts`/`.tsx` file of the feature (those listed in plan.md "Source Code") changed after T053; CSS-only or docs-only changes do not require it
- [ ] T056 [P] Update `README.md` Calendar paragraph: remove "it is read-only"; describe *Edit schedule* / *Reschedule* from Calendar and dragging a scheduled Post to another day of the week on wide screens (the drop opens the dialog to confirm)
- [ ] T057 [P] Update `docs/design-system.md` Calendar line only if needed to document the drop-target feedback pattern (outline + text, never colour alone); otherwise leave it
- [ ] T058 Static checks once: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .`; `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`; `git diff --check`; and `git diff main --stat -- frontend/package.json frontend/package-lock.json` is empty (no dependency added for drag & drop, FR-021)
- [ ] T059 Security review of the diff: no secrets, tokens or private data; no new logging; error messages unchanged
- [ ] T060 Walk through `specs/024-calendar-scheduling-tools/quickstart.md` manual scenarios 1–6 on the scratch instance (backend + frontend left running, link shared)

**⛔ STOP E — final visual/functional approval by the user** before closing the feature and
opening the PR (full suites run in PR CI). Logical commit: *E final polish/docs*.

---

## Dependencies & Execution Order

### Checkpoint dependencies

- **Setup (T001–T002)** → **A (T003–T013)** → **B (T014–T029)** → **C (T030–T044)** →
  **D (T045–T053)** → **E (T054–T060)**.
- A is independent of the frontend but is required first by policy (correctness before
  interaction).
- C builds on B: the drop reuses B's dialog hosting, reload and `initialAt`.
- D refines B and C paths (focus after both).

### Within each checkpoint

- Tests first, then implementation, then the targeted run, then the STOP.
- A: T003 → T004 → T005–T008 (same file, sequential) ∥ T009 → T010 → T011 → T012 → T013.
- B: T014 ∥ T015 ∥ T016; T017–T021 (same file, sequential); T022 ∥ T023 ∥ T024 → T025 → T026
  → T027 → T028 → T029.
- C: T030 ∥ T031 ∥ T032; T033–T037 sequential; T038 → T039 → T040 → T041 → T042 → T043 →
  T044.
- D: T045–T048 sequential; T049 → T050 → T051 → T052 → T053.
- E: T054 → T055; T056 ∥ T057; T058 → T059 → T060.

### Critical path

T001 → T003 → T005 → T010 → T011 → T013 (A) → T017 → T025 → T026 → T027 → T029 (B) → T033 →
T039 → T040 → T041 → T044 (C) → T047 → T050 → T053 (D) → T058 → T060 (E).

## Parallel Opportunities

- T002 with T001 (backend vs frontend baseline).
- A: T009 (existing test files) with T005–T008 (new file).
- B: T014, T015, T016 (three test files); T022, T023, T024 (three source files).
- C: T030, T031, T032 can be written together but share `calendar.test.ts` — parallel only if
  split across authors; T038 independent of the `CalendarView.tsx` tests.
- E: T056 with T057.

### Parallel example — Checkpoint B

```text
T014 calendar.test.ts      — scheduleAction cases
T015 action-dialog.test.tsx — initialAt / onFailed
T016 posts-data.test.ts    — statesChanged + scheduled_at
then
T022 calendar.ts · T023 ActionDialog.tsx · T024 usePostsData.ts
```

## Implementation Strategy

1. **A** alone is shippable: it fixes a real race without any UI change.
2. **A + B** is the MVP: full rescheduling from Calendar on every device, no drag.
3. **C** adds the desktop shortcut on top of B.
4. **D** and **E** finish accessibility, polish and docs.

One logical commit per checkpoint (A–E), never one per task; branch + PR (CI runs the full
suites).

## Coverage

### User Stories → checkpoints

| Story | Tasks |
|---|---|
| US3 (P1) | T003–T013 |
| US1 (P1) | T014–T029, T045, T047, T048, T050, T051 |
| US2 (P2) | T030–T044, T046, T049, T052 |

### Functional Requirements → tasks

| FR | Tasks |
|---|---|
| FR-001, FR-002 | T014, T017, T022, T026 |
| FR-003 | T018, T023, T027 |
| FR-004 | T015, T018, T023 |
| FR-005 | T018, T027 |
| FR-006 | T017, T026 |
| FR-007 | T002, T015, T029 (post-detail tests) |
| FR-010, FR-011 | T030, T035, T038, T039 |
| FR-012, FR-013 | T031, T032, T038, T040 |
| FR-014, FR-015 | T031, T034, T040 |
| FR-016 | T033, T041 |
| FR-017 | T040, T042, T043, T052 |
| FR-018 | T034, T039 |
| FR-019 | T036, T041 |
| FR-020 | T033, T037, T039 |
| FR-021 | T039, T058 (`package.json` / lockfile unchanged) |
| FR-030–FR-033 | T005–T008, T010, T011 |
| FR-034, FR-035 | T009, T012, T013 |
| FR-036 | T010 (no endpoint/model/migration) |
| FR-040 | T019, T027 |
| FR-041 | T019 (detail reads the reloaded list), T055 |
| FR-042 | T016, T021 (one extra overview request; none on unchanged polls), T024 |
| FR-043 | T020, T023, T027 |
| FR-044 | T047, T051 |
| FR-050, FR-051 | T035, T055, T054 |
| FR-052 | T017, T048 |
| FR-060–FR-064 | T045–T052 (T047/T050: vanished-opener fallback) |

### Success Criteria

| SC | Verified by |
|---|---|
| SC-001 (≤3 interactions) | T018, T033, T060 |
| SC-002 (everything without drag) | T017, T048, T060 |
| SC-003 (no `scheduled` + running) | T005–T008 |
| SC-004 (no unconfirmed changes) | T018, T033, T034, T036 |
| SC-005 (Calendar matches backend) | T019, T020 |
| SC-006 (existing tests green) | T013, T029, T044, T053, PR CI |

## Notes

- Out of scope, no tasks: `/cancel`, hour grid, drag to another hour, touch drag, drag in
  agenda, drag between weeks, bulk, duplicate, recurring, timezone persistence, migrations,
  models, new endpoints, DnD library, scheduler wake changes, analytics.
- Manual checks always on a scratch instance (own `AUTOPUBLISHER_CONFIG`, failing keyring).
