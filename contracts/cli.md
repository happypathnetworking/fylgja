# CLI contract: M13 — API; 014 — the stage surface

Extends the CLI as M2–M12 built it, and 014 moves it once more: the section "014: the
stage surface" at the end says what moved. **Everything not named here is as M12 left it**:
every command's text on stdout and stderr, its `--json` document, each identifier, step,
object and message, and each exit status. Identifiers, exit statuses and the JSON
documents are the contract; text is illustrative except where a sentence is quoted. The
wire is [api.md](api.md). At M13 the nine schemas beside `api.schema.json` were M12's byte
for byte: bundle `4`, CTM `1`, PSP `0.6`, `twin.json` `5`, findings `1`; 014 moved the
findings blocks, `twin.json` to `6` and the schemas that carry the record's stage.

## `fylgja serve [--listen <host:port>] [--psp-dir <dir>]`

The API's server: a role of the binary, run on the lab host beside `fylgja worker run`,
as a process of its own. It serves until interrupted, prints its start-up report on
stdout and logs on stderr, and produces no findings document.

It refuses to start, exit 2, before it listens, in this order:

| When | Lines on stderr |
|---|---|
| a usage error: an argument, an unknown flag, or a flag without its value; no findings document, under `--json` too | `fylgja serve: <cobra's error>`, for example `fylgja serve: unknown command "extra" for "fylgja serve"` or `fylgja serve: unknown flag: --nope` |
| `FYLGJA_API_TOKEN` is unset or empty | `fylgja serve: FYLGJA_API_TOKEN is not set; the server does not start without the API's token` |
| `--listen` is not `host:port` | `fylgja serve: --listen <value> is not host:port` |
| the state root cannot be resolved | `fylgja serve: <error>` |
| an override package `psp validate` rejects | that package's findings as text, then `fylgja serve: refusing to serve with an invalid support package` |
| the override directory cannot be read | `fylgja serve: support package override directory: <error>` |
| the address cannot be listened on | `fylgja serve: listening on <address>: <error>` |

The report:

```
fylgja serve: listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)
fylgja serve: state root /srv/fylgja/local (bundles: /srv/fylgja/local/bundles, twin: /srv/fylgja/local/twin)
fylgja serve: the workflow service (localhost:7233, namespace default) and Infrahub are dialled when a request needs them
fylgja serve: host memory budget: unset (memory sums will be warnings)
fylgja serve: probe login nokia_srlinux: FYLGJA_SRLINUX_USERNAME set, FYLGJA_SRLINUX_PASSWORD set
fylgja serve: <the package's line, as fylgja worker run prints it>
```

two lines a support package, the worker's own, and, when `--listen` names an address that
is not loopback, a line straight after the listen line, which it qualifies:

```
fylgja serve: listening on 0.0.0.0:7650 (API version 1, build 0.1.0-dev)
fylgja serve: 0.0.0.0:7650 is not a loopback address: the API's token is sent unencrypted on it
```

The listen line names the address as `--listen` gave it, with the port it got: `--listen
127.0.0.1:0` names the port the system chose. Once it serves, a failure to accept is
`fylgja serve: serving on <address>: <error>`, exit 2.

- It starts with neither Infrahub nor the workflow service reachable, and connects to
  each only when a request needs it.
- It keeps nothing between two requests.
- It logs one line a request on stderr when the request ends: `operation`, `outcome`,
  `duration`. `operation` is the operation's name, an operation's path asked with another
  method included, `interrupt` for the interrupt call, or `unknown` for a path that names
  none. `outcome` is the document's status; or
  `delivered` or `stream_ended` for an interrupt; or a fault of the transport,
  `token_refused`, `version_unknown`, `not_found`, `too_large`, `unreadable`,
  `stream_open`, `client_gone` or `panic`. A status, `delivered` and `stream_ended` are
  `INFO`, the faults `WARN`, a panic `ERROR`.
- A request with no rendering asked for logs its dependencies' warnings there too, each
  the dependency's own line at `WARN` or above with `operation=<op>` added,
  and the HTTP server's own errors are `WARN` lines in the same log.
