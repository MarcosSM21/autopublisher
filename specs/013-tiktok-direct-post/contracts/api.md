# API Contract: TikTok Publisher & Direct Post

**Feature**: `013-tiktok-direct-post` | **Fecha**: 2026-10-14

Amplía la API REST bajo `/api`. Fechas en ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene access/refresh tokens, client secret, cabeceras
`Authorization`, `upload_url` (ni partes de él), `publish_id` ni respuestas crudas de TikTok.

Errores comunes de los endpoints TikTok de publicación:

| Código | HTTP | Cuándo |
|---|---|---|
| `not_found` | 404 | Publicación inexistente. |
| `platform_not_supported` | 409 | La cuenta de la publicación no es TikTok. |
| `tiktok_video_required` | 409 | La publicación no tiene `Content` o no es un vídeo. |
| `publication_not_editable` | 409 | Escritura con la publicación en `PUBLISHING` o `PUBLISHED`. |

---

## 1. `GET /api/publications/{id}/tiktok-options`

Sin red. Estado completo para el panel TikTok.

```json
{
  "privacy_level": null,
  "allow_comment": false,
  "allow_duet": false,
  "allow_stitch": false,
  "commercial_disclosure_enabled": false,
  "brand_organic_toggle": false,
  "brand_content_toggle": false,
  "is_aigc": null,
  "client_audited": false,
  "allowed_privacy_levels": ["SELF_ONLY"],
  "caption": "Validation clip — please ignore\n\n#autopublisher",
  "caption_length": 47,
  "caption_max_length": 2200,
  "declaration": {
    "version": "music-usage-2026-10-14",
    "text": "By posting, you agree to TikTok's Music Usage Confirmation.",
    "links": [
      {"label": "Music Usage Confirmation",
       "url": "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"}
    ]
  },
  "labels": [],
  "fingerprint": null,
  "consent": {"state": "missing", "consented_at": null},
  "integrity_warning": null,
  "problems": [
    {"code": "tiktok_privacy_required", "message": "Choose who can view this video.", "field": "privacy_level"},
    {"code": "tiktok_aigc_required", "message": "Say whether this video is AI-generated.", "field": "is_aigc"}
  ],
  "video": {
    "format": "mp4", "size_bytes": 3145728, "duration_seconds": 12.4,
    "width": 1080, "height": 1920, "frame_rate": 30.0,
    "delegated_checks": [], "chunk_count": 1
  },
  "editable": true
}
```

- `fingerprint`: huella actual (research §6) o `null` si las opciones no están completas. El
  frontend la reenvía al consentir.
- `consent.state`: `missing` | `valid` | `stale` (había consentimiento y algo material cambió).
  `valid` significa "Consent recorded — matches saved publication metadata"; **no** afirma que
  los bytes actuales del archivo estén verificados (se recalcula el SHA-256 en el preflight). La
  UI muestra la nota "File integrity is rechecked before publishing.".
- `integrity_warning`: `null` o `{"code": "tiktok_video_changed", "message": "...",
  "at": "<fecha>"}` cuando el último intento falló porque el archivo ya no coincide con el digest
  consentido y no hay un consentimiento registrado después de ese fallo.
- `labels`: avisos oficiales según disclosure: `"Your video will be labeled as 'Promotional
  content'"` / `"… 'Paid partnership'"`.
- `declaration`: versión, texto y enlaces vigentes según los toggles (con Branded content:
  "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation." y
  ambos enlaces). Las URLs exactas de las páginas oficiales se confirman al implementar.
- `problems`: solo comprobaciones locales (opciones, caption, vídeo, consentimiento); los de
  Creator Info se ven en §3 y en el preflight.
- `video`: resultado de la inspección local (§8 de research); `null` si no se pudo inspeccionar
  (con su problema en `problems`).

## 2. `PUT /api/publications/{id}/tiktok-options`

Sin red. Sustituye todas las opciones (todos los campos obligatorios).

```json
{
  "privacy_level": "SELF_ONLY",
  "allow_comment": true,
  "allow_duet": false,
  "allow_stitch": false,
  "commercial_disclosure_enabled": false,
  "brand_organic_toggle": false,
  "brand_content_toggle": false,
  "is_aigc": false
}
```

- `privacy_level`: `null` o uno de `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`,
  `FOLLOWER_OF_CREATOR`, `SELF_ONLY`.
- `commercial_disclosure_enabled = false` con algún toggle `true` → `422` (el frontend envía
  `false/false` al desactivar).
