# Data Model: Bootstrap técnico del proyecto

**Feature**: `001-technical-bootstrap` | **Fecha**: 2026-10-05

Esta feature no introduce entidades de dominio ni persistencia (FR-019): no hay proyectos,
cuentas, contenido, publicaciones ni base de datos.

El único dato estructurado es la respuesta del health check, que no se persiste:

| Campo    | Tipo   | Valores | Descripción                         |
|----------|--------|---------|-------------------------------------|
| `status` | string | `"ok"`  | Indica que el servicio está operativo |

Detalle completo del contrato en [contracts/health.md](contracts/health.md).
