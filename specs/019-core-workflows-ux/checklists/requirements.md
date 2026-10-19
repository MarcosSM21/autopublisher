# Specification Quality Checklist: Core Workflows UX Redesign

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-18
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

## Critical review (feature input §35)

- [x] Publish is one task even though Drafts are created at Continue (FR-017, FR-030)
- [x] Resume never invents "common content" (FR-031–FR-034)
- [x] New drafts store an explicit snapshot (FR-028, R1)
- [x] Schedule implies auto-publish (FR-049, FR-072, R4)
- [x] `Finish later` does not pretend to save what is already saved (FR-050, FR-051)
- [x] Single TikTok declaration in the new flow (FR-047, R5)
- [x] Posts uses visible semantics, not raw status (FR-061, FR-083, FR-084)
- [x] Missed is never hidden (FR-056, FR-069, FR-083)
- [x] Failed can be rescheduled only without uncertainty (FR-073, R6)
- [x] Published shows what was actually sent (FR-074)
- [x] Calendar stays read-only (FR-066)
- [x] Feature 020 and Republish stay out (Out of Scope)

## Notes

- Mentions of existing routes, `DetailSurface`, display state, publish-check and existing
  read-models are references to capabilities already defined by previous specs (018/017),
  not new implementation decisions.
- Deliberate refinements of earlier specs are documented in the R1–R10 table; R6 is the only
  functional lifecycle change.
- Review 2026-10-18: R11 removed (Reactivate keeps existing rules); added reload-stable Publish
  set identity (FR-031a), partial Schedule failure (FR-052a), mandatory bottom-nav hiding in
  mobile Publish (FR-018), per-type Calendar anchors (FR-069), paused action alignment (FR-071).
