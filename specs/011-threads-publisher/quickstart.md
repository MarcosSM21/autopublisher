# Quickstart: validar la publicación de texto, imagen y vídeo en Threads

**Feature**: `011-threads-publisher` | **Fecha**: 2026-10-13

Guía de validación. Contratos en [contracts/api.md](contracts/api.md); modelo en
[data-model.md](data-model.md); decisiones en [research.md](research.md).

> **Aviso**: toda prueba real **publica de verdad** en la cuenta Threads conectada. Usa solo
> contenido inocuo creado para esta validación y borra los posts de prueba manualmente desde
> Threads al terminar: esta feature no implementa el borrado remoto. No provoques timeouts ni
> resultados ambiguos contra producción: esos casos están cubiertos con fakes.

## 1. Checks automáticos (sin Internet, sin Meta real, sin R2 real, sin keyring real)

Durante la implementación, tests dirigidos (por ejemplo
`uv run pytest tests/test_threads_publish_text.py`). En los hitos y al cerrar:

```bash
cd backend
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy .

cd ../frontend
npm run lint && npm run format:check
npm run typecheck
npm test
npm run build
```

Resultado esperado: todo en verde, incluidas las suites existentes de YouTube, Instagram y
conexión Threads, los tests de arquitectura (`publishing`, `publications`, `scheduler` y
`automation` sin código ni imports de Threads; Threads sin imports de Instagram) y el test de
la migración `0010`.

## 2. Validación real

### Requisitos previos

- Feature 010 validada: la `Account` Threads está `Connected` (tester de la Meta App propia) y
  `Verify connection` funciona.
- Media delivery (R2) configurado y validado en la Feature 009 (bucket privado, regla de
  lifecycle sobre `autopublisher-tmp/`, `backend/data/media-delivery.json` fuera de Git) y
  `url_ttl_seconds` ≥ 900.
- `ffprobe` instalado.
- Contenido de prueba creado para la validación:
  - `threads-test.png`: PNG 1080×1080 opaco con el texto "AutoPublisher test";
  - `threads-test.mp4`: 6 s, 1080×1920, H.264 + AAC 48 kHz estéreo, 30 fps, fast start
    (`ffmpeg -f lavfi -i testsrc=size=1080x1920:rate=30 -f lavfi -i sine=sample_rate=48000
    -t 6 -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 128k -ac 2 -movflags +faststart
    threads-test.mp4`).
- Para inspeccionar sin exponer secretos: `sqlite3 backend/data/autopublisher.db` y los logs
  del backend en nivel `DEBUG`.

Anotar en cada paso: estado devuelto por la **primera** lectura del container, estados
intermedios, tiempo total, post ID, permalink, `quota_usage` antes y después.

### Paso 1 — Codificación de los `POST`, cuota y preflight sin efectos

**Comprobación temprana (antes de cualquier publicación real)**: el gateway envía los
parámetros de creación de container y de `threads_publish` en el **cuerpo**
`application/x-www-form-urlencoded` (UTF-8), sin query string, mientras que la documentación
oficial muestra ejemplos con parámetros en la query (research §1). No se asume que Meta lo
acepte:

1. Con el backend parado, ejecutar desde un script temporal en el scratchpad (no versionado)
   que use `ThreadsGateway.create_container` con la credencial del keyring y un texto de
   prueba `AutoPublisher encoding check áé ✅`, `media_type = TEXT`. **No** llamar a
   `threads_publish`: el container sin publicar caduca solo en 24 h.
2. Comprobar: Meta devuelve un container ID (acepta `access_token`, `media_type` y `text` en
   el cuerpo) y `container_status` lo lee (`FINISHED` o `IN_PROGRESS`). Anotar el estado.
3. La aceptación del cuerpo de `threads_publish` (`creation_id`) se confirma en la primera
   publicación real (paso 2): un rechazo explícito es un fallo determinado y no publica nada.
   La aceptación de `image_url`/`video_url`/`alt_text` en el cuerpo se confirma en los pasos 3
   y 4.

**Detener si** Meta rechaza o ignora cualquier parámetro enviado en el cuerpo: revisar el
gateway (y la redacción de logs si hubiera que mover algo a la URL) antes de continuar.

Después, preflight sin efectos:

4. Crear una publicación de texto (**New text post**) para la cuenta Threads con un texto de
   > 500 caracteres. Abrir el detalle: `threads-options` muestra el texto exacto, su
   longitud y el problema `threads_text_invalid`; `Publish now` queda bloqueado. Ningún
   container creado (sin peticiones `POST …/threads` en el log).
