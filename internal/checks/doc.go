// Package checks is tier 2's proof of the two checks this repository ships to Infrahub,
// fylgja-step and fylgja-twin, inside a running Infrahub (research R-18). It holds no product
// code. The checks are Python, glue on Infrahub's runtime (infrahub/checks/,
// contracts/checks.md), and the repository has one test framework (Constitution I), so they
// are proved here, from Go, as Infrahub runs them: its one test, under the build tag contract,
// serves the tree's checks from the host's Docker bridge under a registration of its own,
// opens a proposed change on a throwaway branch, and reads the checks' conclusions and
// messages back from Infrahub's pipeline.
//
// The registration Infrahub imports from origin's main (D-044) declares the checks under
// their own names; once it has imported them, a second registration of the same names would
// be refused, since Infrahub holds each check definition's and each query's name once on
// main (research §5.3). So the test registers the tree's files under test-only names.
package checks

// The names .infrahub.yml declares.
const (
	// StepCheck is the plan's check, and TwinCheck the rehearsal's.
	StepCheck = "fylgja-step"
	TwinCheck = "fylgja-twin"
	// Query is the query each check's class binds by its query attribute.
	Query = "fylgja_branch"
)

// The names the test registers the tree's checks under.
const (
	TestStepCheck = "fylgja-test-step"
	TestTwinCheck = "fylgja-test-twin"
	// TestQuery is the query's name in the test's registration, which each class's query
	// attribute is rewritten to name in the copy the test serves (research §5.3).
	TestQuery = "fylgja_test_branch"
	// RepositoryPrefix begins the test's registration, fylgja-test-checks-<pid>, inside the
	// prefix every write of a test is held to.
	RepositoryPrefix = "fylgja-test-checks-"
)

// TestNames is each check of the registration under the name the test registers it as.
var TestNames = map[string]string{
	StepCheck: TestStepCheck,
	TwinCheck: TestTwinCheck,
}
