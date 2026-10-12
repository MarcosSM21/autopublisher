# Research: Publicación real de imágenes y Reels en Instagram

**Feature**: `009-instagram-media-publishing` | **Fecha**: 2026-10-08

Las decisiones de protocolo se han contrastado con la documentación oficial vigente de Meta
(consultada el 2026-10-08). Parte de los hallazgos de la Feature 008 (§16 de su research) se
han vuelto a verificar aquí. Lo que la documentación no garantiza no se da por supuesto:
queda como comprobación obligatoria del `quickstart.md` o como política conservadora.

Fuentes principales:

- Content Publishing (Instagram Login):
  <https://developers.facebook.com/docs/instagram-platform/content-publishing>
- IG User Media (`POST /<IG_ID>/media`, especificaciones de imagen y Reels):
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media>
- IG Container (`status_code`):
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-container>
- IG User Media Publish:
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media_publish>
- IG User Content Publishing Limit:
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit>
- IG Media (campos `permalink`, `timestamp`, …):
  <https://developers.facebook.com/docs/instagram-platform/reference/instagram-media>
- Error codes (Content Publishing):
  <https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/error-codes>
- Cloudflare R2 — presigned URLs, object lifecycles y precios:
  <https://developers.cloudflare.com/r2/api/s3/presigned-urls/>,
  <https://developers.cloudflare.com/r2/buckets/object-lifecycles/>,
  <https://developers.cloudflare.com/r2/pricing/>
- Cloudflare Quick Tunnels:
  <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/>

---

## 1. Endpoints de Content Publishing con Instagram Login (investigación 1)

**Decision**: host `graph.instagram.com`, versión **`v26.0`**, tomada de la constante
existente `GRAPH_API_VERSION` de `instagram_gateway.py` (fuente única compartida con la
Feature 008; no se duplica). Endpoints:

| Operación | Llamada |
|---|---|
| Crear container de imagen | `POST /v26.0/<IG_ID>/media` — `image_url`, `caption`, `alt_text` (opcional), `is_ai_generated` |
| Crear container de Reel | `POST /v26.0/<IG_ID>/media` — `media_type=REELS`, `video_url`, `caption`, `share_to_feed`, `is_ai_generated` |
| Estado del container | `GET /v26.0/<CONTAINER_ID>?fields=status_code,status` |
| Publicar | `POST /v26.0/<IG_ID>/media_publish` — `creation_id=<CONTAINER_ID>` → `{"id": "<IG_MEDIA_ID>"}` |
| Permalink | `GET /v26.0/<IG_MEDIA_ID>?fields=id,permalink` |
| Cuota | `GET /v26.0/<IG_ID>/content_publishing_limit?fields=quota_usage,config` |

- `<IG_ID>` = `InstagramConnection.instagram_user_id` (el `user_id` de `/me`, que la
  documentación identifica como el Instagram professional account ID usado en Content
  Publishing; research 008 §8). El quickstart lo confirma con la primera publicación real.
- Los `POST` envían sus parámetros como **cuerpo de formulario**, no en la query string:
  así la URL temporal firmada nunca aparece en la URL de la petición que `httpx2` registra a
  nivel INFO (ver §15). El token viaja como `access_token`, igual que en la Feature 008, y ya
  está cubierto por `RedactInstagramSecrets`.
- `v26.0` se mantiene: es la versión que ya usa la integración y la más reciente publicada.

**Alternatives considered**: subida reanudable (`upload_type=resumable` +
`rupload.facebook.com`), que admite un archivo local. La documentación vigente la sigue
restringiendo: *"Only for apps that have implemented Facebook Login for Business"*. No es
aplicable a Instagram Login y no se cambia de variante de login (FR-005).

---

## 2. Requisitos vigentes de imagen y política de conversión (investigación 2)

**Hallazgos** (IG User Media, *Image Specifications*):

- Formato: **solo JPEG**. Tamaño máx.: **8 MB** (los errores lo expresan como 8 MiB).
- Relación de aspecto: **entre 4:5 y 1.91:1**.
- Ancho mín. 320 / máx. 1440: *"will be scaled up/down … if necessary"*; Meta lo
  reescala, **no es un motivo de rechazo**.
- Espacio de color: sRGB (Meta convierte).
- Errores asociados: `36000/2207004` (demasiado grande), `36001/2207005` (formato),
  `36003/2207009` (aspect ratio).

**Decision — política de imágenes** (`instagram_media.py`, sin red):

1. Se abre con Pillow (ya es dependencia) y se calculan las dimensiones **mostradas**
   (aplicando la orientación EXIF).
2. Comprobaciones comunes: imagen estática (WebP/PNG animados → incompatible);
   relación de aspecto `0.8 ≤ ancho/alto ≤ 1.91` → si no, incompatible (**nunca** se
   recorta ni se añaden bordes).
3. **JPEG**: se envía **tal cual, byte a byte** si pesa ≤ 8 MiB y no es CMYK/YCCK. JPEG
   CMYK → incompatible (la conversión de color no es neutral). JPEG > 8 MiB → incompatible
   (no se recomprime ni se reduce: el usuario decide).
4. **PNG / WebP estáticos**: conversión técnica temporal a JPEG **en memoria**:
   - transparencia: si existe algún píxel no opaco → **incompatible** (aplanar sobre un
     fondo sería una decisión creativa); si el canal alfa es totalmente opaco, se descarta;
   - modos `P`, `L`, `LA`, `I;16`, `RGBA`, etc. → `RGB` 8 bits;
   - se aplica la orientación EXIF a los píxeles (la composición mostrada no cambia) y se
     conserva el perfil ICC si existe;
   - sin redimensionar ni recortar; calidad 95 y submuestreo 4:4:4; si supera 8 MiB, un
     único reintento con calidad 90 y 4:2:0; si sigue superándolo → incompatible.
