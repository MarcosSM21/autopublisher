# Research: TikTok Upload to Inbox

**Feature**: `014-tiktok-inbox-upload` | **Fecha**: 2026-10-15

Decisiones técnicas de la feature. Cada sección: **Decision**, **Rationale**, **Alternatives
considered**. Las referencias `013 §N` apuntan a
[specs/013-tiktok-direct-post/research.md](../013-tiktok-direct-post/research.md), cuyas
decisiones siguen vigentes salvo que aquí se diga otra cosa.

## §0 Documentación oficial reconfirmada (2026-10-15)

Fuentes: TikTok for Developers — *Content Posting API: Upload Content — Get Started*, *Upload
Content API reference* (`content-posting-api-reference-upload-video`), *Get Post Status*,
*Content Sharing Guidelines*.

| Tema | Hecho oficial | Consecuencia |
|---|---|---|
| Endpoint | `POST https://open.tiktokapis.com/v2/post/publish/inbox/video/init/` | constante nueva en el gateway |
| Scope | `video.upload` (la app debe tenerlo aprobado y el usuario concedido) | ampliación del OAuth (§2) |
| Body | **Solo `source_info`**: `source` (`FILE_UPLOAD`/`PULL_FROM_URL`), `video_size`, `chunk_size`, `total_chunk_count` | ni `post_info`, ni caption, ni privacidad, ni AIGC (FR-014) |
| Respuesta | `data.publish_id` (≤ 64), `data.upload_url` (≤ 256, válido **1 h**) | mismos DTO y validaciones que Direct Post |
| Rate limit init | 6 peticiones/min por access token | igual que Direct Post; init nunca se repite |
| Errores init | `invalid_param` (400), `spam_risk_too_many_pending_share` (403, "at most 5 pending shares within any 24-hour period"), `spam_risk_user_banned_from_posting` (403), `url_ownership_unverified` (403), `access_token_invalid` (401), `scope_not_authorized` (401, falta `video.upload`), `rate_limit_exceeded` (429), 5xx | nuevo código de rechazo `spam_risk_too_many_pending_share` (§9) |
| Subida | Mismo `PUT` con `Content-Type`, `Content-Length`, `Content-Range`, URL completa | reutilización íntegra (§4) |
| Estado | `POST /v2/post/publish/status/fetch/`, scope **`video.upload` o `video.publish`**, 30/min | `call_with_token` existente |
| `SEND_TO_USER_INBOX` | solo flujo Upload: notificación enviada al inbox del creador para completar el borrador en el editor de TikTok | Ready in TikTok (§6) |
| `PUBLISH_COMPLETE` (Upload) | el creador pulsó la notificación y publicó desde el flujo de edición | `PUBLISHED` (§6) |
| Varios posts | "Creators can use one uploaded draft to make multiple pieces of content" | nunca un único `external_id` (§7) |
| `publicaly_available_post_id` | solo posts públicos que pasaron moderación (minutos u horas) | no autoritativo; no se mapea (§7) |
| UX obligatoria | "inform users that they must click on inbox notifications to continue the editing flow in TikTok and complete the post" | texto fijo en la UI (§12) |
| Cliente no auditado | Las *Content Sharing Guidelines* solo atan `SELF_ONLY`/cuenta privada al **Direct Post**; nada dice del flujo Upload | **confirmado en V1b (2026-10-15)**: con cuenta pública y cliente Sandbox no auditado, el init se acepta y el vídeo llega al inbox |
| Webhooks | `post.publish.inbox_delivered`, `post.publish.complete` (`publish_type = INBOX_SHARE`) | fuera de alcance: app local sin endpoint público; solo `Check status` |

## §1 Arquitectura: un publisher, dos modos

**Decision**: Mantener un único `TikTokPublisher` registrado para `Platform.TIKTOK`. El modo
(`DIRECT_POST` / `INBOX_UPLOAD`) se lee de `tiktok_publication_options.mode` en
`check`/`prepare`, se congela en el payload y en `tiktok_publish_runs.mode`, y decide la
semántica. La transferencia `FILE_UPLOAD` común se extrae a un módulo nuevo
`app/tiktok_transfer.py`; la semántica Inbox vive en `app/tiktok_inbox.py`.

- `tiktok_transfer.py` (neutral entre modos): `FileUploadTransfer` con la secuencia existente
  `publish_id` commit → chunks intermedios (reintentos, `416`) → verificación de digest →
  write-ahead → último chunk único → polling acotado, parametrizada por (a) la llamada de
  inicialización y (b) un **intérprete de estado** que decide si un estado es terminal.
