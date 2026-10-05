# Research: Biblioteca de contenido e importación local

**Feature**: `003-content-library` | **Fecha**: 2026-10-05

Decisiones técnicas de la Fase 0. Todas parten del stack ya establecido en las Features 001 y
002 (FastAPI + SQLAlchemy 2.x + Alembic sobre SQLite; React + Vite) y de la Constitution
(simplicidad, seguridad en repositorio público).

## 1. Recepción de archivos en la API

- **Decision**: `POST /api/projects/{project_id}/contents` con `multipart/form-data` y un
  campo repetible `files` (1–100 archivos por petición). Se añade la dependencia
  **`python-multipart`**, que FastAPI necesita para leer formularios multipart. El endpoint es
  síncrono (`def`), por lo que FastAPI lo ejecuta en el threadpool y el hashing y la copia no
  bloquean el event loop.
- **Rationale**: es el mecanismo estándar de FastAPI para subir archivos; acepta uno o varios
  archivos en la misma ruta, como pide la spec (FR-001, FR-027).
- **Alternatives considered**: enviar rutas locales del usuario para que el backend las copie
  (rechazado: el navegador no expone rutas, y obligaría al backend a leer cualquier ruta del
  disco); subida en trozos/reanudable (complejidad innecesaria para una app local);
  base64 en JSON (+33 % de tamaño y todo en memoria).

## 2. Envío de lotes desde el frontend

- **Decision**: el usuario elige o arrastra N archivos en una operación; el frontend comprueba
  el límite de lote (100) y después los envía **secuencialmente, un archivo por petición**,
  acumulando los resultados por archivo y mostrando el progreso "Importing 12 of 30…". El
  backend sigue aceptando varios archivos por petición (probado en los tests de API).
- **Rationale**:
  - Progreso real por archivo (FR-032) sin APIs de progreso de subida.
  - Aislamiento natural de fallos: un error de red o del servidor en un archivo no afecta a los
    demás (FR-005).
  - Evita peticiones de varios GB que Starlette tendría que volcar enteras a disco temporal
    antes de procesarlas.
  - Los duplicados dentro del mismo lote se detectan solos: el segundo ya encuentra el
    primero en la base de datos (FR-016).
- **Alternatives considered**: una única petición con todo el lote (sin progreso útil y con
  picos de disco/memoria); subidas en paralelo (sin ventaja relevante en local y complica el
  orden y la detección de duplicados intra-lote).

## 3. Formatos soportados y detección del tipo real

- **Decision**: lista cerrada:

  | Tipo | Formato | Firma comprobada | Extensión almacenada | MIME servido |
  |------|---------|------------------|----------------------|--------------|
  | image | JPEG | `FF D8 FF` | `.jpg` | `image/jpeg` |
  | image | PNG | `89 50 4E 47 0D 0A 1A 0A` | `.png` | `image/png` |
  | image | WebP | `RIFF` + `WEBP` en bytes 8–11 | `.webp` | `image/webp` |
  | video | MP4 | `ftyp` en bytes 4–7 con *major brand* de la lista MP4 | `.mp4` | `video/mp4` |
  | video | MOV | `ftyp` en bytes 4–7 con *major brand* `qt  ` | `.mov` | `video/quicktime` |
  | video | WebM | EBML `1A 45 DF A3` con DocType `webm` en la cabecera | `.webm` | `video/webm` |

  *Major brands* MP4 aceptadas: `isom`, `iso2`, `iso4`, `iso5`, `iso6`, `mp41`, `mp42`,
  `avc1`, `M4V `, `mmp4`, `dash`, `MSNV`. Cualquier otra (`M4A `, `heic`, `mif1`, `3gp4`…)
  se rechaza como formato no soportado.

  El tipo se determina **solo por el contenido** (firma de los primeros bytes) en un módulo
  propio pequeño (`app/media.py`), sin dependencia externa. La extensión del nombre original
  y el `Content-Type` enviado por el navegador se ignoran para decidir; la extensión del
  archivo almacenado se deriva del formato detectado.
