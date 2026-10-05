# Feature Specification: Biblioteca de contenido e importación local de imágenes y vídeos

**Feature Branch**: `003-content-library`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Crear la Feature 003 de AutoPublisher: biblioteca de contenido e importación local de imágenes y vídeos. Permitir importar contenido multimedia dentro de un proyecto (selección de archivos y drag & drop, múltiples archivos a la vez), copiarlo al almacenamiento local de AutoPublisher sin modificar el original, detectar duplicados por checksum dentro del mismo proyecto, editar título, descripción y hashtags, y consultarlo en una biblioteca por proyecto con persistencia local. Sin Publication, scheduler, APIs sociales, conversión de formatos ni eliminación física."

## Contexto

Esta feature introduce el concepto de **Contenido** (`Content`): una pieza multimedia
(imagen o vídeo) importada dentro de un proyecto y gestionada por AutoPublisher como un
recurso reutilizable. En features futuras, un mismo contenido podrá programarse y publicarse
en varias cuentas del proyecto sin duplicar el archivo.

Se apoya en los proyectos de la Feature 002. Todavía **no** existen publicaciones,
programaciones ni conexión con redes sociales: importar contenido no lo publica ni lo
programa. Conceptualmente, todo contenido importado en esta feature está "sin programar"
(`UNSCHEDULED`), sin que sea necesario modelar todavía ese estado.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Importar imágenes y vídeos a un proyecto (Priority: P1)

Como usuario, quiero abrir un proyecto e importar en él una imagen o un vídeo desde mi equipo
(seleccionándolo o arrastrándolo), para que AutoPublisher guarde su propia copia y el
contenido quede disponible en el proyecto aunque después mueva o borre el archivo original.

**Why this priority**: importar y conservar el archivo es la base de toda la feature y de las
futuras publicaciones; sin ello no hay biblioteca.

**Independent Test**: abrir el proyecto "L4i4", importar una imagen y un vídeo, comprobar que
aparecen en el proyecto, borrar o mover los originales del equipo, reiniciar la aplicación y
comprobar que ambos contenidos siguen disponibles y visibles.

**Acceptance Scenarios**:

1. **Given** un proyecto activo, **When** el usuario selecciona una imagen de un formato
   soportado, **Then** se crea un contenido de tipo imagen asociado a ese proyecto, con su
   nombre original, tamaño, checksum, fechas y, cuando sea posible, anchura y altura.
2. **Given** un proyecto activo, **When** el usuario arrastra un vídeo de un formato soportado
   sobre la zona de importación, **Then** se crea un contenido de tipo vídeo asociado a ese
   proyecto, con sus datos básicos y, cuando sea posible, anchura, altura y duración.
3. **Given** un contenido recién importado, **When** el usuario mueve, renombra o elimina el
   archivo original de su equipo, **Then** el contenido sigue disponible y su preview sigue
   funcionando.
4. **Given** un archivo importado, **When** se compara el archivo original del usuario antes y
   después de la importación, **Then** es idéntico y sigue en el mismo lugar.
5. **Given** un archivo con un formato no soportado (p. ej. un documento de texto), **When**
   el usuario intenta importarlo, **Then** se rechaza con un mensaje comprensible y no se
   crea contenido ni se guarda ninguna copia.
6. **Given** un archivo vacío (0 bytes) o cuyo contenido no corresponde a una imagen o vídeo
   válido de formato soportado, **When** el usuario intenta importarlo, **Then** se rechaza
   con un mensaje comprensible.
7. **Given** cualquier intento de importar contenido en un proyecto inexistente, **When** se
   envía la petición, **Then** se rechaza indicando que el proyecto no existe y no se crea
   contenido ni se guarda ningún archivo.
8. **Given** un contenido importado, **When** se reinicia la aplicación, **Then** el registro,
   su asociación con el proyecto y el archivo copiado siguen disponibles.

---

### User Story 2 - Importación masiva con resultado por archivo (Priority: P1)

Como usuario, quiero seleccionar o arrastrar muchos archivos a la vez (p. ej. 20 imágenes y
vídeos de L4i4 o 30 vídeos de Cybersecurity) y ver claramente cuáles se importaron, cuáles se
rechazaron y cuáles ya existían, para cargar mi contenido de una sola vez sin perder los
archivos válidos cuando alguno falla.

**Why this priority**: el caso de uso real es cargar lotes grandes; importar de uno en uno no
es viable en la práctica.

