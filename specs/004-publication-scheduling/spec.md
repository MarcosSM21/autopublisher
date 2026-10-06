# Feature Specification: Publicaciones, selección de cuentas destino y programación

**Feature Branch**: `004-publication-scheduling`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "Crear la Feature 004 de AutoPublisher: modelo de publicaciones, selección de cuentas destino y programación. Una Publication representa la intención de publicar un Content concreto en una Account concreta del mismo proyecto. Crear una o varias Publications desde un Content seleccionando cuentas activas; estados UNSCHEDULED, SCHEDULED y CANCELLED; fecha/hora opcional por Publication; overrides opcionales de título, descripción y hashtags heredando la metadata global del Content; prevención de duplicados activos Content + Account; edición, cancelación y reactivación; vista Queue; persistencia local con migraciones. Sin publicación real, APIs sociales, OAuth, scheduler worker, ejecución automática, retries, estados PUBLISHING/PUBLISHED/FAILED, calendario ni eliminación física."

## Contexto

Esta feature introduce el concepto de **Publicación** (`Publication`): la intención de
publicar un contenido concreto (`Content`, Feature 003) en una cuenta concreta (`Account`,
Feature 002) del mismo proyecto. La relación principal es:

`Project → Content → Publication → Account`

Un mismo contenido puede tener varias publicaciones, una por cuenta destino, todas
compartiendo el mismo archivo multimedia. Por ejemplo, `video_01.mp4` puede tener una
publicación en YouTube @CyberChannel programada para el 10 de octubre a las 18:00, otra en
TikTok @CyberChannel para el 11 de octubre a las 20:00 y otra en Instagram @CyberChannel sin
programar.

En esta feature **programar significa únicamente guardar la intención**: no se publica nada,
no existe conexión con ninguna red social y no se ejecuta ninguna acción cuando llega la hora
programada. La publicación real, el scheduler y sus estados (`PUBLISHING`, `PUBLISHED`,
`FAILED`) llegarán en features futuras.

AutoPublisher sigue siendo una aplicación local de un único usuario, sin login.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preparar publicaciones de un contenido en varias cuentas (Priority: P1)

Como usuario, quiero abrir un contenido ya importado, seleccionar una o varias cuentas activas
de su proyecto y, opcionalmente, una fecha y hora, para crear de una sola vez una publicación
por cada cuenta sin duplicar el archivo.

**Why this priority**: es el núcleo de la feature; sin crear publicaciones no hay nada que
programar ni consultar.

**Independent Test**: en el proyecto "L4i4", abrir un vídeo importado, seleccionar las
cuentas de Instagram, TikTok y X, confirmar y comprobar que existen exactamente tres
publicaciones `UNSCHEDULED`, una por cuenta, todas apuntando al mismo contenido, y que el
almacenamiento multimedia no contiene ninguna copia nueva del archivo.

**Acceptance Scenarios**:

1. **Given** un contenido de un proyecto activo con al menos una cuenta activa, **When** el
   usuario abre la acción de preparar publicaciones desde el detalle del contenido, **Then**
   ve las cuentas activas de ese proyecto (y solo de ese proyecto), identificadas por
   plataforma, handle y nombre visible, y puede seleccionar una o varias.
2. **Given** una única cuenta seleccionada y sin fecha, **When** el usuario confirma, **Then**
   se crea una publicación `UNSCHEDULED` asociada a ese contenido, esa cuenta y ese proyecto.
3. **Given** tres cuentas seleccionadas, **When** el usuario confirma, **Then** se crean tres
   publicaciones independientes en una sola operación, todas apuntando al mismo contenido, y
   no se crea ninguna copia adicional del archivo multimedia.
4. **Given** varias cuentas seleccionadas y una fecha y hora futura, **When** el usuario
   confirma, **Then** todas las publicaciones creadas quedan `SCHEDULED` con esa fecha y hora.
5. **Given** una creación completada, **When** termina, **Then** el usuario recibe un
   feedback claro indicando cuántas publicaciones se crearon y para qué cuentas, y cómo
   encontrarlas en la Queue.
