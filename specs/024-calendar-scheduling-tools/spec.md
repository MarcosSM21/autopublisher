# Feature Specification: Calendar & Scheduling Power Tools

**Feature Branch**: `024-calendar-scheduling-tools`

**Created**: 2026-10-26

**Status**: READY FOR PLANNING

**Input**: User description: "Feature 024 — Calendar & Scheduling Power Tools. Convertir Calendar
de una vista principalmente de consulta en una superficie operativa para reprogramar
publicaciones existentes de forma rápida y segura (Quick Reschedule + drag entre días en la
week view desktop), reutilizando el `ActionDialog` existente, haciendo atómica la actualización
backend frente al claim del scheduler y preservando la arquitectura actual de Calendar,
scheduler y publishing."

## Regla de producto

**View → understand → reschedule quickly**, sin romper los workflows existentes.

La feature amplía el Calendar existente. NO lo convierte en un calendario horario completo, ni
en un editor de publicaciones, ni en una herramienta bulk, ni en un sistema de recurrencias.

**Sustitución explícita**: esta feature sustituye el contrato de Feature 019 (FR-066) que
definía Calendar como "de solo lectura: sin drag & drop". El resto de FR-066–FR-069 (Calendar
dentro de Posts, por proyecto, semana de lunes a domingo, previous/Today/next, rango, zona
horaria, estados mostrados, sin Drafts ni Cancelled, sin backend específico) sigue vigente.

## Contexto (estado actual verificado en el código)

Contexto para la planificación; el comportamiento exigido está en Requirements.

- **Ruta y datos**: `/p/:projectId/posts[/:postId]?view=calendar&week=YYYY-MM-DD`. Calendar no
  tiene fuente propia: usa la lista de Posts del proyecto (`GET /api/projects/{id}/publications`),
  con el mismo poller (2 s mientras algo está Publishing, 15 s mientras hay Posts armados
  esperando, ninguno en otro caso) y los mismos filtros (búsqueda y destino).
- **Agrupación**: cada Post se sitúa en el día local de su "momento" (FR-069 de 019:
  `published_at`, `scheduled_at` o el inicio/fin del último intento según el estado) y se
  ordena por hora. Drafts y Cancelled nunca aparecen.
- **Responsive**: ≥1280 px, week view de 7 columnas (una sección por día, lista ordenada; sin
  grid horario). <1280 px, agenda que solo muestra los días con Posts.
- **Item**: cada Post es un único enlace al Post detail (hora, título, destino, estado), con
  `data-detail-id` para devolver el foco al cerrar el detalle. El detalle se abre como Drawer
  desde `md` y como página completa en móvil.
- **Fuente de verdad de la fecha**: `scheduled_at` de la publicación, guardado en UTC al minuto.
  No se persiste zona horaria: el frontend usa la zona del navegador.
- **Programar hoy**: el `ActionDialog` del Post detail ya ofrece *Reschedule* (Missed, Failed)
  y *Edit schedule* (Scheduled), con `datetime-local`, zona horaria del navegador, validación
  "en el futuro", declaración TikTok para Direct Post, Dialog desde `md` y Sheet en móvil, y
  envía `PATCH /api/publications/{id}` con `{scheduled_at, auto_publish_enabled: true}`.
  Programar siempre es automático (R4 de 019); `scheduled_manual` solo existe como legacy.
- **Carrera conocida**: el PATCH lee la publicación sin bloqueo y escribe después. Si el claim
  atómico del scheduler la pasa a `publishing` entre esa lectura y ese commit, el PATCH puede
  sobrescribir `publishing` con `scheduled`. El orden contrario (PATCH primero, claim después)
  ya es seguro: el claim vuelve a comprobar estado, consentimiento y ventana.

## Clarifications

### Session 2026-10-26 (decisiones del brief)

- Q: ¿El drop persiste directamente? → A: No. El drop solo abre el `ActionDialog` existente
  precargado con la nueva fecha; nada cambia en backend hasta confirmar.
