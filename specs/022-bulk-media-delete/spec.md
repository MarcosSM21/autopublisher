# Feature Specification: Bulk Media Delete

**Feature Branch**: `022-bulk-media-delete`

**Created**: 2026-10-25

**Status**: Ready for planning

**Input**: User description: "Feature 022 — Bulk Media Delete. Permitir borrar varios Media
seleccionados desde Select mode de Library (Folder, Unsorted, All media) con UNA confirmación
agregada, de forma all-or-none, reutilizando la infraestructura de deletion de Feature 021
(preview + confirmation token, ContentFileGuard, exclusión con Remove metadata y con Posts
Publishing/running, `_delete_posts`, `_delete_contents`, pending file cleanup post-COMMIT y en
startup). Sin rediseñar el sistema de deletion. Solo Media: sin bulk de Posts, Accounts,
Projects ni Folders; sin Trash, Undo, soft-delete, borrado remoto ni framework general de
bulk actions."

## Regla de producto

**Bulk Delete is all-or-none.** Borrar una selección es una única operación lógica: o
desaparecen todos los Media seleccionados (y todos sus Posts locales), o no cambia nada.
Nunca hay éxito parcial, ni en el backend ni en lo que muestra la UI.

Se mantiene la regla de Feature 021: **Delete = gone from the user-facing product**, y
**Delete → exactly one confirmation**. El contenido ya publicado en plataformas nunca se toca.

## Contexto (infraestructura existente que se reutiliza)

Contexto para la planificación; el comportamiento exigido está en Requirements.

- Feature 021 ya ofrece borrado individual de Media: preview de solo lectura con
  `counts`, `summary`, `blocker` y `confirmation`; DELETE con `confirmation`; errores
  `404 not_found`, `409 post_in_progress`, `409 metadata_removal_in_progress`,
  `409 deletion_changed`.
- La ejecución sigue un orden fijo: retener Media frente a Remove metadata → una única
  transacción de escritura que bloquea al scheduler → recalcular alcance → bloqueos → token →
  borrar Posts dependientes → encolar archivos (write-ahead) → borrar Media → COMMIT →
  liberar → limpieza de archivos (los fallos quedan en cola para el arranque).
- El guard de archivos de Media ya retiene un conjunto de ids de forma all-or-none y en
  orden determinista; si alguno se está saneando falla con `metadata_removal_in_progress`, y
  si otro borrado ya retiene alguno falla con `deletion_changed`.
- Las primitivas internas de borrado de Posts y de Media ya trabajan sobre conjuntos de ids
  dentro de una transacción abierta, sin commit propio ni acceso a disco.
- Library ya tiene Select mode en Folder, Unsorted y All media, con una barra inferior
  `N selected · Move · Cancel` y Move múltiple atómico (1–500 ids del mismo Project, `404` y
  nada cambia si algún id no existe o es de otro Project).
- La Library es por Project: Select mode solo puede contener Media del Project abierto.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Borrar varios Media con una sola confirmación (Priority: P1)

El usuario entra en Select mode en una vista de Library, marca varios Media y pulsa Delete.
AutoPublisher muestra una única confirmación con las consecuencias agregadas de toda la
selección (cuántos Media y cuántos Posts desaparecen, cuántos pueden existir ya en
plataformas). El usuario confirma y todos los Media seleccionados, con todos sus Posts
locales, desaparecen de AutoPublisher.

**Why this priority**: Es el valor central de la feature: limpiar la Library sin repetir el
borrado individual Media por Media.

**Independent Test**: Con un Project que tiene 3 Media (uno sin Posts, uno con un Post
Scheduled, uno con un Post Published), seleccionar los 3, pulsar Delete, confirmar una vez y
verificar que los 3 Media y sus 2 Posts ya no aparecen en ninguna vista ni contador.

**Acceptance Scenarios**:

1. **Given** Select mode con 0 Media seleccionados, **When** el usuario mira la barra,
   **Then** ve `0 selected · Move · Delete · Cancel` con Move y Delete deshabilitados.
2. **Given** 8 Media seleccionados que suman 12 Posts (3 Published/Awaiting user action),
   **When** pulsa Delete, **Then** ve una sola confirmación que indica que 8 media items y 12
   posts se eliminarán de AutoPublisher, que 3 posts pueden existir ya en plataformas y que el
   contenido publicado en plataformas no se ve afectado; no ve una lista Media por Media.
