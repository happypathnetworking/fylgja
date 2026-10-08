# Research: The launch

**Feature**: `013-launch` · **Plan**: [plan.md](plan.md) · **Spec**: [spec.md](spec.md) ·
**Written**: 2026-10-07, on the development host (Ubuntu 24.04.1, Infrahub 1.11.2), before
any implementation. Every fact below says how it was verified; a fact marked *owed* is
verified during implementation and recorded here then, and in
[verified-facts.md](../../docs/verified-facts.md) with its version and date once it holds.

The brief's [Left to the plan](brief.md#left) list is answered in §1, one decision each.
§2 holds what was verified live for them, §3 what the first run on Ubuntu 26.04 must
re-verify, §4 what this feature owes the records, and §5 the write-up's figures (empty
until the one session that reads them).

---

## 1. Decisions

### R-01 The script is bash, at `scripts/bring-up.sh`

**Decision**: one bash script, `scripts/bring-up.sh`, beside `scripts/e2e.sh`, under
`set -euo pipefail`, in that script's conventions (named helpers, `bring-up:` lines, a
trap). It is tooling that Fylgja does not ship (Constitution I; architecture §5's first
row).

**Rationale**: the toolchain part installs Go, so a Go tool would have to be built by the
thing it installs; bash is on every Ubuntu install; the repository's other test tooling in
shell (`e2e.sh`, `converge-loop.sh`) sets the style and the hygiene (a token in no
process's arguments, `no_credential` greps).

**Alternatives**: a Go tool under `cmd/` (rejected: needs Go first, and would sit beside
the one binary as a second program a reader might take for part of what ships);
Ansible or cloud-init (rejected: a second runtime and a second format for one host).

### R-02 Four parts, one preamble, re-runnable

**Decision**: a preamble, then four parts in order: `toolchain`, `lab`, `infrahub`,
`fylgja`. `--part <name>` (repeatable) runs the named parts alone; CI runs
`--part infrahub`. The preamble refuses a release other than 26.04 before anything
changes, asks for `sudo` once, looks for the cEOS tar and checks its checksum, scaffolds
`local/.env` when it is absent (every token made then), and prints the first report.
Each step of a part is *verify, install if missing, verify again*: a second run on a
set-up host installs nothing, re-verifies everything, keeps `local/.env` and the running
Infrahub, and ends the same way (FR-013).

The spec puts the scaffolding of `local/.env` in the Fylgja part (FR-010); it moves to
the preamble because the Infrahub part reads the file first (Compose takes the admin
token from it), and CI runs the Infrahub part alone. One run on a fresh host still
scaffolds it once, before Infrahub comes up. *(FR-010 was reworded to say so by
`analyze`.)*

**Group membership**: the lab part adds the user to `docker` and `clab_admins`, which a
running session does not see. The script then re-executes itself through
`sudo -u "$USER" -i` (a fresh login session carries the new groups) with its remaining
parts and a marker so it does not loop, and says so. Every process it later leaves
running inherits the groups. `newgrp`/`sg` were rejected (one group at a time, nested
shells); stopping to ask for a re-login was rejected (SC-001: no input after the start
but privilege escalation).

**The seed on a second run**: `fylgja-fixture`'s seed is not idempotent (`CreateBranch`
treats an existing branch as success and the seed would write the devices again), so the
Infrahub part reads the fixture branch first (GraphQL, as `e2e.sh`'s `artifacts_of`
does): three `device-config` artifacts `Ready` → skipped; absent → seeded; present and
incomplete → `make infrahub-clean`, then seeded, with one retry on `graphql: None`
(verified-facts).

### R-03 The Infrahub part writes `main` through the fixture tool

**Decision**: `cmd/fylgja-fixture` gains `-prepare-main` (build tag `fixture`, the one
binary that writes to Infrahub): load `schema/` on `main` and wait for the rebuild
(`LoadSchema`, which exists), create the group `fylgja-devices` when absent, create the
`CoreReadOnlyRepository` named `fylgja` at this repository's HTTPS location on `ref`
`main` with no credential when absent, then wait, bounded, until the repository is
`internal_status active` and `operational_status online` and `main` holds the artifact
definition `srlinux_device_config`, the transform and the query; on expiry it names what
it waited for and the stuck sync to look for (verified-facts: `git_repositories_sync`,
one slot). Flags `-repository-name`, `-repository-location`, `-repository-ref` override
the defaults. Every step looks up by name and skips what exists, so a second run writes
nothing. FR-040 allows exactly this.

**Rationale**: CI's contract job then needs Go alone, which it has for tier 2; the waits
are the bounded Go loops `testsupport` already has (`waitForKinds`, `WaitForArtifacts`),
with the knowledge of what to wait for; idempotence by `lookupByName`, which exists;
one language for test tooling. `infrahubctl` stays the operator's hand tool for
waypoints, installed by the toolchain part (FR-003).

**Alternatives**: `infrahubctl schema load --branch main`, an object file for the group
and `infrahubctl repository add --read-only --ref main` (verified present in SDK
1.23.2, §2.6). Rejected: Python on the runner for three commands; `repository add` is
not idempotent, so the GraphQL lookups would be needed anyway; the import wait would be
shell polling. Writing `main` by `curl` mutations from the script: rejected, the fixture
tool exists for writes.

