---

description: "Task list for Feature 028 — Media Metadata Hygiene (minimal scope)"
---

# Tasks: Media Metadata Hygiene

**Input**: Design documents from `/specs/028-metadata-hygiene/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: requested explicitly. Every checkpoint runs only its targeted tests
(`uv run pytest tests/<file>.py`, `npx vitest run <path>`). The full backend and frontend suites
are **not** run locally: the PR CI runs them.

**Organization**: by checkpoints A–C of [plan.md](plan.md). Each checkpoint is implemented,
tested, audited and closed with **one commit** (tasks marked `[X]`, targeted tests and static
checks green, diff reviewed), and work stops before the next one. Checkpoints are never mixed in
one commit.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no pending dependencies).
- **[Story]**: US1–US3 of spec.md.

## Closed decisions (apply to every task)

- The badge is derived **only** in the frontend from `metadata_status` and
  `publish_file.available` (data-model.md table). No new fields, states, endpoints, tables or
  migrations.
- `POST /api/contents/{id}/remove-metadata` keeps its name, its 016 error codes and its
  behaviour. It only gains the post-clean reinspection and two error codes:
  `422 metadata_not_removed` and `503 metadata_check_unavailable` (contracts/api.md).
- The reinspection reuses `asset_library._inspect` (the 016 inspector). A report with findings
  is rejected, and so is a report with `inspected = False`. In both cases the temp file is
  discarded by the existing `finally`, and neither the DB nor the publish file changes.
- For videos, `ffmpeg` is checked first (the existing `503 ffmpeg_required`), then `ffprobe`
  (`503 metadata_check_unavailable`), both before running ffmpeg.
- No log at any level may contain ffmpeg/ffprobe stderr or output, `exc_info` from them, or
  metadata values. Log the exception class name or the exit code only.
- Out of scope (Feature 031, see `reference-031/`): evidence table, deep container parsers,
  backfill, worker, rules version, streamhash, polling, new endpoints or states, EXIF IFD1
  detection.

---

## Checkpoint A — Minimal backend hardening (US2, US3)

**Goal**: a clean is only accepted after the 016 inspector finds nothing in the result; JPEG
copies drop JFIF thumbnails; tool output never reaches the logs; user-facing texts say *Clean
metadata*.

**Independent test**: the targeted backend tests below pass; the 016 lifecycle (`unknown` →
`clean` / `sanitized`, copy regeneration) still works.

### Implementation

- [X] T001 [US2] In backend/app/asset_library.py `_remove`, right after `_sanitize_to(original, temp, content)` and before `_digest(temp)` and the `clean`/`sanitized` branch, call `_inspect(temp, content)`: if `report.inspected` is false raise `AppError(503, "metadata_check_unavailable", …)`; if `report.findings` is not empty raise `AppError(422, "metadata_not_removed", "Metadata could not be removed safely from this file.")`; rely on the existing `finally: storage.discard(temp)` and make sure no DB write or `storage.commit` happens before the check. Add the two message constants next to the existing ones.
- [X] T002 [US2] In backend/app/asset_library.py `remove_metadata`, for video media add an up-front tool check before taking the guard: keep the 016 `ffmpeg_required` (503) when `shutil.which("ffmpeg")` is None, then return `503 metadata_check_unavailable` when `shutil.which("ffprobe")` is None ("The cleaned file could not be checked, so it was not saved. Videos need ffprobe for this check."), so ffmpeg never runs on a file that cannot be checked.
- [X] T003 [US2] In backend/app/image_metadata.py `_plan_jpeg`: when the APP0 segment whose ident starts with `JFIF\0` has `Xthumbnail·Ythumbnail > 0` or a length greater than 16, replace its `_Copy` by a `_Write` of a 16-byte APP0 (`FFE0`, length 16, `JFIF\0`, the original version, units and X/Y density bytes, thumbnail size `00 00`), all read from the segment `ident`. A minimal JFIF keeps being copied byte for byte, so already-clean JPEGs still give an identical result. JFXX stays dropped (no change to `_jpeg_keep`).
- [X] T004 [US3] In backend/app/image_metadata.py `_inspect_jpeg`: for a kept APP0 `JFIF\0` segment with `Xthumbnail·Ythumbnail > 0`, add `found.add("other", "JFIF thumbnail")`. Use the existing `other` category; JFXX keeps being reported through the existing branch (`APP0:JFXX`).
- [X] T005 [P] In backend/app/video_metadata.py: replace `logger.debug("ffmpeg could not sanitize a video", exc_info=True)` with a message carrying only `type(error).__name__`; replace `logger.debug("ffmpeg failed: %s", completed.stderr[-2000:])` (and its comment) with a message carrying only `completed.returncode`; replace the ffprobe `exc_info=True` in `inspect_video_metadata` with the class name. Change `FFMPEG_MISSING_MESSAGE` to "Cleaning video metadata needs ffmpeg. Install it and try again." and `SANITIZE_FAILED_MESSAGE` to "The metadata could not be cleaned from this video."
- [X] T006 [P] In backend/app/media.py, replace both `logger.debug("ffprobe could not read the video", exc_info=True)` (in `probe_video` and `probe_video_streams`) with messages carrying only the exception class name.
- [X] T007 [P] Rename the action in user-facing messages: `COPY_UNAVAILABLE_MESSAGE` and `COPY_CORRUPT_MESSAGE` ("Use Clean metadata on the media…") in backend/app/content_files.py; `PUBLISHING_MESSAGE` ("…Clean metadata after the upload finishes.") and `INVALID_MEDIA_MESSAGE` ("…its metadata cannot be cleaned safely.") in backend/app/asset_library.py. Leave the "Metadata is being removed…" guard/deletion messages, the internal comments/docstrings and the endpoint path unchanged (research R5).

### Tests

- [X] T008 [P] [US2] Reinspection tests in backend/tests/test_remove_metadata_api.py:
  - (a) a clean temp is accepted: a JPEG with GPS EXIF → `sanitized`, and `GET …/metadata` reports no findings in the copy;
  - (b) a JPEG that is already clean still gives `clean` with no copy;
  - (c) remaining metadata is rejected: monkeypatch `asset_library.sanitize_image` to copy the source unchanged → `422 metadata_not_removed`, status still `unknown`, no `.clean.` file in the media dir, temp dir empty, and the original's bytes and checksum unchanged (reuse `_assert_unchanged`/`_clean_files`);
  - (d) inspection unavailable: monkeypatch `asset_library._inspect` to return `inspected=False` → `503 metadata_check_unavailable` with the same "nothing changed" assertions;
  - (e) the 016 regeneration of a missing copy of a `sanitized` media still ends `sanitized` with a new copy that passes the reinspection.
- [X] T009 [P] [US2] Video tool tests in backend/tests/test_remove_metadata_api.py:
  - keep `test_video_needs_ffmpeg` (all tools missing → `ffmpeg_required`);
  - add a case with `shutil.which` returning a path for `ffmpeg` and None for `ffprobe` → `503 metadata_check_unavailable`, `sanitize_video` never called (spy), status and files unchanged;
  - add a `real_ffprobe` case (skipped without ffmpeg/ffprobe, like `HAS_FFMPEG`): an MP4 with title/location/creation_time tags → `sanitized` and the copy passes the reinspection.
- [X] T010 [P] [US2] JFIF/JFXX tests in backend/tests/test_image_metadata.py, building JPEGs by hand or with Pillow plus segment surgery:
  - JFIF with a 2×2 thumbnail → `inspect_image` reports `other`/"JFIF thumbnail"; `sanitize_image` output has a 16-byte JFIF with thumbnail size 0, identical entropy-coded data, decodes to identical pixels with Pillow, and `inspect_image` on it has no findings;
  - minimal JFIF → output byte-identical to the input;
  - JFXX APP0 → reported as `other` and absent from the output.
- [X] T011 [P] [US3] API test in backend/tests/test_remove_metadata_api.py: cleaning a JPEG with a JFIF thumbnail through `POST …/remove-metadata` → `sanitized`, and `GET …/metadata` lists "JFIF thumbnail" in the original and nothing in the copy.
- [X] T012 [P] Log tests in backend/tests/test_video_metadata.py with `caplog` at DEBUG:
  - point `shutil.which` at fake `ffmpeg`/`ffprobe` scripts written to `tmp_path` that print seeded values (`40.4168`, `iPhone 15`, a prompt string) to stderr and exit 1;
  - run `sanitize_video` (expect `SanitizeFailed`) and `inspect_video_metadata` (expect `inspected=False`);
  - assert no seeded value, no stderr text and no traceback (`record.exc_info is None`) appears in any record;
  - add the same check for `media.probe_video`.

### Checks

- [X] T013 Run T008–T012 (`uv run pytest tests/test_remove_metadata_api.py tests/test_image_metadata.py tests/test_video_metadata.py`, including their `real_ffprobe` cases when ffmpeg is installed), plus `uv run pytest tests/test_content_file_guard.py tests/test_content_files.py` (touched by T007's constants), `uv run ruff check`, `uv run ruff format --check` and `uv run mypy` on the changed files. Review the diff and close Checkpoint A with one commit.

---

## Checkpoint B — Metadata status UI (US1, US2)

**Goal**: every Media Card and the detail header show the badge; **Clean metadata** lives in
the detail header and updates the state at once through `onChanged`.

**Independent test**: vitest with the fake API covers the five combinations, the card, the
header, the action, the refresh and the absence of a duplicate button.

### Implementation

- [X] T014 [P] [US1] Create frontend/src/pages/library/metadata-indicator.ts (pattern of `usage-indicator.ts`): `metadataIndicator(content: Pick<Content, "metadata_status" | "publish_file">)` returns `{tone: "success" | "warning", icon: "check" | "alert", label: "Metadata cleaned" | "Metadata not cleaned", reason, canClean}` per the data-model.md table:
  - `unknown` → Not cleaned yet, `canClean` true;
  - `clean` + available → Already clean;
  - `clean` + unavailable → Media file missing, `canClean` false;
  - `sanitized` + available → Cleaned copy;
  - `sanitized` + unavailable → Clean copy missing, `canClean` true.
- [X] T015 [P] [US2] Create frontend/src/pages/library/useCleanMetadata.ts by moving the existing `handleRemove` logic out of frontend/src/pages/library/FileDetails.tsx: `useCleanMetadata(contentId, onChanged)` returns `{cleaning, error, clean}` and calls the existing `removeMetadata` from frontend/src/api.ts, then `onChanged()`, keeping the API error message via `toApiError`.
- [X] T016 [US1] Show the metadata badge in frontend/src/pages/library/MediaCard.tsx next to the usage badge: `Badge` with tone and icon from `metadataIndicator`, visible label, and the reason in an `ap-visually-hidden` span. Wrap both badges in a row container with `flex-wrap` in frontend/src/pages/library/library.css so they fit at phone width.
- [X] T017 [US2] Add a metadata row to the header of frontend/src/pages/library/MediaDetail.tsx (after the folder row, class `ap-media-detail__metadata`): badge, visible reason and, when `canClean`, a **Clean metadata** button (`loading` while cleaning, label "Cleaning metadata…"), using `useCleanMetadata(content.id, onChanged)`. Show the error with `role="alert"`. Add the row styles in frontend/src/pages/library/library.css (wraps on narrow screens).
- [X] T018 [US3] Update frontend/src/pages/library/FileDetails.tsx:
  - remove the remove button and its state (now in the header);
  - keep *Inspect metadata*, the status text, the report and the checksums;
  - change the texts from "Remove metadata" to "Clean metadata" (e.g. "…Clean metadata again to recreate it…");
  - drop the `onChanged` prop if it becomes unused, updating the call site in MediaDetail.tsx.
- [X] T019 [US2] Extend frontend/src/test-fake-api.ts so `removeMetadataResult` can also simulate `metadata_not_removed` (422) and `metadata_check_unavailable` (503) with their contract messages.

### Tests

- [X] T020 [P] [US1] frontend/src/pages/library/metadata-indicator.test.ts: the five combinations → tone, icon, label, reason and `canClean` (`it.each`).
- [X] T021 [P] [US1] Card tests in frontend/src/pages/library/library.test.tsx (targeted cases): an `unknown` media shows "Metadata not cleaned" with the accessible reason "Not cleaned yet"; a `sanitized` + available media shows "Metadata cleaned"; the usage indicator is still rendered; both badges are inside the wrapping row container (basic mobile check).
- [X] T022 [P] [US2] Detail tests in a new frontend/src/pages/library/media-metadata.test.tsx:
  - the header shows the badge and reason for `unknown`, `clean`, `sanitized` with and without copy;
  - **Clean metadata** calls the endpoint, and after `onChanged` reloads, the badge reads "Metadata cleaned · Cleaned copy" without a page reload and the button disappears;
  - the button is not offered in 🟢 states nor for `clean` + unavailable;
  - the `metadata_not_removed` and `metadata_check_unavailable` errors are shown and the badge stays yellow;
  - there is exactly one "Clean metadata" button in the whole detail (no duplicate in File details).
- [X] T023 [P] [US3] Update frontend/src/pages/library/FileDetails.test.tsx: remove the cases that clicked "Remove metadata" (moved to T022), keep and adapt the Inspect metadata and status-text cases to the new wording, and assert that File details has no clean button.

### Checks

- [X] T024 Run `npx vitest run src/pages/library`, `npm run typecheck` and `npm run lint`. Check the card and the header manually on the safe instance at desktop and phone width (quickstart steps 1, 2 and 7). Review the diff and close Checkpoint B with one commit.

---

## Checkpoint C — Docs, regressions and close

**Goal**: documentation matches the real behaviour and the feature passes the closing checks.

- [ ] T025 Update the "Remove metadata" section of docs/asset-library.md:
  - rename it to "Clean metadata";
  - add the badge and the meaning of each combination (it answers "has AutoPublisher run its cleaning on this media?", not a forensic check);
  - add the post-clean reinspection and the two new errors;
  - note that videos need ffmpeg **and** ffprobe to be cleaned;
  - add the JFIF thumbnail removal and the no-raw-tool-output logging rule;
  - add the new accepted risks: copies cleaned before 028 are not re-checked, and a damaged same-size copy stays green until publishing;
  - add a pointer to Feature 031 for verification and hardening.
- [ ] T026 Mark spec.md **Status** as implemented, refresh specs/028-metadata-hygiene/checklists/requirements.md notes to the minimal scope, and run the manual validation of quickstart.md scenarios 1–8 on a safe instance (`AUTOPUBLISHER_CONFIG` + fail keyring), recording the result in this file.
- [ ] T027 Close the feature once:
  - run any targeted tests still pending, and the 016 regressions only if code they cover changed after A/B;
  - run `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `npm run lint`, `npm run typecheck`, `npm run build` and `git diff --check`;
  - do a security review of the diff (no logging of values or tool output, no new data exposure);
  - close Checkpoint C with one commit;
  - do not run the full pytest/vitest suites locally: the PR CI runs them.

---

## Dependencies & execution order

```text
A ──► B ──► C
```

- **A** is independent: backend only, and the endpoint contract stays compatible (new error
  codes only).
- **B** depends on A only for the two new error messages it shows. Badges, header and action
  work against the existing API, so B could be built in parallel with A, but it closes after A
  to keep the commits in order.
- **C** goes last.

## Parallel opportunities

- A: T005, T006 and T007 in parallel with T001–T004; tests T008–T012 in parallel once the
  implementation is done.
- B: T014 and T015 in parallel; tests T020–T023 in parallel.

## Implementation strategy

- **MVP**: A + B. The badge and the verified clean are complete. C is documentation and closing.
- Stop after every checkpoint commit and report before starting the next one.
- Targeted tests only; other areas run only when a task touches them, and they are named in the
  checkpoint's checks task.
