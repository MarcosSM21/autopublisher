# Research: TikTok Publisher & Direct Post (VIDEO, FILE_UPLOAD)

**Feature**: `013-tiktok-direct-post` | **Fecha**: 2026-10-14 | **Spec**: [spec.md](spec.md)

Fuentes oficiales consultadas el 2026-10-14 (TikTok for Developers): *Content Posting API — Get
Started*, *Direct Post API reference* (`/v2/post/publish/video/init/`), *Query Creator Info*,
*Media Transfer Guide*, *Get Post Status*, *Content Sharing Guidelines*. Código existente
inspeccionado: `publishing.py`, `models.py`, `media.py`, `storage.py`, `publications.py`,
`automation.py`, `scheduler.py`, `tiktok_gateway.py`, `tiktok_connections.py`,
`threads_publishing.py`, `instagram_media.py`, `main.py`.

Cada sección: **Decisión**, **Razón**, **Alternativas descartadas**. Lo que la documentación no
garantiza queda marcado como **[V1]** (se confirma en el checkpoint real temprano) o **[V2]**.

---

## §1 Arquitectura: publisher del protocolo existente

**Decisión**: `TikTokPublisher` implementa el protocolo `Publisher` real (`check`, `prepare`,
`upload`, `refresh_details`, `release`, `reconcile`, `accepts_text_only = False`) y se registra en
`app.state.publishers[Platform.TIKTOK]` desde `main.py`, como YouTube, Instagram y Threads. No
existe `publish()`: el Direct Post completo (init → chunks → write-ahead → último chunk →
polling) ocurre dentro de `upload`. Módulos:

| Módulo | Responsabilidad |
|---|---|
| `tiktok_gateway.py` (ampliado) | HTTP de TikTok y **única** clasificación de sus códigos de error: `query_creator_info`, `init_video_post`, `upload_chunk`, `fetch_publish_status`. Sin estado ni base de datos. |
| `tiktok_media.py` (nuevo) | Reglas sin red: caption y su conteo, plan de chunks, matriz de validación del vídeo, reglas de opciones, mapeo a `post_info`, huella de consentimiento, digest en streaming. |
| `tiktok_publishing.py` (nuevo) | `TikTokPublisher`, `TikTokPublishSettings`, router de opciones / Creator Info / consentimiento. |
| `tiktok_connections.py` (Feature 012, sin cambios de lógica) | `get_valid_credentials`, `call_with_token`, `mark_scope_not_authorized`, `mark_reconnect_required`, `get_connection`. Solo se amplía el filtro de redacción de logs (§10). |

Reutiliza sin cambios: `PublicationRunner`, `start_publication`, `create_running_attempt`,
`PublicationAttempt`, estados genéricos, `enter_final_chunk` (write-ahead genérico),
`recover_interrupted_attempts`, scheduler, pausa y concurrencia. Las únicas extensiones del núcleo
son neutrales y mínimas: §17 (reconciliación "confirmado no publicado") y §20 (problemas de
armado aportados por el publisher).

**Razón**: mismo patrón que las Features 009/011; el núcleo ya modela upload resumible con último
chunk irreversible (`AttemptStage.FINAL_CHUNK` ∈ `UNCERTAIN_STAGES`, introducido para YouTube).

**Alternativas descartadas**: un gateway separado `tiktok_posting_gateway.py` (dividiría la
clasificación de errores de TikTok en dos módulos; el docstring de `tiktok_gateway.py` lo fija
como único intérprete de códigos); un ejecutor propio de TikTok (prohibido por FR-004).

---

## §2 Gateway TikTok

**Decisión**: se amplía `TikTokGateway` con cuatro métodos. Todos reciben el access token como
argumento (nunca lo leen ni lo guardan), envían JSON (`Content-Type: application/json;
charset=UTF-8`) salvo el `PUT`, y lanzan solo excepciones semánticas sin URL, cuerpo ni token
(`raise ... from None`), conservando `log_id` si es seguro.

| Método | Petición | Devuelve | Timeout |
|---|---|---|---|
| `query_creator_info(token)` | `POST /v2/post/publish/creator_info/query/` sin cuerpo | `CreatorInfo` (§3) | 10 s |
| `init_video_post(token, post_info, source_info)` | `POST /v2/post/publish/video/init/` | `InitResult(publish_id, upload_url: UploadUrl)` | 30 s |
| `upload_chunk(upload_url, data, first, last, total, content_type)` | `PUT` al `upload_url` completo, **sin** `Authorization` | `ChunkResult(status: 206/201, progress: UploadProgress \| None)` (§12) | connect 10 s, write 300 s, read 120 s |
| `fetch_publish_status(token, publish_id)` | `POST /v2/post/publish/status/fetch/` `{"publish_id": …}` | `PublishStatus` (§16) | 10 s |

Excepciones nuevas (además de las de la Feature 012, que se mantienen):

- `TikTokPostRejected(code, log_id)`: rechazo de negocio con `code` de un conjunto cerrado
  (`invalid_param`, `privacy_level_option_mismatch`, `spam_risk_too_many_posts`,
  `spam_risk_user_banned_from_posting`, `reached_active_user_cap`,
  `unaudited_client_can_only_post_to_private_accounts`, `url_ownership_unverified`,
  `invalid_publish_id`, `token_not_authorized_for_specified_publish_id`). Cualquier otro código
  no listado → `TikTokUnexpectedResponse` (nunca se propaga un código arbitrario).
- `TikTokUnavailable` gana `rate_limited: bool` (429 / `rate_limit_exceeded`) para el mensaje.
- `TikTokUploadRejected(status)` para `400`/`403`/`404` del `PUT`; `TikTokUploadRangeMismatch
  (progress: UploadProgress | None)` para `416`. `UploadProgress(accepted_bytes, total)` se
  lee del `Content-Range` de la **respuesta** (§12); `None` si falta, es ilegible o no empieza
  en 0.

`_classify` se extiende con esos códigos; `access_token_invalid` → `TikTokTokenInvalid` y
`scope_not_authorized` → `TikTokScopeMissing("video.publish")` (ya existentes).

**Credenciales**: el publisher obtiene tokens solo con `get_valid_credentials` /
`call_with_token` de la Feature 012. `call_with_token` (renovar una vez y repetir ante
`access_token_invalid`) se usa **solo** para llamadas de lectura: Creator Info y estado. `init`
usa el token de `get_valid_credentials` obtenido justo después de Creator Info y **no** se repite
nunca (§13). No se duplica OAuth, renovación, identidad ni reconexión.

**Razón**: separa HTTP (gateway), clasificación (gateway), reglas puras (`tiktok_media`) y
negocio (`tiktok_publishing`); el filtro de excepciones existente ya impide filtrar URLs.

