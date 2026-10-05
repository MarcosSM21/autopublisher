---

description: "Task list for the content library and local media import feature"
---

# Tasks: Biblioteca de contenido e importación local de imágenes y vídeos

**Input**: Design documents from `specs/003-content-library/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/api.md](contracts/api.md), [quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (SC-008):

- importación de imagen y de vídeo válidos;
- importación múltiple;
- persistencia del contenido y del archivo copiado;
- edición de metadata;
- asociación con el proyecto;
- rechazo de proyecto inexistente y de formato inválido;
- duplicados por checksum;
- fallo parcial de lote;
- drag & drop y biblioteca en el frontend.

En cada historia los tests se escriben primero y deben fallar antes de implementar.

**Organization**: tareas agrupadas por historia de usuario. Todo el código, comentarios,
mensajes de API/UI, README y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1–US5)

## Path Conventions

- Backend: `backend/app/`, `backend/migrations/versions/`, `backend/tests/`
- Frontend: `frontend/src/`, `frontend/src/components/`
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

## Reglas transversales (aplican a todas las tareas)

- Sin capa de servicios ni repositorios: la lógica de la API vive en el router
  `backend/app/contents.py`, apoyada en `media.py` (entender el archivo) y `storage.py`
  (sistema de archivos). Sin rutas `DELETE`.
- **Nunca cargar un archivo completo en memoria**:
  - las subidas se leen con `upload.file.read(CHUNK_SIZE)` (1 MiB) en un bucle;
  - prohibido `read()` sin tamaño o acumular bloques;
  - todo lo posterior (firma, Pillow, `ffprobe`) trabaja sobre el temporal en disco.
- **Temporales**: siempre en `<media_dir>/tmp/` (mismo filesystem que `<media_dir>/projects/`).
  El procesamiento de cada archivo va en `try/finally`, que borra el temporal ante
  cualquier rechazo o excepción. Al arrancar se vacía `tmp/`.
- **Orden de persistencia por archivo**:
  1. validar;
  2. comprobar duplicado;
  3. `session.add` + `session.flush()`;
  4. solo entonces `os.replace` a la ruta final;
  5. `session.commit()`.

  Si `flush` o `commit` fallan: `session.rollback()` y borrar el archivo final si ya se
  movió.
- El nombre original nunca participa en rutas de disco. En la base solo se guarda la ruta
  **relativa** a la raíz multimedia; la API nunca expone rutas (ni relativas ni absolutas).
- `created_at`/`updated_at` los asigna el código (no `onupdate`). En el `PATCH`, `updated_at`
  solo cambia si algún valor normalizado difiere del almacenado (FR-021).
- Errores de petición con el formato existente ([contracts/api.md](contracts/api.md));
  rechazos por archivo dentro del cuerpo `200` de `ImportResult`.
- Los catálogos `MediaType`/`MediaFormat` se duplican en backend (`StrEnum`) y frontend
  (`types.ts`), con un comentario en cada lado que apunte al otro.
- Ningún archivo multimedia se versiona: los tests generan sus datos en memoria o en
  `tmp_path`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: añadir las dependencias nuevas.

- [X] T001 Run `uv add python-multipart pillow` in `backend/` so that `backend/pyproject.toml` lists both as runtime dependencies and `backend/uv.lock` is updated; if mypy reports missing stubs for Pillow, rely on Pillow's bundled type hints (Pillow ≥ 10 ships `py.typed`) and do not add ignores unless strictly needed

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: modelo, migración, configuración multimedia, detección de formato,
almacenamiento, esquema de salida, fixtures de test y tipos/cliente del frontend.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta completar esta fase.

### Backend

- [X] T002 [P] Extend `backend/app/config.py` with:
  - `get_media_dir() -> Path`: returns `Path(os.environ["AUTOPUBLISHER_MEDIA_DIR"])` when set
    and non-empty, otherwise `BACKEND_DIR / "data" / "media"`;
  - constants `MAX_FILE_SIZE = 2 * 1024**3`, `MAX_FILES_PER_IMPORT = 100`,
    `MAX_FILENAME_LENGTH = 255` and `CHUNK_SIZE = 1024 * 1024`.
- [X] T003 [P] Add to `backend/app/models.py`:
  - `MediaType(StrEnum)`: `image`, `video`.
  - `MediaFormat(StrEnum)`: `jpeg`, `png`, `webp`, `mp4`, `mov`, `webm`. Comment: keep in
    sync with `frontend/src/types.ts`.
  - Model `Content` (`__tablename__ = "contents"`) with the columns of
    [data-model.md](data-model.md):
    - `project_id`: FK `projects.id` `ondelete="RESTRICT"`;
    - `media_type`: `String(10)`; `media_format`: `String(10)`;
    - `storage_path`: `String(255)`, `unique=True`;
    - `original_filename`: `String(255)`; `checksum`: `String(64)`; `size_bytes`: `int`;
    - `width`, `height`: `int | None`; `duration_seconds`: `float | None`;
    - `title`: `String(200)`, nullable; `description`: `String(5000)`, nullable;
    - `hashtags`: `Mapped[list[str]]` with `JSON`, `default=list`;
    - `created_at`, `updated_at`: `UTCDateTime`.
  - `__table_args__ = (UniqueConstraint("project_id", "checksum"),
    Index("ix_contents_project_id_created_at", "project_id", "created_at"))`; the unique
    constraint name comes from the existing naming convention.
- [X] T004 Create `backend/migrations/versions/0002_create_contents.py`:
  - `down_revision` is the 0001 revision id;
  - creates table `contents` exactly matching the `Content` model (same constraint and
    index names as produced by the naming convention) so the existing schema-drift test in
    `backend/tests/test_migrations.py` passes;
  - `downgrade` drops the table.

  Depends on T003.
- [X] T005 [P] Create `backend/app/media.py`:
  - `detect_format(header: bytes) -> MediaFormat | None`, implementing exactly the
    signatures of [research.md](research.md) decision 3:
    - JPEG `FF D8 FF`;
    - PNG 8-byte signature;
    - WebP `RIFF` + `WEBP` at bytes 8–11;
    - `ftyp` at bytes 4–7: major brand at bytes 8–11 `qt  ` → MOV; brand in
      `MP4_BRANDS = {"isom","iso2","iso4","iso5","iso6","mp41","mp42","avc1","M4V ","mmp4","dash","MSNV"}`
      → MP4; anything else → `None`;
    - EBML `1A 45 DF A3` whose header (first 4096 bytes) contains the DocType element
      (`42 82`) followed by a length byte and `webm` → WebM; `matroska` → `None`.
  - `HEADER_SIZE = 4096`.
  - `media_type_of(fmt) -> MediaType`, `EXTENSIONS: dict[MediaFormat, str]`
    (`.jpg`, `.png`, `.webp`, `.mp4`, `.mov`, `.webm`) and `MIME_TYPES: dict[MediaFormat,
    str]` (`video/quicktime` for MOV).
  - `read_image_info(path: Path, fmt: MediaFormat) -> tuple[int, int]`:
    - opens with `PIL.Image.open(path)` in a `with` block (no pixel decoding);
    - verifies that `image.format` matches the detected format (`JPEG`/`PNG`/`WEBP`);
    - returns `image.size`;
    - raises `InvalidMediaError` on any Pillow error, mismatch, `Image.DecompressionBombError`
      or `DecompressionBombWarning` (turn warnings into errors with
      `warnings.catch_warnings()` + `simplefilter("error", Image.DecompressionBombWarning)`).
  - `probe_video(path: Path) -> VideoInfo` (a dataclass with `width`, `height`,
    `duration_seconds`, all optional):
    - if `shutil.which("ffprobe")` is `None`, return empty info;
    - otherwise `subprocess.run([...,
      "-v","error","-print_format","json","-show_format","-show_streams", str(path)],
      capture_output=True, timeout=15, check=False)` (never `shell=True`);
    - take width/height from the first stream with `codec_type == "video"` and duration
      from `format.duration`;
    - return empty/partial info on any exception, non-zero exit, timeout or malformed JSON
      (log at debug level), never raise.
- [X] T006 [P] Create `backend/app/storage.py` with class `MediaStorage(root: Path)`:
  - Properties `projects_dir` (`root / "projects"`) and `tmp_dir` (`root / "tmp"`).
  - `prepare()`: `mkdir(parents=True, exist_ok=True)` both directories and delete every
    entry inside `tmp_dir`.
  - `receive_upload(source: BinaryIO, max_size: int) -> ReceivedFile`:
    - creates `tmp_dir / f"{uuid4().hex}.part"`;
    - loops `chunk = source.read(CHUNK_SIZE)`, updates `hashlib.sha256()` and a size
      counter, and writes each chunk;
    - as soon as the size exceeds `max_size`, stops reading, deletes the temp file and
      raises `FileTooLargeError`;
    - deletes the temp file on any exception;
    - returns `ReceivedFile(temp_path, checksum_hex, size)`.
  - `discard(path: Path)`: `unlink(missing_ok=True)`.
  - `final_relative_path(project_id: int, extension: str) -> str`: returns
    `f"projects/{project_id}/{uuid4().hex}{extension}"` (POSIX separators).
  - `commit(temp_path: Path, relative_path: str) -> Path`: creates the project directory
    and `os.replace` the temp file onto `resolve(relative_path)`.
  - `resolve(relative_path: str) -> Path`: joins with `root`, resolves it and raises
    `ValueError` if the result is not inside `root.resolve()`.

  Add a module docstring stating the streaming and same-filesystem rules.
- [X] T007 Extend `backend/app/main.py`:
  - `create_app(db_path: Path | None = None, media_dir: Path | None = None)` resolves
    `media_dir or get_media_dir()`;
  - in the lifespan, after migrations: `storage = MediaStorage(resolved_media_dir)`,
    `storage.prepare()`, `app.state.storage = storage`.

  Keep `app = create_app()`. Depends on T002, T006.
- [X] T008 Add to `backend/app/schemas.py` `ContentRead` (`from_attributes=True`):
  - fields: `id`, `project_id`, `media_type: MediaType`, `media_format: MediaFormat`,
    `original_filename`, `title`, `description`, `hashtags: list[str]`, `checksum`,
    `size_bytes`, `width`, `height`, `duration_seconds`, `file_url: str`,
    `file_available: bool`, `created_at`, `updated_at`;
  - a helper `content_to_read(content: Content, storage: MediaStorage) -> ContentRead` in
    `backend/app/contents.py` (created here with an empty `APIRouter(prefix="/api",
    tags=["contents"])` and included in `create_app`) that fills
    `file_url = f"/api/contents/{id}/file"` and `file_available =
    storage.resolve(storage_path).is_file()`;
  - `storage_path` must never appear in any schema.

  Depends on T003, T007.
- [X] T009 Extend `backend/tests/conftest.py`:
  - fixture `media_dir(tmp_path)` → `tmp_path / "media"`;
  - make `client` use `create_app(db_path, media_dir)`;
  - an autouse fixture that monkeypatches `app.media.probe_video` (and the name imported in
    `app.contents`, if imported by name) to return empty `VideoInfo`, so tests never depend
    on ffprobe; tests needing values override it;
  - helpers:
    - `make_image(fmt="PNG", size=(8, 6), color=...) -> bytes` (Pillow in memory; each call
      with a different color yields different bytes);
    - `make_mp4(brand=b"isom", payload=b"") -> bytes` (minimal `ftyp` box plus a free box
      with a unique payload);
    - `make_mov()` and `make_webm(payload=b"")` (EBML header with DocType `webm`);
    - `import_files(client, project_id, files: list[tuple[str, bytes]]) -> Response`,
      posting `files=[("files", (name, data)) ...]` to
      `/api/projects/{id}/contents`.

  Depends on T007.
- [X] T010 [P] Create `backend/tests/test_media.py` covering:
  - `detect_format`:
    - every supported signature;
    - MP4 brands `isom`/`mp42`, and `qt  ` → MOV;
    - rejected brands `M4A `, `heic`, `mif1`;
    - WebM vs Matroska DocType;
    - plain text, empty bytes and a text file named `.jpg` → `None`.
  - `read_image_info` returns the size of a Pillow-generated PNG/JPEG/WebP and raises
    `InvalidMediaError` for a truncated or garbage file that starts with the JPEG
    signature.
  - `probe_video` returns empty info when `shutil.which` returns `None` (monkeypatched) and
    when `subprocess.run` raises `TimeoutExpired` or returns invalid JSON.
  - `MediaStorage`:
    - `receive_upload` computes the same SHA-256 as `hashlib` over a multi-chunk source
      (use a small monkeypatched `CHUNK_SIZE` to force several chunks);
    - raises `FileTooLargeError` and leaves `tmp/` empty when exceeding `max_size`;
    - `prepare()` empties `tmp/`;
    - `resolve("../x")` raises `ValueError`.
- [X] T011 Update `backend/tests/test_migrations.py`:
  - the existing upgrade/drift tests also cover `contents`;
  - add a test that runs upgrade to `0001`, inserts a project and an account, upgrades to
    `head` and asserts both rows survive and `contents` exists.

  Depends on T004.

### Frontend

- [X] T012 [P] Extend `frontend/src/types.ts`:
  - `MediaType = "image" | "video"`;
  - `MediaFormat = "jpeg" | "png" | "webp" | "mp4" | "mov" | "webm"` (comment: keep in sync
    with `backend/app/models.py`);
  - interface `Content` (fields of [contracts/api.md](contracts/api.md#content));
  - `ImportStatus = "imported" | "duplicate" | "rejected"`;
  - `ImportItemResult { filename; status; content: Content | null; existing_content:
    Content | null; error: { code: string; message: string } | null }`;
  - `ImportResult { results: ImportItemResult[]; summary: { imported; duplicates; rejected } }`;
  - `MAX_FILES_PER_IMPORT = 100`;
  - `ACCEPTED_FILE_TYPES = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,.jpg,.jpeg,.png,.webp,.mp4,.mov,.webm"`.
