# Quickstart: validar la conexión de Instagram

**Feature**: `008-instagram-oauth-connection` | **Fecha**: 2026-10-08

Guía de validación. No publica ningún contenido. Contratos en
[contracts/api.md](contracts/api.md); modelo en [data-model.md](data-model.md); decisiones en
[research.md](research.md).

## 1. Checks automáticos (sin Internet, sin keyring real)

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

Resultado esperado: todo en verde. Los tests de Instagram usan un fake de Meta y un
`InMemoryCredentialStore`.

## 2. Validación real (manual)

### Requisitos previos

- Una cuenta Instagram **Professional** propia (Business o Creator).
- Una cuenta de Meta for Developers.
- Navegador en la misma máquina que AutoPublisher.
- Un servicio de secretos del sistema desbloqueado (GNOME Keyring/KWallet en Linux).

### Paso 1 — Meta App (detener si falla)

1. En <https://developers.facebook.com/apps> crear una app de tipo **Business**.
2. Añadir el producto **Instagram** → *API setup with Instagram login*.
   - **Nota**: en algunas Meta Apps nuevas el panel no muestra *API setup with Instagram
     login* y solo ofrece otros flujos o productos (por ejemplo *API setup with Facebook
     login*, que AutoPublisher no soporta). Hay que usar una Meta App que tenga Instagram
     Login disponible y configurado oficialmente (su página muestra *Instagram app ID* e
     *Instagram app secret*). No hay una solución universal y no se elude ninguna
     restricción de Meta. Si se reutiliza una app de otro proyecto, solo se **añade** el
     redirect URI (se conservan los existentes) y nunca se restablece su app secret.
3. En *Set up Instagram business login* → *Business login settings* → *OAuth redirect URIs*
   añadir `https://localhost/autopublisher/instagram/callback`.
   - **Comprobación A**: Meta acepta y guarda el URI (revisar si añadió una barra final).
     Si lo rechaza → **detener** y revisar `research.md` §3. (Validado en T060: Meta lo
     aceptó.)
4. Añadir la cuenta Instagram como **Instagram tester** (App roles) y aceptar la invitación
   desde Instagram (*Settings → Website permissions → Apps and websites → Tester invites*).
   Si la cuenta no está autorizada como tester/rol, Meta puede rechazar el flujo en su propia
   página o volver a la redirect URL con un error OAuth; en ese caso AutoPublisher muestra
   `instagram_oauth_provider_error` sin datos crudos de Meta.
5. Copiar el **Instagram App ID** y el **Instagram App Secret** (no los del Facebook App).
6. Crear `backend/data/instagram-app.json` con `app_id`, `app_secret` y `redirect_uri`
   (idéntico al registrado). Comprobar `git status`: el archivo no aparece.

### Paso 2 — Conectar

1. Arrancar backend y frontend; crear o abrir un proyecto activo con una `Account`
   `Instagram` activa. Debe mostrar `Not connected` y `Connect Instagram`.
2. Pulsar `Connect Instagram`: se abre la página oficial de Instagram pidiendo solo los dos
   permisos (`instagram_business_basic`, `instagram_business_content_publish`).
   - **Comprobación B (App Review)**: si Meta indica que algún permiso requiere App Review o
     Advanced Access para la propia cuenta tester → documentarlo y **detener** la validación.
3. Iniciar sesión con la cuenta Professional y aceptar. El navegador llega a la redirect URL
   `https://localhost/...` y muestra un error de conexión (no hay servidor ahí); copiar la
   dirección completa.
4. Pegarla en el panel de AutoPublisher y pulsar *Complete connection*. El campo se vacía.
   La conexión debe aparecer en menos de 10 s desde el envío (SC-002).
   - **Comprobación C**: la cuenta pasa a `Connected` y muestra username, tipo de cuenta
     (`Business`/`Creator`), Instagram account ID, foto si existe y fecha de caducidad del
     acceso (~60 días).
   - **Comprobación D (permisos)**: la conexión se completó, lo que implica que la respuesta
     de Meta trajo el campo `permissions` con ambos permisos. Meta puede incluir además
     permisos que la misma cuenta concedió antes a la misma Meta App (p. ej.
     `instagram_business_manage_comments`); es esperado: AutoPublisher solo solicita los dos
     permisos, exige que ambos estén y no asume que la lista contenga solo esos dos. Si falla con
     `instagram_unexpected_response`/`instagram_permission_missing` teniendo ambos permisos
     concedidos → **detener** y revisar `research.md` §6.
5. Comprobar el ID: coincide con el `user_id` de la cuenta (p. ej. visible en *App Dashboard →
   Instagram → API setup → Generate access tokens* para la cuenta tester).

#### Problemas de login en Instagram

