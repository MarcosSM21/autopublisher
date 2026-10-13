# Quickstart: validar la conexión de Threads

**Feature**: `010-threads-oauth-connection` | **Fecha**: 2026-10-12

Guía de validación. **No publica ningún Thread.** Contratos en
[contracts/api.md](contracts/api.md); modelo en [data-model.md](data-model.md); decisiones en
[research.md](research.md).

## 1. Checks automáticos (sin Internet, sin Meta real, sin keyring real)

```bash
cd backend
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy .

cd ../frontend
npm run lint && npm run format:check
npm run typecheck
npm test
npm run build
```

Resultado esperado: todo en verde, incluidos los tests existentes de YouTube e Instagram. Los
tests de Threads usan `FakeThreads` (`httpx.MockTransport`) e `InMemoryCredentialStore`.

## 2. Validación real (manual)

Cada paso marcado **(bloqueante)** detiene la validación si falla; se revisa la decisión
indicada antes de continuar. Ningún paso publica, responde ni borra contenido en Threads.

### Requisitos previos

- Una cuenta de Threads propia.
- Una cuenta de Meta for Developers.
- Navegador en la misma máquina que AutoPublisher.
- Servicio de secretos del sistema desbloqueado (GNOME Keyring/KWallet en Linux).

### Paso 1 — Meta App con el caso de uso Threads

1. En <https://developers.facebook.com/apps> crear (o reutilizar) una app y añadir el caso de
   uso **Access the Threads API**.
2. En el caso de uso, activar solo los permisos `threads_basic` y `threads_content_publish`.
3. En *App roles → Roles → Add People*, añadir la cuenta como **Threads Tester**. Aceptar la
   invitación en Threads (*Settings → Account → Website permissions → Invites*).
4. Copiar el **Threads App ID** y el **Threads App Secret** (no los de Instagram/Facebook).

### Paso 2 — Redirect URI y callbacks de Meta (bloqueante)

1. En la configuración del caso de uso Threads, añadir a *Valid OAuth Redirect URIs*:
   `https://localhost/autopublisher/threads/callback`.
   - **Comprobación A**: Meta acepta y guarda el URI. Anotar si añade una barra final; en ese
     caso, usar exactamente el URI guardado en la configuración local. Si lo rechaza →
     **detener** y revisar research §3.
2. *Deauthorize callback URL* y *Data Deletion Requests URL*: AutoPublisher no implementa
   esos callbacks en esta feature. Intentar guardar la configuración del caso de uso Threads
   **sin** esas URLs, si Meta lo permite (no se presupone que lo permita).
   - **Comprobación B**: el dashboard guarda la configuración y el flujo OAuth puede
     completarse sin ellas. Si Meta exige URLs públicas y funcionales (o bloquea el guardado o
     el flujo sin ellas) → **detener** la validación y revisar la arquitectura (research §12).
     **No** introducir valores ficticios, endpoints falsos, `https://localhost/...`, túneles ni
     ningún otro workaround.
3. Crear `backend/data/threads-app.json` con `app_id`, `app_secret` y `redirect_uri` (idéntico
   al registrado). Comprobar con `git status` que el archivo no aparece.

### Paso 3 — Connect (OAuth real)

1. Arrancar backend y frontend. Crear un proyecto activo con una `Account` Threads activa
   (`@cyber.studio`). Debe mostrarse `Not connected` y `Connect Threads`.
2. Pulsar `Connect Threads`.
   - **Comprobación C**: se abre la ventana oficial de autorización de Threads y solicita solo
     acceso básico y publicación (los dos permisos). Si Meta muestra un error de app/tester,
     revisar el paso 1.3.
3. Autorizar. El navegador muestra un error de conexión en
   `https://localhost/autopublisher/threads/callback?code=…&state=…#_`: es lo esperado.
4. Copiar la dirección completa. Primero, validación negativa: pegar la misma URL cambiando el
   host a `localhost.evil.example` (o añadiendo `:8443`) y enviarla → debe rechazarse con
   `threads_oauth_redirect_url_invalid` sin contactar con Meta; el intento sigue utilizable.
