# API Contract — Feature 022: Bulk Media Delete

Formato de error existente: `{"error": {"code": "...", "message": "...", "fields": [...]}}`.
Rutas bajo `/api`: sujetas a los guards de 020 (Host, Origin en métodos inseguros, sesión de
instalación). Solo se listan cambios; las rutas individuales de 021
(`GET /api/contents/{id}/deletion-preview`, `DELETE /api/contents/{id}`) **no cambian**.

## 1. Esquemas

```text
ContentSelection        { content_ids: int[] }        1–500, sin repetidos
ContentSelectionDelete  { content_ids: int[],          igual que arriba
                          confirmation: str }          1–100 caracteres
```

- Límite y mensaje de repetidos compartidos con `ContentMove` (`MAX_CONTENTS_PER_MOVE = 500`,
  "Each media item can only be listed once.").
- Campos extra rechazados (`InputModel`).

`DeletionPreviewRead` (021) cambia solo en tipos:

| Campo | Antes | Ahora |
|---|---|---|
| `kind` | `post \| media \| account \| project \| folder` | + `media_selection` |
| `id` | `int` | `int \| null` (`null` solo en `media_selection`) |
| `name` | `str` | `str \| null` (`null` solo en `media_selection`) |

## 2. Preview

`POST /api/projects/{project_id}/contents/deletion-preview`

```json
{"content_ids": [3, 4, 5]}
```

Solo lectura: no retiene guards, no bloquea, no escribe.

### `200`

```json
{
  "kind": "media_selection",
  "id": null,
  "name": null,
  "counts": {
    "unpublished_posts": 9,
    "remote_posts": 2,
    "needs_review_posts": 1,
    "accounts": 0,
    "posts": 12,
    "media": 8,
    "subfolders": 0,
    "media_to_unsorted": 0
  },
  "summary": [
    "8 media items and 12 posts will be removed from AutoPublisher.",
    "3 posts may already exist on platforms. Content already published on platforms is not affected.",
    "1 post may already have been published. Check the platforms before publishing this content again."
  ],
  "blocker": null,
  "confirmation": "v1:3f9a…"
}
```

- `counts` con la semántica de 021: `remote_posts` = Published + Awaiting user action;
  `needs_review_posts` aparte; `posts` = total; `media` = Media seleccionados.
- `summary` (inglés, pluralizado, frases con cuenta 0 omitidas):
  1. `"{n} media item(s) and {p} post(s) will be removed from AutoPublisher."` —
     sin Posts: `"{n} media item(s) will be removed from AutoPublisher."`
  2. Si `r = remote_posts + needs_review_posts > 0`: `"{r} post(s) may already exist on
     platforms. Content already published on platforms is not affected."`
  3. Si `needs_review_posts > 0`: `"{k} post(s) may already have been published. Check the
     platforms before publishing this content again."`
- Nunca se listan Media individualmente.
- `blocker` (uno solo, precedencia fija):
  1. `{"code": "post_in_progress", "message": "A post using one or more selected media
     items is being published right now. Try again when it finishes."}`
  2. `{"code": "metadata_removal_in_progress", "message": "Metadata is being removed from
     one or more selected media items. Try again when it finishes."}`
- `confirmation` se devuelve también con bloqueo.

### Errores

| Caso | Código |
|---|---|
| Lista vacía, > 500, repetidos, tipos inválidos, campos extra | `422` |
| Project inexistente | `404 not_found` "Project not found." |
| Algún Media inexistente o de otro Project | `404 not_found` "Some selected media no longer exist. Review your selection." |

## 3. Delete

`POST /api/projects/{project_id}/contents/delete`

```json
{"content_ids": [3, 4, 5], "confirmation": "v1:3f9a…"}
```

### `204` — todos los Media y todos sus Posts borrados; archivos borrados o en cola.

### Errores (ninguno tiene efecto en BD, guards ni disco)

| Caso | Código | Mensaje |
|---|---|---|
| Validación (como el preview) o falta `confirmation` | `422` | — |
| Project inexistente | `404 not_found` | "Project not found." |
| Algún Post dependiente Publishing/running (con o sin Remove metadata en otro Media) | `409 post_in_progress` | mensaje del blocker 1 |
| Remove metadata en algún Media y ningún Post Publishing/running | `409 metadata_removal_in_progress` | mensaje del blocker 2 |
| Algún Media inexistente o de otro Project | `409 deletion_changed` | "Something changed since you opened this. Review it again before deleting." |
| Token distinto del alcance actual (Post añadido/eliminado, `status` o `needs_review` cambiado) | `409 deletion_changed` | ídem |
| Otro borrado ya retiene alguno de los Media | `409 deletion_changed` | ídem |
| Error interno | `500 internal_error` | rollback completo |

Un fallo al eliminar archivos **después** del COMMIT no cambia el `204`: las filas de
`pending_file_deletions` permanecen y el arranque reintenta.

## 4. Efectos cruzados (sin cambios de contrato)

| Ruta | Durante un Bulk Delete que retiene el Media |
|---|---|
| `POST /api/contents/{id}/remove-metadata` | `409 content_deleting` "This media is being deleted." |
| Claim del scheduler / `POST /api/publications/{id}/publish` | espera el writer lock; tras el COMMIT el Post no existe (`404` en publish manual; el scheduler no lo ve) |
| `POST /api/projects/{id}/contents/move` | permitido; no afecta al token |

## 5. Garantías observables

- Tras `204`, ningún endpoint devuelve los Media borrados ni sus Posts.
- Ningún Bulk Delete contacta plataformas.
- Los ids de Media y Posts no se reutilizan (`AUTOINCREMENT`, 021).
- Ningún error expone SQL, rutas ni referencias internas.