- Q: ¿El drag cambia la hora? → A: No. Cambia el día y conserva la hora local original.
- Q: ¿Qué estados son draggable? → A: Solo `scheduled_automatic` y `scheduled_paused`.
- Q: ¿Qué pasa con un `scheduled_manual` legacy reprogramado? → A: Pasa al flujo automático
  vigente (`auto_publish_enabled: true`), como hace hoy `ActionDialog`.
- Q: ¿Bloqueo por proximidad ("no reprogramar a menos de X minutos")? → A: No. Se puede
  reprogramar mientras el backend lo considere editable; si el claim gana, 409.
- Q: ¿Versionado optimista / ETag? → A: No en MVP. Entre reschedules concurrentes gana la
  última escritura con éxito.
- Q: ¿Endpoint nuevo? → A: No, salvo necesidad real demostrada en planning. Se reutiliza el
  PATCH existente y su contrato.

### Session 2026-10-26 (correcciones finales)

- Q: ¿FR-042 (resúmenes "Next"/"Up next") entra en 024? → A: Sí. Es coherencia de datos tras
  una operación existente, no información ni funcionalidad nueva; cómo refrescarlos se decide
  en planning.
- Q: ¿Se corrige la carrera análoga de `POST /cancel`? → A: No. Queda fuera de 024 y
  documentada en Assumptions para hardening posterior. 024 solo corrige el PATCH.
- Q: ¿Qué se precarga si la fecha actual de un Scheduled ya no es futura? → A: Nada. Se precarga
  `scheduled_at` solo si es estrictamente futuro; si no, el diálogo abre vacío y exige una fecha
  futura. Nunca una fecha artificial (p. ej. "ahora + X").
- Q: ¿Título y semántica del diálogo? → A: Los existentes. Scheduled (`scheduled_automatic`,
  `scheduled_paused`, `scheduled_manual`) → *Edit schedule*; Missed / Failed → *Reschedule*. Un
  drop de un Scheduled abre *Edit schedule* con el nuevo datetime precargado. Sin títulos ni copy
  específicos de Calendar.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Quick Reschedule desde Calendar (Priority: P1)

El usuario ve en Calendar un Post que quiere mover. Sin abrir antes el Post detail, usa la
acción de scheduling de ese Post (*Edit schedule* si está programado, *Reschedule* si está
Missed o Failed), elige fecha y hora en el diálogo de scheduling de siempre y
confirma. El Post aparece en su nueva fecha.

**Why this priority**: es el método operativo universal (desktop, agenda, móvil, teclado,
lector de pantalla) y la base sobre la que se apoya el drag. Por sí solo ya entrega el
objetivo "reschedule quickly".

**Independent Test**: en week view y en agenda, activar la acción de un Post reprogramable
con ratón, teclado y táctil; elegir una fecha futura; confirmar; comprobar que el Post se
muestra en la nueva fecha y que el backend la ha guardado armada.

**Acceptance Scenarios**:

1. **Given** un Post `scheduled_automatic` con fecha futura visible en Calendar, **When** el
   usuario activa *Edit schedule*, **Then** se abre el diálogo existente *Edit schedule* (Dialog
   desde `md`, Sheet en móvil) con la fecha actual del Post precargada y la zona horaria del
   navegador visible.
2. **Given** el diálogo abierto, **When** el usuario elige una fecha futura y confirma,
   **Then** la nueva fecha queda guardada con publicación automática, el diálogo se cierra y
   Calendar muestra el Post en su nuevo día y hora sin dejar rastro en el día anterior.
3. **Given** un Post `missed` o `failed`, **When** el usuario activa *Reschedule*, **Then** se
   abre el diálogo *Reschedule* sin fecha precargada y exige elegir una futura.
4. **Given** un Post `scheduled_automatic` o `scheduled_paused` cuya fecha ya llegó pero aún
   está en su ventana automática, **When** el usuario activa *Edit schedule*, **Then** el diálogo
   se abre sin fecha precargada y exige elegir una futura.
