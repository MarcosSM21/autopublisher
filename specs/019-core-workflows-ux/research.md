# Research — Feature 019 Core Workflows UX Redesign

Decisiones técnicas tomadas tras inspeccionar el repositorio (rama `019-core-workflows-ux`,
base `main` @ `1acb169`). Formato: Decision / Rationale / Alternatives.

## R-01 Estado real relevante del repo

- Rutas (`frontend/src/routes.tsx`): `p/:projectId/library/:mediaId?`,
  `posts/:postId?`, `accounts/:accountId?` bajo `ProjectLayout`, que carga el proyecto y **un
  overview del proyecto** compartido (`useProject().overview`, recargado al cambiar de sección
  o con `reloadOverview`).
- Legacy por sustituir: `ContentLibrary`, `ContentDetail`, `ContentImport`, `AssetUsage`,
  `AssetFile`, `Distribute` (1021 líneas: formulario, presets, panel de resultado),
  `PublicationQueue`, `PublicationDetail`, `PublicationControls`, `PublishNowDialog`,
  `AutoPublishConsent`, `TextPublicationCreate`, `PublicationAttempts`, `*PublishOptions`
  (formularios con botón Save propio), `useLivePublication`.
- `DetailSurface` (018): portal persistente + `Surface` por breakpoint (`lg` panel no modal,
  `md` Drawer Radix, `sm` página con Back). Sin scroll propio, sin zona sticky, sin preferencia
  por página. Usado por Accounts.
- Primitivas 018 (`ui/`): Button, IconButton, Badge, StatusBadge (`POST_STATUS`), Card,
  Disclosure, EmptyState, ErrorState, Skeleton, Dialog/Drawer/Sheet (Radix), Icon,
  `useMediaQuery`, breakpoints `md=768`, `lg=1024`.
- Backend:
  - `post_state.post_display_state` es la única fuente del display state; lo usan
    `publication_to_read` y `overview`.
  - `GET /projects/{id}/publications` devuelve **todos** los Posts del proyecto (incluido
    histórico) con `display_state`, `latest_attempt` (con `submitted`), overrides y campos
    efectivos, sin N+1 (attempts en lote).
  - `GET /overview?project_id=` produce attention (`incomplete` por post dentro de 7 días
    usando `local_check`, sin red) — **pero** los posts cuyos únicos problemas son de conexión
    se pliegan en el item `reconnect` de la cuenta (`affected_posts`), sin id de post.
  - `GET /contents/{id}/usage` lista los Posts de una Media (`AssetPublicationRead`) sin
    `display_state`; `usage_by_content` agrega recuentos con dos queries por proyecto.
  - Lifecycle: `ensure_editable(FAILED, schedule_change=True)` rechaza con "Cancel and
    reactivate it to schedule it again."; `reactivate` devuelve a SCHEDULED desarmado (fecha
    futura) o UNSCHEDULED. `PATCH /publications/{id}` con `scheduled_at` sin
    `auto_publish_enabled` desarma; arming valida fecha futura, disponibilidad y
    `arming_problems` del publisher (TikTok exige consentimiento `valid`).
  - Publish now: `POST /publications/{id}/publish` (UNSCHEDULED/SCHEDULED/FAILED elegibles),
    preflight completo, `confirm_remote_checked` obligatorio si `requires_remote_check`
    (último intento de la pareja contenido+cuenta incierto).
  - TikTok: `POST /publications/{id}/tiktok-consent {fingerprint, declaration_version}`
    recalcula la huella y registra el consentimiento; `publish-check` y `arming_problems`
    reportan `tiktok_consent_required` si no es `valid`. Hoy existen **dos** confirmaciones:
    el checkbox de `TikTokPublishOptions` (registra al marcar) y el de `PublishNowDialog`
    (registra antes de publicar).

## R-02 Identidad del Publish set

- **Decision**: query param `posts` con ids decimales separados por coma:
  `/p/:pid/library/:mid/publish?posts=12,13,14` y `/p/:pid/posts/new?posts=21,22`.
  Se escribe con `navigate(..., { replace: true })` tras `Continue` y en cada add/remove de
  destino; se lee en cada render (la URL es la única fuente).
- **Rationale**: reload/back/forward/deep link gratis con el router existente; ids reales;
  sin persistencia; legible; patrón ya usado (`?project=`, `?view=`).
- **Alternatives**: `sessionStorage` (no deep-linkable, no compartible entre pestañas);
  entidad batch (prohibida por la spec); path segment (rompe la ruta de Media/Text);
  derivar de "drafts de la Media" tras ejecutar (heurístico, prohibido por FR-031a).

## R-03 Orquestación de la acción final sin endpoint batch

- **Decision**: cliente orquesta peticiones existentes por Post, **secuencialmente** y en el
  orden del set: (TikTok DP) `tiktok-consent` → `publish` | `PATCH {scheduled_at,
  auto_publish_enabled:true}`. Validación previa con `publish-check` por Draft + reglas
  locales (fecha futura, declaración). Sin rollback.
