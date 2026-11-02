# Implementation Plan: Send to Phone

**Branch**: `029-send-to-phone` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/029-send-to-phone/spec.md`

## Summary

Un botón `Send to phone` en Media Detail llama a `POST /api/contents/{id}/send-to-phone`.
El backend, dentro del guard existente `ContentFileGuard.sanitizing`, resuelve el publish
file con `resolve_publish_file(verify=True)` y ejecuta
`tailscale file cp --name <original_filename> <file> <target>:` con argumentos
estructurados y timeout de 5 minutos. Responde 204 o un error `{code, message}` sin rutas.
Sin tablas, sin worker, sin estado persistente.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript + React (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy (existentes); CLI `tailscale` del host (externa,
opcional)

**Storage**: N/A (no hay cambios de esquema)

**Testing**: pytest con `subprocess.run`/`shutil.which` sustituidos; Vitest + `test-fake-api.ts`

**Target Platform**: Linux local (equipo del usuario con Tailscale instalado)

**Project Type**: web application (backend + frontend)

**Performance Goals**: N/A; la duración la marca la red. Timeout fijo de 300 s.

**Constraints**: sin shell, sin stderr en logs ni en UI, sin rutas en mensajes; endpoint
síncrono (`def`, se ejecuta en el threadpool de FastAPI y no bloquea el event loop)

**Scale/Scope**: 1 usuario, 1 móvil, 1 archivo por petición

## Constitution Check

| Principio | Estado |
|-----------|--------|
| I. Simplicidad | ✅ Un módulo pequeño, un endpoint, un botón; reutiliza `resolve_publish_file` y `ContentFileGuard`; sin locks ni tablas nuevas. |
| II. Spec-Driven | ✅ Alcance = spec aprobada (FR-001…FR-010). |
| III. Modularidad | ✅ Taildrop no es una plataforma de publicación: va en su propio módulo `app/send_to_phone.py`, fuera de los publishers y del núcleo de publicación. |
| IV. Seguridad | ✅ Sin secretos; el target es un nombre de host en una variable de entorno; logs sin stderr ni rutas (FR-009). |
| V. Calidad | ✅ Tests backend por cada error y por la elección del archivo; tests UI de estados. |
| VI. Git/Docs | ✅ Se documenta `TAILSCALE_PHONE_TARGET` en `docs/deployment.md` y README. |

Re-check tras el diseño: sin cambios, sin violaciones. Complexity Tracking vacío.

## Project Structure

### Documentation (this feature)

```text
specs/029-send-to-phone/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api.md
└── tasks.md             # /speckit-tasks (no creado aún)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── send_to_phone.py        # NUEVO: router + envío (guard → resolve → tailscale)
│   └── main.py                 # include_router
└── tests/
    └── test_send_to_phone.py   # NUEVO

frontend/src/
├── api.ts                      # sendToPhone(contentId)
├── test-fake-api.ts            # ruta POST /contents/{id}/send-to-phone + resultado configurable
└── pages/library/
    ├── useSendToPhone.ts       # NUEVO: hook (mismo patrón que useCleanMetadata)
    ├── MediaDetail.tsx         # botón + mensajes
    └── send-to-phone.test.tsx  # NUEVO

docs/deployment.md, README.md   # TAILSCALE_PHONE_TARGET
```

**Structure Decision**: aplicación web existente (`backend/` + `frontend/`). Un único módulo
backend nuevo que sigue el patrón de `asset_library.py` (router + dependencia del guard en
`app.state.content_file_guard`).

## Checkpoints

- **A — Backend**: endpoint + tests dirigidos (`test_send_to_phone.py`): éxito con original,
  éxito con copia limpia, argumentos exactos (`--name`, `target:`), sin target, sin
  `tailscale`, archivo ausente/dañado, exit code ≠ 0, timeout, conflicto con el guard
  (limpieza/borrado en curso y viceversa), y que ni stderr ni rutas aparecen en logs ni en la
  respuesta.
- **B — UI + validación real**: botón en Media Detail con tests (estados `Sending…`,
  `Sent to phone`, error + reintento), docs, y un envío real al móvil desde una instancia de
  validación (ver [quickstart.md](quickstart.md)).

Tamaño esperado: ~9–10 tareas.

## Complexity Tracking

Sin violaciones.
