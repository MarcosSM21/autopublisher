# Research: Calendar & Scheduling Power Tools (Feature 024)

Todo lo siguiente está verificado en el código de `main` (2026-10-26). Las referencias son a
rutas del repositorio.

---

## R1. El PATCH hoy y la carrera con el claim

### Cómo funciona hoy

`update_publication` (`backend/app/publications.py`) usa la sesión de la petición
(`get_session`):

1. `get_publication_or_404` → `session.get(Publication, id)`. pysqlite (modo journal por
   defecto, no WAL, timeout 5 s) **no emite `BEGIN` para un SELECT**: tras la lectura no queda
   ningún lock.
2. `ensure_editable(publication, schedule_change=…, session=session)` decide con el `status`
   leído (y, para `failed`, con `requires_remote_check`, que lee el último intento).
3. Mutaciones ORM en memoria: `scheduled_at`, `status` (`scheduled`/`unscheduled`),
   `disarm()`, `_set_consent()`, overrides. Validaciones intercaladas: `ensure_future`
   (`utc_now()`), `ensure_can_prepare` (proyecto/cuenta activos, `file_available` = un `stat`).
4. Si `arming`: `_arming_problems` → `publisher.arming_problems(session, publication)`. Sus
   consultas disparan **autoflush** (`sessionmaker(engine, expire_on_commit=False)`, autoflush
   por defecto): el `UPDATE publications … WHERE id = ?` se envía aquí, pysqlite emite `BEGIN`
   diferido y la conexión toma el lock RESERVED.
5. `session.commit()`; `publication_read(session, …)`.

El `UPDATE` del ORM solo lleva `WHERE id = ?` (no hay `version_id_col`): escribe los valores
calculados con el estado leído en 1.

### La carrera (confirmada leyendo el código)

El claim (`create_running_attempt`, `backend/app/publishing.py`) es un único
`UPDATE publications SET status='publishing', … WHERE id=? AND <condiciones>` + `INSERT` del
intento `running` + `COMMIT`. Si ese commit cae entre 1 y 4–5:

- el PATCH ya pasó `ensure_editable` con `status='scheduled'`;
- su `UPDATE` por `id` escribe `status='scheduled'`, `auto_publish_enabled`, `scheduled_at`…
  encima de `publishing`;
- resultado: Post `scheduled` con un intento `running` (viola la semántica de 007/019; el
  `CHECK` de la tabla no lo impide porque `scheduled` con fecha es válido).

El orden contrario ya es seguro: el claim vuelve a comprobar en su `UPDATE` estado,
consentimiento, ventana con el reloj actual y ausencia de intento en curso
(`scheduled_claim_conditions`), cubierto por
`test_scheduler_concurrency.py::test_changes_during_the_preflight_prevent_the_start`.

La ventana es de milisegundos y solo existe para Posts **dentro de su ventana automática**
(`scheduled_at ≤ now ≤ scheduled_at + 10 min`), que es cuando el scheduler los reclama. El drag
de 024 hace mucho más probable reprogramar justo esos Posts ("los de hoy").

---

## R2. Estrategias de atomicidad

### A. `write_transaction` (`BEGIN IMMEDIATE`) alrededor de todo el handler

- **Lock**: `BEGIN IMMEDIATE` toma RESERVED **como primera sentencia**, antes de leer. Ningún
  otro escritor (claim del scheduler, publish manual, persistencias del runner, otro PATCH,
  borrado) puede confirmar hasta el `COMMIT`/`ROLLBACK`. Las lecturas siguen permitidas a los
  demás.
- **Interacción con el scheduler**: si el PATCH tiene el lock, el `UPDATE` del claim espera
  (busy handler de pysqlite) y, al obtenerlo, evalúa sus condiciones sobre lo que el PATCH
  confirmó → `rowcount 0` → `publication_not_eligible` → `not_claimed`. Si el claim confirmó
  antes, el `BEGIN IMMEDIATE` del PATCH espera a ese `COMMIT` y su lectura ve `publishing` →
  `ensure_editable` → `409 publication_not_editable`. Este comportamiento (segundo escritor
  espera al COMMIT y lo ve) ya está validado en `test_write_transaction.py`
  (`test_a_second_writer_waits_for_the_commit_and_sees_it`) y en el borrado de Feature 021
  (research 021 §4–§5).
