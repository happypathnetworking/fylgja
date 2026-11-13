# Fylgja

[![ci](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml)

> **A refactor of the prototype.** This repository rebuilds Fylgja from scratch, in Python,
> on a clean break in formats ([D-001](design/decisions.md#d-001),
> [D-002](design/decisions.md#d-002)). The prototype it refactors, with its Go core, which
> was the reference implementation and is retired, and the orchestrator that drove it, is
> [happypathnetworking/fylgja-prototype](https://github.com/happypathnetworking/fylgja-prototype):
> the archived repository the design documents refer to.

Fylgja builds a **twin** of a network from its intent, so that a change can be rehearsed
before it reaches production.

Its input is a **blueprint**: every device and its interfaces, the links between them, each
device's configuration exactly as the source of truth rendered it, and optionally
**probes**, small hosts that ping each other through the twin. A blueprint is addressed by
its contents. Fylgja compiles it into a deterministic **bundle**, then runs the bundle as a
twin on real network operating system images and pushes each configuration.

A twin steps from one blueprint to another without a rebuild. `verify` reports whether the
running twin matches its intent, and the probes measure the loss a step causes. Vendors are
data, not code: Nokia SR Linux and Arista EOS today, alone or mixed in one twin.

## This repository

This is **fylgja-core**, and three pieces live here ([D-081](design/decisions.md#d-081)): the
core, the part that turns a blueprint into a twin; a reader for each source of truth, the
Infrahub reader and the NetBox reader; and an example orchestrator. The core knows no source of
truth ([D-003](design/decisions.md#d-003)). Anything
that writes a blueprint can drive it, through its API or its CLI.

The core is being built ([design/core.md](design/core.md)):
- **In Python**, for many named twins at once.
- **Behind a driver seam.**
  - Local containerlab, for development.
  - [clabernetes](https://github.com/clabernetes/clabernetes) on Kubernetes, for production.
  - Real hardware, later.
- **Done so far:** the formats ([formats/](formats/README.md)), the platform and probe
  packages, a model type and a loader for every format, and the compiler, held to the
  facts the prototype's compiler produced; a named twin on the local driver: the
  state store, the containerlab driver, readiness and the push, the reconcile loop, API 1
  and the thin CLI; a step from one blueprint to another, verify and each probe's burst; the
  clabernetes driver, the core as a pod on a cluster, and a conformance suite that holds both
  drivers to one behaviour; and many twins at once, admitted by the runtime's room. Its
  rules are catalogued in [docs/rules.md](docs/rules.md).

The **Infrahub reader**, [`readers/infrahub/`](readers/infrahub/README.md), reads
[Infrahub](https://github.com/opsmill/infrahub) into blueprints, and the **NetBox reader**,
[`readers/netbox/`](readers/netbox/README.md), reads a branch of NetBox's branching plugin, or
`main`, into blueprints: each a library, and a command of its own. The example **orchestrator**,
`orchestrator/`, rehearses a change on a twin, a proposed change in Infrahub through Infrahub's
own check, or a branch in NetBox from the tag set on it, and
[docs/integrating.md](docs/integrating.md) walks through it to join Fylgja to a system of your
own ([D-005](design/decisions.md#d-005), [D-081](design/decisions.md#d-081),
[D-097](design/decisions.md#d-097)). The Infrahub reader and the example were built in phase 8,
which ended on 2026-11-12 with a proposed change created in Infrahub and rehearsed through its
check on the local driver and on a cluster ([D-094](design/decisions.md#d-094)). The NetBox
reader and the example's NetBox change source were built in phase 9
([D-095](design/decisions.md#d-095)), which ended on 2026-11-13 with a branch built in NetBox in
steps, each marked, and rehearsed from the tag the maintainer set on it, on the local driver and
on a cluster, the maintainer reading each report on the branch's journal
([D-101](design/decisions.md#d-101)).

## Read in this order

1. [design/architecture.md](design/architecture.md): the system, as built and as designed.
2. [design/constitution.md](design/constitution.md): the non-negotiables.
3. [design/decisions.md](design/decisions.md): why. Rejected alternatives live there; check
   them before proposing one.
4. [CONTRIBUTING.md](CONTRIBUTING.md): how to build, test and change things.
5. [docs/glossary.md](docs/glossary.md), when a term is new.
6. [design/verified-facts.md](design/verified-facts.md): what has been verified against
   containerlab, clabernetes, Infrahub, NetBox, Prefect and the network operating systems,
   with versions and dates.
7. [docs/integrating.md](docs/integrating.md): how to join Fylgja to a source of truth and a
   platform of your own, walked through the example orchestrator.

## Quick start

You need Python 3.14.

```sh
make venv     # core/.venv at core/pyproject.toml's pins
make lint     # ruff and mypy (strict)
make test     # the pure tier: no infrastructure
```

## Running a twin

`fylgja-core-server` serves API 1 and runs the reconcile loop over a store on this host,
with containerlab as the driver; `fylgja-core` is its thin CLI. With Docker, containerlab
and the SR Linux image in place, a token made and the environment loaded,
`fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json` boots three
SR Linux nodes, pushes each its configuration, and waits until the twin is Ready; `twin
show` and `twin destroy` follow. CONTRIBUTING's
[Running the core](CONTRIBUTING.md#running-the-core) says how to set it up.

On a Kubernetes cluster the core runs as one pod, deployed from the kustomize base under
[`deploy/`](deploy/README.md) and a site's overlay, as
[Running the core on a cluster](CONTRIBUTING.md#running-the-core-on-a-cluster) says.

## Licence

[Apache License 2.0](LICENSE).