- **Rationale**: los endpoints ya garantizan todas las reglas por Post; secuencial evita
  carreras con el límite de concurrencia y hace determinista el resultado; N es pequeño
  (≤ cuentas del proyecto).
- **Alternatives**: endpoint batch transaccional para Schedule (posible pero innecesario: la
  spec acepta fallo parcial; añade contrato y tests); paralelo (`Promise.all`) — más rápido
  pero mensajes de error intercalados y presión innecesaria.

## R-04 Autosave de opciones de plataforma

- **Decision**: hook pequeño `useAutosave<T>(save)` por card: una petición en vuelo como
  máximo; cambios durante el vuelo se **coalescen** (se guarda solo el último valor al
  terminar: last-write-wins por secuenciación, no por abort); estados
  `idle|saving|saved|error`; `retry()` reenvía el último valor; `flush(): Promise<boolean>`
  espera a que no quede nada pendiente. Texto: guarda en blur; radios/checkbox: en change.
  Registro en un `AutosaveRegistry` (contexto del Publish task / Post detail) para que el
  CTA final y `Finish later` hagan `flushAll()`.
- **Rationale**: los PUT de opciones son idempotentes y de documento completo; secuenciar
  evita que una respuesta antigua pise una nueva sin abortar peticiones que el servidor ya
  puede haber aplicado.
- **Alternatives**: debounce sin secuenciación (respuestas fuera de orden); AbortController
  (no deshace la escritura en servidor; falsa sensación de control); librería de formularios
  (dependencia innecesaria).

## R-05 Declaración TikTok única

- **Decision**: la declaración es **estado local** de la acción: `{fingerprint, version}`
  aceptados. Se muestra en la card TikTok (Direct Post) del Publish task y en el Dialog de
  acción de Post detail. Está "aceptada" solo si `accepted.fingerprint ===
  options.fingerprint && accepted.version === options.declaration.version`; cualquier cambio
  de opciones/caption que cambie la huella la invalida automáticamente. Empieza sin marcar en
  cada montaje de acción (ignora `consent.state` persistido). Al ejecutar el CTA:
  `confirmTikTokConsent(fp, version)` justo antes de `publish` / `PATCH` armando.
  `tiktok_consent_required` del `publish-check` se trata como satisfecho por la declaración
  local; si no está marcada se muestra en el error summary como "TikTok declaration".
- **Rationale**: una sola confirmación por acción (R5) manteniendo intacto el backend
  (huella, invalidación, `arming_problems`, preflight).
- **Alternatives**: registrar al marcar (comportamiento actual de `TikTokPublishOptions`:
  persiste antes de la acción y obliga a otra confirmación); cambio backend para aceptar
  fingerprint en `publish` (innecesario).

## R-06 Readiness en Posts (horizonte 7 días)

