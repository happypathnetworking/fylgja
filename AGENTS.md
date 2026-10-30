# Working notes for coding agents

This is **fylgja-core**: a blueprint (a network's intent, content-addressed) becomes a twin
running real network operating system images. It knows no source of truth. The design is
`design/core.md`, and building it is under way.

The orchestrator, which reads Infrahub into blueprints, lives in the project's archived
repository for now, beside the frozen Go core, the reference implementation.

## Read first

- `design/architecture.md`
- `design/constitution.md`: binds every change.
- `design/decisions.md`: rejected alternatives live here; check before proposing one.
- `CONTRIBUTING.md`: setup, tiers, conventions.
- `formats/`: every format, one current version each.
- `design/verified-facts.md`: read it when a task touches containerlab, clabernetes or a
  network operating system, and trust it over recollection.

## Rules

- **A change is a design document, a decision entry where a decision changes, then a pull
  request** (D-033). `design/decisions.md` is append-only: a changed decision is a new entry
  that supersedes the old one.
- **A change to a format is made in `formats/`,** in the same change as the code.
- **Verify against the running system** before asserting how containerlab, clabernetes or a
  network operating system behaves. Record the result in `design/verified-facts.md`.
- **Never echo, log or persist a token or a password.** `local/.env` holds every value.
- **Commit with a conventional-commit message whose body says why.** Never commit `local/`.
  Never push without being asked.

## Build and test

`make venv`, then `make lint` (ruff, mypy strict) and `make test` (the pure tier, no
infrastructure).
