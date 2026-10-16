# Research: Asset Library, Usage & Metadata

**Feature**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Fecha**: 2026-10-16

Decisiones técnicas que resuelven las incógnitas de la spec. Cada sección: decisión,
justificación y alternativas descartadas. Las validaciones marcadas como **[verificado]** se
han comprobado localmente durante el plan (ffmpeg 6.1.1, Ubuntu 24.04).

---

## §1 Agregado de uso (FR-002…FR-007)

**Decisión**: el resumen de uso del listado se calcula con **dos consultas por proyecto**, sin
columnas nuevas en `contents`:

1. `GROUP BY publications.content_id` sobre las publicaciones del proyecto con
   `content_id IS NOT NULL`, devolviendo con `SUM(CASE …)`/`MAX(CASE …)`:
   `publication_count`, `published_count` (`published`), `awaiting_count`
   (`awaiting_user_action`), `scheduled_count` (`scheduled`) y `last_published_at`
   (`MAX(published_at)` de las `published`).
2. `SELECT DISTINCT publications.content_id, accounts.platform` con
   `status IN ('published','awaiting_user_action')` → plataformas usadas por contenido.

`used = published_count + awaiting_count > 0`. Los contenidos sin filas en el agregado reciben
un resumen vacío (`Unused`). El detalle de un contenido reutiliza la misma función filtrada por
`content_id` (mismas reglas, un solo sitio).

**Semántica fijada** (spec FR-003/FR-004/FR-005 y Assumptions):

| Estado de la publicación | Cuenta como usado | Indicador |
|---|---|---|
| `published` | sí (y "confirmada") | plataforma |
| `awaiting_user_action` | sí (no "confirmada") | plataforma + `Ready in TikTok` |
| `scheduled` | no | `Scheduled` |
| `unscheduled`, `publishing`, `failed`, `cancelled` | no | — |

Un intento incierto (`outcome_determined = false`) deja la publicación en `failed` →
no cuenta. El historial del detalle marca la publicación como **incierta** si su último
intento `needs_manual_review` (función existente en `publications.py`).

**Justificación**: dos consultas con índices existentes
(`ix_publications_project_id_status_scheduled_at`) escalan a cientos de assets sin N+1 y no
duplican datos.

**Alternativas descartadas**: columnas `used`/contadores en `contents` (prohibido por la spec);
una consulta por contenido (N+1); `GROUP_CONCAT` para plataformas en una sola consulta
(funciona en SQLite pero devuelve texto a parsear; dos consultas son más claras).

---

## §2 Búsqueda y filtros (FR-010…FR-012)

**Decisión**: búsqueda y filtros **en el cliente** sobre el listado ya cargado. El backend
entrega `usage.used` y `media_type`; el frontend solo filtra por esos campos (la semántica de
`Used` vive en el backend). Búsqueda: `includes` sin distinguir mayúsculas sobre
`title ?? ""` y `original_filename` (se buscan ambos, aunque haya título).

**Justificación**: la biblioteca ya se carga entera; para cientos de elementos el filtrado
local es instantáneo y evita parámetros nuevos en la API. El criterio `used` sigue teniendo una
única fuente.

**Alternativas descartadas**: parámetros `?q=&type=&usage=` en el endpoint (más código, más
tests, sin beneficio a esta escala; se puede añadir si la biblioteca crece mucho).

---

## §3 Archivo efectivo de publicación (FR-032…FR-036)

**Decisión**: nuevo módulo neutral `app/content_files.py` con:

```text
EffectiveFile(path: Path, checksum: str, size: int, clean_copy: bool)
resolve_publish_file(storage, content, *, verify: bool) -> EffectiveFile
    raises ContentFileUnavailable(code="media_unavailable" | "media_corrupt")
```

- `unknown` / `clean` → original (`storage_path`, `checksum`, `size_bytes`).
- `sanitized` → copia (`sanitized_storage_path`, `sanitized_checksum`,
  `sanitized_size_bytes`).
- `verify=False` (checks locales, listado, diálogo de confirmación): existencia + tamaño por
  `stat` (barato, sin leer el archivo).
