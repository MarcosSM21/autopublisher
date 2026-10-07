# Research: publicación manual real de vídeos en YouTube

**Feature**: `006-youtube-manual-publishing` | **Fecha**: 2026-10-07

Decisiones de la Fase 0. Cada una indica qué se elige, por qué y qué alternativas se
descartaron. Los datos de YouTube se han verificado el 2026-10-07 contra la documentación
oficial:

- `videos.insert`: <https://developers.google.com/youtube/v3/docs/videos/insert>
- recurso `videos`: <https://developers.google.com/youtube/v3/docs/videos>
- protocolo resumible:
  <https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol>

---

## 1. Arquitectura de ejecución: preflight síncrono + hilo en segundo plano + sondeo

**Decisión**:

1. `POST /api/publications/{id}/publish` ejecuta **de forma síncrona** el preflight completo,
   incluidas las comprobaciones que necesitan red (credenciales válidas y canal efectivo,
   timeout de 10 s ya existente).
2. Si pasa, en **una única transacción**: transición condicional a `publishing` y creación
   del `PublicationAttempt` en estado `running` (§8).
3. Lanza la subida en un **hilo daemon** gestionado por un `PublicationRunner` que vive en
   `app.state`, y responde `202 Accepted` con la publicación ya en `publishing`.
4. La interfaz **sondea** `GET /api/publications/{id}` cada 2 s mientras el estado sea
   `publishing` (la Queue sondea su listado mientras alguna lo esté).

El `PublicationRunner` expone `start(attempt_id, prepared, publisher)` y no depende de FastAPI ni
de la petición HTTP: el futuro scheduler podrá llamar a la misma función de servicio
`start_publication(...)` (preflight + transición + `runner.start`) sin pasar por la API
(FR-013).

**Razón**:

- Los endpoints del proyecto son síncronos (`def`, threadpool). Un hilo propio por ejecución
  es el mecanismo más simple que no bloquea el navegador durante toda la subida (FR-012).
- El preflight síncrono permite devolver los errores evitables (cuenta a reconectar, canal
  distinto, metadata inválida) como respuesta HTTP normal, **sin** pasar nunca por
  `publishing` (FR-015).
- Sondeo HTTP cada 2 s: mismo patrón que el sondeo de intentos OAuth de la Feature 005;
  cumple SC-002 (progreso cada ≤ 5 s).

**Alternativas descartadas**:

- `BackgroundTasks` de FastAPI: se ejecuta tras la respuesta pero ligado al ciclo de la
  petición y sin control de parada ni de "trabajos vivos".
- `ThreadPoolExecutor`: sus hilos no son daemon y el apagado esperaría a subidas de varios
  minutos; no aporta nada frente a hilos daemon con registro propio.
- Cola persistente / worker separado / Celery: infraestructura excluida por la Constitution.
- WebSocket / SSE para el progreso: más complejo que el sondeo y sin beneficio real para un
  único usuario local.

## 2. Interfaz común de publishers (primer adaptador real)

**Decisión**: introducir en `app/publishing.py` un `Protocol` mínimo y un registro por
plataforma:

```text
Publisher (Protocol)
  check(session, publication, ctx) -> PublishCheck                 # local, sin red
  prepare(session, publication, ctx) -> PreparedPublication         # preflight completo, con red
  upload(prepared, reporter, ctx) -> PublishOutcome                 # ejecución real (hilo)
  refresh_details(prepared, outcome, ctx) -> PublishOutcome         # comprobación ligera

PublishContext        = session_factory + storage + PublishingSettings   # solo tipos del núcleo
PublishingSettings    = sleep, esperas de reintento de persistencia, intervalo de progreso,
                        tiempo máximo de parada                          # genéricos
publishers            = dict[Platform, Publisher] en app.state           # main.py los registra
```

**Independencia del núcleo**:

- `PublishContext` solo contiene dependencias genéricas: `session_factory`, `storage`
  (`MediaStorage`) y `PublishingSettings`. **No** contiene `GoogleGateway`,
  `CredentialStore` ni ninguna configuración de subida de YouTube.
- `PublishingSettings` (definida en `publishing.py`) agrupa lo que es realmente genérico:
  `sleep` inyectable, esperas de los reintentos de persistencia en SQLite (0,5/1/2 s,
  §7), intervalo mínimo entre escrituras de progreso (1 s) y tiempo máximo de espera al
  parar el runner (5 s). `persist_success`/`persist_failure` solo usan estos valores.
