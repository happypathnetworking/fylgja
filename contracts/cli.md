# CLI contract: M13 — API; 014 — the stage surface; 015 — the rehearsal

Extends the CLI as M2–M12 built it, and 014 moves it once more: the section "014: the
stage surface" at the end says what moved. 015 adds to it, and the section "015: the
rehearsal" after that says what was added. **Everything not named here is as M12 left it**:
every command's text on stdout and stderr, its `--json` document, each identifier, step,
object and message, and each exit status. Identifiers, exit statuses and the JSON
documents are the contract; text is illustrative except where a sentence is quoted. The
wire is [api.md](api.md). At M13 the nine schemas beside `api.schema.json` were M12's byte
for byte: bundle `4`, CTM `1`, PSP `0.6`, `twin.json` `5`, findings `1`; 014 moved the
findings blocks, `twin.json` to `6` and the schemas that carry the record's stage, and 015
moved `twin.json` to `7` and added the rehearsal's block.

## `fylgja serve [--listen <host:port>]... [--psp-dir <dir>]`

`--listen` is repeatable since 015 ("015: the rehearsal", below): the server listens on
every address given, and on `127.0.0.1:7650` when none is. What follows is M13's, for each
address.

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
has one, and `twin rehearse` (added at 015). Each does its work by one
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
start runs in the server, in M12's order. `twin rehearse` (015) is a run command too, and
what follows holds for it, with its own interrupt below.

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
| bundle manifest, `twin.json`, PSP, CTM, contract | `4`, `5`, `0.6`, `1`, `0.2` | none (`twin.json` `6` since 014, `7` since 015) |

## Workflows and activities

None is added, removed or changed. `fylgja-provision`, `fylgja-destroy`, `fylgja-step`,
`Reconcile`, the Schedule, all twenty activities and every wire type are M12's, and the
nine recorded histories replay. 015 adds one workflow, `fylgja-rehearse`, below. The server starts, follows and cancels runs through
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

The server needs `containerlab` and `docker` on its `PATH`. A client needs neither. The
two checks of 015, inside Infrahub's task workers, are clients too, and read
`FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` alone (below).

## Tier 3 (`scripts/e2e.sh`)

Eight cases, M12's, unchanged in what they assert (cases 7 and 8 moved to stages at 014,
and case 9 added at 015, below). The script starts a server of its own
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
later of the latest stamp of its intent and artifact checksums and its latest intent event
in Infrahub's event log (a removal moves no stamp; D-048), plus one microsecond. The stages are
ordered branch point, marks by `at`, head. A reference resolves before anything of intent
is read, and its label and description enter neither the CTM nor the bundle.

### `stage list [--branch <b>]`

A heading per proposed change, then one line per stage, the reference, the branch and the
`at` padded so the `at`s, the sources and the descriptions line up whatever each `at`'s
width, the source in parentheses, the description quoted and the twin's row marked:

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
`orphaned: stage "cabled" (18df…) names no proposed change`. Every stage has its row: one
with no `at` prints `at unresolved`, its row has no `at`, and the warning
`stage.at.unresolved` names it; a source branch deleted under its open proposed change lists
its marks at their own `at`s and its branch point and head unresolved, beside one warning
`stage.unknown` naming the branch, until Infrahub cancels it. Exit 0, warnings included; 1
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
the warnings; 1 when any was refused; 2 when the listing failed. A stage whose resolution,
read, compile or filing could not run is `failed` (`operation.failed` at its step) and the
plan goes on, the steps touching it not computed; that exits 1 as well, since the plan ran
and reported every stage, where 2 is an operation that did not run. `--branch` is required:
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
the host check and containerlab's plan, exit 1; a rehearsal in flight is refused before any
of them, `run.in_flight` naming it (015):

