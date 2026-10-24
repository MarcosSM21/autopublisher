# UI Contract: Deployment & Mobile Readiness (Feature 020)

No se rediseña nada de 018/019. Cambios mínimos, mismos tokens y componentes del design system (`docs/design-system.md`). Textos en inglés.

## 1. Arranque y sesión

- Al cargar, la app consulta `GET /api/auth/session`.
  - `auth_required && !authenticated` → redirige a `/login?next=<ruta actual>`.
  - Desarrollo: nada cambia (sin login, sin Sign out).
- Cualquier respuesta `401 auth_required` de `request()` → navegación a `/login?next=<ruta actual>` (una sola vez; sin bucles). Los Drafts ya guardados no se pierden (son del servidor).
- `next` solo se acepta si es una ruta relativa que empieza por `/` y no por `//`; si no, `/`.

## 2. Pantalla `/login` (fuera del AppShell)

- Título "AutoPublisher", campo **Password** (`type=password`, `autocomplete="current-password"`, autofocus), botón **Sign in**.
- Error inline accesible (`role="alert"`): "Incorrect password." / "Too many attempts. Try again in a few minutes." / error de red.
- Texto secundario: "Forgot the password? Reset it on the computer that runs AutoPublisher (see the deployment guide, “Reset the password”)." (sin mostrar un comando inexistente)
- Tras éxito → `next` (el deep link original). Usable en móvil (una columna, sin zoom forzado: `font-size ≥ 16px` en el input).
- Si ya hay sesión, `/login` redirige a `/`.

## 3. Settings — sección nueva "This installation" (solo modo instalación)

Orden en Settings: Automatic publishing (existente) → **This installation** → Platform integrations (existente).

Contenido (read-only, de `GET /api/system/status`):

| Elemento | Contenido |
|---|---|
| Health | "Everything is working" o lista de problemas en palabras: "The database is not responding." · `locked`: "Secure storage is locked. Unlock your keyring on this computer so scheduled posts can be published." · `unavailable`: "Secure storage is not available. Scheduled posts cannot be published." · `unknown`: "Secure storage could not be checked without asking you to unlock it. If scheduled posts fail, unlock your keyring on this computer." (informativo, nunca "working"). El scheduler sigue mostrándose en Automatic publishing (existente). |
| Access from other devices | LAN off: "Only this computer can open AutoPublisher." + cómo habilitarlo (enlace a la guía). LAN on: lista de direcciones (`http://192.168.1.40:8000`, nombres sugeridos con "may work on your network"). Si no se detecta: "Could not detect this computer's address. See the guide." |
| HTTP warning (siempre visible si LAN on; resumida si off) | "Access over your network is not encrypted (HTTP). Only enable it on your private home network. It protects against other devices and websites using AutoPublisher without the password, but not against someone who can intercept or control your network." |
| Port | "Port 8000" |
| Nota | "These settings belong to this computer. To change them, follow “Host configuration” in the deployment guide and restart the service." |

Acciones de cuenta (sección "Sign-in"):

- **Change password** → diálogo/sheet existente: Current password, New password (mín. 12), Confirm; errores de campo; al terminar: "Password changed. Other devices have been signed out."
- **Sign out** → `POST /api/auth/logout` → `/login`.
- En móvil, Settings ya está en **More**; ambos accesibles ahí.

No hay toggles de LAN/puerto en la UI (requieren reinicio y son configuración del host).

## 4. Conectar YouTube / TikTok desde fuera del host

En el panel de conexión de YouTube y TikTok (Accounts → cuenta → Connection & technical details) y en las acciones "Reconnect" que lleven a ellos:

- Si `window.location.hostname` ∉ {`127.0.0.1`, `localhost`, `[::1]`/`::1`}: en lugar del botón **Connect/Reconnect** se muestra:
  - "Connect <Platform> from the computer that runs AutoPublisher."
  - Si la página parece abierta en el propio host por IP LAN no se puede saber de forma fiable: se añade siempre "On that computer, open http://127.0.0.1:<port><ruta actual>" (con `<port>` = `window.location.port`).
- Si el backend devuelve `409 host_only_action` (p. ej. caso no detectado en cliente), se muestra el mismo mensaje.
- Instagram, Threads y Telegram: sin cambios.
- Home/Accounts siguen mostrando "Reconnect needed" igual; la acción lleva a la cuenta, donde aparece la explicación.

## 5. Móvil

Sin cambios de diseño. Correcciones pequeñas que salgan del STOP gate (FR-073) se listan en tasks como bugs puntuales.
