# Feature Specification: Deployment & Mobile Readiness

**Feature Branch**: `020-deployment-mobile-readiness`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "Feature 020 — Deployment & Mobile Readiness. Convertir AutoPublisher en una aplicación estable, local-first, portable entre máquinas, accesible desde otros dispositivos de la misma LAN, capaz de funcionar sin VS Code ni terminales abiertas y preparada para ejecutarse en el futuro 24/7 en una máquina doméstica dedicada (Raspberry Pi / mini PC). Local/LAN deployment readiness, NO public Internet/SaaS. Incluye: ejecución sin entorno de desarrollo, servicio persistente con reinicio automático, reinicio seguro, acceso LAN, postura de seguridad LAN, persistencia portable, separación de configuración/secretos, backup básico, operación y diagnóstico, mobile readiness real, decisión sobre PWA, procedimiento de actualización y migración de host. Sin cloud, VPS, dominio, HTTPS público, multiusuario, PostgreSQL, colas distribuidas, push ni offline-first. Sin elegir todavía tecnología de despliegue."

## Contexto

AutoPublisher es una aplicación single-user (FastAPI + React/Vite, SQLite, media en disco,
scheduler local dentro del proceso backend, secretos de plataforma en el almacenamiento
seguro del sistema operativo). Hoy se ejecuta "como desarrollador": backend con recarga
automática y frontend con el servidor de desarrollo, ambos lanzados a mano desde
terminales, escuchando solo en el propio ordenador.

Feature 020 pasa de:

> "aplicación que ejecuto como desarrollador"

a:

> "servicio doméstico que simplemente está disponible"

### Principio rector

**Local/LAN deployment readiness, NO public Internet/SaaS deployment.** Se describe el
comportamiento de producto; la tecnología concreta de despliegue (gestor de servicios,
contenedores, servidor web, proxy, etc.) se elige en `/speckit-plan`.

### Estado actual relevante (inspección del repositorio, 2026-10-20)

| Área | Estado actual | Implicación para 020 |
|---|---|---|
| Arranque | Backend con `uvicorn --reload` en `127.0.0.1:8000`; frontend con servidor de desarrollo Vite (`:5173`) que reenvía `/api` al backend. | No existe modo de ejecución "producción"; el frontend compilado no lo sirve nadie. |
| Llamadas del frontend | Todas usan rutas relativas `/api/...`; no hay host ni puerto codificados. Rutas cliente (URL como único estado de navegación). | Favorable: un único origen que sirva UI + API funciona desde cualquier dispositivo. Hace falta fallback a `index.html` para rutas no-`/api` (ya documentado en el README). |
| Datos | SQLite en `backend/data/autopublisher.db`; media en `backend/data/media/` (≈245 MB hoy); ficheros de configuración de plataformas en `backend/data/*.json` (permisos 0600). Cada ruta es sobrescribible con una variable `AUTOPUBLISHER_*` distinta. Rutas por defecto relativas al directorio del código. | Los datos viven dentro del checkout del código; no hay un "directorio de datos" único y explícito. Riesgo de acoplar datos a la ubicación del repo y de perderlos al reinstalar. |
| Media | Rutas relativas al directorio raíz de media guardadas en la BD; `storage.resolve` impide salir de la raíz; `tmp/` se limpia al arrancar. | Favorable para portabilidad: mover la raíz de media completa no rompe referencias. |
| Esquema BD | Migraciones aplicadas automáticamente al arrancar. | Favorable para actualizaciones. Una migración fallida debe impedir arrancar de forma diagnosticable. |
| Secretos | Tokens/sesiones de YouTube, Instagram, Threads, TikTok y Telegram en el keyring del SO, solo con backends nativos permitidos (Secret Service/libsecret/KWallet…), **sin fallback**: si no está disponible o está bloqueado, las operaciones fallan con `CredentialStoreUnavailable`. Secretos de aplicación (client secrets de plataforma, credenciales del proveedor de media temporal) en ficheros JSON 0600 en `backend/data/`. | **Riesgo crítico**: en Linux el keyring suele requerir una sesión de escritorio iniciada y desbloqueada. Un servicio arrancado al encender la máquina sin login (o un host headless como una Raspberry Pi) puede no tener acceso → publicaciones automáticas fallarían. Los tokens del keyring no viajan con un backup ni a otra máquina. |
| OAuth | YouTube exige redirect `http://127.0.0.1:<port>`; TikTok exige redirect loopback y además rechaza callbacks cuyo cliente o socket no sea loopback y valida el puerto real del socket; Instagram/Threads usan un paso de "pegar URL" con redirect `https://localhost/...`. | Conectar/reconectar cuentas YouTube y TikTok **solo funciona desde un navegador del propio host**, y la exposición LAN / un intermediario delante del backend puede romper la comprobación de puerto de TikTok. |
| Scheduler | Hilo dentro del proceso backend; ciclo cada ~30 s; ventana automática de 10 min; tras la ventana el Post queda "Missed" (nunca se publica tarde); pausa global persistida en BD; al arrancar se cierran las ejecuciones interrumpidas por el proceso anterior (nunca se reanudan) antes de iniciar el scheduler. `/api/automation` ya expone `paused`, `running`, `last_check_at`. | El diseño ya es "database-driven" y tolera reinicios. No requiere rediseño. Depende de que el reloj del host sea correcto. |
| `/health` | Devuelve siempre `{"status":"ok"}` si el proceso responde; no informa de BD, scheduler ni almacenamiento seguro. | Insuficiente para saber si el scheduler está vivo; el dato existe en `/api/automation`. |
| Autenticación | No existe ninguna. Cualquiera que alcance el puerto tiene acceso completo (leer media, publicar, gestionar cuentas). Hoy está mitigado porque solo escucha en loopback. | Exponer en LAN sin protección = cualquier dispositivo de la Wi-Fi puede publicar en cuentas reales. |
| Logs | Sin configuración propia de logging (por defecto del servidor); filtros de redacción de secretos instalados para OAuth/media delivery; access logs de callbacks redactados. | Base razonable; falta destino persistente y consultable fuera de una terminal. |
| Subidas | Hasta 2 GiB por fichero; el framework puede bufferizar la subida en el directorio temporal del sistema (posible `tmpfs`/RAM). | Riesgo en hosts con poca RAM (Raspberry Pi) y en subidas desde móvil por Wi-Fi. |
| ARM64 | Dependencias Python con wheels ARM64 o puras (Pillow, SQLAlchemy, Telethon, boto3, keyring); `ffmpeg/ffprobe` disponibles en distribuciones ARM; Node solo necesario para compilar el frontend. | Sin incompatibilidades obvias de código. Riesgos: keyring headless, ausencia de reloj RTC en Raspberry Pi (hora incorrecta hasta sincronizar), RAM limitada en subidas grandes. |

## Decisiones cerradas en esta spec

