# Implementation Plan: Deletion & Library Organization

**Branch**: `021-deletion-library-organization` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/021-deletion-library-organization/spec.md`

## Summary

Borrado real ("Delete = gone") de Post, Media, Account, Project y carpeta mediante un
**servicio de borrado** único (`app/deletion.py`) que, dentro de una transacción SQLite
`BEGIN IMMEDIATE`, recalcula el alcance, comprueba los dos únicos bloqueos (Post en
Publishing, Remove metadata en curso) y un **token de confirmación** derivado del alcance
mostrado en el preview, borra todo en orden explícito y registra en la misma transacción las
**limpiezas diferidas** (archivos de Media y credenciales del keyring), que se ejecutan
post-commit y, si fallan, en el siguiente arranque. La exclusión con el scheduler se apoya en
la serialización de escritores de SQLite, sin tocar el claim atómico existente. Los ids dejan
de reutilizarse (`AUTOINCREMENT`). Library gana **carpetas lógicas** por proyecto
(`library_folders`, ≤ 5 niveles, unicidad case-insensitive y mismo-proyecto garantizadas por
constraints), `contents.folder_id` (NULL = Unsorted), raíz fija (carpetas + Unsorted + All
media), mover uno o varios Media de forma atómica y rutas propias por vista. Backup/restore
de 020 no cambia de formato.

Detalle y alternativas: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.1, Alembic, keyring; React Router, Radix
Dialog. **Ninguna dependencia nueva.**

**Storage**: SQLite (1 migración: 3 tablas nuevas, 6 tablas recreadas, 1 eliminada por
generalización), Media en disco (sin mover archivos)

**Testing**: pytest + TestClient (backend), Vitest + Testing Library (frontend); tests
dirigidos por bloque; barreras deterministas (`threading.Event`) para concurrencia; suites
completas solo en CI

**Target Platform**: Linux (Ubuntu GNOME, keyring Secret Service), navegador de escritorio y
móvil en LAN

**Project Type**: web application (backend + frontend)

**Performance Goals**: transacción de borrado de un Project típico (cientos de filas) en
milisegundos; Library root con una consulta de carpetas + recuentos; 500 Media sin
paginación (como hoy)

**Constraints**: un proceso; sin red ni keyring dentro de transacciones; arranque nunca
bloqueado por keyring ni con diálogos; sin cambios en el formato de backup

**Scale/Scope**: single-user; decenas de carpetas, cientos de Media por proyecto

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Notas |
|---|---|---|
| I. Simplicidad y alcance | ✅ | Un servicio de borrado, dos colas mínimas, sin framework de jobs, sin soft-delete/Trash, sin mover carpetas. Reutiliza `normalize_key`, índices parciales, `Dialog/Sheet`, patrón "Discard race". |
| II. Spec-Driven | ✅ | Spec "Ready for planning", D1–D9 confirmadas. Nada fuera de alcance. |
| III. Arquitectura modular | ✅ | El núcleo de borrado solo nombra modelos de plataforma en listas de dependencias; credenciales vía mapa `platform → (store, credential_lock)` compuesto en `main.py`; ningún borrado contacta plataformas. |
| IV. Seguridad | ✅ | Nunca secretos en BD/backup/logs; logs de borrado sin rutas, handles ni refs; rutas validadas con `storage.resolve`; todas las rutas nuevas tras sesión + Host/Origin. |
| V. Calidad | ✅ | Tests dirigidos por bloque, incl. carreras con barreras, migración y restore; ningún borrado silencioso de trabajo programado (el usuario lo confirma explícitamente). |
| VI. Git | ✅ | Commits pequeños por fase; README/docs actualizados (borrado, carpetas, recuperación vía backup). |
| Arquitectura base | ✅ | FastAPI + SQLite + filesystem + scheduler local + keyring; sin cambios. |

Re-check post-diseño: ✅ sin violaciones. **Complexity Tracking** vacío.

## Architecture

```text
 Router (deletion_routes.py)          Router (library_folders.py)
   GET  …/deletion-preview  ─┐          folders CRUD · list contents?folder= · move
   DELETE …?confirmation=   ─┤
                             ▼
 Deletion service (deletion.py)
   1. local exclusions: ContentFileGuard.deleting(ids)   (Media/Project only; all-or-nothing,
                                                          409 if any id is in Remove metadata)
   2. write_transaction(session_factory)  ── own new Session, BEGIN IMMEDIATE first ──┐
   3.   collect scope (set queries)                                                   │ single
   4.   blockers (publishing / running attempt)                                       │ SQLite
   5.   confirmation token == ?                                                       │ writer
   6.   _delete_posts → _delete_accounts → presets → folders → _delete_contents       │
   7.   INSERT pending_file_deletions / pending_credential_deletions (write-ahead)    │
   8. COMMIT (any failure before → ROLLBACK, no side effects anywhere) ───────────────┘
      release ContentFileGuard ids (finally, also on 409 / error)
   9. invalidate runtime connection attempts of deleted accounts (TikTok: no revoke)
  10. post-commit cleanup (cleanup.py)
        files: resolve → unlink → delete pending row   (fail → row stays)
        credentials: probe ok? → platform credential_lock → store.delete → delete row

 Connection flows (OAuth ×4, Telegram login) — final step hardened:
   store.set(secret) → write_transaction: re-read Account (exists & valid) → write
   connection → COMMIT; Account gone → no rows, delete secret or queue it, attempt fails
                             ▲
 Startup (main.serve): storage.prepare → sweep clean copies → run_file_cleanup (sync)
   → recover_interrupted_attempts → run_credential_cleanup (thread, probe == available)
   → scheduler.start

 Scheduler / manual publish: unchanged atomic claim (UPDATE … WHERE status/conditions)
   + NotFound mapping when rows vanish during preflight.
