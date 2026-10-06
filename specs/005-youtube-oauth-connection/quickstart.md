# Quickstart: validar la conexión de cuentas YouTube

**Feature**: `005-youtube-oauth-connection` | **Fecha**: 2026-10-06

Guía para comprobar la feature de extremo a extremo. Las comprobaciones automáticas no usan
Internet; la validación con Google real (§3–§6) es **manual** y no se ejecuta en CI.

Referencias: [contracts/api.md](contracts/api.md), [data-model.md](data-model.md),
[research.md](research.md).

---

## 1. Comprobaciones automáticas

```bash
cd backend
uv sync
uv run pytest                 # incluye tests de OAuth/YouTube con fakes, sin Internet
uv run ruff check . && uv run ruff format --check . && uv run mypy .

cd ../frontend
npm ci
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

Resultado esperado: todo en verde, también sin conexión de red.

## 2. Requisitos para la validación manual

- Una cuenta de Google con un canal de YouTube. Para §6, a ser posible otra que administre
  **varios** canales (por ejemplo, el canal personal y uno de marca).
- Un almacén seguro de credenciales operativo. `keyring` es una dependencia nueva del
  backend y se instala con `uv sync`.
  - **Linux / Ubuntu**:
    - un proveedor de **Secret Service** en la sesión: **GNOME Keyring** (incluido en
      Ubuntu Desktop; en otras variantes, `sudo apt install gnome-keyring`) o **KWallet**
      con Secret Service (KDE);
    - sesión gráfica con **D-Bus de sesión** activo;
    - llavero **desbloqueado** (el llavero "Login" se desbloquea al iniciar sesión);
    - no hace falta ninguna librería de sistema adicional: `keyring` instala `SecretStorage`
      y `jeepney`, que son Python puro;
    - opcional, para inspeccionar: `sudo apt install libsecret-tools` (comando
      `secret-tool`) o `seahorse`.
  - macOS: Keychain.
  - Windows: Credential Manager.

  Comprobar el backend efectivo antes de empezar:

  ```bash
  cd backend && uv run python -c "import keyring; print(keyring.get_keyring())"
  ```

  Debe mostrar un backend seguro (en Ubuntu, `SecretService Keyring`). Si muestra
  `fail Keyring`, `PlaintextKeyring` o similar, AutoPublisher rechazará guardar credenciales
  (`credential_store_unavailable`). Es el comportamiento esperado; hay que instalar o arrancar
  el Secret Service.
- `sqlite3` para inspeccionar la base de datos.

### Proyecto en Google Cloud

1. En <https://console.cloud.google.com/> crear un proyecto (p. ej. `autopublisher-local`).
2. *APIs & Services → Library*: habilitar **YouTube Data API v3**.
3. *Google Auth Platform → Branding / Audience*:
   - tipo **External**;
   - nombre de la app y correo de soporte;
   - añadir la propia cuenta de Google como *test user*.
4. *Data Access*: añadir los scopes
   `https://www.googleapis.com/auth/youtube.readonly` y
   `https://www.googleapis.com/auth/youtube.upload`.
5. *Clients → Create client*: tipo **Desktop app**. Descargar el JSON.
6. Guardar el JSON como `backend/data/google-oauth-client.json`, o en otra ruta indicada
   con `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE`.
7. Comprobar que Git no lo ve: `git status --short` no debe mostrarlo.

> En modo **Testing**, Google caduca el refresh token a los 7 días; después la cuenta
> aparecerá como `Reconnect required` (comportamiento esperado). Para un uso continuado,
> publicar la app ("In production"); al ser no verificada, Google mostrará una advertencia
> en el consentimiento.

### Arranque

```bash
cd backend && uv run uvicorn app.main:app --reload    # http://127.0.0.1:8000
cd frontend && npm run dev                              # http://localhost:5173
```

## 3. Flujo principal (criterio de éxito SC-001)

