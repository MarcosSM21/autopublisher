# API Contract: biblioteca de contenido

**Feature**: `003-content-library` | **Fecha**: 2026-10-05

Amplía la API REST bajo `/api` de la Feature 002. Sin autenticación. Fechas en ISO 8601 UTC.
El formato de error y los códigos existentes (`validation_error`, `not_found`, `duplicate`,
`project_inactive`, `method_not_allowed`, `internal_error`) se mantienen sin cambios
(ver `specs/002-projects-accounts/contracts/api.md#error`).

No existe ninguna ruta `DELETE` para contenido (FR-023); un `DELETE` devuelve
`405 method_not_allowed`. Ninguna respuesta incluye rutas absolutas ni la ruta interna de
almacenamiento.

## Representaciones

### Content

```json
{
  "id": 12,
  "project_id": 1,
  "media_type": "video",
  "media_format": "mp4",
  "original_filename": "reel-01.mp4",
  "title": "Summer teaser",
  "description": null,
  "hashtags": ["l4i4", "summer"],
  "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "size_bytes": 18734211,
  "width": 1080,
  "height": 1920,
  "duration_seconds": 14.53,
  "file_url": "/api/contents/12/file",
  "file_available": true,
  "created_at": "2026-10-05T10:15:00Z",
  "updated_at": "2026-10-05T10:15:00Z"
}
```

- `media_type` ∈ `image | video`.
- `media_format` ∈ `jpeg | png | webp | mp4 | mov | webm`.
- `width`, `height` y `duration_seconds` pueden ser `null`; `duration_seconds` es siempre
  `null` en imágenes.
- `hashtags` se devuelven sin `#`.
- `file_available` es `false` si el archivo almacenado ya no existe en disco.

### ImportResult

```json
{
  "results": [
    {
      "filename": "photo-01.jpg",
      "status": "imported",
      "content": { "...": "Content" },
      "existing_content": null,
      "error": null
    },
    {
      "filename": "photo-01-copy.jpg",
      "status": "duplicate",
      "content": null,
      "existing_content": { "...": "Content" },
      "error": null
    },
    {
      "filename": "notes.txt",
      "status": "rejected",
      "content": null,
      "existing_content": null,
      "error": {
        "code": "unsupported_format",
        "message": "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV, WebM."
      }
    }
  ],
  "summary": { "imported": 1, "duplicates": 1, "rejected": 1 }
}
```

`results` tiene una entrada por archivo recibido, en el mismo orden. `filename` es el nombre
original (*basename*, ≤ 255 caracteres).

| `error.code` (por archivo) | Cuándo |
|----------------------------|--------|
| `empty_file` | El archivo tiene 0 bytes |
| `file_too_large` | Supera 2 GiB (el mensaje indica el límite) |
| `unsupported_format` | El contenido no corresponde a ningún formato soportado |
| `invalid_file` | Firma de imagen soportada pero archivo corrupto o incoherente |
| `storage_error` | Fallo inesperado de disco o base de datos al guardar ese archivo; no queda registro ni archivo residual |

## Contenido

### `GET /api/projects/{project_id}/contents`

Lista los contenidos del proyecto, del más reciente al más antiguo (`created_at` desc,
después `id` desc). Funciona también con proyectos inactivos.

- `200` → `Content[]` (vacío si no hay ninguno).
- `404 not_found` si el proyecto no existe.

### `POST /api/projects/{project_id}/contents`

Importa uno o varios archivos. `Content-Type: multipart/form-data`, campo `files` repetido una
vez por archivo.

- `200` → `ImportResult`, incluso si todos los archivos se rechazan o son duplicados. Cada
  archivo se procesa de forma independiente.
- `404 not_found` → el proyecto no existe; no se procesa ningún archivo.
- `409 project_inactive` → el proyecto está inactivo; no se procesa ningún archivo.
- `422 validation_error` (campo `files`) → no se envió ningún archivo o se enviaron más de 100
  ("At most 100 files can be imported at once."); no se procesa ningún archivo.

Ejemplo:

```bash
curl -F files=@photo.jpg -F files=@clip.mp4 http://127.0.0.1:8000/api/projects/1/contents
```

### `GET /api/contents/{content_id}`

- `200` → `Content`.
- `404 not_found`.

### `PATCH /api/contents/{content_id}`

`Content-Type: application/json`. Cuerpo con uno o más de:

| Campo | Tipo | Reglas |
|-------|------|--------|
| `title` | string \| null | Recortado; ≤ 200; vacío → `null` |
| `description` | string \| null | Recortado; ≤ 5000; vacío → `null` |
| `hashtags` | string[] \| null | Cada elemento: recortado, sin `#` inicial, no vacío, sin espacios, ≤ 100. Repetidos eliminados sin distinguir mayúsculas (se conserva el primero y el orden). Máx. 30. `null` → `[]` |

Cualquier otro campo (`project_id`, `media_type`, `checksum`, etc.) → `422 validation_error`.
Cuerpo vacío `{}` → `422 validation_error`.

- `200` → `Content`. `updated_at` solo cambia si algún valor normalizado difiere del
  almacenado (FR-021); si no, la operación es idempotente.
- `404 not_found`, `422 validation_error` (`fields` indica `title`, `description` o
  `hashtags`).
- Permitido aunque el proyecto esté inactivo.

### `GET /api/contents/{content_id}/file`

Devuelve el archivo almacenado tal cual, con el `Content-Type` del formato (`image/jpeg`,
`image/png`, `image/webp`, `video/mp4`, `video/quicktime`, `video/webm`). Admite cabecera
`Range` (respuesta `206`) para el reproductor de vídeo.

- `200`/`206` → bytes del archivo.
- `404 not_found` → el contenido no existe ("Content not found.") o su archivo no está
  disponible ("The media file is not available.").