- La URL de autorización usa `force_reauth=true`: Instagram puede **cerrar la sesión** de
  Instagram abierta en ese navegador. No se cambia en esta feature (posible mejora de UX
  futura).
- Varios logins seguidos pueden provocar **bloqueos temporales** ("We couldn't connect to
  Instagram…" en la propia página de Instagram): confirmar el aviso "¿Has sido tú?" en la
  app y esperar unos minutos.
- Una **ventana privada/incógnito** facilita probar con la cuenta correcta: abrir
  AutoPublisher en esa misma ventana y lanzar `Connect Instagram` desde ahí.
- Si tras el login Instagram lleva a su inicio y no a la autorización (p. ej. tras "¿Guardar
  la información de inicio de sesión?" → *Ahora no*), pulsar *Cancel* y `Connect Instagram`
  otra vez; con la sesión ya abierta suele ir directo a la autorización.

### Paso 3 — Secretos

```bash
sqlite3 backend/data/autopublisher.db \
  "select username, instagram_user_id, status, credential_ref from instagram_connections;"
grep -c "IGAA\|access_token" backend/data/autopublisher.db || true   # esperado: 0
secret-tool search service autopublisher.instagram   # Linux: existe una entrada
```

- No hay tokens en SQLite, en los logs del backend (buscar `IGAA`, `access_token=`,
  `client_secret=`, `code=`, `state=`) ni en las herramientas del navegador
  (Application → Storage vacío).

### Paso 4 — Persistencia y Verify

1. Reiniciar backend y frontend → sigue `Connected` con la misma identidad.
2. Pulsar `Verify connection` → éxito, `last_verified_at` actualizado. (`Verify connection`
   solo existe en `Connected` y con cuenta y proyecto activos.)
3. Renovación: **solo si el token tiene ≥ 24 h** (repetir Verify al día siguiente) → la
   fecha de caducidad del acceso avanza. Si no es razonable esperar, dejarlo anotado como no
   comprobado; los tests automáticos cubren la lógica.

### Paso 5 — Disconnect y Reconnect

1. `Disconnect` → `Not connected`; `secret-tool search service autopublisher.instagram` ya no
   muestra la entrada; la `Account` y sus publicaciones siguen igual.
2. `Connect Instagram` de nuevo con la misma cuenta → `Connected`. Meta puede devolver un
   token que conserve la caducidad de la autorización existente en lugar de 60 días nuevos;
   AutoPublisher muestra la caducidad que devuelve Meta y no calcula una propia.
3. (Opcional, si existe una segunda cuenta Professional tester) `Reconnect` con otra cuenta →
   advertencia con ambas identidades; *Cancel* conserva la anterior; repetir y *Replace* la
   sustituye.
4. Opcional: retirar el acceso manualmente en Instagram (*Website permissions → Apps and
   websites*) y pulsar `Verify connection` → `Reconnect required` (mensaje de permiso
   retirado o de credencial no válida, según responda Meta).

### Paso 6 — Inactivos

Desactivar la `Account` → se ve el estado, `Connect`/`Reconnect`/`Verify connection` no
disponibles, `Disconnect` funciona y la conexión no se elimina al desactivar. Repetir con el
proyecto.

## Resultado

Anotar en el PR: comprobaciones A–D, si se pudo comprobar la renovación real y cualquier
diferencia observada respecto a `research.md`.

## Resultado de la validación real (T060, 2026-10-08)

Cuenta Instagram Professional (Creator) real con rol en la Meta App, Standard Access. Sin
identificadores ni secretos en este registro.

| Comprobación | Resultado |
|---|---|
| A — redirect URI `https://localhost/autopublisher/instagram/callback` aceptado; el navegador muestra el error de conexión esperado antes de copiar la dirección | PASS |
| B — permisos concedidos sin App Review | PASS |
| C — identidad real, `Connected`, referencia opaca en SQLite, token solo en el keyring | PASS |
| D — `permissions` presente con los dos permisos requeridos (más permisos concedidos antes a la misma app) | PASS |

- Connect, reinicio, Verify, Disconnect, Reconnect y segundo reinicio: validados.
- Renovación real: no aplicable (token con menos de 24 h); cubierta por los tests
  automáticos.
- Seguridad: 0 tokens, app secret, códigos, `state`, direcciones pegadas o cabeceras
  `Authorization` en SQLite, logs del backend/frontend y respuestas de la API.
- Observaciones: la opción *API setup with Instagram login* no apareció en Meta Apps
  nuevas (se usó una app existente con Instagram Login configurado); el login con
  `force_reauth=true` cerró la sesión de Instagram y provocó un bloqueo temporal tras
  varios intentos; tras el Reconnect, Meta devolvió la caducidad existente.
