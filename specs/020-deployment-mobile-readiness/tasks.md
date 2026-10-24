---

description: "Task list for Feature 020 — Deployment & Mobile Readiness"
---

# Tasks: Deployment & Mobile Readiness

**Input**: Design documents from `/specs/020-deployment-mobile-readiness/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [contracts/cli.md](contracts/cli.md),
[quickstart.md](quickstart.md)

**Tests**: requested by the spec and plan ("Testing strategy"). Use a **targeted,
representative and parametrized** set. During implementation run only the tests of the
modified block (`cd backend && uv run pytest <files> -q` / `cd frontend && npx vitest run
<paths>`). A test that already passed is not re-run unless its code changed. When shared
code changes, run only the extra regressions named in the task. Do **not** run the full
pytest or Vitest suite locally: full suites run only in PR CI. Static checks run once, in
Phase 13.

**Organization**: blocks follow real dependencies. Each block goes contract → implementation
→ targeted tests → Done, and leaves the repo in a coherent state. Stories (spec.md):
- US1 Run as a real application (P1)
- US2 Persistent service (P1)
- US3 Safe restart and reliable scheduler (P1)
- US4 LAN access and real mobile use (P2)
- US5 Installation password and LAN security (P2)
- US6 Portable configuration and data (P2)
- US7 Backup and restore (P2)
- US8 Operation and diagnostics (P3)
- US9 Update an installation (P3)

Foundational blocks (config, data layout, locks, modes, guards) carry no story label because
every story depends on them.

**Task format**: `- [ ] ID [P?] [Story?] Description (files)`, followed by the sub-bullets
**Deps** (blocking tasks), **Tests** (targeted) and **Done** (acceptance criterion).

**Notation**: `autopublisher <cmd>` abbreviates `uv run python -m app.cli <cmd>` run from
`backend/` (the backend is not packaged; contracts/cli.md).

**Feature boundary** (checked again in T040):
- No HTTPS, PWA, Service Worker, push, Tailscale/VPN implementation, headless secret store,
  Docker, reverse proxy, Redis, PostgreSQL, cloud or SaaS concepts.
- No users/roles/JWT; no dev-mode LAN bypass; no `--disable-auth`-style setting.
- The scheduler and the publishers are not redesigned (T001 only adds a regression, with a
  minimal fix only if it fails).
- No redesign of Library, Publish, Posts or Calendar.

**Checkpoints** (stable batches for `/speckit-implement`):
- **A** after T006: baseline + config + data layout + locks.
- **B** after T014: app modes + guards + auth backend + `set-password`.
- **C** after T021: SPA/serve + OAuth host-only + health/diagnostics.
- **D** after T025: frontend auth, Settings and host-only messaging.
- **E** after T030: backup/restore, CLI, logging and service.
- **F** T031–T041: docs, STOP gates, close.

---

## Phase 1: Baseline — scheduler with the keyring unavailable

**Purpose**: prove the spec premise before touching deployment (research §1).

- [X] T001 [US3] Add the regression `backend/tests/test_scheduler_keyring_unavailable.py` for the **shared** path (research §1). The behaviour lives in common code: `publishing.start_publication` calls `publisher.prepare()` before the claim; `Scheduler._start` catches `AppError` (→ its code) and any other exception (→ `internal_error`); `automation.record_auto_publish_error` keeps the Post `scheduled`; `automation.is_overdue` turns it into Missed. Two cases, no platform matrix:
  1. **Real integration**: YouTube, whose `list_channels` maps `CredentialStoreUnavailable` to `AppError(503, "credential_store_unavailable")`, using the existing fixtures/fakes.
  2. **Unwrapped exception**: a `FakePublisher` whose `prepare()` raises `CredentialStoreUnavailable` directly.
  - **Check, for both**:
    - Inside the window: the Post stays `scheduled`, shows a visible failure (`auto_publish_error_code`/message set), and no attempt is created.
    - After the 10-minute window (`FakeClock`): `auto_publish_state == "overdue"` (Missed).
    - Further ticks never start it (never published late).
  - **If a case fails**: first locate the real shared point (orchestration in `publishing.start_publication`, `Scheduler._start`, error recording, or another common path) and apply the **minimum** change there. Do not patch each platform's `prepare()`, and do not redesign the scheduler.
  - **Deps**: —
  - **Tests**: the new file; direct-risk regression only if shared code changes: `backend/tests/test_scheduler_preflight.py`.
  - **Done**: both cases pass; any change is minimal and in the shared path.

---

## Phase 2: Foundational — host config, data layout and locks

**Purpose**: one source of truth for paths and exclusion; used by every later block.

- [X] T002 Add data-directory resolution to `backend/app/config.py` (research §5, C3):
  - New `AUTOPUBLISHER_DATA_DIR`.
  - A resolver that each existing `get_*` uses with the exact precedence: (1) specific `AUTOPUBLISHER_*` → (2) `AUTOPUBLISHER_DATA_DIR` + default file name → (3) installation `data_dir` injected by the deployment layer → (4) default (`backend/data` in development).
  - Keep the public signatures used by current callers.
  - Do not move or copy any existing data.
  - **Deps**: —
  - **Tests**: `backend/tests/test_deployment_config.py`, parametrized over DB, media, the six platform JSON files and media delivery, for each precedence level. Also covers: old env vars still win; with nothing set, paths are identical to today.
  - **Done**: precedence matches contracts/cli.md for every path, and the dev defaults are unchanged.
- [X] T003 Create `HostConfig` in `backend/app/deployment.py` (research §5, data-model "Configuración del host"):
  - **Location**: `AUTOPUBLISHER_CONFIG`, or `$XDG_CONFIG_HOME/autopublisher/config.toml`.
  - **Reading**: `tomllib`.
  - **Keys**: `data_dir` (absolute; default `$XDG_DATA_HOME/autopublisher`), `port` (1024–65535, default 8000), `lan_enabled` (default false), `allowed_hosts` (lowercase names without scheme or port), `frontend_dist` (absolute, optional).
  - **No `mode` key.**
  - **Errors**: unknown keys, invalid types/values or a missing file raise a `HostConfigError` with a human message naming the key and, for a missing file, the real command (`uv run python -m app.cli configure …` from `backend/`) (exit code 78 later).
  - **Writer**: a template-text writer for `configure` (file 0600, directory 0700).
  - **Deps**: —
  - **Tests**: `backend/tests/test_deployment_config.py`: valid file, each invalid key, unknown key, missing file, defaults, writer permissions and round trip.
  - **Done**: every key in the contract is validated and the written file contains no secrets.
- [X] T004 Add the portable/host/runtime classification (FR-042, FR-042a, FR-047) to `backend/app/deployment.py` as one `DataLayout` (from the resolved paths) plus host paths:
  - **Portable**: DB, `media/projects`, the six platform JSON names (`PORTABLE_PLATFORM_FILES`, shared with backup/restore).
  - **Runtime**: `<data_dir>/tmp`, `media/tmp`.
  - **Host**: config path, `$XDG_STATE_HOME/autopublisher/logs` (locks: see T005), default backups dir `~/autopublisher-backups`.
  - **Helper**: `is_inside(path, data_dir)` using canonical paths.
  - `ensure_dirs()` creates **new** data/tmp/state directories as 0700.
  - **`permission_warnings()`** (FR-044): reports an **existing** data dir or platform JSON file that is accessible by group/others (warning text + how to fix with `chmod`). It never changes permissions automatically, so legacy `backend/data` keeps working.
  - **Deps**: T002, T003
  - **Tests**: same file. Host and runtime paths are never inside the portable set; logs and locks are outside the data dir; symlinked paths are canonicalized; directories are created 0700.
  - **Done**: serve, backup, restore and status can depend on a single layout object.
- [X] T005 Create the stable locks in `backend/app/instance_lock.py` (research §9, H1):
  - Locks M (`maint-`), A (`data-`) and B (`db-`) in a single root `<passwd home>/.local/state/autopublisher/locks/` (0700), with the home taken only from `pwd.getpwuid(os.geteuid()).pw_dir`; the root never depends on environment variables (`HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR`, `TMPDIR`, `AUTOPUBLISHER_*`), is not configurable, and an unusable or unsafe root fails with `LockRootUnsafe` (no fallback).
  - Each lock is named after the first 16 hex characters of the SHA-256 of the canonical path (`Path.resolve()`).
  - Uses `fcntl.flock(LOCK_EX | LOCK_NB)` — **never** `fcntl.lockf`/POSIX record locks, which do not conflict between two opens inside one process (the in-process tests must prove real exclusion).
  - **Observation for `status`** (L3): `observe(kind)` reads the lock metadata as a hint and, at most, tries one `LOCK_NB` and releases at once; it never waits.
  - A context manager acquires a requested subset **only in the order M → A → B**, releases in reverse order, and on partial failure releases what it took.
  - It writes PID/command/path as information.
  - It raises `LockBusy`, carrying a human message ("…already running with the data directory … (process N). Stop it first: `systemctl --user stop autopublisher`.") and exit code 75.
  - Optional short retry (5 s, every 0.5 s) for the server, to absorb the `--reload` handover.
  - No PID-based staleness logic.
  - **Deps**: T004
  - **Tests**: `backend/tests/test_instance_lock.py`:
    - Same data dir conflicts (two locks taken **in the same process** must conflict).
    - Different data dirs with the same DB via override conflict on B.
    - Out-of-order requests are rejected by the API.
    - A child process killed with SIGKILL releases its lock.
    - The message names the path and PID.
    - Lock files live outside the data dir.
  - **Done**: H1 is satisfied at the library level.
- [X] T006 Wire locks A+B into the lifespan of `backend/app/main.py`, acquired before `run_migrations` and released in `finally`. Add an autouse fixture in `backend/tests/conftest.py` that points `XDG_STATE_HOME`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` to `tmp_path`, and isolates the lock root by replacing only the internal passwd-home helper (never through the environment).
  - **Deps**: T005
  - **Tests**: `backend/tests/test_instance_lock.py`: two `TestClient` apps on the same DB, so the second fails at startup with the readable error; sequential apps work. Direct-risk regressions: `backend/tests/test_scheduler_lifecycle.py`, `backend/tests/test_persistence.py`. If an existing test opens two apps on one DB at the same time, adjust only that test.
  - **Done**: two servers can never share a data dir or an effective DB. **Checkpoint A.**

