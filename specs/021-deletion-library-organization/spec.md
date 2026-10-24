# Feature Specification: Deletion & Library Organization

**Feature Branch**: `021-deletion-library-organization`

**Created**: 2026-10-24

**Status**: Ready for planning

**Input**: User description: "Feature 021 — Deletion & Library Organization. Permitir borrar Projects, Accounts, Posts y Media de forma segura y simple (Delete → Confirm → deleted), resolviendo en el backend toda la complejidad referencial, sin borrar nunca contenido remoto, sin dejar referencias rotas, tareas del scheduler huérfanas ni archivos huérfanos conocidos. Añadir carpetas lógicas (anidadas si es simple) a Library: crear, renombrar, eliminar (el contenido nunca se pierde), mover uno o varios Media, Unsorted, All media, breadcrumb. Todo protegido por la sesión de instalación, funcional en móvil/LAN y cubierto por backup/restore de 020. Sin Trash, soft-delete global, tags, smart folders, borrado remoto, bulk deletion framework ni rediseño general de Library."

## Regla de producto

**Delete = gone from the user-facing product.** Cuando el usuario borra algo, ese objeto y
todos los objetos visibles que dependen de él desaparecen por completo de AutoPublisher: de
listas, detalles, History, Calendar, Home, búsquedas, filtros, contadores e indicadores de
uso. No existen objetos marcados como borrados ni registros "Media deleted" / "Account
removed". El contenido ya publicado en las plataformas nunca se toca.

## Contexto y análisis previo

Resumen del estado actual que condiciona el diseño. Es contexto para la planificación; el
comportamiento exigido está en Requirements.

- **Post** es, en la UI, una Publication: un medio (o texto) en una cuenta. No existe
  entidad de lote; borrar un Post afecta a un único destino.
- Hoy casi todas las relaciones son restrictivas: Project → Accounts, Media, Posts y
  conexiones de plataforma; Account → Posts y conexiones; Media → Posts; Post → intentos de
  ejecución, opciones de plataforma y registros de ejecución por plataforma; intento →
  objetos temporales de entrega de medios. Solo los presets de distribución se borran en
  cascada. Por eso hoy solo existe "descartar" una cuenta provisional y desactivar
  Projects/Accounts.
- Cada conexión de plataforma tiene su **propia** referencia a la credencial en el
  almacenamiento seguro del sistema; ninguna referencia se comparte entre conexiones, cuentas
  ni proyectos.
- Los únicos archivos propios de un Media son el **original** y, si se usó Remove metadata,
  su **copia limpia**. No hay miniaturas ni derivados generados en disco. Los objetos
  temporales subidos al proveedor de entrega pertenecen a intentos de ejecución y ya tienen
  limpieza propia.
- El aviso "comprueba antes de volver a publicar" de un resultado incierto se calcula sobre
  los intentos del mismo medio y cuenta; desaparece al borrar esos Posts.
- Los identificadores numéricos pueden reutilizarse tras borrar el registro más reciente; los
  archivos de un proyecto viven bajo un directorio con su identificador.
- Library ya tiene deep links por Media dentro del proyecto.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Borrar un Post (Priority: P1)

Como usuario quiero borrar cualquier Post (draft, scheduled, failed, missed, cancelled,
awaiting action, needs review o published) con una única confirmación, y tener la certeza de
que un Post programado borrado nunca se publicará.

**Why this priority**: Es el borrado más frecuente y el de mayor riesgo (un Post programado
que se publica tras "borrarlo" es el peor fallo posible). Es independiente del resto.

**Independent Test**: Crear un Post programado con publicación automática, borrarlo, reiniciar
la aplicación y avanzar el reloj más allá de su hora: no existe, no aparece en Posts,
Calendar ni Home y no se ha creado ningún intento.

**Acceptance Scenarios**:

1. **Given** un Post draft, **When** pulso Delete y confirmo, **Then** desaparece de Posts,
   Calendar, Home y de los indicadores de uso del Media.
2. **Given** un Post "Scheduled · automatic", **When** lo borro, **Then** la confirmación dice
   que no se publicará y, tras confirmar, ni el scheduler ni un reinicio pueden ejecutarlo.
3. **Given** un Post Published, **When** pulso Delete, **Then** la confirmación explica en una
   frase que solo se elimina de AutoPublisher y el contenido publicado no se ve afectado; tras
   confirmar desaparece de History y el contenido remoto no se toca.
4. **Given** un Post en "Publishing", **When** lo intento borrar, **Then** la acción no está
   disponible o se rechaza con "This post is being published right now. Try again when it
   finishes.", y el Post sigue intacto.
