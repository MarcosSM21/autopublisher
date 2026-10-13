# Research: Publicación real de texto, imagen y vídeo en Threads

**Feature**: `011-threads-publisher` | **Fecha**: 2026-10-13 | **Spec**: [spec.md](spec.md)

Fuentes oficiales consultadas el 2026-10-13 (Threads API de Meta):

- *Posts* — `developers.facebook.com/docs/threads/posts`
- *Publishing reference* — `developers.facebook.com/docs/threads/reference/publishing`
- *Overview* (límites, especificaciones de media) — `developers.facebook.com/docs/threads/overview`
- *Troubleshooting* (estado del container) — `developers.facebook.com/docs/threads/troubleshooting`
- *Threads Media* — `developers.facebook.com/docs/threads/threads-media`
- App de ejemplo oficial `fbsamples/threads_api` (`src/index.js`)
- Specs y research de las Features 009 (Instagram) y 010 (conexión Threads).

Lo que la documentación **no** garantiza (aceptación de URLs prefirmadas, estado real de un
container `TEXT`/`IMAGE` justo tras crearlo, forma real de la cuota, envío de parámetros en
el cuerpo del `POST`) se marca como **Validación real** y se comprueba en
[quickstart.md](quickstart.md) antes de dar la feature por buena.

---

## 1. Endpoints, host, versión y ruta del usuario

**Decision**:

| Paso | Método y URL (host y versión de `threads_gateway.py`) |
|---|---|
| Crear container | `POST https://graph.threads.net/v1.0/{threads_user_id}/threads` (cuerpo de formulario) |
| Estado del container | `GET …/v1.0/{container_id}?fields=id,status,error_message` |
| Publicar | `POST …/v1.0/{threads_user_id}/threads_publish` — `creation_id` (cuerpo de formulario) |
| Resultado publicado | `GET …/v1.0/{threads_media_id}?fields=id,permalink,timestamp` |
| Cuota | `GET …/v1.0/{threads_user_id}/threads_publishing_limit?fields=quota_usage,config` |

- Se reutilizan `THREADS_GRAPH_HOST` y `THREADS_API_VERSION` de `threads_gateway.py`
  (fuente única de la Feature 010, FR-007). Ninguna constante nueva de host o versión.
- **Ruta con el Threads user ID vinculado**, no `/me`: la referencia de publicación y la
  página *Posts* documentan `/{threads-user-id}/…`; la app de ejemplo usa `me/…`. Ambas
  funcionan con un token de usuario, pero usar el ID autoritativo de la conexión hace
  explícito en cada llamada en qué cuenta se publica, y el preflight ya ha comprobado que ese
  ID coincide con el del token (§6).
- **Codificación de los `POST`** (crear container y `threads_publish`): todos los parámetros
  (`access_token`, `media_type`, `text`, `image_url`/`video_url`, `alt_text`, `creation_id`)
  viajan en el **cuerpo**, codificado como `application/x-www-form-urlencoded` (UTF-8,
  `httpx` `data=`), sin ningún parámetro en la query string. La URL de la petición es solo
  `…/v1.0/{threads_user_id}/threads` o `…/threads_publish`. Motivo: la URL firmada del media,
  el texto y el token nunca deben aparecer en una URL de petición, que los logs del cliente
  HTTP registran (mismo patrón que `instagram_gateway.py`, ya validado contra la Graph API
  de Instagram). Los `GET` llevan `access_token` en la query, ya redactado por
  `RedactThreadsSecrets`.
- **No se asume compatibilidad**: la documentación oficial de Threads muestra los `POST` con
  parámetros en la query string. Que la Threads API acepte la misma codificación en el cuerpo
  **no** está documentado y se valida contra Meta real como **primera comprobación** del
  quickstart (paso 1). Si Meta la rechaza o ignora algún parámetro, se detiene la validación
  y se revisa el gateway antes de continuar (sin pasar los parámetros a la URL sin una
  revisión explícita de la redacción de logs).
- Timeouts: 10 s para lecturas (cliente existente) y 60 s para crear container y
  `threads_publish` (como Instagram).

**Rationale**: mismo host/versión que la conexión validada en la Feature 010; documentación
oficial para la ruta.

**Validación real**: quickstart paso 1 (codificación del cuerpo de los `POST`, comprobación
temprana con **stop condition**) y pasos 2–4 (todas las llamadas responden con el host
elegido).

**Alternatives considered**: `/me/threads` — documentado solo en la app de ejemplo; menos
explícito. Parámetros en la query string como en los ejemplos `curl` de Meta — rechazado
porque expondría la URL firmada en logs.

---

## 2. Representación de publicaciones sin `Content` (spec FR-003, FR-003a)

**Decision**: `publications.content_id` pasa a ser **anulable** (migración `0010`). La
ausencia de `Content` es neutral en el modelo común; cada publisher declara si la admite.

- **Capacidad neutral del publisher**: el protocolo `Publisher` gana el atributo
  `accepts_text_only: bool`. `YouTubePublisher` e `InstagramPublisher` declaran `False`;
  `ThreadsPublisher`, `True`. Plataformas sin publisher (TikTok, X, Telegram) no admiten
  publicaciones sin `Content`. Ningún módulo del núcleo nombra Threads.
- **Creación**: nuevo endpoint `POST /api/projects/{project_id}/text-publications`
  (`publications.py`) que crea una publicación sin `Content` por cuenta, todo o nada, con el
  texto y los hashtags. Solo acepta cuentas cuya plataforma tiene un publisher registrado con
  `accepts_text_only`; si no, `422 text_publication_not_supported`. El router consulta
  `request.app.state.publishers` sin importar `publishing.py` (evita una dependencia
  circular) y sin nombrar plataformas.
- **Origen del texto**: sin `Content`, la metadata efectiva es solo la de la publicación.
  El endpoint guarda el texto en `description_override` y los hashtags en
  `hashtags_override`; `title_override` queda `NULL` (no se usa). `effective_metadata()`
  acepta `content: Content | None` y devuelve `(override or None, override or None,
  override or [])`. La edición posterior usa el `PATCH` existente sin cambios.