5. Importar un WebP **animado** de prueba y crear una publicación Threads: el detalle muestra
   `threads_image_incompatible` y no se sube nada a R2.
6. Acortar el texto a un valor válido. Abrir `Publish now` (diálogo de confirmación, sin
   confirmar): el preflight lee la cuota. Registrar en el log/`submitted` posterior la
   **forma real** de `threads_publishing_limit` (`quota_usage`, `config.quota_total`,
   `config.quota_duration`).

**Detener si** la forma real de la cuota es incompatible con la forma entendida de research
§9 (en ese caso AutoPublisher falla el preflight con `threads_unexpected_response`: no se
publica nada). La forma real debe quedar confirmada y anotada antes del cierre.

### Paso 2 — Texto real

1. Texto: `AutoPublisher validation — text ✅ áéí https://example.com`, hashtag
   `autopublisher`. Comprobar en el detalle el texto final (`…\n\n#autopublisher`) y los
   avisos de vista previa de enlace y topic tag.
2. `Publish now` → confirmar. Fases: *Preparing* → *Processing on Threads* →
   *Publishing on Threads* → `Published`. Comprobar:
   - ningún objeto nuevo en R2 ni fila en `temporary_media_objects`;
   - `threads_publish_runs`: `media_kind = text`, `container_id` y `publish_started_at`
     rellenos, `phase = succeeded`; anotar el estado de la primera lectura del container
     (esperado `FINISHED`; si fue `IN_PROGRESS`, anotar cuánto tardó) y que `threads_publish`
     se llamó con el container `FINISHED` **y** al menos 30 s después de crearlo
     (`publish_started_at - container_created_at ≥ 30 s`, research §10);
   - `external_id` (post ID) y `external_url` (permalink `https://…threads…`);
     `Open on Threads` abre el post y el texto coincide carácter a carácter (acentos y emoji
     incluidos: confirma la codificación UTF-8 del cuerpo);
   - el cuerpo de `threads_publish` fue aceptado (comprobación temprana del paso 1);
   - `quota_usage` aumenta en 1 en una consulta posterior (siguiente preflight);
   - el container original figura `PUBLISHED` (comprobación manual de solo lectura con el
     `container_id`, sin publicar nada).

**Detener si** un container publicado no figura `PUBLISHED`, el estado del container de
texto contradice el modelo o Meta rechaza un texto que AutoPublisher considera válido.

### Paso 3 — Imagen real

1. Importar `threads-test.png`, crear una publicación Threads con texto corto y `alt_text`
   ("A white square with the words AutoPublisher test").
2. `Publish now`. Fases con *Uploading N %* real. Comprobar:
   - antes de subir, fila en `temporary_media_objects` (clave sin firma);
   - Threads **acepta la URL prefirmada de R2** (container `FINISHED`, post visible con el
     alt text);
   - tras `Published`: objeto borrado en R2 y `deleted_at` relleno; archivo original idéntico
     (`sha256sum` antes y después).
3. Repetir con un WebP **estático con transparencia** y comprobar `"→ sent as PNG"` en el
   resumen, que el post muestra la imagen sin recortes y que el WebP original no cambió.

**Detener si** Threads rechaza la URL prefirmada (`threads_media_fetch_failed` o rechazo al
crear el container).

### Paso 4 — Vídeo real

1. Importar `threads-test.mp4`, crear la publicación con texto y alt text.
2. Antes de publicar, anotar lo que `ffprobe` reporta (`ffprobe -v error -show_streams
   threads-test.mp4`), en particular el `bit_rate` del audio AAC codificado a 128 kbps, y
   comprobar que el preflight lo acepta (≤ 128 000 b/s). Si el valor reportado supera
   ligeramente 128 000, anotarlo: es el caso a revisar de research §8.
3. `Publish now`. Comprobar estados `IN_PROGRESS` → `FINISHED`, tiempo de procesamiento
   (debe quedar por debajo del timeout de 5 min), post publicado, cleanup en R2, original
   intacto y `submitted.delegated_checks` (al menos `closed_gop` y `edit_lists`).

### Paso 5 — Publicación programada

1. Crear una publicación de texto programada 3–5 minutos en el futuro con publicación
   automática armada.
2. Con la automatización activa, comprobar que se publica **una sola vez**, con origen
   `scheduled`.
3. Repetir con otra publicación y la automatización en **pausa**: no se publica a la hora;
   `Publish now` sigue disponible.

### Paso 6 — Reinicio y seguridad