| # | Decisión | Justificación |
|---|---|---|
| D1 | **Un único punto de acceso** (una dirección + un puerto) sirve la UI compilada y la API; el dispositivo cliente nunca necesita `localhost` ni un segundo puerto. | El frontend ya usa rutas relativas; un solo origen evita CORS, configuración por dispositivo y dependencia del servidor de desarrollo. |
| D2 | **El scheduler no se rediseña.** Sigue viviendo dentro del proceso principal y conserva la ventana de 10 min, "Missed", la pausa persistida y la recuperación de ejecuciones interrumpidas. | Ya es dirigido por la BD y tolera reinicios; los problemas de deployment se resuelven manteniendo el proceso vivo, no cambiando las reglas. |
| D3 | **Nada se publica durante el downtime ni "tarde" al volver.** Los Posts cuya ventana pasó con la máquina apagada (o sin sesión de usuario con acceso al keyring, D13) aparecen como **Missed** con las acciones existentes (Reschedule / Publish now). | Mantiene la regla de 007 y el principio de la Constitution: ningún fallo silencioso ni publicación inesperada. |
| D4 | **Acceso LAN opt-in.** Por defecto la instalación solo es accesible desde el propio host; habilitar el acceso desde la LAN es una decisión explícita de la configuración de despliegue del host. | Postura segura por defecto; quien solo usa el host no expone nada en la red. |
| D5 | **Conectar/reconectar cuentas OAuth (YouTube, TikTok) sigue siendo una acción del host.** Desde otros dispositivos la UI explica que esa acción debe hacerse desde el navegador del host, en vez de iniciar un flujo que fallaría. Instagram/Threads (paso de pegar URL) y Telegram (código/2FA) pueden funcionar desde cualquier dispositivo si su flujo actual lo permite; si no, mismo tratamiento. | Las plataformas exigen redirects loopback; cambiarlo requeriría HTTPS/dominio público (fuera de alcance). La reconexión es infrecuente; el uso diario (revisar, programar, publicar) sí funciona en LAN. |
| D6 | **Tres capas separadas**: (1) **código** (reemplazable); (2) **estado portable de la aplicación**, en un único **directorio de datos** configurable: BD, Media, copias limpias, configuración local de plataformas necesaria, hash de la contraseña de instalación (con sus parámetros y sal) y demás datos persistentes del producto; las sesiones activas **no** son portables; (3) **configuración de despliegue del host**, específica de cada máquina: ruta del directorio de datos, bind / LAN habilitada, puerto, nombres/direcciones permitidos y configuración del gestor de servicios. Los valores por defecto actuales (`backend/data`) siguen siendo válidos para desarrollo. | El estado portable es lo que se respalda y se mueve; la configuración del host describe *esta* máquina y no tiene sentido aplicarla en otra. Evita depender de rutas del portátil actual. |
| D7 | **Los tokens del almacenamiento seguro del SO no se exportan en backups ni migraciones.** Tras restaurar en otra máquina (o perder el keyring) las cuentas aparecen como "Reconnect needed" y se reconectan con los flujos existentes. | No se rebaja la seguridad de los secretos por comodidad de deployment (requisito explícito); las cuentas ya tienen un estado y flujo de reconexión visibles. |
| D8 | **PWA: opción B — se deja para una feature posterior.** 020 no añade manifest instalable, Service Worker, modo standalone ni notificaciones. | (1) Instalabilidad PWA y Service Workers exigen *secure context* (HTTPS o `localhost`); en una LAN por `http://<ip>` los navegadores no permiten instalar ni registrar el SW, y HTTPS local con certificados es trabajo y fricción fuera del objetivo. (2) La experiencia móvil ya es responsive (018/019). (3) El valor marginal (icono en home screen) se obtiene con un marcador del navegador. Reevaluar junto con acceso remoto vía VPN privada / HTTPS. |
| D9 | **Backup local manual** bajo demanda que produce un único artefacto con el **estado portable de la aplicación** (BD consistente sin sesiones activas + Media + copias limpias + configuración local de plataformas + hash de contraseña). Puede incluir un manifest **informativo** de la instalación origen, que nunca se aplica automáticamente. La configuración de despliegue del host **no** se restaura en otra máquina. Restauración documentada, con el servicio detenido y validando el artefacto antes de sustituir datos; tras restaurar no existe ninguna sesión activa. Sin programación automática obligatoria, sin cloud, sin incrementales. | Simple, verificable y suficiente para no perder el trabajo; restaurar en otro host no hereda rutas, puertos ni exposición LAN de la máquina original. |
| D10 | **Plataforma objetivo**: Linux en el ordenador actual (x86-64). ARM64 (Raspberry Pi / mini PC) no se exige ni se verifica en 020, pero no se toman decisiones que lo impidan y las incompatibilidades conocidas quedan documentadas. | Alcance acotado sin cerrar la evolución a servidor doméstico 24/7. |
| D11 | **Actualización manual** (detener → actualizar código/dependencias → arrancar; migraciones automáticas al arrancar), con recomendación de backup previo. Sin auto-updater ni zero-downtime. | Mínimo suficiente para single-user doméstico. |
| D12 | **Contraseña única de instalación** obligatoria en modo instalación para acceder a la aplicación, tanto desde el host como desde la LAN, con una sesión de navegador que evita pedirla continuamente (Q1 → A). La configuración inicial y el restablecimiento por olvido son acciones locales del host, nunca un endpoint de setup abierto en la LAN. Sin usuarios, roles, permisos, signup ni recuperación por email. | Protege a nivel aplicación la capacidad de publicar, la Media y los datos privados frente a otros dispositivos y páginas web de la red, manteniendo el modelo single-user. Aplicarla también en el host es lo más simple y coherente (sin excepciones por IP/proxy). Sus límites sobre HTTP están en D14. |
| D14 | **Threat model LAN sobre HTTP (sin HTTPS en 020).** 020 protege frente a: otros dispositivos que intentan usar AutoPublisher sin autenticarse; páginas web cross-site; DNS rebinding; acceso accidental o no autorizado a nivel aplicación. 020 **no puede proteger** frente a quien pueda interceptar el tráfico, hacer MITM o controlar la red/punto de acceso: sobre HTTP la contraseña, la cookie de sesión, la Media y los datos viajan sin cifrar por la red local. El acceso LAN está pensado **solo para una red doméstica privada y de confianza** y no debe habilitarse en redes públicas o no confiables. | HTTPS en LAN (certificados, confianza en dispositivos) está fuera de alcance; prometer más seguridad de la que HTTP ofrece sería engañoso. El acceso solo-host (por defecto) no atraviesa la red. |
| D13 | **Secretos: se mantiene el keyring del usuario** (Q2 → C). El servicio se ejecuta dentro de la sesión del usuario y arranca automáticamente al iniciarse esa sesión. Puede arrancar también con login automático, pero el keyring puede seguir bloqueado (con login automático de GNOME no se desbloquea): hasta que el usuario lo desbloquee no se garantiza la publicación automática, el diagnóstico autenticado lo indica como degradado y los Posts que pierdan su ventana terminan como Missed según las reglas existentes. La guía desaconseja configurar un keyring sin contraseña solo para conseguir arranque desatendido. Un almacén de secretos cifrado independiente de la sesión gráfica queda para una futura feature de host headless (Raspberry Pi / mini PC). | No se rebaja ni se rediseña la seguridad de los secretos en 020; la Constitution (keyring del SO) se respeta; el límite queda documentado y visible en vez de prometer disponibilidad desatendida. |

## Clarifications

### Session 2026-10-20

- Q: ¿Qué protección mínima exige el acceso desde la LAN? → A: Una única contraseña de instalación para todo acceso (host y LAN), con sesión de navegador razonable. Sin multiusuario, roles, signup ni recuperación por email. Hashing, cookies/sesiones, CSRF y expiración se deciden en `/speckit-plan`. La LAN sigue desactivada por defecto (D12, D14, FR-030–FR-039).
- Q: ¿Cómo accede el servicio a los secretos cuando arranca sin sesión de usuario iniciada? → A: Se mantiene el keyring del usuario; el servicio corre en la sesión del usuario y arranca al iniciarla. Sin garantía de publicación automática tras un reboot hasta que haya una sesión que desbloquee el keyring; el login automático es opcional y no desbloquea el keyring (ver C1). El secret store cifrado headless queda para una feature futura (D13, FR-010, FR-052).

### Session 2026-10-20 (revisión del plan)

- C1: El login automático de GNOME **no** desbloquea el keyring. AutoPublisher puede arrancar al iniciarse la sesión, pero hasta que el usuario desbloquee el keyring no se garantiza la publicación automática; el diagnóstico lo muestra degradado y los Posts que pierdan su ventana terminan como Missed. La guía desaconseja un keyring sin contraseña solo para arrancar desatendido (D13, FR-010a).
- C2: "Todo acceso requiere contraseña" significa que todos los **datos y acciones privados** requieren sesión; sin sesión solo se sirve lo necesario para iniciar y autenticar (shell de la UI, contrato mínimo de acceso, health mínimo, callbacks OAuth aprobados). La Media siempre requiere sesión (FR-030).
- C3: Precedencia de configuración: variable `AUTOPUBLISHER_*` individual > `AUTOPUBLISHER_DATA_DIR` > configuración del host > default (FR-040).
- C4: El modo desarrollo, sin contraseña, solo acepta clientes loopback aunque escuche en todas las interfaces; las pruebas LAN/móvil usan el modo instalación (FR-004, FR-030h).
- H2: La contraseña (hash con parámetros y sal) es portable; las **sesiones activas no**: el backup no las contiene y tras un restore todos los navegadores inician sesión de nuevo (FR-030c, FR-050, FR-053a).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ejecutar AutoPublisher como aplicación real (Priority: P1)

