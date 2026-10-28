# The commands: `cli.md`'s and `api.md`'s "019: following removed" sections

**Feature**: `019-following-removed` · To land as a section at the end of
`contracts/cli.md` and of `contracts/api.md`. The earlier sections stand as history; where
one states following as current behaviour, it gains a one-line pointer to this section and
no other edit.

## cli.md: 019: following removed

A twin is frozen at its snapshot, and nothing rebuilds it but the operator
([D-062](../../../docs/decisions.md#d-062)). No command makes a Schedule; the worker serves
four workflows and fifteen activities, and reads no source of truth.

### The commands

```text
twin create --branch <b> [--at <t>] [--scope tag:<name>] [--dry-run]
twin create --stage <b>/<label> [--scope tag:<name>] [--dry-run]
twin create --snapshot <id|file> [--dry-run]
twin step [--stage <b>/<label> | --snapshot <id|file>] [--allow-restart] [--wait <d>] [--dry-run]
twin destroy
twin show [--json]
```

- `--interval` and `--no-follow` are unknown flags on every command: cobra's `unknown flag:
  --interval`, exit 2, before any request.
- **`twin step`** steps any twin whose record names a snapshot, built by `--branch`,
  `--stage` or `--snapshot`:
  - `--stage <b>/<label>` names a stage of **any** proposed change, resolved, judged and
    read under the record's scope. Left out, it means the next stage of the twin's own
    proposed change; for a twin whose record names no stage, a target is required,
    unless its record refuses the step for itself, which is then given first (R-08 as
    amended, 2026-10-28).
  - `--snapshot <id|file>` takes the forms `twin create --snapshot` takes: an id the
    server's store holds, or a file read here and sent, which the server files under its
    id. No request reaches Infrahub for it. A snapshot of any branch.
  - The record afterwards names the target's branch, `at`, snapshot and bundle, and its
    stage, or none for a snapshot target. Scope and mapping are the twin's for life.
  - A twin `twin provision` built, a record of `8` or earlier, and a record naming no
    snapshot do not step.
- **`twin destroy`** is the destroy workflow alone; it stops nothing first.

### The text

The twin line of a step, for a twin that names no stage:

```text
twin: snapshot 576933ec… (bundle f764e1fa…), branch fylgja-test-readme, read at 2026-10-28T09:14:02.118Z; 3 nodes
```

A snapshot target's line, in place of a stage's resolution line, and the step:

```text
target: snapshot 9c2d01e7… (branch fylgja-test-readme, read at 2026-10-28T09:21:40.007Z)
step snapshot 576933ec… → snapshot 9c2d01e7… (f764e1fa… → 2b7e90c1…):
  artifacts: n1 device-config 43e8fd0c… → 9a0177b2…
```

A stage side is named `<branch>/<label>` in the step's line and `stage <branch>/<label>`
elsewhere; a snapshot side `snapshot <8>…` everywhere. The closing lines:

```text
stepped to snapshot 9c2d01e7… (bundle 2b7e90c1…) in 41s: push n1 6s; settled after 4s
unchanged; the record moves to snapshot 9c2d01e7… (bundle f764e1fa…) in 3s
diverged towards snapshot 9c2d01e7… (bundle 2b7e90c1…) at phase push: …; the twin is up at stage change-1/seeded (bundle 35aea06f…); fylgja twin destroy clears it
```

`twin show`'s kind line:

```text
kind: snapshot 576933ec… (branch fylgja-test-readme, read at 2026-10-28T09:14:02.118Z)
kind: snapshot 35aea06f… (branch change-1 at 2026-10-28T09:01:00.000001Z), stage change-1/seeded
kind: snapshot 9c2d01e7… (branch change-1 at …), stage change-1/third-link (stepped from change-1/seeded by run fylgja-step 0a1b…, ended …)
kind: snapshot 9c2d01e7… (branch fylgja-test-readme, read at …) (stepped from snapshot 576933ec… by run fylgja-step 0a1b…, ended …)
kind: snapshot none (branch fylgja-test-readme, read at …)
kind: from a bundle
kind: none
```

The `snapshot none` line is followed by the note `the twin's record names no snapshot, so
fylgja twin step refuses it; fylgja twin destroy clears it`. "; not following" is gone from
every line. A step in flight: `…; run fylgja-step <run> is at step push, stepping towards
snapshot 9c2d01e7…`. An unreachable workflow service: `…; in flight: unknown (workflow
service unreachable at localhost:7233)`.

`twin verify`'s first line: `twin: branch fylgja-test-readme (snapshot 9c2d01e7…, bundle
2b7e90c1…), ready; …`.

The dry run of `twin create` has no `follow:` line.

### Identifiers

| Identifier | Severity, exit, step | When |
|---|---|---|
| `snapshot.flags.conflict` | rejection, 2, start | gains: `--stage` beside `--snapshot` on `twin step`, object `--stage` |
| `step.target.unknown` | rejection, 1, resolve | gains: no `--stage` and no `--snapshot` for a twin whose record names no stage, object the record's `bundle_id`, read before any connection |
| `step.twin.unsteppable` | rejection, 1, resolve | reworded: a bundle twin, a record of 8, a record naming no snapshot; and a target whose scope or mapping differs from the record's, object the target, naming both |
| `stage.flags.conflict` | rejection, 2, start | `--branch` or `--at` beside `--stage` (no `--interval`) |
| `show.service.unreachable` | warning | `whether a run is in flight is unknown` |
| `snapshot.unknown`, `snapshot.id.mismatch`, `snapshot.invalid`, `snapshot.version.unsupported` | as on create | on `twin step --snapshot`, at resolve |

**Retired**: `follow.interval.invalid`, `follow.flags.conflict`, `follow.start.failed`,
`follow.stop.failed`, `follow.stopped`, `check.skipped`, `rebuild.failed`,
`step.target.foreign`; the step `follow`.

### Formats and versions

`twin.json` `10`; findings `1`, show, API `1` without the following blocks
([formats.md](formats.md)). Bundle `5`, CTM `2`, snapshot `1`, PSP `0.7` and the goldens do
not move.

### Workflows and activities

`Provision`, `Destroy`, `Step`, `Rehearse`, and the lab's fifteen activities. `Reconcile`,
the Schedule `fylgja-follow`, `ReadIntent`, `Compile`, `RunsInFlight`, `StartFollowing`
and `StopFollowing` are gone, and `bundles/.reads/` is written by nothing. The rehearsal's
baseline provision stops nothing, so every rehearsal's `deadline_s` is 30 s shorter.

### Environment

The worker reads `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` no longer.

### Upgrading

Destroy a following twin before upgrading a host of an earlier build: a Schedule
`fylgja-follow` left behind starts a workflow no worker of this build serves, and this
build carries no code to clear it.

### Tier 3 (`scripts/e2e.sh`)

Nine cases. Case 5 creates from `--branch`, edits the branch and shows, over 330 s, that no
run starts and the record, the containers and the kind line do not move; then steps to a
snapshot by file (an artifact-only change, the readback and verify 5a) and by id (a
topology change). No case makes a Schedule; the trap still refuses a stray
`fylgja-follow`.

## api.md: 019: following removed

- `twin.create` takes `branch`, `at`, `stage`, `dry_run`, `scope`, `snapshot`. A request
  carrying `interval` or `no_follow` is refused as any argument not taken: `400`, `the
  request is not one: twin.create takes no argument "interval"`, under version `1`,
  pre-1.0 as at 014, 015, 017 and 018.
- `twin.step` takes `stage`, `snapshot`, `allow_restart`, `dry_run`, `wait`, and its
  request carries one file, under the `snapshot` path, when `snapshot` is not an id, and
  none otherwise; any other is `operation.failed`, as on `twin.create`. `stage` beside
  `snapshot` is `snapshot.flags.conflict`.
- `twin.destroy`'s answer carries no following event, and its `start` is the destroy run's
  own.
- The documents lose `following`, `dry_run.follow`, `last_check` and the show kinds
  `pinned`, `frozen` and `following`; the verify block's twin gains `snapshot_id`.
