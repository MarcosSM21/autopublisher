# AutoPublisher

AutoPublisher is a local, single-user web application to organize, schedule and publish
images and videos across multiple social media accounts.

## Tech stack

- **Frontend**: React, TypeScript, Vite
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic
- **Storage**: local SQLite database and local file system for media

## Status

Projects and social media accounts can be created, listed, edited, deactivated and
reactivated. Nothing is ever deleted. Accounts only store the identity of a future
connected account: there is no login, token or integration with any platform yet.

Each project has a content library: images and videos can be imported (drag & drop or
file picker, many at once), previewed, and given a title, description and hashtags.
Importing content does not publish or schedule it.

From a content, publications can be prepared for one or more active accounts of the
same project, optionally with a date and time, and reviewed in the project's **Queue**.
Scheduling only records the intent: nothing is published yet, and nothing happens
automatically when the scheduled time arrives.

## Prerequisites

- Git
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm

## Backend

```bash
cd backend
uv sync                                   # install dependencies
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Check it is running: `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
If the port is in use, add `--port 8001` (the frontend dev proxy expects port 8000, so
update `frontend/vite.config.ts` accordingly).

The REST API lives under `/api` (projects, accounts, contents and publications).

### Local data

- Data is stored in `backend/data/autopublisher.db`. The `data/` directory and database
  files are git-ignored and must never be committed.
- Set `AUTOPUBLISHER_DB_PATH` to use another file, e.g.
  `AUTOPUBLISHER_DB_PATH=/tmp/autopublisher-test.db uv run uvicorn app.main:app`.
- The database is created and migrated automatically on startup. Migrations live in
  `backend/migrations/` and are managed with Alembic:

```bash
uv run alembic upgrade head                                  # apply migrations manually
uv run alembic revision --autogenerate -m "describe change"  # after changing app/models.py
```

Review every generated migration before committing it; a test fails if the models and
the migrations drift apart.

### Content library

- Imported files are copied into `backend/data/media/projects/<project id>/` with a
  generated name. Set `AUTOPUBLISHER_MEDIA_DIR` to use another directory. Like the
  database, this directory is git-ignored and must never be committed.
- The original files are never modified, moved or deleted; the library keeps working
  if they are moved or removed afterwards.
- Supported formats (detected from the file content, not its extension): JPEG, PNG and
  WebP images; MP4, MOV and WebM videos. Files are stored as they are: no conversion,
  compression or resizing.
- Limits: 2 GiB per file and 100 files per import.
- Each file gets a SHA-256 checksum. Importing a file that already exists in the same
  project (even under another name) is reported as a duplicate and no copy is created.
  The same file can be imported into different projects.
- Video dimensions and duration are read with `ffprobe` when it is installed (for
  example with the `ffmpeg` package). Without it, videos are still imported and those
  fields stay empty. Image dimensions are always read.
- Contents cannot be deleted yet.

Known limitations:

- Before AutoPublisher processes an upload, the web framework (Starlette) may buffer it
  in the system temporary directory, so a large file briefly uses that space (or RAM if
  that directory is a `tmpfs`). If needed, start the backend with `TMPDIR` pointing to a
  disk-backed directory, e.g. `TMPDIR=/path/on/disk uv run uvicorn app.main:app`.
- Old QuickTime `.mov` files without an `ftyp` header may be rejected as unsupported.
  Modern MOV files (iPhone, cameras, current editors) are supported.

### Publications

- A publication is the intent to publish one content on one account of the same
  project. A content can have many publications; all of them share its single stored
  file.
- Statuses: `unscheduled` (no date), `scheduled` (a date and time) and `cancelled`.
  Dates are sent with a time zone, stored in UTC to the minute and shown in local time.
- Publications start with the content's title, description and hashtags. Each field can
  be overridden per publication (an empty override is allowed); fields without an
  override always follow the content's current values.
- There can be only one active (unscheduled or scheduled) publication per content and
  account. A cancelled publication stays in the queue as history, does not block new
  ones and can be reactivated when there is no conflict.
- Inactive projects or accounts, and contents whose media file is missing, cannot get
  new publications, be scheduled or be reactivated; their publications can still be
  viewed, unscheduled, edited and cancelled.
- Publications cannot be deleted. Real publishing, platform APIs and the scheduler are
  not implemented yet.

API routes: `GET /api/projects/{id}/publications` (queue),
`POST /api/contents/{id}/publications` (one per account), `GET` and `PATCH
/api/publications/{id}`, and `POST /api/publications/{id}/cancel` and `/reactivate`.

Quality checks:

```bash
uv run pytest                             # tests
uv run ruff check .                       # lint
uv run ruff format --check .              # formatting (fix with: uv run ruff format .)
uv run mypy .                             # type checking
```

## Frontend

```bash
cd frontend
npm install                               # install dependencies
npm run dev                               # http://localhost:5173
```

If the port is in use, run `npm run dev -- --port 5174`. The dev server forwards `/api`
requests to the backend at `http://127.0.0.1:8000`, so start the backend first.

Quality checks:

```bash
npm test                                  # tests
npm run lint                              # lint
npm run format:check                      # formatting (fix with: npm run format)
npm run typecheck                         # type checking
npm run build                             # production build
```

## Continuous integration

GitHub Actions runs the same backend and frontend checks on every push and pull request
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
