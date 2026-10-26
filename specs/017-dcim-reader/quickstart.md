# Quickstart: validating the Infrahub reader of the schema library's DCIM

**Feature**: `017-dcim-reader` · **Plan**: [plan.md](plan.md) · **Contracts**:
[contracts/](contracts/) · **Research**: [research.md](research.md)

What proves the feature, scenario by scenario, in the order the work lands (plan, "Order
of the work"). Each names its prerequisites, the commands and what must come out. Nothing
below prints a credential; `local/.env` is the one file that holds a value. Every write to
Infrahub is on a `fylgja-test-*` branch deleted by what made it, but for the migration of
`main` (§2), which is this feature's one lasting write, made once.

## 0. Before the work starts (the operator's; research §1.1)

The demo window ([D-054](../../docs/decisions.md#d-054)) is open on this host: `main`
holds the baseline and `fylgja-test-demo` an open proposed change. Close it **with the
tree as it is before this feature changes the fixture tool**, since `-clear-main` reads
the generics' kinds:

```sh
set -a; . local/.env; set +a
go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-demo -delete
go run -tags fixture ./cmd/fylgja-fixture -clear-main
```

Expected: `deleted 3 stages, 1 proposed change, branch fylgja-test-demo`; `baseline
removed from main: 3 links, 12 interfaces, 3 devices, 1 platform, 1 contract; artifacts:
… gone with their devices, … deleted`. Then `main` reads `FylgjaDevice 0`, `FylgjaLink 0`,
`FylgjaContract 0`, and `Branch` lists `main` and `fylgja-fixture` alone. Also the
operator's, at `analyze`: D-057 and Constitution 2.0.0 (research §3) accepted before the
reader is built.

## 1. Tier 1 (SC-008)

```sh
make build && make test && make lint
```

Expected: green, under 45 s wall uncached. Among the tests that must exist and pass:
`internal/ctm`'s `TestFixturesSatisfyTheSchema` over the moved `testdata/ctm/*.json` against
[contracts/ctm.schema.json](contracts/ctm.schema.json), `TestVersion1IsRefused`; `internal/compiler`'s three
goldens, `TestEveryInterfaceIsAPort`, the survey without a loopback arm, `TestManifestCopiesTheFidelityList`
(the compiler holds no row's text: a CTM with an invented row reaches the manifest
unchanged), `TestCompilerNamesNoPlatform`; `internal/psp`'s `matches` rules and
`TestShippedPackagesAreValidAndEmbedded` at `0.7`; `internal/conformance`'s `matches`
check and `TestShippedPackagesShareNoMatch`, the two defect fixtures failing by name;
`internal/intent`'s conformance findings against an `httptest` schema document (a kind
removed, a field removed, a field of another kind, cardinality and peer, a choice removed,
an implementer removed; each naming `26336e9`), the read against an `httptest` Infrahub
answering research §1.6's shapes (three devices read to `testdata/ctm/three-node.json`
but the envelope; a three-ended cable, a one-ended one, an outside end and an end of
another `__typename` each omitted with its rule, its reason and its row; a device with no
platform, one with an orphan platform and one on `nokia` / `SR-Linux` refused in one pass
with no CTM; `tag:nothing` refused `scope.empty`), the stamps' fold over faked
`node_metadata` answers, the events' rule (a `member_of_groups` update ignored, a cable's
`connected_endpoints` update naming its former port, a `schema.updated` event with no
primary node skipped), `TestEveryOperationIsAQuery`, `TestQueryRootsAreTheMappings`,
`TestFragmentTargetsAreTheMappings`; `internal/stages`'s staleness with a device's cable,
platform and manufacturer stamps; `internal/lab`'s `TestRecord8` and the `7` record read
with no scope, `TestFrozenContractCopiesAgree`; `internal/bundle`'s `5` accepted and `4`
refused naming both; `internal/server`'s `scopeOf` (the default, the argument, `scope.invalid`,
`scope.unset`, each before any connection) and `passedOver` on `scope.empty`;
`internal/cli`'s `--scope` on the five commands through the harness, `twin step --scope`
refused by cobra, `twin show`'s record line, `schema check`'s success line and `verified`
block; `cmd/fylgja`'s `serve` report line for a set and an unset default and the refusal
of a malformed one; the root's `TestVendoredLibraryIsThePinnedCommit` (each file's SHA-256
to `schema/dcim/README.md`'s table); the nine recorded histories replaying.