- No log line carries the API's token, Infrahub's token, a login, an argument, a path a
  request named, a request body or a configuration line. A dependency's warning on a
  request with no rendering is the dependency's own line, so a failed containerlab call
  names the lab host's own twin directory, as the worker's log does.
- Interrupted, it stops serving at once and exits 0. Runs go on. A request its stop cut
  short may log `client_gone`, when its handler returns before the process exits, or no
  line at all; the client's finding names the run.
- `--psp-dir` falls back to `FYLGJA_PSP_DIR`, as on `worker run`.

## Every other command is a client's command

`twin create`, `twin show`, `twin destroy`, `twin provision`, `twin step`, `twin verify`,
`twin compile`, `waypoint list` and `waypoint plan` (moved at 014: `stage list` and `stage
plan`), `intent read`, `schema check` and `psp validate`, each with its dry run where it
has one. Each does its work by one
request to the API and prints what comes back.

- **What it prints and how it exits are M12's**, for the same arguments and the same
  state of the host, Infrahub and the workflow service.
- **Every refusal with a rule identifier is the server's**, those M2–M12 made "before
  any connection" included: a missing `--branch`, a flag conflict, an empty
  `--interval=`, `--wait=` or `--waypoint=` (moved at 014: `--stage=`). "Before any connection" now means before the
  server connects to Infrahub or the workflow service.
- **The client's own errors are its argument parser's**: an unknown flag, a wrong
  argument count. Exit 2, as cobra words them at M12, with no request sent.
- **`--psp-dir` is not a flag of a client's command.** Given one, the command ends with
  `unknown flag: --psp-dir`, exit 2, with no request sent. This is the one difference
  from M12 in what a client's command accepts. The packages every command is
  checked against are the server's.
- **`--json`** as at M12: one findings document on stdout and nothing else there.
- **`fylgja --version` and `--help`** need no server and no token.
- **A message that says "this worker"** (the login and package refusals) keeps its
  words when the server makes it.

What each command needed at M12 it still needs, with the server in the CLI's place: `twin
show` answers for the host and the record with the workflow service unreachable, inside
five seconds; `twin verify` needs no run and no worker; `waypoint list` and `waypoint
plan` (moved at 014: `stage list` and `stage plan`, which need the same) need no lab,
worker or workflow service; `psp validate` and `twin compile` need
neither Infrahub nor the workflow service. **Each needs a server.**

## The client's environment

| Variable | Default | |
|---|---|---|
| `FYLGJA_API_ADDRESS` | `127.0.0.1:7650` | `host:port`, or an `http://` or `https://` URL |
| `FYLGJA_API_TOKEN` | none | the API's token; never printed, logged or persisted |

A client's command reads no other variable of Fylgja's, Infrahub's or a node's: not
`INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`, a login, `FYLGJA_TEMPORAL_*`,
`FYLGJA_STATE_ROOT`, `FYLGJA_HOST_MEMORY_MB` or `FYLGJA_PSP_DIR`.

## The client's own failures

Each ends the command with one finding, in the command's own operation, status `error`,
**exit 2**, as text on stderr or as the document under `--json`. None carries a step.

