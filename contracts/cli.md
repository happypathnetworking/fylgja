# CLI contract: M13 — API; 014 — the stage surface; 015 — the rehearsal; 017 — the scope and the DCIM reader; 018 — snapshots; 019 — following removed

Extends the CLI as M2–M12 built it, and 014 moves it once more: the section "014: the
stage surface" at the end says what moved. 015 adds to it, and the section "015: the
rehearsal" after that says what was added. 017 moves it again, and the section "017: the
scope and the DCIM reader" says what moved. 018 makes the snapshot the core's one input,
and the section "018: snapshots" says what moved. 019 removes following from the core, and
the section "019: following removed", last, says what moved. **Everything not named here is
as M12 left it**:
every command's text on stdout and stderr, its `--json` document, each identifier, step,
object and message, and each exit status. Identifiers, exit statuses and the JSON
documents are the contract; text is illustrative except where a sentence is quoted. The
wire is [api.md](api.md). At M13 the nine schemas beside `api.schema.json` were M12's byte
for byte: bundle `4`, CTM `1`, PSP `0.6`, `twin.json` `5`, findings `1`; 014 moved the
findings blocks, `twin.json` to `6` and the schemas that carry the record's stage, and 015
moved `twin.json` to `7` and added the rehearsal's block; 017 moved the CTM to `2`, the
bundle manifest to `5`, `twin.json` to `8` and PSP to `0.7`, and retired the contract
version; 018 added the snapshot `1`, moved `twin.json` to `9`, and retired `twin compile
--ctm` and the bundle's CTM sidecar; 019 moved `twin.json` to `10` and removed the following
blocks from the findings document and the `show` block.

## `fylgja serve [--listen <host:port>]... [--psp-dir <dir>]`

`--listen` is repeatable since 015 ("015: the rehearsal", below): the server listens on
every address given, and on `127.0.0.1:7650` when none is. It reads `FYLGJA_DEFAULT_SCOPE`
since 017 ("017: the scope and the DCIM reader", below), which adds one refusal to start
and one line of the report. Since 018 the state root line names the snapshot store beside
the bundles ("018: snapshots", below). What follows is M13's, for each address.

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
  `--interval=` (an unknown flag since 019), `--wait=` or `--waypoint=` (moved at 014: `--stage=`), and since 017 an
  empty `--scope=`. "Before any connection" now means before the
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
| `intent read … --out <file>` | writes the CTM that comes back, atomically; writes nothing when the read is refused (since 018 a snapshot, which the server also files: "018: snapshots") | reads, validates, answers with the CTM and M12's summary line |
| `twin compile --ctm <file> --out <dir>` (retired at 018: `--snapshot <file>`) | reads the CTM once both flags are given; writes the bundle that comes back | parses it, checks its contract, compiles on the golden tests' code path |
| `psp validate <file>…` | reads each file | refuses a second YAML document, validates the set; every finding names the path given |
| `twin provision <bundle-dir>` | reads the directory's regular files | verifies, files in its store, and deploys the filed copy |
| `schema check --branch <b>` | sends the branch | answers as at M12 |

