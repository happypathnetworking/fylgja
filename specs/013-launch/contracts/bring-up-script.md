# Contract: `scripts/bring-up.sh`

The one script both consumers run: the setup of a fresh Ubuntu 26.04 host, and CI's
contract job (`--part infrahub`). Tooling beside `scripts/e2e.sh`; nothing Fylgja ships.

## Usage

```
scripts/bring-up.sh [--ceos-tar PATH] [--part NAME]... [--help]
```

Run from the repository root by the user who will run Fylgja (not root). `--part` is
repeatable and takes `toolchain`, `lab`, `infrahub` or `fylgja`; absent, all four run in
that order. `--after-groups` is internal: the lab part re-executes the script with it
through a fresh login session once it changed the user's groups (research R-02), and it is
refused on the command line.

## The preamble (changes nothing)

In order; the first refusal ends the run with exit `2`:

1. **The release**: `/etc/os-release` must carry `ID=ubuntu` and `VERSION_ID=26.04`.
   Otherwise `bring-up: REFUSED: this host is <PRETTY_NAME>; the script supports Ubuntu
   26.04 alone`.
2. **The flags**: an unknown flag, a `--part` name not in the four, or `--after-groups`.
3. **Privilege escalation**: `sudo -v`, the one prompt a run may make. The script then
   keeps the cached credential alive for the whole run, by a background loop that runs
   `sudo -n -v` each minute and is ended by the trap, because sudo's timestamp expires
   (15 minutes by default) sooner than the toolchain and lab parts take, and a second
   prompt would break SC-001. The re-executed run (`--after-groups`) starts its own loop
   and prompts for nothing.
4. **The cEOS tar**: looked for at `--ceos-tar PATH`, then `local/`, then the clone's
   parent directory, never the clone's root; the file is `cEOS-lab-4.32.0.2F.tar` or
   `cEOS-lab-4.32.0.2F.tar.xz`, the version taken from `psp/arista_eos.yaml`'s
   `image.ref`. A found file's sha256 is compared with the recorded
   `89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778`; a mismatch is
   `bring-up: REFUSED: <path>: sha256 <found> does not match the recorded <expected>;
   nothing was imported` and the run ends.
5. **Port 8000**: when something listens on 8000 that is not the Compose project
   `fylgja-infrahub`, `bring-up: REFUSED: port 8000 is held by <process or container>;
   stop it, or point INFRAHUB_ADDRESS at it and run with --part fylgja`.
6. **`local/.env`**: scaffolded from `.env.example` when absent, every name present and
   filled as [data-model.md §2](../data-model.md#2-localenv) says, mode `0600`; kept
   untouched when present.
7. **The first report** (below).

## The parts

Each item is *verify, install if missing, verify again*, printed as one line
`bring-up: <part>: <item>: present <version>` | `installed <version>` | `skipped (<why>)`.
A wait prints `bring-up: <part>: <item>: waiting for <what> (up to <N>s)` and on expiry
`bring-up: FAILED: <part>: <item>: <what> did not happen within <N>s[: <hint>]`, exit `1`.

**toolchain**: `make`, `git`, `curl`, `jq`, `xz-utils`, `file`; Ubuntu's `golang-go` (the
bootstrap `go` that fetches go1.26.0 through `go.mod`; verified by `go version` in the
clone); golangci-lint `v2.14.0` into `/usr/local/bin`; the Temporal CLI `1.9.1` into
`~/.temporalio/bin` and on the `PATH` of the processes the script starts; `gnmic`
`0.49.0`; `python3-venv`, then `.venv/` at the root with `infrahub-sdk[ctl]==1.23.2` and a
`.gitignore` of `*` inside it.