5. El JPEG derivado vive **solo en memoria** (≤ 8 MiB por construcción) dentro del payload
   de la ejecución: no se escribe ningún archivo derivado en disco, de modo que no existen
   derivados locales que limpiar ni que puedan quedar huérfanos. El Content original no se
   toca (se abre en solo lectura).
6. Cada incompatibilidad devuelve un mensaje que indica el requisito incumplido (formato,
   tamaño, relación de aspecto con el valor real, transparencia, animación, CMYK).

**Rationale**: la preferencia funcional del spec (conversión técnica sin alterar la
composición, original intacto, fallo explicado en caso contrario) con la opción más simple:
Pillow ya está disponible y el límite de 8 MiB permite trabajar en memoria.

**Alternatives considered**: reencuadrar al rango 4:5–1.91:1 o añadir bandas (cambia la
composición; prohibido); fondo blanco para transparencias (creativo); escribir el JPEG en
un temporal (añade un ciclo de vida de archivos sin beneficio).

---

## 3. Requisitos vigentes de Reels y validación (investigación 3)

**Hallazgos** (IG User Media, *Reels Specifications*):

| Requisito | Valor vigente |
|---|---|
| Contenedor | MOV o MP4 (MPEG-4 Part 14), sin edit lists, átomo `moov` al principio |
| Vídeo | HEVC o H.264, progresivo, closed GOP, croma 4:2:0 |
| Audio | AAC, ≤ 48 kHz, mono o estéreo, 128 kbps |
| Frame rate | 23–60 FPS |
| Resolución | máx. 1920 píxeles horizontales |
| Aspect ratio | entre 0.01:1 y 10:1 (recomendado 9:16) |
| Bitrate de vídeo | VBR, máx. 25 Mbps |
| Duración | 3 s – 15 min |
| Tamaño | máx. 300 MB |

**Decision — validación de Reels** (sin transcodificar, FR-022):

- Nueva función genérica `probe_video_streams(path)` en `media.py` (mismo patrón y timeout
  que `probe_video` de la Feature 003, `ffprobe -show_format -show_streams`), que devuelve
  `format_name`, `duration`, `size`, `bit_rate` y, por stream, `codec_type`, `codec_name`,
  `width`, `height`, `avg_frame_rate`/`r_frame_rate`, `pix_fmt`, `field_order`,
  `bit_rate`, `sample_rate`, `channels`. Si `ffprobe` no está o falla → `None`.
- Si no puede inspeccionarse el vídeo → `instagram_media_unverifiable` (falla en preflight;
  nunca se publica a ciegas).
- Comprobaciones **bloqueantes**: formato `mp4`/`mov` (la WebM de la biblioteca se rechaza);
  átomo `moov` antes de `mdat` (lectura de las cabeceras de caja de nivel superior, sin cargar
  el archivo); códec de vídeo `h264`/`hevc`; `field_order` progresivo o desconocido
  (entrelazado → incompatible); `pix_fmt` 4:2:0 (`yuv420p`, `yuvj420p`, `yuv420p10le`);
  25 Mbps de vídeo (bitrate del stream o, si falta, el global); 23–60 fps; ancho ≤ 1920;
  aspect 0.01–10; duración 3 s – 15 min; tamaño ≤ 300 MB; si hay audio: `aac`, ≤ 48 kHz y
  1–2 canales. Un Reel sin pista de audio se admite.
- **No verificables localmente** (closed GOP, edit lists, bitrate de audio exacto): no se
  bloquea; si Meta los rechaza, el container termina en `ERROR` y la ejecución falla de forma
  determinada con `instagram_processing_failed` (sin `media_publish`).
- Todas las comprobaciones de media se ejecutan en preflight, **antes** de exponer nada.

**Rationale**: comprobar todo lo verificable con la herramienta ya usada por el proyecto, sin
añadir transcodificación ni dependencias.

---

## 4. Caption, hashtags y menciones (investigación 4)

**Hallazgos**: *"Maximum 2200 characters, 30 hashtags, and 20 @ tags"*; error
`36004/2207010` para captions largos.

**Decision**:

- Caption = misma construcción determinista que la descripción de YouTube: descripción
  efectiva, una línea en blanco y los hashtags efectivos como `#a #b`
  (`description_with_hashtags`). El título efectivo **no** se envía.
- Para no importar código de YouTube desde Instagram, `_effective_metadata` y
  `build_description` se mueven de `youtube_publishing.py` a `publications.py` como
  `effective_metadata()` y `description_with_hashtags()`, neutrales; YouTube los reutiliza
  sin cambio de comportamiento.
- Validación (en `check` y `prepare`, antes de cualquier efecto): longitud ≤ 2200 caracteres
  (puntos de código Unicode, `len()`); hashtags ≤ 30 (ocurrencias de `#` seguidas de
  carácter de palabra y no precedidas de uno, en todo el caption); menciones ≤ 20 (ídem con
  `@`). Exceder → `instagram_caption_invalid` con el límite y el valor real. Nunca se trunca.
- Caption vacío permitido (el parámetro se omite).

**Riesgo**: Meta no define si cuenta caracteres en UTF-16 o puntos de código. Contar puntos
de código puede dejar pasar un caption con muchos emojis cercano a 2200; en ese caso Meta lo
rechaza al crear el container (`instagram_container_failed`, determinado, sin publicación).

---

## 5. `alt_text` (investigación 5)

