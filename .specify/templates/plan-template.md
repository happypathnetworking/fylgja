# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 1.1.1 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness from the PSP | |
| III | Queries only the Fylgja generics; never past a generic; least demanded; graduate-don't-gate; `iftype` is kind, `mgmt_only` is the use-flag; unimplemented `iftype` rejects; conformance and completeness checked separately | |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | |
| VI | Provenance recorded (branch, `at`, schema hash, contract version in the bundle; `observed_at` in the CTM envelope and `twin.json`, never in the bundle); `at` passed verbatim or not at all | |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | |

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the generics contract (D-002).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040).

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