- A file the client cannot read, or cannot write, is its own `operation.failed`, exit 2,
  in M12's words for that command: `reading CTM: open ctm.json: no such file or
  directory`; `reading bundle directory: …` at step `verify`; `output directory out is
  not empty`; `writing CTM: …` (since 018 `reading snapshot: …` and `writing snapshot:
  …`). No request is sent for a file that cannot be read.
- A dry run and a plan file their bundle and CTM in the store on the lab host, and print
  the store's path there (since 018 the snapshot in its own store, `snapshots/`, and no
  CTM sidecar beside the bundle: "018: snapshots"). There is no fetch by identifier.
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
| bundle manifest, `twin.json`, PSP, CTM, contract | `4`, `5`, `0.6`, `1`, `0.2` | none (`twin.json` `6` since 014, `7` since 015; since 017 the bundle manifest `5`, `twin.json` `8`, PSP `0.7` and CTM `2`, and the contract version retired; since 018 `twin.json` `9`, and the snapshot `1` new; since 019 `twin.json` `10`) |

## Workflows and activities

None is added, removed or changed. `fylgja-provision`, `fylgja-destroy`, `fylgja-step`,
`Reconcile`, the Schedule, all twenty activities and every wire type are M12's, and the
nine recorded histories replay. 015 adds one workflow, `fylgja-rehearse`, below; 017 adds
none, its scope riding the runs' inputs; 018 adds none, its snapshot id riding them too; 019
removes `Reconcile`, the Schedule and five activities ("019: following removed", below). The
server starts, follows and cancels runs through
`provision.Service`, as the CLI did. `worker run` is M12's, with `--psp-dir` now its own
flag.

## Environment

Who reads each variable from M13:

| Variable | Client | Server | Worker |
|---|---|---|---|
| `FYLGJA_API_ADDRESS` | yes | no (`--listen`) | no |
| `FYLGJA_API_TOKEN` | yes | yes | no |
| `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` | no | yes | no (yes until 019) |
| `FYLGJA_TEMPORAL_ADDRESS`, `_NAMESPACE` | no | yes | yes |
| `FYLGJA_STATE_ROOT` | no | yes | yes |
| `FYLGJA_HOST_MEMORY_MB` | no | yes | yes |
| each package's login names | no | yes | yes |
| `FYLGJA_PSP_DIR` | no | yes | yes |
| `FYLGJA_DEFAULT_SCOPE` (017) | no | yes | no |

The server needs `containerlab` and `docker` on its `PATH`. A client needs neither. The
two checks of 015, inside Infrahub's task workers, are clients too, and read
`FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` alone (below).

## Tier 3 (`scripts/e2e.sh`)

Eight cases, M12's, unchanged in what they assert (cases 7 and 8 moved to stages at 014,
and case 9 added at 015, every case moved to the library's kinds at 017, the records'
assertions moved to the snapshot at 018, and case 5 moved from following to a frozen twin
and two steps at 019, below). The
script starts a server of its own
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

Moved at 019: nothing follows, and `twin step` takes a stage of any proposed change or a
snapshot ("019: following removed", below).

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
is refused `contract.node.missing` at its read (moved at 017: `scope.empty`, for a `main`
holding no device in the scope). Exit 0 when every stage compiled, whatever
the warnings; 1 when any was refused; 2 when the listing failed. A stage whose resolution,
read, compile or filing could not run is `failed` (`operation.failed` at its step) and the
plan goes on, the steps touching it not computed; that exits 1 as well, since the plan ran
and reported every stage, where 2 is an operation that did not run. `--branch` is required:
`--branch is required`, exit 2, with no request. `--json`: the `plan` block and the
findings, every stage's, in order. Each bundle and its CTM are filed in the store, as a dry
run files them (since 018 each stage's snapshot in its own store and no CTM sidecar: "018:
snapshots").

### `--stage` on `twin create` and `intent read`

Moved at 019: `--interval`, `dry_run.follow` and the closing line's `; not following` are
gone ("019: following removed", below).

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

Moved at 019: a step takes a stage of any proposed change or a snapshot, and its refusals
move ("019: following removed", below).

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
| `step.twin.unsteppable` | no twin; an orphan; an unreadable record; a record of `5` or earlier, or one naming no stage; since 017, a record of `7` or earlier, which names no scope, or an `8` naming a scope that is not `tag:<name>` or a mapping `twin.json` 8 cannot hold (below) | `…; only a twin built from a stage steps (fylgja twin create --stage)`; for a `5` record, `the twin was created from a waypoint of a record version this build no longer reads (twin.json 5); only a twin built from a stage steps; fylgja twin destroy clears it` |
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

Moved at 019: the kind line names the snapshot, and so does `twin verify`'s first line
("019: following removed", below).

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

Moved at 019: `stage.flags.conflict` names no `--interval`, `step.target.foreign` is retired
and `step.twin.unsteppable` is reworded ("019: following removed", below).

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
| `stage.twin.moved` | warning, 0, none | the record's stage no longer resolves to the record's `(branch, at)`, or is gone; in `stage list` beside the record's row, and on `twin step` beside the target's findings; judged under the scope the record names (017), so `stage list` under another scope resolves a head record's head once more under the record's, and a record naming none is judged under the listing's | `waypoint.twin.moved` |
| `step.stage.skipped` | warning, 0, `resolve` | marks between the record's stage and the target | `step.sequence.skipped` (M11) |

`step.target.foreign`, `step.target.unknown`, `step.target.current` and
`step.twin.unsteppable` keep their identifiers, exits and step, reworded for stages. No
status, step or operation is new beyond `stage.list` and `stage.plan`.

### Formats and versions

Moved at 019: `dry_run.follow` is gone ("019: following removed", below).

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

Moved at 019: every deadline is 30 s shorter, since the baseline's provision stops nothing
("019: following removed", below).

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
is `contract.node.missing` (moved at 017: `scope.empty`), kept as a row and passed over; takes the first stage that
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
the commands, one per line, indented: `fylgja twin create --stage` the baseline `--scope`
the scope every stage was read under, `fylgja twin step --stage <ref> --allow-restart` for
each rehearsed stage up to the failed one, `fylgja twin verify` and `fylgja twin destroy`.
Since 017 the create names the scope always, the request's or the server's default, since
the server that reproduces it may hold another default; each step reads its record's scope
and takes none. A rehearsed stage at the branch and `at` of the last
stage a command named, the baseline's or a step's, has no step of its own, since `twin step`
would refuse it `step.target.current` and the twin is already there: run in order, the
commands make the rehearsal's steps and its verify, and a failed stage so left out is
reproduced by the verify after the steps before it. With no step before it, as for a failed
stage at the baseline's `at`, the verify is `fylgja twin verify --wait`: `twin create` waits
for no settle, and the rehearsal compared a whole wait. The findings print on stderr as every
document prints them, the baseline's and each stage's verify findings as warnings whose object is
prefixed by the stage (`change-1/seeded: n1:ethernet-1/2`).

**The markdown** (`--markdown`, and the comment `fylgja-twin` posts) is rendered from the
document and the plan's steps between the stages, GitHub-flavoured: a heading naming the proposed change and its branch; the
run, when the stages were resolved, the status and the time used against the deadline and
the ceiling; a table, one row per stage (its `at`, bundle, step, wait, counts, new
verification failures and verdict: the wait's failing assertions the baseline's wait did not
have, so a refused push, which the step and the verdict carry, is not one); a Mermaid drawing of the stages, top to bottom, each edge the step's changes by node,
link and artifact, never a line of content, a step not computed dotted, and each stage that
failed or erred outlined red by a class (Infrahub drops a node's style attribute); on any status but `ok`
the findings that say why; the stages, since Infrahub's view of the proposed change shows
none; the warnings, each one a stage filed listed once with the stages that filed it
(``- `artifact.interface.unrepresented` n1:ethernet-1/99: … (stages bad-port, head)``), the
run's own as they came; the baseline's findings; on a failure the commands that reproduce it;
and last the caveat, `*Fidelity is asserted, not measured: the twin's containers forward in
software and keep their own timing.*`. An operator's string is escaped where it lands.
It is never longer than 4,092 bytes, the longest text Infrahub keeps as a comment: a
report that would be names each finding by its identifier and object alone, identical ones
once with their count, gives the table each step by its outcome and its new verification failures
by the first two and how many more, and cuts a long proposed change's name in the heading with an
ellipsis; should that still be too long, it leaves sections out whole, by an order of
preference: the baseline's findings first, then the drawing, the warnings, the stages, the
findings and the reproduce commands. The sections are kept from the last of that order back
while each still fits, so one earlier in it is kept when it fits once a later one was left
out: a long drawing can be left out while the baseline's findings are kept. The table is
never left out: it shrinks to each stage's reference and verdict,
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

Moved at 019: the kind line names the snapshot, and no line says `not following` ("019:
following removed", below).

- `twin show`'s kind line for a rehearsal's twin is `pinned at …, stage change-1/seeded, of
  rehearsal run fylgja-rehearse 01a1…; not following`, and while the run is in flight it ends
  `; rehearsal run fylgja-rehearse 01a1… is at stage change-1/third-link, step push`;
  `in_flight` names the rehearsal with its child in flight, its provision, a step or its
  destroy, each by `workflow_id`, `run_id` and `step`, and no stage; the text's line adds the
  stage it is at, `in flight: run fylgja-rehearse 01a1… at step step (run fylgja-step 03c3…
  at step push), stepping towards stage change-1/third-link`, and `notes` carries the kind
  line's `rehearsal run fylgja-rehearse 01a1… is at stage change-1/third-link, step push`.
  `show.record.rehearsal` is `{workflow_id, run_id}`, absent
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
https://github.com/happypathnetworking/fylgja/contracts/twin/v7`): `rehearsal` is required, `{"workflow_id":
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
| `fylgja-step` | 300 | `stage.plan`, `render: "text"`, on every open proposed change, draft or not | failure when no open proposed change has the source branch (`no open proposed change has source branch <b>: nothing was asked of Fylgja`); when the document holds a rejection, but for a branch point (`at_source: branch_point`) whose one rejection is `contract.node.missing` (moved at 017: `scope.empty`); when the plan's status is `error`; when the plan has not answered by the check's own deadline, its `timeout` less 120 s (`the stage plan did not answer by this check's own deadline, 180 s after it began (…): nothing was started, and a re-run of the checks asks again`); and when Fylgja cannot be reached. Success otherwise, warnings included. Its message is the plan's text and the findings' |
| `fylgja-twin` | 4260 | nothing on a draft, `twin.rehearse`, `render: "markdown"`, with a `Fylgja-Stream`, otherwise | failure when no open proposed change has the source branch (`no open proposed change has source branch <b>: nothing was asked of Fylgja`), before its draft test; on a draft, success, its message `skipped: proposed change <id> is a draft; mark it ready for review and re-run the checks to rehearse it`. Otherwise by the document's status alone: `ok` success, every other status failure, which blocks the merge. Its message is the report's text; it posts the answer's markdown as one new comment on the proposed change, as the proposed change's view writes and shows one: a `CoreChangeThread` labelled `Conversation` holding one `CoreThreadComment` (a `CoreChangeComment` would be counted and never shown). A comment it cannot post is logged and fails nothing, and the thread it made for it is deleted |