3. **Given** la confirmación abierta sin bloqueos, **When** el usuario confirma, **Then**
   todos los Media seleccionados y todos sus Posts desaparecen de la vista actual, de los
   contadores de Folder/Unsorted/All media, de Posts (listas, Calendar, History) y de
   Home/overview, sin ninguna confirmación adicional.
4. **Given** la confirmación abierta, **When** el usuario cancela, **Then** no se borra nada
   y la selección se conserva.
5. **Given** un borrado correcto, **When** la vista queda vacía, **Then** se muestra su empty
   state normal sin navegar fuera de la vista.
6. **Given** la selección incluye un Media con Posts en Needs review, **When** se abre la
   confirmación, **Then** se muestra además el aviso de que esos posts pueden haberse
   publicado ya y que conviene revisar las plataformas antes de volver a publicar ese
   contenido.

---

### User Story 2 - Un elemento ocupado bloquea toda la selección (Priority: P1)

Si cualquier Media seleccionado tiene un Post publicándose en ese momento o se le está
quitando la metadata, el Bulk Delete completo se bloquea: no se borra ninguno y el usuario
recibe una explicación humana.

**Why this priority**: Es la garantía de seguridad de la semántica all-or-none; sin ella la
feature no es aceptable.

**Independent Test**: Seleccionar 3 Media, uno de ellos con un Post en Publishing; abrir
Delete y verificar que la confirmación muestra el bloqueo, no ofrece borrar y los 3 Media
siguen intactos.

**Acceptance Scenarios**:

1. **Given** uno de los Media seleccionados tiene un Post Publishing/running, **When** se
   abre la confirmación, **Then** se muestra un bloqueo indicando que uno o más elementos
   seleccionados están ocupados publicándose y que se reintente al terminar, sin opción de
   borrar.
2. **Given** a uno de los Media seleccionados se le está quitando la metadata, **When** se
   abre la confirmación, **Then** se muestra un bloqueo equivalente para Remove metadata.
3. **Given** la confirmación se abrió sin bloqueo, **When** antes de confirmar empieza la
   publicación de un Post de uno de los Media, **Then** al confirmar el borrado falla con un
   bloqueo y ningún Media de la selección se borra.
4. **Given** el Media A seleccionado tiene un Post Publishing/running y al Media B
   seleccionado se le está quitando la metadata, **When** se abre la confirmación o se
   confirma, **Then** siempre se muestra el bloqueo de publicación en curso
   (`post_in_progress`), independientemente del orden de selección o de los ids, y no se
   borra nada.
5. **Given** el Bulk Delete ya ha empezado, **When** el scheduler o el usuario intenta
   empezar la publicación de cualquier Post dependiente, o Remove metadata en cualquiera de
   los Media, **Then** ese intento no puede empezar y, tras el borrado, el Post ya no existe.

---

### User Story 3 - Cambios entre la confirmación y el borrado (Priority: P2)

Si algo relevante cambia entre que el usuario ve la confirmación y la acepta (aparece o
desaparece un Post dependiente, cambia un estado relevante, desaparece un Media
seleccionado), AutoPublisher no borra nada, muestra las consecuencias actualizadas y exige
otro clic explícito en Delete.

**Why this priority**: Garantiza que el usuario solo borra exactamente lo que vio; es menos
frecuente que los flujos anteriores.

**Independent Test**: Abrir la confirmación de 2 Media, crear por otra vía un Post nuevo
para uno de ellos, confirmar y verificar que no se borra nada y que la confirmación se
refresca con el nuevo número de Posts.

**Acceptance Scenarios**:

1. **Given** la confirmación abierta, **When** se crea o borra un Post de algún Media
   seleccionado, o cambia su estado o su marca de Needs review, y el usuario confirma,
   **Then** no se borra nada, la confirmación se recarga con las consecuencias actualizadas
   y el usuario debe pulsar Delete de nuevo.
2. **Given** la confirmación abierta, **When** uno de los Media seleccionados se borra en
   otra pestaña y el usuario confirma, **Then** no se borra ninguno de los restantes; la
   vista y la selección se refrescan (el Media desaparecido sale de la selección) y el
   usuario debe revisar y pulsar Delete de nuevo.