| Rule | When | Wording (shape) |
|---|---|---|
| `step.twin.unsteppable` | no twin; an orphan; an unreadable record; a record of `5` or earlier, or one naming no stage | `…; only a twin built from a stage steps (fylgja twin create --stage)`; for a `5` record, `the twin was created from a waypoint of a record version this build no longer reads (twin.json 5); only a twin built from a stage steps; fylgja twin destroy clears it` |
| `step.target.foreign` | `--stage` names another branch, or another proposed change on the same branch | `stage other/x is not of proposed change <id> on branch change-1, the twin's; a step stays inside the proposed change the twin was built from, whose stages are: …` |
| `step.target.unknown` | no stage after the record's; the record's label gone; `--stage` names no stage of the proposed change | `proposed change <id> on change-1 has no stage after change-1/head; its stages are: …`, or `…; the head has moved since the twin was built (now at …): --stage change-1/head steps to it` |
| `step.target.current` | the target resolves to the record's own `(branch, at)` | `the twin is already at stage change-1/live (branch change-1, at …); the proposed change's stages are: …` |
| `step.stage.skipped` (warning, exit 0) | marks strictly between the record's stage and the target's, either direction | `the step from change-1/branch-point to change-1/head skips stages cabled, live; the step is between the two bundles either way` |
| `stage.twin.moved` (warning, exit 0, no step) | once a target is chosen, the record's stage no longer resolves to the record's `(branch, at)`: the head written since, a mark's `as_of` edited, a rebase; `stage list`'s warning in its words and object, on the dry run and the run alike, and before the failure of a step that fails after its target | `the twin was built from stage change-1/head at branch change-1, at … (head); change-1/head now resolves to branch change-1, at … (head); the twin is pinned to what it was built from` |

The target's own resolution refusals follow, as `twin create --stage` makes them.
Everything after the target is M11's and M12's with "stage" for "waypoint": `stepped to
stage change-1/live (bundle …) in 4.1s: …`; `unchanged; the record moves to stage
change-1/head (bundle …) in 0.9s`; `diverged towards stage change-1/live (bundle …) at
phase push: …; the twin is up at stage change-1/cabled (bundle …); fylgja twin destroy
clears it`. Once the target is chosen, every document the step ends with carries the
warnings found by then (`step.stage.skipped`, `stage.twin.moved`, the target's
`stage.main.moved`), each once: a refusal's, the dry run's and the run's, and, ahead of its
`operation.failed`, a failure's (the from bundle unreadable, the host check, containerlab's
plan, the run's start).

### `twin show`, `twin verify`, `schema check`

`twin show`'s kind line is `pinned at …, stage change-1/cabled; not following`, and after a
step `pinned at …, stage change-1/live (stepped from change-1/cabled by run fylgja-step …,
ended …); not following`; `in_flight` names `stepping towards stage change-1/live`. `twin
verify`'s first line is `twin: stage change-1/live (bundle …), ready, pinned at …; 3
nodes`. A record of `5` or earlier reads with no stage and shows pinned (research R-11);
one that stepped or diverged names each stage of its step as the waypoint it was, `a
waypoint of a record version this build no longer reads (twin.json 5)`, never `none`: in
`twin show`'s step line and a diverged twin's kind line, `twin verify`'s `diverged towards
…` and `step.twin.diverged`'s `towards …`. Its JSON's stages stay `null`. `schema check`'s
last line is one of:

```
stages: FylgjaStage present on the default branch, with its extension
stages: FylgjaStage absent from the default branch (load schema/fylgja-stage.yaml; needed only by --stage, stage list and stage plan)
stages: FylgjaStage on the default branch lacks description (load schema/fylgja-stage.yaml; needed only by --stage, stage list and stage plan)
stages: FylgjaStage present on the default branch, but CoreProposedChange lacks fylgja_stages (load schema/fylgja-stage.yaml; needed only by --stage, stage list and stage plan)
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
| `stage.unknown` | rejection, 1, `resolve` | no open proposed change has the branch as its source; the branch is gone (in `stage list`, a source branch deleted under its open proposed change is a warning, its stages still listed); or the proposed change has no stage of the label | `waypoint.unknown` |
| `stage.duplicate` | rejection, 1, `resolve` | two marks of one proposed change share a label | `waypoint.duplicate` |
| `stage.at.unresolved` | rejection, 1, `resolve` | a given `as_of` later than the server's clock, or a stage with no stamp at all to name its `at` (in `stage list` a warning, the row listed with no `at`) | `waypoint.at.unresolved` |
| `stage.at.before_branch_point` | rejection, 1, `resolve` | the stage's `at` is before the branch's `branched_from`, naming a rebase when the branch was created before the `at` | new |
| `stage.label.reserved` | rejection, 1, `resolve` | a mark labelled `head` or `branch-point` | new |
| `stage.artifact.stale` | rejection, 1, `resolve`, one per device | at the stage's `at`, the device's intent is later than its generation stamp, the later of its artifact's checksum stamp and the proposed change's artifact validator's completion ([D-046](../docs/decisions.md#d-046)), its intent written by its own stamps or by an intent event naming it or one of its interfaces ([D-048](../docs/decisions.md#d-048)); names both remedies | new |
| `stage.orphaned` | warning, 0, none | a stage that names no proposed change | new |
| `stage.main.moved` | warning, 0, `resolve` | `main` was written after the branch's `branched_from`; nothing is refused | new |
| `stage.twin.moved` | warning, 0, none | the record's stage no longer resolves to the record's `(branch, at)`, or is gone; in `stage list` beside the record's row, and on `twin step` beside the target's findings | `waypoint.twin.moved` |
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

