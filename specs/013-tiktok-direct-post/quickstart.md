# Quickstart: validación real de TikTok Direct Post (VIDEO, FILE_UPLOAD)

**Feature**: `013-tiktok-direct-post` | **Fecha**: 2026-10-14

Dos checkpoints reales, en orden. Todo post de prueba es **privado (`SELF_ONLY`)** y se borra a
mano en la app de TikTok al terminar. Ningún secreto (tokens, `upload_url`, client secret) se
pega en el chat, issues, commits ni logs compartidos.

| Checkpoint | Cuándo | Qué |
|---|---|---|
| **V1** — publisher mínimo real | tras el **Bloque 1** de plan.md (foundation, opciones, Creator Info, caption/vídeo, publisher mínimo, un chunk, `Publish now`) y **antes** del Bloque 2 | contrato real de Creator Info, init, `PUT`, estado y `PUBLISH_COMPLETE` |
| **V2** — validación final | al terminar el Bloque 2 | scheduler, pausa, reinicio/reconcile, multi-chunk, disclosure, AIGC, seguridad |

Anotar cada paso como **PASS** / **STOP** (fecha y nota sin datos sensibles) en "Resultados".

## Requisitos previos

- Feature 012 operativa: la `Account` TikTok está `Connected` (Verify OK) con `video.publish`.
- Cuenta TikTok de prueba = target user del Sandbox, **configurada como privada** en la app de
  TikTok (*Settings → Privacy → Private account*).
- `ffprobe` instalado (`ffprobe -version`).
- Vídeos inocuos generados para la prueba (sin música con derechos, sin personas):

```bash
mkdir -p /tmp/tt-v && cd /tmp/tt-v
# V1: ~5 s, 1080x1920, 30 fps, H.264, < 5 MB  → un único chunk
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=30 -t 5 -pix_fmt yuv420p -c:v libx264 v1-small.mp4
# V2 multi-chunk: ~70 MB (> 64 000 000 B) → 2 chunks
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=30 -t 60 -pix_fmt yuv420p -c:v libx264 -b:v 9M v2-multi.mp4
ls -l /tmp/tt-v
```

- Arrancar backend y frontend como en el README; importar los vídeos en un proyecto de prueba y
  crear una publicación por vídeo para la cuenta TikTok.

---

## V1 — Publisher mínimo real (STOP si algo contradice el diseño)

Usar `v1-small.mp4`. Pasos en la UI (panel TikTok de la publicación) salvo indicación.

1. **Cuenta privada**: el panel no muestra el aviso "account appears to be public"
   (`account_appears_public = false`). Anotar las `privacy_level_options` reales.
2. **Creator Info real**: nickname y avatar correctos; anotar tipos reales de los flags y
   `max_video_post_duration_sec`.
3. **`SELF_ONLY`** presente y seleccionable; las demás opciones deshabilitadas con motivo.
4. **Duración máxima**: anotar el valor; el vídeo (5 s) aparece como dentro del límite.
5. **Interacciones**: anotar `comment_disabled`, `duet_disabled`, `stitch_disabled` reales;
   comprobar que los deshabilitados aparecen en gris y desmarcados.
6. Elegir `SELF_ONLY`, dejar interacciones desmarcadas (o marcar comentarios si está habilitado),
   disclosure OFF, `AI-generated: No`; aceptar la declaración. `publish-check` → elegible.
7. `Publish now`: el diálogo muestra la declaración TikTok vigente con su checkbox obligatorio
   aunque ya se aceptara en el panel; marcarlo y confirmar. **Init `FILE_UPLOAD`**: en la base local,
   `tiktok_publish_runs` tiene `publish_id` antes de que `confirmed_bytes` > 0
   (`sqlite3 backend/data/autopublisher.db "select phase, publish_id is not null, confirmed_bytes, video_size, chunk_size, total_chunk_count from tiktok_publish_runs order by attempt_id desc limit 1;"`).
8. **Forma del request**: `publication_attempts.submitted` muestra `post_info` con
   `privacy_level = SELF_ONLY`, `disable_*` invertidos correctamente, `brand_*_toggle =
   false/false`, `is_aigc = false`, `source_info` con `chunk_size = video_size`,
   `total_chunk_count = 1`. TikTok aceptó el init (sin `invalid_param`).
