---

description: "Task list for Feature 022 — Bulk Media Delete"
---

# Tasks: Bulk Media Delete

**Input**: Design documents from `/specs/022-bulk-media-delete/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[contracts/api.md](contracts/api.md), [contracts/ui.md](contracts/ui.md),
[quickstart.md](quickstart.md). No data-model change (no models, tables or migrations).

**Tests**: requested by the spec ("Tests críticos") and the plan. Targeted, representative
and parametrized. During implementation run only the tests named in each task
(`cd backend && uv run pytest <files> -q` / `cd frontend && npx vitest run <paths>`). A test
that already passed is not re-run unless its code changed. Do **not** run the full pytest or
Vitest suite locally: full suites run only in PR CI. Static checks and the frontend build
run once, in T025. Concurrency tests reuse the deterministic barriers of
`backend/tests/test_delete_media.py` (`pause_before_commit`, `statement_reached`,
`pause_in_prepare`, `Gate`, `Background`, `threading.Event`), **never** `sleep`.

**Organization**: three checkpoints (A backend, B frontend, C close). Stories (spec.md):
- US1 Delete several Media with one confirmation (P1)
- US2 One busy item blocks the whole selection (P1)
- US3 Changes between confirmation and delete (P2)
- US4 Mobile use (P3)

Shared backend/frontend plumbing that every story needs carries no story label.

**Task format**: `- [ ] ID [P?] [Story?] Description (files)`, with sub-bullets **Deps**,
**Tests** and **Done**.

**Invariants** (every task preserves them; checked again in T024/T026):
1. All-or-none: a rejected or failed bulk delete changes nothing (DB, guards, disk).
2. Preview is read-only: it never acquires `ContentFileGuard.deleting(...)`, never locks,
   never writes. Its blockers come from read-only checks only (`PostEntry.in_progress`,
   `ContentFileGuard.is_sanitizing`).
3. Blocker precedence `post_in_progress` > `metadata_removal_in_progress` for
   `media_selection`, in preview and delete, independent of id or query order.
4. Guards are acquired only by the real delete: all-or-none, sorted, held through the whole
   transaction, released in `finally`.
5. No filesystem before COMMIT; files queued write-ahead in the same transaction.
6. No platform contact (no remote delete, revoke, check or reconcile).
7. Feature 021 individual deletes, their texts and Move are unchanged.
8. No new models, tables, migrations, scheduler changes or generic bulk framework.
9. No full suites locally.

**Checkpoints** (stable batches for `/speckit-implement`):
- **A** after T010: backend bulk deletion + targeted tests + refactor regressions.
- **B** after T020: frontend Select + Delete + targeted tests.
- **C** T021–T026: docs, STOP manual validation, security, static checks, coverage.

---

## Phase A: Backend bulk deletion

**Goal**: `POST /api/projects/{project_id}/contents/deletion-preview` and
`POST /api/projects/{project_id}/contents/delete` delete 1–500 Media and all their Posts in
one transaction, or nothing (contracts/api.md).

**Independent test**: `uv run pytest tests/test_delete_media_selection.py -q` green, plus
the refactor regressions of T010.

- [X] T001 [US1] Add the bulk schemas in `backend/app/schemas.py` (research §8, contracts/api.md §1):
  - `DeletionKind` gains `"media_selection"`.
  - `DeletionPreviewRead.id: int | None`, `DeletionPreviewRead.name: str | None` (docstring:
    `None` only for `media_selection`).
  - `ContentSelection(InputModel)`: `content_ids` with `Field(min_length=1,
    max_length=MAX_CONTENTS_PER_MOVE)` and `AfterValidator(_unique_content_ids)` (same
    constraint as `ContentMove`; reuse, do not copy).
  - `ContentSelectionDelete(ContentSelection)`: `confirmation: str` with
    `min_length=1, max_length=100` (same bounds as `ConfirmationQuery`).
  - **Deps**: none.
  - **Done**: types compile; individual previews still serialize `id`/`name`.

- [X] T002 [US1] Add the selection scope to `backend/app/deletion.py` (research §2, §3):
  - Messages: `NOT_FOUND_MESSAGES["media_selection"] = "Some selected media no longer
    exist. Review your selection."`; `IN_PROGRESS_MESSAGES["media_selection"] = "A post
    using one or more selected media items is being published right now. Try again when it
    finishes."`; `METADATA_REMOVAL_MESSAGES["media_selection"] = "Metadata is being removed
    from one or more selected media items. Try again when it finishes."`.
  - `collect_media_selection(session, project_id, content_ids) -> DeletionScope`:
    `Project` missing → `NotFoundError("Project not found.")`; **one** query for
    `Content.id, storage_path, sanitized_storage_path` with `Content.id.in_(ids)` and
    `Content.project_id == project_id`, ordered by id; posts via
    `_post_entries(session, Publication.content_id.in_(found_ids))`; returns
    `DeletionScope(kind="media_selection", target_id=project_id, name="", posts=…,
    content_ids=found_ids, file_paths=originals + clean copies)`. It **never raises** for a
    missing Media: callers decide (preview 404, delete 409). No per-id loop, no N+1.
  - `confirmation_token` is **not** modified: the canonical form already carries `kind`,
    `id` (= project id), sorted `contents` and sorted `[post_id, status, needs_review]`
    (research §5).
  - **Deps**: T001.
  - **Done**: collect works for 0 posts, many posts and sanitized Media (both paths).