- `tiktok_publishing.py`: el publisher, el despacho por modo y la semántica Direct Post
  (sin cambios observables).
- `tiktok_inbox.py`: intérprete Inbox, mensajes, `follow_up` (Check status) y la vista de entrega.

**Rationale**: el registro genérico es por plataforma; dos publishers para la misma plataforma
romperían el registro y el despacho del núcleo. Extraer solo la transferencia cumple FR-004 sin
duplicar ~400 líneas y sin mezclar semánticas (FR-005).

**Alternatives considered**: (a) un segundo publisher `TikTokInboxPublisher` → requiere un
registro por (plataforma, modo) en el núcleo, cambio no neutral; (b) copiar `_run`/`_poll` →
duplicación prohibida por FR-004; (c) un flag `if inbox` disperso por `_run` → mezcla semánticas.

## §2 Scopes base y capacidad `video.upload`

Estado actual (Feature 012, inspeccionado): `tiktok_oauth.SCOPES = ("user.info.basic",
"video.publish")` se usa a la vez como scopes **solicitados** (URL de autorización), **exigidos**
en el callback (`has_required_scopes`) y **exigidos** en la renovación (`_renew` →
`reconnect_required` si faltan); `TikTokScopeMissing` solo admite nombres de `REQUIRED_SCOPES`;
`_permissions` lista los concedidos filtrando por `SCOPES`.

**Decision**: separar tres conceptos en `tiktok_oauth.py`:

| Constante | Valor | Uso |
|---|---|---|
| `BASE_SCOPES` | `user.info.basic`, `video.publish` | conexión utilizable; renovación (`_renew`) y lecturas siguen exigiendo exactamente esto (reglas de 012 intactas) |
| `UPLOAD_SCOPE` | `video.upload` | capacidad `inbox_upload` |
| `REQUESTED_SCOPES` | base + `video.upload` | URL de autorización; el **callback** exige todos (`has_requested_scopes`) |
| `KNOWN_SCOPES` | = `REQUESTED_SCOPES` | filtro de `TikTokScopeMissing.scope` y de `_permissions.granted` |

- `TikTokCredential.has_required_scopes()` sigue significando **base** (renovación); se añade
  `has_requested_scopes()` (callback) y `can_upload_to_inbox()`.
- Callback de `Connect`/`Reconnect` sin los tres → `tiktok_permission_missing` **antes** de
  `complete_connection`: el secreto, la fila y el estado previos no se tocan (la credencial nueva
  solo existe en memoria y se descarta). Así ya funciona el flujo actual; se añaden tests de
  regresión explícitos con una conexión previa de dos scopes.
- Renovación: si faltan scopes base → reglas actuales de 012. Si solo falta `video.upload` → se
  guarda la credencial (TikTok es la fuente de verdad), la conexión sigue `Connected` y la
  capacidad pasa a no disponible.
- `TikTokPermissionsRead` gana `capabilities: {"direct_post": bool, "inbox_upload": bool}`
  (derivadas de los scopes concedidos). Mensajes de "grant both permissions" pasan a "grant every
  requested permission".
- `scope_not_authorized` en `inbox/video/init/` → fallo determinado
  `tiktok_upload_permission_missing` **sin** `mark_scope_not_authorized` (no degrada la conexión);
  en Direct Post sigue el comportamiento de 013.

**Rationale**: FR-006–FR-009 y la aclaración 1: la ausencia de `video.upload` nunca produce
`Reconnect required`; el callback mantiene la regla de rechazar concesiones parciales.

**Alternatives considered**: (a) exigir `video.upload` también al renovar → rompería conexiones
antiguas de dos scopes; (b) aceptar concesiones parciales en el callback → contradice FR-007;
(c) tabla de capacidades persistida → innecesaria: se deriva del secreto.

## §3 Modo TikTok y migración

**Decision**: columna `tiktok_publication_options.mode VARCHAR(16) NULL` **sin server default**,
CHECK `mode IS NULL OR mode IN ('DIRECT_POST','INBOX_UPLOAD')`. Migración `0013`:

1. añadir la columna (NULL);
2. `UPDATE tiktok_publication_options SET mode = 'DIRECT_POST'` (todas las filas existentes);
3. `INSERT` de una fila de opciones con valores por defecto de 013 y `mode = 'DIRECT_POST'` para
   cada publicación existente cuya cuenta es TikTok y que aún no tenía fila (cualquier estado,
   incluidas históricas), con `updated_at` = momento de la migración.