- **Rationale**: cubre los formatos habituales en redes sociales (fotos de móvil y cámara,
  capturas, exportaciones de editores de vídeo, vídeos de iPhone) y cumple FR-002
  ("comprobar el contenido real, no solo la extensión") con unas pocas comparaciones de bytes.
  Una extensión engañosa (texto renombrado a `.jpg`) se rechaza; un PNG con extensión `.jpg`
  se acepta como PNG.
- **Limitación conocida (MOV)**: los MOV modernos habituales (iPhone, cámaras y editores
  actuales) incluyen la caja `ftyp` con *brand* `qt  ` y están soportados. Los MOV antiguos
  de QuickTime sin cabecera `ftyp` (que empiezan directamente por átomos como `moov`, `mdat`
  o `wide`) pueden rechazarse como `unsupported_format`; no se añade detección específica
  para ellos.
- **Alternatives considered**: `python-magic`/libmagic (dependencia nativa del sistema, poco
  portable en CI); confiar en la extensión o el MIME del navegador (no cumple FR-002); GIF,
  HEIC, AVI, MKV (fuera del alcance mínimo: GIF animado tiene semántica ambigua imagen/vídeo,
  HEIC no se previsualiza en la mayoría de navegadores, MKV/AVI no son formatos de subida
  habituales).

## 4. Validación de imágenes y metadata técnica de imágenes

- **Decision**: añadir **Pillow**. Tras detectar la firma de imagen, se abre el archivo con
  `Image.open` (lectura perezosa de cabecera), se comprueba que el formato de Pillow coincide
  con el detectado y se leen `width`/`height`. Si Pillow no puede abrirlo, el archivo se
  rechaza como `invalid_file`. No se decodifican los píxeles ni se modifica nada; el límite
  de *decompression bomb* de Pillow se mantiene y su aviso/error se trata como archivo
  inválido.
- **Rationale**: Pillow es la librería estándar de imagen en Python. Es una extensión en C,
  pero se distribuye con wheels precompilados para todas las plataformas habituales
  (incluida la de CI), por lo que no requiere compilar ni instalar librerías del sistema. Valida que la cabecera es coherente y da las dimensiones en una
  línea. También simplifica los tests (generar imágenes válidas en memoria).
- **Alternatives considered**: parsear cabeceras JPEG/PNG/WebP a mano (~100 líneas propensas
  a errores, sobre todo JPEG); `imagesize` (no valida); omitir dimensiones (la spec las pide
  cuando sea sencillo).

## 5. Metadata técnica de vídeos

- **Decision**: usar **`ffprobe` de forma opcional**. Si el ejecutable está en el `PATH`, se
  invoca con `subprocess.run` (lista de argumentos, sin shell, *timeout* de 15 s,
  `-v error -print_format json -show_format -show_streams`) para obtener anchura, altura
  (primer stream de vídeo) y duración. Si no está disponible, falla, tarda demasiado o
  devuelve datos incompletos, el vídeo se importa igualmente con esos campos a `null`
  (FR-019). `ffprobe` **no** se usa para validar: un vídeo con firma correcta se acepta
  aunque `ffprobe` no pueda leerlo.
- **Rationale**: "cuando pueda obtenerse de forma sencilla". `ffprobe` es la herramienta de
  referencia, está en la mayoría de sistemas con ffmpeg y no añade dependencias Python. Hacerla
  opcional mantiene la app funcional sin ffmpeg y evita que CI dependa de él.
- **Testing**: la función de extracción se sustituye en los tests (monkeypatch) para cubrir
  "metadata disponible" y "no disponible"; un test adicional usa el `ffprobe` real con un
  vídeo generado por `ffmpeg` y se marca `skip` si alguno de los dos no está instalado.
- **Alternatives considered**: `pymediainfo` (requiere libmediainfo nativa); `hachoir`
  (dependencia grande y poco mantenida para tres números); parsear `mvhd`/`tkhd` de MP4 a mano
  (no cubre WebM y añade código frágil).

