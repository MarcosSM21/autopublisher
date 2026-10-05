# Quickstart: validación de la biblioteca de contenido

**Feature**: `003-content-library` | **Fecha**: 2026-10-05

Guía para comprobar de extremo a extremo que la feature cumple su especificación. Contratos
en [contracts/api.md](contracts/api.md); reglas de datos en [data-model.md](data-model.md).

## Prerrequisitos

- Los mismos que la Feature 002 (Python 3.12+ con uv, Node.js 22+ con npm), con dependencias
  actualizadas (`uv sync` en `backend/`, `npm install` en `frontend/`).
- Opcional: `ffmpeg`/`ffprobe` en el `PATH` para obtener dimensiones y duración de vídeos y
  para ejecutar el test de integración real (sin ellos, ese test se omite y los vídeos se
  importan con esos datos vacíos).
- Algunas imágenes (JPEG/PNG/WebP) y vídeos (MP4/MOV/WebM) propios en una carpeta fuera del
  repositorio, p. ej. `~/Pictures/l4i4-test/`.

## 1. Checks automáticos (SC-008)

```bash
cd backend
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

Esperado: todo pasa.

## 2. Arranque con datos aislados

```bash
cd backend
export AUTOPUBLISHER_DB_PATH="$(mktemp -d)/autopublisher.db"
export AUTOPUBLISHER_MEDIA_DIR="$(dirname "$AUTOPUBLISHER_DB_PATH")/media"
uv run uvicorn app.main:app --reload

cd frontend
npm run dev                                 # http://localhost:5173
```

Sin las variables, la base y los archivos se guardan en `backend/data/` (ignorado por Git:
`git status` no muestra nada tras importar).

## 3. Flujo de referencia (SC-001)

1. Crear (o abrir) el proyecto **L4i4** y abrir su vista **Content**: se ve el estado vacío.
2. Calcular el hash de un original para comprobarlo después:
   `sha256sum ~/Pictures/l4i4-test/<una-imagen>`.
3. Arrastrar varias imágenes y vídeos a la zona de importación. Se ve el progreso
   "Importing N of M…" y, al terminar, la lista de resultados con todos marcados como
   importados.
4. Comprobar la copia:
   `ls "$AUTOPUBLISHER_MEDIA_DIR/projects/<id-de-L4i4>/"` muestra un archivo por contenido con
   nombre generado. `sha256sum` de cada copia coincide con el `checksum` mostrado en el detalle
   y con el hash del paso 2 para esa imagen.
5. En la biblioteca, cada elemento muestra preview, insignia Image/Video, nombre y fecha. Abrir
   un vídeo y reproducirlo.
6. Editar título, descripción y hashtags (p. ej. `#l4i4 summer, reels`) de un contenido y
   guardar. Los hashtags quedan como `l4i4`, `summer`, `reels`.
7. Detener backend y frontend y volver a arrancarlos con las **mismas** variables. Comprobar
   que contenidos, previews y metadata siguen intactos.
8. Mover o borrar uno de los originales de `~/Pictures/l4i4-test/` y comprobar que su
   contenido sigue visible (SC-004).
9. Volver a arrastrar uno de los archivos ya importados (también renombrado): el resultado lo
   marca como **duplicado**, indicando el contenido existente; el número de contenidos y de
   archivos en `projects/<id>/` no cambia (SC-005).
10. Comprobar que los originales que no se movieron siguen en su sitio con el mismo
    `sha256sum` (SC-006).

## 4. Lote mixto (SC-003)

Arrastrar en una sola operación:

- 2 imágenes nuevas;
- un `.txt`;
- un archivo vacío (`touch empty.jpg`);
- un texto renombrado a `.mp4`;
- una imagen ya importada.

Esperado:

- 2 importados;
- 3 rechazados con motivo (`Unsupported file format…` ×2, `The file is empty.`);
- 1 duplicado.

## 5. Validaciones por API

Con el backend en marcha (L4i4 tiene `id` 1; el contenido `1` existe):

```bash
API=http://127.0.0.1:8000/api

curl -i -F files=@photo.jpg $API/projects/9999/contents
# 404 not_found; no se crea nada

curl -i -F files=@notes.txt $API/projects/1/contents
# 200; results[0].status = "rejected", error.code = "unsupported_format"

curl -i -X PATCH $API/contents/1 -H 'Content-Type: application/json' \
  -d '{"hashtags":["has space"]}'
# 422 validation_error (field: hashtags)

curl -s -X PATCH $API/contents/1 -H 'Content-Type: application/json' \
  -d '{"title":"Same"}' && \
curl -s -X PATCH $API/contents/1 -H 'Content-Type: application/json' \
  -d '{"title":"  Same  "}'
# Mismo updated_at en las dos respuestas (FR-021)

curl -i -X DELETE $API/contents/1
# 405 method_not_allowed
```

Desactivar L4i4 desde la UI: la zona de importación se deshabilita con una explicación, y la
biblioteca y la edición de metadata siguen funcionando.

## 6. Rendimiento (SC-002, SC-007)

- Importar en una operación 30 archivos de tamaño habitual: el resultado completo aparece en
  menos de 1 minuto.
- Con ≥ 200 contenidos en un proyecto, abrir la vista Content: se muestra y es utilizable en
  menos de 2 segundos.
