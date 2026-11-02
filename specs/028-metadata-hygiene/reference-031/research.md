> **Referencia para la futura Feature 031 — Metadata Verification & Hardening.** Este documento
> describe el diseño ampliado que se descartó del scope de Feature 028 el 2026-11-02. NO forma
> parte de la implementación de 028.

# Research: Media Metadata Hygiene (Feature 028)

Fecha: 2026-11-02. Todas las afirmaciones sobre el código se verificaron en el repositorio
(rama `028-metadata-hygiene`, base `main` @ 42fe36e). Las pruebas empíricas de vídeo se hicieron
con ffmpeg/ffprobe 6.1.1 y ExifTool 12.76 sobre archivos sintéticos (MP4, MOV y WebM con título,
comentario JSON, ubicación, `creation_time`, claves Apple `make`/`model`/`content.identifier`,
`loci`, nombre de pista y handler personalizado).

---

## §1. Estado actual de Feature 016: qué se reutiliza y qué cambia

| Pieza (archivo) | Veredicto | Detalle |
|---|---|---|
| `Content.metadata_status` + `sanitized_*` (`models.py`) | **Se reinterpreta** | Pasa a significar solo "hay copia limpia" (`sanitized`) o "no la hay" (`unknown`). `clean` deja de escribirse y se migra a `unknown`: ya no afirma nada sobre la limpieza (FR-003). Ver §5. |
| Sanitizador de imágenes `sanitize_image` (`image_metadata.py`) | **Se reutiliza con 1 corrección** | La lista blanca de PNG/WebP es correcta. En JPEG, `_jpeg_keep` conserva el APP0 JFIF **entero** por prefijo, incluida una posible miniatura JFIF (`Xthumbnail × Ythumbnail > 0`). Hay que reescribir el JFIF sin miniatura (16 bytes de cabecera, densidad conservada). Ver §2. |
| Sanitizador de vídeo `sanitize_video` (`video_metadata.py`) | **Se reutiliza sin cambios de comando** | Verificado empíricamente (§4): copia de streams bit a bit; elimina tags globales/por stream, `udta`/`keys`/`ilst`, `loci`, chapters, nombre de pista y título/fecha WebM; con `+bitexact` las fechas `mvhd`/`tkhd`/`mdhd` quedan a 0, `CompressorName` vacío y `MuxingApp`/`WritingApp` = `Lavf`. Solo cambia el logging (§9). |
| Inspector de imágenes `inspect_image` | **Se amplía** | Ya recorre toda la estructura. Faltan: clasificación tripartita (técnico / relevante / no clasificable), identificadores internos, miniatura IFD1 cuando IFD0 solo trae Orientation, miniatura JFIF, chunks/segmentos técnicos conocidos que hoy salen como "other" (falsos positivos: `pHYs`, `bKGD`, `iDOT`…), y saneado de nombres de clave. Ver §2. |
| Inspector de vídeo `inspect_video_metadata` | **Se sustituye por parser estructural + ffprobe** | Solo ve tags de ffprobe. No ve `uuid`/XMP (el demuxer mov solo exporta XMP con `-export_xmp`, desactivado por defecto), `loci` como bloque propio, fechas de cabecera, nombre de pista WebM (verificado: `Track Name` no aparece en el informe), `SegmentUUID`, adjuntos raros ni cajas desconocidas. Clasifica `content.identifier` como `container`. Ver §3. |
| `resolve_publish_file`, `effective_checksum*` (`content_files.py`) | **Se reutiliza sin cambios** | Sigue siendo el único punto que decide el publish file. Se añade al lado una función de derivación del estado (§6) que lo usa. Los mensajes "Use Remove metadata…" pasan a "Use Clean metadata…". |
| `ContentFileGuard` | **Se reutiliza; se añade marca "inspeccionando"** | `sanitizing`/`claiming`/`deleting` no cambian. Se añade un registro en memoria de las inspecciones en curso (solo para mostrar actividad; la inspección no excluye nada porque solo lee). |
| Borrado (`deletion.py`) | **Cambio mínimo** | El borrado de un media ya elimina dependientes con `delete()` explícitos antes de `Content`; se añade la tabla de evidencias a esa lista (además de `ON DELETE CASCADE`). |
| Cleanup de huérfanos (`sweep_orphan_clean_copies`, `run_file_cleanup`) | **Sin cambios** | Solo considera archivos `.clean.`; las evidencias viven en la BD y se escriben en la misma transacción que la copia. |
| Backup/restore (`backup.py`) | **Sin cambios de código** | El backup es un snapshot de SQLite: la nueva tabla viaja sola. Restore ya verifica los checksums de originales y copias; la evidencia solo vale si su checksum coincide con el efectivo (§6), así que nada puede ponerse en verde por error tras restaurar. Solo tests. |
| Import (`contents.import_one`) | **Cambio mínimo** | Tras el commit, encola el id en el worker de inspección con prioridad. Nunca inspecciona dentro de la importación (§8). |
| Endpoints `GET …/metadata` (inspección en vivo) y `POST …/remove-metadata` | **Se reemplazan** | `GET …/metadata` devuelve la evidencia guardada; `POST …/metadata/check` (Check again) y `POST …/clean-metadata`. Ver [contracts/api.md](contracts/api.md). |
| Frontend `FileDetails.tsx`, `MediaCard.tsx`, `Badge` | **Se amplía** | `Badge` ya tiene tonos `success`/`warning` e icono. `usePostsData` ya hace polling con `setInterval`: mismo patrón. |
| Patrón de hilo de fondo (`AnalyticsRefresher`, `Scheduler`) | **Se reutiliza el patrón** | Hilo daemon + `threading.Event` de stop/wake + `run_once()` testeable + `autostart` en settings. |

