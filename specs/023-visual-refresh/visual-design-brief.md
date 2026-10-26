# Visual Design Brief — Feature 023 Visual Refresh

**Feature**: [spec.md](./spec.md)
**Created**: 2026-10-25
**Status**: Fuente de verdad visual junto con `spec.md` para `/speckit-plan`, `/speckit-tasks` e implementación.

> Dirección: **Creative Editorial Workspace**.
> AutoPublisher debe sentirse como una herramienta profesional para trabajar con contenido
> creativo: **calm, creative, intentional, premium, functional**. Nunca corporate, generic,
> flashy, decorative ni plantilla de admin dashboard.
>
> Combina claridad de SaaS moderno, protagonismo del contenido visual, jerarquía editorial
> fuerte, estética sobria ligeramente premium y personalidad reconocible. La estética nunca
> reduce velocidad, claridad ni accesibilidad.

Los valores de este documento son **dirección inicial**. Pueden corregirse ligeramente en
planning por contraste/accesibilidad (ver §17, ajustes ya detectados), pero no sustituirse por
otra dirección. Cuando este brief y `docs/design-system.md` (Feature 018) difieran, manda este
brief y `docs/design-system.md` se actualiza al implementar.

---

## 1. Principios

### Content first
Las imágenes y vídeos son el contenido principal. La UI es marco y no compite con ellos.

### Quiet chrome
Navegación, botones secundarios, bordes y controles son visualmente tranquilos.

### Strong hierarchy
Debe quedar claro inmediatamente:
1. dónde estoy;
2. qué estoy viendo;
3. cuál es la acción principal;
4. qué es secundario.

### Spacious, not empty
Espacio generoso para jerarquía y legibilidad. Sin grandes zonas vacías sin función.

### Character without decoration
La personalidad surge de typography, proportions, contrast, surfaces, composition, imagery y
controlled color. No de decoración arbitraria.

Se mantienen los principios vigentes de Feature 018 que no contradicen este brief: el color
refuerza y nunca transporta solo el significado; una acción primaria por vista; si hacerlo más
bonito lo hace más difícil de entender, se rechaza.

---

## 2. Tema visual — Workspace claro + sidebar oscura

| Rol | Valor de dirección | Notas |
|---|---|---|
| Canvas | `#F6F5F1` (warm off-white) | Fondo de la app |
| Surface | `#FFFFFF` | Cards, paneles, dialogs |
| Surface muted | `#EFEEE9` | Zonas secundarias, hover de filas, placeholders de thumbnail |
| Sidebar | `#181917` (warm near-black) | Navegación principal |
| Primary text | `#191A18` | |
| Secondary text | `#70736C` → ajustar (ver §17) | Metadata, help text |
| Subtle border | `#DEDDD7` | Solo separadores decorativos |
| Primary accent | `#42634E` (deep desaturated green) | Acción primaria, focus, selección |
| Accent soft | `#E5ECE7` | Fondo de selección, estados suaves |
| Destructive | `#B44747` (muted red) | Solo acciones realmente destructivas y errores |

**La intención no es crear una aplicación verde.** El sistema es predominantemente neutral; el
accent aparece en la acción primaria, el foco, la selección y poco más.

---

## 3. Tipografía

- Familia: **Geist** (o alternativa prácticamente equivalente solo con razón técnica real).
  Sans-serif moderna, muy legible y con personalidad.
- La fuente se empaqueta y sirve desde la propia aplicación: **sin CDN ni peticiones a
  servicios de fuentes remotos** (AutoPublisher es local-first; spec D2). Variable font 400–600.
  Fallback: el system stack actual.
- Sin serif en el sistema base en esta feature.

| Rol | Tamaño / peso |
|---|---|
| Page title | 30–34px / 600 |
| Section title | 20–24px / 600 |
| Card title | 15–16px / 550–600 |
| Body | 14–15px |
| Metadata | 12–13px |
| Buttons | 13–14px / 500–600 |

- Los títulos ganan presencia respecto a la UI actual; el cuerpo se vuelve algo más compacto.
- Sin escalas gigantes de landing page.
- Tamaños relativos (respetan el text-size del navegador). Texto de cuerpo nunca < 14px;
  metadata nunca < 12px.
- Ligero tracking negativo permitido en títulos grandes; nunca en cuerpo.
- Números de fecha/hora y contadores con cifras tabulares donde se alineen en columnas
  (Calendar, listas de Posts).

