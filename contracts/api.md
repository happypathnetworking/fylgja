# API contract: M13, version 1

What crosses between a client and `fylgja serve`. The shapes are
[api.schema.json](api.schema.json); the documents are M12's, unchanged
([findings.schema.json](findings.schema.json) and the blocks beside it). The addresses,
the statuses, the frame kinds and the document are the contract; a sentence is contract
only where it is quoted.

## Transport

HTTP/1.1, JSON, no TLS (D-040, D-042). The server listens on `127.0.0.1:7650` unless
`--listen` says otherwise. A client on another machine comes through an SSH tunnel or a
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
| `twin.create` | `/v1/twin/create` | `branch`, `at`, `waypoint`, `interval`, `no_follow`, `dry_run` | | | from `start` |
| `twin.provision` | `/v1/twin/provision` | `bundle`, `dry_run` | the bundle's regular files | | from `start` |
| `twin.step` | `/v1/twin/step` | `waypoint`, `allow_restart`, `dry_run`, `wait` | | | from `start` |
| `twin.destroy` | `/v1/twin/destroy` | | | | no |
| `twin.show` | `/v1/twin/show` | | | | no |
| `twin.verify` | `/v1/twin/verify` | `wait`, `args` | | | no |
| `twin.compile` | `/v1/twin/compile` | `ctm`, `out` | the CTM | the bundle | no |
| `waypoint.list` | `/v1/waypoint/list` | `series` | | | no |
| `waypoint.plan` | `/v1/waypoint/plan` | `series` | | | no |
| `intent.read` | `/v1/intent/read` | `branch`, `at`, `waypoint`, `out` | | the CTM | no |
| `schema.check` | `/v1/schema/check` | `branch` | | | no |
| `psp.validate` | `/v1/psp/validate` | `files` | each package | | no |

There is no other operation. In particular there is none to re-attach to a run, to list
runs or to fetch a filed bundle.

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
- a `render` other than `"text"` and `"json"`.

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
| `{"files": [{"path": "…", "data": "<base64>"}]}` | the CTM (`ctm.json`), or every file of the bundle |
| `{"document": {…}, "text": "…"}` | the command's findings document; `text` under `render: "text"` when it has findings |

**What `render` asks for.**

| `render` | `out` | `err` | `document.text` |
|---|---|---|---|
| absent | none | none | none |
| `"text"` | every line the command printed without `--json` at M12 | every line it wrote to stderr | its findings as text |
| `"json"` | none | what it wrote to stderr under `--json` | none |

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
progress. `twin.destroy` is followed the same way and takes no interrupt. Its `start`
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

- **`twin.compile`**: `files` holds the CTM under the path given. The answer's `files`
  frame holds the bundle, each file under its path inside it. A golden CTM comes back
  as the golden bundle, byte for byte. A request carrying no file or two, or one file
  under another path than `args.ctm`, is refused before anything is parsed:
  `operation.failed`, exit 2, in a sentence naming the count (`the request carries 0 files
  where twin compile takes the CTM alone`) or the path's mismatch (`the request carries its
  CTM under another path than --ctm gives, where twin compile takes the CTM alone, under
  that path`), and nothing of the file.
- **`intent.read`**: the answer's `files` frame holds `ctm.json`, before the summary
  line. A refused read has no `files` frame.
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
