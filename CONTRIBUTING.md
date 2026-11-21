# Contributing

> **Not accepting contributions yet.** Thank you for your interest in Fylgja. Fylgja is not
> taking outside issues or pull requests yet; this page will say when that changes. This page
> describes how the project itself works. A security concern is always welcome, as
> [SECURITY.md](SECURITY.md) describes.

How to set up, build, test and change fylgja-core. The project's governance and design live
in [`design/`](design/): the system in [architecture.md](design/architecture.md), the rules
every change keeps in the [constitution](design/constitution.md), and the reasons in the
[decision log](design/decisions.md). User documentation lives in [`docs/`](docs/README.md).
Read in this order: architecture, constitution and decisions, where rejected alternatives live
and are to be checked before one is proposed; then this page; then the
[glossary](docs/glossary.md) when a term is new, and [verified-facts.md](design/verified-facts.md),
which records what has been verified against containerlab, clabernetes, Infrahub, NetBox, Nautobot,
Prefect and the network operating systems, with versions and dates. [integrating.md](docs/integrating.md)
shows how to join Fylgja to a source of truth and a platform of your own, walked through the
example orchestrator, which lives in
[`fylgja-examples`](https://github.com/happypathnetworking/fylgja-examples/tree/v1.1.0/).

This repository, **fylgja-core**, holds two pieces: the core, which turns a blueprint into a
twin and knows no source of truth ([D-003](design/decisions.md#d-003)); and a reader for each source
of truth, [Infrahub](readers/infrahub/README.md), [NetBox](readers/netbox/README.md) and
[Nautobot](readers/nautobot/README.md), the last published from 1.1.0
([D-121](design/decisions.md#d-121)). The example orchestrator and the demonstrations
([D-081](design/decisions.md#d-081)) are in
[`fylgja-examples`](https://github.com/happypathnetworking/fylgja-examples/tree/v1.1.0/),
which keeps this repository's paths ([D-126](design/decisions.md#d-126)). It is a
rebuild, in Python, of a prototype with a Go core (`happypathnetworking/fylgja-prototype`), on a
clean break in formats ([D-001](design/decisions.md#d-001), [D-002](design/decisions.md#d-002));
the prototype is archived and private, and the design documents cite it as history.
[design/core.md](design/core.md) says which phases are done, and its "Sequence" what each built
and what it left. The core's drivers are local containerlab, for development, and
[clabernetes](https://github.com/clabernetes/clabernetes) on Kubernetes, for production.

## Setting up

You need Python 3.14 and uv 0.12.23, installed by uv's own installer or the distribution's package.
The system's Python is never installed for you.

```sh
make venv               # core/.venv, synced from uv.lock
make lint               # ruff and mypy (strict)
make test               # the pure tier: no infrastructure
```

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
   format is made there, in the same change as the code that reads or writes it. From 1.0 a
   change to a held format only adds ([What major version 1 holds](docs/compatibility.md)).
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
   - A runbook for an acceptance run from a fresh clone says to clone at the tag and
     `git switch -c <name>`, since a clone at a tag is on a detached head and
     `fylgja-examples`' `make infrahub-demo` refuses one; the clone's `local/.env` is made from the
     lines the
     runbook names, never copied from an earlier clone.
   - An install that follows an upload first reads the index's simple page for the version,
     which can lag the index's JSON API by about a minute; an install from PyPI that must use
     PyPI alone runs `pip --isolated`.
   - A runbook saves the output of each of its checks, as it saves each command's: a line
     seen only at the prompt is cited from a read-only re-run made afterwards, and the record
     says so. A file a repeated command overwrote, and restored from the screen, is said to be
     restored, beside what corroborates it.
   - A dry run follows the runbook's text and nothing else: a step made by hand, such as a
     directory, is a gap in the runbook, and is written into it before the maintainer's run.
   - A process the maintainer starts in a terminal of their own writes its log by
     redirection, never through a pipe: Ctrl-C ends a `tee` with it, and its stop goes
     unlogged.
4. **Land.** On the maintainer's word:
   - `main` is brought into the integration branch where it is not an ancestor of it
     (`git merge-base --is-ancestor main phase-N-integration`): merged in (`--no-ff`) and
     gated, so that the squash's tree is the gated one;
   - the phase is written as built on the integration branch: a decision entry for each
     place the build departed from a decision, the sentences it made untrue corrected, and
     the item in "Sequence" marked done, with what it left to later phases; an open question
     it adds is named in the next release's notes, which `core/tests/test_release.py` holds;
   - where a later phase's design holds decision numbers provisionally, its session is told
     before that commit takes the next free numbers, and told the numbers taken after the
     squash, since its other repositories may cite them;
   - that commit is reviewed afresh, its findings fixed by amending it and the fix read
     again, before the history is tagged; a figure it states is read from the run's own log
     by the controller, and not only by the reviewer;
   - where the phase is a release, the version commit is the last commit before the squash,
     and the changelog's head is dated the day the tag will be made;
   - the integration branch is squashed onto `main` as one commit; where CI fails on the
     landing's last commits on a tree it passed before, the failing test is read against the
     earlier green run, only the failed job is re-run, the test is recorded for a fix, and a
     release's tag waits for a green run;
   - its history is kept under the local tag `archive/phase-N-integration`;
   - the build's records (ledgers, briefs, reviews, rulings, run logs) go to
     `local/sdd/phase-N/`.

## Tooling

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 | [D-001](design/decisions.md#d-001) |
| uv | 0.12.23 | Makes every Python environment the tree makes, in place of pip and `python -m venv` ([D-108](design/decisions.md#d-108)): `core/.venv`, the image's build stage, the wheel check's builds and empty environments and `infrahubctl`'s own; the root `pyproject.toml` requires exactly this version. Install exactly 0.12.23, by uv's own installer or the distribution's package, pinned to it; another uv is refused by `make venv` ("Required uv version `==0.12.23` does not match the running version") and by `make wheelcheck` in one line naming both, and with no uv on the PATH `make venv` is the shell's `uv: not found`, exit 127 |
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
| NetBox, netbox-docker, netbox-branching | 4.7.5, 5.1.1, 1.2.3 | The development NetBox (`make netbox-up`): netbox-docker's release for its version, fetched into `local/netbox/` and never vendored, its image with one layer adding the branching plugin, built from `netbox/dev/`, run by Docker's Compose plugin ([D-096](design/decisions.md#d-096)). Pinned as read on the development host: NetBox's 4.7.5 was two days old when the design chose it, under the two weeks every other pin keeps, on the maintainer's word ([D-099](design/decisions.md#d-099)) |
| Nautobot, Golden Config, Postgres, Redis | 3.2.8, 3.0.8, 17.10, 7.4.11 | The development Nautobot (`make nautobot-up`): Network to Code's image for Nautobot's version on Python 3.14, with one layer adding Golden Config by uv, built from `nautobot/dev/` and never pulled, beside Postgres, Redis, a worker and a service that serves the templates' repository, run by Docker's Compose plugin ([D-119](design/decisions.md#d-119)). Each is a release at least two weeks old when it was chosen: Postgres and Redis by the digest of the index Docker Hub held, the day it was read (`nautobot/dev/compose.yml` names each), Postgres 17.10 and not 17.11, whose index was pushed on 2026-11-11, and Redis 7.4.11 and not 7.4.12, built on 2026-11-09 |

Each pin, the `server` extra's among them, and each floor of the base install is a release at
least two weeks old when it was chosen, but NetBox's, as its row says. `make venv` syncs
`core/.venv` from `uv.lock`, the uv workspace's lock at the root ([D-108](design/decisions.md#d-108)):
the core, the reader, the NetBox reader and the Nautobot reader, each editable with every
extra, the versions every tier runs on. A pin is moved in its `pyproject.toml` and the lock made
again by `uv lock`, in one commit. uv's own version is written in the root
`pyproject.toml`'s `required-version`, the `Dockerfile`'s image tag and, with the tag, its digest, `nautobot/dev/Dockerfile`'s digest, CI's `version`,
`README.md`, `AGENTS.md`, this file and the `Dockerfile`'s comment, and moves in all of them together. The lock's other versions are the ones PyPI held the day it
was made, as an install's are: the two-week rule binds the pins. A venv inside the tree carries
a `.gitignore` of `*`.

## Make targets

| Target | What it does |
|---|---|
| `make venv` | The core's venv, `core/.venv`, a locked `uv sync` of the workspace from `uv.lock` ([D-108](design/decisions.md#d-108)): the core, the reader, the NetBox reader and the Nautobot reader, each editable with every extra, at the versions every tier runs on; a lock that disagrees with a `pyproject.toml` is refused. A `core/.venv` that pip made before keeps its pip: `make venv` syncs it in place, and removing `core/.venv` once gives one with none |
| `make lint` | ruff over `core/`, `scripts/`, `infrahub/`, `netbox/` and `nautobot/`, then mypy in strict mode over the core, its tests and `scripts/`, and again, apart, over `infrahub/seed/`, `infrahub/tests/` and `scripts/infrahub_dev.py`, over `netbox/seed/`, `netbox/tests/` and `scripts/netbox_dev.py`, and a fourth time over `nautobot/seed/`, `nautobot/tests/` and `scripts/nautobot_dev.py`, since the four directories of tests name modules alike; then the same over the reader, `readers/infrahub/`, and over the NetBox reader, `readers/netbox/`, and over the Nautobot reader, `readers/nautobot/` |
| `make test` | The pure tier: no infrastructure. `core/tests/`, then `infrahub/tests/`, then `netbox/tests/`, then `nautobot/tests/`, then the reader's, then the NetBox reader's, then the Nautobot reader's. Gates every pull request |
| `make live` | The live tier on the local driver: the driver's own modules under `core/tests/live/`, then the conformance suite on the local harness. The driver's own: readiness and the push on one SR Linux and one cEOS node booted under containerlab (`core/tests/live/test_push.py`); labs through the local driver, `admit`, `apply`, `inspect` and `destroy`, a `destroy` refused under packages that do not list a node's image, the residue rule, two labs at once, and an `admit` refused on a pool a Docker network of the test's own holds, naming the network and `FYLGJA_LAB_POOL` (`core/tests/live/test_containerlab_driver_live.py`); three labs applied at once, their deploys one after the other, with the host's load and connections read (`core/tests/live/test_many_labs_live.py`, about 2.5 minutes alone); `changes` held to containerlab's own dry run for every step fixture, with the hot-add recreate of two cEOS nodes and `exec` in a probe host (`core/tests/live/test_changes_live.py`, about 4.5 minutes alone); verify over gNMI on a probed twin, with a node stopped and started by containerlab and by Docker, and a configured cEOS node's host name (`core/tests/live/test_verify_live.py`, about 5 minutes alone); the trigger and the restore through Docker's own restart paths, the loop run in-process with its resync an hour away: a node restarted by `docker restart` and one started again by Docker's restart policy, each pushed again by a restore the driver's events started within seconds (its links are not restored), and one removed, reported missing once its boot window passed (`core/tests/live/test_restore_live.py`, about 4 minutes alone); and the object store against Versity S3 Gateway under Docker, the store contract whole and every compare-and-set raced by 32 stores (`core/tests/live/test_object_store_live.py`, about 1 minute alone). Then the suite, as `make conformance DRIVER=containerlab` runs it (below), its many-twins scenario among it, about 36 minutes of the whole. 168 tests by collection; about 62 minutes whole, with the cluster quiet. Load `local/.env` first |
| `make cluster` | The cluster tier: the clabernetes driver's calls on the k3s cluster, from the development host. The driver's reach into Kubernetes, every call of `LightKube` read on a two-node SR Linux twin (`core/tests/cluster/test_kube_cluster.py`, 1 to 2 minutes alone); the driver as the server makes it on a three-node twin: `admit` against a namespace that is not the twin's, `apply` with the root logger at DEBUG and its repeat, `exec`, a node's container ended in its pod, a pod deleted, `reconfigure`, a `destroy` refused under packages that do not list a node's image, `destroy` and the residue, and forty rows of an `apply` cancelled at its Namespace's create and its `destroy` asked at once, their namespaces then read for 30 s (`core/tests/cluster/test_clabernetes_driver_cluster.py`: its last test, the forty rows, took 279 s alone as read on 2026-11-16, and the rest of the module about 4 minutes alone, as read before that test was added); and `changes` held to the pods' uids for every step fixture, with the hot-add recreate of two cEOS nodes killed before its deletions and resumed (`core/tests/cluster/test_clabernetes_changes_cluster.py`, about 10 minutes alone); and the trigger and the restore through the loop, run in-process with the resync an hour away, on a two-node twin stepped twice: a pod deleted, a container ended in its pod and that pod replaced by the driver, a probe host's and a cEOS node's pods deleted, each restored without the resync, the settled twin's pods watched for three minutes, and a watch asked at a compacted version (`core/tests/cluster/test_restore_cluster.py`, about 13 minutes alone); and the Lease, on a Lease of its own in the kubeconfig's default namespace held by two holders in one process: taken, waited for, taken over 15 s after its holder went silent and released (`core/tests/cluster/test_lease_cluster.py`, about 30 s alone); and the driver's reading of the cluster's room, `capacity`, with no twin up and then with a two-node twin admitted, planned and applied by the driver (`core/tests/cluster/test_capacity_cluster.py`). 44 tests by collection; about 35 minutes whole. Load `local/.env` first, with `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE`, `FYLGJA_POD_CIDR` and the cEOS pull credential set. With the core deployed on the cluster, its Deployment is scaled to no replica first and back to one after ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make conformance DRIVER=containerlab\|clabernetes` | The driver conformance suite alone (`core/tests/conformance/`): one set of scenarios, written once, on the harness of the driver `DRIVER` names, `containerlab` by default; any other name is refused in one line. A twin created and shown; stepped through every step fixture with verify after each and the burst held, and the step's refusals; the core killed at each phase boundary of a create and of a step, during an apply and during a destroy, a waiting CLI riding through, a deletion after a kill, and a step cancelled; a node replaced behind the core and one stopped; leftovers read by label; node access through each node's own transport; and isolation over TCP between two twins and from a third namespace, where the driver declares it. Then many twins at once (`core/tests/conformance/test_many.py`): the harness's count, three here and five on the cluster, created together and all Ready, each stepped while the others run with no node unread, a twin of forty nodes refused in a dry run and at its create with the capacity read agreeing, and every twin destroyed, about 5 minutes here and 8 on the cluster. The scenario needs a band of room: about 4.5 CPU and 17 GiB free here for its three twins and 7.5 CPU and 28 GiB on the cluster for its five, and, with them up, under about 80 GiB free on either, since the forty-node twin must be refused; on a roomier runtime its dry run is answered and the scenario fails there, having made no twin of it. `containerlab` runs `fylgja-core-server` on this host under the live tier's marker: 54 tests, about 36 minutes. `clabernetes` drives the core deployed on the cluster over TLS, killing it by its pod, under the cluster tier's marker: 54 tests, about 68 minutes. Load `local/.env` first, and for the cluster the suite's own variables ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |
| `make wheelcheck` | Builds the core's wheel from `core/` and `formats/`, which carries the core's formats and no other, and installs it, with uv, into two empty venvs outside the tree, each made by `uv venv` and the wheel built by `uv build`: with the `server` extra, where it validates a fixture and the server's modules import; and alone, each of the base's four libraries at the floor of its range, where the model and the client import, a run is followed over a fake transport and `fylgja-core-server` refuses in one line; then the reader's wheel, from `readers/infrahub/` and `formats/` and carrying its one format, `infrahub-reader-1`, and no other, with its GraphQL documents, beside the base alone in a third, where the seed's reader document decodes, the command's module imports with nothing of the server, Prefect or Infrahub's SDK, and `fylgja-infrahub --help` exits 0 ([D-066](design/decisions.md#d-066), [D-084](design/decisions.md#d-084)). Then the NetBox reader's wheel, from `readers/netbox/` and `formats/` and carrying its one format, `netbox-reader-1`, and no other, is installed beside the base alone in an empty venv of its own, where a copy of the seed's reader document decodes, the command's module imports with nothing of the server, Prefect, a client library of Infrahub's or NetBox's, the Infrahub reader or the example, `fylgja-netbox --help` exits 0, and `fylgja-netbox check` given no token exits 2 with the one line that names `FYLGJA_NETBOX_TOKEN` ([D-095](design/decisions.md#d-095)). After it, the Nautobot reader's wheel, from `readers/nautobot/` and `formats/` and carrying its one format, `nautobot-reader-1`, and no other, is installed beside the base alone in an empty venv of its own, where a copy of the seed's reader document decodes, the command's module imports with nothing of the server, Prefect, a client library of Infrahub's, NetBox's or Nautobot's, the Infrahub reader, the NetBox reader or the example, `fylgja-nautobot --help` exits 0, and `fylgja-nautobot check` given no token exits 2 with the one line that names `FYLGJA_NAUTOBOT_TOKEN` ([D-118](design/decisions.md#d-118)). Needs the network, so it is no part of `make test`; CI runs it on every push to `main` and every pull request |
| `make wheels` | Builds the four published wheels, `fylgja-core`, `fylgja-infrahub`, `fylgja-netbox` and `fylgja-nautobot`, by `uv build` into `dist/` (git-ignored, emptied first, each member's `build/` removed), with the setuptools `build-constraints.txt` names, each at the tree's commit, which each wheel holds ([D-106](design/decisions.md#d-106), [D-121](design/decisions.md#d-121)). Then `python3 -I scripts/publish.py check --tag v<version> --commit <commit> --dist dist` holds the tag, `VERSION`, `CHANGELOG.md`'s head and the wheels to one another, naming every fault in one pass, and prints `index=pypi` or `index=testpypi`; `notes` prints the changelog's head section. The script uploads, tags and pushes nothing. Needs the network |
| `make image` | Builds the core's image from the `Dockerfile` at the root ([D-062](design/decisions.md#d-062)) as `fylgja-core:<tag>`, the tag the commit's first 12 characters, with `-dirty` where `git status --porcelain` prints anything. Its build context is `.dockerignore`'s allow-list, so nothing under `local/` reaches a layer. Needs Docker and the network |
| `make imagecheck` | Builds the image, then runs it: its user is 10001; given only `FYLGJA_STORE` and a `FYLGJA_TOKENS` that names no file, it exits 2 naming `FYLGJA_TOKENS`, the packages in its wheel loaded against the wheel's formats, `FYLGJA_PACKAGES` unset; and the formats it carries are the core's, `CORE_FORMATS` in `core/setup.py`, equal to `formats/`'s by name and by bytes; and it has no copies of `psp/` and `probes/` of its own and sets no `FYLGJA_PACKAGES`: `packages.shipped()` in the image holds the YAML git tracks there, by name and by bytes, and no other file, so a file git ignores there (an editor's `*.swp`, a nested `local/`), which reaches the image with no `-dirty` tag, fails it. Prints the tag it checked last. CI runs it on every push to `main` and every pull request, and pushes nothing |
| `make infrahub-up` | The development Infrahub, the Compose project `fylgja-core-infrahub` at `INFRAHUB_VERSION` (1.11.11), run by `scripts/infrahub_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its eight names ([`.env.example`](.env.example)) that the file does not hold, generated and never printed, and changes no line already there, since a token made again would not open the kept database; a name the file holds with no value (`NAME=`, `NAME=""`, read from its last line where it has several) is refused, exit 2 and before anything is fetched or started, naming it, since Compose would replace it by the published file's own default; so is `NAME= # a note`, which a shell reads as empty and Compose as the text `# a note`; makes `local/infrahub/repos/` (mode `0700`) where it is absent; fetches Infrahub's published Compose file for the version into `local/infrahub/` once; starts the project with `infrahub/dev/compose.override.yml`, asking Compose once more where its first start fails; and waits up to 600 s for `/api/info` to answer that version, failing at once on another. `VERSION` is the make variable's whatever the shell or `local/.env` holds, and Compose is given none of the eight names and no other name beginning `INFRAHUB_` from the shell, whatever it exports, so that it reads them from `local/.env` alone or takes the published file's defaults: an `INFRAHUB_ADDRESS` exported for a client would otherwise be the task workers' address of Infrahub. The task workers mount the main checkout's `.git` and `local/infrahub/repos/` read-only, and nothing else of the checkout, and are given nothing else of Fylgja's. The override binds each port the published file publishes to loopback (8000, and 15692, 2004 and 6362 for metrics and backup), which that file would publish on every interface, the server answering a read with no token; from another machine the UI is reached by a forward of port 8000 over SSH. About 3.5 minutes on new volumes and 1.5 minutes on kept ones; it then holds about 4.5 GiB. Needs Docker, and the network for the first fetch |
| `make infrahub-down` | Stops the development Infrahub (`docker compose stop --timeout 60`), in 20 to 50 s: each container is given 60 s to exit by itself, since Compose's own 10 s killed Neo4j, which needs about 11 s, and the server once took 31 s. Its containers, network and volumes and everything under `local/infrahub/` are kept, port 8000 and the memory released, and `make infrahub-up` starts it again. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volumes (`down -v`), and `local/infrahub/seed.json` with them; `local/.env` and the rest of `local/infrahub/`, the fetched file among it, stay. It is stopped for every live, cluster or conformance run |
| `make infrahub-register` | The schema library, the group and this repository's registration on the development Infrahub's `main` (`infrahub/seed/register.py`), at `REF`, the branch checked out, from a worktree too, and that branch's commit; an empty `REF`, a detached head, is refused in one line. The library under `infrahub/schema/dcim/` is loaded by `infrahubctl`, given 600 s (`INFRAHUB_TIMEOUT`), where `main` holds none of its kinds, and `main` is read for up to 120 s until it lists them all; a `main` holding part of them is refused with nothing written. The group `fylgja-devices` is made where it is not there. The read-only repository `fylgja` is registered from the main checkout's `.git`, mounted at `/srv/fylgja`: created where there is none; its `ref` updated and its last commit imported where it names another branch; its last commit imported where it reads another commit; then read for up to 300 s until it reads the commit `in-sync` and `online`, with the artifact definition `device-config` on `main`. Then each running task worker of the project is read by `docker` for the tree of that commit, `/opt/infrahub/git/<the registration's id>/commits/<the commit>`: a recreated worker holds no clone, and a task Infrahub runs on it fails, so one lacking the tree is not settled. Its import is asked, at once where the run sent nothing and else 30 s on, and again every 30 s until each holds it, within 300 s: an import with no new commit clones on the one worker that runs it, and after a new commit's import each worker held the tree by an import or a pull of its own, Infrahub's fetch to each beginning after. One already there, settled and its commit's tree on each worker is sent nothing. Its first run builds `infrahubctl`'s venv, `local/infrahub/.venv/`, in about 45 s. About 2.5 minutes on an empty instance, read once, and seconds where all of it is there. Load `local/.env` first |
| `make infrahub-seed` | The fixture network on the development Infrahub's `main`, and the branch `SEED_BRANCH` (`third-link`) with its two staged edits, each regenerated and timed (`infrahub/seed/seed.py`). It is refused with nothing written where `main` holds no artifact definition `device-config` (run `make infrahub-register` first). The reader's kind `FylgjaProbe`, `readers/infrahub/schema/fylgja-probe.yml`, passed as `--schema`, is then loaded on `main` by `infrahubctl` where `main` lacks it, and `main` read for up to 120 s until it lists it. `infrahub/seed/main/`'s object files are loaded by `infrahubctl`, one at a time in the order of their names, where `main` holds none of the devices they say: the manufacturer, the site `lab` under its metro, country and region, the platform, the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json` with their ports and addresses, each a member of `fylgja-devices`, the fixture's cables less the one between `n1` and `n3`, and the probe `n1-loop` of `three-node-probed.json`. Where `main` holds all three, nothing is loaded, since a load would take each device out of the query groups Infrahub joined it to at its first generation; so a hand edit on `main` is not undone by a seed, and a purge and a seed undo it; so too a `main` seeded before the probe's kind existed, which holds no probe, is purged and seeded again. A `main` holding part of them is refused with nothing written. The configurations are then generated and waited for, up to 180 s, until each device tagged `fylgja` has its artifact `device-config` `Ready` and each device the run made shows a checksum that moved; an artifact reading `Error` ends the wait at once. The branch is then made anew from `main`, after the registration's import ([D-088](design/decisions.md#d-088)): one an earlier seed left is deleted first, and the branch, made with `sync_with_git: false`, is refused where it does not read the artifact definition; a create that fails or goes unanswered is read for its branch for up to 120 s. On it, in order, `infrahub/seed/stages/1-third-link.yml` adds the cable between `n1` and `n3`, after which the network is `three-node.json`'s, and `2-n1-address.yml` the address `192.0.2.1/24` on its `n1` end. After each, the configurations are generated and waited for, up to 180 s, until each device the edit changes shows a checksum that moved, and the stage's time is the reader's `head` of the branch, the first instant after its latest write, read with the reader's token, `FYLGJA_INFRAHUB_TOKEN`, once two readings of it 10 s apart agree, within 120 s, so that `seed.json` and a read at its times cannot disagree; a `head` refused because a list it read was not whole, as the event log once was just after a generation, is read again, and one refused otherwise ends the seed. The reader's connection is made before anything is removed or written: its token not set, or a variable not of its form, is exit 2, and Infrahub refusing it exit 1. `local/infrahub/seed.json` is removed before anything is written and written whole at the end, `{"branch", "scope": "tag:fylgja", "stages": [{"label", "at"}, …]}`, the stages in order; a run that fails or lapses leaves none. On an empty `main` after a purge, the kind and the probe among it, 269 s wall, one run on 2026-11-21. An instance seeded before 1.1.0 keeps what the seed no longer clears (`FylgjaStage`, marks, an open proposed change, the example's checks), so purge it once: `make infrahub-down PURGE=1`. Load `local/.env` first |
| `make contract` | The contract tier (below), `infrahub/tests/contract/`, then the reader's, `readers/infrahub/tests/contract/`, against the running development Infrahub, with `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` set on its own command lines. One module of the reader's is run as its line runs the reader's, by its path in place of `tests/contract`. The reader's line, 30 tests, took 757 s run alone, measured once since a branch's events take in `main`'s up to its branch point, and 396 s and 402 s in two runs before; 895 s within the whole tier below. The registration's tests read the task workers' clones by `docker`. Load `local/.env` first |
| `make netbox-up` | The development NetBox, the Compose project `fylgja-core-netbox`: NetBox `NETBOX_VERSION` (4.7.5) on netbox-docker `NETBOX_DOCKER_VERSION` (5.1.1) with netbox-branching `NETBOX_BRANCHING_VERSION` (1.2.3), run by `scripts/netbox_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its four names ([`.env.example`](.env.example)) that the file does not hold, the three secrets generated and never printed, and changes no line already there, since a pepper made again would refuse every token the kept database holds and a password made again would not be the superuser's; a name the file holds with no value is refused, exit 2 and before anything is fetched, built or started, naming it, as `make infrahub-up` refuses one. It fetches netbox-docker's release for its version into `local/netbox/netbox-docker-<version>/` once, never changed; where the project's network `fylgja-core-netbox_default` stands with another subnet than the override's 198.51.100.0/24, removes the project's containers and network and keeps its volumes, so that the start makes the network again, and where Docker could not inspect it says so in one line and goes on; builds the image `fylgja-core-netbox:<NetBox's>-<the plugin's>` from `netbox/dev/`, netbox-docker's with one layer adding the plugin; starts the project with `netbox/dev/compose.override.yml`, which mounts `netbox/dev/plugins.py` over the release's and publishes NetBox on loopback at port 8800; and waits up to 1200 s from that start for Docker to call `netbox` healthy, asking Compose once more where the first start failed, as it does while NetBox migrates, leaving the worker not started. It then reads `/api/status/` with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`, provisioned with the file's password and its line written, that line alone, where the file holds none or NetBox refuses the one it holds, as after a purge; a password NetBox refuses ends it, naming `make netbox-down PURGE=1`. It is done once NetBox names both versions and a running worker, within 60 s of healthy, without which no branch is ever ready, and fails at once on another NetBox, another plugin version or none, which is how a `plugins.py` not loaded shows. The three versions and `netbox/dev/` are set in Compose's environment over whatever the shell or `local/.env` holds, and Compose is given no other name beginning `FYLGJA_NETBOX_`, so that it reads the secrets from `local/.env` alone. About 12.5 minutes on new volumes, 748.9 s, 764.4 s and 749.6 s in three runs, and 73.7 s on kept ones, the image built from the cache each time; it then holds about 1.4 GiB. Needs Docker, and the network for the first fetch |
| `make netbox-down` | Stops the development NetBox (`docker compose stop --timeout 60`), in 8.9 s, read once, each container given 60 s to exit by itself. Its containers, network and six volumes and everything under `local/netbox/` are kept, port 8800 and the memory released, and `make netbox-up` starts it again holding what it held. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volumes (`down -v`), in 10.1 s; `local/.env`, the release and the image stay, and the next `make netbox-up` provisions the superuser's token again and replaces its line, and the next `make netbox-seed` makes the account's token again and replaces its line. It is stopped for every live, cluster or conformance run |
| `make nautobot-up` | The development Nautobot, the Compose project `fylgja-core-nautobot`: Nautobot `NAUTOBOT_VERSION` (3.2.8) with Golden Config `GOLDEN_CONFIG_VERSION` (3.0.8) on the image's Python `NAUTOBOT_PYTHON` (3.14), run by `scripts/nautobot_dev.py` against the main checkout's `local/`, from a worktree too. It adds to `local/.env` each of its five names ([`.env.example`](.env.example)) that the file does not hold, the three secrets and the superuser's token generated and never printed, and changes no line already there, since a database password or a key made again would not open the volumes a kept file made; a name the file holds with no value is refused, exit 2 and before anything is built or started, naming it. It makes `local/nautobot/git`, the directory the `git` service serves, builds the image `fylgja-core-nautobot:<Nautobot's>-<Golden Config's>-py<Python>` from `nautobot/dev/` (Network to Code's with one layer adding Golden Config by uv at its version, Nautobot named beside it so that no resolution moves it) and starts the project, whose Compose file publishes Nautobot on loopback at port 8810 and gives Nautobot and its worker no Docker health check, since the image's takes longer than its timeout and holds a core. It waits up to 1200 s from that start for `GET /health/` to answer 200, asked from the host and never of Docker, and then reads `/api/status/` with the superuser's token, `FYLGJA_NAUTOBOT_WRITE_TOKEN`, which the image takes, with the superuser's password, at every start, so that a line replaced is adopted. It is done once Nautobot names both versions and a running worker, within 60 s of `/health/`, and fails at once on another Nautobot, another Golden Config or none, which is how a `nautobot_config.py` not loaded shows; a token Nautobot refuses ends it, naming `make nautobot-down PURGE=1`, with no second try. The three versions and the two directories are set in Compose's environment over whatever the shell or `local/.env` holds, and Compose is given no other name beginning `FYLGJA_NAUTOBOT_`, so that it reads the secrets from `local/.env` alone. About twelve minutes on new volumes, 690.1 s and 723.0 s in two runs, and 112.1 s on kept ones, the image built from the cache. Needs Docker, and the network for the base image's first pull |
| `make nautobot-down` | Stops the development Nautobot (`docker compose stop --timeout 60`), in 5.9 s, read once, each container given 60 s to exit by itself and none killed: `git` runs under an init process and exits 143. Its containers, network and volume and everything under `local/nautobot/` are kept, port 8810 and the memory released, and `make nautobot-up` starts it again holding what it held. `PURGE=1`, and no other value of `PURGE`, removes the containers, the network and the volume (`down -v`), in 6.5 s; `local/.env`, `local/nautobot/git` and the image stay, and the next `make nautobot-up` starts an empty Nautobot that takes the same token and password. It is stopped for every live, cluster or conformance run |
| `make nautobot-seed` | The fixture network on the development Nautobot (`nautobot/seed/seed.py`), with the superuser's token, `FYLGJA_NAUTOBOT_WRITE_TOKEN`, and its templates in the repository the `git` service serves. First `nautobot/seed/templates/` is written as one tree into `local/nautobot/git/templates.git`, the bare repository made where it is absent, and committed onto its `main`, the repository then made servable over plain HTTP, only where that tree is not `main`'s, so that a template changed reaches Nautobot as a push and a second seed commits nothing. Then each object `nautobot/seed/main.yaml` says is found by its name, a device type by its model, an interface by its device and name, a prefix and an address by their values in the namespace `Global`, an address's assignment by the address and the interface, and a cable by its ends' rows, or made: the manufacturer `Nokia`, the platform `SR Linux` of network driver `nokia_srl`, the device type, the location type `Site` and the location `lab`, the role and the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json`, each `Active`, tagged and carrying the marker as its comments, since a Nautobot device has no description, with their fifteen ports, the six addresses on them in the prefixes they derive, and the fixture's three cables; then the configuration context `fylgja-probes`, inactive, whose data is `three-node-probed.json`'s probe `n1-loop`, the repository `fylgja-templates`, the `git` service's `templates.git` on its branch `main`, and the GraphQL query `fylgja-sotagg` from `nautobot/seed/sotagg.graphql`. Of an object found, the query's text, the repository's remote and branch, and the context's data and state are written again where they differ, and nothing else; a fixture port cabled elsewhere is left as it is. Golden Config's installed `Default Settings`, found by its slug `default`, is pointed at the repository, the path template `{{ obj.platform.network_driver }}.j2` and the query where it is not, and its dynamic group given the filter `{"tags": ["fylgja"]}` where it holds another; Nautobot stores a group's members, so the group is saved again with its filter where they are not the tagged devices, and refused, naming the group, where they still differ. Nautobot is then read back, the devices tagged `fylgja` with their platform, ports, addresses and cables, the setting, its group's filter and members, the repository, the query and the context, and each difference from the fixture said, exit 1 with `make nautobot-down PURGE=1`, since the seed deletes nothing. Last, each tagged device is rendered once by Golden Config with the superuser's token, which fetches the head the seed's commit moved, so that the first read after a seed is not refused for it, and each render is held to `three-node.json`'s configuration for the device, its first line aside, a difference exit 1 naming the device. One line an object, `made` or `found`, and one for the templates; a second seed writes nothing, to Nautobot or to the repository. 46.9 s on an empty Nautobot and 24.2 s on a seeded one, one run each. Then the reader's account (`nautobot/seed/account.py`): the user `fylgja-reader`, found or made, active, no superuser and named by no permission outside its own, each of its fourteen permissions, `view` alone, found by its name or made and brought by one `PATCH` to exactly its row and that one user (a type, an action, a constraint, `enabled` or a second user found otherwise), and its token's line `FYLGJA_NAUTOBOT_TOKEN` in `local/.env`, kept byte for byte where its key is the reader's own with writing disabled, read by that key through the thirteenth permission, else a token made by the account under HTTP Basic with a temporary `add` permission the run deletes, and the line replaced or appended, every other line kept, mode `0600`. It prints one line for each thing it made or set and never a value; Nautobot not answering leaves `local/.env` as it was. Load `local/.env` first, and again after |
| `make netbox-seed` | The fixture network on the development NetBox's `main` (`netbox/seed/seed.py`), with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`. Each object `netbox/seed/main.yaml` says is found on `main` by its name, a device type by its model, an interface by its device and name, an address by its value and interface and a cable by its first end, or made: the manufacturer `Nokia`, the configuration template `fylgja-srlinux` from `netbox/seed/template.j2`, the platform `SR Linux` naming both, the device type, the site `lab`, the role and the tag `fylgja`, the devices `n1`, `n2` and `n3` of `testdata/blueprint/three-node.json`, each `active` and tagged, with their fifteen ports and six addresses, the fixture's cables less the one between `n1` and `n3`, and last the configuration context `fylgja-probes`, inactive, whose data is `three-node-probed.json`'s probe `n1-loop`, so that no device's rendered context takes it. Of an object found, the template's code, the platform's template and the context's data and state are written again where they differ, and nothing else; a fixture port cabled to another port than the fixture's is refused, naming both, before any cable is made. `main` is then read back, the devices tagged `fylgja` with their platform, ports, addresses and cables, and each difference from the fixture said, such as the cable or the address a merged change left, exit 1 with `make netbox-down PURGE=1`, since the seed deletes nothing. One line an object, `made` or `found`; a second seed writes nothing. Then the reader's account (`netbox/seed/account.py`), `fylgja-reader`, with the superuser's token: its user found by its name or made, active and no superuser, its password generated, sent and kept nowhere, a user found holding a group or a permission of another name refused, naming each and `make netbox-down PURGE=1`, nothing removed; each of its grants found by its name or made, and brought by one `PATCH` to exactly its row where it holds another type, another action or another user: `view` of the nine types a read lists and `view` with `render_config` on `dcim.device`; and its token's line, `FYLGJA_NETBOX_TOKEN`, kept byte for byte where NetBox holds exactly one token of its key and that one the account's, else a token made by the superuser and the line appended, or put in place of the last line that holds its name, as after a purge, every other line kept and the file left at mode `0600`. A replaced token is not revoked. It prints what it made, set or replaced and never a value, and NetBox not answering leaves the file as it was. A failure names the remedy for what failed: the purge, then `make netbox-up`, `local/.env` loaded again and `make netbox-seed`, only where NetBox holds what neither removes, a difference from the fixture or an account's stray; `make netbox-up` where NetBox does not answer; and `local/.env` loaded again where NetBox refuses the write token, as after a purge, then `make netbox-up`, which provisions a refused token again without a purge, the purge named only as what remains. NetBox answering two rows to a lookup of one, or a token as another user's, names none. It took 29 s wall on an empty `main` after a purge and 19 s on the seeded one, one run each on 2026-11-21. An instance seeded before 1.1.0 keeps the `fylgja-orchestrator` account, so purge it once: `make netbox-down PURGE=1`. Load `local/.env` first, and again after it for the line |
| `make contract-netbox` | The NetBox contract tier (below), `netbox/tests/contract/`, against the running development NetBox, seeded, with `local/.env` loaded after `make netbox-seed` for `FYLGJA_NETBOX_ADDRESS`, `FYLGJA_NETBOX_WRITE_TOKEN` and the account's token, `FYLGJA_NETBOX_TOKEN`; it seeds `main` first, as `make netbox-seed` does: 13 tests. Then the NetBox reader's tier, `readers/netbox/tests/contract/`, the reader given `FYLGJA_NETBOX_TOKEN` and, for an `https://` address, `FYLGJA_NETBOX_CA`, never the write token: 45 tests. Run whole once on 2026-11-21, `netbox/`'s 13 took 125.23 s and the reader's 45 591.11 s |
| `make contract-nautobot` | The Nautobot contract tier (below), `nautobot/tests/contract/`, against the running development Nautobot, with `local/.env` loaded for `FYLGJA_NAUTOBOT_ADDRESS` and the superuser's token, `FYLGJA_NAUTOBOT_WRITE_TOKEN`: 15 tests, of `nautobot/seed/box.py`, of the seed, which commits the templates and seeds Nautobot first, as `make nautobot-seed` does, and of the reader's account, which reads with `FYLGJA_NAUTOBOT_TOKEN` as well. A test that writes names its objects `fylgja-contract-<8 hex>` and deletes them whatever it did, and the session's start deletes every tag so named; the seed's objects are never touched, and a template a test pushes is pushed back and each device rendered after, so that the repository's head is the tracked templates' again. It then runs the reader's tier, `readers/nautobot/tests/contract/`, 41 tests that provoke on the real Nautobot each rule the reader files (a Nautobot without Golden Config, a list cut short, a device with no platform or named twice, a cable left out, a template that is missing or raises, a render refused, an edit or a push between two renders) and read one state twice, writing under the names above and deleting what they made: the two tiers took 515.8 s and 512.7 s in two runs on 2026-11-20 (`nautobot/` 15 tests in about 119 s, the reader's 41 in about 390 s) |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures, and the store, the object store over a fake S3 endpoint, the reconcile loop, API 1 and the CLI over fakes of the runtime; and, under `infrahub/tests/`, what `infrahub/` gives Infrahub, read as files (the schema library at its commit, the registration with its query and its template, the Compose override, the seed's object files, `main`'s and the seeded branch's two stages, against the fixture, and the reader document), the names and addresses of the tracked tree, the development Infrahub's script over fakes of Compose, the fetch and the clock, and `infrahub/seed/`'s transport, registration and seed over fakes of Infrahub, `infrahubctl`, the reader's `head` and the clock; under `netbox/tests/`, what `netbox/` gives NetBox, read as files (the image's one layer, the Compose override and the plugin's configuration, and the seed's fixture, its probes' context, its template and its reader document, against the blueprints and the package), the names and addresses of `netbox/` and `scripts/netbox_dev.py` and `.env.example`'s NetBox names, the development NetBox's script over fakes of Compose, the fetch, NetBox and the clock, and `netbox/seed/`'s transport over a fake of NetBox's HTTP (each path under `/api/` with the bearer and a branch's header, every page of a list held to its `count`, a name that matches twice refused, a row found before one is made, a branch made once and waited for until `ready`, a branch answered for another name refused, the request timeout, a query's `None` refused, and the token kept out of every error) and its seed over a fake of NetBox's REST API (everything made once, each after the objects its body names, a second seed writing nothing, the template's code, the platform's template and the context written again where they differ and nothing else, a fixture port cabled elsewhere refused before any cable is made, a `main` that is not the fixture refused naming each difference, a variable not set, and the token kept out of everything printed), and its account over the same fake (the account, its grants and its token made on a first run and the line appended, every other line kept and the file at mode `0600`; a line NetBox still takes kept byte for byte and nothing sent but reads; a dead line, one that is no token and one of another user's replaced where it stood, the last where a name is held twice; a grant wider than its row brought back by one `PATCH`; a user found inactive set active; a superuser, a group or a permission of another name refused naming it, with nothing written; NetBox not answering at any request leaving the file as it was; and no token and no password in anything printed or raised, a password or a line's key echoed across the cut of NetBox's words among them), and the NetBox contract tier's branches, its fixtures' own functions over a fake of NetBox's branches (a branch deleted whatever its test did, also where it never read `ready`, and the session's sweep deleting the tier's own branches and no other, waiting for one still provisioning by reading it and never making one, and the writer's `repr` holding no address); under `readers/infrahub/tests/`, what the reader's modules import, its rows with the rule that every list is whole, over rows built in the tests, its reader document, loaded from files and refused by its rules, its times, its GraphQL documents, its transport over a fake of Infrahub's HTTP (the version, the branch's path and `at`, the pager, the event log's pager down to its floor, an artifact's content by its storage id alone, the refusals with their statuses, a stamp that is no time, and the token kept out of every error), its schema check, each difference from its table its rule, over the table's own kinds as rows, and its mapping, each device's configuration from its artifact and the read with its source envelope, over rows built in the tests (the fixture's network and id, one document whatever order the rows come in, the forms judged before anything is sent, and each omission, refusal and fault of an artifact its rule, every device at fault in one pass), and its stale rule and `head`, over rows built in the tests (each node a configuration renders from moving its devices alone, the task workers' restamp discounted and `__system__` never, the events that show what no stamp does, `generated_since`, and the first instant after the latest write, every stamp and event counted, a probe's among them where the branch has the kind); and its probes, the kind's file against blueprint 1's patterns and its probes over rows built in the tests (the probed fixture's id, read only where the document asks, the kind absent, a probe of another scope omitted, a renamed device, each fault of the declaration its rule, a null attribute among them, and a list not whole); and its command over a fake of `connect` and the environment (each exit, what each stream holds, the token in neither), and its README's versions and `mapping.md`'s members held to the code; and the NetBox contract tier's judgments of its branches over a fake; and under `readers/netbox/tests/`, the NetBox reader: what its modules import, its rows with the rule that every list is whole, over rows built in the tests (a list short of its `count` or longer than it, one object twice, and an id asked for and not answered), its transport over a fake of NetBox's HTTP (both versions and the warning outside those verified, the token as a bearer and a branch by its `schema_id`, every page of a list read to the largest `count` NetBox answered and never by its `next`, ids asked fifty a request and their counts summed, each row held to what was asked and to the members it needs, a refusal's status kept with the branch, its body read as JSON only where NetBox says it is, a redirect named by its path alone, and the token kept out of every error, `repr` and log line), the requests it sends, read from its source (each a `GET` but the render's `POST`, through one sender, none by any other of httpx's senders, and no path of NetBox's named in another module), its reader document, loaded from files and refused by its rules; its mapping over rows built in the tests (the fixture's network, one network whatever order the rows come in, a cable's sides swapped among them, a name made a label, two devices of one label each refused, a device with no package refused, and each omission of a cable its rule, every finding in one pass); its bracket (an edit, a row written below the open's id, a sync, a branch gone or no longer `ready`, and a 400 to the close's own requests under a branch's header, each `read.moved`, the rows no read reads refusing nothing, and the changelog or the branches' list short of its `count` `read.incomplete`); its renders, each answer `render-config` can give its rule, no byte of a configuration quoted; the read and its source envelope over a fake source (the fixture's id, the bracket opened before the first list and closed on every path past it, a 400 weighed at the close, every scoped device rendered and every fault filed in one pass, the scope's and the branch's refusals before anything is sent, and the same rows in any order one document); its probes, the seeded context's declaration read inside the bracket, a probe of another scope omitted, a renamed device followed and each fault of the declaration its rule; its command over a fake of `connect` and the environment (each exit, what each stream holds, the token and its halves in neither, and `--out` written whole or not at all); its contract tier's branches, its fixtures' own functions over a fake of NetBox's branches (a branch deleted whatever its test did, also where it never read `ready`, and the session's sweep deleting the tier's own branches and no other, waiting for one still provisioning by reading it and never making one, one gone before its `DELETE` not reported, and one `failed` deleted or named); the names and signatures it exports for what consumes it, and those its consumers are typed against beside them; its rule catalogue held to the code; and its README's versions and upgrade table and `mapping.md`'s members held to the code and the facts; under `nautobot/tests/`, what `nautobot/` gives Nautobot, read as files (the fixture's network, the probes' context, the query and the template, against the blueprints and the package, and the reader document), the names and addresses of `nautobot/` and `scripts/nautobot_dev.py`, the development Nautobot's script over fakes of Compose, the health check and the clock, and `nautobot/seed/`'s transport, seed and reader's account over fakes of Nautobot's REST API, of git and of `local/.env`, with no token and no password in anything printed or raised; and under `readers/nautobot/tests/`, the Nautobot reader: what its modules import, and the requests it sends, read from its source (each a `GET` through one sender, none naming `branch`), its rows with the rule that every list is whole, its transport over a fake of Nautobot's HTTP, its reader document, its mapping over rows built in the tests, its bracket (`read.moved`), each answer Golden Config's render can give its rule, its dynamic groups held to their filters, its probes, the read with its source envelope over a fake source, its command over a fake of `connect` and the environment, its rule catalogue held to the code, and its README's versions and `mapping.md`'s members held to the code and the facts |
| **Live** | Booted images on the local containerlab driver, and Versity S3 Gateway under Docker | On demand: `make live`, with `local/.env` loaded: the driver's own modules under `core/tests/live/` (the driver, `changes` against containerlab's dry run, readiness and the push, verify over gNMI, the trigger and the restore through Docker's restart paths, and the object store against the gateway), then the conformance suite on the local harness. 168 tests by collection; about 62 minutes whole, with the cluster quiet. Never while the cluster runs the suite or the cluster tier: here the two share a hypervisor, and SR Linux segfaults under the contention. `make test` deselects it (the `live` marker) |
| **Cluster** | The k3s cluster, reached from the development host | On demand: `make cluster`, with `local/.env` loaded and `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE` and `FYLGJA_POD_CIDR` set: the clabernetes driver's calls on the cluster, its reach into Kubernetes first (`core/tests/cluster/test_kube_cluster.py`), then the driver's calls and `changes` held to the pods' uids (`core/tests/cluster/test_clabernetes_driver_cluster.py`, `core/tests/cluster/test_clabernetes_changes_cluster.py`), the trigger and the restore through the loop (`core/tests/cluster/test_restore_cluster.py`), the Lease (`core/tests/cluster/test_lease_cluster.py`), and the driver's reading of the cluster's room, with no twin up and with a two-node twin admitted and applied (`core/tests/cluster/test_capacity_cluster.py`). 44 tests by collection; about 35 minutes whole. Each test twin has its own namespace, deleted at its module's end; never while `make live` runs. `make test` deselects it (the `cluster` marker) |
| **Driver conformance** | Each driver's own runtime: for the local driver, containerlab and Docker on the development host; for clabernetes, the core deployed on the cluster with `FYLGJA_RESYNC_S` of 3600 or more, a token of the suite's own principal, both node logins and the cEOS pull credential, reached from the development host ([Running the core on a cluster](#running-the-core-on-a-cluster)) | On demand, per driver: `make conformance DRIVER=containerlab`, 54 tests in about 36 minutes, which `make live` runs too; and `make conformance DRIVER=clabernetes`, 54 tests in about 68 minutes. Each was measured with the other runtime quiet, and the two are never run together here: they share a hypervisor. Each runtime needs the many-twins scenario's band of room: about 4.5 CPU and 17 GiB free locally and 7.5 CPU and 28 GiB on the cluster, and under about 80 GiB free on either with its twins up, so that its forty-node twin is refused. `make test` deselects the suite (its harness's marker, `live` or `cluster`) |
| **Contract** | The development Infrahub, up and registered (`make infrahub-up`, `make infrahub-register`), reached at `FYLGJA_INFRAHUB_ADDRESS` with the writer's token, `FYLGJA_INFRAHUB_WRITE_TOKEN`, and the reader's, `FYLGJA_INFRAHUB_TOKEN`, which the seed's `head` reads with; for the reader's, seeded too (`make infrahub-seed`, which `infrahub/tests/contract/` runs again) | On demand: `make contract`, with `local/.env` loaded; it sets `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` on its own command lines. `infrahub/tests/contract/`: the library, the group and the registration as `main` holds them, and a second registration that changes nothing; then the seed run whole, as `make infrahub-seed` runs it, the reader's kind passed and each stage timed by the reader's `head`, writing `seed.json` where `FYLGJA_INFRAHUB_SEED` names it: `main` left the fixture less one link, `seed.json`'s branch, scope and two stages in order, the branch read at each stage's time with its cables, its addresses and its configurations, each `Ready` with its bytes the fixture's, then the fixture's with `n1`'s address, and a second seed that gives the same network at later times and leaves `main` as it was. Then the reader's, `readers/infrahub/tests/contract/`, with the reader's token, and a writer of its own with the admin's, which the reader is never given, writing only on a branch `fylgja-contract-<8 hex>` it makes from `main` and deletes after, the session's start deleting any that a stopped run left: Infrahub's version read; a branch Infrahub lacks refused with 404, its error naming the branch, and an `at` before the branch with 422 and a malformed one with 400, each naming the branch and the time; a wrong token refused with 401 at the connect, naming `FYLGJA_INFRAHUB_TOKEN`; none of them holding the token; the seeded `main`'s devices and ports read as rows at the first stage's time, every list whole; 120 ports of one device read in two pages; the seeded `main`'s schema held to the schema check's table, nothing differing; and the fixture read into blueprints, `main` and the seeded branch at the first stage's time, the branch's blueprint id the probed fixture's (`three-node-probed.json`), the seed's probe among it, each stage's configurations their artifacts' bytes, a past time read as it stood after a later one, and a scope no device carries empty; and the stale rule and `head`: each stage of the seeded branch read with no stale configuration, and read twice to one id; an address of `n1`'s edited on a branch of the writer's, refusing `n1` alone as stale at `head` until a regeneration the writer asks, and then a port of `n1`'s renamed, refusing `n1` and `n2`, at the cable's far end, and not `n3`; and the seeded branch read at `head` giving its last stage's blueprint id; and the probes: the seed's `n1-loop` alone in each stage's blueprint, and a probe of the tier's own, made through its branch and its gateway changed, read through that branch a microsecond after each write as it stood then, under one id, counted by `head`, and omitted from the read, its devices in no scope. The kind being branch-agnostic, that probe is on every branch while the test runs, and deleted at its end; the session's start deletes any `fc-*` probe a stopped run left. Then each refusal. Provoked by the writer on a branch of its own and read at its `head`: a device made in the scope with no artifact, `artifact.missing` for it alone; an artifact's status written `Pending`, `artifact.unready`, and its checksum written as zeros, `artifact.checksum.mismatch`; a device's serial number, which the template does not render, written, `artifact.stale`, and the same read with a `generated_since` of that `head` giving the configuration as it was; and a cable added and regenerated, then its ends taken off it, `artifact.stale` for its two devices by the cable's event alone. Made in flight, by a transport of the test's own that alters a real answer, where the writer may not write it or Infrahub never answers it: a branch of the writer's whose schema is answered without `DcimCable.label`, which a load may not remove, `schema.field.missing` from `check_schema` and `read`, `main` conforming; and `main` read at its `head` with each answer of the ports cut by an edge, `read.incomplete`. And `main` read at its `head` with a reader document naming no device's platform, `platform.unmatched` for each. Then the command, `fylgja-infrahub`, run as a process of its own with the reader's variables alone: `read` of the first stage writing the library's blueprint, `schema-check` of `main`, `head`, and a scope no device carries exiting 1. Last, every request the reader's connections sent held to reads: a `GET`, or a `POST` to `/graphql/` of a `query`. The library's 6 tests took 236.47 s and the reader's 30 tests 461.28 s, one run on 2026-11-21. Without its variables a test is skipped, and fails when `CI` is set. `make test` deselects it (the `contract` marker) |
| **Contract (NetBox)** | The development NetBox, up and seeded (`make netbox-up`, `make netbox-seed`), reached at `FYLGJA_NETBOX_ADDRESS` with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`, and the account's token, `FYLGJA_NETBOX_TOKEN` | On demand: `make contract-netbox`, with `local/.env` loaded after `make netbox-seed`. `netbox/tests/contract/`: the account, `netbox/seed/account.py`: the reader's token reading the three devices tagged `fylgja`, their ports and cables, the platform with its manufacturer, the tag, the probes' context by its name and `main`'s changelog, and rendering `n1` to the superuser's bytes, on `main` and under a branch of the test's own, which it finds by its name; refused 403 a site's create, a journal entry and a `DELETE` of `n1`, each under the branch's header so that one wrongly taken lands on the branch alone, and a `PATCH` of the branch's tags, neither changelog moving; and the account made again over the line the environment gives, nothing made, the file's bytes unmoved and its count of tokens what it was; the seed's transport, `netbox/seed/box.py`: `/api/status/` naming NetBox's version and the branching plugin's; NetBox's object types listed in pages of 50, as many rows as the `count` it answers, each id once; a branch of the test's own, `fylgja-contract-<8 hex>`, made and read until `ready`, its `schema_id` of eight characters, and a site made under its header found there and not on `main`; and a token of NetBox's v2 shape that NetBox never made, refused with 403 and `Invalid v2 token`, the error holding no part of it, the last of these reading that the tests run before it, the account's and the transport's, left no branch, which the pure tier's `netbox/tests/test_contract_branches.py` holds as a rule; and the seed, `netbox/seed/seed.py`, which seeds `main` first: `main` holding the fixture, three devices tagged `fylgja`, fifteen ports with `mgmt_only` on each `mgmt0` alone, six addresses and the two cables, with no difference; each device's configuration as NetBox renders it, `testdata/blueprint/three-node.json`'s line for line after the first but the far end of the link `main` lacks; on a branch of the test's own, the change's two steps, the cable between `n1` and `n3` moving their configurations to the blueprint's and the address `192.0.2.1/24` on `n1`'s end adding its two lines to `n1`'s, `n2`'s and `main`'s renders unmoved; the probes' context, inactive, by its name, in no device's `config_context`; and a second seed, finding everything and adding no row to `main`'s changelog. Each branch is deleted at its test's end whatever the test did, and the session's start deletes any that a stopped run left, so that `main` stays as the seed left it. 13 tests, in 125.23 s, one run on 2026-11-21. `readers/netbox/tests/contract/`, the NetBox reader's, run after it: its transport with the reader's token, `FYLGJA_NETBOX_TOKEN`, never the write token, verified against `FYLGJA_NETBOX_CA` where the address is `https://`: NetBox's version and the branching plugin's, the warning given exactly where the pair is not one the reader was verified on; a token of NetBox's v2 shape that NetBox never made refused at the connect with 403, the error naming `FYLGJA_NETBOX_TOKEN` and holding no part of the token; the fixture's tag, its three devices, their platform `SR Linux` of `Nokia`, their fifteen ports with `mgmt_only` on each `mgmt0` alone and their two cables, each of one interface end a side, every list whole; a branch of the test's own found by its name, `ready`, and a port disabled under its header read so there and enabled on `main`; and 120 interfaces made on that branch read whole in two pages. Then the read of `main` and of a branch into the fixture's devices, links and configurations; the bracket, as an edit, a journal entry, a render, a sync, a merge and a branch deleted move the changelogs and the branch; the probes' context; each rule of `readers/netbox/rules.md` provoked on purpose, on a branch of the test's own, or in flight, an answer altered on its way to the reader, where NetBox cannot be written into ([readers/netbox/README.md](readers/netbox/README.md#supported-netbox-versions)), an edit, a journal entry, the branch's delete and its sync made as a read's first render passes among them, the entry refusing nothing and each of the others the read; the same state read twice to one id, on `main` and on a branch; the command `fylgja-netbox` run as a process with the reader's variables and not the write token; and, last of the session, every request each of the reader's connections sent, `GET`s and renders alone. Its writes are `netbox/seed/box.py`'s `Box`'s with the superuser's token, under the header of the test's own branch, but for three tests whose tag of the tier's naming reaches `main`, made there in two and merged there in the third, and two that write a journal entry on the test's branch object, which `main` holds, each deleted in a `finally`. 45 tests, in 591.11 s, one run on 2026-11-21, after `netbox/`'s 13. Without its variables a test is skipped, and fails when `CI` is set. `make test` deselects it (the `contract_netbox` marker) |
| **Contract (Nautobot)** | The development Nautobot, up (`make nautobot-up`) and seeded (`make nautobot-seed`), reached at `FYLGJA_NAUTOBOT_ADDRESS` with the superuser's token, `FYLGJA_NAUTOBOT_WRITE_TOKEN`, and the reader's, `FYLGJA_NAUTOBOT_TOKEN` | On demand: `make contract-nautobot`, with `local/.env` loaded. It holds the transport's tests, `nautobot/tests/contract/test_box_contract.py`: the status naming Nautobot and Golden Config, a list read to its count over more than one page, a tag made and found once, and a refused token as a `BoxError` of 403 holding no part of it; and the seed's, `test_seed_contract.py`: a render after `make nautobot-seed`'s run moving no head and adding no changelog row, the fixture whole, each device's render `three-node.json`'s configuration after its first line, the probes' context inactive and in no render, a template pushed rendered at the next render, and a second seed writing nothing; and `test_account_contract.py`: the reader's token reading each list the superuser's does to its count, its render of each device the superuser's byte for byte, its create, change and delete each 403 with the changelog's count unmoved, and the account run again keeping its token. The reader's tier, `readers/nautobot/tests/contract/` (`make contract-nautobot` runs it after the transport's), holds the 41 tests of the reader: its reads, refusals, groups, probes, a read moved by a write between two renders, its command line and the transport's bound, each against this Nautobot. Without the variables a test is skipped, and fails where `CI` is set |

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
| `netbox/seed/` | The fixture network `make netbox-seed` puts on the development NetBox's `main`, as one file, `main.yaml`: `testdata/blueprint/three-node.json`'s devices, ports, addresses and cables less the link between `n1` and `n3`, and `three-node-probed.json`'s probe `n1-loop` as the data of the configuration context `fylgja-probes`; `template.j2`, the configuration template NetBox renders each device with, whose text is `three-node.json`'s for the device but its first line; `reader.yaml`, the reader document that maps the fixture's manufacturer and platform to the package `nokia_srlinux` and names the probes' context; and `account.py`, the reader's account at its least grants with its token's line |
| `nautobot/seed/` | The fixture network `make nautobot-seed` puts on the development Nautobot, as one file, `main.yaml`: `testdata/blueprint/three-node.json`'s devices, ports, addresses and cables whole, and `three-node-probed.json`'s probe `n1-loop` as the data of the configuration context `fylgja-probes`, with the templates' repository, the query's name and the setting's slug, path template and filter; `templates/nokia_srl.j2`, the template Golden Config renders each device with, over the names of the query `sotagg.graphql` alone, whose text is `three-node.json`'s for the device but its first line; `reader.yaml`, the reader document that maps the fixture's manufacturer and platform to the package `nokia_srlinux` and names the probes' context; and `account.py`, the reader's account at its least grants with its token's line |

## Local environment

**uv** reads its own configuration (`~/.config/uv/uv.toml`, the `UV_*` variables). An index set there is written into `uv.lock` by `uv lock` and refused by the tree's test, so a lock is written against PyPI alone. That was not read with an index set (design/verified-facts.md, "uv 0.12.23", "Not read"): it follows from the tree's test, which names the host of any address that is not PyPI's.

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

**The Nautobot reader's command**, `fylgja-nautobot`, which `make venv` installs as
`core/.venv/bin/fylgja-nautobot`, reads `FYLGJA_NAUTOBOT_ADDRESS`, `FYLGJA_NAUTOBOT_TOKEN` and, where
it is set, `FYLGJA_NAUTOBOT_CA`, never a flag, and prints no token
([readers/nautobot/README.md](readers/nautobot/README.md#the-command)). Against the development
Nautobot, seeded, with `local/.env` loaded after `make nautobot-seed`, which writes the reader's
token, the tagged devices are read into a file under `local/`; Nautobot has no branch to name:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-nautobot check
core/.venv/bin/fylgja-nautobot read --scope tag:fylgja --reader nautobot/seed/reader.yaml \
  --out local/nautobot.json
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

How to run the server, its settings, its token file and its exit statuses are in
[`docs/server.md`](docs/server.md), and the `fylgja-core` command that talks to it is in
[`docs/cli.md`](docs/cli.md). What is a contributor's alone is here. Every setting is a variable
of the process's environment, listed also in [`.env.example`](.env.example), and a change that adds
one adds its row to the settings table in `docs/server.md`, which a test holds to every variable
`config.from_environ` reads.

On the development host the environment is `local/.env`, loaded in the shell that starts the
server, and the commands are the ones in `core/.venv/bin/`:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-core-server
```

`python -m fylgja_core.server` runs the same `main` beside the console script. It has no SIGTERM
handler until `main` installs its own, so it is for the development host, where the server is not
PID 1; the console script has one within 0.2 s of the process's start, and the server's module
docstring says why and names the three windows that are left. The CLI is
`core/.venv/bin/fylgja-core`, run in a shell that has loaded `local/.env` and set
`FYLGJA_API_ADDRESS` to the server's listen address.

The commands the local driver runs, `containerlab` and `docker`, get `DOCKER_HOST` and `PATH`
from the server's environment and nothing else ([D-065](design/decisions.md#d-065)); a variable
containerlab should see is added to `ALLOWED_ENV` by a change, with its reason.

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
`make netbox-seed` writes the account's token into it, so the file is loaded after each:

```sh
make netbox-up            # the project started, its secrets and the superuser's token in local/.env
set -a; . local/.env; set +a
make netbox-seed          # the fixture network on main, and the reader's account with its token's line
set -a; . local/.env; set +a
make contract-netbox      # the NetBox contract tier against it
```

- The seed and the contract tier write with the superuser's token, `FYLGJA_NETBOX_WRITE_TOKEN`.
  The reader runs under an account of its own, no superuser, granted the least read on the running
  instance for what it does (`GRANTS` in `netbox/seed/account.py`). `fylgja-reader`'s token,
  `FYLGJA_NETBOX_TOKEN`, has `view` of what a read lists and a render's `render_config` on
  devices: it reads and renders, on `main` and under a branch, and writes nothing.
- `make netbox-down` stops it, keeping its containers, network and volumes and everything under
  `local/netbox/`, so that `make netbox-up` starts it again holding what it held.
  `make netbox-down PURGE=1` removes the containers, the network and the volumes; `local/.env`,
  the fetched release and the image stay, and the next start is an empty NetBox, to seed again.
  The three tokens `local/.env` holds are then dead: the next `make netbox-up` provisions the
  superuser's again and replaces its line, and the next `make netbox-seed` makes the account
  and its token again and replaces its line, every other line kept.
- The project's network is a documentation range, 198.51.100.0/24, named in
  `netbox/dev/compose.override.yml`, so that it never meets the local driver's default lab pool, from which
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

## The development Nautobot

One Nautobot at stated versions runs on the development host as the Compose project
`fylgja-core-nautobot` ([D-119](design/decisions.md#d-119)), behind the make targets above: Nautobot
`NAUTOBOT_VERSION` with Golden Config `GOLDEN_CONFIG_VERSION`, on the image's Python `NAUTOBOT_PYTHON`.
It is brought up and seeded in this order. `make nautobot-up` needs none of `local/.env`'s names in
the shell, and writes the names the others read into it, and `make nautobot-seed` writes the reader's
token into it, so the file is loaded after each:

```sh
make nautobot-up          # the project started, its secrets and the superuser's token in local/.env
set -a; . local/.env; set +a
make nautobot-seed        # the fixture network, its templates, the setting, and the reader's account and token's line
set -a; . local/.env; set +a
make contract-nautobot    # the Nautobot contract tier against it
```

- The seed and the contract tier write with the superuser's token, `FYLGJA_NAUTOBOT_WRITE_TOKEN`, which
  the image takes, with the superuser's password, at every start, so that a line replaced is adopted.
  The reader runs under an account of its own, `fylgja-reader`, no superuser, with the least grants read on
  the running instance (`GRANTS` in `nautobot/seed/account.py`): `view` on twelve types and no other action,
  each one permission, because Golden Config runs the setting's query under the rendering account's grants,
  and an account that cannot see a device's interfaces, platform, manufacturer or addresses is answered a
  render of 200 without them ([D-118](design/decisions.md#d-118)); a thirteenth, `view` on its own tokens
  alone, with which a kept line's key is read back as the reader's and write-disabled; and a fourteenth,
  `view` on `extras.staticgroupassociation`, the stored members of a setting's dynamic group, which the
  reader holds to the group's filter. Its token,
  `FYLGJA_NAUTOBOT_TOKEN`, has writing disabled: it reads and renders, and its creates, changes and deletes
  are each 403. A render of its own writes one changelog row under the account where the repository moved,
  the head it fetches, which no grant is asked for. The token is made by the account itself, since a token
  Nautobot makes is always the requester's: the superuser sets a password on it, generated and kept nowhere,
  grants it `add` on its own tokens for the one request, and deletes that grant at once.
  A line is kept byte for byte while Nautobot takes it, as the reader's and write-disabled, and replaced
  where it does not, every other line kept.
- `make nautobot-down` stops it, keeping its containers, network and volume and everything under
  `local/nautobot/`, so that `make nautobot-up` starts it again holding what it held.
  `make nautobot-down PURGE=1` removes the containers, the network and the volume; `local/.env`,
  `local/nautobot/git` and the image stay, and the next start is an empty Nautobot, to seed again, that takes
  the same superuser token and password. The reader's token is then dead: the next `make nautobot-seed` makes
  the account and its token again and replaces the line.
- A first start on new volumes is about twelve minutes, most of it Nautobot's migrations: 690.1 s and
  723.0 s in two runs, and 112.1 s on kept volumes. Idle, the stack held about 2.2 GiB of the host's memory, the sum of
  one sample's five readings, the worker's 1.78 GiB of it (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8").
- It may stay up beside a twin: its network is the documentation range 203.0.113.0/24, named in
  `nautobot/dev/compose.yml`, off the local driver's lab pool, from which each twin's lab takes its subnet,
  and only Nautobot publishes a port, on loopback at 8810. It is stopped (`make nautobot-down`) for every
  live, cluster or conformance run all the same, for its memory.
- An upgrade is [D-119](design/decisions.md#d-119)'s procedure, by the three make variables
  `NAUTOBOT_VERSION`, `GOLDEN_CONFIG_VERSION` and `NAUTOBOT_PYTHON`: start the new versions on new
  volumes, seed them, run the contract tier, read again the recorded facts the code leans on, and extend
  the list of the versions it passed on.

## Running the example orchestrator

The example orchestrator is not in this repository: it moved to
[`fylgja-examples`](https://github.com/happypathnetworking/fylgja-examples/tree/v1.1.0/)
([D-126](design/decisions.md#d-126)), which runs it against the released
packages of this one. Its edge, the Prefect server and the runner, the accounts it holds in each
source and the lines of
`local/.env` that are its own are set up in that repository's
[CONTRIBUTING.md](https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/CONTRIBUTING.md#running-the-example-orchestrator)
at the tag `v1.1.0`, which says what
each of its make targets does. What this repository gives it is the development sources, each behind
the targets above.

## The demonstrations

The demonstrations, `make infrahub-demo` and `make netbox-demo`, are `fylgja-examples`' too: its
[CONTRIBUTING.md](https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/CONTRIBUTING.md#the-demonstrations)
at the tag `v1.1.0` holds what only a contributor
needs of them. [docs/demonstrations.md](docs/demonstrations.md) says where they went and links their
page for a user.

## The acceptance run

An acceptance run is a phase's own gate, which the maintainer watches. For a change source, it is a change rehearsed
on a twin from where the source starts the rehearsal, its report read where that source files it, once with each
core: on the local driver, and deployed on the cluster. For a reader with no change source, it is a twin made from what
the reader reads, on the local driver. The one written here, From the Nautobot reader, has every
command in order, how its end is read and the block that says the maintainer can be asked; the
others are pointers to `fylgja-examples`:

- [Through Infrahub's check](#through-infrahubs-check) and [Through NetBox's
  tag](#through-netboxs-tag), the change
  sources' runs, are made on the example, which is in `fylgja-examples`.
- [From the Nautobot reader](#from-the-nautobot-reader): the seed read by `fylgja-nautobot`, a twin of it created,
  verified and destroyed on the local driver.

No two of them run at once: each is a live run of its own, one at a time on the host and on the
cluster. A release's
demonstrations, the two runs of a change of a source of truth on a twin, are made in
`fylgja-examples`, at its tag.

### Through Infrahub's check

A proposed change of the seeded branch rehearsed through Infrahub's own check `fylgja-twin` is a run
of the example,
and its runbook is `fylgja-examples`'
[CONTRIBUTING.md](https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/CONTRIBUTING.md#through-infrahubs-check)
at the tag `v1.1.0`.

### Through NetBox's tag

A branch built in the development NetBox in steps, each marked, then given its tag and rehearsed
through NetBox's own
webhook, is a run of the example, and its runbook is `fylgja-examples`'
[CONTRIBUTING.md](https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/CONTRIBUTING.md#through-netboxs-tag)
at the tag `v1.1.0`.

### From the Nautobot reader

Phase 11 is done when the maintainer has watched this: on the development host, `fylgja-nautobot` reads the development
Nautobot's seed into a blueprint; the core, on the local driver, creates a twin of it; verify passes on that twin; and
the twin is destroyed
([core.md](design/core.md#phase-11-the-nautobot-reader-settled-2026-11-19)). The maintainer runs the commands, or the
controller shows each command's whole output before the next. This is that run: every command in order, from a host with
nothing of Fylgja's running to the twin destroyed, how each one's end is read, and the block that says the maintainer can
be asked. It follows [The development Nautobot](#the-development-nautobot), which says what each target does and who
holds which token, and the reader's command
([readers/nautobot/README.md](readers/nautobot/README.md#the-command)). There is no change source here and no
orchestrator: the core is given the blueprint by the CLI, on the local driver alone.

- **Where.** Every command here runs with the main checkout as its working directory, detached at the head of the
  branch under test with `make venv` run there, so that `core/.venv` holds `readers/nautobot`: `local/` is there alone,
  and the core runs that checkout's code. The make targets resolve `local/` to the main checkout from a worktree too,
  but the core, the CLI and the block below name `local/` from the working directory. Once the run is over, the main
  checkout is checked out again on the branch it was on.
- **Alone.** While it runs nothing else live runs on the host: no `make live`, `make cluster`, conformance run or
  contract tier; the development Infrahub and the development NetBox are stopped (`make infrahub-down`,
  `make netbox-down`), their volumes kept; no twin on the local
  core and no containerlab container on the host. Nautobot's network is off the lab pool, so it stays up between runs
  and beside the twin.
- **Credentials.** `set -a; . local/.env; set +a` in the same command as what needs it. No token or password is put on
  a command line, printed or written: a request reads its token from the environment inside the process that sends it.
  The blueprint holds every device's configuration: it stays under `local/` and is never quoted beyond its id and its
  counts.
- **Output.** Each run's output goes under the main checkout's `local/phase-<n>/acceptance/<run>/`, `<n>` the phase the
  run is made for, which the caller sets as `out` and which the preamble makes, as the readiness block makes it too where it is absent. Each command below runs
  after this preamble, in the same command, and is saved whole, with its exit status and its duration by the host's
  clock, and then shown whole before the next is run. `rec` writes `$out/<name>.txt` anew each time, so a command run
  again by mistake overwrites the first one's file; one repeated is saved under another name:

  ```bash
  set -a; . local/.env; set +a
  out=local/phase-<n>/acceptance/<run>
  mkdir -p "$out"
  TIMEFORMAT='real %R s'
  rec() {  # rec <name> <command ...>: its output, its duration and its exit status in $out/<name>.txt, then shown
    local name=$1 status; shift
    { time "$@"; } > "$out/$name.txt" 2>&1; status=$?
    echo "exit $status" >> "$out/$name.txt"; cat "$out/$name.txt"; return "$status"
  }
  nlog() {  # nlog <label>: the changelog's count and newest row, as the reader's token reads them, in $out
    core/.venv/bin/python -I -c '
  import json, os, sys, httpx
  answer = httpx.get(os.environ["FYLGJA_NAUTOBOT_ADDRESS"].rstrip("/") + "/api/extras/object-changes/?limit=1",
                     headers={"Authorization": "Token " + os.environ["FYLGJA_NAUTOBOT_TOKEN"]}, timeout=60)
  body = answer.json() if answer.status_code == 200 else sys.exit("the changelog answered HTTP %d" % answer.status_code)
  rows = body["results"]
  print(json.dumps({"count": body["count"], "newest": {"id": rows[0]["id"], "time": rows[0]["time"]} if rows else None}))' \
      > "$out/changelog-$1.json"
  }
  ```

  A command that outlasts a minute, `twin create` among them, is followed from a second shell with
  `tail -f "$out/<name>.txt"`, the file being written as it runs.

**Bring it up**, in this order, `local/.env` loaded for each step but the first two:

1. `make infrahub-down` and `make netbox-down`, each only where `docker compose ls` lists that project,
   `fylgja-core-infrahub` or `fylgja-core-netbox`, whatever its status. Their volumes are kept. Each end: exit 0, and
   `docker compose ls` lists neither. They read none of `local/.env`'s names from the shell.
2. `make nautobot-up`. It needs none of `local/.env`'s names in the shell: it adds to the file those it lacks, and
   Compose reads them there. Its end: exit 0, once `/api/status/` names both versions and a running worker, said as
   `nautobot_dev: Nautobot 3.2.8 with nautobot_golden_config 3.0.8 answers at http://127.0.0.1:8810, <n> worker(s)
   running`; without a running worker it fails, since then no render runs. About twelve minutes on new volumes and
   about two on kept ones, 112.1 s and 129.0 s in two runs ([The development Nautobot](#the-development-nautobot)). `local/.env` is loaded again after it.
3. `make nautobot-seed`, which is idempotent: a seeded instance is found, not made again, and nothing is deleted. Its
   end: exit 0, with a line an object of the fixture, `made` or `found` and its path, one for the templates' commit and
   one for each account, grant or token it made, set or replaced, and no value. It reads `FYLGJA_NAUTOBOT_ADDRESS` and
   the superuser's `FYLGJA_NAUTOBOT_WRITE_TOKEN`, and writes the reader's token line, `FYLGJA_NAUTOBOT_TOKEN`, where
   Nautobot does not hold it as the reader's; so `local/.env` is loaded again after it. Its last act renders each tagged
   device once, so that the head it pushed is fetched by the seed itself and the first read is not refused for it.
4. The core on the local driver, in a shell of its own, as the run through Infrahub's check starts it (its step 6),
   its store, `local/store`, kept:

   ```sh
   set -a; . local/.env; set +a; FYLGJA_DRIVER=containerlab FYLGJA_STORE=local/store FYLGJA_PACKAGES=psp:probes core/.venv/bin/fylgja-core-server
   ```

   Its end: `FYLGJA_LISTEN`'s address listened on by that process's pid (`ss -Hltnp`), and `GET /v1/version` answering
   there, which takes no token. It reads `FYLGJA_LISTEN`, `FYLGJA_TOKENS` and the SR Linux login,
   `FYLGJA_CREDENTIAL_SRLINUX_USERNAME` and `_PASSWORD`, from `local/.env`. `FYLGJA_API_ADDRESS`, where the CLI reaches it,
   is `local/.env`'s, equal to `FYLGJA_LISTEN`, and is never set by hand. Its output is the log the run's record keeps:
   the shell's own, or the output file of the call that started it.

**Ready to read** is one block, run in a subshell under `set -e` as the blocks above are: after the preamble's first two
lines, in the same command, with `out` set by the caller. It makes `$out` where it is absent and refuses to start
without it. It prints a line a check that passes and exits non-zero at the first that fails, saying why and what is done.
It is run as it stands here, with the main checkout as its working directory, whichever checkout this file was read
from, and reads JSON with that checkout's `core/.venv/bin/python` alone. It reads Nautobot with the reader's token and
the core with the caller's `FYLGJA_API_TOKEN`, writes nothing but `$out`, and reads each token from the environment
inside the process that sends it; none is printed.

- **A0.** The working directory holds `local/.env`; `out` matches `local/phase-*/acceptance/?*`; each name the block
  reads is set (`FYLGJA_NAUTOBOT_ADDRESS`, `FYLGJA_NAUTOBOT_TOKEN`, `FYLGJA_API_ADDRESS`, `FYLGJA_API_TOKEN`,
  `FYLGJA_LISTEN`; `FYLGJA_LAB_POOL` where it is set); `fylgja-nautobot --help` and `fylgja-core --version` exit 0, so
  that the venv holds both; and the commit is printed, which the run's record names.
- **A1.** Nothing else of the host's is up. The projects `fylgja-core-infrahub` and `fylgja-core-netbox` are not
  listed by `docker compose ls`; no container, stopped ones included, is labelled `containerlab`;
  and the Docker networks are read: the project
  `fylgja-core-nautobot`'s is 203.0.113.0/24, and no network inside the lab pool (`FYLGJA_LAB_POOL`, by default
  172.20.0.0/16) is any but containerlab's own, named `clab-<lab>`, with the pool holding none of Nautobot's.
- **A2.** Nautobot is the instance the run is written for, read with the reader's token. `/api/status/` names Nautobot
  3.2.8 and `nautobot_golden_config` 3.0.8, with `celery-workers-running` printed and above 0; `fylgja-nautobot check`
  exits 0, prints its one `ok:` line and no warning; `?tags=fylgja` counts 3 devices; and `fylgja-templates`'
  `current_head` equals `git --git-dir=local/nautobot/git/templates.git rev-parse main`. Where they differ the block
  refuses: the next render fetches the moved head and writes a changelog row, so the next read is refused `read.moved`
  once ([D-118](design/decisions.md#d-118)); one read into `$out/warm.json` is made, which is expected to exit 1, and
  the block is run again.
- **A3.** The core is this checkout's and holds nothing. `FYLGJA_API_ADDRESS` equals `FYLGJA_LISTEN`; the listener on
  its port, by `ss -Hltnp`'s pid, runs the main checkout's own `core/.venv/bin/fylgja-core-server` with that checkout
  as its working directory, and the pid is printed; `fylgja-core twin list --json` is empty; both images the twin runs
  are on the host, `ghcr.io/nokia/srlinux:24.7.1` and `alpine:3.24.2`, since a create missing one is not run; and
  `fylgja-core capacity show --json` answers the driver `containerlab`, `twins` 0 and room, free less pending of at
  least 1.5 CPU and 6144 MiB over the host, with a host of 0.5 CPU and 2048 MiB, so that admission refuses nothing for
  want of room ([D-073](design/decisions.md#d-073)). A shortfall is a stop, read with `free -m` and
  `docker stats --no-stream`, never a run.

```bash
(
  set -e
  refuse() { echo "A$1 refused: $2" >&2; exit 1; }
  [ -f local/.env ] || refuse 0 "run in the main checkout, which holds local/"
  case ${out:-} in
    local/phase-*/acceptance/?*) mkdir -p "$out" || refuse 0 "$out was not made" ;;
    *) refuse 0 "set out=local/phase-<n>/acceptance/<run> first" ;;
  esac
  for name in FYLGJA_NAUTOBOT_ADDRESS FYLGJA_NAUTOBOT_TOKEN FYLGJA_API_ADDRESS FYLGJA_API_TOKEN FYLGJA_LISTEN; do
    [ -n "${!name}" ] || refuse 0 "$name is not set: load local/.env"
  done
  py=core/.venv/bin/python f=core/.venv/bin/fylgja-core r=core/.venv/bin/fylgja-nautobot
  pyj() {  # pyj <python> [<arg> ...]: the Python run with d, the JSON on stdin, and a, the arguments
    "$py" -I -c '
import json, sys
try:
    d, a = json.load(sys.stdin), sys.argv[2:]
    exec(sys.argv[1])
except Exception as error:
    sys.exit("%s: %s" % (type(error).__name__, error))' "$@"
  }
  "$r" --help > /dev/null || refuse 0 "fylgja-nautobot does not run: make venv in this checkout"
  "$f" --version > /dev/null || refuse 0 "fylgja-core does not run: make venv in this checkout"
  commit=$(git rev-parse HEAD) || refuse 0 "git rev-parse HEAD failed"
  echo "A0 ok: local/.env, out $out, both commands run, commit $commit"

  projects=$(docker compose ls --format json) || refuse 1 "docker compose ls failed"
  up=$(pyj 'print(*sorted(p["Name"] for p in d if p["Name"] in a))' \
    fylgja-core-infrahub fylgja-core-netbox <<< "$projects") || refuse 1 "the Compose projects were not read"
  [ -z "$up" ] || refuse 1 "$up running: make infrahub-down or make netbox-down, volumes kept"
  [ -z "$(docker ps -aq --filter label=containerlab)" ] \
    || refuse 1 "a container labelled containerlab is left: Clean up through Nautobot's reader removes it"
  seen=$(docker network inspect --format '{{json .Name}} {{json .IPAM.Config}}' $(docker network ls -q)) \
    || refuse 1 "the Docker networks were not read"
  said=$("$py" -I -c '
import ipaddress, json, os, sys
pool = ipaddress.ip_network(os.environ.get("FYLGJA_LAB_POOL") or "172.20.0.0/16", strict=False)
held, strangers, nautobot = json.JSONDecoder(), [], []
for line in sys.stdin.read().split("\n"):
    if not line.strip():
        continue
    name, end = held.raw_decode(line)
    for config in json.loads(line[end:]) or []:
        subnet = ipaddress.ip_network(config["Subnet"], strict=False) if config.get("Subnet") else None
        if not isinstance(subnet, ipaddress.IPv4Network):
            continue
        if name == "fylgja-core-nautobot_default":
            nautobot.append(str(subnet))
        if subnet.overlaps(pool) and not name.startswith("clab-"):
            strangers.append("%s %s" % (name, subnet))
print("Nautobot", ", ".join(nautobot) or "no network", "and the pool", pool)
if strangers:
    print("inside the pool: " + "; ".join(strangers))
sys.exit(nautobot != ["203.0.113.0/24"] or bool(strangers))' \
    <<< "$seen") || refuse 1 "${said:-the networks}: Nautobot's network must be 203.0.113.0/24 and no network but containerlab's inside the pool"
  echo "A1 ok: no Infrahub or NetBox, no containerlab container; $said"

  reads=$("$py" -I -c '
import json, os, ssl, sys, httpx
token, ca = os.environ["FYLGJA_NAUTOBOT_TOKEN"], os.environ.get("FYLGJA_NAUTOBOT_CA")
base = os.environ["FYLGJA_NAUTOBOT_ADDRESS"].rstrip("/")
try:
    client = httpx.Client(headers={"Authorization": "Token " + token}, timeout=60,
                          verify=ssl.create_default_context(cafile=ca) if ca else True)
    status = client.get(base + "/api/status/")
    devices = client.get(base + "/api/dcim/devices/", params={"tags": "fylgja", "limit": 1})
    repos = client.get(base + "/api/extras/git-repositories/", params={"name": "fylgja-templates"})
    answers = [status, devices, repos]
    if any(a.status_code != 200 for a in answers):
        sys.exit("Nautobot answered HTTP " + ", ".join(str(a.status_code) for a in answers))
    status, devices, repos = (a.json() for a in answers)
except Exception as error:
    sys.exit("Nautobot was not read: " + type(error).__name__)
apps = status.get("nautobot-apps") or {}
rows = repos.get("results") or []
print(json.dumps({"nautobot": status.get("nautobot-version"), "golden": apps.get("nautobot_golden_config"),
                  "workers": status.get("celery-workers-running"), "devices": devices.get("count"),
                  "head": rows[0].get("current_head") if len(rows) == 1 else None}))' 2>&1) \
    || refuse 2 "$reads"
  said=$(pyj 'print("Nautobot %s, Golden Config %s, celery-workers-running %s, %s devices tagged fylgja"
      % (d["nautobot"], d["golden"], d["workers"], d["devices"]))
sys.exit(not (d["nautobot"] == "3.2.8" and d["golden"] == "3.0.8" and type(d["workers"]) is int and d["workers"] > 0
              and d["devices"] == 3))' <<< "$reads") \
    || refuse 2 "Nautobot reads ${said:-nothing}, not 3.2.8, Golden Config 3.0.8, a running worker and 3 tagged devices"
  checked=$("$r" check 2> "$out/check.stderr") || refuse 2 "fylgja-nautobot check exited $?: $(cat "$out/check.stderr")"
  [ ! -s "$out/check.stderr" ] || refuse 2 "fylgja-nautobot check warned: $(cat "$out/check.stderr")"
  head=$(pyj 'print(d["head"] or "")' <<< "$reads") || refuse 2 "the repository's head was not read"
  bare=$(git --git-dir=local/nautobot/git/templates.git rev-parse main) \
    || refuse 2 "local/nautobot/git/templates.git holds no main: make nautobot-seed"
  [ -n "$head" ] && [ "$head" = "$bare" ] || refuse 2 "fylgja-templates' current_head is ${head:-empty}, main of the bare repository \
is $bare: the next render fetches the moved head and writes a row, so the next read is refused read.moved once \
(D-118): make one read into $out/warm.json, expect exit 1, and run the block again"
  echo "A2 ok: $said; $checked; fylgja-templates at $head, main of the bare repository"

  listen=$(ss -Hltnp "sport = :${FYLGJA_LISTEN##*:}") || refuse 3 "ss did not read the listeners"
  [ "$FYLGJA_API_ADDRESS" = "$FYLGJA_LISTEN" ] || refuse 3 "FYLGJA_API_ADDRESS is not FYLGJA_LISTEN"
  [[ $listen =~ pid=([0-9]+) ]] || refuse 3 "nothing of this user's listens on FYLGJA_LISTEN: start the core"
  pid=${BASH_REMATCH[1]}
  "$py" -I -c '
import os, sys
pid, here = sys.argv[1], os.getcwd()
want = os.path.join(here, "core", ".venv", "bin", "fylgja-core-server")
try:
    cwd = os.readlink("/proc/%s/cwd" % pid)
    argv = open("/proc/%s/cmdline" % pid, "rb").read().decode(errors="replace").split("\0")
except OSError:
    sys.exit(1)
sys.exit(cwd != here or not any(os.path.normpath(os.path.join(cwd, part)) == want for part in argv if part))' "$pid" \
    || refuse 3 "pid $pid listens on FYLGJA_LISTEN and is not this checkout's fylgja-core-server run from it"
  twins=$("$f" twin list --json) || refuse 3 "the core's twins were not read"
  held=$(pyj 'print(" ".join(t["name"] for t in d))' <<< "$twins") || refuse 3 "the core's twins were not read"
  [ -z "$held" ] || refuse 3 "the core holds the twins $held: destroy them, or start the core on an empty store"
  docker image inspect ghcr.io/nokia/srlinux:24.7.1 alpine:3.24.2 > /dev/null \
    || refuse 3 "the SR Linux 24.7.1 image or alpine 3.24.2 is not on the host: a create missing one is not run"
  room=$("$f" capacity show --json) || refuse 3 "the core's room was not read"
  sums=$(pyj 'hosts, pending = d["hosts"], d["pending"]
cpu = sum(h["cpu"]["free"] for h in hosts) - pending["cpu"]
mb = sum(h["memory_mb"]["free"] for h in hosts) - pending["memory_mb"]
roomiest = max(hosts, key=lambda h: (h["memory_mb"]["free"], h["cpu"]["free"]), default=None)
print("driver %s, %d host%s, free less pending %g CPU and %d MiB, twins %d"
      % (d["driver"], len(hosts), "" if len(hosts) == 1 else "s", cpu, mb, d["twins"]))
sys.exit(not (d["driver"] == "containerlab" and hosts and d["twins"] == 0 and cpu >= 1.5 and mb >= 6144
              and roomiest["cpu"]["free"] >= 0.5 and roomiest["memory_mb"]["free"] >= 2048))' <<< "$room") \
    || refuse 3 "the core answers ${sums:-no capacity}, not containerlab with the room: read free -m and docker stats --no-stream"
  echo "A3 ok: the local core, pid $pid, both images, $sums, and twin list empty"
)
```

The maintainer is asked once the block exits 0, and not before: a block that refused is run again after its remedy, and
the run's record keeps each refusal.

**The read.** Nautobot's changelog is read before and after, so that what a read writes is seen; the read is made once
into a file, and again into another:

```bash
nlog before
rec read core/.venv/bin/fylgja-nautobot read --scope tag:fylgja --reader nautobot/seed/reader.yaml --out "$out/blueprint.json"
nlog after
rec read-again core/.venv/bin/fylgja-nautobot read --scope tag:fylgja --reader nautobot/seed/reader.yaml --out "$out/blueprint-again.json"
```

The first read ends with exit 0 and its one line `<blueprint id> 3 devices, 3 links, 1 probes`, no finding above a
warning on stderr; the changelog's count and newest row are recorded before and after it, and compared in the record. Then a check, run in a subshell under `set -e` after the same preamble, which reads the saved files and not the
screen, and prints one line:

```bash
(
  set -e
  refuse() {  # refuse <why> [<remedy>]
    echo "read refused: $1${2:+: $2}" >&2; exit 1
  }
  py=core/.venv/bin/python
  id=$(sed -n 's/^\([0-9a-f]\{64\}\) 3 devices, 3 links, 1 probes$/\1/p' "$out/read.txt")
  again=$(sed -n 's/^\([0-9a-f]\{64\}\) 3 devices, 3 links, 1 probes$/\1/p' "$out/read-again.txt")
  [ -n "$id" ] || refuse "read.txt holds no line <id> 3 devices, 3 links, 1 probes"
  [ "$id" = "$again" ] || refuse "the same state read twice gave $id and ${again:-no id}"
  bare=$(git --git-dir=local/nautobot/git/templates.git rev-parse main) \
    || refuse "local/nautobot/git/templates.git holds no main, so the templates' head cannot be compared" "make nautobot-seed"
  said=$("$py" -I -c '
import json, sys
doc = json.load(open(sys.argv[1]))
source = doc["source"]
devices = doc["network"]["devices"]
problems = []
if source.get("source") != "nautobot" or source.get("scope") != "tag:fylgja":
    problems.append("the envelope names %s and %s" % (source.get("source"), source.get("scope")))
if not source.get("mapping") or not source.get("changelog"):
    problems.append("the envelope holds no mapping or no changelog row")
if source.get("templates") != {"fylgja-templates": sys.argv[2]}:
    problems.append("templates names %s, not fylgja-templates at %s" % (source.get("templates"), sys.argv[2]))
for device in devices:
    if device.get("platform") != "nokia_srlinux" or not str(device.get("config", "")).strip():
        problems.append("device %s has platform %s and %s" % (device.get("name"), device.get("platform"),
                        "a configuration" if str(device.get("config", "")).strip() else "no configuration"))
if len(devices) != 3:
    problems.append("%d devices" % len(devices))
print("; ".join(problems) or "envelope source nautobot, scope tag:fylgja, templates at " + sys.argv[2]
      + ", three devices of nokia_srlinux with a configuration")
sys.exit(bool(problems))' "$out/blueprint.json" "$bare") || refuse "$said"
  echo "read ok: $id twice; $said"
)
```

**The twin.** Created from the blueprint, verified, read, destroyed:

```bash
rec create core/.venv/bin/fylgja-core twin create nautobot-acceptance --blueprint "$out/blueprint.json"
rec verify core/.venv/bin/fylgja-core twin verify nautobot-acceptance
rec capacity-mid core/.venv/bin/fylgja-core capacity show --json
rec free-mid free -m
# the rest of the mid-twin reads of "Read the run" here, before the destroy
rec destroy core/.venv/bin/fylgja-core twin destroy nautobot-acceptance
rec list core/.venv/bin/fylgja-core twin list
```

- `twin create`: exit 0, `Ready: True`, `phase: pushed` and `verdict: ok`, its progress lines on stderr while it waits
  (`nautobot-acceptance: compiled`, `nautobot-acceptance: pushed`). Where the create fails, the twin is destroyed before
  anything else is read.
- `twin verify`: exit 0, `verdict: ok` and `held <n>, failed 0, skipped <n>`.
- `twin destroy`: exit 0 and `verdict: ok`; `twin list` then prints `no twins`.

The saved files are read, not the screen: each line wanted is found whole by `/usr/bin/grep -qx` in the file and its
status is the file's last line, `exit 0`. A verdict the maintainer names is the printed `verdict:` line.

**Read the run**, into `$out`, read-only. Each command's output, exit status and duration are the saved files of the
commands above. Besides them:

- **Mid-twin**, between `twin verify` and `twin destroy`: `fylgja-core capacity show --json` (`capacity-mid`) and
  `free -m` (`free-mid`), each by `rec`; `docker stats --no-stream` of the five services of the project, `nautobot`,
  `worker`, `db`, `redis` and `git` (`stats-mid`), by `rec`; and the memory of each SR Linux container by its cgroup,
  since `docker stats` prints `0B` for them
  ([verified-facts.md](design/verified-facts.md), "SR Linux 26.7.2"):

  ```bash
  ids=$(docker ps -q --filter label=com.docker.compose.project=fylgja-core-nautobot)
  if [ -n "$ids" ]; then  # an empty list would make docker stats list every container on the host
    rec stats-mid docker stats --no-stream $ids
  else
    echo "stats-mid refused: no container of fylgja-core-nautobot runs" >&2; false
  fi
  for c in $(docker ps -q --filter label=containerlab --filter ancestor=ghcr.io/nokia/srlinux:24.7.1); do
    id=$(docker inspect --format '{{.Id}}' "$c")
    echo "$(docker inspect --format '{{.Name}}' "$c") $(< /sys/fs/cgroup/system.slice/docker-$id.scope/memory.current) bytes"
  done > "$out/memory-mid.txt"
  ```

  Each mid-run read is shown and read before the next command is run, and a file left empty or a figure missing, a
  `changelog-*.json` with nothing in it or a `memory-mid.txt` line that ends `bytes` with no number, is a stop: the
  reads save no exit status of their own, and the preamble has no `set -e`, so a failed one stops nothing by itself.

- **The changelog**: `changelog-before.json` and `changelog-after.json`, the count and the newest row, from the reads
  of **The read**.
- **The core's log**, the whole of it, copied to `$out/core.log` after `twin destroy`: step 4 starts the core for this
  run, so its log begins with the run, and a core that was up before is stopped by its pid and started again by step 4
  rather than read from an offset.

Then the token check, over every file of `$out`, with `local/.env` loaded. A secret variable that is empty or unset is
refused, since an empty pattern matches every line:

```bash
secrets=(FYLGJA_NAUTOBOT_TOKEN FYLGJA_NAUTOBOT_WRITE_TOKEN FYLGJA_NAUTOBOT_SUPERUSER_PASSWORD
         FYLGJA_NAUTOBOT_DB_PASSWORD FYLGJA_NAUTOBOT_SECRET_KEY FYLGJA_API_TOKEN)
empty=$(for name in "${secrets[@]}"; do [ -n "${!name}" ] || echo "$name"; done)
if [ -n "$empty" ]; then
  echo "token check refused: $empty empty or unset: load local/.env" >&2
else
  for file in "$out"/*; do echo "$file $(/usr/bin/grep -c -F -f <(printenv "${secrets[@]}") "$file")"; done
fi
```

Each file prints 0. The blueprint and the core's log hold a site's values: nothing of either is committed.

**When it does not pass**, read from the commands' exit statuses and printed verdicts, never from a summary:

| The run | The criterion |
|---|---|
| `read` exit 0 with 3 devices, 3 links, 1 probe; `twin create` exit 0, `Ready: True`, `verdict: ok`; `twin verify` exit 0, `verdict: ok`, `failed 0`; `twin destroy` exit 0, `verdict: ok`; `twin list` `no twins` | Met. |
| `read` exit 1 with `read.moved` | Not the run. The changelog's rows since the open read are listed and recorded, and the run is made again from **The read**, the maintainer still watching. |
| `read` exit 1 or 2 otherwise; `twin create` or `twin verify` exit 1, 2 or 3 | Not met. The twin is destroyed, the cause is ruled, the seed's templates, the reader or the core, and recorded, and a fix is made and run dry again. |
| `twin destroy` exit 3, `unclean` | Not met on the destroy. **Clean up**, recorded, and the run made again. |
| a command whose whole output the maintainer did not see before the next was run | Not the run the criterion names: made again. |

What is read for each: the findings of `read`, each a line on stderr in `read.txt`; the run's own document, which
`fylgja-core run get <run id> --json` prints for the run id `twin create` or `twin verify` printed; the core's log; and
`fylgja-core twin show nautobot-acceptance`.

**Clean up**, read-only but for what each step names:

- `fylgja-core twin list` empty. A twin left is destroyed by `fylgja-core twin destroy nautobot-acceptance`, which the
  run's record says.
- `docker ps -a --filter label=containerlab` printing no container, and `local/store/containerlab/` holding no
  directory of the twin's.
- The core stopped by its pid, A3's, the listener of `FYLGJA_LISTEN`, and never by its name.
- Nautobot left up, since its network is off the pool, or stopped by `make nautobot-down`, its volumes kept. The
  development Infrahub and NetBox stay down until the maintainer says otherwise.
- The main checkout checked out again on the branch it was on.

## Releasing

A release publishes the four wheels, `fylgja-core`, `fylgja-infrahub`, `fylgja-netbox` and
`fylgja-nautobot`, at one version ([D-106](design/decisions.md#d-106),
[D-121](design/decisions.md#d-121)). Every act below but the
workflow's own is the maintainer's alone, each on the maintainer's word: no one else makes an
environment, registers a publisher, tags, pushes a tag or approves an upload.

**Before the first tag is pushed**, once, all of it:

- **A tag ruleset** on `v*`, its creation, update and deletion the maintainer's alone, so that
  no one else can start the workflow or move a tag it ran on. On GitHub's Free plan a ruleset
  needs the repository public (design/verified-facts.md, "GitHub Actions, `ubuntu-26.04`").
- **Eight GitHub environments**, one an upload job's and named as it is:
  `testpypi-fylgja-core`, `testpypi-fylgja-infrahub`, `testpypi-fylgja-netbox`,
  `testpypi-fylgja-nautobot`, `pypi-fylgja-core`, `pypi-fylgja-infrahub`, `pypi-fylgja-netbox`
  and `pypi-fylgja-nautobot`, the Nautobot reader's two made before the first candidate's tag
  that carries it ([D-113](design/decisions.md#d-113), [D-121](design/decisions.md#d-121)), each made, or if one
  exists, given these rules, by hand, since a workflow that names an environment that does not
  exist makes it with no protection rule. Each has the maintainer as its required reviewer,
  "Prevent self-review" off (the maintainer pushes the tag and approves its uploads),
  deployment tags `v*` alone, and no secret. On GitHub's Free plan an environment and its
  required reviewers need the repository public.
- **Eight pending publishers**, one an index and a distribution, each with its own environment,
  each from an account with two-factor authentication: on TestPyPI, PyPI Project Name
  `fylgja-core` with Environment name `testpypi-fylgja-core`, `fylgja-infrahub` with
  `testpypi-fylgja-infrahub`, `fylgja-netbox` with `testpypi-fylgja-netbox` and
  `fylgja-nautobot` with `testpypi-fylgja-nautobot`; on PyPI the same four with
  `pypi-fylgja-core`, `pypi-fylgja-infrahub`, `pypi-fylgja-netbox` and `pypi-fylgja-nautobot`,
  the two of the Nautobot reader's made before the first candidate's tag that carries it
  ([D-113](design/decisions.md#d-113), [D-121](design/decisions.md#d-121)); and for every
  one Owner `happypathnetworking`, Repository name `fylgja` and Workflow name `publish.yml`. A
  pending publisher is unique on its owner, repository, workflow and environment, not its
  project, so no two may share an environment (design/verified-facts.md, "PyPI and TestPyPI").
  A pending publisher reserves no name until it is used.

**A release** is then:

1. **One commit** sets `VERSION` and dates `CHANGELOG.md`'s head: `VERSION` the version,
   `X.Y.ZrcN` for a candidate or `X.Y.Z` for a release, the readers' `fylgja-core` floor the same
   version, and the head `## <version> - <YYYY-MM-DD>`, with its known limits. A release's commit
   is on `main`. The date is the day the tag will be made: `scripts/publish.py check` refuses a
   head that is `unreleased` or whose date is no date, and does not compare it with the tag.
2. **Before the tag**, on that commit with a clean tree, `make wheels` and then the check the
   workflow runs, so that a fault is found before anything can be uploaded:

   ```bash
   make wheels
   python3 -I scripts/publish.py check --tag v<version> --commit "$(git rev-parse HEAD)" --dist dist
   ```

3. **The tag** `v<version>` on that commit, pushed. Nothing else starts the workflow: a branch's
   push and a pull request do not.
4. **`.github/workflows/publish.yml`** runs. Its job `build` runs `make venv`, `make lint`,
   `make test` and `make wheelcheck`, builds the wheels by `make wheels`, and runs
   `scripts/publish.py check` against the tag and its commit, which refuses a tag that is not
   `v` + `VERSION`, a changelog's head that is another version or undated, and any wheel but the
   four at the tag's commit, and names the index by the version's form; a release's commit must
   be an ancestor of `main`. It puts each wheel in an artifact of its own. Its four jobs
   `testpypi-<distribution>` (a candidate) or `pypi-<distribution>` (a release) then each wait
   on its environment.
5. **The approval.** The maintainer approves the four waiting jobs; one review may approve
   several waiting environments at once. Each uploads its one wheel by trusted publishing: no
   token is stored anywhere, and only the eight upload jobs may ask GitHub for an identity token.
   A file uploaded to an index can never be uploaded again, nor replaced.
6. **For a release**, once its four uploads have passed, the job `release` makes the GitHub
   release, titled by the tag, carrying the same wheels and the changelog's head section, whose
   links are made absolute at the tag. A candidate has none.

**Where a run fails.** A tag whose `build` job failed, before any upload, may be deleted and
pushed again on a mended commit. Where one upload job failed and the others uploaded, that job
is re-run alone; `skip-existing` is not set, so a re-run of a job whose wheel went up fails, and
that failure says the wheel is already there. A tag that uploaded anything is never deleted or
moved: where its uploads cannot all be completed, the version cannot be uploaded again, so the
next one is cut, `X.Y.Zrc<N+1>` for a candidate or the next patch for a release, by the steps
above.

Each action the workflow uses is pinned by the commit of a release at least two weeks old, the
release named beside it, as CI's `setup-uv` is. What PyPI and GitHub require of the workflow was
read from their documentation (design/verified-facts.md, "PyPI and TestPyPI", "GitHub Actions,
`ubuntu-26.04`") and is first exercised by a candidate's tag.

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
