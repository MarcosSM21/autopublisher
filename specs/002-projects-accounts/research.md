# Research: Gestión básica de proyectos y cuentas

**Feature**: `002-projects-accounts` | **Fecha**: 2026-10-05

El stack base (React + TypeScript + Vite, Python + FastAPI, SQLite local, API REST) viene
impuesto por la Constitution. Este documento resuelve las decisiones que la especificación
delegó al plan. Criterio general: la opción estándar y más sencilla que cumpla los requisitos,
sin abstracciones especulativas.

## 1. Acceso a datos (ORM)

- **Decision**: SQLAlchemy 2.x (API declarativa tipada con `Mapped[...]`), en modo síncrono.
- **Rationale**: es el estándar de facto en Python, se integra de forma nativa con Alembic
  (decisión 2), sus modelos tipados funcionan bien con `mypy --strict` y soporta SQLite sin
  dependencias adicionales. El modo síncrono basta para una aplicación local de un único
  usuario; FastAPI ejecuta los endpoints síncronos en un threadpool.
- **Alternatives considered**:
  - `sqlite3` de la biblioteca estándar con SQL a mano: menos dependencias, pero obliga a
    escribir mapeo, sesiones y un sistema de migraciones propio; no escala bien a las
    features futuras (contenido, publicaciones, scheduler).
  - SQLModel: combina SQLAlchemy y Pydantic, pero mezcla modelos de persistencia y de API,
    va por detrás de SQLAlchemy en tipado y añade una capa más.
  - SQLAlchemy asíncrono + `aiosqlite`: complejidad adicional sin beneficio para un único
    usuario.

## 2. Migraciones del esquema

- **Decision**: Alembic, con migraciones versionadas en `backend/migrations/versions/`. El
  backend aplica `upgrade head` automáticamente al arrancar (lifespan de FastAPI); también se
  puede ejecutar a mano con `uv run alembic upgrade head`.
- **Rationale**: cumple FR-020 (crear el esquema en el primer arranque y evolucionarlo sin
  perder datos). Es la herramienta estándar para SQLAlchemy. Aplicar migraciones al arrancar
  evita un paso manual que el usuario de una aplicación local podría olvidar. Se usa
  `render_as_batch=True` porque SQLite solo admite un subconjunto de `ALTER TABLE`.
- **Alternatives considered**:
  - `Base.metadata.create_all()`: crea tablas pero no evoluciona el esquema; incumple FR-020.
  - Runner propio con `PRAGMA user_version` y ficheros SQL: sencillo hoy, pero reimplementa
    lo que Alembic ya resuelve (autogeneración, historial, downgrade).
- **Verificación**: un test aplica todas las migraciones sobre una base vacía y compara el
  esquema resultante con los modelos (`alembic.autogenerate.compare_metadata`); si alguien
  cambia un modelo sin crear migración, el test falla. No requiere cambios en CI.

## 3. Ubicación y configuración de la base de datos

- **Decision**: ruta configurable mediante la variable de entorno `AUTOPUBLISHER_DB_PATH`;
  por defecto `backend/data/autopublisher.db` (resuelta respecto al directorio `backend/`,
  no al directorio de trabajo). El directorio se crea si no existe.
- **Rationale**: `data/` y `*.db` ya están en `.gitignore` (Constitution IV). Una sola
  variable de entorno leída con `os.environ` evita introducir `pydantic-settings` o ficheros
  `.env` para un único valor. Los tests usan una base temporal propia.
- **Alternatives considered**: `pydantic-settings` (dependencia innecesaria para un valor);
  directorio de datos del sistema operativo (p. ej. `~/.local/share`), más correcto para una
  app instalada, pero menos visible durante el desarrollo; se puede adoptar más adelante sin
  cambiar el código gracias a la variable de entorno.

## 4. Integridad en SQLite

- **Decision**: activar `PRAGMA foreign_keys=ON` en cada conexión (evento `connect` de
  SQLAlchemy) y declarar la clave foránea `accounts.project_id` con `ON DELETE RESTRICT`.
- **Rationale**: SQLite no aplica claves foráneas por defecto; sin el pragma podría crearse
  una cuenta huérfana (FR-012). `RESTRICT` es una defensa adicional contra eliminaciones
  físicas (FR-008), aunque la API no exponga ninguna.

## 5. Unicidad sin distinguir mayúsculas

