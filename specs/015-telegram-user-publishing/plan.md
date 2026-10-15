# Implementation Plan: Telegram User Account & Publishing

**Branch**: `015-telegram-user-publishing` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-telegram-user-publishing/spec.md`

## Summary

Añadir Telegram como **cuenta de usuario real** (MTProto vía Telethon 1.45, sin Bot API):
login teléfono → código → 2FA, sesión `StringSession` solo en el almacén seguro del sistema,
Verify/Disconnect reales, un canal broadcast destino por `Account` (no modificable con
publicaciones `scheduled`/`publishing`) y un `TelegramPublisher` registrado en la arquitectura
genérica que publica texto, una imagen o un vídeo MP4 con caption, manual o programado.

Enfoque técnico (research.md):

- `telegram_gateway.py` es el **único** módulo que importa Telethon; expone métodos síncronos
  que ejecutan `asyncio.run` con un cliente efímero por operación (§2) y traducen errores a
  excepciones propias (§12). El cliente fija explícitamente `flood_sleep_threshold=5`,
  `request_retries=3` y `raise_last_call_error=True`.
- **Serialización por cuenta**: como máximo un cliente MTProto activo por `Account` Telegram
  (lock en proceso por `account_id` dentro de la integración Telegram). Publish Now y el
  scheduler esperan; Verify, canales y Disconnect responden `409 telegram_busy`. Cuentas
  distintas en paralelo. Sin cambios en scheduler/core (§2).
- Anti-duplicados sin reconciliación (§8): `random_id` generado en `prepare()` y persistido por
  el core dentro de `submitted` (write-ahead sin tocar el núcleo); envío con
  `SendMessageRequest`/`SendMediaRequest` de bajo nivel. Telegram deduplica por peer y **no
  olvida** los `random_id`: tras un fallo de red o `RANDOM_ID_DUPLICATE` (envío previo aún en
  curso) se repite la **misma** petición como máximo 2 veces más; solo un `UpdateMessageID`
  con nuestro `random_id` confirma `PUBLISHED` con message ID; sin confirmación → resultado
  incierto genérico. Un intento posterior de la misma publicación reutiliza el `random_id`
  del intento incierto, así que nunca hay dos mensajes.
- Cero cambios en `publishing.py`, `scheduler.py`, `publications.py`, `automation.py` y en las
  tablas comunes. Cambios aditivos solo en el composition root y registros compartidos.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React + Vite (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, Alembic, keyring (existentes) + **Telethon
`>=1.45,<2`** (nueva; `pyaes`, `rsa` transitivas)

**Storage**: SQLite (nueva tabla `telegram_connections`); sesión en almacén seguro del SO
(servicio `autopublisher.telegram`); credenciales de app en `backend/data/telegram-app.json`

**Testing**: pytest con un `FakeTelegramGateway` inyectado en `create_app`; vitest para el
panel. Sin tests de Telethon/MTProto.

**Target Platform**: aplicación local de un usuario (Linux principal)

**Project Type**: web application (backend + frontend)

**Performance Goals**: no críticos; una conexión MTProto (~1 s) por operación es aceptable

**Constraints**: ningún secreto fuera del almacén seguro; nunca duplicar deliberadamente;
nunca bot; sin transformar contenido

**Scale/Scope**: 1 usuario, pocas cuentas Telegram, un canal por cuenta, volumen bajo

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Nota |
|---|---|---|
| I. Simplicidad y alcance | ✅ | Sin reconciliación ni lectura de historial, sin opciones por publicación, sin native scheduling, sin hilo asyncio permanente; serialización con un lock en proceso. Una tabla nueva. |
| II. Spec-Driven | ✅ | Spec aprobada con decisión de canal por `Account` (FR-014/FR-014a). |
| III. Arquitectura modular | ✅ | Todo lo de Telegram en `telegram_*.py`; el core solo ve `Publisher`. Telethon aislado en el gateway. |
| IV. Seguridad | ✅ | Sesión solo en keyring; `api_hash` en archivo ignorado; código/2FA nunca persistidos; logs solo con nombres de clase; `.gitignore` con `*.session`. Usa la API oficial de Telegram (MTProto) con credenciales de app propias; nada de scraping. |
| V. Calidad | ✅ | Tests dirigidos con fakes; fallos visibles en el intento; duplicados evitados por `random_id` + remote check genérico. |
| VI. Git | ✅ | Commits pequeños en inglés; docs `docs/telegram.md` + README. |

**Post-design re-check**: ✅ sin violaciones; Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/015-telegram-user-publishing/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── telegram_gateway.py       # NUEVO: único importador de Telethon (login, me, log_out,
│   │                             #   canales, get_channel, upload+send con random_id)
│   ├── telegram_connections.py   # NUEVO: config app, login registry, verify, disconnect,
│   │                             #   canales, lock por cuenta, rutas /telegram-connection
│   ├── telegram_publishing.py    # NUEVO: TelegramPublisher (check/prepare/upload/...)
│   ├── models.py                 # + TelegramConnection, TelegramConnectionStatus
│   ├── schemas.py                # + schemas Telegram
│   ├── config.py                 # + get_telegram_app_file, TELEGRAM_LOGIN_TTL
│   ├── credential_store.py       # + TELEGRAM_SERVICE
│   └── main.py                   # wiring: store, gateway, registry, publisher, router
├── migrations/versions/0014_create_telegram_connections.py
├── pyproject.toml                # + telethon; mypy override telethon.*
└── tests/
    ├── fakes_telegram.py         # FakeTelegramGateway
    ├── test_telegram_connections.py
    └── test_telegram_publishing.py

frontend/src/
├── types.ts                      # + tipos Telegram; "telegram" en TEXT_POST_PLATFORMS
├── api.ts                        # + llamadas telegram-connection
├── components/TelegramConnectionPanel.tsx (+ .test.tsx)
├── components/AccountList.tsx    # monta el panel
└── components/PublicationDetail.tsx  # "telegram" en PUBLISHING_PLATFORMS

docs/telegram.md, README.md, .gitignore
```

