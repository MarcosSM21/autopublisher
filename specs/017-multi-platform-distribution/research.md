# Research: Distribución multiplataforma y presets de destinos

Decisiones de diseño de la Feature 017, basadas en el código actual (`backend/app/publications.py`,
`schemas.py`, `errors.py`, `frontend/src/components/PublicationCreate.tsx`,
`PublicationDetail.tsx`, `*PublishOptions.tsx`, `PublishNowDialog.tsx`).

---

## 1. Request de creación ampliado (retrocompatible)

**Decision**: ampliar `PublicationCreate` (mismo endpoint `POST /api/contents/{id}/publications`)
con campos opcionales. Se introduce un modelo base `PublicationOverrides`
(`title_override`, `description_override`, `hashtags_override`), reutilizando los tipos ya
existentes `TitleOverride`, `DescriptionOverride` y el validador de hashtags de
`PublicationUpdate`:

```text
PublicationCreate(PublicationOverrides):
  account_ids: list[int]            # sin cambios (1..50, repetidos se deduplican)
  scheduled_at: ScheduledAt | None  # sin cambios
  auto_publish_enabled: bool        # sin cambios
  title_override / description_override / hashtags_override  # comunes, opcionales (nuevo)
  targets: dict[int, PublicationOverrides] | None             # por cuenta, opcional (nuevo)
```

`PublicationOverrides` hereda de `InputModel` (`extra="forbid"`), por lo que un destino
que intente enviar opciones de plataforma (`privacy`, `mode`…) se rechaza con 422.

**Rationale**: un cliente antiguo no envía ninguno de los campos nuevos → comportamiento
idéntico. `dict[int, …]` refleja literalmente `targets[account_id]`; Pydantic convierte la
clave JSON `"12"` a `12` y, en un error, la `loc` es `("targets", "12", "title_override")`
(verificado con la versión de Pydantic del repo).

**`title_override` común**: se acepta (sale gratis del modelo base y es simétrico con
`PublicationUpdate`), pero la UI nunca lo envía (FR-002, FR-020). El backend NO rechaza un
título para plataformas que no lo usan: decidir qué plataforma consume título es lógica de
plataforma y no debe filtrarse al núcleo (Constitution III); se guarda y se ignora, como hoy
con `PATCH`.

**Alternatives considered**:
- `targets` como lista `[{account_id, …}]`: la `loc` de error sería un índice, no la cuenta;
  obliga a validar duplicados de `account_id`. Rechazado.
- Endpoint nuevo `/distributions`: prohibido por la spec y duplicaría validación. Rechazado.

---

## 2. Precedencia y semántica omitido / null / vacío

**Decision**: por cada campo `f` y cada cuenta:

1. si `targets[cuenta]` contiene `f` con valor no nulo → ese valor;
2. si no, si el nivel común contiene `f` con valor no nulo → ese valor;
3. si no → la Publication se crea con `f_override = NULL` (hereda del Content mediante
   `effective_metadata`, sin cambios).

- **Omitido** y **`null`** son equivalentes en creación: "no hay override en este nivel".
- **`""`** (descripción/título) y **`[]`** (hashtags) son overrides explícitos vacíos, como en
  `PublicationUpdate` (`_strip_keep_empty`). Un `""` en el destino prevalece sobre un valor común.
- La resolución es una función pura pequeña en `publications.py`
  (`resolve_overrides(body, account_id) -> dict`), usada al construir cada `Publication`.

**Rationale**: en creación no existe un valor previo que "borrar", así que `null` no
necesita un significado distinto de omitir. Así `Discard customization` es puramente
cliente (no se envía nada para ese destino) y no hay que modelar "volver a heredar del
Content saltándose el común".

**Alternatives considered**: `null` en el destino = "ignorar el común y heredar del Content".
Añade un caso sin demanda real en la spec. Rechazado.

---

## 3. Validación atómica antes de cualquier INSERT

**Decision**: orden de validación en `create_publications`, todo antes de `session.add_all`:

1. Pydantic: tipos, límites, `extra="forbid"`, normalización de hashtags (común y por
   destino) → 422.
2. Nuevo: toda clave de `targets` debe estar en `account_ids` → 422 con un error por clave
   (`field: "targets.<id>"`).
