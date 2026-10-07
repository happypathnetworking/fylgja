<!--
Sync Impact Report
- Version change: 1.1.0 → 1.1.1 (2026-10-06, PATCH, wording only: no principle
  added, removed or redefined). Development Workflow's Documents gate says that this
  repository's decision log begins at its first commit, and that earlier decisions are
  restated there as in force, without the record that produced them, which is private.
  Source: D-043 and D-044, the decisions this repository began with. Templates:
  .specify/templates/plan-template.md's Constitution Check names 1.1.1.
-->

# Fylgja Constitution

Fylgja reads network intent from Infrahub and builds a walking twin of it: a running
virtual topology on real network operating system images, built from one branch at an
optional point in time, provisioned durably through Temporal, one twin at a time. This
document holds the non-negotiables. The reasoning behind each lives in
`docs/architecture.md` and the decision log in `docs/decisions.md`; the constitution cites
them and does not restate them.

## Core Principles

### I. Go, End to End
Fylgja MUST be a single-language Go system: one toolchain, one test framework, one
static binary that is CLI, worker and API server. There MUST be no second runtime in the
critical path. Where a dependency choice affects the static binary, the pure-Go option
MUST be chosen. Platform support packages and the schema MUST be embedded in the binary
with a runtime override directory. CLI parsing, where a platform requires it, is a Go
TextFSM implementation over vendored templates.
*Rationale: D-005, D-018, D-040.*

### II. Platforms Are Data, Never Code
A platform MUST be added by writing a Platform Support Package (`psp/`) and nothing
else. A platform is "supported" only when its PSP passes the conformance suite. If a
new platform requires a compiler change, the abstraction is wrong and the change MUST
be rejected until the abstraction is fixed. A single twin is heterogeneous: no
component MAY assume all nodes share a vendor. Budgets, timeouts and readiness MUST
come from the PSP, never from a global constant.
*Rationale: D-016, D-021.*

### III. The Generics Are the Contract
Fylgja MUST query only its own Infrahub generics (`schema/`). Specifically:
- MUST NOT reach past a generic to a concrete kind.
- MUST demand the least possible; every required attribute is a constraint imposed on
  someone else's model.
- MUST graduate, not gate: optional generics unlock features; when absent, dependent
  behaviour skips with a recorded reason.
- MUST NOT claim a name that carries established operational meaning unless the same
  meaning is intended, and MUST check candidate names against Infrahub's reserved
  names before deciding.
- Wiring behaviour MUST be derived from `iftype` and `mgmt_only` by the compiler,
  never declared in the schema. `iftype` is kind only.
- An unimplemented `iftype` value MUST be an explicit compile-time rejection, never a
  silent fall-through.
- MUST reserve only structure that is confidently known; MUST NOT reserve structure
  that is a guess.
- MUST validate schema conformance and data completeness separately, report all
  findings in one pass, and produce no CTM on failure.
*Rationale: D-002, D-003, D-004.*

### IV. Fylgja Never Renders Configuration
Fylgja MUST consume the artifacts Infrahub renders for the branch under test and push
exactly those. The only per-node file Fylgja emits is bootstrap — hostname, cabled
ports enabled, discovery on — templated from the PSP, never from intent, carrying no
addresses. A Fylgja-owned template that produces anything else is a defect.
*Rationale: D-009.*

### V. The Compiler Is a Pure Function and the Bundle Is Deployable as Emitted
The compiler MUST take a CTM and PSPs as input and produce a bundle as output with no
I/O, no clock and no environment, enforced by a test. The bundle MUST be deterministic
(same input, byte-identical output, stable ordering everywhere), self-describing,
content-addressed by the hash of its canonical bytes, and deployable without a further
binding step: the compiler writes the fixed lab name and relies on containerlab's
default management network. The compile that `fylgja twin compile` asks for MUST run the
identical code path as the golden tests; if they diverge, one of them is lying and the
divergence is a defect.
Synthesized nodes MUST be added to the CTM before compilation, never looked up by the
compiler.
*Rationale: D-010, D-011, D-040.*

### VI. Intent Is Addressed
Every CTM and bundle MUST record its provenance: branch, `at` if supplied, the schema
hash Infrahub reports, and the contract version. `observed_at`, the UTC time the read
began, MUST be recorded on every read, pinned or not, in the CTM and in the twin
directory, and MUST NOT appear in the bundle, so that the same intent hashes the same
whenever it was read. When the operator supplies `at`, it MUST be passed verbatim on
every query of the read. When the operator does not, Fylgja MUST NOT send an `at` of
its own; `observed_at` is then the only record of when the intent was seen. It is
informational in every case, governs nothing when `at` is supplied, and any claim of
reproducibility from it MUST say best-effort.
*Rationale: D-001, D-012, D-023.*

### VII. One Twin at a Time
Fylgja MUST refuse to create a twin while lab `fylgja` exists on the host, stating
why and how to clear it. The lab name MUST be `fylgja`, written by the compiler.
Orphan labs MUST be detected at `create` and at worker start and MUST be clearable by
`fylgja twin destroy` whether or not a twin directory exists. Nothing MAY allocate or
name resources per twin.
*Rationale: D-013.*

