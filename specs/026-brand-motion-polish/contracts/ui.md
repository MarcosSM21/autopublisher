# UI contract: Feature 026 — Brand & Motion Polish

Contrato observable (DOM, atributos, CSS) que implementación y tests deben respetar. Las
decisiones están en [../research.md](../research.md).

## §1 Motion tokens y política

| Token | Valor | Reduced motion | Uso |
|---|---|---|---|
| `--motion-fast` | 140 ms (sin cambios) | 0 | hover, focus, cambios pequeños |
| `--motion-medium` | 200 ms (sin cambios) | 0 | overlays (Dialog, Sheet, Drawer, menú, Flash) |
| `--motion-emphasis` | **360 ms (nuevo)** | 0 | entrada de marca del Login, énfasis Published, highlights |
| `--motion-easing` / `--motion-easing-out` | sin cambios | — | `--motion-easing-out` también para el énfasis |

- Derivados, siempre `calc()` del token de énfasis:
  - ciclo de pulso: `× 3`, con 3 iteraciones (≈ 3,2 s en total);
  - highlight: `× 4` (≈ 1,44 s).
- Propiedades permitidas: `opacity`, `translate`, `scale`, `transform`, `box-shadow`, colores.
  Nunca dimensiones, posiciones, márgenes ni `inset`.
- Ninguna animación nueva con `infinite`. Las tres iteraciones de `ap-pulse` y todo lo demás
  terminan antes de 5 s.
- Keyframes nuevos solo con `from` (o `50%` en el pulso) y sin `fill-mode: forwards`: el final
  es el estilo natural.
- Reduced motion: la regla global existente (no se crea otra). Los estados finales son los
  estáticos.

Keyframes nuevos: `ap-mark-bar`, `ap-pulse`, `ap-badge-emphasis`, `ap-highlight`. El keyframe
reutilizado es `ap-rise-in`.

## §2 Login y Auth

### Marco (`.ap-login`, `.ap-auth-loading`)
- Fondo: `radial-gradient(... at 50% 30%, var(--color-auth-glow), transparent 70%)` sobre
  `var(--color-sidebar)`. Estático.
- `--color-auth-glow: rgb(66 99 78 / 0.28)` es el único gradiente del producto. Documentado como
  excepción.
- Aplica al Login, al Auth loading y al error de sesión de `AuthGate` (`<main class="ap-auth-loading">`).
  El error no tiene motion.

### Login
- `.ap-login__card`: `animation: ap-rise-in var(--motion-emphasis) var(--motion-easing-out)`,
  una vez al montar.
- `.ap-login__title .ap-mark::after`: `animation: ap-mark-bar …` (`from { scale: 0 1 }`, origen
  a la izquierda), una vez.
- Sin cambios:
  - el `h1#login-title` "AutoPublisher" y el `aria-labelledby`;
  - el input `type=password` con `autoFocus`;
  - el `role="alert"` del error;
  - el botón "Sign in".
- Ningún timer ni estado nuevo. El envío no espera a nada.

### Auth loading (`shell/AuthLoading.tsx`)
```html
<p class="ap-auth-loading" role="status">
  <span class="ap-mark ap-auth-loading__mark" aria-hidden="true"></span>
  <span>Loading AutoPublisher…</span>
</p>
```
- Lo usan `AuthGate` (estado loading) y `LoginPage` (estado loading). El texto no cambia.
- `.ap-auth-loading__mark`: tamaño mayor (≈ 2,5 rem); `ap-pulse` acotado (3 ciclos) y luego
  estático.

## §3 Badge: actividad y énfasis

`ui/Badge.tsx` añade props opcionales (por defecto, el comportamiento actual):

| Prop | DOM |
|---|---|
| `activity?: boolean` | `<span class="ap-badge__activity" aria-hidden="true">` dentro del badge, sobre la esquina del icono; el badge recibe `data-activity` |
| `emphasis?: boolean` | `data-emphasis` en el `span.ap-badge` |
| `onEmphasisEnd?: () => void` | se llama en `animationend` con `animationName === "ap-badge-emphasis"` (cualquier otro `animationend`, como el del punto, se ignora) |

- Texto, icono, tono y `role` del badge sin cambios. Sin live regions nuevas.
- `.ap-badge__activity`: punto sólido en `--status-active-solid` con `ap-pulse` acotado al
  montar. Sin cambio de ancho del badge (posición absoluta).
- `.ap-badge[data-emphasis]`: `ap-badge-emphasis` (scale 0,9 → 1 y anillo suave que se
  desvanece), `--motion-emphasis`.

### Regla de actividad
`activity = display_state === "publishing"`, y nada más.
- `StatusBadge` la aplica solo a la variante `post`.
- `ResultsSection` la aplica a `outcome === "publishing"`, que incluye las labels "Publishing…" y
  "Processing" (mismo `display_state`).
