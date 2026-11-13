# Working notes for coding agents

This is **fylgja-core**: a blueprint (a network's intent, content-addressed) becomes a twin
running real network operating system images. It knows no source of truth. The design is
`design/core.md`: its opening says which phases are done, and its "Sequence" what each built
and what it left.

Beside the core this repository holds a reader for each source of truth, which reads that
source into blueprints: the Infrahub reader under `readers/infrahub/` and the NetBox reader
under `readers/netbox/`; and the example orchestrator, under `orchestrator/`, which rehearses a
change of either source on a twin, a proposed change in Infrahub or a branch in NetBox (D-081,
D-095, D-097). The Go core is retired: it gets no more fixes, and nothing tracked here needs it
or the project's archived repository to build, test or run. The archived repository is cited as
history, and as the reference the Infrahub reader and the example were written against.

## Read first

- `design/architecture.md`
- `design/constitution.md`: binds every change.
- `design/decisions.md`: rejected alternatives live here; check before proposing one.
- `CONTRIBUTING.md`: setup, tiers, conventions.
- `formats/`: every format, one current version each.
- `docs/integrating.md`: how to join Fylgja to a source of truth and a platform of your own,
  walked through the example orchestrator.
- `readers/infrahub/README.md`: the Infrahub reader, the Infrahub versions it passed on and
  its upgrade procedure.
- `readers/netbox/README.md`: the NetBox reader, the versions of NetBox and of its branching
  plugin it passed on and its upgrade procedure.
- `design/verified-facts.md`: read it when a task touches containerlab, clabernetes,
  Infrahub, NetBox, Prefect or a network operating system, and trust it over recollection.

## Rules

- **A change is a design document, a decision entry where a decision changes, then a pull
  request** (D-033). `design/decisions.md` is append-only: a changed decision is a new entry
  that supersedes the old one.
- **A change to a format is made in `formats/`,** in the same change as the code.
- **Verify against the running system** before asserting how containerlab, clabernetes,
  Infrahub, NetBox, Prefect or a network operating system behaves. Record the result in
  `design/verified-facts.md`.
- **Never echo, log or persist a token or a password.** `local/.env` holds every value.
- **Commit with a conventional-commit message whose body says why.** Never commit `local/`.
  Never push without being asked.
- **A phase is built by the procedure in `.claude/skills/build-phase/SKILL.md`**
  (`CONTRIBUTING.md`, "How a phase is built"): settle, plan, execute, land.

## Build and test

`make venv`, then `make lint` (ruff, mypy strict) and `make test` (the pure tier, no
infrastructure).
