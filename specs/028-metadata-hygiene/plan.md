# Implementation Plan: Media Metadata Hygiene

**Branch**: `028-metadata-hygiene` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/028-metadata-hygiene/spec.md` (versión simplificada)

## Summary

Badge 🟢/🟡 en cada Media Card y en la cabecera del detalle, derivado en el frontend de
`metadata_status` y `publish_file.available` (datos que la API ya devuelve), y botón **Clean
metadata** en la cabecera, que reutiliza el endpoint y el manejador de Feature 016.

En el backend, tres correcciones dentro del flujo existente:

- reinspeccionar con el inspector actual el resultado temporal antes de aceptarlo;
- reconstruir el JFIF sin miniatura y detectar esa miniatura al inspeccionar;
- eliminar de los logs el stderr y `exc_info` de ffmpeg/ffprobe.

Más el cambio de textos *Remove* → *Clean*.

Sin modelo, migraciones, endpoints ni estados nuevos. El diseño ampliado queda en
[reference-031/](reference-031/research.md) para la futura Feature 031.

Research: [research.md](research.md) · Estados: [data-model.md](data-model.md) · Contrato:
[contracts/api.md](contracts/api.md) · Validación: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React + Vite (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, Pillow (ya presente; en tests compara píxeles en el
caso JFIF), `ffmpeg`/`ffprobe` (ya usados). Sin dependencias nuevas.

**Storage**: sin cambios (SQLite y almacenamiento local de 016).

**Testing**: pytest dirigido (marcador `real_ffprobe` para vídeo), vitest + `test-fake-api.ts`.

**Target Platform**: aplicación local de un usuario (Linux), FastAPI + SPA.

**Project Type**: web application (backend + frontend).

**Performance Goals**:
- Ningún coste nuevo al listar: el badge usa campos existentes.
- La limpieza solo añade una inspección del resultado (lectura acotada en imágenes; una ejecución
  de ffprobe en vídeo).

**Constraints**:
- Original inmutable.
- Ningún valor de metadata ni salida bruta de herramientas en los logs.
- Endpoint y semántica de `metadata_status` sin cambios.

**Scale/Scope**: unos 5 archivos del backend y 7 del frontend.

## Constitution Check

| Principio | Evaluación |
|---|---|
| I. Simplicidad y alcance | ✅ Solución mínima sobre 016; el hardening avanzado se aplaza explícitamente a 031. |
| II. Spec-Driven | ✅ Spec simplificada y aprobada; el plan no añade alcance. |
| III. Arquitectura modular | ✅ No se toca ningún publisher ni el resolvedor. |
| IV. Seguridad | ✅ Se elimina el logging de stderr y `exc_info` de ffmpeg/ffprobe; la limpieza nunca acepta un resultado con metadata detectable. |
| V. Calidad | ✅ Tests dirigidos por cada cambio de comportamiento, incluida la regresión del JFIF. |
| VI. Git | ✅ Un commit por checkpoint; `docs/asset-library.md` actualizado. |

Re-evaluación post-diseño: sin violaciones.

## Project Structure

### Documentation (this feature)

```text
specs/028-metadata-hygiene/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api.md
├── checklists/requirements.md
├── reference-031/           # diseño ampliado descartado: referencia para Feature 031
│   ├── research.md
│   ├── data-model.md
│   └── api-contract.md
└── tasks.md                 # se regenera con /speckit-tasks
```

### Source Code

```text
backend/app/
├── asset_library.py   # _remove: reinspección de temp + errores metadata_not_removed /
│                      #   metadata_check_unavailable; fallo rápido sin ffprobe en vídeo; textos
├── image_metadata.py  # _plan_jpeg: JFIF sin miniatura; _inspect_jpeg: "JFIF thumbnail"
├── video_metadata.py  # logs sin stderr/exc_info; texto de FFMPEG_MISSING_MESSAGE
├── media.py           # logs sin exc_info
└── content_files.py   # textos "Clean metadata"

backend/tests/
├── test_remove_metadata_api.py   # reinspección, errores nuevos, estados 016 intactos
├── test_image_metadata.py        # JFIF/JFXX (sanitizador + inspector)
└── test_video_metadata.py        # logs sin valores sembrados

frontend/src/
├── pages/library/metadata-indicator.ts     # NUEVO helper puro
├── pages/library/metadata-indicator.test.ts
├── pages/library/useCleanMetadata.ts       # NUEVO: manejador extraído de FileDetails
├── pages/library/MediaCard.tsx             # badge
├── pages/library/MediaDetail.tsx           # cabecera: badge + motivo + Clean metadata
├── pages/library/FileDetails.tsx           # textos; sin botón de limpiar
├── pages/library/library.css               # fila de badges con wrap
└── test-fake-api.ts                        # errores nuevos de remove-metadata

