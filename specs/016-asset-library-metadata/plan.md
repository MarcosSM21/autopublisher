# Implementation Plan: Asset Library, Usage & Metadata

**Branch**: `016-asset-library-metadata` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/016-asset-library-metadata/spec.md`

## Summary

Presentar la biblioteca de contenidos como **Asset Library** (sin renombrar `Content`) con
uso derivado, búsqueda/filtros y un detalle con progressive disclosure, y añadir
**`Remove metadata`**: una copia sanitizada que pasa a ser el archivo publicado, con prioridad
absoluta en que el workflow de ComfyUI no sea recuperable.

Enfoque técnico (research.md):

- **Uso** (§1): dos consultas agregadas por proyecto (`GROUP BY content_id` + plataformas
  distintas) añadidas a `ContentRead.usage`; historial en `GET /contents/{id}/usage`. Nada
  persistido. Búsqueda/filtros en el cliente (§2).
- **Archivo efectivo** (§3): módulo neutral `content_files.py` con
  `resolve_publish_file(storage, content, verify)`; `verify=True` solo como último paso
  local de `prepare()` (justo antes del claim y la subida) hace SHA-256 completo de la copia
  limpia (FR-034); listados, detalle y checks usan solo existencia + tamaño. Los cinco publishers (YouTube, Instagram, Threads,
  Telegram, TikTok) dejan de leer `storage_path`/`checksum`/`size_bytes` directamente.
  Fingerprints de TikTok/Instagram con checksum efectivo → invalidación natural.
- **Carrera sanitización/publicación** (§4): `ContentFileGuard` en memoria (lock + conjunto
  de contenidos en sanitización) envolviendo el claim de `create_running_attempt`, más una
  condición SQL en el claim que exige que el checksum efectivo siga siendo el que `prepare()`
  resolvió (`PreparedPublication.file_checksum`). Dos códigos nuevos que el scheduler trata
  como "no reclamado".
- **Sanitizador de imágenes** (§7): parser propio por lista blanca para PNG/JPEG/WEBP, sin
  recompresión, copia literal de bloques permitidos, **en streaming** (memoria acotada, sin
  límite nuevo: aplica el global de 2 GiB), EXIF mínimo regenerado solo con
  `Orientation ≠ 1` en PNG/JPEG/WEBP (FR-025a). Salida idéntica si no hay nada que quitar
  (→ `clean`).
- **Sanitizador de vídeo** (§8, verificado con ffmpeg 6.1.1): `ffmpeg -map 0:V -map 0:a?
  -c copy -map_metadata -1 -map_metadata:s -1 -map_chapters -1 +bitexact [+faststart]`.
  ffmpeg solo es necesario para esta acción.
- **Persistencia** (§5): 5 columnas en `contents` (migración `0015`), copia en
  `projects/{id}/{uuid}.clean{ext}`, flujo temporal → `os.replace` → UPDATE condicional con
  compensación, barrido de `.clean` huérfanos al arrancar. Dedupe con `sanitized_checksum`
  (§6).
- **Inspección** (§9): bajo demanda, categorías + nombres de clave, nunca valores.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React 19 + Vite (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, Alembic, Pillow (existentes). Sin dependencias
Python nuevas. `ffmpeg`/`ffprobe` como binarios opcionales (ffmpeg requerido solo para
`Remove metadata` en vídeo; ffprobe ya era opcional).

**Storage**: SQLite (`contents` + 5 columnas); sistema de archivos local
(`media/projects/{id}/…`, `media/tmp/`)

**Testing**: pytest (tests dirigidos con archivos sintéticos generados en el test, centinelas
ComfyUI; vídeo con `skipif` si no hay ffmpeg); vitest + Testing Library para componentes

**Target Platform**: aplicación local de un usuario (Linux principal), un único proceso

**Project Type**: web application (backend + frontend)

**Performance Goals**: listado de cientos de assets sin degradación perceptible (2 consultas
extra por proyecto); sanitización de imagen < 1 s típico; vídeo limitado por E/S (stream
copy)

**Constraints**: original inmutable; nunca fallback al original con `sanitized`; nunca rutas
internas en la API; ninguna recompresión/recodificación; sin ExifTool en runtime

**Scale/Scope**: 1 usuario, cientos de assets por proyecto, archivos ≤ 2 GiB (límite
global de importación existente; los sanitizadores trabajan en streaming)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin entidad `Asset`, sin variantes, sin tabla nueva; filtros en cliente; parser propio pequeño en lugar de nuevas dependencias; fuera de alcance respetado (delete, thumbnails, resize, presets, republish). | ✅ |
| II. Spec-Driven | Plan derivado de spec + aclaraciones aprobadas (incluido FR-025a: EXIF mínimo de Orientation en PNG/JPEG/WEBP). | ✅ |
| III. Arquitectura modular | Resolvedor y guard en módulo neutral (`content_files.py`); el core no importa sanitizadores ni plataformas; cada publisher solo cambia su fuente de archivo. Cambio mínimo en el core justificado abajo. | ✅ (justificado) |
| IV. Seguridad | Objetivo de la feature: eliminar metadata privada; no se exponen rutas ni valores de metadata; logs sin metadata; archivos de prueba reales nunca versionados (tests generan sintéticos). | ✅ |
| V. Calidad | Tests de uso, resolvedor, sanitizadores con centinelas, carrera claim/sanitización, regresiones de publishers; fallo visible (`media_unavailable`/`media_corrupt`), nunca silencioso. | ✅ |
| VI. Git | Commits pequeños por bloque (migración+modelo, resolvedor+publishers, sanitizadores, API, frontend, docs). README/docs: ffmpeg y Remove metadata. | ✅ |

**Re-check post-diseño**: sin violaciones nuevas. El único punto que toca el núcleo de
publicación queda en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/016-asset-library-metadata/
├── plan.md              # Este archivo
├── research.md          # Fase 0
├── data-model.md        # Fase 1
├── quickstart.md        # Fase 1 (validación + V1 ComfyUI)
├── contracts/api.md     # Fase 1
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (no creado aquí)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── content_files.py        # NUEVO: EffectiveFile, resolve_publish_file, ContentFileGuard,
│   │                           #        sweep_orphan_clean_copies
│   ├── image_metadata.py       # NUEVO: walkers PNG/JPEG/WEBP, sanitize_image, inspect_image
│   ├── video_metadata.py       # NUEVO: sanitize_video (ffmpeg), inspect_video_metadata (ffprobe)
│   ├── asset_library.py        # NUEVO: agregado de uso, historial, inspect, remove-metadata
│   │                           #        (router /api/contents/{id}/usage|metadata|remove-metadata)
│   ├── models.py               # Content + 5 columnas, MetadataStatus
│   ├── schemas.py              # ContentRead + publish_file/usage; esquemas nuevos
│   ├── contents.py             # content_to_read con uso/publish_file; find_duplicate ampliado
│   ├── errors.py               # códigos de conflicto nuevos
│   ├── publishing.py           # PreparedPublication.file_checksum, PublishContext.file_guard,
│   │                           # condición + guard en create_running_attempt, _not_startable
│   ├── scheduler.py            # NOT_CLAIMED_CODES + 2 códigos
│   ├── main.py                 # guard en app.state, barrido al arrancar, router nuevo
│   ├── youtube_publishing.py   # → resolve_publish_file
│   ├── instagram_publishing.py # → resolve_publish_file (fingerprint efectivo)
│   ├── threads_publishing.py   # → resolve_publish_file
│   ├── telegram_publishing.py  # → resolve_publish_file
│   ├── tiktok_publishing.py    # → resolve_publish_file (consent, SHA, chunks, tamaño)
│   └── tiktok_media.py         # inspect_video recibe tamaño efectivo
├── migrations/versions/0015_content_metadata_sanitization.py
└── tests/
    ├── test_asset_usage.py
    ├── test_content_files.py
    ├── test_image_metadata.py
    ├── test_video_metadata.py          # skipif sin ffmpeg
    ├── test_remove_metadata_api.py
    ├── test_publish_effective_file.py  # carrera claim/sanitización + publishers con copia
    └── test_migrations.py              # ampliado

frontend/src/
├── types.ts, api.ts, test-fake-api.ts  # tipos y llamadas nuevas
├── components/ContentLibrary.tsx       # "Asset Library", búsqueda, filtros, tarjeta mínima
├── components/ContentDetail.tsx        # integra AssetUsage y AssetFile
├── components/AssetUsage.tsx (+test)  # NUEVO: historial de uso
├── components/AssetFile.tsx (+test)   # NUEVO: datos técnicos, estado, Inspect/Remove metadata
└── components/ProjectDetail.tsx        # etiqueta de la pestaña

.github/workflows/ci.yml                # instalar ffmpeg en el job backend
README.md / docs                        # ffmpeg opcional, Remove metadata, riesgos aceptados
```

