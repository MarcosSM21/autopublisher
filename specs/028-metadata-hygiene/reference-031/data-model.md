> **Referencia para la futura Feature 031 — Metadata Verification & Hardening.** Este documento
> describe el diseño ampliado que se descartó del scope de Feature 028 el 2026-11-02. NO forma
> parte de la implementación de 028.

# Data Model: Media Metadata Hygiene (Feature 028)

## `metadata_inspections` (nueva tabla)

La evidencia de verificación (spec FR-019, research §5). Una fila por (media, rol); cada nueva
inspección de ese rol reemplaza la anterior (upsert).

| Columna | Tipo | Reglas |
|---|---|---|
| `id` | int PK | |
| `content_id` | int FK → `contents.id` `ON DELETE CASCADE` | |
| `role` | str(12) | `original` \| `clean_copy`; `UNIQUE(content_id, role)` |
| `checksum` | str(64) | SHA-256 de los bytes **leídos** durante la inspección |
| `rules_version` | int | `INSPECTION_RULES_VERSION` con la que se inspeccionó |
| `result` | str(12) | `complete` \| `incomplete` \| `error` (CHECK) |
| `reason_code` | str(40) nullable | Obligatorio si `result ≠ complete`. Catálogo cerrado: `tool_unavailable`, `unclassified_blocks`, `limits_exceeded`, `invalid_structure`, `file_unavailable`, `file_changed`, `read_error` |
| `findings` | JSON | `{categoría: [nombre de clave saneado, …]}`; categorías del catálogo (abajo); nunca valores |
| `unclassified` | JSON | `[nombre de bloque saneado, …]` (vacío salvo `incomplete`/`unclassified_blocks`) |
|  |  | **Dimensiones independientes (C1)**: `findings` y `unclassified` pueden estar llenos a la vez con `result = incomplete`; una evidencia con `findings` no vacío nunca se registra `complete` por ese motivo, ni una `incomplete` pasa a `complete` por tener hallazgos. `verified_clean` exige `result = complete`, `findings = {}` y `unclassified = []`. |
| `technical` | JSON | `[etiqueta fija, …]` p. ej. `"ICC color profile"`, `"EXIF Orientation"`, `"Muxer name"`, `"Codec configuration"`, `"Encoder data in streams"` |
| `inspected_at` | UTC datetime | |

Índice: `UNIQUE(content_id, role)` cubre las consultas por lote de ids del listado.

**Categorías** (`findings`): las de 016 (`comfyui`, `ai_generation`, `location`, `device`,
`software`, `dates`, `exif`, `xmp`, `iptc`, `comments`, `container`, `other`) más
`identifiers` y `trailing_data`, con sus etiquetas para la UI.

**Escritura condicional**: solo se inserta/actualiza si el media existe y, para el rol del publish
file, el checksum efectivo de la BD sigue siendo el inspeccionado; en otro caso se descarta.
La evidencia `clean_copy` se escribe en la **misma transacción** que fija la copia (Clean
metadata) y se borra en la misma transacción que la elimina.

## `contents` (cambios)

| Columna | Cambio |
|---|---|
| `metadata_status` | Se reinterpreta como "existe copia limpia": `unknown` (no) \| `sanitized` (sí). Migración: `clean` → `unknown`; CHECK restringido a esos dos valores. Se deja de exponer en la API. |
| `sanitized_*` | Sin cambios (siguen ligados a `sanitized`). |

Invariante (ya existente): el original (`storage_path`, `checksum`, `size_bytes`) nunca cambia.

## Estado derivado (no se persiste)

`MetadataState` = `verified_clean` \| `metadata_found` \| `not_checked` \| `incomplete` \|
`error`, con `variant` (`already_clean` \| `cleaned_copy`, solo en `verified_clean`),
`inspection_complete` (bool, falso en `metadata_found` si la evidencia es `incomplete`),
`reason_code` y `activity` (`checking` \| `cleaning` \| null). Reglas de derivación en
[research.md §6](research.md).

### Transiciones relevantes

```text
import ───────────────► not_checked ──(worker)──► verified_clean(already_clean)
                                                 ├► metadata_found ──(Clean)──► verified_clean(cleaned_copy)
                                                 ├► incomplete ─────(Clean)──► verified_clean(cleaned_copy) | error
                                                 └► error
verified_clean ──(copia borrada/alterada)──► error ──(Clean)──► verified_clean
cualquier estado ──(INSPECTION_RULES_VERSION++)──► not_checked ──(backfill)──► …
Clean falla (verificación/equivalencia) ──► sin cambios en publish file ni en su evidencia
```

## Constante

`INSPECTION_RULES_VERSION = 1` (módulo común de inspección), protegida por el test de digest de
las tablas de clasificación (research §7).
