# fylgja-nautobot

The Nautobot reader: a typed, read-only library, `fylgja_nautobot`, and a command, `fylgja-nautobot`, that read
Nautobot as it stands, under a scope, by one documented mapping of Nautobot's own DCIM, into a blueprint 1 with its
source envelope, or the findings that refused it ([D-118](../../design/decisions.md#d-118),
[D-121](../../design/decisions.md#d-121)). Each device's configuration is what Golden Config renders for it at the
read. Its mapping is in [mapping.md](mapping.md), and its rules are in [rules.md](rules.md).

## What it is, and what it is not

It is held to what a production workflow needs ([D-081](../../design/decisions.md#d-081)): it must not hand over a
blueprint that is quietly not the network, it installs into a platform it does not own, and a Nautobot upgrade is a
procedure, below, not a rewrite.

- **It gives a blueprint or the faults, and never guesses.** Every list is held to the `count` Nautobot answers for it,
  and every row to what was asked. Every scoped device is rendered, and a device in no setting's group, a template that
  is missing or fails, and an empty render are each an error naming the device. Every fault is filed in one pass, and a
  read with an error gives no blueprint. What the blueprint can bear without a fault is a fidelity row in its envelope:
  a cable it cannot make a link of, a device renamed to a label, a probe outside the scope. The same state read twice
  gives the same blueprint id.
- **It has no branch.** Nautobot has none, so the reader names none, and a finding never says where a read was made.
- **It takes no time.** Nautobot reads no earlier state, so the reader reads it as it stands, and brackets the read by
  the changelog's newest row and its count and by each template repository's head, marked before the first list and
  again after the last render. A read that any of them moved under is refused, `read.moved`, and the remedy is to read
  again ([mapping.md](mapping.md), "The bracket").
- **It has no stale rule.** Nautobot stores no configuration: Golden Config renders a device's template at the request,
  so no configuration is older than the intent it is read with, and the Infrahub reader's stale rule has no
  counterpart here. What Nautobot does store is a dynamic group's members, which `group.stale` holds to the group's
  filter (below).
- **It is read-only.** Every request it sends is a `GET`, and none carries `branch`. A render may still write: see
  "What it sends".
- **It knows no stage, mark, tag, journal entry, twin or workflow engine.** What is read, and what is done with the
  blueprint, are its caller's: the core's client files it, and the example orchestrator under `orchestrator/` is one
  such caller.
- **It has one mapping, and it is not a user's to change.** What Nautobot cannot hold, the platform package of a pair of
  manufacturer and platform and the configuration context that declares the probes, is the reader document's
  ([`nautobot-reader-1.schema.json`](../../formats/nautobot-reader-1.schema.json)).
- **It speaks plain HTTP**, through httpx and no client library of Nautobot's, from one module, `transport.py`. It
  imports nothing of the Infrahub or NetBox readers, the example orchestrator, Prefect, pynautobot or the core's
  `server` extra, which a test over its imports holds.

## Installing it

It needs Python 3.14, `fylgja-core`'s base install, the model package and the client library
([D-084](../../design/decisions.md#d-084)), and httpx at the core's range; never the core's `server` extra. The reader
is **published to PyPI from 1.1.0 as the wheel `fylgja-nautobot`**, at the core's version and requiring `fylgja-core` at
that version or later within its major ([D-106](../../design/decisions.md#d-106)), so that installing it into the
platform's environment brings the core's base install with it. Its command, its document, its settings and its library
are held as [the compatibility page](../../docs/compatibility.md) says ([D-121](../../design/decisions.md#d-121)).
`make wheels` builds the published wheels from this repository, the reader's among them from `readers/nautobot/` with
`formats/` beside it, since its `setup.py` copies the reader's format into the wheel; install it with the core's.
`fylgja-nautobot --version` prints the version and the commit it was built at. In the tree, `make venv` installs it
editable into `core/.venv`, with its console script `core/.venv/bin/fylgja-nautobot`.

Nautobot needs Golden Config, the free app, installed and set up, and no schema or app of Fylgja's: a device's
configuration is Golden Config's render of it, so that a Nautobot without the app is refused, `golden_config.absent`,
before any list. The probes are the data of a configuration context, inactive so that no device's rendered context
takes it, which whoever runs Nautobot makes, and only a reader document that names it needs it
([mapping.md](mapping.md)); `make nautobot-seed` makes `fylgja-probes` on the development Nautobot.

## The library

```python
import os
from pathlib import Path

from fylgja_nautobot import connect, read
from fylgja_nautobot.document import load

reading = load(Path("reader.yaml"))  # documents.Rejected, every problem, where it is refused
address, token = os.environ["FYLGJA_NAUTOBOT_ADDRESS"], os.environ["FYLGJA_NAUTOBOT_TOKEN"]
with connect(address, token) as conn:  # ca=Path(...) for an https:// address a private CA signed
    result = read(conn, scope="tag:fylgja", document=reading)
```

`fylgja_nautobot.__all__` holds eleven names:

- `connect(address, token, *, ca=None)`: the `Nautobot` at `address`, an `http(s)://` URL or `host:port`, a context
  manager and the source every call reads through. It reads Nautobot's version and Golden Config's first,
  `GET /api/status/`; a pair not in `SUPPORTED` is the warning `nautobot.version.unverified`, carried on every result
  of the connection and logged once (logger `fylgja.nautobot`). An `https://` address is verified against the CA file
  `ca`, or the system's trust where it is None. `InvalidAddress`, `InvalidToken` and `InvalidCA`
  (`fylgja_core.client`) are raised before any request.
- `Nautobot`: that connection's class, and `SUPPORTED`: the pairs of Nautobot's version and Golden Config's the reader
  passed on.
- `read(conn, *, scope, document)`: a `Result` of the blueprint, None exactly when a finding is an error; every
  finding, in a result's order (`fylgja_core.findings.order`); and `empty`, whether the scope selected no device.
  `scope` is `tag:<name>`.
- `check(conn)`: the connection's version warning, where it has one, and `golden_config.absent` where Golden Config is
  not installed; nothing is sent.
- `ReaderDocument` and `Match`: the reader document and a row of its platforms; `document.load(path)` makes one from a
  YAML or JSON file, or raises the core's `documents.Rejected` naming the file, with every problem.
- `Result` and `Source`: the result of a read, and every call a read makes of Nautobot, which `Nautobot` is, so a read
  runs alike against Nautobot and against rows built in a test.
- `NautobotError`: Nautobot refused a request, answered what is no answer, or was not reached. Its text names what was
  being read; its `status` is the HTTP status Nautobot answered, 200 for an answer that is no answer to what was asked,
  and None where Nautobot was not reached. A 400 to a list past the bracket's open is weighed at the close before it
  is raised: where the changelog or a head moved, the read is refused by `read.moved` instead. A render's 400 is never
  raised: it is a finding filed for its device. A name that answers two rows, a tag's or a context's, is a
  `NautobotError`, since which of them a read would take cannot be told.
- `redact(text, token)`: `text` with the token replaced, as the reader hides it in every text it raises: for a program
  that sends requests of its own to Nautobot beside the reader's.

No finding, error, log line, `repr` or blueprint holds the token, and no finding a byte of a configuration. The library
logs under `fylgja.nautobot`, the version warning alone, and gives that logger a `NullHandler`, so an integrator who
wants the log attaches a handler of their own.

## The command

`fylgja-nautobot` makes the same calls from a shell. Nautobot's address, the token and the CA are
`FYLGJA_NAUTOBOT_ADDRESS`, `FYLGJA_NAUTOBOT_TOKEN` and `FYLGJA_NAUTOBOT_CA` alone, never a flag
([D-042](../../design/decisions.md#d-042)); the CA may be left unset, an `https://` address then verified against the
system's trust. They are checked, with the reader document, in one pass before Nautobot is reached, each fault named.
The reader document's path and `--out`'s are taken as given, a relative one from the working directory, and `--out`
names a file.

```sh
fylgja-nautobot --version
fylgja-nautobot read --scope tag:N --reader FILE --out FILE
fylgja-nautobot check
```

- `read` reads Nautobot under the scope, writes the blueprint to `--out` as JSON, whole or not at all and readable by
  its owner alone (mode 0600), and prints `<blueprint id> <n> devices, <n> links, <n> probes`.
- `check` prints `ok: Nautobot <version>, Golden Config <version>`. It sends nothing beyond `connect`'s
  `GET /api/status/`, which an account of no grant may read, so it checks none of the grants below.

`--version` prints the command's version and the build it came from, and `--help`, given alone, lists the commands and
`--version`; given after a command, it lists that command's options.

Each finding is one line on stderr, `<severity> <rule> <object>: <message>`, in a result's order. A blueprint holds
every device's configuration, so it is written to `--out` and never printed, and nothing the command prints holds the
token. Its exit status:

| Status | Means |
|---|---|
| 0 | No finding is an error: the blueprint written, or `ok` printed, and any warning or `info` finding printed beside |
| 1 | A finding is an error, `read.moved` among them: `--out` is not written, and a file already there is left as it was |
| 2 | A failure of the command's own: its arguments refused; a variable not set, or one the client's rules refuse, named with the rule and never its value; a reader document refused, with its problems, or not read; a `NautobotError`; or `--out` not written |

## Supported Nautobot versions

The pairs of Nautobot's version and Golden Config's the reader's contract tier passed on, `SUPPORTED` in `transport.py`,
each with the date the tier passed whole on it. On any other pair the reader still reads, and every result carries the
warning `nautobot.version.unverified`. A Nautobot with no Golden Config was not read: it is refused,
`golden_config.absent`.

The tier (`readers/nautobot/tests/contract/`) provokes each rule of [rules.md](rules.md) on the development Nautobot,
writing only objects of the tier's own naming, `fylgja-contract-<8 hex>`, deleted in a `finally`, or editing a seeded
object it restores there. What cannot be written into Nautobot is provoked in flight, an answer altered on its way to
the reader: a Nautobot naming no Golden Config (`golden_config.absent`), a pair of versions not in `SUPPORTED`
(`nautobot.version.unverified`), a list answered short of its count (`read.incomplete`), a render answered 502, 200
with no `intended_config` and 400 in the words of a device not found (`render.unavailable`, `render.invalid`,
`render.device.unknown`), and a changelog row made visible late, the close's count one more with its newest row
unchanged (`read.moved`). An edit of a seeded interface and a push to the template repository are writes made as a
read's first render passes, so that they land inside the read (`read.moved`), and the read after them gives a
blueprint. Every other rule a request can meet is provoked by a write of the tier's, or, for `scope.invalid` and
`probe.context.absent`, by the scope or the reader document the read is given. The pure tier alone holds the reader
document's problems (`reader.version.unsupported`, `reader.invalid`, `reader.platform.duplicate`), which no request
reads; `group.unchecked`, since the tier does not change the type or the filter of the setting's own group; the
declaration's rules the core's loader files, `probes.version.unsupported`, `probes.invalid`, `probe.name.duplicate`
and `probe.address.duplicate`, alike whatever context holds the data (`probe.gateway.outside` alone is provoked on
Nautobot); and the forms of a rule Nautobot cannot be made to answer: a list answering one object twice or lacking an
id asked, a changelog with no row at the open, a repository no longer listed at the close. `make contract-nautobot`
passed whole on 2026-11-20, `nautobot/`'s 15 tests and the reader's 41, in about 515 s.

| Nautobot | Golden Config | Passed on |
|---|---|---|
| 3.2.8 | 3.0.8 | 2026-11-20 |

## Upgrading Nautobot

An upgrade is a procedure, not a rewrite ([D-118](../../design/decisions.md#d-118)): the reader is verified on the new
pair before `SUPPORTED` names it.

1. **The development Nautobot at the new versions**, on new volumes: `make nautobot-down PURGE=1` first where one runs,
   so that the new versions make the database themselves, from empty volumes, and the seed and the contract tier read a
   Nautobot that holds nothing an earlier version wrote. Then, from the repository's root, with `local/.env` loaded
   after `make nautobot-up` and again after `make nautobot-seed`: the purge made the tokens it holds dead, and the seed
   makes the reader's account and its token anew.

   ```sh
   make nautobot-down PURGE=1
   make nautobot-up NAUTOBOT_VERSION=<v> GOLDEN_CONFIG_VERSION=<v>
   set -a; . local/.env; set +a
   make nautobot-seed
   set -a; . local/.env; set +a
   make contract-nautobot
   ```

2. **Each recorded fact the code leans on, read again** on the new pair, and recorded under a section of its own in
   [verified-facts.md](../../design/verified-facts.md), dated, saying only what the run showed. The table below names
   each by its bullet under "Nautobot 3.2.8 with Golden Config 3.0.8". A fact that reads otherwise changes the code, and
   the decision behind it where it changes one, before the pair is named.
3. **`SUPPORTED` and the table of versions above extended in one commit**, with the date the contract tier passed whole,
   every test passed and none skipped: outside `CI` a test the tier cannot connect for, a dead token after the purge
   say, is skipped, and `make contract-nautobot` still exits 0.

| The code | Leans on | Its bullets under "Nautobot 3.2.8 with Golden Config 3.0.8" |
|---|---|---|
| `connect` | `GET /api/status/` names `nautobot-version` and, among `nautobot-apps`, `nautobot_golden_config`; a token is sent as `Authorization: Token <key>`, and a key Nautobot never made is refused | **`/api/status/`**; **A token is the requesting account's, whoever it names.**; **The account's token under its own grants.** |
| The pager, and `read.incomplete` | A list answers `count` beside `results`, and `limit` and `offset` page it; a page of 100 is answered whole | **A page of 100 is whole.** |
| Every row held to what was asked | A filter Nautobot does not know is refused, not ignored; each one the reader sends is honoured: `?name=` exact and case-sensitive, `?tags=`, `?id=` (an id no object has answers no row and no error), `?device_id=` | **A filter Nautobot does not know is refused.**; **`?name=` of a tag or a configuration context is exact, letter case included.**; **Devices are listed by `?tags=` with a tag's name or its id.**; **`?id=` of platforms, manufacturers and cables answers no row, and no error, for an id no object has.**; **Interfaces are listed by `?device_id=` or `?device=`, and an unknown device is 400.**; **Cables by device.**; **`/api/extras/git-repositories/?id=` answers no row, and no error, for an id no repository has.** |
| The request bound (`MAX_REQUEST`) | A request line longer than a server's buffer is dropped with no answer, which the reader raises as a `NautobotError` and never reads as a short list | **A request too long is dropped unanswered.** |
| The rows (`transport.py`) | The members of each list's rows: a device's `name` null or empty where it has none, a platform's `manufacturer`, a related object as `{id, object_type, url}`, a cable's `terminations` of one member a connector of a side, an interface's `cable` and its far port; a deleted device's cables stand with no ends | **A device's `name` may be null, or empty.**; **A related object is `{id, object_type, url}` at the default depth**; **A cable's `terminations` is one member a connector of a side**; **A platform carries its `manufacturer`**; **An interface's row names its cable and the far port**; **A device's delete leaves its cables standing, with no ends.** |
| The renders (`renders.py`) | A render is one `GET` of `generate-intended-config` by `device_id`; its 200 holds `intended_config`, each failure is a 400 in its own words, it starts no job, and it runs the setting's query under the account's grants | **`GET /api/plugins/golden-config/generate-intended-config/?device_id=<id>`**; **What a render answers when it cannot render**; **A render writes nothing of Golden Config's and starts no job.**; **The query runs with the rendering account's grants, and a render of what the account cannot see is answered 200 without it.** |
| Settings and groups (`groups.py`) | A setting is listed at Golden Config's own path and names its repository and its dynamic group; a device is rendered under the setting its group's stored members give, and the members are listed by `?dynamic_group=` and held to the filter's devices | **Golden Config's settings are listed at `/api/plugins/golden-config/golden-config-settings/`**; **The installed app holds one setting, `Default Settings`**; **A device is rendered only while it is a member of a setting's dynamic group, and the members are stored.**; **Of two settings over one device, the heavier's template is rendered, and neither is refused.**; **The setting's group, by `extras/dynamic-groups/?id=`**; **`extras/static-group-associations/?dynamic_group=<id>` lists a dynamic group's stored members, whole, with a count, and restricted by `?associated_object_id=`.**; **The device list asked with a `dynamic-filter` group's filter as its query answered what a save of the filter stored, for every filter read.**; **A filter of other values is saved, and stores what no query can be sent for.**; **A tag a group's filter names, deleted, leaves the filter and the stored members, and the device list refuses it.**; **A device tagged after the default group's last save is in the device list and not in the stored members.** |
| The bracket (`bracket.py`) | The changelog lists the newest row first and `?limit=1` answers it with the count, its `time` with a `Z`; a row written in a longer transaction is visible at its commit; a render fetches the repository's head and records a new one; several web instances were read in the source alone | **`/api/extras/object-changes/` lists the newest row first, and a row's `id` is a UUID**; **The newest row `?limit=1` answers carries `time` with a `Z` suffix**; **A row written inside a longer transaction becomes visible at its commit, with the time it was written.**; **Every render fetches the repository's branch first, and records a new head in the changelog.**; **A render by the reader after a push moves the head and writes one changelog row.**; **Several web instances, read in the installed source alone and not run.**; **Two loops of one open that each closed unmoved rendered one text.**; **Golden Config's `branch` names a branch of the template repository.**; **A Git repository registered over the API**; **`/api/extras/git-repositories/?id=` answers no row, and no error, for an id no repository has.** |
| The probes (`probes.py`) | The context listed by its name holds the declaration as its `data`, inactive, so no device's rendered context takes it | **A configuration context made with `is_active: false`**; **The configuration context reaches the template as the query's `config_context`, the inactive one absent.** |
| The account (below) | A list is refused without `view` on its type, a render of what the account cannot see is answered 200 without it, and the account's token writes nothing | **The least grants under which the account reads what the superuser reads and renders what it renders are `view` on twelve types**; **The account's token writes nothing.**; **Nautobot's API shows no membership of a user.**; **The account's token under its own grants.**; **Only the token's own account can tell its owner and `write_enabled`.** |

## What it sends, and what its account must be allowed

It sends `GET /api/status/`; `GET` lists of `/api/extras/tags/`, `/api/dcim/devices/`, `/api/dcim/platforms/`,
`/api/dcim/manufacturers/`, `/api/dcim/interfaces/`, `/api/dcim/cables/`, `/api/extras/config-contexts/`,
`/api/extras/object-changes/`, the changelog, `/api/extras/git-repositories/`, Golden Config's settings,
`/api/extras/dynamic-groups/` and `/api/extras/static-group-associations/`; and one
`GET /api/plugins/golden-config/generate-intended-config/?device_id=<id>` a scoped device. **Every request is a `GET`,
and none carries `branch`**: Golden Config's `branch` names a branch of the template repository, which the reader
never asks for. It follows no redirect and no `next`, and trusts no proxy of the environment.

**A render may save its repository's new head and write a changelog row under the reader's account**, which the reader
does not ask for and cannot prevent, a token with writing disabled included: Golden Config fetches the repository's
branch at every render and saves a head newer than the one it holds. A read during which a push is first fetched is
refused once, `read.moved`, and the next read finds the head already fetched.

A write to any object anywhere in Nautobot while a read runs adds a changelog row and refuses that read, not only a
write to what is in scope ([D-118](../../design/decisions.md#d-118)), so a busy instance should expect to read again.

It takes Nautobot's token, sent as `Authorization: Token <key>`. Its account needs no superuser, and no right to write
([verified-facts.md](../../design/verified-facts.md), "Nautobot 3.2.8 with Golden Config 3.0.8"). It needs `view`, with
no constraint, on each type a read lists, and the development Nautobot's account `fylgja-reader` holds these grants and
no other, fourteen, `GRANTS` in [`nautobot/seed/account.py`](../../nautobot/seed/account.py): a list without one is 403,
which the reader raises as a `NautobotError` naming `FYLGJA_NAUTOBOT_TOKEN`. One of them, `view` on
`extras.staticgroupassociation`, is the list of a group's stored members, which the reader holds to the group's filter;
one, `view` on `users.token` constrained to the account's own tokens, is how the seed tells whose a key is and
whether it writes. A token of no grant reads `/api/status/`, so `connect` and `check` pass with one;
a read is the first to meet the grants.

**The account must view everything the site's query reads, which the reader cannot check: an account that sees less
gets a smaller configuration and no error, a known limit.** Golden Config runs the setting's GraphQL query under the
rendering account's grants, and a device whose interfaces the account cannot view is rendered, 200, without them. The
grants above are the least on which the development Nautobot's account rendered what the superuser rendered, byte for
byte, for the fixture's query; a site whose query reads more needs more.

Beyond these, the reader's limits are known and not hidden:

- **A request line is held to 1500 bytes.** The development Nautobot's image sets `buffer-size = 4096` in its
  `uwsgi.ini`, and its uWSGI dropped, with no answer, every request of 1825 bytes or more of path and query and
  answered 1824. 1500 is a derivation from that, about 0.82 of 1824, not a reading. The reader sends a list by ids in
  batches whose path and query stay within it, and a request dropped anyway is a `NautobotError`, never a short list.
  A site whose server drops less is not asked to change it.
- **A deleted device's cables stand.** Nautobot leaves them with no ends, and the reader, which lists a cable only by
  the interfaces of a scoped device, never reads them.
- **Several web instances are not supported.** The reader was verified against one. In the installed source each
  instance clones a template repository into its own `GIT_ROOT` (`/opt/nautobot/git` unless `NAUTOBOT_GIT_ROOT` says
  otherwise) and, at every render, fetches the branch's latest commit and saves it as the one `current_head` the
  database holds where that differs, so a site that runs several should expect a push to be fetched by whichever
  instance renders first, and the bracket to refuse that read as it would on one; this was read in the source, not run.
- **A group's stored members are held to its filter.** A Golden Config setting's devices are a dynamic group whose
  members Nautobot stores, and Golden Config renders a device under the setting its stored membership gives. The
  reader holds each setting's group's stored members to its filter for the scoped devices, and a difference refuses the
  read with `group.stale`, naming the group: save the group, or run the job `RefreshDynamicGroupCaches`, then read
  again. A group of another type than `dynamic-filter`, or whose filter is no object or holds a null, an object, a list within a list
  or the key `id`, is not checked (`group.unchecked`, a warning).
- **What the bracket does not see.** `RefreshDynamicGroupCaches` writes no changelog row, so a refresh is a change the
  reader cannot see, and the remedy of `group.stale` is one: read again after it. A row pruned from the changelog while
  another becomes visible late cancels in the count.
- **A group granting the account more cannot be found.** Nautobot's API shows no user's groups and no permission's
  users, so the seed refuses an account that a permission outside the fourteen names, and cannot refuse one a group
  reaches; a token list names no owner (the reader's token carries the description `fylgja-reader`); and a replaced
  reader token is not revoked.