6. **Given** una cuenta inactiva del proyecto, **When** el usuario prepara publicaciones,
   **Then** esa cuenta no puede seleccionarse, y si se intenta usarla igualmente la operación
   se rechaza con un mensaje comprensible.
7. **Given** una cuenta de otro proyecto, **When** se intenta crear una publicación del
   contenido para esa cuenta, **Then** se rechaza indicando que la cuenta no pertenece al
   proyecto del contenido.
8. **Given** un proyecto inactivo, **When** el usuario intenta preparar publicaciones de uno
   de sus contenidos, **Then** la acción no está disponible o se rechaza con un mensaje que
   indica que el proyecto debe reactivarse primero.
9. **Given** un proyecto activo sin cuentas activas, **When** el usuario abre la acción de
   preparar publicaciones, **Then** ve un mensaje claro indicando que necesita al menos una
   cuenta activa en el proyecto.
10. **Given** publicaciones creadas, **When** se reinicia la aplicación, **Then** siguen
    existiendo con sus relaciones, estados y fechas.

---

### User Story 2 - Evitar publicaciones activas duplicadas (Priority: P1)

Como usuario, quiero que AutoPublisher me avise si intento preparar una publicación de un
contenido en una cuenta para la que ya existe una publicación activa, para no publicar dos
veces lo mismo por accidente.

**Why this priority**: una publicación duplicada sin aviso es uno de los fallos más graves de
la aplicación según la Constitution.

**Independent Test**: crear una publicación de un contenido en Instagram; intentar crear otra
para el mismo contenido en Instagram y comprobar que se informa del conflicto sin crear nada;
cancelar la primera y comprobar que ahora sí puede crearse una nueva.

**Acceptance Scenarios**:

1. **Given** una publicación `UNSCHEDULED` o `SCHEDULED` para un contenido y una cuenta,
   **When** el usuario intenta crear otra para la misma pareja, **Then** se rechaza indicando
   claramente qué cuenta ya tiene una publicación activa de ese contenido, y no se crea
   ninguna publicación.
2. **Given** una selección de varias cuentas en la que una de ellas ya tiene una publicación
   activa del contenido, **When** el usuario confirma, **Then** la operación completa se
   rechaza indicando las cuentas en conflicto y no se crea ninguna publicación; el usuario
   puede deseleccionar esas cuentas y volver a confirmar.
3. **Given** el detalle de un contenido, **When** el usuario abre la acción de preparar
   publicaciones, **Then** las cuentas que ya tienen una publicación activa de ese contenido
   aparecen indicadas como tales y no seleccionables.
4. **Given** una publicación `CANCELLED` para un contenido y una cuenta, **When** el usuario
   crea una nueva publicación para la misma pareja, **Then** se crea correctamente y la
   cancelada se conserva en el historial.

---

### User Story 3 - Programar y desprogramar publicaciones individualmente (Priority: P1)

Como usuario, quiero asignar, cambiar o quitar la fecha y hora de cada publicación por
separado, aunque se hayan creado juntas, para planificar cada red social a su ritmo.

**Why this priority**: programar es el objetivo principal de la feature y del flujo de
referencia.

**Independent Test**: crear tres publicaciones juntas sin fecha; programar Instagram para una
fecha y TikTok para otra, dejar X sin programar; comprobar estados y fechas; quitar después la
fecha de TikTok y comprobar que vuelve a `UNSCHEDULED`.

**Acceptance Scenarios**:

1. **Given** una publicación `UNSCHEDULED`, **When** el usuario le asigna una fecha y hora
   futura, **Then** pasa a `SCHEDULED` con esa fecha, sin afectar a otras publicaciones del
   mismo contenido.
2. **Given** una publicación `SCHEDULED`, **When** el usuario cambia su fecha y hora a otra
   futura, **Then** se guarda la nueva fecha y sigue `SCHEDULED`.
3. **Given** una publicación `SCHEDULED`, **When** el usuario quita la fecha, **Then** vuelve
   a `UNSCHEDULED`.
4. **Given** una publicación, **When** el usuario intenta programarla para una fecha y hora
   pasada o inválida, **Then** se rechaza con un mensaje comprensible y la publicación no
   cambia.