## 6. Checksum y detección de duplicados

- **Decision**: **SHA-256** del contenido completo, calculado en streaming (bloques de 1 MiB)
  mientras se copia el archivo al almacenamiento temporal. Se guarda en hexadecimal (64
  caracteres). Unicidad garantizada por `UNIQUE(project_id, checksum)`; antes de insertar se
  consulta si existe para devolver el contenido existente, y un `IntegrityError` de esa
  restricción durante el commit también se traduce en resultado `duplicate`.
- **Rationale**: SHA-256 es robusto (sin colisiones prácticas), está en la librería estándar
  (`hashlib`) y su coste es despreciable frente a la E/S. La restricción por proyecto permite
  el mismo archivo en proyectos distintos (FR-017).
- **Alternatives considered**: MD5/SHA-1 (débiles, sin ventaja real); BLAKE2/xxhash (más
  rápidos pero sin necesidad; xxhash añade dependencia); hash solo de una parte del archivo
  (no es robusto).

## 7. Almacenamiento local y escritura atómica

- **Decision**:
  - Raíz multimedia configurable con **`AUTOPUBLISHER_MEDIA_DIR`**; por defecto
    `backend/data/media` (ya ignorado por Git mediante `data/` y `media/`).
  - Estructura: `<media>/projects/<project_id>/<uuid4-hex>.<ext>` y un directorio de trabajo
    `<media>/tmp/`.
  - En la base de datos se guarda la **ruta relativa** a la raíz (`projects/1/3f…a9.jpg`),
    nunca absoluta, para poder mover la raíz y no exponer rutas del sistema.
  - **Sin cargar el archivo en memoria**: el `UploadFile` se lee por bloques de 1 MiB
    (`upload.file.read(CHUNK)` en el endpoint síncrono). Cada bloque actualiza el
    SHA-256 y el contador de tamaño y se escribe en el temporal; nunca se llama a `read()`
    sin tamaño ni se acumula el contenido. La detección de formato usa solo los primeros
    bytes del temporal, Pillow abre el temporal desde disco (lectura perezosa de cabecera) y
    `ffprobe` recibe su ruta. La memoria usada es constante e independiente del tamaño
    (hasta 2 GiB).
  - **Temporal en el mismo filesystem**: `tmp/` está dentro de la raíz multimedia, por lo que
    el movimiento final es un `os.replace` atómico en el mismo filesystem, sin copias
    adicionales.
  - **Limitación conocida (spooling de Starlette)**: antes de que nuestra lógica reciba el
    `UploadFile`, Starlette ya ha volcado el cuerpo multipart a un
    `SpooledTemporaryFile`. Mantiene hasta 1 MB en memoria y el resto en el directorio
    temporal del sistema (`tempfile.gettempdir()`, normalmente `/tmp`). Consecuencias:
    - cada archivo se escribe dos veces en disco (temporal de Starlette y nuestro
      `tmp/`);
    - si el directorio temporal del sistema está en `tmpfs` (memoria), un archivo grande
      ocuparía RAM durante la subida.

    Se mantiene la arquitectura: nuestro streaming de 1 MiB y nuestro `tmp/` propio no
    cambian, y la subida secuencial de un archivo por petición limita el pico a un archivo.
    **Nota opcional**: si el directorio temporal del sistema está en memoria o tiene poco
    espacio, se puede arrancar el backend con `TMPDIR` apuntando a un directorio en disco,
    p. ej. `TMPDIR=/ruta/en/disco uv run uvicorn app.main:app`. Esta limitación se
    documenta también en el README (T051).
  - Flujo por archivo:
    1. copiar en streaming desde la subida a `tmp/<uuid>.part`, calculando SHA-256 y tamaño
       y cortando en cuanto se supera el límite;
    2. detectar formato y validar;
    3. comprobar duplicado;
    4. extraer metadata;
    5. añadir la fila a la sesión y hacer `flush()` (valida restricciones, incluida la
       unicidad de `(project_id, checksum)`, sin confirmar todavía);
    6. solo si el `flush` tiene éxito, `os.replace` del temporal a su ruta final;
    7. `commit`; si falla, rollback y borrar el archivo final.
  - **Limpieza garantizada**: todo el procesamiento de un archivo se envuelve en
    `try/finally`, de modo que el temporal se borra ante cualquier rechazo, excepción o
    error (si ya se movió, no existe y la limpieza no hace nada). Al arrancar se vacía `tmp/`
    (restos de una caída del proceso).
  - El nombre almacenado lo genera AutoPublisher (UUID + extensión del formato detectado);
    el nombre original nunca participa en la ruta (FR-013).
