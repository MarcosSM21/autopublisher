# UI Contracts — Feature 018

Contratos de la interfaz que los tests y Feature 019 pueden asumir. Textos visibles en
inglés (producto); nombres de componentes y rutas son los de implementación prevista.

## 1. Route tree

| URL | Elemento | Notas |
|---|---|---|
| `/` | `HomePage` | `?project=<id>` filtra Needs attention; chip "Showing <Project> · Show all" |
| `/settings` | `SettingsPage` | |
| `/p/:projectId` | → `/p/:projectId/library` (replace) | landing de proyecto |
| `/p/:projectId/library` | `LibraryPage` | `ContentLibrary` existente, selección controlada |
| `/p/:projectId/library/:mediaId` | `LibraryPage` con medio seleccionado | `ContentDetail` inline (019 lo migra a `DetailSurface`) |
| `/p/:projectId/posts` | `PostsPage` (vista List) | `PublicationQueue` existente, sin `AutomationStatus` |
| `/p/:projectId/posts/:postId` | `PostsPage` con post seleccionado | `PublicationDetail` inline |
| `/p/:projectId/accounts` | `AccountsPage` | |
| `/p/:projectId/accounts/new` | `AccountsPage` + `AddAccountSheet` | cerrar = volver a `accounts` |
| `/p/:projectId/accounts/:accountId` | `AccountsPage` + `AccountDetail` en `DetailSurface` | |
| cualquier otra | `NotFound` | una acción: "Go to Home" (o "Back to <section>" dentro de proyecto) |

Reglas:

- Ids no numéricos, inexistentes o de otro proyecto → `NotFound` (nunca pantalla en blanco ni
  cambio silencioso de proyecto).
- Destinos de proyecto desde contexto global (Home, Settings): proyecto de la preferencia
  `autopublisher.lastProjectId` si existe y es válido; si no, el primer proyecto activo (o el
  primero); si no hay proyectos, los destinos de proyecto se muestran deshabilitados con
  `aria-disabled` y Home muestra "Create your first project".
- Cambiar de proyecto en `ProjectSelector` conserva la sección (`library|posts|accounts`) y
  descarta el id de detalle.
- `NavLink` marca el destino activo con `aria-current="page"`.

## 2. App shell

```text
lg ≥1024     ┌──────────┬──────────────────────────────┐
             │ Home     │ [Project header · status strip]│
             │ Project ▾│ [Onboarding checklist?]        │
             │ Library  │  <page>                 [detail│
             │ Posts    │                          panel]│
             │ Accounts │                                │
             │ Settings │                                │
             └──────────┴──────────────────────────────┘
md 768–1023  rail de iconos + etiqueta corta; ProjectSelector arriba del contenido;
             detalles en drawer superpuesto
sm <768      ┌ TopBar: [Project ▾]              [More ⋯] ┐   More → Settings
             │ <page>                                    │
             └ BottomNav: Home · Library · Posts · Accounts┘
             detalles a pantalla completa con "Back"
```

- Un único `<nav aria-label="Main">`; un único `<main>`; skip link "Skip to content".
- En `sm` la bottom nav es fija y el contenido reserva su altura + `env(safe-area-inset-bottom)`.
- Todos los objetivos ≥ 44×44 px.

## 3. Páginas

### HomePage

Orden: banner de automatización en pausa (si aplica) → **Needs attention** o **Everything
looks good** → **Up next** → **Projects**.

- Carga: skeleton; error: `ErrorState` con "Retry". Nunca "Everything looks good" sin datos.
- `AttentionItem`: título del problema, contexto (`Project · Account · media/excerpt ·
  tiempo relativo`), `StatusBadge` si hay post, **un** botón/enlace primario (texto de
  `action.label`) que navega al destino. Todo el item no es un único enlace (evita enlaces
  anidados); el botón es el objetivo.
- Con `?project=<id>`: `GET /api/overview?project_id=<id>` (nunca filtrado local de un
  overview global); chip "Showing <name> · Show all projects" → `/`; 404 o id inválido →
  "This project doesn't exist" con "Show all projects".
- `Everything looks good`: una frase breve ("Nothing needs your attention right now."); la
  próxima publicación ya aparece en Up next.
- `Up next`: ≤ 5 filas compactas (hora, cuenta, medio/extracto, `StatusBadge`), cada una
  enlaza a su post. Sin "See more".