3. Sin cambios: proyecto activo, archivo disponible, fecha futura, `auto_publish_enabled`
   requiere fecha.
4. Sin cambios: problemas por cuenta (no encontrada / otro proyecto / inactiva / con
   Publication activa) → `_raise_account_problems`.
5. Sin cambios: comprobación de armado si `auto_publish_enabled`.
6. Construcción de las Publications con `resolve_overrides` → `add_all` → commit único;
   la carrera sigue cubierta por el índice único parcial (`_commit_or_conflict`).

**Rationale**: la atomicidad actual ya es "validar todo y un único commit"; los overrides se
validan antes en el parseo, así que nunca se llega a insertar con un override inválido.
No se añade ningún preflight remoto (FR-013).

---

## 4. Mapeo de errores a campo común / cuenta / campo de destino

Formato actual: `{"error": {"code", "message", "fields": [{"field", "message"}]}}`.
`_handle_validation_error` usa solo `loc[0]` como `field`.

**Decision**:

- **Campo común**: sin cambios → `field: "description_override"` (o `hashtags_override`,
  `title_override`).
- **Campo de un destino**: `_handle_validation_error` cambia **solo para errores cuya `loc`
  original empieza por `"body"`**: `field` se construye uniendo con `.` los segmentos **de
  texto** iniciales que siguen a `"body"` (se detiene en el primer índice entero y descarta
  el marcador `[key]` de Pydantic). Resultados: `targets.11.title_override`, `targets.11`
  (también para una clave no numérica, p. ej. `targets.x`). Para todos los modelos de body
  actuales (planos) el resultado es idéntico a hoy: `("body", "hashtags", 0)` → `hashtags`;
  `("body", "account_ids", 3)` → `account_ids`. Ningún `InputModel` existente tiene
  submodelos, así que el cambio es retrocompatible.
- **Errores de `path` y `query`**: contrato actual sin cambios, `field = loc[0]`, es decir
  `field: "path"` o `field: "query"` (p. ej. un id de ruta no numérico o los parámetros de
  los callbacks OAuth). Nunca se produce `path.content_id` ni `query.code`.
- **Clave de destino no seleccionada**: `field: "targets.11"` (generada en el endpoint con
  `field_errors`).
- **Cuenta concreta** (no encontrada, otro proyecto, inactiva, publicación activa, armado):
  se mantiene `field: "account_ids"` y el mismo mensaje, y se **añade** a cada entrada la
  clave `account_id` (entero). `fields` pasa de `list[dict[str, str]]` a
  `list[dict[str, Any]]` en `ConflictError`/`AppError`. Aditivo: los clientes que filtran
  por `field === "account_ids"` siguen funcionando.
- **`account_id` en errores 422**: `field_errors` acepta entradas `(field, message)` (las
  llamadas actuales no cambian) o `(field, message, account_id)`. Como `field_errors`
  construye errores con forma de Pydantic que el handler reconstruye, el `account_id` se
  guarda en `ctx` de cada error y `_handle_validation_error` lo copia a la entrada final de
  `fields` cuando existe. En los 409 (`ConflictError`/`AppError`) se incluye directamente en
  `fields`.

La UI mapea así: `account_id` → fila del destino; `targets.<id>.<campo>` → campo del panel
Customize de ese destino; `targets.<id>` → fila del destino; resto → campo común o
mensaje general.

**Alternatives considered**: `field: "account_ids.12"`. Rompe a clientes y tests que comparan
con `"account_ids"`. Rechazado.

---

## 5. Presets: persistencia, integridad y CRUD

**Decision**:

- Tablas `distribution_presets` y `distribution_preset_accounts` (migración `0016`), ver
  data-model.md.
- Unicidad de nombre: `UniqueConstraint(project_id, name_key)`, `name_key =
  normalize_key(name)` (mismo patrón que `projects`, NFKC + casefold). Comprobación previa
  `ensure_preset_name_available` → `ConflictError("duplicate", field="name")`; la carrera la
  cubre la restricción y el handler existente de `IntegrityError`, que ya mapea `name_key` → `name`.
- Pertenencia de cuentas al proyecto: validada en la aplicación (consulta única de
  `Account.id, project_id` para los ids enviados) → 422 `account_ids` con `account_id` por
  entrada. No se usa FK compuesta (`accounts` no tiene `UNIQUE(id, project_id)` y añadirla
  sería una migración de tabla existente sin necesidad real: las cuentas nunca cambian de proyecto).