5. **Given** un Post "Needs review" (resultado incierto), **When** lo borro, **Then** la
   confirmación advierte que pudo haberse publicado y que conviene comprobarlo en la
   plataforma antes de volver a publicar ese medio.
6. **Given** que el scheduler y el borrado compiten por el mismo Post programado, **When**
   ambos ocurren a la vez, **Then** gana exactamente uno: o el Post se borra y nunca se
   ejecuta, o la ejecución empieza y el borrado se rechaza como "in progress"; nunca ambos.

---

### User Story 2 - Borrar Media de Library y liberar espacio (Priority: P1)

Como usuario quiero borrar imágenes y vídeos que ya no necesito, con una confirmación que me
diga brevemente qué Posts desaparecerán con ellos, y recuperar realmente el espacio en disco.

**Why this priority**: Library crece sin límite con uso real; sin borrado el disco se llena.

**Independent Test**: Subir un vídeo, aplicarle Remove metadata, crear con él un draft y un
Post publicado, borrar el vídeo y comprobar que ni el vídeo ni ninguno de los dos Posts
aparecen en ninguna vista, y que el original y la copia limpia ya no existen en disco.

**Acceptance Scenarios**:

1. **Given** un Media sin uso, **When** lo borro y confirmo, **Then** desaparece de Library y
   se eliminan su original y su copia limpia.
2. **Given** un Media usado por 2 Posts no publicados y 1 Post publicado, **When** pulso
   Delete, **Then** la confirmación dice "2 unpublished posts and 1 published post will also be
   removed from AutoPublisher. Content already published on platforms is not affected." y,
   tras confirmar, el Media y los 3 Posts desaparecen de todas las vistas y nada se publica.
3. **Given** un Media con un Post en "Publishing" o con Remove metadata en curso, **When** lo
   intento borrar, **Then** se rechaza con un mensaje humano y no cambia nada.
4. **Given** un Media borrado, **When** vuelvo a subir el mismo archivo, **Then** se acepta
   como Media nuevo (no se considera duplicado).

---

### User Story 3 - Organizar Library en carpetas (Priority: P2)

Como usuario quiero crear carpetas (y subcarpetas) en Library, entrar en ellas con un
breadcrumb y ver ahí solo su contenido, de forma que organizar cientos de medios reduzca
realmente lo que veo en cada vista.

**Why this priority**: Necesario antes del uso intensivo, pero no bloquea la seguridad.

**Independent Test**: Crear "Cybersecurity" y dentro "DDoS" y "2FA"; comprobar que la raíz de
Library muestra Cybersecurity, Unsorted y All media sin cuadrícula de medios; entrar en
Cybersecurity, ver las dos subcarpetas y el breadcrumb `Library / Cybersecurity`, renombrar
"2FA" a "MFA" y comprobar que persiste tras recargar.

**Acceptance Scenarios**:

1. **Given** un proyecto con o sin carpetas, **When** abro Library, **Then** veo las carpetas
   de primer nivel que existan, la entrada "Unsorted", la entrada "All media" y New folder,
   y ningún medio suelto.
2. **Given** que estoy dentro de "Cybersecurity", **When** creo una carpeta, **Then** se crea
   como subcarpeta de Cybersecurity.
3. **Given** una carpeta hermana "Lux", **When** intento crear o renombrar otra a "lux",
   **Then** se rechaza con "A folder with this name already exists here.".
4. **Given** una carpeta, **When** entro en ella, **Then** veo un breadcrumb clicable, sus
   subcarpetas y solo los medios asignados directamente a ella.
5. **Given** Unsorted, **When** entro, **Then** veo solo los medios sin carpeta.
6. **Given** All media, **When** entro, **Then** veo todos los medios del proyecto con la
   búsqueda y los filtros actuales.
7. **Given** que estoy dentro de una carpeta, **When** subo un medio, **Then** queda en esa
   carpeta; subido desde Unsorted, All media o la raíz, queda en Unsorted.
8. **Given** el enlace de una carpeta, de Unsorted o de All media, **When** lo abro en otra
   pestaña o en el móvil, **Then** se muestra esa vista; si la carpeta ya no existe, se
   muestra "not found" con vuelta a Library.

---

### User Story 4 - Mover Media entre carpetas (Priority: P2)

Como usuario quiero mover uno o varios medios a una carpeta o sacarlos a Unsorted.

**Why this priority**: Las carpetas no sirven sin poder colocar el contenido existente.

**Independent Test**: Seleccionar 3 medios en Unsorted, Move → "Lux"; comprobar que salen de
Unsorted y aparecen en Lux; mover uno a Unsorted y comprobar su ubicación.

**Acceptance Scenarios**:

1. **Given** el detalle de un Media, **When** pulso Move y elijo una carpeta en el selector,
   **Then** el Media pasa a esa carpeta y el detalle muestra su ubicación.
2. **Given** el modo Select de una vista de medios (carpeta, Unsorted o All media), **When**
   marco varios medios y pulso Move, **Then** todos se mueven en una sola operación o ninguno.
3. **Given** el selector de destino, **When** lo abro, **Then** muestra el árbol de carpetas
   y "Unsorted" como destino válido.
4. **Given** que muevo medios, **When** termina, **Then** ningún archivo cambia de lugar en
   disco y los Posts que los usan no se ven afectados.

---

### User Story 5 - Borrar una carpeta sin perder Media (Priority: P2)

Como usuario quiero borrar una carpeta sabiendo que sus medios no se borran.

**Why this priority**: Borrar accidentalmente decenas de medios sería irreversible salvo
backup.

**Independent Test**: Carpeta "Cybersecurity" con 5 medios y subcarpeta "DDoS" con 3; borrarla;
los 8 medios están en Unsorted y ningún archivo ha desaparecido.

**Acceptance Scenarios**:

1. **Given** una carpeta vacía, **When** la borro, **Then** basta una confirmación simple.
2. **Given** una carpeta con medios y subcarpetas, **When** pulso Delete, **Then** la
   confirmación dice, por ejemplo, "1 subfolder will also be removed. 8 media items will move
   to Unsorted. No media is deleted." y, tras confirmar, así ocurre.
3. **Given** que estoy viendo una subcarpeta de la carpeta borrada (otra pestaña), **When**
   recargo, **Then** veo "not found" con vuelta a Library.

---

### User Story 6 - Borrar una Account (Priority: P2)

Como usuario quiero eliminar una cuenta de un proyecto sin afectar a la cuenta real de la
plataforma y sin dejar restos de ella en AutoPublisher.

**Why this priority**: Necesario para mantenimiento, menos frecuente que Posts y Media.

**Independent Test**: Cuenta conectada con 1 draft, 1 programado y 2 publicados; borrarla;
ninguno de los 4 Posts ni la cuenta aparecen en ninguna vista; la credencial ya no está en el
almacenamiento seguro; los Posts publicados siguen en la plataforma.

**Acceptance Scenarios**:

1. **Given** una cuenta conectada, **When** pulso Delete account, **Then** la confirmación
   resume "2 unpublished posts and 2 published posts will also be removed from AutoPublisher.
   Content already published on platforms is not affected. Your @handle account on YouTube is
   not affected."
2. **Given** que confirmo, **Then** la cuenta y todos sus Posts desaparecen de Accounts,
   Posts, Calendar, Home, presets de distribución y Publish; su conexión y su credencial local
   se eliminan.
3. **Given** un Post de esa cuenta en "Publishing", **When** intento borrarla, **Then** se
   rechaza con "A post of this account is being published right now. Try again when it
   finishes." y nada cambia.
4. **Given** una conexión en curso (OAuth, login de Telegram u otro paso de conexión) para la
   cuenta, **When** la borro, **Then** el borrado continúa y se completa, el intento en curso
   queda invalidado y no puede completar ni recrear la conexión después.
5. **Given** que el almacenamiento seguro no está disponible al borrar, **Then** el borrado
   local se completa igualmente y la credencial pendiente se elimina automáticamente más
   tarde; nunca vuelve a usarse.

---

### User Story 7 - Borrar un Project (Priority: P3)

Como usuario quiero borrar un proyecto completo con una confirmación informativa.

**Why this priority**: Menos frecuente; la desactivación ya cubre parte de la necesidad.

**Independent Test**: Proyecto con 3 cuentas, 12 Posts y 24 medios; borrarlo; desaparece de la
app, sus archivos y credenciales no existen, el resto de proyectos no cambia, y un proyecto
nuevo creado después no hereda nada.

**Acceptance Scenarios**:

1. **Given** un proyecto con contenido, **When** pulso Delete project, **Then** la confirmación
   dice "This project contains 3 accounts, 12 posts and 24 media items. Everything will be
   removed from AutoPublisher. Content already published on platforms is not affected." con
   Delete y Cancel.
2. **Given** un proyecto vacío, **Then** la confirmación es simple.
3. **Given** que confirmo, **Then** desaparecen sus cuentas, conexiones, credenciales locales,
   Posts, Media y archivos, carpetas y presets, y vuelvo a Home.
4. **Given** un Post del proyecto en "Publishing" o un Media en Remove metadata, **When** lo
   intento borrar, **Then** se rechaza con un mensaje humano y nada cambia.
