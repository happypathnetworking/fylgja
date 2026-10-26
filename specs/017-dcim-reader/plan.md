# Implementation Plan: The Infrahub reader reads the schema library's DCIM

**Branch**: `017-dcim-reader` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/017-dcim-reader/spec.md`, the brief
([brief.md](brief.md)), the roadmap's [Release 0.3](../../docs/roadmap.md#release-03) and
[F-011](../../docs/roadmap.md#f-011), [D-002](../../docs/decisions.md#d-002) to
[D-004](../../docs/decisions.md#d-004), [D-010](../../docs/decisions.md#d-010),
[D-016](../../docs/decisions.md#d-016), [D-028](../../docs/decisions.md#d-028),
[D-031](../../docs/decisions.md#d-031), [D-044](../../docs/decisions.md#d-044),
[D-045](../../docs/decisions.md#d-045), [D-048](../../docs/decisions.md#d-048),
[D-054](../../docs/decisions.md#d-054) and Constitution 1.3.0. Research is in
[research.md](research.md) (§1 verified at this plan on a throwaway branch, §2 its
decisions R-01…R-22, §3 the decision entry D-057 and the constitution amendment 2.0.0
drafted for the operator, §4 owed at implement), the entities in
[data-model.md](data-model.md), the mapping, the formats and the surfaces in
[contracts/](contracts/), the migration's two verified documents in
[migration/](migration/), the validation in [quickstart.md](quickstart.md). The OpsMill
skill `infrahub-managing-schemas` was loaded for this plan, as asked (R-22).

## Summary

Release 0.3's first spec retires the generics contract: the CTM becomes the contract, and
the Infrahub reader becomes one adapter among the readers to come, reading OpsMill's
schema library's DCIM as it is at commit `26336e9` by one documented mapping
([contracts/mapping.md](contracts/mapping.md)). A twin is of a **scope**, `tag:<name>` on
each device, named by the request or by the server's `FYLGJA_DEFAULT_SCOPE`; inside it
the read is strict (no platform, an unmatched platform, a conformance gap, every finding
in one pass, no CTM), and at its boundary a cable the read cannot place is omitted and
recorded, never a refusal. Two queries read the scope: devices by tag, then physical ports
by device ids with the cable through each port's connector, since the library's nested
`interfaces` cannot be narrowed to a kind and its physical root takes the device one level
down (research §1.4, R-01). Conformance is a per-kind, per-field table against what
`GET /api/schema` reports for the pinned commit, choices and implementers included,
each finding naming the commit (R-02). Each support package declares the manufacturer and
platform pairs it is (`platform.matches`, format `0.7`), matched exactly (R-08). The CTM
moves to `2` (the platform a package, every interface a port, the envelope carrying the
scope, the mapping and the reader's fidelity list), the manifest to `5` (the list copied in
as `fidelity.read` by a compiler that holds no table of any source's rows), `twin.json` to
`8`; the API stays `1` (R-06, R-07, R-16). The stage reader's Infrahub-owned roots are
untouched; its stamps become each node's `node_metadata.updated_at`, which the probe found
is the latest stamp among a node's current attributes and relationship edges, or its
`created_at` when Infrahub's own account, the one that created the template query's
groups, wrote it last (D-058, D-060), so a device's
intent stamp covers every field of the device, its interfaces, its platform, its
manufacturer and its cables with one field per node, and its events count any write on
those nodes but Infrahub's churn (research §1.7, §1.8, R-10). The library is vendored
byte for byte under `schema/dcim/` with its licence; `-prepare-main` loads it on an empty
`main` and refuses one that holds any of its kinds; the development host's `main` is
migrated by two verified removal documents, in that order because one document naming the
generics and their implementers together is refused (research §1.9, R-13, R-14); the one
fixture branch is deleted and re-seeded in the library's kinds with the marker in
`description` (R-15). D-057 and Constitution 2.0.0 (research §3) are drafted for the
operator to accept at `analyze`.

Four things the plan found that the spec did not say, each verified live and decided here,
for `analyze` to settle:

- **The demo window is open on this host** (research §1.1): `main` holds the baseline and
  `fylgja-test-demo` an open proposed change. It must be closed with today's tree, before
  the fixture tool moves, by the operator (quickstart §0).
- **`stage list` needs a scope too** (R-04): the head's `at` is a stamps read, which is
  now the scope's, so the plan gives `stage list` and `stage.list` the `--scope` the spec's
  FR-017 lists for four other commands, rather than leave it refused `scope.unset` on a
  server with no default.
- **The one-document removal of the generics is refused** by Infrahub (research §1.9): the
  migration is two documents, implementers first, each about 50 s.
- **The template's import gates the fixture's re-seed** (R-14): with the library on `main`
  and the registration still rendering from the old query, nothing renders until the
  operator's push and import, so that gate sits before the re-seed and tier 2, not before
  tier 3 alone as FR-040 reads; tier 1 and the reader's code do not wait for it.

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled; YAML for the
vendored library (the library's own bytes), the packages and the migration documents;
JSON Schema 2020-12 for the moved contracts; Jinja2 and GraphQL for the template and its
query, read by Infrahub; Python for one identifier in the checks (R-20); bash for the
tier-3 script and the bring-up script; Markdown for the records.

**Primary Dependencies**: Infrahub 1.11.2 (`GET /api/schema?branch=` with inherited
members and `used_by`; the `DcimDevice` root's `tags__name__value` filter, the
`InterfacePhysical` root's `device__ids`; the `Edged*` wrappers' `node_metadata`;
`InfrahubEvent`; `POST /api/schema/load` with `state: absent`), the schema library at
`26336e9` (Apache 2.0, six files), `infrahub-sdk` 1.23.2's `infrahubctl` in `.venv` (the
migration's loads), `genqlient` (regenerated from the migrated `main`'s SDL), containerlab
0.79.0 and the Temporal Go SDK v1.49 (unchanged), cobra (`--scope`), the OpsMill skills
`infrahub-managing-schemas` (loaded here), `infrahub-managing-objects` (before the seed)
and `infrahub-managing-transforms` (before the template).

**Storage**: files only, as before (IX): the bundle store (bundle `5`), the twin directory
(`twin.json` `8`), Temporal history. Infrahub holds the library's kinds on `main` and the
fixture branch's objects; `BuiltinTag` is branch-aware (research §1.5). No database.

**Testing**: tier 1 (`make test`, under 45 s) over the moved CTMs and goldens, the
conformance table and every new finding against `httptest` answers shaped as research
§1.6, the stamps' and events' rules over faked answers, the package rules and the suite,
the API's `scope`, the record `8` and the frozen `7`, the manifest `5` and the frozen `4`,
the vendored files' SHA-256, the read-only test's new lists, the nine histories replaying
(quickstart §1); tier 2 (`make test-contract`) against the migrated Infrahub: the
re-seeded fixture reads to `three-node.json` but the envelope, the mixed fixture reads,
`schema check` on both and on a branch with `DcimCable` removed, the omitted cables and
the refused platforms on throwaway branches, `scope.empty`, every 014 and 015 test with
its assertions unchanged and SC-009's four edits (quickstart §7; about two minutes more
than today); tier 3's nine cases over the re-seeded fixtures with the marker in
`description` (quickstart §8; no new case).

**Target Platform**: the development host (Ubuntu 26.04.1; one Infrahub whose `main` is
migrated once, by hand, in a documented order; the demo window closed first) and CI's
`ubuntu-26.04` runner, whose fresh `main` takes the library through `-prepare-main` and
the merged template through the registration.

**Project Type**: a feature of an existing single-binary Go project with Infrahub-side
data (the vendored schema, a template and a query), a bash test tier and Markdown
records.

**Performance Goals**: a read of the fixture in two queries plus the artifacts, no slower
than today's three; the stamps read in two queries, each node one stamp; tier 1 under
45 s uncached; tier 2 within its 30 minute timeout; the migration's two loads about 50 s
each and the library's load about 30 s (research §1.2, §1.9).

**Constraints**: nothing added to the library or to anyone's model, the vendored files
byte-identical (SC-007); the reader's queries name no kind of the operator's model but
the four (FR-001); the compiler pure and the goldens re-baselined on their own commit (V,
FR-032); every approximation and omission a row (X, SC-003); no `at` of Fylgja's own
(VI); the API `1`; a session never pushes, so the template's import is the operator's
gate; no twin while tier 2 runs; the one fixture branch deleted and re-seeded, never
rebased (FR-039); the window closed before the fixture tool moves.

**Scale/Scope**: the reader rewritten (`internal/intent`: the queries, projection,
conformance, stamps and events, about 1,000 lines moved); the compiler and validation
thinned (about 200 lines gone); the CTM, manifest, record and package types and five
contracts moved, two frozen copies added; the server's scope plumbing (about 150 lines
across create, rehearse, read, stages, options, serve); the package rules and the suite's
two checks; the fixture tool and test support re-seeded (about 800 lines); the template,
the query and one identifier in the checks; `schema/dcim/` (six files, a licence, a
README) and the two migration documents; about sixteen records. The live parts (the
window's close, the migration, the push and import, the tiers) are the operator's or a
live session's.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 1.3.0 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. Everything that decides is Go in the one binary; the vendored library is embedded beside the stage kind (`embed.go`), as the generics were; the template and the query are Infrahub's to run, as before; the checks change one identifier and no runtime. No dependency is added. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness from the PSP | **PASS**. The package gains `platform.matches`, data (R-08); the reader picks the package by it and branches on nothing a package is; `TestCompilerNamesNoPlatform` holds; the mixed fixture reads and compiles as today. The compiler change (every interface a port) is a change of the contract, not of a platform's handling. |
| III | Queries only the Fylgja generics; never past a generic; least demanded; graduate-don't-gate; `iftype` is kind, `mgmt_only` is the use-flag; unimplemented `iftype` rejects; conformance and completeness checked separately | **VIOLATION, justified** (Complexity Tracking). The reader queries `DcimDevice` and `InterfacePhysical`, concrete kinds of a model Fylgja does not own, and `iftype` is gone: that is the feature, and the principle is rewritten by D-057 as 2.0.0 (research §3), which the operator accepts at `analyze` before the reader is built. What the rewrite keeps holds here: conformance and completeness are checked separately, every finding in one pass, no CTM on failure; the read-only test holds the list of kinds read; the reader reads the least possible (two queries, nothing the mapping does not name); wiring is derived by the compiler from `mgmt_only` and the links; every approximation is recorded. |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. The template is Infrahub's and renders ports from the library's kinds (R-11); the bootstrap is the package's and loses nothing but the loopback it never rendered; the artifact enters the bundle at read time as before. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. `Compile` copies the envelope's fidelity list and holds no table (`TestManifestCopiesTheFidelityList`); `TestCompilerIsPure` holds; the goldens move and are re-baselined on a commit of their own (FR-032); `twin compile` runs the goldens' path. |
| VI | Provenance recorded (branch, `at`, schema hash, contract version in the bundle; `observed_at` in the CTM envelope and `twin.json`, never in the bundle); `at` passed verbatim or not at all | **PASS, reworded by 2.0.0**. The provenance block carries branch, `at`, the schema hash, the scope and the mapping with its model version in place of the contract version (R-06, R-07); `observed_at` stays in the envelope and the record and out of the bundle; no `at` is composed, and the head's microsecond rule stands (research §1.7). |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. Untouched; the scope names which devices, not a second twin. |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS**. No workflow, activity or budget changes; the scope rides the inputs as data (`omitempty`), the nine histories replay. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. `twin.json` `8` carries the scope and the mapping; nothing else holds state. The library's kinds live in Infrahub, the operator's. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. The envelope's fidelity list and the manifest's `fidelity.read` carry every approximation and omission (three rows every read, one per omitted cable); each omitted cable is an `info` finding beside the read; sixteen identifiers added, eight retired, each with its severity, exit, step and object (R-21); the marker moves to `description` and the greps stand; no token reaches any output. |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `scope` is an argument of five operations; every scope refusal is the server's at `start`; the checks send none and are served under the default; the fixture tool and test support write the library's kinds as test code; `TestClientReachesTheCoreThroughTheAPIAlone` is unchanged. |

**Development Workflow gates**: three tiers (tier 2 against the migrated Infrahub, no
fake; tier 3 never in CI) **PASS**; verification just-in-time and recorded (research §1:
the library loaded, the schema endpoint's answers, the SDL's filters, the seed's rules, the
reads, the stamps, the events, the removal; §4 what is owed at implement) **PASS**;
documents (new glossary terms, the decision entry and the amendment drafted, the
architecture grepped for the generics at the close, the C4 model and the schema entity
diagram redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the generics contract (D-002).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None flagged.** The blessed "generics contract" layer leaves with D-057 and the
mapping takes its place (research §3.2).

**The OpsMill skill**: `infrahub-managing-schemas` was loaded at this plan (research
R-22). Followed: the running instance's own answers before anything is relied on; the
library loaded on a branch for the probe; `state: absent` for the removal, in the two
documents the checker accepts; the marketplace's files taken whole with provenance recorded
and never formatted. Departed from, as `CLAUDE.md` decides: nothing is inherited from or
extended, `infrahubctl` is `.venv/bin/infrahubctl`, and the library loads on `main`
(D-028). `infrahub-managing-objects` and `-transforms` are loaded at implement before the
seed and the template.

**Post-design re-check (after Phase 1)**: unchanged. The design moves the CTM (`2`), the
manifest (`5`), the record (`8`) and the package (`0.7`), adds the scope and sixteen
identifiers, and violates no gate but III, which D-057 rewrites. Four places where the
design departs from or refines the spec's text are the plan's to flag and `analyze`'s to
settle: the open window (research §1.1; a precondition the spec did not know); `stage
list`'s `--scope` (R-04; FR-017 names four commands); the migration as two documents
(R-14; FR-040 says "remove `main`'s generics and contract kind" as one step); and the
template's import as the gate before the re-seed and tier 2 (R-14; FR-040 says "before
tier 3"). Beside them, D-057 and Constitution 2.0.0 are `[operator]` tasks at `analyze`,
before the reader is built, and the window's close an `[operator]` task before the fixture
tool moves.

## Project Structure

### Documentation (this feature)

```text
specs/017-dcim-reader/
├── brief.md                 # the specify brief (committed)
├── spec.md                  # the specification, clarified
├── plan.md                  # this file
├── research.md              # §1 verified at plan (the host's state, the library on a branch, the schema endpoint, the SDL, the seed, the reads, the stamps, the events, the removal), §2 R-01…R-22, §3 D-057 and Constitution 2.0.0 drafted, §4 owed
├── data-model.md            # Phase 1: the scope, the CTM 2, the manifest 5 and record 8, the package 0.7, the conformance table, the read, the stamps and events, the findings, the server and API, the template, the schema directory, the fixtures, the migration
├── quickstart.md            # Phase 1: §0 the window closed, §1 tier 1, §2 the migration and the gate, §3–§6 by hand, §7 tier 2, §8 tier 3, §9 records
├── contracts/
│   ├── ctm.schema.json         # CTM 2, to land as contracts/ctm.schema.json
│   ├── mapping.md              # the one documented mapping: what is read and what it becomes, the queries, the conformance table, completeness, the omissions, the fidelity rows, the stamps and events
│   ├── scope-and-commands.md   # --scope, FYLGJA_DEFAULT_SCOPE, the API's argument, the identifiers, the text, twin step and the follow
│   ├── package-matches.md      # PSP 0.7: platform.matches, the rules, the registry, the suite, the fixtures
│   └── formats.md              # bundle 5, twin.json 8, the findings blocks, the frozen copies
├── migration/
│   ├── 1-reference-kinds-absent.yaml   # verified: the four Network* kinds and FylgjaContract
│   └── 2-generics-absent.yaml          # verified: the four generics, after the first
├── checklists/requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
schema/
├── dcim/                             # NEW: README.md (commit, SHA-256s, licence), LICENSE.txt, dcim.yml, ipam.yml, location.yml, organization.yml, cable.yml, location_minimal.yml (R-12)
├── fylgja-stage.yaml                 # stays
├── fylgja-generics.yaml, reference.yaml   # REMOVED
├── infrahub.graphql                  # regenerated from the migrated main (R-14 step 5)
└── README.md                         # rewritten: the mapping, schema check, a diverged DCIM, the reference transform
embed.go                              # schema/dcim/*.yml embedded
psp/
├── psp.schema.json                   # 0.7: platform.matches (R-08)
├── nokia_srlinux.yaml, arista_eos.yaml   # matches: Nokia / SR Linux; Arista / EOS
└── README.md                         # Format 0.7
testdata/
├── ctm/                              # every fixture moved to 2 (no lo0, no role, platform.package); defects: iftype-*, parent-missing, link-endpoint-loopback, mgmt-only-loopback REMOVED; version-1.json ADDED
├── golden/                           # the three goldens re-baselined on their own commit
└── psp/defects/                      # matches-missing.yaml, matches-shared.yaml, version-0-6-m11.yaml ADDED; heterogeneous and lossy packages gain matches
internal/ctm/
├── types.go, json.go                 # Envelope{Scope, Mapping, Fidelity}, Platform{Package, Version}, Interface without Iftype/Parent/Addresses; Version "2"; the constants (R-06)
└── testdata/contracts/017-dcim-reader/ctm.schema.json   # NEW: the frozen 1
internal/intent/
├── queries.graphql                   # Devices(tag), Ports(devices), ArtifactFields; IntentStamps, PortStamps; the stage reader's five unchanged (R-01, R-10)
├── mapping.go                        # NEW: the conformance table, the model and version constants (R-02)
├── conformance.go, schemainfo.go     # the table checked against the endpoint's attributes, relationships, choices and used_by
├── project.go, cable.go              # the two reads, the package match, the cable judgement, the fidelity list (R-03, R-05)
├── stamps.go, events.go              # node_metadata stamps per node; the intent kinds through used_by; the churn list (R-10)
├── summary.go, errors.go, client.go  # Config.Scope; the counts; the summary
├── readonly_test.go                  # the roots and the fragment targets held to the mapping's kinds
└── generated.go                      # regenerated
internal/validate/                    # the iftype, parent and endpoint-kind rules REMOVED; platform.package checked (R-09)
internal/compiler/
├── mapping.go, compile.go, disposition.go, manifest.go   # every interface a port; MappingRow without Iftype; Provenance{Scope, Mapping}; Fidelity.Read copied; BundleVersion "5" (R-07, R-09)
internal/bundle/                      # 5 accepted, 4 refused; testdata/contracts/017-dcim-reader/manifest.schema.json NEW (the frozen 4)
internal/psp/
├── types.go, consistency.go, load.go # Identity.Matches, Match; psp.matches.missing/duplicate; Registry.Match; Load refuses a shared pair; FormatVersion "0.7"
internal/conformance/pure.go          # CheckMatches; the set check
internal/stage/stage.go               # Read(…, scope, …); CheckContract REMOVED; ctm.version.unsupported at twin compile
internal/stages/                      # Stamper.Stamps(…, scope); DeviceStamps.Match through reg.Match in Stale; Plan/List/Resolve carry the scope
internal/findings/
├── finding.go                        # the identifiers of R-21
└── render.go, verify.go              # Subject.Scope; Verified{Model, Version, Kinds, Stages}; ShowRecord's provenance
internal/lab/
├── twin.go                           # TwinVersion "8"
├── wire/types.go                     # Provenance{Scope, Mapping}
└── testdata/contracts/015-proposed-change-rehearsal/twin.schema.json   # NEW: the frozen 7
internal/provision/types.go           # ProvisionInput.Scope, ReadIntentInput.Scope, ReconcileInput.Scope (omitempty); activities pass it
internal/api/wire.go                  # nothing new in the type; api.schema.json's args gain scope
internal/server/
├── scope.go                          # NEW: scopeOf, scope.invalid, scope.unset (R-04)
├── create.go, rehearse.go, read.go, stages.go, step.go, follow.go, show.go, schema.go, handlers.go, options.go, server.go   # the scope through every read; passedOver on scope.empty; the record line; the verified block
internal/cli/                         # --scope on create, rehearse, read, stage plan, stage list; twin show's line
cmd/fylgja/serve.go                   # FYLGJA_DEFAULT_SCOPE read, checked, reported
internal/testsupport/
├── seed.go, baseline.go, proposed.go, infrahub.go   # the seeds in the library's kinds; LoadSchema's two requests; MarkerDescription; SetDeviceDescription, SetDeviceSerial; the baseline in the library's kinds (R-15)
cmd/fylgja-fixture/main.go            # -set-description; -prepare-main's library gate (R-13); the flags over the library's kinds
infrahub/
├── queries/device_config.gql         # DcimDevice by name (R-11)
├── templates/device_config.j2        # the platform's name, physical ports, the header
└── checks/fylgja_api.py              # branch_point_refusal excuses scope.empty (R-20)
.infrahub.yml                         # the description
scripts/bring-up.sh                   # FYLGJA_DEFAULT_SCOPE scaffolded; -prepare-main's refusal read as present
scripts/e2e.sh                        # the marker in description; case 1 asserts the scope; case 5 passes --scope
.env.example, README.md, CLAUDE.md, SECURITY.md (no change expected),
contracts/{ctm,manifest,twin,psp,findings,show,verify,step,api}.schema.json, contracts/api.md, contracts/cli.md,
docs/architecture.md, docs/c4/workspace.dsl (+ make diagrams), docs/diagrams/ (the schema entity diagram), docs/glossary.md,
docs/development.md, docs/verified-facts.md, docs/roadmap.md, docs/brief.md, docs/decisions.md (the operator's D-057),
.specify/memory/constitution.md and .specify/templates/plan-template.md (the operator's 2.0.0)
```

**Structure Decision**: the mapping lives where the reader lives, `internal/intent`, as
the table (`mapping.go`) the conformance check reads and the two queries project from,
so one package knows the library's kinds and nothing else does (brief, "Nothing
Infrahub-shaped lives outside the reader"); the CTM package knows a package id and a
fidelity row and no kind; the compiler copies the list and knows no source. The scope's
resolution is one file in `internal/server`, called by every handler that reads, so the
two refusals are worded once. The vendored library is a directory of its own under
`schema/`, loaded by the same test-support function as the stage kind and embedded by the
same directive, so a fresh host and CI take it the way they took the generics. The
component changes are drawn in `docs/c4/workspace.dsl` (the artifacts repository renders
from the library's kinds; the schema is the vendored library and the stage kind; the
intent component reads by the mapping) and `make diagrams` redraws the views and the
schema entity diagram.

## Order of the work

0. **The operator's, before anything moves**: the demo window closed with today's tree
   (quickstart §0); D-057 and Constitution 2.0.0 accepted at `analyze`, before item 3.
1. **The formats and the pure code** (tier 1 alone): the package's `matches`, `0.7`, the
   two rules, the registry's `Match`, the suite's checks and fixtures; the CTM `2`, the
   compiler and validation without `iftype`, the moved fixture CTMs with their artifacts
   written from the new template by hand (R-11) and the goldens re-baselined on a commit of
   their own; the manifest `5`, the record `8`, the frozen copies; the identifiers; the
   contracts. Checkpoint: `make test` and `make lint` green.
2. **The schema directory, the template, the fixture tool and the migration documents**:
   `schema/dcim/` with its README and the SHA-256 test; `embed.go`; the query, the
   template and `.infrahub.yml` (the transforms skill loaded first) and the checks' one
   identifier; test support's seeds and helpers (the objects skill loaded first);
   `-prepare-main`'s gate; `-set-description`; the bring-up script and `.env.example`.
   Checkpoint: `make test`, `make lint`.
3. **The reader** (needs D-057): the typed client regenerated from a throwaway branch's
   SDL that carries the library (R-14 step 5's interim); `mapping.go`; the conformance
   table; the two reads, the cable judgement, the fidelity list, the completeness
   findings; the stamps and the events; the read-only test's lists; `stage.Read` with the
   scope. Checkpoint: `make test` with the `httptest` cases of quickstart §1.
4. **The scope through the server, the API and the client**: `FYLGJA_DEFAULT_SCOPE`,
   `scopeOf`, the five operations' argument, `--scope`, the record line, `schema check`'s
   lines and block, `passedOver` on `scope.empty`, the wire inputs. Checkpoint: `make
   test`, `make lint`, the harness over every refusal before any connection.
5. **The host, live** (quickstart §2): the migration's two documents on `main`,
   `-prepare-main`, the operator's push of the template commit and the session's import,
   the fixture re-seeded, `make sdl` and `make generate` from the migrated `main`,
   committed; the worker and the server restarted and verified. Then quickstart §3–§6 by
   hand. The session's, but for the push.
6. **Tier 2** (quickstart §7), then **tier 3** whole and narrowed (quickstart §8). Live;
   the session's.
7. **The records at the close** (R-19): architecture (grepped for the generics), the C4
   model and the schema entity diagram, glossary, development.md, verified-facts.md
   (research §1 and §5), roadmap (F-011 built), `docs/brief.md`, README, `CLAUDE.md`'s
   Environment, Formats and State with the new hashes and the fixture's id, `cli.md` and
   `api.md`, the schema and package READMEs, `.env.example` re-read; D-057 appended and the
   constitution amended by the operator.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| III: the reader queries concrete kinds of a model Fylgja does not own (`DcimDevice`, `InterfacePhysical`), and `iftype` is gone | The feature itself (F-011): with NetBox read directly in this release, every reader is an adapter onto a fixed model, and the generics made the Infrahub reader the odd one out; the library would not inherit the generics without adapting one side or the other (verified 2026-10-16). D-057 supersedes D-002, D-003 and D-004 and rewrites the principle as 2.0.0 (research §3), keeping what still holds: conformance and completeness separate, one pass, no CTM on failure, the read-only test's list, the least read, wiring derived in the compiler, every approximation recorded | A layer-1 generics contract carried into the library by an overlay: still something every user loads, and nothing NetBox can load (rejected by the operator on 2026-10-25). A mapping declared as data per install: D-002's "mini-ETL language", now for two sources |
