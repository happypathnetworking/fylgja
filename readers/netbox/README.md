# fylgja-netbox

The NetBox reader: a typed, read-only library, `fylgja_netbox`, and a command, `fylgja-netbox`,
that read a branch of NetBox's branching plugin as it stands, or `main`, under a scope, by one
documented mapping of NetBox's own DCIM, into a blueprint 1 with its source envelope, or the
findings that refused it ([D-095](../../design/decisions.md#d-095),
[D-096](../../design/decisions.md#d-096)). Each device's configuration is what NetBox renders for
it at the read. Its mapping is in [mapping.md](mapping.md), and its rules are in
[rules.md](rules.md).

## What it is, and what it is not

It is held to what a production workflow needs ([D-081](../../design/decisions.md#d-081)): it
must not hand over a blueprint that is quietly not the network, it installs into a platform it
does not own, and a NetBox upgrade is a procedure, below, not a rewrite.

- **It gives a blueprint or the faults, and never guesses.** Every list is held to the `count`
  NetBox answers for it, and every row to what was asked. Every scoped device is rendered, and a
  device with no template, a template that fails and an empty render are each an error naming the
  device. Every fault is filed in one pass, and a read with an error gives no blueprint. What the
  blueprint can bear without a fault is a fidelity row in its envelope: a cable it cannot make a
  link of, a device renamed to a label, a probe outside the scope. The same state read twice
  gives the same blueprint id.
- **A read is of one state, or refused.** NetBox reads no earlier time, so the reader takes no
  time: it reads the branch as it stands, and brackets the read by the changelog it reads from,
  `main`'s or the branch's, marked before the first list and again after the last render, the
  branch read again then. A read the changelog or the branch moved under is refused,
  `read.moved`, and the remedy is to read again ([mapping.md](mapping.md), "The bracket").
- **It has no stale rule.** NetBox stores no configuration: it renders a device's template at the
  request, so no configuration is older than the intent it is read with, and the Infrahub
  reader's stale rule has no counterpart here.
- **It is read-only.** Its one request that is no `GET` is the render (below), which writes
  nothing.
- **It knows no stage, mark, tag, journal entry, twin or workflow engine.** Which branch to read,
  and what is done with the blueprint, are its caller's: the core's client files it, and the
  example orchestrator under `orchestrator/` is one such caller.
- **It has one mapping, and it is not a user's to change.** What NetBox cannot hold, the platform
  package of a pair of manufacturer and platform and the configuration context that declares the
  probes, is the reader document's
  ([`netbox-reader-1.schema.json`](../../formats/netbox-reader-1.schema.json)).
- **It speaks plain HTTP**, through httpx and no client library of NetBox's, from one module,
  `transport.py`. It imports nothing of the Infrahub reader, the example orchestrator, Prefect,
  pynetbox or the core's `server` extra, which a test over its imports holds.

## Installing it

It needs Python 3.14, `fylgja-core`'s base install, the model package and the client library
([D-084](../../design/decisions.md#d-084)), and httpx at the core's range; never the core's
`server` extra. Nothing is published: each wheel is built from this repository, the reader's
from `readers/netbox/` with `formats/` beside it, since its `setup.py` copies the reader's
format into the wheel, and the core's from `core/`. Install the two together into the
platform's environment. In the tree, `make venv` installs it editable into `core/.venv`, with
its console script `core/.venv/bin/fylgja-netbox`.

NetBox needs the branching plugin to hold a branch, and no schema or plugin of Fylgja's. The
probes are the data of a configuration context, inactive so that no device's rendered context
takes it, which whoever runs NetBox makes, and only a reader document that names it needs it
([mapping.md](mapping.md)); `make netbox-seed` makes `fylgja-probes` on the development
NetBox's `main`.

## The library

```python
import os
from pathlib import Path

from fylgja_netbox import connect, read
from fylgja_netbox.document import load

reading = load(Path("reader.yaml"))  # documents.Rejected, every problem, where it is refused
address, token = os.environ["FYLGJA_NETBOX_ADDRESS"], os.environ["FYLGJA_NETBOX_TOKEN"]
with connect(address, token) as conn:  # ca=Path(...) for an https:// address a private CA signed
    result = read(conn, branch="b", scope="tag:fylgja", document=reading)  # branch=None reads main
```

- `connect(address, token, *, ca=None)`: the `NetBox` at `address`, an `http(s)://` URL or
  `host:port`, a context manager and the source every call reads through. It reads NetBox's
  version and the branching plugin's first, `GET /api/status/`; a pair not in `SUPPORTED` is the
  warning `netbox.version.unverified`, carried on every result of the connection and logged
  once (logger `fylgja.netbox`). An `https://` address is verified against the CA file `ca`, or
  the system's trust where it is None. `InvalidAddress`, `InvalidToken` and `InvalidCA`
  (`fylgja_core.client`) are raised before any request.
- `read(conn, *, branch, scope, document)`: a `Result` of the blueprint, None exactly when a
  finding is an error; every finding, in a result's order (`fylgja_core.findings.order`); and
  `empty`, whether the scope selected no device. `branch` is the branch's name, None for `main`,
  and `scope` is `tag:<name>`. An empty `branch`, or one of whitespace alone, is a
  `ValueError`, raised before any request, as `check` raises it too.
- `check(conn, *, branch)`: the connection's version warning, where it has one, and for a branch
  whether NetBox names the plugin and holds the branch `ready`; for `main` nothing is sent.
- `document.load(path)`: a `ReaderDocument` from a YAML or JSON file, or the core's
  `documents.Rejected` naming the file, with every problem.
- `Source`: every call a read makes of NetBox, which `NetBox` is, so a read runs alike against
  NetBox and against rows built in a test.
- `NetBoxError`: NetBox refused a request, answered what is no answer, or was not reached. Its
  text names what was being read and the branch, or `main`; its `status` is the HTTP status
  NetBox answered, 200 for an answer that is no answer to what was asked, and None where NetBox
  was not reached. A 400 to a list past the bracket's open is weighed at the close before it is
  raised, since NetBox answers 400 to a list by an id it no longer holds and to a request under
  the header of a branch it no longer holds: where the changelog or the branch moved, the read is
  refused by `read.moved` instead, and where the close could not list the changelog whole, by
  `read.incomplete`, quoting the 400's words. A 400 to the close's own requests under a branch's
  header is `read.moved` too, quoting NetBox's words: NetBox answers every request under the
  header of a branch deleted, syncing or merged so. A render's 400 is never raised: it is a finding
  filed for its device, `render.template.missing` in NetBox's no-template words, and otherwise
  `render.unavailable`, which gives way to `read.moved` where the close finds it. A name that
  answers two rows, a tag's, a branch's or a context's, is a `NetBoxError`, since which of them a
  read would take cannot be told.
- `redact(text, token)`: `text` with the token, and each half of a v2 token long enough not to
  match ordinary words, replaced, as the reader hides it in every text it raises: for a program
  that sends requests of its own to NetBox beside the reader's, as the example does.

No finding, error, log line, `repr` or blueprint holds the token, and no finding a byte of a
configuration. The library logs under `fylgja.netbox`, the version warning alone, and gives that
logger a `NullHandler`, so an integrator who wants the log attaches a handler of their own.

## The command

`fylgja-netbox` makes the same calls from a shell. NetBox's address, the token and the CA are
`FYLGJA_NETBOX_ADDRESS`, `FYLGJA_NETBOX_TOKEN` and `FYLGJA_NETBOX_CA` alone, never a flag
([D-042](../../design/decisions.md#d-042)); the CA may be left unset, an `https://` address then
verified against the system's trust. The reader document's path and `--out`'s are taken as
given, a relative one from the working directory, and `--out` names a file.

```sh
fylgja-netbox read [--branch B] --scope tag:N --reader FILE --out FILE
fylgja-netbox check [--branch B]
```

- `read` reads the branch `B`, or `main` where `--branch` is not given, writes the blueprint to
  `--out` as JSON, whole or not at all and readable by its owner alone, and prints
  `<blueprint id> <n> devices, <n> links, <n> probes`.
- `check` prints `ok: NetBox <version>, netbox-branching <version, or none>`, and for a branch
  `, branch B ready`. For `main` it sends nothing beyond `connect`'s `GET /api/status/`, which a
  token of no grant may read, so it checks none of the grants below.

Each finding is one line on stderr, `<severity> <rule> <object>: <message>`, in a result's order.
A blueprint holds every device's configuration, so it is written to `--out` and never printed,
and nothing the command prints holds the token. Its exit status:

| Status | Means |
|---|---|
| 0 | No finding is an error: the blueprint written, or `ok` printed, and any warning or `info` finding printed beside |
| 1 | A finding is an error, `read.moved` among them: `--out` is not written, and a file already there is left as it was |
| 2 | A failure of the command's own: its arguments refused; a variable not set, or one the client's rules refuse, named with the rule and never its value; a reader document refused, with its problems, or not read; a `NetBoxError`; or `--out` not written |

## Supported NetBox versions

The pairs of NetBox's version and the branching plugin's the reader's contract tier passed on,
`SUPPORTED` in `transport.py`, each with the date the tier passed whole on it. On any other pair
the reader still reads, and every result carries the warning `netbox.version.unverified`. A
NetBox with no branching plugin was not read: on one, `main` is read with that warning, and a
branch is refused, `branch.unsupported`.

The tier (`readers/netbox/tests/contract/`) provokes each rule of [rules.md](rules.md) on the
development NetBox, writing under the headers of branches it makes and deletes, but for three
tests whose tag of the tier's naming reaches `main`, made there in two and merged there in the
third, and two that write a journal entry on the test's branch object, which `main` holds; each is
deleted in a `finally`, and nothing the seed's `differences` reads is touched. What cannot be
written into NetBox is provoked in flight, an answer altered on its way to the reader: a NetBox
naming no branching plugin (`branch.unsupported`, `netbox.version.unverified`), a list answered
short of its `count` (`read.incomplete`), and a render answered 502 (`render.unavailable`) or in
another content type than `text/plain` (`render.invalid`); and an edit, a journal entry, the
branch's delete and its sync are made in flight too, as a read's first render passes, so that
they land inside the read (`read.moved`, and nothing refused by the entry).

The pure tier alone holds the reader document's problems, which no request reads; a cable with no
B side, which NetBox refuses to make; and the forms of a rule NetBox cannot be made to answer, or
that the tier does not provoke: a list holding one object twice, lacking an id it was asked for,
or answered longer than its `count`, and the branches' list short of its `count` at the open or
the close (`read.incomplete`); a 400 to the close's own requests under a branch's header, a row
committed late below the open's id, which the count at the close finds, and rows listed above
the open's id among which is no row of the close's id (`read.moved`); two devices of one exact
name (`device.name.duplicate`); a label empty or longer than 63 characters
(`device.name.unmappable`); an end on a virtual, bridge or LAG interface
(`omit.cable.outside_scope`); bytes that are no UTF-8 text (`render.invalid`); and a render's 404,
and its 400 in other words than the no-template answer's (`render.unavailable`).

| NetBox | netbox-branching | Passed on |
|---|---|---|
| 4.7.5 | 1.2.3 | 2026-11-12 |

## Upgrading NetBox

An upgrade is a procedure, not a rewrite ([D-096](../../design/decisions.md#d-096)): the reader
is verified on the new pair before `SUPPORTED` names it.

1. **The development NetBox at the new versions**, on new volumes: `make netbox-down PURGE=1`
   first where one runs, so that the new versions make the database themselves, from empty
   volumes, and the seed and the contract tier read a NetBox that holds nothing an earlier
   version wrote.
   Then, from the repository's root
   ([CONTRIBUTING.md](../../CONTRIBUTING.md#the-development-netbox)), with
   `NETBOX_DOCKER_VERSION=<v>` beside the two where the new NetBox is another release of
   netbox-docker's. `local/.env` is loaded after `make netbox-up` and again after
   `make netbox-seed`: the purge made the three tokens it holds dead, and the first replaces the
   superuser's line, the second the two accounts'.

   ```sh
   make netbox-up NETBOX_VERSION=<v> NETBOX_BRANCHING_VERSION=<v>
   set -a; . local/.env; set +a
   make netbox-seed
   set -a; . local/.env; set +a
   make contract-netbox
   ```

2. **Each recorded fact the code leans on, read again** on the new pair, and recorded under a
   section of its own in [verified-facts.md](../../design/verified-facts.md), dated, saying only
   what the run showed. The table below names each by its bullet under "NetBox 4.7.5 with
   netbox-branching 1.2.3". A fact that reads otherwise changes the code, and the decision behind
   it where it changes one, before the pair is named.
3. **`SUPPORTED` and the table of versions above extended in one commit**, with the date the
   contract tier passed whole, every test passed and none skipped: outside `CI` a test the tier
   cannot connect for, a dead token after the purge say, is skipped, and `make contract-netbox`
   still exits 0.

| The code | Leans on | Its bullets under "NetBox 4.7.5 with netbox-branching 1.2.3" |
|---|---|---|
| `connect` | `GET /api/status/` names `netbox-version` and the plugin's among `plugins`; a v2 token is taken as `Authorization: Bearer nbt_<key>.<token>`, its key 12 characters and its token 40, and one NetBox never made is 403 | **`/api/status/`**; **`/api/status/` with the token**; **Provisioning answers the token once.**; **The refusals.** |
| The pager, and `read.incomplete` | A list answers `count` beside `results`, and `limit` and `offset` page it; a page of 100 was answered whole, read under a branch's header in both readings | **A REST list answers `count`, `next`, `previous` and `results`**; **A page of 100 is answered whole.**; **A page of 100 under a branch's header.** |
| Every row held to what was asked | A parameter NetBox does not know answers the whole list; each one the reader sends is honoured: `?name=` exact and case-sensitive, `?tag_id=`, and `?id=` and `?device_id=` given more than once | **A parameter NetBox does not know is ignored**; **`?name=` on tags and on configuration contexts is exact and case-sensitive**; **`plugins/branching/branches/?name=` answered the branch of that name alone.**; **`?tag_id=` on devices is honoured**; **`?id=` given twice answers the two objects**; **`?device_id=` given twice on interfaces answers both devices' ports** |
| The rows (`transport.py`) | The members of each list's rows, the reader's token reading them: a device's `name` null where it has none, a platform's `manufacturer` null where it has none and no member naming a version, an interface's `type` by its `value`, a cable's `label` `""` where none was given and its sides as `object_type` and `object_id` | **The rows of those lists.**; **A branch listed by its name**; **A cable's representation**; **A device made with no name**; **A platform made with no manufacturer**; **An interface's `type`**; **`dcim/interfaces/?device_id=` answers each type's value** |
| The mapping's omissions (`mapping.py`) | A cable can end on a front port, and a side can hold two interfaces | **A cable from an interface to a front port was taken** |
| A branch | `schema_id` in `X-NetBox-Branch` selects the branch and asks no grant of its own; a branch reads `main` as it stood when it was made, and a configuration context made on it is its own | **`POST /api/plugins/branching/branches/ {name}`**; **`X-NetBox-Branch` asks no grant of its own.**; **A branch reads `main` as it stood when the branch was made.**; **A configuration context made on a branch is the branch's alone** |
| The renders (`renders.py`) | `render-config` under the header renders the branch, `Accept: text/plain` the text, its last byte the template's; no template is 400 in its own words, `text/plain`; a template that fails is 500 for that device alone; one that renders nothing is 200 with no byte; a render adds no row to a changelog | **`POST /api/dcim/devices/<id>/render-config/` renders the branch the header names.**; **Three devices render in 1.4 to 2.1 s**; **A device with no template is 400**; **A device whose platform has no template is 400.**; **A template that fails for one device refuses that device alone.**; **A template that renders nothing answers 200 with no byte.**; **A render's last byte is the template's.**; **A branch has a changelog of its own.** |
| The bracket (`bracket.py`) | Each changelog's latest id by `?limit=1&ordering=-id`, the rows above an id by `?id__gt=`, and the count at or below one by `?id__lte=`; the ids interleave and are not dense; the kinds each write adds, a journal entry's and the branch object's own on `main`'s alone; a sync adds no row and moves `last_sync`; no two loops opened and closed on one id rendered two states | **A branch has a changelog of its own.**; **`?limit=1&ordering=-id` answers the row of the highest id**; **`?id__gt=<n>&ordering=id` is honoured**; **`?id__lte=<n>` on `core/object-changes/` is honoured, and an unknown parameter is not.**; **What each write added**; **The ids of the two changelogs interleave, and no id was in both.**; **A row's members**; **A sync adds no row to either changelog, and changes what the branch reads.**; **The edit of `main` above, synced**; **In three runs no two loops that opened and closed on one id rendered different bytes.** |
| A 400 past the open | An id no object has is 400 to a list by it; a header naming no branch, or a branch deleted or merged, is 400 to a list; a render under the header of a branch deleted is 400, and one under a merged branch's was not read | **`?tag_id=` on devices is honoured**; **`?device_id=` given twice on interfaces answers both devices' ports**; **An id no device has, asked by `?device_id=`, is 400 to the reader's token**; **A header naming a `schema_id` no branch has is 400**; **A render under the header of a deleted branch is 400 in `text/html`.**; **A merged branch's header is refused, and the branch can be deleted.** |
| The probes (`probes.py`) | The context listed by its name holds the declaration as its `data`, inactive and so in no device's rendered context; under a branch's header it is `main`'s until the branch edits it | **The seeded context, listed by its name, is the declaration the seed sent.**; **Under a branch's header the context is `main`'s until the branch edits it, and its edit is the branch's alone.**; **A key of an active context renders, and no key of the inactive `fylgja-probes` is defined.** |
| `TIMEOUT_S` | The slowest of the reader's requests read | **The reader's requests took** |
| The account (below) | A list is 403 without `view` on its type; a render 404 without `view` and `render_config` on `dcim.device`, and 403 with a token that may not write; a token of no grant reads `/api/status/` | **A list the account may not view is 403**; **A render needs `view` and `render_config` on `dcim.device`, and a token that may write.**; **An account that is no superuser.**; **Each list the reader sends answered by the reader's token, none refused** |

## What it sends, and what its token must be allowed

It sends `GET /api/status/`; `GET` lists of `/api/plugins/branching/branches/`, by the branch's
name and with no branch's header, and of `/api/extras/tags/`, `/api/dcim/devices/`,
`/api/dcim/platforms/`, `/api/dcim/interfaces/`, `/api/dcim/cables/`,
`/api/extras/config-contexts/` and `/api/core/object-changes/`, the changelog, each under the
branch's header where a branch is read; and one `POST /api/dcim/devices/<id>/render-config/` a
scoped device, under that header, with `Accept: text/plain` and no body. The render is its one
request that is no `GET`: NetBox renders the device's template and stores nothing, and a render
added no row to a changelog where that was read. It follows no redirect and no `next`.

It takes NetBox's v2 token, `nbt_<key>.<token>`, sent as `Authorization: Bearer <token>`; a v1
token is not sent in its own form. Its account needs no superuser
([verified-facts.md](../../design/verified-facts.md), "Permissions"), and, on `main`, since a
branch's header asks no grant of its own:

- `view` on each type a read lists: `dcim.device`, `dcim.interface`, `dcim.cable`,
  `dcim.platform`, `extras.tag`, `extras.configcontext`, `core.objectchange` and
  `netbox_branching.branch`. A list without it is 403, which the reader raises as a
  `NetBoxError` naming `FYLGJA_NETBOX_TOKEN`;
- `view` on `dcim.manufacturer` too, as the development NetBox grants it: grant it beside the
  eight above. The reader lists no manufacturer, but a platform's row carries its manufacturer's
  name, and what NetBox answers a platform's row without that grant was not read, so until it is
  read the eight alone may not be enough;
- `view` and `render_config` on `dcim.device`, for the render. NetBox answers a render without
  them 404, not 403, though the read has just listed the device, so a missing `render_config`
  shows as `render.unavailable`, 404, on every device;
- a token that may write, `write_enabled`: NetBox refuses a render 403 with a token that may
  not, though the render writes nothing, and the reader raises that as a `NetBoxError`.

Each `view` grant must carry no constraints. By NetBox's design of its permissions, as its
documentation describes them and not as a reading shows them, a list is of the objects the
account may view, and its `count` is of that list: a constrained grant shortens a list and its
`count` alike, so every check the reader makes holds, and the blueprint is of less than NetBox
holds, which the reader cannot tell from a whole one. A grant with constraints was not read
([verified-facts.md](../../design/verified-facts.md), "Not read").

The development NetBox's account `fylgja-reader` holds these grants and no other (`GRANTS` in
[`netbox/seed/account.py`](../../netbox/seed/account.py)), and its token is
`FYLGJA_NETBOX_TOKEN`. A token of no grant reads `/api/status/`, so `connect`, and `check` of
`main`, pass with one; a read, or `check` of a branch, is the first to meet the grants.
