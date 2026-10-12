# Implementation Plan: Publicación real de imágenes y Reels en Instagram

**Branch**: `009-instagram-media-publishing` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-instagram-media-publishing/spec.md`

## Summary

Registrar un `InstagramPublisher` en el registro genérico de publishers para publicar
imágenes individuales (feed) y vídeos como Reels, con `Publish now` y con el scheduler
genérico, sin código de Instagram en el núcleo.

Como Instagram Login exige que Meta descargue el media desde una URL pública (la subida
reanudable sigue limitada a Facebook Login), se añade una abstracción **genérica**
`MediaDeliveryProvider` con una implementación **S3-compatible** (Cloudflare R2 recomendado):
bucket privado, objeto con clave aleatoria registrada en SQLite **antes** de subirlo y
accesible solo mediante una URL prefirmada que caduca sola (crash-safe por dos vías). La URL
es un secreto en memoria: viaja en el cuerpo del `POST` a Meta y nunca se guarda ni se
registra. Como red de seguridad adicional contra objetos privados huérfanos, la puesta en
marcha exige una regla de lifecycle nativa de R2 sobre el prefijo exclusivo de AutoPublisher.

Flujo: preflight (credencial e identidad de la Feature 008, cuota real de
`content_publishing_limit`, compatibilidad del media, caption, opciones, configuración,
estado del container anterior) → `PUBLISHING` → subida temporal → container → polling
acotado de `status_code` → write-ahead (`finalizing`) → `media_publish` → permalink →
`PUBLISHED` → **después** limpieza best-effort. Ante un `media_publish` no concluyente nunca
se repite: se lee el estado del container original (único mecanismo oficial de
correlación). Si figura `PUBLISHED`, la publicación queda `PUBLISHED` **sin identidad
remota** (sin media ID ni enlace inferidos, con el aviso `remote_identity_unavailable`), lo
que bloquea cualquier reintento; si no se puede demostrar el resultado, queda ambiguo con
revisión manual. Más tarde (tras un reinicio o al volver a la publicación), antes de exigir
`remote_check_required`, una reconciliación de solo lectura vuelve a leer el container y, si
confirma `PUBLISHED`, cierra la publicación como `PUBLISHED` sin pedir confirmación. Nunca se
identifica el post buscando publicaciones recientes. Imágenes PNG/WebP se convierten a JPEG en memoria sin
alterar la composición; los vídeos se validan con `ffprobe` y nunca se transcodifican.
Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring`, Pillow
(existentes). **Nueva**: `boto3` (cliente S3 para el proveedor de media delivery); dev:
`boto3-stubs[s3]` (mypy estricto). `ffprobe` (opcional del sistema, ya usado en Feature 003).

**Storage**: SQLite, migración `0008_instagram_publishing` (CHECK de `stage` ampliado;
tablas `instagram_publication_options`, `instagram_publish_runs`,
`temporary_media_objects`). Archivo local no versionado `backend/data/media-delivery.json`.
Keyring (servicio `autopublisher.instagram`) sin cambios. Bucket S3-compatible privado para
objetos efímeros.

**Testing**: pytest con `FakeMeta` ampliado (containers, estados, `media_publish`, cuota,
permalink, lista de medios, fallos e indeterminación), `FakeMediaDeliveryProvider` en
memoria (registra GET simulados, borrados y fallos), `InMemoryCredentialStore`,
`probe_video_streams` simulado y `sleep` instantáneo. Vitest + Testing Library con `FakeApi`.
Todo sin Internet, sin Meta real, sin keyring real y sin proveedor cloud.

**Target Platform**: aplicación local (Linux principal) con conexión saliente a Meta y al
proveedor S3.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: imagen publicada en < 1 min en condiciones normales; Reel limitado por
el procesamiento de Meta (timeout 10 min). Timeouts HTTP: 10 s lecturas, 60 s
creación de container y `media_publish`.

**Constraints**: media público solo vía URL prefirmada (TTL 1 h por defecto) y solo durante
la ejecución; cero secretos en SQLite/logs/frontend; sin transcodificación; `media_publish`
nunca se repite automáticamente; preflight sin efectos remotos de publicación ni de delivery.