**Structure Decision**: web application existente (`backend/` + `frontend/`). Código nuevo en
módulos planos de `backend/app/` siguiendo el patrón actual (sin paquetes nuevos).

## Diseño por componentes

### `content_files.py` (neutral)

- `resolve_publish_file(storage, content, *, verify)` según research §3; errores
  `ContentFileUnavailable(code, message)` con mensajes seguros. Sin conocimiento de
  plataformas.
- `ContentFileGuard`: `sanitizing(content_id, check)` y `claiming(content_id)` (research §4).
- `sweep_orphan_clean_copies(session, storage) -> int`: solo nombres con `.clean.`.
- `effective_checksum_sql()`: expresión `CASE` reutilizada por el claim.

### `publishing.py` (core, cambio mínimo)

- `PreparedPublication.file_checksum: str | None = None`.
- `PublishContext.file_guard: ContentFileGuard = field(default_factory=ContentFileGuard)`.
- `create_running_attempt`: si `publication.content_id` no es `None`: exige
  `prepared.file_checksum` (si falta → `internal_error`), añade la condición `EXISTS` del
  checksum efectivo y ejecuta UPDATE+commit dentro de `ctx.file_guard.claiming(content_id)`.
  Recibe el guard por parámetro (se le pasa desde `start_publication`).
