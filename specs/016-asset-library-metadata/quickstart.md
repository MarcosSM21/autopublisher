# Quickstart: validación de Asset Library, Usage & Metadata

**Feature**: [spec.md](spec.md) · **Contrato**: [contracts/api.md](contracts/api.md)

Guía de validación. Los archivos de prueba con workflows reales son **privados**: se guardan
fuera del repositorio y nunca se versionan.

## Prerrequisitos

- Backend y frontend arrancados como en features anteriores (`uv run uvicorn …`,
  `npm run dev`).
- `ffmpeg` y `ffprobe` instalados para la parte de vídeo (`ffmpeg -version`).
- ComfyUI local para V1, con un workflow sencillo que guarde:
  - PNG (`Save Image`, guarda `prompt` + `workflow`);
  - WEBP animado (`Save Animated WEBP`, guarda EXIF con `workflow:`/`prompt:`) si se usa;
  - MP4/WEBM (`Video Combine` de VideoHelperSuite, guarda el JSON en `comment`) si se usa.
- ExifTool opcional, solo como herramienta de diagnóstico manual.

## Tests offline (desarrollo)

```bash
cd backend
uv run pytest tests/test_asset_usage.py tests/test_content_files.py \
  tests/test_image_metadata.py tests/test_video_metadata.py \
  tests/test_remove_metadata_api.py tests/test_publish_effective_file.py
# Regresiones de publishers afectados (solo los tocados):
uv run pytest tests/test_tiktok_*.py tests/test_instagram_publish*.py \
  tests/test_threads_publish*.py tests/test_telegram_publishing.py tests/test_publish_*.py
cd ../frontend && npx vitest run src/components/ContentLibrary.test.tsx \
  src/components/AssetUsage.test.tsx src/components/AssetFile.test.tsx
```

Los tests de vídeo se saltan si no hay ffmpeg (CI lo instala). La suite completa y los quality
gates se ejecutan en la CI del PR.

## Validación manual

### A. Uso y Asset Library (US1, US2)

1. Abrir un proyecto con contenidos: la pestaña se llama **Asset Library**.
2. Comprobar tarjetas: `Unused` en un contenido sin publicaciones; plataformas en uno
   publicado; `Scheduled` en uno programado; `Ready in TikTok` en uno enviado al inbox de
   TikTok (y no "publicado"); `Unused` en uno con publicaciones solo fallidas/canceladas.
3. Ninguna tarjeta muestra checksum, MIME, tamaño, dimensiones ni duración.
4. Buscar por parte del título y por parte del nombre de archivo; probar `Images`, `Videos`,
   `Used`, `Unused` y combinaciones; comprobar el estado vacío del filtro.
5. Abrir un asset usado: historial con plataforma, cuenta, estado, fechas; un intento
   incierto aparece marcado como incierto.

### B. Remove metadata (US3, US4)

1. Importar una foto de móvil con GPS → `Inspect metadata` muestra ubicación y dispositivo.
2. `Remove metadata` → la tarjeta muestra `Metadata clean`; el detalle dice que se publicará
   la copia sin metadata, con su tamaño y checksum; `Inspect metadata` muestra la copia sin
   categorías sensibles. La foto se ve con la misma orientación.
3. Importar un PNG ya limpio (p. ej. exportado sin metadata) → `Remove metadata` → estado
   `clean`, detalle "el original ya estaba limpio", se publica el original.
4. Vídeo con rotación de móvil → `Remove metadata` → la copia se reproduce igual (rotación,
   audio sincronizado, duración).
5. Con ffmpeg ausente (p. ej. `PATH` sin ffmpeg al arrancar) → `Remove metadata` en vídeo
   falla con mensaje que menciona ffmpeg; en imagen funciona; importar y publicar funcionan.
6. Publicar (Telegram o la plataforma más cómoda) un asset sanitizado → el archivo recibido
   no contiene la metadata (descargarlo y comprobar con ExifTool como diagnóstico).
7. Borrar a mano la copia `.clean` de un asset sanitizado → publicar falla con
   `media_unavailable` (no se envía el original) → `Remove metadata` regenera la copia.
8. TikTok con consentimiento confirmado → `Remove metadata` → el consentimiento pide
   confirmarse de nuevo.

### V1 — ComfyUI (obligatoria, criterio SC-001)

Para cada formato de ComfyUI que se use realmente (como mínimo PNG):

1. Arrastrar el **original** a ComfyUI → el workflow se reconstruye.
2. Importarlo en AutoPublisher y pulsar `Remove metadata`.
3. Descargar la copia sanitizada (p. ej. publicarla en un canal de prueba de Telegram y
   descargarla, o copiarla desde el directorio de media para la prueba) y arrastrarla a
   ComfyUI.
4. Confirmar que ComfyUI **no** reconstruye el workflow.

**STOP** si el workflow sigue siendo recuperable: la feature no puede cerrarse.