3. **Given** el usuario pulsa Delete con un Media seleccionado que ya no existe, **When** se
   pide el preview, **Then** no se muestra una confirmación sobre una selección obsoleta: la
   vista y la selección se refrescan con un aviso breve.
4. **Given** dos confirmaciones del mismo conjunto (doble clic u otra pestaña), **When**
   ambas se envían a la vez o una tras otra, **Then** como mucho una tiene efecto; la otra no
   borra nada y recibe `409 deletion_changed`.

---

### User Story 4 - Uso en móvil (Priority: P3)

Desde un móvil, el usuario puede seleccionar Media con toques, ver Delete en la barra
inferior y confirmar en la Sheet de confirmación existente, con textos legibles.

**Why this priority**: AutoPublisher ya es usable en móvil/LAN; la feature debe mantenerlo,
pero el flujo de desktop es el principal.

**Independent Test**: En un viewport de teléfono, seleccionar 2 Media, pulsar Delete,
confirmar en la Sheet y verificar que desaparecen.

**Acceptance Scenarios**:

1. **Given** viewport de teléfono en Select mode, **When** se seleccionan Media, **Then** la
   barra inferior muestra el contador, Move, Delete y Cancel sin desbordarse ni tapar la
   navegación.
2. **Given** viewport de teléfono, **When** se pulsa Delete, **Then** la confirmación se abre
   como Sheet con el resumen agregado legible y la acción de confirmar accesible con el
   pulgar.

---

### Edge Cases

- **Selección vacía**: Delete deshabilitado; la ruta del backend rechaza una lista vacía
  sin efecto.
- **Ids repetidos o de otro Project**: rechazados; nada cambia. No se pueden mezclar
  Projects (la Library es por Project y la petición va dirigida a un único Project).
- **Varios tipos de bloqueo a la vez** (un Media con un Post Publishing/running y otro en
  Remove metadata): todo el Bulk Delete queda bloqueado y se informa de un único bloqueo
  según la precedencia fija `post_in_progress` > `metadata_removal_in_progress`, tanto en el
  preview como en la confirmación.
- **Media sin Posts**: se borra igual; el resumen solo menciona Media.
- **Un Media con muchos Posts y estados mezclados** (Draft, Scheduled, Failed, Published,
  Awaiting user action, Needs review): todos los Posts desaparecen; solo Published/Awaiting
  y Needs review alteran los avisos.
- **Selección de 1 Media**: funciona como bulk de uno (mismas consecuencias que el borrado
  individual, con textos en singular).
- **Selección por encima del límite**: rechazada antes de calcular nada, con mensaje claro.
- **Un Media seleccionado desaparece antes del preview**: preview rechazado como selección
  obsoleta; refrescar vista y selección; no se ofrece borrar el resto automáticamente.
- **Un Media seleccionado desaparece entre preview y confirmación**: el borrado se rechaza
  como cambio; nada se borra; la UI refresca y exige otro Delete.
- **Otro borrado retiene ya alguno de los Media** (borrado individual, otro bulk, borrado del
  Project): el bulk falla como cambio y nada se borra.
- **Remove metadata intenta empezar sobre un Media mientras el bulk lo retiene**: Remove
  metadata se rechaza con el error existente ("This media is being deleted.").
- **El Media abierto en Media detail forma parte de la selección borrada**: el detalle se
  cierra y la vista queda en su lista.
- **Fallo al eliminar uno o varios archivos tras el COMMIT** (original o clean copy): el
  borrado sigue siendo un éxito; los archivos quedan en la cola de limpieza y se reintentan
  en el siguiente arranque. No se restaura ninguna parte.
- **Error interno durante la transacción**: rollback completo; los Media, Posts y archivos
  quedan como estaban y no queda ninguna entrada de limpieza registrada.
- **Error de red tras confirmar**: la UI no muestra un estado parcial; recarga la vista y
  refleja el estado real (todo borrado o nada borrado).
- **Ids reutilizados**: ningún Media ni Post creado después reutiliza un id borrado (se
  mantiene la garantía de 021), de modo que un token o una selección antigua nunca puede
  apuntar a un objeto nuevo.
- **Move durante un bulk Delete pendiente de confirmación**: Move mantiene su semántica; si
  mueve Media de la selección, el alcance destructivo no cambia (la carpeta no forma parte
  del token) y el borrado procede.

## Requirements *(mandatory)*

