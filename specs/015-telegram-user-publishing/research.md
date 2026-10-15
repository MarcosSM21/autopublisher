# Research: Telegram User Account & Publishing

**Feature**: `015-telegram-user-publishing` | **Fecha**: 2026-10-15

Fuentes: código fuente de Telethon 1.45.0 (wheel de PyPI inspeccionado localmente),
documentación de MTProto/Telegram API (`core.telegram.org`) y el código actual de
AutoPublisher (`publishing.py`, `threads_connections.py`, `threads_publishing.py`,
`credential_store.py`). Lo que solo puede confirmarse con la cuenta real se marca
**[V1]** y se valida en el checkpoint (quickstart.md).

---

## §1 Librería: Telethon 1.45.0

- **Decision**: `telethon>=1.45,<2` (1.45.0 publicada el 2026-09-10, "Production/Stable").
  Sin el extra `cryptg`.
- **Rationale**: es la rama estable mantenida; Python puro (`pyaes`, `rsa`), compatible con
  el backend (Python 3.12.12, `requires-python >=3.12`). Para el cifrado AES-IGE usa
  `cryptg` si está instalado, si no `libssl` del sistema por `ctypes` (disponible en Linux) y
  solo en último caso `pyaes`; no hace falta otra dependencia.
- **Typing**: Telethon no publica `py.typed`. Se añade un override de mypy
  (`module = ["telethon", "telethon.*"]`, `ignore_missing_imports = true`) y **solo**
  `app/telegram_gateway.py` importa Telethon; el resto del backend ve tipos propios.
- **Alternatives considered**: Telethon v2 (alpha, API distinta, no estable); Pyrogram
  (abandonado); implementar MTProto (prohibido por la spec); Bot API (prohibido).

## §2 Puente síncrono ↔ asyncio y serialización por cuenta

- **Decision**: `TelegramGateway` expone métodos **síncronos**. Cada operación ejecuta
  `asyncio.run(...)` en el hilo que la llama, crea dentro del bucle un `TelegramClient` con
  `StringSession(<sesión>)`, conecta, hace la operación y desconecta.
- **Rationale**: las rutas existentes son `def` (threadpool de FastAPI) y las subidas corren
  en los hilos daemon de `PublicationRunner`; ninguno tiene un bucle asyncio propio. Un
  cliente por operación evita compartir un cliente entre bucles/hilos y no requiere un hilo
  de bucle permanente. Coste: una conexión (~1 s) por operación, aceptable.
- **Opciones del cliente** (todas fijadas explícitamente, sin depender de defaults):
  - `flood_sleep_threshold=5` (el default de Telethon 1.45 es 60; ver §9);
  - `request_retries=3` (reintentos internos de Telethon de la **misma** petición ante
    `ServerError`/`TimedOutError`, con 2 s de espera);
  - `raise_last_call_error=True` (ver el error real, p. ej. `RandomIdDuplicateError`, en lugar
    de `ValueError("Request was unsuccessful")`);
  - `receive_updates=False` (no se leen chats ni updates);
  - `device_model="AutoPublisher"` (solo visible en "Dispositivos activos" del usuario, nunca
    en el canal).
- **Serialización por cuenta (regla de implementación)**: una misma sesión/autorización de
  Telegram **nunca** se usa desde dos clientes a la vez (Telegram puede rechazarlo con
  `AUTH_KEY_DUPLICATED` y podría mezclar estados de envío).
  - `telegram_connections.py` mantiene un registro en proceso de `threading.Lock` por
    `account_id` (`account_session(account_id, wait=...)`, context manager).
  - **Toda** llamada al gateway que use la sesión guardada de una cuenta se hace dentro de
    ese context manager, que cubre la vida completa del cliente (connect → operación →
    disconnect). Como máximo hay un cliente activo por `Account`; cuentas distintas operan
    en paralelo.
  - Publicación (Publish Now y scheduler, mismo `upload()`): **espera** el lock en bucles de
    1 s comprobando `reporter.should_stop()`. Toda la parte remota de un intento (comprobar
    canal, subir, enviar, repeticiones de §8) ocurre en **una** sección bajo el lock.
    `prepare()` no usa la red, así que nunca toma el lock.
  - Rutas interactivas (Verify, listar canales, cambiar canal, Disconnect): **no esperan**;
    si el lock está ocupado responden `409 telegram_busy`
    ("Telegram is busy with another operation of this account. Try again in a moment.").
  - Login: los pasos `start`/`code`/`password` usan una sesión parcial nueva (otra auth key),
    pero también se ejecutan bajo el lock de la cuenta para que la escritura final del secreto
    no compita con una publicación o un Disconnect.
  - Esto vive solo en la integración Telegram; el scheduler y el core genérico no cambian
    (el core ya impide dos intentos simultáneos de la misma `Publication`; el lock cubre el
    resto de carreras dentro de una misma cuenta).
