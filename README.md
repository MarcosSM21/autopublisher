# AutoPublisher

AutoPublisher is a local, single-user web application to organize, schedule and publish
images and videos across multiple social media accounts.

## Tech stack

- **Frontend**: React, TypeScript, Vite
- **Backend**: Python, FastAPI

## Status

Technical foundation only: the backend exposes a health check and the frontend shows a
minimal page. No product features are available yet.

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
If the port is in use, add `--port 8001`.

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

If the port is in use, run `npm run dev -- --port 5174`.

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