- **Decision**: columnas internas normalizadas, no expuestas en la API, calculadas siempre
  en Python por una única función `normalize_key(value)`:
  1. se parte del valor ya recortado (y, en handles, sin `@` inicial; ver decisión 6);
  2. `unicodedata.normalize("NFKC", value)`;
  3. `.casefold()`;
  4. `unicodedata.normalize("NFKC", …)` de nuevo, porque `casefold()` puede producir
     secuencias no normalizadas.

  Columnas e índices:
  - `projects.name_key = normalize_key(name)`, con índice único.
  - `accounts.handle_key = normalize_key(handle)`, con índice único
    `(project_id, platform, handle_key)`.

  La API comprueba antes de escribir y traduce el conflicto a un error `409` legible; el
  índice único garantiza la regla también ante errores de programación. Los valores visibles
  (`name`, `handle`) se guardan tal como los escribió el usuario (solo recortados).
- **Rationale**: `lower()` y `COLLATE NOCASE` de SQLite solo pliegan ASCII ("Ñ" ≠ "ñ"), y
  `str.lower()` de Python no aplica el plegado completo de Unicode ("Straße" ≠ "STRASSE").
  `casefold()` sí lo hace, y la normalización NFKC hace equivalentes las formas compuestas y
  descompuestas ("é" como un carácter frente a "e" + acento combinante) y las variantes de
  compatibilidad (p. ej. letras de ancho completo). Es la aproximación habitual a la
  comparación sin distinción de mayúsculas de Unicode.
- **Alternatives considered**: índice sobre `lower(name)` (incorrecto para no ASCII);
  solo `casefold()` sin NFKC (formas compuestas y descompuestas distintas); comprobar solo
  en código sin índice (sin garantía en la base de datos).

## 6. Normalización de entradas

- **Decision**: validadores Pydantic en los esquemas de entrada:
  - `name`, `handle`, `display_name`, `description`: se eliminan espacios exteriores.
  - `handle`: además se elimina **un** `@` inicial; si queda vacío, es inválido.
  - `description` y `display_name` vacíos tras recortar se guardan como `null`.
  - Límites de longitud tras normalizar: nombre 1–100, descripción ≤ 1000, handle 1–100,
    nombre visible ≤ 100.
  - Los esquemas usan `extra="forbid"`: enviar campos no editables (`platform`,
    `project_id`, `id`, fechas) en una edición devuelve `422`.
- **Rationale**: un único punto de validación cubre API e interfaz (la interfaz no duplica
  reglas: muestra los errores que devuelve el backend, FR-025).

## 7. Diseño de la API

- **Decision**: recursos REST bajo el prefijo `/api` (detalle en
  [contracts/api.md](contracts/api.md)):
  - `GET/POST /api/projects`, `GET/PATCH /api/projects/{id}`
  - `GET/POST /api/projects/{id}/accounts`
  - `PATCH /api/accounts/{id}`
  La activación/desactivación se hace con `PATCH` del campo `is_active`, igual que el resto
  de ediciones. No existen rutas `DELETE` (FR-008, FR-017).
- **Rationale**: un único mecanismo de edición simplifica la regla de FR-018: el backend
  compara cada campo recibido con el valor actual y solo actualiza `updated_at` si alguno
  cambia. `PATCH` con el mismo `is_active` es idempotente de forma natural.
- **Alternatives considered**: endpoints de acción (`POST .../activate`,
  `POST .../deactivate`): más rutas y la misma lógica; útiles si el cambio de estado tuviera
  efectos secundarios, que hoy no tiene.
- `/health` se mantiene en la raíz, sin cambios.

## 8. Identificadores y fechas

- **Decision**:
  - IDs enteros autoincrementales generados por SQLite.
  - Fechas en UTC con zona horaria: se guardan como UTC y la API las devuelve en ISO 8601
    con desplazamiento (`2026-10-05T10:15:00Z`). Un `TypeDecorator` pequeño garantiza que
    los valores leídos de SQLite vuelven con zona UTC (SQLite no la almacena).
  - `created_at` y `updated_at` los asigna el código de la aplicación, **no** `onupdate`
    de SQLAlchemy, para poder cumplir FR-018 (solo cambia si hay modificación efectiva).
- **Rationale**: los enteros son lo más simple para una base local de un único usuario.
  `onupdate` actualizaría la fecha en cualquier `UPDATE`, incluso sin cambios reales.