9. **`publish_id`**: existe, ≤ 64 caracteres; no aparece en la UI ni en `GET /attempts`.
10. **Forma del `upload_url`** sin registrar valores. Procedimiento preferido, **sin tocar el
    repositorio**: arrancar el backend con el depurador de VS Code, poner un breakpoint al inicio
    de `TikTokGateway.upload_chunk` y evaluar en la *Debug Console* exactamente:

    ```python
    (lambda p: (p.scheme, p.hostname, sorted(__import__("urllib.parse").parse.parse_qs(p.query).keys())))(__import__("urllib.parse").parse.urlsplit(upload_url.reveal()))
    ```

    Esa expresión devuelve solo esquema, host y **nombres** de parámetros; nunca valores, path,
    query ni el token. Anotar el resultado (p. ej. `('https', 'open-upload.tiktokapis.com',
    ['upload_id', 'upload_token'])`) y continuar. No copiar `upload_url` ni evaluar otras
    expresiones sobre él. Si no se puede usar el depurador, añadir temporalmente **solo** esa
    misma expresión en un `logger.info` local, ejecutar, y después: retirarla, `git diff`
    (debe quedar vacío), `git status` sin cambios y comprobar con el paso 19 que ningún log
    contiene valores. Confirmar que la redacción de logs cubre ese host/forma.
11. **Subida de un chunk real**: un único `PUT`.
12. **Respuesta real del `PUT`**: anotar código (`201` esperado) y si trae `Content-Range`.
13. **Polling**: anotar número de lecturas y tiempos (logs a nivel INFO del publisher).
14. **Estados observados**: secuencia real (`PROCESSING_UPLOAD` → `PUBLISH_COMPLETE`).
15. **`PUBLISH_COMPLETE`**: la publicación queda `PUBLISHED`, intento `succeeded`.
16. **`uploaded_bytes`**: valor real comparado con `video_size` (¿igual?, ¿±1?) → fija la
    semántica "1-indexed" (research §12).
17. **`publicaly_available_post_id`**: ausente/vacío esperado con `SELF_ONLY`; si viene, anotar la
    forma. `external_id`/`external_url` según research §16; ningún enlace "Open on TikTok".
18. **Post privado** visible en la app de TikTok de la cuenta (perfil → solo yo).
19. **Seguridad**: `grep -ri "upload_token\|upload_id=\|access_token\|Bearer " backend/data/*.log`
    (o la salida de la consola) sin resultados; `sqlite3 … .dump | grep -i "upload"` sin URLs;
    DevTools → Application → Storage sin datos TikTok.
20. **Cero duplicados**: en la app de TikTok hay exactamente un post nuevo; la base tiene un
    `publish_id` para el intento.

### STOP en V1 (no construir el Bloque 2; revisar spec/plan)

- La cuenta/cliente no permite Direct Post privado; `SELF_ONLY` no se puede seleccionar.
- Creator Info real contradice el DTO (campos ausentes o tipos distintos).
- `init` exige `PULL_FROM_URL`, dominio verificado, `video.upload`, `video.list` o App Audit.
- `FILE_UPLOAD` contradice las reglas de chunks; el `PUT` responde algo distinto de `206/201`
  documentado; el `upload_url` tiene una forma que la redacción no cubre de forma fiable.
- `PUBLISH_COMPLETE` no significa "publicado" (p. ej. no hay post en la cuenta).
- Aparece cualquier secreto en base de datos, logs, API o navegador.
- Más de un post creado.

Tras V1 PASS: ajustar en research.md los valores confirmados (semántica de `uploaded_bytes`,
tiempos de polling, host de subida) antes de seguir con `/speckit-implement`.

---

## V2 — Validación final

1. **Multi-chunk**: publicar `v2-multi.mp4` (> 64 000 000 B): run con `total_chunk_count = 2`,
   `chunk_size = 33554432`; respuesta intermedia `206`, final `201`; `PUBLISH_COMPLETE`.