5. Pegar la dirección original y pulsar *Complete connection*.
   - **Comprobación D**: el campo se vacía tras enviarlo.
   - **Medición SC-002**: medir (cronómetro o pestaña Network) el tiempo desde el envío de la
     redirect URL hasta que el panel muestra `Connected` y registrarlo. Es una **métrica**
     (objetivo < 10 s en condiciones normales de red), no un timeout funcional: un valor mayor
     se anota y se analiza, pero no invalida la conexión.

### Paso 4 — Tokens y llamadas Graph

- **Comprobación E**: la conexión se completa (no hay `threads_token_exchange_failed`), lo que
  confirma intercambio de código, intercambio a larga duración y el host
  `graph.threads.net` (research §2). Si falla por host → probar la constante alternativa
  `graph.threads.com` documentada y anotarlo.

### Paso 5 — Permisos concedidos con `debug_token` (bloqueante)

- **Comprobación F**: la conexión no termina en `threads_permission_missing` ni en
  `threads_unexpected_response`. Con logs del backend a nivel INFO, verificar que hubo una
  llamada a `/v1.0/debug_token` (con `access_token` e `input_token` redactados) y que la
  conexión quedó `Connected`.
- Para confirmar los scopes reales sin exponer el token, ejecutar en el backend un script
  temporal **fuera del repositorio** (por ejemplo en `/tmp`) que lea el secreto del keyring y
  llame a `debug_token`, imprimiendo **solo** `is_valid`, `user_id`, `sorted(scopes)` y
  `data_access_expires_at`. Resultado esperado: `is_valid=true`, `user_id` = Threads user ID
  mostrado, scopes = `["threads_basic", "threads_content_publish"]`.
  - **Prohibido** imprimir o registrar el objeto completo del keyring, el `access_token`, la
    URL de la petición o la respuesta cruda de Meta; no redirigir la salida a archivos
    versionados.
  - **Eliminar el script** (y cualquier salida guardada) inmediatamente después de usarlo y
    comprobar con `git status` que no queda nada nuevo.
- Si `debug_token` rechaza la credencial del tester o los scopes no pueden comprobarse de forma
  inequívoca → **detener** y revisar research §7 (sin relajar FR-008).

### Paso 6 — Identidad y almacenamiento

- **Comprobación G**: el panel muestra username, nombre visible (si existe), Threads user ID,
  caducidad del acceso (~60 días) y, si Meta lo devolvió, caducidad del acceso a datos
  (informativa: nunca cambia el estado por sí sola).
- **Comprobación H**: la base de datos no contiene tokens:
  `sqlite3 backend/data/autopublisher.db "select * from threads_connections;"` muestra solo
  identidad, estado, referencia opaca y fechas. El keyring tiene una entrada del servicio
  `autopublisher.threads` cuyo usuario es la `credential_ref`.
- **Comprobación I**: los logs y la pestaña Network del navegador no muestran tokens, `code`,
  `state` (salvo en la `authorization_url`) ni el app secret. El almacenamiento del navegador
  está vacío.
- Reiniciar backend y frontend: la cuenta sigue `Connected` con la misma identidad.

### Paso 7 — Verify

- Pulsar `Verify connection`: `Connected`, `last_verified_at` actualizado, sin cambios de
  identidad. Ningún contenido creado en Threads.
- Desactivar la `Account`: `Connect`/`Reconnect`/`Verify connection` no disponibles;
  `Disconnect` sí. Reactivar.

### Paso 8 — Renovación (solo si es comprobable sin riesgo)

Política: no se renueva mientras queden más de 7 días; se renueva en `Verify connection` (o
al publicar, en la Feature 011) cuando quedan 7 días o menos y el token tiene ≥ 24 h.

- **Comprobación J1**: pasadas ≥ 24 h desde la conexión (con > 7 días restantes), pulsar
  `Verify connection` → `token_obtained_at` y `access_expires_at` **no cambian** (no hay
  renovación innecesaria).
- **Comprobación J2**: solo cuando el token entre de forma natural en sus últimos 7 días
  (≈ 53 días tras la conexión), pulsar `Verify connection` → `token_obtained_at` y
  `access_expires_at` avanzan (~60 días desde ese momento), `data_access_expires_at` muestra el
  valor oficial devuelto por `debug_token` tras la renovación (nunca una fecha calculada) y la
  cuenta sigue `Connected`.
