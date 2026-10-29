# Implementation Plan: Probes

**Branch**: `016-probes` | **Date**: 2026-10-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/016-probes/spec.md`, the brief
([brief.md](brief.md)), the roadmap's [Release 0.3](../../docs/roadmap.md#release-03) and
[F-014](../../docs/roadmap.md#f-014), [D-010](../../docs/decisions.md#d-010),
[D-022](../../docs/decisions.md#d-022), [D-028](../../docs/decisions.md#d-028),
[D-031](../../docs/decisions.md#d-031), [D-038](../../docs/decisions.md#d-038),
[D-039](../../docs/decisions.md#d-039), [D-045](../../docs/decisions.md#d-045),
[D-057](../../docs/decisions.md#d-057), [D-061](../../docs/decisions.md#d-061),
[D-062](../../docs/decisions.md#d-062) and Constitution 2.2.0. Research is in
[research.md](research.md) (§1 verified at this plan on the host and in the tree, §2 its
decisions R-01…R-30, §3 D-064 and a constitution amendment drafted for the operator, §4
owed at implement); the entities and where each changes in [data-model.md](data-model.md);
the commands and the formats in [contracts/](contracts/); the validation in
[quickstart.md](quickstart.md). The OpsMill skill `infrahub-managing-schemas` was loaded
before the kind's shape was settled (R-07); `-objects` and `-transforms` are implement's,
before the README's object file and the template are edited (research §4).

## Summary

Release 0.3's fourth spec fills the snapshot's probe slot. A **probe declaration** is a
JSON file of its own (`probes.schema.json`, version `1`): each probe a name, the format
`ping` and two endpoints, each a device, an interface, the host's address with its prefix
length and its gateway (R-04). The same declaration lives in Infrahub as **`FylgjaProbe`**,
one object per probe, eight text attributes for the two endpoints, branch-agnostic on
`main` beside `FylgjaStage` (R-07). Every command that takes a snapshot from intent gains
`--probes <file>`, which the client reads and sends as a file beside the request; with no
file the server reads the kind on `main` once per request, unpinned; with neither the list
is empty (R-06). The snapshot moves to **`2`**, its `probes` the contract's elements,
hashed as today; a `1` on disk is read as a `2` with no probes, since the version is not
hashed and the two bodies share one id (R-05).

The compile takes the snapshot's body: a step before the compile proper adds one
synthesized `linux` host per endpoint to the in-memory CTM, with its link to the device
interface, under provenance `synthesized`, and refuses a probe it cannot place by one rule
set that validation and the compiler share (R-01, R-02, R-09). The bundle moves to **`6`**:
a host node's topology entry carries the **`ping` probe package's** kind, image and `exec`
lines for its address and its route; the manifest marks every synthesized node, link and
row, carries a `probes` block and `fidelity.synthesized`, and writes `provenance` only
where it is not `intent`, so a probe-less snapshot compiles to its bundle `5` but for the
version and two empty lists (R-10, R-11). The probe package is a second package kind
beside the PSP, `probes/ping.yaml` at format `0.1`, embedded and overridable from the
PSP override directory's `probes/` subdirectory (R-08); the host check verifies its image
present whatever its acquisition (R-12).

The step gains two activities, **`StartFlows`** after the stage and **`ReadFlows`** after
the wait, so the worker serves four workflows and **seventeen** activities (R-13, R-14):
each flow is busybox `ping` at the package's interval, started inside the host by `docker
exec` and read by an interrupt and its summary; the step's document and `twin.json` (now
**`11`**) carry each probe's packets sent, lost and longest gap under `basis: container`,
never asserted. Verify derives a fourth assertion kind, **`burst`**, one per probe: a short
`ping -c N` from the first host to the second that must get every reply, read by the worker
in the wait and by the server in `twin verify` (R-15, R-16); its failure fails a stage
through 015's unchanged gate. The report's table gains `loss` between `verify` and `new
verification failures` (R-17). Infrahub's reference template renders each physical port's
addresses on both platforms, and the fixture's devices each gain **two** uncabled addressed
ports, since the reference transform renders no routing and a probe that needs only
connected routes lies across one device (R-18, R-19): the demo probe of tier 3 is
same-device, a choice confirmed at `analyze` on 2026-10-28 and written into the spec (R-30).

Verified at this plan (research §1): busybox `ping` and `ip` as the mechanism needs them,
on the host's Docker; containerlab 0.79.0's dry run of a `linux` node with `exec` beside SR
Linux; the kinds, fields and queries the read adds to; the activity, version and deadline
constants the counts move from. Not verified, because this session boots nothing and
pulls nothing: the image's pull, a host booting beside SR Linux, the template's lines on
either image, and the kind's load on `main`, each owed at implement (§4).

Settled by this plan where the spec left the point to it, each recorded in the spec's
Clarifications (R-30): where the hosts enter the compile; a snapshot `1` read as a `2`;
the kind's flat shape; the `flows` phase and the per-probe outcomes; a host the target
drops torn down with no flow, listed `dropped`; two hosts with one address refused; the burst's name
`burst` and its rule `verify.burst`; the host check's presence rule for a probe image; and
**two** probe-ready ports per fixture device with tier 3's probe on one device, in place
of FR-024's one and US1's "through the two devices". One decision entry, D-064, and a
MINOR constitution amendment (2.3.0) are drafted (research §3).

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled; JSON Schema
2020-12 for the two new and six moved schemas; YAML for the probe package and the kind;
Jinja2 and GraphQL for the template; bash for tier 3. No dependency added: the YAML
decoder, the JSON Schema validator, the Temporal SDK and `docker` on the `PATH` are all
there (research §1.4).

**Primary Dependencies**: Infrahub 1.11.2 (the kind on `main`, the template rendered by
its task workers); containerlab 0.79.0 (`linux` kind, `exec`); Docker 29.8.1 (`docker
exec` into the hosts, `docker image inspect`); Temporal Go SDK v1.49 (two activities
added); busybox 1.37.0 in `alpine:3.24.2`, the `ping` package's image.

**Storage**: files only (IX): the snapshot store (`2`), the bundle store (`6`), the twin
directory (`twin.json` `11`), Temporal history. No database, no Schedule.

**Testing**: tier 1 (`make test`, under 45 s; quickstart §1): the compile with and without
probes, every placement refusal, the declaration's rules, the package's schema, the
activities' names and counts, the parse of ping's output, the derivation and the report's
column, the frozen copies and the replays. Tier 2 (`make test-contract`; §6): the kind on
`main`, a probe read into a take, replaced by a file, deleted; the artifact's lines once
the template is imported. Tier 3 (`make test-e2e`; §7): nine cases, probes in 5, 8 and 9.

**Target Platform**: the development host (Ubuntu 26.04.1) and CI's runner for tiers 1–2.

**Project Type**: a feature of the existing single-binary Go project: one new package
(`internal/probe`), one new package kind (`probes/`), one new Infrahub kind, two
activities, six formats moved, two new contracts.

**Performance Goals**: tier 1 under 45 s (about 1,500 lines of tests added; measured at
the close, the budget raised with the figure if it does not hold, SC-009); tier 2 longer
by the kind's test (about 1 minute); tier 3 about 34 minutes, about 2 more than today, for
the probe hosts in three cases and a longer case 9 (R-25). A step's measurement costs two
activities of under a second each; a burst costs about 3 s per probe per read.

**Constraints**: CTM `2`, PSP `0.7`, the mapping, the reader and the schema library's files
unchanged (D-057); the API and findings at `1`; four workflows; every refusal the
server's (XI); the compiler pure and free of any platform or format literal (V, D-031);
`fylgja-twin`'s `timeout` 4,260 unmoved and the rehearsal's deadline inside it; no twin
while tier 2 runs; a session never pushes; the template reaches Infrahub only by the
operator's push and import.

**Scale/Scope**: about 4,500 lines added and 400 changed (R-29): `internal/probe` (new,
about 900 with tests), `internal/compiler` (the synthesis, the manifest, the goldens),
`internal/snapshot` (`2`), `internal/intent` (the kind's read), `internal/server` (the
takes, the files, verify's bursts), `internal/cli` (the flag), `internal/lab` (the
activities, the host check, the record, the burster), `internal/provision` (the step's two
activities, the deadline), `internal/verify` (the kind), `internal/rehearsal` (the column),
`internal/findings` (the rules and blocks), `internal/testsupport` and the fixture tool,
`infrahub/` (the query and the template), `schema/fylgja-probe.yaml`, `probes/`, eight
schemas and six frozen copies, `scripts/e2e.sh`, about twenty records. Re-estimated at
**14–20 hours** of sessions plus the tiers (R-29), against the roadmap's 5–7.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 2.2.0 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. The probe packages are embedded as the PSPs are, with the same override mechanism (R-08); the mechanism is Go driving `docker exec`, which the worker and the server already have on their `PATH`. The template is Infrahub's Jinja2, not a runtime of Fylgja's. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness and the manufacturer and platform pairs from the PSP | **PASS, with the amendment drafted** (research §3.2). No platform package or compiler branch moves for a platform. The host is reached by the probe package's format value and its `clab_kind`, image, `exec` templates, readiness, budgets and resources are the package's, never a constant; `TestCompilerNamesNoPlatform` passes with no `linux` literal in the compiler (R-01). A probe format is data in the same sense as a platform, which II does not yet say: the amendment adds the sentence and blesses the layer. |
| III | The CTM is the contract; the reader names its model version; approximations and omissions in the envelope's fidelity list, copied by the compiler; nothing read the mapping does not name; the read-only test's list; wiring derived from what was mapped; conformance and completeness checked separately | **PASS**. The reader, the mapping and CTM `2` do not move; the template renders the addresses the reader does not read (R-18). The kind's read is a second owned root, `FylgjaProbe`, named in the read-only test with its reason, read unpinned on the default branch as stages are (R-06). The hosts enter the in-memory CTM before the compile under `synthesized`, and the stored CTM moves nothing (R-01). |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. The device side of a probe reaches the node by its artifact alone, rendered by Infrahub's template (R-18). Fylgja configures only what it synthesizes: a host's address and route, as `exec` lines from the probe package's templates, carrying the declaration's values and nothing of intent (R-10). No bootstrap, no artifact for a host. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. The synthesis is a pure function of the snapshot's body and the two registries, inside `compiler.Compile`'s path, which `twin compile`, `stage plan`, the takes and the goldens all run; a fourth golden proves the probed bundle (R-01, R-11). The host's configuration is in the topology, so the bundle deploys as emitted. |
| VI | Provenance recorded (branch, `at`, schema hash, scope, mapping and model version in the bundle; `observed_at` in the CTM envelope, the snapshot's outer part and `twin.json`, never in the bundle nor in the bytes a snapshot's id hashes); `at` passed verbatim or not at all; where the source cannot replay time, the snapshot's id addresses intent | **PASS**. The probe list is hashed by the snapshot's id as D-061 defined, so two declarations differing in a probe take two ids and the bundle id moves with the hosts (FR-012). The kind is read unpinned, as stages are, and the read is recorded in the snapshot it feeds; nothing about the read enters the bundle. |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. Hosts are nodes of lab `fylgja`, named by the compiler from the declaration; nothing is allocated per twin. |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS**. Two activities join the lab's fifteen under a version marker (`flows`), each idempotent (a start kills a stray flow first, a read reads a file), passing node names and the twin directory, bounded by the probe package's budgets; a cancelled or failed step reads its flows on the record's disconnected context (R-13, R-14). Four workflows stay; the seven histories replay without the marker. D-062's count of activities moves to seventeen, which D-064 records. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. The loss is in the step record and the document; the flows' output lives in the host containers for the step's life and nowhere else. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. Every synthesized node, link and row is marked and listed in `fidelity.synthesized`; every refusal, skip and failed flow has a rule (data-model §12); every loss figure and the report's column carry `container`; the burst's and the flow's output hold addresses of the twin's data plane and no credential. |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `--probes` is a file beside a path, as `--snapshot` is, on five operations; every refusal of a declaration, a placement or a flow is the server's or the run's; the client's own are cobra's unknown flag and an unreadable file. `twin verify`'s bursts run in the server. `TestClientReachesTheCoreThroughTheAPIAlone` unchanged. |

**Development Workflow gates**: three tiers (tier 2 against the real Infrahub; tier 3 never
in CI) **PASS**; verification just-in-time and recorded (research §1 what the host and the
tree answered; §4 what implement owes, the live facts among them) **PASS**; documents (the
glossary's six entries, D-064 and the amendment drafted, the architecture's six sections and
the C4 model redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the mapping, one per source, documented (D-057). **This plan asks for a fourth**,
the probe package, by the amendment drafted in research §3.2, citing D-064; until it is
accepted the layer passes under II and the PSP's blessing, as a second package of the same
pattern.

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None flagged.** The flows run for a step's life inside the step's own run; no
timer, signal or queue is added.

**Post-design re-check (after Phase 1)**: unchanged. The design adds one package kind,
one Infrahub kind, two activities, one assertion kind and one new input to the compile; it
violates no gate. The Governance question (a fourth blessed layer) is answered by the
amendment drafted, taken at `analyze` on 2026-10-28 and appended by T002 with D-064.

## Project Structure

### Documentation (this feature)

```text
specs/016-probes/
├── brief.md            # the specify brief (committed)
├── spec.md             # the specification, clarified 2026-10-28; the plan's settlements appended
├── plan.md             # this file
├── research.md         # §1 verified (host, tree), §2 R-01…R-30, §3 D-064 and the amendment drafted, §4 owed
├── data-model.md       # the declaration, the kind, the snapshot, the synthesis, the bundle, the package, the activities, the loss, the burst, the report, the record, the rules, the documents
├── quickstart.md       # §0 the operator's, §1 tier 1, §2–§5 by hand, §6 tier 2, §7 tier 3, §8 records
├── contracts/
│   ├── commands.md     # cli.md's and api.md's "016: probes" sections
│   └── formats.md      # probes 1, the probe package 0.1, snapshot 2, manifest 6, step, verify, rehearsal, twin.json 11, findings, the frozen copies
├── checklists/requirements.md
└── tasks.md            # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
probes/                         # NEW: the probe packages, embedded as psp/ is
├── README.md                   # the format 0.1, its fields, the ping package's measured values
├── probe.schema.json           # the package's JSON Schema
└── ping.yaml                   # the one shipped format
schema/fylgja-probe.yaml        # NEW: the kind (R-07); README.md gains its section and the template's
contracts/probes.schema.json    # NEW: the declaration (R-04)
contracts/{snapshot,manifest,step,verify,rehearsal,twin}.schema.json, cli.md, api.md   # moved (formats.md)
internal/probe/                 # NEW: Declaration, Probe, Endpoint; Parse, Validate (the rules that read no CTM);
│                               #   Package, Registry, Load (embedded + <psp-dir>/probes/), the schema check;
│                               #   ParsePing (the mechanism's reading of ping's output, pure); the exec and command templates
internal/compiler/
├── synthesize.go               # NEW: PlaceProbes: the hosts and links into the in-memory CTM, the host table, every placement refusal
├── compile.go                  # Compile(c, decls, reg, probes); host nodes without package, artifact or bootstrap
├── topology.go                 # exec lines on a host node; kind and image from the probe package
├── manifest.go                 # BundleVersion "6"; provenance on nodes, links, rows; ManifestNode.Probe; Manifest.Probes; Fidelity.Synthesized
├── golden_test.go, testdata/   # the three goldens re-baselined, the fourth golden three-node-probed added
internal/validate/              # the placement rules through compiler.PlaceProbes, so both callers word them alike
internal/snapshot/              # Version "2"; Probes []probe.Probe; a "1" read as a "2"; the elements held to probe.Validate before filing
internal/intent/
├── probes.go                   # NEW: ProbeReader: Check (the kind on the default branch), Probes (paged, name order)
├── queries.graphql             # query Probes; the read-only test's owned roots gain FylgjaProbe
internal/server/
├── probes.go                   # NEW: probesFiles (the one file beside the path), readProbes (file, kind, none) once per request
├── read.go, create.go, step.go, stages.go, rehearse.go, handlers.go   # the probes argument and file; the list carried into every take
├── verify.go                   # the bursts through lab's Burster; the burst column of the text
internal/cli/                   # --probes on intent read, twin create, twin step, stage plan, twin rehearse
internal/lab/
├── flows.go                    # NEW: StartFlows, ReadFlows (docker exec; the mechanism keyed by the package's format)
├── burst.go                    # NEW: DockerBurster for verify's burst assertion
├── hostcheck.go                # probe images present whatever the acquisition; host nodes' plans from the probe registry
├── readiness.go                # the exec readiness mechanism for a host
├── twin.go                     # TwinVersion "11"; step.loss; nodes[] hosts with probe and no psp or artifact
├── wire/types.go               # ActStartFlows, ActReadFlows; FlowsInput, FlowsResult, Loss; NodePlan.Probe
internal/provision/
├── workflow_step.go            # StartFlows after StageStep, ReadFlows after VerifyTwin, under GetVersion("flows")
├── options.go, worker.go       # the two activities' options; counts 4/17
internal/rehearsal/
├── deadline.go                 # Mechanism.FlowsMargin; the flows' budgets in a rehearsed stage
├── markdown.go, report.go      # the loss column; each stage's loss; the footer's caveat
internal/verify/assert.go       # KindBurst; Derive from the manifest's probes; neighbor skipped on a synthesized link
internal/findings/              # the rules of data-model §12; the loss block; VerifyCounts.Burst; the step phase flows
internal/testsupport/seed.go    # the two probe-ready ports per device, addressed; the mixed fixture's; WriteProbes, DeleteProbes
cmd/fylgja-fixture/main.go      # -probes <file> (write the kind), -delete-probes, -prepare-main loads the kind
infrahub/queries/device_config.gql, infrahub/templates/device_config.j2   # ip_addresses rendered, both platforms (R-18)
testdata/ctm/three-node.json, mixed.json; testdata/snapshot/*.json; testdata/probes/*.json   # the fixtures follow; declarations for tier 1
scripts/e2e.sh                  # probes in cases 5, 8 and 9
docs/{architecture,brief,glossary,development,roadmap,verified-facts}.md, decisions.md (the operator's D-064), c4/workspace.dsl (+ make diagrams), README.md, CLAUDE.md, .specify/memory/constitution.md (the operator's amendment)
```

**Structure Decision**: the declaration, the package and the mechanism's pure reading live
in one new package, `internal/probe`, which imports `findings` and the standard library,
and for the registry alone `gopkg.in/yaml.v3`, `github.com/santhosh-tekuri/jsonschema/v6`
and the module root's embedded `probes/`; the declaration and the ping reading import
`findings` and the standard library alone
(`TestTheDeclarationAndThePingReadingImportNoDecoder`), so that the compiler, the
snapshot, the server and the lab share one definition of a probe without any of them
importing another. The synthesis lives in the compiler
(`PlaceProbes`), called by validation and by `Compile`, on the pattern `SurveyDevice` and
`LinkTerminations` already follow, so a refusal is worded alike from both. The hosts'
runtime, `docker exec` to start, read and burst, lives in `internal/lab` as every
host-bound mechanism does, keyed by the package's format value; verify's burst goes
through a `Burster` interface the lab implements and tier 1 fakes, as the gNMI `Reader`
does. The component changes are drawn in `docs/c4/workspace.dsl`: `probe` as a component
of the server and the worker, the probe packages as a second embedded set, Docker as a
reached container for the hosts (R-28).

## Order of the work

0. **The operator's**: this directory reviewed at `analyze`; D-064 and the amendment
   accepted or amended; the roadmap's F-014 paragraph (research §4.7).
1. **The declaration and the package** (`internal/probe`, `probes/`, the two new
   contracts): parse, validate, load, the schema, the conformance of the shipped package.
   Checkpoint: `make test`.
2. **The compile**: `PlaceProbes`, `Compile` with the body, bundle `6`, the manifest's
   blocks, the fourth golden; the goldens re-baselined on a commit of their own.
   Checkpoint: the goldens, `TestCompilerNamesNoPlatform`, the purity test.
3. **The snapshot and the takes**: snapshot `2`, the kind's read, `--probes` on the five
   commands and the API, the files, the conflicts, one list per request. Checkpoint: the
   frozen copies, the handler tests, the read-only test.
4. **The host**: the host check, the node plans, the topology's `exec`, the exec
   readiness, the record (`twin.json` `11`). Checkpoint: the host check's cases, the
   record's tests.
5. **The flows**: the two activities, the step's phases, the loss in the record and the
   document, the replays, the deadline. Checkpoint: counts 4/17, seven replays.
6. **The burst and the report**: `KindBurst`, the burster, the counts, the column, the
   footer. Checkpoint: the derivation and report tests.
7. **The template and the fixture**: the query and template lines, the seed's ports and
   addresses, the fixture tool's flags, the test CTMs and wrapped fixtures, the goldens
   re-baselined again. Checkpoint: `make test`; the template's render is the operator's
   import (quickstart §0).
8. **Tier 3's script and the documents**: `scripts/e2e.sh`; the contracts' prose; the
   architecture, the brief, the glossary, the development notes, the README, the C4 model;
   `make diagrams`, `make linkcheck`.
9. **The host, live** (quickstart §2–§5): the image pulled, the kind loaded by the
   operator, the template imported by the operator, the fixture re-seeded, the hand
   scenarios. The live session's.
10. **Tier 2** (§6), then **tier 3** whole (§7). The live session's.
11. **The records at the close** (research §4): `docs/verified-facts.md`, the roadmap
    (F-014 built), `CLAUDE.md`'s formats, state and the fixture's ids.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None. The one layer added, the probe package, is blessed by the amendment drafted in
research §3.2 and passes under II meanwhile.
