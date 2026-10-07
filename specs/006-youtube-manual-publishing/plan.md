# Implementation Plan: Publicación manual real de vídeos en YouTube

**Branch**: `006-youtube-manual-publishing` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-youtube-manual-publishing/spec.md`

## Summary

Ejecutar manualmente (`Publish now`) una `Publication` de un vídeo destinada a una cuenta
YouTube conectada: preflight completo, subida real con el protocolo resumible oficial,
progreso visible y resultado persistido (video ID, URL, privacidad real). Sin scheduler.

**Ejecución**:

- `POST /api/publications/{id}/publish` hace el preflight **síncrono**, incluidas las
  comprobaciones con red (credenciales válidas y canal efectivo = canal vinculado,
  reutilizando la Feature 005).
- Si pasa, en una transacción: `UPDATE … WHERE status IN (…)` condicional a `publishing` +
  `INSERT` de un `PublicationAttempt` `running` (índice único parcial: un solo intento en
  curso por publicación). Responde `202`.
- Un `PublicationRunner` (en `app.state`) ejecuta la subida en un **hilo daemon**. La UI
  sondea cada 2 s.
- El servicio `start_publication(...)` no depende de la petición HTTP: el futuro scheduler
  podrá reutilizarlo.

**Subida resumible** (implementación propia sobre `httpx2`, sin SDK de Google):

- Inicio de sesión con el recurso `video` y `notifySubscribers` explícito; fragmentos de
  8 MiB enviados como iteradores de porciones de 256 KiB leídas del disco.
- `308` + `Range` para continuar; consulta de estado `bytes */TOTAL` tras cortes.
- Recuperación limitada dentro del mismo intento: backoff exponencial (1–32 s), respetando
  `Retry-After` cuando YouTube lo envía (tope seguro de 60 s por espera; si pide más, el
  intento falla sin reintentar antes de tiempo), máximo 6 fallos consecutivos sin progreso,
  renovación de token ante `401`.
- La URI de sesión vive solo en el hilo; nunca en SQLite, logs ni respuestas (filtro de
  logs para `upload_id`).

**Ambigüedad y duplicados**: el intento persiste un `stage`. **Write-ahead**: `final_chunk`
se escribe y se confirma en SQLite **antes** de enviar el último fragmento; al recibir el
video ID, el resultado, el intento `succeeded` y la publicación `published` se persisten
inmediatamente en una transacción. Un fallo o reinicio en `final_chunk`, una respuesta final
sin video ID válido o un resultado que no pudo persistirse son **ambiguos**: requieren
revisión manual en YouTube Studio (por canal, título y momento aproximado) y una
confirmación explícita (`confirm_remote_checked`) para volver a publicar esa pareja
contenido + cuenta. El video ID nunca se escribe en logs ni en almacenamiento alternativo.
Nunca se resube automáticamente, tampoco tras reiniciar (el arranque cierra los intentos
`running` como `interrupted`).

**Modelo**: migración `0005` con estados nuevos en `publications` (+ `published_at`, índice
de duplicados que excluye `published`), tabla genérica `publication_attempts` y tabla del
adaptador `youtube_publication_options` (privacidad, Made for Kids, synthetic media, notify
subscribers).

**Interfaz común de publishers**: primer adaptador real. Un `Protocol` mínimo
(`check`, `prepare`, `upload`, `refresh_details`) y un diccionario de publishers por
plataforma en `app.state`, rellenado por `main.py`. El núcleo solo recibe dependencias
genéricas (`PublishContext`: sesiones, almacenamiento multimedia, `PublishingSettings`); el
`YouTubePublisher` encapsula gateway, almacén de credenciales y `YouTubeUploadSettings`.

**Frontend**: opciones YouTube y `Publish now` en el detalle de publicación, diálogo de
confirmación genérico alimentado por `publish-check`, progreso/resultado/error e historial
de intentos, Queue con los estados nuevos y sondeo mientras algo se publica.

Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**:

- Existentes: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, `httpx2`, `keyring`; React + Vite.
- **Ninguna dependencia nueva** (backend ni frontend). Sin SDK de Google (research §3).

**Storage**:

- SQLite: `publications` ampliada; tablas nuevas `publication_attempts` y
  `youtube_publication_options`.
- Sistema de archivos: el vídeo existente se lee en modo binario, sin copias.
- Almacén seguro del SO: sin cambios (credenciales de la Feature 005).

**Testing**:

- Backend: pytest + `TestClient`. `FakeGoogle` se amplía con un **simulador de subida
  resumible** programable (fallos por petición: transporte, 5xx, 429, 401, 403/400 con
  razón, 404 de sesión, `308` parciales, respuesta final sin ID, latencia para
  concurrencia) servido por el mismo `httpx2.MockTransport`.
- `create_app(..., publishing_settings=PublishingSettings(sleep=no-op),
  youtube_upload_settings=YouTubeUploadSettings(chunk_size=256 KiB, sleep=no-op))`;
  `runner.wait_idle(timeout)` para esperar la ejecución en segundo plano en los tests. El
  simulador puede **bloquear** una petición con un `threading.Event` para los tests de
  respuesta asíncrona y de apagado.
- Frontend: Vitest + Testing Library con `FakeApi` ampliado y temporizadores falsos para el
  sondeo.

**Quality tooling**: sin cambios (Ruff, mypy strict; Oxlint, Prettier, `tsc -b`). CI sin
cambios.

**Target Platform**: igual que la Feature 005 (uso local; Linux con Secret Service, macOS,
Windows).

**Project Type**: aplicación web local (frontend + backend separados).

**Performance Goals**:

- `Publishing` visible < 2 s tras confirmar, sin contar la verificación con Google (SC-002).
- Progreso persistido como máximo cada 1 s y en cada `308`; sondeo de la UI cada 2 s →
  actualización visible ≤ 5 s.
- Memoria acotada a una porción de 256 KiB por subida, independiente del tamaño del vídeo
  (SC-009).

**Constraints**:

- Ningún efecto externo sin confirmación ni antes del preflight (FR-011, FR-015).
- Nunca subir a otro canal (FR-017); nunca resubir automáticamente (FR-045).
- Sin tokens, cabeceras `Authorization` ni URI de sesión en SQLite, logs o respuestas
  (FR-032, FR-037, FR-052).
- Un solo intento en curso por publicación, garantizado en la base (FR-038).
- Sin scheduler ni ejecución por fecha (FR-004).
- Tests sin Internet (FR-056).

**Scale/Scope**:

- 1 migración; 2 tablas nuevas; 3 estados nuevos.
- 5 rutas nuevas (`youtube-options` GET y PUT, `publish-check`, `publish`, `attempts`) y
  6 rutas existentes con reglas nuevas.
- 3 módulos backend nuevos; 3 componentes de interfaz nuevos.

No quedan `NEEDS CLARIFICATION`. Decisiones que la spec difería al plan:

| Decisión | Dónde |
|----------|-------|
| Ejecución en segundo plano y sondeo | research §1 |
| Interfaz común de publishers | research §2 |
| Implementación del protocolo resumible, tamaño de fragmento | research §3 |
| Reintentos, backoff y `Retry-After` | research §4 |
| Ambigüedad del resultado y write-ahead del último fragmento | research §5 |
| Modelo y estados de `PublicationAttempt`, ubicación del resultado | data-model §2, research §7 |
| Fallo al persistir el resultado | research §7 |
| Política de `FAILED`, edición y duplicados | research §13 |
| Orden de la Queue | research §14 |
| Categoría por defecto y caracteres no válidos | research §12 |
| Cuota | research §16 |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Sin dependencias nuevas. Hilos daemon + sondeo HTTP en lugar de colas, workers o WebSockets. Protocolo resumible propio y pequeño en lugar del SDK. La interfaz de publishers son cuatro métodos y un diccionario. Nada del alcance excluido: sin scheduler, retries entre intentos, `publishAt`, thumbnails, tags, playlists, borrado ni otras plataformas. | ✅ |
| II. Spec-Driven Development | El plan implementa la spec ajustada (incluidos `Notify subscribers` y el fallo de persistencia local). Las decisiones diferidas por la spec quedan justificadas en research; FR-041 se concreta respetando sus restricciones obligatorias. | ✅ |
| III. Arquitectura modular | El núcleo (`publishing.py`, `PublicationAttempt`) es genérico: estados, intentos, concurrencia, recuperación. Todo lo de YouTube (opciones, metadata, canal, protocolo, errores) está en `youtube_publishing.py` y `youtube_upload.py`; `Publication` no tiene campos de YouTube y las opciones viven en su propia tabla. Los datos específicos de plataforma del intento son JSON opaco para el núcleo. `PublishContext` solo lleva dependencias genéricas (sesiones, almacenamiento multimedia, `PublishingSettings`); gateway, almacén de credenciales y `YouTubeUploadSettings` se inyectan en el constructor de `YouTubePublisher` desde `main.py` (raíz de composición). Un test de arquitectura garantiza que `publishing.py` y `publications.py` no importan `app.youtube_*`, `app.credential_store`, `httpx`/`httpx2` ni `keyring`. | ✅ |
| IV. Seguridad (repositorio público) | Credenciales siguen solo en el almacén seguro. URI de sesión solo en memoria del hilo; filtro de logs para `upload_id`; sin `exc_info` en el código de subida; mensajes de error fijos por código; JSON de intentos construidos con lista blanca. Tests de fuga sobre SQLite, respuestas y logs a nivel `DEBUG`. API oficial de YouTube. | ✅ |
| V. Calidad y verificabilidad | Simulador de YouTube para todos los casos pedidos. Ningún fallo se pierde: cada ejecución deja un intento persistente con su error; los reinicios cierran los intentos huérfanos; los resultados ambiguos se señalan y bloquean reintentos silenciosos. Principio "una publicación duplicada sin aviso es el fallo más grave": doble garantía de concurrencia y regla de ambigüedad. | ✅ |
| VI. Git y trazabilidad | Rama `006-youtube-manual-publishing`, commits pequeños en inglés. README: sección "Publishing to YouTube" (flujo, opciones, privacidad en proyectos no verificados, cuota con fecha de consulta, revisión manual, borrado en YouTube Studio). | ✅ |
| Arquitectura tecnológica base | FastAPI + SQLite + REST + adaptador por plataforma. El "scheduler local dirigido por la base de datos" no se introduce todavía, pero el servicio de ejecución queda listo para él. | ✅ |
| Idioma y convenciones | Código, mensajes de API y UI, README y commits en inglés; artefactos Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS. El diseño de Fase 1 no
añade dependencias ni infraestructura más allá de lo listado.

## Project Structure

### Documentation (this feature)

```text
specs/006-youtube-manual-publishing/
├── plan.md              # Este archivo
├── research.md          # Fase 0: ejecución, publishers, protocolo, reintentos, ambigüedad…
├── data-model.md        # Fase 1: estados, publication_attempts, youtube_publication_options
├── quickstart.md        # Fase 1: validación automática y manual con YouTube real
├── contracts/
│   └── api.md           # Fase 1: contrato REST
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
backend/
├── migrations/versions/
│   └── 0005_publication_execution.py   # publications (estados, published_at, CHECKs,
│                                       #   índice de duplicados), publication_attempts,
│                                       #   youtube_publication_options
├── app/
│   ├── main.py                  # RAÍZ DE COMPOSICIÓN: create_app(...,
│   │                            #   publishing_settings=None,
│   │                            #   youtube_upload_settings=None); lifespan:
│   │                            #   recover_interrupted_attempts() tras migraciones,
│   │                            #   PublishContext + PublicationRunner en app.state,
│   │                            #   YouTubePublisher(gateway, credential_store,
│   │                            #   upload_settings) registrado en
│   │                            #   app.state.publishers, runner.stop() al cerrar;
│   │                            #   + include_router(publishing, youtube_publishing)
│   ├── errors.py                # ConflictCode + publication_not_eligible,
│   │                            #   publication_in_progress, publication_not_editable,
│   │                            #   content_not_video, invalid_metadata,
│   │                            #   youtube_options_incomplete, remote_check_required
│   ├── models.py                # PublicationStatus + PUBLISHING/PUBLISHED/FAILED;
│   │                            #   Publication.published_at y CHECKs/índice nuevos;
│   │                            #   PublicationAttempt (+ AttemptStatus, AttemptStage);
│   │                            #   YouTubePublicationOptions (+ YouTubePrivacy)
│   ├── schemas.py               # PublicationRead + published_at, latest_attempt,
│   │                            #   attempt_count; PublicationAttemptRead, PublishCheckRead,
│   │                            #   PublishRequest, YouTubePublicationOptionsRead/Write
│   ├── publications.py          # Reglas de edición/cancelación por estado, criterio de
│   │                            #   duplicados (NOT IN cancelled/published), orden de la
│   │                            #   Queue, latest_attempt en PublicationRead. Sin imports
│   │                            #   de youtube_*
│   ├── publishing.py            # NÚCLEO GENÉRICO (sin imports youtube_*, credential_store,
│   │                            #   httpx, keyring): Publisher (Protocol),
│   │                            #   PublishContext (session_factory, storage, settings),
│   │                            #   PublishingSettings (sleep, esperas de persistencia,
│   │                            #   intervalo de progreso, timeout de parada),
│   │                            #   PreparedPublication, PublishOutcome, PublishFailure,
│   │                            #   ProgressReporter; start_publication() (preflight →
│   │                            #   transición atómica → runner.start); PublicationRunner
│   │                            #   (hilos daemon, stop_event, wait_idle); persistencia de
│   │                            #   progreso/resultado con reintentos;
│   │                            #   recover_interrupted_attempts(); requires_remote_check();
│   │                            #   router: publish-check, publish, attempts
│   ├── youtube_publishing.py    # ADAPTADOR YOUTUBE: YouTubePublisher(gateway,
│   │                            #   credential_store, upload_settings) con check, prepare,
│   │                            #   upload, refresh_details; opciones (router GET/PUT
│   │                            #   youtube-options);
│   │                            #   build_description(), validate_metadata(); verificación
│   │                            #   del canal con _list_channels de la Feature 005;
│   │                            #   submitted/details/warnings con lista blanca;
│   │                            #   comprobación ligera videos.list
│   ├── youtube_upload.py        # Protocolo resumible: ResumableUpload (start, send chunks,
│   │                            #   query status, resume), YouTubeUploadSettings, backoff +
│   │                            #   Retry-After (tope 60 s), write-ahead final_chunk,
│   │                            #   clasificación de respuestas → UploadError(code,
│   │                            #   determined); lectura por porciones; stage callbacks
│   ├── youtube_gateway.py       # + get_video_status(access_token, video_id) para la
│   │                            #   comprobación ligera
│   └── youtube_connections.py   # authorize/disconnect: 409 publication_in_progress;
│                                #   _list_channels → list_channels() reutilizable;
│                                #   install_log_redaction() + RedactYouTubeUrls
└── tests/
    ├── fakes.py                 # FakeGoogle + simulador de subida resumible programable
    │                            #   (FAKE_UPLOAD_ID / FAKE_VIDEO_ID distintivos, cola de
    │                            #   fallos, bloqueo con threading.Event, hooks por
    │                            #   petición, bytes recibidos, vídeos creados)
    ├── conftest.py              # + fixture publishing_client (PublishingSettings y
    │                            #   YouTubeUploadSettings con sleep sin espera),
    │                            #   setup_publishable, set_youtube_options,
    │                            #   publish_and_wait, attempt_rows
    ├── test_migrations.py       # + 0005 sobre base con datos de 0004; restricciones e
    │                            #   índices nuevos; deriva modelo ↔ migración
    ├── test_publications_states.py # Edición/cancelación por estado nuevo, duplicados
    │                            #   con publishing/failed/published, campos nuevos de
    │                            #   PublicationRead; test de arquitectura: publishing.py y
    │                            #   publications.py sin imports youtube_*,
    │                            #   credential_store, httpx/httpx2 ni keyring;
    │                            #   PublishContext solo con campos genéricos
    ├── test_youtube_gateway.py  # + get_video_status
    ├── test_youtube_upload.py   # Protocolo resumible unitario: lectura por porciones,
    │                            #   308/Range, write-ahead antes del último fragmento
    ├── test_publish_preflight.py# Cada condición de preflight sin efectos externos (0
    │                            #   peticiones al endpoint de subida), canal distinto →
    │                            #   reconnect_required, imagen, archivo ausente/tamaño,
    │                            #   inactivos, opciones incompletas; paridad con
    │                            #   publish-check
    ├── test_youtube_metadata.py # Título (vacío, 100/101, <>), descripción + hashtags
    │                            #   (con/sin descripción, sin hashtags, 5000 bytes UTF-8)
    ├── test_publish_upload.py   # Éxito end-to-end, streaming por fragmentos (bytes
    │                            #   recibidos = archivo), progreso, write-ahead, 308
    │                            #   parcial, corte de red recuperado (un intento, un
    │                            #   vídeo), 5xx recuperable, Retry-After respetado
    │                            #   (≤ 60 s) y excesivo (> 60 s → failed sin reintento),
    │                            #   agotamiento, 4xx definitivo, cuota,
    │                            #   uploadLimitExceeded, 401 → refresh, InvalidGrant →
    │                            #   reconnect, 404 de sesión, privacidad distinta, Made for
    │                            #   Kids/synthetic/notifySubscribers en la petición,
    │                            #   archivo intacto (sha256), publicación programada
    ├── test_publish_service.py  # FR-013: start_publication invocado sin HTTP con sus
    │                            #   dependencias normales; SC-002: POST /publish responde
    │                            #   publishing con la subida bloqueada en el fake
    ├── test_youtube_options.py  # Defaults, PUT/GET, validación, no YouTube, edición por
    │                            #   estado, persistencia, mapeo a la petición
    ├── test_publish_ambiguity.py# final_chunk → ambiguo; commit de write-ahead fallido →
    │                            #   último fragmento no enviado; 308 incompleto tras el
    │                            #   último fragmento → uploading; remote_check_required y
    │                            #   confirm_remote_checked (también tras cancelar/reactivar
    │                            #   y con nueva publicación de la pareja); result_not_saved
    │                            #   sin video ID en SQLite ni en logs
    ├── test_publish_concurrency.py # Doble Publish now concurrente → 1 sesión; disconnect/
    │                            #   authorize durante publishing → 409
    ├── test_publish_recovery.py # Arranque con intentos running (uploading/final_chunk) →
    │                            #   failed interrupted determinado/ambiguo; sin peticiones
    │                            #   a YouTube; publicación PUBLISHED persiste tras
    │                            #   reinicio; ninguna programada se ejecuta sola; apagado
    │                            #   ordenado determinista (Event + runner.stop())
    ├── test_publish_secrets.py  # Filtro de upload_id; FAKE_UPLOAD_ID, tokens y "Bearer"
    │                            #   ausentes de SQLite (.dump), respuestas JSON y caplog
    │                            #   (DEBUG); el video ID simulado nunca aparece en caplog
    └── test_publications_queue.py # + orden de la Queue con estados nuevos y
                                 #   latest_attempt con consulta agregada

