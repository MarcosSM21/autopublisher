# Data Model: publicación manual real de vídeos en YouTube

**Feature**: `006-youtube-manual-publishing` | **Fecha**: 2026-10-07

Una sola migración nueva, `0005_publication_execution`, que:

1. amplía `publications` (estados, `published_at`, índice de duplicados);
2. crea `publication_attempts` (núcleo, genérica);
3. crea `youtube_publication_options` (adaptador YouTube).

Todos los nombres de restricciones e índices siguen la convención `NAMING_CONVENTION` de
`app/models.py`, para que el test de deriva modelo ↔ migraciones existente los cubra.

---

## 1. `publications` (existente, Feature 004): cambios

### Estados

`PublicationStatus` (StrEnum, sincronizado con `frontend/src/types.ts`):

| Valor | Significado |
|-------|-------------|
| `unscheduled` | Sin fecha, no ejecutada (sin cambios) |
| `scheduled` | Con fecha, no ejecutada; la fecha nunca dispara nada (sin cambios) |
| `cancelled` | Cancelada (sin cambios) |
| `publishing` | **Nuevo**. Existe exactamente un intento `running` |
| `published` | **Nuevo**. YouTube aceptó la subida, el video ID se obtuvo y se persistió |
| `failed` | **Nuevo**. El último intento terminó sin éxito |

### Columnas nuevas

| Columna | Tipo | Notas |
|---------|------|-------|
| `published_at` | `UTCDateTime`, nullable | Instante en que se persistió el éxito. No nulo si y solo si `status = 'published'` |

`scheduled_at` se conserva en `publishing`/`published`/`failed` como dato histórico.

### Restricciones (recreadas en la migración, modo *batch* de SQLite)

- `ck_publications_status_valid`:
  `status IN ('unscheduled','scheduled','cancelled','publishing','published','failed')`.
- `ck_publications_status_matches_schedule`:
  `status IN ('cancelled','publishing','published','failed')
   OR (status = 'scheduled' AND scheduled_at IS NOT NULL)
   OR (status = 'unscheduled' AND scheduled_at IS NULL)`.
- `ck_publications_published_at_matches_status` (nueva):
  `(status = 'published') = (published_at IS NOT NULL)`.
- `uq_publications_active_content_account` (índice único parcial, **cambia su condición**):
  `(content_id, account_id) WHERE status NOT IN ('cancelled', 'published')`.
  `publishing` y `failed` cuentan como activas (spec FR-009).

El índice `ix_publications_project_id_status_scheduled_at` no cambia.

### Transiciones

```text
             ┌────────────── Publish now (preflight OK) ──────────────┐
unscheduled ─┤                                                        ▼
scheduled  ──┘                                                   publishing
failed ───────── Publish now (preflight OK; ack si ambiguo) ──────────┘
                                                                  │      │
                                    video ID válido y persistido ─┘      └─ fallo / interrupción
                                                                  ▼            ▼
                                                              published      failed

unscheduled / scheduled / failed ── cancel ──▶ cancelled ── reactivate ──▶ scheduled / unscheduled
```

