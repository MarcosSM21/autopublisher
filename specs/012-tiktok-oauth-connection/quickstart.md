# Quickstart: validación de la conexión TikTok

**Feature**: `012-tiktok-oauth-connection` | **Fecha**: 2026-10-14

Tres fases, en orden. **No se publica nada en TikTok en ningún paso.** Ningún secreto se pega
en el chat, en issues, en commits ni en logs compartidos.

| Fase | Cuándo | Qué |
|---|---|---|
| **G** — gate de viabilidad | **antes** de implementar en profundidad (antes de renovación, Reconnect y Disconnect) | solo dashboard de TikTok for Developers; sin código de producto |
| **V1** — primer corte real | tras implementar config + authorize + callback + intercambio + identidad | PKCE, callback, scopes y forma real de las respuestas |
| **V2** — validación completa | al final de la implementación | Verify, reinicio, renovación, Reconnect, Disconnect, seguridad |

Registrar el resultado de cada paso como **PASS** / **STOP** (con fecha y nota breve sin datos
sensibles) en una sección "Resultados" al final de este archivo.

---

## Fase G — Gate temprano de viabilidad (spec FR-058a / FR-058b)

Requisitos: cuenta en TikTok for Developers y una cuenta de TikTok propia.

1. **G-1 Sandbox**: crear una app (o usar una existente) y, con el selector en *Sandbox*, crear un
   Sandbox. PASS si se puede crear y editar.
2. **G-2 Login Kit Desktop**: *Add products → Login Kit*; seleccionar la plataforma **Desktop**.
   PASS si se puede añadir.
3. **G-3 Content Posting API**: *Add products → Content Posting API*. PASS si se puede añadir al
   Sandbox.
4. **G-4 Direct Post**: activar la configuración **Direct Post** de Content Posting API. PASS si
   puede activarse y guardarse.
5. **G-5 `video.publish`**: en *Scopes*, comprobar que `user.info.basic` y `video.publish`
   aparecen disponibles para el Sandbox sin enviar App Review. Añadir la cuenta propia en
   *Sandbox settings → Target users* (aceptar los términos; puede tardar hasta 1 h). PASS si ambos
   scopes están disponibles para el target user sin App Review de producción ni auditoría.
6. **G-6 Redirect URI**: en Login Kit (Desktop) registrar exactamente
   `http://127.0.0.1:8000/api/tiktok/oauth/callback`. PASS si se guarda **sin alteraciones** (ni
   barra final añadida, ni cambio de host). Si el dashboard exige barra final o rechaza el URI,
   anotar exactamente qué acepta (y si acepta `http://127.0.0.1:*/…`) y revisar research §3
   antes de seguir.
7. **G-7 URL / dominio**: anotar si el dashboard exige verificar un dominio o prefijo de URL para
   **guardar** la configuración de Content Posting API o de Direct Post en el Sandbox (solo es
   necesario para `PULL_FROM_URL`, fuera de alcance). PASS si la configuración se guarda sin
   verificar nada, o si la verificación solo afecta a `PULL_FROM_URL` y no bloquea `video.publish`.

Si el dashboard pide website, Privacy Policy o Terms URL para el Sandbox: anotar si son
obligatorios. **No** inventar URLs.

### STOP (detener la feature y revisar el alcance)

- `video.publish` exige App Review de producción o auditoría pública.
- Hace falta un dominio o URL pública que el usuario no posee, o URLs de Privacy Policy / Terms /
  Website inventadas.
- Cualquier requisito externo que no pueda satisfacerse legítimamente en local.
- El redirect URI de loopback no puede registrarse.

En STOP: no degradar a `user.info.basic`, no crear URLs ficticias, túneles ni workarounds.

### Resultados del Gate G

Estado al 2026-10-14: **Gate G superado**. Comprobación manual realizada por el usuario en
TikTok for Developers; cada PASS se basa en lo observado en el dashboard. Nada publicado.