- **Unicidad**: el índice parcial `uq_publications_active_content_account` no cambia. En
  SQLite los `NULL` son distintos en índices únicos, así que una cuenta puede tener varias
  publicaciones de texto activas (cada una es un post diferente). `find_active()` y la
  comprobación de duplicados de `reactivate` se omiten cuando no hay `Content`.
- **Preflight genérico**: `local_check()` añade, antes de llamar al publisher, el problema
  neutral `publication_media_required` si la publicación no tiene `Content` y su publisher no
  la admite (defensa en profundidad: el endpoint de creación ya lo impide). Así YouTube e
  Instagram nunca reciben una publicación sin `Content`.
- **Lectura**: `PublicationRead.content_id: int | None` y
  `PublicationRead.content: PublicationContentSummary | None`; la cola usa `outerjoin` con
  `Content`. `ensure_can_prepare()` solo comprueba el archivo si hay `Content`.
- **Revisión remota**: `requires_remote_check(session, content_id, account_id)` pasa a
  recibir la publicación: con `Content`, comportamiento actual (último intento del par
  content/cuenta); sin `Content`, último intento de **esa** publicación (comparar con `NULL`
  nunca coincidiría).
- **Ejecución**: `PreparedPublication.file_path` pasa a `Path | None`; un post de texto usa
  `total_bytes = 0` (el CHECK `bytes_sent <= total_bytes` se cumple y el progreso público ya
  devuelve `0.0` cuando `total_bytes` es 0).
- **Discriminador**: **no** se persiste. El tipo Threads se deriva siempre de
  `content_id`/`Content.media_type` (§3) y el tipo enviado queda registrado en
  `PublicationAttempt.submitted.media_kind` y en `threads_publish_runs.media_kind`.

**Rationale**: opción A aprobada; el atributo de capacidad mantiene la decisión en cada
publisher sin acoplar el núcleo a Threads (tests de arquitectura existentes:
`test_core_modules_have_no_threads_code`).

**Alternatives considered**: lista `TEXT_ONLY_PLATFORMS` en `models.py` — pondría conocimiento
de plataforma en el núcleo; columna discriminadora `kind` — redundante con `content_id`;
crear las publicaciones de texto desde `POST /contents/{id}/publications` — no hay
`Content`.

---

## 3. Tipo de publicación Threads

**Decision**: `ThreadsMediaKind` = `text` | `image` | `video`, derivado sin persistir:
`content_id is None` → `text`; `Content.media_type == image` → `image`; `video` → `video`.
Se envía como `media_type` = `TEXT` / `IMAGE` / `VIDEO`. `is_carousel_item` se omite (default
`false`).

---

## 4. Texto: composición, conteo y validación (spec FR-017–FR-020)

**Hallazgos**: *"Text posts are limited to 500 characters"*; *"For the post character limit,
emojis are counted as the number of UTF-8 bytes"* (con referencia a un *grapheme splitter*).
`text` es obligatorio para `TEXT`, opcional para `IMAGE`/`VIDEO`. *"The number of links is
restricted to 5 or less"*; desde el 2025-12-22 un exceso falla al crear el container
(`THREADS_API__LINK_LIMIT_EXCEEDED`); cada URL única del texto cuenta. *"The first URL in the
text field will be used as the link preview"* en posts de texto sin `link_attachment`. La
primera etiqueta `#…` válida del texto se convierte en topic tag (`#` seguido solo de dígitos
no cuenta).

**Decision**:

- **Composición** (FR-018): `description_with_hashtags(description, hashtags)` existente en
  `publications.py` (descripción efectiva, línea en blanco, `#a #b`). El título nunca se
  envía. Sin ninguna otra transformación (ni `strip`, ni normalización Unicode, ni cambios
  de saltos de línea). Texto vacío → el parámetro `text` se omite (solo posible en
  imagen/vídeo).
- **Conteo conservador** (`threads_text_length`): cada punto de código cuenta 1, salvo los
  que forman emojis, que cuentan su longitud UTF-8: puntos de código ≥ U+10000 (4 bytes),
  U+200D ZWJ, U+FE0F/U+FE0E selectores de variación, U+20E3 keycap y los de categoría
  Unicode `So` (3 bytes en el BMP). Sobrecontar símbolos como `©` es aceptable (nunca deja
  pasar un texto que Meta rechazaría por el conteo de emojis); el texto nunca se trunca.
- **Enlaces**: se cuentan las URLs **únicas** que empiezan por `http://`, `https://` o `www.`
  (hasta el siguiente espacio). Más de 5 → problema. Si Meta detecta además enlaces sin
  esquema, rechaza al crear el container (fallo determinado, `threads_text_invalid`).
- **Validación** sobre el texto final: longitud ≤ 500, enlaces ≤ 5 y, para `text`, texto no
  vacío. Código `threads_text_invalid` (campo `text`) con el límite y el valor real.
- La interfaz informa de que Threads puede usar la primera URL como vista previa y convertir
  la primera etiqueta en topic tag (comportamiento de la plataforma).

**Rationale**: reutiliza el mecanismo existente sin duplicarlo; el conteo prioriza no fallar
en Meta.

**Validación real**: quickstart paso 2 publica un texto con acentos, un emoji y una URL, y
comprueba que Meta acepta lo que AutoPublisher valida.

**Alternatives considered**: `len()` simple — infravalora emojis; longitud UTF-8 total —
rechazaría textos válidos con acentos; librería de grafemas — dependencia nueva sin necesidad
demostrada.

---

## 5. `alt_text` y opciones (spec FR-021–FR-024)

**Hallazgos**: `alt_text` opcional para imagen y vídeo, *"Max length: 1,000 characters"*. La
API no ofrece un parámetro de declaración de contenido generado por IA para Threads.
`reply_control` sin default documentado (Meta aplica su default si se omite).

**Decision**: tabla `threads_publication_options(publication_id, alt_text, updated_at)`;
`alt_text` se recorta (`strip`), vacío → `NULL` → no se envía; > 1000 caracteres → `422
threads_alt_text_invalid`; en publicaciones de texto → `422 threads_option_not_applicable`.
Ningún otro parámetro opcional se envía (FR-023): no hay ninguno imprescindible para publicar
texto, imagen o vídeo individual.

---

## 6. Preflight (spec FR-025–FR-027)