---

## Phase 3: Foundational — application modes and guards

- [X] T007 Add `DeploymentSettings` to `backend/app/deployment.py`, and make `create_app(..., deployment=None)` accept it in `backend/app/main.py` (research §4, C4):
  - **Factories**: `DeploymentSettings.development()` and `DeploymentSettings.installation(host_config, layout)` (frozen: mode, port, lan_enabled, allowed_hosts, layout, frontend_dist).
  - **Module app**: the module-level `app = create_app(deployment=DeploymentSettings.development())`.
  - **`deployment=None`** keeps today's exact behaviour (used by existing tests).
  - **No bypass**: there is no setting or env var that switches modes or disables auth; installation mode can only be built from a `HostConfig`.
  - **Deps**: T004
  - **Tests**: `backend/tests/test_deployment_modes.py`: the module `app` is development; `create_app()` has no guards; installation requires a `HostConfig`.
  - **Done**: the rule "the entrypoint decides the mode" is enforced in code.
- [X] T008 Create the guards in `backend/app/guards.py` and the shared helper `backend/app/loopback.py` (`is_loopback_request`: client **and** socket loopback). Refactor `tiktok_connections._is_loopback` to use the helper without changing its behaviour. Implement as pure ASGI middlewares, registered per mode in the contract order (contracts/api.md §1):
  - **Loopback-only** (development): non-loopback client → `403 loopback_only`, even when bound to `0.0.0.0`.
  - **Host** (research §14): loopback names; IP literal equal to `scope["server"][0]`; `allowed_hosts`; the port must match in installation and may be any port in development; otherwise `403 host_not_allowed`.
  - **Origin** for POST/PUT/PATCH/DELETE (research §13):
    - `Origin` must equal `http://<validated Host>`.
    - Without `Origin`, the request is accepted only with `Sec-Fetch-Site: same-origin`.
    - Missing, malformed or `null` → `403 origin_not_allowed`.
  - **Security headers** (installation): `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`.
  - **Deps**: T007
  - **Tests**: `backend/tests/test_guards.py`, parametrized (use `TestClient(base_url=…, client=(host, port))`):
    - Dev with a LAN client → 403; dev with Vite-style `Host: localhost:5173` and a matching `Origin` → OK.
    - Host cases: `localhost`, `127.0.0.1`, `[::1]`, LAN socket IP, `allowed_hosts`, `Host` with port, wrong port, `evil.example`, a rebinding-style name, a LAN-IP `Host` with LAN off.
    - Origin cases: same, foreign, missing with `Sec-Fetch-Site`, missing entirely, malformed, `null`.
    - GET/HEAD are never origin-checked.
    - Headers are present only in installation.
    - Direct-risk regression: the TikTok callback tests (`backend/tests/test_tiktok_*connect*.py`).
  - **Done**: every guard rejection uses the contract code, and the loopback helper is shared.

---

## Phase 4: User Story 5 — authentication backend (Priority: P2)

**Goal**: installation mode requires the single password; sessions follow H2 and the lifetime rules.

**Independent Test**: with `deployment=installation`, unauthenticated API calls are rejected, login works, and sessions expire and are invalidated as specified (quickstart T2–T4).

- [X] T009 [US5] Add the `InstallationAuth` and `AuthSession` models to `backend/app/models.py` (data-model.md: singleton `CHECK (id = 1)`, `token_hash` PK, UTC columns) and the Alembic revision `backend/migrations/versions/<rev>_installation_auth.py`.
  - **Deps**: —
  - **Tests**: `backend/tests/test_migrations.py` (the existing drift test, targeted).
  - **Done**: upgrade creates both tables and models and migrations do not drift.
- [X] T010 [US5] Implement password hashing and storage in `backend/app/auth.py` (research §10):
  - `hashlib.scrypt` with n=2^15, r=8, p=1, `maxmem` 64 MiB, a 16-byte salt and a 32-byte key.
  - Self-describing format `scrypt$n$r$p$salt$hash`; `verify` with `hmac.compare_digest`; `needs_rehash`.
  - Length 12–1024.
  - `set_password(session, password, clock)`: upserts the row and deletes **all** `auth_sessions` in the same transaction.
  - **Deps**: T009
  - **Tests**: `backend/tests/test_auth_password.py`: round trip, wrong password, format parsing, rehash when the parameters differ, length bounds, set deletes sessions.
  - **Done**: no reversible password is ever stored.
- [X] T011 [US5] Implement sessions in `backend/app/auth.py` (research §11):
  - **Token**: `secrets.token_urlsafe(32)`; only its `sha256` is stored.
  - **Validity**: `now < min(last_seen_at + 7 d, expires_at)` with `expires_at = created_at + 30 d`.
  - **Renewal**: `touch` updates `last_seen_at` at most every 10 min and never extends `expires_at`.
  - **Lifecycle**: delete one / delete all; purge expired rows; cap of 20 valid sessions (oldest `last_seen_at` deleted first).
  - **Cookie builder**: `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Domain`, no `Secure`, `Max-Age` = seconds until `expires_at`.
  - **Deps**: T009
  - **Tests**: `backend/tests/test_auth_sessions.py` with `FakeClock`:
    - Idle expiry at 7 d; activity renews only the idle deadline; the absolute limit at 30 d is never extended.
    - Purge and the cap of 20.
    - The DB contains no raw token.
    - Sessions survive a new `create_app` on the same DB.
    - Cookie attributes.
  - **Done**: the session lifetime is unambiguous and tested.