5. **Given** un Post `needs_review`, `needs_action`, `publishing` o `published`, **When** el
   usuario mira su item en Calendar, **Then** no se ofrece acción de scheduling y el item sigue
   abriendo el Post detail.
6. **Given** un Post de TikTok Direct Post, **When** el usuario reprograma, **Then** el
   diálogo exige la declaración TikTok antes de confirmar, igual que hoy en Post detail.
7. **Given** el diálogo abierto, **When** el usuario elige una fecha pasada, **Then** ve el
   error inline de siempre y no se envía nada.
8. **Given** un usuario de teclado o lector de pantalla, **When** recorre Calendar, **Then**
   cada Post reprogramable tiene un control de scheduling alcanzable, con nombre accesible que
   identifica el Post, separado del enlace al detalle.

---

### User Story 2 — Arrastrar un Post a otro día (Priority: P2)

En la week view de escritorio, el usuario arrastra un Post programado de un día a otro de la
semana visible. Al soltarlo se abre el mismo diálogo *Edit schedule*, precargado con el día
destino y la hora original; el usuario revisa (o ajusta la hora) y confirma.

**Why this priority**: acelera el caso más frecuente (mover días) pero es complementario: todo
lo que hace ya es posible con Quick Reschedule.

**Independent Test**: con ≥1280 px, arrastrar un Post `scheduled_automatic` del martes 18:30 al
jueves; comprobar el feedback de targets, que se abre el diálogo con jueves 18:30, que nada
cambia hasta confirmar y que tras confirmar el Post está en el jueves.

**Acceptance Scenarios**:

1. **Given** la week view y un Post `scheduled_automatic` el martes 18:30, **When** el usuario
   lo arrastra, **Then** el Post arrastrado queda claramente identificado y los días válidos e
   inválidos se distinguen por algo más que el color.
2. **Given** el arrastre en curso, **When** suelta sobre el jueves de la misma semana,
   **Then** se abre el diálogo *Edit schedule* precargado con jueves 18:30 (hora local) y el
   backend no ha cambiado.
3. **Given** el diálogo abierto tras el drop, **When** el usuario cancela, **Then** el Post
   sigue en el martes y nada se ha guardado.
4. **Given** el diálogo abierto tras el drop, **When** cambia la hora y confirma, **Then** se
   guarda la fecha y hora elegidas en el diálogo.
5. **Given** un Post a las 18:30 y son las 19:00 de hoy, **When** el usuario lo arrastra,
   **Then** hoy (y cualquier día pasado) se muestra como target inválido y soltar ahí no abre
   el diálogo ni cambia nada.
6. **Given** un Post arrastrado, **When** lo suelta sobre su mismo día, **Then** no ocurre
   nada (sin diálogo, sin petición).
7. **Given** un Post `scheduled_manual`, `missed`, `failed`, `needs_review`, `needs_action`,
   `publishing` o `published`, **When** el usuario intenta arrastrarlo, **Then** no se puede
   arrastrar (sin feedback de drag) y, si corresponde, sigue teniendo su acción de scheduling
   (*Edit schedule* o *Reschedule*).
8. **Given** la week view con drag disponible, **When** el usuario hace clic o activa con
   teclado un item draggable, **Then** se abre el Post detail exactamente como hoy.

---

### User Story 3 — Reprogramar sin riesgo frente al scheduler (Priority: P1)

El usuario reprograma un Post que justo está llegando a su hora. O bien su cambio se guarda y
el Post ya no se publica a la hora antigua, o bien el scheduler ya lo había empezado a publicar
y el usuario recibe un rechazo claro; nunca queda un Post "programado" mientras se está
publicando.

**Why this priority**: es un requisito de corrección. El drag hace mucho más probable
reprogramar Posts de hoy, justo dentro de su ventana automática.

**Independent Test**: test backend que fuerza los dos órdenes posibles entre el reschedule y
el claim del scheduler y verifica el resultado de cada uno, más un test de regresión del lost
update.

**Acceptance Scenarios**:

