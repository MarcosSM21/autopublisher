# Research: Deployment & Mobile Readiness (Feature 020)

**Fecha**: 2026-10-20 · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

Cada sección: hallazgo en el código actual → decisión → justificación → alternativas descartadas.

---

## §0. Hallazgos verificados en el repositorio

| Área | Hallazgo (archivo) |
|---|---|
| Entrypoint | `backend/app/main.py`: `create_app(...)` (composition root, inyección para tests) y `app = create_app()` a nivel de módulo, usado por `uv run uvicorn app.main:app --reload`. |
| Lifespan | `lifespan()`: `run_migrations(db)` → engine → `MediaStorage.prepare()` (crea `projects/` y vacía `media/tmp`) → `sweep_orphan_clean_copies` → credential stores (`KeyringCredentialStore` por plataforma) → clientes HTTP → publishers → `recover_interrupted_attempts` → limpieza de huérfanos TikTok → hilo `media-sweep` → `Scheduler.start()`. En el `finally`: `scheduler.stop()` + `runner.stop()`; `engine.dispose()`. |
| Migraciones | `app/db.py::run_migrations` (Alembic `upgrade head` al arrancar, crea el directorio del DB). Un fallo lanza y aborta el lifespan → el servidor no sirve. |
| Scheduler | `app/scheduler.py`: hilo daemon, ciclo cada 30 s; candidatos `SCHEDULED ∧ auto_publish_enabled ∧ scheduled_at ∈ [now-10min, now]`; `start_publication(trigger=SCHEDULED)`; errores no reclamables → `record_auto_publish_error` (el Post sigue `scheduled`, reintento cada 120 s dentro de la ventana). `last_check_at` en memoria. |
| Missed | `app/automation.py::is_overdue`: `scheduled ∧ armed ∧ now > scheduled_at + 10 min` → `auto_publish_state = "overdue"` (UI "Missed"). Derivado, nunca almacenado. Tests: `test_scheduler_lifecycle.py::test_restart_after_the_window_leaves_it_overdue`, `test_scheduler_concurrency.py::test_waiting_beyond_the_window_leaves_it_overdue`. |
| Recuperación | `publishing.recover_interrupted_attempts` antes de arrancar el scheduler: intentos `running` del proceso anterior se cierran, nunca se reanudan. |
| Rutas | `app/config.py`: `get_db_path`, `get_media_dir`, `get_*_app_file`, `get_media_delivery_file`; cada una con su `AUTOPUBLISHER_*` y default `BACKEND_DIR/data/...`. No existe `AUTOPUBLISHER_DATA_DIR`. |
| Media | `app/storage.py`: `<media>/projects/<id>/<uuid><ext>`, temporales en `<media>/tmp/*.part`, `os.replace` atómico; rutas relativas en BD (`Content.storage_path`, `Content.sanitized_storage_path`), `resolve()` impide salir de la raíz. Ficheros inmutables una vez referenciados; las copias limpias huérfanas solo se borran **al arrancar** (`sweep_orphan_clean_copies`). `Content.checksum` y `Content.sanitized_checksum` guardan SHA-256. |
| Uploads | `contents.py`: `list[UploadFile] = File()`. Starlette 1.7 `MultiPartParser`: `spool_max_size = 1 MiB` → `SpooledTemporaryFile` en `tempfile.gettempdir()` (respeta `TMPDIR`); después `MediaStorage.receive_upload` copia en bloques de 1 MiB a `<media>/tmp`. En este host `/tmp` no es un montaje separado (disco), pero en otros (Fedora, Arch, algunos Pi) es `tmpfs`. |
| Keyring | `app/credential_store.py`: `keyring` con allow-list de backends nativos, sin fallback; `CredentialStoreUnavailable`. Host actual: `SecretService.Keyring`, GNOME/X11. |
| OAuth YouTube | `POST /api/accounts/{id}/youtube-connection/authorize` → URL de Google con redirect `http://127.0.0.1:8000/api/youtube/oauth/callback` (validado loopback en `config.get_oauth_redirect_uri`). `GET /api/youtube/oauth/callback` consume `state` + PKCE. El frontend sondea `GET /api/youtube/oauth/attempts/{id}`. El callback **no** comprueba que el cliente sea loopback. |
| OAuth TikTok | `authorize` exige que el puerto real del socket (`scope["server"][1]`) sea el del redirect; `handle_callback` exige cliente **y** socket loopback (`_is_loopback`); `GET /api/tiktok/oauth/result` es una página fija sin datos (303 desde el callback). |
| Instagram/Threads | Paso "pegar la URL" (redirect `https://localhost/...` no servido): todo vía `POST` de la app → funciona desde cualquier dispositivo autenticado. |
| Telegram | Código / 2FA vía `POST` de la app → cualquier dispositivo. |
| Redacción | `install_log_redaction()` de YouTube/Instagram/Threads/TikTok y `install_media_delivery_log_redaction()` como filtros en loggers concretos (p. ej. `uvicorn.access`). No hay configuración global de logging. |
| `/health` | `{"status":"ok"}` fijo. `GET /api/automation` → `paused`, `running`, `last_check_at`, `check_interval_seconds`, `window_minutes`. |
| Frontend | `fetch('/api'+path)` relativo (`src/api.ts`); `createBrowserRouter`; `vite.config.ts` proxy `/api → 127.0.0.1:8000`; `frontend/dist/{index.html,assets/*}` con hashes. Sin APIs de contexto seguro (`crypto.randomUUID`, `clipboard`, SW, `Notification`): solo `localStorage` y `window.open`. Media vía `<img>/<video src="/api/contents/{id}/file">` (`FileResponse`, soporta Range). |
| Tests | `tests/conftest.py`: `create_app(db_path, media_dir, ...)` + `TestClient` (Host `testserver`, cliente `testclient`), keyring real sustituido por backend `fail`. ~100 ficheros de test. |
| CI | `.github/workflows/ci.yml`: ruff, format, mypy, pytest (con ffmpeg); frontend lint, format, typecheck, test, build. |
| Host real | systemd 255 (user manager activo), `graphical-session.target` activo, `DBUS_SESSION_BUS_ADDRESS` en el entorno del user manager, journal persistente, uv 0.12. |

---

## §1. Scheduler con keyring no disponible → Missed (verificación de la spec)

