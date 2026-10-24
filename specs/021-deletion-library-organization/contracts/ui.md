# UI Contract — Feature 021

Sin rediseño de 018/019/020: mismos tokens y componentes (`frontend/src/ui`). Textos en
inglés. Solo se describen cambios.

## 1. Componentes compartidos nuevos

### `DeleteConfirmDialog` (`frontend/src/components/DeleteConfirmDialog.tsx`)

Props: `title` ("Delete post?", "Delete media?", "Delete account?", "Delete project?",
"Delete folder?"), `loadPreview()`, `remove(confirmation)`, `onDeleted()`, `open`,
`onOpenChange`.

Flujo:

1. Al abrir: `Skeleton` mientras carga el preview.
2. Preview cargado sin bloqueo: cuerpo = líneas de `summary` (párrafos); vacío → solo el
   título (confirmación simple). Footer: **Cancel** + **Delete** (`variant="danger"`).
3. Con `blocker`: muestra `blocker.message`; footer solo **Close**.
4. Delete → `remove(confirmation)`:
   - `204` → `onDeleted()` (navega + flash).
   - `404` → tratado como ya borrado: `onDeleted()` sin error.
   - `409 deletion_changed` → recarga el preview y muestra encima del resumen nuevo
     "Something changed. Review it again." (`role="alert"`); el usuario vuelve a pulsar
     Delete (sigue siendo una sola confirmación por intento).
   - `409 post_in_progress` / `metadata_removal_in_progress` → mensaje del backend, footer
     **Close**.
   - Otros → mensaje inline, Delete reintentable.
5. Teléfono (`< MEDIA_MD_UP`): `Sheet`; md+: `Dialog` (patrón de `ActionDialog`). Botones a
   ancho completo en teléfono, Delete y Cancel separados, ≥ 44 px.

Nunca pide escribir nombres ni códigos (FR-002).

### `FolderPicker` (`frontend/src/pages/library/FolderPicker.tsx`)

Lista indentada del árbol (de `GET …/library-folders`) con "Unsorted" primero; una fila
táctil por destino (radio). Carpeta actual del Media marcada "Current". Botones **Cancel** /
**Move here**. Teléfono: `Sheet` con scroll interno; md+: `Dialog`.

### `Breadcrumb` (`frontend/src/pages/library/Breadcrumb.tsx`)

`Library / … / Folder` con enlaces; el último no es enlace (`aria-current="page"`). En
teléfono, si hay más de 2 niveles, los intermedios colapsan en un botón "…" que abre un menú
con los niveles ocultos. Nunca provoca scroll horizontal.

### `FolderNameDialog`

Crear ("New folder") y renombrar ("Rename folder"): un campo **Name** (máx. 100),
errores del backend inline (`folder_name_taken`, `folder_too_deep`).

### Flash tras borrar (FR-010)

`navigate(to, { state: { flash: "Post deleted." } })`; el shell lo muestra en una región
`role="status"` que desaparece sola a los ~4 s y se limpia del historial. Textos: "Post
deleted." · "Media deleted." · "Account deleted." · "Project deleted." · "Folder deleted.".

## 2. Library

Rutas (bajo `/p/:projectId`):

| Ruta | Vista |
|---|---|
| `library` | **Library root** |
| `library/unsorted[/:mediaId]` | Unsorted |
| `library/all[/:mediaId]` | All media |
| `library/folders/:folderId[/:mediaId]` | Folder |
| `library/:mediaId` (existente) | Detalle del Media sobre la vista All media |
| `library/:mediaId/publish` (existente) | Sin cambios |

### Library root (FR-039)

Cabecera con **Import media** y **New folder**. Lista de entradas (cards/filas táctiles):
carpetas de primer nivel (nombre + "{n} media"), **Unsorted** ("{n} media"), **All media**
("{n} media"). Nunca cuadrícula de Media. Proyecto sin Media: el `LibraryDropzone`/empty
state de onboarding actual aparece debajo de las entradas (FR-046). Subir desde la raíz →
Unsorted.

### Folder / Unsorted / All media (FR-040–FR-042)

- Breadcrumb arriba (`Library / Unsorted`, `Library / All media`, `Library / A / B`).
- Folder: subcarpetas como filas arriba, luego la cuadrícula de sus Media directos;
  acciones de carpeta en menú "More": **New folder** (si `depth < 5`), **Rename**,
  **Delete folder**.
- Toolbar, búsqueda, filtros, import y detalle existentes, aplicados a los Media de la vista.
- All media: cada card muestra su carpeta ("Unsorted" o nombre) en la meta.
- Import dentro de una carpeta → `folder_id` de esa carpeta; desde Unsorted/All → Unsorted.
- Carpeta inexistente (borrada, de otro proyecto o id inválido) → `NotFound` con "Back to
  Library".
- Tras borrar la carpeta que se está viendo → navega a su padre (o a Library root) con
  flash.

### Select / Move (FR-047–FR-049)

- Botón **Select** en la toolbar de Folder/Unsorted/All media. En modo Select: checkbox
  visible en cada card, barra inferior fija con "{n} selected", **Move** y **Cancel**.
  Única acción: Move. Sin long-press ni gestos ocultos.
- Move → `FolderPicker` → `POST …/contents/move` → recarga lista y contadores; sale de
  Select. Error → mensaje inline, nada cambia.

### Media detail (FR-045)

- Muestra "Folder: {name}" o "Folder: Unsorted".
- Acciones: **Move** (FolderPicker) y, en zona secundaria/menú, **Delete media**
  (`DeleteConfirmDialog`). Tras borrar → vuelve a la vista de Library de la que venía (la
  ruta padre del detalle) con flash.
- Media card: menú "More" con **Move** y **Delete media**.

## 3. Posts

Post detail: **Delete post** en la zona secundaria de acciones (no dominante) para todos
los estados; en Publishing se muestra deshabilitado con "This post is being published right
now." (el backend sigue siendo la autoridad). Tras borrar → `/p/:id/posts` con flash.

## 4. Accounts

Account detail: **Delete account** en zona secundaria (`DeleteConfirmDialog`), cualquier
estado. Tras borrar → `/p/:id/accounts` con flash. **Discard setup** (provisional) mantiene
su texto y diálogo, pero llama a preview + `DELETE` con el token.

## 5. Projects

Project header: menú "More" con **Deactivate/Activate project** (existente) y **Delete
project**. Tras borrar → Home (`/`) con flash; si era el último, Home muestra el onboarding
vacío existente. Se recarga la lista de proyectos del selector.

## 6. Accesibilidad y móvil (FR-056)

- Todas las acciones destructivas: `variant="danger"`, nunca primarias de página.
- Objetivos táctiles ≥ 44 px; foco devuelto al abridor al cerrar diálogos (Dialog
  existente).
- Sin scroll horizontal a 360 px en root, folder, breadcrumb, picker y diálogos.
