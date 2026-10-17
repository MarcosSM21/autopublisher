# API Contracts — Feature 018

Todos los endpoints nuevos son `GET` de solo lectura salvo `DELETE /accounts/{id}`. Errores
con el formato existente (`{code, message, fields?}`). Fechas ISO 8601 UTC.

## 1. `GET /api/overview`

Query: `project_id` (opcional, entero). Con él, todo se restringe a ese proyecto
(404 `not_found` si no existe).

```json
{
  "generated_at": "2026-10-16T10:00:00Z",
  "automation": { "paused": false, "running": true, "paused_automatic_posts": 0 },
  "attention": [
    {
      "kind": "failed",
      "priority": 2,
      "project": { "id": 1, "name": "Cyber" },
      "account": { "id": 4, "platform": "instagram", "label": "Instagram @l4i4" },
      "post": {
        "id": 12, "display_state": "failed", "scheduled_at": null,
        "media_title": "Launch teaser", "excerpt": null
      },
      "title": "Upload failed",
      "detail": "Instagram rejected the video format.",
      "at": "2026-10-16T08:12:00Z",
      "action": { "label": "Retry", "target": { "type": "post", "project_id": 1, "id": 12 } },
      "affected_posts": 0
    }
  ],
  "upcoming": [
    {
      "post_id": 15, "project": { "id": 1, "name": "Cyber" },
      "account": { "id": 5, "platform": "youtube", "label": "YouTube @cyber" },
      "scheduled_at": "2026-10-17T08:00:00Z", "display_state": "scheduled_automatic",
      "media_title": "Episode 3", "excerpt": null
    }
  ],
  "projects": [
    {
      "id": 1, "name": "Cyber", "is_active": true,
      "accounts_active": 4, "accounts_ready": 3, "attention_count": 2,
      "next_post": { "post_id": 15, "scheduled_at": "2026-10-17T08:00:00Z",
                     "display_state": "scheduled_automatic" },
      "onboarding": { "account_ready": true, "media_imported": true,
                      "post_created": true, "complete": true }
    }
  ]
}
```

Garantías:

- `attention` ordenado por `priority` y criterio secundario de research §7; un item por post
  y por cuenta como máximo.
- `upcoming` ≤ 5 elementos, proyectos activos, `scheduled_at > now`, ascendente.
- `action.target.type`: `post` (→ `/p/{project_id}/posts/{id}`), `account`
  (→ `/p/{project_id}/accounts/{id}`), `settings` (→ `/settings`).
- `detail` solo contiene mensajes ya saneados que el sistema muestra hoy (errores de intento,
  problemas de `local_check`, `auto_publish_error.message`) o "Couldn't verify requirements"
  cuando la comprobación local no puede completarse. En `manual_review` es siempre "This post
  may have published. Check it before trying again." (el error técnico del intento sigue en
  los intentos del post).
- Proyectos inactivos: solo items `manual_review`, `failed`, `needs_action`.
- `display_state` ∈ `draft | scheduled_automatic | scheduled_manual | scheduled_paused |
  publishing | published | failed | needs_review | needs_action | missed | cancelled`.
- Sin escrituras, sin llamadas a plataformas, sin `reconcile`.

## 2. `GET /api/projects/{project_id}/account-health`

404 si el proyecto no existe. Una entrada por cuenta del proyecto (activas e inactivas),
orden: activas primero, después por plataforma y etiqueta.

```json
[
  {
    "account_id": 4, "platform": "instagram", "label": "Instagram @l4i4",
    "display_name": null, "is_active": true,
    "state": "ready",
    "identity": { "name": "l4i4", "username": "l4i4", "avatar_url": "https://…" },
    "expires_at": "2026-10-20T09:00:00Z", "expiring": true,
    "capabilities": ["images", "videos"],
    "issue": { "code": "credential_expiring",
               "message": "The Instagram login expires in 4 days. Reconnect to keep publishing." },
    "can_discard": false
  }
]
```

