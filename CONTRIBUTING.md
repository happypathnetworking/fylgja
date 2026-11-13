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
     wrong; one that leaves an item for the landing also puts it in one list, as it is ruled.
   - A plan's whole branch is reviewed once more, then merged into the integration branch.
   - Live runs are one at a time.
   - The maintainer's word on an acceptance run says what they read, the report in its
     thread, not only that it passed.
   - Where a phase is done when the maintainer has watched a thing, the plan says how they
     watch it: they run the command, or its whole output is shown to them before the next
     act, and their word on whether that was their watching is recorded as they gave it.
   - A live run made from the main checkout, the one that holds `local/`, runs that
     checkout's code: it is checked out at the code under test for the run, and put back.
4. **Land.** On the maintainer's word:
   - the phase is written as built on the integration branch: a decision entry for each
     place the build departed from a decision, the sentences it made untrue corrected, and
     the item in "Sequence" marked done, with what it left to later phases;
   - that commit is reviewed afresh, its findings fixed by amending it and the fix read
     again, before the history is tagged;
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
| Prefect | 3.9.2 | The example orchestrator's edge alone: the two deployments Infrahub's checks start, the second of which NetBox's webhook starts too ([D-085](design/decisions.md#d-085), [D-097](design/decisions.md#d-097)). Pinned as read on the development host: it was three days old when the design chose it, under the two weeks every other pin keeps |
| NetBox, netbox-docker, netbox-branching | 4.7.5, 5.1.1, 1.2.3 | The development NetBox (`make netbox-up`): netbox-docker's release for its version, fetched into `local/netbox/` and never vendored, its image with one layer adding the branching plugin, built from `netbox/dev/`, run by Docker's Compose plugin ([D-096](design/decisions.md#d-096)). Pinned as read on the development host: NetBox's 4.7.5 was two days old when the design chose it, under the two weeks every other pin keeps, on the maintainer's word ([D-099](design/decisions.md#d-099)) |

Each pin, the `server` extra's among them, and each floor of the base install is a release at
least two weeks old when it was chosen, but Prefect's and NetBox's, as their rows say. `make venv` builds
`core/.venv` from `core[server,dev]`, the reader's `readers/infrahub[dev]`, the NetBox reader's
`readers/netbox[dev]` and the example orchestrator's `orchestrator[dev]`, each package installed
editable: the versions every tier runs on. A venv inside the tree carries a `.gitignore` of `*`.

## Make targets

| Target | What it does |
|---|---|
| `make venv` | The core's venv, `core/.venv`, from `core[server,dev]`, then the reader's `readers/infrahub[dev]`, then the NetBox reader's `readers/netbox[dev]`, then the example orchestrator's `orchestrator[dev]`: each package editable, at the versions every tier runs on |
| `make lint` | ruff over `core/`, `scripts/`, `infrahub/` and `netbox/`, then mypy in strict mode over the core, its tests and `scripts/`, and again, apart, over `infrahub/seed/`, `infrahub/tests/` and `scripts/infrahub_dev.py`, and a third time over `netbox/seed/`, `netbox/tests/` and `scripts/netbox_dev.py`, since the three directories of tests name modules alike; then the same over the reader, `readers/infrahub/`, and over `orchestrator/`, and over the NetBox reader, `readers/netbox/` |
| `make test` | The pure tier: no infrastructure. `core/tests/`, then `infrahub/tests/`, then `netbox/tests/`, then the reader's, then the example orchestrator's, then the NetBox reader's. Gates every pull request |
| `make live` | The live tier on the local driver: the driver's own modules under `core/tests/live/`, then the conformance suite on the local harness. The driver's own: readiness and the push on one SR Linux and one cEOS node booted under containerlab (`core/tests/live/test_push.py`); labs through the local driver, `admit`, `apply`, `inspect` and `destroy`, the residue rule and two labs at once (`core/tests/live/test_containerlab_driver_live.py`); three labs applied at once, their deploys one after the other, with the host's load and connections read (`core/tests/live/test_many_labs_live.py`, about 2.5 minutes alone); `changes` held to containerlab's own dry run for every step fixture, with the hot-add recreate of two cEOS nodes and `exec` in a probe host (`core/tests/live/test_changes_live.py`, about 4.5 minutes alone); verify over gNMI on a probed twin, with a node stopped and started by containerlab and by Docker, and a configured cEOS node's host name (`core/tests/live/test_verify_live.py`, about 5 minutes alone); the trigger and the restore through Docker's own restart paths, the loop run in-process with its resync an hour away: a node restarted by `docker restart` and one started again by Docker's restart policy, each pushed again by a restore the driver's events started within seconds (its links are not restored), and one removed, reported missing once its boot window passed (`core/tests/live/test_restore_live.py`, about 4 minutes alone); and the object store against Versity S3 Gateway under Docker, the store contract whole and every compare-and-set raced by 32 stores (`core/tests/live/test_object_store_live.py`, about 1 minute alone). Then the suite, as `make conformance DRIVER=containerlab` runs it (below), its many-twins scenario among it, about 36 minutes of the whole. 165 tests by collection; the tier was last timed whole at about 54 minutes, with the cluster quiet, and the suite has since grown from about 31 minutes to 36, so about 59 minutes, a derivation and not a reading. Load `local/.env` first |
| `make cluster` | The cluster tier: the clabernetes driver's calls on the k3s cluster, from the development host. The driver's reach into Kubernetes, every call of `LightKube` read on a two-node SR Linux twin (`core/tests/cluster/test_kube_cluster.py`, 1 to 2 minutes alone); the driver as the server makes it on a three-node twin: `admit` against a namespace that is not the twin's, `apply` with the root logger at DEBUG and its repeat, `exec`, a node's container ended in its pod, a pod deleted, `reconfigure`, `destroy` and the residue (`core/tests/cluster/test_clabernetes_driver_cluster.py`, about 4 minutes alone); and `changes` held to the pods' uids for every step fixture, with the hot-add recreate of two cEOS nodes killed before its deletions and resumed (`core/tests/cluster/test_clabernetes_changes_cluster.py`, about 10 minutes alone); and the trigger and the restore through the loop, run in-process with the resync an hour away, on a two-node twin stepped twice: a pod deleted, a container ended in its pod and that pod replaced by the driver, a probe host's and a cEOS node's pods deleted, each restored without the resync, the settled twin's pods watched for three minutes, and a watch asked at a compacted version (`core/tests/cluster/test_restore_cluster.py`, about 14 minutes alone); and the Lease, on a Lease of its own in the kubeconfig's default namespace held by two holders in one process: taken, waited for, taken over 15 s after its holder went silent and released (`core/tests/cluster/test_lease_cluster.py`, about 30 s alone). About 30 minutes. Load `local/.env` first, with `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE`, `FYLGJA_POD_CIDR` and the cEOS pull credential set. With the core deployed on the cluster, its Deployment is scaled to no replica first and back to one after ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make conformance DRIVER=containerlab\|clabernetes` | The driver conformance suite alone (`core/tests/conformance/`): one set of scenarios, written once, on the harness of the driver `DRIVER` names, `containerlab` by default; any other name is refused in one line. A twin created and shown; stepped through every step fixture with verify after each and the burst held, and the step's refusals; the core killed at each phase boundary of a create and of a step, during an apply and during a destroy, a waiting CLI riding through, a deletion after a kill, and a step cancelled; a node replaced behind the core and one stopped; leftovers read by label; node access through each node's own transport; and isolation over TCP between two twins and from a third namespace, where the driver declares it. Then many twins at once (`core/tests/conformance/test_many.py`): the harness's count, three here and five on the cluster, created together and all Ready, each stepped while the others run with no node unread, a twin of forty nodes refused in a dry run and at its create with the capacity read agreeing, and every twin destroyed, about 5 minutes here and 8 on the cluster. The scenario needs a band of room: about 4.5 CPU and 17 GiB free here for its three twins and 7.5 CPU and 28 GiB on the cluster for its five, and, with them up, under about 80 GiB free on either, since the forty-node twin must be refused; on a roomier runtime its dry run is answered and the scenario fails there, having made no twin of it. `containerlab` runs `fylgja-core-server` on this host under the live tier's marker: 54 tests, about 36 minutes. `clabernetes` drives the core deployed on the cluster over TLS, killing it by its pod, under the cluster tier's marker: 54 tests, about 71 minutes. Load `local/.env` first, and for the cluster the suite's own variables ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |
| `make wheelcheck` | Builds the core's wheel from `core/` and `formats/`, which carries the core's formats and no other, and installs it into two empty venvs outside the tree: with the `server` extra, where it validates a fixture and the server's modules import; and alone, each of the base's four libraries at the floor of its range, where the model and the client import, a run is followed over a fake transport and `fylgja-core-server` refuses in one line; then the reader's wheel, from `readers/infrahub/` and `formats/` and carrying its one format, `infrahub-reader-1`, and no other, with its GraphQL documents, beside the base alone in a third, where the seed's reader document decodes, the command's module imports with nothing of the server, Prefect or Infrahub's SDK, and `fylgja-infrahub --help` exits 0; then the example orchestrator's wheel, from `orchestrator/` and `formats/` and carrying its two formats and no other, with its Infrahub change source's GraphQL documents, beside the base and the two readers' wheels alone in a fifth, where a plan and a rehearsal validate, the rehearsal library imports with nothing of the server, either reader or Prefect loaded, both change sources import, the Infrahub one reading each of its GraphQL documents from the installed package, the command's module imports with nothing of the server or Prefect, nothing of the server's libraries is installed but the two Prefect brings, starlette and uvicorn, and `fylgja-orchestrator --help` and `fylgja-orchestrator stage mark --help` exit 0 ([D-066](design/decisions.md#d-066), [D-084](design/decisions.md#d-084)). Between the reader's and the example's, the NetBox reader's wheel, from `readers/netbox/` and `formats/` and carrying its one format, `netbox-reader-1`, and no other, is installed beside the base alone in an empty venv of its own, where a copy of the seed's reader document decodes, the command's module imports with nothing of the server, Prefect, a client library of Infrahub's or NetBox's, the Infrahub reader or the example, `fylgja-netbox --help` exits 0, and `fylgja-netbox check` given no token exits 2 with the one line that names `FYLGJA_NETBOX_TOKEN` ([D-095](design/decisions.md#d-095)). Needs the network, so it is no part of `make test`; CI runs it on every push to `main` and every pull request |
| `make image` | Builds the core's image from the `Dockerfile` at the root ([D-062](design/decisions.md#d-062)) as `fylgja-core:<tag>`, the tag the commit's first 12 characters, with `-dirty` where `git status --porcelain` prints anything. Its build context is `.dockerignore`'s allow-list, so nothing under `local/` reaches a layer. Needs Docker and the network |
| `make imagecheck` | Builds the image, then runs it: its user is 10001; given only `FYLGJA_STORE` and a `FYLGJA_TOKENS` that names no file, it exits 2 naming `FYLGJA_TOKENS`, its packages loaded against the wheel's formats; and the formats it carries are the core's, `CORE_FORMATS` in `core/setup.py`, equal to `formats/`'s by name and by bytes; and its copies of `psp/` and `probes/` hold the files git tracks there and no other, by path, so a file git ignores there (an editor's `*.swp`, a nested `local/`), which reaches the image with no `-dirty` tag, fails it. Prints the tag it checked last. CI runs it on every push to `main` and every pull request, and pushes nothing |
| `make infrahub-up` | The development Infrahub, the Compose project `fylgja-core-infrahub` at `INFRAHUB_VERSION` (1.11.11), run by `scripts/infrahub_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its eight names ([`.env.example`](.env.example)) that the file does not hold, generated and never printed, and changes no line already there, since a token made again would not open the kept database; a name the file holds with no value (`NAME=`, `NAME=""`, read from its last line where it has several) is refused, exit 2 and before anything is fetched or started, naming it, since Compose would replace it by the published file's own default; so is `NAME= # a note`, which a shell reads as empty and Compose as the text `# a note`; makes `local/infrahub/repos/` (mode `0700`) where it is absent; fetches Infrahub's published Compose file for the version into `local/infrahub/` once; starts the project with `infrahub/dev/compose.override.yml`, asking Compose once more where its first start fails; and waits up to 600 s for `/api/info` to answer that version, failing at once on another. `VERSION` is the make variable's whatever the shell or `local/.env` holds, and Compose is given none of the eight names and no other name beginning `INFRAHUB_` from the shell, whatever it exports, so that it reads them from `local/.env` alone or takes the published file's defaults: an `INFRAHUB_ADDRESS` exported for a client would otherwise be the task workers' address of Infrahub. The task workers mount the main checkout's `.git` and `local/infrahub/repos/` read-only, and nothing else of the checkout, and are given the edge's Prefect's address and basic auth ([Running the example orchestrator](#running-the-example-orchestrator)). About 3.5 minutes on new volumes and 1.5 minutes on kept ones; it then holds about 4.5 GiB. Needs Docker, and the network for the first fetch |
| `make infrahub-down` | Stops the development Infrahub (`docker compose stop --timeout 60`), in 20 to 50 s: each container is given 60 s to exit by itself, since Compose's own 10 s killed Neo4j, which needs about 11 s, and the server once took 31 s. Its containers, network and volumes and everything under `local/infrahub/` are kept, port 8000 and the memory released, and `make infrahub-up` starts it again. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volumes (`down -v`), and `local/infrahub/seed.json` with them; `local/.env` and the rest of `local/infrahub/`, the fetched file among it, stay. It is stopped for every live, cluster or conformance run |
| `make infrahub-register` | The schema library, the group and this repository's registration on the development Infrahub's `main` (`infrahub/seed/register.py`), at `REF`, the branch checked out, from a worktree too, and that branch's commit; an empty `REF`, a detached head, is refused in one line. The library under `infrahub/schema/dcim/` is loaded by `infrahubctl`, given 600 s (`INFRAHUB_TIMEOUT`), where `main` holds none of its kinds, and `main` is read for up to 120 s until it lists them all; a `main` holding part of them is refused with nothing written. The group `fylgja-devices` is made where it is not there. The read-only repository `fylgja` is registered from the main checkout's `.git`, mounted at `/srv/fylgja`: created where there is none; its `ref` updated and its last commit imported where it names another branch; its last commit imported where it reads another commit; then read for up to 300 s until it reads the commit `in-sync` and `online`, with the artifact definition `device-config` on `main`. Then each running task worker of the project is read by `docker` for the tree of that commit, `/opt/infrahub/git/<the registration's id>/commits/<the commit>`: a recreated worker holds no clone, and a check Infrahub runs on it fails, so one lacking the tree is not settled. Its import is asked, at once where the run sent nothing and else 30 s on, and again every 30 s until each holds it, within 300 s: an import with no new commit clones on the one worker that runs it, and after a new commit's import each worker held the tree by an import or a pull of its own, Infrahub's fetch to each beginning after. One already there, settled and its commit's tree on each worker is sent nothing. Its first run builds `infrahubctl`'s venv, `local/infrahub/.venv/`, in about 45 s. About 2.5 minutes on an empty instance, read once, and seconds where all of it is there. Load `local/.env` first |
| `make infrahub-seed` | The fixture network on the development Infrahub's `main`, and the branch `SEED_BRANCH` (`third-link`) with its two staged edits, each regenerated, timed and marked, and with `PROPOSED_CHANGE=1` its proposed change (`infrahub/seed/seed.py`). It is refused with nothing written where `main` holds no artifact definition `device-config` (run `make infrahub-register` first). The reader's kind `FylgjaProbe`, `readers/infrahub/schema/fylgja-probe.yml`, and the example's stage kind `FylgjaStage`, `infrahub/schema/fylgja-stage.yml`, each passed as `--schema`, are then loaded on `main` by `infrahubctl` where `main` lacks them, and `main` read for up to 120 s until it lists each. `infrahub/seed/main/`'s object files are loaded by `infrahubctl`, one at a time in the order of their names, where `main` holds none of the devices they say: the manufacturer, the site `lab` under its metro, country and region, the platform, the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json` with their ports and addresses, each a member of `fylgja-devices`, the fixture's cables less the one between `n1` and `n3`, and the probe `n1-loop` of `three-node-probed.json`. Where `main` holds all three, nothing is loaded, since a load would take each device out of the query groups Infrahub joined it to at its first generation; so a hand edit on `main` is not undone by a seed, and a purge and a seed undo it; so too a `main` seeded before the probe's kind existed, which holds no probe, is purged and seeded again. A `main` holding part of them is refused with nothing written. The configurations are then generated and waited for, up to 180 s, until each device tagged `fylgja` has its artifact `device-config` `Ready` and each device the run made shows a checksum that moved; an artifact reading `Error` ends the wait at once. What an earlier seed left of the branch is then removed, whether or not the branch is listed: every `FylgjaStage` whose `branch` names it, since a mark outlives its branch, and its open proposed change, which Infrahub would keep open after the branch's delete. The branch is then made anew from `main`, after the registration's import ([D-088](design/decisions.md#d-088)): one an earlier seed left is deleted first, and the branch, made with `sync_with_git: false`, is refused where it does not read the artifact definition; a create that fails or goes unanswered is read for its branch for up to 120 s. On it, in order, `infrahub/seed/stages/1-third-link.yml` adds the cable between `n1` and `n3`, after which the network is `three-node.json`'s, and `2-n1-address.yml` the address `192.0.2.1/24` on its `n1` end. After each, the configurations are generated and waited for, up to 180 s, until each device the edit changes shows a checksum that moved, and the stage's time is the reader's `head` of the branch, the first instant after its latest write, read with the reader's token, `FYLGJA_INFRAHUB_TOKEN`, once two readings of it 10 s apart agree, within 120 s, so that `seed.json` and a read at its times cannot disagree; a `head` refused because a list it read was not whole, as the event log once was just after a generation, is read again, and one refused otherwise ends the seed. The stage is then marked: one `FylgjaStage` written on `main`, naming the branch, the stage's label and its time as `as_of`, verbatim. With `PROPOSED_CHANGE=1`, and no other value, the branch's proposed change into `main`, not a draft, named `Rehearse third-link`, is made last; without it the seed makes none, and the maintainer's opening one is what starts the rehearsal, since Infrahub runs a proposed change's checks when it is created ([D-088](design/decisions.md#d-088)). So every run leaves the branch's marks and, by the flag, its proposed change its own, and no other. The reader's connection is made before anything is removed or written: its token not set, or a variable not of its form, is exit 2, and Infrahub refusing it exit 1. `local/infrahub/seed.json` is removed before anything is written and written whole at the end, `{"branch", "scope": "tag:fylgja", "stages": [{"label", "at"}, …], "marks": [<label>, …], "proposed_change": {"id", "name"} | null}`, the stages and the marks in order; a run that fails or lapses leaves none. About 1.5 to 2 minutes on a seeded `main`: 93 s with no branch to delete, and 97 to 113 s remaking it; with the marks, 107 s and 137 s, and 115 s and 119 s with the proposed change; seeding an empty `main`, the kind and the probe among it, took 273 s. Load `local/.env` first |
| `make contract` | The contract tier (below), `infrahub/tests/contract/`, then the reader's, `readers/infrahub/tests/contract/`, and then the example orchestrator's, `orchestrator/tests/contract/`, against the running development Infrahub, with `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` set on its own command lines. One module of the reader's is run as its line runs the reader's, by its path in place of `tests/contract`. The reader's line, 30 tests, took 757 s run alone, measured once since a branch's events take in `main`'s up to its branch point, and 396 s and 402 s in two runs before; 895 s within the whole tier below. The registration's tests read the task workers' clones by `docker`. The example orchestrator's tests need its account's token, `make orchestrator-env`'s, and the development Prefect and runner down (`make prefect-down`): they start a Prefect of their own on loopback, and stop where anything listens on port 4200, which Infrahub's checks of the proposed changes they make would reach. The orchestrator's line, 11 tests, took 722 s, and the tier whole 1,879 s, the reader's line 895 s of it, each measured once, on 2026-11-11. On 2026-11-12, with the cancel test's `timeout` 660, the three lines took 254.12 s, 1782.90 s and 1469.00 s, measured once: 3,506.02 s summed (a derivation, pytest's three times added). Load `local/.env` first |
| `make orchestrator-env` | The example orchestrator's lines in `local/.env` (`scripts/edge_dev.py env`), each written only where the file lacks it or holds it empty, its mode kept, and printed by its name and never its value: `FYLGJA_ORCHESTRATOR_AUTH`, the basic auth `fylgja:<generated>` that the edge's Prefect, the task workers and NetBox's webhook share; `FYLGJA_ORCHESTRATOR_API_TOKEN`, the runner's token of the core's, generated, its hash appended with the principal `orchestrator` to the token file `FYLGJA_TOKENS` names, its mode kept: where that is not set, or names no file, which the core would not read, it is refused in one line with nothing written; after which the core is restarted to read the file; `FYLGJA_ORCHESTRATOR_SCOPE`, `local/infrahub/seed.json`'s scope, else the seed's own; `FYLGJA_ORCHESTRATOR_READER`, the main checkout's `infrahub/seed/reader.yaml`; and `FYLGJA_ORCHESTRATOR_ROOT`, its `local/orchestrator/`; and `FYLGJA_ORCHESTRATOR_NETBOX_READER`, the main checkout's `netbox/seed/reader.yaml`, and `FYLGJA_ORCHESTRATOR_NETBOX_SCOPE`, the NetBox seed's `tag:fylgja`, which the runner is given as its reader document and its scope under the source `netbox`, so that the file holds both sources' at once. Then, but with `SOURCE=netbox`, `infrahub/seed/account.py`, as the admin: the Infrahub account `fylgja-orchestrator`, its group and its one role, held to exactly four permissions, `object:Core:ChangeThread:create:allow_default`, `object:Core:ThreadComment:create:allow_default`, `global:edit_default_branch:allow_default` and the instance's own `object:*:*:view:allow_all`; and its token, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, made by the account's own login, where the line is missing, or replaced in place where Infrahub refuses the line's token, so the target is run again after a purge. A second run writes nothing; a `local/.env` written before the two NetBox lines existed gains them at its next run. `account.py`, run again with the line accepted, took 0.8 s. Needs `local/.env` there, which `make infrahub-up` or `make netbox-up` makes, and the development Infrahub up. With `SOURCE=netbox` ([D-097](design/decisions.md#d-097)) it runs nothing of Infrahub's and needs no Infrahub, the example's NetBox token being `make netbox-seed`'s; a `SOURCE` that is neither `infrahub` nor `netbox` is refused before anything is run. `SOURCE` is make's variable, so one exported in the shell is taken where the command line gives none: it changes this target and `make orchestrator-serve` as if it were given, or refuses both where it is neither. Load `local/.env` first |
| `make prefect-up` | The edge's Prefect (`scripts/edge_dev.py prefect-up`), `core/.venv`'s `prefect server start --no-ui` on port 4200 of the Docker bridge's gateway, which the task workers and NetBox's worker reach as `host.docker.internal`, or of `PREFECT_BIND` where it is set; in a session of its own, under `local/prefect/` (its home, its database, `server.log` and `server.pid`), its basic auth `FYLGJA_ORCHESTRATOR_AUTH` given in its environment and never as an argument, analytics off; waited for up to 90 s until `/api/health` answers, 8.5 s after the target began, on a `local/prefect/` an earlier run had used, read once. A server it started that runs still is said to be up. Anything else listening on port 4200, on any address, is refused in one line naming the port and the address, with nothing started and nothing stopped: it is another project's. Load `local/.env` first |
| `make prefect-down` | Ends the server `local/prefect/server.pid` names, by SIGTERM to its session and SIGKILL after 30 s, only where that process is this project's Prefect server, its command line `prefect` and `server` and its `PREFECT_HOME` `local/prefect/`, and removes the file; it touches no other process, a reused pid among them |
| `make orchestrator-serve` | The runner of the change source `SOURCE`, `infrahub` where it is not given, or `netbox` ([D-097](design/decisions.md#d-097)), `core/.venv`'s `fylgja-orchestrator serve`, in the foreground until Ctrl-C, serving `stage-plan/main` and `twin-rehearse/main` to the edge's Prefect at `http://<the bind>:4200/api` (`scripts/edge_dev.py serve --source`). Its environment is its own and no other: Prefect's address, basic auth, home and analytics off; `FYLGJA_ORCHESTRATOR_SOURCE`, the source, whatever `local/.env` holds; the runner's own tokens as the names the edge reads, `FYLGJA_API_TOKEN` from `FYLGJA_ORCHESTRATOR_API_TOKEN` and the source's, under `infrahub` `FYLGJA_INFRAHUB_TOKEN` from `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, and under `netbox` `FYLGJA_NETBOX_TOKEN` from `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, with `FYLGJA_ORCHESTRATOR_READER` and `FYLGJA_ORCHESTRATOR_SCOPE` from `FYLGJA_ORCHESTRATOR_NETBOX_READER` and `FYLGJA_ORCHESTRATOR_NETBOX_SCOPE`; the other `FYLGJA_API_*` and `FYLGJA_ORCHESTRATOR_*` names as loaded, and under `infrahub` the other `FYLGJA_INFRAHUB_*`, or under `netbox` `FYLGJA_NETBOX_ADDRESS` and `FYLGJA_NETBOX_CA` alone; never `FYLGJA_INFRAHUB_WRITE_TOKEN` or `FYLGJA_NETBOX_WRITE_TOKEN`, the names it took its own from, the other source's, an `INFRAHUB_*` name of Compose's or a node's login; and `PATH` and `HOME`. A name it needs not set is one line naming it and the target that writes it, exit 2. Load `local/.env` first |
| `make netbox-up` | The development NetBox, the Compose project `fylgja-core-netbox`: NetBox `NETBOX_VERSION` (4.7.5) on netbox-docker `NETBOX_DOCKER_VERSION` (5.1.1) with netbox-branching `NETBOX_BRANCHING_VERSION` (1.2.3), run by `scripts/netbox_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its four names ([`.env.example`](.env.example)) that the file does not hold, the three secrets generated and never printed, and changes no line already there, since a pepper made again would refuse every token the kept database holds and a password made again would not be the superuser's; a name the file holds with no value is refused, exit 2 and before anything is fetched, built or started, naming it, as `make infrahub-up` refuses one. It fetches netbox-docker's release for its version into `local/netbox/netbox-docker-<version>/` once, never changed; where the project's network `fylgja-core-netbox_default` stands with another subnet than the override's 198.51.100.0/24, removes the project's containers and network and keeps its volumes, so that the start makes the network again, and where Docker could not inspect it says so in one line and goes on; builds the image `fylgja-core-netbox:<NetBox's>-<the plugin's>` from `netbox/dev/`, netbox-docker's with one layer adding the plugin; starts the project with `netbox/dev/compose.override.yml`, which mounts `netbox/dev/plugins.py` over the release's and publishes NetBox on loopback at port 8800; and waits up to 1200 s from that start for Docker to call `netbox` healthy, asking Compose once more where the first start failed, as it does while NetBox migrates, leaving the worker not started. It then reads `/api/status/` with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`, provisioned with the file's password and its line written, that line alone, where the file holds none or NetBox refuses the one it holds, as after a purge; a password NetBox refuses ends it, naming `make netbox-down PURGE=1`. It is done once NetBox names both versions and a running worker, within 60 s of healthy, without which no branch is ever ready, and fails at once on another NetBox, another plugin version or none, which is how a `plugins.py` not loaded shows. The three versions and `netbox/dev/` are set in Compose's environment over whatever the shell or `local/.env` holds, and Compose is given no other name beginning `FYLGJA_NETBOX_`, so that it reads the secrets from `local/.env` alone. About 12.5 minutes on new volumes, 748.9 s, 764.4 s and 749.6 s in three runs, and 73.7 s on kept ones, the image built from the cache each time; it then holds about 1.4 GiB. Needs Docker, and the network for the first fetch |
| `make netbox-down` | Stops the development NetBox (`docker compose stop --timeout 60`), in 8.9 s, read once, each container given 60 s to exit by itself. Its containers, network and six volumes and everything under `local/netbox/` are kept, port 8800 and the memory released, and `make netbox-up` starts it again holding what it held. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volumes (`down -v`), in 10.1 s; `local/.env`, the release and the image stay, and the next `make netbox-up` provisions the superuser's token again and replaces its line, and the next `make netbox-seed` makes the two accounts' tokens again and replaces theirs. It is stopped for every live, cluster or conformance run |
| `make netbox-seed` | The fixture network on the development NetBox's `main` (`netbox/seed/seed.py`), with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`. Each object `netbox/seed/main.yaml` says is found on `main` by its name, a device type by its model, an interface by its device and name, an address by its value and interface and a cable by its first end, or made: the manufacturer `Nokia`, the configuration template `fylgja-srlinux` from `netbox/seed/template.j2`, the platform `SR Linux` naming both, the device type, the site `lab`, the role and the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json`, each `active` and tagged, with their fifteen ports and six addresses, the fixture's cables less the one between `n1` and `n3`, and last the configuration context `fylgja-probes`, inactive, whose data is `three-node-probed.json`'s probe `n1-loop`, so that no device's rendered context takes it. Of an object found, the template's code, the platform's template and the context's data and state are written again where they differ, and nothing else; a fixture port cabled to another port than the fixture's is refused, naming both, before any cable is made. `main` is then read back, the devices tagged `fylgja` with their platform, ports, addresses and cables, and each difference from the fixture said, such as the cable or the address a merged change left, exit 1 with `make netbox-down PURGE=1`, since the seed deletes nothing. One line an object, `made` or `found`; a second seed writes nothing. Then the two accounts (`netbox/seed/account.py`), the reader's `fylgja-reader` and the example's `fylgja-orchestrator`, each with the superuser's token: its user found by its name or made, active and no superuser, its password generated, sent and kept nowhere, a user found holding a group or a permission of another name refused, naming each and `make netbox-down PURGE=1`, nothing removed; each of its grants found by its name or made, and brought by one `PATCH` to exactly its row where it holds another type, another action or another user: the reader's `view` of the nine types a read lists and `view` with `render_config` on `dcim.device`, and the example's the same under its own names with `view` and `add` on `extras.journalentry` and `view` and `change` on `netbox_branching.branch`; and its token's line, `FYLGJA_NETBOX_TOKEN` and `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, kept byte for byte where NetBox holds exactly one token of its key and that one the account's, else a token made by the superuser and the line appended, or put in place of the last line that holds its name, as after a purge, every other line kept and the file left at mode `0600`. A replaced token is not revoked. It prints what it made, set or replaced and never a value, and NetBox not answering leaves the file as it was. A failure of either names the remedy for what failed: the purge, then `make netbox-up`, `local/.env` loaded again and `make netbox-seed`, only where NetBox holds what neither removes, a difference from the fixture or an account's stray; `make netbox-up` where NetBox does not answer; and `local/.env` loaded again where NetBox refuses the write token, as after a purge, then `make netbox-up`, which provisions a refused token again without a purge, the purge named only as what remains. NetBox answering two rows to a lookup of one, or a token as another user's, names none. The seed alone took 25.4 s on an empty `main` and 16.4 s on a seeded one; with the accounts, 29.3 s on an empty `main` after a purge, 21.4 s making the accounts alone on a seeded one, and 18.2 s making nothing, one run each. Load `local/.env` first, and again after it for the two lines |
| `make netbox-hook` | The trigger on the development NetBox (`netbox/seed/hook.py`, [D-097](design/decisions.md#d-097)), with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`: the tag `fylgja-rehearse`, limited to branches; the webhook `fylgja-rehearse`, a `POST` to `http://host.docker.internal:4200/api/deployments/<id>/create_flow_run`, its body the branch's name as the flow's one parameter and its `additional_headers` the header line of the basic auth `FYLGJA_ORCHESTRATOR_AUTH`; and the event rule `fylgja-rehearse`, which sends it when a branch carrying the tag is updated. Each is found by its name or made; of one found, each member it writes is compared with what stands and those that differ alone are written again, in one `PATCH`, so a run that finds the trigger as it should be writes nothing. They are left, as the seed's objects are, and `stage.main.gained` counts nothing of the webhook's or the rule's rows of `main`'s changelog. `<id>` is the deployment `twin-rehearse/main`'s, read from Prefect with the basic auth at the API `scripts/edge_dev.py api` prints, `http://<the bind>:4200/api`; a deployment's id is another once Prefect's home is new, and a webhook naming an old id is answered 404 and starts nothing, so the target is run once `make orchestrator-serve SOURCE=netbox` serves, and again after every new `local/prefect/`. It prints a line for each thing it made or wrote again, naming the members written, then the deployment the webhook starts, and never the auth or the header; Prefect not answering, not serving the deployment or refusing the auth is exit 1, one line with the remedy where one is known, and nothing is written to NetBox. `hook.py` ran in 1.2 to 1.4 s, six runs within the contract tier. Load `local/.env` first |
| `make netbox-change` | The seeded change on the development NetBox (`netbox/seed/change.py`, [D-097](design/decisions.md#d-097)), with the superuser's token: the branch `NETBOX_BRANCH` (`third-link`), where it stands, deleted with every journal entry on it, its marks of an earlier build among them, one still `new` or `provisioning` waited for until `ready` first and one of any other status refused by its status with nothing deleted; then made anew from `main` and waited for until `ready`. Its two steps, `infrahub/seed/stages/`' two edits, the cable between `n1` and `n3` and then the address `192.0.2.1/24` on `n1`'s end, are written under its header, each marked as soon as it is written by the example's own `stage mark --branch <branch> --label <step>`, run through `scripts/edge_dev.py run --source netbox` under the example's token, which needs the core running at `FYLGJA_API_ADDRESS`, since a mark's blueprint is the core's. With `NETBOX_TAG=1`, and no other value, the tag `fylgja-rehearse` is added to the branch's tags last, which asks for its rehearsal; where NetBox holds no such tag (`make netbox-hook` makes it) that is refused before anything is written. A label is unique within its branch and never taken twice, and NetBox reads no branch as it stood earlier, so a change is built whole each run, never added to, and seeded and marked once for each core it is rehearsed through. A mark refused stops it, exit 1, the branch left as it stands for reading, and the next run builds it again. 24.2 s, and 26.2 s run again, deleting the first build's branch, one run each. Load `local/.env` first |
| `make contract-netbox` | The NetBox contract tier (below), `netbox/tests/contract/`, against the running development NetBox, seeded, with `local/.env` loaded after `make netbox-seed` for `FYLGJA_NETBOX_ADDRESS`, `FYLGJA_NETBOX_WRITE_TOKEN` and the two accounts' tokens, `FYLGJA_NETBOX_TOKEN` and `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`; it seeds `main` first, as `make netbox-seed` does: 14 tests. Then the NetBox reader's tier, `readers/netbox/tests/contract/`, the reader given `FYLGJA_NETBOX_TOKEN` and, for an `https://` address, `FYLGJA_NETBOX_CA`, never the write token: 45 tests. Then the example's NetBox change source's, `orchestrator/tests/contract_netbox/`, the source and a runner of the source `netbox` given the example's token, `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, with a core and a Prefect server of the tier's own, the server on the Docker bridge's gateway at a free port, and the installed trigger, which `make netbox-hook` writes and the tier rewrites and writes back: 12 tests. A test that sets the tag stops where anything listens on port 4200, so the development Prefect is down (`make prefect-down`). Run whole three times on 2026-11-13 it exited 0 in 1,087 s, 1,070 s and 986 s: in the first, by the shell, `netbox/`'s 14 in 152.47 s, the reader's 45 in 573.18 s, and the example's 12 in 357.19 s; in the last, 133.07 s, 524.66 s and 323.62 s |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures, and the store, the object store over a fake S3 endpoint, the reconcile loop, API 1 and the CLI over fakes of the runtime; and, under `infrahub/tests/`, what `infrahub/` gives Infrahub, read as files (the schema library at its commit, the registration with its query and its template, the Compose override, the seed's object files, `main`'s and the seeded branch's two stages, against the fixture, and the reader document), the names and addresses of the tracked tree, the development Infrahub's script over fakes of Compose, the fetch and the clock, and `infrahub/seed/`'s transport, registration and seed over fakes of Infrahub, `infrahubctl`, the reader's `head` and the clock, and the example's account and its token's line over a fake of Infrahub; under `netbox/tests/`, what `netbox/` gives NetBox, read as files (the image's one layer, the Compose override and the plugin's configuration, and the seed's fixture, its probes' context, its template and its reader document, against the blueprints and the package), the names and addresses of `netbox/` and `scripts/netbox_dev.py` and `.env.example`'s NetBox names, the development NetBox's script over fakes of Compose, the fetch, NetBox and the clock, and `netbox/seed/`'s transport over a fake of NetBox's HTTP (each path under `/api/` with the bearer and a branch's header, every page of a list held to its `count`, a name that matches twice refused, a row found before one is made, a branch made once and waited for until `ready`, a branch answered for another name refused, the request timeout, a query's `None` refused, and the token kept out of every error) and its seed over a fake of NetBox's REST API (everything made once, each after the objects its body names, a second seed writing nothing, the template's code, the platform's template and the context written again where they differ and nothing else, a fixture port cabled elsewhere refused before any cable is made, a `main` that is not the fixture refused naming each difference, a variable not set, and the token kept out of everything printed), and its two accounts over the same fake (each account, its grants and its token made on a first run and the two lines appended, every other line kept and the file at mode `0600`; a line NetBox still takes kept byte for byte and nothing sent but reads; a dead line, one that is no token and one of the other account's replaced where it stood, the last where a name is held twice; a grant wider than its row brought back by one `PATCH`; a user found inactive set active; a superuser, a group or a permission of another name refused naming it, with nothing written; NetBox not answering at any request leaving the file as it was; and no token and no password in anything printed or raised, a password or a line's key echoed across the cut of NetBox's words among them), and the NetBox contract tier's branches, its fixtures' own functions over a fake of NetBox's branches (a branch deleted whatever its test did, also where it never read `ready`, and the session's sweep deleting the tier's own branches and no other, waiting for one still provisioning by reading it and never making one, and the writer's `repr` holding no address), and the trigger, `netbox/seed/hook.py`, and the seeded change, `netbox/seed/change.py`, over the same fake of NetBox and a fake of Prefect (the three made by name, the webhook naming the deployment's id, a member found otherwise written back alone and said, nothing written where all stands as it should, the basic auth never printed and hidden across the cut of NetBox's words; a branch of the name deleted and made anew before any step, each step written under its header and then marked, a mark refused stopping the change, and the tag set last and only by its flag); under `readers/infrahub/tests/`, what the reader's modules import, its rows with the rule that every list is whole, over rows built in the tests, its reader document, loaded from files and refused by its rules, its times, its GraphQL documents, its transport over a fake of Infrahub's HTTP (the version, the branch's path and `at`, the pager, the event log's pager down to its floor, an artifact's content by its storage id alone, the refusals with their statuses, a stamp that is no time, and the token kept out of every error), its schema check, each difference from its table its rule, over the table's own kinds as rows, and its mapping, each device's configuration from its artifact and the read with its source envelope, over rows built in the tests (the fixture's network and id, one document whatever order the rows come in, the forms judged before anything is sent, and each omission, refusal and fault of an artifact its rule, every device at fault in one pass), and its stale rule and `head`, over rows built in the tests (each node a configuration renders from moving its devices alone, the task workers' restamp discounted and `__system__` never, the events that show what no stamp does, `generated_since`, and the first instant after the latest write, every stamp and event counted, a probe's among them where the branch has the kind); and its probes, the kind's file against blueprint 1's patterns and its probes over rows built in the tests (the probed fixture's id, read only where the document asks, the kind absent, a probe of another scope omitted, a renamed device, each fault of the declaration its rule, a null attribute among them, and a list not whole); and its command over a fake of `connect` and the environment (each exit, what each stream holds, the token in neither), and its README's versions and `mapping.md`'s members held to the code; and the example's rehearsal library over a fake change source and the core's server on its fake runtime, and its Infrahub change source over rows built in the tests and a fake of Infrahub's HTTP (the open proposed change of a branch, the stages' order and pins, the wait for the artifact validation, each stage's time and `generated_since`, `main` moved, and the report's thread, measured first, with the token in no error), and its NetBox change source over a fake of NetBox's HTTP (`fake_netbox.py`) with the reader's `connect` and `read` replaced by fakes that record what they were given (a ready branch by its exact name and one gone or not `ready` refused, the stages `main`, the marks in the order written and the head, a mark's entry read back as written and each fault of one refused by its rule, its blueprint read back from the core by its id, `main` and the head read again where they moved, the count of what `main` gained, the mark taken and refused, the tag taken off once, and the report one journal entry of its status's kind with its lists spaced, with the token in no error), a marked branch rehearsed from `main` to its head through the library and the core's own server, and the NetBox contract tier's judgments of the installed webhook and its branches over a fake; and under `readers/netbox/tests/`, the NetBox reader: what its modules import, its rows with the rule that every list is whole, over rows built in the tests (a list short of its `count` or longer than it, one object twice, and an id asked for and not answered), its transport over a fake of NetBox's HTTP (both versions and the warning outside those verified, the token as a bearer and a branch by its `schema_id`, every page of a list read to the largest `count` NetBox answered and never by its `next`, ids asked fifty a request and their counts summed, each row held to what was asked and to the members it needs, a refusal's status kept with the branch, its body read as JSON only where NetBox says it is, a redirect named by its path alone, and the token kept out of every error, `repr` and log line), the requests it sends, read from its source (each a `GET` but the render's `POST`, through one sender, none by any other of httpx's senders, and no path of NetBox's named in another module), its reader document, loaded from files and refused by its rules; its mapping over rows built in the tests (the fixture's network, one network whatever order the rows come in, a cable's sides swapped among them, a name made a label, two devices of one label each refused, a device with no package refused, and each omission of a cable its rule, every finding in one pass); its bracket (an edit, a row written below the open's id, a sync, a branch gone or no longer `ready`, and a 400 to the close's own requests under a branch's header, each `read.moved`, the rows no read reads refusing nothing, and the changelog or the branches' list short of its `count` `read.incomplete`); its renders, each answer `render-config` can give its rule, no byte of a configuration quoted; the read and its source envelope over a fake source (the fixture's id, the bracket opened before the first list and closed on every path past it, a 400 weighed at the close, every scoped device rendered and every fault filed in one pass, the scope's and the branch's refusals before anything is sent, and the same rows in any order one document); its probes, the seeded context's declaration read inside the bracket, a probe of another scope omitted, a renamed device followed and each fault of the declaration its rule; its command over a fake of `connect` and the environment (each exit, what each stream holds, the token and its halves in neither, and `--out` written whole or not at all); its contract tier's branches, its fixtures' own functions over a fake of NetBox's branches (a branch deleted whatever its test did, also where it never read `ready`, and the session's sweep deleting the tier's own branches and no other, waiting for one still provisioning by reading it and never making one, one gone before its `DELETE` not reported, and one `failed` deleted or named); the names and signatures it exports for what consumes it, and those its consumers are typed against beside them; its rule catalogue held to the code; and its README's versions and upgrade table and `mapping.md`'s members held to the code and the facts |
| **Live** | Booted images on the local containerlab driver, and Versity S3 Gateway under Docker | On demand: `make live`, with `local/.env` loaded: the driver's own modules under `core/tests/live/` (the driver, `changes` against containerlab's dry run, readiness and the push, verify over gNMI, the trigger and the restore through Docker's restart paths, and the object store against the gateway), then the conformance suite on the local harness. 165 tests by collection; about 59 minutes, derived from the 54 minutes last read with the cluster quiet and the suite's growth from about 31 minutes to 36, not re-measured. Never while the cluster runs the suite or the cluster tier: here the two share a hypervisor, and SR Linux segfaults under the contention. `make test` deselects it (the `live` marker) |
| **Cluster** | The k3s cluster, reached from the development host | On demand: `make cluster`, with `local/.env` loaded and `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE` and `FYLGJA_POD_CIDR` set: the clabernetes driver's calls on the cluster, its reach into Kubernetes first (`core/tests/cluster/test_kube_cluster.py`), then the driver's calls and `changes` held to the pods' uids (`core/tests/cluster/test_clabernetes_driver_cluster.py`, `core/tests/cluster/test_clabernetes_changes_cluster.py`), the trigger and the restore through the loop (`core/tests/cluster/test_restore_cluster.py`), and the Lease (`core/tests/cluster/test_lease_cluster.py`). Each test twin has its own namespace, deleted at its module's end; never while `make live` runs. `make test` deselects it (the `cluster` marker) |
| **Driver conformance** | Each driver's own runtime: for the local driver, containerlab and Docker on the development host; for clabernetes, the core deployed on the cluster with `FYLGJA_RESYNC_S` of 3600 or more, a token of the suite's own principal, both node logins and the cEOS pull credential, reached from the development host ([Running the core on a cluster](#running-the-core-on-a-cluster)) | On demand, per driver: `make conformance DRIVER=containerlab`, 54 tests in about 36 minutes, which `make live` runs too; and `make conformance DRIVER=clabernetes`, 54 tests in about 71 minutes. Each was measured with the other runtime quiet, and the two are never run together here: they share a hypervisor. Each runtime needs the many-twins scenario's band of room: about 4.5 CPU and 17 GiB free locally and 7.5 CPU and 28 GiB on the cluster, and under about 80 GiB free on either with its twins up, so that its forty-node twin is refused. `make test` deselects the suite (its harness's marker, `live` or `cluster`) |
| **Contract** | The development Infrahub, up and registered (`make infrahub-up`, `make infrahub-register`), reached at `FYLGJA_INFRAHUB_ADDRESS` with the writer's token, `FYLGJA_INFRAHUB_WRITE_TOKEN`, and the reader's, `FYLGJA_INFRAHUB_TOKEN`, which the seed's `head` reads with; for the reader's, seeded too (`make infrahub-seed`, which `infrahub/tests/contract/` runs again); for the example orchestrator's, its account's token too, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN` (`make orchestrator-env`), and a Prefect server on loopback, which its tests start, with the development Prefect and runner down (`make prefect-down`) | On demand: `make contract`, with `local/.env` loaded; it sets `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` on its own command lines. `infrahub/tests/contract/`: the library, the group and the registration as `main` holds them, and a second registration that changes nothing; then the seed run whole, as `make infrahub-seed` runs it, the reader's kind and the stage kind passed and each stage timed by the reader's `head`, writing `seed.json` where `FYLGJA_INFRAHUB_SEED` names it: `main` left the fixture less one link, `seed.json`'s branch, scope and two stages in order, with their marks and no proposed change, each stage marked on `main` at its time and the branch with no open proposed change, the branch read at each stage's time with its cables, its addresses and its configurations, each `Ready` with its bytes the fixture's, then the fixture's with `n1`'s address, and a second seed that gives the same network at later times, its own marks in place of the first's, and leaves `main` as it was. Then the reader's, `readers/infrahub/tests/contract/`, with the reader's token, and a writer of its own with the admin's, which the reader is never given, writing only on a branch `fylgja-contract-<8 hex>` it makes from `main` and deletes after, the session's start deleting any that a stopped run left: Infrahub's version read; a branch Infrahub lacks refused with 404, its error naming the branch, and an `at` before the branch with 422 and a malformed one with 400, each naming the branch and the time; a wrong token refused with 401 at the connect, naming `FYLGJA_INFRAHUB_TOKEN`; none of them holding the token; the seeded `main`'s devices and ports read as rows at the first stage's time, every list whole; 120 ports of one device read in two pages; the seeded `main`'s schema held to the schema check's table, nothing differing; and the fixture read into blueprints, `main` and the seeded branch at the first stage's time, the branch's blueprint id the probed fixture's (`three-node-probed.json`), the seed's probe among it, each stage's configurations their artifacts' bytes, a past time read as it stood after a later one, and a scope no device carries empty; and the stale rule and `head`: each stage of the seeded branch read with no stale configuration, and read twice to one id; an address of `n1`'s edited on a branch of the writer's, refusing `n1` alone as stale at `head` until a regeneration the writer asks, and then a port of `n1`'s renamed, refusing `n1` and `n2`, at the cable's far end, and not `n3`; and the seeded branch read at `head` giving its last stage's blueprint id; and the probes: the seed's `n1-loop` alone in each stage's blueprint, and a probe of the tier's own, made through its branch and its gateway changed, read through that branch a microsecond after each write as it stood then, under one id, counted by `head`, and omitted from the read, its devices in no scope. The kind being branch-agnostic, that probe is on every branch while the test runs, and deleted at its end; the session's start deletes any `fc-*` probe a stopped run left. Then each refusal. Provoked by the writer on a branch of its own and read at its `head`: a device made in the scope with no artifact, `artifact.missing` for it alone; an artifact's status written `Pending`, `artifact.unready`, and its checksum written as zeros, `artifact.checksum.mismatch`; a device's serial number, which the template does not render, written, `artifact.stale`, and the same read with a `generated_since` of that `head` giving the configuration as it was; and a cable added and regenerated, then its ends taken off it, `artifact.stale` for its two devices by the cable's event alone. Made in flight, by a transport of the test's own that alters a real answer, where the writer may not write it or Infrahub never answers it: a branch of the writer's whose schema is answered without `DcimCable.label`, which a load may not remove, `schema.field.missing` from `check_schema` and `read`, `main` conforming; and `main` read at its `head` with each answer of the ports cut by an edge, `read.incomplete`. And `main` read at its `head` with a reader document naming no device's platform, `platform.unmatched` for each. Then the command, `fylgja-infrahub`, run as a process of its own with the reader's variables alone: `read` of the first stage writing the library's blueprint, `schema-check` of `main`, `head`, and a scope no device carries exiting 1. Last, every request the reader's connections sent held to reads: a `GET`, or a `POST` to `/graphql/` of a `query`. The reader's: 30 tests, in 757 s run alone, measured once since a branch's events take in `main`'s up to its branch point; 396 s and 402 s in two runs before; 895 s within the whole tier, measured once, on 2026-11-11, and 1782.90 s on 2026-11-12. Then the example orchestrator's, `orchestrator/tests/contract/`, with the example's account's token, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`, for the change source and the runner, and the admin's for its own writes. Each module makes a proposed change of the seed's branch, finding none open at its start and leaving none at its end, and stops where anything listens on port 4200. The change source's: the head read at the proposed change's creation, waiting for its artifact validation and giving the reader its completion as `generated_since`; the change found by its branch with its draft flag, and `NoChange` for a name that is no branch; the stages the branch point at the cut, the seed's marks at their `as_of` and the head, and a mark written with no `as_of` last before the head at the time Infrahub gave its writing; a report posted as one thread of two comments by the account, a part of 4,092 bytes taken and one of 4,093 sending nothing; the account refused a tag; and every stage read to a blueprint, with no `stage.main.moved` after the module's writes, and the head twice to one id. The edge's: the core served on plan 4's fake runtime in the test's process, a Prefect server on a free loopback port and `fylgja-orchestrator serve`, each ended by its pid, and the checks' glue run in the test's process as a check runs it, never on a task worker: `fylgja-step` passing, its document a plan 1; `fylgja-twin` passing, its document a rehearsal 1 `passed`, and one more thread of two comments; a rehearsal held at its apply and cancelled at the check's own deadline (`timeout` 660, the deadline 420 s after the check begins), read `CANCELLED` within 45 s and its twin gone or its deletion asked within 30 s more; a draft starting no run; and no secret in any message or in the server's and the runner's output. The orchestrator's: 11 tests, in 722 s within the whole tier on 2026-11-11 and 1469.00 s on 2026-11-12, each measured once. Without its variables a test is skipped, and fails when `CI` is set. `make test` deselects it (the `contract` marker) |
| **Contract (NetBox)** | The development NetBox, up and seeded (`make netbox-up`, `make netbox-seed`), reached at `FYLGJA_NETBOX_ADDRESS` with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`, and the two accounts' tokens, `FYLGJA_NETBOX_TOKEN` and `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`; for the example's, nothing listening on port 4200, the development Prefect down (`make prefect-down`), and, where it is set, the superuser's password, `FYLGJA_NETBOX_SUPERUSER_PASSWORD`, for its legs that sign in | On demand: `make contract-netbox`, with `local/.env` loaded after `make netbox-seed`. `netbox/tests/contract/`: the two accounts, `netbox/seed/account.py`: the reader's token reading the three devices tagged `fylgja`, their ports and cables, the platform with its manufacturer, the tag, the probes' context by its name and `main`'s changelog, and rendering `n1` to the superuser's bytes, on `main` and under a branch of the test's own, which it finds by its name; refused 403 a site's create, a journal entry and a `DELETE` of `n1`, each under the branch's header so that one wrongly taken lands on the branch alone, and a `PATCH` of the branch's tags, neither changelog moving; the example's token reading the same, writing a journal entry of kind `info` on the branch, read back in the branch's entries, and setting the tag `fylgja` on the branch and taking it off, and refused 403 a site's create and a `PATCH` and a `DELETE` of `n1` under the branch's header, and the branch's sync, `You do not have permission to perform this action.`; and the accounts made again over the two lines the environment gives, nothing made, the file's bytes unmoved and each account's count of tokens what it was; the seed's transport, `netbox/seed/box.py`: `/api/status/` naming NetBox's version and the branching plugin's; NetBox's object types listed in pages of 50, as many rows as the `count` it answers, each id once; a branch of the test's own, `fylgja-contract-<8 hex>`, made and read until `ready`, its `schema_id` of eight characters, and a site made under its header found there and not on `main`; and a token of NetBox's v2 shape that NetBox never made, refused with 403 and `Invalid v2 token`, the error holding no part of it, the last of these reading that the tests run before it, the accounts' and the transport's, left no branch, which the pure tier's `netbox/tests/test_contract_branches.py` holds as a rule; and the seed, `netbox/seed/seed.py`, which seeds `main` first: `main` holding the fixture, three devices tagged `fylgja`, fifteen ports with `mgmt_only` on each `mgmt0` alone, six addresses and the two cables, with no difference; each device's configuration as NetBox renders it, `testdata/blueprint/three-node.json`'s line for line after the first but the far end of the link `main` lacks; on a branch of the test's own, the change's two steps, the cable between `n1` and `n3` moving their configurations to the blueprint's and the address `192.0.2.1/24` on `n1`'s end adding its two lines to `n1`'s, `n2`'s and `main`'s renders unmoved; the probes' context, inactive, by its name, in no device's `config_context`; and a second seed, finding everything and adding no row to `main`'s changelog. Each branch is deleted at its test's end whatever the test did, and the session's start deletes any that a stopped run left, so that `main` stays as the seed left it. 14 tests, in 151.6 s, 152.8 s and 149.5 s in three runs on 2026-11-12. `readers/netbox/tests/contract/`, the NetBox reader's, run after it: its transport with the reader's token, `FYLGJA_NETBOX_TOKEN`, never the write token, verified against `FYLGJA_NETBOX_CA` where the address is `https://`: NetBox's version and the branching plugin's, the warning given exactly where the pair is not one the reader was verified on; a token of NetBox's v2 shape that NetBox never made refused at the connect with 403, the error naming `FYLGJA_NETBOX_TOKEN` and holding no part of the token; the fixture's tag, its three devices, their platform `SR Linux` of `Nokia`, their fifteen ports with `mgmt_only` on each `mgmt0` alone and their two cables, each of one interface end a side, every list whole; a branch of the test's own found by its name, `ready`, and a port disabled under its header read so there and enabled on `main`; and 120 interfaces made on that branch read whole in two pages. Then the read of `main` and of a branch into the fixture's devices, links and configurations; the bracket, as an edit, a journal entry, a render, a sync, a merge and a branch deleted move the changelogs and the branch; the probes' context; each rule of `readers/netbox/rules.md` provoked on purpose, on a branch of the test's own, or in flight, an answer altered on its way to the reader, where NetBox cannot be written into ([readers/netbox/README.md](readers/netbox/README.md#supported-netbox-versions)), an edit, a journal entry, the branch's delete and its sync made as a read's first render passes among them, the entry refusing nothing and each of the others the read; the same state read twice to one id, on `main` and on a branch; the command `fylgja-netbox` run as a process with the reader's variables and not the write token; and, last of the session, every request each of the reader's connections sent, `GET`s and renders alone. Its writes are `netbox/seed/box.py`'s `Box`'s with the superuser's token, under the header of the test's own branch, but for three tests whose tag of the tier's naming reaches `main`, made there in two and merged there in the third, and two that write a journal entry on the test's branch object, which `main` holds, each deleted in a `finally`. 45 tests, in 587.75 s on 2026-11-12, after `netbox/`'s 14. `orchestrator/tests/contract_netbox/`, the example's NetBox change source's, run last: the source with the example's token, `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, over a core of the module's own on the fake runtime, a branch found by its name and one not yet `ready` or merged refused by its status; the seeded change's two steps, `netbox/seed/change.py`'s, written on a branch of the test's own and each marked, its entry the example's, every stage read to one state, one id, through the reader and the core; the example's `stage mark` taking a mark the source reads back and refusing its label again; a mark read under another scope, through another core or written malformed by hand refused by its name; `main` edited after the branch was made said at the first stage by a count held to the changelog's rows judged in the test, the marks, a claim and a webhook and an event rule counting for nothing; the tag taken off and the others left; a report of each status one journal entry of its kind, read back with an empty line before each list and, signed in as the superuser where `FYLGJA_NETBOX_SUPERUSER_PASSWORD` is set, each list item rendered as one; the example refused a site and the delete of its own entry; the reader's token and the example's each reading the installed webhook's rows of `main`'s changelog as the superuser does, the last holding its `additional_headers` as the webhook holds them; and, with a Prefect server of the module's own on the Docker bridge's gateway, a runner of the source `netbox` and `netbox/seed/hook.py` run against them, the tag set on a marked branch starting one run of `twin-rehearse/main` whose report, `passed`, arrives on the branch, the flow's own untagging starting none, and a setting at a receiver that refuses starting nothing and the next setting a run; no credential in any output or entry. The installed webhook, which the hook rewrites, is written back as it was at the module's end, and a failed sending of a webhook the session made, by the task's own time, is deleted where the superuser's password is set. A run killed before the module's end leaves the installed webhook naming the module's own Prefect, and where pytest is killed outright, that Prefect and the runner, found by `pgrep -x prefect` and `pgrep -x fylgja-orchestr` with a `PREFECT_HOME` under pytest's temporary directory: the next run refuses to start, and `make netbox-hook`, with the development Prefect up, puts the trigger right. 12 tests, in 357.19 s on 2026-11-13, after the reader's; 11, before the test of the webhook's rows of the changelog, in 351.67 s; 10, before the test of `stage mark`, in 339.18 s and 335.37 s. Without its variables a test is skipped, and fails when `CI` is set. `make test` deselects it (the `contract_netbox` marker) |

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
| `netbox/seed/` | The fixture network `make netbox-seed` puts on the development NetBox's `main`, as one file, `main.yaml`: `testdata/blueprint/three-node.json`'s devices, ports, addresses and cables less the link between `n1` and `n3`, and `three-node-probed.json`'s probe `n1-loop` as the data of the configuration context `fylgja-probes`; `template.j2`, the configuration template NetBox renders each device with, whose text is `three-node.json`'s for the device but its first line; and `reader.yaml`, the reader document that maps the fixture's manufacturer and platform to the package `nokia_srlinux` and names the probes' context |

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

**The NetBox reader's command**, `fylgja-netbox`, which `make venv` installs as
`core/.venv/bin/fylgja-netbox`, reads `FYLGJA_NETBOX_ADDRESS`, `FYLGJA_NETBOX_TOKEN` and, where
it is set, `FYLGJA_NETBOX_CA`, never a flag, and prints no token
([readers/netbox/README.md](readers/netbox/README.md#the-command)). Against the development
NetBox, seeded, with `local/.env` loaded after `make netbox-seed`, which writes the reader's
token, `main` is read into a file under `local/` where no `--branch` is given:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-netbox check
core/.venv/bin/fylgja-netbox read --scope tag:fylgja --reader netbox/seed/reader.yaml \
  --out local/main.json
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

## The development NetBox

One NetBox at stated versions runs on the development host as the Compose project
`fylgja-core-netbox` ([D-096](design/decisions.md#d-096)), behind the make targets above: NetBox
`NETBOX_VERSION` on netbox-docker `NETBOX_DOCKER_VERSION`, with the branching plugin at
`NETBOX_BRANCHING_VERSION`. It is brought up and seeded in this order. `make netbox-up` needs none
of `local/.env`'s names in the shell, and writes the names the others read into it, and
`make netbox-seed` writes the two accounts' tokens into it, so the file is loaded after each:

```sh
make netbox-up            # the project started, its secrets and the superuser's token in local/.env
set -a; . local/.env; set +a
make netbox-seed          # the fixture network on main, and the two accounts with their tokens' lines
set -a; . local/.env; set +a
make contract-netbox      # the NetBox contract tier against it
```

- The seed and the contract tier write with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`.
  The reader and the example each run under an account of their own, no superuser, granted the
  least read on the running instance for what each does (`GRANTS` in `netbox/seed/account.py`).
  `fylgja-reader`'s token, `FYLGJA_NETBOX_TOKEN`, has `view` of what a read lists and a render's
  `render_config` on devices: it reads and renders, on `main` and under a branch, and writes
  nothing. `fylgja-orchestrator`'s, `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, has the same, `add` on
  journal entries, any object's, and `change` on branches, any member of a branch: the writes the
  example makes with them are a journal entry on a branch and that branch's tags.
- `make netbox-down` stops it, keeping its containers, network and volumes and everything under
  `local/netbox/`, so that `make netbox-up` starts it again holding what it held.
  `make netbox-down PURGE=1` removes the containers, the network and the volumes; `local/.env`,
  the fetched release and the image stay, and the next start is an empty NetBox, to seed again.
  The three tokens `local/.env` holds are then dead: the next `make netbox-up` provisions the
  superuser's again and replaces its line, and the next `make netbox-seed` makes the two accounts
  and their tokens again and replaces their lines, every other line kept.
- The project's network is a documentation range, 198.51.100.0/24, named in
  `netbox/dev/compose.override.yml`, so that it never meets the local driver's lab pool, from which
  each twin's lab takes its subnet. `make netbox-up` recreates a project network that stands
  with another subnet: it removes the project's containers and network, keeps the volumes, and
  starts it again, which makes the network with the override's range, as read once on kept
  volumes, that `make netbox-up` exiting 0 in 138.8 s, its build fetching the base image's layers
  again (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"); the 73.7 s below
  is a start with no recreate. What Compose's `up` alone does to such a network was not read.
- A first start on new volumes is about twelve and a half minutes, most of it NetBox's migrations:
  748.9 s, 764.4 s and 749.6 s in three runs. On kept volumes it took 73.7 s. Idle, the stack
  held 1.36 GiB of the host's memory, read once (design/verified-facts.md, "NetBox 4.7.5 with
  netbox-branching 1.2.3").
- It is stopped (`make netbox-down`) for every live, cluster or conformance run, and up for the
  acceptance run through its tag, beside that run's twin
  ([D-099](design/decisions.md#d-099)).
- An upgrade is [D-096](design/decisions.md#d-096)'s procedure, by the three make variables
  `NETBOX_VERSION`, `NETBOX_DOCKER_VERSION` and `NETBOX_BRANCHING_VERSION`: start the new versions
  on new volumes, seed them, run the contract tier, read again the recorded facts the code leans
  on, and extend the list of the versions it passed on.

## Running the example orchestrator

The example orchestrator's edge ([D-085](design/decisions.md#d-085)) runs on the development host beside the
development Infrahub or the development NetBox: a Prefect server, the runner that serves it the two flows `stage-plan`
and `twin-rehearse`, and what starts them, Infrahub's task workers, where the example's checks start them, or NetBox's
worker, where its webhook starts `twin-rehearse` ([With NetBox](#with-netbox)). With Infrahub it is set up in this
order, the core running at `FYLGJA_API_ADDRESS` with the token file `FYLGJA_TOKENS` names:

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

### With NetBox

With NetBox ([D-097](design/decisions.md#d-097)) the edge needs nothing of Infrahub's. It is set up in this order, the
core running at `FYLGJA_API_ADDRESS` with the token file `FYLGJA_TOKENS` names:

```sh
make netbox-up                         # the development NetBox
set -a; . local/.env; set +a
make netbox-seed                       # main the fixture, and the reader's and the example's accounts and tokens
set -a; . local/.env; set +a
make orchestrator-env SOURCE=netbox    # the example's lines in local/.env, and nothing of Infrahub's run
# restart the core, so that it reads the runner's line in its token file
set -a; . local/.env; set +a
make prefect-up                        # the edge's Prefect on port 4200 of the Docker bridge's gateway
make orchestrator-serve SOURCE=netbox  # the runner, in a shell of its own with local/.env loaded, until Ctrl-C
make netbox-hook                       # the tag, the event rule and the webhook to twin-rehearse/main
make netbox-change                     # the branch third-link made from main, each of its steps marked
```

`make netbox-change NETBOX_TAG=1` sets the tag `fylgja-rehearse` on the branch last, which asks for its rehearsal, as
setting the tag in NetBox does; on the development core the rehearsal's twin is made on the core's driver. The report
is one journal entry on the branch, its kind the verdict
([docs/integrating.md](docs/integrating.md#the-example-with-netbox-end-to-end)).

Who holds which token there:

- **The runner** holds a token of the core's under the principal `orchestrator`
  (`FYLGJA_ORCHESTRATOR_API_TOKEN`) and the NetBox account `fylgja-orchestrator`'s
  (`FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`), given to it as `FYLGJA_API_TOKEN` and `FYLGJA_NETBOX_TOKEN`, and the basic
  auth as Prefect's `PREFECT_API_AUTH_STRING`. It is never given the superuser's token, the reader's account's or
  anything of Infrahub's.
- **The Prefect server** holds the basic auth alone, as `PREFECT_SERVER_API_AUTH_STRING`.
- **NetBox's webhook** holds the basic auth's header line in its `additional_headers`, written by `make netbox-hook`.
  Neither lesser account may read the webhook, but both may view NetBox's changelog, and the webhook's rows in
  `main`'s changelog hold its `additional_headers` unmasked, and its `secret`, of which the example sets none: both
  lesser tokens read the auth there ([docs/integrating.md](docs/integrating.md#credentials)), as the example's NetBox
  contract tier holds. The rows outlive the webhook, so a value once written stays readable until that changelog's
  own pruning, or a purge of the instance, removes its rows. Replacing the credential removes no row: the old value
  stays readable there, and only stops opening Prefect. As read for those two accounts' grants, which have no
  constraint, an account that may view NetBox's changelog can read a webhook's headers, so Prefect's credential is
  as widely readable as that changelog; a grant with constraints was not read. The example accepts this as a known
  limit: it is a demonstration, whose secrets sit together on a development host. Restricting who may view the
  changelog is by itself no remedy: the reader's account and the example's must keep that view, so both still read
  the header. A deployment that shares its NetBox puts a receiver of its own between NetBox and Prefect, so that
  Prefect's credential never enters NetBox, though whatever that receiver is sent, a header or a `secret`, the same
  rows hold; or it gives grants that hide the webhook's rows from the accounts that need the changelog, which was not
  read.
- **The seed, the trigger, the change's branch, steps and tag, and the tests' set-up** write as the superuser,
  `FYLGJA_NETBOX_WRITE_TOKEN`. The change's marks are the example's own command's, under the example's token.

Three more things hold:

- One Prefect serves one source's runner: both sources' flows are served under the same two names. A Prefect home
  keeps a deployment's id across its runners and its server's restarts, as read of each restarted, so a run, a check's
  or the tag's, goes to whichever runner serves the name; nothing refuses a runner of the other source serving it,
  which was not read, and a tag set while Prefect answers and no runner serves was not read either. Port 4200 is the
  edge's alone, as above.
- `make netbox-hook` names the deployment `twin-rehearse/main` by its id, which a runner or a server restarted under
  the same home keeps and a new home changes. So it is run once `make orchestrator-serve SOURCE=netbox` serves, and
  again after every new `local/prefect/`: a webhook naming an old id is answered 404 and starts nothing, which NetBox
  shows only as a failed background task.
- A command by hand needs the runner's own tokens, which only `scripts/edge_dev.py` reads from `local/.env`, and
  nothing of Prefect's. From the main checkout, with `local/.env` loaded:

  ```sh
  python3 -I scripts/edge_dev.py run --source netbox --local local --main . -- stage list --branch third-link
  ```

  and so `stage plan`, `twin rehearse` or `stage mark`, each with `--branch`.

What the demonstration meets:

- **A request is the tag.** One setting is one rehearsal: the flow takes the tag off before it rehearses, and its own
  untagging starts nothing. NetBox never sends a lost request again: where Prefect is down when the tag is set, the
  request is gone and the branch keeps its tag, and the tag is taken off and set again to ask again. With one worker,
  as the development NetBox runs, a setting made while a sending waits on an address that does not answer waits
  behind it, up to 60 s.
- **Where the tag cannot be taken off**, NetBox refusing or not answering, the rehearsal is not run, the tag stays and
  no report is filed: that run did start, and shows as failed in Prefect.
- **A mark's label is unique within its branch and never taken twice**, and NetBox reads no branch as it stood
  earlier, so a past step cannot be marked again. `make netbox-change` run again for a branch deletes that branch and
  builds it again, marked anew. A change is seeded and marked once for each core: a mark's blueprint is read from the
  core the rehearsal runs through, which holds it where it was given it ([D-100](design/decisions.md#d-100)). A mark
  read under another scope is rehearsed under its own (`mark.scope`), and one whose
  blueprint another core holds through that core (`mark.unheld`). Every other remedy is a deletion in NetBox by a
  person who may delete journal entries, which the example's account may not: of two marks of one label, all but one
  (`mark.duplicate`); of any other mark the rehearsal cannot use, that mark, and the step is marked again only while
  the branch still stands at it; otherwise the change is seeded again.
- **`stage.main.gained`**, a warning on the first stage, counts what `main` gained since the branch's last sync, or
  its creation, leaving out journal entries, the branch object's own rows and the trigger's own webhook and event
  rule.

## The acceptance run

An acceptance run is a phase's own gate: the maintainer watches a change rehearsed on a twin from where its change
source starts the rehearsal, and reads the report where that source files it, once with the core on the local driver
and once with the core deployed on the cluster. Each written here has every command in order, how each one's end is
read and the block that says the maintainer can be asked:

- [Through Infrahub's check](#through-infrahubs-check): a proposed change of the branch seeded in the development
  Infrahub, rehearsed through Infrahub's own check `fylgja-twin`, its report read in the proposed change's thread. It
  takes the branch under test, so that it can be made again before a landing.
- [Through NetBox's tag](#through-netboxs-tag): a branch built in the development NetBox in steps, each marked, then
  given its tag, rehearsed through NetBox's own webhook and Prefect, its report read on the branch's journal.

No two of them run at once: each is a live run of its own, one at a time on the host and on the cluster.

### Through Infrahub's check

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
  the head of the branch under test with `make venv` run there: `local/` is there alone, and the task
  workers mount that checkout's `.git` alone. The registration reads a branch of that `.git` by
  its name: `make infrahub-register` takes it as `REF`, by default the branch checked out, and
  the block below holds the registration to the commit `git rev-parse` answers for `ref`, which
  the caller sets to the branch under test and which is the branch checked out where it is not
  set. The runs of 2026-11-12 were made at `phase-8-integration`, the branch phase 8 was built
  on, before it landed on `main`, with that name written in the block where `ref` now stands; on
  2026-11-13 the block was run as it stands, given `ref=phase-9-integration`, and exited 0
  ([verified-facts.md](design/verified-facts.md), "Infrahub 1.11.11"). For a branch under test
  that is not the one checked out, give `REF=<the branch under test>` and set `ref` to it too:
  `REF` and `ref` name the branch the registration reads, and the core and the runner run the
  checkout's code. So the main checkout may be detached at the code under test, as it was on
  2026-11-13, where that commit and the branch `ref` names do not differ under `infrahub/` and
  in `.infrahub.yml`, which is what Infrahub fetches (`git diff --name-only <the branch> <the
  commit> -- infrahub .infrahub.yml` printing no name). The
  make targets resolve `local/` to the main
  checkout from a worktree too (the `Makefile`'s `MAIN` and `LOCAL`), but the core, the CLI, the
  reader and the block below name `local/` from the working directory.
- **Alone.** While it runs nothing else live runs on the host or the cluster: no `make live`,
  `make cluster` or conformance run, and no other twin. The stopped Compose project
  `fylgja-infrahub` and its volumes are never started, removed or altered. NetBox's runner is
  stopped, and the development NetBox is down (`make netbox-down`), or up with no branch given
  the tag `fylgja-rehearse` until the report: its webhook starts `twin-rehearse/main` by an id the
  runner of the source `infrahub` serves too. The run of 2026-11-13 was made with NetBox up, its
  runner stopped and its trigger installed, and no branch tagged.
- **By pid.** A process is stopped by its pid, never by its name: another core may run on the
  host, on the default port among them, and a pattern of `pkill -f` ends the shell that sends it.
- **Credentials.** `set -a; . local/.env; set +a` in the same command as what needs it. No token
  or password is put on a command line, printed or written.
- **Output.** Each run's output, the block's among it, goes under the main checkout's
  `local/phase-<n>/acceptance/<run>/`, `<n>` the phase the run is made for.

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
3. `make infrahub-register`, given `REF=<the branch under test>` where that is not the branch
   checked out, after every `make infrahub-up` that recreates
   a task worker. Its end: exit 0, with `register: fylgja reads <the branch under test> at <commit>,
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
lines this part's **On the cluster** gives, which set Reach's three once `local/.env` is loaded.
Before it, in that command too, the caller sets `out=local/phase-<n>/acceptance/<run>`, the run's
directory, which the block makes where it is absent and writes R4's blueprints into; it refuses to
start without it. Where the branch under test is not the one checked out in the main checkout, the
caller sets `ref` to it there too; the block takes the branch checked out where `ref` is not set,
and refuses a detached head. It prints a line a check and exits non-zero at the first that fails,
saying why. It is run as it stands here, with the main checkout as its working directory,
whichever checkout this file was read from, and reads JSON with the main checkout's
`core/.venv/bin/python` alone. Inside it the runner's own tokens stand in for `local/.env`'s, by
assignment: `FYLGJA_INFRAHUB_TOKEN` from `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN` and `FYLGJA_API_TOKEN`
from `FYLGJA_ORCHESTRATOR_API_TOKEN`, so that it reads Infrahub and the core as the runner will.
Every request reads its token from the environment inside the process that sends it, and none is
printed.

- **R1.** The registration `fylgja` reads `in-sync` and `online` at the commit `git rev-parse`
  answers for `ref`, and each running container of the Compose service `task-worker`
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
  cluster as this part's **On the cluster** says.

```bash
(
  set -e
  refuse() { echo "R$1 refused: $2" >&2; exit 1; }
  [ -f local/.env ] || refuse 0 "run in the main checkout, which holds local/"
  case ${out:-} in
    local/phase-*/acceptance/?*) mkdir -p "$out" || refuse 0 "$out was not made" ;;
    *) refuse 0 "set out=local/phase-<n>/acceptance/<run> first" ;;
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

  ref=${ref:-$(git branch --show-current)}
  [ -n "$ref" ] || refuse 1 "the main checkout's head is detached: set ref=<the branch under test>"
  commit=$(git rev-parse --verify --quiet "$ref^{commit}") \
    || refuse 1 "the main checkout holds no branch $ref"
  repo=$(gql main '{ CoreReadOnlyRepository(name__value: "fylgja") { edges { node {
    id ref { value } commit { value } sync_status { value } operational_status { value } } } } }' '{}') \
    || refuse 1 "the registration fylgja was not read"
  fields=$(pyj 'n = [e["node"] for e in d["CoreReadOnlyRepository"]["edges"]]
print(*(n and (n[0]["id"], n[0]["ref"]["value"], n[0]["commit"]["value"], n[0]["sync_status"]["value"],
               n[0]["operational_status"]["value"])))' <<< "$repo") \
    || refuse 1 "the registration's answer was not read"
  read -r id registered at sync online <<< "$fields"
  [ "$at" = "$commit" ] && [ "$sync" = in-sync ] && [ "$online" = online ] \
    || refuse 1 "fylgja reads ${registered:-nothing} at ${at:-no commit}, $sync, $online, not $commit in-sync and \
online"
  workers=$(docker ps --filter label=com.docker.compose.project=fylgja-core-infrahub \
    --filter label=com.docker.compose.service=task-worker --format '{{.Names}}') || refuse 1 "docker ps failed"
  n=0
  for w in $workers; do
    docker exec "$w" test -d "/opt/infrahub/git/$id/commits/$commit" \
      || refuse 1 "$w holds no tree of $commit: run make infrahub-register REF=$ref again"
    n=$((n + 1))
  done
  [ "$n" -gt 0 ] || refuse 1 "no task worker runs: make infrahub-up"
  echo "R1 ok: fylgja reads $registered at $commit, in-sync and online, and each of the $n task workers holds its tree"

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
  [ "$open" = 0 ] || refuse 3 "$open open proposed change(s) of $branch: Clean up through Infrahub's check removes it"
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
is unasked: both checks' validators, `Check: fylgja-step` and `Check: fylgja-twin`, made 44.3 s
after the creation on 2026-11-12 and 131.4 s and 131.7 s after it on 2026-11-13, on Infrahub's
volumes kept since then (the user check concluded 27 to 55 s after a creation, with a trivial
check; [verified-facts.md](design/verified-facts.md), "Infrahub 1.11.11"); `fylgja-twin` concluding when
the rehearsal ends; and the report as a thread, labelled `Fylgja rehearsal`, of two comments, the
summary and then the detail. A proposed change made as a draft, or anything done to it beyond its
creation, is not the run: the seed is made again, and the maintainer asked again.

**Read the run**, read-only, once `fylgja-twin` has concluded, into the run's directory,
`local/phase-<n>/acceptance/<run>/`. Infrahub is read with the writer's or the runner's token and
Prefect with `FYLGJA_ORCHESTRATOR_AUTH`, each from the environment inside the process that sends
the request:

- the proposed change's creation time as Infrahub answers it, its edge's `node_metadata {
  created_at }`, never a clock of the reader's;
- by `proposed_change__ids`, the `CoreArtifactValidator` and the two `CoreUserValidator`s, each
  with its `state`, `conclusion`, `started_at` and `completed_at`: from them, when the artifact
  validator appeared after the creation, and whether each check ran for more than 20 s. The
  `fylgja-twin` validator is expected within 120 s of the creation: on 2026-11-12 it was made
  44.3 s on, and on 2026-11-13 131.7 s on, a run that counts, both checks concluding `success`.
  Where 120 s pass with none, the run is waited for and read, never started again: it is not the
  run only where no `fylgja-twin` check is ever started, which the validators and the task
  workers' logs show;
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
  `out=local/phase-<n>/acceptance/<run>`, `ref` where it is set, and `kubectl() { <kubectl> "$@"; }`
  in place of the target.
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

### Through NetBox's tag

Phase 9 is done when the maintainer has watched this: a script builds a branch in NetBox in steps and marks each; the
branch is given its tag, by the script's last act or by hand in NetBox; that starts the rehearsal with nothing else done
by hand; and the maintainer reads the rehearsal's report on the branch's journal in NetBox; once with the core on the
local driver and once with the core deployed on the cluster
([core.md](design/core.md#phase-9-the-netbox-reader-and-the-examples-netbox-change-source-settled-2026-11-12)). This
is that run: every command in order, how each one's end is read, the block that says the change can be built and the
tag set, and what is read where no report comes. It follows [The development NetBox](#the-development-netbox) and
[With NetBox](#with-netbox), which say what each target does and who holds which token.

- **Where.** Every command here runs with the main checkout as its working directory, at the head of the branch under
  test with `make venv` run there: `local/` is there alone, and the core and the runner run that checkout's code. The
  make targets resolve `local/` to the main checkout from a worktree too, but the core, the CLI,
  `scripts/edge_dev.py run` and the block below name `local/` from the working directory. The targets run the
  working directory's `scripts/edge_dev.py`, which starts Prefect and the runner from its own checkout's
  `core/.venv`, whatever `--main` names, and N2 accepts only the working directory's runner: so the run is made from
  the main checkout, checked out at the code under test. A branch a worktree holds checked out is checked out in the
  main checkout at its commit, detached (`git checkout --detach <commit>`), with `make venv` run again; once the run
  is over, the main checkout is checked out again on the branch it was on (`git checkout <that branch>`).
- **Alone.** One NetBox, and one live run at a time: while it runs nothing else live runs on the host or the cluster,
  no `make live`, `make cluster`, conformance run or contract tier, and no other twin on either core. The development
  Infrahub is stopped (`make infrahub-down`): its task workers start the deployments `stage-plan/main` and
  `twin-rehearse/main` by name, which the runner of the source `netbox` serves here. NetBox and a twin on the local
  driver are up together here.
- **By pid.** A process is stopped by its pid, never by its name, as in the run through Infrahub's check.
- **Credentials.** `set -a; . local/.env; set +a` in the same command as what needs it. No token or password is put on
  a command line, printed or written. A command of the example's by hand runs through
  `scripts/edge_dev.py run --source netbox`, as [With NetBox](#with-netbox) has it: only it reads the runner's own
  tokens from `local/.env` and hands them on, and nothing here makes the runner's environment by hand.
- **Output.** Each run's output, the block's among it, goes under the main checkout's
  `local/phase-<n>/acceptance/<run>/`, `<n>` the phase the run is made for.
- **A branch for each core.** A mark's label is unique within its branch, and a mark's blueprint is read from the
  core the rehearsal runs through, which holds it where it was given it ([D-097](design/decisions.md#d-097),
  [D-100](design/decisions.md#d-100)), so the change is seeded and marked once for each core,
  on a branch of its own: `third-link-local` through the core on the local driver, and `third-link-cluster` through
  the deployed core. Neither core is restarted on another store, nor the deployed one's store emptied, between a
  branch's seed and its report; where either happened, the branch is seeded again. `make netbox-change` deletes a
  branch of its name and builds it anew, so a run's branch, its marks and its report are replaced by the next seed of
  that name. No branch is merged, since a merge moves `main` under the fixture, and none is deleted by hand but one
  `make netbox-change` refuses by its status, as its refusal says.

**Bring it up**, in this order, `local/.env` loaded for each step but the first:

1. `make netbox-up`. It needs none of `local/.env`'s names in the shell: it adds to the file those of its own it
   lacks, and Compose reads them there. Its end: exit 0, once `/api/status/` names both versions and a running worker,
   said as `netbox_dev: NetBox 4.7.5 with netbox_branching 1.2.3 answers at http://127.0.0.1:8800, <n> worker(s)
   running`; without a running worker it fails, since then no branch is ever ready. It writes the superuser's token,
   `FYLGJA_NETBOX_WRITE_TOKEN`, where the file holds none or NetBox refuses it. 73.7 s on kept volumes, about twelve
   and a half minutes on new ones. On an instance already up it built the image again from its cache and recreated
   `netbox` and `netbox-worker`, the volumes kept, in 83.2 s, read once.
2. `make netbox-seed`. Its end: exit 0, with a line an object of the fixture, `made` or `found` and its path, then a
   line for each account, grant or token it made, set or replaced, or `account: every account, grant and token line
   is as it should be; nothing written`. Where `main` is not the fixture it says each difference and exits 1, deleting
   nothing. It reads `FYLGJA_NETBOX_ADDRESS` and the superuser's `FYLGJA_NETBOX_WRITE_TOKEN`, and writes the two
   accounts' token lines, `FYLGJA_NETBOX_TOKEN` and `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, where either is missing or
   NetBox does not hold its token as that account's, so `local/.env` is loaded again after it.
3. The core on the local driver, in a shell of its own, started as the run through Infrahub's check starts it, its
   store, `local/store`, kept:

   ```sh
   set -a; . local/.env; set +a; FYLGJA_DRIVER=containerlab FYLGJA_STORE=local/store FYLGJA_PACKAGES=psp:probes core/.venv/bin/fylgja-core-server
   ```

   Its end: `FYLGJA_LISTEN`'s address listened on by that process's pid (`ss -Hltnp`), and `GET /v1/version` answering
   there. It reads `FYLGJA_LISTEN`, `FYLGJA_TOKENS` and the SR Linux login from `local/.env`. `FYLGJA_API_ADDRESS`,
   where the CLI, the marks and the runner reach it, is `local/.env`'s, equal to `FYLGJA_LISTEN`, and is never set by
   hand here.
4. `make orchestrator-env SOURCE=netbox`, which runs nothing of Infrahub's and needs no Infrahub. Its end: exit 0,
   printing names alone, `edge_dev: …/local/.env holds every name already; nothing written` or `edge_dev: …: added
   <names>`. Where it added `FYLGJA_ORCHESTRATOR_API_TOKEN`, it lists that token's hash under the principal
   `orchestrator` in the token file `FYLGJA_TOKENS` names and says `restart the core so that it reads … again`: the
   core is then stopped by its pid and started again by step 3, and `local/.env` loaded again.
5. `make prefect-up`. Its end: exit 0, with `edge_dev: the development Prefect answers at <the bridge's
   gateway>:4200, pid <pid>, …`, or `… is up already, pid <pid>`. It reads `FYLGJA_ORCHESTRATOR_AUTH`. Where anything
   else listens on port 4200 it refuses, starting and stopping nothing.
6. `make orchestrator-serve SOURCE=netbox`, in a shell of its own, `local/.env` loaded in the same command. Its end:
   `fylgja-orchestrator: serving stage-plan/main, twin-rehearse/main at http://<the bridge's gateway>:4200/api`, and
   both deployments `READY` some seconds on. It reads the runner's own tokens, `FYLGJA_ORCHESTRATOR_API_TOKEN` and
   `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`, which it hands the runner as `FYLGJA_API_TOKEN` and `FYLGJA_NETBOX_TOKEN`;
   `FYLGJA_ORCHESTRATOR_NETBOX_READER` and `_NETBOX_SCOPE`, handed on as `FYLGJA_ORCHESTRATOR_READER` and `_SCOPE`;
   `FYLGJA_ORCHESTRATOR_ROOT` and `FYLGJA_ORCHESTRATOR_AUTH`; and `FYLGJA_API_ADDRESS` and `FYLGJA_NETBOX_ADDRESS`, as
   loaded. A name it needs not set is one line naming it and the target that writes it, exit 2.
7. `make netbox-hook`, once the runner serves, since the webhook names the deployment `twin-rehearse/main` by the id
   Prefect answers for it; and again whenever N3 says the webhook names another id or carries another header. It reads
   `FYLGJA_NETBOX_ADDRESS`, the superuser's `FYLGJA_NETBOX_WRITE_TOKEN` and `FYLGJA_ORCHESTRATOR_AUTH`. Its end: exit
   0, with a line for each part of the trigger it made or wrote again, or `hook: the tag, the webhook and the event rule
   fylgja-rehearse stand; nothing made or changed`, and then `hook: the webhook fylgja-rehearse starts
   twin-rehearse/main, deployment <id>, at host.docker.internal:4200; …`. The trigger stays installed from one run to
   the next, and the deployment keeps its id while `local/prefect/` stands, the server and the runner each stopped and
   started again under it, so the block's N3 may pass before this step, and reads the trigger as it stands whoever
   wrote it. Before step 5 the block refuses at N2, which finds no runner, and so never reaches N3. The
   webhook's header carries Prefect's basic auth, and `main`'s changelog shows it unmasked to any account that may view
   that changelog, the reader's and the example's among them: the example accepts this as a known limit
   ([With NetBox](#with-netbox)).

After `make netbox-down PURGE=1`, which cannot be undone and is the maintainer's word alone, never a step of a run, the
three NetBox tokens `local/.env` holds are dead. The bring-up is then: `make netbox-up`, about twelve and a half minutes
on new volumes; `local/.env` loaded again, for the superuser's new token; `make netbox-seed`, which makes the two
accounts and their tokens again and replaces their lines; `local/.env` loaded again; `make netbox-hook`, with Prefect
up, since the new instance holds no trigger; and the runner stopped by its pid and started again by step 6, since it
holds the example's token of the purged instance, which the new one refuses.

**Ready for the change** is one block, run in a subshell under `set -e` as the run through Infrahub's check runs its
own: locally after `set -a; . local/.env; set +a` in the same command, and on the cluster after the lines this part's
**On the cluster** gives. Before it, in that command too, the caller sets `out=local/phase-<n>/acceptance/<run>`, the
run's directory, which the block makes where it is absent and writes N6's plan into; it refuses to start without it.
For **Ready for the tag** the caller sets `branch` too, the branch `make netbox-change` built; with `branch` unset the
block ends after N4, saying so. It prints a line for each check that passes, and exits non-zero at the first that
fails with a refusal that says why and what is done, on one line or two. It is
run as it stands here, with the main checkout as its working directory, whichever checkout this file was read from, and
reads JSON with the main checkout's `core/.venv/bin/python` alone. It reads NetBox with the superuser's token and writes
nothing there; Prefect with `FYLGJA_ORCHESTRATOR_AUTH`; and the core with the caller's own `FYLGJA_API_TOKEN`, but for
one request with the runner's. The example's own commands in it run through `scripts/edge_dev.py run --source netbox`,
so that they read NetBox and the core as the runner will. Every request reads its token from the environment inside
the process that sends it, and none is printed.

- **N0.** The working directory holds `local/.env`; `out` is under `local/phase-<n>/acceptance/`; each name the block
  reads is set; and `core/.venv/bin/fylgja-netbox --help` and the example's `stage mark --help`, through
  `scripts/edge_dev.py run --source netbox`, each exit 0. The second refuses, naming the name, where one the runner
  needs under `netbox` is not set.
- **N1.** NetBox: `/api/status/` names `netbox-version` 4.7.5, `netbox_branching` 1.2.3 among its `plugins`, and
  `rq-workers-running` of 1 or more; a container of the Compose service `netbox-worker` runs in the project
  `fylgja-core-netbox`; and `main` holds three devices tagged `fylgja` and, between the fixture's devices `n1`, `n2`
  and `n3`, the fixture's two cables, so that the third link is the change's. A cable on `main` of other devices
  alone is not counted, as `make netbox-seed` does not count it.
- **N2.** Prefect and the runner: the process `local/prefect/server.pid` names is this project's Prefect server;
  exactly one process on the host runs the main checkout's own `core/.venv/bin/fylgja-orchestrator` and `serve` with
  the main checkout's `local/prefect/` as its `PREFECT_HOME`, its `FYLGJA_ORCHESTRATOR_SOURCE` `netbox` and its
  `FYLGJA_API_ADDRESS` the block's; `twin-rehearse/main` answers 200 by name, `status` `READY`; and
  `POST /api/flow_runs/filter` answers no flow run of that server in a state not ended, `SCHEDULED`, `PENDING`,
  `RUNNING`, `PAUSED` or `CANCELLING`. The runner is read by its process because a stopped runner leaves the deployments
  answering `READY` by name, and a runner of the source `infrahub` serves them under the same names.
- **N3.** The trigger as it stands, read with the superuser's token: the tag `fylgja-rehearse`, limited to branches;
  the event rule `fylgja-rehearse`, enabled, on `netbox_branching.branch` for `object_updated`, its conditions the
  tag's slug as `netbox/seed/hook.py`'s `CONDITIONS` writes them, its action the webhook; the webhook
  `fylgja-rehearse`, its `payload_url` `http://host.docker.internal:4200/api/deployments/<id>/create_flow_run` with
  `<id>` the one Prefect answers now for `twin-rehearse/main`, and its `additional_headers` the line `Authorization:
  Basic ` and the base64 of `FYLGJA_ORCHESTRATOR_AUTH`, said as equal or not and never shown; and `GET` of that
  deployment by its id from inside each running `netbox-worker` container, by the worker's own Python with the basic
  auth handed to it by name, answering 200. It passes on a trigger that stood before `make netbox-hook` ran, and is
  written to refuse one naming another id or carrying another header, whoever wrote it; no run has yet seen N3
  refuse.
- **N4.** The core, as R6 of the run through Infrahub's check reads it. Locally: `FYLGJA_API_ADDRESS` equal to
  `FYLGJA_LISTEN`, the port's listener the pid the main checkout's own `core/.venv/bin/fylgja-core-server` runs as,
  that pid printed, and the image `ghcr.io/nokia/srlinux:24.7.1` on the host. Then `GET /v1/twins` once with the
  runner's token, `FYLGJA_ORCHESTRATOR_API_TOKEN`, which a token file lacking its hash refuses; `fylgja-core capacity
  show --json` answering the driver, and room for the fixture's three SR Linux nodes: over its hosts, free less pending
  of at least 1.5 CPU and 6144 MiB, and a roomiest host with 0.5 CPU and 2048 MiB
  ([D-073](design/decisions.md#d-073)), with `twins` 0; and `fylgja-core twin list` empty. On the cluster as this
  part's **On the cluster** says.

```bash
(
  set -e
  refuse() { echo "N$1 refused: $2" >&2; exit 1; }
  [ -f local/.env ] || refuse 0 "run in the main checkout, which holds local/"
  case ${out:-} in
    local/phase-*/acceptance/?*) mkdir -p "$out" || refuse 0 "$out was not made" ;;
    *) refuse 0 "set out=local/phase-<n>/acceptance/<run> first" ;;
  esac
  for name in FYLGJA_NETBOX_ADDRESS FYLGJA_NETBOX_WRITE_TOKEN FYLGJA_API_ADDRESS FYLGJA_API_TOKEN FYLGJA_LISTEN \
              FYLGJA_ORCHESTRATOR_AUTH FYLGJA_ORCHESTRATOR_API_TOKEN; do
    [ -n "${!name}" ] || refuse 0 "$name is not set: load local/.env"
  done
  py=core/.venv/bin/python f=core/.venv/bin/fylgja-core
  edge() {  # edge <words>: the example's command, given the runner's environment by scripts/edge_dev.py
    python3 -I scripts/edge_dev.py run --source netbox --local local --main . -- "$@"
  }
  nb() {  # nb <path> [<name>=<value> ...]: what NetBox answers a GET of /api/<path> on main, as JSON
    "$py" -I -c '
import json, os, ssl, sys, httpx
token, ca = os.environ["FYLGJA_NETBOX_WRITE_TOKEN"], os.environ.get("FYLGJA_NETBOX_CA")
try:
    answer = httpx.get(os.environ["FYLGJA_NETBOX_ADDRESS"].rstrip("/") + "/api/" + sys.argv[1],
                       params=[pair.partition("=")[::2] for pair in sys.argv[2:]],
                       headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, timeout=30,
                       verify=ssl.create_default_context(cafile=ca) if ca else True, trust_env=False)
    body = answer.json()
except Exception as error:
    sys.exit("NetBox was not read: " + type(error).__name__)
if answer.status_code != 200:
    sys.exit(("NetBox answered HTTP %d: %s" % (answer.status_code, body)).replace(token, "<token>")[:400])
print(json.dumps(body))' "$@"
  }
  pf() {  # pf <host:port> <GET|POST> <path> [<body>]: what the development Prefect answers, as JSON
    "$py" -I -c '
import json, os, sys, httpx
user, _, password = os.environ["FYLGJA_ORCHESTRATOR_AUTH"].partition(":")
try:
    answer = httpx.request(sys.argv[2], "http://" + sys.argv[1] + "/api/" + sys.argv[3], auth=(user, password),
                           json=json.loads(sys.argv[4]) if len(sys.argv) > 4 else None, timeout=30, trust_env=False)
    body = answer.json()
except Exception as error:
    sys.exit("Prefect was not read: " + type(error).__name__)
if not 200 <= answer.status_code <= 299:
    sys.exit(("Prefect answered HTTP %d: %s" % (answer.status_code, body)).replace(password, "<auth>")[:400])
print(json.dumps(body))' "$@"
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

  core/.venv/bin/fylgja-netbox --help > /dev/null || refuse 0 "core/.venv/bin/fylgja-netbox --help exited $?: make venv"
  edge stage mark --help > /dev/null \
    || refuse 0 "the example's stage mark --help, through scripts/edge_dev.py, exited $?: it names what is missing"
  echo "N0 ok: $out, every name set, and fylgja-netbox and the example's stage mark answer"

  status=$(nb status/) || refuse 1 "NetBox's /api/status/ was not read: make netbox-up"
  said=$(pyj 'plugin, workers = (d.get("plugins") or {}).get("netbox_branching"), d.get("rq-workers-running")
print("NetBox %s with netbox_branching %s, %s worker(s) running" % (d.get("netbox-version"), plugin, workers))
sys.exit(not (d.get("netbox-version") == "4.7.5" and plugin == "1.2.3" and type(workers) is int and workers >= 1))' \
    <<< "$status") || refuse 1 "${said:-no status}, not 4.7.5 with netbox_branching 1.2.3 and a worker: make netbox-up"
  workers=$(docker ps --filter label=com.docker.compose.project=fylgja-core-netbox \
    --filter label=com.docker.compose.service=netbox-worker --format '{{.Names}}') || refuse 1 "docker ps failed"
  [ -n "$workers" ] || refuse 1 "no container of netbox-worker runs in fylgja-core-netbox: make netbox-up"
  devices=$(nb dcim/devices/ tag=fylgja limit=1) || refuse 1 "the devices of main were not read"
  cables=$(nb dcim/cables/ device=n1 device=n2 device=n3 limit=1) || refuse 1 "the cables of main were not read"
  n=$(pyj 'print(d["count"])' <<< "$devices") || refuse 1 "the devices of main were not counted"
  m=$(pyj 'print(d["count"])' <<< "$cables") || refuse 1 "the cables of main were not counted"
  [ "$n" = 3 ] && [ "$m" = 2 ] \
    || refuse 1 "main holds $n devices tagged fylgja and $m cables of n1, n2 and n3, not 3 and 2: make netbox-seed"
  echo "N1 ok: $said, its worker running, and main the fixture's 3 devices and 2 cables"

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
    stop("%d runners of this checkout, %s serve, run, not one: make orchestrator-serve SOURCE=netbox"
         % (len(runners), runner))
pid, env = runners[0]
if env.get("FYLGJA_ORCHESTRATOR_SOURCE") != "netbox":
    stop("the runner, pid %s, serves the source %s, not netbox: stop it, make orchestrator-serve SOURCE=netbox"
         % (pid, env.get("FYLGJA_ORCHESTRATOR_SOURCE") or "infrahub"))
if env.get("FYLGJA_API_ADDRESS") != os.environ["FYLGJA_API_ADDRESS"]:
    stop("the runner, pid %s, drives a core FYLGJA_API_ADDRESS does not name: stop it, start it again" % pid)
try:
    server = Path(home, "server.pid").read_text().strip()
except OSError:
    stop("local/prefect/server.pid names no development Prefect: make prefect-up")
process = read(server)
if not process or not {"prefect", "server"} <= {Path(part).name for part in process[0]} \
        or process[2].get("PREFECT_HOME") != home:
    stop("pid %s of local/prefect/server.pid is no Prefect server with PREFECT_HOME local/prefect: make prefect-up"
         % server)
print(pid, server, env.get("PREFECT_API_URL", "").removeprefix("http://").removesuffix("/api"))') \
    || refuse 2 "$found"
  read -r runner prefect address <<< "$found"
  deployment=$(pf "$address" GET deployments/name/twin-rehearse/main) \
    || refuse 2 "twin-rehearse/main was not read from the development Prefect at $address: make prefect-up, then
the runner stopped by its pid and make orchestrator-serve SOURCE=netbox"
  fields=$(pyj 'print(d["id"], d.get("status"))' <<< "$deployment") || refuse 2 "twin-rehearse/main answered no id"
  read -r id state <<< "$fields"
  [ "$state" = READY ] || refuse 2 "twin-rehearse/main is $state, not READY: make orchestrator-serve SOURCE=netbox"
  open=$(pf "$address" POST flow_runs/filter \
    '{"flow_runs": {"state": {"type": {"any_": ["SCHEDULED", "PENDING", "RUNNING", "PAUSED", "CANCELLING"]}}}}') \
    || refuse 2 "the flow runs of the development Prefect were not read"
  runs=$(pyj 'print(", ".join("%s %s" % (r["id"], (r.get("state") or {}).get("type")) for r in d))' <<< "$open") \
    || refuse 2 "the flow runs of the development Prefect were not read"
  [ -z "$runs" ] || refuse 2 "flow runs not ended, $runs: When no report comes says what is done with each"
  echo "N2 ok: the runner of the source netbox, pid $runner, and the development Prefect, pid $prefect;" \
    "twin-rehearse/main READY, deployment $id, and no flow run not ended"

  verdict=$("$py" -I -c '
import base64, os, ssl, sys, httpx
token, ca = os.environ["FYLGJA_NETBOX_WRITE_TOKEN"], os.environ.get("FYLGJA_NETBOX_CA")
deployment = sys.argv[1]
def stop(said):
    print(said)
    sys.exit(1)
def one(path, **params):
    try:
        answer = httpx.get(os.environ["FYLGJA_NETBOX_ADDRESS"].rstrip("/") + "/api/" + path, params=params,
                           headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, timeout=30,
                           verify=ssl.create_default_context(cafile=ca) if ca else True, trust_env=False)
        rows = answer.json()["results"] if answer.status_code == 200 else None
    except Exception as error:
        stop("NetBox was not read: " + type(error).__name__)
    if rows is None:
        stop("GET /api/%s answered HTTP %d: load local/.env again for FYLGJA_NETBOX_WRITE_TOKEN, or make netbox-up"
             % (path, answer.status_code))
    if len(rows) != 1:
        stop("NetBox lists %d of /api/%s named fylgja-rehearse, not one: make netbox-hook" % (len(rows), path))
    return rows[0]
tag = one("extras/tags/", slug="fylgja-rehearse")
rule = one("extras/event-rules/", name="fylgja-rehearse")
hook = one("extras/webhooks/", name="fylgja-rehearse")
if tag.get("object_types") != ["netbox_branching.branch"]:
    stop("the tag fylgja-rehearse is not limited to branches: make netbox-hook")
conditions = {"and": [{"attr": "tags.slug", "value": "fylgja-rehearse", "op": "contains"}]}
if not (rule.get("enabled") is True and rule.get("object_types") == ["netbox_branching.branch"]
        and rule.get("event_types") == ["object_updated"] and rule.get("conditions") == conditions
        and rule.get("action_object_type") == "extras.webhook" and rule.get("action_object_id") == hook["id"]):
    stop("the event rule fylgja-rehearse does not send the webhook on the update of a tagged branch: make netbox-hook")
if hook.get("payload_url") != "http://host.docker.internal:4200/api/deployments/%s/create_flow_run" % deployment:
    stop("the webhook fylgja-rehearse names another deployment than %s, the one Prefect answers: make netbox-hook"
         % deployment)
line = "Authorization: Basic " + base64.b64encode(os.environ["FYLGJA_ORCHESTRATOR_AUTH"].encode()).decode()
if hook.get("additional_headers") != line:
    stop("the header of the webhook fylgja-rehearse is not that of FYLGJA_ORCHESTRATOR_AUTH: make netbox-hook")
print("the tag, the event rule and the webhook fylgja-rehearse, to deployment %s with the basic auth" % deployment)
' "$id") || refuse 3 "$verdict"
  for w in $workers; do
    seen=$(docker exec -e FYLGJA_ORCHESTRATOR_AUTH "$w" /opt/netbox/venv/bin/python -c '
import base64, os, sys, urllib.error, urllib.request
auth = base64.b64encode(os.environ["FYLGJA_ORCHESTRATOR_AUTH"].encode()).decode()
request = urllib.request.Request("http://host.docker.internal:4200/api/deployments/" + sys.argv[1],
                                 headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as answer:
        print(answer.status)
except urllib.error.HTTPError as error:
    print(error.code)
    sys.exit(1)
except Exception as error:
    print("not reached, " + type(error).__name__)
    sys.exit(1)' "$id") || refuse 3 "from $w, GET of the deployment $id answered ${seen:-nothing}: a 401 is a Prefect
started under another auth, make prefect-down and make prefect-up; else the worker reaches no Prefect at port 4200"
  done
  echo "N3 ok: $verdict; GET of it answered 200 from each running netbox-worker"

  listen=$(ss -Hltnp "sport = :${FYLGJA_LISTEN##*:}") || refuse 4 "ss did not read the listeners"
  if [ -n "${FYLGJA_API_CA:-}" ]; then
    [[ $FYLGJA_API_ADDRESS == https://* ]] || refuse 4 "FYLGJA_API_CA is set and FYLGJA_API_ADDRESS is not https://"
    [ -z "$listen" ] || refuse 4 "a listener holds FYLGJA_LISTEN's port: stop the local core by its pid"
    deployed=$(kubectl -n fylgja get deployment fylgja-core \
      -o jsonpath='{.spec.replicas} {.spec.template.spec.containers[0].image}') \
      || refuse 4 "no Deployment read: define kubectl as On the cluster says, with the site's access"
    read -r replicas image <<< "$deployed"
    [ "$replicas" = 1 ] || refuse 4 "the deployed core runs $replicas replicas, not one: its scale is the maintainer's
word, as Running the core on a cluster says"
    started=$(kubectl -n fylgja get pods -l app.kubernetes.io/name=fylgja-core \
      -o jsonpath='{.items[*].status.startTime}') || refuse 4 "the core's pod was not read: as for the Deployment"
    driver=clabernetes least=2
    core="the deployed core, fylgja-core:${image##*:}, one replica, its pod started $started"
  else
    [ "$FYLGJA_API_ADDRESS" = "$FYLGJA_LISTEN" ] || refuse 4 "FYLGJA_API_ADDRESS is not FYLGJA_LISTEN: a shell
that holds Reach's exports is the cluster's, with FYLGJA_API_CA set; locally, load local/.env in a new shell"
    [[ $listen =~ pid=([0-9]+) ]] || refuse 4 "nothing of this user's listens on FYLGJA_LISTEN: start the core"
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
      || refuse 4 "pid $pid listens on FYLGJA_LISTEN and is not this checkout's fylgja-core-server: stop it by its
pid, and start the core as step 3 says"
    docker image inspect ghcr.io/nokia/srlinux:24.7.1 > /dev/null \
      || refuse 4 "no SR Linux 24.7.1 image here: docker pull ghcr.io/nokia/srlinux:24.7.1, as Local environment says"
    driver=containerlab least=1 core="the local core, pid $pid"
  fi
  FYLGJA_API_TOKEN=$FYLGJA_ORCHESTRATOR_API_TOKEN "$f" twin list --json > /dev/null \
    || refuse 4 "$core did not take the runner's token, FYLGJA_ORCHESTRATOR_API_TOKEN: its token file lacks the hash,
or the core was not started again after make orchestrator-env added it, or the core did not answer"
  room=$("$f" capacity show --json) \
    || refuse 4 "the room of $core was not read: the core did not answer, or refused FYLGJA_API_TOKEN, whose hash
its token file must list"
  twins=$("$f" twin list --json) \
    || refuse 4 "the twins of $core were not read: the core did not answer, or refused FYLGJA_API_TOKEN"
  sums=$(pyj 'hosts, pending = d["hosts"], d["pending"]
cpu = sum(h["cpu"]["free"] for h in hosts) - pending["cpu"]
mb = sum(h["memory_mb"]["free"] for h in hosts) - pending["memory_mb"]
roomiest = max(hosts, key=lambda h: (h["memory_mb"]["free"], h["cpu"]["free"]), default=None)
print("driver %s, %d host%s, free less pending %g CPU and %d MiB, twins %d"
      % (d["driver"], len(hosts), "" if len(hosts) == 1 else "s", cpu, mb, d["twins"]))
sys.exit(not (d["driver"] == a[0] and len(hosts) >= int(a[1]) and d["twins"] == 0 and cpu >= 1.5 and mb >= 6144
              and roomiest and roomiest["cpu"]["free"] >= 0.5 and roomiest["memory_mb"]["free"] >= 2048))' \
    "$driver" "$least" <<< "$room") || refuse 4 "$core answers ${sums:-no capacity}, not $driver with the room:
another driver or too few hosts is another core than this run names, read as Where and On the cluster say; a twin
there is destroyed as Clean up says, or the host freed of what else holds its CPU and memory"
  held=$(pyj 'print(" ".join(t["name"] for t in d))' <<< "$twins") || refuse 4 "the twins of $core were not read"
  [ -z "$held" ] || refuse 4 "$core holds the twins $held: each is read and destroyed as Clean up says"
  echo "N4 ok: $core, taking the runner's token, $sums, and twin list empty"

  if [ -z "${branch:-}" ]; then
    echo "N5 and N6 not read: branch is not set; set it once make netbox-change has built a branch with no tag"
    exit 0
  fi
  marked() {  # marked <said>: N5, the branch ready, untagged and marked twice, in one line after <said>
    listed=$(nb plugins/branching/branches/ "name=$branch") || refuse 5 "the branches were not read"
    fields=$(pyj 'rows = [b for b in d["results"] if b["name"] == a[0]]
if len(rows) != 1:
    sys.exit("NetBox lists %d branches named %s" % (len(rows), a[0]))
print(rows[0]["id"], (rows[0].get("status") or {}).get("value"),
      ",".join(t["slug"] for t in rows[0].get("tags") or []) or "-")' "$branch" <<< "$listed") \
      || refuse 5 "NetBox holds no branch $branch: make netbox-change NETBOX_BRANCH=$branch"
    read -r bid status tags <<< "$fields"
    [ "$status" = ready ] || refuse 5 "$branch is $status, not ready: a branch new or provisioning is read again a
minute on; make netbox-change refuses any other, which is deleted in NetBox, or the change built under another name"
    [ "$tags" = - ] || refuse 5 "$branch carries the tags $tags: the block is not run between the tag and the report"
    entries=$(nb extras/journal-entries/ assigned_object_type=netbox_branching.branch "assigned_object_id=$bid" \
      ordering=created limit=100) || refuse 5 "the journal of $branch was not read"
    journal=$(pyj 'heads = [(e.get("comments") or "").partition("\n")[0] for e in d["results"]]
print(", then ".join(heads) or "no entry")
sys.exit(d["count"] != 2 or heads != ["Fylgja stage: third-link", "Fylgja stage: n1-address"])' <<< "$entries") \
      || refuse 5 "the journal of $branch holds ${journal:-nothing}, not the two marks alone: make netbox-change
NETBOX_BRANCH=$branch builds it again, marked anew"
    echo "$1: $branch, branch $bid, ready and untagged, its journal $journal"
  }
  marked "N5 ok"

  stages=$(edge stage list --branch "$branch" --json) || refuse 6 "stage list --branch $branch exited $?"
  labels=$(pyj 'labels = [s["label"] for s in d["stages"]]
print(", ".join(labels))
sys.exit(labels != ["main", "third-link", "n1-address", "head"])' <<< "$stages") \
    || refuse 6 "$branch lists the stages ${labels:-none}, not main, third-link, n1-address and head: make
netbox-change NETBOX_BRANCH=$branch builds it again, marked anew"
  edge stage plan --branch "$branch" --json > "$out/plan.json" 2> "$out/plan.log" \
    || refuse 6 "stage plan --branch $branch exited $?: $out/plan.log and $out/plan.json say why"
  planned=$(pyj 'print(d["status"] + ",", ", ".join("%s %s" % (s["label"], s["outcome"]) for s in d["stages"]))
sys.exit(not (d["status"] == "planned" and d["stages"] and all(s["outcome"] == "built" for s in d["stages"])))' \
    < "$out/plan.json") || refuse 6 "the plan of $branch reads ${planned:-nothing}, not every stage built"
  echo "N6 ok: $branch lists $labels, and its plan is $planned, into $out/plan.json"
  marked "N5 ok again"
)
```

**The change and its tag.** With the block passed through N4, in one command after `set -a; . local/.env; set +a`:

```sh
make netbox-change NETBOX_BRANCH=third-link-local NETBOX_TAG=1
```

It deletes the branch of that name where one stands, every journal entry on it with it, and makes it anew from `main`;
writes the cable between `n1` and `n3` under the branch's header and marks it `third-link`, then the address on `n1`'s
end and marks it `n1-address`, each mark the example's own `stage mark` through `scripts/edge_dev.py run --source
netbox`, its blueprint given to the core at `FYLGJA_API_ADDRESS`; and sets the tag `fylgja-rehearse` on the branch as
its last act, which asks for the rehearsal. It reads `FYLGJA_NETBOX_ADDRESS` and the superuser's
`FYLGJA_NETBOX_WRITE_TOKEN`, and its marks the runner's names as step 6 does. Its end: exit 0, with, where the branch
stood, `change: the branch third-link-local stands: deleting it, and every journal entry on it, its marks among them,
to build it anew from main` and `change: deleted the branch third-link-local`; then `change: made the branch
third-link-local`; for each step `change: wrote <label> on the branch third-link-local: …`, the mark's own line
`third-link-local <label>: blueprint <id>` and `change: marked <label>`; then `change: set the tag fylgja-rehearse on
the branch third-link-local`, and last `change: the tag asks for its rehearsal, which takes it off; …`. It took 24.2 s
and 23.5 s where no branch of the name stood, and 26.2 s and 26.6 s where one did, one run each. The branch it deleted
is gone with its entries, each answering 404 by its id after. That exit 0 stands for N5 and N6, which nothing reads
between the tag and the report. A mark refused stops it, exit 1, with no tag set and the branch left as it stands for
reading; a branch of that name that is neither `ready`, `new` nor `provisioning` is refused by its status, nothing
deleted, and is deleted in NetBox, or another branch named, as the refusal says.

Without `NETBOX_TAG=1` the same command builds and marks the branch and sets no tag, its last line `change: the branch
third-link-local is built and marked: set the tag fylgja-rehearse on it …`. The block is then run with
`branch=third-link-local` too, through N6, and the tag is set by hand: in NetBox's pages, signed in as the superuser,
`admin`, with the password `local/.env`'s `FYLGJA_NETBOX_SUPERUSER_PASSWORD` holds, read from the file by the person
and never shown, the branch `third-link-local` is opened from the branching plugin's list of branches, edited once, the
tag `fylgja-rehearse` added to its tags, and saved. NetBox publishes its pages on the development host's loopback alone,
at `http://127.0.0.1:8800/`: they are reached from a browser on that host itself, or through a forward of port 8800 to
the browser, whichever the person chooses.

**Ready for the tag** is the block above run again before a tag set by hand, once `make netbox-change` without
`NETBOX_TAG=1` has exited 0, with `branch` set too, `branch=third-link-local`; it reads N0 to N4 again, then:

- **N5.** The branch: NetBox lists one branch of that name, `ready` and carrying no tag; its journal, listed by
  `assigned_object_type` `netbox_branching.branch` and `assigned_object_id` its id with `ordering=created`, holds two
  entries, `Fylgja stage: third-link` and then `Fylgja stage: n1-address`, by their first lines, and no other.
- **N6.** In the runner's environment, through `scripts/edge_dev.py run --source netbox`: `stage list --branch
  <branch> --json` lists the stages `main`, `third-link`, `n1-address` and `head`; and `stage plan --branch <branch>
  --json` exits 0, its document `planned` with every stage `built`, saved as `$out/plan.json`, and what it said on
  stderr as `$out/plan.log`. `stage plan` reads each mark's blueprint back from the core the block names, so it refuses
  a mark that core does not hold (`mark.unheld`). N5 is then read again, and reads the same: neither command writes to
  NetBox or takes a tag off.

From the tag to the report nothing touches the branch object: an edit of the branch while it carries the tag is an
update the event rule sends again, and starts a second rehearsal. Nor is the tag set a second time, `twin rehearse` run
by hand or anything written to either core.

The maintainer is asked once the block has passed: the request names the branch, says how long the dry run took, how
to reach NetBox's pages and sign in, and that how the tag is set is theirs to choose, by `NETBOX_TAG=1` or by hand.
They watch the branch being built, from `make netbox-change`'s first line to its last, and may watch the branch's
Journal tab gain its two marks as it runs, reloading the page to see each: whether the tab shows a new entry without
a reload has not been read. A branch they did not watch being built is not the run. On the cluster's run of
2026-11-13 the maintainer ruled the build's whole output, shown to them before the tag, to be their watching
([D-101](design/decisions.md#d-101)); a later run asks them again.

**What follows**, unasked, each read-only:

- within 60 s of the tag, one flow run of `twin-rehearse/main`, its parameters `{"branch": "third-link-local"}`: it was
  made about a second after the tag in every reading with Prefect answering and no sending waiting, 0.905 s and
  0.997 s in the dry run's two, and read `SCHEDULED` until the runner took it up, 12.3 s and 2.9 s;
- the tag gone from the branch, taken off by the run itself once it has read the branch and before the rehearsal
  starts, so at about the time the run reads `RUNNING`: 0.44 s and 0.48 s after it in the dry run;
- mid-run, one `rh-` twin in `fylgja-core twin list`, and its three SR Linux containers among `docker ps`;
- at the end, a third journal entry on the branch, by the account `fylgja-orchestrator`, its kind the rehearsal's
  status ([D-097](design/decisions.md#d-097)): `success` for `passed`, `danger` for `failed`, and `warning` for
  `not_rehearsed` and `stopped`. It is the report: the summary under its heading, which for a pass begins `## Rehearsal
  passed`, with a table and lists, then the detail. Then `fylgja-core twin list` is empty.

The same network's rehearsal took 277 s through Infrahub's check on the development host on 2026-11-12 and 600.5 s
there on 2026-11-13, on Infrahub's volumes kept since then, and 131.0 s and 109.5 s from the tag to the report
through NetBox's tag in the dry run; the flow's own time limit is 3,900 s. The maintainer reads the report
where it is filed: the branch's page in NetBox, signed in as above, its Journal tab, which lists the newest entry
first, so that the report stands above the two marks, each entry's kind shown as a badge, `Success` for a pass and
`Info` for a mark. They are asked to say, in their own words, that they read it there; that the two marks, `Fylgja
stage: third-link` and `Fylgja stage: n1-address`, stand beside it; its heading and its kind as the tab shows them;
and whether its table rendered as a table and its lists as lists, not as text.

**Read the run**, read-only, once the report's entry is written, or 60 s after the tag where no run was made (**When
no report comes**), into the run's directory, `local/phase-<n>/acceptance/<run>/`. NetBox is read with the superuser's
token and Prefect with `FYLGJA_ORCHESTRATOR_AUTH`, each from the environment inside the process that sends the
request. Nothing of a webhook's row of `main`'s changelog is saved: those rows hold its header unmasked.

- the times NetBox gives the tag's setting and its removal, and by whom: the branch object's rows of `main`'s
  changelog, `core/object-changes/` by `changed_object_type_id`, the id
  `core/object-types/?app_label=netbox_branching&model=branch` answers, and `time_after` the branch's `created`, by
  `ordering=id`, kept where `changed_object_id` is the branch's id: each row's `action`, `time` and `user_name`, the
  tag set by `admin` and taken off by `fylgja-orchestrator`, and no other row between. The rows are told apart by
  their `user_name` and order, not by their data: the run's removal and a setting by a `PATCH` each hold an empty
  `prechange_data`, `{}` where the member itself was read, and a `postchange_data` that lists the tag in the row that
  took it off as in the one that set it; the setting made in the branch's edit form holds a `prechange_data` of the
  branch's members, its `tags` before. Every edit of the branch object by the superuser adds an `update` row, one of
  its `description` while untagged among them; its status, `new` to `ready`, adds none;
- the deployment's flow runs created since the tag: its id by `GET /api/deployments/name/twin-rehearse/main`, its runs
  by `POST /api/flow_runs/filter` on that id (`flow_runs.deployment_id`), each with its `created`, its parameters, its
  state and its start and end times: one since the tag, and no more;
- that run's document by `POST /api/artifacts/filter` on the run's id and the type `fylgja-document`, keyed
  `fylgja-twin-rehearse-<run id>`: its `status`, `took_s` and `twin`, each stage's `result`, and its findings;
- the branch's journal entries in order, listed as N5 lists them, each with its `kind`, its author, `created_by`, a
  user's id, read by `users/users/<id>/`, and its `comments` saved byte for byte to a file of its own, with its size;
- the log of each running `netbox-worker` container since the tag (`docker logs --since <the tag's time>`), the
  runner's output over the run, and `local/prefect/server.log` over the run, which holds each start's banner and no
  line of a request;
- `fylgja-core twin list`.

Whether the run is the one the criterion names is read from the document's `status` and its stages' `result`s, never
from the entry's colour. What is read holds a site's values: before any of it is committed, each address and host's
name in it is replaced by a placeholder, and the token check prints 0 for each file to be committed and each of the
run's files. On the cluster the `<(…)` also prints Reach's token, read from its file inside the command:
`printf '%s\n' "$(< local/<the token's file>)"`.

```bash
set -a; . local/.env; set +a
/usr/bin/grep -c -F -f <(printenv FYLGJA_NETBOX_TOKEN FYLGJA_NETBOX_WRITE_TOKEN FYLGJA_ORCHESTRATOR_NETBOX_TOKEN \
    FYLGJA_API_TOKEN FYLGJA_ORCHESTRATOR_API_TOKEN FYLGJA_ORCHESTRATOR_AUTH FYLGJA_NETBOX_SUPERUSER_PASSWORD \
    FYLGJA_NETBOX_SECRET_KEY FYLGJA_NETBOX_API_TOKEN_PEPPER
  printf '%s\n' "${FYLGJA_ORCHESTRATOR_AUTH#*:}" "$(printf %s "$FYLGJA_ORCHESTRATOR_AUTH" | base64 -w0)" \
    "${FYLGJA_NETBOX_TOKEN#*.}" "${FYLGJA_NETBOX_WRITE_TOKEN#*.}" "${FYLGJA_ORCHESTRATOR_NETBOX_TOKEN#*.}") \
  <each file>
```

**When no report comes**, read 60 s after the tag from the branch's tags and journal and the deployment's flow runs
since the tag, as **Read the run** reads them. A run still `RUNNING` is a rehearsal under way, and is left to end.

- *The branch keeps its tag, and no flow run was made*: the request never reached Prefect, and NetBox never sends it
  again. Prefect down or not answering when the tag was set loses the request; a webhook naming a deployment id Prefect
  no longer has, after a new `local/prefect/`, is answered 404, and `make netbox-hook` is run again; no `netbox-worker`
  running, a rule disabled or changed, or a header that is not `FYLGJA_ORCHESTRATOR_AUTH`'s each makes no run, and
  N1 and N3 are written to refuse each, N3's refusal not yet seen in a run. N1 to N3 are read again, with the worker's
  log and `local/prefect/server.log` since the tag:
  the worker logs each sending, with Prefect's words or the address it failed at, and NetBox lists a failed one among
  its queues' failed tasks (`/core/background-queues/0/failed/`). The cause is removed, and the tag set again. As read
  once with `make prefect-down` before the tag: the worker logged the sending and its failure,
  `Failed to establish a new connection: [Errno 111] Connection refused` at `host.docker.internal:4200`, within a
  second of the tag, and the queue `default` counted one failed job; 60 s on the branch kept its tag and its journal
  no entry more. After `make prefect-up` under the same home, the deployment's id unchanged and the runner, left
  running through the stop, serving again, no run was made from the tag's setting to 133 s after the start returned:
  the request is not sent again.
- *A flow run was made and the tag stays, with no entry*: the run started and was refused before it took the tag off,
  and shows as failed in Prefect, in the refusal's words: its settings or its reader document refused; no branch of the
  name, one made anew under it, or one not `ready`; the branch's read or the tag's removal refused or unanswered by
  NetBox, as by a runner that holds the example's token of a purged instance; or a runner of the source `infrahub`
  serving, which reads Infrahub and not NetBox. The run's state and message, and its log lines
  (`POST /api/logs/filter` on its id), say which. The tag is taken off first, since an edit of the branch while it
  carries the tag asks again; then the cause is removed, and the tag set again.
- *A flow run stays `SCHEDULED`, the tag on the branch*: no runner took it. A tag set while Prefect answers and no
  runner serves was not read, nor whether a runner started later takes such a run up. So the run is deleted
  (`DELETE /api/flow_runs/<id>`, with `FYLGJA_ORCHESTRATOR_AUTH`, answered 204 and the run then 404 by its id, as read
  of a run `SCHEDULED`) before a runner is started, so that none rehearses it late; the tag is taken off, and set
  again once the runner serves.
- *The tag is gone and no entry was written*: the rehearsal started and was stopped, cancelled, past the flow's time
  limit, or its runner ended under it. Prefect says why: the run's state and message, its log lines and the runner's
  output. A twin `rh-…` it left is read with `fylgja-core twin show <twin>` until it answers that the twin is not
  found, or destroyed by `fylgja-core twin destroy <twin>`, which the run's record says. A run its runner left
  `PENDING`, `RUNNING` or `CANCELLING`, which N2 refuses for as long as it stands, is then deleted as above, its twin
  read gone first; the delete of a run in those states was not read. Then the tag is set again.

The tag is set again by `make netbox-change NETBOX_TAG=1`, which deletes the branch and builds it again, marks and tag
with it; or by a person in NetBox, who takes the tag off where it stands, which sends nothing, and sets it again, which
asks again: one `PATCH` of the branch's `tags` each, with the superuser's token, does the same, and after the lost
request above made one run, which rehearsed as the first. In a run the maintainer watches, each of these ends the run
short of the criterion: the cause is removed, and the run is made again from `make netbox-change`, watched from the
build.

**Clean up**, read-only but for what each step names:

- `fylgja-core twin list` empty, a twin left read and destroyed as the run through Infrahub's check says.
- The branches are left as they stand, unmerged and untagged; the next `make netbox-change` of a name replaces its
  branch, its marks and its report.
- A failed sending a run left is listed on `/core/background-queues/0/failed/` and removed by
  `POST /api/core/background-tasks/<id>/delete/` with the superuser's token.
- When the work is done: the runner stopped by its pid, N2's, and the core by its pid, N4's, the listener of
  `FYLGJA_LISTEN`; then `make prefect-down` and `make netbox-down`, after which `docker compose ls -a` is expected to
  list `fylgja-core-netbox` with no container running, its status `exited(<n>)`, as it lists a stopped Infrahub;
  NetBox's stopped listing has not been read. A
  `make prefect-down` with the runner still up leaves the runner running, and `make prefect-up` under the same home
  has it serve again, as read once.

**On the cluster** NetBox, Prefect and the runner stay on the development host, and everything is as above but this:

- The core is the deployed one alone: the local core stopped by its pid, nothing listening on `FYLGJA_LISTEN`, no SR
  Linux container left on the host (`docker ps`), and no core started in process against the cluster ("Never two
  cores on the cluster at once"). It runs the image of the branch under test, built, pushed and deployed as
  [Running the core on a cluster](#running-the-core-on-a-cluster) says, the push and the deploy each the maintainer's
  word, at one replica (`<kubectl> -n fylgja get deployment fylgja-core`, `<kubectl>` the site's path to `kubectl`).
  The overlay's `secret/tokens` holds the principal `orchestrator` with the hash of `FYLGJA_ORCHESTRATOR_API_TOKEN`,
  since the marks and the runner use that token there too; a line added to it is the maintainer's word.
- The runner, stopped by its pid where it runs, is started by one command that loads `local/.env`, then sets Reach's
  three, then runs the target. A load after the three would set `local/.env`'s address again, and the run would
  rehearse on the host.

  ```bash
  set -a; . local/.env; set +a
  export FYLGJA_API_ADDRESS=https://<the Service's address> FYLGJA_API_CA=$PWD/local/<the site's CA>
  export FYLGJA_API_TOKEN="$(< local/<the token's file>)"
  make orchestrator-serve SOURCE=netbox
  ```

- The block is run as it stands after the same first three lines, `out=local/phase-<n>/acceptance/<run>`, `branch`
  where it is set, and `kubectl() { <kubectl> "$@"; }` in place of the target. With `FYLGJA_API_CA` set, N4 reads the
  deployed core: an `https://` address; no listener on `FYLGJA_LISTEN`'s port, where the local core served; the
  Deployment `fylgja-core` at one replica, its image's tag printed as the text after the reference's last `:`, and its
  pod's start time; `GET /v1/twins` once with the runner's token, which a token file lacking its hash refuses, before
  any seed; and `capacity show --json` and `twin list` with the caller's own `FYLGJA_API_TOKEN`, Reach's, answering the
  driver `clabernetes` and more than one host, the room and the twins as above. A read that lists one host is the local
  core's.
- The change is built by one command with the same three lines first, so that its marks are given to the deployed
  core: `make netbox-change NETBOX_BRANCH=third-link-cluster NETBOX_TAG=1`; or, for a tag set by hand, the same
  without `NETBOX_TAG=1`, and the block run again with `branch=third-link-cluster` before the tag.
- Mid-run the twin is on the cluster: one `rh-` twin in the deployed core's `twin list`, its namespace
  `fylgja-twin-<twin>` in `<kubectl> get namespaces`, and no SR Linux container in `docker ps` on the host.
- The dry run there took 249.6 s from the tag to the report, one run, against the local dry run's 131.0 s and
  109.5 s; the twin's namespace was first listed about 20 s after the tag, and first found gone by the report.
- **Clean up** there is as above, and besides: the twin's namespace `fylgja-twin-<twin>` read gone in `<kubectl> get
  namespaces`, and the deployed core left as it runs, at one replica, no core started on the host; its scale is the
  maintainer's word.

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
