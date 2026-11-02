# Specification Quality Checklist: Media Metadata Hygiene

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-02
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Como en la spec de 016, la sección *Contexto* y FR-007/FR-009/FR-013 nombran formatos de
  archivo, bloques de metadata y herramientas (`ffmpeg`, `ffprobe`, ExifTool). Es intencional:
  definen **qué** cuenta como metadata relevante y qué herramientas se permiten (restricción de
  dependencias pedida por el usuario), no cómo se implementa. Código, endpoints y esquema de
  datos quedan para el plan.
- SC-003 menciona ExifTool solo como oráculo independiente de validación, no del producto.
- Scope mínimo (tras `/speckit-analyze`): badge derivado en el frontend de `metadata_status` y
  `publish_file.available`, **Clean metadata** en la cabecera del detalle reutilizando el endpoint
  de 016, reinspección del resultado antes de aceptarlo, JFIF sin miniatura y logs sin salida de
  ffmpeg/ffprobe. Sin modelo, migraciones, endpoints ni estados nuevos.
- El hardening avanzado (evidencia persistente, parsers profundos, backfill, versión de reglas,
  streamhash, inspección al importar) queda para la Feature 031; `reference-031/` es solo
  referencia.
- Decisiones: un original ya limpio no genera copia; badge de dos colores con motivo; no se
  bloquea publicar en 🟡.
