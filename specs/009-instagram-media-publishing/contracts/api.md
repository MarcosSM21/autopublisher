# API Contract: publicación real de imágenes y Reels en Instagram

**Feature**: `009-instagram-media-publishing` | **Fecha**: 2026-10-08

Amplía la API REST bajo `/api`. Fechas en ISO 8601 UTC. Formato de error existente:
`{"error": {"code", "message", "fields": []}}`.

**Regla transversal**: ninguna respuesta contiene tokens de Instagram, cabeceras
`Authorization`, credenciales o configuración del proveedor de media delivery, URLs
temporales (firmadas o no), claves de objeto temporales ni respuestas crudas de Meta.

---

## Endpoints existentes reutilizados (sin cambios de forma)

| Endpoint | Cambio para Instagram |
|---|---|
| `GET /api/publications/{id}/publish-check` | `problems` incluye los de Instagram (tabla de errores); `summary` incluye las filas de Instagram (abajo). Puede reconciliar antes un último intento ambiguo (ver *Reconciliación*). |
| `POST /api/publications/{id}/publish` (`{"confirm_remote_checked": bool}`) | Ejecuta Instagram con el mismo flujo: 202 + `PublicationRead`. Errores de preflight como hoy. |
| `GET /api/publications/{id}/attempts` | `stage` admite `processing` y `finalizing`; `platform = "instagram"`. |
| `GET /api/publications`, `GET /api/publications/{id}` | `latest_attempt` con los mismos campos. |
| Scheduler / automatización (Feature 007) | Sin cambios: ejecuta Instagram a través del mismo servicio. |

`summary` de `publish-check` para Instagram (pares etiqueta/valor):

```json
[
  {"label": "Post type", "value": "Image Post"},
  {"label": "Instagram account", "value": "cyber.studio (1784...)"},
  {"label": "Caption", "value": "<caption exacto>"},
  {"label": "AI-generated", "value": "No"},
  {"label": "Alt text", "value": "<texto o 'None'>"},
  {"label": "File", "value": "poster.png (2.3 MB) → sent as JPEG"}
]
```

Para Reel: `"Post type": "Reel"`, `"Share to feed": "Yes"`, sin `Alt text`.

### PublicationAttempt (cambios)

- `stage`: `preparing` | `uploading` | `processing` | `finalizing` | `final_chunk` | `done`.
- `progress` (cambio genérico, todas las plataformas): `1.0` solo si `status =
  "succeeded"`; en cualquier otro caso `min(bytes_sent / total_bytes, 0.99)`. Un intento
  `running` nunca expone `1.0`. La interfaz solo muestra el porcentaje en `uploading`.
- `external_id`: Instagram media ID; `external_url`: permalink (o perfil si
  `permalink_unavailable`).
- **Publicación confirmada sin identidad remota**: `status = "succeeded"`,
  `outcome_determined = true`, `external_id = null`, `external_url = null` y el aviso
  `remote_identity_unavailable`; la publicación queda `published` (no hay enlace
  `Open on Instagram`; la interfaz muestra el aviso con la cuenta, la hora y el caption para
  buscar el post manualmente). AutoPublisher nunca rellena estos campos con un ID inferido.
- `warnings[].code` nuevos: `temporary_media_cleanup_failed`, `permalink_unavailable`,
  `remote_identity_unavailable`.
- Un aviso de limpieza **nunca** cambia `status`.

### Reconciliación antes de `remote_check_required` (FR-046a, research §11b)

`GET /api/publications/{id}/publish-check` y `POST /api/publications/{id}/publish`
ejecutan primero, si la publicación está `failed` y su último intento es ambiguo
(`requires_manual_review = true`), la reconciliación del publisher de su plataforma. Para
Instagram solo actúa si el run alcanzó la fase final con `container_id` conocido, y hace una
única lectura del `status_code` del container original:

