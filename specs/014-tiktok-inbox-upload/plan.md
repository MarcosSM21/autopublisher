# Implementation Plan: TikTok Upload to Inbox

**Branch**: `014-tiktok-inbox-upload` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/014-tiktok-inbox-upload/spec.md`

## Summary

Añadir a TikTok un segundo modo, **Upload to Inbox**, junto a Direct Post (Feature 013), dentro
del mismo `TikTokPublisher`: el usuario elige el modo por publicación (`DIRECT_POST` /
`INBOX_UPLOAD`, sin valor por defecto en las nuevas; las existentes migran a `DIRECT_POST`).
En Inbox, AutoPublisher llama una vez a `POST /v2/post/publish/inbox/video/init/` (solo
`source_info`, `FILE_UPLOAD`, scope `video.upload`), sube el vídeo con la **misma transferencia
de chunks de 013** (extraída a `tiktok_transfer.py` sin cambio de comportamiento), consulta el
estado de forma acotada y, al ver `SEND_TO_USER_INBOX`, cierra el intento como `succeeded` y deja
la publicación en el nuevo estado genérico neutral **`AWAITING_USER_ACTION`** ("Ready in
TikTok"), sin más polling. Un `Check status` manual (endpoint genérico nuevo, hook neutral
`Publisher.follow_up`) consulta el mismo `publish_id` una vez y lleva la publicación a
`PUBLISHED` o `FAILED` sin tocar el intento de entrega. El OAuth de 012 solicita los tres
scopes; `video.upload` es una capacidad adicional: sin ella solo Inbox queda no disponible.
Envío manual y programado con el scheduler genérico. Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 (frontend).

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, `httpx2`, `keyring` (existentes).
**Ninguna dependencia nueva**. `ffprobe` del sistema.

**Storage**: SQLite, migración `0013_tiktok_inbox_upload` (estado `awaiting_user_action` en
`publications`; `mode` en `tiktok_publication_options`; `mode`, `delivered`,
`delivered_to_inbox_at`, `user_published_at`, `public_post_count` en `tiktok_publish_runs`).
Keyring de TikTok sin cambio de formato.

**Testing**: pytest offline con `FakeTikTok` ampliado (inbox init, `SEND_TO_USER_INBOX`,
`spam_risk_too_many_pending_share`, scopes configurables), `FakeClock`, `sleep` instantáneo,
`InMemoryCredentialStore`; Vitest + Testing Library con `FakeApi`. Sin red real.

**Target Platform**: aplicación local (Linux) con salida a `open.tiktokapis.com` y al host de
subida de TikTok.

**Project Type**: aplicación web (backend FastAPI + frontend Vite).

**Performance Goals**: iguales a 013 (subida limitada por ancho de banda, buffer ≤ 64 MiB,
polling ≤ 10 min). `Check status`: una petición por clic.

**Constraints**: init Inbox ≤ 1 por intento y nunca `post_info`; último chunk exactamente una
vez tras el write-ahead; `upload_url` solo en memoria; nunca segundo `publish_id`, nunca
`video.list`, nunca polling tras `SEND_TO_USER_INBOX`; el intento de entrega nunca se reescribe;
sin código TikTok en `publishing`, `publications`, `scheduler`, `automation` ni núcleo de
Accounts; la ausencia de `video.upload` nunca produce `Reconnect required`.

**Scale/Scope**: un usuario, una o pocas cuentas TikTok; máx. 5 envíos pendientes/24 h impuesto
por TikTok; 2 endpoints nuevos (1 genérico, 1 TikTok), 1 componente nuevo, ampliación del panel
TikTok, del diálogo de publicación y de las etiquetas de estado.

No queda ningún NEEDS CLARIFICATION: la API oficial se reconfirmó (research §0). Lo que la
documentación no garantiza (cuenta pública con cliente no auditado, llegada real de la
notificación, apertura del editor, tiempos) se valida en **V1b** con stop conditions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin dependencias ni tablas nuevas; un publisher con dos modos; extracción de la transferencia en lugar de duplicarla; sin webhooks, sin `video.list`, sin contador local de pendientes. Fuera de alcance respetado. | ✅ |
| II. Spec-Driven | Derivado de FR-001…FR-043 y de las aclaraciones (Q1 `AWAITING_USER_ACTION`; scopes base vs. capacidad; modo sin default; intento de entrega inmutable). | ✅ |
| III. Arquitectura modular | Núcleo: solo el estado neutral, `PublishOutcome.awaiting_user_action`, `Reconciliation.published_at` opcional, `Publisher.follow_up` y el endpoint `check-status` — todos neutrales y aprobados por FR-002/FR-019a. Lógica TikTok en `tiktok_transfer.py`, `tiktok_publishing.py`, `tiktok_inbox.py`. Tests de arquitectura ampliados. | ✅ |
| IV. Seguridad | `upload_url`/tokens con las garantías de 013; `publish_id` no expuesto; sin respuestas crudas; tests de secretos para Inbox; API oficial. | ✅ |
| V. Calidad | Tests offline por grupo de FR-043; equivalencia de Direct Post antes de añadir Inbox; regresión de todas las plataformas al cambiar el núcleo. Ningún fallo silencioso: estados visibles, errores seguros. | ✅ |
| VI. Git y trazabilidad | Commits pequeños en inglés; README y `docs/tiktok-publishing.md` actualizados. | ✅ |
| Arquitectura base | SQLite local, scheduler local existente, sin cloud. | ✅ |

**Re-check post-diseño**: sin violaciones. La ampliación del núcleo está aprobada por la spec y
es neutral (ninguna referencia a TikTok). Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/014-tiktok-inbox-upload/
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
│   ├── models.py                 # PublicationStatus.AWAITING_USER_ACTION + CHECKs;
│   │                             #   TikTokMode; TikTokPublicationOptions.mode;
│   │                             #   TikTokPublishRun.mode/delivered/... ; phase DELIVERED
│   ├── schemas.py                # mode en options R/W; modes; TikTokDeliveryRead;
│   │                             #   CheckStatusRead; capabilities en permisos
│   ├── publishing.py             # PublishOutcome.awaiting_user_action; persist_success y
│   │                             #   persist_reconciled_success; Publisher.follow_up;
│   │                             #   UserActionCompleted/Failed; follow_up_publication;
│   │                             #   POST /publications/{id}/check-status (neutral)
│   ├── publications.py           # ensure_editable/cancel/orden/cola con el nuevo estado
│   ├── youtube_publishing.py     # follow_up → None
│   ├── instagram_publishing.py   # follow_up → None
│   ├── threads_publishing.py     # follow_up → None
│   ├── tiktok_oauth.py           # BASE_SCOPES, UPLOAD_SCOPE, REQUESTED_SCOPES, KNOWN_SCOPES
│   ├── tiktok_gateway.py         # init_inbox_video; has_requested_scopes/can_upload_to_inbox;
│   │                             #   spam_risk_too_many_pending_share; KNOWN_SCOPES en ScopeMissing
│   ├── tiktok_connections.py     # callback exige los tres; capabilities; mensajes
│   ├── tiktok_transfer.py        # NEW: FileUploadTransfer (extraído de tiktok_publishing)
│   ├── tiktok_publishing.py      # despacho por modo; Direct Post sobre la transferencia;
│   │                             #   modo en options/check/arming; follow_up delega en inbox
│   ├── tiktok_inbox.py           # NEW: intérprete Inbox, mapeo de errores, follow_up,
│   │                             #   GET /publications/{id}/tiktok-delivery
│   └── main.py                   # registrar el router de tiktok_inbox
├── migrations/versions/
│   └── 0013_tiktok_inbox_upload.py   # NEW
└── tests/
    ├── fakes.py                  # FakeTikTok: inbox init, SEND_TO_USER_INBOX, pending share, scopes
    ├── test_tiktok_scopes.py     # NEW: base vs requested vs capability; reconnect parcial
    │                             #   conserva la conexión; refresh pierde video.upload
    ├── test_tiktok_mode.py       # NEW: migración (existentes DIRECT_POST, sin default),
    │                             #   mode obligatorio en check/arming/diálogo
    ├── test_awaiting_user_action.py  # NEW (núcleo, FakePublisher): transiciones, bloqueo de
    │                             #   acciones, scheduler/recovery lo ignoran, intento inmutable
    ├── test_tiktok_inbox_publish.py  # NEW: init único sin post_info, un chunk, polling se
    │                             #   detiene en SEND_TO_USER_INBOX, PUBLISH_COMPLETE temprano, FAILED
    ├── test_tiktok_inbox_check_status.py  # NEW: awaiting/published/failed/temporal/otra cuenta
    ├── test_tiktok_inbox_errors.py   # NEW: pending share, scope video.upload sin reconnect, taxonomía
    ├── test_tiktok_inbox_recovery.py # NEW: reinicio por fase, reconcile → delivered, sin reenvío
    ├── test_tiktok_inbox_scheduler.py # NEW: programado, pausa, carreras, no re-ejecución
    ├── test_tiktok_inbox_secrets.py  # NEW: sin upload_url/tokens/publish_id en DB, logs, API
    ├── test_migrations.py        # + 0013 (upgrade/downgrade, datos existentes)
    └── test_publications_states.py   # + arquitectura de tiktok_transfer/tiktok_inbox

frontend/src/
├── types.ts                      # awaiting_user_action; TikTokMode; TikTokDelivery; capabilities
├── api.ts                        # getTikTokDelivery, checkPublicationStatus
├── utils.ts                      # publicationStatusLabel (+ test)
├── components/
│   ├── TikTokPublishOptions.tsx  # selector de modo; vista Inbox
│   ├── TikTokInboxDelivery.tsx   # NEW: estados de entrega + Check status (+ test)
│   ├── PublishNowDialog.tsx      # variante Inbox (sin declaración Direct Post)
│   ├── PublicationDetail.tsx     # botones Send to TikTok / nota de Schedule; monta la entrega
│   ├── PublicationQueue.tsx      # nuevo estado en la cola
│   ├── PublicationAttempts.tsx   # "Delivered to TikTok inbox" vs estado final
│   └── TikTokConnectionPanel.tsx # capacidad Inbox + Reconnect
├── test-fake-api.ts              # endpoints nuevos
└── storage-safety.test.tsx       # + Inbox

docs/tiktok-publishing.md         # sección Upload to Inbox
docs/tiktok-accounts.md           # tres scopes, capacidad, Reconnect
README.md                         # dos modos de TikTok
```