- [X] T003 [US1] Add the read-only aggregate preview in `backend/app/deletion.py` (research §4, contracts/api.md §2):
  - `_selection_summary(scope)`: line 1 `"{n} media item(s) and {p} post(s) will be removed
    from AutoPublisher."` (without posts: `"{n} media item(s) will be removed from
    AutoPublisher."`); line 2 if `r = remote + needs_review > 0`: `"{r} post(s) may already
    exist on platforms. Content already published on platforms is not affected."`; line 3:
    the existing `_review_line(posts, generic=True)`. Use `_plural`. Wire it into
    `_summary`.
  - `build_preview`: `IN_PROGRESS_FIRST: frozenset[DeletionKind] = frozenset({"media_selection"})`;
    for those kinds `post_in_progress` is evaluated before `metadata_removal_in_progress`;
    other kinds keep the 021 order. `id`/`name` are `None` for `media_selection`.
  - `preview_media_selection(session, project_id, content_ids, file_guard)`: collect with
    the request session; `len(scope.content_ids) != len(content_ids)` →
    `NotFoundError(NOT_FOUND_MESSAGES["media_selection"])`; `sanitizing = any(
    file_guard.is_sanitizing(id_) for id_ in scope.content_ids)`; `build_preview`.
    **Never** calls `file_guard.deleting(...)`, never opens a write transaction.
  - **Deps**: T002.
  - **Done**: preview counts/summary/blocker/token match contracts/api.md §2.

- [X] T004 Refactor `execute` in `backend/app/deletion.py` without changing 021 behaviour (research §6):
  - Extract `_delete_confirmed(ctx, read_scope, held, kind, confirmation) -> DeletionScope`:
    `write_transaction` → `scope = read_scope(session)` → `held.issuperset(
    scope.content_ids)` else `deletion_changed` (now general: trivially true for post,
    account, folder with empty `content_ids` and for media with `{id}`) → `in_progress` →
    `post_in_progress` → token → `deletion_changed` → `_delete(session, scope)`.
  - Extract `_after_commit(ctx, scope, kind, target_id)`: the current log line, attempt
    invalidation, `run_file_cleanup`, `_clean_credentials`, `_remove_project_dir` (project
    only), exactly as today.
  - `execute` becomes `_held_contents` + `_delete_confirmed` + `_after_commit`. Error codes,
    messages, order and log text stay identical.
  - **Deps**: none (can start in parallel with T001–T003 but touches the same file: do it
    right after T003 to avoid conflicts).
  - **Tests**: `uv run pytest tests/test_delete_media.py tests/test_delete_project.py tests/test_delete_post.py tests/test_delete_account.py -q`
    (`_delete_confirmed`/`_after_commit` carry every kind, including attempt invalidation
    and credential cleanup).
  - **Done**: all four files green with no test change.

