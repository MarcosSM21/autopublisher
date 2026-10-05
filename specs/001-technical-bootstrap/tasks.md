---

description: "Task list for the technical bootstrap feature"
---

# Tasks: Bootstrap técnico del proyecto

**Input**: Design documents from `specs/001-technical-bootstrap/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/health.md](contracts/health.md), [quickstart.md](quickstart.md)

**Tests**: la spec los exige explícitamente (FR-009, FR-010): un test del health check en el
backend y un test de renderizado de la pantalla mínima en el frontend. Se ubican en US2, que
es la historia que entrega la verificación de calidad.

**Organization**: tareas agrupadas por historia de usuario. Todo el código, comentarios,
README, workflow y commits en inglés.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1, US2, US3)

## Path Conventions

- Backend: `backend/app/`, `backend/tests/`
- Frontend: `frontend/src/`
- CI: `.github/workflows/`
- Los comandos de backend se ejecutan desde `backend/`; los de frontend, desde `frontend/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: proteger el repositorio antes de instalar nada e inicializar ambos proyectos.

- [X] T001 Create root `.gitignore` covering every category listed in plan.md → Design Notes → `.gitignore`: env files (`.env`, `.env.*`, `!.env.example`); local databases (`*.db`, `*.sqlite`, `*.sqlite3`, `*.db-journal`); user data/runtime directories at any depth (`data/`, `media/`, `uploads/`) — do NOT ignore image or video extensions globally; logs (`*.log`, `logs/`); caches (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`, `*.tsbuildinfo`); dependencies (`.venv/`, `node_modules/`); builds (`dist/`, `build/`, `coverage/`, `htmlcov/`); temp/editor (`*.tmp`, `*.swp`, `.DS_Store`, `.idea/`, `.vscode/`); secrets (`*.pem`, `*.key`, `secrets.*`, `credentials*.json`, `*token*.json`). Group with short English comments per category in `.gitignore`
- [X] T002 [P] Initialize the backend uv project: create `backend/.python-version` containing `3.12` and `backend/pyproject.toml` with `name = "autopublisher-backend"`, `version = "0.1.0"`, a one-line description, `requires-python = ">=3.12"` and no `[build-system]`; then run `uv add fastapi uvicorn` in `backend/` to populate dependencies and generate `backend/uv.lock`
- [X] T003 [P] Scaffold the frontend with the official Vite `react-ts` template non-interactively into `frontend/` (do not start the dev server), run `npm install`, then remove template demo content and duplicates: `frontend/.gitignore`, `frontend/README.md`, `frontend/src/assets/`, `frontend/src/App.css`, `frontend/src/index.css`, `frontend/public/vite.svg` (and the empty `frontend/public/` directory). Keep `package-lock.json`, `.oxlintrc.json` (unchanged), `tsconfig*.json`, `vite.config.ts`, and `src/vite-env.d.ts` if generated. Do not add ESLint or any ESLint dependency/config

---

## Phase 2: Foundational (Blocking Prerequisites)

No hay prerrequisitos bloqueantes adicionales: sin base de datos, autenticación, routing ni
configuración de entorno en esta feature (FR-019). Las historias pueden empezar tras la Fase 1.

---

## Phase 3: User Story 1 - Arrancar la aplicación localmente (Priority: P1) 🎯 MVP

**Goal**: backend con `GET /health` y frontend con la pantalla mínima "AutoPublisher",
ambos arrancables en local.

**Independent Test**: [quickstart.md](quickstart.md) §1 (arranque + `curl` a `/health` y a una
ruta inexistente) y §2 (arranque + pantalla visible sin backend).

### Implementation for User Story 1

- [X] T004 [P] [US1] Create `backend/app/__init__.py` (empty) and `backend/app/main.py` with `app = FastAPI(title="AutoPublisher")` and a `GET /health` handler returning `{"status": "ok"}` with return type `dict[str, str]`, exactly as specified in [contracts/health.md](contracts/health.md); no routers, settings, CORS or other endpoints
- [X] T005 [P] [US1] Replace `frontend/src/App.tsx` with a stateless `App` component rendering a `<main>` with an `<h1>AutoPublisher</h1>` and one short paragraph stating this is the initial project foundation; no router, state, CSS imports or HTTP calls
- [X] T006 [P] [US1] Clean the frontend entry point: `frontend/src/main.tsx` renders `<App />` inside `StrictMode` via `createRoot` with no CSS import; in `frontend/index.html` set `<title>AutoPublisher</title>` and remove the Vite favicon `<link>`
- [X] T007 [US1] Validate US1 manually following [quickstart.md](quickstart.md) §1 and §2 run steps (`uv run uvicorn app.main:app --reload`, `curl` `/health` → 200 `{"status":"ok"}`, unknown route → 404; `npm run dev` shows "AutoPublisher" with the backend stopped) and confirm `/health` responds in under 1 s (SC-004); stop both servers afterwards

**Checkpoint**: backend y frontend arrancan y cumplen FR-003 a FR-008 y FR-020.

---

## Phase 4: User Story 2 - Verificar la calidad del proyecto (Priority: P2)

**Goal**: tests, lint, formato, type checking y build ejecutables con comandos documentados
en ambos stacks, y el mismo conjunto ejecutado por GitHub Actions en push y pull request.

**Independent Test**: todos los comandos de [quickstart.md](quickstart.md) §1–§2 terminan con
código 0; los errores de §3 hacen fallar el comando correspondiente.

### Backend quality

- [X] T008 [P] [US2] In `backend/`, run `uv add --dev pytest httpx2 ruff mypy` (`httpx2`: Starlette 1.x deprecates `httpx` for `TestClient`) and add tool configuration to `backend/pyproject.toml`: `[tool.pytest.ini_options]` with `pythonpath = ["."]` and `testpaths = ["tests"]`; `[tool.ruff]` with `target-version = "py312"` and `[tool.ruff.lint]` `select = ["E", "F", "I", "UP", "B"]`; `[tool.mypy]` with `strict = true`, `python_version = "3.12"` and `exclude = ["^\\.venv/"]` (defensive; mypy already skips dot-directories)
- [X] T009 [US2] Create `backend/tests/test_health.py` using `fastapi.testclient.TestClient`: one test asserting `GET /health` returns 200 and JSON exactly `{"status": "ok"}`, and one test asserting an unknown route returns 404 (depends on T004, T008)
- [X] T010 [US2] In `backend/`, run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy .`; fix any issue in `backend/app/` or `backend/tests/` until all exit 0

### Frontend quality

- [X] T011 [P] [US2] In `frontend/`, run `npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom prettier` and set `frontend/package.json` scripts to: `dev: "vite"`, `build: "tsc -b && vite build"`, `preview: "vite preview"`, `test: "vitest run"`, `lint: "oxlint --deny-warnings"` (template's `oxlint` script plus `--deny-warnings` so warnings fail, FR-012), `format: "prettier --write ."`, `format:check: "prettier --check ."`, `typecheck: "tsc -b"`
- [X] T012 [US2] Configure Vitest in `frontend/vite.config.ts` (`defineConfig` from `vitest/config`, `test.environment = "jsdom"`, `test.setupFiles = ["./src/test-setup.ts"]`, no globals) and create `frontend/src/test-setup.ts` importing `@testing-library/jest-dom/vitest` (depends on T011)
- [X] T013 [P] [US2] Create `frontend/.prettierrc.json` containing `{}` and `frontend/.prettierignore` excluding `dist`, `coverage` and `package-lock.json` (depends on T011)
- [X] T014 [US2] Create `frontend/src/App.test.tsx`: render `<App />` with `@testing-library/react` and assert the heading "AutoPublisher" is in the document; import `describe`/`it`/`expect`/`afterEach` from `vitest` and call `cleanup` in `afterEach` (depends on T005, T012)
- [X] T015 [US2] In `frontend/`, run `npm run format`, then `npm test`, `npm run lint`, `npm run format:check`, `npm run typecheck` and `npm run build`; fix any issue until all exit 0 (e.g. ensure `vite.config.ts` and `src/test-setup.ts` are covered by the right `tsconfig*.json`)

### Continuous integration

- [X] T016 [US2] Create `.github/workflows/ci.yml` named `CI`, triggered on `push` and `pull_request`, with top-level `permissions: contents: read` and two parallel jobs on `ubuntu-latest`: `backend` (`defaults.run.working-directory: backend`; `actions/checkout`; `astral-sh/setup-uv`; `uv sync --locked`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy .`; `uv run pytest`) and `frontend` (`defaults.run.working-directory: frontend`; `actions/checkout`; `actions/setup-node` with `node-version: 24`, `cache: npm`, `cache-dependency-path: frontend/package-lock.json`; `npm ci`; `npm run lint`; `npm run format:check`; `npm run typecheck`; `npm test`; `npm run build`). Use the current major version of each action; no secrets
- [X] T017 [US2] Verify failure detection (FR-012) following [quickstart.md](quickstart.md) §3: introduce each listed error, confirm the matching command exits non-zero, and revert every change (`git status` clean for `backend/app`, `backend/tests`, `frontend/src` afterwards)

**Checkpoint**: FR-009 a FR-013 y FR-021 cumplidos localmente; CI pendiente de ejecución remota (T022).

---

## Phase 5: User Story 3 - Repositorio público seguro y comprensible (Priority: P3)

**Goal**: README breve en inglés y verificación de que el `.gitignore` protege todas las
categorías sensibles sin bloquear assets públicos.

**Independent Test**: [quickstart.md](quickstart.md) §4 y lectura del README.

### Implementation for User Story 3

- [X] T018 [US3] Create root `README.md` in English, readable in under 3 minutes, with sections: what AutoPublisher is (local, single-user web app to organize, schedule and publish images and videos across multiple social accounts); tech stack; current status (technical foundation only, no product features yet); prerequisites (Git, Python 3.12+, uv, Node.js 22+, npm); backend setup/run (`uv sync`, `uv run uvicorn app.main:app --reload`, `/health`, `--port` override); frontend setup/run (`npm install`, `npm run dev`, `--port` override); quality checks per part (exact commands from [quickstart.md](quickstart.md)); note that CI runs the same checks on push and pull request (depends on T010, T015, T016)
- [X] T019 [US3] Validate `.gitignore` following [quickstart.md](quickstart.md) §4 (sensitive files and media under `data/`, `media/`, `uploads/`, `backend/media/` are ignored; `.env.example` and a root image are not); remove all temporary files afterwards and adjust `.gitignore` if any check fails

**Checkpoint**: FR-015 a FR-018 cumplidos.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T020 Scope and security review: confirm no empty directories, no product code, no frontend→backend calls (FR-002, FR-019, FR-020); confirm `git status --porcelain` lists only intended files (lockfiles included; no `.venv/`, `node_modules/`, `dist/`, caches); scan new files for secrets (FR-017)
- [X] T021 Run the complete [quickstart.md](quickstart.md) validation §1–§4 and §6 from a clean state (`rm -rf backend/.venv frontend/node_modules` then reinstall) and confirm every check passes (SC-001, SC-002, SC-003)
- [X] T022 **Requires explicit user approval (outward-facing)**: push the branch and open a pull request, then confirm the `CI` workflow runs for both push and pull request and that the `backend` and `frontend` jobs pass ([quickstart.md](quickstart.md) §5, SC-008)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 primero (protege el repo antes de instalar dependencias); T002 y T003 en paralelo después.
- **Foundational (Phase 2)**: vacía.
- **US1 (Phase 3)**: depende de T002 (backend) y T003 (frontend).
- **US2 (Phase 4)**: depende de US1 (los tests verifican el endpoint y la pantalla de US1).
- **US3 (Phase 5)**: T019 solo depende de T001; T018 depende de US2 (el README documenta los comandos finales).
- **Polish (Phase 6)**: depende de todas las historias; T022 es la última tarea y requiere aprobación.

### Within Each Story

- US1: T004, T005, T006 en paralelo → T007.
- US2 backend: T008 → T009 → T010. US2 frontend: T011 → (T012, T013) → T014 → T015. Ambas ramas en paralelo. T016 tras T010 y T015. T017 al final.
- US3: T018 y T019 independientes entre sí.

---

## Parallel Example

```bash
# Phase 1, after T001:
Task: "T002 Initialize the backend uv project in backend/"
Task: "T003 Scaffold the frontend with Vite react-ts in frontend/"

# User Story 1:
Task: "T004 Health check in backend/app/main.py"
Task: "T005 Minimal screen in frontend/src/App.tsx"
Task: "T006 Clean entry point in frontend/src/main.tsx and frontend/index.html"

# User Story 2 (backend and frontend tracks in parallel):
Task: "T008 → T009 → T010 (backend)"
Task: "T011 → T012/T013 → T014 → T015 (frontend)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Fase 1 (T001–T003).
2. Fase 3 (T004–T007).
3. **STOP and VALIDATE**: backend y frontend arrancan y responden según quickstart §1–§2.

### Incremental Delivery

1. Setup + US1 → aplicación arrancable (MVP).
2. US2 → tooling de calidad, tests y CI.
3. US3 → README y validación del `.gitignore`.
4. Polish → revisión de alcance, validación completa y CI en remoto (con aprobación).

Commits sugeridos (pequeños, en inglés): uno tras Setup, uno por historia y uno final si
Polish introduce ajustes; solo cuando el usuario lo pida.

---

## Notes

- [P] = archivos distintos, sin dependencias pendientes.
- No crear carpetas, módulos ni archivos fuera de los listados en plan.md (FR-002).
- No añadir Makefile ni `.env.example` (research.md §8 y §10).
- Si una herramienta genera archivos adicionales no previstos, eliminarlos o justificarlos antes de cerrar la tarea.
