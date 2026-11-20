# The demonstrations

A demonstration rehearses a change of a source of truth on a twin, from nothing running. There is
one for each source the example rehearses a change of: Infrahub and NetBox. Each starts the source, seeds it with a
network, starts the core and the example orchestrator, makes a change in the source, waits for the
twin to rehearse it and says the verdict and where the report is read.

A demonstration is a development tool, run from a clone of the repository. It is not installed, and
what it does is not promised the way the commands in [the command line](cli.md) are. The example
orchestrator it uses is described in [integrating Fylgja](integrating.md).

## What the host must have

A demonstration checks these before it starts, says each one that is not met in a line of its own,
and changes nothing until all are met. Only the host's owner can give them.

`make demo-dependencies` gives the host what it can of them, using sudo for each change and
nothing where all is present: git, `ss` and curl, uv, Docker with its Compose plugin and
containerlab, the two groups and the AppArmor widening. It checks Python, the node login and the
memory and says what is left to do by hand. `make demo-dependencies DRY_RUN=1` prints what it
would run instead.

- **A Linux host with Python 3.14, uv 0.12.23, GNU make, git, `ss` and the network.** The script
  looks for `docker`, `containerlab`, `git`, `make` and `ss` on `PATH` and says `<name> is not on
  PATH` for each it does not find. It does not check the versions of Python and uv, or the network:
  `make venv` needs Python 3.14 and uv 0.12.23, and a fetch, a build and an image pull need the
  network.
- **The venv, `core/.venv`.** Without its commands the script says `<checkout>/core/.venv lacks
  <commands>: run make venv`. Through make the target runs `make venv` first where the venv lacks
  the server command.
- **Docker with its Compose plugin, and containerlab,** each answering: a Docker daemon that answers
  this user (`docker info`), `docker compose version` and `containerlab version`. A command that
  fails is said by its name and its exit status.
- **The user in the groups `docker` and `clab_admins`, in a login begun after they were added.** A
  group added reaches no process begun before it, so log in again. The script says `this process is
  not in the group <group>: add the user to it and log in again`, or `the host has no group
  <group>`. Root is asked for neither.
- **On Ubuntu, the AppArmor widening.** SR Linux's `rsyslogd` needs two lines, `/opt/srlinux/** mr,`
  and `/run/srlinux/** rw,`, in `/etc/apparmor.d/local/usr.sbin.rsyslogd`, and the profile reloaded
  with `apparmor_parser -r /etc/apparmor.d/usr.sbin.rsyslogd`. The script reads the local file. It
  cannot read the loaded profile, which AppArmor does not show a user, so it cannot check that you
  reloaded it. Where the local file lacks the lines it says so, and that SR Linux's `rsyslogd` needs
  them on Ubuntu. Where the local file is not yours to read, it says `cannot read <the file>: check
  that it holds <the two lines>` and the run goes on. Where `/etc/apparmor.d/usr.sbin.rsyslogd` is
  no file, nothing is asked.
- **Memory available** (`MemAvailable`): 11776 MiB for Infrahub's demonstration and 8704 MiB for
  NetBox's, with the source stopped. With the source already up it is 7168 MiB, the twin's and the
  edge's. The source's own stack adds 4608 MiB for Infrahub and 1536 MiB for NetBox where it is not
  up. Where memory is short the script says `<have> MiB of memory is available and the <source>
  demonstration needs <need>`. The memory is judged after what an earlier run left is ended and the
  other source is stopped.
- **The ports free.** A listener at the port on any address counts. The ports are 7650, the core's
  (`127.0.0.1:7650` or the address in `FYLGJA_LISTEN`); 4200, the edge's Prefect, unless the Prefect
  server that `local/prefect/server.pid` names is up, which is the one case in which `make
  prefect-up` starts none; and 8000 for Infrahub or 8800 for NetBox, unless that source is up. A
  busy port is said as `port <port> is listened on at <address> by a process the demonstration did
  not start`. Where `FYLGJA_LISTEN` is set, it must be `127.0.0.1:<port>`, since the demonstration's
  core serves HTTP on loopback. Infrahub's Compose file also publishes 15692, 2004 and 6362, which
  are not checked: Infrahub's own start refuses them.
- **`local/.env`, mode `0600`, with the node login's two lines,**
  `FYLGJA_CREDENTIAL_SRLINUX_USERNAME` and `FYLGJA_CREDENTIAL_SRLINUX_PASSWORD`. The image's
  published default login is enough. The script says `<the file> is not there` or `local/.env gives
  <names> no value`. It checks that both have a value, not the file's mode.
