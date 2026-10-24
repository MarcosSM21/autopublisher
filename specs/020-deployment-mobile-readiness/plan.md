# Implementation Plan: Deployment & Mobile Readiness

**Branch**: `020-deployment-mobile-readiness` | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-deployment-mobile-readiness/spec.md`

## Summary

AutoPublisher pasa a tener un **modo instalación** servido por un único proceso FastAPI (UI compilada + API en un puerto), arrancado por un comando `python -m app.cli serve` (abreviado `autopublisher serve`) que lee una configuración del host en TOML (`~/.config/autopublisher/config.toml`), protegido por una **contraseña única** (scrypt, sesiones opacas en SQLite, verificación de Origin y de Host), gestionado como **servicio `systemd --user`** ligado a la sesión gráfica (acceso al keyring, D13), con un **directorio de datos** portable, **locks `flock` estables** fuera del directorio de datos (por directorio de datos y por BD efectiva), **backup online** (SQLite backup API sobre una copia sin sesiones + Media referenciada verificada por checksum, `.tar` con manifest) y **restore** validado con staging y swap que mantiene los locks. El desarrollo (`uvicorn --reload` + Vite) se conserva y queda limitado a clientes loopback. Sin proxy, sin Docker, sin dependencias nuevas de runtime.

Detalle de cada decisión y alternativas: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 6 / React 19 (frontend)

**Primary Dependencies**: FastAPI 0.142 / Starlette 1.7, uvicorn, SQLAlchemy 2.1, Alembic, keyring (+ secretstorage, ya transitiva en Linux); stdlib nueva en uso: `tomllib`, `hashlib.scrypt`, `fcntl`, `tarfile`, `sqlite3.backup`, `argparse`, `logging.handlers`. **Ninguna dependencia nueva** (`secretstorage`, ya instalada como dependencia de `keyring` en Linux, se declara explícitamente con marcador `sys_platform == 'linux'` porque `probe()` la importa directamente).

**Storage**: SQLite (2 tablas nuevas: `installation_auth`, `auth_sessions`), Media en disco, ficheros TOML/JSON

**Testing**: pytest + TestClient (backend), Vitest + Testing Library (frontend); tests dirigidos por bloque, suites completas solo en CI

**Target Platform**: Linux x86-64 con sesión gráfica (Ubuntu GNOME, systemd 255); ARM64 sin incompatibilidades de código conocidas (no verificado)

**Project Type**: web application (backend + frontend)

**Performance Goals**: disponible < 2 min tras login (SC-001), health OK < 30 s tras crash (SC-002); una consulta SQLite extra por petición API (sesión)

**Constraints**: proceso único; sin HTTPS; contraseña obligatoria en instalación; uploads 2 GiB sin RAM (spool a disco en el directorio de datos); scrypt ~32 MiB por verificación

**Scale/Scope**: single-user, 1 host, pocos dispositivos LAN

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Notas |
|---|---|---|
| I. Simplicidad y alcance | ✅ | Un proceso, sin proxy/Docker/Redis, sin dependencias nuevas; CLI con `argparse`; diagnóstico reutiliza `/api/automation`. Nada fuera de la spec. |
| II. Spec-Driven | ✅ | Spec aprobada sin clarifications abiertas; las contradicciones encontradas se señalan abajo, no se resuelven en silencio. |
| III. Arquitectura modular | ✅ | Módulos nuevos separados (`deployment`, `auth`, `backup`, `cli`); los publishers no cambian; OAuth host-only como helper común reutilizado por YouTube/TikTok. |
| IV. Seguridad | ✅ | Hash no reversible; tokens solo hasheados en BD; secretos nunca en logs/API/backup de keyring; config del host sin secretos; permisos 0700/0600; threat model HTTP documentado (D14). |
| V. Calidad | ✅ | Tests dirigidos por bloque; regresión explícita keyring→Missed; fallos de backup/restore visibles y atómicos. |
| VI. Git | ✅ | Commits pequeños por fase; docs actualizadas (README + `docs/deployment.md`). |
| Arquitectura base | ✅ | FastAPI + React/Vite + SQLite + filesystem + scheduler local + keyring del SO, sin cambios. Nada de SaaS/multiusuario/cloud. |

Re-check post-diseño: ✅ sin violaciones; **Complexity Tracking** vacío.

## Architecture

```text
                    host (user session, systemd --user)
 ┌──────────────────────────────────────────────────────────────────┐
 │ autopublisher.service ──► autopublisher serve (uvicorn, 1 proc)  │
 │   bind 127.0.0.1:8000 (LAN off) | 0.0.0.0:8000 (LAN on)          │
 │                                                                  │
 │   guards: Host ► Origin(unsafe) ► Session(/api/*) ► headers      │
 │   ├── /health                       (public, ok|degraded)        │
 │   ├── /api/auth/*                   (login/logout/password)      │
 │   ├── /api/*  (existing API + /api/system/status)                │
 │   ├── /api/{youtube,tiktok}/oauth/callback  (public, loopback)   │
 │   ├── /assets/*                     (frontend/dist)              │
 │   └── /*  → index.html              (SPA fallback, never /api)   │
 │   lifespan: lock ► migrations ► … ► scheduler (unchanged)        │
 └──────────────────────────────────────────────────────────────────┘
   ~/.config/autopublisher/config.toml   (host, not in backup)
   ~/.local/share/autopublisher/          (data dir: portable + tmp)
   ~/.local/state/autopublisher/logs/     (rotating logs, host)
   <passwd home>/.local/state/autopublisher/locks/  (flock: maint / data dir / effective DB)
   ~/autopublisher-backups/*.tar          (backups, outside data dir)
   keyring (Secret Service, session D-Bus) (tokens, never backed up)
```

Desarrollo: `uvicorn app.main:app --reload` (guards de desarrollo: solo loopback, Host loopback, Origin) + Vite en 5173 → sin cambios de uso.

## Decisiones principales (resumen; detalle en research.md)

| # | Decisión | Descartado |
|---|---|---|
| R2 | FastAPI sirve `dist` + SPA fallback | nginx/Caddy, `vite preview` |
| R3 | Build separado; `dist` en el checkout o `frontend_dist` | `dist` versionado, pipeline de releases |
| R4 | Modo = entrypoint (`serve` vs `app.main:app`); sin ajuste de modo ni bypass | `mode` en config, flag de auth |
| R5 | TOML en XDG config; precedencia (C3): `AUTOPUBLISHER_*` individual > `AUTOPUBLISHER_DATA_DIR` > TOML del host > default | Solo env / `.env` |
| R7 | `TMPDIR`/`tempfile.tempdir` → `<data_dir>/tmp` en `serve` | Reescribir el parser multipart |
| R8 | `systemd --user`, `WantedBy/PartOf=graphical-session.target`, sin linger | Unidad de sistema, autostart `.desktop`, Docker |
| R9 | Locks `flock` en una raíz única `<home de passwd>/.local/state/autopublisher/locks/` (independiente del entorno) derivados del hash de rutas canónicas: M (mantenimiento), A (data dir), B (BD efectiva); orden M→A→B; servidor A+B, backup M, set-password M, restore M+A+B | `<db>.lock` junto a la BD (el swap del restore lo sustituiría), PID file, lock en BD |
| R10 | scrypt stdlib, formato autodescriptivo, set/reset por CLI local | argon2-cffi, endpoint de setup |
| R11 | Sesiones opacas en SQLite, token de 256 bits hasheado; idle 7 d renovable, absoluta 30 d sin ampliación; purga oportunista + tope 20; cookie `HttpOnly`, `SameSite=Lax`, `Path=/`, sin `Domain`, sin `Secure`; **no portables** | JWT, cookie firmada |
| R12 | Rate limit en memoria por IP + global | Redis, lockout permanente |
| R13 | Verificación de `Origin` (fallback `Sec-Fetch-Site`) | Token CSRF |
| R14 | Host: loopback, IP literal = dirección del socket, `allowed_hosts` | Enumerar interfaces, aceptar cualquier Host |
| R15 | Host-only = cliente y socket loopback; backend 409 + UI explicativa | Detectar "host" por IP LAN |
| R17 | `/health` → `ok`/`degraded` sin detalle | Health detallado público |
| R18 | `/api/system/status` + `probe()` del keyring sin `unlock`: `available`/`locked`/`unavailable`/`unknown` (nunca `available` sin comprobarlo) | `keyring.get_password` como sondeo |
| R19 | Fichero rotatorio en XDG state + stderr/journal; access log off | Solo journald |
| R20 | Backup = snapshot SQLite → en la copia se vacía `auth_sessions` + `VACUUM` → ficheros referenciados verificados contra la BD → JSON hasheado sobre los bytes leídos → `.partial` → relectura → `rename` | Copiar el `.db`, borrar sesiones de la BD viva, parar el servicio |
| R21 | `.tar` sin comprimir + `manifest.json` (v1, sha256) | zip, tar.gz |
| R22 | Restore: M+A+B toda la operación, validación completa antes de escribir, staging hermano (mismo FS), cero sesiones, swap con copia previa; los locks no se mueven | Extraer in situ |

## Cambios persistentes / migraciones

- **Alembic**: una revisión nueva que crea `installation_auth` (portable) y `auth_sessions` (no portable: la copia del backup se vacía) ([data-model.md](data-model.md)). Sin cambios en tablas existentes. Se aplica sola al arrancar (también en desarrollo; las tablas quedan vacías y sin uso allí).
- **Ficheros nuevos fuera del repo**: `config.toml`, unidad systemd, logs, locks (XDG state), backups.
- **Compatibilidad**: `backend/data` sigue siendo el default de desarrollo; todas las `AUTOPUBLISHER_*` existentes siguen funcionando y ganan; `uvicorn app.main:app --reload` y Vite sin cambios de uso.

## Interfaces nuevas

- **API**: `GET /api/auth/session`, `POST /api/auth/login|logout|password`, `GET /api/system/status`; `/health` con `degraded`; `409 host_only_action` en authorize YouTube/TikTok; guards con códigos nuevos ([contracts/api.md](contracts/api.md)).
- **UI**: `/login`, manejo global de 401, Settings → "This installation" (estado, acceso LAN, aviso HTTP, puerto) + Change password + Sign out, explicación host-only en Connect YouTube/TikTok ([contracts/ui.md](contracts/ui.md)).
- **CLI**: `autopublisher configure|set-password|serve|install-service|uninstall-service|status|backup|restore` ([contracts/cli.md](contracts/cli.md)).

## Project Structure

### Documentation (this feature)

```text
specs/020-deployment-mobile-readiness/
├── spec.md
├── plan.md              # this file
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   ├── ui.md
│   └── cli.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml                    # + secretstorage (marker linux), no packaging changes
├── app/
│   ├── config.py                     # + data dir resolution (AUTOPUBLISHER_DATA_DIR), defaults per mode
│   ├── deployment.py                 # NEW: HostConfig (TOML), DeploymentSettings (dev/installation), address discovery
│   ├── guards.py                     # NEW: loopback-only, Host, Origin, session, security headers middleware
│   ├── auth.py                       # NEW: scrypt hashing, sessions, rate limiter, /api/auth router
│   ├── system_status.py              # NEW: /api/system/status, public health aggregate
│   ├── spa.py                        # NEW: dist mounting + SPA fallback (installation only)
│   ├── instance_lock.py              # NEW: stable flock locks (maint / data dir / effective DB)
│   ├── backup.py                     # NEW: backup + restore (validation, staging, swap)
│   ├── cli.py                        # NEW: argparse commands, serve, logging setup, systemd unit template
│   ├── credential_store.py           # + probe() without unlock
│   ├── loopback.py                   # NEW (small): is_loopback_request shared by YouTube/TikTok
│   ├── youtube_connections.py        # + host-only authorize, loopback callback
│   ├── tiktok_connections.py         # + host-only authorize (reuse helper)
│   ├── models.py                     # + InstallationAuth, AuthSession
│   └── main.py                       # create_app(deployment=…), lock in lifespan, module app = development
├── migrations/versions/<rev>_installation_auth.py
└── tests/
    ├── test_deployment_config.py, test_guards.py, test_auth.py, test_spa.py,
    ├── test_instance_lock.py, test_system_status.py, test_backup.py, test_restore.py,
    ├── test_cli.py, test_scheduler_keyring_unavailable.py, test_oauth_host_only.py,
    └── test_logging_redaction.py   (names indicative)

frontend/src/
├── api.ts                            # + auth calls, system status, global 401 handling
├── routes.tsx                        # + /login outside the shell
├── pages/LoginPage.tsx               # NEW
├── pages/SettingsPage.tsx            # + "This installation" + Sign-in section
├── pages/settings/InstallationStatus.tsx, ChangePasswordDialog.tsx   # NEW
├── shell/useAuthSession.ts           # NEW (session bootstrap)
└── components/{YouTube,TikTok}ConnectionPanel.tsx   # + host-only explanation

docs/deployment.md                    # NEW public guide (English)
README.md                             # link + "must be running" via the service
```

**Structure Decision**: aplicación web existente (`backend/` + `frontend/`); el código nuevo se concentra en módulos backend nuevos y pequeños cambios de frontend, sin tocar publishers ni scheduler.

## Fases de implementación

Cada fase es revisable por separado; tests dirigidos al final de cada una.

| Fase | Contenido | Tests dirigidos | Dependencias |
|---|---|---|---|
| P0 | Regresión keyring caído → Missed (5 plataformas) | T8 | — |
| P1 | Rutas: `AUTOPUBLISHER_DATA_DIR`, `HostConfig` TOML + validación, precedencia C3; locks estables (A+B) en el lifespan | T9, T10 (parte) | — |
| P2 | `DeploymentSettings`; `create_app(deployment=…)`; guards loopback/Host/Origin; módulo `app` = desarrollo | T5, T6 | P1 |
| P3 | Auth backend: migración, scrypt, sesiones, rate limit, `/api/auth/*`, guard de sesión, exenciones OAuth | T2, T3, T4 | P2 |
| P4 | SPA serving + cabeceras; `serve` (config, dist, password, TMPDIR, logging, uvicorn) | T1, T14 | P2, P3 |
| P5 | OAuth host-only (helper, YouTube/TikTok authorize, callback YouTube loopback) | T7 | P2 |
| P6 | Health `ok/degraded`, `probe()` keyring, `/api/system/status`, direcciones | T13 | P2 |
| P7 | Frontend: login, 401, Settings (installation + password + sign out), host-only en paneles | Vitest dirigidos | P3, P5, P6 |
| P8 | Backup + restore + CLI restante (`configure`, `set-password`, `status`, `install/uninstall-service`) | T10, T11, T12, CLI | P1, P3 |
| P9 | Docs: `docs/deployment.md` (20 temas del usuario), README | — | todas |
| P10 | STOP gates (quickstart): servicio en sesión, LAN/móvil, OAuth condicional; bugs pequeños de móvil | manual | todas |
| Close | Tests pendientes, ruff/format/mypy, frontend lint/format/typecheck/build una vez, `git diff --check`, security review | — | — |

## Testing strategy

- **Dirigidos por bloque** (tabla anterior); parametrizados donde haya matrices (5 plataformas en T8; Host/Origin válidos/inválidos en T5; miembros tar maliciosos en T12).
- **Fixtures**: XDG apuntado a `tmp_path` (autouse) para config/logs y raíz de locks aislada sustituyendo el helper interno de la home de passwd; `create_app(deployment=DeploymentSettings.installation(cfg))` con `dist` mínimo en `tmp_path`; `TestClient(base_url="http://127.0.0.1:8000")` y `client=("192.168.1.50", 5000)` para simular LAN; credential store que lanza `CredentialStoreUnavailable`; `FakeClock` existente.
- **Sin tocar** los tests existentes salvo ajustes puntuales si el instance lock detecta dos apps simultáneas sobre la misma BD.
- **No** se ejecuta el pytest completo ni la suite frontend completa en local; CI del PR.
- **Close**: checks estáticos una vez, `git diff --check`, security review del diff.

## External validation (STOP gates)

Tardíos, tras P0–P9 en verde ([quickstart.md](quickstart.md)):

1. **STOP — servicio en la sesión del usuario** (host real): install-service, reboot + login, auto-start, keyring disponible en Settings, `SIGKILL` → reinicio, logs.
2. **STOP — LAN/móvil** (dispositivo real): login, navegación, previews (imagen y vídeo), Reschedule, Publish → Finish later, Text post, subida pequeña, Settings, Sign out, host-only, sin LAN no conecta.
3. **OAuth en el host** (condicional): solo si los tests con transports falsos no cubren el efecto de los guards sobre los callbacks.

No se publica contenido real.

## Security review del diseño

| Riesgo | Mitigación |
|---|---|
| Session fixation | Token nuevo en cada login; nunca desde URL. |
| Carrera login vs reset/cambio | Sesión insertada y hash cambiado de forma condicional al hash verificado, en una transacción (M2). |
| Esquema de la API público | `/docs`, `/redoc`, `/openapi.json` desactivados en instalación (M1). |
| Servicio y CLI sobre datos distintos | El servicio solo lee el TOML (y `AUTOPUBLISHER_CONFIG` escrito en la unidad); `install-service` rechaza overrides de entorno; `backup`/`restore`/`status` muestran la instalación efectiva (M3). |
| Diálogos del keyring | `probe()` nunca crea colecciones, desbloquea ni lee secretos (H2). |
| Sesiones en backups | La copia archivada se vacía y se hace `VACUUM`; restore vacía la tabla otra vez; la BD viva no se toca. |
| Diagnóstico engañoso del keyring | `available` solo tras comprobar desbloqueo sin prompt; si no se puede, `unknown`. |
| Robo de sesión por HTTP | **No mitigable sin HTTPS** (D14): documentado; `HttpOnly` impide robo por JS; expiraciones acotadas; Sign out y cambio de contraseña invalidan. |
| Hash débil | scrypt n=2^15, sal 16 B, re-hash al cambiar parámetros; comparación en tiempo constante. |
| Timing / enumeración | No hay usuarios; mensaje único; rate limit antes de verificar. |
| Fuerza bruta | 5/IP y 20 globales por 15 min; 12 caracteres mínimos. |
| CSRF / login CSRF | Origin obligatorio en métodos no seguros (incl. login); `SameSite=Lax`; GET sin efectos. |
| DNS rebinding / Host spoofing | Host estricto (loopback, IP del socket, `allowed_hosts`); sin `proxy_headers`. |
| Bypass de callbacks OAuth | Exentos solo de sesión; `state`+PKCE; loopback (TikTok existente, YouTube nuevo). Inicio de OAuth autenticado + host-only. |
| Setup/reset remoto | Solo CLI local; sin endpoint. |
| Media sin autenticar | `/api/contents/*/file` bajo guard de sesión (cookie same-origin en `<img>/<video>`). |
| Path traversal / symlinks (restore) | Validación de miembros (solo regulares, sin `..`, sin enlaces, prefijos permitidos, lista exacta del manifest), extracción manual a staging. |
| Tar bomb | Tamaños declarados en manifest, límites frente a espacio libre, tar sin comprimir. |
| Backup con secretos | Sin tokens del keyring; JSON de plataforma sí (documentado como sensible); fichero 0600, dir 0700. |
| Backup recursivo | Inclusión explícita + rechazo de `--output` dentro del directorio de datos. |
| Carreras backup/restore | Backup online verificado por checksum; backup y restore se excluyen por M; restore con M+A+B (servicio parado) durante todo el swap. |
| Doble scheduler | `flock` por directorio de datos (A) y por BD efectiva canónica (B), fuera del directorio de datos. |
| Permisos / tmp | UMask 0077 en el servicio; data/tmp/logs 0700; config 0600; spool en `<data_dir>/tmp`. |
| Logs con secretos | Access log off; filtros de redacción existentes; test de redacción; eventos de auth sin contraseña. |
| Dev expuesto | Modo desarrollo rechaza clientes no-loopback aunque se use `--host 0.0.0.0`. |
| Clickjacking | `X-Frame-Options: DENY`. |

## Riesgos

1. **Keyring con auto-login** (C1): el servicio arranca pero el llavero puede seguir bloqueado; mitigado con diagnóstico `locked` y guía explícita, no eliminado (fuera de 020: secret store headless).
2. **Puerto 8000 compartido** entre servicio y desarrollo en el mismo host: no pueden correr a la vez; durante el desarrollo hay que parar el servicio (documentado). Cambiar el puerto del servicio exige re-registrar redirect URIs.
3. **Datos de desarrollo y de instalación comparten keyring** (verificado: `credential_ref` es un `uuid4` por conexión copiado con la BD): si se usa el backend de desarrollo con la copia antigua y se desconecta/reconecta una cuenta, se borran entradas que la instalación usa. Retirar/archivar `backend/data` tras migrar es un paso **obligatorio** de la guía (y lo recuerda el restore); no se introduce namespace de keyring.
4. **Locks en tests**: la raíz de locks se aísla sustituyendo el helper interno de la home de passwd (fixture a `tmp_path`); algún test podría abrir dos apps sobre la misma BD a la vez → ajuste puntual.
5. **`graphical-session.target`** depende del entorno de escritorio; en GNOME/Ubuntu funciona (verificado activo); otros entornos pueden necesitar `default.target` (documentado; validado en STOP gate 1).
6. **Sondeo del keyring** usa `secretstorage.Collection(bus)` + `is_locked()` (nunca `get_default_collection`, `create_collection` ni `unlock`); con `libsecret`/KWallet u otros backends, o si el alias no existe, se informa `unknown`, nunca `available`.
7. **iOS Safari** con vídeo por Range y cookies sobre HTTP: Range ya cubierto por test (T015); el STOP gate 2 valida el navegador real.
8. **BDs anteriores a 020**: backup y restore deben funcionar sin `auth_sessions` (H1; regresión en T026/T027).

## Decisiones de diseño cerradas (revisión 2026-10-20)

- **C1 (aprobada)**: el login automático de GNOME no desbloquea el keyring; spec D13/FR-010a corregidos; la guía desaconseja un llavero sin contraseña; diagnóstico `locked`.
- **C2 (confirmada)**: datos y acciones privados requieren sesión; exenciones cerradas en [contracts/api.md §1](contracts/api.md); Media siempre autenticada; deep links → shell → login → vuelta a la URL.
- **C3 (confirmada)**: `AUTOPUBLISHER_*` individual > `AUTOPUBLISHER_DATA_DIR` > TOML del host > default.
- **C4 (confirmada)**: desarrollo sin contraseña solo para clientes loopback; sin bypass LAN; LAN/móvil se prueba en modo instalación (spec FR-004/FR-030h).
- **H1**: locks estables fuera del directorio de datos (research §9).
- **H2**: sesiones activas no portables; contraseña sí (research §11, §20, §22).

No quedan contradicciones abiertas entre spec y plan.

## Complexity Tracking

Sin violaciones de la Constitution.
