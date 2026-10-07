package conformance

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// readTwin reads the twin under a state root as the boot half needs it: the record the
// run wrote last and the staged bundle's manifest, where the worker lays them out
// (lab.PathsAt). root is $FYLGJA_STATE_ROOT, and must be absolute, since go test runs in
// internal/conformance and a relative root is not the worker's. Given no ready twin it
// fails naming what it needed; it boots nothing itself. TestBootHalf (tier 3)
// calls it; TestBootHalfNeedsATwin produces its refusals in tier 1.
func readTwin(root string) (wire.TwinRecord, compiler.Manifest, error) {
	if root == "" {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf(
			"the boot half reads the twin under %s, which is unset; set it to the absolute state root the worker uses", lab.EnvStateRoot)
	}
	if !filepath.IsAbs(root) {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf(
			"%s is %q, which is not absolute: go test runs in internal/conformance, so a relative root is not the worker's", lab.EnvStateRoot, root)
	}
	paths := lab.PathsAt(root)
	if _, err := os.Stat(paths.TwinJSON); errors.Is(err, fs.ErrNotExist) {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf(
			"the boot half needs a ready twin: %s is absent; it boots nothing itself", paths.TwinJSON)
	}
	rec, err := lab.ReadRecord(paths.TwinJSON)
	if err != nil {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf("the twin's record: %w", err)
	}
	path := filepath.Join(paths.TwinBundle, compiler.ManifestFile)
	b, err := os.ReadFile(path)
	if err != nil {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf("the twin's staged bundle: %w", err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf("the twin's staged manifest %s: %w", path, err)
	}
	if len(m.Nodes) == 0 {
		return wire.TwinRecord{}, compiler.Manifest{}, fmt.Errorf("the twin's staged manifest %s names no node", path)
	}
	return rec, m, nil
}

// Given no ready twin, the boot half fails naming what it needed, in tier 1: an
// unset root, a relative one, a root with no twin.json, and a record without its staged
// bundle. A root holding both reads.
func TestBootHalfNeedsATwin(t *testing.T) {
	empty := t.TempDir()
	noBundle := t.TempDir()
	writeRecord(t, noBundle)
	ready := t.TempDir()
	writeRecord(t, ready)
	b, err := os.ReadFile(repo("testdata", "golden", "three-node", "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(ready, "twin", "bundle"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ready, "twin", "bundle", "manifest.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}

	for _, c := range []struct {
		root, want string
	}{
		{"", "the boot half reads the twin under FYLGJA_STATE_ROOT, which is unset; set it to the absolute state root the worker uses"},
		{"local", `FYLGJA_STATE_ROOT is "local", which is not absolute: go test runs in internal/conformance, so a relative root is not the worker's`},
		{empty, "the boot half needs a ready twin: " + filepath.Join(empty, "twin", "twin.json") + " is absent; it boots nothing itself"},
		{noBundle, "the twin's staged bundle: open " + filepath.Join(noBundle, "twin", "bundle", "manifest.json") + ": no such file or directory"},
	} {
		_, _, err := readTwin(c.root)
		if err == nil || err.Error() != c.want {
			t.Errorf("readTwin(%q) = %v\nwant %s", c.root, err, c.want)
		}
	}

	rec, m, err := readTwin(ready)
	if err != nil {
		t.Fatal(err)
	}
	if len(rec.Nodes) != 3 || len(m.Nodes) != 3 || m.BundleVersion != compiler.BundleVersion {
		t.Errorf("read %d recorded nodes and %d manifest nodes (bundle %q); want the three-node twin at bundle %q",
			len(rec.Nodes), len(m.Nodes), m.BundleVersion, compiler.BundleVersion)
	}
}

func writeRecord(t *testing.T, root string) {
	t.Helper()
	rec := wire.TwinRecord{TwinVersion: "2", Lab: "fylgja", Nodes: []wire.TwinNode{
		recordNode("n1", "172.20.20.2", "nokia_srlinux", "embedded", 15.8),
		recordNode("n2", "172.20.20.3", "nokia_srlinux", "embedded", 15.9),
		recordNode("n3", "172.20.20.4", "nokia_srlinux", "embedded", 16.03),
	}}
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "twin"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "twin", "twin.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
}