- **Duración**: lecturas de BD + `stat` del fichero + mutaciones + reglas de armado. Sin red.
  Comparado con hoy, el lock empieza antes (en el `BEGIN` en vez de en el autoflush de 4) pero
  la parte potencialmente lenta ya ocurre hoy bajo RESERVED:
  - `TikTokPublisher.arming_problems` en modo Upload to Inbox lee el keyring
    (`inbox_problems` → `can_upload_to_inbox` → `store.get`), **ya hoy después del autoflush,
    con RESERVED tomado**. A no lo empeora. El keyring es local; si no está disponible devuelve
    `CredentialStoreUnavailable` y la regla responde "sin permiso" sin esperar.
  - El resto de `arming_problems` (YouTube, Instagram, Threads: sin reglas; Telegram y TikTok
    Direct Post: filas de BD y checksum ya calculado) no hace E/S.
- **`ensure_editable` + mutación dentro**: sí, sin cambios; todas sus lecturas usan la sesión
  que se le pasa.
- **Operaciones externas dentro**: ninguna nueva. La declaración TikTok se registra antes, en su
  propio endpoint (`POST …/tiktok/consent`), no en el PATCH.
- **Regla de uso de 021**: la sesión de la petición no debe tener DML pendiente en el mismo
  hilo. El PATCH no escribe nada en la sesión de la petición: todas sus escrituras pasan a la
  sesión de `write_transaction`; la respuesta se lee después del commit.
- **Errores**: cada `raise` dentro del bloque hace rollback y se propaga sin cambios → mismos
  códigos HTTP y cuerpos. Si el lock no llega en 5 s → `OperationalError` → 500 genérico
  existente (igual que hoy cualquier escritor bloqueado; en la práctica no ocurre: los demás
  escritores son transacciones cortas).

### B. UPDATE condicional (compare-and-set)

Variante: mantener el handler y sustituir el `UPDATE` del ORM por
`UPDATE publications SET … WHERE id=? AND status=:leído [AND updated_at=:leído]`.

- **Reglas**: `ensure_editable` depende del `status` y, para `failed`, de los intentos. Solo
  `status=:leído` tiene un problema ABA (`failed → publishing → failed` con un intento nuevo e
  incierto entre medias: el guard pasaría). Añadir `updated_at=:leído` lo cierra, pero
  entonces dos reschedules concurrentes válidos chocan → hay que reintentar o devolver 409, lo
  que contradice FR-033 ("ambos terminan sin error, gana el último").
- **Duplicación**: obliga a reescribir las mutaciones como `values(...)` de Core o a usar
  `version_id_col` en el mapper (cambio global: `StaleDataError` en todos los escritores de
  `Publication`).
- **Distinguir errores**: `rowcount 0` exige releer y volver a ejecutar `ensure_editable` para
  elegir el código (409 adecuado) o reintentar.
- **Contrato**: preservable, pero con más código y más casos que A.

### C. Otras opciones del repositorio

- `ContentFileGuard` (lock en memoria por contenido, Feature 016): no cubre a otros escritores
  ni a los Posts sin contenido. Descartado.
- Locks Python / WAL: descartados por 021 por las mismas razones (no cubren todos los caminos
  de escritura / cambio global de journal).

### Decisión

**A — `write_transaction` alrededor de toda la lógica de decisión y escritura del PATCH.**

**Razón**: correcta por construcción (lectura y escritura bajo el único lock de escritor de
SQLite), cambio mínimo (el cuerpo del handler no cambia; solo la sesión), cero duplicación de
reglas, conserva todos los errores, ningún lock nuevo alrededor de operaciones lentas o
externas (la única lectura de keyring ya ocurre hoy bajo RESERVED), es el patrón aprobado de
021 y es testable de forma determinista con las barreras existentes
(`tests/barriers.py`). Cumple "gana el último" sin código extra: dos PATCH se serializan.

