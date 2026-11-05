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
0.79.0 and stand until each is re-exercised on 0.81.0, which phases 4 and 5 do as they build
the local driver and the step; a fact re-verified there gets a *(0.81.0, date)* mark.

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
  - **`destroy -t <file> --cleanup` removes only the nodes its file names**, not every
    container with the lab's label. *(0.81.0, 2026-11-04)* A stray deploy of a three-node
    topology made `n3`, and the file then held a two-node topology of the same lab. The destroy
    removed `n1`, `n2`, the hosts block and the ssh config, exited 0, and left `n3` running on
    the management network. So the `docker network rm` after it failed, each time. Run again
    with only `n3` left, it printed `no containerlab containers found` and exited 0, `n3` still
    up. `destroy --name <lab> --cleanup` did the same: it parsed the file the container's label
    names, found no container, exited 0 and left `n3`. Then `docker network rm` refused,
    naming `n3` among the network's active endpoints. `docker rm -f` of `n3` and `docker network
    rm` cleared it. The driver's destroy removes such a container first
    ([D-055](decisions.md#d-055)).
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
    deploy whose wrapping shell was killed with `kill -9` ran on and completed; where its
    output went was not recorded. *(0.81.0, 2026-11-04)* A deploy whose parent,
    `fylgja-core-server`, was killed with `SIGKILL` ran on 1.0–22.0 s (every run with the
    output piped, before D-056: the whole tier's and the fix wave's included; the deletion
    figures among them are upper bounds, read when the destroy returned) and ended, at its
    next write by inference (the next bullet). Killed 10 s into a deploy adding a node, the
    plain deploy run after it ended made that node anew, though its container was present and
    answering (phase 5's steps block).
  - **A deploy whose output's reader is gone dies of SIGPIPE, at its next write by
    inference.** *(0.81.0,
    Docker 29.8.1, SR Linux 24.7.1, 2026-11-04)* One SR Linux node, in a lab of its own, was
    deployed in a session of its own, its stdout and stderr each a pipe whose read end only a
    separate reader process held, as `fylgja-core-server` holds them. Four deploys:
    - The reader left alive: containerlab wrote its log lines from 0.18 s to 1.89 s, the last
      `Running postdeploy actions`, then nothing until `Adding host entries` at 44.46 s, and
      exited 0 at 44.6 s, its table on stdout last.
    - The reader killed with `SIGKILL` 2.0 s and 12.0 s in, both in that quiet stretch: the
      deploy ended 35.4 s and 32.2 s in, its wait status `SIGPIPE` (-13). The node's
      container was made and running; no host entries or ssh config were written, and the
      network and the lab directory were left.
    - The reader killed 0.41 s in, after `Creating docker network`: the deploy ended 0.56 s
      in, of SIGPIPE, with no lab directory or container, the network alone left.
    - Which write it died at is inferred, not seen: the line that followed in the run with the
      reader alive, `Creating lab directory` or `Adding host entries`, each written before
      what it names is done.
    - Each lab was torn down after it, by `destroy -t --cleanup` (status 0 each time, 0.99 s
      the one timed) and, for the last, `docker network rm`; no container, network, host entry,
      ssh config or `containerlab` process was left.
    - So the strays the live tier met most likely ended so, which their timings fit: 1.0–1.2 s
      after a kill early in a step's deploy, before it made `n3`, and 11.9–22.0 s after one in
      `n3`'s post-deploy wait (phase 5's steps block; every run with the output piped, the
      whole tier's included).
      Their status was not read: no process the tier runs was their parent once the server
      was killed.
  - **A deploy whose output goes to a file runs to completion once its parent is killed.**
    *(0.81.0, Docker 29.8.1, SR Linux 24.7.1, 2026-11-04)* The same one-node lab, deployed in
    a session of its own by a parent process that opened `deploy.log`, gave the deploy that
    file for stdout and stderr and closed its own copy, as `cli.run` does since D-056. Four
    deploys: the parent left alive (the control) ended in 40.8 s; the parent killed with
    `SIGKILL` 0.47 s, 2.07 s and 12.07 s in, the deploy ran on each time and ended 47.5 s,
    40.4 s and 46.9 s in. Each left the node's container up, the lab's four hosts lines
    (the two markers, the node's IPv4 and IPv6 entries), the ssh config, and a log of 19
    lines ending in containerlab's table. The deploy's exit status was not read (the parent
    that would have reaped it was dead); the table and the hosts block show it completed.
    `destroy -t --cleanup` of each exited 0 and left no container, network, host entry, ssh
    config or `containerlab` process.
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
  *(0.81.0, 2026-11-04)* A different case from this rule's, its own evidence untouched: a
  running three-node lab, after a step's deploy adding `n3` was cut short 10 s in by its
  parent's kill, and that deploy had ended. `n3`'s container was present and running, and its
  push transport answered the resume's probe 18.5–19.7 s after the kill. A plain `deploy -t`
  then took 23.6–25.1 s and made `n3` anew (`StartedAt` moved). What containerlab read to
  recreate it was not read (phase 5's steps block).
- **`--reconfigure` over a healthy lab recreates every node**: three SR Linux nodes in
  40.1 s, every container's `State.StartedAt` moved. *(0.81.0, 2026-11-03)*

**fylgja-core, phase 4: one twin end to end through API 1** *(0.81.0, Docker 29.8.1, SR Linux
24.7.1, 2026-11-03)*

The live end-to-end test (`core/tests/live/test_e2e.py`) runs `three-node` through
`fylgja-core-server` and the thin CLI, over a store in a temporary directory, on a host with
27 GiB available. It passed on its first full run and in the whole tier. As it grew a stricter
kill check and a deletion during the deploy, its next full run failed on a loop defect that
deletion found, since fixed, and the two after passed. *(2026-11-04)*

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
- Its harness moved to `core/tests/live/e2e.py` for phase 5's step module, and the module then
  passed alone again, 12 tests in 631.7 s. The create took 65.9 s. Ready came 62.0–69.7 s
  after a create killed at each boundary, and 73.8 s after one killed 10 s into the deploy.
  The twin was gone 2.7 s after a kill during the destroy, and 1.3 s after a deletion during
  the deploy. *(2026-11-04)*

**fylgja-core, phase 5: `changes` against the dry run** *(0.81.0, 2026-11-04)*

The live module `core/tests/live/test_changes_live.py` deploys the twin `chg-live` through the
local driver and steps it through every pair of the
[step fixtures](../testdata/blueprint/steps/README.md). Before each apply it compares `changes` with
`deploy --dry-run --format json` of the new topology, run with `CLAB_LABDIR_BASE` at the twin's
directory (**The dry run**, below). After it, each node's `State.StartedAt` says whether the
lab did what `changes` answered. Docker 29.8.1, SR Linux 24.7.1, cEOS 4.32.0.2F and alpine
3.24.2, on a host with 26 GiB available. **`changes` and the dry run agreed on every pair, in
every run that included it, and the lab agreed with `changes` on every node.** The one recreate
the dry run does not name is the hot-add, as [D-049](decisions.md#d-049) expects. The module
passed six times: alone in 262.5 s (14 tests), 260.1 s, 258.8 s and 255.6 s (15), its cEOS half
alone, and in the whole tier. The timings below are from the five runs that printed them.

| Step | The dry run (lists left empty are not shown) | `changes` | Apply; nodes made anew |
|---|---|---|---|
| `three-node` → `three-node-n1-disabled`, and back | nothing: every list empty | every node kept | 0.72–0.76 s each; none |
| `three-node` → `three-node-unlinked` | `deleted-endpoints` `n2:e1-2`, `n3:e1-1` | `n2`, `n3` recabled; `n1` kept | 0.77–0.83 s; none |
| → `three-node`, the link back | `added-links` `n2:e1-2 -- n3:e1-1` | `n2`, `n3` recabled; `n1` kept | 0.84–0.89 s; none |
| → `two-node` | `deleted-nodes` `n3`; `deleted-endpoints` `n1:e1-2`, `n2:e1-2` | `n3` removed; `n1`, `n2` recabled | 1.25–1.34 s; none |
| → `three-node`, the node back | `added-nodes` `n3`; two `added-links` | `n3` added; `n1`, `n2` recabled | 23.2–24.3 s; none |
| → `three-node-probed` | `added-nodes` `n1-loop-a`, `n1-loop-b`; two `added-links` | the hosts added; `n1` recabled; `n2`, `n3` kept | 2.23–2.46 s; none |
| → `three-node-probed-moved` | `recreated-nodes` both hosts, each with `node-change-reasons` `config drift: Exec`; two `added-links`; `deleted-endpoints` `n1:e1-10`, `n1:e1-11` | the hosts recreated (`exec`, `links`); `n1`, `n2` recabled; `n3` kept | 2.78–2.88 s; both hosts |
| → `three-node`, the probe gone | `deleted-nodes` both hosts; `deleted-endpoints` `n2:e1-10`, `n2:e1-11` | the hosts removed; `n2` recabled; `n1`, `n3` kept | 1.30–1.36 s; none |
| → `three-node-n3-eos` | `recreated-nodes` `n3`, `config drift: Kind, Image, KindSpecificConfig`; `added-links` `n1:e1-2 -- n3:eth2`, `n2:e1-2 -- n3:eth1`; `deleted-endpoints` `n3:e1-1`, `n3:e1-2` | `n3` recreated (`image`, `kind`, `links`); `n1`, `n2` recabled | 51.7–60.3 s; `n3` |
| `mixed` → `mixed-e2-port` | `added-links` `e1:eth10 -- e2:eth10`, and no node named | `e1`, `e2` recreated (`hot_add`, `links`); `s1` kept | 57.9–59.9 s; `e1`, `e2` |

`three-node-unmanaged` renders the same topology as `three-node-n1-disabled`: both change only
a configuration, so the first row stands for both.

- **The dry run over a running lab** answered `deployed-lab: false`. Each empty node list
  (`added-nodes`, `deleted-nodes`, `recreated-nodes`, `restarted-nodes`, `started-nodes`) was
  `[]`, never null, and no plan carried `lab-name`. Each answer took 0.25–0.41 s.
  - `node-change-reasons` appeared only beside a recreate.
  - `restarted-nodes` and `started-nodes` were empty in every step: every node is under `live`.
  - A link is `"<a> -- <b>"`, in the kind's alias names for SR Linux (`n2:e1-2`), where
    `changes` names SR Linux ports by their production names (`n2:ethernet-1/2`).
  - `deleted-endpoints` lists each port that a node in both topologies no longer has. A
    removed node's ports are not listed, nor is a port that stays with a new far end (a
    moved host's `eth1`).
- **A recabled node kept its incarnation in every step**, SR Linux re-cabled live. A recreated
  node's `StartedAt` moved, and no other node's did. The moved hosts' `exec` lines ran anew:
  `n1-loop-a`'s `eth1` held `10.2.10.2/24` and no `10.1.10.2`.
- **The hot-add recreate holds** (six runs, five of them printing). `apply` ran `docker rm
  -f` on `e1`, then on `e2`, each in 0.4–0.6 s, then a plain `deploy -t`, with no
  `--reconfigure`, from 0.9–1.1 s in. The deploy made both nodes anew with their ports, and
  the apply took 57.9–59.9 s.
  - `s1` kept its incarnation. Its two ports to the recreated nodes, `e1-1` and `e1-2`,
    were listed in its `/sys/class/net` after the step, each with a new ifindex in the two
    runs that read them (`1263` to `1274` and `1265` to `1280`; `1326` to `1337` and `1328` to
    `1343`). So the deploy made new interfaces for them in `s1`'s namespace, since a veth
    goes with its peer's.
  - EOS listed `Et10` on each node the first time it was asked, 0.4–1.0 s after the apply
    returned, the nodes asked in turn. In three runs it read `unknown` at first, with type
    `Unknown`, and it read `connected` (`EbraTestPhyPort`, `full`, `1G`) 0.5–3.5 s after
    the apply.
  - `e1` then listed `Et1`, `Et2/1` and `Et10`, all `connected`.
  - The dry run before the step named neither node.
- **`changes` takes a port not in the deployment applied before for one not present at
  boot**, since it compares two topologies and never asks the node. So a cEOS port removed in
  one step and re-added in the next counts as new: the link back answers `e1` `recreated`
  (`hot_add`, `links`), where the runtime would re-cable it live with no restart (**`cEOS
  live`**, under **Reconciling a running lab**, below). It is a recreate the step does not
  need, in the safe direction: the node gets its port either way. The pure tier pins that
  pair, `mixed` without its `e1:Ethernet1` link and then `mixed`; it was not run live.
- **cEOS's CLI through `docker exec`**: `Cli -c 'show interfaces Ethernet10 status'`, with no
  `-p 15`, took 0.26–0.51 s.
  - It answers status 0 and a table that names the port by its short name, `Et10`, never
    `Ethernet10`.
  - For a port the node lacks it answers status 1, with `% Invalid input at line 1` on stdout
    and stderr empty.
  - After `mixed`'s deploy, EOS answered at its first try, 0.5–0.6 s after the apply
    returned. Its linked ports read `connected` in one run and `unknown` in four.
- **`exec` in a probe host**, through the driver:
  - `ping -c 1 -W 1 127.0.0.1` answered status 0 in 0.13–0.15 s. Its stdout held busybox's
    summary, `1 packets transmitted, 1 packets received, 0% packet loss`.
  - `false` answered `Exec(1, "", "")` in 0.12–0.14 s.
  - **The ping package's own readiness command**, rendered with
    `probe_package.host_values` as the loop's ready phase renders it, is `ip -4 -o addr show
    dev eth1`, ready once its stdout holds the host's address with its prefix. In each of the
    two hosts it answered status 0 in 0.13 s, stderr empty, and one line on stdout, ending in
    a newline, from BusyBox 1.37.0's `ip` (alpine 3.24.2's `/sbin/ip` is a link to busybox).
    `n1-loop-a`'s:
    `1304: eth1    inet 10.1.10.2/24 scope global eth1\       valid_lft forever preferred_lft forever`.
    It starts with the port's ifindex, and the backslash, then seven spaces, is where `-o`
    folds the record's second line into the first. After the probe moved, each host showed
    its new address (`10.2.10.2/24`, `10.2.11.2/24`) and not its old one. *(the sixth run,
    2026-11-04)*
  - An `exec` into a node the lab lacks raised `DriverFailed` in 0.07 s.
- **Docker 29.8.1, for a container that does not exist**:
  - `docker exec <name> true` exits 1 with nothing on stdout. Its stderr is
    `Error response from daemon: No such container: <name>`, ending in a newline.
  - `docker rm -f <name>` exits 0 and writes nothing, in 0.07 s. So a hot-add removal that a
    resume repeats is a plain success, and the driver's `No such container` branch is not
    reached on this host.
- **`admit` with the held deployment** answered the held allocation in each step. It took
  under 0.01 s, and 0.06–0.10 s when it checked that the gated cEOS image was present.
- A deploy of `three-node` took 39.5–40.6 s, and one of `mixed` (two cEOS nodes, one SR Linux)
  55.0–57.1 s. A destroy took 1.1–1.8 s and left no container, host entry, ssh config or
  network. The whole live tier, 42 tests (this module's first 14 among them), took 1207 s.

**fylgja-core, phase 5: verify over gNMI** *(0.81.0, pygnmi 0.8.15, 2026-11-04)*

The live module `core/tests/live/test_verify_live.py` deploys the twin `vfy-live` from
`three-node-probed` through the local driver. It waits for each device node's push transport
and each probe host's readiness command through `exec`, pushes every node's configuration, and
runs `Verifier.verify` with the real gNMI reader and the driver's `exec`. Then it does the same
for `vfy-live-mixed` from `mixed`, its `e1` configuration edited to `hostname leaf-01`. Docker
29.8.1, SR Linux 24.7.1, cEOS 4.32.0.2F and alpine 3.24.2. Its first two runs found the
answers' shapes, which the reader was changed to read (the **gNMI** facts under SR Linux and
cEOS, below), and a stopped node holding a read. The third passed, 15 tests in 292 s, and so
did the fourth, in the whole tier.

- **Verify of `three-node-probed` is `ok` in 2.34–2.35 s** (the three runs after the reader
  was changed): 19 held (8 ports
  enabled, 6 neighbours, 3 claims, 2 bursts) and 5 skipped (the 3 configured host names,
  reported; the 2 synthesized links' neighbours). The three Gets run at once, about 0.5 s;
  the bursts run after them, one at a time.
- **A burst through `exec`**, `ping -c 5 -i 0.2 -W 2`, took 0.93–0.95 s in four runs, every
  echo answered: the first burst's first echo in 60–64 ms, every other in 0.6–0.9 ms.
- **A node stopped is a `failed` verdict**, by `containerlab stop --node n3` (0.68–0.70 s) and
  by `docker stop` (0.50–0.72 s) alike, in 16.2–16.9 s in the last two runs: one
  `verify.node.unread` on `n3`, its read cut at 15 s (`TimeoutError`). `n3`'s six assertions
  and the two neighbours facing it are skips; 12 held, none failed. Before the read was
  bounded, a verify with `n3` just stopped took 73.3 s.
- **`containerlab start --node n3` keeps the node's links** (0.67 s). Its push transport
  answered 29.6–30.4 s later, `e1-1` and `e1-2` in its `/sys/class/net`, and verify was `ok`
  again 9.7 s after that, at its second try, in both runs: the first was `nonconforming`, two
  neighbours not yet listed.
- **`docker start` loses them.** Started again after `docker stop`, `n3`'s push transport
  answered 29.7–30.0 s later (four runs). Its `/sys/class/net` no longer listed `e1-1` and
  `e1-2`, holding only `gway-2800`, `lo`, `mgmt0`, `mgmt0-0` and `monit_in` (three runs). The
  far ends were not read; since a veth's peer goes with it, they are taken to have lost
  theirs. Verify was `nonconforming`: each end of `n3`'s two links lists no neighbour (4
  failed, 15 held, 5 skipped), steady over 127 s of polling (18 tries) in one run and the
  same at each later run's one read, while each port's admin state still read `enable`.
- **A configured node's host name is reported**: on `vfy-live-mixed`, `e1`'s skip names
  `leaf-01`, and the neighbours facing it, `s1:ethernet-1/1` and `e2:Ethernet1`, held against
  `leaf-01`. Verify was `ok` at its first try, in 0.27–0.46 s: 15 held (6 ports, 6
  neighbours, 3 claims) and 3 skipped.
- **An abandoned read keeps its thread.** pygnmi's Get has no deadline, so a read cut at its
  budget keeps its thread until the TCP connection fails: one ended 38.8 s after `docker
  stop`, seen when `asyncio.run` waited for it to close the loop, the reads then running on the
  loop's default executor (min(32, CPUs + 4) workers, 14 on this 10-CPU host), where under
  sustained node loss healthy nodes' reads could queue behind abandoned ones. That design note
  is answered by phase 5's plan 5: each read is a daemon thread of its own, at most 16 at once
  (`gnmi.READ_THREADS`) and one per node's address, so a node whose last read still runs is
  unreadable at once and its retries never add threads, and a read finding all 16 busy waits
  for one within its budget. The pure tier holds each of these. On Python 3.14.4 a read held in
  its thread neither held `asyncio.run`'s close nor the process's exit: the process exited in
  about 1 s with the read held 60 s, where with a `ThreadPoolExecutor` it was still waiting at 30 s.
  Not exercised against a node.
- **A TLS dial whose channel is not ready in time waits again, with the process's environment
  changed.** pygnmi's `wait_for_connect` (`pygnmi/client.py`, about line 320) catches the
  `FutureTimeoutError` of a channel that is not insecure, sets `GRPC_SSL_CIPHER_SUITES=HIGH`
  in `os.environ`, where it stays for the rest of the process, and waits another
  `gnmi_timeout` on the same channel. The reader's budget cuts the read first; its thread
  waits on. Read from pygnmi 0.8.15's source, not exercised.
- **An abandoned read no longer holds up a clean exit of `fylgja-core-server`.**
  `uvicorn.Server.run` is `asyncio.run`, whose `Runner.close` joins the default executor for up
  to 300 s (`asyncio.constants.THREAD_JOIN_TIMEOUT`) once `serve()` has returned, and the
  interpreter's exit joins every `ThreadPoolExecutor`'s workers. While the reads ran on the
  default executor, a read thread still dialling kept the process until it ended, SIGINT's exit
  included. A read's daemon thread is in neither, and the exit does not wait on a daemon thread.
  SIGTERM was never held: uvicorn restores the default handler and raises the signal it caught
  inside `serve()`, so the process ends there, before the join. Read from Python 3.14.4's
  `asyncio.runners` and `concurrent.futures.thread` and uvicorn 0.54.0's
  `Server.capture_signals`; the reads' part held by the pure tier, the server's not exercised.
- In the module's four runs, a deploy of `three-node-probed` took 36.9–42.9 s, its push
  transports answered 3.7–4.8 s later, each host showed its address at the first try
  (0.13–0.14 s), and each push took 2.3–3.1 s. A deploy of `mixed` took 56.3–57.4 s (three
  runs), its cEOS nodes' transports answered 10.1–15.0 s later, and the pushes took 2.7–4.4 s
  (cEOS) and 2.4–3.5 s (SR Linux). A destroy took 1.7–1.9 s and left no container, host
  entry, ssh config or network. The whole live tier, 58 tests (this module's 15 among them),
  took 1476 s.

**fylgja-core, phase 5: steps end to end** *(0.81.0, 2026-11-04)*

The live module `core/tests/live/test_e2e_step.py` runs `fylgja-core-server` and the thin CLI,
with the harness phase 4's module uses, now `core/tests/live/e2e.py`, and the server's step wait
at 90 s (`FYLGJA_STEP_WAIT_S`). It creates four twins:
- `e2e-step` from `three-node`. `fylgja-core twin step` takes it to SR Linux
  [step fixtures](../testdata/blueprint/steps/README.md) from their base, and back where the
  next step needs the base, then turns its `n3` into a cEOS node. Until the fix wave it took
  `three-node-unlinked`, `two-node` and `three-node-probed`; from the fix wave on, also
  `three-node-n1-disabled`, `three-node-unmanaged` and `three-node-probed-moved`, so every SR
  Linux fixture (**The fix wave's runs**, below).
- `e2e-step-eos` from `mixed`. Its two cEOS nodes are given a port.
- `e2e-step-kill` from `two-node`. It is stepped to `three-node`, a node added, with the server
  killed at each phase boundary, during the deploy, and before a deletion.
- `e2e-step-cancel` from `two-node`. Its step to `three-node` is cancelled during the deploy,
  and the diverged twin is then deleted.

After each step the module reads back the record, the run's verdict and events, each
container's `State.StartedAt` through `docker`, and a verify through the API. Docker 29.8.1,
SR Linux 24.7.1, cEOS 4.32.0.2F and alpine 3.24.2, on a host with 26–27 GiB available when it
was read, before the fix wave's runs; the earlier runs' was not recorded.

**The steps passed in each of their five runs.** The first two had only the SR Linux steps: 8
tests in 131.3 s and 129.3 s. The next two had the cEOS scenarios too: 14 tests in 371.0 s and
376.8 s. The fifth was the whole module. Each range below is over the runs that included its
step: five for the steps the first two runs had, three for the probe removed and the rest.

The kill scenarios ran three times: twice alone, and once with the whole module, 23 tests in
833.6 s. The first run's deletion found the defect [D-055](decisions.md#d-055) fixes. With
the fix, the kill scenarios passed alone (9 tests in 472.2 s), and the whole module passed.
The whole live tier's runs and the fix wave's, the last bullets, are not folded into these
ranges.

- **Every step that changed a twin ran as a `step` run and ended `ok`**, `last_step` `stepped`
  at `flows`. Ready was True and Stepping False, both for `twin.ready`, and every device node
  held the new bundle. Each step no kill cut short ran one plain `containerlab deploy`, with no
  `--reconfigure`.
  The record's incarnations were the containers' `StartedAt`, and each run's events had no gap.
- **A link removed** (`three-node` → `three-node-unlinked`): exit 0 in 1.9 s end to end,
  the apply 1.03–1.11 s. No node was made anew, nothing was readied, and each node's push
  was `skipped`. The wait held at its first try, `after_s` 0.47–0.48 s. Verify then was `ok` in
  0.53–0.54 s: 11 held (4 ports, 4 neighbours, 3 claims), and the 3 configured host names
  reported. No finding named the removed link's ends.
- **The link added back** (→ `three-node`): 1.9–2.0 s, the apply 1.08–1.14 s, every node kept
  and its push `skipped`. The wait held at its first try (0.47–0.49 s), and verify was `ok` with
  every neighbour held, 15 held and 3 skipped. So both re-cabled ends listed their far end
  within about half a second of the apply's return. Whether that was a fresh LLDP frame or an
  entry kept since the link's removal 4 s earlier was not read.
- **A node removed** (→ `two-node`): 2.3–2.4 s, the apply 1.48–1.60 s. `n3` was gone from the
  record and from `docker ps -a`. `n1` and `n2` kept their incarnations, and their pushes were
  `skipped`. The wait held at 0.46–0.49 s, and verify was `ok`, 6 held and 2 skipped.
- **A node added** (→ `three-node`): 33.1–34.3 s end to end. The apply took 21.7–23.9 s,
  `n3`'s push transport answered 6.2–7.6 s later, and its push took 2.8–3.0 s. Only `n3` was
  readied (`ready done`) and pushed (`push done`); `n1` and `n2` kept their incarnations, their
  pushes `skipped`. The wait held at its first try, 0.47–0.48 s after the push, with the new
  links' neighbours listed at both ends. Verify was `ok`, 15 held.
- **A probe added** (→ `three-node-probed`): 15.2–16.7 s end to end. The apply took
  2.40–2.59 s, and both hosts showed their addresses at the first try, 0.18–0.25 s for the two.
  Every device node kept its incarnation, and its push was `skipped`. **The wait held after
  12.1–13.6 s, at its second try**, in all five runs. That is inferred from the 5 s poll: a held
  try with the bursts takes about 2.4 s, so the first try took about 4.7–6.2 s and did not
  hold. The run keeps only the last try's verdict, so what the first one found was not seen.
  The verdict's `loss` listed `n1-loop` from `a` and from `b`, each `not_started`. Verify then
  was `ok` in 2.39–2.42 s, 19 held (the two bursts among them) and 5 skipped (the host names
  and the probe endpoints' neighbours). **So SR Linux takes a port added after boot**: `n1`,
  its incarnation kept, was cabled live onto `ethernet-1/10` and `ethernet-1/11`, ports it had
  no link on at boot, and both bursts held across them. `changes` relied on that
  (`hot_add_ports: true`), answering `n1` recabled, not recreated.
- **A step to the bundle the twin runs** (`twin step --bundle` with the twin's own bundle,
  a new spec with the same bundle): exit 0 in 0.20–0.22 s. `last_step` was `unchanged` at
  `compiled`, from and to the same bundle, and the run's only events were `compile`'s. Nothing
  was deployed and no incarnation moved.
- **The probe removed** (→ `three-node`): 2.4–2.6 s, the apply 1.58–1.70 s. Both hosts were
  gone from the record and the lab. The three nodes kept their incarnations and their pushes
  were `skipped`. `loss` was `[]`, and the wait held at 0.47 s.
- **A kind change** (→ `three-node-n3-eos`, with `--allow-restart`): 68.8–71.8 s end to end.
  The apply took 52.6 s, and `n3` was made anew from `ceos:4.32.0.2F` while `n1` and `n2`,
  re-cabled live, kept their incarnations. `n3`'s eAPI answered 12.2–14.2 s later, and its push
  took 3.1–4.0 s; `n1` and `n2` were neither readied nor pushed. The wait held at its first try,
  0.46–0.47 s. Verify was `ok` in 0.48–0.51 s, 15 held and 3 skipped, `n3`'s host name
  reported as `n3`. **LLDP across the two kinds**, read from each end after verify (the same
  in all three runs):
  - SR Linux's state, through a JSON-RPC `get` of
    `/system/lldp/interface[name=ethernet-1/2]/neighbor`. On `n1` it listed one neighbour,
    `system-name` `n3`, `port-id` `Ethernet2`, `port-id-type` `INTERFACE_NAME`; on `n2`, `n3`
    on `Ethernet1`.
  - EOS's `show lldp neighbors | json` on `n3`, through `docker exec`. It listed `Ethernet1`
    to `n2` on `ethernet-1/2` and `Ethernet2` to `n1` on `ethernet-1/2`, each with `ttl` 120,
    and nothing else, no `Management0` entry among them.
  - So each kind names the far port by its production name, which verify judges against.
- **A cEOS port added without `allow_restart`** (`mixed` → `mixed-e2-port`): exit 1 in 0.3–0.4 s,
  the run `rejected`. Its only errors were `step.restart.required` on `e1` and on `e2`, and
  the server logged the refusal before anything was touched. Ready and Stepping were False for
  `step.restart.required`, and `last_step` was `rejected` at `planned`. The record's bundle,
  blueprint, deployment and `phase` (the create's) were unchanged, and so were what
  each node held. The run's events were `compile`'s, `admit`'s and `plan`'s alone. Nothing was
  deployed, and every container's `StartedAt` was unchanged.
- **The same with `--allow-restart`**: exit 0 in 74.5–76.6 s, from a twin that was Ready False.
  The apply took 58.9–59.6 s: `docker rm -f` on `e1`, on `e2` 0.58–0.71 s later, then the plain
  deploy 1.2–1.3 s in. `e1` and `e2` were made anew and `s1` kept its incarnation. The two cEOS
  nodes were readied in 8.5–10.6 s together and pushed (`push done`) in 5.3–6.2 s together;
  `s1` was neither readied nor pushed (`push skipped`). The wait held at its first try,
  0.47–0.49 s. EOS listed `Et10` `connected` on both nodes at the first ask, 0.4–0.6 s for the
  command (`routed`, `full`, `1G`, `EbraTestPhyPort`). Verify was `ok` in 0.48–0.51 s, 19 held
  and 3 skipped.
- **EOS on a port the node lacks**: on `e2`, after `mixed`'s create had ended,
  `Cli -c 'show interfaces Ethernet10 status'` answered status 1 in all three runs. Its stdout was
  `% Interface does not exist at line 1`, after the echoed command. Plan 3's module read
  `% Invalid input at line 1` for the same command 0.5 s after the deploy returned. What makes
  the two differ was not read.
- **A server killed after each phase boundary of a step ended with the same run `stepped`**, in
  every one of the three runs. The kill came with SIGKILL as soon as the watch showed
  `last_step.phase` at the boundary. Killed after `verified`, the run had already ended, and no
  pass resumed it. Killed after `compiled` or `admitted`, the run resumed after `planned` in five
  of six tries (the table). Each run so ended:
  - was the same step run, ended `ok`, with no second step run;
  - ran no `--reconfigure`;
  - left one lab, of the three nodes;
  - left `n3` holding the bundle;
  - and verify then was `ok`, 15 held.

  | Killed after | Resumed after (the server's log) | `apply started`, deploys | Kill to `stepped` |
  |---|---|---|---|
  | `compiled` | `compiled` once, `planned` twice | 1 and 1 once; 2 and 1 twice | 50.6–59.8 s |
  | `admitted` | `planned` | 2 and 2 | 40.7–44.5 s |
  | `planned` | `planned` | 2 and 2 | 41.8–44.5 s |
  | `applied` | `applied` | 1 and 1 | 8.6–11.7 s |
  | `ready` | `ready` | 1 and 1 | 4.2–5.6 s |
  | `pushed` | `pushed` | 1 and 1 | 1.6–1.7 s |
  | `verified` | none: the run had ended | 1 and 1 | 1.1–1.3 s |

  - **The first three phases are recorded within about 50 ms**, so a kill that follows the
    record of `compiled` or `admitted` landed after `planned` in five of six tries.
  - **A deploy running at the kill ended 1.0–1.2 s after it, without making `n3`**: at its
    next write, by inference (**A killed or partial deploy**, above), which came before it
    created `n3`'s container. This happened when the kill followed `admitted` or `planned`. The
    resume's probe took 7.3–9.3 s: `n1` and `n2` answered, and `n3` was absent, so not silent.
    It found no stray deploy to wait for and applied plainly. That deploy made `n3`, its
    `StartedAt` 10.2–10.9 s after the kill.
  - **The kill after `compiled` was the twin's first step after its create.** That step's
    deploy of `n3` took 38.8–41.9 s, where every later deploy adding it took 21.6–24.2 s. Why
    was not read.
  - **Killed after `verified`, the run had already ended in each run**: the `flows` phase and
    the run's end take about 10 ms. The record read `stepped` after the restart.
- **Killed 10.1–10.2 s into the step's deploy** (three runs): the deploy, in `n3`'s post-deploy
  wait, ran on 12.0–12.8 s after the kill and ended, at its next write by inference, before it
  wrote the host entries. The resume's probe waited 18.5–19.7 s for `n3`'s push transport and
  found no stray left, so the driver did not wait. It applied plainly: that deploy took
  23.6–25.1 s and made `n3` anew, its `StartedAt` 21.1–21.9 s after the kill, though the probe
  had found its container present, running and answering. Why containerlab recreated it was
  not read. The run showed 2 `apply started` and 2 deploys, with no `--reconfigure`. It was
  `stepped` 54.6–55.3 s after the kill, and verify was `ok`.
- **A deletion asked 1.1–1.3 s after a kill 5 s into a step's deploy**, the deploy still
  running. The step's resume was cancelled and ended `diverged` (`step.diverged`), its apply
  begun.
  - In the first run, the record still named the `two-node` deployment. The destroy ran at
    once beside the deploy: it removed `n1` and `n2` and left `n3`, which the deploy had
    started 0.6 s in. Every retry, on the loop's backoff from 1 s doubling to 60 s, failed on
    the network (**What the local driver reads and
    runs**, above), and the deletion never completed: the defect D-055 fixes.
  - With the fix, in two runs, the destroy logged that it waited for the stray deploy, for
    16.6–16.7 s; the deploy ran on 19.2–19.5 s after the kill and ended, at its next write by
    inference. The destroy then removed `n3` with `docker rm -f` and ran containerlab's
    destroy, and the destroy run ended `ok`. The twin was gone 18.1–18.2 s after its deletion
    was asked. No container, host entry, ssh config, network or `containerlab` process was
    left.
- **A step cancelled 5 s into its deploy** (`e2e-step-cancel`, `two-node` → `three-node`):
  the same in both runs, alone and in the whole tier.
  - `POST /v1/runs/{id}/cancel` answered 202, and the run ended `diverged` 0.40–0.41 s later.
    Its one error was `step.diverged`: "The step was cancelled during apply, after its apply
    began; the twin is left as it stands, diverged, and accepts only deletion. The last phase
    it recorded is planned." The message goes on to name what each node holds.
  - The cancel killed the deploy's process group, so no `containerlab` process was left and
    nothing ran on.
  - The record: Diverged True and Ready False, both for `step.diverged`; `last_step`
    `diverged` at `planned`; its bundle and deployment still `two-node`'s. The lab held `n1`,
    `n2` and `n3`.
  - A `PUT` of another spec answered `409 twin.diverged`.
  - `twin verify` answered `ok`, exit 0, against the running bundle: 6 held and 2 skipped.
  - `twin destroy` exited 0 in 1.7–2.0 s. The destroy removed `n3`, which the
    `two-node` deployment it destroyed does not name (D-055), with no stray deploy to wait
    for, then ran containerlab's destroy, which alone would have left `n3` (**What the local
    driver reads and runs**, above). Nothing was left on the host.
- The creates took 60.2–64.0 s (`three-node`) and 80.3–86.3 s (`mixed`), verify of `mixed` then
  `ok` in 0.29–0.50 s. The destroys took 1.7–2.0 s, and each left no container, host entry, ssh
  config, network or `containerlab` process. The server answered 0.71–1.27 s after each start,
  the kills' restarts among them. Each run's log was all JSON, with no line holding a password:
  226 lines in each SR Linux run, 390 in each cEOS run, and 713, 1013 and 1072 in three of the
  runs with the kills (the first, the whole module's, and the tier's). Those were read by hand;
  from the fix wave on, the module's last test asserts it, the token too (`e2e.assert_log_clean`,
  which phase 4's module runs as well).
- **The whole live tier**, 82 tests, passed in 2371.3 s (39.5 min), this module's 24 among
  them. Its run of this module, the sixth of the steps and the fourth of the kills, gave these
  figures outside the ranges above:
  - the node added: 34.6 s end to end, with a 3.3 s push;
  - the kind change: an apply of 52.8 s;
  - the cEOS restart: 72.6 s end to end, the two nodes readied in 7.0 s together;
  - the kill 10 s into the deploy: `stepped` 51.6 s after the kill, the deploy having run on
    11.9 s after it, and `n3` started 19.7 s after the kill;
  - the deletion, asked 0.8 s after a kill 5 s into the deploy: gone 20.3 s after it was
    asked, the destroy having waited 18.9 s for the deploy, which ran on 21.1 s after the kill.

  Every kill resumed as the table says. The cancel was as its bullet says. The host was left
  clean.
- **The module alone took about 15 minutes** before the fix wave: 833.6 s for its first 23
  tests, and 75.3 s for the cancel alone.
- **The fix wave's runs** *(2026-11-04)*. The module gained the three SR Linux fixtures the runs
  above left out, each stepped to from its base, a dry run and a verify through the
  CLI, and the log check: 31 tests, which passed alone in 937.3 s, on a host with 26–27 GiB
  available. A run before it stopped at the dry run's test, whose expected exit status was wrong
  (a recreate needs `allow_restart`, probe hosts included); the 11 tests before it passed. Where
  both runs had a step, its range is over the two.
  - **A port disabled by intent** (→ `three-node-n1-disabled`), and enabled again (→
    `three-node`): 1.8–1.9 s each end to end, the apply 0.94–1.03 s. No node was made anew or
    readied, and every push was `skipped`, `n1`'s configuration being the same. The wait held at
    its first try, 0.47–0.48 s. Verify of the disabled port's twin was `ok`, 12 held and 6
    skipped: `n1:ethernet-1/2`'s admin state and both neighbours of its link to
    `n3:ethernet-1/2` are skips, beside the three host names.
  - **A configuration dropped** (→ `three-node-unmanaged`, `n2` with none): 1.8 s, the apply
    0.96–1.00 s. Every push was `skipped`, `n2`'s among them, and every node held the new bundle
    (D-048). `n2`'s running configuration kept its pushed `ethernet-1/1` description,
    `to n1 ethernet-1/1`, read by a JSON-RPC `get` of the running datastore. Verify was `ok`, 15
    held and 3 skipped: `n2`'s host name asserted and held, its claim a skip. Given back (→
    `three-node`): 4.8–5.0 s, `n2` alone pushed, in 3.0–3.2 s.
  - **`twin verify --json` through the CLI** on `three-node-probed`: exit 0 in 2.5 s, `ok`, 19
    held and 5 skipped, both bursts held.
  - **A dry run of the probe moved** (`twin step --dry-run --json`, → `three-node-probed-moved`):
    exit 1 in 0.2 s, `rejected` with `step.restart.required` on `n1-loop-a` and `n1-loop-b`. Its
    `changes` were the driver's for that pair in plan 3's table, above: the hosts `recreated`
    (`exec`, `links`), `n1` and `n2` `recabled`, `n3` `kept`. No spec was written, nothing was
    deployed, and no incarnation moved.
  - **The probe moved** (→ `three-node-probed-moved`, with `--allow-restart`), one run: 15.9 s,
    the apply 3.16 s. Both hosts were made anew and readied (0.28 s together), no device node;
    every push was `skipped`. The wait held after 12.04 s, at its second try by the probe
    added's inference. Verify was `ok`, 19 held, both bursts from the hosts' new addresses
    through `n2` among them: `n2` too took `ethernet-1/10` and `ethernet-1/11` live. The probe
    removed from `n2` after it took 2.4 s, the apply 1.58 s.
  - Its figures outside the ranges above, the 31-test run's:
    - the link removed: an apply of 1.02 s; the node removed: 2.2 s, the apply 1.43 s;
    - the node added: an apply of 24.42 s, `n3` readied in 5.43 s and pushed in 3.43 s;
    - the probe added: the wait held after 12.06 s; the step to the bundle it runs: 0.23 s;
    - the kind change: an apply of 53.28 s, `n3` readied in 12.16 s;
    - the cEOS refusal: 0.5 s; the cEOS restart: 73.0 s end to end, the apply 58.19 s, the
      two nodes readied in 8.27 s, the wait held at 0.26 s;
    - the kill after `compiled`: `stepped` 60.0 s after the kill; after `admitted` and
      `planned`, `n3` started 10.1 s and 11.0 s after the kill;
    - the kill 10 s into the deploy: `stepped` 55.6 s after it, `n3` started 22.2 s after it;
    - the deletion, asked 1.6 s after a kill 5 s into the deploy: gone 20.5 s after it was
      asked, the destroy having waited 18.9 s for the deploy, which ran on 22.0 s after the kill;
    - the cancel: the run ended 0.51 s after it was asked; the server's starts: 0.75–1.48 s.

    Every kill resumed as the table says, and every stray a resume met had ended before its
    probe was done. The server logged 1240 lines. The host was left clean.
  - **The whole live tier** then passed, 89 tests in 2406.7 s (40.1 min), this module's 31
    among them. Phase 4's module logged 485 lines and this one 1240, every one JSON with no token
    or password. Its run of this module gave these figures outside the ranges above, the fix
    wave's included:
    - the link added back: an apply of 1.16 s; the verify through the CLI: 2.4 s;
    - the probe moved: an apply of 3.01 s, its hosts readied in 0.21 s, the wait held after
      12.20 s; the probe removed from `n2`: an apply of 1.52 s;
    - the kind change: 68.6 s end to end, the apply 52.32 s, `n3` readied in 12.14 s;
    - the cEOS refusal: 0.2 s; the cEOS restart: an apply of 60.00 s, the two nodes readied in
      8.49 s;
    - the kill 10 s into the deploy: `stepped` 53.2 s after it, the deploy having run on 12.9 s
      after it, and `n3` started 20.5 s after it;
    - the deletion, asked 1.1 s after a kill 5 s into the deploy: gone 20.4 s after it was
      asked, the destroy having waited 18.9 s for the deploy, which ran on 21.5 s after the kill;
    - the cancel: the run ended 0.51 s after it was asked.

    Every kill resumed as the table says; no stray was left for a resume to wait for. The host
    was left clean.
  - **The whole live tier with the deploy's output in a file** ([D-056](decisions.md#d-056))
    *(0.81.0, Docker 29.8.1, 2026-11-04)*: 89 tests in 2391.2 s (39.9 min), 88 passed and one
    failed as the change foretold, the driver's live test listing the twin's directory, which
    now holds `deploy.log` beside the topology; its expectation was corrected and that module
    passed alone, 7 tests in 209.5 s, the log's table asserted. A stray deploy now runs to
    completion:
    - the kills after `admitted` and `planned`, both landing inside the deploy: the deploy ran
      on 23.4 s and 22.8 s after the kill, about a step's whole deploy of `n3`, and `n3`
      started 0.5 s after the kill; the resume ran a second deploy, `stepped` 39.7 s and
      40.2 s after the kill;
    - the kill after `compiled`, landing after `planned` before the deploy: no stray, one
      deploy, `stepped` 55.9 s after the kill;
    - the kill 10.2 s into the deploy: the deploy ran on 14.0 s after it, `stepped` 30.3 s
      after it, and `n3` kept the start it had 9.7 s before the kill: the resume's plain deploy
      no longer made it anew, as it had in every run with the output piped (why was not read;
      the orphan now finishing `n3`'s post-deploy is the likely cause);
    - the deletion, asked 1.2 s after a kill 5 s into the deploy: the destroy logged that it
      waited for the stray from 22:36:47.996 to 22:37:06.821, 18.8 s, so the stray ended about
      20 s after the kill; gone 20.2 s after it was asked. (The test's own figure, 21.4 s, is
      read when the destroy has returned, an upper bound, as the earlier deletion figures are.)
    - the create killed 10 s into its deploy (phase 4's module): Ready 70.5 s after the create
      with no deploy by the resume, the hosts block and the ssh config present, which the test
      now asserts.

    No resume of a step waited for a stray: each stray had ended before the resume reached its
    apply. Why was not read; the resume's probe waiting for `n3`'s push transport, which answers
    once the orphan's post-deploy is done, is the likely reason. The host was left clean.

**The dry run**

- `clab deploy --dry-run --format json` prints a plan on stdout (`added-nodes`,
  `deleted-nodes`, `recreated-nodes`, `restarted-nodes`, `added-links`,
  `deleted-endpoints`, `node-change-reasons`) and writes nothing. *(2026-10-01; 26.04, 2026-10-08)*
  On Ubuntu 26.04 every plan also carried `started-nodes`, and no `deployed-lab: false`
  plan carried `lab-name`, which every such plan on 24.04 at the same release did. A
  `deployed-lab: true` answer still carries it. *(26.04, 2026-10-08)* *(0.81.0, 2026-11-04)*
  The same members on 0.81.0, `started-nodes` among them. Over a running lab every empty list
  is `[]`, and `node-change-reasons` appears only beside a recreate (phase 5's block, above).
  Seen by hand, outside the live module: with no container of the lab, the answer was
  `deployed-lab: true` with `lab-name` and every list null, in 0.16 s.
- **That dry run must run with `CLAB_LABDIR_BASE` at the running lab's directory.**
  containerlab decides a recreate from `.state.clab.yaml` there, so from any other base an
  image or kind change is invisible. *(2026-10-01; 26.04, 2026-10-08)* From another base while the
  lab runs, the answer is still a plan, `deployed-lab: false`, that misses the change (a
  kind change showed only as a restart, for `deleted endpoint`). `deployed-lab: true` with
  `lab-name` and every list `null` comes only when no container of the lab exists.
  *(26.04, 2026-10-08)* *(0.81.0, 2026-11-04)* At the running twin's directory, the dry run
  read the lab (`deployed-lab: false`) and named the kind and image change a recreate (phase
  5's block). The other-base half was not run again.

**Reconciling a running lab**

- **`clab deploy` without `--reconfigure` reconciles a running lab.** *(2026-10-01; 26.04,
  2026-10-08)*
  - A link added or removed re-cables SR Linux live and restarts a cEOS node in place
    (3.5–14.6 s for the apply). *(0.81.0, 2026-11-04)* The SR Linux half: 0.77–1.34 s,
    with no `StartedAt` moved (phase 5's block). The cEOS restart, under the `restart`
    mode, was not run. *(0.81.0, 2026-11-04)* Through `twin step`, an SR Linux link removed
    took 1.03–1.11 s and added 1.08–1.14 s, with no node made anew (phase 5's steps block).
  - A node added is created with containerlab's post-deploy (31.3 s). *(0.81.0,
    2026-11-04)* One SR Linux node in 23.2–24.3 s, two `linux` hosts in 2.23–2.46 s.
    *(0.81.0, 2026-11-04)* Through `twin step`, one SR Linux node in 21.7–23.9 s and two
    hosts in 2.40–2.59 s.
  - An image or kind change is a recreate (20.3 s, 58.7 s with a far cEOS end's restart).
    *(0.81.0, 2026-11-04)* SR Linux to cEOS in 51.7–60.3 s, the SR Linux far ends re-cabled
    live. A `linux` node whose `exec` lines change is recreated too (2.78–2.88 s for two).
    *(0.81.0, 2026-11-04)* Through `twin step`, SR Linux to cEOS in 52.6 s, the SR Linux far
    ends re-cabled live (phase 5's steps block).
  - A node removed is deleted (0.85 s); nothing to do takes 0.39 s. *(0.81.0,
    2026-11-03)* A repeat deploy of a running three-node lab, with nothing to do, took
    0.73 s and moved no node's `State.StartedAt`. *(0.81.0, 2026-11-04)* A node removed
    took 1.25–1.34 s. *(0.81.0, 2026-11-04)* Through `twin step`, 1.36–1.60 s over 29
    steps, and a probe's two hosts 1.58–1.70 s.
  - **A node whose container is gone is made anew by a plain deploy**, with its ports and
    its links to the nodes that stayed. *(0.81.0, 2026-11-04)* Two cEOS nodes removed with
    `docker rm -f` came back in 57.9–59.9 s, in the five runs that printed it. The node that
    stayed listed its two ports to them with a new ifindex each, in the two runs that read
    them (phase 5's block). *(0.81.0, 2026-11-04)* Through `twin step`'s hot-add, the two
    cEOS nodes came back in 58.9–59.6 s, each listing `Et10` `connected` (phase 5's steps
    block).
  - On Ubuntu 26.04: an SR Linux link added in 0.66 s and removed in 0.59 s, live, with
    neither node's `StartedAt` moved; a link between cEOS and SR Linux 3.2 s; a node added
    37.0 s; a kind change 53.6 s; a node removed 1.04 s; nothing to do 0.53 s.
- **SR Linux steps with production names**: a link removed in 0.75 s and added in 1.0 s,
  a node added in 40.7 s and removed in 2.2 s; no existing node restarted, and pushes were
  kept. *(2026-10-30)* *(0.81.0, 2026-11-04)* The same through `twin step`. Each of those
  steps kept every existing node's incarnation, skipped its push, and kept what it held
  (phase 5's steps block).
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
- **Through pygnmi 0.8.15**, verify's reader, in the four runs of
  `core/tests/live/test_verify_live.py`, three alone and one in the whole tier. *(0.81.0,
  2026-11-04)*
  - The dial that works: `gNMIclient(target=(address, 57400), username=…, password=…,
    insecure=False, skip_verify=True, gnmi_timeout=15)`, then `get(path=[…],
    encoding="json_ietf")`. pygnmi fetches the boot-time certificate itself
    (`ssl.get_server_certificate`, with no timeout) and overrides the target name with the
    certificate's names. It logs `ssl_target_name_override is applied, should be used for
    testing only!` at WARNING on every dial, through a stdout handler of its own.
  - **One notification per path asked**, in the order asked, its `prefix` null and each
    update's path carrying every element's module prefix. The host name is one update at
    `srl_nokia-system:system/srl_nokia-system-name:name/host-name`, `n1` on `n1`. An admin
    state is one at `srl_nokia-interfaces:interface[name=ethernet-1/1]/admin-state`, `enable`
    on every cabled port.
  - **A neighbour list comes back at the entry above the path asked**, as gnmic found:
    `/system/lldp/interface[name=ethernet-1/1]/neighbor` is answered by one update at
    `srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]`, whose value is
    `{"neighbor": [ … ]}`. The list's one entry has unprefixed members: `id` and `chassis-id`,
    the far node's MAC (`chassis-id-type` `MAC_ADDRESS`); `system-name`, `n2`; `port-id`,
    `ethernet-1/1` (`port-id-type` `INTERFACE_NAME`); `port-description`, the far port's;
    `system-description`, `SRLinux-v24.7.1-330-g38f237abfe n2 …`; `capability`,
    `first-message` and `last-update`.
  - **No value is a notification with no `update` member**, and no error: a port cabled to a
    probe host (`ethernet-1/10`; the host speaks no LLDP), an uncabled port's neighbour
    (`ethernet-1/3`), and a port the chassis lacks (`ethernet-1/99`).
  - One node's Get of its 2, 5 or 9 paths, the dial and the certificate fetch included, took
    0.25–0.48 s.
  - **A refused login** answers `UNAUTHENTICATED` in 0.27 s (three runs), its details
    `Username or password is not valid`. pygnmi logs `GRPC ERROR Host: <address>:57400,
    Error: <details>` at CRITICAL, which quotes no login.
  - **A node just stopped holds the dial**, in pygnmi's certificate fetch. Unbounded, a read
    begun at `docker stop` ended with an `OSError` about 71 s later. In another run the
    fetch's thread ended 38.8 s after the stop, and a read begun then failed with `OSError`
    within 5 s. The reader cuts a read at its 15 s budget: `TimeoutError` at 15.01–15.02 s,
    after `docker stop` and after `containerlab stop` alike.

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

**gNMI** *(pygnmi 0.8.15, 0.81.0, 2026-11-04)*

Verify's reader, in the four runs of `core/tests/live/test_verify_live.py` (three alone, one in
the whole tier) on `mixed`, its `e1` configuration naming the host `leaf-01`.

- The dial that works: `gNMIclient(target=(address, 6030), username=…, password=…,
  insecure=True, gnmi_timeout=15)`, plaintext, then `get(path=[…], encoding="json_ietf")`.
- **One notification per path asked**, in the order asked, its `prefix` null, and an update's
  path carries no module prefix. The host name is one update at `system/state/hostname`:
  `leaf-01` on the configured `e1`, `e2` on `e2`. An admin state is one at
  `interfaces/interface[name=Ethernet1]/state/admin-status`, `UP` on every cabled port,
  `Ethernet2/1` and `Ethernet3/1/1` among them.
- **A neighbour list comes back one update per entry, below the path asked**:
  `/lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor` is answered at
  `lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor[id=1]`.
  - The entry's members are prefixed: `openconfig-lldp:id`, `"1"`, the port's own index and
    not the chassis; and `openconfig-lldp:state`.
  - The state holds unprefixed `id`, `system-name`, `port-id` (`port-id-type`
    `INTERFACE_NAME`), `chassis-id` (`MAC_ADDRESS`), `port-description` and
    `system-description`, beside Arista's prefixed `arista-lldp-augments:last-update-time`
    and `arista-lldp-augments:registration-time`.
  - An EOS neighbour's entry also holds `management-address` and `management-address-type`
    (`AFIPv4`); an SR Linux neighbour's does not.
  - An EOS far port's id is its own name, one to one with production on cEOS (`Ethernet2/1`,
    `Ethernet1`), and SR Linux's its own (`ethernet-1/1`).
- **No value is a notification with no `update` member**: a configured port with no link's
  neighbour (`Ethernet10`) and a port the node lacks (`Ethernet99`).
- One node's Get of its 2 or 5 paths took 0.20–0.21 s.
- **A refused login** answers `UNAUTHENTICATED` in 0.12–0.14 s (three runs), its details
  `Authentication failed`, which pygnmi's CRITICAL line quotes; no login is in it.
- **A pushed host name reached both neighbours' LLDP by their first read**: after `e1`'s push
  of `hostname leaf-01`, `e2` and `s1` listed `leaf-01` as `e1`'s system name when first read,
  after `e2`'s and `s1`'s own pushes, under 10 s later.

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
