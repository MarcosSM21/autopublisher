# Quickstart: validar la publicación manual en YouTube

**Feature**: `006-youtube-manual-publishing` | **Fecha**: 2026-10-07

Guía para comprobar la feature de extremo a extremo. Las comprobaciones automáticas usan un
simulador de YouTube y no necesitan Internet. La validación con YouTube real (§3–§6) es
**manual**, sube un vídeo de verdad y no se ejecuta en CI.

Referencias: [contracts/api.md](contracts/api.md), [data-model.md](data-model.md),
[research.md](research.md).

---

## 1. Comprobaciones automáticas

```bash
cd backend
uv sync
uv run pytest                 # incluye el simulador de subida resumible, sin Internet
uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm ci
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

Resultado esperado: todo en verde, también sin red.

## 2. Requisitos para la validación manual

- Todo lo de la validación manual de la Feature 005
  (`specs/005-youtube-oauth-connection/quickstart.md` §2): proyecto de Google Cloud con
  YouTube Data API v3, cliente Desktop en `backend/data/google-oauth-client.json`, scopes
  `youtube.readonly` + `youtube.upload`, almacén seguro operativo.
- Una cuenta YouTube **conectada** en AutoPublisher (`Connected`).
- Un **vídeo pequeño de prueba** (unos pocos MB, `mp4`, `mov` o `webm`) sin contenido
  sensible, importado como `Content` con título.
- Anotar su checksum antes de empezar:

  ```bash
  sha256sum backend/data/media/projects/<project_id>/<file>   # ruta en la tabla contents
  ```

- **Cuota**: consultar la cuota vigente de `videos.insert` en
  <https://developers.google.com/youtube/v3/docs/videos/insert> (a 2026-10-07: 1 unidad en el
  bucket "Video Uploads"). Google puede cambiarla.

> **Proyectos no verificados**: desde el 28-07-2020, los vídeos subidos con `videos.insert`
> desde proyectos API no verificados quedan restringidos a **privado** hasta superar la
> auditoría de YouTube. Por eso esta guía usa siempre `private`.

### Arranque

```bash
cd backend && uv run uvicorn app.main:app --reload    # http://127.0.0.1:8000
cd frontend && npm run dev                              # http://localhost:5173
```

## 3. Flujo principal (SC-001)

| # | Acción | Resultado esperado |
|---|--------|--------------------|
| 1 | Desde el contenido de vídeo, crear una publicación para la cuenta YouTube conectada (sin fecha). Abrirla desde la Queue. | Estado `Unscheduled`. Se ven el título, la descripción, los hashtags efectivos y la sección **YouTube options**: privacidad `private`, Notify subscribers `No`, Made for Kids y Altered/synthetic content **sin declarar**, con la nota sobre proyectos no verificados. |
| 2 | Comprobar que **Publish now** está deshabilitado. | Se explica que faltan las declaraciones de Made for Kids y de contenido sintético. |
| 3 | Declarar Made for Kids = `No` y Altered/synthetic = `No`; dejar `private` y Notify subscribers = `No`; guardar. | Opciones guardadas. **Publish now** se habilita. |
| 4 | Pulsar **Publish now**. | Diálogo de confirmación con: título efectivo, canal (título y channel ID), privacidad `private`, Notify subscribers `No`, Made for Kids, contenido sintético y archivo. **Confirmar que el channel ID es el del canal de pruebas** (comparar con YouTube Studio → Settings → Channel → Advanced). |
| 5 | Pulsar **Cancel** en el diálogo. | No pasa nada: sigue `Unscheduled`, sin intentos. |
| 6 | Pulsar **Publish now** de nuevo y confirmar. Hacer doble clic rápido en el botón de confirmar. | La publicación pasa a `Publishing` en < 2 s (más la verificación con Google). El progreso (porcentaje y bytes) avanza al menos cada 5 s. Solo hay **un** intento. |
| 7 | Esperar a que termine. | `Published`, con fecha de publicación, enlace **Open on YouTube**, privacidad real devuelta (`private`) y estado inicial de procesamiento si YouTube lo da. |
| 8 | Pulsar **Open on YouTube**. | Se abre `https://www.youtube.com/watch?v=<video ID>` con el vídeo (privado: visible solo con la cuenta propietaria). |
| 9 | En YouTube Studio → Content, comprobar el vídeo. | Existe una única copia, con el título y la descripción enviados (hashtags al final, tras una línea en blanco), privacidad `Private`, audiencia "No, it's not made for kids" y contenido alterado "No". Los suscriptores no han recibido notificación. |
| 10 | Volver a calcular el checksum del archivo local. | Idéntico al anotado en §2. |
| 11 | Inspeccionar la base de datos y los logs (§5). | Video ID y URL guardados; ningún secreto ni URI de sesión. |
| 12 | Parar y volver a arrancar backend y frontend. | La publicación sigue `Published` con el mismo video ID, URL, privacidad e intento. |
| 13 | Intentar editar la fecha, la metadata o las opciones YouTube de la publicación, o cancelarla. | No se ofrecen; si se fuerza por API: `409 publication_not_editable`. |

