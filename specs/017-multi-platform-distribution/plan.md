# Implementation Plan: Distribución multiplataforma y presets de destinos

**Branch**: `017-multi-platform-distribution` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/017-multi-platform-distribution/spec.md`

## Summary

Convertir **Prepare publications** en **Distribute**: desde un asset, seleccionar destinos
(o aplicar un preset), editar un texto común, personalizar título/descripción/hashtags por
destino, elegir Prepare o Schedule y crear todas las Publications en una única llamada
atómica; después, un panel de resultado compacto con una fila por Publication (estado,
Ready/Needs, opciones de plataforma, Publish now, auto-publish) construida con bloques
extraídos de `PublicationDetail` y compartidos con él.
Añadir presets de destinos por proyecto y corregir el bug `taken` (`PUBLISHED` no bloquea).

Enfoque técnico (research.md):

- **Creación** (§1–§4): `PublicationCreate` hereda de un nuevo `PublicationOverrides` y añade
  `targets: dict[int, PublicationOverrides] | None`. Precedencia destino > común > Content;
  omitido ≡ `null` = sin override en ese nivel; `""`/`[]` = vacío explícito. Validación
  completa antes de cualquier INSERT y commit único (sin cambios en el mecanismo actual).
  Errores: solo para errores del body, paths completos (`targets.11.title_override`,
  `targets.11`, `targets.x`) uniendo los segmentos de texto de `loc` en el handler; los
  errores de `path`/`query` mantienen `field: "path"`/`"query"` (nunca `path.content_id` ni
  `query.code`); `targets.<id>` para claves no seleccionadas; y `account_id` añadido a las
  entradas `account_ids` (en los 422 viaja en `ctx` y el handler lo copia a `fields`; en los
  409 va directamente en `fields`).
- **Presets** (§5–§6): tablas `distribution_presets` (`UNIQUE(project_id, name_key)`) y
  `distribution_preset_accounts` (PK compuesta, FKs CASCADE), migración `0016`, router
  `distribution_presets.py` con list/create/patch/delete. Aplicar un preset es lógica de cliente.
- **`taken`** (§7): `HISTORY_STATUSES` en `types.ts` (patrón "keep in sync" ya existente) +
  datos de `GET /contents/{id}/usage`.
- **Panel de resultado** (§8): extracción pequeña de `PublicationDetail` a
  `PublicationControls.tsx` (`useLivePublication`, `PublicationPlatformOptions`,
  `PublishAction` con `onCheck` opcional, `AutoPublishControls`, constantes). El detalle y la
  fila compacta del panel usan los mismos bloques. Sin copiar lógica.
- **Frontend** (§9–§10): `Distribute.tsx` como vista única progresiva que sustituye a
  `PublicationCreate.tsx`; dirty state explícito por campo.

## Technical Context

**Language/Version**: Python ≥3.12 (backend), TypeScript ~6.0 (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic; React 19, Vite 8

**Storage**: SQLite local (2 tablas nuevas); sin cambios en el sistema de archivos

**Testing**: pytest (backend, `TestClient`); Vitest + Testing Library con `test-fake-api.ts` (frontend)

**Target Platform**: aplicación web local de un único usuario (Linux)

**Project Type**: web application (backend + frontend)

**Performance Goals**: interacción local; creación de ≤50 Publications en una petición (límite actual)

**Constraints**: retrocompatibilidad del request de creación; atomicidad todo-o-nada; sin
cambios en scheduler/publishers; sin preflight remoto en la creación

**Scale/Scope**: decenas de cuentas por proyecto, pocos presets; 1 endpoint ampliado,
4 endpoints nuevos, 1 componente nuevo, 1 módulo extraído de un componente existente

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Estado |
|---|---|---|
| I. Simplicidad y alcance | Sin entidad `Distribution`, sin endpoint paralelo, sin wizard; panel compacto con bloques movidos (no copiados) de `PublicationDetail`, sin refactor general; aplicar preset en cliente. Fuera de alcance de la spec respetado. | ✅ |
| II. Spec-Driven | Spec con aclaraciones (sesión 2026-10-16); el plan no amplía alcance. | ✅ |
| III. Arquitectura modular | Ninguna regla de plataforma entra en el núcleo: el backend acepta `title_override` para cualquier cuenta; la regla "título solo en YouTube" es presentación (`TITLE_PLATFORMS` en UI). Publishers y scheduler sin cambios. | ✅ |
| IV. Seguridad | Sin secretos ni datos nuevos sensibles; presets solo contienen ids de cuenta y nombre. | ✅ |
| V. Calidad | Tests dirigidos pequeños (backend + frontend); atomicidad cubierta; regresión del bug `taken`; ninguna pérdida silenciosa (rechazo total con errores por destino). | ✅ |
| VI. Git y trazabilidad | Commits pequeños por bloque; docs (README/API) actualizadas si describen la creación de publicaciones. | ✅ |
| Arquitectura base | FastAPI + SQLite + React; sin dependencias nuevas. | ✅ |

**Post-design re-check**: ✅ sin violaciones. Única desviación de patrón (no de principio):
FKs `ON DELETE CASCADE` en tablas de presets frente al `RESTRICT` habitual; justificada en
research.md §5 (configuración desechable, no historial) y exigida por la spec (un preset
puede quedar vacío).

## Project Structure

### Documentation (this feature)

```text
specs/017-multi-platform-distribution/
├── plan.md              # Este archivo
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── api.md           # Phase 1 (creación ampliada + presets)
│   └── ui.md            # Phase 1 (Distribute + panel de resultado)
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, no creado aquí)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── schemas.py               # PublicationOverrides; PublicationCreate ampliado;
│   │                            # DistributionPresetCreate/Update/Read
│   ├── publications.py          # resolve_overrides(); validación de claves de targets;
│   │                            # account_id en errores por cuenta
│   ├── errors.py                # body: field = segmentos de texto de loc unidos con ".";
│   │                            # path/query sin cambios; account_id vía ctx; fields: dict[str, Any]
│   ├── models.py                # DistributionPreset, DistributionPresetAccount
│   ├── distribution_presets.py  # NUEVO: router CRUD de presets
│   └── main.py                  # include_router(distribution_presets.router)
├── migrations/versions/
│   └── 0016_create_distribution_presets.py   # NUEVO
└── tests/
    ├── test_publications_create.py           # + precedencia, atomicidad, target no seleccionado
    ├── test_distribution_presets.py          # NUEVO: CRUD, duplicado, otro proyecto
    └── test_migrations.py                    # ajuste de tablas esperadas si las enumera