### Functional Requirements

**Selección y barra**

- **FR-001**: La barra de Select mode MUST mostrar `N selected`, Move, Delete y Cancel en
  Folder, Unsorted y All media, en desktop y en móvil.
- **FR-002**: Delete MUST estar deshabilitado cuando no hay Media seleccionados, y MUST
  presentarse como acción destructiva sin ser la acción visualmente dominante de la barra.
- **FR-003**: Move MUST conservar su comportamiento y su semántica actuales.
- **FR-004**: Una selección MUST contener solo Media del Project abierto; el sistema MUST
  rechazar cualquier petición que incluya ids de otro Project, ids repetidos o una lista
  vacía, sin efecto alguno.
- **FR-005**: El sistema MUST limitar una operación a 500 Media como máximo (el mismo límite
  que Move); una petición mayor MUST rechazarse antes de calcular o cambiar nada.

**Preview agregado**

- **FR-006**: Antes de confirmar, el sistema MUST calcular, sin modificar ni reservar nada,
  las consecuencias del conjunto completo: número de Media que desaparecen, total de Posts
  dependientes, Posts no publicados, Posts que pueden existir remotamente (Published +
  Awaiting user action), Posts en Needs review, bloqueo si existe y token de confirmación.
- **FR-007**: El preview MUST devolver un resumen humano agregado (en inglés, con
  pluralización correcta y frases omitidas cuando su cuenta es 0), por ejemplo:
  "8 media items and 12 posts will be removed from AutoPublisher." · "3 posts may already
  exist on platforms. Content already published on platforms is not affected." y, si aplica,
  "2 posts may already have been published. Check the platforms before publishing this
  content again."
- **FR-008**: El preview MUST NOT listar las consecuencias Media por Media.
- **FR-009**: Si algún Media seleccionado no existe (o no pertenece al Project), el preview
  MUST rechazarse como selección obsoleta, sin devolver un resumen parcial del resto.

**Confirmación**

- **FR-010**: La UI MUST pedir exactamente una confirmación para todo el conjunto, usando el
  diálogo/Sheet de confirmación de borrado existente; MUST NOT pedir escribir nombres, una
  segunda pantalla ni confirmaciones por Media.
- **FR-011**: Con bloqueo, la confirmación MUST mostrar el mensaje humano y MUST NOT ofrecer
  la acción de borrar.

**Token de confirmación**

- **FR-012**: El token MUST cubrir el alcance destructivo completo: todos los ids de Media
  seleccionados y todos los Posts dependientes como `(id, status, needs_review)`.
- **FR-013**: El token MUST ser determinista e independiente del orden en que se envían los
  ids, y MUST NOT contener timestamps, nombres de archivo, rutas ni secretos.
- **FR-014**: El token MUST cambiar si aparece o desaparece un Media seleccionado o un Post
  dependiente, si cambia un estado persistido relevante de un Post o si cambia su marca
  Needs review. Un token de bulk MUST NOT ser válido para un borrado individual ni al revés.

**Bloqueos**

- **FR-015**: Si cualquier Media seleccionado tiene un Post Publishing/running, el Bulk
  Delete completo MUST rechazarse (`post_in_progress`) y no borrar nada.
- **FR-016**: Si a cualquier Media seleccionado se le está quitando la metadata, el Bulk
  Delete completo MUST rechazarse (`metadata_removal_in_progress`, salvo la precedencia de
  FR-017a) y no borrar nada.
- **FR-017**: Los mensajes de bloqueo MUST explicar de forma humana, con la fórmula agregada
  "one or more selected media items", que hay elementos ocupados y que se reintente al
  terminar; MUST NOT identificar el Media concreto.
- **FR-017a**: Si en la misma selección concurren varios tipos de bloqueo, el sistema MUST
  informar de uno solo, elegido con una precedencia determinista e independiente del orden
  de los ids y de las consultas: 1) `post_in_progress`, 2) `metadata_removal_in_progress`.
  La misma precedencia MUST aplicarse al `blocker` del preview y al error del borrado (si la
  retención de los Media falla por Remove metadata, el sistema MUST comprobar antes, en modo
  solo lectura, si algún Post dependiente está Publishing/running y, en ese caso, responder
  `post_in_progress`). No se devuelve una lista de bloqueos. `deletion_changed` no es un
  bloqueo del preview: es un error de cambio de alcance o de retención del borrado.

