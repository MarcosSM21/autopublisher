# Research: Media Metadata Hygiene (Feature 028, scope mínimo)

Fecha: 2026-11-02. Verificado en el código de `main` @ 42fe36e. El diseño ampliado (evidencia,
parsers de contenedor, backfill, equivalencia) está en [reference-031/](reference-031/research.md)
y **no** forma parte de 028.

## R1. Fuente del badge

**Decisión**: helper puro en el frontend sobre `metadata_status` + `publish_file.available`, que
ya llegan en cada `ContentRead` (listado y detalle, `backend/app/contents.py::content_to_read` y
`publish_file_read`).

- `publish_file.available` hace `stat` del archivo publicado (copia si `sanitized`, original si
  no): existencia + tamaño, sin hashing. No hay coste nuevo por card.
- Combinaciones (spec FR-001): `unknown` → 🟡 *Not cleaned yet*; `clean` + disponible → 🟢
  *Already clean*; `clean` + no disponible → 🟡 *Media file missing*; `sanitized` + disponible →
  🟢 *Cleaned copy*; `sanitized` + no disponible → 🟡 *Clean copy missing*. `unknown` no depende
  de la disponibilidad.

**Alternativas rechazadas**: un campo derivado en el backend (cambia la API sin necesidad); la
evidencia persistente (031).

## R2. Reinspección post-clean

**Decisión**: en `asset_library._remove`, justo después de `_sanitize_to(original, temp, content)`
y **antes** de calcular el checksum y de decidir entre `clean` y `sanitized`, inspeccionar `temp`
con la función existente `_inspect(temp, content)` (que ya despacha a `inspect_image` o
`inspect_video_metadata`):