**Alternativas descartadas**: devolver códigos crudos al publisher (rompe "único intérprete");
usar `call_with_token` también en `init` (podría producir dos peticiones `init` en un intento).

---

## §3 Creator Info

**Decisión — DTO** (`CreatorInfo`, validación estricta):

| Campo TikTok | Tipo exigido | Si falta / tipo incorrecto |
|---|---|---|
| `creator_nickname` | `str` no vacío | `TikTokUnexpectedResponse` (la UX oficial exige mostrarlo) |
| `creator_username` | `str` | se acepta ausente (`None`); solo informativo |
| `creator_avatar_url` | `str` | ausente → `None` (opcional) |
| `privacy_level_options` | lista no vacía de `str` | `TikTokUnexpectedResponse` |
| `comment_disabled`, `duet_disabled`, `stitch_disabled` | `bool` estricto | `TikTokUnexpectedResponse` (nunca se asume `false`) |
| `max_video_post_duration_sec` | `int` > 0 (no `bool`) | `TikTokUnexpectedResponse` |

Valores desconocidos dentro de `privacy_level_options` se conservan y se muestran tal cual,
pero solo `SELF_ONLY` es seleccionable mientras el cliente no esté auditado (§4).

**Errores**: `error.code` con HTTP 200 `spam_risk_too_many_posts`,
`spam_risk_user_banned_from_posting`, `reached_active_user_cap` → `TikTokPostRejected` →
"el creador no puede publicar ahora" (bloquea revisión, publicación y programación);
`access_token_invalid` → renovación vía `call_with_token`; `scope_not_authorized` →
`mark_scope_not_authorized` (Feature 012) + `tiktok_reconnect_required`; 429 → `tiktok_rate_limited`
sin reintento; 5xx / red → **un** reintento tras 2 s solo en `prepare` (no tiene efectos);
forma inesperada → `tiktok_unexpected_response`.

**Rate limit**: 20 peticiones/min por token. Consultas: (1) la UI al abrir el panel TikTok y al
pulsar `Refresh`; (2) `prepare` justo antes de `init` (manual y programada). La UI **no** sondea
Creator Info. Con un solo usuario local no hace falta limitador propio.

**Persistencia / frontend**: Creator Info **no se persiste** en ninguna tabla ni en el
navegador; se devuelve al frontend solo en la respuesta de `GET …/tiktok-creator-info`
(nickname, username, avatar URL, opciones, flags, duración máxima). El avatar (URL firmada de
TikTok válida 2 h) es solo presentación; no se guarda. En `submitted` del intento solo queda un
resumen no sensible (`creator_nickname`, `max_video_post_duration_sec` usado).

**Razón**: FR-008–FR-012; la UX oficial exige datos frescos y prohíbe defaults.

**Alternativas descartadas**: caché corta en backend (FR-009 la prohíbe como autoridad y no aporta
con un solo usuario); persistir el avatar (caduca en 2 h).

---

## §4 Cliente no auditado

**Decisión**: el modo se representa con una constante explícita y documentada en
`tiktok_publishing.py`: `CLIENT_AUDITED = False`, con `UNAUDITED_PRIVACY_LEVEL = "SELF_ONLY"`.
No es configurable por entorno en esta feature: activar publicación pública exigiría auditoría,
otra especificación y nuevas pruebas, así que un interruptor solo permitiría afirmar un soporte
que no existe. No se infiere nunca de Creator Info.

Mientras `CLIENT_AUDITED = False`:

- solo `SELF_ONLY` es seleccionable y enviable; las demás opciones de `privacy_level_options`
  se muestran deshabilitadas con el motivo "This TikTok app is not audited: TikTok only allows
  private (Only me) posts";
