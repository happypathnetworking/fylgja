# The three documents' goldens

Captured on 2026-10-29 by 020's T003 (research R-14, FR-023, SC-007) from the Go
implementation as the lab host ran it: the worker and the server built from `96d38d8`
(no Go, `go.mod`, `contracts/`, `probes/` or `psp/` change from 016's merge, `195af3a`),
before any of 020's Go changes. They are the oracle the orchestrator's renderers are held
to: a renderer that differs is fixed, never the golden, unless the operator says the Go
output was wrong.

## What was captured

One throwaway proposed change with three marked stages, the third on a change SR Linux
refuses at the push, as 015's `bad-port` was, so the rehearsal covers each verdict:
refused, baseline, passed, failed and not reached. It also carries the reproduce lines,
a red-outlined stage in the drawing and the markdown's shortened form.

| | |
|---|---|
| branch | `fylgja-test-golden-41263`, seeded with the three-node fixture, deleted after |
| proposed change | `18e3127c-025b-f488-33be-c5158cf576c3`, named as its branch, into `main` |
| scope | `tag:fylgja`, the server's default |
| probes | none: `main` held no `FylgjaProbe`, and no `--probes` was sent, so every loss cell reads `—` |
| rehearsal run | `fylgja-rehearse` `01a188df-b883-70f8-8999-bc18b484dc1f`: provision `01a188df-b908-761c-95d8-868a578bec10`, steps `01a188e0-7642-75da-b355-c789b0bffe8e` (third-link) and `01a188e0-a0b7-78e2-9cb0-2c7bf655c46f` (bad-port), destroy `01a188e0-d0c3-7ce5-a3ce-8cae374baa9e`; stages resolved at `2026-10-29T18:15:11Z`, 74.5 s of the 2,580 s deadline (ceiling 3,600 s) |

The stages, their `at` and their ids (the plan's and the rehearsal's agree):

| stage | `at` (source) | stage id | snapshot id | bundle id |
|---|---|---|---|---|
| `…/branch-point` | `2026-10-29T18:09:04.039194Z` (branch point, on `main`) | — | — (refused, `scope.empty`) | — |
| `…/seeded` | `2026-10-29T18:11:38.471611+00:00` (written) | `18e31292-9dc4-e4dd-33b5-c51a473f07e6` | `78232019fdb8bb0413b7a122a443c1e70f8719b5e2e7658a5c2e1e27fd877478` | `ce705cdb14ccd7d56109a1708e5a1d00f703018df96c1440baeddc4d8c1b13b8` |
| `…/third-link` | `2026-10-29T18:11:50.425111+00:00` (written) | `18e31295-9ca5-f8fd-33b6-c5161e55b543` | `5cbbe59387fa465c80cd3bd83687c8cb978333c0c8f0baba8ee50a35255b2559` | `61665b99bb406d2b6c3aefc1f6624ca4bd6c57ea44f13e65c904733ed5a159e9` |
| `…/bad-port` | `2026-10-29T18:12:11.745240+00:00` (written) | `18e3129a-93a6-6c68-33be-c5136cc0a698` | `cc81016f65b5d964622510eae026276e1eaf91e2f09a22ac911014b76050ef26` | `0b8af687b3e91282898e33c3e14eed1139cecf0957496677b2ac9d8cd1d730bc` |
| `…/head` | `2026-10-29T18:12:10.636975+00:00` (head) | — | `8b986a1036a37a2ba19c5a8f6a7884d56d18d77c95717d24482791227df1ef0f` | `4215a6c2e3e7e1e64b6331e2d6406f1cf45d905db7e8c449ea076e8ea51fd9b5` |

The head's `at` is earlier than `bad-port`'s: the head is the branch's last write, the
artifact n1's regeneration, and `bad-port` was marked after it.

## How, in order

`fixture` is `go run -tags fixture ./cmd/fylgja-fixture`, and `$B` is the branch.

```sh
fixture -branch $B                                   # the three-node fixture, its artifacts Ready
fixture -branch $B -propose                          # the draft; both checks ran at its creation and passed
fixture -branch $B -stage seeded -description seeded
fixture -branch $B -add-link                         # n1:ethernet-1/3 <-> n3:ethernet-1/3; n1's and n3's checksums awaited
fixture -branch $B -stage third-link -description "third link"
fixture -branch $B -add-interface n1:ethernet-1/99 -generate   # n1's checksum awaited
fixture -branch $B -stage bad-port -description "a port SR Linux refuses"
fylgja stage list --branch $B --json > stages.json   # and without --json > stages.txt
fylgja stage plan --branch $B --json > plan.json     # and without --json > plan.txt 2> plan.stderr.txt
fylgja twin create --stage $B/seeded
fylgja stage list --branch $B --json > stages-with-twin.json   # and without --json > stages-with-twin.txt
fylgja twin destroy
fixture -branch $B -ready                            # starts no check
curl -sS -N -X POST -H "Authorization: Bearer $FYLGJA_API_TOKEN" \
     -d '{"render":"markdown","args":{"branch":"'$B'"}}' http://127.0.0.1:7650/v1/twin/rehearse
fixture -branch $B -delete                           # 3 stages, the proposed change and its thread, the branch
```

The rehearsal was asked once, through the API under `render: "markdown"`, whose last frame
carries the document, its findings as text and the markdown together (`contracts/api.md`).
A check's re-run would have been a second rehearsal, and its answer is not kept. Its
markdown was then posted as `fylgja-twin` posts it, by `post_comment` in
`infrahub/checks/fylgja_api.py` (thread `18e312e7-3fe2-e98e-33b1-c51fcee11cab`, comment
`18e312e7-475d-4fce-33b7-c511564dd452`). The `CoreThreadComment`'s text read back by
GraphQL equals the frame's markdown byte for byte (3,486 bytes).

## The files

| file | what it is |
|---|---|
| `stages.json`, `stages-with-twin.json`, `plan.json` | `--json`'s stdout, exit 0, 0 and 1 (the branch point refused); nothing on stderr |
| `stages.txt`, `stages-with-twin.txt`, `plan.txt` | stdout without `--json`; `stage list` wrote nothing on stderr |
| `plan.stderr.txt` | `stage plan`'s stderr without `--json`: its findings as `WriteText` renders them |
| `rehearsal.json` | the document as `twin rehearse --json` prints it: the frame's document re-indented (`internal/cli/root.go`), which equals `WriteJSON` of it decoded |
| `rehearsal.txt` | the report's text, the last lines `twin rehearse` prints on stdout: `rehearsal.StageLines` then `rehearsal.Closing` with its reproduce lines |
| `rehearsal.stderr.txt` | its findings as `WriteText` renders them, printed on stderr; equal to the frame's `text` |
| `rehearsal.out.txt` | every `out` frame, stdout whole: the plan's lines, the children's progress, the destroy's lines, then `rehearsal.txt`; its run ids and timings are this run's |
| `rehearsal.md` | the frame's markdown, the comment posted: `Markdown`'s shortened form, the whole being over the 4,092 bytes Infrahub keeps |
| `rehearsal.full.md` | `Markdown`'s whole form for the same document, 4,271 bytes, which it returns when that fits |

`rehearsal.txt`, `rehearsal.stderr.txt` and both markdowns were rendered from
`rehearsal.json` by a throwaway Go test over `internal/rehearsal` and `internal/findings`,
deleted after. The markdowns took `plan.json`'s `steps` as the plan's steps. Each
rendering equals what the live answer sent, `rehearsal.full.md` aside, since the live
answer carries one form.

**One edit to the captured bytes**: the state root, a path under the capturing user's
home, reads `<state-root>` in `rehearsal.json` (the destroy's `removed`) and
`rehearsal.out.txt` (`removed twin directory <state-root>/twin`). No renderer writes it:
it is the destroy's report carried through.

**What the orchestrator may change** (FR-023, SC-007): `fylgja` reads `fylgja-cli` in the
reproduce lines, which are `rehearsal.json`'s `rehearsal.reproduce`, the indented lines of
`rehearsal.txt`'s closing line and the fenced block under **Reproduce by hand** in both
markdowns. Nothing else may change. A renderer fed these documents must give these bytes.
A live run's ids, times and timings are its own, and its test substitutes them.
