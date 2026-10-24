# Research — Feature 021: Deletion & Library Organization

Fecha: 2026-10-24 · Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md)

Todas las decisiones parten del código real de `main` (673d4d5). Formato por decisión:
**Decisión / Razón / Alternativas descartadas**.

---

## §0. Inventario del modelo actual (código real)

### Tablas, claves foráneas y `ON DELETE`

| Tabla | FK | ON DELETE | Notas |
|---|---|---|---|
| `projects` | — | — | `name_key` UNIQUE. INTEGER PK **sin** AUTOINCREMENT. |
| `accounts` | `project_id → projects` | RESTRICT | UNIQUE(project_id, platform, handle_key). Sin AUTOINCREMENT. |
| `distribution_presets` | `project_id → projects` | **CASCADE** | UNIQUE(project_id, name_key). |
| `distribution_preset_accounts` | `preset_id → presets`, `account_id → accounts` | **CASCADE** ambas | PK compuesta. |
| `contents` (Media) | `project_id → projects` | RESTRICT | UNIQUE(project_id, checksum); `storage_path` y `sanitized_storage_path` UNIQUE. Sin AUTOINCREMENT. |
| `publications` (Post) | `project_id`, `content_id` (nullable), `account_id` | RESTRICT ×3 | Índice parcial único activo (content, account) `WHERE status NOT IN ('cancelled','published')`. |
| `publication_attempts` | `publication_id → publications` | RESTRICT | Índice parcial único `WHERE status='running'`. |
| `youtube/instagram/threads/tiktok_publication_options` | `publication_id` (PK) | RESTRICT | Una fila opcional por Post. |
| `instagram/threads/tiktok_publish_runs` | `attempt_id` (PK), `publication_id` | RESTRICT ×2 | Estado remoto por intento. |
| `temporary_media_objects` | `attempt_id → publication_attempts` | RESTRICT, **NOT NULL** | Objetos en el proveedor de entrega; limpieza propia (`release`, `sweep`). |
| `youtube/instagram/threads/tiktok/telegram_connections` | `account_id`, `project_id` | RESTRICT ×2 | UNIQUE(account_id), UNIQUE(credential_ref). |
| `tiktok_credential_orphans` | — (sin FK) | — | PK `credential_ref`; patrón de limpieza diferida existente solo para TikTok. |
| `automation_settings`, `installation_auth`, `auth_sessions` | — | — | Globales; no se tocan. |

- **No hay relaciones SQLAlchemy** (`relationship`) en ningún modelo: todo es por columnas e
  ids. No hay cascadas ORM que reutilizar ni que temer.
- `PRAGMA foreign_keys=ON` en cada conexión de la app (`app/db.py`); las migraciones usan un
  engine propio **sin** ese pragma (FK desactivadas durante `batch_alter_table`).
- SQLite en modo journal por defecto (no WAL), timeout de pysqlite por defecto (5 s). La
  transacción implícita de pysqlite solo empieza con el primer DML (los SELECT previos van
  fuera de transacción).

### Estado en memoria relevante

| Estado | Dónde | Clave |
|---|---|---|
| Intentos OAuth YouTube/Instagram/Threads/TikTok | `app.state.*_attempts` (`expire_for_account`) | `account_id` |
| Login Telegram pendiente | `app.state.telegram_logins` (`discard`) | `account_id` |
| Lock de sesión Telegram | `telegram_connections.account_session` | `account_id` |
| Locks de credencial por cuenta | `_account_lock` en `youtube/instagram/threads/tiktok_connections` | `account_id` |
| Remove metadata en curso | `ContentFileGuard._sanitizing` (`app.state.content_file_guard`) | `content_id` |
| Hilos de publicación | `PublicationRunner._threads` | `attempt_id` |

### Archivos físicos

- `contents.storage_path` = `projects/{project_id}/{uuid}{ext}` (original).
- `contents.sanitized_storage_path` = `projects/{project_id}/{uuid}.clean{ext}` (copia limpia).
- No hay derivados. Los nombres son UUID: nunca colisionan aunque se reutilice un
  `project_id`, pero el **directorio** sí se compartiría (ver §11).
- `sweep_orphan_clean_copies` (arranque) ya borra `.clean.` no referenciados; nunca toca
  originales.

### Conclusiones que condicionan el diseño

1. Las FK RESTRICT ya garantizan "ninguna referencia rota": cualquier tabla olvidada en un
   borrado hace fallar el COMMIT (atómico). Se **mantienen** como red de seguridad.
2. `temporary_media_objects.attempt_id NOT NULL RESTRICT` impide borrar intentos con objetos
   remotos pendientes: requiere cambio de esquema (§7).
3. El claim del scheduler ya es un `UPDATE` condicional atómico; la exclusión con el borrado
   se obtiene serializando en la BD (§5), sin tocar el claim.
4. Las cinco `complete_connection` ya implementan el patrón "Discard race" (secreto → fila →
   si falla y la cuenta ya no existe: borrar secreto y `authorization_gone()`); se reutiliza
   para FR-028.

---

## §1. Arquitectura de borrado

**Decisión**: capa explícita `router → deletion service → transacción única → limpieza
post-commit`.

- `app/deletion.py` (servicio, sin tipos HTTP):
  - `collect_<kind>(session, id) -> DeletionScope`: calcula el alcance (ids de Posts con su
    categoría, Media, Accounts, carpetas, conexiones, rutas de archivos, credential refs) con
    consultas por conjunto (sin N+1).
  - `preview(scope) -> DeletionPreview`: recuentos, resumen humano, bloqueo y `confirmation`.
  - `execute(session_factory, kind, id, confirmation, ctx) -> CleanupWork`, en este orden
    fijo:
    1. adquiere las exclusiones locales necesarias (solo `ContentFileGuard.deleting` para
       Media/Project, §6);
    2. abre su propia `write_transaction` (§4);
    3. recalcula el alcance;
    4. comprueba bloqueos y token;
    5. borra el estado local;
    6. registra la limpieza pendiente;
    7. COMMIT;
    8. **solo entonces** invalida los intentos de conexión en runtime;
    9. devuelve el trabajo de limpieza post-commit.

    Un rechazo o un error antes del COMMIT no deja ningún efecto en BD, runtime, keyring
    ni disco.
  - Primitivas internas reutilizables sobre conjuntos: `_delete_posts(ids)`,
    `_delete_contents(ids)`, `_delete_accounts(ids)`, `_delete_folders(ids)`. Project las
    compone en la misma transacción.
