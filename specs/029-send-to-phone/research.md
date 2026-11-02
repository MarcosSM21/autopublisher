# Research: Send to Phone

## 1. Proteger el archivo durante la transferencia

- **Decision**: envolver `resolve_publish_file → tailscale file cp → fin` en
  `ContentFileGuard.sanitizing(content.id, check=<no-op>)`, el guard existente de 016/021/028
  (`app.state.content_file_guard`).
- **Rationale**: es el único mecanismo que ya excluye, para un mismo media, las dos
  operaciones que borran o sustituyen su publish file:
  - `Clean metadata` (`sanitizing`) → rechazada con `metadata_removal_in_progress`;
  - borrado (`deleting`) → rechazado con su mensaje de bloqueo; su preview (`is_sanitizing`)
    también lo muestra bloqueado.
  Si el media ya se está limpiando o borrando, el envío se rechaza con 409
  (`metadata_removal_in_progress` / `content_deleting`) antes de leer nada. El guard es en
  memoria y se libera en `finally`, también ante timeout o excepción.
  Efecto colateral aceptado: un *claim* de publicación de ese media durante el envío recibe
  `content_metadata_busy`; el scheduler lo trata como "no reclamado" y reintenta en el
  siguiente tick (`NOT_CLAIMED_CODES`); una publicación manual muestra el 409 y se puede
  reintentar. Publicar y enviar a la vez solo leerían el archivo, pero esto se acepta para
  no crear un lock nuevo.
- **Alternatives considered**: un set `sending` nuevo en el guard con mensajes propios
  (lock nuevo, rechazado por la spec); sin protección (Taildrop podría leer un archivo que
  desaparece).

## 2. Ejecución de Taildrop

- **Decision**: `subprocess.run([tailscale, "file", "cp", "--name", name, str(path),
  f"{target}:"], stdin=DEVNULL, capture_output=True, timeout=300, check=False)` con
  `tailscale = shutil.which("tailscale")`. Mismo patrón que ffmpeg en `video_metadata.py`.
- **Rationale**: sin shell; la salida se captura para que no se mezcle con el log del
  servicio y se descarta. `check=False` + exit code explícito.
- **Alternatives considered**: `asyncio` subprocess (innecesario: la ruta es `def` y corre
  en el threadpool); API local de tailscaled (más acoplamiento, sin ventaja).

## 3. Timeout

- **Decision**: 300 s fijos (`SEND_TIMEOUT_SECONDS`).
- **Rationale**: los archivos pueden llegar a 2 GB; en LAN/Tailscale directo eso cabe en
  pocos minutos, y un móvil inalcanzable no debe dejar la petición abierta indefinidamente.
  `subprocess.run` mata el proceso al expirar.
- **Alternatives considered**: hacerlo configurable (innecesario para el MVP).

## 4. Nombre del archivo

- **Decision**: `--name <content.original_filename>`.
- **Rationale**: en disco los archivos son `<uuid>.<ext>` y las copias limpias
  `<uuid>.clean.<ext>`; el móvil recibiría ese nombre. `original_filename` ya está validado
  en la importación (≤ 255 caracteres) y la copia limpia conserva la extensión del original.
  Taildrop sanitiza el nombre en el receptor y añade sufijo si ya existe.
- **Alternatives considered**: renombrar/copiar a un archivo temporal (I/O extra innecesario);
  usar el título del media (puede no tener extensión ni ser único).

## 5. Configuración

- **Decision**: `os.environ.get("TAILSCALE_PHONE_TARGET", "").strip()` en cada petición.
  Para el servicio systemd instalado se documenta `systemctl --user edit autopublisher` con
  `Environment=TAILSCALE_PHONE_TARGET=...`.
- **Rationale**: la spec fija una variable de entorno; leerla en cada envío evita estado.
- **Alternatives considered**: clave en `config.toml` (amplía `DeploymentSettings`; no
  pedido).

## 6. Errores y logs

| Caso | HTTP | code | Log (solo datos seguros) |
|------|------|------|--------------------------|
| Target vacío | 503 | `phone_target_not_configured` | — |
| `tailscale` no encontrado / `OSError` al lanzar | 503 | `tailscale_unavailable` | clase de excepción |
| Publish file ausente / dañado | 409 | `media_unavailable` / `media_corrupt` | — (mensajes existentes) |
| Limpieza o borrado en curso | 409 | `metadata_removal_in_progress` / `content_deleting` | — |
| Exit code ≠ 0 | 502 | `phone_send_failed` | exit code |
| Timeout | 504 | `phone_send_timeout` | "timed out" + segundos |

Nunca se registran stdout/stderr, rutas, nombre de archivo ni target en los mensajes de
error al usuario. Los códigos nuevos son errores `AppError`; no se añaden a ninguna lista de
conflictos.
