# Data Model: scheduler y ejecución automática

**Feature**: `007-scheduler-automatic-execution` | **Fecha**: 2026-10-07

Cambios sobre el modelo de las Features 004–006. Todo es genérico (ningún campo depende de
una plataforma). Decisiones y alternativas en [research.md](research.md).

---

## 1. `publications` (existente): columnas nuevas

| Columna | Tipo | Nulo | Por defecto | Significado |
|---------|------|------|-------------|-------------|
| `auto_publish_enabled` | `BOOLEAN` | no | `0` (`server_default`) | Consentimiento explícito: el scheduler puede iniciarla al llegar `scheduled_at` |
| `auto_publish_error_code` | `VARCHAR(40)` | sí | `NULL` | Código seguro del último fallo de inicio automático |
| `auto_publish_error_message` | `VARCHAR(500)` | sí | `NULL` | Mensaje comprensible y seguro de ese fallo |
| `auto_publish_failed_at` | `UTCDateTime` | sí | `NULL` | Momento (UTC) de ese último fallo; base persistente de la re-comprobación limitada (`now >= failed_at + 120 s`) |

### Restricciones nuevas

```text
ck_publications_auto_publish_only_scheduled:
    auto_publish_enabled = 0 OR status = 'scheduled'

ck_publications_auto_publish_error_only_armed:
    auto_publish_enabled = 1
    OR (auto_publish_error_code IS NULL
        AND auto_publish_error_message IS NULL
        AND auto_publish_failed_at IS NULL)

ck_publications_auto_publish_error_pair:
    (auto_publish_error_code IS NULL) = (auto_publish_error_message IS NULL)
    AND (auto_publish_error_code IS NULL) = (auto_publish_failed_at IS NULL)
```

Índice nuevo: `ix_publications_status_auto_publish_scheduled_at`
(`status`, `auto_publish_enabled`, `scheduled_at`) para la consulta del ciclo.

Se mantienen sin cambios los CHECK y el índice de duplicados de las Features 004/006.

### Escrituras que tocan las columnas nuevas

| Operación | `auto_publish_enabled` | Error automático |
|-----------|------------------------|------------------|
| Crear con fecha y `auto_publish_enabled=true` | `1` | `NULL` |
| Crear sin fecha o sin armar | `0` | `NULL` |
| `PATCH` armar (`true`, fecha futura) | `1` | `NULL` |
| `PATCH` desarmar (`false`) | `0` | `NULL` |
| `PATCH` cambia `scheduled_at` sin `auto_publish_enabled` | `0` | `NULL` |
| `PATCH` cambia `scheduled_at` con `auto_publish_enabled=true` | `1` | `NULL` |
| `PATCH` `scheduled_at=null` (→ `unscheduled`) | `0` | `NULL` |
| Cancelar | `0` | `NULL` |
| Reactivar | `0` (sigue) | `NULL` (sigue) |
| Inicio de ejecución (manual o scheduler) → `publishing` | `0` | `NULL` |
| Fallo de inicio automático (scheduler) | sin cambio (`1`) | código, mensaje, `failed_at = now` |
| Editar overrides u opciones de plataforma | sin cambio | sin cambio |

El fallo de inicio automático se escribe con un `UPDATE` condicional
`WHERE id=:id AND status='scheduled' AND auto_publish_enabled=1 AND
scheduled_at=:scheduled_at_evaluada`, para no tocar una publicación cambiada entre medias.

## 2. `publication_attempts` (existente): columna nueva

| Columna | Tipo | Nulo | Por defecto | Significado |
|---------|------|------|-------------|-------------|
| `trigger` | `VARCHAR(20)` | no | `'manual'` (`server_default`) | Cómo nació el intento |

```text
ck_publication_attempts_trigger_valid: trigger IN ('manual', 'scheduled')
```

Enum `AttemptTrigger` (`MANUAL = "manual"`, `SCHEDULED = "scheduled"`) en `models.py`,
sincronizado con `frontend/src/types.ts`. Los intentos existentes quedan `manual`. Las reglas
de ciclo de vida, `stage`, ambigüedad y secretos de la Feature 006 no cambian.

