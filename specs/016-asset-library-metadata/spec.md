# Feature Specification: Asset Library, uso de contenidos y metadata

**Feature Branch**: `016-asset-library-metadata`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "Feature 016 — Asset Library, Usage & Metadata. Evolucionar la Content Library hacia una Asset Library útil y sencilla sin crear una entidad `Asset` (internamente se mantiene `Content`). Tres capacidades: (1) visualizar el uso de cada Content derivado de Publication/Account/PublicationAttempt sin persistir contadores; (2) búsqueda, filtros mínimos y progressive disclosure; (3) inspeccionar metadata privada o de generación y eliminarla mediante una copia sanitizada (`Remove metadata`), con prioridad absoluta en impedir que se recuperen workflows de ComfyUI. Original inmutable; la copia limpia se usa automáticamente en futuras publicaciones mediante un único resolvedor de archivo efectivo, sin fallback al original. Imágenes con sanitizador estructural por lista blanca (PNG/JPEG/WEBP, sin recomprimir); vídeo con ffmpeg en stream copy (MP4/MOV/WEBM). Persistencia mínima en `Content` (`metadata_status`, campos de copia). Dedupe ampliado al checksum sanitizado. Fuera de alcance: borrar Content, thumbnails en backend, variantes generales, resize/transcoding, presets, Multi-platform Distribution, Republish, renombrar `Content`, rediseño global."

## Contexto

