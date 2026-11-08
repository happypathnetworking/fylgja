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
- **`docker events`, the driver's account of a container started, dead or removed**
  ([D-058](decisions.md#d-058)). *(Docker 29.8.1, 2026-11-06)* Read by hand under `env -i`
  with `PATH` alone, as `cli.environment` gives a command on this host, with nothing else live
  running: `docker events --filter type=container --filter label=containerlab --filter
  event=start --filter event=die --filter event=destroy --format '{{json .}}'`, and beside it
  the same stream with no `label` or `event` filter, which showed every action.
  - It prints one JSON object a line as each event happens, and runs until killed: it was
    still running 4 s after the last command, and `SIGKILL` ended it (status 137). Each line
    was in the file it wrote within 1 s of its command; read a line at a time from a pipe, as
    `cli.follow` reads it, a `run`'s `start` and an `rm -f`'s `die` and `destroy` each arrived
    before the command had returned. An object holds `Type` (`container`), `Action`,
    `Actor.ID`, `Actor.Attributes`, `scope`, `time` and `timeNano`. `Actor.Attributes` holds
    the container's labels, `containerlab` (the lab's name) among them, beside `image` and
    `name`; a `die` adds `exitCode` and `execDuration`. The longest of the seven lines was 304
    characters.
  - For an alpine 3.24.2 container labelled `containerlab=evt-probe`: `docker run -d` printed
    `start`; `docker restart`, `die` then `start`; `docker stop`, `die`; `docker start`,
    `start`; `docker rm -f`, `die` then `destroy`. The filters dropped `create`, `kill` (twice
    in a restart and in a stop, the container's `sleep` ignoring SIGTERM until it was killed
    10 s later), `stop` and `restart`.
  - **A `docker exec` prints nothing through it**: its actions are `exec_create: true `,
    `exec_start: true ` and `exec_die`, which `event=die` does not match. A container without
    the label printed nothing for its `create`, `start`, `kill`, `die` and `destroy`.
  - **Its reader gone, it ends at its next line, of SIGPIPE.** Started in a session of its own,
    its stdout a pipe whose read end a separate reader process alone held, as a core holds it:
    with the reader killed by `SIGKILL` it ran on for 3 s with no event to print, and the next
    event, an `rm -f`, ended it 0.3 s later with status -13 and nothing on stderr. So a core
    killed with `SIGKILL`, which runs no cleanup, leaves its `docker events` running until the
    next event it prints (a labelled container's start, die or destroy).
  - Under a `DOCKER_HOST` naming a socket that is not there it printed nothing on stdout and
    exited 1 after 0.13 s. Its stderr was `failed to connect to the docker API at
    <DOCKER_HOST>; check if the path is correct and if the daemon is running: dial unix
    <path>: connect: no such file or directory`: it names `DOCKER_HOST`'s value, which can be
    an address of the site, so the driver logs neither a failure's stderr nor a line of the
    stream.
- **The daemon replays its last 256 events, and no older.** *(Docker 29.8.1, 2026-11-06)*
  `docker events --since <t> --until <t'>` replays what the daemon holds in memory. Right after
  an alpine container's `run`, the replay since a moment before it held its `create` and
  `start`, and through the driver's filters its `start`. After 90 `docker exec <container>
  true` (15.6 s; each adds `exec_create`, `exec_start` and `exec_die`), the replay since the
  same moment held 256 events, all `exec_*`, and through the driver's filters nothing; the
  replay since 0 held 256. So every `docker exec` the core runs (a probe host's readiness, a
  burst, a flow) adds three events to that buffer, and the driver asks for no replay after its
  stream ends: it names every lab on the host instead.
- **Every lab on the host** is listed by `docker ps -a --filter label=containerlab --format
  '{{.Label "containerlab"}}'`. *(Docker 29.8.1, 2026-11-06)* It prints one line per container
  that carries the label, the lab's name: a lab of two containers twice, a created and an
  exited container included, a container whose label is empty as an empty line, and nothing
  for a container without the label. With no such container it printed nothing and exited 0;
  under a `DOCKER_HOST` naming a socket that is not there it exited 1, with the stderr
  `docker events` gives.
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
  - **A failed deploy's output holds containerlab's log lines and the error alone.** *(0.81.0,
    Docker 29.8.1, 2026-11-05)* Read because `deploy.log` now persists in the twin's directory
    (D-056). Two one-lab deploys were run by hand with their output in a file, the core's
    environment inherited as `cli.run` leaves it: an image tag that does not exist
    (`ghcr.io/nokia/srlinux:0.0.0-does-not-exist`) failed at the pull in 1 s with 11 lines, the
    docker daemon's "failed to resolve reference … not found"; a link to `n1:e1-99` on SR Linux
    24.7.1 failed at post-deploy after 33 s with 20 lines, "invalid port 99, max is 58" in the
    error. Each output named the lab, the images, the nodes, the lab directory and the error,
    and nothing else: none of the five `FYLGJA_*` values in `local/.env` appeared in either
    (counted with `grep -cF`, each 0). The topology the driver renders carries no
    startup-config, environment or credential, so a deploy's output has nothing of the kind to
    echo; what reaches the nodes' credentials is the push and the gNMI reader, after the deploy.
    `destroy -t --cleanup` of each exited 0 and left the host clean.
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
  *Since 2026-11-06* the server handles SIGTERM itself, so in a container, as PID 1, it is not
  ignored (["The core's image"](#the-cores-image)): the handler uvicorn restores is `main`'s, which
  ends the run as Ctrl-C's, so SIGTERM's exit now passes the join as SIGINT's does, and holds no
  read there.
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

**fylgja-core, phase 6: the local driver's environment** *(0.81.0, Docker 29.8.1, 2026-11-05)*

Every command the local driver runs gets the variables of `cli.ALLOWED_ENV` that the server's
environment sets, and nothing else ([D-065](decisions.md#d-065)). The list was read with the
driver's live module (`core/tests/live/test_containerlab_driver_live.py`: admit, apply,
inspect, a repeat and a `--reconfigure` apply, destroy, the residue rule, two labs at once),
`local/.env` loaded and nothing else live running. A name set on the host stays when the module
fails without it, and goes when it passes without it.

- **The list is `DOCKER_HOST` and `PATH`.** On the host, `HOME` and `PATH` were set and
  `DOCKER_HOST` was not; `local/.env` sets six `FYLGJA_*` names and nothing else. Under the
  starting list, `DOCKER_HOST`, `HOME` and `PATH`, the module passed, 7 tests in 216.8 s.
- **`HOME` goes: the module passed without it**, 7 tests in 209.9 s. By hand under `env -i`
  with `PATH` alone, `docker ps`, `docker network ls`, `docker image inspect`, `containerlab
  version` and `containerlab inspect --all` exited as they did with `HOME`, with the same
  stderr. The host has no `~/.docker/config.json`, so no Docker context or registry login was
  there to miss; a host that has one adds `HOME` with its own reading.
- **`PATH` stays, on this reading and on the decision's word.** Without it the module failed, 5
  of its 7 tests in 4.4 s; the admit and a destroy that found nothing, which run `docker` alone,
  passed. `containerlab deploy -t …/topology.clab.yml` exited 1 in 0.2 s, the last line of its
  error `exec: "getent": executable file not found in $PATH.`, after `Failed to lookup
  containerlab admin group: error while looking up user groups using getent command
  clab_admins:`. Python found `containerlab` in `os.defpath` (`/bin:/usr/bin`); containerlab's
  own search found no `getent`, though it is in `/usr/bin` too. Run by hand under `env -i` with
  `HOME` alone, the deploy failed the same way and made nothing. D-065's first bullet holds
  `PATH` whatever a host shows: without it, Python finds a command in `os.defpath` alone, where
  this host's `containerlab` and `docker` happen to be.
- **`DOCKER_HOST` stays on the decision's word.** It is unset here, and a host on the default
  socket cannot show another's need.
- **A deploy's output names no value of the core's.** One deploy of `three-node` through the
  driver under the list, as the twin `env-read`, `local/.env` loaded, took 39.0 s and wrote a
  `deploy.log` of 32 lines ending in containerlab's table, with no `WARN` or `ERRO` line. None
  of the six `FYLGJA_*` values in `local/.env` appeared in it (counted with `grep -cF`, each
  0); the twin's name, counted the same way, was on 6 lines. Its destroy took 1.7 s.
- **The whole live tier under the list** passed, 90 tests in 2430.3 s (40.5 min): the 89 of
  phase 5's last run and the waiting `twin create` through a kill (`test_e2e.py`, 72.9 s). By
  module, each test's setup, call and teardown summed from a JUnit report: the driver's 7 in
  209.2 s, `changes` 15 in 276.5 s, the end-to-end 13 in 690.8 s, the steps 31 in 888.4 s, the
  push 9 in 93.1 s and verify 15 in 271.4 s. The containerlab that the `changes` and verify
  modules run by hand now gets the list's names too (with `CLAB_LABDIR_BASE` for the dry run),
  and ran so for the first time. The host was left clean: no `clab-*` container, no lab, no
  `containerlab` process.

**fylgja-core, phase 6: a node replaced behind the core's back** *(0.81.0, Docker 29.8.1,
2026-11-06)*

The live module `core/tests/live/test_restore_live.py` runs the loop in-process over the local
driver, its resync at 3600 s and its step wait at 20 s, and makes the twin `rst-live` from
`three-node` ([D-058](decisions.md#d-058), [D-067](decisions.md#d-067)). Once the twin is Ready,
`n3` is restarted by `docker restart`, `n1` is stopped from inside and started again by Docker's
own restart policy, and `n2` is removed by `docker rm -f`. The driver's follower is `cli.follow`
itself, wrapped to keep each line's time; a second `docker events`, without the driver's filters,
writes every action Docker raised for the lab; and the reconciler keeps each pass's start and end.
SR Linux 24.7.1, on a host with 25.7 GiB available. The module passed alone three times, 3 tests
in 238.6 s, 245.5 s and 243.9 s; each range below is over those runs. Times are from the act's
return, and for Docker's own restart from its `start`.

- **The driver's `docker events` ran once for the whole module and never ended**: the first run
  of `ContainerlabDriver.events` against Docker. The driver read each line within 0.01 s of the
  time Docker gives it. The create's deploy printed a `start` for each node, and those kicks,
  folded while the create held the twin, cost one pass after it that made no run and wrote
  nothing. The create took 60.1–67.7 s, the destroy at the end 1.43–1.57 s.
- **`docker restart`** returned in 0.80–0.83 s. Docker raised `kill` (−0.71 to −0.74 s), `stop`
  and `die` with `exitCode` 143 (−0.38 to −0.40 s), then `start` and `restart` (−0.01 s); the
  driver's filters passed the `die` and the `start`. **The pass the `die` caused took the
  restore** (in the two runs that kept the passes): it began when the line was read, and its
  `docker inspect` answered only once the container had started again, reading `n3` running at
  its new incarnation (the inspect bullet below). No pass saw `n3` not running, in any run: the
  loop logs the first sighting of an absent node, and none was logged. The restore run was made
  at +0.00–0.01 s, `n3`'s push transport answered at +30.1–30.6 s (`ready done`), its push was
  done at +33.0–33.9 s, and the run ended `ok` at +53.4–54.4 s, `Ready` True again. The
  `start`'s kick, which came while that pass held the twin, cost one pass after it, 0.16 s long,
  that did nothing.
- **`n3` lost its links across `docker restart`**, as a node does across `docker stop` then
  `docker start` (phase 5's verify block). After the restore its `/sys/class/net` listed
  `e1-1-0`, `e1-10-0`, `e1-11-0`, `e1-2-0` (taken to be SR Linux's subinterfaces of the pushed
  configuration, by their names; not read), `gway-2800`, `gway-2801`, `lo`, `mgmt0`, `mgmt0-0` and `monit_in`, and no
  `e1-1` or `e1-2`, the links' own ports. So the restore's wait expired at 20.5 s on verify
  `nonconforming`, each end of `n3`'s two links listing no neighbour (11 held, 4 failed, 3
  skipped), and the run ended `ok` with the warning `step.wait.expired`. Nothing is applied and a
  twin is not repaired (D-067): the twin is Ready, every node holding the bundle, its two links
  gone.
- **A node that Docker starts again by itself.** containerlab gives an SR Linux node the restart
  policy `no` and a `linux` node, a probe host, `always`: read by hand on a one-node alpine 3.24.2
  lab deployed under `env -i` with `PATH` alone, whose destroy left nothing. The module gave `n1`
  `always` (`docker update --restart always`, 0.11 s) and sent its init SIGTERM from inside
  (`docker exec --user 0 … sh -c 'kill -TERM 1'`, 0.14–0.16 s). Docker raised `exec_create`,
  `exec_start` and `exec_die` for the command, then `die` with `exitCode` 143 and, 0.37–0.39 s
  later, `start`; no `kill`, `stop` or `restart`. `RestartCount` went from 0 to 1. The pass the
  `die` caused took the restore here too (in the two runs that kept the passes), and no pass saw
  `n1` not running; the run was made 0.01–0.02 s after the `start`: `ready done` at
  +30.1–30.5 s, `push done` at +33.5–33.9 s, the run ended `ok` at +54.0–54.4 s, the wait
  expired. `n1` lost its links as well (9 held, 6 failed: `n1`'s two links, and `n3`'s, still
  gone).
- **`docker rm -f`** returned in 0.54–0.58 s. Docker raised `kill` (−0.45 to −0.48 s), `die` with
  `exitCode` 137 (−0.10 to −0.11 s) and `destroy` (−0.01 s). **The pass the `die` caused failed**,
  in every run: its `docker ps` listed `n2`, and its `docker inspect` of the three containers, run
  once `n2` was removed, exited 1, a transient failure logged at WARNING and backed off. The
  `destroy`'s kick, folded meanwhile, ran the next pass at once (+0.07–0.08 s, in the two runs
  that kept the passes): it found `n2` missing and began its boot window, SR Linux's 60 s
  (logged at +0.26–0.29 s). A pass every 5.2 s inside the window wrote nothing. The pass at
  +60.26–60.29 s wrote `Ready` False for `twin.node.missing` (its `since` +60.46–60.48 s) and
  logged a warning naming `n2`. No run was made, the lab held `n1` and `n3`, and no
  `containerlab` process ran.
  - *(0.81.0, Docker 29.8.1, 2026-11-06, with the driver's `inspect` taking its listing again
    once when its `docker inspect` fails)* The module's re-run: **no pass failed**. The `die`'s
    pass (−0.09 to +0.30 s) listed `n1`, `n3` and `n2`; its inspect of the three failed. It
    listed `n1` and `n3` again, inspected those, and found `n2` missing at +0.30 s, with no
    WARNING. The `destroy`'s kick, folded meanwhile, cost a pass (+0.30 to +0.50 s) that wrote
    nothing. `Ready` False came at +60.48 s, the record written once over the window (revision
    20 to 21). The module passed, 3 tests in 253.3 s. Its figures outside the ranges above: the
    create 68.5 s, `docker rm -f` 0.64 s, and for Docker's own restart `ready done` at +31.83 s,
    `push done` at +34.73 s and the run's end at +55.21 s.
- **`docker inspect` while a container starts again** (by hand: an alpine 3.24.2 container run
  with `--init`, inspected back to back, 23–28 inspects of 0.07–0.28 s each per act).
  - Asked after the `die` of a `docker restart`, it answered 0.28 s later, after the `start`,
    with the container running at its new `StartedAt`. Asked before the `die`, it answered at it,
    not running.
  - Under the restart policy `on-failure:3`, after `kill -TERM 1` from inside: asked before the
    `die`, it answered after it with `Running` true, the old `StartedAt` and `RestartCount` 1, the
    container restarting; asked in the 0.27 s between the `die` and the `start`, it answered after
    the `start`, running at the new `StartedAt`.
  - So a pass that a `die` causes, its inspect asked after the line, read a container Docker was
    starting again at its new incarnation, here and in each run of the module, and never one not
    running.
  - A `docker inspect` of several containers, one of them removed since they were listed, exits
    1 (the removal's first pass, above).
- **The whole live tier** then passed, 154 tests in 2804.7 s (46.7 min), the first run since the
  loop gained its settled pass and both drivers their `events`. By module, each test's setup,
  call and teardown summed from a JUnit report: the driver's 7 in 225.8 s, `changes` 15 in
  262.4 s, the end-to-end 13 in 729.3 s, the steps 31 in 913.4 s, the object store 61 in 59.1 s,
  the push 9 in 93.6 s, this module's 3 in 246.6 s and verify 15 in 273.4 s. This module's
  figures fell within the ranges above but for Docker's own restart: `push done` at +33.24 s and
  the run's end at +53.72 s.
  - Each end-to-end module's server was killed with SIGKILL 9 times, and each kill left the
    server's `docker events` running, as the reader-gone bullet above has it; the harness ended
    each, 18 in all, through a pidfd taken while the server was its parent. Each module's last
    stop left none.
  - Neither server's log showed its `docker events` ending, a restore or a node missing, across
    the creates, the steps and the kills.
  - The host was left clean: no `clab-*` container, network, host entry or ssh config, and no
    `docker events`, `containerlab` or `fylgja-core-server` process.

**fylgja-core, phase 6: a node replaced by `containerlab stop --node` and `start --node`, and one
stopped** *(0.81.0, Docker 29.8.1, SR Linux 24.7.1, 2026-11-07)*

The conformance module `core/tests/conformance/test_restore.py` runs on the local harness:
`fylgja-core-server` as a subprocess, its resync at 3600 s and its step wait at 90 s, and the
twin `cf-restore` from `three-node` ([D-067](decisions.md#d-067), [D-058](decisions.md#d-058)).
The harness replaces a node with `containerlab stop --node`, then `start --node`, on the twin's
topology, returning once Docker's `StartedAt` of the node has moved; it stops one with the `stop`
alone. No client writes meanwhile. The module ran alone twice, with `test_zz_end.py`: 6 tests in
243.6 s and 239.8 s. Nothing else of the phase ran on the development host, and no cluster
command was run from it. Each range below is over the two runs. Times are from the harness's
return, or from the `stop`'s return for the stopped node, and the passes are read from the
core's log.

- **A replacement is one restore, taken at the `start`.** `stop --node` returned in 0.71–0.76 s
  and `start --node` in 0.62–0.69 s, so the whole replacement took 1.66–1.76 s.
  - The pass the `stop` caused saw the node not running and began its boot window, SR Linux's
    60 s.
  - The pass the `start` caused came 0.54–0.59 s later. It found the node at another
    incarnation and took the restore, and the record named the run with Ready False for
    `twin.restoring`.
  - No pass reported `twin.node.missing`. The run was made 0.05–0.07 s before the harness
    returned, since the harness reads `StartedAt` after the `start` has returned.
- **`n2` configured, from `three-node`.**
  - `ready done` came at +30.4–30.5 s from the run's start, and `n2` was pushed at
    +33.5–33.6 s.
  - Verify held at the wait's first try (0.46–0.47 s). The run ended `ok`, Ready True, at
    +33.97–34.00 s from the harness's return.
  - Nothing else was readied, pushed or moved, and verify then held 15.
- **`n2` unmanaged, from `three-node-unmanaged`.**
  - `ready done` came at +30.6–31.1 s, and its push was `skipped`.
  - Verify held after 16.7 s and 5.9 s of the wait. The run ended `ok`, Ready True, at
    +47.27 s and +37.03 s.
  - Verify then held 15, with 3 skipped.
  - Why the wait took seconds with no push, where it held at its first try after one, was not
    read.
- **A node stopped and started by containerlab holds the kind's baseline, not its push.**
  - Before the replacement, `n2`'s `ethernet-1/1` in the running datastore held the description
    the create from `three-node` had pushed, `to n1 ethernet-1/1`, with `admin-state` `enable`
    and subinterface 0. The step to `three-node-unmanaged` had pushed nothing.
  - After it, with no push since, the port held `admin-state` `enable` alone, with no
    description and no subinterface.
  - The marker was absent in both runs. So `stop --node` then `start --node` keeps the node's
    links (phase 5's verify block, above; here verify held `n2`'s neighbours with no push) and
    loses its push.
- **A node stopped and left so.** `stop --node n3` returned in 0.66–0.76 s.
  - The pass it caused saw `n3` not running, not missing, and began its window. A pass about
    every 5.1 s inside the window wrote nothing.
  - The pass 60.2 s after that first sighting wrote Ready False for `twin.node.missing`, its
    `since` +60.4 s from the `stop`'s return, and logged a WARNING naming `n3`.
  - No run was made, the generation stayed, and the harness read `n3` at no new incarnation.
  - `twin verify` exited 1 in 14.4 s, `failed`, with 8 held and 10 skipped; its one error was
    `verify.node.unread` on `n3`.
  - The destroy took 1.6–1.7 s and left nothing.

**fylgja-core, phase 6: the conformance suite on the local driver** *(0.81.0, Docker 29.8.1, SR
Linux 24.7.1, cEOS 4.32.0.2F, 2026-11-07)*

The conformance suite, `core/tests/conformance/`, on the local harness: `fylgja-core-server` as a
subprocess over a store in a temporary directory, its resync at 3600 s and its step wait at 90 s,
driven through API 1 and the thin CLI and killed with SIGKILL. The tree read was the branch's head
at the runs, 8a0c8f4: its `core/src` that of `c6be28a`, unchanged on the branch and the commit the
cluster's image was built at, and the suite as the branch holds it. Each run was timed by `time`
and judged by its exit status, `local/.env` loaded, with the cluster quiet: the deployed core held
no twin, and nothing else ran there. The driver's capabilities read `isolation` `names` and
`reapply` False. Each figure below fell outside a range of phase 4's or phase 5's blocks above, or
of the block just above, given beside it, over the suite's two runs, or has no earlier range and
says so; every other reading fell inside.

- **`make conformance DRIVER=containerlab`: 48 passed, 1 skipped in 1870.46 s** (31:12 by `time`,
  17:29 to 18:00Z), exit 0: 12 tests of `test_lifecycle.py`, 20 of `test_steps.py`, 10 of
  `test_step_kills.py`, 4 of `test_restore.py` and 2 of `test_zz_end.py`. `test_isolation.py`'s
  one scenario skipped: `the driver keeps twins apart by names, not by the network`.
- **`make live`, whole: 158 passed, 1 skipped in 3049.30 s** (50:51 by `time`, 18:00 to 18:51Z),
  exit 0: the driver's own modules under `core/tests/live/`, 110 tests (`test_object_store_live.py`
  61, `test_changes_live.py` and `test_verify_live.py` 15 each, `test_push.py` 9,
  `test_containerlab_driver_live.py` 7, `test_restore_live.py` 3), then the suite again, as above.
- **Each session's end**: the runtime held nothing and no record named a twin; the core logged 2032
  and 2035 lines, each one JSON, holding no token or password; it started 19 times a session, in
  0.88 to 1.67 s (0.71–1.48 s), and served again 1.09 to 1.97 s after each kill; the harness ended
  the 18 `docker events` processes the kills left, and the last stop left none. The host was left
  clean after each run: no container, network, host entry or ssh config of a lab, and no
  `containerlab`, `fylgja-core-server` or `docker events` process.
- **The lifecycle** (phase 4's block):
  - the create from `three-node` took 69.3 and 67.4 s end to end (57.8–67.1 s), its apply 45.46
    and 44.56 s (36.1–43.3 s) and its readiness 13.61 s once (12.3–13.3 s); `cf-step`'s took 65.1
    and 65.3 s (60.2–64.0 s, phase 5's);
  - killed 10 s into the apply: Ready 71.7 and 76.9 s after the create's `--no-wait` returned
    (72.2–78.9 s after the create); the deploy running at the kill ran on 61.6 and 66.6 s after it,
    which no earlier block read; the resume deployed nothing, as phase 4's did;
  - a waiting `twin create`, the core killed 10.6 and 10.7 s after it was asked, which no earlier
    local block read: the command ended 65.2 and 63.8 s after the kill, exit 0.
- **The steps** (phase 5's steps block):
  - the link removed and added back, the port disabled and enabled, and the configuration dropped:
    1.82 to 2.06 s end to end (1.8–2.0 s), the applies 0.96 to 1.16 s (0.94–1.14 s);
  - the configuration given back: 5.07 and 5.40 s, `n2`'s push 3.26 and 3.52 s (4.8–5.0 s;
    3.0–3.2 s); the node removed: 2.44 s once (2.2–2.4 s);
  - the node added: 34.2 and 36.3 s end to end (33.1–34.6 s), the apply 24.60 and 24.66 s (up to
    24.42 s), `n3`'s push 3.55 and 3.37 s (2.8–3.43 s);
  - the probe added: the apply 2.68 s once (2.40–2.59 s), the wait held after 12.23 and 12.02 s
    (12.06–13.6 s);
  - the step to the bundle it runs: 0.26 and 0.28 s (0.20–0.23 s);
  - the probe moved: 15.99 and 16.05 s, the apply 3.14 and 3.20 s, the wait held after 12.25 and
    12.24 s (15.9 s; 3.01–3.16 s; 12.04–12.20 s);
  - the kind change: the apply 53.92 and 54.48 s (52.3–53.3 s), `n3` readied in 10.22 and 10.26 s
    (12.1–14.2 s), its push 2.71 s once (3.1–4.0 s);
  - the cEOS port with `--allow-restart`: the apply 60.74 and 60.46 s (58.2–60.0 s), the two nodes
    readied in 6.22 s once (7.0–10.6 s), pushed in 7.20 s once (5.3–6.2 s);
  - the cancel: the run ended 0.52 s once after it was asked (0.40–0.51 s).
- **The step's kills** (phase 5's table and its D-056 run):
  - after `admitted` and `planned`: `stepped` 38.5 and 42.0 s, and 41.3 and 40.2 s, after the kill
    (40.7–44.5 s and 41.8–44.5 s in the table; 39.7 and 40.2 s with the deploy's output in a
    file), `n3` started 0.5 to 0.6 s after it, as in the D-056 run, and the deploy running at the
    kill running on 39.4 to 42.9 s after it by the suite's audit (22.8 and 23.4 s in the D-056
    run);
  - after `pushed` and `verified`: `stepped` 2.0 s, and 1.4 and 1.7 s, after (1.6–1.7 and 1.1–1.3
    s);
  - killed 10.0 s into the deploy: `stepped` 30.0 and 29.2 s after the kill (30.3 s), `n3` keeping
    the start it had 9.5 s before it, but the deploy running at the kill ran on 30.9 and 30.2 s
    after it, where the D-056 run read 14.0 s. Why the stray deploys ran on longer by the suite's
    audit than in that run was not read.
- **A node replaced or stopped** (the block just above): `stop --node` then `start --node` took
  1.69 to 1.81 s (1.66–1.76 s), the restore run made 0.01 to 0.04 s before the harness returned
  (0.05–0.07 s); the configured `n2` was Ready again at +33.67 and +34.30 s (+33.97–34.00 s); the
  unmanaged `n2` at +30.52 s, the wait holding at its first try, and +47.38 s, the wait holding
  after 16.93 s (+37.03–47.27 s); a `stop --node` alone took 0.65 s once (0.66–0.76 s). The marker
  read absent in both runs.

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

- **The cluster stands as recorded, with nothing left on it.** *(2026-11-05)* Read before
  phase 6, through its kubeconfig and one node's shell:
  - three nodes `Ready` as `control-plane,etcd` on k3s v1.37.1+k3s1 and containerd
    2.3.4-k3s1, up 2 days 5 h, each with 8 CPU and 23.5 GiB allocatable and no disk pressure;
  - clabernetes 0.10.1 deployed by its chart in the namespace `c9s`, its manager 3 of 3 and
    its planner pool 4 of 4; MetalLB's controller at v0.16.0, with one pool and one L2
    advertisement;
  - no `Topology`, `Link` or `Node` object (`c9s.run/v1alpha1`), one `Config`, no namespace
    beyond the system's, `c9s` and `metallb-system`, and no LoadBalancer Service;
  - use by `kubectl top`: 145–231m CPU and 0.98–1.66 GiB a node;
  - both images cached on every node: SR Linux by digest from ghcr, cEOS 4.32.0.2F from the
    private registry, which answers 401 without credentials on its TLS port;
  - on the node read, k3s's config holds the two relaxed etcd timings and
    `registries.yaml` the registry's `ca_file`.

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
- **A LoadBalancer's address with no ready pod behind it drops what is sent to it.** *(MetalLB
  0.16.0, 2026-11-07)* Read from the development host, on the cluster's layer 2, at the core's
  Service (`externalTrafficPolicy: Cluster`, port 443), the core scaled to no replica for 151 s,
  one TCP connect at a time:
  - for 0.7 s, while the pod terminated and the address was still announced, each connect was
    refused in 1–2 ms;
  - then one hung 14.3 s, and each of the 43 after it failed `No route to host` in 3.05–3.11 s,
    nothing answering with a refusal. A failure in about 3 s is the kernel's sign of an ARP
    resolution that failed, so MetalLB likely announces no address without a ready endpoint; that
    is inferred, its speaker's log and the host's neighbour table not read;
  - scaled back to one replica, the address answered 7.7 s after the scale.

  The core's client watching a twin across the same absence: its stream ended at the server's
  graceful stop, its first reconnect was refused at once, **its second open waited out its whole
  30 s connect timeout**, and each of thirteen after it failed `No route to host` in about 3.06 s;
  it gave up 185.4 s after the stream ended. A client off this link meets what its router does,
  and a router that drops leaves each open its whole connect timeout. So each reconnect is given
  5 s to connect (`core/src/fylgja_core/client.py`).
- **k3s's network policy controller accepts ICMP echo into every pod**, whatever the policy
  (its `KUBE-NWPLCY-COMMON` chain). It refuses other traffic with REJECT, which a client sees
  as connection refused. A pod started a few seconds before is not yet in the controller's
  sets. Test isolation over TCP, from a pod that has run for 15 s. Over TCP, a twin's pod
  could not reach another twin's node on 22 or 57400, and a pod of the same twin
  could. *(2026-11-02)*
- **A pod in another namespace is refused by a twin's policy on every path, and one
  `namespaceSelector` admits it.** *(2026-11-05)* Read on a two-node SR Linux twin under the
  policy above, each Service at `Local`, from a pod 25 s old in a second namespace, on the
  host of one node and not of the other:
  - gNMI and SSH were refused at each node's pod address, its Service's cluster address and
    its LoadBalancer address, while the development host reached both ports at both
    LoadBalancer addresses;
  - with a `namespaceSelector` on `kubernetes.io/metadata.name` naming that namespace added
    to the policy, every path to both nodes answered within 1 s, the LoadBalancer address of
    the node on the other host included;
  - a pod in a third namespace, 25 s old, stayed refused on every path.
- **A node's pod** has one container, named `node-<uuid>-primary-<hash>`, running the
  node's image by digest, and two init containers of the clabernetes manager image:
  `planner`, and `clabwire` with `restartPolicy: Always`, so the pod reads `2/2`. It carries
  `c9s.run/topologyNode` (the node) and `c9s.run/topologyOwner` (the Topology) beside the
  topology's default labels. Its Services are `<node>` (the LoadBalancer) and `<node>-wire`
  (headless, UDP 14790). An exec that names no container runs in the node's: `sr_cli`
  answered, and an argument vector's exit status came back as the exec's. *(2026-11-05)*
- **A probe host runs as locally.** *(2026-11-05)* On a twin of one SR Linux node, one cEOS
  node and one `linux` node on `alpine:3.24.2` carrying two `exec` lines (an address and a
  route on `eth1`), auto-expose off and each device's ports declared:
  - the host's pod came up with the address and the route set, runs as root, and `ping` and
    `ip` work in it by exec;
  - a node that declares no port gets no LoadBalancer Service, only its `-wire` one; each
    device's Service listed its declared ports alone;
  - **a change to the host's `exec` lines alone replaced the host's pod**, with the new
    address set, and kept the others;
  - a deleted host pod's replacement came up with its address and route set.
- **A cEOS port added after boot arrives with a new pod.** *(2026-11-05)* On that twin, both
  devices under `live`, a second link to the cEOS node replaced no pod, and 30 s after the
  Topology settled the node had no `eth2` in Linux and listed `Et1` alone. With its pod then
  deleted, the replacement was `Ready` in 63 s, at the same LoadBalancer address, and listed
  `Et1` and `Et2`, both connected.
- **With the images cached**, that twin's Topology read `topologyReady` 55 s after its
  apply, the development host idle; its namespace and the two beside it were gone 12 s after
  their delete. *(2026-11-05)*
- **The Topology's requests are by node name.** *(2026-11-05)* Read from the
  `topologies.c9s.run` CRD's one version, `v1alpha1`, making no object:
  - `spec.deployment.resources` is an object keyed by node name, each value a container's
    resource requirements (`requests`, `limits`, `claims`), and `requests` and `limits` map
    a resource to a quantity such as `500m` or `1536Mi`. A node's entry overrides the
    `Config`'s requests; a key `default` stands for every node the map does not name, and
    the `Config`'s are then never read for that topology;
  - `spec.expose.disableAutoExpose` is a boolean, `false` by default, beside `exposeType`
    (`LoadBalancer` by default);
  - `spec.imagePull.pullSecrets` is a set of names of Docker-config Secrets in the
    Topology's namespace, put on each device pod's `imagePullSecrets` and never mounted in
    its container;
  - `spec.definition.containerlab`, a string holding the containerlab topology, is the
    spec's one required member.
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

**fylgja-core, phase 6: the Topology's status, and the pods replaced, read by hand**
*(clabernetes 0.10.1, k3s v1.37.1+k3s1, 2026-11-05)*

Read on SR Linux twins, the Topology's status and the twin's pods sampled every 0.25 to 0.4 s.
The pure tier's fake of the cluster, `core/tests/fake_kube.py`, is written from them.

- **A pass that observes a new generation says the Topology is not ready** *(2026-11-05:
  superseded the same day, at this bullet's end: its first write can keep the readiness of
  the generation before)*. At the first read after an apply that moved the generation, 0.4 to
  0.5 s after it, `status.observedGeneration` already equalled the generation and
  `status.topologyReady` read false, in three steps:
  - the first apply;
  - a link added under `live`, which replaced no pod; ready again 3.6 s after the apply;
  - one node's link mode changed, which replaced that node's pod; ready again 54.8 s after.

  The generation observed and the Topology still ready from before was never read.
  Superseded by a closer reading the same day: sampled every 0.1 s, the first write of a new
  generation kept the readiness of the one before for about 0.14 s, in four steps of six, a
  window these reads 0.25–0.4 s apart missed ("the clabernetes driver's calls", below).
  *(2026-11-05)*
- **A pod deleted with no change of spec**, on a settled twin of two nodes. 0.5 s after the
  delete, `topologyReady` read false and `readyNodeCount` 1; the old pod read deleting and
  still `Ready`, beside its replacement, `Pending`. The old pod read `Failed` 1.7 s after the
  delete and was gone at 2.2 s. The replacement was `Running` at 40.7 s and `Ready` at 42.3 s,
  when `topologyReady` read true again. What the status reads in the first half second after
  a delete was not sampled.
- **A link-mode change replaces the pods of the nodes whose mode changed, and no other.** On
  three nodes, all `live`, cabled n1–n2 and n2–n3:
  - n1 to `restart` replaced n1's pod alone;
  - n1 back to `live`, n1's alone;
  - n1 and n2 to `recreate`, those two, and n3's was kept.

  The reading above that switching to `live` replaced every pod ("Steps across hosts") had
  changed every node's mode at once. The kind reading that changing any node's mode replaces
  every pod (clabernetes 0.10.1, "Steps", 2026-10-30) was not read again.

**fylgja-core, phase 6: the clabernetes driver's calls** *(clabernetes 0.10.1, lightkube
1.0.1, k3s v1.37.1+k3s1, 2026-11-05)*

Read from the development host through the driver as the server makes it (`drivers.make`),
with the cEOS pull credential set and every image cached on every node.
`core/tests/cluster/test_clabernetes_driver_cluster.py` runs the twin `drv-k8s` (`three-node`);
`core/tests/cluster/test_clabernetes_changes_cluster.py` steps the twin `chg-k8s` from
`three-node` through the step fixtures and back, then steps `hot-k8s` from `mixed` to
`mixed-e2-port`. The modules passed alone, 7 tests in 4.1 min and 14 in 9.7 min, and again in
`make cluster`, 27 tests with `test_kube_cluster.py`'s in 14.8 min; a range below is the two
runs'. Two throwaway scripts read beside them: a container ended in its pod, and the
Topology's whole status every 0.1 s across six steps. A node's uid below is its pod's.

- **Timings.**
  - A create: `three-node` 56.2–66.6 s from the apply to its return (five), `mixed`
    74.8–76.0 s.
  - A repeat, and a step that renders the same Topology (`three-node-n1-disabled` and back):
    0.20–0.21 s, the generation unmoved.
  - `reconfigure`: 62.8–64.0 s, the three addresses kept.
  - Steps: a link removed or added, or a node removed, 4.2–4.3 s; a node added 65.4–65.5 s;
    a probe added 24.1–24.8 s, moved 53.9–55.5 s, removed 32.9–33.0 s (its hosts' pods took
    31 s to go); a kind change 63.9–75.7 s (four), and back 85.8 s; the hot-add recreate
    resumed, 71.7–72.4 s.
  - A destroy: `three-node` 14.1 s, the same with a cEOS node 46.3–48.3 s, `mixed`
    46.3–46.4 s, a namespace holding no pod 6.1 s; a second destroy 0.02 s.
  - With `apply`'s settled wait at two reads in a row (below), the next `make cluster` took
    15.9 min, each apply about one poll longer: a repeat 2.2–2.3 s, a re-cable or a node
    removed 6.3 s, `three-node` created in 57.7–67.5 s, `mixed` in 80.6 s, a kind change
    77.5 s, the hot-add resumed 75.3 s.
  - With a pod's deletion at the second of two reads that find the generation observed, and
    a LoadBalancer required for each node that declares ports, the next `make cluster` took
    15.7 min, 27 tests passing *(2026-11-05)*:
    - the killed apply stopped 4.3 s in, a poll later than before; the resumed one read the
      generation observed at 0.04 s, deleted `e1`'s and `e2`'s pods at 2.27 s, returned at
      77.9 s, and both nodes listed `Et10` 0.4–1.0 s after its return;
    - `reconfigure` 56.8 s; `three-node` created in 58.5 s and 67.5 s (the second at DEBUG),
      `mixed` 76.6 s, a re-cable or a node removed 6.3 s, a node added 57.3 s, a probe added
      25.7 s, moved 55.6 s, removed 35.0 s, a kind change 78.0 s, a repeat 2.3 s;
    - every apply returned 0.5–3.7 s after its Topology last turned ready in the 0.25 s
      samples, two reads or fewer, but the probe's removal, which the wait held until its
      hosts' pods were gone (31.9 s) and which returned 3.1 s after: no wait was read held by
      a node that declares ports and had no LoadBalancer. The Services themselves were not
      sampled;
    - the DEBUG create's 6,166 records (`httpcore2.http11` 5,590, `httpx2` 559,
      `httpcore2.connection` 6, `fylgja.clabernetes` 8, `fylgja.credentials` 3) carried no
      value of the credential.
- **A node's Service is the LoadBalancer of its name** in the twin's namespace, as lightkube
  read. After each apply every one read `Local`; one patched to `Cluster` read `Local` after
  one `inspect`. Port 22 at each node's address opened from the development host within
  0.01 s.
- **The pull secret.** Its `auths` holds one key, the registry's host and port: the
  allocation's prefix up to its first `/`. The Secret is `kubernetes.io/dockerconfigjson`,
  and every pod of a twin admitted with the credential names it in `imagePullSecrets`, an SR
  Linux or `alpine` pod's too. With it, each clabernetes `Node` of `hot-k8s` read
  `PlanApplied` `True`, where a missing Secret reads `False` (lightkube 1.0.1, below), and
  both cEOS pods read the image by digest, where the Topology names it by tag. *(2026-11-05:
  that the controller resolved the cEOS manifest through the registry with the Secret is
  inferred, not read. Which field carried the digest was not recorded, and every image was
  cached on every node: a container status's `imageID` would carry one with no request to
  the registry.)*
- **No log record carries the credential at DEBUG.** `drv-k8s`'s create, the root logger at
  DEBUG and the credential set, emitted 6,122 and 6,188 records: `httpcore2.http11`
  5,550–5,610, `httpx2` 555–561, `httpcore2.connection` 6, `fylgja.clabernetes` 8,
  `fylgja.credentials` 3 (variable names) and lightkube none. No record's message,
  arguments or exception held the password, the base64 of `username:password`, or the
  Secret's `.dockerconfigjson`; in these runs httpcore2 wrote a request as
  `<Request [b'PATCH']>`, never its body.
- **`changes` held to the uids**, read before each apply and after its return. Every answer
  held:
  - `three-node` to `three-node-unlinked`, and back: `n1` kept, `n2` and `n3` recabled; no
    uid moved.
  - To `two-node`: `n3` removed, its pod gone; `n1` and `n2` recabled, their uids kept. Back:
    `n3` added, a new pod.
  - To `three-node-n1-disabled`, and back: every node kept.
  - To `three-node-probed`: both hosts added; `n1` recabled; `n2`, `n3` kept. Each host's
    readiness command showed its address at the first try.
  - To `three-node-probed-moved`: both hosts recreated (`exec`, `links`), new uids, `n1-loop-a`
    showing `10.2.10.2/24` and not its old address; `n1`, `n2` recabled; `n3` kept. Back to
    `three-node`: the hosts removed, `n2` recabled, `n1` and `n3` kept.
  - **To `three-node-n3-eos`: `n3`, its kind and image changed, recreated, a new uid; `n1`
    and `n2` recabled, their uids kept.** A kind or image change replaces that node's pod
    alone.
  - `mixed` to `mixed-e2-port`: `e1` and `e2` recreated (`hot_add`, `links`), new uids; `s1`
    kept.
- **The hot-add recreate, killed and resumed.** An apply over a `Kube` that raised at the
  first pod deletion stopped 2.2 s in. The Topology then carried `fylgja.recreate` naming
  `e1` and `e2` at their uids, and both pods stood at them. The session's driver applied the
  same deployment: it read the annotation, deleted both pods 0.1 s into its apply, applied the
  Topology as rendered at once, and returned 71.7–72.4 s in. `e1`'s replacement was `Ready`
  at 61.6–61.7 s and `e2`'s at 71.4–71.6 s, the three addresses kept. Each listed `Et10`,
  `connected`, at the first `show interfaces status` after the return, 0.5–1.3 s after it.
  The controller's script, deleting a pod 0.3 s after its generation was observed, settled
  64 s later. The driver now deletes a pod it replaces, or every pod under `reconfigure`,
  only at the second of two reads `POLL_S` apart that find the generation observed, a poll
  after the first: the controller's first write of a generation can keep the readiness of the
  one before for about 0.14 s ("A new generation can be observed", below). When the
  controller writes what a replaced node's pod is made from was not read, and neither was a
  pod deleted inside that window; the script's deletion, 0.3 s after the observation, came
  back with the port. *(2026-11-05)*
- **`exec`**, beside the local driver's ("A probe host" and "Docker 29.8.1" under
  containerlab):
  - `sh -c "echo out; echo err >&2; exit 7"` answered `Exec(7, "out\n", "err\n")` in 0.14 s;
  - a binary the node lacks is the API's `500 InternalError`, a `KubeFailed`, in 0.14 s,
    where `docker exec` answers 127, which the local driver raises as `DriverFailed`;
  - a node the twin lacks is `DriverFailed` with nothing run, in 0.04 s (locally 0.07 s);
  - `sleep 30` within 3 s raised `ReadTimeout` at 3.07 s, a `KubeFailed`, the command left
    running.
- **An SR Linux node's container ended in its pod is restarted there: the pod's uid stays,
  its restart count grows by one, the node boots again and its push is lost.** Read on an SR
  Linux node alone. On a settled `three-node`, `n1`'s configuration was pushed over JSON-RPC
  at its address (2.8 s), and its `ethernet-1/1` description read back by `sr_cli`. Its
  container's first process is `/tini -- fixuid -q /entrypoint.sh sudo -E bash -c touch
  /.dockerenv && /opt/srlinux/bin/sr_linux`, running as root; `exec` of `sh -c "kill 1"` ends
  it (SIGTERM, which `tini` passes to its child). Read through the driver's `Kube`, from the
  kill:
  - 0.9 s: the pod not `Ready`, its phase `Running`; the container `terminated`, reason
    `Error`, exit code 143 (the script, through lightkube's model);
  - 23.7–26.7 s: restart count 1, the container running, the pod still not `Ready`;
  - 29.3–31.0 s: the pod `Ready` at the same uid, restart count 1;
  - the phase read `Running` throughout, so `inspect` answered `n1` running while its pod was
    not `Ready`, and its incarnation moved from `<uid>/0` to `<uid>/1`, the other two nodes'
    not;
  - the first process had run 29–30 s, against 62 s before; `sr_cli` answered 1.5–1.7 s
    after `Ready`, and the description was gone.

  The Topology read `topologyReady` false and `readyNodeCount` 2 of 3 from 0.9–1.2 s until the
  pod was `Ready`. `inspect` reads the container's state for `running` since: in the next run
  it answered `n1` not running at each read while the container was down and the count
  unmoved, and running from the count's move, the node booting and its pod not yet `Ready`;
  the pod was `Ready` 36.7 s after the kill.
- **A pod deleted through the API.** 0.06 s after the delete `inspect` answered `n1` at
  another uid, not running, its address kept; the new pod was `Running` at 47.8–51.1 s.
  `topologyReady` read false at 0.32 s, the old pod deleting and still `Ready` beside its
  replacement, `Pending`; the old pod read not `Ready` at 1.46 s and was gone at 1.75 s.
  Under `reconfigure` all three old pods read deleting within 0.45 s and were gone at 2.8 s;
  the new ones were `Ready` 51.6–62.5 s after the apply.
- **A new generation can be observed before the readiness of it is written.** Sampled every
  0.1 s across six steps (a kind change each way, twice, and a link removed and added): the
  generation moved 0.20–0.21 s after the apply began, and `observedGeneration` followed at
  0.33–0.37 s. In four of the six, that first write kept the status of the generation before
  for about 0.14 s: `topologyReady` true, `topologyState` `running`, `readyNodeCount` the old
  count, and the `TopologyReady` condition `True` at its old transition time (a condition
  carries no `observedGeneration`). At 0.47 s `topologyReady` read false and `topologyState`
  `degraded`. Sampled every 0.25 s in the step module, 5 of its 18 steps over the two runs
  read the same at their first read (0.34–0.39 s), false at the next (0.63–0.67 s); one read
  `readyNodeCount` 4 of a `nodeCount` already 3. Through that window every pod is its old
  one, `Ready`: a replaced node's old pod began deleting 1.0–2.8 s after its generation read
  observed. So `observedGeneration` equal to the generation does not say the readiness read
  beside it is that generation's. `apply`, which then believed one read, returned on no old
  pod in these runs: the generation was observed 0.12 s or more after it moved, and the wait
  read at once after the Topology's apply and next 2 s later. **`apply`'s settled wait rests
  on the window's width**: it believes the twin ready only when two reads in a row, `POLL_S`
  (2 s) apart, fourteen times the window, each find the generation observed, `topologyReady`
  true and every node's current pod `Ready`, so no two of its reads fall in one window, while
  the window stays narrower than `POLL_S`: it was read only on a lightly loaded cluster. In the
  next `make cluster`, 3 of its 9 steps read the window at their first read, and no apply
  returned on an old pod.
- **A kept pod's readiness can blink after a step.** Three times a node whose pod the step
  kept read not `Ready` for 1–2 s, 1.8–21 s after the Topology first read ready again, its
  uid and restart count unchanged, the Topology not ready meanwhile: twice after the apply had
  returned.
- **`admit`, `inspect` and `destroy` leave a namespace that is not the twin's.** A namespace
  of the twin's name made with no label refused the twin, `admission.namespace.taken`;
  `inspect` answered `absent`; `destroy` left it, logging a warning. The namespace alone,
  applied from `namespace.yaml`, inspected as `residue`, and `destroy` removed it.

**fylgja-core, phase 6: a container restarted in its pod** *(clabernetes 0.10.1, SR Linux 24.7.1,
lightkube 1.0.1, k3s v1.37.1+k3s1, 2026-11-06)*

Read from the development host on four throwaway twins of `steps/two-node`, each made through the
driver as the server makes it (`drivers.make`) and destroyed after, and once through the loop
(the restore module, `core/tests/cluster/test_restore_cluster.py`). Each time `n1`'s container was
ended in its pod by `exec` of `sh -c "kill 1"`, as in the block above; the kubelet restarted it at
the same uid, restart count 1, the pod `Ready` 34.3 s, 34.4 s, 27.5 s and 25.4 s after the kill in
the four throwaway readings, and 27.6 s through the loop.

- **The node's address answers nothing again.** From the development host, JSON-RPC at the
  node's LoadBalancer address answered `ConnectTimeout` or `ConnectError` at every try for 420 s
  after the kill in one reading and 240 s in another, and in two more until the pod was deleted,
  48.9 s and 58.7 s after it. TCP to SSH (22) and gNMI (57400) timed out; to JSON-RPC (443) it
  failed at once. Before each kill all three answered, JSON-RPC within 3.0–3.9 s. The Service's
  EndpointSlice still listed the pod, `ready` and `serving`, not `terminating`, throughout. Through
  the loop, the restore taken 34.6 s inside `n1`'s boot window waited the package's 60 s for
  readiness and ended `failed` for `readiness.timeout`, `Ready` False, not repeated.
- **Inside the node all of it runs.** After the restart, by `exec`: the JSON-RPC server's
  configuration (enabled on the `mgmt` network instance, HTTPS on `clab-profile`) and its state,
  `oper-state up`; `mgmt0` `oper-state up`; JSON-RPC answering on 443 inside the node's
  `srbase-mgmt` namespace (HTTP 405 to a `GET` of `/jsonrpc` with no login), with gNMI on 57400
  beside it; `/etc/opt/srlinux/config.json` on an `ext4` mount, its size and time unchanged, and
  `clab-profile`'s certificate and key. The data link stayed up: `ethernet-1/1` `oper-state up`
  on both nodes and each the other's LLDP neighbour, at 60 s after `Ready` and at 240 s after the
  kill. The pod's interfaces kept their names and MACs (`c9s0`, the pair `c9sr0`/`mgmt0`, `c9sm0`,
  the pair `c9ss…`/`e1-1`, `gway-…`), and `c9s0`, the pod's own, its address.
- **What changed is the management subinterface's address.** `mgmt0.0`, in `srbase-mgmt`, is a
  DHCP client in the node's running configuration (`ipv4 { admin-state enable dhcp-client { } }`),
  and before the kill held one IPv4 address, `/24`, `origin dhcp`, which is not the pod's address.
  After the restart it held none, only a link-local IPv6 address, and its state listed no IPv4
  address. Nothing in the pod's network namespace or in `srbase-mgmt` listened on UDP, before the
  kill or after it. Of the pod's init containers, `planner` had run once and ended and `clabwire`
  (restart policy `Always`) ran, its restart count 0, before and after.
  - **Not read:** which process served the first lease (that `planner`, which runs once a pod,
    did is inferred from the above, not read); how traffic to the pod's address reaches
    `mgmt0.0`'s (the image holds no `iptables-save` or `nft`); and whether the lease returns past
    420 s.
- **A pod deleted then is a node reachable again.** `n1`'s pod deleted through `kube` after the
  restart: the replacement, another uid, restart count 0, answered JSON-RPC at the same
  LoadBalancer address 56.1 s and 68.6 s after the delete, with SSH, gNMI and JSON-RPC all open
  and the EndpointSlice listing it. Its `mgmt0.0` held its IPv4 address again, `origin dhcp`, the
  same address as before the kill.
- **What the watch delivers of the container's end, and of a pod starting** *(2026-11-06)*. Read
  on a fifth throwaway twin, its pods watched through lightkube from before its apply, each change
  with its one container's `state` (which of `running`, `terminated` and `waiting` is set, with the
  reason) and its `lastState`:
  - **A pod starting** (the apply's two, and a deleted pod's replacement): `ADDED` `Pending` with no
    container status, then the container `waiting`, reason `PodInitializing`, with no last state,
    through the init containers' run (`planner` `running`, then `terminated`, `Completed`;
    `clabwire` `running`), then `running` with no last state 46.98–50.31 s in, `started` after,
    and `Ready`. Restart count 0 throughout; never `terminated`, and never a last state.
  - **A container ended in its pod** (`kill 1`): one `MODIFIED` 0.54 s after the kill, the
    container `terminated` (reason `Error`, exit code 143), restart count 0, no last state, the
    pod `Running`, not `Ready`, not deleting. Nothing more until 25.14 s, when it read `running`
    at restart count 1, its last state `terminated` (`Error`, 143), then `started` and `Ready`.
  - **A pod deleted**: deleting first, its container still `running` (0.02 s), then not `Ready`,
    then phase `Failed`, its container `terminated`, its last state `terminated` and `clabwire`
    `terminated` (`Error`, 2), all while deleting, then `DELETED` at 1.13 s.

  So a container that has ended in its pod is delivered, for about 25 s before it runs again, in
  a state a starting pod never shows (`terminated` at the count it had), on a pod not being
  deleted; a pod deleted shows it only once it is deleting. Not read: a container that fails
  before it ever runs, a cEOS node's or a probe host's container ended in its pod, and the
  `waiting` (`CrashLoopBackOff`) state, which a container that ends again within the kubelet's
  backoff would show with its last state `terminated`.

**fylgja-core, phase 6: a node's pod deleted behind the core** *(clabernetes 0.10.1, SR Linux
24.7.1, cEOS 4.32.0.2F, alpine 3.24.2, lightkube 1.0.1, k3s v1.37.1+k3s1, 2026-11-06)*

`core/tests/cluster/test_restore_cluster.py` runs the loop in-process over a store of its own,
on the cluster tier's event loop, its resync at 3600 s and its step wait 180 s, over a
clabernetes driver made as the server's is, on the twin `rst-cluster`: `steps/two-node`, then
stepped through the loop to `three-node-probed` and to `steps/three-node-n3-eos`. Every image
was cached on every node, and each test's act was the only change on the cluster. The module
passed alone, 8 tests in 827.0 s (13.8 min), and in `make cluster`, 35 tests in 1719.3 s
(28.7 min). A range below is those two runs', and for the first test also the earlier run that
read the restore of a container restarted in its pod fail (the block above). Once the driver
renewed a pod at its container's end, the module passed alone again, three times, 8 tests in
783.2 s, 804.9 s and 792.4 s; the in-place path's range is those runs', and the rest, which that
change does not touch, stands as read before. Times are from the act's return.

- **The create through the loop** ended `ok` in 71.4–80.4 s. Its pods' changes named the twin 6
  times while the create held it, and the passes they caused after it wrote nothing and made no
  run.
- **A pod deleted (`n2`, SR Linux).** The pod watch delivered 19 changes:
  - the old pod deleting and still `Ready` at +0.02–0.03 s, its replacement `ADDED`, `Pending`,
    at +0.06–0.07 s;
  - the old pod `Failed` at +0.84–0.89 s and `DELETED` at +1.43–1.81 s, carrying `fylgja.twin`;
  - eleven `MODIFIED` of the replacement while `Pending`, each changing nothing the driver keeps;
  - the replacement running at +43.33–47.47 s, two more unchanged, then `Ready` at
    +51.00–51.20 s.

  The driver's `events` named the twin 6 times, where the pure tier's fake gives 4: it marks
  the old pod `Failed` before it goes, and the replacement runs before it is `Ready`. The first
  pass found `n2` not running at +0.12–0.14 s; the passes every 5.05 s inside SR Linux's 60 s
  window wrote nothing. The pass at the replacement's running took the restore at
  +43.37–47.52 s, 12.6–16.7 s inside the window, so `twin.node.missing` never showed. `ready
  done` came at +55.1–57.2 s, `push done` at +58.1–60.3 s, and verify held at its first try
  (0.3 s; 6 held, 2 skipped). The run ended `ok` at +58.4–60.6 s, `Ready` True at
  +59.4–61.4 s. One pass after it, the replacement's `Ready` folded, wrote nothing. The record
  held `n2` at the new pod's uid, `/0`, at the address it had, and `n1` as it was; both Services
  read `Local` after an `inspect`. **The link came back**: `ethernet-1/1` up on both nodes, each
  the other's LLDP neighbour.
- **A container ended in its pod (`n1`), its pod replaced by the driver at its restart count's
  move** *(2026-11-06: the driver as first built; superseded the same day, the bullet after this
  one)* (the block above). The container read down at +0.61–1.35 s, and running again at restart
  count 1 at
  +25.85–26.81 s. The driver deleted the pod 0.02–0.03 s later, with one INFO line naming the
  twin, the node, the pod, its uid and its count. The old pod was `DELETED` 1.6–1.9 s after; its
  replacement was `ADDED` at once, running 38.5–39.9 s after the deletion and `Ready` 2.1–3.4 s
  after that. The watch delivered 21 changes, and `events` named the twin 8 times.
  - The first pass found `n1` not running at +0.70–1.36 s, and so did the pass the count's name
    caused, after the deletion.
  - **The window passed** at +60.74–61.48 s: a WARNING named `n1`, and `Ready` read False for
    `twin.node.missing` for 4.0–5.0 s. The node's 60 s ran from its container's end, across the
    restart in place and the replacement's boot: the replacement ran 64.4–64.6 s after that
    first pass.
  - The replacement's running took the restore at +65.39–65.76 s (`Ready` False for
    `twin.restoring`). `ready done` came 6.5–9.5 s later and `push done` 2.2–3.0 s after that;
    verify held at its first try. The run ended `ok` at +74.69–78.14 s, `Ready` True at
    +75.63–78.68 s.
  - One restore in all, none `failed`. `ethernet-1/1` was up on both nodes, each the other's
    LLDP neighbour.
- **A container ended in its pod (`n1`), its pod replaced by the driver at the container's
  end.** The watch delivered the container `terminated` at +0.71–1.32 s, and the driver deleted
  the pod 0.04–0.06 s later, with one INFO line; the replacement was `ADDED` at once, ran
  41.1–47.3 s after the deletion and was `Ready` 3.8–10.4 s after that. The old pod, already
  deleting, was restarted by the kubelet at +24.8–26.7 s (restart count 1, running), then read
  `Failed` and was `DELETED` at +25.8–28.0 s; being deleting, it was passed over. The first pass
  found `n1` not running at +0.88–1.46 s, and the replacement's running took the restore at
  +42.5–48.1 s, 12.7–18.9 s inside the 60 s window: **`twin.node.missing` never showed**. `ready
  done` came at +57.65–57.75 s and `push done` at +60.3–60.8 s, verify held at its first try, and
  the run ended `ok` at +60.5–61.1 s, `Ready` True with its end. One restore in all. The watch
  delivered 20–21 changes, and `events` named the twin 8 times. `ethernet-1/1` was up on both
  nodes, each the other's LLDP neighbour.
- **Left alone for 180 s**, the settled twin's pods changed not once, in either run: no change
  delivered, no name, no pass.
- **Steps through the loop.**
  - To `three-node-probed` (`n3` and two hosts added, `n1` and `n2` re-cabled): `ok` in
    67.6–67.7 s, verify held after 2.2 s. Its pods' 43 changes named the twin 11 times while the
    step held it; at most one pass ran after its end, and it wrote nothing.
  - To `steps/three-node-n3-eos` under `allow_restart` (`n3` recreated as a cEOS node, the hosts
    removed): `ok` in 81.9–83.9 s, 34–35 changes and 16 names; no pass ran after it.
  - Neither was followed by a restore, and in the 30 s after either no kept pod's `Ready`
    blinked: the blink of the block above was not seen.
- **A probe host's pod deleted (`n1-loop-a`, ping).** Its replacement ran at +8.38–8.84 s, and
  the restore was taken at +8.43–8.91 s, 21.3–21.7 s inside the ping package's 30 s window. It
  readied both hosts and pushed nothing. Verify held after 31.6–32.6 s (19 held, 5 skipped), and
  the run ended `ok` at +40.9–41.2 s. The old pod stayed deleting and running until it read
  `Failed` at +30.4–30.5 s, and was `DELETED` at +31.2–31.4 s. The watch delivered 19–20 changes,
  and `events` named the twin 6 times.
- **A cEOS pod deleted (`n3`).** Its replacement ran at +56.95–62.06 s, and the restore was
  taken at +57.01–62.11 s, 28.0–33.2 s inside cEOS's 90 s window. `ready done` (eAPI) came at
  +69.3–78.3 s and `push done` at +72.3–80.8 s; verify held at its first try (0.2–0.3 s; 15 held,
  3 skipped). The run ended `ok` at +72.6–81.1 s. The old pod read `Failed` at +30.6 s and was
  `DELETED` at +31.1–31.2 s; 21 changes, 6 names. `n3` listed `Et1` and `Et2` connected and `n2`
  its LLDP neighbour on `Et1`.
- **The teardown's destroy** took 40.4–46.4 s with the cEOS node.
- **Not read:**
  - a twin whose every pod went while the watch was down: the loop's start names every twin, so
    on the cluster only a gap in a running watch shows it, and none could be made without
    deleting a twin's Deployments;
  - how often a long quiet watch's own reconnect lands on a compacted version: the server's
    watch timeout was not waited out (what such a version is answered with is in the lightkube
    section, below);
  - what a closed or cancelled watch does on the API server's side.

**fylgja-core, phase 6: the core as a pod** *(k3s v1.37.1+k3s1, MetalLB 0.16.0, lightkube 1.0.1,
Versity S3 Gateway v1.10.0, Python 3.14.9 in the image and 3.14.4 on the workstation, 2026-11-07)*

The core deployed from the base under `deploy/` and a site's overlay under `local/deploy/`, by
`kubectl apply -k local/deploy`, its image pushed to `<registry>` by CONTRIBUTING.md's recipe;
three-node SR Linux twins created through it from the development host, the workstation, at
`https://<the Service's address>`. Two faults the readings showed were fixed and the image rebuilt
and rolled each time (`0be0fdbacebd`, then `7b807d9d7621`, then `b9721894e252`); a reading made
before a fix is marked so. **The core stays deployed, with no twin, for the conformance suite: the
image `fylgja-core:b9721894e252`**, one replica. The tree after that commit changes `core/src` only
by narrowing the server's catch of a refused raise to `PermissionError` and by a refactor of the
client's page read, neither rolled.

- **The Service's address** is asked of MetalLB by the annotation `metallb.io/loadBalancerIPs`.
  Read on two scratch Services, each asking for a free address of the pool that the allocator would
  not have given first: each got the address asked for, in 0.2 and 0.4 s; the older
  `metallb.universe.tf/loadBalancerIPs` was honoured too, with a second event, `Warning
  deprecatedAnnotation`. No MetalLB CRD names either key.
- **The CA, as Python's client verifies it.** `ssl.create_default_context(cafile=…)` (Python
  3.14.4, OpenSSL 3.5.5) sets `verify_flags` 557088: `VERIFY_X509_STRICT`,
  `VERIFY_X509_PARTIAL_CHAIN` and `VERIFY_X509_TRUSTED_FIRST`. The site's CA certificate, made by
  `openssl req -x509` with the default configuration (`basicConstraints` critical `CA:TRUE`, SKI
  and AKI, no key usage), was refused: verify code 92, `CA cert does not include key usage
  extension`, by Python's context in a loopback handshake and by `openssl verify -x509_strict`. The
  same CA's certificate issued again over its own key and subject with
  `keyUsage=critical,keyCertSign,cRLSign` was accepted by both, and so was every certificate the
  CA had signed: the core's (an EC P-256 key; `CA:FALSE`, `digitalSignature`, `serverAuth`, the
  address as an IP SAN, SKI and AKI) and the registry's. The client was given that certificate as
  `FYLGJA_API_CA`; the site's own CA file was left as it was, so a strict client given it is still
  refused.