El usuario arranca AutoPublisher en modo instalación (no desarrollo) con un procedimiento
documentado y lo abre en el navegador del host a través de un único punto de acceso, sin
servidor de desarrollo, sin recarga automática y sin VS Code.

**Why this priority**: Es la base de todo lo demás; sin un modo de ejecución de
instalación no hay servicio, ni LAN, ni móvil.

**Independent Test**: En una sesión sin VS Code ni terminales de desarrollo, seguir la
documentación de arranque, abrir la dirección indicada en el navegador del host, navegar
por Home/Library/Posts/Settings y recargar una URL profunda (p. ej. un Post concreto).

**Acceptance Scenarios**:

1. **Given** una instalación configurada, **When** el usuario la arranca con el procedimiento documentado, **Then** la UI y la API quedan disponibles en una única dirección y puerto, sin servidor de desarrollo ni recarga automática.
2. **Given** AutoPublisher en ejecución, **When** se abre directamente o se recarga una URL profunda (`/p/<id>/posts/<postId>`, `?view=calendar&week=…`), **Then** se muestra esa vista (no un 404).
3. **Given** falta una configuración obligatoria o el directorio de datos no es utilizable, **When** se intenta arrancar, **Then** el arranque se detiene con un mensaje que dice qué falta y dónde, sin exponer secretos.

---

### User Story 2 - Servicio persistente y recuperación ante fallos (Priority: P1)

AutoPublisher puede configurarse para arrancar automáticamente al iniciarse la sesión del
usuario en el host y se vuelve a levantar solo si el proceso muere inesperadamente; el
usuario puede detenerlo, reiniciarlo y consultar su estado y logs.