- [X] T005 [US1] Implement the real bulk delete in `backend/app/deletion.py` (plan "Orden exacto del Delete", research §4, §6, §7):
  - `_delete`: branch for `media_selection` → `_delete_posts(session, select(
    Publication.id).where(Publication.content_id.in_(scope.content_ids)))` (subquery, no
    list of post ids) then `_delete_contents(session, scope.content_ids,
    scope.file_paths)`.
  - `_hold_selection(ctx, project_id, content_ids)` (context manager): acquire
    `ctx.file_guard.deleting(content_ids, blocked_message=METADATA_REMOVAL_MESSAGES[
    "media_selection"])` through an `ExitStack` so that **only an acquisition failure** is
    inspected: on `ConflictError` with code `metadata_removal_in_progress`, open a short
    read-only `ctx.session_factory()` session, run `collect_media_selection(...)`, and if
    `scope.in_progress` raise `ConflictError("post_in_progress",
    IN_PROGRESS_MESSAGES["media_selection"])` from None; otherwise re-raise. Any other
    acquisition error (`deletion_changed`) propagates unchanged. Errors raised inside the
    body are never converted. Yields `frozenset(content_ids)`.
  - `execute_media_selection(ctx, project_id, content_ids, confirmation)`:
    `with _hold_selection(...) as held:` `_delete_confirmed(ctx, read, held,
    "media_selection", confirmation)` where `read(session)` calls
    `collect_media_selection` and raises `ConflictError("deletion_changed",
    CHANGED_MESSAGE)` when `set(scope.content_ids) != set(content_ids)`; then
    `_after_commit`. Never calls `execute` per Media.
  - **Deps**: T003, T004.
  - **Done**: one `write_transaction`; guards released in every outcome; files only after
    COMMIT.

- [X] T006 [US1] Add the routes to `backend/app/deletion_routes.py` (contracts/api.md §2–§3):
  - `POST /projects/{project_id}/contents/deletion-preview` (`response_model=
    DeletionPreviewRead`, body `ContentSelection`, request session + `GuardDep`) →
    `deletion.preview_media_selection`.
  - `POST /projects/{project_id}/contents/delete` (`status_code=204`, body
    `ContentSelectionDelete`, `ContextDep`) → `deletion.execute_media_selection` → `204`.
    The request session is never used for the delete.
  - Docstrings in the style of the existing routes (no platform is contacted; content
    already published is not affected).
  - Individual routes untouched.
  - **Deps**: T001, T003, T005.
  - **Done**: routes reachable behind the 020 guards (no exemption added).

- [X] T007 [US1] Write the success-path tests in new `backend/tests/test_delete_media_selection.py` (reuse helpers/fixtures from `tests/test_delete_media.py` by import, not copy):
  - 1 Media; several Media; a Media with no Posts; a Media with several Posts in mixed
    states (Draft, Scheduled, Failed, Published, Awaiting user action, Needs review) →
    exact `counts` and `summary` lines (contracts/api.md §2), `id`/`name` null; `204`; no
    Media, Post, attempt or platform option row left.
  - Original + clean copy of every Media queued before COMMIT and unlinked after it.
  - Unlink failure (monkeypatched) → still `204`, rows stay in `pending_file_deletions`,
    removed at restart (`_restart` pattern).
  - Zero publisher calls (`fake_publisher` untouched).
  - Ids not reused: a Media imported afterwards gets a higher id.
  - Token: same with ids in any order (parametrized permutations); bulk token of `[x]` ≠
    individual token of `x`, and each is rejected (`409 deletion_changed`) by the other
    route.
  - Validation: empty, duplicates, 501 ids → `422`; id of another project → preview `404`
    + delete `409 deletion_changed`; unknown project → `404`.
  - 500 Media (rows inserted directly, files tiny): preview and delete succeed (SC-008).
  - Routes private and guarded: no session → 401/403; bad Origin on both `POST`s → refused
    (pattern of `test_media_routes_are_private_and_guarded`).
  - **Deps**: T006.
  - **Tests**: `uv run pytest tests/test_delete_media_selection.py -q`.