- si `SELF_ONLY` no está en `privacy_level_options` → preflight `tiktok_privacy_unavailable`;
- **cuenta privada**: TikTok exige que la cuenta sea privada al publicar. No existe un campo
  oficial "cuenta privada"; la documentación indica que las cuentas privadas reciben
  `FOLLOWER_OF_CREATOR` y las públicas `PUBLIC_TO_EVERYONE`. La revisión muestra un **aviso no
  bloqueante** si las opciones contienen `PUBLIC_TO_EVERYONE` ("Your TikTok account appears to
  be public; set it to private before publishing"). La fuente de verdad es el rechazo de `init`
  (`unaudited_client_can_only_post_to_private_accounts` → fallo determinado). **[V1]** confirma
  la correspondencia.
- caps (5 usuarios/24 h, ~15 posts/día): **no** se codifican; solo se usan los códigos que
  devuelve TikTok.
- README y `docs/tiktok-publishing.md` documentan el riesgo de producto: TikTok declara no
  aceptable para auditoría "A utility tool to help upload contents to the account(s) you or your
  team manages"; no bloquea el uso privado actual y AutoPublisher no intenta sortearlo.

**Alternativas descartadas**: variable de entorno `AUTOPUBLISHER_TIKTOK_CLIENT_AUDITED`
(configuraría un modo no implementado ni validado); inferir auditoría de las opciones (FR-015).

---

## §5 Opciones TikTok

**Decisión**: tabla `tiktok_publication_options` (detalle en [data-model.md](data-model.md)):
`privacy_level` NULL inicial; `allow_comment`, `allow_duet`, `allow_stitch` `false`;
`commercial_disclosure_enabled`, `brand_organic_toggle`, `brand_content_toggle` `false`;
`is_aigc` NULL = `undecided`; `consent_fingerprint`, `consent_declaration_version`,
`consented_at`; `updated_at`. Sin fila = todos los valores iniciales. `Publication` no cambia.

Reglas (validadas en API y, cuando son estructurales, con `CHECK` en SQLite):

- disclosure OFF ⇒ ambos toggles `false` (CHECK). Al desactivar el disclosure la API pone los
  toggles a `false` (el usuario lo ve).
- `brand_content_toggle = true` ∧ `privacy_level = 'SELF_ONLY'` ⇒ inválido (CHECK + 422).
- disclosure ON sin toggle ⇒ guardable (estado intermedio de edición) pero **no publicable**
  (`tiktok_disclosure_incomplete`, mensaje oficial).
- interacciones: booleanos simples, `false` válido, sin tri-estado (spec FR-016).
- consentimiento: los tres campos a la vez NULL o a la vez presentes (CHECK).

**Mapeo comercial** (siempre materializado en el request, ambos booleanos):

| Selección | `brand_content_toggle` | `brand_organic_toggle` |
|---|---|---|
| Disclosure OFF | `false` | `false` |
| Your brand | `false` | `true` |
| Branded content | `true` | `false` |
| Both | `true` | `true` |

Como los toggles persistidos ya están normalizados (OFF ⇒ false/false), el mapeo es directo.
**[V1]** comprueba que TikTok acepta `false/false` explícitos; **[V2]** prueba `Your brand`.

**Mapeo de interacciones**: `disable_comment = not allow_comment`, `disable_duet = not
allow_duet`, `disable_stitch = not allow_stitch`. Si Creator Info deshabilita una interacción,
la UI la muestra deshabilitada (en `false`) con el motivo. `PUT tiktok-options` no consulta la
red, así que solo valida estructura; el preflight falla (`tiktok_interaction_unavailable`) si una
interacción guardada como `true` está deshabilitada en el Creator Info del envío. Nunca se
desmarca en silencio.

**Alternativas descartadas**: tri-estado en interacciones (contradice la UX oficial ajustada en la
spec); guardar el par comercial como enum (pierde el mapeo explícito pedido).

---

## §6 Huella de consentimiento

**Investigación**: `Content.checksum` es el **SHA-256 hexadecimal de todos los bytes** del archivo,
calculado en streaming por `MediaStorage.receive_upload` (Feature 003) y usado para detectar
duplicados. El archivo vive en el almacenamiento propio de AutoPublisher y la aplicación nunca lo
modifica. Es criptográficamente suficiente para identificar los bytes **siempre que se verifique
que el archivo actual sigue produciendo ese digest** (una modificación externa del disco no lo
actualizaría).

**Decisión**:

```
fingerprint = sha256_hex(canonical_json({
  "v": 1,
  "open_id": <TikTokConnection.open_id>,
  "video_sha256": <Content.checksum>,
  "caption": <caption final exacto (§7)>,
  "privacy_level": <str>,
  "allow_comment": <bool>, "allow_duet": <bool>, "allow_stitch": <bool>,
  "commercial_disclosure": <bool>,
  "brand_organic_toggle": <bool>, "brand_content_toggle": <bool>,
  "is_aigc": <bool>,
  "declaration": <versión de la declaración>
}))
```

`canonical_json` = `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
codificado en UTF-8 (mismo enfoque que `instagram_media.fingerprint`). Solo se calcula con las
opciones completas (privacidad elegida y AIGC decidido); si no, no hay huella posible.

Versión de declaración: `"music-usage-2026-10-14"` (sin Branded content) o
`"branded-music-usage-2026-10-14"` (con Branded content); constantes en `tiktok_media.py` con su
texto y enlaces oficiales. Cambiar el texto obliga a cambiar la versión (invalida todo
consentimiento previo).

**Verificación del archivo real**:

1. `check()` (sin red, frecuente): compara la huella guardada con la recalculada usando
   `Content.checksum`; y que `stat().st_size == Content.size_bytes`. **No** recalcula el digest,
   así que la UI nunca afirma que los bytes actuales estén verificados: muestra "Consent
   recorded" / "Consent matches saved publication metadata" y la nota "File integrity is
   rechecked before publishing.". Si el último intento falló con `tiktok_video_changed`, la
   respuesta de opciones lo expone (`integrity_warning`) y el panel lo muestra hasta que un
   consentimiento posterior lo reconfirme.
2. `prepare()` (antes de cualquier efecto remoto): **recalcula SHA-256 en streaming** (lecturas
   de 1 MiB, sin copia ni carga completa) y exige igualdad con `Content.checksum`; si difiere →
   `tiktok_video_changed` (determinado). Coste: lectura secuencial del archivo (≈ segundos para
   varios GB), aceptado.
3. `upload()`: un **segundo SHA-256 incremental sobre los mismos bytes que ya se leen para
   subir**, sin ninguna lectura completa adicional del archivo:
   - cada chunk intermedio se lee una vez en su buffer, actualiza el hash y se envía (un
     reintento reenvía el mismo buffer; el hash no se actualiza dos veces);
   - el **último chunk se lee en memoria antes del write-ahead** (tamaño < 64 MiB por el
     algoritmo de §9; nunca el vídeo completo), se incorpora al hash y se compara el digest
     completo con `Content.checksum` (el mismo valor que entra en la huella consentida);
   - solo si coincide: (1) se persiste el write-ahead y (2) se envía **exactamente una vez** ese
     buffer ya leído;
   - si no coincide → fallo determinado `tiktok_video_changed`, **sin write-ahead y sin `PUT`
     final** (TikTok nunca recibe la parte que inicia la publicación).

   Esto cubre un archivo modificado entre `prepare` y el final de la subida. Lecturas totales del
   vídeo por ejecución: dos (preflight y subida), ninguna redundante. El original no se modifica
   ni se copia.

**Invalida el consentimiento** cualquier cambio de: cuenta TikTok vinculada (`open_id`), `Content`
de la publicación o sus bytes, descripción u hashtags efectivos (overrides de la publicación o
metadata del `Content` cuando no hay override), privacidad, cualquiera de las tres interacciones,
disclosure o sus toggles, AIGC y versión de la declaración. **No** lo invalida: fecha
programada, título genérico (no se envía), cambios de Creator Info (se revalidan en preflight
pero no son contenido consentido).

**Alternativas descartadas**: ruta, nombre, `content_id`, tamaño o mtime (insuficientes, spec
FR-025); recalcular el digest en cada `check()` (coste repetido sin necesidad; la verificación
fuerte se hace donde importa); copiar el vídeo a un área inmutable (prohibido).

---

## §7 Caption y conteo

**Decisión**: caption = `description_with_hashtags(description, hashtags)` existente
(`publications.py`) sobre `effective_metadata` → descripción, `"\n\n"`, `#a #b`; un bloque si el
otro está vacío; `""` si ambos lo están (entonces **no** se envía `title`). Nunca el título.
Sin normalización Unicode, sin trim, sin truncado.

**"2200 UTF-16 runes"**: la documentación no define "rune". En Go, *rune* es un code point; el
calificativo "UTF-16" sugiere unidades de código UTF-16 (la longitud de un string JS/Java). Se
adopta la interpretación **conservadora**: **unidades de código UTF-16** (BMP = 1, no BMP = 2),
que nunca cuenta menos que los code points.

- Python: `len(caption.encode("utf-16-le")) // 2` (`tiktok_caption_length`). **No** `len()`.
- TypeScript: `caption.length` (los strings JS son UTF-16) en `tiktokCaptionLength`.
- Máximo `TIKTOK_CAPTION_MAX = 2200`; `> 2200` → `tiktok_caption_invalid`, nunca truncado.

Tests (backend y frontend con los mismos casos): ASCII (`"a"*2199/2200/2201`); BMP (`"é"`,
`"中"` = 1); emoji `"😀"` = 2; no BMP `"𝐀"` = 2; compuesto `"👨‍👩‍👧"` = 8 (3×2 + 2 ZWJ); bandera
`"🇪🇸"` = 4; `"❤️"` = 2 (BMP + VS16); 1100 × `"😀"` = 2200 válido, + `"a"` inválido; caption
vacío.

**Alternativas descartadas**: code points (`len()`), graphemes (podrían infra-contar).

---

## §8 Validación de vídeo

Inspección: `Content.media_format` (detectado por cabecera, Feature 003), `stat()` y
`media.probe_video_streams` (ffprobe, existente). No se transcodifica, no se modifica, no se copia.

| Propiedad | Clase | Regla | Sin dato |
|---|---|---|---|
| Contenedor | Obligatoria local | `media_format ∈ {mp4, mov, webm}` (cabecera) | n/a (siempre conocido) |
| Tipo de `Content` | Obligatoria local | `media_type == video` | n/a |
| Archivo presente y tamaño | Obligatoria local | existe; `st_size == Content.size_bytes`; `≤ 4 000 000 000` B | falla |
| Integridad | Obligatoria local (solo `prepare`/`upload`) | SHA-256 == `Content.checksum` (§6) | falla |
| ffprobe disponible y legible | Obligatoria local | `probe_video_streams` ≠ `None` | falla `tiktok_video_uninspectable` |
| Stream de vídeo | Obligatoria local | existe `codec_type == "video"` | falla |
| Codec | Obligatoria local | `codec_name ∈ {h264, hevc, vp8, vp9}` | falla |
| Ancho y alto | Obligatoria local | ambos en `[360, 4096]` | falla |
| Duración | Obligatoria local | `0 < d ≤ 600 s` (`check`) y `d ≤ max_video_post_duration_sec` (`prepare`) | falla |
| Frame rate | Validada si disponible | `avg_frame_rate` (o `r_frame_rate`) con `22.99 <= fps <= 60.01` (= `23 − 0,01 … 60 + 0,01`, absorbe 23,976/59,94 y errores de representación; no se amplía más). Casos: 22,98 ✗, 22,99 ✓, 23,0 ✓, 23,976 ✓, 59,94 ✓, 60,0 ✓, 60,01 ✓, 60,02 ✗. TikTok sigue siendo la autoridad final (`frame_rate_check_failed`) | delegada (`delegated_checks: ["frame_rate"]`) |
| FPS variable | Delegada | se valida la media; picos instantáneos los evalúa TikTok | — |
| Perfil, bitrate, pixel format, audio | Delegada | no son requisitos documentados de Direct Post | — |
| Número de chunks | Obligatoria local | derivado del plan (§9), siempre ≤ 1000 | n/a |

Los checks delegados se guardan en `submitted.delegated_checks` y se muestran como "checked by
TikTok". Un rechazo posterior (`file_format_check_failed`, `duration_check_failed`,
`frame_rate_check_failed`, `picture_size_check_failed`) es fallo determinado.