- Dentro de la feature, J2 se marca como **no comprobado razonablemente**: no se modifica el
  código ni la constante para forzarlo y no se manipula el reloj. La política, el fallo
  temporal, la inspección tras renovar, la reparación tras commit SQLite fallido y que un
  `data_access_expires_at` antiguo nunca provoque un falso `Reconnect required` quedan cubiertos
  por tests automáticos con reloj falso.

### Paso 9 — Disconnect y Reconnect

1. `Disconnect` → `Not connected`; la entrada del keyring desaparece; la `Account` y sus
   publicaciones siguen intactas. Se muestra cómo retirar el acceso en Threads
   (*Website permissions*). No se llama a Meta.
2. `Connect Threads` de nuevo con la misma cuenta → `Connected`.
3. `Reconnect` con la misma cuenta → nuevas credenciales, misma identidad, la entrada antigua
   del keyring se elimina.
4. (Opcional) Retirar el acceso desde *Website permissions* en Threads y pulsar
   `Verify connection` → `Reconnect required`.

### Resultado

Registrar en este archivo el resultado de las comprobaciones A–J2 (PASS / FAIL / no
comprobado), la medición de SC-002 y cualquier diferencia con la documentación (forma de
respuestas, barra final, host). La validación solo es PASS si A, B y F son PASS.

## 3. Resultado de la validación real (T062, 2026-10-13)

Validado con una cuenta de Threads propia añadida como Threads tester, en Development Mode,
sin publicar nada. No se registran datos privados (usuario, IDs, App ID, secretos ni tokens).

| Comprobación | Resultado |
|---|---|
| A — redirect URI HTTPS en `localhost` | PASS (Meta la guarda; ver desviaciones) |
| B — Deauthorize / Data Deletion vacíos en Development Mode | PASS |
| C — Threads tester | PASS |
| D — configuración local (`threads-app.json` ignorado por Git, distinto de Instagram) | PASS |
| E — OAuth real | PASS: URL pegada con otro host rechazada sin llamar a Meta; código intercambiado una sola vez; token corto descartado tras el intercambio a larga duración |
| Permisos solicitados y concedidos | exactamente `threads_basic` y `threads_content_publish` |
| F — `debug_token` con el user token del tester | PASS |
| Identidad coherente entre intercambio, `debug_token` y `/me` | PASS |
| SC-002 — redirect URL enviada → Connected | ≈ 1,2–1,6 s |
| G — estado conectado (identidad, caducidades, última verificación; SQLite y keyring) | PASS |
| H — reinicio | PASS |
| I — Verify (solo lectura) | PASS |
| J1 — sin renovación fuera de la ventana | PASS |
| J2 — renovación real cerca de la caducidad | NOT REASONABLY TESTABLE NOW (cubierto por tests con reloj falso) |
| K — Reconnect con la misma cuenta | PASS: referencia nueva, secreto anterior eliminado, sin huérfanos |
| L — Disconnect local | PASS: sin llamadas a Meta; cuenta y publicaciones intactas |
| Conexión restaurada para la Feature 011 | PASS |
| M — seguridad (SQLite, logs, API, navegador, Git) | PASS |

Forma no sensible observada de la respuesta de `debug_token` (HTTP 200):

- `data.is_valid`: bool (`true`);
- `data.type`: texto (`USER`);
- `data.user_id`: texto, igual al Threads user ID de `/me` y del intercambio de código;
- `data.scopes`: lista;
- `data.issued_at`, `data.expires_at`, `data.data_access_expires_at`: enteros (Unix time);
- `data.application`: texto.

Observaciones reales de esta validación (no son valores fijados en el producto, que siempre
usa lo que devuelve Meta): la vida del token de larga duración fue de 60 días y la del
acceso a datos, de 90 días.

Desviaciones respecto a la documentación:

- En el dashboard de Meta fue necesario pulsar **Enter** tras escribir la OAuth Redirect URI
  para que la registrara; sin ello, al guardar aparecía "Especifica un URI de
  redireccionamiento de OAuth". Es una observación del dashboard, no un requisito de la API.
- `secret-tool` no estaba instalado en el equipo de validación (Ubuntu: paquete
  `libsecret-tools`). La comprobación de huérfanos se hizo con `secretstorage`, que ya
  instala `keyring`.
