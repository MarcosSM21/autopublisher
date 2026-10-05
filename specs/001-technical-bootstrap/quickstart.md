# Quickstart: validación del bootstrap técnico

**Feature**: `001-technical-bootstrap` | **Fecha**: 2026-10-05

Guía para comprobar de extremo a extremo que la feature cumple su especificación. Los
comandos son los mismos que documentará el README y que ejecutará CI.

## Prerrequisitos

- Git
- Python 3.12+ y [uv](https://docs.astral.sh/uv/)
- Node.js 22+ y npm

## 1. Backend (US1, US2)

```bash
cd backend
uv sync                                   # instala dependencias
uv run uvicorn app.main:app --reload      # arranca en http://127.0.0.1:8000
```

En otra terminal:

```bash
curl -i http://127.0.0.1:8000/health      # esperado: 200 y {"status":"ok"}
curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1:8000/health
                                          # esperado: < 1 (segundos, SC-004)
curl -i http://127.0.0.1:8000/unknown     # esperado: 404, sin detalles internos
```

Comprobaciones (todas deben terminar con código 0):

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Puerto ocupado: `uv run uvicorn app.main:app --reload --port 8001`.

## 2. Frontend (US1, US2)

```bash
cd frontend
npm install                               # o `npm ci` para instalación reproducible
npm run dev                               # arranca en http://localhost:5173
```

Abrir la URL: debe mostrarse una pantalla mínima con el nombre "AutoPublisher", aunque el
backend no esté en ejecución.

Comprobaciones (todas deben terminar con código 0):

```bash
npm test
npm run lint
npm run format:check
npm run typecheck
npm run build
```

Puerto ocupado: `npm run dev -- --port 5174`.

## 3. Detección de fallos (US2, FR-012)

Introducir temporalmente cada error y comprobar que el comando correspondiente falla con
código distinto de cero; después revertir el cambio:

| Error introducido                          | Comando que debe fallar                     |
|--------------------------------------------|---------------------------------------------|
| Cambiar `"ok"` en el test del health check | `uv run pytest`                             |
| Romper la indentación/espaciado en Python  | `uv run ruff format --check .`              |
| Asignar un `str` a una variable `int`      | `uv run mypy .`                             |
| Cambiar el texto esperado en el test de UI | `npm test`                                  |
| Romper el formato de un archivo `.tsx`     | `npm run format:check`                      |
| Asignar un `string` a una variable `number`| `npm run typecheck`                         |
| Añadir un `import os` sin usar en `app/main.py` | `uv run ruff check .` (regla `F401`)   |
| Llamar a `useState(0)` dentro de un `if` en `App.tsx` | `npm run lint` (regla `react/rules-of-hooks`, configurada como `error` en `.oxlintrc.json`) |

## 4. Seguridad del repositorio (US3, FR-015)

Desde la raíz del repositorio:

```bash
mkdir -p data media uploads backend/media
touch .env backend/.env local.db data.sqlite3 app.log secrets.json credentials.json \
  data/clip.mp4 media/photo.jpg uploads/video.mov backend/media/image.png
git status --porcelain                    # esperado: ninguno de esos archivos aparece
touch .env.example docs-logo.png && git status --porcelain
                                          # esperado: .env.example y docs-logo.png sí aparecen
rm -r .env backend/.env local.db data.sqlite3 app.log secrets.json credentials.json \
  data media uploads backend/media .env.example docs-logo.png
```

## 5. Integración continua (FR-021, SC-008)

1. Hacer push de la rama a GitHub y abrir un pull request.
2. En la pestaña *Actions*, el workflow `CI` debe ejecutarse para el push y para el PR.
3. Los jobs `backend` y `frontend` deben terminar en verde.
4. Opcional: un commit con un test roto debe poner el workflow en rojo.

## 6. Revisión de alcance (FR-002, FR-019, FR-020)

- `backend/` solo contiene la app con el endpoint de health check y sus tests.
- `frontend/src/` solo contiene la pantalla mínima, su test y el punto de entrada.
- No hay carpetas vacías ni código de producto, base de datos, scheduler, OAuth o llamadas
  del frontend al backend.