- `brand_content_toggle = true` con `privacy_level = "SELF_ONLY"` → `422
  tiktok_branded_content_private` ("Branded content visibility cannot be set to private.").
- No modifica el consentimiento guardado: si la huella cambia, `consent.state` pasa a `stale`.

Respuestas: `200` + el objeto de §1; `409 publication_not_editable`; `422 validation_error`.

## 3. `GET /api/publications/{id}/tiktok-creator-info`

**Con red** (solo lectura: `creator_info/query`). Se llama al abrir el panel y con `Refresh`;
nunca en bucle. No persiste nada.

```json
{
  "nickname": "Cyber Studio",
  "username": "cyber.studio",
  "avatar_url": "https://p16-sign.tiktokcdn.example/....jpeg",
  "privacy_level_options": ["FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
  "comment_disabled": false,
  "duet_disabled": true,
  "stitch_disabled": true,
  "max_video_post_duration_sec": 600,
  "can_post": true,
  "blocked": null,
  "account_appears_public": false,
  "video_within_max_duration": true
}
```

- `blocked`: `null` o `{"code": "tiktok_creator_cannot_post", "message": "..."}` cuando TikTok
  devuelve `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting` o
  `reached_active_user_cap` (`can_post = false`; los demás campos `null`).
- `account_appears_public`: `true` si las opciones incluyen `PUBLIC_TO_EVERYONE` (aviso no
  bloqueante; research §4).
- `avatar_url`: solo para mostrar; caduca a las 2 h; el frontend no lo guarda.

Errores: `409 tiktok_not_connected`, `409 tiktok_reconnect_required`, `409
tiktok_identity_mismatch` (Feature 012), `429 tiktok_rate_limited`, `503 tiktok_unavailable`,
`502 tiktok_unexpected_response`, `503 credential_store_unavailable`.

## 4. `POST /api/publications/{id}/tiktok-consent`

Sin red. Registra que el usuario aceptó la declaración para el contenido exacto que revisó.

```json
{"fingerprint": "9f2c…64 hex", "declaration_version": "music-usage-2026-10-14"}
```

- El servidor recalcula la huella con el estado actual (`Content.checksum`, caption, opciones,
  `open_id` de la conexión) y la versión que corresponde a los toggles.
- Coinciden → guarda `consent_fingerprint`, `consent_declaration_version`, `consented_at`.

Respuestas: `200` + el objeto de §1 (`consent.state = "valid"`); `409 tiktok_options_incomplete`
(opciones sin completar: privacidad, AIGC, disclosure); `409 tiktok_consent_stale` (la huella o
la versión enviadas no coinciden con el estado actual: el usuario debe revisar de nuevo); `409
tiktok_not_connected` / `tiktok_reconnect_required`; `409 publication_not_editable`.

---

## 5. Endpoints genéricos (sin cambios de forma)

| Endpoint | Comportamiento con TikTok |
|---|---|
| `GET /api/publications/{id}/publish-check` | `TikTokPublisher.check()` (sin red salvo la reconciliación de solo lectura de un intento ambiguo). `summary`: cuenta, archivo, caption, privacidad, interacciones, disclosure, AI-generated, declaración aceptada (fecha). Problemas posibles: `tiktok_not_connected`, `tiktok_reconnect_required`, `tiktok_video_required`, `media_unavailable`, `tiktok_video_uninspectable`, `tiktok_video_incompatible`, `tiktok_caption_invalid`, `tiktok_privacy_required`, `tiktok_privacy_not_allowed`, `tiktok_aigc_required`, `tiktok_disclosure_incomplete`, `tiktok_consent_required`. |
| `POST /api/publications/{id}/publish` | Sin cambios de forma. Para TikTok el frontend, al confirmar el diálogo (que muestra la declaración vigente y exige su checkbox aunque ya exista consentimiento), llama antes a `POST tiktok-consent` con la huella/versión mostradas; si responde `409 tiktok_consent_stale` no se publica. `202`. Preflight completo (Creator Info reconsultado, digest del vídeo). Errores adicionales de `prepare`: `tiktok_creator_cannot_post`, `tiktok_privacy_unavailable`, `tiktok_privacy_invalid`, `tiktok_interaction_unavailable`, `tiktok_video_too_long`, `tiktok_video_changed`, `tiktok_rate_limited`, `tiktok_unavailable`, `tiktok_unexpected_response`. Si el último intento es ambiguo: reconciliación de solo lectura y, si sigue ambiguo, `409 remote_check_required` hasta `confirm_remote_checked = true`. |
| `GET /api/publications/{id}/attempts` | `PublicationAttemptRead` existente. `external_id` = post ID solo si TikTok lo devuelve (normalmente `null`); `external_url` siempre `null`; `submitted` sin tokens, URL ni `publish_id`. `error.code` de los códigos de abajo. |
| `PATCH /api/publications/{id}` | Edición de descripción/hashtags (caption) y fecha. Armar (`auto_publish_enabled = true`) consulta `Publisher.arming_problems`: para TikTok `409` con el primer problema (`tiktok_options_incomplete`, `tiktok_caption_invalid`, `tiktok_consent_required`) en el campo `auto_publish_enabled`. Editar metadata material de una publicación TikTok ya armada **no** la desarma: el consentimiento pasa a `stale`, `publish-check` muestra `tiktok_consent_required` y el scheduler no la inicia (error automático genérico, sin efectos remotos) hasta que `POST tiktok-consent` lo reconfirme. |
| `POST /api/contents/{id}/publications` | Crear con `auto_publish_enabled = true` para una o varias cuentas TikTok se rechaza con `409 tiktok_consent_required` (aún no hay revisión ni consentimiento). **Todo o nada** (semántica transaccional existente): no se crea ninguna publicación del lote, tampoco las de otras cuentas; `fields[]` incluye una entrada `account_ids` por cuenta TikTok afectada con un mensaje seguro que la identifica ("TikTok @handle: review the TikTok options and confirm the declaration before enabling auto-publish"). La UI de creación muestra qué destino necesita acción. |