1. **Given** un Post armado dentro de su ventana, **When** el reschedule se confirma antes que
   el claim, **Then** la nueva fecha queda guardada y el scheduler no lo inicia por la fecha
   antigua.
2. **Given** un Post armado dentro de su ventana, **When** el claim del scheduler gana,
   **Then** el Post queda `publishing`, el reschedule responde 409 con el error existente de
   "no editable" y el estado `publishing` y su intento en curso no se modifican.
3. **Given** el claim ocurre entre la lectura y la escritura de un reschedule, **When**
   termina el reschedule, **Then** responde 409 y no sobrescribe `publishing` (sin lost update).
4. **Given** dos reschedules del mismo Post casi simultáneos, **When** ambos son válidos,
   **Then** ambos terminan sin error y prevalece el último guardado.

---

### Edge Cases

- **Viernes → lunes siguiente**: el lunes siguiente no está en la semana visible; el drag solo
  admite días de la semana mostrada. Se usa Quick Reschedule (o se navega de semana y se usa
  Quick Reschedule). Viernes → lunes de la misma semana es un día pasado salvo que la semana
  sea futura: entonces es un target válido.
- **Cambio de mes dentro de la semana visible** (p. ej. jueves 30 oct → domingo 2 nov): válido;
  la fecha precargada es el día destino con la hora original.
- **Hoy con hora ya pasada**: hoy es target inválido; Quick Reschedule permite elegir una hora
  futura de hoy.
- **Scheduled cuya fecha ya no es futura** (armado dentro de su ventana, aún sin reclamar):
  Quick Reschedule abre *Edit schedule* sin fecha precargada y exige una futura; nunca se
  propone una fecha artificial. Si el scheduler lo reclama antes de confirmar → 409. Su drag
  sigue las reglas normales (destino válido solo si día + hora original es futuro).
- **Post que pasa a Publishing con el diálogo abierto**: confirmar da 409; el diálogo muestra
  el error, la lista se recarga y Calendar muestra el Post como Publishing.
- **Automatización global en pausa**: un `scheduled_paused` es reprogramable y draggable; el
  diálogo muestra el aviso existente de pausa; tras confirmar sigue `scheduled_paused`.
- **`scheduled_manual` legacy**: Quick Reschedule sí, con *Edit schedule* (queda automático
  tras confirmar); drag no.
- **Failed / Missed**: Quick Reschedule sí, con *Reschedule* y sin fecha precargada; drag no.
  Un Failed con resultado incierto se muestra como `needs_review` y queda bloqueado.
- **Declaración TikTok obsoleta** (`tiktok_consent_stale`): el diálogo pide confirmar de nuevo
  la declaración, como hoy.
- **Proyecto o cuenta inactivos, media no disponible, problema de armado**: el diálogo muestra
  el error existente; nada se guarda; Calendar se resincroniza.
- **El polling cambia o elimina el Post durante el arrastre**: si al soltar el Post ya no
  existe o ya no es draggable, el drop se ignora; si el diálogo llega a abrirse, el backend
  sigue siendo la autoridad al confirmar.
- **Filtro activo que deja de incluir el Post tras reschedule**: no aplica a los filtros
  actuales (búsqueda y destino no dependen de la fecha); si el Post sale de la semana visible,
  simplemente deja de verse en ella y el usuario recibe confirmación de la nueva fecha.
- **Post que se mueve a otra semana vía Quick Reschedule**: desaparece de la semana visible,
  sin elemento fantasma; el foco no se pierde.
- **Títulos o nombres largos**: el control de Quick Reschedule y el feedback de drag no se solapan ni
  desbordan las columnas estrechas de la week view.
- **Drag cancelado** (Escape o soltar fuera de un día): no ocurre nada y el feedback desaparece.
- **Mismo día**: no-op, sin diálogo ni petición.
- **Zona horaria y DST**: la hora conservada es la hora local de pared del navegador. Si la
  hora no existe ese día (salto de primavera) o es ambigua (otoño), se precarga la
  interpretación normalizada del navegador y el diálogo la muestra legible antes de confirmar.
