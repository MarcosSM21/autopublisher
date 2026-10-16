---

description: "Task list for Asset Library, Usage & Metadata (Feature 016)"
---

# Tasks: Asset Library, Usage & Metadata

**Input**: Design documents from `specs/016-asset-library-metadata/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md)

**Tests**: pedidos por la spec y el plan, **solo para código propio**: agregado de uso,
resolvedor, guard/claim, sanitizadores (con centinelas ComfyUI, archivos sintéticos generados
en el test), API, regresiones de los publishers afectados y componentes del frontend. Nada de
tests de internals de Pillow/ffmpeg. Los tests de cada bloque se escriben antes o junto a su
implementación. **Un fixture representativo por formato/caso** que agrupa varios centinelas;
nada de un test por campo ni matrices `formato × metadata × estado × error`. Durante el
desarrollo solo los tests del bloque tocado; **la suite completa (pytest y vitest) solo en la
CI del PR**, nunca en local. Lint/format/typecheck/build: una sola vez al final (T046).

**Organization**: por historia de usuario en orden de prioridad (US1 P1 → US3 P1 → US2 P2 →
US4 P2 → US5 P3). Código, comentarios, mensajes de API/UI, docs y commits en inglés.

> ## ⛔ Límites de `/speckit-implement`
>
> 1. **STOP en T028 (checkpoint V1 PNG)**: el PNG real de ComfyUI sanitizado con
>    `sanitize_image` NO debe permitir reconstruir el workflow en ComfyUI. Continuar solo con
>    PASS registrado en `quickstart.md → Resultados`. Si el workflow es recuperable: STOP y
>    revisar research §7.
> 2. **STOP en T045 (V1 completa)**: no cerrar la feature sin V1 PASS en todos los formatos de
>    ComfyUI que se usen realmente (SC-001).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivo distinto, sin dependencias pendientes).
- **[Story]**: US1 uso y tarjeta · US2 búsqueda/filtros · US3 Remove metadata · US4
  inspección y detalle técnico · US5 dedupe de copia limpia.

## Path Conventions

Backend en `backend/app/`, `backend/migrations/versions/` y `backend/tests/`; frontend en
`frontend/src/`; CI en `.github/workflows/ci.yml`; docs en `README.md` y `docs/`.

---

## Phase 1: Setup

- [X] T001 [P] Install ffmpeg in the backend job of `.github/workflows/ci.yml` (`sudo apt-get update && sudo apt-get install -y ffmpeg` before `uv run pytest`) so video sanitization tests run in CI (research §11)

---

## Phase 2: Foundational (bloquea todas las historias)

- [X] T002 Add `MetadataStatus` (`unknown`/`clean`/`sanitized`) and the five columns `metadata_status` (server default `unknown`), `sanitized_storage_path` (unique, nullable, never exposed), `sanitized_checksum`, `sanitized_size_bytes`, `sanitized_at` to `Content` in `backend/app/models.py`, with the two CHECK constraints of data-model.md (sanitized ⇒ all four set; otherwise all four NULL) and the `metadata_status` value CHECK
- [X] T003 Create migration `backend/migrations/versions/0015_content_metadata_sanitization.py` (revises `0014`, `batch_alter_table`, existing rows become `unknown`; downgrade drops the columns and documents that `.clean` files are left on disk) and add one test to `backend/tests/test_migrations.py` (upgrade keeps an existing content as `unknown`, one inconsistent `sanitized` row is rejected, downgrade runs)
- [X] T004 Create `backend/app/content_files.py` with `EffectiveFile(path, checksum, size, clean_copy)`, `ContentFileUnavailable(code, message)` and `resolve_publish_file(storage, content, *, verify)` exactly as research §3 (`unknown`/`clean` → original; `sanitized` → copy; `verify=False` = exists + size via `stat`; `verify=True` adds full SHA-256 of the clean copy only; codes `media_unavailable` / `media_corrupt`; never returns the original path for a `sanitized` content), plus `effective_checksum_sql()` (the `CASE` expression of data-model.md)
- [X] T005 [P] Write `backend/tests/test_content_files.py` (the strong tests of the effective-file contract; publishers are not re-tested for these cases): parametrized unknown/clean → original and sanitized → copy (path, checksum, size); parametrized copy missing / wrong size / wrong SHA with `verify=True` → `ContentFileUnavailable` with the right code and never the original path; `verify=False` accepts a same-size corrupted copy (no hashing outside `prepare`)
- [X] T006 Extend `ContentRead` in `backend/app/schemas.py` with `metadata_status`, `publish_file` (`version` `original`/`clean_copy`, `available`, `checksum`, `size_bytes`, `sanitized_at`) and `usage` (`ContentUsageRead`: `used`, `publication_count`, `published_count`, `awaiting_count`, `scheduled_count`, `platforms`, `last_published_at`) per contracts/api.md; `content_to_read` in `backend/app/contents.py` fills `publish_file` with `resolve_publish_file(..., verify=False)` (unavailable → `available=false`, never the original for `sanitized`) and accepts a precomputed usage (empty usage when absent)
- [X] T007 [P] Add the new `Content` fields and types (`MetadataStatus`, `PublishFile`, `ContentUsage`) to `frontend/src/types.ts` and default values for them in `frontend/src/test-fake-api.ts`

**Checkpoint**: `uv run pytest tests/test_migrations.py tests/test_content_files.py tests/test_contents_api.py` en verde; comportamiento de la app idéntico (todo `unknown`).

---

## Phase 3: User Story 1 — Ver qué assets he usado y dónde (P1) 🎯 MVP

**Goal**: la biblioteca se presenta como Asset Library; cada tarjeta muestra `Unused` o las plataformas, `Scheduled`, `Ready in TikTok` y el badge de metadata; el detalle muestra el historial de uso.

**Independent Test**: proyecto con contenidos sin publicaciones, publicados, programados, fallidos, cancelados, inciertos y en `awaiting_user_action` → tarjetas e historial correctos (spec US1).

- [X] T008 [P] [US1] Write `backend/tests/test_asset_usage.py` with one project fixture holding one content per representative case (unused; published on two platforms; awaiting_user_action only; scheduled only; failed + cancelled; failed with uncertain attempt; plus a text-only publication) and three tests: (1) one parametrized test over that fixture asserting `used`, counts, `platforms`, `last_published_at` (whole FR-003…FR-006 rule in one table); (2) the listing query count does not grow with N contents (`before_cursor_execute` counter); (3) `GET /api/contents/{id}/usage` order, `uncertain` flag and no internal paths
- [X] T009 [US1] Create `backend/app/asset_library.py` with `usage_by_content(session, project_id, content_ids=None) -> dict[int, ContentUsageRead]` (the two queries of research §1) and router `GET /api/contents/{content_id}/usage` (schemas `AssetUsageRead`, `AssetPublicationRead` in `backend/app/schemas.py`); include the router in `backend/app/main.py`
- [X] T010 [US1] Use `usage_by_content` in `list_contents` and in the single-content responses (`get_content`, `update_content`, import results) of `backend/app/contents.py` so every `ContentRead` carries its usage
- [X] T011 [P] [US1] Add `getContentUsage(contentId)` to `frontend/src/api.ts` and its fake in `frontend/src/test-fake-api.ts`
- [X] T012 [US1] Rework the card in `frontend/src/components/ContentLibrary.tsx`: heading/aria-label "Asset Library", preview, `title ?? original_filename`, Image/Video badge, `Unused` or platform names (existing `platformLabel` in `types.ts`), `Scheduled` when `scheduled_count > 0`, `Ready in TikTok` when `awaiting_count > 0`, `Metadata clean` when `metadata_status` is `clean` or `sanitized` and nothing for `unknown` (FR-008a); remove the date and never show checksum/MIME/size/dimensions/duration; rename the tab label in `frontend/src/components/ProjectDetail.tsx`
- [X] T013 [P] [US1] Create `frontend/src/components/AssetUsage.tsx`: loads `getContentUsage`, shows counts, last confirmed publication, scheduled publications and one row per publication (platform, account, status — `awaiting_user_action` as "Ready in TikTok", never "Published" —, dates, "Uncertain" badge, link when `external_url`); render it from `frontend/src/components/ContentDetail.tsx`
- [X] T014 [P] [US1] Frontend tests of visible behaviour only: in `frontend/src/components/ContentLibrary.test.tsx` one render with a few representative contents (unused/unknown, used on platforms + Scheduled, Ready in TikTok, sanitized → `Metadata clean`) asserting the texts and that no checksum/size appears (no badge combinations beyond that); new `frontend/src/components/AssetUsage.test.tsx` with one history render (awaiting shown as Ready in TikTok, uncertain marker); adjust existing assertions broken by the rename in `ContentLibrary.test.tsx`/`ProjectDetail.test.tsx`

**Checkpoint**: `uv run pytest tests/test_asset_usage.py tests/test_contents_api.py` y `npx vitest run src/components/ContentLibrary.test.tsx src/components/AssetUsage.test.tsx` en verde.

---

## Phase 4: User Story 3 — Remove metadata (P1)

**Goal**: `Remove metadata` crea una copia sanitizada (o marca `clean`), el original no cambia y todas las publicaciones futuras usan el archivo efectivo, sin fallback y sin carreras con la publicación.

**Independent Test**: PNG/JPEG/WEBP/vídeo con centinelas ComfyUI → sin centinelas, válidos, visualmente iguales, original intacto; publicar envía la copia; copia ausente → `media_unavailable` (spec US3).

### Archivo efectivo en el core y los publishers

- [X] T015 [US3] Add `ContentFileGuard` to `backend/app/content_files.py` (`threading.Lock` + `set[int]`; `sanitizing(content_id, check)` context manager raising `409 metadata_removal_in_progress` if already present and running `check(session)` under the lock; `claiming(content_id)` context manager raising `409 content_metadata_busy`), add the conflict codes `metadata_removal_in_progress`, `content_publishing`, `content_metadata_busy`, `content_file_changed` to `backend/app/errors.py`, and create one guard on `app.state.content_file_guard` in `backend/app/main.py`
- [X] T016 [US3] Core change in `backend/app/publishing.py` (research §4): `PreparedPublication.file_checksum: str | None = None`; `PublishContext.file_guard` (default `ContentFileGuard()`, wired to `app.state.content_file_guard` in `main.py`); in `create_running_attempt`, for publications with content: reject a missing `file_checksum` as `internal_error`, add the `EXISTS` effective-checksum condition and run UPDATE+commit inside `file_guard.claiming(content_id)`; `_not_startable` returns `content_file_changed` when the effective checksum differs; messages exactly as contracts/api.md; on a lost race nothing changes (status, arming, no attempt); update the fake publisher in `backend/tests/fakes.py` (and the direct `PreparedPublication(...)` in `backend/tests/test_tiktok_publish.py`) to set `file_checksum` for content publications, otherwise the core tests break
- [X] T017 [US3] Add `content_metadata_busy` and `content_file_changed` to `NOT_CLAIMED_CODES` in `backend/app/scheduler.py`
- [X] T018 [P] [US3] Migrate `backend/app/youtube_publishing.py` to `resolve_publish_file` (`check` with `verify=False`, `prepare` with `verify=True` as last local step, effective path/size in `total_bytes`, `file_size`, label; set `file_checksum`; map `ContentFileUnavailable` to `media_unavailable`/`media_corrupt` problems)
- [X] T019 [P] [US3] Migrate `backend/app/instagram_publishing.py` the same way, including `fingerprint(...)` with the effective checksum and the delivery source/size
- [X] T020 [P] [US3] Migrate `backend/app/threads_publishing.py` the same way (availability, size check, `file_path`, `file_size`)
- [X] T021 [P] [US3] Migrate `backend/app/telegram_publishing.py` the same way (photo/video limits with the effective size, `file_path`, `file_size`, `total_bytes`)
- [X] T022 [US3] Migrate `backend/app/tiktok_publishing.py` and `backend/app/tiktok_media.py`: `inspect_video` and the chunk plan with the effective size, `consent_fingerprint(video_sha256=effective checksum)` everywhere it is computed, replace the own SHA check in `prepare` by `resolve_publish_file(verify=True)` (keep `tiktok_video_changed` for the original, `media_corrupt` for the clean copy), payload `checksum`, `file_size`, `total_bytes`, `file_checksum`
- [X] T023 [US3] Write `backend/tests/test_publish_effective_file.py` (missing/corrupt copy cases stay in T005, not per publisher):
  - one parametrized test over the publishers' `prepare()` (YouTube, Instagram, Threads, Telegram, TikTok Direct) with a sanitized content: `file_path` is the clean copy, `file_checksum`/`total_bytes`/`submitted["file_size"]` are the effective values; plus the sensitive checks only: Instagram `fingerprint` uses the effective checksum, Telegram/Threads size limits use the effective size, TikTok chunk plan uses the effective size;
  - one generic mapping test: copy missing → preflight problem `media_unavailable` through `local_check` (any one publisher), no attempt;
  - TikTok: a consent confirmed before sanitizing is no longer valid;
  - race (manual and scheduler share `start_publication`/`create_running_attempt`, so tested once at that level): (a) claim while the guard holds the content → `409 content_metadata_busy`, publication unchanged (status, arming, no attempt), retry after release starts; (b) `prepare` before sanitizing + commit of the sanitization + claim → `409 content_file_changed`, unchanged; (c) content publication without `file_checksum` → rejected; plus one scheduler test: `_start` returns `not_claimed` for these codes and records no auto-publish failure. "Publishing wins → Remove metadata rejected" lives in T033
- [X] T024 [US3] Run only the regressions of the code touched in T016–T022 and fix fallout: core claim (`tests/test_publish_concurrency.py tests/test_publish_service.py tests/test_publish_preflight.py tests/test_publish_upload.py tests/test_scheduler_concurrency.py tests/test_scheduler_tick.py`) and the sensitive publisher paths (`tests/test_tiktok_consent.py tests/test_tiktok_fingerprint.py tests/test_tiktok_chunks.py tests/test_tiktok_preflight.py tests/test_tiktok_publish.py tests/test_tiktok_inbox_publish.py tests/test_instagram_publish.py tests/test_threads_publish_image.py tests/test_threads_publish_video.py tests/test_telegram_publishing.py tests/test_youtube_upload.py`); everything else is left to the PR CI

### Sanitizador de imágenes

- [X] T025 [US3] Create `backend/app/image_metadata.py`: streaming walkers for PNG chunks (CRC checked incrementally), JPEG segments (entropy-data automaton handling `FF00`, `RSTn` and a `FF` split across reads; stop at `EOI`) and RIFF/WEBP chunks (rebuild `ANMF`, rewrite `VP8X` flags and RIFF size); a minimal TIFF IFD0 reader (seek-based) for Orientation; `sanitize_image(src, dst, fmt)` with the whitelists of research §7, blocks copied verbatim in `config.CHUNK_SIZE` pieces, byte-identical output when nothing is removed, `InvalidMediaError` on broken structure
- [X] T026 [US3] Add the regenerated minimal EXIF (single IFD0 entry `0x0112`, only for Orientation 2–8) to `backend/app/image_metadata.py` with the placement of research §7: JPEG `APP1` after `SOI`/`APP0 JFIF`; PNG `eXIf` before the first `IDAT`; extended WEBP `EXIF` after the image data with the `VP8X` EXIF flag (FR-025a)
- [X] T027 [P] [US3] Write `backend/tests/test_image_metadata.py` with **one dirty fixture per format** generated in the test, each grouping all sentinels (workflow, prompt, parameters/`extra_pnginfo`, seed, checkpoint, LoRA, sampler, local path, custom-node key, GPS, device, dates) and Orientation=6: PNG (APNG with `iCCP`, sentinels spread over `tEXt`/`zTXt`/`iTXt`/`eXIf`/`tIME`/`comf`/private chunk/data after `IEND`); JPEG (progressive, ICC, EXIF, XMP, APP13, COM, `JFXX`, MPF, trailer); WEBP (extended, animated, alpha, ICC, EXIF, XMP). Tests, parametrized by format: (1) sanitize the dirty fixture → no sentinel in the output bytes, only whitelisted blocks, the only EXIF is the one-entry Orientation block, same pixels/frames/alpha/ICC as the original (one comparison, as our appearance contract); (2) an already-clean file → byte-identical output; (3) a truncated file → `InvalidMediaError`. Plus one JPEG test with a tiny read size for the split-`FF` path. No per-field tests
- [X] T028 [US3] **⛔ Checkpoint V1 PNG**: with a private ComfyUI PNG (never committed), run `sanitize_image` from a throwaway local script/REPL, drag the result into ComfyUI and confirm the workflow is NOT reconstructed (original first confirmed to load it); record PASS/FAIL in `specs/016-asset-library-metadata/quickstart.md → Resultados`. STOP on FAIL

### Sanitizador de vídeo

- [X] T029 [US3] Create `backend/app/video_metadata.py` with `sanitize_video(src, dst, fmt)` running exactly the ffmpeg command of research §8 (`-map 0:V -map 0:a? -c copy -map_metadata -1 -map_metadata:s -1 -map_chapters -1`, bitexact flags, `+faststart` for mp4/mov, explicit `-f`, 10-minute timeout), `FfmpegMissing` when `shutil.which("ffmpeg")` is `None`, `SanitizeFailed` with a safe message (stderr only at debug level)
- [X] T030 [P] [US3] Write `backend/tests/test_video_metadata.py`: one test parametrized over MP4/MOV/WEBM (`skipif` without ffmpeg, as in `test_ffprobe_integration.py`) on a tiny synthetic file carrying a JSON `comment` sentinel, `location`, `creation_time`, chapters and 90° rotation (rotation only for MP4/MOV) → no sentinel in the output bytes, no chapters, rotation and duration kept; plus one non-skipped test: ffmpeg missing → `FfmpegMissing`

### Operación Remove metadata

- [X] T031 [US3] Implement `POST /api/contents/{content_id}/remove-metadata` in `backend/app/asset_library.py` following research §5 under `ContentFileGuard.sanitizing` (check no `publishing` publication): idempotent for `clean` and verified `sanitized`; temp file in `tmp/`; SHA equal to the original → `clean` without copy; otherwise `storage.commit` to `projects/{project_id}/{uuid}.clean{ext}` + conditional UPDATE (`metadata_status`/`sanitized_storage_path` as read, `NOT EXISTS` publishing) with compensation (`storage.discard`) on DB failure; regeneration of a missing/corrupt copy with a new path and deletion of the old `.clean`; errors of contracts/api.md (`ffmpeg_required` 503, `invalid_media` 422, `sanitize_failed`/`storage_error` 500, 409s); allowed for inactive projects; never opens the original for writing
- [X] T032 [US3] Add `sweep_orphan_clean_copies(session, storage)` to `backend/app/content_files.py` (only names containing `.clean.` under `projects/*/`, unreferenced by `sanitized_storage_path`) and call it at start-up in `backend/app/main.py` after migrations and before the scheduler
- [X] T033 [US3] Write `backend/tests/test_remove_metadata_api.py` with image contents only (video sanitization is covered in T030):
  - lifecycle: unknown → sanitized (original bytes/checksum unchanged, `publish_file.version = clean_copy`, no internal path in the response) → second call does no work → delete the copy → call regenerates it with a new path;
  - already-clean file → `clean`, no copy;
  - rejections: publication `publishing` → `409 content_publishing`; guard already holding the content → `409 metadata_removal_in_progress`; video with ffmpeg missing → `503 ffmpeg_required` (mapping only);
  - atomicity: sanitizer failure → state unchanged, no files left; DB failure after the move → copy deleted;
  - start-up sweep deletes an orphan `.clean` file and keeps originals and referenced copies
- [X] T034 [P] [US3] Add `removeMetadata(contentId)` to `frontend/src/api.ts` and its fake in `frontend/src/test-fake-api.ts`
- [X] T035 [US3] Create `frontend/src/components/AssetFile.tsx` (rendered from `ContentDetail.tsx`): metadata state texts of FR-013a (unknown / clean "the original was already clean, it is published as is" / sanitized "metadata was removed; the clean copy is published"), version that will be published, `Remove metadata` button (visible for `unknown` and for `sanitized` with `publish_file.available = false`), busy state, contract errors shown, library reloaded on success
- [X] T036 [P] [US3] Write `frontend/src/components/AssetFile.test.tsx`: Remove metadata success (unknown → sanitized text), one error shown (e.g. `content_publishing`), clean vs sanitized texts, button hidden for `clean`

**Checkpoint**: tests dirigidos de T023, T027, T030, T033 y T036 en verde. Sin validación manual adicional aquí (solo T028 y T045).

---

## Phase 5: User Story 2 — Buscar y filtrar (P2)

**Goal**: búsqueda por título/nombre de archivo y filtros `All`/`Images`/`Videos`/`Used`/`Unused`.

**Independent Test**: biblioteca mixta → cada filtro, búsqueda sin mayúsculas, combinaciones y estado vacío del filtro (spec US2).

- [X] T037 [US2] Add to `frontend/src/components/ContentLibrary.tsx` a search box (case-insensitive substring over `title` and `original_filename`) and a filter button group with `aria-pressed` (`All`, `Images`, `Videos`, `Used`, `Unused` using `usage.used`), combined; a "No assets match" empty state distinct from the empty-library message
- [X] T038 [P] [US2] Extend `frontend/src/components/ContentLibrary.test.tsx` with two tests: search (title match, filename match, case-insensitive) and filters (Images, Used with a Ready-in-TikTok asset, Unused with a scheduled-only asset, combined with search, filter empty state)

---

## Phase 6: User Story 4 — Inspeccionar metadata y detalle técnico (P2)

**Goal**: el detalle muestra datos técnicos y la versión publicada, y `Inspect metadata` lista categorías del original y de la copia.

**Independent Test**: archivos con/sin metadata conocida → categorías esperadas; asset sanitizado → la copia sin categorías sensibles (spec US4).

- [X] T039 [US4] Add `inspect_image(src, fmt) -> FileMetadataReport` to `backend/app/image_metadata.py` (keyword-based PNG text classification without decompressing; EXIF via the TIFF reader: orientation-only IFD0 reports nothing, GPS → location, Make/Model → device or comfyui by bounded prefix, Software, dates; XMP, IPTC, COM, `tIME`, unknown/trailers → other) and `inspect_video_metadata(path)` to `backend/app/video_metadata.py` (ffprobe JSON → categories of research §9; `inspected=false` with reason when ffprobe is missing)
- [X] T040 [US4] Implement `GET /api/contents/{content_id}/metadata` in `backend/app/asset_library.py` (schemas `MetadataReportRead`, `FileMetadataReportRead`, `MetadataFindingRead` in `backend/app/schemas.py`): `original` + `publish_copy` per contracts/api.md; only category, label and key names, never values; nothing logged
- [X] T041 [P] [US4] Reuse the dirty fixtures instead of new files: in `backend/tests/test_image_metadata.py` add one test parametrized by format — `inspect_image` on the dirty fixture finds the expected categories (PNG `comfyui`/`ai_generation`/`comments`; JPEG `location`/`device`/`dates`/`exif`/`xmp`/`iptc`; WEBP `comfyui` via Make) and on its sanitized output finds nothing (covers orientation-only EXIF); in `backend/tests/test_video_metadata.py` extend the parametrized test to check `inspect_video_metadata` before (comfyui/location) and after (nothing); in `backend/tests/test_remove_metadata_api.py` one `GET /metadata` test on a sanitized content asserting `original` + `publish_copy` and that no sentinel value appears in the response
- [X] T042 [US4] Extend `frontend/src/components/AssetFile.tsx` with the technical details (size, dimensions, duration, format, checksum, original filename, effective size/checksum) and an `Inspect metadata` button listing findings for the original and the publish copy ("No sensitive metadata found" when empty, reason when not inspected); add `inspectContentMetadata` to `frontend/src/api.ts`/`test-fake-api.ts` and one test to `frontend/src/components/AssetFile.test.tsx` (findings rendered for original and copy)

---

## Phase 7: User Story 5 — Dedupe de la copia limpia (P3)

**Goal**: importar un archivo idéntico a una copia sanitizada del mismo proyecto se detecta como duplicado.

**Independent Test**: sanitizar, importar la copia en el mismo proyecto → `duplicate`; en otro proyecto → importado (spec US5).

- [X] T043 [US5] Extend `find_duplicate` in `backend/app/contents.py` to match `checksum == X OR sanitized_checksum == X` within the project (also used by the IntegrityError path)
- [X] T044 [P] [US5] Add one test to `backend/tests/test_contents_import.py`: importing the clean copy into the same project → `duplicate` pointing at the original content, and into another project → `imported`

---

## Phase 8: Polish & Cross-Cutting

- [X] T045 **⛔ V1 completa + validación manual**: in the real app (backend + frontend running), run quickstart A and the in-app checks of B, and V1 for every ComfyUI format actually used (at least PNG; WEBP/MP4/WEBM if used), taking the sanitized copy from the media directory; **no real publications to external platforms** (B.6/B.8 are covered by T023) unless a specific gap appears; record results in `specs/016-asset-library-metadata/quickstart.md → Resultados`. STOP if any workflow is recoverable
- [X] T046 Light local close (no full `pytest`, no full `npm test`, no re-run of regressions already green): update `README.md` (and `docs/` where relevant) — Asset Library, `Remove metadata` (original untouched, clean copy used automatically, no fallback), ffmpeg needed only for video metadata removal, ExifTool not required, accepted risks (Ultra HDR/gain maps, Motion/Live Photo, videos always copied, encoder strings in bitstream); run any targeted tests still pending; run once `uv run ruff check . && uv run ruff format --check . && uv run mypy .` and `npm run lint && npm run format:check && npm run typecheck && npm run build`; `git diff --check`; security review of the diff (no private media or test files with real workflows, no internal paths or metadata values in responses/logs); mark tasks done. The full suites run in the PR CI; the feature is closed only when that CI is green (fix failures with targeted local tests and push)

---

## Dependencies & Execution Order

- **Setup (T001)**: independiente.
- **Foundational (T002–T007)**: bloquea todo. T003 depende de T002; T004 de T002; T006 de T004.
- **US1 (T008–T014)**: tras Foundational. MVP.
- **US3 (T015–T036)**: tras Foundational; independiente de US1 en backend (la tarjeta muestra `Metadata clean` gracias a T012, pero US3 se prueba por API/detalle).
  - T015 → T016 → T017; T018–T022 tras T016; T023 tras T018–T022; T024 al final del bloque.
  - T025 → T026 → T027 → **T028 (STOP)**.
  - T029 → T030.
  - T031 tras T015, T025/T026, T029; T032 y T033 tras T031; T034–T036 tras T031.
- **US2 (T037–T038)**: tras US1 (usa `usage.used` y la tarjeta nueva).
- **US4 (T039–T042)**: tras T025 (walkers) y T029 (módulo vídeo); T041 reutiliza los fixtures de T027/T030/T033; T042 tras T035.
- **US5 (T043–T044)**: tras T031 (necesita contenidos sanitizados).
- **Polish (T045–T046)**: al final.

## Parallel Opportunities

- Phase 2: T005 y T007 en paralelo con T006.
- US1: T008, T011, T013 y T014 en paralelo una vez hecho T009/T010.
- US3: T018–T021 en paralelo (archivos distintos); T027 y T030 en paralelo con la operación; T034 y T036 en paralelo.
- US2/US4/US5: T038, T041, T044 en paralelo con sus implementaciones.

```text
# Ejemplo US3 tras T016:
T018 youtube_publishing.py | T019 instagram_publishing.py | T020 threads_publishing.py | T021 telegram_publishing.py
# Luego T022 (TikTok, dos archivos) y T023
```

## Implementation Strategy

1. **MVP**: Setup + Foundational + US1 → la Asset Library ya responde "¿lo he usado y dónde?".
2. **US3** (prioridad real de la feature): archivo efectivo + carrera → sanitizador de
   imágenes → **STOP V1 PNG** → vídeo → operación + UI.
3. US2, US4, US5 como incrementos pequeños.
4. Cierre: V1 completa, docs, lint/type/build locales y suite completa en la CI del PR.

Commits pequeños sugeridos: foundational (modelo+migración+resolvedor), uso (US1), archivo
efectivo + publishers, sanitizador de imágenes, sanitizador de vídeo, operación + UI,
búsqueda/filtros, inspección, dedupe, docs.
