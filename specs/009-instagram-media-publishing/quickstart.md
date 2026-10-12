# Quickstart: validar la publicación de imágenes y Reels en Instagram

**Feature**: `009-instagram-media-publishing` | **Fecha**: 2026-10-08

Guía de validación. Contratos en [contracts/api.md](contracts/api.md); modelo en
[data-model.md](data-model.md); decisiones en [research.md](research.md).

> **Aviso**: en Instagram no existen publicaciones privadas. **Toda prueba real publica de
> verdad** en la cuenta conectada. Usa solo contenido inocuo preparado para la validación
> (nunca contenido real existente) y borra los posts de prueba manualmente desde la app de
> Instagram al terminar: esta feature no implementa el borrado remoto.

## 1. Checks automáticos (sin Internet, sin Meta real, sin keyring real, sin proveedor cloud)

```bash
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy .

cd ../frontend
npm run lint && npm run format:check
npm run typecheck
npm test
npm run build
```

Resultado esperado: todo en verde. Los tests de Instagram usan `FakeMeta` (ampliado con
containers, `media_publish`, cuota y permalink), un `FakeMediaDeliveryProvider` en memoria,
`InMemoryCredentialStore`, `ffprobe` simulado y esperas instantáneas. Las pruebas de
arquitectura confirman que `publishing.py`, `publications.py`, `scheduler.py` y
`automation.py` no importan `app.instagram_*`, `app.media_delivery_s3` ni `boto3`.

## 2. Validación real

### Requisitos previos

- Feature 008 validada: la `Account` Instagram está `Connected` con la cuenta Professional
  propia (tester/rol de la Meta App).
- `ffprobe` instalado (`ffprobe -version`).
- Una cuenta de Cloudflare con R2 habilitado (u otro almacenamiento S3-compatible).
- Contenido de prueba preparado expresamente (no usar archivos reales del usuario):
  - `ig-test-square.png`: PNG 1080×1080 opaco (texto "AutoPublisher test");
  - `ig-test-reel.mp4`: vídeo de 5–10 s, 1080×1920, H.264 + AAC, 30 fps, `moov` al principio
    (p. ej. `ffmpeg -f lavfi -i testsrc=size=1080x1920:rate=30 -f lavfi -i sine -t 6
    -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart ig-test-reel.mp4`).

### Paso 1 — Configurar el media delivery (R2)

1. Crear un bucket R2 **privado** (sin acceso público ni dominio `r2.dev`), p. ej.
   `autopublisher-temp`.
2. **Obligatorio** — regla de lifecycle sobre el prefijo exclusivo de AutoPublisher
   (red de seguridad contra objetos privados huérfanos; no sustituye la limpieza inmediata
   ni controla la caducidad de las URLs firmadas):
   - Cloudflare → R2 → bucket → *Settings* → *Object lifecycle rules* → *Add rule*;
   - nombre `autopublisher-temporary-media`; prefijo **exactamente** `autopublisher-tmp/`
     (el mismo valor que `key_prefix`); acción *Delete objects* tras **1 day**; si se ofrece,
     abortar subidas multiparte incompletas tras 1 día;
   - comprobar que la regla aparece *Enabled* y que **no** se aplica a todo el bucket.
   Tiempo máximo documentado de vida de un objeto huérfano: ~48 h (1 día + hasta ~24 h de
   retraso de R2). JSON equivalente para la API S3 en [research.md §17](research.md).
3. Crear un API token R2 con permiso **Object Read & Write** limitado a ese bucket. Anotar
   Access Key ID, Secret Access Key y el endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
4. Crear `backend/data/media-delivery.json` según [research.md §17](research.md) (o apuntar
   `AUTOPUBLISHER_MEDIA_DELIVERY_FILE` a otro archivo). Comprobar con `git status` que **no**
   aparece.
5. Arrancar backend y frontend. En una publicación Instagram, el panel de opciones debe dejar
   de mostrar `media_delivery_not_configured`.

**Detener si**: falta la configuración y aun así el panel no muestra el error, el archivo
aparece en `git status` o la regla de lifecycle no está activa sobre el prefijo exclusivo.

### Paso 2 — Imagen: preflight sin efectos

1. Importar `ig-test-square.png` en un proyecto de prueba y crear una publicación para la
   `Account` Instagram con una descripción y dos hashtags.
2. Abrir el detalle: comprobar `Image Post`, el caption exacto (descripción, línea en blanco,
   `#a #b`), `alt_text` disponible y `share_to_feed` ausente.
3. Sin declarar AI-generated, abrir `Publish now`: el problema
   `instagram_options_incomplete` impide continuar. Comprobar en R2 que el bucket sigue vacío.
