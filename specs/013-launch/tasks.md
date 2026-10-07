# Tasks: The launch

**Input**: Design documents from `/specs/013-launch/`: [plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md); constitution 1.1.1.

**Tests**: no new test files. The spec proves the script by running it (on the development
host's refusal, on a fresh Ubuntu 26.04 VM, and in CI's contract job), the fixture tool's
flag by the registrations it makes, and the platform list by narrowed tier-3 runs. Tiers 1
and 2 are unchanged and must pass with no golden re-baselined (SC-012); `shellcheck` joins
the unit job.

**Organization**: phases follow the operator's order (spec, Assumptions; plan, "Order of
the work"), not the stories' priority order. US1 (P1) comes first because every later
registration needs a public repository, and FR-030 puts the flip before the script, CI
and the registration are built, so the foundational fixture-tool work follows US1 rather
than preceding it. US5 (P2) precedes US2 (P1) because the development host's registration
is the first use of `-prepare-main` and proves it before the script and CI depend on it.

**Tags**: `[operator]` marks a task that needs the operator: an outward-facing act
(FR-037), a decision, the fresh VM, or a session the operator must attend. `[live]` marks a
task that needs the development host's twins (tier 3, a quiet host). Unattended, the loop
stops at both. Commits are by hand, conventional, with a body saying why, and end with the
model's `Co-Authored-By` trailer (FR-042); a session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US7, from spec.md

---

## Phase 1: Setup (the baseline)

**Purpose**: record that the cut's gates pass on this branch before anything changes, so
any later failure is this feature's.

- [X] T001 Run the pure gates from the repository root and confirm each passes: `make build`; `file bin/fylgja` reports a statically linked executable; `make test`; `make lint`; `go vet -tags contract,fixture,e2e ./...`. Confirm `git diff --stat main -- testdata/golden` is empty. Write nothing; report the results.

---

## Phase 2: User Story 1 — The repository goes public first (Priority: P1) 🎯 MVP

**Goal**: the tree carries `SECURITY.md`, the pull-request workflow and no citation of the
private record; the operator flips the repository to public and sets `main`'s ruleset, private
vulnerability reporting and the topics in one sitting.

**Independent Test**: a shell with no GitHub credential clones over HTTPS and reads
`README.md`, `LICENSE` and `SECURITY.md`; a pull request is closed with the Contributing
comment; `gh api repos/happypathnetworking/fylgja/rulesets --jq '.[].name'` lists `main`;
the read of the tree (quickstart §1) finds nothing private.

