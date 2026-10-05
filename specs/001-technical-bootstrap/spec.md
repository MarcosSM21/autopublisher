# Feature Specification: Bootstrap técnico del proyecto

**Feature Branch**: `001-technical-bootstrap`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Crear la feature inicial de bootstrap técnico del proyecto AutoPublisher: base mínima de frontend y backend, herramientas básicas de calidad, forma sencilla y documentada de ejecutar y verificar el proyecto, `.gitignore` seguro y README inicial. Sin ninguna funcionalidad de producto."

## Contexto

Esta feature no aporta funcionalidad al usuario final de AutoPublisher. Su "usuario" es el
desarrollador/mantenedor del proyecto (y cualquier persona que clone el repositorio público),
que necesita una fundación técnica mínima, verificable y segura sobre la que construir las
futuras features. El stack tecnológico no se decide aquí: viene impuesto por la sección
"Arquitectura tecnológica base" de la Constitution.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Arrancar la aplicación localmente (Priority: P1)

Como desarrollador que acaba de clonar el repositorio, quiero instalar las dependencias y
arrancar el backend y el frontend siguiendo unas instrucciones breves, para comprobar que
ambas partes de la aplicación funcionan en mi máquina.

**Why this priority**: sin una base que arranque no se puede desarrollar ninguna otra feature.
Es el mínimo indispensable.

**Independent Test**: siguiendo únicamente el README en un clon limpio, arrancar ambas partes,
consultar el health check del backend y abrir la pantalla mínima del frontend en el navegador.

**Acceptance Scenarios**:

1. **Given** un clon limpio del repositorio con los prerrequisitos documentados instalados,
   **When** el desarrollador ejecuta los comandos documentados de instalación y arranque del
   backend, **Then** el backend queda escuchando en local y su health check responde
   indicando que el servicio está operativo.
2. **Given** un clon limpio del repositorio, **When** el desarrollador ejecuta los comandos
   documentados de instalación y arranque del frontend y abre la URL indicada, **Then** ve una
   pantalla mínima que identifica la aplicación como AutoPublisher.
3. **Given** el backend en ejecución, **When** se consulta el health check, **Then** la
   respuesta es exitosa, tiene un formato estructurado estable y no contiene información
   sensible ni detalles internos del entorno.

---

### User Story 2 - Verificar la calidad del proyecto (Priority: P2)

Como desarrollador, quiero ejecutar tests, lint, comprobación de formato y type checking de
frontend y backend mediante pocos comandos documentados, para poder validar cualquier cambio
antes de considerarlo terminado, como exige la Constitution.

**Why this priority**: la Constitution exige que todas las comprobaciones pasen antes de cerrar
una feature; sin estas herramientas, ninguna feature futura podría cerrarse correctamente.

**Independent Test**: en un clon limpio con dependencias instaladas, ejecutar cada comando de
verificación documentado y comprobar que todos terminan con éxito; introducir deliberadamente
un error (de formato, de tipos o un test roto) y comprobar que el comando correspondiente falla.

**Acceptance Scenarios**:

1. **Given** el proyecto recién configurado, **When** se ejecutan los tests del backend,
   **Then** existe al menos un test que verifica que el health check responde correctamente,
   y pasa.
2. **Given** el proyecto recién configurado, **When** se ejecutan los tests del frontend,
   **Then** existe al menos un test que verifica que la pantalla mínima se renderiza
   correctamente, y pasa.
3. **Given** el proyecto recién configurado, **When** se ejecutan lint, comprobación de
   formato y type checking de ambas partes, **Then** todos terminan sin errores.
4. **Given** un cambio que rompe el formato, los tipos o un test, **When** se ejecuta la
   comprobación correspondiente, **Then** esta falla con un código de salida distinto de cero
   y un mensaje que identifica el problema.
5. **Given** el proyecto recién configurado, **When** se genera el build de producción del
   frontend, **Then** finaliza sin errores.

---

### User Story 3 - Repositorio público seguro y comprensible (Priority: P3)

Como mantenedor de un repositorio público, quiero que el repositorio ignore por defecto
secretos, datos locales y artefactos generados, y que tenga un README breve en inglés, para
que nadie versione accidentalmente información sensible y cualquier visitante entienda qué es
el proyecto y cómo ejecutarlo.

**Why this priority**: protege frente a filtraciones (principio IV de la Constitution) y hace
el proyecto comprensible, pero no bloquea el desarrollo local inmediato.

