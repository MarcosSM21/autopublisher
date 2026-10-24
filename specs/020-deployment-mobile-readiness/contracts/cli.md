# CLI Contract: `autopublisher` (Feature 020)

Módulo `app/cli.py` con `argparse`. **Ningún texto visible** (UI, errores, salida del CLI, documentación operativa) muestra `autopublisher <cmd>` como comando ejecutable: se usa la invocación real o se remite a `docs/deployment.md`. El backend no es un proyecto empaquetado (sin `[build-system]`), así que **no** se instala un console script y 020 no añade empaquetado: la invocación canónica es `uv run python -m app.cli <cmd>` desde `backend/` (o `backend/.venv/bin/python -m app.cli <cmd>`, que usa la unidad systemd). En estos documentos, `autopublisher <cmd>` es la abreviatura de esa invocación. Mensajes en inglés, sin secretos. Exit codes: `0` ok, `1` error, `2` uso, `75` recurso ocupado (lock), `78` configuración inválida/incompleta.

| Comando | Qué hace | Notas |
|---|---|---|
| `configure [--data-dir PATH] [--port N] [--lan/--no-lan] [--allow-host NAME]... [--frontend-dist PATH]` | Crea o actualiza `~/.config/autopublisher/config.toml` (0600) **solo con flags** (sin asistente interactivo). Imprime la configuración resultante. | Nunca toca datos. Avisa si `--port` ≠ 8000 (redirect URIs de YouTube/TikTok). |
| `set-password` | Pide la contraseña dos veces (`getpass`), valida longitud, aplica migraciones si hace falta (solo con A libre), guarda el hash y **borra todas las sesiones** en la misma transacción. Sirve para el primer setup y para el reset, también sobre una BD anterior a 020. | Solo local; toma el lock M; no requiere detener el servicio; con un servidor en marcha y el esquema por detrás de head → "Restart AutoPublisher first." (exit 75). |
| `serve` | Arranca en modo instalación: lee config (exit 78 si falta/inválida), comprueba `dist`, contraseña configurada, `TMPDIR`, logging, uvicorn (`host` según LAN, `port`, `proxy_headers=False`, `access_log=False`, `server_header=False`, `timeout_graceful_shutdown=20`). | Usado por la unidad systemd. Lock conflict → exit 75. |
| `install-service [--no-enable]` | Escribe `~/.config/systemd/user/autopublisher.service` con `ExecStart=<backend abs>/.venv/bin/python -m app.cli serve` y `WorkingDirectory=<backend abs>` (resueltos desde el código, no desde el cwd), `Environment=AUTOPUBLISHER_CONFIG=<abs>` solo si el TOML no es el de por defecto; `systemctl --user daemon-reload` y `enable` (no `start`). Imprime los comandos de gestión. | Rechaza si no hay config, contraseña o `.venv/bin/python`; **rechaza** si hay `AUTOPUBLISHER_DATA_DIR` u overrides `AUTOPUBLISHER_*` de rutas en el entorno ("These environment overrides are not persistent for the service … Move them to the host configuration before installing the service."); nunca copia variables de la shell. No habilita lingering. Si el checkout se mueve: `uv sync` + `install-service` otra vez. |
| `uninstall-service` | `disable --now` + borra la unidad + `daemon-reload`. | No toca datos ni config. |
| `status` | Imprime: banner de instalación efectiva (fichero de config, directorio de datos y BD efectivos, overrides de entorno detectados), puerto y LAN, si un servidor parece tener A/B (observación momentánea, `LOCK_NB`, nunca espera), resultado de `GET http://127.0.0.1:<port>/health`, sondeo del keyring, direcciones LAN candidatas, ubicación de los logs, avisos de permisos (FR-044). | Solo lectura, sin sesión. |
| `backup [--output DIR]` | Imprime primero el banner de instalación efectiva. Backup online (research §20–21): snapshot SQLite **sin sesiones** (la tabla se vacía solo si existe; vale para BDs anteriores a 020) + Media referenciada verificada + JSON de plataforma; `.partial` → verificación → `rename`. Default `~/autopublisher-backups`. Imprime la ruta del `.tar` y el resumen. | Toma el lock M. Rechaza `DIR` dentro del directorio de datos. |
| `restore ARCHIVE [--yes]` | Imprime primero el banner de instalación efectiva. Restore validado (research §22; ruta canónica, nunca sobre un punto de montaje): todo se valida antes de tocar datos; staging en el mismo FS; swap; cero sesiones; la config del host no cambia. | Toma M → A → B durante toda la operación; con el servicio en marcha → exit 75. |

## Precedencia de configuración (C3)

Para cada ruta: (1) variable `AUTOPUBLISHER_*` individual específica (`AUTOPUBLISHER_DB_PATH`, `AUTOPUBLISHER_MEDIA_DIR`, `AUTOPUBLISHER_*_APP_FILE`, `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`, `AUTOPUBLISHER_MEDIA_DELIVERY_FILE`); (2) `AUTOPUBLISHER_DATA_DIR` + nombre por defecto; (3) `data_dir` del TOML del host (solo `serve` y comandos de instalación); (4) default (`backend/data` en desarrollo, `$XDG_DATA_HOME/autopublisher` en instalación). `port`, `lan_enabled`, `allowed_hosts`, `frontend_dist` solo vienen del TOML. Ubicación del TOML: `AUTOPUBLISHER_CONFIG` o `$XDG_CONFIG_HOME/autopublisher/config.toml`.

## Locks

`<home de passwd>/.local/state/autopublisher/locks/` (home de `pwd.getpwuid(os.geteuid())`, raíz única; nunca derivada de variables de entorno ni configurable): M (mantenimiento), A (directorio de datos), B (BD efectiva), orden M → A → B (research §9). Servidor: A+B; `backup`: M; `set-password`: M; `restore`: M+A+B.

Gestión del servicio (documentada, no envuelta):

```bash
systemctl --user start|stop|restart|status autopublisher
journalctl --user -u autopublisher -e
```
