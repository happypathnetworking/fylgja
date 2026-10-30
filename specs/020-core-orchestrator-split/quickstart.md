# quickstart.md

How `020-core-orchestrator-split` is exercised by hand and by the tiers, in the order the
route runs them ([template](../../docs/templates/quickstart-template.md)). Load
`local/.env` first (`set -a; . local/.env; set +a`); never echo a token.

## 0. Before the work: the operator's

- `git log --oneline -3 origin/main` shows `3a5aa37` or later: 016 merged and pushed.
- `grep -c 'id="d-066"' docs/decisions.md` is 1: D-065 and D-066 appended.
- The host: `free -m` reads about 17 GiB available or more; `pgrep -x fylgja -a` shows the
  worker and the server on this build; Infrahub's eight containers healthy; the host's
  4200 free (`ss -ltn | grep 4200` empty).
- Nothing pending in `local/command-log/pending.jsonl`.

## 1. Tier 1

`make build && make test && make lint` inside 90 s wall (raised from 65 s on 2026-10-29).
What must not move: the four goldens (`c70589c3…`, `10099944…`, `44ac283f…`,
`5222063b…`), `testdata/snapshot/*`'s ids, `testdata/ctm/*`. New tests: the five lost paths `404` with "no operation at this path"
and the five lost arguments `400` "takes no argument" (SC-003); `TestWorkerRegistersEveryScheduledActivity`
at three workflows; `twin.json` `12` round-trips and an `11` is shown and refused a step
(SC-004); `run.read` replays each of the seven histories (SC-005); `twin.diff` on the
goldens, three-node to three-node-probed naming the two hosts and their links (SC-006);
`TestClientReachesTheCoreThroughTheAPIAlone` and the new `TestTheCoreLinksNoReader`
(SC-003); `orchestrator/.venv/bin/pytest -q orchestrator -m 'not contract'`: the
normaliser's ids, the verdicts, the three documents' text and markdown against the
captured goldens (SC-007). Proves US2, US4, US5, US7 scenarios 1-2.

## 2. By hand: the core with no Infrahub (US2)

```
env -u INFRAHUB_ADDRESS -u INFRAHUB_API_TOKEN -u FYLGJA_DEFAULT_SCOPE FYLGJA_STATE_ROOT=$PWD/local bin/fylgja serve
```
The report names `listening on 127.0.0.1:7650`, no default scope line, and `the workflow
service (…), Docker, containerlab and the nodes are dialled when a request needs them`.
Then `bin/fylgja twin create --snapshot 0940db93e2ad…` (the fixture's id, filed) builds
the twin from `c3872f5c…`; `twin show` names the snapshot and no stage; `twin create
--branch fylgja-fixture` ends `unknown flag`, exit 2; `curl -s -o /dev/null -w '%{http_code}'
-H "Authorization: Bearer $FYLGJA_API_TOKEN" -X POST 127.0.0.1:7650/v1/stage/list -d '{}'`
is `404`. `twin destroy`.

## 3. By hand: a detached run and its read (US4)

```
bin/fylgja twin create --snapshot <id> --detach        # ends with run fylgja-provision <run id> started
bin/fylgja run read --workflow fylgja-provision        # events so far, no document, exit 0
bin/fylgja run interrupt --workflow fylgja-provision   # run.cancel.requested
bin/fylgja run read --workflow fylgja-provision --json # once ended: the document, cancelled
bin/fylgja run read --workflow fylgja-provision --run 00000000-…   # run.unknown, exit 1
```

## 4. By hand: the adapter reads the fixture (US3 scenario 1, SC-002)

```
orchestrator/.venv/bin/python -m fylgja_orchestrator.adapters.infrahub read --branch fylgja-fixture --out /tmp/s.json
sha256sum < <(jq --indent 2 'del(.snapshot_version, .snapshot_id, .observed_at, .ctm.envelope.observed_at)' /tmp/s.json)   # 0940db93…
bin/fylgja intent read --branch fylgja-fixture --out /tmp/go.json && cmp /tmp/s.json /tmp/go.json   # before the Go reader goes
```
`… stages --branch fylgja-fixture` answers `branch fylgja-fixture: no open proposed change`,
exit 0, its rows empty, as `fylgja stage list` did (014's `contracts/cli.md`; `stage.unknown`,
exit 1, is a stage reference's or `stage plan`'s); `… schema-check --branch fylgja-fixture`
exits 0.

## 5. By hand: `fylgja-cli` creates, steps, lists and plans (US3, US6)

With `PREFECT_API_URL` and `PREFECT_API_AUTH_STRING` from `local/.env`, a throwaway
proposed change from `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-h1
-propose`, then `-stage seeded`, `-add-link`, `-stage third-link`:

```
fylgja-cli stage plan --branch fylgja-test-h1 --json      # 4 stages, 3 steps, each from twin.diff
fylgja-cli twin create --stage fylgja-test-h1/seeded     # progress lines, bundle id; local/orchestrator/twin.json written
fylgja-cli stage list --branch fylgja-test-h1            # the twin's row at seeded
fylgja-cli twin step                                     # to third-link; the record moves
bin/fylgja twin step --snapshot 0940db93…                # the core alone
fylgja-cli stage list --branch fylgja-test-h1            # record.twin.stale, no twin row
fylgja-cli twin step                                     # step.target.required, exit 1
fylgja-cli twin create --branch fylgja-fixture --dry-run # refused, host held; after destroy: the plan's lines
```
`http://<bridge>:4200/api/flow_runs/filter` lists each run; `grep -c Bearer
local/orchestrator.log` is 0. Then `fylgja-fixture -branch fylgja-test-h1 -delete`.

## 6. By hand: the rehearsal, from the CLI and from inside Infrahub (US1)

`fylgja-cli twin rehearse --branch fylgja-test-h1 --markdown` on the same proposed change
marked ready prints the report and posts one thread; `grep -c '/v1/' local/server.log`
grows by the creates, steps, verifies and destroys alone; the thread's reproduce lines
name `fylgja-cli`. From a task worker, after the override's `up -d` (the live session's):
`docker exec fylgja-infrahub-task-worker-1 python -c 'import httpx,os; print(httpx.get("http://"+os.environ["FYLGJA_ORCHESTRATOR_ADDRESS"]+"/api/deployments/name/twin-rehearse/main", auth=tuple(os.environ["FYLGJA_ORCHESTRATOR_AUTH"].split(":",1))).status_code)'`
is `200`, and `…7650/v1/twin/show` from there fails to connect. Then
`-run-checks user` rehearses it twice as tier 3's case 9 does.

