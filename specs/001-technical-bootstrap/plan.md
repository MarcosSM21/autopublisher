# Implementation Plan: Bootstrap técnico del proyecto

**Branch**: `001-technical-bootstrap` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-technical-bootstrap/spec.md`

## Summary

Crear la fundación técnica mínima de AutoPublisher: un backend FastAPI con un único endpoint
`GET /health`, un frontend React + TypeScript + Vite con una única pantalla mínima, tooling de
calidad estándar en ambos stacks (tests, lint, formato, type checking, build), un workflow de
GitHub Actions que ejecuta esos mismos comandos en cada push y pull request, un `.gitignore`
raíz seguro para repositorio público y un README breve en inglés. Sin funcionalidad de
producto. Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**: FastAPI + Uvicorn (backend); React + Vite (frontend)

**Storage**: N/A (sin persistencia en esta fase)

**Testing**: pytest + httpx2/TestClient (backend); Vitest + React Testing Library + jsdom (frontend)

**Quality tooling**: Ruff (lint + formato) y mypy strict (backend); Oxlint, Prettier y `tsc -b` (frontend)

**Dependency management**: uv con `uv.lock` (backend); npm con `package-lock.json` (frontend)

**CI**: GitHub Actions, un workflow con jobs `backend` y `frontend`

**Target Platform**: desarrollo local en Linux/macOS; CI en `ubuntu-latest`

**Project Type**: aplicación web local (frontend + backend separados)

**Performance Goals**: health check < 1 s en local (SC-004); sin otros objetivos en esta fase

**Constraints**: sin funcionalidad de producto, sin comunicación frontend–backend, sin
secretos, sin carpetas ni abstracciones sin responsabilidad real

**Scale/Scope**: 1 endpoint, 1 pantalla, 2 tests mínimos, 1 workflow de CI

No quedan `NEEDS CLARIFICATION`: todas las decisiones de tooling se resuelven en
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Una herramienta por necesidad, sin task runner adicional, sin carpetas vacías; alcance limitado a la spec (FR-002, FR-019, FR-020). | ✅ |
| II. Spec-Driven Development | Plan derivado de la spec aprobada; CI añadido a la spec (FR-021, SC-008) antes de planificarlo. | ✅ |
| III. Arquitectura modular | `frontend/` y `backend/` separados con dependencias propias. Persistencia, scheduler, cuentas y publishers se aplazan sin crear estructura especulativa. | ✅ |
| IV. Seguridad (repositorio público) | `.gitignore` raíz cubre todas las categorías sensibles; sin `.env.example` (no hay variables); health check sin detalles internos; CI con `permissions: contents: read` y sin secretos. | ✅ |
| V. Calidad y verificabilidad | Tests mínimos en ambos stacks; tests, lint, formato, type checking y build con comandos simples documentados y ejecutados en CI. | ✅ |
| VI. Git y trazabilidad | Rama de feature; commits pequeños en inglés; README actualizado. | ✅ |
| Arquitectura tecnológica base | React + TypeScript + Vite; Python + FastAPI. SQLite, scheduler, adapters y almacenamiento de secretos no aplican aún. | ✅ |
| Idioma y convenciones | Código, README, workflow y commits en inglés; artefactos de Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS (el diseño de Fase 1 no
añade dependencias, servicios ni estructura más allá de lo listado).

## Project Structure

### Documentation (this feature)

```text
specs/001-technical-bootstrap/
├── plan.md              # Este archivo
├── research.md          # Fase 0: decisiones de tooling
├── data-model.md        # Fase 1: sin entidades (solo respuesta del health check)
├── quickstart.md        # Fase 1: guía de validación de extremo a extremo
├── contracts/
│   └── health.md        # Fase 1: contrato de GET /health
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
.github/
└── workflows/
    └── ci.yml               # Jobs backend y frontend; push + pull_request

backend/
├── pyproject.toml           # Dependencias y config de pytest, ruff y mypy
├── uv.lock                  # Lockfile versionado
├── .python-version          # 3.12 (lo usan uv y setup-uv)
├── app/
│   ├── __init__.py
│   └── main.py              # Instancia FastAPI + GET /health
└── tests/
    └── test_health.py       # Verifica 200 y {"status": "ok"}

