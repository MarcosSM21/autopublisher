# Data Model: Gestión básica de proyectos y cuentas

**Feature**: `002-projects-accounts` | **Fecha**: 2026-10-05

Persistencia en SQLite mediante SQLAlchemy; esquema creado y evolucionado con Alembic
(ver [research.md](research.md), decisiones 1–5 y 8).

## Normalización de claves de unicidad

`normalize_key(value) = NFKC(casefold(NFKC(value)))`, aplicada en Python sobre el valor ya
recortado (y, en handles, sin `@` inicial). Las columnas `*_key` no se exponen en la API y
nunca se calculan en SQL. Detalle y motivos en [research.md](research.md), decisión 5.

Ejemplos de valores equivalentes: `L4i4` / `l4i4`; `Straße` / `STRASSE`; `é` precompuesta /
`e` + acento combinante.

## Project (`projects`)

| Campo | Tipo | Restricciones | Expuesto en API |
|-------|------|---------------|-----------------|
| `id` | integer | PK, autoincremental | sí |
| `name` | text | NOT NULL, 1–100 caracteres tras recortar espacios | sí |
| `name_key` | text | NOT NULL, **UNIQUE**; `normalize_key(name)` | no |
| `description` | text | NULL, ≤ 1000 caracteres; vacío → `NULL` | sí |
| `is_active` | boolean | NOT NULL, por defecto `true` | sí |
| `created_at` | datetime UTC | NOT NULL; asignado al crear, inmutable | sí |
| `updated_at` | datetime UTC | NOT NULL; igual a `created_at` al crear | sí |

**Reglas**:
- Unicidad del nombre sin distinguir mayúsculas, incluidos proyectos inactivos (FR-003).
- Orden de listado: `name_key` ascendente (FR-004).
- No se elimina nunca (FR-008).

## Account (`accounts`)

| Campo | Tipo | Restricciones | Expuesto en API |
|-------|------|---------------|-----------------|
| `id` | integer | PK, autoincremental | sí |
| `project_id` | integer | NOT NULL, FK → `projects.id` `ON DELETE RESTRICT`; inmutable | sí |
| `platform` | text | NOT NULL, uno de los valores de `Platform`; inmutable | sí |
| `handle` | text | NOT NULL, 1–100 caracteres; sin espacios exteriores ni `@` inicial | sí |
| `handle_key` | text | NOT NULL; `normalize_key(handle)` | no |
| `display_name` | text | NULL, ≤ 100 caracteres; vacío → `NULL` | sí |
| `is_active` | boolean | NOT NULL, por defecto `true` | sí |
| `created_at` | datetime UTC | NOT NULL; asignado al crear, inmutable | sí |
| `updated_at` | datetime UTC | NOT NULL; igual a `created_at` al crear | sí |

**Índices**:
- UNIQUE `(project_id, platform, handle_key)` (FR-013, incluye cuentas inactivas).
- Índice sobre `project_id` (lo cubre el índice único por ser su primera columna).

**Reglas**:
- Solo se puede crear en un proyecto existente (FR-012) y activo (Edge Cases).
- Orden de listado: `platform` y después `handle_key` ascendentes (FR-014).
- No se elimina nunca (FR-017).

## Platform (enumeración, sin tabla)

| Valor en API / BD | Etiqueta visible |
|-------------------|------------------|
| `youtube` | YouTube |
| `instagram` | Instagram |
| `tiktok` | TikTok |
| `x` | X |
| `threads` | Threads |
| `telegram` | Telegram |

Se define como `enum.StrEnum` en el backend y se guarda como texto (sin restricción
`CHECK` ni tipo `ENUM` nativo, para que añadir una plataforma en el futuro no requiera
migración). La validación ocurre en la API (FR-010).

## Relaciones

```text
Project 1 ──── 0..* Account
```

- Una cuenta pertenece exactamente a un proyecto; el proyecto no cambia nunca.
- Desactivar un proyecto no modifica sus cuentas (FR-007): el estado de cada registro es
  independiente.

## Estados y transiciones

Aplica igual a `Project` y `Account`:

```text
          PATCH is_active=false
 activo ─────────────────────────▶ inactivo
        ◀─────────────────────────
          PATCH is_active=true
```

- Estado inicial: `activo`.
- No hay estado terminal ni eliminación.
- Restricción adicional: no se pueden crear cuentas en un proyecto inactivo (`409
  project_inactive`). Editar o cambiar el estado de cuentas existentes de un proyecto
  inactivo sí está permitido.

## Regla de `updated_at` (FR-018)

Al procesar un `PATCH`, para cada campo recibido se compara el valor **normalizado** con el
valor actual:

- Si al menos un campo cambia → se aplican los cambios y `updated_at = now()` (UTC).
- Si ningún campo cambia (incluida una activación/desactivación sobre un recurso que ya está
  en ese estado, o una edición con los mismos valores) → no se escribe nada y `updated_at`
  conserva su valor. La respuesta es `200` con el recurso sin cambios.
- `created_at` no se modifica nunca.

Ejemplo: cambiar el handle de `l4i4` a `@l4i4` no es un cambio efectivo (se normaliza al
mismo valor). Cambiar de `l4i4` a `L4i4` sí lo es (cambia el texto mostrado), y no choca
con la propia cuenta en la comprobación de duplicados.

## Migración inicial

`0001_create_projects_and_accounts`: crea `projects` y `accounts` con todas las columnas,
la clave foránea y los índices descritos. Cualquier cambio futuro de modelos DEBE ir
acompañado de una nueva migración (lo verifica el test de deriva de esquema).