- `verify=True`: además, si es la copia limpia, **SHA-256 completo** contra
  `sanitized_checksum` (FR-034). Se llama **una sola vez por ejecución**, como **último paso
  local de `prepare()`**, después de cualquier preflight de red del publisher e
  inmediatamente antes del claim atómico y del arranque del hilo que hace la transferencia
  remota. Desde ese punto hasta la subida nada de la aplicación puede modificar la copia:
  `Remove metadata` está bloqueado (guard + `publishing`), el barrido solo corre al arrancar
  y solo borra `.clean` no referenciados, y la regeneración solo ocurre vía `Remove
  metadata`. Así el fallo es un preflight limpio (`media_corrupt`, sin intento creado).
- Listados, detalle, `check()` y diálogos usan solo `verify=False`: **nunca** se recalcula
  el SHA completo por render o consulta.
- TikTok ya calculaba el SHA en `prepare()` contra `content.checksum`
  (`tiktok_video_changed`); pasa a hacerse una sola vez a través del resolvedor contra el
  checksum efectivo (para el original se conserva el código `tiktok_video_changed`), sin
  doble lectura.
- Si la copia falta, cambia de tamaño o su SHA no coincide → `ContentFileUnavailable`; el
  resolvedor **no conoce** ningún camino de vuelta al original para un contenido `sanitized`
  (FR-034: nunca fallback).

**Consumidores a migrar** (inventario completo de usos directos de `storage_path`,
`checksum`, `size_bytes` en publishers):

| Módulo | Usos | Qué pasa a usar |
|---|---|---|
| `youtube_publishing.py` | disponibilidad (`stat` vs `size_bytes`), `resolve`, `total_bytes`, `file_size`, etiqueta | `EffectiveFile` |
| `instagram_publishing.py` | disponibilidad, `resolve`, tamaño de entrega, **fingerprint** (`content.checksum`), `file_size` | `EffectiveFile` (fingerprint con checksum efectivo) |
| `threads_publishing.py` | disponibilidad, `resolve`, comprobación de tamaño, `file_size`, `file_path` | `EffectiveFile` |
| `telegram_publishing.py` | límites `PHOTO_MAX_BYTES`/`VIDEO_MAX_BYTES`, `resolve`, `file_size`, `total_bytes` | `EffectiveFile` |
| `tiktok_publishing.py` | `inspect_video`, plan de chunks, **consent fingerprint** (`video_sha256`), verificación SHA en `prepare`, `checksum` del payload, `file_size`, `total_bytes` | `EffectiveFile` |
| `tiktok_media.py` | `consent_fingerprint(video_sha256=…)` (firma sin cambios; cambia el valor que recibe), `inspect_video(content, path)` usa `content.size_bytes` | recibe tamaño efectivo |
| `tiktok_transfer.py` | compara el digest con `file.checksum` del payload | sin cambio (el payload ya lleva el checksum efectivo) |

Las etiquetas visibles (`"nombre (X MB)"`) usan el tamaño efectivo.
`contents.py` (`file_available`, `GET /contents/{id}/file`) sigue sirviendo el **original**
para la preview: es local, nunca se publica, y el detalle informa de qué versión se
publicará.

**Invalidación natural de consentimientos (FR-035)**: TikTok guarda
`options.consent_fingerprint`; al recalcularlo con el checksum efectivo nuevo deja de
coincidir → `consent_state` pasa a no válido y el preflight exige reconfirmar (mecanismo ya
existente). Instagram usa su `fingerprint` para reutilizar un contenedor de una ejecución
previa: con checksum distinto no reutiliza un contenedor creado con el original (correcto).
Intentos y `submitted` históricos no se tocan (FR-036).

**Justificación**: un único punto de decisión (spec), barato en checks y con la garantía SHA
justo antes de usar la copia. El coste del SHA (un pase de lectura) ya lo asume TikTok para
todos sus vídeos.

**Alternativas descartadas**: decidir el archivo dentro de cada publisher (prohibido); hash en
cada check local (relee archivos de hasta 2 GiB al abrir diálogos); cachear el SHA verificado
(complejidad sin necesidad).