- Ninguna transición ocurre por el paso del tiempo (FR-004).
- `publishing` y `published` no admiten `cancel`, edición ni `Publish now`.
- Matriz completa de edición por estado: [research.md §13](research.md#13-política-de-failed-edición-y-duplicados).

## 2. `publication_attempts` (nueva, núcleo genérico)

Una ejecución real de una publicación. Sin lógica de YouTube: los datos específicos de la
plataforma van en `submitted`/`details` como JSON no sensible que el núcleo no interpreta.

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | `INTEGER` PK | |
| `publication_id` | FK → `publications.id` (`RESTRICT`) | Varios intentos por publicación a lo largo del tiempo |
| `platform` | `String(20)` | Copia de la plataforma de la cuenta en el momento del intento |
| `status` | `String(20)` | `running` \| `succeeded` \| `failed` |
| `stage` | `String(20)` | `preparing` \| `uploading` \| `final_chunk` \| `done` (research §5) |
| `started_at` | `UTCDateTime` | |
| `finished_at` | `UTCDateTime`, nullable | No nulo si y solo si `status != 'running'` |
| `progress_updated_at` | `UTCDateTime`, nullable | Última escritura de progreso |
| `bytes_sent` | `INTEGER` | `0 ≤ bytes_sent ≤ total_bytes` |
| `total_bytes` | `INTEGER` | Tamaño del archivo al empezar |
| `error_code` | `String(40)`, nullable | Código seguro (research §6); no nulo si y solo si `status = 'failed'` |
| `error_message` | `String(500)`, nullable | Mensaje fijo y comprensible, nunca texto de Google |
| `outcome_determined` | `BOOLEAN`, nullable | `NULL` mientras `running`; `true` en `succeeded`; en `failed`, `false` si el resultado remoto es incierto |
| `external_id` | `String(100)`, nullable | Video ID de YouTube; solo en `succeeded` (no se conserva en `result_not_saved`, research §7) |
| `external_url` | `String(500)`, nullable | URL directa al vídeo; solo en `succeeded` |
| `submitted` | `JSON` | Instantánea no sensible de lo enviado (§2.1) |
| `details` | `JSON` | Resultado no sensible específico de la plataforma (§2.2) |
| `warnings` | `JSON` | Lista `[{code, message}]`, p. ej. `privacy_differs` |

`progress` no se almacena: se calcula como `bytes_sent / total_bytes` (1.0 si
`total_bytes = 0`).

### Restricciones e índices

- `ck_publication_attempts_status_valid`: `status IN ('running','succeeded','failed')`.
- `ck_publication_attempts_stage_valid`:
  `stage IN ('preparing','uploading','final_chunk','done')`.
- `ck_publication_attempts_finished_matches_status`:
  `(status = 'running') = (finished_at IS NULL)`.
- `ck_publication_attempts_error_matches_status`:
  `(status = 'failed') = (error_code IS NOT NULL)`.
- `ck_publication_attempts_bytes_valid`:
  `bytes_sent >= 0 AND total_bytes >= 0 AND bytes_sent <= total_bytes`.
- `uq_publication_attempts_running`: índice único parcial `(publication_id) WHERE status =
  'running'` (research §8).
- `ix_publication_attempts_publication_id_started_at`: historial ordenado.

### Prohibido almacenar (FR-037)

Access/refresh tokens, cabeceras `Authorization`, la URI de sesión resumible (ni su
`upload_id`), respuestas completas de Google. `submitted`, `details` y `warnings` los
construye el adaptador con una lista blanca de claves.

### 2.1 `submitted` (YouTube)

```json
{
  "title": "Cybersecurity basics",
  "description": "Intro to threat models.\n\n#cyber #security",
  "privacy_status": "private",
  "made_for_kids": false,
  "contains_synthetic_media": false,
  "notify_subscribers": false,
  "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
  "channel_title": "Cyber Channel",
  "file_name": "intro.mp4",
  "file_size": 10485760
}
```

### 2.2 `details` (YouTube)

```json
{
  "privacy_status": "private",
  "upload_status": "uploaded",
  "processing_status": "processing"
}
```

Claves opcionales: solo las que YouTube devuelva.

### Ciclo de vida del intento

```text
(created) running/preparing ──▶ running/uploading ⇄ running/final_chunk
                                        │                     │
            fallo determinado ──────────┤                     ├── video ID persistido ──▶ succeeded/done
                                        ▼                     ▼
                         failed (outcome_determined=true)    failed (outcome_determined=false)
```

- Reanudaciones dentro de la misma sesión: el intento no cambia de fila (FR-035).
- Recuperación de arranque: `running` → `failed`, `interrupted`,
  `outcome_determined = (stage != 'final_chunk')` (research §9).
- `result_not_saved`: `failed`, `outcome_determined = false`, sin `external_id` ni
  `external_url` (research §7).
- `final_chunk` → `uploading` solo si YouTube confirma que la subida está incompleta
  (`308` con `Range` menor que el total, research §5).

### Reglas derivadas

- **Requiere revisión manual**: `status = 'failed' AND outcome_determined = false`.
- **Confirmación extra para publicar** (research §13): el intento más reciente
  (`started_at`, `id`) de cualquier publicación con el mismo `content_id` + `account_id`
  requiere revisión manual.

### Escrituras de progreso

- `bytes_sent` y `progress_updated_at` se escriben como máximo una vez por segundo y en
  cada confirmación `308`, en una sesión corta propia del hilo.
- **Write-ahead** (research §5): `stage = 'final_chunk'` se escribe y se confirma (commit)
  **antes** de enviar el último fragmento. Si ese commit falla, el último fragmento no se
  envía.
- El resultado remoto (`external_id`, `external_url`, `details`, `status = 'succeeded'`,
  `stage = 'done'`) y `publications.status = 'published'` + `published_at` se escriben en
  **una única transacción**, inmediatamente después de recibir la respuesta final.

## 3. `youtube_publication_options` (nueva, adaptador YouTube)

| Columna | Tipo | Notas |
|---------|------|-------|
| `publication_id` | PK + FK → `publications.id` (`RESTRICT`) | Como máximo una fila por publicación |
| `privacy_status` | `String(10)` | `private` (por defecto) \| `unlisted` \| `public` |
| `made_for_kids` | `BOOLEAN`, nullable | `NULL` = sin declarar |
| `contains_synthetic_media` | `BOOLEAN`, nullable | `NULL` = sin declarar |
| `notify_subscribers` | `BOOLEAN` | `false` por defecto |
| `updated_at` | `UTCDateTime` | |

- `ck_youtube_publication_options_privacy_valid`:
  `privacy_status IN ('private','unlisted','public')`.
- Sin fila = `{private, NULL, NULL, false}`. Las publicaciones creadas antes de esta feature
  no necesitan backfill.
- Solo existe para publicaciones cuya cuenta es YouTube (validado en el endpoint).
- Editable solo si la publicación está `unscheduled`, `scheduled` o `failed` (research §13).
- **Completa** si `made_for_kids IS NOT NULL AND contains_synthetic_media IS NOT NULL`.
- `Publication` no tiene relación inversa hacia esta tabla (igual que `Account` con
  `youtube_connections`).

## 4. Entidades efímeras (no persistidas)

- **Sesión de subida**: URI de sesión, offset confirmado, fragmento actual. Vive en
  variables locales del hilo de ejecución.
- **`PreparedPublication`** (núcleo común, genérica): resultado del preflight con
  información independiente de la plataforma:
  - `publication_id` (y los ids que necesite el núcleo);
  - `file_path` (ruta al archivo multimedia existente);
  - `total_bytes` (tamaño del archivo);
  - `submitted` (instantánea no sensible de la metadata enviada, §2.1);
  - `payload`: objeto **opaco** construido e interpretado exclusivamente por el adaptador.

  El núcleo nunca lee `payload`. En YouTube, `payload` contiene el MIME, el recurso `video`
  (snippet + status) y `notify_subscribers`; ninguno de esos datos es un campo común. Ni
  `PreparedPublication` ni su `payload` contienen tokens: el adaptador pide las credenciales
  justo antes de cada petición.
- **`PublicationRunner`**: hilos vivos por `attempt_id`, `stop_event`.

## 5. Sin cambios

- `contents`: el archivo se lee sin modificarse (FR-003).
- `accounts`, `projects`: sin cambios de esquema.
- `youtube_connections`: sin cambios de esquema; sus endpoints `authorize` y `disconnect`
  comprueban además que no haya publicaciones `publishing` de la cuenta.

## 6. Migración `0005_publication_execution`

1. `batch_alter_table("publications")`: añadir `published_at`; recrear
   `ck_publications_status_valid` y `ck_publications_status_matches_schedule`; crear
   `ck_publications_published_at_matches_status`.
2. Eliminar y recrear `uq_publications_active_content_account` con la nueva condición
   (después del modo *batch*, que recrea la tabla).
3. Crear `publication_attempts` con sus restricciones e índices.
4. Crear `youtube_publication_options`.

Datos existentes: todas las publicaciones siguen en `unscheduled`/`scheduled`/`cancelled`
con `published_at = NULL`, así que cumplen las nuevas restricciones sin transformación.
`downgrade` revierte en orden inverso (solo válido si no hay filas con estados nuevos).
