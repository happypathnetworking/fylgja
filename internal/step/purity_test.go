package step

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The step is a pure function of two bundles, as the compiler is (Constitution
// V), and for the same reason: it is what M11 applies to a running twin, so it must say the
// same thing about the same two bundles wherever and whenever it runs. The test is
// internal/compiler/purity_test.go's shape; a failure is a design error, not a test to
// relax.
func TestStepIsPure(t *testing.T) {
	forbidden := map[string]string{
		"os":        "file I/O",
		"net":       "network I/O",
		"net/http":  "network I/O",
		"time":      "wall-clock time makes output non-deterministic",
		"math/rand": "randomness makes output non-deterministic",
		"os/exec":   "process execution",
		"github.com/happypathnetworking/fylgja/internal/intent": "intent performs I/O",
		"github.com/happypathnetworking/fylgja/internal/bundle": "bundle writes files",
	}
	seen := 0
	err := filepath.WalkDir(".", func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return err
		}
		seen++
		f, err := parser.ParseFile(token.NewFileSet(), p, nil, parser.ImportsOnly)
		if err != nil {
			return err
		}
		for _, imp := range f.Imports {
			path := strings.Trim(imp.Path.Value, `"`)
			if why, bad := forbidden[path]; bad {
				t.Errorf("%s imports %q (%s): the step must remain a pure function", p, path, why)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if seen == 0 {
		t.Fatal("no source file was read: the walk found nothing to hold to the rule")
	}
}