- [X] T012 [P] [US5] Implement the in-memory login rate limiter in `backend/app/auth.py` (research §12): 15-minute sliding window, 5 failures per client IP and 20 global, at most 256 tracked IPs (oldest evicted), success clears that IP, it reports "blocked" before any password check, never blocks permanently.
  - **Deps**: —
  - **Tests**: `backend/tests/test_auth_rate_limit.py`: the 6th failure from one IP is blocked; the global limit blocks across IPs; the window expires; the map stays bounded.
  - **Done**: there is no unbounded growth and no permanent lockout.
- [X] T013 [US5] Add the `/api/auth` router to `backend/app/auth.py` and the session guard to `backend/app/guards.py` (contracts/api.md §1, §3):
  - **`GET /api/auth/session`**: returns the contract shapes per mode.
  - **`POST /api/auth/login`**: rate limit → read the current hash → verify (scrypt) → in **one transaction**, re-read `installation_auth.password_hash` and insert the session **only if it still equals the verified hash**; otherwise `401 invalid_credentials` and no session (M2). `401 invalid_credentials` / `429 too_many_attempts`; `409 auth_not_enabled` in development.
  - **`POST /api/auth/logout`**: idempotent; deletes the session and clears the cookie.
  - **`POST /api/auth/password`**: requires a session; verifies the current password (rate-limited) and validates the new one (`422`). In **one transaction**: `UPDATE … SET password_hash = new WHERE password_hash = verified` (no row → `401 invalid_credentials`, nothing changed), delete all sessions, and issue a new one for the caller.
  - **Reset** (`set-password`, T014) uses the same transaction shape (upsert hash + delete all sessions), so a login that verified the old hash cannot persist a session afterwards.
  - **Session guard**: an **explicit, exported allowlist constant** `PUBLIC_API_ROUTES` (method + path template, exactly the contract table); non-`/api/` paths are public; any other `/api/*` needs a valid session. Otherwise `401 auth_required`, and the invalid cookie is cleared.
  - **Startup**: purge expired sessions.
  - **Logging**: log auth events (login ok/failure/blocked with client IP, logout, password change) **without** passwords or tokens.
  - **Deps**: T008, T010, T011, T012
  - **Tests**: `backend/tests/test_auth_api.py`:
    - **Contractual allowlist** (L8): `PUBLIC_API_ROUTES` equals the contract's table, and every route in it exists in `app.routes`.
    - **No route accidentally public**: iterate over `app.routes`, fill path params with `1`, and send a **valid `Origin`** on unsafe methods so the request reaches the session guard. Every `/api` route outside the allowlist returns `401 auth_required` without a cookie. A new `/api` route therefore fails this test unless it is added to the allowlist and the contract.
    - Media `GET /api/contents/1/file` → 401 without a session and 200 with one.
    - Login ok/wrong/429.
    - Login CSRF: a foreign `Origin` → 403.
    - Logout is immediate.
    - **Races (M2)**, with a barrier/hook between the scrypt verification and the persistence step: login vs reset → no session is created; login vs change → no session is created; two concurrent changes with the same current password → only one succeeds.
    - A password change invalidates the other client but keeps the caller.
    - Dev-mode shapes.
  - **Done**: all private data and actions require a session, with a verifiable allowlist (C2).
- [X] T014 [US5] Create the CLI skeleton `backend/app/cli.py` (`argparse`; `python -m app.cli`; exit codes 0/1/2/75/78) and the `set-password` command (contracts/cli.md):
  - Resolves the layout (host config if present, else the development defaults through the same resolver).
  - Takes lock **M**.
  - **Migrations (L4)**: if lock A is free, apply them as needed. If A is held (a server is running) and the schema is not at head → refuse with "Restart AutoPublisher first." (exit 75) without touching the schema. If A is held and the schema is at head → proceed.
  - `getpass` twice; validates the length.
  - Calls `set_password` (deletes all sessions).
  - Messages never echo the password and only show real commands (M6).
  - **Deps**: T005, T010
  - **Tests**: `backend/tests/test_cli.py` (with `getpass` monkeypatched): first setup on a fresh DB and on a **pre-020 DB** (migrated to head); reset deletes the sessions; mismatch or too short → exit 2 and nothing written; M busy → exit 75; A held + schema behind head → exit 75 and the schema unchanged.
  - **Done**: first-time setup and forgotten-password reset are local host actions only (FR-030a, FR-030e). **Checkpoint B.**

---

## Phase 5: User Story 1 — run as a real application (Priority: P1)

**Goal**: one address + one port serves the compiled UI and the API, started by `serve`.

**Independent Test**: quickstart T1; `serve` preconditions fail with clear messages.

- [X] T015 [US1] Add SPA serving in `backend/app/spa.py`, registered only in installation (research §2, contracts/api.md §6):
  - **Assets**: mount `/assets` from `frontend_dist` with `Cache-Control: public, max-age=31536000, immutable`.
  - **Catch-all**: a `GET|HEAD` catch-all registered last. `api`, `api/*` and `health` return the JSON `404 not_found`. A regular file inside `dist` (canonical check) is served. Anything else returns `index.html` with `Cache-Control: no-cache`.
  - **FastAPI docs off in installation (M1)**: `create_app` passes `docs_url=None`, `redoc_url=None`, `openapi_url=None` when the mode is installation; development keeps them.
  - **Development is unchanged**: no SPA.
  - **Deps**: T007, T013
  - **Tests**: `backend/tests/test_spa.py` with a minimal `dist` in `tmp_path`:
    - A deep link with a query string → index.
    - An asset → file with its cache header; a missing asset → 404.
    - `/api` and `/api/nope` → JSON 404 (never the SPA).
    - POST to a non-API path → JSON 404/405.
    - An encoded traversal stays inside `dist`.
    - The SPA shell is served without a session while `/api/contents/1/file` still requires one.
    - Development mode serves no SPA.
    - **Docs off (M1)**: in installation, `/docs`, `/redoc` and `/openapi.json` return 404 and never `index.html`; in development they still exist.
    - **Range (L7)**: with a session, `GET /api/contents/<video>/file` with `Range: bytes=0-1` → `206`, `Content-Range: bytes 0-1/<size>`, `Accept-Ranges: bytes`, 2-byte body; without a session → 401.
  - **Done**: deep links work, the API is never swallowed, there is no public API schema, and authenticated media supports Range.