- **For Infrahub, a branch checked out with its work committed, or `REF=<branch>`.** Infrahub
  registers the branch's last commit and runs its checks from that. The script says `no branch is
  checked out and REF names none`, or `REF names <ref>, which is no commit of this repository`.
- **The twin's images,** `ghcr.io/nokia/srlinux:24.7.1` and `alpine:3.24.2`. The script pulls them
  where Docker holds none, which needs the network.
- **A lab pool no Docker network holds whole.** Where one does, set `FYLGJA_LAB_POOL` in
  `local/.env` to an IPv4 network in CIDR form that holds a /24. The script reads Docker's networks
  once the source is up, since a source's own network may take the pool, and stops there, with the
  source left up, where they leave the pool no /24 free. It says `The pool <pool> has no /24 that
  neither a Docker network nor another twin holds.`, names the Docker networks that hold part of it,
  and ends `Set FYLGJA_LAB_POOL to an IPv4 network with a free /24, and start the core again.`, then
  `<source> is left up: set FYLGJA_LAB_POOL in local/.env, then run make <source>-demo again`. A
  value that is no such network is refused with `FYLGJA_LAB_POOL is not an IPv4 network in CIDR form
  that holds a /24`.

A `local/` that is a symbolic link is not supported for the edge's Prefect: where Prefect was started by
hand under the link's spelling, the demonstration's `prefect-up` step does not see that server as up.

Where a read of the host fails, the line says what was not judged. Where `docker info` fails, the
run stops with the checks above and judges neither memory nor ports.

## Running one

Run a target from the clone's root.

| Target | What it does |
|---|---|
| `make infrahub-demo` | Infrahub's demonstration. The repository is registered in Infrahub at `REF`, the branch checked out where `REF` is not given. |
| `make netbox-demo` | NetBox's demonstration. |
| `make demo-down` | Ends what a demonstration started. The source's volumes are kept; `make demo-down PURGE=1` removes them. |

```sh
make netbox-demo
make demo-down
make infrahub-demo REF=my-branch
make demo-down
```

`PURGE=1` counts only on the make command line of `make demo-down`. A `PURGE` in the shell, in
`local/.env` or on a demonstration's own command line removes no volume. In the same way a make
variable you set is not passed on to the targets a demonstration runs: each runs at the `Makefile`'s
own value, and the demonstration says once which names it did not pass on, never a value. `LOCAL`,
and for Infrahub `REF`, are passed on.

A demonstration takes these steps, in this order:

1. It takes the lock `local/demo/lock`, and reads `local/.env` as a shell reads its lines. A line it
   does not read so, a value holding `$`, a backquote or a backslash outside single quotes among
   them, is refused, naming the variable and the line and never the value.
2. It refuses to run beside a runner it did not start (see below), and checks the host as above.
3. It ends what an earlier run left: its runner, its core and every twin its store holds.
4. It stops the other source where that is up, its volumes kept, since either source starts the same
   two deployments.
5. It judges the host's memory and ports, and says `the host's checks passed`.
6. It makes `local/demo/` and the token file, adds the two lines to `local/.env`, and pulls the
   images.
7. It takes the source's steps, each said as `step <n> of <m>`, through the repository's own
   targets:
   - Infrahub: `make infrahub-up`, `make orchestrator-env`, the core, `make infrahub-up` again,
     `make infrahub-register REF=<branch>`, `make prefect-up`, the runner and `make infrahub-seed
     PROPOSED_CHANGE=1`, which opens the proposed change `Rehearse third-link`.
   - NetBox: `make netbox-up`, `make netbox-seed`, `make orchestrator-env SOURCE=netbox`, the core,
     `make prefect-up`, the runner, `make netbox-hook` and `make netbox-change NETBOX_TAG=1`, which
     sets the tag on the branch `third-link`.
8. It waits for the flow run of `twin-rehearse/main` that the change started on the edge's Prefect,
   reads the document the run filed, keeps it, and says the verdict.

A step that fails stops the run, with `step <n>, make <target>, exited <status>`. From step 3 on,
every way out says last what is left up and that `make demo-down` ends it.

The report is read in the source. In Infrahub it is the proposed change's thread `Fylgja rehearsal`.
In NetBox it is the newest entry of the branch's Journal tab. Sign in as admin, with the password
`local/.env` holds as `INFRAHUB_INITIAL_ADMIN_PASSWORD` or `FYLGJA_NETBOX_SUPERUSER_PASSWORD`; the
demonstration never prints it.

### How long it takes

Each was read once, on the local driver, with the source's volumes kept.

- `make netbox-demo` from NetBox stopped took about 5.5 minutes, and about 3 minutes run again at
  once.
- `make infrahub-demo` from Infrahub stopped took about 25.6 minutes, and about 15.7 minutes run
  again at once. Registering the repository in Infrahub is the longest of the steps; the wait for
  the rehearsal's run that follows is longer, and the registration's first ask can run out its time
  and pass on the second.
