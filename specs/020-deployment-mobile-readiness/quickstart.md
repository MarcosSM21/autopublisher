# Quickstart & Validation: Deployment & Mobile Readiness (Feature 020)

Guía de validación de extremo a extremo. Contratos: [api](contracts/api.md), [ui](contracts/ui.md), [cli](contracts/cli.md). Decisiones: [research](research.md).

`autopublisher <cmd>` abrevia `uv run python -m app.cli <cmd>`, ejecutado desde `backend/` ([contracts/cli.md](contracts/cli.md)).

## 0. Preparación (host Linux actual)

```bash
cd frontend && npm ci && npm run build && cd ..          # or copy a dist built elsewhere
cd backend && uv sync --frozen --no-dev
uv run python -m app.cli configure --data-dir ~/.local/share/autopublisher --port 8000 --no-lan
```

Migrar los datos de desarrollo actuales (recomendado una vez, **antes** de fijar la contraseña, porque el restore sustituye la BD):

```bash
# with the dev backend stopped
AUTOPUBLISHER_DATA_DIR=$PWD/data uv run python -m app.cli backup --output ~/autopublisher-backups
uv run python -m app.cli restore ~/autopublisher-backups/autopublisher-backup-<ts>.tar
mv data data.migrated-<date>     # MANDATORY: retire it; never run development against these Accounts again (shared keyring entries)
```

Después (con o sin migración):

```bash
uv run python -m app.cli set-password
```

## Journeys automatizables (tests dirigidos, sin STOP)

| ID | Qué se prueba | Resultado esperado |
|---|---|---|
| T1 | Modo instalación con `dist` de prueba (incl. `/docs`, `/redoc`, `/openapi.json` → 404; `Range` en Media → 206) | `/p/1/posts/5` → `index.html`; `/assets/x.js` → fichero; `/api/nope` → 404 JSON; `/api` → 404 JSON |
| T2 | Sin sesión | `/api/projects` → 401 `auth_required`; `/health` 200; callbacks OAuth accesibles |
| T3 | Login / logout / expiración / cambio / reset (incl. carreras login vs reset/cambio) | ver contrato §3; idle 7 d renovable y absoluta 30 d con `FakeClock` (la renovación no supera 30 d); logout inmediato; tras cambio, la otra sesión → 401; reset CLI → todas 401; tope de 20 sesiones; cookie sin `Domain`/`Secure`, `HttpOnly`, `SameSite=Lax` |
| T4 | Rate limit | 6º fallo desde una IP → 429 sin evaluar contraseña |
| T5 | Host / Origin | `Host: evil.example` → 403; `Origin: http://evil.example` en POST → 403; `Host` = IP del socket → ok |
| T6 | Desarrollo | `app.main:app` sin login; cliente no-loopback → 403; tests existentes intactos |
| T7 | OAuth host-only | `authorize` YouTube/TikTok desde cliente no-loopback → 409 `host_only_action` |
| T8 | Keyring caído en la ventana | YouTube real + `FakePublisher` que lanza sin envolver: sigue `scheduled` con error visible; tras la ventana → `overdue`; sin intentos |
| T9 | Precedencia de rutas | individual > `AUTOPUBLISHER_DATA_DIR` > config > default |
| T10 | Locks | mismo data dir → error claro; data dirs distintos con la misma BD por override → error claro; lock liberado tras matar el proceso; `restore` con el servidor en marcha → exit 75; durante un restore (locks tomados, tras el swap) un servidor nuevo no arranca; `backup` concurrente con `restore` → bloqueado por M |
| T11 | Backup (incl. BD anterior a 020 sin `auth_sessions`) | con la app en marcha e imports concurrentes: tar con BD + referenciados + JSON + manifest; la BD archivada tiene `auth_sessions` vacía y `installation_auth` intacta; la BD en uso conserva sus sesiones; sin `tmp`, huérfanos; destino dentro de data → rechazado; fichero de Media alterado durante el backup → abortado sin `.tar`; fallo/ENOSPC inyectado → sin `.tar` final |
| T12 | Restore (incl. BD anterior a 020 → `set-password` la lleva a head; destino symlink/punto de montaje; duplicados en el tar) | tar válido → datos iguales, misma contraseña, cero sesiones, config del host intacta, locks retenidos durante el swap; tar con `../`, symlink, fichero extra, checksum malo, schema desconocido → rechazado sin tocar el destino |
| T13 | Health / diagnóstico | `/health` solo `status`; `/api/system/status` requiere sesión; sondeo keyring sin crear colección, sin `unlock`, sin lectura de secretos |
| T14 | Logs | flujos representativos sin contraseñas/tokens/secrets en el fichero |

## Journeys del host (manuales)

### A — Reinicio del host (STOP gate 1)

```bash
uv run python -m app.cli install-service
systemctl --user start autopublisher
systemctl --user status autopublisher          # active (running)
curl -s http://127.0.0.1:8000/health          # {"status":"ok"}
```

Reiniciar el ordenador → iniciar sesión (manual) → en < 2 min `curl …/health` = ok sin abrir terminal (SC-001). Abrir `http://127.0.0.1:8000`, iniciar sesión, Settings → "This installation": secure storage `available`. Opcional: con el llavero bloqueado (p. ej. login automático), Settings muestra "Secure storage is locked" sin que aparezca un diálogo por abrir Settings.

### D — Crash (STOP gate 1)

```bash
systemctl --user kill -s SIGKILL autopublisher
sleep 10; curl -s http://127.0.0.1:8000/health    # ok again (SC-002)
journalctl --user -u autopublisher -e            # shows the restart
```

### C — Scheduler tras reinicio

Programar un Post (cuenta real o una que falle de forma controlada) para dentro de 15 min → `systemctl --user restart autopublisher` → sigue "Scheduled · automatic" y se ejecuta en su ventana. Programar otro para dentro de 5 min, cerrar sesión/apagar 15 min → al volver aparece **Missed**.

### E — Persistencia

Tras el reinicio de A: Projects, Media (previews), Posts, presets, configuración de plataformas presentes; misma contraseña; la sesión del navegador sigue válida (las sesiones sobreviven reinicios del servicio).

### F — Backup / restore

```bash
uv run python -m app.cli backup
tar -tf ~/autopublisher-backups/autopublisher-backup-<ts>.tar | head
systemctl --user stop autopublisher
AUTOPUBLISHER_DATA_DIR=/tmp/ap-restore-test uv run python -m app.cli restore <tar> --yes
```

### G — Mover de host

Revisión documental de `docs/deployment.md` → "Move to another computer" (5 pasos de FR-082).

## B — LAN y móvil (STOP gate 2)

```bash
uv run python -m app.cli configure --lan
systemctl --user restart autopublisher
uv run python -m app.cli status            # shows http://<lan-ip>:8000
```

En un móvil de la misma Wi-Fi: abrir la dirección → login → Home → Posts → Calendar → Post detail (preview de imagen y de vídeo) → Reschedule de un Post → Publish de una Media existente hasta Review + **Finish later** → Text post (Finish later) → subir una imagen pequeña a Library → Settings (sección "This installation" con aviso HTTP) → Sign out. Comprobar que Connect YouTube muestra la explicación host-only. Desde otro dispositivo sin login: no se ve ningún dato. Con LAN off: el móvil no conecta.

No hace falta publicar contenido real.

## OAuth en el host (STOP gate 3, condicional)

Solo si el routing/guards tocan los callbacks de forma que los tests con transports falsos no cubran: en `http://127.0.0.1:8000`, Reconnect de YouTube o TikTok completa el flujo.
