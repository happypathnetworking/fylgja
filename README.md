# Fylgja

[![ci](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml)

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

This is **fylgja-core**, the part that turns a blueprint into a twin. It knows no source of
truth ([D-003](design/decisions.md#d-003)). Anything that writes a blueprint can drive it,
through its API or its CLI.

It is being built ([design/core.md](design/core.md)):
- **In Python**, for many named twins at once.
- **Behind a driver seam.**
  - Local containerlab, for development.
  - [clabernetes](https://github.com/clabernetes/clabernetes) on Kubernetes, for production.
  - Real hardware, later.
- **Done so far:** the formats ([formats/](formats/README.md)), the platform and probe
  packages, and the blueprint's id and validation.

The **orchestrator** reads [Infrahub](https://github.com/opsmill/infrahub) into blueprints and
rehearses proposed changes. It lives in this project's archived repository, and moves here
once this core runs twins ([D-005](design/decisions.md#d-005)).

## Read in this order

1. [design/architecture.md](design/architecture.md): the system, as built and as designed.
2. [design/constitution.md](design/constitution.md): the non-negotiables.
3. [design/decisions.md](design/decisions.md): why. Rejected alternatives live there; check
   them before proposing one.
4. [CONTRIBUTING.md](CONTRIBUTING.md): how to build, test and change things.
5. [docs/glossary.md](docs/glossary.md), when a term is new.
6. [design/verified-facts.md](design/verified-facts.md): what has been verified against
   containerlab, clabernetes and the network operating systems, with versions and dates.

## Quick start

You need Python 3.14.

```sh
make venv     # core/.venv at core/pyproject.toml's pins
make lint     # ruff and mypy (strict)
make test     # the pure tier: no infrastructure
```

## Licence

[Apache License 2.0](LICENSE).