5. **Given** una fecha y hora introducida en hora local, **When** se guarda y se vuelve a
   consultar (también tras reiniciar la aplicación), **Then** se muestra exactamente la misma
   hora local y representa el mismo instante.
6. **Given** una publicación `SCHEDULED` cuya hora llega, **When** pasa ese momento, **Then**
   no se publica nada ni cambia su estado automáticamente; la interfaz la indica como
   vencida (fecha pasada) para que el usuario pueda reprogramarla, desprogramarla o
   cancelarla.
7. **Given** un proyecto inactivo o una cuenta inactiva, **When** el usuario intenta
   programar una publicación existente asociada a ellos, **Then** se rechaza con un mensaje
   que indica qué debe reactivarse primero.

---

### User Story 4 - Consultar la Queue del proyecto (Priority: P2)

Como usuario, quiero una vista `Queue` del proyecto donde ver todas sus publicaciones,
distinguiendo programadas, sin programar y canceladas, para saber qué tengo planificado.

**Why this priority**: es la forma de encontrar y revisar las publicaciones, pero la creación
y programación ya aportan valor verificable por sí solas.

**Independent Test**: con un proyecto con publicaciones en los tres estados, abrir la Queue y
comprobar que aparecen todas con contenido, preview, plataforma, cuenta, estado y fecha,
ordenadas correctamente; con un proyecto sin publicaciones, comprobar el estado vacío.

**Acceptance Scenarios**:

1. **Given** un proyecto sin publicaciones, **When** el usuario abre la Queue, **Then** ve un
   estado vacío que le indica cómo preparar publicaciones desde el contenido.
2. **Given** un proyecto con publicaciones, **When** el usuario abre la Queue, **Then** ve
   todas las publicaciones de ese proyecto (y solo de ese proyecto) mostrando para cada una:
   título del contenido (o su nombre original), preview pequeña o representación del
   contenido, plataforma, cuenta, estado y, si existe, fecha y hora en hora local.
3. **Given** publicaciones en varios estados, **When** el usuario consulta la Queue, **Then**
   se distinguen claramente Scheduled, Unscheduled y Cancelled y aparecen en este orden:
   primero las `SCHEDULED` de la fecha más próxima a la más lejana, después las
   `UNSCHEDULED` y por último las `CANCELLED`.
4. **Given** una publicación cuya cuenta está inactiva, **When** el usuario consulta la
   Queue, **Then** la publicación sigue visible y se indica que su cuenta está inactiva.
5. **Given** un proyecto inactivo, **When** el usuario abre su Queue, **Then** puede
   consultar todas sus publicaciones.
6. **Given** una publicación en la Queue, **When** el usuario la selecciona, **Then** accede
   a su detalle y edición.

---

### User Story 5 - Personalizar la metadata de una publicación (Priority: P2)

Como usuario, quiero que cada publicación use por defecto el título, la descripción y los
hashtags del contenido, pero poder sobrescribir cualquiera de ellos solo para esa
publicación, para adaptar el texto a cada red sin tocar la metadata global.

**Why this priority**: es necesario para el flujo de referencia, pero las publicaciones son
útiles aunque usen solo la metadata global.

**Independent Test**: con un contenido con título y hashtags, crear publicaciones en
Instagram y TikTok; personalizar la descripción de Instagram; comprobar que la metadata del
contenido no cambia y que TikTok sigue mostrando los valores globales; editar después el
título global del contenido y comprobar que ambas publicaciones reflejan el nuevo título
(ninguna lo sobrescribía) y que Instagram mantiene su descripción propia.

**Acceptance Scenarios**:

1. **Given** una publicación recién creada, **When** el usuario consulta su detalle, **Then**
   cada campo (título, descripción, hashtags) indica que usa la metadata global del contenido
   y muestra el valor efectivo heredado.
2. **Given** una publicación, **When** el usuario sobrescribe su descripción y guarda,
   **Then** la publicación usa su descripción propia, el detalle indica que ese campo está
   personalizado, y la metadata del contenido y de las demás publicaciones no cambia.
3. **Given** una publicación sin override de título, **When** el usuario edita el título
   global del contenido, **Then** el título efectivo de la publicación pasa a ser el nuevo
   título global.
