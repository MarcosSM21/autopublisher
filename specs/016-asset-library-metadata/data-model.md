# Data Model: Asset Library, Usage & Metadata

**Feature**: [spec.md](spec.md) · **Research**: [research.md](research.md)

Sin entidades nuevas. Se amplía `Content` y se añaden conceptos derivados no persistidos.

## Content (`contents`, existente — ampliado en migración `0015`)

Campos nuevos:

| Campo | Tipo | Nulo | Notas |
|---|---|---|---|
| `metadata_status` | `String(10)` | no | `unknown` \| `clean` \| `sanitized`; `server_default='unknown'` (filas existentes incluidas) |
| `sanitized_storage_path` | `String(255)` | sí | relativo a la raíz de media, `projects/{project_id}/{uuid}.clean{ext}`; `UNIQUE`; nunca expuesto por la API |
| `sanitized_checksum` | `String(64)` | sí | SHA-256 hex de la copia |
| `sanitized_size_bytes` | `Integer` | sí | |
| `sanitized_at` | `UTCDateTime` | sí | |

Restricciones (`CHECK`):

- `metadata_status IN ('unknown','clean','sanitized')`.
- `(metadata_status = 'sanitized') = (sanitized_storage_path IS NOT NULL AND
  sanitized_checksum IS NOT NULL AND sanitized_size_bytes IS NOT NULL AND
  sanitized_at IS NOT NULL)` y, cuando no es `sanitized`, los cuatro son `NULL`
  (expresado como dos CHECK: "sanitized ⇒ todos no nulos" y "no sanitized ⇒ todos nulos").

Campos existentes que **no cambian** nunca por esta feature: `storage_path`, `checksum`,
`size_bytes` (identidad del original inmutable), `width`, `height`, `duration_seconds`.

La migración `0015` usa `batch_alter_table` (SQLite). Downgrade: elimina las columnas; las
copias `.clean` quedan huérfanas en disco y el barrido no existe en esa versión (documentado
en la migración; el downgrade no borra archivos).

### Transiciones de `metadata_status`

```text
unknown ──Remove metadata (salida == original)──────────────▶ clean
unknown ──Remove metadata (salida ≠ original)───────────────▶ sanitized
sanitized ──Remove metadata con copia OK (verify)───────────▶ sanitized (sin trabajo)
sanitized ──Remove metadata con copia ausente/corrupta──────▶ sanitized (copia regenerada, ruta nueva)
clean ──Remove metadata──────────────────────────────────────▶ clean (sin trabajo; el original es inmutable)
```

No hay transición de vuelta a `unknown` ni a "original" desde `sanitized`.

Reglas:

- Rechazada (`409 content_publishing`) si alguna `Publication` del contenido está
  `publishing`; rechazada (`409 metadata_removal_in_progress`) si ya hay una sanitización en
  curso del mismo contenido.
- Fallo creando la copia → estado sin cambios, temporal borrado, original intacto.
- UPDATE de confirmación condicional al estado leído al empezar y a `NOT EXISTS`
  publicación `publishing` del contenido.

## Archivo efectivo (concepto, no persistido)

`EffectiveFile(path, checksum, size, clean_copy)` devuelto por
`resolve_publish_file(storage, content, verify)`:

| `metadata_status` | Archivo | checksum | size |
|---|---|---|---|
| `unknown`, `clean` | `storage_path` | `checksum` | `size_bytes` |
| `sanitized` | `sanitized_storage_path` | `sanitized_checksum` | `sanitized_size_bytes` |

Errores: `media_unavailable` (no existe / tamaño distinto) y `media_corrupt` (SHA distinto,
solo con `verify=True` y copia limpia). Nunca fallback al original con `sanitized`.

Expresión SQL equivalente usada en el claim:
`CASE WHEN metadata_status = 'sanitized' THEN sanitized_checksum ELSE checksum END`.

## PreparedPublication (dataclass del core, existente — +1 campo)

| Campo | Tipo | Notas |
|---|---|---|
| `file_checksum` | `str \| None = None` | checksum efectivo resuelto en `prepare()`; obligatorio si la publicación tiene contenido; el claim exige que siga siendo el efectivo |

## PublishContext (dataclass del core, existente — +1 campo)

| Campo | Tipo | Notas |
|---|---|---|
| `file_guard` | `ContentFileGuard` (default nuevo) | misma instancia que usa `Remove metadata` (`app.state.content_file_guard`) |

## ContentFileGuard (solo memoria)

- `threading.Lock` + `set[int]` de `content_id` en sanitización.
- `begin_sanitizing(content_id, check)` / `end_sanitizing(content_id)` (context manager).
- `claiming(content_id)` (context manager): mantiene el lock durante el UPDATE+commit del
  claim; si el id está en sanitización lanza `ConflictError("content_metadata_busy")`.
- Se pierde al reiniciar (correcto: una sanitización no sobrevive a un reinicio; el barrido
  limpia `.clean` huérfanos y `prepare()` de storage limpia `tmp/`).

## Resumen de uso (concepto, no persistido)

`ContentUsage` por contenido (listado y detalle):

| Campo | Derivación |
|---|---|
| `used` | `published_count + awaiting_count > 0` |
| `publication_count` | todas las publicaciones del contenido |
| `published_count` | `status = 'published'` |
| `awaiting_count` | `status = 'awaiting_user_action'` |
| `scheduled_count` | `status = 'scheduled'` |
| `platforms` | plataformas distintas (orden alfabético) con `published`/`awaiting_user_action` |
| `last_published_at` | `MAX(published_at)` de `published` |

Historial (solo detalle), una fila por `Publication` del contenido: `publication_id`,
`platform`, `account_id`, `account_name`, `status`, `scheduled_at`, `published_at`,
`created_at`, `updated_at`, `uncertain` (último intento `needs_manual_review`), `external_url`
(si existe). Orden: `updated_at` descendente.

## Informe de inspección (concepto, no persistido)

```text
MetadataReport
  original: FileMetadataReport
  publish_copy: FileMetadataReport | null      # solo si metadata_status = sanitized
FileMetadataReport
  inspected: bool
  reason: str | null                           # p. ej. "ffprobe is not available"
  findings: [ { category, label, keys: [str] } ]
category ∈ location | device | software | dates | exif | xmp | iptc | comments
           | container | ai_generation | comfyui | other
```

`keys` contiene nombres de clave/campo (nunca valores).

## Publication / PublicationAttempt / Account (existentes, sin cambios de esquema)

Fuente del uso. Los intentos y su `submitted` histórico no se reescriben.
