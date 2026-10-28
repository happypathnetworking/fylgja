# The commands: the "016: probes" sections of `contracts/cli.md` and `contracts/api.md`

Drafted here; implement appends each to its file in the shape of the 018 and 019 sections.

## cli.md: 016: probes

### The commands

- `fylgja intent read --branch <b> [--at <ts>] [--scope tag:<name>] [--probes <file>] --out snapshot.json`,
  `fylgja intent read --stage <ref> [--scope …] [--probes <file>] --out snapshot.json`:
  the snapshot written is version `2`; `probes` is the file's list, else `FylgjaProbe`'s
  on the default branch, else `[]`.
- `fylgja twin create --branch <b> … [--probes <file>]`, `--stage <ref> [--probes <file>]`:
  the take carries the list; the twin boots one `linux` host per endpoint. `twin create
  --snapshot <id|file>` takes the snapshot's list; `--probes` beside it is
  `snapshot.flags.conflict` at `--probes`, before any connection.
- `fylgja twin step --stage <ref> [--probes <file>] …`: the target's take carries the list;
  the flows of the probes both snapshots carry are started after the stage and read after
  the wait. `twin step --snapshot <id|file>` takes the snapshot's; `--probes` beside it is
  the conflict. `twin step` with no target reads the record's stage's next, with the kind's
  probes or the file's.
- `fylgja stage plan --branch <b> [--probes <file>]`, `fylgja twin rehearse --branch <b>
  [--probes <file>] [--markdown]`: every stage's take carries the one list read at the
  request's start.
- `fylgja twin verify [--wait]`: the bursts, one per probe, from the server.
- `fylgja twin compile`, `fylgja twin provision`: no `--probes`; the snapshot or the
  bundle says what it carries.
- The checks `fylgja-step` and `fylgja-twin` send no file: theirs are the kind's.

### The text

- `twin create`'s dry run: `nodes: n1, n2, n3 (nokia_srlinux); n1-loop-a, n1-loop-b (ping
  host)`; `memory: 6,208 MiB …`.
- `twin step`: after `step stage:`, `step flows: n1-loop started` (or `n1-loop not
  started: <reason>`); after `step observe: …`, `step loss: n1-loop 0/312 lost, longest
  gap 0.0s (container timing)`; the closing line ends `; loss n1-loop 0/312`.
- `twin verify`: a host line `n1-loop-a (ping host, 172.20.20.5): burst n1-loop 5 of 5
  replies from n1-loop-b at 10.1.11.2 held`; the counts line gains `burst 1 held`.
- `twin rehearse`'s stage lines gain `loss n1-loop 274/300, gap 54.8s`.
- A refusal: `probe n1-loop/b: interface n1:ethernet-1/1 is cabled (n1:ethernet-1/1|n2:ethernet-1/1);
  a probe takes an uncabled port that is not mgmt_only` (`probe.interface.cabled`).

### Identifiers

Data-model §12's table, copied, each with its severity, exit and step.

### Formats and versions

Probes `1` (new), probe package `0.1` (new), snapshot `2`, bundle `6`, `twin.json` `11`,
the step, verify and rehearsal documents moved without a findings version move; the four
goldens; the frozen copies under `019-following-removed/`.

### Workflows and activities

Four workflows; seventeen activities: `StartFlows` and `ReadFlows` join the lab's fifteen,
under the step's version marker `flows`.

### Tier 3 (`scripts/e2e.sh`)

Nine cases; probes in 5 (a file), 8 (the kind) and 9 (the stage `probe-port-down`).

### Upgrading

A snapshot `1` in the store reads as a `2` with no probes; a bundle `5` is refused by
`twin provision`; a twin of a `10` record steps, its `step.loss` null until it does.

## api.md: 016: probes

### The operations

| Operation | Arguments | Files |
|---|---|---|
| `intent.read` | `branch, at, stage, scope, out, probes` | the one file `probes` names |
| `twin.create` | `branch, at, stage, dry_run, scope, snapshot, probes` | one file beside `snapshot` **or** `probes`, never both |
| `twin.step` | `stage, snapshot, probes, allow_restart, dry_run, wait` | as `twin.create` |
| `stage.plan` | `branch, scope, probes` | the one file `probes` names |
| `twin.rehearse` | `branch, scope, probes` | the one file `probes` names |

`probes` is a path, as `snapshot` is, and the request's files hold that path's bytes; a
request naming `probes` with no file, or a file under another path, is `400 … the request
is not one`. The server reads the file as a declaration (`probes.schema.json`) and refuses
it under §12's rules at `start`. API version `1`, pre-1.0 as before.

### The answer

`intent.read`'s `files` frame carries a snapshot `2`. The document's `step` block gains
`loss`, `verify` gains `counts.burst` and `nodes[].bursts`, `rehearsal.stages[]` gains
`loss`; the markdown's table gains the column.
