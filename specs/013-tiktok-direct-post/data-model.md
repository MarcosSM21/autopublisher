# Data Model: TikTok Publisher & Direct Post

**Feature**: `013-tiktok-direct-post` | **Migración**: `0012_tiktok_publishing`

Sin cambios en `publications`, `contents`, `publication_attempts` ni `tiktok_connections`.
Dos tablas nuevas, específicas de TikTok, con el patrón de Instagram/Threads (FK `RESTRICT`,
sin relación inversa desde `Publication`).

## `tiktok_publication_options`

Opciones TikTok de una publicación. **Sin fila = valores iniciales** (se crea al primer `PUT`).

| Columna | Tipo | Nulo | Defecto | Notas |
|---|---|---|---|---|
| `publication_id` | INTEGER PK, FK `publications.id` RESTRICT | no | — | |
| `privacy_level` | VARCHAR(32) | sí | NULL | NULL = sin elegir (sin default, FR-014) |
| `allow_comment` | BOOLEAN | no | `0` | control positivo; `false` válido |
| `allow_duet` | BOOLEAN | no | `0` | |
| `allow_stitch` | BOOLEAN | no | `0` | |
| `commercial_disclosure_enabled` | BOOLEAN | no | `0` | |
| `brand_organic_toggle` | BOOLEAN | no | `0` | "Your brand" |
| `brand_content_toggle` | BOOLEAN | no | `0` | "Branded content" |
| `is_aigc` | BOOLEAN | sí | NULL | NULL = `undecided`; publicar exige `true`/`false` |
| `consent_fingerprint` | VARCHAR(64) | sí | NULL | SHA-256 hex de la huella (research §6) |
| `consent_declaration_version` | VARCHAR(40) | sí | NULL | p. ej. `music-usage-2026-10-14` |
| `consented_at` | DATETIME (UTC) | sí | NULL | |
| `updated_at` | DATETIME (UTC) | no | — | |

Constraints:

- `privacy_valid`: `privacy_level IS NULL OR privacy_level IN ('PUBLIC_TO_EVERYONE',
  'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')`.
- `brand_toggles_need_disclosure`: `commercial_disclosure_enabled = 1 OR
  (brand_organic_toggle = 0 AND brand_content_toggle = 0)`.
- `branded_not_private`: `NOT (brand_content_toggle = 1 AND privacy_level = 'SELF_ONLY')`.
- `consent_complete`: `(consent_fingerprint IS NULL) = (consent_declaration_version IS NULL) AND
  (consent_fingerprint IS NULL) = (consented_at IS NULL)`.

Validación adicional (API / reglas sin red, no CHECK porque son estados intermedios de edición):

- disclosure ON sin ningún toggle → guardable, **no publicable** (`tiktok_disclosure_incomplete`).
- privacidad distinta de `SELF_ONLY` con el cliente no auditado → guardable si viene de Creator
  Info, **no publicable** (`tiktok_privacy_not_allowed`). (La UI no la permite elegir.)

Estados derivados (no persistidos):

- **Opciones completas**: `privacy_level` elegido y permitido, `is_aigc` no NULL, disclosure
  válido (OFF, o ON con ≥ 1 toggle) y compatible con la privacidad.
- **Consentimiento vigente**: `consent_fingerprint == huella_actual(...)` y
  `consent_declaration_version == versión que corresponde a los toggles actuales`.
  Cualquier cambio de los insumos (research §6) lo vuelve **caducado** sin escribir nada.
- **Editable**: solo con la publicación en `UNSCHEDULED`, `SCHEDULED` o `FAILED` (igual que el
  resto de metadata); en `PUBLISHING`/`PUBLISHED` → 409.

## `tiktok_publish_runs`

Estado remoto de TikTok de un intento. **Nunca** contiene `upload_url`, tokens ni respuestas
crudas.