- `make demo-down` took about 15 to 25 seconds.

From new volumes, in a fresh clone, each demonstration took about 17 minutes of wall time, in three
runs on the local driver, two of NetBox's and one of Infrahub's. NetBox's first start is most of
NetBox's demonstration's time: NetBox was healthy about 730 to 790 seconds after its start, in four
readings of 732 to 793 seconds. Infrahub answered about 155 seconds after Compose's start, in five
readings of 153 to 159 seconds.

Why it is so: the readings are in [verified-facts.md](../design/verified-facts.md).

## What it writes

Under `local/demo/`, mode `0700`, never printed:

- `source`, the word of the last `up` that passed its checks, which `make demo-down` keeps;
- `core.pid` and `runner.pid`, and `prefect.pid` only where the demonstration started the Prefect
  server;
- `core.log` and `runner.log`, each start's own, the one before kept as `<name>.1`;
- `store/`, the core's store;
- `unsettled`, empty, which is removed only once a core of the demonstration's own has listed no
  twin;
- `tokens`, mode `0600`, the core's token file, holding the client's token's hash under the
  principal `demo` and the runner's under `orchestrator`;
- `lock`; and `rehearsal.json`, mode `0600`, the last document read, as Prefect gave it.

Into `local/.env` it appends, where the loaded environment, the shell's and the file's, gives the
name no value, two lines: `FYLGJA_API_ADDRESS`, the core's listen address, and `FYLGJA_API_TOKEN`, a
client's token made anew. It keeps every byte already there and says the names, never the values.
The targets it runs write their own lines.

The demonstration's core never reads `FYLGJA_TOKENS` or `FYLGJA_STORE` from `local/.env`. It is
given `local/demo/tokens` and `local/demo/store`, so every twin its core lists is the
demonstration's.

## Exit statuses

The demonstration script exits 0 where the rehearsal passed, and for `make demo-down` where
everything it had to end is ended. It exits 1 for any other verdict, no document, a step that failed
or a wait that ran out, and for a `make demo-down` that did not end everything, which says `down:
not everything was ended: read the lines above, then run make demo-down again`, 2 for a command line
it does not understand, a precondition not met or a refusal, and 130 for Ctrl-C. Each but the passed
verdict is said on stderr.

Run through make, a failing recipe is make's own status 2 for every one of these, and the script's
status shows in make's last line, `make: *** [Makefile:<line>: <target>] Error <status>`. The
demonstrations are a development tool: read the lines they print, and do not script against these
statuses.

## A second run, and the two never at once

A demonstration run again first ends what the one before left, then takes every step again. The
change is built anew by its own target: `make infrahub-seed` removes the earlier seed's open
proposed change and makes the branch and a new one, and `make netbox-change` deletes the branch, its
journal with it, and builds it again. The run it waits for is one Prefect did not list before the
last step, so a run of an earlier change is never taken for it.

The two demonstrations never run together, and a refusal names what to do:

- One demonstration command runs at a time. A second one, `make demo-down` among them, while one
  holds `local/demo/lock` says `another demonstration command holds <local>/demo/lock: one runs at a
  time`.
- With one demonstration's runner up, the other is refused, nothing started or stopped: `the
  <source> demonstration's runner is up, pid <pid>: one Prefect serves one source's runner; run
  make demo-down first`.
- A runner that serves `local/prefect/` and that the demonstration did not start, one of `make
  orchestrator-serve` among them, is refused the same way, with its pid. Stop it by its pid.
- The other source up with no demonstration's runner is not refused. It is stopped, its volumes
  kept.

## Ending it

`make demo-down` ends, in order, the runner and the core by their recorded pids, every twin the
store holds, the Prefect server where the demonstration started it, and the source, its volumes
kept. It ends by saying everything is ended. Where something failed it names what, and ends `down:
not everything was ended: read the lines above, then run make demo-down again`.

What stays: `local/demo/`, `local/.env`, the source's containers, stopped, and its volumes, and the
change in the source: the proposed change open in Infrahub, or the branch with its marks and its
report in NetBox. A Prefect server that was up before the demonstration is left running.

A second `make demo-down`, with nothing left running and the source's containers not up, says
`nothing the <source> demonstration started is running, and <source> is not up: nothing to end; its
records stay under <local>/demo`, and ends. Where the source's containers are up again, it stops
them as the first did. With nothing recorded under `local/demo/` it says `no demonstration is
recorded under <local>/demo: nothing to end`.

A Ctrl-C while a demonstration or `make demo-down` runs says that it was interrupted and what is
left up. `make demo-down` is what ends what the run started.
