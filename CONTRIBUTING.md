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

## Tooling

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 | [D-001](design/decisions.md#d-001) |
| jsonschema, PyYAML | 4.26.0, 6.0.3 | The core's runtime dependencies so far |
| pytest, ruff, mypy | 9.2.0, 0.17.3, 2.4.0 | mypy in strict mode (Constitution I) |
| rfc8785 | 0.1.4 | Tests only: an independent RFC 8785 implementation that the blueprint id is checked against |
| containerlab, Docker | 0.81.0, 29.8.1 | The local driver and the live tier. containerlab is pinned to the version clabernetes 0.10.1 embeds, so the kinds behave alike on both drivers |
| clabernetes, kind | 0.10.1, v0.33.0 | The clabernetes driver's development ([D-022](design/decisions.md#d-022)) |

Each dependency is pinned to a release at least two weeks old when it was chosen.
`make venv` builds `core/.venv` at the pins, with the package installed editable. A venv
inside the tree carries a `.gitignore` of `*`.

## Make targets

| Target | What it does |
|---|---|
| `make venv` | The core's venv |
| `make lint` | ruff over `core/` and `scripts/`, then mypy in strict mode |
| `make test` | The pure tier: no infrastructure. Gates every pull request |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures |
| **Live** | Booted images on the local containerlab driver | On demand, once the local driver exists |
| **Driver conformance** | Each driver's own runtime: a cluster for clabernetes | On demand, per driver |

Development and the live tier never need Kubernetes (Constitution XIII).

## Test data

| Path | Holds |
|---|---|
| `testdata/blueprint/` | Four blueprints: `three-node`, `mixed`, `lossy`, `three-node-probed` |
| `testdata/compiler/` | The facts the frozen Go compiler produced for each, which the new compiler is held to; and under `rejected/`, valid blueprints the compiler must refuse, one fault each |
| `testdata/packages/` | `chassisos`, a synthetic lossy platform; the interface mapping rows each package must produce; and under `invalid/`, the rejection fixtures for the platform and probe package loaders |
| `testdata/probes/` | Probe declaration files, valid and, under `invalid/`, the rejection fixtures for the declaration loader |
| `testdata/deployment/` | The golden deployments: for each driver and fixture, the rendered runtime files and the deployment document the plan must reproduce; they change in a commit of their own |

## Local environment

**Credentials** live in `local/.env` alone (git-ignored, mode `0600`), with the names in
[`.env.example`](.env.example).
- Load it with `set -a; . local/.env; set +a`. Fylgja reads the process environment, never a
  file.
- Never print, log or persist a token or a password.

**The live tier** needs:
- Docker and containerlab, with the user in the `docker` and `clab_admins` groups;
- the SR Linux image (`ghcr.io/nokia/srlinux:24.7.1`, public);
- the cEOS image (`ceos:4.32.0.2F`), imported from Arista's account-gated download and never
  pulled.

On Ubuntu, SR Linux's `rsyslogd` needs an AppArmor widening ([verified-facts.md](design/verified-facts.md)).

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