**Independent Test**: arrastrar en una sola operación un lote con imágenes y vídeos válidos,
un archivo de formato no soportado, un archivo vacío y un archivo ya importado en el proyecto;
comprobar que todos los válidos se importan y que el resultado distingue importados,
rechazados (con motivo) y duplicados.

**Acceptance Scenarios**:

1. **Given** un proyecto activo, **When** el usuario selecciona varios archivos en una única
   operación del selector de archivos, **Then** todos los archivos válidos se importan.
2. **Given** un proyecto activo, **When** el usuario arrastra varios archivos a la vez sobre
   la zona de importación, **Then** todos los archivos válidos se importan.
3. **Given** un lote que mezcla archivos válidos, archivos de formato no soportado y archivos
   vacíos, **When** se importa, **Then** los válidos se importan correctamente y los demás se
   rechazan individualmente sin afectar a los válidos.
4. **Given** una importación de un lote finalizada, **When** el usuario consulta el
   resultado, **Then** ve para cada archivo, identificado por su nombre original, si se
   importó, si se rechazó (con el motivo) o si era un duplicado.
5. **Given** una importación en curso, **When** todavía no ha terminado, **Then** la interfaz
   indica que está en progreso y no permite lanzar involuntariamente la misma importación dos
   veces.
6. **Given** un lote que contiene dos veces exactamente el mismo archivo, **When** se importa,
   **Then** solo se crea un contenido y el segundo se informa como duplicado.

---

### User Story 3 - Detección de duplicados (Priority: P1)

Como usuario, quiero que AutoPublisher detecte si intento importar exactamente el mismo
archivo que ya existe en el proyecto y me avise, para no acumular copias silenciosas del mismo
contenido.

**Why this priority**: es un requisito explícito del flujo principal y evita duplicados que
más adelante provocarían publicaciones repetidas.

**Independent Test**: importar un archivo en "L4i4", volver a importarlo (incluso con otro
nombre de archivo), comprobar que se informa como duplicado y que el número de contenidos y
de archivos almacenados no cambia; importarlo después en "Cybersecurity" y comprobar que sí
se crea allí.

**Acceptance Scenarios**:

1. **Given** un proyecto con un contenido importado, **When** el usuario importa de nuevo
   exactamente el mismo archivo, **Then** se informa claramente de que ya existe en el
   proyecto, indicando cuál es el contenido existente, y no se crea ningún contenido nuevo ni
   ninguna copia nueva del archivo.
2. **Given** un contenido importado, **When** el usuario importa el mismo archivo renombrado,
   **Then** se detecta igualmente como duplicado (la detección se basa en el contenido del
   archivo, no en su nombre).
3. **Given** un archivo importado en "L4i4", **When** el usuario lo importa en
   "Cybersecurity", **Then** se crea un contenido independiente en "Cybersecurity".
4. **Given** dos archivos distintos con el mismo nombre, **When** se importan en el mismo
   proyecto, **Then** ambos se importan como contenidos diferentes.

---

### User Story 4 - Biblioteca de contenido del proyecto (Priority: P2)

Como usuario, quiero ver dentro de cada proyecto una biblioteca con todos sus contenidos,
distinguiendo imágenes y vídeos con una preview y su información, para saber qué material
tengo disponible.

**Why this priority**: es necesaria para usar el contenido importado, pero la importación ya
aporta valor verificable por sí sola.

**Independent Test**: con un proyecto con imágenes y vídeos importados, abrir su biblioteca,
comprobar que se muestran todos, que se distingue imagen de vídeo, que hay preview, y que al
abrir un contenido se ve toda su metadata; con un proyecto sin contenido, comprobar el estado
vacío.

**Acceptance Scenarios**:

1. **Given** un proyecto sin contenido, **When** el usuario abre su biblioteca, **Then** ve
   un estado vacío que le invita a importar archivos.
2. **Given** un proyecto con contenidos, **When** el usuario abre su biblioteca, **Then** ve
   todos los contenidos de ese proyecto (y solo de ese proyecto), cada uno con su preview,
   una indicación clara de si es imagen o vídeo, su título (o el nombre original si no tiene
   título) y su fecha de importación.
3. **Given** un contenido en la biblioteca, **When** el usuario lo selecciona, **Then** ve su
   tipo, nombre original, título, descripción, hashtags, tamaño, fecha de importación, fecha
   de última modificación y, si se conocen, dimensiones y duración.
