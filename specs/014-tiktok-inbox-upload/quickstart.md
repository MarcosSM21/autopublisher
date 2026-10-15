# Quickstart: validación real de TikTok Upload to Inbox

**Feature**: `014-tiktok-inbox-upload` | **Fecha**: 2026-10-15

Checkpoints reales en orden. La cuenta TikTok de prueba se mantiene **pública** salvo en el paso
de regresión de Direct Post (V2-9). Ningún secreto (tokens, `upload_url`, client secret) se pega
en el chat, issues, commits ni logs compartidos. Anotar cada paso como **PASS** / **STOP**
(fecha y nota sin datos sensibles) en "Resultados".

| Checkpoint | Cuándo | Qué |
|---|---|---|
| **V1a** — scopes | tras el paso 1 del Bloque 1 (plan.md) | Reconnect con tres scopes; Direct Post intacto |
| **V1b** — envío real al inbox | al terminar el Bloque 1, **antes** del Bloque 2 | `inbox/video/init` + `FILE_UPLOAD` + `SEND_TO_USER_INBOX` + notificación + editor |
| **V2** — validación final | al terminar el Bloque 2 | scheduler, Check status → `PUBLISH_COMPLETE`, reinicio, multi-chunk, Direct Post, seguridad |

## Requisitos previos

- Features 012 y 013 operativas; la `Account` TikTok `Connected`.
- La app del Sandbox de TikTok for Developers tiene **Content Posting API** con `video.upload`
  disponible (ya confirmado por el usuario) y el usuario de prueba es target user del Sandbox.
- Cuenta TikTok de prueba **pública** (*Settings → Privacy → Private account: OFF*) y la app de
  TikTok instalada en el móvil con esa cuenta.
- `ffprobe`/`ffmpeg` instalados. Vídeos inocuos (sin música con derechos, sin personas):

```bash
mkdir -p /tmp/tt-inbox && cd /tmp/tt-inbox
# V1b: ~5 s, 1080x1920, 30 fps, H.264, < 5 MB → un único chunk
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=30 -t 5 -pix_fmt yuv420p -c:v libx264 inbox-small.mp4
# V2 multi-chunk: ~70 MB (> 64 000 000 B) → 2 chunks
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=30 -t 60 -pix_fmt yuv420p -c:v libx264 -b:v 9M inbox-multi.mp4
```

- Backend y frontend arrancados como indica el README; vídeos importados en un proyecto de
  prueba.

Consulta auxiliar (sin secretos):

```bash
sqlite3 backend/data/autopublisher.db "select attempt_id, mode, phase, publish_id is not null, confirmed_bytes, video_size, last_remote_status, delivered_to_inbox_at, user_published_at from tiktok_publish_runs order by attempt_id desc limit 3;"
sqlite3 backend/data/autopublisher.db "select id, status, published_at from publications order by id desc limit 3;"
```

---

## V1a — Ampliación de scopes (STOP si algo falla)

1. Antes de reconectar: la conexión existente sigue `Connected`; el panel de conexión muestra
   `capabilities.inbox_upload = false` y la indicación de `Reconnect`; Direct Post sigue
   disponible en el selector de modo.
2. Pulsar `Reconnect`: la pantalla de TikTok pide los **tres** permisos (`user.info.basic`,
   `video.publish`, `video.upload`). Conceder todos.
3. La conexión queda `Connected`, misma identidad (`open_id`), `granted` con los tres y
   `capabilities = {direct_post: true, inbox_upload: true}`.
4. `Verify connection` → OK. (Opcional) forzar una renovación según el README de 012 y comprobar
   que los tres scopes se conservan.
5. Si TikTok no concede `video.upload` o el Reconnect falla: anotar STOP; comprobar que la
   conexión previa sigue intacta (`Connected`, dos scopes).

## V1b — Envío real al inbox con la cuenta pública (STOP si algo contradice el diseño)

