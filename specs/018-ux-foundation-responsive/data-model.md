# Data Model: UX Foundation & Responsive App (Feature 018)

Feature 018 **no crea tablas ni columnas**. Hay un único cambio de esquema (nulabilidad de
`accounts.handle`) y varios **read-models derivados** sin persistencia.

## 1. Cambio persistente: `Account.handle` opcional

| Campo | Antes | Después |
|---|---|---|
| `accounts.handle` | `VARCHAR(100) NOT NULL` | `VARCHAR(100) NULL` |
| `accounts.handle_key` | `VARCHAR NOT NULL` | `VARCHAR NULL` |
| `UNIQUE(project_id, platform, handle_key)` | — | sin cambios (NULLs distintos en SQLite) |

- Migración `0017_account_handle_optional` (Alembic `batch_alter_table`), reversible: el
  `downgrade` falla de forma explícita si existen cuentas con `handle IS NULL` (no inventa
  valores).
- Invariante: `handle IS NULL` ⇔ `handle_key IS NULL`.
- Significado de `NULL`: "identidad aún desconocida". Solo lo produce el alta nueva; se
  rellena en la primera conexión correcta (`adopt_connected_identity`), salvo colisión.
- Transiciones:

```text
create(platform)                  handle = NULL
  └─ connect OK ──► adopt         handle = identidad (si libre) | NULL (si colisiona)
create(platform, handle) (legacy) handle = valor del usuario (nunca se sobrescribe)
PATCH handle                      igual que hoy (no permite volver a NULL)
DELETE (Discard)                  solo cuentas provisionales (ver abajo)
```

Una cuenta es **provisional** (descartable) si y solo si: `handle IS NULL` (nunca se adoptó
identidad), no existe fila de conexión en ninguna de las 5 tablas (ni `connected` ni
`reconnect_required`) y no tiene publicaciones en ningún estado.
Una cuenta que ya tuvo identidad (legacy o adoptada) nunca vuelve a ser provisional, aunque
después se desconecte: no hay borrado general de cuentas.

## 2. Read-models (sin persistencia)

Todos se calculan por petición con un reloj inyectable (`now`) y el flag de pausa global.
Nunca escriben, nunca leen secretos para construir la vista (salvo el `local_check` de
TikTok, que ya lee el almacén seguro local), nunca llaman a plataformas.

### PostDisplayState

Enum: `draft`, `scheduled_automatic`, `scheduled_manual`, `scheduled_paused`, `publishing`,
`published`, `failed`, `needs_review`, `needs_action`, `missed`, `cancelled`.
Función pura `post_display_state(status, armed, scheduled_at, paused, latest_attempt, now)`;
tabla de reglas en [research.md §7](research.md#7-derivación-de-attention). Expuesto como
campo aditivo `display_state` en `PublicationRead` y en los items del overview.

Etiquetas de producto (frontend, `StatusBadge`): Draft · Scheduled · automatic ·
Scheduled · manual · Scheduled · paused · Publishing · Published · Failed ·
Needs review · Needs action · Missed · Cancelled.

### AttentionItem

| Campo | Tipo | Notas |
|---|---|---|
| `kind` | `manual_review \| failed \| missed \| needs_action \| reconnect \| incomplete \| expiring` | |
| `priority` | int 1–7 | orden de la tabla de reglas |
| `project` | `{id, name}` | |
| `account` | `{id, platform, label}` | `label` = `account_label()` |
| `post` | `{id, display_state, scheduled_at, media_title?, excerpt?} \| null` | null en `reconnect`/`expiring` |
| `title` | string | problema en lenguaje claro ("Upload failed", "Missed its time") |
| `detail` | string \| null | causa saneada (mensaje de error ya seguro, primer problema de `local_check`, "Couldn't verify requirements", motivo de pausa) |
| `at` | datetime \| null | momento relevante (fallo, hora programada, caducidad) |
| `action` | `{label, target}` | **una** acción; `target` = `{type: "post"\|"account"\|"settings", project_id?, id?}` |
| `affected_posts` | int | solo `reconnect`: posts próximos plegados en este item |

Reglas de unicidad: como máximo un item por post (el de menor `priority`) y como máximo uno
por cuenta (`reconnect` excluye `expiring`).

### UpcomingPost

`{post_id, project:{id,name}, account:{id,platform,label}, scheduled_at, display_state,
media_title?, excerpt?}`. Global: los 5 `scheduled` con `scheduled_at > now` de proyectos
activos, orden ascendente.

### ProjectSummary

| Campo | Notas |
|---|---|
| `id`, `name`, `is_active` | |
| `accounts_active` | cuentas con `is_active` |
| `accounts_ready` | cuentas activas con health `ready` |
| `attention_count` | items de atención del proyecto |
| `next_post` | `{post_id, scheduled_at, display_state} \| null` |
| `onboarding` | `{account_ready, media_imported, post_created, complete}` |

### AccountHealth

| Campo | Notas |
|---|---|
| `account_id`, `platform`, `label`, `display_name`, `is_active` | |
| `state` | `ready \| reconnect_needed \| setup_required \| not_connected \| inactive` (UI: Ready, Reconnect needed, Finish setup, Not connected, Inactive) |
| `identity` | `{name, username?, avatar_url?} \| null` (de la fila de conexión; sin IDs) |
| `expires_at` | datetime \| null (solo Instagram, Threads, TikTok) |
| `expiring` | bool (`ready` y `expires_at <= now + 7d`) |
| `capabilities` | lista de `text \| images \| videos` |
| `issue` | `{code, message} \| null` |
| `can_discard` | bool: cuenta provisional (`handle` nulo, sin conexión, sin publicaciones) |

Precedencia de `state` y fuentes por plataforma: [research.md §8](research.md#8-account-health-por-plataforma-sin-red-sin-escrituras).

### PlatformAvailability

| Campo | Notas |
|---|---|
| `platform`, `label` | incluye `x` |
| `integration_available` | false solo para X |
| `status` | `configured \| partial \| not_configured \| coming_soon` |
| `can_connect` | configuración de app presente y válida |
| `missing` | lista de `app_credentials \| media_delivery` |
| `message` | texto saneado propio; nunca rutas, contenidos ni valores |

`partial`: se puede conectar pero falta algo para publicar parte del contenido (Instagram y
Threads sin media delivery).

### OnboardingProgress

Incluido en `ProjectSummary.onboarding` (ver arriba). Pasos derivados; ninguna tabla.

## 3. Frontend: única preferencia local

| Clave | Valor | Uso |
|---|---|---|
| `autopublisher.lastProjectId` | entero en texto | resolver Library/Posts/Accounts desde contextos globales |

Lectura/escritura tolerantes a fallo (`try/catch`); nunca datos de negocio.