- **Applied.** From the apply to the first `serving API 1 on 0.0.0.0:7650 over the store
  s3://fylgja, driver clabernetes, 4 workers`: **23.7 s**. The core's pod started before its store:
  its first two runs took the Lease (created, holder the pod's name, transitions 0, then taken again
  at once under the same name, `acquireTime` rewritten) and exited 1 at the proof's first put,
  `cannot start: the object store cannot be opened: … the endpoint could not be reached
  (ConnectError)`, the gateway's pod still binding its claim; after the kubelet's backoff of 10 s the
  third served, 0.16 s after it held the Lease, Ready 3.4 s later. The gateway's log holds the
  proof: `PUT` 200, 412, 200, 412, `DELETE` 412, 204 on one key. Every line of the core's log was
  one JSON object, no off-loopback warning among them. A rollout to a new image (`Recreate`) took
  16.7 and 17.4 s from the apply to `successfully rolled out`, the old pod gone before the new was
  made. `kubectl apply -k` printed `configured` for the StatefulSet and three Secrets whose content
  had not changed (the StatefulSet's generation stayed 1) and deletes nothing it does not apply: the
  pull secret `fylgja-registry` made by hand for Task 7's reading was not deleted by it, and stayed,
  unused, beside the overlay's `fylgja-registry-<hash>` until the maintainer deleted it on
  2026-11-07.
- **From the workstation, over TLS** (`core/.venv/bin/fylgja-core`, the address, the CA issued
  again and a token of the overlay's token file in the shell's environment): without
  `FYLGJA_API_CA`, exit 2 in 0.74 s, `… failed: the server's certificate is not trusted: unable to
  get local issuer certificate` and `FYLGJA_API_CA names the CA file an https:// address is
  verified against`. With it, `twin create pod-e2e --blueprint testdata/blueprint/three-node.json`
  exit 0 in 83.3 s; `twin show pod-e2e --json` exit 0 in 0.86 s, Ready True, three nodes each at a
  pool address, its node's LoadBalancer Service's; `twin destroy pod-e2e` exit 0 in 15.4 s, the
  namespace already gone (the destroy run ends with it). Every secret value the core was given,
  one a line, matched none of the pod's log lines (`grep -c -F -f`: 0).
- **A second pod does not reconcile.** Scaled to two replicas, the second was Running and never
  Ready (its readiness probe `connect: connection refused`, 25 times in two minutes: nothing
  bound), its log one line, `waiting for the Lease fylgja-core, held by <the first>`; the Lease's
  holder did not change; a `twin create` meanwhile reached Ready in 91.7 s, each of its run's
  log lines the first pod's.
- **The holder deleted** (`kubectl delete pod`): its Lease released 0.43 s after the delete,
  `stopped by SIGTERM` its last line, exit 143. The waiting pod took the Lease 1.50 s after the
  release (its next read) and was Ready 3.9 s after the delete, the twin read through the same
  address. *Before the fix* (`0be0fdbacebd`), the same delete released the Lease and then exited 1
  with a traceback: a process in the pod may not signal itself ("The core's image", below).
- **A forced delete is no kill.** `kubectl delete pod --grace-period=0 --force` removed the pod
  object at once, and the kubelet still sent SIGTERM: the holder stopped as above, its Lease
  released 0.44 s after the delete, and the waiting pod held it 3.5 s after the delete.
- **The Lease's 15 s, read by cutting the holder off from the API**: the holder labelled and a
  NetworkPolicy selecting that label alone with `policyTypes: [Egress]` and no rule. Its renewals
  failed (`ConnectError`), the log counting down (`it is lost in 10.0s`, `… in 5.0s`), and **15.00 s
  after its last renewal was sent it stopped at once** (`the server stops at once: no renewal
  succeeded within 15 s`, rule `lease.lost`), nothing released, exit 1: both times by the holder's
  own clock, its last `renewTime` and its log line. **The waiting pod held the Lease 15.46 s after
  that renewal**: its `acquireTime`, by its own clock, against the holder's `renewTime`, two pods'
  clocks; by the development host's clock alone, its watch received the last renewal and the
  takeover 15.45 s apart. The cut pod, restarted in place, logged `cannot be read or
  written (ConnectError)` until the policy went, then `the Lease fylgja-core answers again` and
  waited. Scaled back to one replica, the Deployment kept the holder and removed the waiting pod
  (exit 143, `stopped by SIGTERM while waiting for the Lease fylgja-core`). Each renewal there was
  refused at once, as the countdown's whole seconds show. A renewal left unanswered to its 5 s
  bound was not read on the cluster: that the next is then sent at the cut, so that one such
  renewal costs nothing, is read on the fake clock alone (`core/tests/test_lease.py`).
- **A pod deleted mid-create**, when the run's last event was `apply started` (0.13 and 0.25 s
  after it, two runs): the deletion landed in the apply, after its four objects were applied,
  while it waited for the Topology; the pod released the Lease and exited 143. The Deployment's
  next pod held the Lease 4.5 and 4.6 s after the release, logged `create run <id> resumed after
  planned`, wrote a second `apply started` and applied the four objects again (the driver declares
  `reapply`, D-068): no reconfigure. The twin was Ready 91.9 and 92.1 s after the delete, under the
  same run, its 21 events numbered 1 to 21 without a gap. A waiting `twin create` said once on
  stderr `GET https://<the Service's address>/v1/twins/<name> ended before its end;
  reconnecting`, printed each later phase once and exited 0. A `run watch` begun as the server
  went met the refusal at its version read, made once before any stream, and exited 2 at once.