Después de `0013`, toda publicación TikTok anterior tiene `DIRECT_POST`; las nuevas no tienen fila
(o la tienen con `mode NULL`) = **sin decidir**. `PUT tiktok-options` acepta `mode` (nullable).
`check`, `arming_problems` y el diálogo de publicación exigen modo elegido
(`tiktok_mode_required`). El modo solo se edita en `EDITABLE_STATUSES` (no en `PUBLISHING`,
`AWAITING_USER_ACTION` ni `PUBLISHED`).

**Rationale**: aclaración 2 (existentes = Direct Post, nuevas sin default). Insertar filas para
las publicaciones sin opciones evita que una publicación antigua "sin fila" se lea como sin
decidir.

**Alternatives considered**: (a) server default `DIRECT_POST` → prohibido; (b) modo en
`publications` → prohibido (FR-001); (c) no insertar filas y tratar "sin fila" como Direct Post →
ambiguo con las nuevas.

## §4 Transferencia `FILE_UPLOAD` compartida

**Decision**: `FileUploadTransfer.run(init, interpret)` en `tiktok_transfer.py` encapsula, sin
cambios de comportamiento, lo que hoy hace `TikTokPublisher._run/_send_chunk/_send_last_chunk/
_poll` (013 §9–§15): plan de chunks (`plan_chunks`), `UploadDigest`, `UploadUrl` solo en memoria
y redactada, reintentos 2/5/10 s de chunks intermedios, política estricta de `416`, deadline de
50 min, write-ahead (`enter_final_chunk` + run `final_chunk`), último chunk exactamente una vez,
`enter_finalizing`, polling 3 s → (3,5,5,10,10,15,15) → 30 s hasta 10 min con 429 duplicando la
espera. Los puntos variables son:

- `init(token, source_info) -> InitResult` (Direct Post: `init_video_post` con `post_info`;
  Inbox: `init_inbox_video` solo con `source_info`);
- `interpret(status) -> Continue | Done(outcome) | Fail(mapping)` por modo;
- el mapeo de errores de init por modo (§9).

Los tests existentes de Direct Post (`test_tiktok_publish`, `test_tiktok_anti_duplicates`,
`test_tiktok_upload_errors`, `test_tiktok_recovery`, `test_tiktok_reconcile`,
`test_tiktok_publish_secrets`) se ejecutan **sin modificar** tras la extracción como prueba de
equivalencia, antes de añadir Inbox.

**Rationale**: FR-004/FR-015 y anti-duplicados heredado.

**Alternatives considered**: herencia de clases publisher → acopla semánticas; función con flag
de modo → mezcla (§1).

## §5 Preflight Inbox

