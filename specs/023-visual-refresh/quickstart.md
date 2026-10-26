# Quickstart — Validación de Feature 023 Visual Refresh

**Contrato**: [contracts/ui.md](contracts/ui.md) · **Plan**: [plan.md](plan.md)

Guía de validación: qué ejecutar y qué revisar en cada checkpoint. No contiene código.

---

## 0. Preparación

- Rama `023-visual-refresh`, dependencias instaladas (`npm ci` en `frontend/`, incluida
  `@fontsource-variable/geist` tras la fase A).
- **Instancia segura** para revisar con datos: copia scratch con `AUTOPUBLISHER_CONFIG`
  apuntando a una config temporal y keyring en modo fail (nunca la instalación real).
- Datos de prueba mínimos (crear desde la UI de la instancia segura):
  - 2 proyectos (uno sin cuentas → Get started visible);
  - Library con ≥ 12 Media: imágenes claras y oscuras, una 9:16, una panorámica, un vídeo con
    duración, un Media con nombre muy largo, un Media con archivo no disponible;
  - 2 folders (uno con subfolder);
  - Posts en varios estados (draft, scheduled automatic/manual, failed o needs review si se
    puede reproducir sin publicar de verdad);
  - automation pausada en algún momento para ver el banner.
- Arrancar backend + frontend en background (memoria del proyecto) y abrir el enlace local.
- Herramientas del navegador: device toolbar (375 / 768 / 1024 / 1440), zoom de texto 200 %,
  emulación `prefers-reduced-motion: reduce`, pestaña Network con filtro "third-party".

## 1. Checks automáticos por checkpoint (dirigidos)

| Checkpoint | Comando (en `frontend/`) | Qué demuestra |
|---|---|---|
| A | `npx vitest run src/ui src/shell/shell.test.tsx` | primitives y shell siguen cumpliendo su contrato tras tokens/status |
| B | `npx vitest run src/ui src/components/DeleteConfirmDialog.test.tsx src/pages/library/bulk-delete.test.tsx` | variantes, modal/sheet, exactly-one-confirmation |
| C | `npx vitest run src/shell src/routes.test.tsx` | navegación, More, task mode, selector |
| D | `npx vitest run src/pages/home.test.tsx src/pages/library src/pages/login src/components/MediaPreview.test.tsx` | Home, Library (select, move, bulk delete, folders), Login |
| E | `npx vitest run src/pages/posts src/pages/accounts.test.tsx src/pages/settings.test.tsx src/onboarding.test.tsx src/pages/project src/components/*ConnectionPanel.test.tsx src/components/TikTokInboxDelivery.test.tsx src/pages/publish` | Posts/Calendar, Accounts, connections, Settings, onboarding, Publish heredado |
| F (una vez) | `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`, `git diff --check` | checks estáticos y build final |

No se ejecuta la suite completa del frontend ni el pytest del backend localmente (CI del PR).
No se repiten tests ya verdes si los archivos relevantes no cambiaron.

Esperado en todos: verde **sin modificar aserciones funcionales**. Un test que falle por un
selector puramente visual se ajusta solo si la clase no figura en contracts §9.5.

## 2. Revisión visual por checkpoint

Cada checkpoint revisa **solo** lo que cambió, a 375 y 1280 (y 768/1024 cuando el checkpoint
toca layout responsive).

### Checkpoint A — Foundation
- Toda la app ya en canvas cálido, Geist y accent moss; ningún azul `#1D4ED8` visible.
- Network: 0 peticiones a dominios externos; el `woff2` sale del propio origen.
- Badges: Needs review en warning (ámbar), Scheduled en neutral, Publishing en active.
- Foco visible en un formulario cualquiera.

### Checkpoint B — Shared UI
- Botones 40px en desktop con ratón, 44px a 375 (medir en DevTools).
- Un Dialog (Create project), un Sheet en 375 (Add account → bottom sheet) y un Delete
  (Media): una sola confirmación, solo el botón de confirmar en rojo sólido.
- Menús: More (375), Media actions, New post, acciones del proyecto → mismo estilo.
- EmptyState con icono en una Library vacía.

### Checkpoint C — Shell
- 1280: sidebar oscura, brand, activo como pill clara, Settings al pie, selector oscuro
  usable, Tab recorre la nav con foco claro visible.
- 768: rail oscuro + TopBar clara. 375: bottom bar clara, More abre/cierra igual.
- Task mode (Publish media en 375): sin bottom nav, sticky actions al fondo.

### Checkpoint D — Core
- **Home**: attention con más peso; Up next como timeline; Projects como tiles; sin KPI
  cards; ok-state tranquilo; filtro y Create project igual.
- **Library**: thumbnail claramente dominante (target ~70 %+, no umbral); 9:16/panorámica sin
  deformar; imagen clara y oscura con la duración legible; nombre largo truncado; archivo no
  disponible con placeholder; folders distinguibles; Select mode → seleccionar 3 → Move y
  Delete (cancelar) → barra igual que antes; import con dropzone.
- **Login**: marco oscuro + panel claro; contraseña incorrecta → mismo error; correcta →
  redirige a `next`; 375 sin scroll horizontal.

### Checkpoint E — Secondary
- Posts List/Calendar (1280 week, 1024 agenda, 375), Post detail y una ActionDialog cancelada.
- Settings: secciones agrupadas, sin card por input, sin índice/anchors.
- Accounts: lista, detalle, Add account; un connection panel en cada estado disponible
  (connected / reconnect / not connected) legible y sin estilos legacy.
- Get started en el proyecto sin cuentas: mismos pasos.
- Publish media y Text post: sin roturas visuales.

### Checkpoint F — Responsive / legacy / final
- Pantallas prioritarias (Login, Shell, Home, Library, Posts, Calendar, Settings, Accounts) a
  375 / 768 / 1024 / ≥1280.
- 200 % de texto en 375 y 1280: nav, TopBar, badges y bottom nav envuelven sin ocultar.
- Reduced motion: abrir dialog, sheet, menú → sin desplazamiento.
- Safe-area (simulador iOS o `env()` emulado): bottom bar, sticky actions y bottom sheet.
- `index.css` sin clases legacy; búsqueda de literales (contracts §1.6) sin resultados fuera de
  `tokens.css`.
- Comparar tamaño de `dist/assets/*.css` y `*.woff2` con `main` (crecimiento CSS ≤ ~10 %).
- Actualizar `docs/design-system.md` (DR-001) y revisar que coincide con contracts §1–§8.

## 3. Criterio de salida

- Todos los checks de §1 en verde; checkpoint F completo.
- SC-001…SC-010 comprobados; SC-011 confirmado por el usuario en la revisión final.
- Ningún cambio en rutas, pasos, copy funcional ni backend (`git diff main --stat` sin
  `backend/`).