4. **Given** una publicación con override de descripción, **When** el usuario edita la
   descripción global del contenido, **Then** la publicación conserva su descripción propia.
5. **Given** un campo personalizado, **When** el usuario elige volver a usar la metadata
   global para ese campo, **Then** se descarta el override y el campo vuelve a heredar el
   valor del contenido.
6. **Given** un override, **When** el usuario lo deja vacío intencionadamente (p. ej. sin
   hashtags solo para X), **Then** se guarda como override vacío, distinto de "usar metadata
   global", y la publicación no muestra hashtags aunque el contenido sí los tenga.
7. **Given** un override que supera los límites permitidos o hashtags inválidos, **When** el
   usuario guarda, **Then** se rechaza con un mensaje comprensible junto al formulario sin
   perder lo escrito.

---

### User Story 6 - Cancelar y reactivar publicaciones (Priority: P2)

Como usuario, quiero cancelar una publicación que ya no quiero realizar sin perderla del
historial, y reactivarla si cambio de opinión, para mantener un registro claro de lo
planificado.

**Why this priority**: forma parte del flujo de referencia y sustituye a la eliminación
física, que no existe.

**Independent Test**: cancelar una publicación programada; comprobar que sigue visible en la
Queue como `CANCELLED` y que ya no cuenta como activa; reactivarla y comprobar su nuevo
estado; crear una nueva publicación activa para la misma pareja tras cancelar y comprobar que
la reactivación de la cancelada se rechaza por conflicto.

**Acceptance Scenarios**:

1. **Given** una publicación `UNSCHEDULED` o `SCHEDULED`, **When** el usuario la cancela,
   **Then** pasa a `CANCELLED`, sigue visible en la Queue en el grupo de canceladas y
   conserva su fecha (si la tenía) y sus overrides como historial.
2. **Given** una publicación `CANCELLED` con fecha futura, **When** el usuario la reactiva y
   no existe conflicto, **Then** vuelve a `SCHEDULED` con esa fecha.
3. **Given** una publicación `CANCELLED` sin fecha o con fecha ya pasada, **When** el
   usuario la reactiva y no existe conflicto, **Then** vuelve a `UNSCHEDULED`, se descarta
   la fecha pasada y se informa al usuario de que debe programarla de nuevo.
4. **Given** una publicación `CANCELLED` y otra activa para el mismo contenido y la misma
   cuenta, **When** el usuario intenta reactivar la cancelada, **Then** se rechaza indicando
   el conflicto con la publicación activa existente.
5. **Given** una publicación `CANCELLED` de un proyecto inactivo o de una cuenta inactiva,
   **When** el usuario intenta reactivarla, **Then** se rechaza indicando qué debe
   reactivarse primero.
6. **Given** una publicación `CANCELLED`, **When** el usuario intenta cambiar su fecha o sus
   overrides, **Then** no es posible: una publicación cancelada solo puede consultarse o
   reactivarse.
7. **Given** cualquier publicación, **When** el usuario busca una opción para eliminarla,
   **Then** no existe.

---

### Edge Cases

- **Proyecto inactivo**: sus publicaciones siguen consultables; no se pueden crear nuevas,
  ni programar (asignar o cambiar fecha), ni reactivar. Sí se pueden desprogramar, cancelar y
  editar sus overrides, operaciones que no preparan ninguna ejecución futura (coherente con
  la Feature 003, donde la metadata del contenido de un proyecto inactivo sigue editable).
- **Cuenta inactiva**: no puede usarse para nuevas publicaciones; sus publicaciones
  existentes siguen visibles con una indicación de cuenta inactiva. Aplican las mismas
  restricciones que con un proyecto inactivo: no se pueden programar ni reactivar, pero sí
  desprogramar, cancelar y editar sus overrides. Las publicaciones `SCHEDULED` existentes no
  cambian de estado automáticamente al desactivar la cuenta o el proyecto; la interfaz
  advierte de que su cuenta o proyecto está inactivo.
- **Cuenta o contenido inexistente**: crear publicaciones para un contenido que no existe se
  rechaza con un error de "no encontrado". Si alguna de las cuentas seleccionadas no existe,
  la operación se rechaza como datos inválidos indicando claramente, para cada una, que la
  cuenta no se encontró (mensaje distinto del de una cuenta de otro proyecto). En ambos casos
  no se crea ninguna publicación.