frontend/src/
├── api.ts                       # PublicationCreateInput ampliado; FieldError.account_id?;
│                                # list/create/update/deleteDistributionPreset
├── types.ts                     # HISTORY_STATUSES; DistributionPreset
├── utils.ts                     # blocksNewPublication(status)
├── test-fake-api.ts             # overrides en createPublications; presets
└── components/
    ├── ContentDetail.tsx        # botón "Distribute" → <Distribute>
    ├── Distribute.tsx           # NUEVO (sustituye a PublicationCreate.tsx); incluye
    │                            # DistributionResult / DistributionResultRow
    ├── Distribute.test.tsx      # NUEVO (sustituye a PublicationCreate.test.tsx)
    ├── PublicationControls.tsx  # NUEVO: bloques movidos desde PublicationDetail
    ├── AutoPublishConsent.tsx   # NUEVO: movido desde PublicationCreate.tsx (sin cambios)
    ├── PublicationDetail.tsx    # importa los bloques extraídos y AutoPublishConsent
    ├── TextPublicationCreate.tsx # solo cambia el import de AutoPublishConsent
    ├── PublicationQueue.tsx     # texto vacío "…choose Distribute."
    └── PublicationCreate.tsx    # ELIMINADO (su lógica pasa a Distribute.tsx)