AutoPublisher ya tiene una biblioteca de contenidos por proyecto (Feature 003): cada `Content`
es una imagen o un vídeo importado, con su archivo original almacenado de forma inmutable,
nombre original, checksum SHA-256, tamaño, dimensiones, duración, título, descripción y
hashtags. Las publicaciones (`Publication`) enlazan un `Content` con una `Account` de una
plataforma y pasan por estados (`UNSCHEDULED`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`,
`AWAITING_USER_ACTION`, `FAILED`, `CANCELLED`); cada ejecución deja un `PublicationAttempt`
que puede terminar con resultado incierto. Existen publishers para YouTube, Instagram,
Threads, TikTok (Direct Post e Inbox) y Telegram, y todos leen hoy directamente el archivo,
el checksum y el tamaño del `Content`.

Hoy la biblioteca no responde a preguntas básicas del día a día: ¿he usado ya este archivo?,
¿dónde?, ¿está programado?, ¿está esperando en TikTok? Además, muchos archivos generados con
herramientas de IA —en especial ComfyUI— llevan embebido el workflow completo (prompt,
seeds, modelos, LoRAs, rutas locales…), y cualquier publicación del original lo filtra.

Esta feature:

- presenta la biblioteca como **Asset Library** (solo el nombre en la UI; el modelo sigue
  siendo `Content`);
- deriva el **uso** de cada contenido a partir de las publicaciones existentes, sin
  duplicar datos;
- añade **búsqueda, filtros mínimos y un detalle** con progressive disclosure;
- añade **inspección de metadata** bajo demanda y la acción **`Remove metadata`**, que
  produce una copia sanitizada que pasa a ser, automáticamente y para siempre, el archivo
  que se publica.

Principios rectores:

- **No hay entidad nueva**: ni `Asset`, ni variantes, ni un segundo `Content` para la copia.
- **El uso se deriva, no se persiste**: ningún contador ni flag `used` en `Content`.
- **Progressive disclosure**: la tarjeta solo enseña lo útil para navegar; lo técnico vive
  en el detalle.
- **El original es sagrado**: nunca se modifica, reemplaza ni borra.
- **Nunca publicar metadata que el usuario pidió eliminar**: si la copia limpia no está
  disponible, la publicación falla; jamás vuelve silenciosamente al original.
- **Un único punto de decisión**: qué archivo se publica lo decide un único resolvedor
  común; ninguna plataforma decide por su cuenta.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver de un vistazo qué assets he usado y dónde (Priority: P1)

El usuario abre la biblioteca de un proyecto, ahora titulada **Asset Library**. Cada tarjeta
muestra la preview, el título (o el nombre de archivo original si no hay título), si es
imagen o vídeo y un estado compacto: `Unused` o las plataformas donde se ha utilizado. Si el
asset tiene publicaciones programadas aparece un pequeño indicador `Scheduled`; si hay una
publicación esperando a que el usuario la complete en la app de TikTok aparece `Ready in
TikTok`. Al abrir un asset ve su historial de uso completo.

**Why this priority**: es la pregunta más frecuente del usuario ("¿ya lo he publicado?") y no
depende de nada más de la feature. Por sí sola ya convierte la biblioteca en una herramienta
de trabajo.

**Independent Test**: con un proyecto que tenga contenidos sin publicaciones, publicados en
varias plataformas, programados, fallidos, cancelados y en `AWAITING_USER_ACTION`, abrir la
Asset Library y comprobar que cada tarjeta muestra el estado correcto y que el detalle
muestra el historial.

**Acceptance Scenarios**:

1. **Given** un contenido sin ninguna publicación, **When** el usuario abre la Asset
   Library, **Then** su tarjeta muestra `Unused` y ningún indicador adicional.
2. **Given** un contenido con una publicación `PUBLISHED` en YouTube y otra en Telegram,
   **When** el usuario abre la Asset Library, **Then** la tarjeta muestra que se usó en
   YouTube y Telegram y no muestra `Unused`.
3. **Given** un contenido cuya única publicación está `AWAITING_USER_ACTION` en TikTok,
   **When** el usuario abre la Asset Library, **Then** la tarjeta cuenta como usada, muestra
   TikTok entre las plataformas y el indicador `Ready in TikTok`, y en ningún lugar se
   presenta como "publicado".
4. **Given** un contenido con una única publicación `SCHEDULED`, **When** el usuario abre la
   Asset Library, **Then** la tarjeta muestra `Unused` y el indicador `Scheduled`.
5. **Given** un contenido cuyas publicaciones están todas `FAILED` o `CANCELLED`, **When**
   el usuario abre la Asset Library, **Then** la tarjeta muestra `Unused`.
6. **Given** un contenido con un intento cuyo resultado remoto es incierto y sin publicación
   confirmada, **When** el usuario abre la tarjeta y el detalle, **Then** la tarjeta no lo
   cuenta como usado y el detalle muestra ese intento marcado como resultado incierto.
7. **Given** un contenido usado, **When** el usuario abre su detalle, **Then** ve el
   historial de publicaciones con plataforma, cuenta, estado y fechas, el número de
   publicaciones, el número de publicaciones confirmadas, la última publicación confirmada
   y las publicaciones actualmente programadas.
8. **Given** cualquier tarjeta, **When** se muestra en la biblioteca, **Then** no aparecen
   checksum, MIME, ruta, EXIF, tamaño detallado, dimensiones ni duración.

---

### User Story 2 - Buscar y filtrar la biblioteca (Priority: P2)

El usuario escribe parte de un título o de un nombre de archivo para encontrar un asset, y
filtra por `All`, `Images`, `Videos`, `Used` o `Unused`.

**Why this priority**: con muchos assets, encontrar uno concreto o "lo que aún no he usado"
es la segunda necesidad más frecuente. Depende de la semántica de uso de la US1 solo para
los filtros `Used`/`Unused`.

**Independent Test**: con una biblioteca de varios assets de ambos tipos y estados, aplicar
cada filtro y varias búsquedas y comprobar los resultados.

**Acceptance Scenarios**:

1. **Given** assets con títulos y nombres de archivo distintos, **When** el usuario busca un
   texto contenido en el título de uno, **Then** ese asset aparece en los resultados.
2. **Given** un asset sin título, **When** el usuario busca un texto contenido en su nombre
   de archivo original, **Then** el asset aparece.
3. **Given** la búsqueda, **When** el texto difiere solo en mayúsculas/minúsculas, **Then**
   el resultado es el mismo.
4. **Given** el filtro `Images` (o `Videos`), **When** se aplica, **Then** solo aparecen
   assets de ese tipo.
5. **Given** el filtro `Used` (o `Unused`), **When** se aplica, **Then** el resultado
   coincide exactamente con la semántica de uso de la US1 (un asset solo `Scheduled` es
   `Unused`; uno en `Ready in TikTok` es `Used`).
6. **Given** una búsqueda y un filtro combinados, **When** se aplican, **Then** el resultado
   cumple ambos.
7. **Given** una búsqueda o filtro sin resultados, **When** se aplica, **Then** la UI
   muestra un estado vacío claro, distinto del de una biblioteca sin contenidos.

---

### User Story 3 - Eliminar la metadata de ComfyUI antes de publicar (Priority: P1)

El usuario abre un asset generado con ComfyUI y pulsa **Remove metadata**. AutoPublisher
genera una copia sanitizada sin el workflow, el prompt ni ningún otro dato de generación o
privado, conservando la apariencia del contenido. A partir de ese momento la tarjeta muestra
`Metadata clean` y todas las publicaciones futuras de ese asset, en cualquier plataforma,
usan la copia limpia. El original queda intacto.

**Why this priority**: es la razón principal de la feature. Publicar un original de ComfyUI
expone el workflow completo y datos locales del usuario. Es independiente de las US1/US2.

**Independent Test**: importar un PNG, un JPEG, un WEBP y un vídeo con metadata de ComfyUI y
valores centinela; pulsar `Remove metadata`; verificar que ningún centinela aparece en la
copia (incluido contenido comprimido), que el archivo sigue siendo válido y visualmente
equivalente, que el original no ha cambiado y que una publicación posterior envía la copia.

**Acceptance Scenarios**:

1. **Given** un PNG con workflow y prompt de ComfyUI embebidos, **When** el usuario pulsa
   `Remove metadata`, **Then** se crea una copia sanitizada válida, el original no cambia
   (mismo checksum) y la copia no contiene ningún dato que permita reconstruir el workflow.
2. **Given** un asset sanitizado (copia limpia existente), **When** se publica en cualquier plataforma
   (ahora o programado), **Then** el archivo enviado es la copia sanitizada, y su checksum y
   tamaño son los usados en verificaciones, límites y fingerprints.
3. **Given** un asset cuya sanitización produce un archivo byte a byte idéntico al
   original, **When** termina la operación, **Then** el asset queda `clean`, la tarjeta
   muestra `Metadata clean`, el detalle indica que el original ya estaba limpio, no se
   guarda ninguna copia y las publicaciones siguen usando el original.
4. **Given** un asset ya sanitizado cuya copia existe, **When** el usuario vuelve a pulsar
   `Remove metadata` (o hace doble clic), **Then** no se rehace el trabajo y el estado no
   cambia.
5. **Given** un asset sanitizado cuya copia ha desaparecido o cuyo SHA-256 ya no coincide
   con el checksum registrado, **When** se intenta publicar, **Then** la publicación falla como media no disponible, nunca se envía
   el original, y la UI ofrece regenerar la copia.
6. **Given** un asset con una publicación en `PUBLISHING`, **When** el usuario pulsa
   `Remove metadata`, **Then** la operación se rechaza con un mensaje claro y nada cambia.
7. **Given** un asset con una publicación `SCHEDULED` y un consentimiento/fingerprint
   guardado (p. ej. TikTok o Instagram) calculado sobre el original, **When** el usuario
   sanitiza el asset, **Then** la publicación usará la copia limpia al ejecutarse y el
   consentimiento previo deja de ser válido de forma natural, exigiendo nueva confirmación
   donde la plataforma lo requiera.
8. **Given** un vídeo y un sistema sin ffmpeg, **When** el usuario pulsa `Remove metadata`,
   **Then** la operación falla con un mensaje claro indicando que ffmpeg es necesario, y la
   importación, la publicación y la sanitización de imágenes siguen funcionando.
9. **Given** un PNG, JPEG o WEBP con Orientation distinta de 1, **When** se sanitiza,
   **Then** la copia se muestra con la misma orientación visual que el original y su único
   EXIF es un bloque mínimo con Orientation (FR-025a).
10. **Given** un vídeo con rotación, audio y vídeo, **When** se sanitiza, **Then** la copia
    se reproduce con la misma duración efectiva, sincronía y orientación, sin recodificar.

---

### User Story 4 - Inspeccionar la metadata y los detalles técnicos de un asset (Priority: P2)

Desde el detalle del asset, el usuario ve los datos técnicos (tamaño, dimensiones, duración,
formato, checksum, nombre original, qué versión del archivo se usará al publicar) y puede
solicitar una inspección de metadata que le indica qué categorías sensibles o de generación
contiene el archivo: ubicación/GPS, dispositivo, software/encoder, fechas de captura, EXIF,
XMP, IPTC, comentarios/text chunks, metadata de contenedor, metadata de generación de IA y
de ComfyUI.

**Why this priority**: permite al usuario decidir si debe pulsar `Remove metadata` y
comprobar el resultado. Es valioso pero no imprescindible para el objetivo principal.

**Independent Test**: inspeccionar archivos con y sin metadata conocida y comprobar que las
categorías detectadas son las esperadas; inspeccionar un asset sanitizado y comprobar que el
archivo efectivo ya no presenta categorías sensibles.

**Acceptance Scenarios**:

1. **Given** un PNG de ComfyUI, **When** el usuario inspecciona su metadata, **Then** se
   detectan las categorías de generación de IA / ComfyUI.
2. **Given** una foto de móvil con GPS y modelo de dispositivo, **When** se inspecciona,
   **Then** se detectan ubicación y dispositivo.
3. **Given** un asset sin metadata sensible, **When** se inspecciona, **Then** la UI indica
   que no se ha detectado metadata sensible.
4. **Given** un asset sanitizado, **When** se inspecciona, **Then** la UI distingue entre lo
   detectado en el original y lo que contiene el archivo que se publicará, y este último no
   presenta categorías sensibles ni de generación (un EXIF mínimo que solo contiene
   Orientation no cuenta como metadata sensible, FR-025a).
5. **Given** el detalle de cualquier asset, **When** se muestra, **Then** nunca aparece la
   ruta interna del archivo ni el valor completo de datos sensibles innecesarios (p. ej. el
   workflow completo); basta con la categoría y, como mucho, un resumen breve.
6. **Given** el detalle de un asset sanitizado, **When** se muestra, **Then** indica que se
   publicará la versión sin metadata, con su tamaño y checksum efectivos.

---

### User Story 5 - Detectar como duplicado una copia limpia reimportada (Priority: P3)

El usuario descarga o recupera la copia sanitizada de un asset y la vuelve a importar en el
mismo proyecto. AutoPublisher la reconoce como contenido ya conocido en lugar de crear un
asset nuevo.

**Why this priority**: evita duplicados confusos, pero es un caso poco frecuente.

**Independent Test**: sanitizar un asset, importar al mismo proyecto un archivo idéntico a
la copia y comprobar que se detecta como duplicado del asset existente.

**Acceptance Scenarios**:

1. **Given** un asset sanitizado, **When** se importa en el mismo proyecto un archivo cuyo
   SHA-256 coincide con el de la copia sanitizada, **Then** la importación se detecta como
   contenido ya existente y apunta al asset original.
2. **Given** el mismo archivo, **When** se importa en otro proyecto, **Then** se importa
   normalmente (el dedupe sigue siendo por proyecto).

---

### Edge Cases

- **Doble clic / solicitudes concurrentes de `Remove metadata`**: solo una gana; la otra
  descarta su resultado temporal y el estado final es consistente.
- **Fallo al crear la copia** (archivo corrupto, error de ffmpeg, disco lleno): el original
  queda intacto, el estado en base de datos no cambia y el error es visible para el usuario.
- **Copia final escrita pero fallo al guardar el estado**: la copia recién escrita se
  elimina (mismo patrón que la importación); el asset sigue en su estado anterior.
- **Caída del proceso entre escribir la copia y confirmar el estado**: al arrancar se
  eliminan las copias limpias que no estén referenciadas por ningún `Content`. Nunca se
  elimina un original.
- **Copia sanitizada ausente o corrupta con estado `sanitized`**: la publicación falla como
  media no disponible; no hay fallback al original; la UI ofrece regenerar la copia.
- **Regenerar copia**: si el estado es `sanitized` pero la copia no está disponible, volver a
  pulsar `Remove metadata` la regenera desde el original.
- **Asset `clean` y nuevo `Remove metadata`**: el original es inmutable, por lo que el
  resultado sería el mismo; la operación no rehace trabajo.
- **Vídeo prácticamente limpio**: el remux genera normalmente una copia distinta; se acepta y
  el asset queda `sanitized`. No se decide `clean` en vídeo por lo que muestren herramientas
  de inspección.
- **Sanitización con publicación `SCHEDULED`**: permitida; al ejecutarse usa la copia
  limpia. Si una plataforma tenía consentimiento ligado al checksum del original, queda
  invalidado y se pide de nuevo.
- **Sanitización con publicación `PUBLISHING`**: rechazada.
- **Publicación que intenta empezar mientras se sanitiza**: no puede terminar enviando
  silenciosamente el original ni un archivo ambiguo; el mecanismo lo fija el plan (FR-037a).
- **Intentos y publicaciones históricos**: no se reescriben; el historial conserva lo que se
  envió en su momento.
- **PNG/JPEG/WEBP con Orientation ≠ 1**: se elimina todo el EXIF original y se escribe un
  EXIF mínimo que contiene únicamente Orientation (FR-025a).
- **Metadata tras el final lógico del archivo** (datos tras `IEND` en PNG, trailers tipo
  Motion Photo en JPEG): se elimina.
- **APNG / WEBP animado / WEBP con alpha**: la animación y la transparencia se conservan.
- **Ultra HDR / gain maps / Live Photo**: pueden perderse (riesgo aceptado).
- **Contenido sin publicaciones pero con publicaciones `UNSCHEDULED`**: cuenta como `Unused`
  y sin indicador `Scheduled`.
- **Búsqueda con caracteres especiales o vacía**: una búsqueda vacía equivale a no filtrar.

## Requirements *(mandatory)*

### Functional Requirements

#### Asset Library y uso

- **FR-001**: La UI DEBE presentar la biblioteca de contenidos de un proyecto como **Asset
  Library**. El modelo interno `Content` NO DEBE renombrarse y NO DEBE crearse una entidad
  `Asset`.
- **FR-002**: El uso de cada `Content` DEBE derivarse de `Publication`, `Account` y
  `PublicationAttempt`. NO DEBEN persistirse en `Content` flags de uso, contadores, listas de
  plataformas ni fecha de último uso.
- **FR-003**: Un `Content` DEBE considerarse **usado** si y solo si tiene al menos una
  publicación en `PUBLISHED` o `AWAITING_USER_ACTION`. `SCHEDULED`, `UNSCHEDULED`,
  `PUBLISHING`, `FAILED` y `CANCELLED` NO lo convierten en usado.
- **FR-004**: Una publicación en `AWAITING_USER_ACTION` DEBE presentarse como **Ready in
  TikTok** (o el equivalente de su plataforma) y NUNCA como publicada.
- **FR-005**: Un intento con resultado remoto incierto NO DEBE contarse como publicación
  confirmada; PUEDE mostrarse en el historial del detalle marcado como incierto.
- **FR-006**: Para cada `Content` DEBE poder obtenerse: usado/no usado; número de
  publicaciones; número de publicaciones confirmadas (`PUBLISHED`); plataformas y cuentas
  donde se usó; estados de sus publicaciones; fecha de la última publicación confirmada;
  publicaciones actualmente `SCHEDULED`; si alguna está `AWAITING_USER_ACTION`; e historial
  de publicaciones e intentos relacionados.
- **FR-007**: El resumen de uso para el listado de la biblioteca DEBE obtenerse mediante una
  consulta agregada por proyecto cuyo coste no crezca con una consulta adicional por
  contenido (sin N+1).
- **FR-008**: La tarjeta de cada asset DEBE mostrar únicamente: preview; `title` o, si no
  existe, `original_filename`; tipo imagen/vídeo; estado compacto (`Unused` o las
  plataformas donde se usó); indicador `Scheduled` si tiene publicaciones programadas;
  indicador `Ready in TikTok` si aplica; y el badge de metadata según FR-008a.
- **FR-008a**: Presentación del estado de metadata:
  - `unknown` → la tarjeta NO DEBE mostrar ningún badge positivo de metadata.
  - `clean` → la tarjeta DEBE mostrar `Metadata clean`.
  - `sanitized` → la tarjeta DEBE mostrar también `Metadata clean`.
  - NO DEBE usarse `Metadata removed` como badge genérico de forma que `clean` quede sin
    representación. La acción sigue llamándose `Remove metadata`.
- **FR-009**: La tarjeta NO DEBE mostrar checksum, MIME, ruta, EXIF, tamaño detallado,
  dimensiones, duración ni otra metadata técnica.

#### Búsqueda y filtros

- **FR-010**: La Asset Library DEBE ofrecer los filtros `All`, `Images`, `Videos`, `Used` y
  `Unused`, donde `Used`/`Unused` siguen exactamente FR-003.
- **FR-011**: La Asset Library DEBE permitir buscar por texto contenido en `title` u
  `original_filename`, sin distinguir mayúsculas/minúsculas, combinable con el filtro activo.
- **FR-012**: NO DEBE construirse un sistema avanzado de filtros (rangos de fechas, por
  plataforma, por cuenta, guardado de filtros, etc.) en esta feature.

#### Detalle del asset

- **FR-013**: El detalle DEBE poder mostrar: preview grande; historial de uso (plataforma,
  cuenta, estado, fechas, resultado incierto cuando aplique); última publicación confirmada;
  publicaciones programadas; tamaño; dimensiones; duración; formato/MIME; checksum; nombre de
  archivo original; estado de metadata; y qué versión del archivo se usará al publicar
  (original o sin metadata) con su tamaño y checksum efectivos.
- **FR-013a**: El detalle DEBE distinguir explícitamente los dos estados limpios:
  - `clean`: el original se comprobó mediante sanitización y ya era byte a byte limpio; no
    existe copia derivada y se publica el original.
  - `sanitized`: se eliminó metadata y existe una copia sanitizada; esa copia es la que se
    usa para publicar.
  - `unknown`: DEBE indicar que la metadata no se ha comprobado y ofrecer `Remove metadata`.
- **FR-014**: La ruta interna de ningún archivo (original o copia) DEBE exponerse nunca en
  la API ni en la UI.

#### Inspección de metadata

- **FR-015**: El sistema DEBE ofrecer inspección de metadata **bajo demanda** que
  identifique, al menos, las categorías: ubicación/GPS; dispositivo (Make/Model);
  software/encoder; fechas de creación/captura; EXIF; XMP; IPTC; comentarios/text chunks;
  metadata de contenedor; metadata de generación de IA; metadata de ComfyUI.
- **FR-016**: La inspección DEBE poder aplicarse al original y, si existe, a la copia
  sanitizada, y la UI DEBE distinguir ambos resultados.
- **FR-017**: NO es necesario persistir la metadata encontrada; la inspección PUEDE
  recalcularse cada vez.
- **FR-018**: La inspección NO DEBE devolver a la UI el contenido íntegro de bloques
  sensibles (p. ej. el workflow completo); DEBE limitarse a categorías y, como mucho,
  resúmenes breves.

#### Remove metadata

- **FR-019**: El detalle del asset DEBE ofrecer una acción única **Remove metadata**, sin
  exponer opciones técnicas del sanitizador.
- **FR-020**: El archivo original de un `Content` NUNCA DEBE modificarse, reemplazarse ni
  eliminarse por esta feature.
- **FR-021**: `Remove metadata` DEBE producir una versión segura para publicar y, a partir
  de ese momento, esa versión DEBE usarse automáticamente para todas las publicaciones
  futuras del asset. NO DEBE existir un selector original/limpio por publicación.
- **FR-022**: La copia sanitizada NO DEBE contener ningún dato embebido que permita
  reconstruir un workflow de ComfyUI ni revelar datos de generación, incluyendo:
  `workflow`, `prompt`, `extra_pnginfo`, `parameters`, `comf`, JSON de generación,
  metadata de custom nodes, seeds, samplers, nombres de checkpoint/modelo, LoRAs, rutas
  locales, parámetros del workflow o información equivalente, tanto en texto plano como
  comprimido.
- **FR-023**: La copia sanitizada NO DEBE contener ubicación/GPS, dispositivo, fechas de
  captura/creación, EXIF (salvo el EXIF mínimo de Orientation de FR-025a), XMP, IPTC, comentarios ni metadata
  de contenedor privada.
- **FR-024**: La sanitización DEBE conservar únicamente lo necesario para representar
  correctamente el contenido: orientación visual, perfil de color/ICC cuando corresponda,
  estructura del formato, transparencia, animación y los streams necesarios de vídeo y
  audio. NO DEBE alterar deliberadamente la apariencia ni recodificar/recomprimir.
- **FR-025**: **Imágenes** — el sanitizador DEBE funcionar por **lista blanca** estructural
  (solo se conserva lo explícitamente aprobado; lo desconocido se elimina) para:
  - **PNG**: conservar solo chunks estructurales/visuales aprobados (incluyendo color/ICC y
    APNG); eliminar `tEXt`, `zTXt`, `iTXt`, el `eXIf` original, `tIME`, `comf`, chunks
    desconocidos y datos tras `IEND` (Orientation según FR-025a).
  - **JPEG**: sin recompresión; conservar estructura, datos de imagen, JFIF, ICC y Adobe
    cuando sea necesario; eliminar el EXIF original, XMP, IPTC, COM, segmentos desconocidos
    y trailers (p. ej. Motion Photo). Orientation según FR-025a, con el segmento colocado
    según el diseño validado en el plan.
  - **WEBP**: sin recompresión; conservar VP8/VP8L, alpha, animación e ICC; eliminar el EXIF
    original, XMP y chunks desconocidos; recalcular correctamente tamaños y flags del
    contenedor (Orientation según FR-025a).
- **FR-025a**: **Orientation** (PNG, JPEG y WEBP): todo el EXIF original se elimina
  siempre. Si el original declara `Orientation` distinta de 1, la copia DEBE incluir un
  bloque EXIF mínimo, regenerado, que contenga **únicamente** Orientation con el mismo
  valor; ningún otro campo EXIF se conserva. Si Orientation es 1 o no existe, la copia no
  lleva EXIF. Ese EXIF mínimo NO cuenta como metadata sensible en la inspección. Workflow,
  prompt, GPS, dispositivo, fechas, software y el resto de metadata se eliminan igualmente.
  La regla de no recomprimir no cambia.
- **FR-026**: **Vídeo** (MP4, MOV, WEBM) — la sanitización DEBE copiar los streams sin
  recodificar, conservando reproducción, duración efectiva, sincronía y orientación/rotación,
  y eliminando metadata del contenedor, chapters, ubicación/GPS, fechas de creación,
  workflow/prompt de ComfyUI/VHS y datos/tracks auxiliares que puedan contener información
  privada o de generación cuando eliminarlos sea seguro. Se acepta que cadenas del
  codificador dentro del bitstream permanezcan si eliminarlas exigiría recodificar y no
  contienen workflow ni datos identificativos del usuario.
- **FR-027**: La sanitización de vídeo DEBE requerir ffmpeg. Si ffmpeg no está disponible,
  `Remove metadata` sobre vídeo DEBE fallar con un mensaje claro que lo indique, sin afectar
  a la importación, la publicación ni la sanitización de imágenes.
- **FR-028**: ExifTool NO DEBE ser una dependencia de runtime ni formar parte del
  sanitizador.

#### Estado de metadata y persistencia

- **FR-029**: `Content` DEBE ampliarse con la persistencia mínima: estado de metadata
  (`unknown`, `clean`, `sanitized`) y, para la copia, ubicación interna, checksum, tamaño y
  fecha de sanitización (todos opcionales). NO DEBEN crearse entidades de archivo/variante
  ni un `Content` nuevo para la copia.
- **FR-030**: Semántica de estados:
  - `unknown`: nunca se ha sanitizado (valor de todos los contenidos existentes y nuevos).
  - `clean`: se sanitizó y el resultado era byte a byte idéntico al original; no se guarda
    copia.
  - `sanitized`: existe una copia sanitizada distinta; todos los campos de copia DEBEN
    existir de forma consistente. En cualquier otro estado los campos de copia DEBEN estar
    vacíos.
- **FR-031**: La operación DEBE generar un resultado temporal, calcular su checksum y
  compararlo con el original: si es idéntico, el estado pasa a `clean` y el temporal se
  descarta; si no, se guarda como copia y el estado pasa a `sanitized`. En vídeo NO DEBE
  decidirse `clean` por otro criterio que no sea la igualdad byte a byte.

#### Archivo efectivo de publicación

- **FR-032**: DEBE existir un único resolvedor común del **archivo efectivo** de un
  `Content` que devuelva, al menos, su ubicación, checksum y tamaño efectivos:
  `unknown`/`clean` → original; `sanitized` → copia sanitizada.
- **FR-033**: Todos los publishers, verificaciones de integridad, planes de subida,
  comprobaciones de límites de tamaño y fingerprints de consentimiento que usen el archivo,
  el checksum o el tamaño DEBEN obtenerlos del resolvedor común. Como mínimo: TikTok
  (fingerprint de consentimiento, verificación SHA, plan de chunks, tamaño), Instagram
  (fingerprint), Threads (tamaño), Telegram (límites) y cualquier otro uso directo de la
  ubicación, el checksum o el tamaño del original en publishers o en la entrega de media.
- **FR-034**: Antes de utilizar una copia sanitizada para publicar, el sistema DEBE
  comprobar que la copia existe y que su SHA-256 completo coincide con el checksum
  sanitizado registrado, como último paso local de la preparación del envío (justo antes
  de iniciar la transferencia remota). Las comprobaciones ordinarias (listados, detalle,
  diálogos) se limitan a existencia y tamaño; NO DEBE recalcularse el SHA-256 completo en
  cada consulta o render. Si falta o no coincide, la publicación DEBE terminar como media no disponible
  / corrupta, con un error visible, y NUNCA DEBE usarse el original como fallback. El plan
  puede optimizar cómo se realiza esta comprobación, pero no puede reducir esta garantía.
- **FR-035**: Los consentimientos o fingerprints guardados que dependan del checksum del
  archivo DEBEN quedar invalidados de forma natural cuando cambie el checksum efectivo, y
  DEBE pedirse nueva confirmación donde la plataforma lo exija.
- **FR-036**: Las publicaciones e intentos históricos NO DEBEN reescribirse.

#### Concurrencia, idempotencia y atomicidad

- **FR-037**: `Remove metadata` DEBE rechazarse mientras alguna publicación del `Content`
  esté en `PUBLISHING`. DEBE permitirse con publicaciones `SCHEDULED` (el plan DEBE
  confirmar que no hay riesgos adicionales; si los encuentra, DEBE proponer el cambio antes
  de implementarlo).
- **FR-037a**: El plan (`/speckit-plan`) DEBE resolver explícitamente la concurrencia entre
  `Remove metadata` y la transición/inicio de una publicación del mismo `Content` (manual o
  del scheduler), garantizando que:
  - si una publicación ya está `PUBLISHING`, `Remove metadata` se rechaza;
  - mientras `Remove metadata` crea o confirma la versión limpia, ninguna publicación del
    mismo `Content` puede empezar de forma que termine enviando silenciosamente el original;
  - tras confirmar la sanitización, toda publicación nueva usa el archivo efectivo limpio;
  - nunca se produce un estado mixto o ambiguo sobre qué archivo se está enviando.
  La spec no impone mecanismo: el plan DEBE inspeccionar la arquitectura existente y elegir
  la solución neutral más pequeña posible, evitando cambios amplios del núcleo.
- **FR-038**: Si el asset ya está `sanitized` con copia disponible, o ya está `clean`,
  `Remove metadata` NO DEBE rehacer trabajo y DEBE responder con el estado actual.
- **FR-039**: Si dos solicitudes compiten, solo una DEBE confirmar su resultado; la otra
  DEBE descartar su temporal sin dejar archivos huérfanos ni estados inconsistentes.
- **FR-040**: Si falla la creación de la copia, el original DEBE quedar intacto, el estado
  en base de datos NO DEBE cambiar y los temporales DEBEN quedar confinados en el área
  temporal existente.
- **FR-041**: Si la copia final se ha escrito pero falla la confirmación del estado, la copia
  DEBE eliminarse siguiendo el patrón ya usado por la importación.
- **FR-042**: Al arrancar, el sistema DEBE eliminar las copias sanitizadas que no estén
  referenciadas por ningún `Content`. Este barrido NUNCA DEBE eliminar un original.

#### Dedupe

- **FR-043**: La detección de duplicados en la importación DEBE considerar, además del
  checksum del original, el checksum de la copia sanitizada de los contenidos del mismo
  proyecto: un archivo que coincida con cualquiera de ellos DEBE detectarse como contenido
  ya existente. Esto NO DEBE crear un segundo `Content` ni introducir variantes.

#### Errores y seguridad

- **FR-044**: Los errores de sanitización, inspección y resolución de archivo efectivo DEBEN
  ser visibles para el usuario con mensajes seguros que no expongan rutas internas ni
  contenido de metadata sensible.
- **FR-045**: Los logs NO DEBEN registrar el contenido de la metadata sensible encontrada
  (prompts, workflows, coordenadas, etc.).

### Key Entities *(include if feature involves data)*

- **Content** (existente, ampliado): el asset de la biblioteca. Mantiene su original
  inmutable y sus atributos actuales. Se añade su **estado de metadata** (`unknown`,
  `clean`, `sanitized`) y, cuando está `sanitized`, los datos de su **copia sanitizada**
  (ubicación interna, checksum, tamaño, fecha). No guarda datos de uso.
- **Archivo efectivo** (concepto, no persistido): el archivo que se publicará para un
  `Content` —original o copia sanitizada— con su checksum y tamaño. Lo determina un único
  resolvedor.
- **Resumen de uso** (concepto, no persistido): derivado de `Publication`, `Account` y
  `PublicationAttempt`; incluye usado/no usado, recuentos, plataformas, cuentas, estados,
  última publicación confirmada, programadas y `Ready in TikTok`.
- **Informe de inspección de metadata** (concepto, no persistido): categorías de metadata
  sensible o de generación detectadas en el original y, si existe, en la copia.
- **Publication / PublicationAttempt / Account** (existentes, sin cambios de modelo): fuente
  del uso; los intentos históricos no se reescriben.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (crítico)**: Para cada formato soportado en el que ComfyUI puede embeber metadata
  (al menos PNG, y los formatos de imagen y vídeo que el usuario usa realmente), una copia
  sanitizada cargada en ComfyUI **no permite reconstruir el workflow**, mientras que el
  original sí lo permite (validación manual V1). Si el workflow sigue siendo recuperable, la
  feature no puede cerrarse.
- **SC-002**: En el 100 % de los archivos de prueba con valores centinela (workflow, prompt,
  parameters, `comf`, seed, checkpoint, LoRA, sampler, ruta local, metadata de custom node),
  ningún centinela aparece en la copia sanitizada, ni en texto plano ni en contenido
  comprimido, y la copia sigue siendo un archivo válido de su formato.
- **SC-003**: En el 100 % de las sanitizaciones, el checksum del original es idéntico antes y
  después.
- **SC-004**: Las copias sanitizadas de imagen son visualmente idénticas al original
  (mismos píxeles decodificados, misma orientación visual, misma transparencia/animación) y
  las de vídeo conservan duración efectiva, sincronía y orientación.
- **SC-005**: En el 100 % de las publicaciones de un asset sanitizado, en cualquier
  plataforma, el archivo enviado es la copia sanitizada; en ningún caso de copia ausente o
  corrupta se envía el original.
- **SC-006**: El usuario puede responder "¿he usado este asset y dónde?" en menos de
  5 segundos desde que abre la Asset Library, sin abrir el detalle.
- **SC-007**: El estado usado/no usado, `Scheduled` y `Ready in TikTok` coincide con la
  semántica definida en el 100 % de los casos de prueba (incluidos fallidos, cancelados,
  inciertos y `AWAITING_USER_ACTION`).
- **SC-008**: La Asset Library de un proyecto con varios cientos de assets carga su listado
  con el resumen de uso sin degradación perceptible respecto a la biblioteca actual.
- **SC-009**: Ninguna tarjeta muestra datos técnicos (checksum, MIME, ruta, EXIF, tamaño,
  dimensiones, duración), y ninguna respuesta de la API ni pantalla expone la ruta interna de
  un archivo.
- **SC-010**: Sin ffmpeg instalado, importar, publicar y sanitizar imágenes funciona igual;
  solo la sanitización de vídeo falla, con un mensaje que menciona ffmpeg.

## Validación manual V1 (ComfyUI)

Con archivos propios generados para la prueba (nunca versionados):

1. Cargar/arrastrar el original en ComfyUI y confirmar que reconstruye el workflow.
2. Pulsar `Remove metadata` en AutoPublisher.
3. Cargar/arrastrar la copia sanitizada en ComfyUI.
4. Confirmar que ComfyUI **no** puede reconstruir el workflow.

Validar al menos los formatos de ComfyUI que el usuario usa realmente y que admiten workflow
embebido. **STOP** si el workflow sigue siendo recuperable.

## Riesgos aceptados

- Ultra HDR / gain maps pueden perderse en la copia.
- Datos auxiliares de Motion/Live Photo pueden perderse.
- Los vídeos generan normalmente una copia aunque estén prácticamente limpios.
- Cadenas del codificador dentro del bitstream de vídeo pueden permanecer si eliminarlas
  exige recodificar y no contienen workflow ni datos privados.
- Algunos casos de iPhone (HEIF no soportado; vídeos con metadata Apple específica) deben
  validarse con archivos reales si están disponibles.

Estos casos se documentan y NO se convierten en infraestructura compleja en esta feature.

## Fuera de alcance

- Borrar `Content`.
- Thumbnails generados en backend.
- Variantes generales de archivo, resize o transcoding.
- Presets de sanitización u opciones avanzadas.
- Multi-platform Distribution y Republish.
- Renombrar `Content` a `Asset` en código o base de datos.
- Rediseño global de la UI/UX.
- Filtros avanzados (por plataforma, cuenta, fechas…).
- Persistir la metadata inspeccionada.

## Assumptions

- La Asset Library sigue siendo por proyecto, como la Content Library actual; búsqueda y
  filtros se aplican dentro del proyecto.
- "Publicación confirmada" significa `PUBLISHED`. `AWAITING_USER_ACTION` cuenta como uso
  pero no como publicación confirmada ni como "última publicación confirmada".
- Las plataformas/cuentas "usadas" son las de publicaciones `PUBLISHED` o
  `AWAITING_USER_ACTION`.
- `Ready in TikTok` es hoy el único caso de `AWAITING_USER_ACTION`; si otra plataforma lo
  usara en el futuro, la etiqueta se adaptaría a su plataforma.
- La preview de la tarjeta reutiliza el mecanismo actual de la biblioteca (sin thumbnails
  generados en backend).
- Las copias sanitizadas se guardan en el almacenamiento local de medios existente, junto a
  los originales pero claramente distinguibles, y el área temporal existente se reutiliza
  para los resultados intermedios.
- La comprobación de integridad de la copia antes de publicar está fijada en FR-034
  (existencia + SHA-256); el plan solo decide cómo implementarla eficientemente.
- Los tests de integración de vídeo pueden omitirse localmente cuando ffmpeg no está
  disponible, siguiendo el patrón `skipif` existente; la CI DEBE proporcionar ffmpeg para
  ejecutarlos.
- Testing ligero: tests dirigidos del agregado de uso, del sanitizador (con centinelas), del
  resolvedor, regresiones de los publishers afectados y tests de componentes del frontend.
  No se prueban internals de librerías de imagen ni de ffmpeg. La suite completa y los
  quality gates se ejecutan preferentemente en la CI del PR.
- El plan (`/speckit-plan`) DEBE validar en `research.md` la lista blanca exacta de chunks y
  segmentos por formato, la colocación del EXIF mínimo de Orientation en cada formato, la
  recomposición del contenedor WEBP, los parámetros de ffmpeg que garantizan stream copy,
  conservación de rotación y eliminación de metadata/chapters/tracks auxiliares en MP4, MOV
  y WEBM, y cómo detectar metadata de ComfyUI/VHS en vídeo.
