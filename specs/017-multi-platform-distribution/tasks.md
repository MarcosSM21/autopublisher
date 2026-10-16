---

description: "Task list for Feature 017 — Multi-platform Distribution & Presets"
---

# Tasks: Distribución multiplataforma y presets de destinos

**Input**: Design documents from `/specs/017-multi-platform-distribution/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md)

**Tests**: pedidos explícitamente por la spec (sección Testing), en un conjunto **mínimo**
que protege contratos, no combinaciones. Sin tests de publishers, scheduler, attempts,
retries ni subida de medios (no cambian). Sin suites completas en local: solo la CI del PR.

**Organization**: por historia de usuario. US1 (Distribute con texto común), US2 (Customize)
y US4 (bug `taken`) comparten el mismo formulario y se implementan juntas en la fase core.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivos distintos, sin dependencias pendientes)
- **[Story]**: US1–US5 según spec.md
- Rutas relativas a la raíz del repositorio (`backend/`, `frontend/`)

---

## Phase 1: Foundational (contratos compartidos)

**Purpose**: request ampliado, mapeo de errores y tipos de frontend que necesitan todas las
historias. No incluye la migración de presets: no bloquea al core y vive en la fase US5.

- [X] T001 [P] En `backend/app/schemas.py`: crear `PublicationOverrides(InputModel)` con `title_override: TitleOverride = None`, `description_override: DescriptionOverride = None`, `hashtags_override: list[str] | None = None`; mover la normalización de hashtags de `PublicationUpdate` a una función compartida usada por ambos validadores; hacer que `PublicationCreate` herede de `PublicationOverrides` y añadir `targets: dict[int, PublicationOverrides] | None = None` (research.md §1–§2). `PublicationUpdate` no cambia de contrato.
- [X] T002 [P] En `backend/app/errors.py`: en `_handle_validation_error`, **solo para errores cuya `loc` original empieza por `"body"`**, construir `field` uniendo con `.` los segmentos `str` iniciales tras `"body"` (cortar en el primer `int`, descartar `"[key]"`), de modo que los modelos planos actuales den el mismo `field` y los destinos den `targets.12.title_override` / `targets.x`; los errores de `path`/`query` (p. ej. callbacks OAuth, ids en la ruta) conservan exactamente el comportamiento actual (`field = loc[0]`); tipar `fields` como `list[dict[str, Any]]` en `ConflictError`, `AppError` y `error_response`; permitir que `field_errors` reciba entradas `(field, message)` o `(field, message, account_id)`, guardando `account_id` en `ctx` y copiándolo en el handler al `fields` de la respuesta; las llamadas existentes de 2 elementos no cambian (contracts/api.md, research.md §4).
- [X] T003 [P] En `frontend/src/types.ts`: añadir `account_id?: number` a `FieldError`; añadir `HISTORY_STATUSES: readonly PublicationStatus[] = ["cancelled", "published"]` junto a `PublicationStatus` con el comentario "Keep in sync with HISTORY_STATUSES in backend/app/publications.py". En `frontend/src/utils.ts`: añadir `blocksNewPublication(status: PublicationStatus): boolean` (research.md §7).
- [X] T004 [P] En `frontend/src/api.ts`: añadir `PublicationOverrides` (`title_override?`, `description_override?`, `hashtags_override?`, cada uno `| null`) y ampliar la interfaz `PublicationCreate` con esos campos y `targets?: Record<number, PublicationOverrides>` (contracts/api.md).
- [X] T005 En `frontend/src/test-fake-api.ts`: `createPublications` aplica la precedencia destino > común > Content al guardar overrides, rechaza con 422 (`targets.<id>`) claves de `targets` no seleccionadas, y devuelve `account_id` en los errores por cuenta (inactiva / publicación activa); el bloqueo de cuenta importa `HISTORY_STATUSES` de `types.ts` en lugar de redefinir estados (depende de T003, T004).

**Checkpoint**: contratos listos; ninguna conducta visible cambia todavía.

---

## Phase 2: Distribute core — US1 (P1), US2 (P1), US4 (P1) 🎯 MVP

**Goal**: desde un asset, **Distribute** crea en una sola llamada atómica Publications para
varios destinos con texto común y personalización por destino; `PUBLISHED`/`CANCELLED` no
bloquean la selección.

**Independent Test**: quickstart.md A, B, C y E.

### Backend

- [X] T006 [US1] En `backend/app/publications.py` (`create_publications`): tras deduplicar `account_ids`, rechazar con `field_errors` una entrada `targets.<id>` ("This destination is not selected.") por cada clave de `body.targets` fuera de la selección, antes de cualquier otra comprobación de cuentas; añadir la función pura `resolve_overrides(body, account_id) -> dict[str, Any]` (por campo: destino no nulo > común no nulo > `None`) y aplicarla al construir cada `Publication(...)`. Sin cambios en el commit único ni en `_commit_or_conflict` (research.md §2–§3).
- [X] T007 [US1] En `backend/app/publications.py`: cambiar `_raise_account_problems` para recibir `(severity, account_id, message)` y añadir `account_id` a cada entrada de `fields` (manteniendo `field: "account_ids"` y los mensajes actuales); hacer lo mismo en las entradas de problemas de armado de `create_publications`. `_raise_account_problems` también lo usa `create_text_publications`: el cambio es aditivo y se acepta allí igual (depende de T002).
- [X] T008 [US1] En `backend/tests/test_publications_create.py` añadir exactamente: (a) **un** test parametrizado de precedencia con filas: sin overrides; común (descripción + hashtags); destino (título + descripción); destino sobre común; vacío explícito (`""` en destino sobre común no vacío, `[]` común) — comprobando overrides guardados y metadata efectiva del Content intacta; (b) **un** test de atomicidad: un destino con `title_override` > 200 caracteres → 422 con `field == "targets.<id>.title_override"` y cero Publications; (c) **un** test de clave de `targets` no seleccionada → 422 `targets.<id>`, cero Publications; (d) **sin test nuevo**: actualizar las aserciones exactas de `fields` que ya existen para que incluyan `account_id` — 5 en `backend/tests/test_publications_create.py` (cuenta de otro proyecto, no encontrada, inactiva, duplicada…) y 1 en `backend/tests/test_publish_arming.py` (línea ~125); esa actualización es la cobertura de `account_id` (depende de T001, T002, T006, T007).
- [X] T009 [US1] Ejecutar solo `cd backend && uv run pytest tests/test_publications_create.py tests/test_publish_arming.py tests/test_text_publications.py` (los dos últimos por el cambio compartido de `account_id`) y corregir hasta verde.

### Frontend

- [X] T010 [P] [US1] Mover `AutoPublishConsent` sin cambios de `frontend/src/components/PublicationCreate.tsx` a `frontend/src/components/AutoPublishConsent.tsx` y actualizar sus imports en `frontend/src/components/PublicationDetail.tsx` y `frontend/src/components/TextPublicationCreate.tsx`.
- [X] T011 [US1] Crear `frontend/src/components/Distribute.tsx` (sustituye a `PublicationCreate.tsx`): carga en paralelo `listAccounts(project.id)` y `getContentUsage(content.id)`; mantiene los mensajes actuales de proyecto inactivo / archivo no disponible / sin cuentas activas; sección **Destinations** con casillas de cuentas activas, deshabilitando con "Already has an active publication" las que tengan una publicación del Content con `blocksNewPublication(status)` (corrige el bug `taken`, US4); sección **When** con radio Prepare (por defecto) / Schedule + `datetime-local`; botón "Create N publications" deshabilitado sin destinos o enviando, con la indicación "Choose at least one destination." cuando no hay ninguno (US1-6); envío con una única llamada `createPublications` sin `auto_publish_enabled` (contracts/ui.md).
- [X] T012 [US2] En `frontend/src/components/Distribute.tsx`: sección **Common text** (Description / caption, Hashtags) prellenada con el Content y estado `{edited, text}` por campo con "Reset to content value"; lista de destinos seleccionados con **Customize** plegable por destino (título solo si `platform ∈ TITLE_PLATFORMS = ["youtube"]`; campos no editados muestran en vivo el valor heredado), marca "Customized" y **Discard customization**; desmarcar un destino descarta su personalización. Construcción del cuerpo: solo campos `edited` (vacío → `""`/`[]`, hashtags con `parseHashtags`), `targets` solo con destinos con algún campo editado (research.md §10).
- [X] T013 [US1] En `frontend/src/components/Distribute.tsx`: mapeo de errores según contracts/ui.md — `fields[].account_id` → fila del destino; `targets.<id>.<campo>_override` → campo del Customize (desplegándolo); `targets.<id>` → fila; campos comunes → bajo el campo; `scheduled_at` → bajo la fecha; resto → `FormError`. Conservar todo lo introducido tras el error.
- [X] T014 [US1] En `frontend/src/components/ContentDetail.tsx`: el botón pasa a "Distribute" y renderiza `<Distribute>`; en `frontend/src/components/PublicationQueue.tsx` el texto vacío pasa a "No publications yet. Open a content and choose Distribute." y se actualiza su aserción en `frontend/src/components/PublicationQueue.test.tsx`; eliminar `frontend/src/components/PublicationCreate.tsx` y `frontend/src/components/PublicationCreate.test.tsx` (depende de T010–T013).
- [X] T015 [US1] Crear `frontend/src/components/Distribute.test.tsx` con tres tests de flujo: (1) selección + common text + Customize + creación: editar descripción común, personalizar título de YouTube, Discard en otro destino, comprobar el cuerpo enviado (solo campos editados, `targets` solo del destino personalizado, sin título común); (2) Prepare/Schedule + errores: Schedule envía `scheduled_at` común; un error con `account_id` se muestra en la fila del destino y uno `targets.<id>.title_override` bajo el campo, conservando lo introducido; (3) regresión `PUBLISHED` seleccionable y `scheduled` deshabilitada con motivo.
- [X] T016 [US1] Ejecutar solo `cd frontend && npx vitest run src/components/Distribute.test.tsx src/components/ContentDetail.test.tsx src/components/PublicationQueue.test.tsx src/components/TextPublicationCreate.test.tsx` y corregir hasta verde.

**Checkpoint**: Distribute crea Publications con texto común y personalizado; tras crear se
muestra temporalmente el resumen de creadas (el panel llega en la fase 3).

---

## Phase 3: US3 (P1) — Panel de resultado compacto

**Goal**: tras crear, una fila compacta por Publication con estado, Ready/Needs, opciones de
plataforma, Publish now y auto-publish, reutilizando los mismos bloques que `PublicationDetail`.

**Independent Test**: quickstart.md D.

- [X] T017 [US3] Crear `frontend/src/components/PublicationControls.tsx` **moviendo** (no copiando) desde `frontend/src/components/PublicationDetail.tsx`: `useLivePublication(initial, onChanged)` (estado `publication`/`received`, `useEffect` de polling con `POLL_INTERVAL_MS`/`AUTOMATION_POLL_INTERVAL_MS` y `handleReconciled`; devuelve `{publication, setPublication, handleReconciled}`), `PublicationPlatformOptions({publication, onSaved, onModeChange})` (los cuatro condicionales `*PublishOptions`, con `isTikTokVideo`), `PublishAction` + `wasReconciled` con nueva prop opcional `onCheck?: (check: PublishCheck | null) => void` llamada tras cada carga, `AutoPublishControls`, las constantes `PUBLISHABLE`, `PUBLISHING_PLATFORMS`, `POLL_INTERVAL_MS`, y los helpers `isPublishable(publication)` e `isTikTokVideo(publication)` (este último sustituye al cálculo inline de `PublicationDetail`, para que el panel no replique lógica TikTok). `onCheck` NO entra en las dependencias del `useEffect` de `PublishAction` (guardarlo en un ref): el check se sigue cargando solo cuando cambian `publication` o `checkVersion`, sin bucles ni llamadas extra (research.md §8).
- [X] T018 [US3] En `frontend/src/components/PublicationDetail.tsx`: sustituir el código movido por imports de `PublicationControls.tsx`, colocando cada bloque en la misma posición que hoy; re-exportar `POLL_INTERVAL_MS`. Todo lo demás (preview, cabecera, `TikTokInboxDelivery`, `PublicationAttempts`, cancelada/Reactivate, `ScheduleForm`, `MetadataForm`, `MetadataSummary`, Cancel) sin cambios (depende de T017).
- [X] T019 [US3] Regresión dirigida de la extracción, sin tests nuevos: `cd frontend && npx vitest run src/components/PublicationDetail.test.tsx src/components/YouTubePublishOptions.test.tsx src/components/TelegramConnectionPanel.test.tsx`; corregir hasta verde.
- [X] T020 [US3] En `frontend/src/components/Distribute.tsx`: `DistributionResult` (sustituye al formulario tras crear; "Created N publications", "Distribute again" que vuelve al formulario vacío, "Open queue") y `DistributionResultRow` por Publication como `section` con `aria-label` plataforma + cuenta: cabecera con badge de estado y **Ready** / **Needs N** derivado de `onCheck` (solo estado si no es publicable), `<details>` "Platform options" con `PublicationPlatformOptions` (abierto si hay pendientes; `onSaved` incrementa un `checkVersion` local; `onModeChange` guarda el modo TikTok en estado local), `PublishAction` (con `dialogOpen` local, `PublishNowDialog` existente y `sendToTikTok = isTikTokVideo(publication) && mode === "INBOX_UPLOAD"`, igual que el detalle) y `AutoPublishControls` solo si `status === "scheduled"`; `useLivePublication` con `onChanged` que recarga vía `listPublications(project.id)` filtrando los ids creados. Sin preview, metadata, intentos ni Publish all (contracts/ui.md) (depende de T017).
- [X] T021 [US3] En `frontend/src/components/Distribute.test.tsx` añadir un test (4): tras crear, una fila Ready y otra "Needs N" con sus opciones de plataforma visibles, sin vista previa ni intentos, y Publish now abre el diálogo solo para esa fila. Ampliar `frontend/src/test-fake-api.ts` solo si falta algún dato de `publish-check` para ese escenario.
- [X] T022 [US3] Ejecutar solo `cd frontend && npx vitest run src/components/Distribute.test.tsx` y corregir hasta verde.

**Checkpoint (lógico, sin suites amplias)**: revisar el flujo completo Distribute → panel
(quickstart.md A–E) antes de empezar presets. Opcionalmente arrancar backend y frontend en
segundo plano para revisión manual.

---

## Phase 4: US5 (P2) — Presets de destinos

**Goal**: guardar, aplicar, editar y eliminar conjuntos de destinos por proyecto.

**Independent Test**: quickstart.md F.

### Backend

- [X] T023 [P] [US5] En `backend/app/models.py`: añadir `DistributionPreset` (`distribution_presets`: `id`, `project_id` FK `projects.id` ON DELETE CASCADE, `name` String(100), `name_key`, `created_at`, `updated_at` con `UTCDateTime`, `UniqueConstraint("project_id", "name_key")`) y `DistributionPresetAccount` (`distribution_preset_accounts`: PK compuesta `preset_id` FK CASCADE + `account_id` FK `accounts.id` CASCADE, índice en `account_id`) (data-model.md).
- [X] T024 [US5] Crear `backend/migrations/versions/0016_create_distribution_presets.py` (revisa `0015`) que cree ambas tablas con los mismos nombres de constraints que generan los modelos (`op.f(...)`, como `0014`) y un `downgrade` que las elimine (depende de T023).
- [X] T025 [P] [US5] En `backend/app/schemas.py`: `DistributionPresetCreate(InputModel)` (`name: ProjectName`, `account_ids: list[int]` 1..50 con validador que rechaza repetidos), `DistributionPresetUpdate(UpdateModel)` (ambos opcionales) y `DistributionPresetRead` (`id`, `project_id`, `name`, `account_ids` ordenados, `created_at`, `updated_at`) (contracts/api.md).
- [X] T026 [US5] Crear `backend/app/distribution_presets.py` con `get_preset_or_404`, `ensure_preset_name_available` (patrón de `projects.py`, `ConflictError("duplicate", field="name")`), `_validate_accounts` (una consulta; cuentas inexistentes o de otro proyecto → `field_errors` en `account_ids` con `account_id`) y los endpoints `GET`/`POST /api/projects/{project_id}/distribution-presets`, `PATCH`/`DELETE /api/distribution-presets/{preset_id}` (PATCH con `account_ids` reemplaza el conjunto en la misma transacción); registrar el router en `backend/app/main.py` (depende de T023, T025).
- [X] T027 [US5] Crear `backend/tests/test_distribution_presets.py` con tres tests: (1) ciclo CRUD create → list → patch (nombre + cuentas) → delete, comprobando que cuentas y Publications no cambian; (2) nombre duplicado sin distinguir mayúsculas → 409 `duplicate` en `name`; (3) cuenta de otro proyecto → 422 con `account_id`, sin escritura. Revisar `backend/tests/test_migrations.py` y añadir las tablas nuevas si enumera las esperadas (depende de T024, T026).
- [X] T028 [US5] Ejecutar solo `cd backend && uv run pytest tests/test_distribution_presets.py tests/test_migrations.py` y corregir hasta verde.

### Frontend

- [X] T029 [P] [US5] En `frontend/src/types.ts` añadir `DistributionPreset`; en `frontend/src/api.ts` añadir `listDistributionPresets`, `createDistributionPreset`, `updateDistributionPreset`, `deleteDistributionPreset`; en `frontend/src/test-fake-api.ts` implementar presets en memoria con nombre único case-insensitive por proyecto.
- [X] T030 [US5] En `frontend/src/components/Distribute.tsx`: cargar presets con el resto de datos; selector "Choose a preset" que **reemplaza** la selección por las cuentas seleccionables del preset y muestra el aviso "N destinations skipped" con motivo por cuenta (`inactive` / `already has an active publication`), o el aviso vacío si queda en 0; aplicar nunca modifica el preset (depende de T029).
- [X] T031 [US5] En `frontend/src/components/Distribute.tsx`: plegable "Manage presets" con lista de presets y acciones Rename, Edit destinations (usa la selección actual), Delete, y "Save selection as preset" (nombre + cuentas marcadas), mostrando errores de nombre duplicado o de cuenta bajo el campo (depende de T029).
- [X] T032 [US5] En `frontend/src/components/Distribute.test.tsx` añadir un test (5) de preset: guardar la selección como preset, aplicarlo sobre un Content donde una cuenta está inactiva y otra tiene publicación activa → solo se seleccionan las válidas, aviso "2 destinations skipped" con motivos, y el preset sigue con sus cuentas; ejecutar solo `cd frontend && npx vitest run src/components/Distribute.test.tsx`.

**Checkpoint**: US1–US5 completas.

---

## Phase 5: Polish & cierre

- [X] T033 [P] Actualizar `README.md`: flujo Distribute (texto común, Customize, Prepare/Schedule, panel de resultado), campos nuevos de `POST /api/contents/{id}/publications` (`*_override` comunes y `targets`), endpoints de presets y la regla "published/cancelled no bloquean".
- [X] T034 Checks estáticos backend, una sola vez: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .`.
- [X] T035 Checks estáticos frontend, una sola vez: `cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build`.
- [X] T036 `git diff --check` y revisión de seguridad del diff (sin secretos, sin datos privados; validación de pertenencia de cuentas al proyecto en presets y en `targets`).
- [X] T037 Validación manual opcional según `quickstart.md` (servidores en segundo plano); marcar tareas completadas y preparar el resumen de cierre. Sin pytest ni `npm test` completos en local: la suite completa corre en la CI del PR.

