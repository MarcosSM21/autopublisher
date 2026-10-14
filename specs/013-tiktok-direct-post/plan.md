# Implementation Plan: Publicación real de vídeo en TikTok mediante Direct Post (FILE_UPLOAD)

**Branch**: `013-tiktok-direct-post` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/013-tiktok-direct-post/spec.md`

## Summary

Registrar un `TikTokPublisher` en el registro genérico de publishers para publicar **un vídeo
local** en la cuenta TikTok conectada (Feature 012) mediante **Direct Post** con `source =
FILE_UPLOAD` y `video.publish`, con `Publish now` y con el scheduler genérico, sin código de
TikTok en el núcleo. Sin fotos, `PULL_FROM_URL`, R2, `video.upload`, `video.list`, App Audit,
transcoding ni cross-posting.

Flujo dentro del protocolo existente: `check` (sin red: conexión, opciones, caption contado en
unidades UTF-16 ≤ 2200, vídeo con ffprobe, consentimiento vigente por huella) → `prepare`
(Creator Info **reconsultado** con `call_with_token`; creador habilitado; `SELF_ONLY` presente y
elegido; interacciones compatibles; duración ≤ `max_video_post_duration_sec`; **SHA-256 en
streaming del archivo == `Content.checksum`**) → `upload` (segundo hash incremental sobre los
mismos bytes que se suben, sin lectura extra): run TikTok → `video/init/` **una vez**
→ `publish_id` **committed antes del primer byte** → chunks intermedios (buffers ≤ 64 MiB leídos
del original, 3 reintentos ante red/5xx, política estricta de `416`) → último chunk leído en
memoria e incorporado al hash → digest completo == checksum (si no: fallo determinado, sin
write-ahead ni `PUT` final) → **write-ahead** (`AttemptStage.FINAL_CHUNK` genérico + run) → **un único
`PUT` del último chunk, sin reenvío; cualquier respuesta distinta de `201` (incluido `4xx`) no
prueba nada y solo lleva al polling** → `FINALIZING` → polling acotado del `publish_id` (≤ 10 min,
≪ 30/min) → `PUBLISH_COMPLETE` = `PUBLISHED` (sin post ID con `SELF_ONLY`, sin permalink) /
`FAILED` = determinado / resto = ambiguo. `reconcile` solo lee el `publish_id` original; una
extensión neutral (`ReconciledFailure`) permite cerrar como determinado un `FAILED` confirmado.
El armado de auto-publish consulta un hook neutral `Publisher.arming_problems` para exigir el
consentimiento TikTok al programar. Detalle y alternativas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring` (existentes).
**Ninguna dependencia nueva**. `ffprobe` del sistema (ya usado por Features 003/009/011).

**Storage**: SQLite, migración `0012_tiktok_publishing` (tablas `tiktok_publication_options` y
`tiktok_publish_runs`). Keyring de TikTok (Feature 012) sin cambios. Vídeo: archivo original del
almacenamiento local, solo lectura.

**Testing**: pytest con `FakeTikTok` ampliado (creator info, init, upload con host falso, status;
fallos programables por chunk; registro de peticiones), `FakeClock`, `sleep` instantáneo,
`probe_video_streams` simulado, archivos de prueba pequeños con `chunk_size` inyectable para
multi-chunk, `InMemoryCredentialStore`. Vitest + Testing Library con `FakeApi`. Sin red real.

**Target Platform**: aplicación local (Linux principal) con conexión saliente a
`open.tiktokapis.com` y al host de subida que devuelva TikTok.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: preflight dominado por el SHA-256 del archivo (lectura secuencial; ≈
segundos para varios GB); subida limitada por el ancho de banda (32 MiB por petición); resultado
en minutos según TikTok (ventana de 10 min). Memoria pico ≈ un buffer de chunk (≤ 64 MiB).

**Constraints**: init ≤ 1 por intento; último chunk exactamente 1 vez tras el write-ahead;
`upload_url` solo en memoria (`UploadUrl`) y redactado en logs; nunca segundo `publish_id`,
nunca listados de posts; Creator Info nunca cacheado como autoridad; sin transcodificar ni copiar
el vídeo; sin código TikTok en `publishing`, `publications`, `scheduler`, `automation` ni núcleo
de Accounts; TikTok no importa `media_delivery`, Instagram ni Threads.

