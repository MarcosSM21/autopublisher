# Implementation Plan: UX Foundation & Responsive App

**Branch**: `018-ux-foundation-responsive` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/018-ux-foundation-responsive/spec.md`

## Summary

Establecer la foundation UX de AutoPublisher: routing real con URLs persistentes, un
`AppShell` responsive (sidebar / rail / bottom nav), Home orientada a atención, Accounts con
salud de cuenta y alta `Add account → choose platform → Connect`, Settings global,
onboarding por empty states, sistema de estados de post que dice qué va a ocurrir y un
design system propio con primitivas base. Library, Posts y los detalles de medio/post se
**montan** en las nuevas rutas sin rediseñarse (019).

Enfoque técnico (detalle en [research.md](research.md)):

- **Router** (§1–§2): `react-router` 8.4.0 en modo data sin loaders; árbol único en
  `src/routes.tsx` usado por `createBrowserRouter` (app) y `createMemoryRouter` (tests).
  La URL es la única fuente de verdad de navegación.
- **Migración** (§3): `App`/`ProjectDetail` desaparecen; `ProjectLayout` carga el proyecto;
  `ContentLibrary` y `PublicationQueue` pasan a selección controlada por `:mediaId`/`:postId`;
  `AutomationStatus` se mueve a Settings.
- **Add account** (§4–§5): `accounts.handle` nullable (migración `0017`), `handle` opcional
  al crear, adopción de la identidad conectada en el completado de las 5 integraciones (sin
  sobrescribir handles existentes), `DELETE /accounts/{id}` solo para cuentas provisionales
  ("Discard", FR-039a) con invalidación de intentos en memoria. Los 5 paneles de conexión
  existentes se reutilizan dentro del flujo. Estados de cuenta: Ready, Reconnect needed,
  Finish setup, Not connected, Inactive.
- **Read-models** (§6–§9): `GET /api/overview[?project_id]`,
  `GET /api/projects/{id}/account-health`, `GET /api/platforms`; consultas por lotes, sin
  persistencia, sin red, sin `reconcile`; `local_check()` reutilizado para requisitos de
  posts de los próximos 7 días (si no puede completarse → "Couldn't verify requirements" como
  requisitos incompletos). Proyectos inactivos solo generan manual review, failed y needs
  action. `PublicationRead.display_state` aditivo, calculado por una única función (incluye
  "Needs review" y "Scheduled · paused").
- **Design system** (§11–§12): tokens CSS en dos capas, primitivas propias, iconos SVG
  propios, `@radix-ui/react-dialog` 1.1.23 como única dependencia headless; CSS decide el
  layout, `useMediaQuery` solo para `DetailSurface` y el slot del `ProjectSelector`.
- **UI UX Pro Max** (§11): verificado y consultado; se instala como skill local ignorada por
  Git; decisiones adoptadas/rechazadas documentadas.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 6.0 + React 19.2 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 (sin cambios);
frontend nuevo: `react-router@8.4.0`, `@radix-ui/react-dialog@1.1.23` (versiones exactas)

**Storage**: SQLite local; un único cambio de nulabilidad (`accounts.handle`,
`accounts.handle_key`); sin tablas nuevas. Navegador: una preferencia UI
(`autopublisher.lastProjectId`)

**Testing**: pytest (backend, fakes de gateways existentes); Vitest 5 + Testing Library +
jsdom 30 con `FakeApi` (frontend)

**Target Platform**: aplicación web local (Vite dev/preview) en navegadores modernos,
escritorio, tablet y móvil (≥ 375 px)

**Project Type**: web application (backend + frontend)

**Performance Goals**: Home y Accounts cargan con una petición cada una; respuesta
inmediata a escala de un usuario (decenas de proyectos/cuentas, miles de posts); número de
consultas del overview constante salvo `local_check` de los posts de los próximos 7 días

**Constraints**: sin llamadas remotas ni escrituras en read-models; sin secretos en
respuestas; 0 scroll horizontal a 375 px; objetivos ≥ 44 px; WCAG AA; sin dark mode; sin
kit visual; sin fuentes ni recursos remotos

**Scale/Scope**: ~8 páginas/vistas nuevas o rehechas (shell, Home, ProjectLayout, Accounts,
Account detail, Add account, Settings, NotFound), ~12 primitivas, 3 endpoints nuevos +
1 `DELETE`, 1 migración

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin loaders de router, sin librería de estado, sin kit visual, una sola dependencia headless (Radix solo para Dialog/Drawer/Sheet); read-models en un módulo; workflows de 019 solo montados. `DELETE` restringido a "Discard" y `setup_required` ya incorporados a la spec (FR-039a, FR-027). | ✅ |
| II. Spec-Driven | Spec aclarada (sesión 2026-10-16); plan trazado a FR; Calendar, rediseño de Library/Posts/detalles fuera. | ✅ |
| III. Arquitectura modular | Read-models en `overview.py` consumen interfaces existentes (`local_check`, `*_configured()`, filas de conexión); no hay lógica de plataforma nueva en el núcleo salvo la tabla de identidad/expiración por plataforma, ubicada junto a cada integración (`health_of(connection)` por módulo) y agregada por el read-model. | ✅ |
| IV. Seguridad | `/api/platforms` solo devuelve booleanos y mensajes propios; test con centinelas; la preferencia local solo guarda un id de proyecto; ningún secreto en navegador; health no lee keyring. | ✅ |
| V. Calidad | Tests de contrato por journey; regla única de `display_state`; Home nunca muestra "OK" ante error; fallos de verificación de requisitos se muestran, no se silencian. | ✅ |
| VI. Git y trazabilidad | Commits pequeños por bloque; docs (`README`, `docs/design-system.md`) actualizados; la skill de terceros no se versiona. | ✅ |
| Arquitectura base | React + TS + Vite, FastAPI, SQLite, REST: sin cambios de stack; el router y Radix Dialog son librerías de frontend dentro del stack. | ✅ |

**Post-design re-check**: sin violaciones nuevas. Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/018-ux-foundation-responsive/
├── plan.md              # este fichero
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── api.md           # overview, account-health, platforms, cambios de Account
│   └── ui.md            # rutas, shell, páginas, primitivas, tokens, terminología
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, no creado aquí)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── overview.py                 # NEW: post_display_state, attention, upcoming, summaries, routers
│   ├── platform_availability.py    # NEW: GET /api/platforms (agrega *_configured())
│   ├── accounts.py                 # handle opcional, adopt_connected_identity, DELETE, account_label
│   ├── publications.py             # display_state en publication_to_read; account_label con NULL
│   ├── schemas.py                  # Overview*, AccountHealthRead, PlatformAvailabilityRead; handle: str | None
│   ├── models.py                   # Account.handle/handle_key Optional
│   ├── youtube_connections.py      # + adopt identity al completar; health_of(connection)
│   ├── instagram_connections.py    # idem
│   ├── threads_connections.py      # idem
│   ├── tiktok_connections.py       # idem
│   ├── telegram_connections.py     # idem
│   └── main.py                     # include_router(overview, platform_availability)
├── migrations/versions/0017_account_handle_optional.py   # NEW
└── tests/
    ├── test_overview_attention.py  # NEW
    ├── test_post_display_state.py  # NEW
    ├── test_account_health.py      # NEW
    ├── test_platforms_api.py       # NEW
    ├── test_accounts.py            # ampliado
    └── test_migrations.py          # ampliado

frontend/src/
├── main.tsx                        # RouterProvider
├── routes.tsx                      # NEW: árbol único
├── ui-preferences.ts               # NEW: lastProjectId (única clave de storage)
├── ui/                             # NEW: design system
│   ├── tokens.css
│   ├── Button.tsx  IconButton.tsx  Badge.tsx  StatusBadge.tsx  Card.tsx
│   ├── EmptyState.tsx  ErrorState.tsx  Skeleton.tsx
│   ├── Dialog.tsx (Dialog/Drawer/Sheet)  DetailSurface.tsx  Disclosure.tsx
│   ├── Icon.tsx  useMediaQuery.ts
│   └── detail-surface.test.tsx
├── shell/                          # NEW
│   ├── AppShell.tsx  PrimaryNav.tsx  TopBar.tsx  ProjectSelector.tsx
│   ├── RouteError.tsx  NotFound.tsx
│   └── shell.test.tsx
├── pages/                          # NEW
│   ├── HomePage.tsx (+ AttentionList, UpNext, ProjectsList)   home.test.tsx
│   ├── ProjectLayout.tsx (+ ProjectStatusStrip, OnboardingChecklist)
│   ├── LibraryPage.tsx  PostsPage.tsx
│   ├── AccountsPage.tsx  AccountCard.tsx  AccountDetail.tsx  AddAccountSheet.tsx   accounts.test.tsx
│   ├── SettingsPage.tsx (+ PlatformConfigurationList)   settings.test.tsx
│   └── CreateProjectDialog.tsx
├── routes.test.tsx  onboarding.test.tsx                    # NEW
├── api.ts  types.ts  utils.ts      # getOverview, getAccountHealth, listPlatforms, discardAccount; accountLabel
├── components/ContentLibrary.tsx   # selección controlada; "Publish…"
├── components/ContentDetail.tsx / Distribute.tsx   # onOpenQueue → onOpenPosts
├── components/PublicationQueue.tsx # selección controlada; sin AutomationStatus
├── components/*ConnectionPanel.tsx # accountLabel(); bloques técnicos internos sin cambios
├── App.tsx, components/ProjectDetail.tsx, AccountList.tsx, AccountForm.tsx, ProjectList.tsx  # REMOVED
└── storage-safety.test.tsx         # permite solo ui-preferences.ts / una clave

docs/design-system.md               # NEW: tokens, primitivas, recomendaciones UI UX Pro Max adoptadas/rechazadas
README.md                           # navegación/URLs, Settings, Add account, deep links tras despliegue
.gitignore                          # + .claude/skills/ui-ux-pro-max/
```

