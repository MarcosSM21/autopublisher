# Feature Specification: Analytics & Performance

**Feature Branch**: `027-analytics-performance`

**Created**: 2026-10-28

**Status**: Implemented (Checkpoints A–I closed on 2026-10-29; see [tasks.md](tasks.md) and [docs/analytics.md](../../docs/analytics.md))

**Input**: User description: "Feature 027 — Analytics & Performance. Primera capa útil de
analítica para entender cómo rinde el contenido publicado desde AutoPublisher: views, likes,
comments, engagement, evolución, mejores posts, comparación entre plataformas y rendimiento por
tipo de contenido. Debe partir de (1) una auditoría de qué métricas puede recuperar realmente
AutoPublisher de cada plataforma con los permisos e IDs remotos actuales y (2) un modelo común
que conserve las métricas originales de cada plataforma sin perder información y solo permita
comparaciones normalizadas cuando tengan sentido semántico. Accionable antes que decorativo,
trazabilidad a los datos originales, sin equivalencias inventadas, adaptadores modulares por
plataforma, sin sistema de recomendaciones."

## Regla de producto

**Medir solo lo que la plataforma dice de verdad, y comparar solo lo que significa lo mismo.**

- Cada número mostrado DEBE poder rastrearse a una métrica original de una plataforma concreta,
  con su nombre original, su valor y el momento en que se obtuvo.
- AutoPublisher NO inventa equivalencias: ninguna métrica se compara cuantitativamente entre
  plataformas. Los conceptos comunes solo sirven para **alinear** visualmente métricas de
  distintas plataformas, nunca para sumarlas, promediarlas u ordenarlas entre sí (FR-009,
  FR-022).
- Lo que no se puede obtener se muestra como "no disponible" con su motivo, nunca como 0.

## Contexto (auditoría del estado actual verificada en el código)

Contexto para la planificación; el comportamiento exigido está en Requirements. Las capacidades
de cada API se verificaron con documentación oficial en [research.md](research.md)
(2026-10-29); los detalles que siguen siendo hipótesis están listados allí y en el plan.

**Qué se guarda hoy tras publicar**: cada `Publication` publicada tiene intentos
(`PublicationAttempt`); el intento con éxito guarda `external_id` (ID remoto) y `external_url`.
No existe ningún código, tabla ni pantalla de métricas.

| Plataforma | ID remoto guardado | Permisos actuales | Métricas obtenibles sin pedir permisos nuevos | Con permiso adicional (reconexión) | Clasificación v1 |
|---|---|---|---|---|---|
| YouTube | `video_id` siempre que la subida tiene éxito | `youtube.readonly`, `youtube.upload` | Contadores públicos acumulados del vídeo: visualizaciones, me gusta, comentarios (comentarios ausentes si están desactivados) | Analítica avanzada (tiempo de visualización, retención) vía un permiso de analítica — fuera de v1 | **Soportada** |
| Instagram | `media_id`; puede faltar (aviso `remote_identity_unavailable`) | `instagram_business_basic`, `instagram_business_content_publish` | Me gusta (`like_count`, omitido si el dueño oculta los recuentos) y número de comentarios (`comments_count`) del media — **confirmado**. Sin views. | Insights del media: views, reach, saved, shares, total interactions (permiso de insights) | **Soportada (básica)**; insights en feature posterior |
| Threads | `media_id`; puede faltar (aviso equivalente) | `threads_basic`, `threads_content_publish` | Ninguna — **confirmado**: el objeto media no expone contadores | Insights del post: views, likes, replies, reposts, quotes, shares (permiso de insights) | **Requiere permiso** |
| TikTok | Solo si el post es público (`publicaly_available_post_id`); nunca en modo inbox; un cliente no auditado solo publica `SELF_ONLY`, así que en la práctica no hay ID | `user.info.basic`, `video.publish`, `video.upload` | Ninguna | Contadores del vídeo (views, likes, comments, shares) con un permiso de lectura de vídeos, **y** solo para posts con ID público | **`not_supported` en v1** (motivo visible) |
| Telegram | `message_id` del canal | Sesión de usuario MTProto | La API MTProto que usa AutoPublisher sí permite leerlas (`messages.getMessagesViews`: vistas, forwards, replies), pero AutoPublisher no implementa ese adaptador en v1 | — | **`not_supported` en v1** (motivo visible) |
| X | — (sin publisher) | — | — | — | **No aplica** |

