# Implementation Plan: Publicación real de texto, imagen y vídeo en Threads

**Branch**: `011-threads-publisher` | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-threads-publisher/spec.md`

## Summary

Registrar un `ThreadsPublisher` en el registro genérico de publishers para publicar en
Threads un post de **texto** (sin media), una **imagen** o un **vídeo** individuales, con
`Publish now` y con el scheduler genérico, sin código de Threads en el núcleo.

Para el texto sin media, el `Content` de una `Publication` pasa a ser **opcional** de forma
neutral: el protocolo `Publisher` declara `accepts_text_only` (solo Threads lo activa), un
endpoint nuevo crea publicaciones sin `Content` y el preflight genérico rechaza
(`publication_media_required`) cualquier publicación sin media en plataformas que no la
admiten. El tipo Threads se deriva (`content_id` nulo → `TEXT`; imagen → `IMAGE`; vídeo →
`VIDEO`). El texto es la descripción efectiva más, si existen, una línea en blanco y los
hashtags efectivos (mecanismo existente), validado sobre el texto final (500 caracteres con
emojis contados en bytes UTF-8, ≤ 5 enlaces, no vacío en `TEXT`) y nunca truncado.

Flujo: preflight (credencial, permisos e identidad con los servicios de la Feature 010,
cuota real de `threads_publishing_limit`, compatibilidad del media, texto, `alt_text`,
configuración de media delivery solo para imagen/vídeo, container anterior ya publicado;
cuota agotada → error, fallo temporal de la consulta → continúa con aviso, forma inesperada →
`threads_unexpected_response`) →
`PUBLISHING` → (imagen/vídeo: entrega temporal con el `TemporaryMediaService` existente) →
container (`POST /{user}/threads`, id y hora de creación persistidos al instante) → lectura
inmediata del estado y espera acotada solo si Meta indica procesamiento (texto 1 min, imagen
3 min, vídeo 5 min) → `FINISHED` **y** antigüedad del container ≥ 30 s
(`MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS`, política del producto tras la validación real:
un container `FINISHED` a ~300 ms fue rechazado; solo se espera lo que falta y se relee el
estado) → write-ahead (`finalizing`) → `threads_publish` **una sola vez** → permalink oficial →
`PUBLISHED` → **después** cleanup best-effort. Un post ID devuelto por `threads_publish`
determina el éxito: si el permalink no se obtiene, la publicación queda `PUBLISHED` con
`external_url = null` y un aviso, sin repetir nada. Ante un `threads_publish` no concluyente solo
se lee el container original: `PUBLISHED` es la única señal que resuelve (publicado sin
identidad remota si no hay post ID); si no, ambiguo con revisión manual y reconciliación de
solo lectura posterior. Nunca `auto_publish_text`, nunca reutilización de containers, nunca
búsqueda de posts recientes. Vídeo: todo lo que `ffprobe` da de forma fiable se valida en
preflight (datos obligatorios ausentes → falla); solo closed GOP, edit lists y los bitrates o
el escaneo que `ffprobe` no reporte se delegan a Meta, registrados en `delegated_checks`.
WebP estático → PNG sin pérdida validado como derivado; WebP animado → rechazo. Los `POST` a
Meta usan cuerpo `application/x-www-form-urlencoded`, validado contra Meta real como primera
comprobación del quickstart. Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring`, Pillow,
`boto3` (existentes). **Ninguna dependencia nueva**. `ffprobe` (opcional del sistema).

**Storage**: SQLite, migración `0010_threads_publishing` (`publications.content_id`
anulable; tablas `threads_publication_options` y `threads_publish_runs`). Keyring (servicio de
Threads) y bucket R2 sin cambios.

**Testing**: pytest con `FakeThreads` ampliado (containers, estados programables,
`threads_publish`, media, cuota, registro de peticiones), `FakeMediaDeliveryProvider`,
`InMemoryCredentialStore`, `FakeClock`, `probe_video_streams` simulado y `sleep` instantáneo.
Vitest + Testing Library con `FakeApi`. Todo sin Internet, sin Meta real, sin R2 real y sin
keyring real.