**Decision**: soportado para **imágenes**, opcional, máx. **1000 caracteres** (*"up to 1000
character"*; *"Images only, not supported for reels/stories"*). Se envía solo si no está
vacío. Para Reels no se ofrece. Nunca se genera automáticamente.

---

## 6. `is_ai_generated` (investigación 6)

**Decision**: parámetro oficial de autodeclaración (*"to provide a self-disclosure of AI
usage … set `is_ai_generated` parameter to true"*), disponible con Instagram Login para
imágenes y Reels (no para hijos de carrusel). Se guarda como `bool | NULL` en
`instagram_publication_options`; `NULL` = no declarado → `instagram_options_incomplete` en
check y preflight (mismo patrón que `contains_synthetic_media` de YouTube). Se envía siempre
explícitamente (`true`/`false`). Nunca se infiere.

---

## 7. `share_to_feed` (investigación 7)

**Hallazgos**: sigue documentado, solo Reels: `true` → Feed y pestaña Reels; `false` → solo
Reels. **La documentación no indica valor por defecto.**

**Decision**: opción de Instagram para Reels con default explícito **`true`** (el Reel
aparece también en el feed, comportamiento habitual de la app de Instagram), documentado y
visible en la interfaz, y **siempre enviado explícitamente** para no depender del default no
documentado de Meta. No se envía para imágenes (la columna existe pero se ignora y la API la
devuelve como `null`).

---

## 8. Estados del container y polling (investigación 8)

**Hallazgos**: `status_code` ∈ `IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, `PUBLISHED`
(*"The container's media object has been published"*). Recomendación oficial: *"querying a
container's status once per minute, for no more than 5 minutes"*.

**Decision** (`InstagramPublishSettings`, inyectable y sin esperas reales en tests):

- Esperas entre consultas: 2 s, 5 s, 10 s, 20 s, 30 s y después 60 s.
- Tiempo máximo: **5 min para imágenes**; **10 min para Reels**. La desviación respecto a los
  5 minutos recomendados para Reels se justifica por vídeos de hasta 300 MB; el número total
  de consultas (≈ 14) sigue siendo del orden del recomendado.
- La espera usa `settings.sleep` en tramos cortos y consulta `reporter.should_stop()`; nunca
  hay espera activa.
- Resultado: `FINISHED` → continuar; `ERROR` → `instagram_processing_failed` (determinado);
  `EXPIRED` → `instagram_container_expired` (determinado); `PUBLISHED` antes de nuestro
  `media_publish` → imposible salvo reutilización (§12); tiempo agotado →
  `instagram_processing_timeout` (determinado: `media_publish` no se llamó). Un error
  temporal al consultar se reintenta dentro del mismo plazo.
- Las imágenes también se consultan (la documentación aplica el modelo de estado a todos los
  containers); normalmente terminan en la primera consulta.

---

## 9. Caducidad de containers (investigación 9)

**Decision**: un container caduca a las **24 h** (`EXPIRED`). AutoPublisher solo considera
reutilizable un container con < **23 h** de antigüedad (margen de 1 h) y lo comprueba
leyendo su estado (§12). Además Meta limita la creación a **400 containers / 24 h** por
cuenta: cada intento crea **como máximo uno** y la creación nunca se reintenta
automáticamente (FR-039).

---

## 10. `content_publishing_limit` (investigación 10)

**Hallazgos — documentación contradictoria**: Content Publishing dice *"limited to 100
API-published posts within a 24-hour moving period"*; la referencia de
`content_publishing_limit` y la de `media_publish` dicen **50** (`quota_total` "currently
50"). Esto confirma que no debe fijarse un número propio.

**Decision**:

- En `prepare` (consulta de solo lectura permitida en preflight, FR-031a):
  `GET …/content_publishing_limit?fields=quota_usage,config`. Si
  `quota_usage >= config.quota_total` → `instagram_publishing_limit_reached` antes de
  cualquier efecto. Los valores devueltos por Meta son la única fuente de verdad.
- Si la consulta falla temporalmente o la respuesta no tiene la forma esperada, **no se
  bloquea** (no se inventa un valor): se continúa, se anota `quota_checked: false` en
  `submitted` y, si la cuota estuviera agotada, `media_publish` la rechaza con `9/2207042`,
  que es un rechazo **determinado** → `instagram_publishing_limit_reached`.
- No se guarda histórico de uso (FR-035).

---

## 11. Semántica de `media_publish` y recuperación del resultado (investigaciones 11 y 12)

**Hallazgos**:

- `media_publish` crea el post visible y devuelve `{"id": "<IG_MEDIA_ID>"}`. La
  documentación **no** dice nada sobre idempotencia ni sobre publicar dos veces el mismo
  container.
- Tras publicar, el container pasa a `status_code = PUBLISHED`. La referencia de IG
  Container **no** documenta ningún campo que devuelva el media ID publicado.
- `9007/2207027` = *"media is not ready for publishing"* (rechazo; no publicó).

**Decision — política anti-duplicados**:

1. **Write-ahead** (FR-043): antes de `media_publish` se confirma en SQLite
   `instagram_publish_runs.phase = 'publishing'` y después el estado genérico
   `PublicationAttempt.stage = 'finalizing'` mediante `reporter.enter_finalizing()`. Si este
   commit falla, no se publica (fallo determinado).
2. Respuesta **200 con `id`** → éxito; se persiste el resultado (§13).
3. **Rechazo explícito 4xx** clasificado como definitivo (token, permiso, cuota, not ready,
   cuenta restringida, otros 4xx con error Graph legible) → se hace una **lectura de
   comprobación** del container: si `PUBLISHED`, se trata como publicado sin identidad
   remota (paso 5); si no, fallo **determinado** (`instagram_publish_failed`,
   `instagram_publishing_limit_reached`, `instagram_reconnect_required`, …).
4. **Resultado no concluyente** (timeout, error de transporte, 5xx, 429, códigos Graph
   1/2 o respuesta ilegible): **nunca** se repite `media_publish` ni se crea otro container.
   Solo se usan operaciones de lectura: el `status_code` del container original, consultado
   a los 0, 5, 15, 30 y 60 s, que es el **único mecanismo oficial de correlación** con ese
   container que documenta Meta:
   - `PUBLISHED` → publicación **determinada** (paso 5). Es la **única** señal aceptada
     para resolver automáticamente el resultado;
   - **cualquier otro estado** (`ERROR`, `EXPIRED`, `FINISHED`, `IN_PROGRESS`, valor
     desconocido), fallo temporal al consultar o ausencia de respuesta → **ambiguo**:
     `instagram_publish_uncertain`, `outcome_determined = false`, `remote_check_required`
     antes de cualquier nuevo intento manual. Una vez invocado el efecto final, un estado
     distinto de `PUBLISHED` **no** se usa como prueba de que el post no se publicó: la
     documentación vigente de Meta no lo garantiza (p. ej. no documenta que un container
     publicado no pueda pasar a `ERROR`/`EXPIRED` ni el retraso entre publicar y actualizar
     `status_code`). Antes de invocar `media_publish`, en cambio, `ERROR`/`EXPIRED` siguen
     siendo fallos determinados (§8), porque el efecto final no ha ocurrido.
5. **Publicación confirmada sin media ID** (pasos 3–4 con `PUBLISHED`): la referencia de IG
   Container solo documenta `id`, `status`, `status_code` y `copyright_check_status`;
   **ningún mecanismo oficial relaciona el container con el media ID publicado**. Por tanto:
   - **no** se infiere el media ID buscando publicaciones recientes ni se elige un "único
     candidato" por caption, fecha, tipo u otro atributo;
   - el resultado se registra tal como se conoce: publicación `PUBLISHED`, intento
     `succeeded` con `outcome_determined = true`, **`external_id` y `external_url` vacíos**
     (no se inventa ningún ID ni enlace) y el aviso `remote_identity_unavailable`
     ("Instagram confirmed the post was published, but did not return its ID; open your
     profile to find it");
   - como `PUBLISHED` nunca es elegible para ejecutar, queda bloqueado cualquier reintento,
     manual o automático, y la creación de otro container.
   Esto exige un cambio neutral en el núcleo: `PublishOutcome.external_id/external_url`
   pasan a ser opcionales (`str | None`). Las columnas de `PublicationAttempt` ya son
   anulables y ningún CHECK exige un ID en `succeeded`; YouTube siempre los informa.
   Si durante la validación real Meta añadiera un campo oficial que devuelva el media ID desde
   el container, se usaría solo ese campo.
6. Un resultado ambiguo nunca se reintenta automáticamente: el scheduler no ejecuta
   publicaciones `FAILED` y un reintento manual exige `confirm_remote_checked`
   (`remote_check_required`, Feature 006) **solo después** de que la reconciliación de §11b
   no haya podido confirmar `PUBLISHED`; además, como defensa en profundidad, el preflight
   del nuevo intento vuelve a leer el container y bloquea con `instagram_already_published`
   si figura como `PUBLISHED` (§12).
7. **Ayuda para la revisión manual** (nunca prueba automática): los mensajes de
   `instagram_publish_uncertain` y del aviso `remote_identity_unavailable` indican la cuenta
   (`@username`), la hora del write-ahead (`publish_started_at`) y el caption enviado, para
   que el usuario busque el post en su perfil. AutoPublisher no consulta la lista de
   publicaciones recientes para decidir nada.

**Recuperación tras reinicio**: la recuperación genérica de arranque sigue sin red. Un
intento que quedó en `finalizing` se cierra como ambiguo (como `final_chunk` de YouTube). No
se consulta Meta al arrancar (la recuperación de arranque es genérica y sin red; añadir red
ahí acoplaría el núcleo y retrasaría el arranque). La comprobación remota ocurre en la
reconciliación de §11b, la próxima vez que el usuario abre la comprobación de publicación o
pulsa `Publish now`.

## 11b. Reconciliación de solo lectura antes del reconocimiento manual (FR-046a)

**Decision**: punto de extensión **neutral** en el núcleo y lógica de Instagram en su
publisher.

- `Publisher.reconcile(session, publication, attempt, ctx) -> Reconciliation | None`
  (nuevo método del Protocol; YouTube y `FakePublisher` devuelven `None`).
  `Reconciliation(published_at, outcome: PublishOutcome)` solo se devuelve cuando la
  plataforma **confirma** que la publicación ocurrió.
- Núcleo (`publishing.py`): `reconcile_uncertain(session, publication, ctx, publishers)`
  se ejecuta en `get_publish_check` y en `start_publication` **antes** de
  `requires_remote_check`, solo si la publicación está `failed` y su último intento
  `needs_manual_review`. Si el publisher devuelve una `Reconciliation`, el núcleo aplica
  `persist_reconciled_success` en una transacción con UPDATE condicional
  (`publication.status = 'failed'` e `attempt.status = 'failed'` y
  `outcome_determined = false`): intento → `succeeded`, `outcome_determined = true`,
  `error_code`/`error_message` = NULL, `stage = 'done'`, `external_id`/`external_url` del
  outcome (NULL para Instagram), avisos añadidos; publicación → `published` con
  `published_at` = el valor devuelto. Si el UPDATE no afecta a ninguna fila (otra petición se
  adelantó), no hace nada. Después, `start_publication` responde `publication_not_eligible`
  (la publicación ya está `published`) y `publish-check` devuelve el estado reconciliado. El
  núcleo no importa nada de Instagram.
- Nueva transición genérica: `failed → published` **solo** mediante esta reconciliación
  confirmada por la plataforma (nunca por decisión del usuario ni del scheduler).
- Instagram (`InstagramPublisher.reconcile`): requiere que el último run del intento tenga
  `container_id` y fase `publishing` o `verifying_result` (fase final alcanzada). Obtiene una
  credencial válida (Feature 008) y lee **una vez** `status_code` del container:
  - `PUBLISHED` → `Reconciliation(published_at=run.publish_started_at, outcome=
    PublishOutcome(external_id=None, external_url=None,
    warnings=[remote_identity_unavailable]))`; el run pasa a `succeeded`;
  - cualquier otro estado (`FINISHED`, `IN_PROGRESS`, `ERROR`, `EXPIRED`), error temporal,
    credencial inutilizable o respuesta inesperada → `None`: el intento sigue ambiguo y se
    mantiene `remote_check_required`. No se asume "no publicado".
  - Nunca llama a `media_publish`, nunca crea containers y nunca lista publicaciones
    recientes.
- Red en `publish-check`: solo en este caso (último intento ambiguo con container conocido);
  en cualquier otro, `publish-check` sigue sin red.
- `published_at` = instante del write-ahead (`publish_started_at`), el mejor dato conocido de
  cuándo se publicó; se documenta como aproximado.
- **Política unificada** con la ejecución (§11.4): una vez invocado `media_publish` con
  resultado no concluyente, tanto durante la ejecución como en la reconciliación posterior,
  solo `PUBLISHED` resuelve automáticamente; cualquier otro estado o fallo de consulta
  mantiene el intento ambiguo y `remote_check_required`. Nunca se repite `media_publish`.
- `publish-check` solo hace esta lectura cuando reconcilia un intento ambiguo y solo una vez
  por petición; no existe polling remoto pasivo ni periódico (la interfaz no repite
  `publish-check` por su cuenta para reconciliar; el refresco automático existente de la
  publicación usa `GET /publications/{id}`, que no contacta con Meta).

**Alternatives considered**: reintentar `media_publish` sobre el mismo container confiando en
que Meta rechace un container ya publicado (no documentado → rechazado); resolver
ambigüedades al arrancar con llamadas a Meta (acopla la recuperación genérica a la red);
identificar el post buscando publicaciones recientes (`GET /<IG_ID>/media`) por caption,
fecha o tipo, aunque haya un único candidato: **rechazado** porque no es un mecanismo
oficial de correlación y podría asociar un post equivocado (p. ej. uno publicado a mano con
el mismo texto); marcar la publicación confirmada como `FAILED` ambigua: rechazado porque
Meta ya ha determinado que se publicó y `PUBLISHED` bloquea mejor cualquier reintento.

---

## 12. Reutilización de containers y bloqueo de duplicados entre intentos (FR-051)

**Decision**: en `prepare` de cada nuevo intento se lee el último registro
`instagram_publish_runs` de la publicación con `container_id` y antigüedad < 23 h, y se
consulta su `status_code` (lectura permitida en preflight):

| Estado leído | Acción |
|---|---|
| `PUBLISHED` | **Se bloquea** con `instagram_already_published` (409): Instagram indica que ese container ya se publicó; no se crea nada. Defensa en profundidad: el caso ambiguo normal ya lo resuelve la reconciliación de §11b antes de llegar aquí; este bloqueo cubre cualquier otro camino (p. ej. un intento cerrado como determinado cuyo container figura después como `PUBLISHED`). |
| `FINISHED` y misma huella | Se **reutiliza**: el nuevo intento no expone media ni crea container; pasa directamente a `media_publish` (con write-ahead). |
| `FINISHED` con huella distinta, `IN_PROGRESS`, `ERROR`, `EXPIRED`, no encontrado | Se crea un container nuevo desde el principio. |
| Consulta fallida (temporal) | `instagram_unavailable`; el preflight falla sin efectos (no se arriesga un duplicado). |

- **Huella** (`fingerprint`): SHA-256 de checksum del Content + tipo de media + caption +
  opciones enviadas. Garantiza que un container solo se reutiliza para exactamente lo mismo.
- `IN_PROGRESS` no se reutiliza porque el media temporal de ese intento ya se habrá
  eliminado (§16) y Meta podría no terminar de obtenerlo.

---

## 13. Orden publicación confirmada → cleanup

**Decision** (spec FR-054–FR-056):

1. `upload()` del publisher devuelve el `PublishOutcome` (media ID + permalink; o, si solo
   el estado del container confirmó la publicación, sin identidad remota, §11.5; o la URL del
   perfil como enlace alternativo, §14).
2. El runner genérico ejecuta `persist_success` (una transacción: resultado remoto,
   `PUBLISHED`, intento `succeeded`).
3. **Después**, el runner llama a `publisher.release(...)`, un nuevo método genérico
   best-effort que también se invoca tras un fallo persistido. Para Instagram elimina el
   objeto temporal y actualiza su registro. YouTube no hace nada.
4. Si `release` falla, se registra un log seguro y se añade al intento el aviso
   `temporary_media_cleanup_failed` mediante una escritura que **solo** toca `warnings`; el
   registro del objeto queda pendiente para el barrido (§16). El estado nunca cambia.

La limpieza no forma parte de ninguna fase que decida el resultado.

---

## 14. Permalink y resultado publicado

**Decision**: tras `media_publish`, `GET /<IG_MEDIA_ID>?fields=id,permalink` con hasta 3
intentos (esperas 2 s, 5 s) ante fallos temporales. Si no se obtiene, el resultado sigue
siendo un éxito con `external_url` = `https://www.instagram.com/<username>/` (enlace
alternativo seguro al perfil) y el aviso `permalink_unavailable` (FR-057). `refresh_details`
reintenta el permalink una vez más (best-effort) y, si lo obtiene, lo guarda en
`details.permalink` y la interfaz lo prefiere.

`external_id` = media ID. Siguiendo el precedente de YouTube, el media ID nunca se escribe en
logs (FR-058); solo `attempt_id` y códigos.

---

## 15. Comportamiento HTTP que Meta necesita y cuándo deja de necesitar la URL (investigaciones 13 y 14)

**Hallazgos**:

- *"We cURL media used in publishing attempts, so the media must be hosted on a publicly
  accessible server **at the time of the attempt**."* `image_url`/`video_url`: *"must be on a
  public server"*. Error `9004/2207052` = *"The media could not be fetched from this uri"*;
  `-2/2207003` = descarga demasiado lenta.
- La documentación **no** especifica si Meta usa `HEAD`, peticiones `Range`, si sigue
  redirecciones ni qué `Content-Type`/`Content-Length` exige.
- Para vídeo, la obtención ocurre durante el procesamiento asíncrono (`IN_PROGRESS`).

**Decision**:

- La URL debe responder a `GET` con `200`, el `Content-Type` correcto (`image/jpeg`,
  `video/mp4`, `video/quicktime`) y `Content-Length`, sin redirecciones; soportar `Range` es
  deseable para vídeo. El proveedor elegido (§17) cumple estas propiedades con `GET`.
- **Riesgo**: una URL prefirmada para `GET` no autoriza `HEAD` en S3/R2 (la firma incluye el
  método). Si Meta hiciera `HEAD` antes de `GET`, fallaría con `9004`. Se valida en el
  quickstart (paso 1 de la prueba real). Si fallara, la alternativa documentada es un bucket
  R2 público mediante dominio propio con claves aleatorias y borrado inmediato (§17,
  alternativa B), sin cambiar la abstracción.
- **Momento de limpieza**: de forma conservadora, el objeto se mantiene hasta que termina
  `media_publish` (éxito o fallo) o hasta el fallo terminal anterior; nunca se borra entre
  `FINISHED` y `media_publish` porque la documentación no garantiza que Meta no vuelva a
  leerlo. La exposición típica es de segundos (imagen) a pocos minutos (Reel).

---

## 16. Media delivery temporal: seguridad, ciclo de vida y seguridad ante caídas (investigaciones 15 y 16; FR-016a)

**Decision — abstracción genérica** (`media_delivery.py`, sin Instagram):

```text
MediaDeliveryProvider (Protocol)
  name: str
  put(key, source, content_type, size, on_progress) -> None   # crea un objeto PRIVADO
  signed_get_url(key, ttl) -> SecretUrl                         # URL temporal: secreto
  delete(key) -> None                                           # idempotente

TemporaryMediaService
  reserve(attempt_id, content_type, size) -> key      # commit en SQLite ANTES de subir
  upload(key, source, on_progress) -> None
  public_url(key) -> SecretUrl
  release(key) -> bool                                # borrar + marcar; best-effort
  sweep() -> int                                      # limpiar pendientes abandonados
```

**Ciclo de vida a prueba de caídas** (cumple **dos** de las propiedades de FR-016a):

1. `reserve` genera una clave aleatoria no sensible
   `<prefijo>/<uuid4 hex>/<uuid4 hex>.<ext>` (sin rutas ni nombres locales) y confirma una
   fila `temporary_media_objects` **antes** de subir nada → siempre existe una referencia
   recuperable antes de que el recurso exista (propiedad 1).
2. El objeto se sube a un **bucket privado**: sin firma no es accesible. Solo es legible
   mediante una URL prefirmada con caducidad (por defecto **1 h**, máx. del proveedor 7 días)
   que el propio proveedor hace cumplir aunque AutoPublisher muera → la exposición pública
   termina sola (propiedad 2, independiente de AutoPublisher).
3. **Red de seguridad obligatoria del bucket (lifecycle nativo de R2)**: regla de lifecycle
   sobre el **prefijo exclusivo** de AutoPublisher (`key_prefix`, por defecto
   `autopublisher-tmp/`) que borra objetos con más de **1 día** (`Expiration: { Days: 1 }`,
   la granularidad mínima de R2). R2 los elimina *"typically within 24 hours"* tras vencer, por
   lo que el **tiempo máximo documentado** de vida de un objeto huérfano es de **~48 h**
   (1 día + hasta ~24 h de retraso del proveedor). Ver §17 para su configuración.
   - Solo cubre **objetos privados huérfanos** que sobrevivan a todos los mecanismos de
     limpieza de AutoPublisher (`release`, barrido al arrancar y al final de cada intento).
   - **No** sustituye a la limpieza inmediata ni determina cuándo deja de ser pública la URL:
     eso lo hace siempre la caducidad independiente de la URL prefirmada (punto 2).
   - El prefijo es exclusivo de AutoPublisher para no afectar a otros objetos del bucket (se
     recomienda además un bucket dedicado).
   - AutoPublisher no puede comprobar la regla por sí mismo (leer la configuración de
     lifecycle requiere permisos de administración del bucket, mayores que el token
     *Object Read & Write* recomendado), así que se configura en la puesta en marcha y se
     verifica en el quickstart.
4. `release` borra el objeto y marca `deleted_at`; si falla, incrementa `cleanup_failures` y
   el registro queda pendiente.
5. `sweep()` se ejecuta en segundo plano al arrancar (tras la recuperación genérica) y al
   final de cada intento: borra todos los objetos con `deleted_at IS NULL` cuyo intento ya no
   está en ejecución. Así no quedan objetos abandonados aunque falle una limpieza o haya un
   reinicio entre `reserve` y `upload`.

**Seguridad**:

- HTTPS siempre; solo el archivo de ese intento; sin listados ni escritura pública (bucket
  privado, credenciales del proveedor solo en el backend, token del proveedor limitado a
  *Object Read & Write* de ese bucket).
- La URL prefirmada (`SecretUrl`, `repr` oculto) es un **secreto**: solo vive en memoria del
  hilo de ejecución, viaja en el **cuerpo** del `POST` a Meta, nunca se guarda en SQLite,
  nunca llega al frontend ni a mensajes de error. SQLite solo guarda la clave, que sin firma
  no da acceso.
- No contiene tokens de Instagram ni revela rutas locales.
- Redacción de logs: nuevo filtro `RedactMediaDeliverySecrets` en los loggers HTTP y en
  `botocore`/`boto3`/`urllib3` (que se fijan en WARNING) que sustituye `X-Amz-Signature`,
  `X-Amz-Credential`, `X-Amz-Security-Token`, `image_url`, `video_url` y cabeceras
  `Authorization: AWS4-HMAC-SHA256 …`.

---

## 17. Elección del proveedor de media delivery (investigación 15)

Criterios del spec (FR-008) evaluados:

| Criterio | **A. Almacenamiento S3-compatible (Cloudflare R2) con URL prefirmada** | B. Bucket público con dominio propio y claves aleatorias | C. Túnel con nombre (Cloudflare Tunnel) hacia un endpoint local | D. Quick Tunnel / ngrok gratuito | E. Tailscale Funnel |
|---|---|---|---|---|---|
| Fiabilidad programada / horas encendido | Alta: sin sesión que caduque; cada URL se genera en el momento | Alta | Media: depende de un daemon `cloudflared` y de la conexión saliente persistente | Baja: sin garantías, hostname cambia | Media: daemon + función aún orientada a desarrollo |
| Seguridad | Bucket privado; exposición acotada por firma | Objeto público mientras exista (claves impredecibles) | Expone un servidor local a Internet: superficie mayor | Igual que C, sin control | Igual que C |
| Caducidad / crash-safety | Firma caduca sola (proveedor) + lifecycle | Solo lifecycle (≥ 1 día) | Al morir el proceso deja de servir (crash-safe), pero requiere endpoint propio con tokens por archivo | — | ídem C |
| GET/HEAD/Range | GET y Range; HEAD no con firma de GET (riesgo §15) | GET/HEAD/Range | Lo que implemente AutoPublisher | — | ídem |
| Vídeo 300 MB | Sí (PUT único hasta 5 GB) | Sí | Sí, pero sirve desde la máquina local | Límites | Límites de ancho de banda |
| Coste | Free tier 10 GB-mes, egress gratis | Igual + dominio | Gratis, requiere dominio en Cloudflare | Gratis | Gratis |
| Configuración / credenciales | Bucket + token S3 (4 valores) | Bucket + dominio + token | Cuenta, dominio, túnel, daemon y servidor HTTPS local nuevo | Mínima | Cuenta Tailscale + daemon |
| Tras reinicio | Sin estado remoto que reconstruir; barrido de pendientes | Igual | Debe relanzarse el túnel | Nuevo hostname | Relanzar |
| Local-first | Copia remota efímera y privada (minutos) | Copia efímera pero pública | Los archivos no salen salvo a Meta | — | ídem C |

**Decision**: **A — proveedor `s3_compatible`**, con **Cloudflare R2** como opción
recomendada y documentada (cualquier almacenamiento S3-compatible con URLs prefirmadas sirve:
AWS S3, Backblaze B2…). Implementación con **`boto3`** (cliente oficial S3 que Cloudflare
documenta para R2: `endpoint_url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com`,
`region_name="auto"`).

**Rationale**: es la única opción que no exige un servidor público ni un daemon permanente,
funciona igual a las 3 de la madrugada que justo tras arrancar, y cuya exposición termina sola
aunque AutoPublisher muera. El coste para un uso personal es nulo dentro del free tier. La
copia remota es privada, efímera y solo para Meta, lo mínimo compatible con el requisito de
Meta (§15) y con la filosofía local-first.

**Por qué `boto3`**: la firma SigV4 y la subida son código sensible; escribirlas a mano
sería más frágil que usar el cliente oficial. Es la dependencia nueva justificada en
*Complexity Tracking* del plan; para tipado estricto se añade `boto3-stubs[s3]` en dev.

**Alternatives rejected**: B (exposición pública real mientras exista el objeto; queda como
**plan de contingencia** si Meta no aceptara URLs prefirmadas); C y E (añaden un servidor
local expuesto a Internet, un daemon y más configuración; peor fiabilidad para publicaciones
desatendidas); D (Cloudflare documenta: *"Quick Tunnels are for testing and development. For
production, create a Cloudflare Tunnel"*; hostname efímero, sin garantías: prohibido por
FR-009).

**Configuración** (archivo local no versionado, mismo patrón que la Meta App):
`backend/data/media-delivery.json` (sobreescribible con
`AUTOPUBLISHER_MEDIA_DELIVERY_FILE`):

```json
{
  "provider": "s3_compatible",
  "endpoint_url": "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
  "bucket": "<bucket>",
  "region": "auto",
  "access_key_id": "<access key id>",
  "secret_access_key": "<secret access key>",
  "key_prefix": "autopublisher-tmp/",
  "url_ttl_seconds": 3600
}
```

Validación: `endpoint_url` `https`; `bucket` y claves no vacíos; `key_prefix` no vacío,
terminado en `/`, sin `..` ni `/` inicial (debe ser un prefijo exclusivo); TTL entre 900 y
86 400 s. Falta o inválido → `media_delivery_not_configured` (503) en check y preflight. Se
lee en cada operación; nunca se envía al frontend; `.gitignore` añade
`media-delivery*.json`.

**Lifecycle de R2 (obligatorio en la puesta en marcha, §16.3)**: en el panel de Cloudflare →
R2 → bucket → *Settings* → *Object lifecycle rules* → *Add rule*: prefijo exactamente igual a
`key_prefix` (`autopublisher-tmp/`), acción *Delete objects* tras **1 day**; o con la API S3
(credenciales de administración, no las de AutoPublisher):

```json
{"Rules": [{"ID": "autopublisher-temporary-media", "Status": "Enabled",
  "Filter": {"Prefix": "autopublisher-tmp/"},
  "Expiration": {"Days": 1},
  "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}]}
```

La regla de `AbortIncompleteMultipartUpload` limpia también subidas multiparte interrumpidas
(R2 ya las expira por defecto a los 7 días). Otros proveedores S3-compatibles: regla
equivalente de expiración por prefijo.

---

## 18. Clasificación de errores de publicación (FR-047)

El gateway amplía su clasificación sin exponer cuerpos: los números `code`/`error_subcode`
de Graph son enteros no sensibles y se adjuntan a una nueva excepción
`MetaPublishRejected(code, subcode)`.

| Situación | Clasificación | Código público | Determinado |
|---|---|---|---|
| Transporte/timeout, 5xx, 429, Graph 1/2/4/17/32/613 (salvo subcódigos abajo) | temporal | antes de `media_publish`: `instagram_unavailable`; en `media_publish`: no concluyente (§11) | antes: sí; en publish: según §11 |
| Graph 190 | credencial | `instagram_reconnect_required` (+ `Reconnect required`) | sí (antes de publish o rechazo explícito) |
| Graph 10 / 200–299 | permiso | `instagram_reconnect_required` (+ `Reconnect required`) | sí |
| `9/2207042` | cuota | `instagram_publishing_limit_reached` | sí |
| `9004/2207052`, `-2/2207003` | entrega del media | `instagram_media_fetch_failed` | sí |
| `36000–36004`, `352/2207026` | media incompatible | `instagram_media_rejected` | sí |
| `-2/2207020`, container `EXPIRED` **antes** de `media_publish` | caducidad | `instagram_container_expired` | sí |
| `-1/2207032`, otro 4xx al crear | creación | `instagram_container_failed` | sí |
| container `ERROR` **antes** de `media_publish` | procesamiento | `instagram_processing_failed` | sí |
| cualquier estado distinto de `PUBLISHED` **tras** un `media_publish` no concluyente | resultado ambiguo | `instagram_publish_uncertain` | **no** |
| `9007/2207027` en publish | no listo | `instagram_publish_failed` | sí |
| `25/2207050`, `4/2207051` | cuenta restringida | `instagram_account_restricted` | sí |
| Otro 4xx con error Graph en publish | rechazo | `instagram_publish_failed` (tras comprobar container, §11.3) | sí |
| Subida al proveedor fallida | entrega | `media_delivery_failed` | sí |

Reintentos dentro de una ejecución (solo operaciones idempotentes o sin efecto de
publicación, FR-048): subida al proveedor (misma clave, 3 intentos: 2 s, 5 s), consultas de
estado, cuota y permalink (temporales, acotados). **Nunca**: creación de
container y `media_publish`. Sin reintentos entre intentos (Feature 006).

Una credencial invalidada durante la ejecución marca `Reconnect required` con
`mark_reconnect_required` de la Feature 008; los temporales nunca.

---

## 19. Fases internas y progreso (FR-040–FR-042)

**Decision**:

- Etapas **genéricas** de `PublicationAttempt` (neutrales, también útiles para futuras
  plataformas): `preparing` → `uploading` → **`processing`** (nuevo: la plataforma procesa,
  nada publicado) → **`finalizing`** (nuevo: el efecto final irreversible está
  comprometido) → `done`. `final_chunk` sigue existiendo para YouTube. La recuperación
  genérica trata `final_chunk` y `finalizing` como "resultado incierto".
- Fases **específicas** de Instagram en `instagram_publish_runs.phase`:
  `preparing`, `delivering_media`, `creating_container`, `processing_container`,
  `publishing`, `verifying_result`, `succeeded`, `failed`. Sirven para diagnóstico, para el
  preflight del siguiente intento y para la reconciliación.
- **Quién decide determinado/ambiguo**:
  - en la **recuperación genérica al arrancar**, el núcleo decide inicialmente según la
    etapa: interrumpido antes del write-ahead (`finalizing`) → determinado; después →
    ambiguo; sin red ni conocimiento de Instagram;
  - **durante la ejecución** de Instagram y en la **reconciliación** posterior, la lectura de
    solo lectura del container original solo puede resolver hacia `PUBLISHED`;
  - cualquier otro estado tras un `media_publish` no concluyente permanece ambiguo
    (FR-044a).
  El núcleo sigue sin conocer Instagram: solo aplica el resultado que devuelve el publisher.
- Correspondencia: `delivering_media` → `uploading` (bytes reales subidos al proveedor);
  `creating_container`/`processing_container` → `processing`; `publishing`/`verifying_result`
  → `finalizing`.
- API (genérico, todas las plataformas): `attempt_to_read` expone `progress = 1.0` solo si el
  intento está `succeeded`; en cualquier otro estado (`running` o `failed`) expone
  `min(bytes_sent / total_bytes, 0.99)`. YouTube conserva `1.0` al terminar con éxito
  (regresión cubierta por `test_publish_upload.py`).
- Interfaz: el porcentaje solo se muestra en `uploading`; en `processing` y `finalizing` se
  muestra un texto de fase sin porcentaje; 100 % / `Published` solo con el intento
  `succeeded`. La limpieza se muestra aparte como aviso, si lo hubiera.

---

## 20. App Review / Development Mode (investigación 17)

**Hallazgos** (research 008 §15, sin cambios en la documentación): Standard Access (sin App
Review) sirve cuentas propias o gestionadas por quien tiene un rol en la app; Advanced Access
(App Review + Business Verification) es necesario para cuentas de terceros.
`instagram_business_content_publish` es el permiso de publicación y la Feature 008 ya lo
obtuvo con la cuenta tester.

**Decision**: la validación real publica en la cuenta propia (tester/rol) con Standard
Access. Si Meta rechazara la publicación exigiendo App Review/Advanced Access, se documenta y
se detiene la validación; AutoPublisher nunca intenta eludirlo. En Development Mode los posts
son reales y públicos para la cuenta: el quickstart usa contenido inocuo preparado para la
prueba y pide borrarlo manualmente después.