4. Declarar `AI-generated: No` y escribir un alt text.

### Paso 3 — Imagen: publicación real (`Publish now`)

1. `Publish now` → confirmar, **cronometrando** desde la confirmación hasta que la
   publicación aparece `Published`. Observar las fases: *Preparing* → *Uploading N %* →
   *Processing on Instagram* → *Publishing on Instagram* → `Published`. Durante la ejecución
   el porcentaje nunca llega a 100 % (la API expone como máximo `0.99` mientras el intento
   está en curso).
   **Métrica de validación** (no es un timeout funcional): objetivo < 1 minuto en
   condiciones normales; anotar el tiempo real.
2. **Durante** la ejecución (si da tiempo), listar el bucket: existe un único objeto bajo
   `autopublisher-tmp/<aleatorio>/<aleatorio>.jpg`, sin nombre ni ruta local.
3. Al terminar: `Open on Instagram` abre el permalink del post real; la imagen se ve igual
   que el PNG original (sin recortes) y muestra el caption exacto.
4. El bucket vuelve a estar vacío (cleanup).
5. **Validaciones obligatorias** (detener si fallan y revisar research §1/§15):
   - Meta aceptó la URL prefirmada (si el container falla con `instagram_media_fetch_failed`,
     Meta no acepta la URL firmada para `GET`: aplicar el plan de contingencia de research
     §17, alternativa B, antes de seguir);
   - el `<IG_ID>` usado (`instagram_user_id` de `/me`) funcionó para `/media` y
     `/media_publish`;
   - la respuesta de `content_publishing_limit` tenía la forma documentada (si no,
     `quota_checked: false` en `submitted`): anotar el `quota_total` real;
   - anotar qué campos devuelve `GET /<CONTAINER_ID>?fields=id,status,status_code` tras
     publicar (debe ser `PUBLISHED`); si Meta documentara un campo oficial que relacione el
     container con el media ID, registrarlo para una futura revisión (no se usa sin
     documentación oficial).
6. Comprobar el archivo original: `sha256sum` idéntico al calculado antes.

### Paso 4 — Reel: publicación real (`Publish now`)

1. Importar `ig-test-reel.mp4`, crear la publicación Instagram, declarar
   `AI-generated: Yes` y dejar `Share to feed` activado (default).
2. Comprobar `Reel` y la compatibilidad sin problemas en el panel.
3. `Publish now`: observar *Uploading N %* (bytes reales) y *Processing on Instagram* sin
   porcentaje; nunca 100 % antes de `Published`.
4. `Open on Instagram`: el Reel existe, aparece en el feed y en la pestaña Reels, y muestra la
   etiqueta de IA de Instagram (verificación de `is_ai_generated`).
5. El bucket queda vacío.

### Paso 5 — Rechazos en preflight (sin efectos)

1. Importar una imagen 1000×300 (aspect 3.33) → `instagram_image_incompatible` indicando la
   relación de aspecto; el bucket sigue vacío.
2. Importar un PNG con transparencia → incompatible (transparencia).
3. Importar un WebM → `instagram_video_incompatible` (contenedor).
4. Caption con 31 hashtags → `instagram_caption_invalid`; nada se sube.

### Paso 6 — Scheduler (publica de verdad)

1. Preparar un segundo PNG inocuo; crear la publicación Instagram, declarar AI-generated y
   programarla **3 minutos** en el futuro con publicación automática armada.
2. Esperar: el scheduler genérico la ejecuta una sola vez (`Started automatically` en el
   historial). Comprobar en Instagram que existe **un único** post.
3. Repetir con la automatización **pausada**: la publicación vencida no se ejecuta; `Publish
   now` sí funciona.

### Paso 7 — Persistencia, logs y secretos

1. Reiniciar backend: las publicaciones siguen `Published` con enlace; nada se re-ejecuta.
2. Buscar en SQLite (`backend/data/autopublisher.db`) y en los logs del backend:
   - el token de Instagram (desde el keyring, sin imprimirlo: buscar sus primeros 12
     caracteres con `grep -c`) → 0 apariciones;
   - `X-Amz-Signature`, `X-Amz-Credential`, `r2.cloudflarestorage.com` con query string,
     la Secret Access Key → 0 apariciones;
   - `temporary_media_objects` tiene filas con `deleted_at` informado y solo claves aleatorias.
3. En las DevTools del navegador: ninguna respuesta de `/api` contiene URLs del bucket ni
   tokens; `localStorage`/`sessionStorage` vacíos.

### Paso 8 — Limpieza tras caída (opcional, sin publicar)