- **Alternatives considered**: hilo con bucle asyncio permanente y cliente persistente (más
  estado, reconexiones y ciclo de vida a gestionar); rutas `async` (rompe el patrón del
  proyecto); locks en base de datos (innecesario: un solo proceso local).

## §3 Credenciales de aplicación (`api_id`, `api_hash`)

- **Decision**: archivo local `backend/data/telegram-app.json`
  (`{"api_id": 12345, "api_hash": "..."}`), con override
  `AUTOPUBLISHER_TELEGRAM_APP_FILE`, leído en cada uso como `threads-app.json` y
  `tiktok-app.json`. `api_hash` nunca se registra ni se devuelve. `.gitignore` añade
  `telegram-app*.json` (además, `data/` ya está ignorado).
- **Rationale**: mismo patrón que el resto de plataformas; sin `.env` real.

## §4 Login de usuario (teléfono → código → 2FA)

- **Decision**: registro **en memoria** de logins pendientes por `account_id`
  (`TelegramLoginRegistry`, TTL 10 min). Pasos:
  1. `start(phone)`: cliente con `StringSession()` vacío → `connect()` →
     `send_code_request(phone)`; se guardan en memoria la sesión parcial
     (`client.session.save()`), el teléfono y `phone_code_hash`. Telethon gestiona
     `PHONE_MIGRATE` cambiando de DC; la sesión guardada ya refleja el DC correcto.
  2. `code(code)`: cliente desde la sesión parcial →
     `sign_in(phone, code, phone_code_hash=...)`. Si lanza `SessionPasswordNeededError`,
     el login pasa a `password` (se vuelve a guardar la sesión parcial).
  3. `password(password)`: cliente desde la sesión parcial → `sign_in(password=...)`.
  4. Con el usuario autorizado: `get_me()` → identidad; la sesión final se guarda en el
     almacén seguro (§5) y se crea/actualiza la fila de conexión.
- Código y contraseña solo viven en la petición HTTP; nunca se guardan ni registran.
  La sesión parcial (contiene una auth key) solo vive en memoria y se descarta al terminar,
  cancelar o expirar.
- Un reinicio del backend pierde los logins pendientes: el usuario empieza de nuevo
  (FR-006).
- **Reconexión** (`reconnect_required`): mismo flujo. Si el Telegram user ID obtenido es
  distinto del guardado → `409 telegram_identity_mismatch` (hay que desconectar primero);
  el canal elegido pertenece a la otra identidad.
- **Alternatives considered**: `client.start()` interactivo (pensado para consola); login
  por QR (posible mejora futura, no pedido).

## §5 Sesión en el almacén seguro

- **Decision**: `StringSession` serializada (DC, IP/puerto y auth key) guardada con
  `KeyringCredentialStore("autopublisher.telegram")` bajo un `credential_ref` aleatorio
  (UUID), con valor JSON `{"v": 1, "session": "...", "user_id": "..."}`. SQLite solo guarda
  el `credential_ref`. Nunca se usa `SQLiteSession` ni ningún archivo `.session`.
- `StringSession` es una `MemorySession`: la caché de entidades no se persiste, por eso el
  canal se localiza con su `access_hash` guardado (§7).
- `.gitignore` añade `*.session` y `*.session-journal` como red de seguridad.
- Sin backend seguro disponible → `503 credential_store_unavailable` (comportamiento
  existente; no hay fallback).

## §6 Verify y Disconnect

- **Verify**: `get_me()` con la sesión guardada. `AuthKeyUnregisteredError`,
  `SessionRevokedError`, `UserDeactivatedError` (y otros `UnauthorizedError`) →
  `status = reconnect_required`. Si el user ID devuelto no coincide con el guardado →
  `reconnect_required`. Éxito → actualiza nombre/username y `last_verified_at`.
