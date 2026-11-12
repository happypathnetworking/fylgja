# Fylgja Constitution

Fylgja builds a twin of a network, wired as a blueprint of intent says, on a runtime: network
operating system images in containers on one host or a cluster, and later real hardware. It
is three pieces. The **core** turns a blueprint into a named twin, and steps, verifies,
shows and destroys it. A **reader** turns one source of truth into blueprints. The
**example orchestrator** resolves stages, rehearses changes, and drives the core through its
API, as an integrator's own platform would. This document holds the
non-negotiables; the reasons are in `design/decisions.md`.

## Principles

### I. One Language, Typed
Every piece MUST be Python, with strict type checking, one toolchain and one test
framework. They MUST share one model package for every format two of them read. The core's
critical path MUST have no second language runtime besides the twin runtimes its drivers
drive. The example orchestrator MAY call a tool in another language; the core MUST NOT link
one.
*Rationale: [D-001](decisions.md#d-001), [D-081](decisions.md#d-081).*

### II. Platforms Are Data, Never Code
A platform MUST be added by writing a platform package, and a probe format by writing a probe
package, and nothing else. A package MUST state only what the runtime does not already know:
where a runtime's kind provides interface aliases, default logins or default configuration,
they are the kind's. What differs by runtime lives in the package's section for that runtime.
A platform is supported only when its package passes the conformance suite. No component MAY
branch on a vendor or a format, and a twin MAY mix vendors.
*Rationale: [D-013](decisions.md#d-013), [D-014](decisions.md#d-014), [D-008](decisions.md#d-008), [D-015](decisions.md#d-015).*

### III. The Blueprint Is the Contract
The core's one input MUST be a blueprint: the network and its probes. A reader MUST:
- map one source by one documented mapping;
- record every approximation and omission it makes;
- report every finding in one pass;
- produce no blueprint on failure.

Nothing in the core MAY know a source, a branch, a stage or a proposed change. What a reader
may read of its source is that adapter's documented mapping, not this document.
*Rationale: [D-006](decisions.md#d-006), [D-003](decisions.md#d-003).*

### IV. Fylgja Never Renders Configuration
The core MUST push exactly the configuration the source rendered. Fylgja adds no
configuration of its own: a node starts from its runtime's baseline (a kind's default
configuration, or a device's stored baseline), and nothing is ever derived from intent.
*Rationale: [D-007](decisions.md#d-007), [D-015](decisions.md#d-015).*

### V. The Compiler Is Pure; Identity Is Content
The compiler MUST be a function from a blueprint and packages to a bundle, with no I/O, clock
or environment, enforced by a test. A blueprint's id and a bundle's id MUST be SHA-256 over
canonical bytes, RFC 8785 for JSON. A bundle MUST be runtime-neutral and carry nothing that
belongs to one twin. A driver's `plan`, pure as the compiler is, MUST be the only step that
binds a bundle to a twin and a runtime. Fidelity is computed per deployment, beside the
bundle, and is never hashed into it.
*Rationale: [D-006](decisions.md#d-006), [D-011](decisions.md#d-011).*

### VI. Intent Is Addressed
A blueprint's id MUST address intent alone. Where it came from (source, branch, point in time,
scope, mapping, when it was read) MUST travel with it as a source envelope. The core stores
and returns that envelope and never interprets or hashes it.
*Rationale: [D-006](decisions.md#d-006).*

### VII. Twins Are Named and Isolated
Every twin MUST have a name and its own isolation unit, as its driver provides one: a lab, a
namespace or a reservation. Twins MUST share nothing mutable. Every resource a twin uses MUST
be labelled as its own and removed with it, so that an orphan can always be found. A twin
that cannot fit MUST be refused at admission, with the reason.
*Rationale: [D-019](decisions.md#d-019).*

### VIII. Reconcile to Desired State
A twin MUST be a record whose desired state is a bundle. The core's own loop reconciles it
idempotently through its driver, the same way on every runtime. Every phase MUST be recorded
before the next begins, so that a restarted core resumes. Cleanup MUST run on every failure
and deletion path. Every long operation MUST be a run with an id that can be read and
cancelled.
*Rationale: [D-023](decisions.md#d-023).*

### IX. State Lives Behind One Store; No Database
Twin records, runs and their events, blueprints and bundles MUST live behind one store
interface: a directory in development, object storage in production. Blueprints and bundles
are kept by id and never overwritten. A twin record changes only by compare-and-set. No
piece introduces a database without a decision naming the question only a database can
answer.
*Rationale: [D-024](decisions.md#d-024), [D-023](decisions.md#d-023).*

### X. Report Honestly
Every compile MUST report fidelity: what is modelled, approximated, synthesized or omitted,
and why. Fidelity is asserted, not measured, and every surface that reports it MUST say so.
Every finding and refusal MUST have a stable identifier.

No credential MAY appear in a blueprint, bundle, record, finding or log. Credentials come only
from one credential provider: the environment locally, Secrets on a cluster. Every change to
a twin MUST be attributable to a principal.
*Rationale: [D-012](decisions.md#d-012), [D-011](decisions.md#d-011), [D-025](decisions.md#d-025).*

### XI. The API Is the Boundary
Every client MUST reach the core through its API alone: the CLI, the orchestrator, a web UI,
an agent. The store and the runtime's resources are the core's internals, and clients MUST
NOT write them. Every request MUST carry a principal. A malformed or refused request MUST be
answered with a problem document, and a verdict with findings. The API returns documents, and
clients render them. A test over imports MUST hold the boundary.
*Rationale: [D-025](decisions.md#d-025), [D-003](decisions.md#d-003).*

### XII. Every Field Earns Its Place
Every field in a format MUST have a consumer outside its own tests. Each fact MUST be stored
once and referenced elsewhere. Each format MUST have one current version, specified by one
current-state document. A compatibility reader or a frozen copy returns only through a
decision.
*Rationale: [D-002](decisions.md#d-002).*

### XIII. Runtimes Are Drivers
A runtime MUST be added by writing a driver behind the seam (`capabilities`, `admit`, `plan`,
`apply`, `inspect`, `destroy`, `endpoints`) and nothing else. `admit` reserves what a twin is
bound to, or refuses it; `plan` binds it, purely. Nothing above the seam MAY branch on
which runtime a twin runs on; it MAY branch on a declared capability. Every driver MUST pass
the driver conformance suite. A local driver MUST stay sufficient for development and for the
live tier, so that neither needs Kubernetes.
*Rationale: [D-017](decisions.md#d-017), [D-022](decisions.md#d-022).*

## Gates

A plan's check MUST cite the principle for each gate it passes or justifies.

- **Blessed**, never flagged as extra layers:
  - the blueprint and its model package
  - platform and probe packages
  - one documented mapping per source
  - the driver seam
  - a driver's pure `plan` as the one binding of a bundle to a twin and a runtime
- **Flagged**, each returning only through a decision:
  - a database
  - any other binding at deploy
  - a field with no consumer
  - a fact stored twice
  - a second representation of a document
  - a client path besides the API
  - shared mutable state between twins
  - code above the seam that names a runtime
  - a development step that needs Kubernetes

## Development

- **Tiers.**
  - **Pure tests** gate every PR and need no infrastructure: the model, the compiler, every
    driver's `plan`, and the packages.
  - **Contract tests** run against real systems, never fakes: Infrahub for its reader and
    for the example orchestrator.
  - **Live tests** on booted images run on demand on the local driver.
  - **The driver conformance suite** runs on each driver's own runtime, a cluster for
    clabernetes.
- **Verification.** How an external system behaves is verified against the running system
  before code depends on it, and recorded in `design/verified-facts.md` with its version and
  date.
- **Process.** A design document, then a decision entry where a decision changes, then a PR.
  A new term goes in `docs/glossary.md` in the same change.

## Governance

- This constitution supersedes all other practices.
- A decision changes only by a superseding entry in the append-only `design/decisions.md`.
  This constitution is then amended citing that entry, and `design/architecture.md` is
  searched for the old position.
- Versioning follows semver: MAJOR when a principle is removed or redefined, MINOR when one
  is added or materially expanded, PATCH for wording.
- The amendment history lives in git, not in this file.

**Version**: 1.1.0 | **Ratified**: 2026-10-31 | **Last Amended**: 2026-11-09