**Scale/Scope**: un usuario, una o pocas cuentas TikTok; cliente no auditado (`SELF_ONLY`, cuenta
privada, caps dinámicos de TikTok); vídeos ≤ 4 000 000 000 B y ≤ 600 s; 4 rutas nuevas, 1
componente nuevo, ampliación de `PublicationDetail`.

No queda ningún NEEDS CLARIFICATION. Lo que la documentación no garantiza (correspondencia
cuenta privada ↔ `privacy_level_options`, forma real del `upload_url`, semántica de
`uploaded_bytes`, tiempos reales de procesamiento, aceptación de toggles `false` explícitos y de
`is_aigc`) se confirma en el checkpoint **V1** de [quickstart.md](quickstart.md) con stop
conditions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias nuevas, sin media delivery, sin portada, sin modo auditado configurable, sin reanudación tras reinicio, sin caché de Creator Info. Dos extensiones neutrales mínimas del núcleo, ambas exigidas por la spec (FR-049, FR-057). Fuera de alcance respetado. | ✅ |
| II. Spec-Driven | Plan derivado de FR-001…FR-065 y de los ajustes aprobados (último chunk sin reenvío, interacciones `false`, toggles explícitos, huella criptográfica). | ✅ |
| III. Arquitectura modular | Lógica TikTok en `tiktok_gateway.py` (HTTP + clasificación), `tiktok_media.py` (reglas puras) y `tiktok_publishing.py` (publisher + router). Núcleo solo gana `ReconciledFailure` y `Publisher.arming_problems`, neutrales; tests de arquitectura ampliados. | ✅ |
| IV. Seguridad | Tokens solo vía Feature 012; `upload_url` en `UploadUrl` sin repr, nunca persistido, excepciones `from None`, redacción de logs ampliada; `publish_id` no expuesto; tests de secretos en DB, logs, API y navegador. API oficial de TikTok. | ✅ |
| V. Calidad | Tests offline de todos los grupos de FR-062; anti-duplicados probado por fase; ningún fallo silencioso (ambiguos visibles, consentimiento caducado visible). | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README y `docs/tiktok-publishing.md` (incluido el riesgo de intended use). | ✅ |
| Arquitectura base | Sin cloud nueva; SQLite local; scheduler local existente. | ✅ |