- `_not_startable`: además de `publishing`, distingue `content_file_changed` comparando el
  checksum efectivo actual.

### Publishers

Cada `check()` usa `resolve_publish_file(..., verify=False)` (disponibilidad + tamaño) y cada
`prepare()` usa `verify=True` como último paso local (tras su preflight de red) y rellena
`PreparedPublication.file_checksum`; TikTok sustituye su hash propio por este (una sola
lectura). Un
`ContentFileUnavailable` se mapea al `PublishProblem` existente (`media_unavailable`) o nuevo
(`media_corrupt`). Todas las referencias de research §3 pasan a `EffectiveFile`.

### `image_metadata.py` / `video_metadata.py`

- `sanitize_image(src: BinaryIO, dst: BinaryIO, fmt) -> None` en streaming por bloques de
  `CHUNK_SIZE` (research §7) y `inspect_image(src: BinaryIO, fmt) -> FileMetadataReport`;
  lector TIFF mínimo propio para Orientation y tags de IFD0.
- `sanitize_video(src: Path, dst: Path, fmt)` y `inspect_video_metadata(path)`;
  `FfmpegMissing` → `503 ffmpeg_required`.

### `asset_library.py`

- `usage_by_content(session, project_id, content_ids=None)` (2 consultas).
- `GET /contents/{id}/usage`, `GET /contents/{id}/metadata`,
  `POST /contents/{id}/remove-metadata` (flujo de research §5 bajo `ContentFileGuard`).
- `contents.py` llama a `usage_by_content` en el listado y en `content_to_read` del detalle.

### Frontend

- `ContentLibrary.tsx`: título/aria "Asset Library", caja de búsqueda, filtros
  (`All`/`Images`/`Videos`/`Used`/`Unused`) como grupo de botones con `aria-pressed`, estado
  vacío propio del filtro, tarjeta mínima (FR-008/FR-008a).
- `AssetUsage.tsx`: carga `GET /usage`; tabla/lista con plataforma, cuenta, estado (con
  `Ready in TikTok` para `awaiting_user_action`), fechas, "Uncertain".
- `AssetFile.tsx`: tamaño, dimensiones, duración, formato, checksum, nombre original,
  versión publicada (texto FR-013a), `Inspect metadata` (lista de categorías) y
  `Remove metadata` (spinner; errores del contrato visibles; tras éxito recarga la
  biblioteca).

## Orden de implementación (con checkpoints)

1. **Migración + modelo + resolvedor + publishers** (sin UI): `metadata_status` siempre
   `unknown` → comportamiento idéntico; regresiones de publishers en verde.
2. **Guard + condición de claim** + tests de carrera.
3. **Sanitizador de imágenes** + tests con centinelas → **checkpoint V1 PNG**: sanitizar
   desde un test/script con el PNG real de ComfyUI y comprobar en ComfyUI. STOP si el
   workflow es recuperable.