## 3. `automation_settings` (nueva, global)

| Columna | Tipo | Nulo | Por defecto | Significado |
|---------|------|------|-------------|-------------|
| `id` | `INTEGER` PK | no | — | Siempre `1` (`CHECK (id = 1)`) |
| `automation_paused` | `BOOLEAN` | no | `0` | `Pause automation` activo |
| `updated_at` | `UTCDateTime` | no | — | Último cambio |

Fila singleton. La migración la inserta con `automation_paused = false`: es seguro porque
la misma migración deja todas las publicaciones con `auto_publish_enabled = false`, así que
no hay nada que ejecutar hasta que el usuario arme algo. `Pause automation` / `Resume
automation` modifican después este valor. Lectura: si la fila no existiera (base
manipulada a mano), se trata como **pausada** y se registra un aviso; `PUT
/api/automation` la vuelve a crear.

La pausa solo afecta a los inicios `scheduled`; `Publish now` (`manual`) nunca la consulta.

## 4. Estado derivado (no persistido)

Ventana automática: `AUTO_PUBLISH_WINDOW = 10 min` (constante en `app/automation.py`).

```text
window_ends_at = scheduled_at + 10 min
in_window      = scheduled_at <= now <= window_ends_at        (ambos inclusive)
overdue        = status = 'scheduled' AND auto_publish_enabled AND now > window_ends_at
```

`auto_publish_state` (solo para `status = 'scheduled'`; `null` en cualquier otro estado),
evaluado en este orden:

| # | Condición | Valor | Etiqueta en la interfaz |
|---|-----------|-------|-------------------------|
| 1 | no armada | `disabled` | `Auto-publish disabled` (también con fecha pasada: **no** es overdue) |
| 2 | `now > window_ends_at` (overdue) | `overdue` | `Missed automatic publishing window` · `Publish now or reschedule` |
| 3 | automatización pausada | `paused` | `Auto-publish enabled` · `Automation paused` |
| 4 | `now < scheduled_at` | `waiting` | `Auto-publish enabled` · "Waiting for its time" |
| 5 | en ventana | `due` | `Auto-publish enabled` · "Starting soon" |

Ejemplos (`scheduled_at = 18:00:00Z`, armada, sin pausa): 17:59:59 → `waiting`;
18:00:00 → `due`; 18:09 → `due`; 18:10:00 → `due`; 18:10:00.000001 → `overdue` (el estado
sigue siendo `scheduled`).

## 5. Elegibilidad automática (scheduler)

Una publicación se **selecciona** en un ciclo si:

```text
status = 'scheduled' AND auto_publish_enabled = 1
AND scheduled_at <= now AND scheduled_at >= now - 10 min
AND (auto_publish_failed_at IS NULL OR now >= auto_publish_failed_at + 120 s)
```

y la automatización no está pausada (si lo está, no se consulta nada). Orden:
`scheduled_at ASC, id ASC`. Como `auto_publish_failed_at` está persistido, el límite de
120 s se mantiene tras un reinicio.

**Slots automáticos**: máximo 2. Un slot está ocupado por cada intento `running` con
`trigger = 'scheduled'` (la publicación entró correctamente en `publishing` por el
scheduler) y se libera cuando termina (`published` o `failed`). Los intentos `manual` no
cuentan. Al inicio del ciclo se calculan los slots libres para no hacer preflights inútiles;
la garantía está en el `UPDATE` siguiente.

Una seleccionada se **inicia** solo si, además, pasa el preflight completo de la
Feature 006 y, **después** del preflight, gana el `UPDATE` condicional atómico
(research §5), que re-comprueba todas las condiciones en la misma decisión:

```text
UPDATE publications
SET status='publishing', auto_publish_enabled=0,
    auto_publish_error_code=NULL, auto_publish_error_message=NULL,
    auto_publish_failed_at=NULL, updated_at=:now
WHERE id=:id AND status='scheduled' AND auto_publish_enabled=1
  AND NOT EXISTS (SELECT 1 FROM automation_settings WHERE id=1 AND automation_paused=1)
  AND scheduled_at <= :now AND scheduled_at >= :now - 10 min
  AND NOT EXISTS (SELECT 1 FROM publication_attempts
                  WHERE publication_id=:id AND status='running')
  AND (SELECT count(*) FROM publication_attempts
       WHERE status='running' AND trigger='scheduled') < 2
```

seguido, en la misma transacción, del `INSERT` del intento `running` con
`trigger='scheduled'` (índice único parcial de intentos en curso). Si cualquier condición
deja de cumplirse, no se inicia nada.

`Publish now` usa el `UPDATE` de la Feature 006 (`status IN ('unscheduled','scheduled',
'failed')`) sin estas guardas: no le afectan la pausa, la ventana ni los slots; solo
desarma y limpia el fallo automático.

## 6. Transiciones (resumen)

```text
                 PATCH fecha+armar / crear armada
UNSCHEDULED ───────────────────────────────────────▶ SCHEDULED (armada)
     ▲                                                  │  ▲
     │ PATCH scheduled_at=null (desarma)                │  │ PATCH auto_publish_enabled
     │                                                  ▼  │
     └──────────────────────────────────────────── SCHEDULED (desarmada)

SCHEDULED (armada) ── scheduler: en ventana + preflight OK + UPDATE gana ──▶ PUBLISHING
                                                         (trigger = scheduled, desarma)
SCHEDULED (cualquiera) ── Publish now ──▶ PUBLISHING (trigger = manual, desarma)
SCHEDULED (armada) ── preflight automático falla ──▶ SCHEDULED (armada, con error)
SCHEDULED (armada) ── pasa la ventana ──▶ SCHEDULED (armada, derivado: overdue)
SCHEDULED ── cancelar ──▶ CANCELLED (desarmada) ── reactivar ──▶ SCHEDULED/UNSCHEDULED (desarmada)
PUBLISHING ──▶ PUBLISHED / FAILED   (reglas de la Feature 006, sin cambios)
FAILED ── solo Publish now manual (Feature 006) ──▶ PUBLISHING (trigger = manual)
```

## 7. Entidades en memoria (no persistidas)

- **`SchedulerSettings`**: `clock`, `interval` (30 s), `wait`, `autostart`,
  `max_concurrent` (2), `preflight_retry_interval` (120 s), `stop_timeout` (5 s).
- **`Scheduler`**: hilo, `stop_event`, `wake_event`, `last_tick_at` (expuesto como
  "última comprobación"; se pierde al reiniciar, a propósito).
- **`TickReport`** (para tests y logs): ids iniciados, ids con preflight fallido, ids
  saltados por capacidad o por re-comprobación reciente.

## 8. Sin cambios

`projects`, `accounts`, `contents`, `youtube_connections`, `youtube_publication_options` y
el almacén seguro de credenciales. El scheduler no guarda nada fuera de las columnas
anteriores.

## 9. Migración `0006_automatic_publishing`

1. `publications` (batch, `recreate="always"`): añadir las 4 columnas
   (`auto_publish_enabled` con `server_default=sa.false()`), los 3 CHECK y el índice.
2. `publication_attempts` (batch): añadir `trigger` con `server_default='manual'` y su CHECK.
3. Crear `automation_settings` e insertar la fila singleton
   `(id=1, automation_paused=false, updated_at=now_utc)`.

Ninguna operación lee credenciales ni contacta con plataformas. `downgrade()` revierte los
tres pasos. Test: base en `0005` con publicaciones `scheduled` (pasada, en ventana, futura)
e intentos → tras `0006`: `auto_publish_enabled = 0` en todas, `trigger = 'manual'` en
todos, una fila de ajustes con `automation_paused = 0`; además, coincidencia modelo ↔ migración.
