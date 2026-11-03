<!-- Fylgja is not taking outside contributions yet; see CONTRIBUTING.md. This template is the
project's own checklist for a change: a design document, a decision entry where a decision
changes, then a pull request (design/decisions.md, D-033). Replace the comments, keep the
headings. -->

## What changes

<!-- One paragraph, in the terms of design/architecture.md: what this pull request builds,
changes or removes. -->

## Why

<!-- The reason, as the commit bodies say it. Name the design document it follows
(design/core.md and its phase, or another under design/) and any decision entry it adds. -->

## Checklist

- [ ] Anything larger than a fix follows a design document under `design/`.
- [ ] A changed decision is a new entry in `design/decisions.md` that supersedes the old one;
      the log is append-only, and the constitution changes only by citing such an entry.
- [ ] A change to a format is made in `formats/`, in this pull request, with the code that
      reads or writes it; its version is still 1.
- [ ] Anything that depends on how containerlab, clabernetes or a network operating system
      behaves was verified against the running system and recorded, with version and date,
      in `design/verified-facts.md`.
- [ ] Fixtures (blueprints, compiler facts, goldens, rejection fixtures) change in a commit
      of their own, and every rejection fixture has a row in its test.
- [ ] A new rule is in `docs/rules.md`, and a new term is in `docs/glossary.md`.
- [ ] No token, password or credential appears anywhere in the change: not in a document, a
      fixture, a test or a log line.
- [ ] Every commit has a conventional message whose body says why.
- [ ] `make lint`, `make test` and `make linkcheck` pass.