---

## §4 Carrera `Remove metadata` ↔ inicio de publicación (FR-037, FR-037a)

**Arquitectura existente inspeccionada**:

- `start_publication` (manual y scheduler) hace `local_check` → `publisher.prepare()` (puede
  usar red y calcula ya la ruta del archivo) → `create_running_attempt` (UPDATE condicional
  atómico a `publishing` + intento `running`) → hilo de subida con `PreparedPublication`.
- Entre `prepare()` y el claim hay una ventana real (TikTok/Instagram hacen red en `prepare`).
- La app es **un único proceso** (scheduler, runner y API en el mismo proceso; la recuperación
  de intentos interrumpidos ya lo asume).

**Riesgos a cerrar**:

- (a) El claim ocurre mientras la sanitización está en curso → se publicaría el original
  aunque el usuario pidió limpiarlo.
- (b) `prepare()` resolvió el original, la sanitización termina y confirma, y después el claim
  tiene éxito → se publicaría el original con un estado ya `sanitized` (estado mixto).
- (c) La sanitización confirma mientras una publicación ya está `publishing`.

**Decisión** (mínima y neutral, dos piezas):

1. **`ContentFileGuard`** (en `content_files.py`, solo memoria, una instancia en
   `app.state`, referenciada desde `PublishContext`): un `threading.Lock` y el conjunto de
   `content_id` en sanitización.
   - `Remove metadata` entra con `guard.begin_sanitizing(content_id, check)`: bajo el lock
     comprueba que el contenido no está ya en el conjunto (→ `409 metadata_removal_in_progress`,
     cubre doble clic, FR-039) y ejecuta `check(session)`: ninguna publicación del contenido en
     `publishing` (→ `409 content_publishing`). Si pasa, añade el id y suelta el lock. El
     trabajo (ffmpeg incluido) se hace **fuera** del lock; al terminar (éxito o error) se
     retira el id en un `finally`.
   - `create_running_attempt` ejecuta su UPDATE+commit **dentro** de
     `guard.claiming(content_id)`: bajo el mismo lock, si el contenido está en sanitización →
     `409 content_metadata_busy` sin tocar nada. Cierra (a) y (c).
2. **Condición de archivo efectivo en el claim**: `PreparedPublication` gana el campo
   opcional `file_checksum: str | None` (el checksum efectivo que `prepare()` resolvió). Si la
   publicación tiene contenido, el UPDATE condicional de `create_running_attempt` añade
   `EXISTS (SELECT 1 FROM contents WHERE id = :content_id AND CASE WHEN metadata_status =
   'sanitized' THEN sanitized_checksum ELSE checksum END = :file_checksum)`. Si no coincide →
   `409 content_file_changed` sin estado intermedio. Cierra (b).
   - Si una publicación con contenido llega al claim con `file_checksum = None`, el core lo
     rechaza como `internal_error` (fallo de programación; los tests de cada publisher lo
     cubren). Sin contenido (texto) no aplica.
3. **Defensa en profundidad en la confirmación de la sanitización**: el UPDATE de `contents`
   es condicional (`metadata_status`/`sanitized_storage_path` iguales a los leídos al empezar
   **y** `NOT EXISTS` publicación del contenido en `publishing`). Con el guard no debería
   fallar nunca; si falla, se descarta la copia y se responde `409`.

**Si el claim pierde la carrera** (`content_metadata_busy` o `content_file_changed`) el
UPDATE condicional no afecta a ninguna fila y se hace `rollback`: la publicación conserva su
estado (`unscheduled`/`scheduled`/`failed`) y su armado de auto-publish, no se crea intento,
no arranca ningún hilo y no se sube nada (`prepare()` no tiene efectos persistentes antes del
claim, contrato ya existente del `Publisher`).

- **Publish Now (manual)**: `POST /publish` responde `409` con el código y un mensaje claro
  (contrato §Claim); el diálogo lo muestra como cualquier error de preflight. Reintentar
  funciona en cuanto termina la sanitización (`busy`) o inmediatamente (`changed`, ahora con
  la copia limpia; TikTok puede pedir reconfirmar el consentimiento). Nunca queda en
  `publishing`.
