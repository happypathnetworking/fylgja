package snapshot

import (
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// A snapshot is the compiler's input wrapped: it imports the CTM, the probe's declaration
// (016), the findings whose rules name a probe's fault, and the standard library alone, so
// nothing here reads a source, compiles, files a bundle or reaches the lab host.
func TestSnapshotImportsTheCTMAndTheProbeAlone(t *testing.T) {
	admitted := map[string]bool{
		"github.com/happypathnetworking/fylgja/internal/ctm":      true,
		"github.com/happypathnetworking/fylgja/internal/probe":    true,
		"github.com/happypathnetworking/fylgja/internal/findings": true,
	}
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
			// The standard library's paths have no dot in their first element.
			if admitted[path] || !strings.Contains(strings.Split(path, "/")[0], ".") {
				continue
			}
			t.Errorf("%s imports %q: the snapshot imports the CTM, the probe, the findings and the standard library alone", name, path)
		}
	}
	if checked == 0 {
		t.Fatal("no source files found; the check proved nothing")
	}
}