**Ejecución all-or-none**

- **FR-018**: El borrado MUST ejecutarse como una única operación lógica en una sola
  transacción de escritura; MUST NOT implementarse como una serie de borrados individuales
  con commits independientes.
- **FR-019**: Antes de la transacción, el sistema MUST retener todos los Media seleccionados
  frente a Remove metadata de forma all-or-none y en orden determinista, mantenerlos
  retenidos durante la validación y la transacción, y liberarlos siempre al terminar (éxito
  o error). Si otro borrado retiene ya alguno, MUST fallar con `deletion_changed` sin efecto.
- **FR-020**: Dentro de la transacción y en este orden, el sistema MUST: recalcular el
  alcance completo; comprobar que todos los Media existen y están retenidos; comprobar Posts
  Publishing/running; comprobar el token; borrar todos los Posts dependientes y lo que cuelga
  de ellos; registrar todas las eliminaciones de archivos pendientes (original y clean copy
  cuando exista) de forma write-ahead; borrar todos los Media; COMMIT.
- **FR-021**: Si cualquier comprobación falla o se produce un error, MUST hacerse rollback
  completo: ningún Media, Post, entrada de limpieza ni archivo cambia.
- **FR-022**: El sistema MUST NOT tocar el sistema de archivos antes del COMMIT.
- **FR-023**: Tras el COMMIT, el sistema MUST intentar eliminar los archivos encolados; un
  fallo en uno o varios MUST NOT convertir el borrado en error ni restaurar nada: los
  archivos no eliminados quedan en la cola y se reintentan en el arranque.

**Carreras**

- **FR-024**: Si el Bulk Delete obtiene primero el acceso de escritura, ningún Post
  dependiente MUST poder empezar a publicarse después (scheduler o publicación manual).
- **FR-025**: Si el scheduler o una publicación manual reclama primero cualquier Post
  dependiente, el Bulk Delete completo MUST fallar con `409` y ningún Media del conjunto se
  borra.
- **FR-026**: Si el Bulk Delete retiene primero los Media, Remove metadata MUST NOT poder
  empezar en ninguno de ellos; si Remove metadata empezó primero en alguno, el Bulk Delete
  completo MUST bloquearse.

**Cambios y selección obsoleta**

- **FR-027**: Si el alcance difiere del confirmado (incluido un Media seleccionado que ya no
  existe), el borrado MUST rechazarse con `409 deletion_changed` sin borrar nada.
- **FR-028**: Ante `deletion_changed`, la UI MUST volver a pedir el preview, mostrar las
  consecuencias actualizadas y exigir otro clic explícito en Delete; MUST NOT reintentar el
  borrado automáticamente con el alcance nuevo.
- **FR-029**: Si el preview indica selección obsoleta, la UI MUST refrescar la vista,
  quitar de la selección los Media que ya no existen, informar brevemente y no borrar nada;
  el usuario decide si vuelve a pulsar Delete con la selección restante.

**Contenido remoto**

- **FR-030**: El Bulk Delete MUST NOT borrar publicaciones remotas, revocar permisos ni
  contactar ninguna plataforma (ni para borrar, ni para comprobar, ni para reconciliar).
  Published, Awaiting user action y Needs review solo afectan a los avisos del preview.

**Después del borrado**

- **FR-031**: Tras un borrado correcto, la UI MUST quitar todos los Media borrados de la
  vista y de la selección a la vez (sin estado visual parcial), refrescar los contadores de
  Folder, Unsorted y All media, y los datos de Posts y Home/overview, permaneciendo en la
  vista actual.
- **FR-032**: Tras un error (bloqueo, cambio, selección obsoleta, red o interno), la UI MUST
  NOT mostrar ningún Media como borrado si no lo está, y MUST conservar la selección de los
  Media que siguen existiendo.
- **FR-033**: Tras un borrado correcto, ningún endpoint MUST devolver los Media borrados ni
  sus Posts (listas, detalle, overview, uso de Media, Calendar, History).

**Compatibilidad**

- **FR-034**: El borrado individual de Media de Feature 021 (preview, DELETE, errores y
  textos) MUST seguir funcionando sin cambios.
- **FR-035**: Las rutas nuevas MUST estar sujetas a las mismas protecciones de acceso que el
  resto de la API (Host, Origin en métodos inseguros, sesión de instalación); ningún error
  MUST exponer SQL, rutas de archivo ni referencias internas.

