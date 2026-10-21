# Quickstart: validating a proposed change rehearsed on a twin

**Feature**: `015-proposed-change-rehearsal` · **Plan**: [plan.md](plan.md) · **Contracts**:
[contracts/](contracts/)

What proves the feature, scenario by scenario, in the order the work lands (plan, "Order
of the work"). Each names its prerequisites, the commands and what must come out. Nothing
below prints a credential; `local/.env` is the one file that holds a value. Every write to
Infrahub is on a `fylgja-test-*` branch or a `fylgja-test-*` registration, deleted by what
made it; the one lasting write is the operator's import of the checks (§6).

## Prerequisites

- The development host as `CLAUDE.md` describes it: Infrahub 1.11.2 up, `main` at
  `e43a1cde…`, the fixture branch seeded, `local/.env` loaded, Docker and containerlab in
  the shell, the dev server up.
- For §2 on: the worker and the server restarted from this tree (`CLAUDE.md`, the two start
  lines; the server's with both `--listen` flags from §2).
- For §4, §7 and §8: a quiet host (`free -m`), both images.

## 1. Tier 1 (FR-028, SC-010)

```sh
make build && make test && make lint
```

Expected: green, under 45 s wall uncached. Among the tests that must exist and pass:
`internal/rehearsal`'s `TestVerdict` (a finding the baseline had, one it did not, one the
baseline alone had, a divergence at each phase, a wait incomplete, a stage not reached, a
settled wait, `verify.record.holds` ignored), `TestDeadline` (the fixture's 1,980 s, the
mixed fixture's, the ceiling refused), `TestMarkdown` (the table, the drawing with a refused
branch point, an unchanged edge and a failed stage, the escaping, the caveat, the reproduce
commands, no content line), `TestReproduce`, `TestBlockValidates` against
`contracts/rehearsal.schema.json`, and `TestRehearsalIsPure` in `step`'s shape;
`internal/provision`'s `TestRehearseEveryStagePasses`, `TestRehearseStopsAtAFailedStage`,
`TestRehearseBaselineNotBuilt`, `TestRehearseStepRejectedIsError`,
`TestRehearseDeadlineCutsAStepAndDestroys`, `TestRehearseCancelledDestroys`,
`TestRehearseDestroyUnclean`, `TestRehearseOneStage`, each under the test suite with faked
children, and the nine recorded histories replaying unchanged; `internal/lab`'s
`TestRecord7` and the `6` record read with no rehearsal, `TestFrozenContractCopiesAgree` at
30; `internal/findings`'s rehearsal block against the schema; `internal/api`'s frames with
`markdown`; `internal/cli`'s `twin rehearse` through the harness (ok, nonconforming, the
refusals, `--markdown`, `--markdown --json` refused with no request) and the boundary test;
`cmd/fylgja`'s `--listen` repeated (both lines, the unencrypted line, one address refused
and none listening); the root's `TestInfrahubYAMLRegistersTheChecks`.

## 2. The server on the bridge, the override, the task workers (FR-024–FR-026, SC-009; the operator's)

```sh
BRIDGE=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'); echo "$BRIDGE"
cp scripts/infrahub/docker-compose.override.yml local/infrahub/docker-compose.override.yml
docker compose -p fylgja-infrahub --env-file local/.env -f local/infrahub/docker-compose.yml -f local/infrahub/docker-compose.override.yml up -d
pkill -x fylgja; sleep 1
set -a; . local/.env; set +a
setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja worker run >> local/worker.log 2>&1 < /dev/null &
setsid nohup env FYLGJA_STATE_ROOT="$PWD/local" bin/fylgja serve --listen 127.0.0.1:7650 --listen "$BRIDGE:7650" >> local/server.log 2>&1 < /dev/null &
sleep 1; tail -12 local/server.log
docker exec fylgja-infrahub-task-worker-1 python -c "import httpx,os; a=os.environ['FYLGJA_API_ADDRESS']; r=httpx.post(f'http://{a}/v1/twin/show', json={}, headers={'Authorization':'Bearer '+os.environ['FYLGJA_API_TOKEN']}, timeout=15); print(r.status_code, r.headers.get('Fylgja-Api-Version'), r.headers.get('Fylgja-Build')); print(httpx.post(f'http://{a}/v1/twin/show', json={}, timeout=15).status_code)"
curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://$BRIDGE:7650/v1/twin/show"
```

Expected: the two task workers recreated; the server's report with two listen lines, the
bridge's followed by its unencrypted line, and both packages with their logins set; from
inside a task worker `200 1 <build>` then `401`; from the host without the token `401`. The
bring-up script's `fylgja` part, run again, reports the server `present`.

## 3. The rehearsal by hand (US1; FR-001–FR-015)