- **Rationale**: garantiza FR-007 (nunca registro sin archivo ni archivo registrado a medias)
  con primitivas simples; la separación por proyecto cumple FR-009; el UUID evita colisiones y
  sobrescrituras.
- **Alternatives considered**: nombrar por checksum (válido, pero acopla el nombre a la
  política de duplicados); almacenamiento direccionado por contenido compartido entre
  proyectos (la spec quiere contenidos independientes por proyecto y es optimización
  prematura); guardar los archivos en SQLite como BLOB (base enorme, peor para servir vídeo).

## 8. Límites

- **Decision** (constantes en `app/config.py`, documentadas en el README):
  - tamaño máximo por archivo: **2 GiB**;
  - archivos por petición y por operación de la UI: **100**;
  - nombre original: se toma solo el *basename* y se recorta a **255** caracteres
    (conservando la extensión si cabe).

  Archivos de 0 bytes → `empty_file`.
- **Rationale**: 2 GiB cubre vídeos habituales de redes sociales (incluidos vídeos largos de
  YouTube en calidad razonable) sin aceptar cargas absurdas; 100 supera holgadamente los
  lotes reales del usuario (20–30) y el mínimo de 50 de FR-003.
- **Alternatives considered**: límites configurables por variable de entorno (innecesario
  hasta que haya una necesidad real); sin límite (riesgo de llenar el disco por error).

## 9. Formato de la respuesta de importación

- **Decision**: `200` con un objeto `ImportResult` que contiene `results` (uno por archivo, en
  el orden recibido) con `filename`, `status` (`imported` | `duplicate` | `rejected`),
  `content` (si `imported`), `existing_content` (si `duplicate`) y `error` `{code, message}`
  (si `rejected`); más un resumen `{imported, duplicates, rejected}`. Los errores de toda la
  petición (proyecto inexistente `404`, proyecto inactivo `409 project_inactive`, sin
  archivos o más de 100 `422 validation_error`) usan el formato de error de la Feature 002.
  Códigos de rechazo por archivo: `unsupported_format`, `empty_file`, `file_too_large`,
  `invalid_file`, `storage_error`.
- **Rationale**: un lote con fallos parciales no es un error HTTP; el resultado por archivo es
  justo lo que la UI debe mostrar (FR-006). Reutilizar `{code, message}` mantiene la
  coherencia con el formato existente.
- **Alternatives considered**: `207 Multi-Status` (semántica WebDAV, sin ventaja práctica);
  `201` (no siempre se crea algo).

## 10. Servir los archivos para preview

- **Decision**: `GET /api/contents/{id}/file` devuelve el archivo con `FileResponse` de
  Starlette y el MIME del formato detectado. `FileResponse` admite peticiones `Range`, lo que
  permite al `<video>` del navegador avanzar y retroceder. Si el archivo falta del disco →
  `404 not_found` ("The media file is not available."). El `Content` expone `file_url`
  (relativa a la API) y `file_available` (comprobación de existencia en disco al serializar),
  nunca la ruta de almacenamiento.
- **Rationale**: sin thumbnails (fuera de alcance); las imágenes y vídeos se muestran con
  `<img>`/`<video>` nativos a través del proxy `/api` de Vite ya existente.