- **Disconnect** (semántica segura):
  1. `log_out()` (`auth.logOut`) revoca la sesión en Telegram.
  2. Si Telegram responde que la sesión ya no es válida (`UnauthorizedError`), se considera
     revocada.
  3. Solo entonces se borra el secreto del almacén y después la fila.
  4. Si Telegram **no es alcanzable** → `503 telegram_unavailable` y **no** se borra nada
     (la sesión seguiría viva en Telegram). El mensaje indica que puede reintentar o cerrar
     la sesión "AutoPublisher" desde *Ajustes → Dispositivos* en Telegram y volver a pulsar
     Disconnect (entonces el paso 2 la detecta revocada).
  5. Si el almacén seguro falla tras el `log_out` → `503 credential_store_unavailable`; la
     fila se conserva para reintentar (el reintento detecta la sesión revocada).
- Nada de esto toca otras plataformas.

## §7 Canales: descubrimiento, identidad y permiso

- **Listado**: `iter_dialogs()` filtrando entidades `Channel` con `broadcast=True`,
  `left=False` y (`creator=True` o `admin_rights.post_messages=True`). Excluye grupos,
  megagroups/supergrupos, forums y usuarios.
- **Identidad estable**: `channel_id` + `access_hash` (el `access_hash` es estable para esa
  cuenta y necesario para construir `InputPeerChannel` sin caché). Se guardan en la fila de
  conexión. `access_hash` no es una credencial por sí solo (inútil sin la auth key), pero se
  trata como interno: nunca se devuelve por la API.
- **Selección**: `PUT .../channel {channel_id}` vuelve a listar los canales en el servidor
  y toma el `access_hash` de ahí; el frontend solo maneja `channel_id`.
- **Permiso en cada publicación**: dentro de `upload()`, bajo el lock de la cuenta (§2) y con
  el mismo cliente que envía, `channels.getChannels([InputChannel])` devuelve el canal
  actual: se comprueba `broadcast`, no `left` y permiso de publicar; se refrescan título y
  username. `prepare()` no usa la red. `ChannelPrivateError`/`ChannelInvalid` → canal no accesible.
- **Bloqueo de cambio** (FR-014a): `PUT .../channel` → `409 telegram_channel_change_blocked`
  si existe alguna `Publication` de ese `account_id` en `scheduled` o `publishing`.

## §8 Envío y anti-duplicados (`random_id`)

Hechos (documentación oficial de Telegram y código de Telethon 1.45.0):

- `random_id` deduplica envíos hacia el **mismo peer**. Los `random_id` ya usados que guarda
  el servidor **no expiran**.
- Repetir un envío con un `random_id` ya usado normalmente **devuelve el mensaje generado
  anteriormente** (los mismos `Updates`, con `UpdateMessageID(id, random_id)`).
- `RANDOM_ID_DUPLICATE` (`RandomIdDuplicateError`, subclase de `ServerError`) puede aparecer
  cuando el envío anterior con ese ID **todavía está en curso**. No significa por sí solo que
  el mensaje exista.
- `send_message` / `send_file` de Telethon generan su propio `random_id` y **no** permiten
  fijarlo; `messages.SendMessageRequest` y `messages.SendMediaRequest` sí lo aceptan.
- Telethon reenvía el **mismo objeto de petición** (mismo `random_id`) en reconexiones del
  transporte y en sus `request_retries` ante `ServerError`/`TimedOutError`.

**Decision**:

1. **Identidad de envío estable**: `prepare()` genera `random_id = secrets.randbits(63)` y lo
   incluye en `PreparedPublication.submitted` (`telegram_random_id`). El core persiste
   `submitted` al crear el intento → **write-ahead sin cambios en el núcleo**. No es un
   secreto. Nunca se genera otro `random_id` para resolver una duda sobre ese intento.
2. **Reutilización tras incierto**: si el último intento de esa misma `Publication` es
   Telegram, quedó **incierto** (`outcome_determined = false`) y tiene `telegram_random_id`,
   el nuevo intento **reutiliza ese `random_id`** (tras el "remote check" genérico que el core
   ya exige). Como el servidor no olvida el ID, el resultado es exactamente un mensaje: o se
   crea ahora, o Telegram devuelve el original y se guarda su message ID.