**Hallazgo**: los cinco publishers leen el keyring en `prepare()` (YouTube `list_channels`, Instagram/Threads `verify_identity`/`get_valid_credentials`, TikTok, Telegram), y `prepare()` se ejecuta en `start_publication` **antes** de `create_running_attempt` (claim atómico). `CredentialStoreUnavailable` se traduce a `AppError(503, "credential_store_unavailable")`, que no está en `NOT_CLAIMED_CODES` → `Scheduler._record_failure` → `record_auto_publish_error`: el Post sigue `scheduled`, con el motivo visible, reintento cada 120 s mientras dure la ventana; al terminar la ventana `is_overdue` → **Missed**. Nunca se publica tarde porque `_candidates` filtra por la ventana.

Si el keyring cae **después** del claim (p. ej. Instagram `_token()` durante la ejecución), el intento termina `failed` determinado: comportamiento existente correcto (una vez iniciada, la ejecución es final; 007).

**Decisión**: el código cumple US3 escenarios 2–3 por un **camino común** (`start_publication` → `prepare()` antes del claim → `Scheduler._start` captura `AppError` o cualquier excepción → `record_auto_publish_error` → `is_overdue`). No se cambia el scheduler. Regresión con dos casos (no una matriz de plataformas): una integración real (YouTube, `AppError` `credential_store_unavailable`) y un `FakePublisher.prepare()` que lanza `CredentialStoreUnavailable` sin envolver (camino `internal_error`). Si fallara, el cambio mínimo se hace en el punto común, no en cada `prepare()`.

**Alternativas descartadas**: pausar el scheduler cuando el keyring no está disponible (cambia reglas de 007, oculta el motivo por Post).

---

## §2. Single origin: quién sirve UI + API

**Decisión**: **FastAPI sirve el frontend compilado** en modo instalación (opción A). Un único proceso, un puerto.

- `StaticFiles` montado en `/assets` (ficheros con hash, `Cache-Control: public, max-age=31536000, immutable`).
- Ruta catch-all `GET|HEAD /{path:path}` registrada **la última**: si `path` es `api`, empieza por `api/` o es `health` → 404 JSON del formato existente (`not_found`); en otro caso devuelve `dist/index.html` con `Cache-Control: no-cache`. Ficheros sueltos de `dist/` (p. ej. `favicon.svg`, si existen) se sirven si existen como fichero regular dentro de `dist` (resueltos y comprobados con `is_relative_to`).
- Las rutas `/api/*` existentes no cambian; métodos distintos de GET/HEAD en rutas no-API → 405/404 JSON.
- Desarrollo: no se sirve `dist` (Vite sigue igual).

**Justificación**: cumple todos los contratos (deep links, API nunca cae al SPA, callbacks OAuth en el mismo puerto 8000 ya registrado, `scope["server"]` real para TikTok) sin piezas operativas nuevas.

**Alternativas descartadas**: nginx/Caddy delante (segundo servicio, rompe la comprobación de socket/puerto de TikTok y la detección de cliente loopback salvo `proxy_headers`, que abriría spoofing de IP); `vite preview` (Node en runtime, contradice FR-005).

---

## §3. Build y runtime separados (FR-005)

**Decisión**:

- La instalación = checkout del repo (git) + `uv sync --frozen --no-dev` en `backend/` + `frontend/dist/` presente.
- `dist` por defecto en `<repo>/frontend/dist` (resuelto desde `BACKEND_DIR.parent`); sobrescribible con `frontend_dist` en la configuración del host.
- Si falta `index.html` en modo instalación → `serve` termina con exit 78 y mensaje: "Frontend build not found at …; run `npm ci && npm run build` in frontend/ or copy a build there".
- Host sin Node: `npm ci && npm run build` en otra máquina y copiar `frontend/dist/` (p. ej. `rsync -a frontend/dist/ host:…/frontend/dist/`). Sin artefacto de release ni pipeline.
- `dist/` sigue git-ignorado.

**Alternativas descartadas**: commitear `dist` (ruido en historial público, builds desalineados); tarball de release en CI (infraestructura de releases fuera de alcance).

---

## §4. Modo desarrollo vs instalación (FR-004 / FR-030h)

**Regla**: *el modo lo decide el entrypoint, nunca un ajuste.*

| | Desarrollo | Instalación |
|---|---|---|
| Arranque | `uv run uvicorn app.main:app --reload` (sin cambios) | `uv run python -m app.cli serve` (único camino) |
| Construcción | `app = create_app(deployment=DeploymentSettings.development())` a nivel de módulo | `serve` construye `create_app(deployment=DeploymentSettings.installation(host_config))` |
| Contraseña | No existe (C4: compensado por "solo loopback") | Siempre obligatoria; no hay ajuste para desactivarla |
| Clientes | **Solo loopback** (`request.client.host` ∈ {127.0.0.1, ::1}); otro → 403 `loopback_only` | Loopback siempre; LAN si `lan_enabled` |
| Host / Origin | Validados contra nombres loopback | Validados (§14, §13) |
| Frontend | Vite | `dist` servido por FastAPI |
| Datos | `backend/data` (o `AUTOPUBLISHER_DATA_DIR`) | `data_dir` de la configuración del host |

`create_app()` sin `deployment` (usado por los tests) conserva el comportamiento actual exacto (sin guards), para no tocar ~100 ficheros de test; los guards se prueban con `deployment` explícito.

**Por qué es difícil de configurar mal**: la configuración del host **no tiene** campo `mode`; no existe variable de entorno que active/desactive la autenticación; el único proceso que puede escuchar sin contraseña rechaza todo cliente no-loopback aunque alguien lance `uvicorn --host 0.0.0.0`.

**Alternativas descartadas**: `mode = "development"` en config o `AUTOPUBLISHER_AUTH=off` (un ajuste olvidado expone la LAN sin contraseña).

---

## §5. Configuración del host

**Decisión**: fichero **TOML** en `$XDG_CONFIG_HOME/autopublisher/config.toml` (por defecto `~/.config/autopublisher/config.toml`), ruta sobrescribible con `AUTOPUBLISHER_CONFIG`. Leído con `tomllib` (stdlib). Lo escribe `autopublisher configure`, **solo con flags** (sin asistente interactivo; plantilla de texto, sin dependencia de escritura TOML), permisos `0600`, directorio `0700`. Sin secretos. Fuera del checkout y del directorio de datos.

