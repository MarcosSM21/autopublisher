# Feature Specification: Send to Phone

**Feature Branch**: `029-send-to-phone`

**Created**: 2026-11-02

**Status**: Implemented

**Input**: User description: "Feature 029 — Send to Phone (MVP deliberadamente mínimo). Desde el detalle de un media, un botón `Send to phone` envía el publish file del media al móvil Android del usuario mediante Tailscale Taildrop. Una única configuración `TAILSCALE_PHONE_TARGET`. Transferencia síncrona con timeout, sin worker, cola, historial ni estado persistente."

## Contexto

Ya está verificado a mano en el equipo del usuario que `tailscale file cp <archivo> galaxy-a7-2018:`
entrega el archivo en **Descargas** del móvil, y que el usuario es operador de Tailscale
(no hace falta `sudo`). Esta feature solo convierte ese comando en un botón.

Hallazgos de la inspección previa:

- `resolve_publish_file` (feature 028) ya decide qué archivo se publica (copia limpia o
  original) y falla con sus mensajes existentes si no está disponible o está dañado.
- Los archivos se guardan como `<uuid>.<ext>`; enviados tal cual, el móvil recibiría un nombre
  irreconocible. `tailscale file cp` admite `--name`, así que basta con pasar el nombre
  original del media (ver FR-005).
- El backend ya ejecuta herramientas externas (ffmpeg/ffprobe) como proceso con argumentos
  estructurados, `shutil.which` y timeout; se reutiliza el mismo patrón.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enviar un media al móvil con un clic (Priority: P1)

Desde el detalle de un media, el usuario pulsa `Send to phone`. El botón muestra `Sending…`
mientras dura la transferencia y, al terminar, aparece el mensaje corto `Sent to phone`. El
archivo aparece en Descargas del móvil con su nombre original.

**Why this priority**: es todo el valor de la feature.

**Independent Test**: con `TAILSCALE_PHONE_TARGET` configurado y el móvil conectado a la
tailnet, pulsar el botón en un media y comprobar que el archivo llega al móvil con su nombre
original. En tests automáticos, el comando externo se sustituye por un doble que registra los
argumentos recibidos.

**Acceptance Scenarios**:

1. **Given** un media sin copia limpia y el target configurado, **When** el usuario pulsa
   `Send to phone`, **Then** se envía el archivo original al target y la UI muestra
   `Sent to phone`.
2. **Given** un media con copia limpia válida (`sanitized`), **When** el usuario pulsa
   `Send to phone`, **Then** se envía la copia limpia, nunca el original.
3. **Given** cualquier media, **When** se envía, **Then** el móvil lo recibe con el nombre
   original del media, no con el nombre interno de almacenamiento.
4. **Given** una transferencia en curso, **When** el usuario mira el botón, **Then** muestra
   `Sending…` y no se puede pulsar otra vez hasta que termine.

---

### User Story 2 - Entender por qué no se ha enviado y reintentar (Priority: P2)

Si el envío no es posible, el usuario ve un mensaje comprensible que indica qué hacer, y el
botón vuelve a estar disponible para reintentar.

**Why this priority**: sin esto un fallo (móvil apagado, Tailscale caído, falta configuración)
sería silencioso o incomprensible; aun así, el camino feliz (US1) ya aporta valor sin ella.

**Independent Test**: provocar cada caso de error (sin target, sin `tailscale`, archivo
ausente o dañado, comando que falla, comando que excede el tiempo) y comprobar el mensaje y
que el botón vuelve a `Send to phone`.

**Acceptance Scenarios**:

1. **Given** `TAILSCALE_PHONE_TARGET` vacío o ausente, **When** el usuario pulsa el botón,
   **Then** ve un mensaje que indica que el envío al móvil no está configurado, y no se ejecuta
   ningún comando.
2. **Given** que `tailscale` no está instalado o no es accesible, **When** pulsa el botón,
   **Then** ve un mensaje que indica que Tailscale no está disponible en este equipo.
3. **Given** que el publish file no está disponible o la copia limpia está dañada, **When**
   pulsa el botón, **Then** ve el mensaje existente de `resolve_publish_file` y no se envía
   ningún archivo (en particular, nunca el original en lugar de una copia limpia).
4. **Given** que Taildrop termina con error (p. ej. móvil desconectado), **When** pulsa el
   botón, **Then** ve un mensaje de que no se pudo enviar al móvil y que compruebe que está
   conectado a Tailscale.
5. **Given** que la transferencia supera el tiempo máximo, **When** se alcanza el límite,
   **Then** el proceso se detiene, la petición termina y el usuario ve un mensaje de tiempo
   agotado.
6. **Given** cualquiera de los errores anteriores, **When** se muestra el mensaje, **Then** no
   contiene rutas internas del servidor y el botón vuelve a estar disponible.

---

### Edge Cases

- Media inexistente: la acción responde "no encontrado" con el comportamiento habitual de la
  API.