**The OpsMill skill** `infrahub-managing-objects` was loaded for this decision. Its
branch-first rule (load onto a branch, never the default branch) is not followed here on
purpose: Fylgja's schema, group and registration live on `main` so that every branch
created afterwards has them ([D-028](../../docs/decisions.md#d-028)), and the fixture
tool is a local tool against the operator's own Infrahub.

### R-04 The Compose override and the Compose values move into this repository

**Decision**: the published Compose file is fetched by version,
`https://infrahub.opsmill.io/1.11.2` (§2.3), into `local/infrahub/docker-compose.yml`
(git-ignored), and the override is committed at
`scripts/infrahub/docker-compose.override.yml` and copied beside it. Compose runs with
`--env-file local/.env` and project `fylgja-infrahub`. `.env.example` gains the Compose
block: `COMPOSE_PROJECT_NAME`, `INFRAHUB_INITIAL_ADMIN_TOKEN`,
`INFRAHUB_INITIAL_ADMIN_PASSWORD`, `INFRAHUB_INITIAL_AGENT_TOKEN`,
`INFRAHUB_SECURITY_SECRET_KEY`. The script makes all four secrets (the admin token as a
UUID, the shape the development host's token has and the published default has; the
agent token a UUID; the secret key and the password random) and the API's token (24
random bytes, base64, as `.env.example` says), and writes them into `local/.env` alone.

**Rationale**: the published file carries a *default value* for the admin token, the
agent token and the secret key (§2.3), so a host that kept them would run Infrahub under
credentials anyone can read from the file; the override's version pin is now redundant
with the versioned URL but kept (a stray `VERSION` in the environment would otherwise
move the image), and its Neo4j cap is what the development host needed (verified-facts,
The host). The override's current comment on the development host cites the private
record; the committed copy states the fact and cites nothing.

**Alternatives**: keep the override outside the repository as development.md describes
(rejected: a stranger would have to write it from prose); the root URL
`https://infrahub.opsmill.io` (rejected: it serves the latest release, `1.11.4` today).

### R-05 The fresh VM is the development host's shape

**Decision**: the VM the script is proved on is a QEMU/KVM guest of 10 vCPUs, 32 GiB,
8 GiB swap and 100 GB disk, Ubuntu 26.04 Server, no nested virtualisation needed. The
script's first report prints the memory it finds and warns under 24 GiB that tier 3 was
proved with 32 GiB; it never refuses on memory.

**Rationale**: tier 3 was proved on exactly that shape, and verified-facts records a
twin starved beside Infrahub on a host with little to spare. Disk: SR Linux 3.9 GB, cEOS
2.0 GB plus its 0.5 GB tar, Infrahub's stack 2.1 GB (§2.3), the Go toolchain and module
cache about 2 GB, Neo4j's data, eight twins' containerlab directories.

### R-06 CI: the hosted runner holds Infrahub, and the contract job needs no secret

**Decision**: both jobs on `ubuntu-26.04`; the `contract` job runs on `push` to `main`
alone (`if: github.event_name == 'push'`), never `pull_request_target`; its steps are
checkout, `setup-go`, `scripts/bring-up.sh --part infrahub`, the generated-client diff,
`make test-contract` with `local/.env` loaded in the step. No repository secret: the
script makes Infrahub's admin token on the runner, it lives in the job's `local/.env`
and process environment, and the script never echoes it. The `INFRAHUB_API_TOKEN` secret
reference is removed (the repository holds no secret today, §2.7). The badge is
`actions/workflows/ci.yml/badge.svg?branch=main`. The unit job also runs `shellcheck`
over the new script (the runner has it).

**Rationale**: the runner for a public repository has 4 vCPU, 16 GB and a 6-hour job
limit (§2.8); Infrahub idles at about 5 GiB and its stack is 2.1 GB of images; the
expected wall time is about 15 minutes (pulls and health about 4, the preparation of
`main` and the seed about 3, tier 2 about 7, from 422 s on the development host), to be
recorded here on the first run (SC-004). `ubuntu-26.04` has been generally available
since 2026-09-17, and `ubuntu-latest` moves there between 2026-10-19 and 2026-11-19
(§2.8), which is why both jobs name the release.

**A correction**: the `go generate ./... && git diff --exit-code` step needs no
Infrahub. `genqlient` reads the committed `schema/infrahub.graphql` (§2.9); only
`make sdl` fetches from a live Infrahub. The step stays in the contract job as the spec
says, and its comment in `ci.yml` is corrected. The live check of the client against the
schema is tier 2 itself: a query the schema no longer answers fails there.

**If the runner cannot hold Infrahub and the import** inside the job's time, CI is split
out of the one script by a decision-log entry, as the spec's edge case allows; nothing
seen so far suggests it will be needed.

### R-07 The release is built by a tag-triggered workflow and published by the operator

**Decision**: `.github/workflows/release.yml` on `push` of a tag `v*`: checkout,
`setup-go`, `make build VERSION=<tag without v>`, assert `bin/fylgja --version` prints
it and `file` reports a statically linked executable, `make test`, require the tagged
commit's `ci` run to have succeeded (`gh run list --commit`), `sha256sum`, then
`gh release create --draft --verify-tag` with `fylgja-linux-amd64` and `SHA256SUMS`
attached, under `permissions: contents: write` and the job's own `GITHUB_TOKEN`. The
operator pushes the tag and publishes the draft (FR-037); the binary is Linux amd64
alone (the spec's assumption).

**Rationale**: a binary built on the runner from the tagged commit with `go.mod`'s
toolchain is reproducible by any reader; a hand build carries the operator's machine.
No third-party release action: `gh` is on the runner.

**Alternative**: by hand on the development host with `make build VERSION=0.1.0` and
`gh release create` (rejected, above).

### R-08 How pull requests are refused

**Decision**: three things together, since GitHub has no setting that disables pull
requests (§2.7):

1. **Write access** is the operator's alone (one collaborator, verified).
2. **A ruleset on `main`**: block force pushes and restrict deletions, with an empty
   bypass list, so the operator cannot either. Rulesets are available on the Free plan
   only for a public repository (the API answers `Upgrade to GitHub Pro or make this
   repository public`, §2.7), so the ruleset is created in the same sitting as the flip,
   immediately after it. *(FR-030 was reworded to say so by `analyze`: before the flip
   the protection is the access list, and the ruleset follows the flip by minutes.)*
3. **A workflow** `.github/workflows/pull-requests.yml` on `pull_request_target`
   (`opened`, `reopened`), `permissions: pull-requests: write`, no checkout, which
   comments the Contributing sentence and closes the pull request with `gh pr close`.
   It is the one `pull_request_target` in the repository: it runs no code of the fork
   and holds no secret but the job's token, so the brief's concern (a fork's code with
   the contract job's secrets) does not arise, and FR-022 holds for the contract job.

**Alternatives**: interaction limits (rejected: at most six months, and they block
issues too, which stay open); the pull-request limit for users without write access
(rejected: it caps the count of open pull requests, and the documentation shows no zero,
§2.7); closing by hand alone (kept as the fallback the README already states).

### R-09 The write-up's figures: what is counted, and how

**Decision**: the figures are read in one session on the development host from the
private record, at a location the operator gives in that session and nothing here
writes down; the operator reads them before they are committed to §5 and to
`docs/how-it-was-built.md`. Each figure is stated as derived from the private record.
The definitions, so that the counting is the same for every milestone:

- **An hour** is the command log's *active time*: the time a Spec Kit session was
  working, which excludes every wait on the operator (development.md, "Commands are
  logged automatically"). Hours per milestone sum `command` plus `follow_ups` over the
  milestone's features' commands. Wall-clock and the operator's own hours are not in the
  record and are not claimed.
- **A pass** is one run of a Spec Kit command; a *convergence pass* is one
  `/speckit-converge` run. The write-up counts passes per feature and, where
  `tasks.md` carries the tags, how many appended `[behaviour]` tasks, `[pin]` tasks or
  nothing.
- **Model time** is active time by model (Fable, Opus, Sonnet), with tokens by model
  beside it.
- **Counts**: features, tasks, commits, decisions, verified facts. A commit count is a
  number, not a hash.

What never crosses: a quotation, file name, path, commit hash, task number or a
feature's wording (brief, Decided).

### R-10 The recording: asciinema 3.2.1 to a GIF by agg 1.9.0

**Decision**: recorded with asciinema `3.2.1` and rendered with `agg` `1.9.0`, both
single binaries from their GitHub releases (§2.10), hand tools on the development host,
not installed by the script. Files: `docs/recording/session.cast` and
`docs/recording/session.gif`, the GIF embedded by the README. Render with `--cols 100
--rows 30`, `--idle-time-limit 2` (a create's deploy step is one line after about 40 s),
`--fps-cap 15`, a 14-point font; target under 3 MB. The session: `twin create
--waypoint fylgja-test-readme/1`, `twin step`, `twin verify`, in a shell that holds
`FYLGJA_API_TOKEN` alone; the seeding and the series are made before the recording
starts and deleted after, as the README's stepping walk-through does. Before the commit,
the cast and the GIF are grepped for the API's token, Infrahub's token and both
passwords, and every frame is read.

**Alternatives**: an animated SVG by `svg-term` (rejected: a Node runtime for a hand
tool, and the project is unmaintained); Ubuntu's `asciinema 2.4.0` from apt (rejected:
the Rust 3.x is current and agg reads its casts).

### R-11 Each Infrahub behaviour: issue or discussion

**Decision**: the starting classification below; the `infrahub-reporting-issues` skill
classifies, searches for a duplicate and shows each draft, and the operator's word files
or drops each. A filed one's link goes into verified-facts.md beside the fact.

| # | Behaviour (verified-facts, Infrahub 1.11.2) | Starting classification |
|---|---|---|
| 1 | No artifact is regenerated on its own, and nothing marks one stale | discussion (a design question: regenerate, or mark stale) |
| 2 | `?branch=` on `POST /graphql` is ignored and answers for `main` with no error | issue, bug: a silently ignored parameter |
| 3 | An attribute name is 3–64 characters, so `at` is refused by the JSON schema | issue, documentation |
| 4 | `BranchCreate` straight after `BranchDelete` of the same name can fail `graphql: None` | issue, bug, with the reproduction |
| 5 | The SDL's field order is not stable between two fetches | issue, enhancement: a deterministic SDL |

### R-12 The cEOS tar: name, checksum, where it is looked for, and how it is taken

**Decision**: the accepted file is `cEOS-lab-4.32.0.2F.tar` or `cEOS-lab-4.32.0.2F.tar.xz`
(the same content under the name Arista's portal gives it), sha256
`89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778` (md5
`4cddba6be90f1fd79c862b8d76ebcb38`), recorded in the script as a named constant beside
the version it reads from `psp/arista_eos.yaml`'s `image.ref`. The script looks at
`--ceos-tar <path>`, then `local/`, then the repository's parent directory, never the
root, and takes the named file alone. A match is imported with `docker import <tar>
ceos:4.32.0.2F`; a mismatch stops the run before any part (exit 2) naming the file and
both checksums; an absent tar leaves SR Linux alone, named in both reports with where it
looked. When `ceos:4.32.0.2F` is present the import is skipped and the report says
whether the image's one layer is the recorded tar's (§2.2), as information: the host
check reads the reference alone.

**development.md is corrected**: it names `cEOS64-lab-4.32.0.2F.tar`, but the file the
development host's image was imported from is `cEOS-lab-4.32.0.2F.tar` (§2.2). Whether
Arista publishes a checksum to compare with is *owed*: the portal needs an account, so
the operator reads it at the next download.

### R-13 Tier 3's platform list

**Decision**: `PLATFORMS=<list> make test-e2e`, an environment variable like
`WORKER_LOG`, a comma- or space-separated list of shipped package names (each package's
`platform.id`, the stem of its `psp/*.yaml`: `nokia_srlinux`, `arista_eos`). Each case declares its packages in
one table at the top of `scripts/e2e.sh` (cases 1–5 and 7: `nokia_srlinux`; 6 and 8:
`nokia_srlinux arista_eos`). Unset, the script requires every shipped package's image,
as now. Set, it refuses a name no package has (naming the packages known) and a list
that selects no case; skips each case needing a package outside the list, or an
account-gated image that is absent; and ends, when every case it ran passed, exit 0 on
the partial-pass line of [contracts/e2e-platform-list.md](contracts/e2e-platform-list.md),
never `E2E-OK`. A list naming every package on a host with every image runs as a default
run. The closing timing lines print only for the cases that ran (`set -u` would
otherwise fail on a skipped case's variables). The trap, the destroy and the credential
and marker greps are unchanged.

### R-14 The read of the tree: what cites the private record today

**Decision**: the `description` strings of the current contracts
(`contracts/api.schema.json`, `findings.schema.json`, `manifest.schema.json`,
`psp.schema.json`), of `psp/psp.schema.json` and of the frozen copies under
`internal/*/testdata/contracts/*/` cite private specification paths (`specs/0NN-…`),
requirement numbers and research runs (§2.11). They are rewritten to state what each
format version changed, with no path, number or run; every frozen copy of one file is
edited identically (`TestFrozenContractCopiesAgree` holds the copies byte-equal) and
`psp/psp.schema.json` with `contracts/psp.schema.json` (`TestShippedSchemaIsTheContractSchema`).
A description changes no validation, so no format, golden or history moves (FR-039). The
frozen copies' directory names (`testdata/contracts/004-walking/`) are kept: they are
the public convention development.md documents, a format's origin, as a bare milestone
marker is ([D-043](../../docs/decisions.md#d-043)). The override's comment on the
development host (R-04) is not carried over. The template's own text
`rendered by Infrahub (fylgja-artifacts)` is in every artifact and golden and is the
template's bytes, which do not change ([D-044](../../docs/decisions.md#d-044)).

### R-15 The registration on the development host, and the `ref` question

**Decision**: after the flip, in one session with the operator present: remove the
private copy (`CoreRepositoryDelete` of `fylgja-artifacts`, then its
`CorePasswordCredential`), record whether the transform, the query and the definition
survive the delete, run `fylgja-fixture -prepare-main`, record that the three objects on
`main` now belong to the registration `fylgja`, then `make infrahub-clean && make
infrahub-seed` (a branch sees `main` as it was when the branch was created, so the fixture
branch is re-created), and prove `b9d53ebc…`, tier 2 and tier 3. The `ref` question is
then answered against three candidates: the minute sync moving `commit` on its own;
`CoreReadOnlyRepositoryUpdate` of `ref`; and the mutation
`InfrahubReadOnlyRepositoryImportLastCommit`, which exists on this install (§2.5).

---

## 2. Verified on 2026-10-07 (development host, Infrahub 1.11.2)

### 2.1 The private copy's registration

`CoreGenericRepository` on `main` holds one object: a `CoreRepository` named
`fylgja-artifacts`, `internal_status active`, `operational_status online`,
`default_branch main`, with a `CorePasswordCredential` named `fylgja-artifacts`. The
transform `srlinux_device_config`, the query `device_config` and the artifact definition
`srlinux_device_config` (artifact `device-config`) on `main` name it as their repository.
The group `fylgja-devices` has 0 members on `main`; `FylgjaWaypoint { count }` is 0.

### 2.2 The cEOS tar and the imported image

- The file on the development host is `/home/<user>/cEOS-lab-4.32.0.2F.tar`, 520,647,724
  bytes, **XZ compressed data** despite its name (`file`); its sha256 is
  `89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778`, its md5
  `4cddba6be90f1fd79c862b8d76ebcb38`.
- `ceos:4.32.0.2F` is `sha256:bafbcc3a…`, `amd64`, created 2026-09-30, 2,043,819,653
  bytes, one layer `sha256:09ab96357c1d41f8bbaaead9ac10f61724f4890afcc09c75ad6b42519d73dd6c`,
  `Comment: Imported from -`, no `Cmd`.
- `xz -dc <tar> | sha256sum` is `09ab9635…`: **an imported image's one layer digest is the
  sha256 of the decompressed tar**, so the image on the host came from this file, and a
  present image can be told from the recorded tar without re-importing. `docker import`
  takes the xz stream directly (the image's comment).
- development.md's `cEOS64-lab-4.32.0.2F.tar` is not the file the proven image came from.

### 2.3 Infrahub's published Compose

- `https://infrahub.opsmill.io/1.11.2` serves a Compose file whose three Infrahub services
  read `${VERSION:-1.11.2}` (20,275 bytes); the root URL serves the latest release
  (`${VERSION:-1.11.4}` today); `/1.11` is 404. The file on the development host was
  fetched from the root when `1.11.3` was latest and differs from the versioned one by
  four TLS-related variables and the default.
- The published file carries defaults for `INFRAHUB_INITIAL_ADMIN_TOKEN`,
  `INFRAHUB_INITIAL_AGENT_TOKEN` and `INFRAHUB_SECURITY_SECRET_KEY` (UUID-shaped, in the
  file for anyone to read) and `INFRAHUB_INITIAL_ADMIN_PASSWORD:-infrahub`; it publishes
  `8000:8000` (the server), `2004` and `6362` (Neo4j), `15692` (RabbitMQ metrics) on every
  interface. Services: `message-queue` (rabbitmq 4.2.1), `cache` (redis 8.4.0),
  `database` (neo4j 2026.05.0-community), `task-manager`, `task-manager-db` (postgres
  18-alpine), `infrahub-server` (healthcheck `GET /api/config`), `task-worker`.
- The images total about 2.1 GB (infrahub 759 MB, neo4j 637 MB, postgres 304 MB,
  rabbitmq 251 MB, redis 139 MB).
- The development host's Infrahub token is a 36-character UUID; the API's token in
  `local/.env` is 32 characters.
- **Compose 5 already runs the override**: the development host has Docker 27.5.1 with
  Compose `v5.5.1`, and the project `fylgja-infrahub` has been up two days under it. The
  brief's question about the override under Compose 5 is answered on 24.04; 26.04's
  packaged Docker still re-verifies it (§3).

### 2.4 The schema on `main` is this repository's

`POST /api/schema/check?branch=main` with `schema/*.yaml` answers 202 with an empty
diff (`added`, `changed`, `removed` all `{}`) and four deprecation warnings
(`display_labels` on the four Fylgja kinds). So `LoadSchema` on `main` is a no-op on a
host that has it, which is what `-prepare-main`'s re-run relies on. `main`'s hash is
`4d5b37aa0a894aec4cdca69fdb9fe455`.

### 2.5 The mutations and inputs `-prepare-main` uses

Introspected on `main`: `CoreReadOnlyRepositoryCreate(data: {name, location, ref,
description, credential?, …})` with `credential` an optional `RelatedNodeInput`;
`CoreStandardGroupCreate(data: {name, label, description, group_type, members, …})`;
`CoreRepositoryDelete`, `CoreReadOnlyRepositoryDelete`, `CoreReadOnlyRepositoryUpdate`;
and `InfrahubReadOnlyRepositoryImportLastCommit`, `InfrahubRepositoryProcess`,
`InfrahubRepositoryConnectivity`. `CoreReadOnlyRepository`'s fields include `ref`,
`commit`, `internal_status`, `operational_status`, `sync_status`.

### 2.6 `infrahubctl` 1.23.2

A venv at `.venv/` was created in this clone (`python3 -m venv`, `.gitignore` of `*`
inside, `infrahub-sdk[ctl]==1.23.2`; this clone had none). `infrahubctl repository add
{name} {location} [--read-only] [--ref] [--username] [--password] [--description]` exists.
PyPI says `requires_python >=3.10,<3.15` with 3.14 classified, so Ubuntu 26.04's Python
(3.14.4 on the hosted runner, §2.8) is inside the range; the host's own is re-verified
(§3).

### 2.7 GitHub, the repository today

- `happypathnetworking/fylgja`, private, default branch `main`, one collaborator, issues
  on, projects on, wiki off, discussions off, no topics, no release, no tag, **no
  secret**, one workflow (`ci`), its one run on `main` green in 3m07s (the unit job).
- `GET /repos/…/rulesets` and `/branches/main/protection` answer 403 `Upgrade to GitHub
  Pro or make this repository public to enable this feature`: rulesets wait for the flip.
- Interaction limits last at most six months and cover issues and pull requests together;
  the pull-request limit caps how many a user without write access may have open and
  the documentation shows no zero; no setting disables pull requests
  ([GitHub docs: limiting interactions](https://docs.github.com/en/communities/moderating-comments-and-conversations/limiting-interactions-in-your-repository),
  [GitHub blog: pull request limits](https://github.blog/open-source/maintainers/how-pull-request-limits-are-cutting-down-the-noise/)).

### 2.8 The hosted runner

- `ubuntu-26.04` is generally available since 2026-09-17; `ubuntu-latest` migrates from
  24.04 to 26.04 gradually between 2026-10-19 and 2026-11-19
  ([GitHub changelog](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/)).
- Image `20260927.149.1`: Ubuntu 26.04.1 LTS, kernel `7.0.0-1012-azure`, Docker
  `29.4.2`, Compose `5.1.3`, Python `3.14.4` (3.10–3.14 cached), Go 1.24–1.26 cached,
  git `2.55.0` ([runner-images README](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2604-Readme.md)).
- A standard runner for a public repository has 4 vCPU and 16 GB; a job runs at most six
  hours ([runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
  [limits](https://docs.github.com/en/actions/reference/actions-limits)).

### 2.9 `go generate` reads the committed SDL

`internal/intent/generate.go` carries the one directive, `go run github.com/Khan/genqlient`,
and `genqlient.yaml` names `../../schema/infrahub.graphql` as its schema. The CI
comment's "regeneration fetches the SDL from a live Infrahub" describes `make sdl`, not
`go generate`.

### 2.10 The tools' current releases

asciinema `v3.2.1` (2026-06-16; `asciinema-x86_64-unknown-linux-gnu`), agg `v1.9.0`
(2026-05-29; `agg-x86_64-unknown-linux-gnu`), Temporal CLI `v1.9.1`, containerlab
`v0.79.0`, golangci-lint `v2.14.0`, gnmic `v0.49.0`: each pinned version is the latest.
Ubuntu 24.04's apt has asciinema `2.4.0`. The installers take a pin: `cli.sh --version
1.9.1` (Temporal), `get.containerlab.dev --version 0.79.0` (and `containerlab.dev/setup`
pins Docker per release, `29.8.1` for 26.04, with `CLAB_VERSION`), `get-gnmic.openconfig.net
--version 0.49.0`, golangci-lint's `install.sh -b /usr/local/bin v2.14.0`.

### 2.11 Private-record citations in the tree

`grep -rE 'specs/0(0[1-9]|1[0-2])-'` outside this feature's directory finds 21 files:
`contracts/{api,findings,manifest,psp}.schema.json`, `psp/psp.schema.json`, 15 frozen
`findings.schema.json` copies under `internal/{cli,findings,provision,server}/testdata/contracts/`,
and `.claude/skills/speckit-specify/SKILL.md` (an example path in Spec Kit's own text,
not the record). `research R…` and `FR-0NN` references sit in the same descriptions and in
`internal/{cli,findings}/testdata/contracts/001-read-compile/findings.schema.json` and
`internal/findings/testdata/contracts/008-waypoints/waypoints.schema.json`. No hit for a
host path, a process id or a private path elsewhere.

### 2.12 The host, as the script will find a set-up one

Ubuntu 24.04.1, kernel 6.8.0-142, 10 CPUs, 32,095 MiB, 8 GiB swap; the user in
`clab_admins` and `docker`; `/etc/apparmor.d/local/usr.sbin.rsyslogd` carries the two
lines plus `/run/syslogd.pid* rw,`; the worker and the API's server run from this tree
(`/proc/<pid>/cwd` and `exe` under `fylgja-public/`); the dev server runs. Nothing else
in `local/` but what development.md lists.

---

## 3. Owed: the first run on Ubuntu 26.04 re-verifies

Recorded here when the script first runs there, then in verified-facts.md with `26.04`
and the date; a fact that no longer holds is a finding (FR-015).

- **The host** (verified-facts, *The host*): the AppArmor profile `usr.sbin.rsyslogd`
  still attaches to SR Linux's `rsyslogd` and the two `local/` lines still suffice (the
  third line on the development host, `/run/syslogd.pid* rw,`, is recorded as what the
  script writes if 26.04 needs it); `/dev/kvm` absent and unneeded; Infrahub's idle
  memory and the Neo4j cap; a twin beside tier 2 still starves.
- **Docker** as the packaged or Docker-repository release the lab part installs, and
  Compose 5 under it running the published file with the override.
- **containerlab 0.79.0** on 26.04's kernel: the `clab_admins` group, `absLabPath`,
  the dry run with `CLAB_LABDIR_BASE`, the reconcile's behaviours (every containerlab
  fact is kernel-adjacent).
- **The images**: SR Linux 24.7.1 boots and is ready in its budget; cEOS 4.32.0.2F imports
  from the recorded tar and boots.
- **Python**: 26.04's `python3` version against the SDK's range (§2.6).
- **Go**: Ubuntu 26.04's packaged `go` fetches go1.26.0 through `go.mod`.
- **Temporal CLI 1.9.1** and the dev server; **golangci-lint 2.14.0** (the v2 line).
- **The registration** (D-044, §2.1): the import of this repository's `.infrahub.yml`
  completes credential-less; the time to `active` and `online`; and R-15's three
  questions (does a repository delete remove its transform, query and definition; does
  the re-registration keep their ids; which of the three ways takes a new commit).
- **The hosted runner**: the contract job's wall time and peak memory, and whether
  Infrahub reaches healthy inside a few minutes there.
- **Arista's checksum** (R-12), at the operator's next download.

### 3.1 Recorded: the flip, 2026-10-07

- **Before the flip**: the tree read (quickstart §1) found nothing private; run 1's
  commits were fast-forwarded to `main` and pushed at 19:33Z, `origin/main` at `4495ec9`.
- **The settings**, read back by `gh` after the sitting: visibility `PUBLIC`; the ruleset
  `main` created 19:36:12Z, `target: branch`, `enforcement: active`, include
  `~DEFAULT_BRANCH`, exclude none, rules `deletion` and `non_fast_forward`,
  `bypass_actors: []`, as the contract gives it; private vulnerability reporting
  `enabled: true`; issues on, projects and wiki off; the eight topics `arista-eos`,
  `containerlab`, `digital-twin`, `go`, `infrahub`, `network-automation`, `srlinux`,
  `temporal`; Actions secrets 0.
- **The public view**: `env -u GH_TOKEN GIT_TERMINAL_PROMPT=0 git -c credential.helper=
  clone https://github.com/happypathnetworking/fylgja.git` in an empty temporary
  directory succeeded and held `README.md`, `LICENSE` and `SECURITY.md`. The
  `-c credential.helper=` is what makes it a stranger's clone: the development host's
  `~/.gitconfig` names `gh auth git-credential` as the helper for `https://github.com`,
  and a trace of `git credential fill` shows git running it without the override and
  stopping at `terminal prompts disabled` with it.
- **A pull request**: #1, from a throwaway branch `pr-check` made through the API, opened
  20:13Z. `pull-requests.yml` ran on `pull_request_target` and succeeded in 15s; the
  pull request carries one comment, by `github-actions`, in the Contributing sentence,
  and was closed at 20:13:18Z; the branch was deleted. `ci` ran its unit job on the pull
  request, as it does on every one.
- **A finding: a race in `internal/cli`'s tests.** The unit job on the push to `main`
  failed in `TestTheClientReadsTheAPIsTwoVariablesAlone` ("the server logged 2 requests,
  want 1"), passed on a re-run at 19:56Z, and failed the same way on #1. The harness's
  server logs a request after its client has read the document, and every test reads one
  shared log, so a line that lands late is counted by a later command. It predates this
  feature: on `f601cb8`, the whole suite on four CPUs failed 2 of 8 runs, in this test and
  in `TestPSPValidateReportsAnUnreadableFileFirst`. Fixed on `013-launch`: every count of
  the log waits until the server serves nothing (`awaitIdle`); 12 runs on four CPUs and 4
  on two then passed.

### 3.2 Recorded: the registration on the development host, 2026-10-07

- **Before the swap** (T015), read by GraphQL on `main`, each found by name once:

  | Object | Name | id | Repository |
  |---|---|---|---|
  | `CoreGraphQLQuery` | `device_config` | `18da2a5d-e12f-c2a3-3409-c5118660fec2` | `fylgja-artifacts` |
  | `CoreTransformJinja2` | `srlinux_device_config` | `18da2a60-2714-cba1-340b-c517bf6ee1ea` | `fylgja-artifacts` |
  | `CoreArtifactDefinition` | `srlinux_device_config` (artifact `device-config`) | `18da2a61-ecbd-e9f6-3402-c5117971f0c0` | none (the kind has no `repository`; its transform names it) |

  `CoreGenericRepository` held one object, the `CoreRepository` `fylgja-artifacts`
  (`18da2a54-695c-170f-3407-c510e9cd2815`), whose credential was the one
  `CorePasswordCredential`, `fylgja-artifacts` (`18da2a40-8dc6-87dd-3405-c51176d27285`).
- **The delete** (T015), by the operator, by GraphQL on `main`: `CoreRepositoryDelete`
  of the repository, then `CorePasswordCredentialDelete` of the credential; both answered
  `ok: true`.
- **What survives the delete** (R-15's first question): nothing. Read back on `main`
  afterwards, `CoreGenericRepository`, `CorePasswordCredential`, the query
  `device_config`, the transform `srlinux_device_config` and the definition
  `srlinux_device_config` each count 0. Deleting a `CoreRepository` deletes the objects
  its import made, so from the delete until the next registration's import `main` cannot
  render an artifact, and the import makes the three objects anew.
- **`-prepare-main`, the first live run** (T016), by the operator, with `local/.env`
  loaded: `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` printed

  ```
  schema loaded on main
  group fylgja-devices present
  repository fylgja created (location https://github.com/happypathnetworking/fylgja.git, ref main, no credential)
  import complete after 24s: query, transform and definition on main
  ```

  in 35s wall, the build included: the registration reached `active`, `online` and the
  three objects 24 s after its creation, with no sync stuck. The group was `present`
  because the delete removed the repository's objects alone.
- **The second run** printed the same lines but `repository fylgja present (location
  https://github.com/happypathnetworking/fylgja.git, ref main)` and `import complete after
  0s`, in 2.7 s wall: it found everything in place and created nothing (contract,
  Idempotence).
- **`main` after the registration**, read back by GraphQL: `CoreGenericRepository` holds
  one object, the `CoreReadOnlyRepository` `fylgja` (`18dc59e8-1961-9499-340f-c517ee2b828d`),
  location `https://github.com/happypathnetworking/fylgja.git`, `ref main`, `commit
  4495ec9d7a8d1a53fda35e2ca016353c5f94a0d6` (`origin/main` at the time), `active`,
  `online`, no credential; `CorePasswordCredential` counts 0. The three objects are new,
  and the query and the transform name `fylgja` as their repository (R-15's second
  question):

  | Object | id before | id after |
  |---|---|---|
  | query `device_config` | `18da2a5d-e12f-c2a3-3409-c5118660fec2` | `18dc59ea-8cb2-1ef8-3401-c513dff2ecd4` |
  | transform `srlinux_device_config` | `18da2a60-2714-cba1-340b-c517bf6ee1ea` | `18dc59ec-9653-cb6a-3401-c5149735ae15` |
  | definition `srlinux_device_config` (`device-config`) | `18da2a61-ecbd-e9f6-3402-c5117971f0c0` | `18dc59ee-08cb-f50a-340d-c513f7d9e7d1` |

  The ids moved because the delete removed the old objects, not because the registration
  replaced them in place. Nothing Fylgja keeps holds these ids: the definition and the
  group are looked up by name (`lookupByName`), so no file or test changes.
- **The fixture re-made and compiled** (T017): the operator re-created `fylgja-fixture`
  (`make infrahub-clean && make infrahub-seed`) after the registration. `make build`
  (static), then the worker and the API's server restarted from this tree, each on
  `bin/fylgja` not `(deleted)`, each environment carrying `INFRAHUB_*`, both logins,
  `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`, each report naming `arista_eos` and
  `nokia_srlinux` with their logins set, the server's `listening on 127.0.0.1:7650 (API
  version 1, build 0.1.0-dev)`. `fylgja intent read --branch fylgja-fixture` read 3
  devices, 12 interfaces, 3 links and 3 artifacts at schema `4d5b37aa0a894aec4cdca69fdb9fe455`,
  and `fylgja twin compile` gave `bundle_id
  b9d53ebc8d8187ccc73623cd9be2740fb865ff101edc58c0e732735d4fd9d668`: the artifacts
  Infrahub renders from this repository are byte for byte the ones it rendered from the
  private copy.
- **Tier 2** (T017): `make test-contract` passed, exit 0 in 366 s wall, every package
  `ok` (the longest `internal/stage` 358 s, `internal/waypoint` 208 s, `internal/intent`
  191 s); afterwards `fylgja waypoint list` printed `no waypoints`.
- **Tier 3** (T018), on a quiet host (no test or twin running, 20.7 GiB available, load
  2): `WORKER_LOG=local/worker.log make test-e2e`, detached, ended `E2E-OK`, exit 0, eight
  cases, case 1 deploying `b9d53ebc8d8187ccc73623cd9be2740fb865ff101edc58c0e732735d4fd9d668`;
  the script's wall time 1083 s (18 min), creates 42–71 s, verify 2.8–3.5 s, the boot half
  7.8 s and 7.2 s. Afterwards `clab inspect --all` found no containers, `local/twin` was
  absent and `fylgja waypoint list` printed `no waypoints`.
- **The `ref` question** (T019; FR-029, R-15), Infrahub 1.11.2. The operator pushed
  `main` at `510d32ba2ec1729e9ca536caa21c05c59016619f` (on `origin` by 21:21:40Z), so the
  registration's `commit`, `4495ec9`, was one push behind.
  1. *The minute sync on its own*: no. At 21:24:47Z, three minutes on, `commit` was still
     `4495ec9d7a8d1a53fda35e2ca016353c5f94a0d6`, its `updated_at` 20:40:12Z (the
     import), and the repository `active`, `online` and `sync_status in-sync`: a
     read-only repository is not polled for a moved `ref`, and says it is in sync.
  2. *`CoreReadOnlyRepositoryUpdate` of `ref`, set to `main` again*: no. Sent at
     21:25:45Z, it answered `ok: true`; at 21:26:46Z `commit` was still `4495ec9…`, its
     `updated_at` unchanged at 20:40:12Z. An update to the value `ref` already holds
     writes nothing to act on.
  3. *`InfrahubReadOnlyRepositoryImportLastCommit(data: {id})`*: **yes**. Sent at
     21:27:59Z, it answered `ok: true` with a task id; `commit` read
     `510d32ba2ec1729e9ca536caa21c05c59016619f` with `updated_at` 21:28:07Z, 8 s after the
     call, the repository still `active`, `online`, `in-sync`.

  So on 1.11.2 a read-only registration imports at its creation and afterwards only when
  asked: a commit pushed to its `ref` reaches Infrahub by `ImportLastCommit`, and by
  neither the sync nor a rewrite of `ref`. An artifact rendered before the import keeps
  its bytes until it is regenerated, which Infrahub does not do on its own.

### 3.3 Recorded: the installers and the script on the development host, 2026-10-07

**The installers' flags** (T024, against §2.10), read from each installer's current text:

- Temporal `https://temporal.download/cli.sh` takes `--version 1.9.1` and installs into
  `$HOME/.temporalio` (`--dir` overrides it). As §2.10 says.
- gnmic `https://get-gnmic.openconfig.net` and containerlab `https://get.containerlab.dev`
  take `--version` or `-v`, with the version with or without its `v` (each prefixes
  one); both run what needs root through `sudo` themselves, so the script runs them as the
  user. containerlab's installs its `.deb` by default (`/usr/bin/containerlab`, as the
  development host's is). As §2.10 says.
- golangci-lint's `install.sh` takes `-b <dir> v2.14.0`; the script fetches it from the
  `v2.14.0` tag rather than `HEAD` and runs it under `sudo` for `/usr/local/bin`.
- **Difference**: containerlab's setup script (`https://containerlab.dev/setup`, whose
  `install-docker` the lab part runs) does not pin Docker by `CLAB_VERSION`, which names
  the containerlab release alone. Its Docker pin is in its own text, per distribution
  release: today's sets `29.8.1` for Ubuntu 26.04 (and fails with no packages removed
  when that release is not in Docker's repository), while the copy at containerlab's
  `v0.79.0` tag (`utils/quick-setup.sh`) predates 26.04 and would fall back to `27.5.1`.
  So the lab part runs today's script, and the Docker it installs is that script's pin
  for 26.04, recorded at the first 26.04 run (§3).

**The script on the development host** (T028; Ubuntu 24.04.1, ShellCheck 0.9.0, 24.04's
package): `shellcheck scripts/bring-up.sh` and `bash -n` are clean; `--help` exits 0;
the script with no flag, `--bogus`, `--part nope` and `--after-groups` without the marker
each exit 2 with `bring-up: REFUSED: this host is Ubuntu 24.04.1 LTS; the script
supports Ubuntu 26.04 alone`, the release coming first in the preamble; `git status
--short` and `local/` were the same before and after. A copy reading a 26.04
`os-release` from the scratchpad showed each flag refusal's own words, exit 2, before
`sudo`. The script's read-only helpers, run against the live host, read the worker's and
the server's reports as naming both packages with their logins set, the dev server
`SERVING`, `/api/info` `1.11.2`, the fixture `complete`, port 8000 held by
`fylgja-infrahub`'s `infrahub-server`, and `ceos:4.32.0.2F`'s layer as the recorded tar's.

### 3.4 Recorded: the full run on a fresh Ubuntu 26.04 VM, 2026-10-07

- **The VM** (R-05): Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic`, 10 vCPUs, 31,065 MiB,
  8 GiB swap, a 59 GB root; no `/dev/kvm`. A clone of `013-launch` at `5207aae`, the tar
  `cEOS-lab-4.32.0.2F.tar` in the clone's parent directory. The operator's user was in
  `sudo` and had passwordless sudo by a file under `/etc/sudoers.d/`, which the operator
  removes before the second run (T031) so that its prompt is exercised.
- **The run** (T029), by the operator: `scripts/bring-up.sh 2>&1 | tee /tmp/bring-up.out`,
  begun 22:25:46Z, ended `bring-up: DONE in 1685s`, exit 0. The first report:

  ```
  bring-up: host: Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic, 10 CPUs, 31065 MiB, swap 8191 MiB
  bring-up: parts: toolchain lab infrahub fylgja
  bring-up: cEOS tar: found <the clone's parent>/cEOS-lab-4.32.0.2F.tar (sha256 matches 89a567d5…)
  bring-up: platforms: nokia_srlinux arista_eos
  bring-up: memory: 31065 MiB; tier 3 was proved with 32768 MiB
  bring-up: local/.env: scaffolded from .env.example (mode 0600)
  ```

  One prompt, `sudo -v`'s (finding 2), and none after it. One re-exec through a fresh login
  session, after the lab part's groups. Tier 1 passed in 35 s and tier 2 in 398 s; the last
  report named the dev server, the worker and the API's server running, the worker and the
  server each with `packages nokia_srlinux arista_eos`, and how to stop them.
- **The parts' times**, from the modification times of what the run wrote (UTC): the
  preamble to `local/.env` at 22:27:37, the prompt's wait included; the toolchain about
  1 min (the venv at 22:28:26); the lab about 10 min, to the Compose file at 22:38:35
  (Docker's install, containerlab, the re-exec, the 5.19 GB SR Linux pull and the 2.91 GB
  cEOS import, tagged 22:37:25); the infrahub part 7 min 12 s (Compose's pulls and start,
  `infrahub-server` started 22:40:25, `-prepare-main` done 22:44:42, the seed done
  22:45:47); the fylgja part 8 min (the build at 22:46:33, tier 1, tier 2, the three
  processes up by 22:53:50).
- **The items.** Toolchain: `make`, `golang-go`, `python3-venv` and `shellcheck` installed
  by one `apt-get install`, `git`, `curl`, `jq`, `xz-utils` and `file` present; `go`
  `installed go1.26.0` (finding 4); golangci-lint `2.14.0`, Temporal `1.9.1`, gnmic
  `0.49.0` and `infrahub-sdk` `1.23.2` (`.venv`, Python 3.14.4) installed: 5 present, 9
  installed, read from the item lines because the report omits the part's line (finding
  1). `did: lab: 0 present, 6 installed, 0 skipped` (Docker, containerlab, the groups with
  `docker added`, AppArmor's three lines and the reload, SR Linux pulled, cEOS imported from
  the tar). `did: infrahub: 1 present, 5 installed, 0 skipped` (the server's item reads
  `present` once it answers). `did: fylgja: 0 present, 4 installed, 0 skipped`.
- **What §3 owed, as this run found it:**
  - *The host*: `/etc/apparmor.d/usr.sbin.rsyslogd` ships on 26.04; the lab part appended
    the three lines to `local/usr.sbin.rsyslogd` and reloaded the profile. Whether it still
    attaches to SR Linux's `rsyslogd`, and whether the lines suffice, needs a twin, which
    tiers 1 and 2 do not boot: tier 3 answered it (below). `/dev/kvm` absent and unneeded.
    Infrahub after the run: about 5.2 GiB across its eight containers (Neo4j 2.10 GiB under its cap,
    the server 1.60 GiB, the task manager and the two task workers about 0.44 GiB each), and
    `free -m` 24,732 MiB available with the three processes running.
  - *Docker*: containerlab's setup script installed Docker's repository packages,
    `docker-ce` `29.8.1` (the pin §3.3 read for 26.04), `containerd.io` `2.3.6` and the
    Compose plugin `5.6.0`. Compose 5.6 ran the published file with the override, warning
    once per start that the task worker's `deploy.mode is only honored in Swarm mode`; it
    pulled `neo4j:2026.05.0-community`, `postgres:18-alpine`, `redis:8.4.0`,
    `rabbitmq:4.2.1-management` and `infrahub:1.11.2`.
  - *containerlab 0.79.0*, from its `.deb`: `/usr/bin/containerlab` setuid root, as on the
    development host; its package created `clab_admins` and put the user in it, so the lab
    part added `docker` alone (finding 5). Its twin-side facts (`absLabPath`, the dry run,
    the reconcile) need twins: tier 3, below.
  - *The images*: `ghcr.io/nokia/srlinux:24.7.1` pulled; `ceos:4.32.0.2F` imported from the
    tar, its layer the recorded `sha256:09ab9635…`. Their boots are tier 3's, below.
  - *Python*: 26.04's `python3` is 3.14.4 (`python3.14-venv` 3.14.4), inside
    `infrahub-sdk` 1.23.2's `>=3.10,<3.15`; the SDK installed into `.venv`.
  - *Go*: **26.04's packaged Go is go1.26.0** (`golang-go` `2:1.26~1`, `golang-1.26-go`
    `1.26.0-1`), the release `go.mod` names, so nothing is fetched: the module cache holds no
    `golang.org/toolchain`, and `go version` in the clone is the packaged binary's.
  - *Temporal CLI 1.9.1* (Server 1.32.0, UI 2.54.1) by its installer into
    `~/.temporalio/bin`, its dev server `SERVING` inside the 60 s wait; *golangci-lint
    2.14.0* (the v2 line) into `/usr/local/bin`; gnmic `0.49.0`; ShellCheck `0.11.0`, 26.04's
    package.
  - *The registration*, on a fresh Infrahub: `schema loaded on main`, `group fylgja-devices
    created`, `repository fylgja created (location https://github.com/happypathnetworking/fylgja.git,
    ref main, no credential)`, `import complete after 48s`. Credential-less, as on the
    development host (24 s, §3.2) and in CI (22 s, §3.5).
  - *sudo*: 26.04's `sudo` is **sudo-rs 0.2.13** (`/usr/bin/sudo` → `/usr/lib/cargo/bin/sudo`
    through alternatives).
- **Tier 3** (T030), on the host the run left (the dev server, the worker and the API's
  server running; `free -m` 24,634 MiB available, load 0.9, no twin): `make build` left the
  worker's binary in place (not `(deleted)`); `WORKER_LOG=local/worker.log make test-e2e`,
  detached with its exit status in a file, first stopped at once on finding 7, then, with
  `PATH=$HOME/.temporalio/bin:$PATH`, began 23:06:08Z and ended `E2E-OK`, exit 0, all eight
  cases, wall time 1107.1 s (18.5 min; 1083 s on the development host, §3.2). Creates
  42.7–73.6 s (case 6's mixed twin the longest), `twin verify` 3.7 s, 3.8 s and 2.4 s, the
  boot half 9.9 s and 7.0 s, case 8's steps 82.4 s and 63.3 s, their waits settled after
  4.6 s and 3.4 s. Afterwards `clab inspect --all` found no containers, `local/twin` was
  absent, `fylgja waypoint list` printed `no waypoints`, 23,710 MiB available. So on 26.04
  with kernel 7.0: SR Linux deploys through containerlab's post-deploy commit with the
  three AppArmor lines (whether two suffice was not tried); cEOS 4.32.0.2F, imported from
  the tar, boots and runs its artifact (cases 6 and 8); every containerlab path tier 3
  drives (the deploy, the dry run, the orphan of case 3, the destroy) works.
- **Case 1's bundle is `140ae538…`, not `b9d53ebc…`**, and no run on another Infrahub can
  give `b9d53ebc…`. The VM's fixture CTM equals the development host's but for
  `observed_at` and `schema_hash` (`3b686463ab78483d647a5f04187ad22b` here, `4d5b37aa…`
  there): the schema hash is the install's (CLAUDE.md, "a branch's hash covers its whole
  schema, so each install has its own"), and the bundle covers it. The VM's CTM, compiled
  on the development host with `4d5b37aa…` in its place, gives
  `b9d53ebc8d8187ccc73623cd9be2740fb865ff101edc58c0e732735d4fd9d668` exactly. So the fixture
  the VM's Infrahub renders from this repository is the development host's, byte for byte,
  and the id `b9d53ebc…` is the development host's install, not the fixture's alone:
  SC-002, US2's scenario and quickstart §3 named it for the VM, which no fresh install can
  meet. The operator settled their wording (spec, Clarifications): case 1's fixture
  compiles to `b9d53ebc…` under the development host's schema hash, which this run meets.
- **Hygiene**: the greps of quickstart §3, by the operator against the variables from a shell
  that had loaded `local/.env`, over `/tmp/bring-up.out`, `local/*.log`, `bin/`, `.venv/` and
  `local/infrahub/`, found nothing. Repeated after the run for `INFRAHUB_API_TOKEN`,
  `FYLGJA_API_TOKEN`, the SR Linux password, `INFRAHUB_INITIAL_ADMIN_PASSWORD`,
  `INFRAHUB_INITIAL_AGENT_TOKEN` and `INFRAHUB_SECURITY_SECRET_KEY`: 0 files each. The EOS
  image's published default password is a common word, which no grep tells from other
  text; the worker's and the server's reports say each login is `set`, never its value.
- **Findings**, recorded and not fixed in this run (each fix after it is said beside it;
  the fixes after T031 were checked against stand-ins for `sudo`, `go` and the login
  session's groups, run on the blocks taken from the script, then on a fresh host by
  T043, §3.8):
  1. *The last report omits the toolchain part's `did:` line.* The lab part's re-exec passes
     `--part lab --part infrahub --part fylgja` (`scripts/bring-up.sh`, line ~552), and the
     report loop prints a part's line only when the re-executed run's list names it (line
     ~866), so a run that re-executes prints three `did:` lines, against the contract's "one
     line per part run". The toolchain's counts travel in the re-exec's state; only the line
     is skipped. **Fixed after T031**: the re-exec's state also carries the parts the whole
     run runs (`parts=toolchain,lab,infrahub,fylgja`), and the report prints a line for
     each.
  2. *The privilege check prompts despite `NOPASSWD`.* On the VM `sudo -n -v` exits 1
     (`interactive authentication is required`) while `sudo -n true` exits 0: the user
     matches the `NOPASSWD: ALL` rule and also `%sudo ALL=(ALL:ALL) ALL`, and `-v` asks for a
     password unless every rule matching the user is `NOPASSWD` (sudo's `verifypw=all`). So
     the preamble's `sudo -v` prompted once, and the re-executed run, which starts its
     keep-alive loop only when `sudo -n -v` succeeds, ran without one; nothing after the
     groups needed sudo. **Fixed after T031**: the preamble prompts only when it must. A
     credential `sudo -n -v` accepts is kept alive with no prompt; else a user `sudo -n
     true` serves has nothing to keep alive and no prompt; else `sudo -v` prompts, once,
     and the loop keeps it. The contract's preamble item 3 says so.
  3. *`go: downloading` lines in the report.* `-prepare-main` runs by `go run`, which says
     its module downloads on stderr, and the part relays its output, so six `go: downloading
     …` lines appear under `bring-up: infrahub: main:` on a host with an empty module cache.
     CI's contract job showed none there. **Fixed after T031**: the relay drops them, and
     `local/bring-up-main.log` keeps them; a failure still relays the whole log.
  4. *The `go` item reads `installed` on 26.04, and always will.* It reads `present` only
     when the module cache holds the toolchain `go.mod` names (line ~442); 26.04's packaged
     Go is that release, so nothing is ever fetched. The item said `installed go1.26.0
     (fetched through go.mod)`, untrue here, and a second run would have said `installed`
     again, against T031's `installed 0`. **Fixed after the run**: the item reads `present
     <v> (Ubuntu's go, go.mod's release)` when Ubuntu's `go`, run outside the clone with
     `GOTOOLCHAIN=local`, is the release `go.mod` names. Its decision, run read-only on both
     hosts, picks that line on the VM and `present go1.26.0 (go.mod's, run by Ubuntu's go)`
     on the development host (Ubuntu's 1.22.2, the toolchain fetched), as before. A
     packaged Go newer than `go.mod`'s, which Ubuntu's updates may bring, is one Go runs as
     it is, and the item's check that `go version` in the clone was `go.mod`'s release
     would have failed the part on it. **Fixed after T031**: the item takes Ubuntu's `go`
     at `go.mod`'s release or a later one (`present <v> (Ubuntu's go, newer than go.mod's
     go1.26.0)`), and fails only on a `go version` in the clone that is neither.
  5. *The re-exec's line names both groups.* `lab: groups: docker clab_admins added;
     continuing in a fresh login session` is fixed text, while the groups item before it
     said `(docker added)`. **Fixed after T031**: the line names the groups the login
     session lacks, whichever run added them (`lab: groups: docker not in this session;
     continuing in a fresh login session`), and the contract's lab item says so.
  6. *sudo-rs ignores `-E`.* The lab part's `curl … containerlab.dev/setup | sudo -E bash -s
     install-docker` printed `sudo: preserving the entire environment is not supported, '-E'
     is ignored`, twice; the setup script installed Docker at its pin regardless. One
     warning is the lab part's `sudo -E`, the other the setup script's own `sudo -E curl`.
     **Fixed after T031**, the first: the lab part runs `sudo bash -s install-docker`, since
     the setup script reads none of the user's environment, and the classic sudo's `-E`
     would have handed it over; the setup script's own warning stays, and is harmless.
  7. *The Temporal CLI is not on the user's `PATH` after the run* (found at T030). The
     toolchain part installs it into `~/.temporalio/bin`, which its installer only
     suggests adding to `PATH`, and the contract puts it on the `PATH` of the processes the
     script starts alone; neither `~/.bashrc` nor `~/.profile` adds it, so a login shell
     has no `temporal`. The last report says `make test-e2e runs it`, but `scripts/e2e.sh`
     calls `temporal operator cluster health` from the `PATH` and stops at once with `e2e:
     FAILED: the workflow service is not answering at localhost:7233: start it with make
     temporal-dev`, while the dev server is `SERVING`; `make temporal-dev` would not find
     the command either. T030 ran with `PATH=$HOME/.temporalio/bin:$PATH` given on its
     command line. **Fixed after T030**, in the repository's two callers rather than the
     user's shell files: `scripts/e2e.sh` appends `~/.temporalio/bin` to its `PATH` before
     its preconditions, so a CLI on the `PATH` still wins, and refuses with `the Temporal
     CLI is neither on PATH nor in ~/.temporalio/bin, where scripts/bring-up.sh installs
     it` when there is none; `make temporal-dev` runs `$(TEMPORAL)`, the CLI on the `PATH`
     or else `~/.temporalio/bin/temporal`. Checked on the VM, whose login shell has no
     `temporal`: the fallback finds it and the dev server answers `SERVING`, and `make -n
     temporal-dev` names `~/.temporalio/bin/temporal`; on the development host, with no
     CLI in either place, `scripts/e2e.sh` stops on the new refusal, exit 1, before
     anything starts.

### 3.5 Recorded: CI's first run with the contract job, 2026-10-07

- **Run `37694132184`**: `ci` on the push of `5207aae` to `main` at 22:07:40Z, both jobs
  `success`, 8 min 41 s in all: the unit job 1 min 39 s (22:07:43–22:09:22Z), the contract
  job 6 min 55 s (22:09:25–22:16:20Z).
- **The runner**, as the script's first report gave it: Ubuntu 26.04.1 LTS, kernel
  `7.0.0-1012-azure`, 4 CPUs, 15,983 MiB, swap 3,071 MiB; `cEOS tar: not found; looked at
  --ceos-tar (none given), local/, <the clone's parent>; the repository root is never
  searched`; platforms `nokia_srlinux` alone; the memory `WARNING` (under 24,576 MiB) and the
  script going on.
- **`scripts/bring-up.sh --part infrahub`**: `DONE in 229s`, `did: infrahub: 1 present, 5
  installed, 0 skipped`, its lines in order: the Compose file and the override installed;
  Compose's pulls and start, 56 s (`7 services started`); `infrahub-server` healthy and
  `/api/info` answering `1.11.2` 86 s later; `schema loaded on main`, `group fylgja-devices
  created`, `repository fylgja created (… ref main, no credential)`, `import complete after
  22s`, `-prepare-main` 62 s in all; the seed 24 s (`fylgja-fixture, 3 artifacts Ready`).
  So the hosted runner holds Infrahub and reaches healthy inside a few minutes (R-06).
- **Then** `go generate ./... && git diff --exit-code` clean, and tier 2 in about 2 min 46 s
  (22:13:33–22:16:18Z), every package `ok`, the longest `internal/stage` 151 s,
  `internal/waypoint` 98 s and `internal/intent` 85 s.
- **Hygiene** (SC-007), by the operator over the job's log: the expected lines in order; no
  `INFRAHUB_` beside a UUID; no `FYLGJA_API_TOKEN=`; neither image's published default
  password, SR Linux's by value and EOS's by its shapes (no twin runs there, so no login is
  used). Actions secrets: `0`.
- **Peak memory**: the log does not show it (SC-004 asks for it only where it does).

### 3.6 Recorded: the second run on the VM, 2026-10-07

- **Before** (T031): the operator removed the passwordless-sudo file and moved the VM's
  clone to `013-launch` at `80020e8`, which carries the fixes of findings 4 and 7. The
  dev server, the worker and the API's server ran from the first run; Infrahub's eight
  containers had started between 22:39:37 and 22:41:47Z.
- **The run**, by the operator in a terminal multiplexer session: `cp local/.env
  /tmp/env.before; scripts/bring-up.sh 2>&1 | tee /tmp/bring-up2.out; cmp local/.env
  /tmp/env.before`, begun 23:43:30Z, ended `DONE in 68s`, exit 0. sudo prompted once, and
  nothing after it did (the prompt took a second try: `Authentication failed, try again`
  is sudo's own). `local/.env: kept`, and `cmp` found it byte-identical. `cEOS tar: not
  needed; ceos:4.32.0.2F is present`. No re-exec, so all four `did:` lines printed:

  ```
  bring-up: did: toolchain: 14 present, 0 installed, 0 skipped
  bring-up: did: lab: 5 present, 0 installed, 1 skipped
  bring-up: did: infrahub: 6 present, 0 installed, 0 skipped
  bring-up: did: fylgja: 1 present, 3 installed, 0 skipped
  ```

  The `go` item read `present go1.26.0 (Ubuntu's go, go.mod's release)` (finding 4's
  fix). The lab's skip is the cEOS item, `skipped (ceos:4.32.0.2F present; its layer is
  the recorded tar's)`, as the contract's lab item gives it. `-prepare-main` printed
  `present` twice and `import complete after 0s`. Infrahub's containers kept their first
  start times, each the same to the nanosecond.
- **The fylgja part's `3 installed` is the pull's.** `go build` stamps the commit into the
  binary (`go version -m bin/fylgja`: `vcs.revision=80020e8…`, `vcs.modified=false`), and
  the first run's was built at `5207aae`, so `make build` wrote a new binary (`build:
  installed`), and the worker and the server, on the replaced one, were restarted
  (`pid … runs a replaced binary; restarting it`, then `installed`), as the script should.
  At one commit a rebuild leaves the binary in place: T030's `make build` at `5207aae` did.
  A run on a tree no commit has moved since the last would read `fylgja: 4 present`; this
  one could not.
- **Finding 8: the second run's tiers are Go's cached results.** `make test` and `make
  test-contract` run `go test` without `-count=1`, so tier 1 took 17 s and tier 2 16 s:
  17 of tier 2's 21 packages printed `(cached)`, and only `internal/bundle`, `internal/lab`,
  `internal/psp` and `internal/tree` ran. Go's cache keys a test on its binary, the
  environment variables and the files it reads, never on what a service answers, so a
  cached tier 2 says nothing about the Infrahub in front of it, against the contract's
  "the tiers run again" and FR-013's "end with the tiers passing as a first run does".
  Tier 1 is pure, and its cache is sound. **Fixed after the run**, on the operator's word,
  where every caller meets it: `make test-contract` runs `go test -count=1 -tags contract`,
  so tier 2 runs against the Infrahub in front of it from the script, by hand, in the
  converge loop and in CI alike; `make test` keeps its cache.
- **Two more runs close T031**, on the VM's clone pulled to `6cabd94` (the Makefile's fix),
  each by the operator as before, `local/.env` byte-identical after each, exit 0, neither
  output carrying any prompt or sudo message:
  - *Run 3*, begun 23:51:24Z, `DONE in 439s`: toolchain 14 present, lab 5 present and 1
    skipped, infrahub 6 present, and `fylgja: 1 present, 3 installed`, the new commit's
    rebuild and the two restarts, as the pull made them. Tier 1 3 s (cached, as it may
    be), tier 2 417 s, run in full.
  - *Run 4*, begun 00:00:41Z on 2026-10-08, at the same commit, `DONE in 432s`:

    ```
    bring-up: did: toolchain: 14 present, 0 installed, 0 skipped
    bring-up: did: lab: 5 present, 0 installed, 1 skipped
    bring-up: did: infrahub: 6 present, 0 installed, 0 skipped
    bring-up: did: fylgja: 4 present, 0 installed, 0 skipped
    ```

    `build: present`, the dev server `present`, and the worker and the server `present`,
    each the same process as after run 3 and on this tree's `bin/fylgja`
    (`vcs.revision=6cabd94…`). Tier 1 2 s, every package cached; tier 2 420 s, none of its
    21 packages `(cached)`, every one `ok`, the longest `internal/stage` 415 s,
    `internal/intent` 239 s and `internal/waypoint` 216 s; `fylgja waypoint list` printed
    `no waypoints` afterwards. Infrahub's eight containers still carried their first start
    times, 22:39:37–22:41:47Z on 2026-10-07, through all three later runs.

  So a run on a host the script set up, at the commit it was set up from, changes nothing
  and installs nothing, keeps `local/.env` and the running Infrahub, and passes both tiers
  against that Infrahub (FR-013); the only item that is not `present` is the cEOS image's
  `skipped`, which the contract gives a present image.

### 3.7 Recorded: a pull request after the contract job, 2026-10-08

- **The pull request** (T036), by the operator: a throwaway branch `pr-check-2` made
  through the API at `013-launch`'s head (`6cabd94`, ahead of `main`), and pull request #2
  from it to `main`, opened 01:16:16Z.
- **`pull-requests.yml`** ran on `pull_request_target` (run `37712085675`), its one job
  `close` `success` in 10 s: one comment, by `github-actions`, at 01:16:26Z, `This
  repository is read-only: issues are welcome, pull requests are not taken (README,
  Contributing). Closing.`, and the pull request `CLOSED` at 01:16:27Z, 11 s after it
  opened.
- **`ci`** ran on `pull_request` (run `37712085629`, head `6cabd94`), `success`: the unit
  job `success` in 47 s (01:16:22–01:17:09Z), the contract job `skipped`, as its `if:
  github.event_name == 'push'` gives it. No pull request reaches the job that starts
  Infrahub.
- **The branch** was deleted afterwards by the operator; the API answers `Branch not
  found` (404) for it.
- **The badge**: the README's `ci` badge for `main` reads `ci - passing`, the last `ci` run
  on `main` being `37694132184` (the push of `5207aae`, both jobs `success`, §3.5); a
  pull request's run does not move it.

### 3.8 Recorded: SR Linux alone, on a fresh VM with no tar, 2026-10-08

- **The VM** (T043): the first VM, reinstalled by the operator: Ubuntu 26.04.1 LTS, kernel
  `7.0.0-38-generic`, 10 vCPUs, 31,065 MiB, 8 GiB swap, sudo-rs 0.2.13; no Docker,
  containerlab, Go, Temporal or `make`; no file named `cEOS*` anywhere on its disk. The
  user in `sudo` with passwordless sudo by a file under `/etc/sudoers.d/`, finding 2's
  configuration (`sudo -n true` exits 0, `sudo -n -v` exits 1).
- **The clone**: `git clone -b 013-launch https://github.com/happypathnetworking/fylgja.git`
  with no credential, at `6cabd94`, and this tree's `scripts/bring-up.sh` copied over it
  (sha256 `0b62c997…`), the fixes of findings 1, 2, 3, 4's newer Go, 5 and 6 not yet
  committed; `git status` showed that file alone modified.
- **Run 1**, begun 01:12:22Z in a terminal multiplexer session, `DONE in 1229s`, exit 0.
  Both reports said `cEOS tar: not found; looked at --ceos-tar (none given), local/, <the
  clone's parent>; the repository root is never searched` and `platforms: nokia_srlinux
  (arista_eos needs the cEOS tar: docs/development.md says where to get it)`; the last
  report's tier 3 line was `PLATFORMS=nokia_srlinux make test-e2e runs it on SR Linux
  alone`, and the worker and the server ran with `packages nokia_srlinux`. The cEOS item
  read `skipped (no cEOS tar: SR Linux alone)`. Tier 1 35 s, tier 2 420 s; the
  registration's import after 43 s. The `did:` lines: toolchain 6 present and 8
  installed, lab 5 installed and 1 skipped, infrahub 1 present and 5 installed, fylgja 4
  installed.
- **The fixes after T031, on a host for the first time**, all as designed: no prompt
  (nothing in the output, and the journal records no sudo authentication) on the host of
  finding 2; four `did:` lines after the re-exec (finding 1); `lab: groups: docker
  clab_admins not in this session; continuing in a fresh login session`, the session
  holding neither while the groups item said `(docker added)`, containerlab's package
  having put the user in `clab_admins` again (finding 5); no `go: downloading` line in
  the report (finding 3); `go: present go1.26.0 (Ubuntu's go, go.mod's release)`
  (finding 4); one `'-E' is ignored`, the setup script's own, where the first VM had two
  (finding 6).
- **Hygiene**: the greps of quickstart §3 for the six values of `local/.env` (both
  tokens, the SR Linux password, the Compose block's password, agent token and secret
  key) over `/tmp/bring-up1.out`, `local/*.log`, `bin/`, `.venv/` and `local/infrahub/`: 0
  files each.
- **`make test-e2e`**, default: `e2e: FAILED: image ceos:4.32.0.2F is absent: import it as
  docs/development.md says; it is never pulled`, `scripts/e2e.sh` exit 1 (make's own 2),
  before any case; no twin, no image.
- **`PLATFORMS=acme_os make test-e2e`**: `e2e: FAILED: PLATFORMS names acme_os, which no
  shipped package has; known: arista_eos nokia_srlinux`, exit 1 (make's 2).
- **`PLATFORMS=nokia_srlinux make test-e2e`**, detached, begun 01:33:52Z with 24,622 MiB
  available: `E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7; skipped 6 (needs
  arista_eos: not in PLATFORMS; image ceos:4.32.0.2F absent) 8 (needs arista_eos: not in
  PLATFORMS; image ceos:4.32.0.2F absent)`, exit 0, wall time 736.0 s (12.3 min): creates
  38.9–54.0 s, `twin verify` 3.2 s and 3.1 s, the boot half 8.7 s. Afterwards `clab
  inspect --all` found no containers, `local/twin` was absent and `fylgja waypoint list`
  printed `no waypoints`. Each skip says both reasons, as US3's scenario 4 asks of an SR
  Linux-only host.
- **The tar in the clone's root alone**: the recorded tar (sha256 `89a567d5…`) copied to
  `<the clone>/cEOS-lab-4.32.0.2F.tar`, then run 2 from a fresh login, begun 01:46:45Z,
  `DONE in 449s`, exit 0: both reports again `cEOS tar: not found; looked at …; the
  repository root is never searched`, the platforms `nokia_srlinux` alone. It was a
  second run too, and changed nothing: `local/.env: kept`, toolchain 14 present, lab 5
  present and 1 skipped, infrahub 6 present, fylgja 4 present, `installed 0` on every
  part; tier 1 16 s, tier 2 422 s, run in full. The tar was removed afterwards.
- **A file of random bytes** (1,000 bytes) as `local/cEOS-lab-4.32.0.2F.tar`: the script's
  one line was `bring-up: REFUSED: <the clone>/local/cEOS-lab-4.32.0.2F.tar: sha256
  e8aff2a3c1edbbe2c18966e9d9c25d9a8590a8ccead6758d4483d55acea303f9 does not match the
  recorded 89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778; nothing was
  imported`, exit 2, before any part and before the first report; `docker images` and
  `local/.env` were the same before and after. The file was removed, and no `cEOS*` file
  remains on the VM.
- So SC-003 holds: without the tar the script names SR Linux alone in both reports and
  passes tiers 1 and 2, tier 3 narrowed to `nokia_srlinux` ends on the partial pass, and
  a tar in the repository root is not found.

### 3.9 Recorded: the platform list on the development host, 2026-10-08

- **The host**: the development host (Ubuntu 24.04.1), both images present
  (`ceos:4.32.0.2F` and `ghcr.io/nokia/srlinux:24.7.1`). `make build` replaced the
  binary, so the worker and the API's server were restarted from this tree and verified:
  each on `bin/fylgja` not `(deleted)`, each environment carrying `INFRAHUB_*`, both
  logins, `FYLGJA_STATE_ROOT` and `FYLGJA_API_TOKEN`, each report naming `arista_eos` and
  `nokia_srlinux` with their logins set, the server `listening on 127.0.0.1:7650 (API
  version 1, build 0.1.0-dev)`. Before the first run: no twin, no lab, `no waypoints`.
- **`PLATFORMS=nokia_srlinux make test-e2e`** (T041; US3 scenario 5), detached, begun
  02:12:47Z on a quiet host (no test or twin running, 20,888 MiB available, load 1.3):
  `E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7; skipped 6 (needs arista_eos: not
  in PLATFORMS) 8 (needs arista_eos: not in PLATFORMS)`, exit 0, the contract's line to the
  character; the script's wall time 730.5 s (12.2 min; 732 s with make's build), case 1
  deploying `b9d53ebc8d8187ccc73623cd9be2740fb865ff101edc58c0e732735d4fd9d668`, creates
  43.4–53.9 s, `twin verify` 3.9 s and 4.1 s, the boot half 9.2 s. With both images
  present each skip names the list alone: the list selects by package, never by image.
  Afterwards `clab inspect --all` found no containers, `local/twin` was absent and
  `fylgja waypoint list` printed `no waypoints`.
- **`PLATFORMS=nokia_srlinux,arista_eos make test-e2e`** (T042; US3 scenario 7), after the
  host rested (the five-minute load back under 2), begun 02:33:47Z with 20,882 MiB
  available, load 1.1: `E2E-OK`, exit 0, eight cases, none skipped, case 1 deploying
  `b9d53ebc…`; the script's wall time 1075.4 s (17.9 min; 1081 s with make's build),
  creates 42.4–72.0 s (the mixed twins of cases 6 and 8 the longest), `twin verify`
  3.0–4.7 s, case 8's steps 83.9 s and 71.0 s and their waits settled after 4.2 s and
  3.8 s, the boot half 10.2 s and 7.2 s. A list naming every shipped package on a host
  with every image ran as a default run. Afterwards the host was clean as after T041.
- So the platform list holds on a host with both images: narrowed, it skips cases 6 and 8
  for the list alone and ends on the partial pass in two-thirds of a full run's time;
  whole, it is a default run.

### 3.10 Recorded: the recording, 2026-10-08

- **The tools**: asciinema `3.2.1` and agg `1.9.0`, the `x86_64-unknown-linux-gnu`
  binaries of their GitHub releases, installed by hand into `~/.local/bin` (sha256
  `1b405bbd…` and `f111e315…`). asciinema 3.2.1 has no `--cols` or `--rows`: its size is
  `--window-size 100x30`, and it was run `--headless` with the session as its
  `--command`, a short bash script that types each command after a prompt and then runs
  it. The cast's header carries that script verbatim, so it says how it was driven.
- **Off camera**: `fylgja-test-readme` seeded and its waypoints written as the stepping
  walk-through does (the delete, the seed, `/1` "seeded", `-add-link`, a wait until n1's
  and n3's checksums moved with every artifact Ready, `/2` "third link").
- **The take that was kept** is the second. The first ran on the state root `local/`, so
  its create printed the twin directory under the operator's home: a local path in a
  frame (SC-008). The twin was destroyed, the worker and the server restarted on the
  README's state root `/var/tmp/fylgja` (each on `bin/fylgja`, not `(deleted)`, with every
  credential's name set), and the session recorded again. The shell held
  `FYLGJA_API_TOKEN` alone: `local/.env` loaded, then every variable but `HOME`, `PATH`,
  `TERM`, `LANG` and the token unset, so no credential was in any process's arguments.
- **The session**: `twin create --waypoint fylgja-test-readme/1` deploying `2e2dd93b…` in
  38.8 s, `twin step` to `/2` (`02b79569…`; n1 and n3 pushed, n2 untouched, settled after
  4.7 s) in 4.6 s, `twin verify` holding 19 assertions over 3 nodes, nothing failed or
  unread; 77 s recorded. `agg --idle-time-limit 2 --fps-cap 15 --font-size 14` rendered
  it to 87 frames, 860×608, 37 s of play, 1.19 MB (the cast 7.3 KB).
- **Off camera after**: `twin destroy`, `fylgja-fixture -branch fylgja-test-readme
  -delete` (2 test waypoints and the branch), the worker and the server restarted on
  `local/` and verified, `fylgja waypoint list` printing `no waypoints`, no lab.
- **Hygiene**: a fixed-string grep of the cast, the GIF and the cast's text for the API's
  token, Infrahub's token, both node passwords and Infrahub's admin password found
  nothing; the cast names no path under a home directory or the scratchpad.

### 3.11 Recorded: the five Infrahub behaviours, 2026-10-08

Each was taken through the `infrahub-reporting-issues` skill until the operator's word, and
all five were **dropped**. Nothing was posted. `opsmill/infrahub` has Discussions turned
off, so R-11's "discussion" was not available there.

| # | Behaviour | What the search found | Outcome |
|---|---|---|---|
| 1 | No artifact regenerates on its own; nothing marks one stale | Open docs PR #10437 documents both as the design. No issue asks for a staleness or in-flight signal; a feature request was drafted | dropped |
| 2 | `?branch=` on `POST /graphql` is ignored | Exact duplicate #10686, closed as completed on 09-28 with no linked change. The GraphQL app on `stable` and `develop` still reads the branch from the path alone, and the 1.11.3 and 1.11.4 notes don't mention it; a comment asking for the fix's release was drafted | dropped |
| 3 | An attribute name is 3–64 characters | The schema reference at 1.11.2 documents `Length: min 3, max 64` | dropped |
| 4 | `BranchCreate` straight after `BranchDelete` can fail `graphql: None` | No issue. Same cause as open PR #10694 (the delete's side); a comment on it was drafted | dropped |
| 5 | The SDL's field order is not stable | Not searched | dropped |

**Behaviour 4, reproduced on the running 1.11.2.** `fylgja-test-recreate` was created,
deleted and re-created at once, six rounds of two re-creates. 2 of 12 re-creates answered
`"message": "None"`, `UNDEFINED_ERROR`, `http_status: 500`, and each time the branch had
been created. The server log shows the create mutation (`graphql/mutations/branch.py:118`
→ `execute_workflow`) getting `404 Flow run not found` on its own flow run, then
`ObjectNotFound: None`. The task worker meanwhile logged `Purge tasks for deleted branch
'fylgja-test-recreate'`, purging 4–15 runs each time. The purge (#10479, in 1.11.2) picks
runs by the branch's name tag and starts about a second after a delete, so it takes a
same-named branch's create run as well. Afterwards Infrahub held `main` and
`fylgja-fixture` alone.

---

## 4. Owed to the records at the close

development.md (the walk-through as the script's record; the Compose files' new place;
CI's two jobs and the badge; the registration and the `ref` answer; `PLATFORMS`; the
corrected tar name), verified-facts.md (§3, each with `26.04` and the date; the filed
issues' links), glossary (*platform list*, *partial pass*, *Infrahub part*, *recording*,
*write-up*; *Bring-up script* no longer "not yet built"; *Launch* says public at the
start, not the close; *Development host* on 26.04), roadmap (Built table, Next), `CLAUDE.md`
(State rewritten whole, Environment for 26.04 and the venv), README (What it needs,
Tests, the badge, the recording, the SR Linux-only host), `docs/ideas.md` (a persistent
waypoint series on the fixture branch, the idea the spec parks).

---

## 5. The write-up's figures

Every figure below is **derived from the private record** of M1–M13 and the cut, read in
one session on the development host on 2026-10-08 (R-09), at a location the operator gave
in that session. The record was read by a script that printed numbers alone. Nothing of the
record is quoted here, and the figures were read by the operator before this section was
committed. The launch, built here, is not in them.

**How each was counted.**

- **A feature** is one Spec Kit feature. There is one per milestone: M1–M7, M10–M13 and
  M14's first half, the cut. That makes 12.
- **Hours** are the command log's active time: each logged command's time working, the
  command and its follow-ups together, with every wait on the operator left out. Wall
  clock and the operator's own hours are not in the record and are not claimed. A
  milestone's hours sum its feature's commands. Each figure is rounded on its own, to a
  tenth of an hour.
- **A pass** is one logged Spec Kit command, and a **convergence pass** is one
  `/speckit-converge` run. All 309 logged commands are Spec Kit passes. The constitution
  was ratified once before M1 and amended once in M1, and both runs count as passes. The
  record holds two `specify` passes each for M2 and M11 and none for M13; they are counted
  as the record holds them.
- **Tasks appended** are the tasks each convergence pass recorded adding to its feature's
  task list. The log of M1 and M2 predates that field, so their count is not recorded. M14
  ran no convergence pass.
- **`[behaviour]` and `[pin]`** count the tasks that carry the tag in their feature's task
  list. A `[behaviour]` task changes what the code does. A `[pin]` task changes no
  behaviour: it adds a test, a doc line or a named constant, with the code under test
  unchanged. Two passes in a row that append only `[pin]` tasks end convergence
  (development.md, "Stopping rule for converge"). The tags begin at M10, and before it the
  column is empty (—).
- **Model time** is active time by model. 7 of the 309 commands ran on two models, and
  each of those is split by the share of its responses from each model. The harness's own
  responses, which carry no model, account for under 0.02 h; it stays in the hours alone.
  Subagents run inside a command's time and add none of their own. So Sonnet 5.5 and
  Haiku 4.5, which ran only as subagents, appear in tokens alone.
- **Tokens** are by model, the main session's and its subagents' together. They are given
  in millions as *input / output*. Input counts uncached input, cache writes and cache
  reads together, and cache reads are most of it.
- **Totals.** Tasks are every task in the 12 features' task lists. Commits are the private
  history's commit count, through the cut. Decisions are the entries in the decision log
  at the cut, D-001–D-044. Verified facts are the top-level entries in the verified-facts
  record at the cut (this repository's holds 82 now, the launch's two added since).

**Per milestone: hours, passes and model time.**

| Milestone | Hours | Passes | Convergence passes | Tasks appended | `[behaviour]` | `[pin]` | Fable 5.1 h | Opus 5 h | Opus 5.5 h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| M1 | 2.9 | 17 | 3 | not recorded | — | — | 0.8 | 2.1 | — |
| M2 | 7.7 | 34 | 11 | not recorded | — | — | 2.2 | 5.5 | — |
| M3 | 2.4 | 11 | 1 | 0 | — | — | 0.5 | 1.9 | — |
| M4 | 7.0 | 34 | 12 | 18 | — | — | 0.5 | 6.5 | — |
| M5 | 5.3 | 25 | 8 | 14 | — | — | 2.3 | 3.0 | — |
| M6 | 3.8 | 17 | 3 | 6 | — | — | 1.1 | 2.7 | — |
| M7 | 11.2 | 20 | 3 | 10 | — | — | 2.4 | 8.7 | — |
| M10 | 6.3 | 21 | 5 | 12 | 3 | 7 | 1.7 | — | 4.6 |
| M11 | 13.4 | 46 | 13 | 63 | 6 | 54 | 1.3 | — | 12.1 |
| M12 | 7.8 | 25 | 5 | 25 | 8 | 15 | 0.9 | — | 6.9 |
| M13 | 12.4 | 39 | 8 | 51 | 21 | 19 | 0.8 | — | 11.6 |
| M14 (the cut) | 4.8 | 19 | 0 | 0 | — | — | 1.1 | — | 3.7 |
| before M1 | 0.4 | 1 | — | — | — | — | 0.4 | — | — |
| **all** | **85.4** | **309** | **72** | **199** | **38** | **95** | **16.1** | **30.6** | **38.8** |

Opus 5 ran through M7, and Opus 5.5 ran from M10 on.

**Passes by command, all milestones.**

| Pass | specify | clarify | plan | tasks | analyze | implement | converge | constitution | all |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Count | 13 | 13 | 12 | 12 | 16 | 169 | 72 | 2 | 309 |

**Tokens by model, in millions, input / output.**

| Milestone | Fable 5.1 | Opus 5 | Opus 5.5 | Sonnet 5.5 | Haiku 4.5 |
|---|--:|--:|--:|--:|--:|
| M1 | 16.2 / 0.22 | 115.8 / 0.46 | — | — | — |
| M2 | 53.4 / 0.64 | 139.6 / 1.52 | — | — | — |
| M3 | 5.7 / 0.14 | 46.1 / 0.34 | — | — | — |
| M4 | 4.5 / 0.11 | 204.8 / 1.26 | — | — | — |
| M5 | 58.3 / 0.52 | 182.7 / 0.71 | — | — | — |
| M6 | 20.0 / 0.30 | 174.6 / 0.82 | — | — | — |
| M7 | 31.6 / 0.33 | 350.2 / 1.13 | — | — | — |
| M10 | 23.9 / 0.26 | — | 256.0 / 1.09 | — | — |
| M11 | 25.6 / 0.34 | — | 671.4 / 2.47 | 38.6 / 0.00 | — |
| M12 | 17.8 / 0.24 | — | 371.1 / 1.39 | — | — |
| M13 | 37.3 / 0.25 | — | 694.1 / 2.30 | — | — |
| M14 (the cut) | 20.5 / 0.26 | — | 240.3 / 1.05 | 4.5 / 0.01 | 27.1 / 0.07 |
| before M1 | 36.9 / 0.10 | — | — | — | — |
| **all** | 351.6 / 3.70 | 1,213.9 / 6.23 | 2,233.0 / 8.30 | 43.1 / 0.01 | 27.1 / 0.07 |

**Totals.**

| Features | Tasks | Commits | Decisions | Verified facts |
|--:|--:|--:|--:|--:|
| 12 | 947 | 809 | 44 | 80 |