1. Con una publicación armada para dentro de unos minutos, detener y arrancar el backend
   antes de la hora: se publica una sola vez tras el arranque, dentro de la ventana.
2. Buscar secretos (deben dar 0 resultados): el access token (copiado temporalmente del
   keyring solo para esta comprobación), `X-Amz-Signature`, `X-Amz-Credential` y la
   secret key de R2 en:
   - `sqlite3 backend/data/autopublisher.db .dump`;
   - los logs del backend;
   - las respuestas de `GET /api/publications/{id}`, `/attempts`, `/threads-options`;
   - el almacenamiento del navegador (DevTools → Application).

**Detener si** aparece cualquier secreto o si el publisher necesita permisos distintos de
`threads_basic` y `threads_content_publish`.

### Paso 7 — Limpieza

Borrar manualmente en Threads todos los posts de prueba y comprobar que el bucket no
conserva objetos de AutoPublisher.

## 3. Registro de resultados

Anotar en este archivo, al final de la validación: fecha, aceptación de la codificación
del cuerpo de los `POST`, forma real de la cuota, estados observados por tipo y tiempos,
aceptación de URLs prefirmadas, bitrate de audio reportado por `ffprobe`, permalinks,
resultado de las comprobaciones de secretos y cualquier desviación respecto a research.

### Validación real temprana del MVP TEXT — 2026-10-13 (parcial, detenida)

Alcance: solo paso 1 (codificación de los `POST`, cuota) y paso 2 (texto real). Sin imagen,
vídeo ni casos ambiguos. Cuenta Threads de la Feature 010 (`Connected`).

| Comprobación | Resultado |
|---|---|
| Creación de container `TEXT` con cuerpo `application/x-www-form-urlencoded`, sin query (sonda aislada con `ThreadsGateway.create_container`) | **PASS**: Meta devuelve un container ID; ningún parámetro ni texto en la URL. La sonda nunca se publicó (caduca sola). |
| Eco de `media_type`/`text` en el container (`GET /{container}?fields=…,media_type,text`) | No disponible: Meta responde 400 a esos campos sobre un container; el texto solo puede confirmarse en el post publicado. |
| Primer estado del container (sonda) | `IN_PROGRESS` a +0,2 s de crearlo; `FINISHED` en la siguiente lectura (≈ 1 min después; tiempo exacto no medido). |
| Primer estado del container (intento real) | `FINISHED` en la lectura inmediata (sin polling). |
| Forma real de la cuota | `{"data":[{"quota_usage":<int>,"config":{"quota_total":250,"quota_duration":86400}}]}`: coincide con research §9. Quota check: **PASS** (`quota_usage` 0/250). |
| Preflight de la publicación de texto (sin Content, sin media delivery, texto exacto, apta) | **PASS**. |
| `threads_publish` | **FALLO**: rechazo explícito (4xx) unos 300 ms después de crear el container; la lectura posterior del container dio `FINISHED` (no `PUBLISHED`) → `threads_publish_failed`, determinado, nada publicado. El container sigue `FINISHED` sin publicar. Causa no identificada: el gateway descarta (por diseño) el código de error de Meta. |
| Publicación TEXT real, permalink, texto exacto, reinicio | No ejecutados (detenido en la stop condition del cuerpo de `threads_publish`). |
| Secretos (SQLite `.dump`, log del backend en DEBUG, respuestas de la API, `git status`) | **PASS**: 0 tokens, 0 App Secret, 0 `Authorization`/`Bearer`, 0 `access_token=`, 0 `X-Amz-`. |

Hipótesis pendientes de revisar antes de continuar: (a) Threads no acepta `creation_id` en el
cuerpo de `threads_publish`; (b) Threads rechaza publicar un container recién creado aunque
lea `FINISHED` (la documentación recomienda esperar de media 30 s). Distinguirlas requiere
conocer el código/subcódigo de error de Meta.

#### Diagnóstico controlado de `threads_publish` — 2026-10-13

Una sola llamada a `threads_publish`, desde un script temporal, sobre el container de la sonda
inicial (nunca publicado, `FINISHED` confirmado por GET, ~10 min de antigüedad), con
`creation_id` y `access_token` en un cuerpo `application/x-www-form-urlencoded` sin query
(misma codificación que el gateway). El container de la publicación del intento fallido no se
tocó.

- Resultado: HTTP 200 con post ID; `GET /{post}` devolvió permalink y `timestamp`; el
  container pasó a `PUBLISHED`. **Cuerpo form-urlencoded en `threads_publish`: PASS.**