```toml
# AutoPublisher host configuration (this machine only; never restored from a backup)
data_dir = "/home/<user>/.local/share/autopublisher"
port = 8000
lan_enabled = false
allowed_hosts = []          # extra names, e.g. ["my-pc.local"]
# frontend_dist = "/path/to/frontend/dist"   # optional
```

Claves desconocidas o tipos inválidos → `serve` falla (exit 78) indicando la clave. `serve` sin fichero → falla indicando el comando real (`uv run python -m app.cli configure …` desde `backend/`) y la guía.

**Precedencia** (de mayor a menor), idéntica en ambos modos salvo el paso 3:

| Valor | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Directorio de datos | `AUTOPUBLISHER_DATA_DIR` | — | `data_dir` del config (solo instalación) | dev: `backend/data`; instalación: `$XDG_DATA_HOME/autopublisher` |
| Cada fichero (`DB_PATH`, `MEDIA_DIR`, `*_APP_FILE`, `GOOGLE_OAUTH_CLIENT_FILE`, `MEDIA_DELIVERY_FILE`) | su `AUTOPUBLISHER_*` individual existente | `<directorio de datos>/<nombre por defecto>` | | |

**Precedencia confirmada (C3)**, por valor: (1) variable `AUTOPUBLISHER_*` individual específica; (2) `AUTOPUBLISHER_DATA_DIR`; (3) `data_dir` del TOML del host (solo instalación); (4) default. Los overrides individuales existentes siguen ganando (FR-040). El entorno prevalece sobre el fichero (convención). `serve` registra en el log las rutas efectivas y avisa si hay overrides individuales activos. `backup`/`restore` rechazan configuraciones con overrides individuales que apunten fuera del directorio de datos (§20, §22).

`port`, `lan_enabled`, `allowed_hosts`, `frontend_dist` solo vienen del fichero (sin variables de entorno nuevas: menos superficie).

**Alternativas descartadas**: solo variables de entorno / `EnvironmentFile` (ligado a systemd, difícil de validar y documentar); `.env` en el checkout (se versiona por error, vive dentro del código).

---

## §6. Directorio de datos

```text
<data_dir>/                         0700
├── autopublisher.db                PORTABLE (installation_auth incluida; auth_sessions vive aquí pero nunca viaja en backups)
├── media/
│   ├── projects/<id>/…             PORTABLE solo lo referenciado por la BD (originales + copias limpias)
│   └── tmp/                        runtime (se vacía al arrancar)
├── google-oauth-client.json        PORTABLE si existe (0600)
├── instagram-app.json              PORTABLE si existe
├── threads-app.json                PORTABLE si existe
├── tiktok-app.json                 PORTABLE si existe
├── telegram-app.json               PORTABLE si existe
├── media-delivery.json             PORTABLE si existe
└── tmp/                            runtime: spooling de uploads (TMPDIR del proceso)
```

Fuera del directorio de datos: configuración del host (`~/.config/autopublisher/`), logs (`~/.local/state/autopublisher/logs/`), locks (`<home de passwd>/.local/state/autopublisher/locks/`, §9), backups (`~/autopublisher-backups/` por defecto), `.venv`, `frontend/dist`, `node_modules`.

El backup usa **inclusión explícita** (copia de la BD sin sesiones + ficheros referenciados + los seis JSON conocidos), nunca `zip(data_dir)`. Compatibilidad: `backend/data` ya tiene esta forma (BD, `media/`, JSON) → en desarrollo no cambia nada.

---

## §7. Uploads grandes y temporales

**Hallazgo**: Starlette 1.7 hace spool a disco a partir de 1 MiB en `tempfile.gettempdir()`; `SpooledTemporaryFile` pasa a `TemporaryFile` anónimo (borrado al cerrar) → nunca 2 GiB en RAM salvo que `/tmp` sea `tmpfs`. Después hay una segunda copia a `<media>/tmp` y `os.replace`.

**Decisión**: en `serve`, antes de construir la app: crear `<data_dir>/tmp` (0700), fijar `tempfile.tempdir` y `os.environ["TMPDIR"]` a esa ruta (también hereda `ffmpeg/ffprobe`). Sin cambios en el pipeline ni en el límite de 2 GiB. Desarrollo sin cambios (README ya documenta `TMPDIR`).

**Alternativas descartadas**: parser de multipart propio / streaming directo a `media/tmp` (reescritura sin necesidad); subir `spool_max_size` (empeora RAM).

---

## §8. Servicio persistente: `systemd --user`

**Decisión**: unidad de usuario `~/.config/systemd/user/autopublisher.service`, escrita por `autopublisher install-service` (plantilla con rutas absolutas del checkout):

```ini
[Unit]
Description=AutoPublisher
Documentation=file://<repo>/docs/deployment.md
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=exec
WorkingDirectory=<repo>/backend
ExecStart=<repo>/backend/.venv/bin/python -m app.cli serve
Environment=PYTHONUNBUFFERED=1
UMask=0077
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=78
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=graphical-session.target
```

- **Rutas y entorno (M3, M4)**: `install-service` resuelve el directorio `backend` a partir del propio código (absoluto, nunca del cwd) y `<backend>/.venv/bin/python` absoluto (falla si no existe: "run `uv sync --frozen --no-dev` in backend/ first"). `WorkingDirectory` es **obligatorio**: `python -m app.cli` importa `app` desde él. El servicio en ejecución no necesita `uv`. El servicio **no** hereda el entorno de la shell: su única fuente de configuración es el TOML del host; si el TOML usado no es la ruta por defecto, la unidad lleva `Environment=AUTOPUBLISHER_CONFIG=<ruta absoluta>`. Si al instalar hay `AUTOPUBLISHER_DATA_DIR` u overrides `AUTOPUBLISHER_*` de rutas en el entorno, `install-service` se **niega** ("These environment overrides are not persistent for the service … Move them to the host configuration before installing the service.") y no copia variables de la shell. Si el checkout se mueve: recrear/sincronizar `.venv` y volver a ejecutar `install-service`.
- **Backoff**: `RestartSec=5` + `StartLimitIntervalSec=300`/`StartLimitBurst=5` bastan en 020 (sin backoff progresivo).
- **Dentro de la sesión**: el user manager se arranca con el primer login; `graphical-session.target` se activa con la sesión GNOME, cuando `gnome-keyring` ya está disponible por D-Bus de sesión (`DBUS_SESSION_BUS_ADDRESS` está en el entorno del user manager en este host). Al cerrar sesión el servicio se detiene (`PartOf`), coherente con D13.
- **Sin lingering** (`loginctl enable-linger` no se usa: arrancaría sin keyring, contra D13).
- **Reinicio**: `Restart=on-failure` cubre salida no-cero y señales (SIGKILL); `RestartSec=5`; tras 5 fallos en 5 min la unidad queda `failed` y visible en `systemctl --user status`. Exit **78** (`EX_CONFIG`) = configuración inválida / falta contraseña / falta `dist` → no se reintenta en bucle.
- **Parada ordenada**: SIGTERM → uvicorn graceful shutdown (`timeout_graceful_shutdown=20`) → lifespan `finally` (`scheduler.stop()`, `runner.stop()`); `TimeoutStopSec=30` > 20.
- **Gestión**: `systemctl --user start|stop|restart|status autopublisher`, `journalctl --user -u autopublisher` (documentados, no envueltos).

