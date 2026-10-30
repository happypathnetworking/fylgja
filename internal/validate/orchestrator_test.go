package validate

import (
	"bytes"
	"encoding/json"
	"flag"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

var update = flag.Bool("update", false, "rewrite the orchestrator's intrinsic findings")

// orchestratorCTMs is where the orchestrator's validate module finds its cases (020's
// T016): copies of testdata/ctm's fixtures and defects, and cases written from
// three-node.json, one change each.
func orchestratorCTMs() string {
	return filepath.Join("..", "..", "orchestrator", "tests", "data", "ctm")
}

// intrinsicName is the file under orchestratorCTMs holding Intrinsic's findings of each
// case, by its path under that directory.
const intrinsicName = "intrinsic.json"

// orchestrator/tests/data/ctm/intrinsic.json is Intrinsic's findings of every CTM beside
// it, word for word, or is rewritten under -update: what the orchestrator's port of the
// rules (adapters/infrahub/validate.py) is held to, so the two word every refusal alike.
func TestTheOrchestratorsIntrinsicCases(t *testing.T) {
	dir := orchestratorCTMs()
	got := map[string]findings.List{}
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(path, ".json") || d.Name() == intrinsicName {
			return err
		}
		c, err := ctm.Load(path)
		if err != nil {
			t.Errorf("loading %s: %v", path, err)
			return nil
		}
		rel, _ := filepath.Rel(dir, path)
		list := Intrinsic(c)
		if list == nil {
			list = findings.List{}
		}
		got[filepath.ToSlash(rel)] = list
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) == 0 {
		t.Fatalf("no CTM under %s", dir)
	}
	want, err := json.MarshalIndent(got, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	want = append(want, '\n')
	path := filepath.Join(dir, intrinsicName)
	if *update {
		if err := os.WriteFile(path, want, 0o644); err != nil {
			t.Fatal(err)
		}
		t.Logf("%s rewritten", path)
		return
	}
	held, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v (run: go test ./internal/validate -run TestTheOrchestratorsIntrinsicCases -update)", path, err)
	}
	if !bytes.Equal(held, want) {
		t.Errorf("%s is not Intrinsic's findings of the CTMs beside it (run with -update and review the diff)", path)
	}
}
