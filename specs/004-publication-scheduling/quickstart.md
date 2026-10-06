# Quickstart: validación de publicaciones y programación

**Feature**: `004-publication-scheduling` | **Fecha**: 2026-10-06

Guía para comprobar de extremo a extremo que la feature cumple su especificación. Contratos
en [contracts/api.md](contracts/api.md); reglas de datos y estados en
[data-model.md](data-model.md).

## Prerrequisitos

- Los mismos que la Feature 003 (Python 3.12+ con uv, Node.js 22+ con npm). No hay
  dependencias nuevas.
- Un proyecto **L4i4** con al menos una imagen o vídeo importado y cuentas activas de
  **Instagram**, **TikTok** y **X** (Features 002 y 003).

## 1. Checks automáticos (SC-009)

```bash
cd backend
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

Esperado: todo pasa.

## 2. Arranque

Igual que en la Feature 003 (mismas variables `AUTOPUBLISHER_DB_PATH` y
`AUTOPUBLISHER_MEDIA_DIR` si se usan datos aislados). Al arrancar, la migración `0003` crea
la tabla `publications` sin tocar proyectos, cuentas ni contenidos.

## 3. Flujo de referencia (SC-001)

1. Abrir **L4i4** → vista **Content** → seleccionar una imagen o vídeo.
2. Anotar el número de archivos almacenados:
   `ls "$AUTOPUBLISHER_MEDIA_DIR/projects/<id-de-L4i4>/" | wc -l`.
3. Pulsar **Prepare publications**: se listan solo las cuentas activas de L4i4. Marcar
   Instagram, TikTok y X, sin fecha, y confirmar. Aparece "Created 3 publications…".
4. Repetir el `ls` del paso 2: el número no cambia (SC-005).
5. Pulsar **Open queue**: las tres aparecen en **Unscheduled**.
6. Abrir Instagram → asignar una fecha futura (p. ej. mañana 18:00) → Save. Pasa a
   **Scheduled** con esa hora local.
7. Abrir TikTok → asignar otra fecha (pasado mañana 20:00). En la Queue, Scheduled muestra
   primero Instagram y después TikTok; X sigue en Unscheduled.
8. Abrir Instagram → Description → **Customize** → escribir un texto propio → Save. El
   detalle indica que la descripción está personalizada.
9. Volver a **Content**: la descripción global del contenido no ha cambiado. Editar el
   **título** global y volver a la Queue: las tres publicaciones muestran el nuevo título
   (ninguna lo sobrescribía) e Instagram conserva su descripción propia (SC-006).
10. Detener backend y frontend y volver a arrancarlos. Comprobar estados, horas locales,
    cuentas y la descripción personalizada de Instagram (SC-004).
11. Abrir X → **Cancel publication**. Aparece en **Cancelled**, sigue visible y ya no está
    activa.
12. Desde el contenido, **Prepare publications** vuelve a permitir seleccionar X (la
    cancelada no bloquea); Instagram y TikTok aparecen marcadas como ya activas y no
    seleccionables.

## 4. Reglas por API

Con el backend en marcha (contenido `1` en L4i4; cuentas `3` Instagram, `4` TikTok, `5` X;
cuenta `9` de otro proyecto):

```bash
API=http://127.0.0.1:8000/api
J='Content-Type: application/json'

curl -i -X POST $API/contents/1/publications -H "$J" -d '{"account_ids":[3]}'
# 409 duplicate si Instagram ya tiene una activa; no se crea nada

curl -i -X POST $API/contents/1/publications -H "$J" -d '{"account_ids":[9]}'
# 422 validation_error (field: account_ids) — "Account 9 does not belong to this project."

curl -i -X POST $API/contents/1/publications -H "$J" -d '{"account_ids":[9999]}'
# 422 validation_error (field: account_ids) — "Account 9999 not found."

curl -i -X PATCH $API/publications/1 -H "$J" -d '{"scheduled_at":"2000-01-01T10:00:00Z"}'
# 422 validation_error (field: scheduled_at) — fecha pasada

curl -i -X PATCH $API/publications/1 -H "$J" -d '{"scheduled_at":"2100-01-01T10:00"}'
# 422 validation_error (field: scheduled_at) — "Include a time zone."

curl -i -X PATCH $API/publications/1 -H "$J" -d '{"account_id":4}'
# 422 validation_error — campo no editable

curl -i -X PATCH $API/publications/1 -H "$J" -d '{"hashtags_override":[]}'
# 200: hashtags_override = [], hashtags = [] aunque el contenido tenga hashtags

curl -i -X PATCH $API/publications/1 -H "$J" -d '{"hashtags_override":null}'
# 200: vuelve a heredar los hashtags del contenido

curl -i -X DELETE $API/publications/1
# 405 method_not_allowed
```

Cancelación y reactivación con conflicto:

1. Cancelar la publicación de X (`POST $API/publications/<id>/cancel`).
2. Crear otra para X (`POST $API/contents/1/publications` con `[5]`) → `201`.
3. Reactivar la cancelada → `409 duplicate`.
4. Cancelar la nueva y reactivar la antigua → `200`, `unscheduled`.

## 5. Proyecto, cuenta y archivo no disponibles

- **Cuenta inactiva**: desactivar TikTok. En la Queue su publicación sigue visible con aviso
  "Account inactive"; programar o reactivar se rechaza (`account_inactive`); quitar la fecha,
  editar overrides y cancelar funcionan. En **Prepare publications** TikTok no aparece como
  seleccionable.
- **Proyecto inactivo**: desactivar L4i4. La Queue sigue consultable; **Prepare
  publications** muestra que hay que reactivar el proyecto; programar y reactivar se
  rechazan (`project_inactive`).
- **Archivo no disponible**: con datos aislados, borrar el archivo almacenado de un
  contenido con publicaciones. La Queue sigue mostrándolas con "File not available";
  cancelar y quitar la fecha funcionan; crear, programar o reactivar se rechazan con
  "The media file of this content is not available." (`media_unavailable`).

## 6. Sin ejecución automática (SC-007)

Programar una publicación para dentro de 2 minutos y esperar a que pase la hora: sigue
`scheduled`, no ocurre nada y la Queue la marca como **Overdue**.

## 7. Rendimiento (SC-002, SC-008)

- Preparar publicaciones de un contenido para tres cuentas, desde su detalle hasta verlas en
  la Queue, lleva menos de 1 minuto.
- Con ≥ 200 publicaciones en un proyecto, la Queue se muestra y es utilizable en menos de
  2 segundos.