- [X] T016 [US1] Implement `serve` in `backend/app/cli.py` (research §3, §7, contracts/cli.md):
  - **Preconditions**, each failing with exit 78 and a message:
    - Load `HostConfig`.
    - `ensure_dirs()`.
    - `frontend_dist/index.html` exists ("run `npm ci && npm run build` in frontend/ or copy a build there; see docs/deployment.md").
    - A password is configured ("Set it with `uv run python -m app.cli set-password` from backend/; see docs/deployment.md").
  - **Permissions (FR-044)**: log every `permission_warnings()` entry (T004) at startup; never fail because of them.
  - **Temporary files**: set `tempfile.tempdir` and `os.environ["TMPDIR"]` to `<data_dir>/tmp` (0700).
  - **App**: build `create_app(deployment=installation)`.
  - **uvicorn**: `uvicorn.run(host="127.0.0.1"` if LAN is off, else `"0.0.0.0"`, `port`, `proxy_headers=False`, `access_log=False`, `server_header=False`, `timeout_graceful_shutdown=20`, `log_config=None)`.
  - **Exit codes**: `LockBusy` → 75. A failing migration aborts startup without serving (non-zero exit, error logged).
  - **Deps**: T006, T014, T015
  - **Tests**: `backend/tests/test_cli_serve.py` (monkeypatch `uvicorn.run`, capturing its kwargs):
    - Each precondition's exit code and message.
    - Bind host per `lan_enabled`.
    - A migration failure → no serve.
    - **Upload spool**: after setup, `tempfile.gettempdir()` is `<data_dir>/tmp`, and a >1 MiB multipart import into the installation app creates its spooled file there (wrap `tempfile.TemporaryFile`/`SpooledTemporaryFile` rollover to record the directory).
  - **Done**: installation mode runs without Vite, `--reload` or Node at runtime (FR-001, FR-005, FR-043, FR-046, FR-081).

---

## Phase 6: User Story 4 — OAuth host-only (Priority: P2)

- [X] T017 [US4] Make YouTube and TikTok OAuth host-only (research §15–16, contracts/api.md §5):
  - **Authorize endpoints** (`backend/app/youtube_connections.py`, `backend/app/tiktok_connections.py`, and any endpoint that starts a reconnection of these platforms), installation mode: `409 host_only_action` with the loopback URL **before** creating an attempt, when `is_loopback_request` is false.
  - **YouTube callback**: now rejects non-loopback clients with the generic invalid page, without consuming `state`.
  - **Session exemption**: the three callback/result routes are in `PUBLIC_API_ROUTES`.
  - **No weakening**: TikTok's socket/port check and `state`/PKCE are unchanged.
  - **Deps**: T008, T013
  - **Tests**: `backend/tests/test_oauth_host_only.py`:
    - Authorize from a LAN client → 409 and no attempt; from loopback → 201.
    - YouTube callback from non-loopback rejected, and the `state` is still usable afterwards.
    - Callbacks are reachable without a session.
    - Direct-risk regressions: `backend/tests/test_youtube_connect.py` and the TikTok connect tests.
  - **Done**: OAuth start is authenticated and host-only; callbacks keep their protections.

---

## Phase 7: User Story 8 — health, diagnostics and addresses (Priority: P3)

- [X] T018 [P] [US8] Make public `/health` minimal in `backend/app/main.py` (or `backend/app/system_status.py`): `200 {"status":"ok"|"degraded"}`; `degraded` = `SELECT 1` fails **or** the scheduler thread is not alive with autostart; no other fields; no session (contracts/api.md §2, research §17).
  - **Deps**: T013
  - **Tests**: update `backend/tests/test_health.py`: exact key set; degraded when the scheduler is stopped and when the DB fails; reachable without a session in installation; no keyring probe is called.
  - **Done**: the public health is not an operational oracle.
- [X] T019 [P] [US8] Add `probe()` to `backend/app/credential_store.py` (research §18):
  - Results are `available` / `locked` / `unavailable` / `unknown`, cached for 60 s.
  - A non-allowed backend → `unavailable`.
  - With `SecretService` (H2): `secretstorage.dbus_init()` + `secretstorage.Collection(bus)` (the **existing** `default` alias, the one keyring uses) + `is_locked()` → `available` or `locked`. The alias does not exist (`ItemNotFoundException`) → `unknown`. A D-Bus error or no session bus → `unavailable`. **Forbidden in the probe**: `secretstorage.get_default_collection()` (it creates the collection, which prompts), `create_collection`, `unlock()`, `keyring.get_password`/`set_password`, and any item read.
  - Other allowed backends → `unknown`.
  - Declare `secretstorage` with the marker `sys_platform == 'linux'` in `backend/pyproject.toml` and refresh `uv.lock`.
  - **Deps**: —
  - **Tests**: `backend/tests/test_credential_probe.py` with monkeypatched `secretstorage`/backends:
    - Each of the four statuses.
    - **No-interaction regression**: replace `get_default_collection`, `create_collection`, `Collection.unlock`, `keyring.get_password` and item access with spies that fail if called; run the probe for "alias missing", "locked" and "unlocked"; none of the spies is called and no collection is created.
    - The cache; `unknown` is never reported as `available`.
  - **Done**: no false "available", no collection created, no unlock prompt.
- [X] T020 [US8] Add LAN address discovery to `backend/app/deployment.py` (research §23):
  - Find the primary address with a UDP `connect()` to `10.255.255.255:1` + `getsockname()` (no packets sent).
  - Add the request's socket address if it is not loopback.
  - Keep only private, non-loopback, non-link-local addresses; deduplicate.
  - Suggest `<hostname>.local`.
  - On failure → `[]`; no external service.
  - **Deps**: T004
  - **Tests**: `backend/tests/test_deployment_config.py`, monkeypatched `socket`: candidates, loopback excluded, failure → empty.
  - **Done**: useful candidates, or a graceful unknown.
- [X] T021 [US8] Add the authenticated `GET /api/system/status` in `backend/app/system_status.py` (contracts/api.md §4):
  - Fields: `mode`, `database.status`, `credential_store.status` (T019), and `deployment` (port, lan_enabled, `http://` addresses, suggested names, allowed_hosts; `null` in development).
  - No paths, versions or secrets.
  - Scheduler and pause stay in `/api/automation` (unchanged).
  - **Deps**: T013, T019, T020
  - **Tests**: `backend/tests/test_system_status.py`: 401 without a session; shape per mode; key set has no paths or versions; probe results are mapped.
  - **Done**: diagnostics are available only to the signed-in user. **Checkpoint C.**

---

## Phase 8: Frontend — sign-in, Settings and host-only messaging (US5, US8, US4)

- [X] T022 [US5] Add the frontend auth bootstrap (contracts/ui.md §1):
  - `frontend/src/api.ts`: `getAuthSession`, `login`, `logout`, `changePassword`, `getSystemStatus`; a global `401 auth_required` handler that navigates once to `/login?next=<current>`.
  - `frontend/src/shell/useAuthSession.ts`: a gate that renders **no app data or data requests** until the session is known, then redirects unauthenticated users to `/login?next=…`.
  - `frontend/src/routes.tsx`: `/login` outside the AppShell.
  - `next` sanitization: relative, starts with `/` and not with `//`; otherwise `/`.
  - Development mode: no login.
  - **Deps**: T013
  - **Tests**: `frontend/src/auth.test.tsx`:
    - An unauthenticated deep link → `/login?next=<deep link>`, with no data request issued first.
    - A 401 mid-session → login with `next`.
    - Hostile `next` values → `/`.
    - Development renders the app directly.
  - **Done**: no private data flashes before authentication.
- [X] T023 [US5] Create `frontend/src/pages/LoginPage.tsx` (contracts/ui.md §2):
  - Password field (`autocomplete="current-password"`, font ≥16 px, autofocus) and **Sign in**.
  - Inline `role="alert"` errors for invalid / too many attempts / network.
  - Hint for the CLI reset.
  - On success → `next`; already signed in → `/`.
  - **Deps**: T022
  - **Tests**: `frontend/src/pages/login.test.tsx`: success returns to the deep link; each error message; already authenticated.
  - **Done**: the login works with keyboard, screen readers and on phones.
