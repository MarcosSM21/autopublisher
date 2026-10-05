# Quickstart: validación de proyectos y cuentas

**Feature**: `002-projects-accounts` | **Fecha**: 2026-10-05

Guía para comprobar de extremo a extremo que la feature cumple su especificación. Contratos
en [contracts/api.md](contracts/api.md); reglas de datos en [data-model.md](data-model.md).

## Prerrequisitos

Los mismos que la Feature 001 (Python 3.12+ con uv, Node.js 22+ con npm), con dependencias
instaladas (`uv sync` en `backend/`, `npm install` en `frontend/`).

## 1. Checks automáticos (SC-007)

```bash
cd backend
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

Esperado: todo pasa. Los tests del backend incluyen persistencia tras reabrir la base de
datos y el test de deriva de esquema; los del frontend, el comportamiento básico de la UI.

## 2. Arranque con base de datos limpia

Para no tocar datos reales, usa una base temporal:

```bash
cd backend
export AUTOPUBLISHER_DB_PATH="$(mktemp -d)/autopublisher.db"
uv run uvicorn app.main:app --reload       # aplica migraciones y crea la base

cd frontend
npm run dev                                 # http://localhost:5173 (proxy /api → :8000)
```

Esperado: la base se crea automáticamente y la interfaz muestra el estado vacío.
Sin `AUTOPUBLISHER_DB_PATH`, la base se crea en `backend/data/autopublisher.db`
(ignorada por Git: `git status` no la muestra).

## 3. Flujo de referencia (SC-001)

En la interfaz:

1. Crear los proyectos **L4i4** y **Cybersecurity**.
2. En L4i4, añadir Instagram `@l4i4`, TikTok `l4i4` y X `l4i4`.
3. En Cybersecurity, añadir YouTube `@cyber`, Instagram `cyber` y TikTok `cyber`.
4. Detener backend y frontend (Ctrl+C) y volver a arrancarlos con el **mismo**
   `AUTOPUBLISHER_DB_PATH`.
5. Comprobar que ambos proyectos y sus 6 cuentas siguen ahí, cada una en su proyecto y
   con los mismos datos y fechas.
6. Editar la descripción de L4i4, desactivar Cybersecurity y desactivar la cuenta X de L4i4.
7. Comprobar que siguen visibles como inactivos y que las cuentas de Cybersecurity
   conservan su estado.
8. Reactivar Cybersecurity y la cuenta X: todo vuelve a estar activo sin pérdida de datos.

## 4. Validaciones y errores (SC-004)

Con el backend en marcha y tras el flujo anterior (L4i4 tiene `id` 1):

```bash
API=http://127.0.0.1:8000/api

curl -i -X POST $API/projects -H 'Content-Type: application/json' -d '{"name":"   "}'
# 422 validation_error (field: name)

curl -i -X POST $API/projects -H 'Content-Type: application/json' -d '{"name":"l4i4"}'
# 409 duplicate (ya existe "L4i4")

curl -i -X POST $API/projects/9999/accounts -H 'Content-Type: application/json' \
  -d '{"platform":"instagram","handle":"x"}'
# 404 not_found; no se crea nada

curl -i -X POST $API/projects/1/accounts -H 'Content-Type: application/json' \
  -d '{"platform":"myspace","handle":"x"}'
# 422 validation_error (field: platform)

curl -i -X POST $API/projects/1/accounts -H 'Content-Type: application/json' \
  -d '{"platform":"instagram","handle":"@L4I4"}'
# 409 duplicate (normalizado igual que "l4i4")

curl -i -X DELETE $API/projects/1
# 405: no existe eliminación
```

En la interfaz, provocar un nombre duplicado y comprobar que el error aparece junto al
formulario sin perder el texto escrito (FR-025). Intentar añadir una cuenta a un proyecto
inactivo y comprobar el mensaje `project_inactive`.

## 5. Idempotencia de `updated_at` (FR-018)

```bash
curl -s $API/projects/1 | grep updated_at
curl -s -X PATCH $API/projects/1 -H 'Content-Type: application/json' -d '{"is_active":true}'
curl -s $API/projects/1 | grep updated_at
# Esperado: mismo valor de updated_at si el proyecto ya estaba activo
```