2. **Programada**: programar una publicación TikTok a +3 min; completar opciones, aceptar la
   declaración y activar auto-publish → se ejecuta una sola vez con origen `scheduled`
   (Creator Info reconsultado: comprobar en logs una consulta en el preflight).
3. **Invalidación de consentimiento**: en otra publicación armada, editar la descripción → el
   panel muestra consentimiento `stale` y la publicación sigue armada; a la hora no se ejecuta,
   queda el error automático `tiktok_consent_required` y **no** hay intento ni `publish_id` nuevo
   (`tiktok_publish_runs` sin fila nueva; ningún post en TikTok). Reconfirmar la declaración
   dentro de la ventana automática (sin reprogramar) → el siguiente reintento automático
   elegible (como máximo tras `AUTO_PUBLISH_RETRY_INTERVAL`, hoy 120 s) la publica una vez.
4. **Pausa/reanudación**: pausar la automatización antes de la hora → no se ejecuta; reanudar
   dentro de la ventana → se ejecuta una vez.
5. **Reinicio y reconcile**: parar el backend (Ctrl+C) **durante el polling** de una publicación
   pequeña (tras `201`) → al arrancar el intento queda ambiguo (`interrupted`, revisión);
   abrir el detalle → la reconciliación lee el `publish_id` original y la publicación pasa a
   `PUBLISHED` (o queda ambigua si TikTok sigue procesando; repetir la apertura más tarde). No
   provocar ambigüedad de otra forma.
6. **Interrupción antes del write-ahead** (opcional, solo con `v2-multi.mp4`): parar el backend
   durante el primer chunk → `FAILED` determinado; en TikTok no aparece post.
7. **Disclosure**: `Your brand` con `SELF_ONLY` → etiqueta "Promotional content" mostrada y
   publicación aceptada por TikTok (si TikTok la rechaza: anotar y STOP para revisar FR-019);
   `Branded content` aparece bloqueado con el motivo.
8. **AIGC**: publicar con `AI-generated: Yes` → TikTok acepta `is_aigc = true`; anotar si la
   etiqueta oficial es visible en el post privado.
9. **Seguridad**: repetir el paso 19 de V1 tras todas las pruebas.
10. **Conexión TikTok**: `Verify` sigue en `Connected`; YouTube/Instagram/Threads sin cambios
    (smoke manual de un publish-check en cada uno).
11. **Limpieza**: borrar a mano en la app de TikTok todos los posts de prueba. No existe borrado
    remoto en AutoPublisher.

No provocar deliberadamente resultados ambiguos (salvo el reinicio controlado del paso 5) ni
duplicados en la cuenta real.

## Comandos de comprobación automática

