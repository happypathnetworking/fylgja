package cli

import (
	"context"
	"path/filepath"
	"slices"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// A create that fails at compile reports exactly what `twin compile` would, under the
// same identifiers (D-011). Both compile a snapshot on stage.Compile: twin compile in its
// own handler, a create in the server's compileAndFile, after the snapshot's resolve and
// before any run, since no run compiles (019). Asserted for every defect CTM, sent to each
// command as the same snapshot file, so neither twin compile's pre-checks nor the create's
// resolve and filing can drift from the other. A snapshot whose CTM breaks a rule that reads
// no package is refused at compile before it is filed (018), so that create reports those
// rules alone, each one twin compile reports too. A create the compile refused starts no run.
func TestCreateReportsM1Findings(t *testing.T) {
	defects, err := filepath.Glob(repoPath("testdata", "ctm", "defects", "*.json"))
	if err != nil || len(defects) == 0 {
		t.Fatalf("no defect CTMs found (%v); the test would prove nothing", err)
	}

	for _, path := range defects {
		t.Run(filepath.Base(path), func(t *testing.T) {
			wrapped := wrappedCTM(t, path)
			_, compiled := docOf(t, runCompile(&options{asJSON: true},
				&compileFlags{snapshotPath: wrapped, out: filepath.Join(t.TempDir(), "bundle")}))
			var want []string
			for _, f := range compiled.Findings {
				want = append(want, f.Rule)
			}
			slices.Sort(want)
			if c, err := ctm.Load(path); err == nil {
				if intrinsic := validate.Intrinsic(c); intrinsic.Rejected() {
					got := sortedRules(intrinsic)
					for _, rule := range got {
						if !slices.Contains(want, rule) {
							t.Errorf("validate.Intrinsic refuses %s, which twin compile does not report (%v)", rule, want)
						}
					}
					want = got
				}
			}

			useStateRoot(t)
			useInterrupts(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			var createErr error
			captureStdout(t, func() {
				createErr = runCreate(context.Background(), &options{asJSON: true}, &createFlags{snapshot: wrapped, snapshotGiven: true})
			})
			_, created := exitOf(t, createErr)
			if got := sortedRules(created.Findings); !slices.Equal(got, want) {
				t.Errorf("twin create --snapshot rules %v, twin compile rules %v", got, want)
			}
			if created.Findings.Rejected() && len(svc.started) != 0 {
				t.Errorf("a create its compile refused started %+v", svc.started)
			}
		})
	}
}

func sortedRules(list findings.List) []string {
	var out []string
	for _, f := range list {
		out = append(out, f.Rule)
	}
	slices.Sort(out)
	return out
}