- `report.inspected = False` → rechazar con `503 metadata_check_unavailable` ("The cleaned file
  could not be checked, so it was not saved."). En vídeo significa ffprobe ausente o ilegible.
- `report.findings` no vacío → rechazar con `422 metadata_not_removed` ("Metadata could not be
  removed safely from this file.").
- En ambos casos: el `finally` existente descarta `temp`; no se escribe nada en la BD; estado y
  archivo publicado no cambian.
- Si pasa: el flujo de 016 continúa sin cambios (rama `clean` si el resultado es idéntico al
  original; rama `sanitized` si no).

Como la comprobación ocurre antes de la bifurcación, cubre también la rama `clean`.

**Fallo rápido en vídeo**: si el media es vídeo y `ffprobe` no está en el `PATH`, rechazar con
`503 metadata_check_unavailable` antes de lanzar ffmpeg, para no remuxear un archivo grande que
luego no se podrá comprobar. `ffmpeg` ausente sigue dando el `503 ffmpeg_required` de 016.

**Verificado empíricamente** (ffmpeg/ffprobe 6.1.1): el inspector actual devuelve 0 hallazgos
sobre las copias que genera el remux actual de MP4, MOV y WebM, aunque los originales tuvieran
título, comentario JSON, ubicación, fechas, claves Apple y nombre de pista. En imágenes, la lista
blanca solo deja bloques que el inspector no informa (el EXIF mínimo con solo Orientation no
cuenta). Así que la reinspección no rechaza limpiezas legítimas.

**Alternativas rechazadas**: inspeccionar después del commit (habría que deshacer la transacción);
guardar el informe (031).

## R3. Miniatura JFIF / JFXX

Estructura del APP0 JFIF: `FFE0`, longitud (2), `"JFIF\0"`, versión (2), unidades (1), densidad X
(2), densidad Y (2), `Xthumbnail` (1), `Ythumbnail` (1) y `3·X·Y` bytes RGB de miniatura. Sin
miniatura, la longitud es 16.

Estado actual:

- `_jpeg_keep` conserva cualquier APP0 que empiece por `JFIF\0`, **con su miniatura**. El inspector
  lo trata como bloque conservado, así que no lo informa. **Hueco real.**
- `JFXX\0` (APP0 de extensión, solo miniaturas) **ya** se descarta (no empieza por `JFIF\0`) y el
  inspector **ya** lo informa como `other` (`APP0:JFXX`). Solo faltan tests.

**Decisión**:

- **Sanitizador**: en `_plan_jpeg`, si el APP0 JFIF tiene `Xthumbnail·Ythumbnail > 0` o una
  longitud mayor que 16, sustituir su `_Copy` por un `_Write` con un APP0 de 16 bytes que copia
  versión, unidades y densidades y pone las dimensiones de la miniatura a 0. Si el JFIF ya es
  mínimo, se sigue copiando byte a byte, así que los JPEG limpios conservan la rama `clean`. Los
  13 primeros bytes de datos están dentro del `ident` de 32 bytes que ya se lee. Un JFIF truncado
  (menos de 14 bytes de datos) se trata como hoy (`invalid_media` si la estructura es inválida;
  si no, se copia).
- **Inspector**: en `_inspect_jpeg`, un APP0 JFIF con miniatura añade `other` → `"JFIF
  thumbnail"`. Se usa la categoría existente `other`: no hay categorías nuevas.
- La detección de la miniatura EXIF IFD1 queda para 031.

## R4. Logs

Auditoría de las rutas de metadata:

| Ubicación | Hoy | Cambio |
|---|---|---|
| `video_metadata.py:88` | `logger.debug("ffmpeg could not sanitize a video", exc_info=True)` | Sin `exc_info`; solo el nombre de la clase de excepción |
| `video_metadata.py:91-92` | `logger.debug("ffmpeg failed: %s", completed.stderr[-2000:])` | Solo el código de salida |
| `video_metadata.py:145` | `logger.debug("ffprobe could not inspect a video", exc_info=True)` | Solo el nombre de la clase |
| `media.py:197`, `media.py:309` | `logger.debug("ffprobe could not read the video", exc_info=True)` | Solo el nombre de la clase |
| `asset_library.py` (`logger.warning` ×4) | Mensajes fijos | Sin cambios |

Patrón ya usado en `scheduler.py`: "Only the class name: messages of arbitrary errors may hold
secrets". El traceback de `CalledProcessError` incluye la línea de comandos y puede arrastrar
salida, por eso se elimina `exc_info`.

## R5. Textos

Se cambian solo los textos que nombran la acción:

| Archivo | Texto actual | Nuevo |
|---|---|---|
| `content_files.py` `COPY_UNAVAILABLE_MESSAGE`, `COPY_CORRUPT_MESSAGE` | "Use Remove metadata on the asset…" | "Use Clean metadata on the media…" |
| `asset_library.py` `PUBLISHING_MESSAGE` | "…Remove metadata after the upload finishes." | "…Clean metadata after the upload finishes." |
| `asset_library.py` `INVALID_MEDIA_MESSAGE` | "…its metadata cannot be removed safely." | "…its metadata cannot be cleaned safely." |
| `video_metadata.py` `FFMPEG_MISSING_MESSAGE` | "Removing metadata from videos needs ffmpeg…" | "Cleaning video metadata needs ffmpeg…" |
| `FileDetails.tsx` | "Remove metadata", "Removing metadata…", textos de estado | "Clean metadata", "Cleaning metadata…" |

Ningún test fija esos textos del backend (verificado con grep). Los mensajes "Metadata is being
removed…" del guard y de los bloqueos de borrado no nombran la acción y se dejan como están (los
fijan varios tests de borrado; cambiarlos no aporta nada). Los comentarios y docstrings internos
no son visibles y no se tocan. El endpoint `POST /remove-metadata` no cambia.

## R6. UI

- **Helper** `frontend/src/pages/library/metadata-indicator.ts`, con el mismo patrón que
  `usage-indicator.ts`: `metadataIndicator(content) → {tone, icon, label, reason, canClean}`.
  `canClean` replica la condición actual de `FileDetails` (`unknown`, o `sanitized` con la copia
  no disponible) y la extiende de forma coherente a `clean` con el archivo no disponible
  (`false`: no hay archivo que limpiar).
- **Card**: segundo `Badge` en `MediaCard` junto al de uso; texto accesible con el motivo
  (`ap-visually-hidden`).
- **Detalle**: fila nueva en `MediaDetail` tras la carpeta, con badge, motivo y botón **Clean
  metadata** cuando `canClean`.
- **Reutilización del manejador**: el `handleRemove` de `FileDetails` (estado de carga + error +
  `removeMetadata` + `onChanged`) se extrae a un hook `useCleanMetadata(contentId, onChanged)`
  que usa la cabecera. El botón sale de *File details* para que no haya dos botones iguales;
  *Inspect metadata* y el resto de *File details* se quedan donde están.
- **Actualización inmediata**: `onChanged` de `MediaDetail` ya recarga la Library entera (cards
  incluidas) y el detalle recibe el `content` nuevo. No hace falta polling.
- **Móvil**: los dos badges van en una fila que puede partirse (`flex-wrap`) en
  `library.css`.
