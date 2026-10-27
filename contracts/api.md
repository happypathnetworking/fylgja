# API contract: M13, version 1; 014's stage surface; 015's rehearsal; 017's scope; 018's snapshots

What crosses between a client and `fylgja serve`. The shapes are
[api.schema.json](api.schema.json); the documents are M12's
([findings.schema.json](findings.schema.json) and the blocks beside it), as 014 moved them
("014: the stage surface", at the end) and 015 added to them ("015: the rehearsal", after
it), and 017 moved them again ("017: the scope and the DCIM reader"), and 018 added the
snapshot ("018: snapshots", last). The addresses, the statuses, the frame kinds and the
document are the contract; a sentence is contract only where it is quoted.

## Transport

HTTP/1.1, JSON, no TLS (D-040, D-042). The server listens on every address `--listen`
gives, which is repeatable since 015, and on `127.0.0.1:7650` when none is; on the lab
host, on loopback and on the host's Docker bridge, where Infrahub's task workers reach it
(D-050). A client on another machine comes through an SSH tunnel or a
proxy the operator runs; a client's address may be an `https://` URL for such a proxy.
The API never redirects, and a client follows no redirect: a `3xx` is the status it
answered, and nothing is sent to its `Location`.

## The version

- The API's version is `1` and is the first element of every path: `/v1/…`.
- Every answer to a request that carried the token has `Fylgja-Api-Version: 1` and
  `Fylgja-Build: <build>`.
- A path under no version the server serves is `404` with `Fylgja-Api-Versions: <list>`.
  The server has read and done nothing for it.
- A path under `/v1/` that names no operation, or an operation's path asked with a method
  other than `POST`, is `404` **without** `Fylgja-Api-Versions`, since the version is
  served: `API version 1 has no operation at this path; nothing was read or done`. A
  client reads it as `answered 404 Not Found`, never as a version it does not speak.
- `1` is kept by a new operation, a new optional argument, a new frame kind and a new
  block of the document. A client ignores a frame kind it does not know.

## The token

- Every request carries `Authorization: Bearer <token>`.
- A request without it, or with another, is `401` with `WWW-Authenticate: Bearer`,
  before the route is looked up, the body read, a guard run or anything dialled.
  `OPTIONS *` is such a request too: `net/http` does not answer it itself.
- A request that carries files sends `Expect: 100-continue`; the `401` then arrives
  before any of the body is sent.
- No answer, body, frame or header carries a token.

## The operations

Each is `POST`, with a JSON body ([`$defs/request`](api.schema.json)) and an answer of
frames. A dry run is its operation with `dry_run` set.

| Operation | Path | `args` | Files in | Files out | Takes an interrupt |
|---|---|---|---|---|---|
| `twin.create` | `/v1/twin/create` | `branch`, `at`, `stage`, `interval`, `no_follow`, `dry_run`, `scope`, `snapshot` | the snapshot, when `snapshot` is a path | | from `start` |
| `twin.provision` | `/v1/twin/provision` | `bundle`, `dry_run` | the bundle's regular files | | from `start` |
| `twin.step` | `/v1/twin/step` | `stage`, `allow_restart`, `dry_run`, `wait` | | | from `start` |
| `twin.destroy` | `/v1/twin/destroy` | | | | no |
| `twin.show` | `/v1/twin/show` | | | | no |
| `twin.verify` | `/v1/twin/verify` | `wait`, `args` | | | no |
| `twin.rehearse` | `/v1/twin/rehearse` | `branch`, `scope` | | | from `start` |
| `twin.compile` | `/v1/twin/compile` | `snapshot`, `out` | the snapshot | the bundle | no |
| `stage.list` | `/v1/stage/list` | `branch`, `scope` | | | no |
| `stage.plan` | `/v1/stage/plan` | `branch`, `scope` | | | no |
| `intent.read` | `/v1/intent/read` | `branch`, `at`, `stage`, `out`, `scope` | | the snapshot | no |
| `schema.check` | `/v1/schema/check` | `branch` | | | no |
| `psp.validate` | `/v1/psp/validate` | `files` | each package | | no |