**lab**: Docker Engine (the release containerlab's installer pins for 26.04), the user in
`docker`; containerlab `0.79.0`, the user in `clab_admins`; the two AppArmor lines in
`/etc/apparmor.d/local/usr.sbin.rsyslogd` (and `/run/syslogd.pid* rw,`), reloaded with
`apparmor_parser -r`; `ghcr.io/nokia/srlinux:24.7.1` pulled; the cEOS import: `skipped
(ceos:4.32.0.2F present; its layer is the recorded tar's)` or `(… present; its layer is
not the recorded tar's)` when the reference exists, `installed ceos:4.32.0.2F (from
<path>)` when the tar was found, `skipped (no cEOS tar: SR Linux alone)` otherwise. When
this part added a group, the run re-executes once through `sudo -u "$USER" -i` and says
`bring-up: lab: groups: docker clab_admins added; continuing in a fresh login session`.

**infrahub**: `local/infrahub/docker-compose.yml` fetched from
`https://infrahub.opsmill.io/1.11.2` when absent; `docker-compose.override.yml` copied
from `scripts/infrahub/`; `docker compose --env-file local/.env up -d` (project
`fylgja-infrahub`); `infrahub-server` healthy and `GET /api/info` answering `1.11.2`
(up to 600 s); `go run -tags fixture ./cmd/fylgja-fixture -prepare-main`
([fixture-prepare-main.md](fixture-prepare-main.md)); the fixture: `present (fylgja-fixture,
3 artifacts Ready)`, or `installed` by `make infrahub-seed` (after `make infrahub-clean`
when the branch is incomplete; one retry on `graphql: None`). Needs `go` on the `PATH`,
and says so when it is missing (`run the toolchain part, or set up Go`).

**fylgja**: `make build` (static, checked with `file`); `make test` (tier 1); `make
test-contract` (tier 2); the dev server `temporal server start-dev --db-filename
local/temporal.db`, the worker and the API's server started detached from a shell that
loaded `local/.env`, each as `CLAUDE.md` starts them, logging under `local/`; each report
read: the dev server's health (`temporal operator cluster health`), the worker's and the
server's start-up reports naming both packages with their logins set (the packages the
host can run must appear). A process already running from this tree is `present`; one on
a `(deleted)` binary is restarted.

## The first report

```
bring-up: host: Ubuntu 26.04.1 LTS, kernel <uname -r>, <N> CPUs, <MiB> MiB, swap <MiB> MiB
bring-up: parts: toolchain lab infrahub fylgja
bring-up: cEOS tar: found <path> (sha256 matches 89a567d5…)
   or:    cEOS tar: not found; looked at --ceos-tar (<path> | none given), local/, <parent>/; the repository root is never searched
   or:    cEOS tar: not needed; ceos:4.32.0.2F is present
bring-up: platforms: nokia_srlinux arista_eos
   or:    platforms: nokia_srlinux (arista_eos needs the cEOS tar: docs/development.md says where to get it)
bring-up: memory: <MiB> MiB; tier 3 was proved with 32768 MiB       (a warning line under 24576)
```

## The last report

```
bring-up: did: <part>: <n> present, <n> installed, <n> skipped        (one line per part run)
bring-up: cEOS tar: <as the first report>
bring-up: platforms: <as the first report>
bring-up: tier 1: passed (<s>s)
bring-up: tier 2: passed (<s>s)
bring-up: tier 3: not run; make test-e2e runs it (about 17–19 minutes; needs both images, or PLATFORMS=nokia_srlinux)
bring-up: running: temporal (pid <n>, local/temporal.log)
bring-up: running: worker (pid <n>, local/worker.log; packages nokia_srlinux arista_eos)
bring-up: running: server (pid <n>, local/server.log, 127.0.0.1:7650; packages nokia_srlinux arista_eos)
bring-up: to stop them: pkill -x fylgja; pkill -f 'temporal server start-dev'
bring-up: DONE in <s>s
```

With `--part`, the lines of parts not run are absent. On a second run every part's
line reads `present`, `installed 0`, and the tiers run again.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | every part run completed; the tiers run passed; the last report printed |
| `1` | a part's item failed, or a tier failed (the output names it) |
| `2` | refused in the preamble, before any change: the release, a flag, the tar's checksum, port 8000 |

## Hygiene

The script never prints, logs or passes as an argument any value of `local/.env`:
Infrahub's token goes to `curl` as a header file (as `e2e.sh`'s `gql` does), the Compose
values go through `--env-file`, and `set -x` is never used. Every file it writes but
`local/.env` carries no token and no password, and its output can be committed to a CI
log. It writes under `local/`, `.venv/`, `bin/`, `/usr/local/bin`, `~/.temporalio`,
`/etc/apparmor.d/local/` and the package manager's own paths, and nowhere else in the
clone.