**Target Platform**: aplicación local (Linux principal) con conexión saliente a Meta y R2.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: texto e imagen publicados en unos 30 s en condiciones normales (la
antigüedad mínima del container antes de `threads_publish`; sin más esperas si Meta responde
`FINISHED`); vídeo limitado por el procesamiento de Meta (timeout
5 min, recomendación oficial). Timeouts HTTP: 10 s lecturas, 60 s container y publicación.

**Constraints**: `threads_publish` como máximo una vez por container y solo con el container
`FINISHED` y de al menos 30 s de antigüedad; write-ahead antes;
preflight sin efectos remotos de publicación ni de delivery; URL firmada solo en memoria y en
el cuerpo del `POST`; texto sin transformaciones; sin transcodificación; sin código de
Threads en `publishing`, `publications`, `scheduler`, `automation` ni en el núcleo de
Accounts.

**Scale/Scope**: un usuario, pocas cuentas; ≤ 250 posts/24 h por cuenta (cuota real de Meta);
3 rutas nuevas (`text-publications`, `GET`/`PUT threads-options`), 2 componentes nuevos y
ampliaciones de 4 componentes.

No queda ningún NEEDS CLARIFICATION: endpoints, límites de texto y media, `alt_text`, espera
por tipo, caducidad, cuota, semántica de `threads_publish`, reconciliación, permalink, media
delivery y modelo de publicaciones sin `Content` están resueltos en
[research.md](research.md). Lo que la documentación no garantiza (estado inmediato de
containers `TEXT`/`IMAGE`, aceptación de URLs prefirmadas, forma real de la cuota,
parámetros en el cuerpo `application/x-www-form-urlencoded` de los `POST` — comprobación
temprana —, bitrate de audio reportado por `ffprobe`) se valida en
[quickstart.md](quickstart.md) con stop conditions explícitas.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias nuevas, sin `auto_publish_text`, sin reutilización de containers, sin opciones de la API más allá de `alt_text`, sin transcodificación, sin scheduler ni media delivery propios. El único cambio de modelo común (`content_id` anulable) lo exige el alcance aprobado (FR-003). Fuera de alcance respetado (carousels, replies, polls, topic tags explícitos, borrado…). | ✅ |
| II. Spec-Driven | Plan derivado de FR-001…FR-057 y de las tres decisiones de clarificación; protocolo documentado con fuentes en research. | ✅ |
| III. Arquitectura modular | Lógica de Threads en `threads_publishing.py`, `threads_media.py` y `threads_gateway.py`; Threads no importa Instagram. El núcleo solo gana conceptos neutrales: `Publisher.accepts_text_only`, `PreparedPublication.file_path` opcional, `publication_media_required`, `content` opcional. Tests de arquitectura existentes + Threads↛Instagram para los módulos nuevos. | ✅ |
| IV. Seguridad | Sin secretos nuevos. Token en keyring (Feature 010), URL firmada en `SecretUrl`, parámetros sensibles en el cuerpo del `POST`, redacción existente de Threads y de media delivery; tests de secretos en DB, logs, API y navegador. API oficial de Meta. | ✅ |
| V. Calidad | Tests de todos los casos de FR-055 con fakes; write-ahead y política anti-duplicados probados por fase; ningún fallo silencioso (ambiguos visibles, cleanup pendiente registrado). | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README y `docs/threads-publishing.md`. | ✅ |
| Arquitectura base: infraestructura cloud | Se reutiliza el almacenamiento efímero ya justificado en la Feature 009 (solo imagen/vídeo); el texto no lo necesita. Sin nueva desviación. | ✅ |