**Alternativas descartadas**: B (ABA o conflicto entre reschedules, más código); C (no cubre
todos los escritores).

---

## R3. Alcance exacto del backend

- Cambia solo `update_publication` (`PATCH /api/publications/{id}`): la decisión y las
  escrituras pasan a `write_transaction(session_factory)`; la respuesta se construye después
  con la sesión de la petición (`publication_read`), que entonces lee lo confirmado.
- La garantía cubre **todo** el PATCH (fecha, consentimiento y overrides), porque todo pasa por
  el mismo `ensure_editable`; no se distingue por campo.
- No cambian: `ensure_editable`, `ensure_future`, `ensure_can_prepare`, `_set_consent`,
  `_arming_problems`, `disarm`, el schema `PublicationUpdate`, `publication_read`, el claim, el
  scheduler, el runner.
- `POST /api/publications/{id}/cancel` **no se toca** (mismo patrón lectura-luego-escritura;
  problema conocido registrado en la spec).
- Sin migración, modelo ni endpoint nuevos.

---

## R4. Consumidores del PATCH (contrato a preservar)

| Consumidor | Envío | Notas |
|---|---|---|
| `ActionDialog` (Post detail) | `{scheduled_at, auto_publish_enabled: true}` (reschedule/edit_schedule), `{scheduled_at: null}` (move_to_drafts), `{auto_publish_enabled: true}` (publish_automatically) | Mapea `check_result_first`, `tiktok_consent_stale` y el resto vía `problemText` |
| `final-action.ts` (Publish/Review) | `{scheduled_at, auto_publish_enabled: true}` por Post | Programar al finalizar Publish |
| `usePublishTask.updateContent` (Review → Content by destination) | overrides | Un PATCH por Post |
| `PostContent` (Post detail) | overrides | |
| Tests backend | `test_publications_update.py`, `test_publications_states.py`, `test_auto_publish_consent.py`, `test_publish_arming.py`, `test_tiktok_consent.py`, `test_scheduler_concurrency.py` (PATCH durante preflight), `test_text_publications.py` | Deben pasar sin cambiar expectativas |

Se preservan request, response, códigos (`publication_cancelled`, `publication_not_editable`,
`check_result_first`, 422 de fecha pasada / `auto_publish_enabled`, `project_inactive`,
`account_inactive`, `media_unavailable`, problemas de armado por plataforma), Failed/Missed y
`scheduled_manual` legacy: el cuerpo del handler es el mismo.

---

## R5. `ActionDialog`: precarga y reutilización

Hoy (`frontend/src/pages/posts/ActionDialog.tsx`):

- `at` inicial = `toDateTimeLocalValue(scheduled_at)` si `action === "edit_schedule"` y
  `isFuture(scheduled_at)`; si no, `""`. Esto **ya cumple FR-004** para Quick Reschedule
  (Scheduled futura → precarga; Scheduled pasada, Missed, Failed → vacío).
- Título `TITLES[action]`: `Edit schedule` / `Reschedule`. Ya cumple el título exigido.
- Validación, declaración TikTok, envío (`updatePublication`), doble clic, errores: dentro.

**Decisión**: dos props opcionales, nada más:

- `initialAt?: string` (instante ISO): si se pasa, sustituye al valor inicial calculado. Solo lo
  usa el drop.
- `onFailed?: () => void`: se llama en el `catch` tras mostrar el error. Calendar lo usa para
  recargar la lista (FR-043). Post detail no lo pasa (sin cambio de comportamiento).

Calendar renderiza el mismo componente con `action = "edit_schedule" | "reschedule"`, `post`,
`posts` (lista completa sin filtrar, para el guard de "Check result"), `paused`, `onClose`,
`onDone`.

**Alternativas descartadas**: abrir el Post detail (dos pasos, no es "quick"); un formulario
nuevo (prohibido por FR-003); levantar el estado del diálogo a `PostsPage` (innecesario: Calendar
tiene todo lo que necesita).

---

## R6. Qué acción ofrece cada Post en Calendar

