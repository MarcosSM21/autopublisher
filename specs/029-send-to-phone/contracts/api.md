# API Contract: Send to Phone

## `POST /api/contents/{content_id}/send-to-phone`

Sin cuerpo. Requiere sesión en modo instalación y pasa los guards Host/Origin como cualquier
otra ruta `/api` (no es pública). Síncrona: responde cuando `tailscale file cp` termina o
expira (máx. 300 s).

### Éxito

`204 No Content`

### Errores

Cuerpo estándar `{"error": {"code": "...", "message": "..."}}`. Ningún `message` contiene
rutas, target ni salida de `tailscale`.

| HTTP | code | message (orientativo) |
|------|------|-----------------------|
| 404 | `not_found` | existente |
| 503 | `phone_target_not_configured` | "Sending to your phone is not set up. Set TAILSCALE_PHONE_TARGET and restart AutoPublisher." |
| 503 | `tailscale_unavailable` | "Tailscale is not available on this computer." |
| 409 | `media_unavailable` / `media_corrupt` | mensajes existentes de `resolve_publish_file` |
| 409 | `metadata_removal_in_progress` / `content_deleting` | mensajes existentes del guard |
| 502 | `phone_send_failed` | "Could not send the file to your phone. Check that it is online in Tailscale and try again." |
| 504 | `phone_send_timeout` | "Sending to your phone took too long and was stopped. Try again." |

### Proceso ejecutado

```text
argv = [<which tailscale>, "file", "cp", "--name", <original_filename>, <publish file>, "<TAILSCALE_PHONE_TARGET>:"]
```

Sin shell, `stdin` cerrado, salida capturada y descartada, timeout 300 s.

## Frontend: `sendToPhone(contentId): Promise<void>` (`api.ts`)

Media Detail: `Send to phone` → `Sending…` (botón en carga, deshabilitado) → `Sent to phone`
en éxito; en error, `message` del API con `role="alert"` y el botón disponible de nuevo.