- **Doble confirmación**: un doble clic al confirmar nunca envía dos peticiones (garantía
  existente del diálogo).

## Requirements *(mandatory)*

### Matriz de estados (contrastada con el código actual)

Derivada de `ensure_editable` / `update_publication` (backend) y `display_state`.

| display_state | Backend hoy permite cambiar `scheduled_at` | Quick Reschedule (diálogo) | Drag | Fecha precargada (Quick) |
|---|---|---|---|---|
| `scheduled_automatic` | Sí | Sí — *Edit schedule* | **Sí** | Su fecha actual si es estrictamente futura; si no, ninguna |
| `scheduled_paused` | Sí | Sí — *Edit schedule* | **Sí** | Su fecha actual si es estrictamente futura; si no, ninguna |
| `scheduled_manual` (legacy) | Sí | Sí — *Edit schedule* (queda automático) | No | Su fecha actual si es estrictamente futura; si no, ninguna |
| `missed` | Sí (sigue `scheduled`, fecha pasada) | Sí — *Reschedule* | No | Ninguna |
| `failed` (resultado determinado) | Sí (vuelve a `scheduled`) | Sí — *Reschedule* | No | Ninguna |
| `needs_review` | No (409 `check_result_first`) | No | No | — |
| `needs_action` | No (409 `publication_not_editable`) | No | No | — |
| `publishing` | No (409 `publication_not_editable`) | No | No | — |
| `published` | No (409 `publication_not_editable`) | No | No | — |
| `cancelled` | No (409 `publication_cancelled`) | No aparece en Calendar | No | — |
| `draft` | Sí | No aparece en Calendar | No | — |

Un drop válido de un Post draggable abre siempre *Edit schedule* con el datetime resultante
precargado. La matriz de la UI es solo de presentación: el backend sigue siendo la autoridad.

### Functional Requirements — Quick Reschedule

- **FR-001**: Calendar DEBE ofrecer una acción de scheduling ("Quick Reschedule") para cada
  Post visible cuyo estado sea `scheduled_automatic`, `scheduled_paused`, `scheduled_manual`,
  `missed` o `failed`, tanto en week view como en agenda. La acción usa la semántica y la
  etiqueta existentes: *Edit schedule* para los tres `scheduled_*` y *Reschedule* para `missed`
  y `failed`.
- **FR-002**: Calendar NO DEBE ofrecer esa acción para `needs_review`, `needs_action`,
  `publishing` ni `published`.
- **FR-003**: La acción DEBE abrir el diálogo de scheduling existente del Post detail (la misma
  lógica y componente, con su título existente: *Edit schedule* o *Reschedule*); NO DEBE existir
  un segundo formulario de scheduling ni títulos o copy específicos de Calendar. El diálogo conserva: campo de fecha y hora
  local, zona horaria del navegador, vista previa legible, validación "en el futuro",
  declaración TikTok cuando aplique, aviso de automatización en pausa, Dialog desde `md` y
  Sheet en móvil, protección frente a doble envío y mapeo de errores existente.
- **FR-004**: Para `scheduled_automatic`, `scheduled_paused` y `scheduled_manual` el diálogo DEBE
  precargar el `scheduled_at` actual solo si es estrictamente futuro; si no lo es, DEBE abrirse
  sin fecha y exigir una futura. Para `missed` y `failed` DEBE abrirse siempre sin fecha. NO DEBE
  precargarse nunca una fecha artificial (p. ej. "ahora + X").
- **FR-005**: Confirmar DEBE enviar el cambio con el contrato actual (nueva fecha y publicación
  automática activada). Un `scheduled_manual` legacy reprogramado pasa así a automático; no se
  crea semántica nueva para el modo manual.
- **FR-006**: El control de Quick Reschedule DEBE ser un control hermano del enlace al detalle (o un
  menú accesible), nunca un control interactivo anidado dentro del enlace.
- **FR-007**: Las acciones existentes del Post detail (*Edit schedule*, *Reschedule*, *Publish
  now*, *Move to drafts*, etc.) DEBEN seguir comportándose exactamente igual.

