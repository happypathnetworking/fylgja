package cli

import (
	"context"
	"errors"
	"path/filepath"
	"slices"
	"testing"

	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// A create that fails at compile reports exactly what `twin compile` would, under the
// same identifiers. Asserted for the shared stage and for the
// Compile activity a run executes, so neither the command's own pre-checks nor the
// activity's filing can drift from the other.
func TestCreateReportsM1Findings(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	defects, err := filepath.Glob(repoPath("testdata", "ctm", "defects", "*.json"))
	if err != nil || len(defects) == 0 {
		t.Fatalf("no defect CTMs found (%v); the test would prove nothing", err)
	}

	for _, path := range defects {
		t.Run(filepath.Base(path), func(t *testing.T) {
			_, doc := docOf(t, runCompile(&options{asJSON: true},
				&compileFlags{ctmPath: path, out: filepath.Join(t.TempDir(), "bundle")}))
			var want []string
			for _, f := range doc.Findings {
				want = append(want, f.Rule)
			}
			slices.Sort(want)

			root := t.TempDir()
			paths := lab.PathsAt(root)
			control := &provision.ControlActivities{Store: bundle.NewDirStore(paths.Bundles), Paths: paths}

			c, loadErr := ctm.Load(path)
			if loadErr != nil {
				// Neither can read it: twin compile says operation.failed, and so does the run.
				if !slices.Equal(want, []string{findings.RuleOperationFailed}) {
					t.Fatalf("ctm.Load failed (%v) but twin compile reported %v", loadErr, want)
				}
				_, err := control.Compile(context.Background(), provision.CompileInput{CTMPath: path})
				var appErr *temporal.ApplicationError
				if !errors.As(err, &appErr) || appErr.Type() != findings.RuleOperationFailed {
					t.Errorf("Compile activity error = %v, want %s", err, findings.RuleOperationFailed)
				}
				return
			}

			_, _, list := stage.Compile(c, reg)
			if got := sortedRules(list); !slices.Equal(got, want) {
				t.Errorf("stage.Compile rules %v, twin compile rules %v", got, want)
			}

			res, err := control.Compile(context.Background(), provision.CompileInput{CTMPath: path})
			if err != nil {
				t.Fatalf("Compile activity: %v", err)
			}
			if got := sortedRules(res.Findings); !slices.Equal(got, want) {
				t.Errorf("Compile activity rules %v, twin compile rules %v", got, want)
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
