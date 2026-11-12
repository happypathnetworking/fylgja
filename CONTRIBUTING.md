# Contributing

> **Not accepting contributions yet.** Thank you for your interest in Fylgja. The project is
> at an early stage: the core is being built phase by phase from
> [design/core.md](design/core.md), and its formats and API are still settling, so outside
> issues and pull requests are not being taken for now. This page describes how the project
> itself works, and will say when that changes. A security concern is always welcome, as
> [SECURITY.md](SECURITY.md) describes.

How to set up, build, test and change fylgja-core. The project's governance and design live
in [`design/`](design/): the system in [architecture.md](design/architecture.md), the rules
every change keeps in the [constitution](design/constitution.md), and the reasons in the
[decision log](design/decisions.md). User-facing documentation lives in [`docs/`](docs/).

## How a change is made

A change is a **design document, then a decision entry where it changes a decision, then a
pull request** ([D-033](design/decisions.md#d-033)).

1. **Design.** A feature larger than a fix gets a design document under `design/`.
   It covers:
   - intent;
   - requirements;
   - the shape;
   - what it retires;
   - how it is verified.

   [design/core.md](design/core.md) is the current one, and its "Sequence" is the build
   order.
2. **Decide.** A changed decision is a new entry in [decisions.md](design/decisions.md) that
   supersedes the old one. The log is append-only. Check the rejected alternatives before
   proposing one.
   - **The constitution changes only by citing such an entry,** with a semver bump.
   - **Then search** [architecture.md](design/architecture.md) for the old position.
3. **Formats change with the code.** Each format has one current version, specified by its
   file in [`formats/`](formats/README.md) ([D-002](design/decisions.md#d-002)). A change to a
   format is made there, in the same change as the code that reads or writes it.
4. **Verify against the running system** before code depends on how containerlab,
   clabernetes or a network operating system behaves. Record the result, with its version
   and date, in [verified-facts.md](design/verified-facts.md).
5. **Pull request.**
   - Conventional-commit messages whose body says *why*.
   - A new term goes in [glossary.md](docs/glossary.md) in the same change.

## How a phase is built

A phase is one item of the "Sequence" in [design/core.md](design/core.md). It goes through
the flow above in four stages ([D-080](design/decisions.md#d-080)). The procedure an agent follows, with the rules every
implementer and reviewer is handed and the template for a phase's branch plan, is
[`.claude/skills/build-phase/`](.claude/skills/build-phase/SKILL.md); this section is its
statement for people, and is the one that is right where the two disagree.

1. **Settle.** On the branch `phase-N-design`, cut from `main`:
   - the behaviour the phase rests on is read on the running systems and recorded in
     [verified-facts.md](design/verified-facts.md), in a commit of its own;
   - the phase's section goes into [design/core.md](design/core.md), with its decision
     entries: what the phase is for, what is settled before code, the formats touched, its
     non-goals and anti-goals, its plans, when it is done, and what is left to the builder;
   - a fresh reader checks the draft against the code before the maintainer approves it.
2. **Plan.** One working document for each of the design's plans, and a "plan 0" that holds
   the branches, the order and the names the plans share. They live under `local/plans/`,
   git-ignored: a plan is how a branch gets built, and the design and the decision log are
   the record.
3. **Execute.** The integration branch `phase-N-integration` is cut from `main` with the
   design merged in. Each plan is a branch `phase-N/<n>-<name>` in a worktree beside the
   repository (`../fylgja-core-wt/<n>-<name>`).
   - Each task is built from its own brief, test first, and its diff is read by a fresh
     reviewer before the next task starts.
   - Each decision taken along the way is written down as a ruling, with what it costs if
     wrong.
   - A plan's whole branch is reviewed once more, then merged into the integration branch.
   - Live runs are one at a time.
4. **Land.** On the maintainer's word:
   - the phase is written as built on the integration branch: a decision entry for each
     place the build departed from a decision, the sentences it made untrue corrected, and
     the item in "Sequence" marked done, with what it left to later phases;
   - the integration branch is squashed onto `main` as one commit;
   - its history is kept under the local tag `archive/phase-N-integration`;
   - the build's records (ledgers, briefs, reviews, rulings, run logs) go to
     `local/sdd/phase-N/`.

## Tooling

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 | [D-001](design/decisions.md#d-001) |
| httpx, jsonschema, referencing, PyYAML | `>=0.27.0,<1`, `>=4.18.0,<5`, `>=0.28.4,<1`, `>=6.0.3,<7`; in the `server` extra 0.28.1, 4.26.0, 0.37.0, 6.0.3 | The base install, the model and the client ([D-084](design/decisions.md#d-084)): the formats' validation, the packages' YAML and the client's HTTP; the server's readiness wait and push use the same httpx ([D-039](design/decisions.md#d-039)) |
| Starlette, uvicorn | 1.9.0, 0.54.0 | The `server` extra: the server's ASGI application and the process that serves it ([D-025](design/decisions.md#d-025)) |
| pygnmi, grpcio, protobuf | 0.8.15, 1.84.0, 7.36.2 | The `server` extra: verify's gNMI reader ([D-052](design/decisions.md#d-052)) |
| lightkube, lightkube-models, httpx2, msgspec | 1.0.1, 1.37.0.8, 2.16.0, 0.22.0 | The `server` extra: the clabernetes driver's Kubernetes calls ([D-064](design/decisions.md#d-064)) |
| pytest, ruff, mypy | 9.2.0, 0.17.3, 2.4.0 | mypy in strict mode (Constitution I) |
| rfc8785 | 0.1.4 | Tests only: an independent RFC 8785 implementation that the blueprint id is checked against |
| openssl | the host's (3.5.5) | Tests only: the pure tier's TLS tests make a self-signed certificate and key with it (`core/tests/tls.py`); without it they are skipped, and fail when `CI` is set |
| containerlab, Docker | 0.81.0, 29.8.1 | The local driver and the live tier. containerlab is pinned to the version clabernetes 0.10.1 embeds, so the kinds behave alike on both drivers |
| Versity S3 Gateway | v1.10.0 | The object store's live test, and development's endpoint ([D-061](design/decisions.md#d-061)) |
| clabernetes, k3s | 0.10.1, v1.37.1+k3s1 | The clabernetes driver's development ([D-060](design/decisions.md#d-060)) |
| crane | 0.22.1 | Pushes the core's image to the cluster's private registry from a tarball Docker saved ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| kubectl | 1.37.2, its kustomize v5.8.1 | Builds the core's kustomize base under `deploy/` and applies a site's overlay ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| Infrahub, Docker Compose | 1.11.11, v5.6.0 | The development Infrahub (`make infrahub-up`): Infrahub's published Compose file for its version, fetched into `local/infrahub/` and never vendored, run by Docker's Compose plugin ([D-083](design/decisions.md#d-083)) |
| infrahub-sdk\[ctl\] | 1.23.2 | `infrahubctl`, which loads the schema library into the development Infrahub (`make infrahub-register`), in a venv of its own under `local/infrahub/` so that the SDK meets nothing else; no code of the tree imports it ([D-083](design/decisions.md#d-083)) |
| Prefect | 3.9.2 | The example orchestrator's edge alone: the two deployments Infrahub's checks start ([D-085](design/decisions.md#d-085)). Pinned as read on the development host: it was three days old when the design chose it, under the two weeks every other pin keeps |

Each pin, the `server` extra's among them, and each floor of the base install is a release at
least two weeks old when it was chosen, but Prefect's, as its row says. `make venv` builds
`core/.venv` from `core[server,dev]`, the reader's `readers/infrahub[dev]` and the example
orchestrator's `orchestrator[dev]`, each package installed editable: the versions every tier
runs on. A venv inside the tree carries a `.gitignore` of `*`.

## Make targets

| Target | What it does |
|---|---|
| `make venv` | The core's venv, `core/.venv`, from `core[server,dev]`, then the reader's `readers/infrahub[dev]`, then the example orchestrator's `orchestrator[dev]`: each package editable, at the versions every tier runs on |
| `make lint` | ruff over `core/`, `scripts/` and `infrahub/`, then mypy in strict mode over the core, its tests and `scripts/`, and again, apart, over `infrahub/seed/`, `infrahub/tests/` and `scripts/infrahub_dev.py`, since the two directories of tests name modules alike; then the same over the reader, `readers/infrahub/`, and over `orchestrator/` |
| `make test` | The pure tier: no infrastructure. `core/tests/`, then `infrahub/tests/`, then the reader's, then the example orchestrator's. Gates every pull request |
| `make live` | The live tier on the local driver: the driver's own modules under `core/tests/live/`, then the conformance suite on the local harness. The driver's own: readiness and the push on one SR Linux and one cEOS node booted under containerlab (`core/tests/live/test_push.py`); labs through the local driver, `admit`, `apply`, `inspect` and `destroy`, the residue rule and two labs at once (`core/tests/live/test_containerlab_driver_live.py`); three labs applied at once, their deploys one after the other, with the host's load and connections read (`core/tests/live/test_many_labs_live.py`, about 2.5 minutes alone); `changes` held to containerlab's own dry run for every step fixture, with the hot-add recreate of two cEOS nodes and `exec` in a probe host (`core/tests/live/test_changes_live.py`, about 4.5 minutes alone); verify over gNMI on a probed twin, with a node stopped and started by containerlab and by Docker, and a configured cEOS node's host name (`core/tests/live/test_verify_live.py`, about 5 minutes alone); the trigger and the restore through Docker's own restart paths, the loop run in-process with its resync an hour away: a node restarted by `docker restart` and one started again by Docker's restart policy, each pushed again by a restore the driver's events started within seconds (its links are not restored), and one removed, reported missing once its boot window passed (`core/tests/live/test_restore_live.py`, about 4 minutes alone); and the object store against Versity S3 Gateway under Docker, the store contract whole and every compare-and-set raced by 32 stores (`core/tests/live/test_object_store_live.py`, about 1 minute alone). Then the suite, as `make conformance DRIVER=containerlab` runs it (below), its many-twins scenario among it, about 36 minutes of the whole. 165 tests by collection; the tier was last timed whole at about 54 minutes, with the cluster quiet, and the suite has since grown from about 31 minutes to 36, so about 59 minutes, a derivation and not a reading. Load `local/.env` first |
| `make cluster` | The cluster tier: the clabernetes driver's calls on the k3s cluster, from the development host. The driver's reach into Kubernetes, every call of `LightKube` read on a two-node SR Linux twin (`core/tests/cluster/test_kube_cluster.py`, 1 to 2 minutes alone); the driver as the server makes it on a three-node twin: `admit` against a namespace that is not the twin's, `apply` with the root logger at DEBUG and its repeat, `exec`, a node's container ended in its pod, a pod deleted, `reconfigure`, `destroy` and the residue (`core/tests/cluster/test_clabernetes_driver_cluster.py`, about 4 minutes alone); and `changes` held to the pods' uids for every step fixture, with the hot-add recreate of two cEOS nodes killed before its deletions and resumed (`core/tests/cluster/test_clabernetes_changes_cluster.py`, about 10 minutes alone); and the trigger and the restore through the loop, run in-process with the resync an hour away, on a two-node twin stepped twice: a pod deleted, a container ended in its pod and that pod replaced by the driver, a probe host's and a cEOS node's pods deleted, each restored without the resync, the settled twin's pods watched for three minutes, and a watch asked at a compacted version (`core/tests/cluster/test_restore_cluster.py`, about 14 minutes alone); and the Lease, on a Lease of its own in the kubeconfig's default namespace held by two holders in one process: taken, waited for, taken over 15 s after its holder went silent and released (`core/tests/cluster/test_lease_cluster.py`, about 30 s alone). About 30 minutes. Load `local/.env` first, with `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE`, `FYLGJA_POD_CIDR` and the cEOS pull credential set. With the core deployed on the cluster, its Deployment is scaled to no replica first and back to one after ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make conformance DRIVER=containerlab\|clabernetes` | The driver conformance suite alone (`core/tests/conformance/`): one set of scenarios, written once, on the harness of the driver `DRIVER` names, `containerlab` by default; any other name is refused in one line. A twin created and shown; stepped through every step fixture with verify after each and the burst held, and the step's refusals; the core killed at each phase boundary of a create and of a step, during an apply and during a destroy, a waiting CLI riding through, a deletion after a kill, and a step cancelled; a node replaced behind the core and one stopped; leftovers read by label; node access through each node's own transport; and isolation over TCP between two twins and from a third namespace, where the driver declares it. Then many twins at once (`core/tests/conformance/test_many.py`): the harness's count, three here and five on the cluster, created together and all Ready, each stepped while the others run with no node unread, a twin of forty nodes refused in a dry run and at its create with the capacity read agreeing, and every twin destroyed, about 5 minutes here and 8 on the cluster. The scenario needs a band of room: about 4.5 CPU and 17 GiB free here for its three twins and 7.5 CPU and 28 GiB on the cluster for its five, and, with them up, under about 80 GiB free on either, since the forty-node twin must be refused; on a roomier runtime its dry run is answered and the scenario fails there, having made no twin of it. `containerlab` runs `fylgja-core-server` on this host under the live tier's marker: 54 tests, about 36 minutes. `clabernetes` drives the core deployed on the cluster over TLS, killing it by its pod, under the cluster tier's marker: 54 tests, about 71 minutes. Load `local/.env` first, and for the cluster the suite's own variables ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |
| `make wheelcheck` | Builds the core's wheel from `core/` and `formats/`, which carries the core's formats and no other, and installs it into two empty venvs outside the tree: with the `server` extra, where it validates a fixture and the server's modules import; and alone, each of the base's four libraries at the floor of its range, where the model and the client import, a run is followed over a fake transport and `fylgja-core-server` refuses in one line; then the reader's wheel, from `readers/infrahub/` and `formats/` and carrying its one format, `infrahub-reader-1`, and no other, with its GraphQL documents, beside the base alone in a third, where the seed's reader document decodes, the command's module imports with nothing of the server, Prefect or Infrahub's SDK, and `fylgja-infrahub --help` exits 0; then the example orchestrator's wheel, from `orchestrator/` and `formats/` and carrying its two formats and no other, with its change source's GraphQL documents, beside the base and the reader's wheel alone in a fourth, where a plan and a rehearsal validate, the rehearsal library imports with nothing of the server, the reader or Prefect loaded, the command's module with nothing of the server or Prefect, nothing of the server's libraries is installed but the two Prefect brings, starlette and uvicorn, and `fylgja-orchestrator --help` exits 0 ([D-066](design/decisions.md#d-066), [D-084](design/decisions.md#d-084)). Needs the network, so it is no part of `make test`; CI runs it on every push to `main` and every pull request |
| `make image` | Builds the core's image from the `Dockerfile` at the root ([D-062](design/decisions.md#d-062)) as `fylgja-core:<tag>`, the tag the commit's first 12 characters, with `-dirty` where `git status --porcelain` prints anything. Its build context is `.dockerignore`'s allow-list, so nothing under `local/` reaches a layer. Needs Docker and the network |
| `make imagecheck` | Builds the image, then runs it: its user is 10001; given only `FYLGJA_STORE` and a `FYLGJA_TOKENS` that names no file, it exits 2 naming `FYLGJA_TOKENS`, its packages loaded against the wheel's formats; and the formats it carries are the core's, `CORE_FORMATS` in `core/setup.py`, equal to `formats/`'s by name and by bytes; and its copies of `psp/` and `probes/` hold the files git tracks there and no other, by path, so a file git ignores there (an editor's `*.swp`, a nested `local/`), which reaches the image with no `-dirty` tag, fails it. Prints the tag it checked last. CI runs it on every push to `main` and every pull request, and pushes nothing |
| `make infrahub-up` | The development Infrahub, the Compose project `fylgja-core-infrahub` at `INFRAHUB_VERSION` (1.11.11), run by `scripts/infrahub_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its eight names ([`.env.example`](.env.example)) that the file does not hold, generated and never printed, and changes no line already there, since a token made again would not open the kept database; a name the file holds with no value (`NAME=`, `NAME=""`, read from its last line where it has several) is refused, exit 2 and before anything is fetched or started, naming it, since Compose would replace it by the published file's own default; so is `NAME= # a note`, which a shell reads as empty and Compose as the text `# a note`; makes `local/infrahub/repos/` (mode `0700`) where it is absent; fetches Infrahub's published Compose file for the version into `local/infrahub/` once; starts the project with `infrahub/dev/compose.override.yml`, asking Compose once more where its first start fails; and waits up to 600 s for `/api/info` to answer that version, failing at once on another. `VERSION` is the make variable's whatever the shell or `local/.env` holds, and Compose is given none of the eight names and no other name beginning `INFRAHUB_` from the shell, whatever it exports, so that it reads them from `local/.env` alone or takes the published file's defaults: an `INFRAHUB_ADDRESS` exported for a client would otherwise be the task workers' address of Infrahub. The task workers mount the main checkout's `.git` and `local/infrahub/repos/` read-only, and nothing else of the checkout, and are given the edge's Prefect's address and basic auth ([Running the example orchestrator](#running-the-example-orchestrator)). About 3.5 minutes on new volumes and 1.5 minutes on kept ones; it then holds about 4.5 GiB. Needs Docker, and the network for the first fetch |
| `make infrahub-down` | Stops the development Infrahub (`docker compose stop --timeout 60`), in 20 to 50 s: each container is given 60 s to exit by itself, since Compose's own 10 s killed Neo4j, which needs about 11 s, and the server once took 31 s. Its containers, network and volumes and everything under `local/infrahub/` are kept, port 8000 and the memory released, and `make infrahub-up` starts it again. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volumes (`down -v`), and `local/infrahub/seed.json` with them; `local/.env` and the rest of `local/infrahub/`, the fetched file among it, stay. It is stopped for every live, cluster or conformance run |
| `make infrahub-register` | The schema library, the group and this repository's registration on the development Infrahub's `main` (`infrahub/seed/register.py`), at `REF`, the branch checked out, from a worktree too, and that branch's commit; an empty `REF`, a detached head, is refused in one line. The library under `infrahub/schema/dcim/` is loaded by `infrahubctl`, given 600 s (`INFRAHUB_TIMEOUT`), where `main` holds none of its kinds, and `main` is read for up to 120 s until it lists them all; a `main` holding part of them is refused with nothing written. The group `fylgja-devices` is made where it is not there. The read-only repository `fylgja` is registered from the main checkout's `.git`, mounted at `/srv/fylgja`: created where there is none; its `ref` updated and its last commit imported where it names another branch; its last commit imported where it reads another commit; then read for up to 300 s until it reads the commit `in-sync` and `online`, with the artifact definition `device-config` on `main`. Then each running task worker of the project is read by `docker` for the tree of that commit, `/opt/infrahub/git/<the registration's id>/commits/<the commit>`: a recreated worker holds no clone, and a check Infrahub runs on it fails, so one lacking the tree is not settled. Its import is asked, at once where the run sent nothing and else 30 s on, and again every 30 s until each holds it, within 300 s: an import with no new commit clones on the one worker that runs it, and after a new commit's import each worker held the tree by an import or a pull of its own, Infrahub's fetch to each beginning after. One already there, settled and its commit's tree on each worker is sent nothing. Its first run builds `infrahubctl`'s venv, `local/infrahub/.venv/`, in about 45 s. About 2.5 minutes on an empty instance, read once, and seconds where all of it is there. Load `local/.env` first |
| `make infrahub-seed` | The fixture network on the development Infrahub's `main`, and the branch `SEED_BRANCH` (`third-link`) with its two staged edits, each regenerated, timed and marked, and with `PROPOSED_CHANGE=1` its proposed change (`infrahub/seed/seed.py`). It is refused with nothing written where `main` holds no artifact definition `device-config` (run `make infrahub-register` first). The reader's kind `FylgjaProbe`, `readers/infrahub/schema/fylgja-probe.yml`, and the example's stage kind `FylgjaStage`, `infrahub/schema/fylgja-stage.yml`, each passed as `--schema`, are then loaded on `main` by `infrahubctl` where `main` lacks them, and `main` read for up to 120 s until it lists each. `infrahub/seed/main/`'s object files are loaded by `infrahubctl`, one at a time in the order of their names, where `main` holds none of the devices they say: the manufacturer, the site `lab` under its metro, country and region, the platform, the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json` with their ports and addresses, each a member of `fylgja-devices`, the fixture's cables less the one between `n1` and `n3`, and the probe `n1-loop` of `three-node-probed.json`. Where `main` holds all three, nothing is loaded, since a load would take each device out of the query groups Infrahub joined it to at its first generation; so a hand edit on `main` is not undone by a seed, and a purge and a seed undo it; so too a `main` seeded before the probe's kind existed, which holds no probe, is purged and seeded again. A `main` holding part of them is refused with nothing written. The configurations are then generated and waited for, up to 180 s, until each device tagged `fylgja` has its artifact `device-config` `Ready` and each device the run made shows a checksum that moved; an artifact reading `Error` ends the wait at once. What an earlier seed left of the branch is then removed, whether or not the branch is listed: every `FylgjaStage` whose `branch` names it, since a mark outlives its branch, and its open proposed change, which Infrahub would keep open after the branch's delete. The branch is then made anew from `main`, after the registration's import ([D-088](design/decisions.md#d-088)): one an earlier seed left is deleted first, and the branch, made with `sync_with_git: false`, is refused where it does not read the artifact definition; a create that fails or goes unanswered is read for its branch for up to 120 s. On it, in order, `infrahub/seed/stages/1-third-link.yml` adds the cable between `n1` and `n3`, after which the network is `three-node.json`'s, and `2-n1-address.yml` the address `192.0.2.1/24` on its `n1` end. After each, the configurations are generated and waited for, up to 180 s, until each device the edit changes shows a checksum that moved, and the stage's time is the reader's `head` of the branch, the first instant after its latest write, read with the reader's token, `FYLGJA_INFRAHUB_TOKEN`, once two readings of it 10 s apart agree, within 120 s, so that `seed.json` and a read at its times cannot disagree; a `head` refused because a list it read was not whole, as the event log once was just after a generation, is read again, and one refused otherwise ends the seed. The stage is then marked: one `FylgjaStage` written on `main`, naming the branch, the stage's label and its time as `as_of`, verbatim. With `PROPOSED_CHANGE=1`, and no other value, the branch's proposed change into `main`, not a draft, named `Rehearse third-link`, is made last; without it the seed makes none, and the maintainer's opening one is what starts the rehearsal, since Infrahub runs a proposed change's checks when it is created ([D-088](design/decisions.md#d-088)). So every run leaves the branch's marks and, by the flag, its proposed change its own, and no other. The reader's connection is made before anything is removed or written: its token not set, or a variable not of its form, is exit 2, and Infrahub refusing it exit 1. `local/infrahub/seed.json` is removed before anything is written and written whole at the end, `{"branch", "scope": "tag:fylgja", "stages": [{"label", "at"}, …], "marks": [<label>, …], "proposed_change": {"id", "name"} | null}`, the stages and the marks in order; a run that fails or lapses leaves none. About 1.5 to 2 minutes on a seeded `main`: 93 s with no branch to delete, and 97 to 113 s remaking it; with the marks, 107 s and 137 s, and 115 s and 119 s with the proposed change; seeding an empty `main`, the kind and the probe among it, took 273 s. Load `local/.env` first |
| `make contract` | The contract tier (below), `infrahub/tests/contract/`, then the reader's, `readers/infrahub/tests/contract/`, and then the example orchestrator's, `orchestrator/tests/contract/`, against the running development Infrahub, with `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` set on its own command lines. One module of the reader's is run as its line runs the reader's, by its path in place of `tests/contract`. The reader's line, 30 tests, took 757 s run alone, measured once since a branch's events take in `main`'s up to its branch point, and 396 s and 402 s in two runs before; 895 s within the whole tier below. The registration's tests read the task workers' clones by `docker`. The example orchestrator's tests need its account's token, `make orchestrator-env`'s, and the development Prefect and runner down (`make prefect-down`): they start a Prefect of their own on loopback, and stop where anything listens on port 4200, which Infrahub's checks of the proposed changes they make would reach. The orchestrator's line, 11 tests, took 722 s, and the tier whole 1,879 s, the reader's line 895 s of it, each measured once, on 2026-11-11. On 2026-11-12, with the cancel test's `timeout` 660, the three lines took 254.12 s, 1782.90 s and 1469.00 s, measured once: 3,506.02 s summed (a derivation, pytest's three times added). Load `local/.env` first |
| `make orchestrator-env` | The example orchestrator's lines in `local/.env` (`scripts/edge_dev.py env`), each written only where the file lacks it or holds it empty, its mode kept, and printed by its name and never its value: `FYLGJA_ORCHESTRATOR_AUTH`, the basic auth `fylgja:<generated>` that the edge's Prefect and the task workers share; `FYLGJA_ORCHESTRATOR_API_TOKEN`, the runner's token of the core's, generated, its hash appended with the principal `orchestrator` to the token file `FYLGJA_TOKENS` names, its mode kept: where that is not set, or names no file, which the core would not read, it is refused in one line with nothing written; after which the core is restarted to read the file; `FYLGJA_ORCHESTRATOR_SCOPE`, `local/infrahub/seed.json`'s scope, else the seed's own; `FYLGJA_ORCHESTRATOR_READER`, the main checkout's `infrahub/seed/reader.yaml`; and `FYLGJA_ORCHESTRATOR_ROOT`, its `local/orchestrator/`. Then `infrahub/seed/account.py`, as the admin: the Infrahub account `fylgja-orchestrator`, its group and its one role, held to exactly four permissions, `object:Core:ChangeThread:create:allow_default`, `object:Core:ThreadComment:create:allow_default`, `global:edit_default_branch:allow_default` and the instance's own `object:*:*:view:allow_all`; and its token, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, made by the account's own login, where the line is missing, or replaced in place where Infrahub refuses the line's token, so the target is run again after a purge. A second run writes nothing. `account.py`, run again with the line accepted, took 0.8 s. Needs the development Infrahub up; load `local/.env` first |
| `make prefect-up` | The edge's Prefect (`scripts/edge_dev.py prefect-up`), `core/.venv`'s `prefect server start --no-ui` on port 4200 of the Docker bridge's gateway, which the task workers reach as `host.docker.internal`, or of `PREFECT_BIND` where it is set; in a session of its own, under `local/prefect/` (its home, its database, `server.log` and `server.pid`), its basic auth `FYLGJA_ORCHESTRATOR_AUTH` given in its environment and never as an argument, analytics off; waited for up to 90 s until `/api/health` answers, 8.5 s after the target began, on a `local/prefect/` an earlier run had used, read once. A server it started that runs still is said to be up. Anything else listening on port 4200, on any address, is refused in one line naming the port and the address, with nothing started and nothing stopped: it is another project's. Load `local/.env` first |
| `make prefect-down` | Ends the server `local/prefect/server.pid` names, by SIGTERM to its session and SIGKILL after 30 s, only where that process is this project's Prefect server, its command line `prefect` and `server` and its `PREFECT_HOME` `local/prefect/`, and removes the file; it touches no other process, a reused pid among them |
| `make orchestrator-serve` | The runner, `core/.venv`'s `fylgja-orchestrator serve`, in the foreground until Ctrl-C, serving `stage-plan/main` and `twin-rehearse/main` to the edge's Prefect at `http://<the bind>:4200/api` (`scripts/edge_dev.py serve`). Its environment is its own and no other: Prefect's address, basic auth, home and analytics off; the runner's own tokens as the names the edge reads, `FYLGJA_API_TOKEN` from `FYLGJA_ORCHESTRATOR_API_TOKEN` and `FYLGJA_INFRAHUB_TOKEN` from `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`; the other `FYLGJA_API_*`, `FYLGJA_INFRAHUB_*` and `FYLGJA_ORCHESTRATOR_*` names as loaded, never `FYLGJA_INFRAHUB_WRITE_TOKEN`, the three it took its own from, an `INFRAHUB_*` name of Compose's or a node's login; and `PATH` and `HOME`. A name it needs not set is one line naming it, exit 2. Load `local/.env` first |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures, and the store, the object store over a fake S3 endpoint, the reconcile loop, API 1 and the CLI over fakes of the runtime; and, under `infrahub/tests/`, what `infrahub/` gives Infrahub, read as files (the schema library at its commit, the registration with its query and its template, the Compose override, the seed's object files, `main`'s and the seeded branch's two stages, against the fixture, and the reader document), the names and addresses of the tracked tree, the development Infrahub's script over fakes of Compose, the fetch and the clock, and `infrahub/seed/`'s transport, registration and seed over fakes of Infrahub, `infrahubctl`, the reader's `head` and the clock, and the example's account and its token's line over a fake of Infrahub; under `readers/infrahub/tests/`, what the reader's modules import, its rows with the rule that every list is whole, over rows built in the tests, its reader document, loaded from files and refused by its rules, its times, its GraphQL documents, its transport over a fake of Infrahub's HTTP (the version, the branch's path and `at`, the pager, the event log's pager down to its floor, an artifact's content by its storage id alone, the refusals with their statuses, a stamp that is no time, and the token kept out of every error), its schema check, each difference from its table its rule, over the table's own kinds as rows, and its mapping, each device's configuration from its artifact and the read with its source envelope, over rows built in the tests (the fixture's network and id, one document whatever order the rows come in, the forms judged before anything is sent, and each omission, refusal and fault of an artifact its rule, every device at fault in one pass), and its stale rule and `head`, over rows built in the tests (each node a configuration renders from moving its devices alone, the task workers' restamp discounted and `__system__` never, the events that show what no stamp does, `generated_since`, and the first instant after the latest write, every stamp and event counted, a probe's among them where the branch has the kind); and its probes, the kind's file against blueprint 1's patterns and its probes over rows built in the tests (the probed fixture's id, read only where the document asks, the kind absent, a probe of another scope omitted, a renamed device, each fault of the declaration its rule, a null attribute among them, and a list not whole); and its command over a fake of `connect` and the environment (each exit, what each stream holds, the token in neither), and its README's versions and `mapping.md`'s members held to the code; and the example's rehearsal library over a fake change source and the core's server on its fake runtime, and its Infrahub change source over rows built in the tests and a fake of Infrahub's HTTP (the open proposed change of a branch, the stages' order and pins, the wait for the artifact validation, each stage's time and `generated_since`, `main` moved, and the report's thread, measured first, with the token in no error) |
| **Live** | Booted images on the local containerlab driver, and Versity S3 Gateway under Docker | On demand: `make live`, with `local/.env` loaded: the driver's own modules under `core/tests/live/` (the driver, `changes` against containerlab's dry run, readiness and the push, verify over gNMI, the trigger and the restore through Docker's restart paths, and the object store against the gateway), then the conformance suite on the local harness. 165 tests by collection; about 59 minutes, derived from the 54 minutes last read with the cluster quiet and the suite's growth from about 31 minutes to 36, not re-measured. Never while the cluster runs the suite or the cluster tier: here the two share a hypervisor, and SR Linux segfaults under the contention. `make test` deselects it (the `live` marker) |
| **Cluster** | The k3s cluster, reached from the development host | On demand: `make cluster`, with `local/.env` loaded and `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE` and `FYLGJA_POD_CIDR` set: the clabernetes driver's calls on the cluster, its reach into Kubernetes first (`core/tests/cluster/test_kube_cluster.py`), then the driver's calls and `changes` held to the pods' uids (`core/tests/cluster/test_clabernetes_driver_cluster.py`, `core/tests/cluster/test_clabernetes_changes_cluster.py`), the trigger and the restore through the loop (`core/tests/cluster/test_restore_cluster.py`), and the Lease (`core/tests/cluster/test_lease_cluster.py`). Each test twin has its own namespace, deleted at its module's end; never while `make live` runs. `make test` deselects it (the `cluster` marker) |
| **Driver conformance** | Each driver's own runtime: for the local driver, containerlab and Docker on the development host; for clabernetes, the core deployed on the cluster with `FYLGJA_RESYNC_S` of 3600 or more, a token of the suite's own principal, both node logins and the cEOS pull credential, reached from the development host ([Running the core on a cluster](#running-the-core-on-a-cluster)) | On demand, per driver: `make conformance DRIVER=containerlab`, 54 tests in about 36 minutes, which `make live` runs too; and `make conformance DRIVER=clabernetes`, 54 tests in about 71 minutes. Each was measured with the other runtime quiet, and the two are never run together here: they share a hypervisor. Each runtime needs the many-twins scenario's band of room: about 4.5 CPU and 17 GiB free locally and 7.5 CPU and 28 GiB on the cluster, and under about 80 GiB free on either with its twins up, so that its forty-node twin is refused. `make test` deselects the suite (its harness's marker, `live` or `cluster`) |
| **Contract** | The development Infrahub, up and registered (`make infrahub-up`, `make infrahub-register`), reached at `FYLGJA_INFRAHUB_ADDRESS` with the writer's token, `FYLGJA_INFRAHUB_WRITE_TOKEN`, and the reader's, `FYLGJA_INFRAHUB_TOKEN`, which the seed's `head` reads with; for the reader's, seeded too (`make infrahub-seed`, which `infrahub/tests/contract/` runs again); for the example orchestrator's, its account's token too, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN` (`make orchestrator-env`), and a Prefect server on loopback, which its tests start, with the development Prefect and runner down (`make prefect-down`) | On demand: `make contract`, with `local/.env` loaded; it sets `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` on its own command lines. `infrahub/tests/contract/`: the library, the group and the registration as `main` holds them, and a second registration that changes nothing; then the seed run whole, as `make infrahub-seed` runs it, the reader's kind and the stage kind passed and each stage timed by the reader's `head`, writing `seed.json` where `FYLGJA_INFRAHUB_SEED` names it: `main` left the fixture less one link, `seed.json`'s branch, scope and two stages in order, with their marks and no proposed change, each stage marked on `main` at its time and the branch with no open proposed change, the branch read at each stage's time with its cables, its addresses and its configurations, each `Ready` with its bytes the fixture's, then the fixture's with `n1`'s address, and a second seed that gives the same network at later times, its own marks in place of the first's, and leaves `main` as it was. Then the reader's, `readers/infrahub/tests/contract/`, with the reader's token, and a writer of its own with the admin's, which the reader is never given, writing only on a branch `fylgja-contract-<8 hex>` it makes from `main` and deletes after, the session's start deleting any that a stopped run left: Infrahub's version read; a branch Infrahub lacks refused with 404, its error naming the branch, and an `at` before the branch with 422 and a malformed one with 400, each naming the branch and the time; a wrong token refused with 401 at the connect, naming `FYLGJA_INFRAHUB_TOKEN`; none of them holding the token; the seeded `main`'s devices and ports read as rows at the first stage's time, every list whole; 120 ports of one device read in two pages; the seeded `main`'s schema held to the schema check's table, nothing differing; and the fixture read into blueprints, `main` and the seeded branch at the first stage's time, the branch's blueprint id the probed fixture's (`three-node-probed.json`), the seed's probe among it, each stage's configurations their artifacts' bytes, a past time read as it stood after a later one, and a scope no device carries empty; and the stale rule and `head`: each stage of the seeded branch read with no stale configuration, and read twice to one id; an address of `n1`'s edited on a branch of the writer's, refusing `n1` alone as stale at `head` until a regeneration the writer asks, and then a port of `n1`'s renamed, refusing `n1` and `n2`, at the cable's far end, and not `n3`; and the seeded branch read at `head` giving its last stage's blueprint id; and the probes: the seed's `n1-loop` alone in each stage's blueprint, and a probe of the tier's own, made through its branch and its gateway changed, read through that branch a microsecond after each write as it stood then, under one id, counted by `head`, and omitted from the read, its devices in no scope. The kind being branch-agnostic, that probe is on every branch while the test runs, and deleted at its end; the session's start deletes any `fc-*` probe a stopped run left. Then each refusal. Provoked by the writer on a branch of its own and read at its `head`: a device made in the scope with no artifact, `artifact.missing` for it alone; an artifact's status written `Pending`, `artifact.unready`, and its checksum written as zeros, `artifact.checksum.mismatch`; a device's serial number, which the template does not render, written, `artifact.stale`, and the same read with a `generated_since` of that `head` giving the configuration as it was; and a cable added and regenerated, then its ends taken off it, `artifact.stale` for its two devices by the cable's event alone. Made in flight, by a transport of the test's own that alters a real answer, where the writer may not write it or Infrahub never answers it: a branch of the writer's whose schema is answered without `DcimCable.label`, which a load may not remove, `schema.field.missing` from `check_schema` and `read`, `main` conforming; and `main` read at its `head` with each answer of the ports cut by an edge, `read.incomplete`. And `main` read at its `head` with a reader document naming no device's platform, `platform.unmatched` for each. Then the command, `fylgja-infrahub`, run as a process of its own with the reader's variables alone: `read` of the first stage writing the library's blueprint, `schema-check` of `main`, `head`, and a scope no device carries exiting 1. Last, every request the reader's connections sent held to reads: a `GET`, or a `POST` to `/graphql/` of a `query`. The reader's: 30 tests, in 757 s run alone, measured once since a branch's events take in `main`'s up to its branch point; 396 s and 402 s in two runs before; 895 s within the whole tier, measured once, on 2026-11-11, and 1782.90 s on 2026-11-12. Then the example orchestrator's, `orchestrator/tests/contract/`, with the example's account's token, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, for the change source and the runner, and the admin's for its own writes. Each module makes a proposed change of the seed's branch, finding none open at its start and leaving none at its end, and stops where anything listens on port 4200. The change source's: the head read at the proposed change's creation, waiting for its artifact validation and giving the reader its completion as `generated_since`; the change found by its branch with its draft flag, and `NoChange` for a name that is no branch; the stages the branch point at the cut, the seed's marks at their `as_of` and the head, and a mark written with no `as_of` last before the head at the time Infrahub gave its writing; a report posted as one thread of two comments by the account, a part of 4,092 bytes taken and one of 4,093 sending nothing; the account refused a tag; and every stage read to a blueprint, with no `stage.main.moved` after the module's writes, and the head twice to one id. The edge's: the core served on plan 4's fake runtime in the test's process, a Prefect server on a free loopback port and `fylgja-orchestrator serve`, each ended by its pid, and the checks' glue run in the test's process as a check runs it, never on a task worker: `fylgja-step` passing, its document a plan 1; `fylgja-twin` passing, its document a rehearsal 1 `passed`, and one more thread of two comments; a rehearsal held at its apply and cancelled at the check's own deadline (`timeout` 660, the deadline 420 s after the check begins), read `CANCELLED` within 45 s and its twin gone or its deletion asked within 30 s more; a draft starting no run; and no secret in any message or in the server's and the runner's output. The orchestrator's: 11 tests, in 722 s within the whole tier on 2026-11-11 and 1469.00 s on 2026-11-12, each measured once. Without its variables a test is skipped, and fails when `CI` is set. `make test` deselects it (the `contract` marker) |

Development and the live tier never need Kubernetes (Constitution XIII).

## Test data

| Path | Holds |
|---|---|
| `testdata/blueprint/` | Five blueprints: `three-node`, `mixed`, `lossy`, `three-node-probed`, `three-node-unmanaged` (it has no Go facts) |
| `testdata/compiler/` | The facts the frozen Go compiler produced for each, which the new compiler is held to; and under `rejected/`, valid blueprints the compiler must refuse, one fault each |
| `testdata/packages/` | `chassisos`, a synthetic lossy platform; the interface mapping rows each package must produce; and under `invalid/`, the rejection fixtures for the platform and probe package loaders |
| `testdata/probes/` | Probe declaration files, valid and, under `invalid/`, the rejection fixtures for the declaration loader |
| `testdata/deployment/` | The golden deployments: for each driver (`containerlab/`, `clabernetes/`) and fixture, the rendered runtime files and the deployment document the plan must reproduce, which change in a commit of their own; and under `rejected/`, valid blueprints a driver's plan must refuse, one fault each |
| `testdata/s3/` | The SigV4 signer's known answers, written once by `generate.py` from botocore's signer in a venv outside the tree; botocore is never a dependency (D-061) |
| `infrahub/seed/` | The fixture network as object files `infrahubctl` loads into the development Infrahub: under `main/`, `testdata/blueprint/three-node.json`'s devices, ports, addresses and cables less the link between `n1` and `n3`, and `three-node-probed.json`'s probe `n1-loop` as a `FylgjaProbe`; under `stages/`, the seeded branch's two edits in order, that link and then the address `192.0.2.1/24` on its `n1` end; and `reader.yaml`, the reader document that maps the fixture's manufacturer and platform to the package `nokia_srlinux` and reads probes |

## Local environment

**Credentials** live in `local/.env` alone (git-ignored, mode `0600`), with the names in
[`.env.example`](.env.example).
- Load it with `set -a; . local/.env; set +a`. Fylgja reads the process environment, never a
  file.
- Never print, log or persist a token or a password.

**The contract tier** reads the reader's `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_TOKEN` and,
where it is set, `FYLGJA_INFRAHUB_CA`; and `FYLGJA_INFRAHUB_WRITE_TOKEN`, the admin's, for its
tests' own writer. `make contract` sets the other two on its command lines, since a worktree has
no `local/`: `FYLGJA_INFRAHUB_SEED`, the main checkout's `local/infrahub/seed.json`, and
`FYLGJA_INFRAHUB_CTL`, the `infrahubctl` of `local/infrahub/.venv/`.

**The reader's command**, `fylgja-infrahub`, which `make venv` installs as
`core/.venv/bin/fylgja-infrahub`, reads the same `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_TOKEN`
and, where it is set, `FYLGJA_INFRAHUB_CA`, never a flag, and prints no token
([readers/infrahub/README.md](readers/infrahub/README.md#the-command)). Against the development
Infrahub, seeded, a blueprint is read into a file under `local/`, at `head`'s answer where no
`--at` is given:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-infrahub schema-check --branch main
core/.venv/bin/fylgja-infrahub head --branch third-link --scope tag:fylgja
core/.venv/bin/fylgja-infrahub read --branch third-link --scope tag:fylgja \
  --reader infrahub/seed/reader.yaml --out local/third-link.json
```

**The live tier** needs:
- Docker and containerlab, with the user in the `docker` and `clab_admins` groups;
- the SR Linux image (`ghcr.io/nokia/srlinux:24.7.1`, public);
- the cEOS image (`ceos:4.32.0.2F`), imported from Arista's account-gated download and never
  pulled;
- the Versity S3 Gateway image (`ghcr.io/versity/versitygw:v1.10.0`, public), pulled on first
  use.

On Ubuntu, SR Linux's `rsyslogd` needs an AppArmor widening ([verified-facts.md](design/verified-facts.md)).

## Running the core

`fylgja-core-server` is one process: API 1 on uvicorn and the reconcile loop, over one store
held for one core, a directory by its lock and an object store by a Lease
([D-023](design/decisions.md#d-023), [D-039](design/decisions.md#d-039), [D-062](design/decisions.md#d-062)).
Everything it runs with is a `FYLGJA_*` variable ([D-042](design/decisions.md#d-042)), listed
in [`.env.example`](.env.example):

| Variable | Default | Holds |
|---|---|---|
| `FYLGJA_STORE` | required | The store's directory, created on first start (the driver's working files live under it), or `s3://<bucket>[/<prefix>]`, an object store ([D-061](design/decisions.md#d-061)), which needs `FYLGJA_LEASE` and a driver that keeps no files in the store's directory (`clabernetes`) |
| `FYLGJA_S3_ENDPOINT` | required for `s3://` | The object store's endpoint, an `http://` or `https://` URL of a host and an optional port |
| `FYLGJA_S3_ACCESS_KEY` | required for `s3://` | The endpoint's access key |
| `FYLGJA_S3_SECRET_KEY` | required for `s3://` | The endpoint's secret key |
| `FYLGJA_S3_REGION` | `us-east-1` | The region its requests are signed for |
| `FYLGJA_S3_CA` | the system's | A CA bundle for an `https://` endpoint a private CA signed |
| `FYLGJA_LEASE` | none; required by `s3://` | The Lease that holds the store for one core ([D-062](design/decisions.md#d-062)), in the core's namespace (the service account's in a pod, the kubeconfig context's off the cluster), taken before the store is opened: a core that finds it held waits, saying once whom for, and one that loses it stops at once (`lease.lost`): its loop's stop begun, given 2 s, every connection dropped, one still in its TLS handshake among them, and each request in flight cancelled, none answered and none given grace, nothing released, exit status 1 |
| `FYLGJA_PACKAGES` | required | Colon-separated directories of platform and probe packages, loaded once at start: `psp:probes` |
| `FYLGJA_TOKENS` | required | The token file (below) |
| `FYLGJA_LISTEN` | `127.0.0.1:7650` | The address it serves on, `host:port` |
| `FYLGJA_TLS_CERT` | none | The certificate the server ends TLS with, set with `FYLGJA_TLS_KEY` ([D-063](design/decisions.md#d-063)); without the two it serves HTTP, which is for loopback, and a listen address off loopback is one warning at start |
| `FYLGJA_TLS_KEY` | none | The certificate's key, unencrypted, set with `FYLGJA_TLS_CERT`: an encrypted key is refused at start, never prompted for |
| `FYLGJA_DRIVER` | `containerlab` | The driver twins run on: `containerlab`, the local driver, or `clabernetes`, which reaches the cluster from its service account in a pod and from the kubeconfig `KUBECONFIG` names off the cluster |
| `FYLGJA_CLABERNETES_NAMESPACE` | none; required by `clabernetes` | clabernetes' namespace, a DNS-1123 label (`c9s`), which each twin's policy admits |
| `FYLGJA_POD_CIDR` | none; required by `clabernetes` | The cluster's pod network, an IPv4 network in CIDR form (`10.244.0.0/16`); each twin's policy admits any source outside it |
| `FYLGJA_WORKERS` | `8` | How many twins the loop works on at once: five twins created together each hold a worker through an apply, with room beside ([D-075](design/decisions.md#d-075)) |
| `FYLGJA_STEP_WAIT_S` | `180` | Seconds a step waits for verify to hold before it ends anyway (an integer of 1 or more) |
| `FYLGJA_RESYNC_S` | `300` | Seconds between the loop's resyncs, each of which queues every twin again, so a runtime event missed is only late (an integer of 1 or more) |
| `FYLGJA_CREDENTIAL_<NAME>_USERNAME`, `_PASSWORD` | none | Each package's node login, `<NAME>` its `credentials` value upper-cased; a run needing one not set fails with `credential.missing` |
| `FYLGJA_CREDENTIAL_<NAME>_REGISTRY`, `_USERNAME`, `_PASSWORD` | none | A package's pull secret on the clabernetes driver: the image prefix a gated image is pulled under, and the registry's login; a twin's allocation holds the prefixes set when it was admitted |

**The token file** holds one `<sha256 hex of the token> <principal>` per line, `#` comments
and blank lines skipped. It never holds a token itself, and several tokens may be valid at
once, one per client. Make a client's token and add its line:

```sh
token=$(head -c 24 /dev/urandom | base64)
printf '%s %s\n' "$(printf %s "$token" | sha256sum | cut -d' ' -f1)" alice >> local/tokens
printf 'FYLGJA_API_TOKEN=%s\n' "$token" >> local/.env   # the client's token, never echoed
unset token
```

`printf %s "$FYLGJA_API_TOKEN" | sha256sum` gives the hash of a token already set.

The commands the local driver runs, `containerlab` and `docker`, get `DOCKER_HOST` and `PATH`
from the server's environment and nothing else ([D-065](design/decisions.md#d-065)); a
variable containerlab should see is added to `ALLOWED_ENV` by a change, with its reason.

**Start it** with the environment loaded:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-core-server
```

It logs one JSON object per line on stderr, the principal on every write, never a token or a
password. A start refused is one line naming the variable or the file at fault. SIGTERM or
Ctrl-C ends open watches, stops the loop and then releases the Lease. A second Ctrl-C, landing
before uvicorn has begun the loop's stop, gives the loop 2 s to stop; landing after, it leaves
uvicorn's own stop running, unbounded; either way the Lease is released only once the loop has
stopped. SIGTERM anywhere in the start, while it waits for the Lease or opens the store among
it, ends the start as Ctrl-C does, and while the console script imports the server, before
anything is opened, it exits 143: the server handles SIGTERM itself, since in a container it is
PID 1, which ignores a signal it has no handler for. Three windows are left, each leaving the
Lease to its duration (the server's module docstring): the interpreter's first 0.14-0.16 s in the
image, and two in the start, each read at under a millisecond on the development host, where the
Lease's client had no connection to close; against the API the one that closes it takes longer,
by how much not read. A create cut short resumes at the next start. Waiting for a Lease another
holds is not an exit: one INFO line a holder, and no socket bound. Its exit status:

| Status | Means |
|---|---|
| 0 | stopped cleanly, the Lease released first when one is held |
| 130 | stopped by Ctrl-C (SIGINT), the Lease released first when one is held; or Ctrl-C anywhere in the start, while it waits for the Lease, while the store is opened or before uvicorn runs, what was opened closed again and the Lease released first, but in the two windows in the start above, where the status is the same and the Lease is left to its duration |
| 143 | stopped by SIGTERM, as by Ctrl-C, in a container as PID 1 too: after uvicorn's graceful shutdown, which releases the Lease; or anywhere in the start, as Ctrl-C, what was opened closed again and the Lease released first, the two windows in the start above as for 130; or while `fylgja-core-server` imports the server, nothing yet opened |
| 1 | the store is held by another core, an object store cannot be opened (its endpoint unreachable, or refusing), the Lease is lost (`lease.lost`), or the application failed to start |
| 2 | a misconfiguration: a `FYLGJA_*` variable not set, empty or malformed, or set to what another rules out (an `s3://` store without `FYLGJA_LEASE` or with the `containerlab` driver, one of the TLS pair without the other); a certificate or key that does not load (`FYLGJA_TLS_CERT`); a key that is encrypted (`FYLGJA_TLS_KEY`); `FYLGJA_LEASE` set with no cluster to reach, or a Lease the service account may not read or write; a CA bundle that does not load (`FYLGJA_S3_CA`); an endpoint that fails the store's proof (`FYLGJA_S3_ENDPOINT`, `store.unconditional`); Python run optimised (`-O` or `PYTHONOPTIMIZE`, `server.optimised`); a package refused, a token file it cannot read, a cluster the clabernetes driver cannot reach (`KUBECONFIG` not set, or not a kubeconfig, off the cluster), an address it cannot listen on (`FYLGJA_LISTEN`), or the server's libraries not installed (`server.extra.missing`) |

**The thin CLI** reads `FYLGJA_API_ADDRESS` (the server's `host:port` or URL) and
`FYLGJA_API_TOKEN`, and `FYLGJA_API_CA` where it is set: the CA file an `https://` address is
verified against, the system's trust when it is not ([D-063](design/decisions.md#d-063)). A
certificate not trusted is one line saying so and one naming `FYLGJA_API_CA`, and exits 2. In a
shell of its own, load the environment and point the CLI at the server's listen address:

```sh
set -a; . local/.env; set +a
export FYLGJA_API_ADDRESS=127.0.0.1:7650   # FYLGJA_LISTEN's value
core/.venv/bin/fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
core/.venv/bin/fylgja-core twin show demo
core/.venv/bin/fylgja-core twin destroy demo
```

A command that waits rides through a restart of the server: its watch reconnects for up to about
three minutes, each try given 5 s to connect, saying so once on stderr, and then exits 2. A
`twin create` already waiting rides through; a `run watch` begun while the server is away exits 2
at once, since its version read is made once, before any stream.

## Running the core on a cluster

On a cluster the core is one pod under a Lease, run from an image built in the tree
([D-062](design/decisions.md#d-062)). The image holds no containerlab, so a core in a pod
serves the `clabernetes` driver alone.

**Build** the image with `make imagecheck`, which builds it, runs it and prints its tag last.
The tag is the commit the image was built at, so a run on the cluster says which commit's code
it read. Push from a clean head: a `-dirty` tag is for the development host alone and is never
pushed. CI builds the image and pushes nothing: publishing one is a release's decision.

**Push** it to the cluster's private registry as the gated image is
([D-021](design/decisions.md#d-021)): by `crane`, from a tarball Docker saves. Nothing of the
registry is in the tree: `<registry>` is its host and port, `<path>` the repository's path in
it and `<user>` its login, each the site's. In one shell, with `DOCKER_CONFIG` a directory under
`local/` for `crane`'s login, `SSL_CERT_FILE` the registry's CA, and the password read on
standard input from a file under `local/` of mode `0600`, never put on a command line:

```sh
export DOCKER_CONFIG=$PWD/local/<config directory> SSL_CERT_FILE=$PWD/local/<the registry's CA>
crane auth login <registry> -u <user> --password-stdin < local/<password file>
docker save -o local/fylgja-core-<tag>.tar fylgja-core:<tag>
crane push local/fylgja-core-<tag>.tar <registry>/<path>/fylgja-core:<tag>
```

**Deploy** it from a site's overlay, `local/deploy/kustomization.yaml`, over the base under
[`deploy/`](deploy/README.md), which holds no address and no value. The overlay names the image
just pushed by its registry, path and tag; makes the Secrets the base's pods name from files
under `local/deploy/secret/`, each of mode `0600`, and their ConfigMap from two literals; and
may give the Service its address. [deploy/README.md](deploy/README.md) holds a whole example and
says which Secret each file becomes. With `KUBECONFIG` naming the cluster's kubeconfig:

```sh
kubectl apply -k local/deploy
kubectl -n fylgja rollout status statefulset/versity
kubectl -n fylgja rollout status deployment/fylgja-core
```

The core's pod turns Ready when it listens, which it does only after it holds the Lease and has
opened its store; one that waits for the Lease is never Ready, and is not restarted for waiting.
At the first apply it may start before its store: it exits 1 at the store's proof, and the
kubelet starts it again after its backoff (10 s, then doubling).

**Reach** it from a workstation over TLS, at the Service's address, with a token whose hash the
overlay's `secret/tokens` holds, trusting the CA that signed the server's certificate.
`local/.env`'s `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` are the development host's core's, so
the three are set in the shell's own environment, the token read from its file under `local/`
(mode `0600`), never echoed. The token's line needs bash: under dash, Ubuntu's `sh`, `$(< file)`
is empty.

```bash
export FYLGJA_API_ADDRESS=https://<the Service's address> FYLGJA_API_CA=$PWD/local/<the site's CA>
export FYLGJA_API_TOKEN="$(< local/<the token's file>)"
core/.venv/bin/fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
```

The client verifies strictly: Python's `ssl.create_default_context()` sets `VERIFY_X509_STRICT`.
The server's certificate names the address as an IP SAN, and the CA's certificate must carry a
key usage that allows signing certificates. One made by `openssl req -x509` with OpenSSL's
default configuration carries none and is refused (`CA cert does not include key usage
extension`); issued again over the same key and subject with `-addext
keyUsage=critical,keyCertSign,cRLSign`, it is accepted, and every certificate it signed verifies
against it ([verified-facts.md](design/verified-facts.md)).

**Never two cores on the cluster at once.** Once the core is deployed, `make cluster`, a driver
run in process on the development host under the same owner label, runs only with the core's
Deployment scaled to no replica (`kubectl scale deployment fylgja-core --replicas=0 -n fylgja`),
and it is scaled back to one after (`--replicas=1`). The labels name no core, the driver's watch
is cluster-wide, and since [D-070](design/decisions.md#d-070) a core deletes a pod of any twin's
whose container ended or restarted in it, so two would each act on the other's twins.

**The conformance suite on the cluster**, `make conformance DRIVER=clabernetes`, drives the
deployed core from the development host, as the CLI does from a workstation. It reads, beside the
node logins of `local/.env` and the `FYLGJA_CONFORMANCE_DRIVER` that `make` sets:

| Variable | Holds |
|---|---|
| `KUBECONFIG` | The cluster's kubeconfig: the harness reads the core's pod, its Lease and the twins' namespaces |
| `FYLGJA_API_ADDRESS`, `FYLGJA_API_TOKEN`, `FYLGJA_API_CA` | The core's `https://` address, a token and the CA, set as "Reach" says; the token is the suite's own principal's, its hash in the overlay's `secret/tokens` |
| `FYLGJA_CONFORMANCE_SELECTOR` | The label selector of the core's pod, `app.kubernetes.io/name=fylgja-core` in the base |
| `FYLGJA_CONFORMANCE_NAMESPACE` | The core's namespace, `fylgja` where it is unset |

A variable missing ends the session in one line naming it, and a value is never printed. The
deployed core runs with `FYLGJA_RESYNC_S` of 3600 or more as a literal of its pod, the overlay's
optional patch ([deploy/README.md](deploy/README.md)), so a restore the suite reads was started by
the driver's events and not by the resync; the suite refuses to start otherwise. It prints the tag
of the image the core runs, the only record of the commit a run read. To kill the core it labels
the pod that holds the Lease, cuts its egress by a NetworkPolicy of its own, writes an annotation on
the Lease between two renewals, or once one is 6 s overdue, so the release the dying pod sends is
refused, and deletes the pod with no grace; the next pod takes the Lease 15 s after
([D-072](design/decisions.md#d-072)). It undoes the policy, the label and the annotation after
each kill, and deletes the namespace `fylgja-conformance-probe` it makes for its isolation
scenario at its end. A run stopped hard leaves its twins in the store; the next run removes them
first, and says so.

**The maintainer's walk**, the phase's own gate ([Sequence](design/core.md#sequence), item 6): a
twin created over TLS by the CLI from `three-node`, stepped through each step fixture with `twin
verify` after each, and destroyed; and a twin from `mixed` given its cEOS port. In a shell with the
three variables set as "Reach" says; the cEOS steps need the EOS login among the overlay's
credentials:

```bash
(
  set -e
  f=core/.venv/bin/fylgja-core b=testdata/blueprint s=testdata/blueprint/steps
  $f twin create walk --blueprint $b/three-node.json; $f twin verify walk
  for to in $s/three-node-unlinked $b/three-node $s/two-node $b/three-node \
            $s/three-node-n1-disabled $b/three-node $b/three-node-unmanaged $b/three-node \
            $b/three-node-probed; do
    $f twin step walk --blueprint $to.json
    $f twin verify walk || { rc=$?; [ $rc -eq 1 ] || exit $rc; sleep 5; $f twin verify walk; }
  done
  $f twin step walk --blueprint $s/three-node-probed-moved.json --allow-restart; $f twin verify walk
  $f twin step walk --blueprint $b/three-node.json; $f twin verify walk
  $f twin step walk --blueprint $s/three-node-n3-eos.json --allow-restart; $f twin verify walk
  $f twin destroy walk
  $f twin create walk-eos --blueprint $b/mixed.json; $f twin verify walk-eos
  $f twin step walk-eos --blueprint $s/mixed-e2-port.json --allow-restart; $f twin verify walk-eos
  $f twin destroy walk-eos
)
```

Each command exits by its verdict: 0 for `ok`, 1 for `rejected`, `failed` or `nonconforming`, 3
for `unclean` or `diverged`, and 2 for a fault of the CLI's own. The walk runs in a subshell under
`set -e`, so the first command that does not exit 0 ends it and nothing after it runs; the shell
stays open, with the twin left as that command found it, to read with `twin show` and `run get`
and then destroy. A `twin verify` that exits 1 within seconds of a step, with `verify.node.unread`
as its only error, is no finding but the blink [verified-facts.md](design/verified-facts.md)
records, a node's Service the step kept without its endpoint for a second or two, so the loop asks
a verify that exits 1 once more, 5 s on, before the walk stops.

## The development Infrahub

One Infrahub at a stated version runs on the development host as the Compose project
`fylgja-core-infrahub` ([D-083](design/decisions.md#d-083)), behind the make targets above. It
is brought up, given this repository and seeded in this order. `make infrahub-up` needs none of
`local/.env`'s names in the shell, and writes the names the others read into it, so the file is
loaded after it: before its first run the file lacks them, or does not exist.

```sh
make infrahub-up          # the project started, its secrets added to local/.env
set -a; . local/.env; set +a
make infrahub-register    # the schema library, the group, and this repository at REF
make infrahub-seed        # the fixture network on main, and the branch third-link with its two stages
make contract             # the contract tier against it
```

- `make infrahub-down` stops it, keeping its containers, network and volumes and everything under
  `local/infrahub/`, so that `make infrahub-up` starts it again holding what it held.
  `make infrahub-down PURGE=1` removes the containers, the network, the volumes and
  `local/infrahub/seed.json`; `local/.env`, the fetched Compose file and `infrahubctl`'s venv
  stay, and the next start is an empty Infrahub, to register and seed again.
- Infrahub imports a later commit of this repository only when asked: `make infrahub-register`
  imports `REF`'s last commit where the registration reads another. A branch runs what was
  imported before it was made
  ([D-088](design/decisions.md#d-088)), so `make infrahub-seed`, which makes its branch anew,
  follows every `make infrahub-register`.
- It is stopped (`make infrahub-down`) for every live, cluster or conformance run: it holds about
  4.5 GiB of the host's memory.

## Running the example orchestrator

The example orchestrator's edge ([D-085](design/decisions.md#d-085)) runs on the development host beside the
development Infrahub: a Prefect server, the runner that serves it the two flows `stage-plan` and `twin-rehearse`, and
Infrahub's task workers, where the example's checks start them. It is set up in this order, the core running at
`FYLGJA_API_ADDRESS` with the token file `FYLGJA_TOKENS` names:

```sh
make infrahub-up            # the development Infrahub
set -a; . local/.env; set +a
make orchestrator-env       # the example's lines in local/.env, and its Infrahub account and token
# restart the core, so that it reads the runner's line in its token file
set -a; . local/.env; set +a
make infrahub-up            # the task workers recreated, given the basic auth local/.env now holds
make infrahub-register      # this repository at REF, cloned on each new task worker
make infrahub-seed          # the branch made after the registration, so it runs this commit's checks
make prefect-up             # the edge's Prefect on port 4200 of the Docker bridge's gateway
make orchestrator-serve     # the runner, in a shell of its own with local/.env loaded, until Ctrl-C
```

Who holds which token:

- **The runner** holds a token of the core's under the principal `orchestrator`
  (`FYLGJA_ORCHESTRATOR_API_TOKEN`) and the Infrahub account `fylgja-orchestrator`'s
  (`FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`), given to it as `FYLGJA_API_TOKEN` and
  `FYLGJA_INFRAHUB_TOKEN`, the names the edge reads, and the basic auth as Prefect's
  `PREFECT_API_AUTH_STRING`. It is never given the admin's token.
- **The Prefect server** holds the basic auth alone, as `PREFECT_SERVER_API_AUTH_STRING`.
- **The task workers**, and so the checks, hold `FYLGJA_ORCHESTRATOR_ADDRESS`,
  `host.docker.internal:4200`, the host's name `extra_hosts` points at the bridge's gateway, and
  `FYLGJA_ORCHESTRATOR_AUTH`; no token of the core's or of Infrahub's
  (`infrahub/dev/compose.override.yml`).
- **The seed and the tests' set-up** write as the admin, `FYLGJA_INFRAHUB_WRITE_TOKEN`.

Two more things hold:

- Port 4200 is the edge's alone: `make prefect-up` refuses where anything else listens on it, and
  stops nothing. `make prefect-down` ends the server it started and no other process. The
  runner is stopped with Ctrl-C.
- A recreated task worker holds no clone of the registration, and a check run on it fails, so
  `make infrahub-register` follows every `make infrahub-up` that recreates them: it imports until
  each holds the tree of the registered commit.

## The acceptance run

Phase 8 is done when the maintainer creates a proposed change of the seeded branch in the
development Infrahub and reads, in its thread, the report of the rehearsal that Infrahub's own
check `fylgja-twin` started: once with the core on the local driver, and once with the core
deployed on the cluster
([core.md](design/core.md#phase-8-the-infrahub-reader-and-the-example-orchestrator-settled-2026-11-09)).
This is that run: every command in order, how each one's end is read, and the block that says the
maintainer can act. It follows [The development Infrahub](#the-development-infrahub) and
[Running the example orchestrator](#running-the-example-orchestrator), which say what each
target does.

- **Where.** Every command here runs with the main checkout as its working directory, at
  `main`'s head with `make venv` run there: `local/` is there alone, and the task
  workers mount that checkout's `.git` alone. The registration reads a branch of that `.git` by
  its name: `make infrahub-register` takes it as `REF`, by default the branch checked out, and
  the block below holds the registration to the commit `git rev-parse main` answers. The runs
  of 2026-11-12 were made at `phase-8-integration`, the branch phase 8 was built on, before it
  landed on `main`, and the block has not been run since with `main` in that name's place. For
  another branch, give `REF=<branch>` and name it in the block's `git rev-parse` line too. The
  make targets resolve `local/` to the main
  checkout from a worktree too (the `Makefile`'s `MAIN` and `LOCAL`), but the core, the CLI, the
  reader and the block below name `local/` from the working directory.
- **Alone.** While it runs nothing else live runs on the host or the cluster: no `make live`,
  `make cluster` or conformance run, and no other twin. The stopped Compose project
  `fylgja-infrahub` and its volumes are never started, removed or altered.
- **By pid.** A process is stopped by its pid, never by its name: another core may run on the
  host, on the default port among them, and a pattern of `pkill -f` ends the shell that sends it.
- **Credentials.** `set -a; . local/.env; set +a` in the same command as what needs it. No token
  or password is put on a command line, printed or written.
- **Output.** Each run's output, the block's among it, goes under the main checkout's
  `local/phase-8/acceptance/<run>/`.

**Bring it up**, in this order, `local/.env` loaded for each step but the first:

1. `make infrahub-up`. Its end: exit 0, once `GET /api/info` answers `1.11.11`, said as
   `infrahub_dev: Infrahub 1.11.11 answered at …`. It reads Compose's `INFRAHUB_*` from
   `local/.env`, writing those it lacks, and `FYLGJA_ORCHESTRATOR_AUTH`, which Compose gives the
   task workers.
2. Once on a host, after the first `make infrahub-up` and before the registration: `make
   orchestrator-env`, which prints names alone; then the core, where it runs already, stopped by
   its pid and started again (step 6), so that it reads the runner's line in its token file; then
   `make infrahub-up` again, so that the task workers are recreated with the basic auth, as
   [Running the example orchestrator](#running-the-example-orchestrator) orders them. On the host
   of the dry run of 2026-11-12, where it had run before, `make orchestrator-env` said `local/.env`
   held every name already and the example's token was accepted, writing nothing; neither
   `make infrahub-up` recreated a worker; and the registration then read the tree on both
   ([verified-facts.md](design/verified-facts.md), "Infrahub 1.11.11"). After any
   `make infrahub-down PURGE=1`, once `make infrahub-up` answers: `make orchestrator-env` again,
   since the example's Infrahub token died with the purged instance and the target replaces its
   line; Compose's own `INFRAHUB_INITIAL_*` values are applied again by the fresh instance.
3. `make infrahub-register REF=main`, after every `make infrahub-up` that recreates
   a task worker. Its end: exit 0, with `register: fylgja reads main at <commit>,
   in-sync and online, …` and then `register: each of the 2 task workers holds the tree of fylgja
   at <commit>, …`. At 300 s it refuses, naming a worker that lacks the tree and ending `run make
   infrahub-register again`, and it is run again. It reads `FYLGJA_INFRAHUB_ADDRESS` and the
   writer's token, `FYLGJA_INFRAHUB_WRITE_TOKEN`.
4. `make infrahub-seed`, with no flag, always after the registration, since a branch runs the
   checks imported before it was made ([D-088](design/decisions.md#d-088)). Its end: exit 0, with
   `seed: wrote …/local/infrahub/seed.json`, which names the branch `third-link`, its marks
   `third-link` and `n1-address`, and a `proposed_change` of null. It reads
   `FYLGJA_INFRAHUB_ADDRESS`, the writer's `FYLGJA_INFRAHUB_WRITE_TOKEN`, and the reader's
   `FYLGJA_INFRAHUB_TOKEN`, which its `head` is read with.
5. `make prefect-up`. Its end: exit 0, with `edge_dev: the development Prefect answers at <the
   bridge's gateway>:4200, pid <pid>, …`, or `… is up already, pid <pid>`. It reads
   `FYLGJA_ORCHESTRATOR_AUTH`.
6. The core, in a shell of its own, with its driver, its store and its packages on its command
   line and not in `local/.env`; the store, `local/store`, is made at its first start and kept:

   ```sh
   set -a; . local/.env; set +a; FYLGJA_DRIVER=containerlab FYLGJA_STORE=local/store FYLGJA_PACKAGES=psp:probes core/.venv/bin/fylgja-core-server
   ```

   Its end: `FYLGJA_LISTEN`'s address listened on by that process's pid (`ss -Hltnp`), and `GET
   /v1/version` answering there, which takes no token. It reads `FYLGJA_LISTEN`, `FYLGJA_TOKENS`
   and the SR Linux login, `FYLGJA_CREDENTIAL_SRLINUX_USERNAME` and `_PASSWORD`, from
   `local/.env`. `FYLGJA_API_ADDRESS`, where the CLI and the runner reach it, is `local/.env`'s,
   equal to `FYLGJA_LISTEN`, and is never set by hand: the `export` of
   [Running the core](#running-the-core) names the default port, and is not copied here.
7. `make orchestrator-serve`, in a shell of its own. Its end: `fylgja-orchestrator: serving
   stage-plan/main, twin-rehearse/main at http://<the bridge's gateway>:4200/api`, and both
   deployments `READY` some 8 s on, as R5 reads them. It reads the runner's own tokens,
   `FYLGJA_ORCHESTRATOR_API_TOKEN` and `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, which it hands the
   runner as `FYLGJA_API_TOKEN` and `FYLGJA_INFRAHUB_TOKEN`; `FYLGJA_ORCHESTRATOR_AUTH`;
   `FYLGJA_ORCHESTRATOR_SCOPE`, `_READER` and `_ROOT`; and `FYLGJA_API_ADDRESS` and
   `FYLGJA_INFRAHUB_ADDRESS`, as loaded.

**Ready for the maintainer** is one block, run in a subshell under `set -e` as
[the maintainer's walk](#running-the-core-on-a-cluster) is, in the runner's own environment:
locally after `set -a; . local/.env; set +a` in the same command, and on the cluster after the
lines "On the cluster" gives, which set Reach's three once `local/.env` is loaded. Before it, in
that command too, the caller sets `out=local/phase-8/acceptance/<run>`, the run's directory, which
the block makes where it is absent and writes R4's blueprints into; it refuses to start without
it. It prints a line a check and exits non-zero at the first that fails, saying why. It is run as
it stands here, with the main checkout as its working directory, whichever checkout this file was
read from, and reads JSON with the main checkout's `core/.venv/bin/python` alone. Inside it the
runner's own tokens stand in for `local/.env`'s, by assignment: `FYLGJA_INFRAHUB_TOKEN` from
`FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN` and `FYLGJA_API_TOKEN` from `FYLGJA_ORCHESTRATOR_API_TOKEN`,
so that it reads Infrahub and the core as the runner will. Every request reads its token from the
environment inside the process that sends it, and none is printed.

- **R1.** The registration `fylgja` reads `in-sync` and `online` at the commit `git rev-parse
  main` answers, and each running container of the Compose service `task-worker`
  holds that commit's tree, `/opt/infrahub/git/<the registration's id>/commits/<the commit>`, as
  `make infrahub-register` reads it.
- **R2.** `seed.json`'s branch exists, and on `/graphql/<branch>` `CoreCheckDefinition` answers
  `fylgja-step` and `fylgja-twin` and `CoreReadOnlyRepository` the commit of R1: a branch made
  before any import reads neither definition, and one made under an earlier registration reads
  that registration's commit.
- **R3.** `FylgjaStage` by `branch__value` answers the marks `seed.json` lists and no other, and
  no proposed change whose `state` is `open` has the branch as its source, as the seed, the change
  source and the checks' glue read them.
- **R4.** `fylgja-infrahub read` of the branch exits 0 at each `at` of `seed.json`, the last read
  twice giving one id, the blueprints written under `$out`.
- **R5.** One runner of this checkout runs, its command line holding the main checkout's own
  `core/.venv/bin/fylgja-orchestrator` and `serve`, with the main checkout's `local/prefect/` as
  its `PREFECT_HOME`, driving the core the block's `FYLGJA_API_ADDRESS` names,
  and the process `local/prefect/server.pid` names is this project's Prefect server; and
  `stage-plan/main` and `twin-rehearse/main` answer 200 by name, `status` `READY`, from the host
  and from every container of `task-worker` with the worker's own two variables,
  `FYLGJA_ORCHESTRATOR_ADDRESS` and `FYLGJA_ORCHESTRATOR_AUTH`, the status alone printed. The
  runner is read by its process because a stopped runner leaves both deployments answering
  `READY` by name ([verified-facts.md](design/verified-facts.md), "Prefect 3.9.2").
- **R6.** The core. Locally: `FYLGJA_API_ADDRESS` equal to `FYLGJA_LISTEN`, the port's listener the
  pid the main checkout's own `core/.venv/bin/fylgja-core-server` runs as, and the image
  `ghcr.io/nokia/srlinux:24.7.1` on the host, since a rehearsal missing it is not rehearsed. Then
  `fylgja-core capacity show --json` answers the driver, and room for the seeded fixture's three SR
  Linux nodes, 0.5 CPU and 2048 MiB each (`psp/nokia_srlinux.yaml`): over its hosts, free less
  pending of at least 1.5 CPU and 6144 MiB, and a roomiest host, the one with the most memory free,
  free CPU breaking a tie, as the core chooses it, with 0.5 CPU and 2048 MiB
  ([D-073](design/decisions.md#d-073)), with `twins` 0; and `fylgja-core twin list` is empty. On the
  cluster as "On the cluster" says.

```bash
(
  set -e
  refuse() { echo "R$1 refused: $2" >&2; exit 1; }
  [ -f local/.env ] || refuse 0 "run in the main checkout, which holds local/"
  case ${out:-} in
    local/phase-8/acceptance/?*) mkdir -p "$out" || refuse 0 "$out was not made" ;;
    *) refuse 0 "set out=local/phase-8/acceptance/<run> first" ;;
  esac
  for name in FYLGJA_INFRAHUB_ADDRESS FYLGJA_API_ADDRESS FYLGJA_LISTEN FYLGJA_ORCHESTRATOR_AUTH \
              FYLGJA_ORCHESTRATOR_API_TOKEN FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN; do
    [ -n "${!name}" ] || refuse 0 "$name is not set: load local/.env"
  done
  caller=$FYLGJA_API_TOKEN   # the shell's own: Reach's on the cluster
  FYLGJA_API_TOKEN=$FYLGJA_ORCHESTRATOR_API_TOKEN
  FYLGJA_INFRAHUB_TOKEN=$FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN
  py=core/.venv/bin/python f=core/.venv/bin/fylgja-core r=core/.venv/bin/fylgja-infrahub
  seed=local/infrahub/seed.json
  gql() {  # gql <branch> <query> <variables>: the data Infrahub answers, as JSON
    "$py" -I -c '
import json, os, ssl, sys, httpx
token, ca = os.environ["FYLGJA_INFRAHUB_TOKEN"], os.environ.get("FYLGJA_INFRAHUB_CA")
try:
    answer = httpx.post(os.environ["FYLGJA_INFRAHUB_ADDRESS"].rstrip("/") + "/graphql/" + sys.argv[1],
                        json={"query": sys.argv[2], "variables": json.loads(sys.argv[3])},
                        headers={"X-INFRAHUB-KEY": token}, timeout=60,
                        verify=ssl.create_default_context(cafile=ca) if ca else True)
    body = answer.json()
except Exception as error:
    sys.exit("Infrahub was not read: " + type(error).__name__)
if answer.status_code != 200 or not isinstance(body, dict) or body.get("errors") or not body.get("data"):
    said = "Infrahub answered HTTP %d: %s" % (answer.status_code, body)
    sys.exit(said.replace(token, "<token>")[:400])
print(json.dumps(body["data"]))' "$@"
  }
  pyj() {  # pyj <python> [<arg> ...]: the Python run with d, the JSON on stdin, and a, the arguments
    "$py" -I -c '
import json, sys
try:
    d, a = json.load(sys.stdin), sys.argv[2:]
    exec(sys.argv[1])
except Exception as error:
    sys.exit("%s: %s" % (type(error).__name__, error))' "$@"
  }

  commit=$(git rev-parse --verify --quiet 'main^{commit}') \
    || refuse 1 "the main checkout holds no branch main"
  repo=$(gql main '{ CoreReadOnlyRepository(name__value: "fylgja") { edges { node {
    id ref { value } commit { value } sync_status { value } operational_status { value } } } } }' '{}') \
    || refuse 1 "the registration fylgja was not read"
  fields=$(pyj 'n = [e["node"] for e in d["CoreReadOnlyRepository"]["edges"]]
print(*(n and (n[0]["id"], n[0]["ref"]["value"], n[0]["commit"]["value"], n[0]["sync_status"]["value"],
               n[0]["operational_status"]["value"])))' <<< "$repo") \
    || refuse 1 "the registration's answer was not read"
  read -r id ref at sync online <<< "$fields"
  [ "$at" = "$commit" ] && [ "$sync" = in-sync ] && [ "$online" = online ] \
    || refuse 1 "fylgja reads ${ref:-nothing} at ${at:-no commit}, $sync, $online, not $commit in-sync and online"
  workers=$(docker ps --filter label=com.docker.compose.project=fylgja-core-infrahub \
    --filter label=com.docker.compose.service=task-worker --format '{{.Names}}') || refuse 1 "docker ps failed"
  n=0
  for w in $workers; do
    docker exec "$w" test -d "/opt/infrahub/git/$id/commits/$commit" \
      || refuse 1 "$w holds no tree of $commit: run make infrahub-register REF=main again"
    n=$((n + 1))
  done
  [ "$n" -gt 0 ] || refuse 1 "no task worker runs: make infrahub-up"
  echo "R1 ok: fylgja reads $ref at $commit, in-sync and online, and each of the $n task workers holds its tree"

  branch=$(pyj 'print(d["branch"])' < "$seed") || refuse 2 "$seed was not read: make infrahub-seed"
  vars=$(pyj 'print(json.dumps({"b": d["branch"]}))' < "$seed") || refuse 2 "$seed was not read"
  listed=$(gql main 'query ($b: String) { Branch(name: $b) { name } }' "$vars") \
    || refuse 2 "the branches were not read"
  pyj 'sys.exit(len([b for b in d["Branch"] if b["name"] == a[0]]) != 1)' "$branch" <<< "$listed" \
    || refuse 2 "Infrahub holds no branch $branch: make infrahub-seed"
  seen=$(gql "$branch" '{ CoreCheckDefinition { edges { node { name { value } } } }
    CoreReadOnlyRepository(name__value: "fylgja") { edges { node { commit { value } } } } }' '{}') \
    || refuse 2 "$branch was not read"
  said=$(pyj 'names = sorted(e["node"]["name"]["value"] for e in d["CoreCheckDefinition"]["edges"])
held = [e["node"]["commit"]["value"] for e in d["CoreReadOnlyRepository"]["edges"]]
print(", ".join(names) or "no check definition", "at", ", ".join(held) or "no commit")
sys.exit(not ({"fylgja-step", "fylgja-twin"} <= set(names) and held == [a[0]]))' "$commit" <<< "$seen") \
    || refuse 2 "$branch reads ${said:-nothing}: made before the import, make infrahub-seed"
  echo "R2 ok: $branch reads fylgja-step and fylgja-twin, and the registration at $commit"

  held=$(gql main 'query ($b: String!) { FylgjaStage(branch__value: $b) { edges { node { label { value } } } }
    CoreProposedChange(source_branch__value: $b, state__value: "open") { count } }' "$vars") \
    || refuse 3 "the marks and the proposed changes of $branch were not read"
  wanted=$(pyj 'print(" and ".join(d["marks"]))' < "$seed") || refuse 3 "$seed lists no marks"
  marks=$(pyj 'print(json.dumps(d["marks"]))' < "$seed") || refuse 3 "$seed lists no marks"
  marked=$(pyj 'print(" and ".join(e["node"]["label"]["value"] for e in d["FylgjaStage"]["edges"]) or "nothing")' \
    <<< "$held") || refuse 3 "the marks of $branch were not read"
  pyj 'sys.exit(sorted(e["node"]["label"]["value"] for e in d["FylgjaStage"]["edges"])
         != sorted(json.loads(a[0])))' \
    "$marks" <<< "$held" || refuse 3 "$branch is marked $marked, not $wanted alone"
  open=$(pyj 'print(d["CoreProposedChange"]["count"])' <<< "$held") || refuse 3 "the proposed changes were not read"
  [ "$open" = 0 ] || refuse 3 "$open open proposed change(s) of $branch: Clean up removes it"
  echo "R3 ok: $branch is marked $wanted alone, and no proposed change of it is open"

  scope=$(pyj 'print(d["scope"])' < "$seed") || refuse 4 "$seed names no scope"
  ats=$(pyj 'print(*(s["at"] for s in d["stages"]))' < "$seed") || refuse 4 "$seed lists no stages"
  n=0 last=
  for at in $ats; do
    n=$((n + 1)) last=$at
    line=$("$r" read --branch "$branch" --scope "$scope" --reader infrahub/seed/reader.yaml --at "$at" \
      --out "$out/stage-$n.json") || refuse 4 "$branch read at $at exited $?"
  done
  [ "$n" -gt 0 ] || refuse 4 "$seed lists no stage"
  again=$("$r" read --branch "$branch" --scope "$scope" --reader infrahub/seed/reader.yaml --at "$last" \
    --out "$out/again.json") || refuse 4 "$branch read again at $last exited $?"
  [ "${again%% *}" = "${line%% *}" ] || refuse 4 "$branch read twice at $last gave ${line%% *} and ${again%% *}"
  echo "R4 ok: $branch read at each of its $n stages, the last twice to ${line%% *}, into $out"

  found=$("$py" -I -c '
import os, sys
from pathlib import Path
here = Path.cwd()
home, runner = str(here / "local" / "prefect"), str(here / "core" / ".venv" / "bin" / "fylgja-orchestrator")
def read(pid):
    try:
        argv = Path("/proc/%s/cmdline" % pid).read_bytes().decode(errors="replace").split("\0")
        env = Path("/proc/%s/environ" % pid).read_bytes().decode(errors="replace").split("\0")
        cwd = os.readlink("/proc/%s/cwd" % pid)
    except OSError:
        return None
    argv = [part for part in argv if part]
    paths = {os.path.normpath(os.path.join(cwd, part)) for part in argv}
    return argv, paths, dict(entry.partition("=")[::2] for entry in env if "=" in entry)
def stop(said):
    print(said)
    sys.exit(1)
runners = []
for entry in Path("/proc").iterdir():
    process = read(entry.name) if entry.name.isdigit() else None
    if process and runner in process[1] and "serve" in process[0] and process[2].get("PREFECT_HOME") == home:
        runners.append((entry.name, process[2]))
if len(runners) != 1:
    stop("%d runners of this checkout, %s serve, run, not one: make orchestrator-serve" % (len(runners), runner))
pid, env = runners[0]
if env.get("FYLGJA_API_ADDRESS") != os.environ["FYLGJA_API_ADDRESS"]:
    stop("the runner, pid %s, drives a core FYLGJA_API_ADDRESS does not name: stop it, start it again" % pid)
try:
    server = Path(home, "server.pid").read_text().strip()
except OSError:
    stop("local/prefect/server.pid names no development Prefect: make prefect-up")
process = read(server)
if not process or not {"prefect", "server"} <= {Path(part).name for part in process[0]} \
        or process[2].get("PREFECT_HOME") != home:
    stop("pid %s of local/prefect/server.pid is no Prefect server with PREFECT_HOME local/prefect" % server)
print(pid, server, env.get("PREFECT_API_URL", "").removeprefix("http://").removesuffix("/api"))') \
    || refuse 5 "$found"
  read -r runner prefect address <<< "$found"
  probe='
import os, sys, httpx
user, _, password = os.environ["FYLGJA_ORCHESTRATOR_AUTH"].partition(":")
said, ready = [], True
for flow in ("stage-plan", "twin-rehearse"):
    try:
        answer = httpx.get("http://" + os.environ["FYLGJA_ORCHESTRATOR_ADDRESS"] + "/api/deployments/name/" + flow
                           + "/main", auth=(user, password), timeout=10, trust_env=False)
        status = answer.json().get("status") if answer.status_code == 200 else None
        said.append("%s/main %d %s" % (flow, answer.status_code, status))
        ready = ready and answer.status_code == 200 and status == "READY"
    except Exception as error:
        said.append("%s/main not reached, %s" % (flow, type(error).__name__))
        ready = False
print(", ".join(said))
sys.exit(0 if ready else 1)'
  seen=$(FYLGJA_ORCHESTRATOR_ADDRESS=$address "$py" -I -c "$probe") || refuse 5 "from the host: $seen"
  for w in $workers; do
    from=$(docker exec "$w" python3 -c "$probe") || refuse 5 "from $w: $from"
  done
  echo "R5 ok: the runner, pid $runner, and the development Prefect, pid $prefect;" \
    "$seen, from the host and each task worker"

  listen=$(ss -Hltnp "sport = :${FYLGJA_LISTEN##*:}") || refuse 6 "ss did not read the listeners"
  if [ -n "${FYLGJA_API_CA:-}" ]; then
    [[ $FYLGJA_API_ADDRESS == https://* ]] || refuse 6 "FYLGJA_API_CA is set and FYLGJA_API_ADDRESS is not https://"
    [ -z "$listen" ] || refuse 6 "a listener holds FYLGJA_LISTEN's port: stop the local core by its pid"
    deployed=$(kubectl -n fylgja get deployment fylgja-core \
      -o jsonpath='{.spec.replicas} {.spec.template.spec.containers[0].image}') || refuse 6 "no Deployment read"
    read -r replicas image <<< "$deployed"
    [ "$replicas" = 1 ] || refuse 6 "the deployed core runs $replicas replicas, not one"
    room=$(FYLGJA_API_TOKEN=$caller "$f" capacity show --json) || refuse 6 "the deployed core's room was not read"
    twins=$(FYLGJA_API_TOKEN=$caller "$f" twin list --json) || refuse 6 "the deployed core's twins were not read"
    "$f" twin list --json > /dev/null || refuse 6 "the deployed core refused the runner's token"
    driver=clabernetes least=2
    core="the deployed core, fylgja-core:${image##*:}, one replica, taking the runner's token"
  else
    [ "$FYLGJA_API_ADDRESS" = "$FYLGJA_LISTEN" ] || refuse 6 "FYLGJA_API_ADDRESS is not FYLGJA_LISTEN"
    [[ $listen =~ pid=([0-9]+) ]] || refuse 6 "nothing of this user's listens on FYLGJA_LISTEN: start the core"
    pid=${BASH_REMATCH[1]}
    "$py" -I -c '
import os, sys
pid, want = sys.argv[1], os.path.join(os.getcwd(), "core", ".venv", "bin", "fylgja-core-server")
try:
    cwd = os.readlink("/proc/%s/cwd" % pid)
    argv = open("/proc/%s/cmdline" % pid, "rb").read().decode(errors="replace").split("\0")
except OSError:
    sys.exit(1)
sys.exit(not any(os.path.normpath(os.path.join(cwd, part)) == want for part in argv if part))' "$pid" \
      || refuse 6 "pid $pid listens on FYLGJA_LISTEN and is not this checkout's fylgja-core-server"
    docker image inspect ghcr.io/nokia/srlinux:24.7.1 > /dev/null || refuse 6 "no SR Linux 24.7.1 image here"
    room=$("$f" capacity show --json) || refuse 6 "the core's room was not read"
    twins=$("$f" twin list --json) || refuse 6 "the core's twins were not read"
    driver=containerlab least=1 core="the local core, pid $pid"
  fi
  sums=$(pyj 'hosts, pending = d["hosts"], d["pending"]
cpu = sum(h["cpu"]["free"] for h in hosts) - pending["cpu"]
mb = sum(h["memory_mb"]["free"] for h in hosts) - pending["memory_mb"]
roomiest = max(hosts, key=lambda h: (h["memory_mb"]["free"], h["cpu"]["free"]), default=None)
print("driver %s, %d host%s, free less pending %g CPU and %d MiB, twins %d"
      % (d["driver"], len(hosts), "" if len(hosts) == 1 else "s", cpu, mb, d["twins"]))
sys.exit(not (d["driver"] == a[0] and len(hosts) >= int(a[1]) and d["twins"] == 0 and cpu >= 1.5 and mb >= 6144
              and roomiest and roomiest["cpu"]["free"] >= 0.5 and roomiest["memory_mb"]["free"] >= 2048))' \
    "$driver" "$least" <<< "$room") || refuse 6 "$core answers ${sums:-no capacity}, not $driver with the room"
  held=$(pyj 'print(" ".join(t["name"] for t in d))' <<< "$twins") || refuse 6 "$core's twins were not read"
  [ -z "$held" ] || refuse 6 "$core holds the twins $held"
  echo "R6 ok: $core, $sums, and twin list empty"
)
```

**The maintainer's act**, asked a moment after the block exits 0: in Infrahub's UI at `<the
development host>`, port 8000, the maintainer creates a proposed change from the seeded branch
into `main`, not as a draft, and does nothing else: no re-run of a check, no edit, no merge. The
request names the branch, `seed.json`'s `branch`, says how long the dry run took, and says how to
sign in: with their own credential, or as the admin with the password `local/.env`'s
`INFRAHUB_INITIAL_ADMIN_PASSWORD` holds, read from the file by them and never shown. What follows
is unasked: both checks' validators, `Check: fylgja-step` and `Check: fylgja-twin`, within about a
minute (the user check concluded 27 to 55 s after a creation, with a trivial check;
[verified-facts.md](design/verified-facts.md), "Infrahub 1.11.11"); `fylgja-twin` concluding when
the rehearsal ends; and the report as a thread, labelled `Fylgja rehearsal`, of two comments, the
summary and then the detail. A proposed change made as a draft, or anything done to it beyond its
creation, is not the run: the seed is made again, and the maintainer asked again.

**Read the run**, read-only, once `fylgja-twin` has concluded, into
`local/phase-8/acceptance/<run>/`. Infrahub is read with the writer's or the runner's token and
Prefect with `FYLGJA_ORCHESTRATOR_AUTH`, each from the environment inside the process that sends
the request:

- the proposed change's creation time as Infrahub answers it, its edge's `node_metadata {
  created_at }`, never a clock of the reader's;
- by `proposed_change__ids`, the `CoreArtifactValidator` and the two `CoreUserValidator`s, each
  with its `state`, `conclusion`, `started_at` and `completed_at`: from them, when the artifact
  validator appeared after the creation, and whether each check ran for more than 20 s. A run
  with no `fylgja-twin` validator 120 s after the creation is not the run;
- each task worker's log over the run (`docker logs`), for the worker each check ran on, and
  whether a check met a worker lacking the commit's tree (`NodeNotFoundError`);
- the thread: `CoreChangeThread` by `change__ids`, its label, and its `CoreThreadComment`s in the
  order of their edges' `node_metadata { created_at }`, each comment's `text` saved byte for byte
  to a file of its own, with its size;
- the rehearsal document: the deployment's id by `GET /api/deployments/name/twin-rehearse/main`,
  its runs by `POST /api/flow_runs/filter` on that id (`flow_runs.deployment_id`), the one begun
  after the creation with its state and its start and end times, then that run's document by
  `POST /api/artifacts/filter` on the run's id and the type `fylgja-document`, keyed
  `fylgja-twin-rehearse-<run id>`: its `status`, `took_s` and `twin`, each stage's `result`, and
  its findings, `stage.validation.absent` among them;
- `fylgja-core twin list`.

Whether the run is the one the criterion names is read from the document's `status` and its
stages' `result`s, never from the check's colour. What is read holds a site's values: before any
of it is committed, each address and host's name in it is replaced by a placeholder, and the token
check prints 0 for each file to be committed and each of the run's files. On the cluster the
`<(…)` also prints Reach's token, read from its file inside the command:
`printf '%s\n' "$(< local/<the token's file>)"`.

```bash
set -a; . local/.env; set +a
/usr/bin/grep -c -F -f <(printenv FYLGJA_INFRAHUB_TOKEN FYLGJA_INFRAHUB_WRITE_TOKEN FYLGJA_API_TOKEN \
    FYLGJA_ORCHESTRATOR_API_TOKEN FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN FYLGJA_ORCHESTRATOR_AUTH \
    INFRAHUB_INITIAL_ADMIN_PASSWORD INFRAHUB_INITIAL_ADMIN_TOKEN INFRAHUB_INITIAL_AGENT_TOKEN \
    INFRAHUB_SECURITY_SECRET_KEY; printf '%s\n' "${FYLGJA_ORCHESTRATOR_AUTH#*:}") \
  <each file>
```

**Clean up**, read-only but for what each step names:

- `fylgja-core twin list` empty. A destroy has no verdict to wait for: a rehearsal asks its twin's
  deletion and reads it until it is gone, for 120 s, and names one still there in its report
  (`rehearsal.twin.left`). So the twin the document names, `rh-…`, is read with `fylgja-core twin
  show <twin>` until it answers that the twin is not found, and one that stays is destroyed by
  `fylgja-core twin destroy <twin>`, which the run's record says.
- A dry run's proposed change is removed with its branch and its marks by `make infrahub-seed`,
  which deletes the branch's open proposed change and its marks before it makes the branch anew;
  the block then passes R3 again.
- A maintainer's proposed change is left open and unmerged until what was read of its run has
  passed review, then closed: `CoreProposedChangeUpdate` with `state` `closed`, sent with the
  writer's token, and read once after, the filter by its branch and `state` `open` answering none.
  A closed proposed change and its thread stay in Infrahub through every later seed: R3, the seed,
  the change source and the glue each count the branch's open ones alone.
  None is ever merged: a merge moves `main` under the fixture.
- When the work is done: the runner stopped by its pid, R5's, and the core by its pid, R6's, the
  listener of `FYLGJA_LISTEN`; then `make prefect-down` and `make infrahub-down`.

**On the cluster** Infrahub, Prefect and the runner stay on the development host, and everything
is as above but this:

- The core is the deployed one alone: the local core stopped by its pid, nothing listening on
  `FYLGJA_LISTEN`, and no core started in process against the cluster ("Never two cores on the
  cluster at once"). It runs the integration image, built, pushed and deployed as
  [Running the core on a cluster](#running-the-core-on-a-cluster) says, at one replica
  (`<kubectl> -n fylgja get deployment fylgja-core`, `<kubectl>` the site's path to `kubectl`).
  The overlay's `secret/tokens` holds the principal `orchestrator` with the hash of
  `FYLGJA_ORCHESTRATOR_API_TOKEN`, since `make orchestrator-serve` hands the runner that token
  there too.
- The runner, stopped by its pid where it runs, is started by one command that loads `local/.env`,
  then sets Reach's three, then runs the target. A load after the three would set `local/.env`'s
  address again, and the run would rehearse on the host.

  ```bash
  set -a; . local/.env; set +a
  export FYLGJA_API_ADDRESS=https://<the Service's address> FYLGJA_API_CA=$PWD/local/<the site's CA>
  export FYLGJA_API_TOKEN="$(< local/<the token's file>)"
  make orchestrator-serve
  ```

- The block is run as it stands after the same first three lines,
  `out=local/phase-8/acceptance/<run>` and `kubectl() { <kubectl> "$@"; }` in place of the target.
  With `FYLGJA_API_CA` set, R6 reads the deployed core: an `https://` address; no listener on
  `FYLGJA_LISTEN`'s port, where the local core served; the Deployment `fylgja-core` at one replica,
  its image's tag printed as the text after the reference's last `:`; `capacity show --json` and
  `twin list` with the caller's own `FYLGJA_API_TOKEN`, Reach's, answering the driver `clabernetes`
  and more than one host, the room and the twins as above; and `GET /v1/twins` once with the
  runner's token, which a token file lacking its hash refuses. A read that lists one host is the
  local core's.
- Mid-run the twin is on the cluster: one `rh-` twin in the deployed core's `twin list`, its
  namespace `fylgja-twin-<twin>` in `<kubectl> get namespaces`, and no SR Linux container in
  `docker ps` on the host.

## Conventions

- **Platforms are data.** A platform is added by writing a platform package under `psp/`,
  never by code ([D-013](design/decisions.md#d-013), [D-015](design/decisions.md#d-015)).
- **Fixtures change in a commit of their own,** with the diff reviewed: the blueprints, the
  compiler facts and any golden file.
- **A rejection fixture carries one fault,** named in its file name and its header comment
  (a blueprint's in its `source` envelope), and the loader's or the compiler's test holds a
  row per fixture saying the rule and the pointer or object it must report: exactly those,
  so that nothing else is reported, and a fixture without a row fails.
- **A new rule goes in [`docs/rules.md`](docs/rules.md)** in the same change as the code
  that files it.
- **No credential in any output**: not in a blueprint, bundle, finding, answer or log line.