| Gate | Resultado | Evidencia no sensible |
|---|---|---|
| G-1 Sandbox | PASS | 2026-10-14: app creada como *Individual*; Sandbox creado sin clonar de producción, sin errores; *App details* editable con opción de aplicar cambios; sección *Sandbox settings → Target users* visible (alta del target user se comprueba en G-7). |
| G-2 Login Kit Desktop + redirect | PASS | 2026-10-14: Login Kit añadido al Sandbox; *Platforms → Desktop* activado; tras aplicar cambios, la redirect URI Desktop queda guardada exactamente como `http://127.0.0.1:8000/api/tiktok/oauth/callback` (http, `127.0.0.1`, puerto 8000, ruta exacta, sin barra final). |
| G-3 PKCE/config | PASS | 2026-10-14: la configuración de Login Kit Desktop solo contiene la redirect URI; ningún campo ni aviso sobre PKCE, firmas o dominios incompatible con callback loopback, `S256` y challenge hex. El challenge hex se confirma con TikTok real en V-4. |
| G-4 Content Posting API | PASS | 2026-10-14: Content Posting API añadido al Sandbox; *Direct Post* activado y conservado tras aplicar cambios, sin errores. Nada publicado. |
| G-5 video.publish | PASS | 2026-10-14: la sección *Scopes* del Sandbox muestra `user.info.basic` (*Included in Login Kit*), `video.publish` (*Included in Content Posting API*) y `video.upload` (*Included in Content Posting API*), sin estado de revisión ni petición de App Review/auditoría. `video.upload` está disponible a nivel de app por el producto, pero AutoPublisher **no** lo solicita (solo `user.info.basic,video.publish` en la URL de autorización). La autorización real por el target user se confirma en V-3/V-4. |
| G-6 URL verification/requisitos | PASS | Basic information resuelto (opción A, decidida por el usuario): Privacy Policy y Terms reales publicados en el repo (commit `f92a83f` en `main`), icono real, categoría *Productivity*, descripción veraz; cambios aplicados sin errores. 2026-10-14, *Basic information* exige para aplicar cambios en el Sandbox: *App icon* (1024×1024, JPEG/PNG, público), *Category*, *Description* (≤ 120, pública), **Terms of Service URL**, **Privacy Policy URL** y, con *Desktop*, *Web/Desktop URL* (se usa el repositorio público real `https://github.com/MarcosSM21/autopublisher`). El repositorio no contenía Privacy Policy ni Terms antes de esta decisión. Docs (*Media Transfer Guide*): la verificación de dominio/prefijo de URL solo se exige para `PULL_FROM_URL` (error `url_ownership_unverified`); `FILE_UPLOAD` no la requiere. No dice nada sobre Sandbox ni sobre configurar el producto; confirmado en el dashboard: Content Posting API + Direct Post se guardaron **sin** pedir verificación de dominio/URL prefix ni otros campos (2026-10-14). |
| G-7 target user | PASS | 2026-10-14: la cuenta TikTok propia del usuario se añadió en *Sandbox settings → Target users*, tras iniciar sesión y aceptar los términos de TikTok Developer; aparece como activa en la lista. |

Al terminar G con PASS, guardar en `backend/data/tiktok-app.json` (ignorado por Git):

```json
{ "client_key": "<sandbox client key>", "client_secret": "<sandbox client secret>" }
```

y comprobar `git status` → el archivo **no** aparece.

---

## Fase V1 — Primer corte real (tras el corte mínimo de implementación)

Arrancar backend (`cd backend && uv run uvicorn app.main:app`, puerto 8000) y frontend
(`cd frontend && npm run dev`). Crear un proyecto activo con una `Account` TikTok activa.

1. **V-1 Configuración**: el panel TikTok muestra `Connect TikTok` (no `not configured`).
2. **V-2 Autorización**: pulsar `Connect TikTok`. En la pestaña abierta, comprobar en la URL
   (sin copiarla a ningún sitio) que `scope=user.info.basic,video.publish`,
   `code_challenge_method=S256` y que `code_challenge` tiene 64 caracteres hex. El panel muestra
   `Connecting` con `Cancel`.