There is no other operation. In particular there is none to re-attach to a run, to list
runs or to fetch a filed bundle. Moved at 014: `waypoint.list` and `waypoint.plan`
(`/v1/waypoint/list`, `/v1/waypoint/plan`, argument `series`) became `stage.list` and
`stage.plan`, and `twin.create`, `twin.step` and `intent.read` take `stage` where they took
`waypoint`. Added at 015: `twin.rehearse`. Added at 017: the argument `scope` on
`twin.create`, `twin.rehearse`, `intent.read`, `stage.list` and `stage.plan`. Moved at 018:
`twin.compile` takes `snapshot` and the snapshot where it took `ctm` and the CTM,
`intent.read` answers with a snapshot where it answered with the CTM, and `twin.create`
takes the argument `snapshot`, with the snapshot's file when it is a path.

**Arguments are as given.** An absent key is a flag that was not given; a present key is
one that was, whatever its value (`"interval": ""` is `--interval=`). Every guard is the
server's, under M12's identifier, wording and exit status, and each is made before the
server connects to Infrahub or the workflow service where M2–M12 said "before any
connection". A path in `args` is used for wording and the document's subject alone: the
server opens no path a client names.

**The request is decoded strictly.** Each of these is `400` before the answer begins,
with a message that begins `the request is not one: `, and no guard runs:

- a key the server does not know, anywhere in it, or one not spelled as the schema spells
  it (`unknown field "ARGS"`; `unknown field "PATH" in files[0]`), since a key is matched
  exactly, whatever its case would match;
- an argument the operation does not take (`twin.show takes no argument "branch"`), or
  one of another kind, `null` included (`twin.create's argument "branch" is not a
  string`; a flag's value is a boolean, `args` and `files` arrays of strings, with no
  `null` element);
- `twin.provision` without `bundle`, which M12's command took as its one argument
  (`twin.provision takes the bundle directory as its argument "bundle"`), and `twin.verify`
  with `args` and no `wait`, whose words only a bare `--wait` leaves behind
  (`twin.verify's argument "args" is given without "wait"`); no client's command builds
  either, and the answer would name `""` as the directory or ignore the argument;
- files on an operation that takes none (`twin.show takes no files`), a file that is
  `null` (`files[0] is not a file`) or has no path, data that is not base64, or bytes
  after the object;
- a `render` other than `"text"`, `"json"` and `"markdown"` (the last added at 015).

[`$defs/request`](api.schema.json) is what a client sends. The server also reads `render:
""`, `"args": null` and `"files": null` as absent, and a file without `data` as one with
no bytes.

## The answer

`200`, `Content-Type: application/x-ndjson`. One JSON object a line
([`$defs/frame`](api.schema.json)), written as it happens. The last line is always the
`document` frame.

| Frame | Meaning |
|---|---|
| `{"out": "…"}` | text for stdout, whole lines |
| `{"err": "…"}` | text for stderr, whole lines |
| `{"start": {"workflow_id": "…"}}` | the server begins to start this run; from here an interrupt reaches it, but for `twin.destroy`'s, `fylgja-destroy`, which opens no stream |
| `{"run": {"workflow_id": "…", "run_id": "…"}}` | the run's identity |
| `{"event": {…}}` | one step boundary of a run, or one notice about a run |
| `{"files": [{"path": "…", "data": "<base64>"}]}` | the CTM (`ctm.json`; since 018 the snapshot, `snapshot.json`), or every file of the bundle |
| `{"document": {…}, "text": "…", "markdown": "…"}` | the command's findings document; `text` under `render: "text"` or `"markdown"` when it has findings; `markdown` under `render: "markdown"` on `twin.rehearse` alone (015) |

**What `render` asks for.**

| `render` | `out` | `err` | `document.text` |
|---|---|---|---|
| absent | none | none | none |
| `"text"` | every line the command printed without `--json` at M12 | every line it wrote to stderr | its findings as text |
| `"json"` | none | what it wrote to stderr under `--json` | none |
| `"markdown"` (015) | as under `"text"` | as under `"text"` | as under `"text"`; on `twin.rehearse`, `document.markdown` beside it |

With `render` absent, a command that is one answer is its `document` frame alone, but for
`intent.read` and `twin.compile`, whose `files` frame comes first. A run is its `start`,
its `run`, its `event`s and its `document`, and `twin.destroy` its following's `event`s,
its `start`, the destroy's `event`s and its `document`, with no `run`.

**The document** is the one the command printed under `--json` at M12:
`findings_version` `1`, the same operation, status, subject, blocks and findings. Its
`status` is the command's outcome, and `ok`, `rejected`, `error`, `failed`, `unclean`,
`diverged` and `nonconforming` keep exits 0, 1, 2, 3, 4, 4 and 5.

