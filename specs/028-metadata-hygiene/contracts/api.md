# Contract: Media Metadata Hygiene (Feature 028, scope mínimo)

## API

Sin endpoints nuevos ni cambios en `ContentRead`.

### `POST /api/contents/{id}/remove-metadata` (existente, 016)

El comportamiento de 016 se mantiene. Cambios:

1. **Errores nuevos**, ambos sin cambiar el estado ni el archivo publicado y descartando el
   resultado temporal:

   | Código | HTTP | Cuándo | Mensaje |
   |---|---|---|---|
   | `metadata_not_removed` | 422 | La reinspección del resultado encuentra metadata | "Metadata could not be removed safely from this file." |
   | `metadata_check_unavailable` | 503 | La reinspección no puede realizarse (vídeo sin ffprobe o resultado ilegible); en vídeo se comprueba antes de lanzar ffmpeg | "The cleaned file could not be checked, so it was not saved. Videos need ffprobe for this check." |

2. **Textos** de los mensajes existentes: *Remove metadata* → *Clean metadata* (ver
   [research.md R5](../research.md)). Códigos de error y nombre del endpoint sin cambios.

### `GET /api/contents/{id}/metadata` (existente, 016)

Sin cambios, salvo que un JPEG cuyo APP0 JFIF lleva miniatura incluye la categoría `other` con la
clave `"JFIF thumbnail"`.

## UI

| Lugar | Contenido |
|---|---|
| Media Card | `Badge` `success` ("Metadata cleaned", icono `check`) o `warning` ("Metadata not cleaned", icono `alert`) junto al indicador de uso; motivo como texto accesible |
| Cabecera del detalle | Mismo badge + motivo visible + botón **Clean metadata** si `canClean` (con estado "Cleaning metadata…" y error en línea) |
| File details | Sin cambios funcionales: texto de estado, *Inspect metadata*, informe y checksums. Textos *Remove* → *Clean*. El botón de limpiar pasa a la cabecera |

La tabla de estados está en [data-model.md](../data-model.md).