- `app/cleanup.py`: colas persistentes de archivos y credenciales (`run_file_cleanup`,
  `run_credential_cleanup`), usadas post-commit y en el arranque.
- `app/deletion_routes.py`: router con preview + DELETE de los cinco tipos; traduce errores.
- `app/library_folders.py`: carpetas (CRUD, listado, mover Media).

**Razón**: un único sitio conoce el orden de borrado y los bloqueos; los routers quedan
finos; Project reutiliza primitivas sin llamadas HTTP ni commits intermedios.

**Alternativas descartadas**: `ON DELETE CASCADE` en la BD (exige recrear ~12 tablas, oculta
el orden y no permite comprobar bloqueos ni recoger archivos/credenciales antes de borrar);
lógica repartida por routers (duplicación y commits parciales); ORM cascades (no hay
relaciones definidas y añadirlas cambia todo el modelo).

---

## §2. Guarda de completitud del borrado

**Decisión**: tuplas explícitas en `app/deletion.py` con el orden de borrado:

- `POST_ATTEMPT_DEPENDENTS = (InstagramPublishRun, ThreadsPublishRun, TikTokPublishRun)`
- `POST_DEPENDENTS = (YouTubePublicationOptions, InstagramPublicationOptions,
  ThreadsPublicationOptions, TikTokPublicationOptions)`
- `CONNECTION_MODELS` (las cinco conexiones, con su `Platform`).

Más un **test de esquema** que recorre `Base.metadata` y falla si existe una tabla con FK a
`projects`, `accounts`, `contents`, `publications`, `publication_attempts` o
`library_folders` que no esté en esas tuplas ni en la lista de tablas tratadas a mano.

**Razón**: legible, sin magia de metadatos en tiempo de ejecución; una futura plataforma que
añada una tabla rompe el test (y, si no, el RESTRICT rompe el COMMIT), nunca deja basura.
Las tablas de plataforma se nombran solo como modelos en una lista de dependencias, sin
lógica de plataforma en el núcleo (Constitution III).

**Alternativas descartadas**: derivar el orden de `metadata.sorted_tables` en runtime (menos
explícito; `temporary_media_objects` necesita trato especial igualmente).

---

## §3. Resumen de consecuencias y token de confirmación (FR-003)

**Decisión**: `GET …/deletion-preview` calcula el alcance y devuelve recuentos, líneas de
resumen, bloqueo (si lo hay) y `confirmation`: `"v1:" + sha256(JSON canónico)` del alcance
relevante:

- kind + id del objetivo;
- lista de `(post_id, status, needs_review)` ordenada por `post_id`. `status` es la
  columna persistida (`unscheduled`, `scheduled`, …) y `needs_review` es el booleano
  derivado del último intento. Con eso el token cambia cuando cambia cualquier frase del
  resumen: buckets, "will not be published" de un Post programado, advertencia de Needs
  review;
- ids ordenados de Media, Accounts y carpetas afectados.

Solo valores persistidos y deterministas: **nunca** estados derivados del reloj (Missed,
Overdue, `auto_publish_state`), timestamps, nombres, handles ni refs de credencial. JSON
con `sort_keys=True` y listas ordenadas explícitamente, nunca en el orden de las
consultas. Que el tiempo pase (un Scheduled que se vuelve Missed) no provoca
`deletion_changed`. Los bloqueos no forman parte del token: se comprueban por separado y
dan su propio 409.

`DELETE …?confirmation=<token>` recalcula el alcance **dentro** de la transacción de
escritura y compara: distinto → `409 deletion_changed` (nada cambia). El frontend vuelve a
pedir el preview y muestra el resumen nuevo.

- Igualdad estricta: detecta cualquier aumento (Post nuevo, Media nueva en la carpeta, un
  Post que pasa de no publicado a publicado). También rechaza disminuciones (p. ej. otro tab
  borró un Post): es raro y solo obliga a reconfirmar; simplifica el contrato.
- El token no es un secreto ni un lock: no se guarda nada en servidor, no hay locks mientras
  el usuario mira el diálogo, y es determinista (mismo estado → mismo token).
- `confirmation` es obligatorio en los cinco DELETE (422 si falta).

**Razón**: transaccional, sin estado en servidor, sin confiar en recuentos del cliente.

**Alternativas descartadas**: el cliente reenvía los recuentos (se confía en el cliente);
versión/`updated_at` por fila (no capta filas nuevas); lock o reserva temporal (estado en
servidor, caducidades, locks largos).

### Buckets (reutilizan `app.post_state`)

| Bucket | Estados |
|---|---|
| `unpublished` | `unscheduled` (draft), `scheduled` (incl. Missed), `cancelled`, `failed` con resultado determinado |
| `remote` | `published`, `awaiting_user_action` |
| `needs_review` | `failed` cuyo último intento tiene `outcome_determined = False` (`needs_manual_review`) |

El texto agrupa `remote + needs_review` como "published post(s)" en Media/Account (FR-020) y
añade la advertencia de Needs review (FR-015, edge case). `publishing` nunca es bucket: es
bloqueo.

---

## §4. Transacción de escritura en SQLite

**Decisión**: context manager `write_transaction(session_factory)` en `app/db.py` que
**posee** su propia Session, nueva y dedicada; nunca recibe ni reutiliza la sesión de la
petición:

```text
with write_transaction(session_factory) as tx:      # conceptual
    1. session = session_factory()                  # sesión nueva, sin estado
    2. conn = session.connection()                  # checkout; pysqlite no emite SQL
    3. assert not conn.connection.driver_connection.in_transaction
       → si ya hay transacción a nivel DBAPI: RuntimeError (siempre, no solo en dev;
         nunca rollback defensivo)
    4. conn.exec_driver_sql("BEGIN IMMEDIATE")       # primera sentencia SQL
    5. yield session                                # scope, bloqueos, token, DML
    6a. éxito → session.commit()
    6b. excepción → session.rollback(); re-raise
    7. finally → session.close()
```

- Ningún SELECT precede a `BEGIN IMMEDIATE` en esa sesión: todas las lecturas que deciden
  (alcance, bloqueos, token) ven el estado confirmado bajo el lock de escritor.