**Re-check post-diseño**: sin violaciones. Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/013-tiktok-direct-post/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks (no generado aún)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── models.py                 # TikTokPublicationOptions, TikTokPublishPhase, TikTokPublishRun
│   ├── schemas.py                # TikTokPublicationOptionsRead/Write, TikTokCreatorInfoRead,
│   │                             #   TikTokConsentWrite
│   ├── publishing.py             # ReconciledFailure, persist_reconciled_failure,
│   │                             #   Publisher.arming_problems (neutral)
│   ├── publications.py           # armado/creación consultan arming_problems (neutral)
│   ├── youtube_publishing.py     # arming_problems → []
│   ├── instagram_publishing.py   # arming_problems → []
│   ├── threads_publishing.py     # arming_problems → []
│   ├── tiktok_gateway.py         # + query_creator_info, init_video_post, upload_chunk,
│   │                             #   fetch_publish_status, UploadUrl, CreatorInfo,
│   │                             #   PublishStatus, nuevas excepciones y códigos
│   ├── tiktok_connections.py     # solo: redacción de URLs de subida en RedactTikTokSecrets
│   ├── tiktok_media.py           # NEW: caption + conteo UTF-16, plan_chunks, matriz de vídeo,
│   │                             #   reglas de opciones, post_info, declaración, huella, sha256
│   ├── tiktok_publishing.py      # NEW: TikTokPublisher, TikTokPublishSettings, router
│   │                             #   tiktok-options / tiktok-creator-info / tiktok-consent
│   └── main.py                   # registrar TikTokPublisher y su router
├── migrations/versions/
│   └── 0012_tiktok_publishing.py # NEW
└── tests/
    ├── fakes.py                  # FakeTikTok: creator_info, init, upload, status
    ├── conftest.py               # fixtures publicación TikTok (vídeo pequeño, opciones listas)
    ├── test_tiktok_caption.py    # NEW: caption + UTF-16 (casos compartidos con utils.test.ts)
    ├── test_tiktok_chunks.py     # NEW: plan_chunks (tabla + propiedades, sin archivos grandes)
    ├── test_tiktok_video_rules.py    # NEW: matriz de vídeo (FPS 22.99–60.01)
    ├── test_tiktok_option_rules.py   # NEW: mapeos de interacciones y toggles, declaraciones
    ├── test_tiktok_fingerprint.py    # NEW: huella, SHA-256 en streaming, digest incremental
    ├── test_tiktok_gateway_post.py   # NEW: DTOs, shapes, errores, UploadUrl
    ├── test_tiktok_errors.py     # NEW: tabla de taxonomía
    ├── test_tiktok_options.py    # NEW: GET/PUT, constraints
    ├── test_tiktok_consent.py    # NEW: consent API, invalidación
    ├── test_tiktok_creator_info.py   # NEW: endpoint de revisión
    ├── test_tiktok_caption_preview.py  # NEW: caption en opciones
    ├── test_tiktok_preflight.py  # NEW: check/prepare, digest, Creator Info cambiado
    ├── test_tiktok_publish.py    # NEW: un chunk, registro del publisher, polling, resultado
    ├── test_tiktok_anti_duplicates.py  # NEW: init≤1, publish_id antes del byte, write-ahead,
    │                             #   último chunk ≤1 (≠201 → solo estado), digest
    ├── test_tiktok_publish_secrets.py  # NEW: redacción + e2e de un chunk (pre-V1) + global
    ├── test_tiktok_upload_errors.py    # NEW: multi-chunk, 5xx retry, 400/403/404, 416, deadline
    ├── test_tiktok_reconcile.py  # NEW: COMPLETE/FAILED/processing; ReconciledFailure
    ├── test_tiktok_recovery.py   # NEW: reinicio en cada fase
    ├── test_tiktok_publish_errors.py   # NEW: taxonomía integrada con Feature 012
    ├── test_publish_arming.py    # NEW: hook neutral arming_problems
    ├── test_tiktok_scheduler.py  # NEW: armado, consentimiento, reintento 120 s, pausa, carreras
    ├── test_publish_reconcile.py # NEW: ReconciledFailure genérico con FakePublisher
    ├── test_migrations.py        # + 0012
    └── test_publications_states.py   # + arquitectura de los módulos nuevos

frontend/src/
├── types.ts                      # tipos TikTok; PUBLISHING_PLATFORMS + "tiktok"
├── api.ts                        # get/saveTikTokOptions, getTikTokCreatorInfo, confirmTikTokConsent
├── utils.ts                      # tiktokCaptionLength (+ utils.test.ts)
├── components/
│   ├── TikTokPublishOptions.tsx  # NEW (+ test)
│   ├── MediaPreview.tsx          # NEW: preview neutral extraído de ContentDetail
│   ├── ContentDetail.tsx         # usa MediaPreview (sin cambios visibles)
│   ├── PublishNowDialog.tsx      # declaración TikTok obligatoria en Publish now
│   ├── PublicationDetail.tsx     # monta el panel TikTok
│   └── PublicationAttempts.tsx   # textos de revisión manual / procesamiento TikTok
├── test-fake-api.ts              # endpoints nuevos
└── storage-safety.test.tsx       # + TikTok publishing

