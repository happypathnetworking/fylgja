# Implementation Plan: The split: the core and the orchestrator

**Branch**: `020-core-orchestrator-split` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), [brief.md](brief.md), [D-065](../../docs/decisions.md#d-065),
[D-066](../../docs/decisions.md#d-066), Constitution 2.3.0. Research in
[research.md](research.md) (§1 verified on the host and in the tree, §2 R-01…R-24, §3 the
3.0.0 amendment drafted for the operator, §4 owed at implement); the units in
[data-model.md](data-model.md); the interfaces in [contracts/](contracts/README.md); the
validation in [quickstart.md](quickstart.md). No Infrahub skill designs a kind here;
`infrahub-managing-checks` is read before the checks change and `infrahub-common`'s
GraphQL references with `infrahub-managing-transforms`' union-fragment rule before the
adapter's queries (R-21), at implement.

## Summary

Fylgja becomes two deployables. The **core**, the `fylgja` binary, loses the five
operations and five arguments that read Infrahub, its `INFRAHUB_*` and default scope,
the bridge listener and the rehearse workflow; it gains `detach` on its four runs,
`run.read` and `run.interrupt` by identity over the history reads it already makes, and
`twin.diff`, the pure step between two snapshots; `twin.json` moves to `12`, naming no
stage. The **orchestrator**, a Python project on **Prefect 3.9.0** under `orchestrator/`
with its own venv, `pytest` and `ruff`, holds the Infrahub adapter (a port of the Go
reader on `infrahub-sdk` 1.23.2 to the same snapshot id, verified reproducible in
Python), six flows served by one runner against a Prefect server of its own with basic
auth on the Docker bridge, the `rehearsal`, `stages` and `plan` documents and their
renderers held to goldens captured from Go, one record of the twin it drove, and the CLI
`fylgja-cli`. The rehearse flow posts the report; the two checks trigger a deployment over
plain `httpx`, wait and conclude from the status. Verified on the host: Infrahub's embedded
Prefect is separate and unpublished, the open-source server authenticates, a deployment
is triggered, polled, read and cancelled over HTTP, and a flow's `finally` runs on a
timeout and a cancellation (research §1). The route ports, compares, then removes.

## Technical Context

**Language/Version**: Go 1.26 (the core); Python 3.14.4 (the orchestrator, the checks).
**Primary Dependencies**: Temporal Go SDK 1.49 (core); Prefect 3.9.0, infrahub-sdk 1.23.2,
httpx 0.28, pydantic 2.14 (orchestrator); the checks httpx and the SDK the task worker
image carries. **Storage**: files (the core's state root; the orchestrator's root), Temporal
history, Prefect's SQLite under `local/orchestrator/prefect`. **Testing**: `go test`;
`pytest` 9.2 (`-m contract` for tier 2); `scripts/e2e.sh`. **Target Platform**: the lab
host, Ubuntu 26.04. **Project Type**: a CLI/server/worker binary plus a Python flow
project and a CLI. **Performance Goals**: tier 1 ≤ 65 s; tier 2 and 3 measured (R-15,
R-16); `fylgja-twin` inside 4,260 s. **Constraints**: the goldens, the fixture's ids, CTM
`2`, snapshot `2`, bundle `6` unmoved; no token on the bridge; no database. **Scale/Scope**:
about 25,600 Go lines leave or move (11,300 tests); about 8,000 Python lines arrive;
T001–T095 expected, inside 017's 121 (R-22).

## Constitution Check

Constitution 2.3.0, amended to 3.0.0 by this feature (research §3.2); each gate read as
2.3.0 has it and as the draft rewords it.

| # | Gate | Status |
|---|---|---|
| I | Go only for the core; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | PASS under 3.0.0: the core unchanged; the orchestrator, a Python project on Prefect, is outside I as amended and reaches the core through the API alone (XI); a VIOLATION under 2.3.0, resolved by D-065 and the MAJOR amendment (Complexity Tracking) |
| II | Platforms are data; probe format a package | PASS: untouched; the adapter reads `platform.matches` from the shipped packages (FR-013) |
| III | The CTM is the contract; a reader maps one source | PASS: the mapping, the fidelity list, the read-only kinds and the two validations are ported with their identifiers (R-07); the reader is now an adapter (amendment) |
| IV | No configuration rendered | PASS: untouched |
| V | Compiler pure; `twin compile` on the goldens' path | PASS: `twin.diff` compiles on the same path (R-05); the adapter never compiles |
| VI | Provenance; `at` verbatim; a stage where time cannot replay | PASS: unchanged in the snapshot; D-066's sentence added |
| VII | One twin at a time | PASS: the fixed identities stay the one lock; the orchestrator adds none |
| VIII | Temporal: fixed ids, deterministic, idempotent, heartbeats, cleanup, one queue | PASS: three workflows, seventeen activities; nothing long-running added; the rehearse flow lives outside Temporal (D-065) |
| IX | No database | PASS: the orchestrator's state is files and Prefect's own run history (amendment); SQLite is Prefect's, not Fylgja's |
| X | Fidelity manifest; stable ids; no credential logged | PASS: every moved rule keeps its id; `rehearsal.report.unposted` and the four `run.*` are new and stable; the greps extend to the orchestrator's logs |
| XI | The API is the boundary | PASS: the orchestrator drives the core by the API alone, held by `TestClientReachesTheCoreThroughTheAPIAlone` for the CLI and the new `TestTheCoreLinksNoReader`; no shipped client carries a second path |

**Blessed layers**: untouched. **Must flag**: no binding stage, no database, no
long-running workflow, no per-twin resource, no client path around the API.

## Project Structure

### Documentation (this feature)

```text
specs/020-core-orchestrator-split/
├── plan.md  research.md  data-model.md  quickstart.md  contracts/README.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
cmd/fylgja/                 serve.go loses INFRAHUB_* and the scope; the CLI gains --detach, run, twin diff
internal/api, internal/server, internal/findings, internal/lab, internal/provision   §1-3, §11 of data-model.md
internal/intent, internal/stages, internal/stage, internal/rehearsal                 removed after the port (R-15)
orchestrator/
├── pyproject.toml          fylgja-cli, fylgja-orchestrator; ruff; pytest markers
├── src/fylgja_orchestrator/{adapters/infrahub/, documents/, flows/, core.py, record.py, cli.py, serve.py}
└── tests/{unit, contract, golden/, data/}
infrahub/checks/            fylgja_api.py the platform's client; fylgja_step.py; fylgja_twin.py
scripts/                    bring-up.sh part orchestrator; e2e.sh through fylgja-cli; infrahub/docker-compose.override.yml
contracts/                  api.md, cli.md, orchestrator.md, checks.md, the schemas
docs/                       architecture, c4, glossary, development, verified-facts, roadmap, brief
```

**Structure Decision**: the core stays the one Go module; the orchestrator is one Python
project in the same repository (D-065, R-02), its venv at `orchestrator/.venv`.

## Order of the work

1. **The core's shape**: `detach`, `run.read`, `run.interrupt`, `twin.diff`, `twin.json`
   `12`, the contracts and frozen copies; tier 1 (R-03 to R-06).
2. **The goldens' capture** on the live host, before any renderer goes (R-14, a task of
   the attended loop); the roadmap reconciled (R-24).
3. **The orchestrator's toolchain**: `orchestrator/`, the venv, `make` and CI (R-02, R-17).
4. **The adapter's port**, module by module with each Go contract test's assertions
   carried over; the compare test against `fylgja intent read`; `0940db93…` (R-07).
5. **The documents and flows**: the renderers to the goldens; `core.py`; the six flows;
   the record; `fylgja-cli` (R-08 to R-13).
6. **The checks and the host**: `fylgja_api.py`, the override, the bring-up part, the
   loopback listener; `[operator]` push and import (R-12, R-18).
7. **The removal**: the five handlers, the rehearse workflow, `internal/rehearsal`, the
   reader packages, the boundary test; the constitution 3.0.0; the documents (R-15, R-20).
8. **The tiers**: tier 2 whole, tier 3 nine cases, the records (R-15, R-16).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| A second runtime (Python, Prefect) beside the Go binary, against Principle I as 2.3.0 words it | D-065: the orchestrator is a deployable of its own on the ecosystem's language, F-025's adapter joins it, and the checks already run on Prefect | The orchestrator on Temporal in Go keeps one toolchain but defers the platform question and leaves Constitution I's freedom unused (D-065, Options); the amendment keeps I for the core |