docs/asset-library.md                       # sección de metadata actualizada
```

**Structure Decision**: aplicación web existente; los helpers siguen el patrón de
`usage-indicator.ts` y los hooks `use*.ts` de `pages/library/`.

## Key Design Decisions

1. **Badge 100 % frontend** con un único helper (`metadataIndicator`) que usan la card y el
   detalle; nada de condiciones duplicadas (R1, R6).
2. **La reinspección va antes de la bifurcación `clean`/`sanitized`** en `_remove`, reutilizando
   `_inspect`. Un informe con hallazgos da `422 metadata_not_removed`; un informe no inspeccionado
   da `503 metadata_check_unavailable`. En vídeo sin ffprobe se falla antes de ejecutar ffmpeg.
   El temporal siempre se descarta en el `finally` existente (R2).
3. **El JFIF solo se reescribe cuando tiene miniatura**, así que los JPEG ya limpios siguen
   produciendo un resultado idéntico (rama `clean`). JFXX ya se elimina y detecta hoy; solo se
   cubre con tests (R3).
4. **Logs**: solo el nombre de la clase de excepción o el código de salida (R4).
5. **Textos**: solo los que nombran la acción; el endpoint y los códigos de 016 no cambian (R5).
6. **El botón Clean metadata vive solo en la cabecera** del detalle, mediante un hook extraído
   del manejador de `FileDetails`. *File details* conserva *Inspect metadata* y el informe. La
   actualización se hace con el `onChanged` existente, que recarga Library y detalle (R6).

## Checkpoints

Cada checkpoint se cierra con sus tests dirigidos verdes y un commit propio.

| CP | Alcance | Tests dirigidos de cierre |
|---|---|---|
| **A — Backend hardening mínimo** | Reinspección post-clean y errores nuevos, fallo rápido sin ffprobe, JFIF sin miniatura + detección en el inspector, logs seguros, textos *Clean metadata*. | `test_remove_metadata_api.py`: `unknown`→`clean` (PNG ya limpio) y `unknown`→`sanitized` (JPEG con GPS) siguen funcionando y su resultado pasa la reinspección; sanitizador alterado que deja un bloque → `422`, sin copia ni cambio de estado y con el temporal descartado; informe `inspected=False` simulado → `503`; vídeo sin ffprobe → `503` sin ejecutar ffmpeg; regeneración de una copia ausente; original byte a byte intacto. `test_image_metadata.py`: JFIF con miniatura → inspector la informa; la copia tiene un JFIF de 16 bytes, los mismos datos entrópicos y los mismos píxeles (Pillow); un JFIF sin miniatura se copia idéntico; JFXX eliminado e informado. `test_video_metadata.py`: con ffmpeg/ffprobe falsos que escriben valores sembrados en stderr, `caplog` a nivel DEBUG no contiene ninguno ni hay trazas. |
| **B — UI de estado de metadata** | `metadata-indicator.ts`, badge en `MediaCard` (+ CSS), cabecera del detalle con badge, motivo y **Clean metadata** vía `useCleanMetadata`, textos de `FileDetails`, fake API. | `metadata-indicator.test.ts`: las cinco combinaciones → tono, label, motivo y `canClean`. Card (`library.test.tsx`): badge verde/amarillo con texto accesible junto al de uso. Detalle (`FileDetails.test.tsx` + nuevo `media-metadata.test.tsx`): Clean metadata en la cabecera llama al endpoint, el badge pasa a 🟢 sin recargar y el botón desaparece; se muestran los errores `metadata_not_removed`/`metadata_check_unavailable`; no se ofrece en 🟢; *Inspect metadata* sigue funcionando. Responsive básico: la fila de badges usa la clase con wrap. |
| **C — Docs, regresiones y cierre** | `docs/asset-library.md` (badge y significado, reinspección, JFIF, logs, riesgos aceptados, referencia a 031), estado de la spec y checklist, validación manual del quickstart en una instancia de prueba y checks de cierre una sola vez. | Regresiones solo de las áreas tocadas que no se hayan probado ya. ruff, format, mypy, `npm run lint`/`typecheck`/`build`, `git diff --check` y revisión de seguridad del diff. |

**Estimación**: unas 14–16 tareas (A ≈ 7, B ≈ 6, C ≈ 3).

## Riesgos restantes

- Las copias limpiadas antes de 028 no se reinspeccionan y conservan su badge verde aunque
  tuvieran una miniatura JFIF (riesgo aceptado en la spec; la reverificación queda para 031).
- La reinspección de vídeo depende de ffprobe: sin él no se puede limpiar vídeo (comportamiento
  buscado).
- La inspección de vídeo de 016 solo ve los tags que expone ffprobe (límite conocido; 031).
- Una copia dañada con el mismo tamaño se ve 🟢 hasta publicar, donde la bloquea el checksum.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
