# Data Model: Publicación real de imágenes y Reels en Instagram

**Feature**: `009-instagram-media-publishing` | **Fecha**: 2026-10-08

Migración nueva: **`0008_instagram_publishing`**. `Publication`, `Account` y
`InstagramConnection` no reciben columnas nuevas. Ninguna tabla guarda tokens, credenciales
del proveedor ni URLs firmadas.

---

## 1. `PublicationAttempt` (existente, Feature 006/007) — cambios genéricos

| Cambio | Detalle |
|---|---|
| `stage` | CHECK ampliado a `('preparing', 'uploading', 'processing', 'finalizing', 'final_chunk', 'done')` (recreación de tabla en batch, como en `0005`). |
| Sin columnas nuevas | El aviso de limpieza usa la columna `warnings` existente. |
| `progress` (derivado, API) | `1.0` solo si `status = succeeded`; en otro caso `min(bytes_sent / total_bytes, 0.99)` (neutral, todas las plataformas). |

```python
class AttemptStage(StrEnum):
    PREPARING = "preparing"
    UPLOADING = "uploading"
    PROCESSING = "processing"   # NEW: the platform processes a prepared item; nothing is public
    FINALIZING = "finalizing"   # NEW: committed before the irreversible publishing call
    FINAL_CHUNK = "final_chunk" # YouTube: committed before the last upload request
    DONE = "done"

UNCERTAIN_STAGES = frozenset({AttemptStage.FINAL_CHUNK, AttemptStage.FINALIZING})
```

Transiciones de `stage` (todas confirmadas en SQLite antes de seguir):

```text
preparing ──► uploading ──► processing ──► finalizing ──► done (succeeded)
     │            │              │              │
     └────────────┴──────────────┴──► failed (determined)
                                                └──► failed (determined | ambiguous, research §11)
```

Instagram con container reutilizado: `preparing → finalizing → done`.

Recuperación al arrancar (sin red): todo intento `running` → `failed`, `error_code =
interrupted`, `outcome_determined = stage NOT IN UNCERTAIN_STAGES`.

**Reconciliación de un intento ambiguo** (research §11b, FR-046a): transición genérica
nueva, aplicada solo cuando el publisher confirma la publicación en solo lectura y mediante
UPDATE condicional en una única transacción:

```text
PublicationAttempt: failed (outcome_determined = false) ──► succeeded (outcome_determined = true,
                    error_code/error_message = NULL, stage = done, external_id/url = NULL para Instagram,
                    warnings += remote_identity_unavailable)
Publication:        failed ──► published (published_at = publish_started_at del run)
```

Si la plataforma no confirma `PUBLISHED` (cualquier otro estado, incluidos `ERROR`/`EXPIRED`,
o un fallo de consulta), nada cambia (sigue ambiguo y `remote_check_required`); la misma
regla se aplica durante la ejecución tras un `media_publish` no concluyente.
`published_at` reconciliado = `publish_started_at`, valor **aproximado** documentado.

`submitted` (snapshot no sensible) para Instagram:

```json
{
  "media_kind": "image",
  "caption": "...",
  "is_ai_generated": false,
  "alt_text": "...",
  "share_to_feed": null,
  "instagram_user_id": "1784...",
  "username": "cyber.studio",
  "file_name": "poster.png",
  "file_size": 2310000,
  "delivered_format": "jpeg",
  "delivered_size": 1840000,
  "converted": true,
  "container_reused": false,
  "quota_checked": true
}
```

`external_id` = Instagram media ID; `external_url` = permalink (o URL del perfil si no pudo
obtenerse, con aviso `permalink_unavailable`). `details` puede incluir `permalink` refinado y
`media_product_type`.

**Publicación confirmada sin identidad remota** (research §11.5): si `media_publish` no fue
concluyente pero el container original figura como `PUBLISHED`, el intento queda
`succeeded`, `outcome_determined = true`, con `external_id = NULL` y `external_url = NULL`
(nunca se infiere ni inventa un ID o enlace), y la publicación `PUBLISHED` (por tanto no
elegible para ningún reintento). Las columnas ya son anulables y no hay CHECK que lo impida;
solo cambia el tipo de `PublishOutcome` (`external_id`/`external_url: str | None`).