4. **Sanitizador de vídeo** + CI con ffmpeg.
5. **API** (`remove-metadata`, `metadata`, `usage`, `ContentRead` ampliado, dedupe, barrido).
6. **Frontend** (biblioteca, detalle, componentes nuevos).
7. **Docs** (README: ffmpeg opcional, Remove metadata, riesgos aceptados) y validación
   manual del quickstart (incluida V1 completa por formato usado).

## Tests mínimos (nuestro código; sin probar internals de Pillow/ffmpeg)

- **Uso**: matriz de estados (published, awaiting, scheduled, unscheduled, failed,
  cancelled, incierto) → `used`, recuentos, plataformas, `last_published_at`; número de
  consultas constante con N contenidos.
- **Resolvedor**: unknown/clean → original; sanitized → copia; copia ausente, tamaño distinto
  o SHA distinto → error y nunca la ruta del original.
- **Imágenes** (archivos generados en el test): PNG con `tEXt`/`zTXt`/`iTXt` (`prompt`,
  `workflow`, `parameters`, `extra_pnginfo`), `eXIf`, `tIME`, `comf`, chunk privado y datos
  tras `IEND`; JPEG con EXIF (GPS, Make, Orientation=6), XMP, APP13, COM, MPF y trailer;
  WEBP extendido con EXIF/XMP/ICC/alpha/animación; Orientation=6 también en PNG y WEBP
  (copia con EXIF mínimo de una sola entrada, no reportado por la inspección); `FF` partido
  entre bloques en JPEG (bloque pequeño en test). Comprobaciones: ningún centinela en los
  bytes (ni en texto descomprimido de chunks restantes), solo bloques de la lista blanca,
  archivo decodificable, píxeles idénticos tras `exif_transpose`, orientación conservada,
  ICC conservado, salida idéntica para archivos ya limpios (→ `clean`).
- **Vídeo** (`skipif` sin ffmpeg): MP4/MOV/WEBM con `comment` JSON centinela, `location`,
  chapters, rotación → sin centinelas, rotación y duración conservadas; ffmpeg ausente →
  `ffmpeg_required`.
- **API remove-metadata**: estados resultantes, idempotencia/doble petición, `publishing` →
  409, fallo del sanitizador → estado intacto y sin archivos, fallo de DB tras mover →
  copia borrada, regeneración, barrido de huérfanos (nunca originales), dedupe por
  `sanitized_checksum`, original con checksum idéntico tras la operación.
- **Carrera**: claim durante sanitización → `content_metadata_busy`; `prepare` antes de
  sanitizar y claim después → `content_file_changed`; en ambos, manual: 409 y publicación
  sin cambios (estado, armado, sin intento) y un reintento posterior funciona; scheduler:
  `not_claimed` sin fallo registrado y el siguiente tick publica la copia; publicación con
  contenido sin `file_checksum` → rechazada.
- **Publishers**: un test por publisher con contenido sanitizado (envía la copia; tamaño y
  checksum efectivos en `submitted`/payload) y con copia ausente (`media_unavailable`, nunca
  el original); TikTok: consentimiento previo pasa a no válido tras sanitizar.
- **Frontend**: tarjeta (Unused, plataformas, Scheduled, Ready in TikTok, Metadata clean en
  clean/sanitized y nada en unknown, sin datos técnicos), búsqueda/filtros, historial,
  textos de clean vs sanitized, Remove metadata (éxito y errores).

## Complexity Tracking

| Desviación | Por qué es necesaria | Alternativa más simple descartada porque |
|---|---|---|
| Cambio en el core de publicación (`publishing.py`: 2 campos con default, 1 condición y un `with` en el claim; `scheduler.py`: 2 códigos) | FR-037a exige que ningún claim envíe el original durante o después de una sanitización; el claim atómico solo existe en el core. | Hacerlo en cada publisher repetiría la lógica 5 veces y no cubre la ventana entre `prepare()` y el claim. |
| Estado en memoria (`ContentFileGuard`) | Bloquear claims mientras ffmpeg trabaja sin bloquear SQLite ni persistir un estado extra. | Un estado persistido `sanitizing` necesita recuperación tras crash y amplía los estados de la spec. |
| Parser propio de PNG/JPEG/WEBP | Lista blanca sin recompresión (spec). | Pillow recomprime; ExifTool está prohibido en runtime y es lista negra. |
