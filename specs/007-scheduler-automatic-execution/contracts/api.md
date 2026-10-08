# API Contract: scheduler y ejecución automática

**Feature**: `007-scheduler-automatic-execution` | **Fecha**: 2026-10-07

Amplía la API REST bajo `/api` (Features 004–006). Fechas en ISO 8601 UTC. Formato de
error existente: `{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta nueva contiene tokens, cabeceras `Authorization`,
URIs de sesión de subida ni respuestas crudas de plataformas. Los mensajes de fallo
automático son los mismos mensajes seguros que ya devuelve `Publish now`.

---

## Representaciones

### AutomationStatus (nueva)

```json
{
  "paused": false,
  "running": true,
  "last_check_at": "2026-10-07T17:59:30Z",
  "check_interval_seconds": 30,
  "window_minutes": 10
}
```

- `paused`: valor persistente de `automation_settings.automation_paused`.
- `running`: el hilo del scheduler de este proceso está vivo (no indica si está pausado).
- `last_check_at`: fin del último ciclo completo sin error; `null` hasta el primero tras
  arrancar (no se persiste).
- `check_interval_seconds`, `window_minutes`: informativos para la interfaz.

### Publication (ampliada)

`PublicationRead` añade:

```json
{
  "auto_publish_enabled": true,
  "auto_publish_state": "waiting",
  "auto_publish_window_ends_at": "2026-10-07T18:10:00Z",
  "auto_publish_error": null
}
```

Todos los endpoints que devuelven una `Publication` (crear, `GET`, listado, `PATCH`,
`cancel`, `reactivate`, `publish`) la construyen con el mismo mapper, que recibe el reloj de
la aplicación y el estado de pausa, así que los campos derivados son siempre coherentes.

- `auto_publish_enabled`: indicador persistente. Siempre `false` fuera de `scheduled`.
- `auto_publish_state`: `null` si `status != "scheduled"`; si no, `disabled` | `waiting` |
  `due` | `paused` | `overdue` ([data-model.md §4](../data-model.md#4-estado-derivado-no-persistido)).
  `overdue` es una condición derivada, no un estado: `status` sigue siendo `scheduled`; solo
  existe en publicaciones **armadas**.
- `auto_publish_window_ends_at`: `scheduled_at + 10 min` si `status = "scheduled"`; si no,
  `null`.
- `auto_publish_error`: `null` o
  `{"code": "reconnect_required", "message": "...", "failed_at": "2026-10-07T18:00:12Z"}`
  (último fallo de inicio automático vigente).

### PublicationAttempt (ampliada)

Añade `"trigger": "manual" | "scheduled"`. Los intentos anteriores a esta feature son
`manual`.

---

## Endpoints nuevos

### `GET /api/automation`

`200` → `AutomationStatus`.

### `PUT /api/automation`

Cuerpo: `{ "paused": true }` (obligatorio, booleano). Idempotente.

`200` → `AutomationStatus` actualizado.

- Pausar: el scheduler no inicia ni pre-comprueba nada desde el siguiente punto de
  decisión (incluida la reclamación atómica de una publicación cuyo preflight ya estaba en
  curso); las subidas `publishing` siguen; `Publish now` sigue disponible.
- Valor inicial tras la migración: `paused = false` (seguro: ninguna publicación existente
  queda armada).
- Reanudar: despierta el scheduler; solo se inician publicaciones aún dentro de su ventana.

Errores: `422` si falta `paused` o no es booleano.

---

## Endpoints existentes con comportamiento nuevo

### `POST /api/contents/{id}/publications`

Cuerpo ampliado:

```json
{ "account_ids": [3, 5], "scheduled_at": "2026-10-07T18:00:00Z", "auto_publish_enabled": true }
```

- `auto_publish_enabled` opcional, por defecto `false`. Se aplica a todas las
  publicaciones creadas en la petición.
- `true` sin `scheduled_at` → `422` (`fields`: `auto_publish_enabled`, "Choose a date and
  time to enable auto-publish.").
- Resto de reglas sin cambios (fecha futura, proyecto/cuenta activos, duplicados).

### `PATCH /api/publications/{id}`

Cuerpo ampliado: cualquier combinación de `scheduled_at`, `auto_publish_enabled` y los
overrides existentes.

| Petición | Resultado |
|----------|-----------|
| `{"auto_publish_enabled": true}` en `scheduled` con fecha futura | Armada; error automático limpio |
| `{"auto_publish_enabled": true}` en `scheduled` con fecha pasada | `422` (`auto_publish_enabled`: "Reschedule to a future time to enable auto-publish.") |
| `{"auto_publish_enabled": true}` en `unscheduled` sin `scheduled_at` en el cuerpo | `422` (`auto_publish_enabled`: "Choose a date and time to enable auto-publish.") |
| `{"scheduled_at": <futura>, "auto_publish_enabled": true}` | Programada (o reprogramada) y armada |
| `{"scheduled_at": <futura>, "auto_publish_enabled": false}` | Programada y desarmada |
| `{"scheduled_at": <futura distinta>}` (sin el campo) | Reprogramada y **desarmada** |
| `{"scheduled_at": null}` | `unscheduled` y desarmada |
| `{"scheduled_at": null, "auto_publish_enabled": true}` | `422` |
| `{"auto_publish_enabled": false}` en `scheduled` | Desarmada (permitido aunque proyecto o cuenta estén inactivos) |
| `{"auto_publish_enabled": false}` en otro estado | Sin efecto (ya es `false`) salvo las reglas de edición existentes |
| `{"auto_publish_enabled": true}` en `failed`, `cancelled`, `publishing`, `published` | `409 publication_not_editable` / `publication_cancelled` (reglas de `ensure_editable` con `schedule_change`) |
| `{"auto_publish_enabled": true}` con proyecto o cuenta inactivos o archivo ausente | `409 project_inactive` / `account_inactive` / `media_unavailable` |

Cambiar `scheduled_at` o desarmar limpia `auto_publish_error`. Editar solo overrides no
cambia el armado.

### `POST /api/publications/{id}/cancel`

La publicación cancelada queda con `auto_publish_enabled = false` y sin error automático.

### `POST /api/publications/{id}/reactivate`

Sin cambios de cuerpo. La publicación reactivada queda **siempre** desarmada
(`auto_publish_state = "disabled"` si vuelve a `scheduled`).

### `POST /api/publications/{id}/publish` (Publish now)

Sin cambios de cuerpo ni de reglas. Novedades:

- el intento se crea con `trigger = "manual"`;
- si la publicación estaba armada, la transición a `publishing` la desarma (ya no puede
  ejecutarla el scheduler);
- funciona igual con la automatización pausada y no consume ni espera slots automáticos
  (las guardas de pausa, ventana, armado y slots solo se aplican a `trigger = scheduled`);
- compite con el scheduler a través del mismo `UPDATE` condicional: si el scheduler la
  inició antes, responde `409 publication_in_progress`.

### `GET /api/projects/{id}/publications` y `GET /api/publications/{id}`

Incluyen los campos nuevos de `Publication`; `latest_attempt.trigger` incluido. El orden de
la Queue no cambia.

### `GET /api/publications/{id}/attempts`

Cada intento incluye `trigger`.

---

## Servicio interno (no HTTP)

El scheduler llama directamente a:

```text
start_publication(session, publication_id, *, confirm_remote_checked=False, ctx, runner,
                  publishers, trigger=AttemptTrigger.SCHEDULED,
                  clock=<reloj del scheduler>)