**An answer with no `document` frame did not finish.** The server stopped, or the
connection was lost.

## The transport's statuses

A command that ran is `200` whatever it decided. Every other status is the transport's
own fault, with a body of [`$defs/problem`](api.schema.json).

| Status | When | The server has |
|---|---|---|
| `401` | no token, or a wrong one | read nothing |
| `404` | a path under no version served, with `Fylgja-Api-Versions`; a path under `/v1/` that names no operation, or the wrong method, without it; a path not in its clean form (`//v1/twin/show`), or `/v1` without its slash, as the path it cleans to, never a redirect; an interrupt for a stream that is not open | done nothing |
| `413` | a body over 33,554,432 bytes (32 MiB); the body names `limit_bytes` | read and filed nothing |
| `400` | a body that is not a request (above); a `Fylgja-Stream` that is not a stream identity | run no guard |
| `409` | `Fylgja-Stream` names a stream that is open | run no guard |
| `204` | an interrupt delivered | |

## A run

`twin.create`, `twin.provision` and `twin.step` start a run and stay open as its
progress, and so does `twin.rehearse` (015). `twin.destroy` is followed the same way and takes no interrupt. Its `start`
comes once following has stopped, just before the destroy run is started, and opens no
stream; its answer has no `run` frame, and the document's `subject.run_id` names the
destroy run. An answer cut after its `start` says a run may have been started and was not
cancelled, and one cut while following stops says nothing of a run.

```text
POST /v1/twin/create        Fylgja-Stream: 5f1c9a…
← {"start":{"workflow_id":"fylgja-provision"}}
← {"run":{"workflow_id":"fylgja-provision","run_id":"01a1…"}}
← {"event":{"workflow_id":"fylgja-provision","step":"read","finding_step":"read","end":false}}
← {"event":{"workflow_id":"fylgja-provision","step":"read","finding_step":"read","end":true,"outcome":"done","duration_s":2.1}}
  …
← {"document":{"findings_version":"1","operation":"twin.create","status":"ok",…}}
```

- A refusal before the start is the `document` frame, with no `start`.
- `Fylgja-Stream` is the client's name for this answer: 16 random bytes in hex. Without
  it the run cannot be interrupted. A value that is not one unescaped path segment of at
  most 128 characters is `400`, `the request is not one: Fylgja-Stream is not a stream
  identity`. On an operation that takes no interrupt the header is ignored, and opens
  nothing.
- **A client that goes away leaves its run running.** A start still waiting for a worker
  finishes, and the run goes on for that worker, as M12's killed process left it; only the
  operator's interrupt abandons a start. The same holds when the server stops.
- Two clients asking at once are refused as two shells were: by the fixed workflow
  identities, under `run.in_flight`. The server adds no lock.

### `POST /v1/streams/{stream}/interrupt`

The operator's interrupt, delivered to the answer `{stream}` names. No body.

| Arrives | Effect, as since M2 |
|---|---|
| the start still waiting for a worker | the start is abandoned; the answer ends with `run.cancelled`, exit 2 |
| the run followed, the first | the run is asked to cancel; the answer goes on to the run's own end |
| the second | the answer ends with `run.cancelled`, `stopped waiting for run <id>; …`; the run goes on |

`204` when delivered. `404` when no such answer is open. A client sends one only after
`start`: before it, the operator's interrupt ends the client, and the server stops the
request's work.

### The event

[`$defs/event`](api.schema.json): `workflow_id`, `step`, `finding_step`, `end`,
`outcome` (`done`, `failed`, `timed out`, `cancelled`), `duration_s`, `detail`, `rule`,
`message`; or `notice` alone. They are read from the run's history. The server keeps
nothing to produce them.

## Files

Each file crosses whole, as base64, in the one request or the one `files` frame. The
bytes written are the bytes read.