- FKs: `distribution_preset_accounts.preset_id → distribution_presets.id ON DELETE CASCADE`,
  `distribution_preset_accounts.account_id → accounts.id ON DELETE CASCADE`,
  `distribution_presets.project_id → projects.id ON DELETE CASCADE`. `PRAGMA foreign_keys=ON`
  ya está activo (`db.py`). Hoy no existe borrado de cuentas ni de proyectos en la API; el
  CASCADE solo garantiza la semántica de la spec (un preset puede quedar vacío y seguir
  existiendo) si se añade en el futuro. Desviación consciente del patrón `RESTRICT` del
  repo: los presets son configuración desechable, no historial.
- Cuentas inactivas: se permiten en un preset (se omiten al aplicarlo, FR-037).
- Repetidos en `account_ids` del preset: se rechazan (422), FR-035.
- Edición de cuentas: `PATCH` con `account_ids` reemplaza el conjunto completo (borrar las
  filas y volver a insertarlas en la misma transacción).
- Router nuevo `app/distribution_presets.py`, registrado en `main.py`.

**Alternatives considered**: columna JSON con ids de cuenta (sin integridad referencial;
rechazado por la spec); `localStorage` (prohibido).

---

## 6. Aplicar un preset

**Decision**: lógica de cliente. Distribute ya carga cuentas del proyecto y el uso del Content;
aplicar un preset intersecta `preset.account_ids` con las cuentas seleccionables y genera el
aviso de omitidas (`inactive` / `already has active publication`). Se **añade** a la
selección actual o la **reemplaza**: reemplaza (comportamiento esperado de "aplicar"), y el
usuario puede ajustar después (US5-9). No hay endpoint de "apply".

**Rationale**: los datos necesarios ya están en el cliente; un endpoint dedicado duplicaría
la regla de "seleccionable".

---

## 7. Corrección de `taken` (estados históricos)

**Ubicación del bug**: `frontend/src/components/PublicationCreate.tsx:84-92`, que solo excluye
`cancelled`.

**Decision**: añadir en `frontend/src/types.ts`, junto a `PublicationStatus` (que ya lleva el
comentario "Keep in sync with … backend"), la constante
`HISTORY_STATUSES: readonly PublicationStatus[] = ["cancelled", "published"]` con el comentario
"Keep in sync with HISTORY_STATUSES in backend/app/publications.py", y un helper
`blocksNewPublication(status)` en `utils.ts`. Distribute lo usa para deshabilitar cuentas.

**Fuente de datos**: `GET /contents/{id}/usage` (Feature 016) ya devuelve las publicaciones
del Content con `account_id` y `status`; se usa en lugar de `listPublications(project)`
(más ligero y ya acotado al Content).

**Alternatives considered**: que el backend exponga `blocking: bool` por publicación o
cuenta. Más correcto en teoría, pero añade un campo de API para una regla de dos valores que
ya se replica por el mismo patrón "keep in sync" en `types.ts`. Rechazado por simplicidad.

---

## 8. Panel de resultado: reutilización de `publish-check`, `*PublishOptions`, `PublishNowDialog`, auto-publish

**Hallazgos** (`frontend/src/components/PublicationDetail.tsx`):

- `YouTube/Instagram/Threads/TikTokPublishOptions` reciben `{publication, onSaved}` y cargan y
  guardan sus opciones por sí mismos: **ya reutilizables** sin cambios.
- `PublishNowDialog` recibe `{publication, onCancel, onPublished}`: **reutilizable** sin cambios.
- Privado dentro de `PublicationDetail` y necesario para el panel:
  - `PublishAction` + `wasReconciled` (carga de `publish-check`, reconciliación de intentos
    inciertos, botón Publish now / Send to TikTok, apertura de `PublishNowDialog`, lista de
    problemas);
  - `AutoPublishControls` (estado, confirmación y PATCH de auto-publish);
  - la selección del componente de opciones según plataforma (`isTikTokVideo`, modo TikTok
    vía `onModeChange`);
  - el *polling* (`POLL_INTERVAL_MS` mientras `publishing`, `AUTOMATION_POLL_INTERVAL_MS`
    mientras espera al scheduler) y la sincronización de la copia local con la prop;
  - las constantes `PUBLISHABLE` y `PUBLISHING_PLATFORMS`.