- No puede descartar cambios de un caller: la sesión es suya y nadie más la ve. La sesión de
  la petición (`get_session`) solo se usa para lecturas fuera del borrado (p. ej. el
  preview).
- **Regla de uso (riesgo de auto-bloqueo)**: en modo journal de SQLite, otra conexión del
  **mismo hilo** que tenga DML sin confirmar (lock RESERVED) o un cursor de lectura abierto
  dentro de una transacción haría esperar a `BEGIN IMMEDIATE`/COMMIT hasta el timeout
  (5 s) y fallaría con `database is locked`. Por eso, quien llame a `write_transaction` no
  debe tener DML pendiente en la sesión de la petición:
  - las rutas DELETE no usan la sesión de la petición;
  - los flujos de conexión mueven **todas** sus escrituras finales (conexión,
    `adopt_connected_identity`, orphans) dentro de `write_transaction`;
  - los objetos ORM de la sesión de la petición nunca se pasan a la transacción: dentro
    se vuelven a leer.

  Test de T004: una sesión de petición con solo lecturas completadas no bloquea a
  `write_transaction`.
- El mismo helper se usa en el paso final de los flujos de conexión (§9b).
- Test dirigido: un segundo escritor (claim simulado) espera hasta el COMMIT; el helper
  falla si la conexión llega con una transacción abierta; `BEGIN IMMEDIATE` es la primera
  sentencia (listener `before_cursor_execute` en el test).

Todo el borrado (recalcular alcance, comprobar bloqueos y token, DELETE/UPDATE, filas
pendientes) ocurre dentro.

- `BEGIN IMMEDIATE` toma el lock RESERVED antes de leer: ningún otro escritor (claim del
  scheduler, publish manual, persistencias del runner) puede confirmar entre la comprobación
  y el borrado. Las lecturas dentro ven el estado final confirmado.
- La duración es solo la del trabajo en BD (milisegundos incluso para Project); no hay red,
  keyring ni disco dentro.
- Si no se obtiene el lock en el timeout de pysqlite (5 s) → error interno genérico con el
  formato existente (nunca detalles técnicos); en la práctica no ocurre (los demás escritores
  son transacciones cortas).

**Razón**: la exclusión se apoya en la BD (FR-007), no en locks en memoria ni en tiempos. Con
pysqlite, una transacción diferida que lee y luego escribe puede ver un estado ya obsoleto o
fallar con `database is locked` al promocionar; `IMMEDIATE` elimina ambos problemas.

**Alternativas descartadas**: `DELETE … WHERE status <> 'publishing'` sin transacción
explícita (no protege el cálculo de alcance/token ni las tablas hijas); WAL (cambio global de
journal sin necesidad); locks Python (no cubren otros caminos de escritura).

---

## §5. Scheduler / publicación vs Delete

### Cómo funciona hoy (verificado)

1. `Scheduler._candidates` lee (fuera de transacción) Posts `scheduled` armados en ventana.
2. `start_publication` → `get_publication_or_404`, `auto_start_blocker`, `local_check`,
   `publisher.prepare()` (red/keyring), y `create_running_attempt`.
3. `create_running_attempt` (bajo `ContentFileGuard.claiming`): **un** `UPDATE publications
   SET status='publishing' WHERE id=? AND <condiciones>` + `INSERT` del intento `running`,
   un COMMIT. `rowcount != 1` → `_not_startable` → `publication_not_eligible` (si la fila ya
   no existe) → el scheduler lo trata como `not_claimed`.
4. `PublicationRunner` ejecuta en hilo; `persist_success/failure` cierran intento y Post en
   una transacción.
5. `recover_interrupted_attempts` (arranque, antes del scheduler) cierra intentos `running`.

### Garantía

**Decisión**: el borrado ejecuta en `BEGIN IMMEDIATE` y, dentro, rechaza con `409
post_in_progress` si algún Post afectado está `publishing` **o** tiene un intento `running`.
El claim no cambia. Como SQLite tiene un único escritor:

- **Delete confirma primero** → el `UPDATE` del claim no encuentra la fila (rowcount 0) →
  `publication_not_eligible` → no se crea intento. Nunca se publica.
- **Claim confirma primero** → el borrado ve `publishing`/intento `running` → 409, nada
  cambia.
- Nunca ambos: la comprobación y el DELETE del borrado están en la misma transacción
  serializada contra el claim.

### Cambios mínimos de endurecimiento (no cambian la garantía)

1. `start_publication`: si una fila (Post, Account, Content) desaparece durante el preflight
   (`NoResultFound`/`ObjectDeletedError` de `get_one`), traducir a `NotFoundError` en vez de
   500.
2. `scheduler.NOT_CLAIMED_CODES` += `"not_found"`: un candidato borrado entre la selección y
   el claim no registra un "auto publish error" ni hace ruido en logs.
3. `follow_up_publication` y `reconcile_uncertain` (acciones manuales de Awaiting / Needs
   review): mismo mapeo a 404 si el Post o la Account desaparecen durante la llamada remota.
   Su escritura final ya es condicional (`UPDATE … WHERE status=…`): sobre una fila borrada
   no hace nada.
4. `add_warnings`/`update_details` del runner ya toleran el intento desaparecido
   (`NoResultFound` es `SQLAlchemyError` → log de aviso). Solo pueden ocurrir tras
   `persist_success`, cuando el Post ya no está `publishing`.

### Comportamiento por caso

| Caso | Resultado |
|---|---|
| Tick concurrente | Exactamente uno gana (arriba). Un candidato borrado → `not_claimed` silencioso. |
| Publish manual concurrente | Igual: o 409 al borrar, o el usuario recibe 404/`publication_not_eligible` al publicar. |
| Recuperación tras reinicio | Solo cierra intentos `running`; un Post borrado no tiene intentos. Un borrado nunca ocurre con intento `running` (bloqueo), así que no queda nada que "resucitar". |
| Awaiting user action | Borrable. El seguimiento es manual (`follow_up_publication`); tras el borrado devuelve 404. No hay sondeo automático que continuar. |
| Needs review | Borrable; la advertencia del resumen lo explica. El aviso "check before republishing" desaparece porque se calcula sobre intentos que ya no existen. |
| Remove metadata (Media) | Ver §6. |

