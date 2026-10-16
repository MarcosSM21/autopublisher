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

### Durante la implementación

- Ejecuta solo los tests dirigidos del bloque modificado.
- No ejecutes suites completas por rutina.
- No repitas regresiones que ya pasaron si el código correspondiente no ha vuelto a cambiar.
- Prefiere tests parametrizados o representativos frente a matrices redundantes.
- Si cambia código compartido o core, ejecuta únicamente las regresiones adicionales necesarias para cubrir riesgos concretos y directamente relacionados.
- No uses un cambio en core como motivo automático para ejecutar una regresión amplia: la cobertura global corresponde a la CI del PR.
- No pruebes internals de librerías externas; prueba nuestro contrato y comportamiento.

### Antes de declarar una tarea terminada

- Ejecuta los tests dirigidos necesarios para demostrar el comportamiento implementado en esa tarea.
- Si esos tests ya pasaron y el código relevante no ha cambiado después, no los repitas.
- No ejecutes lint, typecheck, build o regresiones globales por cada tarea salvo que exista una razón concreta.

### Antes de cerrar una feature y abrir el PR

Ejecuta localmente una sola vez, cuando corresponda:

- los tests dirigidos que queden pendientes;
- lint y formatting checks;
- type checking;
- build del frontend si se ha visto afectado;
- `git diff --check`;
- revisión de seguridad del diff cuando aplique.

Si después solo cambian documentación, specs o tasks, no repitas checks de código.

No ejecutes localmente:

- el pytest completo del backend;
- el test completo del frontend;

si la CI del PR va a ejecutar exactamente esas suites.

La suite completa se ejecuta en la CI del PR.

No declares una feature terminada si existen checks obligatorios fallando.

### Si la CI falla

1. Identifica el fallo exacto.
2. Corrígelo.
3. Ejecuta localmente el test que falló o el test dirigido que reproduce el problema.
4. Ejecuta únicamente los checks estáticos directamente relevantes para la corrección (`mypy`, lint, format, typecheck, etc.).
5. Ejecuta tests adicionales solo si la corrección afecta directamente otro comportamiento y existe una razón concreta.
6. Haz push únicamente cuando esas comprobaciones dirigidas estén en verde.
7. Deja que la CI vuelva a ejecutar la suite completa sobre el nuevo estado del PR.

No ejecutes una suite completa local solo porque la CI haya encontrado un fallo aislado.

Después de modificar un test o código para corregir la CI, no hagas push sin comprobar primero la corrección de forma dirigida.

Una corrección de pytest puede afectar también a un check estático; ejecuta esos checks cuando sean relevantes, pero no lances todos los checks del proyecto automáticamente ante cada corrección.

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