**Structure Decision**: aplicación web existente. La transferencia común se extrae a un módulo
TikTok neutral entre modos; la semántica Inbox tiene módulo propio; el núcleo solo gana las
extensiones neutrales aprobadas.

## Decisiones de diseño (resumen; detalle en research.md)

| Tema | Decisión | Ref. |
|---|---|---|
| API oficial | Init Inbox solo `source_info`; 6/min; status con `video.upload` o `video.publish` | §0 |
| Arquitectura | Un publisher, modo congelado en payload y run; `tiktok_transfer.py` + `tiktok_inbox.py` | §1 |
| Scopes | `BASE_SCOPES` (renovación, conexión utilizable), `REQUESTED_SCOPES` (authorize + callback), capacidad `inbox_upload`; callback parcial falla sin tocar la conexión previa | §2 |
| Modo | Columna nullable sin default; migración existentes → `DIRECT_POST` (+ filas para publicaciones sin opciones); `tiktok_mode_required` | §3 |
| Transferencia | Extracción sin cambios; tests de Direct Post como prueba de equivalencia | §4 |
| Preflight Inbox | Conexión + capacidad + vídeo (sin Creator Info ni consentimiento); digest en `prepare` | §5 |
| Estado genérico | `AWAITING_USER_ACTION`; `PublishOutcome.awaiting_user_action`; `Publisher.follow_up`; transiciones condicionales sin tocar el intento | §6 |
| Identidad remota | Nunca `external_id`; solo `public_post_count` diagnóstico | §7 |
| Check status | `POST /check-status` genérico; una lectura; temporales → 503 sin cambio | §8 |
| Errores | `tiktok_too_many_pending_shares`, `tiktok_upload_permission_missing` (sin reconnect) | §9 |
| Persistencia | `tiktok_publish_runs` + `mode`, fase `delivered`, timestamps | §10 |
| Recuperación | Genérica; Ready in TikTok no es `RUNNING`; nunca reenvío | §11 |
| UI | Selector de modo, Send to TikTok, `TikTokInboxDelivery`, etiquetas | §12 |
| Validación | V1a scopes, V1b inbox con cuenta pública, V2 final | §13 |

