# API Contract — Feature 021: Deletion & Library Organization

Formato de error existente: `{"error": {"code": "...", "message": "...", "fields": [...]}}`.
Todas las rutas nuevas están bajo `/api` y, por tanto, sujetas a los guards de 020 (Host,
Origin en métodos inseguros, sesión de instalación). No hay exenciones nuevas (FR-053).
Solo se listan cambios.

## 1. Patrón común de borrado

Para cada `kind`:

| kind | Preview | Delete |
|---|---|---|
| Post | `GET /api/publications/{id}/deletion-preview` | `DELETE /api/publications/{id}?confirmation=…` |
| Media | `GET /api/contents/{id}/deletion-preview` | `DELETE /api/contents/{id}?confirmation=…` |
| Account | `GET /api/accounts/{id}/deletion-preview` | `DELETE /api/accounts/{id}?confirmation=…` (sustituye al descarte de cuenta provisional) |
| Project | `GET /api/projects/{id}/deletion-preview` | `DELETE /api/projects/{id}?confirmation=…` |
| Folder | `GET /api/library-folders/{id}/deletion-preview` | `DELETE /api/library-folders/{id}?confirmation=…` |

### Preview → `200`

Solo lectura; nunca bloquea ni reserva nada.

```json
{
  "kind": "media",
  "id": 42,
  "name": "launch-teaser.mp4",
  "counts": {
    "unpublished_posts": 2,
    "remote_posts": 1,
    "needs_review_posts": 0,
    "accounts": 0,
    "posts": 3,
    "media": 0,
    "subfolders": 0,
    "media_to_unsorted": 0
  },
  "summary": [
    "2 unpublished posts and 1 published post will also be removed from AutoPublisher.",
    "Content already published on platforms is not affected."
  ],
  "blocker": null,
  "confirmation": "v1:3f9a…"
}
```

- `counts`: todos los campos siempre presentes (0 si no aplica). `remote_posts` = Published +
  Awaiting user action; `needs_review_posts` aparte; `posts` = total de Posts que
  desaparecen.
- `summary`: frases en inglés listas para mostrar, en orden. Vacío → confirmación simple.
- `blocker`: `null` o `{"code": "post_in_progress" | "metadata_removal_in_progress",
  "message": "…"}`. Con bloqueo, la UI muestra el mensaje y no ofrece Delete.
- `confirmation`: token opaco determinista del alcance (research §3). Se devuelve también
  con bloqueo.
- `404 not_found` si el objeto no existe (o es de otro proyecto en rutas anidadas).

### Delete → `204`

`confirmation` obligatorio (query). Transacción única; nada cambia si falla.

| Estado | Código | Mensaje (ejemplos exactos) |
|---|---|---|
| Borrado | `204` | — |
| No existe (incl. segundo borrado) | `404 not_found` | "Post not found." / "Media not found." / "Account not found." / "Project not found." / "Folder not found." |
| Post afectado publicándose | `409 post_in_progress` | Post: "This post is being published right now. Try again when it finishes." · Media: "A post using this media is being published right now. Try again when it finishes." · Account: "A post of this account is being published right now. Try again when it finishes." · Project: "A post in this project is being published right now. Try again when it finishes." |
| Remove metadata en curso | `409 metadata_removal_in_progress` | Media: "Metadata is being removed from this media. Try again when it finishes." · Project: "Metadata is being removed from a media item in this project. Try again when it finishes." |
| Alcance distinto al del preview | `409 deletion_changed` | "Something changed since you opened this. Review it again before deleting." |
| Falta `confirmation` | `422` (validación existente) | — |

Una conexión, OAuth o login en curso **nunca** produce 409 (FR-028). No existe
`account_busy` ni `account_not_discardable`.

Un borrado rechazado (cualquier 409/404/422 o error interno) no tiene **ningún** efecto:
ni en la BD, ni en los intentos de conexión en memoria, ni en el keyring, ni en el disco.
Los intentos de conexión de las cuentas borradas se invalidan solo después del COMMIT, sin
contactar plataformas (TikTok incluido: la credencial pendiente se descarta sin revocarla).

`409 deletion_changed` también se devuelve si otro borrado concurrente ya retiene alguno de
los Media afectados.

### Textos de `summary` por kind

Pluralización inglesa (`1 post` / `2 posts`); las frases se omiten cuando su cuenta es 0.