**MIME** (`Content-Type` del `PUT`): mp4 → `video/mp4`, mov → `video/quicktime`, webm →
`video/webm` (`media.MIME_TYPES` existente).

**Unidades**: la documentación dice "4 GB" sin precisar; se usa el valor decimal
**4 000 000 000 B** (conservador). Duración técnica 10 min = 600 s.

**Alternativas descartadas**: publicar si falta ffprobe (FR-022 / Feature 003); exigir FPS
obligatorio (ffprobe puede no reportarlo en algunos WebM; se delega explícitamente).

---

## §9 Plan de chunks

**Hechos oficiales**: `< 5 MB` en un único chunk con `chunk_size` = tamaño; chunks de 5 MB a
64 MB; último chunk hasta 128 MB; `total_chunk_count = floor(video_size / chunk_size)`; 1–1000
chunks; archivos > 64 MB en varios chunks; secuencial.

**MB vs MiB**: la documentación escribe "MB" sin definirlo. Se eligen constantes válidas bajo
**ambas** interpretaciones: mínimo efectivo 5 MiB (≥ 5 MB), máximo efectivo 64 000 000 B (≤ 64
MiB), último chunk < 64 MiB (≤ 128 000 000 B).

**Decisión — algoritmo** (`plan_chunks(video_size) -> ChunkPlan`):

```
SINGLE_CHUNK_MAX = 64_000_000          # bytes
CHUNK_SIZE       = 32 * 1024 * 1024    # 33_554_432 bytes

if video_size <= 0: error
if video_size <= SINGLE_CHUNK_MAX:
    chunk_size = video_size; count = 1
else:
    chunk_size = min(CHUNK_SIZE, video_size // 2)
    count = video_size // chunk_size          # ≥ 2
chunk i (0 ≤ i < count-1): [i*chunk_size, (i+1)*chunk_size - 1]
último chunk:              [(count-1)*chunk_size, video_size - 1]
```

Propiedades: un único chunk siempre ≤ 64 000 000 B (cumple "< 5 MB en uno" y "≤ 64 MB");
multi-chunk: `chunk_size ∈ [32 000 000, 33 554 432]` (≥ 5 MiB, ≤ 64 000 000), último chunk en
`[chunk_size, 2·chunk_size)` < 64 MiB < 128 000 000; `count ≤ 119` para 4 000 000 000 B.
32 MiB equilibra memoria (≤ 64 MiB por buffer), número de peticiones y coste de reintento.
Un archivo válido (≤ 4 GB) siempre es representable; `plan_chunks` lanza error interno si alguna
invariante falla (test de propiedades sobre todo el rango).

| Tamaño | `chunk_size` | `total_chunk_count` | Último chunk |
|---|---|---|---|
| 1 MiB (1 048 576) | 1 048 576 | 1 | 1 048 576 |
| 5 MiB (5 242 880) | 5 242 880 | 1 | 5 242 880 |
| 20 MiB (20 971 520) | 20 971 520 | 1 | 20 971 520 |
| 64 000 000 | 64 000 000 | 1 | 64 000 000 |
| 64 000 001 | 32 000 000 | 2 | 32 000 001 |
| 64 MiB (67 108 864) | 33 554 432 | 2 | 33 554 432 |
| 65 MiB (68 157 440) | 33 554 432 | 2 | 34 603 008 |
| 128 MiB (134 217 728) | 33 554 432 | 4 | 33 554 432 |
| 500 MiB (524 288 000) | 33 554 432 | 15 | 54 525 952 |
| 4 000 000 000 | 33 554 432 | 119 | 40 577 024 |

**Alternativas descartadas**: `chunk_size` de 64 MiB (excede 64 MB decimal); 10 MiB (más
peticiones sin beneficio); calcular `ceil` (contradice la regla oficial `floor`).

---

## §10 Subida y `upload_url`

**Decisión**:

- Cada chunk se lee del archivo original con `seek` + lectura acotada a su tamaño (≤ 64 MiB) en un
  `bytes`; ese buffer se hashea (§6) y se envía con `Content-Type` (§8),
  `Content-Length = len(buffer)` y `Content-Range: bytes {first}-{last}/{video_size}`. El reintento
  de un chunk intermedio reenvía el mismo buffer. Nunca se carga el archivo entero ni se copia a
  disco. Pico de memoria ≈ un buffer.
- `UploadUrl`: envoltorio propio en `tiktok_gateway.py` (`__slots__`, `__repr__`/`__str__`
  → `UploadUrl([redacted])`, `reveal()` solo en la llamada `PUT`). No se importa `SecretUrl` de
  `media_delivery` para no acoplar TikTok a media delivery (FR-007). Vive solo en variables
  locales de `upload()`; nunca en el payload, el run, `submitted`, `details`, errores ni logs.
- El gateway envía el `PUT` sin `Authorization` y captura `httpx.HTTPError` → excepción semántica
  `from None` (las excepciones de httpx contienen la URL).
- `RedactTikTokSecrets` (Feature 012) se amplía: cualquier URL de un host `*.tiktokapis.com`
  cuya ruta contenga `upload` o cuya query contenga `upload` se sustituye **entera** por
  `[redacted TikTok upload URL]`; además se redactan parámetros `upload_token`/`upload_id`/
  `signature`. Se instala en los loggers HTTP existentes (`httpx`, `httpcore`, `httpx2`…). **[V1]**
  confirma la forma real del URL (registrando solo host y nombres de parámetros) y que los logs
  quedan limpios.
- El progreso (`report_bytes(confirmed=True)`) avanza solo con `206`/`201`.

**Confirmado en V1 (2026-10-14)**: el `upload_url` real es `https://open-upload-i18n.tiktokapis.com/…?upload_id=…&upload_token=…` (solo se registraron esquema, host y nombres de parámetros). La redacción lo cubre: la línea de `httpx2` del `PUT` quedó como `[redacted TikTok upload URL]` y ni logs ni base de datos contienen `upload_id=`/`upload_token=`. Se añadió ese formato a los tests de redacción.

**Validez de una hora**: `TikTokPublishSettings.upload_deadline = 50 min` desde `init`. Si antes del
write-ahead se supera, fallo determinado `tiktok_upload_expired` (no se envía el último chunk);
deja ≥ 10 min de margen para el último chunk.

**Alternativas descartadas**: streaming por generador sin buffer (impide hashear exactamente lo
enviado antes del write-ahead); persistir el URL para reanudar (prohibido).

---

## §11 Reintentos

**Chunks intermedios**: hasta **3 reintentos** del mismo chunk (esperas 2 s, 5 s, 10 s, en
rodajas interrumpibles) ante error de red, timeout, `5xx` o `429`. Agotados → fallo determinado
`tiktok_upload_failed`. `400`/`403`/`404` → determinado sin reintento (`403` →
`tiktok_upload_expired`). `416` → §12. Nunca se reinicializa.

**Último chunk** (cerrado por la spec, política conservadora): write-ahead → **un único**
`PUT` → cero reintentos. Solo `201` es una respuesta con significado propio (→ polling normal).
**Cualquier otra** respuesta o resultado — red, timeout, `5xx`, `4xx` (incluidos 400/403/404/416),
respuesta perdida o inesperada — **no** prueba ausencia de efecto remoto: no se reenvía, no se
crea otro Direct Post y solo se hace polling del `publish_id` original (§15) con la misma
interpretación: `PUBLISH_COMPLETE` → éxito; `FAILED` → determinado; `PROCESSING_UPLOAD` al agotar
la ventana → ambiguo; error de lectura o estado inesperado → ambiguo. El código HTTP del último
`PUT` se guarda solo como diagnóstico (nunca decide). `uploaded_bytes` nunca autoriza reenviar.
Esta semántica existe desde el Bloque 1 (pre-V1); el Bloque 2 solo amplía mensajes y taxonomía.

**Creator Info**: 1 reintento tras 2 s ante red/5xx en `prepare`. **Init**: 0 reintentos.
**Estado**: cada lectura del polling es independiente; errores temporales se toleran dentro de la
ventana (§15).

---

## §12 `Content-Range` y política ante `416`

**Garantías oficiales**: `416` = el `Content-Range` no coincide con el progreso real; las
respuestas *pueden* incluir `Content-Range: bytes 0-{uploaded}/{total}`.

**Semántica (confirmada en V2 real, 2026-10-14; coincide con la documentación oficial)** — la
cabecera tiene significados **distintos** en la petición y en la respuesta:

| | Forma | Segundo número |
|---|---|---|
| Petición (`PUT`) | `bytes {first}-{last}/{total}` | `last`: offset 0-based **inclusivo** del último byte enviado (`first` también 0-based inclusivo) |
| Respuesta de TikTok | `bytes 0-{accepted_bytes}/{total}` | **número de bytes aceptados** = siguiente offset (fin exclusivo); **no** es el índice del último byte |

Por tanto, un chunk `[first, last]` aceptado se responde con `accepted_bytes == last + 1`.
Observado en V2 (vídeo de 67 686 392 B, dos chunks): petición `bytes 0-33554431/67686392` →
`206` con `bytes 0-33554432/67686392`; petición `bytes 33554432-67686391/67686392` → `201` con
`bytes 0-67686392/67686392`. El gateway lo expone como `UploadProgress(accepted_bytes, total)`
(`total = None` si TikTok responde `*`; `None` entero si falta, es ilegible o no empieza en 0).
En `206`/`201` es solo diagnóstico: el avance lo deciden el código HTTP y el plan de chunks.

**`uploaded_bytes` del estado**: en V1 (un chunk) no apareció; en V2 apareció durante
`PROCESSING_UPLOAD` con valor igual al tamaño total y desapareció en `PUBLISH_COMPLETE`, lo que
encaja con un **recuento de bytes** (no un índice final). Aun así no es requisito, no se asume
presente, no decide nada (ni el `416` ni el último chunk) y solo se guarda como diagnóstico
(`remote_uploaded_bytes`). El fake lo envía en `PROCESSING_UPLOAD` y lo omite en
`PUBLISH_COMPLETE`.

**Decisión** (conservadora; solo chunks intermedios; el último nunca se reenvía):

- Caso esperado: se reintentó el chunk *k* `[first, last]` tras perder la respuesta de un envío
  que TikTok sí recibió. El chunk *k* se da por aceptado y se continúa con *k+1* **solo** si la
  respuesta `416` trae un `Content-Range` legible con `accepted_bytes == last + 1` **y**
  `total == video_size`. Como los chunks se envían en orden desde el offset confirmado
  (`first`), ese es también el único valor que ni retrocede ni salta.
