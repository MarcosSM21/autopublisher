# Quickstart: validar Feature 026 (Brand & Motion Polish)

Guía de validación. El contrato está en [contracts/ui.md](contracts/ui.md) y las decisiones en
[research.md](research.md).

## Prerrequisitos

- Rama `026-brand-motion-polish`.
- Instancia de prueba, no la instalación real: copia de la base de datos con
  `AUTOPUBLISHER_CONFIG` propio y keyring que falla, como en las features anteriores.
- Backend y frontend arrancados en segundo plano, con un proyecto que tenga:
  - Media en una carpeta y en Unsorted;
  - Posts programados en la semana actual del Calendar;
  - una password activa (para ver Login y Auth loading).
- Chrome con CDP (como en Feature 025).

## Tests dirigidos (por checkpoint)

```bash
cd frontend
npx vitest run src/pages/login/login.test.tsx src/auth.test.tsx src/shell/shell.test.tsx src/ui/motion-policy.test.ts   # A
npx vitest run src/ui/published-emphasis.test.tsx src/pages/posts/posts.test.tsx src/pages/posts/post-detail.test.tsx src/pages/publish/final-action.test.tsx src/pages/publish/usePublishTask.test.tsx   # B
npx vitest run src/pages/library/import-highlight.test.tsx src/pages/library/library.test.tsx src/pages/library/search-filters.test.tsx   # C
npx vitest run src/pages/posts/calendar-view.test.tsx src/pages/posts/action-dialog.test.tsx        # D
```

Los nombres de los tests nuevos (`motion-policy`, `published-emphasis`, `import-highlight`) son
orientativos; `/speckit-tasks` los fija.

Cierre, una sola vez en el checkpoint E:

```bash
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build
git diff --check
```

Sin suites completas en local: las ejecuta la CI del PR. Sin cambios de backend.

## Verificación con CDP

### Utilidades (Runtime / Emulation)

- **Anchos**: `Emulation.setDeviceMetricsOverride` con 375×812, 390×844, 768×1024, 1280×800 y
  1440×900 (`mobile: true` en 375, 390 y 768).
- **Reduced motion**:
  `Emulation.setEmulatedMedia({ features: [{ name: "prefers-reduced-motion", value: "reduce" }] })`.
- **Táctil**: `Emulation.setTouchEmulationEnabled({ enabled: true })` más `mobile: true`.
  Confirmar con `Runtime.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches")`,
  que debe dar `false`.
- **Inventario de animaciones** (no basta con capturas):
  ```js
  document.getAnimations().map(a => ({
    name: a.animationName,
    target: a.effect.target.className,
    iterations: a.effect.getTiming().iterations,
    duration: a.effect.getComputedTiming().duration,
    state: a.playState,
  }))
  ```
- **Estados de prueba de Publishing/Published**: con `Fetch.enable` y patrones `/api/…`,
  interceptar las respuestas de Posts o de la tarea Publish y reescribir `display_state`:
  `"publishing"` en un poll y `"published"` en el siguiente. Así se observa una transición sin
  publicar de verdad.
- **Overflow**: `document.documentElement.scrollWidth <= innerWidth` en cada ancho.

### Escenarios

1. **Login (US1)**: abrir `/login` sin sesión.
   - Animaciones `ap-rise-in` (card) y `ap-mark-bar` (monograma), cada una con 1 iteración y
     duración ≤ 400 ms.
   - `document.activeElement` es el input de password desde la primera evaluación.
     `Input.insertText` inmediato más Enter envía.
   - Captura: el glow es visible y el texto legible. Repetir en los 5 anchos sin overflow.
   - Con reduced motion: las duraciones son ≈ 0 y el estado final se ve directo.
2. **Auth loading (US1)**: ralentizar `GET /api/auth/session` (Fetch con retardo).
   - Se ven el monograma y "Loading AutoPublisher…".
   - `ap-pulse` tiene 3 iteraciones y ninguna animación nueva tiene `Infinity`. Tras unos 3,5 s,
     el `playState` es `finished`.
   - Con un fallo forzado: el error de sesión aparece sobre el mismo marco, sin animación nueva.
3. **Publishing (US2)**: Post interceptado como `publishing` en Posts, Post detail, Calendar
   (semana y agenda), Home y Publish Results.
   - Se ve el punto `.ap-badge__activity`; el ancho del badge no cambia.
   - `ap-pulse` termina (`finished`) en < 5 s.
   - Que no haya animaciones con `iterations: Infinity` salvo `ap-spin`.
4. **Published (US2)**: siguiente poll con `published`.
   - En Post detail, Calendar y Publish Results, `ap-badge-emphasis` corre una vez y el
     atributo `data-emphasis` desaparece al terminar.
   - Recargar la página: no hay `data-emphasis`.
4b. **Fast-path de Results (FR-020a)**: en Publish, pulsar "publicar ahora" con la respuesta
   interceptada para devolver la publicación ya `published` (nunca `publishing`).
   - La fila corre `ap-badge-emphasis` una vez.
   - Navegar a Posts → History, Calendar y Post detail de esa publicación: no hay
     `data-emphasis`.
   - Recargar la tarea Publish: no hay `data-emphasis`.
5. **Import (US3)**: en una carpeta con Media, importar 2 válidos y 1 duplicado.
   - Solo las 2 cards nuevas tienen `data-just-imported` y corre `ap-highlight` (≈ 1,4 s);
     después el atributo desaparece.
   - Con un filtro que oculte uno de ellos: ese no aparece y los filtros siguen en la URL.
6. **Calendar (US4)**: reprogramar un Post por diálogo y por drag (lg).
   - El item en su nuevo día tiene `data-just-rescheduled`; el foco y el anuncio son los de hoy.
   - Cancelar: no hay atributo. Repetir en agenda a 375.
7. **Favicon (US5)**: la pestaña muestra el monograma. `GET /favicon.svg` responde 200 en la
   instancia servida por el backend (`frontend/dist`).
8. **Hover guard (US6)**:
   - Con emulación táctil, tocar una card de Media y una tile de Home: después
     `getComputedStyle(card).translate` es `none`.
   - En 1280 con ratón (`Input.dispatchMouseEvent` move): `translate` es `0px -1px`, como hoy.
   - El foco por teclado sigue levantando la card.
9. **Reduced motion global**: repetir 1, 3, 4, 5 y 6 con `reduce`.
   - Toda la información sigue visible.
   - Los atributos se limpian igual (el `animationend` llega con 0,01 ms).

## Resultado esperado

Todos los criterios SC-001 a SC-011 y SC-007a de la spec, comprobados en los anchos 375, 390,
768, 1280 y 1440 y con reduced motion.