**Diferencias semánticas relevantes detectadas**:

- "Views" no significa lo mismo: YouTube cuenta visualizaciones según su propio criterio de
  validez; Instagram y Threads cuentan reproducciones/visualizaciones según los suyos. No son
  sumables ni comparables entre plataformas.
- "Comments" en YouTube/Instagram y "replies" en Threads describen respuestas al post, pero con
  reglas distintas (hilos, respuestas anidadas, moderación).
- YouTube y los contadores básicos de Instagram son contadores públicos acumulados; los insights
  de Meta son métricas privadas que pueden tener retraso, ventanas de retención o redondeos.
- Todas las métricas crecen con la antigüedad del post: comparar un post de hace 2 días con uno
  de hace 2 meses sin contexto induce a error.

## Clarifications

### Session 2026-10-29

- Q: ¿La solicitud/reconexión de permisos de insights de Instagram y Threads forma parte de la
  Feature 027? → A: No. Se elimina US6; la arquitectura queda preparada y las cuentas afectadas
  se muestran como `permission_required` indicando la capacidad que falta, sin tocar OAuth,
  conexión ni publicación.
- Q: ¿`likes` y `comments` son comparables entre plataformas? → A: Solo se alinean visualmente
  bajo una etiqueta común cuando el mapeo es claro; no son cuantitativamente equivalentes. No se
  suman, promedian, rankean ni se interpretan como mejor/peor entre plataformas. `views` y
  `shares` tampoco se comparan numéricamente.
- Q: ¿Cómo se calcula el engagement? → A: Con una fórmula fija y explícita declarada por la
  capacidad de cada plataforma; mismos componentes para todos sus posts; si falta cualquier
  componente, "no disponible"; nunca componentes opcionales ni comparación entre plataformas; la
  UI muestra fórmula y componentes.
- Q: ¿Qué deltas del research se incorporan a la spec? → A: Los seis propuestos en el plan:
  FR-006 excluye métricas obsoletas documentadas (YouTube `favoriteCount`); FR-001 añade
  `not_supported` y capacidad por cuenta y grupo de métricas; se elimina el edge case de
  contenido borrado con publicación conservada (imposible por Feature 021); el Contexto marca
  como confirmados los contadores básicos de Instagram y la ausencia de métricas de Threads
  sin insights; se añade el cambio de definición de YouTube `viewCount` (2026-08-24).
- Q: ¿Telegram no ofrece métricas? → A: Sí las ofrece: AutoPublisher usa una sesión de usuario
  MTProto, y `messages.getMessagesViews` devuelve vistas, forwards y replies. Telegram queda
  fuera de v1 como `not_supported` (antes `not_available_on_platform`, basado en la Bot API).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver el rendimiento de cada publicación (Priority: P1)

El usuario abre la analítica de un proyecto y ve la lista de sus publicaciones publicadas con
las métricas disponibles de cada una (con nombre original de plataforma), la antigüedad del
post, cuándo se actualizaron los datos por última vez y, si no hay datos, el motivo concreto.
Desde ahí puede abrir el post remoto.

