# Feature Specification: Publicación real de vídeo en TikTok mediante Direct Post (FILE_UPLOAD)

**Feature Branch**: `013-tiktok-direct-post`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Feature 013 — TikTok Publisher & Direct Post. Permitir publicar vídeos reales desde AutoPublisher directamente en la cuenta TikTok conectada (Feature 012) mediante la Content Posting API — Direct Post oficial, con `source = FILE_UPLOAD` desde el archivo local, tanto con `Publish now` como con el scheduler genérico existente. Creator Info obligatorio y reconsultado antes del envío real; UX obligatoria de TikTok (nickname, preview, caption editable, privacy sin valor por defecto, interacciones sin activar por defecto, commercial content disclosure, AIGC explícito, declaración de Music Usage Confirmation y consentimiento expreso, también para publicaciones programadas); cliente no auditado restringido a `SELF_ONLY`; validación local del vídeo sin transcodificar; subida por chunks con `upload_url` tratado como secreto efímero solo en memoria; `publish_id` persistido antes de subir; write-ahead antes del último chunk; polling acotado de estado; `PUBLISH_COMPLETE` sin post ID no es error; resultado ambiguo reconciliado solo con el `publish_id` original; nunca un segundo Direct Post automático. Sin fotos, `PULL_FROM_URL`, R2, verificación de dominio, Upload to Draft, `video.upload`, `video.list`, webhooks, borrado remoto, App Audit, transcoding ni cross-posting."

## Contexto

Desde la Feature 012, una `Account` de plataforma TikTok puede estar vinculada (`Connected`) a
una cuenta TikTok real mediante TikTok Login Kit for Desktop, con access y refresh token solo en
el almacén seguro del sistema operativo, el `open_id` como identidad autoritativa, el permiso
`video.publish` concedido y servicios internos para obtener una credencial válida (renovándola
on-demand), comprobar la identidad vinculada y marcar `Reconnect required`. Todavía no se puede
publicar nada en TikTok.

Desde las Features 006, 007, 009 y 011, AutoPublisher tiene una ejecución de publicaciones
**genérica**: preflight, estados `PUBLISHING` / `PUBLISHED` / `FAILED`, `PublicationAttempt`
con origen (`manual` / `scheduled`), fases genéricas (incluida la fase final irreversible con
write-ahead), progreso, errores seguros, resultado remoto (identificador y enlace opcionales),
resultado determinado/ambiguo, reconocimiento manual antes de reintentar un intento ambiguo, un
punto de extensión neutral de reconciliación de solo lectura, recuperación genérica de intentos
interrumpidos al arrancar y un scheduler local que ejecuta publicaciones programadas y armadas
(consentimiento de publicación automática de la Feature 007). Hoy están registrados los
publishers de YouTube, Instagram y Threads.

Esta feature registra un **publisher de TikTok real** dentro de esa arquitectura genérica, de
modo que una `Publication` de vídeo destinada a una `Account` TikTok conectada pueda publicarse
mediante **Direct Post**:

- manualmente, mediante `Publish now`;
- automáticamente, mediante el scheduler genérico existente;

conservando historial, intentos, progreso, errores y resultado remoto igual que el resto de
plataformas. No se crea un scheduler ni un ejecutor específicos de TikTok, ni se rediseña la
conexión de la Feature 012.

Flujo conceptual:

`Publication` vídeo → revisión TikTok en la interfaz (Creator Info real + opciones obligatorias
elegidas por el usuario + declaración y consentimiento expreso) → preflight genérico + preflight
de TikTok (Creator Info **reconsultado**) → inicializar Direct Post (`FILE_UPLOAD`) → persistir
`publish_id` (commit) → subir los chunks intermedios al `upload_url` (solo en memoria) →
**write-ahead** persistido → enviar el último chunk (inicio del posting process de TikTok) →
consultar el estado del `publish_id` de forma acotada → `PUBLISH_COMPLETE` → `PUBLISHED` /
`FAILED` → fallo determinado / sin conclusión → resultado ambiguo, reconciliable después solo con
el mismo `publish_id`.

Alcance de esta versión: **un único vídeo local por publicación, publicado con Direct Post y
`FILE_UPLOAD`**. Las fotos no se soportan: TikTok solo admite fotos mediante `PULL_FROM_URL`, que
exige un dominio o prefijo de URL propiedad de la app y verificado en TikTok, una dependencia
externa que no se introduce en el MVP del publisher de vídeo.

Principios rectores:

- **Nunca publicar duplicados**: una vez persistido el write-ahead del último chunk,
  AutoPublisher nunca inicializa otro Direct Post para el mismo intento ni repite
  automáticamente la publicación; ante incertidumbre solo consulta el `publish_id` original.
- **Decide el usuario, no AutoPublisher**: privacidad y declaración de IA se eligen
  explícitamente; las interacciones parten desmarcadas y solo el usuario puede activarlas; la
  divulgación comercial parte desactivada; nada se preselecciona ni se sustituye en silencio.
- **El caption y el vídeo del usuario no se transforman**: no se generan hashtags, menciones ni
  textos; no se transcodifica ni se modifica el archivo original.
- **Ningún secreto sale de donde debe**: ni tokens de TikTok ni el `upload_url` aparecen en base
  de datos, logs, respuestas al frontend, almacenamiento del navegador, errores o documentación.
- **Honestidad sobre el entorno**: el cliente actual no está auditado; los posts son privados
  (`SELF_ONLY`) y AutoPublisher no afirma soportar publicación pública de producción.

## Restricciones de la plataforma (documentación oficial de TikTok, consultada 2026-10-14)

Estos hechos condicionan el comportamiento del producto. El plan DEBE reconfirmarlos y fijar los
detalles técnicos (cabeceras, tamaños exactos, clasificación de errores, intervalos) en
`research.md`.