```bash
cd backend && uv run pytest tests/test_tiktok_*.py -q      # dirigido durante el desarrollo
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd frontend && npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

## Resultados

### V1 — 2026-10-14: **PASS**

Ejecutado con el backend de esta rama (migración `0012` aplicada, copia previa de la base en
el scratchpad de la sesión), la cuenta TikTok de prueba (target user privado), vídeo inocuo
`v1-small.mp4` (4 266 526 B, H.264 1080×1920, 30 fps, 5 s), publicación 12. Pasos 6–7 por la API
con exactamente las mismas llamadas que la UI (`PUT tiktok-options`, `POST tiktok-consent`, y en
`Publish now` de nuevo `POST tiktok-consent` con la huella mostrada + `POST publish`).

| Paso | Resultado | Nota (sin datos sensibles) |
|---|---|---|
| 1 Cuenta privada | PASS (tras corregirla) | 1.ª lectura: `PUBLIC_TO_EVERYONE` presente → cuenta pública; el usuario la puso privada; 2.ª lectura `account_appears_public = false`. Confirma la correspondencia de research §4. |
| 2 Creator Info real | PASS | `creator_nickname`/`creator_username` str, avatar presente, flags `bool`, `max_video_post_duration_sec` int. DTO sin contradicciones. |
| 3 `SELF_ONLY` | PASS | Opciones reales (privada): `FOLLOWER_OF_CREATOR`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`. |
| 4 Duración máxima | PASS | `max_video_post_duration_sec = 3600` (> 600 documentado; el límite técnico local de 600 s se mantiene). Vídeo de 5 s dentro. |
| 5 Interacciones | PASS | Privada: `comment_disabled=false`, `duet_disabled=true`, `stitch_disabled=true` (pública: los tres `false`). |
| 6 Opciones + consentimiento | PASS | `SELF_ONLY`, interacciones desmarcadas, disclosure OFF, AIGC No; consentimiento `valid`; `publish-check` elegible. |
| 7 Init `FILE_UPLOAD` | PASS | `publish_id` committed antes del `PUT` (run en `uploading`); un único `init`. |
| 8 Forma del request | PASS | `post_info` con `disable_*` = true, toggles `false/false` explícitos, `is_aigc=false`, `title` = caption; `source_info` con `chunk_size = video_size`, `total_chunk_count = 1`. Sin `invalid_param`. |
| 9 `publish_id` | PASS | 35 caracteres; ausente de la UI y de todas las respuestas de la API. |
| 10 Forma del `upload_url` | PASS | `('https', 'open-upload-i18n.tiktokapis.com', ['upload_id', 'upload_token'])`, obtenido con un lanzador fuera del repositorio (equivalente al breakpoint); repositorio sin cambios. Redacción cubre el host. |
| 11 Un chunk | PASS | Un único `PUT`. |
| 12 Respuesta del `PUT` | PASS | `201 Created` (presencia de `Content-Range` no registrada). |
| 13 Polling | PASS | 2 lecturas: 1.ª a 3 s del `PUT`, 2.ª a 6 s; ≈ 9 s desde el write-ahead. |
| 14 Estados | PASS | `PROCESSING_UPLOAD` → `PUBLISH_COMPLETE`. |
| 15 Resultado | PASS | Publicación `published`, intento `succeeded`, origen `manual`. |
| 16 `uploaded_bytes` | Sin dato | No vino en la respuesta `PUBLISH_COMPLETE`; semántica sin confirmar (no se usa para decidir). |
| 17 Post ID | PASS | `publicaly_available_post_id` ausente/vacío; `external_id`/`external_url` NULL; aviso `tiktok_private_post_no_link`. |
| 18 Post privado visible | PASS | Confirmado por el usuario en la app de TikTok. |
| 19 Seguridad | PASS (parcial) | Logs del backend y `.dump` de SQLite sin `upload_id=`/`upload_token=`/tokens/`Bearer`; respuestas de la API sin `publish_id` ni URL. DevTools del navegador no revisado en esta ejecución (el flujo se hizo por la API). |
| 20 Cero duplicados | PASS | El usuario ve exactamente un post nuevo; la base tiene un `publish_id` para el intento. |

Observaciones: el backend no configura logging, así que los INFO del publisher solo se ven con
un logging configurado (aquí, el lanzador de V1). Borrar a mano el post de prueba en TikTok al
terminar las validaciones.

## Precondiciones (T001, 2026-10-14)

Verificadas sin cambiar código y sin registrar secretos:

| Precondición | Resultado | Nota |
|---|---|---|
| Feature 012 integrada en `main` | PASS | `main` = merge de PR #12 (`6daf385`); la rama `013-tiktok-direct-post` parte de ahí. |
| `Account` TikTok `Connected` y `Verify` correcto | PASS | Cuenta `tiktok-sandbox` (id 5) `connected`; `POST …/tiktok-connection/verify` → `connected`, identidad coincidente. |
| Scopes incluyen `video.publish` | PASS | `granted = [user.info.basic, video.publish]` (fuente `token_exchange`). |
| Config Sandbox de la Feature 012 | PASS | `backend/data/tiktok-app.json` presente, ignorado por git, sin cambios desde antes de la conexión (solo `client_key`/`client_secret`). |
| Cuenta TikTok destino privada | PENDIENTE (usuario) | No verificable desde AutoPublisher sin Creator Info; se confirma en el paso 1 de V1 (`account_appears_public = false`). |
| `ffprobe -version` | PASS | ffprobe 6.1.1. |

### V2 — 2026-10-14: **STOP** (Content-Range), detenida tras el paso 1

