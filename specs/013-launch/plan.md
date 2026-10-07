# Implementation Plan: The launch

**Branch**: `013-launch` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/013-launch/spec.md`, the brief
([brief.md](brief.md)) and the roadmap's [Next](../../docs/roadmap.md#next). Research is in
[research.md](research.md), the entities in [data-model.md](data-model.md), the tooling's
wire forms in [contracts/](contracts/), the validation in [quickstart.md](quickstart.md).

## Summary

M14's second half. The repository goes public first, by the operator's act, once
`SECURITY.md`, the pull-request workflow and a read of the tree are in; then every
registration of this repository in an Infrahub is the credential-less one a stranger
makes. One bash script, `scripts/bring-up.sh`, takes a fresh Ubuntu 26.04 host through
four parts (toolchain, lab host, Infrahub, Fylgja) to tiers 1 and 2 passing and the
worker's and the server's reports naming both packages, with an SR Linux-only path when
the cEOS tar is absent; its Infrahub part writes `main` through a new flag of the fixture
tool, `-prepare-main`, and is what CI's contract job runs on a hosted `ubuntu-26.04`
runner before tier 2, with no secret. Tier 3 gains a platform list (`PLATFORMS`) that
narrows a run and ends on a partial-pass line. The development host's Infrahub registers
this repository in place of the private copy. The front page gains a recorded session (an
asciinema cast rendered to a GIF), `SECURITY.md`, a badge, `v0.1.0` built by a
tag-triggered workflow and published by the operator, the one-page write-up, and the five
Infrahub behaviours filed or dropped. **No product behaviour changes.**

## Technical Context

**Language/Version**: bash for the script and `scripts/e2e.sh`; Go 1.26.0 for the fixture
tool's flag (build tag `fixture`) and the one reworded message in `internal/testsupport`;
YAML for three GitHub Actions workflows and the Compose override; Markdown for the
records. No product Go changes.

**Primary Dependencies**: Infrahub 1.11.2's published Compose (`https://infrahub.opsmill.io/1.11.2`)
and its stack (Neo4j, RabbitMQ, Redis, Postgres); Docker Engine and Compose 5 (the runner's
29.4.2/5.1.3; the release containerlab's installer pins for 26.04); containerlab 0.79.0;
the Temporal CLI 1.9.1; golangci-lint 2.14.0; gnmic 0.49.0; `infrahub-sdk[ctl]` 1.23.2
in a venv (Python ≥3.10, <3.15); the SR Linux image and the operator-provided cEOS tar
(sha256 `89a567d5…`); GitHub's hosted `ubuntu-26.04` runner, rulesets and releases;
asciinema 3.2.1 and agg 1.9.0 as hand tools; the OpsMill `infrahub-reporting-issues`
skill. All pinned; each verified or owed in research.md.

**Storage**: files only. `local/.env` (the one file holding a value), `local/infrahub/`
(the Compose project), `.venv/`; Infrahub's volumes under the Compose project
`fylgja-infrahub`; `docs/recording/` for the cast and the GIF. No database (IX).

**Testing**: the script is proved by running it, on a fresh 26.04 VM (twice: with the
tar and without, then a second run on a set-up host) and by CI's contract job on every
push to `main`; `shellcheck` in the unit job. The fixture tool's flag is proved by those
runs and by the development host's registration. Tier 3's platform list is proved by a
narrowed run on the development host and on the SR Linux-only VM. Tiers 1 and 2 are
unchanged and must pass with no golden re-baselined (SC-012).

**Target Platform**: Ubuntu 26.04 LTS alone, on amd64: a QEMU/KVM guest of the
development host's shape (10 vCPU, 32 GiB, 8 GiB swap, 100 GB) and GitHub's hosted
runner (4 vCPU, 16 GB, 6-hour jobs). The release's binary is Linux amd64.

**Project Type**: tooling, CI and records around an existing single-binary Go project.

**Performance Goals**: the script's full run on a fresh VM in well under an hour
(the image pulls dominate); CI's contract job in about 15 minutes, recorded on its first
run; tier 3 unchanged at 17–19 minutes, and a narrowed run shorter by its skipped cases.

**Constraints**: no credential in anything this feature writes or prints (X; FR-011,
FR-024, FR-041); the repository public before the script and CI are proved (FR-030); no
product change (FR-039: every format version, golden, history and the fixture id
`b9d53ebc…` stay); the template's bytes unchanged (D-044); tier 3 never in CI (D-017);
a session never pushes, and every outward-facing act is the operator's (FR-037); the
write-up cites nothing of the private record and its figures are read by the operator
before they are committed (FR-035).

**Scale/Scope**: one script of four parts and about a dozen installed components; one
new fixture-tool flag (about 150 lines of Go in `testsupport` and `cmd/fylgja-fixture`);
a case table, a skip rule and an end line in `scripts/e2e.sh`; three workflows; one
override file; `SECURITY.md`, `docs/how-it-was-built.md`, the recording; six documents
rewritten at the close. The roadmap sizes it at 10–14 hours.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 1.1.1 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. Nothing ships changes. The script is bash tooling beside `scripts/e2e.sh` (FR-014); the venv, asciinema and agg are hand and setup tools, not in the critical path. The release workflow asserts the binary is static (`file`) before it attaches it. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness from the PSP | **PASS**. The script and `e2e.sh` read the cEOS reference and the shipped package names from `psp/*.yaml`, never a constant of their own; the platform list selects by package. No PSP changes (format 0.6 stays). |
| III | Queries only the Fylgja generics; never past a generic; least demanded; graduate-don't-gate; `iftype` is kind, `mgmt_only` is the use-flag; unimplemented `iftype` rejects; conformance and completeness checked separately | **N/A**: no read, schema or compiler change. The schema loaded on `main` is the committed `schema/` (research §2.4: an empty diff on the development host). |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. Infrahub renders from this repository's template (D-044), whose bytes do not change; the fixture tool asks Infrahub to generate, as before. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **N/A**: untouched; SC-012 holds the goldens and the fixture id. |
| VI | Provenance recorded; `at` passed verbatim or not at all | **N/A**: untouched. |
| VII | One twin at a time; orphan detection; nothing per-twin | **N/A**: untouched. The script boots no twin; tier 3's narrowed run makes the same twins one at a time. |
| VIII | Temporal: fixed IDs; deterministic workflows; idempotent activities; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **N/A**: no workflow or activity changes. The script starts the dev server, the worker and the server as `CLAUDE.md` does. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. The script's state is `local/.env`, `local/infrahub/` and Infrahub's own volumes; nothing new holds state. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. Every token the script makes goes to `local/.env` alone (`0600`), through header files and `--env-file`, never an argument or a line of output (contract, Hygiene); CI holds no secret; the recording is grepped and read frame by frame; the partial-pass line names every skipped case with why (nothing skipped silently). |
| XI | The API is the boundary; every refusal is the server's; payloads are the versioned documents; no second path in a shipped client; held by an import test | **PASS**. The recording and the script drive Fylgja through the CLI as the API's client; the fixture tool is test tooling, as Constitution XI allows. |

**Development Workflow gates**: three tiers (tier 3 never in CI, FR-026; tier 2 against a
real Infrahub on the runner, never a fake) **PASS**; verification just-in-time and
recorded (research §2, with §3 owed to the first 26.04 run) **PASS**; documents (new terms
in the glossary; no decision changes, so no new entry: D-043, D-044, D-017, D-042 and
D-028 are executed as they stand; a split of CI out of the script, if the runner needs
it, would be a new entry) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the generics contract (D-002).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None introduced.**

**The OpsMill skills**: `infrahub-managing-objects` was loaded for the group and the
registration (research R-03); its branch-first rule is not followed on purpose, since
Fylgja's schema, group and registration live on `main` (D-028).

**Post-design re-check (after Phase 1)**: unchanged. The design adds one fixture-tool
flag, one script, three workflows and records; no gate moved. Three places where the
design refined the spec's first wording were settled in the spec by `analyze`:
`local/.env` is scaffolded by the preamble rather than the Fylgja part (FR-010; research
R-02), the ruleset that protects `main` follows the flip by minutes because GitHub's Free
plan offers rulesets to public repositories alone (FR-030, FR-034; research R-08), and
`FYLGJA_PSP_DIR` is left empty on purpose (US2 scenario 8; data-model §2).

## Project Structure

### Documentation (this feature)

```text
specs/013-launch/
├── brief.md                 # the specify brief (committed before this plan)
├── spec.md                  # the specification, clarified
├── plan.md                  # this file
├── research.md              # Phase 0: decisions R-01…R-15, verified facts, what is owed, the write-up's figures
├── data-model.md            # Phase 1: the script's run, local/.env, the platform list, the registration, the release, the settings
├── quickstart.md            # Phase 1: the validation scenarios, in the operator's order
├── contracts/
│   ├── bring-up-script.md   # usage, parts, reports, exit codes, hygiene
│   ├── e2e-platform-list.md # PLATFORMS, the case table, the partial-pass line
│   ├── fixture-prepare-main.md  # the fixture tool's flag and the reworded refusal
│   └── ci-and-release.md    # ci.yml, pull-requests.yml, release.yml, the ruleset, the settings
├── checklists/requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
scripts/
├── bring-up.sh                      # NEW: the bring-up script (research R-01, R-02; contracts/bring-up-script.md)
├── infrahub/
│   └── docker-compose.override.yml  # NEW: the 1.11.2 pin and the Neo4j cap, from the development host, comment rewritten (R-04)
└── e2e.sh                           # the case table, the skip rule, the partial-pass line, guarded closing lines (R-13)
cmd/fylgja-fixture/main.go           # -prepare-main and its flags (R-03)
internal/testsupport/
├── infrahub.go                      # the reworded refusal in lookupByName and groupMemberCount (FR-028)
└── main.go                          # NEW: EnsureGroup, EnsureReadOnlyRepository, AwaitImport (build tag contract || fixture)
.github/workflows/
├── ci.yml                           # ubuntu-26.04; the contract job enabled on push; no secret; shellcheck in unit (R-06)
├── pull-requests.yml                # NEW: closes pull requests with the Contributing sentence (R-08)
└── release.yml                      # NEW: the tag-triggered draft release (R-07)
.env.example                         # the Compose block (R-04)
SECURITY.md                          # NEW: the threat model and how to report (FR-031)
README.md                            # the badge, the recording, What it needs and Tests for the script, CI and the SR Linux-only host
docs/
├── how-it-was-built.md              # NEW: one page (R-09)
├── recording/session.cast, session.gif   # NEW (R-10)
├── development.md                   # the walk-through as the script's record; CI; the registration and the ref answer; PLATFORMS; the tar's name
├── verified-facts.md                # 26.04 re-verifications; the filed issues' links
├── glossary.md                      # platform list, partial pass, Infrahub part, recording, write-up; Bring-up script, Launch, Development host updated
├── roadmap.md                       # the launch into Built; Next names item 7
└── ideas.md                         # a persistent waypoint series on the fixture branch
contracts/{api,findings,manifest,psp}.schema.json, psp/psp.schema.json,
internal/*/testdata/contracts/*/*.schema.json   # description strings scrubbed of private paths and numbers (R-14), copies kept byte-equal
CLAUDE.md                            # Environment for 26.04 and the venv; State rewritten whole at the close
```

**Structure Decision**: tooling joins `scripts/`, where tier 3's script and the loop
already live; the Compose override sits under `scripts/infrahub/` so that `infrahub/`
stays what Infrahub reads at import; the fixture tool, the one writer, gains the
preparation of `main`; workflows stay the repository's three files; records stay where
development.md's layout puts them. No Go package is added or re-wired, so
`docs/c4/workspace.dsl` is not redrawn (its "Artifacts repository" already describes
this repository registered read-only).

## Order of the work

The operator's acts come in the spec's order, and the work fits around them:

1. **Before the flip** (this branch, then `main`): `SECURITY.md`, the pull-request
   workflow, the scrub of the private-record citations (R-14), the glossary's *Launch*
   entry corrected; the read of the tree (quickstart §1).
2. **The flip and the settings** (operator): visibility, the ruleset, private
   vulnerability reporting, topics.
3. **The development host registers this repository** (quickstart §2): the fixture tool's
   flag first, since it is what registers; the private copy removed; the fixture
   re-seeded; tiers 2 and 3; the `ref` answer.
4. **The script and CI**: the script's four parts and the override; `ci.yml` enabled; the
   fresh VM's runs (full, SR Linux alone, second run); the first push to `main` with the
   contract job; the re-verified facts into research.md §3.
5. **Tier 3's platform list**: the case table and the end line; a narrowed run on the
   development host and on the SR Linux-only VM.
6. **The visible half**: the recording, the badge, the README's sections, the write-up
   (one session reading the figures, the operator reading them back), the five Infrahub
   behaviours through the skill, the release workflow and `v0.1.0`.
7. **The records at the close**: development.md, verified-facts.md, the glossary, the
   roadmap, `CLAUDE.md`, `docs/ideas.md`; the development host moved to 26.04 by the
   script.

Items 3, 4 and 5 need the host or the VM and the operator present: they are live or
operator work in the loop's terms, as the brief says.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None. No gate is violated and no rejected design returns.