**Decision** — `ThreadsPublisher.check()` (sin red) y `prepare()` (lecturas permitidas):

`check()`: tipo soportado (§3); para imagen/vídeo, `Content` del tipo esperado y archivo
presente con el tamaño registrado; compatibilidad local del media (§7, §8); texto final
válido (§4); `alt_text` válido; media delivery configurado (solo imagen/vídeo); conexión
existente y `connected`. Resumen para el diálogo: tipo de post, cuenta Threads, texto,
alt text, archivo.

`prepare()` (orden): conexión existente → `verify_identity()` de la Feature 010 (credencial
válida con renovación, `debug_token` con los dos permisos y el ID vinculado, `/me`), que ya
marca `Reconnect required` ante señales definitivas → `get_valid_credentials()` → preparación
local del media (copia técnica en memoria si procede, §7) → cuota (§9) → lectura del último
container reciente de la publicación (§11, defensa anti-duplicados). Nada se sube ni se crea.

Errores de `prepare()` con código propio: `threads_not_connected`,
`threads_reconnect_required`, `threads_identity_mismatch`, `credential_store_unavailable`,
`threads_unavailable` (Feature 010), `threads_image_incompatible`,
`threads_publishing_limit_reached`, `threads_unexpected_response` (cuota con forma no
entendida, §9), `threads_already_published`.

**Rationale**: `verify_identity` es de solo lectura respecto a Threads y comprueba
exactamente "credencial utilizable, permisos e identidad" de FR-025 sin duplicar lógica.

---

## 7. Imágenes (spec FR-013, FR-014)

**Hallazgos**: JPEG y PNG oficiales; ≤ 8 MB; relación de aspecto ≤ 10:1; ancho 320–1440 (Meta
escala); sRGB (Meta convierte otros espacios). WebP no figura.

**Decision** (`threads_media.prepare_threads_image`, sin red, el original solo se lee):

| Formato del Content | Qué se envía |
|---|---|
| JPEG | El archivo original byte a byte (`image/jpeg`). |
| PNG | El archivo original byte a byte (`image/png`). |
| WebP **estático** | Copia técnica **PNG sin pérdida** (misma resolución, orientación EXIF aplicada, **transparencia conservada** si existe, perfil ICC conservado), `image/png`. |
| WebP **animado** (más de un frame) | Rechazo en preflight `threads_image_incompatible`. **Nunca** se elige silenciosamente un frame. |
| Imagen ilegible | Rechazo `threads_image_incompatible`. |

Reglas de validación — siempre sobre el **archivo que realmente se enviará** (el original en
JPEG/PNG; el **derivado** PNG en WebP):

- **Formato** enviado: JPEG o PNG (comprobado sobre los bytes del derivado, no sobre la
  extensión del original).
- **Tamaño** ≤ 8 MiB (8 × 1024 × 1024, interpretación prudente de "8 MB").
- **Relación de aspecto** (lado mayor / lado menor, con orientación EXIF) ≤ 10:1, medida
  sobre las dimensiones del derivado.
- El ancho fuera de 320–1440 **no** se rechaza (Meta escala).
- Nunca se recorta, rellena, redimensiona ni recomprime un JPEG/PNG.
- Si el PNG derivado supera 8 MiB o incumple cualquier límite → el preflight falla
  (`threads_image_incompatible`, explicando que AutoPublisher no redimensiona) **antes** de
  cualquier media delivery.

**Ciclo de vida del derivado**: la conversión se hace durante `prepare()` (preflight local
permitido), solo en memoria; el original solo se abre en lectura. Los bytes viajan en el
payload hasta la subida al proveedor temporal, que es el único lugar donde existen fuera del
proceso; ese objeto sigue el mecanismo existente (`reserve` con commit antes de subir,
`release` tras persistir el resultado, `sweep` y lifecycle de R2). No se escribe ningún
derivado en disco local.

`TemporaryMediaService.EXTENSIONS` gana `image/png → png` (cambio neutral).

**Rationale**: Threads acepta PNG, así que no hace falta la conversión a JPEG de Instagram;
PNG sin pérdida es la conversión técnica más fiel para WebP. El módulo de Threads no puede
importar `instagram_media.py` (test `test_threads_and_instagram_do_not_depend_on_each_other`),
así que las reglas viven en `threads_media.py` con Pillow.

**Alternatives considered**: rechazar WebP — formato soportado por la Content Library; WebP→JPEG
como Instagram — con pérdida e incompatible con transparencia, innecesario.

---

## 8. Vídeo (spec FR-015, FR-016)

**Hallazgos** (*Overview → Video Specifications*): MOV o MP4 sin edit lists y `moov` al
inicio; HEVC o H.264, progresivo, closed GOP, 4:2:0; audio AAC ≤ 48 kHz, mono/estéreo,
128 kbps; 23–60 FPS; ancho ≤ 1920; aspecto 0,01:1–10:1; VBR ≤ 100 Mbps; duración > 0 y
≤ 300 s; ≤ 1 GB.

**Decision** (`threads_media.video_problems`, con `media.probe_video_streams` y
`media.moov_before_mdat` existentes; sin transcodificar). Principio: todo lo que `ffprobe`
(o el parser de cajas existente) da de forma fiable **se valida en preflight**; nada se
delega a Meta si puede comprobarse localmente, y nunca se da por validado lo que no se ha
comprobado.

Tres categorías por requisito:

- **Obligatorio local**: si el dato falta o no es fiable, el preflight **falla
  conservadoramente** (`threads_video_incompatible` con el mensaje "AutoPublisher could not
  determine <dato>"); nunca se publica a ciegas.
- **Local si hay dato**: se valida cuando `ffprobe` lo reporta; si no lo reporta, se
  **delega a Meta** y queda registrado.
- **Delegado a Meta**: no verificable de forma robusta en local; documentado y registrado.

| Requisito (Threads) | Fuente local | Categoría |
|---|---|---|
| Contenedor MOV o MP4 | `Content.media_format` (+ `format_names` de ffprobe) | Obligatorio local (WebM y otros → rechazo) |
| Tamaño ≤ 1 GB (10⁹ bytes) | tamaño del archivo | Obligatorio local |
| Stream de vídeo presente | ffprobe | Obligatorio local |
| Codec de vídeo H.264 o HEVC | `codec_name` | Obligatorio local |
| Resolución: ancho ≤ 1920 | `width`, `height` | Obligatorio local |
| Relación de aspecto 0,01:1–10:1 | `width`/`height` | Obligatorio local |
| Duración > 0 y ≤ 300 s | `format.duration` | Obligatorio local |
| Frame rate 23–60 FPS | `avg_frame_rate` / `r_frame_rate` | Obligatorio local |
| Submuestreo 4:2:0 | `pix_fmt` (`yuv420p`, `yuvj420p`, `yuv420p10le`) | Obligatorio local |
| `moov` al inicio | `moov_before_mdat` (cabeceras de primer nivel) | Obligatorio local (si el archivo no se puede analizar → falla) |
| Bitrate de vídeo ≤ 100 Mbps | `bit_rate` del stream; si falta, `bit_rate` del contenedor (incluye audio: sobrestima, conservador) | Local si hay dato; sin ninguno → delegado |
| Audio (si existe): codec AAC | `codec_name` | Obligatorio local |
| Audio: sample rate ≤ 48 kHz | `sample_rate` | Obligatorio local |
| Audio: mono o estéreo (1–2 canales) | `channels` | Obligatorio local |
| Audio: bitrate ≤ 128 kbps (128 000 b/s) | `bit_rate` del stream de audio | Local si hay dato; si falta → delegado |
| Escaneo progresivo | `field_order` | Local si hay dato (`progressive` pasa; `tt`/`bb`/`tb`/`bt` → rechazo); ausente o `unknown` → delegado |
| Closed GOP | — | Delegado a Meta (exige analizar el bitstream) |
| Sin edit lists | — | Delegado a Meta (no expuesto por el análisis actual) |

- Sin `ffprobe` (o si falla) → `threads_media_unverifiable`: el preflight falla, porque los
  requisitos obligatorios no pueden comprobarse.
- Los requisitos delegados de cada intento se registran en
  `submitted.delegated_checks` (por ejemplo `["closed_gop", "edit_lists",
  "audio_bitrate"]`) y la documentación lo explica; la interfaz no los presenta como
  validados.
- Si Meta rechaza por un requisito delegado (`INVALID_BIT_RATE`, `FAILED_PROCESSING_VIDEO`,
  `FAILED_PROCESSING_AUDIO`…), el container queda `ERROR` antes de publicar: fallo
  determinado `threads_media_rejected`.
- El límite de audio se aplica estrictamente (≤ 128 000 b/s), sin tolerancia propia. El
  quickstart registra el valor que `ffprobe` reporta para un AAC codificado a 128 kbps; si
  los archivos reales reportan sistemáticamente un valor ligeramente superior que Meta
  acepta, se revisará esta regla antes del cierre.
- Código de rechazo: `threads_video_incompatible` (campo `media`), uno por requisito
  incumplido o indeterminado.

**Rationale**: validar localmente todo lo que es fiable evita subir un vídeo que Meta
rechazará; fallar ante datos obligatorios ausentes cumple "no publicar a ciegas"; delegar
solo lo que no puede comprobarse de forma robusta, de forma explícita y registrada. Lógica
propia de Threads (límites distintos de Reels y prohibición de importar Instagram); los
helpers de inspección ya son neutrales en `media.py`.

---

## 9. Límite de publicación (spec FR-028, FR-029)

**Hallazgos**: `GET /{threads-user-id}/threads_publishing_limit` → uso `quota_usage` y
configuración `config` con `quota_total` y `quota_duration`; ejemplo:
`{"data":[{"quota_usage":4,"config":{"quota_total":250,"quota_duration":86400}}]}`. Límite
documentado: 250 posts publicados por la API en 24 h móviles (un carousel cuenta como uno).
Requiere `threads_basic` y `threads_content_publish`. Meta recomienda que las apps respeten el
límite, sobre todo en posts programados. No documenta si crear containers consume cuota ni el
retraso del contador.

**Decision**:

- Se piden `fields=quota_usage,config`. **Forma entendida**: `data` es una lista cuyo primer
  elemento (o, si no hay `data`, el objeto raíz) contiene `quota_usage` entero ≥ 0 y `config`
  con `quota_total` entero > 0; `quota_duration` (entero > 0) se registra en `submitted` si
  viene (informativo). Ninguna cifra fija propia.
- La política distingue **tres casos**:

| Caso | Ejemplos | Resultado |
|---|---|---|
| **Cuota obtenida** con la forma entendida | `{"data":[{"quota_usage":4,"config":{"quota_total":250,…}}]}` | `quota_usage >= quota_total` → preflight falla `409 threads_publishing_limit_reached`. Si no, continúa; `submitted` guarda `quota_checked: true`, `quota_usage`, `quota_total`, `quota_duration`. |
| **Fallo temporal** al consultar | timeout, error de red, 5xx, 429 o códigos Graph transitorios (`ThreadsUnavailable`) | **Continúa** la publicación: la cuota no es un mecanismo anti-duplicado. `submitted.quota_checked = false` y aviso seguro `quota_unavailable` en el intento ("Threads did not report the publishing limit; publishing continued"). Si la cuota estuviera agotada, Meta rechaza al crear el container o en `threads_publish` (fallo determinado, §12). |
| **Respuesta estructuralmente inesperada** | 200 con JSON que no tiene la forma entendida (campos ausentes, tipos distintos, `data` vacío), o cuerpo no JSON (`ThreadsUnexpectedResponse`) | **Falla el preflight** con `502 threads_unexpected_response` ("Threads answered the publishing limit in a format AutoPublisher does not understand; nothing was published"). No se inventan valores ni se trata como "cuota no disponible". Puede indicar un **cambio de contrato** de Meta (*contract drift*): se documenta y requiere revisar el gateway. |

- Un error de credencial o permiso en la consulta (`ThreadsTokenInvalid`,
  `ThreadsPermissionDenied`) → `Reconnect required` (Feature 010). Otro rechazo explícito 4xx
  (`ThreadsRejected`) se trata como respuesta inesperada del contrato (falla el preflight con
  `threads_unexpected_response`): un 4xx en un endpoint de solo lectura documentado no es un
  fallo temporal.
- `publishing_limit()` del gateway devuelve la cuota normalizada o lanza
  `ThreadsUnexpectedResponse` ante una forma no entendida (ya no devuelve `None`).
- Solo se cuenta lo que consume `threads_publish` (un post publicado = 1). Crear un container
  no se considera consumo (no documentado como tal).
- La cuota **nunca** se usa para decidir si un intento ambiguo publicó (contador con retraso,
  FR-029).

**Rationale**: misma política probada en Instagram (009 §10); no inventa valores ni bloquea
publicaciones válidas por un fallo de lectura.

**Validación real**: quickstart paso 1 registra la respuesta real (forma y valores) **antes
del cierre** y el paso 2 comprueba que `quota_usage` sube tras publicar. **Stop condition**
si la forma real es incompatible con la forma entendida.

---

## 10. Containers: estados, espera por tipo y caducidad (spec FR-030–FR-034)

**Hallazgos**: estados `IN_PROGRESS`, `FINISHED` (*"ready to be published"*), `PUBLISHED`,
`ERROR` (con `error_message`: `FAILED_DOWNLOADING_VIDEO`, `FAILED_PROCESSING_AUDIO`,
`FAILED_PROCESSING_VIDEO`, `INVALID_ASPEC_RATIO`, `INVALID_BIT_RATE`, `INVALID_DURATION`,
`INVALID_FRAME_RATE`, `INVALID_AUDIO_CHANNELS`, `INVALID_AUDIO_CHANNEL_LAYOUT`, `UNKNOWN`),
`EXPIRED` (no publicado en 24 h). *"We recommend querying a container's status once per
minute, for no more than 5 minutes."* *"It is recommended to wait on average 30 seconds
before publishing a Threads media container."* La documentación no dice que `TEXT` o `IMAGE`
**no** necesiten procesamiento, ni lo contrario. La app de ejemplo crea el container en el
servidor y expone la lectura de `status,error_message` como paso separado antes de publicar,
para todos los tipos.

**Decision — verificación por tipo (FR-032)** (revisada el 2026-10-13 tras la validación
real temprana, ver quickstart §3): un container solo es publicable cuando se cumplen
**ambas** condiciones:

1. `status == FINISHED`, la única que la documentación define como lista para publicar
   (condición **necesaria**, no suficiente);
2. **antigüedad** del container ≥ `MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS` (30 s), medida
   desde su `container_created_at` persistido con el reloj inyectable del publisher.

Los 30 s son **política del producto**, conservadora, basada en la recomendación de Meta
(*"wait on average 30 seconds before publishing"*) y en la validación real: un container
`TEXT` leído `FINISHED` unos 300 ms después de crearse fue rechazado (4xx) por
`threads_publish`, mientras que otro `FINISHED` de unos 10 min se publicó con exactamente la
misma codificación. **No** es un mínimo documentado de la API ni una garantía de que 30 s
basten. La regla es común a `TEXT`, `IMAGE` y `VIDEO`.

Un container `FINISHED` más joven espera **solo el tiempo que le falta** (nunca un
`sleep(30)` fijo añadido tras `FINISHED`) y se **vuelve a leer** antes del write-ahead: un
`ERROR`/`EXPIRED` durante esa espera sigue impidiendo la publicación. Ejemplos: `FINISHED`
a 0,5 s → espera ≈ 29,5 s; a 20 s → espera 10 s; a 35 s → publica sin esperar. La espera
respeta el cierre ordenado y el timeout de procesamiento del tipo (contado también desde la
creación del container). Lo que cambia por tipo es el polling mientras Meta procesa:

| Tipo | Comportamiento |
|---|---|
| `TEXT` | 1) crear container; 2) leer estado **inmediatamente**; 3) `FINISHED` → publicar en cuanto tenga 30 s; 4) `IN_PROGRESS` (o estado desconocido / lectura temporal fallida) → esperas de 2, 5, 10 y 15 s y después cada 15 s; 5) hasta `FINISHED`, `ERROR`, `EXPIRED` o timeout de **1 min**. |
| `IMAGE` | 1) crear container; 2) leer estado **inmediatamente**; 3) `FINISHED` → publicar en cuanto tenga 30 s; 4) `IN_PROGRESS` (o estado desconocido / lectura temporal fallida) → esperas de 2, 5, 10 y 15 s y después **cada 30 s**; 5) continuar hasta `FINISHED`, `ERROR`, `EXPIRED` o timeout máximo de **3 min** (Meta descarga la imagen desde la URL temporal). |
| `VIDEO` | 1) crear container; 2) leer estado inmediatamente; 3) `FINISHED` → publicar en cuanto tenga 30 s; 4) si no, esperas de 10, 20 y 30 s y después cada 60 s; 5) hasta `FINISHED`, `ERROR`, `EXPIRED` o timeout de **5 min** en total (recomendación oficial). |