- [X] T013 [P] Update `request()` in `frontend/src/api.ts` so that the `Content-Type:
  application/json` header is only added when `init.body` is a string (never for
  `FormData`). Add a case to `frontend/src/api.test.ts` asserting that a `FormData` request
  is sent without that header.
- [X] T014 [P] Extend `frontend/src/utils.ts` with:
  - `formatBytes(bytes)`, e.g. `"18.7 MB"`;
  - `formatDuration(seconds | null)`, e.g. `"0:14"`, `"1:02:05"`, `"—"` for null;
  - `parseHashtags(text)`: splits on whitespace and commas, drops empty parts, keeps order.

  Add `frontend/src/utils.test.ts` covering the three.
- [X] T015 Extend `FakeApi` in `frontend/src/test-fake-api.ts` with a `contents: Content[]`
  store, `addContent(values)` and routes:
  - `GET /projects/{id}/contents` (newest first);
  - `GET /contents/{id}`;
  - `POST /projects/{id}/contents`:
    - reads `FormData` `files`;
    - decides per file by a simple rule: name ending in `.txt` or size 0 → `rejected`
      (`unsupported_format` / `empty_file`); same name + size as an existing content of
      the project → `duplicate`; otherwise `imported` with `media_type` from the extension;
    - returns `404` for unknown projects and `409 project_inactive` for inactive ones;
  - `PATCH /contents/{id}` (applies title/description/hashtags, strips `#`, updates
    `updated_at` only on change);
  - existing `failures` queue support, plus an optional per-request delay hook so tests can
    observe the in-progress state.

  Depends on T012.

