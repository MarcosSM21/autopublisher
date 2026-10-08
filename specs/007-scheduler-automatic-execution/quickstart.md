# Quickstart: validar la publicación automática

**Feature**: `007-scheduler-automatic-execution` | **Fecha**: 2026-10-07

Guía para comprobar la feature de extremo a extremo. Las comprobaciones automáticas usan
reloj falso, publishers simulados y el simulador de YouTube: no necesitan Internet ni
esperas reales. La validación con YouTube real (§3) es **manual**, sube un vídeo de verdad
y no se ejecuta en CI.

Referencias: [contracts/api.md](contracts/api.md), [data-model.md](data-model.md),
[research.md](research.md).

> **Importante**: AutoPublisher solo publica automáticamente mientras el backend está en
> ejecución. Si está cerrado, suspendido o apagado a la hora programada, solo recupera la
> publicación si vuelve a arrancar en los 10 minutos siguientes.

---

## 1. Comprobaciones automáticas

```bash
cd backend
uv sync
uv run pytest                 # incluye scheduler con reloj falso, sin Internet
uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm ci
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

Resultado esperado: todo en verde, también sin red, en un tiempo similar al de la
Feature 006 (sin esperas de 30 s).

## 2. Requisitos para la validación manual

- Todo lo de `specs/006-youtube-manual-publishing/quickstart.md` §2: cuenta YouTube
  **conectada**, vídeo pequeño de prueba importado como `Content`, cliente OAuth y almacén
  seguro operativos.
- Reloj del sistema en hora (sincronización automática activa).
- **Antes de actualizar** a esta versión, si existe alguna publicación `Scheduled` en la base
  local, anotar su id: se usará en §5.3.

### Arranque

```bash
cd backend && uv run uvicorn app.main:app --reload    # http://127.0.0.1:8000
cd frontend && npm run dev                              # http://localhost:5173
```

En la salida del backend no debe aparecer ningún error al arrancar. El orden es:
migraciones → publishers → recuperación de intentos interrumpidos → scheduler.

## 3. Flujo principal con YouTube real (SC-001, SC-002)

| # | Acción | Resultado esperado |
|---|--------|--------------------|
| 1 | Abrir la Queue del proyecto. | Cabecera con **Automation running** (y la hora de la última comprobación tras ≤ 30 s), botón **Pause automation** y la nota "AutoPublisher must be running to publish automatically." |
| 2 | Crear una publicación del vídeo de prueba para la cuenta YouTube conectada, con fecha **dentro de 4–5 minutos**, sin marcar "Publish automatically at this time". | El botón dice **Save schedule**. Estado `Scheduled` con `Auto-publish disabled`. |
| 3 | En el detalle, configurar opciones YouTube: privacidad `private`, Notify subscribers `No`, Made for Kids `No`, Altered/synthetic `No`. | Opciones guardadas. |
| 4 | En el formulario de programación, marcar "Publish automatically at this time". | El botón cambia a **Schedule & enable auto-publish** y se explica que AutoPublisher subirá el vídeo solo a esa hora y debe estar en ejecución. |
| 5 | Pulsar **Schedule & enable auto-publish**. | `Auto-publish enabled`, "Waiting for its time". En la Queue, la misma etiqueta. |
| 6 | **No pulsar Publish now.** Esperar sin tocar nada con backend y frontend abiertos. | Antes de la hora sigue `Scheduled`; ninguna petición de subida en los logs. |
| 7 | Llegada la hora. | En ≤ 60 s la publicación pasa a `Publishing` sola; la Queue se actualiza sin recargar (≤ 15 s tras el inicio). Progreso visible. |
| 8 | Esperar a que termine. | `Published`, con **Open on YouTube**, privacidad real `private`. |
| 9 | Abrir el historial de intentos. | Un único intento, **Started by scheduler**. |
| 10 | **Open on YouTube** y YouTube Studio → Content. | Una sola copia del vídeo, privada, sin notificación a suscriptores. |
| 11 | Parar y volver a arrancar backend y frontend. | Sigue `Published` con el mismo resultado; el intento sigue **Started by scheduler**; el scheduler no la vuelve a ejecutar. |
| 12 | Inspección de secretos (§6). | Sin secretos nuevos. |

Al terminar, borrar el vídeo de prueba manualmente en **YouTube Studio** si se desea.
Anotar en el PR el retraso observado entre `scheduled_at` y el paso a `Publishing`. No
incluir video IDs ni URLs.

## 4. Pausa y reanudación (sin subida real)

Usar una cuenta YouTube **desconectada** o una publicación con Made for Kids sin declarar
para que, si algo fallara, no se suba nada; la pausa debe impedir incluso el preflight.

| # | Acción | Resultado esperado |
|---|--------|--------------------|
| 1 | Programar y armar una publicación para dentro de 2 minutos. | `Auto-publish enabled`. |
| 2 | Pulsar **Pause automation**. | Cabecera: **Automation paused**; la publicación muestra `Automation paused`. |
| 3 | Parar y arrancar el backend. | Sigue **Automation paused** (persistente). |
| 4 | Esperar a que pase la hora (sin superar 10 min). | Sigue `Scheduled`; no aparece `auto_publish_error` (no hubo preflight). |
| 5 | Pulsar **Resume automation** dentro de la ventana. | En pocos segundos el scheduler la intenta. Comportamiento observable (sin importar en qué paso del preflight se detecte): no pasa a `Publishing`; no se crea ninguna subida (ningún vídeo en YouTube Studio, ningún intento en el historial); sigue `Scheduled`; se muestra el motivo del fallo automático, un mensaje seguro de conexión/reconexión requerida cuyo texto exacto es el de la implementación final. |
| 5b | Reiniciar el backend inmediatamente (< 120 s después del fallo). | No hay una comprobación inmediata: la hora del fallo mostrada no cambia hasta que pasan 120 s desde el anterior (límite persistente). |
| 6 | Pausar, programar y armar otra publicación para dentro de 1 minuto y esperar > 11 minutos. Reanudar. | No se ejecuta: **Missed automatic publishing window · Publish now or reschedule**. |
| 7 | Con la automatización pausada, pulsar **Publish now** sobre una publicación válida (opcional, sube un vídeo real `private`). | Funciona normalmente; intento **Started manually**. |

## 5. Overdue, desarmado y migración (sin subida real)

### 5.1 Publicación armada fuera de la ventana

1. Programar y armar una publicación para dentro de 2 minutos.
2. Parar el backend antes de esa hora y arrancarlo **más de 10 minutos después**.
3. Resultado: sigue `Scheduled`, **Missed automatic publishing window**, sin intentos.
4. Pulsar **Disable auto-publish** → pasa a `Auto-publish disabled` (ya no es overdue).
5. Reprogramar a una hora futura con **Schedule & enable auto-publish** → vuelve a
   `Auto-publish enabled` con la ventana calculada desde la nueva fecha.

### 5.2 Publicación desarmada con fecha pasada

1. Programar una publicación para dentro de 1 minuto **sin** armarla y esperar 12 minutos.
2. Resultado: `Scheduled` con **Auto-publish disabled**; **no** muestra "Missed automatic
   publishing window"; **Publish now** y la reprogramación siguen disponibles; nunca se
   ejecuta sola.

### 5.3 Publicaciones preexistentes

1. Con la base anterior a la actualización (§2), arrancar el backend nuevo.
2. Las publicaciones `Scheduled` anotadas aparecen con **Auto-publish disabled** y no se
   ejecutan al llegar su hora.
3. Comprobación directa:

   ```bash
   sqlite3 backend/data/autopublisher.db \
     "SELECT id, status, scheduled_at, auto_publish_enabled FROM publications WHERE status='scheduled';"
   sqlite3 backend/data/autopublisher.db \
     "SELECT trigger, count(*) FROM publication_attempts GROUP BY trigger;"
   sqlite3 backend/data/autopublisher.db "SELECT * FROM automation_settings;"
   ```

   Esperado: `auto_publish_enabled = 0` en todas las preexistentes; intentos anteriores
   `manual`; una fila con `automation_paused = 0` (la automatización empieza activa, pero no
   hay nada armado). La cabecera de la Queue muestra **Automation running**.

### 5.4 Cancelar y reactivar

1. Programar y armar una publicación para mañana; cancelarla; reactivarla.
2. Resultado: `Scheduled` con **Auto-publish disabled**; hay que volver a armarla.

## 6. Inspección de secretos

```bash
sqlite3 backend/data/autopublisher.db \
  "SELECT id, status, auto_publish_enabled, auto_publish_error_code, auto_publish_error_message FROM publications;"
sqlite3 backend/data/autopublisher.db .dump | grep -E 'ya29\.|1//|upload_id|Bearer' || echo "no secrets in SQLite"
```

- Salida del backend: los mensajes del scheduler solo contienen ids de publicación, códigos
  de error y nombres de clase; buscar `upload_id`, `Bearer` y `ya29.` sin resultados.
- Herramientas de desarrollo del navegador (Network): `GET /api/automation` y los
  listados no contienen tokens ni URIs de sesión. `localStorage` / `sessionStorage` no
  contienen datos sensibles.

## 7. Resultado

La feature se considera validada cuando §1 pasa completo y §3–§6 se cumplen. En el PR:
retraso observado hasta `Publishing`, resultado de pausa/overdue/migración, sin video IDs ni
URLs reales.
