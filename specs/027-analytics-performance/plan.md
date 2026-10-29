# Implementation Plan: Analytics & Performance

**Branch**: `027-analytics-performance` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/027-analytics-performance/spec.md`

## Summary

Primera capa de analítica por proyecto. Se leen métricas de los posts publicados desde
AutoPublisher que tienen ID remoto, con APIs oficiales y **sin pedir permisos nuevos**:

- **YouTube**: `videos.list`/`statistics` (views, likes, comments).
- **Instagram**: campos `like_count`/`comments_count` del media.

El resto de plataformas queda así:

- **Threads**: `permission_required` (insights).
- **TikTok**: no soportada en esta versión.
- **Telegram**: no soportada en esta versión (la API MTProto que usa AutoPublisher sí ofrece
  métricas, pero el adaptador queda fuera de v1).
- **X**: no aplica.

Cada lectura correcta se guarda como snapshot histórico con los nombres y valores originales.
Un catálogo en código alinea `likes`/`comments` solo visualmente y nunca compara plataformas.
El engagement usa una fórmula fija por plataforma; en v1 solo existe para YouTube.

Un refresher en segundo plano, separado del scheduler de publicación, refresca cada 24 h los
posts de los últimos 90 días y atiende las peticiones manuales (cooldown de 15 min). Siempre
cede ante la publicación. La UI añade la sección "Analytics" al proyecto, con lista por post,
estados, rankings dentro de una plataforma, resumen por tipo, vista lado a lado y evolución.

Research completo en [research.md](research.md); modelo y reglas en [data-model.md](data-model.md);
API en [contracts/analytics-api.md](contracts/analytics-api.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy + Alembic, httpx (gateways existentes); React
Router y componentes `ui/` existentes. Sin dependencias nuevas; los gráficos de evolución se
dibujan con SVG simple.

**Storage**: SQLite local; migración `0020` con 3 tablas nuevas.

**Testing**: pytest con gateways falsos (`tests/fakes.py`); vitest + `test-fake-api.ts`.

**Target Platform**: aplicación web local de un usuario (Linux/macOS), modo despliegue Feature 020.

**Project Type**: web application (`backend/` + `frontend/`).

**Performance Goals**: listas de analytics del proyecto en menos de 1 s con cientos de
publicaciones; un refresco manual se ve reflejado en menos de 1 min si no hay publicaciones en
curso.

**Constraints**:

- la publicación tiene prioridad absoluta;
- analytics consume como mucho 200 unidades al día del bucket **general** de YouTube (las
  subidas usan su propio bucket y analytics no lo toca);
- no se piden scopes nuevos;
- no se usa scraping;
- no se suman ni comparan métricas entre plataformas.

**Scale/Scope**: uso personal; del orden de cientos de publicaciones y una lectura diaria por
post reciente (≈ decenas de miles de filas al año).

## Constitution Check

| Principio | Evaluación |
|---|---|
| I. Simplicidad | ✅ Catálogo, capacidades y fórmulas en código; 3 tablas; sin dependencias ni infraestructura nuevas; backoff de plataforma en memoria. Las vistas derivadas (P2/P3) son checkpoints separados. |
| II. SDD | ✅ La spec manda. Las contradicciones del research se propusieron como deltas (abajo) y se aplicaron tras aprobación explícita. |
| III. Modularidad | ✅ Un adaptador por plataforma en `analytics/adapters/`; el núcleo solo usa la declaración común. El scheduler de publicación no se toca salvo un helper de "publicación inminente" reutilizable. |
| IV. Seguridad | ✅ Solo APIs oficiales y permisos ya concedidos. Credenciales vía `get_valid_credentials`; mensajes de error fijos sin tokens ni cuerpos remotos. Datos en la base local (fuera del repo). |
| V. Calidad | ✅ Tests por checkpoint con gateways falsos; los fallos de refresco quedan registrados y visibles por publicación. |
| VI. Git | ✅ Rama de feature, commits pequeños por checkpoint, PR. |

Re-evaluación tras el diseño: sin violaciones; Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/027-analytics-performance/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/analytics-api.md
└── checklists/requirements.md
```

### Source Code

