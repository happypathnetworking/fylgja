package wire

import (
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// Workflow files import this package, so it must hold nothing a workflow may not do:
// no filesystem, process, network, clock or randomness (Constitution VIII). Its only
// dependency outside the standard library is internal/findings, whose List it carries.
func TestWireImportsNoIO(t *testing.T) {
	forbidden := map[string]bool{
		"os": true, "os/exec": true, "net": true, "io/fs": true,
		"path/filepath": true, "time": true, "math/rand": true, "math/rand/v2": true,
	}
	const findingsPath = "github.com/happypathnetworking/fylgja/internal/findings"

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
			stdlib := !strings.Contains(strings.SplitN(path, "/", 2)[0], ".")
			switch {
			case path == findingsPath:
			case !stdlib:
				t.Errorf("%s imports %q: wire may import only internal/findings and the standard library", name, path)
			case forbidden[path], strings.HasPrefix(path, "net/"), strings.HasPrefix(path, "os/"):
				t.Errorf("%s imports %q: wire must hold no I/O, clock or randomness", name, path)
			}
		}
	}
	if checked == 0 {
		t.Fatal("no source files found; the check proved nothing")
	}
}