```sh
B=fylgja-test-qs-$$
go run -tags fixture ./cmd/fylgja-fixture -branch $B
go run -tags fixture ./cmd/fylgja-fixture -branch $B -propose
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage seeded -description seeded
ck() { curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql/$B" --data-binary '{"query":"{ CoreArtifact { edges { node { checksum { value } } } } }"}' | jq -c '[.data.CoreArtifact.edges[].node.checksum.value]'; }
BEFORE=$(ck); go run -tags fixture ./cmd/fylgja-fixture -branch $B -add-link
until ck | jq -e --argjson b "$BEFORE" '. as $n | ($n - $b | length) == 2' > /dev/null; do sleep 1; done
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage third-link -description "third link"
bin/fylgja stage plan --branch $B; echo "exit $?"
bin/fylgja twin rehearse --branch $B; echo "exit $?"
bin/fylgja twin show
bin/fylgja twin rehearse --branch $B --json > /tmp/rehearsal.json; echo "exit $?"
jq -c '{status, stages: [.rehearsal.stages[] | {ref, role, verdict, new: (.new_findings | length)}], deadline: .rehearsal.deadline_s, used: .rehearsal.used_s, reproduce: .rehearsal.reproduce}' /tmp/rehearsal.json
bin/fylgja twin rehearse --branch $B --markdown > /tmp/rehearsal.md; echo "exit $?"; head -20 /tmp/rehearsal.md
```

Expected: the plan as 014 prints it (the branch point refused, three ids); the rehearsal
prints the stage lines, the provision's, the baseline's verify (`settled`, 15 held), the
two steps (`stepped` with n1 and n3 pushed, then `unchanged`), the destroy, and `rehearsal
ok`, exit 0; `twin show` reports no twin; the document's rows read `refused`, `baseline`,
`passed`, `passed`, `deadline_s` 1980, `reproduce` empty; the markdown begins with the
heading naming the run and `resolved_at`, then the table.

Then the failing stage, the interrupt and the reclaim:

```sh
BEFORE=$(ck); go run -tags fixture ./cmd/fylgja-fixture -branch $B -add-interface n1:ethernet-1/99
go run -tags fixture ./cmd/fylgja-fixture -branch $B -generate
until ck | jq -e --argjson b "$BEFORE" '. as $n | ($n - $b | length) == 1' > /dev/null; do sleep 1; done
go run -tags fixture ./cmd/fylgja-fixture -branch $B -stage bad-port -description "a port n1 does not have"
bin/fylgja twin rehearse --branch $B; echo "exit $?"
bin/fylgja twin create --stage $B/seeded && bin/fylgja twin step --stage $B/third-link --allow-restart && bin/fylgja twin step --stage $B/bad-port --allow-restart; echo "exit $?"
bin/fylgja twin verify; echo "exit $?"; bin/fylgja twin destroy
bin/fylgja twin rehearse --branch $B & sleep 75; kill -INT %1; wait %1; echo "exit $?"; bin/fylgja twin show
```

Expected: `bad-port` fails at phase `push`, n1 `push.refused`, `head` `not reached`, exit
5, the twin destroyed, the closing lines giving five reproduce commands, since `bad-port`
is the second rehearsed stage and each one up to it is stepped through: `twin create
--stage $B/seeded`, `twin step --stage $B/third-link --allow-restart`, `twin step --stage
$B/bad-port --allow-restart`, `twin verify` and `twin destroy`. Run by hand, the step to
`bad-port` ends `diverged` at push the same way (exit 4), `twin verify` fails on the
record's claim (exit 5), and the destroy clears it (research §5.2). The interrupt during
the step cancels it (`run.cancelled`, the record diverged), the destroy runs, exit 2, and
`twin show` reports no twin. A second `twin rehearse` started while a create of your own
runs is refused `run.in_flight` at once.

The reclaim needs the run ended, which a run with no worker cannot do by itself: it has no
execution timeout, and its own destroy needs a worker (research §5.2). Start a rehearsal
and stop the worker while the baseline is being deployed; end the run with `temporal
workflow terminate --workflow-id fylgja-rehearse`, which runs no destroy; restart the
worker, so that the abandoned provision child ends ready and records the twin naming the
dead run; then run `twin rehearse` again: it prints `reclaiming the twin of rehearsal run
…`, the destroy's lines, and goes on (`rehearsal.twin.reclaimed`). A client still following
the terminated run answers only once that child closes, `operation.failed` (`terminated`),
exit 2. Finally `go run -tags fixture ./cmd/fylgja-fixture -branch $B -delete`.

## 4. The checks by hand, through a test-only registration (US2, US3; before the push)

```sh
go test -count=1 -tags contract ./internal/checks -run 'TestChecksInsideInfrahub' -v
```

