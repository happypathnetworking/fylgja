package probe

import (
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// admitted are the imports outside the standard library a probe may make: the findings it
// reports, the module's embedded files (the shipped packages and their schema), and the two
// decoders internal/psp reads a package with.
var admitted = []string{
	"github.com/happypathnetworking/fylgja",
	"github.com/happypathnetworking/fylgja/internal/findings",
	"gopkg.in/yaml.v3",
	"github.com/santhosh-tekuri/jsonschema/v6",
}

// A probe is the one definition the compiler, the snapshot, the server and the lab share
// without importing one another: it imports findings, the embedded files, the two decoders
// and the standard library alone, so nothing here reads a source, compiles, files a bundle
// or reaches the lab host. The plan's "findings and the standard library alone" admits the
// decoders and the embedded files, without which no package could be loaded or held to its
// schema; no other Fylgja package is among them.
func TestProbeImportsFindingsAndTheStandardLibraryAlone(t *testing.T) {
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
			if !strings.Contains(strings.Split(path, "/")[0], ".") {
				continue
			}
			ok := false
			for _, a := range admitted {
				ok = ok || path == a
			}
			if !ok {
				t.Errorf("%s imports %q: a probe imports findings, the embedded files, the two decoders and the standard library alone", name, path)
			}
		}
	}
	if checked == 0 {
		t.Fatal("no source files found; the check proved nothing")
	}
}

// The parts of a probe the snapshot and the compiler read, the declaration and the pure
// reading of ping, import findings and the standard library alone, as the plan says.
func TestTheDeclarationAndThePingReadingImportNoDecoder(t *testing.T) {
	for _, name := range []string{"decl.go", "ping.go"} {
		f, err := parser.ParseFile(token.NewFileSet(), name, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		for _, spec := range f.Imports {
			path, _ := strconv.Unquote(spec.Path.Value)
			if strings.Contains(strings.Split(path, "/")[0], ".") && path != "github.com/happypathnetworking/fylgja/internal/findings" {
				t.Errorf("%s imports %q: the declaration and ping's reading import findings and the standard library alone", name, path)
			}
		}
	}
}
