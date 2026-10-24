# Quickstart — validar Feature 021

Guía de validación (no de implementación). Contratos: [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md). Modelo: [data-model.md](data-model.md).

## Prerrequisitos

```bash
cd backend && uv sync
cd ../frontend && npm ci
```

## 1. Tests dirigidos por bloque (durante la implementación)

Ejecutar solo el bloque modificado (nombres orientativos; se fijan en tasks):

```bash
cd backend
uv run pytest tests/test_migrations.py -k "0019 or autoincrement or folder"   # A: esquema
uv run pytest tests/test_write_transaction.py tests/test_content_file_guard.py # A: base
uv run pytest tests/test_delete_concurrency.py                               # A/B: carreras
uv run pytest tests/test_delete_post.py                                      # B
uv run pytest tests/test_delete_media.py tests/test_cleanup_files.py         # C
uv run pytest tests/test_delete_account.py tests/test_cleanup_credentials.py # D
uv run pytest tests/test_connection_late_results.py                          # D: tardíos
uv run pytest tests/test_delete_project.py                                   # D
uv run pytest tests/test_library_folders.py tests/test_media_move.py         # E
uv run pytest tests/test_restore.py -k "pre_021 or deleted"                  # backup
cd ../frontend
npx vitest run src/pages/library src/components/DeleteConfirmDialog          # F/G
```

## 2. Escenarios manuales (servidores en segundo plano)

```bash
cd backend && uv run uvicorn app.main:app --reload     # :8000
cd frontend && npm run dev                              # :5173
```

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Post Scheduled · automatic → Delete → Confirm; reiniciar backend; esperar a que pase su hora | No aparece en Posts/Calendar/Home; ningún intento creado. |
| 2 | Post Published → Delete | Resumen: "only removed from AutoPublisher… not affected"; desaparece de History. |
| 3 | Media con Remove metadata + 1 draft + 1 publicado → Delete | Resumen "1 unpublished post and 1 published post…"; Media y Posts desaparecen; original y `.clean` ya no están en `media/projects/{id}/`. |
| 4 | Re-subir el mismo archivo | Se importa como nuevo (no "duplicate"). |
| 5 | Library root sin carpetas | Unsorted, All media, New folder; sin cuadrícula. |
| 6 | Crear "Cybersecurity" › "DDoS", "2FA"; renombrar "2FA" → "MFA"; crear "lux" junto a "Lux" | Breadcrumb `Library / Cybersecurity`; rename persiste; colisión rechazada con el mensaje exacto. |
| 7 | Select 3 en Unsorted → Move → Lux | Salen de Unsorted, aparecen en Lux; ningún archivo cambia en disco. |
| 8 | Borrar "Cybersecurity" con 5 + 3 Media | "1 subfolder… 8 media items will move to Unsorted. No media is deleted."; 8 en Unsorted. |
| 9 | Cuenta con 1 draft, 1 programado, 2 publicados → Delete account | Resumen con handle; cuenta y 4 Posts fuera; preset conservado (vacío); secreto fuera del keyring. |
| 10 | Iniciar OAuth de una cuenta, borrarla antes de completar en el navegador, completar | Callback "Authorization not valid"; ninguna conexión/cuenta reaparece; ningún secreto nuevo en el keyring. |
| 10b | Abrir el diálogo Delete de una cuenta con OAuth en curso; en otra pestaña añadir un Post; confirmar | `deletion_changed`; el OAuth sigue siendo válido y puede completarse (nada se invalidó). |
| 11 | Project con contenido → Delete project | Vuelve a Home; crear proyecto nuevo → id nuevo, Library vacía. |
| 12 | Abrir deep link de un Post/Media/carpeta borrado | "not found" con vuelta al contenedor. |
| 13 | Preview abierto en tab A; en tab B añadir un Post al Media; confirmar en A | `deletion_changed`; el diálogo muestra el resumen nuevo. |
| 14 | Móvil (LAN o DevTools 360 px): root, carpeta profunda, picker, Select/Move, diálogos | Sin scroll horizontal; todo táctil. |

## 3. Backup / restore

```bash
cd backend
uv run python -m app.cli backup             # tras organizar carpetas
# borrar una Account; luego (con el servicio parado):
uv run python -m app.cli restore <archivo>
```

Esperado: carpetas y ubicaciones restauradas; la cuenta borrada reaparece como
"Reconnect required" (su secreto no se restaura). Un backup pre-021 restaurado arranca con
todo en Unsorted.

## 4. Cierre de feature (una vez, antes del PR)

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd ../frontend && npm run lint && npm run typecheck && npm run build
git diff --check
```

Suites completas: solo en la CI del PR.
