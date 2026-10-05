# Feature Specification: Gestión básica de proyectos y cuentas

**Feature Branch**: `002-projects-accounts`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Crear la Feature 002 de AutoPublisher: gestión básica de proyectos y cuentas. Permitir organizar el trabajo mediante proyectos independientes (p. ej. 'L4i4', 'Cybersecurity') y asociar a cada uno múltiples cuentas de redes sociales (YouTube, Instagram, TikTok, X, Threads, Telegram), con persistencia local, API mínima para gestionarlos e interfaz funcional y minimalista. Sin eliminación física, sin integración real con plataformas, sin autenticación de usuario."

## Contexto

Esta es la primera funcionalidad de producto de AutoPublisher. Introduce los dos conceptos
organizativos sobre los que se construirán todas las features posteriores (contenido,
publicaciones, programación):

- **Proyecto**: una marca, temática o línea de trabajo independiente del usuario
  (p. ej. "L4i4", "Cybersecurity").
- **Cuenta**: la identidad de una cuenta de red social que pertenece a un proyecto
  (p. ej. Instagram `@l4i4`).

Una cuenta creada en esta feature representa únicamente la configuración/identidad de una
futura cuenta conectada: **no** está autenticada contra la plataforma ni se comunica con ella.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Crear y consultar proyectos persistentes (Priority: P1)

Como usuario de AutoPublisher, quiero crear proyectos con un nombre y una descripción opcional
y verlos en una lista, para organizar mi trabajo por marcas o temáticas, y quiero que sigan ahí
cuando vuelva a abrir la aplicación.

**Why this priority**: el proyecto es la unidad organizativa raíz; sin él no pueden existir
cuentas ni ninguna funcionalidad futura. Junto con la persistencia, constituye el MVP mínimo.

**Independent Test**: crear los proyectos "L4i4" y "Cybersecurity", comprobar que aparecen en
la lista, abrir uno para ver su detalle, reiniciar la aplicación completa y comprobar que ambos
siguen disponibles con los mismos datos.

**Acceptance Scenarios**:

1. **Given** la aplicación sin proyectos, **When** el usuario abre la pantalla principal,
   **Then** ve un estado vacío que le invita a crear su primer proyecto.
2. **Given** la aplicación en marcha, **When** el usuario crea un proyecto con nombre "L4i4"
   y sin descripción, **Then** el proyecto aparece en la lista como activo, con su fecha de
   creación y última modificación.
3. **Given** un proyecto existente, **When** el usuario lo selecciona, **Then** ve su nombre,
   descripción, estado, fecha de creación y fecha de última modificación.
4. **Given** proyectos creados, **When** se cierran y vuelven a iniciar frontend y backend,
   **Then** todos los proyectos siguen disponibles con exactamente los mismos datos.
5. **Given** el formulario de creación, **When** el usuario intenta crear un proyecto con el
   nombre vacío o formado solo por espacios, **Then** la creación se rechaza con un mensaje
   comprensible y no se crea nada.
6. **Given** un proyecto "L4i4" existente, **When** el usuario intenta crear otro proyecto
   llamado "l4i4" (mismas letras, distinto uso de mayúsculas), **Then** la creación se rechaza
   indicando que ya existe un proyecto con ese nombre.

---

### User Story 2 - Añadir y consultar cuentas de un proyecto (Priority: P1)

Como usuario, quiero añadir a un proyecto varias cuentas de distintas plataformas (indicando
plataforma, handle y un nombre visible opcional) y verlas dentro del proyecto, para tener
registrada la identidad de cada canal en el que publicaré.

**Why this priority**: asociar cuentas a proyectos es el objetivo central de la feature; sin
ello los proyectos no aportan valor operativo.

**Independent Test**: con un proyecto "L4i4" creado, añadirle cuentas de Instagram, TikTok y X
con handle `l4i4`, comprobar que aparecen únicamente dentro de ese proyecto, reiniciar la
aplicación y comprobar que siguen asociadas correctamente.

**Acceptance Scenarios**:

1. **Given** un proyecto activo, **When** el usuario añade una cuenta de Instagram con handle
   `@l4i4`, **Then** la cuenta aparece en la lista de cuentas del proyecto como activa, con su
   plataforma, handle, nombre visible (si se indicó) y fechas.
2. **Given** un proyecto activo, **When** el usuario añade cuentas de varias plataformas,
   **Then** todas aparecen en ese proyecto y en ningún otro.
3. **Given** un proyecto con una cuenta de YouTube, **When** el usuario añade una segunda
   cuenta de YouTube con un handle distinto, **Then** ambas coexisten en el proyecto.
4. **Given** el formulario de cuenta, **When** el usuario intenta crearla sin plataforma, sin
   handle o con una plataforma no reconocida, **Then** se rechaza con un mensaje comprensible.
5. **Given** cualquier intento de asociar una cuenta a un proyecto inexistente, **When** se
   envía la petición, **Then** se rechaza indicando que el proyecto no existe y no se crea
   ninguna cuenta.
6. **Given** dos proyectos con cuentas, **When** se reinicia la aplicación, **Then** cada
   cuenta sigue perteneciendo al mismo proyecto que antes.
7. **Given** un proyecto con la cuenta Instagram `l4i4`, **When** el usuario intenta añadir
   otra cuenta de Instagram con handle `@L4i4` en el mismo proyecto, **Then** se rechaza por
   duplicada.

---

### User Story 3 - Editar y desactivar/reactivar proyectos (Priority: P2)

Como usuario, quiero editar el nombre y la descripción de un proyecto y poder desactivarlo y
reactivarlo, para mantener mi organización al día sin perder nunca información.

**Why this priority**: la edición y el cambio de estado son necesarios para el mantenimiento
diario, pero la feature ya aporta valor con solo crear y consultar.

**Independent Test**: editar el nombre y la descripción de un proyecto con cuentas,
desactivarlo, comprobar que sigue visible (marcado como inactivo) y que sus cuentas siguen
intactas, reactivarlo y comprobar que todo se conserva.

**Acceptance Scenarios**:

1. **Given** un proyecto existente, **When** el usuario cambia su nombre y descripción,
   **Then** los cambios se guardan, la fecha de última modificación se actualiza y la fecha de
   creación no cambia.
2. **Given** un proyecto activo con cuentas, **When** el usuario lo desactiva, **Then** el
   proyecto aparece como inactivo, sigue siendo consultable y todas sus cuentas se conservan
   con su estado individual sin modificar.
3. **Given** un proyecto inactivo, **When** el usuario lo reactiva, **Then** vuelve a estar
   activo con todos sus datos y cuentas intactos.
4. **Given** un proyecto, **When** el usuario intenta dejar su nombre vacío o renombrarlo con
   el nombre de otro proyecto existente, **Then** la edición se rechaza con un mensaje
   comprensible y los datos anteriores se conservan.
5. **Given** cualquier proyecto, **When** el usuario busca una opción para eliminarlo,
   **Then** no existe: los proyectos no se pueden eliminar en esta feature.

---

### User Story 4 - Editar y desactivar/reactivar cuentas (Priority: P2)

Como usuario, quiero corregir el handle o el nombre visible de una cuenta y poder desactivarla
y reactivarla, para reflejar cambios en mis canales sin perder su historial.

**Why this priority**: igual que en proyectos, es mantenimiento necesario pero secundario frente
a la creación.

**Independent Test**: editar el handle y el nombre visible de una cuenta, desactivarla,
comprobar que sigue visible como inactiva dentro de su proyecto, reactivarla y comprobar que
conserva sus datos.

**Acceptance Scenarios**:

1. **Given** una cuenta existente, **When** el usuario cambia su handle o nombre visible,
   **Then** los cambios se guardan y se actualiza su fecha de última modificación sin alterar
   la de creación ni el proyecto al que pertenece.
2. **Given** una cuenta activa, **When** el usuario la desactiva, **Then** aparece como
   inactiva en la lista de cuentas de su proyecto y no se elimina.
3. **Given** una cuenta inactiva, **When** el usuario la reactiva, **Then** vuelve a estar
   activa con todos sus datos intactos.
