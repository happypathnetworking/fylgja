# API 1

API 1 is the HTTP API of `fylgja-core-server`. [The command page](cli.md) describes the client
that ships with the core; a program of your own reaches the server with the requests below. The
checked-in document [`formats/api-1.openapi.yaml`](../formats/api-1.openapi.yaml) is the statement
of every member: each route, parameter, header, status and schema. This page takes a client through
them in the order a client uses them, and holds nothing the document does not say.

A request and an answer are JSON. A request with a body carries `Content-Type: application/json`. A
refusal is a problem document, `application/problem+json`. API 1 does not change: a server of API 1
answers every request this page shows. [What major version 1 holds](compatibility.md) says what an answer may
gain within major version 1, and how to read one. The examples use `curl` against the server's default
address.

## Reaching it

The server listens on `127.0.0.1:7650` unless its `FYLGJA_LISTEN` says otherwise, as
[the server page](server.md#settings) describes. Every route but `GET /v1/version` needs the header
`Authorization: Bearer <token>`, where the token is the one whose hash the server's token file holds
([the token file](server.md#the-token-file)). The examples read it from `$FYLGJA_API_TOKEN`. A
request with no token or an unknown one is refused with status `401`. Status `403` is reserved for
a client that may not make a call: no route answers it yet, and every known client makes every call.

A server given a certificate and a key serves HTTPS, and a client then names the address with
`https://` and verifies the certificate against its own trust; `curl` takes a CA file with
`--cacert`. A server given none serves HTTP, which fits the loopback address and nothing else
([TLS](server.md#tls)).

`GET /v1/version` answers the API version, the core's build and the version of each format. A client
checks that `api` is `"1"` before it relies on the rest. `build` is for people: show it in a bug
report, and parse nothing of it.

```sh
curl http://127.0.0.1:7650/v1/version
```

The answer is `200`:

```json
{
  "api": "1",
  "build": "1.0.0 (commit 0123abc)",
  "formats": {
    "blueprint": "1",
    "bundle": "1",
    "deployment": "1",
    "twin_record": "1",
    "findings": "1",
    "problem": "1",
    "platform_package": "1",
    "probe_package": "1"
  }
}
```

## Routes

Each route is one operation of the document. A path in braces takes an id or a name.

| Method | Path | Operation | Does |
|---|---|---|---|
| `GET` | `/v1/version` | `getVersion` | Answers the API version, the build and the format versions. Needs no token. |
| `POST` | `/v1/blueprints` | `putBlueprint` | Files a blueprint and answers its id. |
| `GET` | `/v1/blueprints/{blueprint_id}` | `getBlueprint` | Reads a filed blueprint. |
| `POST` | `/v1/bundles` | `buildBundle` | Compiles a filed blueprint and answers the bundle, its fidelity and its findings. |
| `GET` | `/v1/bundles/{bundle_id}` | `getBundle` | Reads a filed bundle's manifest. |
| `GET` | `/v1/bundles/{bundle_id}/diff/{to_bundle_id}` | `diffBundles` | Says what a step from one bundle to another changes. |
| `POST` | `/v1/packages:validate` | `validatePackage` | Holds one platform or probe package to its schema. |
| `GET` | `/v1/drivers` | `listDrivers` | Lists the drivers, their capabilities and the default. |
| `GET` | `/v1/capacity` | `getCapacity` | Reads the default driver's room, so a client can look before it asks. |
| `GET` | `/v1/twins` | `listTwins` | Lists every twin's record, or watches them. |
| `GET` | `/v1/twins/{name}` | `getTwin` | Reads one twin's record, or watches it. |
| `PUT` | `/v1/twins/{name}` | `applyTwin` | Creates a twin or steps it, by writing its spec; plans it with `dry_run`. |
| `DELETE` | `/v1/twins/{name}` | `deleteTwin` | Asks for the twin's deletion. |
| `POST` | `/v1/twins/{name}/verifications` | `verifyTwin` | Reads every node once and judges it against its bundle. |
| `GET` | `/v1/runs` | `listRuns` | Lists runs, newest first, all or one twin's. |
| `GET` | `/v1/runs/{run_id}` | `getRun` | Reads one run, with its verdict once it has ended. |
| `GET` | `/v1/runs/{run_id}/events` | `getRunEvents` | Reads a run's events after a cursor, or streams them. |
| `POST` | `/v1/runs/{run_id}/cancel` | `cancelRun` | Asks a run to cancel. |

A path the table does not list is `404`, and a method a path does not take is refused. A path takes
no trailing slash.

## Filing and compiling

A blueprint is filed by its content, so its id is a SHA-256 hash in lower-case hex, and filing the
same blueprint twice files it once. The body is the blueprint document itself, as
[the blueprint format](../formats/README.md) describes it. This files the three-node blueprint of
the repository's tree, run from a clone:

```sh
curl -H "Authorization: Bearer $FYLGJA_API_TOKEN" -H "Content-Type: application/json" \
  --data @testdata/blueprint/three-node.json http://127.0.0.1:7650/v1/blueprints
```

The first time, the answer carries a `Location` header. A blueprint already filed is `200`,
and nothing is written. A list the format sorts that arrives unsorted is refused with status `400`
and the rule `blueprint.unsorted`, and is never sorted for you.

The first answer is `201`:

```json
{
  "id": "98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342"
}
```

`GET /v1/blueprints/{blueprint_id}` reads it back. `POST /v1/bundles` with
`{"blueprint_id": "<id>"}` compiles a filed blueprint with the packages the server loaded, and
answers `201` or `200` with the bundle's `id`, its `manifest`, its `fidelity` and the compile's
`findings`. A blueprint that does not compile is `422` with the rule `bundle.rejected`, and every
fault in `findings`; one never filed is `404`. `GET /v1/bundles/{bundle_id}` reads the manifest, and
`GET /v1/bundles/{bundle_id}/diff/{to_bundle_id}` names the nodes, links and probes a step from one
bundle to the other adds, removes or changes, with nothing built.

`POST /v1/packages:validate` with `{"package": <the package, as JSON>}` holds one platform or probe
package to its schema. A package that fails is not a problem: the answer is `200` and a verdict,
status `rejected`, whose findings say why. `GET /v1/drivers` lists the drivers with the capabilities
each has, and `GET /v1/capacity` reads the room the default driver has now. The reading is
advisory, since a create it seemed to fit can still be refused. A driver that cannot read its
runtime answers `503` with the rule `capacity.unread`.

## A twin: create, step and delete

A twin is written by `PUT /v1/twins/{name}` with its spec. The spec names exactly one of
`blueprint_id` and `bundle_id`, and may name `driver` and set `allow_restart`; a field the document
does not list is refused. The server fills what is absent: the driver it was started with, and
`allow_restart` false. The answer is the twin's record, and the record is the twin: its `spec` is
what you asked for, its `status` is what the loop has done so far, and its `generation` and
`revision` count the writes of each. A new spec queues a run, which the record's status names; the
loop works toward the spec after the call has answered.

`If-None-Match: *` makes the write a create only. The answer to a create is `201`, with `Location`
and `ETag`. If the twin exists, the write is refused with status `412` and the rule `twin.exists`.

```sh
curl -X PUT -H "Authorization: Bearer $FYLGJA_API_TOKEN" -H "Content-Type: application/json" \
  -H "If-None-Match: *" --data '{"spec": {"blueprint_id": "98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342"}}' \
  http://127.0.0.1:7650/v1/twins/demo
```

The answer is `201`:

```json
{
  "record_version": "1",
  "name": "demo",
  "revision": 1,
  "generation": 1,
  "spec": {
    "blueprint_id": "98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342",
    "driver": "containerlab",
    "allow_restart": false
  },
  "status": {
    "observed_generation": 0,
    "conditions": [],
    "nodes": []
  }
}
```

The same request again, with the same header, is refused. The `detail` is for people, and its words
may change; a client reads `rule`:

```sh
curl -X PUT -H "Authorization: Bearer $FYLGJA_API_TOKEN" -H "Content-Type: application/json" \
  -H "If-None-Match: *" --data '{"spec": {"blueprint_id": "98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342"}}' \
  http://127.0.0.1:7650/v1/twins/demo
```

The answer is `412`:

```json
{
  "type": "about:blank",
  "title": "Precondition failed",
  "status": 412,
  "detail": "Twin demo exists, and If-None-Match asks for a create.",
  "instance": "/v1/twins/demo",
  "rule": "twin.exists"
}
```

A write with no `If-None-Match` creates the twin if it is new, and steps it if it exists. A step
writes a new spec: another blueprint, or the same one with `allow_restart` set. Writing the spec the
twin already holds changes nothing, starts no run and answers `200`. A step that would restart or
recreate a node is refused by the loop unless the spec allows a restart, and the run ends
`rejected`; [the dry run](#the-dry-run) says so before the write.

The answer to a read of one twin and the answer to a write by `PUT` carry the record's revision as
the `ETag` header, quoted, such as `"3"`; a dry run and a `DELETE` answer none. A client that reads
a record and then writes sends that header back as `If-Match`, and the write is refused with `412`
and the rule `twin.conflict` if the record has moved since. The same header makes a deletion
conditional.

Other refusals of a write are `409`, for a request the twin's state contradicts: the spec names
another driver than the twin's (`twin.driver.fixed`), the twin is being deleted (`twin.deleting`),
or the twin has diverged and accepts only deletion (`twin.diverged`). A blueprint or bundle that
cannot be compiled or planned is `422`.

`DELETE /v1/twins/{name}` asks for the twin's deletion, cancelling a run in flight first. The
answer is `202` and the record as it stands, with `deletion_requested_at` set. The loop tears the
twin down and then deletes the record, and until then the record stays readable. Asking again
answers the record as it stands.

```sh
curl -X DELETE -H "Authorization: Bearer $FYLGJA_API_TOKEN" -H "If-Match: \"1\"" \
  http://127.0.0.1:7650/v1/twins/demo
```

The answer is `202`:

```json
{
  "record_version": "1",
  "name": "demo",
  "revision": 2,
  "generation": 2,
  "deletion_requested_at": "2026-11-03T10:04:30.000000Z",
  "spec": {
    "blueprint_id": "98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342",
    "driver": "containerlab",
    "allow_restart": false
  },
  "status": {
    "observed_generation": 0,
    "conditions": [],
    "nodes": []
  }
}
```

`POST /v1/twins/{name}/verifications` reads every node of a running twin once and judges it
against the bundle it should hold. It changes nothing and answers `200` with a verdict, status `ok`,
`nonconforming` or `failed`, and counts. A twin with no applied deployment to read is `409` with
the rule `twin.not_running`.

## The dry run

`PUT /v1/twins/{name}?dry_run=true` takes the same body as a write and writes nothing. It compiles
the blueprint, checks that the runtime has room, and plans what the driver would do. The answer is
`200` and a plan: the deployment that applying the spec would make, a verdict, and for a twin that
runs, the `changes` a step would make to each node and link. A step the loop would refuse is not an
error: the plan's verdict is `rejected`, with a finding that says why, such as
`step.restart.required`, and the twin is untouched. A blueprint that does not compile, a bundle the
driver cannot plan and an admission the runtime's room refuses are each `422`, the last with the
rule `admission.capacity`.

On the clabernetes driver, a node the plan answers `recabled` may still be replaced, without
`allow_restart`, if any step since that node was last made has added or removed a node: that can
move its management address, and clabernetes then makes its pod anew when its links change. The
answer stays `recabled`.

## Watching

`GET /v1/twins/{name}` and `GET /v1/twins` answer once. With `?watch=true`, or with the header
`Accept: text/event-stream`, they stream changes as server-sent events instead. `?watch=false`
answers JSON whatever the `Accept` says. Each message names its event `ADDED`, `MODIFIED` or
`DELETED`, and its data line is one JSON object with a `type` and the whole record as `object`.

A watch of one twin first sends the record as it stands, then one message for each write to it, and
ends with `DELETED` once the twin is gone. A twin that does not exist when the watch begins is
`404`. A watch of every twin sends every current record, then each change to any twin, and does
not end. The store keeps no history. A client that lost its connection sends the last revision it
saw as `since_revision`, and is sent the record as it stands, if that is newer, and every later
write.

```sh
curl -N -H "Authorization: Bearer $FYLGJA_API_TOKEN" "http://127.0.0.1:7650/v1/twins/demo?watch=true"
```

```text
event: ADDED
data: {"type":"ADDED","object":{"record_version":"1","name":"demo","revision":1,"generation":1,"spec":{"blueprint_id":"98f106a152ae938acb8cc95dcb73701036a4dd3bb00c99d1322993b324e6b342","driver":"containerlab","allow_restart":false},"status":{"observed_generation":0,"conditions":[],"nodes":[]}}}

```

## Runs and their events

Every change of spec starts a run, and the twin's status names it. `GET /v1/runs` lists runs,
newest first, and `?twin=<name>` keeps one twin's. `GET /v1/runs/{run_id}` reads one: its `state`,
and once it has ended its `verdict`, a findings document. `POST /v1/runs/{run_id}/cancel` asks a run
to cancel and answers `202` with the run in state `cancelling`; read the run to see how it ends. A
run that has ended is `409` with the rule `run.ended`.

A run's events are its steps, each with a `seq`. `GET /v1/runs/{run_id}/events` answers the events
with a `seq` greater than `after`, which is 0 when absent, with `next`, the cursor for the next
read, and `ended`, whether the run has ended, so that no more will follow. A client polls with
`after` set to the last `next` until `ended` is true. The events of a run the store no longer holds
are not replayed.

```sh
curl -H "Authorization: Bearer $FYLGJA_API_TOKEN" \
  "http://127.0.0.1:7650/v1/runs/01JB8Z5Y3V4W6X7Y8Z9A0B1C2D/events?after=0"
```

```json
{
  "events": [
    {
      "seq": 1,
      "at": "2026-11-03T10:00:00.000000Z",
      "phase": "compile",
      "outcome": "started"
    },
    {
      "seq": 2,
      "at": "2026-11-03T10:00:00.000000Z",
      "phase": "compile",
      "outcome": "done",
      "duration_s": 0.25
    }
  ],
  "next": 2,
  "ended": false
}
```

With `Accept: text/event-stream` the same route streams each event as one message, whose `id` is its
`seq` and whose data is the event as JSON. The stream ends when the run does. A client that
reconnects sends `Last-Event-ID`, the header the server-sent events standard names, and the server
resumes after the greater of that and `after`. An `after` or a `Last-Event-ID` that is not an
integer of 0 or more is `400`.

## Problems

A request that is malformed, unauthorised, refused or in conflict with the twin's state is answered
with a problem document, under the media type `application/problem+json`. Its `status` repeats the
HTTP status, its `rule` is a stable id a client matches on, its `detail` is one sentence, and its
`findings`, where a request has several faults, list each with its own rule. A `400` is a request
the server cannot read, a `404` names nothing it holds, a `409` contradicts the state of a twin or
a run, a `412` fails a precondition and a `422` is well-formed but not compilable or plannable.
[The rules page](rules.md) lists each rule id and what it means.

## Parameters

Each query parameter of the API. A boolean is `true` or `false`; an integer is written in decimal.

| Parameter | Taken by | Holds |
|---|---|---|
| `after` | `getRunEvents` | The cursor, an integer of 0 or more: only events with a greater `seq` are answered. Default 0. |
| `dry_run` | `applyTwin` | A boolean. `true` plans the write and writes nothing. Default `false`. |
| `since_revision` | `getTwin`, `listTwins` | An integer of 0 or more, with a watch: only changes after this revision. |
| `twin` | `listRuns` | A twin's name: only that twin's runs. |
| `watch` | `getTwin`, `listTwins` | A boolean. `true` streams changes as server-sent events. Default `false`. |

## Headers

Each header the document gives a request or an answer. `Authorization`, `Accept`, `Content-Type`
and `Last-Event-ID` are the ones HTTP defines, and are described above where a route uses them.

| Header | On | Holds |
|---|---|---|
| `ETag` | The answers of `getTwin` and `applyTwin` | The twin record's revision, quoted. |
| `If-Match` | The requests of `applyTwin` and `deleteTwin` | The revision the client read, quoted: the request is refused with `412` if the record has moved since. |
| `If-None-Match` | The request of `applyTwin` | `*`, to create only: the request is refused with `412` if the twin exists. |
| `Location` | The `201` answers of `putBlueprint`, `buildBundle` and `applyTwin` | The path of the resource the request created. |

Why it is so: [the core's design](../design/core.md).