| # | Acción | Resultado esperado |
|---|--------|--------------------|
| 1 | Abrir un proyecto activo con una cuenta YouTube activa (p. ej. `@CyberChannel`). | La cuenta muestra `Not connected` y el botón **Connect**. Las cuentas de otras plataformas no muestran nada nuevo. |
| 2 | Pulsar **Connect**. | Se abre una pestaña con el selector de cuentas de Google. |
| 3 | Elegir la cuenta o canal y conceder **todos** los permisos. **Poner en marcha un cronómetro al pulsar el botón final de conceder (*Continue/Allow*) en Google.** | La pestaña muestra "YouTube channel connected. You can close this tab…". |
| 4 | Volver a AutoPublisher y **parar el cronómetro cuando la cuenta muestre `Connected`**. | Tiempo medido **< 10 s** (SC-002); anotar el valor. La cuenta muestra `Connected`, el título del canal, su channel ID (`UC…`), su handle y su miniatura si existen, y la fecha de conexión. Comprobar que el handle y el nombre visible de la cuenta de AutoPublisher **no han cambiado** (FR-017). |
| 5 | Inspeccionar la base de datos (ver abajo). | Solo hay datos públicos del canal y un `credential_ref`; ningún token. |
| 6 | Parar y volver a arrancar backend y frontend. | La cuenta sigue `Connected` con el mismo canal. |
| 7 | Pulsar **Verify connection**. | Éxito sin pedir login; `last_verified_at` se actualiza. |
| 8 | Pulsar **Disconnect** y confirmar. | `Not connected`. Se muestra la nota de que AutoPublisher ha borrado sus credenciales y de cómo retirar el permiso en Google manualmente. El backend no hace ninguna petición a Google (funciona también sin red). |
| 9 | Inspeccionar el almacén seguro y la base de datos. | No queda la entrada `autopublisher.youtube` de esa cuenta ni la fila de conexión. La cuenta y sus publicaciones siguen existiendo. |
| 10 | (Opcional) En <https://myaccount.google.com/connections>, abrir la app de AutoPublisher y pulsar *Delete all connections*. | La app deja de tener acceso en Google. Afecta a **todas** las conexiones de AutoPublisher que usen esa cuenta de Google, que pasarán a `Reconnect required` al verificarlas. |
| 11 | Pulsar **Connect** de nuevo y autorizar el mismo canal (sin haber retirado el permiso en Google). | Google muestra **otra vez** la pantalla de consentimiento (intencionado: `prompt=consent` garantiza un refresh token nuevo). Vuelve a `Connected` con el mismo channel ID, y **Verify connection** funciona tras reiniciar. |

Inspección de la base de datos (pasos 5 y 9):

```bash
sqlite3 backend/data/autopublisher.db \
  "SELECT account_id, channel_id, channel_title, status, credential_ref FROM youtube_connections;"
# Ninguna columna contiene tokens. Además, no debe haber coincidencias:
sqlite3 backend/data/autopublisher.db .dump | grep -E 'ya29\.|1//' || echo "no tokens in SQLite"
```

Inspección del almacén seguro en Linux (pasos 5 y 9):

```bash
secret-tool search --all service autopublisher.youtube | grep -E '^attribute\.username'
# Tras conectar: aparece un username igual al credential_ref de la fila.
# Tras desconectar: no aparece ese username.
```

Comprobar también que no hay tokens en la salida del backend, ni en las respuestas que se
ven en las herramientas de desarrollo del navegador (pestaña Network), ni en `localStorage`.

## 4. Errores y cancelación

