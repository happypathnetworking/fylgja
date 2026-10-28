# Specify brief: <release> spec <n> of <m>: <title> (F-NNN)

A section list, one line each on what belongs there (docs/development.md, "Spec Kit
workflow"). The brief is the operator's one input to the chain: when it is finished,
`clarify` has nothing to ask and no `[operator]` task is owed that could have been done
here. Copy this file to `specs/NNN-slug/brief.md`, keep the headings, and replace every
line below them.

<!-- The opening paragraph: what `/speckit-specify` reads this for, the roadmap feature and
release, when it was written and from what (an inventory, questions put to the operator),
what it was re-read against, the one-sentence shape, "the session verified nothing live;
the plan verifies each point", and "specify what the operator gets, not a new design".
Name the constitution version once, here or under Where the shape is fixed. -->

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/NNN-slug GIT_BRANCH_NAME=NNN-slug. <release>, the <n>th of its <m> specs: <title>, as docs/roadmap.md's F-NNN and <release> section define it. Read specs/NNN-slug/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

Two to four bullets: the gap, what prepared the ground, and what this proves for the
production shape. Bold lead, one claim each, with the decision or document that backs it.

## Where the shape is fixed

One bullet per decision, roadmap section, constitution principle or earlier brief's
hand-off that binds this feature, saying what it fixes and where this brief departs from
it (owed back under Exit).

<a id="what-changes"></a>
## What changes, and nothing else

A numbered list, each item one behaviour change with its sub-bullets: the surface, the
formats that move, the refusals, the documents. Any other difference from what is built is
a defect.

<a id="decided"></a>
## Decided

Each decision in one sentence with its reason, dated and attributed (the operator on
<date>; the brief's author), and *Not chosen* alternatives where a reader would ask. End
with **Out of this feature**.

<a id="open"></a>
## Open, for clarify

`none` before the chain starts. Until then, each open question with its options; the
feature-open step puts them to the operator and moves each into Decided.

<a id="left-to-the-plan"></a>
## Left to the plan

What the plan verifies live or decides without the operator: images, mechanics, format
versions and their frozen copies, the fixture, the Constitution Check's open point, which
Infrahub skill to load, the estimate.

<a id="operator-steps"></a>
## Operator steps

Checkboxes for what only the operator does and that precedes the chain: a push, an
import into Infrahub, a schema load on `main`, a host step. Each ticked here, or listed
with its command and the reason it must wait (then it is the route's `[operator]` task).

- [ ] …

<a id="hand-off"></a>
## Hand-off

What this feature leaves to the next specs and to the production shape, one bullet each.

<a id="exit"></a>
## Exit

**The one criterion** in a sentence; then what each tier proves (tier 1, tier 2, tier 3),
whether the goldens and the fixture's ids move, and **Owed before the work starts**: the
roadmap reconciled, the previous feature closed, this brief committed.

<a id="references"></a>
## References

"Read in this order, after `CLAUDE.md`'s list", then a table: `| Record | What it gives |`,
one row per document, decision set, contract, package, schema file and code directory
the plan should read, with links.
