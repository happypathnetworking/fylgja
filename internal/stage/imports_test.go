package stage

import (
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// The stages are shared by the stage commands, the activities and the dry run, and are
// usable without a workflow service: nothing here may reach Temporal or the lab host.
func TestStageImportsNoTemporalOrLab(t *testing.T) {
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	var checked int
	for _, name := range files {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		f, err := parser.ParseFile(token.NewFileSet(), name, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		checked++
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil {
				t.Fatal(err)
			}
			switch {
			case strings.HasPrefix(path, "go.temporal.io/"),
				path == "github.com/happypathnetworking/fylgja/internal/provision",
				strings.HasPrefix(path, "github.com/happypathnetworking/fylgja/internal/provision/"),
				path == "github.com/happypathnetworking/fylgja/internal/lab",
				strings.HasPrefix(path, "github.com/happypathnetworking/fylgja/internal/lab/"):
				t.Errorf("%s imports %q: the stages must not depend on Temporal or the lab host", name, path)
			}
		}
	}
	if checked == 0 {
		t.Fatal("no source files found; the check proved nothing")
	}
}
