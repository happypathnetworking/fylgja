# Specify brief: M14 feature 2 of 2 — the launch

What `/speckit-specify` reads for the launch, beside the roadmap's
[Next section](../../docs/roadmap.md#next), [D-043](../../docs/decisions.md#d-043) and
[D-044](../../docs/decisions.md#d-044). Written 2026-10-07, the day this repository's first
commit (`a5225dd`, M14's cut) was pushed and verified, before any research, so that the
prompt carries decisions and not restatement
([development.md](../../docs/development.md#spec-kit-workflow), "The specify prompt carries
decisions"). It is a draft for the operator's confirmation. Five questions are left for
clarify ([Open](#open)), which runs in specify's context and asks only those and what
specify finds underspecified. Specify what the operator gets, not a new design. The
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
  ending with the repository public. Its size is 10–14 hours, kept whole because both of
  the script's consumers run the one script; the spec may still split CI out if the runner
  needs more than the script gives. Its [Decisions the order
  needs](../../docs/roadmap.md#decisions-the-order-needs) names one for the launch: whether
  the script offers an SR Linux-only path.
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
   start-up reports naming both packages. It asks for the cEOS tar and refuses to continue
   without it (unless clarify (b) gives an SR Linux-only path). Its Infrahub part brings
   up the pinned Compose and gives `main` what development.md says it needs: the schema,
   the group, this repository registered, the import awaited, then the fixture seeded.
   development.md's walk-through becomes the script's record.
2. **CI with a real Infrahub**: the `contract` job enabled, running the script's
   Infrahub part on a hosted runner, then the `go generate` diff and tier 2, on pushes to
   `main` alone; a badge in the README.
3. **Infrahub renders from this repository**: the development host's Infrahub registers
   this repository in place of the private copy (D-044), with the fixture id `b9d53ebc…`
   unmoved; the fixture tool's message names this repository's registration; the `ref`
   update question verified and recorded in verified-facts.md.
4. **The visible half**: the README's recorded session of a create, a step and a verify;
   `SECURITY.md`, the threat model and how to report a vulnerability; the `v0.1.0` tag
   with a static binary stamped by `make build VERSION=…` attached; `main` protected,
   issues open, pull requests not taken, and the topics; `docs/how-it-was-built.md`, one
   page; the Infrahub behaviours of verified-facts.md drafted as issues or discussions on
   `opsmill/infrahub`.
5. **The records**: development.md (the walk-through, CI, the registration),
   verified-facts.md (every fact the script re-verifies on the new release, with its
   version and date), the glossary for any new term, the roadmap (the launch moved to
   Built, Next naming the first item after it), `CLAUDE.md`'s State rewritten whole, and
   the README's What it needs and Tests pointing at the script and CI.
6. **The repository goes public** at the launch's close, so the first view has the script,
   CI and the README.

Nothing else moves. No product behaviour changes: bundle `4`, CTM `1`, PSP `0.6`,
`twin.json` `5`, contract `0.2`, findings `1`, the API `1`, the three goldens
(`23f86a26…`, `5773b6bb…`, `391bcb96…`), the live fixture id `b9d53ebc…`, every command,
workflow, activity and wire type, and the nine recorded histories are the cut's. A change
the script or CI needs in the fixture tool or `testsupport` is test tooling, named in the
spec; a product change found necessary is a defect, raised before it is made.

## Decided

Each is one sentence, with its reason where the reason is not on disk.

- **The launch is `013-launch`, the first feature here, and M14's second half**; its spec,
  plan and research are public from their first line and cite this repository's documents
  alone (D-043).
- **One script, two consumers**: the setup of a fresh VM and CI on a hosted runner run the
  same script, CI running its Infrahub part alone (the roadmap).
- **The script's first run on the new release is the re-verification** that
  verified-facts.md asks for on any upgrade: what it finds is recorded in the feature's
  `research.md`, then in verified-facts.md with its version and date, and a fact that no
  longer holds is a finding, not a silent workaround.
- **The cEOS tar stays the operator's to provide**: account-gated, never vendored and
  never pulled (development.md); the script asks for it and refuses without it, unless
  clarify (b) gives an SR Linux-only path, which it then names as such.
- **CI's contract job runs on pushes to `main` alone**, and never under
  `pull_request_target`, which would run a fork's code with the job's secrets; tier 3 is
  never in CI (D-017).
- **Registration per D-044**: a `CoreReadOnlyRepository` on `main`, no credential, once
  this repository is public; the private copy is no longer registered on the development
  host afterwards.
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

<a id="open"></a>
## Open, for clarify

Five, each with its options and this brief's lean. (a) and (c) need research at plan
whatever the answer.

- **(a) The order of going public and registering this repository.** D-044's registration
  needs no credential only once the repository is public, and the roadmap makes it public
  at the launch's close, after the script and CI are in; but the fresh VM's run and CI's
  contract job both register the template while the repository is still private.
  *Lean:* while private, both register this repository with a credential (CI with a
  repository secret holding a fine-grained read-only token, the fresh VM with the
  operator's), which the plan verifies against 1.11.2; at the close the operator makes the
  repository public, the credential is dropped from both, and CI and the development
  host run once more with none. *Alternatives:* make the repository public first, then
  build and prove the script and CI in the open; or register the private copy's
  remote in CI and on the fresh VM until the close.
- **(b) An SR Linux-only path.** Without the cEOS tar, tiers 1 and 2 still pass and tier 3
  passes without its EOS cases. *Lean:* yes: the script takes an explicit choice to skip
  EOS, says so at its start and in its closing report, and the README says what that
  reader gets; without the choice and without the tar, it refuses. *Alternative:* no; the
  script always refuses without the tar.
- **(c) Which Ubuntu releases the script supports.** The roadmap says a clean Ubuntu 26.04
  install; the development host is 24.04.1, and a hosted runner's images may lag a new
  release. *Lean:* 26.04 is the release the script is written and proved on (the fresh
  VM), and CI runs on GitHub's `ubuntu-26.04` image if the plan finds it offered, else
  on 24.04 for the Infrahub part alone, which needs Docker and nothing of the kernel's;
  the development host stays on 24.04 and is not rebuilt. *Alternatives:* 24.04 and 26.04
  both supported and both proved; or 24.04 alone until the development host moves.
- **(d) The recorded session's form.** *Lean:* an asciinema recording of one create, step
  and verify on the development host, rendered to an animated SVG or GIF committed under
  `docs/` and embedded in the README, with the cast beside it; every credential kept out
  of the frame. *Alternatives:* the cast alone, linked from the README (GitHub does not
  play it in place); or a video attached to the release.
- **(e) The write-up's figures.** It summarises hours and passes the private record holds.
  *Lean:* the operator gives the figures (hours per milestone, passes, model time) as a
  table in this feature's `research.md`, stated there as the operator's and used without a
  link; nothing of the private record is read by a session here. *Alternative:* a session
  here reads the private record on the development host and states the figures with no
  citation; or the write-up gives no figures.

<a id="left"></a>
## Left to the plan

Not questions for the operator, but the plan's to research and decide, each recorded in
its `research.md`: the script's language and place (bash under `scripts/`, as
`scripts/e2e.sh` is, or a Go tool), its stages and whether a second run on a set-up host
changes nothing; how its Infrahub part writes to `main` (the fixture tool, under its build
tag, or `infrahubctl` and object files from the venv); whether the Compose override and the
Compose values' names move into this repository; the fresh VM's size, which tier 3's
memory needs bound; how a hosted runner's time and memory hold Infrahub and the import;
the release's build (by hand or a tag-triggered workflow); how GitHub's settings refuse
pull requests; and whether each Infrahub behaviour is an issue or a discussion.

## Exit

- **On a fresh VM of the release clarify (c) names**: from a clone and the cEOS tar, the
  script ends with tiers 1 and 2 passing and the worker's and the server's reports naming
  both packages; tier 3 is `E2E-OK` there once; what the script re-verified is in
  verified-facts.md.
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
- **Public**, by the operator's act at the close, and the front page then read by the
  operator: README, badge, recording, `LICENSE`, `SECURITY.md`, the release, the diagrams.
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