- **The LoadBalancer's address while no pod is ready** drops what is sent to it (the bullet above
  on MetalLB's address). The core's client watching a twin across the core scaled to no replica
  gave up 185.4 s after its stream ended, one reconnect's open waiting out its whole 30 s connect
  timeout; with each reconnect given 5 s to connect, the same open timed out at 5.01 s and the
  watch gave up 160.3 s after its stream ended. Across a 5 s absence the watch reconnected and went
  on.
- **The gateway stopped** (`kubectl scale statefulset/versity --replicas=0` 10 s into a create's
  apply, back to one 63 s later; Ready 2.9 s after that, its claim kept). The core's first store
  call hung its whole 10 s connect timeout (`ConnectTimeout`), and that call held the event loop:
  **one renewal gap of 10.11 s**, the Lease kept. Each call after was refused at once, the pass
  backing off 1 to 32 s, one WARNING each; a read route answered `500 server.error` (`twin list`
  exit 2). The waiting `twin create`'s twin watch reads nothing from the store while idle: it
  printed nothing, ended nothing, and exited 0 once the create had finished. The pass resumed on its
  backoff's schedule, 8.9 s after the gateway was Ready; the twin Ready 42.7 s after the scale back,
  its events without a gap. The core never restarted.
- **The gateway made slow.** `kubectl exec versity-0 -- kill -STOP 1` answered `can't kill pid 1:
  Permission denied`, the process still running. Stopped from its node's shell (`sudo kill -STOP`
  of the PID `k3s crictl inspect` reports for its container) for 22.3 and 22.6 s:
  - under a destroy, after its namespace was gone: **one store call hung 11.3 s**, to its 10 s
    `ReadTimeout`, the renewal gap 13.48 s, the Lease kept;
  - under a create's apply, where the loop reads its run every 0.5 s for a cancel while the call on
    the runtime runs: **two reads in a row held the event loop, and 21.08 s after its last renewal
    was sent the core stopped at once** (its `renewTime` and its log line, its own clock),
    `lease.lost`, exit 1; restarted in place, it took the Lease again at once under its own name,
    the gateway continued by then, served, and resumed the create, Ready 80.9 s after the gateway
    continued. The waiting `twin create` said once `… failed: peer closed connection without
    sending complete message body (incomplete chunked read); reconnecting` and exited 0.
  - **So the holder outlived its deadline**: it stopped 6.08 s past the 15 s D-071 item 3 promises,
    while a waiting core takes the Lease from about 15.5 s (the cut from the API, above). No core
    waited here; had one, two would have been up together for about 5.6 s. This holder was blocked
    in a read throughout and wrote nothing late, but nothing checks the deadline before a write:
    once a blocked call returns, the loop may write before the cut, the store's compare-and-set
    limiting what such a write can overwrite (D-071's status note).
- **A pass on a twin of twenty runs.** A step to a twin's own bundle with the same spec makes no
  run (the route answers the spec unchanged), so the steps alternated `--allow-restart`; each ended
  `unchanged … at compiled`. The store keeps a destroyed twin's runs, so a name used again counts
  them. From 4 runs to 20, the step's spec write to its first event went from 0.146 to 0.389 s, to
  its run's end from 0.235 to 0.484 s; the API's `GET /v1/runs?twin=` (the store's
  `list_runs(twin)`) from 45 to 154 ms (21 runs): **about 7 ms a run, and about 15 ms a run a
  step's pass**, which lists the twin's runs twice. A settled pass lists none and logs no line: not
  timed.
- **The gateway shut to twins.** Under its NetworkPolicy the gateway stayed Ready, the kubelet's
  probe answering (one failure, as it restarted); the core's proof passed at each start and its
  9395 requests were answered 200, 204, 404 or 412; from a pod 37 s old in a namespace with no
  label, `versity.fylgja:7070` answered `Connection refused` at once, three times, while the same pod
  resolved its name and reached `kubernetes.default:443` and `kube-dns.kube-system:53`.

**fylgja-core, phase 6: the conformance suite's cluster harness** *(k3s v1.37.1+k3s1, clabernetes
0.10.1, lightkube 1.0.1, the core's image `fylgja-core:c6be28acb35b`, 2026-11-07)*

The core deployed as the block above leaves it, rolled once by the site's overlay with
`FYLGJA_RESYNC_S` 3600 and a token for the principal `conformance`: 11.9 s from the apply to
`successfully rolled out`, the new pod `holding the Lease` at its first line, the old one having
released it. Read from the development host, with `kubectl` and with
`core/tests/conformance/harness.py`'s `ClusterHarness`, the cluster holding no twin but where one is
named; nothing else ran on the cluster or the host.

- **An egress-deny NetworkPolicy on k3s v1.37.1 leaves an established connection alone, so the cut
  did not cut the Lease of an idle core.** The holder labelled and the NetworkPolicy of the block
  above applied (`policyTypes: [Egress]`, no rule): a new connection was refused within 4 s (the
  store's read behind `twin list` answered `500 server.error`, the core logging `GET /v1/twins
  failed`), and the holder's renewals, over the connection its Lease's client already held, did not
  fail once in 153 s under the cut, the Lease's `renewTime` moving every 5 s. Which rule passes the
  open connection was not read: its effect alone.
  - **Why the reading above held, and this one does not.** lightkube 1.0.1 gives its httpx client no
    limits, so the client keeps an idle connection for httpx's default `keepalive_expiry` of 5.0 s
    (read in the library's source). At `b9721894e252` each renewal was sent 5 s after the one before
    was answered: the renewals were 5.02 s apart (plan 6's reading, the Lease watched), so the
    connection had been idle past its 5 s and closed before each, and each renewal opened a new one,
    which the cut refused (not re-read on that image: an explanation from that spacing, plan 6's
    `ConnectError` and the library's default, an idle of about 5.00 s against an expiry of 5.0 s).
    Since `b39be82`, in the merged tree (`c6be28acb35b`), each is sent 5 s after the one before was
    sent: read now at 5.000 to 5.001 s apart, the connection is reused before it expires, and the
    cut does not reach it while it is. Each reading holds where it was made: on an idle core, as
    here, the renewals rode one connection through 153 s of the cut; under a twin's create they did
    not always, the holder's renewals stopping under the cut in two kills of one run and four of
    nine of another (the conformance suite's block below, its last bullet).
  - **A release that meets a Conflict gives up.** `Lease.release` writes the Lease held by no one as
    a replace at the version it holds; a 409 is `Conflict`, which `release`, catching any failure,
    logs as one WARNING (`the Lease <name> was not released (Conflict): it is taken 15s after its
    last renewal`) and answers False. It reads nothing back and tries nothing again; the server then
    stops as it would have, `stopped by SIGTERM`, and the Lease stays held under the name of the pod
    that went until a waiter has seen it unchanged for its duration.
- **Nor does the cut keep the release from the API.** The holder cut and deleted with no grace
  (`kubectl delete pod --grace-period=0 --force`), 0.24 s after the cut and again 21.3 s after it:
  each time its log ended `Shutting down`, then `released the Lease fylgja-core` 0.12 s after that
  line, and `stopped by SIGTERM`; the next pod held the Lease at its first read, 3.2 to 3.3 s after
  the deletion, and was Ready 6.4 to 6.5 s after it. A `kubectl logs -f` begun before a deletion
  with no grace delivered the pod's lines to its container's end. A twin watch held open to the core
  across the deletion changed nothing: the core logged `Waiting for connections to close`, closed it
  0.87 s after the deletion, and released the Lease 0.32 s after `Shutting down`.
- **What leaves the Lease unreleased: a write of the Lease between two renewals.** An annotation
  written on the Lease 0.38 s after a renewal was seen, then the holder deleted with no grace: its
  release was refused, `the Lease fylgja-core was not released (Conflict): it is taken 15s after its
  last renewal`, then `stopped by SIGTERM`. The Deployment's next pod logged `waiting for the Lease
  fylgja-core, held by <the pod that went>` 3.4 s after the deletion, held it 15.03 s after that,
  18.8 s after the last renewal (two pods' clocks), and was Ready 21.1 s after the deletion. Read
  again through the harness's `kill` (the cut 1.17 s after a renewal, then the write and the
  deletion): the next pod waited from +3.23 s, held the Lease at +18.25 s, 19.66 s after the last
  renewal, was Ready at 21.23 s and answered over the LoadBalancer at 22.30 s. The development
  host's clock and the holder's agree: four renewals were seen 9 to 52 ms after their `renewTime`, a
  read's round trip 8 to 9 ms.
- **A node's Deployment scaled to no replica is scaled back at once.** In a twin from `three-node`
  (`rd-scale`, created through the core in 92.0 s), each node's Deployment is owned, as its
  controller, by clabernetes' `Node` of the node's name. `n3`'s, scaled to 0 (its generation 2),
  read one replica again 1.3 s later (generation 3), its pod deleted and another `Pending`; that pod
  ran at +46.2 s, the core made a restore run (`core`) at +45.9 s, Ready False for `twin.restoring`,
  and Ready True at +59.7 s. So a node stopped behind the core is not expressible on the cluster:
  the harness's `stop_node` raises, and the scenario of a stopped node skips there with that reason.
  The destroy took 15.4 s.

**fylgja-core, phase 6: the conformance suite's reach** *(k3s v1.37.1+k3s1, clabernetes 0.10.1,
BusyBox 1.37.0 in `alpine:3.24.2`, lightkube 1.0.1, the core's image `fylgja-core:c6be28acb35b`,
2026-11-07)*

Read from the development host on a twin from `three-node-probed` (`rd-iso`, created through the
deployed core in 99.7 s), with `LightKube.exec` as the driver's `exec` calls it, naming no
container, and from a pod made in a third namespace; nothing else ran on the cluster or the host.

- **The probe host's exec runs in the host's own container.** `n1-loop-a`'s pod has one container,
  `node-<uuid>-primary-<hash>`, running `alpine` by digest, beside the init containers `planner` and
  `clabwire` (`restartPolicy: Always`) of the clabernetes manager's image; no launcher stands
  between. An exec naming no container answered `/etc/alpine-release` `3.24.2`, `BusyBox v1.37.0`,
  uid 0 and a first process `/bin/sh`, each in 0.08 to 0.12 s.
- **BusyBox's `nc -z -w 3 <address> <port>`, by exec, answers by its status alone**, printing
  nothing on either stream (its help lists `-z` "Zero-I/O mode" and `-w SEC` "Timeout for connects
  and final net reads"):
  - **0 where the connection is accepted**, in 0.10 to 0.12 s with the exec's round trip: from
    `n1-loop-a`, 91 s old, to its own twin's `n1` on 57400 at its pod's address, its Service's cluster
    address and its LoadBalancer address, and on 22 at its pod's address;
  - **1 where it is refused**, in 0.10 to 0.15 s: from `n1-loop-a` to `n1`'s pod address on port 1,
    which nothing serves, and from a pod of a third namespace to `n1` on 22 and 57400 at each of its
    three addresses, under the twin's NetworkPolicy;
  - **1 where nothing answers**, in 3.12 s: to an address of TEST-NET-1 that nothing routes, from
    either pod.
- **A pod of a third namespace is refused as soon as it runs.** That pod (`alpine:3.24.2` running
  `sleep 3600`, image cached) ran 2.6 s after it was made; at 0.8 s old and again at 15.0 s old its
  six probes answered 1 in 0.10 to 0.15 s. A probe still waits until its source has run 15 s: a pod
  a few seconds old is not yet in the controller's sets (above, "accepts ICMP echo"), which would
  refuse a source the policy admits; that was not read here. Its namespace was gone 11.8 s after its
  delete.

**fylgja-core, phase 6: the conformance suite on the cluster** *(k3s v1.37.1+k3s1, clabernetes
0.10.1, SR Linux 24.7.1, lightkube 1.0.1, the core's image `fylgja-core:c6be28acb35b`, 2026-11-07)*

Each module of `core/tests/conformance/` ran alone with `test_zz_end.py` (`cd core &&
FYLGJA_CONFORMANCE_DRIVER=clabernetes .venv/bin/pytest -q -rA -m cluster tests/conformance/<module>
tests/conformance/test_zz_end.py`), from the development host against the deployed core of the block
above, over TLS, as the principal `conformance`; then the whole suite ran, `make conformance
DRIVER=clabernetes`, and `test_restore.py` twice more (the block's last bullets). Each start printed
the image's tag `c6be28acb35b`.
The development host booted nothing, and nothing else ran on the cluster. The default driver's
capabilities read `nodes` `provisions`, `relink` True, `forwarding` `software`, `access` `direct`,
`isolation` `network` and `reapply` True. Every kill is the harness's (the block above), its seconds
from the deletion to the next pod's first answer over the LoadBalancer.

**Across the 35 kills** (31 read whole; a kill made beside a waiting CLI printed into that CLI's
captured output until the harness kept its readings for the session's end):
- the next pod first read the Lease 3.1 to 8.1 s after the deletion;
- it held the Lease 15.02 to 15.04 s after that read, 18.1 to 23.1 s after the deletion and 18.7 to
  24.1 s after the last renewal;
- it was Ready at 21.0 to 26.3 s, and the kill answered at 21.2 to 26.5 s;
- every next pod waited for the Lease the pod that went held.

- **`test_lifecycle.py`: 14 passed in 1127.42 s, and 14 passed in 1163.60 s** (13:26 to 13:45Z,
  14:43 to 15:02Z).
  - **The create** took 79.2 and 89.6 s end to end. Its apply took 58.9 to 67.6 s, its ready 11.1 to
    12.1 s and its push 7.8 to 8.8 s. Each node answered its own host name through its push
    transport at its LoadBalancer Service's address, and verify held 15 and skipped 3. The audit
    read three LoadBalancer Services at `Local`, no `fylgja.recreate` and one pod a node, at its
    first read. The destroy took 14.5 s.
  - **A kill at each phase boundary of a create** answered in 21.5 to 22.8 s, and each resume was
    the same run.
    - At `compiled`, `admitted` and `planned` (0.9 to 3.3 s into the create), the record read
      `planned` after the kill, the core logged `create run … resumed after planned`, and the resume
      applied again (2 applies started). Ready came 79.2 to 91.5 s after the create.
    - At `applied` (61.5 to 68.9 s in) and `ready` (81.7 to 84.1 s in), it resumed after the phase
      killed at. One apply started, each node kept the incarnation it had at the kill, and Ready
      came 101.7 to 112.6 s after the create.
    - At `pushed` (81.5 to 91.5 s in), the run had ended before the cut, and nothing resumed.
  - **Killed 10 s into a create's apply**, the core answered in 21.3 and 22.2 s and resumed after
    `planned` with 2 applies (`reapply`, D-068). Ready came 87.4 and 89.5 s after the create's
    `--no-wait` returned.
  - **A waiting `twin create`, killed in its apply.** The core served again 33.4 and 32.9 s after
    the create was asked, and the command ended 47.1 and 54.6 s after that, exit 0. **The CLI's
    watch outlasted the pod's replacement.**
  - **A waiting `twin destroy`, killed once the destroy had started.** The core served again 23.4
    and 22.6 s after the destroy was asked, and the command ended 0.6 and 2.5 s after that, exit 0.
  - **A deletion 2.4 to 2.6 s into a create's apply**, its first nodes made, left the twin gone 61.1
    and 15.3 s after it was asked. The create ended `failed` with `run.cancelled` alone, and the
    destroy `ok`. Why the first took 61 s was not read.
  - **The sessions' logs** were 549 and 559 lines, each one JSON, holding no token or password. The
    harness kept 510 and 520 of them from the nine pods each session's kills deleted.
- **`test_steps.py`: 18 passed, 4 failed in 635.30 s** (13:46 to 13:57Z).
  - `cf-step` was created in 88.2 s, and every step through `three-node-probed-moved` and back
    passed:
    - the link and port steps took 3.8 to 7.9 s;
    - `two-node` took 12.0 s;
    - `three-node`, `n3` added, took 76.2 s, its verify settling after 10.8 s;
    - `three-node-probed` took 50.5 s, its verify settling after 22.5 s;
    - the own bundle took 0.58 s, `unchanged` at `compiled`;
    - `three-node-probed-moved`, its hosts recreated under `--allow-restart`, took 59.8 s;
    - back to `three-node` took 36.8 s.
  - The step wait's budget read 180 s, the core's default.
  - **The four cEOS scenarios failed on the site, not the code.** The deployed core holds no EOS
    login: its overlay's credentials gave it the SR Linux login and the cEOS pull credential alone.
    - The step to `three-node-n3-eos` ended `diverged` at `applied`, after a 77.8 s apply, with
      `credential.missing: the environment variable FYLGJA_CREDENTIAL_EOS_USERNAME is not set`.
    - The create from `mixed` ended `failed` on the same rule for `e1`, so its two steps' dry runs
      answered no changes.
    - Each twin was destroyed `ok`.
    - The dry run of a create from `mixed` answered `ok`: the image could be had.
    - The cEOS scenarios were not read on the cluster.
- **`test_step_kills.py`: 12 passed in 1010.76 s** (14:17 to 14:34Z), at its second run.
  - **The first run** (13:58 to 14:15Z) passed 11 and failed in `kill_base`'s step back to
    `two-node`. That step ended `ok`, its own wait settled, and a `twin verify` asked 1.2 s later
    read `verify.node.unread` on `n2`: `ConnectionRefusedError` on its gNMI port at its LoadBalancer
    address. `n2` was the node the step kept, and its Service was without an endpoint for a moment,
    as the driver's block above reads a kept pod not Ready for 1 to 2 s after a step.
    `reads.verified` now asks again every 2 s, within 30 s, while its only errors are nodes unread.
    The second run did not meet it.
  - **A kill at each phase boundary of a step** answered in 21.2 to 26.5 s.
    - At `compiled`, `admitted` and `planned` (0.5 to 1.0 s into the step), the record read the step
      `running` at `planned`. It resumed after `planned` with 2 applies and was stepped 64.3 to 85.2
      s after the kill.
    - At `applied` and `ready`, it resumed after that phase with 1 apply, stepped 23.4 to 28.4 s
      after the kill.
    - At `pushed`, it resumed after `pushed` or `verified`, stepped 22.2 to 23.0 s after.
    - At `verified`, the run had ended and nothing resumed.
  - **Killed 10.1 s into a step's apply**, the core answered in 21.8 and 22.3 s, resumed with 2
    applies (`reapply`), and stepped 55.6 and 66.1 s after the kill.
  - **A deletion asked once the core answered again** (23.2 s after a kill 5 s into a step's apply)
    left the twin gone 33.2 s later. The step ended `diverged` and the destroy `ok`, and nothing was
    left, the node the apply had added (`n3`) among it.
  - **A step cancelled 5 s into its apply** ended 0.56 and 0.59 s after the cancel. It left the twin
    `diverged` at `planned`, refusing a new spec `409 twin.diverged`, with verify holding 6 and
    skipping 2. The destroy took 44.9 and 50.7 s.
- **`test_restore.py`: 5 passed, 1 skipped in 222.33 s** (14:34 to 14:38Z).
  - The create took 79.3 s.
  - **`n2`'s pod deleted** (the harness's `replace_node`): the next was there 0.11 s later. The core
    made the restore run 46.77 s after `replace_node` returned, with `ready` and `push` done for
    `n2` alone and verify held at its first try (0.28 s). Ready True came at +60.36 s.
  - **Stepped to `three-node-unmanaged`, `n2`'s pod deleted again**: the restore run came at +46.08
    s, with the push `skipped`, and Ready at +56.86 s. **The marker read absent**: `n2`'s
    `ethernet-1/1` held no description after its pod was replaced, the kind's baseline.
  - The stopped node's scenario skipped with the reason of the block above, the twin destroyed
    first.
- **A run stopped before its end.**
  - **One Ctrl-C** (SIGINT to pytest) 5 s into `cf-life`'s create, its namespace made: pytest's
    session teardown ran the harness's `close`, which asked the twin's deletion 0.55 s after the
    interrupt. The create ended `failed` with `run.cancelled`, and the twin was gone 61 s later
    (exit 2, nothing left).
  - **Two Ctrl-Cs 0.21 s apart**, 6 s into the create: the same, the deletion asked 0.38 s after the
    first. The second interrupt surfaced only after the teardown, in pytest's report (exit 130).
  - **A run stopped hard** (SIGKILL, exit 137) 5 s into the create, as a closed terminal or a lost
    host would stop it: it left the twin in the store (`twin.creating`, phase `planned`) with its
    namespace. The next run's start printed `removing the twin cf-life left behind`, and that run
    passed (the second lifecycle run above).
- **`test_lifecycle.py` after the review's fixes: 14 passed in 1173.66 s** (15:58 to 16:18Z), the
  kill cutting the holder and keeping its log first, then reading the renewal window on the
  client that writes the Lease and deletes the pod, and holding the take-over.
  - **The run before it** (15:36 to 15:54Z, at `17c1cc0`) passed 12 and failed 2 of the create
    kills, at `compiled` and `ready`, in the harness. What was read: with the cut made before the
    window was read, the Lease's `renewTime` did not move within the window's 15 s wait, twice, so
    the holder's renewals stopped under the cut; at `ea90e1c` the passing run's kills wrote at the
    overdue mark four times in nine (below). Why the renewals stopped was not read (the holder's
    log was not): the explanation is that a renewal's connection was opened anew and the cut
    refused it, the cut reaching the Lease then. A renewal overdue by 6 s (`OVERDUE_S`, `RENEW_S`
    and 1 s) now lets the kill write at once.
  - **In the passing run, four of the nine kills wrote at that overdue mark** (6.01 to 6.05 s
    behind the last renewal) and five within the window (0.31 to 2.04 s).
  - **Every next pod read the Lease 2.95 to 4.90 s after the deletion and held it 15.02 to
    15.03 s after that read**, 17.97 to 19.93 s after the deletion, the harness now asserting no
    less than the Lease's duration, less 1 s. Each pod was Ready at 21.3 to 22.1 s, and each kill
    answered at 21.6 to 22.4 s.
  - The create took 98.6 s. The kills at each phase boundary landed and resumed as above, each the
    same run, with Ready 89.3 to 115.0 s after the create.
  - **A waiting `twin create`** was killed 15.2 s after it was asked, the core serving again 21.8 s
    after the kill, and the command ended 75.6 s after the kill, exit 0.
  - **A waiting `twin destroy`** was killed 2.7 s after it was asked, the core serving again 21.8 s
    after the kill, and the command ended 23.0 s after the kill, exit 0.
  - The deletion during the apply left the twin gone in 15.4 s. The log held 545 lines, each one
    JSON, with no token or password.
- **`test_isolation.py`: 3 passed in 271.94 s** (16:49 to 16:54Z), each probe the harness's `reach`
  as read in "the conformance suite's reach", above. Its local run, after it, skipped the scenario
  for the local driver's isolation by `names` (2 passed, 1 skipped in 6.28 s).
  - **The twins.** `cf-iso-a` (`three-node-probed`) was created in 94.3 s and `cf-iso-b`
    (`two-node`) after it in 74.0 s. Both records then read Ready and settled, and verify held 19
    and skipped 5, and held 6 and skipped 2. The destroys took 46.8 s and 12.5 s.
  - **The control.** From `n1-loop-a` of `cf-iso-a`, 160.6 s old on 22 and 182.2 s old on 57400,
    its own twin's `n1` answered 0 at its pod's address, its Service's cluster address and its
    LoadBalancer address, each in 0.11 to 0.13 s.
  - **Another twin, refused.** From `n1-loop-a` (161.1 to 183.1 s old), each node of `cf-iso-b`
    answered 1 on 22 and 57400 at each of its three addresses, in 0.11 to 0.12 s.
  - **A third namespace, refused.** The pod of no twin ran 1.24 s after it was asked and was first
    used at 15.0 s old. From it, each device node of both twins answered 1 on 22 and 57400 at each
    of its three addresses: in 0.09 to 0.13 s, but `cf-iso-a`'s `n3`, refused in 1.15 to 1.17 s on
    every path and port, still a refusal well inside `nc`'s 3 s; why `n3` alone was slower was not
    read.
  - **The test's host** connected to each device node's record address (its LoadBalancer's) on
    57400 within 0.01 s.
  - **At the session's end** the probe's namespace was gone 9.3 s after its delete, the runtime held
    no twin, and the core's 88 lines were each one JSON, with no token or password.
- **`test_isolation.py` after the review's fixes: 3 passed in 287.80 s** (17:14 to 17:19Z). A
  refusal is now status 1 with nothing on either stream, and the probe pod's age is the harness's own
  clock from its first read of the pod running. Every probe answered as above:
  - the control 0 on every path, from `n1-loop-a` 161.5 s old on 22 and 187.7 s old on 57400;
  - each node of `cf-iso-b`, from `n1-loop-a`, and each device node of both twins, from the pod of no
    twin (first used at 15.0 s, 1.77 s after it was asked), refused on every path and port, with
    nothing printed.
  - The twins were created in 90.0 s and 84.7 s and destroyed in 46.8 s and 12.5 s; the test's host
    reached each device node's record address on 57400 within 0.01 s; the probe's namespace was gone
    11.7 s after its delete.
  - **The slower refusals moved.** This run, every path to `cf-iso-b`'s `n2`, from either source,
    was refused in 1.13 to 1.17 s, and `cf-iso-a`'s `n3` in 0.10 to 0.12 s; every other refusal took
    0.10 to 0.13 s. So the slower refusals belong to no one node and no one twin; which host each pod
    ran on, and why a refusal took a second longer, was not read.
- **The whole suite, `make conformance DRIVER=clabernetes`: 44 passed, 4 failed, 1 skipped in
  3450.33 s** (57:32 by `time`, 18:52 to 19:49Z), `make`'s exit status 2, after the local runs had
  ended, the development host booting nothing. Its start found the core's pod Ready, the tag
  `c6be28acb35b` and `FYLGJA_RESYNC_S` 3600, and no twin left behind. Passed: `test_isolation.py` 1,
  `test_lifecycle.py` 12, `test_restore.py` 3 (the stopped node skipped, as above),
  `test_step_kills.py` 10, `test_steps.py` 16 and `test_zz_end.py` 2.
  - **The four failures are the site's, as in the module's run above.** The deployed core still held
    no EOS login: the overlay's EOS login was not applied, and the credentials Secret was the one
    the module's run met. The step to `three-node-n3-eos` ended `diverged` at `applied` after a
    77.78 s apply, for `credential.missing` in `ready`; the create from `mixed` ended `failed` in
    125.4 s, its one error `credential.missing` on `e1`, `FYLGJA_CREDENTIAL_EOS_USERNAME is not
    set`, so the dry runs of its two steps answered no changes. The dry run of a create from `mixed`
    had answered `ok`. Each twin was destroyed `ok`.
  - **The create** from `three-node` took 89.4 s end to end: its apply 67.95 s, its readiness
    12.04 s and its push 8.28 s; each node answered its own host name through its push transport,
    and the destroy took 14.7 s. The other creates from `three-node` took 88.1 to 90.9 s, from
    `two-node` 75.7 to 84.6 s and from `three-node-probed` 90.0 s.
  - **Each step of `cf-step`**, the wait settling at its first try (0.26 to 0.28 s) unless named:
    - the link removed and added back, the port disabled and enabled, and the configuration dropped:
      3.94 to 8.10 s end to end, the applies 2.31 to 6.37 s; the configuration given back: 6.66 s,
      `n2`'s push 2.60 s; `two-node`: 8.04 s;
    - `three-node`, `n3` added: 65.78 s, its apply 57.55 s, `n3` readied in 3.85 s and pushed in
      2.70 s;
    - `three-node-probed`: 63.36 s, its apply 25.49 s, the wait settling after 35.86 s;
    - the bundle it runs: 0.83 s, `unchanged` at `compiled`;
    - `three-node-probed-moved`, under `--allow-restart`: 62.18 s, its apply 58.02 s, the wait
      settling after 2.17 s; back to `three-node`: 36.85 s, its apply 35.05 s.
  - **The 18 kills.** The Lease was written 0.32 to 2.82 s after a renewal in fifteen, and at the
    overdue mark, 6.01 to 6.05 s after one, in three. The next pod read the Lease 3.08 to 4.89 s
    after the deletion and held it 15.02 to 15.03 s after that read, 18.10 to 19.92 s after the
    deletion and 18.68 to 24.89 s after the last renewal; it was Ready at 21.23 to 22.82 s, and each
    kill answered at 21.51 to 22.97 s. Every next pod waited for the Lease the pod that went still
    held. The harness kept 1413 lines of the pods that went.
  - **A kill at each phase boundary of a create**, each resume the same run: at `compiled`,
    `admitted` and `planned` (1.2 to 1.8 s in) the record read `planned`, the core logged `resumed
    after planned` and applied again (2 applies), and Ready came 80.3 to 91.3 s after the create; at
    `applied` (70.3 s in) and `ready` (80.6 s in) it resumed after that phase with 1 apply, Ready
    109.0 and 108.7 s after the create; at `pushed` (91.7 s in) the run had ended and nothing
    resumed. Killed 10 s into a create's apply, the core answered at 22.47 s, resumed after
    `planned` with 2 applies, and was Ready 86.6 s after the create's `--no-wait` returned.
  - **A waiting `twin create`**, the core killed 13.9 s after it was asked, served again 22.2 s
    after the kill, and the command ended 74.2 s after the kill, exit 0. **A waiting `twin
    destroy`**, the core killed 0.9 s after it was asked, served again 22.0 s after, and the command
    ended 24.3 s after the kill, exit 0. **A deletion 2.6 s into a create's apply** left the twin
    gone 15.1 s after it was asked.
  - **A kill at each phase boundary of a step** (`cf-skill`, `two-node` to `three-node`), each
    resume the same run: at `compiled`, `admitted` and `planned` (0.9 to 1.2 s in), resumed after
    `planned` with 2 applies, stepped 75.0 to 93.3 s after the kill; at `applied` (58.8 s in),
    `ready` (63.2 s) and `pushed` (65.2 s), resumed after that phase with 1 apply, stepped 22.9 to
    26.8 s after; at `verified` (66.8 s in) the run had ended and nothing resumed. Killed 10.1 s
    into the step's apply, the core answered at 21.71 s, resumed after `planned` with 2 applies, and
    stepped 54.2 s after the kill. The step back to `two-node` that followed the kill at `compiled`
    took 97.95 s, its apply 96.10 s, where each of the others took 6.29 to 10.42 s; why was not
    read.
  - **A deletion asked once the core answered again**, 22.1 s after a kill 5 s into a step's apply,
    left the twin gone 33.4 s later: the step `diverged`, the destroy `ok`, `n3` among what was
    removed. **A step cancelled 5 s into its apply** ended 0.59 s after the cancel, the twin
    `diverged` at `planned` and refusing a new spec `409 twin.diverged`; it was destroyed in 46.7 s.
  - **A node replaced.** `n2`'s pod deleted, the next was there 0.12 s later; the restore run was
    made 44.72 s after `replace_node` returned, readied and pushed `n2` alone, and Ready came at
    +59.99 s. Stepped to `three-node-unmanaged` (3.88 s) and `n2`'s pod deleted again: the restore
    run at +52.77 s, its push `skipped`, Ready at +67.51 s. **The marker read absent**: `n2`'s
    `ethernet-1/1`, which held the pushed description `to n1 ethernet-1/1` and subinterface 0 before
    the replacement, held `admin-state` `enable` alone after it.
  - **Isolation**, as in the module's runs: `cf-iso-a` created in 90.0 s and `cf-iso-b` in 82.4 s;
    the control accepted on every path, from `n1-loop-a` 161.2 s old on 22 and 187.0 s old on 57400;
    each node of `cf-iso-b` from `n1-loop-a`, and each device node of both twins from the pod of no
    twin (running 1.23 s after it was asked, first used at 15.0 s old), refused on every path and
    port, nothing printed. The slower refusals, 1.11 to 1.16 s, were this time every path to
    `cf-iso-b`'s `n1`, from either source; every other took 0.10 to 0.15 s. The test's host reached
    each device node's record address on 57400 at once; the destroys took 46.8 and 12.6 s.
  - **At the session's end** the runtime held no twin and no record named one; the core's 2006 lines
    were each one JSON, holding no token or password; the probe's namespace was gone 11.8 s after
    its delete. Read by `kubectl` after it: no namespace labelled `fylgja.owner=core`, `fylgja.twin`
    or `fylgja.conformance=probe`; in `fylgja` the NetworkPolicy `versity` alone, no pod labelled
    `fylgja.reading` and no annotation on the Lease.
- **`test_restore.py` twice more, with `test_zz_end.py`: 5 passed, 1 skipped in 220.33 s, and in
  224.82 s** (19:51 to 19:55Z and 19:55 to 19:59Z), exit 0 each, the stopped node skipped as above.
  The creates took 79.6 and 81.9 s. `n2`'s pod deleted, the restore run was made 47.52 and 45.71 s
  after `replace_node` returned, and Ready came at +58.33 and +59.46 s; stepped to
  `three-node-unmanaged` (3.94 s each) and replaced again, the restore run came at +41.41 and
  +49.14 s, its push `skipped`, and Ready at +55.41 and +55.96 s. Each session's 106 lines were
  each one JSON, holding no token or password, and the cluster was left as the whole run left it.
- **The SR Linux marker after a pod replacement: absent in all three readings**, the whole run's and
  the two above, as in the module's run before them. Each time `n2`'s `ethernet-1/1` held the
  description `to n1 ethernet-1/1` and subinterface 0 that the create from `three-node` had pushed,
  the step to `three-node-unmanaged` pushing `n2` nothing; after its pod was replaced, with no push
  since, the port held `admin-state` `enable` alone. **So a replaced pod boots the kind's baseline,
  not what its node was pushed**, as [D-048](decisions.md#d-048) and [D-023](decisions.md#d-023)
  assume. The one earlier reading, of a marker present after a link-mode switch replaced the pod,
  was not seen again; the switch itself was not repeated, the pod being replaced by its deletion in
  each of the three readings.

- **The four cEOS scenarios, read on 2026-11-08 once the site's EOS login was applied** (the
  overlay rolled by the maintainer; the core's pod rolled with `FYLGJA_CREDENTIAL_EOS_USERNAME`
  and `FYLGJA_CREDENTIAL_EOS_PASSWORD` present; the image still `fylgja-core:c6be28acb35b`;
  the suite at `c12d986`). `test_steps.py` alone with `test_zz_end.py`: **22 passed in
  827.96 s** (21:14 to 21:28Z). The dry run of a create from `mixed` answered `ok`; the step to
  `three-node-n3-eos` was refused without `--allow-restart` (`step.restart.required` on `n3`)
  and with it ended `ok` in 85.8 s, `n3` recreated and `n1` and `n2` kept, its phases apply
  77.6 s, ready 4.3 s, push 1.8 s; `cf-eos` was created from `mixed` in 95.2 s and verified; the
  step to `mixed-e2-port` was refused without `--allow-restart` and made with it, as the dry run
  answered. No namespace was left. With this the suite has passed whole on both drivers.

---

## lightkube 1.0.1, against k3s v1.37.1+k3s1

lightkube 1.0.1 with lightkube-models 1.37.0.8, httpx2 2.16.0 and msgspec 0.22.0 on Python
3.14.4, from the development host through the cluster's kubeconfig, on a two-node SR Linux
twin. *(2026-11-05)*

- **Objects.** A Namespace, a NetworkPolicy and a `Topology` (a generic namespaced resource
  of `c9s.run/v1alpha1`) were made from plain mappings. A second create of the Namespace
  answered `409 AlreadyExists`; a server-side apply of the NetworkPolicy twice changed
  nothing and failed nothing. A merge patch set a Service's `externalTrafficPolicy`.
- **A watch outlives the stream's end.** A pod watch with a server timeout of 5 s and
  `on_error_retry` delivered 27 events over 55 s, across a silence of 32 s, to both pods
  `Ready`. A second watch saw a deleted node pod go (`DELETED`) and its replacement come
  (`ADDED`, another uid) within 1 s of each other.
- **A node's pods are `Ready` before its Topology says so**: `status.topologyReady` read
  false in the second both pods turned `Ready`.
- **Exec** in a node's pod, no container named, answered an argument vector's stdout,
  stderr and exit status apart (`out`, `err`, 7).
  - A budget run out raises `httpx2.ReadTimeout` at the budget (3.0 s for `sleep 30`), **and
    the command runs on in the node**; so does one whose output the caller stopped reading
    (a writer that refused past 64 KiB ended the exec with its own error).
  - A binary the node lacks is `ApiError` 500, not an exit status; a pod that does not exist
    is a refused WebSocket upgrade, 404.
- **A Lease** (`coordination.k8s.io/v1`) was created, and created again answered `409
  AlreadyExists`; a replace at the resourceVersion read renewed it, and a replace at the
  one before answered `409 Conflict`.
  - **The core's Lease, taken over and released** *(k3s v1.37.1+k3s1, lightkube 1.0.1,
    2026-11-06)*. `core/tests/cluster/test_lease_cluster.py` holds a Lease in the
    kubeconfig's default namespace by `KubeLeases` (`core/src/fylgja_core/lease.py`), as `a`
    and `b`, two holders in one process; it passed alone three times, each in 25.4 s (5
    tests). Created by `a`, the Lease read back holder `a`, `leaseDurationSeconds` 15, no
    transitions and `acquireTime` equal to `renewTime`; `b` was still waiting 10 s later.
    `a`'s renewals stopped just after one was answered, with no release, and **`b` held it
    15.0 s later** (15.1 s after that renewal was sent), in each run. `b`'s reads fell just
    after `a`'s renewals there, so this is the least the rule allows: a read falling just
    before one adds up to the 5 s between reads. `a`, its clock stood still since it stopped
    (as a suspended host's does: run on, `a` is lost with nothing written), renewed at the
    version it held: answered 409, the Lease read back named `b`. **A release frees it at
    once**: written by `b` with no holder, its transitions kept, it was `a`'s 0.02 s later, at
    `a`'s first read.
  - **A time at a whole second is refused** *(k3s v1.37.1+k3s1, lightkube 1.0.1, msgspec
    0.22.0, 2026-11-06)*. lightkube encodes a time with no microseconds with no fraction
    (`…:00Z`), and a replace carrying one as `renewTime` and `acquireTime` answered `400
    BadRequest` in each run: a Lease's times are `MicroTime`, read with six digits. One write
    in a million would fail so; `KubeLeases` writes such a time a microsecond later.
- **A deleted node pod** was replaced and `Ready` in 63 s, at the same LoadBalancer address,
  its Service still `Local`.

**fylgja-core, phase 6: the driver's reach, over lightkube** *(clabernetes 0.10.1, lightkube
1.0.1, k3s v1.37.1+k3s1, 2026-11-05)*

`core/tests/cluster/test_kube_cluster.py` reads every call of `LightKube`
(`core/src/fylgja_core/clabernetes/kube.py`) from the development host, on the twin `kube-k8s`:
`steps/two-node.json`, two SR Linux nodes and one link, planned by the clabernetes plan on an
allocation holding no registry, its three files applied through `LightKube` alone, the image
cached on every node. The module passed alone three times, in 72.3 s, 104.8 s and 116.5 s (6
tests), the last by `make cluster` with a pull credential set in the environment; a range below is
the three runs'.

- **Applies.** `namespace()` of a name not there answered None. The Namespace applied twice read
  its two labels, with `kubernetes.io/metadata.name` and the pod-security label beside them, and
  not deleting. The policy applied. The Topology applied twice read `metadata.generation` 1, and
  no `status` yet.
- **The Topology's status** came with `conditions`, `kind`, `linkCount`, `nodeCount`,
  `observedGeneration`, `readyNodeCount`, `topologyReady` and `topologyState`.
  `observedGeneration` equalled the generation 2.1 s after the apply, at the second read, and
  more than 50 s before any pod was `Ready`: it says the controller has seen the generation, not
  that the nodes run it. Both pods turned `Ready` and `topologyReady` true within the same 2 s
  poll, 54.7–55.0 s after the apply.
- **A Topology naming a pull secret its namespace lacks gets no pod**, so the driver's `apply`
  makes every pull secret before the Topology. With a pull credential's registry in the
  allocation and no Secret applied, each clabernetes `Node` read `PlanApplied` `False`, reason
  `ImagePullSecretMissing` (`resolving image pull Secret <namespace>/fylgja-pull-<key>: secrets
  "…" not found`), and the Topology `observedGeneration` 1, `topologyReady` false and
  `topologyState` `deploying`, for 300 s. clabernetes resolves the Secret itself, before any
  kubelet would; whether a Secret made later starts the nodes was not read. That namespace,
  holding no pod, was gone 8 s after its delete.
- **Pods and Services.** `pods` by the twin's two labels answered two pods `Running`, each named
  `<node>-<hash>-<suffix>` as a Deployment's are, and labelled `c9s.run/topologyNode` `n1` or
  `n2`. `services` answered `n1` and `n2` of type `LoadBalancer`, each holding an address at the
  first read after the twin was ready and at `externalTrafficPolicy` `Cluster`, and `n1-wire` and
  `n2-wire` of type `ClusterIP`. **No name carries the Topology's name**: a node's Service is
  named for the node. A merge patch set `n1` to `Local` and left `n2` at `Cluster`.
- **An annotation comes and goes by server-side apply, at the same generation.** The Topology
  applied with `fylgja.recreate: "{}"` read the annotation at generation 1; applied again as
  rendered, under the same field manager, it read no annotation, still at generation 1. The
  Topology carries no other annotation.
- **Exec** in `n1`'s pod, no container named:
  - `sh -c "echo out; echo err >&2; exit 7"` answered `Exec(7, "out\n", "err\n")` in 0.12 s;
  - `sleep 30` within 3 s raised `httpx2.ReadTimeout` at 3.05 s, a `KubeFailed` with no status;
  - a binary the node lacks answered `500 InternalError` in 0.11–0.12 s;
  - a pod that does not exist raised `httpx2.websockets.WebSocketUpgradeError` at `404 Not
    Found` in 0.02 s;
  - `yes | head -c 200000` answered its last 65536 bytes in 0.12–0.13 s.
- **A deleted pod, watched.** A watch of pods labelled `fylgja.owner: core` in every namespace
  began with `ADDED` for each pod there. Within 0.1 s of `delete_pod` the old pod read deleting
  and still `Ready`, and its replacement was `ADDED` at another uid, `Pending`: **for about a
  second the node had two pods, the old one terminating and `Ready`.** The old pod's phase turned
  `Failed` at 0.9–1.1 s, and it was `DELETED` at 1.3–1.9 s. A second `delete_pod` of its name
  raised nothing.
- **A namespace deleted.** `delete_namespace` returned in 0.01–0.02 s and `namespace()` then read
  it deleting. A second delete while it was being deleted raised nothing. It was gone 12.1 s,
  44.2 s and 56.3 s after the delete, and a delete of it gone raised nothing.

**fylgja-core, phase 6: a client lightkube cannot make** *(lightkube 1.0.1, httpx2 2.16.0,
Python 3.14.4, 2026-11-05)*

Read on the development host with no cluster: `KubeConfig.from_file` or
`KubeConfig.from_service_account`, then `AsyncClient(config=…)`, over files in a temporary
directory. No request was made. `kubeapi.client()` answers each as `Unconfigured`
(`core/tests/test_drivers.py`).

- **From a kubeconfig.** A file that does not exist is `ConfigError`, and one that is not YAML
  `yaml.YAMLError`, both from `from_file`. YAML whose top is a scalar or a list is
  `AttributeError`, and a member of the wrong shape (`users` a list of strings, `clusters` a
  string) `TypeError`.
- **Raised by `AsyncClient`, not by `from_file`:**
  - a `current-context` naming no context, or none set, is `ConfigError`;
  - a context naming a cluster or a user that is not there is a bare `KeyError`;
  - a client certificate, key or CA file that is missing is `FileNotFoundError`, and a CA
    that is not PEM `ssl.SSLError`, as the client builds its TLS context;
  - `certificate-authority-data` that is not base64 is `binascii.Error`, a `ValueError`.
- **From a service account** holding a token:
  - no `namespace` file beside it is `ConfigError`;
  - `KUBERNETES_SERVICE_HOST` or `KUBERNETES_SERVICE_PORT` unset is a bare `KeyError` naming
    it, both read from the process's environment;
  - a missing `ca.crt` is `FileNotFoundError`, and one that is not PEM `ssl.SSLError`, raised
    by `AsyncClient`.

**fylgja-core, phase 6: the pod watch, as lightkube runs it** *(lightkube 1.0.1, httpx2 2.16.0,
Python 3.14.4, 2026-11-06)*

Read on the development host with no cluster, in lightkube's source
(`lightkube/core/generic_client.py`, `GenericAsyncClient.watch` and `WatchDriver`) and over
httpx2's `MockTransport` (`core/tests/test_clabernetes_kube.py`). None of it was read on the
cluster.

- **`AsyncClient.watch` answers an asynchronous generator**, though it is typed an
  `AsyncIterable`; lightkube's own `wait` closes one with `aclose()`. Its `finally` closes the
  response it streams, so a watch closed while it waits for its next line closes its response
  at once. `LightKube.watch_pods` closed without closing lightkube's watch returned with the
  response still open. What a close does to the API server's side of the watch was not read.
- **How it goes on after a stream, in its source.** It keeps the `resourceVersion` of the last
  object it decoded, none before the first, and sends it with each request. A stream that ends
  cleanly is asked for again at that version, and nothing is delivered again. An `ERROR` line is
  raised as `ApiError` carrying the API's Status, inside the loop that hands a failure to
  `on_error`; one of code 410 drops the version, so the next request carries none and begins as
  a new watch does, with every pod there `ADDED` (the cluster's reading above). The request is
  sent before that loop's `try`, so a failure to send it, a refused connection, is raised out of
  `watch` itself, to `LightKube.watch_pods`' own loop, which starts a fresh watch with no
  version. A response that is not 2xx is raised by httpx's own `raise_for_status`, an
  `HTTPStatusError` and not an `ApiError`, so an HTTP 410, unlike an `ERROR` line of 410, does
  not drop the version and is asked for again at it. Which of the two the API server answers
  for a version too old was not read. *(2026-11-06: read since, on the cluster: the `ERROR`
  line, the bullet below.)*
- **A version too old is answered inside the stream** *(k3s v1.37.1+k3s1, 2026-11-06)*. A pod
  watch asked at `resourceVersion` `1`, through lightkube's client as `kubeapi.client()` makes it
  and its handler that raises, was answered within 0.03 s by an `ERROR` event, raised as
  `ApiError` with code 410 and reason `Expired`, in each of the cluster module's runs
  (`test_restore_cluster.py`). That is the form lightkube's own retry answers by dropping the
  version, so a watch whose version is compacted starts again as a new watch does, and
  `LightKube.watch_pods` needs nothing of its own for it.
- **A line it cannot decode** is msgspec's `DecodeError` (not JSON) or `ValidationError` (JSON
  not shaped as an event), each a `ValueError`, read over `MockTransport`. Neither is an
  `httpx2.HTTPError`, so it is raised out of lightkube's watch and past `LightKube.watch_pods`'
  retries (`kube.FAILURES`), to the clabernetes driver's `events`, which watches again.

**From inside a pod, under the core's service account** *(lightkube 1.0.1, httpx2 2.16.0, Python
3.14.9, k3s v1.37.1+k3s1, clabernetes 0.10.1, 2026-11-07)*

The pod `reading` in `fylgja` ran the core's image, `fylgja-core:73c2f149ef62` pushed to
`<registry>`, under the service account `fylgja-core` of `deploy/rbac.yaml`, its command `sleep
3600`. Its token was projected by hand: `automountServiceAccountToken: false`, and at the service
account's path a projected volume of a `serviceAccountToken` of `expirationSeconds: 600`, the
`kube-root-ca.crt` ConfigMap and the namespace by the downward API. A script fed to `python -` by
`kubectl exec -i` made each client by `kubeapi.client()` and printed one line a call, a refusal by
the status, verb and resource of the API's message. In the pod `lease.identity()` read `reading`,
the pod's name, and `kubeapi.core_namespace()` `fylgja`.

- **Every call of `LightKube`** (`core/src/fylgja_core/clabernetes/kube.py`) was made on a scratch
  twin, `reading`: `steps/two-node.json` less `n2` and its link, planned in the pod by the
  clabernetes plan. In the namespace `fylgja-twin-reading`:
  - the namespace was read absent (None), applied, read, applied again with a label added and
    read with it;
  - a pull secret was applied absent and again with its data changed;
  - the NetworkPolicy and the Topology were applied twice each, and the Topology read at
    generation 1;
  - the node's pod was watched to `Ready`, 54.0–55.4 s after the watch started, and listed;
  - the Services were listed, `n1` patched to `Local` and read so;
  - an exec of `["true"]` answered `Exec(0, "", "")` in 0.10–0.11 s;
  - the pod was deleted: its replacement `ADDED` 0.05–0.06 s after, the pod `DELETED` 1.7–2.1 s
    after;
  - the namespace was deleted, and gone 44.2–48.3 s after.

  Each other call took 0.01–0.04 s. A range is the five whole runs' (in two of them a call was
  refused, below), the exec's the three in which it answered.
- **The rules.** The script ran under the ClusterRole as Task 6 wrote it, and again with it
  changed by hand between runs: a verb added for each refusal, then each verb no call needed
  taken away.
  - **An exec asks `get` and `create` on `pods/exec`.** Under the role as written, with `create`
    alone, the exec was the one call refused: its WebSocket upgrade, a GET, answered 403, as
    `WebSocketUpgradeError`, whose body httpx2 never reads. The same handshake sent raw through
    the client read the API's message: **`get` on `pods/exec`**. With `get` alone, it was refused
    403 again, its message naming no verb (`pods "reading" is forbidden: `). The API server's
    metrics read `AuthorizePodWebsocketUpgradeCreatePermission` enabled, at beta: an upgrade to an
    exec is authorised as `get`, its HTTP verb, and then as `create`.
  - **A server-side apply of an object not there asks `create` beside `patch`.** With `create`
    taken from Secrets, the apply of the absent pull secret answered `403 create secrets`.
  - **The pod watch across every namespace asks `watch` alone.** With `list` taken from pods,
    `pods` answered `403 list pods` in the twin's namespace, while the watch delivered every
    event. `list` is `pods`', in a twin's namespace.
  - **Taken away, every call still answering:** `list` on namespaces; `get` and `delete` on
    Secrets and NetworkPolicies; `list`, `watch` and `delete` on Topologies; `get` on Services;
    and `get` on pods. No call reads a Secret, a NetworkPolicy, a Service or a pod by name, lists
    namespaces or Topologies, or deletes a Secret, a NetworkPolicy or a Topology: each goes with
    its namespace.
  - **The rules as read**, which `deploy/rbac.yaml` holds:

    | Resource | Verbs | Asked by |
    |---|---|---|
    | `namespaces` | `get`, `create`, `patch`, `delete` | `namespace`, `apply` (`create` for one not there), `delete_namespace` |
    | `secrets` | `create`, `patch` | `apply` |
    | `networking.k8s.io` `networkpolicies` | `create`, `patch` | `apply` |
    | `c9s.run` `topologies` | `get`, `create`, `patch` | `topology`, `apply` |
    | `services` | `list`, `patch` | `services`, `patch_service` |
    | `pods` | `list`, `watch`, `delete` | `pods`, `watch_pods` (every namespace), `delete_pod` |
    | `pods/exec` | `get`, `create` | `exec`'s WebSocket handshake |
    | `coordination.k8s.io` `leases`, the Role in `fylgja` | `create`; `get`, `update` on `fylgja-core` | `KubeLeases` |

- **The driver's `events`, the watch, under the role.** `watch_pods` by the owner's label, started
  before the twin's namespace was made, delivered its pod `ADDED` 2.5–4.0 s after it started, then
  `MODIFIED` to `Ready`, the deleted pod's replacement and its `DELETED`.
  - **A 403 on the watch is no `KubeFailed`.** Under the role less `watch` on pods, each request
    of `watch_pods` was refused by an `HTTPStatusError` 403. lightkube hands that to
    `watch_retry`, so it retried after 1, 2, 4 and 8 s, one WARNING each (`HTTPStatusError,
    status 403`), and in 15 s delivered nothing and raised nothing. Under a role without it, the
    driver's `events` would be silent but for those WARNINGs. The consequence, from the code and
    not read further: the retries' pause grows to the seam's 60 s and holds there, no pod is
    renewed at its container's end, and a twin's pass runs at the loop's resync alone. A
    `KubeFailed` raised out of the watch would have been as silent: `events` catches whatever its
    watch raises, logs one WARNING and watches again.
- **The renewal's deletion.** Under the role, `delete_pod` deleted a pod in a twin's namespace,
  which the renewal ([D-070](decisions.md#d-070)) and the hot-add rely on.
- **The Lease** was read by `KubeLeases("fylgja-core")`, in the client's default namespace, the
  service account's: `fylgja`. Under the Role `fylgja-core-lease`:
  - it was read absent (None), created, read, replaced, released (holder empty, transitions 0)
    and read;
  - a create of another name, `fylgja-core-reading`, was allowed, and its read refused, `403 get
    leases`: `get` and `update` are confined to the core's Lease by name.
  - **`create` cannot be confined by name.** A Role whose one rule gave `create`, `get` and
    `update` on `fylgja-core` by name refused the create of `fylgja-core` itself, `403 create
    leases`, as it refused the create of `fylgja-core-reading`.

  Each Lease was deleted by `kubectl` after its run.
- **What the role refuses.** Each was refused 403 at the cluster scope: `list nodes`; `list
  secrets` across every namespace; and the create of a ClusterRoleBinding, sent as a server dry
  run.
- **A Lease's name**, the API's rule against `config.py`'s (`_lease`). Server dry runs from the
  development host created a Lease named by 63 characters, by 64, by a 64-character label then
  `.b`, and by 253; one of 254 was refused, `must be no more than 253 characters`, as the pattern
  refuses it. Neither holds a label of a Lease's name to 63 characters. No name the pattern
  accepts was refused.
- **The token's rotation, and an exec's handshake across it.** lightkube's client made from a
  service account authenticates by `BearerTokenFileAuth` (`lightkube/config/client_adapter.py`):
  it reads the token file at its first request, sends that token until a response is 401, then
  reads the file again and sends the request once more. The WebSocket upgrade of an exec is httpx2's
  `client.stream("GET", …)` and goes through the same flow. In the pod, three clients were made
  and each answered a `get` and an exec on the first token. The script then waited for the token
  file to change and the first token's `exp` (decoded in the pod, never printed) to pass, and
  asked again with the same clients. Whether a call met a 401 was read from its client's cached
  token (compared by digest), which changes only then. Two runs:
  - **The kubelet's new token was issued 541 s and 545 s after the first** (their `iat`), each of
    600 s (`exp` less `iat`), 55–59 s before the first expired; the file held it within the 2 s
    the script read it at.
  - **11 s past `exp`, the first token was still accepted.** Every call answered on it and no
    client read the file again: the API server allows an expired token some leeway. Its length,
    between 11 s and 91 s (the bullet below), and what sets it were not read.
  - **91 s past `exp`, it was refused, and every kind of call followed the rotation.** The client
    that asked in the brief's order had its `get` refused 401 and sent again on the new token,
    answering in 0.03 s; its exec then answered on the new token in 0.17 s, and a watch opened
    anew delivered the pod `ADDED`. **An exec as a client's first call since, its handshake
    refused 401, read the file again and was upgraded, answering in 0.17 s.** So was a
    watch opened anew as a client's first call (0.02 s). `LightKube.exec` needs nothing of its
    own across a rotation.

---

## Versity S3 Gateway v1.10.0

`ghcr.io/versity/versitygw:v1.10.0` under Docker 29.8.1 on the development host, its
`posix` backend over a directory, one process holding 12 MiB. Read with SigV4 signed by
hand over httpx 0.28.1, path-style. *(2026-11-05)*

- **A bucket name** shorter than three characters is refused, `400 InvalidBucketName`.
- **Create only if absent.** A put with `If-None-Match: *` answered 200 on a key that did
  not exist and `412 PreconditionFailed` on one that did, leaving it as it was.
- **Replace only if unchanged.** A put with `If-Match` answered 200 at the object's ETag and
  412 at an earlier one; on a key that does not exist it answered `404 NoSuchKey`. The ETag
  is the body's MD5 in double quotes, and is matched with or without them.
- **One winner.** Of 32 puts started together, five rounds each: with `If-None-Match: *` on
  one new key, one answered 200 and 31 answered 412; with `If-Match` at one ETag, the same.
  The object read back was the winner's each time.
- **A conditional delete** answered 412 at an earlier ETag, the object kept, and 204 at the
  current one. A delete of a key that does not exist answers 204.
- **`ListObjectsV2`** with a `prefix` answered keys in order across pages (`max-keys` 5,
  twelve keys, three pages); `start-after` answered the keys after the one named.
- **An object is a file** under `<directory>/<bucket>/<key>`. After a restart of the gateway
  an object kept its ETag, and both conditions held as before.
- An unsigned request is `403 AccessDenied`; a put to a bucket that does not exist is `404
  NoSuchBucket`; a body of 8 MiB was accepted in one put.

**fylgja-core, phase 6: the object store against it** *(Docker 29.8.1, httpx 0.28.1, 2026-11-05)*

The live module `core/tests/live/test_object_store_live.py` runs the gateway with this line,
two keys made for the run in Docker's own environment, from which it reads each `-e NAME`:

`docker run -d --name fylgja-versity-<8 hex> --user <uid>:<gid> -p 127.0.0.1:<free port>:7070 -e ROOT_ACCESS_KEY -e ROOT_SECRET_KEY -v <data directory>:/data ghcr.io/versity/versitygw:v1.10.0 posix /data`

- **The line.** The image's `--help` names the listen address (`:7070` by default) and the
  root keys' variables (`ROOT_ACCESS_KEY` or `ROOT_ACCESS_KEY_ID`, `ROOT_SECRET_KEY` or
  `ROOT_SECRET_ACCESS_KEY`). `posix --help` gives `--object-lock-mode`, "lock mode for
  conditional object publishes", `flock` unless set. Under `--user` the gateway ran, and the
  module removed its data directory with the container. It answered a listing 0.46–1.10 s
  after `docker run`, and one signed `PUT /fylgja-live` made the bucket, answered 200.
- **The store contract passed whole**, each case under a prefix of its own in the one bucket:
  among them `a`, `a-b` and `a0` listed by name, and `configs/a b+c=é~x.cfg` filed and read
  back the same.
- **Each compare-and-set raced by 32 stores**, each with its own client and its own lock and
  no Lease between them, behind one barrier, five rounds each. Every round of three runs
  answered alike:

  | Raced | Answered | Read back |
  |---|---|---|
  | `create_twin` of one name | 1 accepted, 31 `Conflict` | the winner's record |
  | `update_twin` at revision 1 | 1 accepted, 31 `Conflict` | the winner's generation, at revision 2 |
  | `create_run` of one id | 1 accepted, 31 `Conflict` | the winner's run alone, by `list_runs()` and by its twin |
  | `update_run` from `queued` | 1 accepted, 31 `Conflict` | the winner's run, `running` |
  | `append_event` to one run | 32 accepted, numbered 1 to 32 | `events` in order, each the event its writer was answered |
  | `put_bundle` of one id | one True, 31 False | the whole bundle, by each of the 32 stores after its answer |
  | `delete_twin` at revision 1 | 1 accepted, 31 `NotFound`, no `Conflict` | the twin gone |

  Where the store raises an unsettled refusal (a run's marker, a bundle's file or manifest,
  an event) none was raised: each refusal the gateway gave there was a 412.
- **The edges**, each held equal to the fake endpoint's answer to the same call:
  - A delete with `If-Match` of a key that does not exist is `404 NoSuchKey` (without a
    condition it is 204, above). The fake answered 204 until this reading, and now answers as
    the gateway does; the store reads it as `NotFound`.
  - A put signed 20 minutes behind is `403 RequestTimeTooSkewed`, and nothing is written. The
    window itself was not read.
  - A start with a wrong secret key is `403 SignatureDoesNotMatch` at the proof's first put;
    the error holds neither key.
  - A start against a bucket that does not exist is `404 NoSuchBucket` at the proof's first
    put: an `S3Error`, not `Unconditional`.
- **A listing in pages of five** (`S3(…, page=5)`) over twelve events: the five after event 7
  came in one page, sent with `start-after` and not marked truncated; the ten after event 2 in
  two, `start-after` then `continuation-token`; all twelve in three.
- **A continuation token is the last key of its page**, as it stands. The one after
  `configs/a b+c=é~x.cfg` held its space, `+`, `=`, `é` and `/`; sent percent-encoded (`%20`,
  `%2B`, `%3D`, `%C3%A9`, `%2F`), it was signed as sent and answered.
- **After `docker restart`** the gateway answered a listing again in 1.60–1.71 s, and a new
  store read a twin written before and replaced it at the ETag it read.
- **Wall time** through the store, five of each in each of three runs: `open`, the proof's
  six requests on a new client, medians 21.2–22.9 ms (20.2–83.8); one `append_event`, a get, a
  listing and a put, medians 10.1–11.3 ms (9.6–25.4); `list_twins` over 20 twins, a listing
  and 20 gets, medians 87.0–103.7 ms (68.9–176.2). That is 3.5–5 ms a request.
- The module passed alone, 61 tests in 55.7 s and 60.2 s, after a first run that failed only on
  the conditional delete of a missing key, where the fake differed.

**fylgja-core, phase 6: a bucket made by `mkdir`, and the image's entry point** *(Docker 29.8.1,
2026-11-07)*

The base's StatefulSet (`deploy/versity.yaml`) makes its bucket with an init container of the
gateway's image, `command: ["mkdir", "-p", "/data/fylgja"]`, and starts the gateway with `args:
["posix", "/data"]`. Read on the development host through the live module's helpers and its
`docker run` line (above), with a directory made under the data directory before `docker run`
in place of the signed `PUT /<bucket>`, by the user the gateway then ran as (`--user`), as the
init container is; three runs.

- **A directory made before the gateway starts is a bucket.** `ObjectStore.open` over the bucket
  `fylgja` with no prefix, as the core opens `s3://fylgja`, proved the endpoint in each run, in
  36.3, 31.9 and 36.3 ms. In the second and third runs a listing of the bucket after the proof
  answered no key, and a bucket no directory was made for answered `404 NoSuchBucket` at the
  proof's first put, on the same gateway.
- **What it wrote was under the data directory**: `.vgwlocks/<64 hex>/<2 hex>` beside the bucket,
  and `fylgja/.sgwtmp`. `docker diff` of the container (third run) listed only the mount point
  `/data`: nothing of the image's own filesystem was written.
- **The entry point** is a script, `/usr/local/bin/docker-entrypoint.sh`, read from its layer of
  the image, not run: given arguments it runs `exec /usr/local/bin/versitygw "$@"`, so a pod's
  `args` are the gateway's own and the gateway is the container's process; given none, it builds
  them from `VGW_BACKEND` and the variables beside it. The image's first layer is
  `alpine-minirootfs-3.24.3`, and it sets no user, so it runs as root unless told otherwise.
- **`mkdir` is in the image**: `docker run --rm --entrypoint mkdir
  ghcr.io/versity/versitygw:v1.10.0 -p /tmp/x` exited 0.
- The gateway answered a listing 0.84, 0.53 and 0.79 s after `docker run`. As user 10001 on a
  `local-path` volume, on the cluster, it is not read here.

**fylgja-core, phase 6: the gateway on the cluster** *(k3s v1.37.1+k3s1, local-path, 2026-11-07)*

The base's StatefulSet `versity`, read in its pod (k3s's section, "the core as a pod", holds what
the core did with it).

- **As user 10001 on a `local-path` volume, its root read-only**: `id` reads `uid=10001
  gid=10001`; `/data` is the claim `data-versity-0` (`local-path`, 1 GiB), ext4 mounted `rw`, its
  directory `drwxrwxrwx` and root's, as the provisioner makes it, so the init container's `mkdir -p
  /data/fylgja` as 10001 made the bucket; under it `.vgwlocks` and `fylgja` (`.sgwtmp` and the
  store's prefixes) are 10001's. `/` is an `overlay` mounted `ro`: a `touch` in `/`, `/tmp`, `/var`
  and `/home` answered `Read-only file system`, in `/root` `Permission denied`. **It writes nothing
  but under `/data`**: over 9395 requests its log holds no error, every answer 200, 204, 404 or
  412.
- **Scaled to none and back**, its pod was gone 3.1 s after the scale and Ready 2.9 s after the
  scale back, on its claim, the bucket and every object there.
- **Its process cannot be stopped from inside its container**: `kill -STOP 1` by `kubectl exec`
  answered `can't kill pid 1: Permission denied`.

---

## uvicorn 0.54.0, Starlette 1.9.0 and Python 3.14.4's `ssl`

Read from their source in the core's venv, with OpenSSL 3.5.5, and held by the pure tier's
`core/tests/test_server_main.py`, which runs `fylgja-core-server`'s `_Server` in a thread on the
development host. *(2026-11-06)*

- **A server's start and stop.** `Server._serve` awaits `startup`, then `main_loop` unless
  `should_exit` is set, then `shutdown` once `started` is, so a subclass's `startup` and
  `shutdown` run at every start and at every stop that follows one. A lifespan that fails at
  startup is `sys.exit(3)` raised from `startup` (`server.py`, line 118) before `started` is
  set: `shutdown` is not called. `main_loop` reads `should_exit` every 0.1 s.
- **`force_exit` skips the waits, not `shutdown`.** Set with `should_exit`, `Server.shutdown`
  still closes the listeners, asks each connection to shut down and sleeps 0.1 s; then it skips
  its waits for open connections and tasks, and the lifespan's shutdown (line 310). It still
  awaits each asyncio server's `wait_closed()` (line 329), within `timeout_graceful_shutdown`,
  which on Python 3.14 waits until every connection has dropped
  (`asyncio.base_events.Server.wait_closed`): a watch held open holds it until its stream ends,
  and a request in flight until its response is done. With a 3 s request in flight, a server so
  stopped began the loop's stop 2.99 s after losing its Lease, and the request answered 200 (Task
  3's review, a probe in the pure tier), so a lost Lease is not left to uvicorn's shutdown (below).
- **After a forced exit the lifespan's task is cancelled as `asyncio.run` closes the loop**, still
  waiting for its shutdown. Starlette's `Router.lifespan` catches the cancellation, runs the
  application's lifespan to its end (the loop's `stop()` in its `finally`), and sends
  `lifespan.shutdown.failed` carrying the traceback (`routing.py`, line 667), which uvicorn logs
  at ERROR on `uvicorn.error`: one line whose message is the traceback of a `CancelledError`.
  So `fylgja-core-server` runs the lifespan's shutdown itself wherever `force_exit` made uvicorn
  skip it, bounded by 2 s (`LOST_STOP_S`): at the loss of its Lease, before uvicorn's shutdown,
  and after a second Ctrl-C, before the Lease is released. The loop stops through its own
  `stop()`, at the cost the loop's close would have had, since that stop only cancels, and
  nothing is logged as failed. Only a stop that does not end within the bound leaves the
  lifespan's task to the loop's close, and the traceback with it; the pure tier holds both.
- **A loop's stop that raises does not raise from `LifespanOn.shutdown`.** Starlette sends
  `lifespan.shutdown.failed` carrying the traceback, uvicorn logs it at ERROR (`on.py`, lines
  128-134) and then "Application shutdown failed. Exiting." (line 73), and the call returns. The
  core's bound therefore warns of a stop that did not end, never of one that raised.
- **What holds a request, and how one cut ends quietly.** The protocol is `H11Protocol` and the
  event loop asyncio's: the core's `_config` names `http="h11"` and `loop="asyncio"`, so an
  installed httptools or uvloop, which `"auto"` would take (`protocols/http/auto.py`,
  `loops/auto.py`), is never picked. An upgrade of uvicorn must read these again.
  - `server_state.connections` holds each connection's protocol, added in `connection_made` and
    discarded in `connection_lost` (`h11_impl.py`, lines 92-108). `server_state.tasks` holds each
    request's task, `RequestResponseCycle.run_asgi`, removed when it is done (lines 250-260).
  - A request task cancelled: `run_asgi` catches the `CancelledError` as any `BaseException`,
    logs "Exception in ASGI application" with its traceback at ERROR, and answers 500, or closes
    the transport where the response has begun (lines 409-420). The core's `_Faults` catches
    `Exception` alone, so this is what a cancelled request does with no layer of the core's.
  - A connection's transport aborted: `connection_lost` runs on a later turn of the event loop
    (one `call_soon` over TCP, two under TLS) and sets the cycle's `disconnected`. From then
    `receive()` answers `http.disconnect`, and an application that returns, having answered
    nothing, is neither answered nor logged: both of `run_asgi`'s later branches test
    `disconnected` (lines 421-433).
  - So at the loss the core closes each listener and aborts every connection it accepted (next
    bullet), aborts every connection uvicorn holds, and then cancels every request; its
    outermost layer, `_Cut`, takes that cancellation alone, once lost: it awaits
    `http.disconnect` and returns, however many turns `connection_lost` takes. Read by a probe
    (a script outside the tree) on uvicorn 0.54.0 and h11 0.16.0, over HTTP and over TLS, 40 runs
    each, with a route held open, a route that would write once the loss was set and a stream in
    flight. In every run nothing was logged at WARNING or above, nothing was written, and each
    client's call failed with `RemoteProtocolError`. The same cancellation with no loss set gave
    500s and one "Exception in ASGI application" ERROR each, as without the layer.
- **What a listener holds that uvicorn does not yet** (Python 3.14.4's `asyncio`,
  `base_events.py` lines 275-360, `selector_events.py` lines 167-262 and 770-799).
  - A transport attaches to its `Server` as it is made (`Server._attach`, from
    `_SelectorTransport.__init__`). It is made by `_accept_connection2`, a task the accept
    starts, a turn after the accept. Under TLS the transport attached is the raw socket's,
    made before the handshake, and uvicorn's protocol has `connection_made` only once the
    handshake is done.
  - `Server.close()` stops the accepts and leaves those connections open; `Server.abort_clients()`
    (Python 3.13 on) aborts every transport attached, a TLS one in its handshake and a client
    that never sends its ClientHello among them.
  - A connection accepted before the close whose transport is made after it fails `_attach`'s
    `assert self._sockets is not None`: it is never served, and its socket closes only when the
    half-made transport, which sits in a reference cycle, is collected or the process ends (a
    `ResourceWarning`, "unclosed transport", and a `TypeError` from its deallocator on stderr):
    dropped, though not under `python -O` or `PYTHONOPTIMIZE`, which strip the assert, where it
    was served and its write answered 200 a few milliseconds after the cut; so the server refuses
    to start optimised (`server.optimised`).
  - So the core, at the loss, closes each listener and calls its `abort_clients()`. The pure tier
    holds it: a client whose TLS handshake ended after the loss was dropped and its `POST` wrote
    nothing, where without `abort_clients()` it was answered 200; a client that connected and
    sent nothing let the lost server end within 1 s, where without it the server waited out
    `GRACE_S` and logged an ERROR.
  - A loss during the lifespan's startup leaves no such window here. `Server.start_serving`'s
    `sleep(0)` queues uvicorn's startup ahead of the listener's first accept in the same turn of
    the loop, and the shutdown that follows closes the listener before any further await,
    cancelling that accept. The pure tier's test of it served no request with the core's second
    drop in `startup` and without it, so that drop is a guard.
- **TLS.** With `ssl_certfile` and `ssl_keyfile`, `Config.load()`, which `_serve` calls before
  `startup`, makes the context by `ssl.SSLContext(PROTOCOL_TLS_SERVER)` and
  `load_cert_chain(certfile, keyfile)`, `verify_mode` `CERT_NONE`, and `startup` serves each
  socket passed in `sockets` with it. So served, the core answered `/v1/version` over TLS,
  verified against its self-signed certificate, and a plain HTTP request to the same port had
  no answer.
- **What a pair or a CA bundle that does not load raises.** `load_cert_chain` on a file that is
  no certificate raises `ssl.SSLError` with no `reason`, its message `[SSL] PEM lib
  (_ssl.c:4160)`; with the key of another certificate, `ssl.SSLError` `KEY_VALUES_MISMATCH`; on a
  file missing, `FileNotFoundError`. `ssl.create_default_context(cafile=…)` on a file holding no
  certificate raises `ssl.SSLError` `NO_CERTIFICATE_OR_CRL_FOUND`, and on a file missing
  `FileNotFoundError`. None of them carries the path or what the file holds.
- **An encrypted key.** `load_cert_chain` with no `password` makes OpenSSL ask for one: it wrote
  "Enter PEM pass phrase:" twice with no terminal and then raised `OSError` `Invalid argument`;
  with a terminal it waits for input, and uvicorn's load would ask again. A `password` callable
  is not called for a key that is not encrypted, and for one that is, what it raises propagates
  unchanged, so the core's check raises its own and names `FYLGJA_TLS_KEY`. An empty password
  instead raises `[SSL] PEM lib`, the same as a file that is no key.

---

## httpx 0.28.1, httpcore 1.0.9 and Python 3.14.4's `ssl`: a client's trust

Read from their source in the core's venv, with OpenSSL 3.5.5, and by a probe (a script outside
the tree) of a server on loopback serving `core/tests/tls.py`'s self-signed certificate, on the
development host; held by the pure tier's `core/tests/test_client.py`. *(2026-11-06)*

