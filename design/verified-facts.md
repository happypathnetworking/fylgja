# Verified facts

A **verified fact** is something about a dependency that was checked against the running
system, not taken from its documentation or from memory: how containerlab, clabernetes,
kind, a network operating system, Docker, GitHub's runner or the host actually behaves.

This file holds the facts the core relies on: its runtimes, the nodes it boots, the probes
it runs on a twin and the hosts it runs on. Facts about Infrahub, Prefect and NetBox are
kept with the orchestrator, which reads them, in the archived repository until it moves
here.

- Each fact names the version it was verified against and the date.
- **Re-verify a fact on any upgrade** of the system it names.
- **A fact recorded here is trusted over recollection.** Before a change depends on a
  behaviour that is not here, verify it and add it
  ([how a change is made](../CONTRIBUTING.md#how-a-change-is-made)).

Terms are the [glossary](../docs/glossary.md)'s. Dates are written in full, `YYYY-MM-DD`.
- A date alone up to 2026-10-08 is a verification on Ubuntu 24.04.1; a later one is on Ubuntu
  26.04.
- *(26.04, 2026-10-08)* beside an earlier date is a re-verification on Ubuntu 26.04 on that
  date.

---

## containerlab 0.79.0

The development host moved to containerlab 0.81.0 on 2026-11-03, the version clabernetes
0.10.1 embeds, so that both drivers run one containerlab. The facts below were verified on
0.79.0 and stand until each is re-exercised on 0.81.0, which phase 4 does as it builds the
local driver; a fact re-verified there gets a *(0.81.0, date)* mark.

**Deploy, inspect and destroy**

- `clab deploy` creates `clab-<lab>/` beside the topology file, or under
  `CLAB_LABDIR_BASE` when it is set, mostly root-owned; `clab destroy --cleanup` removes
  it without root in about 1 s. *(2026-09-15; 26.04, 2026-10-08; 0.81.0, 2026-11-03)* On
  0.81.0 the destroy of a two-node lab took 1.26–1.4 s, eight times, once after a failed
  deploy; the directory itself is root's, and `destroy -t <file> --cleanup`
  removed it with a three-node lab in 1.5 s.
- **A one-SR Linux, one-cEOS lab joined by one link deploys in 49.1–55.5 s** (five
  deploys, an otherwise idle host). The same two nodes with no link took 87.6 s, the cEOS
  node's post-deploy holding the deploy for 84 s. *(0.81.0, 2026-11-03)*
- containerlab applies an SR Linux `.cli` startup snippet over the default configuration
  and commits it itself, so the snippet carries no `commit` line; LLDP and gNMI are on by
  default. *(0.77, 2026-09-15; 26.04, 2026-10-08)*
- **No startup-config means the kind's baseline.** *(2026-10-30; 0.81.0, 2026-11-03: the local
  driver's plan renders no startup-config, and every push of phase 4's live runs, the
  end-to-end test's three SR Linux nodes and the push lab's SR Linux and cEOS nodes,
  replaced onto the baseline and landed)*
  - SR Linux 24.7.1 holds hostname = node name, linked ports enabled, LLDP with
    neighbours, gNMI and JSON-RPC.
  - cEOS 4.32.0.2F holds the hostname, ports connected, LLDP on every port
    (`Management0` included) and gNMI on 6030.
  - On both, all of it survives the replace push (`load startup`, and `rollback
    clean-config` with `copy startup-config session-config`) and a repeat push.
- `inspect --all --format json` gives each container's `absLabPath`, always absolute;
  `labPath` is relative to the caller's directory when the topology file is under it, so
  decode `absLabPath`. *(2026-09-16; 26.04, 2026-10-08)*
- **`inspect -t <file> --format json`** prints on stdout an object mapping the lab's name
  to one entry per container, its log on stderr, in 0.12–0.24 s. *(0.81.0, 2026-11-03)*
  - An entry's members are `lab_name`, `labPath`, `absLabPath`, `name`, `container_id`,
    `image`, `kind`, `state`, `status`, `ipv4_address`, `ipv6_address` and `owner`.
  - `name` is the container's, `clab-<lab>-<node>`: no member holds the node's own name.
  - `ipv4_address` carries the prefix length (`172.20.20.3/24`), so the management address
    is the part before the `/`.
  - `labPath` was relative (`push-explore.clab.yml`) with the caller in the topology's
    directory, and `absLabPath` absolute, as the `--all` fact above says.
- `inspect` reports an exited container's address as `N/A`. *(2026-10-03; 26.04, 2026-10-08)*
- A lab's node management addresses are reassigned at each deploy: read them after the
  deploy, never from an earlier one. *(2026-10-29; 0.81.0, 2026-11-03: a lab destroyed and
  deployed again gave `n1` `.4`, where its first deploy had given it `.2`)*
- **Labels.** The topology's `defaults.labels` reach every container, beside
  containerlab's own (`containerlab=<lab>`, `clab-node-*`, `clab-owner`). *(2026-10-30;
  0.81.0, 2026-11-03)* On 0.81.0 an SR Linux node carries exactly `clab-mgmt-net-bridge`,
  `clab-node-group`, `clab-node-kind`, `clab-node-lab-dir`, `clab-node-longname`,
  `clab-node-name` (the node's name in the topology), `clab-node-type`, `clab-owner`,
  `clab-topo-file` and `containerlab` (the lab's name); then the topology's `fylgja.twin`,
  and the image's own `description` and `org.opencontainers.image.*`.
- **Two labs at once**, each with its own `mgmt.network` and `ipv4-subnet`, deploy
  concurrently in 48–50 s, with distinct names, labels and hosts entries. Destroying one
  (1.6 s) leaves the other running. **Their management networks route to each other
  through the host** (3 ms ping between two labs' nodes). *(2026-10-30)* Re-exercised on
  0.81.0, all but the route *(0.81.0, 2026-11-03)*: `drv-live` and `drv-live-2`, three SR
  Linux nodes each, deployed at once through the driver in 53.1 s; destroying `drv-live`
  (1.6 s) left `drv-live-2` running, with its hosts block whole. **The route between two
  labs, which `isolation: names` rests on, was not re-exercised in phase 4**: it stands from
  0.79.0.
- **Residue.** *(2026-10-30)*
  - `docker rm` of a lab's containers, followed by `destroy --cleanup`, leaves the
    management network, the `/etc/hosts` lines and
    `/etc/ssh/ssh_config.d/clab-<lab>.conf`. *(0.81.0, 2026-11-03)* `docker rm -f` of a
    three-node lab's containers (0.84 s) leaves the same three: the network, the whole
    hosts block (both markers and every node's line) and the ssh config.
  - `destroy --name` refuses a lab with no containers. *(0.81.0, 2026-11-03: `Lab '<lab>'
    not found - no running containers.`, status 1)*
  - A deploy followed by a destroy clears all of it. *(0.81.0, 2026-11-03)*: no
    container, no `/etc/hosts` line, no `/etc/ssh/ssh_config.d/clab-<lab>.conf` and no
    management network was left after any of eight labs, a failed deploy among them. The
    deploy over that residue reuses the management network left behind; the driver's
    residue rule took 25.0 s, the deploy 24 s of it, where a fresh deploy took about 40 s.
  - A deploy refused at its start leaves only the management network. *(0.81.0,
    2026-11-03)* A node image that no registry serves (`fylgja.invalid/none:0`) was refused
    at its pull, status 1 in 0.55 s. containerlab creates the network before it pulls, and
    no lab directory, host entry or ssh config yet. The driver's `inspect` reads it as
    `residue` that is not root-owned, and `docker network rm` alone clears it.

**What the local driver reads and runs** *(0.81.0, Docker 29.8.1, 2026-11-03)*

- **A lab's containers** are listed by
  `docker ps -a --filter label=containerlab=<lab> --format '{{.Names}}'`. The label's value
  is the lab's name exactly, so `drv-live`'s listing never holds `drv-live-2`'s containers.
- **`docker inspect --type container <names…>`** answers a JSON array. The driver reads:
  - `Name`, with a leading `/`;
  - `State.Running`;
  - `State.StartedAt`, RFC 3339 with nanoseconds (`2026-11-03T19:55:43.416491086Z`);
  - `Config.Labels["clab-node-name"]`;
  - `NetworkSettings.Networks["clab-<lab>"].IPAddress`, the node's address in the lab's
    management subnet.
- **An exited container** keeps its last `StartedAt` and its `IPAMConfig.IPv4Address`; its
  `IPAddress`, `Gateway` and `MacAddress` are empty, and `State.Running` is false.
- **`/etc/hosts`** holds each lab's entries in a block between
  `###### CLAB-<lab>-START ######` and `###### CLAB-<lab>-END ######`, one line per node:
  `<ipv4>\tclab-<lab>-<node> <short id>\t# Kind: <kind>`.
  - An IPv4-only management network's block held no IPv6 line.
  - `clab-<lab>-` also begins another lab's names (`clab-drv-live-2-n1`), so the driver
    finds a lab's residue by its start marker.
- **`docker network inspect --format '{{json .IPAM.Config}}' <ids…>`** prints one line per
  network: a list of `{"Subnet", "Gateway"}` objects, or `null` for `host` and `none`.
  `docker image inspect` of an absent image (`No such image`) and `docker network inspect`
  of an absent network each exit 1.
- **`destroy -t <file> --cleanup` needs the topology file.** Without it, it exits 1
  (`Stat <file>: no such file or directory`) and removes nothing.
  - `destroy --name <lab> --cleanup` needs no file. It removes the containers, the hosts
    block, the network and the lab directory, but leaves
    `/etc/ssh/ssh_config.d/clab-<lab>.conf`: it removes `clab-.conf`, an empty lab name.
  - So the driver writes the topology and destroys with `-t`.
- **`destroy -t <file> --cleanup` of a running lab removes its management network too**: the
  driver's `docker network rm` found nothing to remove in any run.
- **Timings through the driver** for `three-node`, three SR Linux 24.7.1 nodes, on a host
  with 27 GiB available:

  | Operation | Time |
  |---|---|
  | Deploy | 44.1 s and 39.9 s |
  | Repeat deploy | 0.73 s |
  | `--reconfigure` | 40.1 s |
  | Destroy | 1.5 s |
  | Two labs at once | 53.1 s |
  | The residue rule (deploy, then destroy) | 25.0 s |
  | `inspect` (one `docker ps`, one `docker inspect`) | 0.07–0.17 s |
  | Two `admit`s | 0.18 s |

  The whole live tier, seven tests, took 212 s twice. A one-node `linux` lab (alpine)
  deploys in 1.6 s.

**Interface names**

- **`nokia_srlinux` takes production names as aliases**: `ethernet-1/1` → `e1-1`, and
  breakout `ethernet-1/1/1` → `e1-1-1`. `inspect interfaces` lists each port's `alias`.
  *(2026-10-30; 0.81.0, 2026-11-03: the end-to-end test's topology, its links between
  production names such as `n1:ethernet-1/1`, deployed every time; the breakout alias was
  not re-exercised)*
- **An out-of-range SR Linux name** (`ethernet-1/99`, `ethernet-2/1`) passes `validate`
  and is refused in post-deploy, about 30 s in, after the containers exist (deploy rc 1).
  *(2026-10-30)*
- **`ceos` has no aliases.** It refuses `Ethernet2/1` and `Et4` at deploy start ("ethX or
  etX"). Its pattern `eth[1-9][\w.]*$|et[1-9][\w.]*$` is unanchored at the start, so
  `Ethernet1` passes and becomes a Linux port EOS never lists: a silent failure, which in
  that lab also held cEOS's post-deploy for about 6 minutes. 0.80 through 0.82 are
  unchanged. *(2026-10-30)* *(0.81.0, 2026-11-03: the push lab's cEOS node deployed with its
  link on the Linux name `eth1`; the refusals were not re-run)*
- **`validate` checks no interface name.** *(2026-10-30)*

**A killed or partial deploy**

- `/usr/bin/containerlab` is setuid root: it runs with the user's real uid and effective
  uid 0. *(2026-09-15; 26.04, 2026-10-08, 2026-10-30; 0.81.0, 2026-11-03: a running
  deploy's `/proc/<pid>/status` reads `Uid: 1000 0 0 0`)*
  - The kernel clears `Pdeathsig` when it starts, so a `clab deploy` outlives a parent
    killed with `kill -9`: stop a stray `clab` before acting. *(0.81.0, 2026-11-03)* A
    deploy whose wrapping shell was killed with `kill -9` ran on and completed.
  - `kill -9` from the user kills it. *(0.81.0, 2026-11-03)* A deploy of one SR Linux node,
    killed 4 s in, exited 137 at once. So did the local driver's budget kill, which sends
    `SIGKILL` to the command's process group (`cli.run`, with the command started in a
    session of its own): `CommandFailed` with status -1 after 4 s, and no `containerlab`
    process left.
- **A deploy killed in post-deploy** leaves running nodes that never answer, the network
  and the lab directory. *(2026-10-30)* *(0.81.0, 2026-11-03)* One SR Linux node killed
  4 s in, in its post-deploy, left the node running, the network and the lab directory, and
  no host entries or ssh config. containerlab creates the network, then the lab directory,
  then the containers; it writes the host entries and the ssh config only after the nodes'
  post-deploy. Whether that node ever answered was not checked. *(0.81.0, 2026-11-04)* It
  does not: one SR Linux 24.7.1 node, its post-deploy begun 2.0 s into the deploy, was
  killed with `SIGKILL` 7.0 s in (status -9, no `containerlab` process left). It left the
  node running with its management address and no host entries or ssh config, and its push
  transport never answered the readiness request: `readiness.timeout` after 88 s of a
  90 s budget.
- **A plain re-deploy of a partial lab skips containerlab's post-deploy** and leaves the
  bootstrap unapplied: after a killed deploy it returned 0 in 0.6 s and fixed nothing.
  Deploy over a partial lab with `--reconfigure`, which recovered the lab in 51.7 s.
  *(2026-09-15; 26.04, 2026-10-08, 2026-10-30)*
  *(0.81.0, 2026-11-04)* The same on 0.81.0: over that node, a plain `deploy -t` returned 0
  in 0.6 s with the container not restarted (`StartedAt` unchanged), and readiness timed
  out again after 88 s. `deploy -t --reconfigure` then returned 0 in 37.4 s, the node made
  anew (`StartedAt` moved), and its push transport answered 4.4 s later; `destroy -t
  --cleanup` took 0.9 s and left no container, network, host entry or ssh config.
- **`--reconfigure` over a healthy lab recreates every node**: three SR Linux nodes in
  40.1 s, every container's `State.StartedAt` moved. *(0.81.0, 2026-11-03)*

**fylgja-core, phase 4: one twin end to end through API 1** *(0.81.0, Docker 29.8.1, SR Linux
24.7.1, 2026-11-03)*

The live end-to-end test (`core/tests/live/test_e2e.py`) runs `three-node` through
`fylgja-core-server` and the thin CLI, over a store in a temporary directory, on a host with
27 GiB available. It passed on its first full run and in the whole tier, and three times more
as it grew a stricter kill check and a deletion during the deploy. *(2026-11-04)*

- **A create**, `twin create` to Ready, took 57.8–67.1 s end to end over eight runs: apply
  36.1–43.3 s, the three nodes' readiness 12.3–13.3 s, the three pushes 9.0–10.0 s together
  (2.9–3.5 s each), and compile, admit and plan under 0.2 s together. A destroy took
  1.4–2.1 s and left no container, host entry, ssh config or network.
- **A server killed with SIGKILL at each phase boundary of a create resumed the same run to
  Ready**, with no gap in its events' `seq` and no second create run. That held at
  `compiled`, `admitted`, `planned`, `applied`, `ready` and `pushed`, Ready 60.2–70.3 s
  after the create, five times. No kill caused a `--reconfigure`, and each create deployed
  once.
  - The kills at `admitted` and `planned` landed in the apply step's first `docker ps`,
    before its deploy began, so the run shows two `apply started` events and one deploy.
  - The kill at `pushed` landed before the run's end was written, and the resume wrote it.
- **A server killed 10 s into the deploy**: containerlab's deploy, run in a session of its
  own, ran on without the server. The resumed pass found the three containers, and each
  node's push transport answered within its readiness budget (46.6 s for the three, while
  the deploy finished), so it deployed nothing (apply `skipped`) and pushed: Ready
  72.2–78.9 s after the create.
- **A server killed during a destroy**: the restarted server took up the destroy run, and
  the twin was gone 2.6–3.2 s after its deletion was asked, nothing left on the host.
- **A deletion during the deploy**, asked once the deploy had made its three containers
  (0.9–1.6 s in): the loop stopped the deploy, killing its process group, and the cancel's
  `destroy -t --cleanup` of the partial lab took 0.75 s; the create run ended `failed`
  (`run.cancelled`), the destroy run `ok`, and the twin was gone 1.4–1.7 s after it was asked,
  no container, host entry, ssh config, network or `containerlab` process left. Asked 0.2 s
  in, before any container, it found only the management network, and removed it.
  *(2026-11-04)*
- The server answered its first request 0.5–1.2 s after each start; its 402–485 lines of log
  were each one JSON object, none holding the token or a password. The whole live tier, 27
  tests (the driver's, the push's and the end-to-end), took 904 s. *(2026-11-04)*

**The dry run**

- `clab deploy --dry-run --format json` prints a plan on stdout (`added-nodes`,
  `deleted-nodes`, `recreated-nodes`, `restarted-nodes`, `added-links`,
  `deleted-endpoints`, `node-change-reasons`) and writes nothing. *(2026-10-01; 26.04, 2026-10-08)*
  On Ubuntu 26.04 every plan also carried `started-nodes`, and no `deployed-lab: false`
  plan carried `lab-name`, which every such plan on 24.04 at the same release did. A
  `deployed-lab: true` answer still carries it. *(26.04, 2026-10-08)*
- **That dry run must run with `CLAB_LABDIR_BASE` at the running lab's directory.**
  containerlab decides a recreate from `.state.clab.yaml` there, so from any other base an
  image or kind change is invisible. *(2026-10-01; 26.04, 2026-10-08)* From another base while the
  lab runs, the answer is still a plan, `deployed-lab: false`, that misses the change (a
  kind change showed only as a restart, for `deleted endpoint`). `deployed-lab: true` with
  `lab-name` and every list `null` comes only when no container of the lab exists.
  *(26.04, 2026-10-08)*

**Reconciling a running lab**

- **`clab deploy` without `--reconfigure` reconciles a running lab.** *(2026-10-01; 26.04,
  2026-10-08)*
  - A link added or removed re-cables SR Linux live and restarts a cEOS node in place
    (3.5–14.6 s for the apply).
  - A node added is created with containerlab's post-deploy (31.3 s).
  - An image or kind change is a recreate (20.3 s, 58.7 s with a far cEOS end's restart).
  - A node removed is deleted (0.85 s); nothing to do takes 0.39 s. *(0.81.0,
    2026-11-03)* A repeat deploy of a running three-node lab, with nothing to do, took
    0.73 s and moved no node's `State.StartedAt`.
  - On Ubuntu 26.04: an SR Linux link added in 0.66 s and removed in 0.59 s, live, with
    neither node's `StartedAt` moved; a link between cEOS and SR Linux 3.2 s; a node added
    37.0 s; a kind change 53.6 s; a node removed 1.04 s; nothing to do 0.53 s.
- **SR Linux steps with production names**: a link removed in 0.75 s and added in 1.0 s,
  a node added in 40.7 s and removed in 2.2 s; no existing node restarted, and pushes were
  kept. *(2026-10-30)*
- **`link-apply-mode` is a node field in 0.79** (the strict parser knows it). *(2026-10-30)*
  - `cEOS live`: a link removed or re-added on a port present at boot applies in about
    0.7 s, with no restart, the push kept and LLDP re-formed. containerlab warns that the
    mode is more permissive than the kind's default.
  - A port **added** after boot comes up in Linux, and EOS never lists it.
  - The default (restart) restarts both ends, loses the push, and took 18 s and 125 s to
    apply.
- A changed SR Linux `.cli` is never applied to a running node by a reconcile. *(2026-10-01;
  26.04, 2026-10-08)*
- Disabling one end of a containerlab link takes the link down at both ends: both are
  oper `down`, neither has a neighbour, and the far end's admin-state stays `enable`.
  *(2026-09-19; 26.04, 2026-10-08)*

**Install**

- Its `.deb` installs `/usr/bin/containerlab` setuid root, creates the group
  `clab_admins` and puts the installing user in it. *(26.04, 2026-10-07)*
- It does not need `clab_admins` among the calling process's groups: a process with
  `docker` as its group and no `clab_admins` among its groups (the user listed in it by
  `getent`) deployed and destroyed every twin of a full live run. *(26.04, 2026-10-08)*
- Its setup script (`https://containerlab.dev/setup`, `install-docker`) pins Docker per
  distribution release in its own text, `29.8.1` for Ubuntu 26.04, and fails, removing
  nothing, when that release is not in Docker's repository. `CLAB_VERSION` names
  containerlab's own release, and the copy at its `v0.79.0` tag predates 26.04. On 26.04
  it installed `docker-ce` 29.8.1, `containerd.io` 2.3.6 and the Compose plugin 5.6.0.
  *(2026-10-07; 26.04, 2026-10-07)*

**The `ping` host**

- **The image** is `alpine:3.24.2`, pulled by hand: its id and its repository digest are
  both `sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6` on Docker
  29.8.1, its busybox `v1.37.0`. *(2026-10-29)*
- **busybox 1.37.0's `ping` and `ip` are the mechanism's tools.** *(Docker 29.8.1,
  2026-10-28)*
  - `ping` takes `-c`, `-i`, `-W` (seconds to wait for the first response after the `-c`
    packets are sent), `-w`, `-q`, `-I` and `-t`. `-i 0.2` is accepted as root with no
    minimum-interval refusal.
  - `ip` has `address`, `route` and `link`; `pgrep`, `pkill` and a fractional `sleep` are
    applets of the same image.
  - A reply line reads `64 bytes from <a>: seq=0 ttl=64 time=…` (`seq=`, where iputils
    writes `icmp_seq=`), and the summary `N packets transmitted, M packets received, P%
    packet loss`.
  - A background `ping` sent `SIGINT` prints the same summary and exits: an interrupt ends
    a flow and reads its counters.
- **A `linux` node with `exec` lines plans and deploys beside SR Linux.** *(SR Linux
  24.7.1, alpine 3.24.2, 2026-10-28, 2026-10-29)*
  - `clab deploy --dry-run --format json` checks a topology of a `linux` node and a
    `nokia_srlinux` node without the `linux` node's image and pulls nothing.
  - Both hosts of a probe deploy beside three privileged SR Linux nodes (46.7 s for 5
    nodes), a `linux` node privileged too.
  - Each runs its two `exec` lines after its links are made: inside
    `clab-fylgja-n1-loop-a`, `eth1` holds `10.1.10.2/24` and the route `10.1.11.2 via
    10.1.10.1 dev eth1` sits beside the connected one, 0.1–0.2 s after the deploy returns.
  - A host's container holds about 700 KiB, and its pings to the far host go through the
    device (TTL 63; `traceroute` reads the gateway, then the far host).
- **A failed `exec` line is logged, not failed**: a route through an unreachable gateway
  is logged `ERRO Failed to execute command … rc=2` with its stderr (`ip: RTNETLINK
  answers: Network unreachable`), and the deploy exits 0 with the node `running`. So the
  host's readiness must read the lines' effect itself. *(2026-10-29)*
- **`docker exec -d` and `pkill -INT` in a containerlab-run container**: `docker exec -d
  <host> sh -c 'pkill -x ping; exec ping -i 0.2 <far> > /run/flow.log 2>&1'` exits 0 and
  leaves `ping` running; `pkill -INT -x ping` makes it print its counters at once (the
  read 0.15 s), as outside containerlab. *(Docker 29.8.1, 2026-10-29)*

**A probe's flows and burst**

- A burst, `ping -c 5 -i 0.2 -W 2`, takes 0.93–0.96 s when every echo is answered. `twin
  verify` on a probed three-node twin took 5.3 s (22 assertions over 5 nodes), 6.0 s with
  the burst failing. *(2026-10-29)*
- **Starting and reading the flows adds no measurable time to a step.** *(SR Linux 24.7.1,
  cEOS 4.32.0.2F, 2026-10-29)*
  - Three steps of a probed twin, each pushing `n1` alone, took 12.0, 40.8 and 18.3 s at
    the client, the second waiting out a 30 s wait on a failing burst.
  - The loss read across them: `0/45` with `n1:ethernet-1/2` disabled, `176/190`
    (longest gap 35.2 s) with the probe's own port disabled, and `41/77` (8.2 s) back.
  - A step across a cEOS node's restart in place lost `369/403` (gap 73.8 s) and `321/356`
    (64.2 s).

---

## clabernetes 0.10.1

On kind v0.33.0 (below), unless marked; on three k3s hosts in
[its own section](#k3s-v1371k3s1-three-servers-with-clabernetes-0101).

- **Install.** Helm OCI `oci://ghcr.io/clabernetes/clabernetes/clabernetes`, version
  `0.10.1` (no `v`; digest `sha256:d98a5b25…`), installs with `--wait` in 20 s: 3
  managers, 4 planner pods, CRDs `configs`, `links`, `nodeprofiles`, `nodes`,
  `topologies`. *(2026-10-30)*
- **The default Config** requests 200m CPU and 512 Mi per node, with `imagePull`
  `IfNotPresent`. *(2026-10-30)*
- **The `Topology` spec** carries `imagePull.pullSecrets`, `expose.{exposeType,
  disableAutoExpose, useNodeMgmtIpv4Address}`, `rollout`, `statusProbes`,
  `disableManagement` and `deployment.{persistence, resources, scheduling, filesFrom*}`.
  *(2026-10-30)*
- **Production names.** The Topology takes containerlab YAML verbatim, and SR Linux
  production names compile (containerlab 0.81 inside). cEOS takes `ethN` names. *(2026-10-30)*
- **Fixtures.** *(2026-10-30)*
  - Three-node: Ready in 237 s on a first pull of SR Linux.
  - Mixed: Ready in 208 s on a first pull of cEOS from the private registry.
  - About 70 s with the images cached.
  - One LoadBalancer IP per node, with 14 TCP ports exposed by default.
  - No LLDP over management.
- **Steps.** *(2026-10-30)*
  - Default modes: a cEOS link change replaces both cEOS pods (about 140–156 s) and loses
    their push; the SR Linux pod is kept.
  - `live`: no pod is replaced, and pushes are kept. A node is added in 70 s and removed
    in 29 s.
  - `restart` and `recreate` each replace the link's cEOS pods (108–116 s).
  - Changing any node's `link-apply-mode` replaces every pod.
  - A cEOS port added after boot is never seen.
- **Managers killed mid-step.** With all three manager pods deleted 10 s into a step, the
  step completed (136 s against 116 s). *(2026-10-30)*
- **Namespace delete.** `kubectl delete namespace` removes a twin in 49 s, leaving
  nothing by its label and releasing its LoadBalancer IPs. *(2026-10-30)*
- **Reach between twins.** The pod network lets one twin's node reach another twin's pod.
  A NetworkPolicy refuses it and keeps the push, the links and Ready. The policy admits the
  twin's own pods, the `c9s` namespace and `0.0.0.0/0` except the pod CIDR. *(2026-10-30)*
  On k3s across hosts it also needs each LoadBalancer at `externalTrafficPolicy: Local`
  (below). *(2026-11-02)*
- **A private registry** (registry 3.0.0, TLS by a private CA, htpasswd) on loopback and
  the kind network. *(2026-10-30)*
  - The controller trusts it via `Config.spec.imagePull.registryMetadataTrust`.
  - Each namespace gets a pull secret.
  - `fy-registry` resolves from pods and nodes.
  - The cEOS image's uncompressed layer is the recorded `sha256:09ab9635…` (cEOS, below).
- **Memory**, close to local containerlab: about 1.6–2 GiB per SR Linux node and
  0.9–1.5 GiB per cEOS node. *(2026-10-30)*

---

## kind v0.33.0 (Kubernetes 1.37.0, containerd 2.3.4)

- **kind needs no root.** The `vxlan` module loaded on demand. *(2026-10-30)*
- **kindnet enforces NetworkPolicy** (clabernetes, above). *(2026-10-30)*
- The empty three-node cluster holds about 1 GiB. *(2026-10-30)*

---

## k3s v1.37.1+k3s1, three servers, with clabernetes 0.10.1

Three Proxmox VMs, each 8 vCPU, 24 GiB and 80 GB on spinning disks the VMs share; Ubuntu
26.04.1, kernel 7.0.0-42; k3s with embedded etcd, containerd 2.3.4-k3s1, flannel VXLAN and
k3s's embedded network policy controller (kube-router v2.6.3); MetalLB 0.16.0 in layer 2 on
the LAN; clabernetes 0.10.1 at its default requests (200m CPU, 512 Mi). Five twins: three
three-node SR Linux twins and two mixed ones (two cEOS, one SR Linux).

- **etcd on spinning disks shared by the hosts** loses its leader when the three hosts
  unpack a 5.2 GB image at once. Applies took 5 s against an expected 100 ms, and k3s
  restarted on two servers, cancelling the pulls. With `etcd-arg` `heartbeat-interval=500`
  and `election-timeout=5000` in `/etc/rancher/k3s/config.yaml`, and images pulled one host
  at a time, the outages fell to blips of 2–3 s. *(2026-11-02)*
- **A private registry is trusted** by `configs."<host:port>".tls.ca_file` in
  `/etc/rancher/k3s/registries.yaml`, after a k3s restart (about 31 s a host). *(2026-11-02)*
- **First pulls.** A three-node SR Linux twin from ghcr was Ready 257 s after its apply, its
  three hosts pulling at once. cEOS pulled from the private registry in 107–111 s per host.
  With the images present, a mixed twin was Ready in 107 s, and three twins created at once
  in 89–119 s. *(2026-11-02)*
- **Spread.** The default scheduler put each three-node twin's nodes one per host, so every
  link crossed hosts over VXLAN. *(2026-11-02)*
- **Steps across hosts** behave as on kind. *(2026-11-02)*
  - Default modes: a cEOS link change replaced both cEOS pods (136–138 s); the SR Linux pod
    was kept.
  - Switching to `live` replaced every pod (137 s).
  - `live`: no pod was replaced (25 s), and cEOS ports went `notconnect` and `connected`
    across hosts.
- **A LoadBalancer with `externalTrafficPolicy: Cluster`** reaches a pod on another host with
  its source rewritten to the announcing host's flannel address (`10.42.N.0`), inside the
  pod CIDR. *(2026-11-02)*
  - A policy admitting `0.0.0.0/0` except the pod CIDR then refuses it. That hits whichever
    nodes MetalLB announces from a host other than the pod's.
  - `Local` keeps the client's address, and MetalLB then announces from the pod's host.
  - clabernetes has no setting for it. It keeps a patched value across Topology updates, pod
    replacements and a drain.
- **k3s's network policy controller accepts ICMP echo into every pod**, whatever the policy
  (its `KUBE-NWPLCY-COMMON` chain). It refuses other traffic with REJECT, which a client sees
  as connection refused. A pod started a few seconds before is not yet in the controller's
  sets. Test isolation over TCP, from a pod that has run for 15 s. Over TCP, a twin's pod
  could not reach another twin's node on 22 or 57400, and a pod of the same twin
  could. *(2026-11-02)*
- **Five twins at once** (11 SR Linux and 4 cEOS nodes) took 15 LoadBalancer addresses.
  Every node's push transport, SSH and gNMI answered from off the cluster. *(2026-11-02)*
- **Use per node**, by `kubectl top`: SR Linux 0.35–0.5 core and 1.58–1.63 GiB; cEOS
  0.2–0.45 core and 0.89–0.96 GiB. The five twins used about 6.8 cores and 23 GiB, leaving
  14.4–15.2 GiB available on each host. *(2026-11-02)*
- **Drain.** *(2026-11-02)*
  - Draining a host holding one node of each of the five twins evicted in 6 s.
  - Each twin was Ready again on the other two hosts in 94–114 s, each node at its same
    LoadBalancer address. The moved nodes are new pods.
  - The two remaining hosts held 10.1 and 11.4 GiB available, with about 2.5 of 8 cores busy
    on each.
  - etcd stayed in quorum, with one blip of 2–3 s just after the evictions.
  - Nothing moved back after the uncordon.
  - A drain refuses a pod with no controller, until it is deleted.
- **Namespace delete** removed an SR Linux twin in 13–14 s and a mixed one in 46–48 s,
  leaving nothing by its label and releasing its LoadBalancer addresses. *(2026-11-02)*

---

## SR Linux 24.7.1

**Booting** (one node, an otherwise idle host)

- From deploy start the container runs at 0.6 s and `sr_cli` answers at 2 s, which is
  **not** readiness; `clab deploy` returns at 12.4 s, and gNMI `:57400` opens and
  completes a TLS handshake at 15.2–15.4 s. *(2026-09-15)*
- One booted node holds about 1.57 GiB (cgroup `memory.current`, steady over a minute).
  *(2026-09-15)*
- **The chassis is the `7220 IXR-D2L`**, containerlab's default `type` for
  `nokia_srlinux`. Its front ports are `ethernet-1/1` to `ethernet-1/58`, beside `lo0` and
  `mgmt0`. A push naming `ethernet-1/99` is refused `invalid port 99, max is 58`, and one
  naming `ethernet-2/1` `invalid slot 2`, on that node alone. *(2026-09-19; 26.04, 2026-10-19,
  2026-10-20)* The port-99 refusal was re-exercised on 0.81.0, not the slot's.
  *(0.81.0, 2026-11-03)*
- The node's name for a port is `ethernet-1/1`, not containerlab's endpoint name `e1-1`:
  `set / interface e1-1 admin-state enable` is refused. *(2026-09-15)*
- Every LLDP adjacency forms before `clab deploy` returns, so a read after the twin is
  `ready` never waits for a neighbour. *(2026-09-19)*
- SR Linux writes to containerlab's node directory on its own
  (`clab-fylgja/<node>/config/gnoi/healthz/events/events.data` moves on every node), so a
  digest of the whole twin directory moves with nothing read. *(2026-10-03)*
- It boots on Ubuntu only once AppArmor allows its `rsyslogd`
  ([Ubuntu hosts](#ubuntu-hosts)). *(2026-09-30; 26.04, 2026-10-07, 2026-10-08)*
- **Under memory pressure its own `sr_cli` can segfault**, or refuse containerlab's
  post-deploy checkpoint, failing the deploy. *(2026-09-16, 2026-09-17; 26.04, 2026-10-27)* With about
  10.2 GiB available at a load of 5–6, one node's `sr_cli` segfaulted in containerlab's
  post-deploy (`python3.11` in the kernel log), containerlab cancelled the other two
  nodes' post-deploy and the deploy failed; the run after a rest passed.
  *(0.81.0, 2026-11-03)* CPU contention alone does it too: with 22 GiB available and the
  load at 33, another live tier booting six nodes beside it, `sr_cli` segfaulted in
  containerlab's post-deploy 31 s in (`Segmentation fault (core dumped)` in its bootstrap),
  the deploy failed at 65.9 s with rc 1, and `destroy --cleanup` left nothing. The run on a
  quiet host passed.

**gNMI**

- gNMI listens in the management namespace: reach it from the host at the node's
  management address, or by name through containerlab's `/etc/hosts` entry, not from
  inside the container. *(2026-09-15)*
- The encoding must be set: gnmic's default JSON gets `Unimplemented` ("Only ASCII,
  PROTO/TYPED_VAL, JSON_IETF, … supported"), so a probe on the default never succeeds;
  `json_ietf` works. *(2026-09-15)*
- The paths: `/system/name/host-name`; `/system/information/version`
  (`v24.7.1-330-g38f237abfe`); `/interface[name=X]/admin-state`;
  `/system/lldp/interface[name=X]/admin-state`; and `…/neighbor`, whose `system-name` is
  the far node and whose `port-id` is the far port under the far node's own name
  (`port-id-type INTERFACE_NAME`). *(2026-09-19)*
- A leaf comes back as one update at the leaf. A subtree comes back as one update at the
  list entry, with the subtree inside its value, the update path's elements carrying
  module prefixes and the keys inside the value carrying none. *(2026-09-19)*
- An absent value is no update and no error: an uncabled port's neighbour, or a port the
  node lacks, gives `updates: []` with exit 0. *(2026-09-19)*

**Readiness (JSON-RPC)** *(0.81.0, 2026-11-03)*

- **`show version` over `cli`**, sent with no output-format, answers HTTP 200 with a
  `result` of one JSON object, `{"basic system info": {…}}`, not text: `Hostname`, `Chassis
  Type` (`7220 IXR-D2L`), `Software Version` (`v24.7.1`), `Build Number`
  (`330-g38f237abfe`), `Last Booted` and memory among its members.
- **It answered at the first attempt, 3.2–3.5 s after the addresses were read from
  `inspect`**, 0.12–0.24 s after the deploy returned (four runs, the cEOS node booting
  beside it): the request itself took those seconds.
- **Every `cli` request costs seconds.** Twelve `show version` requests in a row on a
  fresh node took 3.2–4.4 s each, three of them over 4 s. A replace took 2.0–3.4 s and
  `commit validate` 1.6–2.3 s. A readiness attempt cut at 4 s would miss about one answer
  in four.
- **A wrong password is answered HTTP 401 at once**, in 0.31 s, with a 32-byte body,
  `AuthenticationFailed (status: 1)`, as `text/html; charset=utf-8`. Readiness got it at
  its first attempt and the push got it too (`Unauthorized`). Three refused logins locked
  nothing: the real login answered right after.

**The push (JSON-RPC)**

- The push is JSON-RPC `cli` over HTTPS 443 with basic auth: `enter candidate private`,
  the lines, `commit now`. Without the candidate, `set` is refused. It takes 0.62–0.96 s
  for an 839-byte rendered config, and is idempotent. *(2026-09-18; 0.81.0, 2026-11-03)*
  On 0.81.0 the replace of mixed.json's `s1` (27 commands, `load startup` and `diff flat`
  among them) took 2.0–3.4 s, and its repeat changed nothing.
- **A committed replace answers one `{"text": …}` entry** holding every command's output in
  order: `/system/configuration/checkpoint[id=__startup__]:` and `    Loaded startup
  configuration` (the reset's), a blank line, `diff flat`'s lines, then `All changes have
  been committed. Leaving candidate mode.` With `"output-format": "text"` the entry is a
  bare string. So the device's diff is `diff flat`'s lines alone. *(0.81.0, 2026-11-03)*
- **`info from running / system name host-name`** as a JSON-RPC `cli` request with
  `"output-format": "text"` answers `result` as a list of one bare string:
  `    system {\n        name {\n            host-name n1\n        }\n    }\n` on a node named
  `n1`, after its replace. *(0.81.0, 2026-11-03)*
- **`diff flat` writes `insert /` and `delete /` lines.** A changed leaf is an `insert /`
  line, a removed subtree a `delete /` line, and a changed address a `delete /` and an
  `insert /`. *(0.81.0, 2026-11-03)*
- **A repeat push's answer holds only the reset's lines and the commit's line**, no
  `diff flat` line: its diff is empty. *(0.81.0, 2026-11-03)*
- The baseline's host name is the node's name, yet the first replace's diff holds `insert /
  system name host-name s1` on a node named `s1`: the startup configuration does not state
  it. `#` comment lines are accepted in the request. *(0.81.0, 2026-11-03)*
- A refused line comes back as HTTP 200 with a JSON-RPC error that echoes every command
  sent, the rendered config included, so keep only the reason. *(2026-09-18; 0.81.0,
  2026-11-03)* The error's `code` is `-1`, and its message is `Error: Cli commands '…'
  failed with error 1: …`, the echo holding one command per line.
- A refused line stays in the login's private candidate across requests, and every later
  `commit now` fails on it, until `discard now` or `load startup` clears it. *(2026-09-19,
  2026-10-01; 0.81.0, 2026-11-03)*
- Under a replace, a refusal's message is `At line N: Error: <reason>`, a blank line, then
  the request's output so far, `diff flat`'s `insert /` lines included; the reason ends at
  the first blank line. *(2026-10-01; 0.81.0, 2026-11-03)* On 0.81.0 a commit's reason
  runs two lines, `Error: Error in path: .interface{.name=="ethernet-1/99"}` and
  `    [InvalidArgument] invalid port 99, max is 58`; a schema constraint's second line is
  `[FailedPrecondition] vlan-id only configurable if vlan-tagging enabled on parent
  interface`.
- **A parse error writes no blank line before the output.** `set / bogus thing` answers
  `At line 4: Parsing error: Unknown token 'bogus'. Options are […]`, and the next line is
  already the reset's `/system/configuration/checkpoint[id=__startup__]:`. So a reason
  ends at the first blank line or at that line. *(0.81.0, 2026-11-03)*
- SR Linux cuts that message at about 1 KiB, inside its echo of the commands, so a real
  replace's reason never arrives. `commit validate` after it recovers a schema
  constraint's reason, but answers `All changes are valid.` for the port-range check,
  which only a commit makes. *(2026-10-02; 0.81.0, 2026-11-03)* On 0.81.0 the cut
  message was 1,031 characters, ending `...`, for mixed.json's `s1` with one line
  appended. After a parse error, `commit validate` answered `All changes are valid.` too.
- **`commit validate`'s answers.** *(0.81.0, 2026-11-03)*
  - A valid candidate: `result` `[{"text": "All changes are valid.\n"}]`.
  - A refused one: an error whose message keeps the `At line N:` shape: `Error: Cli
    commands 'enter candidate private\ncommit validate' failed with error 1: At line 2:
    Error in /interface[name=ethernet-1/1]/subinterface[index=0]/vlan/encap/single-tagged/vlan-id::`,
    an indented `vlan-id only configurable if vlan-tagging enabled on parent interface`,
    then `Error: Validate failed`, with no blank line. `At line 2` is the validate
    request's own line, never the configuration's.
- `delete /` as a replace darkens the management plane when the rendered config does not
  restate it; `load startup` resets to the baseline containerlab left and does not.
  *(2026-09-18, 2026-10-01)* The `load startup` half was re-exercised on 0.81.0: the node
  answered every request after each replace. *(0.81.0, 2026-11-03)*
- **A port's address lines are accepted in the replace**: `subinterface 0 ipv4
  admin-state enable` and `subinterface 0 ipv4 address <a/l>` after `subinterface 0
  admin-state enable`. Pushes took 2.8–2.9 s, and `info from running` reads `ipv4 {
  admin-state enable address 10.1.10.1/24 { } }`. A second address is a second plain
  `address` line. *(2026-10-29)* Re-exercised on 0.81.0 by mixed.json's `s1`, whose two
  addressed ports landed (the diff's `insert / … ipv4 address` lines); `info from running`
  was not read again. *(0.81.0, 2026-11-03)*

---

## cEOS 4.32.0.2F

- **The image is account-gated**: downloaded from Arista with an account and imported with
  `docker import`, which leaves one layer and no `Cmd`, and gives each import a new image
  id. containerlab's `ceos` kind boots it with nothing else stated and supplies the
  command. *(2026-09-20; 26.04, 2026-10-07, 2026-10-08)*
- **The file Arista's portal gives, `cEOS-lab-4.32.0.2F.tar`, is xz-compressed** despite
  its name, and `docker import` reads the xz stream as it is. The imported image's one
  layer has the decompressed tar's sha256 as its digest, so a present image can be told
  from the tar it came from without importing again: the tar whose sha256 is `89a567d5…`
  gives the layer `sha256:09ab9635…`. *(2026-10-07; 26.04, 2026-10-07, 2026-10-08, 2026-10-30)*
- **It carries production's names one to one**: `Ethernet1` … `Ethernet511`
  (`/interfaces/interface/name`, beside `Loopback0` and `Management0`), and modular and
  breakout forms such as `Ethernet2/1` and `Ethernet3/1/1` are the node's own names. A
  push naming a port beyond 511 is refused at parse; one inside the range that the node
  lacks is accepted with a warning. *(2026-09-20)* containerlab's topology takes `ethN` names
  alone for it (containerlab, **Interface names**).
- gNMI is plaintext gRPC on 6030, not TLS on 57400 (containerlab's default is `transport
  grpc default` with no SSL profile), and it answers about a second before eAPI does.
  *(2026-09-20, 2026-09-21)*
- The startup-config is the node's whole configuration, not a part merged over a default.
  The kind's default already sets the host name from the node name and brings every port
  up. *(2026-09-20)*
- **The push is eAPI `runCmds`** over HTTPS to `/command-api` with basic auth, in a named
  configuration session, since a committed session name cannot be reused; a refused
  session is aborted before the next attempt. *(2026-09-20; 0.81.0, 2026-11-03)* On 0.81.0
  the replace of mixed.json's `e1` (25 commands) took 2.6–5.3 s, and its repeat 1.6–2.4 s.
- **Readiness: `show version` over `runCmds`** with `format: "json"` answers HTTP 200 with
  a `result` of one object: `mfgName` `Arista`, `modelName` `cEOSLab`, `version`
  `4.32.0.2F-41889544.43202F (engineering build)`, `uptime` among its members.
  *(0.81.0, 2026-11-03)*
  - It first answered 8.1–17.4 s after the addresses were read from `inspect`, 0.12–0.24 s
    after the deploy returned (four runs).
  - In the run read with the core's debug log, the port refused connections for about
    14 s, then `/command-api` answered HTTP 404 once; the next attempt, 2 s later, got the
    first answer, which took about 1.3 s. Later answers took 0.08–0.13 s.
- **A wrong password is answered HTTP 401 at once**, in 0.09–0.10 s, with a 62-byte body,
  `Unable to authenticate user: Bad username/password combination`, as `text/plain`.
  Readiness got it at its first attempt and the push got it too (`Unauthorized`). Three
  refused logins locked nothing: the real login answered right after. *(0.81.0,
  2026-11-03)*
- **A replace's answer** is one `{"output": …}` entry per command, the diff's the entry
  before the commit's (`{"output": ""}`). The diff opens `--- system:/running-config` and
  `+++ session:/<session>-session-config`, then unified lines. **A repeat push's diff
  entry is `""`.** *(0.81.0, 2026-11-03)*
- **A port the node lacks is accepted in the session with a warning**: its `interface`
  entry carries `warnings`, `Interface does not exist. The configuration will not take
  effect until the module is inserted.`, and its lines appear in the diff.
  *(0.81.0, 2026-11-03)* This differs from the `arista_eos` package's `hot_add_ports` note,
  which says a push naming such a port is accepted silently: the node does warn, in an
  answer the push does not read, and the push lands.
- **A refused command** answers HTTP 200 with an error. *(0.81.0, 2026-11-03)*
  - `code` is `1002` and `message` `CLI command 25 of 27 'no such command' failed:
    invalid command`.
  - `data` holds one entry per command run, the refused one last: its index is the
    command's number less one.
  - That entry carries `errors` (`Invalid input (at token 1: 'such')`) beside `output`.
- **A refused session stays `pending`** in `show configuration sessions` (`format:
  "json"`: `sessions` by name, each with a `state`, beside `maxSavedSessions` `1` and
  `maxOpenSessions` `5`). `configure session <name>` then `abort` removes it, and no
  session is left. A committed session is not listed: `sessions` was `{}` after two
  commits. *(0.81.0, 2026-11-03)*
- `#` is refused at token 0, and `!` is read as a comment. *(2026-09-20)* The `!` half was
  re-exercised on 0.81.0: mixed.json's `e1` carries three `!` lines, and its push lands.
  *(0.81.0, 2026-11-03)*
- `show session-config diffs` has no JSON model: `format: "json"` fails the whole request
  with code 1003 and leaves the session pending, and `format: "text"` answers. The diff
  carries its own bare `!` separators, never the rendered config's `!` comment.
  *(2026-10-01, 2026-10-02)* The `format: "text"` half was re-exercised on 0.81.0, its bare
  `!` separators with it; the `json` failure was not tried again. *(0.81.0, 2026-11-03)*
- **Address lines are accepted in the eAPI replace**: `ip routing` after `hostname`, and
  on each addressed port `no switchport` and `ip address <a/l>` after `no shutdown`.
  Pushes took 2.3–2.5 s, and `show running-config` reads them. A second address needs
  `secondary`: a plain second `ip address` replaces the first. *(2026-10-29)* That holds on
  a node with an Ethernet port; one with none refuses `ip routing` (below). *(0.81.0,
  2026-11-03)*
- **A node with no Ethernet port refuses `ip routing`**: `Unavailable command (not
  supported on this hardware platform) (at token 1: 'routing')`. *(0.81.0, 2026-11-03)*
  - With no link, containerlab sets `CLAB_INTFS=0`, and the node lists `Management0` alone.
  - Its forwarding agent, `Etba`, never started: still absent six minutes after boot.
  - The same image with one link ran `Etba` and accepted `ip routing` at once.
  - The rest of mixed.json's `e1` configuration was accepted on the link-less node.
- The paths: `/system/state/hostname`; `/system/state/software-version`
  (`4.32.0.2F-41889544.43202F (engineering build)`);
  `/interfaces/interface[name=X]/state/enabled`; `/lldp/interfaces/interface[name=X]/…`.
  *(2026-09-20)*
- An absent value is not a default: OpenConfig reports nothing where SR Linux reports a
  value. *(2026-09-20)*
- A node restarted in place by a reconcile answers gNMI about 49 s and eAPI about 55 s
  later, on its startup configuration: its push is lost. *(2026-10-01)*
- **A gNMI Set is refused** (`Unavailable desc = system not yet initialized`) more than a
  minute after the node is ready, while its Gets answer. Shut a port through the node's
  own CLI instead: `docker exec clab-fylgja-<node> Cli -p 15 -c 'configure / interface
  Ethernet1 / shutdown'`. *(2026-10-03)*
- A shut port lists a far end as its LLDP neighbour after that end restarted in place,
  while the far end sees none. *(2026-10-03)*

---

## GitHub Actions, `ubuntu-26.04`

- **The hosted runner for a public repository** has 4 vCPUs, 15,983 MiB and 3 GiB of
  swap, Ubuntu 26.04.1 and kernel `7.0.0-1012-azure` (image `20260927.149.1`). Its log
  shows no peak memory. *(2026-10-07)*
- On the Free plan, rulesets and branch protection need the repository public: on a
  private one the API answers `Upgrade to GitHub Pro or make this repository public`. No
  setting disables pull requests; interaction limits last at most six months and cover
  issues too. *(2026-10-07)*

---

## Ubuntu hosts

Verified on Ubuntu 26.04.1 LTS, kernel 7.0, Docker 29.8.1 (Compose 5.6.0, cgroup v2).
Facts dated up to 2026-10-08 were first verified on Ubuntu 24.04.1, kernel 6.8, Docker 27.5.1,
and each says whether it was re-verified on 26.04.

- **SR Linux's `rsyslogd` needs an AppArmor widening on Ubuntu hosts.** *(2026-09-30; 26.04,
  2026-10-08)*
  - Ubuntu's `/etc/apparmor.d/usr.sbin.rsyslogd` attaches to the `rsyslogd` inside every
    privileged SR Linux container. Unwidened, it fails `log_mgr`, and every
    `nokia_srlinux` deploy fails at containerlab's post-deploy commit (`Applications have
    failed: log_mgr`).
  - Add `/opt/srlinux/** mr,` and `/run/srlinux/** rw,` to
    `/etc/apparmor.d/local/usr.sbin.rsyslogd` and reload it with `apparmor_parser -r`.
  - On 26.04 the profile ships and still attaches: inside a running twin SR Linux's
    `rsyslogd` runs `(enforce)`, as the host's own does. With those two lines and
    `/run/syslogd.pid* rw,`, every SR Linux deploy passed. Whether the two alone suffice
    there was not tried.
- With those lines the profile still denies SR Linux's `rsyslogd` the `net_admin`
  capability (`capable`: 10 denials over a full live run), denies no file, and every
  deploy passes. *(26.04, 2026-10-08)*
- A guest that does not nest has no `/dev/kvm`, which only a `vrnetlab_vm` platform
  package would need. *(2026-09-30; 26.04, 2026-10-08)*
- **Booting a twin beside another heavy workload starves a host with little memory to
  spare**: deploys are cut short, and the other workload's requests time out. Read
  `free -m` before booting a twin. *(2026-09-15)*
- **A group added to the user reaches no process that began before it.** A shell or the
  user's `systemd --user` started before the group was added lacks `docker` and
  `clab_admins` while `getent` lists the user in both, until the next login. Under `sg`,
  nesting `sg docker` and `sg clab_admins` keeps only the inner group. *(26.04, 2026-10-08)*
- Ubuntu 26.04's `python3` is 3.14.4, which meets the core's `requires-python >=3.14`.
  *(26.04, 2026-10-07)*
