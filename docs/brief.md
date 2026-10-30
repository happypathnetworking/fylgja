# Fylgja — Brief

What Fylgja is for, what it deliberately is not, and the principles every later document
works from. The [architecture](architecture.md) says how it is built, and the
[decision log](decisions.md) why.

## What Fylgja is

Fylgja reads network intent from Infrahub and builds a **walking twin** of it: a
running virtual topology on real network operating system images, provisioned with
containerlab, built from one Infrahub branch at an optional point in time. It is two
deployables ([D-065](decisions.md#d-065)):

- **The core**, the `fylgja` binary in Go, runs a twin from a *snapshot*: it builds,
  steps, destroys, shows and verifies one, compiles one, validates a platform package and
  answers the step between two snapshots. It knows no branch, proposed change, stage or
  source of truth, and holds no Infrahub credential. Temporal provides durable execution
  for its provisioning.
- **The orchestrator**, a Python project on Prefect under `orchestrator/`, owns the source
  of truth: its Infrahub adapter reads a branch, a pinned branch or a stage to a snapshot
  file, and its flows read, create, step, plan, rehearse and check a schema, driving the
  core through its API alone. Its CLI is `fylgja-cli`.

## Scope

- **Input is an intent reference: `(branch, at?)`, or a stage that names one.** With
  `at`, the reference is pinned and its read can be taken again. Without it, Fylgja
  reads the branch head, sends no `at`, and records the read time as informational
  provenance. A stage is a moment of an Infrahub proposed change: its branch point, its
  head, or a mark the operator writes between them; it always resolves to a pinned
  reference, read to a snapshot ([D-066](decisions.md#d-066)). The orchestrator's adapter
  reads every reference; the core takes the snapshot alone.
- **One twin at a time.** `create` is refused while a twin exists; the operator
  destroys first. Comparisons between references are sequential, and a twin built from a
  snapshot steps to a stage of any proposed change, or to a snapshot of any branch,
  without a rebuild. A rehearsal, the orchestrator's flow, builds a proposed change's
  stages on one twin in turn through the core, verifies each, and destroys it.
- **One lab host**, the development host, until remote hosts are built.
- **Temporal runs the core's short workflows with fixed IDs**: `provision`, `destroy` and
  `step`. The server compiles before it starts one, and none reads a source of truth.
  Provisioning cleans up after itself on failure or cancellation. A run may be left
  running and read or interrupted again by its identity. There is no long-running
  lifecycle workflow, no Schedule, no TTL, no signals and no scheduled sweeper; an orphan
  lab is detected at `create` and at worker start.
- **The orchestrator's flows run on Prefect**: six, each a deployment its runner serves,
  the rehearsal among them under a deadline, ending in its destroy whatever happened.
  Temporal is not the orchestrator's integration surface, and Prefect is not the core's.
- **State lives in containerlab and files.** The twin is the lab containerlab reports
  plus the manifest staged beside it; bundles and snapshots live in directories by content
  hash; Temporal keeps run history. The orchestrator keeps the snapshots it takes and one
  record of the twin it drove, as files, beside its platform's own run history. No
  database of Fylgja's own.
- **One task queue** until remote hosts; host-bound activities live in their own
  package so the boundary stays visible.
- **A twin is frozen at its snapshot.** Nothing rebuilds it but the operator: it walks
  when the operator steps it, through a proposed change's stages or to any snapshot taken
  since. Its scope and mapping are fixed for its life; its branch is not. Following a
  branch left the core ([D-062](decisions.md#d-062)): the orchestrator may bring it back as
  a flow that takes a snapshot, compares and steps, and none does yet.
- **Fylgja never renders configuration.** Per-node bootstrap (hostname, cabled ports
  enabled, discovery on) comes from the platform support package. Production
  configuration is an artifact Infrahub rendered for the branch, pushed to each node
  after boot.
- **A probe is a declaration outside intent** ([D-064](decisions.md#d-064)): two
  endpoints on uncabled device ports, from a file or else the kind `FylgjaProbe` on the
  default branch, carried by the snapshot and compiled into two synthesized `ping` hosts,
  configured from the declaration alone, across which a step measures its transient loss,
  labelled container timing and never asserted, and verify runs a burst whose short count
  fails the stage.
- **Every command reaches the core through its API.** `fylgja` is a client of `fylgja
  serve`, which runs on the lab host beside the worker, on loopback; a client holds one
  token and an address. So are the orchestrator's flows. The two checks this repository
  registers in Infrahub, which run on every proposed change, are clients of the
  orchestrator's platform on the host's Docker bridge, never of the core: one triggers the
  stage plan, the other the rehearsal, whose flow posts its report on the proposed change,
  and a stage that fails blocks the merge.

## Principles carried from the first design

The core Go end to end, static binary, no second runtime; the orchestrator Python on
Prefect, free to call tools written in anything ([D-065](decisions.md#d-065)) · the CTM is
the contract, and an adapter maps one source's model onto it by one documented mapping:
the Infrahub adapter reads the OpsMill schema library's DCIM at a pinned commit, under a
scope, `tag:<name>` ([D-057](decisions.md#d-057), in place of Fylgja's generics and
reference schema); every
interface a port, `mgmt_only` the one use-flag, wiring derived never declared, VLANs
deferred · thin CTM with provenance,
justified by synthesized nodes · the snapshot, the CTM wrapped and content-addressed, the
core's one input ([D-061](decisions.md#d-061)) · pure compiler producing a deterministic,
content-addressed, self-describing bundle (topology, bootstrap per node, manifest) ·
fidelity manifest on every bundle · platforms are data: PSPs, conformance suite,
heterogeneous twins · drive the `clab` CLI, never link it · test tiers: pure and
golden on every change, Temporal test suite without a server, real Infrahub never a fake,
end-to-end with a booted NOS never gating · the core a single Go module, one binary
including the worker and the server, PSPs embedded · SR Linux first, EOS second ·
noun-verb CLI with stages exposed on the same code path as the tests · credentials from
the process environment only, never persisted.

## Pipeline

```
     the orchestrator         │                   the core
read ──────▶ take ────────────┼──▶ compile ─────▶ provision ───▶ operate
(Infrahub    (CTM →           │    (snapshot's    (bundle →      (show, destroy,
 → CTM;       snapshot;       │     CTM →         running lab;   step, verify)
 conformance  content-        │     bundle;       pushed;
 + complete-  addressed)      │     pure)         durable)
 ness checks)                 │
```

The snapshot crosses the boundary as a file, through the API. No separate resolve or bind
stage. The compiler emits a deployable topology with the
fixed lab name `fylgja` and containerlab's default management network; image
overrides use the PSP override directory. The take carries the request's probes beside
the CTM, and the compile places each probe's two hosts on a copy of the CTM before it
surveys it, so a probe reaches the bundle as synthesized nodes, which the step and verify
read from the manifest. `step` takes a twin built from a snapshot to
the bundle of a stage of any proposed change, or of a snapshot of any branch, in place,
and is how a twin walks; `verify` reads the running twin against the intent it was
built from and changes nothing. The orchestrator's `rehearse` builds, steps and verifies a
proposed change's stages in turn through the core, stops at the first that fails, destroys
the twin and reports; its `plan` compiles each stage through the core and asks it for the
step between each pair.

## CLI

The core's, `fylgja`:

```
fylgja serve          [--listen <host:port>]... [--psp-dir <dir>]
fylgja worker run     [--psp-dir <dir>]

fylgja twin create    --snapshot <id|file> [--dry-run] [--detach]
fylgja twin step      --snapshot <id|file> [--allow-restart] [--wait <duration>] [--dry-run] [--detach]
fylgja twin verify    [--wait[=<duration>]]
fylgja twin show
fylgja twin destroy   [--detach]

fylgja twin compile   --snapshot snapshot.json --out <bundle-dir>
fylgja twin provision <bundle-dir> [--dry-run] [--detach]
fylgja twin diff      --from <id|file> --to <id|file>

fylgja run read       --workflow <id> [--run <id>]
fylgja run interrupt  --workflow <id> [--run <id>]

fylgja psp validate   <file>...
```

The orchestrator's, `fylgja-cli`, each command but `stage list` running its flow
([contracts/orchestrator.md](../contracts/orchestrator.md)):

```
fylgja-cli twin create   --branch <b> | --stage <branch>/<label> [--dry-run]
fylgja-cli twin step     [--stage <branch>/<label>] [--allow-restart] [--wait <duration>] [--dry-run]
fylgja-cli twin rehearse --branch <b> [--markdown]

fylgja-cli intent read   --branch <b> [--at <ts>] | --stage <branch>/<label> --out snapshot.json
fylgja-cli stage list    [--branch <b>]
fylgja-cli stage plan    --branch <b>
fylgja-cli schema check  --branch <b>
```

Every `fylgja-cli` command but `schema check` also takes `--scope tag:<name>`, and `intent
read`, `twin create`, `twin step`, `stage plan` and `twin rehearse` take `--probes <file>`.

## Parked

Decided once, not adopted until the work that needs them is planned
([decision log](decisions.md#parked)):

- firewall staging: network configuration first, policy later, traffic validation last;
- production state collection, and read-only substitutes for it;
- platforms beyond SR Linux and EOS, IOL before PAN-OS.

Posting a twin's verification on an Infrahub proposed change is not parked: a rehearsal's
report is posted there from 015, by the orchestrator's rehearse flow from 020, and more of
it is on the [roadmap](roadmap.md).

## Open questions

1. ~~Infrahub `at` edge cases~~: closed by [D-045](decisions.md#d-045)'s verification
   (the [architecture](architecture.md#7-open-questions) says how).
2. Opt-in coupling of twin lifetime to branch lifetime.
3. The lab runtime remote hosts target: containerlab on remote hosts, clabernetes or KNE.
