# API Contract: Deployment & Mobile Readiness (Feature 020)

Formato de error existente: `{"error": {"code": "...", "message": "...", "fields": [...]}}`.
Solo se listan cambios; el resto de la API no cambia de forma ni de semántica.

## 1. Guards (middleware), en este orden

Se aplican solo cuando `create_app` recibe `deployment` (módulo `app.main:app` en desarrollo, `serve` en instalación). `create_app()` sin `deployment` (tests existentes) no los aplica.

| # | Guard | Desarrollo | Instalación | Rechazo |
|---|---|---|---|---|
| 1 | Cliente loopback | Obligatorio | — | `403 loopback_only` "AutoPublisher in development mode only accepts this computer." |
| 2 | Host | Nombre loopback, cualquier puerto | research §14 (puerto = el de escucha) | `403 host_not_allowed` "This address is not allowed for AutoPublisher." |
| 3 | Origen (POST/PUT/PATCH/DELETE) | Sí | Sí | `403 origin_not_allowed` "Request blocked: it did not come from AutoPublisher." |
| 4 | Sesión (`/api/*` salvo exentas) | — | Sí | `401 auth_required` "Sign in to continue." (la cookie inválida se borra en la respuesta) |
| 5 | Cabeceras de seguridad | — | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` | — |

Principio (C2): todos los **datos y acciones privados** requieren sesión; la Media (`/api/contents/{id}/file` y similares) **siempre**. Sin sesión solo se sirve lo necesario para iniciar y autenticar. Lista cerrada de exenciones del guard 4 (siguen sometidas a 2 y, si aplica, 3):

| Exento | Motivo |
|---|---|
| Rutas que no empiezan por `/api/` (`index.html`, `/assets/*`, `/login` y cualquier deep link) | Shell del SPA: código público del repo, sin datos privados. Un deep link sin sesión recibe el shell, que redirige a `/login?next=…` |
| `GET /api/auth/session`, `POST /api/auth/login`, `POST /api/auth/logout` | Contrato mínimo de acceso (no devuelven datos; logout solo borra la propia cookie/sesión) |
| `GET /health` | Health público mínimo (§2) |
| `GET /api/youtube/oauth/callback`, `GET /api/tiktok/oauth/callback`, `GET /api/tiktok/oauth/result` | Callbacks OAuth aprobados (§5): `state` + PKCE + loopback; `result` es una página fija |

Cualquier otra ruta `/api/*`, existente o futura, exige sesión por defecto (lista de exenciones explícita en código, no por prefijo).

## 2. Health público

`GET /health` → `200`

```json
{"status": "ok"}        // or {"status": "degraded"}
```

`degraded` = la BD no responde o el hilo del scheduler no está vivo (con autostart). Nada más. Sin sesión. Igual en ambos modos (en tests sin `deployment`, el test existente sigue esperando `ok`).

## 3. Autenticación (`/api/auth`)

### `GET /api/auth/session` (pública)

```json
{"mode": "installation", "auth_required": true, "authenticated": false}
```

Desarrollo: `{"mode": "development", "auth_required": false, "authenticated": true}`. Sin `deployment` (tests): igual que desarrollo.

### `POST /api/auth/login` (pública, guard de origen; la sesión solo se crea si el hash verificado sigue siendo el actual, en la misma transacción)

Request `{"password": "..."}` (1–1024 caracteres).

| Respuesta | Cuándo |
|---|---|
| `204` + `Set-Cookie: autopublisher_session=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000` (sin `Domain`: host-only; sin `Secure`: HTTP LAN, limitación documentada D14) | Contraseña correcta (sesión nueva; token de 256 bits, solo su SHA-256 en BD) |
| `401 invalid_credentials` "Incorrect password." | Contraseña incorrecta (mensaje único) |
| `429 too_many_attempts` "Too many attempts. Try again in a few minutes." | Rate limit (research §12) |
| `409 auth_not_enabled` | Modo desarrollo |

### `POST /api/auth/logout` (guard de origen)

`204`; borra la sesión (si existe) y la cookie (`Max-Age=0`). Efecto inmediato. Idempotente.

### Vida de la sesión

Idle 7 días renovable por actividad; absoluta 30 días desde el login, nunca ampliada; inválida → `401 auth_required` y la cookie se borra en la respuesta. Cambio/reset de contraseña invalida todas. Un restore empieza con cero sesiones (research §11).

### `POST /api/auth/password` (sesión)

Request `{"current_password": "...", "new_password": "..."}`.

| Respuesta | Cuándo |
|---|---|
| `204` + nueva cookie | Cambiado; todas las demás sesiones invalidadas |
| `401 invalid_credentials` "Current password is incorrect." | Actual incorrecta (cuenta para el rate limit) |
| `422 validation_error` (`fields: new_password`) | `new_password` < 12 o > 1024 caracteres |
| `429 too_many_attempts` | Rate limit |

## 4. Diagnóstico autenticado

### `GET /api/system/status` (sesión)

```json
{
  "mode": "installation",
  "database": {"status": "ok"},
  "credential_store": {"status": "available"},
  "deployment": {
    "port": 8000,
    "lan_enabled": true,
    "addresses": ["http://192.168.1.40:8000"],
    "suggested_names": ["http://my-pc.local:8000"],
    "allowed_hosts": ["my-pc.local"]
  }
}
```

- `database.status`: `ok` | `error`.
- `credential_store.status`: `available` | `locked` | `unavailable` | `unknown` (sondeo no interactivo, nunca `unlock()`, cache 60 s; `available` solo si se comprobó que la colección está desbloqueada; si no se puede comprobar → `unknown`; research §18).
- `deployment`: `null` en modo desarrollo. Sin rutas de ficheros, sin secretos, sin versiones.
- Scheduler y pausa: siguen en `GET /api/automation` (sin cambios).

## 5. OAuth: acciones solo del host

`POST /api/accounts/{id}/youtube-connection/authorize` y `POST /api/accounts/{id}/tiktok-connection/authorize` (y cualquier endpoint que inicie una reconexión de esas dos plataformas) en modo instalación:

`409 host_only_action` "Connect this account from the computer that runs AutoPublisher, at http://127.0.0.1:<port>." cuando el cliente o el socket no son loopback. Se comprueba antes de crear el intento.

`GET /api/youtube/oauth/callback`: **nuevo** rechazo si el cliente no es loopback → misma página de error genérica del callback (outcome inválido), sin consumir el `state`. TikTok: sin cambios.

## 6. SPA y estáticos (solo instalación)

| Ruta | Respuesta |
|---|---|
| `GET /assets/*` | Fichero de `dist/assets`, `Cache-Control: public, max-age=31536000, immutable`; inexistente → 404 |
| `GET|HEAD /api`, `/api/<desconocido>` | `404 not_found` JSON (nunca el SPA) |
| `GET|HEAD /<cualquier otra ruta>` | Fichero regular de `dist/` si existe; si no `dist/index.html`, `Cache-Control: no-cache` |
| Otros métodos en rutas no-API | `404`/`405` JSON |
| `/docs`, `/redoc`, `/openapi.json` | En instalación **no existen** (`docs_url=None`, `redoc_url=None`, `openapi_url=None`) → `404` JSON, nunca el SPA. En desarrollo se mantienen. |

`GET /api/contents/{id}/file` (con sesión) soporta `Range` (`206`, `Content-Range`, `Accept-Ranges: bytes`).

## 7. Códigos de error nuevos

`loopback_only` (403), `host_not_allowed` (403), `origin_not_allowed` (403), `auth_required` (401), `invalid_credentials` (401), `too_many_attempts` (429), `auth_not_enabled` (409), `host_only_action` (409).
