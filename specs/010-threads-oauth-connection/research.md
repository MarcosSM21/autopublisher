# Research: Conexión de cuentas Threads mediante OAuth oficial

**Feature**: `010-threads-oauth-connection` | **Fecha**: 2026-10-12

Documentación oficial consultada el 2026-10-12 (Meta for Developers, Threads API):

- *Get Access Tokens and Permissions* — `docs/threads/get-started/get-access-tokens-and-permissions`
- *Long-Lived Access Tokens* — `docs/threads/get-started/long-lived-tokens`
- *App Access Tokens* — `documentation/threads/get-started/app-access-tokens`
- *Get Started* — `docs/threads/get-started`
- *Threads Profiles* — `docs/threads/threads-profiles`
- *Debug Access Token* (troubleshooting) y referencia `/debug_token` — `documentation/threads/troubleshooting/debug-access-token`, `docs/threads/reference/debug`
- *Threads API Reference* (hosts) — `docs/threads/reference`
- *Customize a Meta app with the Access the Threads API use case* — `docs/development/create-an-app/threads-use-case`
- App de ejemplo oficial de publicación de Threads (README: redirecciones OAuth solo sobre HTTPS)

Lo que la documentación no cubre se marca como **validación real** y se comprueba en
[quickstart.md](quickstart.md) con condición de detención.

---

## 1. API elegida y separación respecto de Instagram

**Decision**: Threads API oficial, con la Meta App configurada con el caso de uso *Access the
Threads API*. Se usan el **Threads App ID** y el **Threads App Secret** que ese caso de uso
muestra (distintos de los de Instagram/Facebook). Integración independiente: módulos
`threads_*`, configuración `threads-app.json`, servicio de keyring `autopublisher.threads`,
tabla `threads_connections`.

**Rationale**: *Get Started* indica que la app obtiene dos pares ID/secret y que para Threads se
usa el de Threads. Instagram Login y Threads tienen hosts, grant types (`ig_*` vs `th_*`) y
respuestas distintas; forzarlos en un mismo módulo acoplaría dos APIs que cambian por separado
(Constitution III).

**Alternatives considered**: reutilizar `instagram_gateway.py` parametrizado por host —
rechazado: mezcla clasificación de errores y formatos de respuesta distintos (p. ej. el
intercambio de Instagram devuelve `permissions` y el de Threads no).

---

## 2. Endpoints, hosts y versión

**Decision**:

| Paso | Método y URL |
|---|---|
| Autorización (navegador) | `GET https://threads.com/oauth/authorize` |
| Código → token corto | `POST https://graph.threads.net/oauth/access_token` (cuerpo de formulario) |
| Corto → largo | `GET https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=…&access_token=…` |
| Renovación | `GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=…` |
| Identidad | `GET https://graph.threads.net/v1.0/me?fields=id,username,name,threads_profile_picture_url` |
| Inspección de token | `GET https://graph.threads.net/v1.0/debug_token?input_token=…&access_token=…` |

- `THREADS_GRAPH_HOST = "https://graph.threads.net"` y `THREADS_API_VERSION = "v1.0"` como
  constantes únicas en `threads_gateway.py`. Los endpoints de token no están versionados.
- `THREADS_AUTH_ENDPOINT = "https://threads.com/oauth/authorize"`, constante en
  `threads_oauth.py`.

**Rationale**: la *Threads API Reference* indica que la API es accesible tanto por
`graph.threads.net` como por `graph.threads.com`; las páginas de tokens de larga duración,
app access tokens y debug usan `graph.threads.net`, así que se usa un único host coherente. La
ventana de autorización se toma literalmente de la página vigente *Get Access Tokens and
Permissions* (`https://threads.com/oauth/authorize`). Si la validación real muestra un
problema con cualquiera de los dos hosts, se cambia una constante.

**Validación real**: quickstart paso 3 (la URL de autorización abre la ventana de
consentimiento de Threads) y paso 4 (todas las llamadas Graph responden en el host elegido).

**Alternatives considered**: `graph.threads.com` — igualmente válido según la referencia; se
elige `.net` por coherencia con la mayoría de páginas y con la referencia de `debug_token`.

---

## 3. Redirect URI para una aplicación local