3. **V-3 Consentimiento**: TikTok muestra exactamente los permisos de perfil básico y de publicar
   vídeos; ninguno más.
4. **V-4 Callback automático + PKCE**: autorizar. **Tras completar el callback, la barra de
   direcciones termina en una ruta limpia sin `code` ni `state`**:
   `http://127.0.0.1:8000/api/tiktok/oauth/result?outcome=connected`, con la página mínima
   "TikTok account connected", cuyo contenido tampoco refleja ningún valor OAuth. En el historial
   del navegador no queda ninguna entrada de `/api/tiktok/oauth/callback?…`. El panel pasa solo a
   `Connected` en < 10 s con nombre visible y avatar (anotar el tiempo observado).
   **STOP** si TikTok rechaza el challenge hex o el `redirect_uri`.
5. **V-5 Forma de la respuesta**: los tests de contrato del gateway reflejan los campos reales
   (`access_token`, `expires_in`, `refresh_token`, `refresh_expires_in`, `open_id`, `scope`,
   `token_type`). Las caducidades mostradas son coherentes (≈ 24 h y ≈ 365 días si TikTok sigue
   devolviendo esos valores). **STOP** si la forma es incompatible.
6. **V-6 Concesión parcial**: si la pantalla de TikTok permite desmarcar `video.publish`,
   reconectar desmarcándolo → `tiktok_permission_missing`, la conexión anterior intacta. (Si
   TikTok no lo permite, anotarlo.)
7. **V-7 Cancelación**: `Connect`, cancelar en TikTok → ruta limpia `outcome=cancelled` y el
   panel muestra `tiktok_oauth_denied`; y `Connect` + `Cancel` en AutoPublisher → un callback
   posterior termina en `outcome=invalid`.
8. **V-8 Resultado repetido / historial**: tras V-4, recargar la página final → vuelve a mostrar
   el mismo resultado sin ningún efecto (no hay nueva petición al callback); usar *Atrás* no
   reenvía el callback. Abrir a mano `…/api/tiktok/oauth/result?outcome=<texto inventado>` →
   página "Authorization not valid", sin reflejar el texto.

---

## Fase V2 — Validación completa

1. **V-9 Identidad**: `GET /api/accounts/{id}/tiktok-connection` contiene `open_id`,
   `display_name`, `avatar_url`, `permissions.source = token_exchange`; ningún token.
2. **V-10 Verify**: `Verify connection` → `last_verified_at` actualizado; el texto de permisos
   dice "según la última autorización de TikTok" (no "comprobado ahora"). Nada publicado.
3. **V-11 Reinicio**: reiniciar backend y frontend → sigue `Connected` sin autorizar de nuevo.
4. **V-12 Reinicio durante OAuth**: `Connect`, reiniciar el backend antes de autorizar, autorizar
   → ruta limpia `outcome=invalid`; la cuenta conserva su estado.
5. **V-13 Renovación real** (si es razonablemente comprobable): pasadas > 23 h desde la conexión
   (access token dentro del margen de 1 h), pulsar `Verify` → `access_expires_at` avanza,
   `permissions.source = token_refresh`; anotar si el refresh token rotó (comparar solo un hash
   local temporal, nunca el valor). Si no es comprobable en el plazo de la feature, anotarlo:
   queda cubierto por tests. **STOP** si la renovación contradice la documentación.
6. **V-14 Reconnect misma cuenta**: `Reconnect` → `Connected`; `connected_at` actualizado; el
   keyring contiene una única entrada para la cuenta (la nueva) y
   `tiktok_credential_orphans` está vacía.
7. **V-15 Reconnect otra cuenta** (si se dispone de un segundo target user): advertencia con ambas
   cuentas; `Cancel` deja la conexión intacta.
8. **V-16 Disconnect + revocación**: `Disconnect` → mensaje "revocado en TikTok"; en la app
   TikTok, *Settings → Security/Privacy → Manage app permissions*, AutoPublisher ya no aparece;
   la `Account` y sus publicaciones siguen; keyring sin la entrada. Anotar qué devuelve TikTok al
   revocar (solo HTTP y `error`, sin cuerpo completo). **STOP** si la revocación contradice la
   documentación.
