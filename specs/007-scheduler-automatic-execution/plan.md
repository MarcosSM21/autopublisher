# Implementation Plan: Scheduler y ejecución automática de publicaciones programadas

**Branch**: `007-scheduler-automatic-execution` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-scheduler-automatic-execution/spec.md`

## Summary

Un scheduler local dentro del backend inicia automáticamente las publicaciones
`scheduled` que el usuario ha **armado** explícitamente cuando llega su hora, siempre que
siga dentro de una ventana de 10 minutos. Para hacerlo llama al mismo servicio genérico
`start_publication` de la Feature 006. No introduce dependencias ni infraestructura nuevas.

**Worker** (`app/scheduler.py`): un hilo daemon que ejecuta `run_once()` al arrancar y
después cada 30 s. El reloj, la espera, el intervalo, la concurrencia (2) y la
re-comprobación del preflight (120 s) se inyectan con `SchedulerSettings`. Arranca en el
`lifespan` después de migraciones → publishers → recuperación de intentos interrumpidos, y
se detiene antes que el `PublicationRunner`.

**Consentimiento**: columna `publications.auto_publish_enabled` (por defecto `0`; la
migración no arma nada). Un CHECK la limita a `scheduled`, así que cualquier salida de ese
estado la desarma: inicio de la ejecución, cancelación, reactivación o quitar la fecha. Una
fecha nueva sin `auto_publish_enabled` explícito queda desarmada. La interfaz muestra
`Schedule & enable auto-publish` frente a `Save schedule`.

**Reclamación atómica**: `start_publication(..., trigger=SCHEDULED, clock=…)` comprueba la
elegibilidad sin red y ejecuta el preflight completo existente. **Después** del preflight,
el `UPDATE` condicional de la Feature 006 re-comprueba en la misma transacción que crea el
intento: `scheduled`, armada, `automation_paused = false`, dentro de la ventana con el reloj
de ese instante, sin ejecución activa y con un slot automático libre. Ese mismo `UPDATE`
desarma la publicación. El intento se crea con `trigger = 'scheduled'` y sigue protegido por
el índice único parcial. Ticks concurrentes, varios workers o un `Publish now` simultáneo
producen como máximo un intento. `Publish now` (`manual`) no tiene ninguna de estas guardas
nuevas: no le bloquean la pausa ni los slots.

**Concurrencia automática**: como máximo 2 intentos `running` con `trigger = 'scheduled'`.
El slot se ocupa al entrar en `publishing` por el scheduler y se libera al terminar
(`published`/`failed`). Los manuales no cuentan. El límite forma parte del `UPDATE`
atómico, así que ni ciclos concurrentes ni varios workers pueden superarlo.

**Fallos de preflight**: la publicación sigue `scheduled` y no se crea intento. Se guardan
el código y el mensaje seguros existentes en `auto_publish_error_*` y el momento en
`auto_publish_failed_at`. El siguiente preflight automático solo ocurre cuando
`now >= auto_publish_failed_at + 120 s` y dentro de la ventana; como el momento está
persistido, el límite sobrevive a reinicios. Sin retries tras `FAILED`.

**Pausa global**: tabla singleton `automation_settings`, creada por la migración con
`automation_paused = false` (seguro: nada queda armado); `GET`/`PUT /api/automation`.

**Overdue**: estado derivado `auto_publish_state` (`disabled` | `waiting` | `due` |
`paused` | `overdue`), calculado al leer y nunca persistido como estado; `overdue` solo
existe para publicaciones armadas, que siguen `scheduled`.

**Frontend**: casilla y botón explícitos al programar, `Enable`/`Disable auto-publish` en
el detalle, etiquetas en la Queue, cabecera `AutomationStatus` con
`Pause`/`Resume automation`, origen del intento en el historial y sondeo de 15 s mientras
haya publicaciones armadas.

Decisiones detalladas en [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend); TypeScript sobre Node.js 22+ (frontend)

**Primary Dependencies**:

- Existentes: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, `httpx2`, `keyring`; React + Vite.
- **Ninguna dependencia nueva** (sin APScheduler ni librerías de tiempo; research §1).

**Storage**:

- SQLite: columnas nuevas en `publications` (`auto_publish_enabled`,
  `auto_publish_error_code`, `auto_publish_error_message`, `auto_publish_failed_at`) y en
  `publication_attempts` (`trigger`); tabla nueva `automation_settings` (singleton,
  `automation_paused = false` al crearla). Migración `0006`.
- Sistema de archivos y almacén seguro: sin cambios.

**Testing**:

- Backend: pytest + `TestClient`.
  - `create_app(..., scheduler_settings=SchedulerSettings(autostart=False, clock=fake))`
    con `app.state.scheduler.run_once()` llamado explícitamente.
  - `FakeClock` mutable compartido por el scheduler y las lecturas de la API
    (`app.state.clock`).
  - Publishers simulados (registro de publishers con un `FakePublisher` programable) para
    preflight, capacidad y concurrencia, y el simulador de YouTube de la Feature 006 para
    los flujos completos y los tests de fuga.
  - Concurrencia con `threading.Barrier` y el bloqueo por `threading.Event` ya existente
    en el simulador.
  - Un test del hilo real con `interval` muy pequeño y `wait` inyectada para arranque,
    parada limpia y orden de arranque.
- Frontend: Vitest + Testing Library con `FakeApi` ampliado y temporizadores falsos para
  los sondeos; prueba de conversión de fechas con `TZ=Europe/Madrid`.

**Quality tooling**: sin cambios (Ruff, mypy strict; Oxlint, Prettier, `tsc -b`). CI sin
cambios.

**Target Platform**: igual que la Feature 006 (uso local; Linux, macOS, Windows).

**Project Type**: aplicación web local (frontend + backend separados).

**Performance Goals**:

- Inicio < 60 s tras `scheduled_at` en condiciones normales: ciclo de 30 s + preflight
  (SC-002).
- Inicio visible en la interfaz ≤ 15 s después (sondeo), progreso con el sondeo de 2 s
  existente.
- Un ciclo sin candidatas es una consulta indexada; coste despreciable.

**Constraints**:

- Ninguna ejecución automática sin armado explícito, fuera de la ventana, con pausa o
  desde estados distintos de `scheduled` (FR-010, FR-011, FR-019–FR-023).
- Garantía de no duplicar en la base, no en memoria (FR-024, FR-025).
- Un solo preflight y un solo servicio de ejecución (FR-002, FR-028).
- El núcleo del scheduler no conoce plataformas (FR-003).
- Sin cron/systemd/cloud (FR-004). Tests sin Internet ni esperas reales (FR-044).

**Scale/Scope**:

- 1 migración; 1 tabla nueva; 5 columnas nuevas.
- 2 rutas nuevas (`GET`/`PUT /api/automation`); 5 rutas existentes con reglas o campos
  nuevos.
- 2 módulos backend nuevos (`automation.py`, `scheduler.py`); 2 componentes de interfaz
  nuevos (`AutomationStatus`, `AutoPublishBadge`).

No quedan `NEEDS CLARIFICATION`. Decisiones que la spec difería al plan:

| Decisión | Valor | Dónde |
|----------|-------|-------|
| Frecuencia del ciclo | 30 s (+ despertar inmediato al reanudar) | research §1, §8 |
| Límite de ejecuciones automáticas simultáneas | 2 slots `scheduled`, atómico en el `UPDATE`; manuales no cuentan | research §6 |
| Estrategia de reclamación | `UPDATE` condicional existente + guardas tras el preflight | research §5 |
| Ubicación de `auto_publish_enabled` | columna de `publications` con CHECK | research §3 |
| Ajuste de pausa | tabla `automation_settings` (singleton, `automation_paused = false` inicial) | research §8 |
| Último error automático | 3 columnas en `publications` | research §7 |
| Origen del intento | `publication_attempts.trigger` | research §9 |
| Re-comprobación del preflight | `now >= auto_publish_failed_at + 120 s` (persistente), solo dentro de la ventana | research §7 |
| Refresco de la interfaz | sondeo 15 s con publicaciones armadas | research §11 |
| Última comprobación | sí, en memoria (`last_check_at`) | research §1 |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|-----------|------------|--------|
| I. Simplicidad y control de alcance | Sin dependencias nuevas. Un hilo con `Event.wait` en lugar de librerías de scheduling o procesos externos. Reutiliza el `UPDATE` condicional y el índice único de la Feature 006 en lugar de leases o colas. El consentimiento es una columna booleana con CHECK; la pausa, una fila. Nada excluido: sin retries entre intentos, Calendar, recurrencias, notificaciones ni otras plataformas. | ✅ |
| II. Spec-Driven Development | Implementa la spec ajustada (overdue solo para armadas). Las decisiones diferidas quedan justificadas en research. El cambio frente a FR-004/SC-012 de la Feature 006 lo declara la propia spec (FR-001). | ✅ |
| III. Arquitectura modular | El scheduler es la pieza "scheduler/queue" de la Constitution: solo selecciona y llama a `start_publication`; no importa `app.youtube_*`, `credential_store`, `httpx`/`httpx2` ni `keyring` (el test de arquitectura existente se amplía a `scheduler.py` y `automation.py`). Todos los datos nuevos son genéricos. Los publishers no cambian. | ✅ |
| IV. Seguridad (repositorio público) | El scheduler no ve credenciales ni `PreparedPublication.payload`; guarda solo códigos y mensajes seguros ya existentes; registra en el log solo ids, códigos y nombres de clase. Los tests de fuga se amplían a las ejecuciones automáticas (SQLite, respuestas y logs a nivel `DEBUG`). | ✅ |
| V. Calidad y verificabilidad | Reloj y espera inyectables. Tests de tiempo (límites exactos, DST), arranque, consentimiento, pausa, duplicados, preflight, ejecución, concurrencia, migración, interfaz y seguridad. Ningún fallo silencioso: los preflights fallidos quedan visibles (`auto_publish_error`), las ventanas perdidas se ven como overdue (la publicación sigue `scheduled`) y las ejecuciones siguen las reglas de la Feature 006. | ✅ |
| VI. Git y trazabilidad | Rama `007-scheduler-automatic-execution`, commits pequeños en inglés. README: sección "Automatic publishing" (backend en ejecución, consentimiento, ventana de 10 min, overdue, pausa, publicaciones antiguas desarmadas). | ✅ |
| Arquitectura tecnológica base | Introduce el "scheduler local dirigido por la base de datos" previsto, dentro del backend FastAPI y sobre SQLite. | ✅ |
| Idioma y convenciones | Código, API, UI, README y commits en inglés; artefactos Spec Kit en español. | ✅ |

**Resultado pre-research**: PASS. **Re-check post-diseño**: PASS. El diseño de la Fase 1
no añade dependencias ni infraestructura más allá de lo listado.

## Project Structure

### Documentation (this feature)

```text
specs/007-scheduler-automatic-execution/
├── plan.md              # Este archivo
├── research.md          # Fase 0: worker, arranque, consentimiento, claim, concurrencia…
├── data-model.md        # Fase 1: columnas nuevas, automation_settings, estado derivado
├── quickstart.md        # Fase 1: validación automática y manual con YouTube real
├── contracts/
│   └── api.md           # Fase 1: contrato REST y servicio interno
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec
└── tasks.md             # Fase 2 (/speckit-tasks, aún no creado)
```

### Source Code (repository root)

```text
backend/
├── migrations/versions/
│   └── 0006_automatic_publishing.py  # publications: auto_publish_* + CHECKs + índice;
│                                     #   publication_attempts.trigger; automation_settings
│                                     #   con su fila (automation_paused = 0). Sin efectos externos
├── app/
│   ├── main.py              # create_app(..., scheduler_settings=None, clock=None);
│   │                        #   lifespan: migraciones → publishers → recover_interrupted
│   │                        #   → Scheduler en app.state → scheduler.start(); al cerrar
│   │                        #   scheduler.stop() antes de runner.stop();
│   │                        #   app.state.clock; include_router(automation)
│   ├── models.py            # Publication.auto_publish_* + CHECKs/índice;
│   │                        #   AttemptTrigger + PublicationAttempt.trigger;
│   │                        #   AutomationSettings
│   ├── schemas.py           # PublicationCreate/Update + auto_publish_enabled;
│   │                        #   PublicationRead + auto_publish_enabled/state/
│   │                        #   window_ends_at/error; PublicationAttemptRead.trigger;
│   │                        #   AutomationStatusRead, AutomationUpdate
│   ├── automation.py        # NUEVO, genérico: AUTO_PUBLISH_WINDOW, AutoPublishState,
│   │                        #   auto_publish_state(), auto_start_blocker(), is_paused(),
│   │                        #   set_paused(), scheduled_claim_conditions(now,
│   │                        #   max_concurrent) (estado, armado, pausa, ventana,
│   │                        #   sin ejecución activa, slot libre),
│   │                        #   record_auto_publish_error(), get_clock();
│   │                        #   router GET/PUT /api/automation
│   ├── scheduler.py         # NUEVO, genérico: SchedulerSettings, Scheduler (start, stop,
│   │                        #   wake, run_once, last_check_at, running), TickReport;
│   │                        #   selección + orden + capacidad + re-comprobación;
│   │                        #   llama a publishing.start_publication(trigger=SCHEDULED)
│   ├── publishing.py        # start_publication(..., trigger, clock);
│   │                        #   create_running_attempt(..., trigger, clock) con guardas
│   │                        #   de automation para SCHEDULED y desarmado en el UPDATE;
│   │                        #   attempts con trigger
│   └── publications.py      # Reglas de armado en create/PATCH; cancel/unschedule
│                            #   desarman y limpian el error; reactivate desarmada;
│                            #   campos derivados en PublicationRead (una lectura de
│                            #   paused por petición, reloj de app.state)
└── tests/
    ├── fakes.py             # + FakeClock, FakePublisher programable (problemas locales,
    │                        #   errores en prepare, bloqueo, recuento de prepare/upload)
    ├── conftest.py          # + fixtures scheduler_client (autostart=False, FakeClock),
    │                        #   arm(), run_tick(), helpers de tiempo
    ├── test_migrations.py   # + 0006 sobre base 0005 con scheduled pasadas/en ventana/
    │                        #   futuras e intentos: nada armado, trigger manual, fila de
    │                        #   ajustes; deriva modelo ↔ migración
    ├── test_automation_state.py   # auto_publish_state y ventana: futura, exacta, dentro,
    │                        #   límite 10:00 inclusive, después, desarmada con fecha
    │                        #   pasada (disabled), pausada, offsets y DST en UTC
    ├── test_auto_publish_consent.py # crear/PATCH armar y desarmar, fecha pasada → 422,
    │                        #   reprogramar sin campo → desarmada, null → desarmada,
    │                        #   cancelar/reactivar → desarmada, Publish now desarma,
    │                        #   inactivos, CHECK en base
    ├── test_automation_api.py     # GET/PUT /api/automation (inicial paused=false),
    │                        #   persistencia tras reinicio, fila ausente → pausada
    ├── test_scheduler_tick.py     # futura no se ejecuta; exacta/dentro/límite/después;
    │                        #   desarmada no; pausa sin preflight; reanudar dentro/fuera;
    │                        #   estados no elegibles; trigger scheduled vs manual;
    │                        #   éxito → PUBLISHED; fallo → FAILED sin nuevo intento;
    │                        #   ticks consecutivos sin duplicar; orden y desempate;
    │                        #   slots: 2 máx., manuales no cuentan, slot liberado al
    │                        #   terminar; espera de slot que expira → overdue
    ├── test_scheduler_preflight.py # proyecto/cuenta inactivos, reconexión, archivo
    │                        #   ausente, metadata, opciones, publisher ausente, red
    │                        #   temporal, remote_check_required: sin intento ni subida,
    │                        #   error guardado, re-comprobación ≥ failed_at + 120 s
    │                        #   también tras reiniciar (sin comprobación inmediata), fin de
    │                        #   ventana,
    │                        #   limpieza al reprogramar/desarmar/ejecutar
    ├── test_scheduler_concurrency.py # dos ticks simultáneos, dos Scheduler sobre la
    │                        #   misma base, tick + Publish now: 1 intento, 1 subida;
    │                        #   ciclos concurrentes con 4 candidatas nunca superan 2
    │                        #   slots; pausa/desarmado/reprogramación durante el
    │                        #   preflight → no se inicia; Publish now con pausa y con
    │                        #   los 2 slots ocupados sí se inicia
    ├── test_scheduler_lifecycle.py  # orden de arranque (recuperación antes del primer
    │                        #   tick), reinicio antes/dentro/después de la ventana,
    │                        #   parada limpia, fallo inesperado en un ciclo no detiene
    │                        #   el hilo, wake al reanudar
    ├── test_scheduler_secrets.py    # flujo automático con el simulador de YouTube: sin
    │                        #   tokens/upload_id en SQLite, respuestas ni logs DEBUG
    └── test_publications_states.py  # + test de arquitectura: scheduler.py y
                             #   automation.py sin imports youtube_*, credential_store,
                             #   httpx/httpx2, keyring

