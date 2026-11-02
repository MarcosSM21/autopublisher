---

description: "Task list for Feature 029 — Send to Phone (minimal MVP)"
---

# Tasks: Send to Phone

**Input**: Design documents from `/specs/029-send-to-phone/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: requested explicitly. Each checkpoint runs only its targeted tests
(`uv run pytest tests/<file>.py`, `npx vitest run <path>`). The full backend and frontend suites
are **not** run locally: the PR CI runs them.

**Organization**: by checkpoints A–B of [plan.md](plan.md). Each checkpoint is implemented,
tested and closed with **one commit** (tasks marked `[X]`, targeted tests and static checks
green, diff reviewed), and work stops before the next one.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no pending dependencies).
- **[Story]**: US1 (send) / US2 (errors and retry) of spec.md.

## Closed decisions (apply to every task)

- One new module `backend/app/send_to_phone.py`; one endpoint
  `POST /api/contents/{content_id}/send-to-phone` → `204` on success.
- The file is **only** what `resolve_publish_file(storage, content, verify=True)` returns; no
  own file choice, no metadata checks.
- The whole `resolve_publish_file → tailscale file cp → end` runs inside the existing
  `ContentFileGuard.sanitizing(content.id, check)` with a no-op `check`
  (`request.app.state.content_file_guard`). No new lock, set or method on the guard, and its
  messages are not changed.
- Target: `os.environ.get("TAILSCALE_PHONE_TARGET", "").strip()`, read on every request. No
  setting in `config.toml` or the DB.
- Process: `subprocess.run([tailscale, "file", "cp", "--name", content.original_filename,
  str(path), f"{target}:"], stdin=subprocess.DEVNULL, capture_output=True,
  timeout=SEND_TIMEOUT_SECONDS, check=False)` with `tailscale = shutil.which("tailscale")`
  and `SEND_TIMEOUT_SECONDS = 300` (fixed, not configurable).
- Errors and codes exactly as in [contracts/api.md](contracts/api.md). Logs carry only the exit
  code, "timed out", or the exception class name; never stdout/stderr, paths, filename or
  target, and never `exc_info`.
- Out of scope: device selector, discovery/`--targets`, settings table, worker, queue, history,
  polling, MediaCard button, batch, QR, custom Android folder, multi-phone infrastructure.

---

## Checkpoint A — Backend (US1, US2)

**Goal**: the endpoint sends the publish file to the configured phone under the guard, and
fails safely in the five spec cases.

**Independent test**: `uv run pytest tests/test_send_to_phone.py` with `shutil.which` and
`subprocess.run` replaced by fakes; no real Tailscale needed.

### Implementation

- [X] T001 [US1] Create backend/app/send_to_phone.py following the asset_library.py pattern: `router = APIRouter(prefix="/api")`, `SEND_TIMEOUT_SECONDS = 300`, `TARGET_ENV = "TAILSCALE_PHONE_TARGET"`, the message constants of contracts/api.md, and `@router.post("/contents/{content_id}/send-to-phone", status_code=204)` as a sync `def` taking `SessionDep`, `StorageDep` and the guard dependency (reuse `GuardDep` from asset_library.py or the same `request.app.state.content_file_guard` getter). Flow: `get_content_or_404` → read target (empty → `AppError(503, "phone_target_not_configured", …)`) → `shutil.which("tailscale")` (None → `AppError(503, "tailscale_unavailable", …)`) → `with guard.sanitizing(content.id, lambda: None):` resolve the file (`ContentFileUnavailable` → `AppError(409, error.code, error.message)`) and run the process. Register the router in backend/app/main.py next to `asset_library.router`.
- [X] T002 [US2] In backend/app/send_to_phone.py map process outcomes inside the guard block: `subprocess.TimeoutExpired` → log "tailscale file cp timed out after %s s" with `SEND_TIMEOUT_SECONDS`, `AppError(504, "phone_send_timeout", …)`; `OSError` → log the class name, `AppError(503, "tailscale_unavailable", …)`; `returncode != 0` → log only the exit code, `AppError(502, "phone_send_failed", …)`. Raise with `from None`; never log `completed.stdout`/`stderr`. Do not touch backend/app/errors.py: its `ConflictCode` list is only for `ConflictError`, and `AppError` takes free codes (as 028's `metadata_check_unavailable`).

### Tests

- [X] T003 [P] [US1] Success tests in backend/tests/test_send_to_phone.py (fixtures from conftest.py, `monkeypatch.setenv(TARGET_ENV, "galaxy-test")`, fake `shutil.which` → `/usr/bin/tailscale`, fake `subprocess.run` recording its argv and kwargs and returning `returncode=0`):
  - original media → `204`; argv is exactly `["/usr/bin/tailscale", "file", "cp", "--name", <original_filename>, <original path>, "galaxy-test:"]`; no `shell=True`, `timeout == 300`, `stdin` is `DEVNULL`;
  - `sanitized` media with a valid clean copy → the path in argv is the clean copy, never the original, and `--name` is still the original filename.
- [X] T004 [P] [US2] Error tests in backend/tests/test_send_to_phone.py (one parametrized test where it fits):
  - target unset and target `"   "` → `503 phone_target_not_configured`, `subprocess.run` not called;
  - `which` returns None → `503 tailscale_unavailable`; `run` raising `FileNotFoundError` → same code;
  - original file missing, clean copy missing, clean copy corrupt (bytes changed, same size) → `409 media_unavailable` / `media_corrupt` with the existing messages, `run` not called;
  - `returncode=1` with stderr containing a path and the target → `502 phone_send_failed`;
  - `run` raising `subprocess.TimeoutExpired` → `504 phone_send_timeout`;
  - unknown content → `404`;
  - every error body has no `/`-rooted path, no filename and no target.
- [X] T005 [P] [US2] Guard and log tests in backend/tests/test_send_to_phone.py:
  - content already registered with `guard.sanitizing(...)` → `409 metadata_removal_in_progress`; with `guard.deleting([...])` → `409 content_deleting`; `run` not called in either case;
  - during the send (inside the fake `run`), `guard.sanitizing(content.id, …)` and `guard.deleting([content.id])` raise `ConflictError`;
  - after success, after `returncode=1` and after a timeout, `guard.sanitizing(content.id, lambda: None)` can be entered again (guard released);
  - with `caplog` at DEBUG for the failure and timeout cases, no record contains the stderr text, the storage path, the filename or the target, and every `record.exc_info` is None.

### Checks

- [X] T006 Run `uv run pytest tests/test_send_to_phone.py`, plus `uv run pytest tests/test_content_file_guard.py` only if T001/T002 touched content_files.py (they should not), `uv run ruff check`, `uv run ruff format --check` and `uv run mypy` on the changed files. Review the diff and close Checkpoint A with one commit.

---

## Checkpoint B — UI, real validation and close (US1, US2)

**Goal**: the button in Media Detail sends the media, shows its states and errors, the config is
documented, and a real send reaches the phone.

**Independent test**: vitest with the fake API; then a real Taildrop send from a safe instance.

### Implementation

- [ ] T007 [P] [US1] In frontend/src/api.ts add `sendToPhone(contentId: number): Promise<void>` (`POST /contents/${contentId}/send-to-phone`, next to `removeMetadata`). In frontend/src/test-fake-api.ts add the route and a `sendToPhoneResult: Record<number, {status, code, message} | undefined>` (default success, `204`) plus a record of calls, mirroring `removeMetadataResult`.
- [ ] T008 [US1] Create frontend/src/pages/library/useSendToPhone.ts (same shape as useCleanMetadata.ts): `{sending, sent, error, send}`; `send` clears `sent`/`error`, sets `sending`, calls `sendToPhone`, sets `sent = true` on success or `error = toApiError(caught).message` on failure, and always clears `sending`. In frontend/src/pages/library/MediaDetail.tsx add one `Send to phone` button in the header (own row or next to the folder row, wrapping at phone width): `loading={sending}`, label `Sending…` while sending; on success a short `Sent to phone` status (`role="status"`); on error the message with `role="alert"` and the button enabled again. Add minimal styles in frontend/src/pages/library/library.css only if needed. No change to MediaCard.
- [ ] T009 [P] Document `TAILSCALE_PHONE_TARGET` in docs/deployment.md (what it is, Taildrop + operator prerequisite `sudo tailscale set --operator=$USER`, the `systemctl --user edit autopublisher.service` override with `Environment=TAILSCALE_PHONE_TARGET=…` and restart, the 5-minute limit, that the phone receives the publish file with its original name in Downloads) and add a one-line mention in README.md.

### Tests

- [ ] T010 [P] [US1] [US2] frontend/src/pages/library/send-to-phone.test.tsx with the fake API:
  - the detail shows exactly one `Send to phone` button;
  - clicking it shows `Sending…` with the button disabled while the request is pending, then `Sent to phone`, and the fake recorded one call for that content;
  - with `phone_target_not_configured`, `phone_send_failed` and `phone_send_timeout` results (`it.each`), the message is shown as an alert and the button is enabled again; a second click retries (two calls);
  - no `Send to phone` button in the Media Card.

### Checks and close

- [ ] T011 Run `npx vitest run src/pages/library/send-to-phone.test.tsx` (and `media-metadata.test.tsx` only if T008 changed the shared header row), `npm run typecheck`, `npm run lint`, `npm run format:check`, `npm run build` and `git diff --check`. Run quickstart.md checkpoint B on a safe instance (`AUTOPUBLISHER_CONFIG` + fail keyring, never the real installation) with `TAILSCALE_PHONE_TARGET` set: send an original and a cleaned media to the phone and check name and arrival in Downloads; check the unset-target message; with the phone offline, record whether `tailscale file cp` fails fast or reaches the 300 s timeout. Record the results in this file. If the real test shows the fixed timeout does not work, stop and report instead of adding a setting. Mark spec.md **Status** as implemented, do a security review of the diff (no tool output, paths or target in logs or responses), and close Checkpoint B with one commit. Do not run the full pytest/vitest suites locally: the PR CI runs them.

---

## Dependencies & execution order

```text
A ──► B
```

- **A** (T001–T006) is independent.
- **B** (T007–T011) needs A's endpoint for the real validation; the UI and its tests only use
  the fake API, but B closes after A to keep the commits in order.
- Within A: T001 → T002 → tests T003–T005 → T006.
- Within B: T007 → T008 → T010 → T011; T009 at any time before T011.

## Parallel opportunities

- A: T003, T004 and T005 in parallel once T001–T002 are done.
- B: T007 and T009 in parallel; T010 once T008 is done.

## Implementation strategy

- **MVP**: A + B (the feature is the MVP). US1 is covered by T001, T003, T007, T008 and T010;
  US2 by T002, T004, T005 and T010.
- Stop after each checkpoint commit and report before starting the next one.
