# A feature's section in `contracts/cli.md` and `contracts/api.md`

Each feature appends one `## NNN: <title>` section to each contract document it touches,
and moves a schema's `description` by prefixing its history with the feature's number:
`NNN: <what moved>; …`. The subsections, in this order, each left out when empty:

```markdown
## NNN: <title>

### The commands
Each command or operation added or changed: flags, arguments, their refusals and exit codes.

### The text
The text renderings that change, line by line as a reader sees them.

### Identifiers
Rule ids added and retired, with the surface and the condition.

### Formats and versions
Each document whose version moves, from what to what, and what a reader of the old
version gets; the frozen copies kept under `testdata/contracts/`.

### Workflows and activities
What the worker serves after the feature, when it changes.

### Environment
Variables added, removed or re-read.

### Upgrading
What a host of the previous release must do first.

### Tier 3 (`scripts/e2e.sh`)
The cases added, repurposed or moved, by number.
```