- [X] T024 [US8] Add the Settings sections (contracts/ui.md §3) in `frontend/src/pages/SettingsPage.tsx`, the new `frontend/src/pages/settings/InstallationStatus.tsx`, and the new `frontend/src/pages/settings/ChangePasswordDialog.tsx` (reuse the existing dialog/sheet and `Field`). Shown only in installation mode:
  - **"This installation"** (read-only): health problems, including the exact messages for `locked` / `unavailable` / `unknown` (`unknown` is never "working").
  - **Access from other devices**: LAN off/on, addresses or "could not detect".
  - **HTTP warning**: always visible when LAN is on.
  - **Port**, and a note that host settings change via `configure` + restart.
  - **"Sign-in"**: **Change password** (current, new ≥12, confirm; field errors; success message about other devices) and **Sign out**.
  - No LAN or port toggles.
  - **Deps**: T021, T022
  - **Tests**: `frontend/src/pages/settings.test.tsx` (extend):
    - Each credential state's text.
    - The LAN section with addresses, with none, and with LAN off.
    - The warning text present when LAN is on.
    - Change password success and errors; Sign out → `/login`.
    - Development hides the sections.
  - **Done**: FR-034, FR-037 (UI part), FR-061 and FR-030c/e are visible to the user.
- [X] T025 [P] [US4] Add the host-only explanation to `frontend/src/components/YouTubeConnectionPanel.tsx` and `frontend/src/components/TikTokConnectionPanel.tsx` (contracts/ui.md §4):
  - When `window.location.hostname` is not loopback, replace Connect/Reconnect with the explanation and "On that computer, open http://127.0.0.1:<port><path>".
  - Show the same message when the backend returns `409 host_only_action`.
  - Instagram, Threads and Telegram are unchanged.
  - **Deps**: T017
  - **Tests**: `frontend/src/pages/accounts.test.tsx` (extend): LAN hostname → no doomed flow and the message is shown; loopback → the button; 409 → the message.
  - **Done**: remote clients never start a flow that would fail. **Checkpoint D.**

---

## Phase 9: User Story 7 — backup and restore (Priority: P2)

**Goal**: an online, consistent, verified backup without active sessions; a validated restore that keeps the target host config and the locks.

**Independent Test**: quickstart T11–T12 and Journey F.

- [X] T026 [US7] Implement the backup in `backend/app/backup.py`, following research §20–21 exactly:
  1. **Preconditions**: resolve the layout; reject specific overrides outside the data dir; reject an output inside (or containing) the data dir; take lock **M**; create the output dir 0700; delete stale `.partial` files and snapshots; check free space.
  2. **Snapshot**: `sqlite3.backup` into a temp file in the output dir. On **that copy only**: if the table `auth_sessions` exists, `DELETE FROM auth_sessions`; then `VACUUM`. A pre-020 DB (no `auth_sessions`, no `installation_auth`) is backed up as is; the source DB is never migrated or modified. `installation_auth` is kept when present.
  3. **Write the `.tar.partial`** (0600):
     - The DB copy.
     - Each referenced media file, streamed with SHA-256; abort if the file is missing, its size changed, or its hash ≠ the DB checksum.
     - Each present platform JSON, read once (≤64 KiB) and archived from the same bytes it was hashed from.
     - `manifest.json` last (format, version 1, `created_at`, `app_version`, `schema_revision`, components, files with size and sha256, informative `source.hostname`).
  4. **Finalize**: `fsync`; re-read verification; atomic `rename` to `autopublisher-backup-<ts>.tar`; `fsync` the directory.
  5. **Errors** (any error, ENOSPC, interrupt): delete the partial file and the snapshot, non-zero exit.
  - **Never included**: keyring tokens, host config, logs, tmp, `media/tmp`, orphan files, locks, previous backups, build or dependencies.
  - **Deps**: T004, T005, T009
  - **Tests**: `backend/tests/test_backup.py`:
    - **Pre-020 DB (H1)**: a DB at the last pre-020 Alembic revision (no `installation_auth`, no `auth_sessions`) is backed up successfully; the source DB is unchanged.
    - The exact member set.
    - The archived DB has an empty `auth_sessions` and the same `installation_auth`, while the live DB keeps its sessions.
    - Media altered during the backup (hook between snapshot and copy) → no `.tar`; a missing file → no `.tar`.
    - Injected write failure / ENOSPC → no `.tar` and no `.partial`.
    - Output inside the data dir rejected; stale partial cleaned.
    - The JSON bytes match their checksum.
    - The manifest fields.
    - In-memory credential store secrets do not appear in the tar bytes.
    - A concurrent import produces a valid artifact.
    - Concurrent backups → the second exits 75.
  - **Done**: a valid artifact can only exist if its bytes match the snapshot (FR-050, FR-050a/b, FR-051, FR-052).
- [X] T027 [US7] Implement the restore in `backend/app/backup.py`, following research §22 exactly:
  1. Resolve the layout (reject specific overrides) and print the effective target paths (M3). Resolve the target to its **canonical** path and operate only on it (a symlinked `data_dir` is followed; the swap happens at the resolved location). Reject a target that is itself a **mount point** ("use a subdirectory inside the mounted disk"). Take **M → A → B** for the whole operation; busy → 75 ("Stop AutoPublisher first").
  2. Read and validate the manifest.
  3. Validate **every** member before writing anything:
     - Only `isreg()` files and the expected directories; reject symlinks, hard links, devices, FIFOs, sparse/other non-regular types and **duplicate member names** (L5). PAX headers are accepted as metadata only and never widen the allowed path set (the effective member name is validated).
     - No absolute paths or `..`.
     - Only allowed prefixes, with an exact 1:1 match with the manifest.
     - Declared sizes, total size against free space, and a file-count limit.
  4. Check that `schema_revision` is known in `backend/migrations`.
  5. Extract into a sibling staging directory on the same filesystem (0700, `xb` writes, streaming SHA-256). Put the config JSON files at the staging root (0600). Run `PRAGMA integrity_check`, and `DELETE FROM auth_sessions` **only if the table exists** (H1).
  6. Confirm unless `--yes`.
  7. Swap: rename the target to `.before-restore-<ts>`, rename the staging into place, `fsync` the parent. Undo the first rename if the second fails. The locks stay held throughout.
  8. Release B → A → M and print the next steps with real commands (M6): start the service, set the password with `uv run python -m app.cli set-password` if the backup had none, reconnect accounts. When the source looks like a development `backend/data`, remind that retiring it is mandatory (M7).
  - The two renames are not one atomic transaction (L6): the message and docs describe the rare crash window and its manual recovery.
  - **Deps**: T026
  - **Tests**: `backend/tests/test_restore.py`:
    - **Pre-020 round trip (H1)**: back up a pre-020 DB (T026), restore it, then `set-password` migrates it to head and works; `configure → backup/restore → set-password` succeeds end to end.
    - Symlinked target → operates on the resolved path; mount-point target → rejected (mount check monkeypatched).
    - Duplicate member names → rejected.
    - **Round trip into a different directory**: data is equal; media is readable through the new path (FR-045); the same password verifies; zero sessions; `config.toml` is byte-identical; LAN is unchanged; the `.before-restore` copy is kept.
    - **Hostile and broken archives**, parametrized: `../`, absolute path, symlink, hard link, device, extra member, missing member, checksum mismatch, size mismatch, unknown `format_version`, unknown schema revision, corrupt tar, failing integrity check. Each leaves the target byte-identical and the staging removed.
    - Server holding A → 75.
    - From a hook between the renames, a new server cannot acquire A/B.
    - A second-rename failure → rolled back.
    - With an empty credential store, a restored YouTube account shows reconnect needed.
  - **Done**: validation happens before mutation, the lock is never lost, and sessions are gone while the password is kept (FR-053, FR-053a, SC-011).