4. **Given** una cuenta, **When** el usuario intenta dejar su handle vacío o hacerlo coincidir
   con otra cuenta de la misma plataforma del mismo proyecto, **Then** la edición se rechaza
   con un mensaje comprensible.
5. **Given** cualquier cuenta, **When** el usuario busca una opción para eliminarla,
   **Then** no existe: las cuentas no se pueden eliminar en esta feature.

---

### Edge Cases

- **Nombres y handles con espacios**: se eliminan los espacios al principio y al final antes de
  validar y guardar; un valor formado solo por espacios cuenta como vacío.
- **Handle con o sin `@`**: `@l4i4` y `l4i4` representan el mismo handle; el sistema lo
  almacena de forma normalizada (sin `@` inicial) y lo muestra de forma consistente.
- **Mayúsculas en nombres y handles**: la comparación para detectar duplicados no distingue
  mayúsculas de minúsculas, pero se conserva y muestra el texto tal como lo escribió el usuario.
  Además de eliminar espacios exteriores (y el `@` inicial en handles), la comparación
  contempla equivalencias Unicode mediante la estrategia aprobada en el plan (NFKC +
  casefold): p. ej. "Straße" y "STRASSE", o una "é" precompuesta y una descompuesta, se
  consideran el mismo valor.
- **Misma cuenta en proyectos distintos**: se permite registrar la misma plataforma y handle en
  dos proyectos diferentes (son configuraciones independientes); solo se rechaza el duplicado
  dentro del mismo proyecto.
- **Duplicados con cuentas inactivas**: una cuenta inactiva sigue contando para la detección
  de duplicados (debe reactivarse en lugar de crearse de nuevo).
- **Añadir cuentas a un proyecto inactivo**: se rechaza con un mensaje que indica que el
  proyecto debe reactivarse primero. Las cuentas existentes de un proyecto inactivo siguen
  siendo consultables, editables y reactivables/desactivables.
- **Proyecto o cuenta inexistente**: consultar, editar o cambiar el estado de un identificador
  que no existe devuelve un error claro de "no encontrado".
- **Textos demasiado largos**: valores que superen los límites definidos se rechazan con un
  mensaje que indica el máximo permitido.
- **Desactivar/activar algo que ya está en ese estado**: la operación es idempotente; no da
  error, no altera otros datos y no modifica la fecha de última modificación.
- **Primer arranque**: si el almacenamiento local no existe, se crea automáticamente vacío y
  la aplicación muestra el estado vacío.
- **Fallo del backend o del almacenamiento**: la interfaz muestra un mensaje de error visible
  y no da por guardado un cambio que no se ha persistido.

## Requirements *(mandatory)*

### Functional Requirements

**Proyectos**

- **FR-001**: El sistema DEBE permitir crear un proyecto indicando un nombre obligatorio
  (1–100 caracteres tras eliminar espacios exteriores) y una descripción opcional
  (máximo 1000 caracteres).
- **FR-002**: El sistema DEBE asignar a cada proyecto un identificador único, el estado
  "activo" al crearse, y registrar su fecha de creación y de última modificación.
- **FR-003**: El sistema DEBE impedir que existan dos proyectos con el mismo nombre,
  comparando sin distinguir mayúsculas/minúsculas, incluidos los proyectos inactivos.
- **FR-004**: El sistema DEBE permitir listar todos los proyectos, activos e inactivos,
  indicando claramente el estado de cada uno, ordenados alfabéticamente por nombre.
- **FR-005**: El sistema DEBE permitir consultar un proyecto concreto con todos sus datos.
- **FR-006**: El sistema DEBE permitir editar el nombre y la descripción de un proyecto,
  aplicando las mismas validaciones que en la creación.
- **FR-007**: El sistema DEBE permitir desactivar y reactivar un proyecto. Desactivar un
  proyecto NO DEBE eliminar ni cambiar el estado de sus cuentas.
- **FR-008**: El sistema NO DEBE ofrecer eliminación física de proyectos.

**Cuentas**

- **FR-009**: El sistema DEBE permitir añadir una cuenta a un proyecto existente y activo
  indicando plataforma (obligatoria), handle (obligatorio, 1–100 caracteres) y nombre visible
  (opcional, máximo 100 caracteres).