## 4. Publicación programada publicada antes de hora (US6) y no-scheduler (SC-012)

| # | Acción | Resultado esperado |
|---|--------|--------------------|
| 1 | Crear otra publicación del mismo vídeo (otro contenido o tras la anterior) con fecha dentro de 3 minutos, opciones completas. | `Scheduled`. |
| 2 | Esperar a que pase la fecha sin hacer nada. | Sigue `Scheduled`: **no se ejecuta sola**. |
| 3 | Crear otra programada para mañana y pulsar **Publish now**. | La confirmación avisa de que está programada para mañana y que se publicará **ahora**. |
| 4 | Confirmar y esperar. | `Published`; conserva la fecha programada como dato histórico; no vuelve a ejecutarse. |

## 5. Inspección de secretos

```bash
sqlite3 backend/data/autopublisher.db \
  "SELECT id, publication_id, status, stage, error_code, outcome_determined, external_id, external_url FROM publication_attempts;"
sqlite3 backend/data/autopublisher.db \
  "SELECT publication_id, privacy_status, made_for_kids, contains_synthetic_media, notify_subscribers FROM youtube_publication_options;"
# Sin tokens ni URIs de sesión en ningún sitio:
sqlite3 backend/data/autopublisher.db .dump | grep -E 'ya29\.|1//|upload_id' || echo "no secrets in SQLite"
```

- En la salida del backend: buscar `upload_id`, `Bearer` y `ya29.`. Las URLs de subida
  aparecen como `upload_id=[redacted]`. Los mensajes de error de publicación tampoco
  contienen el video ID.
- En las herramientas de desarrollo del navegador (Network): ninguna respuesta contiene
  `upload_id`, `Location` de la sesión ni tokens.

## 6. Errores y casos límite (manual, opcional)

| Caso | Cómo provocarlo | Esperado |
|------|-----------------|----------|
| Imagen | Crear una publicación de una imagen para la cuenta YouTube. | **Publish now** no disponible: "YouTube only accepts video content". |
| Archivo ausente | Renombrar temporalmente el archivo del contenido y pulsar **Publish now**. | `409 media_unavailable` antes de contactar con YouTube; sigue `Unscheduled`. |
| Título largo | Override de título de 101 caracteres. | **Publish now** deshabilitado con "Title must be at most 100 characters for YouTube". |
| `<` en la descripción | Override de descripción con `<b>`. | Igual, con el problema de la descripción. |
| Cuenta a reconectar | Retirar el acceso en myaccount.google.com/connections y pulsar **Publish now**. | `Reconnect required`; no se sube nada. |
| Corte de red recuperable | Durante la subida de un vídeo algo mayor, desconectar la red ~10 s y volver a conectarla. | El progreso se detiene y continúa desde el último byte confirmado; termina `Published` con **un** intento y **un** vídeo en YouTube Studio. |
| Corte de red prolongado | Desconectar la red > 2 min durante la subida. | `Failed` con "network error"; si fue antes del último fragmento, sin revisión manual; **Publish now** vuelve a estar disponible. |
| Reinicio durante la subida | Parar el backend (Ctrl+C) a mitad de la subida y arrancarlo. | `Failed` con "interrupted". Si el corte fue antes de confirmar la fase del último fragmento (`stage` ≠ `final_chunk`): resultado determinado. Si no: revisión manual, con canal, título y momento aproximado para localizar el vídeo en YouTube Studio, y casilla obligatoria para volver a publicar. **No se resube nada automáticamente.** |
| Desconectar durante la subida | Pulsar **Disconnect** en la cuenta mientras sube. | `409 publication_in_progress`. |
| Privacidad `public` en proyecto no verificado | Publicar otro vídeo con `public`. | `Published` con privacidad real `private` y el aviso de que YouTube aplicó otra privacidad. |

Al terminar, borrar los vídeos de prueba manualmente en **YouTube Studio**: AutoPublisher no
implementa borrado remoto.

## 7. Resultado

La feature se considera validada cuando §1 pasa completo y §3–§5 se cumplen con YouTube real.
Anotar en el PR: tiempo hasta `Publishing` y cadencia observada del progreso. No incluir
video IDs ni URLs de vídeos en el PR.

**Validación de `categoryId`** (research §12): comprobar explícitamente que la subida real
funciona **sin** enviar `categoryId`, tal como está diseñada.

- Si funciona: registrar en el PR que la decisión "upload sin `categoryId`" quedó
  **validada**.
- Si YouTube rechaza la subida específicamente por falta de `categoryId`: **detener** la
  validación y reportar el error (código HTTP, motivo y mensaje mostrado por AutoPublisher,
  sin secretos ni respuestas crudas de Google), **sin modificar código**. La decisión se
  revisa en spec y plan antes de continuar.
- No introducir ninguna categoría durante la validación manual.