**Decision**: reutilizar el patrón de la Feature 008: redirect URI **HTTPS** en `localhost`
donde no escucha ningún servidor; el usuario copia la redirect URL final del navegador y la
pega en AutoPublisher. Valor por defecto documentado:
`https://localhost/autopublisher/threads/callback` (propio de Threads, distinto del de
Instagram, aunque la misma Meta App pueda registrar ambos).

**Rationale**: la app de ejemplo oficial de Threads indica que las redirecciones OAuth solo se
admiten sobre HTTPS (también en local), así que un callback loopback HTTP como el de YouTube no
sirve. El patrón de pegado evita certificados, túneles y servidores adicionales (Constitution
I) y ya está validado con Meta en la Feature 008 para Instagram Login.

**Validación real**: quickstart paso 2 — el dashboard del caso de uso Threads acepta y guarda
el URI. Si lo rechaza → **detener** y revisar esta decisión (no se usarán túneles ni dominios
de terceros sin una nueva decisión aprobada).

**Alternatives considered**: listener HTTPS local con certificado autoafirmado o mkcert (lo que
hace la app de ejemplo) — más complejo, instala CA o muestra avisos; túnel público — expone el
código a terceros; ambos aplazables a una feature futura sin cambiar el modelo de datos.

---

## 4. Validación estricta de la redirect URL pegada (spec FR-014)

**Decision**: `parse_redirect_url(pasted, config)` en `threads_oauth.py`:

1. `urlsplit` sobre la cadena recortada; cualquier `ValueError` (incluido un puerto
   inválido) → `InvalidRedirectUrl`.
2. Rechazar si la URL trae credenciales de usuario (`username`/`password` no nulos).
3. Comparar **exactamente** con el redirect URI configurado, componente a componente:
   - `scheme` (normalizado a minúsculas);
   - `hostname` (`urlsplit` ya lo normaliza a minúsculas);
   - **puerto efectivo** (explícito o 443 por defecto en `https`);
   - `path`, **igualdad exacta** (sin tolerar barra final: Meta redirige al `redirect_uri`
     exacto que AutoPublisher envía en la autorización, que es el configurado).
   Nunca se usa `startswith` ni comparación por prefijo de cadena.
4. Solo tras esa validación se lee la **query**: `code`, `state`, `error`,
   `error_reason`, `error_description`. Si `code`, `state` o `error` aparecen más de una vez →
   inválida. Si no hay ni `code` ni `error` → inválida.
5. El **fragment** solo puede estar vacío o ser `_` (sufijo `#_` documentado por Threads); se
   ignora. Por robustez, si un `code` termina en `#_` (pegado con el fragmento codificado), se
   elimina ese sufijo. Un fragment con otro contenido no aporta parámetros (se ignora).
6. `load_threads_app_config` exige que el `redirect_uri` configurado sea `https`, con host, sin
   credenciales de usuario, sin query y sin fragment.

**Rationale**: compara la identidad de destino del redirect, no su representación textual: un
prefijo común (`https://localhost.evil.example/...`, `https://localhost:8443/...`,
`.../callback-other`) nunca se acepta. Diferencia deliberada con Instagram (que tolera barra
final); no se cambia Instagram.

**Alternatives considered**: tolerar barra final — innecesario porque Meta usa el URI exacto
enviado; aceptar parámetros en el fragment — no documentado para Threads.

---

## 5. PKCE y parámetros de autorización

**Decision**: sin PKCE. Parámetros enviados: `client_id`, `redirect_uri`,
`scope=threads_basic,threads_content_publish`, `response_type=code`, `state`. Ningún otro
parámetro (no hay equivalente documentado de `force_reauth`).

**Rationale**: la documentación de autorización de Threads no menciona `code_challenge` ni
`code_verifier`; no se envían parámetros no documentados (spec FR-016). Seguridad: `state` de
un solo uso ligado a intento y `Account`, código de un solo uso, intercambio en el backend con
el app secret.

---

## 6. Intercambio de tokens y ciclo de vida

**Decision**:

1. **Código → token corto (1 h)**: `POST /oauth/access_token` con cuerpo de formulario
   `client_id`, `client_secret`, `code`, `grant_type=authorization_code`, `redirect_uri`.
   Respuesta documentada: `{"access_token", "token_type": "bearer", "user_id"}`. Sin
   reintentos: el código es de un solo uso y válido 1 h.
