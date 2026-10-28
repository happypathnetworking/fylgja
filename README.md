# Fylgja

[![ci](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml)

Fylgja builds a **walking twin** of a network from its intent. You name a branch in
[Infrahub](https://github.com/opsmill/infrahub), and optionally a point in time. Fylgja
reads it, compiles it into a deterministic bundle, and boots it as a running
[containerlab](https://containerlab.dev) topology on real network operating system
images. Then it pushes each device's production configuration as Infrahub rendered it.
The twin stays as it was read until you step it, to a later read of the branch or to a
stage of a proposed change, and a step changes only what differs. Provisioning runs through
[Temporal](https://temporal.io), so a create that fails or is cancelled cleans up after
itself; state lives in containerlab, a few files and Temporal, and there is no database.
There is one twin at a time, on one lab host. Every command is a request to Fylgja's API,
which `fylgja serve` answers on the lab host, so a shell that holds the API's token alone
can drive the twin, from the lab host or through an SSH tunnel from another machine.
`v0.2.0` is released: a proposed change rehearsed on a twin before it merges. What
[v0.1](docs/archive/v0.1-built.md) and [v0.2](docs/archive/v0.2-built.md) built is recorded,
and the [roadmap](docs/roadmap.md) says what comes next.

![A proposed change's stages listed, then rehearsed on one twin: booted at the branch point, stepped through two stages, refused at the third, and destroyed](docs/recording/session.gif)

The asciinema cast beside it, [docs/recording/session.cast](docs/recording/session.cast),
plays the same session as text. Both were recorded at `v0.2.0`, with the fixture's three
nodes written to `main` for the recording alone ([D-054](docs/decisions.md#d-054)), so that
the branch point is the baseline; on a `main` that holds no network, as here otherwise, it is
refused and the first marked stage is. [What the rehearsal posts in
Infrahub](#a-proposed-change-rehearsed) is shown below.

Today it runs Nokia SR Linux and Arista EOS, alone or mixed in one twin. A vendor is a
YAML file, not code ([psp/README.md](psp/README.md)). A twin steps to another read or to a
stage of a proposed change without a rebuild, and `twin verify` reports whether the running
twin matches its intent. A rehearsal takes a twin through every
stage of a proposed change and destroys it, from the shell or from a check inside Infrahub
that posts the report on the proposed change and fails it when a stage fails.

## Built with an AI agent

Fylgja was built with Claude, an AI agent, working through the
[Spec Kit](https://github.com/github/spec-kit) workflow, with a human deciding every
question of scope and design. The record of how it was built (the specifications, plans,
research and command logs) is private; this repository holds the result.

## What it needs

One Ubuntu 26.04 host on amd64, and a clone of this repository. `scripts/bring-up.sh`
stands the host up: run it from the clone, as the user who will run Fylgja (not root). It
asks for `sudo` once.

```sh
git clone https://github.com/happypathnetworking/fylgja.git && cd fylgja
scripts/bring-up.sh --ceos-tar ~/Downloads/cEOS-lab-4.32.0.2F.tar   # or no flag: SR Linux alone
```

It runs four parts in order. Each item is checked, installed when it is missing and
checked again, and each prints one line, `present`, `installed` or `skipped` with why:

| Part | What it installs, or finds already there |
|---|---|
| `toolchain` | `make`, `git`, `curl`, `jq`, `xz-utils`, `file`; Go (Ubuntu's, which fetches the 1.26 toolchain `go.mod` names); golangci-lint 2.14.0; the Temporal CLI 1.9.1; gnmic 0.49.0; `.venv/` with `infrahub-sdk[ctl]` 1.23.2 |
| `lab` | Docker and containerlab 0.79.0, with you in the groups `docker` and `clab_admins`; the AppArmor lines SR Linux's `rsyslogd` needs; the SR Linux image, pulled; the cEOS image, imported from the tar |
| `infrahub` | Infrahub 1.11.2 on `:8000`, from its published Compose file, under `local/infrahub/`. Fylgja reads intent and each device's configuration from it, and never writes to it. The part prepares its `main`: the schema library's DCIM, vendored under `schema/dcim/` and loaded only on a `main` holding none of the library's kinds, beside the stage kind, the one kind Fylgja adds ([schema/README.md](schema/README.md)); the empty group `fylgja-devices`; and this repository registered read-only, so that Infrahub renders each device's `device-config` artifact from the template here and runs the two checks of [A proposed change, rehearsed](#a-proposed-change-rehearsed) (`.infrahub.yml`, `infrahub/`); its Compose override gives Infrahub's task workers the API's address and token. Then it seeds the fixture branch `fylgja-fixture` |
| `fylgja` | `make build` → `bin/fylgja`, one static binary: the commands, the worker and the API's server; then three processes, left running and logging under `local/`: Temporal's file-backed dev server on `:7233`, the worker, and the API's server on `127.0.0.1:7650` and on the host's Docker bridge address, where those checks reach it, the last two with `local/` as their state root; then tiers 1 and 2 (see [Tests](#tests)), after the processes since tier 2's check test runs the checks inside Infrahub against this build's server on the bridge |

Before any part, when there is no `local/.env`, it writes one, readable by you alone:
Infrahub's address and an admin token it makes, each platform's node login (the image's
default), the API's token (`FYLGJA_API_TOKEN`), which the server and every command share,
the server's default scope (`FYLGJA_DEFAULT_SCOPE`, `tag:fylgja`), the tag a command that
names no `--scope` reads its devices under, and Infrahub's Compose values. A `local/.env`
already there is kept as it is. Fylgja reads
the process environment only, and neither it nor the script prints, logs or stores a
credential anywhere else ([.env.example](.env.example) names every value).

The script ends `bring-up: DONE`, naming the three processes and how to stop them; on a
host it set up, skip the first walk-through's step that starts them. A second run installs
nothing and runs the tiers again, and `--part` runs one part alone. A fresh host took
about 28 minutes with the tar and 20 without, most of it the images' pulls and import. The
host it was proved on had 10 vCPUs and 32 GiB; Infrahub idles at about 5 GiB, and the
script warns under 24 GiB.

**The cEOS image is account-gated.** You download `cEOS-lab-4.32.0.2F.tar` (or `.tar.xz`)
from Arista yourself, and Fylgja never pulls it. The script looks for it at `--ceos-tar`,
then in `local/`, then in the clone's parent directory, never in the clone's root, and
imports it only when its sha256 is the one recorded. Without it the host runs **SR Linux
alone**, and the script says so in its first and last reports. The cEOS image is needed
only for EOS and mixed twins and for tier 3's two EOS cases. Every twin the walk-throughs
on this page boot is SR Linux, and the mixed compile under [Two vendors, one
twin](#two-vendors-one-twin) boots nothing, so each runs on such a host unchanged.

[docs/development.md](docs/development.md#local-environment) describes each component, and
where the cEOS image comes from.

## A walking twin, start to finish

This is a real session on one lab host, with Infrahub running beside it. Each step's
`begins` line is left out, and other trimmed lines are marked `…`. It was recorded at
`v0.2.0`, before Fylgja read the schema library's DCIM or took snapshots, and while a twin
followed its branch: its ids, counts and schema hashes are that release's, and the lines
017, 018 and 019 changed (the record's scope, mapping and snapshot, the scope in a plan's
heading, `scope.empty` at the branch point, a create's two `stored:` lines in place of its
run's read and compile, each stage's `snapshot_id`, the report's `snapshot` column, the
kind line, the snapshot in `twin verify`'s first line, a rehearsal's deadline) are shown as
this build prints them, with the snapshot ids, which that release did not take, trimmed to
`…`. Where that release rebuilt the twin on the branch's change, this build steps it: the
reads and the steps to their snapshots are shown as this build prints them, with the ids,
checksums and times no recorded run printed trimmed to `…`, and the bundle ids and
checksums the release's rebuild printed kept. Start the workflow service, the worker,
which runs on the lab host and does everything that touches it, and
the API's server beside it, which every command below talks to. The two roles share one
state root, here `/var/tmp/fylgja`; any absolute directory both can write will do:

```sh
set -a; . local/.env; set +a     # Infrahub, the node logins, FYLGJA_API_TOKEN and FYLGJA_DEFAULT_SCOPE
make build                       # once: both roles below run this binary
make temporal-dev &              # the workflow service
mkdir -p /var/tmp/fylgja         # the state root: the bundle and snapshot stores and the twin directory
FYLGJA_STATE_ROOT=/var/tmp/fylgja bin/fylgja worker run &   # the lab host worker: prints what it will run, and what's on the host
FYLGJA_STATE_ROOT=/var/tmp/fylgja bin/fylgja serve &        # the API's server on 127.0.0.1:7650: prints where it listens, its state root, its default scope and packages
```

`make worker` and `make serve` each build first, and use `local/` in the repository as
their state root, so starting both at once runs two builds of `bin/fylgja` side by side,
and the second can replace the binary the first role has just started, leaving it on a
`(deleted)` binary. Build once, then start each role from the binary, as above; restart
both after every rebuild.

Every `bin/fylgja` command after this is a client of that server, and needs nothing from
`local/.env` but the token. A shell that holds only `FYLGJA_API_TOKEN`, and
`FYLGJA_API_ADDRESS` when the server is not at `127.0.0.1:7650`, runs them; from another
machine, open `ssh -N -L 7650:127.0.0.1:7650 <lab host>` first and copy the binary over.
The server makes every refusal and renders every line. The fixture tool is a test tool: it writes to Infrahub itself, with
`local/.env` loaded.

Seed a throwaway branch with the three-node SR Linux fixture. Every device gets its
configuration artifact rendered by Infrahub:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme
schema loaded on fylgja-test-readme
three-node fixture seeded on fylgja-test-readme, with every artifact rendered and Ready
```

**Create the twin.** Fylgja reads the branch, takes what it read as a **snapshot**,
content-addressed and filed, and compiles it, all before the run starts; the run then
checks the host, deploys, waits for every node to answer, pushes each artifact, and
records what it built. It reads the
devices tagged by its scope, `--scope tag:<name>`, or, given none as here, the server's
default, `FYLGJA_DEFAULT_SCOPE` from `local/.env` (`tag:fylgja`, the tag the fixture puts
on every device), which the record line names; a server started with no default refuses a
command that names no scope `scope.unset`, as one started from a `local/.env` written
before 017 does, since the script keeps the file it finds: add the line to it.

```console
$ bin/fylgja twin create --branch fylgja-test-readme
snapshot_id …  stored: /var/tmp/fylgja/snapshots/….json
bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee  stored: /var/tmp/fylgja/bundles/777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee
run fylgja-provision 01a112a2-7ee6-7772-a701-af726d528abc
step host check: done in 0.1s
step stage: done in 0.0s
step deploy: done in 41.3s (3 nodes)
step readiness n1: ready in 0.3s
step readiness n2: ready in 0.3s
step readiness n3: ready in 0.4s
step push n2: done in 2.3s
step push n1: done in 2.4s
step push n3: done in 2.5s
step record: done in 0.0s
twin ready: bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee
  n1  172.20.20.3
  n2  172.20.20.4
  n3  172.20.20.2
record: branch fylgja-test-readme, snapshot …, bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee, schema 4d5b37aa0a894aec4cdca69fdb9fe455, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9
twin directory /var/tmp/fylgja/twin
warning host.memory.unbudgeted [step host_check] host: sum 6144 MiB (n1 2048, n2 2048, n3 2048) is not checked against a host budget: FYLGJA_HOST_MEMORY_MB is unset
1 finding(s): 0 rejection, 1 warning, 0 info
```

Nearly all of the time is containerlab booting three SR Linux nodes, and it depends on
how busy the host is. The snapshot's id is the hash of what was read, without the time it
was read, so the same intent read again has the same id; `twin create --snapshot <id>`
builds it again from the server's store, with no read, as the end of this walk-through
says. A second `twin create` is refused, naming this twin.

**Look at it.** `twin show` reads containerlab, the record and the workflow service, and
changes nothing. Its kind line names the snapshot the twin is at:

```console
$ bin/fylgja twin show
twin: lab fylgja present (3 nodes); twin directory present
  n1  clab-fylgja-n1  running  172.20.20.3  nokia_srlinux  device-config f05634801639578ed97c10f9d0265546
  n2  clab-fylgja-n2  running  172.20.20.4  nokia_srlinux  device-config 36667eef6c8a92923957b9549784273b
  n3  clab-fylgja-n3  running  172.20.20.2  nokia_srlinux  device-config 7efd0c0d5f40e5119d75b8b8d31d3e57
record: branch fylgja-test-readme, snapshot …, bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee, schema 4d5b37aa0a894aec4cdca69fdb9fe455, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9
  intent read at 2026-10-06T19:13:21.796364Z; reproducing it with --at that instant is best-effort
  provisioned by run fylgja-provision 01a112a2-7ee6-7772-a701-af726d528abc (source intent), worker 0.1.0-dev, recorded 2026-10-06T19:14:09.579682296Z, 3 nodes
kind: snapshot … (branch fylgja-test-readme, read at 2026-10-06T19:13:21.796364Z)
in flight: none
```

The nodes are real. `twin verify` asks each one over its own package's transport whether
it is what intent says: its host name, every cabled port enabled, and every link seen as
an LLDP neighbour from both ends. It also reports what the record says each node holds,
labelled as the record's claim. It needs no worker and changes nothing:

```console
$ bin/fylgja twin verify
twin: branch fylgja-test-readme (snapshot …, bundle 777e9899…), ready; 3 nodes
staged: bundle 777e9899…; 15 assertions over 3 nodes, 0 skipped
n1 (172.20.20.3:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2; record: holds 777e9899…
n2 (172.20.20.4:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds 777e9899…
n3 (172.20.20.2:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2; record: holds 777e9899…
skipped: none
in flight: none
held: 3 host names, 6 ports, 6 link ends, 3 record claims (the record's, not read); failed: none; unread: none
```

A port disabled by hand outside Fylgja draws three findings (its own state and both ends'
neighbours) and exit 5, `nonconforming`; `--wait` reads again until the twin settles.

**Change the branch.** Disable n1's `ethernet-1/2` in Infrahub and have it re-render the
artifacts. Infrahub 1.11 doesn't regenerate them on its own, so the fixture tool asks it to:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -disable-port n1:ethernet-1/2 -generate
interface ethernet-1/2 on n1 disabled on fylgja-test-readme
artifacts rendered and Ready on fylgja-test-readme
```

The twin does not move. Nothing reads the branch for it, and nothing changes it but you:
`twin show` prints what it printed before, the same record and the same kind line, with
nothing in flight:

```console
$ bin/fylgja twin show
…
kind: snapshot … (branch fylgja-test-readme, read at 2026-10-06T19:13:21.796364Z)
in flight: none
```

**Step it to the change.** Read the branch again. `intent read --out` takes and files a
snapshot as a create does, writes it to the file, and prints its id; `twin step --snapshot`
takes that file, or the id, and steps the twin to it with no request to Infrahub: the server
compiles the snapshot and compares its bundle with the twin's, and the run changes only what
differs. The fixture tool can return before Infrahub has rewritten an artifact, so read once
n1's checksum has moved in Infrahub. Only n1's artifact moved, so only n1 is pushed, by
replace, and no container restarts:

```console
$ bin/fylgja intent read --branch fylgja-test-readme --out local/readme-1.json
wrote local/readme-1.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports (branch fylgja-test-readme, scope tag:fylgja, schema 7c413536d67ef86321c629c076a0d3a4); snapshot …, stored at /var/tmp/fylgja/snapshots/….json
$ bin/fylgja twin step --snapshot local/readme-1.json
twin: snapshot … (bundle 777e9899…), branch fylgja-test-readme, read at 2026-10-06T19:13:21.796364Z; 3 nodes
target: snapshot … (branch fylgja-test-readme, read at …)
step snapshot … → snapshot … (777e9899… → e26f042a…):
  nodes: unchanged
  links: unchanged
  artifacts: n1 device-config f0563480… → cf9fe341…
reconcile: nothing to apply
push: n1 (artifact); n2, n3 untouched
run fylgja-step …
…
stepped to snapshot … (bundle e26f042a…) in …: push n1 …; settled after …
```

The record now names the new snapshot and its bundle, and still no stage. After its record
the run waits, as `twin verify --wait` would, until the twin conforms to its new intent, and
`twin verify` names the snapshot the twin is at:

```console
$ bin/fylgja twin verify
twin: branch fylgja-test-readme (snapshot …, bundle e26f042a…), ready; 3 nodes
staged: bundle e26f042a…; 15 assertions over 3 nodes, 3 skipped
n1 (172.20.20.3:57400, nokia_srlinux): host name n1; ethernet-1/1 enabled; neighbour n2 ethernet-1/1; record: holds e26f042a…
n2 (172.20.20.4:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds e26f042a…
n3 (172.20.20.2:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbour n2 ethernet-1/2; record: holds e26f042a…
skipped: n1:ethernet-1/2 (intent disables it); link n1:ethernet-1/2|n3:ethernet-1/2 at both ends (intent disables n1:ethernet-1/2)
in flight: none
held: 3 host names, 5 ports, 4 link ends, 3 record claims (the record's, not read); failed: none; unread: none
```

Intent now disables `n1:ethernet-1/2`, and the artifact n1 was pushed says so, so verify
skips that port and its link rather than expecting them up, and names what it skipped. Tier
3 makes the same change and step, reads the port disabled on n1 itself, and reads verify to
the same skips.

**Step it again, by id.** Add a third link, between n1 and n3, and once both their
checksums have moved in Infrahub, read the branch again. The read files the snapshot in the
server's store, so the step names it by the id the read printed, and sends no file. SR Linux
takes the new link live: containerlab re-cables the running lab without restarting a
container, and n1 and n3 are pushed their new artifacts:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -add-link
link n1:ethernet-1/3 <-> n3:ethernet-1/3 added on fylgja-test-readme
$ bin/fylgja intent read --branch fylgja-test-readme --out local/readme-2.json
wrote local/readme-2.json: 3 devices (nokia_srlinux 3), 11 interfaces, 4 links, 3 artifacts, 0 lossy mappings, 0 shared ports (branch fylgja-test-readme, scope tag:fylgja, schema 7c413536d67ef86321c629c076a0d3a4); snapshot …, stored at /var/tmp/fylgja/snapshots/….json
$ bin/fylgja twin step --snapshot …
twin: snapshot … (bundle e26f042a…), branch fylgja-test-readme, read at …; 3 nodes
target: snapshot … (branch fylgja-test-readme, read at …)
step snapshot … → snapshot … (e26f042a… → …):
  nodes: ~n1 (bootstrap, mapping); ~n3 (bootstrap, mapping)
  links: +n1:e1-3 — n3:e1-3
  artifacts: n1 device-config cf9fe341… → …; n3 device-config 7efd0c0d… → …
reconcile: live n1 (nokia_srlinux declares live); live n3 (nokia_srlinux declares live)
push: n1 (artifact, bootstrap); n3 (artifact, bootstrap); n2 untouched
run fylgja-step …
…
stepped to snapshot … (bundle …) in …: reconcile …; push n1 …, n3 …; settled after …
```

`twin show`'s kind line now names the second read's snapshot, read at that read's time, and
the step that took the twin there from the first's.

**Destroy it.** A run in flight, a create's, a step's or a rehearsal's, is cancelled and
waited for first; here none was:

```console
$ bin/fylgja twin destroy
run fylgja-destroy 01a112a6-9096-7338-8a2d-a2f03734039f
step plan teardown: done in 0.0s
step teardown: done in 1.9s (3 containers)
step unstage: done in 0.0s
removed lab fylgja (3 containers)
removed twin directory /var/tmp/fylgja/twin
$ bin/fylgja twin show
twin: none: no lab fylgja, no twin directory
kind: none
in flight: none
```

**What the kind line says.** A twin built from intent stays at the snapshot it was built
from, or last stepped to, until you step it or destroy it. Its kind line names that
snapshot and, in brackets, what it is of: the branch and the `at` its reference named,
`(branch B at T)`, or, when the reference named none, the time the branch's head was read,
`(branch B, read at T)`. An `at` makes the read pinned, and pinned reads are reproducible:
`twin create --branch B --at T` takes the same snapshot again and compiles to the same
`bundle_id`, even after the branch moves on. A read time is no reference: the head moves on,
and a read pinned at that instant takes the same snapshot only best-effort, as `twin show`
says. Either way the snapshot is filed, and `twin create --snapshot <id|file>` builds it
again, by its id in the server's store or from a file, with **no read**; it carries its own
branch, `at` and scope, so `--branch`, `--stage`, `--at` and `--scope` are refused beside
it. `twin provision <bundle-dir>` boots a bundle you already have, with no read at all: its
kind is `from a bundle`, and it names no snapshot, so it does not step.

`--dry-run` stops before starting a run. On `create` it reads, takes and files the
snapshot, compiles and files the bundle and checks the host; with `--snapshot` it reads
and takes nothing, files the snapshot a file carries, and compiles, files and checks as
before. On `provision` it reads, takes and compiles nothing: it verifies the bundle, files
it and checks the host. The same intent read twice has one snapshot id while the branch's
history stands: a rebase moves it ([D-061](docs/decisions.md#d-061)).

## A stepping twin

The walking twin above stepped to reads of its branch, each taken by hand. A twin also
steps to a **stage**. A stage is a moment of a change under review, as Infrahub holds one: a
proposed change, opened from the branch the change is built on. Every proposed change has two stages of its own, its **branch point**
(`main` as it was when the branch was made) and its **head** (the branch as it is now), and
you mark the moments between, each after the writes it seals
([schema/README.md](schema/README.md) says how). A stage is named `<branch>/<label>`.
`twin step --stage` takes the running twin to a stage, of its own proposed change or
another, and changes only what differs, as a step to a snapshot does: containerlab
re-cables the running lab, and only the nodes whose configuration moved are pushed. The push is a replace, so whatever the new stage drops is
removed from the node. Same host, same services, `begins` lines left out as before.

Start from a fresh fixture, since the walking twin's branch now has the port disabled and
the third link. The fixture tool works on test branches (their names begin `fylgja-test-`): `-propose`
opens a draft proposed change from one into `main` and waits for its checks, which render
the branch's artifacts. Mark `seeded`, add a third link, wait for n1's and n3's artifacts
to be re-rendered (their checksums move in Infrahub, here 8 to 10 seconds after `-add-link` returns), then
mark `third-link`:

```sh
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete    # its stages, its proposed change, the branch
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme            # seed it again
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -propose   # a draft into main; waits for its checks
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -stage seeded -description seeded
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -add-link  # n1:ethernet-1/3 <-> n3:ethernet-1/3
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -stage third-link -description "third link"
```

A stage marked before its artifacts are re-rendered is refused as stale
(`stage.artifact.stale`), naming each device and how to regenerate; mark it again once they
are. If the seed answers `graphql: None` straight after the delete, run it again: Infrahub
1.11.2 can refuse to create a branch just after one of the same name was deleted
([verified facts](docs/verified-facts.md#infrahub-1112)).

**Plan the stages.** `stage plan` reads every stage of the proposed change, takes and files
its snapshot and compiles it, in order, and shows what each step between them would
change. It needs no lab and no worker.
`main` holds no network here, so the branch point is refused at its read and the plan exits
1; the head is the branch as it is now, which the second mark already seals, so it is last
whatever its `at` and the step to it changes nothing:

```console
$ bin/fylgja stage plan --branch fylgja-test-readme
proposed change "fylgja-test-readme" (18df36fe-997f-c213-33b8-c510acd939bd) on branch fylgja-test-readme → main, draft (4 stages), scope tag:fylgja
fylgja-test-readme/branch-point: refused (scope.empty)
  rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at …
step fylgja-test-readme/branch-point → fylgja-test-readme/seeded (— → b63404c3…): not computed (fylgja-test-readme/branch-point was refused)
fylgja-test-readme/seeded: branch fylgja-test-readme at 2026-10-17T04:34:59.424352+00:00 (written), "seeded"
  snapshot_id …
  bundle_id b63404c330b6144f78dc3dae5daf2d675e3ddd71eec11e899cb4af14dfa00efd
  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports
step fylgja-test-readme/seeded → fylgja-test-readme/third-link (b63404c3… → d05dc990…):
  nodes: ~n1 (bootstrap, mapping); ~n3 (bootstrap, mapping)
  links: +n1:e1-3 — n3:e1-3
  artifacts: n1 device-config f0563480… → a5d72b0d…; n3 device-config 7efd0c0d… → 01125980…
fylgja-test-readme/third-link: branch fylgja-test-readme at 2026-10-17T04:35:09.759424+00:00 (written), "third link"
  snapshot_id …
  bundle_id d05dc990c7f49e6de0755978bc9f4cb75f138fc79e6c5b43ee95c2e541db6daa
  read: 3 devices (nokia_srlinux 3), 14 interfaces, 4 links, 3 artifacts, 0 lossy mappings, 0 shared ports
step fylgja-test-readme/third-link → fylgja-test-readme/head (d05dc990… → 6ecc489c…): unchanged; the ids differ by provenance alone
fylgja-test-readme/head: branch fylgja-test-readme at 2026-10-17T04:35:08.687492+00:00 (head)
  snapshot_id …
  bundle_id 6ecc489c6a38c219abf5b3d84ecbabb57db6b74d1982e409937a060a05d188d2
  read: 3 devices (nokia_srlinux 3), 14 interfaces, 4 links, 3 artifacts, 0 lossy mappings, 0 shared ports
rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at …
1 finding(s): 1 rejection, 0 warning, 0 info
```

**Create the twin at `seeded`.** It is the same run as the walking twin's, pinned at the
stage's instant:

```console
$ bin/fylgja twin create --stage fylgja-test-readme/seeded
stage fylgja-test-readme/seeded: branch fylgja-test-readme at 2026-10-17T04:34:59.424352+00:00 (written), "seeded"
snapshot_id …  stored: /var/tmp/fylgja/snapshots/….json
bundle_id b63404c330b6144f78dc3dae5daf2d675e3ddd71eec11e899cb4af14dfa00efd  stored: /var/tmp/fylgja/bundles/b63404c330b6144f78dc3dae5daf2d675e3ddd71eec11e899cb4af14dfa00efd
run fylgja-provision 01a14824-b77c-7ed6-958f-d5b3ad006e5f
…
step deploy: done in 43.2s (3 nodes)
…
twin ready: bundle_id b63404c330b6144f78dc3dae5daf2d675e3ddd71eec11e899cb4af14dfa00efd
…
twin directory /var/tmp/fylgja/twin
```

**Step it.** With no `--stage`, `twin step` goes to the next stage of the proposed change.
`--dry-run` makes every check the step makes, including containerlab's own plan for the
running lab, and touches nothing:

```console
$ bin/fylgja twin step --dry-run
dry run: no lab, container, twin directory or run is changed
twin: stage fylgja-test-readme/seeded (snapshot …, bundle b63404c3…), pinned at 2026-10-17T04:34:59.424352+00:00; 3 nodes
stage fylgja-test-readme/third-link: branch fylgja-test-readme at 2026-10-17T04:35:09.759424+00:00 (written), "third link"
step fylgja-test-readme/seeded → fylgja-test-readme/third-link (b63404c3… → d05dc990…):
  nodes: ~n1 (bootstrap, mapping); ~n3 (bootstrap, mapping)
  links: +n1:e1-3 — n3:e1-3
  artifacts: n1 device-config f0563480… → a5d72b0d…; n3 device-config 7efd0c0d… → 01125980…
reconcile: live n1 (nokia_srlinux declares live); live n3 (nokia_srlinux declares live)
push: n1 (artifact, bootstrap); n3 (artifact, bootstrap); n2 untouched
wait: after the record, until the twin conforms, at most 2m0s
memory: sum 6144 MiB; host budget 22873 MiB
host: lab fylgja present; twin directory present
verdict: clear
$ bin/fylgja twin step
…
run fylgja-step 01a14825-cf27-77d6-bfeb-00dcaf01d2f4
step inspect: done in 0.2s
step host check: done in 0.2s
step plan reconcile: done in 0.3s (live n1, n3)
step stage: done in 0.0s
step reconcile: done in 0.8s (3 nodes)
step push n1: done in 2.6s
step push n3: done in 2.6s
step record: done in 0.1s
step observe: settled after 6.1s (1 read)
stepped to stage fylgja-test-readme/third-link (bundle d05dc990…) in 4.5s: reconcile 0.8s; push n1 2.5s, n3 2.6s; settled after 6.1s
```

The step took 4.5 seconds where a destroy and a create take about a minute. SR Linux takes the new link
live, so no container restarted (each still had the create's start time), n2 was neither
touched nor pushed, and n1 and n3 were pushed their new artifacts by replace. After its
record the run waits, as `twin verify --wait` would, until the twin conforms to its new
intent; here the first read already did. `twin verify` sees the new link from both ends,
and `stage list` marks the twin's stage:

```console
$ bin/fylgja twin verify
twin: stage fylgja-test-readme/third-link (snapshot …, bundle d05dc990…), ready, pinned at 2026-10-17T04:35:09.759424+00:00; 3 nodes
staged: bundle d05dc990…; 19 assertions over 3 nodes, 0 skipped
n1 (172.20.20.3:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2, ethernet-1/3 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2, n3 ethernet-1/3; record: holds d05dc990…
n2 (172.20.20.2:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds d05dc990…
n3 (172.20.20.4:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2, ethernet-1/3 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2, n1 ethernet-1/3; record: holds d05dc990…
skipped: none
in flight: none
held: 3 host names, 8 ports, 8 link ends, 3 record claims (the record's, not read); failed: none; unread: none
$ bin/fylgja stage list
proposed change "fylgja-test-readme" (18df36fe-997f-c213-33b8-c510acd939bd) on branch fylgja-test-readme, draft (4 stages)
  fylgja-test-readme/branch-point  main                at 2026-10-17T04:33:44.802096Z      (branch point)  ""
  fylgja-test-readme/seeded        fylgja-test-readme  at 2026-10-17T04:34:59.424352+00:00 (written)       "seeded"
  fylgja-test-readme/third-link    fylgja-test-readme  at 2026-10-17T04:35:09.759424+00:00 (written)       "third link"  ← twin
  fylgja-test-readme/head          fylgja-test-readme  at 2026-10-17T04:35:08.687492+00:00 (head)          ""
```

A step with no `--stage` from here goes to the head, and is `unchanged`: the two bundles
differ in provenance alone, so nothing is pushed and the record moves to the head.

**Step back.** A step can go to any stage of the proposed change, backwards too. The
replace takes the third link's configuration off n1 and n3, and containerlab removes the
link:

```console
$ bin/fylgja twin step --stage fylgja-test-readme/seeded
…
  links: -n1:e1-3 — n3:e1-3
…
stepped to stage fylgja-test-readme/seeded (bundle b63404c3…) in 4.8s: reconcile 0.6s; push n1 2.8s, n3 2.8s; settled after 4.9s
```

`twin destroy` removes the twin as before, and the fixture tool's `-delete` removes the
stages, then the proposed change, then the branch: Infrahub refuses to delete a proposed
change while a stage names it, and a branch deleted first leaves its proposed change behind,
canceled. Not every step is this light. A cEOS node restarts in place when it is
re-cabled, and a changed image or kind recreates a node, so a step that needs either is
refused (`step.restart.required`, exit 1) until you pass `--allow-restart`. A step can go
to a stage of another proposed change, or to a snapshot of any branch, but never to one of
another scope or mapping than the twin's, which are fixed when it is created
(`step.twin.unsteppable`). A step that fails once it has started leaves the twin up and
`diverged` (exit 4), recorded with what each node was last known to hold, and a diverged
twin accepts only `twin destroy`.

## A proposed change, rehearsed

A stepping twin is driven by hand. A **rehearsal** makes the same moves unattended, through
every stage of a proposed change: it builds a twin at the first stage that compiles, the
**baseline**, and verifies it; steps it to each later stage in turn, verifying each; and
destroys it, whatever happens. A stage **passes** when its step lands and its verify finds
nothing the baseline did not already have, and the rehearsal stops at the first stage that
does not. `twin rehearse --branch <b>` runs one from the shell. Inside Infrahub, two checks
this repository ships run on every proposed change, when it is created and each time its
checks are run again:

- **`fylgja-step`** asks Fylgja for the plan, as `stage plan` prints it, in seconds, draft or
  not. Its message is the plan. It fails when a stage is refused, but for a branch point
  refused `scope.empty`, the scope selecting no device on `main`, which may hold untagged
  devices.
- **`fylgja-twin`** skips a draft. Otherwise it asks Fylgja to rehearse the proposed change,
  posts the report as a comment in a new thread on it, and concludes `success` when the
  rehearsal's status is `ok` and `failure` otherwise, which blocks the merge. Its message
  is the report's text.

Both are Python glue in `infrahub/checks/` and clients of the API: every verdict is the
server's, and Fylgja itself still writes nothing to Infrahub, the thread and its comment
being the check's one write ([D-049](docs/decisions.md#d-049),
[D-052](docs/decisions.md#d-052), [D-053](docs/decisions.md#d-053)).

**What the checks need.** Three things the walk-throughs above did not:

- **The checks, imported.** They reach Infrahub as the template does, through the
  registration `fylgja` in `.infrahub.yml`, from `origin`'s `main`
  ([docs/development.md](docs/development.md#local-environment)). A registration made after
  they were there has them. One made before needs
  `InfrahubReadOnlyRepositoryImportLastCommit` on the registration; both task workers then
  fetch the commit, about 15 seconds after the import's own run, before a re-run sees the
  checks. Read them back as `CoreCheckDefinition`: `fylgja-step`, timeout 300, and
  `fylgja-twin`, timeout 4260. A branch made before the import never runs them, so seed
  after it.
- **The server where the checks reach it.** The checks run in Infrahub's task workers, on
  Infrahub's own Compose network, where `127.0.0.1` is the container itself. So on the lab
  host the API's server also listens on the host's Docker bridge address (`172.17.0.1` by
  Docker's default), and the Compose override (`scripts/infrahub/docker-compose.override.yml`)
  gives the task workers that address, as `host.docker.internal:7650`, and the API's token
  from `local/.env`. The bring-up script starts the server so. The one the first
  walk-through started listens on loopback alone: stop it and start it on both addresses.
  Its report names both, and says the token crosses the bridge unencrypted. Any container on
  the host can reach that address, the twin's nodes included, and the token is what guards
  it; [SECURITY.md](SECURITY.md#the-threat-model) says what that means on a shared host.
- **A source branch named without a `/`.** Infrahub accepts a branch named `feature/x`,
  which a stage's reference cannot name (`stage.ref.invalid`). On such a branch's proposed
  change both checks conclude `failure` with that refusal in their message, `fylgja-step` at
  its creation and `fylgja-twin` once it is ready for review, and nothing is booted. Name a
  branch to rehearse without a `/`.

```sh
FYLGJA_STATE_ROOT=/var/tmp/fylgja bin/fylgja serve --listen 127.0.0.1:7650 --listen "$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'):7650" &
```

Start from a fresh fixture again, and open a draft. Its creation runs both checks:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete
deleted 2 stages, 1 proposed change, branch fylgja-test-readme
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme
schema loaded on fylgja-test-readme
three-node fixture seeded on fylgja-test-readme, with every artifact rendered and Ready
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -propose
proposed change 18e01843-9cb0-c335-33b3-c51c6053f556 opened on fylgja-test-readme, draft; 5 validators concluded in 53s
```

In Infrahub, under Proposed changes, open `fylgja-test-readme` and its Checks tab.
`Check: fylgja-twin` succeeded in 8 seconds without asking Fylgja anything, its message
`skipped: proposed change 18e01843-9cb0-c335-33b3-c51c6053f556 is a draft; mark it ready for
review and re-run the checks to rehearse it`. `Check: fylgja-step` succeeded too, in 18
seconds, its `Message` the plan of the two stages a proposed change has before any is
marked, the branch point refused for want of a network on `main`, then its findings:

```text
proposed change "fylgja-test-readme" (18e01843-9cb0-c335-33b3-c51c6053f556) on branch fylgja-test-readme → main, draft (2 stages), scope tag:fylgja
fylgja-test-readme/branch-point: refused (scope.empty)
  rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at 2026-10-20T01:21:38.649050Z
step fylgja-test-readme/branch-point → fylgja-test-readme/head (— → e26a0e65…): not computed (fylgja-test-readme/branch-point was refused)
fylgja-test-readme/head: branch fylgja-test-readme at 2026-10-20T01:21:59.327451+00:00 (head)
  snapshot_id …
  bundle_id e26a0e6578ce80add8f096da796187d56139f204e08cd13a1c9b32b7744f98ad
  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports
rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at 2026-10-20T01:21:38.649050Z
1 finding(s): 1 rejection, 0 warning, 0 info
```

Mark the two stages as before, then mark the proposed change ready for review, which runs
nothing by itself:

```sh
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -stage seeded -description seeded
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -add-link  # then wait for n1's and n3's checksums, as above (7 seconds here)
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -stage third-link -description "third link"
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -ready
```

**Run the checks again** from the proposed change's Checks tab. `fylgja-twin` takes as long
as the rehearsal and some 15 seconds more, to plan the stages and post the comment (88
seconds here, for a rehearsal of 71). From a shell, the fixture tool asks for the same
re-run and waits until both checks have concluded:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -run-checks user
check fylgja-step: success (message 2,027 characters)
check fylgja-twin: success (message 3,693 characters)
```

The comment is a thread in the proposed change's Overview, where Infrahub renders its table
and its drawing. Here are the Checks tab and the thread of the rehearsal recorded for
`v0.2.0`, whose branch point is the baseline on `main` ([D-054](docs/decisions.md#d-054)):

![A proposed change's Checks tab: Data Integrity, fylgja-step and fylgja-twin all succeeded](docs/recording/rehearsal-checks-passing.png)

![The rehearsal's thread in the proposed change's Overview: every stage passed, with the table, the drawing, the stages and the caveat](docs/recording/rehearsal-thread-passing.png)

The thread's markdown below is this walk-through's own rehearsal. It is headed by the run
and when the stages were resolved, so a later rehearsal's comment, a new one, is told from
it:

````markdown
## Fylgja rehearsed proposed change "fylgja-test-readme" on fylgja-test-readme, scope tag:fylgja

Run `fylgja-rehearse 01a156e8-da76-7743-9ca7-53c29d65ddc5`, stages resolved at 2026-10-20T01:24:14Z. Status **ok**. 70.7s of the 1950s deadline (ceiling 3600s).

| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |
|---|---|---|---|---|---|---|---|---|
| fylgja-test-readme/branch-point | 2026-10-20T01:21:38.649050Z | — | — | | | | | refused (scope.empty) |
| fylgja-test-readme/seeded | 2026-10-20T01:23:39.142559+00:00 | … | f278dcb6… | created | settled after 4.6s | 15 held, 0 failed, 0 skipped | — | baseline |
| fylgja-test-readme/third-link | 2026-10-20T01:23:48.370039+00:00 | … | 9827fe8f… | stepped 5.1s; push n1, n3 | settled after 5.7s | 19 held, 0 failed, 0 skipped | none | passed |
| fylgja-test-readme/head | 2026-10-20T01:23:46.627087+00:00 | … | 904addf9… | unchanged | settled after 5.9s | 19 held, 0 failed, 0 skipped | none | passed |

```mermaid
flowchart TD
  s0["fylgja-test-readme/branch-point<br/>refused"]
  s1["fylgja-test-readme/seeded<br/>baseline"]
  s2["fylgja-test-readme/third-link<br/>passed"]
  s3["fylgja-test-readme/head<br/>passed"]
  s0 -. "not computed" .-> s1
  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2
  s2 -- "unchanged" --> s3
```

**Stages** (Infrahub's view does not show them):

- `fylgja-test-readme/branch-point` main at 2026-10-20T01:21:38.649050Z (branch point)
- `fylgja-test-readme/seeded` fylgja-test-readme at 2026-10-20T01:23:39.142559+00:00 (written) "seeded"
- `fylgja-test-readme/third-link` fylgja-test-readme at 2026-10-20T01:23:48.370039+00:00 (written) "third link"
- `fylgja-test-readme/head` fylgja-test-readme at 2026-10-20T01:23:46.627087+00:00 (head)

**Warnings**: none

**Baseline findings** (reported, failing nothing): none

*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing.*
````

The drawing runs top to bottom, and a stage that failed or erred is outlined red. Below
the drawing the report lists the stages, with each one's branch, instant and description,
since Infrahub's own view of the proposed change shows none; the warnings; the baseline's
own findings, reported and failing nothing; and the caveat that a twin's fidelity is
asserted, not measured. A comment holds at most 4,092 bytes, all Infrahub keeps of one, so
a longer report, a failure's with many findings, names each finding by its identifier and
object alone and says so above the caveat. `fylgja-twin`'s message is the whole report as
text, as `twin rehearse` prints it. **The same rehearsal from the shell** needs no check
and no ready proposed change:

```console
$ bin/fylgja twin rehearse --branch fylgja-test-readme
rehearsal of proposed change "fylgja-test-readme" (18e01843-9cb0-c335-33b3-c51c6053f556) on branch fylgja-test-readme: 4 stages; deadline 32m30s (ceiling 1h0m0s), scope tag:fylgja
fylgja-test-readme/branch-point: refused (scope.empty)
  rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at 2026-10-20T01:21:38.649050Z
fylgja-test-readme/seeded: branch fylgja-test-readme at 2026-10-20T01:23:39.142559+00:00 (written), "seeded"; baseline
fylgja-test-readme/third-link: branch fylgja-test-readme at 2026-10-20T01:23:48.370039+00:00 (written), "third link"
fylgja-test-readme/head: branch fylgja-test-readme at 2026-10-20T01:23:46.627087+00:00 (head)
run fylgja-rehearse 01a156ea-612c-7982-a098-6825eedadb09
stage fylgja-test-readme/seeded: creating the twin
run fylgja-provision 01a156ea-61f8-75a1-8979-1a531b5ad6aa
…
stage fylgja-test-readme/seeded: verify: settled after 4.9s (1 read)
stage fylgja-test-readme/third-link: stepping
run fylgja-step 01a156eb-29eb-713e-9d3d-fa436e8e2b0e
…
stage fylgja-test-readme/head: stepping
run fylgja-step 01a156eb-555b-79f9-a1ee-517828abde9e
…
destroying the twin
run fylgja-destroy 01a156eb-724d-70c9-a6a1-5be1450ce34b
…
removed lab fylgja (3 containers)
removed twin directory /var/tmp/fylgja/twin
stage fylgja-test-readme/branch-point: refused (scope.empty)
stage fylgja-test-readme/seeded: created; settled after 4.9s (1 read); 15 held, 0 failed, 0 skipped; baseline
stage fylgja-test-readme/third-link: stepped in 4.7s (push n1 2.6s, n3 2.7s); settled after 6.2s (1 read); 19 held, 0 failed, 0 skipped; passed
stage fylgja-test-readme/head: unchanged in 1.1s; settled after 6.0s (1 read); 19 held, 0 failed, 0 skipped; passed
rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 72.1s of the 1950s deadline
```

It took 83 seconds end to end, and wrote nothing to Infrahub: the comment is the check's.

`--markdown` prints the comment's markdown alone, and `--json` the document. There is one
twin at a time: a rehearsal is refused while a run is in flight or a twin stands
(`run.in_flight`, `host.twin.present`), and `fylgja-twin` asks again every 30 seconds while
what remains of its own deadline still covers the rehearsal it would start. A rehearsal's own deadline is the sum of its stages' budgets, under a
ceiling of an hour. A stage that **fails** stops the rehearsal there, its step diverged or its verify
finding what the baseline did not have: the report says why, the stages after it read `not
reached`, the twin is destroyed all the same, and the comment ends with the commands that
reproduce it by hand, one `twin create`, a `twin step` for each stage up to the failed one,
`twin verify` and `twin destroy`. The rehearsal ends `nonconforming`, exit 5, and
`fylgja-twin` fails. Tier 3's case 9 makes one, with a port n1 does not have, refused at the
push. The recording's has a port n4 does not have; its stage is outlined red in the drawing:

![The Checks tab after a failing rehearsal: fylgja-twin failed](docs/recording/rehearsal-checks-failing.png)

![The failing rehearsal's thread: the stage bad-port failed at the push, head not reached, the findings and the commands that reproduce it](docs/recording/rehearsal-thread-failing.png)

`-delete` removes the stages first, since Infrahub refuses to delete a proposed change while
a stage names it, then the proposed change, whose threads, their comments and its checks go
with it, then the branch:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete
deleted 2 stages, 1 proposed change, branch fylgja-test-readme
```

## Two vendors, one twin

A platform is a **platform support package**: one YAML file that says how a vendor's
production interface names map onto a lab image, how to tell when a node is ready, and
how to push its configuration. The compiler has no vendor branch
([D-031](docs/decisions.md#d-031)). Here a twin of two cEOS nodes and one SR Linux node
compiles from a snapshot on disk, with no Infrahub and no workflow service: the command
sends the snapshot to the API's server, which compiles its CTM and sends the bundle back
to be written on your disk, filing nothing:

```console
$ bin/fylgja twin compile --snapshot testdata/snapshot/mixed.json --out /tmp/mixed
wrote bundle to /tmp/mixed (3 nodes, 3 links)
snapshot_id 37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf
bundle_id ecb665f58ffc9882024a06e29b01e681ee38ce40f55b76994d470fe3272a2aec
warning artifact.interface.unrepresented e1:Management1: artifact device-config names interface Management1 at line 10, which the node calls Management0; the line is pushed as production wrote it
…
$ sed -n '/links:/,$p' /tmp/mixed/topology.clab.yml
  links:
    - endpoints: ["e1:eth1", "s1:e1-1"]
    - endpoints: ["e1:eth2_1", "e2:eth1"]
    - endpoints: ["e2:eth3_1_1", "s1:e1-2"]
```

Production's `Ethernet2/1` and `Ethernet3/1/1` become containerlab's `eth2_1` and
`eth3_1_1`, and the node still calls them by their production names. Where a lab image
can't carry what production has (a port it doesn't have, a management name it spells
differently), the bundle records it as a lossy mapping, an omission or a warning, or the
compile refuses. Nothing is dropped silently. Provisioned, each node is probed, pushed and read back over its own package's
transport: gNMI over TLS and JSON-RPC for SR Linux, plaintext gNMI and eAPI for EOS.
[psp/README.md](psp/README.md) records which packages have passed the conformance suite
against a live twin.

## The stages on their own

`twin create` runs every stage for you: the API's server reads the branch, takes and files
the snapshot, compiles it and files the bundle, then one durable run boots the twin from
the host check on. Each stage is also a command, so you can stop anywhere and look. Like
every command, each is a request to a running `fylgja serve`, and is checked against the
server's packages:

```sh
fylgja schema check  --branch B                           # is the branch's DCIM the one the reader reads? reads nothing else
fylgja intent read   --branch B [--at T] [--scope tag:S] --out snapshot.json
                                                          # the validated intent of the devices tagged S, as a snapshot
fylgja twin compile  --snapshot snapshot.json --out bundle/
                                                          # the pure compiler: same snapshot, same bytes
fylgja twin provision bundle/                             # boot a bundle
fylgja psp validate  psp/*.yaml                           # check platform support packages
```

The files are yours, on the machine the command runs on. `intent read --out` writes the
snapshot the server took of what it read, and files it in the server's store too; `twin
compile` sends a snapshot and writes the bundle the server compiled to `--out`, on your
disk, byte for byte what the golden tests compare. A bare CTM compiles once wrapped:
`{"snapshot_version": "1", "ctm": <the CTM>, "probes": []}`, its id and `observed_at`
left for the server to fill. `--ctm` is retired.
`twin provision` sends the bundle directory's files, which the server verifies and files
in its store on the lab host before it boots them, and `psp validate` sends each package.
`psp validate` and `twin compile` need neither Infrahub nor the workflow service, but they
do need the server. A snapshot or a bundle a dry run or a plan files stays in the lab
host's stores.

`fylgja` only ever reads from Infrahub (the fixture tool is the one thing that writes). Every refusal is reported in one pass, each as a
finding with a stable rule name (`device.name.duplicate`, `host.image.absent`, …), and
a refused read writes nothing; a refused compile leaves only the snapshot it took. Every
command takes `--json` for one machine-readable findings document. Exit statuses:

| Code | Meaning |
|---|---|
| `0` | done: the twin is ready, the destroy is done, or the dry run is clear (warnings allowed) |
| `1` | refused before the host was touched: bad intent, a host check refusal, a twin already there |
| `2` | could not run: bad flags, no workflow service, no worker, Infrahub unreachable, the API unreachable or its token refused (`api.unreachable`, `api.token.refused`, `api.version.unknown`, `api.transfer.too_large`) |
| `3` | the run failed or was cancelled after the host check, and cleaned up completely |
| `4` | the run failed and something remains on the host; the report says what, and how to clear it. A step that failed leaves the twin up, `diverged` |
| `5` | `twin verify` read every node, and the twin does not conform to its intent: `nonconforming` |

## Tests

```sh
make test            # tier 1: unit, golden, workflow and replay tests, every command through a server in the test's process; no infrastructure, seconds
make test-contract   # tier 2: against a real Infrahub; needs local/.env
make test-e2e        # tier 3: nine cases and nine live twins, SR Linux and EOS, every command through a server of its own, and a proposed change rehearsed by the checks inside Infrahub; never in CI
make lint
```

CI ([ci.yml](.github/workflows/ci.yml), the badge above) runs three jobs on GitHub's hosted
Ubuntu 26.04 runner. The **lint** job and the **unit** job run on every push to `main` and
every pull request: the first runs the linter and shellcheck over both scripts, the second
the build and tier 1. The **contract** job runs on pushes to `main` alone, after both: it
brings up a real Infrahub on the runner with the script's Infrahub part, checks the
committed GraphQL client against the committed SDL, and runs tier 2. It needs no secret:
the script makes Infrahub's token on the runner and never prints it.

Tier 3 boots twins, so it is the operator's, on a lab host, and never runs in CI. It needs
the dev server and a worker running from the repository root (the script leaves both),
Docker, containerlab, Infrahub and both images, and for case 9 the two checks imported and
the API's server from the same tree on the Docker bridge, as [A proposed change,
rehearsed](#a-proposed-change-rehearsed) starts it; it refuses before any case without
them. It takes about 31.5 minutes (1,894.1 s on 2026-10-28), among them case 5's five and
a half minutes of watching a twin that must not move. Without the cEOS image it refuses
before any case too; `PLATFORMS` narrows it to the packages you name, and on an SR
Linux-only host it ends on a partial pass, exit 0:

```console
$ PLATFORMS=nokia_srlinux make test-e2e
…
E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7 9; skipped 6 (needs arista_eos: not in PLATFORMS; image ceos:4.32.0.2F absent) 8 (needs arista_eos: not in PLATFORMS; image ceos:4.32.0.2F absent)
```

Cases 6 and 8 build mixed twins, and each skip says why. A narrowed run takes about 19
minutes, leaves the host as clean as a full one, and never prints `E2E-OK` when it skipped
a case.

## Where to read next

- [docs/brief.md](docs/brief.md): what Fylgja is for, and what it deliberately is not
- [docs/architecture.md](docs/architecture.md): the pipeline, the workflows and the contracts between stages, with its diagrams
- [docs/decisions.md](docs/decisions.md): every decision, and the alternatives rejected
- [docs/glossary.md](docs/glossary.md): the terms used above
- [docs/development.md](docs/development.md): environment, layout, conventions, test tiers
- [docs/verified-facts.md](docs/verified-facts.md): how Infrahub, containerlab, the network operating systems and Temporal were found to behave, with versions and dates
- [psp/README.md](psp/README.md): the platform support package format, and which packages are supported
- [schema/README.md](schema/README.md): the mapping the reader reads Infrahub by, `schema check`, and how to mark a stage
- [contracts/](contracts/): the CLI, the API and every format, as the tests hold them

## Contributing

This repository is read-only. Issues are welcome; pull requests are not taken.

## License

Apache License 2.0; the text is in `LICENSE`.
