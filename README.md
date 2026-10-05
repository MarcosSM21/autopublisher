# AutoPublisher

AutoPublisher is a local, single-user web application to organize, schedule and publish
images and videos across multiple social media accounts.

## Tech stack

- **Frontend**: React, TypeScript, Vite
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic
- **Storage**: local SQLite database

## Status

Projects and social media accounts can be created, listed, edited, deactivated and
reactivated. Nothing is ever deleted. Accounts only store the identity of a future
connected account: there is no login, token or integration with any platform yet.

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

The REST API lives under `/api` (projects and accounts).

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