- **FR-010**: Las plataformas reconocidas DEBEN ser exactamente: YouTube, Instagram, TikTok,
  X, Threads y Telegram. Cualquier otro valor DEBE rechazarse.
- **FR-011**: El sistema DEBE asignar a cada cuenta un identificador único, asociarla a un
  único proyecto, ponerla en estado "activo" al crearse y registrar sus fechas de creación y
  última modificación.
- **FR-012**: El sistema DEBE rechazar cualquier intento de asociar una cuenta a un proyecto
  inexistente, sin crear ningún dato.
- **FR-013**: El sistema DEBE permitir varias cuentas de la misma plataforma en un proyecto,
  pero DEBE impedir dos cuentas con la misma plataforma y el mismo handle (normalizado según
  los Edge Cases) dentro del mismo proyecto, incluidas las inactivas.
- **FR-014**: El sistema DEBE permitir listar las cuentas de un proyecto, activas e inactivas,
  indicando su estado, ordenadas por plataforma y después por handle.
- **FR-015**: El sistema DEBE permitir editar el handle y el nombre visible de una cuenta,
  aplicando las mismas validaciones que en la creación. La plataforma y el proyecto de una
  cuenta NO son editables en esta feature.
- **FR-016**: El sistema DEBE permitir desactivar y reactivar una cuenta sin eliminarla.
- **FR-017**: El sistema NO DEBE ofrecer eliminación física de cuentas.

**Comunes**

- **FR-018**: Toda edición o cambio de estado que suponga una modificación efectiva de los
  datos o del estado DEBE actualizar la fecha de última modificación del registro afectado y
  NO DEBE modificar su fecha de creación. Una activación o desactivación sobre un recurso que
  ya se encuentra en el estado solicitado NO DEBE modificar la fecha de última modificación.
- **FR-019**: Los proyectos y cuentas DEBEN persistir localmente y seguir disponibles, con los
  mismos datos y relaciones, tras reiniciar frontend y backend.
- **FR-020**: DEBE existir un mecanismo mantenible y versionado para crear el esquema de
  almacenamiento en el primer arranque y evolucionarlo en features futuras sin perder los
  datos existentes.
- **FR-021**: El backend DEBE exponer una API mínima que cubra todas las operaciones de
  proyectos y cuentas descritas, validando todos los datos recibidos.
- **FR-022**: Los errores DEBEN devolverse con un formato estructurado y consistente, un
  mensaje comprensible para el usuario e indicación del campo afectado cuando proceda,
  distinguiendo al menos: datos inválidos, recurso no encontrado y conflicto (duplicado o
  proyecto inactivo). Los errores NO DEBEN exponer detalles internos.
- **FR-023**: La interfaz DEBE permitir: ver los proyectos; crear un proyecto; seleccionar y
  abrir un proyecto; editarlo o cambiar su estado; ver sus cuentas; añadir una cuenta; editar
  o cambiar el estado de una cuenta.
- **FR-024**: La interfaz DEBE mostrar de forma visible el estado (activo/inactivo) de cada
  proyecto y cuenta, y los registros inactivos DEBEN seguir siendo accesibles para poder
  reactivarlos.
- **FR-025**: La interfaz DEBE mostrar los errores de validación y de servidor de forma
  comprensible, junto al formulario o acción que los provocó, sin perder lo que el usuario
  había escrito.
- **FR-026**: La aplicación NO DEBE requerir autenticación de usuario.
- **FR-027**: Ningún dato de esta feature DEBE incluir ni solicitar tokens, contraseñas ni
  credenciales de plataformas.

### Key Entities *(include if feature involves data)*

- **Proyecto**: unidad organizativa independiente (marca o temática). Atributos:
  identificador único, nombre (único sin distinguir mayúsculas), descripción opcional, estado
  activo/inactivo, fecha de creación, fecha de última modificación. Tiene cero o más cuentas.
