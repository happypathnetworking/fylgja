package compiler

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// directImports returns the import paths of every non-test Go file in a directory tree.
func directImports(t *testing.T, dir string) map[string][]string {
	t.Helper()
	out := map[string][]string{}
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		fset := token.NewFileSet()
		// ImportsOnly still honours build tags being *present*, but we deliberately
		// parse every file regardless of tags: an import that only appears under a tag
		// is still an import we want to know about.
		f, err := parser.ParseFile(fset, p, nil, parser.ImportsOnly)
		if err != nil {
			return err
		}
		for _, imp := range f.Imports {
			out[p] = append(out[p], strings.Trim(imp.Path.Value, `"`))
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// The compiler is a pure function (Constitution V). Purity is not a convention here:
// it is what makes the riskiest logic in Fylgja testable with no infrastructure, and
// what lets `fylgja twin compile` run the identical code the golden tests exercise.
// A failure here is a design error, not a test to relax.
func TestCompilerIsPure(t *testing.T) {
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
	for file, imports := range directImports(t, ".") {
		for _, imp := range imports {
			if why, bad := forbidden[imp]; bad {
				t.Errorf("%s imports %q (%s): the compiler must remain a pure function", file, imp, why)
			}
		}
	}
}

// platformNames are the platforms the tree knows by name: the two shipped ones, the
// design case, and the vendors, systems and container kinds any of them is modelled on.
// `ceos` joins the list at M7, with the second shipped platform.
var platformNames = regexp.MustCompile(`(?i)\b(srlinux|nokia|eos|chassisos|arista|ceos)\b`)

// No source under the compiler, the profile engine, the lab-host driver, the workflows,
// the stage pipelines, the bundle store or validation names a platform (Constitution
// II). A platform is data: the rules, the budgets, the
// probe and the push all come from its package, and the code that applies them branches
// on what a format value says, never on whose package it is — which is what makes a
// second platform a file under psp/ and nothing else. A comment counts too: a comment
// that explains code by a platform is the first sign of code that depends on one.
//
// The file set is M7's, wider than M6's two directories: it was empty across all seven
// when M7 began, and every change since must keep it so.
func TestCompilerNamesNoPlatform(t *testing.T) {
	for _, dir := range []string{
		".",
		filepath.Join("..", "psp"),
		filepath.Join("..", "lab"),
		filepath.Join("..", "provision"),
		filepath.Join("..", "stage"),
		filepath.Join("..", "bundle"),
		filepath.Join("..", "validate"),
		// M10: the step and the waypoint commands' package. Named here
		// because the walk is of named directories, not of
		// internal/ whole, and a missing directory fails it.
		filepath.Join("..", "step"),
		filepath.Join("..", "waypoint"),
		// M12: the readers of a booted node, moved out of the suite, and verify's core
		// (D-031, D-037). Reading is one mechanism
		// keyed by a package's conformance facet, so nothing in it names whose package it
		// is.
		filepath.Join("..", "verify"),
		// M13: the API's wire and client, its server (M12's command logic, moved), the
		// client's commands and the directory helper they share (D-031). A request names an
		// operation, never a platform.
		filepath.Join("..", "api"),
		filepath.Join("..", "server"),
		filepath.Join("..", "cli"),
		filepath.Join("..", "tree"),
	} {
		err := filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
				return err
			}
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			for i, line := range strings.Split(string(b), "\n") {
				if m := platformNames.FindString(line); m != "" {
					t.Errorf("%s:%d names the platform %q: %s", p, i+1, m, strings.TrimSpace(line))
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}

// The product never writes to Infrahub (Constitution III). The test harness
// does — that is what testsupport is for — so the boundary is enforced rather than
// trusted.
//
// The walk is over `cmd/fylgja` and the whole of `internal/`, not a list of package
// names, so a package added later — `internal/provision` at M2, `internal/server` at
// M13 — is covered the day it appears rather than the day somebody remembers to add it
// here.
func TestProductDoesNotImportTestSupport(t *testing.T) {
	root := filepath.Join("..", "..")
	for _, dir := range []string{filepath.Join(root, "cmd", "fylgja"), filepath.Join(root, "internal")} {
		if _, err := os.Stat(dir); os.IsNotExist(err) {
			continue
		}
		for file, imports := range directImports(t, dir) {
			if strings.Contains(filepath.ToSlash(file), "internal/testsupport") {
				continue
			}
			for _, imp := range imports {
				if strings.HasSuffix(imp, "internal/testsupport") {
					t.Errorf("%s imports the test harness: only tests may write to Infrahub", file)
				}
			}
		}
	}
}

// The conformance suite is `go test` and nothing else (M6 plan, Structure Decision): the
// CLI, the worker and the compiler know nothing of it, so a verdict is a test result and
// a README row, never something the product consults at run time.
func TestProductDoesNotImportConformance(t *testing.T) {
	root := filepath.Join("..", "..")
	seen := 0
	for _, dir := range []string{filepath.Join(root, "cmd"), filepath.Join(root, "internal")} {
		for file, imports := range directImports(t, dir) {
			seen++
			if strings.Contains(filepath.ToSlash(file), "internal/conformance/") {
				continue
			}
			for _, imp := range imports {
				if strings.HasSuffix(imp, "internal/conformance") {
					t.Errorf("%s imports the conformance suite: only its own tests may", file)
				}
			}
		}
	}
	if seen == 0 {
		t.Fatal("no product file was read: the walk found nothing to hold to the rule")
	}
}

// module is this module's import path, which every package of Fylgja's begins with.
const module = "github.com/happypathnetworking/fylgja/"

// moduleImports is every package of this module that the non-test files directly in dir
// import, by its path inside the module: internal/api for
// github.com/happypathnetworking/fylgja/internal/api. A sub-directory is a package of its own and is
// not counted.
func moduleImports(t *testing.T, dir string) []string {
	t.Helper()
	seen := map[string]bool{}
	for file, imports := range directImports(t, dir) {
		if filepath.Dir(file) != filepath.Clean(dir) {
			continue
		}
		for _, imp := range imports {
			if rest, ok := strings.CutPrefix(imp, module); ok {
				seen[rest] = true
			}
		}
	}
	out := make([]string, 0, len(seen))
	for p := range seen {
		out = append(out, p)
	}
	sort.Strings(out)
	return out
}

// reach is every package of this module that start's non-test files reach through its
// imports, followed to a fixed point, by its path inside the module; start itself is not
// in it unless an import comes back to it.
func reach(t *testing.T, root, start string) map[string]bool {
	t.Helper()
	reached := map[string]bool{}
	queue := moduleImports(t, start)
	for len(queue) > 0 {
		p := queue[0]
		queue = queue[1:]
		if reached[p] {
			continue
		}
		reached[p] = true
		queue = append(queue, moduleImports(t, filepath.Join(root, filepath.FromSlash(p)))...)
	}
	return reached
}

// A user-facing client reaches Fylgja through the API alone (D-040; Constitution XI). The
// client's commands live in internal/cli, and Go's imports are per
// package, so this walk is the boundary: from internal/cli's non-test files, every package
// of the module they reach is the API's wire and client, the findings document and the
// directory helper, and nothing else. Those three reach nothing of the module but the
// findings document, which reaches nothing. No flag or variable can make a client's
// command run the core, because the package that holds the commands does not link it.
//
// Test files are not walked: tests call the core, under D-040's exception. The second case
// runs the same walk over testdata/boundary/leaky, a client that imports internal/stage,
// and passes only when the walk names it.
func TestClientReachesTheCoreThroughTheAPIAlone(t *testing.T) {
	root := filepath.Join("..", "..")
	allowed := map[string]bool{"internal/api": true, "internal/findings": true, "internal/tree": true}

	got := reach(t, root, filepath.Join(root, "internal", "cli"))
	if len(got) == 0 {
		t.Fatal("internal/cli reaches no package of the module: the walk read nothing")
	}
	for p := range got {
		if !allowed[p] {
			t.Errorf("internal/cli reaches %s: a client's command reaches the core around the API", p)
		}
	}
	for p := range allowed {
		if !got[p] {
			t.Errorf("internal/cli does not reach %s, which the boundary names", p)
		}
	}
	for _, p := range []string{"internal/api", "internal/tree"} {
		for _, imp := range moduleImports(t, filepath.Join(root, filepath.FromSlash(p))) {
			if imp != "internal/findings" {
				t.Errorf("%s imports %s; it may import internal/findings alone", p, imp)
			}
		}
	}
	if imps := moduleImports(t, filepath.Join(root, "internal", "findings")); len(imps) != 0 {
		t.Errorf("internal/findings imports %v; it imports nothing of the module", imps)
	}

	// A sub-directory is a package of its own: testdata/boundary holds no file, and its one
	// sub-package's imports are not its.
	if imps := moduleImports(t, filepath.Join(root, "testdata", "boundary")); len(imps) != 0 {
		t.Errorf("testdata/boundary imports %v: the walk counted a sub-package's imports", imps)
	}

	// internal/bundle is reached through internal/stage alone, so the walk is held to follow
	// an import past the first.
	leaky := reach(t, root, filepath.Join(root, "testdata", "boundary", "leaky"))
	for _, p := range []string{"internal/stage", "internal/bundle"} {
		if !leaky[p] {
			t.Errorf("the walk from testdata/boundary/leaky does not name %s: it reached %v", p, leaky)
		}
	}
}