- **`twin.compile`** (moved at 018: the snapshot under `args.snapshot`, "018: snapshots"):
  `files` holds the CTM under the path given. The answer's `files`
  frame holds the bundle, each file under its path inside it. A golden CTM comes back
  as the golden bundle, byte for byte. A request carrying no file or two, or one file
  under another path than `args.ctm`, is refused before anything is parsed:
  `operation.failed`, exit 2, in a sentence naming the count (`the request carries 0 files
  where twin compile takes the CTM alone`) or the path's mismatch (`the request carries its
  CTM under another path than --ctm gives, where twin compile takes the CTM alone, under
  that path`), and nothing of the file.
- **`intent.read`**: the answer's `files` frame holds `ctm.json` (since 018
  `snapshot.json`), before the summary line. A refused read has no `files` frame.
- **`twin.provision`**: `files` holds every regular file of the bundle directory, each
  under its slash-separated path inside it. The server verifies and files it, and every
  refusal names the directory as `args.bundle` gave it. Files that cannot all be files of
  one bundle, a path that is `.` or `..`, one beneath another path sent, one sent twice, or
  one not in canonical form, are refused before anything is written: `operation.failed` at
  step `verify`, in a sentence naming the path inside the bundle (`bundle path ".." escapes
  the bundle root`).
- **`psp.validate`**: `files` holds each package under the path given, in order. Every
  finding names that path. A request whose `files` are not one package for each path of
  `args.files`, in order and under that path, or that names no path, is refused before
  anything is validated: `operation.failed`, exit 2, in a sentence giving the two counts
  (`the request carries 0 files for 1 path where psp validate takes at least one path and
  one package for each, in order and under that path`).

## What the server keeps and logs

- It keeps nothing between two requests. While a run's answer is open it holds the
  channel that answer's interrupts arrive on, and nothing once the answer ends.
- It logs one line a request, when the request ends: the operation, the outcome and the
  duration ([cli.md](cli.md), `fylgja serve`, names every outcome). Never an argument, a
  path a request named, a body, a token or a login. A request cut short by the server's own
  stop may log `client_gone`, when its handler returns before the process exits, or no
  line at all.

## By hand

```sh
curl -sS -X POST -H "Authorization: Bearer $FYLGJA_API_TOKEN" \
     -d '{}' http://127.0.0.1:7650/v1/twin/show | jq .document