**Keyring y auto-login (C1, aprobada)**: con login automático de GNOME, `gnome-keyring` **no** se desbloquea (no hay contraseña de login que PAM pueda usar) salvo que el llavero tenga contraseña vacía (secretos sin cifrar en disco). El servicio arranca igualmente; el primer acceso a secretos muestra un diálogo de desbloqueo; mientras no se desbloquee, las publicaciones automáticas fallan visiblemente (preflight, §1) y acaban en Missed, y el diagnóstico muestra `locked`. La guía lo explica y desaconseja un llavero sin contraseña solo para arrancar desatendido.

**Alternativas descartadas**: unidad de sistema (sin sesión → sin keyring); XDG autostart `.desktop` (sin restart/backoff/status); cron `@reboot` (antes del login); Docker (sin D-Bus de sesión ni keyring, pieza extra).

---

## §9. Instance lock (FR-014) — locks estables

**Requisitos**: impedir (1) dos procesos sobre el mismo directorio de datos y (2) dos schedulers sobre la misma BD efectiva aunque los directorios de datos difieran por overrides; la exclusión no puede depender de un fichero dentro del directorio de datos, porque el restore lo sustituye.

**Decisión**: locks `fcntl.flock(LOCK_EX | LOCK_NB)` (**no** `fcntl.lockf`: los locks POSIX no entran en conflicto entre dos aperturas del mismo proceso) sobre ficheros en un **directorio de locks estable, fuera del directorio de datos**: una **raíz única** `<home>/.local/state/autopublisher/locks/` (0700), donde `<home>` sale exclusivamente de `pwd.getpwuid(os.geteuid()).pw_dir` (canonicalizada). La raíz **no** depende de variables de entorno (`HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR`, `TMPDIR`, `AUTOPUBLISHER_*`) ni del TOML y no es configurable: dos procesos que comparten un recurso siempre encuentran el mismo fichero de lock. Es persistente a propósito (un fichero de lock no bloqueado es inocuo; la exclusión es el `flock` sobre el descriptor), así que no depende de que exista una sesión. Si la home no existe en la base de usuarios, no es absoluta, no es un directorio del usuario o es escribible por otros, o si la raíz final es un symlink, no pertenece al usuario o tiene permisos de grupo/otros, se falla con `LockRootUnsafe` sin recurrir a `/tmp` ni a otra ruta (revisión 2026-10-20 tras Checkpoint A). Cada fichero se nombra con el SHA-256 (16 primeros hex) de la **ruta canónica** (`Path.resolve()`, sigue symlinks, no exige que exista) del recurso protegido:

| Lock | Fichero | Protege | Lo toman |
|---|---|---|---|
| M (mantenimiento) | `maint-<hash(data_dir)>.lock` | Operaciones offline/maintenance entre sí | `restore`, `backup`, `set-password` |
| A (directorio de datos) | `data-<hash(data_dir)>.lock` | Mismo directorio de datos | proceso servidor (dev e instalación), `restore` |
| B (BD efectiva) | `db-<hash(db_path)>.lock` | Misma SQLite efectiva | proceso servidor (dev e instalación), `restore` |

- **Orden de adquisición** fijo: M → A → B; liberación en orden inverso. Si uno falla, se liberan los ya tomados y se informa del que está ocupado. Al tener un orden total no hay interbloqueos.
- **Crash**: `flock` lo libera el kernel al morir el proceso → no hay locks huérfanos; el fichero puede quedarse (vacío de significado) y se reutiliza.
- **Contenido** (solo informativo, para el mensaje): PID, comando y ruta protegida. Mensaje humano: "AutoPublisher is already running with the data directory /home/…/autopublisher (process 1234). Stop it first: `systemctl --user stop autopublisher`." (exit 75).
- **Estabilidad frente al restore**: los locks se derivan de la **ruta** canónica, no del inodo ni de un fichero dentro del directorio; el swap (`rename`) del restore no los mueve ni los sustituye, y la ruta del directorio de datos tras el swap es la misma → un `serve` lanzado durante o después del swap choca con A/B mientras el restore los mantenga.
- **Servidor** (desarrollo e instalación): toma A y B al **inicio del lifespan**, antes de migraciones, y los mantiene hasta salir. `--reload`: el worker saliente los libera antes de que el nuevo los tome (reintento breve de 5 s con espera de 0,5 s antes de fallar, para absorber la carrera de la recarga).
- **backup**: toma solo M (es online; no compite con el servidor, sí con un restore u otro backup).
- **restore**: toma M, A y B durante **toda** la operación (validación, staging, swap y limpieza) → imposible con el servidor en marcha.
- **set-password**: toma M (no puede escribir en una BD que un restore está sustituyendo); compatible con el servidor en marcha. Migraciones: solo si A está libre; con A ocupado y el esquema por detrás de head → "Restart AutoPublisher first." (exit 75), sin tocar el esquema.
- **status**: observación momentánea: lee los metadatos del lock como pista y, como mucho, un `LOCK_NB` liberado al instante; nunca espera.
- **Tests**: `create_app()` sin `deployment` también toma A/B; el `conftest` aísla la raíz de locks con una *seam* interna de tests (sustituye solo el helper interno `instance_lock._passwd_home` por una home en `tmp_path`, fixture autouse), nunca vía variables de entorno. Si algún test existente abre dos apps simultáneas sobre la misma BD, se ajusta ese test.