2. **Corto → largo (60 días)**: inmediatamente después, `GET /access_token` con
   `grant_type=th_exchange_token`, `client_secret`, `access_token`. Respuesta:
   `{"access_token", "token_type", "expires_in"}`. El token corto se descarta: **solo se guarda
   el largo**.
3. **Renovación**: `GET /refresh_access_token` con `grant_type=th_refresh_token` y
   `access_token`. Condiciones oficiales: token largo **vigente**, con **≥ 24 h** de antigüedad
   y con `threads_basic` concedido. Devuelve un token válido 60 días desde la renovación. No
   usa el app secret. Un token no renovado en 60 días caduca y no puede renovarse.

**Timestamps** (spec FR-019, FR-032, FR-033):

- `token_obtained_at` = reloj de AutoPublisher en el momento de **recibir** la respuesta del
  intercambio a larga duración o de una renovación correcta. Solo se usa para comprobar la
  condición técnica de antigüedad mínima de 24 h de Meta; nunca para calcular la caducidad.
- `credential_expires_at` = `token_obtained_at + expires_in` (dato oficial de esa misma
  respuesta). Nunca se calcula a partir de reglas como "60 días".
- `data_access_expires_at` = último valor oficial de `debug_token` si es un Unix time
  positivo; si falta o es `0`, `null` (desconocido). Nunca se infiere de la regla de 90 días
  (ni al conectar ni tras renovar). Se actualiza al conectar, en Verify y tras cada renovación
  inspeccionada con éxito.
- **`data_access_expires_at` es solo informativo**: una renovación puede extender la concesión
  (perfiles públicos), así que una fecha local pasada puede ser metadata no actualizada. Nunca
  provoca por sí sola `reconnect_required`, ni en el `GET` ni en `get_valid_credentials`. El paso
  a `reconnect_required` exige una señal oficial actual (`debug_token.is_valid = false`, permiso
  requerido ausente, error definitivo de Meta como 190, mismatch de identidad), el token
  caducado según su propio `expires_at` o la credencial ausente.

**Fuente de verdad**: el secreto del almacén seguro es autoritativo para el token actual,
`token_obtained_at`, `expires_at` (derivado de `expires_in`) y `scopes`; se escriben en la misma
operación que el token. SQLite solo **refleja** `token_obtained_at` y `credential_expires_at`
para mostrarlos y para la comprobación local sin red del `GET`.

**Política de renovación de AutoPublisher** (`get_valid_credentials`):

La regla de 24 h es una **condición técnica de Meta** para poder renovar, no la política de
renovación. La política es una decisión de producto:

- `RENEWAL_WINDOW = 7 días` — constante interna de `threads_connections.py`; decisión de
  producto configurable en código, **no** una regla de Meta.
- `REFRESH_MIN_AGE = 24 h` — mínimo oficial de Meta (*Long-Lived Access Tokens*).
- `EXPIRY_MARGIN = 5 min` — margen de seguridad: un token se considera **vigente** si
  `expires_at - now > EXPIRY_MARGIN`, para no entregar una credencial que caduque durante la
  operación.

| Situación (leída del secreto) | Acción |
|---|---|
| Secreto ausente o ilegible | `reconnect_required` |
| `expires_at ≤ now` (caducado) | `reconnect_required` |
| Vigente y `expires_at - now > RENEWAL_WINDOW` | usar el token, **sin** renovar |
| `expires_at - now ≤ RENEWAL_WINDOW` y `now - token_obtained_at ≥ 24 h` | intentar renovar |
| `expires_at - now ≤ RENEWAL_WINDOW` y `now - token_obtained_at < 24 h` | usar el token mientras sea vigente (Meta no permitiría renovarlo) |
| `expires_at - now ≤ RENEWAL_WINDOW`, `now - token_obtained_at < 24 h` y ya dentro de `EXPIRY_MARGIN` | `reconnect_required`: el token no puede entregarse de forma segura y aún no es técnicamente renovable. No es una regla de Meta, sino la consecuencia de combinar la restricción oficial de 24 h con el margen interno de seguridad de AutoPublisher |
| Renovación OK | guardar el secreto nuevo y usar el token nuevo |
| Renovación con fallo temporal (`ThreadsUnavailable`, `ThreadsUnexpectedResponse`) y token vigente | conservar y usar el token actual; aviso en log sin datos sensibles; sin cambio de estado |
| Renovación con fallo temporal y token ya dentro de `EXPIRY_MARGIN` | `threads_unavailable`, sin cambio de estado |
| Fallo definitivo (`ThreadsTokenInvalid`, `ThreadsPermissionDenied`, `ThreadsRejected`) | `reconnect_required` |

