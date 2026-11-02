# Data Model: Send to Phone

Sin cambios de modelo ni migraciones.

- Se leen campos existentes de `Content`: `original_filename` y lo que use
  `resolve_publish_file` (`metadata_status`, rutas, checksum, tamaño).
- Configuración: `TAILSCALE_PHONE_TARGET` (variable de entorno, leída en cada envío; vacía =
  no configurada).
- Estado en memoria: el registro temporal del media en `ContentFileGuard` mientras dura el
  envío (existente; se libera siempre al terminar).
- No hay estado persistente, historial ni transiciones de estado.