- Cualquier otro caso — sin `Content-Range`, ilegible, que no empieza en 0, `accepted_bytes ==
  last` (error típico de confundir semánticas), menor, mayor (aunque coincida con el fin de otro
  chunk), `total` distinto o `*` — → fallo determinado `tiktok_upload_failed` antes del
  write-ahead. No se consulta `uploaded_bytes` del estado como alternativa.
- Un `416` nunca provoca un nuevo Direct Post, un salto de offset, bytes fuera de orden ni el
  reenvío del último chunk. No se intenta recuperar estados parciales.

**Alternativas descartadas**: deducir el offset de `uploaded_bytes`; avanzar a cualquier offset
que TikTok declare; reiniciar la subida desde 0 en el mismo `upload_url` (comportamiento no
documentado).

---

## §13 `publish_id` y TikTok Publish Run

**Decisión**: tabla `tiktok_publish_runs` (una fila por intento, PK = `attempt_id`); detalle en
[data-model.md](data-model.md). Secuencia en `upload()`:

1. crear el run (`phase = preparing`, plan de chunks, `video_size`) y confirmar;
2. `init_video_post` **una vez** (`phase = initializing`); cualquier error → fallo determinado
   (sin `upload_url` no puede publicarse nada; un `publish_id` huérfano caduca solo);
3. guardar `publish_id` + `initialized_at` (`phase = uploading`) **con commit antes del primer
   byte**; si no se puede → determinado, no se sube nada;
4. chunks intermedios (actualizando `confirmed_bytes`);
5. write-ahead (§14) y último chunk;
6. polling y resultado (`phase = succeeded | failed`, `last_remote_status`, `fail_reason`).

`publish_id` es `UNIQUE`; nunca se crea otro para el mismo intento ni se reutiliza entre intentos.
No va a `external_id` ni a `details` del intento (no se expone al frontend; §21).

---

## §14 Punto irreversible

**Decisión**: write-ahead = `reporter.enter_final_chunk()` (commit de `AttemptStage.FINAL_CHUNK`,
genérico, ya en `UNCERTAIN_STAGES`) **y** run `phase = final_chunk`, `final_chunk_started_at`
(commit). Ambos deben confirmarse antes del `PUT` final; si cualquiera falla → fallo determinado y
no se envía. Un único chunk: write-ahead antes del único `PUT`. Multi-chunk: inmediatamente antes
del último. Tras el último `PUT`, **sea cual sea su resultado** (`201` o cualquier otro):
`reporter.enter_finalizing()` (`FINALIZING`, también incierto), run `phase = processing` y
`final_chunk_http_status` (solo diagnóstico), y polling del `publish_id`. **Nunca** se usa `leave_final_chunk()` ni `enter_processing()` (el primero
existe para YouTube; el segundo marcaría la fase como no incierta, y tras el `201` TikTok ya está
publicando). No se crean estados nuevos de `Publication` ni de etapa.

---

## §15 Polling

**Decisión** (`TikTokPublishSettings`):

- primera lectura 3 s después del `201` o de cualquier otro resultado del último chunk (§11);
- esperas sucesivas `(3, 5, 5, 10, 10, 15, 15)` s y después cada 30 s;
- tiempo máximo `processing_timeout = 10 min` desde el envío del último chunk;
- ≈ 25 lecturas en 10 min; máximo ≈ 12/min en el primer minuto (≪ 30/min);
- sin jitter (un único usuario, sin riesgo de sincronización);
- esperas en rodajas de 1 s con `reporter.should_stop()`;
- `429` → la siguiente espera se duplica (sin superar 60 s); red/5xx/`access_token_invalid`
  (renovado por `call_with_token`) → se sigue intentando dentro de la ventana.

**Observado en V1 (2026-10-14, vídeo de 4,27 MB, un chunk)**: `init` → `PUT` (`201
Created`) ≈ 2 s; secuencia real `PROCESSING_UPLOAD` (1.ª lectura, 3 s después del `PUT`) →
`PUBLISH_COMPLETE` (2.ª lectura, 3 s más tarde); ≈ 9 s desde el write-ahead. Dos lecturas de
estado en total. La ventana de 10 min se mantiene.

Al agotar la ventana o al cerrarse la aplicación: `PROCESSING_UPLOAD`, estado desconocido o
error de lectura → **ambiguo** (`tiktok_processing_pending` / `tiktok_result_uncertain`), sin
reintento automático. 10 min es ajustable tras medir en **[V1]**; mantiene ocupado el hilo del
intento (aceptado, como el vídeo de Threads).

---

## §16 Estado: DTO y mapeo

`PublishStatus(status: str, fail_reason: str | None, post_ids: tuple[int, ...], uploaded_bytes:
int | None)`; `fail_reason` solo si coincide con `^[a-z_]{1,64}$` (si no → `"unknown"`);
`publicaly_available_post_id` (grafía oficial) lista de enteros; elementos no enteros → se ignoran
con aviso; `uploaded_bytes` entero ≥ 0 o `None`.

| Estado | Interpretación |
|---|---|
| `PROCESSING_UPLOAD` | seguir esperando |
| `PUBLISH_COMPLETE` | éxito: `PUBLISHED`; `external_id = str(id)` si hay **exactamente un** post ID, si no `None`; `external_url = None` siempre |
| `FAILED` | fallo determinado con `fail_reason` mapeado (§19) |
| `PROCESSING_DOWNLOAD`, `SEND_TO_USER_INBOX`, otros | inesperado: nunca éxito; tras el write-ahead → ambiguo inmediato |

`PUBLISH_COMPLETE` sin post ID (normal con `SELF_ONLY`) no es error; aviso informativo
`tiktok_private_post_no_link`. No se construye permalink, no se usa `video.list`, no se listan
posts. `refresh_details` es no-op (devuelve el `outcome`). `release` es no-op (no hay recursos
temporales).

---

## §17 Reconciliación: extensión neutral

**Inspección**: `Publisher.reconcile` devuelve `Reconciliation | None` y `reconcile_uncertain`
solo sabe persistir un éxito (`persist_reconciled_success`). No hay forma de expresar
"la plataforma confirma que no se publicó".

**Decisión**: añadir al núcleo un tipo neutral `ReconciledFailure(code: str, message: str)` y
ampliar el tipo de retorno a `Reconciliation | ReconciledFailure | None`. `reconcile_uncertain`
llama a `persist_reconciled_failure(session, attempt_id, failure)`, que, solo si el intento sigue
`FAILED` con `outcome_determined = False` y la publicación `FAILED`, pone `outcome_determined =
True`, `error_code`, `error_message` (la publicación sigue `FAILED`). Así desaparece la exigencia
de reconocimiento manual (`needs_manual_review` = falso).