- **Scheduler**: ambos códigos se añaden a `NOT_CLAIMED_CODES`: no se registran como fallo
  de auto-publish y el siguiente tick vuelve a preparar con el archivo efectivo nuevo.

**`SCHEDULED` permitido (confirmado)**: una publicación programada no ha resuelto archivo
hasta que empieza; al ejecutarse resuelve el efectivo (la copia). Cualquier consentimiento
ligado al checksum anterior queda inválido de forma natural (§3). No hay riesgo adicional.

**Garantías resultantes**: si hay `publishing` → `Remove metadata` rechazado; mientras se
sanitiza → ningún claim; tras confirmar → todo claim nuevo usa la copia o falla con
`content_file_changed`; nunca un intento `running` con un archivo distinto del efectivo en el
momento del claim.

**Cambio en el core** (justificado en Complexity Tracking): `PublishContext` +1 campo con
valor por defecto, `PreparedPublication` +1 campo opcional, `create_running_attempt` +1
condición y el `with guard.claiming(...)`, `_not_startable` distingue los dos códigos nuevos.
Sin cambios en estados, tablas comunes ni en el scheduler más allá de dos códigos.

**Alternativas descartadas**:
- Estado persistido `sanitizing` en `contents`: añade un estado fuera de la spec y exige
  recuperación tras crash; el conjunto en memoria desaparece solo al reiniciar.
- Solo la condición de checksum: no cubre (a) (se publicaría el original durante el ffmpeg).
- Solo el guard: no cubre (b) (`prepare()` anterior a la sanitización).
- Bloquear la sanitización si hay publicaciones `scheduled`: innecesario (§ anterior) y peor
  UX.
- Lock de fila/`BEGIN IMMEDIATE` durante todo el ffmpeg: bloquearía toda la base SQLite.

---

## §5 Persistencia y almacenamiento de la copia (FR-029…FR-031, FR-040…FR-042)

**Decisión**:

- Columnas nuevas en `contents` (migración `0015`): `metadata_status` (`unknown` por
  defecto, también para filas existentes), `sanitized_storage_path` (único, nullable),
  `sanitized_checksum`, `sanitized_size_bytes`, `sanitized_at`. `CHECK` de consistencia: los
  cuatro campos de copia son no nulos **si y solo si** `metadata_status = 'sanitized'`.
- Ruta de la copia: `projects/{project_id}/{uuid}.clean{ext}` (los originales son
  `{uuid}{ext}`, nunca contienen `.clean`).
- Flujo (patrón de `import_one`):
  1. temporal en `tmp/{uuid}.sanitize{ext}` (sanitizador escribe ahí; error → se borra el
     temporal, DB intacta, original nunca abierto en escritura);
  2. SHA-256 + tamaño del temporal; si SHA == `content.checksum` → `clean`, se borra el
     temporal y se confirma solo el estado;
  3. si no: `storage.commit(temp, clean_path)` (`os.replace`, mismo FS) → UPDATE condicional
     → `commit`; si falla la DB → `storage.discard(final_path)` (FR-041);
  4. regeneración (estado `sanitized` con copia ausente/corrupta): nueva ruta; tras
     confirmar, se borra la ruta antigua si existe (siempre un `.clean`).
- **Barrido al arrancar** (FR-042): `sweep_orphan_clean_copies(session, storage)` recorre
  `projects/*/` buscando **solo** archivos cuyo nombre contenga `.clean.` y borra los no
  referenciados por `sanitized_storage_path`. Nunca toca otros nombres. Se ejecuta en el
  lifespan tras las migraciones, antes del scheduler. Los temporales ya los limpia
  `MediaStorage.prepare()`.

**Justificación**: reutiliza `MediaStorage` (`tmp/` + `os.replace` atómico) y el patrón de
compensación de la importación.

**Alternativas descartadas**: tabla `content_files`/variantes (prohibido); directorio aparte
`clean/` (más rutas que validar; el sufijo basta y el barrido filtra por nombre).