`state` ∈ `ready | reconnect_needed | setup_required | not_connected | inactive`
(UI: Ready · Reconnect needed · Finish setup · Not connected · Inactive). `setup_required` =
conexión válida pero incompleta para publicar (Telegram sin canal); `reconnect_needed` =
conexión ya no válida o credencial caducada.
`identity` nunca incluye IDs de plataforma, tokens ni `credential_ref`.

## 3. `GET /api/platforms`

```json
[
  { "platform": "youtube", "label": "YouTube", "integration_available": true,
    "status": "configured", "can_connect": true, "missing": [], "message": null },
  { "platform": "instagram", "label": "Instagram", "integration_available": true,
    "status": "partial", "can_connect": true, "missing": ["media_delivery"],
    "message": "Media delivery is not configured: Instagram posts can't be published yet." },
  { "platform": "x", "label": "X", "integration_available": false,
    "status": "coming_soon", "can_connect": false, "missing": [], "message": null }
]
```

Prohibido en la respuesta: rutas de fichero, nombres de variables de entorno, contenido de
ficheros, `client_id`/`client_key`/`api_id`, secretos, tokens, texto de excepciones.

## 4. Cambios en endpoints existentes (aditivos / retrocompatibles)

| Endpoint | Cambio |
|---|---|
| `POST /api/projects/{id}/accounts` | `handle` pasa a opcional. Sin `handle` → cuenta provisional (`handle: null`). Con `handle` → igual que hoy. |
| `GET/PATCH …/accounts`, `AccountRead` | `handle: string \| null` |
| `PublicationRead.account.handle` | `string \| null` |
| `PublicationRead` | nuevo campo `display_state` (enum de data-model) |
| Completado de conexión (5 integraciones) | si `handle` es `null`, se adopta la identidad conectada (misma transacción) |
| `PATCH /api/accounts/{id}` | sin cambios (no admite `handle: null`) |

## 5. `DELETE /api/accounts/{account_id}` (nuevo, solo "Discard")

Única finalidad: descartar un alta abandonada. No es un borrado general de cuentas.

Una cuenta es **provisional** (descartable) si y solo si: `handle IS NULL` (nunca se adoptó
identidad), no existe fila de conexión en ninguna de las 5 tablas (ni `connected` ni
`reconnect_required`) y no tiene publicaciones en ningún estado.

Respuestas:

- `204`: cuenta provisional borrada (y sus filas de presets por `CASCADE`).
- `409 account_not_discardable`: tiene identidad, conexión o posts ("This account is in use
  and can't be removed. Deactivate it instead.").
- `409 account_busy`: hay una operación de conexión de Telegram en curso con el lock de esa
  cuenta ("A connection step is in progress. Try again in a moment.").
- `404`: no existe.

Orden y limpieza de intentos transitorios (todos viven solo en memoria; antes de completar
una conexión no existe nada en SQLite ni en el almacén seguro):

1. Se valida que la cuenta es provisional.
2. Se invalidan sus intentos: `expire_for_account(account_id)` en los registros OAuth de
   YouTube, Instagram, Threads y TikTok (pasan a `expired`; una redirección posterior del
   proveedor con ese `state` responde "Authorization not valid" y no crea conexión) y
   `discard(account_id)` en el registro de logins de Telegram (se descarta la sesión temporal
   no autorizada en memoria).
3. En una transacción se vuelve a comprobar la ausencia de conexión y de publicaciones y se
   borra la fila. Si un callback ganó la carrera y ya creó la conexión → `409
   account_not_discardable`. Si el borrado gana, un callback que ya hubiera consumido el
   `state` falla al no encontrar la cuenta por su camino de error existente; la
   implementación DEBE verificar (test con YouTube como integración representativa) que
   ese camino no deja secretos huérfanos en el almacén seguro.

No contacta plataformas. El frontend solo ofrece "Discard" cuando `can_discard` es `true`.