| Rule | When | Object | Message shape |
|---|---|---|---|
| `api.unreachable` | nothing answers at the address | the address | `the API at 127.0.0.1:7650 cannot be reached: dial tcp 127.0.0.1:7650: connect: connection refused; fylgja serve runs on the lab host` |
| `api.unreachable` | `FYLGJA_API_ADDRESS` is not an address: a `host:port` with no port, with a port that is not a decimal number from 1 to 65535 (`7650x`, `http`, `0`), or with a `/` in it; a URL with no host, a query or a fragment, or with a port that is not one from 1 to 65535; any value holding a control character, such as the carriage return a `local/.env` saved with CRLF line endings leaves; or any value naming a user or password; nothing is sent | the address, without a user or password; one holding a control character quoted as Go quotes a string, in the object and in every sentence, so that none reaches the output | `the API at 127.0.0.1: cannot be reached: 127.0.0.1: is not host:port: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL; fylgja serve runs on the lab host`, or for `127.0.0.1:7650` and a carriage return `the API at "127.0.0.1:7650\r" cannot be reached: "127.0.0.1:7650\r" is not host:port: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL; fylgja serve runs on the lab host`, or for `https://user:pw@lab-host/` `the API at https://lab-host/ cannot be reached: https://lab-host/ names a user or password, which FYLGJA_API_ADDRESS never carries: it takes host:port or an http:// or https:// URL without one; fylgja serve runs on the lab host` |
| `api.unreachable` | what answers is not the API: a `200` with no `Fylgja-Api-Version` | the address | `the API at <address> cannot be reached: what answers there is not the API: its answer names no Fylgja-Api-Version; fylgja serve runs on the lab host` |
| `api.unreachable` | the answer stops before its document | the address | `the API at <address> stopped answering before the command ended: <cause>`; once the server had begun to start a run, `…; a run may have been started and was not cancelled: fylgja twin show names it`; once it had named the run, `…; run fylgja-provision 01a1… was not cancelled and goes on: fylgja twin show names it`; and once an interrupt had been delivered, `…; run fylgja-provision 01a1… was asked to cancel and goes on to its cleanup: fylgja twin show names it`, or before the run was named `…; a run may have been started and was asked to cancel: fylgja twin show names it` |
| `api.unreachable` | an interrupt could not be delivered | the address | the started and the named run's shapes above, since an interrupt is sent only from `start`; the cause is the network's own error when nothing answered, and otherwise the fault's sentence |
| `api.token.refused` | `FYLGJA_API_TOKEN` is unset; nothing is sent | `FYLGJA_API_TOKEN` | `FYLGJA_API_TOKEN is not set; a client sends the API's token with every request, and nothing was sent` |
| `api.token.refused` | `FYLGJA_API_TOKEN` holds a byte no request header can carry, a control character other than a horizontal tab, such as the carriage return a `local/.env` saved with CRLF line endings leaves; or it ends in a space or a horizontal tab, which a server's reader trims before it compares the token, so a server started with the same token would refuse it (a leading blank reaches the server whole); nothing is sent | `FYLGJA_API_TOKEN` | `FYLGJA_API_TOKEN holds a character a request header cannot carry, such as a carriage return; nothing was sent`, or for a token that ends in a space or a tab `FYLGJA_API_TOKEN ends in a space or a tab, which a request header cannot carry; nothing was sent` |
| `api.token.refused` | the server refused the token | the address | `the API at <address> refused this client's token; FYLGJA_API_TOKEN must be the token fylgja serve was started with` |
| `api.version.unknown` | the server serves no version this client speaks: a `404` whose `Fylgja-Api-Versions` does not name `1`; it did nothing for the command | the address | `the API at <address> serves version 2; this client speaks version 1` |
| `api.transfer.too_large` | a request with files was over the server's bound; nothing was read or filed | the operation | `the request is larger than this server's transfer bound of 33554432 bytes (32 MiB); nothing was read or filed` |
| `api.transfer.too_large` | a frame of the answer was over the client's bound; the client wrote no file | the operation | `the API at <address> sent an answer frame larger than this client's bound of 67108864 bytes (64 MiB); nothing was written on this machine` |

No message names either token. Each of the first three is told from the other two, and
from every M12 failure, by its identifier alone.

**A different build.** When the server's build is not the client's, one line on stderr,
in both modes, and the command goes on to its M12 result and exit status:

```
fylgja: this client is build 0.1.0-dev; the API at 127.0.0.1:7650 is build 0.2.0
```

It is not a finding and is not in the document.

**Anything else the transport says** is `operation.failed`, exit 2: `the API at
<address> could not read this request: <message>` for a `400`, its message the server's
(`the request is not one: …`), or `the API at <address> answered <status>`, the status as
Go words it (`answered 404 Not Found` for a path under `/v1/` that names no operation, or a
`404` whose `Fylgja-Api-Versions` names `1`, as for an address under a prefix the server
does not have; `answered 409 Conflict`; `answered 302 Found` or `answered 307 Temporary
Redirect` for a redirect, which the API never answers with and the client never follows,
from the command's request or from an interrupt, so nothing, the token included, is sent to
its `Location`), or `the API at <address> sent a document this client cannot read:
<error>` for a `document` frame whose document is not a findings document.

