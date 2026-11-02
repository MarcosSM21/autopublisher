# Data Model: Media Metadata Hygiene (Feature 028, scope mínimo)

**Sin cambios de modelo ni migraciones.**

| Entidad | Uso en 028 |
|---|---|
| `Content.metadata_status` (`unknown` \| `clean` \| `sanitized`) | Fuente del badge, con la semántica de 016 sin cambios |
| `Content.sanitized_*` | Sin cambios |
| `ContentRead.publish_file.available` (API existente) | Segunda entrada del badge |

## Estado visual derivado (solo frontend, no se persiste)

| `metadata_status` | `publish_file.available` | Tono | Label | Motivo | `canClean` |
|---|---|---|---|---|---|
| `unknown` | cualquiera | warning | Metadata not cleaned | Not cleaned yet | sí |
| `clean` | `true` | success | Metadata cleaned | Already clean | no |
| `clean` | `false` | warning | Metadata not cleaned | Media file missing | no |
| `sanitized` | `true` | success | Metadata cleaned | Cleaned copy | no |
| `sanitized` | `false` | warning | Metadata not cleaned | Clean copy missing | sí |

## Transiciones (las de 016, con la nueva comprobación)

```text
unknown ──Clean metadata──► (reinspección OK) ──► clean | sanitized
unknown ──Clean metadata──► (reinspección falla) ──► unknown (sin cambios)
sanitized(copia ausente) ──Clean metadata──► (reinspección OK) ──► sanitized (copia regenerada)
```