**Alternativas descartadas**: `<db>.lock` junto a la BD (el swap del restore lo sustituiría y un servidor podría arrancar a mitad de restore); PID file con comprobación de proceso (stale locks, carreras); lock en la BD (sobrevive al crash); `$XDG_RUNTIME_DIR` o `/run/user/<uid>` (puede no existir fuera de la sesión, p. ej. por SSH, y desaparece al cerrar la última sesión); `$XDG_STATE_HOME` (dos procesos con valores distintos no se excluirían); cualquier raíz configurable o con fallback a una segunda ruta.

---

## §10. Contraseña de instalación

**Hashing**: `hashlib.scrypt` (stdlib, sin dependencia nueva, disponible en ARM64): `n=2**15, r=8, p=1` (~32 MiB, `maxmem=64 MiB`), sal aleatoria de 16 bytes, clave de 32 bytes. Formato autodescriptivo `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`; al verificar con parámetros distintos a los actuales se re-hashea (cambio futuro de parámetros sin migración). Comparación con `hmac.compare_digest`. Longitud: 12–1024 caracteres (cota superior para limitar coste).

Argon2id (`argon2-cffi`) sería igual de válido pero añade una dependencia nativa; scrypt es memory-hard, estándar (RFC 7914) y suficiente para single-user LAN.

**Almacenamiento**: tabla `installation_auth` (fila única) en la BD → portable (el string incluye algoritmo, parámetros y sal), sobrevive restore (FR-053a). Ver [data-model.md](data-model.md).

**Setup inicial y reset**: `autopublisher set-password` (CLI local, `getpass` dos veces, sin eco; toma el lock M, §9). Aplica migraciones si la BD no existe, escribe el hash y **borra todas las sesiones**. Mismo comando para primer setup y para "olvidé la contraseña": requiere acceso local al host con el usuario dueño del directorio de datos (permisos 0700). No existe endpoint de setup ni de reset.

**Cambio desde la app**: `POST /api/auth/password` con `current_password` y `new_password` → verifica la actual (sujeta al rate limit) y, en **una transacción**, `UPDATE … WHERE password_hash = <hash verificado>` (si no afecta a ninguna fila → 401, nada cambia), borra todas las sesiones y crea una nueva para el navegador actual (los demás dispositivos salen; este sigue dentro).

**Carreras (M2)**: el login lee el hash, verifica con scrypt (~100 ms) y, en **una transacción**, relee `password_hash` e inserta la sesión **solo si sigue siendo el hash verificado**; si cambió → 401 genérico sin sesión. Reset (CLI) y cambio sustituyen el hash y borran las sesiones en la misma transacción. Así un login que verificó la contraseña antigua nunca persiste una sesión después de un reset o cambio.

---

## §11. Sesiones

**Decisión**: sesiones **opacas server-side** en SQLite (`auth_sessions`). Token `secrets.token_urlsafe(32)` (256 bits) solo en la cookie; en BD únicamente `sha256(token)`.

**Duración (inequívoca)**:

- **Idle timeout 7 días**: la sesión es válida mientras `now < last_seen_at + 7 d`. Cada petición autenticada renueva `last_seen_at` (escritura como mucho cada 10 min).
- **Vida absoluta 30 días**: `expires_at = created_at + 30 d`; la renovación nunca la supera: validez = `now < min(last_seen_at + 7 d, expires_at)`.
- **Sign out**: borra la fila → inválida de inmediato en todos los procesos (se consulta la BD en cada petición).
- **Cambio de contraseña (app)**: borra todas las filas y crea una nueva para el navegador actual. **Reset (CLI)**: borra todas.
- **Restore**: empieza con cero sesiones (el backup no las contiene, §20; el restore además vacía la tabla por defensa en profundidad, §22).
- **Purga oportunista y acotada**: al arrancar y en cada login se borran las filas caducadas; una sesión inválida detectada en una petición se borra; además, en cada login, si hay más de 20 sesiones válidas se borran las de `last_seen_at` más antiguo hasta quedar en 20 (single-user: tope holgado). La tabla nunca crece sin límite.
- **Reinicios del servicio**: las sesiones sobreviven (están en la BD).

**Cookie** `autopublisher_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, **sin `Domain`** (host-only), `Max-Age` = segundos hasta `expires_at` (30 d al crear). **Sin `Secure`**: el acceso LAN es HTTP y la cookie no se enviaría. Nunca se acepta un token por URL ni por cabecera distinta de la cookie. Sesión nueva en cada login (sin fijación).

**Limitación por HTTP** (D14): contraseña y cookie viajan en claro por la LAN; quien intercepte la red puede robar la sesión. `HttpOnly` evita el robo por JS; `SameSite` y la verificación de origen evitan el uso cross-site; las caducidades acotan la ventana; Sign out y el cambio de contraseña la cierran.

**Portabilidad**: la contraseña (hash con algoritmo, parámetros y sal en el propio string) es portable; las sesiones activas no. No se necesita contador de "generación": la invalidación es borrar filas.

**Alternativas descartadas**: cookie firmada / JWT (la invalidación global exige estado igualmente); sesiones en memoria (se pierden al reiniciar).

---

## §12. Rate limiting de login

**Decisión**: en memoria (proceso único). Ventana deslizante de 15 min: máximo **5 fallos por IP de cliente** y **20 fallos globales**; superado → `429 too_many_attempts` ("Too many attempts. Try again in a few minutes.") sin evaluar la contraseña, hasta que caduquen los fallos. Diccionario acotado (poda de entradas antiguas; máximo 256 IPs, la más antigua se descarta). Un login correcto limpia los fallos de esa IP. Se reinicia al reiniciar el servicio (aceptable). Aplica también a `current_password` del cambio de contraseña. El coste de scrypt (~50–100 ms) añade frenado natural. Fallos y bloqueos se registran en el log (IP, sin contraseña).

**Alternativas descartadas**: Redis/BD (persistencia innecesaria); bloqueo permanente (DoS contra el propio usuario).

---

## §13. CSRF / cross-site

**Decisión**: un único mecanismo además de `SameSite=Lax`: **verificación de origen** en métodos no seguros (`POST/PUT/PATCH/DELETE`) para todas las rutas (incluido `/api/auth/login`, contra login CSRF):

1. Si hay `Origin`: debe ser exactamente `http://<Host validado>` → si no, `403 origin_not_allowed`.
2. Si no hay `Origin`: se acepta solo con `Sec-Fetch-Site: same-origin`; si faltan ambos → `403`.