- **`PUBLISHED`** → sin pedir confirmación: la publicación pasa a `published`, el intento
  original a `succeeded` (`outcome_determined = true`, `error = null`, `external_id = null`,
  `external_url = null`, aviso `remote_identity_unavailable`). `publish-check` devuelve
  `eligible = false` con el problema `publication_not_eligible` y `requires_remote_check =
  false`; `publish` responde `409 publication_not_eligible`. No se crea ningún intento nuevo.
- **Cualquier otro resultado** (otro estado, error de Meta, credencial inutilizable) → nada
  cambia: `requires_remote_check = true` y `publish` sin `confirm_remote_checked` responde
  `409 remote_check_required`.

**Nota sobre la mutación en un GET**: `GET /publish-check` puede materializar localmente una
reconciliación remota confirmada. Es intencionado y acotado a este caso porque la operación
es idempotente (repetir el GET produce el mismo resultado), solo hace lecturas en Meta, nunca
crea un container ni ejecuta `media_publish` y solo persiste localmente un hecho que la
plataforma ya confirma (`container = PUBLISHED`). Esta política no se generaliza a otros GET.

La reconciliación nunca llama a `media_publish`, nunca crea containers y nunca consulta la
lista de publicaciones. Es una única lectura por petición, solo para reconciliar un
resultado ambiguo; no hay polling remoto pasivo. `published_at` de una publicación
reconciliada es aproximado: la hora del write-ahead (`publish_started_at`), no la hora real
de publicación en Instagram. Es la única situación en la que `publish-check` contacta con Meta;
en cualquier otro caso sigue sin red. YouTube no reconcilia (comportamiento sin cambios).

### Mensaje `remote_check_required` (generalizado)

El texto deja de mencionar "video"/"channel": *"The last attempt may have published this
content. Check the platform (account, caption or title and time of the attempt) and confirm
before publishing again."* El código no cambia.

---

## Nuevos endpoints

### `GET /api/publications/{publication_id}/instagram-options`

Opciones de Instagram, caption final y compatibilidad local del media. Sin red (no contacta
con Meta ni con el proveedor de media delivery).

**200**

```json
{
  "media_kind": "image",
  "caption": "Summer drop.\n\n#cyber #studio",
  "caption_length": 29,
  "caption_hashtags": 2,
  "caption_mentions": 0,
  "is_ai_generated": null,
  "share_to_feed": null,
  "alt_text": null,
  "complete": false,
  "editable": true,
  "media_delivery_configured": true,
  "problems": [
    {"code": "instagram_options_incomplete", "field": "is_ai_generated",
     "message": "Declare whether the content is AI-generated."}
  ],
  "limits": {"caption_characters": 2200, "caption_hashtags": 30,
             "caption_mentions": 20, "alt_text_characters": 1000}
}
```

- `media_kind`: `image` | `reel` | `null` (Content no soportado).
- `share_to_feed`: `bool` solo para `reel` (default `true` si no hay fila); `null` en imagen.
- `alt_text`: `string | null` solo para `image`; `null` en Reel.
- `complete`: `is_ai_generated` declarado.
- `problems`: problemas de Instagram detectables localmente (caption, opciones,
  compatibilidad del media, media delivery), mismo formato que `publish-check`.

**Errores**: `404 not_found`; `409 platform_not_supported` (la cuenta no es Instagram).

### `PUT /api/publications/{publication_id}/instagram-options`

```json
{"is_ai_generated": true, "share_to_feed": false, "alt_text": "A neon sign at night"}
```

- `is_ai_generated`: `bool | null` (null = sin declarar).
- `share_to_feed`: `bool`, opcional; solo aceptado si `media_kind = reel`.
- `alt_text`: `string | null`, opcional; solo aceptado si `media_kind = image`; se recorta;
  vacío → `null`; máx. 1000 caracteres.

**200**: la misma representación que `GET`.

**Errores**:

| Estado | Código | Cuándo |
|---|---|---|
| 404 | `not_found` | publicación inexistente |
| 409 | `platform_not_supported` | no es una cuenta Instagram |
| 409 | `publication_not_editable` / `publication_cancelled` | `publishing`, `published` o `cancelled` (reglas de `ensure_editable`) |
| 422 | `instagram_option_not_applicable` | `share_to_feed` en imagen o `alt_text` en Reel (`fields` indica cuál) |
| 422 | `validation_error` | `alt_text` > 1000 caracteres o tipos inválidos |