## Runs: `twin create`, `twin provision`, `twin step`, `twin destroy`

Each prints the run's progress as it happens, line for line as at M12, and ends with
M12's closing lines, document and exit status. Everything a run command does before its
start runs in the server, in M12's order.

| The operator | What happens | Ends |
|---|---|---|
| interrupts before the server begins to start the run | the command ends by the signal; the server stops that request's work; nothing was started | the signal's status, no document |
| interrupts while the start waits for a worker | the start is abandoned; a run no worker took is terminated | `run.cancelled` at `start`, exit 2, M2's two sentences |
| interrupts once, the run followed | the run is cancelled and its cleanup, or a step's record, waited for | the run's own end, as since M2 |
| interrupts again | the command stops waiting; the run goes on | `run.cancelled`, `stopped waiting for run <id>; it continues on the workflow service, and fylgja twin destroy will wait for it`, at the step reached, exit 2 |
| closes the shell, or loses the connection | the run is **not** cancelled; a start still waiting for a worker finishes, a destroy's included | `fylgja twin show` names it in flight, then the twin it made |
| interrupts `twin destroy` | the command ends by the signal; the destroy run goes on | as at M12 |

- A second client that starts a conflicting run is refused as a second shell was, by the
  fixed workflow identities, under `run.in_flight`, exit 1.
- `twin destroy` from another client cancels a create or a step in flight and waits for
  it, with M12's notices.
- The server stopped during a run: the run goes on, a start still waiting for a worker
  included; the client ends `api.unreachable`, exit 2, saying the run was not cancelled.
  There is no command to re-attach to it.

## The stage commands and the operator's files

| Command | The client | The server |
|---|---|---|
| `intent read … --out <file>` | writes the CTM that comes back, atomically; writes nothing when the read is refused | reads, validates, answers with the CTM and M12's summary line |
| `twin compile --ctm <file> --out <dir>` | reads the CTM once both flags are given; writes the bundle that comes back | parses it, checks its contract, compiles on the golden tests' code path |
| `psp validate <file>…` | reads each file | refuses a second YAML document, validates the set; every finding names the path given |
| `twin provision <bundle-dir>` | reads the directory's regular files | verifies, files in its store, and deploys the filed copy |
| `schema check --branch <b>` | sends the branch | answers as at M12 |

