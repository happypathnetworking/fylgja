# The client library

The client library is a Python module, `fylgja_core.client`, that makes the calls of API 1 for a
script of your own. `pip install fylgja-core` gives the model and the client and nothing more: the
server, with its dependencies, is the extra `fylgja-core[server]`
([the server page](server.md)). `fylgja-core`, the command ([the command page](cli.md)), is written
against this module, and every call it makes is one of the calls below.
[What 1.0 holds](compatibility.md) says which of the module's names are held across the releases of
major version 1, and that the client passes over a member of an answer it does not know.

The client is synchronous. It reaches the server over HTTP alone and holds none of the server's
rules: a refusal is the server's, raised as it came. Its calls answer the API's documents as the
JSON values they are, dictionaries and lists, so a field is read by its name as
[the API page](api.md) and [`formats/api-1.openapi.yaml`](../formats/api-1.openapi.yaml) give it.

This script files the three-node blueprint of the repository's tree, run from a clone, creates a
twin of it and waits for the run to end. The address and the token come from the environment, as
`fylgja-core` takes them.

```python
import json
import os
from pathlib import Path

from fylgja_core.client import Client

blueprint = json.loads(Path("testdata/blueprint/three-node.json").read_text())
with Client(os.environ["FYLGJA_API_ADDRESS"], os.environ["FYLGJA_API_TOKEN"]) as client:
    blueprint_id = client.put_blueprint(blueprint)
    record, etag = client.apply_twin("demo", {"blueprint_id": blueprint_id}, if_none_match="*")
    followed = client.follow(record, ("create",))
    print(followed.run["verdict"]["status"])
```

