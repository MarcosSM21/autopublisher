---

description: "Task list for Feature 021 — Deletion & Library Organization"
---

# Tasks: Deletion & Library Organization

**Input**: Design documents from `/specs/021-deletion-library-organization/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md)

**Tests**: requested by the spec and plan ("Test Strategy"). Use a **targeted,
representative and parametrized** set. During implementation run only the tests of the
modified block (`cd backend && uv run pytest <files> -q` / `cd frontend && npx vitest run
<paths>`). A test that already passed is not re-run unless its code changed. When shared
code changes, run only the extra regressions named in the task. Do **not** run the full
pytest or Vitest suite locally: full suites run only in PR CI. Static checks and the
frontend build run once, in T050. Concurrency tests use deterministic barriers
(`threading.Event`), **never** `sleep`.

**Organization**: phases follow the approved plan checkpoints A–H. Stories (spec.md):
- US1 Delete a Post (P1)
- US2 Delete Media and free disk space (P1)
- US3 Organize Library in folders (P2)
- US4 Move Media between folders (P2)
- US5 Delete a folder without losing Media (P2)
- US6 Delete an Account (P2)
- US7 Delete a Project (P3)

Phase A has no story label because every story depends on it.

**Task format**: `- [ ] ID [P?] [Story?] Description (files)`, followed by the sub-bullets
**Deps** (blocking tasks), **Tests** (targeted) and **Done** (acceptance criterion).

**Invariants** (every task preserves them; checked again in T051/T052):
1. Delete = gone from every user-facing view, list, count and read model.
2. No soft delete, deletion flag, Trash or visible history.
3. No remote deletion, revoke or any platform contact while deleting (TikTok included).
4. No keyring, filesystem or runtime (connection-attempt) side effects before the DB COMMIT;
   a rejected delete changes nothing anywhere.
5. Pending cleanup rows are written in the same transaction as the delete (write-ahead).
6. Scheduler/manual start and delete are mutually exclusive (DB serialization).
7. Remove metadata and Media/Project delete are mutually exclusive (`ContentFileGuard`).
8. Connection attempts never block a delete (never `409` for them).
9. A late connection result never recreates an Account, Connection or active secret.
10. IDs are never reused (`AUTOINCREMENT`).
11. Folder operations never move, copy or rename files.
12. Folder delete never deletes Media or Posts.
13. Backup `.tar` format unchanged; no secrets in backups.
14. No public routes: all new routes under `/api`, behind 020 guards.
15. No full suites locally.

**Checkpoints** (stable batches for `/speckit-implement`):
- **A** after T013: schema, transaction/guard primitives, cleanup queues, hardening.
- **B** after T017: Delete Post (backend) + race tests.
- **C** after T019: Delete Media + file cleanup.
- **D** after T024: Delete Account + Project + credential cleanup + backup cases.
- **E** after T030: Library folders backend.
- **F** after T038: Library frontend.
- **G** after T046: Deletion frontend.
- **H** T047–T052: docs, STOP gates, close.

---

## Phase A: Schema + deletion/concurrency primitives (Foundational)

**Purpose**: everything later phases build on. Validates the MEDIUM risk of `BEGIN
IMMEDIATE` with pysqlite/SQLAlchemy (T004).

- [X] T001 Update the models in `backend/app/models.py` (data-model.md):
  - New `LibraryFolder`. Columns: `id`, `project_id`, `parent_id`, `name` (100), `name_key`, `depth`, `created_at`, `updated_at`. Constraints:
    - `UNIQUE(id, project_id)`;
    - composite FK `(parent_id, project_id) → library_folders(id, project_id)` RESTRICT;
    - CHECK `depth_range` (1–5) and CHECK `root_depth` (`(parent_id IS NULL) = (depth = 1)`);
    - partial unique indexes `uq_library_folders_root_name` and `uq_library_folders_child_name`.
  - New `PendingFileDeletion` (`storage_path` PK, `created_at`).
  - New `PendingCredentialDeletion` (`credential_ref` PK, `platform` with CHECK on the platforms that have connections, `account_id` nullable without FK, `created_at`).
  - `Content`:
    - `folder_id` nullable;
    - composite FK `(folder_id, project_id) → library_folders(id, project_id)` RESTRICT;
    - index `ix_contents_folder_id`.
  - `sqlite_autoincrement=True` on `Project`, `Account`, `Content`, `Publication`, `DistributionPreset` and `LibraryFolder`. Merge it into `__table_args__` as the trailing dict.
  - `TemporaryMediaObject.attempt_id` → `Mapped[int | None]`.
  - Remove `TikTokCredentialOrphan`.
  - **Deps**: —
  - **Tests**: covered by T003.
  - **Done**: models match data-model.md; `mypy`-clean types (checked in T050).
- [X] T002 Write the migration `backend/migrations/versions/0019_deletion_library_folders.py` (research §18), in this order:
  1. Create `library_folders`.
  2. Batch-recreate `projects`, `accounts` and `distribution_presets` with `recreate="always", table_kwargs={"sqlite_autoincrement": True}`.
  3. Recreate `contents` with AUTOINCREMENT, `folder_id`, the composite FK and the index.
  4. Recreate `publications` with AUTOINCREMENT, then recreate its partial indexes with the `_recreate_partial_index` pattern of 0006.
  5. Make `temporary_media_objects.attempt_id` nullable.
  6. Create `pending_file_deletions` and `pending_credential_deletions`.
  7. `INSERT … SELECT` the `tiktok_credential_orphans` rows with `platform='tiktok'`, then drop that table.

  `downgrade()` drops folders, `folder_id` and the queues, recreates `tiktok_credential_orphans` from the `tiktok` rows and restores `attempt_id NOT NULL`. Downgrade refuses with a clear message if any `attempt_id` is NULL. AUTOINCREMENT is left in place. The migration is non-destructive: every row keeps its id.
  - **Deps**: T001
  - **Tests**: T003.
  - **Done**: `upgrade head` works on an empty DB and on a seeded 0018 DB.
- [X] T003 Add the migration tests to `backend/tests/test_migrations.py`:
  - **0018 → 0019 with seeded data** (projects, accounts, contents with a clean copy, publications in active/published/cancelled, attempts, temporary objects, presets, a connection, two TikTok orphans). Every row and id is kept; all `folder_id` are NULL (Unsorted).
  - **Orphans**: TikTok orphans moved to `pending_credential_deletions` with `platform='tiktok'`, and `tiktok_credential_orphans` is gone.
  - **AUTOINCREMENT**: `sqlite_master` SQL of the 6 tables contains it. `sqlite_sequence` equals the max id. Deleting the newest row and inserting yields a new id (ID non-reuse).
  - **Partial indexes**: they keep their `WHERE` clause.
  - **Folder constraints**: same-project composite FK rejects a cross-project parent or `folder_id`; root/child sibling `name_key` uniqueness; depth CHECKs.
  - **Parity**: the existing `test_migrations_match_models` (`compare_metadata`) passes.
  - **Integrity**: `PRAGMA foreign_key_check` and `PRAGMA integrity_check` are clean after the upgrade. The CHECK constraints and `server_default`s of the recreated tables are still present (inspect `sqlite_master`, and insert a row relying on defaults).
  - **Downgrade**: round trip.
  - **Deps**: T002
  - **Tests**: `uv run pytest tests/test_migrations.py -q -k "0019 or autoincrement or folder or match_models"`.
  - **Done**: all pass; migration is non-destructive.
- [X] T004 [P] Add `write_transaction(session_factory)` to `backend/app/db.py` (research §4):
  - Context manager that creates its **own** new Session.
  - Checks out its connection and raises `RuntimeError` if the DBAPI connection is already `in_transaction`. Never a defensive rollback.
  - Executes `BEGIN IMMEDIATE` as the first SQL statement.
  - Yields the session; commits on success, rolls back and re-raises on exception, always closes.
  - **Deps**: —
  - **Tests**: new `backend/tests/test_write_transaction.py`:
    1. A `before_cursor_execute` listener proves `BEGIN IMMEDIATE` is the first statement of the session.
    2. A second writer thread (plain `UPDATE` + commit) blocks until the first COMMIT, released by a barrier; the first transaction reads the state confirmed before it.
    3. An exception rolls back every change **and releases the lock**: a second writer proceeds immediately afterwards.
    4. A connection with an open transaction raises `RuntimeError`.
    6. A request-style session that only ran completed reads does not block `write_transaction` (research §4, usage rule).
    5. Behaviour with the real file DB and `PRAGMA foreign_keys=ON` engine from `create_db_engine`.
  - **Done**: the MEDIUM pysqlite risk is retired (downgraded to LOW in plan.md if all pass; otherwise STOP and report before continuing).
- [X] T005 [P] Extend `ContentFileGuard` in `backend/app/content_files.py` (research §6):
  - Add a `_deleting` set and `deleting(content_ids)`. Under `_lock`, all-or-nothing and never waiting: if any id is in `_sanitizing` → `ConflictError("metadata_removal_in_progress", …)`; if any id is in `_deleting` → `ConflictError("deletion_changed", …)`; otherwise register all ids, sorted ascending.
  - Release in `finally` under `_lock`.
  - `sanitizing()` rejects ids in `_deleting` with the new code `content_deleting` ("This media is being deleted."). Add `content_deleting` and `deletion_changed` to `ConflictCode` in `backend/app/errors.py`.
  - `claiming()` is unchanged.
  - **Deps**: —
  - **Tests**: new `backend/tests/test_content_file_guard.py`, deterministic with barriers:
    1. Delete holds the guard → `POST /api/contents/{id}/remove-metadata` → `409 content_deleting`, no clean copy written.
    2. Remove metadata holds the guard (barrier in the sanitizer) → `deleting({id})` raises `metadata_removal_in_progress`.
    3. Three ids with one sanitizing → raises, and the other two are not retained (a later `sanitizing` on them works).
    4. An exception inside the block releases all ids.
    5. A `claiming` that waits on the DB while a `deleting` holder commits: no deadlock (both finish).
  - **Done**: real exclusion, no hold-and-wait.
- [X] T006 Create `backend/app/cleanup.py` (research §8, §15):
  - `enqueue_files(session, paths)` and `enqueue_credentials(session, items)`: add rows in the caller's transaction. Credentials use `INSERT OR IGNORE`.
  - `run_file_cleanup(session_factory, storage, paths=None)`:
    - for each pending row (or only `paths`): skip unlink and drop the row if any `contents.storage_path/sanitized_storage_path` references it;
    - otherwise `storage.resolve()` → `unlink(missing_ok=True)` → delete the row;
    - `OSError`/`ValueError` → log without absolute path, keep the row, continue.
  - `run_credential_cleanup(session_factory, targets, refs=None)`. `targets: Mapping[Platform, CredentialTarget(store, credential_lock)]`. Per row:
    - ref still used by any connection table → drop only the row;
    - otherwise take `credential_lock(account_id)` with a bounded wait (timeout → keep the row);
    - `store.delete(ref)` → delete the row;
    - `CredentialStoreUnavailable` → stop and keep the remaining rows.
  - Never raises; idempotent; never recreates anything. Logs carry counts only, never refs.
  - **Deps**: T001
  - **Tests**: new `backend/tests/test_cleanup_files.py` (success, missing file = success, unlink failure keeps row, referenced path untouched, path outside root rejected) and `backend/tests/test_cleanup_credentials.py` (success, unavailable keeps rows, ref still in use only drops row, lock timeout keeps row, idempotent second run).
  - **Done**: both queues behave per research §15.
- [X] T007 Generalize TikTok orphans in `backend/app/tiktok_connections.py`:
  - `register_orphan`, `_delete_new_secret` and `_cleanup_replaced_secret` use `cleanup.enqueue_credentials` with `platform='tiktok'` and `PendingCredentialDeletion`.
  - Delete `cleanup_orphans`; startup uses the generic cleanup (T009).
  - **Deps**: T001, T006
  - **Tests**: `backend/tests/test_tiktok_orphans.py` (adapt to the generic table), `backend/tests/test_tiktok_reconnect.py`.
  - **Done**: behaviour identical; one cleanup mechanism.
- [X] T008 [P] Add the platform credential hooks:
  - Public `credential_lock(account_id)` in `backend/app/youtube_connections.py`, `instagram_connections.py`, `threads_connections.py` and `tiktok_connections.py`, returning the existing `_account_lock`. In `telegram_connections.py`, a context manager over `account_session(account_id, wait=True, should_stop=<deadline>)`.
  - `TikTokAttemptRegistry.expire_for_account(account_id, *, revoke: bool = True)` in `backend/app/tiktok_oauth.py`. With `revoke=False`, a dropped pending credential is discarded in memory without calling `discard`.
  - **Deps**: —
  - **Tests**: `backend/tests/test_tiktok_oauth.py`: `revoke=False` never calls the discard callback (fake that fails if called); default behaviour unchanged.
  - **Done**: hooks exist; no remote revoke possible from delete.
- [X] T009 Wire startup cleanup and credential targets in `backend/app/main.py` (research §16):
  - `app.state.credential_targets` = platform → (store, credential_lock).
  - After `sweep_orphan_clean_copies`: synchronous `run_file_cleanup`.
  - Replace `tiktok_connections.cleanup_orphans` with a daemon thread `credential-cleanup` that runs `run_credential_cleanup` **only if** `app.state.credential_probe.status() == "available"`; otherwise log and skip.
  - Startup never waits on the keyring.
  - **Deps**: T006, T007, T008
  - **Tests**: new `backend/tests/test_cleanup_startup.py`:
    - pending file rows are retried at startup;
    - probe `locked`/`unavailable`/`unknown` → no store call (store fake that fails if used);
    - probe `available` → rows cleaned.
    - Direct-risk regression: `backend/tests/test_scheduler_lifecycle.py`.
  - **Done**: deferred cleanup survives restart without prompts.
- [X] T010 [P] Make temporary delivery cleanup independent of attempts in `backend/app/media_delivery.py`:
  - `sweep()` uses a LEFT OUTER JOIN: pending rows whose `attempt_id` is NULL or whose attempt is not `running`.
  - `release_attempt` is unchanged.
  - **Deps**: T001
  - **Tests**: `backend/tests/test_media_delivery.py`: a pending row with `attempt_id NULL` is released by `sweep()` through the fake provider using only `object_key` and the delivery config. Credential stores are fakes that fail if touched (research §7, case A).
  - **Done**: cleanup is self-contained.
- [X] T011 [P] NotFound hardening (research §5):
  - `backend/app/publishing.py`: in `start_publication`, `follow_up_publication` and `reconcile_uncertain`, map `NoResultFound`/`ObjectDeletedError` from rows that vanished during preflight or the remote call to `NotFoundError`.
  - `backend/app/scheduler.py`: add `"not_found"` to `NOT_CLAIMED_CODES`.
  - **Deps**: —
  - **Tests**: `backend/tests/test_publish_service.py` (publication deleted with raw SQL inside a fake `prepare()` → 404, no attempt) and `backend/tests/test_scheduler_tick.py` (candidate deleted between selection and claim → `not_claimed`, no auto-publish error recorded).
  - **Done**: no 500 and no noise when a Post disappears mid-start.
- [X] T012 Harden the final persistence of OAuth connection flows (research §9b):
  - Add `AccountGone` and a helper in `backend/app/accounts.py` that runs inside `write_transaction`: re-read the Account (exists, same platform, connectable per the current rules) or raise `AccountGone`.
  - Apply it to `complete_connection` in `backend/app/youtube_connections.py`, `instagram_connections.py`, `threads_connections.py` and `tiktok_connections.py`. Each one, inside its own `write_transaction`, re-reads the Account and the existing connection, then writes the connection, identity and replaced-ref orphan, then commits.
  - On `AccountGone` or a commit failure with `account_gone()`: no rows; delete the new secret, or `enqueue_credentials` in a short `write_transaction` if the store is unavailable; raise `authorization_gone()`.
  - `_discard_secret` failures enqueue instead of only logging.
  - The callers pass `request.app.state.session_factory`. Secret-before-row order is kept.
  - Usage rule (research §4): **all** final writes move inside `write_transaction`; the request session has no pending DML when it is entered; request-session ORM objects are re-read inside, never reused.
  - **Deps**: T004, T006, T007
  - **Tests**: new `backend/tests/test_connection_late_results.py`, YouTube as the representative OAuth platform plus one parametrized check for Instagram, Threads and TikTok:
    - the Account is deleted with raw SQL between `store.set` and the final persist (barrier) → callback shows "Authorization not valid", no connection row, secret deleted;
    - same with the store failing on delete → ref in `pending_credential_deletions`;
    - persist commits first → the row exists (a delete later removes it, covered in T021).
    - Regressions: `backend/tests/test_youtube_connect.py`, `backend/tests/test_youtube_oauth.py`, `backend/tests/test_instagram_connect.py`, `backend/tests/test_tiktok_connect.py` and the Threads connect test file.
  - **Done**: no OAuth flow can recreate state for a deleted Account.
- [X] T013 Harden Telegram login completion in `backend/app/telegram_connections.py`:
  - `_complete_login` persists inside `write_transaction` with the Account re-read.
  - On `AccountGone`, delete the written secret (new ref, or renewed existing ref already queued) or enqueue it, then fail with the existing invalid-authorization error.
  - **Deps**: T012
  - **Tests**: `backend/tests/test_connection_late_results.py` (Telegram cases: new connection and renewal) + regression `backend/tests/test_telegram_connections.py`.
  - **Done**: **Checkpoint A** — schema, primitives and hardening green with the targeted tests above.

---

## Phase B: Delete Post (US1, P1) 🎯 MVP

**Goal**: any Post except Publishing can be deleted with one confirmation; a deleted
scheduled Post never runs.

**Independent test**: schedule an automatic Post, delete it, restart, advance the clock: no
Post, no attempt (spec US1).

- [X] T014 [US1] Create the deletion core in `backend/app/deletion.py` (research §1, §3):
  - `DeletionScope` dataclass: post ids with bucket, content ids, account ids, folder ids, connection refs, file paths.
  - Bucket classification via `app.post_state.needs_manual_review`: `unpublished` / `remote` / `needs_review`. Blocker detection: `publishing` status **or** running attempt.
  - `confirmation_token(scope)`: `"v1:" + sha256` of canonical JSON (`sort_keys=True`). Post entries are `(post_id, status, needs_review)` sorted by id. Content, account and folder ids are sorted. No clock-derived state (Missed/Overdue), timestamps, names, handles or refs (research §3).
  - `build_preview(kind, scope, names)`: counts plus the exact English `summary` lines of contracts/api.md, with pluralization and per-kind phrases.
  - Add `DeletionPreviewRead` to `backend/app/schemas.py`.
  - **Deps**: T004
  - **Tests**: new `backend/tests/test_deletion_preview.py` (unit): the token is deterministic (query order shuffled) and changes on any added/removed id, status change (draft → scheduled) or needs-review change; it does **not** change when only the clock moves (scheduled → Missed); summary text per kind and per count combination, including the exact spec strings (US2 #2, US6 #1, US7 #1, US5 #2).
  - **Done**: preview logic is pure and covered.
- [X] T015 [US1] Implement `_delete_posts(session, post_ids)` in `backend/app/deletion.py`, in this order (research §7):
  1. temporary objects of their attempts: DELETE the released ones, `attempt_id = NULL` for the pending ones;
  2. `POST_ATTEMPT_DEPENDENTS` (publish runs);
  3. attempts;
  4. `POST_DEPENDENTS` (options);
  5. publications.

  Define the `POST_ATTEMPT_DEPENDENTS`, `POST_DEPENDENTS` and `CONNECTION_MODELS` tuples.
  - **Deps**: T001, T014
  - **Tests**: new `backend/tests/test_deletion_schema.py`: walks `Base.metadata` and fails if a table with an FK to `projects`, `accounts`, `contents`, `publications`, `publication_attempts` or `library_folders` is neither in the tuples nor in the explicit handled list.
  - **Done**: every dependent table is covered; RESTRICT FKs stay.
- [X] T016 [US1] Add `execute(session_factory, kind, id, confirmation, ctx)` for `post`, and the router `backend/app/deletion_routes.py` with `GET /api/publications/{id}/deletion-preview` (request session, read-only) and `DELETE /api/publications/{id}?confirmation=` (required query → 422 if missing):
  - Fixed order: `write_transaction` → scope → blocker (`409 post_in_progress` with the Post message) → token (`409 deletion_changed`) → `_delete_posts` → COMMIT → `204`.
  - 404 for a missing Post. Log with counts only (FR-012).
  - The DELETE route does not use the request session (research §4, usage rule).
  - Register the router in `backend/app/main.py`.
  - **Deps**: T015
  - **Tests**: new `backend/tests/test_delete_post.py`:
    - parametrized over draft, scheduled automatic/manual/paused, missed, failed, cancelled, needs review, awaiting user action, published: preview summary/buckets as in the contract, then delete → 204;
    - afterwards absent from `GET /api/projects/{id}/publications`, `/api/overview`, Media usage (`/api/contents/{id}/usage`) and needs-review warnings;
    - Publishing → 409 and intact;
    - second delete → 404;
    - changed scope → `deletion_changed`;
    - pending temporary object kept with `attempt_id NULL`;
    - fake transports record no platform call.
  - **Done**: US1 backend behaviour per contract.
- [X] T017 [US1] Add the concurrency tests in new `backend/tests/test_delete_concurrency.py` (research §5). A `FakePublisher` blocks in `prepare()` and around the claim commit with `threading.Event` barriers:
  - (a) delete commits first → the scheduler tick ends `not_claimed`, no attempt, no auto-publish error;
  - (b) the claim commits first → delete `409 post_in_progress`, Post intact;
  - (c) and (d): same two orders with manual `POST …/publish`;
  - (e) restart after delete (`recover_interrupted_attempts` + a new tick with the clock past the time) → nothing runs.

  Reusable barrier helpers live in `backend/tests/` for T019/T021/T023.
  - **Deps**: T016, T011
  - **Tests**: the new file.
  - **Done**: exactly one wins in every order. **Checkpoint B.**

---

## Phase C: Delete Media + file cleanup (US2, P1)

**Goal**: Media and all its Posts disappear; original and clean copy leave the disk.

**Independent test**: video with Remove metadata + draft + published Post → delete → no
views show them; both files gone (spec US2).

- [X] T018 [US2] Implement Media deletion in `backend/app/deletion.py` and `backend/app/deletion_routes.py`:
  - `_delete_contents(session, ids)`: `enqueue_files` (original + clean copy) in the same transaction, then DELETE contents.
  - `execute` for `media`, in this order:
    1. `guard.deleting({id})` (`409 metadata_removal_in_progress`, Media message);
    2. `write_transaction`;
    3. scope: every Post of the Media, any state;
    4. blocker `post_in_progress` (Media message);
    5. token;
    6. `_delete_posts`;
    7. `_delete_contents`;
    8. COMMIT;
    9. release the guard (`finally`);
    10. post-commit `run_file_cleanup(paths)`.
  - Routes `GET /api/contents/{id}/deletion-preview` and `DELETE /api/contents/{id}?confirmation=`. The preview reports `metadata_removal_in_progress` as a `blocker` when the id is sanitizing.
  - No file is touched before COMMIT.
  - **Deps**: T005, T006, T016
  - **Tests**: T019.
  - **Done**: per contract.
- [X] T019 [US2] Add the Media tests in new `backend/tests/test_delete_media.py`:
  - **Removal**: 2 unpublished + 1 published → exact spec summary; Media and the 3 Posts absent from contents list, publications, overview and calendar data; original and clean copy unlinked.
  - **Unlink failure**: patched `Path.unlink` → 204 and the row stays in `pending_file_deletions`; a new app startup removes the file and the row.
  - **Shared path**: a path still referenced by another content (forged row) is never unlinked.
  - **Re-upload**: the same file is accepted as new.
  - **Blocking**: Remove metadata in progress → 409 (and the reverse order, via T005 helpers through the API); Publishing → 409; claim race in both orders (reuse T017 barriers).
  - **Failure path**: an injected failure after `_delete_posts` → nothing changed, no file touched, guard free.
  - **Deps**: T018, T017, T009
  - **Tests**: the new file.
  - **Done**: **Checkpoint C.**

---

## Phase D: Delete Account + Project + credential cleanup (US6 P2, US7 P3)

**Goal (US6)**: an Account and all its Posts, connection and local credential disappear;
connection attempts never block and their late results are discarded.

**Goal (US7)**: a Project and all its local state disappear in one transaction.

- [X] T020 [US6] Implement Account deletion in `backend/app/deletion.py` and `backend/app/deletion_routes.py`:
  - `_delete_accounts(session, ids)`: DELETE `distribution_preset_accounts`; for each `CONNECTION_MODELS` row, `enqueue_credentials((platform, ref, account_id))` then DELETE; DELETE accounts.
  - `execute` for `account`, in this order:
    1. no local exclusions;
    2. `write_transaction`;
    3. scope;
    4. blocker (Account message);
    5. token;
    6. `_delete_posts`;
    7. `_delete_accounts`;
    8. COMMIT;
    9. **then** `expire_for_account` on the four OAuth registries (TikTok with `revoke=False`) and `telegram_logins.discard`;
    10. post-commit `run_credential_cleanup(refs)` unless the probe says `locked`/`unavailable`, then the rest of the queue.
  - The preview includes the identity line (handle + platform).
  - Routes `GET /api/accounts/{id}/deletion-preview` and the new `DELETE /api/accounts/{id}?confirmation=`.
  - Delete `backend/app/account_discard.py` and its router registration in `backend/app/main.py`; remove the `account_busy`/`account_not_discardable` usages.
  - **Deps**: T008, T009, T012, T013, T016
  - **Tests**: T021.
  - **Done**: per contract; no remote contact.
- [X] T021 [US6] Add the Account tests in new `backend/tests/test_delete_account.py`, and adapt the discard tests in `backend/tests/test_accounts.py` to preview + `confirmation` (same result):
  - **Removal**: 1 draft + 1 scheduled + 2 published → exact summary; Account and Posts absent from accounts, publications, overview and presets; the preset is kept empty.
  - **Credentials**: secret deleted from the fake store; store unavailable → 204, connection gone, row queued; probe `locked` → no store call, row queued.
  - **Rejected delete** (`deletion_changed`, Publishing): OAuth attempt still completable, Telegram login still present, store untouched.
  - **Connection attempts**: TikTok pending credential is discarded without `revoke` (gateway fake fails if called). An OAuth attempt mid-callback with the Account deleted in between → no connection, no active secret (end-to-end through the delete endpoint). A Telegram step holding `account_session` → the delete still returns 204, and secret cleanup waits for the step and then runs.
  - **Refresh**: an in-flight refresh under `credential_lock` finishes before the secret delete.
  - **Temporary delivery**: an Instagram temporary object left pending is still released by `sweep()` after the delete.
  - **Concurrency**: claim race in both orders (T017 helpers).
  - **Deps**: T020
  - **Tests**: the new file + `backend/tests/test_accounts.py` (discard cases only).
  - **Done**: US6 backend complete.
- [X] T022 [US7] Implement Project deletion in `backend/app/deletion.py` and `backend/app/deletion_routes.py`, in this order:
  1. read the Project's content ids in a short read session;
  2. `guard.deleting(ids)`;
  3. `write_transaction`;
  4. scope; a non-retained content → `deletion_changed`;
  5. blockers;
  6. token;
  7. deletes: `_delete_posts(all)`, `_delete_accounts(all)`, `DELETE distribution_presets`, `UPDATE contents SET folder_id = NULL`, DELETE `library_folders` (by `depth DESC`), `_delete_contents(all)`, DELETE project;
  8. COMMIT;
  9. release the guard;
  10. invalidate the attempts of every deleted Account (TikTok `revoke=False`);
  11. file and credential cleanup, then `rmdir projects/{id}` if empty.

  Routes `GET /api/projects/{id}/deletion-preview` and `DELETE /api/projects/{id}?confirmation=`. Global settings untouched.
  - **Deps**: T018, T020
  - **Tests**: T023.
  - **Done**: one transaction, no intermediate visibility.
- [X] T023 [US7] Add the Project tests in new `backend/tests/test_delete_project.py`:
  - **Removal**: 3 accounts / 12 posts / 24 media → exact summary; an empty project gives an empty summary. `automation_settings`, `installation_auth` and the platform configuration files are unchanged (FR-033). After the delete, nothing of the project is returned by any endpoint, files and secrets are gone, another project is byte-for-byte unchanged, and a new project gets a new id and an empty Library. Deleting the last project → `GET /api/projects` empty.
  - **Atomicity**: a failure injected after half the deletes → nothing changed, no file or keyring touched, guard free, attempts intact.
  - **Guard**: one of several Media sanitizing → 409; a Media imported between the guard and the transaction → `deletion_changed`.
  - **Concurrency**: claim race in both orders.
  - **Deps**: T022
  - **Tests**: the new file.
  - **Done**: US7 backend complete.
- [X] T024 Backup/restore cases in `backend/tests/test_restore.py`:
  - (a) A pre-021 backup restored → migrates; every Media is in Unsorted.
  - (b) A backup taken after deleting objects → deleted objects do not reappear; pending-file rows whose file is absent are cleared at startup. Folder rows are seeded directly in the DB here; the API-level folder backup case is in T029.
  - (c) A backup taken before deleting an Account, restored after the delete → the account shows Reconnect required (secret gone), no crash, no secret in the archive.

  No format change in `backend/app/backup.py`; modify it only if a case fails.
  - **Deps**: T009, T020
  - **Tests**: the three new cases.
  - **Done**: **Checkpoint D.**

---

## Phase E: Library folders backend (US3, US4, US5)

- [X] T025 [US3] Create `backend/app/library_folders.py` (router + service) and add the reads to `backend/app/schemas.py`:
  - `GET /api/projects/{id}/library-folders`: flat tree ordered by `depth, name_key`, with direct `media_count`, plus `unsorted_count` and `total_count`; at most 3 queries.
  - `POST /api/projects/{id}/library-folders` `{name, parent_id}`, inside `write_transaction`: strip; 1–100 → 422; parent missing or from another project → 404; `depth = parent.depth + 1`, > 5 → `409 folder_too_deep`; sibling `name_key` collision → `409 folder_name_taken`. A residual `IntegrityError` is mapped to the same codes, never leaked.
  - `PATCH /api/library-folders/{id}` `{name}`: rename; a same-key rename is allowed.
  - Add the codes to `backend/app/errors.py`. Register the router in `backend/app/main.py`.
  - **Deps**: T003, T004
  - **Tests**: T029.
  - **Done**: per contract §2.
- [X] T026 [US3] Extend `backend/app/contents.py`:
  - `ContentRead.folder_id`.
  - `GET /api/projects/{id}/contents?folder=<id>|unsorted`: absent = all; a foreign or missing folder → 404; another value → 422. Usage is still computed in one pass.
  - `POST /api/projects/{id}/contents?folder_id=<id>`: imported Media go to that folder, checked before processing any file (404). A returned duplicate is not moved. If the folder is deleted during a multi-file import, each remaining file goes to Unsorted (the per-file insert re-checks that the folder exists), never an `IntegrityError`.
  - **Deps**: T025
  - **Tests**: T029.
  - **Done**: listing and upload by folder.
- [X] T027 [US4] Add `POST /api/projects/{id}/contents/move` `{content_ids (1–500, unique), folder_id|null}` → `{moved}` in `backend/app/library_folders.py`: one `write_transaction`; every id must belong to the project and the folder to the project, else 404 and nothing changes; a single UPDATE. No disk or Post change; allowed while publishing.
  - **Deps**: T025
  - **Tests**: T030.
  - **Done**: atomic single and multi move.
- [X] T028 [US5] Implement folder deletion in `backend/app/deletion.py` and `backend/app/deletion_routes.py`:
  - Scope via recursive CTE (research §13): subfolder ids and Media of the subtree.
  - Never blocked. Token.
  - `UPDATE contents SET folder_id = NULL` for the subtree, then DELETE folders by `depth DESC`, inside `write_transaction`.
  - Routes `GET /api/library-folders/{id}/deletion-preview` and `DELETE /api/library-folders/{id}?confirmation=`.
  - **Deps**: T014, T025
  - **Tests**: T029.
  - **Done**: subtree → Unsorted, no Media/Post/file touched.
- [X] T029 [P] [US3] Add the folder tests in new `backend/tests/test_library_folders.py`:
  - **Hierarchy**: root/child creation and depth 5 OK; level 6 → `folder_too_deep`.
  - **Names**: "Lux"/"lux"/a Unicode-equivalent form → `folder_name_taken` at root and among children; the same name under different parents is OK; rename persists; a same-key rename is allowed; a user folder named "Unsorted" or "All media" is allowed (FR-037).
  - **Isolation**: cross-project parent, folder and listing → 404.
  - **Views**: Unsorted, folder and All listings.
  - **Upload**: into a folder; from root/Unsorted.
  - **Delete**: a folder with 5 + a subfolder with 3 → exact summary, 8 Media in Unsorted, files untouched, Posts untouched, a deleted subfolder → 404; an empty folder → empty summary; ids never reused.
  - **Backup** (in `backend/tests/test_restore.py`): a backup taken after organizing folders restores the same folders and `folder_id` (SC-009).
  - **Deps**: T026, T028
  - **Tests**: the new file.
  - **Done**: US3/US5 backend behaviour.
- [X] T030 [P] [US4] Add the move tests in new `backend/tests/test_media_move.py`:
  - single move; multi move;
  - one foreign id → 404 and nothing moved; a foreign folder → 404;
  - move to Unsorted;
  - moving a Media whose Post is `publishing` is allowed and leaves the Post untouched;
  - disk listing unchanged; Posts unchanged.
  - **Deps**: T027
  - **Tests**: the new file.
  - **Done**: **Checkpoint E.**

---

## Phase F: Library frontend (US3, US4)

- [X] T031 [US3] Add the client contracts in `frontend/src/types.ts` and `frontend/src/api.ts`:
  - `LibraryFolder`, `LibraryFolders`, `Content.folder_id`;
  - `listLibraryFolders`, `createLibraryFolder`, `renameLibraryFolder`;
  - `listContents(projectId, scope)` with the `folder` param, import with `folderId`, `moveContents`.
  - Update `frontend/src/test-fake-api.ts`.
  - **Deps**: T026, T027
  - **Tests**: `frontend/src/api.test.ts` (params and paths).
  - **Done**: typed API.
- [X] T032 [US3] Add the routes in `frontend/src/routes.tsx`:
  - `library` → `LibraryRoot`;
  - `library/unsorted/:mediaId?`, `library/all/:mediaId?`, `library/folders/:folderId/:mediaId?` → `MediaView`;
  - keep `library/:mediaId` (detail over All media) and `library/:mediaId/publish`.
  - Split `frontend/src/pages/LibraryPage.tsx` into `frontend/src/pages/library/LibraryRoot.tsx` and `frontend/src/pages/library/MediaView.tsx` (scope `all | unsorted | folder`). The current grid, toolbar, search, filters, import and detail move unchanged into `MediaView`.
  - A missing or foreign folder → `NotFound` with "Back to Library".
  - **Deps**: T031
  - **Tests**: `frontend/src/routes.test.tsx` (each URL renders its view; the legacy media deep link still works; unknown folder → not found).
  - **Done**: every view has its own URL.
- [X] T033 [P] [US3] Build `LibraryRoot` in `frontend/src/pages/library/LibraryRoot.tsx` (contracts/ui.md §2):
  - top-level folders with counts, then Unsorted and All media entries, Import media and New folder;
  - never a media grid;
  - the onboarding `LibraryDropzone`/empty state below when the project has no Media;
  - import from root → Unsorted.
  - **Deps**: T032
  - **Tests**: `frontend/src/pages/library/library.test.tsx` (root with and without folders; no grid; empty onboarding; counts).
  - **Done**: FR-039, FR-046.
- [X] T034 [P] [US3] Add `frontend/src/pages/library/Breadcrumb.tsx` and `frontend/src/pages/library/FolderNameDialog.tsx`, and the folder header in `MediaView`:
  - Breadcrumb: on phone, levels between `Library` and the current folder collapse into a "…" menu; no horizontal scroll.
  - FolderNameDialog: create/rename with backend errors inline.
  - Folder header: subfolder rows, then the "More" menu with New folder (only if `depth < 5`) and Rename. Delete folder is added in T045.
  - **Deps**: T032
  - **Tests**: `frontend/src/pages/library/folders.test.tsx` (breadcrumb links and collapse at phone width, create in current folder, `folder_name_taken` message, rename persists after reload).
  - **Done**: FR-040–FR-042 navigation.
- [X] T035 [US3] Show folders on Media in `frontend/src/pages/library/MediaCard.tsx` and `frontend/src/pages/library/MediaDetail.tsx`:
  - card meta shows the folder in All media;
  - detail shows "Folder: …";
  - `useMediaImport` passes the current folder id when importing inside a folder.
  - **Deps**: T032
  - **Tests**: `frontend/src/pages/library/library.test.tsx` (folder label; upload inside a folder sends `folder_id`; from Unsorted it does not).
  - **Done**: FR-042, FR-044, FR-045 (display).
- [X] T036 [US4] Create `frontend/src/pages/library/FolderPicker.tsx`:
  - indented tree with Unsorted first, current location marked "Current";
  - `Sheet` on phone, `Dialog` on md+;
  - Move from the Media detail via `moveContents`, then reload.
  - **Deps**: T031, T035
  - **Tests**: `frontend/src/pages/library/move.test.tsx` (picker lists tree + Unsorted; moving from detail updates location; error shown and nothing changes).
  - **Done**: FR-048, single Move.
- [X] T037 [US4] Add Select mode in `MediaView` (`frontend/src/pages/library/MediaView.tsx`, `LibraryToolbar.tsx`, `MediaGrid.tsx`, `MediaCard.tsx`, `library.css`):
  - a Select button; a visible checkbox per card;
  - a fixed bottom bar "{n} selected" with Move and Cancel; the only action is Move;
  - no long-press;
  - Move → FolderPicker → one `moveContents` call → reload the list and counts → exit Select.
  - **Deps**: T036
  - **Tests**: `frontend/src/pages/library/move.test.tsx` (select 3 → Move → one request with 3 ids; cancel clears).
  - **Done**: FR-047, FR-049 (UI).
- [X] T038 [US3] Library frontend consolidation:
  - reload counts after import, move and rename;
  - "Back" navigation between views;
  - focus return from detail;
  - CSS for root entries and the bottom bar in `frontend/src/pages/library/library.css` (≥ 44 px targets, 360 px without horizontal scroll).
  - **Deps**: T033, T034, T035, T037
  - **Tests**: the Library test files touched in T032–T037 only, if their code changed.
  - **Done**: **Checkpoint F.**

---

## Phase G: Deletion frontend (all delete stories)

- [X] T039 Add the deletion client and flash:
  - `DeletionPreview` type and `get*DeletionPreview`/`delete*(id, confirmation)` for publication, content, account, project and folder in `frontend/src/types.ts` and `frontend/src/api.ts`; replace `discardAccount`.
  - Flash region in `frontend/src/shell/AppShell.tsx`: reads `location.state.flash`, `role="status"`, auto-hides after ~4 s, then clears the history state.
  - **Deps**: T016, T018, T020, T022, T028
  - **Tests**: `frontend/src/api.test.ts` (paths + query) and `frontend/src/shell/shell.test.tsx` (flash shown once).
  - **Done**: shared plumbing.
- [X] T040 Create `frontend/src/components/DeleteConfirmDialog.tsx` (contracts/ui.md §1):
  - **Loading**: skeleton while the preview loads.
  - **Body**: `summary` lines; an empty summary → simple confirm. Footer Cancel + Delete (`danger`).
  - **Blocker**: shows the message with Close only.
  - **Responses**: `204` → `onDeleted`; `404` → `onDeleted` without error; `409 deletion_changed` → reload the preview and show "Something changed. Review it again." (`role="alert"`); busy `409` → message + Close; other errors → inline and retryable.
  - **Layout**: `Sheet` on phone, `Dialog` on md+; never asks to type anything.
  - **Deps**: T039
  - **Tests**: new `frontend/src/components/DeleteConfirmDialog.test.tsx` covering every branch above.
  - **Done**: one reusable confirmation.
- [X] T041 [P] [US1] Add Delete post to `frontend/src/pages/posts/PostDetail.tsx`:
  - secondary zone, `danger` style;
  - disabled with "This post is being published right now." while publishing;
  - after deleting → `/p/:id/posts` with "Post deleted."; the Posts data reloads.
  - **Deps**: T040
  - **Tests**: `frontend/src/pages/posts/post-detail.test.tsx` (scheduled/published/needs-review summaries rendered; navigation + flash; publishing disabled).
  - **Done**: US1 UI.
- [X] T042 [P] [US2] Add Delete media to `frontend/src/pages/library/MediaDetail.tsx` (secondary zone) and to the `MediaCard` "More" menu. After deleting → the parent view route the detail came from, with "Media deleted.", and the list and counts reload.
  - **Deps**: T040, T038
  - **Tests**: `frontend/src/pages/library/media-delete.test.tsx` (from folder view → back to that folder; from the legacy link → All media).
  - **Done**: US2 UI.
- [X] T043 [P] [US6] Add Delete account to `frontend/src/pages/accounts/AccountDetail.tsx` (secondary zone): after deleting → `/p/:id/accounts` with "Account deleted.". `DiscardSetup` keeps its text and dialog but fetches the preview and sends `confirmation`.
  - **Deps**: T040
  - **Tests**: `frontend/src/pages/accounts.test.tsx` (summary with handle; navigation; discard still works).
  - **Done**: US6 UI.
- [X] T044 [P] [US7] Add Delete project to the "More" menu of `frontend/src/pages/project/ProjectHeader.tsx` (with Deactivate/Activate): after deleting → `/` with "Project deleted."; reload the project selector (`frontend/src/shell/projects-reload.ts`); the last project → existing empty onboarding on Home.
  - **Deps**: T040
  - **Tests**: `frontend/src/pages/home.test.tsx` or a new `frontend/src/pages/project/project-delete.test.tsx` (navigation, selector reloaded, empty state).
  - **Done**: US7 UI.
- [X] T045 [P] [US5] Add Delete folder to the folder "More" menu (`frontend/src/pages/library/MediaView.tsx`): after deleting → parent folder or Library root with "Folder deleted.", counts reloaded.
  - **Deps**: T040, T034
  - **Tests**: `frontend/src/pages/library/folders.test.tsx` (summary "… move to Unsorted. No media is deleted."; navigation to parent).
  - **Done**: US5 UI.
- [X] T046 Deletion UX consistency pass:
  - every Delete is secondary/`danger`, never a page primary (FR-009);
  - exactly one confirmation;
  - deep links to deleted objects show not found with the container link (FR-010, edge cases);
  - after every delete, the overview/project context (`reloadOverview`), the project list and the current view's data reload, so no stale card, count or ghost row remains (FR-005);
  - fake API updated.
  - **Deps**: T041–T045
  - **Tests**: only the test files of T041–T045 whose code changed in this pass.
  - **Done**: **Checkpoint G.**

---

## Phase H: Integration, mobile and close

- [X] T047 Update docs: `README.md` (deleting Posts/Media/Accounts/Projects, folders, recovery only via backup) and `docs/deployment.md` (deferred cleanup at startup with the keyring unlocked; no change to backup format). Only what changed.
  - **Deps**: T046
  - **Tests**: —
  - **Done**: docs match behaviour.
- [X] T048 [US3] **STOP 1 — manual validation, desktop + phone** (quickstart §2, scenarios 1–14). Start the backend and frontend in the background and give the link. On a real phone over LAN, or 360 px DevTools if LAN is not available:
  - delete dialogs on phone;
  - Library root, deep folder, breadcrumb collapse;
  - picker; Select/Move;
  - delete from the phone;
  - a deleted object appears nowhere (Home, Posts, History, Calendar, Library, Accounts, Publish, presets);
  - a deleted scheduled Post never runs after a restart.

  Record the results here. **STOP** for the user's confirmation.
  - **Deps**: T047
  - **Done**: the user confirms or issues are fixed with targeted tests.
- [X] T049 **STOP 2 — migration and backup on real data (safe copy only)**:
  - Copy the real installation DB and media to a scratch directory (never in place) and run 0019 there. Check row counts per table before/after, `sqlite_sequence`, every Media in Unsorted, and that the app starts on the copy.
  - With the CLI against a scratch data dir: create a post-021 backup and restore it; restore a pre-021 backup.
  - No real data is modified. Record the results. **STOP** for the user's confirmation.
  - **Deps**: T024, T047
  - **Done**: migration verified on a real-shaped DB.
- [X] T050 Close checks, **once**:
  - `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .`;
  - `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`;
  - `git diff --check`.
  - Fix any failure and re-run only the affected check. No full local pytest/Vitest.
  - **Deps**: T048, T049
  - **Done**: all green.
- [X] T051 Security review of the diff:
  - no secrets, refs, absolute paths or handles in logs or errors;
  - every new route under `/api` behind the 020 guards (no new exemption);
  - `storage.resolve` used for every unlink;
  - no platform calls in delete paths;
  - no keyring, disk or runtime effect before COMMIT;
  - `IntegrityError` never leaked;
  - backup contains no secrets.
  - Targeted route sweeps: `uv run pytest tests/test_guards.py -k every_other_route -q` and the route sweep in `tests/test_auth_api.py` (new routes are private automatically).
  - **Deps**: T050
  - **Done**: findings fixed (with targeted tests) or none.
- [X] T052 Requirements coverage: map every FR-001–FR-056 and SC-001–SC-011, and the 15 invariants above, to the task and test (or STOP gate) that covers it. Write the table at the end of this file. Update `checklists/requirements.md` if needed.
  - **Deps**: T051
  - **Done**: nothing uncovered; feature ready for PR (full suites in CI).

---

## Dependencies & Execution Order

```text
A: T001 → T002 → T003
   T004 [P] · T005 [P] · T008 [P] · T011 [P]   (independent files)
   T001 → T006 → T007 → T009 (needs T008)
   T001 → T010 [P]
   T004 + T006 + T007 → T012 → T013                       ── Checkpoint A