```

## Respuestas clave

### 1. Arquitectura de borrado

`router → deletion service → BEGIN IMMEDIATE (todo el estado local) → COMMIT → limpieza
post-commit`. Primitivas sobre conjuntos (`_delete_posts/_contents/_accounts/_folders`)
reutilizadas por Media, Account y Project en la misma transacción. Orden y lista de tablas
explícitos + test de completitud del esquema; las FK RESTRICT se mantienen como red de
seguridad (research §1–§2). Orden fijo de `execute`: exclusiones locales →
`write_transaction` → alcance → bloqueos → token → borrado → filas pendientes → COMMIT →
invalidación de intentos de conexión en runtime → limpieza post-commit. Nada observable
cambia antes del COMMIT.

`write_transaction(session_factory)` crea **su propia** Session, comprueba que la conexión
DBAPI no tiene transacción abierta (si la tiene → `RuntimeError`, nunca rollback
defensivo), emite `BEGIN IMMEDIATE` como primera sentencia, y hace commit/rollback/close
por sí misma (research §4).

### 1b. Delete Account con conexión en curso

Transacción completa → COMMIT → `expire_for_account` (TikTok sin revocación remota) y
`telegram_logins.discard` → limpieza de credenciales bajo el lock de credencial de cada
plataforma. El paso final de **todos** los flujos de conexión se ejecuta en
`write_transaction` y re-lee la Account antes de escribir. Si ya no existe: ninguna fila, el
secreto escrito se borra o pasa a `pending_credential_deletions`, y el intento termina con
`authorization_gone` (research §9).

### 1c. `ContentFileGuard.deleting`

Retención todo-o-nada de los Media afectados (`_deleting`) bajo el mutex del guard, sin
esperas. 409 si alguno está en Remove metadata. Mientras están retenidos, Remove metadata
responde `409 content_deleting`. Se liberan siempre en `finally`, tras COMMIT/ROLLBACK. Solo
Media/Project lo usan (research §6).

### 2. Scheduler vs Delete

Sin cambios en el claim (`UPDATE` condicional + INSERT del intento en un COMMIT). El borrado
toma el lock de escritor con `BEGIN IMMEDIATE` **antes** de leer y comprueba dentro que
ningún Post afectado esté `publishing` ni tenga intento `running`. SQLite serializa: si el
borrado confirma antes, el claim no encuentra fila (`publication_not_eligible` →
`not_claimed`); si el claim confirma antes, el borrado devuelve `409 post_in_progress`.
Endurecimiento: `NotFound` en lugar de 500 cuando las filas desaparecen durante el
preflight, follow-up o check result; `not_found` en `NOT_CLAIMED_CODES` (research §5).

### 3. Esquema / migración `0019`

Nuevas: `library_folders`, `pending_file_deletions`, `pending_credential_deletions`.
Recreadas: `projects`, `accounts`, `distribution_presets`, `contents` (+`folder_id`, FK
compuesta), `publications` (índices parciales recreados) con AUTOINCREMENT;
`temporary_media_objects.attempt_id` nullable. Verificado: su limpieza solo usa
`object_key` y la configuración global del proveedor de entrega, no la Account, la conexión
ni el keyring (research §7, caso A). `tiktok_credential_orphans` → migrada a la
cola genérica y eliminada. No destructiva; pre-021 → todo Unsorted ([data-model.md](data-model.md)).

### 4. IDs no reutilizables

`sqlite_autoincrement=True` en Project, Account, Content, Publication, DistributionPreset y
LibraryFolder; `sqlite_sequence` sembrada con el máximo actual al recrear. Sin UUID
(research §11).

### 5. Limpieza diferida

Write-ahead en la transacción del borrado; intento inmediato post-commit; reintento en el
arranque (archivos síncronos antes del scheduler; credenciales en hilo y solo con sonda
`available`). Idempotente, nunca revive objetos, nunca borra un archivo referenciado ni un
secreto aún usado (research §8, §15, §16).

### 6. API

Preview + DELETE con `confirmation` para los cinco tipos; carpetas (lista plana, crear,
renombrar); `GET …/contents?folder=`; import con `folder_id`; `POST …/contents/move`
([contracts/api.md](contracts/api.md)).

### 7. Modelo de carpetas

`name_key` + dos índices únicos parciales (raíz / hijas), FK compuesta `(parent_id,
project_id)` y `(folder_id, project_id)` para mismo-proyecto, `depth` 1–5 con CHECK;
subárbol por CTE recursiva (research §12–§13).

## Implementation Phases (checkpoints estables)

Cada fase termina con sus tests dirigidos en verde y deja la app usable.

| Fase | Contenido | Checkpoint verificable |
|---|---|---|
| **A. Esquema + base** | Migración 0019 y modelos; `write_transaction`; `ContentFileGuard.deleting` (+ `content_deleting` en Remove metadata); tablas pendientes; `sweep()` con LEFT JOIN; generalizar orphans TikTok; hardening `NotFound` en `start_publication`/scheduler/follow-up/reconcile. | Tests de migración (datos/ids intactos, AUTOINCREMENT, índices parciales, `compare_metadata`), test de completitud de esquema, tests de `write_transaction` (primera sentencia, sesión con transacción → error, segundo escritor espera), tests del guard (4 casos de research §6, con un borrado simulado), tests TikTok orphans existentes adaptados. |
| **B. Delete Post** | `deletion.py` (scope, buckets, token, `_delete_posts`), `deletion_routes.py` preview+DELETE de Post. | Todos los estados; Publishing → 409; duplicado → 404; temp objects pendientes conservados; **carreras scheduler/manual vs delete** con barreras; reinicio sin intentos. |
| **C. Delete Media + archivos** | `_delete_contents`, `cleanup.run_file_cleanup`, arranque de archivos; preview/DELETE Media. | Unlink OK/fallo/reintento en arranque; ruta referenciada no se borra; re-upload aceptado; Remove metadata bloquea; carrera con claim. |
| **D. Delete Account + Project + credenciales** | `_delete_accounts` (conexiones, presets), invalidación post-commit (TikTok `revoke=False`), `credential_lock` público en cada módulo de conexión, paso final de conexión en `write_transaction` con re-lectura de Account en las 5 plataformas, `run_credential_cleanup` + arranque con sonda; Project compuesto; reemplazo de `account_discard.py`. | Keyring disponible/no disponible/bloqueado; resultado tardío OAuth/Telegram tras borrar (sin fila, secreto borrado o en cola); borrado rechazado (`deletion_changed`/Publishing) no invalida intentos; TikTok no revoca; Telegram login en curso no bloquea; objeto temporal pendiente limpiable tras borrar Account/Project; Project atómico, otros proyectos intactos, nuevo proyecto con id nuevo; backup previo restaurado → Reconnect required. |
| **E. Carpetas backend** | `library_folders.py`: lista, crear, renombrar, preview/DELETE carpeta, `contents?folder=`, import con `folder_id`, move. | Jerarquía, 5 niveles, colisión case-insensitive/Unicode, cross-project → 404, borrar subárbol → Unsorted, move múltiple atómico. |
| **F. Library frontend** | Rutas nuevas, Library root, MediaView parametrizada, Breadcrumb, FolderNameDialog, FolderPicker, Select/Move, carpeta en detalle/card. | Vitest de rutas/deep links/not found, root sin grid, picker, move. |
| **G. Borrado frontend** | `DeleteConfirmDialog`, flash, Delete en Post/Media/Account/Project/Folder; Discard setup vía token. | Vitest: summary, blocker, `deletion_changed`, 404 como borrado, navegación + flash. |
| **H. Móvil + cierre** | Ajustes de teléfono (Sheet, breadcrumb colapsado, barra Select), README/docs, quickstart manual, checks de cierre una vez. | Escenarios manuales del [quickstart](quickstart.md) a 360 px; lint/format/typecheck/build/`git diff --check`. |

Orden justificado: A antes de todo (esquema y transacción); B fija el patrón y las pruebas de
carrera que C/D reutilizan; E es independiente de B–D salvo que Project borra carpetas (D
puede borrar `library_folders` porque la tabla existe desde A); F depende de E; G depende de
B–E.

## Test Strategy (dirigida)

| Bloque | Casos representativos |
|---|---|
| Concurrencia | Delete Post/Media/Account/Project vs scheduler tick y vs publish manual, en **ambos órdenes**, con barrera en `publisher.prepare` (fake) y en el commit del claim; nunca intento tras delete; nunca delete tras claim. Delete vs Remove metadata en ambos órdenes, Project con varios Media y liberación tras fallo (research §6). Delete Account vs paso final de conexión en ambos órdenes (YouTube como representativa + Telegram). Sin `sleep`. |
| Efectos parciales | Delete rechazado (`deletion_changed`, `post_in_progress`, `metadata_removal_in_progress`, excepción) → intentos en runtime intactos, guard libre, keyring sin tocar, filas intactas. |
| Borrado | Parametrizado por estado visible (draft, scheduled auto/manual, missed, failed, cancelled, needs review, awaiting, published); remoto intacto (fakes sin llamadas); overview/uso/presets/calendar sin restos; doble delete → 404. |
| Archivos | unlink OK; unlink falla (permiso simulado) → fila; arranque reintenta; ruta referenciada → no se borra; re-upload. |
| Credenciales | store OK; `CredentialStoreUnavailable` → fila y conexión borrada igualmente; arranque con sonda `locked` no toca store; OAuth/Telegram tardío descartado sin conexión ni secreto activo (borrado o en cola si el store falla); TikTok sin revocación. |
| Delivery temporal | Objeto pendiente de un intento borrado sobrevive (`attempt_id NULL`) y `sweep()` lo limpia tras borrar Account/Project sin tocar ningún store de credenciales. |
| Carpetas | crear/renombrar/listar; nivel 6 → 409; "Lux"/"lux"/forma Unicode equivalente → 409; raíz vs hijas; cross-project; borrar subárbol; move atómico con un id ajeno. |
| Migración / backup | 0018→0019 con datos; restore de backup pre-021; backup anterior a un borrado → Reconnect required. |
| Frontend | DeleteConfirmDialog, rutas de Library, FolderPicker, Select/Move, Breadcrumb móvil. |

Suites completas solo en la CI del PR.

## Project Structure

### Documentation (this feature)

```text
specs/021-deletion-library-organization/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   └── ui.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks (no creado aquí)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── db.py                     # + write_transaction (own session, BEGIN IMMEDIATE)
│   ├── models.py                 # LibraryFolder, Pending*Deletion, folder_id, autoincrement
│   ├── deletion.py               # NEW: scope, preview/token, primitives, execute
│   ├── deletion_routes.py        # NEW: preview + DELETE (5 kinds)
│   ├── cleanup.py                # NEW: file / credential queues
│   ├── library_folders.py        # NEW: folders, list by folder, move
│   ├── account_discard.py        # REMOVED (subsumed by deletion)
│   ├── content_files.py          # + ContentFileGuard.deleting
│   ├── contents.py               # folder filter, import folder_id, ContentRead.folder_id
│   ├── media_delivery.py         # sweep() LEFT JOIN
│   ├── publishing.py, scheduler.py   # NotFound hardening
│   ├── *_connections.py          # public credential_lock(); final persist in write_transaction
│   │                             #   with Account re-read; discard failure → pending row
│   ├── tiktok_oauth.py           # expire_for_account(revoke=False)
│   ├── tiktok_connections.py     # generic pending credential helpers
│   ├── schemas.py, errors.py     # new reads / codes
│   └── main.py                   # routers, credential targets, startup cleanup
├── migrations/versions/0019_deletion_library_folders.py
└── tests/                        # test_delete_*.py, test_cleanup_*.py, test_library_folders.py, …