4. **Given** un vídeo en la biblioteca, **When** el usuario lo consulta, **Then** puede
   visualizarlo o, como mínimo, ver una representación reconocible como vídeo.
5. **Given** un proyecto inactivo con contenido, **When** el usuario abre su biblioteca,
   **Then** sigue pudiendo consultar su contenido.

---

### User Story 5 - Editar título, descripción y hashtags (Priority: P2)

Como usuario, quiero editar el título, la descripción y los hashtags de un contenido ya
importado, para preparar la información que usarán sus futuras publicaciones.

**Why this priority**: es la metadata que alimentará las publicaciones futuras, pero se puede
añadir después de importar.

**Independent Test**: editar título, descripción y hashtags de un contenido, reiniciar la
aplicación y comprobar que se conservan, que la fecha de última modificación cambió y que el
archivo almacenado no se ha modificado.

**Acceptance Scenarios**:

1. **Given** un contenido sin metadata, **When** el usuario añade título, descripción y
   hashtags y guarda, **Then** los cambios se guardan, se actualiza la fecha de última
   modificación y la fecha de importación no cambia.
2. **Given** un contenido con metadata, **When** el usuario vacía el título, la descripción o
   los hashtags, **Then** quedan sin valor y el contenido sigue siendo válido.
3. **Given** un contenido, **When** el usuario edita su metadata, **Then** el archivo
   almacenado (y su checksum) no cambia.
4. **Given** un contenido, **When** el usuario introduce valores que superan los límites
   permitidos o hashtags inválidos, **Then** la edición se rechaza con un mensaje comprensible
   junto al formulario y sin perder lo que había escrito.
5. **Given** un contenido editado, **When** se reinicia la aplicación, **Then** la metadata
   se conserva exactamente.
6. **Given** un contenido, **When** el usuario busca una opción para eliminarlo, **Then** no
   existe: el contenido no se puede eliminar en esta feature.

---

### Edge Cases

- **Proyecto inactivo**: importar contenido en un proyecto inactivo se rechaza con un mensaje
  que indica que el proyecto debe reactivarse primero (coherente con la regla de cuentas de la
  Feature 002). Su contenido existente sigue siendo consultable y su metadata editable.
- **Extensión engañosa**: un archivo cuya extensión indica un formato soportado pero cuyo
  contenido real no corresponde a una imagen o vídeo de formato soportado se rechaza como
  inválido.
- **Mayúsculas en la extensión**: `FOTO.JPG` y `foto.jpg` se tratan igual.
- **Archivo demasiado grande**: un archivo que supere el tamaño máximo permitido se rechaza
  indicando el límite; en un lote, solo se rechaza ese archivo.
- **Lote demasiado grande**: un lote que supere el número máximo de archivos por operación se
  rechaza con un mensaje que indica el límite, sin importar parcialmente nada de ese lote.
- **Metadata técnica no disponible**: si no se pueden obtener anchura, altura o duración de
  un archivo válido, el contenido se importa igualmente y esos datos quedan sin valor.
- **Nombre original con caracteres especiales o muy largo**: se conserva para mostrarlo al
  usuario, pero el nombre del archivo almacenado lo decide AutoPublisher y nunca depende de
  forma insegura del nombre original (no puede salir del almacenamiento de AutoPublisher ni
  sobrescribir otros archivos).
- **Mismo nombre, distinto contenido**: no es un duplicado; ambos se importan.
- **Duplicado dentro del mismo lote**: solo el primero se importa; los siguientes se informan
  como duplicados.
- **Fallo a mitad de la importación de un archivo** (p. ej. error de disco): no debe quedar un
  contenido registrado sin su archivo ni un archivo huérfano registrado como contenido; ese
  archivo se informa como fallido y el resto del lote continúa.
- **Archivo almacenado desaparecido**: si el archivo copiado falta del almacenamiento de
  AutoPublisher por una manipulación externa, la biblioteca sigue mostrando el contenido con
  una indicación de que su archivo no está disponible, en lugar de fallar por completo.
- **Hashtags**: se aceptan con o sin `#` inicial y se almacenan de forma normalizada (sin `#`,
  sin espacios exteriores); un hashtag no puede contener espacios; los repetidos dentro del
  mismo contenido (sin distinguir mayúsculas) se eliminan conservando el primero y el orden.
- **Textos con solo espacios**: un título o descripción formado solo por espacios cuenta como
  vacío.