- Las dependencias exclusivas de YouTube se encapsulan en el adaptador:
  `YouTubePublisher(gateway, credential_store, upload_settings: YouTubeUploadSettings)`.
  `YouTubeUploadSettings` (en `youtube_upload.py`) contiene tamaño de fragmento y de
  porción, backoff, número máximo de fallos consecutivos, tope de `Retry-After` y su propio
  `sleep`.
- `main.py` es la raíz de composición: construye el gateway, el almacén de credenciales y
  el `YouTubePublisher`, y lo registra en `app.state.publishers[Platform.YOUTUBE]`. El
  núcleo solo usa el protocolo `Publisher`.
- Un test de arquitectura (`ast`) garantiza que `publishing.py` y `publications.py` no
  importan `app.youtube_*`, `app.credential_store`, `httpx`/`httpx2` ni `keyring`.

- El **núcleo** (`publishing.py`) se encarga de: estados de `Publication`, creación y cierre
  de `PublicationAttempt`, concurrencia, persistencia del progreso y del resultado,
  recuperación tras reinicio y endpoints genéricos (`publish-check`, `publish`,
  `attempts`).
- El **adaptador** (`youtube_publishing.py`) se encarga de: reglas de elegibilidad de
  YouTube, opciones YouTube, construcción y validación de metadata, verificación del canal,
  protocolo resumible y clasificación de errores de YouTube.
- `PreparedPublication` y `PublishOutcome` son dataclasses genéricas: el `submitted`
  (instantánea no sensible de lo enviado), el `external_id`, la `external_url`, `details`
  (dict no sensible específico de la plataforma) y `warnings`.

**Razón**: la Constitution (III) exige que cada plataforma sea un adaptador independiente y
que el núcleo no conozca su lógica. La Feature 005 aplazó esta interfaz "hasta que exista
una segunda operación real"; esta feature introduce la primera ejecución real, así que es
el momento. Se mantiene mínima: cuatro métodos y un diccionario, sin jerarquías de clases
ni plugins.

**Alternativas descartadas**: lógica de YouTube directamente en `publications.py` (viola el
principio III); un sistema de plugins con descubrimiento dinámico (abstracción prematura).

## 3. Protocolo resumible: implementación propia sobre `httpx2`, subida por fragmentos

**Decisión**: implementar el protocolo oficial con el `httpx2.Client` existente, en
`youtube_upload.py`, sin SDK de Google:

1. **Iniciar sesión**: `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status&notifySubscribers=<true|false>`
   con `Authorization`, `Content-Type: application/json; charset=UTF-8`,
   `X-Upload-Content-Length` y `X-Upload-Content-Type`, y el recurso `video` (snippet +
   status) en el cuerpo. La respuesta `200` trae la URI de sesión en `Location`.
2. **Enviar fragmentos**: `PUT <session URI>` con `Content-Range: bytes START-END/TOTAL` y
   `Content-Length`. Tamaño de fragmento **8 MiB** (múltiplo de 256 KiB, como exige el
   protocolo); el último puede ser menor.
3. **Cada fragmento se envía como iterador** que lee el archivo en porciones de 256 KiB:
   nunca hay más de una porción en memoria y el progreso en memoria se actualiza por
   porción.
4. **Respuestas**: `308` → leer `Range: bytes=0-N` y continuar desde `N+1` (sin cabecera
   `Range` → nada recibido, continuar desde 0); `200`/`201` → recurso `video` final.
5. **Consulta de estado tras interrupción**: `PUT <session URI>` vacío con
   `Content-Range: bytes */TOTAL`; `308` + `Range` indica el último byte confirmado;
   `200`/`201` indica que la subida ya terminó (y trae el vídeo).
6. MIME por formato: `mp4` → `video/mp4`, `mov` → `video/quicktime`, `webm` → `video/webm`.
7. Timeouts de subida propios por petición: `connect=10 s`, `write=60 s`, `read=60 s`.

**Razón**: el gateway propio de la Feature 005 ya evita el SDK de Google y sus dependencias
(research 005 §2). El protocolo es pequeño, está bien documentado y escribirlo permite
controlar exactamente qué se registra (la URI de sesión nunca) y cuándo una respuesta es
ambigua (§5).

Los fragmentos dan puntos naturales de confirmación (`308`) para persistir el progreso y
reanudar; la lectura por porciones cumple FR-003 (sin cargar el archivo en RAM).

