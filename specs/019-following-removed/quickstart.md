# Quickstart: Following removed from the core

**Feature**: `019-following-removed` · **Plan**: [plan.md](plan.md)

How to prove the feature works, in the order it is built. Each section names what to run
and what must be true afterwards; the shapes are in [contracts/](contracts/) and
[data-model.md](data-model.md), the reasons in [research.md](research.md). Run from the
repository root, in a shell with `local/.env` loaded (`set -a; . local/.env; set +a`).

## 0. Before the work: the operator's

- D-062 is appended to `docs/decisions.md` and research R-27 is settled (2026-10-28).
- The roadmap's F-026 edits, D-062 and `specs/019-following-removed/` committed.

## 1. Tier 1

```sh
make test     # under 45 s, uncached: go clean -testcache first to time it
make lint
```

True afterwards:

- `TestWorkerRegistersEveryScheduledActivity` and `TestEveryActivityHasAFindingStep` count
  **4 workflows and 15 activities**; `Reconcile` is not registered.
- The seven remaining replays pass (`go test ./internal/provision -run Replay -v` lists
  seven), and none names `ReadIntent`, `Compile` or a follow activity.
- `twin create --interval 30s` and `--no-follow` fail with `unknown flag`, exit 2, and the
  harness logs no request; a raw `twin.create` request with `interval` or `no_follow` is
  `400 … takes no argument`.
- `twin step --snapshot` by id and by file from twins built by `--branch`, `--stage` and
  `--snapshot`; the bundle twin refused, naming no snapshot; `--stage` with `--snapshot`
  refused at start; no target for a stage-less twin refused before any connection; a stage
  of another proposed change stepped to; a snapshot of another branch stepped to and the
  record naming that branch; another scope and another mapping refused before any run,
  naming both.
- The kind line in each shape of [commands.md](contracts/commands.md), "The text"; none
  says pinned, frozen or following.
- A `--snapshot` twin stepped to a stage and a stage twin stepped to a snapshot each write a
  `twin.json` 10 valid under `contracts/twin.schema.json`; every frozen copy loads
  (`TestFrozenContractCopiesAgree`, the count research R-12 gives).
- `internal/rehearsal`: every computed deadline 30 s shorter (1,950, 2,580, 2,400, 690,
  5,520); `TestTheTwinCheckOutlastsItsRehearsal` unchanged and passing.
- The goldens: `go test ./internal/compiler` passes with no `-update`, `43d91715…`,
  `4213b3cf…`, `ecb665f5…`.

```sh
/usr/bin/grep -rniE 'fylgja-follow|StartFollowing|StopFollowing|ReadIntent|RunsInFlight|no_follow|no-follow|FollowBudget|\.reads' \
  --include='*.go' --include='*.sh' --include='*.json' internal cmd scripts contracts
```

matches only `scripts/e2e.sh`'s leak check (`FOLLOW_SCHEDULE`, `schedule_state`) and
comments that cite history; SC-002.

## 2. The host, after the rebuild

```sh
make build
pgrep -x fylgja | xargs -r kill        # then start both as CLAUDE.md prescribes
```

Start the worker and the server as `CLAUDE.md` prescribes, then verify:

- each `/proc/<pid>/exe` not `(deleted)`;
- the server's environment as before; the worker's carries both logins and
  `FYLGJA_STATE_ROOT` (it no longer needs `INFRAHUB_*`, research R-22);
- `local/worker.log`'s start-up names both packages; `local/server.log` as `CLAUDE.md`
  says;
- `~/.temporalio/bin/temporal schedule list --address localhost:7233` prints its header
  alone.

## 3. By hand: a step to a snapshot

On a throwaway branch, never `fylgja-fixture`, with no tier 2 running and `free -m` read
first:

```sh
B=fylgja-test-qs-$$
go run -tags fixture ./cmd/fylgja-fixture -branch "$B"
bin/fylgja twin create --branch "$B"
bin/fylgja twin show                  # kind: snapshot <short> (branch $B, read at …)
go run -tags fixture ./cmd/fylgja-fixture -branch "$B" -disable-port n1:ethernet-1/2 -generate
bin/fylgja twin show                  # the same kind line: nothing moved
bin/fylgja intent read --branch "$B" --out local/qs-1.json
bin/fylgja twin step --snapshot local/qs-1.json --dry-run   # twin:, target:, step, reconcile:, push:; no run
bin/fylgja twin step --snapshot local/qs-1.json             # stepped to snapshot …
bin/fylgja twin show                  # kind names the new snapshot, (stepped from snapshot …)
bin/fylgja twin verify                # n1:ethernet-1/2 and its link skipped
jq '.stage, .source, .snapshot_id, .twin_version' local/twin/twin.json   # null, "intent", <id>, "10"
bin/fylgja twin step                  # refused: the twin names no stage; give --stage or --snapshot
bin/fylgja twin step --snapshot "$(jq -r .snapshot_id local/twin/twin.json)"   # unchanged
bin/fylgja twin destroy               # no following line
go run -tags fixture ./cmd/fylgja-fixture -branch "$B" -delete
rm -f local/qs-1.json
```

True afterwards: `temporal workflow list` shows no run but the create, the steps and the
destroy. That no request reached Infrahub for a snapshot target is tier 2's to prove (its
counters, §4); by hand, stopping Infrahub's server container for the second step would
show it, and is not required.

## 4. Tier 2

```sh
make test-contract
```

No twin while it runs. True afterwards: `TestFollowingDetection` is gone;
`TestStepTargetFromASnapshot` passes (the snapshot target, by file and by id, files one
snapshot and compiles to `stage plan`'s bundle for the same read, with no second Infrahub
request); `internal/stages` and `internal/checks` pass; Infrahub left as the tier leaves
it (`CLAUDE.md`, Stages).

## 5. Tier 3

```sh
free -m
nohup make test-e2e > local/e2e-019.log 2>&1; echo $? > local/e2e-019.status &   # detached, as CLAUDE.md says
```

True afterwards: `E2E-OK`, nine cases; case 5's log shows the 330 s frozen wait with no run
started and the record, the containers and the kind line unchanged, then `stepped to
snapshot …` twice (by file, then by id), the readback, and verify 5a's skipped port and
link; `temporal schedule list` empty; the trap's leak check silent. About 32–33 minutes
whole.

## 6. The records at the close

- `/usr/bin/grep -niE 'follow|reconcile|schedule|interval|frozen|pinned' docs/architecture.md`
  and the glossary: following appears only as history (Governance), "reconcile" only as
  containerlab's phase, "pinned" only of a reference.
- `make diagrams` after the C4 edit; `make linkcheck` clean.
- `docs/verified-facts.md` and `CLAUDE.md` per research §4; the roadmap's F-026 marked
  built.