**Alternativas descartadas**: comprobar estado antes del DELETE sin transacción (carrera
TOCTOU); lock Python compartido scheduler/borrado (no cubre todos los escritores ni
procesos; acopla módulos); marcar Posts "deleting" (estado intermedio visible y que
sobreviviría a un crash).

---

## §6. Remove metadata vs Delete — `ContentFileGuard.deleting`

**Estado actual**: `ContentFileGuard` tiene un mutex interno (`_lock`) y el conjunto
`_sanitizing`. `sanitizing(id, check)` registra el id bajo el mutex (tras `check`) y lo
retiene mientras dura todo Remove metadata (fuera del mutex). `claiming(id)` mantiene el
mutex durante el claim de publicación.

**Decisión**: añadir el conjunto `_deleting` y un context manager
`deleting(content_ids: Collection[int])` que **retiene** los Media afectados durante toda
la operación de borrado:

```text
with guard.deleting(ids):                 # conceptual
    adquirir (bajo _lock, sin esperar):
        ordenar ids ascendente
        si alguno ∈ _sanitizing           → 409 metadata_removal_in_progress (nada registrado)
        si alguno ∈ _deleting             → 409 deletion_changed (nada registrado)
        _deleting |= ids                  # todo o nada
    yield                                 # validación + write_transaction completa
    finally (bajo _lock): _deleting -= ids  # siempre: éxito, blocker, deletion_changed,
                                            # rollback o excepción
```

Un id ya en `_deleting` significa otro borrado concurrente que lo incluye (doble clic,
otra pestaña, Media y Project a la vez): se responde `deletion_changed` sin código nuevo;
al revisar, el preview dará 404 si el otro ganó.

`sanitizing(id, check)` se amplía: bajo `_lock`, si `id ∈ _deleting` → `409
content_deleting` "This media is being deleted." y Remove metadata no empieza.

Semántica:

- **Exclusión real, no un check puntual**: mientras los ids están en `_deleting`, ningún
  Remove metadata nuevo puede empezar sobre ellos; mientras un id está en `_sanitizing`,
  ningún borrado que lo incluya puede empezar.
- **Sin deadlocks**: la adquisición es atómica (todo o nada) bajo un único mutex y nunca
  espera; no hay "hold and wait" entre ids. El orden ascendente solo hace determinista el
  registro y los logs. El mutex se suelta antes de abrir la transacción.
- **Conjunto afectado**: Media → `{content_id}`. Project → ids de todos sus Media, leídos
  en una lectura breve **antes** del guard (sesión de lectura propia). Dentro de
  `write_transaction` se recalcula el alcance; si aparece un Media no retenido (importado
  entre medias) → `409 deletion_changed` (el token también cambiaría). Así nunca se borra
  un Media no protegido.
- Delete Post, Account y Folder **no** usan el guard (no borran Media ni archivos).

Interacción con `BEGIN IMMEDIATE` y el claim. El orden global de adquisición es:
`ContentFileGuard._lock` (instantáneo) → lock de escritor SQLite.

- `deleting` solo usa `_lock` para registrar y para liberar, **nunca** mientras tiene la
  transacción abierta. La liberación ocurre después de COMMIT/ROLLBACK.
- `claiming` mantiene `_lock` mientras espera el lock de escritor. Puede esperar a que el
  borrado confirme, pero el borrado no necesita `_lock` para confirmar. Después el claim
  libera `_lock` y el borrado libera sus ids. No hay ciclo.
- `claiming` no consulta `_deleting`: la exclusión entre borrado y publicación la da la BD
  (§5).

Remove metadata que leyó el Media antes del borrado y empieza después de la liberación:
su `UPDATE contents … WHERE id=?` final no encuentra fila → rollback y descarta su copia
(código existente). Si un crash deja la copia, `sweep_orphan_clean_copies` la borra al
arrancar.

Tests deterministas (barreras `threading.Event`):

1. Delete adquiere primero (barrera dentro de la transacción) → Remove metadata del mismo
   Media → `409 content_deleting`, sin copia creada.
2. Remove metadata adquiere primero (barrera en `_sanitize_to`) → Delete Media → `409
   metadata_removal_in_progress`, nada borrado.
3. Project con 3 Media, uno en Remove metadata → 409 y los otros dos no quedan retenidos
   (un Remove metadata posterior sobre ellos funciona).
4. `deletion_changed`, blocker `post_in_progress` y excepción forzada en la transacción →
   `_deleting` vacío al terminar.

**Razón**: el estado "Remove metadata en curso" solo vive en memoria (un proceso); el guard
es su única fuente de verdad y ya coordina con el claim.

---

## §7. Delete Post

**Decisión** — orden dentro de la transacción, para el conjunto `P` de Posts e `A` = sus
intentos:

1. `temporary_media_objects` de `A`: `DELETE` las ya borradas (`deleted_at IS NOT NULL`);
   `UPDATE attempt_id = NULL` las pendientes (siguen en la cola de limpieza remota).
2. `instagram/threads/tiktok_publish_runs WHERE publication_id IN P`.
3. `publication_attempts WHERE publication_id IN P`.
4. `*_publication_options WHERE publication_id IN P`.
5. `publications WHERE id IN P`.

### Inspección de `temporary_media_objects` (código actual)

- **Campos**: `id`, `provider` (nombre del proveedor), `object_key` (UNIQUE, clave
  aleatoria `"{key_prefix}{uuid}/{uuid}.{ext}"`), `attempt_id`, `content_type`,
  `size_bytes`, `created_at`, `uploaded_at`, `deleted_at` (NULL = pendiente),
  `cleanup_failures`, `last_cleanup_at`.
- **Qué limpia**: `TemporaryMediaService.release(key)` → `provider_factory()` →
  `provider.delete(key)`; marca `deleted_at` o suma `cleanup_failures`. `release_attempt`
  (fin de un intento Instagram/Threads) y `sweep()` (arranque y antes de cada publicación
  Instagram/Threads) solo **seleccionan** claves y llaman a `release`.
- **Qué necesita**: solo `object_key` y la configuración **global** del proveedor de
  entrega (`media_delivery.json`, leída en cada uso por `load_media_delivery_config`;
  endpoint, bucket y claves de acceso del bucket en ese archivo local, no en el keyring).
  **No** usa PublicationAttempt (salvo para excluir intentos `running` en `sweep`), ni
  Account, ni Connection, ni `credential_ref` ni ningún secreto de plataforma.