**Alternativas descartadas**:

- `google-api-python-client` + `MediaFileUpload(resumable=True)`: añade el SDK y
  `google-auth`, oculta la URI de sesión y sus reintentos, y dificulta clasificar la
  ambigüedad.
- Una sola petición `PUT` con todo el archivo en streaming: menos peticiones, pero cada
  corte obliga a consultar el estado sin puntos intermedios de persistencia; los fragmentos
  son igual de simples con el iterador.

**Ajustable para tests**: `create_app` acepta `publishing_settings: PublishingSettings` (núcleo)
y `youtube_upload_settings: YouTubeUploadSettings` (adaptador, con `chunk_size`,
`slice_size`, `max_consecutive_failures`, `max_backoff`, `max_retry_wait` y `sleep`). Los
tests usan archivos de unos cientos de KiB, fragmentos de 256 KiB y funciones `sleep` que no
esperan.

## 4. Recuperación limitada dentro del mismo intento

**Decisión**:

| Situación | Acción |
|-----------|--------|
| Error de transporte (`httpx.TransportError`: conexión, timeout, corte) | Recuperable |
| HTTP `500`, `502`, `503`, `504` | Recuperable (lo indica la guía oficial) |
| HTTP `429`, o `403` con razón `rateLimitExceeded` / `userRateLimitExceeded` | Recuperable |
| HTTP `401` | Renovar credenciales (forzado) y repetir; un segundo `401` seguido → `reconnect_required` |
| Cualquier otro `4xx` | Definitivo (§6) |

- Tras un fallo recuperable con sesión ya creada: espera, **consulta de estado** y
  reanudación desde el último byte confirmado. Antes de crear la sesión: espera y se repite
  la petición de inicio (una sesión sin bytes no crea ningún vídeo).
- **Backoff exponencial con jitter**: 1, 2, 4, 8, 16, 32 s (tope 32 s), como máximo
  **6 fallos recuperables consecutivos sin progreso**. Cualquier avance confirmado reinicia
  el contador.
- **`Retry-After`**: si una respuesta recuperable (`429`, `503` u otro 5xx) incluye la
  cabecera `Retry-After` (segundos o fecha HTTP, RFC 9110), YouTube está indicando cuándo
  volver a intentarlo y se respeta:
  - espera = `max(backoff calculado, Retry-After)`, con un **tope seguro de 60 s** por
    espera;
  - si `Retry-After` pide **más de 60 s**, no se reintenta antes de lo indicado ni se
    espera más del tope: el intento termina `failed` con `youtube_unavailable` (determinado
    o ambiguo según el `stage`, §5);
  - un valor ilegible, negativo o en el pasado se ignora y se usa el backoff normal;
  - cada espera cuenta como uno de los 6 fallos consecutivos; el peor caso queda acotado
    (≈ 6 min de esperas).
  La guía del protocolo resumible prescribe backoff exponencial para los 5xx; respetar
  además `Retry-After` cuando YouTube lo envía es compatible con ella y evita reintentar
  antes de tiempo.
- Agotado el límite: el intento termina `failed` con `youtube_unavailable` (si la última
  causa fue un 5xx/429) o `network_error` (si fue de transporte).
- Reintentos, esperas y reanudaciones pertenecen siempre al **mismo** `PublicationAttempt`
  y a la misma sesión resumible.
- Las renovaciones de token durante subidas largas se piden antes de cada petición si el
  token caduca en menos de 60 s (reutiliza `get_valid_credentials` de la Feature 005).

**Razón**: cumple FR-030 (recuperación acotada, mismo intento) y la guía oficial (backoff
exponencial para 5xx). Los límites son pequeños y fijos; no son configuración de negocio.

**Alternativas descartadas**: reintentos ilimitados (pueden dejar una publicación
`publishing` indefinidamente); crear una sesión nueva tras un `404` de sesión (riesgo de
duplicar si la sesión anterior llegó a completarse, §5).

## 5. Determinar si el resultado es ambiguo

**Decisión**: el intento guarda un `stage` persistente:
`preparing` → `uploading` → `final_chunk` → `done`.

**Write-ahead del último fragmento.** El "último fragmento" es la petición `PUT` cuyo
`Content-Range` incluye el último byte del archivo. Orden obligatorio:

