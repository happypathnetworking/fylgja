# Fylgja — Brief

What Fylgja is for, what it deliberately is not, and the principles every later document
works from. The [architecture](architecture.md) says how it is built, and the
[decision log](decisions.md) why.

## What Fylgja is

Fylgja reads network intent from Infrahub and builds a **walking twin** of it: a
running virtual topology on real network operating system images, provisioned with
containerlab, built from one Infrahub branch at an optional point in time. Temporal
provides durable execution for provisioning.

## Scope

- **Input is an intent reference: `(branch, at?)`, or a stage that names one.** With
  `at`, the reference is pinned and its read can be taken again. Without it, Fylgja
  reads the branch head, sends no `at`, and records the read time as informational
  provenance. A stage is a moment of an Infrahub proposed change: its branch point, its
  head, or a mark the operator writes between them; it always resolves to a pinned
  reference.
- **One twin at a time.** `create` is refused while a twin exists; the operator
  destroys first. Comparisons between references are sequential, and a twin built from a
  snapshot steps to a stage of any proposed change, or to a snapshot of any branch,
  without a rebuild. A rehearsal builds a proposed change's stages on one twin in turn,
  verifies each, and destroys it.
- **One lab host**, the development host, until remote hosts are built.
- **Temporal runs short workflows with fixed IDs**: `provision`, `destroy`, `step` and
  `rehearse`, whose children are the other three, under a deadline. The server reads and
  compiles before it starts one, and none reads a source of truth. Provisioning cleans up
  after itself on failure or cancellation, and a rehearsal ends in its destroy. There is no
  long-running lifecycle workflow, no Schedule, no TTL, no signals and no scheduled
  sweeper; an orphan lab is detected at `create` and at worker start.
- **State lives in containerlab and files.** The twin is the lab containerlab reports
  plus the manifest staged beside it; bundles live in a directory by content hash;
  Temporal keeps run history. No database.
- **One task queue** until remote hosts; host-bound activities live in their own
  package so the boundary stays visible.
- **A twin is frozen at its snapshot.** Nothing rebuilds it but the operator: it walks
  when the operator steps it, through a proposed change's stages or to any snapshot taken
  since. Its scope and mapping are fixed for its life; its branch is not. Following a
  branch left the core ([D-062](decisions.md#d-062)): an orchestrator outside it may take
  a snapshot, compare and step.
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
- **Every command goes through the API.** The CLI is a client of `fylgja serve`, which
  runs on the lab host beside the worker; a client holds one token and an address. So are
  the two checks this repository registers in Infrahub, which run on every proposed
  change: one reports its stage plan, the other its rehearsal, posted on the proposed
  change, and a stage that fails blocks the merge.

## Principles carried from the first design

Go end to end, static binary, no second runtime · the CTM is the contract, and a reader
maps one source's model onto it by one documented mapping: the Infrahub reader reads the
OpsMill schema library's DCIM at a pinned commit, under a scope, `tag:<name>`
([D-057](decisions.md#d-057), in place of Fylgja's generics and reference schema); every
interface a port, `mgmt_only` the one use-flag, wiring derived never declared, VLANs
deferred · thin CTM with provenance,
justified by synthesized nodes · the snapshot, the CTM wrapped and content-addressed, the
core's one input ([D-061](decisions.md#d-061)) · pure compiler producing a deterministic,
content-addressed, self-describing bundle (topology, bootstrap per node, manifest) ·
fidelity manifest on every bundle · platforms are data: PSPs, conformance suite,
heterogeneous twins · drive the `clab` CLI, never link it · test tiers: pure and
golden on every change, Temporal test suite without a server, real Infrahub never a fake,
end-to-end with a booted NOS never gating · single Go module, one binary including
the worker and the server, PSPs and schema embedded · SR Linux first, EOS second ·
noun-verb CLI with stages exposed on the same code path as the tests · credentials from
the process environment only, never persisted.

## Pipeline

```
read ──────▶ take ────▶ compile ─────▶ provision ───▶ operate
(Infrahub    (CTM →     (snapshot's    (bundle →      (show, destroy,
 → CTM;       snapshot;  CTM →         running lab;   step, verify,
 conformance  content-   bundle;       pushed;        rehearse)
 + complete-  addressed) pure)         durable)
 ness checks)
```

No separate resolve or bind stage. The compiler emits a deployable topology with the
fixed lab name `fylgja` and containerlab's default management network; image
overrides use the PSP override directory. The take carries the request's probes beside
the CTM, and the compile places each probe's two hosts on a copy of the CTM before it
surveys it, so a probe reaches the bundle as synthesized nodes, which the step and verify
read from the manifest. `step` takes a twin built from a snapshot to
the bundle of a stage of any proposed change, or of a snapshot of any branch, in place,
and is how a twin walks; `verify` reads the running twin against the intent it was
built from and changes nothing; `rehearse` builds, steps and verifies a proposed change's
stages in turn, stops at the first that fails, destroys the twin and reports.

## CLI

```
fylgja serve         [--listen <host:port>]... [--psp-dir <dir>]
fylgja worker run    [--psp-dir <dir>]

fylgja twin create   --branch <b> [--at <ts>]
fylgja twin create   --stage <branch>/<label>
fylgja twin create   --snapshot <id|file>
fylgja twin step     [--stage <branch>/<label> | --snapshot <id|file>] [--allow-restart] [--wait <duration>] [--dry-run]
fylgja twin verify   [--wait[=<duration>]]
fylgja twin rehearse --branch <b> [--markdown]
fylgja twin show
fylgja twin destroy

fylgja intent read   --branch <b> [--at <ts>] --out snapshot.json
fylgja intent read   --stage <branch>/<label> --out snapshot.json
fylgja twin compile  --snapshot snapshot.json --out <bundle-dir>
fylgja twin provision <bundle-dir>

fylgja stage list    [--branch <b>]
fylgja stage plan    --branch <b>

fylgja schema check  --branch <b>
fylgja psp validate  <file>...
```

## Parked

Decided once, not adopted until the work that needs them is planned
([decision log](decisions.md#parked)):

- firewall staging: network configuration first, policy later, traffic validation last;
- production state collection, and read-only substitutes for it;
- platforms beyond SR Linux and EOS, IOL before PAN-OS.

Posting a twin's verification on an Infrahub proposed change is not parked: a rehearsal's
report is posted there from 015, and more of it is on the [roadmap](roadmap.md).

## Open questions

1. ~~Infrahub `at` edge cases~~: closed by [D-045](decisions.md#d-045)'s verification
   (the [architecture](architecture.md#7-open-questions) says how).
2. Opt-in coupling of twin lifetime to branch lifetime.
3. The lab runtime remote hosts target: containerlab on remote hosts, clabernetes or KNE.