---

## §2. Inspección completa de imágenes

**Decisión**: se mantiene el recorrido estructural propio de 016 (sin dependencias nuevas) y cada
bloque se clasifica en una de cuatro clases con tablas explícitas:

- **estructural**: necesario para decodificar; no se informa;
- **técnico conservado**: permitido por FR-009; se lista en "datos técnicos conservados" con una
  etiqueta fija, nunca con su valor;
- **relevante**: categoría de metadata (lo que impide el 🟢);
- **no clasificable**: desconocido y capaz de llevar payload arbitrario → resultado `incomplete`.

Regla general (FR-007): en los tres formatos todo bloque auxiliar desconocido puede llevar
payload arbitrario por definición del formato (chunks PNG/RIFF y segmentos APPn son contenedores
de bytes opacos), así que **un bloque desconocido es siempre no clasificable**. Lo
"inequívocamente estructural" se cubre enumerando los bloques técnicos conocidos, no adivinando.

### JPEG

| Bloque | Clase | Categoría / etiqueta |
|---|---|---|
| SOI, EOI, SOFn, DHT, DQT, DAC, DRI, DNL, SOS, RSTn, datos entrópicos | estructural | — |
| APP0 `JFIF\0` sin miniatura | técnico | "JFIF header" |
| APP0 `JFIF\0` con miniatura (`Xthumb·Ythumb > 0`) | relevante | `other` → "Thumbnail" |
| APP0 `JFXX\0` (miniatura extendida) | relevante | `other` → "Thumbnail" |
| APP2 `ICC_PROFILE\0` | técnico | "ICC color profile" |
| APP14 `Adobe` | técnico | "Adobe color transform" |
| APP1 `Exif\0\0` solo con Orientation **y** sin IFD1 | técnico | "EXIF Orientation" |
| APP1 `Exif\0\0` con cualquier otra cosa | relevante | `exif` + subcategorías: GPS IFD → `location`; Make/Model/BodySerialNumber(0xA431)/LensMake/LensModel/LensSerialNumber(0xA435)/CameraOwnerName(0xA430) → `device`; Software/ProcessingSoftware → `software`; DateTime/DateTimeOriginal/Digitized/OffsetTime* → `dates`; ImageUniqueID(0xA420) → `identifiers`; Artist/Copyright/ImageDescription/UserComment(0x9286)/XPComment… → `comments`; MakerNote(0x927C) → `device`; IFD1 → `other` "Thumbnail"; prefijos ComfyUI en Make/Model → `comfyui` |
| APP1 XMP / XMP extendido | relevante | `xmp`; además, si el paquete contiene los nombres `xmpMM:DocumentID`/`InstanceID`/`OriginalDocumentID` → `identifiers`; `exif:GPS*` → `location` (se buscan **nombres** de propiedad, nunca se extraen valores) |
| APP13 Photoshop/IRB (IPTC) | relevante | `iptc` |
| COM | relevante | `comments` |
| APP2 `MPF\0` (Ultra HDR, imágenes secundarias), APP2 `FPXR` | relevante | `other` "Secondary image data" |
| APP12 `Ducky`, APP1 otros conocidos (p. ej. `http://ns.adobe.com/xmp/extension/`) | relevante | `comments` / `xmp` |
| Cualquier otro APPn (APP3–APP15 desconocidos) | **no clasificable** | `incomplete` |
| Datos tras EOI (Motion Photo, MPF) | relevante | `trailing_data` |

