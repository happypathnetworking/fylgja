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

Empty until the one session that reads the private record (R-09); each figure stated
as derived from it and read by the operator before this section is committed.
