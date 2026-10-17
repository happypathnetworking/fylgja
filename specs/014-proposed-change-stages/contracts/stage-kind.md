# Contract: the stage kind, its migration and its removal of the waypoint kind

The schema file Fylgja ships beside the contract, how it lands on an Infrahub `main`, how
the waypoint kind leaves, and what the schema README tells the operator. Verified on
2026-10-16 against Infrahub 1.11.2 ([research.md §6.2–§6.5](../research.md#6-verified-at-plan)).

## The file: `schema/fylgja-stage.yaml`

```yaml
---
# yaml-language-server: $schema=https://schema.infrahub.app/infrahub/schema/latest.json
#
# Fylgja stage kind (014, D-045): a moment of a proposed change. Beside the generics
# contract, not in it (the contract stays 0.2); loaded on the default branch (D-028), where
# Fylgja reads it; needed only by --stage, stage list and stage plan.
#
#   - A stage belongs to a proposed change and has no branch of its own: its branch is the
#     proposed change's source. The relationship is required, so the uniqueness constraint
#     may name it; a human-friendly id through the proposed change is refused by Infrahub,
#     since a proposed change's name is not unique.
#   - The label is the stage's name in a reference, <branch>/<label>: no '/' and no
#     whitespace (the regex mirrors stages.LabelPattern; a test holds the two equal). The
#     labels branch-point and head name the two derived stages and are refused by Fylgja
#     on a mark; Infrahub does not know them.
#   - The attribute is `as_of`, not `at`: Infrahub refuses a two-character name. Every
#     command, report and record says `at`.
#   - `branch: agnostic`, so a mark lands in no branch's diff and is read from the default
#     branch.
version: "1.0"
nodes:
  - name: Stage
    namespace: Fylgja
    description: "A marked moment of a proposed change: its source branch at a point in time."
    label: Stage
    icon: mdi:map-marker-path
    branch: agnostic
    include_in_menu: true
    generate_profile: false
    display_label: "{{ label__value }}"
    order_by: [as_of__value]
    uniqueness_constraints:
      - [proposed_change, label__value]
    attributes:
      - name: label
        kind: Text
        optional: false
        parameters:
          regex: "^[^/\\s]+$"
        description: "What this stage of the change is: a name with no '/' and no whitespace, unique within its proposed change."
        order_weight: 1000
      - name: as_of
        kind: DateTime
        optional: true
        description: "The point in time on the source branch. Omitted: when the stage was written."
        order_weight: 1100
      - name: description
        kind: Text
        optional: true
        description: "What this moment of the change is, in a sentence."
        order_weight: 1200
    relationships:
      - name: proposed_change
        peer: CoreProposedChange
        kind: Attribute
        cardinality: one
        optional: false
        identifier: "proposed_change__fylgja_stages"
        order_weight: 900
extensions:
  nodes:
    - kind: CoreProposedChange
      relationships:
        - name: fylgja_stages
          peer: FylgjaStage
          kind: Generic
          cardinality: many
          optional: true
          identifier: "proposed_change__fylgja_stages"
```

Keys are in the order the schema skill's formatting rule gives. `infrahubctl schema format`
(SDK 1.23.2) orders them otherwise: it would put `order_by` before `display_label`,
`generate_profile` and `branch` after `uniqueness_constraints`, and `label`'s `optional`
after its `parameters` (research §8.2). No gate runs it, and whether to reformat the file
is the operator's. The identifier is shared by both sides and is immutable once loaded; it
is the candidate's, so the migration keeps it.

## The migration on a `main` that carries the candidate (the development host)

From the tree, with `local/.env` loaded, Infrahub up, no twin:

1. `.venv/bin/infrahubctl schema check --branch main schema/` prints, for `FylgjaStage`,
   `attributes: added: description; changed: label: description, parameters.regex` and
   nothing else (the four `display_labels` deprecation warnings on the shipped files are
   not findings of this pass).
2. `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` loads `schema/` on `main`
   (`schema loaded on main`), then finds the group and the registration present.
3. `.venv/bin/infrahubctl schema check --branch main specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml`
   prints `removed: FylgjaWaypoint`; `schema load` of the same document removes the kind
   (about 40 s).
4. `curl -s "$INFRAHUB_ADDRESS/api/schema" | jq '[.nodes[] | select(.kind | startswith("Fylgja")) | .kind]'`
   lists `FylgjaStage` and no `FylgjaWaypoint`, and `FylgjaStage`'s attributes are `label`,
   `as_of`, `description`; `jq '.nodes[] | select(.kind=="CoreProposedChange") | .relationships[] | select(.name=="fylgja_stages")'`
   shows the extension. `GET /api/schema/summary` gives `main`'s new hash, recorded in
   `CLAUDE.md`.
5. `make sdl` refetches `schema/infrahub.graphql` (the header kept by hand); `make generate`
   regenerates the client; `go build ./...`.

Nothing is written to `fylgja-fixture`; its hash stays `0aba31a5…` and it compiles to
`47b2c449…`. Loading `schema/` again writes nothing; loading the absent document again is
"already up to date".

## On a `main` that never had either kind (CI's runner, a stranger's install)

`-prepare-main` loads the stage kind and the extension with the rest of `schema/`. The
absent document is not loaded; checked or loaded, it would be `No diff`.

## The waypoint kind's removal is reversible

`git show <before>:schema/fylgja-waypoint.yaml > /tmp/w.yaml && infrahubctl schema load --branch main /tmp/w.yaml`
puts the kind back, empty. No object of the kind existed on the development host.

## What `schema/README.md` says ("Stages: marking one")

Replaces "Waypoints: writing one". Its content, in order; the implement task verifies the
three ways on a throwaway proposed change before the text is committed
([research.md §7](../research.md#7-owed)):

- **What a stage is**: a moment of a proposed change; every proposed change has its branch
  point and its head, derived; the operator marks the moments between, after the writes
  of that moment and after its artifacts are regenerated.
- **Open the proposed change first**, as a draft while the change is built (the UI's
  "Create proposed change" with the draft toggle, or `CoreProposedChangeCreate` with
  `is_draft: true`), on the branch being built; `main` cannot be a source; one open per
  branch.
- **When to mark**: after the moment's writes have landed and the artifacts have been
  regenerated, by the proposed change's checks (its creation or a retry runs the artifact
  validator) or by a generate; a stage marked before that is refused as stale, naming the
  device and both remedies (`stage.artifact.stale`); mark again after regenerating. Leave
  `as_of` out unless an instant is wanted: the mark's own write is always after what it
  seals, and a read pinned at exactly a stamp sees the node and not the value.
- **The fields**: `label` (required; no `/`, no whitespace; unique within the proposed
  change; `branch-point` and `head` are reserved for the two derived stages, and a mark so
  labelled is refused), `as_of` (optional; verbatim; at most six fractional digits; later
  than now refused until it has passed), `description` (optional), `proposed_change`
  (required).
- **Three ways to write one**, all Infrahub's: the UI (Stage, an entry of its own in the
  sidebar's object menu, `/objects/FylgjaStage`, with the proposed change chosen from the
  list; research §8.12); an object file (`kind: Object`, `spec.kind:
  FylgjaStage`, each row's `proposed_change` by the proposed change's id, since the kind
  has no human-friendly id), loaded with `infrahubctl object load stages.yml` (any
  branch; the default has the kind); `infrahubctl object create FylgjaStage --set
  label=cabled --set proposed_change=<id> --set description="…"`. Deleting: the UI or
  `FylgjaStageDelete`.
- **Editing a stage**: `description` changes nothing Fylgja reads; `as_of` moves the
  stage's `at`; `label` renames the reference. None changes a twin already built from it:
  the record keeps what the twin was built from, and `stage list` warns `stage.twin.moved`
  beside it, as `twin step` does beside its target.
- **Delete stages before their proposed change**: Infrahub refuses a proposed change's
  delete while a stage names it (`It is linked to mandatory relationship proposed_change on
  node FylgjaStage …`; research §8.8). A stage removed from its proposed change's
  `fylgja_stages` is left naming none; `stage list` reports each such stage as
  `stage.orphaned` until it is deleted by id. A branch deleted under an open proposed change
  cancels it, about 16 s later.
- **The kind on the default branch**: `-prepare-main` or `infrahubctl schema load
  schema/fylgja-stage.yaml` once; `fylgja schema check --branch <b>` reports `stages:
  FylgjaStage present on the default branch, with its extension`. An installation that
  never loads it loses only the stage surface, each command refused naming this file.

The README's table row for the file follows the waypoint row's shape. The section no
longer says "write the waypoint last": the staleness check is the rule made a query.
