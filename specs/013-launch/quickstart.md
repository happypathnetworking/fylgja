# Quickstart: validating the launch

**Feature**: `013-launch` · **Plan**: [plan.md](plan.md) · **Contracts**: [contracts/](contracts/)

What proves the feature, scenario by scenario, in the order the operator's acts come
(spec, Assumptions). Each names its prerequisites, the commands and what must come out.
Credentials: nothing below prints one; `local/.env` is the one file that holds a value.

## Prerequisites

- **The flip** (scenario 1) precedes every registration: the script, CI and the
  development host register this repository with no credential, which only a public
  repository allows.
- **A fresh Ubuntu 26.04 VM** of the development host's shape (10 vCPU, 32 GiB, 8 GiB
  swap, 100 GB; research R-05), with a clone of this repository and, for the full run,
  the cEOS tar (`cEOS-lab-4.32.0.2F.tar`, sha256 `89a567d5…`) in the clone's parent
  directory. It is the operator's to provide; the development host moves to 26.04 by
  such an install once the script is proved.
- **The development host** as it stands (24.04.1, Infrahub 1.11.2 up, worker and server
  from this tree), for scenarios 1, 5, 6 and 8.
- **GitHub**: the `gh` CLI logged in as the operator for the outward-facing acts.

## 1. The tree is read, the settings are set, the repository goes public

**Operator's act.** On `013-launch`, merged to `main` and pushed before the flip:

```sh
grep -rnE 'specs/0(0[1-9]|1[0-2])-|research R[0-9]|/home/[a-z]+/|\bT0[0-9]{2}\b' \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=local --exclude-dir=bin . | grep -vE '^(\./)?specs/013-launch/'
test -f SECURITY.md && test -f .github/workflows/pull-requests.yml
```

(The filter takes both path forms: GNU grep prints `./README.md`, ugrep `README.md`.)

Expected: the grep finds nothing but Spec Kit's own text, which is not the record: the
example path in `.claude/skills/speckit-specify/SKILL.md` and the example task ids
(`T001`…) in `.specify/templates/tasks-template.md` and in the `speckit-taskstoissues`,
`speckit-tasks` and `speckit-converge` skills; and four made-up paths in tests
(`/home/operator/…` in `internal/server/provision_test.go`, `/home/op/…` in
`internal/lab/stray_test.go` and `internal/provision/workflow_reconcile_test.go`).
Research §2.11 lists what was scrubbed; the description strings of every contract schema
and frozen copy carried such citations. `SECURITY.md` says how to report a vulnerability.
Then, in one sitting
([contracts/ci-and-release.md](contracts/ci-and-release.md), "The other settings" and
"The ruleset"): the flip, the ruleset, private vulnerability reporting, projects and wiki
off, the topics. Check: `gh repo view --json visibility,repositoryTopics`;
`gh api repos/happypathnetworking/fylgja/rulesets --jq '.[].name'` lists `main`; a clone
over HTTPS from a shell with no credential succeeds.

## 2. The development host renders from this repository (FR-027, FR-029)

**With the operator's word in the session** (the development host's Infrahub is not
outward-facing). Research R-15; record each answer in `research.md` §3 as it comes:

```sh
set -a; . local/.env; set +a
# 1. remove the private copy and its credential (CoreRepositoryDelete, CorePasswordCredentialDelete), by GraphQL
# 2. do the query, the transform and the definition survive on main? record it
go run -tags fixture ./cmd/fylgja-fixture -prepare-main          # registers fylgja, awaits the import
# 3. record the three objects' repository and whether their ids moved
make infrahub-clean && make infrahub-seed                          # the fixture branch re-created (retry once on graphql: None)
bin/fylgja intent read --branch fylgja-fixture --out /tmp/f.json && bin/fylgja twin compile --ctm /tmp/f.json --out /tmp/f
make test-contract
make test-e2e                                                      # a quiet host; free -m first
```

Expected: `CoreGenericRepository` on `main` holds `fylgja` alone (read-only, `ref main`,
no credential, `active`, `online`); the seed passes; `twin compile` prints
`bundle_id b9d53ebc…`; tier 2 passes; tier 3 ends `E2E-OK` with eight cases. Then the
`ref` question: after a new commit on `main` of this repository, which of the three ways
(the minute sync; `CoreReadOnlyRepositoryUpdate` of `ref`;
`InfrahubReadOnlyRepositoryImportLastCommit`) moves `commit`; recorded with the version
and date, and development.md says which.

## 3. A stranger stands Fylgja up: the full run (US2)

On the fresh VM, from the clone, the tar in the parent directory:

```sh
scripts/bring-up.sh
```

Expected ([contracts/bring-up-script.md](contracts/bring-up-script.md)): the first report
names both platforms and where the tar was found; every item ends `present` or
`installed`; the lab part re-executes the run once through a fresh login session after
the groups; tiers 1 and 2 pass; the last report names the three processes running with
how to stop them and both packages in the worker's and the server's lines; exit 0; no
input asked after the start but `sudo`'s. Then, once:

```sh
free -m
make test-e2e
```

Expected: `E2E-OK`, eight cases, case 1's fixture compiling to `b9d53ebc…` under the
development host's schema hash (each install has its own, and the bundle covers it, so
the VM's own id differs; SC-002). Record the script's
timings and what §3 of research.md asked for (the re-verified facts), then the
development host's facts move to verified-facts.md with `26.04` and the date.

Hygiene: `grep -rF -- "$(sed -n 's/^INFRAHUB_API_TOKEN=//p' local/.env)" local/*.log
bin/ .venv/ /tmp/bring-up.out` finds nothing, and the same for `FYLGJA_API_TOKEN` and
both passwords (run from a shell that has loaded `local/.env`, comparing against the
variables, never pasting a value).