5. **Given** que borro el último proyecto, **Then** veo el estado vacío de onboarding.

---

### Edge Cases

- **Delete vs scheduler tick**: el borrado y el inicio automático de un Post son exclusivos;
  si el Post ya pasó a Publishing, el borrado (de Post, Media, Account o Project) se rechaza
  como "in progress". Si el borrado se confirma primero, ningún tick posterior ni reinicio lo
  encuentra.
- **Publicación ya enviada remotamente**: nunca se cancela; se espera a que termine o se
  reconcilie y después puede borrarse.
- **Awaiting user action** (p. ej. TikTok Inbox): puede borrarse; cualquier seguimiento
  automático de ese Post se detiene y no recrea nada.
- **Recuperación tras reinicio** de un intento interrumpido: nunca resucita un Post borrado.
- **Borrar Posts Needs review** (directamente o con su Media/Account) elimina también el aviso
  de comprobación para ese medio y cuenta; la confirmación lo advierte.
- **Conexión en curso al borrar una Account**: nunca bloquea; el intento se invalida y su
  resultado tardío se descarta sin crear conexión, credencial ni cuenta.
- **Doble clic / doble petición / otra pestaña**: un segundo borrado del mismo objeto responde
  "not found" y la UI lo trata como ya borrado, sin error visible.
- **Deep links a objetos borrados** (Post, Media, carpeta, cuenta, proyecto): muestran "not
  found" y nunca abren otro objeto; los identificadores de objetos borrados no se reutilizan.
- **Proyecto nuevo tras borrar uno**: nunca hereda archivos, carpetas ni datos del borrado.
- **Fallo al eliminar un archivo físico** tras el borrado: el borrado se mantiene, el archivo
  se elimina automáticamente más tarde y nunca se elimina un archivo aún referenciado.
- **Crash a mitad de borrado**: el estado local queda o bien como antes o bien borrado del
  todo; nunca a medias en la base de datos.
- **Objetos temporales de entrega** de intentos de Posts borrados: siguen limpiándose; no
  quedan objetos remotos temporales abandonados.
- **Media duplicado tras borrado**: puede volver a subirse.
- **Presets** que se quedan sin cuentas al borrar una Account: se conservan vacíos y Publish
  los trata como cualquier preset sin destinos disponibles.
- **Media movido mientras se publica**: permitido; mover no afecta a la publicación.
- **Carpeta de otro proyecto** (mover, abrir o borrar): se rechaza como "not found".
- **Profundidad de carpetas**: máximo 5 niveles; crear más profundo se rechaza con mensaje
  claro.
- **Restaurar un backup anterior a 021**: funciona; todos los medios quedan en Unsorted.
- **Restaurar un backup posterior a un borrado**: devuelve el estado del backup (mecanismo de
  recuperación); las credenciales borradas no se restauran y las cuentas afectadas aparecen
  como "Reconnect required", igual que en 020.
- **Móvil**: los diálogos de confirmación, el selector de carpetas y las entradas de la raíz
  de Library son usables a ancho de teléfono y con táctil; Select/Move funciona sin gestos
  ocultos.

## Requirements *(mandatory)*

### Functional Requirements

#### General

- **FR-001**: Borrar en AutoPublisher DEBE significar borrar estado local de AutoPublisher.
  Ningún borrado DEBE contactar con una plataforma ni borrar contenido remoto o la cuenta real.
- **FR-002**: Toda acción Delete DEBE requerir exactamente una confirmación (Delete / Cancel)
  sin escribir nombres, códigos ni pantallas o pasos de confirmación adicionales. Abrir antes
  un menú de acciones para llegar a Delete está permitido. La confirmación DEBE resumir en
  lenguaje humano las consecuencias relevantes (cuántos Posts no publicados y publicados
  desaparecen, que el contenido en plataformas no se ve afectado) y omitirlas cuando no
  existan.
- **FR-003**: El resumen de consecuencias DEBE obtenerse del backend antes de confirmar y DEBE
  coincidir con lo que el borrado hará. Si entre resumen y confirmación el estado cambió de
  forma que se borraría algo no anunciado, el backend DEBE rechazar el borrado pidiendo
  revisarlo de nuevo.
- **FR-004**: Cada borrado DEBE ser atómico respecto al estado local: o se aplica completo o
  no cambia nada.
- **FR-005**: Tras un borrado, el objeto y todos los objetos visibles que dependen de él NO
  DEBEN aparecer en ninguna vista, búsqueda, filtro, contador, indicador de uso ni read-model
  (Home, Posts, History, Calendar, Library, Accounts, Publish). No se DEBEN conservar como
  objetos marcados como borrados ni como registros visibles derivados.
