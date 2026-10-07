# Specify brief: M14 feature 2 of 2 — the launch

What `/speckit-specify` reads for the launch, beside the roadmap's
[Next section](../../docs/roadmap.md#next), [D-043](../../docs/decisions.md#d-043) and
[D-044](../../docs/decisions.md#d-044). Written 2026-10-07, the day this repository's first
commit (`a5225dd`, M14's cut) was pushed and verified, before any research, so that the
prompt carries decisions and not restatement
([development.md](../../docs/development.md#spec-kit-workflow), "The specify prompt carries
decisions"). It is a draft for the operator's confirmation. No question is left for
clarify ([Open](#open)), which runs in specify's context and asks only what specify finds
underspecified. Specify what the operator gets, not a new design. The
[References](#references) section names every file to read, with what each gives.

This is the first feature specified in this repository, so there is no earlier spec here
to follow: the spec takes [the template](../../.specify/templates/spec-template.md)'s
shape, and the records it builds on are the documents of the first commit.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/013-launch. M14 — Reproducible and visible, the second of its two features: the launch, as docs/roadmap.md's Next section, D-043 and D-044 define it. Read specs/013-launch/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Where the shape is fixed

- **The roadmap's [Next section](../../docs/roadmap.md#next)** is this feature's scope,
  item by item: the bring-up script, CI with a real Infrahub, Infrahub rendering from this
  repository, and the visible half (the README with its recorded session, `SECURITY.md`,
  `v0.1.0`, the repository's settings and topics, the write-up and the Infrahub issues),
  with the repository public from its start ([Decided](#decided)), and a stranger able to
  stand Fylgja up at its close. Its size is 10–14 hours, kept whole because both of
  the script's consumers run the one script; the spec may still split CI out if the runner
  needs more than the script gives. Its [Decisions the order
  needs](../../docs/roadmap.md#decisions-the-order-needs) names one for the launch: whether
  the script offers an SR Linux-only path. It does ([Decided](#decided)).
- **[D-043](../../docs/decisions.md#d-043)**: development continues here, the bring-up
  script and CI are built here, and the private development record is summarised by a
  write-up that does not cite it.
- **[D-044](../../docs/decisions.md#d-044)**: this repository registered in Infrahub as a
  `CoreReadOnlyRepository` on `main` with no credential, once it is public; the template's
  bytes unchanged, so no artifact or fixture id moves; the fixture tool's message reworded;
  whether Infrahub 1.11.2 takes a new commit on a `ref` update, or only on re-creation,
  verified then.
- **[D-017](../../docs/decisions.md#d-017)** and the constitution's Development Workflow:
  three tiers; contract tests against a real Infrahub, never a fake; end-to-end tests never
  gate a pull request, so tier 3 stays out of CI.
  **[D-042](../../docs/decisions.md#d-042)**: one bearer token in the clear, on loopback
  unless `--listen` says otherwise, which `SECURITY.md` states.
  **[D-028](../../docs/decisions.md#d-028)**: Infrahub renders the configuration Fylgja
  pushes.
- **[Constitution 1.1.1](../../.specify/memory/constitution.md)**: I (one static binary in
  Go, no second runtime in the critical path: the script is tooling beside
  `scripts/e2e.sh`, not something Fylgja ships, as [architecture §5](../../docs/architecture.md#5-stack)'s
  first row says of what ships); X (no credential in anything this feature writes: the
  script, CI's logs, the recorded session, `SECURITY.md`).
- **What this repository holds for the launch** (read 2026-10-07, at `a5225dd`):
  - **`.github/workflows/ci.yml`**: the `unit` job runs on every push to `main` and every
    pull request (build, test, golangci-lint). The `contract` job is under `if: false`.
    Its steps run `make infrahub-schema && make infrahub-seed`, then `go generate ./... &&
    git diff --exit-code`, then `make test-contract`, against `http://localhost:8000` with
    the token from a secret. They start no Infrahub, make no group and register no
    repository, and `make infrahub-schema` loads the schema on the fixture branch, not on
    `main`: the steps predate the schema on `main` (D-028) and the template here (D-044).
  - **Nothing here loads the schema on `main`, creates the group `fylgja-devices`, or
    registers a repository.** [development.md](../../docs/development.md#local-environment)
    ("What Infrahub needs") says what `main` must carry. The fixture tool
    (`cmd/fylgja-fixture`, build tag `fixture`, the one binary that writes to Infrahub)
    creates a branch, loads `schema/` on it, seeds, joins the group by name and generates.
    It looks the definition and the group up by name, and its refusal says `the
    fylgja-artifacts repository must be connected and in-sync on main`
    (`internal/testsupport/infrahub.go`, `lookupByName` and the group's member check).
  - **Infrahub's Compose.** development.md describes the published file and an override
    beside it (the three services pinned to 1.11.2, Neo4j capped at heap 1g/2g and page
    cache 1g), in a directory of the operator's choosing; neither file is in this
    repository. `local/.env` holds the Compose values (`COMPOSE_PROJECT_NAME`, the initial
    admin token and password) beside Fylgja's, and `.env.example` names Fylgja's alone.
  - **The hand walk-through** the script records: development.md's Local environment
    table and paragraphs (Go through `go.mod`'s toolchain, containerlab with
    `clab_admins`, Docker, the AppArmor lines for SR Linux's `rsyslogd`, Infrahub, the
    Temporal CLI, `gnmic`, golangci-lint 2.14, both images, the cEOS import) and
    `CLAUDE.md`'s Environment (the Python venv with `infrahub-sdk[ctl]` and a `.gitignore`
    of `*` inside it).
  - **[verified-facts.md](../../docs/verified-facts.md)**: every fact verified on Ubuntu
    24.04.1, kernel 6.8, Docker 27.5.1 ([The host](../../docs/verified-facts.md#the-host)),
    to be re-verified on any upgrade. Its Infrahub section holds the five behaviours the
    roadmap names as candidate issues and the credential-less registration.
  - **The README**: [What it needs](../../README.md#what-it-needs) points at
    development.md for each prerequisite; the walk-throughs' sample output is from real
    runs; [Contributing](../../README.md#contributing) says the repository is read-only;
    there is no badge and no recording.
  - **The development host's Infrahub renders from the private copy** of the template,
    registered with a credential (D-044's context).
- **Verified at the cut** (2026-10-07, from a fresh clone of `a5225dd` on the development
  host): `make build` static, `make lint` clean, `make test` 28–38s wall uncached (the
  first run in a new directory the slowest), tier 2 in 422s, tier 3 `E2E-OK` with eight
  cases in 1019s (case 1 deploying `b9d53ebc…`), and both of the README's walk-throughs
  followed from its own instructions. The worker and the API's server run from this tree.

## What changes, and nothing else

1. **The bring-up script**: one script that takes a clean Ubuntu install to every tier
   passing, in the roadmap's four parts (toolchain, lab host, Infrahub, Fylgja), ending
   with `make build`, `make test`, `make test-contract` and the worker's and the server's
   start-up reports naming both packages. It imports the pinned cEOS tar when it finds
   one, and without one it goes on for SR Linux alone, naming the platforms the host can
   run ([Decided](#decided)). Its Infrahub part brings up the pinned Compose and gives
   `main` what development.md says it needs: the schema, the group, this repository
   registered, the import awaited, then the fixture seeded. development.md's walk-through
   becomes the script's record.
2. **Tier 3 by platform**: `scripts/e2e.sh` requires every package's image by default, as
   now, and takes an explicit platform list that narrows it: a narrowed run skips each
   case that needs a package outside the list or whose image is absent, and ends on a
   partial-pass line naming them ([Decided](#decided)). Test tooling, no product change.
3. **CI with a real Infrahub**: the `contract` job enabled, running the script's
   Infrahub part on a hosted `ubuntu-26.04` runner, then the `go generate` diff and tier
   2, on pushes to `main` alone; both jobs pinned to `ubuntu-26.04`; a badge in the
   README.
4. **Infrahub renders from this repository**: the development host's Infrahub registers
   this repository in place of the private copy (D-044), with the fixture id `b9d53ebc…`
   unmoved; the fixture tool's message names this repository's registration; the `ref`
   update question verified and recorded in verified-facts.md.
5. **The visible half**: the README's recorded session of a create, a step and a verify;
   `SECURITY.md`, the threat model and how to report a vulnerability; the `v0.1.0` tag
   with a static binary stamped by `make build VERSION=…` attached; `main` protected,
   issues open, pull requests not taken, and the topics; `docs/how-it-was-built.md`, one
   page; the Infrahub behaviours of verified-facts.md drafted as issues or discussions on
   `opsmill/infrahub`.
6. **The records**: development.md (the walk-through, CI, the registration, tier 3's
   platform list), verified-facts.md (every fact the script re-verifies on the new
   release, with its version and date), the glossary for any new term, the roadmap (the
   launch moved to Built, Next naming the first item after it), `CLAUDE.md`'s State
   rewritten whole and its Environment for the 26.04 host, verified-facts.md's The host
   for 26.04, and the README's What it needs and Tests pointing at the script and
   CI and saying what an SR Linux-only host gets: the cEOS image needed only for EOS and
   mixed twins and tier 3's EOS cases, and the walk-throughs, all SR Linux, unchanged.
7. **The repository goes public first**, before the script, CI and the registration are
   built and proved ([Decided](#decided)); what must precede the flip is the settings that
   refuse pull requests and protect `main`, `SECURITY.md`'s way to report a vulnerability,
   and one more read of the tree for anything private.

Nothing else moves. No product behaviour changes: bundle `4`, CTM `1`, PSP `0.6`,
`twin.json` `5`, contract `0.2`, findings `1`, the API `1`, the three goldens
(`23f86a26…`, `5773b6bb…`, `391bcb96…`), the live fixture id `b9d53ebc…`, every command,
workflow, activity and wire type, and the nine recorded histories are the cut's. A change
the script or CI needs in the fixture tool or `testsupport` is test tooling, named in the
spec; a product change found necessary is a defect, raised before it is made.

<a id="decided"></a>
## Decided

Each is one sentence, with its reason where the reason is not on disk.

- **The launch is `013-launch`, the first feature here, and M14's second half**; its spec,
  plan and research are public from their first line and cite this repository's documents
  alone (D-043).
- **One script, two consumers**: the setup of a fresh VM and CI on a hosted runner run the
  same script, CI running its Infrahub part alone (the roadmap).
- **Ubuntu 26.04 alone** (the roadmap's open question on releases, taken here): the script
  is written and proved on 26.04 and supports no other release, naming the release it
  finds and refusing another; CI's jobs, `unit` and `contract`, both name `ubuntu-26.04`,
  never `ubuntu-latest`, which GitHub moves from 24.04 to 26.04 between 2026-10-19 and
  2026-11-19 (checked 2026-10-07: `ubuntu-26.04` is generally available, 26.04.1 LTS with
  Docker 29.4.2 and Compose 5.1.3), so CI and the fresh VM run one release and a failure
  in that window is never a release change in disguise; the development host moves to
  26.04 as the operator verifies the script, and its 24.04.1 facts are re-verified there,
  Infrahub's Compose and override under Compose 5 among them.
- **The script's first run on the new release is the re-verification** that
  verified-facts.md asks for on any upgrade: what it finds is recorded in the feature's
  `research.md`, then in verified-facts.md with its version and date, and a fact that no
  longer holds is a finding, not a silent workaround.
- **The cEOS tar stays the operator's to provide**: account-gated, never vendored and
  never pulled (development.md).
- **An SR Linux-only path, and how the script finds the tar** (the roadmap's decision for
  the launch, taken here): the script looks for the tar at a path the operator gives,
  then in `local/` and the repository's parent directory, never in the repository root,
  which `.gitignore` does not cover and the converge loop commits from, so a 2 GB
  account-gated image is never staged; it takes only the file the package's version
  names (development.md's `cEOS64-lab-4.32.0.2F.tar`), checks it against a recorded
  checksum, since the image id changes on every import, imports it under exactly the
  reference `psp/arista_eos.yaml` names, and skips the import when that reference is
  present; without the tar it goes on for SR Linux alone, and its first and last reports
  name the platforms the host can run and where it looked.
- **Tier 3 is full coverage unless narrowed**: `scripts/e2e.sh` requires every package's
  image by default, so a bare `E2E-OK` keeps meaning all eight cases; an explicit platform
  list narrows a run, selecting by package, not by image (an image is present only under
  exactly the reference its package names, as the host check reads it), skips each case
  that needs another package or an absent account-gated image (today cases 6 and 8), and
  ends on a distinct partial-pass line naming the platforms and the skipped cases with
  why. The runs that need full coverage are the launch's exit, a milestone's close and the
  attended loop's live sessions; CI is not one, since tier 3 is never in CI (D-017).
- **CI's contract job runs on pushes to `main` alone**, and never under
  `pull_request_target`, which would run a fork's code with the job's secrets; tier 3 is
  never in CI (D-017).
- **The repository goes public before the script and CI are built and proved** (clarify
  (a), taken here, reversing the draft roadmap's public at the close): every
  registration the script, CI and the development host make is then the credential-less
  one a stranger makes, so no token for this repository is ever stored, in a repository
  secret or on a host, and nothing has to be dropped and re-proved at the close; the
  first public view is the README and the system as cut, and the script, CI, the
  recording and the release arrive in the open. The operator makes the flip, once the
  settings refuse pull requests and protect `main`, `SECURITY.md` says how to report a
  vulnerability, and the tree, this branch's work included, has been read once more for
  anything private.
- **Registration per D-044**: a `CoreReadOnlyRepository` on `main`, no credential, from
  the flip on: the development host's Infrahub registers this repository in place of the
  private copy as the launch's first work after the flip, and the private copy is no
  longer registered there afterwards.
- **The recorded session is an asciinema recording** of one create, step and verify on the
  development host, rendered to an animated SVG or GIF committed under `docs/` and
  embedded in the README, with the cast beside it, since GitHub does not play a cast in
  place; every credential is kept out of the frame (constitution X).
- **Contributions are not taken**: the README already says the repository is read-only,
  issues are welcome and pull requests are not taken; there is no `CONTRIBUTING.md`
  (Apache-2.0, `LICENSE`, settled before the cut).
- **Outward-facing acts are the operator's, or made with the operator's word in the
  session**: making the repository public, changing its settings and topics, publishing
  the release, and submitting an issue or a discussion. The OpsMill
  `infrahub-reporting-issues` skill shows each draft before anything is submitted.
- **A session never pushes** (`CLAUDE.md`); the operator pushes `origin`.
- **Commits are authored as this repository's first commit is**, with the
  `Co-Authored-By` trailer of the model that made them, since the README says an AI agent
  built Fylgja with a human deciding.
- **The command log is git-ignored here** (`commands/`, `specs/*/commands/`), so
  `make command-log` publishes and commits nothing, and the loop's stopping rule reads
  `tasks.md`'s tags.
- **The write-up summarises the private development record and does not cite it**
  (D-043): no link, path, commit hash or task number of that record.
- **The write-up's figures are derived from the private record**: a session here reads it
  on the development host, at a location the operator gives in that session and nothing
  here writes down, for the figures alone (hours per milestone, passes, model time); the
  figures and how each was counted go in this feature's `research.md` and the write-up,
  stated as derived from the private record and uncited, and nothing else of it crosses:
  no quotation, file name, path, commit hash, task number or feature's wording. The
  operator reads the figures before they are committed, since `research.md` is public
  from its first line, and the record stays reachable while the development host moves
  to 26.04.

<a id="open"></a>
## Open, for clarify

None. All five the draft left open are [decided](#decided): (a), the repository public
before the script and CI; (b), the SR Linux-only path; (c), Ubuntu 26.04 alone; (d), the
recorded session's form; (e), the write-up's figures derived from the private record.
Clarify asks only what specify finds underspecified.

<a id="left"></a>
## Left to the plan

Not questions for the operator, but the plan's to research and decide, each recorded in
its `research.md`: the script's language and place (bash under `scripts/`, as
`scripts/e2e.sh` is, or a Go tool), its stages and whether a second run on a set-up host
changes nothing; how its Infrahub part writes to `main` (the fixture tool, under its build
tag, or `infrahubctl` and object files from the venv); whether the Compose override and the
Compose values' names move into this repository; the fresh VM's size, which tier 3's
memory needs bound; how a hosted runner's time and memory hold Infrahub and the import, and whether the
contract job needs any secret at all once the registration needs no credential;
the release's build (by hand or a tag-triggered workflow); how GitHub's settings refuse
pull requests; which figures the write-up states and how each is counted from the
private record (what an hour, a pass and model time are); the recording's rendering (SVG or GIF, and the tool) and its size on the
README; whether each Infrahub behaviour is an issue or a discussion; and, for the
SR Linux-only path, where the cEOS tar's checksum is recorded and whether Arista publishes
one to record, how the script and `scripts/e2e.sh` take a path and a platform list (flag
or environment variable), how a case declares the packages it needs, and the partial-pass
line's exact form.

## Exit

- **On a fresh Ubuntu 26.04 VM**: from a clone and the cEOS tar, the
  script ends with tiers 1 and 2 passing and the worker's and the server's reports naming
  both packages; tier 3 is `E2E-OK` there once, all eight cases; what the script
  re-verified is in verified-facts.md.
- **The SR Linux-only path**: the script run once without the tar names SR Linux alone in
  its first and last reports and passes tiers 1 and 2; a tier 3 run narrowed to
  `nokia_srlinux` ends on the partial-pass line naming cases 6 and 8; a default run on
  that host refuses, naming the absent cEOS reference; a tar placed in the repository
  root is not found.
- **CI**: on a push to `main`, the `unit` and `contract` jobs pass, the contract job having
  brought up Infrahub, registered this repository, seeded and run tier 2; the README's
  badge shows it; a pull request runs the `unit` job alone.
- **Infrahub renders from this repository** on the development host: the private copy
  unregistered, the live fixture compiling to `b9d53ebc…`, tier 2 and tier 3 passing, the
  `ref` update question answered in verified-facts.md, the fixture tool's message
  reworded.
- **Visible**: the README with its recording, the badge and the script; `SECURITY.md`;
  `v0.1.0` with its static binary; the settings and topics; `docs/how-it-was-built.md`;
  each Infrahub behaviour filed or dropped with the operator's word, its link in
  verified-facts.md when filed.
- **Public**, by the operator's act before the script and CI are proved, CI's contract
  job and the fresh VM having registered this repository with no credential; at the close
  the front page read by the operator: README, badge, recording, `LICENSE`, `SECURITY.md`, the release, the diagrams.
- **Records**: the roadmap's Built table carries the launch and its Next names what comes
  after it; `CLAUDE.md`'s State is rewritten whole; development.md's walk-through is the
  script's record.
- **Owed before the work starts**: nothing. The development host is set up and verified,
  and its worker and server run from this tree.

<a id="references"></a>
## References

Everything specify needs, with what each gives. Read in this order after `CLAUDE.md`'s
list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Next](../../docs/roadmap.md#next), the Built table's M14 row, [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the feature's scope, item by item, its size, and the one decision named for it |
| [docs/decisions.md](../../docs/decisions.md): [D-043](../../docs/decisions.md#d-043), [D-044](../../docs/decisions.md#d-044), [D-017](../../docs/decisions.md#d-017), [D-028](../../docs/decisions.md#d-028), [D-042](../../docs/decisions.md#d-042), [D-001](../../docs/decisions.md#d-001) (Infrahub the source of truth, which Fylgja only reads, as [architecture §5](../../docs/architecture.md#5-stack) says; the fixture tool, which writes, is test tooling) | the decisions this feature executes and leans on; the numbering continues from D-044 |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 1.1.1: I, X; Development Workflow (three tiers, verification); Governance | the Constitution Check |
| [docs/development.md](../../docs/development.md): [Local environment](../../docs/development.md#local-environment) (the table, the environment variables, Temporal, the three processes, "What Infrahub needs", the fixture); [Build and make targets](../../docs/development.md#build-and-make-targets); [Test architecture](../../docs/development.md#test-architecture); [Spec Kit workflow](../../docs/development.md#spec-kit-workflow) | the hand walk-through the script becomes; what each tier needs; how the work flows here |
| [docs/verified-facts.md](../../docs/verified-facts.md): [Infrahub 1.11.2](../../docs/verified-facts.md#infrahub-1112) (the five behaviours and the registration), [containerlab 0.79.0](../../docs/verified-facts.md#containerlab-0790), [The host](../../docs/verified-facts.md#the-host) | what the script re-verifies on the new release, and the candidate issues |
| [docs/architecture.md](../../docs/architecture.md): [§4.5](../../docs/architecture.md#45-lab-host-containerlab-and-the-twin-directory), [§4.6](../../docs/architecture.md#46-operator-surface) (the API's server and its token), [§5](../../docs/architecture.md#5-stack) | the lab host the script sets up, and what `SECURITY.md` describes |
| [README.md](../../README.md): [What it needs](../../README.md#what-it-needs), the two walk-throughs, [Tests](../../README.md#tests), [Contributing](../../README.md#contributing) | the front page the launch finishes |
| [CLAUDE.md](../../CLAUDE.md): Environment, Build and test, State | the development host as set up, and the State the launch rewrites |
| [.github/workflows/ci.yml](../../.github/workflows/ci.yml) | CI as it stands, and the contract job to enable |
| [Makefile](../../Makefile) (`infrahub-schema`, `infrahub-seed`, `infrahub-clean`, `test-contract`, `test-e2e`, `build`'s `VERSION`), [.env.example](../../.env.example) | the targets the script and CI call, and the names `local/.env` is scaffolded from |
| [cmd/fylgja-fixture/main.go](../../cmd/fylgja-fixture/main.go), [internal/testsupport/infrahub.go](../../internal/testsupport/infrahub.go) (`LoadSchema`, `ArtifactDefinitionName`, `ArtifactGroupName`, `lookupByName`) | what the fixture tool writes, and the message D-044 rewords |
| [.infrahub.yml](../../.infrahub.yml), [infrahub/](../../infrahub/), [schema/](../../schema/) and [schema/README.md](../../schema/README.md) | the template, the query and the schema the Infrahub part registers and loads |
| [scripts/e2e.sh](../../scripts/e2e.sh) | tier 3 as it runs, its preconditions (both images, the dev server, a worker), and the shape of a bash script here |
| [psp/README.md](../../psp/README.md) | which platforms are supported, for the SR Linux-only path |