3. **Orden**: bajo el lock de la cuenta (§2) se comprueba el canal, se sube el archivo con
   `upload_file()` (sin efecto visible), se llama a `reporter.enter_finalizing()` y solo
   entonces se envía `SendMessageRequest` / `SendMediaRequest` con ese `random_id`.
4. **Repetición acotada con el mismo `random_id`** (solo tras `finalizing`): si el envío
   termina en `RandomIdDuplicateError` (después de los `request_retries` de Telethon) o en un
   error de red/timeout/desconexión, la integración repite **la misma petición** (mismo
   `random_id`, reconectando si hace falta) como máximo **2 veces más**, esperando 3 s y
   10 s. Total acotado; sin listar mensajes ni leer el historial del canal.
5. **Confirmación**: solo cuenta como éxito una respuesta que contenga
   `UpdateMessageID` con nuestro `random_id` (o el mensaje original devuelto por la
   repetición) → intento `succeeded`, `PUBLISHED`, `external_id = message_id`.
6. **Sin confirmación suficiente** (repeticiones agotadas con `RANDOM_ID_DUPLICATE` o errores
   de red, o una respuesta sin `UpdateMessageID` reconocible) →
   `PublishFailure("telegram_unconfirmed", ..., determined=False)` → semántica genérica de
   resultado incierto ("may have been published; check the channel before publishing
   again"). Nunca se marca `PUBLISHED` sin message ID.
7. `reconcile()` devuelve `None` (no hay reconciliación de lectura); `follow_up()` no aplica.
   Un reinicio con el intento en `finalizing` lo cierra la recuperación genérica como
   incierto; el siguiente intento reutiliza el `random_id` (punto 2).

- **Alternatives considered**: tratar `RANDOM_ID_DUPLICATE` como éxito (descartado: puede
  significar "aún en curso"); reconciliación leyendo mensajes recientes del canal (la spec la
  descarta); `send_file` de alto nivel (no permite fijar `random_id`); nuevo `random_id` en
  cada intento (rompería la deduplicación entre intentos).

## §9 FloodWait

- **Decision**: el cliente se crea **siempre** con `flood_sleep_threshold=5` explícito (no se
  depende del default 60 de Telethon 1.45):
  - **≤ 5 s**: Telethon espera automáticamente y repite la petición.
  - **> 5 s**: Telethon lanza `FloodWaitError` con `.seconds`:
    - en login/verify/canales: `429 telegram_rate_limited` con
      "Telegram asks to wait N seconds before trying again.";
    - en publicación: `PublishFailure("telegram_rate_limited", ..., determined=True)` (la
      petición fue rechazada, no hay mensaje) y se guarda
      `flood_wait_until = now + seconds` en la conexión (cooldown local).
  - `check()` añade el problema `telegram_rate_limited` mientras `flood_wait_until` no haya
    pasado, de modo que ni `Publish now` ni el scheduler reintentan antes de tiempo.
- Un FloodWait durante una repetición de §8.4 (ya en `finalizing`) no confirma nada: el
  intento queda **incierto** (§8.6) y el cooldown se guarda igualmente; el siguiente intento
  reutiliza el mismo `random_id`.
- `SlowModeWaitError` no aplica a canales broadcast.

## §10 Contenido, límites y preflight

- **Texto**: igual que Threads, `description_with_hashtags(effective description, hashtags)`;
  el título no se envía. Sin `parse_mode`: texto plano, sin entidades.
- **Límites** (cuenta normal; Premium no se detecta en V1):
  - mensaje de texto: 4096; caption: 1024. Se cuentan en **unidades UTF-16** (como cuenta
    Telegram); vacío solo se permite con media.
  - Si se supera → problema de preflight `telegram_text_too_long`; nunca se trunca.
- **Imagen** (como foto, `InputMediaUploadedPhoto`): JPEG, PNG, WEBP; ≤ 10 MB;
  ancho + alto ≤ 10000; relación de aspecto ≤ 20. Fuera de eso →
  `telegram_media_unsupported` (no se convierte ni se envía como documento). Telegram
  recomprime fotos por su cuenta (comportamiento normal de una publicación manual).
- **Vídeo** (`InputMediaUploadedDocument`, `video/mp4`, `DocumentAttributeVideo(duration,
  w, h, supports_streaming=True)` con los metadatos ya guardados en `Content`, y
  `DocumentAttributeFilename("video.mp4")` para no filtrar el nombre original): solo **MP4**
  en V1. MOV/WEBM → `telegram_media_unsupported`. Tamaño ≤ 2 000 MiB (4000 partes de
  512 KiB). Sin miniatura propia: **[V1]** comprobar que Telegram muestra vista previa.
- **Archivo**: `file_available` existente → `media_unavailable` (código genérico).
- **Progreso**: `upload_file(progress_callback=...)` → `reporter.report_bytes(sent)`; el
  callback también comprueba `reporter.should_stop()` y aborta la subida (fallo determinado,
  aún no hay mensaje).

## §11 Resultado remoto y enlace

- `external_id = str(message_id)`.
- `external_url = https://t.me/<username>/<message_id>` **solo** si el canal tiene username
  público (leído en `upload()` al comprobar el canal). Canales privados: sin URL (no se usan enlaces `t.me/c/...`,
  válidos solo para miembros).
- `details`: `{"channel_id", "channel_title"}` (no sensibles).

## §12 Mapeo de errores (pequeño)

| Situación (Telethon) | Código | `determined` |
|---|---|---|
| `UnauthorizedError` (`AuthKeyUnregistered`, `SessionRevoked`, `UserDeactivated`…) | `telegram_reconnect_required` + conexión a `reconnect_required` | sí |
| `ChatWriteForbidden`, `ChatAdminRequired`, sin `post_messages` | `telegram_channel_unavailable` | sí |
| `ChannelPrivate`, `ChannelInvalid`, `left` | `telegram_channel_unavailable` | sí |
| `MessageTooLong`, `MediaCaptionTooLong`, `MessageEmpty` | `telegram_text_too_long` / `telegram_text_invalid` | sí |
| `PhotoInvalidDimensions`, `PhotoSaveFileInvalid`, `FilePartsInvalid`, `MediaInvalid` | `telegram_media_rejected` | sí |
| `FloodWaitError` / `FloodPremiumWaitError` | `telegram_rate_limited` | sí |
| `OSError`/`ConnectionError`/timeout **antes** de `finalizing` | `telegram_unavailable` | sí |
| Red/timeout o `RandomIdDuplicateError` **después** de `finalizing`, tras la repetición acotada (§8.4) | `telegram_unconfirmed` | **no** (incierto genérico) |
| Respuesta al envío sin `UpdateMessageID` con nuestro `random_id` | `telegram_unconfirmed` | **no** |
| Login: `PhoneNumberInvalid`, `PhoneCodeInvalid`, `PhoneCodeExpired`, `PasswordHashInvalid`, `PhoneNumberBanned` | `422 telegram_login_invalid` con mensaje específico | — |

Mensajes en inglés, sin texto crudo de Telegram (solo el nombre de clase en logs).

## §13 Logs y secretos

- `logging.getLogger("telethon").setLevel(logging.WARNING)`.
- Nunca se registran mensajes de excepciones de Telethon; solo `type(exc).__name__`
  (patrón existente).
- Teléfono: no se persiste. La respuesta de la API puede mostrar una versión enmascarada
  (`+34 ••• •• 12`) mientras el login está pendiente.
- Tests de ausencia de secretos: la sesión, `api_hash`, código y contraseña de los fakes no
  aparecen en SQLite, respuestas ni logs capturados.

## §14 Riesgos conocidos

- Telegram puede limitar o marcar cuentas que usan `api_id` recién creados con clientes no
  oficiales; se usa la cuenta real con volumen muy bajo y sin automatizaciones masivas.
- Autor visible: en canales broadcast los mensajes aparecen como el canal (y con firma solo
  si el canal tiene "Sign messages" activo); **[V1]** confirmar visualmente.
- Sin miniatura de vídeo propia: **[V1]**.

## §15 Fuera de alcance confirmado

Scheduling nativo (`schedule_date`, posible mejora futura), `send_as`, álbumes, grupos,
supergrupos, forums, DMs, edición/borrado remoto, login por QR, detección de Premium,
miniaturas de vídeo, MOV/WEBM.