- **FR-006**: Ningún borrado DEBE dejar referencias rotas ni trabajo programado capaz de
  ejecutarse.
- **FR-007**: Los únicos estados ocupados que bloquean un borrado (busy-state blockers) DEBEN
  ser: un Post afectado está en Publishing, o un Media afectado tiene Remove metadata en curso.
  Además, un borrado PUEDE rechazarse con `deletion_changed` cuando las consecuencias
  confirmadas quedaron obsoletas entre el resumen y la confirmación (FR-003). Una conexión
  OAuth, un login u otro intento de conexión en curso NO es un bloqueo (FR-028). Todo rechazo
  DEBE llevar un mensaje humano y no cambiar nada. Un borrado confirmado y el inicio de una
  ejecución DEBEN ser mutuamente excluyentes.
- **FR-008**: Los identificadores de objetos borrados NO DEBEN reutilizarse para objetos
  nuevos.
- **FR-009**: Las acciones Delete DEBEN ser visibles pero no dominantes (zona secundaria o menú
  del objeto, estilo de acción destructiva).
- **FR-010**: Tras borrar el objeto que se está viendo, la UI DEBE navegar a su contenedor
  (Post → Posts, Media → la vista de Library de la que venía, Account → Accounts, Project →
  Home) y mostrar una notificación breve.
- **FR-011**: No se DEBE introducir Trash, papelera ni soft-delete; la recuperación es el
  backup de Feature 020.
- **FR-012**: No se introduce registro de auditoría en esta feature. Los logs existentes
  PUEDEN registrar que ocurrió un borrado (tipo, identificador y cantidades), sin datos
  sensibles, y nunca se muestran en la UI.

#### Posts

- **FR-013**: Se DEBE poder borrar un Post en cualquier estado salvo Publishing.
- **FR-014**: Borrar un Post DEBE eliminar el Post y todo su historial local (intentos,
  opciones de plataforma, registros de ejecución). El contenido remoto no se toca.
- **FR-015**: Para Posts Published o Awaiting user action, la confirmación DEBE indicar que el
  contenido en la plataforma no se ve afectado. Para Posts Needs review, DEBE advertir que
  pudo haberse publicado.
- **FR-016**: Un Post borrado NO DEBE ejecutarse nunca, ni tras reinicio ni por recuperación
  de intentos interrumpidos; ningún seguimiento automático de un Post borrado DEBE continuar.
- **FR-017**: Los objetos temporales de entrega asociados a intentos de Posts borrados DEBEN
  seguir limpiándose por el mecanismo existente.

#### Media

- **FR-018**: Se DEBE poder borrar un Media salvo mientras un Post que lo usa esté en
  Publishing o se esté ejecutando Remove metadata sobre él.
- **FR-019**: Borrar un Media DEBE borrar también **todos** los Posts que lo usan, en
  cualquier estado (Draft, Scheduled, Missed, Failed, Needs review, Cancelled, Awaiting user
  action, Published), con la semántica de FR-014 y FR-016.
- **FR-020**: La confirmación DEBE contar por separado los Posts no publicados y los Posts que
  pueden existir en plataformas (Published, Awaiting user action, Needs review), indicando que
  todos desaparecerán de AutoPublisher y que el contenido ya publicado no se ve afectado.
- **FR-021**: Tras borrar un Media DEBEN eliminarse del disco su original y su copia limpia.
- **FR-022**: Si un archivo no puede eliminarse en el momento, el borrado DEBE mantenerse y el
  archivo DEBE eliminarse automáticamente más tarde (como muy tarde en el siguiente arranque).
  Solo se eliminan archivos que ningún Media existente referencia.
- **FR-023**: Tras borrar un Media, volver a subir el mismo archivo DEBE aceptarse como nuevo.
- **FR-024**: El borrado de Media es individual, desde su detalle o su card. No se incluye
  borrado múltiple.

#### Accounts

- **FR-025**: Se DEBE poder borrar cualquier Account (conectada, desconectada, que requiere
  reconexión, inactiva o provisional) salvo mientras uno de sus Posts esté en Publishing. El
  descarte actual de cuentas provisionales queda subsumido sin cambiar su resultado.
- **FR-026**: Borrar una Account DEBE borrar también **todos** sus Posts, en cualquier estado,
  con la semántica de FR-014 y FR-016, y la confirmación DEBE contarlos como en FR-020.
- **FR-027**: Borrar una Account DEBE eliminar su conexión de plataforma y su pertenencia a
  presets.
