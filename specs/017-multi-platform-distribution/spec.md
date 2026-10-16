# Feature Specification: Distribución multiplataforma y presets de destinos

**Feature Branch**: `017-multi-platform-distribution`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "Feature 017 — Multi-platform Distribution & Presets. Convertir `Prepare publications` en un flujo **Distribute** desde un asset: seleccionar varias cuentas (o aplicar un preset), reutilizar description/caption y hashtags comunes, personalizar metadata solo para destinos concretos (Customize), elegir Prepare o Schedule (fecha común) y crear todas las Publications con una única llamada atómica, evolucionando de forma retrocompatible `POST /contents/{id}/publications` (overrides comunes + `targets[account_id]`). Después, un panel de resultado por Publication con `publish-check`, opciones específicas de plataforma (componentes `*PublishOptions` existentes), `PublishNowDialog` y armado individual de auto-publish. Presets solo de destinos, por proyecto, persistidos (`distribution_presets` + `distribution_preset_accounts`). Corregir el bug `taken` (`PUBLISHED` no bloquea). Sin entidad `Distribution`, sin identificador de lote, sin Publish all, sin cambios en scheduler ni publishers, sin opciones de plataforma en `PublicationCreate`, sin truncado automático, sin Republish."

## Contexto

AutoPublisher ya permite, desde el detalle de un asset (`Content`), **Prepare publications**:
elegir varias cuentas activas del proyecto y crear una `Publication` por cuenta, sin fecha
(`UNSCHEDULED`) o con una fecha común (`SCHEDULED`), opcionalmente con `auto_publish_enabled`.
La creación ya es atómica: valida todas las cuentas antes de crear nada, rechaza duplicados y
protege contra concurrencia. Cada `Publication` puede después editarse individualmente
(fecha, `title_override`, `description_override`, `hashtags_override`), revisarse con
`publish-check`, completarse con las opciones específicas de su plataforma, publicarse con
**Publish now** o armarse para publicación automática.

Lo que falta es una experiencia clara de **distribución multiplataforma**:

- hoy no se puede adaptar el texto en el momento de crear: todas las Publications nacen con
  la metadata del Content y hay que editarlas una a una después;
- no hay una vista única que muestre, tras crear, qué destinos están listos y qué le falta a
  cada uno;