### API observable (confirmada, D1)

Coherente con Move (`POST /api/projects/{project_id}/contents/move`) y con el patrón de
borrado de 021. Se usan rutas anidadas en el Project para que la pertenencia al Project sea
explícita, y `POST` con body en lugar de `DELETE` con body (soporte irregular de body en
`DELETE`).

| Acción | Ruta | Body |
|---|---|---|
| Preview | `POST /api/projects/{project_id}/contents/deletion-preview` | `{"content_ids": [3, 4, 5]}` |
| Delete | `POST /api/projects/{project_id}/contents/delete` | `{"content_ids": [3, 4, 5], "confirmation": "…"}` |

`content_ids`: 1–500, sin repetidos (misma validación que Move).

**Preview → `200`** (solo lectura; misma forma que el preview de 021):

```json
{
  "kind": "media_selection",
  "id": null,
  "name": null,
  "counts": {
    "media": 8,
    "posts": 12,
    "unpublished_posts": 9,
    "remote_posts": 3,
    "needs_review_posts": 0,
    "accounts": 0, "subfolders": 0, "media_to_unsorted": 0
  },
  "summary": [
    "8 media items and 12 posts will be removed from AutoPublisher.",
    "3 posts may already exist on platforms. Content already published on platforms is not affected."
  ],
  "blocker": null,
  "confirmation": "v1:…"
}
```

**Delete → `204`**, o:

| Estado | Código | Mensaje |
|---|---|---|
| Lista vacía, > 500, repetidos, falta `confirmation` | `422` | validación existente |
| Project inexistente | `404 not_found` | "Project not found." |
| Algún Media inexistente o de otro Project (preview) | `404 not_found` | "Some selected media no longer exist. Review your selection." |
| Algún Media inexistente o de otro Project (delete) | `409 deletion_changed` | "Something changed since you opened this. Review it again before deleting." |
| Algún Post dependiente Publishing/running | `409 post_in_progress` | "A post using one or more selected media items is being published right now. Try again when it finishes." |
| Remove metadata en algún Media (y ningún Post Publishing/running) | `409 metadata_removal_in_progress` | "Metadata is being removed from one or more selected media items. Try again when it finishes." |
| Alcance distinto / otro borrado retiene alguno | `409 deletion_changed` | mensaje existente |

Un borrado rechazado no tiene ningún efecto en la base de datos ni en el disco. Con varios
bloqueos a la vez se aplica la precedencia de FR-017a. Las rutas individuales de 021
(`GET /api/contents/{id}/deletion-preview`, `DELETE /api/contents/{id}`) no cambian.

### Deletion semantics (resumen)

- **Qué desaparece**: cada Media seleccionado, todos los Posts que lo usan (cualquier
  estado) y todo lo que cuelga de esos Posts; los archivos original y clean copy de cada
  Media (tras el COMMIT, o en la limpieza diferida).
- **Qué no cambia**: carpetas, Accounts, presets, otros Media y Posts, y todo el contenido
  remoto.
- **Orden**: retener Media → transacción (alcance → existencia/retención → Publishing → token
  → Posts → cola de archivos → Media) → COMMIT → liberar → limpieza de archivos.
- **Garantía**: todos o ninguno; un único Media ocupado o un único cambio bloquea todo.

### Key Entities

- **Media selection**: conjunto no vacío (máx. 500) de ids de Media de un mismo Project,
  elegido en Select mode. Es el objetivo del borrado; no se persiste.
- **Aggregate deletion preview**: consecuencias del conjunto completo (conteos, resumen,
  bloqueo, token). Se calcula sin efectos.
- **Confirmation token (bulk)**: huella determinista del alcance destructivo: ids de Media
  ordenados + Posts dependientes `(id, status, needs_review)` ordenados, con un
  discriminador propio del bulk.
- **Pending file deletion**: entrada existente de 021 por cada archivo (original / clean
  copy) que debe eliminarse tras el COMMIT o en el arranque.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Borrar varios Media requiere exactamente: seleccionarlos en Select mode, una
  acción Delete y una única confirmación; tras confirmar, el resultado (Media desaparecidos,
  contadores y vistas actualizados) se refleja sin ningún paso adicional del usuario.
