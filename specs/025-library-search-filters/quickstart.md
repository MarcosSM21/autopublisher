# Quickstart: validar Feature 025 (Library Search, Filters & Organization)

Guía de validación. El contrato está en [contracts/ui.md](contracts/ui.md) y las decisiones en
[research.md](research.md).

## Prerrequisitos

- Rama `025-library-search-filters`.
- Validar sobre una instancia de prueba, no sobre la instalación real: copia con
  `AUTOPUBLISHER_CONFIG` propio y keyring que falla, como en las features anteriores.
- Backend y frontend arrancados en segundo plano (ver README), con un proyecto que tenga:
  - imágenes y vídeos, alguno con title acentuado ("Café de verano"), alguno sin title, alguno
    con hashtags y alguno con description;
  - al menos una carpeta con una subcarpeta, y Media en Unsorted;
  - un Media con solo un Post cancelado, otro con un borrador y otro publicado;
  - Media importados en distintas fechas. Si todos son de hoy, valida "Last 7 days" con la
    combinación vacía o en los tests unitarios.

## Tests dirigidos (por checkpoint)

```bash
cd frontend
npx vitest run src/pages/library/library-query.test.ts src/pages/library/library-helpers.test.ts   # A
npx vitest run src/pages/library/search-filters.test.tsx src/pages/library/library.test.tsx        # B, C, D
npx vitest run src/pages/library/move.test.tsx src/pages/library/bulk-delete.test.tsx src/pages/library/folders.test.tsx  # B/C riesgo directo
npx vitest run src/pages/publish/publish-page.test.tsx src/pages/publish/usePublishTask.test.tsx  # C
```

Cierre (una sola vez, en el checkpoint E):

```bash
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build
git diff --check
```

Scripts de `frontend/package.json`. `build` ya incluye `tsc -b`. Sin suites completas
en local.

## Escenarios manuales

1. **Búsqueda** (US1): en All media, escribe `cafe verano`, luego `VERANO café` y luego
   `#summer`.
   - Esperado: aparece el Media; `cafe invierno` no encuentra nada; la URL muestra `?q=…` y back
     sale de la Library sin pasar por cada tecla.
2. **Filtros combinados** (US2): Type = Videos, Usage = Unused, Imported = Last 30 days.
   - Esperado: solo los vídeos sin Posts no cancelados; el Media con solo un Post cancelado sale
     en Unused; el del borrador, en Used.
   - Quita el chip "Unused": solo cambia esa dimensión.
   - `Clear all`: se conserva la búsqueda.
3. **Orden** (US5): Name A–Z con "a2" y "a10" → "a2" va primero. Newest coincide con el orden
   anterior a la feature.
4. **URL** (US4): copia la URL con búsqueda, filtros y orden, ábrela en otra pestaña y recarga.
   - Esperado: mismo resultado.
   - `?type=gif&sort=size` → defaults, sin error.
5. **Detail y Publish** (US4):
   - Abre un Media desde una carpeta filtrada y ciérralo a 1300, 900 y 375 px. Esperado: mismos
     params y foco en la card.
   - Entra en Publish y pulsa Continue; luego "Back to media". Esperado: misma carpeta y mismos
     params.
   - Entra en Publish desde Posts: "Back to media" lleva al detail sobre All media.
6. **Deep link oculto y edición**:
   - Abre `…/library/all/<id de imagen>?type=videos`. Esperado: el detail se abre y la card no
     está en el grid; al cerrar, el foco va al contenido principal.
   - Busca `summer`, abre un Media y quita "summer" de su title. Esperado: el detail sigue
     abierto y al cerrar la card ya no está.
7. **Selección** (US3): Select, marca 3 y escribe una letra.
   - Esperado: "0 selected" y Move/Delete deshabilitados.
   - Marca 2 y cambia solo Sort: siguen marcados.
   - Marca 2 y pulsa back del navegador tras un cambio de filtro: la selección se vacía.
8. **Search all media** (US6): en la carpeta, busca algo que solo está en otra.
   - Esperado: estado vacío con `Clear search` y `Search all media`; este último lleva a All media
     con la misma consulta.
   - En All media no aparece.
9. **Estados vacíos** (US8): solo búsqueda, solo filtros, ambos, carpeta vacía y Library vacía.
   - Esperado: según la matriz de [contracts/ui.md §8](contracts/ui.md).
10. **Móvil** (US7) a 375 y 390 px:
    - Búsqueda a ancho completo; `Filters · N` + Sort en una fila; chips desplazables; sin scroll
      horizontal; con el panel cerrado, los controles ocupan como mucho ~1/3 de la altura.
    - El panel Filters aplica al momento; `Done` y Escape devuelven el foco a `Filters`.
11. **Escritorio** a 768, 1024 y 1280 px (con y sin detail lateral):
    - Controles inline, sin panel; dos filas como máximo a 1024 con la lista a ancho completo.
12. **Regresiones**: import con filtros activos (el Media nuevo puede quedar fuera y el panel de
    import enlaza a su detail), Move y Delete individual y en bloque, y crear, renombrar y
    borrar carpetas, todo con params activos.