Impacto: YouTube, Instagram y Threads no cambian (nunca devuelven `ReconciledFailure`); el tipo
anterior sigue siendo válido (compatibilidad hacia atrás). Tests: `FakePublisher` que devuelve
`ReconciledFailure` (núcleo), y suites de reconciliación existentes en verde.

`TikTokPublisher.reconcile`: solo si el run tiene `publish_id` y `final_chunk_started_at`; una
lectura de estado con `call_with_token` → `PUBLISH_COMPLETE` → `Reconciliation(published_at =
final_chunk_started_at, outcome sin URL)`; `FAILED` → `ReconciledFailure`; otro → `None`. Cero
`init`, cero `PUT`, cero listados. Se dispara con los puntos existentes: `GET publish-check` y
`Publish now` (y por tanto al abrir el detalle tras un reinicio).

---

## §18 Recuperación tras reinicio

Sin red ni lógica TikTok (genérico `recover_interrupted_attempts`, por `AttemptStage`):

| Datos persistidos | Etapa genérica | Resultado |
|---|---|---|
| sin run o sin `publish_id` | `preparing` | `FAILED` determinado (`interrupted`) |
| `publish_id`, sin write-ahead | `preparing`/`uploading` | `FAILED` determinado (`interrupted`); no se reanuda (URL perdido) |
| `final_chunk_started_at` | `final_chunk`/`finalizing` | `FAILED` ambiguo; reconciliación posterior con el `publish_id` (§17) |

El run se cierra perezosamente: `reconcile` actualiza `phase`/`last_remote_status` en la misma
transacción que la reconciliación; un run de un intento determinado queda como diagnóstico.

---

## §19 Taxonomía de errores

Efecto de conexión vía Feature 012: **R** = `mark_reconnect_required`/`mark_scope_not_authorized`;
**—** = ninguno. Antes del write-ahead todo fallo es determinado.

| Código TikTok / señal | HTTP | Fase | Categoría | Reintento | Conexión | Código AutoPublisher / mensaje |
|---|---|---|---|---|---|---|
| `access_token_invalid` | 401 | creator info / estado | auth | renovar+1 (`call_with_token`) | R si persiste | `tiktok_reconnect_required` |
| `access_token_invalid` | 401 | init | auth | no | — (la próxima lectura renueva) | `tiktok_unavailable` "TikTok rejected the session; try again" |
| `scope_not_authorized` | 401 | cualquiera | auth | no | R | `tiktok_reconnect_required` |
| `auth_removed` (`fail_reason`) | — | estado | auth | no | R | `tiktok_publish_failed` "TikTok access was removed" (determinado) |
| `invalid_param` | 400 | init | negocio | no | — | `tiktok_init_failed` |
| `privacy_level_option_mismatch` | 403 | init | negocio | no | — | `tiktok_privacy_invalid` |
| `spam_risk_too_many_posts` | 200/403 | creator info / init / `fail_reason` | negocio | no | — | `tiktok_creator_cannot_post` "daily limit reached" |
| `spam_risk_user_banned_from_posting` | 200/403 | ídem | negocio | no | — | `tiktok_creator_cannot_post` |
| `reached_active_user_cap` | 200/403 | ídem | negocio | no | — | `tiktok_creator_cannot_post` "app daily cap" |
| `unaudited_client_can_only_post_to_private_accounts` | 403 | init | negocio | no | — | `tiktok_private_account_required` |
| `url_ownership_unverified` | 403 | init | inesperado (no usamos URL) | no | — | `tiktok_unexpected_response` (stop condition) |
| `spam_risk_text`, `spam_risk` | — | `fail_reason` | negocio | no | — | `tiktok_content_rejected` |
| `rate_limit_exceeded` | 429 | creator info / init | temporal | no | — | `tiktok_rate_limited` |
| `rate_limit_exceeded` | 429 | estado | temporal | espera ×2 en la ventana | — | (ambiguo si se agota) |
| 5xx / red / timeout | — | creator info | temporal | 1 | — | `tiktok_unavailable` |
| 5xx / red / timeout | — | init | temporal | no | — | `tiktok_unavailable` |
| `invalid_publish_id`, `token_not_authorized_for_specified_publish_id` | 400 | estado | inesperado | no | — | ambiguo `tiktok_result_uncertain` |
| PUT 400 / 404 | — | chunk intermedio | determinado | no | — | `tiktok_upload_failed` |
| PUT 403 | — | chunk intermedio | determinado | no | — | `tiktok_upload_expired` |
| PUT 416 | — | chunk intermedio | §12 | §12 | — | `tiktok_upload_failed` |
| PUT 5xx / red / 429 | — | chunk intermedio | temporal | 3 | — | `tiktok_upload_failed` |
| PUT ≠ `201` (red, timeout, 4xx, 5xx, inesperado) | — | **último chunk** | incierto | **0** | — | solo estado del `publish_id`: `PUBLISH_COMPLETE` éxito, `FAILED` determinado, resto ambiguo `tiktok_result_uncertain` / `tiktok_processing_pending` (§11) |
| `file_format_check_failed`, `duration_check_failed`, `frame_rate_check_failed`, `picture_size_check_failed` | — | `fail_reason` | negocio | no | — | `tiktok_video_rejected` |
| `internal` | — | `fail_reason` | temporal remoto | no automático | — | `tiktok_publish_failed` (determinado: TikTok dice `FAILED`) |
| `publish_cancelled` | — | `fail_reason` | negocio | no | — | `tiktok_publish_failed` |
| `video_pull_failed`, `photo_pull_failed` | — | `fail_reason` | inesperado (no usamos pull) | no | — | `tiktok_publish_failed` |

Mensajes en inglés, fijos y seguros; `log_id` puede añadirse al registro, nunca respuestas crudas.

---

## §20 Scheduler, armado y consentimiento

**Inspección**: armar es genérico (`PATCH /publications/{id}` con `auto_publish_enabled`, y en la
creación); `_set_consent` solo valida fecha y `ensure_can_prepare`. El núcleo no puede conocer el
consentimiento TikTok.

**Decisión**: extensión neutral mínima del protocolo: `Publisher.arming_problems(session,
publication) -> list[PublishProblem]` (sin red). YouTube, Instagram y Threads devuelven `[]`.
`_set_consent` y la creación con `auto_publish_enabled = true` la consultan vía
`app.state.publishers` (como ya hace `text-publications` con `accepts_text_only`) y, si hay
problemas, rechazan el armado (`409`, campo `auto_publish_enabled`). En la creación por lotes
(`POST /contents/{id}/publications` con varias cuentas) se mantiene la semántica **todo o nada**
existente: si alguna cuenta TikTok tiene problemas de armado no se crea ninguna publicación y se
responde `409` con `fields[]` por cuenta (`account_ids`, mensaje que identifica la cuenta TikTok y
la acción necesaria); nunca creación parcial. TikTok devuelve problemas si:
opciones incompletas o inválidas, caption inválido o consentimiento ausente/caducado.

