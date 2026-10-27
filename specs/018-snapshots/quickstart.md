# Quickstart: Snapshots, the core's one input

**Feature**: `018-snapshots` · **Plan**: [plan.md](plan.md) · **Contracts**:
[snapshot.schema.json](contracts/snapshot.schema.json),
[snapshot-commands.md](contracts/snapshot-commands.md), [formats.md](contracts/formats.md)

How the feature is shown to work, in the order the work lands: the operator's
preconditions, tier 1, the hand checks on the development host, tier 2, tier 3, the
records. Every command runs from the repository root; `set -a; . local/.env; set +a`
first for anything that reaches the server. Expected outcomes are stated; a number marked
*candidate* is research §1.3's and the shipped code's own value stands.

## 0. Before the work: the operator's

1. **D-061 and Constitution 2.2.0** accepted at `analyze` from research §3: the entry
   appended to `docs/decisions.md`, the constitution's VI and version line amended, the
   plan template's Constitution Check naming 2.2.0. The records and the contracts move
   after this.
2. **The roadmap's edits committed**: `git status` shows `docs/roadmap.md` modified
   (F-024 reworded, F-026 added) from the brief's writing on 2026-10-27.
3. **Nothing on Infrahub moves.** No schema, fixture, query, template or check changes;
   `fylgja-fixture` stays as 017 re-seeded it. Infrahub's `main` holds no network (no
   demo window open).

## 1. Tier 1

```
make build && make test && make lint
```

Green, under 45 s uncached, with:

- `internal/snapshot`: two CTMs differing only in `observed_at` (`three-node.json`,
  `observed-later.json`) wrap to one id; a reordered CTM (`three-node.shuffled.json`)
  wraps to the same; one artifact byte changed, or one fidelity row added or altered,
  moves it; a stored body hashed by a test-local struct with the inner `observed_at`
  removed equals the stored id; the hashed envelope mirrors `ctm.Envelope` but
  `ObservedAt` (reflection); a `snapshot_version` of `"2"` or none, a non-empty or
  missing `probes`, a declared id the body does not hash to, a bare CTM, an outer
  `observed_at` unequal to the inner, each refused under its rule; `Put` twice keeps
  the first document and writes nothing; a corrupt entry is `ErrIDMismatch`.
- The three wrapped fixtures (`testdata/snapshot/`) compile to `43d91715…`, `4213b3cf…`
  and `ecb665f5…` byte for byte, and their inner CTMs equal `testdata/ctm/`'s.
- `twin.json` `9` against the contract; an `8` against the frozen copy; `NewRecord`'s
  rules by source (`snapshot` without an id refused; `bundle` with one refused; `intent`
  without one accepted).
- Every moved document against its contract and the frozen copies
  (`TestFrozenContractCopiesAgree` with the new count); the nine histories replay.
- The server over faked pipelines: a create reads, takes, compiles, files and starts with
  both ids; `--snapshot` with `--branch`/`--stage`/`--at`/`--scope` refused
  `snapshot.flags.conflict` and with `--interval` `follow.flags.conflict` before any
  connection; an unknown id `snapshot.unknown`; a mismatched file `snapshot.id.mismatch`;
  a file with no id filed and built; `intent read` answers `snapshot.json` and files;
  `twin compile --snapshot` compiles a wrapped fixture to its golden and files nothing;
  `twin show`'s record and kind lines for a `9` with and without a snapshot, an `8`, and
  a `source: snapshot` record.
- The client: `--snapshot` id versus file, an unreadable file refused before any
  connection, `--ctm` unknown; `--out` writes the snapshot that comes back.
- The rehearsal's table carries the `snapshot` column; `CommentMax` holds.

## 2. By hand: the hand tools

```
bin/fylgja twin compile --snapshot testdata/snapshot/three-node.json --out /tmp/s-three --json | jq -r '.snapshot_id, .bundle_id'
bin/fylgja twin compile --snapshot testdata/snapshot/mixed.json --out /tmp/s-mixed --json | jq -r .bundle_id
bin/fylgja twin compile --ctm testdata/ctm/three-node.json --out /tmp/x; echo "exit $?"
jq '{snapshot_version: "1", ctm: ., probes: []}' testdata/ctm/lossy.json > /tmp/hand.json && bin/fylgja twin compile --snapshot /tmp/hand.json --out /tmp/s-hand --json | jq -r '.snapshot_id, .bundle_id'
ls local/snapshots 2>/dev/null | wc -l   # before and after: twin compile files nothing
```