---

## 4. Spacing

- Escala en múltiplos de 4: `4 / 8 / 12 / 16 / 24 / 32 / 48`.
- Padding horizontal de página en desktop: ~32px.
- Separación entre secciones mayores: ~32–40px.
- Padding de página en móvil: ~16px.
- Ningún valor fuera de la escala sin justificación registrada en planning.

---

## 5. Geometry

| Elemento | Radio |
|---|---|
| Cards | ~14–16px |
| Inputs / buttons | ~9–11px |
| Dialogs / Sheets | ~18–20px |
| Pills / badges | full radius cuando corresponda |
| Thumbnails dentro de una card | radio interior coherente con la card (card − padding) |

Evitar que absolutamente todo sea redondeado: tablas, filas de lista, sidebar y separadores
pueden ser rectos.

---

## 6. Surfaces & depth

- Jerarquía: `background → surface → elevated overlay`.
- Reducir dependencia de cajas delimitadas por bordes: se agrupa con superficie y espacio antes
  que con borde.
- Nunca border fuerte y shadow fuerte a la vez.
- Sombras principalmente en dialogs, menus, sheets y floating elements; las cards en reposo
  sin sombra o con una sombra mínima, no ambas cosas con un borde marcado.
- **No** glassmorphism general, gradientes decorativos ni blur de fondo.

---

## 7. Sidebar

Inspiración conceptual: Godly + Arc + SaaS product navigation.

- Fondo oscuro (`#181917`).
- Iconos outline, una única familia, ~18–20px, stroke consistente.
- Texto secundario claro; el item activo con texto claro pleno.
- Bastante respiración vertical.
- Separación visible entre navegación principal (Home, Library, Posts, Accounts) y utilidades
  (Settings).
- Item normal: sin caja visible. Hover: surface sutilmente más clara.
- Item activo: surface/pill ligeramente más clara (aprox. `#2A2B28`) + peso; **no** gran bloque
  verde. El activo nunca se indica solo con color (peso + surface + `aria-current`).
- Branding AutoPublisher: tratamiento tipográfico cuidado (wordmark con peso/tracking propios y,
  si se quiere, un monograma geométrico simple). No hace falta logo profesional.
- El project selector, cuando vive en la sidebar, adopta el lenguaje oscuro.
- Foco de teclado visible sobre fondo oscuro (anillo claro, ver §17).

Rail (`md`) y bottom bar (`sm`): mismo lenguaje adaptado. Rail `md` oscuro como la sidebar;
bottom bar `sm` en surface clara con separador sutil (spec D8).

---

## 8. Home — workspace overview

- No convertir Home en dashboard corporativo de KPI cards idénticas.
- Priorizar: actividad relevante (lo que necesita atención), lo que viene a continuación
  (Up next), accesos útiles (projects) y secciones con jerarquía clara.
- Las secciones importantes pueden ser mayores y más visuales; las secundarias, filas limpias.
- Estado "todo bien" tranquilo, no celebratorio.
- Solo con la información que Home ya muestra hoy, sin thumbnails ni media reciente (spec D3).

---

## 9. Library — creative asset library (prioridad alta)

Media cards:
- thumbnail protagonista (la imagen/vídeo ocupa la mayor parte del peso visual de la card);
- metadata subordinada (nombre, carpeta, duración) en tamaño y color secundarios;
- superficie limpia;
- states/badges discretos, superpuestos o bajo el thumbnail sin tapar el contenido relevante;
- acciones secundarias discretas.

Hover:
- ligera elevación o surface change;
- posible aparición de acciones, **pero nunca solo en hover**: en táctil y teclado las acciones
  siguen accesibles;
- sin zoom agresivo.

Folders:
- identidad distinta de Media (forma, proporción o superficie propias);
- sin iconografía genérica exagerada.

Selected:
- outline accent;
- background accent muy suave;
- checkbox visible.

Select mode: conservar exactamente la funcionalidad actual y mejorar visualmente la barra de
selección y los estados.

Empty states y densidad: ver §13 y spec.

---

## 10. Status system

Estados: Draft, Scheduled (automatic / manual / paused), Publishing, Published, Failed, Needs
review, Needs action, Missed, Cancelled; estados de account y de platform.