9. **V-17 Disconnect ya revocado**: conectar, retirar el permiso desde *Manage app permissions*,
   `Disconnect` → `already_invalid` o `revoked` según la respuesta real (anotar cuál); nunca
   "revoked" si TikTok no lo confirmó.
10. **V-18 Reconexión final**: `Connect TikTok` de nuevo y dejar la cuenta `Connected` para la
    Feature 013.
11. **V-19 Seguridad**:
    - `sqlite3 backend/data/autopublisher.db ".dump tiktok_connections"` y
      `".dump tiktok_credential_orphans"` → sin tokens, código, `state`, verifier ni secret.
    - Logs del backend de toda la sesión: `grep -E "code=|state=|access_token|refresh_token|client_secret|code_verifier|Bearer "` → solo `[redacted]`; las líneas del callback aparecen como `/api/tiktok/oauth/callback?[redacted]`.
    - DevTools: `localStorage`/`sessionStorage` vacíos de datos TikTok; respuestas de `/api`
      sin tokens; `state` solo dentro de `authorization_url`.
    - `git status`: ni `tiktok-app.json` ni bases de datos.

## Checks automáticos

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd frontend && npm test && npm run lint && npm run format:check && npm run typecheck && npm run build
```

Todos deben pasar; los tests no usan Internet, TikTok real ni keyring real.

## Resultados

### Resultados de V1 (T032)

Estado al 2026-10-14: **V1 superado, ninguna STOP condition**. TikTok Sandbox real, target user
propio, nada publicado. Backend arrancado en `127.0.0.1:8000` mediante un lanzador local (no
versionado) que llama a `create_app(tiktok_transport=…)` con un transporte observador que solo
registraba nombres de campos, tipos, longitudes y comparaciones booleanas; el reinicio se hizo
con el arranque normal `uv run uvicorn app.main:app`. Frontend con `npm run dev`.

| Paso | Resultado | Evidencia no sensible |
|---|---|---|
| V-1 Configuración | PASS | `GET …/tiktok-connection` → `not_connected`, `oauth_configured: true`; el panel muestra `Connect TikTok`. Cuenta no TikTok → `409 platform_not_supported`. |
| V-2 Autorización | PASS | Endpoint `https://www.tiktok.com/v2/auth/authorize/`; solo los 7 parámetros documentados, sin repetidos; `scope=user.info.basic,video.publish`; `response_type=code`; `code_challenge_method=S256`; `code_challenge` de 64 caracteres hex en minúsculas; `redirect_uri=http://127.0.0.1:8000/api/tiktok/oauth/callback`; `state` de 43 caracteres. |
| V-3 Consentimiento | PASS | TikTok muestra exactamente dos permisos: *Access your profile info (avatar and display name)* (no desmarcable) y *Post content to TikTok* (desmarcable). Ninguno más. |
| V-4 Callback + PKCE | PASS | Callback → `303` a `/api/tiktok/oauth/result?outcome=connected` (`Cache-Control: no-store`, `Referrer-Policy: no-referrer`), página "TikTok account connected" sin valores OAuth ni scripts. TikTok aceptó el challenge hex: el SHA-256 hex del `code_verifier` enviado (64 caracteres) coincide con el challenge de la URL y el intercambio respondió 200. `redirect_uri` del intercambio idéntica a la de la autorización; secretos solo en el cuerpo `application/x-www-form-urlencoded`, ninguno en la URL. Exchange exactamente una vez, seguido de `GET /v2/user/info/?fields=open_id,display_name,avatar_url` con `Bearer`. El panel pasó a `Connected` con nombre y avatar casi de inmediato (observado por el usuario, muy por debajo de 10 s). |
| V-5 Forma de la respuesta | PASS | Token: HTTP 200 con exactamente `access_token` (str), `expires_in` (int, 86400), `open_id` (str, 36), `refresh_expires_in` (int, 31536000), `refresh_token` (str), `scope` (str, `user.info.basic,video.publish`), `token_type` (`Bearer`); sin `error`. user/info: `{"data": {"user": {open_id, display_name, avatar_url}}, "error": {"code": "ok", "message", "log_id"}}`; avatar en `*.tiktokcdn-eu.com`. Revocación correcta: `200` con cuerpo `{}` (`FakeTikTok` ajustado a esta forma; el cuerpo vacío queda cubierto con el fault `empty_body`). Caducidades leídas: ≈ 24 h y ≈ 365 días. |
| V-6 Concesión parcial | PASS | Desmarcando *Post content to TikTok*, TikTok devuelve `scope=user.info.basic` → `outcome=failed`, intento `tiktok_permission_missing (missing: video.publish)`, credencial temporal revocada en TikTok (`200 {}`) y no guardada; la cuenta sigue `not_connected` (no había conexión previa que preservar). |
| V-7 Cancelación | PASS | *Cancel* en TikTok → `outcome=cancelled`, intento `tiktok_oauth_denied`. `authorize` + `Cancel` en AutoPublisher + callback posterior con ese `state` → `303 outcome=invalid`, ninguna llamada a TikTok, conexión existente intacta. |
| V-8 Resultado repetido | PASS | Recargar `…/result?outcome=connected` → misma página, `200`, sin petición al callback. `outcome` inventado (con markup) → "Authorization not valid", sin reflejar el texto. Como el callback responde con `303`, su URL no queda como entrada del historial. |
| Persistencia | PASS | Fila `tiktok_connections` `connected` con `open_id` (36), `display_name`, `avatar_url`, `credential_ref` y fechas; ningún token. Secreto del keyring con todos los campos de data-model (`version=1`, `scopes` ambos, `scopes_source=token_exchange`); `open_id` y caducidades idénticos a la fila. `tiktok_credential_orphans` vacía. Migración 0011 aplicada al arrancar. |
| Reinicio | PASS | Tras reiniciar el backend con `uv run uvicorn app.main:app`: `connected`, identidad presente, `permissions.source=token_exchange`, sin autorizar de nuevo. |
| Seguridad | PASS | Access/refresh token, client secret y client key **no** aparecen en la BD, en los logs del backend y del frontend ni en las observaciones. Grep del quickstart sobre el log del backend: 0 líneas sensibles sin `[redacted]`; las 4 líneas del callback aparecen como `/api/tiktok/oauth/callback?[redacted]`. Respuestas `/api` sin tokens (falso positivo conocido: la URL del avatar de TikTok incluye un parámetro de CDN `refresh_token=<8 hex>` que no es el refresh token OAuth). `git status`: ni `tiktok-app.json` ni bases de datos. |