### Functional Requirements — Drag & drop

- **FR-010**: El drag DEBE existir solo en la week view (≥1280 px). NO DEBE existir en agenda,
  en móvil ni como interacción táctil.
- **FR-011**: Solo los Posts `scheduled_automatic` y `scheduled_paused` DEBEN ser arrastrables.
  El resto no inicia ningún arrastre.
- **FR-012**: Los únicos destinos son los 7 días de la semana visible. NO hay destinos por
  hora, ni resize, ni arrastre vertical con significado horario, ni navegación de semana
  durante el arrastre.
- **FR-013**: La fecha resultante DEBE ser el día destino con la hora local de pared original
  del Post (p. ej. martes 18:30 → jueves 18:30).
- **FR-014**: Un día es destino inválido si la fecha resultante no es estrictamente futura en
  el momento del arrastre. Soltar en un destino inválido NO DEBE abrir el diálogo ni cambiar
  nada.
- **FR-015**: Soltar sobre el mismo día del Post NO DEBE abrir el diálogo ni enviar petición.
- **FR-016**: Soltar sobre un día válido distinto DEBE abrir el diálogo *Edit schedule* de
  FR-003 precargado con la fecha resultante, editable. El backend NO DEBE cambiar hasta que el usuario confirme;
  cancelar el diálogo deja todo como estaba.
- **FR-017**: Durante el arrastre: el Post arrastrado DEBE quedar identificado; los destinos
  válidos DEBEN resaltarse y los inválidos distinguirse; la distinción NO DEBE depender solo
  del color; el movimiento DEBE ser mínimo y respetar `prefers-reduced-motion`.
- **FR-018**: Cancelar el arrastre (Escape, soltar fuera de un día) DEBE limpiar todo el
  feedback sin efectos.
- **FR-019**: Si al soltar el Post ya no existe en la lista o ya no es arrastrable (p. ej. por
  el polling), el drop DEBE ignorarse.
- **FR-020**: El drag NO DEBE romper el item: clic y activación por teclado siguen abriendo el
  Post detail, `data-detail-id` y la devolución de foco al cerrar el detalle se mantienen, y
  arrastrar el enlace no debe producir navegación ni arrastrar su URL como dato.
- **FR-021**: El drag DEBE implementarse con capacidades nativas del navegador y sin añadir
  una librería de drag & drop.

### Functional Requirements — Backend y concurrencia

- **FR-030**: La actualización de una publicación (`PATCH /api/publications/{id}`) DEBE comprobar su editabilidad y escribir
  sus cambios de forma atómica respecto al claim del scheduler y a cualquier otra transición
  de estado: ningún PATCH puede persistir cambios sobre una publicación que, en el momento de
  escribir, ya no es editable.
- **FR-031**: Si el reschedule gana: la nueva fecha queda guardada y el scheduler ya no puede
  iniciar la publicación por la fecha anterior (garantía actual del claim, que se mantiene).
- **FR-032**: Si el claim gana: la publicación queda `publishing`, el reschedule responde 409
  con el código existente (`publication_not_editable`) y el estado `publishing`, el intento en
  curso y el resto de columnas no se modifican.
- **FR-033**: Dos reschedules concurrentes válidos DEBEN terminar ambos sin error, prevaleciendo
  la última escritura con éxito. Sin versionado optimista ni ETag.
