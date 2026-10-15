# Data Model: TikTok Upload to Inbox

**Feature**: `014-tiktok-inbox-upload` | **Migración**: `0013_tiktok_inbox_upload`

Cambios sobre el modelo de la Feature 013 ([data-model](../013-tiktok-direct-post/data-model.md)).
Sin tablas nuevas. Ningún campo de TikTok en `publications`; ningún cambio en
`publication_attempts` ni `tiktok_connections`.

## `publications` (núcleo) — nuevo estado genérico

`PublicationStatus` gana `AWAITING_USER_ACTION = "awaiting_user_action"` (backend
`app/models.py` y frontend `types.ts`, sincronizados).

CHECKs (recreados con `batch_alter_table(recreate="always")`, como 0005):

- `status_valid`: añade `'awaiting_user_action'`.
- `status_matches_schedule`: `status IN ('cancelled','publishing','published','failed',
  'awaiting_user_action') OR (scheduled AND scheduled_at NOT NULL) OR (unscheduled AND
  scheduled_at NULL)`.
- `published_at_matches_status` sin cambios (`AWAITING_USER_ACTION` ⇒ `published_at` NULL).
- `uq_publications_active_content_account` sin cambios: el nuevo estado **cuenta como activo**.
- `auto_publish_only_scheduled` sin cambios (el nuevo estado siempre está desarmado).

**Downgrade de `0013`**: si existe alguna publicación con `status = 'awaiting_user_action'`, el
downgrade DEBE fallar explícitamente (excepción con mensaje claro: cuántas publicaciones están
esperando acción en TikTok y que deben resolverse antes de bajar de versión). Nunca se mapean
silenciosamente a otro estado. Sin esas filas, el downgrade restaura el esquema de `0012`.

### Máquina de estados (añadidos en negrita)

```
UNSCHEDULED/SCHEDULED/FAILED ──start──▶ PUBLISHING
PUBLISHING ──outcome normal──▶ PUBLISHED
PUBLISHING ──outcome awaiting_user_action──▶ **AWAITING_USER_ACTION**
PUBLISHING ──failure──▶ FAILED
FAILED (ambiguo) ──reconcile: published──▶ PUBLISHED
FAILED (ambiguo) ──reconcile: awaiting──▶ **AWAITING_USER_ACTION**
**AWAITING_USER_ACTION ──follow_up: completed──▶ PUBLISHED**
**AWAITING_USER_ACTION ──follow_up: failed──▶ FAILED**
**AWAITING_USER_ACTION ──follow_up: still waiting / error──▶ AWAITING_USER_ACTION**
```

Reglas del estado: no elegible para publicar, no editable, no cancelable, no reprogramable, no
seleccionado por scheduler ni recuperación, no ocupa concurrencia. Transiciones de salida con
`UPDATE ... WHERE status = 'awaiting_user_action'` (idempotentes). **Nunca** cambian el
`PublicationAttempt`.

## `tiktok_publication_options` — modo

| Columna | Tipo | Nulo | Defecto | Notas |
|---|---|---|---|---|
| `mode` | VARCHAR(16) | sí | **ninguno** | `NULL` = sin decidir; `DIRECT_POST` / `INBOX_UPLOAD` |

- CHECK `mode_valid`: `mode IS NULL OR mode IN ('DIRECT_POST','INBOX_UPLOAD')`.
- Migración: filas existentes → `DIRECT_POST`; para cada publicación TikTok existente sin fila,
  se inserta una fila con los valores iniciales de 013 y `mode = 'DIRECT_POST'`.
- Filas nuevas (primer `PUT`) toman el `mode` del cuerpo (puede ser `NULL`). "Sin fila" sigue
  significando valores iniciales con `mode = NULL`.
- Las opciones de Direct Post se conservan aunque el modo sea `INBOX_UPLOAD` (no se borran al
  cambiar de modo) y solo se validan en modo `DIRECT_POST`.

Estado derivado "listo para publicar/armar":

- `mode NULL` → no listo (`tiktok_mode_required`).
- `DIRECT_POST` → reglas de 013 sin cambios.
- `INBOX_UPLOAD` → capacidad `inbox_upload` concedida + vídeo válido (sin opciones de post ni
  consentimiento de Direct Post).

## `tiktok_publish_runs` — generalizado a dos modos