Usar `inbox-small.mp4`.

1. Crear una publicación TikTok del vídeo; el panel muestra el selector de modo **sin
   selección**; `Publish now`/`Schedule` deshabilitados con "Choose how to send this video to
   TikTok".
2. Elegir **Upload to Inbox**: desaparecen privacidad, interacciones, disclosure, AIGC,
   caption y declaración; aparece el aviso de que la configuración final se hace en TikTok.
3. Pulsar **Send to TikTok** y confirmar el diálogo (sin declaración de Direct Post).
4. **Init**: TikTok acepta `inbox/video/init/` (sin `invalid_param`, sin errores de cuenta
   privada/audit). En SQLite, el run tiene `mode = INBOX_UPLOAD` y `publish_id` antes de que
   `confirmed_bytes` > 0. `publication_attempts.submitted` contiene `source_info` y **no**
   `post_info`.
5. **Subida**: un único chunk aceptado (`201`); la UI pasa por `Uploading` y `Processing in
   TikTok`.
6. **Estado**: se observa `SEND_TO_USER_INBOX`; anotar el tiempo aproximado. El run queda
   `phase = delivered` con `delivered_to_inbox_at`; la publicación `awaiting_user_action`; el
   intento `succeeded`; la UI muestra **Ready in TikTok** y "Open your TikTok inbox to review,
   edit and publish the video."; el polling se detiene (no hay más lecturas en el log).
7. **Móvil**: en la app de TikTok aparece la notificación en el inbox (anotar si además llega
   push del sistema; no es requisito).
8. Pulsar la notificación: TikTok abre el editor con el vídeo cargado.
9. Comprobar que puede editarse (p. ej. añadir texto o cambiar la portada). **No publicar** en
   V1b; salir guardando o dejando el borrador según ofrezca TikTok.
10. **Respuesta explícita**: "¿Upload to Inbox funciona realmente con nuestra cuenta pública y
    nuestro cliente Sandbox/no auditado?" → **Sí / No** con la evidencia.
11. Seguridad rápida: `grep` de los logs del backend y de la base SQLite sin coincidencias de
    `upload_url`, `access_token`, `Authorization` ni host de subida con query.

**Stop conditions V1b**: TikTok exige cuenta privada, audit o cualquier condición inesperada;
`invalid_param` sin explicación; no se alcanza `SEND_TO_USER_INBOX`; la notificación no aparece
o no abre el editor; cualquier secreto visible. → detener y revisar spec/plan.

---

## V2 — Validación final (tras el Bloque 2)

1. **Programado**: crear otra publicación con `inbox-small.mp4` (o un nuevo vídeo inocuo),
   modo Upload to Inbox, programar ~5 min en el futuro y armar. La UI muestra `Scheduled` y la
   nota de que la hora es de inicio del envío.
2. **Pausa/reanudación**: pausar la automatización antes de la hora; comprobar que no se
   ejecuta; reanudar dentro de la ventana; se ejecuta una sola vez con origen `scheduled`.
3. Se alcanza `SEND_TO_USER_INBOX` → Ready in TikTok; aparece la notificación.
4. **Reinicio**: reiniciar el backend; la publicación sigue `awaiting_user_action`; ningún
   nuevo `inbox/video/init` en el log; el scheduler no la toca.
5. **Check status** antes de publicar en TikTok → "still waiting"; estado sin cambios.
6. En el móvil: abrir la notificación, hacer una edición sencilla y **publicar** desde TikTok
   (con la privacidad que el usuario elija en TikTok; recomendado "Only me" para la prueba).
7. Volver a AutoPublisher → **Check status** → `published`; la publicación pasa a `PUBLISHED`;
   el intento de entrega sigue `succeeded` y el historial muestra "Delivered to TikTok inbox" y
   "Published in TikTok"; no aparece enlace ni ID de post.