- A file the client cannot read, or cannot write, is its own `operation.failed`, exit 2,
  in M12's words for that command: `reading CTM: open ctm.json: no such file or
  directory`; `reading bundle directory: …` at step `verify`; `output directory out is
  not empty`; `writing CTM: …`. No request is sent for a file that cannot be read.
- A dry run and a plan file their bundle and CTM in the store on the lab host, and print
  the store's path there. There is no fetch by identifier.
- The package `psp validate` is sent is checked on its own, as a file, as at M12. The
  server's override directory decides only what the other commands are checked against.

Six differences from M12 are deliberate, each on an input no M12 test pins or in text
the move of the commands' work into the server made false:

- (a) `--psp-dir` is gone from a client's command (above).
- (b) With several files given to `psp validate`, one that cannot be read is reported
  before another's second YAML document.
- (c) An unreadable file inside a bundle directory is worded `reading <file>: open
  <dir>/<file>: permission denied` whichever file it is.
- (d) A path inside a bundle directory that is not a regular file (a directory, a symlink)
  is not sent, so the server answers as for a bundle without it: an empty directory or a
  symlink at `topology.clab.yml` is `<dir> is not a bundle: no topology.clab.yml`, where
  M12 said `topology.clab.yml is not a file` or read through the link. A bundle directory
  that is itself a symlink is followed: the client sends the directory it names, whole, and
  the server files it under its own id and names the link as given, where M12 hashed nothing
  through it and filed an empty bundle under `e3b0c442…`, or reported `bundle.id.mismatch`
  when the link's name was an id.
- (e) The help texts of `psp validate` and `twin compile` say the API's server checks or
  compiles what it is sent and that neither needs Infrahub nor the workflow service, where
  M12's said "no network" and "entirely local". Those of `waypoint list` and `waypoint
  plan` (moved at 014: `stage list` and `stage plan`, whose help says the same), `twin
  step` and `twin show` say the API's server does the command's work, where M12's
  said the command needs Infrahub and nothing else, needs Infrahub and the bundle store,
  resolves, reads, compiles and files its target "here", or "Runs on the lab host".
- (f) A dependency's warning that M12 wrote to stderr is an `err` frame when a rendering
  was asked for, and a line of the server's log otherwise (above).

## Identifiers

New: `api.unreachable`, `api.token.refused`, `api.version.unknown`,
`api.transfer.too_large`; each a rejection, status `error`, exit 2, no step, made by the
client. No new status, step, operation or exit status. No M1–M12 identifier, wording or
exit status changes. `serve`'s refusals to start and the build line have no identifier.

## Formats and versions

| Format | Version | Change |
|---|---|---|
| the API | `1` | new: [api.md](api.md), [api.schema.json](api.schema.json) |
| findings | `1` | none; the four identifiers match its `rule` pattern |
| bundle manifest, `twin.json`, PSP, CTM, contract | `4`, `5`, `0.6`, `1`, `0.2` | none (`twin.json` `6` since 014) |

## Workflows and activities

None is added, removed or changed. `fylgja-provision`, `fylgja-destroy`, `fylgja-step`,
`Reconcile`, the Schedule, all twenty activities and every wire type are M12's, and the
nine recorded histories replay. The server starts, follows and cancels runs through
`provision.Service`, as the CLI did. `worker run` is M12's, with `--psp-dir` now its own
flag.

## Environment

Who reads each variable from M13:

| Variable | Client | Server | Worker |
|---|---|---|---|
| `FYLGJA_API_ADDRESS` | yes | no (`--listen`) | no |
| `FYLGJA_API_TOKEN` | yes | yes | no |
| `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` | no | yes | yes |
| `FYLGJA_TEMPORAL_ADDRESS`, `_NAMESPACE` | no | yes | yes |
| `FYLGJA_STATE_ROOT` | no | yes | yes |
| `FYLGJA_HOST_MEMORY_MB` | no | yes | yes |
| each package's login names | no | yes | yes |
| `FYLGJA_PSP_DIR` | no | yes | yes |

The server needs `containerlab` and `docker` on its `PATH`. A client needs neither.

## Tier 3 (`scripts/e2e.sh`)

Eight cases, M12's, unchanged in what they assert (cases 7 and 8 moved to stages at 014,
below). The script starts a server of its own
from the tree, with a token it makes for the run, and stops it in its trap. Every
`fylgja` command runs with `PATH`, `HOME`, `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`
and nothing else. The script's own reads (`gnmic`, Docker, containerlab, `twin.json`,
the store), the boot half and the fixture tool stay direct, with the full environment.
The credential and marker greps gain the API's token and `$OUT/server.log`. The closing
lines are M12's.

## 014: the stage surface

A proposed change's stages replace the waypoint ([D-045](../docs/decisions.md#d-045)). A
stage is a moment of an open proposed change, named `<branch>/<label>` by the proposed
change's source branch: its two derived stages, `branch-point` and `head`, and the marks the
operator writes between them as `FylgjaStage` objects ([schema/README.md](../schema/README.md)).
**Everything not named here is as M13 left it.** Identifiers, exit statuses and the JSON
documents are the contract; text is illustrative except where a sentence is quoted.

### The commands

```
fylgja stage list  [--branch <b>]             # every open proposed change's stages, or one's; marks the twin's
fylgja stage plan  --branch <b>               # reads and compiles each stage; the step between each pair
fylgja twin create --stage <branch>/<label>   # the pinned run of the reference the stage resolves to; never follows
fylgja twin step   [--stage <branch>/<label>] [--allow-restart] [--wait <duration>] [--dry-run]
fylgja intent read --stage <branch>/<label> --out ctm.json
fylgja schema check --branch <b>              # also says whether the default branch has the stage kind and its extension
```

Moved at 014: `waypoint list`, `waypoint plan` and `--waypoint` are gone. `fylgja --help`
names none, and `fylgja waypoint list` is cobra's `unknown command`, exit 2, with no
request.

Each is a client's command, as above: one request, the frames printed, the exit by the
document, and every refusal with an identifier the server's. `stage list` and `stage plan`
need Infrahub and (the plan) the bundle store, and no lab, worker or workflow service.
**Each needs a server.**

**The reference.** `<branch>/<label>`, split at the first `/`; the branch and the label are
each `^[^/\s]+$`, so a reference is one shell word. The server finds the one open proposed
change whose source branch is the branch, then the stage by its label: the branch point is
`main` at the branch's `branched_from`; a mark is its source branch at its `as_of`,
verbatim, or at its own write stamp when it has none; the head is the source branch at the
latest stamp of its intent and artifact checksums, plus one microsecond. The stages are
ordered branch point, marks by `at`, head. A reference resolves before anything of intent
is read, and its label and description enter neither the CTM nor the bundle.

### `stage list [--branch <b>]`

A heading per proposed change, then one line per stage, the reference and the branch padded
so the `at`s line up, the source in parentheses, the description quoted and the twin's row
marked:

```
proposed change "third link" (18df…) on branch change-1, draft (4 stages)
  change-1/branch-point  main      at 2026-10-16T17:20:19.944651+00:00 (branch point)  ""
  change-1/cabled        change-1  at 2026-10-16T17:25:30.118244+00:00 (written)       "after the link is cabled"  ← twin
  change-1/live          change-1  at 2026-10-16T17:30:00.000000+00:00 (given)         "after its configuration is live"
  change-1/head          change-1  at 2026-10-16T17:30:11.884302+00:00 (head)          ""