- **Alternatives considered**: montar la carpeta multimedia como `StaticFiles` (expondría la
  estructura interna y saltaría la comprobación de existencia del contenido); generar
  thumbnails (fuera de alcance).

## 11. Hashtags y metadata editable

- **Decision**:
  - `hashtags` se guarda como lista JSON en una columna `JSON` de SQLAlchemy (texto en
    SQLite) y la API la recibe y devuelve como `string[]`.
  - Normalización en el esquema de entrada: recortar, quitar un `#` inicial, rechazar vacíos o
    con espacios internos, máx. 100 caracteres cada uno, eliminar repetidos comparando con
    `normalize_key` (conservando la primera aparición y el orden), máx. 30 tras deduplicar.
  - `title` (≤ 200) y `description` (≤ 5000) usan `clean_text` (vacío/espacios → `null`).
  - En la UI los hashtags se editan en un único campo de texto separado por espacios o comas;
    el frontend lo divide en lista antes de enviarlo.
- **Rationale**: una lista JSON es lo más simple para un dato que siempre se lee y escribe
  entero y no se consulta por separado (no hay búsqueda por hashtag en esta feature).
- **Alternatives considered**: tabla `content_hashtags` (normalización relacional
  innecesaria hoy); texto separado por espacios en una columna (obliga a parsear en cada
  lectura y es ambiguo).

## 12. Regla de `updated_at` en la edición de metadata

- **Decision**: igual que en la Feature 002: el `PATCH` normaliza los valores, compara cada
  campo enviado con el almacenado (los hashtags como lista ordenada exacta, por lo que
  cambiar el orden o las mayúsculas es una modificación efectiva) y solo si hay diferencias
  escribe y asigna `updated_at`. Sin `onupdate`.
- **Rationale**: aplica la aclaración de FR-021 reutilizando el patrón existente.

## 13. Interfaz

- **Decision**:
  - `ProjectDetail` gana un selector de vista "Accounts | Content" (dos botones con estado,
    sin router).
  - La vista de contenido (`ContentLibrary`) incluye:
    - zona de importación con drag & drop y botón "Choose files" (`<input type="file"
      multiple accept="…">`);
    - progreso y resultados por archivo;
    - grid con preview (`<img loading="lazy">` / `<video preload="metadata" muted>`), insignia
      Image/Video, título o nombre original y fecha;
    - panel de detalle con metadata completa y formulario de edición.
  - La importación se deshabilita con una explicación si el proyecto está inactivo.
  - El `accept` del input solo ayuda a filtrar en el diálogo; la validación real es del
    backend.
  - `api.ts` deja de forzar `Content-Type: application/json` cuando el cuerpo es `FormData`.
- **Rationale**: mantiene la UI funcional y minimalista de la Feature 002 sin nuevas
  dependencias (ni router ni librería de drag & drop: los eventos nativos `dragover`/`drop`
  bastan).
- **Alternatives considered**: `react-dropzone` (dependencia para ~30 líneas de código);
  react-router (no hay todavía suficientes vistas).

## 14. Tests

- **Decision**:
  - **Backend** (pytest + `TestClient`, base y raíz multimedia en `tmp_path`):
    - imágenes generadas con Pillow en memoria;
    - vídeos MP4/MOV/WebM como cabeceras mínimas sintéticas (válidas para la detección por
      firma), con la extracción de `ffprobe` sustituida;
    - test real con `ffmpeg`/`ffprobe` marcado `skip` si no están disponibles.
  - **Frontend** (Vitest + Testing Library):
    - `FakeApi` ampliado con contenidos y respuestas de importación;
    - drag & drop con `fireEvent.dragOver`/`fireEvent.drop` y un `dataTransfer` con `File`s;
    - selección con `userEvent.upload`.
- **Rationale**: tests rápidos, deterministas y sin archivos multimedia versionados en el
  repositorio (Constitution IV).