- [X] T028 [US7] Finish the CLI commands `configure`, `status`, `backup` and `restore` in `backend/app/cli.py` (contracts/cli.md):
  - **`configure`**: **flags only** (L10; no interactive wizard); writes the TOML (T003); warns when the port ≠ 8000.
  - **Effective installation banner (M3)**: `status`, `backup` and `restore` first print the config file in use, the effective data dir and DB path, and list every `AUTOPUBLISHER_*` environment override detected ("this command is using environment overrides; the service does not see them").
  - **`status`**: the banner, port/LAN, whether a server seems to hold A/B (`observe()`, momentary, never waits — L3), `GET /health` on loopback, `probe()`, addresses, logs location, permission warnings (FR-044); no secrets.
  - **`backup`** / **`restore`**: wire to T026/T027 with the banner, summaries and exit codes.
  - **Deps**: T020, T026, T027
  - **Tests**: `backend/tests/test_cli.py` (extend): configure writes and validates from flags and never touches data; the banner lists the effective paths and detected overrides; status output has no secrets, reports the lock state without blocking a concurrent lock holder; backup and restore exit codes and messages; no output mentions a non-existent `autopublisher` executable.
  - **Done**: every command in contracts/cli.md exists and behaves as specified.

---

## Phase 10: User Story 2 — logging and the user service (Priority: P1)

- [X] T029 [US8] Configure logging in `serve` (`backend/app/cli.py`; research §19):
  - **Handlers**: a `RotatingFileHandler` at `$XDG_STATE_HOME/autopublisher/logs/autopublisher.log` (5 MiB × 5; directory 0700, files 0600) plus stderr (journal).
  - **Levels**: INFO for `app.*` and `uvicorn.error`; access log off.
  - **Startup line**: mode, port, LAN, effective paths and a warning when specific overrides are active. Also a shutdown line.
  - **Existing behaviour kept**: the redaction filters stay installed by `create_app`; the scheduler/publication lifecycle logs are kept.
  - **Deps**: T016
  - **Tests**: `backend/tests/test_logging.py`:
    - Handler configuration and permissions.
    - **Redaction run**: a wrong-password login, a correct login, a YouTube callback with `code`/`state`, a failed scheduled publication. The log file then contains no password, token, client secret or session cookie.
  - **Done**: logs persist across restarts, stay bounded and hold no secrets (FR-062, FR-033).
- [X] T030 [US2] Implement `install-service` and `uninstall-service` in `backend/app/cli.py` (research §8, contracts/cli.md):
  - **Paths (M4)**: resolve the backend directory from the code itself (`BACKEND_DIR`, absolute), never from the caller's cwd; resolve `<backend>/.venv/bin/python` as an absolute path and refuse if it does not exist ("run `uv sync --frozen --no-dev` in backend/ first"). `WorkingDirectory` is required because `python -m app.cli` imports `app` from it. The running service does not need `uv`.
  - **Environment (M3)**:
    - If the host config in use is not the default path, render `Environment=AUTOPUBLISHER_CONFIG=<absolute path>`.
    - If `AUTOPUBLISHER_DATA_DIR` or any path/data `AUTOPUBLISHER_*` override is set in the caller's environment, **refuse**: "These environment overrides are not persistent for the service: … Move them to the host configuration before installing the service." No shell variables are copied into the unit.
  - **Unit file**: renders `~/.config/systemd/user/autopublisher.service` exactly as specified:
    - `ExecStart=<abs backend>/.venv/bin/python -m app.cli serve`, `WorkingDirectory=<abs backend>`, `Environment=PYTHONUNBUFFERED=1`, `UMask=0077`.
    - `Restart=on-failure`, `RestartSec=5`, `StartLimitIntervalSec=300`, `StartLimitBurst=5`, `RestartPreventExitStatus=78`.
    - `KillSignal=SIGTERM`, `TimeoutStopSec=30`.
    - `PartOf/After/WantedBy=graphical-session.target`.
  - **Commands**: `daemon-reload` + `enable` (no `start`; `--no-enable` skips it); `uninstall-service` runs `disable --now`, removes the unit and runs `daemon-reload`.
  - **Refusals**: no config or no password → refuse.
  - **No linger**; no claim that the keyring is available.
  - `systemctl` is called through `subprocess`, mockable.
  - **Deps**: T016, T028
  - **Tests**: `backend/tests/test_cli_service.py`: rendered unit content (all directives above) with absolute paths independent of the cwd used to run the command; `AUTOPUBLISHER_CONFIG` rendered only when non-default; refusal with each kind of environment override; refusal when `.venv/bin/python` is missing; `systemctl` call sequence; the other refusals; no `loginctl` call.
  - **Done**: FR-010, FR-011, FR-013 are implementable on the host (validated in STOP 1). **Checkpoint E.**

---

## Phase 11: Documentation and update compatibility (US9, all stories)

- [X] T031 [US9] Write `docs/deployment.md` (English, public; FR-090–FR-092, FR-010a, FR-024, FR-025, FR-034, FR-036–FR-038, FR-047, FR-053, FR-054, FR-080–FR-082). Sections, in this order:
  - Prerequisites.
  - **Build vs runtime**: build the frontend here or elsewhere and copy `dist`; no Node at runtime.
  - Host config: TOML keys and the precedence C3.
  - Data directory layout and the portable/host/runtime classification; expected permissions and how to tighten an existing directory (FR-044); the data dir must not be a mount point itself (use a subdirectory).
  - Password: setup, reset, change.
  - Install the service; start/stop/restart/status/logs. The service only reads the host config file (plus `AUTOPUBLISHER_CONFIG` written into the unit when non-default); shell environment overrides are not visible to it (M3). If the checkout moves: re-create/sync `.venv` and run `install-service` again (M4); the running service does not need `uv`.
  - **Keyring and login**: auto-login does not unlock the GNOME keyring; locked keyring → diagnostics + Missed; do not use a passwordless keyring only for unattended startup; no linger; headless is future work.
  - Health and diagnostics.
  - Enable LAN, find the address (with `ip -4 addr` as a fallback).
  - **HTTP threat model** (what it does and does not protect; trusted private home network only).
  - Mobile access.
  - OAuth connect/reconnect from the host (`127.0.0.1`), and the port-8000 redirect URIs.
  - Scheduler requirements: running, awake, time sync, network, keyring; stopping during an upload.
  - Sleep and time sync (Raspberry Pi without an RTC).
  - Uploads and the tmp directory.
  - Backup: what it contains and excludes, and storing it safely.
  - Restore (service stopped; validation before any change); the rare crash window between the two renames and how to recognise and recover it manually (`<data_dir>` missing and `<data_dir>.before-restore-<ts>` present → rename it back) (L6).
  - Update: backup → stop → pull/`uv sync` → build/copy `dist` → start → health; failed migration → roll back with the backup.
  - Migrate from `backend/data`: `configure` → backup/restore → `set-password` (restore **before** setting the password). **Mandatory**: retire/archive the old `backend/data` afterwards and never run development against those Accounts again, because both copies reference the same keyring entries (M7).
  - Move to another computer (the 5 steps of FR-082) and reconnect accounts.
  - Development vs installation (port 8000 shared: stop the service while developing; dev is loopback-only).
  - ARM64 caveats.
  - Future private VPN/Tailscale (not implemented).
  - An explicit warning against exposing AutoPublisher directly to the Internet.
  - **Deps**: T030
  - **Tests**: none (documentation); every command shown is the real invocation (`uv run python -m app.cli <cmd>` from `backend/`, `systemctl --user …`), cross-checked against contracts/cli.md (M6).
  - **Done**: a non-developer can follow it end to end (SC-007).
- [X] T032 [P] [US9] Update `README.md`:
  - "Automatic publishing → AutoPublisher must be running": it can now be a user service.
  - A short "Running AutoPublisher as an installation" section linking `docs/deployment.md`.
  - The development section notes loopback-only, and that `AUTOPUBLISHER_DATA_DIR` exists.
  - The "Deploying the frontend later" note is replaced by the link.
  - **Deps**: T031
  - **Tests**: none.
  - **Done**: FR-093.

