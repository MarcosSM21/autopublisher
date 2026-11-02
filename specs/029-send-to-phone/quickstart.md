# Quickstart: Send to Phone

## Checkpoint A — Backend

```bash
cd backend
uv run pytest tests/test_send_to_phone.py -q
```

Esperado: verde. Cubre éxito (original y copia limpia), argv exacto, los cinco errores,
conflictos con el guard y ausencia de stderr/rutas en logs y respuestas.
Ver [contracts/api.md](contracts/api.md).

## Checkpoint B — UI + validación real

```bash
cd frontend
npx vitest run src/pages/library/send-to-phone.test.tsx
```

Validación real en una instancia de prueba (no la instalación real; copia con
`AUTOPUBLISHER_CONFIG` propio y keyring de prueba):

1. Prerrequisitos: `tailscale status` muestra el móvil online; `tailscale file cp` funciona
   sin `sudo` (operador configurado).
2. Arrancar backend y frontend con `TAILSCALE_PHONE_TARGET=galaxy-a7-2018` en el entorno.
3. Abrir un media en Media Detail → `Send to phone`.
   - Esperado: `Sending…`, luego `Sent to phone`; el archivo aparece en Descargas del móvil
     con su nombre original.
4. Repetir con un media con copia limpia → llega la copia (sin metadata).
5. Sin la variable → mensaje "not set up"; con el móvil sin conexión a Tailscale → error o
   timeout comprensible y botón disponible.

Servicio instalado (documentado en `docs/deployment.md`):

```bash
systemctl --user edit autopublisher.service
# [Service]
# Environment=TAILSCALE_PHONE_TARGET=galaxy-a7-2018
systemctl --user restart autopublisher.service
```