`postActions()` no sirve tal cual: para `scheduled_manual` su primaria es *Publish
automatically* y no ofrece *Edit schedule*; para `failed` la primaria es *Retry now*.

**Decisión**: función pura nueva en `calendar.ts`:

```text
scheduleAction(post):
  scheduled_automatic | scheduled_paused | scheduled_manual → "edit_schedule"
  missed | failed                                           → "reschedule"
  resto                                                     → null
canDrag(post): display_state ∈ {scheduled_automatic, scheduled_paused}
```

Ambas acciones ya existen en `ActionDialog` (`DialogAction`): no hay semántica nueva.

---

## R7. Control Quick Reschedule

Restricciones: el item es un `<Link>` completo con `data-detail-id` y `aria-current`; no se
puede anidar un botón dentro.

**Decisión**: el `<li>` pasa a contener dos hermanos: el `<Link>` actual (sin cambios de
contenido, atributos ni navegación) y un control de scheduling.

- Week view (columnas estrechas): `IconButton` existente (icono `clock`, 44×44) colocado en la
  esquina superior derecha de la tarjeta; el `<Link>` reserva ese hueco en su primera fila
  (la hora) con padding en línea, para que nada se solape con títulos largos.
- Agenda (<1280, incluye móvil): `Button` existente `variant="ghost"` con texto visible
  (*Edit schedule* / *Reschedule*) a continuación del enlace.
- Nombre accesible en ambos: `"<Acción>: <título del Post>"` (contiene el texto visible →
  label-in-name). Sin `title` (regla de `IconButton`).
- Orden de tabulación: enlace → control, por Post.

**Alternativas descartadas**: menú de acciones (no existe un primitive de menú compartido;
`NewPostMenu` es específico; más interacción para una sola acción); botón superpuesto sin
reservar espacio (solapes con títulos largos).

---

## R8. Drag & drop nativo

Precedente: `frontend/src/pages/library/usePageDrop.ts` (HTML5 DnD de ficheros) y sus tests con
`fireEvent.drop(…, { dataTransfer })` en `library.test.tsx`.

**Decisión** (solo con `isLarge`, es decir week view):

- **Origen**: el `<Link>` de un Post `canDrag` lleva `draggable` y `onDragStart`:
  `dataTransfer.clearData()` (quita la URL que el navegador pone para un enlace),
  `setData("application/x-autopublisher-post", id)`, `effectAllowed = "move"`; estado local
  `drag = { postId, scheduledAt, now }`. Los Links no arrastrables no cambian (su arrastre
  nativo de URL sigue como hoy y Calendar lo ignora porque no hay `drag`).
- **Destinos**: cada `<section>` de día tiene `onDragOver`/`onDrop`. Con `drag` activo:
  - clasificación pura por día: `source` (mismo día), `valid`, `invalid` (R9);
  - `onDragOver`: `preventDefault()` solo si `valid` o `source` (permite soltar);
    `dropEffect = "move"` en `valid`, `"none"` en el resto; guarda `over = dayKey` si cambió;
  - `onDrop`: `preventDefault()`; revalida (R11); si `valid` → abre el diálogo; si `source` o
    `invalid` → nada.
- **Fin**: `onDragEnd` en el origen limpia `drag` y `over` siempre (Escape, soltar fuera,
  después de un drop). Sin `dragenter`/`dragleave` (frágiles con hijos): el día resaltado es el
  último `over` y se limpia en `dragend`/`drop`.
- **Clic vs drag**: el navegador no emite `click` tras un arrastre; clic y Enter siguen siendo
  navegación del `<Link>`. No hay umbral propio.
- **Estado**: solo `drag` y `over` en `CalendarView`; nada persiste; el polling no se detiene.

**Alternativas descartadas**: librería DnD (prohibida, innecesaria para escritorio); pointer
events propios (más código, sin beneficio sin táctil); arrastre en agenda (no hay días vacíos ni
espacio de destino).

---

## R9. Fecha del drop (hora local de pared)

