# Contract: Health check

**Feature**: `001-technical-bootstrap` | Requisitos: FR-004, FR-005, SC-004

## `GET /health`

Indica si el backend está en ejecución. No requiere autenticación ni parámetros.

### Respuesta exitosa

- **Status**: `200 OK`
- **Content-Type**: `application/json`
- **Body**:

```json
{"status": "ok"}
```

### Garantías

- El cuerpo contiene exactamente el campo `status` con el valor `"ok"`.
- No incluye secretos, rutas del sistema, variables de entorno, versiones de dependencias
  ni otros detalles internos.
- No depende de servicios externos: responde siempre que el proceso esté en ejecución.

### Rutas inexistentes

Cualquier otra ruta responde `404 Not Found` con el cuerpo de error estándar del framework
(`{"detail": "Not Found"}`), sin detalles internos.

### Fuera de contrato

La documentación interactiva autogenerada (`/docs`, `/redoc`, `/openapi.json`) puede estar
disponible en desarrollo, pero no forma parte del contrato de esta feature.