- Limpieza de metadata o borrado concurrente sobre el mismo media: el envío reutiliza el
  guard existente de 016/028 (`ContentFileGuard`) durante todo el tramo
  `resolve_publish_file → tailscale file cp → fin`. Si el media ya se está limpiando o
  borrando, el envío se rechaza con el mensaje de conflicto existente; mientras se envía,
  `Clean metadata` y el borrado de ese media se rechazan con sus mensajes existentes. No se
  crean locks nuevos.
- Salida de error de `tailscale` (stderr/stdout): nunca se muestra al usuario ni se registra
  en el log; solo se registra información segura (ver FR-009).
- Nombre original con caracteres extraños: se pasa tal cual como nombre de destino; Taildrop
  aplica su propia sanitización en el receptor.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer una única acción "send to phone" por media
  (`POST /api/contents/{content_id}/send-to-phone`), que responde éxito o error cuando la
  transferencia termina.
- **FR-002**: El archivo enviado MUST obtenerse exclusivamente mediante
  `resolve_publish_file` con verificación completa (la misma usada antes de publicar); la
  feature no decide por su cuenta qué archivo enviar ni revalida metadata.
- **FR-003**: El destino MUST leerse de la variable de configuración
  `TAILSCALE_PHONE_TARGET` en el momento de cada envío; ningún nombre de dispositivo se fija
  en código. Un valor vacío equivale a "no configurado".
- **FR-004**: El envío MUST ejecutar `tailscale file cp` como proceso con argumentos
  estructurados (sin shell ni concatenación de cadenas), esperar su resultado y abortarlo si
  supera un tiempo máximo fijo.
- **FR-005**: El archivo MUST llegar al móvil con el nombre original del media (opción
  `--name` de `tailscale file cp`), no con el nombre interno de almacenamiento.
- **FR-006**: El sistema MUST distinguir solo estos fallos, cada uno con un mensaje breve y
  sin rutas internas: target no configurado, `tailscale` no disponible, publish file no
  disponible/dañado (mensajes existentes), error de Taildrop y tiempo agotado.
- **FR-007**: Media Detail MUST mostrar un botón `Send to phone` con los estados
  `Send to phone` → `Sending…` (deshabilitado) → mensaje `Sent to phone` en éxito, o mensaje
  de error y botón de nuevo disponible en fallo.
- **FR-008**: Durante todo el envío, el publish file MUST quedar protegido frente a limpieza
  de metadata y borrado del mismo media mediante el guard existente (`ContentFileGuard`),
  sin introducir locks nuevos.
- **FR-009**: Los logs del envío MUST contener solo información segura (código de salida,
  timeout, clase de excepción, código interno genérico); nunca stderr/stdout de `tailscale`,
  rutas internas ni el nombre del archivo.
- **FR-010**: La feature MUST NOT crear tablas, preferencias, historial, cola, worker,
  polling ni ningún estado persistente.

### Key Entities

No introduce entidades nuevas. Usa el media existente (su publish file y su nombre original)
y un único valor de configuración (`TAILSCALE_PHONE_TARGET`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Con el móvil conectado, el usuario recibe el media en Descargas con un solo clic
  y sin abrir una terminal.
- **SC-002**: El archivo recibido tiene el nombre original del media en el 100 % de los
  envíos.
- **SC-003**: Un media con copia limpia nunca envía el original (0 casos en los tests).
- **SC-004**: Ningún envío deja la acción esperando más que el tiempo máximo configurado;
  todos los fallos terminan con un mensaje visible y el botón reutilizable.
- **SC-005**: Ningún mensaje mostrado al usuario contiene rutas del servidor.

## Checkpoints futuros

1. **Backend**: acción + tests con el comando externo sustituido (éxito, copia limpia,
   `--name`, los cinco errores, timeout).
2. **UI + validación real**: botón en Media Detail con tests del fake API y un envío real al
   móvil desde una instancia de validación.

## Assumptions

- El usuario es operador de Tailscale (`tailscale set --operator=$USER`), así que el proceso
  del backend puede usar Taildrop sin privilegios.
- `TAILSCALE_PHONE_TARGET` es una variable de entorno del proceso del backend. Para el
  servicio instalado se documentará cómo definirla (p. ej. un override de la unidad de
  systemd); no se añade a `config.toml` ni a la base de datos.
- Tiempo máximo por defecto: 5 minutos, fijo en código, suficiente para vídeos grandes en la
  red local; se puede ajustar en el plan si las pruebas reales lo exigen.
- La transferencia es síncrona dentro de la petición; un único usuario local no necesita
  ejecución en segundo plano.
- Fuera de alcance: selector de dispositivos, `--targets`/discovery, varios móviles,
  preferencias en DB, botón en MediaCard, envío en lote, QR, servidor de descarga, Termux,
  receptor Android, carpeta personalizada en Android, sincronización automática, Telegram
  Drafts e historial de transferencias.