- **Caso A — autosuficiente.** Borrar Post, Account o Project (incluidas sus credenciales)
  no impide la limpieza: la fila con `attempt_id = NULL` conserva todo lo necesario. No hace
  falta ordenar "delivery cleanup → credential cleanup". Limitación existente, no
  introducida aquí: `provider` se guarda pero `release` usa la configuración **actual**; si
  el usuario cambia de bucket, los objetos antiguos fallan y quedan contados en
  `cleanup_failures`.

Cambio de esquema: `temporary_media_objects.attempt_id` pasa a **nullable** (FK RESTRICT
se mantiene).

Test específico: Account con un Post Instagram cuyo intento falló dejando un objeto
pendiente (`deleted_at IS NULL`). Se borran la Account y luego el Project, con stores de
credenciales fake que fallan si se usan. Resultado esperado: la fila sobrevive con
`attempt_id NULL` y `sweep()` llama a `provider.delete(key)` (proveedor fake) y marca
`deleted_at`, sin tocar ningún store de credenciales. Con un objeto ya limpiado, la fila
desaparece con el Post. `TemporaryMediaService.sweep()` pasa a `LEFT OUTER JOIN`: pendientes cuyo
intento no existe o no está `running`. `release(key)` sigue funcionando por clave; solo
`release_attempt(attempt_id)` deja de verlas (las recoge el siguiente `sweep`: arranque o
siguiente publicación Instagram/Threads). FR-017 cumplido sin contacto remoto en el borrado.

No hay otro recurso externo temporal: el borrado de Post no tiene limpieza post-commit.

**Alternativas descartadas**: borrar los objetos remotos dentro del borrado (red dentro de
la transacción; FR-001); conservar el intento (viola "gone"); `ON DELETE SET NULL`
(equivalente, pero el resto del borrado es explícito; se prefiere un único estilo).

---

## §8. Delete Media y archivos

**Decisión**:

1. `guard.deleting({content_id})` (Remove metadata → `metadata_removal_in_progress`) +
   `write_transaction`; bloqueo: Post del Media `publishing`/intento `running` →
   `post_in_progress`.
2. Token.
3. `_delete_posts(posts del Media)` (cualquier estado).
4. `INSERT pending_file_deletions` para `storage_path` y, si existe,
   `sanitized_storage_path` (**write-ahead**, siempre, no solo si falla el unlink).
5. `DELETE contents`. COMMIT.
6. Post-commit: `run_file_cleanup(paths)`: por cada ruta, `storage.resolve()` → `unlink`
   (inexistente = éxito) → borrar su fila pendiente. Fallo → log sin ruta absoluta, la fila
   queda, se reintenta en el siguiente arranque.

Seguridad del archivo:

- La ruta solo se borra si **ningún** `contents.storage_path/sanitized_storage_path` la
  referencia (se comprueba en la limpieza; con UUID nunca debería ocurrir, pero FR-022 lo
  exige).
- `storage.resolve()` rechaza rutas fuera de la raíz de Media.
- Un archivo pendiente nunca vuelve a usarse: ningún Media lo referencia y las rutas nuevas
  son UUID.
- Re-subir el mismo archivo: la fila con su `checksum` ya no existe → UNIQUE(project_id,
  checksum) lo acepta como nuevo con ruta UUID nueva (FR-023).

**Razón**: escribir la intención en la misma transacción hace que un crash entre COMMIT y
unlink nunca deje un huérfano desconocido; el coste son dos inserts.

**Alternativas descartadas**: unlink antes del COMMIT (si la transacción falla, Media sin
archivo); registrar solo si falla (un crash entre COMMIT y unlink deja un huérfano
desconocido); GC general que escanee el disco (fuera de alcance, riesgo de borrar originales).

---

## §9. Delete Account

### §9a. Secuencia (sin efectos en runtime antes del COMMIT)

1. **Exclusiones locales**: ninguna (no borra Media → sin `ContentFileGuard`; no se toma
   `account_session` ni `credential_lock` antes de la transacción, para no bloquear por
   una conexión en curso).
2. `write_transaction` (`BEGIN IMMEDIATE` como primera sentencia).
3. Calcular el alcance: Posts de la cuenta y sus buckets, conexiones con su
   `(platform, credential_ref)` y memberships de presets.
4. Bloqueo: algún Post `publishing` o con intento `running` → `409 post_in_progress`.
5. Token distinto → `409 deletion_changed`.
6. Borrar estado local: `_delete_posts`, `DELETE distribution_preset_accounts`,
   `DELETE <conexiones>` y `DELETE accounts`.
7. `INSERT pending_credential_deletions` por cada ref (write-ahead).
8. **COMMIT**. Si algo falló antes, ROLLBACK: no hay ningún efecto en runtime ni en
   el keyring.
9. **Invalidar intentos en runtime** (solo tras el COMMIT): `expire_for_account` en los
   registros YouTube/Instagram/Threads/TikTok y `telegram_logins.discard(account_id)`.
   TikTok usa un modo **sin revocación** (`expire_for_account(account_id, revoke=False)`):
   hoy `expire_for_account` entrega la credencial pendiente a `discard_credential`, que la
   revoca en TikTok. Eso es contacto remoto, prohibido por FR-001/FR-030. En este modo la
   credencial pendiente (solo en memoria, nunca guardada) se descarta sin red. El resto de
   llamadas existentes conserva su comportamiento.
10. **Limpieza post-commit** (`run_credential_cleanup(refs)`, §15): por cada ref se toma el
    `credential_lock(account_id)` de su plataforma con espera acotada. En Telegram es
    `account_session`, que también retiene `_complete_login`. Después `store.delete(ref)` y
    se borra la fila pendiente. Si el store no está disponible o el lock no llega a tiempo,
    la fila queda.

### §9b. Resultado tardío de un intento de conexión (todas las plataformas)

Hoy, las cinco completaciones guardan primero el secreto y después hacen
`INSERT/UPDATE` de la conexión con la sesión de la petición. Confían en la FK y en
`account_gone()` después del fallo, y Telegram en algunos casos no limpia el secreto. Se
endurece **el paso final de persistencia** de todos los flujos (OAuth YouTube, Instagram,
Threads y TikTok, incluido el cambio de cuenta confirmado, y el login de Telegram):