### PNG / APNG

| Chunk | Clase |
|---|---|
| IHDR, PLTE, IDAT, IEND, acTL, fcTL, fdAT | estructural |
| tRNS, cHRM, gAMA, sRGB, sBIT, cICP, mDCV, cLLI | técnico ("Color information", "Transparency") |
| iCCP | técnico ("ICC color profile"; el nombre del perfil es texto libre corto: riesgo aceptado, se documenta) |
| pHYs, bKGD, hIST, oFFs, sCAL, iDOT (Apple, offsets de IDAT) | técnico conocido (no impide 🟢; el sanitizador los descarta igualmente) |
| tEXt/zTXt/iTXt | relevante: `prompt`/`workflow` → `comfyui`; `parameters`/`extra_pnginfo`/… → `ai_generation`; `XML:com.adobe.xmp` → `xmp` (+ identificadores por nombre); resto → `comments` |
| eXIf | igual que el EXIF de JPEG |
| tIME | relevante `dates` |
| comf | relevante `comfyui` |
| sPLT, pCAL (llevan cadenas libres), dSIG | relevante `other` |
| Cualquier otro chunk | **no clasificable** |
| Datos tras IEND | relevante `trailing_data` |

### WebP

| Chunk RIFF | Clase |
|---|---|
| VP8, VP8L, VP8X, ANIM, ANMF, ALPH (dentro de ANMF: VP8/VP8L/ALPH) | estructural |
| ICCP | técnico ("ICC color profile") |
| EXIF | igual que el EXIF de JPEG (incl. workflow ComfyUI en WebP animado) |
| `XMP ` | relevante `xmp` (+ identificadores) |
| Cualquier otro chunk, o chunk desconocido dentro de ANMF | **no clasificable** |
| Datos tras el tamaño RIFF declarado | relevante `trailing_data` |

**Alternativas rechazadas**: Pillow para inspeccionar (no expone chunks desconocidos ni trailers
de forma fiable y carga más de lo necesario); ExifTool en runtime (prohibido por FR-018).

**Saneado de nombres de clave** (seguridad, §9): los nombres que se guardan o devuelven (palabras
clave PNG, claves QuickTime, TagName WebM, tags de ffprobe) se aceptan solo si cumplen
`^[A-Za-z0-9 ._:@©-]{1,64}$`; si no, se sustituyen por un nombre genérico (`"text chunk"`,
`"custom key"`). Así un nombre de clave nunca transporta un valor personal.

---

## §3. Inspección profunda de vídeo (punto principal)

### Hallazgos empíricos