- `Projects`: filas con nombre, "N need attention" o "All good", enlace a
  `/p/:id/library`. Botón secundario "New project" (dialog). Sin proyectos: `EmptyState`
  "Create your first project" (único CTA) en lugar de las tres secciones.

### ProjectLayout

- Cabecera: nombre, badge "Inactive" si aplica, disclosure "Project actions" (Edit project,
  Deactivate/Activate) reutilizando `ProjectForm` en `Dialog`.
- `ProjectStatusStrip`: `3/4 accounts ready` → `accounts`; `2 need attention` →
  `/?project=<id>`; `Next: tomorrow 10:00` → post; "Automation paused" → `/settings` si
  aplica. Elementos vacíos se omiten; en `sm` puede partirse en dos líneas.
- `OnboardingChecklist` (solo si `!onboarding.complete`): 3 pasos con estado; solo el
  siguiente paso tiene CTA primario.

### LibraryPage / PostsPage

Montaje temporal de componentes existentes (ver research §3). Cambios visibles: títulos
"Library" y "Posts"; botón "Distribute" → "Publish…"; en Posts, banner de pausa enlazado a
Settings en lugar del control.
Empty states: Library sin medios → "Import your first media" (abre el import existente);
Posts sin posts → "Open the Library to publish your media" (un CTA → `library`).

### AccountsPage

- Sin cuentas: `EmptyState` "Connect an account" (único CTA → `accounts/new`).
- Lista de `AccountCard` (activas primero; inactivas atenuadas en sección "Inactive").
- `AccountCard`: icono + nombre de plataforma, identidad (o "Not connected yet"),
  `StatusBadge` de cuenta (Ready / Reconnect needed / Finish setup / Not connected /
  Inactive), capacidades ("Text · Images · Videos"), `issue.message`, aviso de caducidad
  ("Login expires in 4 days"), **una** acción primaria según estado (Reconnect / Finish
  setup / Connect / ninguna si Ready) y enlace "Details" → `accounts/:id`.
- Botón de página "Add account" → `accounts/new`.

### AccountDetail (en `DetailSurface`)

- Siempre visible: estado, identidad, problema, acción principal.
- "Name in AutoPublisher" (display name) editable; Activate/Deactivate; "Discard" solo si
  `can_discard` (cuenta provisional); nunca para cuentas con identidad, conexión o posts.
- `<details>` **"Connection & technical details"** (cerrado por defecto): el
  `<Platform>ConnectionPanel` existente (scopes, IDs, Test connection, Disconnect, flujos de
  reconexión y confirmación). Si la acción principal es Reconnect/Connect/Finish setup, el
  `<details>` se abre automáticamente con el panel enfocado en esa acción.

### AddAccountSheet (`accounts/new`)

1. **Choose platform**: tarjetas radio de las 6 plataformas. `coming_soon` →
   deshabilitada con badge "Coming soon". `not_configured` → seleccionable pero el paso 2
   muestra "AutoPublisher isn't set up for <Platform> yet" + **Open Settings** (única
   acción) en lugar de Connect.
2. **Connect**: botón "Connect <Platform>" → `POST /projects/{id}/accounts {platform}` →
   monta el panel de conexión existente de esa cuenta (OAuth, pegar URL o Telegram teléfono
   → código → contraseña → canal) en el sheet.
3. **Done**: al pasar el panel a conectado → navega a `accounts/:accountId`.
- Cerrar antes de conectar **no** descarta nada: la cuenta provisional queda visible como
  "Not connected" (con Connect y "Discard setup"). Solo la acción explícita "Discard setup"
  (en el sheet o en el detalle, con confirmación) llama a `DELETE`; un `409` (p. ej.
  `account_busy`) se muestra y la cuenta sigue recuperable.
- Telegram conectado sin canal → el panel continúa en el paso de canal; si se cierra antes,
  la cuenta queda en "Finish setup" (no es provisional: ya tiene conexión).

### SettingsPage

- **Automation**: `AutomationStatus` existente (Pause/Resume, scheduler running, last check).
- **Platforms**: fila por plataforma con `StatusBadge` (Configured / Partially configured / Not
  configured / Coming soon) y `message`. Sin edición, sin rutas, sin secretos.

## 4. Primitivas del design system (`src/ui/`)