- La lectura inmediata es una consulta de solo lectura: detecta pronto `ERROR`/`EXPIRED` y
  evita esperas de polling si Meta ya terminó, pero `FINISHED` por sí solo **no** autoriza
  el efecto irreversible hasta alcanzar la antigüedad mínima.
- Un reinicio o cierre durante la espera de antigüedad deja el intento en `processing` (no
  incertidumbre): `threads_publish` aún no se llamó, el resultado es determinado.
- `ERROR` → fallo determinado: `FAILED_DOWNLOADING_VIDEO` → `threads_media_fetch_failed`;
  `INVALID_*`/`FAILED_PROCESSING_*` → `threads_media_rejected`; `UNKNOWN` u otro →
  `threads_processing_failed`. `EXPIRED` → `threads_container_expired`. Tiempo agotado →
  `threads_processing_timeout`. Ninguno ejecuta `threads_publish`.
- Estado ausente o desconocido en la respuesta, o error temporal al leer → se vuelve a leer en
  la siguiente espera; si se agota el tiempo, `threads_processing_timeout` (determinado: no se
  ha llamado a `threads_publish`).
- `PUBLISHED` en un container recién creado (nunca esperado) → nunca se publica de nuevo; se
  trata como publicado sin identidad remota (§12).
- Las esperas se trocean en intervalos de 1 s para respetar el cierre ordenado (`interrupted`,
  determinado).