docs/tiktok-publishing.md         # NEW
README.md                         # sección Publishing to TikTok
```

**Structure Decision**: aplicación web existente (`backend/` + `frontend/`). TikTok sigue el
patrón de Instagram/Threads (gateway, reglas sin red, publisher + router de opciones) en módulos
propios; el núcleo solo recibe las dos extensiones neutrales listadas.

## Decisiones de diseño (resumen; detalle en research.md)

| Tema | Decisión | Ref. |
|---|---|---|
| Gateway | 4 métodos en `TikTokGateway`; único intérprete de códigos; `call_with_token` solo en lecturas (Creator Info, estado); `init` nunca repetido | §2 |
| Creator Info | DTO estricto; consultado al abrir/refrescar el panel y en `prepare`; no persistido; avatar solo presentación | §3 |
| Cliente no auditado | Constante documentada `CLIENT_AUDITED = False`; solo `SELF_ONLY`; aviso no bloqueante de cuenta pública; caps solo de TikTok | §4 |
| Opciones | Tabla propia; interacciones `false` por defecto; AIGC NULL = undecided; toggles comerciales siempre materializados; Branded + `SELF_ONLY` inválido | §5 |
| Huella | SHA-256 de JSON canónico con `open_id`, `Content.checksum`, caption, opciones, versión de declaración; digest real en streaming en `prepare`; en `upload`, hash incremental de los mismos bytes subidos con el último chunk leído antes del write-ahead (sin lectura extra) | §6 |
| Consentimiento inválido en publicación armada | No se desarma; `check()` sin red bloquea con `tiktok_consent_required` antes de cualquier efecto remoto; reconfirmar basta (sin reprogramar dentro de la ventana) | §20 |
| Caption | `description_with_hashtags` existente; unidades UTF-16 (`encode("utf-16-le")//2` / `s.length`); 2200 | §7 |
| Vídeo | Matriz: obligatorias (contenedor, tamaño, digest, ffprobe, stream, codec, dimensiones, duración); FPS si disponible; resto delegado | §8 |
| Chunks | ≤ 64 000 000 B → 1 chunk; si no `min(32 MiB, size//2)` y `floor`; ≤ 119 chunks | §9 |
| Subida | Buffer por chunk, hasheado; `UploadUrl` sin repr; redacción ampliada; deadline 50 min | §10 |
| Reintentos | Intermedios 3 (2/5/10 s); último chunk 0 (≠ `201` → solo estado del `publish_id`; `PROCESSING_UPLOAD` = ambiguo); init 0; Creator Info 1 | §11 |
| Consentimiento en `Publish now` | El diálogo muestra siempre la declaración y exige confirmarla; registra de nuevo el consentimiento (misma huella) antes del `POST publish` genérico | §21 |
| FPS | `22.99 <= fps <= 60.01`; TikTok autoridad final | §8 |
| `416` | Solo chunks intermedios: avanzar solo si la respuesta `bytes 0-{accepted}/{total}` trae `accepted == last + 1` y `total` esperado (la respuesta cuenta bytes; la petición usa `last` inclusivo); si no, determinado | §12 |
| Write-ahead | `enter_final_chunk()` + run `final_chunk`; tras `201` `enter_finalizing()` | §14 |
| Polling | 3 s, luego (3,5,5,10,10,15,15) y cada 30 s; 10 min; 429 duplica espera | §15 |
| Reconcile | `ReconciledFailure` neutral; solo estado del `publish_id` | §17 |
| Recovery | Genérico por etapa; sin reanudación | §18 |
| Errores | Tabla oficial → códigos `tiktok_*` | §19 |
| Scheduler | `Publisher.arming_problems` neutral; resto genérico | §20 |
| API/UI | 4 endpoints TikTok; botones genéricos; `publish_id` no expuesto | §21 |

## Orden de implementación (para `/speckit-tasks`)

### Bloque 1 — publisher VIDEO mínimo real (manual, un chunk)

1. **Foundation**: migración `0012`, modelos, esquemas, `TikTokPublishPhase`; registro de
   `TikTokPublisher` en `main.py`; tests de migración y arquitectura.
2. **Reglas sin red** (`tiktok_media.py`): caption + conteo UTF-16, `plan_chunks`, matriz de
   vídeo, reglas de opciones, mapeo `post_info` (interacciones y toggles), declaración, huella,
   SHA-256 en streaming. Tests unitarios completos (incluida la tabla de chunks).
3. **Gateway**: `query_creator_info`, `init_video_post`, `upload_chunk`,
   `fetch_publish_status`, `UploadUrl`, excepciones y clasificación; `FakeTikTok` ampliado;
   redacción de URLs de subida.
4. **API de opciones**: `GET/PUT tiktok-options`, `GET tiktok-creator-info`,
   `POST tiktok-consent`.
5. **Publisher mínimo**: `check`, `prepare`, `upload` (init → `publish_id` commit → chunks →
   verificación de digest → write-ahead → último chunk único → polling → resultado),
   `refresh_details`/`release` no-op, `reconcile` básico (solo éxito). Tests de un chunk,
   anti-duplicados (init ≤ 1, último chunk ≤ 1, write-ahead; digest distinto → sin write-ahead
   ni `PUT` final; una sola lectura del archivo durante la subida; último `PUT` ≠ `201` → solo
   estado), registro del publisher y **seguridad de extremo a extremo tras un publish de un
   chunk** (DB, respuestas de la API, logs capturados y mensajes de error sin `upload_url`,
   tokens, `Authorization` ni `publish_id` expuesto).