- Solo se ejecuta cuando AutoPublisher **necesita** la credencial: Verify en esta feature y
  publicación en la Feature 011. **No hay scheduler ni renovación periódica.**
- Candado por cuenta: nunca dos renovaciones simultáneas de la misma credencial.
- Consecuencia aceptada: si una cuenta no se usa durante la ventana final de 7 días, su token
  caduca y pasa a `Reconnect required`; la interfaz muestra la caducidad para que el usuario
  pueda verificar antes.

**Rationale**: renovar solo en la ventana final evita escrituras en el keyring y llamadas a Meta
en cada uso, mantiene la renovación lejos del momento de conexión y deja 7 días de margen para
que algún uso (Verify o publicación) la dispare.

**Alternatives considered**: renovar en cada uso con ≥ 24 h (política de la Feature 008) —
descartada para Threads por decisión de producto; renovar solo a < 1 día — demasiado poco
margen para cuentas de uso esporádico; refresco periódico en el scheduler — prohibido por spec
FR-036 y acopla el núcleo.

**Inspección tras renovar**: tras guardar un token renovado, `get_valid_credentials` lo
inspecciona con `debug_token` (mismo mecanismo de §7). Éxito → se comprueba la identidad, se
actualizan los `scopes` confirmados en el secreto (solo si cambian, conservando token y fechas)
y `data_access_expires_at` en SQLite con el valor oficial. Señal definitiva (`is_valid=false`,
permiso ausente, `user_id` distinto) → `reconnect_required`. Fallo temporal → se conserva el
token nuevo (no se descarta ni se restaura el antiguo), no cambia el estado y se mantiene la
última metadata conocida hasta la siguiente verificación. Coste: una llamada extra a Meta por
renovación, como mucho una vez por ventana.

**Consistencia entre secreto y SQLite tras renovar**:

Orden de una renovación correcta: (1) Meta devuelve el token renovado; (2) se escribe el secreto
con el mismo `credential_ref` (token nuevo, `token_obtained_at = now`,
`expires_at = now + expires_in`); (3) se actualizan en SQLite `token_obtained_at`,
`credential_expires_at` y `updated_at`.

Si (2) falla → `credential_store_unavailable`; el secreto anterior sigue intacto y válido.

Si (2) tiene éxito y (3) falla:

- **No** se restaura el token antiguo (Meta puede haberlo invalidado al emitir el nuevo).
- **No** se considera perdida la renovación: se hace rollback de la sesión, se registra un aviso
  sin datos sensibles y la operación en curso continúa con el token nuevo.
- **No** se vuelve a renovar por culpa de metadata SQLite obsoleta: la política solo usa los
  valores del secreto.
- En el siguiente acceso a la credencial (`get_valid_credentials`, Verify) se lee primero el
  secreto, se compara con SQLite y, si `token_obtained_at` o `credential_expires_at` difieren,
  se **repara** SQLite copiando los valores del secreto (operación idempotente: repetirla no
  cambia nada). Después se aplica la política con el token nuevo.
- El `GET` de estado normalmente no lee el keyring. Solo cuando la metadata SQLite indica
  `credential_expires_at ≤ now` en una conexión `connected`, consulta el secreto antes de
  marcar `reconnect_required`: si el secreto tiene una caducidad posterior y vigente, repara
  SQLite y la conexión sigue `connected`; si el almacén no está disponible, no cambia el estado.

---

---

## 7. Comprobación de permisos efectivos (spec FR-008)

**Hallazgo**: el intercambio código → token **no** devuelve la lista de permisos (a diferencia de
Instagram Login). La documentación ofrece `GET /debug_token`:

- Parámetros: `input_token` (token a inspeccionar) y `access_token`, descrito literalmente como
  *"Threads Graph API user access token of a Threads tester"*. Ambos tokens *"can be associated
  with different users but must be associated with the same app"*.