- **Creator Info**: `POST https://open.tiktokapis.com/v2/post/publish/creator_info/query/` con
  `video.publish`; límite **20 peticiones/minuto por access token**. Devuelve
  `creator_avatar_url` (válida 2 h), `creator_username`, `creator_nickname`,
  `privacy_level_options` (cuentas públicas: `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`,
  `SELF_ONLY`; cuentas privadas: `FOLLOWER_OF_CREATOR`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`),
  `comment_disabled`, `duet_disabled` y `stitch_disabled` (los dos últimos son `true` si la cuenta
  es privada o la opción está en "No one") y `max_video_post_duration_sec`. Errores con HTTP 200
  y código distinto de `ok`: `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting`,
  `reached_active_user_cap`; además `access_token_invalid` y `scope_not_authorized` (401),
  `rate_limit_exceeded` (429) y 5xx.
- **Inicialización**: `POST /v2/post/publish/video/init/` con `video.publish`; límite **6
  peticiones/minuto por access token**. `post_info`: `title` (caption, opcional, máximo **2200
  "UTF-16 runes"**; `#` y `@` se reconocen delimitados por espacios o saltos de línea),
  `privacy_level` (obligatorio, debe ser uno de `privacy_level_options`), `disable_comment`,
  `disable_duet`, `disable_stitch`, `video_cover_timestamp_ms` (opcional; sin él, primer
  fotograma), `brand_content_toggle`, `brand_organic_toggle`, `is_aigc` (por defecto `false`; si
  es `true`, TikTok etiqueta el vídeo como "Creator labeled as AI-generated"). `source_info` con
  `source = FILE_UPLOAD`, `video_size`, `chunk_size`, `total_chunk_count`. Respuesta:
  `publish_id` (≤ 64 caracteres) y `upload_url` (≤ 256 caracteres, válido **una hora**; la
  subida debe completarse en ese plazo). Errores documentados: `invalid_param` (400),
  `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting`, `reached_active_user_cap`,
  `unaudited_client_can_only_post_to_private_accounts`, `url_ownership_unverified`,
  `privacy_level_option_mismatch` (403), `access_token_invalid`, `scope_not_authorized` (401),
  `rate_limit_exceeded` (429) y 5xx.
- **Subida (`FILE_UPLOAD`)**: `PUT` al `upload_url` completo (con su query) con `Content-Type`
  (`video/mp4`, `video/quicktime` o `video/webm`), `Content-Length` y
  `Content-Range: bytes {first}-{last}/{total}`. Reglas: archivos **< 5 MB** en un único chunk
  con `chunk_size` = tamaño del archivo; chunks de **5 MB a 64 MB**; archivos > 64 MB en varios
  chunks; el **último chunk puede superar `chunk_size` hasta 128 MB** para absorber el resto;
  `total_chunk_count` = tamaño / `chunk_size` **redondeado hacia abajo**; entre **1 y 1000**
  chunks; envío **secuencial**. Respuestas: `206` chunk aceptado y faltan más; `201` todas las
  partes recibidas y **TikTok inicia el posting process**; `400` cabeceras inválidas o tamaño no
  coincidente; `403` `upload_url` caducado; `404` ninguna subida asociada; `416`
  `Content-Range` no coincide con el progreso real; `5xx` error de gateway/interno: **reintentar
  el mismo chunk**. Las respuestas pueden incluir `Content-Range: bytes 0-{uploaded}/{total}`,
  donde `uploaded` es el **número de bytes aceptados** (siguiente offset), no el índice inclusivo
  del último byte como en la petición (confirmado en V2 real; research §12).
- **Estado**: `POST /v2/post/publish/status/fetch/` con `{"publish_id": ...}`; límite **30
  peticiones/minuto por access token**. Respuesta: `status`, `fail_reason`,
  `publicaly_available_post_id` (con esa grafía; lista de int64; solo para posts **públicos** que
  han pasado moderación), `uploaded_bytes` (solo `FILE_UPLOAD`; la documentación lo describe como
  "1-indexed") y `downloaded_bytes`. Estados aplicables a Direct Post con `FILE_UPLOAD`:
  `PROCESSING_UPLOAD`, `PUBLISH_COMPLETE` (el contenido se ha publicado) y `FAILED`.
  `PROCESSING_DOWNLOAD` es solo de `PULL_FROM_URL` y `SEND_TO_USER_INBOX` solo del flujo Upload;
  la posibilidad de varios posts por `publish_id` se documenta **solo** para el flujo Upload.
  `fail_reason`: `file_format_check_failed`, `duration_check_failed`, `frame_rate_check_failed`,
  `picture_size_check_failed`, `internal` (temporal), `video_pull_failed`,
  `photo_pull_failed`, `publish_cancelled`, `auth_removed`, `spam_risk_too_many_posts`,
  `spam_risk_user_banned_from_posting`, `spam_risk_text`, `spam_risk`. Errores:
  `invalid_publish_id`, `token_not_authorized_for_specified_publish_id` (400),
  `access_token_invalid`, `scope_not_authorized` (401), `rate_limit_exceeded` (429),
  `internal_error` (5xx). La moderación suele tardar menos de un minuto pero puede tardar horas;
  TikTok no garantiza un tiempo máximo de procesamiento.
- **Vídeo**: MP4 (recomendado), WebM o MOV; H.264 (recomendado), H.265, VP8 o VP9; 23–60 FPS;
  ancho y alto entre 360 y 4096 px; tamaño ≤ 4 GB; hasta 10 minutos vía API, limitado además por
  `max_video_post_duration_sec` de la cuenta (3 minutos para todos los creadores, 5 o 10 para
  algunos).
- **Cliente no auditado** (*Content Sharing Guidelines*): todo el contenido publicado queda
  restringido a visibilidad privada; solo puede publicarse con `SELF_ONLY`; la cuenta destino
  **debe ser privada en el momento de publicar**; hasta 5 usuarios pueden publicar en 24 h; todo
  posting está además sujeto a caps de creador y de posts (orientativamente ~15 posts/día por
  cuenta), que son **dinámicos** y no se usan como fuente de verdad.
- **UX obligatoria de Direct Post** (*Content Sharing Guidelines*): obtener Creator Info cada vez
  que se renderiza la página de publicación y mostrar el nickname; si el creador no puede
  publicar, detener e indicar que lo intente más tarde; comprobar la duración contra
  `max_video_post_duration_sec`; caption editable; privacidad en un desplegable **sin opción
  preseleccionada** derivado de `privacy_level_options`; Comment/Duet/Stitch **sin marcar por
  defecto** y en gris si Creator Info los indica deshabilitados; commercial content disclosure
  desactivado por defecto que, al activarse, muestra `Your brand` y `Branded content`
  (seleccionables ambos), con los avisos "Your photo/video will be labeled as 'Promotional
  content'" (solo Your brand) o "… 'Paid partnership'" (Branded content, solo o con Your brand);
  con el toggle activo y ninguna opción marcada, el botón de publicar queda deshabilitado con el
  mensaje "You need to indicate if your content promotes yourself, a third party, or both.";
  **Branded content solo puede ser público o de amigos**: con "only me" se deshabilita Branded
  content (o se cambia la visibilidad avisando, alternativa que **no** se usa aquí) y con
  Branded content marcado se deshabilita "only me" ("Branded content visibility cannot be set to
  private."); antes del botón de publicar, la declaración "By posting, you agree to TikTok's
  Music Usage Confirmation." (sin divulgación o solo Your brand) o "By posting, you agree to
  TikTok's Branded Content Policy and Music Usage Confirmation." (con Branded content), con
  enlaces a las páginas oficiales; preview del contenido; no añadir marcas de agua ni branding;
  **no enviar media a TikTok hasta que el usuario haya consentido expresamente**; avisar de que
  el procesamiento puede tardar unos minutos en aparecer en el perfil; consultar el estado para
  informar al usuario.
- **Intended use y auditoría**: las *Content Sharing Guidelines* indican como **no aceptable**
  para la auditoría "A utility tool to help upload contents to the account(s) you or your team
  manages" y que los clientes deben dirigirse a una audiencia amplia, no a uso interno/privado.

Fuentes: TikTok for Developers — *Content Posting API: Get Started*, *Direct Post API
reference*, *Query Creator Info*, *Media Transfer Guide*, *Get Post Status*, *Content Sharing
Guidelines*.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publicar ahora un vídeo en TikTok con Direct Post (Priority: P1)

Como usuario, quiero revisar en AutoPublisher cómo quedará mi vídeo en TikTok, elegir las
opciones obligatorias, dar mi consentimiento y pulsar `Publish now` para que el vídeo se publique
en mi cuenta TikTok conectada, viendo su estado hasta que TikTok lo confirme.

**Why this priority**: es el camino mínimo que demuestra el flujo completo (Creator Info → init →
`FILE_UPLOAD` → estado → resultado) y el checkpoint temprano de validación real (V1).

**Independent Test**: con fakes de TikTok, crear una publicación de un vídeo pequeño (< 5 MB)
para una `Account` TikTok `Connected`, elegir `SELF_ONLY`, interacciones, AIGC y aceptar la
declaración, ejecutar `Publish now` y comprobar: Creator Info consultado al revisar y de nuevo
antes de inicializar; una única inicialización con `FILE_UPLOAD`; `publish_id` persistido antes
del primer `PUT`; write-ahead persistido antes del único chunk; respuesta `201`; consulta de
estado hasta `PUBLISH_COMPLETE`; publicación `PUBLISHED` e intento `succeeded` con origen
`manual`; `external_id` y `external_url` vacíos si TikTok no devuelve post ID; y ausencia del
`upload_url` y de tokens en base de datos, logs y respuestas de la API.

**Acceptance Scenarios**:

1. **Given** una publicación de vídeo `UNSCHEDULED` o `SCHEDULED` destinada a una `Account`
   TikTok `Connected`, con cuenta y proyecto activos, opciones TikTok completas y consentimiento
   vigente, **When** el usuario pulsa `Publish now` y confirma la declaración, **Then** se
   ejecuta el preflight completo (incluido Creator Info reconsultado) y, si pasa, la publicación
   pasa a `PUBLISHING` con un `PublicationAttempt` de origen `manual`.
2. **Given** la ejecución en curso, **When** se inicializa el Direct Post, **Then** se envía
   `source = FILE_UPLOAD` con el tamaño real del archivo y un plan de chunks válido, y el
   `publish_id` recibido se persiste y confirma (commit) antes de enviar ningún byte; el
   `upload_url` solo existe en memoria.
3. **Given** un vídeo de un único chunk, **When** se va a enviar, **Then** primero se persiste
   el write-ahead y solo después se envía el `PUT`; una respuesta `201` deja la ejecución en
   espera del estado remoto.
4. **Given** que el estado remoto pasa a `PUBLISH_COMPLETE`, **When** se observa, **Then** la
   publicación queda `PUBLISHED` y el intento `succeeded`; si TikTok no devuelve
   `publicaly_available_post_id` (lo normal con `SELF_ONLY`), el resultado no tiene identificador
   ni enlace, no es un error y la interfaz informa de que TikTok no proporciona enlace para posts
   privados.
5. **Given** que TikTok devuelve un post ID público, **When** se persiste el resultado, **Then**
   se guarda como identificador remoto sin construir ningún permalink heurístico.
6. **Given** la ejecución en curso, **When** el usuario la observa, **Then** ve las fases reales
   (las etapas genéricas existentes: preparing, uploading con progreso por bytes confirmados,
   final_chunk y finalizing mientras TikTok procesa, con sus etiquetas de presentación actuales;
   sin estados nuevos) y el aviso de que TikTok puede tardar unos minutos en mostrar el vídeo en su perfil.

---

### User Story 2 - Revisión TikTok con Creator Info y opciones obligatorias (Priority: P1)

Como usuario, quiero ver en una pantalla de revisión la cuenta real que recibirá el vídeo, el
preview, el caption final y elegir yo mismo privacidad, interacciones, divulgación comercial y
declaración de IA, con explicaciones claras cuando algo esté bloqueado.

**Why this priority**: TikTok exige esta UX para Direct Post; sin ella la publicación no es
conforme.

**Independent Test**: con un fake de Creator Info, abrir la revisión de una publicación TikTok y
comprobar: nickname y avatar mostrados; preview del vídeo; privacidad sin valor seleccionado y
con opciones idénticas a `privacy_level_options`; interacciones sin marcar y deshabilitadas
(con motivo) cuando Creator Info lo indica; divulgación comercial desactivada; AIGC sin decidir;
`Publish now` y `Schedule` deshabilitados hasta completar todo y aceptar la declaración.

**Acceptance Scenarios**:

1. **Given** una publicación TikTok, **When** el usuario abre su revisión TikTok, **Then** se
   consulta Creator Info en ese momento y se muestran nickname, avatar si existe, la duración
   máxima permitida y si el creador puede publicar ahora; si no puede (cap, baneo, cupo del
   cliente), se informa y no se permite publicar ni programar.
2. **Given** las opciones de privacidad devueltas por TikTok, **When** se muestra el selector,
   **Then** contiene exactamente esas opciones, ninguna está preseleccionada y `Publish now` /
   `Schedule` siguen deshabilitados hasta que el usuario elija una.
3. **Given** el entorno no auditado, **When** el usuario elige una privacidad distinta de la
   permitida para clientes no auditados (actualmente `SELF_ONLY`), **Then** la combinación se
   marca como no publicable con una explicación; AutoPublisher nunca cambia la privacidad por su
   cuenta.
4. **Given** Creator Info con `duet_disabled` o `stitch_disabled` en `true` (p. ej. cuenta
   privada), **When** se muestran las interacciones, **Then** esos controles aparecen
   deshabilitados, sin marcar (permanecen `false`) y con el motivo; los habilitados aparecen sin
   marcar y el usuario puede activarlos manualmente.
4a. **Given** las tres interacciones desmarcadas, **When** se evalúa si la publicación está
   lista, **Then** desmarcado es un estado válido (`false`): no exige ninguna decisión adicional
   ni bloquea `Publish now` / `Schedule`.
5. **Given** la divulgación comercial activada, **When** no se marca ni `Your brand` ni
   `Branded content`, **Then** no se puede publicar ni programar y se muestra "You need to
   indicate if your content promotes yourself, a third party, or both.".
6. **Given** la privacidad `SELF_ONLY`, **When** el usuario intenta marcar `Branded content`,
   **Then** no puede (o la combinación queda bloqueada) y se explica que el contenido de marca no
   puede ser privado y que el cliente actual solo puede publicar en privado.
7. **Given** la decisión de IA sin tomar, **When** se evalúa la publicación, **Then** no está
   lista; el usuario debe elegir explícitamente `AI-generated: Yes` o `No`.
8. **Given** una publicación de otra plataforma, **When** se abre, **Then** no muestra opciones
   ni revisión de TikTok.

---

### User Story 3 - Caption exacto y validado según la regla de TikTok (Priority: P1)

Como usuario, quiero ver exactamente el caption que se enviará a TikTok, poder editar su
descripción y hashtags antes de publicar y saber si cumple el límite de TikTok contado como lo
cuenta TikTok.

**Why this priority**: el caption es lo que verá el público y no puede truncarse ni alterarse.

**Independent Test**: componer captions con solo descripción, solo hashtags, ambos y ninguno;
con texto ASCII, emojis y caracteres fuera del BMP justo por debajo, en y por encima del límite;
comprobar el texto final, el contador y que el enviado al fake coincide carácter a carácter.

**Acceptance Scenarios**:

1. **Given** descripción y hashtags efectivos, **When** se compone el caption, **Then** es la
   descripción, una línea en blanco y los hashtags; el título genérico de la `Publication` nunca
   se envía.
2. **Given** solo descripción o solo hashtags, **When** se compone, **Then** el caption es ese
   único bloque, sin líneas en blanco sobrantes; si ambos están vacíos, el caption queda vacío y
   no se envía.
3. **Given** un caption que excede el máximo de TikTok según su regla de conteo, **When** se
   revisa, se publica o se programa, **Then** se informa del límite y del valor real; nunca se
   trunca.
4. **Given** una publicación en `PUBLISHING` o `PUBLISHED`, **When** se intenta editar el
   caption u opciones, **Then** se rechaza.

---

### User Story 4 - Validar todo antes de enviar nada a TikTok (Priority: P1)

Como usuario, quiero que cualquier problema detectable se descubra antes de que AutoPublisher
inicialice un Direct Post o envíe un solo byte.

"Antes de enviar nada" significa antes de `video/init/` y de cualquier `PUT`. Durante el
preflight SÍ se permiten: lecturas locales, inspección local del vídeo, obtención/renovación de
la credencial mediante la Feature 012 y la consulta de Creator Info.

**Why this priority**: inicializar un Direct Post consume cupo de peticiones y deja operaciones
remotas huérfanas.

**Independent Test**: para cada condición de preflight, preparar el fallo con fakes y comprobar
que la publicación no pasa a `PUBLISHING`, que no se llamó a `video/init/` y que el usuario ve
un error específico y seguro.

**Acceptance Scenarios**:

1. **Given** cualquiera de estas condiciones: proyecto o cuenta inactivos, cuenta no TikTok,
   conexión no utilizable, credencial no obtenible, `video.publish` no concedido, identidad no
   coincidente, Content inexistente o no vídeo, archivo inexistente, inspección no disponible,
   vídeo incompatible, Creator Info que impide publicar, privacidad no elegida o ya no
   permitida, interacción activada que Creator Info deshabilita, divulgación comercial inválida,
   AIGC sin decidir, consentimiento ausente o caducado, caption inválido, duración mayor que la
   máxima de la cuenta o ejecución ya en curso, **When** se intenta ejecutar, **Then** el
   preflight falla con un error específico, la publicación no pasa a `PUBLISHING` y no se
   inicializa ningún Direct Post.
2. **Given** una comprobación de publicabilidad solicitada solo para mostrar el estado, **When**
   se ejecuta, **Then** nunca llama a `video/init/` ni sube nada.

---

### User Story 5 - Publicación automática programada en TikTok (Priority: P2)

Como usuario, quiero programar una publicación TikTok con todas sus opciones y mi consentimiento
dados en el momento de programar, y que el scheduler genérico la publique a su hora exactamente
una vez, o falle de forma segura si las reglas de TikTok han cambiado.

**Why this priority**: la automatización es el valor principal de AutoPublisher, pero depende
del flujo manual (P1).

**Independent Test**: con reloj inyectable y fakes, programar y armar una publicación TikTok con
consentimiento vigente; avanzar el reloj y comprobar una sola ejecución `scheduled` que
reconsulta Creator Info; repetir con privacidad que deja de estar permitida, duración máxima
reducida, automatización pausada, carrera con `Publish now` y dos ciclos concurrentes.

**Acceptance Scenarios**:

1. **Given** una publicación TikTok con opciones completas, **When** el usuario confirma
   `Schedule` (armado de la Feature 007), **Then** se le muestra la declaración de TikTok y su
   aceptación queda asociada a esa publicación y al contenido exacto consentido; sin ella no
   puede armarse.
2. **Given** una publicación TikTok `SCHEDULED`, armada, con consentimiento vigente y vencida
   dentro de la ventana de la Feature 007, **When** el scheduler hace su ciclo, **Then** la
   ejecuta con el mismo servicio que `Publish now`, origen `scheduled`, reconsultando Creator
   Info y aplicando el preflight completo.
3. **Given** que a la hora programada la privacidad elegida ya no figura en
   `privacy_level_options`, una interacción elegida está ahora deshabilitada, la duración supera
   la nueva máxima o Creator Info impide publicar, **When** se ejecuta el preflight, **Then**
   falla de forma determinada con el comportamiento genérico de la Feature 007, sin modificar las
   opciones guardadas ni recortar el vídeo.
4. **Given** la automatización global en pausa, **When** vence una publicación TikTok armada,
   **Then** no se ejecuta; `Publish now` sigue disponible y una ejecución en curso no se cancela.
5. **Given** un `Publish now` y un ciclo del scheduler sobre la misma publicación, o dos ciclos
   concurrentes, **When** coinciden, **Then** como máximo una ejecución comienza.
6. **Given** que el usuario edita metadata TikTok material tras programar, **When** guarda,
   **Then** el consentimiento previo deja de ser válido y la publicación no puede ejecutarse
   automáticamente hasta reconfirmarlo.

---

### User Story 6 - Nunca publicar un duplicado ante fallos, cortes o reinicios (Priority: P2)

Como usuario, quiero la garantía de que, aunque se corte la red, TikTok no responda o
AutoPublisher se reinicie, nunca aparecerán dos vídeos iguales en mi TikTok por culpa de
AutoPublisher.

**Why this priority**: un post duplicado en una cuenta real es el fallo más grave
(Constitution, principio V).

**Independent Test**: con fakes, interrumpir la ejecución antes de la inicialización, tras
recibir el `publish_id`, durante chunks intermedios, justo después del write-ahead, durante el
último chunk y durante el polling; comprobar estado final, resultado determinado o ambiguo, que
`video/init/` se llama como máximo una vez por intento, que nunca se crea un segundo
`publish_id` automáticamente y que nunca se listan posts.

**Acceptance Scenarios**:

1. **Given** una ejecución interrumpida antes de recibir el `publish_id`, **When** termina o el
   backend se reinicia, **Then** la publicación queda `FAILED` con resultado determinado.
2. **Given** una ejecución con `publish_id` persistido e interrumpida antes del write-ahead del
   último chunk, **When** se reinicia, **Then** queda `FAILED` determinada (interrumpida); no se
   reanuda la subida (el `upload_url` no se conserva) ni se inicializa otro Direct Post.
3. **Given** que AutoPublisher va a enviar el último chunk, **When** lo hace, **Then** antes ha
   confirmado de forma persistente el write-ahead; si no puede persistirlo, no lo envía (fallo
   determinado).
4. **Given** un último chunk cuyo `PUT` no devuelve `201` (timeout, corte, `5xx`, `4xx`,
   respuesta perdida o inesperada), **When** se evalúa, **Then** el último chunk NO se reenvía (se intenta exactamente
   una vez tras el write-ahead) y solo se consulta el estado del `publish_id` original:
   `PUBLISH_COMPLETE` → `PUBLISHED`; `FAILED` → fallo determinado; en procesamiento, error de
   consulta o estado inconcluso → resultado ambiguo (FR-043). Ni siquiera un `uploaded_bytes`
   menor que el total autoriza el reenvío.
5. **Given** un `publish_id` que tras el tiempo máximo de espera sigue en procesamiento, **When**
   se agota, **Then** la publicación queda `FAILED` con resultado ambiguo, no se reintenta
   automáticamente y la interfaz explica que TikTok sigue procesando y que puede volver a
   comprobarse.
6. **Given** una publicación con resultado ambiguo, **When** el usuario consulta la
   comprobación o pulsa `Publish now` (también tras un reinicio: la recuperación genérica
   clasifica el intento localmente y sin red, sin reanudar la subida ni inicializar nada; la
   primera consulta de publish-check o un nuevo `Publish now` reconcilia de forma perezosa),
   **Then** primero se reconcilia en modo lectura el `publish_id` original: `PUBLISH_COMPLETE` → `PUBLISHED`; `FAILED` → fallo
   determinado con su motivo; en otro caso sigue ambigua y un nuevo intento exige que el usuario
   reconozca que ha comprobado en TikTok que no se publicó; el scheduler nunca la reintenta.
7. **Given** una publicación `PUBLISHED`, **When** ocurre cualquier reinicio o ciclo del
   scheduler, **Then** nunca se vuelve a publicar.

---

### User Story 7 - Vídeos grandes en varios chunks (Priority: P3)

Como usuario, quiero publicar vídeos de mayor tamaño sin que AutoPublisher cargue el archivo
entero en memoria ni lo copie, con reintentos acotados ante fallos temporales de un chunk
intermedio.

**Why this priority**: amplía el flujo P1 a archivos reales más grandes; el caso de un chunk ya
demuestra el valor principal.

**Independent Test**: con fakes, subir vídeos que requieren varios chunks; simular `206`, un
`5xx` en un chunk intermedio reintentado con éxito, `416`, `403` (URL caducada) y `404`;
comprobar el `Content-Range` de cada `PUT`, el número total de chunks y que el original no cambia.

**Acceptance Scenarios**:

1. **Given** un vídeo que requiere varios chunks, **When** se sube, **Then** los chunks se envían
   en orden, leídos directamente del archivo original, cada uno con su `Content-Range` correcto,
   y cada `206` avanza el progreso confirmado.
2. **Given** un `5xx` o error de red en un chunk intermedio, **When** ocurre, **Then** se
   reintenta el mismo chunk con número y espera acotados dentro del mismo `publish_id`; si se
   agotan los reintentos, fallo determinado (el último chunk no se envió).
3. **Given** un `403` (URL caducada), `404` o `400` antes del último chunk, **When** ocurre,
   **Then** fallo determinado; no se inicializa otro Direct Post.
4. **Given** un `416`, **When** ocurre antes del último chunk, **Then** se trata según la
   política del plan basada en el progreso confirmado por TikTok, sin enviar bytes fuera de orden
   ni inicializar otro Direct Post.

---

### User Story 8 - Entender los fallos y la pérdida de conexión (Priority: P3)

Como usuario, quiero que cualquier fallo de una publicación TikTok me explique qué ha pasado y
qué puedo hacer, y que una credencial invalidada marque la cuenta para reconexión sin
confundirla con un fallo temporal.

**Why this priority**: mejora la recuperabilidad y la confianza sobre flujos ya cubiertos.

**Independent Test**: con fakes, provocar cada categoría de error y comprobar código seguro,
mensaje, estado de la publicación, estado de la conexión y ausencia de respuestas crudas.

**Acceptance Scenarios**:

1. **Given** `access_token_invalid` o `scope_not_authorized`, **When** ocurre, **Then** se
   aplican los servicios de la Feature 012 (renovación cuando proceda, `Reconnect required`
   cuando corresponda) sin duplicar su lógica.
2. **Given** un rechazo de negocio (`spam_risk_*`, `reached_active_user_cap`,
   `unaudited_client_can_only_post_to_private_accounts`, `privacy_level_option_mismatch`,
   `invalid_param`, `fail_reason` de formato/duración/FPS/tamaño, `auth_removed`), **When**
   ocurre, **Then** fallo determinado con un mensaje comprensible y sin reintento automático.
3. **Given** un error temporal (red, 5xx, `rate_limit_exceeded`), **When** ocurre, **Then** la
   conexión NO pasa a `Reconnect required`.
4. **Given** una publicación `FAILED`, **When** el usuario la consulta, **Then** ve el último
   error, si el resultado está determinado o es ambiguo y el historial de intentos con su origen.

---

### Edge Cases

- **Cuenta TikTok pública con cliente no auditado**: TikTok rechaza la inicialización
  (`unaudited_client_can_only_post_to_private_accounts`): fallo determinado (no se publicó). La
  revisión PUEDE avisar de antemano si Creator Info indica una cuenta pública (opciones sin
  `FOLLOWER_OF_CREATOR`), según decida el plan, sin bloquear por inferencia.
- **`SELF_ONLY` ausente de `privacy_level_options`**: preflight falla; no se elige otra
  privacidad.
- **Opciones de privacidad que cambian entre la revisión y el envío**: manda Creator Info más
  reciente; si la privacidad guardada ya no es válida, fallo determinado sin sustitución.
- **Interacción marcada por el usuario que después Creator Info deshabilita**: preflight falla;
  no se desmarca en silencio.
- **Interacciones deshabilitadas por cuenta privada**: Duet y Stitch aparecen deshabilitados; se
  envían como deshabilitados.
- **Caption con emojis o caracteres fuera del BMP cerca del límite**: se aplica la regla de
  conteo fijada en el plan (FR-030); si TikTok aun así rechaza, fallo determinado.
- **Caption vacío**: se permite; no se envía `title`.
- **Hashtags o menciones**: se envían tal cual los escribió el usuario; AutoPublisher no los
  genera ni los modifica.
- **Vídeo de exactamente 23/60 FPS, 360/4096 px, 4 GB o la duración máxima**: se acepta en el
  límite; por fuera, se rechaza indicando el requisito.
- **FPS variable o metadatos que la inspección no entrega**: el plan decide qué es obligatorio
  localmente y qué se delega a TikTok (FR-022); lo delegado nunca se presenta como validado.
- **Herramienta de inspección no disponible**: el preflight falla con un mensaje claro en lugar
  de publicar a ciegas (patrón de la Feature 003).
- **Archivo modificado o sustituido entre la revisión y el envío**: el consentimiento ligado al
  vídeo deja de ser válido; si cambia entre el preflight y la subida, fallo determinado antes del
  write-ahead.
- **Vídeo < 5 MB**: un único chunk con `chunk_size` igual al tamaño.
- **`upload_url` caducado durante una subida larga**: fallo determinado si ocurre antes del
  write-ahead; el plan DEBE dimensionar la subida para completarse en la hora de validez.
- **Respuesta `201` perdida, `4xx` o `5xx` en el último chunk**: resultado incierto; no se
  reenvía; solo se consulta el `publish_id` original (`PROCESSING_UPLOAD` sigue siendo ambiguo).
- **`PUBLISH_COMPLETE` sin `publicaly_available_post_id`**: `PUBLISHED` sin identificador ni
  enlace; no es error.
- **`FAILED` con `fail_reason = internal` tras el último chunk**: fallo determinado (TikTok
  informa que no se publicó); un nuevo intento solo lo inicia el usuario.
- **Estados no aplicables a Direct Post (`PROCESSING_DOWNLOAD`, `SEND_TO_USER_INBOX`) o
  desconocidos**: respuesta inesperada; nunca se interpretan como éxito; el intento queda
  ambiguo si se había alcanzado el write-ahead.
- **Consulta de estado con `invalid_publish_id` o
  `token_not_authorized_for_specified_publish_id`**: no confirma ni descarta la publicación;
  queda ambigua (si se había alcanzado el write-ahead) con revisión manual.
- **Reconexión con otra cuenta TikTok (otro `open_id`)**: reglas de identidad de la Feature 012;
  el consentimiento ligado a la cuenta anterior deja de ser válido; nunca se publica en otra
  cuenta.
- **Desconexión mientras hay una ejecución en curso**: regla genérica existente (no se permite
  desconectar una cuenta con publicaciones en `PUBLISHING`).
- **Content de imagen destinado a TikTok**: se rechaza en preflight indicando que las fotos no
  están soportadas en esta versión.
- **Avatar de Creator Info caducado (2 h)**: solo se muestra; no se persiste como dato
  autoritativo.

## Requirements *(mandatory)*

### Functional Requirements

#### Alcance e integración con la arquitectura genérica

- **FR-001**: El sistema DEBE registrar un publisher de TikTok en el registro genérico de
  publishers existente, implementando el protocolo real (`check`, `prepare`, `upload`,
  `refresh_details`, `release`, `reconcile`), sin añadir un método `publish`. La publicación
  remota ocurre dentro de `upload`. `release` DEBE ser no-op salvo recursos locales temporales
  realmente creados. `reconcile` DEBE ser de solo lectura respecto al efecto remoto.
- **FR-002**: Solo DEBE poder publicarse en TikTok un **vídeo individual** mediante Direct Post
  con `FILE_UPLOAD`. Publicaciones sin `Content` o con `Content` de imagen DEBEN rechazarse en
  preflight; el publisher NO admite publicaciones solo de texto.
- **FR-003**: El scheduler, el núcleo genérico de publicación y el núcleo de Accounts NO DEBEN
  importar ni contener lógica de TikTok. DEBE existir un test de arquitectura que lo garantice.
- **FR-004**: NO DEBE crearse un scheduler, ejecutor, estado de `Publication` ni modelo de
  intentos específicos de TikTok. Cualquier extensión necesaria de las interfaces genéricas DEBE
  ser neutral y no romper YouTube, Instagram ni Threads.
- **FR-005**: El publisher DEBE reutilizar exclusivamente la conexión y los servicios internos de
  la Feature 012 (credencial válida con renovación on-demand, identidad `open_id`, permisos,
  reglas de `Reconnect required`). NO DEBE introducir otro flujo OAuth, duplicar la lógica de
  renovación ni solicitar nuevos scopes (`video.upload`, `video.list` u otros).
- **FR-006**: El host y la configuración base de la API de TikTok DEBEN proceder de la fuente
  común definida en la Feature 012, sin duplicarse.
- **FR-007**: El publisher NO DEBE usar `PULL_FROM_URL`, el `MediaDeliveryProvider`, Cloudflare
  R2, URLs firmadas ni verificación de dominio, y su preflight NO DEBE exigir configuración de
  media delivery.

#### Creator Info

- **FR-008**: El sistema DEBE consultar Creator Info (a) cuando el usuario abre o refresca la
  revisión TikTok de una publicación y (b) de nuevo durante el preflight inmediatamente anterior
  a la inicialización del Direct Post, tanto en `Publish now` como en ejecuciones programadas.
- **FR-009**: Creator Info NO DEBE cachearse como fuente autoritativa entre publicaciones ni
  entre la revisión y el envío. Si cambia entre ambos momentos, manda la respuesta más reciente y
  la ejecución DEBE fallar de forma segura si las opciones guardadas ya no son válidas.
- **FR-010**: La revisión DEBE mostrar `creator_nickname`, el avatar si existe (solo para
  mostrar, sin persistirlo como dato autoritativo) y si el creador puede publicar ahora. Si
  Creator Info devuelve `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting` o
  `reached_active_user_cap`, DEBE informarse que no puede publicarse ahora y bloquear
  publicación y programación.
- **FR-011**: Una respuesta de Creator Info con forma inesperada (campos ausentes o de tipo
  incorrecto) DEBE tratarse como fallo seguro del preflight; NUNCA DEBEN inventarse valores ni
  usarse valores por defecto en su lugar.
- **FR-012**: Los límites de caps (usuarios activos, posts por día) NO DEBEN codificarse como
  fuente de verdad; solo se usan las señales que devuelve TikTok.

#### Opciones de publicación TikTok

- **FR-013**: Las opciones de TikTok DEBEN persistirse en una estructura propia de TikTok,
  separada del modelo común de `Publication` (mismo patrón que YouTube, Instagram y Threads), con
  al menos: privacidad elegida, permitir comentarios, permitir duet, permitir stitch,
  divulgación comercial activada, `Your brand`, `Branded content`, declaración de IA y el
  registro del consentimiento (FR-024). `Publication` NO DEBE recibir campos de TikTok.
- **FR-014**: **Privacidad**: las opciones mostradas DEBEN derivarse exclusivamente de
  `privacy_level_options`; NO DEBE existir valor por defecto; publicar y programar DEBEN estar
  bloqueados hasta que el usuario elija. Una opción que deje de ser válida NUNCA DEBE sustituirse
  en silencio.
- **FR-015**: **Cliente no auditado**: mientras el cliente no esté auditado, solo DEBE poder
  enviarse la privacidad permitida por TikTok para Direct Post privado (actualmente `SELF_ONLY`).
  Si el usuario elige otra, la combinación DEBE marcarse como no publicable con explicación. Si
  `SELF_ONLY` no figura en `privacy_level_options`, el preflight DEBE fallar. NUNCA DEBE
  cambiarse la privacidad automáticamente. El plan DEBE decidir cómo se representa el estado
  "cliente no auditado" (configuración explícita o regla fija documentada) sin afirmar soporte de
  publicación pública.
- **FR-016**: **Interacciones**: la interfaz DEBE mostrar controles positivos `Allow comments`,
  `Allow duet` y `Allow stitch`, que comienzan desmarcados; `false` es un estado por defecto
  válido y solo el usuario puede activarlos manualmente. NO se exige una decisión explícita
  Yes/No por control (no son tri-estado) y permanecer desmarcados NO bloquea publicar ni
  programar. Si Creator Info indica `comment_disabled`, `duet_disabled` o `stitch_disabled`, el
  control correspondiente DEBE mostrarse deshabilitado, con el motivo, y permanece `false`. Los
  valores DEBEN guardarse con la publicación para el scheduler.
- **FR-017**: El gateway DEBE convertir los controles positivos al contrato de TikTok
  (`disable_comment = not allow_comment`, etc.). DEBEN existir tests que impidan invertir la
  semántica. Una interacción deshabilitada por Creator Info DEBE enviarse como deshabilitada.
- **FR-018**: **Divulgación comercial**: desactivada por defecto. Al activarla se muestran
  `Your brand` (→ `brand_organic_toggle`) y `Branded content` (→ `brand_content_toggle`),
  seleccionables ambos; con la divulgación activa, al menos uno es obligatorio, y en caso
  contrario publicar y programar quedan bloqueados con el mensaje oficial. DEBEN mostrarse los
  avisos de etiquetado oficiales según la combinación ("Promotional content" / "Paid
  partnership").
- **FR-018a**: El request de Direct Post DEBE materializar **siempre** ambos booleanos, con este
  mapeo explícito (`brand_content_toggle` / `brand_organic_toggle`):

  | Selección | `brand_content_toggle` | `brand_organic_toggle` |
  |-----------|------------------------|------------------------|
  | Divulgación OFF | `false` | `false` |
  | Solo `Your brand` | `false` | `true` |
  | Solo `Branded content` | `true` | `false` |
  | Ambos | `true` | `true` |

  Divulgación ON sin ninguna selección nunca llega al request (FR-018), y `Branded content`
  sigue siendo incompatible con `SELF_ONLY` (FR-019). DEBEN existir tests del mapeo. El plan
  reconfirmará la forma real con TikTok.
- **FR-019**: **Branded content y privacidad**: `Branded content` NO DEBE poder combinarse con
  `SELF_ONLY` (TikTok solo lo admite con visibilidad pública o de amigos). En el entorno actual
  no auditado DEBE quedar bloqueado, con la explicación de por qué; NUNCA DEBE cambiarse la
  privacidad automáticamente y una combinación inválida NO DEBE poder publicarse ni programarse.
  `Your brand` se permite con la privacidad elegida mientras las reglas oficiales vigentes lo
  permitan; el plan DEBE reconfirmarlo.
- **FR-020**: **Contenido generado por IA**: DEBE exigirse una elección explícita
  `AI-generated: Yes / No`; sin ella la publicación no está lista para publicar ni programar.
  NUNCA DEBE inferirse. Con `Yes` se envía `is_aigc = true` para que TikTok aplique su etiqueta
  oficial; AutoPublisher NO DEBE añadir texto sobre IA al caption.
- **FR-021**: **Portada**: `video_cover_timestamp_ms` NO se expone ni se envía en esta versión;
  TikTok usa el primer fotograma. Queda registrado como extensión futura.

#### Vídeo

- **FR-022**: Antes de cualquier efecto remoto, el preflight DEBE inspeccionar localmente el
  vídeo reutilizando la inspección de media existente y validarlo contra los requisitos vigentes:
  contenedor (MP4, MOV, WebM), codec (H.264, H.265, VP8, VP9), frame rate (23–60 FPS), ancho y
  alto (360–4096 px), tamaño (≤ 4 GB), duración ≤ `max_video_post_duration_sec` de Creator Info y
  ≤ el límite técnico documentado (10 minutos), y la compatibilidad con las reglas de chunks
  (≤ 1000 chunks). El plan DEBE clasificar explícitamente cada propiedad como: obligatoria
  localmente (falta de dato → rechazo), validada solo si la inspección la entrega, o delegada a
  TikTok. Lo delegado NUNCA DEBE presentarse como validado, y su rechazo por TikTok
  (`fail_reason` de formato, duración, FPS o tamaño de imagen) es un fallo determinado.
- **FR-023**: El sistema NO DEBE transcodificar, recortar ni modificar el vídeo, ni crear copias
  completas del archivo. Los chunks DEBEN leerse del archivo original sin cargarlo entero en
  memoria. El original NUNCA DEBE modificarse.

#### Consentimiento expreso

- **FR-024**: Antes de enviar contenido a TikTok, el usuario DEBE confirmar expresamente la
  declaración oficial vigente correspondiente a su combinación de divulgación comercial
  ("By posting, you agree to TikTok's Music Usage Confirmation." o, con Branded content, "…
  Branded Content Policy and Music Usage Confirmation."), con enlaces a las páginas oficiales:
  - **`Publish now`**: la confirmación forma parte de la acción de publicar: el diálogo de
    `Publish now` DEBE mostrar la declaración vigente y exigir su confirmación expresa en esa
    acción, aunque exista un consentimiento guardado (p. ej. de una programación) con la misma
    huella; esa confirmación vuelve a registrar el consentimiento. Si la huella actual no
    coincide con la consentida, `Publish now` sigue bloqueado hasta reconfirmar.
  - **Programación**: la confirmación DEBE obtenerse cuando el usuario confirma `Schedule` /
    arma la publicación automática, y DEBE quedar asociada a esa publicación. El scheduler NUNCA
    DEBE inventar ni renovar un consentimiento.
- **FR-025**: El consentimiento DEBE ligarse al contenido exacto consentido, incluido el
  **vídeo real** y no solo el registro `Content`. El plan DEBE definir una huella determinista
  que incluya como mínimo: identidad TikTok destino (`open_id`); identidad criptográfica
  (checksum/digest) del archivo de vídeo; caption final; privacidad; interacciones; divulgación
  comercial y sus toggles; declaración de IA; y versión de la declaración aceptada. Una ruta, un
  nombre de archivo, un `content_id`, un tamaño o un mtime, por sí solos, NO bastan para
  identificar el vídeo consentido. Cualquier cambio material posterior (incluido un archivo con
  distinto digest) DEBE invalidar el consentimiento y exigir una nueva confirmación antes de
  publicar o programar, y el preflight DEBE verificar que la huella sigue coincidiendo. El plan
  decidirá cómo reutilizar el checksum existente o calcular/verificar el digest sin modificar ni
  copiar el original. La huella NO DEBE implicar campos TikTok en `Publication`.

#### Caption

- **FR-026**: El caption (`title` de TikTok) DEBE componerse de forma determinista desde la
  descripción efectiva y, si existen, una línea en blanco y los hashtags efectivos formateados
  según el mecanismo de metadata existente; si uno de los dos está vacío, solo el otro, sin
  separadores sobrantes; si ambos están vacíos, no se envía caption. El título genérico de la
  `Publication` NUNCA DEBE enviarse.
- **FR-027**: AutoPublisher NO DEBE autogenerar hashtags, menciones ni texto, ni truncar,
  normalizar o reescribir el caption. El usuario DEBE poder editar la descripción y los hashtags
  antes de publicar mientras la publicación sea editable.
- **FR-028**: La interfaz DEBE mostrar el caption exacto que se enviará, su validez y un contador
  que aplique la misma regla de conteo que la validación del backend.
- **FR-029**: El caption final DEBE validarse antes de cualquier efecto remoto contra el máximo
  vigente (2200 unidades según la definición oficial). Un caption inválido NUNCA DEBE truncarse.
- **FR-030**: El plan DEBE investigar cómo interpretar "2200 UTF-16 runes" y fijar la regla; a
  falta de evidencia en contra, se cuentan **unidades de código UTF-16** (un carácter fuera del
  BMP, como la mayoría de emojis, cuenta 2), interpretación conservadora frente a contar code
  points. NO DEBE usarse un conteo de code points (`len()` de Python) si no representa la regla.
  DEBEN existir tests con ASCII, emojis, secuencias de emoji compuestas y caracteres no BMP.

#### Preflight

- **FR-031**: Antes de cualquier efecto remoto, el sistema DEBE validar como mínimo: publicación
  ejecutable; proyecto y `Account` activos; plataforma TikTok; conexión utilizable; credencial
  válida obtenida mediante la Feature 012; `video.publish` concedido; identidad coincidente;
  `Content` de vídeo; archivo local existente; inspección disponible; formato, codec, FPS,
  dimensiones, tamaño y duración (FR-022); Creator Info real reconsultado; creador habilitado
  para publicar (sin cap, baneo ni cupo del cliente agotado); privacidad elegida y presente en
  `privacy_level_options` y permitida para el cliente no auditado; interacciones compatibles;
  divulgación comercial válida y compatible con la privacidad; AIGC elegido; consentimiento
  vigente para el contenido exacto; caption válido; ninguna ejecución activa; y cualquier
  condición genérica existente.
- **FR-032**: Durante el preflight SÍ se permiten lecturas locales, inspección local, obtención y
  renovación de la credencial mediante la Feature 012 y la consulta de Creator Info. Antes de
  superarlo NO DEBE llamarse a `video/init/` ni enviarse ningún byte. La comprobación local
  (`check`) NO DEBE usar la red, y una consulta de estado de publicabilidad para la interfaz
  NUNCA DEBE inicializar un Direct Post.
- **FR-033**: Las reglas comunes del preflight DEBEN reutilizarse sin duplicarse; si el
  preflight falla, la publicación NO DEBE pasar a `PUBLISHING`.

#### Inicialización y `publish_id`

- **FR-034**: Cada intento DEBE llamar a `video/init/` **como máximo una vez**, con
  `source = FILE_UPLOAD`, el tamaño real del archivo, el `chunk_size` y el `total_chunk_count`
  elegidos por el plan conforme a las reglas vigentes (< 5 MB en un único chunk; chunks de
  5–64 MB; último chunk ≤ 128 MB; recuento por división entera; 1–1000 chunks), y con el
  `post_info` derivado exclusivamente de las opciones consentidas y del Creator Info vigente.
- **FR-035**: El `publish_id` recibido DEBE persistirse y confirmarse (commit) en el estado
  específico de TikTok del intento **antes** de enviar ningún byte. NO DEBE guardarse en campos
  genéricos cuyo significado sea "post remoto". Si no puede persistirse, NO DEBE subirse nada
  (fallo determinado).
- **FR-036**: NUNCA DEBE crearse automáticamente otro `publish_id` para el mismo intento, ni como
  reintento ni para resolver incertidumbre.

#### Subida por chunks y `upload_url`

- **FR-037**: El `upload_url` DEBE tratarse completo como **secreto efímero**: existe solo en
  memoria durante el intento y NUNCA DEBE persistirse (base de datos ni ningún otro
  almacenamiento), registrarse en logs, incluirse en errores o excepciones registradas,
  enviarse al frontend, guardarse en el navegador ni aparecer en documentación. El redactor de
  logs DEBE cubrir las URLs de subida de TikTok completas.
- **FR-038**: Los chunks DEBEN enviarse secuencialmente al mismo `upload_url`, cada uno con
  `Content-Type` adecuado al contenedor, `Content-Length` y `Content-Range` correctos. `206`
  avanza al siguiente chunk; `201` en el último chunk indica que TikTok ha recibido todo e
  iniciado el posting process. El progreso visible DEBE basarse en bytes confirmados.
- **FR-039**: Un `5xx` o error de red en un **chunk intermedio** PUEDE reintentarse con el mismo
  chunk, dentro del mismo `publish_id` y `upload_url`, con número y espera acotados definidos en
  el plan. Agotados los reintentos, o ante `400`, `403` (URL caducada) o `404`, la ejecución DEBE
  fallar de forma determinada (el último chunk no se envió). El plan DEBE fijar la política ante
  `416` usando el progreso confirmado por TikTok en el `Content-Range` de la respuesta, sin
  enviar bytes fuera de orden: solo se avanza con evidencia inequívoca de que TikTok ya aceptó el
  chunk intermedio enviado (el "final del chunk" en la respuesta es `last_byte + 1`, porque
  cuenta bytes aceptados); el último chunk nunca se reintenta y un `416` nunca crea un segundo
  Direct Post. `uploaded_bytes` del estado es solo diagnóstico.
- **FR-040**: La subida DEBE dimensionarse para completarse dentro de la validez del
  `upload_url` (una hora); el plan DEBE definir el comportamiento si se prevé o detecta que no
  será así.

#### Punto irreversible (write-ahead) y anti-duplicados

- **FR-041**: El envío del último chunk es el punto irreversible. Antes de enviarlo, el sistema
  DEBE persistir y confirmar el write-ahead mediante el mecanismo genérico existente (fase final
  irreversible) más el estado específico de TikTok. En vídeos de un único chunk el write-ahead
  precede a ese único `PUT`; en vídeos multi-chunk, inmediatamente antes del último. Si no puede
  confirmarse, el último chunk NO DEBE enviarse (fallo determinado).
- **FR-042**: Antes del write-ahead, una interrupción en la que se sabe que el último chunk
  nunca se envió DEBE clasificarse como fallo determinado (interrumpido). NO DEBE inventarse una
  reanudación si se perdió el `upload_url`, ni persistirse el `upload_url` para facilitarla.
- **FR-043**: Tras el write-ahead, el último chunk DEBE intentarse **exactamente una vez** y
  NUNCA DEBE reenviarse automáticamente, ni tras timeout, error de red, `5xx`, `4xx` o
  respuesta perdida o inesperada. Ninguna respuesta HTTP del último `PUT` salvo `201` permite
  concluir por sí sola nada sobre el efecto remoto (en particular, un `4xx` no prueba que no se
  publicó). Cualquier resultado distinto de `201` o un reinicio DEBE considerarse
  potencialmente ambiguo y resolverse solo consultando el estado del `publish_id` original:
  `PUBLISH_COMPLETE` → éxito; `FAILED` → fallo determinado; en procesamiento, error de consulta
  o estado inconcluso → resultado ambiguo. El sistema NUNCA DEBE crear un nuevo `publish_id`,
  inicializar un segundo Direct Post, reenviar el último chunk ni listar posts. `uploaded_bytes`
  sigue siendo útil para el progreso, los chunks intermedios y el diagnóstico/reconciliación,
  pero NO es prueba suficiente para repetir el punto irreversible. Los reintentos acotados de
  chunks **intermedios** ante `5xx`/red (FR-039) se mantienen.
- **FR-044**: Para resolver incertidumbre NUNCA DEBEN listarse posts del usuario, inferirse la
  publicación por posts recientes ni solicitarse `video.list`; la única fuente es el estado del
  `publish_id` original.

#### Estado, polling y resultado

- **FR-045**: Tras el `201` del último chunk, o tras cualquier otro resultado del último chunk
  después del write-ahead, el sistema DEBE consultar el estado del `publish_id` de forma progresiva y acotada (intervalo creciente y
  tiempo máximo definidos en el plan), claramente por debajo del límite de 30 peticiones/minuto
  por token, sin espera activa continua y respetando el cierre ordenado de la aplicación.
- **FR-046**: Interpretación del estado para Direct Post `FILE_UPLOAD`:
  - `PUBLISH_COMPLETE` → publicación confirmada.
  - `FAILED` → fallo remoto determinado; `fail_reason` DEBE persistirse como valor seguro y
    estructurado y traducirse a un mensaje comprensible.
  - `PROCESSING_UPLOAD` al agotar el tiempo máximo → resultado **ambiguo** pendiente de
    reconciliación, sin reintento automático, cualquiera que fuera la respuesta HTTP del último
    `PUT` (un `4xx` previo no lo convierte en fallo determinado).
  - Error de la consulta de estado o respuesta inesperada tras el write-ahead → ambiguo.
  - Estados de otros modos (`PROCESSING_DOWNLOAD`, `SEND_TO_USER_INBOX`) o desconocidos →
    respuesta inesperada, nunca éxito; ambiguo si se había alcanzado el write-ahead.
- **FR-047**: Con `PUBLISH_COMPLETE`, la publicación DEBE quedar `PUBLISHED` y el intento
  `succeeded`. Si TikTok devuelve `publicaly_available_post_id` con un valor inequívoco, se
  persiste como identificador remoto (`external_id`); si no, `external_id` y `external_url`
  quedan vacíos, sin que sea un error. NUNCA DEBE inventarse un ID ni construirse un permalink
  heurístico, y el enlace "abrir en TikTok" solo se muestra si existe una URL oficial conocida
  (no la hay en esta versión).
- **FR-048**: `refresh_details` NO DEBE solicitar `video.list` ni listar posts para obtener
  enlaces; como mucho re-lee el estado del mismo `publish_id`.

#### Reconciliación, reinicios y recuperación

- **FR-049**: `reconcile` DEBE consultar únicamente el `publish_id` original en modo lectura:
  `PUBLISH_COMPLETE` → `PUBLISHED`; `FAILED` → fallo determinado con su motivo (sin exigir el
  reconocimiento manual de no publicación); en procesamiento, error de consulta o respuesta
  inconclusa → sigue ambigua. NUNCA DEBE inicializar un Direct Post ni volver a subir el vídeo.
  Si el punto de extensión genérico actual solo admite confirmar éxitos, el plan DEBE extenderlo
  de forma neutral para admitir "la plataforma confirma que no se publicó", sin romper el resto
  de publishers.
- **FR-050**: Una publicación con resultado ambiguo NUNCA DEBE reintentarse automáticamente
  (tampoco por el scheduler). Antes de exigir el reconocimiento manual, el sistema DEBE intentar
  la reconciliación (FR-049); si no se resuelve, un nuevo intento manual DEBE requerir que el
  usuario reconozca explícitamente que ha comprobado en TikTok que el vídeo no se publicó
  (modelo de las Features 006/009/011).
- **FR-051**: Al arrancar, la recuperación genérica DEBE seguir aplicándose sin red y sin lógica
  de TikTok en el núcleo: ninguna ejecución se reanuda; sin `publish_id` → `FAILED` determinada;
  con `publish_id` y sin write-ahead → `FAILED` determinada (interrumpida); con write-ahead →
  ambigua, resoluble después solo mediante la reconciliación de FR-049.

#### Errores, reintentos y conexión

- **FR-052**: Los errores DEBEN clasificarse al menos en:
  - **Autenticación/autorización** (`access_token_invalid`, `scope_not_authorized`,
    `auth_removed`): integrados con la Feature 012 (renovación cuando proceda,
    `Reconnect required` cuando corresponda), sin duplicar su lógica.
  - **Rechazo de negocio determinado** (`invalid_param`, `privacy_level_option_mismatch`,
    `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting`,
    `reached_active_user_cap`, `unaudited_client_can_only_post_to_private_accounts`,
    `fail_reason` de formato/duración/FPS/tamaño, `spam_risk_text`, `spam_risk`,
    `publish_cancelled`): sin reintento automático.
  - **Temporales** (red, timeout, 5xx, `rate_limit_exceeded`, `fail_reason = internal`): solo se
    reintentan donde no hay efecto de publicación (Creator Info en preflight, chunks intermedios,
    consultas de estado), con número y espera acotados; antes del write-ahead terminan en fallo
    determinado y después en ambigüedad o en el resultado que TikTok confirme.
  - **Resultado ambiguo** e **interrumpido**.
- **FR-053**: Un error temporal posterior al punto irreversible NUNCA DEBE transformarse en un
  nuevo Direct Post automático. Los errores temporales NO DEBEN cambiar el estado de conexión.
- **FR-054**: Los errores DEBEN seguir el formato estructurado existente con códigos estables y
  seguros que distingan al menos: TikTok no conectado, reconexión requerida, permiso ausente,
  creador no puede publicar (cap/baneo/cupo), cliente no auditado/cuenta no privada, privacidad
  no elegida o no válida, combinación de divulgación inválida, AIGC sin decidir, consentimiento
  ausente o caducado, vídeo incompatible (con el requisito concreto), duración superior a la
  máxima de la cuenta, caption inválido, límite de peticiones/temporal, inicialización fallida,
  subida fallida, URL de subida caducada, procesamiento fallido (con motivo), procesamiento sin
  concluir, resultado ambiguo y ejecución interrumpida. NUNCA DEBEN devolverse respuestas crudas
  de TikTok.

#### Persistencia específica de TikTok

- **FR-055**: Las opciones de TikTok (FR-013) y el estado de cada ejecución DEBEN persistirse en
  estructuras propias de TikTok mediante migraciones versionadas. El estado de ejecución
  (**TikTok Publish Run**) DEBE incluir como mínimo: publicación e intento, `publish_id`,
  metadata de subida no sensible (tamaño total, `chunk_size`, número de chunks, bytes
  confirmados), fase específica, momento del write-ahead del último chunk, último estado remoto,
  `fail_reason` seguro y timestamps. NUNCA DEBE contener `upload_url`, tokens ni respuestas
  crudas.

#### Scheduler, pausa y concurrencia

- **FR-056**: Las publicaciones TikTok DEBEN ejecutarse con el ejecutor genérico: origen
  `manual` para `Publish now` y `scheduled` para el scheduler. Pausa global, protección frente a
  carreras manual/scheduler, ciclos concurrentes y concurrencia máxima existentes DEBEN
  reutilizarse sin añadir lógica de TikTok al scheduler.
- **FR-057**: Una publicación TikTok solo DEBE poder armarse para publicación automática si
  tiene caption válido, privacidad elegida, interacciones compatibles con Creator Info
  (desmarcadas es válido), divulgación comercial válida,
  AIGC elegido y consentimiento vigente (FR-024/FR-025). Al ejecutarse, el scheduler DEBE
  reconsultar Creator Info y aplicar el preflight completo; si las reglas han cambiado, fallo
  determinado sin modificar las opciones.

#### API e interfaz

- **FR-058**: La API DEBE permitir: consultar Creator Info de la cuenta destino para la
  revisión (sin efectos remotos de publicación); consultar y editar las opciones de TikTok;
  consultar el caption final con su conteo y validez; registrar el consentimiento al publicar o
  programar; y exponer intentos, fases, progreso, errores y resultado remoto mediante los
  endpoints genéricos existentes. Ninguna respuesta DEBE incluir tokens ni `upload_url`; el
  `publish_id` no DEBE exponerse al frontend salvo que aporte valor diagnóstico justificado en el
  plan.
- **FR-059**: Para una publicación TikTok de vídeo, la interfaz DEBE mostrar, integrada con los
  componentes existentes y sin rediseño: nickname y avatar de Creator Info; preview del vídeo;
  caption editable (descripción y hashtags) con su resultado y contador TikTok; desplegable de
  privacidad sin valor por defecto; `Allow comments`, `Allow duet`, `Allow stitch`; divulgación
  comercial con `Your brand` / `Branded content` y sus avisos; `AI-generated: Yes / No`; la
  declaración con enlaces y su confirmación; `Publish now` y `Schedule`; el motivo de cualquier
  opción o acción deshabilitada; el aviso de entorno no auditado (solo `SELF_ONLY`, cuenta
  privada); el aviso de que el procesamiento puede tardar unos minutos; progreso por fases
  reales; errores; e historial de intentos.

#### Seguridad, documentación y calidad

- **FR-060**: Se DEBEN mantener todas las garantías de seguridad de las Features 005–012. NUNCA
  DEBEN persistirse, registrarse ni exponerse: access token, refresh token, client secret,
  cabecera `Authorization`, `upload_url` (ni su query o token de subida) ni respuestas crudas que
  los contengan. NO DEBE almacenarse media binaria adicional. DEBEN existir tests que verifiquen
  su ausencia en base de datos, logs, respuestas de la API y almacenamiento del navegador.
- **FR-061**: La documentación (README y `quickstart.md`) DEBE explicar la publicación de vídeo
  en TikTok con Direct Post, las opciones obligatorias, el consentimiento, el entorno no
  auditado (`SELF_ONLY`, cuenta privada, caps dinámicos), la ausencia de enlace en posts
  privados, el tratamiento de resultados ambiguos y, como **riesgo de producto**, que TikTok
  considera actualmente no aceptable para la auditoría pública una utilidad limitada a gestionar
  las cuentas propias o del equipo; ese riesgo no bloquea el desarrollo privado actual y
  AutoPublisher no intenta sortear estas reglas.
- **FR-062**: Los tests automatizados DEBEN ejecutarse offline, sin TikTok real ni keyring real,
  con fakes, y cubrir como mínimo: Creator Info (opciones de privacidad, nickname, duración
  máxima, interacciones deshabilitadas, spam/caps, respuesta inesperada); vídeo (formatos,
  codecs, límites de FPS y dimensiones, tamaño, duración, inspección ausente o incompleta,
  original inmutable); caption (descripción, hashtags, ambos, vacíos, límite, UTF-16/emoji);
  opciones (privacidad sin defecto, privacidad obsoleta, interacciones y su semántica,
  deshabilitadas, divulgación comercial, incompatibilidad de Branded content con `SELF_ONLY`,
  AIGC explícito, invalidación del consentimiento); subida (un chunk, multi-chunk, `206`, `201`,
  `Content-Range`, reintento de chunk intermedio por `5xx`, URL caducada, `416`, ambigüedad del
  último chunk sin ningún reenvío; mapeo de `brand_content_toggle` / `brand_organic_toggle`;
  invalidación del consentimiento por cambio de digest del vídeo); anti-duplicados (commit del `publish_id`, write-ahead antes del último chunk,
  interrupción antes y después, timeout final, `PUBLISH_COMPLETE`, `FAILED`, procesamiento
  agotado, reconciliación, ningún segundo `publish_id`, ningún listado de posts); scheduler
  (programada, pausa/reanudación, carrera manual/scheduler, ciclos concurrentes, preflight
  cambiado, ambigüedad que bloquea el reintento); seguridad (`upload_url` y credenciales
  ausentes, sin R2, arquitectura); y regresión (YouTube, Instagram, Threads, conexión TikTok de
  la Feature 012, núcleo y scheduler neutrales).

#### Validación real por etapas y stop conditions

- **FR-063**: **Checkpoint V1 (temprano, tras el publisher mínimo de vídeo)**: con la cuenta
  TikTok ya conectada y un vídeo inocuo y corto, `quickstart.md` DEBE validar contra TikTok real
  (Sandbox / cliente no auditado): que la cuenta destino es adecuada (privada) para el cliente no
  auditado; Creator Info real; presencia de `SELF_ONLY`; duración máxima; flags de interacción;
  `video/init/` con `FILE_UPLOAD`; reglas de chunks; subida completa de un vídeo pequeño; forma
  real del `upload_url` (sin registrarlo); respuestas reales de chunk; estados observados;
  `PUBLISH_COMPLETE`; semántica real de `uploaded_bytes`; y presencia o ausencia de
  `publicaly_available_post_id`. Si algo contradice el diseño, DEBE detenerse antes de construir
  scheduler, recuperación avanzada y opciones avanzadas.
- **FR-064**: **Checkpoint V2 (final)**: DEBE validar scheduler real, pausa/reanudación,
  multi-chunk si es razonable con un vídeo inocuo, reinicio y reconciliación, anti-duplicados,
  divulgación comercial y AIGC (si se decide probarlo) y seguridad. Los posts de prueba serán
  privados y DEBE indicarse borrarlos manualmente en TikTok; no se implementa borrado remoto. NO
  DEBEN provocarse deliberadamente resultados ambiguos en la cuenta real.
- **FR-065**: La implementación y la validación DEBEN detenerse y revisarse spec/plan si: la
  cuenta o el cliente no permiten Direct Post privado como se espera; Creator Info real
  contradice el contrato; `SELF_ONLY` no puede seleccionarse; `FILE_UPLOAD` contradice las reglas
  documentadas; el `upload_url` o las respuestas de chunk tienen forma incompatible;
  `PUBLISH_COMPLETE` no significa lo esperado; los posts privados requieren información o
  permisos no contemplados; TikTok exige dominio o `PULL_FROM_URL` para vídeo local; se necesita
  `video.upload` o `video.list`; se requiere App Audit para el Direct Post privado; aparece algún
  secreto en base de datos, logs, API o frontend; o no puede garantizarse el anti-duplicado tras
  el último chunk. NO DEBEN ampliarse scopes ni introducirse workarounds sin esa revisión.

### Key Entities *(include if feature involves data)*

- **TikTok Publication Options**: opciones específicas de TikTok de una `Publication` TikTok,
  separadas del modelo común: privacidad elegida (sin valor por defecto), permitir comentarios,
  duet y stitch (booleanos, `false` por defecto, activables solo por el usuario), divulgación
  comercial activada (`false` por defecto), `Your brand`, `Branded content`, declaración de IA
  (sin decidir / sí / no) y registro del consentimiento (momento, versión de la declaración y
  huella determinista del contenido consentido, incluido el digest del vídeo real, FR-025).
- **Caption TikTok**: valor derivado y determinista (no un campo editable nuevo): descripción
  efectiva y, si existen, una línea en blanco y los hashtags efectivos (FR-026).
- **Creator Info**: lectura efímera de TikTok sobre la cuenta destino (nickname, avatar,
  opciones de privacidad, interacciones deshabilitadas, duración máxima, capacidad de publicar);
  no se persiste como fuente autoritativa.
- **TikTok Publish Run**: estado remoto de TikTok de un intento: `publish_id`, plan de subida no
  sensible, bytes confirmados, fase, momento del write-ahead del último chunk, último estado
  remoto, `fail_reason` seguro y timestamps. Nunca contiene el `upload_url` ni credenciales.
- **Upload URL**: secreto efímero devuelto por la inicialización; existe solo en memoria durante
  el intento.
- **PublicationAttempt** (existente): se reutiliza con origen, fases, progreso, error, resultado
  determinado/ambiguo y resultado remoto (identificador opcional, sin enlace en esta versión).
- **Publication** (existente): no recibe campos de TikTok; el armado de publicación automática de
  la Feature 007 se complementa con el consentimiento TikTok guardado en sus opciones.
- **TikTok Connection** (existente, Feature 012): fuente de la credencial, la identidad
  (`open_id`) y los permisos; sin cambios de modelo salvo lo necesario para marcar
  `Reconnect required`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El usuario puede completar el flujo real de `quickstart.md` (revisión TikTok →
  opciones → consentimiento → `Publish now` → `PUBLISH_COMPLETE`) con un vídeo inocuo en su cuenta
  TikTok privada sin editar archivos de datos ni la base de datos a mano.
- **SC-002**: Una publicación TikTok programada, armada y con consentimiento vigente se publica
  exactamente una vez mediante el scheduler genérico en la validación real y en el 100 % de los
  tests de concurrencia.
- **SC-003**: 0 posts duplicados en todos los escenarios de fallo, corte e interrupción
  simulados: como máximo una inicialización de Direct Post por intento y 0 inicializaciones
  automáticas tras el write-ahead.
- **SC-004**: En el 100 % de los fallos de preflight no se inicializa ningún Direct Post ni se
  envía ningún byte.
- **SC-005**: En el 100 % de las revisiones, ninguna privacidad ni declaración de IA aparece
  preseleccionada, las interacciones aparecen desmarcadas y la divulgación comercial
  desactivada; publicar/programar permanece bloqueado hasta que el usuario elija privacidad y
  declaración de IA y acepte la declaración, sin que las interacciones desmarcadas lo bloqueen.
- **SC-006**: El 100 % de los cambios materiales tras el consentimiento lo invalidan, y 0
  ejecuciones (manuales o programadas) ocurren sin un consentimiento vigente para el contenido
  exacto enviado.
- **SC-007**: El caption mostrado coincide en el 100 % de los casos con el enviado, 0 captions se
  truncan o alteran, y el contador coincide con la validación del backend en todos los casos de
  prueba (ASCII, emoji y no BMP).
- **SC-008**: Base de datos, logs, errores, respuestas de la API y almacenamiento del navegador
  contienen 0 tokens de TikTok y 0 URLs de subida.
- **SC-009**: 0 identificadores o enlaces de TikTok inventados: con `PUBLISH_COMPLETE` sin post
  ID, la publicación queda `PUBLISHED` sin identificador ni enlace en el 100 % de los casos.
- **SC-010**: El 100 % de los archivos originales permanecen idénticos byte a byte y ningún
  vídeo se transcodifica ni se copia completo.
- **SC-011**: 0 errores temporales provocan `Reconnect required`; cada error de FR-054 produce un
  mensaje comprensible que indica qué hacer y si el resultado está determinado o requiere
  revisión.
- **SC-012**: La suite de la feature se ejecuta sin Internet ni servicios reales; scheduler,
  núcleo de publicación y núcleo de Accounts no contienen referencias a TikTok; el publisher de
  TikTok no usa media delivery.
- **SC-013**: YouTube, Instagram, Threads y la conexión de TikTok siguen funcionando sin cambios
  de comportamiento (suites existentes en verde).

## Assumptions

- **Alcance**: solo vídeo individual con Direct Post y `FILE_UPLOAD`. Quedan fuera: Photo Direct
  Post, carruseles de fotos, `PULL_FROM_URL`, verificación de URL/dominio, Upload to Draft /
  inbox, `video.upload`, `video.list`, webhooks, borrado remoto, analytics, comentarios, APIs de
  moderación, publicación pública/auditada, App Audit, transcoding, música, ubicación, stickers,
  efectos, sonidos, portada personalizada (`video_cover_timestamp_ms`), rediseño de UI y
  cross-posting (Feature 014).
- **Entorno**: cliente TikTok no auditado (Sandbox de la Feature 012), con la cuenta TikTok del
  usuario como target user, configurada como **privada** en el momento de publicar, y posts
  `SELF_ONLY` que el usuario borra manualmente tras las pruebas. AutoPublisher encendido a la hora
  de las publicaciones programadas.
- **Un `publish_id` de Direct Post produce como máximo un post**: la documentación solo describe
  varios posts por `publish_id` para el flujo Upload; se confirma en V1.
- **Rate limits por token** (init 6/min, Creator Info 20/min, estado 30/min): suficientes para un
  único usuario local; el plan los respeta sin construir un sistema de cuotas.
- **Riesgo de producto documentado**: TikTok indica que "A utility tool to help upload contents
  to the account(s) you or your team manages" no es un intended use aceptable para la auditoría
  pública; la publicación pública de producción no está garantizada para AutoPublisher.
- **Decisiones diferidas al plan** (verificadas en documentación oficial vigente): `chunk_size`
  y algoritmo de división; política de reintentos de chunks intermedios y de `416`; semántica
  de `uploaded_bytes` (sin uso para reenviar el último chunk); intervalos y tiempo máximo del
  polling; clasificación de propiedades del vídeo (FR-022); regla exacta de conteo del caption;
  representación del cliente no auditado, del consentimiento y su huella (incluido el digest
  del vídeo y la reutilización del checksum existente); extensión neutral de
  la reconciliación para "no publicado confirmado"; esquema exacto de opciones y publish runs;
  nombres de códigos de error y fases (reutilizando los genéricos); si se avisa en la revisión
  de una cuenta pública.
- **Precedentes reutilizados**: confirmación de `Publish now`, preflight, estados, write-ahead,
  reconocimiento manual ante resultado ambiguo y recuperación de intentos interrumpidos
  (Features 006/009/011); elegibilidad, armado, ventana, pausa y concurrencia (Feature 007);
  opciones por plataforma, declaración de IA explícita y resultado sin identidad remota
  (Features 006/009/011); credencial, identidad y permisos (Feature 012).
- **Dependencias**: Content y su inspección de media (Feature 003), `Publication` y metadata
  efectiva (Feature 004), ejecución genérica y `PublicationAttempt` (Feature 006), scheduler
  (Feature 007), conexión TikTok (Feature 012), formato de errores, redactor de logs y
  migraciones existentes.