- No un color intenso distinto por estado.
- La mayoría neutrales.
- Color fuerte reservado para error, warning, attention y meaningful success.
- Cada estado conserva texto + icono; el color es la tercera señal.
- Los badges usan tonos suaves (fondo tenue + texto con contraste AA), no fondos saturados.

Mapeo de tonos confirmado (spec D5). **Needs review** es warning/attention: requiere atención
del usuario pero no implica necesariamente un error. Danger se reserva para estados realmente
fallidos/críticos. Labels e iconos no cambian.

Mapeo:

| Tono | Post | Account | Platform |
|---|---|---|---|
| neutral | Draft, Scheduled · automatic, Scheduled · manual, Cancelled | Not connected, Inactive | Coming soon |
| neutral activo (accent soft) | Publishing | — | — |
| success (sutil) | Published | Ready | Configured |
| warning / attention | Scheduled · paused, Needs action, Needs review | Finish setup | Partially configured |
| danger | Failed, Missed | Reconnect needed | Not configured |

---

## 11. Calendar

Inspiración funcional: Toggl Track.
- Prioriza tiempo, legibilidad, eventos distinguibles y ruido mínimo.
- No experimentar con layout: se conservan semana desde `xl`, agenda por día debajo y detalle en
  drawer.
- Rejilla con líneas muy sutiles; hoy marcado con claridad sin depender solo de color.

---

## 12. Settings

Inspiración: Krea + Arc + Blinq.
- Settings conserva exactamente su navegación y comportamiento actuales (spec D4): **sin**
  rutas nuevas, anchors navegables ni secondary navigation. La jerarquía sale solo de section
  titles, descriptions, spacing, grouping, surfaces y typography (`grouped content`).
- Cada sección: title, explicación breve y controls.
- **No** una card alrededor de cada input.
- Labels arriba; help text breve debajo.
- Connection states muy claros (estado + siguiente paso).

Accounts y connection panels: mismo lenguaje de grupos, estados de conexión claros.

---

## 13. Empty states

Cada empty state puede incluir, cuando sea útil:
- small visual/icon;
- title;
- explicación de una línea;
- primary action.

Ejemplo conceptual: `No media yet` · `Import images or videos to start building your Library.` ·
`Import media`.

No grandes ilustraciones genéricas repetidas. El copy funcional existente solo cambia si es
microcopy presentacional sin cambiar su significado.

---

## 14. Dialogs / Sheets

Inspiración: Clay + Microsoft Loop.

Desktop:
- padding generoso;
- título claro;
- explicación;
- contenido;
- actions claramente separadas (zona propia, primaria a la derecha).

Mobile:
- bottom Sheet;
- touch friendly.

Delete:
- destructive styling solo cuando es realmente destructive.
- **Delete → exactly one confirmation**. El refresh no añade pasos ni cambia la semántica de
  confirmación.

---

## 15. Login

Más personalidad que el workspace, sin perder simplicidad.

Dirección confirmada (spec D7): **dark framing + light panel**, que conecta con la sidebar
oscura. (La alternativa "warm canvas muy limpio" queda descartada.)

Debe tener: AutoPublisher branding, password como acción central, una sola acción `Sign in`.

No: OAuth, marketing copy, stock imagery.

---

## 16. Controles

### Buttons
| Variante | Uso |
|---|---|
| Primary | Acción principal (máx. una por vista) |
| Secondary | Neutral |
| Ghost | Navigation / low priority |
| Destructive | Solo acciones destructivas |

- Altura habitual **40px en desktop con puntero fino**; **mínimo 44px de touch target en móvil
  y con puntero táctil** (spec D1; sustituye la regla universal de 44px de Feature 018).
- No todos los botones pill-shaped.

### Inputs
- ligeramente más altos y cómodos;
- borde sutil pero con contraste suficiente para identificar el control (≥ 3:1);
- clean surface;
- focus con accent + soft ring;
- placeholder en color secundario;
- sin inset shadows.

Textarea, Select y Checkbox siguen el mismo lenguaje; Checkbox con estado checked en accent.

---

## 17. Accesibilidad y ajustes de contraste detectados

Medido con la fórmula WCAG 2.x sobre los valores de dirección:

| Par | Ratio | Objetivo | Resultado |
|---|---|---|---|
| Primary text `#191A18` / canvas | 16.0 | 4.5 | OK |
| Secondary text `#70736C` / canvas `#F6F5F1` | 4.42 | 4.5 | **Falla** |
| Secondary text `#70736C` / surface muted `#EFEEE9` | 4.15 | 4.5 | **Falla** |
| Secondary text `#70736C` / surface | 4.82 | 4.5 | OK |
| White / accent `#42634E` | 6.72 | 4.5 | OK |
| Accent como texto / canvas | 6.16 | 4.5 | OK |
| Accent / accent soft | 5.59 | 4.5 | OK |
| White / destructive `#B44747` | 5.34 | 4.5 | OK |
| Subtle border `#DEDDD7` / surface | 1.36 | 3.0 (si identifica un control) | Solo decorativo |
| Accent `#42634E` como focus ring / sidebar `#181917` | 2.63 | 3.0 | **Falla** |
| Texto claro `#F6F5F1` / sidebar | 16.2 | 4.5 | OK |
| Texto claro / item activo `#2A2B28` | 13.0 | 4.5 | OK |

Ajustes propuestos (dirección, a fijar en planning):
- Secondary text ≈ `#666962` (5.1 sobre canvas, 4.8 sobre muted, 4.65 sobre accent soft).
- Border de controles (inputs, checkbox, secondary button si lo lleva) separado del subtle
  border: ≈ `#85877F` (≥ 3.3:1 sobre canvas y surface).
- Focus ring sobre la sidebar oscura: tono claro del accent ≈ `#A9C2B1` (9.3:1).
- Texto secundario de la sidebar ≈ `#A3A69E` (7.1:1 sobre `#181917`).

Requisitos permanentes: WCAG AA en texto, foco visible siempre, no depender solo de color,
controles semánticos, reduced motion, touch targets y tamaños legibles. No se sacrifica
contraste por estética.

---

## 18. Motion

Subtle and functional.
- Hover/focus: ~120–160ms.
- Dialog / sheet / dropdown: ~180–240ms.
- Preferir fade, small translate y surface transitions.
- Evitar bounce, pronounced zoom, long animation y parallax.
- Respetar `prefers-reduced-motion` (sin movimiento; como mucho cambio instantáneo).

---

## 19. Responsive

- No convertir desktop en una versión simplemente estrecha.
- Preservar la arquitectura responsive ya construida (breakpoints `sm/md/lg/xl`, sidebar/rail/
  bottom bar, DetailSurface, drawers, sticky PageActions, task mode).
- Mobile: padding ~16px, touch targets suficientes, dialogs → sheets, cards adaptadas,
  tipografía proporcional, navegación accesible.
- Sin rediseño específico de tablet en 023.

---

## 20. Interaction states

Todos los componentes interactivos consideran: default, hover, focus-visible, active, selected,
disabled, loading y error cuando aplique. Nunca solo color. Foco de teclado siempre visible.

---

## 21. Referencias visuales conceptuales

Godly, Basedash, Arc Browser, Lovable, Krea, Clay, Microsoft Loop, Toggl Track, Blinq,
ActiveCollab, Conduktor, Resend, Midjourney. **No copiar ninguna literalmente.**

| Referencia | Tomar | No tomar / evitar |
|---|---|---|
| Godly | personalidad, contraste, composición, tipografía, sensibilidad editorial | hero sections, giant typography, layouts experimentales de marketing |
| Basedash | product clarity, navigation, organización, estructura de settings/modals | apariencia demasiado administrativa |
| Arc | refinement, personalidad de navegación, surfaces, sensación de producto terminado | — |
| Lovable | grids de proyecto/contenido, thumbnails, organización, tratamiento visual del contenido | — |
| Krea | producto creativo, assets, Library, editor, settings, login (referencia clave) | — |
| Clay / Microsoft Loop | dialogs, overlays, spacing, jerarquía de acciones | — |
| Toggl Track | claridad del Calendar | — |

---

## 22. Prioridades por pantalla

Tratamiento más profundo:
1. Sidebar / app shell
2. Home
3. Library
4. Login

Tratamiento coherente pero más conservador:
5. Posts
6. Calendar
7. Accounts
8. Settings
9. Onboarding / connections
10. Shared dialogs / sheets

---

## 23. Estrategia de rollout

El refresh se implementa como **sistema**, nunca `page → arbitrary CSS → next page → different
CSS`. Orden:
1. tokens;
2. primitives / shared components;
3. shell;
4. core screens;
5. secondary screens;
6. responsive / polish.