frontend/src/
├── types.ts                 # AutoPublishState, AttemptTrigger, AutomationStatus;
│                            #   Publication + auto_publish_*; PublicationAttempt.trigger
├── api.ts                   # getAutomation(), setAutomationPaused(); create/update con
│                            #   auto_publish_enabled
├── utils.ts                 # (sin cambios funcionales; test DST de la conversión)
└── components/
    ├── AutomationStatus.tsx # NUEVO: running/paused, última comprobación, Pause/Resume,
    │                        #   nota "must be running"
    ├── AutoPublishBadge.tsx # NUEVO: etiqueta por auto_publish_state + último error
    ├── PublicationCreate.tsx   # casilla "Publish automatically at this time" con fecha;
    │                        #   botón Schedule & enable auto-publish / Create
    ├── PublicationDetail.tsx   # ScheduleForm con casilla y botón explícito;
    │                        #   Enable/Disable auto-publish (confirmación al habilitar);
    │                        #   badge; sondeo 15 s con armada
    ├── PublicationQueue.tsx    # AutomationStatus en cabecera, badge por fila, sondeo
    │                        #   15 s con armadas además del de 2 s
    └── PublicationAttempts.tsx # Started manually / Started by scheduler

README.md                    # sección "Automatic publishing"
```

**Structure Decision**: misma aplicación web local (backend FastAPI + frontend React). La
lógica nueva genérica va en dos módulos backend nuevos (`automation.py`: reglas y API de la
automatización; `scheduler.py`: el worker), al lado de `publishing.py`, que solo cambia para
aceptar `trigger`/`now` y las guardas atómicas.

## Design Notes

- **Dependencias entre módulos**: `scheduler → publishing → automation`;
  `publications → automation`. `automation` no importa `publishing` ni `scheduler`, así que
  no hay ciclos.
- **Reloj único**: `app.state.clock` (por defecto `utc_now`) lo usan el scheduler, el
  `clock` de `start_publication` (consultado antes del preflight y justo antes del claim) y
  el mapper único de `Publication` (`publication_read`) para los campos derivados de todas
  las respuestas. Las
  validaciones existentes de "fecha futura" (`ensure_future`) siguen con `utc_now`.
- **`Publish now` no cambia de contrato**: `trigger` por defecto `MANUAL`; el único efecto
  nuevo es desarmar en la transición (exigido por el CHECK).
- **Sesiones**: cada candidata usa su propia sesión (`session_factory()`), para que un
  error o un `rollback` no afecte al resto del ciclo.
- **Logs**: `INFO` al iniciar una publicación automática (id); `WARNING` por cada fallo
  de preflight (id + código) solo la primera vez en esa ventana; `ERROR` por excepción
  inesperada (nombre de clase).
- **Documentación**: README ("Automatic publishing") y este `quickstart.md`; la UI repite
  que AutoPublisher debe estar en ejecución.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.
