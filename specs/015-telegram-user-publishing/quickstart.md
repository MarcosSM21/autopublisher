# Quickstart: validación de Telegram (V1a / V1b)

**Feature**: `015-telegram-user-publishing` | **Fecha**: 2026-10-15

Guía de validación real. Contratos en [contracts/api.md](contracts/api.md); modelo en
[data-model.md](data-model.md).

## Prerrequisitos

- Cuenta real de Telegram (con 2FA si se quiere validar ese paso).
- Un canal broadcast de prueba administrado por esa cuenta (público para validar el enlace;
  opcionalmente uno privado para comprobar que no se inventa URL).
- `api_id` / `api_hash` creados en <https://my.telegram.org> → *API development tools*.
- Almacén seguro del sistema disponible (Secret Service/KWallet/Keychain).
- Un proyecto con una `Account` de plataforma `telegram`.

## Configuración

```bash
cat > backend/data/telegram-app.json <<'EOF'
{"api_id": 12345678, "api_hash": "<api_hash>"}
EOF
git check-ignore backend/data/telegram-app.json   # debe imprimir la ruta
cd backend && uv sync && uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

## V1a — Cuenta (antes de construir la UI completa; se puede hacer con `curl`)

1. `POST /api/accounts/{id}/telegram-connection/login/start` con el teléfono → `login.step = "code"`.
2. Telegram envía el código (app de Telegram) → `POST .../login/code`.
3. Si responde `login.step = "password"` → `POST .../login/password`.
4. Esperado: `status = "connected"`, identidad correcta (user ID, nombre, username).
5. `POST .../verify` → `connected`, `last_verified_at` actualizado.
6. `GET .../channels` → aparece el canal de prueba; no aparecen grupos ni chats privados.
7. `PUT .../channel` con el `channel_id` de prueba → `channel` relleno.
8. Comprobaciones de seguridad:
   - `sqlite3 backend/data/autopublisher.db "select * from telegram_connections"`: solo
     metadata pública, `credential_ref` y `channel_access_hash`; ninguna sesión.
   - `find . -name '*.session*' -not -path './node_modules/*'` → vacío.
   - `grep -ri "<api_hash>\|<código>" backend/data/*.log` (si hay logs) → vacío.
   - En Telegram → *Ajustes → Dispositivos* aparece la sesión "AutoPublisher".

**STOP** si la sesión no se guarda en el almacén seguro o el canal no se identifica bien.

## V1b — Publicación (Publish now)

1. Texto: crear una publicación de texto inocua para la cuenta Telegram → *Publish now*.
2. Comprobar en la app de Telegram: aparece en el canal, sin bot, sin "via @bot", sin marca de
   AutoPublisher, igual que una publicación manual (autor = canal; firma solo si el canal
   tiene "Sign messages").
3. Imagen pequeña JPEG + caption → *Publish now* → foto con el caption exacto.
4. Vídeo MP4 pequeño + caption → *Publish now* → vídeo reproducible, con vista previa, caption
   exacto.
5. En AutoPublisher: cada intento `succeeded`, publicación `PUBLISHED`, message ID guardado;
   enlace `https://t.me/<canal>/<id>` solo si el canal es público y abre el mensaje.

Los tres tipos funcionan → **V1 PASS**. Borrar a mano los mensajes de prueba en Telegram.

## Validación posterior (tras UI y scheduler)

- Programar un texto a +2 min con auto-publish armado → `SCHEDULED → PUBLISHING → PUBLISHED`.
- Con una publicación `scheduled`, intentar cambiar el canal → bloqueado con explicación.
- Mientras se sube un vídeo de la cuenta, pulsar Verify → `409 telegram_busy`; al terminar,
  Verify funciona. Otra cuenta Telegram (si existe) no queda bloqueada.
- Disconnect → la sesión desaparece de *Dispositivos* en Telegram y del almacén seguro.

## Tests offline (desarrollo)

```bash
cd backend && uv run pytest tests/test_telegram_connections.py tests/test_telegram_publishing.py
cd frontend && npx vitest run src/components/TelegramConnectionPanel.test.tsx
```

Quality gates completos una sola vez al final (`ruff`, `ruff format --check`, `mypy`,
`pytest`, `npm run lint`, `npm run build`, `vitest`).

## Resultados

### V1a — Cuenta: **PASS** (2026-10-15)

Validado con la cuenta real del usuario y la API (`/docs`), sin UI de Telegram:

- `telegram-app.json` con `api_id`/`api_hash` propios; ignorado por Git (`data/`); `configured: true`.
- Login real: teléfono → código (sin 2FA en esta cuenta) → `connected`.
- Identidad correcta confirmada por el usuario (Telegram user ID, nombre y username).
- Verify real → `connected`, `last_verified_at` actualizado.
- Canales: aparece el canal de prueba (broadcast privado, sin username público); ningún
  grupo ni chat privado. Canal seleccionado con `PUT .../channel`.
- Sesión solo en el almacén seguro (Secret Service, servicio `autopublisher.telegram`);
  ausente de SQLite. `api_hash` ausente de SQLite y de las respuestas de la API. Ningún
  archivo `.session` en el proyecto. Respuestas de la API solo con metadata pública.
- Sesión "AutoPublisher" visible en Telegram → Ajustes → Dispositivos.
- Terminal del backend revisado por el usuario: sin teléfono completo ni código.
- Nota: el login no pidió 2FA, así que el paso de contraseña solo está cubierto por tests
  offline.

### V1b — Publicación: **PASS** (2026-10-15)

Validado con Publish Now por la API (sin UI de Telegram) en el canal de prueba privado:

| Tipo | Archivo | Intento | Publicación | Message ID |
|---|---|---|---|---|
| Texto | — | `succeeded` | `PUBLISHED` | 53 |
| Imagen + caption | JPEG 640×360, 15 KB | `succeeded` | `PUBLISHED` | 54 |
| Vídeo + caption | MP4 H.264/AAC 640×360, 4 s, 66 KB | `succeeded` | `PUBLISHED` | 55 |

Comprobado por el usuario en Telegram:

- Los tres mensajes aparecen en el canal, sin bot ni "via @bot" y sin marca de
  AutoPublisher; se ven como publicaciones manuales normales del canal.
- Captions exactos (incluidos emojis).
- El vídeo se reproduce como vídeo (no como archivo) y Telegram genera su propia vista
  previa sin miniatura enviada por AutoPublisher.

Comportamiento real observado:

- Canal privado sin username: se guarda el message ID y no se genera enlace (correcto).
- Cada intento guardó su `telegram_random_id` en `submitted` antes del envío; no hubo
  repeticiones ni resultados inciertos en estos envíos.
- Sesión y `api_hash` ausentes de SQLite y de las respuestas de la API tras publicar;
  ningún archivo `.session` en el workspace.
- Los mensajes de prueba se eliminan manualmente en Telegram.

**V1 PASS.**

### Validación posterior

_(pendiente: T035)_