Expected: `6a8a77fc…` (*candidate*) and `43d91715…`; `ecb665f5…`; `unknown flag: --ctm`,
exit 2, no request (the server's log shows none); the hand-wrapped lossy CTM compiles to
`4213b3cf…` with its id computed (`91f06cd6…`, *candidate*); the store's count is
unchanged.

## 3. By hand: `intent read --out` and the same intent twice

```
bin/fylgja intent read --branch fylgja-fixture --out /tmp/snap-1.json; sleep 5
bin/fylgja intent read --branch fylgja-fixture --out /tmp/snap-2.json
jq -r .snapshot_id /tmp/snap-1.json /tmp/snap-2.json
diff /tmp/snap-1.json /tmp/snap-2.json
ls -la local/snapshots/$(jq -r .snapshot_id /tmp/snap-1.json).json && cmp /tmp/snap-1.json local/snapshots/$(jq -r .snapshot_id /tmp/snap-1.json).json && echo stored-is-the-first-take
jq --indent 2 'del(.snapshot_version, .snapshot_id, .observed_at, .ctm.envelope.observed_at)' /tmp/snap-1.json | sha256sum
```

Expected: one id twice (`576933ec…`, *candidate*: the shipped code's value is **the
fixture's snapshot id for `CLAUDE.md`**); the diff is the two `observed_at` lines (outer
and inner) and nothing else; the store holds the first take byte for byte; the summary
line ends `; snapshot <id>, stored at <path>`; the `jq` recipe gives the id.

## 4. By hand: a create the server takes a snapshot for

```
bin/fylgja twin create --branch fylgja-fixture --dry-run
bin/fylgja twin create --branch fylgja-fixture --no-follow --json > /tmp/create.json; jq -r '.status, .snapshot_id, .bundle_id' /tmp/create.json
RUN=$(jq -r .subject.run_id /tmp/create.json); ~/.temporalio/bin/temporal workflow show -w fylgja-provision -r "$RUN" -o json | jq -r '[.events[] | .activityTaskScheduledEventAttributes.activityType.name // empty] | unique'
bin/fylgja twin show
jq '.twin_version, .snapshot_id, .source, .step' local/twin/twin.json
find local/bundles -maxdepth 1 -name '*.ctm.json' -newer /tmp/create.json | wc -l
```

Expected: the dry run prints `snapshot_id … stored: …/local/snapshots/….json` then
`bundle_id f764e1fa… stored: …`, `follow: would not follow (--no-follow given)` is absent
(no flag), `verdict: clear`; the create ends `ok` with the same two ids; the run's
activities are `CheckHost, StageBundle, DeployLab, AwaitReadiness, PushConfig, RecordTwin,
StopFollowing` and no `ReadIntent` or `Compile`; `twin show`'s record line reads `record:
branch fylgja-fixture, snapshot <id>, bundle_id f764e1fa…, schema 7c413536…, scope
tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9` and the kind
`frozen; not following`; `twin.json` is `"9"`, names the snapshot, `source` `intent`,
`step` null; no sidecar is newer than the create. Then a read refused (a throwaway branch
with a device of an unmatched platform, as `TestPlatformsTheReadRefuses` seeds one, or
`--scope tag:nothing`): `twin create` ends `rejected` at `read`, no run starts, and
`local/snapshots` gains nothing.

## 5. By hand: a twin from a snapshot, frozen

```
SID=$(jq -r .snapshot_id /tmp/create.json); bin/fylgja twin destroy
bin/fylgja twin create --snapshot "$SID" --interval 1m; echo "exit $?"            # refused before any connection
bin/fylgja twin create --snapshot "$SID" --branch fylgja-fixture; echo "exit $?"   # refused before any connection
bin/fylgja twin create --snapshot 0000000000000000000000000000000000000000000000000000000000000000; echo "exit $?"
bin/fylgja twin create --snapshot "$SID" --json > /tmp/create-s.json; jq -r '.status, .snapshot_id, .bundle_id' /tmp/create-s.json
bin/fylgja twin show; jq '.source, .snapshot_id, .observed_at, .stage' local/twin/twin.json
~/.temporalio/bin/temporal schedule describe -s fylgja-follow; echo "exit $?"      # absent
bin/fylgja twin step --stage fylgja-fixture/head; echo "exit $?"                   # step.twin.unsteppable
bin/fylgja twin destroy
jq 'del(.snapshot_id)' /tmp/snap-1.json > /tmp/snap-noid.json && bin/fylgja twin create --snapshot /tmp/snap-noid.json --json | jq -r '.status, .snapshot_id'
jq '.snapshot_id = "1111111111111111111111111111111111111111111111111111111111111111"' /tmp/snap-1.json > /tmp/snap-bad.json && bin/fylgja twin create --snapshot /tmp/snap-bad.json; echo "exit $?"
bin/fylgja twin destroy
```

Expected, in order: `follow.flags.conflict`, exit 2, `--interval is meaningless with
--snapshot: a twin built from a snapshot never follows`; `snapshot.flags.conflict`, exit
2, naming `--branch`; `snapshot.unknown` at `resolve`, exit 1, naming the id and the store;
the create ends `ok` with `f764e1fa…`, the server's log showing no request to Infrahub
(no `intent` read lines), `twin show` reading `kind: frozen; not following; built from
snapshot <id8>…` and the record line as in §4, `twin.json` with `source` `snapshot`, the
stored take's `observed_at` (§3's first take) and `stage` null; the Schedule absent; the
step refused `step.twin.unsteppable` ("created from branch fylgja-fixture, not from a
stage"); the file without an id builds a twin under the same id; the file with a wrong
id is `snapshot.id.mismatch`, exit 1, naming both ids. With `--at`: a snapshot of a
pinned read (`intent read --branch fylgja-fixture --at <T> --out …`) creates a twin whose
kind reads `pinned at <T>; not following; built from snapshot …`.

## 6. By hand: stages, a step and a rehearsal name the snapshot

As 015's quickstart composes a throwaway proposed change (`B=fylgja-test-018`):

```
go run -tags fixture ./cmd/fylgja-fixture -branch $B
go run -tags fixture ./cmd/fylgja-fixture -branch $B -propose
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage seeded -description seeded
go run -tags fixture ./cmd/fylgja-fixture -branch $B -add-link
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage third-link -description "third link"
bin/fylgja stage plan --branch $B --json > /tmp/plan.json; jq -r '.plan.stages[] | "\(.ref) \(.snapshot_id) \(.bundle_id)"' /tmp/plan.json
bin/fylgja stage plan --branch $B --json | jq -r '.plan.stages[].snapshot_id' | diff - <(jq -r '.plan.stages[].snapshot_id' /tmp/plan.json) && echo same-ids-twice
bin/fylgja twin create --stage $B/seeded && bin/fylgja twin step --stage $B/third-link --allow-restart --json > /tmp/step.json
jq -r '.snapshot_id, .step.from.snapshot_id, .step.to.snapshot_id' /tmp/step.json; jq '.snapshot_id, .step.from.snapshot_id, .step.to.snapshot_id' local/twin/twin.json
bin/fylgja twin destroy
bin/fylgja twin rehearse --branch $B --markdown > /tmp/rehearsal.md; grep -m1 '| stage |' /tmp/rehearsal.md
go run -tags fixture ./cmd/fylgja-fixture -branch $B -delete
```

Expected: the branch point refused `scope.empty` with `null` ids, three compiled stages
each with a snapshot id beside its bundle id, printed as `  snapshot_id …` over
`  bundle_id …`; the second plan's ids equal the first's; the step's document and the
record name the from side's snapshot (seeded's) and the to side's (third-link's), the top
level the to side's; the report's header reads `| stage | at | snapshot | bundle | step |
wait | verify | new verification failures | verdict |`, within 4,092 bytes.

## 7. Tier 2

No twin on the host (`twin show` → `none`), the worker and the server from this tree
(§0 of `CLAUDE.md`'s rules; `/proc/<pid>/exe` not deleted), then:

```
set -a; . local/.env; set +a; make test-contract 2>&1 | tee local/018-contract.out; tail -5 local/018-contract.out
```

Green, about a minute over 017's 1,714.7 s, with `TestPinnedReadReproducesItsBundle`
logging one snapshot id for the three pinned reads and another for the unpinned,
`TestStageTakenTwiceHasOneSnapshot` logging the id and the store's unchanged entry, and
`internal/stages` and `internal/checks` green. After it: `CoreProposedChange`,
`FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` count 0, `Branch` lists `main`
and `fylgja-fixture` alone, no `fylgja-test-*` branch remains.

## 8. Tier 3

The dev server and the worker up, Docker, containerlab, both images, Infrahub, the
server on the bridge, both checks imported, `free -m` read, no tier 2 running:

```
set -a; . local/.env; set +a; setsid nohup sh -c 'make test-e2e > local/018-e2e.out 2>&1; echo $? > local/018-e2e.exit' < /dev/null > /dev/null 2>&1 &
```

Then wait in foreground calls of under ten minutes until `local/018-e2e.exit` exists.
`E2E-OK` in about 29.5 minutes; then `PLATFORMS=nokia_srlinux make test-e2e` ending
`E2E-PARTIAL` in about 19. The outputs show every create's `snapshots/<id>.json`, case
1's `twin show` text holding `snapshot <id>, bundle_id <id>`, case 5's rebuilt twin
reading `.show.record.snapshot_id == null`, and case 7's steps naming the target's
snapshot. Rest the host between the two runs.

## 9. The records at the close

- `CLAUDE.md`: Formats (snapshot `1`, `twin.json` `9`, `--ctm` retired), State (018
  closed; the fixture's snapshot id from §3 beside `f764e1fa…`), Build and test (tier 2's
  and tier 3's new timings), the worker's and server's state root lines.
- `docs/verified-facts.md`: research §1.2 and §1.3 under 10-27, and the stage-twice
  result from §7.
- `docs/architecture.md` grepped for `ctm.json`, `.reads`, `ReadIntent`, `--ctm` and
  "read and compile" and each sentence made true; `docs/glossary.md` likewise; the C4
  model redrawn (`make diagrams`); `docs/development.md`; `README.md`; `docs/roadmap.md`
  (F-024 built).
- `make linkcheck` clean; the credential greps over the tree nothing.
- D-061 and Constitution 2.2.0 in place (the operator's; §0).