1. persistir `stage = 'final_chunk'` en el intento;
2. **commit** en SQLite (y comprobar que se ha confirmado);
3. enviar el último fragmento;
4. recibir la respuesta final con el video ID;
5. persistir inmediatamente el resultado remoto (§7);
6. marcar el intento `succeeded` y la publicación `published` (misma transacción que 5).

Si el commit del paso 2 falla, el último fragmento **no se envía**: YouTube no ha recibido
el archivo completo, así que el intento se cierra `failed` / `internal_error`
**determinado** (si tampoco eso puede escribirse, la fila queda en `uploading` y la
recuperación de arranque la cierra como determinada, §9).

Reglas de ambigüedad:

- **Un intento fallido es ambiguo (`outcome_determined = false`) si y solo si**:
  su `stage` era `final_chunk` cuando terminó; o YouTube respondió éxito sin un video ID
  válido; o el resultado recibido no pudo persistirse (§7).
- Un reinicio con el `stage = 'final_chunk'` ya confirmado y sin resultado persistido →
  ambiguo y revisión manual (§9).
- Las fases anteriores (`preparing`, `uploading`) son **determinadas** ("no se publicó"):
  mientras no se haya enviado el último fragmento, YouTube no puede haber recibido el
  archivo completo y el vídeo no puede existir. Permiten reintentar sin la confirmación
  extra de FR-041.
- Si tras enviar el último fragmento YouTube responde de forma autoritativa que la subida
  está **incompleta** (`308` con un `Range` menor que el total, en la respuesta o en una
  consulta de estado), YouTube confirma que no tiene el archivo completo: se persiste
  `stage = 'uploading'`, se reanuda, y antes de volver a enviar el último fragmento se
  repite el write-ahead (pasos 1–2).
- En `final_chunk`, tras un fallo recuperable, las consultas de estado (`bytes */TOTAL`) se
  hacen sin cambiar de fase: un `200`/`201` con video ID es éxito; un `308` incompleto,
  vuelta a `uploading`.
- Un `404` de sesión en `uploading` → `upload_session_expired`, determinado. En
  `final_chunk` → ambiguo.

**Razón**: aplica el principio "nunca duplicar automáticamente" sin marcar como ambiguos
todos los cortes: solo el tramo final, en el que YouTube podría haber creado el vídeo sin
que AutoPublisher lo sepa, exige revisión manual.

**Alternativas descartadas**: considerar ambiguo todo fallo con sesión creada (obliga a
revisar YouTube Studio tras cualquier corte de red, sin motivo); buscar el vídeo por título
en el canal (la spec lo prohíbe: un título no identifica un vídeo).

## 6. Clasificación de errores de YouTube (códigos seguros)

**Decisión**: los mensajes mostrados son **fijos por código**; nunca se copia texto de
Google. De la respuesta de error solo se lee `error.errors[0].reason` para clasificar.

| Código del intento | Origen |
|--------------------|--------|
| `reconnect_required` | `401` tras renovar; `InvalidGrant`; credenciales ausentes |
| `media_unavailable` | Archivo ausente, ilegible, o lectura más corta de lo esperado |
| `invalid_metadata` | `400` con `invalidTitle`, `invalidDescription`, `invalidVideoMetadata`, `invalidCategoryId`, `invalidFilename`, `mediaBodyRequired` |
| `permission_denied` | `403` con `forbidden`, `insufficientPermissions`, `forbiddenPrivacySetting`, `forbiddenLicenseSetting`, `youtubeSignupRequired` |
| `quota_exceeded` | `403` con `quotaExceeded` o `dailyLimitExceeded` |
| `upload_limit_exceeded` | `400` con `uploadLimitExceeded` |
| `youtube_rejected` | Otros `4xx` definitivos |
| `youtube_unavailable` | 5xx/429 tras agotar la recuperación |
| `network_error` | Errores de transporte tras agotar la recuperación |
| `upload_session_expired` | `404`/`410` sobre la URI de sesión |
| `unexpected_response` | Respuesta final sin video ID válido, `Location` ausente, cuerpos ilegibles |
| `interrupted` | Reinicio o apagado del backend durante la ejecución |
| `result_not_saved` | YouTube devolvió un video ID pero no pudo persistirse el resultado (§7) |
| `internal_error` | Excepción inesperada en el hilo de ejecución |

Video ID válido: `^[A-Za-z0-9_-]{11}$`. URL directa: `https://www.youtube.com/watch?v=<id>`.

**Razón**: FR-042/FR-043. Los códigos coinciden con los que la UI necesita distinguir y no
filtran información de Google.

