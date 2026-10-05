# Implementation Plan: Biblioteca de contenido e importación local de imágenes y vídeos

**Branch**: `003-content-library` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-content-library/spec.md`

## Summary

Introducir la entidad `Content` y la biblioteca multimedia por proyecto.

**Backend**:

- Nueva tabla `contents` (migración Alembic `0002`).
- Endpoint multipart para importar uno o varios archivos. Cada archivo:
  1. se copia en streaming a un directorio temporal, calculando SHA-256 y tamaño;
  2. se valida por su firma real (JPEG, PNG, WebP, MP4, MOV, WebM), con Pillow para
     imágenes;
  3. se comprueba como duplicado con `UNIQUE(project_id, checksum)`;
  4. se enriquece con dimensiones y duración (Pillow; `ffprobe` opcional para vídeo);
  5. se mueve de forma atómica a `<media>/projects/<id>/<uuid>.<ext>`.
- La respuesta da un resultado por archivo (importado, duplicado o rechazado).
- Rutas para listar, consultar, editar metadata (con la regla idempotente de `updated_at`) y
  servir el archivo para preview.

**Frontend**: `ProjectDetail` gana una vista "Content" con:

- drag & drop y selector múltiple;
- envío secuencial de un archivo por petición, con progreso y resultados;
- grid con previews nativas;
- detalle con edición de título, descripción y hashtags.

Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**:

- Backend: FastAPI, SQLAlchemy 2.x y Alembic (existentes), más **`python-multipart`**
  (formularios multipart) y **Pillow** (validación y dimensiones de imágenes).
- Herramienta externa opcional: `ffprobe`.
- Frontend: React + Vite, sin dependencias nuevas.

**Storage**:

- SQLite (`AUTOPUBLISHER_DB_PATH`, existente): nueva tabla `contents`.
- Sistema de archivos local en `AUTOPUBLISHER_MEDIA_DIR` (por defecto `backend/data/media`,
  ignorado por Git).

**Testing**:

- Backend: pytest + `TestClient`, con base y raíz multimedia en `tmp_path`, imágenes
  generadas con Pillow y cabeceras de vídeo sintéticas.
- Frontend: Vitest + Testing Library + user-event, con `FakeApi` ampliado.

**Quality tooling**: sin cambios (Ruff, mypy strict; Oxlint, Prettier, `tsc -b`); CI sin
cambios (`uv sync --locked` instalará las nuevas dependencias)

**Target Platform**: uso local en Linux/macOS; CI en `ubuntu-latest`

**Project Type**: aplicación web local (frontend + backend separados)

**Performance Goals**: 30 archivos habituales importados con resultado en < 1 min (SC-002);
biblioteca de 200 contenidos utilizable en < 2 s (SC-007)

**Constraints**:

- Copia exacta sin transformación (FR-014).
- Nunca registro sin archivo ni archivo registrado a medias (FR-007).
- Sin rutas absolutas en la API (FR-028).
- Sin borrado (FR-023).
- `updated_at` solo con cambios efectivos (FR-021).

**Scale/Scope**:

- 1 tabla nueva y 5 operaciones de API.
- Límites: 2 GiB por archivo, 100 archivos por operación.
- 1 vista nueva con ~4 componentes.

No quedan `NEEDS CLARIFICATION`: los aspectos que la spec delegó al plan (formatos, límites,
checksum, forma de la API, comportamiento ante duplicados) se resuelven en
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Dos dependencias nuevas con necesidad concreta:<br>• `python-multipart`: imprescindible para subir archivos con FastAPI.<br>• Pillow: valida imágenes y da sus dimensiones.<br>`ffprobe` es opcional y no es una dependencia del proyecto. La detección de formato es un módulo propio pequeño, sin libmagic. Sin capa de servicios genérica, sin thumbnails, sin router ni librería de drag & drop. Hashtags como lista JSON en lugar de una tabla. | ✅ |
| II. Spec-Driven Development | El plan sigue la spec aprobada y su aclaración de FR-021. Las decisiones que la spec delegó (formatos, límites, duplicados) quedan documentadas y no amplían el alcance. | ✅ |
| III. Arquitectura modular | Responsabilidades separadas en módulos:<br>• `media.py`: detección de formato y metadata técnica.<br>• `storage.py`: sistema de archivos.<br>• `contents.py`: API.<br>• `models.py` y `migrations/`: persistencia.<br>No hay lógica de plataforma: el contenido es agnóstico de red social y se guarda una copia única reutilizable (FR-012), preparada para los futuros adaptadores. | ✅ |
| IV. Seguridad (repositorio público) | • La multimedia vive en `backend/data/media` (ya cubierta por `data/` y `media/` en `.gitignore`).<br>• Ningún fichero multimedia se versiona: los tests generan sus datos en memoria o en `tmp_path`.<br>• El nombre original no participa en las rutas (sin *path traversal*).<br>• `ffprobe` se invoca sin shell y con *timeout*.<br>• La API no expone rutas internas. | ✅ |
| V. Calidad y verificabilidad | Tests para cada punto de SC-008, incluidos fallo parcial de lote, duplicados intra-lote, persistencia tras reabrir base y raíz multimedia, ausencia de residuos tras fallos de guardado e idempotencia de `updated_at`. Resultado visible por archivo: ningún rechazo es silencioso. | ✅ |
| VI. Git y trazabilidad | Rama `003-content-library`; commits pequeños en inglés; README actualizado (multimedia, `AUTOPUBLISHER_MEDIA_DIR`, formatos, límites, `ffprobe` opcional). | ✅ |
| Arquitectura tecnológica base | SQLite para datos y sistema de archivos local para multimedia, como fija la Constitution; API REST. Scheduler y adaptadores siguen sin aplicar. | ✅ |
| Idioma y convenciones | Código, mensajes de API y UI, README y commits en inglés; artefactos Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS (el diseño de Fase 1 no
añade dependencias ni estructura más allá de lo listado).

## Project Structure

### Documentation (this feature)

```text
specs/003-content-library/
├── plan.md              # Este archivo
├── research.md          # Fase 0: subida, formatos, metadata, checksum, almacenamiento, UI
├── data-model.md        # Fase 1: Content, validaciones, updated_at, disco
├── quickstart.md        # Fase 1: guía de validación de extremo a extremo
├── contracts/
│   └── api.md           # Fase 1: contrato REST de contenidos e importación
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml               # + python-multipart, pillow
├── uv.lock
├── migrations/versions/
│   └── 0002_create_contents.py  # Tabla contents + índices/únicos
├── app/
│   ├── main.py                  # create_app(db_path, media_dir): prepara la raíz multimedia
│   │                            #   y vacía tmp/ en el lifespan; incluye router contents
│   ├── config.py                # + get_media_dir() (AUTOPUBLISHER_MEDIA_DIR), límites
│   ├── models.py                # + MediaType, MediaFormat (StrEnum), Content
│   ├── schemas.py               # + ContentRead, ContentUpdate (normalización de hashtags),
│   │                            #   ImportItemResult, ImportResult
│   ├── media.py                 # detect_format(header) → MediaFormat | None;
│   │                            #   read_image_info (Pillow); probe_video (ffprobe opcional)
│   ├── storage.py               # MediaStorage: raíz, tmp, receive_upload (copia + SHA-256 +
│   │                            #   límite), commit (os.replace a ruta final), discard,
│   │                            #   resolve(relative) con comprobación de que está bajo la raíz
│   └── contents.py              # Router: listar, importar, consultar, PATCH, servir archivo
└── tests/
    ├── conftest.py              # + fixture media_dir, helpers make_image/make_video_header,
    │                            #   upload helper; ffprobe sustituido por defecto
    ├── test_media.py            # Detección por firma (todos los formatos, brands rechazadas,
    │                            #   extensión engañosa), Pillow inválido, probe_video tolerante
    ├── test_contents_import.py  # Imagen válida, vídeo válido, múltiple, fallo parcial,
    │                            #   duplicado (mismo proyecto, renombrado, intra-lote,
    │                            #   otro proyecto), proyecto inexistente/inactivo, límites,
    │                            #   vacío, storage_error sin residuos, original intacto
    ├── test_contents_api.py     # Listado y orden, consulta, PATCH y normalización, updated_at
    │                            #   idempotente, campos no editables, servir archivo/Range,
    │                            #   file_available=false, DELETE → 405
    ├── test_persistence.py      # + contenidos y archivos tras reabrir base y raíz multimedia
    ├── test_migrations.py       # + 0002 sobre base con datos de 0001 (sin pérdida)
    └── test_ffprobe_integration.py  # ffmpeg/ffprobe reales; skip si no están instalados