- **SC-002**: En el 100% de los casos probados (bloqueo, cambio de alcance, Media
  desaparecido, carrera con scheduler, carrera con Remove metadata, error interno) el
  resultado es "todos borrados" o "ninguno borrado"; nunca un subconjunto.
- **SC-003**: Un solo Media ocupado (publicándose o saneándose) en una selección de cualquier
  tamaño impide el borrado del 100% de la selección.
- **SC-004**: Ningún Post borrado llega a empezar una publicación después de un Bulk Delete
  correcto.
- **SC-005**: Cero llamadas a plataformas durante cualquier Bulk Delete.
- **SC-006**: Tras un Bulk Delete correcto, todos los archivos de los Media borrados se
  eliminan inmediatamente o quedan en la cola de limpieza y se eliminan en el siguiente
  arranque; no quedan filas huérfanas ni referencias rotas.
- **SC-007**: El flujo completo (seleccionar, Delete, confirmar) funciona en Folder,
  Unsorted y All media, en desktop y en un viewport de teléfono.
- **SC-008**: Una selección de 500 Media se previsualiza y se borra sin errores ni
  degradación perceptible (confirmación visible en menos de 2 segundos en la instalación
  de referencia).
- **SC-009**: El borrado individual de Media y Move se comportan exactamente igual que antes
  de la feature.

## Assumptions

- Se reutiliza la infraestructura de 021 (guard de archivos, transacción de escritura,
  primitivas de borrado, cola de archivos, limpieza en arranque, diálogo de confirmación);
  no se introduce un framework general de bulk actions.
- El límite de 500 Media por operación (igual que Move) cubre la escala esperada (decenas,
  ocasionalmente cientos) y acota el coste del preview y de la transacción.
- La selección no sobrevive a un cambio de vista (comportamiento actual de Select mode); por
  tanto todos los Media seleccionados son del Project abierto.
- Los textos de resumen y de error se redactan en inglés, como el resto de la UI.
- La carpeta de un Media no forma parte del alcance destructivo; un Move concurrente no
  invalida el token.
- No se añade selección múltiple en Media detail; no hay bulk de Posts, Accounts, Projects
  ni Folders; no hay Trash, Undo ni soft-delete.

## Decisiones confirmadas

- **D1 — API**: `POST /api/projects/{project_id}/contents/deletion-preview` con
  `{"content_ids": [...]}` y `POST /api/projects/{project_id}/contents/delete` con
  `{"content_ids": [...], "confirmation": "..."}`. El borrado individual de Media de 021 no
  cambia.
- **D2 — Selección obsoleta**: preview con algún Media inexistente o ajeno → `404 not_found`
  agregado; delete cuando el conjunto ya cambió → `409 deletion_changed`. En ambos casos no
  se borra nada.
- **D3 — Límite**: 500 Media por operación, igual que Move.
- **D4 — Bloqueo**: mensaje agregado ("one or more selected media items"), sin identificar
  el Media concreto; con varios bloqueos, precedencia FR-017a.
- **D5 — Esquema del preview**: se reutiliza el de 021 con `kind = "media_selection"`,
  `id = null`, `name = null`; no se crea un esquema nuevo.

## Tests críticos (referencia para `/speckit-tasks`)

- **Backend**: 2+ Media borrados; Media con varios Posts; estados mezclados; un Post
  Publishing → nada borrado; un Remove metadata → nada borrado; **Publishing en un Media y
  Remove metadata en otro → `post_in_progress` en preview y delete, con cualquier orden de
  ids, y nada borrado**; carrera con el scheduler en ambos órdenes; token determinista con
  cualquier orden de ids; cambio de alcance → `deletion_changed`; un Media desaparece →
  `404` en preview y `409` en delete, sin borrado parcial; rollback ante error → todo
  intacto; original + clean copies encolados; fallos de unlink; reintento en el arranque;
  ninguna llamada a publishers remotos; ids no reutilizados; borrado individual de 021 sin
  cambios.
- **Frontend**: Select muestra Move + Delete; Delete deshabilitado con 0; preview agregado;
  una sola confirmación; bloqueo sin acción Delete; `deletion_changed` → preview refrescado
  y nueva confirmación; `404` → vista y selección refrescadas; éxito quita todas las
  tarjetas a la vez; sin estado visual parcial; Folder / Unsorted / All media; Sheet móvil.