frontend/
├── package.json             # Scripts: dev, build, preview, test, lint, format, format:check, typecheck
├── package-lock.json        # Lockfile versionado
├── index.html
├── vite.config.ts           # Incluye la configuración de Vitest (jsdom)
├── tsconfig.json            # + tsconfig.app.json / tsconfig.node.json de la plantilla
├── .oxlintrc.json           # Config de Oxlint de la plantilla, sin cambios
├── .prettierrc.json         # Config mínima (puede ser {})
├── .prettierignore          # Excluye dist/ y lockfile
└── src/
    ├── main.tsx             # Punto de entrada
    ├── App.tsx              # Pantalla mínima "AutoPublisher"
    ├── App.test.tsx         # Verifica que la pantalla se renderiza
    ├── test-setup.ts        # Matchers de @testing-library/jest-dom
    └── vite-env.d.ts        # Solo si la plantilla lo genera

.gitignore                   # Único, en la raíz; cubre ambos stacks y FR-015
README.md                    # Inglés: qué es, stack, estado, cómo ejecutar y verificar
```

**Structure Decision**: aplicación web con dos directorios de primer nivel independientes,
`backend/` y `frontend/` (FR-001), más `.github/workflows/` para CI. Dentro de cada uno solo se
crean los archivos con responsabilidad real hoy (FR-002): el backend es un paquete plano
`app/` sin subcarpetas `api/`, `models/` ni `services/`; el frontend elimina el contenido de
demostración de la plantilla de Vite (contador, logos, `assets/`, CSS de ejemplo y su
`.gitignore` propio). Las subcarpetas modulares exigidas por el principio III se crearán en
las features que introduzcan persistencia, scheduler, cuentas o publishers. No se mantiene
favicon ni `public/` en esta feature.

## Design Notes

- **Health check**: definido en [contracts/health.md](contracts/health.md). Se implementa
  directamente en `app/main.py`; un router dedicado sería una abstracción prematura con un
  solo endpoint.
- **Pantalla mínima**: un componente `App` que muestra el nombre "AutoPublisher" y una línea
  indicando que es la base inicial del proyecto. Sin router, sin estado, sin llamadas HTTP.
- **Comandos únicos de verdad**: los comandos de [quickstart.md](quickstart.md) son los mismos
  que documenta el README y ejecuta CI; no se duplican en ningún script intermedio.
- **CI**: `uv sync --locked` y `npm ci` garantizan que CI usa exactamente los lockfiles
  versionados. Versiones fijadas mediante `backend/.python-version` y `node-version: 24` en
  `actions/setup-node`.
- **`.gitignore`**: patrones por categoría:
  - entorno: `.env`, `.env.*`, con excepción `!.env.example`;
  - bases de datos: `*.db`, `*.sqlite`, `*.sqlite3`, `*.db-journal`;
  - multimedia y datos del usuario: por directorios de datos/runtime, no por extensión
    (`data/`, `media/`, `uploads/`, en cualquier nivel del repositorio);
  - logs: `*.log`, `logs/`;
  - caches: `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`,
    `*.tsbuildinfo`;
  - dependencias: `.venv/`, `node_modules/`;
  - builds: `dist/`, `build/`, `coverage/`, `htmlcov/`;
  - temporales y editor: `*.tmp`, `*.swp`, `.DS_Store`, `.idea/`, `.vscode/` (salvo
    configuración compartida explícita);
  - secretos: `*.pem`, `*.key`, `secrets.*`, `credentials*.json`, `*token*.json`.
- **Multimedia por directorio, no por extensión**: no se ignoran globalmente extensiones de
  imagen o vídeo, para poder versionar assets públicos del frontend, logos, documentación o
  imágenes del README. La multimedia privada queda protegida porque deberá residir siempre
  en los directorios de datos/runtime ignorados; la feature que introduzca el almacenamiento
  de multimedia DEBE ubicarlo en uno de ellos (o añadir al `.gitignore` su directorio
  concreto).

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