```

With no open proposed change: `no open proposed change`, or `branch b: no open proposed
change` with `--branch`, exit 0, `stages.rows` empty. Beside a diverged record the mark
reads `← twin (diverged towards change-1/live)`. Orphans print after the proposed changes:
`orphaned: stage "cabled" (18df…) names no proposed change`. Exit 0, warnings included; 1
when a mark labelled `head` or `branch-point` is among the rows, which are all still listed,
or the kind is absent; 2 when Infrahub cannot be read (`operation.failed` at `resolve`).
`--json`: the `stages` block and the findings.

### `stage plan --branch <b>`

The heading, then each stage as it finishes and each step as it is known:

```
proposed change "third link" (18df…) on branch change-1 → main, draft (4 stages)
change-1/branch-point: refused (contract.node.missing)
  rejection contract.node.missing [step read] main: branch defines FylgjaContract but holds no instance of it
step change-1/branch-point → change-1/cabled (— → 5c6c1d96…): not computed (change-1/branch-point was refused)
change-1/cabled: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"
  bundle_id 5c6c1d96…
  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports
step change-1/cabled → change-1/head (5c6c1d96… → cc1ca493…): unchanged; the ids differ by provenance alone
…
```

Each step is the pure step between the two bundles, as M10's plan printed it, and is
`unchanged` when they differ in provenance alone, as the step from a mark written after the
last regenerate to the head always does. A refused stage prints its findings beneath it,
and a step touching it is not computed; the branch point of a `main` that holds no contract
is refused `contract.node.missing` at its read. Exit 0 when every stage compiled, whatever
the warnings; 1 when any was refused; 2 when the listing failed. `--branch` is required:
`--branch is required`, exit 2, with no request. `--json`: the `plan` block and the
findings, every stage's, in order. Each bundle and its CTM are filed in the store, as a dry
run files them.

### `--stage` on `twin create` and `intent read`

The resolved line first, before the run or the read:

```
stage change-1/cabled: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"
stage change-1/branch-point: main at 2026-10-16T17:20:19.944651+00:00 (branch point)
stage change-1/head: branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)
```

Then the pinned run (create) or the read, as M13 has them, with the `at` verbatim on every
query. `twin create --stage` never follows (`dry_run.follow.reason: stage`). `--branch`,
`--at` or `--interval` beside `--stage` is `stage.flags.conflict` at `start`, naming the
first in that order. The document carries `subject.stage`, as given, and the `stage` block
once resolved; `intent read`'s summary line begins `stage change-1/cabled: …`. The twin's
closing line names the stage, as `twin show`'s kind line does (below): `pinned at …, stage
change-1/cabled; not following`.

### `twin step [--stage <branch>/<label>]`

The first lines:

```
twin: stage change-1/cabled (bundle f857d513…), pinned at …; 3 nodes
stage change-1/live: branch change-1 at … (given), "after its configuration is live"
step change-1/cabled → change-1/live (f857d513… → 7eafd93c…):
  …
