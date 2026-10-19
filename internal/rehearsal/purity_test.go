package rehearsal

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// The rehearsal's rules and renderings are pure, as the step's are (research R-11): the
// workflow classifies each stage with them, so they must decide the same on a replay, and
// the server renders the report with them, so the same run gives the same block and the same
// markdown wherever it is rendered. The test is internal/step/purity_test.go's shape, and
// holds two rules more: of the module the package imports findings, lab/wire and step alone,
// and it may name time's durations but never read its clock. A failure is a design error,
// not a test to relax.
func TestRehearsalIsPure(t *testing.T) {
	const module = "github.com/happypathnetworking/fylgja/"
	forbidden := map[string]string{
		"os":            "file I/O and the environment",
		"io":            "I/O",
		"io/fs":         "file I/O",
		"io/ioutil":     "file I/O",
		"bufio":         "I/O",
		"path/filepath": "the file system",
		"net":           "network I/O",
		"net/http":      "network I/O",
		"os/exec":       "process execution",
		"syscall":       "the operating system",
		"math/rand":     "randomness makes output non-deterministic",
		"math/rand/v2":  "randomness makes output non-deterministic",
		"crypto/rand":   "randomness makes output non-deterministic",
		"log":           "logging is output",
		"log/slog":      "logging is output",
	}
	allowed := map[string]bool{
		module + "internal/findings": true,
		module + "internal/lab/wire": true,
		module + "internal/step":     true,
	}
	// time's clock: anything that reads the time, waits on it or names the local zone.
	clock := map[string]bool{
		"Now": true, "Since": true, "Until": true, "Sleep": true, "After": true, "AfterFunc": true,
		"Tick": true, "NewTimer": true, "NewTicker": true, "Local": true, "LoadLocation": true,
	}
	seen := 0
	err := filepath.WalkDir(".", func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return err
		}
		seen++
		f, err := parser.ParseFile(token.NewFileSet(), p, nil, 0)
		if err != nil {
			return err
		}
		timeName := ""
		for _, imp := range f.Imports {
			path, _ := strconv.Unquote(imp.Path.Value)
			if why, bad := forbidden[path]; bad {
				t.Errorf("%s imports %q (%s): the rehearsal's rules must remain pure", p, path, why)
			}
			if strings.HasPrefix(path, module) && !allowed[path] {
				t.Errorf("%s imports %q: the rehearsal imports findings, lab/wire and step alone of the module", p, path)
			}
			if path == "time" {
				timeName = "time"
				if imp.Name != nil {
					timeName = imp.Name.Name
				}
			}
		}
		if timeName == "" {
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if x, ok := sel.X.(*ast.Ident); ok && x.Name == timeName && clock[sel.Sel.Name] {
				t.Errorf("%s uses time.%s: the rehearsal reads no clock but the run's, which its caller passes in",
					p, sel.Sel.Name)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if seen == 0 {
		t.Fatal("no source file was read: the walk found nothing to hold to the rule")
	}
}