- **FR-034**: NO DEBE añadirse un bloqueo temporal arbitrario ("no reprogramar a menos de X
  minutos"): se puede reprogramar mientras el backend considere editable el Post.
- **FR-035**: DEBEN preservarse sin cambios: el ciclo e intervalo del scheduler, la ventana
  automática, el claim atómico, los intentos, las reglas de consentimiento/armado (cambiar la
  fecha sin consentimiento desarma), las validaciones de fecha futura, proyecto/cuenta activos,
  media disponible y problemas de armado por plataforma, y el contrato de request/response y
  de códigos de error del PATCH.
- **FR-036**: NO DEBE crearse un endpoint nuevo, un modelo nuevo ni una migración, salvo que
  planning demuestre una necesidad real y se apruebe explícitamente.

### Functional Requirements — Refresco y errores

- **FR-040**: Tras un reschedule con éxito, Calendar DEBE mostrar el Post en su nueva fecha de
  inmediato y sin elemento fantasma en el día anterior, recargando la lista de Posts existente
  (sin caché ni estado paralelo).
- **FR-041**: Si el Post detail de ese Post está abierto, DEBE reflejar la nueva fecha.
- **FR-042**: Tras un reschedule con éxito, cualquier resumen visible que muestre la próxima
  publicación programada ("Next", "Up next" o equivalente existente) NO DEBE quedarse mostrando
  la fecha anterior. Es coherencia de datos de una operación existente: no añade información ni
  funcionalidad. Cómo se refrescan se decide en planning.
- **FR-043**: Ante cualquier error al confirmar (422 fecha pasada; 409 no editable, cancelado,
  `check_result_first`, proyecto o cuenta inactivos, media no disponible, problema de armado;
  declaración TikTok obsoleta o pendiente), el diálogo DEBE mostrar el mensaje existente para
  ese código, nada DEBE quedar guardado parcialmente y Calendar DEBE recargarse para reflejar
  el estado real del backend. No se inventan códigos de error nuevos si existe uno adecuado.
- **FR-044**: Tras un reschedule con éxito DEBE anunciarse de forma no intrusiva (región
  `polite` o equivalente) la nueva fecha del Post.

### Functional Requirements — Responsive

- **FR-050**: Los breakpoints DEBEN mantenerse exactamente: week view de 7 columnas desde
  1280 px, agenda por debajo. No se crea grid horario.
- **FR-051**: Calendar DEBE seguir abriendo el Post detail como Drawer desde `md` y como página
  completa en móvil, y conservar navegación de semana, filtros, indicadores de estado y la
  URL `?view=calendar&week=`.
- **FR-052**: En agenda y móvil, Quick Reschedule DEBE ser usable con táctil (targets mínimos
  del design system) y su diálogo DEBE abrirse como Sheet en móvil.

### Functional Requirements — Accesibilidad

- **FR-060**: Toda capacidad de reprogramar DEBE estar disponible sin drag mediante Quick
  Reschedule (teclado, táctil, lector de pantalla).
- **FR-061**: El control de Quick Reschedule DEBE tener un nombre accesible que identifique el Post,
  foco visible y orden de tabulación lógico respecto al enlace del item.
- **FR-062**: Al cerrar el diálogo sin cambios, el foco DEBE volver al control que lo abrió.
  Tras un reschedule con éxito, el foco DEBE quedar en un lugar predecible: el Post en su nueva
  posición si sigue visible en la semana, y si no, el encabezado del rango de la semana.
- **FR-063**: El diálogo conserva la semántica de Dialog/Sheet existente (título, foco atrapado,
  Escape cierra).
- **FR-064**: Ningún feedback (drag, destinos, estado) DEBE depender solo del color, y el
  movimiento DEBE respetar `prefers-reduced-motion`.

### Key Entities

- **Post (publication)**: fecha programada (`scheduled_at`, instante UTC al minuto), estado
  persistido, consentimiento de publicación automática y estado visible derivado. No cambia su
  modelo.
- **Destino de drop (día)**: uno de los 7 días locales de la semana visible; válido si día +
  hora local original del Post es futuro y distinto del día actual del Post. Solo existe en la
  interfaz.

## Testing requirements

No se exigen pixel tests. Cobertura mínima:

**Backend**
- reschedule normal (`scheduled_*` → nueva fecha, armado);
- el claim gana → 409 y `publishing` intacto;
- el reschedule gana → nueva fecha y sin inicio por la fecha antigua;
- regresión de lost update (claim entre lectura y escritura del PATCH);
- estados bloqueados (`needs_review`, `needs_action`, `publishing`, `published`, `cancelled`);
- reschedule de `failed` y `missed`;
- declaración TikTok requerida/obsoleta en el armado;
- fecha pasada → 422.

**Frontend**
- Quick Reschedule desde week view y agenda, con ratón y teclado;
- diálogo y título correctos (*Edit schedule* en `scheduled_*`, *Reschedule* en `missed`/`failed`);
- precarga: fecha actual futura en `scheduled_*`; vacío si ya no es futura; vacío en
  `missed`/`failed`; fecha del drop en *Edit schedule*;
- drag a día válido abre el diálogo precargado; nada se envía hasta confirmar;
- día pasado / hoy con hora pasada → destino inválido, sin diálogo;
- mismo día → no-op;
- estados no draggable no inician arrastre;
- clic y teclado siguen abriendo el Post detail; el drag no navega;
- éxito → lista recargada, Post en el nuevo día, sin fantasma, detalle abierto actualizado;
- 409/422 → mensaje en el diálogo y Calendar recargado al estado real;
- week view (≥1280) con drag vs agenda (<1280) sin drag.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario puede reprogramar un Post visible en Calendar en un máximo de 3
  interacciones desde la vista (abrir la acción o soltar, ajustar si quiere, confirmar), sin
  pasar por el Post detail.
- **SC-002**: El 100 % de las acciones de reprogramación disponibles con drag lo están también
  sin drag (teclado, táctil y lector de pantalla).
- **SC-003**: En los tests de concurrencia, 0 casos en los que un Post termine `scheduled`
  mientras tiene una ejecución en curso, en ambos órdenes de la carrera.
- **SC-004**: 0 cambios guardados por un drop no confirmado, un drop en el mismo día, un drop
  en destino inválido o un arrastre cancelado.
- **SC-005**: Tras cualquier respuesta (éxito o error) del reschedule, Calendar muestra el
  estado real del backend sin necesidad de recargar la página.
- **SC-006**: Los tests existentes de Calendar, Post detail, `ActionDialog`, scheduling y
  scheduler siguen pasando sin cambiar sus expectativas (salvo la que fijaba Calendar como solo
  lectura).

## Non-goals

- Drag a otra hora, grid horario, resize, drag vertical.
- Drag táctil, drag en agenda o móvil, drag entre semanas.
- Duplicar Posts, selección o reschedule bulk, crear Posts desde un hueco.
- Posts recurrentes.
- Gestión nueva de zona horaria o persistencia de zona horaria.
- Librería de drag & drop nueva.
- Analytics.
- Cambios de semántica de publishing o de la arquitectura/intervalo del scheduler.
- Modelo, migración, endpoint o fuente de datos nuevos para Calendar; caché de scheduling.
- Versionado optimista / ETag.
- Cualquier cambio en `POST /api/publications/{id}/cancel`, incluida su carrera frente al claim
  (ver Assumptions).

## Assumptions

- Aplicación local de un único usuario: la política "gana la última escritura" entre
  reschedules es aceptable.
- La zona horaria es siempre la del navegador; las fechas siguen guardándose en UTC al minuto.
- La declaración TikTok y el resto de reglas de armado por plataforma ya viven en el diálogo y
  en el backend; esta feature solo las reutiliza.
- La solución atómica (p. ej. `write_transaction` / `BEGIN IMMEDIATE`, UPDATE condicional u otra
  equivalente ya presente en el repositorio) se decide en planning.
- El scheduler no se despierta tras un PATCH; reprogramar a una hora muy próxima puede iniciarse
  hasta un ciclo (30 s) después, dentro de la ventana automática. Se mantiene salvo necesidad
  demostrada en planning.
- **Problema conocido, fuera de 024**: `POST /api/publications/{id}/cancel` tiene una ventana
  de carrera análoga frente al claim del scheduler (lee y escribe sin bloqueo). 024 no lo
  modifica; queda registrado para una feature posterior de hardening/mantenimiento.
- Feature 019 (FR-066) queda modificada solo en "solo lectura / sin drag & drop".