```

`clock: Callable[[], datetime]` (no un instante fijo) se consulta varias veces en la misma
ejecución: antes del preflight y justo antes de la reclamación atómica.

Mismos errores y orden de preflight que `POST /publish` (Feature 006, contrato
`specs/006-youtube-manual-publishing/contracts/api.md`), más:

- antes del preflight: `409 publication_not_eligible` si la publicación no está
  `scheduled`, armada, sin pausa y dentro de la ventana según `clock()`;
- en la transición, **después** del preflight y en la misma transacción que crea el
  intento: el `UPDATE` condicional exige de nuevo `status = scheduled`, armada, sin pausa,
  dentro de la ventana con el reloj en ese instante, sin otra ejecución activa y con un
  slot automático libre (máximo 2 intentos `running` con `trigger = scheduled`); si no se
  cumplen → `publication_not_eligible` (o `publication_in_progress` si otra ejecución
  ganó).

Tratamiento en el scheduler:

| Resultado | Acción |
|-----------|--------|
| Intento creado | Nada más: la subida sigue en el `PublicationRunner` (reglas de la Feature 006) |
| `publication_in_progress`, `publication_not_eligible` | Ignorado (carrera perdida, pausa, ventana expirada o sin slot libre); no se registra error |
| Otro `ConflictError` / `AppError` / `NotFoundError` | Se guarda `{code, message, failed_at}` como `auto_publish_error`; no se vuelve a intentar hasta `failed_at + 120 s` (también tras reiniciar) |
| Cualquier otra excepción | Se guarda `internal_error` con mensaje fijo; log con el nombre de la clase |

## Códigos de error

No hay códigos HTTP nuevos. Código nuevo solo en `auto_publish_error`:

| Código | Cuándo |
|--------|--------|
| `internal_error` | Excepción inesperada al intentar el inicio automático ("AutoPublisher could not start this publication automatically.") |

Los demás códigos de `auto_publish_error` son los del preflight existente:
`project_inactive`, `account_inactive`, `platform_not_supported`, `content_not_video`,
`media_unavailable`, `invalid_metadata`, `youtube_options_incomplete`,
`oauth_not_configured`, `not_connected`, `reconnect_required`,
`credential_store_unavailable`, `youtube_unavailable`, `remote_check_required`, `not_found`.
