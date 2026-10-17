# Research: UX Foundation & Responsive App (Feature 018)

Investigación realizada sobre el código de `main` (`53d2e34`) el 2026-10-16. Cada sección
sigue el formato Decision / Rationale / Alternatives considered.

---

## §1. Router

**Hallazgos**

- Frontend: React 19.2 + TypeScript 6 + Vite 8 + Vitest 5 (jsdom 30). No hay router: `App.tsx`
  guarda `selectedId` en `useState`, `ProjectDetail` guarda `view` ("accounts" | "content" |
  "queue") en `useState`, `ContentLibrary` y `PublicationQueue` guardan su `selectedId` en
  `useState`.
- La app solo se sirve con `vite` (dev) y `vite preview`; ambos hacen *history fallback* a
  `index.html` por defecto. El backend FastAPI no sirve el frontend (no hay `StaticFiles`) y
  el proxy de Vite solo reenvía `/api`. Por tanto, URLs como `/p/3/posts/12` resuelven a la
  SPA sin configuración adicional.
- Los callbacks OAuth son páginas HTML del backend (`/api/*/oauth/callback`) que dicen
  "Return to AutoPublisher"; el frontend sigue el intento haciendo *polling* por
  `attempt_id`. Instagram/Threads usan "pegar la URL de redirección". Nada depende de la URL
  del frontend.
- `react-router` 8.4.0 (2026-09-15; peer `react >=19.2.7`, `node >=22.22`; CI usa Node 24 y
  `react ^19.2.8`): exporta `createBrowserRouter`, `createMemoryRouter`, `RouterProvider`,
  `NavLink`, `useParams`, `useSearchParams`, `Navigate`.
- `@tanstack/react-router` 1.170: tipado de rutas excelente, pero su modo recomendado es
  file-based + plugin de Vite; añade más superficie que la que 018 necesita.

**Decision**: `react-router` **8.4.0** (versión exacta, ≥ 2 semanas de antigüedad) en
**modo data sin loaders**: un único array `routes` exportado desde `src/routes.tsx`;
`main.tsx` usa `createBrowserRouter(routes)` + `<RouterProvider>`; los tests usan
`createMemoryRouter(routes, { initialEntries })` con exactamente el mismo árbol. Sin
loaders/actions: los componentes existentes siguen cargando sus datos como hoy (cambiar eso
sería rediseñar 019).

**Rationale**: router mantenido, estándar en React, compatible con React 19.2 y Vite sin
plugin; el modo data aporta `errorElement` (pantallas "not found"/error) y un seam de test
limpio (`createMemoryRouter`) con el mismo árbol de producción. `BrowserRouter` + history
API cumple reload, back/forward y deep links; el fallback ya lo hace Vite. Un despliegue
futuro solo tendrá que servir `index.html` como fallback de rutas no-`/api` (documentado,
sin diseñarlo ahora).

**Alternatives considered**

- *Declarative mode (`<BrowserRouter><Routes>`)*: válido, pero sin `errorElement` y con un
  árbol JSX que los tests tendrían que reconstruir.
- *TanStack Router*: más potente en tipado; rechazado por coste de adopción (plugin,
  file-based routing) sin beneficio para 018.
- *Hash router*: evita fallback pero produce URLs `/#/p/1`, peores para deep links;
  innecesario porque Vite ya hace fallback.
- *Router propio sobre `history`*: reinventar; rechazado.

---

## §2. Árbol de rutas y reglas de navegación