La cuenta TikTok de prueba (`tiktok-sandbox`, proyecto activo) queda `Connected`. V2 (V-9…V-19)
pendiente.

### Resultados de V2 (T064)

Estado al 2026-10-14: **V2 superado, ninguna STOP condition**. TikTok Sandbox real, target user
propio, nada publicado. Backend en `127.0.0.1:8000` con el mismo lanzador observador local no
versionado de V1 (solo nombres de campos, tipos, longitudes, booleanos y códigos de error); el
reinicio final se hizo con `uv run uvicorn app.main:app` y `npm run dev`. El keyring se revisó
solo estructuralmente (número de entradas y sufijos de las referencias opacas).

| Paso | Resultado | Evidencia no sensible |
|---|---|---|
| V-9 Identidad | PASS | `GET …/tiktok-connection` → `connected`, `identity` con `open_id` (36), `display_name` y `avatar_url`; `permissions.source=token_exchange`; ninguna clave de token, `credential_ref`, secret ni `state`. |
| V-10 Verify | PASS | `POST …/verify` → 200; una sola llamada real a `GET /v2/user/info/` (`error.code=ok`), sin renovación (al access token le quedaban ~21 h); `last_verified_at` actualizado; `permissions.source` sigue `token_exchange`. El panel muestra "Connection verified with TikTok. Permissions are shown as granted in TikTok's last authorization or renewal" (confirmado por el usuario); no se afirma una comprobación en vivo de `video.publish`. |
| V-11 Reinicio | PASS | Backend reiniciado (y frontend en el reinicio final) → `connected` sin autorizar de nuevo. |
| V-12 Reinicio durante OAuth | PASS | `authorize` → reinicio del backend → callback con el `state` de ese intento → `303 outcome=invalid`, 0 llamadas a TikTok, cuenta sin cambios. Desviación: el callback se envió con un código ficticio en lugar de autorizar en TikTok; el resultado depende solo del `state` desconocido tras el reinicio. |
| V-13 Renovación real | No comprobable ahora | El access token obtenido caduca a las 24 h y la política solo renueva con ≤ 1 h de vida; no se manipularon fechas ni secretos. La renovación, la rotación del refresh token y sus fallos quedan cubiertos por `test_tiktok_tokens.py` (15 casos del plan) y `test_tiktok_verify.py`. Pendiente de observar en el uso real (Feature 013). |
| V-14 Reconnect misma cuenta | PASS | `Reconnect` → página "TikTok account connected" y `Connected`; `credential_ref` nueva (sufijo `…780f11` → `…8ac0c7`); keyring con una única entrada igual a la referencia de la BD; `tiktok_credential_orphans` vacía; `connected_at` actualizado; sin revocación; PKCE hex, `redirect_uri` y scopes de nuevo correctos. |
| V-15 Reconnect otra cuenta | No aplicable | No hay un segundo target user en el Sandbox. Cubierto por `test_tiktok_reconnect.py` (advertencia, `Replace`/`Cancel`, caducidad, unicidad e inactivos al confirmar). |
| V-16 Disconnect + revocación | PASS | `POST /v2/oauth/revoke/` → **HTTP 200 con `{}`**, sin `error`; panel "TikTok confirmed that AutoPublisher's access was revoked"; secreto y fila borrados, keyring sin entradas TikTok, sin huérfanos; la `Account` y las demás cuentas intactas. En la app de TikTok, AutoPublisher (Sandbox) ya no aparece en *Manage app permissions* (confirmado por el usuario). |
| V-17 Disconnect ya revocado | PASS | Conectar → retirar AutoPublisher en *Manage app permissions* → `Disconnect`: TikTok responde **HTTP 200 con `error=invalid_grant`** (más `error_description` y `log_id`, no registrados) → `already_invalid`; panel "TikTok reported that the authorization was no longer valid, so there was nothing left to revoke"; nunca "revoked". Coincide con research §13; añadida esa forma (`oauth200_invalid_grant`) a `test_tiktok_disconnect.py`. |
| V-18 Reconexión final | PASS | `Connect TikTok` → `Connected`; AutoPublisher (Sandbox) vuelve a aparecer en *Manage app permissions*. Tras el reinicio final: `connected`, identidad presente, permisos `user.info.basic` y `video.publish` (`token_exchange`), `oauth_configured: true`. Lista para la Feature 013. |
| V-19 Seguridad | PASS | Access y refresh token actuales, client secret y client key **no** aparecen en el dump de SQLite, en los logs del backend y del frontend de V1 y V2, en las observaciones ni en las respuestas de `/api`. `tiktok_connections` y `tiktok_credential_orphans` solo tienen columnas no sensibles. Grep del quickstart sobre los logs: 0 líneas sensibles sin `[redacted]`; las 4 líneas de callback aparecen como `/api/tiktok/oauth/callback?[redacted]`, ninguna sin redactar. `localStorage`/`sessionStorage` vacíos (DevTools, confirmado por el usuario). Keyring: 1 entrada, igual a la referencia de la BD. `git status`: `backend/data/` ignorado; ni `tiktok-app.json` ni bases de datos ni logs. |

La cuenta `tiktok-sandbox` (proyecto activo) queda `Connected` para la Feature 013.
