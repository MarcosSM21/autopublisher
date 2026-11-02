# Feature Specification: Media Metadata Hygiene

**Feature Branch**: `028-metadata-hygiene`

**Created**: 2026-11-02 (simplificada el 2026-11-02 tras `/speckit-analyze`)

**Status**: Draft

**Input**: User description: "Feature 028 — Media Metadata Hygiene. Mostrar en cada Media Card y
en el detalle si AutoPublisher ya ha limpiado la metadata del media (🟢 Metadata cleaned /
🟡 Metadata not cleaned), permitir limpiarla con la funcionalidad existente de Feature 016 y
actualizar el estado visual al terminar. Reutilizar `metadata_status` y `publish_file.available`
como fuente del badge; reinspeccionar la copia con el inspector existente antes de aceptarla;
corregir la miniatura JFIF y los logs con salida bruta. Sin tablas de evidencia, versionado de
reglas, parsers nuevos, worker, backfill ni validación forense."

## Regla de producto

**El badge responde a una sola pregunta: "¿AutoPublisher ya ha ejecutado correctamente su
proceso de limpieza de metadata sobre este media?"**

- 🟢 significa que la limpieza de Feature 016 se ejecutó con éxito sobre este media y que el
  archivo que se publica es el resultado de esa limpieza (o el original, si no había nada que
  quitar).
- No promete una verificación forense exhaustiva de cada byte. Los límites conocidos de la
  limpieza de 016 siguen vigentes (ver Riesgos aceptados).

## Contexto (estado actual verificado en el código)

Feature 016 ([docs/asset-library.md](../../docs/asset-library.md),
[specs/016-asset-library-metadata](../016-asset-library-metadata/spec.md)) ya implementa todo
el mecanismo:

- **`Content.metadata_status`**:
  - `unknown`: Remove metadata nunca se ha ejecutado (valor de todo media importado);
  - `clean`: se ejecutó y el resultado fue byte a byte idéntico al original (la lista blanca no
    tenía nada que quitar), así que no hay copia y se publica el original;
  - `sanitized`: existe una copia limpia, con checksum guardado, que se publica siempre en lugar
    del original.
- **`publish_file.available`**, en cada `ContentRead` (listado y detalle): comprobación barata
  (existencia + tamaño) del archivo que se publica.
- **Sanitizadores** sin recompresión ni recodificación: JPEG, PNG/APNG y WebP por lista blanca de
  bloques; MP4, MOV y WebM por remux con copia de streams.
- **Inspector bajo demanda** (`Inspect metadata`): categorías y nombres de claves, nunca valores.
- **Endpoint `POST /api/contents/{id}/remove-metadata`**: idempotente, regenera una copia ausente
  o dañada, con concurrencia frente a publicaciones, borrado y cleanup de huérfanos.
- **Resolvedor único** `resolve_publish_file`, que comprueba el SHA-256 de la copia antes de cada
  subida y nunca cae al original.
- **UI actual**: el estado solo aparece como texto dentro del desplegable *File details* del
  detalle, junto a los botones *Inspect metadata* y *Remove metadata*. No hay badge en las cards
  ni en la cabecera del detalle.

Huecos detectados durante el research (ver [research.md](research.md)):

1. El sanitizador JPEG conserva el segmento JFIF entero, **incluida una posible miniatura
   embebida**, y el inspector no la detecta.
2. Tras limpiar, la copia no se vuelve a inspeccionar: se acepta solo por su checksum.
3. Los errores de ffmpeg/ffprobe se registran en logs de debug con su stderr y con `exc_info`,
   que pueden contener tags y valores de metadata.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver de un vistazo si cada media está limpio (Priority: P1)

Al abrir la Library, cada Media Card muestra un badge: 🟢 **Metadata cleaned** o 🟡 **Metadata
not cleaned**. El detalle del media muestra el mismo badge en su cabecera, con un motivo breve.

**Why this priority**: es la necesidad central: saber qué media ya ha pasado por la limpieza antes
de publicarlo o enviarlo.

**Independent Test**: con un media sin limpiar y otro limpiado, la Library muestra un badge
amarillo y otro verde, y el detalle de cada uno repite el badge con su motivo.

**Acceptance Scenarios**:

1. **Given** un media recién importado (`unknown`), **When** abro la Library, **Then** su card
   muestra 🟡 *Metadata not cleaned* y el detalle indica *Not cleaned yet*.
2. **Given** un media `clean`, **When** abro la Library, **Then** su card muestra 🟢 *Metadata
   cleaned* y el detalle indica *Already clean*.
3. **Given** un media `sanitized` cuya copia limpia está disponible, **When** abro la Library,
   **Then** su card muestra 🟢 *Metadata cleaned* y el detalle indica *Cleaned copy*.
4. **Given** un media `sanitized` cuya copia limpia no está disponible, **When** abro la Library,
   **Then** su card muestra 🟡 *Metadata not cleaned* y el detalle indica *Clean copy missing*.
5. **Given** un teléfono, **When** veo la Library, **Then** el badge de metadata y el indicador de
   uso existente caben en la card sin desbordarla.

---

### User Story 2 - Limpiar la metadata desde el detalle (Priority: P1)

En la cabecera del detalle de un media 🟡, el usuario pulsa **Clean metadata**. AutoPublisher
ejecuta la limpieza de 016, **reinspecciona el resultado con el inspector existente** antes de
aceptarlo y, si todo va bien, el badge pasa a 🟢 sin recargar la página.

**Why this priority**: sin una acción visible y fiable, el badge solo informa.

**Independent Test**: en un JPEG con GPS, pulsar Clean metadata → el badge pasa a 🟢 *Cleaned
copy* en el detalle y en la card al volver a la Library; el original no cambia.

**Acceptance Scenarios**:

1. **Given** un media `unknown`, **When** pulso Clean metadata en la cabecera del detalle,
   **Then** se ejecuta la limpieza existente y el badge del detalle pasa a 🟢 inmediatamente;
   al volver a la Library la card también aparece en 🟢.
2. **Given** un media `sanitized` con la copia ausente, **When** pulso Clean metadata, **Then** se
   regenera la copia (comportamiento de 016) y el badge pasa a 🟢 *Cleaned copy*.
3. **Given** que la reinspección del resultado encuentra metadata, **When** termina la acción,
   **Then** la limpieza se rechaza, no se guarda ninguna copia, el estado no cambia, el badge
   sigue 🟡 y se muestra un mensaje claro.
4. **Given** un vídeo y falta `ffmpeg` o `ffprobe`, **When** pulso Clean metadata, **Then** la
   acción falla con un mensaje claro y el estado no cambia.
5. **Given** un media en 🟢, **When** abro su detalle, **Then** Clean metadata no se ofrece.
6. **Given** un post del media está publicándose, **When** pulso Clean metadata, **Then** se
   rechaza con el mensaje existente de 016 y nada cambia.
7. **Given** un JPEG cuyo segmento JFIF lleva una miniatura embebida, **When** pulso Clean
   metadata, **Then** la copia conserva la imagen principal sin recomprimir, ya no contiene la
   miniatura y supera la reinspección.

---

### User Story 3 - Seguir inspeccionando la metadata (Priority: P3)

*Inspect metadata* y *File details* se mantienen como hoy: el usuario puede ver qué categorías
tiene el original y, si existe, la copia limpia.

**Why this priority**: ya existe; solo se cambian textos y se añade la detección de la miniatura
JFIF.

**Independent Test**: Inspect metadata sobre un JPEG con miniatura JFIF lista esa miniatura entre
las categorías encontradas.

**Acceptance Scenarios**:

1. **Given** cualquier media, **When** pulso Inspect metadata, **Then** veo el mismo informe que en
   016, con *Clean metadata* en lugar de *Remove metadata* en los textos.
2. **Given** un JPEG con miniatura JFIF, **When** lo inspecciono, **Then** el informe del original
   incluye la miniatura como metadata encontrada.

### Edge Cases

- **Original ya limpio**: la limpieza produce un resultado idéntico, la reinspección no encuentra
  nada y el estado pasa a `clean` (🟢 *Already clean*), sin copia (016).
- **Vídeo**: el remux casi siempre produce bytes distintos, así que un vídeo limpiado acaba
  `sanitized` (🟢 *Cleaned copy*), igual que en 016.
