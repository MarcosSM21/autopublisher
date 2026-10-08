# Research: scheduler y ejecución automática de publicaciones programadas

**Feature**: `007-scheduler-automatic-execution` | **Fecha**: 2026-10-07

Decisiones de la Fase 0. Cada una indica qué se elige, por qué y qué alternativas se
descartaron. Todas parten del código existente de la Feature 006 (`app/publishing.py`:
`start_publication`, `create_running_attempt`, `PublicationRunner`,
`recover_interrupted_attempts`) y no introducen dependencias nuevas.

---

## 1. Worker: un hilo daemon con reloj y espera inyectables

**Decisión**: nuevo módulo `app/scheduler.py` con una clase `Scheduler` que:

- expone `run_once() -> TickReport`: un ciclo completo y síncrono (seleccionar candidatas →
  ordenar → respetar capacidad → intentar iniciar cada una). Es lo que prueban los tests;
- expone `start()` / `stop()`: un único hilo daemon (`name="publication-scheduler"`) que
  ejecuta `run_once()` inmediatamente al arrancar y después cada `interval` segundos;
- recibe `SchedulerSettings` (dataclass congelada):

  | Campo | Valor por defecto | Uso |
  |-------|-------------------|-----|
  | `clock` | `utc_now` | Hora UTC actual (inyectable) |
  | `interval` | `30.0` s | Espera entre ciclos |
  | `wait` | `None` → `stop_event.wait` | Espera interrumpible (inyectable) |
  | `autostart` | `True` | Los tests de API lo ponen a `False` y llaman a `run_once()` |
  | `max_concurrent` | `2` | §6 |
  | `preflight_retry_interval` | `120.0` s | §7 |
  | `stop_timeout` | `5.0` s | Espera máxima al hilo al apagar |

- La espera por defecto es `stop_event.wait(interval)`, de modo que `stop()` despierta al
  hilo al instante. Entre candidatas de un mismo ciclo también se comprueba `stop_event`.
- Cada ciclo va envuelto en `try/except Exception`: un fallo inesperado se registra solo
  con el nombre de la clase de la excepción (como en el runner de la Feature 006) y el
  siguiente ciclo continúa (FR-009). Un fallo de una candidata no impide procesar las
  demás.
- Tras un ciclo sin excepción global se guarda en memoria `last_tick_at` (hora del reloj
  inyectado) para mostrar "última comprobación" (opcional en la spec, barato aquí).

**Razón**: mismo patrón que `PublicationRunner` (hilos daemon + `threading.Event`), sin
infraestructura nueva. Con 30 s de intervalo y preflight de pocos segundos, el inicio
ocurre < 60 s tras `scheduled_at` (SC-002). `run_once()` con reloj falso permite probar
todo sin esperas reales (FR-007).

**Alternativas descartadas**:

- `asyncio` task en el `lifespan`: el servicio de publicación y las sesiones son síncronos;
  habría que delegar en un threadpool igualmente.
- APScheduler u otra librería: dependencia nueva para un bucle de 20 líneas; además su
  persistencia de jobs duplicaría la fuente de verdad (la tabla `publications`).