```text
backend/app/
├── analytics/
│   ├── __init__.py
│   ├── catalog.py          # common concepts (views, likes, comments, shares) + alignable
│   ├── adapters/
│   │   ├── base.py         # MetricsAdapter protocol, MetricDef, EngagementFormula, FetchResult
│   │   ├── youtube.py      # videos.list statistics, batches of 50
│   │   ├── instagram.py    # media fields like_count/comments_count, 1 call per media
│   │   ├── threads.py      # declaration only (insights group, permission_required)
│   │   └── registry.py     # platform → adapter; TikTok/Telegram/X static capability
│   ├── capability.py       # account × group capability from connection + scopes
│   ├── refresh.py          # eligibility, queueing, state transitions, backoff
│   ├── refresher.py        # AnalyticsRefresher daemon (tick 5 min, wake())
│   ├── queries.py          # posts list, rankings, content-type medians, side by side, history
│   └── routes.py           # router /api/... (contracts/analytics-api.md)
├── models.py               # + MetricSnapshot, MetricValue, PublicationMetricState
├── deletion.py             # + new tables in POST_DEPENDENTS
├── automation.py           # + publishing_imminent(session, now) helper (read only)
├── youtube_gateway.py      # + get_video_statistics(access_token, ids)
├── instagram_gateway.py    # + get_media_counters(access_token, media_id)
└── main.py                 # start/stop refresher after scheduler; include router
backend/migrations/versions/0020_analytics_snapshots.py
backend/tests/test_analytics_*.py

frontend/src/
├── pages/analytics/        # AnalyticsPage, PostsTable, CapabilityPanel, RefreshStatus,
│                           # ContentTypeSummary, SideBySide + ContentAnalyticsPage,
│                           # EvolutionChart, copy.ts, analytics.css and their tests
├── pages/library/          # + MediaUsage link to the media's side-by-side view
├── routes.tsx              # + p/:projectId/analytics, p/:projectId/analytics/media/:contentId
├── shell/…                 # + nav entry "Analytics"
├── api.ts / types.ts       # + analytics client and types
└── test-fake-api.ts        # + analytics fakes
docs/analytics.md           # user/maintainer doc (capabilities, metrics, refresh rules)
```

**Structure Decision**: web application existente. El paquete `analytics/` agrupa la feature,
siguiendo el patrón de un módulo por responsabilidad. Los adaptadores reutilizan los gateways y
`get_valid_credentials` de cada plataforma.

## Key Design Decisions

1. **Snapshot + values + state** (data-model.md). Solo las lecturas correctas crean snapshots.
   "No disponible" es ausencia de fila, nunca un 0.
2. **Mapeo de conceptos al leer, no al guardar**: los datos originales nunca se reescriben.
3. **Capacidad por cuenta y por grupo de permisos**: Instagram muestra a la vez `basic`
   soportado e `insights` con permiso pendiente. Una feature futura de permisos solo tendrá que
   añadir el scope y activar la lectura del grupo.
4. **Engagement** calculado al leer con la fórmula fija declarada por el adaptador. v1: solo
   YouTube `(likeCount + commentCount) / viewCount`. Instagram no declara fórmula (no tiene
   views sin insights).
5. **Refresher propio** con reglas exactas (data-model §Refresh rules). Las peticiones manuales
   aceptadas quedan `pending` (`manual_requested_at`) y las atiende el mismo worker; las que
   llegan dentro del cooldown de 15 min se rechazan con `409` y no se encolan; no hay trabajo de red dentro
   de la request HTTP.
6. **Rankings** solo con `platform` fijado (lo valida la API); el resumen por tipo exige
   `platform`. Medianas con n ≥ 3 y antigüedad mediana como contexto.
7. **Evolución** solo con los puntos reales del snapshot. La definición mostrada de YouTube
   `viewCount` indica el cambio de definición del 2026-08-24; el valor nunca se corrige.

## Checkpoints

Cada checkpoint se implementa, se prueba con tests dirigidos y se cierra con su commit.