**Structure Decision**: web application existente (`backend/` + `frontend/`). En frontend
se introducen tres carpetas por responsabilidad (`ui/` design system, `shell/` navegación,
`pages/` pantallas enrutadas); `components/` conserva los workflows de 019 sin moverlos para
no generar diffs de ruido.

## Implementation phases (orden propuesto para /speckit-tasks)

1. **Backend read-models y Account** (independiente del frontend): migración `0017` +
   `handle` opcional + adopción + `DELETE`; `post_display_state` + `display_state`;
   `overview`; `account-health`; `platforms`. Tests backend dirigidos.
2. **Design system**: instalar UI UX Pro Max (local, ignorada), `docs/design-system.md`,
   tokens y primitivas, `detail-surface.test.tsx`.
3. **Router + shell + migración**: dependencia `react-router`, `routes.tsx`, `AppShell`,
   `ProjectLayout`, `LibraryPage`/`PostsPage` montando componentes existentes, NotFound,
   `ui-preferences.ts`, ajustes de tests existentes (`storage-safety`, Library, Queue).
   `routes.test.tsx`, `shell.test.tsx`.
4. **Home** (US1) + strip (US5): `home.test.tsx`.
5. **Accounts** (US3): cards, detalle, Add account, Discard: `accounts.test.tsx`.
6. **Settings** (US6): `settings.test.tsx`.
7. **Onboarding** (US4) y terminología/estados (US7): `onboarding.test.tsx`.
8. **Cierre**: docs, validación manual responsive/a11y (quickstart §5–§6), checks estáticos
   una vez, PR.