- cron / systemd / proceso separado: excluidos por la spec (FR-004).
- Un temporizador por publicación (`threading.Timer` hasta `scheduled_at`): no sobrevive a
  reinicios, se desincroniza con ediciones y complica la pausa; el sondeo de la base es la
  fuente de verdad que pide la Constitution ("scheduler local dirigido por la base de
  datos").

## 2. Orden de arranque y apagado

**Decisión**: en `main.py` (`lifespan`):

1. `run_migrations()`;
2. motor, `session_factory`, almacenamiento, `PublishContext`, `PublicationRunner` y
   registro de publishers (`app.state.publishers`);
3. `recover_interrupted_attempts(session_factory)` — se mueve **después** del registro de
   publishers para seguir literalmente el orden de la spec (la recuperación no depende de
   ellos, así que el cambio es inocuo);
4. construir `Scheduler(...)` y guardarlo en `app.state.scheduler`;
5. `scheduler.start()` → el primer `run_once()` busca publicaciones vencidas.

Todo ocurre antes del `yield`, es decir, antes de aceptar peticiones. Como la recuperación
es una llamada síncrona que termina antes de `scheduler.start()`, el scheduler nunca
compite con ella (FR-008).

Apagado (bloque `finally`): `scheduler.stop()` **antes** de `runner.stop()`, para que no se
inicie nada nuevo mientras se detienen las subidas en curso. Si el scheduler está a mitad
de un preflight, `stop()` espera como máximo `stop_timeout`; si en ese tiempo llegara a
crear un intento, la recuperación del siguiente arranque lo cierra como `interrupted`
(regla existente de la Feature 006).

**Alternativas descartadas**: arrancar el scheduler en el primer request o en otro hilo
paralelo a la recuperación (rompe FR-008).

## 3. Dónde vive el consentimiento: `publications.auto_publish_enabled`

**Decisión**: columna booleana `auto_publish_enabled` en `publications`
(`NOT NULL`, `server_default 0`) con el invariante:

> `auto_publish_enabled = 1` solo es posible con `status = 'scheduled'`
> (CHECK `auto_publish_enabled = 0 OR status = 'scheduled'`).

Consecuencias directas:

- **Migración** (FR-014): la columna nace a `0` para todas las filas; ninguna publicación
  existente queda armada.
- **Salir de `scheduled` desarma siempre**, en la misma escritura que cambia el estado:
  pasar a `unscheduled` (quitar fecha), `cancelled`, o `publishing` (tanto por `Publish now`
  como por el scheduler). Por tanto una publicación reactivada nace desarmada
  (FR-017) y una `FAILED`/`PUBLISHED` nunca está armada (FR-011).
- El "estaba armada cuando empezó" no se pierde: queda en el origen del intento
  (`trigger = scheduled`, §9).

**Razón**: genérico (no depende de plataforma), un solo dato, y el CHECK hace imposible por
construcción que un estado no programado esté armado.

**Alternativas descartadas**:

- Tabla aparte `scheduled_runs` / `publication_automation`: más joins y estado duplicado
  sin beneficio para un indicador booleano.
- Mantener el indicador tras ejecutar: obligaría a filtrar por estado en todas partes y
  abre la puerta a "re-armar" silenciosamente al reactivar.

## 4. Reglas de armado en la API

**Decisión** (contrato en [contracts/api.md](contracts/api.md)):

- `POST /api/contents/{id}/publications` acepta `auto_publish_enabled` (por defecto
  `false`); `true` exige `scheduled_at`.
- `PATCH /api/publications/{id}` acepta `auto_publish_enabled`:
  - `true` exige que el resultado sea `scheduled` con fecha **futura** en ese momento
    (`ensure_future`) y proyecto, cuenta y archivo válidos (`ensure_can_prepare`), con las
    mismas reglas de edición por estado que la fecha (`ensure_editable(schedule_change=True)`);
  - `false` siempre se permite en una publicación `scheduled` (desarmar no prepara nada,
    también con proyecto o cuenta inactivos);
  - si el `PATCH` **cambia** `scheduled_at` y **no** incluye `auto_publish_enabled`, la
    publicación queda **desarmada**: una nueva fecha nunca hereda el consentimiento en
    silencio. La interfaz siempre envía ambos campos juntos (FR-015, FR-018);
  - quitar la fecha (`scheduled_at: null`) desarma; enviar a la vez `true` es `422`.
- Cancelar y reactivar no aceptan el campo; ambas operaciones dejan la publicación
  desarmada (§3).

**Razón**: el consentimiento siempre es un dato explícito de la petición; la opción
segura (desarmado) es la que se aplica cuando falta.

**Alternativa descartada**: conservar el armado al cambiar la fecha si no se indica nada:
cómodo, pero es exactamente la "automatización silenciosa" que la spec prohíbe.

## 5. Reclamación atómica: el mismo `UPDATE` condicional de la Feature 006 con guardas extra

**Decisión**: `start_publication(...)` gana dos parámetros con valores por defecto que
mantienen el comportamiento manual intacto:

```text
start_publication(session, publication_id, *, confirm_remote_checked, ctx, runner,
                  publishers, trigger=AttemptTrigger.MANUAL,
                  clock: Callable[[], datetime] = utc_now)
```

El servicio no recibe un instante fijo sino un **reloj** (`clock`), que consulta varias
veces durante la misma ejecución: antes del preflight (pre-comprobación) y de nuevo justo
antes de la reclamación atómica, dentro de `create_running_attempt`.

Con `trigger=SCHEDULED`:

1. **Antes del preflight** (sin red) se comprueba la elegibilidad automática con la función
   pura `automation.auto_start_blocker(publication, paused, clock())`: estado `scheduled`,
   armada, no pausada, `scheduled_at <= now <= scheduled_at + 10 min`. Si no se cumple, se
   lanza `ConflictError("publication_not_eligible")` sin contactar con nadie.
2. `confirm_remote_checked` es siempre `False`: si el último intento de esa pareja
   contenido + cuenta es ambiguo, el inicio automático falla con `remote_check_required`
   (la Feature 006 exige una confirmación humana).
3. Preflight completo existente (`local_check` + `publisher.prepare`), sin cambios
   (FR-028).
4. **Re-check atómico tras el preflight**: `create_running_attempt(...)` ejecuta el
   `UPDATE` condicional existente añadiendo, solo para `scheduled`, estas condiciones en el
   mismo `WHERE`. Es la única decisión que permite iniciar la ejecución:

   ```text
   id = :id
   AND status = 'scheduled'                                   -- estado
   AND auto_publish_enabled = 1                               -- armada
   AND NOT EXISTS (SELECT 1 FROM automation_settings
                   WHERE id = 1 AND automation_paused = 1)    -- no pausada
   AND scheduled_at <= :now AND scheduled_at >= :now - 10 min -- dentro de la ventana
   AND NOT EXISTS (SELECT 1 FROM publication_attempts
                   WHERE publication_id = :id
                     AND status = 'running')                  -- sin ejecución activa
   AND (SELECT count(*) FROM publication_attempts
        WHERE status = 'running' AND trigger = 'scheduled') < :max_concurrent  -- slot (§6)
   ```

   `:now` es el resultado de llamar a `clock()` **justo antes del `UPDATE`**, después del
   preflight, que puede tardar segundos. El mismo `UPDATE` pone `auto_publish_enabled = 0`
   y limpia el último fallo automático (§7). En la **misma transacción** se hace el
   `INSERT` del intento con `trigger = 'scheduled'`, que sigue protegido por el índice
   único parcial de intentos `running` (segunda barrera frente a una ejecución activa).
   Si cualquiera de las condiciones deja de cumplirse, no se inicia nada.

Si `rowcount != 1`, el resultado es `publication_in_progress` o `publication_not_eligible`
(sin efectos externos: aún no se ha creado sesión de subida).

**`Publish now` (`trigger=MANUAL`)**: su `UPDATE` es el de la Feature 006
(`status IN ('unscheduled','scheduled','failed')`) **sin** ninguna de las guardas
anteriores: la pausa, la ventana, el armado y los slots automáticos no lo bloquean. Solo
añade `auto_publish_enabled = 0` y la limpieza del fallo automático en los valores
(obligado por el CHECK de §3). Las guardas viven en `automation.scheduled_claim_conditions(
now, max_concurrent)`, que devuelve expresiones SQL genéricas sin ninguna referencia a
plataformas.

**Garantías** (FR-024, FR-025, SC-007):

- Dos ciclos o dos instancias del worker: ambos pueden pasar el preflight, solo uno gana el
  `UPDATE`.
- Scheduler contra `Publish now`: el primero que ejecute el `UPDATE` gana; el otro recibe
  `409 publication_in_progress` (manual) o se descarta en silencio (scheduler).
- Pausa, desarmado, cancelación o reprogramación ocurridos **durante** el preflight: el
  `UPDATE` ya no encuentra la fila en las condiciones requeridas y no inicia nada.
- Límite de slots: dos ciclos concurrentes que pasan el preflight a la vez no pueden
  superar 2 ejecuciones automáticas (§6).
- Ventana que expira durante el preflight o la espera de capacidad: igual; la publicación
  queda overdue (FR-027).

SQLite serializa escrituras: la transacción de reclamación empieza con el propio `UPDATE`
(pysqlite solo abre la transacción al primer DML; las lecturas del preflight quedan
fuera), así que el `UPDATE` evalúa sus subconsultas con el bloqueo de escritura tomado y ve
las reclamaciones confirmadas por otras conexiones. Una conexión que encuentra la base
bloqueada espera (timeout por defecto de pysqlite, 5 s) en lugar de leer datos antiguos; si
aun así falla, se trata como carrera perdida. Los `datetime` se comparan como texto ISO homogéneo
generado por `UTCDateTime` (siempre UTC sin zona, mismo formato que los parámetros
enlazados), así que las comparaciones son correctas.

**Alternativas descartadas**:

- Columna `claimed_by` / `lease_until` para reclamar antes del preflight: añade estados
  intermedios y su recuperación; el `UPDATE` condicional ya existe y basta.
- Lock en memoria: no protege frente a dos procesos ni sustituye a la base (la spec lo
  exige explícitamente).
- Un servicio aparte "scheduled_start": duplicaría el preflight y la transición (FR-002).

## 6. Selección, orden y concurrencia limitada

**Decisión**:

- Consulta de candidatas por ciclo (sin red):

  ```text
  SELECT publications WHERE status='scheduled' AND auto_publish_enabled=1
    AND scheduled_at <= :now AND scheduled_at >= :now - 10 min
  ORDER BY scheduled_at ASC, id ASC
  ```

  Si la automatización está pausada, el ciclo termina antes de consultar nada (FR-022).
- **Slot automático** (definición exacta):
  - máximo `max_concurrent` = **2** ejecuciones iniciadas por el scheduler a la vez;
  - un slot queda **ocupado** cuando la publicación entra correctamente en `publishing`
    con un intento `trigger = 'scheduled'` (es decir, existe un intento `running` con
    `trigger = 'scheduled'`);
  - se **libera** cuando ese intento termina y la publicación queda `published` o `failed`
    (incluido el cierre como `interrupted` de la recuperación al arrancar);
  - las ejecuciones `manual` (`Publish now`) **no** ocupan slots ni se ven limitadas por
    ellos.
- **Pre-comprobación (optimización)**: al principio del ciclo se cuentan los slots libres
  en la base; si no hay ninguno, el ciclo no ejecuta preflights (evita contactar con
  plataformas para nada). Se intenta iniciar como mucho tantas candidatas como slots libres.
- **Garantía**: la condición de slot libre forma parte del `UPDATE` atómico de reclamación
  (§5). Aunque dos ciclos concurrentes (o dos workers) vean ambos un slot libre y pasen el
  preflight a la vez, SQLite serializa sus `UPDATE`: el segundo evalúa el recuento después
  de que el primero confirme su intento, y no se inicia si ya hay 2. La candidata que pierde
  así su turno se descarta como `publication_not_eligible` (sin registrar error) y vuelve a
  seleccionarse en el ciclo siguiente.
- Se recorren las candidatas en orden; las que tienen un fallo automático reciente (menos
  de 120 s) se saltan (§7). Las que no caben simplemente se vuelven a seleccionar en el
  siguiente ciclo: no hay cola en memoria que pueda duplicarlas ni perderlas.
- Cada inicio re-evalúa la ventana con el reloj en el momento del `UPDATE` (§5).

**Razón**:

- Orden determinista (FR-026): `scheduled_at` y luego `id`, estable entre ciclos.
- **Límite 2**: las subidas comparten el ancho de banda de subida de un ordenador
  doméstico; 1 haría que una subida larga (> 10 min) dejara overdue a cualquier otra
  publicación programada a la misma hora, y más de 2 apenas aporta y multiplica la memoria
  y las conexiones. Es configurable en `SchedulerSettings` (no en la interfaz).
- Contar en la base (no en memoria) mantiene la cifra correcta tras reinicios, con subidas
  iniciadas en ciclos anteriores y con varios workers o procesos sobre la misma base.

**Tests**: dos `Scheduler` sobre la misma base con 4 candidatas y un `FakePublisher` cuyo
`prepare` espera en una `threading.Barrier` (para que ambos ciclos pasen el preflight a la
vez) → nunca más de 2 intentos `running` con `trigger = 'scheduled'`; con 2 automáticas en
curso, `Publish now` sigue iniciando una manual; al terminar una automática, el siguiente
ciclo ocupa el slot liberado.

## 7. Fallo de preflight: último error automático y re-comprobación limitada

**Decisión**:

- Tres columnas genéricas en `publications`:
  `auto_publish_error_code` (≤ 40), `auto_publish_error_message` (≤ 500) y
  `auto_publish_failed_at` (momento UTC del último fallo de inicio automático,
  persistido).
- Cuando `start_publication(trigger=SCHEDULED)` lanza `ConflictError`, `AppError` o
  `NotFoundError` con un código distinto de `publication_in_progress` /
  `publication_not_eligible` (carreras perdidas, que no son errores para el usuario), el
  scheduler guarda `code` y `message` **ya existentes** de esa excepción (los mensajes de
  la API son seguros por diseño en las Features 005/006) con un `UPDATE` condicional
  `WHERE status='scheduled' AND auto_publish_enabled=1 AND scheduled_at=:scheduled_at`,
  para no escribir un error obsoleto sobre una publicación reprogramada o desarmada entre
  medias.
- Cualquier otra excepción se guarda como `internal_error` con un mensaje fijo
  ("AutoPublisher could not start this publication automatically.") y se registra en el
  log solo el nombre de la clase.
- **Re-comprobación limitada y persistente**: el siguiente preflight automático de una
  publicación solo puede ocurrir cuando `now >= auto_publish_failed_at + 120 s`. La
  condición forma parte de la consulta de candidatas (no hay estado en memoria), así que
  **sobrevive a reinicios**: arrancar el backend no provoca una comprobación inmediata si
  aún no han pasado 120 s desde el último fallo. Así una publicación cuyo preflight falla se
  comprueba como máximo ~6 veces en su ventana de 10 minutos (t = 0, 2, 4, 6, 8, 10 min),
  sin bucles agresivos ni llamadas continuas a la plataforma (FR-031). Fuera de la ventana
  nunca se selecciona (FR-012).
- **Limpieza**: las columnas se ponen a `NULL` cuando cambia `scheduled_at`, cuando se
  desarma y en el `UPDATE` que pasa correctamente a `publishing` (FR-030); con ello el
  fallo anterior deja de estar vigente y tampoco limita la siguiente comprobación. Al salir de `scheduled` por
  cancelación o al quitar la fecha también se limpian. CHECK:
  `auto_publish_enabled = 1 OR (auto_publish_error_code IS NULL AND
  auto_publish_failed_at IS NULL)`.
- Al terminar la ventana el error se conserva y se muestra junto a "Missed automatic
  publishing window" (US6 escenario 4).
- Ningún `PublicationAttempt` se crea por un preflight fallido: `start_publication` solo lo
  crea tras pasar el preflight, igual que en la Feature 006 (FR-029).

**Razón**: guardar lo mínimo, junto a la publicación a la que se refiere, reutilizando los
códigos y mensajes seguros existentes.

**Alternativas descartadas**: registrar los fallos como `PublicationAttempt` (la spec y la
Feature 006 reservan los intentos para ejecuciones reales); tabla de historial de fallos
automáticos (fuera de alcance, solo se pide el último).

## 8. Pausa global: tabla `automation_settings` de una fila

**Decisión**: tabla singleton `automation_settings` con
`id INTEGER PRIMARY KEY CHECK (id = 1)`, `automation_paused BOOLEAN NOT NULL DEFAULT 0` y
`updated_at`. La migración inserta la fila `(id=1, automation_paused=false, updated_at=now)`.
Lectura con `automation.is_paused(session)` (si faltara la fila, se trata como **pausada**
por seguridad y se registra un aviso).

**Estado inicial `automation_paused = false`**: es seguro porque la misma migración deja
todas las publicaciones existentes con `auto_publish_enabled = false` (§3, §14): con la
automatización activa no hay nada armado que ejecutar hasta que el usuario arme algo de
forma explícita. La migración solo escribe en SQLite; no tiene efectos externos.
`Pause automation` / `Resume automation` modifican después ese valor persistente.

- `GET /api/automation` devuelve el estado; `PUT /api/automation` con `{ "paused": bool }`
  lo cambia (idempotente).
- Pausar no toca las subidas `running` ni `Publish now` (FR-022): la pausa solo forma
  parte de las guardas del inicio `scheduled` (§5), nunca del manual.
- La pausa se comprueba dos veces: al principio del ciclo (si está pausada, no se consulta
  ni se pre-comprueba nada) y de nuevo, atómicamente, en el `UPDATE` de reclamación tras el
  preflight (§5).
- Reanudar no hace nada especial: el siguiente ciclo aplica la ventana normal, así que solo
  se inician las publicaciones todavía dentro de su ventana y nunca hay "volcado" de
  antiguas (FR-023). Tras `PUT` con `paused=false` se despierta el worker para no esperar
  hasta 30 s (`scheduler.wake()`, que activa un `threading.Event` de despertar).

**Razón**: persistente (FR-021), trivial y genérica; deja sitio para futuros ajustes
globales sin tabla clave-valor sin tipos.

**Alternativas descartadas**: variable de entorno o archivo de configuración (no editable
desde la interfaz ni persistente tras cambiarla); tabla clave-valor genérica (sin tipos ni
restricciones).

## 9. Origen del intento: `publication_attempts.trigger`

**Decisión**: columna `trigger` `String(20) NOT NULL`, CHECK `trigger IN ('manual',
'scheduled')`, `server_default 'manual'` para que los intentos existentes queden como
manuales (FR-033). Enum `AttemptTrigger` en `models.py` (sincronizado con
`frontend/src/types.ts`). `create_running_attempt(..., trigger)` lo rellena;
`PublicationAttemptRead.trigger` lo expone; la interfaz muestra `Started manually` /
`Started by scheduler`.

**Razón**: genérico, una columna, sin datos de plataforma.

## 10. Estado derivado de la automatización (overdue y compañía)

**Decisión**: función pura en `app/automation.py`:

```text
auto_publish_state(status, auto_publish_enabled, scheduled_at, paused, now)
  -> None | "disabled" | "waiting" | "due" | "paused" | "overdue"
```

| Valor | Condición (solo para `status = scheduled`; `None` en otro caso) |
|-------|------------------------------------------------------------------|
| `disabled` | no armada (aunque la fecha haya pasado: **nunca** overdue) |
| `overdue` | armada y `now > scheduled_at + 10 min` (condición overdue, FR-019; el estado sigue `scheduled`) |
| `paused` | armada, no `overdue`, automatización pausada |
| `waiting` | armada, `now < scheduled_at` |
| `due` | armada, dentro de la ventana, a la espera de que el scheduler la inicie |

`PublicationRead` gana `auto_publish_enabled`, `auto_publish_state`,
`auto_publish_window_ends_at` y `auto_publish_error` (`{code, message, failed_at}` o
`null`). El cálculo usa el reloj de la aplicación (`app.state.clock`, por defecto
`utc_now`, el mismo que recibe el scheduler) y una sola lectura de `paused` por petición
(también en el listado de la Queue).

Desarmar una publicación overdue la convierte inmediatamente en `disabled`; reprogramarla
a una fecha futura calcula la nueva ventana desde esa fecha.

**Razón**: un único lugar define overdue para la API, la interfaz y los tests; no se
persiste ningún estado nuevo (FR-019).

## 11. Interfaz: armado explícito, estado global y refresco

**Decisión**:

- **Programar** (creación con fecha y `ScheduleForm` del detalle): casilla
  "Publish automatically at this time" con el valor actual (desmarcada por defecto en
  creación y para publicaciones no armadas). El botón cambia de texto según la casilla:
  `Schedule & enable auto-publish` o `Save schedule` (sin armar), y bajo la casilla se
  explica "AutoPublisher will upload this publication automatically when the time comes.
  It must be running at that time." El formulario siempre envía `scheduled_at` y
  `auto_publish_enabled` juntos.
- **Detalle** de una publicación `scheduled`: estado (`Auto-publish enabled` / `Auto-publish
  disabled` / `Automation paused` / `Missed automatic publishing window — Publish now or
  reschedule`), último error automático si existe, y botones `Enable auto-publish` (solo
  con fecha futura; diálogo de confirmación con la fecha y el destino) y `Disable
  auto-publish`.
- **Queue**: misma etiqueta por fila (componente `AutoPublishBadge`), y en la cabecera un
  componente `AutomationStatus`: "Automation running · last check HH:MM" o "Automation
  paused", botón `Pause automation` / `Resume automation`, y la nota "AutoPublisher must be
  running to publish automatically."
- **Historial de intentos**: `Started manually` / `Started by scheduler`.
- **Refresco** (FR-037): la Queue y el detalle ya sondean cada 2 s mientras hay algo
  `publishing`. Se añade un sondeo de **15 s** mientras exista alguna publicación armada
  (`waiting`, `due` o `paused`): un inicio automático se ve como máximo 15 s después y, a
  partir de ahí, el sondeo rápido existente muestra el progreso. Los cambios de etiqueta
  por tiempo (`waiting` → `due` → `overdue`) llegan con el mismo sondeo.

**Alternativas descartadas**: WebSocket/SSE (mismo motivo que en la Feature 006);
interruptor global en una página de ajustes nueva (la spec pide algo sencillo y visible).

## 12. Tiempo, zonas horarias y DST

**Decisión**: sin cambios de modelo: `scheduled_at` ya se guarda en UTC (`UTCDateTime`) y
el frontend convierte la hora local del `datetime-local` a ISO UTC
(`fromDateTimeLocalValue`). Toda la lógica nueva compara instantes UTC conscientes de
zona; la ventana es `timedelta(minutes=10)` en UTC, por lo que un cambio de hora local no
la acorta ni la alarga. Tests:

- backend: `scheduled_at` enviado con offsets distintos (`+02:00` antes y `+01:00` después
  del cambio de hora de octubre en Europe/Madrid) se almacena y evalúa como el mismo
  instante UTC; ventana evaluada con reloj falso alrededor de la hora repetida;
- frontend: conversión local → UTC con `TZ=Europe/Madrid` en la hora repetida/omitida
  (prueba unitaria de `utils.ts`).

**Saltos de reloj**: cada ciclo usa la hora actual; un salto hacia delante que deja una
publicación fuera de la ventana la deja overdue (sigue `scheduled`); uno hacia atrás puede retrasar el
inicio pero nunca adelantarlo respecto a `scheduled_at`.

## 13. Seguridad y arquitectura

**Decisión**:

- `scheduler.py` y `automation.py` no importan `app.youtube_*`, `app.credential_store`,
  `httpx`/`httpx2` ni `keyring`; el test de arquitectura existente se amplía a ambos
  módulos (FR-003).
- El scheduler solo maneja ids, fechas, códigos y mensajes seguros; nunca recibe
  `PreparedPublication.payload` (se queda dentro de `start_publication`).
- Los logs del scheduler incluyen ids de publicación, códigos de error y nombres de clase
  de excepción; nunca mensajes de excepciones arbitrarias (pueden contener URLs).
- Tests de fuga existentes (`FAKE_UPLOAD_ID`, tokens falsos) se repiten para ejecuciones
  iniciadas por el scheduler: SQLite (`.dump`), respuestas de la API y logs a nivel
  `DEBUG`.

## 14. Migración `0006_automatic_publishing`

**Decisión**: una migración Alembic sin efectos externos:

- `publications` (modo *batch*): `auto_publish_enabled` (`server_default '0'`),
  `auto_publish_error_code`, `auto_publish_error_message`, `auto_publish_failed_at`,
  CHECKs de §3 y §7, e índice `ix_publications_status_auto_publish_scheduled_at`
  (`status`, `auto_publish_enabled`, `scheduled_at`) para la consulta del ciclo;
- `publication_attempts` (modo *batch*): `trigger` con `server_default 'manual'` y su CHECK;
- `automation_settings`: creación e inserción de la fila singleton
  `(1, automation_paused=false)` (§8).

`downgrade()` elimina lo añadido. El test de migraciones parte de una base en `0005` con
publicaciones `scheduled` (con fecha pasada, en ventana y futura) e intentos existentes y
comprueba que tras `0006` ninguna está armada, todos los intentos son `manual`, existe la
fila de ajustes con `automation_paused = false` y no se ha invocado ningún publisher.

**Razón**: FR-014, FR-040; mismo patrón que `0005`.
