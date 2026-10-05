# Research: Bootstrap técnico del proyecto

**Feature**: `001-technical-bootstrap` | **Fecha**: 2026-10-05

El stack base (React + TypeScript + Vite, Python + FastAPI) viene impuesto por la Constitution.
Este documento resuelve las decisiones de tooling que la especificación delegó al plan.
Criterio general: la opción estándar y más sencilla de cada ecosistema, con el menor número
de herramientas y de archivos de configuración.

## 1. Versiones de los entornos de ejecución

- **Decision**: Python 3.12+ y Node.js 22+ (CI usa Node 24 LTS y Python 3.12).
- **Rationale**: versiones soportadas y estables; coinciden con el entorno local disponible
  (Python 3.12.12, Node 24.16.0). Node 22 sigue siendo LTS y es compatible con Vite actual.
- **Alternatives considered**: Python 3.13 como mínimo (innecesariamente restrictivo);
  Node 20 (fuera de soporte en esta fecha).

## 2. Gestión de dependencias del backend

- **Decision**: `uv` con `pyproject.toml` y `uv.lock` versionado; proyecto no empaquetado
  (sin build system).
- **Rationale**: un solo comando (`uv sync`) crea el entorno virtual e instala dependencias
  de forma reproducible; `uv run <cmd>` ejecuta herramientas sin activar el entorno. Tiene
  acción oficial para GitHub Actions (`astral-sh/setup-uv`).
- **Alternatives considered**: `pip` + `venv` + `requirements.txt` (más pasos manuales y sin
  lockfile real); Poetry (más pesado, sin ventaja para este caso).

## 3. Servidor del backend

- **Decision**: `fastapi` + `uvicorn` como dependencias directas; arranque con
  `uv run uvicorn app.main:app --reload`.
- **Rationale**: mínimo de dependencias. `fastapi[standard]` y el CLI `fastapi dev` arrastran
  paquetes no necesarios en esta fase.
- **Alternatives considered**: `fastapi[standard]` (más dependencias); Hypercorn (menos común).

## 4. Calidad del backend

- **Decision**:
  - Tests: `pytest` + `httpx2` (requerido por `fastapi.testclient.TestClient`; Starlette 1.x
    marca `httpx` como obsoleto para este uso).
  - Lint y formato: `ruff` (`ruff check` y `ruff format --check`).
  - Type checking: `mypy` en modo `strict`.
  - Toda la configuración en `pyproject.toml`.
- **Rationale**: Ruff unifica lint y formato en una sola herramienta rápida; mypy es el type
  checker de referencia y `strict` es viable con tan poco código, fijando un listón alto
  desde el principio.
- **Alternatives considered**: Black + Flake8 + isort (tres herramientas en vez de una);
  Pyright (requiere Node o un wrapper; mypy es más habitual en proyectos Python).

## 5. Endpoint de health check

- **Decision**: `GET /health` → `200 OK` con cuerpo `{"status": "ok"}`.
- **Rationale**: convención extendida, cuerpo mínimo y estable que no expone detalles
  internos (FR-004, FR-005). Sin prefijo `/api`: el health check describe el servicio, no un
  recurso de la API de producto. El prefijo de la API REST se decidirá en la primera feature
  que la introduzca.
- **Alternatives considered**: incluir versión, uptime o estado de dependencias (no hay
  dependencias que comprobar y podría exponer información innecesaria).

## 6. Frontend: scaffolding y gestión de dependencias

- **Decision**: plantilla oficial `create-vite` `react-ts`, `npm` con `package-lock.json`
  versionado, eliminando el contenido de demostración (contador, logos, assets).
- **Rationale**: es la base oficial de Vite y ya incluye TypeScript y Oxlint configurados
  (verificado con `create-vite` 9.2.1: `.oxlintrc.json` y script `lint: "oxlint"`, sin
  ESLint); npm viene con Node, sin herramienta extra.
- **Alternatives considered**: pnpm o yarn (instalación adicional sin beneficio relevante);
  escribir la configuración desde cero (más trabajo y más riesgo).

## 7. Calidad del frontend

- **Decision**:
  - Tests: Vitest + React Testing Library + `jsdom`, configurado dentro de `vite.config.ts`.
  - Lint: Oxlint con el `.oxlintrc.json` que genera la plantilla, sin cambios. El script
    `lint` de la plantilla (`oxlint`) se conserva añadiendo `--deny-warnings`:
    `"lint": "oxlint --deny-warnings"`.
  - Formato: Prettier (`prettier --check .`).
  - Type checking: `tsc -b` (configuración de proyectos de la plantilla, ya sin emisión).
  - Scripts npm: `dev`, `build`, `preview`, `test`, `lint`, `format`, `format:check`,
    `typecheck`.