- [X] T002 [P] [US1] Write `SECURITY.md` at the repository root (FR-031). Read `docs/architecture.md` §4.6 and §5, [D-042](../../docs/decisions.md#d-042) and `contracts/api.md` first, and state only what they say: the API is one bearer token (`FYLGJA_API_TOKEN`) sent in the clear over HTTP; `fylgja serve` listens on `127.0.0.1:7650` unless `--listen` says otherwise, and a client on another machine comes through `ssh -N -L 7650:127.0.0.1:7650 <lab host>`; the server and the worker hold Infrahub's token and both node logins in their environment, and `local/.env` (mode `0600`) is the one file holding a value; what a reader on a shared host should know (any local user can reach the loopback port but needs the token; anyone who can read the user's processes' environment or `local/.env` has every credential; the twin's nodes use their images' published default logins and are reachable from the host's management network; Infrahub's published Compose binds port 8000 on every interface). Then how to report: GitHub's private vulnerability reporting (the repository's Security tab, "Report a vulnerability"), what is in scope (the binary, the scripts, the workflows), and what is not (the images' published default logins; Infrahub, containerlab and Temporal themselves, reported to their projects). No credential value, no private path.
- [X] T003 [P] [US1] Create `.github/workflows/pull-requests.yml` as [contracts/ci-and-release.md](contracts/ci-and-release.md) gives it: `on: pull_request_target: types: [opened, reopened]`, `permissions: pull-requests: write`, one job `close` on `ubuntu-26.04` with no checkout, whose step runs `gh pr comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "This repository is read-only: issues are welcome, pull requests are not taken (README, Contributing). Closing."` then `gh pr close "$NUMBER" --repo "$GITHUB_REPOSITORY"`, with `env: GH_TOKEN: ${{ github.token }}` and `NUMBER: ${{ github.event.pull_request.number }}`. A header comment says why `pull_request_target` is safe here (no checkout, no fork code, no secret but the job's token) and that it is the repository's one use of it. Check that the comment's wording agrees with `README.md`'s Contributing section and adjust the comment, not the README.
- [X] T004 [P] [US1] Scrub the private-record citations from the `description` strings of `contracts/api.schema.json`, `contracts/findings.schema.json`, `contracts/manifest.schema.json`, `contracts/psp.schema.json` and `psp/psp.schema.json` (research R-14, §2.11): rewrite each sentence that cites a `specs/0NN-…` path, an `FR-0NN` number or a `research R…` run so that it states what the format version changed, with no path, number or run. Change no other key: a description changes no validation. Make the identical edit to `psp/psp.schema.json` and `contracts/psp.schema.json` so that `TestShippedSchemaIsTheContractSchema` (`internal/psp/contract_test.go`) still holds.
- [X] T005 [P] [US1] Scrub the same citations from every frozen copy under `internal/{cli,findings,provision,server}/testdata/contracts/*/` (the `findings.schema.json` copies, `001-read-compile/findings.schema.json` and `internal/findings/testdata/contracts/008-waypoints/waypoints.schema.json`), editing every copy of one file identically so that `TestFrozenContractCopiesAgree` (`internal/findings/frozen_contracts_test.go`) holds them byte-equal. Keep the directory names (`004-walking/` and the rest): they are the public convention development.md documents (research R-14). Run `go test ./internal/findings/ ./internal/psp/ -count=1` after.
- [X] T006 [P] [US1] Correct the *Launch* entry in `docs/glossary.md` (line ~402): the repository goes public at the launch's start, before the script and CI are built, not at its close ([D-043](../../docs/decisions.md#d-043), FR-030).
- [X] T007 [US1] Read the tree once more (FR-030, SC-008; quickstart §1), this branch's work included: run `grep -rnE 'specs/0(0[1-9]|1[0-2])-|research R[0-9]|/home/[a-z]+/|\bT0[0-9]{2}\b' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=local --exclude-dir=bin . | grep -v '^./specs/013-launch/'`, expecting only Spec Kit's own example path in `.claude/skills/speckit-specify/SKILL.md`; then, from a shell that has loaded `local/.env`, `grep -rlF -- "$INFRAHUB_API_TOKEN"` and the same for `FYLGJA_API_TOKEN` over the tree (same exclusions), expecting nothing, never printing a value. Read `specs/013-launch/*` for anything private (a host's process id, a local path, a quotation of the private record) and fix any hit. Depends on T002–T006. Then run `make test` and confirm no golden moved.
- [X] T008 [operator] [US1] The operator commits T002–T007, merges `013-launch` to `main` and pushes `origin` (data-model §10, "before the flip"). A session prepares the commits only on the operator's word and never pushes.
- [X] T009 [operator] [US1] In one sitting, by the operator or with the operator's word in the session ([contracts/ci-and-release.md](contracts/ci-and-release.md), "The ruleset" and "The other settings"): `gh repo edit --visibility public --accept-visibility-change-consequences`; immediately after, the ruleset `main` (`deletion`, `non_fast_forward`, `bypass_actors: []`) by `gh api -X POST repos/happypathnetworking/fylgja/rulesets --input <file in the scratchpad>`; `gh api -X PUT repos/happypathnetworking/fylgja/private-vulnerability-reporting`; `gh repo edit --enable-projects=false --enable-wiki=false`; `gh repo edit --add-topic infrahub,containerlab,digital-twin,network-automation,temporal,srlinux,arista-eos,go`.
- [X] T010 [operator] [US1] Check the public view (US1 scenarios 2–3): `gh repo view --json visibility,repositoryTopics,hasIssuesEnabled`; `gh api repos/happypathnetworking/fylgja/rulesets --jq '.[].name'` lists `main`; in an empty directory under the scratchpad, `env -u GH_TOKEN GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone https://github.com/happypathnetworking/fylgja.git` succeeds and holds `README.md`, `LICENSE`, `SECURITY.md`; the operator opens one pull request from a throwaway branch and sees it commented and closed by `pull-requests.yml`, then deletes the branch. Record the date of the flip and each answer in `specs/013-launch/research.md` §3.

**Checkpoint**: the repository is public; every registration from here on is credential-less.

---

## Phase 3: Foundational — the fixture tool prepares `main` (blocks US5, US2, US4)

**Purpose**: `fylgja-fixture -prepare-main` ([contracts/fixture-prepare-main.md](contracts/fixture-prepare-main.md);
research R-03) loads the schema on `main`, creates the group, registers this repository
read-only with no credential and awaits the import. The development host (US5), the
script's Infrahub part (US2) and CI's contract job (US4) all call it. Built after the flip
(FR-030).

**⚠️ CRITICAL**: US5, US2's Infrahub part and US4's contract job need this phase.

- [ ] T011 Create `internal/testsupport/main.go` (build tag `//go:build contract || fixture`, package `testsupport`), in `infrahub.go`'s style, using `Client.GraphQL`, `Client.create` and `Client.redact`: constants `RepositoryName = "fylgja"`, `RepositoryLocation = "https://github.com/happypathnetworking/fylgja.git"`, `RepositoryRef = "main"`, and the three names `.infrahub.yml` declares (query `device_config`, transform `srlinux_device_config`, definition `srlinux_device_config` with artifact `device-config`); `func (c *Client) EnsureGroup(name string) (created bool, err error)`, which counts `CoreStandardGroup` named `name` on `main` and creates it (`CoreStandardGroupCreate`, `name` and `label`) when absent, erroring on more than one; `func (c *Client) EnsureReadOnlyRepository(name, location, ref string) (created bool, err error)`, which looks up `CoreGenericRepository` by name on `main` and, when absent, runs `CoreReadOnlyRepositoryCreate` with `name`, `location`, `ref` and a `description` naming D-044 and **no `credential`**; when present with another `location` or `ref` it returns `repository <name> is registered at <location> on <ref>, not <wanted>; remove it or name another with -repository-name` and changes nothing; `func (c *Client) AwaitImport(name string, wait time.Duration) (took time.Duration, err error)`, polling once a second until the repository's `internal_status` is `active`, its `operational_status` is `online`, and `main` holds the query, the transform and the definition (with `artifact_name` `device-config`), each found by name exactly once; on expiry it returns `main did not hold <the missing ones> within <wait>; the repository is <internal_status>/<operational_status>; a git_repositories_sync run stuck PENDING in Infrahub's task manager blocks every import until it is cancelled`. Verify each field name against `schema/infrahub.graphql` before using it (research §2.5 lists them). No error carries the token.
- [ ] T012 In `internal/testsupport/infrahub.go`, reword the refusal in `lookupByName` (line ~252) and `groupMemberCount` (line ~453) to the contract's text: `branch %s holds %d %s named %q, want one; register this repository (github.com/happypathnetworking/fylgja) on main as a read-only repository with no credential and wait for its import (docs/development.md, "What Infrahub needs"); a branch created before the import cannot see it` (FR-028), and fix `ArtifactDefinitionName`'s comment (line ~229), which names the `fylgja-artifacts` repository. Then `grep -rn 'fylgja-artifacts' --include='*.go' --include='*.sh' --include='*.md' .` and change any test tooling or document that still names the private copy as the registration, except the template's own text `rendered by Infrahub (fylgja-artifacts)` in `infrahub/` and the goldens, which is the template's bytes and does not change (D-044, research R-14); documents beyond `docs/development.md`'s fixture lines are left to T050–T057.
- [ ] T013 In `cmd/fylgja-fixture/main.go`, add `-prepare-main` with `-repository-name` (default `testsupport.RepositoryName`), `-repository-location` (default `testsupport.RepositoryLocation`), `-repository-ref` (default `testsupport.RepositoryRef`) and `-wait` (a `time.Duration`, default `300s`), reusing `-schema-dir`. Before any request: refuse a `-branch` given on the command line (detect it with `flag.Visit`) with `-prepare-main takes no -branch: it prepares main`, and refuse any other action flag beside it; refuse the four new flags without `-prepare-main`. Steps, printing exactly the contract's lines on stdout: `LoadSchema("main", schemaDir)` → `schema loaded on main`; `EnsureGroup(testsupport.ArtifactGroupName)` → `group fylgja-devices present` | `created`; `EnsureReadOnlyRepository` → `repository fylgja present (location …, ref main)` | `created (location …, ref main, no credential)`; `AwaitImport` → `import complete after <s>s: query, transform and definition on main`. Every failure exits 1 as `fylgja-fixture: <message>` on stderr, as the tool's other flags do. Add `-prepare-main` to the fixture tool's description in `docs/development.md` (the `make infrahub-seed` / `infrahub-clean` row of "Build and make targets") in one sentence: what it writes, that it acts on `main` alone, and that a second run writes nothing.
- [ ] T014 Gate the phase: `make build`, `make test`, `make lint`, `go vet -tags contract,fixture,e2e ./...`; then, with no Infrahub variables in the environment, `go run -tags fixture ./cmd/fylgja-fixture -prepare-main -branch x` exits 1 with the `-branch` refusal and `go run -tags fixture ./cmd/fylgja-fixture -repository-ref main` exits 1, both before any request. Depends on T011–T013.

**Checkpoint**: `-prepare-main` builds, lints and refuses offline; its first live run is US5's.

---

## Phase 4: User Story 5 — Infrahub renders from this repository (Priority: P2)

**Goal**: the development host's Infrahub registers this repository read-only on `main`
with no credential, the private copy is gone, the fixture still compiles to `b9d53ebc…`,
tiers 2 and 3 pass, and the `ref` question has one recorded answer (research R-15;
quickstart §2).

**Independent Test**: `CoreGenericRepository` on `main` holds `fylgja` alone (read-only,
`ref main`, no credential, `active`, `online`); `make infrahub-seed` passes; the live fixture
compiles to `b9d53ebc…`; `make test-contract` and `make test-e2e` pass.

- [ ] T015 [operator] [US5] With the operator's word in the session and `local/.env` loaded: record into `specs/013-launch/research.md` §3 the ids of `CoreGraphQLQuery device_config`, `CoreTransformJinja2 srlinux_device_config` and `CoreArtifactDefinition srlinux_device_config` on `main` and their repository; then delete the private copy by GraphQL on `main` (`CoreRepositoryDelete` of `fylgja-artifacts`, then `CorePasswordCredentialDelete` of its credential), sending the token as a header file as `scripts/e2e.sh`'s `gql` does; record whether the query, the transform and the definition survive the delete (R-15's first question).
- [ ] T016 [operator] [US5] Run `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` against the development host's Infrahub; record in research.md §3 its output, the time to `active`, `online` and the import, whether the three objects now name `fylgja` as their repository, and whether their ids moved (R-15's second question). Confirm `CoreGenericRepository` on `main` lists `fylgja` alone, with no credential. Run it a second time and confirm it prints `present` twice and writes nothing (contract, Idempotence). A failure here is a defect in T011–T013, fixed before going on.
- [ ] T017 [live] [US5] `make infrahub-clean && make infrahub-seed` (run the seed again once on `graphql: None`); `make build`, then restart the worker and the API's server from this tree as `CLAUDE.md` says and verify both (`/proc/<pid>/exe` not `(deleted)`, both packages in their reports); `bin/fylgja intent read --branch fylgja-fixture --out <scratchpad>/f.json && bin/fylgja twin compile --ctm <scratchpad>/f.json --out <scratchpad>/f` prints `bundle_id b9d53ebc…`; then `make test-contract` passes. Record each result in research.md §3.
- [ ] T018 [live] [US5] On a quiet host (`free -m` first; no tier 2 running): `make test-e2e`, started detached with its exit status in `local/converge-e2e.out` and waited on in foreground calls of under ten minutes; it ends `E2E-OK`, eight cases, case 1 deploying `b9d53ebc…`. Record the wall time in research.md §3.
- [ ] T019 [operator] [US5] The `ref` question (FR-029; R-15): after the operator pushes a new commit to `main`, read the registration's `commit`, then try in turn the minute sync on its own (wait three minutes), `CoreReadOnlyRepositoryUpdate` of `ref` (set to `main` again), and `InfrahubReadOnlyRepositoryImportLastCommit`; record which moves `commit` in research.md §3 with Infrahub 1.11.2 and the date; then add it to `docs/verified-facts.md`'s Infrahub 1.11.2 section with the version and date, and say in `docs/development.md`'s "What Infrahub needs" how a template change reaches Infrahub (the way that worked, or a documented re-registration if none did) and that the registration is `fylgja`, read-only, on `main`, made by `-prepare-main`.

**Checkpoint**: D-044 executed on the development host; `-prepare-main` proved live.

---

## Phase 5: User Story 2 — A stranger stands Fylgja up with one script (Priority: P1)

**Goal**: `scripts/bring-up.sh` takes a fresh Ubuntu 26.04 host through the preamble and four
parts to tiers 1 and 2 passing and the three processes running
([contracts/bring-up-script.md](contracts/bring-up-script.md); data-model §1–§2; research
R-01, R-02, R-04, R-05, R-12).

**Independent Test**: on a fresh 26.04 VM with the tar in the clone's parent directory, one run
ends exit 0 with tiers 1 and 2 passed and the worker's and the server's reports naming both
packages; `make test-e2e` then ends `E2E-OK`; a second run changes nothing.

- [ ] T020 [P] [US2] Create `scripts/infrahub/docker-compose.override.yml` from the development host's `~/projects/infrahub-dev/docker-compose.override.yml`: the same `services` (`task-manager`, `infrahub-server`, `task-worker` on `registry.opsmill.io/opsmill/infrahub:1.11.2`; `database` with `NEO4J_server_memory_heap_initial__size: 1g`, `NEO4J_server_memory_heap_max__size: 2g`, `NEO4J_server_memory_pagecache_size: 1g`), with the header comment rewritten to state the facts alone and cite nothing (research R-04): the file sits beside the Compose file fetched from `https://infrahub.opsmill.io/1.11.2` under `local/infrahub/`, which it leaves untouched; the pin is kept although the URL is versioned, because a stray `VERSION` in the environment would move the image; uncapped, Neo4j's JVM grew into the headroom a twin needs and a tier-3 run died of memory (verified-facts, The host). No private path, task number or run.
- [ ] T021 [P] [US2] Add the Compose block to `.env.example`, after the existing names, in its comment style and with no value: `COMPOSE_PROJECT_NAME` (`fylgja-infrahub`), `INFRAHUB_INITIAL_ADMIN_TOKEN` (a UUID; `INFRAHUB_API_TOKEN` carries the same value), `INFRAHUB_INITIAL_ADMIN_PASSWORD`, `INFRAHUB_INITIAL_AGENT_TOKEN` (a UUID, the task worker's) and `INFRAHUB_SECURITY_SECRET_KEY`; one comment says these are read by Infrahub's Compose (`docker compose --env-file local/.env`), never by Fylgja, that `scripts/bring-up.sh` makes each one when it scaffolds `local/.env`, and that the published Compose file's defaults for them are public and must not be kept (research §2.3). Update the header's "copy to local/.env and fill in" to say the bring-up script scaffolds it.
- [ ] T022 [US2] Create `scripts/bring-up.sh` (mode 755) with its frame, in `scripts/e2e.sh`'s conventions: `#!/bin/bash`, a header comment (what it does, usage `scripts/bring-up.sh [--ceos-tar PATH] [--part NAME]... [--help]`, the preamble and the four parts, exit codes 0/1/2, hygiene: no value of `local/.env` is ever printed, logged or passed as an argument, and `set -x` is never used), `set -euo pipefail`, `cd` to the repository root from the script's own path; an `EXIT` trap that kills the sudo keep-alive loop of T023 when its pid is set (the only thing the trap does: the script undoes nothing it installed); helpers `say` (prints `bring-up: …`), `refuse` (`bring-up: REFUSED: …`, exit 2), `fail` (`bring-up: FAILED: <part>: <item>: …`, exit 1), `item <part> <name> present|installed|skipped <detail>` (prints `bring-up: <part>: <name>: <outcome> <detail>` and counts per part for the last report), `wait_for <part> <item> <what> <seconds> <hint> <command…>` (prints `waiting for <what> (up to <N>s)`, polls each second, fails naming it on expiry), and `psp_scalar` copied from `scripts/e2e.sh`. Flag parsing: `--ceos-tar PATH`, `--part NAME` (repeatable; one of `toolchain lab infrahub fylgja`; absent, all four in order), `--help` (prints the usage and exits 0), `--after-groups` accepted only when the environment carries the re-exec marker `BRING_UP_REEXEC=1` set by the lab part, refused otherwise; any other flag refused (exit 2). Refuse to run as root. Run the parts in order, then the last report.
- [ ] T023 [US2] Write the preamble of `scripts/bring-up.sh`, in the contract's order, changing nothing until `local/.env`: (1) `/etc/os-release` must carry `ID=ubuntu` and `VERSION_ID="26.04"`, else `REFUSED: this host is <PRETTY_NAME>; the script supports Ubuntu 26.04 alone`; (2) the flags (T022); (3) `sudo -v`, the one prompt, then a background loop `while sudo -n -v; do sleep 60; done &` whose pid the trap kills, so the cached credential outlives the parts' installs and pulls and no second prompt is made (contract, preamble item 3; SC-001), the re-executed run starting its own loop; (4) the cEOS tar (research R-12): the version from `psp/arista_eos.yaml`'s `image.ref` (`ceos:4.32.0.2F` → `4.32.0.2F`), the names `cEOS-lab-<version>.tar` and `cEOS-lab-<version>.tar.xz`, looked for at `--ceos-tar PATH`, then `local/`, then the clone's parent directory, never the root; a found file's `sha256sum` compared with the named constant `CEOS_TAR_SHA256=89a567d52f85e5f0e4650fe8e097e0226f78346d5a13d26bcab2a5623e888778`, a mismatch `REFUSED: <path>: sha256 <found> does not match the recorded <expected>; nothing was imported`; when `ceos:<version>` is already present the tar is not needed; (5) port 8000: when something listens there (`ss -ltnH 'sport = :8000'`) and no running container of Compose project `fylgja-infrahub` publishes it, `REFUSED: port 8000 is held by <process or container>; stop it, or point INFRAHUB_ADDRESS at it and run with --part fylgja`; (6) `local/.env`: when absent, scaffolded under `umask 077` from `.env.example`'s names, every name filled as data-model §2 says (UUIDs from `/proc/sys/kernel/random/uuid`, the API's token `head -c 24 /dev/urandom | base64`, the password and secret key random, `INFRAHUB_API_TOKEN` equal to `INFRAHUB_INITIAL_ADMIN_TOKEN`, `FYLGJA_STATE_ROOT` the absolute `local/`, `FYLGJA_HOST_MEMORY_MB` `MemTotal` in MiB less 8192, `FYLGJA_PSP_DIR` empty on purpose, each login the image's published default exactly as `scripts/e2e.sh` exports it, with e2e.sh's comment), mode `0600`; when present, kept byte for byte (FR-013); (7) the first report exactly as the contract's "The first report" gives it (host line, parts, cEOS tar line, platforms line, memory line with the warning under 24576 MiB). No value is written anywhere but `local/.env`.
- [ ] T024 [US2] Write the toolchain part of `scripts/bring-up.sh`: apt packages `make git curl jq xz-utils file golang-go python3-venv shellcheck` (each `present`, or installed with one `sudo apt-get install -y` of the missing ones after one `apt-get update`); `go version` run in the clone shows go1.26.0 fetched through `go.mod` (FR-003); golangci-lint `v2.14.0` into `/usr/local/bin` by its `install.sh -b /usr/local/bin v2.14.0` when `golangci-lint version` does not report 2.14.0; the Temporal CLI `1.9.1` by `curl -sSf https://temporal.download/cli.sh | sh -s -- --version 1.9.1` into `~/.temporalio/bin` when absent or another version; `gnmic` `0.49.0` by `bash -c "$(curl -sL https://get-gnmic.openconfig.net)" -- -v 0.49.0` when absent or another version; `.venv/` at the root by `python3 -m venv .venv`, a `.venv/.gitignore` of `*`, and `.venv/bin/pip install 'infrahub-sdk[ctl]==1.23.2'` when `.venv/bin/infrahubctl` is absent or another version. Check each installer's flags against its current documentation before use (research §2.10) and record any difference in research.md §3.
- [ ] T025 [US2] Write the lab part of `scripts/bring-up.sh`: Docker Engine when `docker version` fails, by containerlab's setup script pinned to `CLAB_VERSION=0.79.0` (research §2.10), and the user in `docker`; containerlab `0.79.0` (`bash -c "$(curl -sL https://get.containerlab.dev)" -- -v 0.79.0` when absent or another version) and the user in `clab_admins`; the AppArmor lines `/opt/srlinux/** mr,`, `/run/srlinux/** rw,` and `/run/syslogd.pid* rw,` in `/etc/apparmor.d/local/usr.sbin.rsyslogd`, each appended when missing, then `sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.rsyslogd`; `ghcr.io/nokia/srlinux:24.7.1` (read from `psp/nokia_srlinux.yaml`'s `image.ref`) pulled when absent; the cEOS import as the contract's lab item gives its four outcomes, the layer compared with the named constant `CEOS_LAYER=sha256:09ab96357c1d41f8bbaaead9ac10f61724f4890afcc09c75ad6b42519d73dd6c` (`docker image inspect --format '{{index .RootFS.Layers 0}}'`), and the import `docker import <tar> <image.ref>`. When this part added the user to a group, print `bring-up: lab: groups: docker clab_admins added; continuing in a fresh login session`, kill the sudo keep-alive loop (the `exec` would otherwise orphan it; the re-executed run starts its own) and `exec sudo -u "$USER" -i -- env BRING_UP_REEXEC=1 bash -c 'cd <root> && exec scripts/bring-up.sh --after-groups <the remaining --part flags> <the --ceos-tar flag>'`, carrying the part counters so the last report covers the whole run; `--after-groups` skips the preamble's prompt and the first report but re-checks the release.
- [ ] T026 [US2] Write the infrahub part of `scripts/bring-up.sh`, runnable alone (`--part infrahub`, FR-009) on a host where `docker`, `go`, `curl` and `jq` are on the `PATH` (it fails naming `go` when absent: `run the toolchain part, or set up Go`): `local/infrahub/docker-compose.yml` fetched from `https://infrahub.opsmill.io/1.11.2` when absent; `scripts/infrahub/docker-compose.override.yml` copied beside it when absent or different; `docker compose -p fylgja-infrahub --env-file local/.env -f local/infrahub/docker-compose.yml -f local/infrahub/docker-compose.override.yml up -d` (`present` when every service already runs, so a second run keeps the running Infrahub and its volumes); `wait_for` up to 600 s for `infrahub-server` healthy and `GET /api/info` answering version `1.11.2`, the token sent as a header file (as `e2e.sh`'s `gql` does); then, with `local/.env` loaded in a subshell, `go run -tags fixture ./cmd/fylgja-fixture -prepare-main`, its lines relayed under `bring-up: infrahub:`; then the fixture (research R-02): read `fylgja-fixture`'s `device-config` artifacts by GraphQL on that branch (`POST /graphql/fylgja-fixture`, as `e2e.sh`'s `artifacts_of` reads them): three `Ready` → `present (fylgja-fixture, 3 artifacts Ready)`; branch absent → `make infrahub-seed`; present and incomplete → `make infrahub-clean`, then `make infrahub-seed`; the seed run once more on `graphql: None`. Every wait bounded and named (FR-008).
- [ ] T027 [US2] Write the fylgja part and the last report of `scripts/bring-up.sh`: `make build`, `file bin/fylgja` statically linked; `make test` and `make test-contract`, each timed, with `local/.env` loaded in a subshell; the dev server (`~/.temporalio/bin/temporal server start-dev --db-filename local/temporal.db`, detached by `setsid nohup … >> local/temporal.log 2>&1 < /dev/null &`, `present` when `temporal operator cluster health` already answers `SERVING`, then `wait_for` it); the worker and the API's server, each started exactly as `CLAUDE.md`'s two commands start them, `present` when `pgrep -x fylgja` finds one whose `/proc/<pid>/cmdline` is that role and whose `/proc/<pid>/exe` is this tree's `bin/fylgja` and not `(deleted)`, restarted when `(deleted)`; each report read from `local/worker.log` and `local/server.log` (the server's `listening on 127.0.0.1:7650 (API version 1, build …)`), each naming the packages the host can run with their logins set, else `fail`. Then the last report exactly as the contract's "The last report" gives it, with `with --part` omitting parts not run, and exit 0. Nothing in either report carries a value of `local/.env`.
- [ ] T028 [US2] Check the script on the development host without changing it. The development host (24.04.1) has no `shellcheck`: the operator installs it before this run (`sudo apt-get install -y shellcheck`, Ubuntu's package; T040 and T059 use it too), since a session cannot answer sudo's prompt; if it is still absent, leave this task unchecked and say so. Then `shellcheck scripts/bring-up.sh` and `bash -n scripts/bring-up.sh` are clean (the local `shellcheck` is 24.04's package and a pre-check; the unit job's, on 26.04, is the gate, and a warning the two disagree on is fixed to the job's); `scripts/bring-up.sh --help` exits 0; `scripts/bring-up.sh` exits 2 with `bring-up: REFUSED: this host is Ubuntu 24.04.1 LTS; the script supports Ubuntu 26.04 alone` and `git status --short` and `local/` are unchanged after it; `scripts/bring-up.sh --bogus` and `scripts/bring-up.sh --part nope` exit 2; `scripts/bring-up.sh --after-groups` without the marker exits 2. Depends on T020–T027.
- [ ] T029 [operator] [US2] On a fresh Ubuntu 26.04 VM of the development host's shape (research R-05), with a clone at the branch's head and the tar in the clone's parent directory: `scripts/bring-up.sh 2>&1 | tee /tmp/bring-up.out` (quickstart §3). Expect exit 0, the first report naming both platforms and where the tar was found, one re-exec through a fresh login session, tiers 1 and 2 passed, the last report naming the three processes and both packages, no prompt after `sudo`'s. Run the hygiene greps of quickstart §3 against the variables (never a pasted value) over `/tmp/bring-up.out`, `local/*.log` and every file the run wrote but `local/.env`. Record in research.md §3 the timings and every fact §3 lists as owed (the host, Docker and Compose, containerlab, the images, Python, Go, Temporal, golangci-lint, the registration's import time); a fact that no longer holds is a finding fixed in the script or recorded, never worked around silently (FR-015). Each script defect found is fixed in `scripts/bring-up.sh` and the run repeated.
- [ ] T030 [operator] [US2] On that VM, `free -m`, then `make test-e2e` (detached, exit status in a file): `E2E-OK`, eight cases, case 1 deploying `b9d53ebc…` (SC-002). Record the wall time in research.md §3.
- [ ] T031 [operator] [US2] On that VM, the second run (quickstart §4): `cp local/.env /tmp/env.before; scripts/bring-up.sh; cmp local/.env /tmp/env.before`; every item `present`, `installed 0` on every part, Infrahub's containers keep their first start time (`docker compose -p fylgja-infrahub ps`), tiers 1 and 2 pass again, exit 0 (FR-013). Record the result in research.md §3.

**Checkpoint**: a stranger with the tar can stand Fylgja up.

---

## Phase 6: User Story 4 — CI runs tier 2 against a real Infrahub (Priority: P2)

**Goal**: on every push to `main`, the unit job and then the contract job pass on
`ubuntu-26.04`, the contract job running the script's Infrahub part, the generated-client
diff and tier 2 with no secret; a pull request runs the unit job alone; the README carries
the badge ([contracts/ci-and-release.md](contracts/ci-and-release.md); research R-06).

**Independent Test**: a push to `main` turns both jobs green with the Infrahub part's lines
in order in the contract job's log; a pull request runs the unit job alone; `gh api
repos/happypathnetworking/fylgja/actions/secrets --jq .total_count` is 0.

- [ ] T032 [US4] Rewrite `.github/workflows/ci.yml` per the contract: both jobs `runs-on: ubuntu-26.04`; `unit` keeps checkout@v5, setup-go@v6 (`go-version-file: go.mod`), `make build`, `make test`, golangci-lint-action@v9, and adds `shellcheck scripts/bring-up.sh scripts/e2e.sh`; `contract` drops `if: false` and the `env:` block that read `secrets.INFRAHUB_API_TOKEN`, takes `if: github.event_name == 'push'`, and runs checkout, setup-go, `scripts/bring-up.sh --part infrahub`, `go generate ./... && git diff --exit-code`, and `set -a; . local/.env; set +a; make test-contract`. Rewrite the comments: the contract job brings up a real Infrahub on the runner with the script's Infrahub part and needs no secret, because the script makes Infrahub's admin token on the runner, keeps it in the job's `local/.env`, and never prints it; it runs on pushes to `main` alone, never under `pull_request_target`; the `go generate` diff checks the committed client against the committed SDL and needs no Infrahub (research §2.9); tier 3 is never in CI (D-017). No `ubuntu-latest`, no `secrets.` anywhere.
- [ ] T033 [P] [US4] Add the badge to `README.md` directly under the title: `[![ci](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml)` (FR-025).
- [ ] T034 [US4] Check the workflows offline: each file under `.github/workflows/` parses as YAML (`python3 -c 'import sys, yaml; [yaml.safe_load(open(f)) for f in sys.argv[1:]]' .github/workflows/*.yml`, using `.venv/bin/python` when the system lacks PyYAML); `grep -n 'ubuntu-latest\|secrets\.\|if: false' .github/workflows/ci.yml` finds nothing; `grep -rn pull_request_target .github/workflows/` finds `pull-requests.yml` alone; no workflow runs `make test-e2e` or `scripts/e2e.sh`. Depends on T032.
- [ ] T035 [operator] [US4] After the operator merges and pushes `main` with the script and `ci.yml`: `gh run list --workflow ci -L 3`, then read the contract job's log (quickstart §6): Compose up, healthy, `schema loaded on main`, `group fylgja-devices created`, `repository fylgja created (… no credential)`, `import complete after <s>s`, the seed, the clean `go generate` diff, tier 2's `ok` lines; grep the log for `INFRAHUB_` beside a UUID, for `FYLGJA_API_TOKEN=` and for both images' published default passwords (against the variables `scripts/e2e.sh` exports, never a pasted value) and find nothing (SC-007; no twin runs there, so no login is ever used); `gh api repos/happypathnetworking/fylgja/actions/secrets --jq .total_count` prints 0. Record the contract job's wall time and, if the log shows it, peak memory in research.md §3 (SC-004). If the runner cannot hold Infrahub and the import, stop: splitting CI out of the script is a new decision-log entry, the operator's.
- [ ] T036 [operator] [US4] The operator opens a pull request from a throwaway branch: the unit job runs, the contract job does not, and `pull-requests.yml` comments and closes it; then deletes the branch. The badge on the front page shows the last run on `main`. Record both in research.md §3.

**Checkpoint**: tier 2 is the repository's, not the operator's.

---

## Phase 7: User Story 3 — SR Linux alone (Priority: P2)

**Goal**: without the tar the script goes on for SR Linux alone (built in T023 and T025,
proved here), and `scripts/e2e.sh` takes a platform list that narrows a run and ends on the
partial-pass line ([contracts/e2e-platform-list.md](contracts/e2e-platform-list.md);
data-model §3; research R-13).

**Independent Test**: on a VM without the tar the script names SR Linux alone and passes
tiers 1 and 2; a default tier-3 run refuses naming `ceos:4.32.0.2F`; `PLATFORMS=nokia_srlinux`
ends on `E2E-PARTIAL` naming cases 6 and 8, exit 0; a tar in the repository root is not found.

- [ ] T037 [US3] In `scripts/e2e.sh`, before `local/.env` is read and before anything starts: the case table, one associative array declared once near the top (`CASE_PACKAGES=([1]=nokia_srlinux [2]=nokia_srlinux [3]=nokia_srlinux [4]=nokia_srlinux [5]=nokia_srlinux [6]="nokia_srlinux arista_eos" [7]=nokia_srlinux [8]="nokia_srlinux arista_eos")`); the known packages, the stems of `psp/*.yaml`; `PLATFORMS` read from the environment, split on commas and spaces; unset or empty, a default run as now. Set: each name no package has refused with `fail "PLATFORMS names <name>, which no shipped package has; known: <sorted list>"`; a list that selects no case refused with `fail "PLATFORMS=<list> selects no case: every case needs nokia_srlinux"`. A helper `case_runs <n>` returns 0 when every package the case needs is in the list and each such package whose `image.acquisition` (read with `psp_scalar`) is `account_gated` has its `image.ref` present (`docker image inspect`); otherwise it sets the skip reason: `needs <pkg>: not in PLATFORMS`, `needs <pkg>: image <ref> absent`, or, when both hold, `needs <pkg>: not in PLATFORMS; image <ref> absent` (the contract's third form, so that US3 scenario 4's "its image is absent" and `not in PLATFORMS` are both said on an SR Linux-only host). Default run: every case runs. Document `PLATFORMS` and the partial-pass end in the header comment beside `WORKER_LOG`.
- [ ] T038 [US3] In `scripts/e2e.sh`, guard each case: at each `# --- case N` heading, `if case_runs N; then` … `fi` around the case's body (re-indenting nothing, so the diff shows the guards alone), the `else` branch printing `e2e: case N: skipped (<reason>)` and recording the case in a `SKIPPED` list, a case that ran in a `RAN` list. Keep the `CEOS_REF` presence check (line ~637) for a default run alone; with a list it is the skip rule's. The trap's destroy, the branch deletions (which already skip a branch never made), the leak checks and the credential and marker greps stay as they are and run after a narrowed run too (FR-021).
- [ ] T039 [US3] In `scripts/e2e.sh`, the end of the run: each closing timing line printed only when its case ran (case 5's, 6's, 7's and 8's lines and the verify and boot-half lines, which name case 6 and case 8 variables, split so that no unset variable is read under `set -u`); then `E2E-OK` when no case was skipped (a default run, or a list that skipped nothing), else `E2E-PARTIAL: platforms <list>; ran <cases>; skipped <case> (<reason>) …` and exit 0. A failed check still exits 1 and a leak 99. Update the header's "Exit 0 prints E2E-OK" paragraph to say both ends.
- [ ] T040 [US3] Check the platform list offline on the development host, starting nothing: `shellcheck scripts/e2e.sh` is clean; `PLATFORMS=acme_os scripts/e2e.sh` exits 1 naming `acme_os` and the known packages; `PLATFORMS=arista_eos scripts/e2e.sh` exits 1 with `selects no case`; neither starts a server, a worker or a twin, nor writes under `local/`. Depends on T037–T039.
- [ ] T041 [live] [US3] On the development host (both images), a quiet host, `free -m` first: `PLATFORMS=nokia_srlinux make test-e2e` (detached, exit status in `local/converge-e2e.out`, waited on in calls of under ten minutes) ends `E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7; skipped 6 (needs arista_eos: not in PLATFORMS) 8 (needs arista_eos: not in PLATFORMS)`, exit 0 (US3 scenario 5); afterwards `clab inspect --all` holds no `fylgja` lab, `local/twin` is absent and `fylgja waypoint list` prints `no waypoints`. Record the wall time in research.md §3.
- [ ] T042 [live] [US3] After resting the host: `PLATFORMS=nokia_srlinux,arista_eos make test-e2e` ends `E2E-OK`, eight cases (US3 scenario 7); the host is clean afterwards as in T041.
- [ ] T043 [operator] [US3] On a fresh Ubuntu 26.04 VM with no tar anywhere (quickstart §5): `scripts/bring-up.sh` names `nokia_srlinux` alone and where it looked in both reports and passes tiers 1 and 2; `make test-e2e` exits 1 before any case naming `ceos:4.32.0.2F` and how to import it; `PLATFORMS=nokia_srlinux make test-e2e` ends `E2E-PARTIAL` naming cases 6 and 8 with both reasons, exit 0; `PLATFORMS=acme_os make test-e2e` is refused; the tar copied into the clone's root alone and the script run again reports `not found` with where it looked; a file of random bytes named `local/cEOS-lab-4.32.0.2F.tar` ends the script `REFUSED` with both checksums, exit 2, before any part, and `docker images` shows no new image. Record each in research.md §3 (SC-003).

**Checkpoint**: half the audience without an Arista account can stand Fylgja up.

---

## Phase 8: User Story 6 — The front page (Priority: P3)

**Goal**: the README with the recording and the script, the release workflow, the write-up,
and the five Infrahub behaviours filed or dropped (FR-032–FR-036).

**Independent Test**: the operator reads the front page and finds the README, the badge,
the recording, `LICENSE`, `SECURITY.md`, the diagrams and (after the polish phase) the
release; `docs/how-it-was-built.md` is one page; each behaviour has one outcome.

- [ ] T044 [P] [US6] Rewrite `README.md`'s "What it needs" and "Tests" sections (US7 scenario 5): What it needs points at `scripts/bring-up.sh` as the way to stand a host up (Ubuntu 26.04 alone; `--ceos-tar`; what the script installs; the three processes it leaves running) and says what an SR Linux-only host gets: the cEOS image is needed only for EOS and mixed twins and tier 3's EOS cases, and the walk-throughs, all SR Linux, are unchanged; Tests says CI runs the unit job on every push and pull request and the contract job against a real Infrahub on pushes to `main`, that tier 3 is the operator's and never in CI, and how `PLATFORMS=nokia_srlinux make test-e2e` narrows it to an `E2E-PARTIAL` end. Leave every walk-through and the Contributing section unchanged.
- [ ] T045 [P] [US6] Create `.github/workflows/release.yml` per the contract: `on: push: tags: ['v*']`, `permissions: contents: write`, one job `release` on `ubuntu-26.04` with `env: GH_TOKEN: ${{ github.token }}`: checkout@v5, setup-go@v6 (`go-version-file: go.mod`), `VERSION="${GITHUB_REF_NAME#v}"`, `make build VERSION="$VERSION"`, `test "$(bin/fylgja --version)" = "fylgja version $VERSION"`, `file bin/fylgja | grep -q 'statically linked'`, `make test`, `gh run list --repo "$GITHUB_REPOSITORY" --commit "$GITHUB_SHA" --workflow ci --json conclusion --jq '.[0].conclusion' | grep -qx success`, `cp bin/fylgja fylgja-linux-amd64 && sha256sum fylgja-linux-amd64 > SHA256SUMS`, then `gh release create "$GITHUB_REF_NAME" --draft --verify-tag --title "$GITHUB_REF_NAME" --notes-file <notes written by a heredoc in the step> fylgja-linux-amd64 SHA256SUMS`; the notes say what the release is (the launch; M1–M7 and M10–M14 built), the binary's platform (Linux amd64, static) and that a client on another machine builds from the tree. A header comment says the operator pushes the tag and publishes the draft (FR-037). Confirm locally that `make build VERSION=0.1.0 && bin/fylgja --version` prints `fylgja version 0.1.0`, then `make build` again.
- [ ] T046 [operator] [US6] The recording, on the development host with the operator present (research R-10; quickstart §7; data-model §6): install asciinema `3.2.1` and agg `1.9.0` by hand from their GitHub releases into `~/.local/bin` (not by the script); off camera, seed `fylgja-test-readme` and write its waypoints 1 and 2 exactly as `README.md`'s stepping walk-through does; record `asciinema rec --cols 100 --rows 30 docs/recording/session.cast` in a shell holding `FYLGJA_API_TOKEN` alone, running `bin/fylgja twin create --waypoint fylgja-test-readme/1`, `bin/fylgja twin step` to waypoint 2, `bin/fylgja twin verify`; render `agg --idle-time-limit 2 --fps-cap 15 --font-size 14 docs/recording/session.cast docs/recording/session.gif` (under 3 MB); off camera, `bin/fylgja twin destroy` and `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete`, then `fylgja waypoint list` prints `no waypoints`. Grep both files for the API's token, Infrahub's token and both passwords against the variables and find nothing; the operator reads every frame; a credential in a frame means a new recording. Embed it in `README.md` after the first paragraph: `![A twin created from a waypoint, stepped to the next and verified](docs/recording/session.gif)`, with one line saying the cast is beside it.
- [ ] T047 [operator] [US6] The write-up's figures (research R-09; FR-035): in one session on the development host, from the location the operator gives in that session (which nothing here writes down), count per milestone the features, the active hours (`command` plus `follow_ups`), the Spec Kit passes and convergence passes, the appended `[behaviour]` / `[pin]` tasks where tags exist, model time and tokens by model, and the totals of features, tasks, commits, decisions and verified facts, by R-09's definitions; write them into `specs/013-launch/research.md` §5, each stated as derived from the private record with how it was counted, and no quotation, file name, path, commit hash, task number or feature wording of that record. The operator reads §5 before it is committed.
- [ ] T048 [US6] Write `docs/how-it-was-built.md`, one page (data-model §8): what Fylgja is (one paragraph); what a Spec Kit pass is (specify → clarify → plan → tasks → analyze → implement → converge, each in a fresh context, with a human deciding); what a convergence pass finds (the kinds of task it appends, with the tags `[behaviour]`, `[pin]`, `[operator]`); the figures as one table (milestone, features, hours, passes, model time by model) taken from research.md §5, each said to be derived from the private record; what the hours say about AI-assisted engineering with a human deciding; what stays private and why (D-043, linked as `decisions.md#d-043` from the page). Check: `grep -nE 'specs/0|T0[0-9]{2}|[0-9a-f]{7,40}' docs/how-it-was-built.md` finds nothing; the figures match §5. Depends on T047.
- [ ] T049 [operator] [US6] The five Infrahub 1.11.2 behaviours of research R-11 (FR-036), one at a time: load the `infrahub-reporting-issues` skill and pass it the behaviour, its verified-facts entry and R-11's starting classification; it searches for a duplicate and shows the draft; nothing is submitted without the operator's word. For each, record in `docs/verified-facts.md` beside the fact: `filed` with the issue's or discussion's link, or `dropped` with the operator's word (and the existing issue's link when a duplicate was found). No credential or private path in any draft.

**Checkpoint**: everything the front page shows exists but the release.

---

## Phase 9: User Story 7 — The records are true at the close (Priority: P3)

**Goal**: development.md, verified-facts.md, the glossary, the roadmap, `docs/ideas.md` and
`CLAUDE.md` say what the launch made true (FR-038; research §4).

**Independent Test**: each record says what this feature made true, and the grep of T058
finds no statement the launch made false.

- [ ] T050 [US7] Rewrite `docs/development.md`'s "Local environment" as the script's record (FR-016): part by part, what `scripts/bring-up.sh` does (the preamble's checks and `local/.env`'s scaffold; toolchain; lab, with the re-exec through a fresh login session; infrahub, with the Compose files' place, `scripts/infrahub/docker-compose.override.yml` copied beside the versioned Compose file under `local/infrahub/`, and `-prepare-main`; fylgja and the three processes), no longer asking the reader to do it by hand; the cEOS tar's name corrected to `cEOS-lab-4.32.0.2F.tar` (or `.tar.xz`), its sha256, where the script looks and that the root is never searched (research R-12); the SR Linux-only host; Ubuntu 26.04 as the one supported release. Keep what the table says about each component that is still true. Depends on T029 and T043, whose findings it describes.
- [ ] T051 [US7] Update the rest of `docs/development.md`: "Repository layout" gains `scripts/bring-up.sh`, `scripts/infrahub/`, the three workflows, `docs/recording/`, `SECURITY.md` and `docs/how-it-was-built.md`; "Test architecture" describes CI's two jobs (the unit job with `shellcheck`; the contract job on pushes to `main` alone, the Infrahub part, no secret) and the badge, and tier 3's `PLATFORMS` with the `E2E-PARTIAL` end; "Build and make targets" names the script. Confirm T019's "What Infrahub needs" text still reads true beside them.
- [ ] T052 [operator] [US7] The development host moves to Ubuntu 26.04 by a fresh install that `scripts/bring-up.sh` sets up (spec, Assumptions), only after T047 has read the figures (the private record stays reachable until then; spec, Edge Cases). Then the worker and the server run from this tree there, tiers 1 and 2 pass, and the development host's 24.04.1 facts of verified-facts.md (The host, containerlab 0.79.0) are re-verified on it; record each in research.md §3.
- [ ] T053 [US7] Update `docs/verified-facts.md` from research.md §3: every fact the script re-verified on 26.04 carries `26.04` and its date beside its earlier verification; The host describes the 26.04 host as T052 found it; a fact that no longer held is corrected, with what changed; the registration's facts (R-15's three answers, the import's time), the `ref` answer (T019) and the five behaviours' outcomes (T049) are in. Depends on T029, T031, T043, T049, T052.
- [ ] T054 [P] [US7] Update `docs/glossary.md`: new entries *platform list*, *partial pass*, *Infrahub part*, *recording* and *write-up*, each one or two sentences in the glossary's style with a link to where it is defined; *Bring-up script* no longer "not yet built" and names `scripts/bring-up.sh`; *Development host* on Ubuntu 26.04.
- [ ] T055 [P] [US7] Update `docs/roadmap.md`: the Built table carries the launch (M14 complete: the cut and the launch); Next names the first item after the launch from the roadmap's own order (plan: item 7); remove or rewrite every sentence that calls the launch next or the repository private.
- [ ] T056 [P] [US7] Add to `docs/ideas.md`, in its style: a persistent waypoint series on the fixture branch, and what it would reverse (the fixture tool's refusal to write a series naming `fylgja-fixture`, the test-series guard, the tiers' "no waypoints" invariant) and what it could add (a tier-3 step of an SR Linux-only twin, which no case steps today) (spec, Out of scope).
- [ ] T057 [US7] Update `CLAUDE.md`: Environment describes the 26.04 development host as T052 found it (release, kernel, Docker, Compose, Python, the venv), Infrahub's Compose run from `local/infrahub/` with the committed override, `main` carrying the read-only registration `fylgja` with no credential (the private copy and its credential gone), the Compose block's names in `local/.env`, the tar's name; Build and test names `scripts/bring-up.sh` and `PLATFORMS`; Formats unchanged; State rewritten whole (M1–M7 and M10–M14 built, the launch verified as SC-001–SC-012 record, the release the close's last act, Next as the roadmap names it, Open what remains).

**Checkpoint**: the documents a reader and the next session act on are true.

---

## Phase 10: Polish & the close

- [ ] T058 Grep the documents for what the launch made false and fix each hit: `grep -rnE '24\.04|fylgja-artifacts|CorePasswordCredential|if: false|cEOS64|not yet built|private copy|infrahub-dev' README.md CLAUDE.md docs/ schema/README.md psp/README.md .env.example`, keeping only historical mentions kept on purpose (a 24.04 verification's date, the template's `rendered by Infrahub (fylgja-artifacts)` text); then `grep -n 'ubuntu-latest' .github/workflows/*.yml` finds nothing.
- [ ] T059 Run the closing gates and hygiene: `make build`; `file bin/fylgja` statically linked; `make test` with `git diff --stat main -- testdata/golden` empty and every format version unchanged (SC-012); `make lint`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`; the private-record grep of T007 over the whole tree (SC-008); from a shell that has loaded `local/.env`, `grep -rlF` for `INFRAHUB_API_TOKEN`'s and `FYLGJA_API_TOKEN`'s values over the tree, `docs/recording/` and the saved script outputs (SC-007), and for both passwords over `docs/recording/`, `specs/013-launch/`, `docs/`, `README.md`, `SECURITY.md` and the saved outputs, CI's log having been grepped in T035 (the published defaults live in `scripts/e2e.sh`, `scripts/bring-up.sh` and `local/.env` alone, as FR-041 and SC-007 allow), never printing a value.
- [ ] T060 [operator] The release (FR-033; quickstart §8), once the commit that carries T058–T059 is on `main` and its `ci` run is green: the operator runs `git tag -a v0.1.0 -m 'Fylgja v0.1.0: the launch' && git push origin v0.1.0`; `release.yml` builds the draft; the operator publishes it. Check: `gh release view v0.1.0 --json assets,isDraft` lists `fylgja-linux-amd64` and `SHA256SUMS`; the downloaded binary prints `fylgja version 0.1.0` and `file` says statically linked (SC-011).
- [ ] T061 [operator] The operator reads the front page at the close (SC-006): README with the recording, the badge and the script; `LICENSE`; `SECURITY.md`; the release `v0.1.0` with its binary; the diagrams; the settings and topics; `docs/how-it-was-built.md` one page. Then `make command-log` once the session is closed.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none.
- **US1 (Phase 2)**: after Setup. **Blocks everything after it**: the flip precedes every
  credential-less registration, and FR-030 puts it before the script, CI and the registration
  are built.
- **Foundational (Phase 3)**: after the flip (T009). Blocks US5, US2's Infrahub part (T026
  onward) and US4's contract job.
- **US5 (Phase 4)**: after Foundational; the first live use of `-prepare-main`.
- **US2 (Phase 5)**: T020–T028 after Foundational (T026 calls `-prepare-main`); T029–T031
  need the fresh VM and the repository public.
- **US4 (Phase 6)**: T032–T034 after T028 (the contract job runs the script); T035–T036 after
  the operator pushes `main` with them.
- **US3 (Phase 7)**: T037–T040 depend only on Setup and may run beside US2 and US4; T041–T042
  need the development host's twins; T043 needs the script (T028) and a tar-less VM.
- **US6 (Phase 8)**: T044 after T028 and T039 (it describes both); T045 independent; T046
  after T018 (the development host renders from this repository); T048 after T047; T049
  independent of the rest.
- **US7 (Phase 9)**: T050 after T029 and T043; T052 after T047; T053 after T029, T031, T043,
  T049 and T052; T057 after T052.
- **Polish (Phase 10)**: after every story; T060 is the close's last outward act but T061.

### Within a story

The offline work (code, workflow, document) comes first and is gated offline; the live or
operator task that proves it follows. A defect found by a live task is fixed in the same
story before the story's checkpoint.

### Parallel opportunities

- US1: T002, T003, T004, T005, T006 touch different files.
- US2: T020 and T021 beside each other and beside T022.
- US3's offline work (T037–T040) beside US2's script (T022–T028) and US4's workflow (T032).
- US6: T044 and T045; T049 at any time after the flip.
- US7: T054, T055, T056.

### Parallel example: User Story 1

```text
T002 SECURITY.md
T003 .github/workflows/pull-requests.yml
T004 contracts/*.schema.json and psp/psp.schema.json descriptions
T005 internal/*/testdata/contracts/*/ frozen copies
T006 docs/glossary.md, the Launch entry
→ then T007, the read of the tree, over all of them
```

---

## Implementation Strategy

**MVP**: US1, the flip. Every other story depends on it, it is small (two files, a scrub and
a read), and it is the one act that cannot be done twice.

**Incremental delivery**, in the operator's order: US1 → Foundational → US5 (the development
host proves `-prepare-main`) → US2 (the script, proved on the fresh VM) → US4 (CI, proved
by the first push) → US3 (the platform list, proved on the development host and the tar-less
VM) → US6 (the visible half) → US7 (the records) → the release. Each checkpoint leaves the
repository consistent: a stop after any of them is a launch with less on its front page,
never a broken one.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

1. **Run 1** — the baseline, and everything the flip needs in the tree: SECURITY.md, the pull-request workflow, the scrub of the contract descriptions, the glossary's Launch entry, the read of the tree (T001–T007). Only these; stop and report.
2. **Run 2** — [operator] the merge, the flip, the ruleset, the settings and the public checks (T008–T010). The operator's acts; stop and report.
3. **Run 3** — the fixture tool prepares main and its refusal is reworded, gated offline (T011–T014). Only these; stop and report.
4. **Run 4** — [operator] the development host registers this repository: the swap, `-prepare-main` live, the re-seed and `b9d53ebc…`, tier 2 and tier 3 on a quiet host, the `ref` question (T015–T019). Stop and report.
5. **Run 5** — the bring-up script, the Compose override and `.env.example`'s Compose block, checked on the development host by its refusal (T020–T028). Only these; stop and report.
6. **Run 6** — CI's workflow and the README's badge, checked offline (T032–T034). Only these; stop and report.
7. **Run 7** — scripts/e2e.sh's platform list (PLATFORMS), its skip rule and its partial-pass end, checked offline (T037–T040). Only these; stop and report.
8. **Run 8** — [operator] the fresh VMs: the full run, tier 3, the second run, the tar-less run, then the first push to main and a pull request (T029–T031, T035–T036, T043). Stop and report.
9. **Run 9** — narrowed tier 3 on the development host, on a quiet host (T041–T042). Stop and report.
10. **Run 10** — the README's What it needs and Tests sections, and the release workflow (T044–T045). Only these; stop and report.
11. **Run 11** — [operator] the recording, the write-up's figures, the five Infrahub behaviours (T046, T047, T049). Stop and report.
12. **Run 12** — the write-up's one page from research.md §5 (T048). Only this; stop and report.
13. **Run 13** — [operator] the development host moves to Ubuntu 26.04 by the script, and its facts are re-verified (T052). Stop and report.
14. **Run 14** — the records: development.md, verified-facts.md, the glossary, the roadmap, ideas, CLAUDE.md (T050–T051, T053–T057). Only these; stop and report.
15. **Run 15** — the stale-statement grep and the closing gates (T058–T059). Only these; stop and report.
16. **Run 16** — [operator] the release v0.1.0 and the front page read (T060–T061). Stop and report.

`converge` follows Run 16.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route" only up to the next heading. The runs are invoked by hand with `/speckit-implement`, one line each, since six of them are the operator's.