frontend/src/
├── types.ts                     # PublicationStatus + publishing/published/failed y
│                                #   etiquetas; PublicationAttempt, PublishCheck,
│                                #   YouTubePublicationOptions; Publication + published_at,
│                                #   latest_attempt, attempt_count
├── api.ts                       # getYouTubeOptions, saveYouTubeOptions, getPublishCheck,
│                                #   publishNow, listAttempts
├── test-fake-api.ts             # + opciones, publish-check, ejecución simulada con
│                                #   progreso, intentos
├── index.css                    # + badges de estados nuevos, barra de progreso, avisos
└── components/
    ├── PublicationDetail.tsx    # Secciones según estado; sondeo cada 2 s en publishing;
    │                            #   bloqueo de edición; YouTubePublishOptions solo si la
    │                            #   cuenta es YouTube; botón Publish now (deshabilitado con
    │                            #   problems de publish-check)
    ├── YouTubePublishOptions.tsx# Privacidad, Made for Kids, synthetic, Notify subscribers;
    │                            #   nota de proyectos no verificados; solo lectura si
    │                            #   !editable
    ├── PublishNowDialog.tsx     # Diálogo genérico: summary de publish-check, aviso de
    │                            #   publicación programada, casilla obligatoria si
    │                            #   requires_remote_check, botón deshabilitado mientras
    │                            #   se envía (evita doble clic)
    ├── PublicationAttempts.tsx  # Progreso, resultado (Open on YouTube, privacidad real,
    │                            #   avisos, procesamiento), error y revisión manual,
    │                            #   historial de intentos
    ├── PublicationQueue.tsx     # Secciones nuevas en el orden del backend; progreso,
    │                            #   enlace o error por fila; sondeo mientras haya
    │                            #   publishing
    ├── PublicationDetail.test.tsx  # Publish now, diálogo, doble clic, sondeo, progreso,
    │                            #   resultado, problemas del preflight, fallos, revisión
    │                            #   manual y casilla, aviso de programada
    ├── YouTubePublishOptions.test.tsx # Defaults, guardado, solo lectura, no YouTube
    └── PublicationQueue.test.tsx   # + secciones nuevas, progreso, enlace, error, sondeo