---

## Phase 12: External validation — STOP gates (late, on real devices)

- [X] T033 [US2] **STOP 1 — user-session service** on the real host (quickstart Journeys A, D, C, E):
  - `configure`, migrate the data if desired, `set-password`, `install-service`, `start`, then `status` and `/health`.
  - Reboot + **manual** login → available in <2 min.
  - Sign in at `http://127.0.0.1:8000`; Settings shows the credential state.
  - Optional: auto-login/locked keyring shows `locked` without a prompt being caused by Settings.
  - `systemctl --user kill -s SIGKILL autopublisher` → back to OK in <30 s.
  - The logs show the restart.
  - A scheduled Post survives a service restart; a Post whose window passes while logged out → Missed.
  - Do not assume auto-login unlocks the keyring.
  - **Deps**: T001–T032
  - **Done**: the user confirms each step; results are recorded in this task.
  - **Prepared (2026-10-23, not a validation)**: frontend built; `serve` smoke run with a throwaway installation (scratch config/data/state): `/health` ok, `/api/projects` 401 without session, deep link → `index.html`, `/docs` 404, `Host: evil.example` 403, wrong password 401, login 204, `/api/system/status` with keyring `available`, logout → 401, clean SIGTERM stop, no password in the log. The unit rendered for this checkout passes `systemd-analyze --user verify`; `graphical-session.target` active; clock synchronised; linger off. Not done yet: real host configuration, password, data migration decision, `install-service`, reboot/login, SIGKILL. **STOPPED** waiting for the user.
  - **Validated (2026-10-24, real host, by the user)**: real systemd user service installed and running; keyring `available`; normal restart OK; `SIGKILL` → automatic restart; reboot + login → the service started on its own; app reachable at `http://127.0.0.1:8000`. One defect found: a graceful SIGTERM stop logged uvicorn's "Finished server process" but not the T029 line "AutoPublisher stopped." — fixed in T037 (see Notes).
- [X] T034 [US4] **STOP 2 — LAN/mobile** with a real second device (quickstart B):
  - LAN off → unreachable. `configure --lan` + restart → `status` shows the address.
  - On the phone:
    - Login, a deep link (after login it returns to it).
    - Home, Posts, Calendar, Post detail with image and video previews.
    - Reschedule; Publish → Review → **Finish later**; Text post → Finish later.
    - A small image upload; Settings (installation section + HTTP warning); Sign out.
    - Connect YouTube shows the host-only explanation.
  - Another device without login sees no data.
  - No real publication is required.
  - **Deps**: T033
  - **Done**: the user confirms each step; any defect is listed in T035.
  - **Validated (2026-10-24, real phone over the LAN, by the user)**: login; Posts → detail → back; Calendar; image and video previews; Reschedule; Publish → Review → Finish later; Text post → Finish later; small image upload; Settings with the HTTP warning; sign out; a private deep link without a session → login; YouTube/TikTok host-only notice. The host's UFW denied incoming connections by default, so LAN access needed a manual rule allowing port 8000/tcp from the LAN subnet (documented in `docs/deployment.md` → Host firewall). No mobile defect found.
- [X] T035 [US4] Fix only **small** deployment/mobile defects found in T034 (FR-073; e.g. a Range/cookie/viewport issue), each with a targeted regression test in the affected file. Anything that needs a redesign of Library, Publish, Posts or Calendar is recorded as future work under "Notes" in this file instead.
  - **Deps**: T034
  - **Tests**: per fix.
  - **Done**: the T034 steps pass, or the remaining items are recorded as future work.
  - **Result (2026-10-24)**: N/A — T034 found no mobile/deployment defect; no code change.
- [X] T036 [US4] **STOP 3 — OAuth on the host (conditional)**:
  - Run it only if the T017/T008 tests with fake transports do not cover the effect of the guards on the real callbacks.
  - If run: at `http://127.0.0.1:8000`, **Reconnect** YouTube or TikTok completes.
  - Otherwise mark it "not needed" with the reason.
  - **Deps**: T033
  - **Done**: OAuth on the host is proven, or the gate is explicitly waived.
  - **Assessment (2026-10-23)**: `tests/test_oauth_host_only.py` already covers, in installation mode with fake transports, the effect of the guards on the real callback routes: host-only `authorize` (409 from a phone and from the host through its LAN IP, no attempt created), public YouTube/TikTok callbacks without a session, a LAN callback rejected without consuming the `state`, and the `127.0.0.1:8000` Host. The success path after the guards is the same code tested in development. Proposed: waive the guard-related gate; the only uncovered real-world effect is writing tokens to the keyring from the systemd service context (not a guard effect), offered as an optional Reconnect during T033. Pending the user's decision with T033 (Deps).
  - **Result (2026-10-24)**: waived (not needed) by the user. The installation-mode OAuth tests cover the Feature 020 changes (host-only start, public callbacks, loopback/socket checks, `state` preserved on a rejected callback), and T034 confirmed the host-only UX on a real phone. No real account was reconnected for this gate.

---

## Phase 13: Close

- [X] T037 Cleanup and copy review:
  - Remove orphans and dead code (e.g. a now-unused `_is_loopback`).
  - Review the user-visible and docs copy: FR-038 (no "secure"/"encrypted" claim for LAN without the caveat); C1 (no promise that auto-login unlocks the keyring); `unknown` is never shown as available; **M6**: no UI text, error, CLI output or operational doc shows the non-existent `autopublisher` executable (use `uv run python -m app.cli <cmd>` from `backend/`, the absolute `.venv/bin/python` for the unit, or a pointer to `docs/deployment.md`).
  - Check `.gitignore` covers nothing new inside the repo (locks, logs, config and backups live outside it).
  - **Deps**: T035, T036
  - **Done**: there is no dead code and no misleading copy.
  - **Result (2026-10-24)**: no orphan found (`_is_loopback` already gone; ruff clean). Copy reviewed: the HTTP warning never claims encryption; auto-login is documented as not unlocking the keyring; `unknown` is shown as a problem, never as working; no UI/CLI/doc text uses a non-existent `autopublisher` executable. `.gitignore` needs nothing new (config, logs, locks and backups live outside the repo; `frontend/dist` is ignored). Fixed the SIGTERM stop log (see Notes) with `tests/test_logging.py::test_serve_logs_stop_once_on_sigterm`.
- [X] T038 Docs review: `docs/deployment.md` and `README.md` against the final behaviour and the CLI help output; check the links.
  - **Deps**: T037
  - **Done**: the docs match the implementation.
  - **Result (2026-10-24)**: `docs/deployment.md` → LAN section now states the address is `http://` (not `https://`) and adds a **Host firewall** subsection (Ubuntu/UFW example restricted to the trusted LAN subnet, no `ufw allow 8000`, AutoPublisher never changes firewall rules). README unchanged (it only points to the deployment guide).
- [X] T039 Final targeted tests and global static checks, **once**:
  - Run any targeted tests still pending.
  - Backend: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`.
  - Frontend: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`.
  - `git diff --check`.
  - **No** full local pytest or Vitest suites (they run in PR CI).
  - **Deps**: T038
  - **Done**: all green.
  - **Result (2026-10-24)**: backend `ruff check`, `ruff format --check`, `mypy` (256 files) green; frontend `oxlint --deny-warnings`, `prettier --check`, `tsc -b`, `npm run build` green; `git diff --check` clean. Targeted tests: `tests/test_logging.py -k serve_logs` (2 passed). No full suites (PR CI).