**Checkpoint**: `uv run pytest`, `uv run mypy .`, `npm test` and `npm run typecheck` pass;
the app starts and creates `backend/data/media/{projects,tmp}`.

---

## Phase 3: User Story 1 - Importar imágenes y vídeos a un proyecto (Priority: P1) 🎯 MVP

**Goal**: importar una imagen o un vídeo en un proyecto activo, con copia exacta en el
almacenamiento de AutoPublisher y acceso al archivo, desde la UI (selector o drag & drop).

**Independent Test**: importar una imagen y un vídeo en "L4i4"; la respuesta los marca como
`imported`, `GET /api/contents/{id}/file` devuelve bytes idénticos (mismo SHA-256), el
original no cambia, y tras reabrir la app con la misma base y raíz multimedia siguen ahí.

### Tests for User Story 1 ⚠️

- [X] T016 [P] [US1] Create `backend/tests/test_contents_import.py` with US1 cases (one file
  per request):
  - Valid PNG → `200`, `results[0].status == "imported"`, `content.project_id` correct,
    `media_type == "image"`, `media_format == "png"`, correct `width`/`height`,
    `size_bytes`, `checksum == sha256(data)`, `original_filename`,
    `created_at == updated_at`, `hashtags == []`, `title is None`.
  - Valid MP4 → `media_type == "video"`, `duration_seconds is None`, with `probe_video`
    returning empty info; and with `probe_video` monkeypatched to return `(1080, 1920,
    14.5)` → those values stored.
  - JPEG with `.JPG` extension; and a PNG named `photo.jpg` → stored as `png`.
  - `.txt` content → `rejected`/`unsupported_format`; text renamed to `.mp4` → `rejected`.
  - 0-byte file → `rejected`/`empty_file`.
  - Corrupted JPEG (signature + garbage) → `rejected`/`invalid_file`.
  - In every rejection: no row in the DB, `media_dir/projects` has no new file and
    `media_dir/tmp` is empty.
  - Unknown project → `404 not_found`; nothing written to `media_dir/projects` and `tmp/`
    is empty.
  - Inactive project → `409 project_inactive`.
  - Original intact: write bytes to a file in `tmp_path`, record its SHA-256 and mtime, upload
    it by opening that path, and assert path, hash and mtime are unchanged.
  - `original_filename` with path components (`"../../evil.png"`) is reduced to its basename
    and the stored file lives under `media_dir/projects/{id}/` with a generated name; a
    300-character name is truncated to 255.
  - `storage_error` without residue: monkeypatch `MediaStorage.commit` to raise `OSError` →
    `rejected`/`storage_error`, no DB row, no file in `projects/`, empty `tmp/`.
  - Simulate a DB commit failure after the move (monkeypatch `Session.commit` to raise
    `OperationalError` once) → `storage_error`, final file removed.