- **Selección vacía**: confirmar sin ninguna cuenta seleccionada no es posible en la interfaz
  y se rechaza como dato inválido si llega al sistema.
- **Cuenta repetida en la misma petición**: si la misma cuenta aparece varias veces en una
  creación, se trata como una sola.
- **Atomicidad de la creación múltiple**: si alguna de las cuentas solicitadas es inválida
  (inexistente, de otro proyecto, inactiva o en conflicto), no se crea ninguna publicación y
  el error indica qué cuentas fallaron y por qué.
- **Fecha pasada**: no se puede asignar una fecha y hora anterior al momento actual, ni al
  crear ni al editar. Una fecha que estaba en el futuro y que ya ha pasado no se modifica
  automáticamente: la publicación sigue `SCHEDULED` y la interfaz la marca como vencida.
- **Precisión de la fecha**: la programación tiene precisión de minuto.
- **Cambio de horario de verano o de zona horaria del equipo**: el instante guardado no
  cambia; la hora mostrada se recalcula según la hora local vigente.
- **Cambio de la cuenta, contenido o proyecto**: no se permite; para otra cuenta se crea otra
  publicación.
- **Override igual al valor global**: si el usuario guarda un override con el mismo valor que
  el global en ese momento, sigue siendo un override (no hereda cambios futuros) y se indica
  como personalizado; el usuario puede volver a "usar metadata global" explícitamente.
- **Normalización de overrides**: se aplican las mismas reglas que a la metadata del
  contenido (Feature 003): textos solo con espacios cuentan como vacíos; hashtags con o sin
  `#`, sin espacios, sin repetidos (sin distinguir mayúsculas) conservando el orden.
- **Edición idempotente**: guardar exactamente los mismos valores no modifica la fecha de
  última modificación de la publicación.
- **Contenido con archivo no disponible**: si el archivo multimedia almacenado de un
  contenido falta, sus publicaciones siguen visibles y consultables en la Queue con una
  representación del contenido en lugar de la preview, sin que falle la vista, y pueden
  cancelarse y desprogramarse. En cambio, no se pueden crear nuevas publicaciones para ese
  contenido, ni asignar o cambiar la fecha de sus publicaciones, ni reactivar sus
  publicaciones canceladas; el error indica claramente que el archivo multimedia del
  contenido no está disponible (ver FR-033).
- **Muchas publicaciones con la misma fecha**: varias publicaciones pueden compartir fecha y
  hora; su orden relativo en la Queue es estable.
- **Publicación inexistente**: consultar o editar un identificador que no existe devuelve un
  error claro de "no encontrado".

## Requirements *(mandatory)*

### Functional Requirements

**Modelo y estados**

- **FR-001**: Una publicación DEBE representar la intención de publicar exactamente un
  contenido en exactamente una cuenta, ambos del mismo proyecto. Contenido, cuenta y proyecto
  de una publicación son obligatorios e inmutables.
- **FR-002**: Los únicos estados de una publicación en esta feature DEBEN ser `UNSCHEDULED`,
  `SCHEDULED` y `CANCELLED`. NO DEBEN existir los estados `DRAFT`, `PUBLISHING`, `PUBLISHED`
  ni `FAILED`.
- **FR-003**: Una publicación no cancelada DEBE estar `UNSCHEDULED` si no tiene fecha y
  `SCHEDULED` si la tiene. Una publicación cancelada DEBE estar `CANCELLED`
  independientemente de si conserva una fecha.
- **FR-004**: Un mismo contenido DEBE poder tener varias publicaciones; todas DEBEN
  reutilizar el único archivo almacenado del contenido sin crear copias.

**Creación**

- **FR-005**: El sistema DEBE permitir crear, en una única operación, una publicación por cada
  cuenta de una selección de una o varias cuentas, para un mismo contenido, con una fecha y
  hora opcional común a todas.