- Nunca a "Processing in TikTok" (`TikTokInboxDelivery`) ni a textos que no son badges.

### `usePublishedEmphasis(displayState, options?)` (`ui/usePublishedEmphasis.ts`)
- Devuelve `{ emphasis: boolean, onEmphasisEnd: () => void }`.
- **Vía A (general)**: `emphasis` es `true` cuando **la misma instancia montada** pasa de
  `"publishing"` a `"published"`.
- **Vía B (solo Publish Results)**: con `options.initiallyEmphasized === true` y el estado de
  montaje `"published"`, `emphasis` empieza en `true`. Sin la opción, al montar siempre es
  `false`.
- Se apaga con `onEmphasisEnd` o con cualquier cambio de estado posterior.
- Sin persistencia de ningún tipo.
- Consumidores: `StatusBadge` (variante `post`, **nunca** pasa `initiallyEmphasized`) y la fila
  de `ResultsSection`.

### Fast-path de Publish Results (`usePublishTask` + `ResultsSection`)
- `PostStep` gana `emphasized?: boolean`. Acción del reducer:
  `{ type: "emphasis_shown"; id: number }`, que la fija en `steps[id]`. `run_start` sigue
  reiniciando `steps`.
- `initiallyEmphasized` de una fila =
  `step?.run === "now" && step.status === "done" && !step.emphasized`. El hook la aplica solo si
  el estado de montaje es `published`.
- Cuando la fila muestra el énfasis (vía A o B), despacha `emphasis_shown` una vez.
- Sin persistencia: `steps` vive en el reducer de la tarea y desaparece al recargar.

## §4 Highlight de import (Library)

- `useMediaImport(project, folderId, onImported)`: `onImported(importedIds: number[])`.
  `importedIds` son los `content.id` de los resultados `status === "imported"` de esa operación.
- `MediaView` guarda `justImported: { ids, key, loadedAt } | null` y lo fija **después** de la
  relectura:
  - `key` = scope + `selectionKey(query)` actuales en ese momento;
  - `loadedAt` = el del snapshot cargado por esa relectura (`load()` resuelve con él).
- `MediaCard` recibe `justImported?: boolean` y renderiza `data-just-imported` en el
  `a.ap-media-card` solo cuando:
  - `justImported.key === currentKey`;
  - `justImported.loadedAt === loaded.loadedAt` (snapshot posterior al import);
  - el id está en `ids`;
  - la card está en los resultados visibles.
- `onAnimationEnd` con `animationName === "ap-highlight"` quita el id; con el set vacío, vuelve
  a `null`.
- Cambiar búsqueda, filtros u orden invalida el set, igual que cualquier recarga posterior
  (nuevo `loadedAt`), aunque la consulta y la carpeta no cambien. No hay auto-scroll, ni cambio de
  foco, selección ni filtros.
- `LibraryRoot`: sin highlight. El panel de resultados es la confirmación.
- `.ap-media-card[data-just-imported]`: `ap-highlight` (anillo moss que se desvanece).

## §5 Highlight de reschedule (Calendar)

- `CalendarView` tiene el estado `landed: { id, week } | null`, donde `week` es el lunes visible
  (`dayKey(monday)`).
- Se fija en `onDone` del `ActionDialog`, tras `await onChanged()`, si
  `result.scheduled_at !== scheduling.post.scheduled_at` **y** la nueva fecha cae en la semana
  visible.
- Se limpia en `openDialog` y en `animationend` (`ap-highlight`).
- `a.ap-calendar-item[data-detail-id=<id>]` lleva `data-just-rescheduled` solo si
  `landed.id === id && landed.week === week`, en la semana y en la agenda. Cualquier cambio de
  semana (botones, Back/Forward, URL) lo invalida por derivación.
- Cancelar, fallar (incluido 409) o un Post fuera del rango visible: sin atributo.
- Sin cambios: `focusAfterDialog`, el ref `rescheduled`, el texto del `role="status"`, los
  atributos de drag (`data-drop`, `data-dragging`) y sus estilos.

## §6 Favicon

- `frontend/public/favicon.svg`: el monograma (fondo `#42634e` con radio del 25 %, barra
  `#f6f5f1` en `inset 25% 25% 25% 42%`).
- `frontend/index.html`: `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />`.

## §7 Hover guard

```css
.ap-media-card:focus-visible { /* lift: todos los dispositivos */ }
@media (hover: hover) and (pointer: fine) {
  .ap-media-card:hover { /* lift */ }
  .ap-home-tile:hover { /* lift */ }
}
```
Mismos valores que hoy (`--shadow-raised`, `translate: 0 -1px`, transiciones `--motion-fast`).

## §8 Fuera del contrato (no cambia)

Flash, page transitions, Home (salvo heredar el badge), empty states, skeletons, spinner, drag
del Calendar, TopBar, sidebar, Dialog, Sheet y Drawer.