- [X] T017 [P] [US1] Create `backend/tests/test_contents_api.py` with US1 cases:
  - `GET /api/contents/{id}` returns the content without any `storage_path` key; unknown id
    → `404`.
  - `GET /api/contents/{id}/file` returns the exact bytes with the format MIME
    (`image/png`, `video/mp4`, `video/quicktime`, `video/webm`).
  - A `Range: bytes=0-9` request → `206` with 10 bytes.
  - Unknown content → `404 not_found`.
  - `DELETE /api/contents/{id}` → `405 method_not_allowed`.
- [X] T018 [P] [US1] Extend `backend/tests/test_persistence.py`: import an image and a video
  with one app, dispose it, create a new app on the same `db_path` and `media_dir`, and
  assert the contents (all fields), their project association and the served file bytes
  (SHA-256) are identical.
- [X] T019 [P] [US1] Create `frontend/src/components/ContentLibrary.test.tsx` with US1 cases
  using `FakeApi`. Every test in this file mounts `ProjectDetail` (with a project from
  `FakeApi`) and clicks the "Content" view button first, so the navigation from the project
  to its library is exercised. `App` is not mounted here:
  - Selecting "Content" in a project's detail shows the import zone.
  - `userEvent.upload` of one image on the "Choose files" input sends one
    `POST /projects/{id}/contents` and shows the file as imported.
  - `fireEvent.dragOver` + `fireEvent.drop` on the drop zone with `dataTransfer: { files:
    [videoFile], types: ["Files"] }` imports the video.
  - For an inactive project, the import zone is disabled with an explanation and nothing
    is sent.

### Implementation for User Story 1

