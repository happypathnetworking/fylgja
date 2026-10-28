# Specification Quality Checklist: Probes

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-28
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

- Validated on 2026-10-28 at `specify`, one pass, headless: the brief's Open section is
  empty, so no clarification marker was written and none remains.
- **Implementation details**: the spec names contracts, formats and their versions
  (snapshot `2`, bundle `6`, `probes.schema.json`), the fixture's test files, the Infrahub
  kind `FylgjaProbe`, the template and the three test tiers, because each is a deliverable
  the brief and the roadmap name and the operator sees, as 017's, 018's and 019's specs
  name theirs; no language, library, package path, function or mechanism is named. The
  `linux` containerlab kind is named because the roadmap's F-014 and the brief's Decided
  list fix it as the operator's choice, not as a design.
- **Testable**: every requirement has a tier-1, tier-2 or tier-3 case in a story's
  Independent Test or acceptance scenarios, or a grep over the tree (FR-027, FR-028).
- **Left to the plan**: FR-017's handling of a dropped host, a cancellation and a flow that
  fails to start; whether a snapshot `1` on disk reads as a `2` (US7 scenario 1); the
  kind's exact shape; the Constitution Check's answer on a fourth blessed layer; the
  assertion kind's name and rule id; the burst's budget; and the estimate. Each is a
  decision the brief leaves to the plan, listed under Assumptions, not an ambiguity in
  what the operator gets.
- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
