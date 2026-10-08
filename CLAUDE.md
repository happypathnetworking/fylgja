# Fylgja — working notes for Claude

A walking twin of network intent: Infrahub branch (+ optional point in time) → pure
compiler → deployable bundle → one containerlab twin, provisioned through Temporal.
One twin at a time. No database. Every command is a request to the API's server,
`fylgja serve`, on the lab host.

Read in this order, then the current feature under `specs/`:
`docs/brief.md` (what we are building) · `docs/architecture.md` · `docs/decisions.md`
(rejected alternatives live here — check before proposing one) · `docs/roadmap.md`
(what is built, the launch, the order after it) · `docs/development.md` (conventions).
Terms are in `docs/glossary.md`. What has been verified about a dependency is in
`docs/verified-facts.md`, read when a task touches that dependency. The constitution at
`.specify/memory/constitution.md` (1.1.1) binds every plan's Constitution Check.

This repository began with one commit, M14's cut ([D-043](docs/decisions.md#d-043)). The
record of how M1–M13 were built (their specs, research logs and command logs) is private
and is not cited here; a bare milestone marker (`M7`) is resolved by the table below.

## Workflow

- **Spec Kit**: `/speckit-specify` → `clarify` → `plan` → `tasks` → `analyze` →
  `implement` → `converge` (repeat until nothing is added). **Each command runs in a
  fresh context** (`/clear`, `/model` per the table in `docs/development.md`, then the
  command), **except `clarify`, which runs in `specify`'s context**. Every command reads
  its inputs from disk. A feature's `brief.md` carries its full reading list, so the
  specify prompt is one line. `.specify/feature.json` (git-ignored) names the current
  feature's directory.
- **Commands are logged automatically** by the Claude Code hooks in `.claude/settings.json`
  (`.claude/hooks/command-log.py`): prompt, report, model, effort, time, context and
  tokens, kept in `local/command-log/pending.jsonl` so no turn dirties the tree.
  `make command-log` publishes them into `commands/` or `specs/NNN-slug/commands/`, which
  are **git-ignored here**: it commits nothing. Run it after a hand session, once the
  session is closed or cleared. Do not write the log files by hand. The loop's stopping
  rule reads `tasks.md`'s tags, never the log.
- **Commit manually** with a conventional-commit message whose body says *why*. Never
  commit `local/`. The one exception is `scripts/converge-loop.sh`, which commits as it
  goes and never pushes (`docs/development.md`, "The converge loop"). Its sessions get
  Infrahub's address and token from `local/.env` and run tier 2, never the node logins;
  tier 3, twins, the worker and the hand scenarios stay the operator's. Boot no twin while
  it runs. **Attended** (`/converge-loop`; "The attended loop"), its live sessions get the
  logins and run tier 3, the worker and the hand scenarios, and what would stop it is a
  question put to the operator by the session that started it; that session writes the
  answer into the tree only while the loop says it is paused.
- **A session never pushes.** `origin` is pushed by the operator; a moved remote-tracking
  ref stops the converge loop at `contract`.