| kind | Frases |
|---|---|
| Post (unpublished) | "This post will not be published." solo si estaba programado; si no, vacío. |
| Post (remote) | "It will only be removed from AutoPublisher. The content published on {Platform} is not affected." |
| Post (needs review) | "This post may have been published. Check {Platform} before publishing this media again." |
| Media | "{n} unpublished post(s) and {m} published post(s) will also be removed from AutoPublisher." · "Content already published on platforms is not affected." (si m>0) · advertencia Needs review si aplica |
| Account | Igual que Media + "Your {@handle} account on {Platform} is not affected." (siempre; sin handle: "Your {Platform} account is not affected.") |
| Project | "This project contains {a} account(s), {p} post(s) and {k} media item(s). Everything will be removed from AutoPublisher." · "Content already published on platforms is not affected." (si hay Posts remotos) — vacío si el proyecto está vacío |
| Folder | "{s} subfolder(s) will also be removed." · "{k} media item(s) will move to Unsorted." · "No media is deleted." (si s>0 o k>0) |

## 2. Carpetas de Library

### `GET /api/projects/{project_id}/library-folders` → `200`

```json
{
  "folders": [
    {"id": 7, "parent_id": null, "name": "Cybersecurity", "depth": 1, "media_count": 5},
    {"id": 9, "parent_id": 7, "name": "DDoS", "depth": 2, "media_count": 3}
  ],
  "unsorted_count": 12,
  "total_count": 20
}
```

Árbol plano completo, ordenado por `depth, name_key`. `media_count` = Media asignada
directamente. `404` si el proyecto no existe.

### `POST /api/projects/{project_id}/library-folders` → `201 LibraryFolderRead`

Request `{"name": "DDoS", "parent_id": 7}` (`parent_id` null = primer nivel).

| Error | Cuándo |
|---|---|
| `422` | Nombre vacío o > 100 tras recorte |
| `404 not_found` "Folder not found." | `parent_id` inexistente o de otro proyecto |
| `409 folder_name_taken` "A folder with this name already exists here." | Hermana con el mismo nombre (sin distinguir mayúsculas/Unicode) |
| `409 folder_too_deep` "Folders can be nested up to 5 levels." | El padre ya está en el nivel 5 |

Se permite en proyectos inactivos (organización local, no publica).

### `PATCH /api/library-folders/{folder_id}` → `200 LibraryFolderRead`

Request `{"name": "MFA"}`. Errores: `422`, `404`, `409 folder_name_taken`. Renombrar a la
misma clave (solo cambia mayúsculas) está permitido.

`LibraryFolderRead`: `{id, project_id, parent_id, name, depth, media_count, created_at,
updated_at}`.

## 3. Media en Library

### `GET /api/projects/{project_id}/contents?folder=<folder_id>|unsorted`

- Sin `folder`: todos (comportamiento actual = All media).
- `folder=unsorted`: `folder_id IS NULL`.
- `folder=<id>`: solo asignados directamente. `404` si la carpeta no existe o es de otro
  proyecto.
- Otro valor → `422`.

`ContentRead` gana `folder_id: int | null`.

### `POST /api/projects/{project_id}/contents?folder_id=<id>` (import)

`folder_id` opcional: destino de los Media importados; ausente → Unsorted. Carpeta
inexistente/ajena → `404` antes de procesar ningún archivo. Un duplicado devuelto como
`duplicate` no se mueve.

### `POST /api/projects/{project_id}/contents/move` → `200`

Request `{"content_ids": [3, 4, 5], "folder_id": 9}` (`folder_id` null = Unsorted;
1–500 ids, sin repetidos).

Response `{"moved": 3}`.

Un único `UPDATE` en una transacción: si algún id no existe o no es del proyecto, o la
carpeta es de otro proyecto → `404` y nada cambia. No toca disco ni Posts. Permitido durante
una publicación (FR edge case).

## 4. Cambios en rutas existentes

| Ruta | Cambio |
|---|---|
| `DELETE /api/accounts/{id}` | Ahora es el borrado general (requiere `confirmation`); el descarte de provisional pasa por aquí con el mismo resultado. Desaparecen `account_busy` y `account_not_discardable`. |
| `GET /api/contents/{id}`, listados | `folder_id` añadido. |
| Inicio de publicación (manual) sobre un Post borrado durante el preflight | `404 not_found` en vez de 500. |
| Follow-up / Check result sobre un Post borrado durante la llamada | `404 not_found`. |
| `POST /api/contents/{id}/remove-metadata` mientras ese Media se está borrando | `409 content_deleting` "This media is being deleted." (nada cambia). |
| Callbacks/confirmaciones OAuth (YouTube, Instagram, Threads, TikTok) y pasos de login de Telegram cuya Account se borró | El intento termina con el error existente `oauth_state_invalid` / "Authorization not valid…" (página de callback o respuesta del paso). No se crea Account, Connection ni secreto activo; el secreto ya escrito se borra o queda en la cola de limpieza. |

## 5. Garantías observables

- Tras `204`, ningún endpoint devuelve el objeto ni sus dependientes (listas, detalle,
  overview, uso de Media, presets, calendar/history).
- Ningún borrado contacta una plataforma.
- Ningún error expone `IntegrityError`, SQL, rutas o refs.
