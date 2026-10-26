package cli

import (
	"net/url"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// withoutKind is a schema mutation: the branch's schema without kind, as on a branch that
// does not hold the library (017).
func withoutKind(kind string) func(map[string]any) {
	return func(doc map[string]any) {
		var nodes []any
		for _, n := range doc["nodes"].([]any) {
			if n.(map[string]any)["kind"] != kind {
				nodes = append(nodes, n)
			}
		}
		doc["nodes"] = nodes
	}
}

// schemaReads counts the schema requests made of each branch.
func schemaReads(f *fakeInfrahub) map[string]int {
	n := map[string]int{}
	for _, r := range f.requests() {
		if r.Path == "/api/schema" {
			q, _ := url.ParseQuery(r.Query)
			n[q.Get("branch")]++
		}
	}
	return n
}

// operations counts the GraphQL requests made of a branch, by operation.
func operations(f *fakeInfrahub, branch string) map[string]int {
	n := map[string]int{}
	for _, r := range f.requests() {
		if r.Path == "/graphql/"+branch {
			n[r.Operation]++
		}
	}
	return n
}

// A stage command on a proposed change whose source branch does not hold the library is
// refused with the conformance findings, exit 1, every one in one pass, before the branch's
// stamps are read (017; US3 scenario 4, FR-011): the stamps select DcimDevice, and on such
// a branch they would fail as a GraphQL error, operation.failed, naming nothing of the
// mapping's table. stage plan and twin create --stage alike: schema.kind.missing
// DcimDevice naming the branch and the commit, at resolve, with no IntentStamps sent,
// nothing read, compiled or started.
func TestStageCommandsRefuseANonConformantBranch(t *testing.T) {
	const want = "branch " + lessLink + ": the branch's schema has no kind DcimDevice; the mapping reads it as " +
		"opsmill/schema-library@26336e9 has it"
	for _, c := range []struct {
		name string
		args []string
	}{
		{"stage plan", []string{"stage", "plan", "--branch", lessLink}},
		{"twin create --stage", []string{"twin", "create", "--stage", lessLink + "/cabled"}},
		{"twin create --stage, the head", []string{"twin", "create", "--stage", lessLink + "/head"}},
		{"intent read --stage", []string{"intent", "read", "--stage", lessLink + "/live", "--out", filepath.Join(t.TempDir(), "ctm.json")}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := planInfrahub(t, twoMarks()...)
			f.schemaMutations = map[string]func(map[string]any){lessLink: withoutKind("DcimDevice")}
			f.start()

			code, doc := executeStage(t, c.args...)
			if code != findings.ExitRejected || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 1 with schema.kind.missing alone", code, doc.Findings)
			}
			got := doc.Findings[0]
			step := findings.StepResolve
			if c.args[0] == "intent" {
				step = "" // intent read's operations carry no step
			}
			if got.Severity != findings.Rejection || got.Rule != findings.RuleSchemaKindMissing || got.Object != "DcimDevice" ||
				got.Step != step || got.Message != want {
				t.Errorf("finding %+v; want schema.kind.missing DcimDevice at step %q saying %q", got, step, want)
			}
			if ops := operations(f, lessLink); len(ops) != 0 {
				t.Errorf("%s was sent %v; want nothing past its schema", lessLink, ops)
			}
			if n := schemaReads(f)[lessLink]; n != 1 {
				t.Errorf("%s's schema was read %d times; want once", lessLink, n)
			}
			if got := storedBundles(t, paths.Bundles); len(got) != 0 {
				t.Errorf("the store holds %v", got)
			}
			mustCarryNoToken(t, c.name, doc)
			validateM10Document(t, doc)
		})
	}
}

// The destination's schema is checked as the source branch's is, before its first stamps
// read: on a main that does not hold the library, a plan's branch point is refused with the
// conformance findings, once, naming main, where its staleness and stage.main.moved would
// each have read main's stamps; the rest of the plan reads the source branch, which
// conforms.
func TestStagePlanRefusesTheBranchPointOfANonConformantMain(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.schemaMutations = map[string]func(map[string]any){"main": withoutKind("DcimDevice")}
	f.start()

	code, doc := executeStage(t, "stage", "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	if code != findings.ExitRejected || len(stages) != 4 {
		t.Fatalf("exit %d, %d stages; want 1 and four", code, len(stages))
	}
	bp := stages[0]
	if len(bp.Findings) != 1 || bp.Findings[0].Rule != findings.RuleSchemaKindMissing || bp.Findings[0].Object != "DcimDevice" ||
		bp.Findings[0].Step != findings.StepResolve || !strings.HasPrefix(bp.Findings[0].Message, "branch main: ") {
		t.Errorf("the branch point's findings %+v; want schema.kind.missing DcimDevice alone, naming main, at resolve", bp.Findings)
	}
	if got := compiledRefs(stages); len(got) != 3 || got[0] != lessLink+"/cabled" {
		t.Errorf("compiled %v; want every stage but the branch point", got)
	}
	if ops := operations(f, "main"); len(ops) != 0 {
		t.Errorf("main was sent %v; want nothing past its schema", ops)
	}
	if n := schemaReads(f)["main"]; n != 1 {
		t.Errorf("main's schema was read %d times; want once", n)
	}
}

// On a conformant branch the check adds one schema request per branch to what a command
// sends and changes nothing else: stage plan's stamps and reads are sent as before, each
// stage's read checking its own branch's schema as stage.Read does, and the plan compiles
// every stage (017).
func TestStagePlanChecksEachBranchOnce(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.start()

	code, doc := executeStage(t, "stage", "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	if code != findings.ExitOK || len(compiledRefs(stages)) != 4 {
		t.Fatalf("exit %d, compiled %v; want 0 and every stage", code, compiledRefs(stages))
	}
	schema := schemaReads(f)
	for _, branch := range []string{lessLink, "main"} {
		ops := operations(f, branch)
		if ops["IntentStamps"] == 0 || ops["Devices"] == 0 {
			t.Errorf("%s was sent %v; want its stamps and its reads", branch, ops)
		}
		if schema[branch] != 1+ops["Devices"] {
			t.Errorf("%s's schema was read %d times for %d reads; want once more than its reads", branch, schema[branch], ops["Devices"])
		}
	}
}