## 7. Persistencia inmediata del resultado y fallo al persistirlo

**Decisión**:

1. Al recibir un video ID válido, el hilo **persiste inmediatamente**, en una transacción:
   intento `succeeded` (`external_id`, `external_url`, `details`, `stage = done`) y
   publicación `published` con `published_at`. Si falla, se repite hasta **3 veces** con
   esperas cortas (0,5 s, 1 s, 2 s).
2. Si las 3 fallan, el resultado se trata como **ambiguo**: se intenta escribir (con los
   mismos reintentos) el intento `failed`, `error_code = result_not_saved`,
   `outcome_determined = false`, y la publicación `failed`. **No se guarda el video ID ni
   la URL** en este caso: el resultado se considera no conservado.
3. Si tampoco eso puede escribirse, la fila queda en `running`/`final_chunk` (confirmada por
   el write-ahead, §5) y la **recuperación de arranque** (§9) la cerrará como `interrupted`
   y ambigua.
4. **El video ID no se escribe en logs** en ningún caso. Aunque no es una credencial OAuth,
   en un vídeo `unlisted` forma parte de un enlace que da acceso al vídeo. El log `ERROR`
   solo contiene los ids internos del intento y de la publicación y el código
   `result_not_saved`; nunca video ID, URL, tokens, cabeceras, URI de sesión ni cuerpos de
   Google.
5. **Revisión manual**: el mensaje del intento (`result_not_saved` o `interrupted` ambiguo)
   indica que YouTube podría haber aceptado el vídeo y pide comprobarlo en **YouTube
   Studio** antes de cualquier nueva ejecución, identificándolo por **canal, título y
   momento aproximado**. La interfaz muestra esos tres datos a partir de `submitted`
   (`channel_title`, `channel_id`, `title`) y de `started_at`/`finished_at` del intento.
6. **Nunca** se inicia otra subida, ni en este hilo ni tras reiniciar.
7. Sin almacenamiento alternativo ni fichero de emergencia (archivos sueltos, JSON
   auxiliares, logs…).

La comprobación ligera posterior (§10) se hace **después** de este commit, para que un
fallo de red no retrase la persistencia del resultado.

**Razón**: cumple FR-040a con la regla conservadora pedida. La base es SQLite local: un
fallo de escritura es raro (disco lleno, bloqueo), y los reintentos cortos cubren los
bloqueos transitorios.

**Alternativas descartadas**: guardar el video ID en un archivo de emergencia (almacenamiento
alternativo excluido por la spec); escribirlo en logs (un video ID de un vídeo `unlisted`
da acceso al vídeo); reintentar la persistencia indefinidamente (el hilo no debería vivir
sin límite).

## 8. Concurrencia: transición condicional + índice único parcial

**Decisión**: doble garantía en persistencia, en la misma transacción:

1. `UPDATE publications SET status='publishing', updated_at=… WHERE id=:id AND status IN
   ('unscheduled','scheduled','failed')`. Si `rowcount != 1` → `409
   publication_in_progress` (o `publication_not_eligible` si el estado no es elegible).
2. `INSERT` del intento `running`, protegido por el índice único parcial
   `uq_publication_attempts_running ON publication_attempts(publication_id) WHERE status =
   'running'`. Un `IntegrityError` → rollback y `409 publication_in_progress`.

Dos `Publish now` simultáneos pueden pasar ambos el preflight (que incluye red), pero solo
uno gana el `UPDATE` condicional; el otro recibe `409` sin crear sesión de subida.

El runner registra el intento como "vivo" antes de lanzar el hilo.

**Razón**: FR-038; la garantía no depende de la interfaz. SQLite serializa las escrituras y
el `UPDATE … WHERE status IN (…)` es atómico.

**Alternativas descartadas**: un `threading.Lock` por publicación (no sobrevive a varios
procesos y duplica lo que ya garantiza la base); `SELECT … FOR UPDATE` (no existe en
SQLite).

## 9. Reinicio y apagado durante `PUBLISHING`

**Decisión**:

- **Arranque** (`lifespan`, tras las migraciones y antes de aceptar peticiones):
  `recover_interrupted_attempts()` busca intentos `running` y, para cada uno:
  - intento → `failed`, `error_code = interrupted`, `finished_at = now`,
    `outcome_determined = (stage != 'final_chunk')`;
  - publicación → `failed`.

  Un intento con `stage = 'final_chunk'` confirmado y sin resultado persistido es, por
  tanto, siempre ambiguo y requiere revisión manual (§5, §7).

  Nunca se reanuda ni se vuelve a subir nada (FR-044/FR-045). La URI de sesión no existe
  tras el reinicio porque nunca se persistió.