- **Decision**: reutilizar el `overview` del proyecto que `ProjectLayout` ya carga:
  `attention[kind=incomplete].post.id` → "Needs details" (con `detail` como resumen; "Couldn't
  verify requirements" incluido). Para los posts plegados en `reconnect`, usar la salud de
  cuenta (`GET /projects/{id}/account-health`, una petición): Scheduled dentro de 7 días cuya
  cuenta no está `ready` → "Blocked · Reconnect account / Finish account setup". Resto dentro
  del horizonte → "Ready". Más allá: sin indicador.
- **Rationale**: cero `local_check` adicional, cero endpoint nuevo.
- **Alternatives**: endpoint de readiness por post (prohibido salvo imposibilidad); añadir
  ids de posts afectados al item `reconnect` (cambio backend evitable).

## R-07 Uso por Media (read-model)

- **Decision**: ampliar `usage_by_content` con **una** query adicional por proyecto que
  carga `(content_id, status, auto_publish_enabled, scheduled_at)` de Posts no históricos y
  evalúa `post_display_state(..., latest_attempt=None, ...)` en Python (Failed y Needs review
  cuentan igual como atención, así que el intento no es necesario). Nuevos campos:
  `draft_count`, `attention_count`, `upcoming_count`, `next_scheduled_at`,
  `cancelled_count`. `AssetPublicationRead` añade `display_state`, `inherits` (por campo) y
  `consent_covers_caption`.
- **Rationale**: semántica de producto desde la única fuente (`post_display_state`); sin
  N+1; Library no necesita cargar Posts.
- **Alternatives**: SQL que replique la lógica de missed (duplica reglas); cargar
  `listPublications` en Library (más datos, más acoplamiento).

## R-08 Published: contenido enviado

- **Decision**: mapear `latest_attempt.submitted` por plataforma:
  YouTube `title` + `description`; Instagram `caption`; Threads `text` (+`alt_text`);
  TikTok Direct Post `caption`; TikTok Inbox: sin caption (se escribe en TikTok →
  "You wrote the caption in TikTok"); Telegram: solo `text_length` → **fallback** al
  contenido efectivo con nota "May differ from what was sent". Sin persistencia nueva.
- **Constraint**: Telegram no guarda el texto enviado; la spec ya admite el fallback
  (FR-074). No se añade persistencia.

## R-09 Calendar

- **Decision**: sin backend; deriva del mismo `listPublications` que la lista. URL
  `?view=calendar&week=YYYY-MM-DD` (lunes local; inválido → semana actual con `replace`).
  Anclaje (función pura `calendarMoment(post)`):
  Published → `published_at`; Scheduled* y Missed → `scheduled_at`; Publishing (la
  ejecución real) → `scheduled_at` si el intento en curso es `trigger=scheduled`, si se inició
  manualmente `latest_attempt.started_at`, fallback `updated_at` (alineado con spec FR-069); Failed/Needs review → `scheduled_at` si
  `latest_attempt.trigger=scheduled`, si no `latest_attempt.started_at`; Needs action →
  `latest_attempt.finished_at` (momento en que el envío al inbox terminó; equivalente a
  `delivered_at` sin pedir `tiktok-delivery` por post) con fallback a `updated_at`.
  Semana ≥1024 px; agenda <1024 px. `Intl.DateTimeFormat` con zona del navegador.
- **Alternatives**: `delivered_at` vía `GET tiktok-delivery` por post (N peticiones);
  ISO week `2026-W42` (parse más complejo).

## R-10 Failed → Reschedule / Move to drafts (único cambio de lifecycle)

- **Decision**: ampliar `PATCH /publications/{id}`: para `FAILED`, la presencia de
  `scheduled_at` en el body **siempre** transiciona (aunque el valor coincida): no nulo →
  `SCHEDULED` (fecha futura, `ensure_can_prepare`), nulo → `UNSCHEDULED`; se desarma y se
  limpia `auto_publish_error`; si el body arma, se aplican `_set_consent` y
  `arming_problems` en la misma petición. Si `requires_remote_check` → `409
  check_result_first` "Check the result first." Retry sigue siendo `POST /publish`.
- **Rationale**: reutiliza un endpoint y todas sus reglas; un único request atómico por
  acción; sin nuevo endpoint.
- **Alternatives**: endpoints `/reschedule` y `/move-to-drafts` (más superficie);
  Cancel→Reactivate (prohibido como flujo obligatorio).

## R-11 Needs review y "Check result"

- **Decision (confirmada; spec FR-073a, plan C1)**: `Check result` abre un
  Dialog que ejecuta el `publish-check` (que ya reconcilia en solo lectura un intento
  incierto, research 018/006). Si sigue incierto explica qué comprobar en la plataforma y
  ofrece el reconocimiento existente de 006 FR-041 ("I checked … and it was not published")
  que habilita `Publish again` con `confirm_remote_checked=true`. Retry directo, Reschedule y
  Move to drafts permanecen rechazados mientras el resultado sea incierto; si la
  reconciliación lo resuelve, se aplica el estado determinado (Published, o Failed con R6).
- **Rationale**: sin esta salida un Post Needs review no tendría recuperación salvo cancelar,
  rompiendo 006 FR-041.

## R-12 Text posts

- **Decision**: misma página/controlador de Publish con `mode: "text"` en
  `/p/:pid/posts/new[?posts=]`. Compose: texto + hashtags comunes (obligatorio texto) y
  destinos con capacidad `text` (account health `capabilities`), el resto "Needs media".
  `Continue` → `POST /projects/{id}/text-publications` (ya guarda el texto como override
  explícito). La personalización por destino se hace en Review (`PATCH` overrides), porque el
  endpoint de texto no acepta `targets`.
- **Constraint/plan decision**: sin `Customize` en Compose para texto (el endpoint no lo
  admite y hacerlo tras crear no sería atómico).

## R-13 Responsive

- **Decision**: añadir breakpoint `xl = 1280`. DetailSurface acepta
  `panelFrom: "lg" | "xl"` (default `lg`, Accounts sin cambios). Library y Calendar usan
  `xl` (Drawer en 1024–1279); Posts List usa `lg`. Publish no usa DetailSurface. Grid de
  Library con CSS `repeat(auto-fill, minmax(…))` sobre el contenedor (se adapta solo al
  panel). Bottom nav oculta por `handle: { taskMode: true }` de ruta (`useMatches` en
  AppShell), solo en `sm`.

## R-14 Polling

- **Decision**: una sola fuente por superficie.
  - Posts (lista, detail, calendar): `usePostsData(projectId)` = `listPublications` con el
    intervalo actual (rápido si hay `publishing`, lento si hay armados esperando); Post detail
    lee su Post de esa lista (sin `useLivePublication` propio). Al detectar cambios de estado
    → `reloadOverview()` (readiness).
  - Publish task: `getPublication` solo de los ids del set en `publishing` (2 s) hasta que no
    quede ninguno; opciones/publish-check se refrescan tras autosave, no por intervalo.
  - Creator Info: una lectura al abrir la card Direct Post y con `Retry`; nunca en intervalo.
