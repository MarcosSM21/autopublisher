---

description: "Task list for Feature 018 — UX Foundation & Responsive App"
---

# Tasks: UX Foundation & Responsive App

**Input**: Design documents from `/specs/018-ux-foundation-responsive/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md)

**Tests**: pedidos por la spec (sección Testing Strategy) y por research §15, en un conjunto
**mínimo de contratos agrupado por journey**. Sin snapshots, sin asserts de CSS/píxeles, sin
matrices plataforma × estado, sin duplicar tests de workflows de 019 que no cambian ni
lógica ya cubierta por tests existentes (p. ej. `AutomationStatus.test.tsx`). Durante la
implementación solo tests dirigidos, una vez al final de cada bloque; un test que ya pasó no
se repite si su código no ha cambiado. Suites completas: solo en la CI del PR. Checks
estáticos: una sola vez, al final (T066).

**Organization**: por fases técnicas en orden de dependencias, cada una asociada a su
historia de usuario. Fases foundational (read-models, design system) sin etiqueta de
historia. Historias: US1 Home/Attention · US2 Navegación/shell · US3 Accounts · US4
Onboarding · US5 Project strip · US6 Settings · US7 Estados y terminología.

**Feature boundary**: ninguna tarea rediseña Library, Media detail, Publish/Distribute,
Posts List, Calendar ni Post detail (Feature 019). En esos componentes solo se permiten:
selección controlada por URL, `onOpenQueue → onOpenPosts`, retirada de `AutomationStatus`
de la cola, texto "Publish…" y `accountLabel()` para handles nulos. Sus clases CSS actuales
se conservan.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivos distintos, sin dependencias pendientes)
- **[Story]**: US1–US7 según spec.md
- Rutas relativas a la raíz del repositorio (`backend/`, `frontend/`)

---

## Phase 1: Technical foundation — routing y montaje de workflows existentes (US2)

**Goal**: URLs reales para todas las secciones, medios y posts; Projects, Accounts, Library
y Posts existentes siguen funcionando bajo las nuevas rutas, sin rediseño y sin regresión
temporal.

**Independent Test**: quickstart.md §5 (deep link, reload, back/forward, not found).

- [X] T001 Añadir dependencias exactas `react-router@8.4.0` y `@radix-ui/react-dialog@1.1.23` (`npm install --save-exact`) en `frontend/package.json` y `frontend/package-lock.json`; ninguna otra dependencia de UI (research §1, §11).
- [X] T002 [P] [US2] Crear `frontend/src/ui-preferences.ts`: `getLastProjectId(): number | null`, `setLastProjectId(id: number)`, `clearLastProjectId()` con la única clave `autopublisher.lastProjectId`, todo envuelto en `try/catch` (storage ausente o que lanza → `null`/no-op); solo acepta enteros positivos (research §10, data-model §3).
- [X] T003 [US2] Crear `frontend/src/routes.tsx` con el array `routes` exacto de research §2 / contracts/ui.md §1 y helper `parseId(param): number | null` (entero positivo o null); incluir en el mismo bloque `frontend/src/shell/NotFound.tsx` (mensaje + **una** acción: "Go to Home" o "Back to <section>") y `frontend/src/shell/RouteError.tsx` (`errorElement`, HTML semántico; se re-estiliza en Phase 4). Elementos provisionales: `AppShell` = nav mínima de enlaces + `<Outlet>` (el shell responsive llega en Phase 5); `HomePage` provisional que monta el `ProjectList` existente (`frontend/src/components/ProjectList.tsx`) para crear y seleccionar proyectos, navegando a `/p/:id/library`; `SettingsPage` placeholder con su `<h1>`; `p/:projectId` → `ProjectLayout`, index → `<Navigate to="library" replace>`, `library`, `library/:mediaId`, `posts`, `posts/:postId`, `accounts`, `accounts/new`, `accounts/:accountId` (las tres de Accounts montan `LegacyAccountsSection` hasta Phase 8), `*` → `NotFound` en ambos niveles.
- [X] T004 [US2] Crear `frontend/src/pages/ProjectLayout.tsx` y añadir `getProject(id)` (`GET /api/projects/{id}`, ya existe en backend) en `frontend/src/api.ts` y en `frontend/src/test-fake-api.ts` (404 si no existe): valida `:projectId` con `parseId`, carga el proyecto, muestra skeleton/`NotFound` (y `clearLastProjectId()` si era el guardado), `setLastProjectId` al cargar, y entrega `{ project, reloadProject }` vía `useOutletContext` (hook tipado `useProject()`). Incluye temporalmente, **movido tal cual** desde `ProjectDetail.tsx`, el bloque de cabecera de proyecto: nombre, badge activo/inactivo, descripción, "Edit project" (`ProjectForm`) y "Activate/Deactivate project" (se re-estiliza en T052).
- [X] T005 [US2] Crear `frontend/src/pages/LegacyAccountsSection.tsx` extrayendo **tal cual** de `ProjectDetail.tsx` la carga de cuentas (`listAccounts`), `AccountList` (editar, activar/desactivar, paneles de conexión) y el alta legacy con `AccountForm` (`createAccount`, deshabilitada si el proyecto está inactivo), usando `useProject()`. Es temporal: se elimina en T057.
- [X] T006 [US2] En `frontend/src/components/ContentLibrary.tsx`: sustituir `useState(selectedId)` por props controladas `selectedId: number | null` y `onSelect(id: number | null)`; renombrar `onOpenQueue` → `onOpenPosts(postId?: number)` también en `frontend/src/components/ContentDetail.tsx` y `frontend/src/components/Distribute.tsx`; sin otros cambios de contenido ni comportamiento.
- [X] T007 [US2] En `frontend/src/components/PublicationQueue.tsx`: props controladas `selectedId`/`onSelect` en lugar de `useState(selectedId)`; retirar `<AutomationStatus>` y el `<h3>Queue</h3>` (el título lo pone la página); mantener `PublicationDetail` inline y el polling tal cual.
- [X] T008 [US2] Crear `frontend/src/pages/LibraryPage.tsx` y `frontend/src/pages/PostsPage.tsx`: `<h1>Library</h1>`/`<h1>Posts</h1>`, montan `ContentLibrary`/`PublicationQueue` con `selectedId` desde `:mediaId`/`:postId` (`parseId`), `onSelect` → `navigate` a `library[/:id]`/`posts[/:id]`, `onOpenPosts` → `/p/:id/posts[/:postId]`. Pertenencia: si hay id en la URL, la página llama a `getContent(id)` / `getPublication(id)` (ya existen en `frontend/src/api.ts`) y compara `project_id`; id no numérico, 404 o de otro proyecto → `NotFound` de sección. **No** se añade ningún callback ni prop nueva a los componentes de 019 para esto.
- [X] T009 [US2] Sustituir el arranque en `frontend/src/main.tsx` por `createBrowserRouter(routes)` + `<RouterProvider>`; eliminar `frontend/src/App.tsx` y `frontend/src/components/ProjectDetail.tsx` (sus responsabilidades ya viven en T003, T004 y T005). `ProjectList.tsx` se mantiene hasta T050; `AccountList.tsx` y `AccountForm.tsx` hasta T057.
- [X] T010 [US2] Ajustar tests existentes sin reescribir casos: `frontend/src/components/ContentLibrary.test.tsx` y `frontend/src/components/PublicationQueue.test.tsx` (render con `selectedId`/`onSelect` controlados por un wrapper de test; **eliminar** las aserciones de pausa de la cola sin reubicarlas — ya las cubre `AutomationStatus.test.tsx`); eliminar `frontend/src/App.test.tsx`; transformar `frontend/src/components/ProjectDetail.test.tsx` en `frontend/src/pages/LegacyAccountsSection.test.tsx` con los mismos casos de cuentas (temporal, se elimina en T057).
- [X] T011 [US2] Actualizar `frontend/src/storage-safety.test.tsx` (research §10): el test de código fuente permite `localStorage` **solo** en `src/ui-preferences.ts`; los flujos espiados exigen que `setItem` solo reciba la clave `autopublisher.lastProjectId`; `sessionStorage`, IndexedDB y cookies siguen prohibidos.
- [X] T012 [US2] Crear el helper `renderRoute(path, { api })` en `frontend/src/test-utils.tsx` (`createMemoryRouter(routes, { initialEntries: [path] })` + `FakeApi`) y `frontend/src/routes.test.tsx` (pocos casos): crear un proyecto desde la Home provisional con base vacía aterriza en `library`; deep link a `library/:mediaId` y `posts/:postId` muestra el detalle existente; `/p/:id` redirige a `library`; back/forward con `router.navigate(-1/1)`; not found para id inexistente, de otro proyecto y no numérico (proyecto, medio, post); `lastProjectId` se escribe al entrar y se ignora/limpia si es inválido o el storage lanza.
- [X] T013 [US2] Ejecutar solo `cd frontend && npx vitest run src/routes.test.tsx src/storage-safety.test.tsx src/pages/LegacyAccountsSection.test.tsx src/components/ContentLibrary.test.tsx src/components/PublicationQueue.test.tsx src/components/ContentDetail.test.tsx src/components/Distribute.test.tsx` y corregir hasta verde.

**✅ Checkpoint A — Routing + workflows legacy operativos** (tests: los de T013, sin
repetir). Manual con `npm run dev` y **base vacía**: crear proyecto, reload, deep links,
back/forward, abrir medio y post por URL, `/p/:id` aterriza en Library, editar/activar
proyecto y alta/edición legacy de cuentas siguen funcionando. Revisión del usuario.

---

## Phase 2: Backend read-model foundation (foundational)

**Purpose**: `display_state`, account health, platform availability y overview: solo
lectura, sin persistencia, sin red, sin `reconcile`, sin efectos secundarios. Reutiliza
`is_overdue`, `auto_publish_state`, `needs_manual_review`, `latest_attempts`, `local_check`,
`*_configured()`.

- [X] T014 [P] En `backend/app/schemas.py` añadir los modelos de respuesta de contracts/api.md §1–§3: `PostDisplayState` (Literal de 11 valores), `OverviewRead` (`automation`, `attention`, `upcoming`, `projects`) con `AttentionItemRead`, `AttentionActionRead`, `UpcomingPostRead`, `ProjectSummaryRead`, `OnboardingRead`; `AccountHealthRead` (`state` Literal de 5 valores, `identity`, `expires_at`, `expiring`, `capabilities`, `issue`, `can_discard`); `PlatformAvailabilityRead`. Añadir `display_state: PostDisplayState` a `PublicationRead`.
- [X] T015 En `backend/app/overview.py` (nuevo) implementar la función pura `post_display_state(status, armed, scheduled_at, paused, latest_attempt, now)` con la tabla exacta de research §7 (incluye `needs_review` y `scheduled_paused`; manual con hora pasada → `missed`), reutilizando `is_overdue` y `needs_manual_review`; en `backend/app/publications.py` (`publication_to_read`) rellenar `display_state` con ella. Es la única implementación de la regla.
- [X] T016 [P] Crear `backend/tests/test_post_display_state.py`: **un** test parametrizado sobre las filas de la tabla de research §7 (función pura, sin BD).
- [X] T017 [P] Definir la dataclass `ConnectionHealth` (`state`, `identity`, `expires_at`, `issue`) en `backend/app/accounts.py` y añadir `health_of(connection, now) -> ConnectionHealth` en cada módulo de conexión (`backend/app/youtube_connections.py`, `instagram_connections.py`, `threads_connections.py`, `tiktok_connections.py`, `telegram_connections.py`), leyendo **solo columnas SQLite** según research §8 (IG/Threads `credential_expires_at`, TikTok `refresh_expires_at`; Telegram sin canal → `setup_required`; `flood_wait_until` → issue informativo). Nunca lee el keyring ni llama a `connection_to_read`.
- [X] T018 En `backend/app/overview.py` implementar `account_health(session, accounts, now)` por lotes (cuentas + 5 consultas `IN` a las tablas de conexión): precedencia `inactive → not_connected → reconnect_needed → setup_required → ready`, `expiring` (≤ 7 días sobre `ready`), capacidades desde una tabla estática por plataforma (`text` solo si el publisher declara `accepts_text_only`), `can_discard` (provisional: `handle IS NULL`, sin conexión, sin publicaciones; `EXISTS` agrupado — el caso `true` solo es alcanzable tras la migración `0017` y se prueba en T032); y el endpoint `GET /api/projects/{project_id}/account-health` (404 si no existe) (contracts/api.md §2) (depende de T014, T017).
- [X] T019 [P] Crear `backend/app/platform_availability.py` con `GET /api/platforms` reutilizando `youtube_connections.oauth_configured`, `instagram_connections.oauth_configured`, `threads_connections.oauth_configured`, `tiktok_connections.oauth_configured`, `telegram_connections.configured` y `MediaDelivery.configured()` (Instagram/Threads → `partial` sin media delivery); X → `coming_soon`; mensajes saneados propios; nunca rutas, variables de entorno, contenidos, ids ni texto de excepciones (contracts/api.md §3).
- [X] T020 En `backend/app/overview.py` implementar la derivación de atención de research §7 exactamente: reglas 1–7 con acción/destino únicos, un item por post (menor prioridad) y por cuenta, plegado de `incomplete` solo-conexión en el item `reconnect` (`affected_posts`), proyectos inactivos solo reglas 1, 2 y 4, cuentas inactivas sin 5/7, pausa (regla 3 con "Resume automation" → settings; automáticos futuros solo en `automation.paused_automatic_posts`), ventana de 7 días, orden secundario por regla. Reglas 5/7 usan `account_health()` de T018. `local_check()` se invoca solo para posts `scheduled` de los próximos 7 días no `missed`, sin `reconcile_uncertain`; cualquier excepción (`CredentialStoreUnavailable`, `AppError` de configuración u otra) → item `incomplete` con `detail` "Couldn't verify requirements" (nunca listo ni oculto) (depende de T015, T018).
- [X] T021 En `backend/app/overview.py` implementar `upcoming` (≤ 5 globales, proyectos activos, `scheduled_at > now` asc), `projects[]` (`accounts_active`, `accounts_ready` **reutilizando `account_health()`** sin recalcular, `attention_count`, `next_post`, `onboarding` con `EXISTS` agrupados) y el endpoint `GET /api/overview?project_id=` con las consultas de research §6; registrar los routers de `overview` y `platform_availability` en `backend/app/main.py` (depende de T019, T020).
- [X] T022 Crear `backend/tests/test_overview_attention.py`: (a) **un** test parametrizado con un caso mínimo por regla (manual review, failed, missed automático, missed manual, missed por pausa, needs action, reconnect, incomplete, couldn't verify — `local_check` forzado a lanzar —, expiring) comprobando `kind`, `action.label` y `action.target`; (b) **un** test de dedup/prioridad/plegado; (c) **un** test de filtro `project_id`, proyecto inactivo (solo 1/2/4) y cuenta inactiva; (d) **un** test de no red / no escrituras: gateways fake que lanzan si se llaman y filas/`updated_at` idénticos antes y después de `GET /api/overview`.
- [X] T023 [P] Crear `backend/tests/test_account_health.py`: **un** test parametrizado con un caso representativo por estado (`ready`, `reconnect_needed` por status, `reconnect_needed` por expiración, `setup_required` Telegram sin canal, `not_connected`, `inactive`) y uno de `expiring`; endpoint 404. Sin matriz plataforma × estado y sin `can_discard=true` (T032).
- [X] T024 [P] Crear `backend/tests/test_platforms_api.py`: configured / partial / not_configured / coming_soon con ficheros de configuración temporales con valores centinela; aserción de que ni los valores ni las rutas aparecen en el JSON.
- [X] T025 Ejecutar solo `cd backend && uv run pytest tests/test_post_display_state.py tests/test_account_health.py tests/test_platforms_api.py tests/test_overview_attention.py tests/test_publications_queue.py` (el último por el campo nuevo en `PublicationRead`) y corregir hasta verde.

---

## Phase 3: Account model + provisional account flow (US3, backend)

**Goal**: crear cuentas solo con plataforma, adoptar la identidad al conectar, "Discard"
restringido y seguro.

- [X] T026 [US3] Crear `backend/migrations/versions/0017_account_handle_optional.py` (`batch_alter_table`): `accounts.handle` y `accounts.handle_key` nullable; `downgrade` falla explícitamente si hay filas con `handle IS NULL`; en `backend/app/models.py` tipar ambos como `Mapped[str | None]` (data-model §1).
- [X] T027 [US3] En `backend/app/schemas.py`: `AccountCreate.handle: Handle | None = None`; `AccountRead.handle` y `PublicationAccountSummary.handle` → `str | None`; `AccountUpdate` sin cambios (no admite `null`). En `backend/app/accounts.py` (`create_account`): sin `handle` → `handle = handle_key = None` y sin `ensure_handle_available`; con `handle` → igual que hoy.
- [X] T028 [US3] En `backend/app/accounts.py` añadir `adopt_connected_identity(session, account, candidate: str | None) -> None` (sin commit): si `account.handle is None`, valida `candidate` con **las mismas reglas que el tipo `Handle`** (`clean_handle` + longitud 1–100); si es válido y libre en `(project, platform)` → asigna `handle`/`handle_key`; si es inválido, vacío o colisiona → deja `NULL`; nunca sobrescribe. Hacer `account_label()` tolerante a `NULL` (`"<Platform> account"` + `display_name` si existe) y sustituir los usos directos de `account.handle` en mensajes por `account_label()` en `backend/app/*.py` (research §5).
- [X] T029 [US3] Llamar a `adopt_connected_identity` **antes del commit** en la función de completado de cada integración en `backend/app/`: `youtube_connections.complete_connection` (`channel_handle` sin `@` o `channel_title`), `instagram_connections.complete_connection` (`username`), `threads_connections.complete_connection` (`username`), `tiktok_connections.complete_connection` (`display_name`), `telegram_connections._complete_login` (`username` o `display_name`). Una línea por integración; ninguna otra lógica de conexión cambia.
- [X] T030 [US3] En `backend/app/accounts.py` implementar `DELETE /api/accounts/{account_id}` (contracts/api.md §5): 404 si no existe; **adquirir** `account_session(account_id, wait=False)` (si está tomado → `409 account_busy`) y **mantenerlo** durante todo lo siguiente: comprobar que es provisional (si no → `409 account_not_discardable`); invalidar intentos en memoria — `expire_for_account(account_id)` en `app.state.oauth_attempts`, `instagram_attempts`, `threads_attempts`, `tiktok_attempts` y `discard(account_id)` en `app.state.telegram_logins` —; en una transacción, re-comprobar ausencia de conexión y publicaciones y borrar la fila (presets por `CASCADE`). El lock mantenido cubre también la carrera con los pasos de login de Telegram. No contacta plataformas ni el almacén seguro.
- [X] T031 [US3] Carrera Discard ↔ callback OAuth (riesgo compartido; YouTube como caso representativo) en `backend/app/youtube_connections.py`: confirmar que (a) un callback con `state` de un intento expirado por Discard responde "Authorization not valid" sin crear conexión, y (b) si el callback ya había consumido su `state` y la cuenta se descarta antes de completar, `complete_connection` falla (FK / cuenta inexistente) por el camino existente `session.rollback()` + `_discard_secret`; mapear ese caso "la cuenta ya no existe" a un mensaje claro de autorización no válida en lugar de "channel already connected", dentro del mismo `except`. No replicar en otras integraciones salvo que T032 demuestre el mismo defecto.
- [X] T032 [US3] Ampliar `backend/tests/test_accounts.py` y `backend/tests/test_migrations.py`: crear sin handle (`handle: null`) y con handle (legacy, igual que hoy); adopción al completar YouTube (fake gateway) y Telegram (`fakes_telegram`); candidato inválido o en colisión deja `NULL`; handle existente no se sobrescribe; `can_discard=true` en `GET /account-health` para una cuenta provisional; `DELETE` → 204 provisional, 409 con identidad, con conexión (también `reconnect_required`), con posts, 409 `account_busy` con el lock tomado; tras Discard, intento OAuth expirado y login Telegram descartado; **carrera representativa YouTube**: (1) crear intento y consumir su `state`, (2) descartar la cuenta, (3) llamar a `complete_connection` con `FakeCredentialStore`, (4) rollback hecho, (5) el secreto temporal ya no está en el almacén, (6) no existe `YouTubeConnection`, (7) mensaje de error claro; migración `0017` sube y baja con datos legacy y `downgrade` falla con una cuenta provisional.
- [X] T033 [US3] Ejecutar solo `cd backend && uv run pytest tests/test_accounts.py tests/test_migrations.py tests/test_youtube_connect.py tests/test_youtube_secrets.py tests/test_telegram_connections.py` (las tres últimas por el cambio en el completado y la limpieza de secretos); añadir `tests/test_account_health.py` y `tests/test_overview_attention.py` **solo** si T027/T028 modificaron `backend/app/overview.py` o `account_label()` usado por el read-model; corregir hasta verde.

**✅ Checkpoint B — Read-model + provisional Accounts** (tests: los de T025 y T033, sin
repetir). Manual: `curl` de quickstart §2. Revisión del usuario.

---

## Phase 4: Design system (foundational)

**Purpose**: tokens y primitivas mínimas de contracts/ui.md §4–§5 con las recomendaciones
adoptadas de UI UX Pro Max (research §11), conviviendo con la CSS legacy de 019.

- [X] T034 [P] En `frontend/src/types.ts` añadir los tipos de estado que necesita `StatusBadge`: `PostDisplayState` (11 valores), `AccountHealthState` (`ready | reconnect_needed | setup_required | not_connected | inactive`), `PlatformStatus` (`configured | partial | not_configured | coming_soon`), y `display_state: PostDisplayState` en `Publication` (con comentario "Keep in sync with backend/app/schemas.py"); actualizar las fixtures de `frontend/src/test-fake-api.ts` para incluir `display_state`.
- [X] T035 **UI UX Pro Max — instalación**: copiar `.claude/skills/ui-ux-pro-max/` del tag `v2.15.0` del repo oficial `nextlevelbuilder/ui-ux-pro-max-skill` a `.claude/skills/ui-ux-pro-max/`, añadir esa ruta a `.gitignore` y comprobar con `git check-ignore` y `git status --short` que no queda nada versionable. Ejecutar sus scripts solo con `python3 -s -E` (stdlib, sin red; auditado en research §11). No es dependencia del runtime.
- [X] T036 **UI UX Pro Max — consulta y documentación**: crear `docs/design-system.md` (inglés) con principios, tokens, primitivas, mapa de `StatusBadge`, breakpoints, foco y motion, y la tabla de recomendaciones **consultadas / adoptadas / rechazadas con motivo** de research §11, re-consultando con la skill instalada las de navegación, formularios, touch, foco, color-only y reduced motion para confirmar que siguen vigentes en `v2.15.0`.
- [X] T037 [P] Crear `frontend/src/ui/tokens.css` (capa primitiva + capa semántica; tipografía system stack 16 px/1.5 y escala; espaciado 4–48; radios; `--shadow-overlay`; colores base, acción `#1D4ED8`, estados AA; foco `:focus-visible` 2 px + offset; `--target-min: 44px`; breakpoints 768/1024; `prefers-reduced-motion`) importado desde `frontend/src/main.tsx`. En `frontend/src/index.css` **no** sustituir el archivo: solo adaptar `:root` y `body` para consumir tokens (fuente, color, fondo, sin padding de página que ahora gestiona el shell) y eliminar únicamente reglas de componentes ya eliminados (`.layout`, `.project-button`); **conservar** `.badge`, `.actions`, `.error`, `.muted`, `.account`, `.queue-section`, `ul.plain` y el resto de clases que usan Library, Distribute, Posts y Post Detail hasta Feature 019. Los estilos nuevos viven encapsulados en `frontend/src/ui/*.css` y `frontend/src/shell/*.css` (clases con prefijo propio, p. ej. `ap-`). Sin dark mode.
- [X] T038 [P] Crear `frontend/src/ui/Button.tsx` (primary/secondary/ghost/danger, `loading`, `as="link"` con `Link`), `frontend/src/ui/IconButton.tsx` (`aria-label` requerido por tipo), `frontend/src/ui/Icon.tsx` (SVG inline: home, library, posts, accounts, settings, more, back, close, alert, check, clock, plus; `aria-hidden`).
- [X] T039 [P] Crear `frontend/src/ui/Badge.tsx` y `frontend/src/ui/StatusBadge.tsx` con **un único mapa** etiqueta+tono+icono para `PostDisplayState` (Draft, Scheduled · automatic, Scheduled · manual, Scheduled · paused, Publishing, Published, Failed, Needs review, Needs action, Missed, Cancelled), `AccountHealthState` (Ready, Reconnect needed, Finish setup, Not connected, Inactive) y `PlatformStatus` (contracts/ui.md §5); texto siempre visible (depende de T034).
- [X] T040 [P] Crear `frontend/src/ui/Card.tsx`, `frontend/src/ui/EmptyState.tsx` (`action` primaria obligatoria y única por tipo, `secondary?` enlace), `frontend/src/ui/ErrorState.tsx` (`onRetry`), `frontend/src/ui/Skeleton.tsx` (`aria-busy` en contenedor).
- [X] T041 [P] Crear `frontend/src/ui/Dialog.tsx` exportando `Dialog`, `Drawer` y `Sheet` sobre `@radix-ui/react-dialog` (título obligatorio, Escape/overlay cierran, foco devuelto), `frontend/src/ui/Disclosure.tsx` (`aria-expanded`/`aria-controls`, Escape cierra y devuelve foco, sin Radix) y `frontend/src/ui/useMediaQuery.ts` (`matchMedia` con fallback seguro en jsdom).
- [X] T042 Crear `frontend/src/ui/DetailSurface.tsx`: `lg` panel lateral no modal, `md` `Drawer`, `sm` página completa con botón "Back"; cerrar/Back = `navigate(parentPath)`; modo elegido con `useMediaQuery` (depende de T041).
- [X] T043 Crear `frontend/src/ui/detail-surface.test.tsx` (mock de `matchMedia`): modo drawer — foco dentro, Tab no sale, Escape cierra navegando al padre y el foco vuelve al disparador; modo página — Back navega al padre; `EmptyState` renderiza una sola acción primaria. Ejecutar solo este archivo.
- [X] T044 **UI UX Pro Max — revisión final del design system** contra research §11 y `docs/design-system.md`: comprobar una a una las recomendaciones adoptadas — contraste AA de cada par de tokens (herramienta de contraste), foco visible ≥ 2 px / 3:1, objetivos ≥ 44 px en primitivas, estado nunca solo por color, ninguna información o acción solo con hover (FR-059), formularios a ancho completo en `sm` (FR-014), una animación por vista y reduced motion, sin emoji, labels visibles — y anotar el resultado en `docs/design-system.md`; corregir tokens/primitivas si algo no cumple.

---

## Phase 5: Responsive App Shell (US2)

**Goal**: un único shell — sidebar (escritorio), rail + TopBar (tablet), bottom nav + TopBar
con More (móvil). CSS decide el layout; JS solo donde cambia el comportamiento.

- [X] T045 [US2] Crear `frontend/src/shell/ProjectSelector.tsx` (lista de proyectos con `listProjects`; cambiar de proyecto conserva la sección `library|posts|accounts` y descarta el id de detalle; sin proyectos → enlace a Home) y `frontend/src/shell/useProjectTarget.ts` (proyecto de la URL, o `getLastProjectId()` válido, o primer proyecto activo/primero; `null` sin proyectos → destinos de proyecto `aria-disabled`).
- [X] T046 [US2] Crear `frontend/src/shell/PrimaryNav.tsx` (un único `<nav aria-label="Main">` con `NavLink` Home/Library/Posts/Accounts/Settings, `aria-current="page"`), `frontend/src/shell/TopBar.tsx` (visible en `sm` **y** `md`: `ProjectSelector`; el `Disclosure` "More" con Settings **solo en `sm`**) y `frontend/src/shell/AppShell.tsx` (skip link "Skip to content", un `<main id>`, `ProjectSelector` en el sidebar en `lg` y en la TopBar en `sm`/`md`, elegido con `useMediaQuery` para no duplicar nodos), con `frontend/src/shell/shell.css` (sidebar `lg`; rail `md`; bottom nav fija `sm` con 4 destinos, `safe-area-inset-bottom` y compensación de altura; Settings oculto en la bottom nav; objetivos ≥ 44 px; 0 scroll horizontal). Sustituir el `AppShell` provisional en `frontend/src/routes.tsx`.
- [X] T047 [US2] Crear `frontend/src/shell/shell.test.tsx` (pocos casos): destinos y `aria-current` según la URL; destinos de proyecto desde Home resuelven al último proyecto válido; "More" abre/cierra y lleva a Settings en `sm` y no existe en `md`; `ProjectSelector` se renderiza una sola vez según `matchMedia`; cambiar de proyecto en Posts navega a Posts del otro proyecto. Ejecutar solo `src/shell/shell.test.tsx` y `src/routes.test.tsx` (este último porque cambia el `AppShell` del árbol).

**✅ Checkpoint C — Design system + shell** (tests: los de T043 y T047, sin repetir).
Manual en DevTools a 375×812, 768×1024 y 1280×800 (quickstart §6: navegación por breakpoint,
TopBar en móvil/tablet, More solo en móvil, 0 scroll horizontal, foco visible, touch ≥ 44 px,
pantallas de 019 sin cambio visual relevante). Revisión del usuario.

---

## Phase 6: Home / Attention (US1)

**Goal**: "What needs my attention, and what is happening next?" en ≤ 5 s.

**Independent Test**: quickstart.md §4.

- [X] T048 [US1] En `frontend/src/types.ts` añadir los tipos restantes de contracts/api.md §1–§3 (`OverviewRead`, `AttentionItem`, `UpcomingPost`, `ProjectSummary`, `AccountHealth`, `PlatformAvailability`); en `frontend/src/api.ts` `getOverview(projectId?)`, `getAccountHealth(projectId)`, `listPlatforms()`, `discardAccount(id)`; en `frontend/src/test-fake-api.ts` respuestas configurables para esos endpoints (fixtures directos, sin re-implementar la derivación) y `DELETE /accounts/{id}`.
- [X] T049 [US1] Crear `frontend/src/pages/CreateProjectDialog.tsx` (reutiliza `ProjectForm` en `Dialog`; al crear navega a `/p/:id/library`).
- [X] T050 [US1] Crear `frontend/src/pages/HomePage.tsx` con `AttentionList`/`AttentionItem`, `UpNext`, `ProjectsList` y `AutomationPausedBanner` en `frontend/src/pages/home/`, usando **solo** `getOverview()` (ninguna regla de atención en el frontend): orden banner → Needs attention | Everything OK → Up next → Projects; `?project=<id>` solo **filtra** `attention` en cliente por `project.id`, con chip "Showing <name> · Show all" (id inválido → aviso + Show all); cada item: título, contexto, `StatusBadge` si hay post, **un** botón primario que navega al destino de `action.target`; Everything OK con próxima publicación o "Nothing scheduled"; Up next ≤ 5 filas que enlazan a su post; Projects con "N need attention"/"All good" → `/p/:id/library` y "New project" secundario (`CreateProjectDialog`); skeleton en carga; `ErrorState` + Retry en error (nunca OK sin datos); sin proyectos → solo `EmptyState` "Create your first project". Sustituir la Home provisional en `frontend/src/routes.tsx` y eliminar `frontend/src/components/ProjectList.tsx`.
- [X] T051 [US1] Crear `frontend/src/pages/home.test.tsx`: items con una sola acción y destino correcto (post, account, settings); filtro `?project=` y "Show all"; Everything OK; error → Retry sin OK; banner de pausa; sin proyectos → crear proyecto y aterrizar en Library. Ejecutar solo este archivo y `src/routes.test.tsx` (cambia la Home del árbol).

---

## Phase 7: Project context — strip, onboarding y empty states (US5, US4)

**Goal**: contexto compacto del proyecto y onboarding por empty states encadenados, sin
Project Overview.

**Independent Test**: quickstart.md §3 (hasta "identify and reach Publish…").

- [X] T052 [US5] En `frontend/src/pages/ProjectLayout.tsx`: cargar **una sola vez** `getOverview(projectId)` y compartirlo vía `useOutletContext` (`overview`, `reloadOverview`) con la franja, la checklist y las páginas hijas; sustituir el bloque legacy de cabecera de T004 por cabecera compacta (nombre, badge "Inactive", `Disclosure` "Project actions" con Edit project — `ProjectForm` en `Dialog` — y Activate/Deactivate con `updateProject`). Crear `frontend/src/pages/project/ProjectStatusStrip.tsx`: `x/y accounts ready` → `accounts`; `N need attention` → `/?project=<id>`; `Next: <relative>` → post; "Automation paused" → `/settings`; omite elementos vacíos; sin listas ni gráficas.
- [X] T053 [US4] Crear `frontend/src/pages/project/OnboardingChecklist.tsx` (de `overview.projects[0].onboarding` del contexto): 3 pasos con estado, CTA primario solo en el siguiente (Connect an account → `accounts/new`; Import your first media → `library`; Publish… → primer medio sin uso `library/:mediaId`); oculto si `complete`; montado en `ProjectLayout`. Derivado, nunca persistido.
- [X] T054 [US4] Empty states con una sola acción primaria: en `frontend/src/pages/LibraryPage.tsx` sin medios → `EmptyState` "Import your first media" (abre el import existente de `ContentLibrary`); en `frontend/src/pages/PostsPage.tsx` sin posts → "Open the Library to publish your media"; en `frontend/src/components/ContentDetail.tsx` el botón "Distribute" pasa a "Publish…" (único cambio de texto en ese componente; actualizar solo las aserciones de ese texto en sus tests existentes).
- [X] T055 [US4] Crear `frontend/src/onboarding.test.tsx`: Library vacía → "Import your first media"; Posts vacío → su único CTA; medio sin usar con "Publish…"; checklist visible con el CTA solo en el siguiente paso y oculta con `complete`; franja con sus tres enlaces; exactamente un CTA primario por empty state. (El empty state de Accounts se prueba en T060.) Ejecutar solo este archivo y `src/components/ContentDetail.test.tsx`.

**✅ Checkpoint D — Home + project context** (tests: los de T051 y T055, sin repetir).
Manual: quickstart §3 hasta "Publish…" (salvo el paso de Accounts, aún legacy) y §4 con la
app real. Revisión del usuario.

---

## Phase 8: Accounts UX (US3, frontend)

**Goal**: salud de cuenta de un vistazo, alta `Add account → choose platform → Connect`,
detalle con progressive disclosure. Reutiliza los 5 paneles de conexión sin duplicar OAuth,
polling ni lógica.

**Independent Test**: quickstart.md §3 paso 3 y spec US3.

- [X] T056 [US3] En `frontend/src/utils.ts` hacer `accountLabel()` tolerante a `handle: null` (`"<Platform> account"` + display name) y tipar `handle: string | null` en `frontend/src/types.ts`; sustituir los usos directos de `account.handle` en `frontend/src/components/*ConnectionPanel.tsx` (aria-labels y textos) y demás componentes por `accountLabel()`; ningún otro cambio en esos componentes.
- [X] T057 [US3] Crear `frontend/src/pages/accounts/AccountCard.tsx` y `frontend/src/pages/AccountsPage.tsx`: lista desde `getAccountHealth`, activas primero e inactivas atenuadas; tarjeta con plataforma, identidad o "Not connected yet", `StatusBadge` (5 estados), capacidades, issue, aviso de caducidad, **una** acción primaria por estado (Reconnect / Finish setup / Connect / ninguna) → `accounts/:id`, enlace "Details"; botón "Add account"; sin cuentas → `EmptyState` "Connect an account". Reemplazar `LegacyAccountsSection` en `frontend/src/routes.tsx` y eliminar `frontend/src/pages/LegacyAccountsSection.tsx`, `frontend/src/pages/LegacyAccountsSection.test.tsx`, `frontend/src/components/AccountList.tsx` y `frontend/src/components/AccountForm.tsx`.
- [X] T058 [US3] Crear `frontend/src/pages/accounts/AccountDetail.tsx` en `DetailSurface` (`accounts/:accountId`; not found si la cuenta no está en `getAccountHealth` del proyecto): estado, identidad, issue y acción principal visibles; nombre visible editable (`updateAccount`), Activate/Deactivate, "Discard" solo con `can_discard`; `<details>` "Connection & technical details" cerrado por defecto que contiene el `<Platform>ConnectionPanel` existente, abierto automáticamente cuando la acción principal es Connect/Reconnect/Finish setup; el panel permanece montado mientras haya un intento en curso (`open` controlado; el contenido de `<details>` no se desmonta al cerrarse) para no cortar su polling.
- [X] T059 [US3] Crear `frontend/src/pages/accounts/AddAccountSheet.tsx` (`accounts/new`, `Sheet`): paso 1 tarjetas de las 6 plataformas desde `listPlatforms()` — `coming_soon` (X) deshabilitada con badge y no seleccionable, `not_configured` → mensaje + **Open Settings** como única acción; paso 2 "Connect <Platform>" → `createAccount(projectId, { platform })` y monta el panel de conexión existente de esa cuenta (su propio OAuth/pegado de URL/Telegram y su polling, sin duplicarlos); al quedar conectada → `navigate(accounts/:id)`; cerrar antes de conectar → `discardAccount` (si `409 account_busy`, avisar y reintentar al cerrar; otro fallo → la cuenta queda "Not connected" con Discard); Telegram cerrado sin canal → queda en "Finish setup".
- [X] T060 [US3] Crear `frontend/src/pages/accounts.test.tsx`: sin cuentas → `EmptyState` "Connect an account" con un único CTA; tarjetas por estado (incl. Finish setup y caducidad) con una acción; detalles técnicos plegados por defecto y abiertos en Reconnect; Add account sin pedir handle (X no seleccionable, not configured → Settings, Connect crea la cuenta con solo `platform`, cancelar → `DELETE`); detalle de cuenta de otro proyecto → not found; Discard ausente en cuentas no provisionales. Ejecutar solo este archivo y los tests existentes de los paneles tocados en T056 (`src/components/*ConnectionPanel.test.tsx`).

---

## Phase 9: Settings (US6)

**Goal**: automatización global y disponibilidad de configuración fuera del proyecto.

- [X] T061 [US6] Crear `frontend/src/pages/SettingsPage.tsx`: sección Automation con el `AutomationStatus` existente **sin cambios de lógica**; sección Platforms (`frontend/src/pages/settings/PlatformConfigurationList.tsx`) con `StatusBadge` (Configured / Partly configured / Not configured / Coming soon) y `message`; sin edición ni secretos. En `frontend/src/pages/PostsPage.tsx` mostrar el banner "Automation is paused … Resume" → `/settings` a partir del `overview` ya cargado por `ProjectLayout` (sin nueva llamada). Reemplazar el placeholder en `frontend/src/routes.tsx`.
- [X] T062 [US6] Crear `frontend/src/pages/settings.test.tsx`: Settings monta `AutomationStatus` (sin re-probar pausa/reanudación, cubiertas por `AutomationStatus.test.tsx`); estado de plataformas sin rutas ni valores; Posts muestra el banner y no el control. Ejecutar solo este archivo.

**✅ Checkpoint E — Accounts + Settings** (tests: los de T060 y T062, sin repetir). Manual
con una plataforma real configurada: alta real sin handle; cancelar el alta → Discard sin
cuenta residual; Telegram conectado sin canal → "Finish setup"; **reload durante OAuth**
(la cuenta queda Ready si el callback terminó, o "Not connected" con Discard si no); pausar y
reanudar desde Settings. Revisión del usuario.

---

## Phase 10: Terminology / state foundation (US7)

**Goal**: lenguaje de producto y estados que dicen qué va a ocurrir, solo en el alcance de
018.

- [X] T063 [US7] Revisar los textos visibles de `frontend/src/shell/`, `frontend/src/pages/` y `frontend/src/ui/` frente a contracts/ui.md §6 (Post/Media/Library/Posts/Draft; ningún "Publication", "Asset", "Queue", "Prepare", "Unscheduled", "preflight", "reconcile", "attempt", "checksum" fuera de `<details>` técnicos; ningún "Scheduled" sin modo), sin tocar textos internos de `ContentLibrary`, `Distribute`, `PublicationQueue` ni `PublicationDetail` (019); y añadir a `frontend/src/pages/home.test.tsx` **un** caso que recorre Home, Accounts y Settings con datos que cubren todos los `display_state` y estados de cuenta comprobando que no aparece ningún término prohibido ni "Scheduled" a secas. Ejecutar solo `src/pages/home.test.tsx`.

---

## Final Phase: Polish & cierre

- [X] T064 [P] Actualizar `README.md` (inglés): navegación y URLs, Home/Attention, Accounts (Add account sin handle, Finish setup, Discard), Settings (automatización y configuración de plataformas), nota de despliegue futuro (servir `index.html` como fallback de rutas no-`/api`); enlazar `docs/design-system.md`.
- [X] T065 Revisión manual final según `specs/018-ux-foundation-responsive/quickstart.md` §6 y §7: en 375×812, 768×1024 y 1280×800 sobre todas las rutas — 0 scroll horizontal, objetivos ≥ 44 px, formularios a ancho completo en móvil (FR-014), nada solo con hover (FR-059), recorrido completo con teclado, foco visible, drawer/sheet con foco atrapado y Escape, reduced motion —; y regresión funcional desde la nueva navegación (importar, Publish…, programar, Publish now, auto-publicar, conectar/reconectar una cuenta existente). Corregir lo encontrado con cambios dirigidos y ejecutar solo los tests de los archivos tocados.
- [X] T066 Checks estáticos **una sola vez**: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .`; `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`; `git diff --check`; revisión de seguridad del diff (sin secretos, `/api/platforms` sin rutas, storage solo `ui-preferences.ts`, skill ignorada por Git). Sin pytest/Vitest completos: los ejecuta la CI del PR.

---

## Dependencies & Execution Order

```text
Phase 1 (routing, legacy operativo) ──► Checkpoint A
Phase 2 (read-models) ─┐   backend; puede ir en paralelo a Phase 1
Phase 3 (account model) ┴► Checkpoint B
Phase 4 (design system) ─► Phase 5 (shell) ─► Checkpoint C        requiere Phase 1
Phase 6 (Home) ──────────┐  requiere 2, 5
Phase 7 (project context)┴► Checkpoint D   requiere 2, 5, 6 (T048)
Phase 8 (Accounts) ─┐  requiere 2, 3, 4, 5, 6 (T048)
Phase 9 (Settings) ─┴► Checkpoint E        requiere 2, 4, 7 (overview en ProjectLayout)
Phase 10 (terminology) ─► Final            requiere 6–9
```

Dependencias críticas:

- T003 → T004/T005 → T009: `App` y `ProjectDetail` solo se eliminan cuando la Home
  provisional (`ProjectList`), la cabecera de proyecto y `LegacyAccountsSection` ya existen.
- T014 → T015/T018/T019 → T020 → T021: esquemas antes de la derivación; `account_health`
  antes de la atención y del resumen de proyectos (que lo reutilizan).
- T026 → T027 → T028 → T029/T030 → T031 → T032: migración antes del modelo; Discard tras la
  adopción; la carrera se verifica sobre el Discard real.
- T034 → T039: tipos de estado antes de `StatusBadge`.
- T041 → T042 → T058: `DetailSurface` antes del detalle de cuenta.
- T048 bloquea Phases 6–9 (API y tipos de overview/health/platforms).
- T052 (overview único en `ProjectLayout`) antes de T053 y T061.
- Eliminaciones diferidas: `ProjectList` en T050; `LegacyAccountsSection`, su test,
  `AccountList` y `AccountForm` en T057.

## Parallel Opportunities

- Phase 1: T002 en paralelo a T003; Phase 2 completa en paralelo a Phase 1 (backend).
- Phase 2: T014, T017, T019 en paralelo; T016, T023, T024 en paralelo tras sus funciones.
- Phase 4: T034 y T037–T041 en paralelo tras T036 (T039 tras T034).
- Phase 8 y Phase 9 pueden avanzar en paralelo tras T052.

## Implementation Strategy

1. **MVP navegable** = Phase 1 (Checkpoint A): URLs reales, nada se rompe, funciona con
   base vacía.
2. **Backend completo** = Phases 2–3 (Checkpoint B).
3. **Base visual** = Phases 4–5 (Checkpoint C).
4. **Valor diario** = Phases 6–7 (Checkpoint D).
5. **Onboarding completo** = Phases 8–9 (Checkpoint E).
6. **Cierre** = Phase 10 + Final: terminología, revisión manual y checks estáticos una vez.

En cada checkpoint no se repiten tests ya verdes cuyo código no haya cambiado. Sin commits,
push ni PR en los checkpoints salvo instrucción explícita del usuario.