8. **Multi-chunk** con `inbox-multi.mp4`: 2 chunks, progreso por bytes, `SEND_TO_USER_INBOX`.
   (Cuenta para el límite de 5 envíos pendientes/24 h: descartar o publicar los borradores en
   TikTok antes de seguir.)
9. **Direct Post sigue funcionando**: poner la cuenta TikTok en **privada** temporalmente,
   publicar con Direct Post (`SELF_ONLY`) un vídeo pequeño como en 013 V1 → `PUBLISHED`; volver
   a poner la cuenta **pública**.
10. **Seguridad**: base de datos, logs, respuestas de la API (`/attempts`, `/tiktok-delivery`,
    `/check-status`) y almacenamiento del navegador sin tokens, `upload_url` ni `publish_id`.
11. No provocar en la cuenta real `spam_risk_too_many_pending_share` ni resultados ambiguos (se
    cubren con fakes). Borrar a mano en TikTok los posts y borradores de prueba.

Después de V2, quality gates completos (una vez; comandos del README):

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd frontend && npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

## Resultados

| Paso | Fecha | PASS/STOP | Nota (sin datos sensibles) |
|---|---|---|---|
| V1a | 2026-10-15 | PASS | Reconnect real: TikTok concedió los tres scopes (`user.info.basic`, `video.publish`, `video.upload`); conexión `Connected`, misma cuenta; `capabilities = {direct_post: true, inbox_upload: true}`; `Verify connection` OK. Renovación forzada (opcional) no ejecutada. |
| V1b | 2026-10-15 | **PASS** | **¿Upload to Inbox funciona con nuestra cuenta pública y el cliente Sandbox/no auditado? Sí.** Pasos 1–2 PASS (modo sin selección → `tiktok_mode_required`; Inbox elegible sin privacidad/AIGC/caption/consentimiento). 3–4 PASS (init aceptado con la cuenta pública, sin `invalid_param` ni errores de cuenta privada/audit; `publish_id` antes del primer byte; `submitted` sin `post_info`). 5 PASS (un chunk, HTTP 201, vídeo 6 s 1080x1920 4,7 MB). 6 PASS (`SEND_TO_USER_INBOX` ~30 s tras el envío, tras 9 lecturas `PROCESSING_UPLOAD`; run `delivered`, intento `succeeded`, publicación `awaiting_user_action`; sin más lecturas). 7 PASS (notificación en el inbox de TikTok; la push del sistema depende de los permisos de la app en el móvil, ajeno a AutoPublisher). 8 PASS (abre el editor con el vídeo). 9 PASS (editable; guardado como borrador, sin publicar). 11 PASS (sin URL de subida, tokens ni `Authorization` en logs/SQLite; `publish_id` solo en su fila del run, nunca en la API). |
| V2 | 2026-10-15 | **PASS** (reducida) | Por acuerdo con el usuario solo se validó en real lo que no cubren los tests offline. **Programado** PASS: publicación armada en Inbox sin consentimiento; el scheduler la inició a su hora (origen `scheduled`), un único intento, `SEND_TO_USER_INBOX` ~8 min después. **Multi-chunk** PASS: 67,6 MB en 2 chunks (32 MiB + resto), progreso por bytes confirmados, `SEND_TO_USER_INBOX` ~9 min después (TikTok tardó bastante más que en V1b; dentro de la ventana de 10 min). **Check status** PASS: antes de publicar → `awaiting`, sin cambios ni intentos nuevos; tras publicar el usuario en TikTok ("Solo yo") → `PUBLISH_COMPLETE`, publicación `published`, intento de entrega intacto, sin `external_id` ni enlace. **Seguridad** PASS: sin URL de subida, tokens ni `Authorization` en logs/SQLite; `publish_id` nunca en la API. **No ejecutados en real** (cubiertos offline): pausa/reanudación, reinicio del backend, Direct Post con la cuenta en privado. Borradores y post de prueba: borrar a mano en TikTok. |