```

One line comes back: the `document` frame, which is `fylgja twin show --json`'s
document.

## 014: the stage surface

A proposed change's stages replace the waypoint ([D-045](../docs/decisions.md#d-045);
[cli.md](cli.md), "014: the stage surface", says what each command does). The API's
version stays `1`: it is pre-1.0, and every other operation, the transport, the token, the
frames, the statuses and the files are as M13 left them.

| | Operation | Path | `args` |
|---|---|---|---|
| removed | `waypoint.list` | `/v1/waypoint/list` | `series` |
| removed | `waypoint.plan` | `/v1/waypoint/plan` | `series` |
| added | `stage.list` | `/v1/stage/list` | `branch` |
| added | `stage.plan` | `/v1/stage/plan` | `branch` |
| renamed argument | `twin.create`, `twin.step`, `intent.read` | | `stage` for `waypoint` |

- `/v1/waypoint/list` and `/v1/waypoint/plan` are `404`, as any path under `/v1/` that names
  no operation. A request carrying `waypoint` is `400`: `the request is not one: twin.create
  takes no argument "waypoint"`.
- `stage` is the reference as given, `<branch>/<label>`. Present and empty is `--stage=`,
  and `branch` present and empty on `stage.list` or `stage.plan` is `--branch=`: each is
  refused `stage.ref.invalid` at `start`, exit 2, before the server connects to Infrahub.
  `stage.list` without `branch` lists every open proposed change's stages; `stage.plan`
  without it is `operation.failed`, `--branch is required`, exit 2.
- `stage.list` and `stage.plan` are one answer each, their `document` frame alone when no
  rendering is asked for, and take no interrupt. The plan files each bundle and its CTM in
  the store on the lab host (since 018 each stage's snapshot and no CTM sidecar: "018:
  snapshots"); there is still no fetch by identifier.
- [api.schema.json](api.schema.json)'s `args` definitions move with the table. The
  documents' blocks are [findings.schema.json](findings.schema.json)'s at version `1`: the
  `stage`, `stages` and `plan` blocks of [stages.schema.json](stages.schema.json), which
  replaces `waypoints.schema.json`, and `twin.json` `6`'s stage in `show`, `step` and
  `verify`.

## 015: the rehearsal

A proposed change rehearsed on a twin ([D-049](../docs/decisions.md#d-049)–[D-052](../docs/decisions.md#d-052);
[cli.md](cli.md), "015: the rehearsal", says what the command does and how it exits). The
API's version stays `1`: a new operation, a new value of `render` and a new field of the
`document` frame, each of which a client of M13 never asks for or ignores. Every other
operation, the token, the statuses and the files are as 014 left them.

| | Operation | Path | `args` | Files in | Files out | Takes an interrupt |
|---|---|---|---|---|---|---|
| added | `twin.rehearse` | `/v1/twin/rehearse` | `branch` | | | from `start` |

- **`branch`** is the proposed change's source branch, as `--branch` gave it. Present and
  empty is `--branch=`, refused `stage.ref.invalid` at `start`, exit 2; absent is
  `operation.failed`, `--branch is required`, exit 2. Both are refused before the server
  connects to Infrahub.
- **The answer** is a run's ([A run](#a-run)). A refusal before the start, a stage refused,
  the deadline unfit, a run in flight or the host held, is the `document` frame alone, after
  the plan's `out` lines under a rendering, with no `start`. A **reclaim**, of a twin whose
  record names a rehearsal run no longer running, is followed inside the answer before the
  `start`: under a rendering, the `out` line `reclaiming the twin of rehearsal run <id>`,
  then its destroy's events, with neither a `start` nor a `run` frame of their own. Then
  `{"start": {"workflow_id": "fylgja-rehearse"}}`, the `run` frame, and the events of the
  run and of each child, `fylgja-provision`, `fylgja-step` and `fylgja-destroy`, each child
  announced by the notice `run <workflow> <id>` and, under a rendering, preceded by an
  `out` line: `stage <ref>: …` before the provision and each step, `destroying the twin`
  before the destroy. The `document` frame comes once the run has closed and the
  stages have been resolved again. Its document is `findings_version` `1`, operation
  `twin.rehearse`, with the `rehearsal` block of
  [rehearsal.schema.json](rehearsal.schema.json).
- **`render: "markdown"`**: the `out` and `err` frames and `document.text` are as under
  `"text"`, and on `twin.rehearse` the `document` frame carries `markdown`, the report as
  GitHub-flavoured markdown, rendered from the document and the plan's steps between the
  stages; it is a rendering, never part of
  the document. Every other operation answers `"markdown"` as it answers `"text"`, with no
  `markdown` field. [api.schema.json](api.schema.json)'s `render` enum, its `document` frame
  and `start.workflow_id`'s enum, which gains `fylgja-rehearse`, move with it.
- **The interrupt** is `POST /v1/streams/{stream}/interrupt`, from `start`, as for a create.
  The first asks the run to cancel: it cancels the child in progress and destroys the twin,
  and the answer goes on to the run's own end. The second ends the answer with
  `run.cancelled`, and the run goes on to its destroy. An answer cut, or a client gone,
  leaves the run running to its destroy.
- **Beside a rehearsal**: `twin.show`'s `show.record.rehearsal` is `{workflow_id, run_id}`,
  absent when the record names no rehearsal, and `in_flight` names the rehearsal with its
  child; `twin.verify`'s `verify.twin.rehearsal` is the same or `null`; `twin.destroy` cancels a rehearsal in flight, follows
  its destroy after the notice `cancelling rehearsal run <id>; waiting for its destroy`, then
  makes its own; `twin.create`, `twin.provision` and `twin.step` are refused `run.in_flight`,
  naming it.

**Clients inside Infrahub.** The checks `fylgja-step` and `fylgja-twin` run in Infrahub's
task workers and are clients of the API like any other: they send the one token, read
`Fylgja-Api-Version`, and never follow a redirect. `fylgja-step` asks `stage.plan` with
`render: "text"`; `fylgja-twin` asks `twin.rehearse` with `render: "markdown"` and a
`Fylgja-Stream`, reads the answer with no read timeout, and interrupts its run at its own
deadline, or with a blocking call when Infrahub cancels it. They reach the server at
`host.docker.internal:7650`, the host's Docker bridge address, which `--listen` names
beside loopback on the lab host ([D-050](../docs/decisions.md#d-050)); the token crosses
the bridge unencrypted, as the server's start-up report says, and
[SECURITY.md](../SECURITY.md) says what that exposes. One token guards every address, a
request is answered alike on each, and the request log names no address.

By hand, the report as the comment carries it:

```sh
curl -sS -N -X POST -H "Authorization: Bearer $FYLGJA_API_TOKEN" \
     -d '{"render":"markdown","args":{"branch":"change-1"}}' \
     http://127.0.0.1:7650/v1/twin/rehearse | jq -r 'select(.document) | .markdown'
