// Package rehearsal holds a rehearsal's pure rules and renderings (015, D-051): the
// deadline its stages' budgets sum to under the ceiling, each stage's verdict against the
// baseline's findings, the report's block built from what the server decided and what the
// run returned, the text's lines, the commands that reproduce a failure by hand, and the
// markdown a check posts on the proposed change.
//
// It is shared by the workflow, which classifies each stage, and the server, which decides
// the deadline and builds the report, so each rule has one home. It imports findings,
// lab/wire and step alone of the module, and does no I/O, reads no clock and no
// environment: the same run gives the same block and the same markdown wherever it is
// rendered (research R-11; TestRehearsalIsPure).
package rehearsal