## Feature boundary (confirmación)

018 **no** absorbe: rediseño de Library (cards/flujo), Media detail, Publish/Distribute,
Posts (List/Active/History), Calendar, Post detail, migración de detalles de medio/post a
`DetailSurface`, terminología completa dentro de esas pantallas. Solo se tocan en ellas:
selección controlada por URL, `onOpenQueue → onOpenPosts`, títulos de página, botón
"Publish…", retirada de `AutomationStatus` de la cola y `accountLabel()` para handles nulos.

## Approved decisions (2026-10-16)

1. **Esquema de `Account`**: `handle`/`handle_key` nullable (migración `0017`), `POST`
   retrocompatible, `adopt_connected_identity` tras conexión correcta, nunca sobrescribe
   handles existentes (FR-038).
2. **`DELETE /api/accounts/{id}`** solo como "Discard" de cuentas provisionales, con
   invalidación de intentos en memoria (FR-039a, contracts/api.md §5).
3. **Estado de cuenta `setup_required`** ("Finish setup") distinto de "Reconnect needed"
   (FR-027, FR-032).
4. **Estados de post "Needs review" y "Scheduled · paused"** (FR-049).
5. **Proyectos inactivos**: solo manual review, failed y needs action (FR-017a).
6. **Requisitos no verificables** → `incomplete` con "Couldn't verify requirements" (FR-017b).
7. **Dependencias**: `react-router@8.4.0` y `@radix-ui/react-dialog@1.1.23` (Radix solo para
   primitivas con gestión compleja de foco/modalidad); sin kit visual.
8. **UI UX Pro Max**: tooling local en `.claude/skills/ui-ux-pro-max/` desde `v2.15.0`,
   ignorado por Git; consultas, adopciones y rechazos documentados (research §11 →
   `docs/design-system.md`).

## Remaining risks

1. **Riesgo técnico — paneles de conexión dentro de un sheet**: los 5 paneles se diseñaron
   inline; su *polling* de intentos debe sobrevivir al montaje en `AddAccountSheet` y en
   `AccountDetail`. Mitigación: se montan sin cambios de lógica; si el `<details>` cerrado
   desmonta el panel se usa `open` controlado para mantenerlo montado durante un intento.
2. **Riesgo técnico — `local_check` de TikTok lee el keyring**: el overview lo invoca para
   posts TikTok de los próximos 7 días; si el almacén no está disponible se captura y se
   muestra "Couldn't verify requirements" (nunca se oculta el post).
3. **Carrera Discard ↔ callback OAuth**: cubierta por re-comprobación transaccional; hay
   que verificar que el camino de fallo del callback no deja secretos huérfanos (test
   representativo con YouTube).
4. **Churn de tests existentes**: se eliminan `App.test.tsx` y `ProjectDetail.test.tsx`
    (su cobertura pasa a routes/accounts/onboarding) y se ajustan props en tests de Library
    y Queue; no se reescriben sus casos.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