- [X] T008 [US2] Add blocker, precedence and race tests to `backend/tests/test_delete_media_selection.py`:
  - One Media with a Publishing post (+ running attempt) → preview blocker
    `post_in_progress`, delete `409 post_in_progress`, nothing deleted, guard set empty.
  - One Media in Remove metadata (held with `Gate` on `asset_library._sanitize_to`) →
    preview blocker `metadata_removal_in_progress`, delete `409` same code, nothing
    deleted; Remove metadata then completes `200`.
  - **Both at once**: Media A and Media B are **both inside the selection**; A has a
    Publishing post (+ running attempt), B is in Remove metadata (held with `Gate`);
    parametrized over id order `[A, B]` / `[B, A]` → always `post_in_progress` in preview
    **and** delete; nothing deleted; guard set empty afterwards.
  - Remove metadata on a Media **outside** the selection (held with `Gate`) does **not**
    affect the bulk delete: bulk preview has no blocker, bulk delete returns `204`, the
    outside Media is untouched (row and files), and its Remove metadata then completes
    `200`.
  - Preview never acquires guards: preview during a held sanitization leaves
    `_deleting` empty and Remove metadata unaffected.
  - Delete first → scheduler claim (barriers of `test_delete_media_first_then_scheduler_claim`
    with two selected Media): `204`, tick starts nothing, no attempts, no upload.
  - Claim first, parametrized `scheduler` / `publish-now` (pattern `_claim_first`) on one of
    two selected Media → `409 post_in_progress`, **both** Media and all Posts intact.
  - Bulk holds guards (paused before COMMIT) → `POST /api/contents/{id}/remove-metadata`
    on any selected Media → `409 content_deleting`.
  - **Deps**: T007.
  - **Tests**: `uv run pytest tests/test_delete_media_selection.py -q`.

- [X] T009 [US3] Add scope-change and rollback tests to `backend/tests/test_delete_media_selection.py`:
  - Parametrized after preview: new Post, Post deleted, Post `status` changed,
    `needs_review` changed → `409 deletion_changed`; nothing deleted; guards released.
  - Stale before preview: one selected Media deleted individually → preview `404`
    "Some selected media no longer exist. Review your selection."
  - Stale after preview: one selected Media deleted individually → bulk delete `409
    deletion_changed`; the remaining Media and Posts intact.
  - Another delete holds one Media (bulk paused before COMMIT) → second bulk/individual
    delete on an overlapping set → `409 deletion_changed`.
  - A Move of a selected Media to another folder after preview → delete still `204`
    (folder not in the token).
  - Rollback: `before_cursor_execute` failure on `DELETE FROM contents` → `500
    internal_error`; all Media, Posts, files intact; no pending rows; guards released;
    the same token then succeeds.
  - **Deps**: T007.
  - **Tests**: `uv run pytest tests/test_delete_media_selection.py -q`.

- [X] T010 Checkpoint A — refactor regressions (targeted, once):
  - `uv run pytest tests/test_delete_media.py tests/test_delete_project.py tests/test_delete_post.py tests/test_delete_account.py tests/test_media_move.py tests/test_delete_media_selection.py -q`
    (skip files already green since their code last changed).
  - **Deps**: T004–T009.
  - **Done**: all green; individual Post, Media, Account and Project deletes and Move
    unchanged.

---

## Phase B: Frontend Select + Delete

**Goal**: Select mode bar `N selected | Move | Delete | Cancel` opens the existing
`DeleteConfirmDialog` with the aggregate preview (contracts/ui.md).

**Independent test**: `npx vitest run src/pages/library src/components/DeleteConfirmDialog`
green.

