# Data Model: Biblioteca de contenido

**Feature**: `003-content-library` | **Fecha**: 2026-10-05

Se añade una tabla (`contents`) mediante la migración Alembic
`0002_create_contents`. Las tablas `projects` y `accounts` no cambian.

## Content (`contents`)

| Campo | Tipo SQL | Nulo | Reglas |
|-------|----------|------|--------|
| `id` | INTEGER PK | no | Autoincremental |
| `project_id` | INTEGER FK → `projects.id` (`ON DELETE RESTRICT`) | no | Inmutable; el proyecto debe existir y estar activo al importar |
| `media_type` | VARCHAR(10) | no | `image` \| `video` |
| `media_format` | VARCHAR(10) | no | `jpeg` \| `png` \| `webp` \| `mp4` \| `mov` \| `webm` (detectado por contenido, [research.md](research.md) decisión 3) |
| `storage_path` | VARCHAR(255) | no | Ruta **relativa** a la raíz multimedia, p. ej. `projects/1/3f2c…a9.jpg`; única; generada por AutoPublisher |
| `original_filename` | VARCHAR(255) | no | *Basename* del nombre enviado, recortado a 255 caracteres; solo informativo |
| `checksum` | VARCHAR(64) | no | SHA-256 en hexadecimal minúscula |
| `size_bytes` | INTEGER | no | > 0 y ≤ 2 GiB |
| `width` | INTEGER | sí | Píxeles; `null` si no se pudo obtener |
| `height` | INTEGER | sí | Píxeles; `null` si no se pudo obtener |
| `duration_seconds` | FLOAT | sí | Solo vídeos; `null` en imágenes o si no se pudo obtener |
| `title` | VARCHAR(200) | sí | Recortado; vacío → `null` |
| `description` | VARCHAR(5000) | sí | Recortado; vacío → `null` |
| `hashtags` | JSON (TEXT) | no | Lista de strings normalizados; `[]` por defecto |
| `created_at` | DATETIME (UTC) | no | Fecha de importación; inmutable |
| `updated_at` | DATETIME (UTC) | no | Igual a `created_at` al importar; ver regla abajo |

**Restricciones e índices**

- `UNIQUE(project_id, checksum)` → detección de duplicados por proyecto (FR-016, FR-017).
- `UNIQUE(storage_path)`.
- Índice por `(project_id, created_at)` para el listado de la biblioteca.

**Relaciones**

- `Project 1 ── 0..* Content`. Un contenido pertenece siempre a exactamente un proyecto.
  No existe borrado (FR-023), y `RESTRICT` impide borrar un proyecto con contenido.

**Campos editables**: solo `title`, `description` y `hashtags` (FR-020, FR-021). El resto se
fija al importar.

**Estado de programación**: no se modela. Todo contenido es implícitamente "sin programar"
(`UNSCHEDULED`) hasta que exista `Publication` en una feature futura.

## Reglas de validación

### Importación (por archivo)

| Comprobación | Resultado si falla |
|--------------|--------------------|
| Tamaño 0 bytes | `rejected` / `empty_file` |
| Tamaño > 2 GiB | `rejected` / `file_too_large` |
| Firma de los primeros bytes no corresponde a un formato soportado | `rejected` / `unsupported_format` |
| Imagen que Pillow no puede abrir o cuyo formato no coincide con la firma | `rejected` / `invalid_file` |
| Checksum ya existente en el proyecto (incluido un archivo anterior del mismo lote) | `duplicate` con referencia al contenido existente |
| Error de disco o de base de datos al guardar | `rejected` / `storage_error` (sin registro ni archivo residual) |

### Importación (por petición)

| Comprobación | Error |
|--------------|-------|
| Proyecto inexistente | `404 not_found` |
| Proyecto inactivo | `409 project_inactive` |
| Ningún archivo | `422 validation_error` (campo `files`) |
| Más de 100 archivos | `422 validation_error` (campo `files`) |

### Edición de metadata

- `title`: string \| null; recortado; ≤ 200; vacío → `null`.
- `description`: string \| null; recortado; ≤ 5000; vacío → `null`.
- `hashtags`: array de strings \| null (`null` equivale a `[]`). Por cada elemento:
  1. recortar;
  2. quitar un `#` inicial;
  3. rechazar si queda vacío o contiene espacios;
  4. rechazar si supera 100 caracteres.

  Después se eliminan los repetidos comparando con `normalize_key` (se conserva la primera
  aparición y el orden) y se rechaza si quedan más de 30.
- Cuerpo vacío `{}` o campos no editables → `422 validation_error`.

## Regla de `updated_at` (FR-021)

1. Normalizar los valores recibidos.
2. Para cada campo presente en el cuerpo, compararlo con el valor almacenado (`hashtags`
   como lista exacta: el orden y las mayúsculas cuentan).
3. Si ningún campo difiere → no se escribe nada y `updated_at` no cambia (operación
   idempotente).
4. Si alguno difiere → se actualizan los campos que cambian y `updated_at = now()` (UTC).
5. `created_at`, el archivo almacenado y su checksum nunca cambian.

## Almacenamiento en disco

```text
<AUTOPUBLISHER_MEDIA_DIR>          # por defecto backend/data/media (ignorado por Git)
├── projects/
│   └── <project_id>/
│       └── <uuid4-hex>.<ext>      # copia exacta del archivo importado
└── tmp/                           # archivos parciales en curso; se vacía al arrancar
```

- Cada fila de `contents` referencia exactamente un archivo de `projects/` y viceversa (salvo
  manipulación externa, que se refleja como `file_available: false`).
- Una copia por contenido; las futuras publicaciones referenciarán el `Content`, no copiarán
  el archivo (FR-012).

## Representación en la API (`ContentRead`)

Todos los campos de la tabla excepto `storage_path`, más:

- `file_url`: `"/api/contents/{id}/file"`;
- `file_available`: `true` si el archivo existe en disco.

Detalle en [contracts/api.md](contracts/api.md).