Flujo UI "Schedule" para TikTok: el usuario fija la fecha (genérico), completa opciones, marca la
declaración (`POST …/tiktok-consent`) y activa auto-publish (genérico). Cualquier edición posterior
material cambia la huella y el consentimiento queda inválido **sin desarmar** la publicación ni
añadir hooks TikTok a los endpoints genéricos de edición:

- la publicación sigue `SCHEDULED` y armada; el panel TikTok muestra `consent.state = "stale"` y
  pide reconfirmar ("Your changes need a new confirmation before this video can be published");
- a su hora, el scheduler llama a `start_publication` → `local_check` → `TikTokPublisher.check()`
  (**sin red**), que detecta `tiktok_consent_required` **antes** de `prepare`, de Creator Info,
  de obtener credenciales, de pasar a `PUBLISHING` y de cualquier efecto remoto: no hay
  `video/init/`, ni bytes enviados, ni intento creado; ninguna opción cambia;
- el scheduler registra el error automático genérico de la Feature 007 con un mensaje local
  ("AutoPublisher needs you to confirm the TikTok declaration again"), nunca presentado como un
  rechazo de TikTok;
- `auto_start_blocker` no se bloquea por un error registrado: si el usuario reconfirma el
  consentimiento sobre la huella actual (`POST tiktok-consent`) antes de la hora o dentro de la
  ventana automática de la Feature 007 (10 min), el **siguiente reintento automático elegible**
  —como máximo tras `AUTO_PUBLISH_RETRY_INTERVAL` (hoy 120 s) desde el fallo registrado— la
  ejecuta **sin reprogramarla** (sin retry específico de TikTok). Si
  la ventana ya pasó, aplica la regla genérica de publicación vencida (reprogramar), igual que
  cualquier otro fallo de preflight.
- comportamiento esperado (documentado, no se optimiza): mientras siga armada con consentimiento
  caducado dentro de la ventana, cada reintento automático (hoy cada 120 s) registra un warning
  de log del scheduler.

Al ejecutarse con consentimiento vigente: `start_publication(trigger=SCHEDULED)` → `local_check` →
`prepare` (Creator Info reconsultado, privacidad/interacciones/duración/huella/digest) → mismo
`upload`. Carreras manual/scheduler, ciclos concurrentes, pausa y ambigüedad sin reintento:
mecanismos genéricos existentes (UPDATE condicional, índice único de intentos `running`,
`requires_remote_check`, `auto_start_blocker`).

**Alternativas descartadas**: desarmar automáticamente al invalidarse el consentimiento (requiere
hooks del núcleo en cada edición); exigir `check()` completo para armar (cambiaría el
comportamiento de YouTube/Instagram/Threads).

---

## §21 API y frontend

**Decisión**: endpoints TikTok específicos (detalle en [contracts/api.md](contracts/api.md)):
`GET`/`PUT /api/publications/{id}/tiktok-options`, `GET /api/publications/{id}/tiktok-creator-info`,
`POST /api/publications/{id}/tiktok-consent`. Ejecución, intentos, publish-check y edición de
descripción/hashtags: endpoints genéricos existentes. El caption, su conteo, la huella actual y
el estado del consentimiento van en `tiktok-options` (sin red). `publish_id` no se expone (no
aporta al usuario; está en la base local para diagnóstico); `upload_url` nunca.

Frontend: `TikTokPublishOptions.tsx` dentro de `PublicationDetail` (`"tiktok"` en
`PUBLISHING_PLATFORMS`), con creator header, preview del vídeo (componente/URL de media
existente), caption y contador, privacidad sin default, interacciones, disclosure, AIGC,
declaración + checkbox, avisos de entorno no auditado y de procesamiento. `Publish now` y la
activación de auto-publish siguen siendo los botones genéricos; quedan deshabilitados por
`publish-check`/`arming_problems` hasta que todo esté listo.

**Consentimiento en `Publish now` (FR-024 estricto)**: para una publicación TikTok,
`PublishNowDialog` muestra siempre la declaración vigente (texto y enlaces de `tiktok-options`)
con un checkbox obligatorio, aunque ya exista un consentimiento guardado con la misma huella. Al
confirmar, el frontend llama primero a `POST tiktok-consent` con la huella y versión mostradas
(registra de nuevo `consented_at`) y después al `POST publish` genérico. Si la huella no
coincide (`409 tiktok_consent_stale`), no se publica y el panel pide revisar. El backend exige
consentimiento vigente por huella en `check()`/`prepare()`; el endpoint genérico de publicación
no cambia (sin campos TikTok en `PublishRequest`). `submitted` del intento guarda
`consented_at` para auditar el momento de la confirmación.

**Limitación consciente**: la confirmación expresa en cada `Publish now` la exige el diálogo de
la UI. El backend solo valida que exista un consentimiento **vigente por huella**; una llamada
directa a la API de publicación con una huella aún válida no tiene un concepto adicional de
"consentimiento reciente" ligado al diálogo. Es una decisión deliberada para no introducir
campos TikTok en el `PublishRequest` genérico, aceptable en el modelo actual de AutoPublisher
(aplicación local de un único usuario, sin API pública). **No** es una garantía válida para un
futuro sistema multiusuario o una API pública, que requeriría revisar este diseño.

**Preview**: el `<video>` inline de `ContentDetail.tsx` se extrae a un componente neutral
`MediaPreview.tsx` (misma lógica de URL de media), usado por `ContentDetail` y por el panel
TikTok, sin rediseño.

**Alternativas descartadas**: botones de publicación propios de TikTok (duplican el flujo
genérico); un campo `tiktok_consent` en `PublishRequest` genérico (filtra TikTok al núcleo).

---

## §22 Pruebas offline

`FakeTikTok` (existente, httpx `MockTransport`) se amplía con endpoints `creator_info`, `init`,
`upload` (host de subida falso, `upload_id`/`upload_token` en la query para probar redacción) y
`status`: respuestas programables por chunk (206/201/4xx/5xx/timeout/sin `Content-Range`/416 con
`Content-Range`), secuencias de estados, registro de peticiones (para afirmar "init ≤ 1",
"último chunk ≤ 1", ausencia de `Authorization` en el `PUT`, cabeceras `Content-Range`). Más:
`FakeClock`, `sleep` instantáneo, `probe_video_streams` simulado, archivos de prueba generados
(tamaños pequeños; los planes grandes se prueban con `plan_chunks` puro y un `chunk_size`
inyectable en settings para multi-chunk con archivos de pocos KB), `InMemoryCredentialStore`.
Estrategia vigente: tests dirigidos durante el desarrollo, suite completa al final/CI; no se
optimiza pytest ahora.