1. **ffprobe no basta**: con tags estándar ve título, comentario, ubicación, encoder, fechas y
   claves Apple (`make`, `model`, `content.identifier`), pero:
   - no informa de cajas `uuid` (XMP) sin `-export_xmp`;
   - no informa de las fechas de `mvhd`/`tkhd`/`mdhd` (en el MOV de prueba seguían a
     2024-05-01 aunque no había tag `creation_time` en ese nivel);
   - no ve el nombre de pista WebM (`Name`), ni `SegmentUUID`, ni elementos/átomos que su demuxer
     no mapea;
   - su salida depende de la versión del demuxer.
2. **El remux actual limpia de verdad**, pero deja **estructuras vacías** que el inspector debe
   aceptar como estructurales: en MP4 `moov/udta/meta(hdlr mdir, ilst vacío)`; en WebM un `Tags`
   con un `SimpleTag DURATION` por pista; `free`/`wide`/`Void` de relleno; `VendorID = FFmpeg` en
   la sample description MOV.
3. **Residuos en el bitstream** (no en el contenedor): el SEI de x264 (`x264 - core 164 …
   options…`) y la cadena `Lavc60.x` del encoder AAC dentro de los paquetes. Son idénticos en
   original y copia (los paquetes son bit a bit iguales) y solo eliminables recodificando.
   Coincide con el riesgo aceptado de 016 / FR-016.

### Decisión: parser estructural mínimo propio + ffprobe como verificación cruzada

- **ISO-BMFF/QuickTime (MP4, MOV)**: un recorredor de cajas con lecturas acotadas (como los de
  imagen), que **solo desciende** en contenedores conocidos y **salta** `mdat` sin leerlo.
- **EBML (WebM)**: un recorredor de elementos con el esquema reducido de WebM, que salta el
  contenido de los bloques (`SimpleBlock`/`BlockGroup`) pero recorre los `Cluster`, incluidos los
  de **tamaño desconocido** (MediaRecorder de navegadores), avanzando bloque a bloque.
- **ffprobe** sigue siendo obligatorio (también para validar la copia en Clean metadata; con
  ffmpeg para el remux: limpiar vídeo necesita ambos, C2): confirma que el archivo es válido y sus tags se
  clasifican con las reglas de 016 como señal adicional; cualquier tag que vea ffprobe y el
  parser no explique cuenta como relevante (unión de ambos). Sin ffprobe → `incomplete`
  (spec, US1-4).

**Alternativas rechazadas**: mutagen (no está en el proyecto, no cubre WebM y no informa de lo
desconocido); hachoir/pymediainfo (dependencias grandes o con binario nativo);
`ffprobe -export_xmp` + `-show_data` (sigue sin ver cajas no mapeadas ni fechas de cabecera);
ExifTool (prohibido en runtime).

### Reglas MP4/MOV