frontend/src/
├── api.ts, types.ts              # preview/delete, folders, move
├── routes.tsx                    # library/unsorted|all|folders/:id
├── components/DeleteConfirmDialog.tsx
├── shell/                        # flash region
└── pages/
    ├── LibraryPage.tsx → LibraryRoot + MediaView
    ├── library/                  # Breadcrumb, FolderPicker, FolderNameDialog, Select bar
    ├── posts/PostDetail.tsx, accounts/AccountDetail.tsx, project/ProjectHeader.tsx
```

**Structure Decision**: web application existente (`backend/`, `frontend/`); módulos nuevos
junto a los actuales, sin capas nuevas.

## Risks

| Riesgo | Mitigación |
|---|---|
| `BEGIN IMMEDIATE` mal integrado con pysqlite/SQLAlchemy (BEGIN implícito duplicado, SQL previo en la sesión, cambios de un caller descartados) | `write_transaction` posee una Session nueva y dedicada (nunca la de la petición); falla con `RuntimeError` si la conexión DBAPI ya tiene transacción, sin rollback defensivo. Tests: `BEGIN IMMEDIATE` es la primera sentencia, un segundo escritor espera al COMMIT y el estado leído es el confirmado. **LOW** (retirado en la fase A: `tests/test_write_transaction.py` en verde con pysqlite real). |
| Resultado tardío de conexión tras borrar la Account | Paso final en `write_transaction` con re-lectura de la Account; FK como red de seguridad; el secreto se borra o pasa a la cola. Queda una ventana de crash entre `store.set` y la limpieza (existente, LOW). |
| `expire_for_account` de TikTok revoca en remoto la credencial pendiente | Modo `revoke=False` usado solo por el borrado; test con gateway fake que falla si se llama a `revoke`. |
| Guard de Media no liberado tras un error | Liberación en `finally` después de COMMIT/ROLLBACK; tests de `deletion_changed`, bloqueo y excepción. |
| Recrear `publications`/`contents` pierde índices parciales o CHECK | Patrón probado de 0006 (`_recreate_partial_index`); test sobre `sqlite_master` + `compare_metadata`. |
| Migración larga en BD real grande | Tablas de cientos/miles de filas: segundos; FK off solo durante migración; restore probado. |
| Credencial re-escrita por un refresh en vuelo tras borrarla | Borrado del secreto bajo el `credential_lock` de la plataforma; refresh que empieza después no encuentra conexión. |
| Keyring con diálogos en acciones del usuario | Mismo comportamiento que Disconnect hoy; omitido si la sonda dice `locked`/`unavailable`; nunca en arranque salvo `available`. |
| Backends sin sonda (`unknown`) no limpian en arranque | Limpieza en el siguiente borrado; host actual da estados reales. Limitación documentada. |
| Token estricto produce `deletion_changed` por cambios irrelevantes | Raro (otra pestaña); solo obliga a reconfirmar; no cambia nada. |
| Archivos de Media visibles en disco tras borrar si unlink falla | Cola write-ahead + arranque; ruta nunca reutilizada. |
| Generalizar orphans TikTok toca un flujo estable | Cambio mecánico de modelo; tests TikTok existentes de cleanup adaptados y ejecutados en fase A. |

## Decisiones

Aprobadas (2026-10-24): `BEGIN IMMEDIATE`, claim sin cambios, AUTOINCREMENT, limpieza
write-ahead + post-commit + arranque, token estricto, generalización de
`tiktok_credential_orphans`, limpieza de credenciales en arranque solo con sonda
`available`, preview + confirmation también para Discard setup.

Incorporadas en esta revisión:

- invalidación de intentos solo después del COMMIT;
- paso final de conexión protegido por la BD;
- `write_transaction` con sesión propia;
- semántica exacta de `ContentFileGuard.deleting`;
- `temporary_media_objects` es autosuficiente (caso A);
- TikTok sin revocación remota al borrar.

No quedan decisiones pendientes.

## Complexity Tracking

Vacío: sin violaciones de la Constitution.