Ejecutado tras T048–T073 en verde (backend 3129 tests, frontend 354, lint/formato/tipos/build).
Vídeo `v2-multi.mp4` (67 686 392 B), publicación 13, cuenta TikTok de prueba privada, `Verify`
`connected`. Observación con un lanzador fuera del repositorio que solo registra códigos HTTP, el
fin de `Content-Range` y la presencia de `uploaded_bytes`.

| Paso | Resultado | Nota |
|---|---|---|
| 1 Multi-chunk | PASS funcional | `total_chunk_count = 2`, `chunk_size = 33554432`; `206` intermedio, `201` final, `PROCESSING_UPLOAD` → `PUBLISH_COMPLETE` (≈ 11 s); `published`, sin post ID; un único post privado confirmado por el usuario. |
| — `Content-Range` | **STOP** | `206` del chunk `0–33554431` → fin **33554432**; `201` → fin **67686392** (= total). TikTok expresa el progreso como recuento de bytes (último byte + 1), no como índice inclusivo. La política de `416` (research §12) compara con el último byte base 0, así que con la semántica real nunca aceptaría un chunk reintentado (fallo determinado: seguro, sin reenvío ni duplicado, pero sin la recuperación prevista). El `FakeTikTok` modela lo contrario. |
| — `uploaded_bytes` | Observado | Presente en `PROCESSING_UPLOAD` (= 67686392, el total) y ausente en `PUBLISH_COMPLETE`. Sigue sin usarse para decidir. |
| Seguridad (paso 1) | PASS | Logs: `PUT [redacted TikTok upload URL]`, sin `upload_id=`/`upload_token=`/tokens; `.dump` de SQLite y respuestas de la API sin URL ni `publish_id`. |
| 2–11 | No ejecutados | Detenido por decisión del usuario antes de crear más posts reales; revisar spec/plan (research §12) antes de continuar. |

Conexión TikTok al terminar: `connected` (`user.info.basic`, `video.publish`). Backend relanzado
con el comando normal. Posts de prueba pendientes de borrar a mano: V1 (publicación 12) y V2-1
(publicación 13).

#### Corrección tras el STOP (2026-10-14)

Evidencia real de V2 paso 1, ya incorporada a research §12, spec (FR-039 y requisitos de
subida), plan, tasks (T011/T048), `FakeTikTok` y tests:

- Multi-chunk real funcionó: `206` → `201` → `PROCESSING_UPLOAD` → `PUBLISH_COMPLETE`;
  exactamente un post privado.
- `Content-Range` de la **petición**: `bytes first-last/total` (`last` inclusivo). De la
  **respuesta**: `bytes 0-accepted_bytes/total`, recuento de bytes aceptados (fin exclusivo):
  `bytes 0-33554431/…` → `bytes 0-33554432/…`; `bytes 33554432-67686391/…` →
  `bytes 0-67686392/…`.
- `uploaded_bytes` apareció durante `PROCESSING_UPLOAD` (= total) y no en `PUBLISH_COMPLETE`;
  solo diagnóstico.
- `416` (solo chunks intermedios): avanzar únicamente si `accepted_bytes == last + 1` y `total`
  coincide; cualquier otro caso → fallo determinado antes del write-ahead. Último chunk sin
  reintento y anti-duplicados sin cambios.

V2 se reanudó desde el paso 2 (el paso 1 no se repitió: la ruta de éxito `206`/`201` no
cambió).

### V2 (reanudación, pasos 2–11) — 2026-10-14: **PASS**

Backend con la corrección de `Content-Range` cargada. Observación con el mismo lanzador fuera
del repositorio, que ahora también registra cada consulta de Creator Info y los valores no
sensibles del `init` (privacidad, toggles, `is_aigc`, número de chunks). Vídeos inocuos de 5 s;
cuenta TikTok de prueba privada.