frontend/src/
├── types.ts                     # + Content, ImportResult, ImportItemResult, MediaType
├── api.ts                       # + listContents, getContent, importFile, updateContent;
│                                #   request() sin Content-Type JSON cuando el cuerpo es FormData
├── utils.ts                     # + formatBytes, formatDuration, parseHashtags
├── test-fake-api.ts             # + contenidos, importación y servir archivo simulados
├── index.css                    # + estilos de dropzone, grid y estados de resultado
└── components/
    ├── ProjectDetail.tsx        # + selector de vista "Accounts | Content"
    ├── ContentLibrary.tsx       # Carga, estado vacío, grid, selección, orquesta importación
    ├── ContentLibrary.test.tsx  # Estado vacío, grid, drag & drop, selector múltiple,
    │                            #   resultados mixtos, proyecto inactivo, detalle y edición
    ├── ContentImport.tsx        # Dropzone + input multiple, límite de lote, progreso,
    │                            #   envío secuencial y lista de resultados por archivo
    └── ContentDetail.tsx        # Preview grande, metadata completa, formulario de edición

README.md                        # + multimedia local, AUTOPUBLISHER_MEDIA_DIR, formatos,
                                 #   límites, ffprobe opcional
```

**Structure Decision**: se mantienen `backend/` y `frontend/` con el paquete plano `app/`.
La lógica de importación vive en el router `contents.py`, como en las Features 001 y 002,
apoyada en dos módulos con responsabilidad técnica propia:

- `media.py`: entender el archivo;
- `storage.py`: dónde y cómo se guarda.

Ambos se prueban de forma aislada y se reutilizarán en features futuras (publicadores que
lean el archivo). No se introduce una capa de servicios genérica.

## Design Notes

- **Configuración**:
  - `create_app(db_path=None, media_dir=None)` resuelve la raíz multimedia en este orden:
    argumento → `AUTOPUBLISHER_MEDIA_DIR` → `backend/data/media`.
  - En el lifespan crea `projects/` y `tmp/` y vacía `tmp/`.
  - `app.state.storage` guarda la instancia de `MediaStorage`.
- **Importación por archivo** (dentro del endpoint, en orden):
  1. *basename* y recorte del nombre original;
  2. `storage.receive_upload` lee el `UploadFile` en bloques de 1 MiB y los escribe en
     `<media>/tmp/`, calculando SHA-256 y tamaño, y aborta al superar 2 GiB. El archivo
     nunca se carga completo en memoria; todo lo posterior trabaja sobre el temporal en
     disco;
  3. `empty_file`;
  4. `detect_format` sobre los primeros bytes;
  5. validación de imagen con Pillow;
  6. consulta de duplicado por `(project_id, checksum)`;
  7. `probe_video` si es vídeo;
  8. `INSERT` + `flush()`;
  9. `storage.commit` → `os.replace` a la ruta final (mismo filesystem que `tmp/`);
  10. commit de la sesión.

  El archivo solo se mueve al almacenamiento definitivo cuando está validado y la fila ha
  pasado el `flush`. Cada archivo se procesa dentro de un `try/finally` que descarta el
  temporal ante cualquier rechazo o error, y cada fallo produce su `ImportItemResult`. Si el
  `flush` o el commit fallan, se hace rollback y, si ya se había movido, se borra el archivo
  final. Un `IntegrityError` de `(project_id, checksum)` da `duplicate` (consultando el
  existente); cualquier otro fallo da `storage_error`, con el detalle registrado en el log y
  no en la respuesta.
- **Validación de petición**: proyecto (404/409) y número de archivos (422) se comprueban
  antes de tocar ningún archivo.
- **Seguridad de rutas**: `storage.resolve()` convierte la ruta relativa de la base en
  absoluta y verifica que queda dentro de la raíz antes de servirla.
- **`file_available`**: se calcula al serializar (`Path.is_file()`); es barato para cientos de
  elementos.
- **Errores**: se reutilizan `NotFoundError`, `ConflictError` y los manejadores existentes.
  Los rechazos por archivo no son excepciones HTTP: forman parte del cuerpo `200`.
- **UI**:
  - `ContentImport` valida el límite de 100 antes de enviar y envía los archivos uno a uno
    con `importFile(projectId, file)`.
  - Muestra "Importing i of N…" y deshabilita la zona mientras dura la importación.
  - Agrega resultados en tres grupos con estilos distintos: imported, duplicate (con enlace
    para abrir el contenido existente) y rejected (con motivo).
  - Si una petición devuelve `404`/`409 project_inactive`, aborta el resto e informa.
  - Un error de red en un archivo lo marca como rechazado y continúa.
  - Al terminar recarga la biblioteca desde la API.
  - La zona se deshabilita con explicación si el proyecto está inactivo.
- **Previews**:
  - Imágenes: `<img loading="lazy">`.
  - Vídeos en el grid: `<video preload="metadata" muted>`.
  - Vídeos en el detalle: `<video controls>`.
  - Si el navegador no puede reproducir el formato (`onError`) o `file_available` es `false`,
    se muestra un marcador con el tipo y el aviso correspondiente.
- **Hashtags en la UI**: un campo de texto. `parseHashtags` divide por espacios y comas; el
  backend normaliza y valida, y sus errores se muestran junto al campo.
- **Tests de persistencia**: misma técnica que la Feature 002, reabriendo además la misma
  raíz multimedia y comprobando que `GET /file` devuelve bytes idénticos (SHA-256) a los
  subidos.
- **CI**: sin cambios de workflow. El test con `ffprobe` real se ejecuta si `ubuntu-latest`
  lo trae y se omite si no.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