**Why this priority**: es la base de todo lo demás y responde a la pregunta más básica ("¿cómo
le ha ido a lo que publiqué?"). Con YouTube e Instagram básico funciona sin pedir permisos nuevos.

**Independent Test**: con un proyecto que tiene publicaciones en YouTube e Instagram y una en
Telegram, abrir la analítica, refrescar y comprobar que YouTube/Instagram muestran sus métricas
con fecha de obtención y que Telegram aparece como "no soportada por AutoPublisher en esta
versión".

**Acceptance Scenarios**:

1. **Given** una publicación de YouTube publicada con `video_id`, **When** se obtienen sus
   métricas, **Then** se muestran visualizaciones, me gusta y comentarios con su nombre de
   plataforma, su valor y la fecha/hora de obtención.
2. **Given** una publicación publicada sin ID remoto (p. ej. TikTok inbox o Instagram con
   identidad no disponible), **When** se abre la analítica, **Then** aparece como "sin vínculo
   remoto" con el motivo y nunca con valores 0.
3. **Given** una publicación en una plataforma cuyas métricas AutoPublisher aún no lee
   (Telegram), **When** se abre la analítica, **Then** aparece como "las métricas de Telegram no
   están soportadas por AutoPublisher en esta versión", nunca con valores 0.
4. **Given** una publicación con métricas, **When** el usuario pulsa el enlace, **Then** se abre
   el post en la plataforma.

---

### User Story 2 - Refrescar métricas de forma fiable (Priority: P1)

Las métricas se actualizan automáticamente con una cadencia moderada y el usuario puede
forzar un refresco. Los errores (cuenta desconectada, permiso que falta, límite de la API,
post borrado en remoto) se registran y se muestran por publicación y por cuenta, sin bloquear
nunca la publicación de contenido.

**Why this priority**: sin refresco fiable la analítica miente por omisión; sin tratamiento de
errores visible, el usuario no sabe si un número es actual.

**Independent Test**: simular respuestas correctas, límite de API, token caducado y post
inexistente; comprobar el estado mostrado y que se conservan los últimos datos válidos.

**Acceptance Scenarios**:

1. **Given** una cuenta desconectada o con credencial caducada, **When** toca refrescar,
   **Then** no se llama a la plataforma, se conservan los datos previos marcados como
   desactualizados y se indica que hay que reconectar.
2. **Given** que la plataforma responde con límite de peticiones, **When** se refresca, **Then**
   se detiene el refresco de esa plataforma, se reintenta más tarde y el resto de plataformas
   no se ve afectado.
3. **Given** que el post ya no existe en la plataforma, **When** se refresca, **Then** se marca
   como "eliminado en la plataforma", se conserva el histórico y se deja de refrescar.
4. **Given** una publicación programada para ahora, **When** coincide con un refresco de
   métricas, **Then** la publicación tiene prioridad: no se inicia ninguna lectura mientras
   haya una publicación en curso o inminente, y el refresco no consume cuota que la publicación
   necesite.

---

### User Story 3 - Mejores posts y rendimiento por tipo de contenido (Priority: P2)

El usuario elige una plataforma (o cuenta) y un periodo de publicación y ve sus posts ordenados
por una métrica de esa plataforma, y un resumen por tipo de contenido (imagen, vídeo, texto) con
número de posts y mediana de cada métrica, mostrando la antigüedad para dar contexto.

**Why this priority**: es la primera información accionable ("¿qué tipo de contenido funciona
mejor aquí?"), pero depende de US1/US2.

**Independent Test**: con datos de ejemplo de 10 posts de una cuenta, verificar el orden por
métrica, las medianas por tipo y que la vista nunca mezcla plataformas en un mismo ranking.

**Acceptance Scenarios**:

1. **Given** posts de varias plataformas, **When** el usuario pide "mejores posts", **Then** el
   ranking siempre se limita a una sola plataforma.
2. **Given** un tipo de contenido con menos de 3 posts con datos, **When** se muestra el resumen,
   **Then** se indica que la muestra es insuficiente en lugar de presentar la mediana como
   conclusión.

---

### User Story 4 - Ver un contenido lado a lado por plataforma (Priority: P2)

Para un mismo contenido publicado en varias cuentas, el usuario ve lado a lado las métricas de
cada publicación. Las métricas con un mapeo claro a un concepto común se **alinean** bajo una
etiqueta común para facilitar la lectura, conservando su nombre y definición originales; el
resto se muestra por separado con su nombre original. La vista no compara cuantitativamente
plataformas entre sí.

**Why this priority**: es el caso de uso multiplataforma real de AutoPublisher, pero solo es
honesto si distingue alinear de comparar (FR-009, FR-022).

**Independent Test**: un contenido publicado en YouTube e Instagram muestra me gusta y
comentarios alineados bajo etiquetas comunes con su nombre original, las visualizaciones por
plataforma con su nombre original, y ningún total, promedio, orden ni indicador de "mejor"
entre plataformas.

**Acceptance Scenarios**:

1. **Given** un contenido publicado en YouTube e Instagram, **When** se abre su vista lado a
   lado, **Then** likes y comments aparecen alineados bajo etiquetas comunes con su nombre y
   definición originales, y una nota indica que no son cuantitativamente equivalentes.
2. **Given** la misma vista, **When** una plataforma tiene más likes que otra, **Then** la vista
   no la destaca como mejor ni ordena las plataformas por ese valor.
3. **Given** la misma vista, **When** se muestran views o shares, **Then** aparecen por
   plataforma con su nombre original, sin total ni promedio combinado.

---

### User Story 5 - Evolución de una publicación (Priority: P3)

El usuario ve cómo han evolucionado las métricas de una publicación a lo largo del tiempo a
partir de las lecturas guardadas.

**Why this priority**: aporta contexto (¿sigue creciendo o se ha estancado?), pero requiere
haber acumulado histórico.

**Independent Test**: con varias lecturas guardadas de una publicación, la vista de evolución
muestra cada métrica en el tiempo con los puntos reales de lectura.

**Acceptance Scenarios**:

1. **Given** una publicación con al menos 2 lecturas, **When** se abre su evolución, **Then**
   se muestran los valores en cada fecha de lectura sin interpolar puntos inexistentes.

### Edge Cases

- Publicaciones anteriores a esta feature: se incluyen si tienen ID remoto en su intento con
  éxito; no se intenta vincular posts por búsqueda, título o fecha.
- Varios intentos de una misma publicación: solo cuenta el intento con éxito que tiene ID remoto.
- Posts publicados fuera de AutoPublisher: fuera de alcance.
- Publicación borrada localmente, también por el borrado de su media o de su cuenta
  (Feature 021): sus lecturas de métricas se eliminan con ella.
- Cambio de definición de YouTube `viewCount`: desde el 24 de agosto de 2026 YouTube cambió la
  definición de su contador público `viewCount`. AutoPublisher conserva siempre el valor
  devuelto por YouTube y no intenta reconstruirlo, corregirlo ni normalizarlo. Los vídeos
  antiguos pueden tener un contador acumulado que atraviesa ese cambio de definición; la
  definición mostrada de la métrica lo indica.
- La plataforma devuelve un campo ausente (p. ej. comentarios desactivados en YouTube): se
  muestra "no disponible", no 0.
- La plataforma devuelve un valor menor que la lectura anterior (moderación, recuento de spam):
  se guarda tal cual; no se corrige ni se oculta.
- La plataforma cambia o retira una métrica: las lecturas antiguas conservan su nombre original;
  las nuevas simplemente no la traen.
- Cuenta reasignada o reconectada con otra identidad remota: no se refrescan posts de la
  identidad anterior (se marcan como no accesibles).

## Requirements *(mandatory)*

### Functional Requirements

**Capacidades y trazabilidad**

- **FR-001**: El sistema DEBE determinar la capacidad de métricas de cada cuenta **y de cada
  grupo de métricas/permisos** de su plataforma (p. ej. Instagram `basic` e `insights`), con
  los estados `supported`, `permission_required`, `not_supported` (la plataforma ofrece
  métricas pero AutoPublisher aún no las implementa, p. ej. TikTok y Telegram en v1),
  `not_available_on_platform` (la plataforma no ofrece métricas; ninguna en v1),
  `not_applicable` o `not_connected`, según la tabla de auditoría y los permisos realmente
  concedidos. Una cuenta es refrescable si al menos un grupo
  está en `supported`; los demás grupos muestran su estado y la capacidad que falta.
- **FR-002**: Cada plataforma DEBE obtener sus métricas mediante su propio adaptador
  independiente; el núcleo de analítica solo trabaja con el modelo común (FR-008).
- **FR-003**: Solo se DEBEN pedir métricas de publicaciones en estado publicado cuyo intento con
  éxito tenga ID remoto; las demás publicaciones publicadas DEBEN mostrarse como "sin vínculo
  remoto" con el motivo conocido (inbox, post privado, identidad no disponible).
- **FR-004**: El sistema NO DEBE vincular publicaciones con posts remotos por heurísticas
  (búsqueda, título, fecha).

**Modelo común**

- **FR-005**: Cada lectura de métricas DEBE guardar: publicación, plataforma, ID remoto usado,
  instante de obtención y, por cada métrica, su nombre original en la plataforma, su valor y su
  origen (contador público o insight privado).
- **FR-006**: Toda métrica vigente devuelta por la plataforma para ese post DEBE conservarse,
  aunque no tenga equivalente común. Solo se excluyen las métricas oficialmente obsoletas o sin
  significado útil (p. ej. YouTube `favoriteCount`, obsoleta y siempre 0), y cada exclusión
  DEBE quedar documentada en la declaración del adaptador/catálogo.
- **FR-007**: Las métricas DEBEN distinguir "valor 0" de "no disponible"; nunca se DEBE
  rellenar un hueco con 0.
- **FR-008**: El sistema DEBE mantener un catálogo de métricas común reducido —`views`, `likes`,
  `comments`, `shares`— al que cada adaptador mapea explícitamente sus métricas originales, con
  la definición de cada mapeo visible para el usuario. Las métricas sin mapeo se muestran con
  su nombre original.
- **FR-009**: Ninguna métrica del catálogo común es cuantitativamente comparable entre
  plataformas. El catálogo DEBE declarar para cada concepto si admite **alineación visual**:
  en v1, `likes` y `comments` sí (cuando el mapeo de la plataforma es claro); `views` y
  `shares` no, y se muestran por plataforma con su nombre original. Alinear significa mostrar
  bajo una etiqueta común conservando nombre y definición originales; NO implica sumar,
  promediar, ordenar ni interpretar un valor mayor en una plataforma como mejor rendimiento que
  un valor menor en otra.
- **FR-010**: La alineación de Threads `replies` bajo `comments` DEBE mostrarse con nota de
  definición; `reposts` y `quotes` se conservan como métricas propias de Threads.

**Historial y refresco**

- **FR-011**: El sistema DEBE guardar un histórico de lecturas (no solo el último valor); la
  vista principal usa la lectura válida más reciente.
- **FR-012**: El sistema DEBE refrescar automáticamente, como máximo una vez cada 24 h por
  publicación, las publicaciones publicadas en los últimos 90 días con capacidad `supported`.
- **FR-013**: El usuario DEBE poder refrescar manualmente una publicación o un proyecto. Una
  petición manual de una publicación cuyo último intento fue hace menos de 15 minutos DEBE
  rechazarse indicando cuándo vuelve a ser elegible, y NO queda en cola.
- **FR-014**: El refresco DEBE agrupar peticiones cuando la plataforma lo permita, respetar sus
  límites, detener el refresco de esa plataforma ante un límite alcanzado y reintentar después,
  y NUNCA consumir la cuota necesaria para publicaciones pendientes ni retrasarlas.
- **FR-015**: Cada publicación refrescable DEBE mostrar un estado de refresco visible,
  conservando siempre la última lectura válida y su antigüedad:
  - `pending`: refresco aceptado (petición manual o primera lectura automática) aún no
    ejecutado; puede seguir así mientras una pausa o un rate limit de la plataforma lo impida;
  - `ok`: la última lectura fue correcta;
  - `stale`: el último intento falló por un motivo transitorio o desconocido;
  - `rate_limited`, `reconnect_required` y `permission_required`: la plataforma limitó las
    peticiones, la conexión no es utilizable, o falta un permiso;
  - `remote_not_found`: primera ausencia del post remoto, pendiente de la segunda
    confirmación;
  - `remote_deleted`: solo tras la segunda confirmación definida en el plan (FR-016).

  No existe un estado genérico `error`; el detalle técnico del último fallo se conserva como
  código y mensaje seguros asociados al estado.
- **FR-016**: Un post reportado como inexistente por la plataforma DEBE marcarse
  `remote_not_found` y, si la ausencia se confirma en un segundo intento al menos 1 h después,
  `remote_deleted`, dejando de refrescarse automáticamente.
- **FR-017**: El refresco de métricas NO DEBE depender del interruptor de pausa de publicación
  automática ni modificar el estado de ninguna publicación.

**Análisis**

- **FR-018**: El sistema DEBE mostrar por publicación: métricas (común + originales), antigüedad
  del post, fecha de la última lectura, estado y enlace al post remoto.
- **FR-019**: El engagement DEBE calcularse solo dentro de una plataforma y nunca compararse
  entre plataformas. La capacidad de cada plataforma DEBE declarar una única fórmula fija y
  explícita (componentes del numerador y denominador, todos métricas originales de esa
  plataforma); todos los posts de la plataforma usan exactamente los mismos componentes. Si
  falta cualquier componente requerido en una lectura, el engagement de ese post es "no
  disponible"; NO se admiten componentes opcionales ni fórmulas que cambien según la
  disponibilidad de datos. Una plataforma sin fórmula declarada no ofrece engagement. La UI
  DEBE mostrar la fórmula y los valores de los componentes usados.
- **FR-020**: Los rankings de mejores posts DEBEN limitarse a una sola plataforma (o cuenta) y
  a una métrica de esa plataforma, filtrables por periodo de publicación.
- **FR-021**: El resumen por tipo de contenido (imagen, vídeo, texto) DEBE calcularse por
  plataforma con número de posts y mediana; con menos de 3 posts con datos se DEBE indicar
  "muestra insuficiente".
- **FR-022**: La vista lado a lado de un contenido DEBE alinear solo los conceptos que admiten
  alineación (FR-009) y mostrar el resto por separado con su nombre original. Ninguna vista
  DEBE sumar, promediar, rankear ni destacar como mejor una plataforma frente a otra a partir
  de sus métricas.
- **FR-023**: La evolución de una publicación DEBE mostrar solo puntos de lectura reales.

**Permisos adicionales (preparación, sin cambios de OAuth)**

- **FR-024**: La capacidad de cada plataforma DEBE declarar qué permiso requiere cada grupo de
  métricas, de modo que una feature posterior pueda solicitar permisos de insights sin rediseñar
  el modelo. En esta feature NO se modifican el flujo OAuth, la conexión ni la publicación: las
  cuentas a las que les falte un permiso se muestran como `permission_required`, indicando qué
  capacidad falta (p. ej. "insights de Threads").
- **FR-025**: Se DEBEN usar exclusivamente APIs oficiales y permisos de lectura; las
  credenciales siguen sin salir del almacén seguro y no aparecen en logs ni errores.

### Key Entities *(include if feature involves data)*

- **Metric capability (por cuenta y grupo de métricas)**: estado derivado de plataforma +
  permisos concedidos + conexión, por cada grupo de métricas; explica qué métricas se pueden
  obtener y qué falta.
- **Metrics snapshot (lectura)**: una obtención de métricas de una publicación en un instante;
  referencia la publicación, el ID remoto y el resultado (éxito o estado de error).
- **Metric value**: valor de una métrica dentro de una lectura; nombre original, mapeo común
  opcional, valor, origen (público/insight).
- **Metric catalog (común)**: definición de `views`, `likes`, `comments`, `shares`, si admiten
  alineación visual (nunca comparación cuantitativa) y el mapeo declarado por cada plataforma.
- **Engagement formula (por plataforma)**: fórmula fija declarada por la capacidad de la
  plataforma: componentes requeridos y denominador; puede no existir.
- **Refresh state (por publicación)**: última lectura válida, último intento, estado y próxima
  elegibilidad de refresco.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El 100 % de las publicaciones publicadas aparece en la analítica con métricas o
  con un motivo explícito de ausencia; ninguna aparece con 0 por falta de datos.
- **SC-002**: El 100 % de los valores mostrados puede rastrearse hasta su nombre de métrica
  original, plataforma e instante de obtención.
- **SC-003**: Ninguna vista suma, promedia, ordena ni destaca como mejor métricas o engagement
  de plataformas distintas (verificable con tests sobre datos de ejemplo multiplataforma).
- **SC-008**: Dentro de una plataforma, el 100 % de los engagements mostrados usa la misma
  fórmula y componentes; los posts a los que les falta un componente aparecen como "no
  disponible".
- **SC-004**: El refresco de métricas no provoca ningún retraso ni fallo en publicaciones
  programadas (0 publicaciones afectadas en pruebas con refresco y publicación simultáneos).
- **SC-005**: Una cuenta desconectada, un límite de API o un post borrado en remoto se reflejan
  en la analítica en el siguiente refresco, conservando el último dato válido.
- **SC-006**: El usuario puede identificar el mejor post de una cuenta en un periodo en menos de
  30 segundos desde que abre la analítica del proyecto.
- **SC-007**: Las publicaciones de YouTube anteriores a la feature con ID remoto obtienen
  métricas sin que el usuario tenga que reconectar ninguna cuenta.

## Out of Scope

- Recomendaciones, predicciones o "mejor hora para publicar".
- Solicitar o reconectar con permisos de insights de Instagram o Threads (feature posterior;
  esta solo deja el modelo preparado, FR-024).
- Cualquier comparación cuantitativa o ranking entre plataformas.
- Métricas de cuenta (seguidores, alcance de perfil) y demografía de audiencia.
- Analítica avanzada de YouTube (tiempo de visualización, retención) y cualquier permiso de
  analítica de YouTube nuevo.
- Métricas de TikTok, Telegram y X en v1 (ver auditoría); el modelo DEBE permitir añadirlas
  después con un adaptador nuevo.
- Importar o vincular posts publicados fuera de AutoPublisher.
- Exportación de métricas, alertas o notificaciones.
- Comparaciones normalizadas por edad del post (p. ej. "views a los 7 días").

## Assumptions

- AutoPublisher sigue siendo local y de un único usuario; la analítica es por proyecto.
- El scope `youtube.readonly` ya concedido basta para leer los contadores públicos de los
  vídeos propios. La lectura cuesta 1 unidad de la cuota general diaria del proyecto de Google;
  las subidas (`videos.insert`) usan su propio bucket de cuota (confirmado en research).
- Los contadores básicos de Instagram (likes, comments) son accesibles con
  `instagram_business_basic` (confirmado en research).
- Las lecturas se guardan indefinidamente; con cadencia diaria y ventana de 90 días el volumen es
  pequeño para un uso personal. Forman parte de la base local y de sus backups, nunca del
  repositorio.
- El tipo de contenido se deriva del media existente (imagen, vídeo) o de su ausencia (texto).
- El refresco automático reutiliza el proceso en segundo plano existente.
