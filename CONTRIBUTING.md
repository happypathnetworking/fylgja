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
| jsonschema, PyYAML | 4.26.0, 6.0.3 | Runtime dependencies: the formats' validation and the packages' YAML |
| httpx | 0.28.1 | A runtime dependency: the readiness wait and the push ([D-039](design/decisions.md#d-039)) |
| Starlette, uvicorn | 1.9.0, 0.54.0 | Runtime dependencies: the server's ASGI application and the process that serves it ([D-025](design/decisions.md#d-025)) |
| pygnmi, grpcio, protobuf | 0.8.15, 1.84.0, 7.36.2 | Runtime dependencies: verify's gNMI reader ([D-052](design/decisions.md#d-052)) |
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
| `make live` | The live tier: boots labs under containerlab, one SR Linux and one cEOS node for readiness and the push, and labs through the local driver (admit, apply, inspect, destroy, the residue rule, two labs at once), then destroys them; `changes` held to containerlab's own dry run for every step fixture, with the hot-add recreate of two cEOS nodes and `exec` in a probe host (`core/tests/live/test_changes_live.py`, about 4.5 minutes alone); verify over gNMI on a probed twin, with a node stopped and started by containerlab and by Docker, and a configured cEOS node's host name (`core/tests/live/test_verify_live.py`, about 5 minutes alone); the end-to-end test, `three-node` through `fylgja-core-server` and the thin CLI, with the server killed at every phase boundary of a create, during a deploy and during a destroy, and a deletion during a deploy (`core/tests/live/test_e2e.py`, about 11 minutes alone); and the steps end to end, `fylgja-core twin step` to every step fixture from its base (the SR Linux ones, a cEOS port refused without `allow_restart` and made with it, and a kind change), the server killed at every phase boundary of a step, during its deploy and before a deletion, and a step cancelled during its apply, left diverged and then deleted (`core/tests/live/test_e2e_step.py`, about 16 minutes alone). About 40 minutes. Load `local/.env` first |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures, and the store, the reconcile loop, API 1 and the CLI over fakes of the runtime |
| **Live** | Booted images on the local containerlab driver | On demand: `make live`, with `local/.env` loaded: the driver, `changes` against containerlab's dry run, readiness and the push, verify over gNMI, the end-to-end test through the API (`core/tests/live/test_e2e.py`, about 11 minutes alone), and the steps end to end (`core/tests/live/test_e2e_step.py`, about 16 minutes alone). `make test` deselects it (the `live` marker) |
| **Driver conformance** | Each driver's own runtime: a cluster for clabernetes | On demand, per driver |

Development and the live tier never need Kubernetes (Constitution XIII).

## Test data

| Path | Holds |
|---|---|
| `testdata/blueprint/` | Five blueprints: `three-node`, `mixed`, `lossy`, `three-node-probed`, `three-node-unmanaged` (it has no Go facts) |
| `testdata/compiler/` | The facts the frozen Go compiler produced for each, which the new compiler is held to; and under `rejected/`, valid blueprints the compiler must refuse, one fault each |
| `testdata/packages/` | `chassisos`, a synthetic lossy platform; the interface mapping rows each package must produce; and under `invalid/`, the rejection fixtures for the platform and probe package loaders |
| `testdata/probes/` | Probe declaration files, valid and, under `invalid/`, the rejection fixtures for the declaration loader |
| `testdata/deployment/` | The golden deployments: for each driver and fixture, the rendered runtime files and the deployment document the plan must reproduce, which change in a commit of their own; and under `rejected/`, valid blueprints a driver's plan must refuse, one fault each |

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

## Running the core

`fylgja-core-server` is one process: API 1 on uvicorn and the reconcile loop, over one store
it holds locked for one core ([D-023](design/decisions.md#d-023), [D-039](design/decisions.md#d-039)).
Everything it runs with is a `FYLGJA_*` variable ([D-042](design/decisions.md#d-042)), listed
in [`.env.example`](.env.example):

| Variable | Default | Holds |
|---|---|---|
| `FYLGJA_STORE` | required | The store's directory, created on first start; the driver's working files live under it |
| `FYLGJA_PACKAGES` | required | Colon-separated directories of platform and probe packages, loaded once at start: `psp:probes` |
| `FYLGJA_TOKENS` | required | The token file (below) |
| `FYLGJA_LISTEN` | `127.0.0.1:7650` | The address it serves on, `host:port` |
| `FYLGJA_DRIVER` | `containerlab` | The driver twins run on |
| `FYLGJA_WORKERS` | `4` | How many twins the loop works on at once |
| `FYLGJA_STEP_WAIT_S` | `180` | Seconds a step waits for verify to hold before it ends anyway (an integer of 1 or more) |
| `FYLGJA_CREDENTIAL_<NAME>_USERNAME`, `_PASSWORD` | none | Each package's node login, `<NAME>` its `credentials` value upper-cased; a run needing one not set fails with `credential.missing` |

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

**Start it** with the environment loaded:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-core-server
```

It logs one JSON object per line on stderr, the principal on every write, never a token or a
password. A start refused is one line naming the variable or the file at fault. SIGTERM or
Ctrl-C ends open watches and stops the loop; a create cut short resumes at the next start. Its
exit status:

| Status | Means |
|---|---|
| 0 | stopped cleanly |
| 130 | stopped by Ctrl-C (SIGINT) |
| 143 | stopped by SIGTERM: uvicorn ends the process by the signal after its graceful shutdown |
| 1 | the store is held by another core, or the application failed to start |
| 2 | a misconfiguration: a `FYLGJA_*` variable not set, empty or malformed, a package refused, a token file it cannot read, or an address it cannot listen on (`FYLGJA_LISTEN`) |

**The thin CLI** reads `FYLGJA_API_ADDRESS` (the server's `host:port` or URL) and
`FYLGJA_API_TOKEN`. In a shell of its own, load the environment and point the CLI at the
server's listen address:

```sh
set -a; . local/.env; set +a
export FYLGJA_API_ADDRESS=127.0.0.1:7650   # FYLGJA_LISTEN's value
core/.venv/bin/fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
core/.venv/bin/fylgja-core twin show demo
core/.venv/bin/fylgja-core twin destroy demo
```

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
