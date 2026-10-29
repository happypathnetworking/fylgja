# Recorded answers

The answers tier 1 reads in place of a live Infrahub or core: GraphQL replies under
`graphql/`, findings cases under `findings/`, each written by the task that ports the Go
test it carries over (020's T015 onward).

`snapshot/` holds Go-written snapshots: the four wrapped fixtures, copied from
`testdata/snapshot/` (a test holds each copy to its original), and `escapes.json`, whose
strings carry every character Go escapes otherwise than `json.dumps`, written by
`go test ./internal/snapshot -run TestTheOrchestratorsEscapesFixture -update` and held
to Go's encoder by the same test.