- **FR-006**: El sistema DEBE rechazar la creación si el proyecto, el contenido o alguna
  cuenta no existen; si alguna cuenta no pertenece al proyecto del contenido; si alguna
  cuenta está inactiva; si el proyecto está inactivo; si la fecha es inválida o pasada; o si
  alguna cuenta tiene ya una publicación activa del contenido.
- **FR-007**: La creación múltiple DEBE ser atómica: o se crean todas las publicaciones
  solicitadas o ninguna, y el error DEBE identificar cada cuenta problemática y su motivo.

**Duplicados**

- **FR-008**: NO DEBEN existir simultáneamente dos publicaciones activas (`UNSCHEDULED` o
  `SCHEDULED`) para la misma pareja contenido + cuenta. El sistema DEBE garantizar esta regla
  tanto al crear como al reactivar, informando del conflicto en lugar de crear o reactivar
  silenciosamente.
- **FR-009**: Las publicaciones `CANCELLED` NO DEBEN impedir crear una nueva publicación para
  la misma pareja contenido + cuenta.

**Programación**

- **FR-010**: El sistema DEBE permitir asignar, cambiar o quitar individualmente la fecha y
  hora de una publicación no cancelada, actualizando su estado según FR-003.
- **FR-011**: Las fechas y horas DEBEN almacenarse como instantes inequívocos con zona
  horaria, introducirse y mostrarse en la hora local del usuario, con precisión de minuto.
- **FR-012**: Asignar o cambiar una fecha DEBE rechazarse si la fecha es anterior al momento
  actual, si el proyecto está inactivo o si la cuenta está inactiva.
- **FR-013**: El sistema NO DEBE ejecutar ninguna publicación ni cambiar automáticamente el
  estado de ninguna publicación cuando llegue o pase su fecha programada.

**Metadata**

- **FR-014**: Para cada campo de metadata (título, descripción, hashtags), una publicación
  DEBE distinguir entre "usar metadata global del contenido" (por defecto) y "usar override
  propio". Un override puede tener un valor vacío.
- **FR-015**: El valor efectivo de cada campo DEBE ser el override si existe y, si no, el
  valor global actual del contenido. Editar la metadata global del contenido DEBE reflejarse
  inmediatamente en todas sus publicaciones que no tengan override para ese campo.
- **FR-016**: El sistema NO DEBE copiar los valores globales del contenido en la publicación:
  solo se guardan los overrides definidos explícitamente.
- **FR-017**: Los overrides DEBEN cumplir los mismos límites y normalización que la metadata
  del contenido (título máximo 200 caracteres; descripción máxima 5000 caracteres; máximo 30
  hashtags de hasta 100 caracteres sin espacios). Editar overrides NO DEBE modificar la
  metadata del contenido ni de otras publicaciones.

**Edición, cancelación y reactivación**

- **FR-018**: El sistema DEBE permitir, sobre una publicación no cancelada, editar su fecha y
  hora, quitar la fecha, definir o descartar overrides de metadata y cancelarla.
- **FR-019**: Una publicación `CANCELLED` DEBE conservar su fecha y overrides y solo puede
  consultarse o reactivarse.
- **FR-020**: Reactivar una publicación cancelada DEBE llevarla a `SCHEDULED` si conserva una
  fecha futura, o a `UNSCHEDULED` (descartando una fecha pasada e informando al usuario) en
  caso contrario. La reactivación DEBE rechazarse si existe otra publicación activa para la
  misma pareja contenido + cuenta, si el proyecto está inactivo o si la cuenta está inactiva.
- **FR-021**: Toda modificación efectiva DEBE actualizar la fecha de última modificación de la
  publicación; las ediciones que no cambian nada DEBEN ser idempotentes.
- **FR-022**: El sistema NO DEBE ofrecer eliminación física de publicaciones.

**Consulta y persistencia**

- **FR-023**: El sistema DEBE permitir listar las publicaciones de un proyecto (incluidas las
  canceladas y las de cuentas inactivas) y consultar una publicación concreta con su
  contenido, cuenta, plataforma, estado, fecha, valores efectivos de metadata e indicación de
  qué campos están personalizados.
- **FR-024**: El listado DEBE ordenarse: `SCHEDULED` por fecha ascendente, después
  `UNSCHEDULED` y después `CANCELLED`, con un orden estable dentro de cada grupo.