- **Alternatives considered**: UUID (sin beneficio sin sincronización ni múltiples
  instancias); `server_default=func.now()` (SQLite devuelve hora sin zona).

## 9. Formato de errores

- **Decision**: todas las respuestas de error usan la misma forma:

  ```json
  {"error": {"code": "validation_error", "message": "…", "fields": [{"field": "name", "message": "…"}]}}
  ```

  Códigos: `validation_error` (422), `not_found` (404), `duplicate` (409),
  `project_inactive` (409), `method_not_allowed` (405) e `internal_error` (500, para errores
  inesperados, con mensaje neutro). Se sustituye el manejador por defecto de
  `RequestValidationError` de FastAPI para traducir sus errores a este formato con mensajes
  legibles y sin detalles internos (FR-022).
- **Rationale**: la interfaz necesita una forma única para mostrar errores por campo
  (FR-025). Las excepciones de dominio (`NotFoundError`, `ConflictError`) se traducen en un
  único manejador.

## 10. Comunicación frontend–backend

- **Decision**: el frontend llama a rutas relativas `/api/...`; en desarrollo, el servidor
  de Vite las reenvía al backend (`server.proxy` → `http://127.0.0.1:8000`).
- **Rationale**: evita configurar CORS y no fija URLs en el código. El backend no necesita
  conocer el origen del frontend.
- **Alternatives considered**: `CORSMiddleware` + URL base configurable (más configuración
  sin beneficio para una app local).

## 11. Interfaz

- **Decision**:
  - Sin librería de enrutado ni de estado: `App` mantiene en estado el proyecto
    seleccionado. Vista en dos zonas: lista de proyectos y detalle del proyecto
    seleccionado con sus cuentas.
  - Un módulo `api.ts` con funciones tipadas sobre `fetch` y un error `ApiError` que
    conserva `code`, `message` y `fields`.
  - El catálogo de plataformas (valor de API → etiqueta visible) es una constante del
    frontend; el backend es la fuente de verdad de los valores válidos.
  - Los handles se muestran siempre con `@` delante; las fechas con
    `toLocaleString()` (hora local del usuario).
  - Tras cada operación correcta se recargan los datos afectados desde la API (sin caché
    ni actualizaciones optimistas), de modo que la interfaz nunca muestra como guardado algo
    que no se ha persistido.
  - Sin librería de estilos: CSS mínimo en un único fichero.
- **Rationale**: el volumen y la complejidad no justifican React Router, TanStack Query ni
  una librería de componentes (Constitution I). La selección por estado basta para los
  siete comportamientos de FR-023.
- **Alternatives considered**: React Router (URLs por proyecto: útil más adelante, no
  requerido ahora); TanStack Query (caché y reintentos innecesarios en local).

## 12. Tests

- **Decision**:
  - **Backend**: pytest + `TestClient`. Cada test usa una base SQLite temporal en `tmp_path`
    con migraciones aplicadas (fixture). Una fábrica `create_app(db_path)` permite crear
    dos instancias consecutivas sobre el mismo fichero para probar persistencia tras
    reinicio. Cobertura según SC-007 y el test de deriva de esquema (decisión 2).
  - **Frontend**: Vitest + React Testing Library + `@testing-library/user-event` (nueva
    dependencia de desarrollo) con `fetch` simulado (`vi.stubGlobal`). Se prueban los
    flujos básicos: estado vacío, crear proyecto, seleccionar proyecto, añadir cuenta,
    desactivar/reactivar y mostrar errores del backend.
- **Rationale**: `user-event` es la forma recomendada de simular interacciones en RTL;
  simular `fetch` evita dependencias como MSW para un número pequeño de tests.
- **Alternatives considered**: MSW (más configuración); tests end-to-end con navegador
  (Playwright): demasiado coste para esta feature; el flujo completo se valida manualmente
  con [quickstart.md](quickstart.md).

## 13. Dependencias nuevas

| Dependencia | Ámbito | Motivo |
|-------------|--------|--------|
| `sqlalchemy` (2.x) | backend | ORM (decisión 1) |
| `alembic` | backend | Migraciones (decisión 2) |
| `@testing-library/user-event` | frontend (dev) | Interacciones en tests (decisión 12) |

Se añaden con `uv add` / `npm install -D` en su versión estable actual y quedan fijadas en
los lockfiles. No se añaden otras dependencias.