| Primitiva | Contrato |
|---|---|
| `Button` | variantes `primary` (máx. una por vista/empty state), `secondary`, `ghost`, `danger`; `size` `md` (≥44 px); `loading` deshabilita y anuncia; usa `<button>` o `<Link>` (`as="link"`) |
| `IconButton` | `aria-label` obligatorio (tipo requerido), ≥44×44 px, icono SVG `aria-hidden` |
| `Badge` / `StatusBadge` | texto siempre presente + icono; `StatusBadge` recibe `PostDisplayState`, `AccountHealthState` o `PlatformStatus` y resuelve etiqueta y tono desde un único mapa |
| `Card` | contenedor con borde; sin sombra |
| `EmptyState` | `title`, `description?`, `action` (exactamente una primaria, tipo requerido), `secondary?` (enlace) |
| `ErrorState` | mensaje + `onRetry` (botón "Retry") o acción de recuperación |
| `Skeleton` | bloques con `aria-hidden`; el contenedor tiene `aria-busy="true"` |
| `Dialog` | Radix Dialog centrado; título obligatorio; Escape y overlay cierran; foco devuelto |
| `Drawer` | Radix Dialog anclado a la derecha (`md`/`lg`) |
| `Sheet` | Radix Dialog a pantalla completa en `sm`, centrado en `md+` (Add account) |
| `DetailSurface` | `lg` panel lateral no modal; `md` `Drawer`; `sm` página con "Back"; cierre = `navigate(parent)` |
| `Disclosure` | `button[aria-expanded][aria-controls]` + región; Escape cierra y devuelve foco |
| `Icon` | SVG inline propios (home, library, posts, accounts, settings, more, back, close, alert, check, clock, plus); sin emoji |

## 5. Tokens (`src/ui/tokens.css`, tema claro)

Organizados en dos capas para permitir dark mode futuro sin tocar componentes: primitivos
(`--blue-700`, `--gray-900`…) y semánticos (`--color-text`, `--color-surface`,
`--color-action`…). Los componentes **solo** usan semánticos.

| Grupo | Valores |
|---|---|
| Tipografía | `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; base 16 px, line-height 1.5; escala 14 / 16 / 18 / 20 / 24 / 30; pesos 400/600 |
| Espaciado | 4 · 8 · 12 · 16 · 24 · 32 · 48 (`--space-1..7`) |
| Radios | 6 px (controles), 10 px (cards/superficies), 999 px (badges) |
| Sombras | solo superficies flotantes: `--shadow-overlay` |
| Color base | texto `#1F2328` (16:1), texto secundario `#57606A` (≥ 6:1), borde `#D0D7DE`, superficie `#FFFFFF`, fondo `#F6F8FA` |
| Acción | `--color-action #1D4ED8` (blanco encima ≥ 6.5:1), hover `#1E40AF` |
| Estados | success `#1A7F37`, warning `#9A6700`, danger `#CF222E`, info `#0969DA`, neutral `#57606A`; fondos suaves correspondientes; texto ≥ 4.5:1 sobre su fondo |
| Foco | `outline: 2px solid var(--color-focus)` + `outline-offset: 2px`, `--color-focus #1D4ED8`, contraste ≥ 3:1; solo `:focus-visible` |
| Interacción | hover/active/disabled por token; transiciones 150–200 ms; `@media (prefers-reduced-motion: reduce)` → sin transiciones |
| Breakpoints | `768px`, `1024px` (constantes compartidas CSS/JS) |
| Touch | `--target-min: 44px` |

Mapa de tonos de `StatusBadge`:

| Tono | Estados |
|---|---|
| success | Ready, Published, Configured |
| info | Scheduled · automatic, Publishing |
| neutral | Draft, Scheduled · manual, Cancelled, Inactive, Coming soon, Not connected |
| warning | Scheduled · paused, Needs action, Finish setup, Partially configured, expiring |
| danger | Failed, Needs review, Missed, Reconnect needed, Not configured |

## 6. Terminología visible

| Interno / API | Visible |
|---|---|
| Publication | Post |
| Content / Asset | Media |
| Asset Library | Library |
| Queue | Posts |
| Unscheduled / Prepare | Draft / Save as draft |
| Distribute | Publish… |
| preflight, reconcile, attempt, checksum | solo dentro de detalles técnicos plegados |

Aplicación en 018: shell, Home, strip, checklist, Accounts, Settings, empty states, títulos de
Library/Posts y botón Publish…. El resto de textos de las pantallas de 019 se migra en 019.