Utilidades existentes (`frontend/src/utils.ts`): `toDateTimeLocalValue(iso)` (ISO → valor
`datetime-local` local), `fromDateTimeLocalValue(value)` (local → ISO UTC), `isFuture(iso,
now)`. En `calendar.ts`: `dayKey`, `mondayOf`, `weekDays` (fechas locales a medianoche).

**Decisión**: función pura en `calendar.ts`:

```text
moveToDay(scheduledAt: string, target: Date, now: Date)
  → { at: string /* ISO */, kind: "source" | "valid" | "invalid" }

  source = new Date(scheduledAt)
  candidate = new Date(target.getFullYear(), target.getMonth(), target.getDate(),
                       source.getHours(), source.getMinutes())
  kind = dayKey(source) === dayKey(target) ? "source"
       : candidate > now                   ? "valid"
       :                                     "invalid"
```

- Cambio de mes/año: el constructor local con año/mes/día del destino es correcto (los
  `target` vienen de `weekDays`).
- DST: el constructor local normaliza una hora inexistente (salto de primavera) a la siguiente
  válida y elige la interpretación del navegador en la ambigua; el diálogo la muestra legible
  antes de confirmar. Sin sistema de zonas propio.
- Hoy con hora pasada: `candidate ≤ now` → `invalid`.
- Segundos: `scheduled_at` ya está al minuto; el candidato también.
- El ISO resultante se pasa como `initialAt` al diálogo, que lo muestra con
  `toDateTimeLocalValue`.

Tests deterministas: `now` y `target` inyectados; DST con `process.env.TZ` fijado en el test
(p. ej. `Europe/Madrid`) y restaurado después.

---

## R10. Refresco tras reschedule

- `usePostsData` ya es la única fuente: `reload()` (promesa) relee la lista; `PostDetail` lee el
  Post de esa lista (`listed`) y su copia `latest` solo gana si es más reciente.
- **Decisión**: `CalendarView` recibe `onChanged: () => Promise<void>` (= `data.reload`).
  `onDone` del diálogo → cerrar diálogo → `await onChanged()` → foco/anuncio (R13). `onFailed`
  → `void onChanged()`.
- Sin elemento fantasma: el render sale siempre de la lista recargada; no hay estado optimista.
- Post detail abierto: con `panelFrom="never"` el detalle es un Drawer modal (md+) o una página
  (móvil) con la lista oculta, así que no se puede usar Quick Reschedule de Calendar con el
  detalle abierto; tras cerrar, el detalle se reabre desde la lista ya recargada. FR-041 queda
  cubierto por el flujo existente.

---

## R11. Polling durante el arrastre

En `onDrop` se revalida con la lista actual (props frescas por el polling):

1. el Post `drag.postId` sigue en `posts`;
2. `canDrag(post)` sigue siendo cierto;
3. `post.scheduled_at === drag.scheduledAt` (si cambió, el cálculo ya no vale);
4. `moveToDay(post.scheduled_at, target, new Date())` sigue siendo `valid`.

Cualquier fallo → drop ignorado y feedback limpiado. Si el Post desaparece del DOM a mitad de
arrastre, `dragend` puede no dispararse en el nodo: `CalendarView` también limpia `drag` si el
Post ya no está en `posts` o dejó de ser `canDrag` (efecto sobre `posts`). El backend sigue
siendo la autoridad al confirmar.

---

## R12. FR-042 — Next / Up next

- **Dónde se calculan**: backend `overview.py` (`_next_posts` → `next_post` por proyecto,
  `upcoming` para Home).
- **Dónde se muestran**:
  - `ProjectStatusStrip` ("Next: …") sobre las páginas del proyecto, incluida Posts/Calendar;
    lee `overview` de `ProjectLayout`, que solo lo vuelve a pedir al cambiar de sección o con
    `reloadOverview()`.
  - `HomePage` → `UpNext` y `ProjectsList` ("Next: …"): piden su propio overview al montarse;
    no son visibles a la vez que Calendar y se refrescan al navegar.
