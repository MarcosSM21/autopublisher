---

description: "Task list for Feature 026 — Brand & Motion Polish"
---

# Tasks: Brand & Motion Polish

**Input**: Design documents from `specs/026-brand-motion-polish/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md). No `data-model.md` and no
API contract: there is no model or API change.

**Tests**: required by the spec ("Testing and acceptance"). In each checkpoint, tests are written
first and must fail (or not exist yet) before the implementation tasks. Tests check state, DOM
attributes and classes, never frames or milliseconds.

**Organization**: by checkpoint (A–E), the required technical order. Story labels map tasks to
the spec's user stories:

| Checkpoint | User Stories | Priority |
|---|---|---|
| A — Motion foundation + Auth | US1, US5, US6 (+ foundation) | P1/P3 |
| B — Publishing feedback | US2 | P1 |
| C — Import highlight | US3 | P2 |
| D — Calendar reschedule highlight | US4 | P2 |
| E — Polish, docs & verification | cross-cutting | — |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US6 (spec.md).

## Closed decisions

- One new token only: `--motion-emphasis: 360ms` (0 ms with reduced motion). No
  `--motion-easing-emphasis`: `--motion-easing-out` is reused.
- Bounded motion: no new `infinite`. The pulse runs 3 cycles of `calc(var(--motion-emphasis) * 3)`
  (≈ 3.2 s); highlights last `calc(var(--motion-emphasis) * 4)` (≈ 1.4 s). `ap-spin` stays the
  only `infinite`.
- New keyframes use only `from` (or `50%` for the pulse) and no `forwards`: the end state is the
  natural style, so a leftover attribute is visually inert.
- Cleanup happens in `onAnimationEnd`, filtered by `animationName`. There is no timeout that
  duplicates a CSS duration (research R2).
- Auth loading copy stays exactly `Loading AutoPublisher…`.
- Published emphasis has two triggers (FR-020/020a):
  - (A) an observed `publishing → published` transition in any view;
  - (B) the Publish Results fast-path, only for posts of the current final action
    (`steps[id].run === "now"`, `status === "done"`, not yet `emphasized`) whose first state is
    `published`.

  (B) never applies outside `ResultsSection`.
- "Processing" gets the activity dot only in Publish Results (same `display_state: publishing`).
  `TikTokInboxDelivery` "Processing in TikTok" does not.

## Testing policy (CLAUDE.md)

- Targeted Vitest files only, once per checkpoint; never the full frontend suite locally.
- No backend tests: the backend does not change.
- Lint, format, typecheck and build only once, in E. Full suites only in PR CI.
- Tests use `renderRoute` (`frontend/src/test-utils.tsx`) and the fake API
  (`frontend/src/test-fake-api.ts`).
- jsdom runs no CSS and emits no `animationend`. Cleanup is tested with
  `fireEvent.animationEnd(el, { animationName })`.
- Real motion is checked over CDP in E: `getAnimations()`, reduced motion, touch emulation.

## Commit strategy

One commit per checkpoint, after its STOP is approved; no commit per task:

- A: `feat: add brand motion foundation and auth entrance`
- B: `feat: add publishing activity and published emphasis`
- C: `feat: highlight newly imported media`
- D: `feat: highlight rescheduled calendar posts`
- E: `docs: document brand and motion polish`, plus any polish

---

## Phase 1: Setup

- [X] T001 Confirm branch `026-brand-motion-polish`. Record that `frontend/package.json` and `frontend/package-lock.json` must stay unchanged (no new dependency, SC-010) and that `backend/` is out of scope.

---

## Phase 2: Checkpoint A — Motion foundation + Auth (US1, US5, US6) 🎯 foundation

**Goal**: the motion token and the bounded policy; a branded, non-blocking Login and Auth
loading with the static glow; the favicon; the touch hover guard. Auth complete and stable.

**Independent test**: open the app without a session. The branded loading appears, then Login
with entrance. The password field has focus and typing plus Enter submits at once. The tab shows
the monogram. On touch, cards do not stay lifted.

### Tests for A (write first)

- [X] T002 [P] Create `frontend/src/ui/motion-policy.test.ts`, reading every `src/**/*.css` with `import.meta.glob(..., { query: "?raw" })` (same technique as `storage-safety.test.tsx`). Assert:
  - `infinite` appears only in the `ap-spin` rule (FR-005a, SC-007a);
  - `--motion-emphasis` is defined in `ui/tokens.css` and set to `0ms` inside its `prefers-reduced-motion: reduce` block, and the global `animation-duration`/`iteration-count` override is still present (FR-038);
  - `gradient(` appears only in `pages/login/login.css` (FR-008);
  - the `.ap-media-card:hover` and `.ap-home-tile:hover` lift rules appear only inside `@media (hover: hover) and (pointer: fine)`, and `.ap-media-card:focus-visible` keeps the lift outside it (FR-036, FR-037).
- [X] T003 [US5] Extend `frontend/src/ui/motion-policy.test.ts`: `frontend/index.html` (raw import) has `<link rel="icon" type="image/svg+xml" href="/favicon.svg">`, and `frontend/public/favicon.svg` exists with the monogram colours `#42634e` and `#f6f5f1` (FR-034).
- [X] T004 [P] [US1] Extend `frontend/src/auth.test.tsx`:
  - while the session loads, both the app gate and `/login` render one `role="status"` with the exact text `Loading AutoPublisher…` and an `.ap-mark` with `aria-hidden="true"` (FR-012, FR-014);
  - the session error (`Couldn't reach AutoPublisher` + Retry) is unchanged and renders no `.ap-auth-loading__mark`.
- [X] T005 [P] [US1] Extend `frontend/src/pages/login/login.test.tsx`:
  - the `h1#login-title` still names the form;
  - its `.ap-mark` is `aria-hidden`;
  - the password input has focus right after render (`document.activeElement`), with no timers advanced;
  - typing and pressing Enter at once calls login, with no wait (FR-009–FR-011, SC-001, SC-008).

### Implementation for A

- [X] T006 Add `--motion-emphasis: 360ms` (with a comment: brand entrance, success and highlights only), set to `0ms` in the reduced-motion block, plus the semantic token `--color-auth-glow: rgb(66 99 78 / 0.28)` in `frontend/src/ui/tokens.css` (FR-001, FR-002, FR-006).
- [X] T007 Add `@keyframes ap-pulse` (`50% { opacity: 0.35 }`, ends at the natural style) with a comment stating the bounded policy (3 iterations, no `infinite`, < 5 s) in `frontend/src/ui/ui.css` (FR-005a, FR-013).
- [X] T008 [P] [US6] Split `.ap-media-card:hover, .ap-media-card:focus-visible`: `:focus-visible` keeps the lift everywhere, and `:hover` moves into `@media (hover: hover) and (pointer: fine)` with the same values, in `frontend/src/pages/library/library.css` (FR-036, FR-037).
- [X] T009 [P] [US6] Move `.ap-home-tile:hover` into `@media (hover: hover) and (pointer: fine)` with the same values in `frontend/src/pages/home/home.css` (FR-036).
- [X] T010 [P] [US5] Create `frontend/public/favicon.svg`: a `viewBox 0 0 32 32` rect with `rx=8` in `#42634e` and a bar at `x=13.4 y=8 w=10.6 h=16 rx=1` in `#f6f5f1` (the monogram's proportions, research R12) (FR-034, FR-035).
- [X] T011 [US5] Add `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />` in `frontend/index.html`.
- [X] T012 [US1] Create `frontend/src/shell/AuthLoading.tsx`: `<p className="ap-auth-loading" role="status">` with `<span className="ap-mark ap-auth-loading__mark" aria-hidden="true" />` and `<span>Loading AutoPublisher…</span>` (contract §2).
- [X] T013 [US1] Use `AuthLoading` for the loading state in `frontend/src/shell/AuthGate.tsx`; the error branch stays as it is.
- [X] T014 [US1] Use `AuthLoading` for the loading state in `frontend/src/pages/login/LoginPage.tsx`. No change to `handleSubmit`, `autoFocus`, `<Navigate>` or the error `role="alert"`.
- [X] T015 [US1] In `frontend/src/pages/login/login.css`:
  - the static glow: a `radial-gradient(... at 50% 30%, var(--color-auth-glow), transparent 70%)` layer over `var(--color-sidebar)` on `.ap-login, .ap-auth-loading`, with a comment marking it as the only gradient exception;
  - `.ap-login__card` with `ap-rise-in var(--motion-emphasis) var(--motion-easing-out)`;
  - `@keyframes ap-mark-bar` (`from { scale: 0 1 }`), applied to `.ap-login__title .ap-mark::after` with `transform-origin: left center`;
  - the `.ap-auth-loading` column layout and `.ap-auth-loading__mark` (≈ 2.5 rem, `ap-pulse calc(var(--motion-emphasis) * 3) ease-in-out 3`).

  No motion on the error frame (FR-006–FR-013).
- [X] T016 Run the targeted A tests: `npx vitest run src/ui/motion-policy.test.ts src/auth.test.tsx src/pages/login/login.test.tsx src/shell/shell.test.tsx`. Fix until green.

**⛔ STOP A — Auth and foundation review** (scratch instance per `quickstart.md`, servers
running):
- quickstart scenarios 1, 2, 7 and 8 at 375 and 1280, normal and reduced motion;
- `getAnimations()` shows `ap-rise-in`/`ap-mark-bar` with 1 iteration and `ap-pulse` with 3, and no new `Infinity`;
- focus is in the password field from the first frame;
- the glow is legible.

Commit A after approval.

---

## Phase 3: Checkpoint B — Publishing feedback (US2) ⚠️ highest risk

**Goal**: every badge of the real `publishing` state shows a bounded activity dot. Published is
emphasised once, only on an observed transition (A) or on the Publish Results fast-path (B).

**Independent test**: publish a post and watch Publish Results and Post detail: dot while
publishing, then one emphasis on Published. Reload: static Published.

### Tests for B (write first)

- [ ] T017 [P] [US2] Create `frontend/src/ui/published-emphasis.test.tsx` for the general rule (via A), rendering `StatusBadge` with `rerender`:
  - **Case 1**: mount with `published` → no `data-emphasis`.
  - **Case 2**: `publishing` → `published` → `data-emphasis` present once.
  - **Case 4**: then `published` → `published` (poll) → no new `data-emphasis` after cleanup.
  - **Case 5**: unmount and mount again with `published` → none.
  - **Case 6**: `publishing` → `failed`, `needs_action`, `needs_review`, `missed`, `cancelled` → none.
- [ ] T018 [US2] Extend `frontend/src/ui/published-emphasis.test.tsx` with cleanup and structure:
  - `fireEvent.animationEnd(badge, { animationName: "ap-badge-emphasis" })` removes `data-emphasis`;
  - an `animationend` named `ap-pulse` (bubbling from the dot) does not;
  - with no `animationend` at all, the attribute stays but the badge text, icon and tone are unchanged (inert leftover, research R2);
  - `StatusBadge` for `account`/`platform` never gets activity or emphasis.
- [ ] T019 [US2] Extend `frontend/src/ui/published-emphasis.test.tsx` with the activity indicator:
  - for every `PostDisplayState`, only `publishing` renders `.ap-badge__activity` with `aria-hidden="true"` and `data-activity` on the badge;
  - the label `Publishing` and the clock icon are unchanged;
  - no `role`, `aria-live` or focus change is added (FR-015–FR-018).
- [ ] T020 [US2] Extend `frontend/src/ui/published-emphasis.test.tsx` with `ResultsSection` rendered directly (MemoryRouter, props `rows`, `steps`, `onEmphasisShown`):
  - **Case 3 (fast-path)**: a row mounted already `published` with `steps[id] = { run: "now", status: "done" }` gets `data-emphasis` once and calls `onEmphasisShown(id)` once.
  - Fast-path negatives:
    - the same row with `steps[id].emphasized = true` (remount) → none;
    - `steps` empty (reload, or the post is not in the current operation) → none;
    - `run: "schedule"` → none;
    - `status: "error"` → none.
  - A Results row going `publishing` → `published` (via A) also calls `onEmphasisShown`.
  - A row whose outcome is `publishing` with `latest_attempt.stage` `processing`/`finalizing` (label `Processing`) has the activity dot; the aggregate `aria-live` text is unchanged.
- [ ] T021 [P] [US2] Extend `frontend/src/pages/publish/usePublishTask.test.tsx`:
  - `emphasis_shown` sets `steps[id].emphasized = true` and is a no-op for an unknown id;
  - `run_start` resets `steps` (a new operation is eligible again);
  - nothing is written to browser storage.
- [ ] T022 [P] [US2] Extend `frontend/src/pages/publish/final-action.test.tsx` with an integration case: "Publish now" whose fake API answers the post already `published` → its Results row has `data-emphasis`. After `animationEnd` and a re-render of the task, there is none. Results focus and the aggregate announcement are unchanged.

### Implementation for B

- [ ] T023 [US2] Re-check the `publishing` inventory against the code (research R6). The `StatusBadge` consumers are `PostRow`, `CalendarView`, `StatusActionPanel`, `UpNext`, `AttentionList` and `MediaUsage`; `ResultsSection` uses `Badge` directly. Confirm that `DailyList` "Publishing now", `publish/destinations.ts`, `PostWhen`, `CheckResultDialog` and `TikTokInboxDelivery` are text or another process and stay untouched. Update `research.md` R6 only if the code differs.
- [ ] T024 [US2] In `frontend/src/ui/ui.css`:
  - `.ap-badge` gets `position: relative`;
  - `.ap-badge__activity` is a ~6 px solid dot in `--status-active-solid`, absolutely positioned over the icon corner (no width change), with `ap-pulse calc(var(--motion-emphasis) * 3) ease-in-out 3`;
  - `@keyframes ap-badge-emphasis` (`from { scale: 0.9; box-shadow: 0 0 0 0.375rem var(--color-focus-ring-soft); }`);
  - `.ap-badge[data-emphasis]` with `animation: ap-badge-emphasis var(--motion-emphasis) var(--motion-easing-out)` (FR-016, FR-020, FR-024).
- [ ] T025 [US2] Add the optional props `activity`, `emphasis` and `onEmphasisEnd` to `frontend/src/ui/Badge.tsx`:
  - the dot is `aria-hidden`; `data-activity`/`data-emphasis` go on the root;
  - `onAnimationEnd` calls `onEmphasisEnd` only when `event.animationName === "ap-badge-emphasis"`.

  Default behaviour is unchanged.
- [ ] T026 [US2] Create `frontend/src/ui/usePublishedEmphasis.ts`: `(displayState, options?: { initiallyEmphasized?: boolean }) → { emphasis, onEmphasisEnd }`, using state derived during render (the `Flash` pattern).
  - Mount = initialisation; `emphasis` starts `true` only if `initiallyEmphasized && displayState === "published"`.
  - On a state change: `emphasis = previous === "publishing" && current === "published"`.
  - No storage and no effects for detection (FR-020–FR-023).
- [ ] T027 [US2] In `frontend/src/ui/StatusBadge.tsx`, the `post` variant passes `activity={post === "publishing"}` and the emphasis from `usePublishedEmphasis(post)`, **without** `initiallyEmphasized`. The `account`/`platform` variants are unchanged (FR-015, FR-020 A).
- [ ] T028 [US2] In `frontend/src/pages/publish/usePublishTask.ts`:
  - `PostStep` gets `emphasized?: boolean`;
  - add the reducer action `{ type: "emphasis_shown"; id }` that sets it when the step exists;
  - expose `emphasisShown(id)` on the controller;
  - `run_start` keeps resetting `steps` (FR-020a).
- [ ] T029 [US2] In `frontend/src/pages/publish/review/ResultsSection.tsx`:
  - add a local `ResultBadge` (post, view, step, onEmphasisShown):
    - `activity = view.outcome === "publishing"`;
    - `initiallyEmphasized = step?.run === "now" && step.status === "done" && !step.emphasized`;
    - `usePublishedEmphasis(post.display_state, { initiallyEmphasized })`;
    - a `useEffect` calls `onEmphasisShown(post.id)` once when `emphasis` becomes true;
  - add the `onEmphasisShown` prop.

  Labels, the aggregate `aria-live`, focus and links are unchanged.
- [ ] T030 [US2] Pass `onEmphasisShown={task.emphasisShown}` to `ResultsSection` in `frontend/src/pages/publish/review/TaskView.tsx`.
- [ ] T031 [US2] Run the targeted B tests: `npx vitest run src/ui/published-emphasis.test.tsx src/pages/publish/usePublishTask.test.tsx src/pages/publish/final-action.test.tsx src/pages/publish/review.test.tsx src/pages/posts/post-detail.test.tsx src/pages/posts/posts.test.tsx src/pages/home.test.tsx src/pages/library/media-usage.test.tsx`. These are the direct `StatusBadge` consumers; run them only for the DOM risk. Fix until green.

**⛔ STOP B — Published false-positive review** (servers running; quickstart scenarios 3, 4 and
4b with Fetch interception, normal and reduced motion):
- no emphasis on initial Published in Posts, History, Calendar, Home, Post detail or Media detail;
- the fast-path only in Publish Results, and only for posts of the current action;
- no repetition on polls, remount or reload;
- `publishing` → `failed` shows no emphasis;
- the dot's pulse ends (`playState: finished`) in < 5 s;
- with reduced motion: a static dot and a plain Published badge.

Commit B after approval.

---

## Phase 4: Checkpoint C — Import highlight (US3)

**Goal**: after an import, the cards of the Media created by that operation and visible in the
current view get one temporary highlight.

**Independent test**: import 2 valid files and 1 duplicate into a folder with Media: only the 2
new cards are highlighted; filters, selection and focus are unchanged.

### Tests for C (write first)

- [ ] T032 [P] [US3] Create `frontend/src/pages/library/import-highlight.test.tsx` (folder view, fake API):
  - after an import with `imported` + `duplicate` + `rejected` results and one file that fails with an API error, only the `imported` ids' cards have `data-just-imported`;
  - the duplicate's existing Media and the earlier Media have none;
  - the import panel and its `role="status"` summary are unchanged (FR-025, FR-026, FR-029).
- [ ] T033 [US3] Extend `frontend/src/pages/library/import-highlight.test.tsx`:
  - with an active filter that hides one imported Media, it is not shown, the URL query is unchanged and no hidden id is marked;
  - changing search or a filter after the import removes every `data-just-imported`;
  - a later reload from Move/Delete does not re-add it;
  - **late-highlight guard**:
    1. import a Media that the active `q` hides;
    2. it has no attribute;
    3. another reload happens with exactly the same query (for example, editing its title in the detail so it matches `q`);
    4. it becomes visible and still has no `data-just-imported`;
  - `fireEvent.animationEnd(card, { animationName: "ap-highlight" })` removes that card's attribute only;
  - focus and selection are unchanged;
  - importing from the Library root (`LibraryRoot`) marks nothing (FR-027, FR-028).

### Implementation for C

- [ ] T034 [US3] In `frontend/src/pages/library/useMediaImport.ts`, collect the `content.id` of the results with `status === "imported" && content !== null` during the loop and call `onImported(importedIds)`. Duplicate, rejected, per-file errors and stopped imports add no ids.
- [ ] T035 [P] [US3] Adapt the `onImported` callback in `frontend/src/pages/library/LibraryRoot.tsx` to the new signature, ignoring the ids (the root has no grid).
- [ ] T036 [US3] In `frontend/src/pages/library/MediaView.tsx`:
  - add the state `justImported: { ids: ReadonlySet<number>; key: string; loadedAt: number } | null` and a ref with the current key (scope + `selectionKey(query)`);
  - make `load()` resolve with the `loadedAt` of the snapshot it set;
  - on import completion, `const loadedAt = await load()` and then, if there are ids, set `{ ids, key: keyRef.current, loadedAt }`;
  - derive the marked ids as `key === currentKey && loadedAt === loaded.loadedAt ? ids ∩ visibleIds : ∅`, so any later reload invalidates them;
  - add a `clearImported(id)` that removes one id and resets to `null` when empty (contract §4).
- [ ] T037 [US3] Thread the marked ids and `onHighlightEnd` through `frontend/src/pages/library/MediaGrid.tsx` to `frontend/src/pages/library/MediaCard.tsx`, which sets `data-just-imported` on `a.ap-media-card` and calls `onHighlightEnd` on `animationend` named `ap-highlight`. Selection, `aria-current` and the menu are unchanged.
- [ ] T038 [US3] Add `@keyframes ap-highlight` (`from { box-shadow: 0 0 0 3px var(--color-action), 0 0 0 7px var(--color-focus-ring-soft); }`) to `frontend/src/ui/ui.css`, shared with D. Add `.ap-media-card[data-just-imported] { animation: ap-highlight calc(var(--motion-emphasis) * 4) var(--motion-easing-out); }` to `frontend/src/pages/library/library.css` (FR-025, FR-028).
- [ ] T039 [US3] Run the targeted C tests: `npx vitest run src/pages/library/import-highlight.test.tsx src/pages/library/library.test.tsx src/pages/library/search-filters.test.tsx`. Fix until green.

**⛔ STOP C — Import review** (servers running; quickstart scenario 5 at 375 and 1280, normal
and reduced motion):
- only the new cards are highlighted;
- hidden Media are not forced;
- no layout shift or scroll;
- every `data-just-imported` is gone after ~2 s.

Commit C after approval.

---

## Phase 5: Checkpoint D — Calendar reschedule highlight (US4)

**Goal**: after a confirmed reschedule, the item is highlighted once at its new position. The
focus and announcement of Feature 024 stay identical.

**Independent test**: reschedule a post to another visible day, by dialog and by drag: a brief
highlight on the new day, same focus and announcement. Cancel: nothing.

### Tests for D (write first)

- [ ] T040 [P] [US4] Extend `frontend/src/pages/posts/calendar-view.test.tsx`:
  - a successful reschedule by dialog to another visible day sets `data-just-rescheduled` on that post's `a.ap-calendar-item` in its new day (week view at 1280 and agenda);
  - focus lands on the same element as before the feature and the `role="status"` text is the same;
  - `fireEvent.animationEnd(item, { animationName: "ap-highlight" })` removes the attribute (FR-030–FR-032).
- [ ] T041 [US4] Extend `frontend/src/pages/posts/calendar-view.test.tsx` with the negatives:
  - Cancel;
  - a failed save (409 and generic error);
  - a save with the same `scheduled_at`;
  - a new date outside the visible week, then navigating to the destination week by URL (`?week=`) and by Back/Forward → no late highlight;
  - navigating to another week after a successful in-week reschedule, then back → no attribute;
  - opening another dialog.

  All leave no `data-just-rescheduled`. The drag attributes (`data-drop`, `data-dragging`) are unchanged (FR-033, FR-051).

### Implementation for D

- [ ] T042 [US4] In `frontend/src/pages/posts/CalendarView.tsx`:
  - add the state `landed: { id: number; week: string } | null`;
  - in the existing `onDone`, after `await onChanged()`, the `rescheduled.current` assignment and `setAnnouncement`, call `setLanded({ id: result.id, week })` only if `result.scheduled_at !== scheduling.post.scheduled_at` **and** the new date falls within the visible week;
  - reset it in `openDialog`;
  - set `data-just-rescheduled` on the item link only when `landed?.id === post.id && landed.week === week` (so any week change invalidates it without a handler), with `onAnimationEnd` (`ap-highlight`) → `setLanded(null)`;
  - leave `focusAfterDialog`, `rescheduled`, the announcement and the drag handlers untouched.
- [ ] T043 [US4] Add `.ap-calendar-item[data-just-rescheduled] { animation: ap-highlight calc(var(--motion-emphasis) * 4) var(--motion-easing-out); }` to `frontend/src/pages/posts/posts.css`, without touching the drag rules ("no animation") (FR-031).
- [ ] T044 [US4] Run the targeted D tests: `npx vitest run src/pages/posts/calendar-view.test.tsx src/pages/posts/action-dialog.test.tsx`. Fix until green.

**⛔ STOP D — Calendar review** (servers running; quickstart scenario 6: week view at 1280 by
dialog and drag, agenda at 375, normal and reduced motion):
- the highlight is at the new position;
- focus and announcement are as in 024;
- no highlight on cancel or outside the range;
- no geometry movement.

Commit D after approval.

---

## Phase 6: Checkpoint E — Polish, docs & verification

**Purpose**: documentation, full visual verification and static checks, once.

- [ ] T045 [P] Update `docs/design-system.md` (FR-053):
  - the Motion table: fast, medium and **emphasis** with their uses;
  - the bounded policy (no new `infinite`, < 5 s, static end state) and the allowed properties;
  - reduced-motion behaviour for new animations;
  - `animationend` cleanup;
  - the Login/Auth glow as the only gradient exception (contrast table rows for the glow);
  - the hover guard;
  - "Rejected → gradients" annotated with the exception.
- [ ] T046 [P] Note in `docs/design-system.md` ("Known issues") the pre-existing Flash live-region problem as future maintenance, with no code change (FR-052).
- [ ] T047 CDP review, normal motion (quickstart scenarios 1–8) at 375, 390, 768, 1280 and 1440:
  - Login, Auth loading, session error, Publishing (Posts, Post detail, Calendar week/agenda, Home, Media detail, Publish Results), Published (A and fast-path), import highlight, Calendar highlight;
  - `scrollWidth <= innerWidth` everywhere (SC-009).
- [ ] T048 CDP review with `prefers-reduced-motion: reduce` (quickstart scenario 9):
  - every state is readable and there is no perceptible movement;
  - `document.querySelectorAll('[data-emphasis],[data-just-imported],[data-just-rescheduled]')` is empty after the events settle (cleanup still fires);
  - `getAnimations()` has no new `Infinity` (SC-007, SC-007a).
- [ ] T049 CDP touch emulation (`mobile: true` + touch): `matchMedia('(hover: hover) and (pointer: fine)')` is `false`, and after tapping a Media card and a Home tile the computed `translate` is `none`. At 1280 with the mouse the lift is as before, and keyboard focus still lifts the card (SC-011).
- [ ] T050 Build the frontend and check that `GET /favicon.svg` returns 200 from the backend-served `frontend/dist` on the scratch instance and that the tab shows the monogram (US5).
- [ ] T051 Run the static checks once: `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`, and `git diff --check`. Confirm `package.json`/`package-lock.json` are unchanged (SC-010).
- [ ] T052 Review the diff for security and scope: no secrets, no browser storage (the existing `storage-safety.test.tsx` still passes if touched files require it), no backend change, nothing in Flash, Home entrance, empty states, TopBar, skeletons, page transitions or drag motion (FR-047–FR-052).
- [ ] T053 Set `spec.md` **Status** to implemented with the date, and tick the completed tasks in `tasks.md`.

**⛔ STOP E — final visual and functional approval by the user**, before the commit and PR.
Commit E after approval; then push the branch and open the PR (CI runs the full suites).

---

## Dependencies & Execution Order

- **Setup (T001)** → **A** → B, C and D → **E**.
- B, C and D all depend on A (the token and `ap-pulse`). D depends on C only for the shared
  `ap-highlight` keyframe (T038). If D runs before C, T043 adds the keyframe instead.
- Inside each checkpoint: tests first (they must fail), then implementation, then the targeted
  run, then the STOP, then the commit.

Critical path:

```text
T001 → T002–T005 → T006–T015 → T016 (STOP A) → T017–T022 → T023–T030 → T031 (STOP B)
→ T032–T033 → T034–T038 → T039 (STOP C) → T040–T041 → T042–T043 → T044 (STOP D)
→ T045–T052 → T053 (STOP E)
```

## Parallel Opportunities

- **A**:
  - tests T002 ∥ T004 ∥ T005 (T003 follows T002, same file);
  - implementation T008 ∥ T009 ∥ T010;
  - T012–T015 sequential (Auth files).
- **B**: T017 (then T018–T020, same file) ∥ T021 ∥ T022. The implementation is sequential
  (Badge → hook → consumers).
- **C**: T032 → T033 (same file); T035 ∥ T034.
- **D**: T040 → T041 (same file).
- **E**: T045 ∥ T046; the CDP tasks T047–T050 can share one session.

## Implementation Strategy

- **MVP**: A (US1 + US5 + US6) and B (US2), the two P1 moments. They can be delivered after STOP B.
- C and D are independent P2 increments, each with its own STOP and commit.
- E closes with docs and the only full verification and static checks.

## Coverage

### User Stories → checkpoints

| Story | Tasks |
|---|---|
| US1 Login/Auth (P1) | T004, T005, T006, T007, T012–T016, STOP A, T047, T048 |
| US2 Publishing/Published (P1) | T017–T031, STOP B, T047, T048 |
| US3 Import highlight (P2) | T032–T039, STOP C, T047, T048 |
| US4 Calendar highlight (P2) | T040–T044, STOP D, T047, T048 |
| US5 Favicon (P3) | T003, T010, T011, T050 |
| US6 Hover guard (P3) | T002, T008, T009, T049 |

### FR → tasks

| FR | Tasks |
|---|---|
| FR-001–FR-004 (tokens, emphasis use, properties) | T006, T007, T024, T038, T045 |
| FR-005, FR-005a (non-blocking, bounded) | T002, T005, T007, T024, T048 |
| FR-006–FR-008 (glow) | T002, T006, T015, T045, T047 |
| FR-009–FR-011 (Login entrance) | T005, T015 |
| FR-012–FR-014 (Auth loading) | T004, T012–T015 |
| FR-015, FR-015a (activity, Processing) | T019, T020, T023, T024, T025, T027, T029 |
| FR-016–FR-019 (indicator form, a11y, 2.2.2) | T019, T024, T025, T048 |
| FR-020 A (observed transition) | T017, T018, T026, T027 |
| FR-020a / FR-020 B (fast-path) | T020, T021, T022, T026, T028–T030 |
| FR-021–FR-023 (detection, no persistence) | T017, T020, T021, T026 |
| FR-024 (Published static otherwise) | T018, T020, T024 |
| FR-025–FR-029 (import) | T032–T038 |
| FR-030–FR-033 (Calendar) | T040–T043 |
| FR-034, FR-035 (favicon) | T003, T010, T011, T050 |
| FR-036, FR-037 (hover guard) | T002, T008, T009, T049 |
| FR-038–FR-040 (reduced motion) | T002, T006, T018, T048, every STOP |
| FR-041–FR-044 (a11y) | T005, T019, T020, T022, T040, T047 |
| FR-045, FR-046 (mobile) | T047, T049 |
| FR-047–FR-052 (out of scope) | T046, T052 |
| FR-053 (docs) | T045 |

### Published cases → tests

| Case | Test |
|---|---|
| 1 Mount with existing Published → no | T017 |
| 2 Observed Publishing → Published → once | T017, T020 (Results) |
| 3 Fast-path in Results → once | T020, T022 |
| 4 Poll returns Published again → no | T017, T022 |
| 5 Remount/reload with Published → no | T017, T020 (`emphasized`, empty `steps`), T021 |
| 6 Publishing → failed/other → no | T017 |

### Motion cleanup

`animationend` cleanup: T018, T033, T040. Reduced-motion cleanup and no visible leftover: T048.
Inert-leftover structure: T018. No timers that duplicate CSS durations: closed decision, reviewed
in T052.

## Risks covered explicitly

| Risk | Coverage |
|---|---|
| Published false positives or repetition | Cases 1–6 (T017, T020–T022), STOP B |
| Fast-path leaking outside Results | Option passed only by `ResultsSection` (T027, T029); T020 negatives; STOP B |
| Import highlight on the wrong cards | Ids from the import result, key + `loadedAt` + visibility (T032, T033, T036) |
| Late Calendar highlight after a week change | `landed = { id, week }`, set only in-week, matched by derivation (T041, T042) |
| Glow contrast | Research R3 values; T047 visual; T045 contrast rows |
| Infinite or long motion (WCAG 2.2.2) | T002 policy test; T048 `getAnimations()` |
| Focus or announcement regressions | T005, T022, T040; STOPs B and D |
| Sticky hover on touch | T002, T049 |

## Notes

- [P] tasks touch different files with no pending dependency.
- Do not add tasks for Flash, Home entrance, empty-state branding, TopBar, skeletons, page
  transitions, drag animation, animation libraries or backend/API.