Avisos (`warnings`) nuevos: `temporary_media_cleanup_failed`, `permalink_unavailable`,
`remote_identity_unavailable`.

---

## 2. `InstagramPublicationOptions` (nueva tabla `instagram_publication_options`)

Opciones solo de Instagram; mismo patrón que `youtube_publication_options`. Sin fila =
valores por defecto (no declarados).

| Campo | Tipo | Regla |
|---|---|---|
| `publication_id` | int, PK, FK → `publications.id` (RESTRICT) | una fila por publicación |
| `is_ai_generated` | bool, NULL | NULL = no declarado → bloquea publicar (`instagram_options_incomplete`) |
| `share_to_feed` | bool, NOT NULL, default `true` | solo se aplica a Reels; se ignora en imágenes |
| `alt_text` | String(1000), NULL | solo imágenes; `strip()`; vacío → NULL; ≤ 1000 caracteres |
| `updated_at` | datetime UTC | |

CHECK: `alt_text IS NULL OR length(alt_text) <= 1000`.

Edición: igual que la metadata común (`ensure_editable`): permitida en `unscheduled`,
`scheduled` y `failed`; rechazada en `publishing`, `published` y `cancelled`.

---

## 3. `TemporaryMediaObject` (nueva tabla genérica `temporary_media_objects`)

Registro de cada objeto subido al proveedor de media delivery. Independiente de Instagram
(`media_delivery.py`).

| Campo | Tipo | Regla |
|---|---|---|
| `id` | int PK | |
| `provider` | String(40) | p. ej. `s3_compatible` |
| `object_key` | String(255), UNIQUE | `<prefijo><uuid4hex>/<uuid4hex>.<ext>`; aleatorio, sin rutas ni nombres locales; no da acceso sin firma; siempre bajo el prefijo exclusivo cubierto por la regla de lifecycle del bucket (research §16.3) |
| `attempt_id` | int, FK → `publication_attempts.id` (RESTRICT) | intento que lo creó |
| `content_type` | String(50) | `image/jpeg`, `video/mp4`, `video/quicktime` |
| `size_bytes` | int ≥ 0 | |
| `created_at` | datetime UTC | **commit antes de subir** (crash-safe, research §16) |
| `uploaded_at` | datetime, NULL | al terminar la subida |
| `deleted_at` | datetime, NULL | al confirmar el borrado |
| `cleanup_failures` | int ≥ 0, default 0 | |
| `last_cleanup_at` | datetime, NULL | último intento de borrado |

Índice: `ix_temporary_media_objects_pending` sobre `deleted_at` (barrido).

Estados derivados:

```text
reserved (uploaded_at NULL) ──► uploaded ──► deleted (deleted_at set)
     │                              │
     └──────────────┬───────────────┘
                    ▼
     pending cleanup (deleted_at NULL, attempt not running) ──sweep──► deleted
```

Nunca se guarda la URL prefirmada. Las filas `deleted` se conservan como historial no
sensible (tamaño mínimo).

---

## 4. `InstagramPublishRun` (nueva tabla `instagram_publish_runs`)

Estado remoto de Instagram por intento, para recuperación sin duplicados (FR-041, FR-051).

| Campo | Tipo | Regla |
|---|---|---|
| `attempt_id` | int, PK, FK → `publication_attempts.id` (RESTRICT) | uno por intento Instagram |
| `publication_id` | int, FK → `publications.id` (RESTRICT) | para buscar el último run |
| `media_kind` | String(10) | `image` \| `reel` |
| `fingerprint` | String(64) | SHA-256 de checksum + tipo + caption + opciones (research §12) |
| `phase` | String(30) | ver máquina de estados |
| `container_id` | String(64), NULL | se guarda inmediatamente tras crearlo |
| `container_created_at` | datetime, NULL | para la ventana de 23 h |
| `container_status` | String(20), NULL | último `status_code` leído |
| `reused_from_attempt_id` | int, NULL | si reutiliza el container de otro intento |
| `publish_started_at` | datetime, NULL | instante del write-ahead; solo diagnóstico y ayuda para la revisión manual (nunca para identificar el post automáticamente) |
| `updated_at` | datetime UTC | |