- **What httpx trusts.** `verify=True`, its default, is a context made from certifi's bundle
  (`certifi.where()`), or from `SSL_CERT_FILE` or `SSL_CERT_DIR` only where `trust_env` is set
  (`_config.py`, `create_ssl_context`); an `ssl.SSLContext` given as `verify` is used as it is.
  A client given a `transport` sends through it, and its `verify` is not read. So the core's
  client makes its trust itself: the CA file named, or `ssl.create_default_context()`, the
  system's.
- **A CA file it cannot use.** `ssl.create_default_context(cafile=…)` raises an `OSError` for
  each: `FileNotFoundError` for a file missing, `PermissionError` for one it may not read,
  `IsADirectoryError` for a directory, and `ssl.SSLError`, itself an `OSError`,
  `NO_CERTIFICATE_OR_CRL_FOUND` for a file of prose, of binary bytes or empty, and `[X509] PEM
  lib` for a certificate block cut short. None carries the path or what the file holds.
- **A certificate that fails verification** is `httpx.ConnectError`, on a request and on a
  stream's open alike, under the system's trust and certifi's. Its `__cause__` is
  `httpcore.ConnectError`, which httpcore's `map_exceptions` raises `from` the `ssl` error and
  its pool raises again `from None` (`_sync/connection_pool.py`, line 256): that clears its
  `__cause__`, and the `ssl.SSLCertVerificationError` is its `__context__` alone. The error's
  `verify_message` names the fault and holds neither the certificate nor a header: for the
  self-signed certificate under either trust, `self-signed certificate` (`verify_code` 18); with
  its CA trusted and the host named `localhost`, which the certificate does not hold, `Hostname
  mismatch, certificate is not valid for 'localhost'.` (62). `ssl` sets both attributes on the
  error it raises; one made by hand carries neither.