| CP | Contenido | Historias / FR | Tests dirigidos |
|---|---|---|---|
| **A — Base de datos y catálogo** | Modelos + migración 0020; `POST_DEPENDENTS`; `catalog.py`, `adapters/base.py`, declaraciones de YouTube/Instagram/Threads; `registry.py`; `capability.py`; `GET catalog` y `GET accounts`. | FR-001, 002, 005–010, 024 | migración up/down; borrado de post/cuenta/media elimina lecturas; capacidad por plataforma y grupo; catálogo sin conceptos comparables |
| **B — Motor de refresco + YouTube** | `refresh.py` (elegibilidad, transiciones, backoff, cola manual); `youtube_gateway.get_video_statistics`; adaptador de YouTube; endpoints `POST …/refresh`; ejecución síncrona de un ciclo invocable en tests. | FR-003, 004, 011, 013, 015, 016 | éxito → snapshot y valores; campo ausente → sin fila; 0 se guarda; id ausente → not_found y luego deleted; 401 → reconnect_required; quotaExceeded (bucket general) → rate_limited hasta el reinicio; cooldown 409; `not_linked` con motivo |
| **C — Instagram básico** | `instagram_gateway.get_media_counters`; adaptador con grupo `basic`; mapeo de errores (100 → not_found, límites → rate_limited). | FR-002, 006, 007 | like_count oculto → no disponible; errores; `insights` sigue `permission_required` sin llamadas |
| **D — Refresco automático y prioridad** | `refresher.py` (tick 5 min, `wake`, stop limpio); `automation.publishing_imminent`; ventana de 90 días; 24 h; presupuesto del bucket general de YouTube; arranque/parada en `main.py`. | FR-012, 014, 017 | no lee con un intento `running` ni con una publicación que vence en < 10 min; posts > 90 días solo manual; presupuesto agotado; la pausa de automatización no lo afecta; un fallo de ciclo no detiene el hilo |
| **E — UI base (MVP)** | `GET posts` y `GET publication analytics`; página Analytics: panel de capacidades, tabla de posts con métricas originales, estado, antigüedad, fecha de lectura, enlace, engagement con fórmula y botones de refresco. | US1, US2, FR-018, 019 | API: forma de las filas, sin agregados; UI: estados `not_linked`/permiso/no disponible, nunca 0, fórmula visible, mensaje de cooldown |
| **F — Rankings y por tipo** | `sort` con `422` si no hay plataforma; `GET content-types` con medianas y `insufficient_sample`; UI con selector de cuenta (y por tanto plataforma) obligatorio para ordenar. | US3, FR-020, 021 | ranking cross-platform rechazado; no disponibles al final; n < 3 → muestra insuficiente; medianas correctas |
| **G — Lado a lado** | `GET contents/{id}/analytics`; página propia `analytics/media/:contentId`, enlazada desde cada post de media en Analytics y desde Usage del media. | US4, FR-009, 010, 022 | solo alinea `likes`/`comments`; views/shares por plataforma; ninguna suma, orden ni marca de "mejor" |
| **H — Evolución** | `history` y `series` en el detalle de la publicación; panel "Evolution" en cada post con un SVG de puntos reales, huecos, tabla de valores exactos y la nota de definición de YouTube. | US5, FR-023 | sin interpolación; 1 lectura → sin línea; orden temporal |
| **I — Cierre** | `docs/analytics.md`, README, checks de cierre (quickstart). | — | checks estáticos únicos |

A–E forman el MVP (P1). F, G y H son vistas derivadas independientes sobre las mismas tablas y
se pueden cerrar o aplazar por separado sin tocar la base.

## Deltas de spec (aprobados y aplicados en spec.md el 2026-10-29)

| # | Contradicción detectada en research | Propuesta |
|---|---|---|
| D1 | FR-006 exige conservar "toda métrica devuelta", pero `favoriteCount` de YouTube está obsoleto y vale siempre 0 (no es un dato). | FR-006: "toda métrica **vigente** declarada por el adaptador"; las obsoletas documentadas se descartan. |
| D2 | FR-001 no tiene un estado para "la plataforma ofrece métricas pero AutoPublisher no las soporta aún" (TikTok). | Añadir `not_supported` a FR-001. |
| D3 | FR-001 define un estado por cuenta, pero Instagram tiene a la vez métricas soportadas e insights pendientes de permiso. | FR-001: capacidad por cuenta **y por grupo de métricas**. |
| D4 | El edge case "contenido local borrado pero publicación conservada" no puede ocurrir: borrar un media o una cuenta borra sus publicaciones (Feature 021). | Eliminado sin sustituto artificial; el edge case existente de borrado de publicación cubre ahora también el borrado por media/cuenta. |
| D5 | El Contexto marca como "a confirmar" los contadores básicos de Instagram y Threads sin insights. | Instagram `like_count`/`comments_count`: confirmado. Threads: confirmado que no hay contadores sin insights. Instagram **no tiene views** sin insights, así que no tiene engagement en v1. |
| D6 | No hay en la spec una nota sobre el cambio de definición de `viewCount` de YouTube (2026-08-24). | Añadir edge case: la evolución de views de YouTube cruza un cambio de definición y la UI lo indica. |

| D7 | La research asumía la Bot API para Telegram, pero AutoPublisher usa una sesión de usuario MTProto, cuyo `messages.getMessagesViews` sí devuelve vistas, forwards y replies. | Telegram pasa de `not_available_on_platform` a `not_supported` en v1; no se implementa su lectura. |

Ninguno de los deltas cambia el alcance; precisan o corrigen supuestos. Redacción final de D6
en spec.md: AutoPublisher conserva siempre el `viewCount` devuelto y no lo reconstruye,
corrige ni normaliza; no se afirma que existan lecturas anteriores al cambio.

## Hipótesis que se validan en la implementación (no son requisitos)

- YouTube: tope práctico de 50 IDs por `videos.list`, un ID borrado que no aparece en `items`,
  y la omisión de `commentCount`/`likeCount` cuando están desactivados u ocultos. Los cubre la
  regla genérica (ausente → no disponible; doble confirmación de borrado).
- Instagram: código/subcódigo exacto de "media inexistente" y los códigos de rate limit. Si
  difieren, se trata el error como `stale` (transitorio), nunca como borrado.

## Complexity Tracking

Sin violaciones de la Constitution.