## 2. The migration of `main` and the fixtures (research R-14; the operator's gate inside it)

Prerequisites: §0 done; the tree holds the new fixture tool, `schema/dcim/`, the template,
the query and `.infrahub.yml`; `local/.env` loaded; nothing else running against Infrahub.

```sh
# 1. the generics leave main: two documents, about 50 s each
.venv/bin/infrahubctl schema check --branch main specs/017-dcim-reader/migration/1-reference-kinds-absent.yaml
.venv/bin/infrahubctl schema load  --branch main specs/017-dcim-reader/migration/1-reference-kinds-absent.yaml
.venv/bin/infrahubctl schema check --branch main specs/017-dcim-reader/migration/2-generics-absent.yaml
.venv/bin/infrahubctl schema load  --branch main specs/017-dcim-reader/migration/2-generics-absent.yaml
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" "$INFRAHUB_ADDRESS/api/schema?branch=main" | jq -c '{hash: .main, fylgja: [.nodes[].kind, .generics[].kind | select(startswith("Fylgja") or startswith("Network"))]}'
# 2. the library on main, beside the stage kind
go run -tags fixture ./cmd/fylgja-fixture -prepare-main
go run -tags fixture ./cmd/fylgja-fixture -prepare-main   # refuses, naming the kinds found; exit 1
```

Expected after step 1: `removed:` naming the five, then the four; `fylgja:
["FylgjaStage"]` and a new hash. After step 2: `schema library loaded on main (6 files,
opsmill/schema-library@26336e9)`, `stage kind present`, `group fylgja-devices present`,
`repository fylgja present`; the second run `main holds 27 of the schema library's kinds
(DcimCable, DcimConnector, DcimDevice, …): -prepare-main is the development host's and CI's tool,
which loads the library on an empty main alone; it is not an install path: …`, exit 1,
nothing written. Record the hash.

```sh
# 3. the operator's gate: the template commit on origin's main, imported
#    (the operator pushes; the session imports, as 015's quickstart §6 did)
ID=$(curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -X POST "$INFRAHUB_ADDRESS/graphql" -H 'Content-Type: application/json' \
  -d '{"query":"{ CoreReadOnlyRepository(name__value: \"fylgja\") { edges { node { id } } } }"}' | jq -r '.CoreReadOnlyRepository.edges[0].node.id // .data.CoreReadOnlyRepository.edges[0].node.id')
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -X POST "$INFRAHUB_ADDRESS/graphql" -H 'Content-Type: application/json' \
  -d "{\"query\":\"mutation { InfrahubReadOnlyRepositoryImportLastCommit(data: {id: \\\"$ID\\\"}) { ok } }\"}"
sleep 20
curl -s -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" -X POST "$INFRAHUB_ADDRESS/graphql" -H 'Content-Type: application/json' \
  -d '{"query":"{ CoreReadOnlyRepository { edges { node { name { value } commit { value } } } } CoreGraphQLQuery(name__value: \"device_config\") { edges { node { query { value } } } } }"}' | jq -r '.data.CoreReadOnlyRepository.edges[0].node.commit.value, (.data.CoreGraphQLQuery.edges[0].node.query.value | test("DcimDevice"))'
# 4. the fixture, re-seeded in the library's kinds
make infrahub-clean && make infrahub-seed
# 5. the SDL and the client from the migrated main
make sdl && make generate && git status --short schema/infrahub.graphql internal/intent/generated.go
```