**Scale/Scope**: un usuario, pocas cuentas; ≤ 50–100 posts/24 h por cuenta (cuota real de
Meta); 2 rutas nuevas, 1 componente nuevo y ampliaciones de 3 componentes.

Todas las incógnitas (endpoints, límites, `alt_text`, `is_ai_generated`, `share_to_feed`,
estados y polling, caducidad, cuota, semántica de `media_publish`, recuperación, requisitos
HTTP de Meta, proveedor, App Review) quedan resueltas en [research.md](research.md). No queda
ningún NEEDS CLARIFICATION. Lo que la documentación no garantiza (aceptación de URLs
prefirmadas, forma real de la cuota, `<IG_ID>`) se valida en el quickstart (paso 3).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin transcodificación, sin túneles ni servidores públicos, sin archivos derivados en disco (JPEG en memoria ≤ 8 MiB), sin resolución remota al arrancar, sin scheduler propio. Reutilización solo de containers `FINISHED` con la misma huella. Fuera de alcance respetado (carousel, Stories, tags, borrado remoto…). | ✅ |
| II. Spec-Driven | Plan derivado de FR-001…FR-071; decisiones de protocolo documentadas con fuentes en research. | ✅ |
| III. Arquitectura modular | Lógica de Instagram en `instagram_publishing.py`, `instagram_media.py` e `instagram_gateway.py`; media delivery genérico en `media_delivery.py` y concreto en `media_delivery_s3.py`. El núcleo solo gana conceptos neutrales (`processing`, `finalizing`, `release`, `attempt_id` del reporter). Tests de arquitectura ampliados. | ✅ |
| IV. Seguridad | Bucket privado + URL prefirmada tratada como secreto (memoria, cuerpo del POST, nunca persistida ni registrada); redacción de firmas S3 y de `image_url`/`video_url`; API oficial de Meta. **Credencial S3/R2**: se guarda en `backend/data/media-delivery.json`, el mismo modelo de configuración local del backend usado para el app secret de la Meta App (Feature 008); archivo fuera de Git (`.gitignore` específico `media-delivery*.json`) y nunca enviado al frontend; token con mínimo privilegio (*Object Read & Write* limitado al bucket/prefijo dedicado de AutoPublisher); nunca aparece en logs, API ni SQLite (tests de secretos). Mover la Secret Access Key al almacén seguro del sistema operativo queda como hardening futuro, no requisito de esta feature. | ✅ |
| V. Calidad | Tests de todos los casos de FR-070 con fakes; write-ahead y política anti-duplicados probados por fase; ningún fallo se pierde (ambiguos visibles, limpieza pendiente registrada). | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README y `docs/instagram-publishing.md`. | ✅ |
| Arquitectura base: "sin infraestructura cloud salvo requisito explícito" | **Desviación justificada**: el spec (FR-008, Assumptions) reconoce el requisito de Meta de una URL pública; se usa un almacenamiento de objetos efímero y privado, opcional (solo necesario para Instagram). Ver Complexity Tracking. | ⚠️ justificado |

**Re-check post-diseño**: sin violaciones nuevas. Las dos desviaciones (almacenamiento
externo y `boto3`) están justificadas abajo.

## Project Structure

### Documentation (this feature)