---

## §6 Dedupe ampliado (FR-043)

**Decisión**: `find_duplicate` busca `checksum == X OR sanitized_checksum == X` en el mismo
proyecto. Sin índice nuevo (volumen bajo, y el `UNIQUE(project_id, checksum)` ya cubre el
primer término). No se añade restricción única sobre `sanitized_checksum`: si una sanitización
produjera una copia idéntica al original de *otro* contenido del proyecto (caso
prácticamente imposible), ambos conviven; no se crean variantes.

---

## §7 Sanitizador de imágenes (FR-022…FR-025)

Implementación propia en Python (`app/image_metadata.py`), **lista blanca**, sin
recompresión, copiando bytes de los bloques conservados tal cual. Si la estructura es
inválida (CRC/longitudes/marcadores) → error `invalid_media` y no se crea copia. Si no se
elimina nada, la salida es **byte a byte idéntica** a la entrada (permite `clean`).

**Memoria y límite de tamaño — sin límite nuevo**. Investigado:

- Ya existe un límite global aplicable: `config.MAX_FILE_SIZE = 2 GiB` en la importación;
  ningún `Content` (imagen o vídeo) puede superarlo, así que tampoco su sanitización.
- Los tres formatos se pueden procesar en **streaming** desde archivo de entrada a archivo
  temporal de salida, con bloques de `config.CHUNK_SIZE` (1 MiB, el mismo que la
  importación):
  - **PNG**: cada chunk tiene cabecera de 8 bytes con su longitud; los permitidos se copian
    por bloques (CRC validado de forma incremental) y los demás se saltan con `seek`.
  - **WEBP**: igual con cabeceras RIFF de 8 bytes. El tamaño `RIFF` total y el de cada `ANMF`
    reconstruido se conocen leyendo solo cabeceras (primer pase con `seek`), o escribiendo un
    marcador y corrigiéndolo con `seek` en la salida (es un archivo).
  - **JPEG**: los segmentos previos a `SOS` tienen longitud ≤ 65 535 bytes (acotados por el
    formato). Los datos entrópicos se copian por bloques con un autómata que reconoce `FF00`,
    `RSTn` y el siguiente marcador (incluido un `FF` partido entre bloques). Tras `EOI` se deja
    de leer.
  - **EXIF para Orientation**: no se carga el bloque EXIF entero; un lector mínimo propio de
    TIFF lee la cabecera (8 bytes), salta al IFD0 y recorre sus entradas de 12 bytes con
    `seek` hasta encontrar `0x0112`. Memoria acotada sea cual sea el tamaño del bloque.
  - El SHA-256 y el tamaño de la salida se calculan mientras se escribe.
- Nada necesita cargar el archivo completo en memoria; el pico es del orden de
  `CHUNK_SIZE` + 64 KiB. Por tanto **no se introduce `MAX_SANITIZE_IMAGE_BYTES`** ni el error
  `413 media_too_large`.
- Solo los **tests** decodifican imágenes completas con Pillow para comparar píxeles (archivos
  sintéticos pequeños).

### Orientation (FR-024, FR-025a — aprobado, aplica a PNG, JPEG y WEBP)

- El EXIF original (APP1 `Exif` en JPEG, `eXIf` en PNG, `EXIF` en WEBP) **se elimina
  siempre** entero.
- Si declara `Orientation` (0x0112) con valor válido 2–8, se escribe un **EXIF mínimo
  regenerado** (no copiado): cabecera TIFF `II*\0` + offset 8 + IFD0 con **una sola
  entrada** `0x0112 SHORT 1 <valor>` + next-IFD 0 (26 bytes; en JPEG precedido de
  `Exif\0\0`). Ningún otro campo, sub-IFD, miniatura ni MakerNote sobrevive.