Los navegadores modernos envían `Origin` en todo `fetch` POST/PUT/PATCH/DELETE (incluidos multipart). Sin token CSRF: no aporta nada frente a esta comprobación con Host validado. GET/HEAD siguen sin efectos (ya es así en la API). Los callbacks OAuth son GET.

Desarrollo: mismo guard (el proxy de Vite conserva `Host: localhost:5173` y el navegador envía `Origin: http://localhost:5173`).

---

## §14. Validación de Host / DNS rebinding

**Decisión**: middleware que acepta la petición solo si el `Host` (nombre + puerto) es válido; si no → `403 host_not_allowed` (JSON).

- El puerto del `Host` debe ser el de escucha (instalación) o cualquiera en desarrollo (Vite 5173).
- Nombre aceptado si:
  - es `localhost`, `127.0.0.1` o `[::1]`; o
  - es un **literal IP igual a la dirección local real del socket** (`scope["server"][0]`) por la que llegó la conexión — cubre la IP LAN actual, cambios por DHCP y múltiples interfaces sin enumerar interfaces (un ataque de DNS rebinding siempre usa un nombre de dominio, nunca un literal IP); o
  - está en `allowed_hosts` del config (nombres explícitos, p. ej. `my-pc.local`), comparación sin mayúsculas.
- Nunca se acepta un `Host` arbitrario, tampoco con LAN activa. No hay resolución DNS.

`scope["server"]` lo fija uvicorn con `getsockname()` del socket aceptado; con bind `0.0.0.0` es la dirección concreta de la interfaz. `serve` arranca uvicorn con `proxy_headers=False` (`X-Forwarded-*` ignorados: el cliente no puede falsear su IP).

---

## §15. Host vs cliente remoto (OAuth loopback)

**Decisión**: "acción del host" = conexión **loopback**: `request.client.host` ∈ {127.0.0.1, ::1} **y** `scope["server"][0]` loopback (mismo criterio que `tiktok_connections._is_loopback`, extraído a un helper común).

| Cómo se abre la app | ¿Connect YouTube/TikTok? |
|---|---|
| `http://127.0.0.1:8000` / `http://localhost:8000` en el host | Sí |
| `http://<IP LAN>:8000` en el propio host | No (el socket no es loopback) → la UI ofrece "Open on this computer: http://127.0.0.1:8000/…" |
| Desde otro dispositivo | No → explicación: "Connect from the computer that runs AutoPublisher." |

Backend (autoridad): `authorize` de YouTube y TikTok en modo instalación → `409 host_only_action` si no es loopback, antes de crear el intento. Frontend: si `window.location.hostname` no es loopback, el botón Connect/Reconnect de esas dos plataformas se sustituye por la explicación + enlace loopback (solo útil en el host). Instagram, Threads y Telegram: sin cambios (funcionan desde cualquier dispositivo autenticado).

---

## §16. OAuth: rutas exentas de sesión

| Ruta | Por qué es seguro sin sesión |
|---|---|
| `GET /api/youtube/oauth/callback` | `state` aleatorio de un intento vivo (10 min, un solo uso) + PKCE; **se añade** la comprobación de cliente loopback (endurecimiento: Google siempre redirige al navegador del host a `127.0.0.1`). |
| `GET /api/tiktok/oauth/callback` | `state` + PKCE + cliente y socket loopback (existente) + puerto real. |
| `GET /api/tiktok/oauth/result` | Página fija sin datos ni reflejo de query (existente). |

Siguen exigiendo sesión (y origen): `authorize`, `attempts/{id}`, `confirm`/`cancel` y el resto. La cookie de sesión puede no viajar con el callback (navegación cross-site / nombre `localhost` vs `127.0.0.1`), por eso la exención; el resultado lo lee la pestaña de la app sondeando el intento con su sesión.

Los callbacks siguen sometidos a la validación de Host (`127.0.0.1:8000` es válido).

---

## §17. Health público

**Decisión**: `GET /health` → `200 {"status":"ok"}` o `200 {"status":"degraded"}`. Sin más campos. `degraded` = la BD no responde a `SELECT 1` **o** el hilo del scheduler no está vivo cuando debería (autostart). **No** incluye keyring (sondearlo sin sesión podría provocar diálogos de desbloqueo y es información de diagnóstico) ni la pausa (es una elección del usuario, no un fallo). 200 en ambos casos: el proceso responde (liveness); el detalle está en el diagnóstico autenticado.

---

## §18. Diagnóstico autenticado

**Decisión**: `GET /api/system/status` (sesión requerida) con `mode`, `database`, `credential_store`, `deployment` (puerto, LAN, direcciones candidatas, nombres permitidos). El estado del scheduler y la pausa **siguen** en `GET /api/automation` (sin duplicar). Settings combina ambos.

**Estado del almacenamiento seguro sin prompts ni falsos positivos** — nuevo `probe()` en `credential_store`, cacheado 60 s, que nunca lee ni escribe secretos ni llama a `unlock()`:

| Resultado | Cuándo |
|---|---|
| `available` | Backend `SecretService`: conexión D-Bus de sesión correcta, `secretstorage.Collection(bus)` (alias `default` **existente**, el que usa keyring) e `is_locked()` es `False`. |
| `locked` | Backend `SecretService`: colección por defecto bloqueada. Degradación: la publicación automática fallará hasta desbloquearla. |
| `unavailable` | Backend no permitido (`ensure_secure_backend` falla), sin bus de sesión, servicio Secret Service ausente o error de D-Bus. |
| `unknown` | El alias `default` no existe (`ItemNotFoundException`: keyring lo crearía con un diálogo), backend permitido que no se puede comprobar sin interacción (`libsecret`, KWallet, macOS, Windows) o cualquier resultado ambiguo. Degradación **informativa**: nunca se presenta como "available". |

**Prohibido en el sondeo (H2)**: `secretstorage.get_default_collection()` (crea la colección si no existe → diálogo), `create_collection`, `unlock()`, `keyring.get_password`/`set_password` y cualquier lectura de items. `keyring.get_password` no sirve como sondeo: desbloquea la colección y muestra un diálogo. `secretstorage` se importa solo en `probe()` y solo con el backend `SecretService`; con otros backends Linux el resultado es `unknown` (no se acopla 020 a Secret Service más allá del diagnóstico). En Ubuntu GNOME (host actual, backend `SecretService`) se obtiene `available`/`locked`/`unavailable` reales.

