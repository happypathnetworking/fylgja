# A decision entry

A section list for one entry of `docs/decisions.md` (docs/development.md, "Keeping the
documents true"). Entries are append-only; a changed decision is a new entry that
supersedes the old one, whose `**Status**` then gains a *Superseded* line and nothing else.
Number: the next free `D-NNN`. The anchor precedes the heading.

```markdown
<a id="d-nnn"></a>
## D-NNN — <the decision in one sentence, as a title>

**Status:** Accepted <date>, by the operator, at <where: a feature's plan, analyze or
converge loop, a design session>. Supersedes [D-xxx](#d-xxx) <whole, or in which part>.
Beside [D-yyy](#d-yyy), which stands. To be built by `NNN-slug`.

### Context

What was true, what was found (verified where, when), and why it no longer holds or
why a choice is forced now. Cite the research section or verified fact.

### Options considered

- **<Option>.** One or two sentences; *Rejected*: why, or *Chosen*.
- …

### Decision

The rule, in the present tense, as the code and documents will state it: what, where,
and the names involved. Bullets when there are several parts.

### Consequences

What moves because of it: documents, formats, the constitution (a version bump citing
this entry), tests; limits accepted; and **Revisit** conditions.

---
```
