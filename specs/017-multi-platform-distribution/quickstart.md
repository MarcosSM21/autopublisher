# Quickstart: validación de Distribución multiplataforma y presets

**Feature**: [spec.md](spec.md) · **Contratos**: [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md) · **Modelo**: [data-model.md](data-model.md)

## Prerrequisitos

- Backend y frontend arrancados como en features anteriores (`uv run uvicorn …`,
  `npm run dev`), con la migración `0016` aplicada (`uv run alembic upgrade head`).
- Un proyecto con al menos: una cuenta de YouTube, una de Instagram y una de Telegram
  activas; una cuenta extra inactiva; un asset de vídeo con descripción y hashtags.
- No hace falta publicar de verdad: Prepare/Schedule no contactan con plataformas.

## Tests dirigidos (durante la implementación)

```bash
cd backend
uv run pytest tests/test_publications_create.py tests/test_distribution_presets.py \
  tests/test_migrations.py
cd ../frontend
npx vitest run src/components/Distribute.test.tsx src/components/PublicationDetail.test.tsx \
  src/components/ContentDetail.test.tsx
```

Sin regresiones de publishers ni scheduler (no cambian). Las suites completas corren en la CI
del PR.

## Checks antes del PR (una sola vez)

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd ../frontend && npm run lint && npm run format:check && npm run typecheck && npm run build
cd .. && git diff --check
```

## Validación manual

### A. Distribute básico (US1)

1. Abrir el asset → **Distribute**. Las cuentas activas aparecen como casillas; la inactiva no.
2. Common text está prellenado con la descripción y hashtags del asset.
3. Marcar YouTube + Instagram + Telegram, cambiar la descripción común, elegir **Schedule** con
   una fecha futura → **Create 3 publications**.
4. Esperado: panel de resultado con 3 filas `Scheduled`, misma fecha; en cada Publication la
   descripción efectiva es la común editada; el asset conserva su descripción original.

### B. Customize (US2)

1. Distribute de nuevo sobre otro asset; marcar YouTube e Instagram.
2. Customize en YouTube: hay campo **Title** (prellenado con el título del asset); en Instagram no.
3. Cambiar título y hashtags de YouTube; dejar Instagram sin tocar → crear.
4. Esperado: YouTube con título/hashtags propios y descripción común; Instagram con la común.
5. Repetir personalizando y pulsando **Discard customization** → el destino hereda Common/Content.
6. Borrar por completo la descripción común → crear → la descripción efectiva es vacía (no la del asset).

### C. Atomicidad (US1-5, US2-6)

1. Con el formulario abierto, desactivar una de las cuentas seleccionadas en otra pestaña → crear.
2. Esperado: no se crea nada; la fila de esa cuenta muestra el motivo; lo introducido se conserva.
3. Vía API: enviar `targets` con una cuenta no incluida en `account_ids` → 422
   `targets.<id>`, cero Publications.

### D. Panel de resultado (US3)

1. En el panel: cada destino es una fila compacta (sin preview, metadata ni intentos). La
   fila de YouTube muestra "Needs …" (p. ej. made for kids sin definir) con "Platform
   options" abierto; Telegram muestra **Ready** y no tiene opciones.
2. Completar las opciones de YouTube en la fila → la cabecera pasa a **Ready**.
3. En una fila `Scheduled`, **Enable auto-publish** usa la confirmación existente.
4. **Publish now** abre el diálogo existente solo para esa Publication; la fila pasa por
   Publishing → Published sin recargar. No existe "Publish all".
5. Abrir la misma Publication desde la cola: el detalle muestra opciones, Publish now y
   auto-publish igual que antes de la feature (bloques compartidos).

### E. `PUBLISHED` no bloquea (US4)

1. Con un asset que tenga una Publication `Published` en Instagram y otra `Scheduled` en YouTube:
   Distribute → Instagram seleccionable; YouTube deshabilitada con "Already has an active
   publication".

### F. Presets (US5)

1. Marcar YouTube + Instagram + la cuenta de Telegram → **Manage presets → Save selection as
   preset** "Short video".
2. Crear otro con el nombre "short video" → error de nombre duplicado.
3. Desactivar la cuenta de Telegram; abrir Distribute en un asset donde YouTube tenga una
   Publication activa; aplicar "Short video" → solo Instagram seleccionada y aviso
   "2 destinations skipped" con motivos. El preset sigue teniendo 3 cuentas.
4. Renombrar el preset, quitarle una cuenta, y eliminarlo; cuentas y Publications intactas.