- **FR-028**: Un intento de conexión en curso (OAuth, login de Telegram o cualquier otro paso
  de conexión) NO DEBE impedir el borrado: el intento DEBE invalidarse y su resultado tardío
  DEBE descartarse sin crear conexión, credencial ni cuenta. Si un paso está a mitad de
  ejecución, el borrado PUEDE esperar a que termine ese paso, pero NO DEBE rechazarse por ello.
- **FR-029**: La credencial local de la conexión DEBE eliminarse del almacenamiento seguro.
  Como cada conexión tiene una referencia propia no compartida, esto no afecta a ninguna otra
  cuenta ni proyecto. Si el almacenamiento seguro no está disponible, el borrado DEBE
  completarse y la referencia DEBE quedar registrada para eliminarse automáticamente más
  tarde; nunca se vuelve a usar.
- **FR-030**: Borrar una Account NO DEBE revocar autorizaciones en la plataforma (sin
  contacto remoto). La confirmación DEBE indicar que la cuenta real no se ve afectada.

#### Projects

- **FR-031**: Se DEBE poder borrar un Project, activo o inactivo, salvo mientras alguno de sus
  Posts esté en Publishing o algún Media esté en Remove metadata. Las conexiones en curso de
  sus cuentas se tratan como en FR-028.
- **FR-032**: Borrar un Project DEBE eliminar todo su estado local: cuentas, conexiones y sus
  credenciales locales (regla de FR-029), Posts e historial, Media y sus archivos, carpetas y
  presets.
- **FR-033**: Con contenido, la confirmación DEBE indicar cuántas cuentas, Posts y medios
  contiene y que el contenido publicado en plataformas no se ve afectado; vacío, la
  confirmación es simple. La configuración global (plataformas, automatización, instalación)
  no se toca.

#### Carpetas

- **FR-034**: Cada Project DEBE tener su propio árbol de carpetas de Library. Una carpeta
  tiene nombre y carpeta padre opcional del mismo proyecto; un Media está como mucho en una
  carpeta.
- **FR-035**: Las carpetas son organización lógica: crear, renombrar o borrar carpetas y mover
  Media NO DEBE mover, renombrar ni copiar archivos en disco.
- **FR-036**: El usuario DEBE poder crear carpetas en la raíz o dentro de otra carpeta (máximo
  5 niveles), renombrarlas y borrarlas. No se incluye mover carpetas en esta versión.
- **FR-037**: Los nombres DEBEN tener entre 1 y 100 caracteres tras recortar espacios y ser
  únicos entre hermanas sin distinguir mayúsculas. "Unsorted" y "All media" no son carpetas y
  no colisionan con nombres de usuario.
- **FR-038**: Borrar una carpeta DEBE eliminar también sus subcarpetas y mover todos los medios
  de la carpeta y sus subcarpetas a Unsorted. Nunca borra Media ni Posts. La confirmación DEBE
  indicar cuántas subcarpetas se eliminan y cuántos medios pasan a Unsorted cuando no sean
  cero.

#### Navegación de Library

- **FR-039**: **Library root** DEBE mostrar siempre la misma estructura: las carpetas de
  primer nivel (si existen), la entrada **Unsorted** y la entrada **All media**, cada una con
  su número de medios, y la acción New folder. No DEBE mostrar una cuadrícula de medios,
  tampoco cuando el proyecto no tiene carpetas.
- **FR-040**: **Folder** DEBE mostrar un breadcrumb clicable (`Library / … / carpeta`), sus
  subcarpetas y solo los medios asignados directamente a ella. Búsqueda y filtros se aplican a
  esos medios.
- **FR-041**: **Unsorted** DEBE mostrar solo los medios sin carpeta, con breadcrumb
  `Library / Unsorted`; búsqueda y filtros se aplican a esos medios.
- **FR-042**: **All media** DEBE mostrar todos los medios del proyecto con la búsqueda y los
  filtros globales actuales, con breadcrumb `Library / All media`. Cada medio DEBE indicar su
  carpeta.
- **FR-043**: Cada vista DEBE tener una URL propia, coherente con las rutas actuales del
  proyecto, que funcione como deep link, al recargar y con la navegación atrás del navegador:
  Library root, cada carpeta (por su identificador), Unsorted y All media. El deep link
  existente de cada Media DEBE seguir funcionando.
- **FR-044**: Subir un medio dentro de una carpeta DEBE colocarlo en esa carpeta; desde la
  raíz, Unsorted o All media, en Unsorted.
- **FR-045**: El detalle del Media DEBE mostrar su carpeta y ofrecer Move y Delete.
- **FR-046**: Los empty states de onboarding de Library DEBEN seguir guiando la primera subida
  aunque el proyecto no tenga carpetas.

#### Mover Media

