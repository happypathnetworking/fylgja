# The commands: `cli.md`'s and `api.md`'s "018: snapshots" sections

**Feature**: `018-snapshots` · **Plan**: [plan.md](../plan.md) · **Research**:
[research.md](../research.md) (R-01…R-24) · **Formats**: [formats.md](formats.md)

This is the text to land as `## 018: snapshots` in [contracts/cli.md](../../../contracts/cli.md)
and [contracts/api.md](../../../contracts/api.md), in the shape of their 017 sections.
Identifiers, exit statuses and the JSON documents are the contract; text is illustrative
except where a sentence is quoted. **Everything not named here is as 017 left it.**

## cli.md: 018: snapshots

The core's one input is the **snapshot**: one document of version `1` wrapping an
unchanged CTM `2`, with a slot for probe declarations, empty until 016, and an id of its
own, the hash of its body without the read's `observed_at`
([snapshot.schema.json](snapshot.schema.json); [D-061](../../../docs/decisions.md#d-061)).
The server takes one for every create and files it under the state root's `snapshots/`,
beside the bundles; every workflow the core runs but the reconcile takes a snapshot id
and a bundle id and never a branch. The wire is [api.md](../../../contracts/api.md), "018:
snapshots".

### The commands

```
fylgja twin create   --branch <b> [--at <t>] [--scope tag:<name>] [--interval <d> | --no-follow] [--dry-run]   # as before: the server reads, takes, files, compiles and starts
fylgja twin create   --stage <b>/<label> [--scope tag:<name>] [--no-follow] [--dry-run]                       # as before, the same way
fylgja twin create   --snapshot <id|file> [--no-follow] [--dry-run]                                         # from a snapshot alone; frozen; no read
fylgja twin compile  --snapshot <file> --out <dir>                                                          # in place of --ctm, which is retired
fylgja intent read   --branch <b> | --stage <b>/<label> [--at <t>] [--scope tag:<name>] --out <file>          # writes a snapshot, and files it
fylgja stage plan    --branch <b> [--scope tag:<name>]                                                      # each compiled stage names its snapshot
fylgja twin step     --stage <b>/<label> …                                                                  # unchanged flags; the step's sides name their snapshots
fylgja twin rehearse --branch <b> …                                                                         # unchanged flags; the rows and the report name them
```

- **`twin create --branch` and `--stage` are one step for the operator, as before.** The
  server resolves the stage if one is named, reads under the read bound (`stage.ReadTimeout`,
  five minutes), takes the snapshot and files it, compiles and files the bundle, and
  starts `fylgja-provision` with the snapshot id and the bundle id: the run begins at the
  host check and runs no read and no compile. A read or compile refusal is the server's
  document before any run, at `read` or `compile`, under the identifiers `intent read`
  and `twin compile` use; a refused read files nothing, and a refused compile leaves the
  snapshot filed, since its CTM validated. An Infrahub that fails or times out during the
  read is `operation.failed` at `read` at once; the worker's retries and heartbeat no
  longer apply to a create, as they do not to a step or a rehearsal. Following is as
  before: a `--branch` twin with no `--at` and no `--no-follow` follows its branch, and a
  twin a check's rebuild makes names no snapshot.
- **`twin create --snapshot <arg>`**: `<arg>` of 64 lowercase hex characters is a
  snapshot id, looked up in the store; anything else is a file the client reads and
  sends. An id the store does not hold is `snapshot.unknown` at `resolve`, exit 1,
  before any run; a file is read as [snapshot.schema.json](snapshot.schema.json) says and
  filed under its id (an entry already there is kept, and the twin records the stored
  document's `observed_at`, the first take's); then the compile, the filing and the run as
  above. No request reaches Infrahub. Such a twin is **frozen by rule**: its reference is
  a document, which does not move. `--interval` beside it is `follow.flags.conflict`,
  exit 2, `--interval is meaningless with --snapshot: a twin built from a snapshot never
  follows`; `--no-follow` is accepted and changes nothing; no Schedule is made whatever
  the envelope's `at` says. It has no stage, so it does not step (`step.twin.unsteppable`,
  as a `--branch` twin). `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope`
  is `snapshot.flags.conflict`, exit 2 at `start`, naming the first found in that order
  (`--branch is meaningless with --snapshot: a snapshot carries its own branch, at and
  scope`), before any connection; the scope is the snapshot's. `--dry-run` reads nothing,
  files the bundle and reports as a create's dry run does.
- **`twin compile --snapshot <file> --out <dir>`** compiles the snapshot's CTM on the
  golden tests' code path and writes the bundle, filing nothing and needing no state
  root. **`--ctm` is retired**: `unknown flag: --ctm`, exit 2, no request; the help names
  `--snapshot`. A hand user with a bare CTM wraps it: `{"snapshot_version": "1", "ctm":
  <the CTM>, "probes": []}`, leaving out `snapshot_id`, which the server computes, and
  `observed_at`, which it fills from the CTM. The repository ships the three fixture CTMs
  wrapped under `testdata/snapshot/`, each compiling to its golden.
- **`intent read --out <file>`** writes a snapshot, version `1`, with its id, and files it
  in the store, so a hand read and a create of the same intent share one stored document.
- **`twin show`** names the snapshot in the record line of every twin, or says `none`;
  for a `--snapshot` twin the kind line is what the envelope says, with a note.
- **`stage list`** is unchanged: it neither reads nor compiles.

### The text

- `twin create` and its dry run print, before the run's `start` (or the dry run's
  report):

  ```
  snapshot_id 576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482  stored: /home/…/local/snapshots/576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482.json
  bundle_id f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147  stored: /home/…/local/bundles/f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147
  ```

  The dry run's `follow:` line for `--snapshot` reads `would not follow (--snapshot given:
  a twin built from a snapshot never follows)`.
- `intent read`'s summary line ends with the snapshot: `wrote snap.json: 3 devices
  (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports
  (branch fylgja-fixture, scope tag:fylgja, schema 7c413536…); snapshot 576933ec…, stored at
  /home/…/local/snapshots/576933ec….json` (the ids in full); with a stage, as 014 has it.
- `twin compile` prints `wrote bundle to <dir> (3 nodes, 3 links)`, then `snapshot_id
  <id>`, then `bundle_id <id>`.
- `stage plan` prints, under each compiled stage, `  snapshot_id <id>` then `  bundle_id
  <id>`, then its read line as before.
- `twin step`'s twin line reads `twin: stage change-1/seeded (snapshot 1a2b3c4d…, bundle
  5e6f7a8b…), pinned at …; 3 nodes`, `snapshot none` for a record of `8`.
- `twin show`'s record line reads `record: branch fylgja-fixture, snapshot
  576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482, bundle_id
  f764e1fa…, schema 7c413536…, scope tag:fylgja, read by infrahub-dcim from
  opsmill/schema-library@26336e9`; `record: branch b, snapshot none, bundle_id …` for a
  `9` naming none (a twin `twin provision` built, or a following rebuild made); `record:
  branch b, snapshot none (record 8), bundle_id …` for a record of `8` or earlier. `twin
  create` and `twin provision` print the same line for the twin they made.
- `twin show`'s kind line for a `--snapshot` twin: `kind: pinned at
  2026-10-27T14:13:38.380155Z; not following; built from snapshot 576933ec…` with an `at`
  in the envelope, `kind: frozen; not following; built from snapshot 576933ec…` without;
  the note `built from snapshot <id>` (in full) joins the notes. `from a bundle` is
  unchanged.
- The rehearsal's report table gains the column `snapshot` before `bundle`, eight
  characters and an ellipsis, `—` on a refused stage:

  ```
  | stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |
  ```

- The refusals, as they print:

  ```
  rejection snapshot.unknown [step resolve] 0000…0000: the store under /home/…/local/snapshots holds no snapshot 0000…0000; a snapshot id comes from a create, a dry run, a plan or intent read --out on this server
  rejection snapshot.id.mismatch snap.json: snap.json declares snapshot_id 1111…1111, but its body hashes to 576933ec…; leave snapshot_id out to have it computed
  rejection snapshot.version.unsupported snap.json: the snapshot declares snapshot_version "2"; this build reads "1", and nothing converts one
  rejection snapshot.invalid probes: probes holds 1 entry; in snapshot 1 the list is required and empty, since 016 defines its element
  rejection snapshot.flags.conflict [step start] --branch: --branch is meaningless with --snapshot: a snapshot carries its own branch, at and scope
  rejection follow.flags.conflict [step start] --interval: --interval is meaningless with --snapshot: a twin built from a snapshot never follows
  rejection ctm.version.unsupported snap.json: the CTM declares ctm_version "1"; this build reads "2", and nothing converts one
  rejection data.required.missing ctm.envelope.fidelity: ctm.envelope.fidelity, the reader's fidelity list, is not recorded: …
  ```

  (`[step resolve]` on `twin create --snapshot`; no step on `twin compile`.)

### Identifiers

Five added. No status, step or exit is new.

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `snapshot.invalid` | rejection, 1, none (`twin compile`) or `resolve` (`twin create --snapshot <file>`) | the field, or the file | the outer shape is not version 1's: an unknown key, `ctm` absent or not an object, `probes` absent, null or not empty, `snapshot_id` not 64 lowercase hex characters, `observed_at` not of the CTM's form or not the inner CTM's |
| `snapshot.version.unsupported` | rejection, 1, none or `resolve` | the file | `snapshot_version` is not `"1"`, or absent; names the version read, or that none was, and `"1"` |
| `snapshot.id.mismatch` | rejection, 1, none or `resolve`; `compile` for the store | the file, or the store path | a declared `snapshot_id` is not what the body hashes to, naming both; or an entry under the id hashes to another, naming the path and both |
| `snapshot.unknown` | rejection, 1, `resolve` | the id | `twin create --snapshot <id>` names an id the store does not hold; names the store's directory |
| `snapshot.flags.conflict` | rejection, 2, `start` | the flag | `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope`, the first found in that order; before any connection |

`follow.flags.conflict` gains the `--snapshot` sentence. The inner CTM's faults keep
`ctm.version.unsupported` and `data.required.missing`, the object prefixed `ctm.`;
validation's rules refuse at compile as they do a bare CTM. The client's own refusal of a
snapshot file it cannot read is `operation.failed`, exit 2, `reading snapshot: open
<path>: …`, before any connection, as for a CTM at M13.

### Formats and versions

| Format | Version | Change |
|---|---|---|
| snapshot | `1` | new: [snapshot.schema.json](snapshot.schema.json), `$id` `…/contracts/snapshot/v1` |
| `twin.json` | `9` | `snapshot_id` (string or null); `source` gains `snapshot`; `step.from.snapshot_id` and `step.to.snapshot_id`, optional ([formats.md](formats.md)) |
| findings | `1` | `snapshot_id` beside `bundle_id` on `twin.compile`, `intent.read`, `twin.create` and `twin.step`; `dry_run.follow.reason` gains `snapshot`; `plan.stages[].snapshot_id`, `rehearsal.stages[].snapshot_id` (string or null); `step` sides' optional `snapshot_id`; `show.record.snapshot_id` (string or null), `show.record.source` gains `snapshot`, `show.record.step` sides' optional `snapshot_id`; the five identifiers |
| the API | `1` | `snapshot` on `twin.create`, with one file beside it; `twin.compile`'s `ctm` becomes `snapshot`; `intent.read` answers `snapshot.json` ([api.md](../../../contracts/api.md)) |
| bundle manifest, CTM, PSP | `5`, `2`, `0.7` | none: the goldens stand |

- `twin compile --snapshot` refuses a snapshot of another version, or declaring none,
  `snapshot.version.unsupported`, never reading it as a `1`; the inner CTM's version and
  required fields as 017 refuses a bare CTM's, the object prefixed `ctm.`.
- The bundle's CTM sidecar `<bundle_id>.ctm.json` is retired: no build writes one and the
  ones on disk are never read. `bundles/.reads/` stays, the reconcile's alone.
- A `9` record reads with its snapshot; an `8` reads with none: `twin show` says `snapshot
  none (record 8)`, `twin step` steps it with a from side naming no snapshot, `twin
  destroy` clears it.

### Workflows and activities

None is added, removed or changed: no workflow decision, activity, budget or version
marker. `ProvisionInput`, `RecordInput`, `StepSide` and `RehearseStage` carry
`snapshot_id`, omitted when empty, so the nine recorded histories replay; the runs branch
on nothing of it. Every `fylgja-provision` the server starts is already compiled, as a
check's rebuild has been since M4, so its history holds no `ReadIntent` and no `Compile`;
the provision workflow keeps its read-and-compile branch for the recorded histories and
the reconcile keeps both activities. The `Compile` activity files no sidecar.

### Tier 3 (`scripts/e2e.sh`)

The nine cases, unchanged in what they assert but the records': the read-then-compile
helper reads with `--out` and compiles with `--snapshot`; every create asserts
`snapshots/<snapshot_id>.json` exists and that no `bundles/*.ctm.json` is newer than the
case's start, since the host's store keeps the sidecars of every read before this feature;
`twin.json` names the create's snapshot; case 1's `twin show` text holds `snapshot <id>,
bundle_id <id>`; case 5's rebuilt twin reads `.show.record.snapshot_id == null`; case 7's
steps name the target's snapshot. No case is added.

## api.md: 018: snapshots

The core's one input is the snapshot ([D-061](../../../docs/decisions.md#d-061);
[cli.md](../../../contracts/cli.md), "018: snapshots", says what each command does). The
API's version stays `1`: a client that never sends `snapshot` is served as before. Every
operation, the transport, the token, the frames, the statuses and the files are as 017
left them, but for these.

| | Operation | `args` | Files in | Files out |
|---|---|---|---|---|
| argument added | `twin.create` | `snapshot` | the snapshot, when `snapshot` is a path | |
| argument renamed | `twin.compile` | `snapshot` (was `ctm`) | the snapshot, under the path given | the bundle |
| file renamed | `intent.read` | | | `snapshot.json` (was `ctm.json`) |

- **`snapshot`** on `twin.create` is `--snapshot` as given: 64 lowercase hex characters
  name a snapshot the store holds, and the request carries no file; anything else is the
  path of a file the client read, and the request carries that one file under that path.
  The guards are the server's, before any connection: `snapshot` beside `branch`, `stage`,
  `at` or `scope` is `snapshot.flags.conflict` at `start`, exit 2, naming the first
  found; beside `interval`, `follow.flags.conflict`; `no_follow` and `dry_run` are
  accepted. A request carrying a file beside no `snapshot`, two files, or one under
  another path than `snapshot` gives, is refused before anything is parsed,
  `operation.failed`, exit 2, as `twin.compile`'s are (`the request carries 1 file where
  twin create takes a snapshot file beside --snapshot alone`). An id the store does not
  hold is `snapshot.unknown` at `resolve`, exit 1.
- **`twin.compile`** takes `snapshot` and `out`, and `files` holds the snapshot under the
  path `snapshot` gives, as it held the CTM under `ctm`; a request carrying `ctm` is `400`,
  `the request is not one: twin.compile takes no argument "ctm"`, pre-1.0 as 014 renamed
  `series` to `stage`. The snapshot is read as [snapshot.schema.json](snapshot.schema.json)
  says: `snapshot_id` and `observed_at` optional, computed and filled when absent, checked
  when present. The answer's `files` frame holds the bundle, as before; nothing is filed.
- **`intent.read`**'s `files` frame holds `snapshot.json`, a snapshot `1` with its id,
  before the summary line; the server files it in its store. A refused read has no `files`
  frame.
- **The documents** stay `findings_version` `1`: `snapshot_id` beside `bundle_id` where
  [cli.md](../../../contracts/cli.md) says; the blocks' new keys are
  [formats.md](formats.md)'s. The five identifiers are cli.md's.
- **The files**: a snapshot is snapshot `1`; a CTM sent bare is refused
  `snapshot.version.unsupported` (it declares no `snapshot_version`); the bundle is `5`
  as before. A snapshot holds configuration, as the CTM did: it crosses as a file and
  never in a document, a finding or a log line.
- **The checks** `fylgja-step` and `fylgja-twin` send nothing new: the plan's and the
  rehearsal's documents gain a key per stage, which neither reads, and the report's table
  gains a column.