**Decision**: `check` (sin red) en modo Inbox: conexión utilizable (reglas 012) + capacidad
`inbox_upload` (`tiktok_upload_permission_missing`, con mensaje "Reconnect the TikTok account to
grant video.upload"), modo elegido, Content vídeo, archivo, ffprobe y la matriz de vídeo de 013
§8 **sin** `max_video_post_duration_sec` (no hay Creator Info): contenedor, codec, 23–60 FPS
(tolerancia 22.99–60.01), 360–4096 px, ≤ 4 000 000 000 B, ≤ 600 s. No se exigen privacidad,
interacciones, disclosure, AIGC, caption ni consentimiento. `prepare`: sin Creator Info; SHA-256
en streaming == `Content.checksum` (como 013 §6); `submitted` = `{mode, source_info, video
summary}`.

**Rationale**: FR-010/FR-011; la documentación del flujo Upload no exige UX de Direct Post y el
límite de duración propio de la cuenta lo aplica TikTok en su editor.

**Alternatives considered**: consultar Creator Info para la duración → requiere `video.publish`
y no es parte del flujo Upload; podría rechazar vídeos que el editor acepta.

## §6 Estados, `AWAITING_USER_ACTION` y transiciones

**Decision**: estado genérico nuevo `PublicationStatus.AWAITING_USER_ACTION =
"awaiting_user_action"` y extensión neutral mínima del núcleo (`publishing.py`):

- `PublishOutcome.awaiting_user_action: bool = False`. `persist_success` con `True`: intento
  `succeeded`/`done`, `outcome_determined = True`, sin `external_id`/`external_url`;
  publicación → `AWAITING_USER_ACTION`, `published_at = NULL`.
- `Reconciliation.published_at` pasa a `datetime | None`; `persist_reconciled_success` con
  `outcome.awaiting_user_action` lleva `FAILED → AWAITING_USER_ACTION` (en vez de `PUBLISHED`).
- Nuevo método del protocolo `Publisher.follow_up(session, publication, attempt, ctx) ->
  UserActionCompleted | UserActionFailed | None` (YouTube/Instagram/Threads: `None`, nunca
  llamado porque nunca producen el estado). `UserActionCompleted(published_at)`;
  `UserActionFailed(code, message)`; `None` = sigue esperando. Errores temporales se propagan.
- `follow_up_publication(...)` del núcleo: exige `status == AWAITING_USER_ACTION` y último
  intento `succeeded`; llama una vez a `follow_up`; persiste con `UPDATE ... WHERE status =
  'awaiting_user_action'` (condicional, idempotente): `PUBLISHED` + `published_at` o `FAILED`.
  **Nunca** modifica `publication_attempts` ni crea intentos.

Reglas genéricas del estado (FR-019a): no está en `ELIGIBLE_STATUSES` (sin `Publish now`);
`ensure_editable` lo rechaza (`publication_not_editable`), también `cancel`; no es
`HISTORY_STATUSES` → sigue contando en el índice único de publicación activa por
contenido+cuenta (impide crear otra publicación del mismo vídeo a la misma cuenta mientras
espera); el scheduler (`status == SCHEDULED`) y `recover_interrupted_attempts` (`RUNNING`) no lo
ven; no ocupa concurrencia. CHECKs de `publications`: `status_valid` lo incluye;
`status_matches_schedule` lo trata como `published`/`failed` (fecha solo histórica);
`published_at_matches_status` se mantiene (`published_at` NULL). Orden de la cola: rango propio
entre `PUBLISHING` y `FAILED`.

Transiciones Inbox:

| Observado | Momento | Intento | Publicación |
|---|---|---|---|
| `PROCESSING_UPLOAD` | polling | running (`finalizing`) | `PUBLISHING` |
| `SEND_TO_USER_INBOX` | polling o reconcile | `succeeded` | `AWAITING_USER_ACTION` |
| `PUBLISH_COMPLETE` | polling o reconcile | `succeeded` | `PUBLISHED` |
| `PUBLISH_COMPLETE` | Check status | sin cambios (`succeeded`) | `AWAITING_USER_ACTION → PUBLISHED` |
| `FAILED` | polling | `failed` determinado | `FAILED` |
| `FAILED` | Check status | sin cambios (`succeeded`) | `AWAITING_USER_ACTION → FAILED` |
| `SEND_TO_USER_INBOX` | Check status | sin cambios | sin cambios |
| desconocido/`PROCESSING_DOWNLOAD` | polling | ambiguo | `FAILED` (reconciliable) |
| desconocido/`PROCESSING_UPLOAD` | Check status | sin cambios | sin cambios (registrado como inesperado) |

`published_at` de `UserActionCompleted` = momento de la observación (TikTok no da la hora real).

**Rationale**: aclaración Q1 + aclaración 3 (terminal para la ejecución, no para el ciclo de
vida; intento de entrega intacto).

**Alternatives considered**: reutilizar `persist_reconciled_*` para el Check status → reescriben
el intento; `PUBLISHED` + subestado TikTok → rechazado por el usuario (Q1).

## §7 Identidad remota y varios posts

**Decision**: en modo Inbox no se rellena `external_id` ni `external_url` nunca. Si
`publicaly_available_post_id` llega no vacío, solo se guarda su **número** en
`tiktok_publish_runs.public_post_count` (diagnóstico informativo, no autoritativo) y no se
muestra como enlace. `video.list` no se usa.

**Rationale**: la documentación confirma varios posts por `publish_id` y que la lista solo
incluye posts públicos moderados; cualquier mapeo 1:1 sería inventado (FR-023).

**Alternatives considered**: guardar la lista de IDs → sin valor para el usuario y tienta a
construir enlaces; omitirlo por completo → se pierde un diagnóstico barato.

## §8 Check status

**Decision**: endpoint genérico `POST /api/publications/{id}/check-status` (núcleo) →
`follow_up_publication`. TikTok `follow_up`: exige run `mode = INBOX_UPLOAD`, `phase =
delivered` y `publish_id`; **una** lectura de estado con `call_with_token` (renovación una vez,
como 013). Respuestas: `awaiting` / `published` / `failed`; errores temporales (`5xx`, red, 429)
→ HTTP 503 `tiktok_unavailable`/`tiktok_rate_limited`, estado intacto; `invalid_publish_id` /
`token_not_authorized_for_specified_publish_id` → 409 `tiktok_status_unavailable` (estado intacto,
mensaje: la cuenta conectada no puede consultar este envío); conexión no utilizable → 409 con el
código de conexión. Sin polling, sin reintentos automáticos; el frontend deshabilita el botón
mientras la petición está en curso.

**Rationale**: FR-021/FR-022; 30 lecturas/min por token sobran para clics manuales.

**Alternatives considered**: polling en segundo plano diario → prohibido ("No polling
infinito"); webhooks → requieren endpoint público.

## §9 Taxonomía de errores Inbox

**Decision**: reutilizar `map_gateway_error`/`map_fail_reason` de 013 con estas diferencias
para `INBOX_UPLOAD` (mensajes con "Nothing was sent to TikTok." antes del write-ahead):

| Señal | Código | Determinado | Reintento | Reconnect |
|---|---|---|---|---|
| `spam_risk_too_many_pending_share` (init) | `tiktok_too_many_pending_shares` | sí | no | no |
| `spam_risk_user_banned_from_posting` (init) | `tiktok_creator_cannot_post` | sí | no | no |
| `scope_not_authorized` (init) | `tiktok_upload_permission_missing` | sí | no | **no** |
| `access_token_invalid` (init) | `tiktok_unavailable` | sí | no | no (como 013) |
| `invalid_param` (init) | `tiktok_init_failed` | sí | no | no |
| `rate_limit_exceeded` (init) | `tiktok_rate_limited` | sí | no | no |
| `FAILED` + `fail_reason` | igual que 013 con textos "was not delivered" | sí | no | `auth_removed` sí (como 013) |
| chunks, último chunk, polling | idéntico a 013 | — | — | — |

`spam_risk_too_many_pending_share` se añade a `POST_REJECTION_CODES` del gateway. Mensaje:
"TikTok has too many uploads waiting for review in this account's inbox (at most 5 in 24 hours).
Open TikTok, publish or discard the pending drafts, then try again. Nothing was sent." No se
lleva contador local.

## §10 Persistencia: `tiktok_publish_runs` generalizado

**Decision**: ampliar la tabla en `0013` (batch recreate, patrón de 0005):

- `mode VARCHAR(16) NOT NULL` (existentes → `DIRECT_POST` en la migración; filas nuevas siempre
  explícitas), CHECK `mode IN ('DIRECT_POST','INBOX_UPLOAD')`;
- `phase` admite `delivered` (solo Inbox), CHECK `phase <> 'delivered' OR mode =
  'INBOX_UPLOAD'`;
- `delivered_to_inbox_at DATETIME NULL` (CHECK solo Inbox), `user_published_at DATETIME NULL`
  (observado), `public_post_count INTEGER NULL`;
- `last_remote_status` admite `SEND_TO_USER_INBOX`.

Fases Inbox: `preparing → initializing → uploading → final_chunk → processing → delivered →
succeeded | failed`; o `processing → succeeded` (PUBLISH_COMPLETE temprano) / `failed`. Nunca
`upload_url`, tokens ni respuestas crudas.

**Alternatives considered**: tabla `tiktok_inbox_runs` → casi idéntica, prohibida por FR-031.

## §11 Recuperación y anti-duplicados

**Decision**: sin cambios de mecanismo. Un intento Inbox interrumpido antes del write-ahead →
fallo determinado (genérico); después → ambiguo, reconciliable solo con su `publish_id` (§6
para `SEND_TO_USER_INBOX`). `AWAITING_USER_ACTION` no es `RUNNING`: la recuperación no lo toca.
Un nuevo envío solo es posible con acción explícita del usuario desde `FAILED` (y, si el último
intento es ambiguo, tras el reconocimiento manual genérico). `tiktok_publish_runs.publish_id`
UNIQUE garantiza un `publish_id` por intento.

## §12 Interfaz

**Decision**:

- `TikTokPublishOptions` gana un selector de modo obligatorio (radio "Direct Post" / "Upload to
  Inbox", ninguno marcado si `mode = null`). En Inbox: oculta Creator Info, privacidad,
  interacciones, disclosure, AIGC, caption y declaración; muestra preview y el aviso "You'll
  finish the post in TikTok: caption, privacy, sounds and other settings are chosen in TikTok's
  editor." Si falta la capacidad: "Upload to Inbox needs the video.upload permission. Reconnect
  the TikTok account." con acceso a `Reconnect`.
- Botones: en Inbox `Publish now` se rotula **Send to TikTok** y `Schedule` aclara "AutoPublisher
  starts sending at this time; the TikTok inbox notification may arrive later."
  `PublishNowDialog` en Inbox no muestra la declaración de Direct Post; muestra "AutoPublisher
  will upload this video to TikTok. You'll get a TikTok inbox notification to review, edit and
  publish it."
- Estado de entrega (`TikTokInboxDelivery`): `Scheduled`, `Uploading` (progreso), `Processing in
  TikTok`, `Ready in TikTok` + "Open your TikTok inbox to review, edit and publish the video." +
  "TikTok inbox notification (not necessarily a phone push notification)", `Published`,
  `Failed`; botón `Check status` solo en Ready in TikTok.
- Genérico: `PUBLICATION_STATUS_LABELS.awaiting_user_action = "Awaiting your action"`; una
  función `publicationStatusLabel(publication)` devuelve "Ready in TikTok" para TikTok. La cola
  lo agrupa como estado propio. `PublicationAttempts` muestra el intento como "Delivered to
  TikTok inbox" y, aparte, el estado final de la publicación ("Published in TikTok" / "Failed in
  TikTok").

## §13 Validación real y stop conditions

**Decision**: V1 en dos tramos dentro del Bloque 1 (ver plan): **V1a** reautorización con tres
scopes (y Direct Post todavía conectado) y **V1b** envío real al inbox con la cuenta **pública**.
STOP ante: `unaudited_client...`, petición de cuenta privada, rechazo por audit, `invalid_param`
inexplicable, ausencia de `SEND_TO_USER_INBOX`, notificación que no llega o no abre el editor.
V2 revalida Direct Post (requiere poner la cuenta en privado temporalmente: restricción ya
documentada de 013) y vuelve a pública.

**Hechos observados (V1a/V1b, 2026-10-15)**: Reconnect concede los tres scopes con la misma
identidad. Con la cuenta **pública** y el cliente Sandbox no auditado, `inbox/video/init/` se
acepta; un vídeo de 6 s (4,7 MB, un chunk) recibe `201` y llega a `SEND_TO_USER_INBOX` unos
30 s después (9 lecturas `PROCESSING_UPLOAD`). La notificación aparece en el inbox de la app de
TikTok y abre el editor con el vídeo, editable y guardable como borrador. La notificación push
del sistema depende de los permisos de notificaciones de la app en el móvil (no garantizada).

**Hechos observados (V2, 2026-10-15)**: el tiempo de procesado de TikTok no es estable: con
dos envíos simultáneos (6 MB y 67,6 MB) y un borrador pendiente, `SEND_TO_USER_INBOX` llegó
a los ~8–9 min, cerca del límite de 10 min de polling (si se supera, el intento queda incierto
y se resuelve con el mismo `publish_id`). Tras publicar el usuario desde el editor ("Solo yo"),
el estado devuelve `PUBLISH_COMPLETE` sin `publicaly_available_post_id`.

## §14 Pruebas offline

`FakeTikTok` gana `inbox_init` (registro de cuerpo para afirmar ausencia de `post_info`), estados
`SEND_TO_USER_INBOX`, códigos `spam_risk_too_many_pending_share` y `scope_not_authorized` para
`video.upload`, y scopes configurables en exchange/refresh. Tests nuevos listados en plan.md.
Regla de CLAUDE.md: tests dirigidos por bloque; suite completa solo al final (cambia el núcleo:
regresión de todas las plataformas una vez antes de cerrar).

## Riesgos

- **Cuenta pública + cliente no auditado**: la documentación no lo prohíbe ni lo garantiza; V1b
  decide.
- **Publicación atascada**: si el usuario descarta el borrador en TikTok y TikTok sigue
  respondiendo `SEND_TO_USER_INBOX` indefinidamente, la publicación queda en
  `AWAITING_USER_ACTION` sin salida (no cancelable por spec) y bloquea otra publicación del mismo
  vídeo a esa cuenta. **Limitación aceptada** en el spec (Edge Cases y Assumptions): sin
  salida manual local en esta feature; ninguna acción local elimina el pending share remoto; una
  salida segura podrá estudiarse en una feature posterior.
- **`published_at`** es la hora de observación, no la de publicación real.
- **Límite de 5 envíos pendientes/24 h** puede interrumpir la validación real.
- **Conexiones de dos scopes** no ven Inbox hasta reconectar (comportamiento buscado).