- **Un container por intento** (FR-034). **No se reutilizan containers** de intentos
  anteriores: el coste de crear uno nuevo es pequeño (texto/imagen inmediatos; vídeo
  acotado) y elimina la lógica de huellas de Instagram. La caducidad de 24 h solo afecta a
  la defensa de §11.
- Persistencia: `threads_publish_runs` guarda `container_id` y `container_created_at`
  **inmediatamente** tras crearlo (commit), y `container_status`/`container_error` en cada
  lectura (FR-031).

**Rationale**: una sola regla (`FINISHED` + antigüedad mínima) para los tres tipos; polling
solo cuando Meta indica procesamiento, y espera de antigüedad solo por el tiempo que falta.

**Validación real**: quickstart pasos 2–4 anotan el estado devuelto por la primera lectura y
el tiempo hasta `FINISHED` de cada tipo. Validación temprana (2026-10-13): la sonda `TEXT`
leyó `IN_PROGRESS` a +0,2 s; el intento real leyó `FINISHED` de inmediato y su
`threads_publish` a ~300 ms fue rechazado → origen de la antigüedad mínima. **Stop condition** si un estado real contradice el modelo (por ejemplo, un
container de texto sin `status` o que nunca llega a `FINISHED`).

**Alternatives considered**: publicar texto sin leer el estado — la documentación no lo
garantiza y la lectura cuesta una petición; publicar en cuanto se lee `FINISHED` — rechazado
por Meta en la validación real; `sleep(30)` fijo tras `FINISHED` — alarga sin necesidad los
containers que ya son antiguos (polling largo, vídeo); reintentar `threads_publish` tras el
rechazo — prohibido (§12); reutilizar containers como Instagram — complejidad sin beneficio
claro.

---

## 11. Defensa entre intentos: container anterior ya publicado

**Decision**: en `prepare()`, si la publicación tiene un run con `container_id` creado hace
menos de 23 h, se lee su estado (solo lectura). `PUBLISHED` → `409 threads_already_published`
("Threads reports that a previous attempt of this publication was already published"); nada
se crea. Cualquier otro estado o un error "desconocido para Meta" → se continúa con un
container nuevo. Error temporal → `503 threads_unavailable` (no se publica sin poder
descartar el duplicado). Credencial → `threads_reconnect_required`.

**Rationale**: defensa en profundidad tras un reconocimiento manual equivocado
(`confirm_remote_checked`), igual que Instagram (009 §12).

---

## 12. `threads_publish`, write-ahead y resultado ambiguo (spec FR-035–FR-040)

**Hallazgos**: `threads_publish` con `creation_id` devuelve `{"id": "<THREADS_MEDIA_ID>"}`.
La guía oficial de troubleshooting, para el caso "*publish did not return a media ID*",
indica consultar el estado del container; `PUBLISHED` significa *"The container's media
object has been published"*. No se documenta idempotencia, ni un campo del container con el
media ID publicado, ni que el ID del container coincida con el del post.

**Decision**:

1. **Write-ahead**: tras ver `FINISHED` con la antigüedad mínima de §10, se confirma en SQLite
   `threads_publish_runs.phase = 'publishing'` con `publish_started_at`, y después
   `reporter.enter_finalizing()` (stage genérico `finalizing`, en `UNCERTAIN_STAGES`). Si
   cualquiera de los dos commits falla → `internal_error` determinado, sin publicar.
2. `threads_publish` se llama **exactamente una vez** por container.
3. **200 con `id`** → éxito: post ID → permalink (§13).
4. **Rechazo explícito** (`ThreadsRejected`, `ThreadsTokenInvalid`,
   `ThreadsPermissionDenied`) → **una** lectura del container: `PUBLISHED` → publicado sin
   identidad remota (paso 6); otro → fallo **determinado** (`threads_publish_failed`;
   `threads_reconnect_required` y marca de conexión si es credencial/permiso).
5. **No concluyente** (`ThreadsUnavailable` — transporte, timeout, 5xx, 429, códigos
   transitorios 1/2/4/17/32/613 — o `ThreadsUnexpectedResponse`): nunca se repite
   `threads_publish` ni se crea otro container. Solo lecturas del container original a los
   0, 5, 15, 30 y 60 s. `PUBLISHED` es la **única** señal que resuelve → paso 6. Cualquier
   otro estado (`FINISHED`, `ERROR`, `EXPIRED`, `IN_PROGRESS`, desconocido) o lectura fallida
   → `threads_publish_uncertain`, `outcome_determined = false`, revisión manual. Una vez
   invocado `threads_publish`, un estado distinto de `PUBLISHED` **no** prueba que no se
   publicó (posible retraso del estado; no documentado).
6. **Publicado sin post ID**: `PublishOutcome(external_id=None, external_url=None)` con el
   aviso `remote_identity_unavailable` (cuenta, hora del write-ahead). Nunca se infiere el ID
   buscando posts recientes por texto, hora o media, aunque haya un único candidato.
7. El mensaje de `threads_publish_uncertain` indica `@username`, la hora UTC del write-ahead y
   el inicio del texto (o "image"/"video" si no hay texto) como **ayuda** para la revisión
   manual, nunca como prueba.

**Reconciliación** (FR-040, punto de extensión existente `Publisher.reconcile`): para un
intento ambiguo con run en fase `publishing`/`verifying_result`/`failed`, `container_id` y
`publish_started_at`: obtener credencial válida y **una** lectura del container. `PUBLISHED` →
`Reconciliation(published_at=publish_started_at, outcome sin identidad remota + aviso)` y el
run pasa a `succeeded`; cualquier otro caso → `None` (sigue ambiguo y se exige
`confirm_remote_checked`). Nunca publica, nunca crea containers, nunca lista posts.

**Reinicio**: la recuperación genérica sin red cierra los intentos `running`; los que estaban
en `finalizing` quedan ambiguos y se reconcilian después con lo anterior. Ningún cambio en el
núcleo.

**Rationale**: misma política que Instagram, que es la que exige la spec; la guía oficial de
Threads respalda el estado del container como mecanismo de comprobación.