**Decision — extracción pequeña** a un módulo nuevo
`frontend/src/components/PublicationControls.tsx`, que **mueve** (no copia) ese código:

| Export | Origen | Cambio |
|---|---|---|
| `useLivePublication(initial, onChanged)` | estado `publication`/`received` + `useEffect` de polling + `handleReconciled` de `PublicationDetail` | movido tal cual; devuelve `{publication, setPublication, handleReconciled}` |
| `PublicationPlatformOptions({publication, onSaved, onModeChange})` | el bloque de 4 condicionales `*PublishOptions` | movido; Telegram/X no renderizan nada |
| `PublishAction` (+ `wasReconciled`) | función privada | movido; nueva prop opcional `onCheck?: (check: PublishCheck \| null) => void`, llamada tras cada carga del check |
| `AutoPublishControls` | función privada | movido sin cambios |
| `PUBLISHABLE`, `PUBLISHING_PLATFORMS`, `POLL_INTERVAL_MS`, `isPublishable(publication)` | constantes de `PublicationDetail` | movidas; `PublicationDetail` re-exporta `POLL_INTERVAL_MS` para no tocar sus tests |

`checkVersion` (contador local que se incrementa en `onSaved` para recargar el check) y
`dialogOpen` siguen siendo estado local de cada consumidor: son dos `useState` triviales,
no lógica de negocio.

**Permanece dentro de `PublicationDetail`** (sin cambios de comportamiento ni de orden en
pantalla): título, `MediaPreview`, cabecera cuenta + estado, `TikTokInboxDelivery`,
`PublicationAttempts`, rama de cancelada + Reactivate, `ScheduleForm` (y `scheduleBlocker`,
`INBOX_SCHEDULE_NOTE`), `MetadataForm`, `MetadataSummary`, Cancel publication,
`preparationBlocker`, `run()` y `DATE_REMOVED_NOTICE`. `PublicationDetail` pasa a componer
los bloques extraídos en las mismas posiciones que hoy.

**Panel de resultado compacto** — `DistributionResult` + `DistributionResultRow` (en
`Distribute.tsx`). Cada fila usa solo los bloques extraídos:

```text
<section aria-label="YouTube @chan">
  YouTube @chan · [Unscheduled] · Ready | Needs 2                 ← cabecera
  <details open={needs}> Platform options                          ← PublicationPlatformOptions
  <PublishAction onCheck=…>  (lista de problemas + Publish now / PublishNowDialog)
  <AutoPublishControls>     solo si status === "scheduled"
</section>
```

- `useLivePublication` aporta el polling (p. ej. tras Publish now la fila pasa por
  Publishing → Published sin lógica nueva).
- Ready/Needs se deriva del `onCheck` de `PublishAction`; no hay una segunda llamada a
  `publish-check`. Si la Publication no es publicable (publishing, published,
  awaiting_user_action) la cabecera muestra solo el estado.
- No se muestran: preview del asset, metadata, intentos/historial, fecha, cancelar, inbox de
  TikTok. Para eso, "Open queue" en la cabecera del panel.

**Rationale**: reutiliza exactamente el código que hoy usa el detalle, sin duplicar polling,
reglas de auto-publish, lógica TikTok, reconciliación, llamadas API ni validaciones; el
diff en `PublicationDetail` se limita a sustituir código por imports.

**Alternatives considered**:
- Embeber `PublicationDetail` completo por fila: descartado por el usuario (panel demasiado
  largo, contrario al objetivo de reducir fricción).
- Un componente compuesto único `PublicationPublishControls` usado también por el detalle:
  obligaría a reordenar el detalle (opciones, inbox, publish, attempts y schedule están
  intercalados) y a tocar más tests. Rechazado.

---

## 9. Flujo Distribute (frontend)

**Decision**: **una única vista progresiva** (no wizard) en un componente nuevo
`Distribute.tsx` que sustituye a `PublicationCreate.tsx`:

1. **Destinations**: selector de preset + gestión de presets (desplegable "Manage presets",
   con "Save selection as preset"), casillas de cuentas activas, cuentas bloqueadas
   deshabilitadas con motivo, aviso de omitidas al aplicar.