| Caso | Cómo provocarlo | Esperado |
|------|-----------------|----------|
| Sin configuración | Renombrar temporalmente `google-oauth-client.json` y recargar la vista de cuentas (sin reiniciar el backend). | **No se abre ninguna pestaña** al pulsar **Connect**: el panel muestra cómo configurar YouTube OAuth ("YouTube OAuth is not configured…"). Las cuentas conectadas siguen mostrándose y pueden desconectarse. Al restaurar el archivo y recargar, **Connect** vuelve a funcionar sin reiniciar el backend (la configuración se lee en cada operación). |
| Configuración retirada tras cargar | Con la vista ya cargada (`oauth_configured = true`), renombrar el archivo y pulsar **Connect**. | La pestaña en blanco que se abrió se **cierra** sola y se muestra el error `oauth_not_configured`. |
| Cancelar en Google | En la pantalla de consentimiento pulsar **Cancel**. | Mensaje "The connection was cancelled in Google." Sin cambios en la cuenta. |
| Permisos parciales | Desmarcar uno de los permisos en el consentimiento granular. | Mensaje pidiendo conceder todos los permisos. Sin conexión. |
| `state` inválido | Copiar la URL del callback de un intento ya completado y abrirla otra vez. | Página "This authorization is invalid or has expired…". Sin cambios. |
| Intento caducado | Pulsar **Connect** y esperar más de 10 min antes de autorizar. | Error de autorización caducada. Se puede reintentar. |
| Cuenta inactiva | Desactivar la cuenta conectada. | Sigue mostrando el canal y el estado. **Connect**/**Reconnect** deshabilitados con explicación. **Disconnect** funciona. |
| Proyecto inactivo | Desactivar el proyecto. | Igual que el caso anterior. |
| Desactivar durante la autorización | Pulsar **Connect**, desactivar la cuenta en otra pestaña y después autorizar. | Error `account_inactive`. Sin conexión. |
| Acceso revocado fuera | Retirar el acceso en myaccount.google.com/connections y pulsar **Verify connection**. | `Reconnect required` con el botón **Reconnect**. La cuenta sigue activa. |
| Desconectar con llavero no disponible (Linux) | Con una cuenta conectada, bloquear el llavero (o arrancar sin D-Bus) y pulsar **Disconnect**, cancelando el desbloqueo. | Error "The system's secure credential storage is not available…". La cuenta **sigue** mostrándose conectada con su canal. Al desbloquear y reintentar, pasa a `Not connected`. |
| Llavero bloqueado (Linux) | Bloquear el llavero "Login" en `seahorse` y pulsar **Connect**; cancelar el diálogo de desbloqueo al volver de Google. | Error "The system's secure credential storage is not available…". Sin conexión y sin credenciales escritas en ningún otro sitio. |
| Sin Secret Service (Linux) | Arrancar el backend en una sesión sin D-Bus (p. ej. `env -u DBUS_SESSION_BUS_ADDRESS uv run uvicorn app.main:app`) y conectar. | Mismo error. No se crea ningún archivo de credenciales. |
| Sin red | Desconectar la red y pulsar **Verify connection**. | Error "Could not reach YouTube…". El estado sigue `Connected`. |

## 5. Canal equivocado y canal duplicado

| Caso | Pasos | Esperado |
|------|-------|----------|
| Cambio de canal | Con la cuenta `Connected` al canal A, pulsar **Reconnect** y elegir el canal B. | Advertencia con A y B (título y channel ID) y botones **Replace with this channel** / **Keep current channel**. Mientras no se elige, la cuenta sigue con A. |
| Mantener | Pulsar **Keep current channel**. | Sigue A sin cambios. |
| Sustituir | Repetir y pulsar **Replace with this channel**. | Conectada a B. El secreto antiguo ya no está en el almacén. |
| Duplicado en el proyecto | Crear otra cuenta YouTube en el mismo proyecto y conectarla al canal ya vinculado. | Error indicando qué cuenta (`@handle`) tiene ya ese canal. La segunda queda `Not connected`. |
| Mismo canal en otro proyecto | Conectar el canal a una cuenta YouTube de **otro** proyecto. | Permitido. Al desconectar una de las dos, la otra sigue funcionando (**Verify connection** correcto), porque `Disconnect` no revoca el permiso en Google. |

## 6. Cuenta de Google con varios canales (si hay una disponible)

1. Con una cuenta de Google que administre varios canales, pulsar **Connect**.
2. En el selector de Google aparecen la cuenta personal y las cuentas o canales de marca.
   Elegir un canal de marca concreto.
3. Esperado: AutoPublisher muestra **exactamente** ese canal (comprobar el channel ID en
   YouTube Studio → *Settings → Channel → Advanced settings*), y nunca otro.
4. Repetir eligiendo el canal personal. Se muestra el aviso de cambio de canal con los dos
   channel IDs correctos.
5. Si en algún caso AutoPublisher no puede determinar un único canal, debe mostrarse
   "Could not determine which YouTube channel to connect…" y la cuenta no debe quedar
   conectada. Anotar el caso para revisión.

Si no hay ninguna cuenta así disponible, dejar constancia de que §6 no se ejecutó. El
comportamiento ante 0, 1 y 2 canales queda cubierto por los tests automáticos.