- **What each needs**: `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` in the task workers'
  environment, which the Compose override gives them (`host.docker.internal:7650`, and the
  token from `local/.env`), and a server listening where that address leads, the host's
  Docker bridge (`--listen`, below). Either variable unset is a failure naming it, with
  nothing sent; Fylgja unreachable, refusing the token or the version, or its answer cut,
  is a failure naming the address. Nothing else of Fylgja's, Infrahub's or a node's.
- **The host held**: when the rehearsal is refused by `run.in_flight`, `host.lab.present`
  or `host.twin.present` alone, the branch point's lone `contract.node.missing` (moved at
  017: `scope.empty`) passed over
  as `fylgja-step` passes it over, whether the server found the holder before `start` or
  after it (a start refused by a run begun since the host was read or by the rehearsal's
  fixed id, or a run refused at its baseline's start, each touching nothing), and no run was
  asked to cancel, `fylgja-twin` asks
  again every 30 s while what would remain of its own deadline, its `timeout` less 240 s,
  at the next ask still covers the refused rehearsal's deadline (its block's `deadline_s`),
  the destroy's budget (120 s) and the 300 s allowed before `start`, so that no run it
  starts is interrupted by it; then it fails naming what holds the host. A retried refusal
  is logged and never posted; the last one's markdown is the comment.
- **Cut short**: an answer cut after the run started is a failure saying `the connection to
  Fylgja was lost while the rehearsal ran; the run goes on to its destroy and no report will
  be posted; re-run the checks once fylgja twin show reports no twin`. At the check's own
  deadline it sends the interrupt and reads the answer on to its end, but no later than
  120 s before its timeout, past which it is a cut; it says the run was asked to cancel only
  once the run had started, and an answer interrupted before any start is the refusal it
  carries. `fylgja-step` stops reading the plan 120 s before its timeout, which closes the
  request and ends the plan's work on the server. Cancelled or timed out
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

Moved at 019: the worker serves four workflows, `Reconcile` gone ("019: following removed",
below).

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
(4260) on `main`, and the server the task workers reach, at `http://<bridge>:7650`,
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

## 017: the scope and the DCIM reader

The Infrahub reader reads the OpsMill schema library's DCIM at a pinned commit,
`opsmill/schema-library@26336e9`, vendored under `schema/dcim/`, by one documented mapping
([mapping.md](../specs/017-dcim-reader/contracts/mapping.md)), reader `infrahub-dcim`, in
place of Fylgja's generics and the contract node ([D-057](../docs/decisions.md#d-057)); what
a twin is of is a **scope**. **Everything not named here is as 015 left it.** Identifiers,
exit statuses and the JSON documents are the contract; text is illustrative except where a
sentence is quoted. The wire is [api.md](api.md), "017: the scope and the DCIM reader".

### The scope

Moved at 019: nothing follows, so no check reads under a twin's scope ("019: following
removed", below).

`tag:<name>`: the literal `tag:` and one shell word (`^tag:\S+$`). It names the devices a
twin is of: every `DcimDevice` on the branch carrying the `BuiltinTag` of that name,
whatever its status; ports and cables follow their devices.

```
fylgja twin create   --branch <b> [--at <t>] [--scope tag:<name>] …
fylgja twin create   --stage <b>/<label> [--scope tag:<name>] …
fylgja twin rehearse --branch <b> [--scope tag:<name>]
fylgja intent read   --branch <b> | --stage <b>/<label> [--scope tag:<name>] --out ctm.json
fylgja stage plan    --branch <b> [--scope tag:<name>]
fylgja stage list    [--branch <b>] [--scope tag:<name>]
```

- Given, the scope is the request's; not given, the server's `FYLGJA_DEFAULT_SCOPE`. Every
  stage a command resolves, reads or plans is read under that one scope, but the twin's:
  `stage list` judges the twin's stage for `stage.twin.moved` under the scope its record
  names, as `twin step` reads it. The document's `subject.scope` names the request's from
  the moment it is resolved.
- `twin step` takes no `--scope`: `rejection operation.failed twin.step: unknown flag:
  --scope`, exit 2, with no request. It reads under the scope its twin's record carries,
  and a following twin's checks read under the twin's.
- `twin show` prints it; `twin compile` takes none, since the CTM carries it; `twin
  provision`, `twin verify`, `twin destroy`, `schema check` and `psp validate` take none.
- The checks `fylgja-step` and `fylgja-twin` send no `scope`: theirs is the server's
  default. A server with none refuses each check's request `scope.unset`, which the check
  concludes as failure, as it concludes any refusal it does not pass over.

### `fylgja serve` and `FYLGJA_DEFAULT_SCOPE`

| | |
|---|---|
| The variable | `FYLGJA_DEFAULT_SCOPE`, read by the server at start and never by a client or the worker; documented in `.env.example`; scaffolded by `scripts/bring-up.sh` as `tag:fylgja` |
| The report's line | straight after the state root line: `fylgja serve: default scope: tag:fylgja`, or `fylgja serve: default scope: unset (a request that names no scope is refused)` |
| The refusal to start | an unset or empty value is reported, not refused; a value that is not `tag:<name>` is `fylgja serve: FYLGJA_DEFAULT_SCOPE <value> is not tag:<name>`, exit 2, after `--listen`'s check and before the state root is resolved |

Two packages naming one manufacturer and platform pair, among the embedded and the override
packages once shadowed, refuse the start as an override package `psp validate` rejects does:
the `psp.matches.duplicate` finding as text, then `fylgja serve: refusing to serve with an
invalid support package`. Two declaring one `platform.id` refuse it alike, under
`psp.identity.duplicate`, since a device names its package by id. `worker run` refuses to
start on the same registry.

### The text