```

## 017: the scope and the DCIM reader

The Infrahub reader reads the schema library's DCIM at `opsmill/schema-library@26336e9`,
and a twin is of a scope ([D-057](../docs/decisions.md#d-057); [cli.md](cli.md), "017: the
scope and the DCIM reader", says what each command does). The API's version stays `1`: a
client that never sends `scope` is served under the server's default. Every operation, the
transport, the token, the frames, the statuses and the files are as 015 left them.

| | Operation | `args` |
|---|---|---|
| argument added | `twin.create`, `twin.rehearse`, `intent.read`, `stage.plan`, `stage.list` | `scope` |

- **`scope`** is `--scope` as given, `tag:<name>`: the devices every read of the request
  selects. Absent is the server's `FYLGJA_DEFAULT_SCOPE`. Present and empty (`"scope": ""`)
  is `--scope=`, and a value that is not `tag:<name>` is refused `scope.invalid` at `start`,
  exit 2; absent beside a server with no default is `scope.unset` at `start`, exit 2. Each
  is refused before the server connects to Infrahub, after the `branch` and `stage` guards.
- **`twin.step`** takes none: a request carrying it is `400`, `the request is not one:
  twin.step takes no argument "scope"`. The step reads under the scope its twin's record
  carries. No operation that reads no intent takes it.
- **The documents** stay `findings_version` `1`: `subject.scope` names the scope once it is
  resolved; `schema.check`'s `verified` is `{model, version, kinds: [{kind, fields}],
  stages}`, without `contract_version` and `generics`; `twin.show`'s `show.record` carries
  the record's `scope` and `mapping` and no `contract_version`. The seventeen identifiers
  are [cli.md](cli.md)'s.
- **The files**: `intent.read`'s `ctm.json` is CTM `2` ([ctm.schema.json](ctm.schema.json)),
  and `twin.compile` takes a CTM `2` alone, refusing another, or one declaring none,
  `ctm.version.unsupported`, and one leaving out `envelope.fidelity`, `links` or a
  device's `interfaces` `data.required.missing`, and answers with a bundle `5`
  ([manifest.schema.json](manifest.schema.json)); `twin.provision`
  refuses a bundle `4` `bundle.version.unsupported`. A package sent to `psp.validate` is
  format `0.7` ([psp.schema.json](psp.schema.json)), with `platform.matches`. The twin's
  record is `twin.json` `8` ([twin.schema.json](twin.schema.json)). The contract version is
  retired: the CTM's version is the contract's.
- **The checks** `fylgja-step` and `fylgja-twin` send no `scope`: they are served under the
  default of the server they reach, and a server with none refuses each `scope.unset`. They
  pass over a branch point refused `scope.empty` alone, where they passed over
  `contract.node.missing`.

## 018: snapshots

The core's one input is the snapshot ([D-061](../docs/decisions.md#d-061);
[cli.md](cli.md), "018: snapshots", says what each command does). The API's version stays
`1`: a client that never sends `snapshot` is served as before. Every operation, the
transport, the token, the frames, the statuses and the files are as 017 left them, but for
these.

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
  `series` to `stage`. The refusals of a request's files are "Files"' with the snapshot for
  the CTM (`the request carries 0 files where twin compile takes the snapshot alone`; `the
  request carries its snapshot under another path than --snapshot gives, where twin
  compile takes the snapshot alone, under that path`). The snapshot is read as
  [snapshot.schema.json](snapshot.schema.json) says: `snapshot_id` and `observed_at`
  optional, computed and filled when absent, checked when present. The answer's `files`
  frame holds the bundle, as before; nothing is filed.
- **`intent.read`**'s `files` frame holds `snapshot.json`, a snapshot `1` with its id,
  before the summary line; the server files it in its store. A refused read has no `files`
  frame.
- **The documents** stay `findings_version` `1`: `snapshot_id` beside `bundle_id` where
  [cli.md](cli.md) says; the blocks' new keys are their schemas'
  ([show.schema.json](show.schema.json), [stages.schema.json](stages.schema.json),
  [step.schema.json](step.schema.json), [rehearsal.schema.json](rehearsal.schema.json)),
  each named in cli.md's "018: snapshots", "Formats and versions". The five identifiers are
  cli.md's.
- **The files**: a snapshot is snapshot `1`; a CTM sent bare is refused
  `snapshot.version.unsupported` (it declares no `snapshot_version`); the bundle is `5`
  as before. A snapshot holds configuration, as the CTM did: it crosses as a file and
  never in a document, a finding or a log line.
- **The checks** `fylgja-step` and `fylgja-twin` send nothing new: the plan's and the
  rehearsal's documents gain a key per stage, which neither reads, and the report's table
  gains a column.