---

## §19. Logging

**Decisión**: combinación mínima configurada por `serve` (desarrollo intacto):

- `RotatingFileHandler` en `$XDG_STATE_HOME/autopublisher/logs/autopublisher.log` (por defecto `~/.local/state/autopublisher/logs/`), 5 MiB × 5 ficheros, directorio `0700`, ficheros `0600` (UMask 0077). Fuera del directorio de datos y del backup.
- `stderr` → journal del usuario (`journalctl --user -u autopublisher`) para errores de arranque antes de configurar el fichero.
- Nivel INFO para `app.*` y `uvicorn.error`; **access log desactivado** (evita volumen y URLs de callback); se registran en su lugar los eventos de autenticación (login ok/fallo/bloqueo con IP, logout, cambio de contraseña), arranque (modo, puerto, LAN, rutas efectivas), parada, migraciones, ciclo de vida del scheduler/publicaciones (ya existente) y errores.
- Los filtros de redacción existentes siguen instalados en `create_app`; se añade un test que recorre flujos representativos (login, OAuth callback, publicación fallida) y comprueba que el fichero de log no contiene contraseñas, tokens ni secrets.

**Alternativas descartadas**: solo journald (en Raspberry Pi OS el journal es volátil por defecto: no cumple "persisten entre reinicios" de forma predecible); stack de observabilidad.

---

## §20. Backup online consistente

**Hallazgos**: BD SQLite en modo journal por defecto (no WAL); ficheros de Media **inmutables** una vez referenciados (escritura en `tmp` + `os.replace` antes del commit; nunca se modifican; copias limpias huérfanas solo se borran al arrancar); cada fichero referenciado tiene su SHA-256 en la BD (`checksum`, `sanitized_checksum`); los JSON de plataforma solo cambian por edición manual.

**Definición de snapshot consistente**: *la BD en el instante T (API de backup de SQLite) sin sesiones activas + exactamente los ficheros de Media que esa BD referencia, cuyos bytes archivados coinciden con el checksum que esa misma BD registra + los JSON de plataforma presentes, archivados con el checksum de los bytes exactos leídos*. Imports en curso no referenciados en T no se incluyen (coherente con T).

**Algoritmo** (`autopublisher backup [--output DIR]`, con el servicio en marcha o no, sin pararlo):

1. Resolver rutas (precedencia §5); rechazar overrides individuales que apunten fuera del directorio de datos; resolver `DIR` y **rechazar si está dentro del directorio de datos** (o lo contiene). Tomar el lock M (§9).
2. Crear `DIR` (0700). Borrar `.autopublisher-backup-*.partial` y snapshots temporales antiguos de `DIR`. Comprobar espacio libre ≥ tamaño estimado × 1.05.
3. `sqlite3.connect(db).backup(tmp_snapshot)` a un fichero temporal **en `DIR`** (snapshot transaccional; reintenta ante `SQLITE_BUSY`).
4. **En la copia** (nunca en la BD en uso): si la tabla `auth_sessions` existe, `DELETE FROM auth_sessions;`; después `VACUUM` (no quedan hashes de tokens en páginas libres). Una BD anterior a 020 (sin `auth_sessions` ni `installation_auth`) se respalda tal cual: no se exige migrar el origen. `installation_auth` se conserva cuando existe.
5. Desde la copia: lista de rutas referenciadas (`storage_path`, `sanitized_storage_path`) con su checksum esperado; versión Alembic.
6. Escribir `DIR/.autopublisher-backup-<ts>.tar.partial` (0600):
   - `autopublisher.db` desde la copia (SHA-256 calculado al escribir).
   - Cada fichero de Media: abrir, `fstat`, añadir al tar con ese tamaño leyendo en streaming y calculando SHA-256; si el fichero falta, cambia de tamaño o el hash ≠ checksum de la BD → **abortar** ("Media changed during backup; run it again"). Nunca se archiva un fichero cuyo contenido no corresponde a la BD.
   - Cada JSON de plataforma presente: leer una vez en memoria (tamaño máximo 64 KiB), hashear y escribir **esos mismos bytes** → bytes y checksum siempre coinciden aunque el fichero se edite a la vez.
   - `manifest.json` como último miembro, con todos los checksums (§21).
7. `flush` + `fsync`; **verificación por relectura**: reabrir el `.partial`, comprobar miembros y recomputar todos los SHA-256 contra el manifest.
8. `rename` atómico a `autopublisher-backup-<ts>.tar` (mismo directorio) y `fsync` del directorio. Solo entonces el artefacto existe con nombre válido.
9. Cualquier error, `ENOSPC` o `KeyboardInterrupt` → borrar `.partial` y snapshot temporal, exit ≠ 0 con mensaje claro. Un `SIGKILL` deja un `.partial` oculto, nunca un `.tar` válido; el siguiente backup lo limpia.

No hace falta barrera con el servicio: la inmutabilidad de los ficheros referenciados + la verificación por checksum hacen imposible un artefacto válido con bytes inesperados; la única carrera posible (un reinicio del servicio que barra una copia limpia desreferenciada a mitad) produce un fallo explícito.

**Alternativas descartadas**: copiar el `.db` en caliente (inconsistente); borrar sesiones en la BD viva (cerraría la sesión de todos los navegadores por hacer un backup); parar el servicio (innecesario); snapshots LVM/btrfs (dependen del sistema).

---

## §21. Formato de backup

**Decisión**: **tar sin comprimir** (`tarfile`, stdlib). La Media ya está comprimida; gzip solo gasta CPU (relevante en Raspberry Pi). Nombre `autopublisher-backup-YYYYMMDDTHHMMSSZ.tar`.

```text
autopublisher.db
media/projects/<id>/<file>          (solo referenciados)
config/<platform>.json              (solo los presentes; nombre por defecto)
manifest.json                       (último miembro)
```

La BD archivada no contiene filas en `auth_sessions` (§20 paso 4).

`manifest.json`:

```json
{
  "format": "autopublisher-backup",
  "format_version": 1,
  "created_at": "2026-10-20T10:15:00Z",
  "app_version": "0.1.0",
  "schema_revision": "<alembic head of the snapshot>",
  "components": ["database", "media", "platform_config"],
  "files": [{"path": "autopublisher.db", "size": 319488, "sha256": "…"}, …],
  "source": {"hostname": "…"}            // informative only, never applied
}
```

