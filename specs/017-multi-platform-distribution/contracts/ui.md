# UI Contract: Distribute

## Entrada

`ContentDetail`: el botón **Prepare publications** pasa a **Distribute** (`aria-expanded`),
y abre `Distribute` bajo el detalle. El texto vacío de la cola ("…choose Prepare
publications.") pasa a "…choose Distribute.". Tarjetas de la Asset Library sin cambios.

## Vista Distribute (formulario único, progresivo)

```text
┌ Distribute ───────────────────────────────────────────────┐
│ Destinations                                               │
│   Preset: [Choose a preset ▾]   [Manage presets]           │
│   ⚠ 2 destinations skipped: TikTok @x (inactive),          │
│     Instagram @y (already has an active publication)       │
│   [x] YouTube @chan                                        │
│   [x] Instagram @l4i4                                      │
│   [ ] TikTok @x   — Already has an active publication      │  (disabled)
│                                                            │
│ Common text                                                │
│   Description / caption  [.........................]      │
│                          (Reset to content value)          │
│   Hashtags               [#a #b]                           │
│                                                            │
│ Selected destinations                                      │
│   YouTube @chan    Customized  [Customize ▾] [Discard]     │
│      Title [...]  Description [...]  Hashtags [...]        │
│   Instagram @l4i4               [Customize ▸]              │
│      Description [...] Hashtags [...]   (sin título)       │
│                                                            │
│ When  (•) Prepare   ( ) Schedule [datetime-local]          │
│                                                            │
│ [Create 2 publications]                                    │
└────────────────────────────────────────────────────────────┘
```

Reglas:

- Cuentas: solo activas; las que tienen una Publication del Content en un estado no
  histórico (`!HISTORY_STATUSES.includes(status)`) se muestran deshabilitadas con
  "Already has an active publication".
- Preset: elegirlo **reemplaza** la selección por sus cuentas seleccionables y muestra el
  aviso de omitidas (o "No destinations selected from this preset" si quedan 0).
- **Manage presets** (plegable): lista de presets con Rename / Edit destinations / Delete, y
  **Save selection as preset** (nombre + cuentas marcadas). Sin pantalla aparte.
- Common text: prellenado con el Content; dirty state explícito por campo.
- Customize: título solo si `platform ∈ TITLE_PLATFORMS` (`["youtube"]`). Los campos no
  editados muestran en vivo el valor heredado. "Customized" visible cuando hay algún campo
  editado; **Discard customization** limpia el destino.
- Ningún "título común". Ninguna opción de plataforma. Ningún truncado ni contador de
  límite por plataforma.
- When: Prepare (por defecto) o Schedule + fecha. Sin auto-publish en la creación.
- Botón deshabilitado sin destinos o mientras envía.

### Errores

- `fields[].account_id` → mensaje en la fila de ese destino (lista de destinos).
- `targets.<id>.<campo>_override` → mensaje bajo ese campo en el Customize del destino (se
  despliega automáticamente).
- `targets.<id>` → mensaje en la fila del destino.
- `description_override` / `hashtags_override` → bajo el campo común.
- `scheduled_at` → bajo la fecha.
- Resto → alerta general (`FormError`).
- Todo lo introducido se conserva.

## Panel de resultado (compacto)

Sustituye al formulario tras una creación correcta.

```text
Created 3 publications                    [Distribute again] [Open queue]

┌ YouTube @chan · [Unscheduled] · Needs 2 ────────────────────────┐
│ ▾ Platform options        (PublicationPlatformOptions, abierto)  │
│ • Choose whether the video is made for kids.                     │
│ • …                                   [Publish now] (disabled)   │  ← PublishAction
└──────────────────────────────────────────────────────────────────┘
┌ Instagram @l4i4 · [Scheduled] · Ready ──────────────────────────┐
│ ▸ Platform options        (plegado)                              │
│ [Publish now]                                                    │  ← PublishAction
│ Auto-publish: off  [Enable auto-publish]                         │  ← AutoPublishControls
└──────────────────────────────────────────────────────────────────┘
┌ Telegram @c · [Unscheduled] · Ready ────────────────────────────┐
│ [Publish now]                     (sin opciones de plataforma)   │
└──────────────────────────────────────────────────────────────────┘
```

- Cada fila es una `section` con `aria-label` = plataforma + cuenta.
- Cabecera: plataforma + cuenta, badge de estado, **Ready** si `check.eligible` o
  **Needs N** (N = `check.problems.length`) — ambos derivados de `PublishAction.onCheck`.
  Si el estado no es publicable (publishing, published, awaiting_user_action) solo se
  muestra el estado.
- Cuerpo, solo con bloques compartidos de `PublicationControls.tsx`:
  - `PublicationPlatformOptions` dentro de `<details>` "Platform options" (abierto si hay
    pendientes); guardar recarga el check de esa fila;
  - `PublishAction` (lista de problemas + Publish now / Send to TikTok → `PublishNowDialog`);
  - `AutoPublishControls` solo si `status === "scheduled"`.
- `useLivePublication` mantiene la fila al día (publishing → published, inicio por el
  scheduler) con el polling existente.
- NO se muestran: preview del asset, metadata, intentos/historial, fecha, cancelar,
  inbox de TikTok. Para eso: **Open queue**.
- Sin "Publish all" ni armado masivo.
- Cerrar/volver no afecta a las Publications.