```text
specs/009-instagram-media-publishing/
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
├── pyproject.toml                    # + boto3; dev: boto3-stubs[s3]
├── app/
│   ├── config.py                     # + get_media_delivery_file()
│   ├── models.py                     # + AttemptStage.PROCESSING/FINALIZING, UNCERTAIN_STAGES,
│   │                                 #   InstagramPublicationOptions, InstagramPublishRun,
│   │                                 #   TemporaryMediaObject
│   ├── schemas.py                    # + InstagramPublicationOptionsRead/Write
│   ├── media.py                      # + probe_video_streams(), moov_before_mdat()
│   ├── publications.py               # + effective_metadata(), description_with_hashtags(),
│   │                                 #   ensure_not_publishing() (movidos, neutrales);
│   │                                 #   attempt_to_read: progress 1.0 solo si succeeded (≤ 0.99 si no)
│   ├── publishing.py                 # + stages processing/finalizing en reporter y recovery,
│   │                                 #   Publisher.release()/reconcile(), add_warnings(),
│   │                                 #   reconcile_uncertain(), persist_reconciled_success(),
│   │                                 #   mensajes neutrales
│   ├── media_delivery.py             # NEW: MediaDeliveryProvider, SecretUrl, config,
│   │                                 #   TemporaryMediaService (reserve/upload/url/release/sweep),
│   │                                 #   RedactMediaDeliverySecrets
│   ├── media_delivery_s3.py          # NEW: S3CompatibleProvider (boto3)
│   ├── instagram_media.py            # NEW: caption, política de imagen (JPEG en memoria),
│   │                                 #   validación de Reels; sin red
│   ├── instagram_gateway.py          # + create_container, container_status, publish,
│   │                                 #   media_permalink, publishing_limit,
│   │                                 #   MetaPublishRejected(code, subcode)
│   ├── instagram_publishing.py       # NEW: router de opciones, InstagramPublisher,
│   │                                 #   InstagramPublishSettings, runs
│   ├── instagram_connections.py      # disconnect usa ensure_not_publishing
│   ├── youtube_publishing.py         # usa los helpers movidos; release() no-op
│   ├── youtube_connections.py        # importa ensure_not_publishing desde publications
│   └── main.py                       # + media delivery, InstagramPublisher, sweep al arrancar,
│                                     #   media_delivery_provider/instagram_publish_settings
│                                     #   inyectables
├── migrations/versions/
│   └── 0008_instagram_publishing.py
└── tests/
    ├── fakes.py                      # FakeMeta ampliado, FakeMediaDeliveryProvider,
    │                                 #   FakePublisher.release
    ├── conftest.py                   # fixtures: instagram_publication, media_delivery_file, …
    ├── test_publications_states.py   # arquitectura: núcleo sin app.instagram_*, media_delivery_s3, boto3
    ├── test_media_delivery.py        # reserve-before-upload, release, sweep, config, redacción
    ├── test_media_delivery_s3.py     # provider con cliente S3 simulado (sin red)
    ├── test_instagram_media.py       # caption, imágenes (JPEG/PNG/WebP/transparencia/aspect/CMYK), Reels
    ├── test_instagram_options.py     # API de opciones, aplicabilidad, editabilidad
    ├── test_instagram_gateway_publish.py # endpoints de publicación, parsing, clasificación de errores
    ├── test_instagram_preflight.py   # cada condición sin efectos remotos; cuota; already_published
    ├── test_instagram_publish.py     # imagen y Reel end-to-end; polling; permalink; reutilización
    ├── test_instagram_ambiguity.py   # media_publish no concluyente, PUBLISHED sin identidad, sin repetición ni búsqueda heurística
    ├── test_instagram_reconcile.py   # reconciliación antes de remote_check_required (PUBLISHED / no concluyente)
    ├── test_instagram_errors.py      # cada código de ejecución, Reconnect required vs temporales
    ├── test_instagram_recovery.py    # reinicio en cada fase; barrido de objetos
    ├── test_instagram_cleanup.py     # orden éxito → cleanup; fallo de cleanup no cambia estados
    ├── test_instagram_scheduler.py   # scheduled, pausa, manual vs scheduler, concurrencia
    ├── test_instagram_publish_secrets.py  # sin token/URL firmada/credenciales en DB, logs, API
    ├── test_publish_upload.py        # regresión YouTube: progress 1.0 solo al terminar con éxito
    └── test_migrations.py            # 0008 upgrade/downgrade (abort si hay fases nuevas)

frontend/src/
├── types.ts                          # + AttemptStage processing/finalizing; InstagramPublicationOptions
├── api.ts                            # + getInstagramOptions / saveInstagramOptions
├── test-fake-api.ts                  # + soporte de opciones Instagram y etapas nuevas
├── utils.ts                          # + platformName(), attemptPhaseLabel()
├── components/
│   ├── InstagramPublishOptions.tsx   # NEW: tipo, caption exacto, AI, share_to_feed, alt text, problemas
│   ├── InstagramPublishOptions.test.tsx # NEW
│   ├── PublicationDetail.tsx         # monta el panel si platform === "instagram"; publishable por plataforma
│   ├── PublicationAttempts.tsx       # "Open on {platform}", fases sin % fuera de uploading, avisos
│   ├── PublicationAttempts.test.tsx  # NEW: enlaces por plataforma, fases, avisos, sin enlace si no hay URL
│   └── PublicationQueue.tsx          # ídem en la fila

docs/instagram-publishing.md          # NEW: R2/S3, lifecycle, opciones, ambiguos, App Review
README.md                             # + "Publishing to Instagram"
.gitignore                            # + media-delivery*.json
```