No incluye: tokens del keyring, `tmp/`, `media/tmp/`, ficheros huérfanos, lock, logs, configuración del host, backups previos.

---

## §22. Restore

**Decisión**: `autopublisher restore <archivo.tar> [--yes]`:

1. Resolver el directorio de datos destino (precedencia §5) e imprimir las rutas efectivas y los overrides de entorno detectados; rechazar overrides individuales (el restore solo soporta la disposición estándar del directorio de datos). Operar sobre la **ruta canónica** (un `data_dir` symlink se sigue y el swap ocurre en el destino resuelto). Rechazar un destino que sea **punto de montaje** ("use a subdirectory inside the mounted disk").
2. Tomar **M → A → B** (§9) y mantenerlos hasta terminar. Si A o B están ocupados: "Stop AutoPublisher first: `systemctl --user stop autopublisher`" (exit 75). Los locks viven fuera del directorio de datos, así que el swap no los afecta.
3. Abrir el tar (`tarfile`, sin extraer nada todavía); leer `manifest.json`; validar `format`, `format_version == 1` y campos obligatorios.
4. Validar **todos** los miembros antes de escribir nada: solo `isreg()` y los directorios esperados; rechazar **nombres duplicados**, tipos sparse u otros no regulares; las cabeceras PAX son solo metadatos y nunca amplían el conjunto de rutas permitido (se valida el nombre efectivo); rutas relativas normalizadas, sin `..`, sin absolutas, sin enlaces (sym/hard), dispositivos ni FIFOs; prefijos permitidos (`autopublisher.db`, `media/projects/<id>/<nombre>`, `config/<nombre conocido>.json`, `manifest.json`); correspondencia exacta 1:1 con `manifest.files`; tamaños = declarados; tamaño total ≤ espacio libre con margen y nº de ficheros ≤ límite razonable (anti tar-bomb).
5. Compatibilidad: `schema_revision` debe existir en `backend/migrations` (si no: "This backup was created by a newer AutoPublisher; update first"). Revisiones antiguas migran al arrancar.
6. Extraer a **staging hermano** del destino (`<parent>/.<name>.restore-<ts>/`, mismo sistema de ficheros → `rename` atómico; 0700), escribiendo cada fichero con `open(..., "xb")` dentro del staging y verificando SHA-256 en streaming; `config/*.json` → raíz del staging con 0600; `PRAGMA integrity_check` sobre la BD; `DELETE FROM auth_sessions` **solo si la tabla existe** (defensa en profundidad: un backup de formato v1 ya no las trae; una BD anterior a 020 no tiene la tabla).
7. Confirmación (salvo `--yes`) con el resumen del manifest (fecha, versión, nº de ficheros, host origen informativo).
8. Swap: si el destino existe, `rename(<data_dir>, <parent>/<name>.before-restore-<ts>)`; `rename(staging, <data_dir>)`; `fsync` del directorio padre. Si el segundo `rename` falla, se deshace el primero. Los locks (fuera de `<data_dir>`) siguen tomados durante todo el swap.
9. Liberar B → A → M. Mensaje final con comandos reales: `systemctl --user start autopublisher`, iniciar sesión con la contraseña **del backup** (si no tenía, `uv run python -m app.cli set-password` desde `backend/`), reconectar las cuentas "Reconnect needed"; si el origen parece un `backend/data` de desarrollo, recordar que retirarlo es obligatorio (M7). La copia `.before-restore-<ts>` se conserva para que el usuario la borre.

**Atomicidad real (L6)**: los dos `rename` no forman una transacción. Si el proceso muere entre ambos, queda `<data_dir>` ausente y `<data_dir>.before-restore-<ts>` presente (más el staging): la guía explica reconocerlo y recuperarlo renombrando `.before-restore-<ts>` de vuelta. Staging + swap se mantiene porque reduce el riesgo a esa ventana mínima.

Cualquier fallo en 1–7 deja el destino intacto (SC-011) y borra el staging. No toca la configuración del host (otro directorio), no habilita LAN, no cambia puerto. Tras el restore hay **cero sesiones activas** y la misma contraseña. Restaurar sobre una versión anterior de AutoPublisher: no soportado (paso 5).

---

## §23. Descubrimiento de direcciones de red

**Decisión** (solo para mostrar en Settings y `autopublisher status`; no afecta a la seguridad):

- Dirección primaria: socket UDP `connect()` a una dirección privada no enrutable (`10.255.255.255:1`; no envía paquetes) → `getsockname()`.
- Más la dirección local del socket de la petición actual si no es loopback.
- Filtrar: solo IPv4/IPv6 privadas (`ipaddress.is_private`), no loopback, no link-local; deduplicar.
- Nombre sugerido: `<hostname>.local` marcado como "may work if your network supports it".
- Sin resultados → "Could not detect the address; run `ip -4 addr` on the host" (documentado).

Sin servicios externos ni dependencias (`psutil` descartado).

---

## §24. CLI

**Decisión**: un módulo `app/cli.py` con `argparse` (stdlib), invocado como `uv run python -m app.cli <cmd>` (unidad systemd: `.venv/bin/python -m app.cli serve`). El backend no está empaquetado (sin `[build-system]`), por lo que un `[project.scripts]` no se instalaría; empaquetarlo no aporta valor en 020. "autopublisher <cmd>" en la documentación es la abreviatura. Comandos: `configure`, `set-password`, `serve`, `install-service`, `uninstall-service`, `status`, `backup`, `restore`. Typer/Click descartados (dependencia por ergonomía). Contrato en [contracts/cli.md](contracts/cli.md).

---

## §25. Mobile sobre HTTP en LAN

**Hallazgo**: el frontend no usa APIs de contexto seguro. Riesgos a verificar en dispositivo real: Range en `<video>` de iOS Safari (Starlette `FileResponse` lo soporta), cookie `SameSite=Lax` en Safari iOS sobre HTTP con IP (soportado), `window.open` en paneles Instagram/Threads (no bloqueado si se abre en el gesto), selector de ficheros y subida por Wi-Fi.

**Decisión**: verificación manual en el STOP gate de LAN/móvil ([quickstart.md](quickstart.md)); solo correcciones pequeñas (FR-073).

---

## §26. Cabeceras de seguridad (bajo coste)

En modo instalación, todas las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`. Sin CSP en 020 (riesgo de romper la app sin beneficio proporcional en LAN; se registra como posible mejora).
