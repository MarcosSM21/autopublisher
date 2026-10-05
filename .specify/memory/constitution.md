<!--
Sync Impact Report
- Version change: (template sin versionar) → 1.0.0
- Principios definidos (adopción inicial):
  - I. Simplicidad y control de alcance
  - II. Spec-Driven Development
  - III. Arquitectura modular
  - IV. Seguridad (repositorio público)
  - V. Calidad y verificabilidad
  - VI. Git y trazabilidad
- Secciones añadidas:
  - Arquitectura tecnológica base
  - Idioma y convenciones
  - Governance
- Secciones eliminadas: ninguna
- Plantillas: no se modifican; leen la constitución en tiempo de ejecución.
- TODOs diferidos: ninguno
-->

# AutoPublisher Constitution

AutoPublisher es una aplicación web local y de un único usuario para organizar, programar y
publicar imágenes y vídeos en múltiples cuentas y redes sociales. Se desarrolla con GitHub
Spec Kit + Claude Code en un repositorio público de GitHub.

## Core Principles

### I. Simplicidad y control de alcance

- Se DEBE elegir la solución más sencilla que cumpla correctamente los requisitos.
- NO se DEBEN introducir abstracciones prematuras, infraestructura innecesaria ni
  funcionalidades especulativas.
- El alcance de una feature NO DEBE ampliarse silenciosamente durante su implementación.
- Las ideas fuera del alcance actual DEBEN registrarse y aplazarse para futuras features.

**Razón**: un proyecto personal y local solo es sostenible si la complejidad crece únicamente
cuando un requisito real lo exige.

### II. Spec-Driven Development

- Toda feature relevante DEBE comenzar con una especificación de Spec Kit.
- La especificación aprobada define el comportamiento y el alcance esperados; cualquier
  desviación DEBE reflejarse primero en la especificación.
- Se DEBE trabajar principalmente en una feature importante cada vez.
- Una feature solo se considera terminada cuando cumple todos sus criterios de aceptación.

**Razón**: la especificación es la fuente de verdad compartida entre el usuario y Claude Code.

### III. Arquitectura modular

- Se DEBEN mantener responsabilidades claras y separadas entre: frontend, backend,
  persistencia, scheduler/queue, cuentas y autenticación, e integraciones externas.
- Cada plataforma social DEBE implementarse mediante un publisher/adaptador independiente.
- La lógica específica de una plataforma NO DEBE filtrarse al núcleo común de la aplicación;
  el núcleo solo interactúa con los adaptadores a través de una interfaz común.

**Razón**: las APIs de las redes sociales cambian con frecuencia; aislarlas permite añadir,
modificar o retirar plataformas sin afectar al resto del sistema.

### IV. Seguridad (repositorio público)

- NUNCA se DEBEN versionar: contraseñas, tokens OAuth, API secrets, archivos `.env` reales,
  credenciales, bases de datos locales, multimedia privada, datos privados del usuario ni
  logs con información sensible.
- Solo se DEBEN versionar plantillas de configuración sin secretos (p. ej. `.env.example`).
- Los logs y mensajes de error NO DEBEN exponer secretos ni tokens.
- Se DEBEN preferir las APIs y los mecanismos OAuth oficiales frente a automatizaciones
  frágiles (scraping, automatización de navegador) siempre que sea posible.

**Razón**: el repositorio es público y la aplicación gestiona credenciales de cuentas reales.

### V. Calidad y verificabilidad

- Los cambios de comportamiento DEBEN incluir tests cuando sea razonablemente posible.
- La corrección de un bug DEBERÍA incluir un test de regresión.
- Tests, lint, formatting, type checking y builds DEBEN ejecutarse mediante comandos simples
  y documentados.
- Todas las comprobaciones del proyecto DEBEN pasar antes de considerar terminada una feature.
- Los errores NO DEBEN provocar pérdida silenciosa de programaciones, publicaciones ni
  historial: todo fallo DEBE quedar registrado y ser visible para el usuario.

**Razón**: una publicación perdida o duplicada sin aviso es el fallo más grave de la aplicación.

### VI. Git y trazabilidad

- Git DEBE utilizarse durante todo el desarrollo.
- Los commits DEBEN ser pequeños, claros, significativos y escritos en inglés.
- La documentación DEBE actualizarse cuando cambien de forma relevante la arquitectura,
  la configuración o el comportamiento.
- El historial público en GitHub DEBE mantenerse comprensible.

**Razón**: el historial público es la documentación de cómo y por qué evolucionó el proyecto.

## Arquitectura tecnológica base

Mientras una futura especificación no justifique explícitamente un cambio, se DEBE usar:

- **Frontend**: React + TypeScript + Vite.
- **Backend**: Python + FastAPI.
- **Persistencia**: SQLite local.
- **Multimedia**: sistema de archivos local.
- **Comunicación**: API REST entre frontend y backend.
- **Programación**: scheduler local dirigido por la base de datos.
- **Integraciones**: publisher adapters independientes por plataforma.
- **Secretos**: almacenamiento seguro del sistema operativo para tokens cuando corresponda.

AutoPublisher es una aplicación local y de un único usuario. NO se DEBEN introducir SaaS,
múltiples usuarios, pagos, infraestructura cloud, workers distribuidos, analytics ni
funcionalidades de IA salvo que una futura especificación lo requiera explícitamente.

## Idioma y convenciones

- Esta constitución y los artefactos de trabajo con el usuario pueden redactarse en español.
- El código fuente, los identificadores técnicos, los mensajes de commit y la documentación
  pública orientada al repositorio (README, docs) DEBEN escribirse en inglés.

## Governance

- Esta constitución prevalece sobre cualquier otra práctica del proyecto. Los planes
  (`/speckit-plan`) DEBEN verificar su cumplimiento y justificar explícitamente cualquier
  complejidad o desviación.
- Las enmiendas DEBEN realizarse mediante `/speckit-constitution`, documentarse en el Sync
  Impact Report y registrarse en un commit propio.
- Versionado semántico:
  - **MAJOR**: eliminación o redefinición incompatible de principios.
  - **MINOR**: nuevo principio o sección, o ampliación material de la guía.
  - **PATCH**: aclaraciones y correcciones de redacción sin cambio semántico.
- La constitución DEBE mantenerse breve y limitada a principios permanentes; los detalles
  de cada feature pertenecen a su especificación.

**Version**: 1.0.0 | **Ratified**: 2026-10-05 | **Last Amended**: 2026-10-05
