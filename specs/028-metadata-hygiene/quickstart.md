# Quickstart / validación: Media Metadata Hygiene (Feature 028)

Contrato en [contracts/api.md](contracts/api.md); estados en [data-model.md](data-model.md).

## Requisitos

- Backend y frontend como en el README; `ffmpeg` y `ffprobe` en el `PATH`.
- Validar en una **instancia de prueba** (`AUTOPUBLISHER_CONFIG` con copia de datos y keyring
  desactivado), nunca en la instalación real.

## Tests dirigidos

```bash
cd backend
uv run pytest tests/test_remove_metadata_api.py tests/test_image_metadata.py
uv run pytest tests/test_video_metadata.py -m real_ffprobe
cd ../frontend
npx vitest run src/pages/library
```

(Los casos concretos los fija `tasks.md`; la suite completa la ejecuta la CI del PR.)

## Escenarios manuales

1. **Badges**: en la Library, un media recién importado muestra 🟡 *Metadata not cleaned*; uno ya
   limpiado, 🟢 *Metadata cleaned*. En el detalle, el mismo badge con su motivo (*Not cleaned yet*,
   *Already clean*, *Cleaned copy*).
2. **Clean metadata (imagen)**: importar un JPEG con GPS, abrir el detalle y pulsar **Clean
   metadata** en la cabecera → el badge pasa a 🟢 *Cleaned copy* sin recargar; al volver a la
   Library, la card también está en 🟢. *Inspect metadata* muestra la copia sin metadata.
3. **Clean metadata (vídeo)**: con un MOV con metadata (ubicación, modelo, fecha) → 🟢 *Cleaned
   copy*.
4. **Miniatura JFIF**: un JPEG con miniatura JFIF → *Inspect metadata* la lista (*JFIF thumbnail*);
   tras Clean metadata, `exiftool -JFIF:all <copia>` no muestra miniatura y la imagen se ve igual.
5. **Copia ausente**: borrar la copia limpia de un media `sanitized` → la card muestra 🟡 *Clean copy
   missing*; Clean metadata la regenera → 🟢.
6. **Sin ffprobe**: con `PATH` sin ffprobe, Clean metadata en un vídeo `unknown` → error "The
   cleaned file could not be checked…" y el badge sigue 🟡; las imágenes se limpian igual.
7. **Móvil**: en un viewport estrecho, el badge de metadata y el de uso caben en la card.
8. **Logs**: con logging DEBUG, forzar un fallo de ffmpeg/ffprobe y buscar los valores sembrados
   (`40.4168`, `iPhone 15`) en el log → ninguna coincidencia.

## Cierre

Una sola vez antes del PR: tests dirigidos pendientes, `ruff check`, `ruff format --check`,
`mypy`, `npm run lint`, `npm run typecheck`, `npm run build`, `git diff --check` y revisión de
seguridad del diff.