## 7. Tier 2

`make test-contract` (Go's packages, `internal/checks` alone, then `pytest -m contract`),
2,692.6 s, about 45 minutes, measured at implement (T042: the Go half about 370 s,
`pytest -m contract` 2,322.3 s; research §5.29); needs `INFRAHUB_*`, the Prefect server
and the runner up, the core's server on loopback with no `INFRAHUB_*`. Named: the ported
`test_read_*`, `test_stages_*`, `test_stage_*` (each a Go test's assertions),
`test_adapter_matches_go_reader` (until the removal), `test_flows_create_from_fixture`,
`test_stage_plan_of_a_throwaway_change`, `test_rehearse_refused_on_a_stale_mark`,
`test_rehearse_composed_by_the_fixture_tool`, and `TestChecksInsideInfrahub` through the
bridge. Infrahub is left as today: `CoreProposedChange`, `FylgjaStage`, `FylgjaProbe`,
`CoreChangeThread`, `CoreUserValidator` at 0, `Branch` listing `main` and `fylgja-fixture`.
Proves SC-002, SC-008's first half, US1 scenarios 5 and 8, US3, US5 scenario 4, US6.

## 8. Tier 3

`make test-e2e` with the worker, the Prefect server and the runner running, the core's
server on loopback from this tree, the platform on the bridge, both checks imported on
`main`, no twin up: nine cases, cases 1 to
8 through `fylgja-cli` for every branch or stage, case 9 through `fylgja-twin`, the
orchestrator and the core; ends `E2E-OK`, measured at implement in 2,798.6 s, about 47
minutes, by T043's evidence run, a copy of the script whose case-9 precheck compared the
checks' syntax trees, since `make test-e2e` itself was refused at that precheck on this
tree (the imported `infrahub/checks/fylgja_api.py` differing by one comment; research
§5.29); `free -m` before, the host rested after. Proves SC-001, SC-008, US1 scenarios
1-4, 6-7.

## 9. The records at the close

`docs/verified-facts.md` (§1's facts under "Prefect 3.8.8" and Infrahub's), `CLAUDE.md`'s
Environment and State (five processes, the override's variables, the tiers' times),
`docs/roadmap.md` (R-24), the constitution 3.0.0; the greps: `/usr/bin/grep -rn
'fylgja-rehearse\|bridge.*7650\|internal/intent' docs README.md contracts SECURITY.md
CLAUDE.md` finds only the decision log's superseded entries, the archive and the release
notes (SC-011); `make linkcheck` clean; the credential greps over `local/orchestrator.log`,
`local/prefect.log` and `local/orchestrator/prefect/`; the figures: tiers 1, 2 and 3,
the flow's overhead, the effort against R-22's 24-36 hours.