| Ubicación | Estructural / técnico | Relevante | No clasificable |
|---|---|---|---|
| Raíz | `ftyp`, `moov`, `mdat`, `moof`, `mfra`, `sidx`, `styp`; `free`/`skip`/`wide` con payload vacío o todo ceros | `udta`/`meta` en raíz → `container`; `free`/`skip`/`wide` con datos → `other` "Padding with data"; `uuid` XMP (`BE7ACFCB-97A9-42E8-9C71-999491E3AFAC`) → `xmp`; `pnot`/`PICT` → `other` "Preview image"; bytes tras la última caja → `trailing_data` | `uuid` no XMP; cualquier otra caja |
| `moov` | `mvhd` con fechas 0, `trak`, `mvex`, `iods`, `udta` vacío | `mvhd` con fecha ≠ 0 → `dates`; `udta`/`meta` con contenido (ver abajo) | otras |
| `trak` | `tkhd` con fechas 0, `edts`/`elst`, `mdia`, `tref`, `tapt`, `load` | `tkhd` con fecha ≠ 0 → `dates`; `udta`/`meta` con contenido | otras |
| `mdia` | `mdhd` con fechas 0, `hdlr`, `minf` | `mdhd` con fecha ≠ 0 → `dates`; `hdlr` con tipo ≠ `vide`/`soun` → `other` "<tipo> track" (timecode `tmcd`, `text`, `sbtl`, `meta`/`mebx`, `gpmd`/GPS de GoPro, `hint`, chapters `chap`); nombre de handler no genérico → `container` | otras |
| `minf`/`dinf`/`stbl` | `vmhd`, `smhd`, `gmhd`, `hdlr`, `dinf`/`dref`/`url `, `stsd`, `stts`, `stss`, `ctts`, `stsc`, `stsz`, `stz2`, `stco`, `co64`, `sgpd`, `sbgp`, `sdtp`, `cslg`, `stps`, `saiz`, `saio`, `subs` | `CompressorName` no vacío en la sample entry visual → `software` | otras |
| `stsd` (sample entries) | configuración de códec (`avcC`, `hvcC`, `esds`, `dOps`, `colr`, `pasp`, `btrt`, `clap`, …): técnico "Codec configuration"; `VendorID` de 4 caracteres: técnico | — | — (no se desciende más allá de la sample entry) |
| `udta` (cualquier nivel) | vacío, o solo `meta` vacío | **todo hijo es metadata**: `©xyz`/`loci` → `location`; `©day` → `dates`; `©too`/`©swr` → `software`; `©mak`/`©mod` → `device`; `©cmt`/`©des`/`©nam`/`name` → `comments`/`container`; `XMP_` → `xmp`; `chpl` → `container`; cualquier otro → `container` | — (dentro de `udta` nada es ambiguo: todo es metadata) |
| `meta` | `hdlr` + `keys`/`ilst` vacíos | cada clave de `keys` / ítem de `ilst` por nombre: `com.apple.quicktime.location.*` → `location`; `.make`/`.model` → `device`; `.software` → `software`; `.creationdate` → `dates`; `.content.identifier` → `identifiers`; `©xyz` etc. como en `udta`; resto → `container` | — |

Límites: profundidad máxima de anidamiento y número máximo de cajas; superarlos → `incomplete`.
Tamaños de caja incoherentes → `error` (`invalid_structure`).

### Reglas WebM

| Elemento | Estructural / técnico | Relevante | No clasificable |
|---|---|---|---|
| Cabecera EBML (`DocType = webm`) | estructural | — | DocType distinto → `error` |
| `Segment` hijos | `SeekHead`, `Info`, `Tracks`, `Cluster`, `Cues`, `Void` (todo ceros), `CRC-32` | `Tags` (salvo `DURATION`, ver abajo), `Attachments` → `other` "Attachments", `Chapters` → `container`; `Void` con datos → `other` | otros |
| `Info` | `TimestampScale`, `Duration`; `MuxingApp`/`WritingApp` = `Lavf` exacto (técnico "Muxer name") | `MuxingApp`/`WritingApp` con otro valor → `software`; `Title` → `container`; `DateUTC` → `dates`; `SegmentUUID`/`PrevUUID`/`NextUUID`/`SegmentFilename` → `identifiers` | otros |
| `TrackEntry` | elementos del esquema WebM de pista (`TrackNumber`, `TrackUID`, `TrackType`, `FlagLacing`, `CodecID`, `CodecPrivate`, `CodecDelay`, `SeekPreRoll`, `DefaultDuration`, `Language`, `Video`/`Audio` y sus hijos, `ContentEncodings`…) | `Name` → `container`; `CodecName` → `software` | otros |
| `Tags/Tag/SimpleTag` | `Targets`/`TagTrackUID`; `TagName = DURATION` (técnico "Track duration") | otros nombres: `ENCODER` → `software`; `DATE*`/`CREATION_TIME` → `dates`; `*LOCATION*`/`GPS*` → `location`; `COMMENT`/`TITLE`/`DESCRIPTION` → `comments`/`container`; `workflow`/`prompt` → `comfyui`; resto → `container` | — |
| `Cluster` | `Timestamp`, `SimpleBlock`, `BlockGroup` (no se leen los datos) | — | otros hijos |
| Bytes tras el `Segment` | — | `trailing_data` | — |

### Zonas no inspeccionadas (límite documentado)