## 015: the rehearsal

A proposed change rehearsed on a twin: from the shell by `twin rehearse`, and from inside
Infrahub by two checks this repository ships ([D-049](../docs/decisions.md#d-049)–[D-052](../docs/decisions.md#d-052)).
**Everything not named here is as 014 left it.** Identifiers, exit statuses and the JSON
documents are the contract; text is illustrative except where a sentence is quoted. The wire
is [api.md](api.md), "015: the rehearsal"; the block is
[rehearsal.schema.json](rehearsal.schema.json).

### `twin rehearse --branch <b> [--markdown] [--json]`

A client's command and a run command: one request, the frames printed, the exit by the
document. It needs everything `twin create`, `twin step`, `twin verify` and `twin destroy`
need, both images where its stages name them included. **It needs a server.**

- `--branch` is required: left out, `--branch is required`, exit 2, with no request. An
  empty `--branch=` is the server's `stage.ref.invalid` at `start`, exit 2.
- `--markdown` prints the report's markdown alone on stdout, the progress and the findings
  on stderr, and exits by the document. `--json` prints the document alone. Both together
  are cobra's own refusal, exit 2, with no request.
- There is no `--allow-restart`, `--wait` or `--dry-run`: a rehearsal's twin is its own,
  every step allows a restart and waits the step's default budget, and `stage plan` is its
  dry run.

**What the server does, in order**, each refusal ending the request with its document and
nothing started: plans every stage of the open proposed change whose source branch is `b`,
as `stage plan` does, a refused stage refusing the rehearsal (status `rejected`, exit 1; `2`
for `operation.failed` and `intent.at.precision`) but for a branch point whose one rejection
is `contract.node.missing`, kept as a row and passed over; takes the first stage that
compiled as the **baseline**, filing `rehearsal.steps.none` when it is the only one; sums the
stages' budgets into the **deadline** and refuses one over the ceiling, 3,600 s
(`rehearsal.deadline.unfit`); refuses beside any run in flight (`run.in_flight`, naming
`fylgja-rehearse`'s, `fylgja-provision`'s, `fylgja-step`'s or `fylgja-destroy`'s run);
**reclaims** a twin whose record names a rehearsal run that is no longer running, by its
destroy, followed in the answer after `reclaiming the twin of rehearsal run <id>`
(`rehearsal.twin.reclaimed`; `cleanup.incomplete`, exit 4, when that destroy leaves
something), a destroy that cancels nothing: a rehearsal, provisioning or step run it finds
in flight, begun since the first look, refuses the rehearsal (`run.in_flight`, naming it,
exit 1, no `reclaimed` block); and otherwise checks the host for the baseline's bundle as
a dry run does, under the `host.*` identifiers, exit 1; then starts `fylgja-rehearse` and
follows it and its children; and after the run closes, resolves the stages again for
`rehearsal.stage.moved` and `rehearsal.change.closed`.

**The run.** `fylgja-rehearse` creates the twin from the baseline (`fylgja-provision`, the
bundle already compiled, never following, its record naming the rehearsal) and waits for it
to settle under the step's default budget, verifying it; steps it to each later stage in
order (`fylgja-step`, with `--allow-restart`'s behaviour and the default wait); and destroys
it (`fylgja-destroy`), always, but when the baseline's provision could not start because
another run began under its id since the server looked: then it touched nothing, starts no
destroy, which would tear down that run's lab, and ends `rejected`, `run.in_flight` naming
`fylgja-provision`, the closing line `rehearsal rejected: the run touched nothing, since a
run already holds the id of its baseline's provision; no destroy was needed`. It stops at the first stage whose verdict is not `passed`. A
stage **passes** when its step lands and its wait finds nothing the baseline's did not;
the baseline's own findings are reported and fail nothing. The deadline is a timer on the
run: when it passes, the child in progress is cancelled (a provision cleans up; a step
records the twin `diverged`) and the destroy follows.

```
rehearsal of proposed change "third link" (18df…) on branch change-1, draft: 4 stages; deadline 33m0s (ceiling 1h0m0s)
change-1/branch-point: refused (contract.node.missing)
  rejection contract.node.missing [step read] main: branch defines FylgjaContract but holds no instance of it
change-1/seeded: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"; baseline
change-1/third-link: branch change-1 at 2026-10-16T17:30:00.000000+00:00 (given), "third link"
change-1/head: branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)
run fylgja-rehearse 01a1…
stage change-1/seeded: creating the twin
run fylgja-provision 02b2…
…
stage change-1/seeded: verify: settled after 3.2s (2 reads)
stage change-1/third-link: stepping
run fylgja-step 03c3…
…
destroying the twin
run fylgja-destroy 04d4…
…
removed lab fylgja (3 containers)
removed twin directory /srv/fylgja/local/twin
stage change-1/branch-point: refused (contract.node.missing)
stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline
stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed
stage change-1/head: unchanged in 0.9s; settled after 1.0s (1 read); 19 held, 0 failed, 0 skipped; passed
rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1980s deadline
```

A step that restarted or recreated a node names each with the seconds its readiness took,
as `twin show` words a step's readiness (`stage change-1/third-link: stepped in 95.3s
(restarted n3 61.2s; push n1 2.5s, n3 2.6s); …`), and a node the step was cut before
awaiting alone; the table's step cell names them alike. A step the deadline or an interrupt
cut keeps its phase and names what it touched, as a diverged one does: `cancelled at phase
push: restarted n3 61.2s; landed n3; not landed n1 (not attempted)`, or `cancelled at phase
readiness: restarted n3`.
A failed stage's line says why (`diverged at phase push: restarted n3 61.2s; landed n3; not
landed n1 (push.refused)`, or a finding the baseline did not have, by rule and object), the stages
after it read `not reached`, and the closing line is `rehearsal nonconforming: stage
change-1/bad-port failed at phase push; the twin is destroyed; reproduce it by hand:`, then
the commands, one per line, indented: `fylgja twin create --stage` the baseline, `fylgja twin
step --stage <ref> --allow-restart` for each rehearsed stage up to the failed one, `fylgja
twin verify` and `fylgja twin destroy`. The findings print on stderr as every document
prints them, the baseline's and each stage's verify findings as warnings whose object is
prefixed by the stage (`change-1/seeded: n1:ethernet-1/2`).

**The markdown** (`--markdown`, and the comment `fylgja-twin` posts) is rendered from the
document and the plan's steps between the stages, GitHub-flavoured: a heading naming the proposed change and its branch; the
run, when the stages were resolved, the status and the time used against the deadline and
the ceiling; a table, one row per stage (its `at`, bundle, step, wait, counts, new findings
and verdict); a Mermaid drawing of the stages, each edge the step's changes by node, link
and artifact, never a line of content, a step not computed dotted; on any status but `ok`
the findings that say why; the stages, since Infrahub's view of the proposed change shows
none; the warnings, each one a stage filed listed once with the stages that filed it
(``- `artifact.interface.unrepresented` n1:ethernet-1/99: … (stages bad-port, head)``), the
run's own as they came; the baseline's findings; on a failure the commands that reproduce it;
and last the caveat, `*Fidelity is asserted, not measured: the twin's containers forward in
software and keep their own timing.*`. An operator's string is escaped where it lands.
It is never longer than 4,092 bytes, the longest text Infrahub keeps as a comment: a
report that would be names each finding by its identifier and object alone, identical ones
once with their count, gives the table each step by its outcome and its new findings by the
first two and how many more, and cuts a long proposed change's name in the heading with an
ellipsis; should that still be too long, it leaves sections out whole, the baseline's
findings first, then the drawing, the warnings, the stages, the findings and the reproduce
commands. The table is never left out: it shrinks to each stage's reference and verdict,
then, should even that be too long, to as many stages as fit and `… and <n> more`. A line
before the caveat says what was shortened, and `fylgja-twin`'s message, the text, is the
whole report.

**Status and exit.** No status or exit is new.

| Status | Exit | When |
|---|---|---|
| `ok` | 0 | every rehearsed stage passed; the baseline's findings and the warnings notwithstanding |
| `rejected` | 1 | refused before any run: a stage refused, the deadline unfit, a run in flight, the host held; or the run's baseline provision refused at its start, another run holding its id, the run touching nothing and starting no destroy |
| `error` | 2 | a stage's step could not run, was rejected by its locks or was cancelled before its stage; the baseline's provision ended `error`, `rejected` or `cancelled`, building nothing to clean up; its wait incomplete; the deadline cut the rehearsal; the operator's interrupt; `operation.failed`; each after the destroy |
| `failed` | 3 | the baseline could not be built: its provision ended `failed`, and cleaned up |
| `unclean` | 4 | the destroy left something; `cleanup.incomplete` says what, and that `twin destroy` clears it |
| `nonconforming` | 5 | a stage failed: diverged, or a finding the baseline did not have; the twin destroyed |

**The operator** interrupts once: the run is cancelled and its destroy waited for, `run
cancelled; waiting for its destroy`, the rehearsal ending `error` with `run.cancelled`. A
second interrupt stops waiting (`run.cancelled`), and the run goes on to its destroy. A
client that goes away leaves the run running to its destroy. An answer that stops waiting,
or whose result cannot be read, keeps the run it started: the block names it, every stage
`not_reached` and `destroy` `null`, and the closing line and the markdown say it was
started, why its end was not read and that it goes on to its destroy, which `twin show`
follows (`rehearsal error: run fylgja-rehearse <id> was started and its end was not read
(<why>); it goes on to its destroy, and fylgja twin show says where it is`), with no stage
line.

### Identifiers

Nine, each `rehearsal.*`. `run.cancelled`, `run.in_flight`, `run.worker.absent`,
`run.service.unreachable`, `host.*`, `cleanup.incomplete` and every `stage.*`, `step.*` and
`verify.*` keep their identifiers.

| Rule | Severity, exit, step | When |
|---|---|---|
| `rehearsal.deadline.unfit` | rejection, 1, `start` | the stages' summed budgets exceed the ceiling; names the time the stages need and the ceiling |
| `rehearsal.twin.reclaimed` | warning, 0, `destroy` | a twin of a rehearsal whose run was no longer running was destroyed before the start; names the run and what was removed |
| `rehearsal.steps.none` | warning, 0, `resolve` | one stage alone compiled: it was built, verified and destroyed, and no step was rehearsed |
| `rehearsal.stage.failed` | rejection, 5, the phase's step for a divergence, `observe` for a finding | the stage failed; names the phase and the nodes landed and not landed, or the finding by rule and object |
| `rehearsal.stage.error` | rejection, 2, the step reached | the stage's step could not run, was rejected by its locks or cancelled before its stage, or its wait could not complete; or the baseline's provision ended `error`, `rejected` or `cancelled`, at the step it stopped at |
| `rehearsal.baseline.failed` | rejection, 3, `provision` | the baseline could not be built: its provision ended `failed`; the provision's own findings stand beside it |
| `rehearsal.deadline.cut` | rejection, 2, the step reached | the deadline passed; names the stage in progress, each finished stage's time and the deadline |
| `rehearsal.stage.moved` | warning, 0, `resolve` | after the run, a rehearsed stage, the head included, no longer resolves to the `(branch, at)` it was rehearsed at, or is gone |
| `rehearsal.change.closed` | warning, 0, `resolve` | after the run, the proposed change is no longer open |

### `twin show`, `twin verify`, `twin destroy`, `stage list` beside a rehearsal

- `twin show`'s kind line for a rehearsal's twin is `pinned at …, stage change-1/seeded, of
  rehearsal run fylgja-rehearse 01a1…; not following`, and while the run is in flight it ends
  `; rehearsal run fylgja-rehearse 01a1… is at stage change-1/third-link, step push`;
  `in_flight` names the rehearsal with its child and the stage it is at, `in flight: run
  fylgja-rehearse 01a1… at step step (run fylgja-step 03c3… at step push), stepping towards
  stage change-1/third-link`. `show.record.rehearsal` is `{workflow_id, run_id}`, absent
  when the record names no rehearsal.
- `twin verify`'s first line names the rehearsal's run after the stage, and
  `verify.twin.rehearsal` carries it, `null` when the record names none.
- `twin destroy` during a rehearsal prints `cancelling rehearsal run 01a1…; waiting for its
  destroy`, follows that destroy, then makes its own, which finds nothing. `twin create`,
  `twin provision` and `twin step` beside a rehearsal are `run.in_flight`, naming it.
  `twin step` asks the workflow service first, after its flags' guards and before it reads
  the host or Infrahub, so it is never refused as an orphan during the baseline's provision
  or as diverged after a failed stage; its dry run asks nothing, as `twin create --dry-run`
  does not.
- `stage list` marks a rehearsal's twin as it marks any twin. While the run is in flight,
  and while a dead rehearsal's twin waits for its reclaim, the record names a stage of the
  proposed change, whose row carries `← twin`, or `← twin (diverged towards …)` after a
  failed step (its `stages.rows[].twin` true under `--json`); nothing there names the
  rehearsal, which `twin show` does. Once the rehearsal ends its twin is gone, and no row
  is marked.

### `twin.json` 7

`twin_version` `"7"` ([twin.schema.json](twin.schema.json), `$id
https://fylgja.dev/contracts/twin/v7`): `rehearsal` is required, `{"workflow_id":
"fylgja-rehearse", "run_id": "…"}` for a rehearsal's twin and `null` otherwise. A create's
record writes it from its input and a step's record keeps it. Everything else of `6`
stands, and a `6` record reads with no rehearsal.

### The checks, `fylgja-step` and `fylgja-twin`

Infrahub runs both on every open proposed change, at its creation and on each re-run of its
checks, in its task workers; each finds its proposed change by its source branch and asks
Fylgja through the API alone. They are registered in `.infrahub.yml` beside the template,
global, with the query `fylgja_branch` (`infrahub/queries/branch.gql`), and reach Infrahub
as the template does: on `origin`'s `main`, imported on request, a branch made before the
import never running them.

| Check | `timeout` | Asks | Concludes |
|---|---|---|---|
| `fylgja-step` | 300 | `stage.plan`, `render: "text"`, on every open proposed change, draft or not | failure when the document holds a rejection, but for a branch point (`at_source: branch_point`) whose one rejection is `contract.node.missing`; when the plan's status is `error`; and when Fylgja cannot be reached. Success otherwise, warnings included. Its message is the plan's text and the findings' |
| `fylgja-twin` | 4200 | nothing on a draft, `twin.rehearse`, `render: "markdown"`, with a `Fylgja-Stream`, otherwise | on a draft, success, its message `skipped: proposed change <id> is a draft; mark it ready for review and re-run the checks to rehearse it`. Otherwise by the document's status alone: `ok` success, every other status failure, which blocks the merge. Its message is the report's text; it posts the answer's markdown as one new comment on the proposed change, as the proposed change's view writes and shows one: a `CoreChangeThread` labelled `Conversation` holding one `CoreThreadComment` (a `CoreChangeComment` would be counted and never shown). A comment it cannot post is logged and fails nothing, and the thread it made for it is deleted |

- **What each needs**: `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` in the task workers'
  environment, which the Compose override gives them (`host.docker.internal:7650`, and the
  token from `local/.env`), and a server listening where that address leads, the host's
  Docker bridge (`--listen`, below). Either variable unset is a failure naming it, with
  nothing sent; Fylgja unreachable, refusing the token or the version, or its answer cut,
  is a failure naming the address. Nothing else of Fylgja's, Infrahub's or a node's.
- **The host held**: when the rehearsal is refused before any start by `run.in_flight`,
  `host.lab.present` or `host.twin.present` alone, `fylgja-twin` asks again every 30 s until
  its own deadline, its `timeout` less 180 s, nears, then fails naming what held it. A
  retried refusal is logged and never posted.
- **Cut short**: an answer cut after the run started is a failure saying `the connection to
  Fylgja was lost while the rehearsal ran; the run goes on to its destroy and no report will
  be posted; re-run the checks once fylgja twin show reports no twin`. At the check's own
  deadline it sends the interrupt and reads the answer on to its end. Cancelled or timed out
  by Infrahub, it sends the interrupt with a blocking call; Infrahub then leaves the
  validator `in_progress`, which blocks the merge.
- No message, comment or log line carries a token, a password or a configuration line.

### `fylgja serve --listen <host:port>...`

`--listen` is repeatable; none given is `127.0.0.1:7650`. On the lab host the server listens
on loopback and on the host's Docker bridge address, `<docker0>:7650`, where Infrahub's task
workers reach it ([D-050](../docs/decisions.md#d-050)). In order, before anything listens:
every value is checked `host:port` (`fylgja serve: --listen <value> is not host:port`, exit
2); every listener is opened, a failure closing those opened and refusing to start naming
the address (`fylgja serve: listening on <address>: <error>`, exit 2, listening on none).
One server serves every listener; a failure to accept on any is `fylgja serve: serving on
<address>: <error>`, exit 2, and an interrupt closes them all. The report has one listen
line per address, in the order given, each straight followed by its unencrypted line when
it is not loopback:

```
fylgja serve: listening on 127.0.0.1:7650 (API version 1, build 0.1.0-dev)
fylgja serve: listening on 172.17.0.1:7650 (API version 1, build 0.1.0-dev)
fylgja serve: 172.17.0.1:7650 is not a loopback address: the API's token is sent unencrypted on it
fylgja serve: state root …
```

One token guards every address, a request is answered alike on each, and the request log
names no address. [SECURITY.md](../SECURITY.md) says what the bridge listener exposes.

### Formats and versions

| Format | Version | Change |
|---|---|---|
| the API | `1` | `twin.rehearse`; `render: markdown` and the `document` frame's `markdown`; `start.workflow_id` `fylgja-rehearse` ([api.md](api.md)) |
| findings | `1` | operation `twin.rehearse`; the `rehearsal` block ([rehearsal.schema.json](rehearsal.schema.json)); `show.record.rehearsal`, `verify.twin.rehearsal`; `step.wait_counts` ([step.schema.json](step.schema.json)); the nine identifiers |
| `twin.json` | `7` | `rehearsal` |
| bundle manifest, PSP, CTM, contract | `4`, `0.6`, `1`, `0.2` | none |

The versions of the findings document and of the API did not move: a client of 014 ignores
a new operation, a rendering it does not ask for, a frame field it does not know and a
block of an operation it does not run.

### Workflows and activities

One workflow is added, `fylgja-rehearse` ([D-051](../docs/decisions.md#d-051)), with a
fixed id, its children `fylgja-provision`, `fylgja-step` and `fylgja-destroy` under theirs;
the worker serves five. No activity, budget or version marker is added or changed, and the
nine recorded histories replay. `StepResult` gains `wait_counts` and `wire.VerifyResult`
`counts`, each omitted when absent. `twin step`'s block carries `wait_counts` beside `wait`,
the wait's last read counted by kind as `twin verify` counts its block, once the run closed
and its wait read: absent on the dry run, on a wait that made no read and on a run
cancelled before its wait. Its text does not change.

### Tier 3 (`scripts/e2e.sh`)

Case 9 is added, SR Linux alone, so `PLATFORMS=nokia_srlinux` runs it; the run makes nine
twins. Before anything starts, the script requires `fylgja-step` (300) and `fylgja-twin`
(4200) on `main`, and the server the task workers reach, at `http://<bridge>:7650`,
answering with local/.env's token and the tree's build: the operator's, never started or
stopped by the script, whose own server stays on loopback. Case 9 seeds a throwaway
branch and opens a draft, whose creation's checks read `fylgja-twin` skipped and
`fylgja-step` passed, and no comment; marks `seeded`, adds the third link, marks
`third-link` and marks the proposed change ready; re-runs the checks, after which
`fylgja-twin` reads success with `rehearsal ok` in its message, one comment holds the
table, the drawing and the stages, the rehearsal's run is fetched and `twin show` reports no
twin; adds `n1:ethernet-1/99`, generates, marks `bad-port` and re-runs them, after which
`fylgja-twin` reads failure naming `bad-port`'s push on n1, and a second comment holds the
commands that reproduce it and the head `not reached`; then `-delete`s the branch, after
which Infrahub holds nothing of it, its comments and validators gone with the proposed
change. The comments and the checks' messages are written to `$OUT`, where the credential
and marker greps read them, and the trap's destroy cancels a rehearsal in flight and waits
for its destroy.
