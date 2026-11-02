> **Referencia para la futura Feature 031 — Metadata Verification & Hardening.** Este documento
> describe el diseño ampliado que se descartó del scope de Feature 028 el 2026-11-02. NO forma
> parte de la implementación de 028.

# API Contract: Media Metadata Hygiene (Feature 028)

Todas las rutas siguen detrás del inicio de sesión de la instalación. Ninguna respuesta contiene
valores de metadata, rutas internas ni salida de herramientas.

## `ContentRead` (cambio)

Se elimina `metadata_status`. Se añade:

```json
"metadata": {
  "state": "verified_clean | metadata_found | not_checked | incomplete | error",
  "variant": "already_clean | cleaned_copy | null",
  "inspection_complete": true,
  "reason_code": "tool_unavailable | unclassified_blocks | limits_exceeded | invalid_structure | file_unavailable | file_changed | read_error | null",
  "reason": "Short sentence for the UI, or null",
  "categories": ["Location (GPS)", "Device"],
  "checked_at": "2026-11-02T10:00:00Z | null",
  "activity": "checking | cleaning | null",
  "can_clean": true
}
```

- `inspection_complete`: `false` cuando la evidencia del publish file es `incomplete`, también en
  `metadata_found` (C1); la UI muestra entonces "Metadata found; the file could not also be fully
  inspected." Nunca `true` sin una evidencia `complete`.
- `categories`: etiquetas de las categorías encontradas en el publish file (vacío salvo
  `metadata_found`).
- `can_clean`: `true` en `metadata_found`, `incomplete` y `error` por copia ausente/dañada o
  `file_changed` de la copia; `false` en `verified_clean`, `not_checked` y errores del original.
- `publish_file` no cambia (versión original/copia, checksum, tamaño, disponibilidad).
- Aparece en todas las respuestas que ya devuelven `ContentRead` (listado de Library, detalle,
  importación, edición).

## `GET /api/contents/{id}/metadata` (cambia de semántica)

Devuelve la **evidencia guardada**; ya no inspecciona en vivo.

```json
{
  "state": { "...": "igual que ContentRead.metadata" },
  "original": FileEvidence | null,
  "publish_copy": FileEvidence | null
}
```

`FileEvidence`:

```json
{
  "result": "complete | incomplete | error",
  "reason_code": "... | null",
  "current": true,
  "findings": [{ "category": "location", "label": "Location (GPS)", "keys": ["GPSInfo"] }],
  "unclassified": ["APP11"],
  "technical": ["ICC color profile"],
  "inspected_at": "..."
}
```

`current = false` si la evidencia es obsoleta (checksum o versión de reglas). `404` si el media no
existe.

## `POST /api/contents/{id}/metadata/check` (nuevo — Check again)

Inspecciona ahora el original y, si existe, la copia; guarda ambas evidencias; responde `200`
con `ContentRead`. Permitido en proyectos inactivos. Errores: `404` media inexistente; `409
content_cleaning` si el media se está limpiando. Un fallo de inspección **no** es un error HTTP:
queda reflejado en el estado (`incomplete`/`error`).

## `POST /api/contents/{id}/clean-metadata` (sustituye a `/remove-metadata`)

Flujo de spec FR-011. Idempotente. Responde `200` con `ContentRead`.

| Código | HTTP | Cuándo |
|---|---|---|
| `media_unavailable` | 404 | Original ausente o de tamaño distinto |
| `media_corrupt` | 409 | Checksum del original distinto del de importación |
| `content_publishing` | 409 | Un post del media está publicándose (016) |
| `content_cleaning` | 409 | Ya hay una limpieza en curso (016 `removal_in_progress`, renombrado) |
| `invalid_media` | 422 | Estructura inválida (016) |
| `metadata_not_removed` | 422 | La copia no obtiene una inspección `complete` sin metadata relevante ni bloques no clasificables |
| `clean_result_invalid` | 500 | La copia no supera la equivalencia (FR-014) |
| `tool_unavailable` | 503 | Falta ffmpeg o ffprobe (vídeo; hacen falta ambos) |
| `sanitize_failed` | 500 | La herramienta de limpieza falló (016) |
| `storage_error` | 500 | No se pudo guardar la copia o el estado (016) |

Mensajes fijos en inglés, por ejemplo: `"Metadata could not be removed safely from this file."`,
`"Cleaning video metadata needs ffmpeg and ffprobe. Install them and try again."`.

`POST /remove-metadata` se elimina (frontend y backend se actualizan juntos; no hay clientes
externos).

## Resolvedor del publish file (contrato interno para 029/030)

`resolve_publish_file(storage, content, verify)` no cambia. Se añade, junto a él,
`publish_file_metadata_state(session, storage, content) -> MetadataStateRead` (la misma
derivación que `ContentRead.metadata`), para que cualquier consumidor futuro obtenga archivo,
checksum y estado sin lógica propia. Ningún publisher se modifica.

## UI (contrato de comportamiento)

| Lugar | Contenido |
|---|---|
| Media Card | Badge `success` "Metadata cleaned" (`verified_clean`) o `warning` "Metadata not cleaned" (resto; icono de aviso en `error`); texto accesible con el motivo |
| Cabecera del detalle | Mismo badge + frase de motivo/variante (*Already clean*, *Cleaned copy*, categorías, *Not checked yet*, *Could not be fully inspected*, error); botones **Clean metadata** (`can_clean`) y **Check again**; estado "Cleaning…"/"Checking…" durante `activity` |
| File details | Evidencia del original y del publish file (categorías, claves, no clasificables, técnicos conservados), archivo publicado, fecha de verificación, checksums |
| Polling | Cada 3 s solo mientras algún media visible tenga `not_checked` o `activity` |