Expected: the test serves the tree's checks from the bridge, registers
`fylgja-test-checks-<pid>`, seeds a branch, opens a draft with two marks, reads
`fylgja-twin` `success` with `skipped a draft` and `fylgja-step` `success` with the plan's
text and the branch point's refusal, marks a stage stale, re-runs the user checks and reads
`fylgja-step` `failure` naming `stage.artifact.stale` and the device; then deletes the
branch and the registration. On this host it needs §2's server; where the task workers
reach none it skips after the draft's skip, saying so.

## 5. Tier 2 (FR-029, SC-010)

```sh
make test-contract
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary '{"query":"{ Branch { name } CoreProposedChange { count } FylgjaStage { count } CoreChangeThread { count } CoreThreadComment { count } CoreReadOnlyRepository { edges { node { name { value } } } } CoreCheckDefinition { count } }"}' | jq -c .data
```

Expected: green; §4's test among it, and `internal/server`'s `TestRehearseRefusesBeforeAnyRun`
(a stale mark refuses the rehearsal with the plan's findings and the workflow service is
never dialled); after it, `main` and `fylgja-fixture` alone, zero proposed changes, stages
and comments, the one registration `fylgja`, and the check definitions the registration
holds. About four minutes longer than before (two registrations' imports, two pipelines).

## 6. The checks on `origin`'s `main`, imported (the operator's; R-21)

Once the checks are pushed to `origin`'s `main`:

```sh
ID=$(curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary '{"query":"{ CoreReadOnlyRepository(name__value: \"fylgja\") { edges { node { id } } } }"}' | jq -r '.data.CoreReadOnlyRepository.edges[0].node.id')
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary "{\"query\":\"mutation { InfrahubReadOnlyRepositoryImportLastCommit(data: {id: \\\"$ID\\\"}) { ok } }\"}"
sleep 30
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -H 'Content-Type: application/json' "$INFRAHUB_ADDRESS/graphql" --data-binary '{"query":"{ CoreCheckDefinition { edges { node { name { value } timeout { value } } } } }"}' | jq -c '[.data.CoreCheckDefinition.edges[].node | {name: .name.value, timeout: .timeout.value}]'
```

Expected: `fylgja-step` 300 and `fylgja-twin` 4200. Then the README's proposed-change
walk-through by hand on a fresh `fylgja-test-readme` branch: `-propose` (the draft skipped,
the plan passed), two stages, `-ready`, the checks re-run from the proposed-change view,
the comment with its table and drawing read in the UI, `fylgja-step`'s message read under
`Message`, `twin rehearse` by hand, `-delete`; nothing left in Infrahub or on the host.

## 7. Tier 3 (FR-030, SC-010)

```sh
free -m; set -a; . local/.env; set +a
(make test-e2e > local/e2e-015.log 2>&1; echo $? > local/e2e-015.status) &
```

Wait in foreground calls of under ten minutes. Expected: `E2E-OK` after about 27 minutes,
nine cases and nine twins; case 9's lines: the draft skipped by `fylgja-twin`, the plan's
pass, the rehearsal's success and its comment, then `bad-port` failing at `push` on n1 with
`head` not reached and the second comment naming the commands; after it no twin, no
`fylgja-test-*` branch, proposed change, stage or comment. Then `PLATFORMS=nokia_srlinux
make test-e2e`: `E2E-PARTIAL`, cases 6 and 8 skipped, case 9 run.

## 8. The records and the tree (US5, SC-011, SC-012)

```sh
/usr/bin/grep -rn -i 'loopback' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=local --exclude-dir=bin --exclude-dir=specs README.md SECURITY.md CLAUDE.md docs contracts .env.example
jq -r '.properties.operation.enum[]' contracts/findings.schema.json | /usr/bin/grep -c rehearse
git diff --stat main -- testdata/golden; bin/fylgja intent read --branch fylgja-fixture --out /tmp/f.json && bin/fylgja twin compile --ctm /tmp/f.json --out /tmp/f-bundle --json | jq -r .bundle_id
make diagrams && git status --short docs/c4 docs/diagrams docs/development.md
```

Expected: every sentence that said the server listens on loopback alone now says where it
listens; one `twin.rehearse`; no golden moved and the fixture still `47b2c449…`; the diagrams
regenerated with `rehearsal` in both views and the checks' container, and nothing else moved.

## 9. The close

`CLAUDE.md`'s Formats (`twin.json` `7`), State (015 built, 016 next) and the server's start
line; `docs/development.md`, `docs/verified-facts.md` (research §1), the glossary, the
roadmap (F-007 and F-008 built, F-007's row reworded), `SECURITY.md`, `docs/architecture.md`
§4.4, §4.6, §6 and the C4 model; `contracts/api.md` and `cli.md`'s 015 sections; the four
decision entries accepted or declined by the operator and appended.