- `Orientation = 1`, ausente o ilegible → la copia no lleva EXIF.
- Lectura con el lector TIFF mínimo propio descrito arriba (sin cargar el bloque).
- Ubicación del bloque mínimo:
  - **JPEG**: `SOI`, `APP0 JFIF` (si existía), `APP1` mínimo, resto en su orden original.
  - **PNG**: chunk `eXIf` (CRC calculado) justo antes del primer `IDAT` (la especificación
    PNG exige que `eXIf` preceda a `IDAT`).
  - **WEBP**: chunk `EXIF` tras los datos de imagen (orden de la especificación: `VP8X`,
    `ICCP`, `ANIM`, imagen/frames, `EXIF`); flag EXIF de `VP8X` a 1. Un WEBP simple (sin
    `VP8X`) no puede llevar EXIF, así que no hay orientación que conservar.
- La inspección (§9) no reporta como sensible un EXIF cuyo único contenido es IFD0 con
  Orientation.

### PNG

- Recorrido: firma + chunks (longitud, tipo, datos, CRC); se valida CRC; se para en `IEND`
  (todo lo posterior se descarta).
- **Lista blanca**: `IHDR`, `PLTE`, `IDAT`, `IEND`, `tRNS`, `cHRM`, `gAMA`, `iCCP`, `sRGB`,
  `sBIT`, `cICP`, `mDCV`, `cLLI` (color/HDR) y APNG `acTL`, `fcTL`, `fdAT`.
- Todo lo demás se elimina: `tEXt`, `zTXt`, `iTXt` (ahí van `prompt`, `workflow`,
  `parameters`, `extra_pnginfo`), `eXIf`, `tIME`, `pHYs`, `bKGD`, `hIST`, `sPLT`, `comf` y
  cualquier chunk desconocido (privado o no).
- `iCCP` incluye un nombre de perfil (texto corto) y el perfil comprimido: se conserva porque
  define el color (riesgo bajo, documentado).

### JPEG

- Recorrido de segmentos desde `SOI`; tras `SOS` se copian los datos entrópicos (respetando
  `FF00` y `RSTn`) hasta el siguiente marcador; soporta múltiples scans (progresivo). Se para
  en `EOI`: todo lo posterior (Motion Photo, gain maps MPF, trailers) se descarta.
- **Lista blanca**: `SOI`, `APP0` **solo** `JFIF\0` (se descarta `JFXX`, que lleva
  miniaturas), `APP2` **solo** `ICC_PROFILE\0` (todas sus partes), `APP14` **solo** `Adobe`,
  `DQT`, `DHT`, `DAC`, `SOF0…SOF15` (salvo `DHT/JPG/DAC` ya listados), `DRI`, `SOS` + datos,
  `RST0…7`, `DNL`, `EOI`.
- Eliminados: `APP1` (Exif y XMP/Extended XMP), `APP2` MPF y otros, `APP13` (Photoshop/IPTC),
  `APP3…APP15` restantes, `COM`, desconocidos.
- **Colocación del EXIF mínimo**: `SOI`, `APP0 JFIF` (si existía), `APP1` mínimo, y después el
  resto en su orden original. Es el orden que generan libjpeg/ExifTool y que leen navegadores y
  Pillow.

### WEBP

- RIFF: `RIFF <size> WEBP` + chunks (FourCC, tamaño, datos, padding par).
- Formato simple (`VP8 `/`VP8L` sin `VP8X`): no admite metadata → salida idéntica salvo
  basura tras el RIFF (se descarta).
- Extendido (`VP8X`): **lista blanca** `VP8X`, `ICCP`, `ANIM`, `ANMF`, `ALPH`, `VP8 `,
  `VP8L`. `ANMF` se reconstruye conservando su cabecera de 16 bytes + `ALPH`/`VP8 `/`VP8L`
  internos (desconocidos dentro del frame se descartan). Eliminados: `EXIF`, `XMP `,
  desconocidos.
- Se reescriben los flags de `VP8X` (bits EXIF/XMP a 0, o EXIF a 1 si se añade el mínimo de
  orientación; ICC/alpha/animación sin cambios) y el tamaño `RIFF`.
- ComfyUI (`SaveAnimatedWEBP`) guarda `workflow:`/`prompt:` dentro de tags EXIF
  (`Make`/`Model`): eliminado con el EXIF.