6. **Frontend mínimo**: componente neutral `MediaPreview` extraído de `ContentDetail`; panel
   TikTok con Creator Info, preview, caption y contador, privacidad sin default, interacciones,
   AIGC, declaración + consentimiento (disclosure visible en OFF); `Publish now` genérico cuyo
   diálogo muestra y exige la declaración TikTok.

> ### ⛔ STOP de `/speckit-implement` — Checkpoint V1
>
> Detener la implementación al terminar el Bloque 1 y ejecutar **V1** de
> [quickstart.md](quickstart.md) con un vídeo inocuo pequeño. Si algo contradice el diseño
> (stop conditions de V1), revisar spec/plan antes de continuar. Con V1 PASS, actualizar
> research.md con los valores confirmados y reanudar con el Bloque 2.

### Bloque 2 — capas avanzadas

7. **Multi-chunk y errores avanzados**: reintentos de chunks intermedios, `400/403/404/416`,
   deadline de 50 min, mensajes/taxonomía del último chunk (sin cambiar su semántica), mapeo completo de `fail_reason` y
   códigos (§19), integración de `scope_not_authorized`/`auth_removed` con la Feature 012.
8. **Reconciliación y recuperación**: `ReconciledFailure` + `persist_reconciled_failure` en el
   núcleo (con regresión YouTube/Instagram/Threads), `reconcile` TikTok completo, tests de
   reinicio en cada fase.
9. **Scheduler**: `Publisher.arming_problems` (neutral; `[]` en el resto), armado y creación con
   consentimiento, invalidación por edición (publicación armada con consentimiento `stale` →
   bloqueada por `check()` con 0 peticiones a TikTok y ejecutable tras reconfirmar sin
   reprogramar), Creator Info reconsultado al ejecutar, pausa,
   carreras, ciclos concurrentes, ambiguo sin reintento.
10. **Frontend completo**: disclosure (`Your brand` / `Branded content`, etiquetas, mensajes,
    bloqueo con `SELF_ONLY`), estado de consentimiento `stale`, avisos de cuenta pública y de
    procesamiento, textos de intentos ambiguos, `storage-safety`.
11. **Seguridad y regresión**: tests de secretos (`upload_url`, tokens, sin media delivery),
    arquitectura, suites de YouTube/Instagram/Threads/Feature 012.
12. **Documentación**: README, `docs/tiktok-publishing.md` (riesgo de intended use incluido).

> ### Checkpoint V2
>
> Ejecutar **V2** de [quickstart.md](quickstart.md); después, suite completa, lint, formato,
> type checking y build del frontend.

## Riesgos e incertidumbres

- **Cuenta privada ↔ opciones de Creator Info**: inferido de la documentación; V1 lo confirma.
- **`uploaded_bytes` "1-indexed"**: V2 lo observó como recuento de bytes (= total en
  `PROCESSING_UPLOAD`, ausente en `PUBLISH_COMPLETE`); sigue sin usarse para decidir.
- **`Content-Range` de la respuesta**: V2 confirmó que cuenta bytes aceptados (fin exclusivo),
  distinto de la petición (research §12).
- **Forma del `upload_url`**: host y parámetros reales desconocidos; la redacción se valida en V1.
- **MB vs MiB y "4 GB"**: se eligen valores válidos en ambas lecturas (puede rechazar vídeos entre
  4 000 000 000 B y 4 GiB).
- **"UTF-16 runes"**: interpretación conservadora; podría rechazar captions que TikTok aceptaría.
- **Tiempo de procesamiento**: sin máximo oficial; 10 min puede dejar ambiguos casos lentos
  (resolubles por reconciliación).
- **`Your brand` con `SELF_ONLY`**: la guía solo restringe Branded content; V2 lo confirma.
- **Caps dinámicos del cliente no auditado** (5 usuarios/24 h, ~15 posts/día): pueden interrumpir
  la validación; se respetan los códigos de TikTok.
- **Producto**: TikTok considera no aceptable para auditoría una utilidad para cuentas propias o
  del equipo; la publicación pública no está garantizada para AutoPublisher.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