- [X] T011 [P] Add bulk types and API in `frontend/src/types.ts` and `frontend/src/api.ts` (research §9):
  - `DeletionKind` gains `"media_selection"`; `DeletionPreview.id: number | null`,
    `name: string | null`.
  - `DELETION_PATHS: Record<Exclude<DeletionKind, "media_selection">, string>`;
    `getDeletionPreview`/`deleteObject` typed on that same subset.
  - `getMediaSelectionDeletionPreview(projectId, contentIds)` → `POST
    /projects/{id}/contents/deletion-preview` `{content_ids}`;
    `deleteMediaSelection(projectId, contentIds, confirmation)` → `POST
    /projects/{id}/contents/delete` `{content_ids, confirmation}` (pattern of
    `moveContents`).
  - **Deps**: T006 (contract).
  - **Done**: existing callers compile unchanged.

- [X] T012 [P] Extend `frontend/src/components/DeleteConfirmDialog.tsx` (contracts/ui.md §2):
  - Render `ap-delete-dialog__name` only when `preview.name !== null`.
  - Optional prop `onMissing?: () => void`: a `404` from the preview or the delete calls
    `onMissing` when given, otherwise `onDeleted` (current behaviour). `onMissing` is read
    through the `latest` ref, exactly like `onDeleted`, so a reload after
    `deletion_changed` (the `useCallback([])` `load`) never calls a stale callback.
  - **Tests** in `frontend/src/components/DeleteConfirmDialog.test.tsx`: null name renders
    no name line; preview 404 with `onMissing` calls it and not `onDeleted`; existing tests
    unchanged and green (individual behaviour intact).
  - **Deps**: T011.
  - **Done**: `npx vitest run src/components/DeleteConfirmDialog` green.

- [X] T013 [P] Add the bulk routes to `frontend/src/test-fake-api.ts`:
  - Both `POST` routes; 422 for empty/duplicates/>500; preview `404` if any id is missing
    or of another project; aggregate of the existing `deletionScope("media", id)` per id;
    summary lines as contracts/api.md §2; blocker from `deletionBlockers` (`media:<id>`)
    with precedence `post_in_progress` > `metadata_removal_in_progress`; token derived from
    the sorted ids + posts; delete `409 deletion_changed` on token mismatch or missing id;
    on success remove every Media and its Posts.
  - **Deps**: T011.
  - **Done**: used by T016–T019.

- [X] T014 [P] [US1] Add Delete to `frontend/src/pages/library/SelectionBar.tsx` and phone layout in `frontend/src/pages/library/library.css` (contracts/ui.md §1):
  - Prop `onDelete`; order Move (primary, unchanged) · Delete (secondary, class
    `ap-delete-entry`) · Cancel; Move and Delete `disabled` when `count === 0`; update the
    component comment ("Move and Delete").
  - Phone (`max-width: 767px`): `.ap-selection-bar__count` full row; the three buttons share
    the second row (`flex: 1 1 0`), no horizontal overflow.
  - **Deps**: none.

- [X] T015 [US1] Wire the bulk delete into `frontend/src/pages/library/MediaView.tsx` (plan "Stale selection", contracts/ui.md §3):
  - State `bulkDelete: number[] | null`: snapshot `[...checked]` when Delete is pressed.
  - `<DeleteConfirmDialog title={`Delete ${n} media item(s)?`} loadPreview={() =>
    getMediaSelectionDeletionPreview(project.id, ids)} remove={(c) =>
    deleteMediaSelection(project.id, ids, c)} … />`.
  - `onDeleted`: close dialog; `setChecked(null)`; if `selectedId` is in `ids` navigate to
    `viewPath` (replace); flash `"{n} media deleted."` (FlashState, as `mediaDeleted`);
    `await handleChanged()` (list, folder tree counts, overview).
  - `onMissing`: close dialog; `await load()` (prunes the selection); flash `"Some selected
    media no longer exist. Review your selection."`; Select mode stays.
  - `onClose`: close dialog only (selection kept).
  - **Deps**: T011–T014.