- `intent read`'s summary line names the scope before the schema: `wrote ctm.json: 3
  devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared
  ports (branch fylgja-fixture, scope tag:fylgja, schema 7c413536…)`; with cables omitted,
  `…, 0 shared ports; 2 cables omitted (branch …)` (`; 1 cable omitted` for one); with a
  stage, as 014 has it.
- `twin show`'s record line ends with the record's provenance: `record: branch
  fylgja-fixture, bundle_id f764e1fa…, schema 7c413536…, scope tag:fylgja, read by
  infrahub-dcim from opsmill/schema-library@26336e9`; for a record of `7` or earlier, `…,
  scope unknown (record 7)`; for an `8` whose scope is not `tag:<name>`, which no build
  writes, `…, scope unknown (record 8 names scope "fylgja", not tag:<name>)`, its JSON
  record carrying neither `scope` nor `mapping`, as a `7`'s; for an `8` whose mapping
  `twin.json` 8 cannot hold, a reader's name not of its form or a model or version left
  empty, which no build writes either, `…, scope tag:fylgja, read by an unknown reader
  (record 8 names mapping reader "Infrahub DCIM")`, each field it fails named (`model ""`,
  `version ""`), its JSON record carrying neither, since the show contract has the scope
  only beside the mapping, and `twin step` refuses it (below; T113). `twin create` prints the same
  line for the twin it made, from the record its run wrote, after the nodes and before `twin
  directory …`, as `twin show` prints it after the nodes; `twin provision` does too, its
  record naming what its bundle's provenance names.
- `schema check`'s first line is `conformant with opsmill/schema-library@26336e9:
  DcimDevice, DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable,
  DcimConnector`, the mapping's table in its order, the generic `DcimConnector` among it
  since the `Ports` query reads its `connected_endpoints` through it; then 014's `stages:
  …` line.
- `stage plan`'s heading and `twin rehearse`'s end `, scope tag:fylgja`, and the report's
  markdown heading names the scope; `stage list`'s headings do not.
- The branch point of a `main` holding no device in the scope, in `stage plan` and `twin
  rehearse`:

  ```
  change-1/branch-point: refused (scope.empty)
    rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at 2026-10-26T13:29:45.838959Z
  ```

- The refusals of the scope and of the platforms, as they print:

  ```
  rejection scope.invalid [step start] fylgja: --scope "fylgja" is not a scope: the accepted form is tag:<name>, the literal tag: and one word, the tag every device of the twin carries
  rejection scope.unset [step start] FYLGJA_DEFAULT_SCOPE: no --scope was given and the server has no default: name one with --scope tag:<name>, or set FYLGJA_DEFAULT_SCOPE where fylgja serve starts
  rejection scope.empty tag:nothing: scope tag:nothing selects no device on branch fylgja-fixture
  rejection platform.missing n2: device n2 carries no platform; its support package is the one whose matches name its platform and manufacturer
  rejection platform.unmatched n1: device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]
  info omit.cable.ends c-three: cable c-three is omitted: other than two ends (3); its ends are n1:ethernet-1/4, n2:ethernet-1/3, n3:ethernet-1/3
  ```

- `twin step` on a record of `7` or earlier is refused at `resolve`, exit 1:
  `step.twin.unsteppable`, `the twin was created from a record version this build no
  longer reads (twin.json 7); fylgja twin destroy clears it`, as a `5` is; on an `8` whose
  scope is not `tag:<name>` alike: `the twin's record names scope "fylgja", which is not
  tag:<name>, and every read a step makes is under the record's scope; fylgja twin destroy
  clears it`; and on an `8` of a known scope whose mapping `twin.json` 8 cannot hold, each
  field it fails named in `twin show`'s order (`reader "Infrahub DCIM"`, `model ""`,
  `version ""`), since a step that diverges writes the record's mapping into its own record,
  which no build writes: `the twin's record names mapping reader "Infrahub DCIM", which
  twin.json 8 cannot hold, and a step that diverges keeps the record's mapping in the record
  it writes; fylgja twin destroy clears it` (T113). Each is refused before any Infrahub read, after the check for a rehearsal in
  flight, which comes before every other refusal: with the workflow service down, a step
  that is not a dry run ends `operation.failed` at `start` first.

### Identifiers

Seventeen added and eight removed. No status, step or exit is new.

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `scope.invalid` | rejection, 2, `start` | the value given | `--scope` is not `tag:<name>`, an empty value included; before any connection, after `--branch`'s and `--stage`'s guards |
| `scope.unset` | rejection, 2, `start` | `FYLGJA_DEFAULT_SCOPE` | no `--scope` and the server has no default; before any connection |
| `scope.empty` | rejection, 1, `read` (none on `intent read`; a stage's at its read, the branch point's included, where `contract.node.missing` was); `resolve` for a stage's head (a warning in `stage list`) | the scope | the device query answered 0 on the branch at the `at`; or, for a head, the stamps read under the scope selected no device and the branch holds no intent event since its branch point, so the head has no `at` (`scope <scope> selects no device on branch <b>`); the rehearsal and `fylgja-step` pass over a branch point refused by this rule at `read` alone, as they passed over `contract.node.missing` |
| `schema.kind.missing` | rejection, 1, `read`; `resolve` in a stage command (below); none on `schema check` | the kind | the branch's schema lacks a kind the mapping reads |
| `schema.field.missing` | rejection, 1, `read` | `<kind>.<field>` | the kind lacks a field the mapping reads |
| `schema.field.mismatch` | rejection, 1, `read` | `<kind>.<field>` | the field's kind, cardinality, peer or optionality is not the mapping's; names both |
| `schema.choice.missing` | rejection, 1, `read` | `<kind>.<field>` | the dropdown lacks `management` (role) or `disabled` (status) |
| `schema.used_by.missing` | rejection, 1, `read` | the generic | the generic is not implemented by the kind the mapping expects |
| `platform.missing` | rejection, 1, `read` | the device | no platform, or a platform with no manufacturer; names what the device carries |
| `platform.unmatched` | rejection, 1, `read` | the device | no package matches the pair exactly; names the pair and every package's pairs |
| `omit.cable.ends` | info, 0, `read` | the cable | other than two ends |
| `omit.cable.endpoint` | info, 0, `read` | the cable | an end not on a physical port |
| `omit.cable.outside_scope` | info, 0, `read` | the cable | an end outside the scope |
| `omit.cable.kind` | info, 0, `read` | the connector | a connector that is not a DcimCable (`<kind>`) |
| `ctm.version.unsupported` | rejection, 1, none | the CTM file | `twin compile` given a CTM of another version, or declaring none; names both, or the one it reads |
| `psp.matches.missing` | rejection, 1, `verify` | the package path | no match, or a pair with an empty name |
| `psp.matches.duplicate` | rejection, 1, `verify` | the package path | two packages name one pair; names both packages and the pair; also refuses `serve` and `worker run` at start, and the registry's load |

A stage command (`stage plan`, `stage list`, `twin create --stage`, `intent read --stage`,
`twin step`, `twin rehearse`) checks the conformance of each branch whose stamps it reads,
the source branch and the destination, once, before its first stamps read, and files a
branch that does not conform under the read's `schema.*` findings at `resolve`, every one
in one pass, each message prefixed `branch <b>: `, exit 1: the source branch's refuses the
proposed change whole; the destination's refuses a plan's branch point, and any other
stage's resolution at `stage.main.moved`; `stage list` lists its rows beside them, the
source branch's head with no `at`. A stage's head with no `at` because the stamps read under
the scope selected no device is `scope.empty` at `resolve`; `stage.at.unresolved` names a
head whose devices carry no stamp (`… Infrahub returned no stamp for the devices scope
<scope> selects on branch <b> or for anything of theirs …`).

Removed: `contract.version.mismatch`, `contract.node.missing`,
`schema.generic.unimplemented`, `schema.artifact_target.missing`,
`interface.iftype.unimplemented`, `interface.mgmt_only.iftype`,
`interface.parent.missing` and `link.endpoint.iftype`: every interface is a port, and a
cable is a link only with exactly two physical ends inside the scope, an *omission*
otherwise. `platform.unsupported` stays, for a CTM naming a package this build lacks.

### Formats and versions

| Format | Version | Change |
|---|---|---|
| the API | `1` | `scope`, an optional argument of `twin.create`, `twin.rehearse`, `intent.read`, `stage.plan` and `stage.list` ([api.md](api.md)) |
| findings | `1` | `subject.scope`; `verified` is `{model, version, kinds: [{kind, fields}], stages}`, without `contract_version` and `generics`; `show.record` carries `scope` and `mapping` and no `contract_version`; the seventeen identifiers |
| CTM | `2` | [ctm.schema.json](ctm.schema.json): the platform is a package, every interface a port, the envelope carries `scope`, `mapping` and `fidelity` and no `contract_version` |
| bundle manifest | `5` | [manifest.schema.json](manifest.schema.json): `provenance` is `{branch, at?, schema_hash, scope, mapping{reader, model, version}}`; a `mapping[]` row has no `iftype`; `fidelity.read` is the CTM's fidelity list, copied |
| `twin.json` | `8` | [twin.schema.json](twin.schema.json): `provenance` as the manifest's |
| PSP | `0.7` | [psp.schema.json](psp.schema.json): `platform.matches`, the manufacturer and platform name pairs a package is, matched exactly |
| contract | retired | the CTM's version is the contract's |

- `twin compile` refuses a CTM `1` `ctm.version.unsupported`, and a CTM declaring no
  version alike (`the CTM declares no ctm_version; this build reads "2", …`), never reading
  it as a `2`; a CTM leaving out `envelope.fidelity`, or writing it null, is a rejection
  `data.required.missing` naming `envelope.fidelity`, exit 1, nothing written, since `[]`
  would say the reader approximated and omitted nothing, and one leaving out `links` or a
  device's `interfaces`, or writing either null, alike, naming `links` or
  `devices[<i>].interfaces` (`<i>` the device's place in the file), since `[]` would say
  there is no cable or no port; `intent read` writes a tagged device with no physical
  port `"interfaces": []`; the compile activity refuses each `operation.failed` at
  `compile`, as it refuses any CTM it cannot load; `twin provision` refuses a
  bundle `4` `bundle.version.unsupported`, naming both, as it refused a `3`; a package
  declaring `0.6` or earlier is `psp.version.unknown`, `package declares format version
  "0.6", this build understands "0.7"`.
- Validation holds a CTM's envelope to its contract's forms, wherever a CTM is validated,
  `twin compile` included, each a rejection `data.required.missing`, exit 1, naming the
  field, as an empty one is: `envelope.scope` not `tag:<name>` (`the scope intent was read
  under is "fylgja", which is not a scope: the accepted form is tag:<name>, …`),
  `envelope.mapping.reader` not `^[a-z0-9][a-z0-9-]*$`, and a fidelity row of a
  disposition other than `approximated` and `omitted`
  (`envelope.fidelity[<i>].disposition`) or with its `object`, `source` or `reason` empty
  (`envelope.fidelity[<i>].reason`, …), `<i>` its place in the list sorted by the whole
  row, (disposition, object, source, reason). So a CTM validation accepts compiles to a manifest
  `manifest.schema.json` accepts, and a record refuses a provenance naming a scope or a
  reader of another form, as `twin.schema.json` does.
- A `7` record reads with no scope: `twin show` shows it, `twin step` refuses it, `twin
  destroy` clears it, and `twin rehearse` reclaims it when it names a dead rehearsal.
- The versions of the findings document and of the API did not move: a `1` reader ignores
  `subject.scope`, and the removals from `verified` and `show.record` are read by this
  build's `twin show` and `schema check` alone, by no check and by no recorded history.

### Workflows and activities

Moved at 019: `StartFollowingInput`, `ReconcileInput` and `ReadIntentInput` are gone with
the reconcile ("019: following removed", below).

None is added, removed or changed: no workflow decision, activity, budget or version
marker. `ProvisionInput`, `StartFollowingInput`, `ReconcileInput` and `ReadIntentInput`
carry `scope`, omitted when empty, so the nine recorded histories replay; the runs branch
on nothing of it. The read refuses a scope that is not `tag:<name>` before any connection,
as `operation.failed` at `read`, `the read names scope "", which is not tag:<name>: a twin
created before 017 follows its branch under no scope, and this build reads only under one;
fylgja twin destroy clears it`: the checks of a following twin created before 017, whose
`ReconcileInput` names none, end so.

### Tier 3 (`scripts/e2e.sh`)

The nine cases, unchanged in what they assert but the reader's: every fixture is in the
library's kinds, tagged `fylgja`, and the marker is a device's `description`. Case 1's
record names the scope and the mapping, and `twin show`'s text holds `scope tag:fylgja, read
by infrahub-dcim from opsmill/schema-library@26336e9`; case 5's create passes `--scope
tag:fylgja`; cases 7, 8 and 9 read the branch point refused `scope.empty`, for want of a
tagged device on `main`. Before any case, the script's own server must report `default
scope: tag:fylgja`, read from `local/.env`, and for case 9 the operator's server on the
bridge must carry `FYLGJA_DEFAULT_SCOPE=tag:fylgja` in its environment, since the checks
send no scope.

## 018: snapshots

The core's one input is the **snapshot**: one document of version `1` wrapping an
unchanged CTM `2`, with a slot for probe declarations, empty until 016, and an id of its
own, the hash of its body without the read's `observed_at`
([snapshot.schema.json](snapshot.schema.json); [D-061](../docs/decisions.md#d-061)).
The server takes one for every create and files it under the state root's `snapshots/`,
beside the bundles; every workflow the core runs but the reconcile takes a snapshot id
and a bundle id and never a branch. **Everything not named here is as 017 left it.**
Identifiers, exit statuses and the JSON documents are the contract; text is illustrative
except where a sentence is quoted. The wire is [api.md](api.md), "018: snapshots".

Moved at 019: the reconcile is gone, so every workflow takes a snapshot id and a bundle id
("019: following removed", below).

### The commands

Moved at 019: nothing follows, `--interval` and `--no-follow` are unknown flags, and a
`--snapshot` twin steps ("019: following removed", below).

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
  snapshot filed, since its CTM validated, and its `snapshot_id … stored:` line names it,
  as the document's `snapshot_id` does; so does a bundle's filing that is refused or
  fails. An Infrahub that fails or times out during the read is `operation.failed` at
  `read` at once; the worker's retries and heartbeat no longer apply to a create, as they
  do not to a step or a rehearsal. Following is as before: a `--branch` twin with no
  `--at` and no `--no-follow` follows its branch, and a twin a check's rebuild makes names
  no snapshot.
- **`twin create --snapshot <arg>`**: `<arg>` of 64 lowercase hex characters is a
  snapshot id, looked up in the store; anything else is a file the client reads and
  sends. An id the store does not hold is `snapshot.unknown` at `resolve`, exit 1,
  before any run; a file is read as [snapshot.schema.json](snapshot.schema.json) says,
  its CTM held to the rules validation applies that read no package (the envelope's, the
  device list's, each device's and interface's name, the links'), each refusal at
  `compile` under the rule and object the compile gives it, with nothing filed, and then
  filed under its id (an entry already there is kept, and the twin records the stored
  document's `observed_at`, the first take's); then the compile, the filing and the run as
  above, where a refusal that needs the server's packages (a platform no package matches)
  leaves the file filed, as a read's take is. No request reaches Infrahub. Such a twin is **frozen by rule**: its reference is
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
- **`fylgja serve`** and `worker run` name the snapshot store in their state root line:
  `fylgja serve: state root /srv/fylgja/local (bundles: /srv/fylgja/local/bundles,
  snapshots: /srv/fylgja/local/snapshots, twin: /srv/fylgja/local/twin)`. Nothing creates
  the directory at start; the first snapshot filed does.

### The text

Moved at 019: the dry run has no `follow:` line, and the kind line is `snapshot …` ("019:
following removed", below).

- `twin create` and its dry run print, before the run's `start` (or the dry run's
  report):

  ```
  snapshot_id 576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482  stored: /home/…/local/snapshots/576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482.json
  bundle_id f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147  stored: /home/…/local/bundles/f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147
  ```

  A compile, or the bundle's filing, that refuses or fails once the snapshot is filed
  (by a create's take, or at `--snapshot`'s `resolve`) prints the snapshot's line alone on
  stdout, and the refusal on stderr; a refused read, or a snapshot refused at `resolve`,
  prints neither line. A dry run whose host check cannot run (`operation.failed` at
  `host_check`) has filed both, and prints both lines alone on stdout, in this order, with
  the failure on stderr; its document names both ids, after the read's and the compile's
  findings, as a create's run failing at the host check does (`twin provision --dry-run`,
  which files no snapshot, prints and names its bundle alone). The dry run's `follow:` line
  for `--snapshot` reads `would not follow (--snapshot given: a twin built from a snapshot
  never follows)`.
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
  branch b, snapshot none (record <version>), bundle_id …` for a record of `8` or earlier,
  `(record 8)` for an `8`. `twin
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

Moved at 019: `follow.flags.conflict` is retired ("019: following removed", below).

Five added. No status, step or exit is new.

| Rule | Severity, exit, step | Object | When |
|---|---|---|---|
| `snapshot.invalid` | rejection, 1, none (`twin compile`) or `resolve` (`twin create --snapshot <file>`) | the field, or the file | the outer shape is not version 1's: an unknown key, `ctm` absent or not an object, `probes` absent, null or not empty, `snapshot_id` not 64 lowercase hex characters, `observed_at` not of the CTM's form or not the inner CTM's; or the inner CTM's `observed_at` not of that form, at `ctm.envelope.observed_at` |
| `snapshot.version.unsupported` | rejection, 1, none or `resolve` | the file | `snapshot_version` is not `"1"`, or absent; names the version read, or that none was, and `"1"` |
| `snapshot.id.mismatch` | rejection, 1, none or `resolve`; `compile` for the store | the file, or the store path | a declared `snapshot_id` is not what the body hashes to, naming both; or an entry under the id hashes to another, or hashes to it and declares another, naming the path and both |
| `snapshot.unknown` | rejection, 1, `resolve` | the id | `twin create --snapshot <id>` names an id the store does not hold; names the store's directory |
| `snapshot.flags.conflict` | rejection, 2, `start` | the flag | `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope`, the first found in that order; before any connection |

`follow.flags.conflict` gains the `--snapshot` sentence. The inner CTM's faults keep
`ctm.version.unsupported`, its object the snapshot file, and `data.required.missing`, its
object the field prefixed `ctm.`, at `twin compile --snapshot` (no step) and at `twin create
--snapshot`'s `resolve`; validation's rules refuse at compile as they do a bare CTM. Its
`observed_at` is held at the file, before anything is filed, since the id leaves it out and an entry filed without it
could not be read back under the id every take of that intent hashes to: none recorded is
`data.required.missing`, one not of the CTM's form `snapshot.invalid`, each at
`ctm.envelope.observed_at`. The client's own refusal of a
snapshot file it cannot read is `operation.failed`, exit 2, `reading snapshot: open
<path>: …`, before any connection, as for a CTM at M13. The client reads the file only
when none of `--branch`, `--stage`, `--at`, `--scope` and `--interval` is given beside
`--snapshot`, as `twin compile` holds its read back for the server's refusals: when one
is, it sends `snapshot` with no file, and the server's guard answers
(`snapshot.flags.conflict` or `follow.flags.conflict`), whatever the file, before the
request's files are held to their shape. An explicit empty `--snapshot=` with none of
those beside it names no file and is the client's own `operation.failed`, exit 2,
`--snapshot= is empty; give a snapshot id or the path of a snapshot file`, before any
connection; beside one, the guard answers.

### Formats and versions

Moved at 019: `twin.json` `10`, and the following blocks and kinds are gone ("019: following
removed", below).

| Format | Version | Change |
|---|---|---|
| snapshot | `1` | new: [snapshot.schema.json](snapshot.schema.json), `$id` `…/contracts/snapshot/v1`, referencing CTM `2` by its `$id`; its description says that the bytes the id hashes differ from the stored bytes, and gives the hand recipe |
| `twin.json` | `9` | [twin.schema.json](twin.schema.json): `snapshot_id`, required, a snapshot id or null (null for a twin `twin provision` built, one a following rebuild made, or a record of `8` or earlier, which reads with none); `source` gains `snapshot`, a twin `twin create --snapshot` built, and `intent` reads "created by twin create --branch or --stage: the server read and compiled, or a check's rebuild did"; `step.from` and `step.to` gain an optional `snapshot_id`, absent where the side's is not known (the from side of an `8` record that stepped); `observed_at` is the run's input's read time, a create's, a snapshot's stored take or a check's, null for `twin provision` |
| findings | `1` | [findings.schema.json](findings.schema.json): `snapshot_id`, optional, beside `bundle_id` on `twin.compile` and `intent.read` (status ok), `twin.create` and its dry run (once the take completed), and `twin.step` and its dry run (the target's); `subject.snapshot`, `--snapshot` as given, an id or a path, on `twin.compile` and `twin.create --snapshot`, where `subject.ctm` stays for older documents and no build writes it; `dry_run.follow.reason` gains `snapshot`; the five identifiers |
| the `show` block | `1` | [show.schema.json](show.schema.json): `record.snapshot_id`, required, the record's id or null (a `9` naming none, or a record of `8` or earlier, whose record line says `(record <version>)`, `(record 8)` for an `8`); `record.source` gains `snapshot`; `record.step.from` and `.to` gain an optional `snapshot_id`; `kind` unchanged, a `--snapshot` twin `pinned` or `frozen`, its note `built from snapshot <id>` among `notes` |
| the `stages` block | `1` | [stages.schema.json](stages.schema.json): `plan_stage.snapshot_id`, required, the stage's snapshot once its read was filed, null when the stage was refused at resolution or read; the step pair, the rows, the record and the list unchanged, since `stage list` neither reads nor compiles |
| the `step` block | `1` | [step.schema.json](step.schema.json): each side's optional `snapshot_id`, absent on a from side whose record names none (a record of `8`) |
| the `rehearsal` block | `1` | [rehearsal.schema.json](rehearsal.schema.json): each stage's `snapshot_id`, required, beside `bundle_id`, null when the stage was refused; the markdown's table carries a `snapshot` column before `bundle` |
| the API | `1` | `snapshot` on `twin.create`, with one file beside it; `twin.compile`'s `ctm` becomes `snapshot`; `intent.read` answers `snapshot.json` ([api.md](api.md), [api.schema.json](api.schema.json)) |
| bundle manifest, CTM, PSP | `5`, `2`, `0.7` | none: the goldens stand |

- `twin compile --snapshot` refuses a snapshot of another version, or declaring none,
  `snapshot.version.unsupported`, never reading it as a `1`; the inner CTM's version and
  required fields as 017 refuses a bare CTM's, the version at the file and a missing field
  at its name prefixed `ctm.`.
- The bundle's CTM sidecar `<bundle_id>.ctm.json` is retired: no build writes one and the
  ones on disk are never read. `bundles/.reads/` stays, the reconcile's alone.
- A `9` record reads with its snapshot; an `8` reads with none: `twin show` says `snapshot
  none (record 8)`, `twin step` steps it with a from side naming no snapshot, `twin
  destroy` clears it.
- The earlier contracts are frozen where tests read them: `twin.json` `8` under
  `internal/lab/testdata/contracts/017-dcim-reader/`, and the findings contract with its
  `show`, `stages`, `step` and `rehearsal` blocks as 017 left them under each of
  `internal/findings`, `internal/server` and `internal/cli`'s
  `testdata/contracts/017-dcim-reader/`, so a document naming no snapshot still validates
  under 017's contract.
- The version of the findings document and of the API did not move: a `1` reader ignores
  `snapshot_id` and a block's new key, and a client that never sends `snapshot` is served
  as before.

### Workflows and activities

Moved at 019: the reconcile and the provision's read-and-compile branch are gone, with two
histories ("019: following removed", below).

None is added, removed or changed: no workflow decision, activity, budget or version
marker. `ProvisionInput`, `RecordInput`, `StepSide` and `RehearseStage` carry
`snapshot_id`, omitted when empty, so the nine recorded histories replay; the runs branch
on nothing of it. Every `fylgja-provision` the server starts is already compiled, as a
check's rebuild has been since M4, so its history holds no `ReadIntent` and no `Compile`;
the provision workflow keeps its read-and-compile branch for the recorded histories and
the reconcile keeps both activities. The `Compile` activity files no sidecar.

### Tier 3 (`scripts/e2e.sh`)

Moved at 019: case 5 steps where it rebuilt ("019: following removed", below).

The nine cases, unchanged in what they assert but the records': the read-then-compile
helper reads with `--out`, a snapshot, and compiles with `--snapshot`, and cases 1 and 2
hold the create's snapshot to the one it compiles, as they hold the bundle; every create
asserts `snapshots/<snapshot_id>.json` exists and that no `bundles/*.ctm.json` is newer
than the case's start, since the host's store keeps the sidecars of every read before this
feature; `twin.json` names the create's snapshot; case 1's `twin show` text holds
`snapshot <id>, bundle_id <id>`; case 4's create takes case 2's snapshot; case 5's
created twin names its snapshot in `twin show`, and its rebuilt twin reads
`.show.record.snapshot_id == null` and `snapshot none, bundle_id <id>`; case 7's plan names
three snapshot ids, the branch point's null, the create takes the plan's for `seeded`, and
each step's sides name the plan's snapshots, the target's in `twin.json` too. The marker
grep passes over a read's snapshot (`snapshot-*.json`) where it passed over its CTM. No case
is added.

## 019: following removed

A twin is frozen at its snapshot, and nothing rebuilds it but the operator
([D-062](../docs/decisions.md#d-062)). No command makes a Schedule; the worker serves four
workflows and fifteen activities, and reads no source of truth. **Everything not named
here is as 018 left it.** Identifiers, exit statuses and the JSON documents are the
contract; text is illustrative except where a sentence is quoted. The wire is
[api.md](api.md), "019: following removed".

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
- **`twin create`** follows nothing, from any reference: its document has no `following`
  key, its dry run no `follow:` line and no `dry_run.follow`, and a ready twin's text ends
  at `twin directory …`, since the record line before it names the stage and the `at`.
- **`twin step`** steps any twin whose record names a snapshot, built by `--branch`,
  `--stage` or `--snapshot`:
  - `--stage <b>/<label>` names a stage of **any** proposed change, resolved, judged and
    read under the record's scope. Left out, it means the next stage of the twin's own
    proposed change; for a twin whose record names no stage, a target is required.
  - `--snapshot <id|file>` takes the forms `twin create --snapshot` takes: an id the
    server's store holds, or a file read here and sent, which the server files under its
    id. No request reaches Infrahub for it. A snapshot of any branch. The server resolves
    it as a create does, compiles it and files its bundle, each refusal at `resolve` or
    `compile` before any run, and the twin untouched.
  - The record afterwards names the target's branch, `at`, snapshot and bundle, and its
    stage, or none for a snapshot target, and keeps its `source`. Scope and mapping are the
    twin's for life: a target of another scope or mapping is refused before any run, and
    a snapshot target's bundle is then never filed.
  - A twin `twin provision` built, a record of `8` or earlier, and a record naming no
    snapshot do not step.
  - `stage.twin.moved` is given only for a target in the record's own proposed change;
    `stage list` gives none beside a twin whose record names no stage.
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

- The `snapshot none` line is followed by the note `the twin's record names no snapshot, so
  fylgja twin step refuses it; fylgja twin destroy clears it`. A twin with no `at` keeps
  the best-effort note; `from a bundle` notes `provisioned from a bundle; read time
  unknown`; 018's note `built from snapshot <id>` is gone, since the kind line and the
  record line name the snapshot.
- "; not following" is gone from every line, and so are the last check and the next.
- A step in flight: `…; run fylgja-step <run> is at step push, stepping towards snapshot
  9c2d01e7…`, or `stepping towards stage <branch>/<label>`.
- An unreachable workflow service: the warning `show.service.unreachable`, `the workflow
  service at localhost:7233 did not answer within 5s: whether a run is in flight is
  unknown`, whatever the cause, and the line `in flight: unknown (workflow service
  unreachable at localhost:7233)`; the host and the record are reported, exit 0.

`twin verify`'s first line names the snapshot of the staged bundle beside it: `twin: branch
fylgja-test-readme (snapshot 9c2d01e7…, bundle 2b7e90c1…), ready; …`, `snapshot none`
when the record names none.

The dry run of `twin create` has no `follow:` line. A rehearsal's deadline is 30 s shorter:
015's sample reads `deadline 32m30s` and `of the 1950s deadline`.

### Identifiers

| Identifier | Severity, exit, step | When |
|---|---|---|
| `snapshot.flags.conflict` | rejection, 2, start | gains: `--stage` beside `--snapshot` on `twin step`, object `--stage` |
| `step.target.unknown` | rejection, 1, resolve | gains: no `--stage` and no `--snapshot` for a twin whose record names no stage, object the record's `bundle_id`, read before any connection |
| `step.twin.unsteppable` | rejection, 1, resolve | reworded: a bundle twin, a record of 8, a record naming no snapshot; and a target whose scope or mapping differs from the record's, object the target, naming both |
| `stage.flags.conflict` | rejection, 2, start | `--branch` or `--at` beside `--stage` (no `--interval`) |
| `show.service.unreachable` | warning | `whether a run is in flight is unknown` |
| `snapshot.unknown`, `snapshot.id.mismatch`, `snapshot.invalid`, `snapshot.version.unsupported` | as on create | on `twin step --snapshot`, at resolve |

The wordings, in shape:

- `snapshot.flags.conflict`: `--stage is meaningless with --snapshot: the snapshot is the
  target`.
- `step.target.unknown` with no target: `the twin names no stage, so there is no next stage
  to step to; give --stage <branch>/<label> or --snapshot <id|file>`; with the record's
  proposed change closed: `proposed change <id> on branch change-1, the twin's, is no
  longer open (the open proposed change on change-1 is pc-9), so the twin has no next
  stage; give --stage <branch>/<label> or --snapshot <id|file>`. A step no longer stays
  inside the proposed change the twin was built from: a `--stage` of another is the
  target, refused `step.target.unknown` naming that proposed change's stages when it has
  no such label.
- `step.twin.unsteppable`, judged after 017's refusal of a record naming no scope, a bundle
  twin's first: `the twin was provisioned from a bundle, which names no snapshot; only a
  twin whose record names a snapshot steps; fylgja twin destroy clears it`; `the twin was
  created from a record version that names no snapshot (twin.json 8); only a twin whose
  record names a snapshot steps; fylgja twin destroy clears it`; `the twin's record names
  no snapshot (an earlier build's rebuild made it); only a twin whose record names a
  snapshot steps; fylgja twin destroy clears it`. No twin ends `…; a twin built from a
  snapshot steps (fylgja twin create --branch, --stage or --snapshot)`, and an orphan, an
  unreadable record, a lab gone and a leftover end `…; a twin built from a snapshot steps;
  fylgja twin destroy clears it`, where each said a twin built from a stage steps. A
  target held to the record: `the twin's record names scope tag:fylgja and mapping infrahub-dcim
  opsmill/schema-library 26336e9; snapshot 576933ec… names scope tag:other and mapping
  infrahub-dcim opsmill/schema-library 26336e9; a twin's scope and mapping are fixed when
  it is created; fylgja twin destroy and create again to change them`.

**Retired**: `follow.interval.invalid`, `follow.flags.conflict`, `follow.start.failed`,
`follow.stop.failed`, `follow.stopped`, `check.skipped`, `rebuild.failed`,
`step.target.foreign`; the step `follow`.

### Formats and versions

| Format | Version | Change |
|---|---|---|
| `twin.json` | `10` | [twin.schema.json](twin.schema.json), `$id` `…/contracts/twin/v10`: a stage needs `provenance.at` alone, so a `--snapshot` twin stepped to a stage names it beside `source: snapshot`; a step keeps `source`; `snapshot_id` null names an earlier build's rebuild, not a check's |
| findings | `1` | [findings.schema.json](findings.schema.json): `following` and `dry_run.follow` removed; the step `follow` and the eight identifiers retired |
| the `show` block | `1` | [show.schema.json](show.schema.json): `kind` one of `none`, `snapshot`, `from_bundle` and `diverged`; `following`, `last_check` and `$defs/check` removed |
| the `verify` block | `1` | [verify.schema.json](verify.schema.json): `twin.snapshot_id`, required, the staged bundle's snapshot (the record's, or the step's target's for a diverged twin), or null; `twin.source` admits `snapshot`, a `--snapshot` twin's, which its steps keep; additive |
| the `stages` block | `1` | [stages.schema.json](stages.schema.json): `$defs/side_name`, a step's side named `<branch>/<label>` or `snapshot <8 hex>…`; additive |
| the `step` block | `1` | [step.schema.json](step.schema.json): unchanged in shape; its description says a side names no stage when the step's target was a snapshot, or when the twin was built from one and has not stepped to a stage |
| the API | `1` | [api.schema.json](api.schema.json): `twin.create` takes neither `interval` nor `no_follow`; `twin.step` takes `snapshot`, with one file beside a path |
| bundle manifest, CTM, snapshot, PSP | `5`, `2`, `1`, `0.7` | none: the goldens stand |

- The versions of the findings document and of the API did not move: the removals are
  accepted pre-1.0, as the API's version `1` accepted 014's, 015's, 017's and 018's
  changes.
- A record of `9` reads as 018 wrote it. The earlier contracts are frozen where tests read
  them, under each of `internal/lab`, `internal/findings`, `internal/server` and
  `internal/cli`'s `testdata/contracts/018-snapshots/` (`twin.json` `9`, and the findings
  and `show` contracts with their following blocks), so a document an earlier build wrote
  still validates under 018's contract.

### Workflows and activities

`Provision`, `Destroy`, `Step`, `Rehearse`, and the lab's fifteen activities. `Reconcile`,
the Schedule `fylgja-follow`, `ReadIntent`, `Compile`, `RunsInFlight`, `StartFollowing`
and `StopFollowing` are gone, and `bundles/.reads/` is written by nothing. A provision
with no bundle id ends `operation.failed` at `host_check` and schedules no activity. Seven
recorded histories replay; the two of a cancelled following went with it. The rehearsal's
baseline provision stops nothing, so every rehearsal's `deadline_s` is 30 s shorter.

### Environment

The worker reads `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` no longer.

### Upgrading

Destroy a following twin before upgrading a host of an earlier build: a Schedule
`fylgja-follow` left behind starts a workflow no worker of this build serves, and this
build carries no code to clear it.

### Tier 3 (`scripts/e2e.sh`)

Nine cases. Case 5 creates from `--branch`, edits the branch and shows, over 330 s from
the moment the change is visible to a read, that no run starts (the workflow service lists
none since the create's answer) and that the record, the containers and the kind line do
not move; then steps to a snapshot by file (an artifact-only change, the readback and
verify 5a, which names the snapshot) and by id (a topology change), and `twin show` names
the step from the first. Cases 7 and 8 read the kind `snapshot` where they read `pinned`.
No case passes `--no-follow` or `--interval`, and none makes a Schedule; the trap still
refuses a stray `fylgja-follow`.