- **A changed decision** is a new entry in `docs/decisions.md` that supersedes the old one
  (append-only; the log begins at this repository's first commit), then grep
  `docs/architecture.md` for the old position. The constitution is amended only by citing
  an entry, with a version bump.
- **Verify against the running system** before asserting how Infrahub, containerlab, a
  network operating system or Temporal behaves; record the result in the feature's
  `research.md` and, once it holds, in `docs/verified-facts.md`.
- **A changed package, import or component is redrawn** in the same change: edit
  `docs/c4/workspace.dsl` beside the prose it illustrates, then `make diagrams`.
- **The OpsMill `infrahub-*` skills** (installed in the user's Claude Code skills, not in
  this repository) are loaded, not left to chance: when a feature designs or changes
  something in Infrahub — a schema kind, object files, a transform, a check — `plan`
  loads the matching skill before writing `data-model.md` or `research.md`, and
  `specify` does when it names a new kind. Most often `infrahub-managing-schemas`, then
  `-objects`, `-transforms`, `-checks`. Apply their rules; do not obey them where a
  decision already differs: Fylgja's schema loads on `main` on purpose
  ([D-028](docs/decisions.md#d-028)), against `workflow-branch-first`. They do not replace
  verifying against the running 1.11.2.

## Environment

**The development host** is one machine: Ubuntu 26.04.1 LTS, kernel 7.0, under QEMU/KVM,
10 vCPUs, 32 GiB, 8 GiB swap, set up by `scripts/bring-up.sh` from this clone. It is the
only lab host until M9. Ubuntu 26.04 is the one release the script supports; the host ran
24.04.1 until the launch, and `docs/verified-facts.md` marks each fact re-verified on 26.04.

- **Credentials**: `local/.env` (git-ignored, mode `0600`, scaffolded by the bring-up
  script) holds `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`, both node logins — the SR Linux
  probe and push login `FYLGJA_SRLINUX_USERNAME`/`_PASSWORD` and the EOS one
  `FYLGJA_EOS_USERNAME`/`_PASSWORD`, each the image's default, as `scripts/e2e.sh` sets
  them — and `FYLGJA_API_TOKEN`, the API's token, which the server and every client's
  command share and the worker never reads ([D-042](docs/decisions.md#d-042)). It also
  holds Infrahub's Compose values, which Compose reads and Fylgja never does:
  `COMPOSE_PROJECT_NAME`, `INFRAHUB_INITIAL_ADMIN_TOKEN` (equal to `INFRAHUB_API_TOKEN`),
  `INFRAHUB_INITIAL_ADMIN_PASSWORD`, `INFRAHUB_INITIAL_AGENT_TOKEN` and
  `INFRAHUB_SECURITY_SECRET_KEY`. Never re-make it: Infrahub's volumes hold the admin
  token it carries. Both login names are their package's data, not code. Load with
  `set -a; . local/.env; set +a`. Fylgja reads the process environment only, never a
  file; `local/.env` is the only file that holds a value, and `.env.example` documents
  the names. **Never echo, log, or persist a token, a password or the secret key.**
- **Infrahub 1.11.2** runs as the Docker Compose project `fylgja-infrahub`, the host's one,
  from `local/infrahub/` (git-ignored): Infrahub's published Compose file, fetched by
  version from `https://infrahub.opsmill.io/1.11.2`, and this repository's
  `scripts/infrahub/docker-compose.override.yml` copied beside it; at
  http://localhost:8000. The override pins the three Infrahub services to `1.11.2`, since a
  stray `VERSION` would move them, and caps Neo4j at heap 1g/2g and page cache 1g. Run
  Compose from the repository root as the script does: `docker compose -p fylgja-infrahub
  --env-file local/.env -f local/infrahub/docker-compose.yml -f
  local/infrahub/docker-compose.override.yml <command>`. Volumes persist across `down`.
- **Infrahub's `main`** carries the Fylgja schema (`NetworkDevice` inherits
  `CoreArtifactTarget`; the waypoint kind `FylgjaWaypoint`, branch-agnostic, attribute
  `as_of`), hash `0aba31a5…` on this install (a branch's hash covers its whole schema, so
  each install has its own; the 24.04 install's was `4d5b37aa…`); the empty group
  `fylgja-devices`; and the registration `fylgja`, a `CoreReadOnlyRepository` at
  `https://github.com/happypathnetworking/fylgja.git`, `ref main`, with no credential
  ([D-044](docs/decisions.md#d-044)), whose import made the query `device_config`, the
  transform `srlinux_device_config` and the definition `srlinux_device_config` → artifact
  `device-config`, `text/plain`. `fylgja-fixture -prepare-main` loaded the schema, made
  the group and registered the repository, each only when absent. No credential is
  registered. **One template renders both platforms**: it branches on the device's
  platform. **A template change reaches Infrahub
  only when asked**: once it is on `origin`'s `main`, which the operator pushes,
  `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main` imports it (neither
  the minute sync nor rewriting `ref` does); a branch then sees it only after
  `BranchRebase` or re-creation, and each artifact only once generated again. `make sdl`
  fetches the SDL from `main`. Prefect's `git_repositories_sync` runs every minute with
  one concurrency slot, so a run stuck `PENDING` blocks every import until it is
  cancelled.
- **The fixture branch `fylgja-fixture`**: the four Fylgja generics plus the reference
  schema, 3 devices, 12 interfaces, 3 links, contract `0.2`; the devices are in group
  `fylgja-devices`, each with one `device-config` artifact, `Ready`. It has the same
  schema hash as `main`. It compiles to **`47b2c449…`** on this install; its CTM equals
  `testdata/ctm/three-node.json` in everything but the envelope, and with the 24.04
  install's hash `4d5b37aa…` in place of this one's it compiles to `b9d53ebc…`, the id the
  cut recorded. It is written by its seed (`make infrahub-seed`, which the bring-up
  script runs when the branch is absent) and by no test. Contract tests make their own
  throwaway `fylgja-test-*` branches and `fylgja-test-*` waypoint series, deleted by the
  test that wrote them. `fylgja-fixture` has no series, and the fixture tool refuses to
  write one naming it.
- **Waypoints** are the operator's to write, by object file (`kind: Object`, the node kind
  under `spec.kind`), the UI or `.venv/bin/infrahubctl object create`; the guide is
  `schema/README.md`. After the contract tier, `FylgjaWaypoint { count }` reads 0.
- **containerlab 0.79.0** (its `.deb`; `/usr/bin/containerlab` setuid root) and **Docker
  29.8.1** with Compose 5.6.0, from Docker's repository. The user is in `clab_admins` and
  `docker`: `clab` runs without sudo. A shell begun before the bring-up script added the
  groups lacks them until the next login (read `id -nG`): run Docker, containerlab, the
  worker, the server and tier 3 from one under `sg docker`, which is all containerlab
  needs. **No `/dev/kvm`**: the host does not nest, which only a `vrnetlab_vm` package
  would need. `gnmic` 0.49.0 is installed (`/usr/local/bin`) as a hand tool.
- **The images.** SR Linux `ghcr.io/nokia/srlinux:24.7.1`, pulled. cEOS `4.32.0.2F`,
  imported by the bring-up script from the account-gated tar `cEOS-lab-4.32.0.2F.tar`
  (xz-compressed despite its name; sha256 `89a567d5…`, the script's recorded value), which
  sits in the clone's parent directory: the script looks at `--ceos-tar`, `local/` and
  there, never in the clone's root, from which the loop commits. `ceos:4.32.0.2F` has one
  layer, `sha256:09ab9635…`, the decompressed tar's sha256, and no `Cmd`, as `docker
  import` leaves it; each import gets a new image id. **cEOS is never pulled**: its
  package says `acquisition: account_gated`, so the host check verifies presence under
  exactly that reference and refuses the run when it is absent — the same image under
  another tag is absent.
- **The host's AppArmor must allow SR Linux's `rsyslogd`.** Ubuntu's
  `/etc/apparmor.d/usr.sbin.rsyslogd` attaches to the `rsyslogd` inside every privileged
  SR Linux container; unwidened, every `nokia_srlinux` deploy fails at containerlab's
  post-deploy commit (`Applications have failed: log_mgr`).
  `/etc/apparmor.d/local/usr.sbin.rsyslogd` carries `/opt/srlinux/** mr,`,
  `/run/srlinux/** rw,` and `/run/syslogd.pid* rw,`, which the bring-up script's lab part
  writes and reloads with `apparmor_parser -r`. The kernel log's `net_admin` denials of
  SR Linux's `rsyslogd` are harmless: every deploy passes.
- **Go**: Ubuntu 26.04's `golang-go` is go1.26.0, the release `go.mod` names, so nothing
  is fetched. The module is `github.com/happypathnetworking/fylgja`.
- **golangci-lint 2.14.0** (`/usr/local/bin`; the v2 line — `.golangci.yml` declares
  `version: "2"`, which v1 rejects). **ShellCheck 0.11.0**, 26.04's package: CI's lint job
  runs it over `scripts/bring-up.sh` and `scripts/e2e.sh`.
- **Temporal CLI 1.9.1** (Server 1.32.0) at `~/.temporalio/bin/temporal`, where its
  installer puts it and which no login shell's `PATH` names: `make temporal-dev` and
  `scripts/e2e.sh` look there when the `PATH` has none. The dev server is `temporal server
  start-dev --db-filename local/temporal.db` on `:7233`, UI `:8233` (`make temporal-dev`).
  Start it detached, as the worker is, logging to `local/temporal.log`, and restart it if
  it is down.
- **Python**: `.venv` at the repository root (Python 3.14.4, `python3.14-venv`) holds
  `infrahub-sdk[ctl]` 1.23.2, which connects as Admin. The repository does not ignore
  `.venv`; a `.gitignore` of `*` inside it keeps the tree clean, so a new venv needs one
  too.
- **sudo** is sudo-rs 0.2.13, and a session cannot answer its prompt (`sudo -n` asks for
  a password): a step that needs root is the operator's.
- **Git**: this clone's `user.name`/`user.email` are set in its own config, as the
  history's author.
- **Memory**: 32 GiB leaves tier 3 room. Still read `free -m` before tier 3. Infrahub
  idles at about 5.2 GiB, leaving about 24 GiB available with the three processes running,
  and its Neo4j is capped (above) because uncapped it once took the headroom a twin needs
  and killed a tier-3 run. Do not boot a twin while the contract tier runs, and rest the
  host between tier-3 runs.

**The worker is yours to run.** Start, stop and restart `fylgja worker run` yourself
whenever you need to — after every rebuild, before any live run, and whenever its binary
reads `(deleted)`. Do not leave it for the operator and do not ask. Start it detached so
it outlives the session, from a shell that has loaded `local/.env`, at the repository
root:

```
set -a; . local/.env; set +a; setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja worker run >> local/worker.log 2>&1 < /dev/null &
```

Then verify what you started, never assume it: `/proc/<pid>/exe` is not `(deleted)`, the
environment names carry `INFRAHUB_*` and both logins, and the start-up report names both
packages. A rebuild does not always replace the binary, so read `/proc/<pid>/exe` rather
than assuming either way. The worker serves four workflows (provision, destroy, the
following check and step) and twenty activities; a worker on an older binary than the
tree may lack one and fail a run at it. The start-up report names
packages, never workflows or activities. A stopped worker lingers as a poller for about
five minutes — harmless, and not a second worker. The dev server is the same: restart it
if it is down.

**The API's server is yours to run, as the worker is.** Every command but `worker run`
and `serve` itself is a request to `fylgja serve` ([D-040](docs/decisions.md#d-040),
[D-041](docs/decisions.md#d-041)); `--version` and `--help` alone need no server. Start,
stop and restart it yourself on the same occasions, detached, from a shell that has loaded
`local/.env` (which carries `FYLGJA_API_TOKEN`; without it the server refuses to start):

```
set -a; . local/.env; set +a; setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja serve >> local/server.log 2>&1 < /dev/null &
```

Then verify it: `/proc/<pid>/exe` is not `(deleted)`; its environment carries
`INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`; and its report
(`local/server.log`) says `listening on 127.0.0.1:7650 (API version 1, build …)` and names
both packages with their logins set. **Find both with `pgrep -x fylgja`** (`pgrep -f` also
matches the shell that runs it) and tell them apart by `/proc/<pid>/cmdline`. The server
dials nothing at start and keeps nothing between two requests, so a restart loses nothing
but the answers it was sending, whose runs go on. It logs one line a request to
`local/server.log`, never a token. `docker` and `containerlab` must be on the `PATH` of
both the worker and the server, which makes every dry run; a client needs neither.

**A client** needs `FYLGJA_API_TOKEN`, and `FYLGJA_API_ADDRESS` when the server is off
`127.0.0.1:7650`, and nothing else: run a client's command from a shell that holds the
token alone, or with `local/.env` loaded, which it ignores but for the token. A client on
another machine comes through `ssh -N -L 7650:127.0.0.1:7650 <lab host>`, with a binary
built from this tree.

**Formats**: bundle `4` (a bundle of another format is refused), CTM `1`, PSP `0.6`
(both shipped packages on `mode: replace`), `twin.json` `5`, contract `0.2`, findings `1`,
the API `1` (`contracts/api.md`, the version in every path). The three goldens are
three-node **`23f86a26…`**, lossy **`5773b6bb…`** and mixed **`391bcb96…`**, and the live
fixture compiles to `47b2c449…` on this install (`b9d53ebc…` under the 24.04 install's
schema hash). The current contracts are in `contracts/`; a test of an
older format reads a frozen copy under its package's `testdata/contracts/`.

## Verified facts a session acts on (trust these over recollection)

Each is in `docs/verified-facts.md` with the version and date it was verified; the rest
of what has been verified — the SR Linux and cEOS nodes' paths and answers, the push and
the replace, containerlab's reconcile, the waypoint kind, verify's reads — is there too.
Re-verify on any upgrade.

- **Infrahub filters `created_at <= at`**: send no `at` unless the operator supplied one.
  A pinned `at` carries at most six fractional digits.
- **GraphQL takes the branch in the path**, `POST /graphql/<branch>`; a `?branch=`
  parameter there is ignored and answers for `main` with no error.
- **The schema.** `POST /api/schema/load` rebuilds the branch schema asynchronously: poll
  before seeding. Check candidates with `POST /api/schema/check`. Attribute names `class`
  and `type` are rejected, a name is 3–64 characters of `[a-z0-9_]`, a description ≤128
  characters; strict mode is on. On a branch without the Fylgja schema the generics are
  not GraphQL types: read `GET /api/schema` first (`used_by` is the conformance check).
  The SDL is at `GET /schema.graphql?branch=`, and its field order is not stable between
  two fetches: compare SDLs structurally.
- **Infrahub regenerates no artifact on its own**: not on a data change, a group join or
  a commit import. Generate with `POST /api/artifact/generate/<definition id>?branch=`,
  then wait for the checksum to move; a regeneration to identical bytes writes nothing.
  `CoreArtifact.checksum` is the MD5 of the stored bytes.
- **A `BranchCreate` straight after a `BranchDelete`** of the same name can fail with
  `graphql: None`; run it again.
- **containerlab**: decode `absLabPath` from `inspect --all --format json`, never
  `labPath`. `clab deploy --dry-run --format json` is a plan, and must run with
  `CLAB_LABDIR_BASE` at the twin directory. `/usr/bin/containerlab` is setuid root, so a
  `clab` outlives a worker killed with `kill -9`.
- **gNMI**: set the encoding (`json_ietf`), or SR Linux answers `Unimplemented`. SR
  Linux's gNMI is TLS on 57400 in the management namespace, probed at the node's
  management address; cEOS's is plaintext on 6030. cEOS refuses a gNMI Set: shut a port
  through its CLI (`docker exec clab-fylgja-<node> Cli -p 15 -c 'configure / interface
  Ethernet1 / shutdown'`).
- **The SR Linux push**: a refused line stays in the login's private candidate across
  requests, and the replace's `load startup` clears it. A refusal's message is cut at
  about 1 KiB.
- **Temporal Go SDK v1.49 abandons an activity attempt at the first heartbeat call that
  fails**, not after `HeartbeatTimeout`; a call fails once unanswered for about half of
  `MaxHeartbeatThrottleInterval`. `context.Cause(ctx)` is a `*temporal.CanceledError` for
  a cancellation the workflow asked for, and the RPC's error for a lost heartbeat.
- **No twin while tier 2 runs**: the host starves, deploys lose their heartbeats, and
  Infrahub times out the tier.

## Milestones

M1 — Read and compile: the intent reader, the CTM and the pure compiler to a content-addressed bundle.
M2 — Provision and destroy: the provision and destroy workflows, the worker, the containerlab driver, readiness; one SR Linux twin.
M3 — Operate: refusal while a twin exists, orphan detection, a pinned `at` that reproduces its bundle.
M4 — Walking: following a branch by a scheduled read and compare, `--no-follow`, `twin show`.
M5 — Configuration: each device's artifact as Infrahub renders it, in the bundle and pushed after readiness.
M6 — PSP format and lossy mapping: the mapping profile and the conformance suite.
M7 — EOS: the second vendor as data, the account-gated image path, a mixed twin.
M8 — Object storage and Temporal cluster: not yet built.
M9 — Remote hosts: not yet built.
M10 — Waypoints: `FylgjaWaypoint`, `twin create --waypoint`, `waypoint list` and `waypoint plan`.
M11 — Stepping: `twin step` from one waypoint to another without a rebuild, the replace push, a diverged twin.
M12 — Verify: `twin verify` and the step's wait.
M13 — API: `fylgja serve` on the lab host, every command its client.
M14 — Reproducible and visible: the cut (this repository's first commit) and the launch.

## Build and test

`scripts/bring-up.sh` (sets a fresh Ubuntu 26.04 host up: the toolchain, the lab host,
Infrahub with `main` prepared and the fixture seeded, then the build, tiers 1 and 2 and
the three processes left running; `--part NAME` runs one part, and `--part infrahub` is
what CI's contract job runs; a second run installs nothing; it asks for sudo, so it is
the operator's) · `make build` → `bin/fylgja` (CGO disabled; must stay static; `make
build VERSION=…` stamps `--version`) · `make test` (tier 1, no infrastructure; under 35s
wall uncached; CI's unit job on every push and pull request, beside its lint job, which
runs golangci-lint and `shellcheck scripts/bring-up.sh scripts/e2e.sh`) · `make
test-contract` (tier 2, real
Infrahub, never cached; needs `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN`; CI's contract
job on every push to `main`, against an Infrahub the script brings up on the runner, with
no secret) · `make lint` (runs with build tags `contract,fixture,e2e`) ·
`go test ./internal/compiler -update` regenerates the three goldens — review the diff,
and commit a re-baseline on its own · the conformance suite's pure half is part of
`make test`; its boot half is `FYLGJA_STATE_ROOT=$PWD/local go test -count=1 -tags e2e
./internal/conformance -run '^TestBootHalf$' -v` against a ready twin · `make
temporal-dev` (the file-backed dev server) · `make worker` and `make serve` (each with the
state root made absolute; load `local/.env` first) · `make infrahub-seed` and `make
infrahub-clean` (the fixture branch) · `make sdl` · `make diagrams` (needs Docker; no tier
needs it) · **every command but `worker run` and `serve` needs a running server**, the
stage commands included (`psp validate` and `twin compile` need neither Infrahub nor the
workflow service, but they need the server) · `make test-e2e` (tier 3, `scripts/e2e.sh`:
eight cases, eight twins, `twin verify` on three of them and on the steps' waits, every
command through a server the script starts itself with a token it makes; needs the dev
server and a worker running from the repository root, Docker, containerlab, **both**
images and Infrahub; about 17–19 minutes; `WORKER_LOG=<file>` adds the worker's log to its
credential greps; `PLATFORMS=nokia_srlinux` narrows it to the six cases SR Linux alone
runs, about 12 minutes, ending `E2E-PARTIAL: platforms …; ran …; skipped …` with exit 0,
never `E2E-OK`; never in CI). A command that runs longer than one tool call (tier 3)
starts detached with its exit status in a file, and is waited on in foreground calls of
under ten minutes.

## State

Rewritten whole at each milestone's close, never appended to.

- **M14 is built**: the cut, this repository's one first commit
  ([D-043](docs/decisions.md#d-043)), and the launch (`013-launch`). M1–M7 and M10–M14
  are built; M8 and M9 are not.
- **The launch** made the repository public at its start (2026-10-07), with
  `SECURITY.md`, the ruleset `main`, private vulnerability reporting and pull requests
  closed by `pull-requests.yml`; then `scripts/bring-up.sh` with its SR Linux-only path,
  CI's contract job against a real Infrahub with no secret, Infrahub rendering from this
  repository (D-044), tier 3's `PLATFORMS`, the recording, the write-up, the release
  workflow, and the five Infrahub behaviours, each dropped on the operator's word.
- **Verified** as SC-001–SC-012 record (`specs/013-launch/research.md` §3): the script's
  full run on a fresh 26.04 VM to tiers 1 and 2, tier 3 `E2E-OK` there, a second run that
  installed nothing, the run with no tar and its `E2E-PARTIAL`; CI's two jobs green and a
  pull request closed; the development host's registration, on 24.04, with tiers 2 and 3
  (case 1 deploying `b9d53ebc…`); `PLATFORMS` narrowed and whole there; and the
  development host reinstalled on 26.04 by the script, tiers 1, 2 and 3 passing there and
  its host and containerlab facts re-verified, but for a twin beside tier 2 and `sr_cli`
  under pressure, left untried on purpose. No golden and no format version moved.
- **The release `v0.1.0`** is the close's last act: the operator pushes the tag,
  `release.yml` builds the draft, the operator publishes it.
- **Next**: item 7 of the roadmap's order, the pure proposed-change check, specified as
  one pass with items 8 and 9 ([roadmap](docs/roadmap.md#next)).
- **Open**: the last runs of `013-launch`'s route: the grep for statements the launch made
  false and the closing gates, then the release and the operator's read of the front
  page, then `converge`. Arista's own checksum for the tar is unread, owed at the
  operator's next download. On 26.04, whether the two AppArmor lines suffice without
  `/run/syslogd.pid* rw,` is untried.