B: T004 → T014 → T015 → T016 → T017 (needs T011)          ── Checkpoint B
C: T005 + T006 + T016 → T018 → T019 (needs T017, T009)    ── Checkpoint C
D: T008 + T009 + T012 + T013 + T016 → T020 → T021
   T018 + T020 → T022 → T023
   T009 + T020 → T024                                     ── Checkpoint D
E: T003 + T004 → T025 → T026, T027 ; T014 + T025 → T028
   T026 + T028 → T029 [P] ; T027 → T030 [P]               ── Checkpoint E
F: T026 + T027 → T031 → T032 → {T033 [P], T034 [P], T035} → T036 → T037 → T038  ── Checkpoint F
G: B–E routes → T039 → T040 → {T041, T042, T043, T044, T045} [P] → T046         ── Checkpoint G
H: T047 → T048 (STOP) ; T049 (STOP) → T050 → T051 → T052
```

- Phase E only needs Phase A (+ T014 for folder deletion). It can run in parallel with
  B–D if desired; checkpoints stay in order A→H by default.

## Parallel Opportunities

- **A**: T004, T005, T008, T011 (different modules, no shared state). T010 after T001.
- **E**: T029 and T030 (different test files) once their implementation tasks are done.
- **F**: T033 and T034 after T032.
- **G**: T041–T045 after T040 (different pages).

## Implementation Strategy

1. **MVP** = Checkpoints A + B (+ T039–T041 for the Post UI): the riskiest deletion
   (scheduled Post) is safe end to end.
2. Then C (disk space), D (Account/Project), E–F (folders), G (remaining delete UIs), H.
3. Each checkpoint ends green on its targeted tests only; full suites run in PR CI.

## Unusually risky tasks

- **T002/T003**: recreating 5 core tables (partial indexes, CHECKs, composite FKs).
- **T004**: pysqlite `BEGIN IMMEDIATE` integration (STOP if T004 tests fail).
- **T012/T013**: changes to the final step of 5 connection flows.
- **T020/T022**: composite transactions, post-commit runtime invalidation, keyring ordering.
- **T049**: real-data migration (only on a copy).

---

## Results of Phase H

### T048 — manual validation, desktop + real phone over LAN (2026-10-24)

Run by the user on a disposable installation-mode instance (`:8020`, a migrated copy of the
real data, isolated keyring, no platform configuration); the real installation on `:8000`
was not touched. Desktop and a real phone over LAN: Library root, All media, Unsorted,
folders and subfolders, breadcrumb, browser Back, contextual upload, Move, Select + Move,
Delete folder/media/post/account/project, Calendar and History after deleting Posts, and
navigation with no deleted object left anywhere. No HIGH or MEDIUM defect. Scenarios 10/10b
(OAuth in progress) and the Publishing blocker need real platforms and stay covered by the
automated tests. The instance and its scratch data were removed afterwards.

**Post-021 improvement (LOW, out of scope):** *Bulk Media Delete from Select mode* —
Select several Media; actions Move + Delete; one aggregated confirmation; atomic
all-or-none backend; reuse the existing deletion primitives, guards and cleanup.

### T049 — migration and backup on a copy of the real installation (2026-10-24)

Source: `~/.local/share/autopublisher/autopublisher.db` (revision `0018`), copied with the
SQLite backup API from a read-only connection, plus a copy of `media/`. The real database,
media, keyring, host configuration and service were not modified (the real DB is still
`0018`; the service stayed active). Every app/CLI run used `AUTOPUBLISHER_CONFIG` pointing
to a scratch file and `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`.

- `alembic upgrade head` → `0019`. `integrity_check` ok, `foreign_key_check` empty. Row
  counts identical for every table (1 project, 6 accounts, 23 media, 27 posts, 24
  attempts); ids identical; `tiktok_credential_orphans` (0 rows) replaced by the two
  pending tables; `sqlite_sequence` seeded (accounts 6, contents 23, projects 1,
  publications 27). All 23 Media `folder_id NULL`. The app starts on the copy and lists
  `unsorted_count 23 / total_count 23`.
- Post-021 state on a second copy (API): folders `Cybersecurity › DDoS`, 3 + 2 Media
  assigned, folder `Temp` deleted (its Media → Unsorted), one Post deleted, one Media
  deleted (its file unlinked from the copy, no pending rows left). `cli backup` →
  `cli restore --yes` into a new directory: hierarchy and assignments identical, deleted
  Post/Media absent, integrity ok. The tar holds only `autopublisher.db`, `manifest.json`
  and `media/`; no OAuth token in the DB (the only `refresh_token` string is a query
  parameter of a TikTok CDN avatar URL, pre-existing data).
- Pre-021 backup made with `main` (worktree, removed afterwards) from a fresh `0018` copy →
  restored with this branch → migrated to `0019` at start-up, every Media in Unsorted.
- Pending cleanup: paths are relative and resolved with `storage.resolve`; a missing file
  or secret counts as done; a path/ref still referenced is never deleted
  (`run_file_cleanup` / `run_credential_cleanup`, covered by `test_cleanup_files.py`,
  `test_cleanup_credentials.py`, `test_cleanup_startup.py`).

### T050 / T051 (2026-10-24)

- Close checks once: ruff, ruff format, mypy (fixed a typing error in
  `tests/test_deletion_preview.py`; 21 tests re-run), oxlint, prettier, `tsc -b`, `npm run
  build` (only the existing chunk-size warning), `git diff --check`: green.
- Security: route sweeps green (`test_guards.py -k every_other_route`,
  `test_auth_api.py -k "public_api_routes or no_api_route_is_public"`). Delete logs carry
  kind, id and counts only; no platform client in delete paths (TikTok attempts expire with
  `revoke=False`, Telegram logins are dropped in memory); unlinks go through
  `storage.resolve`; secrets only after COMMIT through the queue; `IntegrityError` mapped by
  the global handler; the token is a scope digest, never an authorization; the frontend
  renders summaries as text and hides 5xx details. No HIGH/MEDIUM finding.

### T052 — coverage

| Requirement | Task(s) | Covered by |
|---|---|---|
| FR-001, FR-005, SC-004, SC-005 (gone everywhere) | T014–T024, T039–T046 | `test_delete_post/media/account/project.py`, `media-delete`, `post-detail`, `accounts`, `project-delete` tests; T048 |
| FR-002, FR-003, FR-009, SC-001 (one confirmation, backend summary, secondary) | T014, T040–T046 | `test_deletion_preview.py`, `DeleteConfirmDialog.test.tsx` |
| FR-004, FR-006 (atomic, no broken refs) | T002–T004, T015–T022 | `test_write_transaction.py`, `test_deletion_schema.py`, delete tests |
| FR-007, FR-013, FR-018, FR-031 (busy blockers only) | T014–T022 | `test_delete_concurrency.py`, `test_scheduler_concurrency.py`, `DeleteConfirmDialog.test.tsx` |
| FR-008 (no id reuse) | T002/T003 | `test_migrations.py` (autoincrement), T049 |
| FR-010 (navigate to container) | T041–T046 | `media-delete`, `folders`, `post-detail`, `accounts`, `project-delete` tests |
| FR-011, FR-012 (no Trash, no audit) | all | docs (T047); no such code |
| FR-014–FR-017, SC-002 (Post) | T015–T017 | `test_delete_post.py`, `test_delete_concurrency.py`, `test_scheduler_concurrency.py`; T048 scenario 1 |
| FR-019–FR-024, SC-003 (Media + files) | T018–T019, T042 | `test_delete_media.py`, `test_cleanup_files.py`, `media-delete.test.tsx`; T049 |
| FR-025–FR-030, SC-010, SC-011 (Account) | T012, T013, T020–T021, T043 | `test_delete_account.py`, `test_cleanup_credentials.py`, `test_connection_late_results.py`, `accounts.test.tsx` |
| FR-031–FR-033 (Project) | T022–T023, T044 | `test_delete_project.py`, `project-delete.test.tsx` |
| FR-034–FR-038, SC-006 (folders) | T025–T030, T045 | `test_library_folders.py`, `folders.test.tsx` |
| FR-039–FR-046, SC-008 (Library views) | T031–T038 | `library.test.tsx`, `folders.test.tsx`, `routes.test.tsx`; T048 |
| FR-047–FR-049, SC-007 (Move) | T028, T036 | `test_media_move.py`, `move.test.tsx`, `media-delete.test.tsx` |
| FR-050–FR-053 (API, errors, guards) | T014–T028, T051 | delete/folder API tests, `test_guards.py`, `test_auth_api.py` |
| FR-054, FR-055, SC-009 (backup) | T024 | `test_backup.py`, `test_restore.py`; T049 |
| FR-056 (mobile) | T033–T040 | `folders.test.tsx` (breadcrumb), `DeleteConfirmDialog.test.tsx` (Sheet); T048 |

| Invariant | Covered by |
|---|---|
| 1 gone everywhere · 2 no soft delete | delete tests + UI tests (no ghost rows); no flag/Trash in schema |
| 3 no platform contact | T051 review; `test_delete_account.py`, `test_connection_late_results.py` |
| 4 no side effect before COMMIT · 5 write-ahead | `test_cleanup_*`, `test_delete_account.py` (rejected delete changes nothing) |
| 6 scheduler/delete exclusive | `test_scheduler_concurrency.py`, `test_delete_concurrency.py` |
| 7 Remove metadata/delete exclusive | `test_content_file_guard.py`, `test_remove_metadata_api.py` |
| 8 attempts never block · 9 late results never recreate | `test_connection_late_results.py` |
| 10 ids never reused | `test_migrations.py`; T049 (`sqlite_sequence`) |
| 11 folders never move files · 12 folder delete keeps Media | `test_library_folders.py`, `test_media_move.py`; T049 |
| 13 backup format, no secrets | `test_backup.py`, `test_restore.py`; T049 |
| 14 no public routes | T051 route sweeps |
| 15 no full local suites | only targeted tests and the close checks were run |