### Equivalencia visual (SC-004)

Los tests comparan los píxeles decodificados del original y la copia (Pillow, tras aplicar
`exif_transpose` a ambos) y el número de frames/alpha. Es un uso de Pillow como oráculo, no
un test de Pillow.

**Alternativas descartadas**: `Image.save()` de Pillow (recomprime JPEG/WEBP → altera
apariencia); ExifTool `-all=` (dependencia externa y modelo de lista negra; la spec lo
prohíbe en runtime); `piexif`/librerías extra (no aportan frente a ~300 líneas de parser
propio con tests de centinelas).

---

## §8 Sanitizador de vídeo (FR-026, FR-027) — **[verificado]**

**Decisión**: `app/video_metadata.py` ejecuta:

```text
ffmpeg -v error -nostdin -y -i <orig>
  -map 0:V -map 0:a? -c copy
  -map_metadata -1 -map_metadata:s -1 -map_chapters -1
  -fflags +bitexact -flags:v +bitexact -flags:a +bitexact
  [-movflags +faststart]   # solo mp4/mov
  -f <mp4|mov|webm> <tmp/…sanitize.ext>
```

- `0:V` (mayúscula) = vídeo **sin** imágenes adjuntas (portadas); `0:a?` = audio si hay. No
  se mapean data/subtitle/attachment/timecode tracks (GPS de Apple `mebx`, chapters de texto,
  `tmcd`, adjuntos de Matroska).
- `-map_metadata -1` + `:s -1`: sin tags globales ni por stream (`comment` con el JSON de
  VHS, `title`, `location`, `com.apple.quicktime.*`, `creation_time`).
- `+bitexact`: el muxer no escribe `encoder=Lavf<versión>` ni fechas; los `mvhd/tkhd/mdhd`
  quedan con tiempo 0.
- La rotación es side data (display matrix) del stream y **se conserva** con stream copy.
- `+faststart`: mantiene el `moov` delante (lo que esperan las plataformas) sin tocar streams.
- Timeout de 10 minutos; código de salida ≠ 0, timeout o archivo vacío → error
  `sanitize_failed` con mensaje seguro (sin stderr en la respuesta; stderr solo a log en
  `debug`, sin rutas en el mensaje de usuario).