- **FR-025**: Las publicaciones, sus relaciones, estados, fechas y overrides DEBEN persistir en
  la base de datos local y sobrevivir a reinicios. El esquema DEBE evolucionar mediante el
  mecanismo versionado de migraciones existente sin perder proyectos, cuentas ni contenidos.

**API y errores**

- **FR-026**: El backend DEBE exponer la API necesaria para listar las publicaciones de un
  proyecto, consultar una publicación, crear una o varias publicaciones desde un contenido,
  editar fecha y overrides, cancelar y reactivar, validando todos los datos recibidos.
- **FR-027**: Los errores DEBEN seguir el formato estructurado existente (mensaje
  comprensible, campo afectado cuando proceda, distinción entre datos inválidos, no
  encontrado y conflicto) sin exponer detalles internos.

**Interfaz**

- **FR-028**: El detalle de un contenido DEBE ofrecer una acción clara para preparar
  publicaciones, con un selector múltiple de las cuentas activas del proyecto (indicando las
  que ya tienen una publicación activa de ese contenido y no permitiendo seleccionarlas), una
  fecha y hora opcional y feedback claro del resultado.
- **FR-029**: La interfaz DEBE ofrecer una vista `Queue` por proyecto con la información y el
  orden definidos en la User Story 4, distinguiendo visualmente los tres estados, las
  publicaciones vencidas y las de cuentas inactivas, y con un estado vacío claro.
- **FR-030**: La interfaz DEBE ofrecer un detalle/edición de publicación que permita
  programar, desprogramar, editar o descartar overrides por campo, cancelar y reactivar,
  mostrando los errores de forma comprensible sin perder lo escrito.
- **FR-031**: La interfaz NO DEBE permitir cambiar el contenido, la cuenta ni el proyecto de
  una publicación, y DEBE deshabilitar o rechazar con un mensaje claro las acciones no
  permitidas por proyecto o cuenta inactivos.
- **FR-032**: Ninguna operación de esta feature DEBE comunicarse con plataformas externas ni
  solicitar credenciales.

**Archivo multimedia no disponible**

- **FR-033**: Si el archivo multimedia almacenado de un contenido no está disponible, el
  sistema DEBE mantener sus publicaciones existentes consultables en la Queue y permitir
  cancelarlas y desprogramarlas, pero DEBE rechazar: la creación de nuevas publicaciones para
  ese contenido; la asignación o el cambio de fecha de sus publicaciones; y la reactivación de
  sus publicaciones canceladas. El error DEBE indicar claramente que el archivo multimedia del
  contenido no está disponible.

### Key Entities *(include if feature involves data)*

- **Publicación (Publication)**: intención de publicar un contenido en una cuenta.
  Atributos: identificador único; proyecto, contenido y cuenta (obligatorios e inmutables,
  con contenido y cuenta del mismo proyecto); estado (`UNSCHEDULED`, `SCHEDULED`,
  `CANCELLED`); fecha y hora programada opcional con zona horaria; overrides opcionales de
  título, descripción y hashtags, cada uno distinguible de "usar metadata global"; fecha de
  creación y fecha de última modificación. Como máximo una publicación activa por pareja
  contenido + cuenta.
- **Contenido (Content)** (existente, Feature 003): tiene cero o más publicaciones y aporta su
  archivo y su metadata global a todas ellas.
- **Cuenta (Account)** (existente, Feature 002): es el destino de cero o más publicaciones; su
  plataforma identifica la red social de la publicación.
- **Proyecto (Project)** (existente, Feature 002): agrupa contenidos, cuentas y
  publicaciones; su estado activo/inactivo condiciona qué operaciones se permiten.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El flujo de referencia se completa sin errores: abrir "L4i4"; seleccionar una
  imagen o vídeo ya importado; seleccionar Instagram, TikTok y X; crear tres publicaciones
  sin duplicar el archivo; programar Instagram para una fecha y TikTok para otra; dejar X sin
  programar; ver las tres en la Queue con estados y horarios correctos; personalizar la
  descripción de Instagram sin modificar la metadata global del contenido; reiniciar la
  aplicación y comprobar que todo persiste; cancelar una publicación; y comprobar que sigue
  en la Queue pero ya no está activa.