`mdat` y los datos de bloques de `Cluster` son **payload de media**: no se recorren. Las cadenas del
bitstream (§3.3) y unos bytes no referenciados dentro de `mdat` no pueden detectarse sin
decodificar o reconstruir la tabla de muestras. Se tratan como "media data" (no como zona de
metadata) y se documentan en Riesgos aceptados. Una copia producida por el remux solo contiene
muestras referenciadas. **Aprobado como límite explícito (C3): spec FR-007a y Riesgos aceptados.**

---

## §4. Limpieza y equivalencia

### Verificación empírica del remux actual

| Residuo | MP4 | MOV | WebM |
|---|---|---|---|
| Fechas de cabecera | 0 | 0 | sin `DateUTC` |
| Tags globales/por stream | ninguno | ninguno | solo `DURATION` por pista |
| `udta`/`keys`/`ilst`/`loci` | `udta/meta/ilst` **vacío** | eliminado | n/a |
| Encoder/muxer en contenedor | ninguno (`CompressorName` vacío) | `VendorID FFmpeg` (técnico) | `Lavf` sin versión |
| Nombre de pista / handler | `VideoHandler`/`SoundHandler` | genéricos | sin `Name` |
| XMP/`uuid` | eliminado (el muxer no los copia) | eliminado | n/a |
| Paquetes (`ffmpeg -f streamhash`) | **idénticos** al original | **idénticos** | **idénticos** |

Conclusión: el comando de 016 cumple la spec; el trabajo está en verificarlo.

### Equivalencia de imágenes (FR-014)

Con Pillow (ya dependencia), frame a frame y sin cargar todo el archivo a la vez:
mismo formato; mismas dimensiones y modo; mismo `n_frames`; para animaciones, misma duración por
frame y `loop`; **bytes de píxel decodificados idénticos** por frame; mismo perfil ICC; misma
Orientation EXIF efectiva (1 o ausente cuentan igual). Se respeta el límite anti-bomba de
descompresión de Pillow; superarlo da `clean_result_invalid` (no se fuerza). Como la limpieza
copia byte a byte los datos de imagen, la igualdad es exacta: tolerancia 0.

### Equivalencia de vídeo (FR-014)

1. `ffprobe` de ambos: mismos streams de vídeo y audio, en el mismo orden, con igual `codec_name`,
   `profile`, `width`/`height`, `pix_fmt`, `sample_rate`, `channels` y rotación (side data
   *display matrix*).
2. **Sin recodificación ni pérdida de muestras**: `ffmpeg -map 0:V -map 0:a? -c copy -f
   streamhash -hash sha256` de ambos archivos debe coincidir stream a stream (verificado
   empíricamente). Es una lectura secuencial sin decodificar, limitada por E/S.
3. **Duración y sincronía**: para cada stream, `|start_time₁ − start_time₂|` y
   `|duration₁ − duration₂|` ≤ **max(1 intervalo de frame del stream, 50 ms)**. Justificación:
   los paquetes son idénticos (paso 2), así que la diferencia solo puede venir del redondeo de la
   base de tiempo del muxer y de la escritura de la lista de edición, que nunca supera un frame;
   50 ms cubre audio sin frame rate definido y está por debajo del umbral perceptible de desfase
   audio/vídeo (~45 ms de adelanto).

Cualquier fallo → se descarta el resultado (`clean_result_invalid`).

### Corrección necesaria en el sanitizador JPEG

Reescribir el APP0 JFIF con `Xthumbnail = Ythumbnail = 0` y sin datos de miniatura (se conservan
versión, unidades y densidad). Es el único cambio de comportamiento del sanitizador. **Ver
aprobado (C4): spec FR-013 y US2-9.**

---

## §5. Evidencia persistente

**Decisión**: tabla nueva `metadata_inspections`, una fila por (media, rol), roles `original` y
`clean_copy`, con upsert. Cuando no hay copia, el publish file es el original y se usa la
evidencia `original`: así se guarda exactamente "la última del original y la del publish file"
sin duplicar filas. Esquema en [data-model.md](data-model.md).