| Columna | Tipo | Nulo | Notas |
|---|---|---|---|
| `attempt_id` | INTEGER PK, FK `publication_attempts.id` RESTRICT | no | 1:1 con el intento |
| `publication_id` | INTEGER FK `publications.id` RESTRICT | no | índice |
| `phase` | VARCHAR(20) | no | ver transiciones |
| `publish_id` | VARCHAR(64) UNIQUE | sí | committed antes del primer byte |
| `video_size` | INTEGER | no | bytes |
| `chunk_size` | INTEGER | no | |
| `total_chunk_count` | INTEGER | no | 1–1000 (en la práctica ≤ 119) |
| `confirmed_bytes` | INTEGER | no | bytes aceptados por TikTok (`206`/`201`/`416` §12) |
| `remote_uploaded_bytes` | INTEGER | sí | último `uploaded_bytes` leído (diagnóstico) |
| `initialized_at` | DATETIME | sí | respuesta de `init` recibida |
| `final_chunk_started_at` | DATETIME | sí | **write-ahead** del último chunk |
| `final_chunk_http_status` | INTEGER | sí | código HTTP del último `PUT` (solo diagnóstico; nunca decide; NULL si no hubo respuesta) |
| `last_remote_status` | VARCHAR(32) | sí | `PROCESSING_UPLOAD`, `PUBLISH_COMPLETE`, `FAILED` o `UNEXPECTED` |
| `fail_reason` | VARCHAR(64) | sí | solo `^[a-z_]{1,64}$`, si no `unknown` |
| `last_log_id` | VARCHAR(64) | sí | `log_id` seguro de TikTok (soporte) |
| `last_status_at` | DATETIME | sí | |
| `created_at` | DATETIME | no | |
| `updated_at` | DATETIME | no | |

Constraints: `phase IN ('preparing','initializing','uploading','final_chunk','processing',
'succeeded','failed')`; `confirmed_bytes BETWEEN 0 AND video_size`; `total_chunk_count BETWEEN 1
AND 1000`; `final_chunk_started_at IS NULL OR publish_id IS NOT NULL`. Índice
`ix_tiktok_publish_runs_publication_id`.

### Transiciones de `phase`

```
preparing ──init──▶ initializing ──publish_id committed──▶ uploading
uploading ──write-ahead (genérico FINAL_CHUNK + run)──▶ final_chunk
final_chunk ──cualquier resultado del único PUT (201, 4xx, 5xx, red, timeout)──▶ processing (polling)
processing ──PUBLISH_COMPLETE──▶ succeeded
processing ──FAILED──▶ failed (determinado)
processing ──timeout/inesperado──▶ failed (intento ambiguo; reconcile puede llevarlo a succeeded/failed)
preparing | initializing | uploading ──cualquier error──▶ failed (determinado)
```

Correspondencia con la etapa genérica de `PublicationAttempt`:

| `phase` TikTok | `AttemptStage` | ¿Incierta? |
|---|---|---|
| `preparing`, `initializing` | `preparing` | no |
| `uploading` | `uploading` | no |
| `final_chunk` | `final_chunk` | **sí** |
| `processing` | `finalizing` | **sí** |
| `succeeded` | `done` | — |

## Entidades existentes reutilizadas

- **`PublicationAttempt`**: `trigger`, `stage`, `bytes_sent`/`total_bytes` (= `video_size`),
  `submitted` (snapshot no sensible: caption, `post_info` sin token, plan de chunks, resumen de
  Creator Info usado, `delegated_checks`, versión de declaración), `outcome_determined`,
  `external_id` (post ID público solo si TikTok lo devuelve; normalmente NULL), `external_url`
  (siempre NULL en esta versión), `warnings` (`tiktok_private_post_no_link`).
- **`Content`**: `checksum` (SHA-256 del archivo) como identidad criptográfica del vídeo; nunca se
  modifica.
- **`TikTokConnection`** (Feature 012): `open_id` para la huella; estado para reconexión.

## Valores en memoria (nunca persistidos)

- `UploadUrl` (secreto efímero), access token, Creator Info completo (solo un resumen en
  `submitted`), buffers de chunk.

## Reconciliación (núcleo, neutral)

Nuevo tipo `ReconciledFailure(code, message)`; `persist_reconciled_failure` actualiza solo
`publication_attempts.outcome_determined`, `error_code`, `error_message` (sin cambio de esquema).