**Re-check post-diseño**: sin violaciones. Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/011-threads-publisher/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── models.py                     # content_id Optional; ThreadsPublicationOptions,
│   │                                 #   ThreadsMediaKind, ThreadsPublishPhase, ThreadsPublishRun
│   ├── schemas.py                    # PublicationRead.content_id/content opcionales;
│   │                                 #   TextPublicationCreate; ThreadsPublicationOptionsRead/Write
│   ├── publications.py               # effective_metadata(content opcional); lectura, cola
│   │                                 #   (outerjoin), ensure_can_prepare, reactivate y
│   │                                 #   consentimiento sin Content; POST text-publications
│   │                                 #   (consulta app.state.publishers.accepts_text_only)
│   ├── publishing.py                 # Publisher.accepts_text_only; file_path opcional;
│   │                                 #   local_check → publication_media_required;
│   │                                 #   requires_remote_check(publication)
│   ├── media_delivery.py             # EXTENSIONS + image/png; mensaje neutral
│   ├── youtube_publishing.py         # accepts_text_only = False
│   ├── instagram_publishing.py       # accepts_text_only = False
│   ├── threads_gateway.py            # + create_container, container_status, publish,
│   │                                 #   published_media, publishing_limit
│   ├── threads_media.py              # NEW: kind, texto (composición, conteo, enlaces),
│   │                                 #   imagen (JPEG/PNG; WebP→PNG en memoria), vídeo (ffprobe)
│   ├── threads_publishing.py         # NEW: router threads-options, ThreadsPublisher
│   │                                 #   (check/prepare/upload/refresh_details/release/
│   │                                 #   reconcile), ThreadsPublishSettings
│   └── main.py                       # registrar ThreadsPublisher y su router
├── migrations/versions/
│   └── 0010_threads_publishing.py    # NEW
└── tests/
    ├── fakes.py                      # FakeThreads ampliado; FakePublisher.accepts_text_only
    ├── conftest.py                   # fixtures de publicación Threads (texto/imagen/vídeo)
    ├── test_text_publications.py     # NEW: creación sin Content y regresión neutral
    ├── test_threads_media.py         # NEW: texto, imagen, vídeo (sin red)
    ├── test_threads_options.py       # NEW
    ├── test_threads_preflight.py     # NEW: incl. cuota (válida, agotada, temporal, inesperada)
    ├── test_threads_gateway_publish.py  # NEW
    ├── test_threads_publish.py       # NEW: texto, imagen, vídeo; polling; timeouts; errores
    ├── test_threads_ambiguity.py     # NEW: write-ahead, una sola llamada, ambigüedad
    ├── test_threads_reconcile.py     # NEW
    ├── test_threads_recovery.py      # NEW: reinicio en cada fase
    ├── test_threads_scheduler.py     # NEW: programada, pausa, carrera, concurrencia
    ├── test_threads_cleanup.py       # NEW
    ├── test_threads_publish_secrets.py  # NEW
    ├── test_migrations.py            # + 0010
    └── test_publications_states.py   # + arquitectura de los módulos nuevos

frontend/src/
├── types.ts                          # content opcional; ThreadsPublicationOptions;
│                                     #   TEXT_POST_PLATFORMS
├── api.ts                            # createTextPublications, get/saveThreadsOptions
├── components/
│   ├── TextPublicationCreate.tsx     # NEW (+ test)
│   ├── ThreadsPublishOptions.tsx     # NEW (+ test)
│   ├── PublicationQueue.tsx          # botón New text post; filas sin Content
│   ├── PublicationDetail.tsx         # threads en PUBLISHING_PLATFORMS; sin Content
│   └── PublicationAttempts.tsx       # revisión manual Meta compartida (Instagram/Threads)
├── test-fake-api.ts                  # endpoints nuevos
└── storage-safety.test.tsx           # + Threads publishing

docs/threads-publishing.md            # NEW
README.md                             # sección Publishing to Threads
```

**Structure Decision**: aplicación web existente (`backend/` + `frontend/`). Threads sigue el
patrón de Instagram (gateway, reglas de media sin red, publisher + router de opciones) en
módulos propios; el núcleo solo recibe los cambios neutrales listados.

## Fases de implementación (orientativas para `/speckit-tasks`)

1. **Base neutral**: migración `0010`, `content_id` opcional en modelo/esquemas/lectura,
   `accepts_text_only`, `publication_media_required`, `requires_remote_check(publication)`,
   endpoint `text-publications`; regresión YouTube/Instagram.
2. **Gateway y reglas sin red**: métodos nuevos de `ThreadsGateway`, `threads_media.py`.
3. **Publisher texto (MVP)**: opciones, check/prepare, container `TEXT`, write-ahead,
   publish, permalink, ambigüedad, reconciliación, recuperación.
4. **Imagen y vídeo**: media delivery, polling por tipo, errores de container, cleanup.
5. **Scheduler y concurrencia**: tests de integración con el scheduler genérico.
6. **Frontend**: tipos, API, creación de texto, opciones, detalle, intentos.
7. **Seguridad, docs y validación real** (quickstart).

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