- [X] T016 [US1] Write `frontend/src/pages/library/bulk-delete.test.tsx` — main flow, parametrized over Folder / Unsorted / All media:
  - Select shows Move + Delete + Cancel; 0 selected → Move and Delete disabled.
  - Aggregate preview shown (summary lines, no name, no per-Media list); one Delete click
    deletes; no second confirmation.
  - Success: all selected cards disappear together, Select mode ends, flash, folder/Unsorted/
    All media counts updated, overview reloaded, stays on the view; empty state when the
    view becomes empty; open detail of a deleted Media closes.
  - **Deps**: T013, T015.
  - **Tests**: `npx vitest run src/pages/library/bulk-delete.test.tsx`.

- [X] T017 [US2] Add blocker tests to `frontend/src/pages/library/bulk-delete.test.tsx`:
  - Preview blocker → message + Close only; nothing removed; selection kept.
  - Delete answering `409 post_in_progress` → shown as blocker.
  - **Deps**: T016.

- [X] T018 [US3] Add stale-selection and change tests to `frontend/src/pages/library/bulk-delete.test.tsx`:
  - Preview 404 → no confirmation, view reloaded, selection pruned to remaining Media,
    flash, nothing else deleted.
  - Delete `409 deletion_changed` → "Something changed" + new summary; nothing deleted until
    a second explicit click.
  - `deletion_changed` caused by a vanished Media → re-preview 404 → `onMissing` path.
  - Network/5xx failure → error in dialog; no card disappears; selection kept.
  - **Deps**: T016.

- [X] T019 [US4] Add mobile tests to `frontend/src/pages/library/bulk-delete.test.tsx`:
  - Phone viewport (mocked `MEDIA_MD_UP` false, as existing Sheet tests): bar shows Move,
    Delete, Cancel; confirmation renders as `Sheet` with the summary; confirm deletes.
  - **Deps**: T016.

- [X] T020 Checkpoint B — targeted frontend run (once):
  - `npx vitest run src/pages/library src/components/DeleteConfirmDialog` (includes
    `move.test.tsx` and `media-delete.test.tsx`: Move and individual delete unchanged).
  - **Deps**: T012, T016–T019.
  - **Done**: all green.

---

## Phase C: Validation + close

- [X] T021 [P] Document bulk delete in `README.md` (deletion section): select several Media
  in Library → Delete → one confirmation; all or nothing; up to 500; remote content
  untouched.
  - **Deps**: T015.

- [X] T022 STOP — manual desktop validation (quickstart.md §2, scenarios 1–6, 8) on a scratch
  instance (`AUTOPUBLISHER_CONFIG` copy + fail keyring), backend and frontend left running
  in background; give the user the link. 2–3 Media with mixed Posts in Folder, Unsorted and
  All media; record results in `specs/022-bulk-media-delete/quickstart.md` (append a short
  "Validation results" section).
  - **Deps**: T010, T020.

- [X] T023 STOP — manual mobile/LAN validation (quickstart.md §2 scenario 7): select,
  Delete, Sheet, result on a real phone; record in the same section.
  - **Deps**: T022.

- [X] T024 Targeted security review of the diff: new routes only under `/api`, behind
  session + Host/Origin (covered by T007 test); no SQL/paths/refs in errors or logs (log
  line counts only); token has no names/paths/secrets; preview read-only (Invariant 2);
  frontend renders summary as text. Record findings in the PR description.
  - **Deps**: T010, T020.