- **SC-002**: Preparar publicaciones de un contenido para tres cuentas, desde su detalle
  hasta verlas en la Queue, lleva menos de 1 minuto.
- **SC-003**: El 100 % de los intentos de crear o reactivar una publicación activa duplicada
  para la misma pareja contenido + cuenta se rechaza con un aviso claro y sin crear ni
  modificar publicaciones.
- **SC-004**: El 100 % de las publicaciones, relaciones, estados, fechas y overrides
  sobreviven a un reinicio completo, y las fechas se muestran con la misma hora local.
- **SC-005**: Crear publicaciones no aumenta el número de archivos almacenados.
- **SC-006**: Tras editar la metadata global de un contenido, el 100 % de sus publicaciones
  sin override reflejan el nuevo valor y el 100 % de las que tienen override conservan el
  suyo.
- **SC-007**: Ninguna publicación se ejecuta ni cambia de estado automáticamente al llegar su
  hora programada.
- **SC-008**: Con al menos 200 publicaciones en un proyecto, la Queue se muestra y es
  utilizable en menos de 2 segundos.
- **SC-009**: Todos los quality gates existentes siguen pasando y existen tests automatizados
  que cubren al menos: creación de una publicación; creación para múltiples cuentas; relación
  correcta contenido/cuenta/proyecto; rechazo de cuenta de otro proyecto; rechazo de cuenta
  inactiva; rechazo en proyecto inactivo; prevención de duplicados activos; cancelación y
  reactivación; transición `UNSCHEDULED` ↔ `SCHEDULED`; persistencia tras reinicio; metadata
  heredada; overrides de metadata; cambio posterior de metadata global reflejado sin
  override; Queue; y selección múltiple de cuentas en el frontend.

## Assumptions

- El stack, la base de datos local, el sistema de migraciones, el formato de errores, la
  normalización de hashtags y los límites de metadata son los ya establecidos en las
  Features 001–003. La forma concreta de la API y del modelo de datos se decide en
  `/speckit-plan` priorizando simplicidad.
- La regla de duplicados se aplica a nivel de sistema (no solo en la interfaz); el mecanismo
  concreto se decide en `/speckit-plan` eligiendo el más sencillo que la garantice.
- Ante una cuenta en conflicto dentro de una creación múltiple se rechaza toda la operación
  (sin creación parcial); la interfaz evita el caso marcando de antemano las cuentas con
  publicación activa. Es más sencillo y predecible que un resultado parcial.
- La fecha opcional elegida al crear se aplica a todas las publicaciones de esa operación;
  las fechas distintas por cuenta se asignan después, editando cada publicación.
- Desactivar un proyecto o una cuenta no cancela ni desprograma automáticamente sus
  publicaciones; solo restringe las operaciones que preparan ejecución futura (programar y
  reactivar) y la creación. Los efectos sobre la ejecución real se definirán con el
  scheduler.
- Las publicaciones `SCHEDULED` cuya fecha ya pasó permanecen `SCHEDULED` y se marcan como
  vencidas en la interfaz; no existe ninguna transición automática hasta que exista
  publicación real.
- La Queue es una vista por proyecto, sin filtros, búsqueda ni paginación para el volumen
  esperado (centenares de publicaciones por proyecto). La preview reutiliza la del contenido
  (Feature 003), sin generar thumbnails.
- No existe metadata específica por plataforma (p. ej. límites de caracteres de X o
  categorías de YouTube); los overrides usan los mismos campos y límites que el contenido.
- Aplicación local de un único usuario: no se contemplan ediciones concurrentes desde varios
  clientes.
- Fuera de alcance: publicación real, APIs de YouTube, Instagram, TikTok, X, Threads y
  Telegram, OAuth, almacenamiento de tokens, scheduler worker, ejecución automática, retries,
  PublicationAttempt, estados `PUBLISHING`/`PUBLISHED`/`FAILED`, calendario visual, drag &
  drop de calendario, analytics, IA, selección de música, metadata avanzada por plataforma y
  eliminación física de publicaciones.