1. Con un Reel de prueba, iniciar `Publish now` y detener el backend (`Ctrl+C` dos veces o
   `kill -9`) durante *Uploading*.
2. Rearrancar: el intento aparece `failed` (`interrupted`, resultado determinado); en menos de
   un minuto el barrido elimina el objeto del bucket. En Instagram no aparece nada.
3. Red de seguridad del lifecycle (opcional, sin publicar): subir a mano un archivo inocuo
   bajo `autopublisher-tmp/manual-check/` y otro fuera del prefijo; comprobar a las ~48 h que
   R2 ha borrado el primero y conservado el segundo.

> Los resultados ambiguos de `media_publish` no se provocan en la validación real (forzarlos
> podría publicar duplicados); se cubren con tests automatizados, incluida la reconciliación.
> Si apareciera uno: al abrir de nuevo la publicación, AutoPublisher lee el container
> original y, si Instagram confirma `PUBLISHED`, la cierra como `Published` con el aviso
> `remote_identity_unavailable` sin pedir nada (su `published_at` es aproximado: la hora en
> que AutoPublisher iba a publicar). Con cualquier otro estado, incluidos `ERROR` o
> `EXPIRED`, no se asume que no se publicó: sigue
> `instagram_publish_uncertain` y pide revisar Instagram antes de cualquier reintento: buscar
> el post a mano en el perfil usando la cuenta, la hora y el caption del mensaje.
> AutoPublisher nunca lo identifica automáticamente ni vuelve a publicarlo.

### Paso 9 — Cierre

- Borrar manualmente desde la app de Instagram todos los posts de prueba.
- Si Meta exigiera App Review/Advanced Access para publicar con la cuenta tester, documentarlo
  en `docs/instagram-publishing.md` y detener la validación (no eludirlo).
- Registrar en el PR: forma real de `content_publishing_limit`, aceptación de URLs
  prefirmadas, tiempos de procesamiento observados y el tiempo de `Publish now` → `Published`
  de la imagen (objetivo < 1 min; métrica, no requisito funcional).

## 3. Resultado de la validación real (T065, 2026-10-12)

Validado con una cuenta Instagram Professional (Creator) propia como tester de la Meta App,
Standard Access y un bucket R2 privado con la regla de lifecycle obligatoria. Contenido de
prueba creado para la validación y borrado después a mano. Sin identificadores reales.

| Comprobación | Resultado |
|---|---|
| Regla de lifecycle de R2 sobre el prefijo exclusivo | PASS (confirmada en el panel) |
| R2 local: subida, GET sin firma rechazado, GET firmado sin credenciales, `Range` 206, caducidad de la firma, borrado idempotente | PASS (`HEAD` con firma de `GET` → 403, sin efecto en Meta) |
| Meta acepta la URL prefirmada de R2 | PASS |
| `instagram_user_id` de `/me` válido para `/media` y `/media_publish` | PASS |
| Imagen real (PNG convertido a JPEG, alt text, AI = No) con `Publish now` | PASS |
| Reel real (H.264/AAC, AI = Sí, `share_to_feed = true`) con `Publish now` | PASS: aparece en feed y en Reels, con etiqueta de IA |
| Publicación programada con el scheduler genérico (pausa y reanudación) | PASS: nada se inicia en pausa; una ejecución con `trigger = scheduled` |
| Un único container y un único `media_publish` por publicación | PASS |
| Limpieza de R2 después de `PUBLISHED` (0 objetos al final) | PASS |
| Persistencia tras reiniciar backend y frontend (sin repeticiones) | PASS |
| Secretos en SQLite, logs y API (tokens, claves R2, URLs firmadas, `X-Amz-*`) | PASS (0) |
| Original local idéntico byte a byte | PASS |

Observaciones (no son garantías):

- `content_publishing_limit` devolvió
  `{"data":[{"quota_usage":int,"config":{"quota_total":int,"quota_duration":int}}]}` con
  `quota_total = 100` y `quota_duration = 86400` (100 publicaciones / 24 h).
- `quota_usage` se actualizó con retraso (tras dos publicaciones seguía en 1): no es un
  contador transaccional inmediato. AutoPublisher solo lo usa para bloquear cuando Meta
  indica cuota agotada.
- Tiempos observados (`Publish now` → `Published`): imagen ~10 s; Reel ~45 s, de los que
  ~38 s fueron procesamiento del container en Meta.
- Durante la validación se encontró y corrigió un bug: el primer guardado de las opciones
  de un Reel pasaba `share_to_feed` dos veces (error 500). Test de regresión en
  `backend/tests/test_instagram_options.py`.