| Columna | Tipo | Nulo | Notas |
|---|---|---|---|
| `mode` | VARCHAR(16) | no | **nueva**; existentes → `DIRECT_POST`; congelado al crear el run |
| `phase` | VARCHAR(20) | no | añade `delivered` |
| `delivered_to_inbox_at` | DATETIME | sí | **nueva**; primera observación de `SEND_TO_USER_INBOX` |
| `user_published_at` | DATETIME | sí | **nueva**; observación de `PUBLISH_COMPLETE` en Inbox |
| `public_post_count` | INTEGER | sí | **nueva**; nº de `publicaly_available_post_id` (diagnóstico, no autoritativo) |
| `last_remote_status` | VARCHAR(32) | sí | admite `SEND_TO_USER_INBOX` |
| resto | — | — | sin cambios (013) |

CHECKs nuevos:

- `mode_valid`: `mode IN ('DIRECT_POST','INBOX_UPLOAD')`.
- `phase_valid`: añade `'delivered'`.
- `delivered_only_inbox`: `(phase <> 'delivered' AND delivered_to_inbox_at IS NULL) OR mode =
  'INBOX_UPLOAD'`.
- `user_published_only_inbox`: `user_published_at IS NULL OR mode = 'INBOX_UPLOAD'`.
- `public_post_count IS NULL OR public_post_count >= 0`.

Nunca: `upload_url`, tokens, cabeceras, respuestas crudas, lista de post IDs.

### Transiciones de `phase` (Inbox)

```
preparing ─▶ initializing ─(publish_id committed)─▶ uploading ─(write-ahead)─▶ final_chunk
final_chunk ─(cualquier respuesta del único PUT)─▶ processing
processing ─SEND_TO_USER_INBOX─▶ delivered        (attempt succeeded; publicación AWAITING_USER_ACTION)
processing ─PUBLISH_COMPLETE─▶ succeeded          (attempt succeeded; publicación PUBLISHED)
processing ─FAILED─▶ failed                       (attempt failed determinado)
processing ─timeout/inesperado─▶ failed           (attempt ambiguo; reconcile → delivered/succeeded/failed)
delivered ─Check status: PUBLISH_COMPLETE─▶ succeeded (user_published_at; publicación PUBLISHED)
delivered ─Check status: FAILED─▶ failed          (fail_reason; publicación FAILED; attempt intacto)
delivered ─Check status: SEND_TO_USER_INBOX─▶ delivered (last_status_at actualizado)
preparing|initializing|uploading ─error─▶ failed  (determinado)
```

Correspondencia con `AttemptStage` igual que 013; `delivered` ↔ `done`.

## Vista derivada: estado de entrega Upload to Inbox (no persistida)

Valores de la API `tiktok-delivery`. La UI solo muestra como estado visible `Scheduled`,
`Uploading`, `Processing in TikTok`, `Ready in TikTok`, `Published` y `Failed`; `not_sent` es un
valor derivado de la API (no se ha enviado nada) y **no** es una etiqueta de estado de la UI.

| Estado UI | Condición |
|---|---|
| `scheduled` | publicación `SCHEDULED`, modo `INBOX_UPLOAD` |
| `uploading` | `PUBLISHING`, stage `preparing`/`uploading`/`final_chunk` |
| `processing` | `PUBLISHING`, stage `finalizing` |
| `ready` | `AWAITING_USER_ACTION` |
| `published` | `PUBLISHED` con último run Inbox |
| `failed` | `FAILED` (con `after_delivery = true` si el último intento está `succeeded`, es decir, TikTok informó del fallo tras la entrega) |
| `not_sent` | `UNSCHEDULED` sin intentos |

## Credencial TikTok (secreto, sin cambio de formato)

El JSON del almacén seguro ya guarda `scopes` y `scopes_source`. Derivados nuevos (no
persistidos): `has_requested_scopes()` (los tres), `has_required_scopes()` (base, sin cambios de
semántica), `can_upload_to_inbox()` (`video.upload` ∈ scopes).

## Entidades del núcleo: tipos nuevos (en memoria)

- `PublishOutcome.awaiting_user_action: bool = False`.
- `Reconciliation.published_at: datetime | None`.
- `UserActionCompleted(published_at: datetime)`, `UserActionFailed(code: str, message: str)`.
- `Publisher.follow_up(...) -> UserActionCompleted | UserActionFailed | None`.