## Orden de implementación (para `/speckit-tasks`)

### Bloque 1 — mínimo real (V1 temprano)

1. **Scopes** (`tiktok_oauth`, `tiktok_gateway`, `tiktok_connections`): constantes separadas,
   callback con tres scopes, renovación con base, capacidad en la lectura de conexión, mensajes.
   Tests `test_tiktok_scopes.py` + regresión de `test_tiktok_connect`/`test_tiktok_tokens`.

> **⛔ STOP — V1a** ([quickstart.md](quickstart.md)): Reconnect real y tres scopes. Si TikTok no
> concede `video.upload`, detener.

2. **Foundation**: migración `0013` (estado genérico, `mode` en opciones y runs, columnas Inbox),
   modelos, esquemas; `test_migrations` con datos existentes (DIRECT_POST, filas insertadas, sin
   default en nuevas) y downgrade que **falla explícitamente** si hay publicaciones en
   `awaiting_user_action` (nunca las remapea). Tests del modo antes de implementarlo.
3. **Núcleo neutral mínimo**: `AWAITING_USER_ACTION` en `models`/`publications`
   (editable/cancel/cola) y `PublishOutcome.awaiting_user_action` en `persist_success`;
   `follow_up` en el protocolo (`None` en YouTube/Instagram/Threads). Tests del núcleo con
   `FakePublisher` (sin TikTok).