- El **checksum guardado es el de los bytes realmente leídos** durante la inspección (se calcula
  el SHA-256 en la misma pasada), no una copia del valor de la BD. Si difiere del checksum que la
  BD espera para ese rol, la inspección se guarda como `error` / `file_changed`. Esto ata la
  evidencia a los bytes (FR-002 b).
- Se guardan categorías y nombres de clave saneados (§2), la lista de bloques no clasificables
  (nombres saneados), los técnicos conservados (etiquetas fijas), un `reason_code` y la fecha.
- **`metadata_status`**: se mantiene como **indicador de existencia de copia** (lo leen el
  resolvedor, publishers, borrado y backup; cambiarlo tocaría todos los publishers sin aportar
  nada). La migración convierte `clean` → `unknown` y restringe el CHECK a `unknown`/`sanitized`
  (`batch_alter_table`, patrón ya usado en 0015/0019). Sale de la API pública (`ContentRead`), que
  pasa a exponer el estado derivado. El nombre de la columna queda como deuda menor documentada.

**Alternativas rechazadas**: columnas de evidencia en `contents` (mezcla dos roles y multiplica
nulos); historial completo de inspecciones (no se pide, crece sin límite); reutilizar
`metadata_status` como estado visible (es justo el booleano editable que la spec prohíbe).

---

## §6. Derivación del estado

Función pura `derive_metadata_state(content, evidence_by_role, publish_available, activity)`:

1. Rol del publish file = `clean_copy` si `metadata_status = sanitized`, si no `original`.
2. Publish file no disponible (comprobación barata existencia + tamaño, la misma que ya hace
   `publish_file_read`) → `error` / `file_unavailable`.
3. Sin evidencia para ese rol, o `evidence.checksum ≠ effective_checksum(content)`, o
   `evidence.rules_version ≠ INSPECTION_RULES_VERSION` → `not_checked`.
4. `evidence.result = error` → `error` (con su `reason_code`).
5. `evidence.findings` no vacío → `metadata_found` (aunque además haya no clasificables).
6. `evidence.result = incomplete` → `incomplete`.
7. En otro caso → `verified_clean`, variante `already_clean` (rol original) o `cleaned_copy`.

`activity` (`checking` / `cleaning` / null) se añade desde memoria (guard) y no altera el estado.
**Aprobado (C1)**: la precedencia solo afecta al estado visible. La evidencia conserva
`result = incomplete` con sus `findings` y `unclassified`; la API expone
`inspection_complete = false` y el detalle dice "Metadata found; the file could not also be fully
inspected." Tras Clean metadata, 🟢 exige que la evidencia de la copia sea `complete` sin
hallazgos ni no clasificables.

---

## §7. Versionado de reglas

`INSPECTION_RULES_VERSION: int` en el módulo común de inspección, empezando en `1`. Se incrementa
a mano cuando cambie cualquier tabla de clasificación o regla. Para que no se olvide: un test
calcula un digest determinista de las tablas de clasificación y lo compara con un valor anotado
junto a la versión; si las tablas cambian sin actualizar ambos, el test falla con un mensaje que
pide subir la versión. Al subirla, toda evidencia queda obsoleta (§6 paso 3) → `not_checked` → el
backfill la vuelve a inspeccionar. Sin migraciones de reglas.

---

## §8. Backfill, import y Check again

**Decisión**: un hilo daemon `MetadataInspector` (patrón de `AnalyticsRefresher`), arrancado en
el lifespan después del scheduler y parado antes que él.

- **Cola de prioridad en memoria**: ids encolados por la importación y por la limpieza; se sirven
  antes que el backfill. Se pierde al reiniciar sin consecuencia: lo pendiente se recalcula desde
  la BD.
- **Backfill**: cuando la cola está vacía, pide a la BD un lote (p. ej. 20) de media cuyo publish
  file no tiene evidencia válida (falta, checksum distinto o versión antigua), más recientes
  primero, y los inspecciona **uno a uno** con una pausa corta entre ítems. Es "reanudable" por
  construcción: lo ya verificado tiene evidencia válida y no vuelve a salir.
