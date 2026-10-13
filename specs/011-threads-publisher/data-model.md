# Data Model: Publicación real de texto, imagen y vídeo en Threads

**Feature**: `011-threads-publisher` | **Migración**: `0010_threads_publishing`

Cambios de persistencia: un cambio **neutral** en `publications` y dos tablas nuevas propias
de Threads. Ninguna tabla guarda tokens, URLs firmadas ni respuestas crudas de Meta.

---

## 1. `publications` (existente, cambio neutral)

| Campo | Cambio | Regla |
|---|---|---|
| `content_id` | `NOT NULL` → **anulable** | `NULL` solo si el publisher de la plataforma de la cuenta tiene `accepts_text_only` (hoy solo Threads). Validado en la creación (`text_publication_not_supported`) y en el preflight genérico (`publication_media_required`). |

- Sin columnas nuevas ni campos de Threads (FR-003). Sin discriminador: el tipo se deriva
  (research §3).
- `description_override` / `hashtags_override` son la **única** fuente del texto de una
  publicación sin `Content`; `title_override` no se usa.
- Índice parcial `uq_publications_active_content_account` sin cambios (en SQLite los `NULL`
  no colisionan: varias publicaciones de texto activas por cuenta son válidas).
- La migración recrea la tabla con `batch_alter_table` y vuelve a crear los índices parciales
  (`uq_publications_active_content_account`, con su `WHERE`), porque las reconstrucciones
  batch de SQLite no conservan el `WHERE` (precedente de `0008`). Se conservan todos los
  CHECK existentes.
- **Downgrade**: solo si no existe ninguna publicación con `content_id IS NULL`; si existe,
  aborta antes de tocar el esquema (nunca borra publicaciones ni inventa contenidos).

Efectos derivados (sin cambio de esquema):

- `effective_metadata(publication, content: Content | None)`: sin `Content`, los overrides o
  `None`/`[]`.
- `PublicationRead.content_id: int | None`, `content: PublicationContentSummary | None`.
- `requires_remote_check(session, publication)`: sin `Content`, mira el último intento de la
  propia publicación.

---

## 2. `ThreadsPublicationOptions` → tabla `threads_publication_options` (nueva)

Opciones solo de Threads; sin fila = valores por defecto (sin `alt_text`). `Publication` no
tiene relación de vuelta.

| Campo | Tipo | Regla |
|---|---|---|
| `publication_id` | int, PK, FK `publications.id` `RESTRICT` | Publicación de una cuenta Threads |
| `alt_text` | str(1000) \| NULL | `CHECK (alt_text IS NULL OR length(alt_text) <= 1000)`; solo imagen/vídeo; vacío → `NULL` |
| `updated_at` | datetime UTC | |

Validación (API): editable solo en `unscheduled`/`scheduled`/`failed` (`ensure_editable`
existente); `alt_text` en publicación de texto → `422 threads_option_not_applicable`; > 1000 →
`422 threads_alt_text_invalid`; cuenta no Threads → `409 platform_not_supported`.

---

## 3. `ThreadsPublishRun` → tabla `threads_publish_runs` (nueva)

Estado remoto de **un** intento Threads, para recuperación, reconciliación y diagnóstico. Se
crea con commit al empezar `upload()`.

| Campo | Tipo | Regla |
|---|---|---|
| `attempt_id` | int, PK, FK `publication_attempts.id` `RESTRICT` | 1:1 con el intento |
| `publication_id` | int, FK `publications.id` `RESTRICT` | |
| `media_kind` | str(10) | `CHECK IN ('text','image','video')` |
| `phase` | str(30) | `ThreadsPublishPhase` (abajo), `CHECK` |
| `container_id` | str(64) \| NULL | Persistido con commit **inmediatamente** tras crearlo |
| `container_created_at` | datetime \| NULL | Hora de creación (reloj del publisher), persistida con el `container_id`. Origen de la antigüedad mínima antes de `threads_publish` (≥ 30 s, research §10) y del timeout de procesamiento |
| `container_status` | str(20) \| NULL | Último estado leído (`IN_PROGRESS`, `FINISHED`, `PUBLISHED`, `ERROR`, `EXPIRED`) |
| `container_error` | str(40) \| NULL | `error_message` de Meta solo si es uno de los códigos documentados (research §10); nunca texto libre |
| `publish_started_at` | datetime \| NULL | Commit del write-ahead, justo antes de `threads_publish` |
| `updated_at` | datetime UTC | |