4. **Extracción de la transferencia** a `tiktok_transfer.py`; los tests de Direct Post existentes
   pasan sin modificarse (salvo fixtures de opciones que ahora necesitan `mode`).
5. **Inbox mínimo**: `init_inbox_video` en el gateway; modo en opciones (`PUT` con `mode`);
   `check`/`prepare` Inbox; intérprete Inbox (`SEND_TO_USER_INBOX` → outcome awaiting;
   `PUBLISH_COMPLETE`; `FAILED`); run con `mode`/`delivered`. Tests de un chunk, init único sin
   `post_info`, polling detenido, anti-duplicados básicos y secretos de extremo a extremo.
6. **Frontend mínimo**: selector de modo, vista Inbox del panel, Send to TikTok, diálogo Inbox,
   etiqueta de estado "Ready in TikTok" con la instrucción.

> ### ⛔ STOP de `/speckit-implement` — Checkpoint V1b
>
> Ejecutar **V1b** de [quickstart.md](quickstart.md) con la cuenta **pública**. Responder
> explícitamente si Upload to Inbox funciona con la cuenta pública y el cliente Sandbox/no
> auditado. Si TikTok exige cuenta privada, audit o algo inesperado: STOP y revisar spec/plan.
> Con PASS, anotar los valores reales en research.md y seguir con el Bloque 2.

### Bloque 2 — capas completas

7. **Check status**: `follow_up_publication` + `POST /check-status` (núcleo) y `follow_up` TikTok;
   `GET /tiktok-delivery`; tests de todos los resultados y de intento inmutable.
8. **Errores**: `spam_risk_too_many_pending_share`, `scope_not_authorized` de `video.upload` sin
   reconnect, mensajes Inbox, `fail_reason` tras la entrega.
9. **Reconciliación y recuperación**: `Reconciliation.published_at` opcional y
   `persist_reconciled_success` hacia `AWAITING_USER_ACTION`; reconcile Inbox; reinicio en cada
   fase; Ready in TikTok tras reinicio sin consultas.
10. **Multi-chunk** Inbox (reutilizando la transferencia) y tests de `416`/`5xx`/URL caducada en
    modo Inbox.
11. **Scheduler**: `arming_problems` por modo (modo requerido; Inbox sin consentimiento; capacidad),
    programado, pausa, carreras, no re-ejecución desde `AWAITING_USER_ACTION`.
12. **Frontend completo**: `TikTokInboxDelivery` con Check status, historial (entrega vs estado
    final), cola, panel de conexión con capacidad, nota de Schedule, `storage-safety`.
13. **Seguridad y regresión**: secretos Inbox; arquitectura; suites de YouTube, Instagram,
    Threads, conexión TikTok y Direct Post (cambia el núcleo).
14. **Documentación**: README, `docs/tiktok-publishing.md`, `docs/tiktok-accounts.md`.

> ### Checkpoint V2
>
> Ejecutar **V2** de [quickstart.md](quickstart.md); después, quality gates completos una vez.

## Riesgos e incertidumbres

- **Cuenta pública con cliente no auditado**: no documentado para Upload; V1b decide.
- **Publicación atascada en `AWAITING_USER_ACTION`** si TikTok nunca sale de
  `SEND_TO_USER_INBOX` (borrador descartado): **limitación aceptada** (spec, Edge Cases y
  Assumptions); sin salida manual local, puede bloquear contenido/cuenta; ninguna acción local
  elimina el pending share remoto. Una salida segura queda para una feature posterior.
- **`published_at`** = momento de observación del `PUBLISH_COMPLETE`.
- **Límite de 5 envíos pendientes/24 h**: puede frenar la validación real; los borradores de
  prueba deben resolverse en TikTok.
- **Regresión de Direct Post** exige poner la cuenta en privado temporalmente (restricción de
  013 para clientes no auditados).
- **Extracción de la transferencia**: riesgo de cambio sutil en Direct Post; mitigado ejecutando
  las suites de 013 antes de añadir Inbox.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