- Respuesta (`data`): `type`, `application`, `data_access_expires_at`, `expires_at`,
  `is_valid`, `issued_at`, `scopes` (array), `user_id`.
- *App Access Tokens*: existen (`grant_type=client_credentials` o `TH|<APP_ID>|<APP_SECRET>`),
  pero la documentación solo los asocia a endpoints como oEmbed y **no** indica que
  `debug_token` los acepte; tampoco documenta su caducidad.

**Decision**: autenticar `debug_token` con la **propia credencial de larga duración del usuario**
como `access_token` e `input_token`:

- En Development Mode solo los Threads testers pueden conceder permisos (*Get Started*), así
  que el usuario conectado es, por definición, un Threads tester de la misma app: cumple
  literalmente el requisito documentado.
- No se crea, guarda ni transmite ninguna credencial de aplicación adicional: el App Access
  Token **no se usa**. (Si una revisión futura lo necesitara, se generaría en el backend en
  cada uso, nunca se persistiría y se redactaría de logs; hoy no aplica.)
- La conexión solo se completa si `data.is_valid` es `true`, `data.user_id` coincide con el
  `user_id` del intercambio y con `/me.id`, y `data.scopes` contiene **ambos**
  `threads_basic` y `threads_content_publish`. Si falta alguno → `threads_permission_missing`
  (indicando cuáles). Si la respuesta no trae `scopes`/`is_valid`/`user_id` con el tipo
  esperado → `threads_unexpected_response` y no se conecta (fail-closed).
- Un error de `debug_token` con código de permisos o "no tester" se clasifica como
  `ThreadsPermissionDenied` → `threads_permission_missing`; nunca se degrada a "conectar sin
  comprobar".
- Verify repite la inspección (spec FR-037) y también se inspecciona el token tras cada
  renovación correcta (§6).
- **Scopes en el secreto durante Verify**: solo se reescribe el secreto si los scopes
  confirmados difieren de los almacenados, con un único `set` del valor completo que conserva
  `access_token`, `token_obtained_at` y `expires_at`. Si la escritura falla →
  `credential_store_unavailable`, secreto anterior intacto y sin cambio de estado. Un permiso
  requerido ausente lleva a `reconnect_required` sin depender de esa escritura.

**Validación real**: quickstart paso 5 (bloqueante): `debug_token` responde con la credencial
del tester, `is_valid=true`, `user_id` coherente y `scopes` con los dos permisos. Si Meta
rechaza la llamada o los scopes no pueden comprobarse inequívocamente → **detener** y revisar
esta decisión (por ejemplo, evaluar el App Access Token con su análisis de seguridad), sin
relajar FR-008.

**Limitación documentada**: el requisito "token de un Threads tester" puede no cumplirse para
usuarios sin rol cuando la app pase App Review y se publique. AutoPublisher es local y de un
único usuario-tester; distribuirlo a otros usuarios está fuera de alcance y obligaría a revisar
esta decisión.

**Alternatives considered**: deducir permisos de que `/me` responda — no distingue
`threads_content_publish`; consultar `/me/permissions` — no documentado para Threads; asumir
concesión completa — viola FR-008.

---

## 8. Identidad

**Decision**: `GET /v1.0/me?fields=id,username,name,threads_profile_picture_url`.

- `id` (Threads user ID) es la **identidad autoritativa**; se exige que coincida con el
  `user_id` del intercambio de código y con `debug_token.user_id`. Cualquier incoherencia →
  `threads_unexpected_response` y no se conecta.
- `username` obligatorio (cadena no vacía); `name` y `threads_profile_picture_url` opcionales.
- Los IDs se normalizan a cadena (Meta puede devolver número o cadena).
- No se piden `threads_biography` ni `is_verified` (no se necesitan).
- No se filtra por tipo de cuenta: la documentación no exige un tipo concreto para la Threads
  API (spec Assumptions).

---

## 9. Requisitos adicionales para la Feature 011 (spec FR-040)

**Hallazgo**: para publicar, la documentación exige `threads_content_publish` y que la
multimedia esté en un servidor público en el momento de la petición (eso es responsabilidad de la
Feature 011, que podrá reutilizar `media_delivery`). Existe además un límite de publicación
consultable (`threads_publishing_limit`), que es un detalle de ejecución, no de conexión. No se
ha encontrado ningún requisito de tipo de perfil (público/privado, verificado) para publicar.

