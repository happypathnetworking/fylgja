# Quickstart: Probes

**Feature**: `016-probes` · **Plan**: [plan.md](plan.md)

How to prove the feature works, in the order it is built. The shapes are in
[contracts/](contracts/) and [data-model.md](data-model.md), the reasons in
[research.md](research.md). Run from the repository root, in a shell with `local/.env`
loaded (`set -a; . local/.env; set +a`). The live sections (§2–§5, §7) are the live
session's or the operator's, never a headless run's.

## 0. Before the work: the operator's

- The brief's push of `main` to `origin` is done (`origin/main` at `7a1a180`, 2026-10-28).
- At `analyze`: this directory reviewed; D-064 (research §3.1) and the amendment (§3.2)
  accepted or amended; research R-30's settlements, the same-device demo probe and the two
  ports per device first, confirmed or overturned.
- **Before tier 2**: `FylgjaProbe` loaded on `main`, Infrahub up, no twin:
  `.venv/bin/infrahubctl schema check --branch main schema/fylgja-probe.yaml`, then
  `schema load`; `main`'s hash recorded.
- **Before tier 2's artifact proof, the fixture's re-seed and tier 3**: the template's
  change merged into `main`, pushed, imported
  (`InfrahubReadOnlyRepositoryImportLastCommit`) and both task workers' `commits/` read.
- The live session pulls the image (`docker pull alpine:3.24.2`) and re-seeds the fixture
  (`make infrahub-clean && make infrahub-seed`).

## 1. Tier 1

```sh
make test     # under 45 s uncached: go clean -testcache first to time it
make lint
```

True afterwards (SC-003, SC-004, SC-008, SC-009, US1, US5, US6, US7):

- `go test ./internal/compiler`: the four goldens pass with no `-update`; the three-node
  snapshot wrapped with `testdata/probes/n1-loop.json` compiles to `three-node-probed`,
  whose manifest names `n1-loop-a`, `n1-loop-b`, their link and both rows under
  `synthesized`, `probes[]` one entry and `fidelity.synthesized` two names; the same
  snapshot with no probes compiles to `three-node`, differing from the `5` golden in the
  version, `probes: []` and `fidelity.synthesized: []` alone; `TestCompilerNamesNoPlatform`
  and `TestCompilerIsPure` pass.
- One tier-1 case per refusal of data-model §12, each naming the probe, the endpoint and
  the cause: the device unknown, the interface unknown, cabled, `mgmt_only`, taken; the
  format unknown; a name repeated; an address without a prefix length; a gateway outside
  the prefix; two hosts with one address; a stage plan whose second stage cables a probe's
  port marks that stage refused.
- `internal/probe`: the shipped package validates; a package missing each required field
  is refused naming it; `ParsePing` reads busybox and iputils output; the conformance pure
  half's `probes` check passes.
- `internal/snapshot`: two declarations differing in one probe take two ids; a `1` on
  disk reads as a `2` with no probes and the same id; a `2` with a non-contract element
  is `snapshot.invalid` at the element's field.
- `internal/provision`: 4 workflows and 17 activities registered; the seven replays pass
  without the `flows` marker; a step records `loss` per probe, labelled `container`, with
  `not_started` and `interrupted` outcomes in their cases; the dry run carries none.
- `internal/verify`: `Derive` on `three-node-probed`'s manifest yields one `burst` per
  probe after the three kinds, a synthesized link's `neighbor` skipped at both ends; a
  burst read `4 of 5` is `verify.burst`, exit 5; the counts carry `burst`.
- `internal/rehearsal`: the table with `loss` for a stepped, a created and a refused
  stage; the footer's caveat; the deadline with the flows' budgets.
- `internal/lab`: the host check refuses an absent `alpine:3.24.2` naming the pull; a host
  node's plan from the probe registry; `twin.json` `11` with a host and `step.loss`.