- Diagnóstico 2 (`creation_id` en query) no fue necesario.
- Conclusión: el rechazo del intento real es compatible con publicar demasiado pronto
  (~300 ms tras crear el container) aunque la lectura inmediata devolviera `FINISHED`.
  La regla de research §10 ("`FINISHED` → publicar sin ninguna espera") debe revisarse antes
  de continuar (p. ej. una antigüedad mínima del container antes de `threads_publish`, como
  recomienda la documentación de Meta: ~30 s de media).
- El post de diagnóstico se borra manualmente en Threads.

#### Corrección de diseño tras la validación temprana — 2026-10-13

`FINISHED` pasa a ser condición **necesaria pero no suficiente**: AutoPublisher solo ejecuta
el write-ahead y `threads_publish` cuando el container está `FINISHED` **y** tiene al menos
`MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS` = 30 s desde su `container_created_at` persistido
(research §10). Es una política conservadora del producto basada en la recomendación de Meta
(~30 s de media) y en esta validación, no un mínimo documentado de la API. Se espera solo el
tiempo que falta y se relee el estado antes de publicar; regla común a texto, imagen y vídeo.
La publicación del intento rechazado queda `failed` (puede cancelarse con el flujo normal) y su
container no se reutiliza. Pendiente: repetir la publicación TEXT real (paso 2) con la regla
corregida.

#### Repetición de la publicación TEXT real con la antigüedad mínima — 2026-10-13

Nueva publicación de texto creada con el flujo normal (la del intento rechazado se canceló
desde la API; sus containers y los de las sondas no se reutilizaron). Texto:
`AutoPublisher validation — text ✅ áéí https://example.com` + `#autopublisher`.

| Comprobación | Resultado |
|---|---|
| Preflight (sin Content, cuenta Threads e identidad verificadas, texto exacto, sin media delivery, apta) | **PASS** |
| Cuota | **PASS**: forma `{"data":[{"quota_usage":<int>,"config":{"quota_total":250,"quota_duration":86400}}]}`; `quota_usage` 1/250 (cuenta el post de diagnóstico de las últimas 24 h aunque se borró). |
| Container | Uno solo, `TEXT`; `container_created_at` persistido. |
| Primera lectura de estado | `FINISHED` a +0,15 s de la creación. |
| Espera | Solo la que faltaba hasta 30 s; segunda lectura `FINISHED` a +30,2 s. **Dos** lecturas de estado en total (las esperas de 1 s no generan peticiones). |
| Regla ≥ 30 s | **PASS**: `publish_started_at - container_created_at = 30,24 s`; sin otros 30 s añadidos. |
| `threads_publish` (cuerpo form-urlencoded) | **PASS**: una sola llamada, HTTP 200 (~3,3 s de respuesta), post ID devuelto. |
| Permalink | Devuelto (`https://www.threads.com/@…/post/…`), `timestamp` en `details`; `external_url` = permalink. |
| Publicación / intento | `published` / `succeeded`, origen `manual`, `progress` 1,0, sin avisos. Tiempo total ≈ 38,6 s. |
| Texto | AutoPublisher envió el texto exacto. Threads convirtió la primera etiqueta en topic tag: el post devuelve `text` = `…https://example.com\n\nautopublisher` y `topic_tag = autopublisher` (comportamiento de la plataforma previsto en research §4). |
| Media delivery | Ningún objeto ni fila de `temporary_media_objects` para este intento. |
| Reinicio | **PASS**: tras reiniciar y > 2 ciclos del scheduler, sigue `published` con su post ID y permalink; 1 intento, 1 run; ninguna petición a Meta. |
| Secretos (SQLite `.dump`, logs con peticiones HTTP, respuestas de la API, `git status`) | **PASS**: 0 tokens, 0 App Secret, 0 `Authorization`/`Bearer`, 0 `X-Amz-`; los `access_token` de las URLs de log aparecen como `[redacted]`. Navegador no usado. |
| Limpieza | Post de prueba a borrar manualmente en Threads. |

Pendiente para cerrar la validación real (T058): imagen, vídeo, scheduler real.

#### T058 — validación real de imagen, vídeo, scheduler y reinicio — 2026-10-13

Incluye como evidencia previa la validación TEXT anterior (codificación de los `POST`,
cuota, antigüedad mínima de 30 s, una sola llamada a `threads_publish`, post ID, permalink,
reinicio sin duplicados y seguridad). Medios generados solo para esta validación fuera de
Git: PNG 1080×1080 "AutoPublisher test" y MP4 6 s 1080×1920 H.264 + AAC (comando del paso 4).