**Structure Decision**: misma estructura web existente; un módulo por responsabilidad como
Threads/TikTok, pero con un solo archivo de tests por área para mantener el testing ligero.

## Diseño por componentes

### `telegram_gateway.py`

Interfaz síncrona (Protocol `TelegramGateway`, implementada por `TelethonGateway` y por el
fake de tests):

- `send_code(config, phone) -> PendingLogin` · `sign_in_code(config, pending, code) -> SignedIn | PasswordRequired`
  · `sign_in_password(config, pending, password) -> SignedIn` (`SignedIn` = sesión + identidad).
- `get_me(config, session) -> TelegramIdentity` · `log_out(config, session) -> None`.
- `list_channels(config, session) -> list[TelegramChannel]` (con `access_hash` interno).
- `publish(config, session, channel_ref, SendSpec, random_id, on_progress, before_send) -> SendResult`:
  en un solo cliente comprueba el canal (permiso, título, username), sube el archivo y envía
  (el `InputFile` pertenece al cliente que lo subió). `before_send()` llama a
  `reporter.enter_finalizing()`; si devuelve `False` no se envía. Incluye la repetición
  acotada de §8.4 con el mismo `random_id`. `SendResult` = `message_id` + canal refrescado;
  sin confirmación lanza `TelegramUnconfirmed`.
- Excepciones propias: `TelegramUnauthorized`, `TelegramChannelUnavailable`,
  `TelegramTextRejected`, `TelegramMediaRejected`, `TelegramRateLimited(seconds)`,
  `TelegramLoginInvalid(reason)`, `TelegramUnavailable` (antes de enviar),
  `TelegramUnconfirmed` (tras `finalizing` sin confirmación).

### `telegram_connections.py`

Patrón de `threads_connections.py` simplificado: `load_config()`, `get_connection()`,
`TelegramLoginRegistry` (memoria, TTL), `account_session(account_id, wait)`: context manager
con un `threading.Lock` por `account_id` que envuelve **toda** llamada al gateway con la sesión
de esa cuenta (rutas interactivas y login con `wait=False` → `409 telegram_busy`; publicación
con espera en bucles de 1 s comprobando `should_stop()`), `mark_reconnect_required()`, `load_session(store, connection)`,
rutas del contrato, y el bloqueo de cambio de canal consultando `Publication`.