- `shutil.which("ffmpeg") is None` → `503 ffmpeg_required` ("Removing metadata from videos
  needs ffmpeg. Install it and try again.") sin tocar nada. Importar y publicar no dependen de
  ffmpeg (sin cambios).
- Vídeo: nunca se decide `clean` por ffprobe; solo por igualdad de bytes (en la práctica
  siempre `sanitized`, aceptado).

**Verificación local** (ffmpeg 6.1.1, archivos sintéticos con `comment` JSON centinela,
`location`, `creation_time`, chapters, `handler_name` personalizado y rotación 90°):

| Formato | Centinelas tras sanitizar | Chapters | Rotación | Duración |
|---|---|---|---|---|
| MP4 | 0 | eliminados | 90° conservada | 2.000 s = original |
| MOV (con `com.apple.quicktime.location.ISO6709`) | 0 | — | 90° conservada | igual |
| WEBM (VP9/Opus) | 0 | eliminados | — | igual |

Restos aceptados (spec "Riesgos aceptados"): `handler_name` genérico (`VideoHandler`/
`SoundHandler`), `vendor_id=FFMP` en MOV, `MuxingApp/WritingApp = Lavf` **sin versión** en
WEBM y la cadena SEI del codificador dentro del bitstream H.264 (`x264 - core …`), que no
contiene workflow ni datos del usuario y exigiría recodificar.

**Alternativas descartadas**: recodificar (prohibido); `-map 0` + borrado selectivo (deja
tracks de datos con GPS); ExifTool para MP4 (prohibido en runtime).

---

## §9 Inspección de metadata (FR-015…FR-018)

**Decisión**: `GET /contents/{id}/metadata` bajo demanda, sin persistencia. Devuelve
categorías detectadas para el original y, si existe, para la copia limpia.

- **Imágenes**: el mismo recorrido de chunks/segmentos de §7 clasifica bloques:
  - texto PNG (`tEXt/zTXt/iTXt`) → clasificado por su **keyword** (≤ 79 bytes, sin
    descomprimir): `prompt`/`workflow` → `comfyui`; `parameters` (A1111) u otras claves de
    generación → `ai_generation`; el resto → `comments`;
  - EXIF (APP1, `eXIf`, `EXIF`) con el lector TIFF mínimo: si IFD0 contiene **solo**
    Orientation no se reporta nada (FR-025a); en otro caso → `exif`, y además: puntero GPS
    (0x8825) → `location`; `Make`/`Model` → `device` (o `comfyui` si su valor empieza por
    `workflow:`/`prompt:`, comprobando solo un prefijo acotado); `Software` → `software`;
    `DateTime` o puntero Exif IFD con `DateTimeOriginal`/`DateTimeDigitized` → `dates`;
  - XMP (APP1 `http://ns.adobe.com/xap/1.0/`, `XMP `, `iTXt XML:com.adobe.xmp`) → `xmp`;
  - APP13 → `iptc`; `COM` → `comments`; `tIME` → `dates`; desconocidos y trailers →
    `other`.
- **Vídeo**: `ffprobe -show_format -show_streams -show_chapters` (JSON): tags globales/por
  stream → `container`; `location`/`ISO6709` → `location`; `creation_time` → `dates`;
  `encoder`/`com.apple.quicktime.software` → `software`; `make`/`model` → `device`;
  chapters → `container`; tags con `workflow`/`prompt`/JSON de nodos → `comfyui`; streams
  data/attachment → `other`. Sin ffprobe → `inspected: false` con motivo.
- La respuesta solo trae **códigos de categoría + etiqueta + nombres de clave** (p. ej.
  `["workflow","prompt"]`), nunca valores (FR-018). Nada de esto se loguea (FR-045).

**Alternativas descartadas**: persistir el informe (innecesario); ExifTool para inspeccionar
(dependencia de runtime prohibida).

---

## §10 Presentación (FR-008, FR-008a, FR-013, FR-013a)

- Tarjeta: preview, `title ?? original_filename`, badge `Image`/`Video`, `Unused` o
  plataformas (`YouTube · Telegram`), `Scheduled`, `Ready in TikTok`, `Metadata clean`
  (si `clean` o `sanitized`). Se quita la fecha actual de la tarjeta (no está en la lista
  de FR-008).
- Detalle: secciones **Usage** (historial) y **File** (datos técnicos, versión que se
  publicará, estado de metadata con los textos de FR-013a, `Inspect metadata`,
  `Remove metadata`).
- `Remove metadata` visible si `unknown`, o si `sanitized` con copia no disponible
  (regenerar); oculto en `clean` y en `sanitized` disponible (el endpoint es idempotente de
  todos modos).
- "Disponible" en el listado = existe y tamaño correcto (`verify=False`). Una corrupción del
  mismo tamaño solo se detecta al publicar (`media_corrupt`); el mensaje del error indica
  pulsar `Remove metadata` en el asset, y el endpoint, con `verify=True`, regenera.

---

## §11 CI y dependencias

- `ffmpeg` se instala en el job backend de `.github/workflows/ci.yml`
  (`sudo apt-get update && sudo apt-get install -y ffmpeg`) para que los tests de integración
  de vídeo (marcados con el `skipif` existente de `shutil.which`) se ejecuten en CI.
- Sin dependencias Python nuevas (Pillow ya está). ExifTool no se usa en runtime.

---

## §12 Riesgos conocidos

- Ultra HDR/gain maps (MPF) y Motion/Live Photo se pierden.
- Vídeos casi siempre generan copia.
- Cadena SEI del codificador y `Lavf` sin versión pueden permanecer.
- iPhone: HEIC no está soportado por la biblioteca; MOV de iPhone con track `mebx` de
  metadata y GPS → se valida con archivo real si está disponible (quickstart).
- Corrupción de la copia con el mismo tamaño solo se detecta en `prepare()` (antes de la
  subida, sin intento creado).
