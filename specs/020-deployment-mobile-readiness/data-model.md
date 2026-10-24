# Data Model: Deployment & Mobile Readiness (Feature 020)

Solo lo nuevo. Ningún modelo existente cambia. Una migración Alembic nueva crea dos tablas.
La configuración del host y el manifest de backup son **ficheros**, no entidades de BD.

## Tablas nuevas (SQLite, estado portable)

### `installation_auth` — contraseña de instalación (fila única)

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | INTEGER PK | Siempre `1` (`CHECK (id = 1)`). |
| `password_hash` | TEXT NOT NULL | `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>` (research §10). Nunca se expone por API ni logs. |
| `password_changed_at` | UTCDateTime NOT NULL | Momento del último set/cambio/reset. |

- Sin fila → no hay contraseña configurada → `serve` termina con exit 78 ("Run `autopublisher set-password` first").
- `set-password` (CLI local) hace upsert y borra todas las `auth_sessions` en la misma transacción.
- `POST /api/auth/password` actualiza el hash, borra todas las sesiones y crea una nueva para el navegador actual, en una transacción.
- Re-hash transparente al hacer login si los parámetros guardados difieren de los actuales.
- **Portable**: el string del hash incluye algoritmo, parámetros y sal; viaja en el backup y se conserva tras un restore. No hace falta ningún contador de generación: la invalidación de sesiones es borrar filas de `auth_sessions`.

### `auth_sessions` — sesiones de navegador

| Campo | Tipo | Reglas |
|---|---|---|
| `token_hash` | TEXT(64) PK | `sha256(token)` en hex; el token solo existe en la cookie. |
| `created_at` | UTCDateTime NOT NULL | |
| `last_seen_at` | UTCDateTime NOT NULL | Renueva el plazo de inactividad; se escribe como mucho cada 10 min. |
| `expires_at` | UTCDateTime NOT NULL | `created_at + 30 días` (vida absoluta; nunca se amplía). |

Validez: `now < min(last_seen_at + 7 días, expires_at)` (idle 7 d renovable por actividad, absoluta 30 d). Una sesión inválida se borra al detectarla.

**No es estado portable**: la tabla vive en la BD, pero la copia que entra en un backup se vacía (y se hace `VACUUM`) antes de archivarla; la BD en uso nunca se toca por hacer un backup. Purga acotada: caducadas al arrancar y en cada login; tope de 20 sesiones válidas (se borran las de `last_seen_at` más antiguo).

Transiciones:

```text
login ok ─────────────► fila nueva (token nuevo; nunca reutiliza el presentado)
uso (≥10 min) ────────► last_seen_at = now (sin superar expires_at)
sign out ─────────────► borra la fila
cambio de contraseña ─► borra todas + fila nueva para el navegador actual
set-password (CLI) ───► borra todas
backup ───────────────► la copia archivada no contiene filas (la BD en uso no cambia)
restore ──────────────► cero sesiones (vacía también la tabla en el staging, por defensa)
arranque / login ─────► borra las caducadas; login aplica el tope de 20
```

Sin relación con otras tablas (single-user). En el backup viaja `installation_auth` con la BD; `auth_sessions` viaja vacía (FR-030c, FR-050, FR-053a).

## Ficheros (no BD)

### Configuración del host — `~/.config/autopublisher/config.toml`

| Clave | Tipo | Default | Reglas |
|---|---|---|---|
| `data_dir` | string (ruta absoluta) | `$XDG_DATA_HOME/autopublisher` | Debe ser absoluta; se crea con 0700. `AUTOPUBLISHER_DATA_DIR` la sobrescribe. |
| `port` | int | `8000` | 1024–65535. Cambiarlo exige actualizar los redirect URIs de YouTube/TikTok (documentado). |
| `lan_enabled` | bool | `false` | `false` → bind `127.0.0.1`; `true` → bind `0.0.0.0`. |
| `allowed_hosts` | list[string] | `[]` | Nombres DNS/mDNS extra válidos en `Host` (minúsculas, sin puerto ni esquema). |
| `frontend_dist` | string (ruta absoluta) | `<repo>/frontend/dist` | Debe contener `index.html`. |

Claves desconocidas o inválidas → error de configuración (exit 78). Permisos 0600. Nunca se incluye en backups ni se aplica desde ellos.

### Manifest de backup — `manifest.json` dentro del `.tar`

Ver [research.md §21](research.md). Campos: `format`, `format_version` (1), `created_at`, `app_version`, `schema_revision`, `components`, `files[] {path, size, sha256}`, `source {hostname}` (informativo, nunca aplicado).

### Locks — `<home de passwd>/.local/state/autopublisher/locks/`

`maint-<hash(data_dir)>.lock`, `data-<hash(data_dir)>.lock`, `db-<hash(db_path)>.lock` (hash SHA-256 de la ruta canónica). Contienen PID/comando/ruta (informativo); la exclusión real es `flock`. Viven fuera del directorio de datos, así que el swap del restore no los sustituye (research §9). La raíz no depende de variables de entorno (research §9). Host/runtime, nunca en backup.

## Clasificación del estado (FR-047)

| Clase | Contenido | Backup | Migración |
|---|---|---|---|
| Portable | BD (incl. `installation_auth`), Media referenciada (originales y copias limpias), JSON de plataforma | Sí | Se restaura |
| No portable (en la BD) | Filas de `auth_sessions` | No (copia vaciada) | Restore empieza con cero sesiones |
| Host | `config.toml`, unidad systemd, logs, locks | No | Se reconfigura en cada host |
| Runtime / regenerable | `tmp/`, `media/tmp/`, ficheros huérfanos, `.venv`, `frontend/dist`, `node_modules`, backups producidos | No | Se regenera |
| Keyring | Tokens/sesiones de cuentas | No | Reconectar cuentas |