### `telegram_publishing.py`

`TelegramPublisher` con `accepts_text_only = True`:

- `check()`: tipo (texto/imagen/vídeo), límites §10, archivo, conexión, canal, FloodWait.
- `prepare()` (sin red): carga la sesión del almacén, decide `random_id` (nuevo o reutilizado
  §8.2), construye `PreparedPublication` (`submitted` con `telegram_random_id`).
- `upload()`: dentro de `account_session(account_id, wait=True)`, `gateway.publish(...)` con
  progreso; refresca título/username del canal en la fila; traduce errores a
  `PublishFailure` (`TelegramUnconfirmed` → `determined=False`, el resto determinado);
  FloodWait → `flood_wait_until`; `Unauthorized` → `reconnect_required`.
- `refresh_details()` devuelve el outcome tal cual; `release()` → `[]`;
  `arming_problems()` → sin conexión o sin canal; `reconcile()` / `follow_up()` → `None`.

### Frontend

`TelegramConnectionPanel`: estado, formulario por pasos (teléfono → código → contraseña),
Verify, Disconnect, selector de canal (deshabilitado con explicación si
`channel_change_blocked`). Publicaciones: reutiliza las pantallas existentes (texto con
"New text post", media desde la biblioteca); sin opciones específicas de Telegram.

## Orden de implementación (con checkpoints reales)

1. **Fundación**: dependencia, config, `TELEGRAM_SERVICE`, modelo + migración, `.gitignore`.
2. **Cuenta (backend)**: gateway (login/me/log_out/canales), conexiones y rutas; tests con
   fake. → **Checkpoint V1a** real vía `curl` (quickstart). STOP si falla.
3. **Publicación (backend)**: `send` en el gateway, `TelegramPublisher`, registro en `main.py`;
   tests (texto, imagen, vídeo, random_id, FloodWait, errores, secretos). → **Checkpoint V1b**
   real (texto, imagen, vídeo vía API). No seguir sin **V1 PASS**.
4. **UI**: panel de conexión, plataformas habilitadas, tests de componente.
5. **Scheduler**: test manual + programado con el mismo publisher (fake); validación real de
   una programación.
6. **Docs** (`docs/telegram.md`, README) y quality gates completos una vez.

## Tests mínimos (nuestro código, fakes en el límite)

- Login completo y con 2FA; código inválido; login pendiente expirado/cancelado; reconexión
  con otra identidad → mismatch.
- Sesión: solo en el store fake; ausente de SQLite, respuestas y logs (junto con código,
  contraseña y `api_hash`).
- Verify válido / revocado → `reconnect_required`. Disconnect: éxito, sesión ya revocada,
  Telegram inalcanzable (no borra nada).
- Canales: solo elegibles; selección; cambio bloqueado con `scheduled`/`publishing`;
  canal no elegible → 422.
- Publicación: texto, imagen, vídeo, caption exacto, `external_id`/`external_url`
  (público vs privado), `random_id` persistido en `submitted` antes del envío, FloodWait → error +
  bloqueo en `check()`, canal sin permiso, preflight de límites/formatos.
- Anti-duplicados: respuesta con `UpdateMessageID` → éxito con ID; `RANDOM_ID_DUPLICATE`
  seguido de la respuesta original en la repetición → éxito con ID; `RANDOM_ID_DUPLICATE`/red
  persistentes tras `finalizing` → incierto (nunca `PUBLISHED` sin ID); todas las
  repeticiones usan el mismo `random_id`; reutilización del `random_id` tras incierto.
- Concurrencia: con el lock de una cuenta ocupado, Verify/canales/cambio de canal/Disconnect
  → `409 telegram_busy` y la publicación espera; otra cuenta no se bloquea.
- Cliente: la factoría del gateway construye `TelegramClient` con `flood_sleep_threshold=5`
  (test pequeño, sin red).
- Manual + scheduler usan el mismo publisher.

## Complexity Tracking

Sin violaciones de la Constitution.
