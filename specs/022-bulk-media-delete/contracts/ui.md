# UI Contract — Feature 022: Bulk Media Delete

Solo cambios sobre Feature 021. Textos en inglés.

## 1. SelectionBar (Folder, Unsorted, All media)

```text
desktop:  [ N selected ................ (Move) (Delete) (Cancel) ]
phone:    [ N selected                                          ]
          [ (Move)        (Delete)        (Cancel)              ]
```

- Move: primario (sin cambios). Delete: botón secundario con texto destructivo
  (`ap-delete-entry`), nunca el dominante. Cancel: sin cambios.
- `0 selected` → Move y Delete deshabilitados.
- Teléfono: el contador ocupa su propia fila; los tres botones comparten la segunda fila
  (`flex: 1 1 0`), sin desbordamiento horizontal y por encima de la navegación inferior
  (comportamiento sticky existente).

## 2. Confirmación (DeleteConfirmDialog reutilizado)

- Título: `Delete {n} media item(s)?` (n = selección al pulsar Delete).
- Desktop → `Dialog`; teléfono → `Sheet` (comportamiento existente del componente).
- Cuerpo: líneas de `summary` del backend. Sin nombre (el preview trae `name: null`). Sin
  lista de Media.
- Botones: `Delete` (danger) + `Cancel`. Con bloqueo: solo el mensaje del bloqueo y `Close`.
- Una sola confirmación; sin escribir nombres ni segundas pantallas.

### Cambios en el componente

| Cambio | Efecto en usos existentes |
|---|---|
| `preview.name` nulo → no se pinta la línea de nombre | ninguno (siempre traen nombre) |
| Prop opcional `onMissing` → un `404` (preview o delete) llama a `onMissing` en lugar de `onDeleted` | ninguno (no la pasan) |

## 3. Estados y transiciones

| Situación | Comportamiento |
|---|---|
| Cancel / cerrar | Nada cambia; la selección y Select mode se conservan |
| `204` | Select mode termina; todas las tarjetas seleccionadas desaparecen a la vez tras recargar la vista; flash `"{n} media deleted."`; si el detalle abierto era de un Media borrado, se cierra a la vista; contadores de carpetas, Unsorted y All media actualizados; overview recargado |
| Vista vacía tras borrar | Empty state normal de esa vista; no se navega fuera |
| Blocker en el preview | Mensaje + `Close`; nada cambia |
| `409 post_in_progress` / `metadata_removal_in_progress` en el delete | Se muestra como blocker (comportamiento existente) |
| `409 deletion_changed` | Aviso "Something changed. Review it again.", preview recargado, nuevo clic en Delete requerido |
| Preview `404` (selección obsoleta), también tras un `deletion_changed` | Diálogo cerrado; vista recargada; la selección se poda a los Media que siguen en la vista; flash `"Some selected media no longer exist. Review your selection."`; Select mode sigue activo |
| Error de red / 5xx en el delete | "Couldn't delete it. Try again." en el diálogo; ninguna tarjeta desaparece |

Nunca hay estado visual parcial: las tarjetas solo cambian tras recargar la vista del
backend.

## 4. Fuera de alcance

Selección múltiple en Media detail, bulk de Posts/Accounts/Projects/Folders, Undo, Trash,
cambios visuales generales de Library.