Expected: the registration's commit is the pushed one and the query names `DcimDevice`;
the seed prints `three-node fixture seeded on fylgja-fixture, with every artifact rendered
and Ready`; the SDL and the client change and are committed. Until step 3 no artifact
renders on this host, so steps 4 and 5 wait for it; tier 1 does not.

## 3. The fixture read by hand (SC-001, US1, US3)

Prerequisites: §2; the worker and the server restarted from this tree (`CLAUDE.md`'s two
start lines, `local/.env` carrying `FYLGJA_DEFAULT_SCOPE=tag:fylgja`), the server's
report naming `default scope: tag:fylgja`.

```sh
bin/fylgja schema check --branch fylgja-fixture
bin/fylgja intent read --branch fylgja-fixture --out local/fixture.ctm.json
jq 'del(.envelope)' local/fixture.ctm.json > local/a.json; jq 'del(.envelope)' testdata/ctm/three-node.json > local/b.json; diff local/a.json local/b.json && echo same
jq -c '.envelope | {scope, mapping, fidelity: [.fidelity[] | [.disposition, .object]]}' local/fixture.ctm.json
bin/fylgja twin compile --ctm local/fixture.ctm.json --out local/fixture.bundle && jq -c '.provenance, .fidelity.read' local/fixture.bundle/manifest.json
```

Expected: `conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform,
OrganizationManufacturer, InterfacePhysical, DcimCable, DcimConnector` (the generic since
T091) and the stages line; `wrote
local/fixture.ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0
lossy mappings, 0 shared ports (branch fylgja-fixture, scope tag:fylgja, schema …)`;
`same`; the envelope's scope `tag:fylgja`, mapping `{infrahub-dcim, opsmill/schema-library,
26336e9}` and three rows; the manifest's provenance and `fidelity.read` the same. Record
the bundle id as the fixture's compiled id.

## 4. The scope by hand (US1 scenarios 2 and 7; FR-017, FR-018)

```sh
bin/fylgja intent read --branch fylgja-fixture --scope tag:fylgja --out local/scope.ctm.json  # the same read
                                                    # (not /dev/null: the client writes through a temporary file beside it)