- [X] T040 Security/privacy review of the diff (`/security-review`). Covers:
  - Session fixation; theft over HTTP (documented); hash parameters; timing/enumeration; CSRF and login CSRF.
  - Host spoofing and DNS rebinding; OAuth callback bypass; unauthenticated media.
  - Path traversal, symlinks and tar bombs in restore; secrets in backups and logs.
  - Permissions (0700/0600, `UMask`); tmp location.
  - Races: backup/restore, second scheduler, restore swap vs locks.
  - Also confirm that nothing from the feature boundary entered (no Feature 021+ scope).
  - **Deps**: T039
  - **Done**: no open finding, or each one is fixed with a targeted test (re-run only that test plus the relevant static check).
  - **Result (2026-10-24)**: no open finding. Reviewed: exact public route allowlist (every other `/api` route needs a session, `HEAD` follows `GET`); SPA catch-all returns JSON 404 for backend roots and refuses paths outside `dist`; Host check (loopback names, `allowed_hosts`, or the socket's own IP literal with LAN on; port must match) against DNS rebinding; Origin / `Sec-Fetch-Site` on every unsafe method (login CSRF included); session tokens stored as SHA-256, new token per login (no fixation), HttpOnly + SameSite=Lax, no `Secure` by design over HTTP (documented); scrypt hashes with `compare_digest`; login/change/reset races closed by conditional `INSERT … SELECT`/`UPDATE`; bounded in-memory rate limit; media only under `/api` (session); OAuth starts host-only, callbacks public but `state` + PKCE; restore validates every tar member against a strict allowlist (regular files only: no symlinks, hardlinks or devices), manifest/size/SHA-256 checked, exclusive writes inside a 0700 staging dir; backups 0600, include app client secrets (documented as private) but no keyring tokens or sessions; log redaction filter; the unit only sets `PYTHONUNBUFFERED` and `AUTOPUBLISHER_CONFIG`, `UMask=0077`. Feature boundary respected (no HTTPS/PWA/users/roles/remote access).
- [X] T041 Requirements coverage check: walk the table below against the implementation and tests; confirm every FR/SC is covered or explicitly validated in a STOP gate; update `checklists/requirements.md` notes if needed.
  - **Deps**: T040
  - **Done**: coverage confirmed. (Commit, push, PR and merge happen afterwards, outside these tasks.)
  - **Result (2026-10-24)**: every FR/SC id in `spec.md` (79) maps to the table below (FR-050a/b and FR-053a inside FR-050–FR-054); STOP-only items validated in T033/T034. FR-062's "stop" event is now logged on SIGTERM. `checklists/requirements.md` has no open items; no change needed.

---

## Requirements coverage

| Requirement | Tasks |
|---|---|
| FR-001–FR-003 | T015, T016 |
| FR-004, FR-030h (dev loopback-only) | T007, T008 |
| FR-005 | T016, T031 |
| FR-010, FR-010a, FR-011, FR-013 | T030, T031, T033 |
| FR-012 (scheduler in the same process) | existing; T016 |
| FR-014 (locks) | T005, T006, T026, T027 |
| FR-020–FR-023 | existing behaviour; T001, T033 |
| FR-024, FR-025 | T031 |
| FR-030 (private data/actions need a session; C2) | T013, T015, T022 |
| FR-030a, FR-030e (local setup/reset, change) | T014, T013, T024 |
| FR-030b | T010 |
| FR-030c (sessions, H2) | T011, T013, T026, T027 |
| FR-030d | T012, T013 |
| FR-030f, FR-032 | T008 |
| FR-030g | boundary; T040 |
| FR-031, FR-034 | T016, T020, T021, T024, T031 |
| FR-033 | T013, T029 |
| FR-035 | T017, T025 |
| FR-036–FR-039 | T024, T031, T037 |
| FR-040–FR-042a, FR-047 | T002, T003, T004, T031 |
| FR-043 | T003, T016 |
| FR-044 | T003, T004, T016, T026, T029 |
| FR-045 | T027 (restore into another path) |
| FR-046 | T016 |
| FR-050–FR-054 | T026, T027, T028, T031 |
| FR-060 | T018 |
| FR-061 | T019, T021, T024 |
| FR-062, FR-063 | T029 |
| FR-070–FR-074 | T022–T025, T034, T035 |
| FR-080, FR-081 | T016, T031 |
| FR-082 | T031 |
| FR-090–FR-093 | T031, T032 |
| SC-001, SC-002, SC-003 | T033 (and T001) |
| SC-004 | T034 |
| SC-005 | T013, T008 |
| SC-006, SC-011 | T027 |
| SC-007 | T031, T033 |
| SC-008 | T018, T026, T029 |
| SC-009 | T031, T016 |
| SC-010 | T011 |

---

## Dependencies & execution order

```text
T001 ─┐
T002 → T003 → T004 → T005 → T006 ──────────────── Checkpoint A
              T004 → T007 → T008
T009 → T010, T011; T012 (P) → T013 → T014 ─────── Checkpoint B
T013 → T015 → T016 ; T008+T013 → T017
T013 → T018 (P) ; T019 (P) ; T004 → T020 → T021 ─ Checkpoint C
T013 → T022 → T023 ; T021+T022 → T024 ; T017 → T025 (P) ─ Checkpoint D
T004+T005+T009 → T026 → T027 → T028 ; T016 → T029 ; T016+T028 → T030 ─ Checkpoint E
T030 → T031 → T032 (P)
T001–T032 → T033 → T034 → T035 ; T033 → T036
T035+T036 → T037 → T038 → T039 → T040 → T041
```

**Story dependencies**: all stories depend on Phases 2–3. US5 (T009–T014) unlocks US1 (T015–T016), US4 (T017, T025), US8 (T018–T021, T024) and US7 (T026–T028). US2 (T030) needs `serve`. US9 docs come last.

## Parallel opportunities

- T012 (rate limiter) alongside T010/T011.
- T018 and T019 alongside T020 once T013 is done.
- T025 alongside T023/T024 (different components).
- T032 alongside the T031 review.

Everything else touches shared files (`cli.py`, `auth.py`, `main.py`, `guards.py`) and stays sequential.

## Implementation strategy

1. **Batch A** (T001–T006): safe groundwork; no behaviour change for the user.
2. **Batch B** (T007–T014): development stays usable (loopback-only); installation auth exists in the backend.
3. **Batch C** (T015–T021): `serve` gives a working installation on loopback (MVP: US1 + US5 on the host).
4. **Batch D** (T022–T025): usable UI in installation mode.
5. **Batch E** (T026–T030): backup/restore, logs and the user service.
6. **Batch F** (T031–T041): docs, STOP gates on real devices, close.

## Notes

- Risks to watch: the locks vs existing tests that open two apps on one DB (T006); pre-020 databases in backup/restore (T026/T027); the shared port 8000 between dev and the service; dev and installation data sharing keyring entries after a migration (T031 docs); `graphical-session.target` outside GNOME (T033); iOS Safari video Range/cookies over HTTP (T034).
- Future work found during T034/T035 is recorded here.
- Found while preparing T033 (not fixed, outside this batch): on SIGTERM uvicorn re-raises the signal after shutdown, so the `finally` in `serve` never logs the T029 shutdown line "AutoPublisher stopped." (uvicorn's "Finished server process" is still logged; the exit status is 143, which systemd treats as a clean stop). Small fix candidate for T035/T037. **Fixed in T037 (2026-10-24)**: `serve` installs a SIGTERM handler for the uvicorn run that logs the stop line once and then re-raises SIGTERM with the default action, so the process still ends by the signal (verified on a real process: exit by SIGTERM, one "AutoPublisher stopped." after "Finished server process"; SIGINT also logs it once). The previous handler is restored afterwards; restart semantics are unchanged.