---

## The core's image

`make image` and `make imagecheck` on the development host, Docker 29.8.1 with buildx v0.37.1
(its `docker` driver), from the `Dockerfile` at the root. *(2026-11-06)*

- **The base.** `python:3.14.9-slim`, whose index `docker buildx imagetools inspect` read as
  `sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8`, each platform's
  manifest annotated `3.14.9-slim-trixie` and built 2026-10-21 on `debian:trixie-slim`. Inside
  the image `python --version` is 3.14.9, whose `pydoc_data/topics.py` was generated "as part of
  the release process" on 2026-10-21, 16 days before it was pinned. 3.14.10's, generated
  2026-10-25, was 12 days old, under the two weeks every pin keeps (CONTRIBUTING.md).
- **The image** is 284 MB on disk and 68 MB of content (`docker images --tree`), for
  linux/amd64. Its build context, `.dockerignore`'s allow-list, was 886.70 kB when first sent;
  BuildKit sends only what changed after.
- **The build** took 57.4 s cold, its base pulled and the wheel's dependencies fetched from PyPI
  (59.7 s on 3.14.10's base), and 0.8 s cached, each step `CACHED`.
- **As run** it is `uid=10001 gid=10001`, `HOME=/`. Given only `FYLGJA_STORE=/tmp/store` and
  `FYLGJA_TOKENS=/nonexistent`, it made its store under `/tmp`, owned by 10001, and exited 2 with
  one line on stderr, the token file's refusal. The venv, the packages and `/` are not writable
  to it.
- **What it installed**, `pip freeze --all` in its venv, so two builds of one commit can be
  compared. Only the core's own dependencies are pinned (`core/pyproject.toml`); the rest are
  resolved as it builds: anyio 4.16.0, attrs 26.1.0, certifi 2026.10.23, cffi 2.1.1, click 8.5.1,
  cryptography 50.0.2, dictdiffer 0.10.0, fylgja-core 0.0.0 (the wheel), grpcio 1.84.0, h11
  0.16.0, h2 4.4.1, hpack 4.2.0, httpcore 1.0.9, httpcore2 2.16.0, httpx 0.28.1, httpx2 2.16.0,
  hyperframe 6.1.0, idna 3.20, jsonschema 4.26.0, jsonschema-specifications 2025.9.1, lightkube
  1.0.1, lightkube-models 1.37.0.8, msgspec 0.22.0, pip 26.2.2, protobuf 7.36.2, pycparser 3.12,
  pygnmi 0.8.15, PyYAML 6.0.3, referencing 0.37.0, rpds-py 2026.9.1, starlette 1.9.0, truststore
  0.10.5, typing_extensions 4.16.0, uvicorn 0.54.0, wsproto 1.3.2.
- **The server is the container's PID 1, which ignores a signal it has no handler for.** In the
  image `python` as PID 1, its SIGTERM handler `SIG_DFL`, went on after
  `signal.raise_signal(SIGTERM)`. So the server installs its own: the console script's
  (`server/entry.py`) once the interpreter has started it, 0.14 to 0.16 s after the process
  starts in the image (the re-review's reading; a SIGTERM in that window is still dropped), then
  `main`'s (`server/__main__.py`).
  - uvicorn 0.54.0's `Server.capture_signals` replaces SIGINT's and SIGTERM's handlers by
    `signal.signal` while it serves, puts back the ones it found once `_serve` has returned, and
    then raises each signal it caught again, the last first (`server.py`, lines 332-349). Python
    3.14's `asyncio.Runner.run`, in the main thread with Python's own SIGINT handler, takes SIGINT
    by cancelling its task, then raises `KeyboardInterrupt` (`runners.py`, `_on_sigint`).
  - Serving, with a directory store under a tmpfs on `/tmp`, a token file and `FYLGJA_LISTEN` on
    loopback, the image of the commit before the server had its handler stopped gracefully on
    `docker kill --signal=TERM` and exited 0: uvicorn's raise again was ignored. With the handler
    the same run exited 143 0.71 s after the kill, `stopped by SIGTERM` its last line, no
    traceback.
  - **SIGTERM during the import of the server is taken by the console script.** The import of the
    server's modules takes 2.06 s inside the image, all of it before `main` runs. With `main`'s
    handler alone, SIGTERMs sent up to 1.9 s into a start were dropped and the start ran on. The
    console script, `fylgja-core-server`, now imports `signal` alone, installs a handler that exits
    143, and only then imports the server. Sent to the serving start above, SIGTERM at 0.3, 1.0
    and 1.9 s after `docker run -d` returned exited 143 within 0.28-0.50 s, nothing logged, three
    runs each; at 2.3 s `main`'s handler took it (143, `stopped by SIGTERM` its one line), and at
    3.0 s uvicorn's graceful stop (143). None hung.
  - **In a pod on the cluster a process may not signal itself** *(k3s v1.37.1+k3s1, containerd
    2.3.4-k3s1, 2026-11-07)*. A signal a process sends itself is refused: in an exec in the core's
    pod, `signal.raise_signal`, `os.kill(os.getpid(), …)` and `signal.pthread_kill` of its own
    thread each raised `PermissionError` 13, `EACCES`. The pod's processes run under the AppArmor
    label `cri-containerd.apparmor.d//&unconfined (enforce)`, the container's profile stacked;
    under Docker 29.8.1 on the development host the image's label is `docker-default (enforce)`,
    and `raise_signal` answered, with `--cap-drop ALL`, `--read-only` and `no-new-privileges` too.
    The stacked label is the likely cause; the refusal's cause was not read (the kernel's log of an
    AppArmor denial was not looked for). So uvicorn's raise again of the SIGTERM it caught, once it
    had stopped gracefully and released the Lease, raised out of `main`: the image
    `0be0fdbacebd`'s pod, deleted, exited 1 with a traceback, not 143. The server now takes that
    refusal, a `PermissionError`, as a raise that reached no handler (`_Server.capture_signals`),
    and exits by the signal it caught; any other `OSError` there is raised.
- **Its Python is not the development host's**, on which the facts above on Python 3.14.4's
  `asyncio` and `ssl` were read. Compared by their syntax trees, what the cut at a lost Lease rests
  on is the same in 3.14.9: `Server`'s `_attach` (its assert), `close`, `abort_clients` and
  `wait_closed`; the accept path (`_accept_connection`, `_accept_connection2`); and the
  transport's `__init__`, `abort`, `_force_close` and `_call_connection_lost`. 3.14.9 differs
  elsewhere, among it: `Server.serve_forever`, which uvicorn does not call, closes its clients
  when cancelled; and a socket transport's write path calls `_call_connection_lost` once at most.
  Its `sslproto.py` is 3.14.4's. The pure tier runs on the host's interpreter, so it holds none of
  this for the image.
  - **Read in a pod** *(k3s v1.37.1+k3s1, 2026-11-07)*. The image `fylgja-core:73c2f149ef62`, run
    as the pod `reading` (the block "From inside a pod, under the core's service account"), is
    Python 3.14.9, and its asyncio still holds the line the cut rests on: `Server._attach`'s
    `assert self._sockets is not None`, at `base_events.py` line 297, the line it holds in the
    host's 3.14.4.
- **Pushed, by CONTRIBUTING.md's recipe as written** *(crane 0.22.1, Docker 29.8.1, 2026-11-07)*.
  Its first run, the image `fylgja-core:73c2f149ef62` to the cluster's registry, `<registry>`:
  - `crane auth login` with `--password-stdin`, `DOCKER_CONFIG` a new directory and the registry's
    CA trusted by `SSL_CERT_FILE` alone, wrote `config.json` there at mode `0600` under a umask of
    `0002`: crane makes it so, and the recipe needs no `chmod`.
  - `docker save -o` wrote a tarball of 68 MB at mode `0600`, holding an OCI layout (`oci-layout`,
    `index.json`, `blobs/`) beside Docker's `manifest.json`. `crane push` sent it in 2.2 s, 8
    blobs, as a Docker v2 schema 2 manifest of 7 layers: linux/amd64, user `10001:10001`, entry
    point `fylgja-core-server`.
  - The kubelet pulled it by the pull secret `fylgja-registry`, a `kubernetes.io/dockerconfigjson`
    Secret made from a file, in 10.1 s, at the digest pushed.

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
- **A node made anew boots the kind's baseline, not what it was pushed.** On clabernetes, an SR
  Linux node's pod deleted and made again by its Deployment came back with `ethernet-1/1` holding
  `admin-state` `enable` alone, where the create had pushed a description and subinterface 0: in
  three readings of three, and once before them (k3s's section, "the conformance suite on the
  cluster"). *(clabernetes 0.10.1, k3s v1.37.1+k3s1, 2026-11-07)* On containerlab a node stopped
  and started by `stop --node` and `start --node` came back the same, in four runs (containerlab's
  section, the phase 6 blocks). *(0.81.0, 2026-11-07)* So a managed node holds nothing of its push
  after a replacement until a restore pushes it again ([D-067](decisions.md#d-067)), and an
  unmanaged one holds the kind's baseline, as [D-048](decisions.md#d-048) and
  [D-023](decisions.md#d-023) assume.

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
- **eAPI as the conformance suite's step scenarios read it**
  (`core/tests/conformance/test_steps.py`, one run on the local driver), each request
  `runCmds` of one command. *(0.81.0, 2026-11-07)*
  - **A show command about a port the node lacks is refused.** On `mixed`'s `e2`, after its
    create had ended, `show interfaces Ethernet10 status` (`format: "text"`) answered HTTP 200
    with an `error` whose `message` was `CLI command 1 of 1 'show interfaces Ethernet10
    status' failed: invalid command`, the shape of the refused command's above. Its `code` is
    `1002` and its `data` one `{"output": "% Interface does not exist\n", …}` entry (read by
    plan 7's final local run, 2026-11-07). The node's CLI through `docker exec` words the
    same refusal `% Interface does not exist at line 1` (containerlab, **EOS on a port the
    node lacks**).
  - **Once the port exists, the answer is the CLI's table as text**: a `result` of one
    `{"output": …}` entry, a header line (`Port`, `Name`, `Status`, `Vlan`, `Duplex`,
    `Speed`, `Type`, `Flags`, `Encapsulation`), then `Et10` `connected` `routed` `full` `1G`
    `EbraTestPhyPort`, the port by its short name. Both `e1` and `e2` answered so at the first
    ask after `mixed-e2-port`'s step had ended, each in about 0.1 s.
  - **`show lldp neighbors` with `format: "json"`** answered a `result` whose entry holds
    `lldpNeighbors`, one object a neighbour with `port` (the node's own port), `neighborDevice`,
    `neighborPort` and `ttl`. On `three-node-n3-eos`'s `n3` after the kind change it listed
    `Ethernet1` to `n2` on `ethernet-1/2` and `Ethernet2` to `n1` on `ethernet-1/2`, each `ttl`
    `120`, and nothing else, as `show lldp neighbors | json` through `docker exec` listed them
    in phase 5. The result's other members were not printed.
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