**Why this priority**: Es el objetivo central ("servicio doméstico que simplemente está
disponible") y la condición para que el scheduler publique sin supervisión mientras la
sesión del usuario está activa.

**Independent Test**: Instalar como servicio, reiniciar el SO e iniciar sesión (Journey A),
y matar el proceso a la fuerza (Journey D); en ambos casos el health vuelve a OK sin
intervención.

**Acceptance Scenarios**:

1. **Given** AutoPublisher instalado como servicio, **When** la máquina se reinicia y el usuario inicia su sesión, **Then** AutoPublisher vuelve a estar disponible sin abrir VS Code ni ejecutar comandos (Journey A); con un inicio de sesión manual el keyring queda accesible.
2. **Given** la máquina se ha reiniciado y todavía no hay sesión de usuario, o la sesión se inició por login automático y el keyring sigue bloqueado, **When** el usuario consulta la documentación o el diagnóstico, **Then** entiende que la publicación automática no está garantizada hasta iniciar sesión y desbloquear el keyring, el diagnóstico lo muestra degradado, y los Posts cuya ventana pase en ese intervalo aparecerán como **Missed**.
3. **Given** el servicio en marcha, **When** el proceso principal termina inesperadamente, **Then** se reinicia automáticamente, el health vuelve a OK y el fallo queda registrado con su causa diagnosticable (Journey D).
4. **Given** un fallo que se repite al arrancar (p. ej. configuración inválida), **When** el mecanismo de reinicio lo intenta, **Then** no entra en un bucle infinito de reinicios rápidos sin rastro: el fallo queda visible en el estado del servicio y en los logs.
5. **Given** el servicio instalado, **When** el usuario sigue la documentación, **Then** sabe detener, arrancar, reiniciar, ver el estado y ver los logs.

---

### User Story 3 - Reinicio seguro y scheduler fiable (Priority: P1)

Tras reiniciar AutoPublisher, el SO o apagar y encender la máquina, todos los datos siguen
presentes y los Posts programados futuros siguen programados y el scheduler los vuelve a
reconocer; lo que venció durante el apagado se muestra como Missed.

**Why this priority**: Una programación perdida o una publicación inesperada es el fallo
más grave del producto (Constitution V).

**Independent Test**: Journeys C y E: crear un Post programado a futuro, reiniciar el
servicio y la máquina (con inicio de sesión del usuario), comprobar estado, publicación a
su hora y Missed para un Post cuya ventana pasó con la máquina apagada o sin sesión.

**Acceptance Scenarios**:

1. **Given** un Post programado (auto-publish) para dentro de 30 minutos, **When** se reinicia el servicio, **Then** el Post sigue "Scheduled · automatic" y se publica en su ventana (Journey C).
2. **Given** un Post programado cuya ventana completa transcurre con la máquina apagada, o encendida pero sin sesión de usuario capaz de acceder al keyring, **When** AutoPublisher vuelve a estar en marcha con acceso al keyring, **Then** el Post aparece como **Missed** con Reschedule / Publish now y no se publica automáticamente.
3. **Given** AutoPublisher en marcha pero sin acceso al keyring, **When** llega la ventana de un Post programado, **Then** no se publica, el motivo es visible (cuenta/almacenamiento seguro no disponible, como hoy) y nada falla en silencio.
4. **Given** una publicación en curso cuando el proceso muere, **When** el servicio vuelve a arrancar, **Then** esa ejecución se cierra según las reglas existentes (nunca se reanuda ni se reenvía a ciegas) y queda visible para el usuario.
5. **Given** la automatización estaba en pausa, **When** se reinicia, **Then** sigue en pausa.
6. **Given** un reinicio completo y el usuario ha iniciado sesión, **When** se abre la app, **Then** Projects, Accounts, Media (con sus ficheros y copias limpias), Posts, historial, schedules, presets, configuración de plataformas y la contraseña de instalación siguen presentes (Journey E), y las cuentas conectadas siguen "Ready" (keyring accesible, D13).

---

### User Story 4 - Acceso desde la LAN y uso real en móvil (Priority: P2)

Con el acceso LAN habilitado, el usuario abre AutoPublisher desde otro ordenador, móvil o
tablet de la misma red usando la dirección del host; puede navegar, revisar Posts, abrir
Calendar y Post detail, cambiar schedules y usar Publish / Finish later y los dialogs/sheets.

**Why this priority**: Es el principal beneficio visible para el usuario tras tener el
servicio estable.

**Independent Test**: Journey B con un móvil real en la misma Wi-Fi, más un recorrido
de Publish de una Media existente (programar y Finish later) y una subida pequeña.

**Acceptance Scenarios**:

1. **Given** el acceso LAN habilitado, **When** el usuario consulta la documentación o Settings, **Then** conoce la dirección y el puerto a usar desde otros dispositivos y los requisitos de red.
2. **Given** un móvil en la misma Wi-Fi, **When** abre la dirección del host e introduce la contraseña de instalación, **Then** ve AutoPublisher, puede consultar Posts y abrir Calendar y Post detail (Journey B), con previews de imágenes y vídeos.
3. **Given** un móvil en la LAN, **When** reprograma un Post o completa Publish / Finish later, **Then** el resultado es el mismo que en el host.
4. **Given** un móvil en la LAN, **When** intenta conectar/reconectar una cuenta YouTube o TikTok, **Then** la UI explica que debe hacerse desde el navegador del host en lugar de iniciar un flujo que fallaría.
5. **Given** el acceso LAN deshabilitado (por defecto), **When** otro dispositivo intenta acceder, **Then** no obtiene respuesta de la aplicación.

---

### User Story 5 - Contraseña de instalación y seguridad LAN (Priority: P2)

El acceso a AutoPublisher en modo instalación (desde el host o desde la LAN) exige una única
contraseña de instalación; una vez introducida, el navegador mantiene una sesión razonable.
Con el acceso LAN habilitado en una red doméstica de confianza, otro dispositivo o una
página web ajena no puede, a nivel aplicación, leer la Media privada, ver secretos ni
publicar en las cuentas del usuario sin la contraseña. El usuario sabe además qué no
protege 020 al usar HTTP (D14).

**Why this priority**: La app guarda credenciales reales y puede publicar; la exposición
LAN sin protección convierte cualquier dispositivo de la Wi-Fi (invitados, IoT) en un
publicador. Saber los límites evita habilitar la LAN donde no es seguro.

**Independent Test**: Configurar la contraseña, acceder desde el host y desde un segundo
dispositivo de la LAN con y sin contraseña, cerrar sesión, y verificar que peticiones sin
sesión, con un `Host` no permitido o desde orígenes ajenos son rechazadas.

**Acceptance Scenarios**:

1. **Given** una instalación nueva, **When** se configura por primera vez siguiendo la guía, **Then** el usuario establece la contraseña de instalación mediante una acción local en el host antes de poder usar la aplicación; sin contraseña configurada, el modo instalación no sirve la aplicación y ningún dispositivo de la LAN puede establecerla.
2. **Given** el host o un dispositivo de la LAN sin sesión, **When** abre cualquier URL de la aplicación, **Then** ve la pantalla de acceso y, tras introducir la contraseña correcta, llega a la URL que pidió.
3. **Given** un dispositivo sin sesión, **When** intenta leer cualquier dato, Media o ejecutar una acción de la API, **Then** es rechazado sin revelar datos.
4. **Given** una contraseña incorrecta, **When** se introduce, **Then** se muestra un error genérico, y los intentos repetidos se frenan para dificultar adivinarla.
5. **Given** una sesión iniciada, **When** el usuario usa la app en el mismo navegador al menos una vez cada 7 días, **Then** no se le pide la contraseña hasta que pasen 30 días desde que inició sesión; tras 7 días sin uso, o al cumplirse los 30 días, debe volver a entrar; puede **cerrar sesión** explícitamente con efecto inmediato.
6. **Given** el usuario olvida la contraseña, **When** sigue la documentación, **Then** puede restablecerla con una acción local en el host (sin email ni servicio externo), y las sesiones anteriores dejan de ser válidas.
7. **Given** el usuario cambia la contraseña, **When** lo hace, **Then** las demás sesiones abiertas dejan de ser válidas.
8. **Given** una página web cualquiera abierta en un dispositivo de la LAN, **When** intenta invocar la API de AutoPublisher (petición cross-site o DNS rebinding), **Then** la petición es rechazada y no produce cambios.
9. **Given** cualquier respuesta, log o pantalla, **When** se inspecciona, **Then** no contiene tokens, contraseñas (ni la de instalación), client secrets ni rutas a ficheros de secretos.
10. **Given** el usuario va a habilitar el acceso LAN, **When** consulta la guía o Settings, **Then** se le indica que el acceso viaja sin cifrar (HTTP), que solo debe habilitarse en una red doméstica privada y de confianza, y que no protege frente a quien controle o intercepte la red.

---

### User Story 6 - Configuración y datos portables (Priority: P2)

El usuario sabe exactamente qué constituye su instalación (código, configuración de la
instalación, secretos y datos), la configura sin tocar ficheros versionados y puede
entender cómo moverla a otra máquina.

**Why this priority**: Evita perder datos al reinstalar o actualizar y habilita la futura
migración a un servidor doméstico.

**Independent Test**: Instalar con un directorio de datos fuera del checkout del código,
arrancar, crear datos, reemplazar el checkout y comprobar que todo sigue; revisar que la
guía de migración separa estado portable y configuración del host (Journey G).

**Acceptance Scenarios**:

1. **Given** un directorio de datos configurado fuera del código, **When** se arranca, **Then** todo el estado portable de la aplicación (BD, Media, copias limpias, configuración local de plataformas, hash de contraseña) se lee y escribe solo ahí.
2. **Given** una instalación existente con los valores por defecto actuales (`backend/data`), **When** se actualiza a 020, **Then** sigue funcionando sin migración manual de datos, y la documentación explica cómo pasar a un directorio de datos dedicado.
3. **Given** la documentación, **When** el usuario la sigue, **Then** distingue configuración versionable (plantillas sin secretos), estado portable de la aplicación, configuración de despliegue del host y secretos del keyring, y sabe que nada de ello salvo las plantillas va a Git.
4. **Given** la documentación de migración, **When** el usuario la lee, **Then** entiende los pasos para mover la instalación a otra máquina Linux: preparar y configurar el nuevo host → elegir su directorio de datos → restaurar el estado portable → configurar bind/LAN/puerto/nombres permitidos para esa máquina → reconectar las cuentas cuyos tokens no están en su keyring, sin depender de rutas del portátil original (Journey G).
5. **Given** un backup de otra máquina, **When** se restaura en un host nuevo, **Then** la ruta de datos, la exposición LAN, el puerto, los nombres permitidos y la configuración del gestor de servicios del host nuevo no cambian por el restore (en particular, la LAN no se habilita sola).

---

### User Story 7 - Backup y restauración básicos (Priority: P2)

El usuario crea un backup de los datos críticos y sabe restaurarlo.

**Why this priority**: Protege contra la pérdida de la instalación con un mecanismo simple.

**Independent Test**: Journey F: crear backup con la app en marcha, inspeccionar que
contiene el estado portable definido como crítico, restaurarlo con el servicio detenido en
un directorio de datos vacío y abrir la app con los mismos Projects/Media/Posts.

**Acceptance Scenarios**:

1. **Given** AutoPublisher en marcha (incluso con el scheduler activo), **When** el usuario crea un backup, **Then** obtiene un artefacto fechado con el estado portable: copia consistente de la BD, Media (originales y copias limpias), configuración local de plataformas y hash de contraseña, sin ninguna sesión activa; el artefacto se escribe fuera de lo respaldado (nunca se incluye a sí mismo ni a backups anteriores).
2. **Given** un backup, **When** se sigue el procedimiento de restauración (servicio detenido) en una instalación vacía, **Then** la app arranca con los mismos datos y la misma contraseña de instalación (por su hash persistido) y sin ninguna sesión activa (todos los navegadores deben iniciar sesión de nuevo); la configuración de despliegue de ese host se mantiene; las cuentas cuyos tokens no estén en el keyring de esa máquina aparecen como "Reconnect needed".
3. **Given** un backup, **When** se inspecciona, **Then** no contiene tokens del keyring del SO; puede contener un manifest informativo de la instalación origen que no se aplica al restaurar; la documentación advierte de que sí contiene datos privados y configuración sensible de plataformas y cómo guardarlo.
4. **Given** un artefacto dañado, incompleto o que no es un backup de AutoPublisher, **When** se intenta restaurar, **Then** la restauración se detiene antes de sustituir ningún dato y explica el motivo.
5. **Given** espacio insuficiente o un error durante el backup, **When** ocurre, **Then** el backup se marca como fallido de forma clara y no deja un artefacto parcial que parezca válido.

---

### User Story 8 - Operación y diagnóstico (Priority: P3)

El usuario puede saber de un vistazo si AutoPublisher está en marcha, si está sano, si el
scheduler está activo y dónde mirar si algo falla.

**Why this priority**: Necesario para confiar en un servicio desatendido, pero apoyado en
capacidades que ya existen en gran parte.

**Independent Test**: Consultar el health público sin sesión, el diagnóstico autenticado
(Settings) y los logs en estado normal, con la automatización en pausa y con el
almacenamiento seguro no disponible.

**Acceptance Scenarios**:

1. **Given** AutoPublisher en marcha, **When** se consulta el health público sin sesión, **Then** solo indica que el servicio responde y, como mucho, un estado agregado `ok` / `degraded`, sin ningún detalle (ni scheduler, ni última comprobación, ni pausa, ni almacenamiento seguro, ni BD más allá del agregado).
2. **Given** el scheduler parado inesperadamente o el almacenamiento seguro no disponible, **When** el usuario con sesión abre Settings (o el diagnóstico autenticado), **Then** ve qué componente falla (BD, scheduler y última comprobación, pausa, almacenamiento seguro) con una explicación entendible; el health público solo muestra `degraded`.
3. **Given** un fallo, **When** el usuario sigue la documentación, **Then** encuentra los logs persistentes (que sobreviven a reinicios) y estos no contienen secretos.

---

### User Story 9 - Actualizar una instalación existente (Priority: P3)

El usuario actualiza AutoPublisher a una versión nueva conservando todos sus datos.

**Why this priority**: Necesario a medio plazo, de bajo riesgo gracias a las migraciones
automáticas existentes.

**Independent Test**: Con datos reales, seguir el procedimiento de actualización y
comprobar que datos, schedules y configuración se conservan.

**Acceptance Scenarios**:

1. **Given** una instalación con datos, **When** se sigue el procedimiento de actualización documentado, **Then** tras reiniciar todos los datos y schedules siguen presentes y el esquema se ha migrado.
2. **Given** una migración que falla, **When** se arranca la nueva versión, **Then** no arranca a medias: falla de forma diagnosticable y la documentación indica cómo volver atrás usando el backup previo.

### Edge Cases

- **Reloj incorrecto al arrancar** (p. ej. Raspberry Pi sin RTC antes de sincronizar la hora): la documentación exige un reloj sincronizado; el riesgo de marcar Missed o publicar a destiempo queda documentado como requisito del host (no se resuelve en 020 más allá de documentarlo y, si es trivial, avisar en diagnóstico).
- **Suspensión del host** (portátil con tapa cerrada / suspensión automática): equivale a downtime; la documentación recomienda desactivar la suspensión en un host dedicado.
- **IP del host cambia** (DHCP): la documentación indica cómo descubrir la dirección actual y recomienda reservar la IP en el router o usar el nombre del host en la red local si está disponible.
- **Puerto ocupado** al arrancar: el arranque falla con un mensaje claro y el mecanismo de servicio no entra en bucle silencioso.
- **Almacenamiento seguro bloqueado o ausente** (p. ej. tras un reboot sin sesión de usuario, o keyring bloqueado): si la app llega a ejecutarse, se marca degradada, las cuentas muestran el problema y las publicaciones automáticas no se inician o fallan de forma visible (nunca silenciosa); los Posts cuya ventana pase así terminan como Missed (D13).
- **Reboot sin login o con login automático**: sin sesión, AutoPublisher no arranca; con login automático arranca, pero el keyring puede seguir bloqueado hasta que el usuario lo desbloquee. En ambos casos no hay garantía de publicación automática, el diagnóstico lo indica y los Posts que pierdan su ventana quedan como Missed. No se recomienda un keyring sin contraseña para evitarlo.
- **Sesión del navegador caducada** en mitad de un Publish o de una subida: el usuario vuelve a la pantalla de acceso sin perder lo ya guardado (los Drafts existentes siguen ahí) y, tras entrar, vuelve a la URL en la que estaba.
- **Acceso por nombres distintos** (IP del host, nombre en la red local, `127.0.0.1`): la sesión puede ser independiente por nombre; volver a introducir la contraseña en ese caso es aceptable.
- **Callbacks OAuth** (YouTube/TikTok) que vuelven al host: MUST seguir funcionando aunque la sesión de navegador no viaje con el callback, protegidos por sus mecanismos propios existentes (state/PKCE, loopback).
- **Subida grande desde móvil por Wi-Fi** (cerca de 2 GiB) y host con poca RAM o `/tmp` en memoria: la subida no debe agotar la memoria del host; los ficheros temporales deben vivir en disco dentro del espacio controlado por la instalación.
- **Disco lleno** durante una importación o un backup: error visible, sin corrupción de BD ni artefactos parciales presentados como válidos.
- **Dos instancias a la vez** sobre el mismo directorio de datos (p. ej. servicio + arranque manual de desarrollo): se impide o se avisa claramente, porque dos schedulers podrían competir.
- **Restore en un host con rutas distintas**: el estado portable funciona en el nuevo directorio de datos (rutas relativas, FR-045); el manifest de origen solo se muestra a título informativo.
- **Restore con el servicio en marcha**: no se permite; el procedimiento exige detenerlo antes.
- **Backup cuyo destino está dentro del directorio de datos**: se rechaza o se excluye inequívocamente para impedir que el backup se incluya a sí mismo o a backups previos.
- **Red no confiable** (Wi-Fi pública, red de invitados compartida): la guía indica no habilitar el acceso LAN; 020 no protege frente a interceptación (D14).
- **Backup restaurado en una versión más nueva** de AutoPublisher: las migraciones automáticas lo actualizan; restaurar en una versión más antigua no está soportado y se documenta.
- **Navegador móvil con la app en segundo plano** durante horas: al volver, la UI recarga datos sin quedarse en un estado inconsistente.
- **Acceso desde un dispositivo de la LAN con el acceso LAN deshabilitado**: no responde; la documentación explica cómo habilitarlo.

## Requirements *(mandatory)*

### Functional Requirements

#### Modo de ejecución de instalación (US1)

- **FR-001**: AutoPublisher MUST poder ejecutarse en un modo de instalación que no use servidor de desarrollo del frontend, recarga automática ni herramientas de edición.
- **FR-002**: En modo instalación, la UI compilada y la API MUST servirse desde un único punto de acceso (una dirección y un puerto); el cliente no necesita conocer ni alcanzar ningún otro puerto.
- **FR-003**: Toda ruta de la UI que no pertenezca a la API MUST devolver la aplicación, de modo que las URL profundas se puedan abrir, recargar y marcar desde cualquier dispositivo.
- **FR-004**: El flujo de desarrollo actual (backend de desarrollo + servidor de desarrollo del frontend en `localhost`) MUST seguir funcionando para desarrollar desde el propio ordenador. El modo desarrollo, que no tiene contraseña, MUST aceptar solo clientes loopback aunque se arranque escuchando en todas las interfaces; las pruebas desde la LAN o el móvil usan el modo instalación.
- **FR-005**: La compilación del frontend MUST poder realizarse en una máquina distinta de la que ejecuta AutoPublisher (el host de ejecución no necesita herramientas de compilación del frontend).

#### Servicio persistente (US2)

- **FR-010**: Debe existir un procedimiento documentado para registrar AutoPublisher como servicio que se ejecuta **dentro de la sesión del usuario** del host (para acceder a su keyring) y arranca automáticamente al iniciarse esa sesión, sin requerir abrir terminales ni VS Code.
- **FR-010a**: La documentación MUST explicar explícitamente la limitación de D13: tras un reboot, la publicación automática no está garantizada hasta que exista una sesión de usuario con el keyring desbloqueado; con login automático AutoPublisher puede arrancar, pero el keyring puede seguir bloqueado (en GNOME no se desbloquea) hasta que el usuario lo desbloquee, y el diagnóstico autenticado lo indica; los Posts que venzan en ese intervalo aparecen como Missed; la guía MUST desaconsejar configurar un keyring sin contraseña solo para conseguir arranque desatendido; un host headless necesitará una feature futura.
- **FR-011**: Si el proceso principal termina inesperadamente, MUST reiniciarse automáticamente; los reinicios repetidos MUST espaciarse y quedar registrados, sin bucles rápidos indefinidos.
- **FR-012**: El scheduler MUST vivir en el mismo proceso supervisado que sirve la API (sin componente aparte que pueda quedar parado sin que se note).
- **FR-013**: Debe existir una forma documentada de detener, arrancar, reiniciar y consultar el estado del servicio.
- **FR-014**: AutoPublisher MUST impedir, con un mensaje claro, que dos procesos usen el mismo directorio de datos o la misma base de datos efectiva (aunque se llegue a ella mediante overrides distintos); la exclusión MUST mantenerse durante todo un restore y sobrevivir a la sustitución del directorio de datos.

#### Reinicio seguro y scheduler (US3)

- **FR-020**: Todos los datos persistentes (Projects, Accounts, Media y sus ficheros, copias limpias, Posts e historial de intentos, schedules, pausa de automatización, presets, configuración de plataformas y de la instalación) MUST sobrevivir a reinicios del servicio, del SO y apagados.
- **FR-021**: Tras arrancar, el scheduler MUST reconocer todos los Posts programados almacenados, sin ninguna acción del usuario, aplicando las reglas existentes (ventana de 10 minutos, pausa, consentimiento, máximo de concurrencia).
- **FR-022**: Los Posts cuya ventana pasó mientras AutoPublisher no estaba en marcha MUST mostrarse como **Missed** con las acciones existentes y NUNCA publicarse automáticamente tarde.
- **FR-023**: Las ejecuciones interrumpidas por la caída del proceso MUST cerrarse al arrancar según las reglas existentes, antes de que el scheduler empiece, y quedar visibles.
- **FR-024**: Al detener el servicio de forma ordenada, el scheduler MUST dejar de iniciar publicaciones nuevas antes de que el proceso termine (comportamiento actual), y la documentación MUST indicar que detener durante una subida puede dejarla como interrumpida.
- **FR-025**: La documentación MUST explicar qué necesita el scheduler para funcionar (proceso en marcha, host despierto, reloj sincronizado, red, almacenamiento seguro disponible) y qué ocurre si falta cada cosa.

#### Acceso LAN y seguridad (US4, US5)

- **FR-030**: En modo instalación, todos los **datos y acciones privados** (toda la API, incluida la Media, desde el host o desde la LAN) MUST requerir una sesión de navegador válida obtenida con la **contraseña única de instalación** (D12). Sin sesión solo se sirven los recursos estrictamente necesarios para iniciar y autenticar: el shell de la UI (`index.html`, recursos estáticos y pantalla de acceso), que no contiene datos privados; el contrato mínimo de sesión/acceso; el health público mínimo (FR-060); y los callbacks OAuth expresamente aprobados, con sus protecciones propias. Un enlace profundo abierto sin sesión recibe el shell, lleva a la pantalla de acceso y, tras entrar, vuelve a la URL pedida.
- **FR-030a**: El primer arranque/configuración MUST obligar a establecer la contraseña de instalación antes de servir la aplicación; sin contraseña configurada, el modo instalación MUST negarse a servir la aplicación con un mensaje claro (FR-043). Establecer la contraseña por primera vez y restablecerla por olvido MUST ser acciones locales del host; MUST NOT existir un endpoint de setup o reset accesible sin sesión desde la red.
- **FR-030b**: La contraseña MUST almacenarse de forma no reversible y nunca mostrarse, registrarse en logs ni devolverse por la API.
- **FR-030c**: La sesión de navegador MUST caducar tras **7 días sin actividad** (la actividad renueva ese plazo) y, en cualquier caso, **30 días** después de iniciarla, sin que la renovación pueda superar ese límite; MUST poder cerrarse explícitamente (**Sign out**, efecto inmediato); todas las sesiones MUST invalidarse al cambiar o restablecer la contraseña; las sesiones caducadas MUST purgarse de forma oportunista y acotada. Las sesiones activas no son estado portable: no viajan en backups y un restore empieza sin sesiones.
- **FR-030d**: Los intentos fallidos repetidos MUST frenarse (limitación de ritmo o equivalente) y el error MUST ser genérico.
- **FR-030e**: El usuario MUST poder cambiar la contraseña desde la app (conociendo la actual) y restablecerla si la olvida mediante una acción local documentada en el host, sin email ni servicio externo.
- **FR-030f**: Las acciones que modifican estado MUST estar protegidas frente a peticiones cross-site (CSRF) en combinación con la sesión; el mecanismo se decide en el plan.
- **FR-030g**: 020 MUST NOT introducir múltiples usuarios, roles, permisos por usuario, signup, recuperación por email ni arquitectura SaaS.
- **FR-030h**: El único modo sin contraseña es el de desarrollo, determinado por cómo se arranca la aplicación (no por un ajuste), y MUST aceptar solo clientes loopback (FR-004). No existe ningún ajuste que desactive la contraseña en modo instalación ni un bypass de desarrollo para la LAN.
- **FR-031**: Por defecto la instalación MUST escuchar solo en el propio host; el acceso LAN MUST habilitarse explícitamente en la configuración de despliegue del host, y un restore nunca lo habilita.
- **FR-032**: La aplicación MUST rechazar peticiones cuyo destino (`Host`) no sea uno de los nombres/direcciones esperados de la instalación y peticiones que modifiquen estado procedentes de un origen distinto del de la propia aplicación (protección frente a DNS rebinding y peticiones cross-site desde otras webs abiertas en la LAN). Esta protección es a nivel aplicación y no sustituye a una red de confianza (D14).
- **FR-033**: Ninguna respuesta de la API, pantalla ni log MUST incluir tokens, contraseñas, client secrets, sesiones de Telegram ni contenido de ficheros de secretos (refuerza la regla existente para el nuevo modo de ejecución y sus logs).
- **FR-034**: La documentación y Settings MUST mostrar cómo acceder desde otros dispositivos: dirección(es) de red del host, puerto, requisito de estar en la misma red, si el acceso LAN está habilitado y la advertencia de FR-037.
- **FR-035**: Las acciones que requieren redirects loopback (conectar/reconectar YouTube y TikTok) MUST, cuando se usan desde un dispositivo que no es el host, explicar que deben hacerse desde el navegador del host en lugar de iniciar un flujo que fallaría. El funcionamiento desde el host MUST seguir intacto en modo instalación (incluida la comprobación de puerto del callback de TikTok).
- **FR-036**: 020 MUST NOT exponer AutoPublisher a Internet ni requerir abrir puertos en el router; la documentación MUST desaconsejarlo explícitamente.
- **FR-037**: La documentación (y Settings, junto a la información de acceso LAN) MUST explicar el threat model de D14: el acceso LAN usa HTTP sin cifrar; protege frente a dispositivos no autenticados, páginas cross-site, DNS rebinding y acceso no autorizado a nivel aplicación; NO protege frente a quien intercepte tráfico, haga MITM o controle la red/punto de acceso; y solo debe habilitarse en una red doméstica privada y de confianza, nunca en redes públicas o no confiables.
- **FR-038**: Ninguna documentación ni texto de la UI MUST presentar el acceso LAN como "seguro" o "cifrado" sin esa salvedad.
- **FR-039**: 020 MUST NOT añadir HTTPS (ni certificados locales); queda como evolución futura junto con el acceso remoto por VPN privada.

#### Configuración y persistencia portable (US6, US7)

- **FR-040**: Debe existir un **directorio de datos**, configurable con un único ajuste, que contenga por defecto todo el **estado portable de la aplicación**: BD, Media (incluidos temporales de importación), copias limpias, configuración local de plataformas, hash de la contraseña de instalación (con parámetros y sal) y demás datos persistentes del producto; las sesiones activas viven en la BD pero no son estado portable. Precedencia: una variable `AUTOPUBLISHER_*` individual existente > `AUTOPUBLISHER_DATA_DIR` > configuración del host > default; los ajustes individuales existentes MUST seguir funcionando y tener prioridad cuando se definan.
- **FR-041**: Sin configuración explícita, el comportamiento por defecto MUST seguir siendo compatible con las instalaciones de desarrollo actuales (`backend/data`).
- **FR-042**: La configuración MUST separarse en: (a) plantillas versionadas sin secretos; (b) **configuración de despliegue del host** (ruta del directorio de datos, bind / LAN habilitada, puerto, nombres/direcciones permitidos, configuración del gestor de servicios), no versionada y específica de cada máquina; (c) **estado portable** dentro del directorio de datos (incluidos los ficheros de configuración de plataforma con client secrets), nunca versionado; (d) tokens y sesiones de cuentas en el keyring del SO, nunca versionados ni respaldados.
- **FR-042a**: La configuración de despliegue del host MUST vivir fuera del estado portable o ser inequívocamente distinguible de él, de modo que un backup/restore no la transporte ni la aplique a otra máquina.
- **FR-043**: Si falta o es inválida una configuración obligatoria para arrancar, AutoPublisher MUST negarse a arrancar con un mensaje que indique qué ajuste falta y cómo corregirlo. Las integraciones de plataforma no configuradas MUST seguir siendo opcionales (se muestran como "Not configured" en Settings, comportamiento actual).
- **FR-044**: El directorio de datos y los ficheros de secretos MUST tener permisos restringidos al usuario que ejecuta el servicio; AutoPublisher MUST crear con esos permisos lo que cree y la documentación MUST indicar los permisos esperados.
- **FR-045**: Ninguna referencia persistida (BD o configuración) MUST contener rutas absolutas dependientes de la máquina para localizar la media; mover el directorio de datos completo MUST bastar para que la media siga localizándose.
- **FR-046**: Los ficheros temporales de subidas grandes MUST poder ubicarse en disco bajo control de la instalación, para no agotar RAM en hosts pequeños.
- **FR-047**: La documentación MUST clasificar explícitamente: estado portable (persistente, se respalda y se migra); configuración de despliegue del host (persistente en esa máquina, se reconfigura en cada host, no se restaura); regenerable (build del frontend, dependencias, entorno virtual, temporales, caché); qué nunca se versiona; qué no se incluye en backups (tokens del keyring).

#### Backup y restauración (US7)

- **FR-050**: El usuario MUST poder crear un backup bajo demanda que contenga el estado portable de la aplicación: una copia **consistente** de la BD (válida aunque la app esté en marcha), toda la Media (originales y copias limpias), la configuración local de plataformas y el hash de contraseña, **sin sesiones activas** (se eliminan de la copia destinada al backup, nunca de la BD en uso), en un único artefacto con fecha.
- **FR-050a**: El destino del backup MUST estar fuera del contenido respaldado o excluirse inequívocamente, de modo que un backup nunca se incluya a sí mismo ni a backups anteriores.
- **FR-050b**: El backup MAY incluir un manifest informativo de la instalación origen (versión, fecha, resumen de contenidos y, si es útil, datos del host origen sin secretos); ese manifest MUST NOT aplicarse automáticamente al restaurar. La configuración de despliegue del host MUST NOT restaurarse en otra máquina.
- **FR-051**: Un backup fallido MUST reportarse claramente y no dejar un artefacto que parezca completo.
- **FR-052**: Los tokens y sesiones guardados en el almacenamiento seguro del SO MUST NOT incluirse en el backup (D7). El servicio MUST seguir usando el keyring del usuario tal como hoy (D13): sin fallback a texto plano y sin un almacén de secretos nuevo en 020.
- **FR-053**: Debe existir un procedimiento documentado de restauración que: se ejecute con el servicio detenido; valide el artefacto (que es un backup de AutoPublisher, completo e íntegro) **antes** de sustituir ningún dato; restaure solo el estado portable en el directorio de datos del host destino; conserve la configuración de despliegue de ese host; y termine verificando el health, iniciando sesión con la contraseña de instalación restaurada y reconectando las cuentas que lo necesiten.
- **FR-053a**: La contraseña de instalación MUST conservarse tras un restore mediante su hash persistido; tras un restore MUST no existir ninguna sesión activa (todos los navegadores inician sesión de nuevo); los tokens del keyring siguen fuera (D7).
- **FR-054**: La documentación MUST advertir que el backup contiene media privada y configuración sensible, y recomendar dónde guardarlo (p. ej. disco externo) y cómo protegerlo.

#### Operación y diagnóstico (US8)

- **FR-060**: Debe existir un **health público mínimo** sin autenticación, para el gestor de servicios y el diagnóstico básico, que revele como máximo: que el servicio responde y un estado agregado `ok` / `degraded`. MUST NOT revelar públicamente la última comprobación del scheduler, si la automatización está en pausa, la disponibilidad del almacenamiento seguro, detalles de la BD más allá del agregado, versiones, rutas ni datos de usuario.
- **FR-061**: Los **detalles diagnósticos** (BD, scheduler vivo, última comprobación, pausa, almacenamiento seguro) MUST requerir una sesión autenticada y exponerse en Settings (reutilizando la sección de automatización existente) y/o mediante un diagnóstico autenticado, con explicaciones entendibles cuando algo está degradado. El estado del almacenamiento seguro MUST obtenerse sin provocar diálogos de desbloqueo y MUST informarse como desconocido cuando no pueda comprobarse de forma no interactiva; nunca se informa como disponible sin haberlo comprobado.
- **FR-062**: Los logs del modo instalación MUST persistir entre reinicios, tener un tamaño acotado (rotación o equivalente) y ser localizables mediante la documentación; MUST incluir arranque, parada, errores de arranque, ciclo de vida de publicaciones automáticas y fallos, sin secretos.
- **FR-063**: No se crea una plataforma de observabilidad (sin métricas, dashboards ni alertas externas).

#### Mobile readiness real (US4, US10)

- **FR-070**: En modo instalación, desde un móvil/tablet en la LAN, MUST funcionar: Home, Library (incl. previews de imagen y vídeo), Media detail, Posts (Needs you / Upcoming / Drafts / History), Calendar, Post detail y sus acciones (Reschedule, Edit schedule, Retry now, Move to drafts, Cancel/Reactivate), Publish (Compose → Review, Schedule, Publish now, Finish later), Text post, dialogs/sheets, Settings (incluida Pause/Resume) y la pantalla de acceso / Sign out.
- **FR-071**: La importación de Media desde el móvil (selector de archivos del dispositivo) MUST funcionar con los límites existentes.
- **FR-072**: La UI MUST NOT depender de funciones disponibles solo en `localhost` o en contextos seguros (p. ej. APIs del navegador restringidas a HTTPS) para los flujos de FR-070; si alguno depende, MUST degradar de forma usable.
- **FR-073**: Los bugs de deployment/móvil real descubiertos durante la verificación MUST corregirse dentro de 020 si son pequeños; los que impliquen rediseño se registran como trabajo futuro.
- **FR-074**: 020 MUST NOT rediseñar Library, Publish, Posts ni Calendar.

#### Actualización y migración de host (US6, US9)

- **FR-080**: Debe existir un procedimiento documentado de actualización: backup recomendado → detener → actualizar código y dependencias → (compilar frontend si aplica) → arrancar → verificar health; las migraciones de esquema se aplican automáticamente al arrancar.
- **FR-081**: Si la migración de esquema falla, AutoPublisher MUST no servir la aplicación y MUST dejar el error en los logs; la documentación MUST describir cómo volver a la versión anterior con el backup.
- **FR-082**: Debe existir documentación de migración a otra máquina Linux, en este orden: (1) preparar e instalar/configurar el nuevo host; (2) elegir su directorio de datos; (3) restaurar el estado portable (FR-053) con el servicio detenido; (4) configurar bind/LAN/puerto/nombres permitidos y el servicio para **esa** máquina; (5) arrancar, verificar health e iniciar sesión; (6) reconectar las cuentas cuyos tokens no existen en su keyring; (7) verificar el scheduler.

#### Documentación de instalación (todas las US)

- **FR-090**: Debe existir una guía de instalación en inglés (repositorio público) que cubra, en orden: preparar la máquina (requisitos, reloj sincronizado, sin suspensión), configurar la instalación (incluida la contraseña de instalación), instalar/crear el servicio en la sesión del usuario (con la limitación de D13: el login automático no desbloquea el keyring y no se recomienda un keyring sin contraseña), arrancar, verificar health, abrir desde el navegador del host, habilitar y abrir desde el móvil en la LAN (con el threat model de FR-037), comprobar el scheduler, detener/reiniciar/actualizar, y crear/restaurar backup (estado portable vs. configuración del host).
- **FR-091**: La guía MUST incluir una sección de compatibilidad con hosts ARM64 (Raspberry Pi / mini PC) que enumere incompatibilidades y riesgos conocidos (almacenamiento seguro headless, reloj sin RTC, RAM en subidas grandes, compilación del frontend en otra máquina) sin prometer soporte verificado.
- **FR-092**: La guía MUST mencionar como evolución futura, no implementada, el acceso remoto mediante VPN privada (p. ej. Tailscale) sin publicar AutoPublisher en Internet.
- **FR-093**: El README MUST actualizarse para reflejar que "AutoPublisher must be running" puede cumplirse mediante el servicio, y para enlazar la guía.

### Key Entities

- **Instalación**: una copia en ejecución de AutoPublisher en un host; tiene código (reemplazable), configuración de despliegue del host, estado portable (en su directorio de datos) y secretos en el keyring del usuario.
- **Estado portable de la aplicación**: todo lo que debe sobrevivir a backup y migración: BD, Media (originales, copias limpias), configuración local de plataformas necesaria, hash de la contraseña de instalación (parámetros y sal incluidos) y demás datos persistentes del producto. No incluye sesiones activas. Vive en el **directorio de datos**; es lo que se respalda y se mueve.
- **Configuración de despliegue del host**: ajustes específicos de una máquina: ruta del directorio de datos, bind / LAN habilitada, puerto, nombres/direcciones permitidos y configuración del gestor de servicios. No versionada (existe una plantilla sin secretos), no forma parte del estado portable y nunca se restaura automáticamente en otro host.
- **Contraseña de instalación**: credencial única de acceso a la instalación, almacenada de forma no reversible dentro del estado portable (por tanto, conservada tras un restore). No identifica a una persona ni tiene roles.
- **Sesión de navegador**: prueba de que un navegador introdujo la contraseña; caduca por inactividad (7 días) y por edad (30 días), puede cerrarse y se invalida al cambiar/restablecer la contraseña. No es estado portable: no viaja en backups.
- **Secretos**: tokens/sesiones de cuentas (almacenamiento seguro del SO, no respaldados) y secretos de aplicación de plataformas (ficheros de configuración de plataforma con permisos restringidos, incluidos en el backup).
- **Backup**: artefacto fechado con el estado portable (BD consistente sin sesiones activas + Media + copias limpias + configuración local de plataformas + hash de contraseña), opcionalmente con un manifest informativo de origen; no contiene tokens del keyring ni configuración de despliegue aplicable; se guarda fuera de lo respaldado.
- **Health público**: respuesta mínima sin autenticación: el servicio responde y, como mucho, `ok` / `degraded`.
- **Diagnóstico**: detalle autenticado (BD, scheduler, última comprobación, pausa, almacenamiento seguro) visible en Settings y/o un diagnóstico autenticado.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Tras reiniciar la máquina host, AutoPublisher está disponible en el navegador en menos de 2 minutos desde que se inicia la sesión del usuario (manual o automática), sin ninguna otra acción manual (Journey A).
- **SC-002**: Tras una terminación forzada del proceso, el health vuelve a OK en menos de 30 segundos sin intervención (Journey D).
- **SC-003**: El 100 % de los Posts programados a futuro antes de un reinicio siguen programados después y se publican dentro de su ventana si el host está en marcha (Journey C); el 0 % de los Posts vencidos durante un apagado se publican automáticamente al volver.
- **SC-004**: Desde un móvil en la misma Wi-Fi, el usuario abre Posts, el Calendar y un Post detail, y reprograma un Post, sin escribir más que la dirección de la instalación y la contraseña de instalación (Journey B).
- **SC-005**: En la verificación a nivel aplicación desde otro dispositivo de la LAN y desde páginas cross-site, 0 peticiones sin sesión válida consiguen leer datos o Media ni modificar nada; con la contraseña, el acceso funciona en el primer intento. (No se mide resistencia frente a interceptación de red, fuera del threat model de D14.)
- **SC-006**: Un backup creado con la app en marcha se restaura, con el servicio detenido, en una instalación vacía y reproduce el 100 % de Projects, Media (ficheros incluidos) y Posts, con la misma contraseña de instalación, cero sesiones activas y sin alterar la configuración de despliegue del host destino (Journey F).
- **SC-007**: Un usuario que no ha desarrollado AutoPublisher puede completar la instalación siguiendo solo la guía en menos de 30 minutos (excluida la configuración de plataformas en sus consolas de desarrollador).
- **SC-008**: Una búsqueda de tokens, client secrets y contraseñas conocidos en logs, respuestas de health/API y en el backup devuelve 0 coincidencias (salvo los ficheros de configuración de plataforma dentro del backup, documentados como sensibles); el health público sin sesión no contiene ningún campo más allá de "responde" y `ok`/`degraded`.
- **SC-009**: Tras una actualización siguiendo el procedimiento, el 100 % de los datos y schedules se conservan.
- **SC-010**: Tras iniciar sesión una vez en un navegador, el usuario no vuelve a introducir la contraseña mientras lo use al menos una vez cada 7 días, hasta un máximo de 30 días desde el login, salvo que cierre sesión o cambie la contraseña.
- **SC-011**: Restaurar un artefacto dañado o ajeno no modifica ningún dato del directorio de datos destino (0 ficheros alterados).

## Fuera de alcance

- Hosting público en Internet, VPS/cloud, dominio, HTTPS público, apertura de puertos en el router.
- SaaS, multiusuario, roles, registro público, billing, tenant isolation, OAuth propio para usuarios finales.
- PostgreSQL, object storage cloud (más allá del proveedor de media temporal existente), colas distribuidas, workers, Kubernetes, autoscaling, gestores de secretos cloud.
- PWA (manifest instalable, Service Worker, standalone), push notifications, offline-first (D8).
- Analytics, métricas, dashboards y alertas externas.
- Rediseño de Library, Publish, Posts o Calendar; Republish; Calendar editable.
- Rediseño del scheduler o cambios de sus reglas (ventana, Missed, concurrencia).
- Backups automáticos programados, incrementales, cifrados gestionados, en la nube o disaster recovery; herramienta sofisticada de migración.
- Auto-updater, zero-downtime, rolling deployments.
- Soporte verificado de ARM64 / Raspberry Pi (solo documentar compatibilidad).
- VPN privada / Tailscale (solo mencionarla como evolución futura).
- HTTPS en la LAN y protección frente a atacantes con control o capacidad de interceptación de la red (MITM, AP malicioso) (D14).
- Restaurar o migrar automáticamente la configuración de despliegue del host.
- Conectar cuentas YouTube/TikTok desde dispositivos distintos del host.
- Almacén de secretos cifrado independiente de la sesión gráfica / funcionamiento headless sin login (feature futura de Raspberry Pi / mini PC, D13).
- Garantía de publicación automática antes de que el usuario inicie sesión tras un reboot.
- Multiusuario, roles, permisos, signup, recuperación de contraseña por email, 2FA.
- Un modo desarrollo accesible desde la LAN o cualquier bypass de la contraseña (C4).

## Cuestiones para `/speckit-plan`

- Tecnología de servicio dentro de la sesión del usuario (D13) y cómo encaja con la comprobación de puerto/loopback del callback de TikTok.
- Contraseña de instalación: algoritmo de hashing, dónde se guarda el hash, formato de sesión (cookies), duración/expiración, protección CSRF, limitación de intentos, procedimiento local de reset y si el modo desarrollo puede omitirla (FR-030–FR-030h).
- Si la UI compilada la sirve el propio backend o un servidor delante (afecta a `Host`/origen, callbacks loopback y logs).
- Mecanismo de bloqueo de instancia única (FR-014).
- Formato del backup y técnica de copia consistente de SQLite en caliente (FR-050).
- Cómo descubre y muestra la app su dirección de red para Settings (FR-034).
- Destino y rotación de logs (FR-062).
- **Constraint**: el destino de un backup debe estar fuera del contenido respaldado o inequívocamente excluido, para impedir recursión (FR-050a).
- **Constraint**: el restore se realiza con el servicio detenido y debe validar el artefacto antes de sustituir datos (FR-053, SC-011).
- **Constraint**: verificar contra el código y los tests actuales que, si el keyring no está disponible durante la ventana automática, el Post termina en el comportamiento Missed prometido (US3 escenarios 2–3), sin rediseñar el scheduler; si hay una divergencia, corregirla de forma mínima.
- **Constraint**: la implementación de sesión debe permitir invalidar todas las sesiones al cambiar o restablecer la contraseña (FR-030c); las sesiones activas no forman parte del estado portable (H2).
- **Constraint**: el setup inicial de la contraseña y el reset por olvido son acciones locales seguras del host, no un endpoint de setup abierto en la LAN (FR-030a).
- Dónde vive la configuración de despliegue del host y cómo se distingue del estado portable (FR-042a); contenido del manifest informativo (FR-050b).
- Forma del health público (`ok`/`degraded`) y del diagnóstico autenticado (FR-060, FR-061).

## Assumptions

- El host inicial es el ordenador Linux actual (x86-64) del usuario, con acceso administrativo para registrar un servicio.
- Los dispositivos cliente están en la misma red local doméstica, privada y de confianza, que el host y usan navegadores modernos (Chrome/Safari/Firefox móviles actuales).
- El usuario puede compilar el frontend en el host o en otra máquina; el host de ejecución no necesita herramientas de desarrollo más allá de lo necesario para ejecutar el backend.
- El reloj del host está sincronizado por red (requisito documentado, no implementado por AutoPublisher).
- El host no se suspende mientras deba publicar automáticamente (requisito documentado).
- Los ficheros de configuración de plataforma con client secrets (`*-app.json`, `google-oauth-client.json`, `media-delivery.json`) siguen siendo ficheros locales con permisos restringidos, como hoy; no se migran al almacenamiento seguro en 020.
- El proveedor de media temporal (S3-compatible) existente para Instagram/Threads no cambia y sigue funcionando desde cualquier host con salida a Internet.
- Las reglas de publicación, scheduler, consentimiento TikTok y estados de Posts de las features 006–019 se mantienen sin cambios.
- La contraseña de instalación es única por instalación (single-user); no hay gestión de usuarios.
- El usuario del host inicia sesión tras cada reboot y, si el keyring queda bloqueado (p. ej. con login automático), lo desbloquea para que las publicaciones automáticas puedan ejecutarse (D13).
