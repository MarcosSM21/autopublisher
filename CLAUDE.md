# CLAUDE.md

## Idioma de trabajo

- Comunícate con el usuario en español.
- Los artefactos internos de Spec Kit pueden redactarse en español.
- El código fuente, nombres de variables, funciones, clases, commits, README y documentación pública del repositorio deben escribirse en inglés.

## Flujo de desarrollo

- Sigue GitHub Spec Kit para todas las features relevantes.
- Trata la especificación activa como fuente de verdad del alcance.
- No amplíes el alcance sin aprobación explícita.
- Trabaja principalmente en una feature importante cada vez.
- Prefiere cambios pequeños y revisables frente a grandes lotes.

## Disciplina de implementación

- Respeta la arquitectura y la Constitution del proyecto salvo que una especificación aprobada indique lo contrario.
- Reutiliza patrones existentes antes de introducir nuevas abstracciones.
- Prefiere siempre la solución correcta más sencilla.
- Añade o actualiza tests cuando cambie el comportamiento, siempre que sea razonablemente posible.
- Los bug fixes deberían incluir tests de regresión cuando corresponda.
- Actualiza la documentación relevante cuando cambien la arquitectura, configuración o comportamiento visible.

## Verificación

Antes de declarar una tarea terminada:

- ejecuta los tests relevantes;
- ejecuta lint y formatting checks;
- ejecuta type checking cuando corresponda;
- verifica el build del frontend si ha sido afectado;
- informa claramente de cualquier comprobación que falle.

No declares una feature terminada si existen checks obligatorios fallando.

## Git

- Nunca versiones secretos, tokens, credenciales, multimedia privada, bases de datos locales, logs sensibles ni archivos `.env` reales.
- Mantén commits pequeños y significativos.
- Escribe los mensajes de commit en inglés.
- No realices commits salvo que el usuario lo pida explícitamente o el workflow activo lo requiera.
- Antes de realizar operaciones Git destructivas, explica brevemente qué va a ocurrir.

## Comunicación

Al finalizar una tarea, informa de forma breve sobre:

1. qué se ha cambiado;
2. qué archivos relevantes se han modificado;
3. qué tests o checks se han ejecutado;
4. qué limitaciones o decisiones pendientes existen.

Evita explicaciones innecesariamente largas.