- el usuario repite siempre la misma selección de cuentas (p. ej. "Instagram + TikTok +
  YouTube" para vídeos cortos);
- el frontend considera que una Publication `PUBLISHED` bloquea volver a usar esa cuenta con
  el mismo asset, mientras que el backend la trata como histórica (`HISTORY_STATUSES` =
  `CANCELLED`, `PUBLISHED`). Es un bug.

Principios rectores de esta feature:

- **`Publication` sigue siendo la unidad persistente y de ejecución.** Una "distribución" es
  solo el acto de crear varias Publications a la vez; no existe como entidad, no tiene
  identificador de lote y no agrupa nada después de crearse.
- **Se evoluciona lo existente.** Se amplía la creación actual de Publications de forma
  retrocompatible; no se crea un endpoint paralelo ni un modelo universal de post.
- **La metadata efectiva existente es la fuente de verdad.** Los textos comunes y por destino
  se guardan como los overrides que ya existen en `Publication`; lo no personalizado se
  hereda del Content mediante la resolución actual.
- **Las reglas de plataforma no se duplican ni se homogeneizan.** Las opciones específicas
  (privacidad, declaraciones de IA, made for kids, consentimiento de TikTok, alt text…) se
  completan después con los componentes y endpoints existentes; los límites de texto no se
  replican en el frontend ni se aplican truncando.
- **Cada Publication se publica y falla de forma independiente.** No hay Publish all.

## Clarifications

### Session 2026-10-16

- Q: ¿Qué ocurre con un preset que se queda sin cuentas por cambios externos? → A: Crear o editar manualmente exige ≥1 cuenta; un preset existente puede quedar con 0 cuentas si estas dejan de existir. Sigue existiendo, no se elimina automáticamente y aplicarlo selecciona 0 destinos con el aviso vacío correspondiente. Sin lógica nueva de mantenimiento.
- Q: ¿Cómo decide la UI si enviar un override en Common text / Customize? → A: Por dirty state explícito por campo: no modificado → no se envía; modificado y vacío → override vacío; modificado → ese valor exacto. No se basa únicamente en comparar con el Content. `Discard customization` elimina los overrides locales del destino y vuelve a heredar Common/Content.
- Q: ¿Cómo se reutilizan las opciones de plataforma en el panel de resultado? → A: El plan investiga `*PublishOptions`, `PublishNowDialog`, armado de auto-publish y `publish-check`; si alguno está acoplado a su vista actual se propone la extracción mínima, sin duplicar validaciones, llamadas API, reglas ni estado. Sin cambios en publishers ni scheduler.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Distribuir un asset a varias cuentas con texto común (Priority: P1)

Desde el detalle de un asset, el usuario pulsa **Distribute**. Ve las cuentas activas del
proyecto como casillas, marca varias, revisa la description/caption y los hashtags comunes
(prellenados con los del Content), elige **Prepare** (sin fecha) o **Schedule** (una fecha
común) y pulsa el botón final. Se crean todas las Publications de una vez, o ninguna si algo
es inválido.

**Why this priority**: es el núcleo de la feature y sustituye al flujo actual de Prepare
publications; por sí solo ya entrega valor (crear varias Publications con un texto común
adaptado en un único paso).

**Independent Test**: con un proyecto con tres cuentas activas de plataformas distintas y un
asset con descripción y hashtags, abrir Distribute, seleccionar las tres, cambiar la
descripción común, elegir Schedule con una fecha futura y crear; comprobar que existen tres
Publications `SCHEDULED` con la misma fecha y cuya descripción efectiva es la común editada.

**Acceptance Scenarios**:

1. **Given** un asset con descripción "A" y hashtags `#x`, **When** el usuario abre
   Distribute, **Then** la description/caption común aparece prellenada con "A" y los
   hashtags comunes con `#x`.
2. **Given** tres cuentas seleccionadas y los textos comunes sin modificar, **When** el
   usuario elige Prepare y crea, **Then** se crean tres Publications `UNSCHEDULED` sin
   overrides, cuya metadata efectiva es la del Content.
3. **Given** tres cuentas seleccionadas y la descripción común cambiada a "B", **When** el
   usuario crea, **Then** las tres Publications tienen descripción efectiva "B" y el Content
   conserva "A".
4. **Given** Schedule con una fecha futura, **When** el usuario crea, **Then** todas las
   Publications quedan `SCHEDULED` con exactamente esa fecha.
5. **Given** que una de las cuentas seleccionadas se desactivó en otra pestaña antes de
   crear, **When** el usuario crea, **Then** no se crea ninguna Publication y la UI indica
   qué destino debe corregirse.
6. **Given** que no hay ninguna cuenta seleccionada, **When** el usuario intenta crear,
   **Then** la acción no se permite y se indica que debe elegir al menos un destino.
7. **Given** Schedule con una fecha pasada, **When** el usuario crea, **Then** no se crea
   nada y se muestra el error en el campo de fecha.

---

### User Story 2 - Personalizar el texto de un destino concreto (Priority: P1)

En la lista de destinos seleccionados, cada cuenta tiene una acción **Customize** que permite
definir solo para ese destino: título (cuando la plataforma lo usa, hoy YouTube),
description/caption y hashtags. Lo que no se personaliza hereda el texto común o, en su
defecto, el del Content.

**Why this priority**: la distribución multiplataforma real casi siempre necesita algún
ajuste por red (un título para YouTube, un caption más corto para otra); sin esto el usuario
vuelve a editar Publications una a una.

**Independent Test**: seleccionar una cuenta de YouTube y otra de Instagram, personalizar en
YouTube el título y la descripción, dejar Instagram sin personalizar y crear; comprobar que
YouTube usa el título y la descripción personalizados e Instagram la descripción común.

**Acceptance Scenarios**:

1. **Given** un destino YouTube seleccionado, **When** el usuario abre Customize, **Then**
   puede editar el título, que aparece inicialmente con el título efectivo del Content.
2. **Given** un destino de una plataforma que no consume título (Instagram, TikTok, Threads,
   Telegram), **When** el usuario abre Customize, **Then** no se le ofrece campo de título.
3. **Given** descripción común "B" y descripción personalizada "C" en un destino, **When**
   el usuario crea, **Then** ese destino tiene descripción efectiva "C" y el resto "B".
4. **Given** un destino con solo los hashtags personalizados, **When** el usuario crea,
   **Then** ese destino usa sus hashtags y hereda la descripción común.
5. **Given** un destino personalizado que el usuario desmarca, **When** crea, **Then** no se
   envía ni se crea nada para ese destino.
6. **Given** un destino con una personalización inválida (p. ej. un título que excede el
   límite del modelo existente), **When** el usuario crea, **Then** no se crea ninguna
   Publication y el error se asocia a ese destino.
7. **Given** la UI de creación, **When** el usuario la recorre, **Then** en ningún momento
   ve un "título común" que parezca aplicarse a todas las plataformas.

---

### User Story 3 - Ver el estado de cada destino y completarlo desde un único panel (Priority: P1)

Tras crear, el usuario ve un panel de resultado con una fila por Publication creada:
plataforma, cuenta, estado, resultado de `publish-check` (**Ready** o los requisitos
pendientes), las opciones específicas de la plataforma y las acciones existentes (Publish
now, armar auto-publish). Completa lo que falte en cada destino sin salir del panel.

**Why this priority**: sin este panel el usuario no sabe qué destinos pueden publicarse ya y
cuáles necesitan algo (made for kids, consentimiento de TikTok, etc.); es lo que hace usable
la distribución.

**Independent Test**: crear una distribución con un destino que pasa `publish-check` y otro
que necesita una opción de plataforma; comprobar que el panel muestra **Ready** en el
primero y el requisito pendiente en el segundo, completar la opción en el propio panel y ver
que pasa a Ready.

**Acceptance Scenarios**:

1. **Given** una distribución recién creada, **When** se muestra el panel, **Then** hay una
   fila por Publication creada con plataforma, cuenta y estado.
2. **Given** una Publication que cumple sus requisitos, **When** se consulta su
   `publish-check`, **Then** la fila muestra **Ready**.
3. **Given** una Publication de YouTube sin `made_for_kids` definido, **When** se muestra su
   fila, **Then** indica qué falta y ofrece las opciones de YouTube existentes para
   completarlo.
4. **Given** que el usuario completa la opción pendiente desde el panel, **When** se guarda,
   **Then** la fila vuelve a consultar `publish-check` y refleja el nuevo resultado.
5. **Given** una fila Ready, **When** el usuario pulsa Publish now, **Then** se abre el
   diálogo de publicación existente para esa Publication únicamente.
6. **Given** una Publication `SCHEDULED`, **When** el usuario arma auto-publish desde su
   fila, **Then** se usa la edición existente y se aplican las mismas reglas actuales (p.
   ej. los requisitos de TikTok).
7. **Given** el panel, **When** el usuario lo recorre, **Then** no existe ninguna acción
   "Publish all" ni de armado masivo.
8. **Given** una Publication de Telegram, **When** se muestra su fila, **Then** no se
   muestran opciones específicas porque la plataforma no las tiene por Publication.

---

### User Story 4 - Corregir la selección de cuentas ya publicadas (Priority: P1)

Una cuenta que ya publicó este asset (`PUBLISHED`) o cuya Publication se canceló
(`CANCELLED`) puede volver a seleccionarse. Solo las cuentas con una Publication activa del
asset (cualquier estado que no sea histórico) aparecen deshabilitadas, con una explicación
breve.

**Why this priority**: es un bug actual que impide volver a publicar un asset en una cuenta
y deja la UI en desacuerdo con el backend; además es base de Feature 018.

**Independent Test**: con un asset que tiene una Publication `PUBLISHED` en la cuenta A y
otra `SCHEDULED` en la cuenta B, abrir Distribute: A es seleccionable y B aparece
deshabilitada con su motivo.

**Acceptance Scenarios**:

1. **Given** una Publication `PUBLISHED` del asset en la cuenta A, **When** el usuario abre
   Distribute, **Then** A es seleccionable y crear con A tiene éxito.
2. **Given** una Publication `UNSCHEDULED`, `SCHEDULED`, `PUBLISHING`, `FAILED` o
   `AWAITING_USER_ACTION` del asset en la cuenta B, **When** el usuario abre Distribute,
   **Then** B aparece deshabilitada con una explicación breve (ya tiene una publicación
   activa de este asset).
3. **Given** una Publication `CANCELLED` del asset en la cuenta C, **When** el usuario abre
   Distribute, **Then** C es seleccionable.

---

### User Story 5 - Guardar y aplicar presets de destinos (Priority: P2)

El usuario guarda conjuntos de cuentas habituales del proyecto como **presets** con nombre
(p. ej. "Short video" = Instagram + TikTok + YouTube) y los aplica en Distribute para
preseleccionar destinos. Puede listarlos, renombrarlos, cambiar sus cuentas y eliminarlos.

**Why this priority**: ahorra tiempo en el uso repetido, pero la distribución es útil sin
presets.

**Independent Test**: crear el preset "Short video" con tres cuentas, abrir Distribute en un
asset, aplicarlo y comprobar que las tres cuentas quedan seleccionadas; renombrarlo, quitarle
una cuenta y eliminarlo.

**Acceptance Scenarios**:

1. **Given** un proyecto con cuentas, **When** el usuario crea un preset con nombre y al
   menos una cuenta del proyecto, **Then** el preset queda guardado y aparece en la lista de
   presets del proyecto.
2. **Given** un preset existente, **When** el usuario lo aplica en Distribute, **Then** se
   preseleccionan las cuentas del preset que sean utilizables.
3. **Given** un preset con una cuenta desactivada y otra con Publication activa del asset,
   **When** se aplica, **Then** solo se preseleccionan las utilizables y se muestra un
   aviso breve, p. ej. "2 destinations skipped", con el motivo de cada una (inactive /
   already has active publication).
4. **Given** que aplicar un preset omitió cuentas, **When** el usuario continúa, **Then** el
   preset almacenado no se modifica.
5. **Given** un preset llamado "Short video", **When** el usuario intenta crear otro con el
   nombre "short video" en el mismo proyecto, **Then** se rechaza por nombre duplicado.
6. **Given** un preset, **When** el usuario lo renombra o cambia sus cuentas, **Then** los
   cambios se guardan y se reflejan al aplicarlo.
7. **Given** un preset, **When** el usuario lo elimina, **Then** desaparece de la lista y
   las cuentas y Publications no se ven afectadas.
8. **Given** un intento de crear o editar un preset con una cuenta de otro proyecto,
   **When** se guarda, **Then** se rechaza sin guardar cambios.
9. **Given** un preset aplicado, **When** el usuario modifica manualmente la selección,
   **Then** puede añadir o quitar cuentas libremente antes de crear.

---

### Edge Cases

- **Cuenta desactivada o Publication activa creada entre abrir el formulario y crear**: la
  creación completa se rechaza (nada se crea) y la UI marca el destino a corregir; el
  usuario puede desmarcarlo y volver a crear.
- **Override por destino para una cuenta no seleccionada**: se rechaza la creación entera;
  nunca se crea una Publication implícita para esa cuenta.
- **Cuenta repetida en la selección**: se rechaza como hasta ahora.
- **Texto común vaciado por el usuario**: un campo común vacío se trata como override
  explícito vacío, con la misma semántica que ya tiene la edición de Publication (vacío ≠
  heredar). Un campo común que el usuario no modifica no genera override y se hereda del
  Content.
- **Texto que supera el límite de una plataforma pero no el del modelo**: la Publication se
  crea como borrador; `publish-check` muestra después qué falta. Nada se trunca ni se adapta.
- **Requisitos de plataforma incompletos** (made for kids, synthetic media,
  `is_ai_generated`, modo/privacidad/consentimiento de TikTok…): no impiden crear; quedan
  pendientes en el panel de resultado.
- **Asset con archivo no disponible**: se mantiene el comportamiento actual de la creación
  de Publications.
- **Schedule con `auto_publish_enabled` enviado por un cliente existente**: se mantiene el
  comportamiento actual (retrocompatibilidad); la UI de Distribute no lo ofrece como flujo
  principal.
- **Preset cuyas cuentas están todas inactivas o bloqueadas**: aplicarlo no selecciona nada
  y el aviso indica cuántas se omitieron y por qué; no es un error.
- **Cuenta eliminada que formaba parte de un preset**: la relación del preset con esa cuenta
  desaparece con la cuenta (integridad referencial); el preset sigue existiendo.
- **Preset que se queda sin cuentas**: crear o editar manualmente un preset exige al menos
  una cuenta, pero un preset existente PUEDE quedar con cero cuentas si esas cuentas dejan
  de existir después. En ese caso el preset sigue existiendo y no se elimina
  automáticamente; aplicarlo selecciona cero destinos y muestra el aviso vacío
  correspondiente. No hay lógica adicional de mantenimiento.
- **Fallo remoto tras crear** (p. ej. Instagram falla al publicar): solo afecta a esa
  Publication; las demás siguen su ciclo de vida, reintentos e historial como hoy.
- **Usuario cierra el panel de resultado**: las Publications ya existen y siguen accesibles
  desde la cola de publicaciones y el detalle del asset como cualquier otra.

## Requirements *(mandatory)*

### Functional Requirements

#### Creación multi-destino (backend)

- **FR-001**: La creación de Publications desde un Content DEBE seguir realizándose con la
  operación existente, ampliada de forma retrocompatible: toda petición válida hoy DEBE
  seguir produciendo exactamente el mismo resultado.
- **FR-002**: La creación DEBE aceptar overrides comunes opcionales de
  `description_override` y `hashtags_override` que se aplican a todos los destinos que no
  los personalicen. MAY aceptar también `title_override` común si encaja con el modelo
  existente, pero la UI NO DEBE presentarlo.
- **FR-003**: La creación DEBE aceptar overrides opcionales por destino, indexados por
  cuenta, con `title_override`, `description_override` y `hashtags_override`.
- **FR-004**: Para cada campo, el valor por destino DEBE prevalecer sobre el común, y el
  común sobre la herencia del Content. Un campo no enviado (ni común ni por destino) NO
  DEBE generar override y DEBE heredarse mediante la resolución de metadata efectiva
  existente.
- **FR-005**: Los overrides comunes y por destino DEBEN usar los mismos tipos, límites,
  normalización (p. ej. de hashtags) y semántica de vacío explícito que la edición actual de
  Publication.
- **FR-006**: Un override por destino que haga referencia a una cuenta no incluida en la
  selección DEBE provocar el rechazo de toda la creación.
- **FR-007**: La creación DEBE ser todo o nada: antes de persistir se DEBEN validar todas las
  cuentas (existen, pertenecen al proyecto del Content, están activas, no están duplicadas,
  no tienen Publication activa de ese Content) y todos los overrides; si cualquier
  validación falla NO DEBE crearse ninguna Publication.
- **FR-008**: Ante un rechazo, la respuesta DEBE identificar el destino o campo a corregir
  con suficiente precisión para que la UI lo señale (cuenta concreta, campo común o campo de
  un destino concreto).
- **FR-009**: Solo las Publications en estados no históricos DEBEN bloquear una nueva
  Publication del mismo Content y cuenta; `PUBLISHED` y `CANCELLED` NO DEBEN bloquear.
- **FR-010**: Con Prepare, todas las Publications DEBEN crearse `UNSCHEDULED`; con Schedule,
  todas DEBEN crearse `SCHEDULED` con la misma fecha, con las reglas de fecha actuales.
- **FR-011**: La creación NO DEBE aceptar opciones específicas de plataforma (privacidad,
  declaraciones, modo TikTok, alt text, interacciones…), ni fechas distintas por destino.
- **FR-012**: La ausencia de opciones específicas de plataforma NO DEBE impedir crear una
  Publication.
- **FR-013**: La creación NO DEBE ejecutar comprobaciones remotas contra plataformas.
- **FR-014**: El soporte actual de `auto_publish_enabled` en la creación DEBE mantenerse sin
  cambios de comportamiento.
- **FR-015**: NO DEBE persistirse ninguna entidad de distribución, agrupación ni
  identificador de lote; el resultado son Publications normales e independientes.

#### Flujo Distribute (frontend)

- **FR-016**: La acción "Prepare publications" del detalle de un asset DEBE pasar a llamarse
  **Distribute** y abrir el flujo de distribución. Las tarjetas de la Asset Library NO DEBEN
  rediseñarse. Los textos de la UI que remiten a "Prepare publications" DEBEN actualizarse.
- **FR-017**: La sección **Destinations** DEBE mostrar las cuentas activas del proyecto como
  casillas, con su plataforma y su identificador.
- **FR-018**: Una cuenta con una Publication activa (no histórica) del Content DEBE aparecer
  deshabilitada con una explicación breve; la determinación de "activa" DEBE coincidir con
  la semántica de estados históricos del backend (`PUBLISHED` y `CANCELLED` no bloquean).
- **FR-019**: La sección **Common text** DEBE permitir editar description/caption y hashtags,
  prellenados con los valores actuales del Content. Solo los campos comunes que el usuario
  modifique DEBEN enviarse como override común.
- **FR-020**: La UI NO DEBE mostrar un título común. Para destinos YouTube el título efectivo
  por defecto DEBE ser el del Content, editable solo mediante Customize.
- **FR-021**: Cada destino seleccionado DEBE ofrecer **Customize**, que permite editar solo:
  título (únicamente en plataformas que lo consumen; hoy YouTube), description/caption y
  hashtags. Los campos no modificados DEBEN heredar el valor común o del Content. Customize
  NO DEBE incluir privacidad, declaraciones legales, modo TikTok, alt text, interacciones ni
  otras opciones de publisher.
- **FR-022**: La UI DEBE indicar visualmente qué destinos tienen personalización y permitir
  descartarla (**Discard customization**), lo que elimina los overrides locales de ese
  destino y vuelve a heredar Common/Content.
- **FR-022a**: Para cada campo de Common text y de Customize, la UI DEBE registrar
  explícitamente si el usuario lo editó (dirty state), sin depender únicamente de comparar
  el valor final con el del Content:
  - campo no modificado → no se envía override;
  - campo modificado y dejado vacío → se envía override vacío explícito;
  - campo modificado → se envía exactamente ese valor.
- **FR-023**: La sección **When** DEBE ofrecer únicamente Prepare (sin fecha) y Schedule (una
  fecha común).
- **FR-024**: El botón final DEBE crear todas las Publications mediante una única petición
  atómica y DEBE estar deshabilitado mientras no haya ningún destino seleccionado o la
  petición esté en curso.
- **FR-025**: Si la creación se rechaza, la UI DEBE conservar todo lo introducido y señalar el
  destino o campo a corregir.
- **FR-026**: La UI NO DEBE truncar, recortar ni adaptar automáticamente textos, ni replicar
  límites de longitud propios de cada plataforma.

#### Panel de resultado

- **FR-027**: Tras una creación correcta, la UI DEBE mostrar un panel con una fila por
  Publication creada que incluya plataforma, cuenta, estado y el resultado de
  `publish-check` existente: **Ready** o la lista de requisitos pendientes.
- **FR-028**: Cada fila DEBE ofrecer las opciones específicas de su plataforma reutilizando
  los componentes y endpoints existentes, sin redefinir sus contratos; las plataformas sin
  opciones por Publication (Telegram) no muestran sección de opciones.
- **FR-029**: Tras guardar opciones o cambios en una fila, su resultado de `publish-check`
  DEBE actualizarse.
- **FR-030**: Cada fila DEBE ofrecer Publish now mediante el diálogo existente y, cuando
  aplique, armar o desarmar auto-publish mediante la edición existente, de forma individual.
- **FR-031**: NO DEBE existir "Publish all" ni armado masivo de auto-publish.
- **FR-031a**: El plan DEBE investigar los componentes actuales (`*PublishOptions`,
  `PublishNowDialog`, edición/armado de auto-publish y la presentación de `publish-check`)
  para reutilizarlos en el panel de resultado. Si alguno está demasiado acoplado a su vista
  actual, se DEBE proponer la extracción mínima necesaria, sin duplicar validaciones,
  llamadas API, reglas de plataforma ni estado de negocio.

#### Presets de destinos

- **FR-032**: El sistema DEBE permitir crear, listar, editar (nombre y cuentas) y eliminar
  presets de destinos por proyecto.
- **FR-033**: Un preset DEBE contener únicamente un nombre y un conjunto de cuentas del mismo
  proyecto; NO DEBE almacenar textos, títulos, hashtags, privacidad, fechas, opciones de
  plataforma, declaraciones, consentimientos ni modo TikTok.
- **FR-034**: El nombre de un preset DEBE ser obligatorio y único dentro del proyecto sin
  distinguir mayúsculas/minúsculas ni espacios sobrantes, de forma coherente con la unicidad
  de nombres existente en el proyecto.
- **FR-035**: Crear o editar un preset con una cuenta inexistente, de otro proyecto o
  repetida DEBE rechazarse sin guardar cambios. Un preset DEBE contener al menos una cuenta
  al crearse o editarse.
- **FR-036**: Los presets DEBEN persistirse en el backend con integridad referencial con
  proyectos y cuentas: eliminar un proyecto elimina sus presets; eliminar una cuenta la
  elimina de los presets que la contengan. NO DEBEN usarse almacenamiento del navegador ni
  presets globales.
- **FR-037**: Aplicar un preset en Distribute DEBE preseleccionar solo las cuentas que estén
  activas, pertenezcan al proyecto y sean seleccionables para ese Content, y DEBE mostrar un
  aviso breve con el número de destinos omitidos y el motivo de cada uno (inactive / already
  has active publication). Aplicarlo NO DEBE modificar el preset almacenado.
- **FR-038**: La gestión de presets DEBE ser sencilla (lista, crear, editar, eliminar) y
  accesible desde el flujo Distribute, incluida la opción de guardar la selección actual
  como preset.

#### Invariantes

- **FR-039**: El scheduler, los publishers, `publish-check`, los attempts, los reintentos y el
  historial NO DEBEN cambiar su comportamiento. Una distribución programada se procesa como
  Publications `SCHEDULED` individuales.
- **FR-040**: Un fallo remoto de una Publication NO DEBE modificar ninguna otra Publication
  creada en la misma distribución.

### Key Entities *(include if feature involves data)*

- **Publication** (existente, sin cambios de modelo): unidad persistente y de ejecución.
  Enlaza un Content con una Account; sus `title_override`, `description_override` y
  `hashtags_override` almacenan el texto común y/o personalizado de la distribución.
- **Content** (existente): asset de entrada de Distribute; proporciona la metadata base
  (`title`, `description`, `hashtags`) que se hereda cuando no hay override.
- **Account** (existente): destino seleccionable; solo las activas del proyecto del Content.
- **Distribution Preset** (nuevo): conjunto reutilizable con nombre de cuentas de un
  proyecto. Atributos: proyecto, nombre, clave normalizada del nombre (única por proyecto),
  fechas de creación y actualización.
- **Distribution Preset Account** (nuevo): pertenencia de una cuenta a un preset; par único
  preset–cuenta, eliminado en cascada con el preset o con la cuenta.
- **Distribución** (concepto, no entidad): la creación atómica de varias Publications desde
  un Content en una única acción; no se persiste.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede preparar o programar un asset en 3 cuentas de plataformas
  distintas, con un texto común y un título personalizado para YouTube, en menos de 1 minuto
  y con una sola acción de creación.
- **SC-002**: En el 100 % de las creaciones rechazadas no se crea ninguna Publication, y la
  UI señala el destino o campo a corregir.
- **SC-003**: Tras crear, el usuario identifica en una única vista, sin navegar, qué destinos
  están Ready y qué le falta a cada uno de los demás.
- **SC-004**: El usuario puede completar las opciones pendientes de cualquier destino y
  publicarlo individualmente sin salir del panel de resultado.
- **SC-005**: Una cuenta cuya única Publication del asset está `PUBLISHED` o `CANCELLED` es
  siempre seleccionable (0 falsos bloqueos).
- **SC-006**: Aplicar un preset selecciona los destinos habituales en un solo clic, y las
  cuentas no utilizables se omiten con aviso sin bloquear el flujo.
- **SC-007**: Todos los clientes y tests existentes de creación de Publications siguen
  funcionando sin modificaciones de comportamiento.
- **SC-008**: Ningún texto se trunca o adapta automáticamente: la metadata efectiva de cada
  Publication creada coincide exactamente con lo introducido o heredado.

## Testing

Se sigue la política de verificación de CLAUDE.md. Esta feature no toca publishers ni
scheduler, por lo que NO se ejecutan regresiones de esos subsistemas por rutina.

**Backend** (conjunto pequeño):

- Creación de Publications, test parametrizado: sin overrides; override común; override por
  destino; destino sobre común.
- Atomicidad: un destino inválido → ninguna Publication creada.
- Override por destino para una cuenta no seleccionada → rechazo.
- Presets: CRUD básico (create/list/update/delete) en pocos tests; cuenta de otro proyecto
  rechazada.

**Frontend** (conjunto pequeño):

- Selección de destinos.
- Aplicar preset (incluido aviso de omitidos).
- Customize de un destino.
- Prepare / Schedule.
- Panel de resultado con al menos un Ready y un requisito pendiente.
- Regresión: `PUBLISHED` no bloquea la selección.

No se prueban todas las combinaciones plataforma × estado. Durante la implementación solo
tests dirigidos; antes del PR, checks estáticos una sola vez; suites completas solo en la CI
del PR.

## Relación con Feature 018

Feature 017 deja como base para una futura Republish:

- Distribute recibe un Content como entrada y puede recibir valores iniciales de texto común
  y por destino;
- `Publication` sigue siendo la unidad persistente;
- los overrides pueden proporcionarse por destino;
- `PUBLISHED` no bloquea otra distribución;
- los presets seleccionan destinos.

Republish (prellenar Distribute desde una Publication anterior) NO se implementa aquí.

## Fuera de alcance

- Entidad `Distribution`, agrupación persistente de Publications o identificador de lote.
- Publish all y armado masivo de auto-publish como flujo principal.
- Fechas u horarios distintos por destino en la creación.
- Cambios en el scheduler o en los publishers.
- Preflight remoto antes de crear.
- Opciones específicas de plataforma en la creación.
- Truncado o adaptación automática de texto; duplicación de límites de plataforma en el
  frontend.
- Modelo universal de post.
- Presets de metadata o configuración; presets globales.
- Republish (Feature 018).
- Rediseño global de la Asset Library.
- Distribución de publicaciones de solo texto (sin Content): su flujo actual no cambia.

## Assumptions

- Hoy solo YouTube consume el título de forma significativa; la decisión de qué plataformas
  muestran el campo de título en Customize se basa en ese hecho y puede revisarse si otra
  plataforma empieza a usarlo.
- La resolución de metadata efectiva existente (override → Content) se mantiene; el texto
  común se guarda como override en cada Publication, no en el Content.
- Si el usuario no modifica un campo común, no se crean overrides: las Publications siguen
  reflejando cambios posteriores de la metadata del Content, como hoy.
- Los presets se gestionan desde el flujo Distribute (sin pantalla de administración
  independiente) para mantener la UI sencilla.
- La unicidad del nombre de preset sigue el mismo patrón de normalización ya usado para
  nombres de proyecto (`name_key`).
- El panel de resultado vive en el contexto del detalle del asset; cerrarlo no afecta a las
  Publications, que siguen visibles en la cola.
- El límite actual de cuentas por petición se mantiene.
- Desarmar/armar auto-publish por fila usa exactamente las reglas actuales, incluidos los
  requisitos de TikTok; no se añade lógica para saltarlos.