- **FR-047**: El usuario DEBE poder mover un Media desde su detalle y varios desde un modo
  Select de cualquier vista de medios (carpeta, Unsorted, All media), cuya única acción es
  Move.
- **FR-048**: El selector de destino DEBE mostrar el árbol de carpetas del proyecto y Unsorted.
- **FR-049**: Mover varios medios DEBE ser una única operación atómica; no se permite mover a
  una carpeta de otro proyecto.

#### Contrato observable de la API

El usuario pidió explícitamente definir este contrato; los nombres exactos se fijan en el plan.

- **FR-050**: Bajo `/api` DEBEN existir operaciones DELETE para Project, Account, Post, Media y
  carpeta; operaciones para crear, renombrar y listar carpetas de un proyecto; listar medios
  por carpeta, Unsorted o todos; una operación para mover uno o varios Media a una carpeta o a
  Unsorted; y una operación de solo lectura que devuelva el resumen de consecuencias de borrar
  un Project, Account, Post, Media o carpeta.
- **FR-051**: Códigos de estado: borrado correcto → 204; objeto inexistente o de otro proyecto
  → 404 (un borrado repetido devuelve 404 y la UI lo trata como ya borrado); bloqueo de FR-007
  (Post afectado en Publishing o Media en Remove metadata) → 409; consecuencias distintas de
  las anunciadas (FR-003) → 409; validación de nombres o profundidad → 422 o 409 según la
  convención existente. Una conexión en curso NUNCA produce 409.
- **FR-052**: Los errores DEBEN usar el formato de error existente con códigos estables y
  mensajes humanos: `post_in_progress`, `metadata_removal_in_progress`, `deletion_changed`,
  `folder_name_taken`, `folder_too_deep`. No existe `account_busy` por conexión en curso.
  NUNCA se devuelven errores de integridad de la base de datos ni detalles técnicos.
- **FR-053**: Todas las operaciones nuevas DEBEN exigir la sesión de instalación y las mismas
  comprobaciones de Host y Origin que el resto de la API privada. No se añaden rutas públicas.

#### Backups

- **FR-054**: Carpetas y ubicación de cada Media DEBEN vivir en la base de datos local y formar
  parte del backup sin cambios en su formato; no se crea almacenamiento fuera del árbol
  portable de datos.
- **FR-055**: Restaurar un backup creado antes de esta feature DEBE funcionar dejando todo el
  Media en Unsorted.

#### Móvil

- **FR-056**: Delete, confirmaciones, Library root, navegación de carpetas, breadcrumb, Select
  y Move DEBEN funcionar desde móvil en LAN con táctil y a ancho de teléfono, sin auditoría
  responsive general.

### Key Entities *(include if feature involves data)*

- **Library Folder** (nuevo): carpeta lógica de un Project; nombre y carpeta padre opcional
  del mismo proyecto. Se borra con su proyecto; al borrarla sus subcarpetas se borran y su
  Media queda sin carpeta.
- **Media (Content)**: gana una carpeta opcional (sin carpeta = Unsorted). Al borrarse elimina
  sus archivos (original y copia limpia) y todos sus Posts.
- **Post (Publication)**: siempre tiene su Account y, salvo los de solo texto, su Media; nunca
  sobrevive a ellos.
- **Account**: al borrarse arrastra su conexión, credencial local, pertenencia a presets y
  todos sus Posts.
- **Project**: al borrarse arrastra todo su estado local.
- **Credencial pendiente de borrado** (interno): referencia a un secreto del almacenamiento
  seguro que ya no se usa y queda por eliminar; generaliza a todas las plataformas el patrón
  ya existente para TikTok. Nunca visible en la UI.
- **Archivo pendiente de borrado** (interno): archivo de un Media borrado que no pudo
  eliminarse aún. Nunca visible en la UI.

### Semántica de borrado por entidad (resumen)

| Se borra | Desaparece también | Bloqueado mientras |
|----------|--------------------|--------------------|
| **Post** | Sus intentos, opciones y registros de ejecución. | El Post está en Publishing. |
| **Media** | Todos sus Posts (cualquier estado) con su historial; original y copia limpia en disco. | Un Post suyo está en Publishing o Remove metadata en curso. |
| **Account** | Todos sus Posts con su historial; conexión; credencial local; pertenencia a presets; intentos de conexión en curso (invalidados). | Un Post suyo está en Publishing. |
| **Project** | Todo: cuentas, conexiones, credenciales locales, Posts e historial, Media y archivos, carpetas, presets. | Un Post suyo está en Publishing o un Media en Remove metadata. |
| **Folder** | Sus subcarpetas. Su Media y el de su subárbol pasa a Unsorted (nunca se borra). | Nunca. |