```text
secreto ya obtenido (en memoria)
store.set(new_ref | ref existente en Telegram)      # fuera de transacción (keyring)
with write_transaction(session_factory) as tx:       # BEGIN IMMEDIATE primero
    account = SELECT accounts WHERE id = :account_id
    if account is None (o ya no es válida según las reglas actuales del flujo:
                        misma plataforma, activa/conectable):
        raise AccountGone
    existing = SELECT conexión de la cuenta   # re-leída aquí, no la de antes
    (comprobaciones existentes: identidad, connection_changed, …)
    INSERT/UPDATE conexión; adopt_connected_identity; orphans del ref anterior
COMMIT
```

Si salta `AccountGone` (o falla el COMMIT y `account_gone()` lo confirma):

- no se crea ni se recrea Account ni Connection;
- el secreto escrito por este flujo se borra con `store.delete`. Si el store no está
  disponible, se registra en `pending_credential_deletions` con una `write_transaction`
  breve propia (`INSERT OR IGNORE`, idempotente). Telegram, al renovar, sobrescribe el
  `credential_ref` existente; ese ref ya está en la cola desde el borrado, así que basta
  con intentar `store.delete` y asegurar la fila;
- el intento se cierra con el error existente `authorization_gone()` ("Authorization not
  valid…") y la página de callback lo muestra;
- `_discard_secret` deja de ser best-effort silencioso: si falla, registra en la cola.

Por qué la BD protege la decisión. El borrado y el paso final de conexión son ambos
`BEGIN IMMEDIATE`, así que SQLite los serializa:

- si la conexión confirma primero, el borrado la ve y la elimina junto con su credencial;
- si el borrado confirma primero, la re-lectura de la Account no la encuentra.

La FK `RESTRICT` de la conexión hacia `accounts` sigue como red de seguridad. No existe
flag ni soft-delete: "válida" = la fila existe y cumple las reglas actuales.

El orden con el secreto (secreto antes que fila) se mantiene: nunca hay una fila sin
secreto. Un crash entre `store.set` y la limpieza deja un secreto huérfano desconocido,
igual que hoy. Es una ventana mínima y se acepta (riesgo bajo).

Por qué además se invalida en runtime (paso 9):

- un intento no reclamado deja de ser utilizable: su callback responde "Authorization not
  valid" antes de contactar al proveedor;
- un intento ya reclamado (`claimed`/`PROCESSING`) termina su paso y cae en §9b.

### §9c. Otros concurrentes

- Refresh de token (YouTube/Instagram/Threads/TikTok bajo `_account_lock`). El borrado
  del secreto usa ese mismo lock, así que un refresh en vuelo termina su `store.set`
  antes. Verificado en el código: los refresh leen la fila de conexión **antes** del lock,
  pero dentro de él hacen `store.get(ref)` antes de cualquier `store.set`. Uno que tome el
  lock después del borrado del secreto lee `None` y va a `reconnect_required` sin
  reescribir nada. Ese `reconnect_required` sobre una fila ya borrada puede lanzar un
  error ORM; T011 lo traduce a 404/no-op. Si la limpieza se aplazó (keyring bloqueado), un
  refresh tardío puede reescribir el secreto, pero la fila pendiente sigue y se borra en
  la siguiente limpieza.
- Paso de Telegram en curso: el borrado no lo espera ni lo rechaza. Solo la limpieza del
  secreto espera a `account_session`. FR-028 permite esperar y nunca hay 409.
- IDs no reutilizables (§11): un resultado tardío nunca puede adjuntarse a otra cuenta.

Se sustituye `DELETE /api/accounts/{id}` (descartar provisional, `account_discard.py`) por
el borrado general. Una cuenta provisional no tiene Posts ni conexión, así que el resultado
es idéntico (FR-025). Desaparecen `account_busy` y `account_not_discardable`. Nunca se
contacta la plataforma (FR-030). Un preset que se queda vacío se conserva.

**Alternativas descartadas**:

- bloquear con 409 mientras hay una conexión en curso (prohibido por D8);
- invalidar en memoria antes de la transacción (efectos parciales si el borrado se
  rechaza);
- bool en memoria "account deleted" (no protege frente a la carrera con la BD);
- borrar el secreto antes del COMMIT;
- mantener la conexión si falla el keyring (FR-029).

---

## §10. Delete Project

**Decisión**: una única transacción que compone las primitivas sobre conjuntos:

1. Lectura breve (sesión de lectura propia) de los ids de Media del proyecto.
2. `guard.deleting(esos ids)`. Si alguno está en Remove metadata →
   `metadata_removal_in_progress` y no se abre la transacción.
3. `write_transaction`: recalcular el alcance. Si hay un Media no retenido →
   `deletion_changed`. Después, bloqueos (`post_in_progress`) y token.
4. `_delete_posts(todos)` y `_delete_accounts(todas)` (conexiones → pending credentials,
   memberships). Después `DELETE distribution_presets`, `UPDATE contents SET folder_id =
   NULL`, `DELETE library_folders` (por `depth DESC`), `_delete_contents(todas)` (pending
   files) y `DELETE projects`. COMMIT.
5. Liberar el guard (en `finally`, también en error).
6. Tras el COMMIT: invalidar los intentos en runtime de todas sus cuentas (TikTok sin
   revocación).
7. Limpieza post-commit de archivos y credenciales. Después, `rmdir` de
   `projects/{id}` si quedó vacío (sin error si no).

Sin endpoints internos, sin commits por objeto: el estado intermedio nunca es visible.

---

## §11. IDs no reutilizables (FR-008)

**Hallazgo**: `INTEGER PRIMARY KEY` sin `AUTOINCREMENT` reutiliza `max(rowid)+1`: borrar el
último Project/Post/Media/Account y crear otro devuelve el mismo id → un deep link antiguo
abriría otro objeto, y `projects/{id}/` de Media se compartiría con el borrado.

**Decisión**: `sqlite_autoincrement=True` en `projects`, `accounts`, `contents`,
`publications`, `distribution_presets` y la nueva `library_folders`.

- Migración: `batch_alter_table(..., recreate="always",
  table_kwargs={"sqlite_autoincrement": True})`. Al copiar las filas con su id explícito,
  SQLite fija `sqlite_sequence` al máximo existente. Ids de filas borradas **antes** de 021
  por encima del máximo actual (p. ej. cuentas provisionales descartadas) podrían
  reutilizarse una vez; se acepta.
- `publications` se recrea con el patrón de 0006 (`_recreate_partial_index` tras el batch)
  para conservar los índices parciales; test que verifica en `sqlite_master` que el SQL de
  esas tablas contiene `AUTOINCREMENT` y que los índices conservan su `WHERE`.
- No se incluyen `publication_attempts` ni conexiones (sus ids no aparecen en URLs ni
  sobreviven a su padre).

**Alternativas descartadas**: UUID global (cambio masivo de API/frontend sin necesidad);
tabla de "tombstones" de ids (estado extra); conservar el id máximo en `automation_settings`
(manual, frágil).

---

## §12. Modelo de carpetas

**Decisión**: tabla `library_folders` (detalle en [data-model.md](data-model.md)):

- `name` (1–100 tras `strip()`), `name_key = normalize_key(name)` (NFKC+casefold, mismo
  criterio que Project y presets; `COLLATE NOCASE` solo pliega ASCII).
- Unicidad entre hermanas **en BD** con dos índices únicos parciales (SQLite trata NULL como
  distinto en UNIQUE): `(project_id, name_key) WHERE parent_id IS NULL` y `(parent_id,
  name_key) WHERE parent_id IS NOT NULL`.
- Mismo proyecto **en BD**: `UNIQUE(id, project_id)` + FK compuesta `(parent_id, project_id)
  → library_folders(id, project_id)` (SQLite no la aplica si `parent_id` es NULL: raíz).
  `contents` usa el mismo patrón: FK compuesta `(folder_id, project_id) →
  library_folders(id, project_id)`, de modo que un Media nunca puede estar en una carpeta de
  otro proyecto.
- Profundidad: columna `depth` con `CHECK(depth BETWEEN 1 AND 5)` y `CHECK((parent_id IS
  NULL) = (depth = 1))`. El servicio fija `depth = parent.depth + 1` dentro de `BEGIN
  IMMEDIATE`; sin mover carpetas, `depth` nunca cambia. Profundidad > 5 → `409
  folder_too_deep` (validación previa; el CHECK es la red).
- Ciclos: imposibles por construcción (el padre existe antes que el hijo y nunca cambia);
  además `depth` estrictamente creciente los excluye.
- "Unsorted" y "All media" no son filas: nunca colisionan.

**Razón**: todas las invariantes exigidas quedan en constraints de SQLite; la validación
Python solo da mensajes humanos.

**Alternativas descartadas**: `COLLATE NOCASE` (no pliega Unicode); índice de expresión
`COALESCE(parent_id, 0)` (válido, pero los índices parciales ya son el patrón del repo);
closure table / materialized path (innecesario sin mover carpetas).

---

## §13. Borrar carpeta (subárbol)

**Decisión**: CTE recursiva dentro de `BEGIN IMMEDIATE`:

```sql
WITH RECURSIVE subtree(id) AS (
  SELECT id FROM library_folders WHERE id = :id
  UNION ALL
  SELECT f.id FROM library_folders f JOIN subtree s ON f.parent_id = s.id
)
```

`UPDATE contents SET folder_id = NULL WHERE folder_id IN subtree`; `DELETE library_folders
WHERE id IN subtree` (orden hijos→padre por `depth DESC`, la FK compuesta es RESTRICT).
Nunca bloqueada; token con ids de subcarpetas y Media. No toca disco ni Posts.

---

## §14. API de Library

**Decisión** (contrato exacto en [contracts/api.md](contracts/api.md)):

- `GET /api/projects/{id}/library-folders` → árbol **plano** completo del proyecto: cada
  carpeta con `id, parent_id, name, depth, media_count` (directos) + `unsorted_count` y
  `total_count`. Una sola llamada alimenta raíz, subcarpetas, breadcrumb y selector.
- `POST /api/projects/{id}/library-folders` `{name, parent_id|null}`.
- `PATCH /api/library-folders/{id}` `{name}`.
- `GET /api/projects/{id}/contents?folder=<id>|unsorted` (sin parámetro = All media,
  comportamiento actual). Búsqueda y filtros siguen siendo locales en el frontend. `ContentRead`
  gana `folder_id`.
- `POST /api/projects/{id}/contents?folder_id=<id>` (import): destino de la subida; sin él →
  Unsorted.
- `POST /api/projects/{id}/contents/move` `{content_ids: [...], folder_id: <id>|null}`: uno o
  varios, un único `UPDATE` atómico; cualquier id ajeno/inexistente o carpeta de otro
  proyecto → 404 y nada cambia.

**Razón**: extiende el endpoint actual de Library en vez de duplicarlo; el árbol de carpetas
es pequeño y se pide entero.

**Alternativas descartadas**: `GET /library-folders/{id}/contents` y `/unsorted` separados
(tres endpoints para el mismo listado); `PATCH /contents/{id}` para mover (no cubre el
movimiento múltiple atómico).

---

## §15. Colas de limpieza diferida

**Decisión**: dos tablas mínimas, separadas:

- `pending_file_deletions(storage_path PK, created_at)`.
- `pending_credential_deletions(credential_ref PK, platform, account_id NULL sin FK,
  created_at)`.

Se **generaliza** `tiktok_credential_orphans` a `pending_credential_deletions` (la migración
copia sus filas con `platform='tiktok'` y elimina la tabla; `tiktok_connections` registra y
limpia con el helper genérico). Un único mecanismo, como pide la spec.

Ejecutores en `app/cleanup.py`:

- `run_file_cleanup(session_factory, storage, paths=None)`: idempotente; ruta referenciada →
  solo se borra la fila; inexistente → éxito; `OSError` → queda.
- `run_credential_cleanup(session_factory, targets, refs=None)`: `targets` es un mapa
  `platform → (store, credential_lock)` construido en `main.py` (cada módulo de conexión
  expone `credential_lock(account_id)`). Ref aún usada por alguna conexión → solo se borra la
  fila; `CredentialStoreUnavailable` → se detiene y conserva el resto; ausente → éxito.
- Nunca reviven objetos: solo borran archivos/secretos y su propia fila.

**Razón**: campos y ejecutores distintos; dos tablas pequeñas son más claras que una
polimórfica.

**Alternativas descartadas**: tabla genérica `pending_cleanups(kind, payload)` (JSON
opaco, validación débil); framework de jobs en segundo plano (fuera de alcance).

---

## §16. Limpieza en el arranque

**Decisión** (en `main.serve`, orden):

1. `storage.prepare()` → `sweep_orphan_clean_copies` (existente) → **`run_file_cleanup`**
   (síncrono: unlinks locales, acotado por el número de filas; cada fallo se loguea y
   continúa). Antes del scheduler.
2. `recover_interrupted_attempts` (existente).
3. **`run_credential_cleanup`** en un hilo daemon (como `media-sweep`), **solo si**
   `credential_probe.status() == "available"`. Con `locked`/`unavailable`/`unknown` no se
   toca el keyring: se loguea y las filas quedan. Sustituye a la llamada actual
   `tiktok_connections.cleanup_orphans` (que hoy toca el keyring sin sonda).
4. Post-commit de un borrado de Account/Project (acción del usuario): intento inmediato
   salvo que la sonda diga `locked` o `unavailable` (mismo criterio que hoy Disconnect, que
   ya accede al keyring en una acción del usuario). Tras el intento se reintenta también el
   resto de la cola.

**Razón**: el arranque nunca espera al keyring ni abre diálogos (020, §18); la limpieza
ocurre en el siguiente arranque con almacén disponible (SC-010).

**Limitación**: en backends sin sonda fiable (`unknown`: macOS, Windows, KWallet) la
limpieza de arranque no corre; la del borrado sí lo intenta. El host actual (Secret
Service) da `available`/`locked` reales.

---

## §17. Backup / restore (020)

**Verificado**: el backup copia la BD entera (API de backup de SQLite) y solo los archivos
referenciados por `contents`; el restore migra a head en el siguiente arranque
(`known_revision` + `run_migrations`).

- Carpetas, `folder_id` y colas pendientes viven en la BD → viajan sin cambiar el formato
  `.tar`.
- Backup pre-021 restaurado → migración 0019 → todo `folder_id = NULL` → Unsorted (FR-055).
- Filas de `pending_file_deletions` en un backup: sus archivos no están en el `.tar` (no
  referenciados) → al arrancar, "inexistente = éxito" → la fila desaparece.
- Filas de `pending_credential_deletions` en un backup: refs UUID que ninguna conexión
  restaurada usa (se borraron en la misma transacción) → el borrado del secreto es inocuo o
  ya ocurrió.
- Backup tomado **antes** de borrar una Account, restaurado después: la conexión vuelve con
  un `credential_ref` cuyo secreto ya no existe → los flujos existentes lo tratan como
  Reconnect required (020). Ningún secreto entra en el backup. Test dirigido que lo
  demuestra para una plataforma representativa.

---

## §18. Migración 0019 y datos existentes

**Decisión**: una sola revisión `0019_deletion_library_folders`:

1. Crear `library_folders`.
2. Recrear `projects`, `accounts`, `distribution_presets` con AUTOINCREMENT.
3. Recrear `contents` con AUTOINCREMENT + `folder_id` NULL + FK compuesta hacia
   `library_folders(id, project_id)`.
4. Recrear `publications` con AUTOINCREMENT; recrear sus índices parciales.
5. `temporary_media_objects.attempt_id` → nullable.
6. Crear `pending_file_deletions`, `pending_credential_deletions`; copiar
   `tiktok_credential_orphans`; eliminarla.

FK desactivadas durante la migración (engine de Alembic sin pragma, como en 0005/0006/0015).
No destructiva: todas las filas se conservan con su id. `downgrade` revierte carpetas,
`folder_id`, colas (re-crea `tiktok_credential_orphans` con las filas `tiktok`) y la
nulabilidad; AUTOINCREMENT se deja (inocuo).

Pruebas: BD de `main` sembrada en 0018 → upgrade → datos y ids intactos, Media en Unsorted,
`sqlite_sequence` correcto, índices parciales intactos, `compare_metadata` sin diferencias;
y restore de un backup pre-021 (test existente de restore extendido con un caso).

---

## §19. Frontend

**Decisión** (contrato en [contracts/ui.md](contracts/ui.md)):

- Rutas bajo `/p/:projectId/library`: raíz `library`, `library/unsorted[/:mediaId]`,
  `library/all[/:mediaId]`, `library/folders/:folderId[/:mediaId]`. El deep link existente
  `library/:mediaId` se mantiene y abre el detalle sobre la vista All media. Los segmentos
  estáticos tienen prioridad sobre `:mediaId` en react-router.
- `LibraryPage` se divide en `LibraryRoot` (entradas) y `MediaView` (la cuadrícula actual
  parametrizada por `scope`), compartiendo toolbar, import, grid y detalle existentes.
- Componentes compartidos nuevos: `DeleteConfirmDialog` (preview → Delete/Cancel, maneja
  bloqueo, `deletion_changed` y 404) y `FolderPicker` (árbol + Unsorted). Además
  `Breadcrumb`, `FolderNameDialog` (crear/renombrar) y un aviso breve tras navegar (`flash`
  vía estado de navegación, renderizado por el shell con `role="status"`). No existe hoy un
  sistema de toasts; se añade el mínimo.
- Delete en Post detail, Media detail/card (menú), Account detail, Project header; zona
  secundaria con estilo destructivo (FR-009).
- Select mode solo con Move.

**Alternativas descartadas**: query params (`?folder=`) para las vistas (peor como deep link
y para "atrás"); librería de toasts (dependencia nueva).

---

## §20. Móvil

- `DeleteConfirmDialog`: `Sheet` en teléfono / `Dialog` en md+ (patrón de `ActionDialog`);
  botones a ancho completo, Delete separado de Cancel, objetivos ≥ 44 px.
- `FolderPicker`: lista indentada con filas táctiles de altura completa (sin drag, sin
  hover); en teléfono, `Sheet` con scroll propio.
- `Breadcrumb`: una línea; en teléfono colapsa los niveles intermedios a "…" (menú) y
  mantiene `Library` y la carpeta actual; nunca scroll horizontal de página.
- Select/Move: botón explícito "Select"; checkbox visible por card; barra inferior fija con
  "Move (n)" y "Cancel"; sin long-press ni gestos ocultos.
- Acciones destructivas en menú "More" (`IconButton`) en cards y detalle.

---

## §21. Logs (FR-012)

`logger.info("Deleted %s %s (posts=%d, media=%d, accounts=%d)", kind, id, …)`. Nunca
nombres de archivo, rutas absolutas, handles ni refs de credencial.
