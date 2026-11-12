# fylgja-infrahub

The Infrahub reader: a typed, read-only library and a command, `fylgja-infrahub`, that read a
branch of Infrahub, at a time and under a scope, by one documented mapping of the OpsMill schema
library's DCIM, into a blueprint 1 with its source envelope, or the findings that refused it
([D-082](../../design/decisions.md#d-082), [D-083](../../design/decisions.md#d-083)). Its mapping
is in [mapping.md](mapping.md), and its rules are in [rules.md](rules.md).

## What it is, and what it is not

It is held to what a production workflow needs ([D-081](../../design/decisions.md#d-081)): it
must not hand over a blueprint that is quietly not the network, it installs into a platform it
does not own, and an Infrahub upgrade is a procedure, below, not a rewrite.

- **It gives a blueprint or the faults, and never guesses.** Every list is counted against the
  total Infrahub answers for it. Every scoped device has its configuration artifact, `Ready`,
  holding the bytes its checksum names, and generated no earlier than the latest write to the
  intent it renders. Every fault is filed in one pass, and a read with an error gives no
  blueprint. What the blueprint can bear without a fault is a fidelity row in its envelope: a
  cable it cannot make a link of, a device renamed to a label. The same read gives the same
  blueprint id.
- **It is read-only.** It sends no mutation (below).
- **It knows no stage, proposed change, twin or workflow engine.** Which branch and which time
  to read, and what is done with the blueprint, are its caller's: the core's client files it,
  and the example orchestrator under `orchestrator/` is one such caller.
- **It has one mapping, and it is not a user's to change.** It reads the DCIM library at the
  commit `schema.COMMIT` names, and a branch whose schema differs from the mapping's table is
  refused before anything of the network is read. What the schema cannot hold, the platform
  package of a pair of manufacturer and platform, the artifact that holds a device's
  configuration and whether probes are read, is the reader document's
  ([`infrahub-reader-1.schema.json`](../../formats/infrahub-reader-1.schema.json)).
- **It speaks plain HTTP**, through httpx and no SDK, from one module, `transport.py`, with every
  GraphQL document a file under `src/fylgja_infrahub/queries/`. It imports nothing of the example
  orchestrator, Prefect, Infrahub's SDK or the core's `server` extra, which a test over its
  imports holds.

## Installing it

It needs Python 3.14, `fylgja-core`'s base install, the model package and the client library
([D-084](../../design/decisions.md#d-084)), and httpx at the core's range; never the core's
`server` extra. Nothing is published: each wheel is built from this repository, the reader's
from `readers/infrahub/` with `formats/` beside it, since its `setup.py` copies the reader's
format into the wheel, and the core's from `core/`. Install the two together into the
platform's environment. In the tree, `make venv` installs it editable into `core/.venv`, with
its console script `core/.venv/bin/fylgja-infrahub`.

The kind `FylgjaProbe`, [`schema/fylgja-probe.yml`](schema/fylgja-probe.yml), is loaded into
Infrahub by whoever runs it, and only a reader document that asks for probes needs it
([mapping.md](mapping.md), "The probes"); `make infrahub-seed` loads it on the development
Infrahub's `main`. The wheel does not carry it.

## The library

```python
import os
from pathlib import Path

from fylgja_infrahub import connect, document, head, read

reading = document.load(Path("reader.yaml"))  # documents.Rejected, every problem, where it is refused
address, token = os.environ["FYLGJA_INFRAHUB_ADDRESS"], os.environ["FYLGJA_INFRAHUB_TOKEN"]
with connect(address, token) as conn:  # ca=Path(...) for an https:// address a private CA signed
    at = head(conn, branch="main", scope="tag:fylgja")
    result = read(conn, branch="main", at=at, scope="tag:fylgja", document=reading)
```

- `connect(address, token, *, ca=None)`: the `Infrahub` at `address`, an `http(s)://` URL or
  `host:port`, a context manager and the source every call reads through. It reads Infrahub's
  version first; a version not in `SUPPORTED` is the warning `infrahub.version.unverified`,
  carried on every result of the connection and logged once (logger `fylgja.infrahub`). An
  `https://` address is verified against the CA file `ca`, or the system's trust where it is
  None. `InvalidAddress`, `InvalidToken` and `InvalidCA` (`fylgja_core.client`) are raised
  before any request.
- `read(conn, *, branch, at, scope, document, generated_since=None)`: a `Result` of the
  blueprint, None exactly when a finding is an error; every finding, in a result's order
  (`fylgja_core.findings.order`); and `empty`, whether the scope selected no device. `at` is sent
  to Infrahub as given, and `scope` is `tag:<name>`. `generated_since` is a time at which a
  regeneration of the configurations is known to have completed, for a regeneration that stored
  the same bytes and so moved no checksum's stamp (`artifact.stale` in [rules.md](rules.md)).
- `head(conn, *, branch, scope)`: the first instant after the branch's latest write under the
  scope, the time a read of the branch as it stands is pinned at; `Refused`, with its findings,
  where it cannot answer one.
- `check_schema(conn, *, branch)`: every way the branch's schema differs from the mapping's
  table, the connection's warning among them.
- `document.load(path)`: a `ReaderDocument` from a YAML or JSON file, or the core's
  `documents.Rejected` naming the file, with every problem.
- `InfrahubError`: Infrahub refused a request, answered what is no answer, or was not reached.
  Its text names what was being read, the branch and the time; its `status` is the HTTP status
  Infrahub answered, the one a GraphQL error carries under 200, or None where it was not reached.

No finding, error, log line or blueprint holds the token, and no finding a byte of a
configuration. The library logs under `fylgja.infrahub`, the version warning alone, and gives that
logger a `NullHandler`, so an integrator who wants the log attaches a handler of their own.

## The command

`fylgja-infrahub` makes the same calls from a shell. Infrahub's address, the token and the CA
are `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_TOKEN` and `FYLGJA_INFRAHUB_CA` alone, never a
flag ([D-042](../../design/decisions.md#d-042)); the CA may be left unset, an `https://`
address then verified against the system's trust.

```sh
fylgja-infrahub read --branch B --scope tag:N --reader FILE --out FILE [--at T] [--generated-since T]
fylgja-infrahub head --branch B --scope tag:N
fylgja-infrahub schema-check --branch B
```

- `read` writes the blueprint to `--out` as JSON, whole or not at all and readable by its owner
  alone, and prints `<blueprint id> <n> devices, <n> links, <n> probes`. Without `--at` it reads
  at `head`'s answer, and says which time on stderr.
- `head` prints the time.
- `schema-check` prints `ok: opsmill/schema-library@<commit>`.

Each finding is one line on stderr, `<severity> <rule> <object>: <message>`, in a result's order.
A blueprint holds every device's configuration, so it is written to `--out` and never printed,
and nothing the command prints holds the token. Its exit status:

| Status | Means |
|---|---|
| 0 | No finding is an error: the blueprint written, the time or `ok` printed, and any warning or `info` finding printed beside |
| 1 | A finding is an error, a refusal of `head`'s among them: `--out` is not written, and a file already there is left as it was |
| 2 | A failure of the command's own: its arguments refused; a variable not set, or one the client's rules refuse, named with the rule and never its value; a reader document refused, with its problems, or not read; an `InfrahubError`; or `--out` not written |

## Supported Infrahub versions

The versions of Infrahub the reader's contract tier passed on, `SUPPORTED` in `transport.py`,
each with the date it passed. On any other the reader still reads, and every result carries the
warning `infrahub.version.unverified`.

| Infrahub | Passed on |
|---|---|
| 1.11.11 | 2026-11-10 |

## Upgrading Infrahub

An upgrade is a procedure, not a rewrite ([D-083](../../design/decisions.md#d-083)): the reader
is verified on the new version before `SUPPORTED` names it.

1. **The development Infrahub at the new version**, on new volumes: `make infrahub-down PURGE=1`
   first where one runs, since a version started on the volumes another made has not been read.
   Then, from the repository's root
   ([CONTRIBUTING.md](../../CONTRIBUTING.md#the-development-infrahub)):

   ```sh
   make infrahub-up INFRAHUB_VERSION=<v>
   set -a; . local/.env; set +a
   make infrahub-register
   make infrahub-seed
   make contract
   ```

2. **Each recorded fact the code leans on, read again** on the new version, and recorded under a
   section of its own in [verified-facts.md](../../design/verified-facts.md), dated, saying only
   what the run showed. The table below names each by its bullet under "Infrahub 1.11.11". A
   fact that reads otherwise changes the code, and the decision behind it where it changes one,
   before the version is named.
3. **`SUPPORTED` and the table of versions above extended in one commit**, with the date the
   contract tier passed.

| The code | Leans on | Its bullets under "Infrahub 1.11.11" |
|---|---|---|
| `connect` | `GET /api/info` answers the version, and refuses a wrong token with 401 before any query | **Its version.**; **`/api/info` refuses a wrong token.** |
| The transport's requests | `POST /graphql/<branch>` with `X-INFRAHUB-KEY`, a branch not there 404; `?at=` honoured, a malformed one 400 and one before the branch 422 | **GraphQL over plain HTTP.**; **`at` is honoured.** |
| `InfrahubError` | How a refusal is shaped, and the status a query refused under HTTP 200 carries at `extensions.http_status` | **How a refusal is shaped.**; **A query refused under HTTP 200 carries its status in each error.** |
| The pager, and `read.incomplete` | A list's `count` is its filtered total whatever its `limit` and `offset`; a nested list selected with no `limit` is answered whole | **A list answers `count` beside `edges`**; **A nested list is answered whole, with no limit.** |
| `KEEPALIVE_S` | The server closes a connection idle for 2 s | **A read 2 s after the last could go unanswered; the server's files give it a keep-alive of 2 s.** |
| `times` | Infrahub cuts an `at` past the microsecond; the layouts it writes times in, each answered when sent back as `at` | **An `at` past the microsecond is cut to it.**; **The times' layouts.** |
| The schema check | `GET /api/schema?branch=`: the hash under `main` beside the nodes and generics, an `at` changing nothing; each entry's fields; the table's kinds and fields as `main` answers them; no commit and no file's hash told; a pinned query checked against the branch's present schema | **The schema over REST.**; **The schema's entries.**; **The table's kinds on `main`.**; **Of the table's eight attributes**; **The generics' own fields.**; **A kind's hash is not its file's.**; **Nothing answers where a schema came from.**; **A pinned query is checked against the branch's present schema.** |
| A device's configuration | Its artifacts read through the device; `Pending` with no checksum and no storage id while generated, `Ready` throughout a rewrite; the stored bytes served with no branch, their MD5 the checksum; a read at a past time listing the artifact as it stood, its storage id still serving those bytes | **An artifact through its device.**; **A generation is answered before anything is rendered.**; **A generation rewrites in place, `Ready` throughout.**; **The stored bytes, with a token and without.**; **The stored bytes are the checksum's, and the template renders the fixture.**; **An artifact at a past time.** |
| The stale rule | Nothing regenerated unasked; which stamps each write moves and which events it logs; the task workers' account, told by its name alone; the branch's events, 50 a page; an uncabled port's connector stamp null; the addresses under `InterfaceLayer3`; a far port renamed; a device made on the platform naming it among its event's related nodes and moving its node stamp, not its name's; a cable's ends taken off it shown by its event alone | **Nothing was generated unasked.**; **What a stale rule can be built on**, and each bullet it cites; **The branch's events.**; **An uncabled port's `connector { node_metadata }` reads null.**; **An address on a virtual interface, read under `InterfaceLayer3`.**; **A port renamed, nothing regenerated.**; **A device made on the scope's platform.**; **The platform's node stamp moves with a device made on it.**; **The same cable's ends removed instead.** |
| `head` | No field holds a branch's latest write: it is the later of the newest stamp and the newest event, and a read a microsecond after it answers the branch as it stands; `Branch(name:)` answers `branched_from`; on a branch not yet written, a time before it, at which a pinned read is answered whole | **No latest write in what was read of a branch.**; **The newest stamp, the newest event, and the pin after both.**; **Pinned at a write's stamp.**; **`Branch(name:)`**; **`head` of a branch not yet written.** |
| The probes | The kind as loaded, `format` reading optional; a probe of the branch-agnostic kind read through a branch at a time as it stood then, its stamp too, and one deleted since | **The kind loaded on `main`.**; **A probe of the branch-agnostic kind, at a time.**; **The edge's stamp at a pin.**; **Pinned at the create's own stamp.**; **A probe deleted.** |

## What it sends, and what its token must read

The reader sends no mutation. Its token must be allowed to read, on each branch read:

- Infrahub's version, `GET /api/info`;
- the branch's schema, `GET /api/schema?branch=<branch>`;
- through `POST /graphql/<branch>`, queries alone: `DcimDevice` by its tag, with its platform, a
  `DcimPlatform`, and the platform's `OrganizationManufacturer`, its interfaces of either kind
  and their `IpamIPAddress` objects, and its artifacts, each a `CoreArtifact` with its
  definition, the definition's transformation and the transformation's query; each
  `InterfacePhysical` of those devices, with its connector and the connector's ends; the
  internal `CoreGraphQLQueryGroup` objects of those queries, with the account that made each;
  `InfrahubEvent`, the branch's event log; `Branch`; and `FylgjaProbe`, where the branch has the
  kind;
- each configuration's stored content, `GET /api/storage/object/<storage_id>`.

A read's events run from the oldest checksum stamp among the scoped devices, or `generated_since`
where later, to the present, 50 a page: every event of the branch's log in that time and, for a
branch but `main`, of `main`'s, whatever the scope ([mapping.md](mapping.md), "The stale rule").

The development Infrahub gives the reader the admin's token ([`.env.example`](../../.env.example));
which role of Infrahub's grants these reads and no more has not been read.
