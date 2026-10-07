# Fylgja

Fylgja builds a **walking twin** of a network from its intent. You name a branch in
[Infrahub](https://github.com/opsmill/infrahub), and optionally a point in time. Fylgja
reads it, compiles it into a deterministic bundle, and boots it as a running
[containerlab](https://containerlab.dev) topology on real network operating system
images. Then it pushes each device's production configuration as Infrahub rendered it.
If the branch changes, the twin rebuilds itself to match. Provisioning runs through
[Temporal](https://temporal.io), so a create that fails or is cancelled cleans up after
itself; state lives in containerlab, a few files and Temporal, and there is no database.
There is one twin at a time, on one lab host. Every command is a request to Fylgja's API,
which `fylgja serve` answers on the lab host, so a shell that holds the API's token alone
can drive the twin, from the lab host or through an SSH tunnel from another machine.
Milestones M1–M7 and M10–M13 are built, and the [roadmap](docs/roadmap.md) says what
each delivered and what comes next.

Today it runs Nokia SR Linux and Arista EOS, alone or mixed in one twin. A vendor is a
YAML file, not code ([psp/README.md](psp/README.md)). A twin built from a waypoint can
step to the next one without a rebuild, and `twin verify` reports whether the running twin
matches its intent.

## Built with an AI agent

Fylgja was built with Claude, an AI agent, working through the
[Spec Kit](https://github.com/github/spec-kit) workflow, with a human deciding every
question of scope and design. The record of how it was built (the specifications, plans,
research and command logs) is private; this repository holds the result.

## What it needs

| | |
|---|---|
| Go 1.26, `make` | to build. `make build` → `bin/fylgja`, one static binary: the commands, the worker and the API's server |
| Docker and containerlab 0.79 | on the lab host. The SR Linux image is pulled. The cEOS image is **account-gated**: you download it from Arista and `docker import` it; Fylgja never pulls it |
| Temporal | `make temporal-dev` starts a file-backed dev server on `:7233` |
| Infrahub 1.11.2 | operator-provided. Fylgja reads intent and each device's configuration from it, and never writes to it. Its `main` needs Fylgja's schema (`schema/`), the empty group `fylgja-devices`, and this repository registered as a read-only repository, so that Infrahub renders each device's `device-config` artifact from the template here (`.infrahub.yml`, `infrahub/`) |
| `local/.env` | the Infrahub address and token, each platform's node login, and the API's token (`FYLGJA_API_TOKEN`), which the server and every command share. Fylgja reads the process environment only, and never prints, logs or stores a credential ([.env.example](.env.example)) |

[docs/development.md](docs/development.md#local-environment) walks through each of these,
including the cEOS import, registering the template and seeding the Infrahub fixture.

## A walking twin, start to finish

This is a real session on one lab host, with Infrahub running beside it. Each step's
`begins` line is left out, and other trimmed lines are marked `…`. Start the workflow
service, the worker, which runs on the lab host and does everything that touches it, and
the API's server beside it, which every command below talks to. The two roles share one
state root, here `/var/tmp/fylgja`; any absolute directory both can write will do:

```sh
set -a; . local/.env; set +a     # Infrahub, the node logins and FYLGJA_API_TOKEN
make build                       # once: both roles below run this binary
make temporal-dev &              # the workflow service
mkdir -p /var/tmp/fylgja         # the state root: the bundle store and the twin directory
FYLGJA_STATE_ROOT=/var/tmp/fylgja bin/fylgja worker run &   # the lab host worker: prints what it will run, and what's on the host
FYLGJA_STATE_ROOT=/var/tmp/fylgja bin/fylgja serve &        # the API's server on 127.0.0.1:7650: prints where it listens, its state root and packages
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

**Create the twin.** Fylgja reads the branch, compiles it, checks the host, deploys, waits
for every node to answer, pushes each artifact, and records what it built:

```console
$ bin/fylgja twin create --branch fylgja-test-readme --interval 15s
run fylgja-provision 01a112a2-7ee6-7772-a701-af726d528abc
step read: done in 3.0s
step compile: done in 0.0s (bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee)
step host check: done in 0.1s
step follow: done in 0.0s
step stage: done in 0.0s
step deploy: done in 41.3s (3 nodes)
step readiness n1: ready in 0.3s
step readiness n2: ready in 0.3s
step readiness n3: ready in 0.4s
step push n2: done in 2.3s
step push n1: done in 2.4s
step push n3: done in 2.5s
step record: done in 0.0s
step follow: done in 0.1s
twin ready: bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee
  n1  172.20.20.3
  n2  172.20.20.4
  n3  172.20.20.2
twin directory /var/tmp/fylgja/twin
following branch fylgja-test-readme, checked every 15s (schedule fylgja-follow)
warning host.memory.unbudgeted [step host_check] host: sum 6144 MiB (n1 2048, n2 2048, n3 2048) is not checked against a host budget: FYLGJA_HOST_MEMORY_MB is unset
1 finding(s): 0 rejection, 1 warning, 0 info
```

Nearly all of the time is containerlab booting three SR Linux nodes, and it depends on
how busy the host is. A second `twin create` is refused, naming this twin.

**Look at it.** `twin show` reads containerlab, the record and the workflow service, and
changes nothing:

```console
$ bin/fylgja twin show
twin: lab fylgja present (3 nodes); twin directory present
  n1  clab-fylgja-n1  running  172.20.20.3  nokia_srlinux  device-config f05634801639578ed97c10f9d0265546
  n2  clab-fylgja-n2  running  172.20.20.4  nokia_srlinux  device-config 36667eef6c8a92923957b9549784273b
  n3  clab-fylgja-n3  running  172.20.20.2  nokia_srlinux  device-config 7efd0c0d5f40e5119d75b8b8d31d3e57
record: branch fylgja-test-readme, bundle_id 777e9899213110875f41da982d2a19f9ba683331da223dd2b418f169dd534bee, schema 4d5b37aa0a894aec4cdca69fdb9fe455, contract 0.2
  intent read at 2026-10-06T19:13:21.796364Z; reproducing it with --at that instant is best-effort
  provisioned by run fylgja-provision 01a112a2-7ee6-7772-a701-af726d528abc (source intent), worker 0.1.0-dev, recorded 2026-10-06T19:14:09.579682296Z, 3 nodes
kind: following branch fylgja-test-readme, checked every 15s
  next check: 2026-10-06T19:14:30Z
  a rebuild discards the twin's runtime state
in flight: check fylgja-reconcile-2026-10-06T19:14:15Z at step read
```

The nodes are real. `twin verify` asks each one over its own package's transport whether
it is what intent says: its host name, every cabled port enabled, and every link seen as
an LLDP neighbour from both ends. It also reports what the record says each node holds,
labelled as the record's claim. It needs no worker and changes nothing:

```console
$ bin/fylgja twin verify
twin: branch fylgja-test-readme (bundle 777e9899…), ready; 3 nodes
staged: bundle 777e9899…; 15 assertions over 3 nodes, 0 skipped
n1 (172.20.20.3:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2; record: holds 777e9899…
n2 (172.20.20.4:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds 777e9899…
n3 (172.20.20.2:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2; record: holds 777e9899…
skipped: none
in flight: check fylgja-reconcile-2026-10-06T19:14:15Z at step read
held: 3 host names, 6 ports, 6 link ends, 3 record claims (the record's, not read); failed: none; unread: none
```

A port disabled by hand outside Fylgja draws three findings (its own state and both ends'
neighbours) and exit 5, `nonconforming`; `--wait` reads again until the twin settles.

**Change the branch.** Every 15 seconds a check reads and compiles the branch and compares
the result with the twin. While nothing changes, it touches nothing:

```console
  last check: fylgja-reconcile-2026-10-06T19:14:45Z at 19:14:46Z, unchanged
```

Now disable n1's `ethernet-1/2` in Infrahub and have it re-render the artifacts. Infrahub
1.11 doesn't regenerate them on its own, so the fixture tool asks it to:

```console
$ go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -disable-port n1:ethernet-1/2 -generate
interface ethernet-1/2 on n1 disabled on fylgja-test-readme
artifacts rendered and Ready on fylgja-test-readme
```

With no further command, a check sees a new `bundle_id` and rebuilds the twin: a destroy
and a create, about as long as the first. The fixture tool can return before Infrahub has
rewritten an artifact, so here the 19:15:00Z check read the disabled port beside n1's old
artifact and rebuilt to that, and the 19:16:00Z check read the new artifact and rebuilt
again. Only n1's artifact moved:

```console
$ bin/fylgja twin show
twin: lab fylgja present (3 nodes); twin directory present
  n1  clab-fylgja-n1  running  172.20.20.4  nokia_srlinux  device-config cf9fe341574d6bd1f8d9a2f721429d6f
  n2  clab-fylgja-n2  running  172.20.20.2  nokia_srlinux  device-config 36667eef6c8a92923957b9549784273b
  n3  clab-fylgja-n3  running  172.20.20.3  nokia_srlinux  device-config 7efd0c0d5f40e5119d75b8b8d31d3e57
record: branch fylgja-test-readme, bundle_id e26f042ab5e63d1e6815544da7639bdc22cfc3fd1343512d10a0757b535faa59, …
…
kind: following branch fylgja-test-readme, checked every 15s
  last check: fylgja-reconcile-2026-10-06T19:16:00Z at 19:16:45Z, rebuilt
…
$ bin/fylgja twin verify
twin: branch fylgja-test-readme (bundle e26f042a…), ready; 3 nodes
staged: bundle e26f042a…; 15 assertions over 3 nodes, 3 skipped
n1 (172.20.20.4:57400, nokia_srlinux): host name n1; ethernet-1/1 enabled; neighbour n2 ethernet-1/1; record: holds e26f042a…
n2 (172.20.20.2:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds e26f042a…
n3 (172.20.20.3:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbour n2 ethernet-1/2; record: holds e26f042a…
skipped: n1:ethernet-1/2 (intent disables it); link n1:ethernet-1/2|n3:ethernet-1/2 at both ends (intent disables n1:ethernet-1/2)
in flight: check fylgja-reconcile-2026-10-06T19:17:30Z at step read
held: 3 host names, 5 ports, 4 link ends, 3 record claims (the record's, not read); failed: none; unread: none
```

Intent now disables `n1:ethernet-1/2`, and the artifact says so, so verify skips that port
and its link rather than expecting them up, and names what it skipped. Tier 3 makes the same change and reads it to the same
counts.

**Destroy it.** Following stops first. A check in flight is cancelled and waited for;
here none was:

```console
$ bin/fylgja twin destroy
following of branch fylgja-test-readme stopped
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

## A stepping twin

A walking twin keeps up with its branch by rebuilding: a destroy and a create, about a
minute each time here. A twin built from a **waypoint** steps instead. A waypoint is a
named, pinned reference into a branch, `<series>/<sequence>`, which you write in Infrahub
after the changes it marks ([schema/README.md](schema/README.md) says how). `twin step`
takes the running twin to another waypoint of its series and changes only what differs:
containerlab re-cables the running lab, and only the nodes whose configuration moved are
pushed. The push is a replace, so whatever the new waypoint drops is removed from the node.
Same host, same services, `begins` lines left out as before.

Start from a fresh fixture, since the walking twin's branch still has the port disabled.
The fixture tool writes test series (their names begin `fylgja-test-`). Write `/1`, add a
third link, wait for n1's and n3's artifacts to be re-rendered (their checksums move in
Infrahub, here after about 8 seconds), then write `/2`:

```sh
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete    # the branch and its test series
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme            # seed it again
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -waypoint fylgja-test-readme/1 -description seeded
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -add-link  # n1:ethernet-1/3 <-> n3:ethernet-1/3
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -waypoint fylgja-test-readme/2 -description "third link"
```

If the seed answers `graphql: None` straight after the delete, run it again before writing
`/1`: Infrahub 1.11.2 can refuse to create a branch just after one of the same name was
deleted ([verified facts](docs/verified-facts.md#infrahub-1112)).

**Plan the series.** `waypoint plan` reads and compiles every waypoint and shows what each
step between them would change. It needs no lab and no worker:

```console
$ bin/fylgja waypoint plan --series fylgja-test-readme
series fylgja-test-readme (2 waypoints)
fylgja-test-readme/1: branch fylgja-test-readme at 2026-10-07T11:52:21.501002+00:00 (written), "seeded"
  bundle_id f857d51352836db586f6f1089ec9ca3324cc4bac05fb3a7badbb3cb37aec15d1
  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports
step fylgja-test-readme/1 → fylgja-test-readme/2 (f857d513… → 7eafd93c…):
  nodes: ~n1 (bootstrap, mapping); ~n3 (bootstrap, mapping)
  links: +n1:e1-3 — n3:e1-3
  artifacts: n1 device-config f0563480… → a5d72b0d…; n3 device-config 7efd0c0d… → 01125980…
fylgja-test-readme/2: branch fylgja-test-readme at 2026-10-07T11:52:51.233406+00:00 (written), "third link"
  bundle_id 7eafd93cc5a8ebdac69656dac4b4793d3351202a4cdbc929f744bff4ac3ac855
  read: 3 devices (nokia_srlinux 3), 14 interfaces, 4 links, 3 artifacts, 0 lossy mappings, 0 shared ports
```

**Create the twin at `/1`.** It is the same run as the walking twin's, pinned at the
waypoint's instant, and it never follows:

```console
$ bin/fylgja twin create --waypoint fylgja-test-readme/1
waypoint fylgja-test-readme/1: branch fylgja-test-readme at 2026-10-07T11:52:21.501002+00:00 (written), "seeded"
run fylgja-provision 01a11635-d5b5-7c3c-8df0-9dd946eb34bb
…
step deploy: done in 36.2s (3 nodes)
…
twin ready: bundle_id f857d51352836db586f6f1089ec9ca3324cc4bac05fb3a7badbb3cb37aec15d1
…
pinned at 2026-10-07T11:52:21.501002+00:00, not following
```

**Step it.** With no `--waypoint`, `twin step` goes to the next waypoint of the series.
`--dry-run` makes every check the step makes, including containerlab's own plan for the
running lab, and touches nothing:

```console
$ bin/fylgja twin step --dry-run
dry run: no lab, container, twin directory or run is changed
twin: waypoint fylgja-test-readme/1 (bundle f857d513…), pinned at 2026-10-07T11:52:21.501002+00:00; 3 nodes
waypoint fylgja-test-readme/2: branch fylgja-test-readme at 2026-10-07T11:52:51.233406+00:00 (written), "third link"
step fylgja-test-readme/1 → fylgja-test-readme/2 (f857d513… → 7eafd93c…):
  nodes: ~n1 (bootstrap, mapping); ~n3 (bootstrap, mapping)
  links: +n1:e1-3 — n3:e1-3
  artifacts: n1 device-config f0563480… → a5d72b0d…; n3 device-config 7efd0c0d… → 01125980…
reconcile: live n1 (nokia_srlinux declares live); live n3 (nokia_srlinux declares live)
push: n1 (artifact, bootstrap); n3 (artifact, bootstrap); n2 untouched
wait: after the record, until the twin conforms, at most 2m0s
memory: sum 6144 MiB; host budget unset
host: lab fylgja present; twin directory present
verdict: clear
…
$ bin/fylgja twin step
…
run fylgja-step 01a11636-a6ad-767f-8fb9-8918c890ca50
step inspect: done in 0.2s
step host check: done in 0.2s
step plan reconcile: done in 0.3s (live n1, n3)
step stage: done in 0.0s
step reconcile: done in 0.6s (3 nodes)
step push n1: done in 2.5s
step push n3: done in 2.5s
step record: done in 0.0s
step observe: settled after 5.7s (1 read)
stepped to waypoint fylgja-test-readme/2 (bundle 7eafd93c…) in 4.1s: reconcile 0.5s; push n1 2.4s, n3 2.5s; settled after 5.7s
…
```

The step took 4.1 seconds where a rebuild takes about a minute. SR Linux takes the new link
live, so no container restarted (each still had the create's start time), n2 was neither
touched nor pushed, and n1 and n3 were pushed their new artifacts by replace. After its
record the run waits, as `twin verify --wait` would, until the twin conforms to its new
intent; here the first read already did. `twin verify` sees the new link from both ends:

```console
$ bin/fylgja twin verify
twin: waypoint fylgja-test-readme/2 (bundle 7eafd93c…), ready, pinned at 2026-10-07T11:52:51.233406+00:00; 3 nodes
staged: bundle 7eafd93c…; 19 assertions over 3 nodes, 0 skipped
n1 (172.20.20.3:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2, ethernet-1/3 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2, n3 ethernet-1/3; record: holds 7eafd93c…
n2 (172.20.20.4:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds 7eafd93c…
n3 (172.20.20.2:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2, ethernet-1/3 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2, n1 ethernet-1/3; record: holds 7eafd93c…
skipped: none
in flight: none
held: 3 host names, 8 ports, 8 link ends, 3 record claims (the record's, not read); failed: none; unread: none
$ bin/fylgja waypoint list
series fylgja-test-readme (2 waypoints)
  fylgja-test-readme/1  branch fylgja-test-readme  at 2026-10-07T11:52:21.501002+00:00 (written)  "seeded"
  fylgja-test-readme/2  branch fylgja-test-readme  at 2026-10-07T11:52:51.233406+00:00 (written)  "third link"  ← twin
```

**Step back.** A step can go to any waypoint of the series, backwards too. The replace
takes the third link's configuration off n1 and n3, and containerlab removes the link:

```console
$ bin/fylgja twin step --waypoint fylgja-test-readme/1
…
  links: -n1:e1-3 — n3:e1-3
…
stepped to waypoint fylgja-test-readme/1 (bundle f857d513…) in 4.7s: reconcile 0.5s; push n1 3.0s, n3 2.9s; settled after 5.0s
…
```

`twin destroy` removes the twin as before, and the fixture tool's `-delete` removes the
branch and its series. Not every step is this light. A cEOS node restarts in place when
it is re-cabled, and a changed image or kind recreates a node, so a step that needs either
is refused (`step.restart.required`, exit 1) until you pass `--allow-restart`. A step that
fails once it has started leaves the twin up and `diverged` (exit 4), recorded with what
each node was last known to hold, and a diverged twin accepts only `twin destroy`.

## Pinned and frozen twins

Following the branch is the default. Three other kinds of twin never rebuild:

- `twin create --branch B --at 2026-09-20T12:00:00Z` builds the branch **as it was at
  that instant**: a pinned twin. Pinned reads are reproducible, so the same reference
  compiles to the same `bundle_id` even after the branch moves on.
- `twin create --branch B --no-follow` builds the branch head **once**, as a frozen twin.
- `twin provision <bundle-dir>` boots a bundle you already have, with no read at all.

`--dry-run` on `create` and `provision` reads, compiles, files the bundle and checks the
host, then stops before starting a run.

## Two vendors, one twin

A platform is a **platform support package**: one YAML file that says how a vendor's
production interface names map onto a lab image, how to tell when a node is ready, and
how to push its configuration. The compiler has no vendor branch
([D-031](docs/decisions.md#d-031)). Here a twin of two cEOS nodes and one SR Linux node
compiles from a snapshot on disk, with no Infrahub and no workflow service: the command
sends the CTM to the API's server, which compiles it and sends the bundle back to be
written on your disk:

```console
$ bin/fylgja twin compile --ctm testdata/ctm/mixed.json --out /tmp/mixed
wrote bundle to /tmp/mixed (3 nodes, 3 links)
bundle_id 391bcb96c39e7e878fa6ba78ac869742b04f517fa914e2fce51c3ea4944dd3cb
warning artifact.interface.unrepresented e1:Management1: artifact device-config names interface Management1 at line 12, which the node calls Management0; the line is pushed as production wrote it
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

`twin create` runs every stage inside one durable run. Each one is also a command, so you
can stop anywhere and look. Like every command, each is a request to a running `fylgja
serve`, and is checked against the server's packages:

```sh
fylgja schema check  --branch B                           # does the branch conform? reads nothing else
fylgja intent read   --branch B [--at T] --out ctm.json   # the validated intent snapshot (CTM)
fylgja twin compile  --ctm ctm.json --out bundle/         # the pure compiler: same CTM, same bytes
fylgja twin provision bundle/                             # boot a bundle
fylgja psp validate  psp/*.yaml                           # check platform support packages
```

The files are yours, on the machine the command runs on. `intent read --out` writes the
CTM the server read, and `twin compile` sends the CTM and writes the bundle the server
compiled to `--out`, on your disk, byte for byte what the golden tests compare.
`twin provision` sends the bundle directory's files, which the server verifies and files
in its store on the lab host before it boots them, and `psp validate` sends each package.
`psp validate` and `twin compile` need neither Infrahub nor the workflow service, but they
do need the server. A bundle a dry run or a plan files stays in the lab host's store.

`fylgja` only ever reads from Infrahub (the fixture tool is the one thing that writes). Every refusal is reported in one pass, each as a
finding with a stable rule name (`device.name.duplicate`, `host.image.absent`, …), and
a refused read or compile writes nothing. Every command takes `--json` for one
machine-readable findings document. Exit statuses:

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
make test-e2e        # tier 3: eight cases and eight live twins, SR Linux and EOS, every command through a server of its own; never in CI
make lint
```

## Where to read next

- [docs/brief.md](docs/brief.md): what Fylgja is for, and what it deliberately is not
- [docs/architecture.md](docs/architecture.md): the pipeline, the workflows and the contracts between stages, with its diagrams
- [docs/decisions.md](docs/decisions.md): every decision, and the alternatives rejected
- [docs/glossary.md](docs/glossary.md): the terms used above
- [docs/development.md](docs/development.md): environment, layout, conventions, test tiers
- [docs/verified-facts.md](docs/verified-facts.md): how Infrahub, containerlab, the network operating systems and Temporal were found to behave, with versions and dates
- [psp/README.md](psp/README.md): the platform support package format, and which packages are supported
- [schema/README.md](schema/README.md): the schema contract, and how to write a waypoint
- [contracts/](contracts/): the CLI, the API and every format, as the tests hold them

## Contributing

This repository is read-only. Issues are welcome; pull requests are not taken.

## License

Apache License 2.0; the text is in `LICENSE`.