A `Client` is a context manager: leaving the block closes its connections, and `close` does the
same where a block does not fit. Before its first call the client reads the server's version and
raises `UnsupportedVersion` if the server speaks another API than API 1. The address is `host:port`
or an `http://` or `https://` URL, and the token is the one whose hash the server's token file
holds ([the token file](server.md#the-token-file)). The client sends the token in the
`Authorization` header and nowhere else. No error, `repr` or log line of the client holds it.

## Calls

A call that takes a twin's name, a run's id or a bundle's id raises `ProblemError` where the server
refuses it. Each call below is `Client`'s method of that name, and the table gives its signature as
the code has it, then the route it requests and what it answers. A parameter after the bare `*` is
given by keyword.

| Call | Route and answer |
|---|---|
| `Client(address, token, *, ca=None, …)` | Opens the client; it makes no request. `ca` is [described below](#tls). `transport` and `sleep` are for the library's own tests and a script leaves them alone. `notice` is a function of one string that is called once when a watch begins to reconnect, as [the watches](#watches-and-reconnecting) say. |
| `close()` | Closes the client's connections. |
| `version()` | `GET /v1/version`. The versions document. `UnsupportedVersion` where `api` is not `"1"`. |
| `put_blueprint(doc)` | `POST /v1/blueprints`. The blueprint's id, a string. |
| `get_blueprint(blueprint_id)` | `GET /v1/blueprints/{blueprint_id}`. The filed blueprint. |
| `build_bundle(blueprint_id)` | `POST /v1/bundles`. The bundle's `id`, `manifest`, `fidelity` and `findings`. |
| `get_bundle(bundle_id)` | `GET /v1/bundles/{bundle_id}`. The bundle's `id` and `manifest`. |
| `diff_bundles(from_id, to_id)` | `GET /v1/bundles/{from_id}/diff/{to_id}`. What a step from the first bundle to the second changes. |
| `list_drivers()` | `GET /v1/drivers`. A list of the drivers, sorted by name. |
| `capacity()` | `GET /v1/capacity`. The default driver's reading of its runtime's room. |
| `list_twins()` | `GET /v1/twins`. A list of the twins' records, sorted by name. |
| `get_twin(name)` | `GET /v1/twins/{name}`. A pair: the twin's record and its `ETag`, to give back as `if_match`. |
| `apply_twin(name, spec, *, if_match=None, if_none_match=None, dry_run=False)` | `PUT /v1/twins/{name}` with `{"spec": spec}`. A pair: the record and its `ETag`. `if_match` and `if_none_match` are the headers of those names, `"*"` among the values they take. With `dry_run` the server writes nothing, and the pair is the plan and `None`. |
| `delete_twin(name, *, if_match=None)` | `DELETE /v1/twins/{name}`. The record, with its deletion requested. |
| `watch_twin(name, since_revision=None)` | `GET /v1/twins/{name}?watch=true`. An iterator of the twin's watch events, which ends after `DELETED`. With `since_revision` it begins after that revision. |
| `verify_twin(name)` | `POST /v1/twins/{name}/verifications`. The findings document, the verdict. |
| `follow(record, operations, *, progress=None)` | No route of its own: it watches a twin and reads a run. A `Followed`, [below](#following-a-write). |
| `list_runs(twin=None)` | `GET /v1/runs`, with `?twin=` when given. A list of runs, newest first. |
| `get_run(run_id)` | `GET /v1/runs/{run_id}`. The run, with its verdict once it has ended. |
| `run_events(run_id, after=0, *, timeout=None)` | `GET /v1/runs/{run_id}/events?after=`. One page of the run's events. `timeout` is an `httpx.Timeout` for this call in place of the client's. |
| `watch_run(run_id, after=0)` | `GET /v1/runs/{run_id}/events` as a stream. An iterator of the run's events after `after`, which ends when the run has. |
| `cancel_run(run_id)` | `POST /v1/runs/{run_id}/cancel`. The run, cancelling. |

A call's errors are those of [the table below](#errors). `get_twin` and `apply_twin` give the
`ETag` of the revision they read or wrote, so a script can write only a twin it has seen
(`if_match`) or only a twin that does not exist (`if_none_match="*"`), and the server refuses a
write that meets another. `verify_twin` reads every node once and can take longer than another
call, and the client allows it a long read timeout.

## Following a write

`follow` waits for a write of a twin's spec to take effect. Give it the record `apply_twin` or
`delete_twin` answered and the operations of the run the write may have started: `("create",)` for
a twin made, `("step", "create")` for one stepped, since a twin whose create never applied runs its
create again, and `("destroy",)` for a deletion. It watches the twin until the server's loop has
acted on the record's generation or the twin is gone, then finds the run, follows it to its end and
reads it. It answers a `Followed`, whose fields are:

- `record`: the last record of the twin it saw.
- `run`: the run the write started, ended, with its `verdict`.
- `gone`: whether the twin no longer exists.

A record whose generation the loop has acted on already is answered at once, with no watch, and
its run is the one the record names, or else the twin's newest of those operations. A script that
must know whether its write started a run compares the record's `generation` with its `status`'s
`observed_generation` before it calls `follow`.

`progress`, when given, is a function of one string. It is called with `"<twin>: <phase>"` each
time the phase of the twin's run moves. It is called at no other time, and it is not a deadline: a
twin that stands still, or a server that keeps a watch open and reports nothing, calls it never.
What `progress` raises is not caught: it leaves `follow` as it was raised and ends the wait.

`follow` takes no timeout and nothing inside it bounds the wait. A script that needs a bound sets
it from outside the call: a time limit on the process or the worker that runs it, or an interrupt.
It raises `FollowError` where the twin's watch ends before the loop has acted, where the twin has
no run of the operations given, and where the run has ended with no verdict.

## Watches and reconnecting

`watch_twin` and `watch_run` read a stream, and each event arrives once. A watch outlives a restart
of the server. Where its stream ends before its proper end, is cut off, or is answered with a
proxy's `5xx` while the server is away, the client opens the watch again after the last revision or
event it saw, which the server resumes from. The waits between tries grow. The watch is opened again
after each of a bounded number of early ends in a row with no event between them, about three
minutes in all; the next raises `TransportError`. The first early end of a run of them is told to
`notice`, if the client has one.

A refusal, an answer that is no event stream, an event the client cannot read, a certificate it
does not trust and a `4xx` answer with no problem document end a watch at once. A twin's watch ends
after the event `DELETED`; a run's ends once the server says the run has.

## Errors

| Error | Raised when |
|---|---|
| `ProblemError` | The server refused a request with a problem document. `status` is the HTTP status. `problem` is the problem document, not a dictionary, read by attribute: `rule` names the rule the request broke, and `title`, `status` and `detail` say the rest. |
| `TransportError` | The request did not reach the server, or the answer is no API 1 document: a connection that failed or timed out, an answer that is no JSON object, a watch that gave up reconnecting. |
| `Untrusted` | A kind of `TransportError`: the server's certificate failed verification against the client's trust. |
| `FollowError` | `follow` could not bring a write to a verdict, as [above](#following-a-write). |
| `UnsupportedVersion` | The server speaks another API than API 1. A `ValueError`. |
| `InvalidAddress` | The address is no server's: it is not an `http://` or `https://` URL or `host:port`, or it holds a login. A `ValueError`. |
| `InvalidToken` | The token is no bearer token: letters, digits and `-._~+/` with trailing `=`. A `ValueError`. |
| `InvalidCA` | The CA file cannot be read as CA certificates. A `ValueError`. |

All of them are importable from `fylgja_core.client`. `InvalidAddress`, `InvalidToken` and
`InvalidCA` are raised by `Client(...)` before any request, and their messages say what is wrong
and never repeat the address, the token or the path. `TransportError` is also what a call raises
where the server's answer is an HTTP error that carries no problem document.

A document that the model refuses is another error: `fylgja_core.documents.Rejected`, raised by
the model's readers of documents and not by the client. Its `problems` lists every fault found in
one pass, each with a `pointer`, a `rule` and a `detail`.

## TLS

An `https://` address is verified against the CA certificates in the file `ca` names, given as a
`Path`: `Client(address, token, ca=Path("ca.pem"))`. With no `ca` it is verified against the
system's trust, which a site can add its own CA to. The certificate must name the server's
address, as [the server page](server.md#tls) describes. A file that cannot be read as CA
certificates raises `InvalidCA`, and a certificate that fails verification raises `Untrusted`.