2. **Common text**: Description/caption y Hashtags.
3. **Destinos seleccionados**: lista con **Customize** por destino (plegable); título solo
   para YouTube; marca "Customized" y **Discard customization**.
4. **When**: radio Prepare / Schedule + fecha.
5. Botón **Create N publications**.
6. Tras crear: el formulario se sustituye por el **panel de resultado** (botón "Distribute
   again" para volver al formulario vacío, y "Open queue").

`AutoPublishConsent` (hoy exportado desde `PublicationCreate.tsx` y usado por `ScheduleForm`)
se mueve a su propio archivo `AutoPublishConsent.tsx` (lo usan `ScheduleForm` en
`PublicationDetail.tsx` y `TextPublicationCreate.tsx`); Distribute no ofrece armado en la
creación (se hace por fila en el panel).

**Títulos de plataformas**: la regla "qué plataforma muestra título en Customize" se
expresa como una constante de UI `TITLE_PLATFORMS: Platform[] = ["youtube"]`. No es una regla
de validación de publisher (el backend acepta título en cualquier caso); es una decisión de
presentación de la spec.

---

## 10. Dirty state de Common text y Customize

**Decision**: estado explícito por campo `{ edited: boolean; text: string }`, mismo patrón
que `FieldState {custom, text}` de `MetadataForm`:

- se marca `edited = true` en el primer `onChange` del campo; nunca se deduce comparando con
  el Content;
- al enviar: `edited === false` → el campo no se incluye; `edited` y texto vacío → `""` (o `[]`
  para hashtags); `edited` → valor exacto (hashtags con el `parseHashtags` existente);
- Common text ofrece "Reset to content value" por campo (vuelve a `edited = false` y al texto
  del Content);
- Customize: `customizations: Record<accountId, Partial<Record<Field, FieldState>>>`. Un
  campo no editado muestra el valor heredado (común editado o Content) en vivo.
  **Discard customization** borra la entrada del destino. Desmarcar un destino descarta su
  personalización (no se envía, US2-5).
- El `targets` enviado contiene solo destinos con algún campo `edited`.

---

## 11. Testing (deliberadamente pequeño)

**Backend** — ampliar `tests/test_publications_create.py`:

- 1 test parametrizado de precedencia (sin overrides / común / destino / destino sobre común,
  incluido un `""` explícito);
- 1 test de atomicidad: override inválido en un destino → 422 con
  `field == "targets.<id>.title_override"` y cero Publications;
- 1 test: clave de `targets` no seleccionada → 422 `targets.<id>`, cero Publications;
- sin test nuevo para `account_id`: actualizar las 6 aserciones exactas de `fields` ya
  existentes (5 en `test_publications_create.py`, 1 en `test_publish_arming.py`).

Nuevo `tests/test_distribution_presets.py`: 1 test de ciclo CRUD (create/list/update/delete),
1 de nombre duplicado (case-insensitive), 1 de cuenta de otro proyecto rechazada.
`tests/test_migrations.py` se ejecuta de forma dirigida (la migración nueva debe coincidir
con los modelos).

**Frontend** — nuevo `Distribute.test.tsx` (sustituye a `PublicationCreate.test.tsx`), ~4
tests de comportamiento con `test-fake-api.ts` ampliado:

1. selección: cuenta con `PUBLISHED` seleccionable, `SCHEDULED` deshabilitada con motivo;
2. preset: aplicar preselecciona y avisa "N destinations skipped"; guardar selección como preset;
3. common + Customize + Schedule: el cuerpo enviado contiene solo campos editados, `""`
   explícito y `targets` del destino personalizado; Discard elimina el destino de `targets`;
4. panel de resultado compacto: una fila Ready y otra "Needs" con sus opciones de
   plataforma; sin preview ni intentos; Publish now abre el diálogo de esa fila.

`PublicationDetail.test.tsx` se ejecuta de forma dirigida (sin tests nuevos): sus tests
existentes de Publish now, publish-check, auto-publish, opciones y TikTok ya cubren los
bloques extraídos en su consumidor original. El test 4 de `Distribute.test.tsx` cubre su uso
en el panel.
Sin pruebas de publishers ni scheduler; sin matrices plataforma × estado.