```

**Structure Decision**: web application existente (`backend/` + `frontend/`). Un router
nuevo para presets siguiendo `projects.py`/`accounts.py`; la creación sigue en
`publications.py`. Un componente nuevo de UI (`Distribute`) y un módulo extraído
(`PublicationControls`) compartido por `PublicationDetail` y el panel de resultado.

## Design Notes

### Backend — creación

1. `schemas.py`: `PublicationOverrides(InputModel)` con `title_override: TitleOverride = None`,
   `description_override: DescriptionOverride = None`, `hashtags_override: list[str] | None =
   None` + el validador de normalización de hashtags (movido desde `PublicationUpdate` a una
   función compartida). `PublicationCreate(PublicationOverrides)` añade `targets: dict[int,
   PublicationOverrides] | None = None`. `PublicationUpdate` no cambia de contrato.
2. `publications.py`:
   - tras deduplicar `account_ids`, si `targets` tiene claves fuera de la selección →
     `field_errors([(f"targets.{id}", "This destination is not selected.")])`;
   - `resolve_overrides(body, account_id) -> dict[str, Any]` (función pura) aplicada al
     construir cada `Publication(...)`;
   - `_raise_account_problems` recibe `(severity, account_id, message)` y añade `account_id`
     a cada entrada; igual en los problemas de armado.
3. `errors.py`: en `_handle_validation_error`, solo para errores cuya `loc` empieza por
   `"body"`, `field = ".".join(segmentos str iniciales tras "body", hasta el primer índice,
   sin "[key]")` → `targets.11.title_override`, `targets.11`, `targets.x`; los errores de
   `path`/`query` conservan `field = loc[0]` (`"path"`/`"query"`, nunca `path.content_id` ni
   `query.code`). `field_errors` admite `(field, message)` o `(field, message, account_id)`:
   el `account_id` viaja en `ctx` y el handler lo copia al objeto final de `fields`; en los
   409 (`ConflictError`/`AppError`) va directamente en `fields`. Tipos de `fields` a
   `list[dict[str, Any]]`.

### Backend — presets

- Modelos y migración según data-model.md; `name` reutiliza el tipo `ProjectName` (recortado,
  1..100) o uno equivalente.
- `distribution_presets.py`: `get_preset_or_404`, `ensure_preset_name_available`,
  `_validate_accounts(session, project_id, account_ids)` (una consulta), y los 4 endpoints.
  Orden de presets por `name_key`; `account_ids` de lectura ordenados.

### Frontend

- `Distribute.tsx` carga en paralelo: `listAccounts(project)`, `getContentUsage(content)`,
  `listDistributionPresets(project)`. Estado según data-model.md. Envío con
  `createPublications(content.id, body)` construyendo solo campos `edited`.
- `PublicationControls.tsx` (extracción pequeña, research.md §8): mueve desde
  `PublicationDetail` `useLivePublication` (polling + sincronización + reconciliación),
  `PublicationPlatformOptions` (selección de `*PublishOptions` y modo TikTok),
  `PublishAction` + `wasReconciled` (con `onCheck?` nuevo), `AutoPublishControls` y las
  constantes `PUBLISHABLE`, `PUBLISHING_PLATFORMS`, `POLL_INTERVAL_MS` (re-exportada por
  `PublicationDetail`). `PublicationDetail` los importa y los coloca donde están hoy; el
  resto del detalle (preview, inbox TikTok, intentos, fecha, metadata, cancelar/reactivar)
  no cambia.
- Panel de resultado: `DistributionResult` (cabecera "Created N publications", "Distribute
  again", "Open queue") y `DistributionResultRow` por Publication: plataforma + cuenta,
  estado, Ready/Needs N (desde `onCheck`), `<details>` "Platform options" con
  `PublicationPlatformOptions` (abierto si hay pendientes), `PublishAction` y
  `AutoPublishControls` si `status === "scheduled"`. Sin preview, metadata, intentos ni
  historial. `onChanged` recarga con `listPublications(project)` filtrando los ids creados.

### Testing (resumen; detalle en research.md §11)

- Backend: 3 tests nuevos en creación (1 parametrizado), 3 en presets, `test_migrations.py`
  dirigido.
- Frontend: ~4 tests en `Distribute.test.tsx` (el del panel cubre el uso de los bloques
  extraídos fuera del detalle); `PublicationDetail.test.tsx` existente, sin tests nuevos,
  dirigido para confirmar que los bloques extraídos siguen funcionando en el detalle;
  `ContentDetail.test.tsx` dirigido. No se duplican tests del detalle.
- Sin regresiones de publishers/scheduler. Checks estáticos una vez antes del PR. Suites
  completas solo en CI.

## Complexity Tracking

Sin violaciones de la Constitution que justificar.

## Decisiones aprobadas (2026-10-16)

1. **Panel de resultado compacto** con bloques extraídos a `PublicationControls.tsx` y
   compartidos con `PublicationDetail` (sustituye a la propuesta inicial de embeber
   `PublicationDetail` completo, rechazada).
2. **Distribute no ofrece auto-publish en la creación**; se arma por fila con las reglas
   actuales. El backend mantiene `auto_publish_enabled` por compatibilidad.
3. **Aplicar un preset reemplaza la selección actual**; después se puede ajustar a mano; el
   preset almacenado nunca cambia al aplicarlo.
4. **Cascades**: el preset se elimina con su Project; las memberships, con su preset o su
   Account; un preset puede quedar vacío y sigue existiendo.
5. **Semántica de null**: omitido/`null` = sin override en ese nivel (hereda); `""` = vacío
   explícito; `[]` = hashtags vacíos explícitos. Dirty state explícito en frontend.