**Validación real**: no se provocan ambigüedades contra producción (cubiertas con fakes). El
quickstart sí comprueba, tras una publicación normal, que el container figura `PUBLISHED`
(paso 2), lo que respalda el modelo. **Stop condition** si un container publicado no figura
`PUBLISHED`.

---

## 13. Permalink y resultado publicado (spec FR-045, FR-046)

**Hallazgos**: `GET /{threads-media-id}` con `fields` `permalink`, `timestamp`, `shortcode`…;
`permalink` *"will be omitted if the media contains copyrighted material or has been flagged
for a copyright violation"*. Sin acceso avanzado solo se recuperan posts de testers (nuestro
caso).

**Decision — el permalink nunca bloquea ni vuelve ambiguo un resultado**:

Orden exacto tras un `threads_publish` que devuelve un post ID:

1. **Desde ese momento el efecto remoto está determinado como publicado.** El run pasa a
   `verifying_result` y nada posterior puede convertir el intento en fallido ni ambiguo.
2. Intento de obtener el post con la operación oficial
   `GET /{post_id}?fields=id,permalink,timestamp`, con reintentos acotados **solo de esa
   lectura** ante errores temporales (esperas de 2 y 5 s). Se acepta solo un `permalink` que
   empiece por `https://`.
3. Se construye el resultado:
   - con permalink → `external_id = post ID`, `external_url = permalink`,
     `details = {"permalink": …, "threads_timestamp": …}`;
   - si la lectura **falla temporalmente**, devuelve una respuesta **sin `permalink`**, Meta
     lo **omite** (copyright) o la respuesta es inesperada → `external_id = post ID`,
     `external_url = null` y el aviso seguro `permalink_unavailable` ("Threads did not return
     the link of the post"). Cualquier excepción de esta lectura se captura dentro del
     publisher: nunca escapa como `PublishFailure`.
4. El ejecutor genérico persiste en una transacción (`persist_success`): resultado remoto,
   Publication `PUBLISHED` y Attempt `succeeded`.
5. `refresh_details()` intenta una vez más el permalink si faltaba (best-effort existente;
   si lo obtiene, actualiza `details` y quita el aviso, pero `external_url` de un intento ya
   cerrado solo se rellena con un permalink oficial).
6. Solo después, `release()` (cleanup de media temporal en imagen/vídeo).

Reglas:

- Un fallo al recuperar el permalink **nunca** repite `threads_publish`, nunca crea otro
  container y nunca cambia `PUBLISHED`/`succeeded`.
- **Nunca** se construye un enlace con el ID, el shortcode o el username (FR-046), a
  diferencia del fallback de perfil de Instagram.
- `Open on Threads` aparece solo cuando `external_url` contiene un permalink oficial
  (componentes existentes).

---

## 14. Media delivery (spec FR-008–FR-012)

**Decision**: se reutiliza `TemporaryMediaService` tal cual (bucket privado, clave aleatoria
registrada con commit **antes** de subir, URL prefirmada en memoria (`SecretUrl`), `release`,
`sweep`, lifecycle de R2 como última red, redacción de firmas). Flujo en imagen/vídeo:
`reserve` → `upload` (progreso de bytes real) → `public_url` → container. Texto: ninguna
llamada al servicio. `release()` del publisher: `release_attempt(attempt_id)` + `sweep()`; si
no hay objetos (texto), no devuelve avisos.

- **Validez de la URL** (FR-010): la URL firmada se genera **después** de terminar la subida
  (`public_url` tras `upload`), así que el tiempo de subida no consume su validez. Desde ese
  momento Meta puede necesitarla durante la creación del container (timeout
  `PUBLISH_TIMEOUT_SECONDS` = 60 s) más la espera máxima del vídeo (`video_timeout` = 5 min).
  Se define `URL_TTL_SAFETY_MARGIN_SECONDS` (5 min) en `threads_publishing.py` y un test
  (T034) comprueba con las constantes del producto que `MIN_URL_TTL_SECONDS` (900 s) ≥
  `PUBLISH_TIMEOUT_SECONDS + video_timeout + URL_TTL_SAFETY_MARGIN_SECONDS` (60 + 300 + 300 =
  660 s). Como la configuración rechaza cualquier `url_ttl_seconds` < 900, ninguna
  configuración válida deja expirar la URL mientras Meta puede necesitarla. La documentación lo
  explica.
- Cambios neutrales: `EXTENSIONS` + `image/png`; `NOT_CONFIGURED_MESSAGE` deja de nombrar
  Instagram ("…that lets the platform fetch the media…", misma guía de configuración).
- No hay ningún sistema de entrega nuevo.

**Validación real**: quickstart paso 3 — **Stop condition** si Threads rechaza la URL
prefirmada (container `ERROR` por descarga o rechazo al crearlo).

---

## 15. Fases internas y progreso (spec FR-031, FR-051)

**Decision**: `ThreadsPublishPhase`: `preparing`, `delivering_media`, `creating_container`,
`processing_container`, `publishing`, `verifying_result`, `succeeded`, `failed` (mismos
nombres que Instagram, tabla propia). Stages genéricos: `preparing` → (`uploading` con bytes
reales, solo imagen/vídeo) → `processing` (container creado/esperando) → `finalizing`
(write-ahead) → `done`. Texto: `preparing` → `processing` → `finalizing` → `done`. Etiquetas de
interfaz existentes: "Uploading", "Processing on Threads", "Publishing on Threads"; sin
porcentajes inventados.

---

## 16. Clasificación de errores (spec FR-041–FR-043, FR-050)

**Decision** — la clasificación HTTP/Graph sigue en `threads_gateway._error_for` (Feature
010). Nuevos códigos seguros:

| Código | Cuándo | Determinado |
|---|---|---|
| `threads_text_invalid` | texto > 500, > 5 enlaces, vacío en `TEXT`, o rechazo de Meta con `THREADS_API__LINK_LIMIT_EXCEEDED` | sí |
| `threads_alt_text_invalid` / `threads_option_not_applicable` | al guardar opciones (422) | — |
| `threads_media_unsupported` | tipo de `Content` no soportado | sí |
| `threads_image_incompatible` / `threads_video_incompatible` / `threads_media_unverifiable` | preflight | sí |
| `threads_publishing_limit_reached` | cuota agotada (preflight o rechazo de Meta) | sí |
| `threads_container_failed` | rechazo al crear el container | sí |
| `threads_media_fetch_failed` | `FAILED_DOWNLOADING_VIDEO` / descarga | sí |
| `threads_media_rejected` | `INVALID_*`, `FAILED_PROCESSING_*` | sí |
| `threads_processing_failed` / `threads_processing_timeout` / `threads_container_expired` | estados | sí |
| `threads_publish_failed` | rechazo explícito de `threads_publish` sin `PUBLISHED` | sí |
| `threads_publish_uncertain` | §12 paso 5 | **no** |
| `threads_already_published` | §11 | — (preflight) |
| `threads_unexpected_response` | cuota con forma no entendida (§9); posible *contract drift* | — (preflight) |
| `publication_media_required` (neutral) | publicación sin `Content` en plataforma que no lo admite | — |
| `text_publication_not_supported` (neutral, 422) | crear publicación de texto para esa plataforma | — |

Se reutilizan: `threads_not_connected`, `threads_reconnect_required`,
`threads_identity_mismatch`, `threads_unavailable`, `credential_store_unavailable`,
`media_unavailable`, `media_delivery_not_configured`, `media_delivery_failed`, `interrupted`,
`internal_error`, `result_not_saved`, `remote_check_required`. Avisos:
`remote_identity_unavailable`, `permalink_unavailable`, `quota_unavailable`,
`temporary_media_cleanup_failed`.

`ThreadsTokenInvalid`/`ThreadsPermissionDenied` durante la ejecución → `mark_reconnect_required`
de la Feature 010 en una sesión nueva; `ThreadsUnavailable` nunca cambia el estado de
conexión. Los errores de Meta del cuerpo (`error_message`, `error.message`) nunca se
devuelven crudos; solo se mapean a códigos.

---

## 17. Seguridad y logging (spec FR-052)

**Decision**: sin secretos nuevos: el token sigue en el keyring (Feature 010) y la URL
firmada en `SecretUrl`. Los `POST` llevan token y URL en el cuerpo; los `GET` llevan el token
en la query (redactado por `RedactThreadsSecrets`, ya instalado sobre `httpx2`/`httpcore2`).
Las excepciones del gateway no llevan cuerpo, URL ni token y se lanzan `from None`. Tests de
secretos: base de datos (incluidas `threads_publish_runs`, `submitted`, `details`), logs
(`caplog` con nivel DEBUG), respuestas de la API y almacenamiento del navegador (test de
frontend existente ampliado).

---

## 18. Frontend (spec FR-051)

**Decision** — cambios mínimos, sin rediseño:

- `types.ts`: `Publication.content_id: number | null`, `content: … | null`;
  `ThreadsPublicationOptions`; `TEXT_POST_PLATFORMS = ["threads"]` (qué cuentas ofrece el
  formulario de texto, espejo de `accepts_text_only`); `PUBLISHING_PLATFORMS` + `"threads"`.
- `PublicationQueue`: botón **New text post** visible solo si el proyecto tiene cuentas activas
  de `TEXT_POST_PLATFORMS`; abre `TextPublicationCreate` (texto, hashtags, cuentas, fecha y
  consentimiento automático existente). Filas sin `Content` muestran "Text post" y el inicio
  del texto.
- `PublicationDetail`: sin `MediaPreview` ni bloqueo por archivo cuando no hay `Content`;
  `ThreadsPublishOptions` (texto final exacto con su conteo/enlaces y avisos de vista previa y
  topic tag, `alt_text` solo en imagen/vídeo, problemas locales, estado de media delivery).
- `PublicationAttempts`: revisión manual genérica para Meta (cuenta, texto/caption, hora)
  reutilizada por Instagram y Threads; `Open on Threads` ya sale de `external_url`.
- `api.ts`: `createTextPublications`, `getThreadsOptions`, `saveThreadsOptions`.

---

## 19. Tests (spec FR-055)

**Decision**: `FakeThreads` (tests/fakes.py) se amplía con containers (`TEXT`/`IMAGE`/`VIDEO`,
parámetros recibidos, secuencia de estados programable, `error_message`), `threads_publish`
(éxito, rechazo, timeout/5xx tras publicar realmente o sin publicar), media (`permalink`,
`timestamp`, omitido), cuota (forma válida, agotada, error temporal, forma inesperada) y
registro de peticiones (para verificar "como máximo una vez" y que la URL firmada solo va en
el cuerpo). Reutiliza `FakeMediaDeliveryProvider`, `InMemoryCredentialStore`, `FakeClock`,
`sleep` instantáneo y `probe_video_streams` simulado. Nuevos archivos `test_threads_*` por área
(publish texto/imagen/vídeo, preflight, options, quota, ambiguity, reconcile, recovery,
scheduler, cleanup, secrets, text publications) y regresión de YouTube/Instagram (suites
existentes) y de las publicaciones con `Content`. Casos explícitos de los ajustes del plan:
cuota en sus tres casos (agotada → error; temporal → continúa con `quota_unavailable`;
forma inesperada → `threads_unexpected_response`, sin container); permalink que falla
temporalmente, ausente u omitido tras un post ID (→ `PUBLISHED`, `succeeded`,
`external_url = null`, aviso, `threads_publish` llamado una sola vez); vídeo con cada dato
obligatorio ausente (→ falla) y con bitrates/escaneo ausentes (→ delegados en
`delegated_checks`); WebP estático con transparencia (derivado PNG validado), WebP animado
(rechazo) y derivado PNG > 8 MiB (rechazo sin media delivery); y la codificación del cuerpo
de los `POST` (sin parámetros en la URL). Test de migración `0010` (upgrade y
downgrade). Tests de arquitectura existentes + uno nuevo: `threads_publishing`/`threads_media`
no importan `app.instagram*`.

---

## 20. App Review / Development Mode

**Hallazgo**: los Threads testers pueden conceder `threads_basic` y
`threads_content_publish` sin App Review (Feature 010). `GET /{media-id}` sin acceso avanzado
solo devuelve posts de testers (el nuestro).

**Decision**: no se solicitan permisos nuevos. **Stop condition** si alguna llamada de
publicación exige un permiso distinto.