---

## Dependencies & Execution Order

```text
Phase 1 (T001–T005)
   └─► Phase 2 core: backend T006→T007→T008→T009 ‖ frontend T010→T011→T012→T013→T014→T015→T016
          └─► Phase 3 panel: T017→T018→T019 ; T017→T020→T021→T022
                 └─► checkpoint lógico
                        └─► Phase 4 presets: backend T023→T024, T025 → T026→T027→T028
                                             frontend T029→T030, T031→T032
                               └─► Phase 5 (T033–T037)
```

- El backend de presets (T023–T028) no depende de las fases 2–3 y puede adelantarse en
  paralelo si conviene; su frontend (T030–T032) sí depende de `Distribute.tsx`.
- T017/T018 (extracción) pueden hacerse en paralelo con el backend core porque tocan solo
  `PublicationControls.tsx`/`PublicationDetail.tsx`.

## Parallel Opportunities

- Fase 1: T001, T002, T003, T004 en paralelo (archivos distintos).
- Fase 2: backend (T006–T009) en paralelo con frontend (T010–T016); T010 en paralelo con T011.
- Fase 3: T017–T019 en paralelo con el backend core.
- Fase 4: T023 y T025 en paralelo; T029 en paralelo con todo el backend de presets.
- Fase 5: T033 en paralelo con T034/T035.

## Implementation Strategy

1. **MVP**: Fases 1–2 → Distribute con texto común, Customize y corrección de `taken`.
2. **Incremento 2**: Fase 3 → panel compacto (completa la experiencia P1).
3. **Incremento 3**: Fase 4 → presets (P2).
4. **Cierre**: Fase 5, checks estáticos una sola vez, PR; la CI ejecuta las suites completas.
   Si la CI falla: corregir, ejecutar solo el test/check que falló, push.

## Testing Summary

| Área | Tests nuevos | Archivo |
|---|---|---|
| Creación (backend) | 1 parametrizado (5 filas) + atomicidad + target no seleccionado; `account_id` cubierto actualizando 6 aserciones exactas existentes | `test_publications_create.py`, `test_publish_arming.py` |
| Presets (backend) | 3 (CRUD, duplicado, otro proyecto) | `test_distribution_presets.py` |
| Distribute (frontend) | 5 tests de flujo | `Distribute.test.tsx` |
| Extracción `PublicationControls` | 0 nuevos; regresión dirigida de los existentes | `PublicationDetail.test.tsx` y relacionados |

No se planifican tests de publishers, scheduler, attempts, retries ni subida de medios.