- **Rationale**: Vitest reutiliza la configuración de Vite (sin config de Jest/Babel);
  Oxlint es el linter que trae la plantilla oficial, por lo que no requiere dependencias ni
  configuración adicionales (principio I); Prettier es el estándar de facto para formato y
  Oxlint no aplica reglas de estilo, así que no hay conflicto entre ambos. `--deny-warnings`
  es necesario para FR-012: sin él, Oxlint termina con código 0 cuando solo hay warnings
  (verificado: con la configuración de la plantilla, `no-debugger` es warning y sale con 0;
  con `--deny-warnings` sale con 1).
- **Alternatives considered**: ESLint (la plantilla ya no lo incluye; habría que instalar
  `eslint`, `@eslint/js`, `typescript-eslint` y `eslint-plugin-react-hooks` y escribir su
  configuración); script `lint` sin modificar (los warnings no harían fallar el comando ni
  CI); Jest (requiere transformaciones adicionales); Biome (unifica lint y formato, pero se
  aparta de la configuración de la plantilla oficial).

## 8. Orquestación de comandos

- **Decision**: sin Makefile ni task runner raíz. Cada parte se gestiona con su herramienta
  nativa (`uv run …` en `backend/`, `npm run …` en `frontend/`), documentado en el README.
- **Rationale**: principio I (simplicidad). Los comandos nativos ya son cortos y CI los
  reutiliza tal cual; una capa adicional duplicaría la definición de los comandos.
- **Alternatives considered**: Makefile raíz con `make check` (cómodo, pero añade una capa y
  dependencia de `make`); scripts npm en la raíz (mezcla ecosistemas).

## 9. Integración continua

- **Decision**: un único workflow `.github/workflows/ci.yml`, disparado en `push` y
  `pull_request`, con dos jobs independientes en paralelo:
  - `backend`: `astral-sh/setup-uv` → `uv sync --locked` → `ruff check` →
    `ruff format --check` → `mypy` → `pytest`.
  - `frontend`: `actions/setup-node` (caché npm) → `npm ci` → `lint` → `format:check` →
    `typecheck` → `test` → `build`.
  - Cada job usa `working-directory` en su carpeta y `permissions: contents: read`.
- **Rationale**: reutiliza exactamente los comandos documentados (FR-021); dos jobs dan un
  diagnóstico claro y no hay estado compartido entre stacks. Permisos mínimos por seguridad.
- **Alternatives considered**: un job único secuencial (más lento y menos legible);
  filtros por rutas (`paths`) para ejecutar solo el job afectado (optimización prematura);
  matriz de versiones (innecesaria para una app local de un usuario).

## 10. `.gitignore` y variables de entorno

- **Decision**: un único `.gitignore` en la raíz que cubre ambos stacks y las categorías de
  FR-015 (incluye `!.env.example`). No se crea `.env.example`: no hay ninguna variable
  necesaria en esta fase (FR-016).
  La multimedia privada se protege ignorando directorios de datos/runtime del usuario
  (`data/`, `media/`, `uploads/`), no extensiones de archivo.
- **Rationale**: un solo archivo es más fácil de auditar en un repositorio público; la
  plantilla de Vite genera su propio `.gitignore`, que se elimina para no duplicar reglas.
  Ignorar por directorio permite versionar assets públicos (logos, imágenes del README o de
  la documentación, assets del frontend) sin excepciones.
- **Alternatives considered**: `.gitignore` por subproyecto (reglas dispersas); ignorar
  globalmente extensiones de imagen y vídeo (bloquea assets públicos legítimos y obliga a
  mantener excepciones).

## 11. Estructura del backend

- **Decision**: paquete plano `backend/app/` (`__init__.py`, `main.py`) y `backend/tests/`,
  con `pythonpath = ["."]` en la configuración de pytest.
- **Rationale**: lo mínimo para un único endpoint; sin `src/` layout ni build system porque
  el backend no se distribuye como librería. Las subcarpetas (`api/`, `models/`…) se crearán
  cuando una feature les dé responsabilidad real (FR-002).
- **Alternatives considered**: `src/` layout con paquete instalable (más configuración sin
  beneficio actual).
