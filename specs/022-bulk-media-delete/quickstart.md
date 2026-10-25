# Quickstart — validar Feature 022

Guía de validación. Contratos: [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md).

## 1. Tests dirigidos

```bash
cd backend
uv run pytest tests/test_delete_media_selection.py                     # A
uv run pytest tests/test_delete_media.py tests/test_delete_project.py \
              tests/test_media_move.py                                 # A: regresión del refactor
cd ../frontend
npx vitest run src/pages/library src/components/DeleteConfirmDialog    # B
```

## 2. Validación manual

Sobre una instancia de prueba (copia con `AUTOPUBLISHER_CONFIG` propio y keyring de fallo),
backend y frontend en segundo plano.

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Folder: Select → marcar 3 Media (uno con Post Scheduled, uno con Post Published) → Delete → confirmar | Un solo diálogo con resumen agregado; las 3 tarjetas desaparecen; contador de la carpeta y All media bajan en 3; los Posts desaparecen de Posts y Home |
| 2 | Unsorted y All media: lo mismo con 2 Media | Igual; si la vista queda vacía, su empty state |
| 3 | Select con 0 marcados | Move y Delete deshabilitados |
| 4 | Abrir confirmación, crear un Post para uno de los Media en otra pestaña, confirmar | Aviso "Something changed", resumen nuevo, hace falta otro Delete |
| 5 | Abrir confirmación, borrar uno de los Media en otra pestaña, confirmar | Diálogo cerrado, selección sin ese Media, aviso breve; nada más borrado |
| 6 | Un Media con Post publicándose en la selección | Blocker de publicación; solo Close |
| 7 | Teléfono (LAN): seleccionar 2, Delete | Barra en dos filas sin desbordar; Sheet legible; borrado correcto |
| 8 | Borrado individual de un Media y Move múltiple | Igual que antes |

## 3. Cierre (una vez)

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ../frontend && npm run lint && npm run typecheck && npm run build
git diff --check
```

## Validation results (2026-10-25)

Throwaway instance on port 8020: copy of the real data (SQLite backup from a read-only
connection, media copied), own `AUTOPUBLISHER_CONFIG`, fail keyring, frontend built
outside `frontend/dist`. Fixtures: folders **Bulk test** (5 Media, published posts, a
draft and a manual scheduled post) and **Archive** (2 Media); 17 Media in Unsorted with
two extra drafts. The real installation on `:8000` was not touched.

- T022 desktop (scenarios 1–6, 8): confirmed by the user. Bulk Delete works in Folder,
  Unsorted and All media.
- T023 phone over LAN (scenario 7): confirmed by the user.

The instance and its data were removed afterwards; the temporary ufw rule for 8020 is
removed by the user.