- **Causa exacta**: `usePostsData.reload()` solo llama a `onStatusChange` (=
  `reloadOverview`) si `statesChanged(before, after)`, que compara número de Posts y
  `display_state` por id. Reprogramar un `scheduled_automatic` a otra fecha deja el mismo
  `display_state` → no se recarga el overview → el strip mantiene la fecha antigua. Afecta hoy
  también a *Edit schedule* desde Post detail.
- **Decisión (mínima)**: `statesChanged` compara también `scheduled_at` por id. Reutiliza la
  señal existente, sin store ni bus nuevo. El polling no provoca recargas extra: `scheduled_at`
  solo cambia por ediciones.

---

## R13. Foco y anuncios

Base existente: el `Modal` de `ui/Dialog.tsx` guarda `document.activeElement` al abrir y le
devuelve el foco al cerrar si sigue conectado.

| Caso | Mecanismo |
|---|---|
| Quick Reschedule → cancelar | Automático: el opener es el control → vuelve a él |
| Drop → diálogo → cancelar | Antes de abrir, Calendar enfoca el `<Link>` origen (`[data-detail-id]`); el Modal lo toma como opener y lo devuelve al cerrar |
| Éxito, el Post sigue en la semana | Tras `await onChanged()`, Calendar enfoca `[data-detail-id=<id>]` (el enlace en su nueva posición; si cambió de día, el nodo es nuevo) |
| Éxito, el Post sale de la semana | Foco al encabezado del rango (`h2`, `tabIndex={-1}`) |
| Error | El diálogo sigue abierto con el error (comportamiento existente); al cerrarlo, vuelve al opener si existe; si el opener ya no existe, al encabezado del rango |

Anuncio (FR-044): un `<p role="status" className="ap-visually-hidden">` en Calendar con
"`<título> rescheduled for <formatWhen(nueva fecha)>.`" tras el éxito. El `aria-live` del
rango no se reutiliza (anuncia cambios de semana).

---

## R14. Estilos

Reutilizar tokens de 023 (`--color-action`, `--color-action-subtle`, `--color-border`,
`--color-text-secondary`, `--status-*`, `--radius-*`, `--motion-fast`):

- control: `IconButton`/`Button` sin estilos nuevos salvo su posición en la tarjeta;
- origen arrastrado: opacidad reducida + borde discontinuo (`data-dragging`);
- destino válido: contorno discontinuo `--color-action` (`data-drop="valid"`), sólido cuando es
  el día bajo el puntero (`data-drop-over`);
- destino inválido: fondo atenuado `--color-surface-muted` + texto visible corto en el día bajo
  el puntero ("Can't move here — that time has already passed.") — distinto por forma y texto, no solo
  color; cursor `not-allowed` por `dropEffect = "none"`;
- sin animaciones nuevas; las transiciones usan `--motion-fast`, que ya es 0 con
  `prefers-reduced-motion`.

---

## R15. Tests deterministas

Backend (patrón `tests/barriers.py`: hilos + `threading.Event`, nunca `sleep`):

- `pause_before_commit(session_factory, is_claim)` detiene el claim con su `UPDATE`+`INSERT`
  ejecutados (lock de escritor tomado); `statement_reached(engine, "BEGIN IMMEDIATE")` indica
  que el PATCH ya espera el lock → liberar → el PATCH ve `publishing` → 409.
- Pausa del PATCH dentro de su transacción con un helper nuevo `pause_after_call` (monkeypatch
  de `_set_consent` o `ensure_editable`; no un predicado sobre `session.dirty`, que un
  autoflush puede vaciar), `statement_reached(engine, "UPDATE
  publications")` para saber que el claim espera → liberar → claim `not_claimed`, sin intento.
- Regresión del lost update: el PATCH pausado justo después de su lectura (gate en
  `ensure_editable` vía monkeypatch o `pause_before_commit`) mientras se lanza un tick; tras
  liberar: nunca `scheduled` con intento `running`.

Frontend: `FakeApi` (`test-fake-api.ts`) ya implementa el PATCH; drag con `fireEvent.dragStart/
dragOver/drop/dragEnd` y un `dataTransfer` falso (como `library.test.tsx`); viewport con
`setViewport` (`publish/test-publish.ts`).
