# Research: Analytics & Performance (Feature 027)

Fecha: 2026-10-29. Fuentes: documentación oficial de cada plataforma (enlazada en cada
sección) y el código actual del repositorio. Solo APIs oficiales; scraping y APIs no oficiales
descartados por la Constitution (IV).

Leyenda: **CONFIRMADO** (documentación oficial y/o código), **HIPÓTESIS** (no documentado de
forma explícita; se valida en la implementación con un test real y, si falla, se aplica el
fallback indicado — nunca se convierte en requisito).

---

## §1 YouTube

Fuentes: [videos.list](https://developers.google.com/youtube/v3/docs/videos/list),
[recurso Video](https://developers.google.com/youtube/v3/docs/videos).

| Punto | Resultado | Estado |
|---|---|---|
| Endpoint | `GET youtube/v3/videos?part=statistics&id=<id1,id2,…>` con el token OAuth de la cuenta. El gateway ya llama a este endpoint (`GoogleGateway.get_video_status`, `part=status,processingDetails`). | CONFIRMADO |
| Scopes | Los concedidos (`youtube.readonly`, `youtube.upload`) incluyen lectura; `videos.list` es un método de lectura. El dueño ve también sus vídeos privados/no listados (la propia app ya lee `status` de sus vídeos con este token). | CONFIRMADO (código) |
| Métricas | `viewCount`, `likeCount`, `commentCount`. `dislikeCount` solo aparece si quien pregunta es el dueño. `favoriteCount` está obsoleto desde 2015 y vale siempre `0`. | CONFIRMADO |
| Semántica de `viewCount` | Desde el **2026-08-24** `viewCount` cuenta la vista "en cuanto empieza la reproducción" (incluye autoplay y hover). Un vídeo antiguo puede tener un contador acumulado que atraviesa el cambio. AutoPublisher conserva el valor devuelto tal cual y no lo reconstruye, corrige ni normaliza. | CONFIRMADO |
| Campos ausentes | La documentación no detalla cuándo se omiten `likeCount`/`commentCount` (p. ej. comentarios desactivados). Regla genérica: campo ausente = "no disponible". | HIPÓTESIS (cubierta por regla genérica) |
| Cuota | Según el [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost), `videos.list` cuesta **1 unidad del bucket general** (10.000 unidades/día por defecto) sea cual sea el número de IDs. `videos.insert` (y `search.list`) tienen **su propio bucket** (100 llamadas/día por defecto), así que leer métricas **no consume la cuota de subidas**. El bucket general sí lo comparten las llamadas auxiliares de AutoPublisher a YouTube: `channels.list` al conectar/verificar y `videos.list` de estado tras subir (`get_video_status`). Las cuotas se reinician a medianoche hora del Pacífico. | CONFIRMADO |
| Batching | `id` acepta una lista separada por comas. No hay un máximo oficial documentado; se usan **lotes de 50**, el valor práctico habitual. | HIPÓTESIS (50 es conservador; validar con un test real) |
| Vídeo inexistente | `videos.list` con `id` devuelve los vídeos encontrados; un ID borrado simplemente **no aparece** en `items` (el 404 `videoNotFound` documentado aplica a otros parámetros). | HIPÓTESIS (validar; la regla de doble confirmación de §7 cubre ambos casos) |

**Decisión**: YouTube es `supported` en v1 sin pedir permisos nuevos. El adaptador conserva
`viewCount`, `likeCount`, `commentCount` y `dislikeCount` (si llega). Descarta `favoriteCount`
por ser un valor fijo y obsoleto, no un dato (delta D1, aplicado en FR-006).
**Engagement YouTube**: `(likeCount + commentCount) / viewCount`; si falta cualquiera de los
tres o `viewCount = 0`, el engagement es "no disponible".
**Alternativas descartadas**: YouTube Analytics API (requiere el scope
`yt-analytics.readonly` y está fuera de alcance).

## §2 Instagram (API de Instagram con Instagram Login)

Fuentes: [IG Media](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media),
[Media Insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights).

| Punto | Resultado | Estado |
|---|---|---|
| Contadores públicos con permisos actuales | `GET graph.instagram.com/{ver}/{media-id}?fields=like_count,comments_count` con `instagram_business_basic` (ya concedido). | CONFIRMADO |
| `like_count` | Me gusta del media (incluye me gusta de respuestas a comentarios). Se **omite** si el dueño ocultó los recuentos. | CONFIRMADO → ausente = "no disponible" |
| `comments_count` | Comentarios del media (excluye el caption y los hijos de un álbum). | CONFIRMADO |
| Views | `view_count` solo existe para Business Discovery; **no hay views sin el permiso de insights**. | CONFIRMADO |
| Media Insights | `views`, `reach`, `likes`, `comments`, `shares`, `saved`, `total_interactions` en `/{media-id}/insights`. Requiere **`instagram_business_manage_insights`**. Retraso de hasta 48 h, datos durante 2 años y un conjunto vacío (no 0) cuando no hay datos. `impressions` está obsoleto para media posterior al 2024-07-02. | CONFIRMADO; fuera de v1 |
| Sin el permiso de insights | La llamada a insights falla por falta de permiso. **No se llama nunca en v1**: la capacidad lo declara `permission_required`. | CONFIRMADO (decisión) |
| Media inexistente | Error de Graph "object does not exist" (código 100) → `remote_not_found`. Los códigos se clasifican reutilizando el mapa de `instagram_gateway.py`. | HIPÓTESIS (validar el subcódigo exacto) |
| Rate limit | Business Use Case rate limiting; las cifras publicadas por terceros son contradictorias (4800 × impresiones / 24 h frente a 200/h). Se tratan como límite los códigos 4, 17, 32, 613 y 80002 y el HTTP 429. | HIPÓTESIS sobre cifras → no se codifica ningún número; solo reacción a errores |
| Batching | La consulta de varios IDs con `?ids=` no está confirmada en `graph.instagram.com`. **v1: una llamada por media.** | Decisión conservadora |

**Decisión**: Instagram tiene el grupo `basic` en `supported` (`like_count`, `comments_count`)
y el grupo `insights` en `permission_required`. Sin views no hay denominador, así que
**Instagram no declara fórmula de engagement en v1**.

## §3 Threads

Fuentes: [Insights](https://developers.facebook.com/docs/threads/insights),
[Media](https://developers.facebook.com/docs/threads/threads-media).

| Punto | Resultado | Estado |
|---|---|---|
| Con `threads_basic` | El objeto media expone identidad, tipo, texto, `permalink` y `timestamp`; **ningún contador**. | CONFIRMADO |
| Insights | `GET graph.threads.net/v1.0/{threads-media-id}/insights?metric=views,likes,replies,reposts,quotes,shares`. Requiere **`threads_manage_insights`** (no concedido). `views` y `shares` están "in development"; no incluye respuestas anidadas; `replies` en un post raíz cuenta el total. | CONFIRMADO; fuera de v1 |
| ID necesario | El `media_id` publicado (`external_id`) si existe. | CONFIRMADO (código) |

**Decisión**: todas las cuentas de Threads quedan con el grupo `insights` en
`permission_required` y el adaptador no hace llamadas. El catálogo declara ya los mapeos
futuros (`replies`→`comments` con nota) para no rediseñar después.

## §4 TikTok

Fuente: [Query Videos](https://developers.tiktok.com/doc/tiktok-api-v2-video-query); código
`tiktok_gateway.py`, `tiktok_publishing.py`, `tiktok_inbox.py`, `tiktok_media.py`.

| Punto | Resultado | Estado |
|---|---|---|
| IDs guardados (Direct Post) | `external_id` solo si el estado devuelve **exactamente un** `publicaly_available_post_id`, que existe solo para posts públicos; en otro caso `external_id = NULL` con aviso. | CONFIRMADO (código) |
| IDs guardados (Inbox) | Nunca: `external_id = NULL` (`tiktok_mode = inbox_upload`). | CONFIRMADO (código) |
| Cliente no auditado | Solo puede publicar `SELF_ONLY`, así que nunca hay ID público. | CONFIRMADO (código + guía de TikTok) |
| Métricas futuras | `POST /v2/video/query/` con el scope **`video.list`** (no solicitado hoy): `view_count`, `like_count`, `comment_count`, `share_count`, hasta 20 IDs por petición y solo vídeos del usuario. | CONFIRMADO |

**Decisión**: TikTok queda fuera de v1 por dos motivos acumulados: falta el scope `video.list`
y en la práctica no hay IDs remotos. Su capacidad se muestra como "no soportada en esta
versión" con el motivo (delta D2, aplicado en FR-001).

## §5 Telegram

Fuentes: [messages.getMessagesViews](https://core.telegram.org/method/messages.getMessagesViews) (MTProto);
[Bot API](https://core.telegram.org/bots/api).

- AutoPublisher publica en Telegram con una **sesión de usuario MTProto** (Telethon), no con
  la Bot API. **CONFIRMADO (código)**.
- `messages.getMessagesViews` es un método MTProto disponible para usuarios y devuelve, por
  mensaje, al menos vistas, forwards e información de replies. **CONFIRMADO**.
- (La Bot API no expone las vistas de un mensaje de canal, pero AutoPublisher no la usa.)
- La vista web pública `t.me/s/…` es scraping, descartado por la Constitution.

**Decisión**: `not_supported` en v1. La API que ya usa AutoPublisher permite leer métricas,
pero esta feature no implementa el adaptador de Telegram; se podrá añadir después sin cambiar
el modelo. Motivo visible: "Telegram metrics are not supported by AutoPublisher in this
version." (Corrige la decisión anterior `not_available_on_platform`, que asumía la Bot API.)
**X**: `not_applicable` (no hay publisher).

---

## §6 Arquitectura de adaptadores y catálogo

- **Decisión**: paquete `backend/app/analytics/` con:
  - un catálogo común en código (no en la base de datos);
  - un protocolo `MetricsAdapter` por plataforma (declaración + `fetch(batch)`);
  - un registro de adaptadores;
  - el servicio de refresco, el worker y el router.
  Cada adaptador reutiliza el gateway y `get_valid_credentials` de su plataforma.
- **Por qué**: Constitution III (un adaptador por plataforma). El catálogo es estático y
  versionado con el código, y la capacidad se calcula a partir de la conexión y sus scopes, sin
  duplicar estado.
- **Alternativas descartadas**: un catálogo en tablas (añade migraciones sin necesidad) y
  ampliar los `Publisher` existentes (mezclaría publicar con medir).

## §7 Refresco, prioridad y backoff

- **Decisión**: un `AnalyticsRefresher` propio (hilo daemon, separado del `Scheduler` de
  publicación, que según su docstring solo decide cuándo publicar). Se arranca después del
  scheduler en `main.py`, con un tick cada 5 minutos y `wake()` para las peticiones manuales.
  Las reglas exactas están en [data-model.md §Reglas de refresco](data-model.md).
- **Prioridad de publicación**: el refresher no inicia lecturas mientras haya intentos de
  publicación `running` o publicaciones armadas que vencen en los próximos 10 minutos. Lo
  comprueba antes de cada lote; una lectura ya en curso (segundos) no se aborta. El scheduler de
  publicación no consulta nunca el refresher.
- **Presupuesto de YouTube (bucket general)**: analytics usa como máximo **200 unidades al día
  del bucket general** (2 % del valor por defecto; unas 10.000 lecturas de vídeo en lotes de
  50). No limita ni toca el bucket de `videos.insert`: ese límite protege las llamadas
  auxiliares de publicación y conexión que comparten el bucket general. Si una lectura de
  analytics recibe `quotaExceeded`/`dailyLimitExceeded`, es que el bucket general está agotado:
  se pausa la analítica de YouTube hasta el siguiente reinicio (00:00 hora del Pacífico).
  Alternativa descartada: `videos.batchGetStats`, que según terceros tiene un bucket propio
  pero no está verificado en la documentación oficial consultada; se puede reconsiderar en una
  feature futura.
- **Backoff**: según el tipo de error (data-model §Reglas). El backoff por plataforma se guarda
  en memoria; el estado por publicación, en la base de datos.
- **Doble confirmación de borrado remoto**: la primera ausencia marca `remote_not_found`; una
  segunda, al menos 1 h después, marca `remote_deleted`. Evita falsos positivos por
  inconsistencias temporales de la API.

## §8 Hallazgos del código que afectan a la spec

- Borrar un media o una cuenta borra sus publicaciones, también las publicadas
  (Feature 021, `deletion.py` con `POST_DEPENDENTS`). El edge case de la spec "contenido local
  borrado pero publicación conservada" **no puede ocurrir**: las lecturas se borran con la
  publicación (delta D4). Las tablas nuevas deben registrarse en `POST_DEPENDENTS`.
- `Publication.content_id IS NULL` significa exclusivamente "publicación de solo texto", así
  que el tipo de contenido (image/video/text) se deriva sin ambigüedad.
