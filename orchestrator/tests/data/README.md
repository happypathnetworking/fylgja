# Recorded answers

The answers tier 1 reads in place of a live Infrahub or core: GraphQL replies under
`graphql/`, findings cases under `findings/`, each written by the task that ports the Go
test it carries over (020's T015 onward).

`snapshot/` holds Go-written snapshots: the four wrapped fixtures, copied from
`testdata/snapshot/` (a test holds each copy to its original), and `escapes.json`, whose
strings carry every character Go escapes otherwise than `json.dumps`, written by
`go test ./internal/snapshot -run TestTheOrchestratorsEscapesFixture -update` and held
to Go's encoder by the same test.

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