- **Apagado ordenado**: el runner activa un `stop_event`; cada hilo lo comprueba entre
  porciones y, si está en `preparing`/`uploading`, cierra su intento como `interrupted`
  determinado. Se esperan los hilos como máximo 5 s; lo que quede (p. ej. una petición
  final en vuelo) se cierra en el siguiente arranque según la regla anterior.

**Razón**: FR-044/FR-045 y el caso "reinicio con Publication en `PUBLISHING`" de los tests.

## 10. Comprobación ligera posterior

**Decisión**: tras persistir el éxito, una única llamada
`videos.list?part=status,processingDetails&id=<id>` (coste de lectura mínimo). Actualiza en
`details`: `privacy_status` real, `upload_status` y `processing_status` (si existen). Si
falla por cualquier motivo, se ignora y se conserva lo devuelto por la propia subida
(FR-040). No se espera a que termine el procesamiento.

La privacidad real se toma primero de la respuesta final de la subida
(`status.privacyStatus`) y se refina con esta comprobación. Si difiere de la solicitada se
añade el aviso `privacy_differs` a `warnings`.

## 11. Opciones YouTube: tabla propia del adaptador

**Decisión**: tabla `youtube_publication_options` (1:1 opcional con `publications`):
`privacy_status` (`private` por defecto), `made_for_kids` (nullable), `contains_synthetic_media`
(nullable), `notify_subscribers` (`false` por defecto). Sin fila = valores por defecto. Se
gestiona con `GET`/`PUT /api/publications/{id}/youtube-options` desde `youtube_publishing.py`.

Mapeo a `videos.insert`:

| Opción | Destino |
|--------|---------|
| `privacy_status` | `status.privacyStatus` |
| `made_for_kids` | `status.selfDeclaredMadeForKids` |
| `contains_synthetic_media` | `status.containsSyntheticMedia` |
| `notify_subscribers` | parámetro de consulta `notifySubscribers` (siempre explícito; su valor por defecto en YouTube es `true`) |

**Razón**: FR-018 (sin campos `youtube_*` en `Publication`), mismo patrón que
`youtube_connections` (tabla aparte con FK hacia el núcleo).

## 12. Metadata enviada

**Decisión** (verificado en el recurso `videos`):

- `snippet.title` = título efectivo. Debe ser no vacío tras recortar espacios, tener
  **≤ 100 caracteres** y no contener `<` ni `>`.
- `snippet.description` = descripción efectiva + `"\n\n"` + `"#a #b #c"` (sin descripción:
  solo la línea de hashtags; sin hashtags: solo la descripción; sin ambos: cadena vacía).
  Debe tener **≤ 5000 bytes UTF-8** y no contener `<` ni `>`.
- Los hashtags se guardan sin `#` (Feature 004), así que se antepone `#` a cada uno.
- `snippet.tags`: no se envía (fuera de alcance).
- `snippet.categoryId`: **no se envía**. La documentación de `videos.insert` no lo marca
  como obligatorio (solo en `videos.update`); YouTube asigna su categoría por defecto.
  - Esta decisión se **valida durante la prueba real** (`quickstart.md` §7, tarea T063).
  - Si YouTube acepta la subida sin `categoryId`, la decisión queda **confirmada**.
  - Si YouTube rechaza la subida específicamente porque exige `categoryId`, la validación
    **se detiene**: no se modifica código ni se introduce automáticamente ninguna
    categoría. Antes de decidir cómo resolverlo se revisan explícitamente spec y plan.
- No se usa `status.publishAt` (FR-033).

Errores de validación → `409 invalid_metadata` en el preflight, con `fields` (`title`,
`description`) y mensajes concretos, antes de crear la sesión (FR-028).

## 13. Política de `FAILED`, edición y duplicados

**Decisión**:

- **Reintento manual**: `Publish now` está permitido desde `failed`, con confirmación y
  preflight completos, y crea un intento nuevo.