```

The target is the next stage of the twin's own proposed change when none is given, the head
when no mark follows; the one given otherwise, forward or back, the head included when it
has moved since the record. Each refusal below is made at `resolve`, before the from bundle,
the host check and containerlab's plan, exit 1:

| Rule | When | Wording (shape) |
|---|---|---|
| `step.twin.unsteppable` | no twin; an orphan; an unreadable record; a record of `5` or earlier, or one naming no stage | `…; only a twin built from a stage steps (fylgja twin create --stage)`; for a `5` record, `the twin was created from a waypoint of a record version this build no longer reads (twin.json 5); only a twin built from a stage steps; fylgja twin destroy clears it` |
| `step.target.foreign` | `--stage` names another branch, or another proposed change on the same branch | `stage other/x is not of proposed change <id> on branch change-1, the twin's; a step stays inside the proposed change the twin was built from, whose stages are: …` |
| `step.target.unknown` | no stage after the record's; the record's label gone; `--stage` names no stage of the proposed change | `proposed change <id> on change-1 has no stage after change-1/head; its stages are: …`, or `…; the head has moved since the twin was built (now at …): --stage change-1/head steps to it` |
| `step.target.current` | the target resolves to the record's own `(branch, at)` | `the twin is already at stage change-1/live (branch change-1, at …); the proposed change's stages are: …` |
| `step.stage.skipped` (warning, exit 0) | marks strictly between the record's stage and the target's, either direction | `the step from change-1/branch-point to change-1/head skips stages cabled, live; the step is between the two bundles either way` |

The target's own resolution refusals follow, as `twin create --stage` makes them.
Everything after the target is M11's and M12's with "stage" for "waypoint": `stepped to
stage change-1/live (bundle …) in 4.1s: …`; `unchanged; the record moves to stage
change-1/head (bundle …) in 0.9s`; `diverged towards stage change-1/live (bundle …) at
phase push: …; the twin is up at stage change-1/cabled (bundle …); fylgja twin destroy
clears it`.

### `twin show`, `twin verify`, `schema check`

`twin show`'s kind line is `pinned at …, stage change-1/cabled; not following`, and after a
step `pinned at …, stage change-1/live (stepped from change-1/cabled by run fylgja-step …,
ended …); not following`; `in_flight` names `stepping towards stage change-1/live`. `twin
verify`'s first line is `twin: stage change-1/live (bundle …), ready, pinned at …; 3
nodes`. `schema check`'s last line is one of:

```
stages: FylgjaStage present on the default branch, with its extension
stages: FylgjaStage absent from the default branch (load schema/fylgja-stage.yaml; needed only by the stage commands)
stages: FylgjaStage on the default branch lacks description (load schema/fylgja-stage.yaml; needed only by the stage commands)
stages: FylgjaStage present on the default branch, but CoreProposedChange lacks fylgja_stages (load schema/fylgja-stage.yaml; needed only by the stage commands)
```

and the document's `verified.stages` carries `kind`, `present`, `missing`, `extension` and
`file`.

### Identifiers

Twelve `stage.*` rules, seven of them moved at 014 from the waypoint's and five new; one M11
rule renamed; `waypoint.time.reversed` dropped, since marks are ordered by their `at`. The
step `stage` and the rule `stage.failed` are the staging step's, as before. A rejection at
`resolve` is made before any run starts and before any branch's intent is read.

| Rule | Severity, exit, step | When | Moved at 014 from |
|---|---|---|---|
| `stage.ref.invalid` | rejection, 2, `start` | `--stage` is not `<branch>/<label>`, or `--branch` on `stage list` or `stage plan` is not a branch | `waypoint.ref.invalid` |
| `stage.flags.conflict` | rejection, 2, `start` | `--stage` beside `--branch`, `--at` or `--interval` | `waypoint.flags.conflict` |
| `stage.kind.absent` | rejection, 1, `resolve` | the default branch lacks `FylgjaStage`, an attribute of it, or `CoreProposedChange`'s `fylgja_stages`, naming `schema/fylgja-stage.yaml` | `waypoint.kind.absent` |
| `stage.unknown` | rejection, 1, `resolve` | no open proposed change has the branch as its source; the branch is gone; or the proposed change has no stage of the label | `waypoint.unknown` |
| `stage.duplicate` | rejection, 1, `resolve` | two marks of one proposed change share a label | `waypoint.duplicate` |
| `stage.at.unresolved` | rejection, 1, `resolve` | a given `as_of` later than the server's clock, or a mark with no stamp at all | `waypoint.at.unresolved` |
| `stage.at.before_branch_point` | rejection, 1, `resolve` | the stage's `at` is before the branch's `branched_from`, naming a rebase when the branch was created before the `at` | new |
| `stage.label.reserved` | rejection, 1, `resolve` | a mark labelled `head` or `branch-point` | new |
| `stage.artifact.stale` | rejection, 1, `resolve`, one per device | at the stage's `at`, the device's intent is later than its generation stamp, the later of its artifact's checksum stamp and the proposed change's artifact validator's completion ([D-046](../docs/decisions.md#d-046)); names both remedies | new |
| `stage.orphaned` | warning, 0, none | a stage that names no proposed change | new |
| `stage.main.moved` | warning, 0, `resolve` | `main` was written after the branch's `branched_from`; nothing is refused | new |
| `stage.twin.moved` | warning, 0, none | the record's stage no longer resolves to the record's `(branch, at)`, or is gone | `waypoint.twin.moved` |
| `step.stage.skipped` | warning, 0, `resolve` | marks between the record's stage and the target | `step.sequence.skipped` (M11) |

`step.target.foreign`, `step.target.unknown`, `step.target.current` and
`step.twin.unsteppable` keep their identifiers, exits and step, reworded for stages. No
status, step or operation is new beyond `stage.list` and `stage.plan`.

### Formats and versions

| Format | Version | Change |
|---|---|---|
| the API | `1` | `stage.list` and `stage.plan` for `waypoint.list` and `waypoint.plan`; `stage` for `waypoint` in three operations' arguments ([api.md](api.md)) |
| findings | `1` | operations `stage.list` and `stage.plan` for the waypoint's; `subject.stage` for `subject.waypoint`; the blocks `stage`, `stages` and `plan` in [stages.schema.json](stages.schema.json), which replaces `waypoints.schema.json`; `verified.stages`; `dry_run.follow.reason` `stage`; `show`, `step` and `verify` carry `stage` where they carried `waypoint` |
| `twin.json` | `6` | `stage` (`proposed_change {id, branch}`, `label`, `description`, `at_source`) for `waypoint`, and in the step's two sides; `provenance.branch` is `main` for a twin from a branch point. A `5` record reads with no stage, and does not step |
| bundle manifest, PSP, CTM, contract | `4`, `0.6`, `1`, `0.2` | none |

The version of the findings document and of the API did not move: both are pre-1.0, and
every other operation and block is unchanged.

### Workflows and activities

None is added, removed or changed: no workflow decision, activity, timeout or version
marker. The wire types carry `stage` where they carried `waypoint`, and the three recorded
step histories carry the stage block in their payloads; every recorded history replays.

### Tier 3 (`scripts/e2e.sh`)

Cases 7 and 8 move to stages; the other six are unchanged, and the run makes seven twins.
Case 7 seeds a throwaway branch, opens a draft proposed change on it, marks `seeded`, adds
the third link and marks `third-link` once the checksums move; `stage plan` gives four
stages, the branch point refused, three ids and three steps, the last unchanged; a twin
from `seeded` carries the plan's id and a `6` record; a step with no target goes to
`third-link` and a second to the head, unchanged, the record moving; after its `-delete`,
`stage list --branch` lists nothing and `stage plan --branch` is `stage.unknown`. Case 8
does the same on the mixed fixture with `seeded` and `mixed-link`, stepping forward with
`--allow-restart` and back with `--stage <branch>/seeded`.