## Resultados

### V1 PNG temprana (T028) — 2026-10-16 — **PASS**

- Archivos: 2 PNG reales y privados de ComfyUI (`Save Image`), copiados al scratchpad de
  la sesión; nunca versionados. Ambos con `tEXt[prompt]`, `tEXt[workflow]` y `tEXt[AIGC]`.
- Sanitización con `sanitize_image(..., "png")` desde un script desechable.
- ComfyUI local (frontend 1.51.9) en `127.0.0.1:8189`, sin custom nodes; drag-and-drop
  simulado con Playwright (eventos `dragenter`/`dragover`/`drop` sobre el canvas).

| Comprobación | Archivo 1 | Archivo 2 |
|---|---|---|
| Original soltado en ComfyUI reconstruye el workflow | ✅ 68 nodos (KSampler, CLIPLoader, …) | ✅ 69 nodos |
| Copia sanitizada creada | ✅ solo `IHDR`/`IDAT`/`IEND` | ✅ solo `IHDR`/`IDAT`/`IEND` |
| Visualmente correcta | ✅ mismo modo/tamaño, píxeles idénticos | ✅ píxeles idénticos |
| Original intacto | ✅ SHA-256 igual antes/después | ✅ |
| Copia soltada en ComfyUI NO reconstruye el workflow | ✅ 0 nodos del workflow (solo el `LoadImage` que ComfyUI crea para cualquier imagen sin metadata) | ✅ ídem |
| Sin `workflow`/`prompt`/`parameters`/`comf`/seed/modelos/LoRA/rutas | ✅ ningún chunk de texto ni privado; ninguna clave en bytes ni en `IDAT` descomprimido | ✅ |
| Re-sanitizar la copia | ✅ idéntica byte a byte (→ `clean`) | ✅ |

El frontend de ComfyUI lee el workflow de los chunks `tEXt`, `iTXt` y `comf`; los tres
quedan fuera de la lista blanca.

### V1 completa (T045) — 2026-10-16 — **PASS**

Formatos de ComfyUI usados realmente (nodos de guardado de los 182 workflows guardados):
PNG (`SaveImage`) y MP4 H.264 (`VHS_VideoCombine` y `SaveVideo`). WEBP y WEBM no se usan.

- PNG: un PNG real y privado de ComfyUI (`tEXt[prompt]`, `tEXt[workflow]`, `tEXt[AIGC]`).
- MP4: no había vídeos reales con workflow embebido a mano, así que se generaron dos con
  el ComfyUI local: grafos mínimos encolados desde su propia UI (`EmptyImage` →
  `CreateVideo` → `SaveVideo`; `EmptyImage` → `VHS_VideoCombine`, `save_metadata`), para
  que la metadata se embeba igual que en el uso real.
- Flujo por la **app real** (backend en `:8000` con DB/media del scratchpad): importar →
  `POST /remove-metadata` → `GET /metadata` → copia limpia tomada del directorio de media →
  original y copia soltados en ComfyUI (drag-and-drop simulado con Playwright).
- No se publicó en ninguna plataforma externa.

| Comprobación | PNG | MP4 `SaveVideo` | MP4 `VHS_VideoCombine` |
|---|---|---|---|
| El original reconstruye el workflow | ✅ 69 nodos | ✅ 3 nodos | ✅ 2 nodos |
| `Remove metadata` | ✅ `sanitized`, se publica `clean_copy` | ✅ | ✅ |
| La copia NO reconstruye el workflow | ✅ solo `LoadImage` (lo que ComfyUI crea para cualquier imagen) | ✅ solo `LoadVideo` | ✅ solo `LoadVideo` |
| `Inspect metadata` del original | `comfyui` (prompt, workflow), `ai_generation` | `comfyui` (prompt, workflow*), `software` | `comfyui` (comment), `software`, `dates` |
| `Inspect metadata` de la copia | sin hallazgos | sin hallazgos | sin hallazgos |
| Sin restos en los bytes (workflow, prompt, class_type, seed, modelos, LoRA, nombres de nodos, rutas, `Lavf6x`, creation_time) | ✅ | ✅ | ✅ |
| Apariencia / reproducción | ✅ píxeles idénticos | ✅ mismos paquetes (sin recodificar), misma duración y streams, decodifica | ✅ ídem |
| Original intacto (SHA-256 igual al importado y tras la operación) | ✅ | ✅ | ✅ |
| Ninguna ruta interna en las respuestas | ✅ | ✅ | ✅ |

\* La etiqueta `workflow` de `SaveVideo` se clasificaba como `container` en la inspección
(el valor es el grafo de la UI, sin marcadores reconocibles); corregido clasificando también
por nombre de clave. La sanitización no se veía afectada.

Los MP4 generados no tienen audio: la sincronía de audio queda cubierta por el test
sintético con audio (`test_video_metadata.py`, paquetes de audio idénticos).
