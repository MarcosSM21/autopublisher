# Data Model: Distribución multiplataforma y presets de destinos

## Entidades existentes (sin cambios de esquema)

### Publication

Sin columnas nuevas. Los textos de la distribución se guardan en los overrides existentes:

| Campo | Tipo | Origen en Feature 017 |
|---|---|---|
| `title_override` | `str(≤200) \| NULL` | destino > común > `NULL` (hereda `Content.title`) |
| `description_override` | `str(≤5000) \| NULL` | destino > común > `NULL` (hereda `Content.description`) |
| `hashtags_override` | `list[str] \| NULL` | destino > común > `NULL` (hereda `Content.hashtags`) |

`""` y `[]` son overrides explícitos vacíos (no heredan). La metadata efectiva se sigue
calculando con `effective_metadata()` sin cambios.

Estados que bloquean una nueva Publication del mismo par (Content, Account): todos salvo
`HISTORY_STATUSES = (CANCELLED, PUBLISHED)`, igual que el índice único parcial actual.

No existe entidad `Distribution`, ni identificador de lote, ni columna de agrupación.

## Entidades nuevas

### DistributionPreset — tabla `distribution_presets`

| Columna | Tipo | Restricciones |
|---|---|---|
| `id` | integer | PK |
| `project_id` | integer | NOT NULL, FK `projects.id` ON DELETE CASCADE |
| `name` | string(100) | NOT NULL; texto recortado, 1..100 caracteres |
| `name_key` | string | NOT NULL; `normalize_key(name)` |
| `created_at` | datetime (UTC) | NOT NULL |
| `updated_at` | datetime (UTC) | NOT NULL |

- `UNIQUE(project_id, name_key)` → nombre único por proyecto, sin distinguir mayúsculas ni
  formas Unicode equivalentes.
- Índice implícito por la restricción única (listado por proyecto ordenado por `name_key`).

### DistributionPresetAccount — tabla `distribution_preset_accounts`

| Columna | Tipo | Restricciones |
|---|---|---|
| `preset_id` | integer | NOT NULL, FK `distribution_presets.id` ON DELETE CASCADE |
| `account_id` | integer | NOT NULL, FK `accounts.id` ON DELETE CASCADE |

- PK compuesta `(preset_id, account_id)` → sin cuentas repetidas en un preset.
- Índice en `account_id` (búsqueda inversa y CASCADE eficientes).

### Reglas de validación (aplicación)

- Crear/editar: `name` obligatorio (recortado, 1..100); `account_ids` 1..50 ids, sin repetidos.
- Cada `account_id` debe existir y pertenecer al `project_id` del preset; si no → 422,
  ninguna escritura.
- Se permiten cuentas inactivas (se omiten al aplicar el preset).
- Un preset existente puede quedar con 0 cuentas solo por CASCADE (borrado externo de
  cuentas); sigue existiendo. Hoy la API no borra cuentas ni proyectos.
- `PATCH` con `account_ids` reemplaza el conjunto completo en la misma transacción;
  `updated_at` se actualiza si cambia el nombre o el conjunto.

### Relaciones

```text
Project 1 ──< DistributionPreset 1 ──< DistributionPresetAccount >── 1 Account
   │                                                                     │
   └──────────────────────────────< Account (project_id) ────────────────┘
```

Invariante: `Account.project_id == DistributionPreset.project_id` para toda fila de
`distribution_preset_accounts` (garantizada en la aplicación al escribir; las cuentas no
cambian de proyecto).

## Modelos de request (no persistidos)

### PublicationOverrides (nuevo, base)

| Campo | Tipo | Semántica |
|---|---|---|
| `title_override` | `TitleOverride` (str ≤200, strip, `""` permitido) \| null | null/omitido = sin override en este nivel |
| `description_override` | `DescriptionOverride` (str ≤5000) \| null | idem |
| `hashtags_override` | `list[str]` normalizada \| null | idem; `[]` = vacío explícito |

`extra="forbid"`.

### PublicationCreate (ampliado)

`PublicationOverrides` + `account_ids`, `scheduled_at`, `auto_publish_enabled` (sin cambios)
+ `targets: dict[int, PublicationOverrides] | null` (claves ⊆ `account_ids`).

### Resolución por destino

```text
for field in (title, description, hashtags):
    value = targets[account].field  if not None
         else common.field          if not None
         else None                  # hereda del Content
```

## Estado de UI (no persistido)

- `selected: number[]` — cuentas marcadas.
- `common: Record<"description" | "hashtags", {edited: boolean; text: string}>`.
- `customizations: Record<accountId, Partial<Record<"title" | "description" | "hashtags", {edited: boolean; text: string}>>>`.
- `when: {mode: "prepare"} | {mode: "schedule"; at: string}`.
- `skipped: {accountId, reason: "inactive" | "active_publication"}[]` — tras aplicar un preset.
- `created: Publication[] | null` — si no es null se muestra el panel de resultado.