**Independent Test**: crear en el repositorio archivos de ejemplo de cada categoría sensible
(p. ej. `.env`, una base de datos local, un vídeo dentro de un directorio de datos del
usuario, un log) y comprobar con el estado de Git que
ninguno aparece como archivo a versionar; leer el README y verificar que cubre los apartados
requeridos.

**Acceptance Scenarios**:

1. **Given** archivos `.env`, bases de datos locales, multimedia en los directorios de
   datos/runtime del usuario, logs, caches, dependencias
   instaladas, builds, temporales o archivos de credenciales dentro del repositorio, **When**
   se consulta el estado de Git, **Then** ninguno aparece como candidato a versionar.
2. **Given** una plantilla de configuración sin secretos (p. ej. `.env.example`), si existe,
   **When** se consulta el estado de Git, **Then** sí puede versionarse.
3. **Given** un visitante del repositorio, **When** lee el README, **Then** encuentra en
   inglés: qué es AutoPublisher, el stack tecnológico, el estado inicial del proyecto y cómo
   instalar, arrancar y verificar frontend y backend localmente.

---

### Edge Cases

- **Puerto ocupado**: si el puerto por defecto del backend o del frontend ya está en uso, el
  arranque falla con un mensaje claro (comportamiento por defecto de las herramientas) y el
  README indica cómo usar otro puerto.
- **Prerrequisitos ausentes o con versión incorrecta**: el README documenta las versiones
  mínimas de los entornos de ejecución necesarios; con versiones inferiores no se garantiza
  el funcionamiento.
- **Ruta inexistente en el backend**: cualquier ruta distinta del health check responde con
  un error estándar de "no encontrado", sin exponer detalles internos.
- **Frontend sin backend**: la pantalla mínima del frontend se muestra aunque el backend no
  esté en ejecución (no hay dependencia entre ambos en esta fase).
- **Archivos sensibles ya versionados**: el repositorio actual no contiene ninguno; la
  feature no necesita limpiar historial.

## Requirements *(mandatory)*

### Functional Requirements

**Estructura**

- **FR-001**: El repositorio DEBE separar claramente el frontend y el backend en dos
  directorios de primer nivel independientes, cada uno con sus propias dependencias y
  configuración.
- **FR-002**: La estructura NO DEBE incluir carpetas, módulos ni abstracciones vacías o sin
  responsabilidad real en esta fase (p. ej. carpetas para modelos, persistencia, scheduler o
  publishers).

**Backend**

- **FR-003**: El backend DEBE poder arrancarse localmente con un comando documentado.
- **FR-004**: El backend DEBE exponer un único endpoint de health check que responda con éxito
  y un cuerpo estructurado mínimo indicando que el servicio está operativo.
- **FR-005**: La respuesta del health check NO DEBE incluir secretos, rutas del sistema,
  variables de entorno ni otros detalles internos.

**Frontend**

- **FR-006**: El frontend DEBE poder arrancarse localmente en modo desarrollo con un comando
  documentado.
- **FR-007**: El frontend DEBE mostrar una única pantalla mínima que identifique la
  aplicación (nombre "AutoPublisher") y permita verificar visualmente que funciona.
- **FR-008**: El frontend DEBE poder generar un build de producción con un comando
  documentado.

**Calidad**

- **FR-009**: DEBE existir al menos un test automatizado del backend que verifique la
  respuesta del health check (código de éxito y contenido esperado).
- **FR-010**: DEBE existir al menos un test automatizado del frontend que verifique que la
  pantalla mínima se renderiza con el contenido esperado.
- **FR-011**: Frontend y backend DEBEN tener configuradas herramientas de lint, comprobación
  de formato y type checking, ejecutables mediante comandos documentados.
- **FR-012**: Cada comando de verificación DEBE terminar con código de salida distinto de cero
  cuando detecte un problema, de modo que pueda usarse para bloquear cambios.
- **FR-013**: El estado inicial del proyecto DEBE superar todas las comprobaciones (tests,
  lint, formato, type checking y build del frontend).

**Desarrollo local**

- **FR-014**: DEBE existir una forma documentada, con pocos comandos por parte, de: instalar
  dependencias, arrancar frontend, arrancar backend, ejecutar tests, ejecutar lint, comprobar
  formato y ejecutar type checking.

**Seguridad y repositorio**