- **Contenido inexistente**: consultar o editar un identificador que no existe devuelve un
  error claro de "no encontrado".
- **Primer arranque**: si el almacenamiento multimedia local no existe, se crea
  automáticamente.

## Requirements *(mandatory)*

### Functional Requirements

**Importación**

- **FR-001**: El sistema DEBE permitir importar uno o varios archivos multimedia en un
  proyecto existente y activo en una única operación.
- **FR-002**: El sistema DEBE aceptar únicamente un conjunto cerrado y documentado de
  formatos comunes de imagen y de vídeo (definido en `/speckit-plan`) y rechazar cualquier
  otro. La validación DEBE comprobar el contenido real del archivo, no solo su extensión.
- **FR-003**: El sistema DEBE rechazar archivos vacíos, inválidos o que superen el tamaño
  máximo por archivo, y lotes que superen el número máximo de archivos por operación. Los
  límites concretos se definen en `/speckit-plan` con valores que permitan importar vídeos
  habituales de redes sociales y lotes de al menos 50 archivos.
- **FR-004**: El sistema DEBE rechazar cualquier importación en un proyecto inexistente o
  inactivo, sin crear contenido ni guardar archivos.
- **FR-005**: El sistema DEBE procesar cada archivo de un lote de forma independiente: el
  rechazo o fallo de un archivo NO DEBE impedir la importación de los demás archivos válidos.
- **FR-006**: El resultado de una importación DEBE indicar, para cada archivo enviado e
  identificado por su nombre original, uno de estos resultados: importado (con el contenido
  creado), duplicado (con referencia al contenido existente) o rechazado (con un motivo
  comprensible).
- **FR-007**: El sistema NO DEBE crear un contenido parcialmente: o existen registro y
  archivo almacenado, o no existe ninguno de los dos.
- **FR-008**: Importar contenido NO DEBE publicarlo, programarlo ni comunicarse con ninguna
  plataforma externa.

**Almacenamiento**

- **FR-009**: Al importar, el sistema DEBE guardar una copia del archivo en el almacenamiento
  local gestionado por AutoPublisher, organizado de forma mantenible (al menos separado por
  proyecto) y fuera del repositorio Git.
- **FR-010**: El sistema NO DEBE modificar, mover, renombrar ni eliminar el archivo original
  del usuario.
- **FR-011**: Un contenido DEBE seguir disponible aunque el archivo original del usuario se
  mueva o elimine.
- **FR-012**: El sistema DEBE guardar una única copia física por contenido, pensada para ser
  reutilizada por todas sus futuras publicaciones sin duplicarla por plataforma o cuenta.
- **FR-013**: El nombre y la ubicación del archivo almacenado DEBEN ser decididos por
  AutoPublisher y NO DEBEN permitir escribir fuera de su almacenamiento ni sobrescribir
  archivos existentes, sea cual sea el nombre original.
- **FR-014**: El sistema NO DEBE convertir, transcodificar, comprimir, redimensionar ni
  editar los archivos importados: la copia almacenada es idéntica al original.

**Duplicados**

- **FR-015**: El sistema DEBE calcular para cada archivo importado un checksum robusto
  basado en su contenido completo.
- **FR-016**: Si se importa en un proyecto un archivo cuyo checksum coincide con el de un
  contenido existente de ese mismo proyecto (incluido otro archivo del mismo lote), el sistema
  NO DEBE crear un nuevo contenido ni una nueva copia, y DEBE informar del duplicado indicando
  el contenido existente.
- **FR-017**: El sistema DEBE permitir que el mismo archivo exista como contenidos
  independientes en proyectos diferentes.

**Contenido y metadata**

- **FR-018**: Cada contenido DEBE tener: identificador único, proyecto al que pertenece
  (obligatorio e inmutable), tipo (imagen o vídeo), referencia a su archivo almacenado, nombre
  original del archivo, título opcional, descripción opcional, hashtags opcionales, checksum,
  tamaño en bytes, fecha de creación (importación) y fecha de última modificación.
- **FR-019**: Cuando pueda obtenerse de forma sencilla, el sistema DEBE guardar la anchura y
  altura de imágenes y vídeos y la duración de los vídeos. Si no puede obtenerse, el contenido
  se importa igualmente con esos datos vacíos.