**Decision**: Verify comprueba solo credencial válida, identidad y los dos permisos. El
límite de publicación y la multimedia pública se investigarán y aplicarán en la Feature 011.

---

## 10. Clasificación de errores de Meta (solo en `threads_gateway.py`)

Formato Graph: `{"error": {"message", "type", "code", "error_subcode", "fbtrace_id"}}`.

| Situación | Excepción semántica |
|---|---|
| Error de transporte (DNS, timeout, conexión) | `ThreadsUnavailable` |
| HTTP 5xx o 429 | `ThreadsUnavailable` |
| `code` en {1, 2, 4, 17, 32, 613} | `ThreadsUnavailable` |
| `code` 190 (token inválido/caducado/revocado) | `ThreadsTokenInvalid` |
| `code` 10 o 200–299 (permisos) | `ThreadsPermissionDenied(permission?)` |
| Otro 4xx | `ThreadsRejected` |
| 200 con JSON no objeto o sin campos esperados | `ThreadsUnexpectedResponse` |

- `ThreadsPermissionDenied.permission` solo se rellena si el mensaje de Meta nombra
  exactamente uno de los dos permisos requeridos; nunca se propaga texto libre de Meta.
- Ninguna excepción lleva cuerpo, URL ni token; se lanzan `from None`.
- En el intercambio de código o a larga duración, cualquier `ThreadsRejected`/
  `ThreadsTokenInvalid` → `threads_token_exchange_failed` (código usado/caducado, URI distinto,
  app secret incorrecto). `ThreadsUnavailable` → `threads_unavailable`, indicando que debe
  iniciarse una nueva autorización (el código no se reintenta).
- Política de estado (spec FR-034/035): `ThreadsTokenInvalid`, `ThreadsPermissionDenied` y
  `debug_token.is_valid=false` son **definitivos** (→ `reconnect_required`);
  `ThreadsUnavailable` es **temporal** (sin cambio de estado).

**Validación real**: no se fuerzan errores reales contra Meta; la tabla se cubre con el fake.

---

## 11. Configuración local de la app Threads

**Decision**: archivo JSON local `backend/data/threads-app.json`, sobreescribible con
`AUTOPUBLISHER_THREADS_APP_FILE`:

```json
{
  "app_id": "<Threads App ID>",
  "app_secret": "<Threads App Secret>",
  "redirect_uri": "https://localhost/autopublisher/threads/callback"
}
```

- Se lee en cada operación que la necesita (como Instagram); `oauth_configured` se calcula en
  cada `GET` sin exponer valores.
- Validación: `app_id` numérico, `app_secret` no vacío, `redirect_uri` según §4.
- `.gitignore`: se añade `threads-app*.json` (además de los patrones existentes).
- `MetaAppConfig` de Instagram **no** se reutiliza: `ThreadsAppConfig` propio con
  `app_secret` fuera de `repr`.
- Verify **no** exige la configuración: la renovación y `debug_token` (con token de usuario) no
  usan el app secret.

---

## 12. Deauthorize callback URL y Data Deletion Requests URL

**Hallazgo**: la página del caso de uso de Threads lista, junto a los *Valid OAuth Redirect
URIs*, una *Deauthorize callback URL* y una *Data Deletion Requests URL*. La documentación
consultada no aclara si son obligatorias para guardar la configuración ni si Meta comprueba que
sean alcanzables durante Development Mode.

**Decision**:

- AutoPublisher **no implementa** estos callbacks en la Feature 010: no expone rutas para ellos
  ni procesa sus avisos. Una revocación se detecta en el siguiente uso o Verify
  (`ThreadsTokenInvalid` → `reconnect_required`).
- No se asume que dejarlos sin rellenar sea aceptable para Meta: es un comportamiento de la
  plataforma que **solo se puede comprobar** en la validación real.
- Durante la validación real (quickstart paso 2, comprobación B, bloqueante) se intenta
  configurar el caso de uso Threads **sin** esas URLs, si Meta lo permite.
- Si el dashboard exige URLs públicas y funcionales (o impide guardar la configuración o
  completar el flujo OAuth sin ellas) → **detener** la validación y revisar la arquitectura antes
  de continuar.
- **Nunca** se usarán valores ficticios, endpoints falsos, `https://localhost/...` como
  sustituto, túneles, dominios de terceros ni ningún otro workaround automático.