### Códigos de error de intentos TikTok (`PublicationAttemptRead.error.code`)

| Código | Determinado | Significado |
|---|---|---|
| `tiktok_reconnect_required` | sí* | Credencial o permiso rechazados (Feature 012). |
| `tiktok_unavailable` / `tiktok_rate_limited` | sí* | Fallo temporal antes del punto irreversible. |
| `tiktok_unexpected_response` | sí* | Respuesta con forma inesperada. |
| `tiktok_creator_cannot_post` | sí | Cap diario, baneo o cupo de la app. |
| `tiktok_private_account_required` | sí | Cliente no auditado y cuenta pública. |
| `tiktok_privacy_invalid` | sí | `privacy_level_option_mismatch`. |
| `tiktok_init_failed` | sí | `invalid_param`. |
| `tiktok_video_changed` | sí | El archivo ya no coincide con el digest consentido. |
| `tiktok_upload_failed` / `tiktok_upload_expired` | sí | Subida de un chunk intermedio fallida / URL caducada. |
| `tiktok_video_rejected` | sí | `fail_reason` de formato, duración, FPS o tamaño. |
| `tiktok_content_rejected` | sí | `spam_risk_text` / `spam_risk`. |
| `tiktok_publish_failed` | sí | Otro `FAILED` de TikTok (`internal`, `publish_cancelled`, `auth_removed`…). |
| `tiktok_processing_pending` | **no** | TikTok seguía procesando al agotar la espera. |
| `tiktok_result_uncertain` | **no** | El último `PUT` no devolvió `201` (red, timeout, `4xx`, `5xx`, inesperado) y el estado del `publish_id` no se resolvió (`PROCESSING_UPLOAD`, error de lectura o estado inesperado). Un `4xx` final nunca se clasifica como determinado por sí mismo. |
| `interrupted`, `internal_error`, `result_not_saved` | según etapa | Genéricos existentes. |

\* Tras el write-ahead, cualquier fallo de lectura/credencial se convierte en ambiguo
(`tiktok_result_uncertain`).

---

## 6. Frontend (`frontend/src`)

- `types.ts`: `TikTokPublicationOptions`, `TikTokPublicationOptionsWrite`, `TikTokCreatorInfo`,
  `TikTokPrivacyLevel`, `TikTokConsentState`; `PUBLISHING_PLATFORMS` incluye `"tiktok"`.
- `api.ts`: `getTikTokOptions`, `saveTikTokOptions`, `getTikTokCreatorInfo`,
  `confirmTikTokConsent`.
- `utils.ts`: `tiktokCaptionLength(s) = s.length` (unidades UTF-16; mismos casos de prueba que el
  backend, en `utils.test.ts`).
- `components/TikTokPublishOptions.tsx` (+ test): ver plan.md.
- Ningún dato de TikTok en `localStorage`/`sessionStorage` (`storage-safety.test.tsx`).