| Paso | Resultado | Nota |
|---|---|---|
| 2 Programada (pub 14) | PASS | Armada a +3 min; a su hora, una consulta de Creator Info en el preflight, un `init`, un `PUT` `201` y `PROCESSING_UPLOAD` → `PUBLISH_COMPLETE`; un intento `trigger = scheduled`; un post. |
| 3 Consentimiento `stale` (pub 15) | PASS | Armada; cambiar la descripción → `stale`, sigue armada. A su hora: `tiktok_consent_required`, cero intentos, cero runs y **cero peticiones a TikTok**. Reconfirmar sin reprogramar → el siguiente reintento automático (120 s después del bloqueo) la publicó una vez. |
| 4 Pausa/reanudación (pub 16) | PASS | Pausada antes de la hora; pasada la hora no se ejecutó ni hubo peticiones. Al reanudar dentro de la ventana: una ejecución `scheduled`, un post; nada más en los 70 s siguientes. |
| 5 Reinicio y reconcile (pub 17) | PASS | SIGINT (Ctrl+C) justo después del `201`: la parada ordenada durante el polling dejó el intento **ambiguo** (`tiktok_result_uncertain`, no determinado; diseño cubierto por `test_shutdown_during_polling_is_uncertain`). El arranque no hizo ninguna petición a TikTok. Al abrir el detalle (`publish-check`) se hizo una lectura de estado del `publish_id` original (`PUBLISH_COMPLETE`) y pasó a `published`, sin `init` ni `PUT`. |
| 6 Interrupción antes del write-ahead (pub 18) | PASS | Vídeo de 80 846 232 B (2 chunks). SIGINT durante el primer chunk: `206` (`accepted_bytes = 33554432 = last + 1`), luego `interrupted` determinado, sin write-ahead; el último chunk no se envió. Ningún post en TikTok. |
| 7 Your brand (pub 19) | PASS | Etiqueta "Promotional content" mostrada; Branded content con `SELF_ONLY` → `422 tiktok_branded_content_private`. TikTok aceptó `brand_organic_toggle = true`, `brand_content_toggle = false` con `SELF_ONLY`; `PUBLISH_COMPLETE`. La etiqueta es visible en el post. |
| 8 AIGC (pub 20) | PASS | TikTok aceptó `is_aigc = true`; el caption enviado es exactamente la descripción + hashtags (sin texto añadido); privado. La etiqueta "AI-generated" es visible en el post. |
| 9 Seguridad | PASS | Volcado de SQLite, logs del lanzador y de todas las ejecuciones del backend y 54 respuestas de la API: cero tokens, client secret, `upload_url`/`upload_token`/`upload_id` y cero `publish_id` fuera de la base local. Navegador (Chrome headless + DevTools Protocol sobre el frontend de desarrollo: proyecto, cuentas, contenido, cola, detalle de 5 publicaciones TikTok, **Refresh** de Creator Info y diálogo **Publish now** abierto y cancelado): 147 peticiones y 74 cuerpos de la API sin secretos, sin `publish_id`, sin `Authorization` y sin host de subida; `localStorage`, `sessionStorage`, cookies, IndexedDB y Cache Storage vacíos. El diálogo mostró la declaración con su checkbox. Única coincidencia de patrón: el parámetro `refresh_token=` de la URL firmada del avatar en el CDN de TikTok (`*.tiktokcdn-eu.com`, Feature 012), que no es el token OAuth. Cambios del repositorio: sin secretos ni `publish_id` reales (solo valores ficticios de los tests); `backend/data/` y `.env` ignorados. |
| 10 Conexión y regresión | PASS | `Verify` → `connected` con `user.info.basic` y `video.publish`. `publish-check` de YouTube, Instagram y Threads → 200. |
| 11 Limpieza | PASS | El usuario confirmó visualmente **8 posts privados** (V1, V2 multi-chunk y los 6 de esta reanudación), sin duplicados y ninguno de la interrupción. El usuario los borró todos a mano en TikTok. |

Observaciones: el `Content-Range` de cada `201` de un solo chunk también fue
`bytes 0-{total}/{total}`; `uploaded_bytes` = total en cada `PROCESSING_UPLOAD` y ausente en
cada `PUBLISH_COMPLETE`. La publicación 21 (solo para el diálogo, nunca publicada) quedó
cancelada. Al terminar: lanzador parado, backend con el comando normal, TikTok `connected`.

Quality gates finales (tras la corrección de `Content-Range`): backend 3158 tests, ruff check,
ruff format --check y mypy (179 archivos) en verde; frontend 354 tests, lint, format:check,
typecheck y build en verde.
