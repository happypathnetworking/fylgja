package server

import (
	"context"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// twin rehearse's guards (015) refuse before any connection, as stage plan's do: --branch
// absent is --branch is required, operation.failed, and --branch= is stage.ref.invalid at
// start, each exit 2. The API lists the operation before the run behind the guards is built,
// so a branch the guards pass is refused at start with nothing read, dialled or started:
// the options here carry no Infrahub, no service and no runner for anything to reach.
func TestRehearseGuardsBeforeAnyConnection(t *testing.T) {
	for _, c := range []struct {
		name       string
		f          rehearseFlags
		rule, step string
		message    string
	}{
		{"--branch absent", rehearseFlags{}, findings.RuleOperationFailed, "", "--branch is required"},
		{"--branch=", rehearseFlags{branchGiven: true}, findings.RuleStageRefInvalid, findings.StepStart, ""},
		{"a branch", rehearseFlags{branch: "change-1", branchGiven: true}, findings.RuleOperationFailed, findings.StepStart, ""},
	} {
		code, doc := exitOf(t, runTwinRehearse(context.Background(), &options{}, &c.f))
		if code != findings.ExitError || doc.Operation != findings.OpTwinRehearse || len(doc.Findings) != 1 {
			t.Fatalf("%s: exit %d, %+v", c.name, code, doc)
		}
		f := doc.Findings[0]
		if f.Rule != c.rule || f.Step != c.step || c.message != "" && f.Message != c.message {
			t.Errorf("%s: %+v, want %s at %q", c.name, f, c.rule, c.step)
		}
	}
}
