# Specification Quality Checklist: Conexión de cuentas reales de TikTok mediante OAuth oficial

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-14
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

- Como en las Features 005/008/010, la sección "Restricciones de la plataforma" cita endpoints,
  parámetros y códigos de error oficiales de TikTok: son restricciones externas que condicionan el
  comportamiento del producto, no decisiones de implementación. Lenguajes, frameworks, rutas,
  puertos, esquema y nombres de módulos quedan diferidos al plan.
- Decisiones de producto tomadas sin marcador de clarificación (documentadas en Assumptions):
  `Disconnect` con fallo temporal no borra nada y ofrece `Remove locally without revoking` como
  acción explícita separada; `Disconnect` permitido en entidades inactivas incluida la renovación
  necesaria para revocar; la caducidad del refresh token guardada en el almacén seguro es evidencia
  definitiva; los scopes autoritativos son los de la respuesta de tokens.
- Riesgos a confirmar en plan/quickstart: codificación hexadecimal del `code_challenge` (no
  estándar), disponibilidad de `video.publish` en Sandbox, códigos de error OAuth de grant
  inválido y semántica de error de `/v2/oauth/revoke/`.
- Revisión 2026-10-14 (4 ajustes del usuario), todos los ítems siguen en PASS:
  1. FR-031/FR-018/FR-021/SC-003/tests: `code` y `state` existen solo en la URL entrante del
     callback exigida por TikTok (no persistida, no registrada, no devuelta por API, consumida y
     sustituida por URL limpia); secret, tokens y `code_verifier` nunca en URLs.
  2. FR-009/FR-043/FR-044/US3: Verify separa señales vivas de scopes conocidos; `video.publish`
     nunca se presenta como comprobado en vivo; sin llamadas de publishing/`creator_info`.
  3. FR-058a/FR-058b: gate manual temprano de viabilidad (Sandbox, Login Kit Desktop, Content
     Posting API, Direct Post, `video.publish` sin App Review, redirect URI, verificación de
     URL/dominio) con STOP explícito.
  4. US4/FR-012/FR-046–FR-048/FR-052/edge cases: secreto ausente (`tiktok_credential_missing`,
     sin afirmar revocación) ≠ credencial inválida según TikTok ≠ almacén inaccesible
     (`credential_store_unavailable`).