- [X] T025 Final static checks, **once**:
  - `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
  - `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`
  - `git diff --check`
  - **Deps**: T021–T024. If only docs/specs change afterwards, do not repeat.

- [X] T026 Requirement coverage table appended below (FR/SC → task → test); verify each
  invariant; open the PR (full suites run in CI).
  - **Deps**: T025.

---

## Dependencies

```text
T001 → T002 → T003 → T004 → T005 → T006 → T007 → {T008, T009} → T010
T006 → T011 → {T012, T013} ; T014 (independent)
{T011..T014} → T015 → T016 → {T017, T018, T019} → T020
{T010, T020} → T021..T024 → T025 → T026
```

- Phase B can start once T006 fixes the contract (frontend does not need the backend
  running: tests use `test-fake-api.ts`).
- T008/T009 and T017–T019 share a file each: sequential in practice.

## Parallel opportunities (real)

- T012, T013, T014 (different files) after T011.
- T014 can start at any time.
- Phase B (T011–T019) in parallel with T007–T010 once T006 is done.
- T021 in parallel with T022–T024.

## Implementation strategy

MVP = US1 (T001–T007, T011–T016): bulk delete with one confirmation. US2 (blockers) and US3
(changes) add tests on the same code paths; US4 is CSS + one test. Stop at checkpoints A, B
and the STOP tasks T022/T023 for user validation.

## Coverage (filled in T026)

| Requirement | Task(s) | Covered by |
|---|---|---|
| FR-001–FR-003 (bar, Delete, Move unchanged) | T014, T015 | `bulk-delete.test.tsx`, `move.test.tsx` |
| FR-004, FR-005 (same project, 1–500, unique) | T001, T002 | `test_delete_media_selection.py` (validation) |
| FR-006–FR-009 (aggregate preview, 404) | T002, T003 | `test_delete_media_selection.py` |
| FR-010, FR-011 (one confirmation, blocker) | T012, T015 | `bulk-delete.test.tsx`, `DeleteConfirmDialog.test.tsx` |
| FR-012–FR-014 (token) | T002 | token tests (T007, T009) |
| FR-015–FR-017 (blockers) | T003, T005 | T008 |
| FR-017a (precedence `post_in_progress` first, any id order) | T003, T005 | T008 `test_publishing_wins_over_remove_metadata_in_the_selection` (both orders, preview + delete), T017 |
| FR-018–FR-023 (one transaction, guards, files) | T004, T005 | T007, T009 |
| FR-024–FR-026 (races) | T005 | T008 |
| FR-027–FR-029 (changes, stale) | T005, T012, T015 | T009, T018 |
| FR-030 (no remote) | T005 | T007 (no publisher calls), T024 |
| FR-031–FR-033 (after delete) | T015 | T016 |
| FR-034, FR-035 (compat, guards) | T004, T006 | T010 (post/media/account/project/move regressions), T020, T007 (guards) |
| SC-001 (select, one Delete, one confirm) | T015 | T016, T022 |
| SC-002 (all-or-none in every failure) | T005 | T008, T009, T018 |
| SC-003 (one busy media blocks all) | T003, T005 | T008, T017 |
| SC-004 (no deleted post starts) | T005 | T008 scheduler/publish-now races |
| SC-005 (zero platform calls) | T005 | T007 `no_platform_contact` |
| SC-006 (files removed or queued) | T005 | T007 write-ahead, unlink failure, restart |
| SC-007 (Folder, Unsorted, All media, phone) | T014, T015 | T016, T019, T022, T023 |
| SC-008 (500 Media) | T002, T005 | T007 `test_five_hundred_media_at_once` |
| SC-009 (individual delete and Move unchanged) | T004 | T010, T020 |
| US1–US4 | T001–T019 | T007/T016 (US1), T008/T017 (US2), T009/T018 (US3), T019/T023 (US4) |
| Edge cases (empty, duplicates/other project, >500, no posts, mixed states, single, stale before/after preview, overlapping delete, Remove metadata vs held, open detail, unlink failure, rollback, network error, ids not reused, Move during confirmation) | T001–T015 | T007–T009, T012, T016, T018 |

Note: on a network error after confirming, the dialog shows "Couldn't delete it. Try
again." and no card changes (contracts/ui.md §3); the next attempt resolves the real
state through `deletion_changed` → preview 404 → reload. No partial state is shown.

Manual validation (T022 desktop, T023 phone over LAN) was confirmed by the user on a
throwaway instance (copied data, own config, fail keyring, port 8020).