**Structure Decision**: misma estructura web y mismo patrón de "módulos por plataforma"
que YouTube. La entrega temporal de media es una capacidad genérica separada para que el
núcleo y otras plataformas futuras no dependan de Instagram ni de S3.

## Diseño por capas

### Núcleo genérico (`publishing.py`) — cambios mínimos y neutrales

- `ProgressReporter` gana `attempt_id` (propiedad), `enter_processing()` y
  `enter_finalizing() -> bool` (write-ahead: confirma la etapa y solo devuelve `True` si se
  guardó). `report_bytes` sigue pasando a `uploading`.
- `Publisher` gana `release(prepared, ctx, *, attempt_id, succeeded) -> list[dict]`
  (best-effort; avisos a añadir). `PublicationRunner._execute` lo llama **después** de
  `persist_success`/`persist_failure` (y después de `refresh_details`), captura cualquier
  excepción y guarda avisos con `add_warnings()`, que solo modifica `warnings`.
- `recover_interrupted_attempts` usa `UNCERTAIN_STAGES`; mensajes neutrales ("may have
  published this content").
- Excepción inesperada en el hilo: determinado si la etapa no es incierta (igual que hoy).
- `PublishOutcome.external_id`/`external_url` pasan a `str | None` para representar una
  publicación confirmada sin identidad remota (research §11.5); `persist_success` los guarda
  tal cual (las columnas ya son anulables) y nunca se inventan.
- `Publisher.reconcile(session, publication, attempt, ctx) -> Reconciliation | None`
  (research §11b): `reconcile_uncertain()` lo invoca en `get_publish_check` y en
  `start_publication` **antes** de `requires_remote_check`, solo si la publicación está
  `failed` y su último intento es ambiguo. Con una `Reconciliation`, `persist_reconciled_success`
  aplica en una transacción con UPDATE condicional la transición genérica nueva
  `failed → published` (intento `failed` ambiguo → `succeeded` determinado). Sin ella, nada
  cambia y sigue `remote_check_required`. El núcleo no importa Instagram.
- `attempt_to_read` (publications.py): `progress = 1.0` solo si el intento está `succeeded`;
  si no, `min(ratio, 0.99)`. Neutral para todas las plataformas.
- YouTube: `release` no-op y `reconcile` devuelve `None`; comportamiento sin cambios (siempre
  informa ID y URL; `progress = 1.0` al terminar con éxito).

### `media_delivery.py` (genérico, sin Instagram)

- `MediaDeliveryConfig` + `load_media_delivery_config(path)` → `MediaDeliveryNotConfigured`.
- `MediaDeliveryProvider` (Protocol), `SecretUrl` (`reveal()`, `repr` oculto),
  `MediaDeliveryFailed`.
- `TemporaryMediaService(session_factory, provider_factory)`: `reserve` (commit previo),
  `upload` (3 intentos), `public_url`, `release`, `sweep` (objetos con `deleted_at IS NULL` e
  intento no `running`).
- `RedactMediaDeliverySecrets` instalado en `HTTP_LOGGERS` y en `botocore`/`boto3`/`urllib3`
  (nivel WARNING).
- `key_prefix` validado como prefijo exclusivo (no vacío, termina en `/`, sin `..` ni `/`
  inicial); todas las claves se generan bajo él.

### Lifecycle nativo de R2 (red de seguridad obligatoria en la puesta en marcha)

- Regla del bucket sobre el prefijo exclusivo `key_prefix` (`autopublisher-tmp/`):
  *Delete objects* tras **1 día** (granularidad mínima de R2) y abortar subidas multiparte
  incompletas tras 1 día. Tiempo máximo documentado de un objeto huérfano: **~48 h** (1 día
  + hasta ~24 h de retraso de R2).
- Solo protege contra objetos **privados** huérfanos que sobrevivan a `release` y al barrido.
  No sustituye la limpieza inmediata y no controla cuándo deja de ser pública la URL: eso lo
  hace la caducidad independiente de la URL prefirmada (TTL 1 h por defecto).
- Prefijo exclusivo para no afectar a otros objetos; se recomienda un bucket dedicado.
- Configuración: panel de Cloudflare (*Settings → Object lifecycle rules*) o la API S3 con
  credenciales de administración (JSON en research §17). AutoPublisher no la lee (su token es
  solo *Object Read & Write*); se documenta en `docs/instagram-publishing.md` y se verifica en
  el quickstart (paso 1).

### `media_delivery_s3.py`

- `S3CompatibleProvider(config)`: `boto3.client("s3", endpoint_url, region_name,
  aws_access_key_id, aws_secret_access_key, config=Config(signature_version="s3v4"))`;
  `put` con `upload_fileobj` (callback de progreso, `ContentType`); `signed_get_url` con
  `generate_presigned_url("get_object", ExpiresIn=ttl)`; `delete` con `delete_object`
  (idempotente). Errores de `botocore` → `MediaDeliveryFailed` sin mensaje original (puede
  contener URLs).

### `instagram_media.py` (puro, sin red)

- `build_caption(publication, content)`, `caption_problems(caption)`.
- `prepare_image(path, media_format) -> PreparedImage(bytes | path, size, converted)` y
  `image_problems(...)` según research §2.
- `reel_problems(path, size, streams)` según research §3.
- `fingerprint(...)`.

### `instagram_gateway.py` (ampliado)

Métodos de publicación (research §1) que reutilizan `_send` y `GRAPH_API_VERSION`;
`MetaPublishRejected(code, subcode)` para 4xx con error Graph; timeouts largos para creación
y `media_publish`. Clasificación de research §18.

### `instagram_publishing.py`

- Rutas `GET/PUT /api/publications/{id}/instagram-options` (contrato).
- `InstagramPublisher(gateway, credential_store, media_delivery, settings)`:
  - `check`: tipo de media, archivo, compatibilidad local, caption, opciones, configuración
    de delivery, conexión (sin red).
  - `prepare` (preflight con lecturas permitidas): `verify_identity` (Feature 008: credencial,
    identidad, Professional), cuota, último run (`instagram_already_published` / reutilización),
    construcción del payload (JPEG en memoria si procede) y `submitted`.
  - `upload`: crea el run; si no reutiliza → `reserve` + subida (progreso real) + URL
    prefirmada → `enter_processing` → crear container (persistir ID) → polling → write-ahead
    (`phase=publishing`, `enter_finalizing`) → `media_publish` → política de research §11 →
    permalink → `PublishOutcome`. Ante un resultado no concluyente solo lee el
    `status_code` del container original: `PUBLISHED` → `PublishOutcome` sin identidad remota
    + aviso `remote_identity_unavailable`; cualquier otro estado (incluidos `ERROR`/`EXPIRED`) o fallo de consulta → `instagram_publish_uncertain`
    (ambiguo). No consulta publicaciones recientes. Credencial invalidada →
    `mark_reconnect_required`.
  - `release`: borra el objeto temporal del intento y barre pendientes; devuelve
    `temporary_media_cleanup_failed` si falla.
  - `refresh_details`: reintento best-effort del permalink.
  - `reconcile`: si el último run alcanzó `publishing`/`verifying_result` con `container_id`,
    una lectura de `status_code`; `PUBLISHED` → `Reconciliation(publish_started_at,
    PublishOutcome(None, None, [remote_identity_unavailable]))` y run `succeeded`; cualquier
    otro resultado → `None`. Nunca `media_publish`, nunca containers, nunca lista de posts.
  - Cualquier `PublishFailure` terminal deja el run en fase `failed`.

### Frontend

- `InstagramPublishOptions`: tipo (`Image Post`/`Reel`), caption exacto con contadores,
  `AI-generated` (Yes/No obligatorio), `Share to feed` (solo Reel, default activado y
  explicado), `Alt text` (solo imagen, contador 1000), problemas de compatibilidad y de
  configuración; deshabilitado si no es editable.
- `PublicationDetail`: `publishable` para `youtube` e `instagram`; monta el panel de
  Instagram solo en cuentas Instagram.
- `PublicationAttempts`/`PublicationQueue`: `Open on Instagram`/`Open on YouTube` según
  `attempt.platform`; etiquetas de fase; porcentaje solo en `uploading` (≤ 99 % mientras
  corre); avisos, incluido el de limpieza. Sin `external_url` no se muestra enlace; con el
  aviso `remote_identity_unavailable` se muestra "Published on Instagram — open your profile
  to find it" con cuenta, hora y caption.

## Riesgos y validaciones bloqueantes

| Riesgo | Mitigación |
|---|---|
| Meta no acepta URLs prefirmadas (p. ej. hace `HEAD`) | Quickstart paso 3; contingencia: bucket público por dominio propio con claves aleatorias y borrado inmediato (research §17-B), sin cambiar la abstracción. |
| `media_publish` sin idempotencia documentada | Write-ahead + nunca repetir + comprobación de solo lectura del container + reconciliación de solo lectura antes de `remote_check_required` (research §11b) + bloqueo `instagram_already_published` en el preflight como defensa en profundidad. |
| Meta no relaciona oficialmente container y media ID | Si solo el container confirma `PUBLISHED`: `PUBLISHED` sin identidad remota y aviso `remote_identity_unavailable`; nunca búsqueda heurística de posts. |
| Objetos privados huérfanos en el bucket | Clave persistida antes de subir + `release` + barrido; red de seguridad obligatoria: lifecycle de R2 sobre el prefijo exclusivo (≤ ~48 h). |
| Cuota documentada de forma contradictoria (50 vs 100) | Se usa solo el valor de Meta; si no se puede leer, Meta rechaza de forma determinada. |
| `<IG_ID>` incorrecto para publicar | Quickstart paso 3; el error sería un rechazo determinado antes de publicar. |
| Requisitos de Reel no verificables (closed GOP, edit lists) | Container `ERROR` → fallo determinado sin publicar. |
| App Review para publicar con la cuenta tester | Quickstart paso 9: documentar y detener. |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Almacenamiento de objetos externo (infraestructura cloud) | Con Instagram Login, Meta solo acepta media desde una URL pública (`image_url`/`video_url`); la subida local está limitada a Facebook Login. | Túnel con nombre o Funnel exponen un servidor local y dependen de un daemon (menos fiable para publicaciones desatendidas); Quick Tunnels están documentados solo para desarrollo; bucket público expone el archivo sin caducidad automática. El bucket privado con URL prefirmada es lo mínimo que cumple el requisito de Meta, y solo se usa para Instagram. |
| Dependencia `boto3` | Firma SigV4 de URLs prefirmadas y subida S3, código sensible para la seguridad. | Implementar SigV4 a mano con `httpx2`: más código propio y más riesgo de errores de firma o de fuga en un área de seguridad; Cloudflare documenta `boto3` para R2. |
| Dos etapas genéricas nuevas (`processing`, `finalizing`), `Publisher.release`, `Publisher.reconcile` y la transición `failed → published` solo por reconciliación confirmada | Recuperación sin duplicados y limpieza posterior al éxito sin acoplar el núcleo a Instagram. | Reutilizar `final_chunk` para `media_publish` mezclaría semánticas de YouTube; limpiar dentro de `upload` violaría el orden "persistir éxito → limpiar" (FR-056). |