### VIII. Temporal Runs Short, Idempotent Provisioning
Provisioning MUST be a Temporal workflow with a fixed ID that runs to a ready twin or
cleans up; destroy MUST be a second workflow with a fixed ID. Workflow code MUST be
deterministic: no I/O, no wall clock, no randomness. Every activity MUST be idempotent,
MUST pass paths and hashes rather than bundle bytes, and, if it can run for minutes,
MUST heartbeat under a budget from the PSP. Cleanup MUST run on a disconnected context
from every failure and cancellation path. There MUST be one task queue until the host
move, and everything that must run on the lab host MUST live in `internal/lab`. A
long-running workflow, a signal, a TTL, or a second task queue MUST NOT be introduced
without a decision-log entry.
*Rationale: D-006, D-007, D-015.*

### IX. State Lives in containerlab and Files; No Database
Whether the twin exists is what containerlab reports. Its provenance is the manifest
staged in the twin directory beside it. Every compiled bundle MUST be kept in the
bundle store by hash, behind an interface small enough to be replaced by object
storage. Temporal holds run history. Fylgja MUST NOT introduce a database without a
decision-log entry naming the question only a database can answer.
*Rationale: D-014.*

### X. Report Honestly
Every bundle MUST carry a fidelity manifest — modelled exactly, approximated,
stubbed, omitted; software- versus hardware-forwarding per platform; every synthesized
node; every omission with its reason. Skips and omissions MUST be recorded, never
silent. Every finding, rejection and skip MUST have a stable identifier. Fidelity is
asserted, not measured, and every surface that reports it MUST say so. No credential
MAY appear in a bundle, a finding, or a log line; credentials come from the process
environment only and are never persisted.
*Rationale: D-022, D-017.*

### XI. The API Is the Boundary
A user-facing client MUST reach Fylgja's core through the API alone. The CLI is a
client, and so is every later one: a web UI, an agent surface, a check running inside
Infrahub. A client MUST NOT import, link or run the core by any other path, and no
command of the CLI runs the core in its own process: the binary's roles, `serve` and
`worker run`, are the core and not clients. Every refusal that concerns intent, a twin,
a bundle or the host MUST be the server's, so that every client is refused alike. The
API's payloads MUST be the documents Fylgja already versions, never a second
representation. Test code and test tools MAY call the core directly and MAY read the
nodes, the containers and the record on their own; a shipped client MUST NOT carry a
second path for them. The boundary MUST be held by a test over imports.
*Rationale: D-040.*

## Constitution Check — Gate Adjustments

The default simplicity / single-data-model gate MUST NOT flag the following three
layers. Each is blessed with its justification:

- **The CTM (Canonical Topology Model).** Synthesized nodes are not in Infrahub and
  cannot live in types generated from Infrahub; something Infrahub does not own must
  be the compiler's input. The CTM MUST stay a near-copy of the generated types until
  a synthesized node needs more. *(D-010)*
- **The Platform Support Package abstraction.** Required by Principle II. *(D-016)*
- **The generics contract.** Required by Principle III. *(D-002)*

Conversely, the gate MUST flag any plan that introduces a binding stage, a database, a
long-running workflow, or per-twin resources; each of those was considered and
rejected (D-011, D-014, D-007, D-013) and returns only through a new decision. It MUST
also flag a user-facing client that reaches the core by any path but the API, and a
direct mode for tests in a shipped client (D-040).

## Development Workflow

Detail lives in `docs/development.md`; these are the gates.

- **Three test tiers.** Pure, golden-file and Temporal test-suite tests run on every
  PR and need no infrastructure. Contract tests run against a real Infrahub with the
  reference schema loaded — a fake Infrahub MUST NOT be used. End-to-end tests with a
  booted NOS run on demand and MUST NOT gate a PR. *(D-017)*
- **Verification is just-in-time and recorded.** Before an implementation task
  depends on how Infrahub, containerlab or Temporal behaves, the behaviour MUST be
  verified against the running system and recorded in the feature's `research.md`.
- **Repository.** Single Go module, one binary, `internal/lab` as the host-bound
  boundary. *(D-018, D-015)*
- **CLI.** Noun-verb; `fylgja twin create` is the front door; every stage is exposed
  on the same code path as its tests. From M13 the CLI is the API's client, and each
  stage runs in the server. *(D-019, D-040)*
- **Documents.** A new term goes in the glossary, a changed decision in the decision
  log, in the same change. The decision log is append-only, and this repository's log
  begins at its first commit: earlier decisions are restated there as in force, without
  the record that produced them, which is private (D-043).

## Governance

- This constitution supersedes all other practices. Every plan's Constitution Check
  MUST cite the principle number for each gate it passes or justifies.
- A decision changes only via a new entry in `docs/decisions.md` that supersedes the
  old one; the constitution is then amended citing that entry. When a decision
  changes, `docs/architecture.md` MUST be searched for the old position before the change
  is considered complete — prose lags decisions.
- Versioning follows semver: MAJOR for a principle removed or redefined; MINOR for a
  principle added or materially expanded; PATCH for wording and clarification.
- **Ratification.** This file, `.specify/memory/constitution.md`, is the binding
  constitution; Spec Kit reads it here. Every decision it cites is *Accepted* in
  `docs/decisions.md`. A change to any cited decision requires a superseding entry
  there and an amendment here, with a version bump per the rule above. The draft that
  preceded 1.0.0 at the repository root is retired and MUST NOT be edited in its
  place.

**Version**: 1.1.1 | **Ratified**: 2026-09-14 | **Last Amended**: 2026-10-06