| Comprobación | Resultado |
|---|---|
| Imagen (PNG, camino directo) | **PASS**. Preflight, cuota y media delivery correctos; fila temporal confirmada antes de subir; Threads **aceptó la URL prefirmada de R2**; container `IMAGE` creado (≈ 5 s de respuesta); `FINISHED` en la primera lectura (+0,3 s); dos lecturas de estado; edad al publicar 30,25 s; un `threads_publish`; post ID y permalink; `published`/`succeeded`. El post devuelve `media_type = IMAGE`, el texto enviado (con la primera etiqueta convertida en topic tag) y el `alt_text` exacto. |
| Cleanup imagen | **PASS**: objeto borrado tras persistir el éxito (`deleted_at` ≈ 0,2 s después del resultado); bucket sin objetos. |
| Vídeo — corte real del backend | El proceso del backend se detuvo durante el primer intento de vídeo, con el container `IN_PROGRESS` y **antes del write-ahead**. Al arrancar, la recuperación genérica cerró el intento como `interrupted` **determinado** y el sweep borró el objeto temporal. Ese container nunca recibió `threads_publish` (sigue `FINISHED` sin publicar y caduca solo). |
| Vídeo (reintento normal) | **PASS**. Antes de subir se leyó el container anterior (research §11). `ffprobe`: H.264 1080×1920, 30 fps, `yuv420p`, progresivo, 6 s, AAC 48 kHz estéreo con `bit_rate` **127 915** (≤ 128 000, aceptado); `delegated_checks = ["closed_gop", "edit_lists"]`. Threads **aceptó la URL prefirmada de R2**; container `VIDEO` `IN_PROGRESS` a +0,2 s, lecturas a +10,5 s y +30,8 s; edad al publicar 30,79 s; un `threads_publish` (≈ 24 s de respuesta de Meta); post ID y permalink; `media_type = VIDEO`, texto y `alt_text` exactos; archivo original idéntico (sha256). |
| Cleanup vídeo | **PASS**: objeto del reintento borrado tras el éxito; objeto del intento interrumpido borrado por el sweep del arranque; bucket sin objetos. |
| Scheduler (texto programado y armado) | **PASS**. Con la automatización **en pausa** pasó la hora y varios ciclos sin iniciarse (`auto_publish_state = paused`, 0 intentos); al **reanudar** el scheduler genérico la inició de inmediato con `trigger = scheduled`: un intento, un container (`IN_PROGRESS` a +0,2 s, releído a +2,5 s, publicado con 30,49 s de antigüedad), un `threads_publish`, `published`/`succeeded`. `scheduler.py`/`automation.py` sin código de Threads. |
| Reinicio | **PASS**: tras reiniciar y ≈ 100 s (varios ciclos), imagen, vídeo y texto programado siguen `published` con su permalink; ningún intento, container ni petición a Meta nuevos; ninguna media pendiente. |
| Cuota | **PASS**: misma forma `{"data":[{"quota_usage":<int>,"config":{"quota_total":250,"quota_duration":86400}}]}`; `quota_usage` subió en cada consulta posterior y cuenta también los posts de prueba borrados de las últimas 24 h. |
| Seguridad | **PASS**: 0 tokens, 0 App Secret, 0 credenciales del proveedor, 0 `Authorization`/`Bearer`, 0 `X-Amz-`/host de R2 y 0 `access_token` sin redactar en SQLite (`.dump`), logs y respuestas de la API; los IDs de objetos aparecen como `[id]` en los logs HTTP; `backend/data/` sigue ignorado; scripts y medios temporales solo en el scratchpad. La interfaz no se usó (almacenamiento del navegador cubierto por `storage-safety.test.tsx`). |

Observaciones: `threads_publish` de vídeo tardó ≈ 24 s en responder (dentro del timeout de
60 s); los containers de texto pueden leer `IN_PROGRESS` o `FINISHED` en la primera lectura,
y en ambos casos la publicación se hizo con ≥ 30 s de antigüedad.

Comprobación visual (usuario, 2026-10-13): **PASS**. Imagen: un único post, imagen completa.
Vídeo: un único post, se reproduce correctamente y con audio. Texto programado: un único
post, texto correcto. Los tres posts de prueba se borraron manualmente en Threads; los
containers sin publicar de las sondas y del intento interrumpido caducan solos.

**T058 completada**: validación real de texto, imagen, vídeo, scheduler, reinicio, cuota y
seguridad superada.