- Every frozen copy loads (`TestFrozenContractCopiesAgree`, seven new); `--probes` on
  `twin compile` and `twin provision` is an unknown flag, exit 2; beside `--snapshot` on
  create and step it is `snapshot.flags.conflict` before any connection.

```sh
/usr/bin/grep -rn 'linux\|alpine\|"ping"' --include='*.go' internal/compiler | grep -v _test
```

matches nothing: the kind, the image and the format come from the package.

## 2. The host, after the rebuild

```sh
make build
pgrep -x fylgja | xargs -r kill        # then start both as CLAUDE.md prescribes
docker pull alpine:3.24.2 && docker image inspect --format '{{.Id}} {{.RepoDigests}}' alpine:3.24.2
```

True afterwards: each `/proc/<pid>/exe` not `(deleted)`; both start-up reports name the
two platform packages and the `ping` probe package; the image's digest recorded in
research §5.

## 3. By hand: a probe on a throwaway branch (US1, US5)

On a throwaway branch, never `fylgja-fixture`, with no tier 2 running and `free -m` read
first. The template imported (§0) so the ports come up addressed.

```sh
B=fylgja-test-qs-$$
go run -tags fixture ./cmd/fylgja-fixture -branch "$B"            # n1–n3 with ethernet-1/10 and -1/11 addressed
cat testdata/probes/n1-loop.json                                   # n1:ethernet-1/10 ↔ n1:ethernet-1/11
bin/fylgja twin create --branch "$B" --probes testdata/probes/n1-loop.json --dry-run   # the hosts in the plan, memory: with 2×32 MiB
bin/fylgja twin create --branch "$B" --probes testdata/probes/n1-loop.json
jq '.snapshot_version, (.probes|length)' local/snapshots/$(jq -r .snapshot_id local/twin/twin.json).json   # "2", 1
jq '.bundle_version, [.nodes[]|select(.provenance=="synthesized")|.name], .probes[0].name, .fidelity.synthesized' local/twin/bundle/manifest.json
docker exec clab-fylgja-n1-loop-a ip -4 -o addr show dev eth1; docker exec clab-fylgja-n1-loop-a ip route
docker exec clab-fylgja-n1-loop-a ping -c 3 10.1.11.2             # answered through n1
bin/fylgja twin verify                                             # burst n1-loop held; counts burst 1/0
bin/fylgja twin show                                               # the hosts among the nodes, probe named
sed 's/ethernet-1\/11/ethernet-1\/1/' testdata/probes/n1-loop.json > local/qs-cabled.json
bin/fylgja intent read --branch "$B" --probes local/qs-cabled.json --out local/qs.json   # filed: placement is the compile's (FR-009)
bin/fylgja twin compile --snapshot local/qs.json --out local/qs-bundle   # refused: probe.interface.cabled n1-loop/b, exit 1, no bundle
bin/fylgja twin create --snapshot local/qs.json --probes testdata/probes/n1-loop.json    # snapshot.flags.conflict --probes
```

True afterwards: `twin.json` is `11`, `source` `intent`, five nodes, the hosts' `psp`
null and `probe` named.

## 4. By hand: loss across a step (US2, US3)

```sh
go run -tags fixture ./cmd/fylgja-fixture -branch "$B" -disable-port n1:ethernet-1/2 -generate
# -generate returns once the count holds, before a rewrite lands: wait for n1's checksum to move
bin/fylgja intent read --branch "$B" --probes testdata/probes/n1-loop.json --out local/qs-1.json
bin/fylgja twin step --snapshot local/qs-1.json --wait 60s   # step flows: n1-loop started; … step observe: settled …; loss n1-loop 0/N, gap 0.0s (container timing)
jq '.step.loss' local/twin/twin.json                        # basis container, one probe, sent > 0
go run -tags fixture ./cmd/fylgja-fixture -branch "$B" -disable-port n1:ethernet-1/10 -generate   # and wait, as above
bin/fylgja intent read --branch "$B" --probes testdata/probes/n1-loop.json --out local/qs-2.json
bin/fylgja twin step --snapshot local/qs-2.json --wait 30s   # stepped; wait expired: verify.burst n1-loop 0 of 5 replies
bin/fylgja twin verify; echo $?                             # 5, nonconforming on the burst alone
bin/fylgja twin step --snapshot local/qs-1.json --wait 60s   # back: the port re-enabled, the burst held, lost > 0 across the step
bin/fylgja twin destroy                                     # the hosts removed with the lab
go run -tags fixture ./cmd/fylgja-fixture -branch "$B" -delete
rm -f local/qs-*.json
```