- **Copia dañada con el mismo tamaño**: el badge sigue 🟢 porque la comprobación de la UI es
  barata; publicar se bloquea por el checksum (016) y Clean metadata la regenera.
- **Media limpiados antes de esta feature**: conservan su estado (`clean`/`sanitized`) y su badge
  verde; no se reinspeccionan automáticamente (ver Riesgos aceptados).
- **Fallo de la reinspección por herramienta ausente** (ffprobe en vídeo): no se puede verificar,
  así que la limpieza se rechaza; importar y publicar no se ven afectados.
- **Crash durante la limpieza**: sin cambios respecto a 016 (temporales y copias huérfanas se
  eliminan al arrancar).
- **Proyecto inactivo**: limpiar sigue permitido (016).

## Requirements *(mandatory)*

### Functional Requirements

#### Estado visual

- **FR-001**: El badge DEBE derivarse únicamente de `metadata_status` y `publish_file.available`,
  que ya incluye cada `ContentRead`:

  | `metadata_status` | `publish_file.available` | Badge | Motivo en el detalle |
  |---|---|---|---|
  | `unknown` | — | 🟡 Metadata not cleaned | Not cleaned yet |
  | `clean` | `true` | 🟢 Metadata cleaned | Already clean |
  | `sanitized` | `true` | 🟢 Metadata cleaned | Cleaned copy |
  | `sanitized` | `false` | 🟡 Metadata not cleaned | Clean copy missing |
  | `clean` | `false` | 🟡 Metadata not cleaned | Media file missing |

- **FR-002**: El color NUNCA DEBE ser la única señal: el badge lleva texto y un texto accesible con
  el motivo.
- **FR-003**: NO DEBEN añadirse campos, tablas ni estados nuevos para el badge; la API no cambia
  para mostrarlo.

#### Library y detalle

- **FR-004**: Cada Media Card DEBE mostrar el badge de metadata junto al indicador de uso existente,
  legible en móvil.
- **FR-005**: La cabecera del detalle del media DEBE mostrar el badge, su motivo y el botón **Clean
  metadata** cuando la limpieza se puede ejecutar: `unknown`, o `sanitized` con la copia no
  disponible (la misma condición que hoy usa *File details*).
- **FR-006**: Clean metadata DEBE reutilizar el endpoint existente `POST
  /api/contents/{id}/remove-metadata` y el manejador existente del frontend; mientras se ejecuta,
  el botón muestra un estado de carga y los errores de la API se muestran en el detalle.
- **FR-007**: Tras una limpieza correcta, el badge del detalle DEBE actualizarse inmediatamente sin
  recargar, y la card DEBE mostrar el nuevo estado al volver a la Library.
- **FR-008**: *Inspect metadata* y *File details* DEBEN mantenerse; los textos visibles *Remove
  metadata* / *Removing metadata…* DEBEN pasar a *Clean metadata* / *Cleaning metadata…*.

#### Backend

- **FR-009**: **Reinspección antes de aceptar.** Tras generar el resultado temporal de la limpieza,
  y antes de guardarlo como copia o de marcar el media `clean`, el sistema DEBE inspeccionarlo con
  el inspector existente de 016. Si la inspección encuentra cualquier categoría de metadata, o no
  puede realizarse (por ejemplo, porque falta ffprobe en un vídeo), la limpieza DEBE rechazarse
  con un error claro, el temporal DEBE descartarse y ni el estado ni el archivo publicado DEBEN
  cambiar.
- **FR-010**: **Miniatura JFIF.** El sanitizador JPEG DEBE reconstruir el segmento JFIF sin
  miniatura embebida, conservando su información técnica (versión, unidades, densidad) y sin
  recomprimir la imagen principal; los segmentos de extensión JFXX (miniaturas) DEBEN eliminarse.
  El inspector existente DEBE informar de una miniatura JFIF/JFXX como metadata encontrada, para
  que Inspect metadata y la reinspección de FR-009 la detecten.
- **FR-011**: **Logs.** Ningún log, en ningún nivel (debug incluido), DEBE contener el stderr o la
  salida bruta de ffmpeg/ffprobe, ni trazas (`exc_info`) de sus errores, ni valores de metadata.
  Solo se registran el tipo de error o el código de salida.