bin/fylgja intent read --branch fylgja-fixture --scope tag:nothing --out /dev/null    # scope.empty, exit 1
bin/fylgja intent read --branch fylgja-fixture --scope fylgja --out /dev/null         # scope.invalid, exit 2
bin/fylgja intent read --branch fylgja-fixture --scope= --out /dev/null               # scope.invalid, exit 2
bin/fylgja twin step --scope tag:fylgja                                               # unknown flag: --scope, exit 2
```

Then a scratch server with no default, on a scratch port and state root, from a shell
where `FYLGJA_DEFAULT_SCOPE` is unset: its report says `default scope: unset (a request
that names no scope is refused)`, and `FYLGJA_API_ADDRESS=127.0.0.1:<port> bin/fylgja
intent read --branch fylgja-fixture --out /dev/null` is `scope.unset` naming
`FYLGJA_DEFAULT_SCOPE`, exit 2, before Infrahub is dialled (the server's log shows no
read). Stop it.

## 5. Omissions and refusals on a throwaway branch (US2; SC-003, SC-005)

```sh
B=fylgja-test-017-hand
go run -tags fixture ./cmd/fylgja-fixture -branch $B                 # seeds in the library's kinds
# by infrahubctl or GraphQL on $B: an untagged device cs1 with a port; a cable n1:ethernet-1/3 <-> cs1:port1;
# a cable with three ends on n2:ethernet-1/3, n3:ethernet-1/3 and a new n1:ethernet-1/4 (ports added first)
bin/fylgja intent read --branch $B --out local/hand.ctm.json
```

Expected: exit 0; two `info` findings, `omit.cable.outside_scope` naming the cable and
`cs1:port1`, `omit.cable.ends` naming three ends; the CTM holds three devices and three
links, no `cs1`; `.envelope.fidelity` has five rows. Then set `n1`'s platform to one named
`SR-Linux` (manufacturer `nokia`) and remove `n2`'s platform:

```sh
bin/fylgja intent read --branch $B --out local/hand.ctm.json; echo exit $?
```

Expected: exit 1, `platform.unmatched n1` naming `nokia` / `SR-Linux` beside
`nokia_srlinux [Nokia / SR Linux], arista_eos [Arista / EOS]`, and `platform.missing n2`,
both in one pass; no file written. `go run -tags fixture ./cmd/fylgja-fixture -branch $B
-delete` at the end.

## 6. Stages over the new model (US5; SC-009)

On a throwaway branch with a draft proposed change and a mark (`-propose`, `-stage
seeded` after the seed's artifacts), each edit below made after the mark and followed by
`bin/fylgja stage plan --branch $B`: an `InterfaceVirtual` added to `n1`; `n1`'s
platform's `description`; the manufacturer's `description`; the cable on
`n1:ethernet-1/1` re-ended. Expected: `stage.artifact.stale n1` after each (and `n2` for
the cable). Then an edit of `cs1` (untagged): no stale mark. Then `main` holding no tagged
device: the plan's branch point `refused (scope.empty)` and the plan going on, `fylgja-step`
and a rehearsal passing over it (§7's checks test asserts the same).

## 7. Tier 2 (SC-001, SC-004, SC-006, SC-009)

```sh
set -a; . local/.env; set +a; make test-contract 2>&1 | tee local/017-contract.out
```

Expected: green (`internal/intent`, `internal/stage`, `internal/stages`, `internal/server`,
`internal/cli`, then `internal/checks`), no twin booted meanwhile. Among the tests:
`TestFixtureReadsToTheThreeNodeCTM`, `TestMixedSeedReads`, `TestSchemaCheckPassesOnBothFixtures`,
`TestSchemaCheckNamesAMissingKind` (`DcimCable` removed on a throwaway branch),
`TestCablesTheReadCannotPlace`, `TestPlatformsTheReadRefuses`, `TestScopeSelectsNothing`,
`TestStagesSeeEveryWriteOfADevice`, and every 014 and 015 test with its assertions
unchanged. After it: `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and
`CoreUserValidator` count 0, `Branch` lists `main` and `fylgja-fixture` alone, `main`
holds no tagged device.

## 8. Tier 3 (SC-006)

Prerequisites: a quiet host (`free -m`), both images, the worker and the server from this
tree, the checks and the template imported (§2 step 3).

```sh
make test-e2e 2>&1 | tee local/017-e2e.out; tail -3 local/017-e2e.out
```

Expected: `E2E-OK`, nine cases, the marker found in no output, record, document, history
or log; case 1's `twin show` names `scope tag:fylgja`. Then `PLATFORMS=nokia_srlinux make
test-e2e` once, `E2E-PARTIAL`.

## 9. The records and the greps

`make linkcheck` clean; `/usr/bin/grep -rn 'FylgjaDevice\|FylgjaContract\|iftype\|contract_version\|set-role' --include='*.md' --include='*.go' --include='*.json' --include='*.yaml' --include='*.sh' .` finds the retired names only where each hit is a past-tense record or frozen test data:
the decision log; the contracts' version histories (each format's description,
`contracts/api.md`'s and `contracts/cli.md`'s accounts of what 017 removed, and `cli.md`'s
014 and 015 layers); the retired entries of `docs/architecture.md`, `docs/glossary.md`, `docs/roadmap.md` and the
dated facts of `docs/verified-facts.md`; Go comments in the past tense
(`internal/bundle/verify.go`, `internal/compiler/manifest.go`, `internal/ctm/json.go`,
`internal/lab/wire/types.go`); the frozen copies under the packages' `testdata/contracts/`,
`testdata/ctm/defects/version-1.json` and `internal/bundle/testdata/three-node-4.manifest.json`,
and the tests that build an older format or hold a retired name absent; and 013's, 014's
and 015's records and this feature's (on a working host the git-ignored `local/` adds the
command logs' and the loop's copies); the credential greps of 015's quickstart over the tree and the outputs find nothing; `make diagrams` changes nothing on a second run.