Índice: `(publication_id, container_created_at)` para la defensa entre intentos (research §11).

### `ThreadsPublishPhase` y transiciones

```text
preparing ─► delivering_media ─► creating_container ─► processing_container ─► publishing ─► verifying_result ─► succeeded
    │        (solo imagen/vídeo)      ▲ (texto salta aquí)          │                 │
    └────────────────────────────────┴───────── failed ◄───────────┴─────────────────┘
```

- `processing_container` incluye la espera hasta que el container esté `FINISHED` **y** tenga
  al menos 30 s desde `container_created_at`; un reinicio en esta fase es determinado.
- `publishing` solo se escribe (commit) **antes** de `threads_publish`, y después el stage
  genérico `finalizing`; si alguno falla, no se publica.
- `failed` lo escribe `upload()` ante cualquier excepción; tras un crash el run conserva su
  última fase y la recuperación genérica cierra el intento.
- `succeeded` se escribe tras obtener el resultado o en la reconciliación (`PUBLISHED`).
- Reconciliación admitida si `phase ∈ {publishing, verifying_result, failed}`,
  `container_id` y `publish_started_at` no son `NULL`.

---

## 4. Entidades existentes reutilizadas (sin cambio de esquema)

### `PublicationAttempt`

- `platform = 'threads'`; stages: texto `preparing → processing → finalizing → done`;
  imagen/vídeo `preparing → uploading → processing → finalizing → done`.
- `total_bytes`: tamaño de lo entregado (0 en texto).
- `submitted` (no sensible): `media_kind`, `text`, `alt_text`, `threads_user_id`, `username`,
  `file_name`/`file_size` (imagen/vídeo), `delivered_format`, `delivered_size`, `converted`,
  `quota_checked`, `quota_usage`/`quota_total`/`quota_duration` cuando se leyeron y, en
  vídeo, `delegated_checks` (requisitos no verificados localmente, delegados a Meta).
- `details`: `permalink`, `threads_timestamp`.
- `external_id` = Threads post ID (o `NULL` si solo el container confirmó la publicación);
  `external_url` = permalink oficial o `NULL` (también `NULL` si `threads_publish` devolvió
  el post ID pero el permalink no pudo obtenerse: el intento sigue `succeeded`).
- `warnings`: `remote_identity_unavailable`, `permalink_unavailable`, `quota_unavailable`,
  `temporary_media_cleanup_failed`.

### `TemporaryMediaObject`

Sin cambios; una fila por objeto entregado (imagen/vídeo), registrada antes de subir. Ninguna
para texto.

### `ThreadsConnection`

Sin cambios: fuente del Threads user ID, username y estado; `mark_reconnect_required` de la
Feature 010.

---

## 5. Valores derivados (no persistidos)

| Valor | Derivación |
|---|---|
| `ThreadsMediaKind` | `content_id IS NULL` → `text`; `Content.media_type` `image` → `image`; `video` → `video` |
| Texto final | `description_with_hashtags(descripción efectiva, hashtags efectivos)` |
| Longitud del texto | Conteo conservador de research §4 |
| Enlaces | URLs únicas `http(s)://…` o `www.…` |
| Media entregado | JPEG/PNG originales; WebP estático → PNG sin pérdida en memoria, validado como derivado (research §7); WebP animado → rechazo |

---

## 6. Migración `0010_threads_publishing`

1. `publications.content_id` anulable (batch, recreando índices parciales).
2. Crear `threads_publication_options`.
3. Crear `threads_publish_runs` con su índice.

Downgrade: aborta si hay publicaciones sin `Content`; si no, elimina las dos tablas y
restaura `NOT NULL`. Tests en `test_migrations.py` (upgrade desde `0009` con datos, downgrade
vacío, downgrade bloqueado).