CHECK: `phase IN ('preparing', 'delivering_media', 'creating_container',
'processing_container', 'publishing', 'verifying_result', 'succeeded', 'failed')`,
`media_kind IN ('image', 'reel')`.

Índice: `(publication_id, container_created_at)`.

Máquina de estados:

```text
preparing ─► delivering_media ─► creating_container ─► processing_container ─► publishing ─► verifying_result ─► succeeded
    │               │                    │                      │                   │
    └───────────────┴────────────────────┴──────────────────────┴───────────────────┴─► failed
(reutilización: preparing ─► publishing ...)

publishing / verifying_result / failed ──(reconciliación: container original = PUBLISHED)──► succeeded
```

Reglas:

- `creating_container` se confirma **antes** de llamar a Meta; `container_id` y
  `container_created_at`, **inmediatamente después** de la respuesta. Una caída entre ambos
  deja un container huérfano sin publicar que caduca en 24 h (sin efecto público).
- `publishing` + `publish_started_at` se confirman **antes** que la etapa genérica
  `finalizing`, y ambas antes de `media_publish`.
- Tras un reinicio la fila puede quedar en una fase intermedia: es solo informativa; el
  intento genérico ya está cerrado y el siguiente preflight consulta Meta (research §12).
- **Reconciliación** (research §11b): tras un resultado ambiguo el run normalmente queda en
  `failed` (o en `publishing`/`verifying_result` si hubo un reinicio). Una reconciliación
  positiva lo pasa a `succeeded`, **solo** si el intento genérico sigue ambiguo
  (`failed` + `outcome_determined = false`) y el container original confirma `PUBLISHED`.
  Cualquier otro resultado no cambia la fase.

---

## 5. Entidades derivadas (no persistidas)

- **Caption de Instagram**: `description_with_hashtags(effective_description,
  effective_hashtags)`; límites 2200 caracteres / 30 hashtags / 20 menciones.
- **Media kind**: `image` si `Content.media_type == image`; `reel` si `video`.
- **Entrega preparada** (`InstagramPayload`, en memoria): `account_id`, `instagram_user_id`,
  `media_kind`, `fingerprint`, caption y opciones, origen de los bytes (ruta del original o
  JPEG derivado en memoria), `content_type`, tamaño y, si procede, el `container_id`
  reutilizable.
- **`SecretUrl`**: URL prefirmada en memoria, `repr`/`str` ocultos; solo se expone con
  `.reveal()` en la llamada al gateway.
- **`MediaDeliveryConfig`**: archivo local `media-delivery.json` (research §17); el secreto del
  proveedor no se guarda en SQLite.

---

## 6. Relaciones

```text
Publication 1 ── 0..1 InstagramPublicationOptions
Publication 1 ── * PublicationAttempt 1 ── 0..1 InstagramPublishRun
                              PublicationAttempt 1 ── * TemporaryMediaObject
Account 1 ── 0..1 InstagramConnection (Feature 008; credencial e identidad)
```

`Publication` no tiene relaciones ORM hacia las tablas de Instagram ni hacia
`temporary_media_objects` (aislamiento del núcleo).

---

## 7. Migración `0008_instagram_publishing`: upgrade y downgrade

**Upgrade** (en este orden): recrear `publication_attempts` en batch con el CHECK de `stage`
ampliado; crear `instagram_publication_options`, `temporary_media_objects` e
`instagram_publish_runs` con sus constraints e índices.

**Downgrade** (inequívoco, sin mapeos silenciosos):

1. **Antes de modificar el esquema**, comprobar
   `SELECT COUNT(*) FROM publication_attempts WHERE stage IN ('processing', 'finalizing')`.
   Si es > 0, abortar con un error claro (`RuntimeError`: "Cannot downgrade: N publication
   attempts use the stages 'processing'/'finalizing' introduced by 0008.") sin tocar nada.
   Nunca se convierten esas fases a otro valor.
2. Si es 0: eliminar `instagram_publish_runs`, `temporary_media_objects` e
   `instagram_publication_options` (orden inverso de dependencias) y recrear
   `publication_attempts` en batch con el CHECK original
   `('preparing', 'uploading', 'final_chunk', 'done')`.