---

## Errores de preflight y de ejecución (Instagram)

Preflight (`publish-check`, `publish`, scheduler). Orden: genéricos de la Feature 006/007,
después los de Instagram en este orden.

| Estado | Código | Cuándo |
|---|---|---|
| 409 | `instagram_media_unsupported` | Content que no es imagen ni vídeo individual |
| 409 | `media_unavailable` | archivo inexistente o cambiado (existente) |
| 409 | `instagram_image_incompatible` | formato, tamaño, aspect ratio, transparencia, animación o CMYK (`fields`: `media`) |
| 409 | `instagram_video_incompatible` | requisito de Reel incumplido; el mensaje nombra el requisito |
| 409 | `instagram_media_unverifiable` | no se puede inspeccionar el vídeo (sin `ffprobe`) |
| 409 | `instagram_caption_invalid` | longitud, hashtags o menciones (`fields`: `caption`) |
| 409 | `instagram_options_incomplete` | `is_ai_generated` sin declarar |
| 503 | `media_delivery_not_configured` | sin configuración válida de media delivery |
| 409 | `instagram_not_connected` | sin conexión (Feature 008) |
| 409 | `instagram_reconnect_required` | conexión `Reconnect required` o credencial inutilizable |
| 409 | `instagram_identity_mismatch` | la cuenta autorizada ya no es la vinculada |
| 409 | `instagram_account_not_professional` | ya no es Business/Creator |
| 503 | `credential_store_unavailable` | almacén seguro no disponible |
| 503 | `instagram_unavailable` | Meta temporalmente inaccesible en una lectura de preflight |
| 409 | `instagram_publishing_limit_reached` | `quota_usage >= quota_total` según Meta |
| 409 | `instagram_already_published` | el container del intento anterior figura como `PUBLISHED` |
| 409 | `remote_check_required` | último intento ambiguo que la reconciliación no pudo resolver (el container no confirmó `PUBLISHED`), sin `confirm_remote_checked` (existente) |

Ejecución (se ven en `PublicationAttempt.error`, publicación `failed`):

| Código | Determinado | Significado |
|---|---|---|
| `media_delivery_failed` | sí | no se pudo subir el media al proveedor; no existe container |
| `instagram_container_failed` | sí | Meta rechazó crear el container |
| `instagram_media_fetch_failed` | sí | Meta no pudo descargar el media |
| `instagram_media_rejected` | sí | Meta rechazó el media (formato/tamaño/aspect) |
| `instagram_processing_failed` | sí | container en `ERROR` |
| `instagram_processing_timeout` | sí | el container no terminó a tiempo; no se publicó |
| `instagram_container_expired` | sí | container caducado |
| `instagram_publishing_limit_reached` | sí | Meta rechazó `media_publish` por cuota |
| `instagram_account_restricted` | sí | cuenta restringida por Instagram |
| `instagram_reconnect_required` | sí | credencial invalidada; la conexión pasa a `Reconnect required` |
| `instagram_unavailable` | sí | error temporal antes de `media_publish` |
| `instagram_publish_failed` | sí | rechazo explícito de `media_publish` y container no publicado |
| `instagram_publish_uncertain` | **no** | `media_publish` sin respuesta concluyente y el container no confirma `PUBLISHED` (cualquier otro estado, incluidos `ERROR`/`EXPIRED`, fallo de consulta o sin respuesta); revisar Instagram (el mensaje incluye cuenta, hora y caption como ayuda). Nuevo intento solo con `confirm_remote_checked` |

Si el container original confirma `PUBLISHED`, no hay error: el intento termina `succeeded`
sin identidad remota (ver *PublicationAttempt (cambios)*).
| `interrupted` | según etapa | genérico: reinicio durante la ejecución |
| `result_not_saved` | **no** | genérico: no se pudo guardar el resultado |

Los mensajes son en inglés, comprensibles y sin datos crudos de Meta, URLs ni IDs de media.