**Decision** (contrato completo en [contracts/ui.md](contracts/ui.md#1-route-tree)):

```text
/                                   AppShell (layout, errorElement=RouteError)
├── (index)                         HomePage            ?project=<id> filtra Needs attention
├── settings                        SettingsPage
├── p/:projectId                    ProjectLayout       carga proyecto, 404, strip, checklist
│   ├── (index)                     <Navigate to="library" replace>   landing = Library
│   ├── library                     LibraryPage
│   ├── library/:mediaId            LibraryPage (medio seleccionado)
│   ├── posts                       PostsPage (List)
│   ├── posts/:postId               PostsPage (post seleccionado)
│   ├── accounts                    AccountsPage
│   ├── accounts/new                AccountsPage + AddAccountSheet
│   ├── accounts/:accountId         AccountsPage + AccountDetail (DetailSurface)
│   └── *                           NotFound (en contexto de proyecto)
└── *                               NotFound
```

- Toda navegación es `<Link>`/`<NavLink>`/`navigate()`; no existe estado de navegación fuera
  del router (se eliminan `view`, `selectedId` de `App`, `ProjectDetail`, `ContentLibrary` y
  `PublicationQueue`).
- `:projectId`, `:mediaId`, `:postId`, `:accountId` se validan como enteros positivos; un
  valor no numérico es "not found" sin llamar a la API.
- La pertenencia al proyecto se verifica en el cliente con datos que la página ya carga
  (lista de cuentas / contenidos / publicaciones del proyecto): un id que no está en la lista
  del proyecto es "not found". No hace falta un endpoint nuevo de verificación.
- `accounts/new` es una ruta (no un estado local) para que "atrás" cierre el flujo y el
  usuario pueda recargar sin quedar en un estado inconsistente.
- Posts queda preparado para List/Calendar con la ruta `posts` = vista List; Calendar no se
  crea (ni ruta ni botón). 019 añadirá `posts/calendar` u otra forma sin romper `posts` y
  `posts/:postId`.

**Rationale**: árbol plano y explícito; layouts anidados para shell y proyecto; un único
lugar de verdad (la URL).

**Alternatives considered**: abrir detalles como query (`?media=3`) — rechazado porque la
spec fija segmentos de ruta; modal sin ruta para Add account — rechazado (no sobrevive a
reload, rompe "atrás").

---

## §3. Migración del frontend actual

**Hallazgos**: `App` (lista + detalle de proyecto), `ProjectDetail` (cabecera de proyecto,
editar/activar, conmutador Accounts/Asset Library/Queue, lista y alta de cuentas),
`ContentLibrary` (lista + `ContentDetail` inline + import), `PublicationQueue` (secciones +
`PublicationDetail` inline + `AutomationStatus` + texto). `ContentDetail` y `Distribute`
reciben `onOpenQueue`.

**Decision**: desmontaje progresivo en 4 pasos, sin reescribir workflows de 019:

1. **Router + shell vacío**: `main.tsx` → `RouterProvider`; `AppShell` con navegación;
   `App.tsx` desaparece (su lógica de crear proyecto pasa a Home/`CreateProjectDialog`).
2. **ProjectLayout**: carga el proyecto por `:projectId` (`GET /api/projects/{id}`), muestra
   cabecera compacta (nombre, estado activo/inactivo, menú "Edit project / Deactivate" que
   reutiliza `ProjectForm` en un `Dialog`), `ProjectStatusStrip` y `OnboardingChecklist`, y
   proporciona el `Project` a las páginas hijas vía `useOutletContext`. `ProjectDetail.tsx`
   se elimina.
3. **Montaje temporal de Library y Posts**:
   - `LibraryPage` = encabezado "Library" + `<ContentLibrary project selectedId onSelect
     onOpenPosts>`. `ContentLibrary` pasa de `useState(selectedId)` a props controladas
     (`selectedId` desde `:mediaId`, `onSelect` → `navigate`). El `ContentDetail` sigue
     renderizándose inline como hoy (su migración a `DetailSurface` es 019).
   - `PostsPage` = encabezado "Posts" + indicador de automatización en pausa (enlace a
     Settings) + `<PublicationQueue project selectedId onSelect>`. Se retira
     `<AutomationStatus>` de la cola y su `<h3>Queue</h3>`. `PublicationDetail` sigue inline.
   - `onOpenQueue` se renombra a `onOpenPosts` y navega a `/p/:id/posts` (o a
     `/p/:id/posts/:postId` cuando hay un post concreto).
4. **Accounts nuevo**: `AccountsPage` sustituye a la sección de cuentas de `ProjectDetail`
   (ver §8). `AccountList.tsx` y `AccountForm.tsx` se eliminan (el alta deja de pedir handle;
   la edición de nombre visible pasa al detalle de cuenta).

Cambios en workflows 019: solo props de selección controlada, renombre `onOpenQueue`, retirada
de `AutomationStatus` de la cola, `accountLabel()` para handles nulos (§5) y el texto del botón
"Distribute" → "Publish…". Nada más.

**Rationale**: la URL pasa a ser la fuente de verdad sin tocar el contenido de las
pantallas; los tests existentes de esas pantallas siguen válidos con ajustes mínimos de props.

**Alternatives considered**: envolver los componentes con un adaptador que sincronice estado
interno ↔ URL — rechazado (dos fuentes de verdad, justo lo que se quiere evitar).

---

## §4. Creación de cuentas hoy

**Hallazgos**

- `Account`: `handle VARCHAR(100) NOT NULL`, `handle_key NOT NULL`,
  `UNIQUE(project_id, platform, handle_key)`. `POST /projects/{id}/accounts` exige
  `platform` + `handle` (escrito a mano). No existe borrado de cuentas.
- Las 5 integraciones son **account-scoped**: `POST /accounts/{id}/<platform>-connection/
  authorize` (YouTube, Instagram, Threads, TikTok), `.../login/start|code|password`
  (Telegram), `verify`, `disconnect`. Los registros de intentos OAuth están en memoria y
  guardan `account_id`.
- La identidad real se conoce **solo al completar la conexión**: callback OAuth
  (YouTube `channel_id/title/handle`; TikTok `open_id/display_name`), pegado de URL
  (Instagram `username`, Threads `username`) o tras el código/contraseña de Telegram
  (`get_me()`: `telegram_user_id`, `display_name`, `username`). Telegram además necesita
  después elegir canal de destino.
- `account.handle` **nunca** se actualiza desde la conexión y nada lo compara con la
  identidad; se usa como etiqueta (`account_label()`, mensajes de conflicto, `PublicationRead
  .account.handle`, 14 usos en el frontend).
- Cada conexión ya garantiza unicidad de identidad por proyecto (`UNIQUE(project_id,
  channel_id|instagram_user_id|threads_user_id|open_id)`); Telegram por `account_id`.

## §5. Add account → choose platform → Connect

**Decision**: **identidad diferida** con el mínimo cambio de esquema.

1. **Migración `0017_account_handle_optional`**: `accounts.handle` y `accounts.handle_key`
   pasan a `NULL`able (Alembic `batch_alter_table`, como migraciones previas en SQLite). La
   restricción `UNIQUE(project_id, platform, handle_key)` se mantiene: SQLite trata los
   `NULL` como distintos, así que varias cuentas provisionales no colisionan y las cuentas con
   handle conservan su unicidad. Sin datos nuevos ni backfill: las cuentas existentes ya
   tienen handle.
2. **`AccountCreate.handle` opcional** (`Handle | None = None`). El cliente nuevo crea la
   cuenta solo con `platform` (y opcionalmente `display_name`); el API sigue aceptando
   `handle` (retrocompatible).
3. **Adopción de identidad**: un único helper `adopt_connected_identity(session, account,
   candidate)` en `accounts.py`, llamado desde la función de completado de cada integración
   (5 puntos, misma transacción que crea la conexión). Si `account.handle is None`, asigna
   `handle = clean_handle(candidate)` y `handle_key`, salvo que colisione con otra cuenta del
   mismo proyecto y plataforma (entonces lo deja `NULL`; la identidad sigue visible vía
   health). Nunca sobrescribe un handle existente. Candidatos: YouTube `channel_handle` sin
   `@` o `channel_title`; Instagram/Threads `username`; TikTok `display_name` (no expone
   username); Telegram `username` o `display_name`.
4. **Etiquetas**: `account_label()` (backend) y `accountLabel()` (frontend) devuelven
   `"<Platform> @handle"` o, si `handle` es `NULL`, `"<Platform> account"` (+ `display_name`
   si existe). Todos los usos directos de `account.handle` pasan por esos helpers.
   `AccountRead.handle` y `PublicationAccountSummary.handle` pasan a `str | None`.
5. **Descartar cuentas provisionales** (aprobado): `DELETE /api/accounts/{id}` solo para
   cuentas **provisionales**: `handle IS NULL` (nunca se adoptó identidad), sin fila de
   conexión en ninguna plataforma (ni `connected` ni `reconnect_required`) y sin
   publicaciones (las filas de presets se borran por `CASCADE`). Una cuenta legacy o con
   identidad adoptada nunca es descartable, aunque se haya desconectado: no es un borrado
   general. Errores: `409 account_not_discardable`, `409 account_busy` (lock de Telegram en
   uso). **Intentos transitorios** (solo en memoria; antes de completar no hay nada en
   SQLite ni en el keyring): `expire_for_account()` en los 4 registros OAuth (una
   redirección posterior responde "Authorization not valid") y `discard()` en el registro de
   logins de Telegram (descarta la sesión temporal no autorizada); después, transacción que
   re-comprueba y borra. Carrera con un callback ya en curso: si el callback crea la conexión
   primero → `409`; si el borrado va primero → el callback falla por su camino existente (a
   verificar en implementación que no deja secretos huérfanos, test representativo con
   YouTube). El frontend solo lo usa como "Discard" de Add account y en cuentas con
   `can_discard`.
6. **Flujo UI**: `Add account` (ruta `accounts/new`) → elegir plataforma (tarjetas; X =
   "Coming soon" deshabilitada; sin configuración = explicación + "Open Settings") →
   `Connect` → se crea la cuenta provisional y se muestra **el panel de conexión existente**
   de esa plataforma en modo conexión, dentro del mismo sheet → al completar, se navega a
   `accounts/:accountId`. Cancelar antes de conectar → `DELETE` (Discard).

**Rationale**: reutiliza íntegros los 5 flujos de conexión (OAuth, pegado de URL, Telegram
multi-paso, confirmaciones de reemplazo) sin duplicarlos; el único placeholder es `NULL`,
que significa literalmente "identidad aún desconocida" (no un valor inventado); la ventana en
la que existe es la del flujo de conexión. La cuenta legacy sin conexión sigue siendo válida.

**Alternatives considered**

- *Conexión project-scoped (crear la `Account` en el callback)*: exigiría duplicar
  `authorize`/callback/confirm/cancel en 5 integraciones, cambiar registros de intentos y el
  flujo Telegram con estado en memoria por cuenta, y nuevas variantes de los paneles.
  Rechazado por riesgo y tamaño.
- *Handle provisional inventado (p. ej. `pending-<uuid>`)*: persistiría un valor falso visible
  en mensajes, presets y publicaciones; rechazado (la petición prohíbe placeholders
  injustificados).
- *Pedir el handle después de conectar*: el usuario sigue escribiendo algo que el sistema ya
  sabe; rechazado.

---

## §6. Read-model: forma y eficiencia

**Decision**: tres endpoints pequeños, solo lectura, en un módulo nuevo
`backend/app/overview.py` (lógica de derivación) + routers:

| Endpoint | Uso |
|---|---|
| `GET /api/overview[?project_id=]` | Home (global), strip y checklist (`project_id`) |
| `GET /api/projects/{id}/account-health` | Accounts, detalle de cuenta, Add account |
| `GET /api/platforms` | Settings, selector de plataforma de Add account |

`overview` devuelve `automation`, `attention[]`, `upcoming[]` (≤ 5) y `projects[]` (cada uno
con `accounts_ready`, `accounts_active`, `attention_count`, `next_post`, `onboarding`). Con
`project_id` todo se restringe a ese proyecto. La Home sin query llama a la versión global y
con `?project=<id>` **filtra en cliente** `attention` por `project_id` (Up next y Projects
siguen globales, como pide la spec); el strip usa la versión acotada.

Consultas (independientes del número de proyectos/cuentas, sin N+1):

1. proyectos (1);
2. cuentas + 5 tablas de conexión (6, o 1 + 5 `IN`);
3. publicaciones candidatas: `status IN (failed, awaiting_user_action)` **o**
   (`status = scheduled` y `scheduled_at <= now + 7d`) (1), con contenido/cuenta ya cargados
   por identidad;
4. últimos intentos de las fallidas con `latest_attempts()` existente (2);
5. próximos: `scheduled AND scheduled_at > now ORDER BY scheduled_at LIMIT 5` (1) y el
   siguiente por proyecto (`GROUP BY project_id, MIN(scheduled_at)`) (1);
6. onboarding: `EXISTS` contenidos y publicaciones por proyecto (`GROUP BY`) (2);
7. `is_paused()` y estado del scheduler (como `GET /automation`).

La única parte por elemento es `local_check()` sobre los posts programados en las próximas
7 días (§7, regla 6), acotada por volumen de un usuario (decenas). Se documenta el coste y se
reutiliza tal cual.

**Rationale**: una llamada por pantalla; contratos estables para 019 (Posts Active/History y
Calendar podrán reutilizar `display_state` y `upcoming`).

**Alternatives considered**: un endpoint por sección de Home (4 llamadas, más estados de
carga); health embebido en `overview` (pesado para Home, que solo necesita contadores);
health embebido en `GET /accounts` (cambiaría un contrato muy usado por 019).

---

## §7. Derivación de Attention

Definiciones compartidas (`now` = reloj inyectable, `W` = `AUTO_PUBLISH_WINDOW` existente,
`H` = 7 días):

- **armed** = `auto_publish_enabled` (solo posible en `scheduled`).
- **display_state** (función única `post_display_state`, usada por `publication_to_read` y por
  el overview; nuevo campo aditivo `PublicationRead.display_state`):

| Condición (en orden) | display_state | Qué significa para el usuario |
|---|---|---|
| `publishing` | `publishing` | Se está publicando ahora |
| `published` | `published` | Publicado |
| `cancelled` | `cancelled` | Cancelado; no ocurrirá |
| `awaiting_user_action` | `needs_action` | Termina el post en la plataforma |
| `failed` y último intento `needs_manual_review` | `needs_review` | Resultado incierto: revisa en la plataforma antes de reintentar |
| `failed` | `failed` | Falló; no se reintentará solo |
| `unscheduled` | `draft` | Borrador; no se publicará hasta programarlo o publicarlo |
| `scheduled`, armed, `is_overdue` | `missed` | Su ventana automática pasó sin publicarse |
| `scheduled`, no armed, `scheduled_at <= now` | `missed` | Era manual y la hora pasó |
| `scheduled`, armed, automatización en pausa | `scheduled_paused` ("Scheduled · paused") | Programado para publicación automática, pero la automatización global está en pausa: no se ejecutará mientras siga así |
| `scheduled`, armed | `scheduled_automatic` | Se publicará solo a su hora |
| `scheduled`, no armed | `scheduled_manual` | A su hora tendrás que publicarlo tú |

`Scheduled · automatic` significa exactamente: estado `scheduled`, consentimiento de
auto-publicación armado, automatización global **no** pausada y ventana no vencida. No
garantiza que los requisitos estén completos: si no lo están, el post además aparece en
Needs attention como `incomplete` (regla 6).

**Reglas** (prioridad 1 = más grave; un post genera como máximo un item: el de menor número):

| # | kind | Fuente | Acción primaria → destino |
|---|---|---|---|
| 1 | `manual_review` | `failed` + último intento `needs_manual_review` | **Review** → post |
| 2 | `failed` | `failed` (resto) | **Retry** → post |
| 3 | `missed` | `display_state == missed`, o armed + pausa + `scheduled_at <= now` (no se ejecutará) | **Publish now** → post (allí también Reschedule); si la causa es la pausa: **Resume automation** → `/settings` |
| 4 | `needs_action` | `awaiting_user_action` | **Check status** → post |
| 5 | `reconnect` | cuenta activa con health `reconnect_needed` | **Reconnect** → `accounts/:id` |
| 6 | `incomplete` | `scheduled`, `now < scheduled_at <= now + H`, no `missed`, y `local_check()` con problemas **o** `auto_publish_error` vigente | **Complete** → post |
| 7 | `expiring` | cuenta activa `ready` con expiración en `(now, now + H]` | **Reconnect** → `accounts/:id` |

Casos aclarados:

- **Manual programado cuya hora pasó** → `missed` (regla 3) desde `scheduled_at`; nunca se
  publicará solo.
- **Automático programado futuro** → no es atención (aparece en Up next como
  `scheduled_automatic`), salvo requisitos incompletos (regla 6).
- **Automático dentro de su ventana y no pausado** → el scheduler lo arrancará: no es atención.
- **Automatización en pausa**: los automáticos futuros no generan items individuales; Home y
  Posts muestran un **banner único** "Automation is paused — N automatic posts won't publish"
  con "Resume" → `/settings`. Los automáticos cuya hora llega durante la pausa pasan a regla 3
  con acción "Resume automation".
- **Cuenta inactiva**: no genera `reconnect`/`expiring`. Sus posts `failed`/`needs_review`/
  `needs_action` siguen apareciendo; sus programados próximos aparecen como `incomplete`
  porque `local_check` ya informa `account_inactive`.
- **Proyecto inactivo** (aprobado): solo reglas 1, 2 y 4 (problemas ya existentes que
  todavía hay que conocer o resolver); nunca 3, 5, 6 ni 7 (reconexión, caducidad, requisitos
  de próximos posts, planificación futura). Up next y `next_post` excluyen proyectos
  inactivos.
- **Requisitos incompletos / no verificables**: `local_check()` existente sin
  `reconcile_uncertain()`. Puede leer recursos locales (TikTok lee el keyring en su `check`)
  pero **nunca** usa la red ni modifica estado. Si no puede completarse (keyring o
  configuración local no disponible: `CredentialStoreUnavailable`, `AppError` de
  configuración u otra excepción), el post **no** se considera listo ni se oculta: se emite
  como `incomplete` con `detail` "Couldn't verify requirements" y acción **Complete** → post.
  No hay categoría adicional.
- **Plegado por cuenta**: si un post `incomplete` solo tiene problemas de conexión
  (`*_not_connected`, `*_reconnect_required`) y su cuenta ya tiene item `reconnect`, el post
  no genera item propio; el item de la cuenta incluye `affected_posts` (conteo). Evita
  duplicar el mismo problema.
- **Orden dentro de la misma prioridad**: 1–2 por `updated_at` desc (lo más reciente primero);
  3 y 6 por `scheduled_at` asc; 4 por `updated_at` asc (lo que más espera); 5 por nombre de
  proyecto/cuenta; 7 por `expires_at` asc.

**Rationale**: reutiliza `is_overdue`, `auto_publish_state`, `needs_manual_review`,
`latest_attempts`, `local_check`; una sola función de estado visible para backend y API.

**Alternatives considered**: calcular `display_state` en el frontend a partir de
`auto_publish_state` — rechazado (segunda copia de reglas; el backend ya tiene `now`/`paused`
en el mapper único).

---

## §8. Account health por plataforma (sin red, sin escrituras)

**Decision**: `account_health(account, connection, now)` puro sobre filas SQLite; nunca lee
el keyring ni llama a `connection_to_read` (TikTok la usa para *reparar* y puede escribir).

| Plataforma | Identity | Reconnect needed | expires_at (aviso) | Extra |
|---|---|---|---|---|
| YouTube | `channel_title` (+ `channel_handle`) | `status = reconnect_required` | — (refresh token sin caducidad local) | — |
| Instagram | `@username` | `status = reconnect_required` o `credential_expires_at <= now` | `credential_expires_at` | — |
| Threads | `@username` (+ `display_name`) | igual que Instagram | `credential_expires_at` | — |
| TikTok | `display_name` | `status = reconnect_required` o `refresh_expires_at <= now` | `refresh_expires_at` (el access token se renueva solo) | — |
| Telegram | `display_name` (+ `@username`) | `status = reconnect_required` | — | sin canal → `setup_required`; `flood_wait_until > now` → issue informativo |

Estado de producto (en orden): `inactive` (cuenta desactivada) → `not_connected` (sin fila)
→ `reconnect_needed` → `setup_required` (solo Telegram sin canal) → `ready`.
`expiring` es un flag sobre `ready` cuando `expires_at <= now + 7d`.

Capacidades en lenguaje de producto, derivadas de una tabla estática junto a los publishers
(`text` solo si `publisher.accepts_text_only`): YouTube *Videos*; Instagram *Images, Videos*;
Threads *Text, Images, Videos*; TikTok *Videos*; Telegram *Text, Images, Videos*. El detalle
TikTok Direct Post / Inbox (scopes en keyring) sigue en el panel técnico existente.

Issue: texto corto por estado (p. ej. "Instagram no longer accepts the saved login.
Reconnect to keep publishing.", "Choose the channel where posts will be published.").

**Rationale**: `setup_required` ("Finish setup", aprobado y reflejado en FR-027/FR-032)
representa una conexión válida pero incompleta para publicar; una cuenta Telegram sin canal
no es "Ready" ni "Not connected", y tampoco "Reconnect needed" (su conexión es válida).

---

## §9. Platform configuration availability

**Hallazgos** (`config.py`, loaders existentes que ya validan contenido sin exponerlo):

| Plataforma | Necesita para conectar | Necesita además para publicar | Loader |
|---|---|---|---|
| YouTube | Google OAuth client JSON | — | `youtube_connections.oauth_configured()` |
| Instagram | Meta App JSON | media delivery (todas las publicaciones) | `instagram_connections.oauth_configured()`, `MediaDelivery.configured()` |
| Threads | Threads App JSON | media delivery (solo imágenes/vídeos) | `threads_connections.oauth_configured()` |
| TikTok | TikTok App JSON (`client_key`, `client_secret`, `redirect_uri`) | — | `tiktok_connections.oauth_configured()` |
| Telegram | Telegram App JSON (`api_id`, `api_hash`) | — | `telegram_connections.configured()` |
| X | — (sin integración) | — | — |

**Decision**: `GET /api/platforms` → por plataforma: `integration_available`, `can_connect`,
`status` (`configured` | `partial` | `not_configured` | `coming_soon`), `missing[]` con
códigos (`app_credentials`, `media_delivery`) y `message` saneado escrito por nosotros
("The YouTube app credentials are missing or invalid."). Reutiliza los `*_configured()`
existentes. **Nunca** devuelve rutas, nombres de variables de entorno, contenidos, ids de
cliente, tokens ni mensajes de excepción. Un test escribe ficheros de configuración con
valores centinela y comprueba que ni los valores ni las rutas aparecen en la respuesta.

**Rationale**: los loaders ya existen y se leen en cada llamada; solo se agregan.

---

## §10. Storage del último proyecto

**Hallazgos**: `storage-safety.test.tsx` prohíbe toda referencia a `localStorage`,
`sessionStorage`, `indexedDB` o cookies en el código de la app y espía `setItem` en varios
flujos.

**Decision**: un único módulo `src/ui-preferences.ts` con una única clave
`autopublisher.lastProjectId` (solo un entero). Lectura/escritura envueltas en `try/catch`;
si el almacenamiento no existe o falla, devuelve `null` y la app usa el primer proyecto.
Se escribe al entrar en `ProjectLayout` con un proyecto válido; se borra si apunta a un
proyecto inexistente. El test de storage pasa a: (a) solo `ui-preferences.ts` puede
referenciar `localStorage`; (b) en todos los flujos espiados, `setItem` solo recibe esa
clave; (c) ningún otro mecanismo (session, IndexedDB, cookies).

**Alternatives considered**: guardar el último proyecto en el backend (persistencia nueva
para una preferencia de UI) — rechazado; no recordarlo — peor UX en móvil (bottom nav sin
proyecto).

---

## §11. Design system y UI UX Pro Max

**Verificación**: repositorio oficial `github.com/nextlevelbuilder/ui-ux-pro-max-skill`
(MIT, ~136k estrellas, release `v2.15.0` 2026-08-13). La skill está en
`.claude/skills/ui-ux-pro-max/` del repo (SKILL.md + `data/*.csv` + `scripts/*.py`,
3,6 MB). Auditados `search.py`, `core.py`, `design_system.py`: solo stdlib, sin red ni
subprocess. Se consultó desde una copia temporal fuera del repo.

**Decision de instalación**: al iniciar la tarea de design system se instala como **skill
de proyecto local** en `.claude/skills/ui-ux-pro-max/` a partir del tag `v2.15.0` del repo
oficial, y se **excluye de Git** con una línea en `.gitignore`
(`.claude/skills/ui-ux-pro-max/`). No se vendoriza ni se publica código de terceros en el
repositorio; solo se versionan nuestras decisiones (en `docs/design-system.md`). El CLI
global `uipro` / marketplace no se usa: instalar desde el tag fija la versión y evita
instalar paquetes npm globales.

**Consultas realizadas** y resultado:

| Consulta | Recomendación | Decisión |
|---|---|---|
| `--design-system "social media scheduling productivity dashboard"` | Patrón "Feature-Rich Showcase" (landing), estilo "Vibrant & Block-based", rosa `#E11D48`, Inter + Playfair Display | **Rechazada**: orientada a landing/marketing; contradice claridad y jerarquía |
| `product "productivity tool"` | Flat Design + Minimalism & Swiss Style; "clear hierarchy + functional colors" | **Adoptada** como dirección: plano, funcional, jerarquía tipográfica |
| `color "productivity saas"` | Teal `#0D9488` primario, naranja de acción | **Rechazada parcialmente**: blanco sobre `#0D9488` no alcanza 4.5:1; se adopta la idea de "un solo primario + colores funcionales" con azul AA propio |
| `typography "dashboard"` | Fira Sans/Code o Plus Jakarta Sans (Google Fonts) | **Rechazada**: app local, sin fuentes remotas; se usa *system font stack* |
| `style "minimalism"` | Sin sombras salvo necesarias, radios mínimos, un acento | **Adoptada con ajuste**: sombras solo en superficies flotantes (drawer/sheet/menú); radios pequeños |
| ux: Back button / Deep linking | Preservar historial; URL refleja estado | **Adoptada** (router, §2) |
| ux: Touch target | Web WCAG 2.2 AA = 24 px; 44 pt iOS | **Adoptada la spec (44 px)**, más estricta |
| ux: Focus states / Focus appearance | Anillo visible ≥ 2 px, contraste 3:1 | **Adoptada** |
| ux: Color only / live badges | Texto + icono además de color; `role=status` atómico | **Adoptada** (StatusBadge) |
| ux: Empty states | Mensaje + una acción | **Adoptada** (exactamente una primaria) |
| ux: Form labels / submit feedback | Label visible, error junto al campo, feedback de envío | **Adoptada** (ya es el patrón actual) |
| ux: Reduced motion / excessive motion | `prefers-reduced-motion`; 1–2 animaciones por vista | **Adoptada** |
| ux: Sticky nav no tapa contenido | Compensar altura de barras fijas | **Adoptada** (bottom nav + safe-area) |
| Checklist "cursor-pointer", "hover 150–300 ms" | — | **Adoptada** (estados de interacción) |
| Breakpoints 375/768/1024/1440 | — | **Adoptada** (§12) |
| Emojis como iconos | Prohibido; SVG | **Adoptada**: iconos SVG inline propios (sin librería de iconos) |

**Headless primitives**: jsdom 30 **no** implementa `HTMLDialogElement.showModal()`, así que
un `<dialog>` nativo obligaría a stubs en tests y no da *focus trap* completo en todos los
navegadores. **Decision**: `@radix-ui/react-dialog` **1.1.23** (2026-07-24; versión exacta
≥ 2 semanas) como única dependencia headless, para `Dialog`, `Drawer` y `Sheet` (misma
primitiva, distinto CSS). El menú secundario de Settings en móvil y las "acciones" de
cabecera se resuelven como **disclosure** (`button[aria-expanded]` + lista de enlaces), no
como menú ARIA, sin librería. "Technical details" usa `<details>/<summary>` nativo. No se
añade kit visual ni librería de iconos.

**Alternatives considered**: Base UI 1.8 (paquete único, más superficie de la necesaria);
React Aria Components (excelente a11y pero mucho más grande); Headless UI (último release
abril 2026, menos activo).

---

## §12. Arquitectura responsive

**Decision**: un único `AppShell`, un único árbol de rutas; **CSS decide el layout**,
React solo donde hay comportamiento distinto.

- Breakpoints (tokens): `sm < 768px` (móvil), `md 768–1023px` (tablet), `lg ≥ 1024px`
  (escritorio). Mobile-first.
- `PrimaryNav` (un solo `<nav aria-label="Main">`): Home, Library, Posts, Accounts,
  Settings. CSS: `lg` sidebar con etiquetas y `ProjectSelector`; `md` rail de iconos con
  etiqueta corta; `sm` barra inferior fija con 4 destinos (Settings oculto por CSS).
- `TopBar` (solo `sm`, por CSS): `ProjectSelector` + botón "More" (disclosure) con Settings.
- `ProjectSelector`: un componente; se renderiza en el slot de sidebar (`lg`) o de topbar
  (`sm`/`md`). Para no duplicar nodos accesibles se elige el slot con `useMediaQuery`
  (`matchMedia`), único hook responsive.
- `DetailSurface` (patrón de detalle): `lg` panel lateral no modal junto a la lista;
  `md` drawer modal superpuesto (Radix Dialog); `sm` pantalla completa con "Back" (página,
  no modal). Elige el modo con `useMediaQuery`. Cerrar = `navigate` a la ruta padre; "Back"
  en móvil = la misma navegación (no `history.back()`, para que un deep link directo también
  funcione).
- Contenido: `max-width` fluido, `min-width: 0` en grids, sin anchos fijos; tablas existentes
  envueltas en contenedores con scroll **propio** (nunca del documento).

Comportamiento JS a testear: elección de modo de `DetailSurface` y del slot del selector
(mockeando `matchMedia`), disclosure de "More". El resto es CSS y se valida manualmente.

---

## §13. Onboarding derivado

**Decision**: `overview.projects[].onboarding = { account_ready, media_imported,
post_created }` (booleans derivados: ≥ 1 cuenta activa `ready`; ≥ 1 contenido; ≥ 1
publicación en cualquier estado). `complete = all`. Sin tabla. La checklist se muestra en
`ProjectLayout` solo si `!complete`; el paso siguiente tiene la única acción primaria
(Connect an account → `accounts/new`; Import your first media → `library`; Publish… → el
primer medio sin uso `library/:mediaId`, obtenido de `listContents` + `usage` que la
Library ya trae).

---

## §14. Settings

**Decision**: `SettingsPage` = `AutomationStatus` existente (sin cambios de lógica;
`onChanged` opcional ya existe) + `PlatformConfigurationList` (de `GET /api/platforms`).
Solo lectura de configuración; texto que explica qué falta sin rutas ni secretos (las rutas
y formatos siguen documentados en README/docs, no en la UI).

---

## §15. Estrategia de tests

**Backend** (pytest, fakes existentes de gateways que fallan si se llaman):

1. `test_overview_attention.py`: un test **parametrizado** por regla (7 casos + pausa +
   proyecto inactivo + cuenta inactiva) que construye el mínimo de datos y comprueba
   `kind`, acción y destino; un test de **dedup/prioridad** (post con varias condiciones,
   plegado por cuenta); un test de **filtro por proyecto**; un test de **no red / no
   escritura** (gateways que lanzan + comparación de `updated_at`/filas antes y después).
2. `test_post_display_state.py`: parametrizado sobre la tabla de §7 (función pura).
3. `test_account_health.py`: parametrizado con un caso representativo por estado y por
   regla de expiración (no matriz plataforma × estado completa).
4. `test_platforms_api.py`: configurado/no configurado/parcial + **sin secretos ni rutas**.
5. `test_accounts.py` (ampliado): crear sin handle; adopción de identidad en una
   integración OAuth representativa (YouTube) y Telegram; colisión deja `NULL`; handle existente no se sobrescribe; `DELETE` permitido solo para
   provisional, `409` con identidad/conexión/posts, intentos OAuth expirados y login Telegram
   descartado tras el Discard, callback posterior sin crear conexión ni dejar secretos.
6. `test_migrations.py` (ampliado): `0017` sube y baja.

**Frontend** (Vitest + Testing Library, FakeApi existente ampliada; agrupado por journey):

1. `routes.test.tsx`: deep link a cada ruta, landing → library, back/forward, not found
   (id inexistente, de otro proyecto, no numérico), último proyecto (con y sin storage).
2. `shell.test.tsx`: destinos de navegación y estado activo; disclosure "More" → Settings;
   slot del selector según `matchMedia`.
3. `home.test.tsx`: attention con una acción por item y su enlace; filtro `?project=`;
   Everything OK; error → Retry (nunca OK); banner de pausa.
4. `accounts.test.tsx`: tarjetas por estado; detalles técnicos plegados; Add account
   (Coming soon no seleccionable, sin configuración → Settings, conectar crea cuenta
   provisional sin handle, cancelar → Discard; Telegram sin canal → Finish setup); detalle 404 de otro proyecto.
5. `settings.test.tsx`: pausa/reanuda reutilizando `AutomationStatus`; estado de plataformas.
6. `onboarding.test.tsx`: cada empty state tiene exactamente un CTA primario; checklist
   aparece/desaparece.
7. `detail-surface.test.tsx`: modo drawer: foco atrapado, Escape cierra, foco vuelve; modo
   página: botón Back.
8. Ajustes: `storage-safety.test.tsx` (§10), tests de `ContentLibrary`/`PublicationQueue`
   (props controladas, sin `AutomationStatus`), eliminación de `App.test.tsx` y
   `ProjectDetail.test.tsx` (su cobertura útil pasa a 1, 4 y 6).

Sin snapshots, sin asserts de CSS. La validación visual/responsive es manual
(quickstart.md).
