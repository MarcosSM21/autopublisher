# Quickstart — Validar Feature 018

Guía de validación. Contratos en [contracts/api.md](contracts/api.md) y
[contracts/ui.md](contracts/ui.md); reglas en [research.md](research.md).

## Requisitos

- Backend y frontend como en el README (`uv run …` en `backend/`, `npm run dev` en
  `frontend/`), proxy `/api` → `127.0.0.1:8000`.
- Al menos una plataforma con configuración local (p. ej. Telegram o YouTube) para el
  journey de primer uso.
- Base de datos de prueba nueva (`AUTOPUBLISHER_DB_PATH=/ruta/temporal.db`) para el journey
  de primer uso; una base con datos variados para Home.

## 1. Tests dirigidos (durante la implementación)

```bash
# backend
cd backend
uv run pytest tests/test_overview_attention.py tests/test_post_display_state.py \
  tests/test_account_health.py tests/test_platforms_api.py tests/test_accounts.py \
  tests/test_migrations.py

# frontend
cd frontend
npx vitest run src/routes.test.tsx src/shell.test.tsx src/pages/home.test.tsx \
  src/pages/accounts.test.tsx src/pages/settings.test.tsx src/onboarding.test.tsx \
  src/ui/detail-surface.test.tsx src/storage-safety.test.tsx
```

Antes del PR, una sola vez: `ruff check`, `ruff format --check`, `mypy` (backend);
`npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build` (frontend);
`git diff --check`. Suites completas: solo CI del PR.

## 2. Contratos de API (manual rápido)

```bash
curl -s localhost:8000/api/overview | jq '.attention[] | {kind, action}'
curl -s "localhost:8000/api/overview?project_id=1" | jq '.projects[0]'
curl -s localhost:8000/api/projects/1/account-health | jq '.[] | {label, state, expiring}'
curl -s localhost:8000/api/platforms | jq '.[] | {platform, status, missing}'
```

Esperado: ningún valor de configuración, ruta ni token en `/api/platforms`; la llamada a
`/api/overview` no altera `updated_at` de ninguna fila.

## 3. Journey de primer uso (SC-001, alcance 018)

Con base vacía y una plataforma configurada, sin leer documentación:

1. `/` muestra solo "Create your first project" → crear → aterriza en `/p/1/library`.
2. Checklist visible; la Library vacía y la checklist proponen el siguiente paso; en Accounts
   el único CTA es "Connect an account".
3. Add account → elegir plataforma (X aparece como "Coming soon", no seleccionable) →
   Connect → completar el flujo → la cuenta aparece "Ready" con la identidad real; no se ha
   escrito ningún handle. Repetir y cancelar antes de conectar → no queda cuenta residual.
   Con Telegram, conectar sin elegir canal → la cuenta aparece "Finish setup".
4. Library: "Import your first media" → importar.
5. El medio sin usar muestra **Publish…** de forma evidente; la checklist lleva a él.
   (Configurar destinos y programar se valida en 019.)

## 4. Uso diario (SC-002, SC-003)

Con datos que incluyan: un post fallido, uno con revisión manual, uno de TikTok Inbox en
espera, uno automático vencido, uno manual con la hora pasada, uno programado mañana con
opciones incompletas, una cuenta con reconexión y una que caduca en 3 días:

- Home muestra los 8 problemas en el orden de research §7, cada uno con una sola acción que
  abre el destino correcto.
- Pausar la automatización en Settings → Home muestra el banner de pausa; los automáticos
  futuros aparecen en Up next como "Scheduled · paused".
- Strip del proyecto: "N need attention" abre `/?project=<id>` con el filtro visible.
- Sin problemas: "Everything is on track" + próxima publicación.

## 5. Navegación (SC-004)

Para cada URL de contracts/ui.md §1: abrir directamente en una pestaña nueva, recargar,
navegar atrás/adelante. Probar ids inexistentes, de otro proyecto y no numéricos → "not
found" con una acción.

## 6. Responsive y accesibilidad (SC-006–SC-008, manual)

En DevTools a **375×812**, **768×1024**, **1280×800**:

- Sin scroll horizontal del documento en todas las rutas (`document.documentElement.scrollWidth
  <= innerWidth`).
- 375: bottom nav (4 destinos), selector arriba, Settings en "More"; detalle de cuenta a
  pantalla completa con Back. 768: rail; detalle en drawer. 1280: sidebar; detalle en panel.
- Objetivos táctiles ≥ 44 px (inspección de botones, enlaces de nav, chips).
- Recorrido completo solo con teclado: skip link, foco visible siempre, drawer atrapa el foco
  y Escape lo cierra devolviendo el foco.
- Contraste AA de los tokens (comprobado una vez con una herramienta de contraste) y
  `prefers-reduced-motion` desactiva transiciones.

## 7. Regresión funcional (SC-010)

Desde la nueva navegación: importar, Publish… (Distribute), programar, Publish now,
auto-publicar, conectar/reconectar una cuenta existente. Los tests existentes de esos
componentes cubren la lógica; aquí solo se comprueba que son alcanzables y funcionan.