---

## 13. Revocación remota

**Decision**: sin revocación remota. Disconnect borra el secreto del keyring y la fila local.
La interfaz y `docs/threads-accounts.md` indican cómo retirar el acceso desde Threads
(*Settings → Account → Website permissions*).

**Rationale**: la documentación consultada no ofrece un endpoint para que la app revoque la
autorización de un usuario de Threads (spec FR-044).

---

## 14. Intentos OAuth pendientes

**Decision**: `ThreadsAttemptRegistry` propio en `threads_oauth.py`, con las mismas reglas que
el de Instagram: solo en memoria, `state` de 32 bytes (`secrets.token_urlsafe`), comparación
en tiempo constante, un `state` distinto no consume el intento, latest-attempt-wins, TTL
`THREADS_ATTEMPT_TTL = 10 min` (< 1 h de validez del código) y retención de resultados
terminales sin secretos `THREADS_ATTEMPT_RETENTION = 10 min`. Las credenciales pendientes de
confirmación de cambio de cuenta solo viven en el intento.

**Rationale**: extraer un registro genérico obligaría a refactorizar YouTube e Instagram,
ampliando el alcance (Constitution I, spec "no amplíes alcance"); la Feature 008 tomó la misma
decisión. Se registra como candidato a refactor futuro.

---

## 15. Almacenamiento seguro

**Decision**: `KeyringCredentialStore(THREADS_SERVICE)` con
`THREADS_SERVICE = "autopublisher.threads"` en `credential_store.py` (solo una constante nueva,
sin cambios de lógica). Usuario = `credential_ref` (UUID hex). Valor JSON:
`{"access_token", "token_obtained_at", "expires_at", "scopes"}`. Mismos backends permitidos y
sin fallback; tests con `InMemoryCredentialStore`.

**Orden seguro entre almacén y SQLite** (spec FR-029): cada conexión, reconexión o
confirmación guarda el secreto bajo una **`credential_ref` nueva**, hace commit de la fila y
solo entonces borra la referencia anterior. Si el commit falla (cualquier error), se borra el
secreto nuevo y la fila anterior —con su referencia y su secreto intactos— sigue siendo la
conexión vigente. Nunca se elimina la única credencial anterior utilizable antes de que la nueva
sea autoritativa. La renovación es el único caso que reutiliza la referencia; ahí aplica la
reconciliación secreto → SQLite (§6) y nunca se restaura un token antiguo. No se introduce
ningún mecanismo genérico de transacciones distribuidas.

---

## 16. Logging

**Decision**: filtro `RedactThreadsSecrets` instalado en los mismos `HTTP_LOGGERS` que YouTube e
Instagram (`httpx2`, `httpcore2.*`) desde `create_app`. Redacta en mensajes:
`access_token`, `input_token`, `client_secret`, `code`, `state` (parámetros `=valor`),
cabeceras `Bearer …` y prefijos `TH|…`. Los logs propios solo registran `account_id` y códigos
de error seguros. Tests específicos con `caplog` sobre peticiones reales del fake.

**Rationale**: los endpoints de token y `debug_token` llevan secretos en la query string por
diseño de Meta (`client_secret`, `access_token`, `input_token`), y `httpx2` registra la URL a
nivel INFO.

---

## 17. Frontend

**Decision**: `ThreadsConnectionPanel.tsx` nuevo, siguiendo `InstagramConnectionPanel` como
referencia pero sin importarlo ni generalizarlo. `AccountList.tsx` añade una condición
`account.platform === "threads"` (el mismo punto de extensión existente). Tipos y funciones API
propias en `types.ts`/`api.ts`, soporte en `test-fake-api.ts`. Sin almacenamiento del navegador
(cubierto por `storage-safety.test.tsx`). Sin rediseño.

---

## 18. App Review y Development Mode

**Decision**: validar con la cuenta propia como **Threads tester** (App roles → Add People →
Threads Tester; aceptar en Threads *Settings → Account → Website permissions → Invites*). Según
*Get Started*, los testers pueden conceder `threads_basic` y `threads_content_publish` sin App
Review. No se solicita App Review ni se intenta eludir ninguna restricción. Si en la validación
real Meta exigiera App Review para la cuenta tester → documentar y detener.