Además de estos bloqueos, cualquier borrado puede rechazarse con `deletion_changed` si sus
consecuencias cambiaron tras el resumen (FR-003). En ningún caso se borra contenido remoto ni
la cuenta real de la plataforma. Los objetos temporales de entrega siguen su limpieza propia.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Borrar cualquier Post, Media, Account, carpeta o Project requiere una acción
  Delete y exactamente una confirmación, sin pasos de confirmación adicionales, escribir
  nombres ni códigos, desde escritorio y desde móvil (puede haber una interacción previa para
  abrir un menú de acciones).
- **SC-002**: En el 100 % de las pruebas de concurrencia borrado/scheduler, un Post programado
  borrado nunca obtiene un intento de ejecución, ni tras reinicio.
- **SC-003**: Tras borrar un Media, el espacio libre del disco aumenta en el tamaño de su
  original más su copia limpia, y tras el siguiente arranque no queda ningún archivo de Media
  borrados.
- **SC-004**: Tras cualquier borrado no existe ningún Post, conexión, preset o carpeta que
  apunte a un objeto inexistente, y ninguna vista de la app muestra un error por ello.
- **SC-005**: Tras borrar un Media, Account o Project, el 100 % de sus Posts dependientes
  (incluidos los publicados) están ausentes de Posts, History, Calendar, Home, búsquedas,
  filtros y contadores.
- **SC-006**: Borrar una carpeta con N medios en su subárbol deja exactamente N medios más en
  Unsorted y 0 medios borrados.
- **SC-007**: Mover 20 medios a una carpeta es una única acción y ningún archivo cambia de
  ubicación en disco.
- **SC-008**: En una Library de 500 medios organizados en carpetas, la raíz no muestra ningún
  medio suelto y el usuario encuentra un medio concreto en menos de 30 segundos (navegando
  carpetas o con All media).
- **SC-009**: Un backup creado tras organizar carpetas y borrar objetos se restaura con las
  mismas carpetas y ubicaciones, sin reaparecer objetos borrados antes del backup.
- **SC-010**: Ninguna credencial local de una Account o Project borrados permanece en el
  almacenamiento seguro después del siguiente arranque con almacenamiento disponible.
- **SC-011**: Borrar una Account con una conexión en curso se completa en el 100 % de los
  casos y nunca reaparece una conexión para ella.

## Assumptions

- Post equivale a Publication; no se introduce entidad de lote.
- "Missed" es un Post programado cuya hora pasó sin ejecutarse.
- Las carpetas son por proyecto, igual que Library.
- No se permite mover carpetas (evita ciclos y complejidad); se puede renombrar y borrar.
- Profundidad máxima de 5 niveles para mantener el breadcrumb usable en móvil.
- No se incluye borrado múltiple de Media ni de Posts; el modo Select solo mueve.
- La desactivación existente de Projects y Accounts se mantiene sin cambios.
- No hay miniaturas ni derivados en disco hoy; si aparecieran, pertenecerían al Media y se
  borrarían con él.
- Backup/restore de 020 se reutiliza tal cual: la base de datos y el directorio de medios ya
  forman el estado portable.

## Out of Scope

Internet público, almacenamiento cloud, Trash/papelera o soft-delete, registro o interfaz de
auditoría, historial visible de objetos borrados, tags, smart folders, organización por IA o
automática, detección de duplicados, borrado del contenido en la plataforma, revocación remota
de autorizaciones al borrar, framework de borrado masivo, mover carpetas, rediseño general de
Library, Raspberry Pi y validación de sleep/lid-close.

## Decisiones

Confirmadas por el usuario (2026-10-24):

- **D1/D2 — Delete = gone**: borrar Post, Media, Account o Project elimina del producto todos
  los Posts dependientes en cualquier estado, sin historial visible; el contenido remoto no se
  toca.
- **D3**: borrar carpeta elimina su subárbol de carpetas y mueve su Media a Unsorted.
- **D4**: borrar Account/Project elimina la credencial local sin revocarla en la plataforma,
  con limpieza diferida si el almacenamiento seguro no está disponible.
- **D5**: Library root = carpetas de primer nivel + Unsorted + All media, sin cuadrícula.
- **D6**: modo Select solo para Move.
- **D7**: carpetas anidadas hasta 5 niveles, sin mover carpetas.
- **D8**: una conexión en curso nunca bloquea borrar una Account; se invalida.
- **D9**: Library root mantiene siempre la misma estructura (Unsorted, All media, New folder
  y las carpetas que existan), también sin carpetas de usuario: navegación consistente,
  Library no cambia de semántica al crear la primera carpeta y Unsorted deja claro qué falta
  por organizar.

No quedan decisiones pendientes.