- **FR-020**: El sistema DEBE permitir editar el título (máximo 200 caracteres), la
  descripción (máximo 5000 caracteres) y los hashtags (máximo 30 hashtags de hasta 100
  caracteres cada uno, sin espacios) de un contenido, aplicando la normalización descrita en
  los Edge Cases. Los tres campos pueden quedar vacíos.
- **FR-021**: Una edición que suponga una modificación efectiva de título, descripción o
  hashtags DEBE actualizar la fecha de última modificación. Una edición que guarde
  exactamente los mismos valores normalizados que ya tenía el contenido DEBE ser idempotente
  y NO DEBE modificar la fecha de última modificación. Ninguna edición DEBE modificar la fecha
  de creación ni el archivo almacenado. Los datos técnicos
  (tipo, archivo, nombre original, checksum, tamaño, dimensiones, duración, proyecto) NO son
  editables.
- **FR-022**: La metadata de un contenido es global al contenido; no existe todavía metadata
  por plataforma.
- **FR-023**: El sistema NO DEBE ofrecer eliminación de contenido ni de sus archivos.

**Consulta y persistencia**

- **FR-024**: El sistema DEBE permitir listar los contenidos de un proyecto, ordenados del
  más reciente al más antiguo por fecha de importación, y consultar un contenido concreto con
  todos sus datos.
- **FR-025**: El sistema DEBE permitir obtener el archivo almacenado de un contenido para
  mostrar su preview en la interfaz.
- **FR-026**: Los contenidos, su metadata y su relación con el proyecto DEBEN persistir en la
  base de datos local, y los archivos en el almacenamiento local, sobreviviendo a reinicios
  de la aplicación. El esquema DEBE evolucionar mediante el mecanismo versionado de
  migraciones existente, sin perder los datos de proyectos y cuentas.

**API y errores**

- **FR-027**: El backend DEBE exponer la API necesaria para listar el contenido de un
  proyecto, consultar un contenido, importar uno o varios archivos, editar metadata y obtener
  el archivo para preview, validando todos los datos recibidos.
- **FR-028**: Los errores DEBEN seguir el formato estructurado establecido en la Feature 002
  (mensaje comprensible, campo afectado cuando proceda, distinción entre datos inválidos,
  no encontrado y conflicto) y NO DEBEN exponer detalles internos como rutas absolutas del
  sistema.

**Interfaz**

- **FR-029**: La interfaz DEBE permitir acceder desde cada proyecto a su biblioteca de
  contenido.
- **FR-030**: La biblioteca DEBE mostrar un listado o grid sencillo con preview, indicación
  de imagen/vídeo, título o nombre original y fecha de importación, y un estado vacío claro
  cuando no haya contenido.
- **FR-031**: La interfaz DEBE permitir importar archivos tanto arrastrándolos sobre una zona
  de importación como mediante el selector de archivos tradicional, en ambos casos con
  selección múltiple.
- **FR-032**: La interfaz DEBE mostrar el progreso de una importación en curso y, al
  terminar, el resultado por archivo (importados, duplicados y rechazados con su motivo),
  distinguiendo visualmente los tres casos.
- **FR-033**: La interfaz DEBE permitir consultar la metadata completa de un contenido y
  editar su título, descripción y hashtags, mostrando los errores de forma comprensible sin
  perder lo escrito.
- **FR-034**: Cuando el proyecto esté inactivo, la interfaz DEBE impedir o rechazar con un
  mensaje claro la importación, manteniendo accesible la consulta y edición de su contenido.

### Key Entities *(include if feature involves data)*

- **Contenido (Content)**: pieza multimedia reutilizable importada en un proyecto. Atributos:
  identificador único, proyecto (obligatorio e inmutable), tipo (imagen/vídeo), referencia al
  archivo almacenado, nombre original, título opcional, descripción opcional, hashtags
  (lista ordenada, opcional), checksum, tamaño, anchura/altura opcionales, duración opcional
  (solo vídeo), fecha de creación y fecha de última modificación. Pertenece siempre a
  exactamente un proyecto; dentro de un proyecto, el checksum es único. Conceptualmente está
  "sin programar" hasta que existan publicaciones (feature futura).
- **Archivo almacenado**: copia exacta del archivo original, gestionada por AutoPublisher en
  su almacenamiento local. Corresponde a un único contenido y será compartida por sus futuras
  publicaciones.
- **Resultado de importación**: respuesta no persistente a una operación de importación que
  indica, por cada archivo enviado, si se importó, era duplicado o se rechazó y por qué.