- **Confirmación extra**: si el **último intento** de cualquier publicación de la misma
  pareja contenido + cuenta es `failed` y ambiguo, `POST /publish` exige
  `confirm_remote_checked: true` (la UI muestra una casilla obligatoria: "I checked YouTube
  Studio and this video was not published"). Sin ella → `409 remote_check_required`.
  Comprobarlo por pareja, y no solo por publicación, impide saltarse la regla cancelando y
  reactivando, o creando una publicación nueva.
- **Edición por estado**:

| Estado | Fecha | Overrides | Opciones YouTube | Cancelar | Publish now |
|--------|-------|-----------|------------------|----------|-------------|
| `unscheduled` / `scheduled` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `failed` | ❌ (se conserva) | ✅ | ✅ | ✅ | ✅ (§13) |
| `publishing` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `published` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `cancelled` | ❌ | ❌ | ❌ | — (reactivar) | ❌ |

  `failed` permite corregir metadata y opciones antes de reintentar. La fecha no se edita en
  `failed` porque no existe scheduler: para reprogramar, se cancela y se reactiva.
- **Duplicados** (spec FR-009): el índice único parcial pasa de `status != 'cancelled'` a
  `status NOT IN ('cancelled', 'published')`. `find_active` usa el mismo criterio.
- **Desconectar/reconectar**: `authorize` y `disconnect` de la Feature 005 rechazan con
  `409 publication_in_progress` si la cuenta tiene alguna publicación `publishing`.

## 14. Orden de la Queue

**Decisión**: `publishing` → `failed` → `scheduled` (fecha ascendente) → `unscheduled`
(creación ascendente) → `published` (`published_at` descendente) → `cancelled`
(`updated_at` descendente), desempate por `id`. Lo que está en curso o requiere atención
aparece primero.

## 15. Secretos y logs

**Decisión**:

- La URI de sesión (contiene `upload_id`) solo vive en una variable local del hilo.
- `httpx2` registra en `INFO` la URL de cada petición y `httpcore2` registra en `DEBUG` las
  cabeceras de respuesta (incluida `Location`): se instala un filtro `RedactYouTubeUrls` en
  el logger `httpx2` y en los loggers `httpcore2.*` (en `install_log_redaction`, junto al
  filtro existente) que sustituye por `[redacted]` el valor de `upload_id=` y el del
  parámetro `id=` de `videos.list`. Este último se añadió durante la implementación: los
  tests de fuga detectaron que la URL de la comprobación ligera (§10) llevaba el video ID
  al log, lo que contradecía §7. La validación real (T063) detectó además que YouTube
  repite el id de la sesión en la cabecera de respuesta `X-GUploader-UploadID`, que
  `httpcore2` registra en `DEBUG`; el filtro también redacta su valor.
- El código de subida nunca registra excepciones con `exc_info` ni su `str()` (podrían
  contener la URL); solo el nombre de la clase y los ids del intento.
- Las excepciones propias tienen mensajes fijos.
- El video ID y la URL del vídeo no se escriben nunca en logs (§7); solo se persisten en
  SQLite como resultado de un intento `succeeded`.
- Tests: valores distintivos en el fake (`upload_id`, tokens) que se buscan en el volcado
  de SQLite, en todas las respuestas JSON y en `caplog` a nivel `DEBUG`.

## 16. Cuota

**Dato a 2026-10-07** (documentación oficial de `videos.insert`): "A call to this method has a
quota cost of **1 unit in the Video Uploads quota bucket**". Versiones anteriores de la
documentación indicaban 1600 unidades en la cuota general. Se documenta en el README con la
fecha de consulta y el enlace, **sin** codificarlo como constante. Los errores
`quotaExceeded`/`dailyLimitExceeded` se muestran como `quota_exceeded`.

## 17. Proyectos API no verificados

**Dato oficial**: "All videos uploaded via the videos.insert endpoint from unverified API
projects created after 28 July 2020 will be restricted to private viewing mode", hasta
superar una auditoría. AutoPublisher no intenta evitarlo: muestra la privacidad real con el
aviso `privacy_differs` y la nota en la UI y el README (FR-055).

## 18. Integridad del archivo

**Decisión**: el preflight comprueba que el archivo existe, es legible y su tamaño coincide
con `contents.size_bytes`. No se recalcula el SHA-256 (leería el archivo entero una vez más
antes de subirlo). Si la lectura durante la subida devuelve menos bytes de los esperados, el
intento termina `media_unavailable` (ambiguo si estaba en `final_chunk`). El archivo se abre
en modo lectura binaria: nunca se escribe ni se copia.