- **FR-012**: Los mensajes del backend que mencionan *Remove metadata* (por ejemplo, copia ausente o
  dañada) DEBEN decir *Clean metadata*. El nombre del endpoint no cambia.
- **FR-013**: El resto del comportamiento de 016 DEBE mantenerse sin cambios: original inmutable,
  resolvedor único, concurrencia, idempotencia, regeneración de la copia, borrado, cleanup y
  backup/restore.

### Key Entities *(include if feature involves data)*

- **Media (`Content`)**: sin cambios de modelo. `metadata_status` y los campos de la copia limpia
  (016) siguen siendo la fuente del estado.
- **Publish file**: el archivo que se publica (la copia limpia si existe, si no el original),
  decidido por el resolvedor de 016; su disponibilidad llega ya en `publish_file.available`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El 100 % de las Media Cards y de los detalles muestran el badge según la tabla de
  FR-001; los tests cubren las cinco combinaciones.
- **SC-002**: Desde el detalle de un media 🟡, el usuario lo deja en 🟢 con un solo clic y sin
  recargar.
- **SC-003**: Ninguna limpieza se acepta si la reinspección del resultado encuentra metadata: un
  test con un sanitizador alterado lo demuestra.
- **SC-004**: Un JPEG con miniatura JFIF limpiado no contiene la miniatura; su imagen principal se
  decodifica con píxeles idénticos al original y su original conserva el checksum de importación.
- **SC-005**: Con los logs a nivel debug, una limpieza o inspección de vídeo que falla no registra
  ningún valor de metadata sembrado ni la salida bruta de la herramienta.
- **SC-006**: Abrir la Library no tarda perceptiblemente más que antes: no hay inspecciones ni
  consultas nuevas por card.

## Riesgos aceptados

- El badge refleja que la limpieza se ejecutó, no una verificación forense: siguen vigentes los
  límites de 016 (cadenas del encoder dentro del bitstream de vídeo, pérdida de Ultra HDR y de
  datos de Live Photo/Motion Photo, inspección de vídeo basada en los tags que expone ffprobe).
- Los media limpiados antes de esta feature conservan su badge verde aunque su copia pudiera
  contener una miniatura JFIF (corrección FR-010); no se reinspeccionan automáticamente. La
  reverificación queda para la feature de hardening.
- Una copia dañada con el mismo tamaño se muestra 🟢 hasta que se intenta publicar (allí el
  checksum la bloquea).

## Fuera de alcance

Reservado para una futura **Feature 031 — Metadata Verification & Hardening**, con el research ya
hecho como referencia en [reference-031/](reference-031/research.md) (no forma parte del scope de
028):

- evidencia persistente atada al checksum y tabla de inspecciones;
- versionado de reglas de inspección (`INSPECTION_RULES_VERSION`);
- parsers propios de contenedor MP4/MOV y WebM;
- inspección automática al importar, worker y backfill de media existentes;
- validación de equivalencia (píxeles idénticos, `streamhash`) y análisis del bitstream;
- estados más ricos (`incomplete`, `error`), categoría de identificadores internos y detección de
  la miniatura EXIF IFD1;
- reverificación de los media limpiados antes de esta feature.

También fuera de alcance: Send to Phone (029), Telegram Drafts (030), sobrescribir el original,
limpieza en lote, filtros por estado de metadata, avisos o bloqueos al publicar un media 🟡,
cambiar el nombre del endpoint y nuevos formatos.

## Assumptions

- El listado de Library y el detalle ya reciben `metadata_status` y `publish_file` en cada
  `ContentRead`; el frontend ya tiene el tipo `MetadataStatus`.
- El detalle ya vuelve a pedir el media tras una limpieza (`onChanged`), y la Library vuelve a
  cargar sus media al regresar; basta con mostrar el badge con esos datos.
- La reinspección usa las funciones existentes `inspect_image` / `inspect_video_metadata`; un
  informe con `inspected = false` cuenta como "no se pudo verificar".
- El componente `Badge` existente (tonos `success`/`warning`, icono) es suficiente.
- La CI ya instala ffmpeg/ffprobe; los tests de vídeo reales siguen el marcador `real_ffprobe`.