- [X] T020 [US1] Add `ImportError(code, message)`, `ImportItemResult` and `ImportResult`
  schemas to `backend/app/schemas.py` exactly as in
  [contracts/api.md](contracts/api.md#importresult).
- [X] T021 [US1] Implement `POST /api/projects/{project_id}/contents` in
  `backend/app/contents.py`:
  - **Signature**: synchronous `def`, `files: list[UploadFile] = File(...)`.
  - **Request checks**: `get_project_or_404`; inactive project → `ConflictError(
    "project_inactive", "Reactivate the project before importing content.")`.
  - **Per file**: call `import_one(session, storage, project_id, upload) ->
    ImportItemResult` inside a loop, collect results and build the summary.
  - **`import_one`**:
    1. `clean_filename` (basename via `PurePosixPath`/`PureWindowsPath` name, fallback
       `"unnamed"`, truncate to 255 keeping the extension when possible);
    2. `storage.receive_upload(upload.file, MAX_FILE_SIZE)`
       (`FileTooLargeError` → `file_too_large` "The file exceeds the 2 GiB limit.");
    3. `try/finally: storage.discard(temp_path)`;
    4. size 0 → `empty_file` "The file is empty.";
    5. read only `HEADER_SIZE` bytes of the temp file → `detect_format`; `None` →
       `unsupported_format` "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV,
       WebM.";
    6. image → `read_image_info` (`InvalidMediaError` → `invalid_file` "The file is
       damaged or is not a valid image."); video → `probe_video(temp_path)`;
    7. build `Content` (`created_at == updated_at == utc_now()`, `storage_path =
       storage.final_relative_path(...)`), `session.add`, `session.flush()`;
    8. `storage.commit(temp_path, storage_path)`;
    9. `session.commit()`.
  - **Failures in steps 7–9**: `session.rollback()`, `storage.discard(final path)` if moved;
    `OSError`/`SQLAlchemyError` → `storage_error` "The file could not be saved. Please try
    again." (log with `logger.exception`, no paths in the response).
  - Never call `upload.file.read()` without a size.

  Depends on T020.
- [X] T022 [US1] Implement `GET /api/contents/{content_id}` and
  `GET /api/contents/{content_id}/file` in `backend/app/contents.py`:
  - unknown id → `NotFoundError("Content not found.")`;
  - the file route uses `storage.resolve()`; a missing file (or `ValueError`) →
    `NotFoundError("The media file is not available.")`;
  - returns `FileResponse(path, media_type=MIME_TYPES[fmt])` (supports `Range`).
- [X] T023 [P] [US1] Add `importFile(projectId: number, file: File):
  Promise<ImportResult>` (`FormData` with field `files`) and `getContent(id)` to
  `frontend/src/api.ts`, plus `contentFileUrl(content)` returning `content.file_url` as is
  (served through the `/api` proxy).
- [X] T024 [US1] Create `frontend/src/components/ContentImport.tsx` (props: `project`,
  `onImported: () => void`):
  - A drop zone (`role="region"`, `aria-label="Import files"`) handling
    `onDragOver`/`onDragEnter` (`preventDefault`, highlight), `onDragLeave` and `onDrop`
    (`Array.from(event.dataTransfer.files)`).
  - A visible "Choose files" button bound to a hidden `<input type="file" multiple
    accept={ACCEPTED_FILE_TYPES}>` with an accessible label; reset the input value after
    each selection.
  - For each received file, calls `importFile` sequentially and appends each
    `ImportItemResult` to a results list rendered below (filename + status + message).
  - When `project.is_active` is false, the zone and button are disabled and the text
    "Reactivate the project to import content." is shown.
  - Calls `onImported()` when finished.

  Depends on T023.
- [X] T025 [US1] Create `frontend/src/components/ContentLibrary.tsx` (props: `project`) that
  renders `ContentImport` (the list and grid come in US4), and add to
  `frontend/src/components/ProjectDetail.tsx` a view selector with two buttons "Accounts" |
  "Content" (`aria-pressed`). The accounts section keeps its current behaviour; "Content"
  renders `ContentLibrary`. Default view: "Accounts". Depends on T024.
- [X] T026 [US1] Add minimal styles for the drop zone (dashed border, highlighted while
  dragging, disabled look) and the result list to `frontend/src/index.css`.

**Checkpoint**: US1 tests pass; a single image or video can be imported from the UI and its
file is served back unchanged.

---

## Phase 4: User Story 2 - Importación masiva con resultado por archivo (Priority: P1)

**Goal**: importar lotes (hasta 100) en una operación, con progreso, resultados agrupados
y aislamiento de fallos por archivo.

**Independent Test**: arrastrar un lote con imágenes y vídeos válidos, un `.txt` y un archivo
vacío; todos los válidos se importan y el resultado distingue importados y rechazados con
motivo. Por API, una petición con varios archivos mezclados devuelve un resultado por
archivo en orden.

### Tests for User Story 2 ⚠️

- [X] T027 [P] [US2] Add to `backend/tests/test_contents_import.py`:
  - A single request with 3 valid files (PNG, JPEG, MP4) → 3 `imported` in order and
    `summary`.
  - A mixed request (valid PNG, `.txt`, empty file, valid WebM, corrupted JPEG) →
    `results` in the same order with the right status/code; the 2 valid are persisted
    with files; `summary == {imported: 2, duplicates: 0, rejected: 3}`; `tmp/` empty.
  - A request where `MediaStorage.commit` fails only for the 2nd file → 1st and 3rd
    imported, 2nd `storage_error`.
  - A request with no `files` → `422 validation_error` with field `files`.
  - 101 files → `422` "At most 100 files can be imported at once." and nothing persisted;
    exactly 100 tiny distinct images → `200` with 100 `imported`.
- [X] T028 [P] [US2] Add to `frontend/src/components/ContentLibrary.test.tsx`:
  - `userEvent.upload` of 4 files (2 valid, a `.txt`, an empty file) → 4 sequential
    requests (one file each), then a results list grouped/marked as Imported (2) and
    Rejected (2) with the reason messages.
  - While importing, "Importing 1 of 4…" is visible and the drop zone/button are disabled
    (use the FakeApi delay hook).
  - Dropping 101 files shows "You can import at most 100 files at once." and sends nothing.
  - A network failure on the 2nd file marks only that file as rejected ("Could not reach
    the server.") and the 3rd is still sent.
  - A `409 project_inactive` response stops the remaining files and shows the message.

### Implementation for User Story 2

- [X] T029 [US2] In `backend/app/contents.py`, validate the request before processing any
  file: an empty list → `422 validation_error` with field `files` ("Select at least one
  file."); more than `MAX_FILES_PER_IMPORT` → `422` with field `files` ("At most 100 files
  can be imported at once."). Raise it in the shared error format (e.g. a small
  `RequestValidationError` built with the right `loc`/`msg`, or a dedicated helper in
  `backend/app/errors.py` producing the same body). Ensure a missing `files` field
  produces the same field name.
- [X] T030 [US2] Extend `frontend/src/components/ContentImport.tsx`:
  - Reject selections larger than `MAX_FILES_PER_IMPORT` before sending (error message, no
    requests).
  - Track `progress = { current, total }` and show "Importing {current} of {total}…" while
    busy; disable inputs while busy.
  - Per file, catch errors with `toApiError`:
    - `code === "project_inactive"` or `status === 404` → stop the loop and show the message;
    - any other error → push a synthetic `rejected` result with the error message and
      continue.
  - Render the final results with a summary line ("2 imported · 1 duplicate · 2 rejected")
    and per-file rows with visually distinct classes (`result-imported`,
    `result-duplicate`, `result-rejected`) and an accessible text label for each status.
- [X] T031 [US2] Add the result-state styles (`result-imported`, `result-duplicate`,
  `result-rejected`) and progress text to `frontend/src/index.css`.

**Checkpoint**: lotes mixtos funcionan por API y desde la UI sin perder los válidos.

---

## Phase 5: User Story 3 - Detección de duplicados (Priority: P1)

**Goal**: no crear contenidos ni copias duplicadas dentro de un proyecto e informar del
contenido existente.

**Independent Test**: importar un archivo en "L4i4", reimportarlo (también renombrado) →
`duplicate` con referencia al existente, sin nuevas filas ni archivos; importarlo en
"Cybersecurity" → `imported`.

### Tests for User Story 3 ⚠️

- [X] T032 [P] [US3] Add to `backend/tests/test_contents_import.py`:
  - Re-importing the same bytes → `duplicate` with `existing_content.id` equal to the
    original; row count and number of files in `projects/{id}/` unchanged; `tmp/` empty.
  - Same bytes with a different filename → `duplicate`.
  - Same bytes twice in one request → first `imported`, second `duplicate` referencing the
    first.
  - Same bytes in another project → `imported` there.
  - Two different files with the same name → both `imported`.
  - Race: monkeypatch the pre-check so it finds nothing, so the unique constraint fires on
    `flush` → still reported as `duplicate` with the existing content, and no file is left
    in `projects/` or `tmp/`.
- [X] T033 [P] [US3] Add to `frontend/src/components/ContentLibrary.test.tsx`: importing a
  file the FakeApi considers duplicate shows it under the duplicate state with "Already in
  this project" and the existing content's title (or original filename).

### Implementation for User Story 3

- [X] T034 [US3] In `import_one` (`backend/app/contents.py`):
  - Before `probe_video`/`flush`, query `Content` by `(project_id, checksum)`; if found,
    return `ImportItemResult(status="duplicate", existing_content=...)`.
  - Catch `IntegrityError` on `flush`: `rollback()`, re-query the existing content by
    `(project_id, checksum)` and return `duplicate` if found, otherwise `storage_error`.
  - The temp file is discarded by the `finally` in both paths.
- [X] T035 [US3] In `frontend/src/components/ContentImport.tsx`, render duplicate rows as
  "Already in this project as “{existing title or original_filename}”" with a button that
  calls a new optional prop `onOpenContent(id)` (wired to selection in US4; no-op until
  then).

**Checkpoint**: P1 completo (importación, lotes, duplicados) — MVP funcional por API y UI.

---

## Phase 6: User Story 4 - Biblioteca de contenido del proyecto (Priority: P2)

**Goal**: ver en cada proyecto todos sus contenidos con preview, tipo, título/nombre y fecha,
estado vacío y detalle completo de solo lectura.

**Independent Test**: un proyecto con imágenes y vídeos muestra su grid (solo sus
contenidos, más recientes primero) y el detalle completo; un proyecto sin contenido muestra
el estado vacío; un proyecto inactivo sigue mostrando su biblioteca.

### Tests for User Story 4 ⚠️

- [X] T036 [P] [US4] Add to `backend/tests/test_contents_api.py`:
  - `GET /api/projects/{id}/contents`:
    - empty project → `[]`;
    - unknown project → `404`;
    - newest first (`created_at` desc, then `id` desc);
    - only that project's contents;
    - works for an inactive project.
  - `file_available` becomes `false` after deleting the stored file from disk (locate it
    via the DB row in the test), and the file route then returns
    `404 not_found` "The media file is not available.".
  - Volume (SC-007, functional only):
    - import 200 distinct tiny images into one project (two requests of 100 files);
    - assert `GET /api/projects/{id}/contents` returns `200` with exactly 200 items, all
      `file_available: true`, ordered newest first;
    - no time threshold is asserted (real performance stays in the manual quickstart).
- [X] T037 [P] [US4] Add to `frontend/src/components/ContentLibrary.test.tsx`:
  - Empty project → "No content yet. Drop images or videos here or choose files to import
    them.".
  - Project with an image and a video → two cards with `<img>`/`<video>` previews, "Image" /
    "Video" badges, title (or original filename when no title) and import date.
  - Clicking a card shows the detail with type, original filename, title, description,
    hashtags (`#tag`), size, dimensions, duration, imported and updated dates.
  - A content with `file_available: false` shows "File not available" instead of the
    preview.
  - After an import finishes, the grid reloads and shows the new item.
  - Clicking the duplicate link opens the existing content.
  - Volume (SC-007, functional only): with 200 contents in `FakeApi`, the library renders
    200 cards and selecting the last one shows its detail. No time threshold is asserted.

### Implementation for User Story 4

- [X] T038 [US4] Implement `GET /api/projects/{project_id}/contents` in
  `backend/app/contents.py` (`get_project_or_404`, order by `created_at.desc(), id.desc()`,
  map with `content_to_read`).
- [X] T039 [P] [US4] Add `listContents(projectId)` to `frontend/src/api.ts`.
- [X] T040 [P] [US4] Create `frontend/src/components/ContentDetail.tsx` (props: `content`),
  read-only:
  - Large preview: `<img>` for images; `<video controls preload="metadata">` for videos,
    with `onError` falling back to a placeholder "Preview not available in this browser".
    "File not available" when `file_available` is false.
  - A definition list with all metadata, using `formatBytes`, `formatDuration` and
    `formatDate`.
- [X] T041 [US4] Extend `frontend/src/components/ContentLibrary.tsx`:
  - Load `listContents` on mount and after `onImported`; show load errors with
    `role="alert"`.
  - Empty state.
  - A simple grid of cards (button elements): preview `<img loading="lazy">` /
    `<video preload="metadata" muted>`, type badge, title or original filename, formatted
    date.
  - Selected-content state rendering `ContentDetail`; pass `onOpenContent` to
    `ContentImport`.

  Depends on T039, T040.
- [X] T042 [US4] Add grid, card, badge and detail styles to `frontend/src/index.css`
  (responsive `grid-template-columns: repeat(auto-fill, minmax(160px, 1fr))`, fixed-ratio
  previews with `object-fit: cover`).

**Checkpoint**: biblioteca navegable con previews y detalle.

---

## Phase 7: User Story 5 - Editar título, descripción y hashtags (Priority: P2)

**Goal**: editar la metadata global de un contenido con validación, normalización e
idempotencia de `updated_at`.

**Independent Test**: editar título, descripción y hashtags; tras reiniciar se conservan,
`updated_at` cambió, `created_at` y el checksum/archivo no; repetir los mismos valores no
cambia `updated_at`.

### Tests for User Story 5 ⚠️

- [X] T043 [P] [US5] Add to `backend/tests/test_contents_api.py` (`PATCH /api/contents/{id}`):
  - Setting title/description/hashtags → `200`, values stored, `updated_at > created_at`,
    `created_at`/`checksum`/served bytes unchanged.
  - Normalization:
    - `["#L4i4", " summer ", "l4i4", "#Summer"]` → `["L4i4", "summer"]`;
    - `"   "` title → `null`;
    - `hashtags: null` → `[]`.
  - Idempotency:
    - sending the same normalized values (e.g. `"  Same  "` after `"Same"`, or the same
      hashtag list with `#`) keeps `updated_at` unchanged;
    - changing hashtag order or case is an effective change.
  - Clearing values (`title: ""`, `description: null`, `hashtags: []`) works.
  - Validation errors → `422` with field:
    - title > 200; description > 5000;
    - hashtag with internal space; hashtag `"#"` (empty after stripping);
    - hashtag > 100 chars; 31 distinct hashtags;
    - non-list `hashtags`.
  - `{}` and non-editable fields (`project_id`, `checksum`, `media_type`) → `422`.
  - Unknown id → `404`.
  - Allowed on an inactive project.
- [X] T044 [P] [US5] Extend `backend/tests/test_persistence.py`: edited metadata survives
  reopening the app.
- [X] T045 [P] [US5] Add to `frontend/src/components/ContentLibrary.test.tsx`:
  - Editing title, description and hashtags (`"#l4i4 summer, reels"`) sends `PATCH` with
    `hashtags: ["#l4i4", "summer", "reels"]` (normalization is the backend's job) and the
    detail shows the updated values after reload.
  - A `422` with `fields: [{field: "hashtags", ...}]` is shown next to the hashtags field
    and the typed text is kept.
  - There is no delete control anywhere in the library or detail.

### Implementation for User Story 5

- [X] T046 [US5] Add `ContentUpdate(UpdateModel)` to `backend/app/schemas.py`:
  - `title`: `Annotated[str, StringConstraints(max_length=200)] | None`, cleaned with
    `clean_text`.
  - `description`: same with `max_length=5000`.
  - `hashtags: list[str] | None`, validated in a `field_validator`:
    - per item: strip, remove one leading `#`, then strip; reject empty or containing
      whitespace (`"Hashtags cannot be empty or contain spaces."`); reject > 100
      (`"Each hashtag must be at most 100 characters."`);
    - dedupe by `normalize_key` keeping first occurrence and order;
    - reject > 30 after dedupe (`"At most 30 hashtags are allowed."`);
    - `None` → `[]`.

  Make sure `_validation_message` in `backend/app/errors.py` reports these messages and the
  `hashtags` field (add `list_type` → "Must be a list of text values." if needed).
- [X] T047 [US5] Implement `PATCH /api/contents/{content_id}` in `backend/app/contents.py`:
  - for each field in `body.model_fields_set`, compare with the stored value (hashtags as
    exact list) and assign only if different;
  - if anything changed → `updated_at = utc_now()` and `commit`;
  - return `content_to_read`;
  - allowed regardless of project state.

  Depends on T046.
- [X] T048 [P] [US5] Add `updateContent(id, changes: Partial<{ title: string | null;
  description: string | null; hashtags: string[] }>)` to `frontend/src/api.ts`.
- [X] T049 [US5] Add an edit mode to `frontend/src/components/ContentDetail.tsx`:
  - "Edit" button → form with title input, description textarea and hashtags input
    (initial value `content.hashtags.map(h => "#" + h).join(" ")`);
  - on save, call `updateContent` with `parseHashtags(text)` and show field errors with the
    existing `FormError` component, keeping the typed values on error;
  - on success, exit edit mode and notify the parent (`onChanged`) so `ContentLibrary`
    reloads the list and the selected content.

  Depends on T048.

**Checkpoint**: todas las historias completas e independientes.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T050 [P] Create `backend/tests/test_ffprobe_integration.py` with two tests:
  - **Real ffprobe** (`test_real_ffprobe_extracts_video_metadata`):
    - runs only when `ffprobe` is available in the environment;
    - decorated with `pytest.mark.skipif(shutil.which("ffprobe") is None or
      shutil.which("ffmpeg") is None, reason="ffprobe/ffmpeg not installed")`, so that
      without them pytest reports it as explicitly *skipped* (never failed nor errored) and
      neither the test run nor CI fails;
    - no other part of the suite or of CI may require ffmpeg/ffprobe;
    - generates a 1-second 64x48 MP4 in `tmp_path` with `ffmpeg -f lavfi -i
      testsrc=size=64x48:rate=10 -t 1 -pix_fmt yuv420p`;
    - disables the autouse probe stub for this test and imports the file via the API;
    - asserts `width == 64`, `height == 48` and `duration_seconds ≈ 1`.
  - **Missing ffprobe** (`test_video_imports_without_ffprobe`): a normal test, never
    skipped, that runs in every environment:
    - disables the autouse probe stub so the real `probe_video` runs;
    - monkeypatches `shutil.which` (as used by `app.media`) to return `None`;
    - imports a synthetic MP4 (`make_mp4()`) via the API;
    - asserts `status == "imported"`, `media_type == "video"` and `width`, `height` and
      `duration_seconds` are `None`;
    - asserts the file is stored and served unchanged.
- [X] T051 [P] Update `README.md` (in English):
  - a "Content library" section;
  - local media storage location (`backend/data/media`, ignored by Git) and
    `AUTOPUBLISHER_MEDIA_DIR`;
  - supported formats;
  - limits (2 GiB per file, 100 files per import);
  - duplicate behaviour;
  - optional `ffprobe` for video dimensions/duration;
  - the fact that originals are never modified;
  - a "Known limitations" note:
    - Starlette may buffer each upload in the system temporary directory before AutoPublisher
      processes it, so a large file can briefly use that space (or RAM if it is a `tmpfs`);
    - optionally, `TMPDIR` can point to a disk-backed directory when needed;
    - old QuickTime MOV files without an `ftyp` header may be rejected (see research.md
      decisions 3 and 7).
- [X] T052 [P] Verify `.gitignore` already ignores `backend/data/` (including `media/`): after
  importing a file locally, `git status` shows nothing new. Only add a rule if needed.
- [X] T053 Run all quality gates and fix any failure:
  - in `backend/`: `uv run pytest && uv run ruff check . && uv run ruff format --check . &&
    uv run mypy .`;
  - in `frontend/`: `npm test && npm run lint && npm run format:check && npm run typecheck &&
    npm run build`.
- [X] T054 Execute the manual validation in [quickstart.md](quickstart.md) (reference flow
  with L4i4, mixed batch, API validations, restart persistence) and fix any deviation.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup; BLOQUEA todas las historias.
  - Backend: T003 → T004 → T011; T002 ∥ T005 ∥ T006 → T007 → T008 → T009; T010 tras T005 y
    T006.
  - Frontend: T012 → T015; T013 ∥ T014.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de US1 (amplía el endpoint de importación y `ContentImport`).
- **US3 (Phase 5)**: depende de US1 (amplía `import_one` y `ContentImport`); puede ir en
  paralelo con US2 salvo en `test_contents_import.py`, `contents.py`, `ContentImport.tsx` y
  `ContentLibrary.test.tsx`, que se editan en secuencia.
- **US4 (Phase 6)**: depende de US1; T041 conecta el `onOpenContent` de US3 si ya existe.
- **US5 (Phase 7)**: depende de US4 (la edición vive en `ContentDetail`).
- **Polish (Phase 8)**: depende de todas las historias.

### User Story Dependencies

```text
Foundational ──▶ US1 ──┬──▶ US2
                       ├──▶ US3
                       └──▶ US4 ──▶ US5
```

### Within Each User Story

- Tests primero (deben fallar), luego schemas, router, cliente API, componentes y estilos.
- Las tareas que tocan el mismo archivo son secuenciales:
  - backend: `contents.py`, `schemas.py`, `test_contents_import.py`,
    `test_contents_api.py`;
  - frontend: `api.ts`, `ContentImport.tsx`, `ContentLibrary.tsx`,
    `ContentLibrary.test.tsx`, `index.css`.

### Parallel Opportunities

- Foundational: T002 ∥ T003 ∥ T005 ∥ T006 ∥ T012 ∥ T013 ∥ T014; luego T010 ∥ T011 ∥ T015.
- US1: T016 ∥ T017 ∥ T018 ∥ T019; backend (T020–T022) ∥ frontend (T023–T026).
- US2: T027 ∥ T028; T029 (backend) ∥ T030–T031 (frontend).
- US3: T032 ∥ T033; T034 ∥ T035.
- US4: T036 ∥ T037; T038 ∥ T039 ∥ T040.
- US5: T043 ∥ T044 ∥ T045; T046–T047 (backend) ∥ T048–T049 (frontend).
- Polish: T050 ∥ T051 ∥ T052.

---

## Parallel Example: User Story 1

```bash
# Tests (primero, deben fallar):
Task: "Import tests in backend/tests/test_contents_import.py"             # T016
Task: "Content/file API tests in backend/tests/test_contents_api.py"      # T017
Task: "Persistence test in backend/tests/test_persistence.py"             # T018
Task: "UI import tests in frontend/src/components/ContentLibrary.test.tsx" # T019

# Implementación backend ∥ frontend:
Task: "Import endpoint in backend/app/contents.py"                        # T020 → T021 → T022
Task: "ContentImport in frontend/src/components/ContentImport.tsx"        # T023 → T024 → T025
```

## Parallel Example: User Story 4

```bash
Task: "List/file_available tests in backend/tests/test_contents_api.py"   # T036
Task: "Library UI tests in frontend/src/components/ContentLibrary.test.tsx" # T037
Task: "ContentDetail in frontend/src/components/ContentDetail.tsx"        # T040
Task: "listContents in frontend/src/api.ts"                               # T039
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Fase 1 (Setup) y Fase 2 (Foundational).
2. Fase 3 (US1): importar un archivo con copia exacta y acceso al archivo.
3. **STOP y VALIDAR**: tests de US1 + importación manual de una imagen y un vídeo.

### Incremental Delivery

1. Setup + Foundational → base lista.
2. US1 → importación unitaria (MVP).
3. US2 → lotes con resultados por archivo.
4. US3 → duplicados (P1 completo: pasos 2, 3 y 8 del flujo de referencia).
5. US4 → biblioteca con previews (paso 4).
6. US5 → edición de metadata (paso 5); el flujo de referencia SC-001 queda completo.
7. Polish → integración con ffprobe, README, quality gates y quickstart.

### Notes

- Commits pequeños en inglés al cerrar cada tarea o grupo lógico (p. ej. por fase).
- No ampliar el alcance: sin thumbnails, conversión, borrado, búsqueda ni paginación.
