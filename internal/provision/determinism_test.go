package provision

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
)

// Workflow code is replayed, so it must do the same thing every time: no filesystem,
// process, network, wall clock or randomness, and no path to host-bound code
// (Constitution VIII). internal/lab/wire is allowed; its own test holds it to
// a no-I/O import rule.
func TestWorkflowFilesAreDeterministic(t *testing.T) {
	forbiddenImports := map[string]bool{
		"os": true, "os/exec": true, "net": true, "net/http": true,
		"math/rand": true, "math/rand/v2": true, "io/fs": true, "path/filepath": true,
		"github.com/happypathnetworking/fylgja/internal/lab": true,
	}
	forbiddenClock := map[string]bool{"Now": true, "Sleep": true, "After": true, "Tick": true}

	files, err := filepath.Glob("workflow_*.go")
	if err != nil {
		t.Fatal(err)
	}
	files = append(files, "options.go")

	var checked []string
	for _, name := range files {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		fset := token.NewFileSet()
		f, err := parser.ParseFile(fset, name, nil, 0)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		checked = append(checked, name)

		timeName := ""
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil {
				t.Fatal(err)
			}
			if forbiddenImports[path] {
				t.Errorf("%s imports %q: workflow code must be deterministic", name, path)
			}
			if path == "time" {
				timeName = "time"
				if spec.Name != nil {
					timeName = spec.Name.Name
				}
			}
		}
		if timeName == "" {
			continue
		}
		ast.Inspect(f, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if pkg, ok := sel.X.(*ast.Ident); ok && pkg.Name == timeName && forbiddenClock[sel.Sel.Name] {
				t.Errorf("%s uses time.%s: workflow code reads workflow.Now and waits with workflow.Sleep",
					fset.Position(sel.Pos()), sel.Sel.Name)
			}
			return true
		})
	}
	for _, must := range []string{"workflow_provision.go", "options.go"} {
		if !slices.Contains(checked, must) {
			t.Errorf("%s was not checked; the rule proved nothing about it", must)
		}
	}
}
