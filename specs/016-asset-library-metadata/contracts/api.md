# API Contract: Asset Library, Usage & Metadata

**Feature**: `016-asset-library-metadata` | **Fecha**: 2026-10-16

Amplía la API REST bajo `/api`. Fechas ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene rutas internas (`storage_path`,
`sanitized_storage_path`) ni valores de metadata sensible (solo categorías y nombres de
clave). Los mensajes de error no incluyen rutas ni stderr de ffmpeg/ffprobe.

---

## `ContentRead` (ampliado; usado por todos los endpoints existentes de contenidos)

Campos existentes sin cambios (incluidos `checksum`, `size_bytes`, `file_url`, que siguen
describiendo el **original**). Campos nuevos:

```json
{
  "metadata_status": "unknown | clean | sanitized",
  "publish_file": {
    "version": "original | clean_copy",
    "available": true,
    "checksum": "<sha256 efectivo>",
    "size_bytes": 1234,
    "sanitized_at": "2026-10-16T10:00:00Z | null"
  },
  "usage": {
    "used": true,
    "publication_count": 3,
    "published_count": 1,
    "awaiting_count": 1,
    "scheduled_count": 1,
    "platforms": ["telegram", "tiktok"],
    "last_published_at": "2026-10-10T09:00:00Z | null"
  }
}
```

- `publish_file.version = "clean_copy"` solo si `metadata_status = "sanitized"`.
- `publish_file.available`: existencia + tamaño (sin hash). Con `sanitized`, refleja la copia;
  nunca el original.
- `usage` sigue la semántica de research.md §1 (`awaiting_user_action` cuenta como usado y
  no como publicado; `scheduled` no cuenta).

## `GET /api/projects/{project_id}/contents` (existente)

Mismo orden y forma; cada elemento incluye `metadata_status`, `publish_file` y `usage`. El
resumen de uso se obtiene con dos consultas agregadas por proyecto (sin N+1). Búsqueda y
filtros se hacen en el cliente.

## `GET /api/contents/{content_id}` (existente)

Incluye los campos nuevos.

## `GET /api/contents/{content_id}/usage` (nuevo)

Historial de uso para el detalle.

```json
{
  "usage": { "...": "igual que en ContentRead" },
  "publications": [
    {
      "publication_id": 12,
      "platform": "tiktok",
      "account_id": 3,
      "account_name": "Main",
      "status": "awaiting_user_action",
      "scheduled_at": null,
      "published_at": null,
      "created_at": "…",
      "updated_at": "…",
      "uncertain": false,
      "external_url": null
    }
  ]
}
```

Orden: `updated_at` descendente. `uncertain = true` si el último intento de esa publicación
requiere revisión manual (resultado incierto). Errores: `404` contenido inexistente.

## `GET /api/contents/{content_id}/metadata` (nuevo)

Inspección bajo demanda (no persistida).

```json
{
  "original": {
    "inspected": true,
    "reason": null,
    "findings": [
      { "category": "comfyui", "label": "ComfyUI workflow", "keys": ["prompt", "workflow"] },
      { "category": "location", "label": "Location (GPS)", "keys": ["GPSInfo"] }
    ]
  },
  "publish_copy": null
}
```

- `publish_copy` solo si `metadata_status = "sanitized"` y la copia está disponible; si no
  está disponible: `{ "inspected": false, "reason": "The clean copy is missing.", "findings": [] }`.
- Vídeo sin ffprobe: `{ "inspected": false, "reason": "ffprobe is not available.", "findings": [] }`.
- `findings: []` con `inspected: true` → "No sensitive metadata found".
- Categorías: `location`, `device`, `software`, `dates`, `exif`, `xmp`, `iptc`, `comments`,
  `container`, `ai_generation`, `comfyui`, `other`.

Errores: `404` contenido inexistente; `404 media_unavailable` si falta el original.

## `POST /api/contents/{content_id}/remove-metadata` (nuevo)

Sin cuerpo. Respuesta `200` con el `ContentRead` actualizado.

| Situación | Resultado |
|---|---|
| `unknown`, salida idéntica al original | `200`, `metadata_status = "clean"`, sin copia |
| `unknown`, salida distinta | `200`, `metadata_status = "sanitized"` |
| `sanitized` con copia que existe y verifica SHA | `200` sin trabajo |
| `sanitized` con copia ausente/corrupta | `200`, copia regenerada (ruta nueva) |
| `clean` | `200` sin trabajo |

Errores:

| Código | Cuándo |
|---|---|
| `404` | Contenido inexistente. |
| `404 media_unavailable` | Falta el archivo original. |
| `409 content_publishing` | Alguna publicación del contenido está `publishing`. Mensaje: "This content is being published. Remove metadata after the upload finishes." |
| `409 metadata_removal_in_progress` | Ya hay una sanitización en curso de este contenido. |
| `422 invalid_media` | El archivo no tiene una estructura válida para sanitizar. |
| `503 ffmpeg_required` | Vídeo y ffmpeg no está instalado. Mensaje: "Removing metadata from videos needs ffmpeg. Install it and try again." |
| `500 sanitize_failed` | ffmpeg falló o agotó el tiempo. |
| `500 storage_error` | No se pudo guardar la copia (estado sin cambios). |

Se permite también en proyectos inactivos (como editar título/descripción): no publica nada.

---

## Publicación (endpoints existentes, sin rutas nuevas)

### Problemas de preflight / check (todos los publishers con contenido)

| Código | Cuándo |
|---|---|
| `media_unavailable` | El archivo efectivo no existe o su tamaño no coincide. Con `sanitized`, el mensaje indica que falta la copia limpia y que `Remove metadata` la regenera; nunca se usa el original. |
| `media_corrupt` | (solo en `prepare`, último paso local antes del claim y de la subida) SHA-256 de la copia limpia distinto de `sanitized_checksum`. No se crea intento. |

### Claim (`POST /api/publications/{id}/publish` y scheduler)

| Código | Cuándo |
|---|---|
| `409 content_metadata_busy` | Se está eliminando la metadata de este contenido. Mensaje: "Metadata is being removed from this content. Publish again when it finishes." |
| `409 content_file_changed` | El archivo efectivo cambió entre la preparación y el inicio (se acaba de eliminar la metadata). Mensaje: "The file to publish changed because its metadata was just removed. Review the publication and publish again." |

En ambos casos **no cambia nada**: la publicación conserva su estado (`unscheduled`,
`scheduled` o `failed`) y su armado de auto-publish, no se crea intento y no se contacta con la
plataforma para subir nada.

- **Publish Now (manual)**: el diálogo muestra el mensaje del 409 como cualquier otro error
  de preflight y el usuario puede volver a pulsar Publish. Tras `content_file_changed` el
  reintento prepara con la copia limpia (TikTok puede pedir reconfirmar el consentimiento,
  porque el checksum cambió). Tras `content_metadata_busy`, el reintento funciona en cuanto
  termina la sanitización. Nunca queda en `publishing` ni atascada.
- **Scheduler**: ambos códigos están en `NOT_CLAIMED_CODES`: no se registran como fallo de
  auto-publish y el siguiente tick vuelve a intentarlo con el archivo efectivo nuevo.

### Consentimientos / fingerprints

- TikTok: el `consent_fingerprint` usa el checksum efectivo; tras sanitizar, un consentimiento
  previo aparece como no válido y el flujo existente de confirmación lo pide de nuevo.
- Instagram: el `fingerprint` de reutilización de contenedores usa el checksum efectivo.

### Valores enviados (`submitted`)

`file_size` (y equivalentes) pasan a ser el tamaño efectivo. Los intentos históricos no se
reescriben.
