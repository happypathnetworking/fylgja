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

- **Input is an intent reference: `(branch, at?)`, or a waypoint that names one.** With
  `at`, the twin is pinned and reproducible. Without it, Fylgja reads the branch head,
  sends no `at`, and records the read time as informational provenance. A waypoint is a
  mark the operator writes in Infrahub, and it always resolves to a pinned reference.
- **One twin at a time.** `create` is refused while a twin exists; the operator
  destroys first. Comparisons between references are sequential, and a twin built from a
  waypoint steps to another waypoint of its series without a rebuild.
- **One lab host**, the development host, until remote hosts are built.
- **Temporal runs short workflows with fixed IDs**: `provision`, `destroy`, a `reconcile`
  check and `step`. Provisioning cleans up after itself on failure or cancellation. There
  is no long-running lifecycle workflow, no TTL, no signals and no scheduled sweeper; an
  orphan lab is detected at `create` and at worker start.
- **State lives in containerlab and files.** The twin is the lab containerlab reports
  plus the manifest staged beside it; bundles live in a directory by content hash;
  Temporal keeps run history. No database.
- **One task queue** until remote hosts; host-bound activities live in their own
  package so the boundary stays visible.
- **A twin built from an unpinned reference follows its branch.** A Temporal Schedule
  starts a `reconcile` check every interval, which rebuilds the twin when its compiled
  bundle has changed. `--no-follow` builds a frozen twin instead.
- **Fylgja never renders configuration.** Per-node bootstrap (hostname, cabled ports
  enabled, discovery on) comes from the platform support package. Production
  configuration is an artifact Infrahub rendered for the branch, pushed to each node
  after boot.
- **Every command goes through the API.** The CLI is a client of `fylgja serve`, which
  runs on the lab host beside the worker; a client holds one token and an address.

## Principles carried from the first design

Go end to end, static binary, no second runtime · schema contract as Infrahub generics
with a shipped reference schema; `iftype` is kind, `mgmt_only` is the one use-flag,
wiring derived never declared, VLAN generic deferred · thin CTM with provenance,
justified by synthesized nodes · pure compiler producing a deterministic,
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
read ──▶ compile ──▶ provision ──▶ operate
(Infrahub    (CTM →      (bundle →      (show, destroy,
 → CTM;       bundle;     running lab;   reconcile, step,
 conformance  pure)       pushed;        verify)
 + complete-              durable)
 ness checks)
```

No separate resolve or bind stage. The compiler emits a deployable topology with the
fixed lab name `fylgja` and containerlab's default management network; image
overrides use the PSP override directory. `step` takes a waypoint twin to another
waypoint's bundle in place; `verify` reads the running twin against the intent it was
built from and changes nothing.

## CLI

```
fylgja serve         [--listen <host:port>] [--psp-dir <dir>]
fylgja worker run    [--psp-dir <dir>]

fylgja twin create   --branch <b> [--at <ts>] [--no-follow] [--interval <d>]
fylgja twin create   --waypoint <series>/<sequence>
fylgja twin step     [--waypoint <series>/<sequence>] [--allow-restart] [--wait <duration>] [--dry-run]
fylgja twin verify   [--wait[=<duration>]]
fylgja twin show
fylgja twin destroy

fylgja intent read   --branch <b> [--at <ts>] --out ctm.json
fylgja intent read   --waypoint <series>/<sequence> --out ctm.json
fylgja twin compile  --ctm ctm.json --out <bundle-dir>
fylgja twin provision <bundle-dir>

fylgja waypoint list [--series <s>]
fylgja waypoint plan --series <s>

fylgja schema check  --branch <b>
fylgja psp validate  <file>...
```

## Parked

Decided once, not adopted until the work that needs them is planned
([decision log](decisions.md#parked)):

- firewall staging: network configuration first, policy later, traffic validation last;
- production state collection, and read-only substitutes for it;
- platforms beyond SR Linux and EOS, IOL before PAN-OS.

Posting a twin's verification on an Infrahub proposed change is not parked; it is on the
[roadmap](roadmap.md).

## Open questions

1. Infrahub `at` edge cases: before the branch's creation, sub-second precision, a
   server-side marker for the read time.
2. Opt-in coupling of twin lifetime to branch lifetime.
3. The lab runtime remote hosts target: containerlab on remote hosts, clabernetes or KNE.