frontend/src/storage-safety.test.tsx  # El código de la app no usa localStorage,
                                 #   sessionStorage, IndexedDB ni cookies, y el flujo de
                                 #   publicación no escribe nada en ellos

README.md                        # + "Publishing to YouTube"
```

**Structure Decision**: se mantienen `backend/` y `frontend/` y el paquete plano `app/`.

- **Núcleo de ejecución** (`publishing.py`): genérico y reutilizable por el futuro
  scheduler y otras plataformas.
- **Adaptador YouTube** dividido en reglas/metadata/opciones (`youtube_publishing.py`) y
  protocolo de transporte (`youtube_upload.py`), siguiendo la separación de la Feature 005
  (lógica pura / HTTP / router).
- `publications.py` sigue siendo el CRUD de intenciones; solo aprende los estados nuevos.

## Design Notes

- **Dependencias del núcleo**: `publishing.py` importa solo `models`, `schemas`, `errors`,
  `db`, `storage` y la librería estándar. No importa `app.youtube_*`,
  `app.credential_store`, `httpx`/`httpx2` ni `keyring` (test de arquitectura).
- **Registro de publishers**: `app.state.publishers: dict[Platform, Publisher]`. `main.py`
  (raíz de composición) construye
  `YouTubePublisher(gateway=GoogleGateway(...), credential_store=..., upload_settings=YouTubeUploadSettings(...))`
  y lo registra. Los endpoints del núcleo lo obtienen del `app.state` y solo usan el
  protocolo `Publisher`.
- **`PublishContext`** (inyectado en `check`/`prepare`/`upload`/`refresh_details`):
  `session_factory`, `storage` y `settings: PublishingSettings`. Nada específico de una
  plataforma. El adaptador YouTube usa sus propias dependencias (gateway, almacén,
  `YouTubeUploadSettings`) y `ctx.session_factory` para obtener credenciales con
  `get_valid_credentials` justo antes de cada petición; nunca las guarda en
  `PreparedPublication`.
- **`PublishingSettings`** (núcleo): `sleep`, `persist_retry_waits=(0.5, 1.0, 2.0)`,
  `progress_interval=1.0`, `stop_timeout=5.0`. `persist_success`/`persist_failure` y el
  reporter solo usan estos valores.
- **`YouTubeUploadSettings`** (adaptador): `chunk_size=8 MiB`, `slice_size=256 KiB`,
  `max_consecutive_failures=6`, `max_backoff=32`, `max_retry_wait=60`, `sleep`.
- **`start_publication(session, publication_id, *, confirm_remote_checked, ctx, runner, publishers)`**
  (función sin tipos de FastAPI; el endpoint la llama tras resolver `app.state`, y un test
  la invoca directamente sin HTTP, FR-013):
  1. `publisher.check(...)` (local); el primer problema se lanza como error (orden del
     contrato);
  2. `requires_remote_check` sin confirmación → `remote_check_required`;
  3. `publisher.prepare(...)` (red: credenciales y canal);
  4. transición atómica + `INSERT` del intento con `submitted`, `total_bytes`,
     `stage = preparing` (research §8);
  5. `runner.start(attempt_id, prepared, publisher)`; si lanzar el hilo falla, el intento se cierra
     `failed`/`internal_error` determinado.
- **Hilo de ejecución** (`PublicationRunner._run`):
  1. `outcome = publisher.upload(prepared, reporter)`;
  2. `reporter` persiste `bytes_sent` (≤ 1/s y en cada `308`) y `stage`, y expone
     `should_stop()`. `reporter.enter_final_chunk()` hace el **write-ahead**: escribe
     `final_chunk`, hace commit y devuelve si se confirmó; el uploader solo envía el último
     fragmento si devolvió `True` (research §5);
  3. éxito → `persist_success` inmediatamente, en una transacción (resultado remoto +
     intento `succeeded` + publicación `published`), con reintentos (research §7); después,
     comprobación ligera (`publisher.refresh_details`, opcional, fuera de esa transacción).
     Si `persist_success` falla → `result_not_saved` ambiguo, sin video ID en la base ni en
     logs;
  4. `PublishFailure(code, message, determined, external_id?)` → intento `failed` y
     publicación `failed`;
  5. cualquier otra excepción → `internal_error`, `determined = stage != final_chunk`; log
     solo con el nombre de la clase y los ids internos.
- **`401` durante la subida**: el uploader pide `get_valid_credentials(force_refresh=True)`
  una vez; `ConflictError("reconnect_required")` → `PublishFailure("reconnect_required")`
  (la conexión ya queda `reconnect_required` por la Feature 005).
- **Sesiones de base de datos en el hilo**: cada escritura abre su propia sesión corta con
  `app.state.session_factory`; nunca se comparte la sesión de la petición.
- **`PublicationRead`**: `latest_attempt` y `attempt_count` se cargan con una consulta por
  publicación en el detalle y con una consulta agregada en el listado de la Queue.
- **Reglas de edición** (research §13): una función `ensure_editable(publication, change)`
  en `publications.py` y reutilizada por `youtube_publishing.py` para las opciones.
- **Frontend: confirmación**: `PublishNowDialog` pide `publish-check` al abrirse; muestra
  `summary` tal cual; si `scheduled_at`, el aviso "This publication is scheduled for … It
  will be published now, before its scheduled time."; si `requires_remote_check`, la casilla
  obligatoria. El botón **Publish** se deshabilita al primer clic hasta la respuesta.
- **Frontend: sondeo**: `PublicationDetail` sondea `getPublication` cada 2 s mientras
  `status === "publishing"`; `PublicationQueue` sondea el listado cada 2 s mientras alguna
  fila esté `publishing`. Ambos se limpian al desmontar.
- **Frontend: resultado**: `Open on YouTube` usa `latest_attempt.external_url` con
  `target="_blank" rel="noopener noreferrer"`. Los `warnings` se muestran como avisos.
- **Logs**: `RedactYouTubeUrls` se instala en `install_log_redaction()` (llamada ya
  desde `create_app`) sobre `httpx2` y `httpcore2.*`, y redacta `upload_id=`, la cabecera
  `X-GUploader-UploadID` y el `id=` de `videos.list`. Tests de `caplog` a nivel `DEBUG` lo verifican.
- **README**: sección "Publishing to YouTube": flujo, opciones (privacidad por defecto
  `private`, Made for Kids y synthetic obligatorios, Notify subscribers por defecto `No`),
  proyectos no verificados → `private` y auditoría, cuota vigente con fecha y enlace, qué
  significa "requires manual review", borrar vídeos de prueba en YouTube Studio, sin
  scheduler todavía.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.

| Elemento | Por qué es necesario | Alternativa más simple descartada |
|----------|----------------------|------------------------------------|
| Interfaz `Publisher` + registro | Constitution III: adaptador por plataforma sin lógica de YouTube en el núcleo; el scheduler la reutilizará. | Lógica de YouTube en `publications.py`: viola el principio III. |
| Hilos daemon con `PublicationRunner` | La subida dura minutos y la API no debe bloquear al navegador (FR-012); control de parada y de intentos vivos. | `BackgroundTasks` sin control de parada; colas o workers externos excluidos por la Constitution. |
| `stage` persistido en el intento con write-ahead | Distinguir fallos determinados de ambiguos sin marcar como ambiguo cualquier corte, también tras un reinicio (research §5). | Considerar ambiguo todo fallo con sesión creada: obligaría a revisión manual tras cualquier corte de red. |
| Protocolo resumible propio | Control exacto de logs (URI de sesión) y de la ambigüedad; sin dependencias nuevas. | SDK de Google: añade dependencias y oculta la sesión y los reintentos. |