True afterwards: the step's outcome was `stepped` whatever the loss (FR-016); the burst's
failure alone made the verify `nonconforming` (FR-020).

## 5. By hand: the kind (US4)

```sh
go run -tags fixture ./cmd/fylgja-fixture -probes testdata/probes/n1-loop.json   # written to FylgjaProbe on main
.venv/bin/infrahubctl object get FylgjaProbe                                     # n1-loop, its eight fields
bin/fylgja intent read --branch fylgja-fixture --out local/qs-k.json             # no flag: probes from the kind
jq '.probes[0].name' local/qs-k.json                                             # n1-loop
bin/fylgja intent read --branch fylgja-fixture --probes testdata/probes/n2-loop.json --out local/qs-f.json; jq '.probes[].name' local/qs-f.json   # n2-loop alone
go run -tags fixture ./cmd/fylgja-fixture -delete-probes
bin/fylgja intent read --branch fylgja-fixture --out local/qs-n.json; jq '.probes' local/qs-n.json    # [], no warning
rm -f local/qs-*.json
```

## 6. Tier 2

```sh
make test-contract
```

No twin while it runs; the kind on `main` first (§0). True afterwards (SC-005, SC-006,
SC-007): `TestProbesFromTheKind` writes a probe on `main`, takes a `fylgja-test-*` branch
with no flag and reads it in the list, with a file and reads the file's alone, deletes it
and reads `[]`, and `FylgjaProbe` counts 0 after; `TestIntentReadFilesASnapshot2` and
`twin create --snapshot` of it compiles; once the template is imported, the fixture's three
artifacts carry each addressed port's lines and the ids `CLAUDE.md` records; `internal/checks`
passes with the server on the bridge. About 34 minutes. Infrahub left as the tier leaves
it: `FylgjaProbe` 0, `main` holding the kind beside `FylgjaStage`.

## 7. Tier 3

```sh
free -m
nohup make test-e2e > local/e2e-016.log 2>&1; echo $? > local/e2e-016.status &   # detached, as CLAUDE.md says
```

True afterwards (SC-001, SC-002, SC-010): `E2E-OK`, nine cases; case 5's create with
`--probes`, its verify's burst held, its steps' `loss` per probe in the document and the
record; case 8's probe from the kind on `e1`, `lost > 0` across `e1`'s restart and the
burst held after the wait, the probe deleted; case 9's third stage `probe-port-down`
failed on `verify.burst`, the two earlier passed with their loss figures, the thread's
table carrying `loss`; no `clab-fylgja-*-a` container left after any destroy. About 34
minutes whole. The flows' and bursts' output never reaches `$OUT` but as figures.

## 8. The records at the close

- `/usr/bin/grep -rn 'ping and iperf3' docs README.md CLAUDE.md` matches the archive and
  the decision log alone; `/usr/bin/grep -n 'Everything is .intent. today' docs/architecture.md`
  matches nothing.
- `make diagrams` after the C4 edit; `make linkcheck` clean.
- `docs/verified-facts.md` per research §4 (the host, the template's lines, the kind's
  load, the namespace); `CLAUDE.md`'s Formats (`probes 1`, probe package `0.1`, snapshot
  `2`, bundle `6`, `twin.json` `11`, the four goldens' ids, the fixture's snapshot and
  compiled ids), the worker's counts (4/17), State; the roadmap's F-014 marked built with
  the measured hours against R-29's 14–20.