- **FR-015**: El repositorio DEBE incluir reglas de exclusión de Git que impidan versionar:
  archivos `.env` reales (excepto plantillas como `.env.example`), bases de datos locales,
  multimedia y datos privados del usuario ubicados en los directorios de datos/runtime
  destinados a ello, logs, caches, dependencias instaladas, builds, archivos temporales y
  archivos de secretos o credenciales. Las reglas NO DEBEN ignorar globalmente extensiones
  de imagen o vídeo, para permitir versionar assets públicos (frontend, logos,
  documentación).
- **FR-016**: Solo DEBE crearse una plantilla de variables de entorno si alguna variable es
  realmente necesaria en esta fase; si se crea, NO DEBE contener valores sensibles.
- **FR-017**: Ningún archivo añadido por esta feature DEBE contener secretos, tokens ni
  credenciales.

**Documentación**

- **FR-018**: DEBE existir un README público en inglés, breve, que explique qué es
  AutoPublisher, su stack tecnológico, el estado inicial del proyecto, los prerrequisitos y
  cómo instalar, arrancar y verificar frontend y backend localmente.

**Límites de alcance**

- **FR-019**: Esta feature NO DEBE introducir ninguna funcionalidad de producto: proyectos,
  cuentas, contenido, publicaciones, base de datos, scheduler, calendario, OAuth, APIs
  sociales, almacenamiento multimedia, navegación real, dashboard ni interfaz real del
  producto.
- **FR-020**: El frontend NO DEBE comunicarse con el backend en esta fase.

**Integración continua**

- **FR-021**: El repositorio DEBE incluir un workflow mínimo de GitHub Actions que se ejecute
  ante pushes y pull requests y verifique automáticamente, cuando corresponda: tests, lint,
  comprobación de formato y type checking del backend; tests, lint, comprobación de formato y
  type checking del frontend; y build del frontend. El workflow DEBE mantenerse sencillo,
  reutilizar en la medida de lo posible los mismos comandos documentados para desarrollo
  local y fallar si alguna de estas comprobaciones falla.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un desarrollador con los prerrequisitos instalados puede, siguiendo solo el
  README, tener backend y frontend en ejecución en menos de 10 minutos desde un clon limpio.
- **SC-002**: El 100 % de las comprobaciones documentadas (tests, lint, formato, type checking
  y build del frontend) pasan en el estado inicial del proyecto.
- **SC-003**: Cada parte (frontend y backend) se puede verificar por completo con como máximo
  un comando por tipo de comprobación, y todos ellos están listados en el README.
- **SC-004**: El health check responde con éxito en el 100 % de las consultas mientras el
  backend está en ejecución, y en menos de 1 segundo en local.
- **SC-005**: 0 archivos de las categorías sensibles enumeradas en FR-015 aparecen como
  candidatos a versionar al crearlos dentro del repositorio.
- **SC-006**: 0 funcionalidades de producto (FR-019) presentes en el código entregado,
  verificable por revisión.
- **SC-007**: El README se puede leer completo en menos de 3 minutos.
- **SC-008**: El workflow de GitHub Actions se ejecuta correctamente ante pushes y pull
  requests, y todas sus comprobaciones pasan en el estado inicial del proyecto.

## Assumptions

- **Stack impuesto por la Constitution**: frontend con React + TypeScript + Vite y backend con
  Python + FastAPI. La elección concreta de herramientas de testing, lint, formato, type
  checking y gestión de dependencias se decide en `/speckit-plan`, priorizando las opciones
  estándar y más sencillas de cada ecosistema.
- **Usuario de la feature**: el desarrollador/mantenedor del proyecto en su máquina local; no
  hay usuarios finales, autenticación ni despliegue en esta fase.
- **Entorno**: desarrollo local en Linux/macOS con versiones recientes y soportadas de los
  entornos de ejecución de Python y Node.js; las versiones mínimas concretas se fijan en el
  plan y se documentan en el README.
- **Sin orquestación conjunta obligatoria**: frontend y backend se arrancan por separado; un
  único comando que arranque ambos no es requisito de esta fase.
- **Variables de entorno**: se asume que en esta fase no hay variables necesarias, por lo que
  probablemente no se cree `.env.example`; si el plan identifica alguna, se creará sin
  valores sensibles.
- **Licencia y guía de contribución**: fuera de alcance de esta feature.
- **Comunicación frontend–backend** (REST, CORS, proxy de desarrollo): se aplaza a la primera
  feature que la necesite.
