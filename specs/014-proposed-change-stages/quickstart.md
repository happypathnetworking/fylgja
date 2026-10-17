# Quickstart: validating a proposed change's stages

**Feature**: `014-proposed-change-stages` · **Plan**: [plan.md](plan.md) · **Contracts**:
[contracts/](contracts/)

What proves the feature, scenario by scenario, in the order the work lands (plan, "Order
of the work"). Each names its prerequisites, the commands and what must come out.
Credentials: nothing below prints one; `local/.env` is the one file that holds a value.
Every write to Infrahub is on a `fylgja-test-*` branch and deleted by what made it, except
scenario 1's migration of `main`, which is the feature's.

## Prerequisites

- The development host as `CLAUDE.md` describes it: Infrahub 1.11.2 up, `main` at hash
  `e7386419…` with the candidate kind, the fixture branch seeded, `local/.env` loaded
  (`set -a; . local/.env; set +a`), Docker and containerlab reachable from the shell.
- For scenarios 7 and 8: the dev server and a worker from this tree, both images, a quiet
  host (`free -m`), the server restarted after every rebuild.

## 1. The kind migrates onto `main` (FR-001, FR-002; tasks T003–T004)

```sh
.venv/bin/infrahubctl schema check --branch main schema/
go run -tags fixture ./cmd/fylgja-fixture -prepare-main
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" "$INFRAHUB_ADDRESS/api/schema" | jq -c '[.nodes[] | select(.kind | startswith("Fylgja")) | .kind], (.nodes[] | select(.kind=="FylgjaStage") | [.attributes[].name]), (.nodes[] | select(.kind=="CoreProposedChange") | [.relationships[] | select(.name=="fylgja_stages") | .peer])'
make sdl && make generate && go build ./... && git status --short schema/ internal/intent/
```

Expected: the check's diff is `FylgjaStage: attributes: added: description; changed:
label` and nothing else (`FylgjaWaypoint` shows no diff: its file is still in `schema/`);
`schema loaded on main`, the group and the repository `present`; the kinds list
`FylgjaContract`, `FylgjaDevice`, `FylgjaInterface`, `FylgjaLink`, `FylgjaPlatform`,
`FylgjaStage` and, until §1b, `FylgjaWaypoint`; the attributes `as_of`, `description`,
`label` (in Infrahub's order); the extension's peer `FylgjaStage`; the SDL and the
generated client changed and nothing else. `GET /api/schema/summary` gives `main`'s new
hash. Then `fylgja intent read --branch fylgja-fixture` through a restarted server still
compiles, via `twin compile`, to `47b2c449…`.

## 1b. The waypoint kind leaves `main`, after the switch (FR-002; task T042)

Only once the waypoint code and its `Waypoints` query are out of the tree (T030): genqlient
validates every query against the SDL, so the kind cannot leave `main` before the query
leaves the tree.

```sh
.venv/bin/infrahubctl schema check --branch main specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml
.venv/bin/infrahubctl schema load  --branch main specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" "$INFRAHUB_ADDRESS/api/schema" | jq -c '[.nodes[] | select(.kind | startswith("Fylgja")) | .kind]'
.venv/bin/infrahubctl schema check --branch main specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml
make sdl && make generate && go build ./... && git status --short schema/ internal/intent/
```

Expected: the first check prints `removed: FylgjaWaypoint`; the load takes about 40 s; the
kinds list the five generics and `FylgjaStage` and no `FylgjaWaypoint`; the second check
prints `No diff`; the SDL's diff removes the waypoint's types alone and `generated.go` is
unchanged. `GET /api/schema/summary` gives the hash `CLAUDE.md` records.

## 2. Tier 1 (FR-027, SC-006)

```sh
make build && make test && make lint
```

Expected: green, under 35 s wall uncached. Among the tests that must exist and pass:
`TestLabelPatternEqualsTheKinds`, `TestOrderEndsFixed` (a mark stamped after the head's
`at` still sorts before it), `TestHeadIsLatestStampPlusOneMicrosecond` (the formatting),
`TestResolveRefusals` (each rule of [contracts/stage-reference.md](contracts/stage-reference.md)
from a faked reader, none reading a branch's intent), `TestRebaseIsNamed`,
`TestStalePerDevice` (checksum alone; validator alone; identical bytes; a neighbour's
rename not named), `TestMainMovedWarns`, `TestTargetByPosition` (foreign, unknown,
current by resolved reference, a moved head as a target, skipped), `TestRecord6` and the
`5` record read with no stage, the renderings against `stages.schema.json`, the replays of
the three step histories, `TestFrozenContractCopiesAgree` at 29, the boundary test, the
platform grep with `stages` in its list, `TestQueryRootsAreFylgjaGenerics` with its three
named exceptions.

## 3. The surface by hand, on a throwaway proposed change (US1, US3, US4)

```sh
B=fylgja-test-qs-$$
go run -tags fixture ./cmd/fylgja-fixture -branch $B
go run -tags fixture ./cmd/fylgja-fixture -branch $B -propose
bin/fylgja stage plan --branch $B --json | jq -c '{status, stages: [.plan.stages[] | {label, at_source, bundle_id, rule: (.findings | map(select(.severity=="rejection")) | .[0].rule)}], steps: [.plan.steps[] | {from, to, computed, unchanged}]}'
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage seeded -description seeded
go run -tags fixture ./cmd/fylgja-fixture -branch $B -set-role stale-probe
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage stale
bin/fylgja stage plan --branch $B --json | jq -c '[.plan.stages[] | {label, rule: (.findings | map(select(.severity=="rejection")) | .[0].rule), devices: [.findings[] | select(.rule=="stage.artifact.stale") | .object]}]'
ck() { curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql/$B" --data-binary '{"query":"{ CoreArtifact { edges { node { checksum { value } } } } }"}' | jq -c '[.data.CoreArtifact.edges[].node.checksum.value]'; }
BEFORE=$(ck)
go run -tags fixture ./cmd/fylgja-fixture -branch $B -generate
until ck | jq -e --argjson b "$BEFORE" 'length == 3 and all(.[]; IN($b[]) | not)' > /dev/null; do sleep 1; done
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage fresh
bin/fylgja stage list --branch $B
bin/fylgja intent read --stage $B/fresh --out /tmp/fresh.ctm.json && AT=$(jq -r .envelope.at /tmp/fresh.ctm.json) && bin/fylgja intent read --branch $B --at "$AT" --out /tmp/at.ctm.json && diff <(jq 'del(.envelope.observed_at)' /tmp/fresh.ctm.json) <(jq 'del(.envelope.observed_at)' /tmp/at.ctm.json) && echo same
bin/fylgja twin create --stage $B/fresh --branch $B --dry-run; echo "exit $?"
bin/fylgja stage plan --branch no-such-branch; echo "exit $?"
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage head
bin/fylgja stage list --branch $B; echo "exit $?"
go run -tags fixture ./cmd/fylgja-fixture -branch $B -close
bin/fylgja stage list --branch $B; bin/fylgja stage plan --branch $B; echo "exit $?"
go run -tags fixture ./cmd/fylgja-fixture -branch $B -delete
bin/fylgja stage list
```

Expected, in order: the first plan lists `branch-point` refused `contract.node.missing`
and `head` compiled, one step not computed (`status rejected`, exit 1, on this install);
after `stale`: `seeded` compiled, `stale` refused `stage.artifact.stale` naming `n1`, `n2`,
`n3`, `head` refused the same (the role is unrendered until a generate); the three
checksums move a few seconds after `-generate` returns (it waits for Ready, which a
rewrite never leaves, so `fresh` is marked only once they have: a mark made before them is
refused stale, rightly); after the generate
and `fresh`: `seeded`, `stale` (still refused: pinned at its own `at`, its artifacts are
the old ones), `fresh` and `head` compiled, the step `fresh → head` `unchanged`; the list
shows five stages with no twin mark; the CTM from `--stage` equals the one from `--branch
--at` but for `observed_at` (`same`); the dry run is refused `stage.flags.conflict` naming
`--branch`, exit 2; the unknown branch is `stage.unknown` saying no open proposed change
has it, exit 1; after a mark labelled `head`, the list is `rejected` with
`stage.label.reserved` beside it and the derived head still listed, exit 1; after the
close, the list prints `branch …: no open proposed change` and the plan is `stage.unknown`,
exit 1; after `-delete` the list prints `no open proposed change`.

## 4. The rebase and the orphan (US1 scenario 5, US3 scenario 3)

```sh
B=fylgja-test-qs-rb-$$
go run -tags fixture ./cmd/fylgja-fixture -branch $B && go run -tags fixture ./cmd/fylgja-fixture -branch $B -propose
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage one && go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage two
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"mutation { BranchRebase(data: {name: \\\"$B\\\"}, wait_until_completion: true) { ok } }\"}"
bin/fylgja stage plan --branch $B --json | jq -c '[.plan.stages[] | {label, rule: (.findings | map(select(.severity=="rejection")) | .[0].rule), msg: (.findings | map(select(.rule=="stage.at.before_branch_point")) | .[0].message)}]'; echo "exit ${PIPESTATUS[0]}"
PC=$(curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"{ CoreProposedChange(source_branch__value: \\\"$B\\\") { edges { node { id } } } }\"}" | jq -r '.data.CoreProposedChange.edges[0].node.id')
pcdelete() { curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"mutation { CoreProposedChangeDelete(data: {id: \\\"$PC\\\"}) { ok } }\"}" | jq -c '{ok: .data.CoreProposedChangeDelete.ok, code: .errors[0].extensions.code}'; }
pcdelete
IDS=$(curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"{ CoreProposedChange(ids: [\\\"$PC\\\"]) { edges { node { fylgja_stages { edges { node { id } } } } } } }\"}" | jq -c '[.data.CoreProposedChange.edges[0].node.fylgja_stages.edges[].node.id]')
jq -nc --arg pc "$PC" --argjson ids "$IDS" '{query: "mutation { RelationshipRemove(data: {id: \"\($pc)\", name: \"fylgja_stages\", nodes: [\($ids | map("{id: \"\(.)\"}") | join(", "))]}) { ok } }"}' | curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary @- | jq -c .data
bin/fylgja stage list --json | jq -c '{orphans: [.stages.orphans[].label], warnings: [.findings[] | select(.rule=="stage.orphaned") | .object]}'; echo "exit ${PIPESTATUS[0]}"
pcdelete
go run -tags fixture ./cmd/fylgja-fixture -branch $B -delete
bin/fylgja stage list; echo "exit $?"
for id in $(jq -r '.[]' <<< "$IDS"); do curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"mutation { FylgjaStageDelete(data: {id: \\\"$id\\\"}) { ok } }\"}" | jq -c .data; done
bin/fylgja stage list
```

Expected: after the rebase (about 20 s on a seeded branch with nothing on `main` to take;
§2.7 read 67 s) both marks are refused `stage.at.before_branch_point` with a message
naming the rebase and both stamps, and the branch point and the head are planned (the
branch point refused `contract.node.missing` on this install). Infrahub then **refuses**
the proposed change's delete while its stages name it (`ATTRIBUTE_CONSTRAINT_VIOLATION`,
`Cannot delete CoreProposedChange '<id>'. It is linked to mandatory relationship
proposed_change on node FylgjaStage '<id>'`; research §8.8): with the kind on `main` a
proposed change is never deleted under its stages. Removing the stages from its
`fylgja_stages` is accepted and leaves each naming no proposed change: the list carries
the proposed change with its two derived stages, then two orphans and two
`stage.orphaned` warnings, exit 0. The proposed change's delete then succeeds. `-delete`
removes the branch and no stage (`deleted 0 stages, 0 proposed changes, branch …`), since
nothing ties an orphan to its branch any more, so the list still carries the two orphans
until they are deleted by id; after that it prints `no open proposed change`.

## 5. Tier 2 (FR-028, SC-006)

```sh
make test-contract
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary '{"query":"{ Branch { name } CoreProposedChange { count } FylgjaStage { count } }"}' | jq -c .data
```

Expected: green, with `TestStageKindLoads` (the kind and the extension on `main`; a
duplicate label refused from the branch), `TestStagesListAndPlan` (four stages, three
steps, the ids), `TestStageRefusals` (stale, rebase, reserved, closed, unknown), the
deletion in order inside each test; after it, `main` and `fylgja-fixture` alone, zero
proposed changes, zero stages. About three minutes longer than before.

## 6. The records and the tree (US5, SC-009)

```sh
/usr/bin/grep -rn -i 'waypoint' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=local --exclude-dir=bin --exclude-dir=specs --exclude-dir=testdata --exclude='*_test.go' . | /usr/bin/grep -v -E '^\./(docs/decisions\.md|docs/archive/|docs/glossary\.md|docs/how-it-was-built\.md|docs/recording/|README\.md|CLAUDE\.md|contracts/(api|cli)\.md|contracts/[a-z]+\.schema\.json|docs/architecture\.md|docs/roadmap\.md|internal/lab/twin\.go|internal/provision/workflow_step\.go)'
for f in README.md CLAUDE.md contracts/api.md contracts/cli.md docs/architecture.md docs/roadmap.md internal/lab/twin.go internal/provision/workflow_step.go; do echo "== $f"; /usr/bin/grep -n -i waypoint "$f"; done
for f in contracts/*.schema.json; do jq -r '[.. | objects | to_entries[] | select(.key != "description") | .key, (.value | strings)] | .[]' "$f" | /usr/bin/grep -i waypoint; done
/usr/bin/grep -rl -i waypoint --include='*_test.go' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=local .
test ! -e schema/fylgja-waypoint.yaml && test ! -e contracts/waypoints.schema.json && bin/fylgja --help | /usr/bin/grep -c -i waypoint
make diagrams && git status --short docs/c4 docs/diagrams
```

Expected: the first grep prints nothing (the glossary's superseded entries, the decision
log, the archive, the write-up's milestone row, the recording's caption and the frozen
`twin.schema.json` copies under `testdata/` are the allowed history); the second, over the
excluded records, shows in each only what SC-009 allows: the README's note beside the
recording, `CLAUDE.md`'s Milestones lines, the contracts' rows marked moved at 014, the
architecture's one sentence saying what replaced the waypoint, the roadmap's F-023,
`twin.go`'s `5`-record wording and `workflow_step.go`'s `step.twin.unsteppable` refusal
of a `5` record; the third prints nothing, since a contract's schema names the waypoint in
its description alone, in the history of its versions and the one sentence saying what
replaced it at 014; the fourth lists the tests that name it, each only as FR-021's older
records (`internal/lab`, `internal/cli`'s show, step and verify tests, the replay's
rewritten histories), FR-028's absent kind (`internal/stages`'s contract test), or a
refusal a contract requires: `fylgja waypoint list` unknown (the repository's
`contracts/cli.md`), `/v1/waypoint/*` `404` and a `waypoint` argument `400` (its
`contracts/api.md`; `internal/server`, `internal/api`), M10's shape refused where a stage goes, and the `5`-record refusal
(`internal/provision`); the three tests print `0`; the diagrams are regenerated with
`stages` where `waypoint` was and nothing else moved. *(Run 17, T055: the first grep
excluded neither `*_test.go`, the contracts' schemas nor `workflow_step.go`, so it could not
print nothing while FR-021's and FR-028's tests and SC-009's `5`-record refusal stand; the
third and fourth lines check what it now leaves out.)*

## 7. Tier 3 (FR-029, SC-006)

```sh
free -m
set -a; . local/.env; set +a
setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja worker run >> local/worker.log 2>&1 < /dev/null &
(make test-e2e > local/e2e-014.log 2>&1; echo $? > local/e2e-014.status) &
```

Then wait in foreground calls of under ten minutes. Expected: `E2E-OK` after about 19–21
minutes; case 7's log lines name the plan's four stages, the branch point refused
`contract.node.missing`, one create from `seeded` carrying the plan's id, a step to
`third-link`, an `unchanged` step to `head` with the record moving; case 8's the step forward with
`--allow-restart` and back with `--stage`; after the run no lab, no twin directory, no
Schedule, no `fylgja-test-*` branch, proposed change or stage. Then `PLATFORMS=nokia_srlinux
make test-e2e` ends `E2E-PARTIAL`, case 7 run and 8 skipped.

## 8. The README's walk-through by hand (SC-010)

Follow "A stepping twin" as rewritten: seed `fylgja-test-readme`, `-propose`, `-stage
seeded`, `-add-link`, n1's and n3's checksums awaited (as §3 awaits them: `-add-link`
returns before the rewrite lands), `-stage third-link`, `stage plan`, `twin create --stage
fylgja-test-readme/seeded`, `twin step --dry-run`, `twin step`, `twin verify`, `stage list`,
`twin step --stage fylgja-test-readme/seeded`, `twin destroy`, `-delete`. Expected: the
outputs the README shows, with the stage lines; nothing left in Infrahub.

## 9. The close

`CLAUDE.md`'s Formats (`twin.json` `6`) and State (`main`'s hash, 014 built, 015 next),
`docs/development.md` (the layout, the tiers, the fixture tool, the walk-through's
numbers), `docs/verified-facts.md` (research §6), the glossary, the roadmap (F-023 built),
`docs/ideas.md` (the persistent series closed), `docs/brief.md`, the C4 model; D-046 written
or declined by the operator; the upstream request drafted under this feature's directory
through `infrahub-reporting-issues`, not filed.