- **Cuenta**: identidad configurada de una cuenta de red social, todavía no conectada.
  Atributos: identificador único, proyecto al que pertenece (obligatorio e inmutable),
  plataforma (de la lista reconocida, inmutable), handle, nombre visible opcional, estado
  activo/inactivo, fecha de creación, fecha de última modificación. Pertenece siempre a
  exactamente un proyecto.
- **Plataforma**: catálogo cerrado de valores reconocidos (YouTube, Instagram, TikTok, X,
  Threads, Telegram). No tiene datos propios editables en esta feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El flujo completo de referencia se puede realizar sin errores: iniciar la
  aplicación; crear "L4i4" y "Cybersecurity"; añadir al menos 3 cuentas de distintas
  plataformas a cada uno; cerrar y volver a iniciar la aplicación; comprobar que proyectos y
  cuentas siguen disponibles; editar o desactivar cualquiera; y reactivarlos sin pérdida de
  información.
- **SC-002**: El 100 % de los proyectos y cuentas creados sobreviven a un reinicio completo
  de la aplicación con idénticos datos, estados y asociaciones.
- **SC-003**: Un usuario puede crear un proyecto y añadirle su primera cuenta en menos de
  1 minuto desde la pantalla principal.
- **SC-004**: El 100 % de las entradas inválidas cubiertas por los requisitos (nombres o
  handles vacíos, demasiado largos, duplicados, plataformas no reconocidas, proyectos
  inexistentes o inactivos) se rechazan con un mensaje comprensible y sin crear ni modificar
  datos.
- **SC-005**: Ninguna operación disponible en la aplicación provoca la desaparición de un
  proyecto o una cuenta: tras cualquier secuencia de ediciones y cambios de estado, el número
  total de registros nunca disminuye.
- **SC-006**: Con al menos 20 proyectos y 100 cuentas registrados, las listas y el detalle de
  un proyecto se muestran sin esperas perceptibles (menos de 1 segundo).
- **SC-007**: Todos los quality gates establecidos en la Feature 001 (tests, lint, formato,
  type checking, build del frontend y CI) siguen pasando, y existen tests automatizados que
  cubren: creación y persistencia de proyectos; edición; activación/desactivación; varias
  cuentas por proyecto; asociación cuenta-proyecto; rechazo de proyectos inexistentes; edición
  y activación/desactivación de cuentas; persistencia tras reabrir el almacenamiento; y el
  comportamiento básico de la interfaz.

## Assumptions

- El stack tecnológico (incluido el uso de SQLite local para la persistencia y una API REST
  entre frontend y backend) viene fijado por la Constitution y por la descripción de la
  feature; la elección concreta de ORM y sistema de migraciones se decide en `/speckit-plan`
  priorizando simplicidad.
- La base de datos local se guarda en una ubicación configurable con un valor por defecto
  documentado, y nunca se versiona en el repositorio (Constitution, principio IV).
- Los nombres de proyecto son únicos para evitar confusión al seleccionar proyectos; los
  handles solo son únicos por plataforma dentro de un mismo proyecto.
- La plataforma de una cuenta no es editable: si se registró con la plataforma equivocada, el
  usuario la desactiva y crea una nueva. Mover cuentas entre proyectos queda fuera de alcance.
- No se valida el formato específico de los handles de cada plataforma (caracteres
  permitidos, longitud propia de cada red): solo se aplican las reglas genéricas de esta
  especificación. Esa validación corresponderá a futuras integraciones.
- No se requiere búsqueda, filtrado ni paginación en las listas: el volumen esperado de un
  único usuario es pequeño (decenas de proyectos, centenares de cuentas como máximo).
- Las fechas se registran con hora y zona horaria inequívoca, y la interfaz las muestra en la
  hora local del usuario.
- Al ser una aplicación local de un único usuario, no se contemplan ediciones concurrentes.
- La interfaz es funcional y minimalista; no se construye todavía el dashboard definitivo ni
  un diseño avanzado.
- Fuera de alcance: OAuth, login en redes sociales, tokens o credenciales, conexión con APIs
  sociales, publicación, Content, Publication, scheduler, queue, calendario, subida de
  multimedia, metadata de publicaciones, eliminación física, analytics e IA.