- **Proyecto** (existente, Feature 002): tiene cero o más contenidos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El flujo de referencia se completa sin errores: abrir el proyecto "L4i4";
  arrastrar en una sola operación varias imágenes y vídeos; comprobar que AutoPublisher los
  ha copiado a su almacenamiento; verlos en la biblioteca; editar título, descripción y
  hashtags; cerrar y reiniciar la aplicación; comprobar que archivos y metadata siguen
  disponibles; e intentar importar de nuevo uno de los archivos recibiendo un aviso de
  duplicado sin que aparezca un nuevo contenido ni una nueva copia.
- **SC-002**: Un lote de 30 archivos válidos (imágenes y vídeos de tamaño habitual en redes
  sociales) se importa en una sola operación y el usuario ve el resultado completo en menos de
  1 minuto en un equipo personal típico.
- **SC-003**: En un lote que mezcla archivos válidos, inválidos y duplicados, el 100 % de los
  archivos válidos se importa y el 100 % de los archivos se refleja en el resultado con su
  categoría correcta.
- **SC-004**: El 100 % de los contenidos, su metadata y sus archivos sobreviven a un reinicio
  completo de la aplicación, también cuando los archivos originales del usuario se han
  movido o eliminado.
- **SC-005**: El 100 % de los reintentos de importar un archivo idéntico en el mismo proyecto
  se informan como duplicado, sin aumentar el número de contenidos ni de archivos
  almacenados.
- **SC-006**: Ningún archivo original del usuario resulta modificado, movido o eliminado por
  una importación.
- **SC-007**: Con al menos 200 contenidos en un proyecto, la biblioteca se muestra y es
  utilizable en menos de 2 segundos.
- **SC-008**: Todos los quality gates existentes (tests, lint, formato, type checking, build
  del frontend y CI) siguen pasando, y existen tests automatizados que cubren al menos:
  importación de imagen válida; importación de vídeo válido; importación múltiple;
  persistencia del contenido; persistencia del archivo copiado; edición de metadata;
  asociación correcta con el proyecto; rechazo de proyecto inexistente; rechazo de formato
  inválido; detección de duplicados por checksum; fallo parcial en importación múltiple; y el
  comportamiento básico de drag & drop y de la biblioteca en el frontend.

## Assumptions

- El stack, la base de datos local, el sistema de migraciones y el formato de errores son los
  ya establecidos en las Features 001 y 002. La forma concreta de la API, el algoritmo de
  checksum y las librerías para leer metadata técnica se deciden en `/speckit-plan`
  priorizando simplicidad.
- Los formatos soportados serán un conjunto reducido de formatos habituales en redes sociales
  (p. ej. JPEG, PNG y WebP para imagen; MP4, MOV y WebM para vídeo); la lista definitiva se
  fija en `/speckit-plan`. No se incluyen GIF animados ni formatos RAW salvo que el plan lo
  justifique.
- Ante un duplicado, el comportamiento por defecto es no importarlo e informarlo en el
  resultado (sin pedir confirmación ni ofrecer importarlo igualmente); es la opción más
  sencilla y cumple el requisito de no crear copias silenciosas.
- El almacenamiento multimedia vive en el directorio de datos local de AutoPublisher, en una
  ubicación configurable con valor por defecto documentado, ya excluida de Git.
- Importar en un proyecto inactivo se rechaza, por coherencia con la regla de cuentas de la
  Feature 002.
- La preview de imágenes usa el propio archivo almacenado y la de vídeos el reproductor
  nativo del navegador; no se generan thumbnails. Si un formato no puede previsualizarse en el
  navegador, basta con una representación reconocible del tipo de contenido.
- No se requiere búsqueda, filtros, ordenación configurable ni paginación en la biblioteca
  para el volumen esperado (centenares de contenidos por proyecto).
- No se modela todavía un estado de programación; "sin programar" es implícito para todo
  contenido de esta feature.
- Las fechas se registran con zona horaria inequívoca y se muestran en hora local.
- Aplicación local de un único usuario: no se contemplan importaciones concurrentes desde
  varios clientes.
- Fuera de alcance: Publication, selección de cuentas destino, scheduler, queue, calendario,
  publicación inmediata, APIs sociales, OAuth, metadata por plataforma, thumbnails
  personalizados, edición de imagen o vídeo, conversión/transcodificación, compresión,
  generación de metadata con IA, música, analytics y eliminación de contenido o archivos.