## 4. A second run changes nothing (FR-013)

On the host scenario 3 left:

```sh
cp local/.env /tmp/env.before; scripts/bring-up.sh; cmp local/.env /tmp/env.before
docker compose -p fylgja-infrahub ps --format '{{.Name}} {{.Status}}'
```

Expected: every item `present`, `installed 0` on every part, Infrahub's containers with
their first run's start time, `local/.env` byte-identical, tiers 1 and 2 passed again,
exit 0.

## 5. SR Linux alone (US3)

On a fresh VM with no tar anywhere, then with the tar placed in the clone's root alone:

```sh
scripts/bring-up.sh                                   # → platforms: nokia_srlinux (…); tiers 1 and 2 pass
make test-e2e                                         # → e2e: FAILED: image ceos:4.32.0.2F is absent: … (exit 1, before any case)
PLATFORMS=nokia_srlinux make test-e2e                 # → E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7; skipped 6 (…) 8 (…)  (exit 0)
PLATFORMS=acme_os make test-e2e                       # → e2e: FAILED: PLATFORMS names acme_os, which no shipped package has; known: … (exit 1)
cp ../cEOS-lab-4.32.0.2F.tar . && scripts/bring-up.sh # → cEOS tar: not found; looked at …; the repository root is never searched
```

Also, on the development host (both images): `PLATFORMS=nokia_srlinux make test-e2e` still
skips 6 and 8 (`not in PLATFORMS`), and `PLATFORMS=nokia_srlinux,arista_eos make test-e2e`
ends `E2E-OK`. After each narrowed run: `clab inspect --all` is `{}`, `local/twin` is
absent, `fylgja waypoint list` prints `no waypoints`.

A tar whose checksum differs (make one with `head -c 1000 /dev/urandom >
local/cEOS-lab-4.32.0.2F.tar`): the script ends `REFUSED` with both checksums, exit 2,
before any part; `docker images` shows no new image.

## 6. CI (US4)

**Operator's act**: push `main`. Then:

```sh
gh run list --workflow ci -L 3
gh run view <id> --log | grep -E 'bring-up: |E2E|PASS|FAIL' | head -50
gh api repos/happypathnetworking/fylgja/actions/secrets --jq .total_count     # → 0
```

Expected: both jobs green; the contract job's log shows the Infrahub part's lines in
order (Compose up, healthy, `schema loaded on main`, `group fylgja-devices created`,
`repository fylgja created (… no credential)`, `import complete after <s>s`, the seed),
then the `go generate` diff clean and tier 2's `ok` lines; no token in the log (grep it
for the shape of a UUID beside `INFRAHUB_`, and for `FYLGJA_API_TOKEN=`); the wall time
recorded in `research.md` (SC-004). Open a pull request from a fork or a branch: the
unit job runs, the contract job does not, and the pull-request workflow closes it with
the Contributing comment. The README's badge shows the last run on `main`.

## 7. The recording (FR-032)

On the development host, with asciinema 3.2.1 and agg 1.9.0 installed by hand:

```sh
# off camera: seed fylgja-test-readme and write /1 and /2 as the README's stepping walk-through does
asciinema rec --cols 100 --rows 30 docs/recording/session.cast      # in a shell holding FYLGJA_API_TOKEN alone:
#   bin/fylgja twin create --waypoint fylgja-test-readme/1 ; bin/fylgja twin step ; bin/fylgja twin verify ; exit
agg --idle-time-limit 2 --fps-cap 15 --font-size 14 docs/recording/session.cast docs/recording/session.gif
# off camera: bin/fylgja twin destroy; go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-readme -delete
```

Expected: both files under `docs/recording/`, the GIF under 3 MB, the README embedding
it; a grep of both files for the four credentials finds nothing; every frame read before
the commit; `fylgja waypoint list` prints `no waypoints` afterwards.

## 8. The release (FR-033)

**Operator's acts**: `git tag -a v0.1.0 -m 'Fylgja v0.1.0: the launch' && git push origin
v0.1.0`; then publish the draft. Check:

```sh
gh release view v0.1.0 --json assets,isDraft --jq '{isDraft, assets: [.assets[].name]}'
gh release download v0.1.0 -p fylgja-linux-amd64 -D /tmp/rel && chmod +x /tmp/rel/fylgja-linux-amd64
/tmp/rel/fylgja-linux-amd64 --version && file /tmp/rel/fylgja-linux-amd64
```

Expected: assets `fylgja-linux-amd64` and `SHA256SUMS`; `--version` prints `0.1.0`;
`file` says statically linked; the tagged commit's `ci` run was green.

## 9. The write-up, the issues, the records (US6, US7)

- `docs/how-it-was-built.md` is one page; `grep -nE 'specs/0|T0[0-9]{2}|[0-9a-f]{7,40}'`
  over it finds no path, task number or hash; its figures match `research.md` §5, read by
  the operator before the commit.
- Each of the five behaviours has one outcome in verified-facts.md (`filed`, with a link,
  or `dropped`), each draft having been shown by the `infrahub-reporting-issues` skill.
- `grep -n '24.04' docs/development.md docs/verified-facts.md CLAUDE.md` finds only the
  historical mentions the documents keep on purpose (the 24.04 verifications' dates), and
  *The host*, *Local environment* and `CLAUDE.md`'s Environment describe 26.04;
  `grep -n 'if: false' .github/workflows/ci.yml` finds nothing; the roadmap's Built table
  has the launch; the glossary has *platform list*, *partial pass*, *Infrahub part*,
  *recording*, *write-up*; `make test` passes with no golden re-baselined (SC-012).