- **Sin reintentos agresivos**: una evidencia `error` o `incomplete` para (checksum, versión)
  cuenta como procesada. Única excepción: `tool_unavailable` (ffprobe/ffmpeg ausente) se
  reintenta una vez por arranque del proceso.
- **No interfiere**: solo lee archivos; no toma `claiming` ni `sanitizing`; si un media está en
  limpieza o borrado se salta en esta vuelta. La escritura de evidencia es condicional (el media
  existe y su checksum efectivo sigue siendo el inspeccionado); si no, se descarta (spec: "una
  inspección de un archivo que ya no es el publish file se descarta").
- **Import**: sin cambios en la validación ni en la transacción; tras el commit se encola el id
  con prioridad y se despierta el worker. Un fallo del worker no afecta a la importación. La
  respuesta de import devuelve el media en `not_checked`.
- **Check again**: síncrono en la petición (inspecciona original y, si existe, copia; guarda
  evidencias; devuelve el media). Prioridad real sin colas: no espera al worker. Una inspección
  concurrente del worker sobre el mismo media es inocua (mismo upsert condicional).
- **Library nunca inspecciona**: el listado solo hace una consulta extra de evidencias por lote
  de ids y reutiliza el `stat` que ya hace para `publish_file`.
- **Frontend**: Library y detalle hacen polling ligero (cada 3 s, patrón de `usePostsData`)
  solo mientras algún media visible esté `not_checked` o con `activity`; se detiene en cuanto
  no queda ninguno.

---

## §9. Seguridad de metadata

Auditoría del código actual frente a FR-010/FR-026:

| Ubicación | Problema | Acción |
|---|---|---|
| `video_metadata.py:92` | `logger.debug("ffmpeg failed: %s", stderr[-2000:])`: stderr de ffmpeg puede contener tags y rutas | Eliminar; registrar solo código de salida |
| `video_metadata.py:88`, `:145`; `media.py:197`, `:309` | `exc_info=True` en debug: el traceback de `CalledProcessError` incluye la línea de comandos (ruta) y puede arrastrar salida | Registrar solo el nombre de la clase de excepción (patrón de `scheduler.py`) |
| `inspect_*` (todos) | Devuelven solo categorías y claves, pero los nombres de clave son texto libre | Saneado de nombres (§2) |
| Evidencia en BD | Nueva | Solo enumeraciones, categorías, nombres saneados, etiquetas fijas, checksum y fecha; un test recorre las evidencias de los fixtures y comprueba que no aparece ningún valor sembrado (coordenadas, `iPhone 15`, prompt, fecha original, identificador) |
| Mensajes de error de la API | Ya genéricos | Catálogo cerrado de mensajes (contracts/api.md) |

Test transversal: con `caplog` a nivel DEBUG durante inspección, limpieza y fallo forzado de
ffmpeg/ffprobe, ningún valor sembrado aparece en los logs.

---

## §10. Fixtures y oráculo

- Fixtures **generados en los tests** (patrón actual: no hay carpeta de binarios): bytes
  construidos a mano para imágenes (EXIF con GPS/serie/ImageUniqueID, XMP con DocumentID, IPTC,
  COM, JFIF con miniatura, IFD1, APPn desconocido, chunks PNG de texto/ComfyUI/privados, WebP
  animado con EXIF, trailers) y vídeos generados con `ffmpeg` (`lavfi testsrc`/`sine`) con tags,
  claves Apple, `loci`, `uuid` XMP inyectado (caja escrita a mano), fechas de cabecera, pista de
  timecode, carátula, nombre de pista WebM, `Attachments`, cluster de tamaño desconocido.
- Tests de vídeo reales con el marcador `real_ffprobe` existente; la CI ya instala ffmpeg.
- **ExifTool solo como oráculo**: tests marcados que se omiten (`skipif`) si `exiftool` no está;
  comprueban que tras Clean metadata ExifTool no ve ninguno de los valores sembrados. Los tests
  principales no dependen de él.
