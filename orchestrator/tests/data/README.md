# Recorded answers

The answers tier 1 reads in place of a live Infrahub or core: GraphQL replies under
`graphql/`, findings cases under `findings/`, each written by the task that ports the Go
test it carries over (020's T015 onward).

`snapshot/` holds Go-written snapshots: the four wrapped fixtures, copied from
`testdata/snapshot/` (a test holds each copy to its original), and `escapes.json`, whose
strings carry every character Go escapes otherwise than `json.dumps`, written by
`go test ./internal/snapshot -run TestTheOrchestratorsEscapesFixture -update` and held
to Go's encoder by the same test.

`frames/` holds the core's answers as the API carries them, one frame a line, which
`test_core.py`'s stub server answers (020's T023). A throwaway Go test in `internal/server`
recorded them from the server's own test harness and was deleted: a create detached from
the fixture's snapshot (`detachedAnswer`), a destroy detached, run.read of
`cancel-during-push`'s recorded history running (cut at its twentieth event) and ended,
run.interrupt of it running, run.read of a run the workflow service does not hold, and a
create refused `run.flags.conflict`, each under `render: text`. Two edits: the replayed
run's id is the detached create's (`…dp1`), so the read follows the start, and the test's
temporary state root in the create's two lines is `/state`.

`ctm/` holds copies of `testdata/ctm/`'s fixtures and defects (a test holds each copy to
its original; `version-1.json` is left out, since no CTM `1` reaches the rules), and under
`cases/` CTMs written from `three-node.json` with one change each, named by it.
`ctm/intrinsic.json` is the core's `validate.Intrinsic` findings of every CTM beside it,
written by `go test ./internal/validate -run TestTheOrchestratorsIntrinsicCases -update`
and held to Go's rules by the same test: the words the orchestrator's `validate.py` is
held to (020's T016).

`schema/schema-26336e9.json` is a copy of `internal/intent/testdata/`'s recorded
`GET /api/schema` answer for the schema library at `26336e9` (a test holds the copy to its
original); each conformance case changes it in the test, as the Go test does.
`schema/dcim-cable-absent.yaml` is a copy of `internal/intent/testdata/`'s schema change, the
library's `DcimCable` removed by `state: absent` (a test holds the copy to its original),
which tier 2 loads on a throwaway branch through the fixture tool's `-load-schema-file`
(`tests/contract/test_read_conformance.py`, 020's T020).

`probes/` holds copies of `testdata/probes/`'s declarations, `invalid/` beside them (a test
holds each copy to its original and the set to the original's), which `test_probes.py`
reads as the Go tests of `internal/probe` and `internal/server` read them.
`schema/schema-fylgja-probe.json` is a copy of `internal/intent/testdata/`'s recorded
`FylgjaProbe` node (a test holds the copy to its original), added to the default branch's
schema in the test, less the attributes a case drops, as the Go test does.

`graphql/fylgja-fixture/` is this host's Infrahub 1.11.2 answering the adapter for the
fixture branch on 2026-10-29, recorded read-only by the adapter itself (020's T017):
`read.json` the Devices and Ports answers and the branch's schema hash, `object-<id>.txt`
the three artifacts' bytes, `stamps.json` the IntentStamps, PortStamps, QueryGroups,
BranchPoint and IntentEvents answers, and `go-stamps-events.json` what the Go reader's
`Stamps` and `IntentEvents` returned for the same branch at the same moment.
`test_recorded.py` replays them: the read files `0940db93…`, and the stamps and events are
Go's. They hold node ids and timestamps, no credential and no address.

`graphql/stages/` holds the stages' answers (020's T018). `golden.json` is the golden
listing's proposed change (`tests/golden/README.md`) as Infrahub answers it, written from
the golden's values: its id, its three marks' ids, ats and descriptions, its branch's
branched_from, the branch's stamps with n1's artifact the latest write one microsecond
before the head, main holding no device, and the default branch's schema cut from this
host's `main` to the stage kind and `CoreProposedChange`; `test_stages.py` lists it through
the real reader and stamper and holds the block to `stages.json` and
`stages-with-twin.json`. `live.json` is a live proposed change recorded read-only by the
adapter on 2026-10-29, with the Go server's `stage list --json` and each stage's resolution
in its `stage plan --json` of the same moment; each request is kept once, and every branch
schema answer is `schema/schema-26336e9.json` under the hash the branch answered, as
`test_recorded.py` serves it. Node ids and timestamps, no credential and no address.

`findings/` holds one document of each of the sixteen operations, and more where a shape
asks, transcribed by hand from `internal/findings`' Go tests (each case's `about` names
its test), with the text `WriteText` prints for it and its exit (020's T019). A throwaway Go
test held all thirty to the current contract, to `WriteText` and to `WriteJSON`, byte for
byte, before it was deleted (research §5.13); `test_findings.py` holds the Python renderer
to them.
