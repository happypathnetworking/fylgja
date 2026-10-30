package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The three-node-probed golden's snapshot and bundle (testdata/snapshot/three-node-probed.json,
// testdata/golden/three-node-probed).
const (
	probedSnapshotID = "aef03f5d8136b49bb4e0b6b40c9473c5d009af966d07a5fe658860d203c1de3c"
	probedBundleID   = "5222063bac574cf7ba031a0cb7a04dc0ae8b40cca84403215bf5356c50dfcde9"
)

// snapshotSent is the snapshot file testdata/snapshot/<name> as a request carries it, under
// path.
func snapshotSent(t *testing.T, name, path string) api.File {
	t.Helper()
	raw, err := os.ReadFile(repoPath("testdata", "snapshot", name))
	if err != nil {
		t.Fatal(err)
	}
	return api.File{Path: path, Data: raw}
}

// diffPair is a twin.diff document's step block, as stages.schema.json's $defs/step has it.
type diffPair struct {
	From         string  `json:"from"`
	To           string  `json:"to"`
	FromBundleID *string `json:"from_bundle_id"`
	ToBundleID   *string `json:"to_bundle_id"`
	Computed     bool    `json:"computed"`
	Unchanged    *bool   `json:"unchanged"`
	Nodes        struct {
		Added, Removed []string
		Changed        []nodeChange
	} `json:"nodes"`
	Links struct {
		Added, Removed []struct {
			ID   string `json:"id"`
			A, B struct{ Node, Port string }
		}
	} `json:"links"`
	Artifacts struct {
		Changed []json.RawMessage
	} `json:"artifacts"`
}

// nodeChange is one node a pair names changed, and why.
type nodeChange struct {
	Node    string   `json:"node"`
	Reasons []string `json:"reasons"`
}

// pairOf is doc's step block, read back as the wire carries it.
func pairOf(t *testing.T, doc *findings.Document) diffPair {
	t.Helper()
	if doc.Step == nil || doc.Step.Pair == nil {
		t.Fatalf("the document carries no pair: %+v", doc.Step)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var read struct {
		Step diffPair `json:"step"`
	}
	if err := json.Unmarshal(b, &read); err != nil {
		t.Fatal(err)
	}
	return read.Step
}

// The step from the three-node golden to the three-node-probed one names the probe's two
// hosts and their two links (020, SC-006; R-05), and no artifact moved; the one device
// changed is n1, by its bootstrap alone, which enables the two ports the hosts take
// (ethernet-1/10 and -1/11, 016's compile), as the goldens' n1.cli differ:
// both compiled on the goldens' path to the goldens' ids, both snapshots and both bundles
// filed, and nothing dialled. The document names both sides and is the current contract's.
func TestDiffNamesTheProbesHostsAndTheirLinks(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	files := []api.File{snapshotSent(t, "three-node.json", "from.json"), snapshotSent(t, "three-node-probed.json", "to.json")}
	var err error
	out := captureStdout(t, func() {
		err = runTwinDiff(t.Context(), testOptions(t, false), &diffFlags{from: "from.json", to: "to.json"}, files)
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitOK || doc.Operation != findings.OpTwinDiff {
		t.Fatalf("exit %d, document %+v; want 0, twin.diff", code, doc)
	}
	if doc.SnapshotFrom != fixtureSnapshotID || doc.SnapshotTo != probedSnapshotID || doc.BundleFrom != fixtureBundleID ||
		doc.BundleTo != probedBundleID {
		t.Errorf("sides %s → %s, bundles %s → %s; want the goldens'", doc.SnapshotFrom, doc.SnapshotTo, doc.BundleFrom, doc.BundleTo)
	}
	if doc.SnapshotID != "" || doc.BundleID != "" || doc.Subject != nil {
		t.Errorf("snapshot %q, bundle %q, subject %+v; want none: a diff names its two sides", doc.SnapshotID, doc.BundleID, doc.Subject)
	}

	p := pairOf(t, doc)
	if p.From != "snapshot b9db37f8…" || p.To != "snapshot aef03f5d…" || !p.Computed || p.Unchanged == nil || *p.Unchanged ||
		p.FromBundleID == nil || *p.FromBundleID != fixtureBundleID || p.ToBundleID == nil || *p.ToBundleID != probedBundleID {
		t.Errorf("pair %+v; want the two snapshots' names and bundles, computed and changed", p)
	}
	changed := []nodeChange{{Node: "n1", Reasons: []string{"bootstrap"}}}
	if !reflect.DeepEqual(p.Nodes.Added, []string{"n1-loop-a", "n1-loop-b"}) || len(p.Nodes.Removed) != 0 ||
		!reflect.DeepEqual(p.Nodes.Changed, changed) {
		t.Errorf("nodes %+v; want n1-loop-a and n1-loop-b added, and n1 changed by its bootstrap alone", p.Nodes)
	}
	if len(p.Links.Added) != 2 || len(p.Links.Removed) != 0 {
		t.Fatalf("links %+v; want the hosts' two added", p.Links)
	}
	for i, host := range []string{"n1-loop-a", "n1-loop-b"} {
		if l := p.Links.Added[i]; l.A.Node != "n1" && l.B.Node != "n1" || l.A.Node != host && l.B.Node != host {
			t.Errorf("link %+v; want %s's to n1", l, host)
		}
	}
	if len(p.Artifacts.Changed) != 0 {
		t.Errorf("artifacts %+v; want none moved", p.Artifacts.Changed)
	}

	for _, entry := range []string{
		filepath.Join(paths.Snapshots, fixtureSnapshotID+".json"), filepath.Join(paths.Snapshots, probedSnapshotID+".json"),
		filepath.Join(paths.Bundles, fixtureBundleID), filepath.Join(paths.Bundles, probedBundleID),
	} {
		if _, err := os.Stat(entry); err != nil {
			t.Errorf("%s is not filed: %v", entry, err)
		}
	}
	if entries, err := os.ReadDir(paths.Root); err != nil || len(entries) != 2 {
		t.Errorf("the state root holds %v (%v); want snapshots/ and bundles/ alone", entries, err)
	}

	for _, want := range []string{
		"from: snapshot b9db37f8… (branch fylgja-fixture at 2026-09-08T12:00:00Z)\n",
		"snapshot_id " + fixtureSnapshotID + "  stored: " + filepath.Join(paths.Snapshots, fixtureSnapshotID+".json") + "\n",
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID) + "\n",
		"to: snapshot aef03f5d… (branch fylgja-fixture at 2026-09-08T12:00:00Z)\n",
		"bundle_id " + probedBundleID + "  stored: " + filepath.Join(paths.Bundles, probedBundleID) + "\n",
		"step snapshot b9db37f8… → snapshot aef03f5d… (c70589c3… → 5222063b…):\n" +
			"  nodes: +n1-loop-a; +n1-loop-b; ~n1 (bootstrap)\n" +
			"  links: +n1-loop-a:eth1 — n1:e1-10; +n1-loop-b:eth1 — n1:e1-11\n" +
			"  artifacts: unchanged\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("stdout:\n%s\nlacks %q", out, want)
		}
	}
	validateWithShow(t, currentContract, "020", doc)
}

// One snapshot against itself is unchanged, the two bundles one, whether named twice as one
// file, sent once, or as the file and then its id once filed; the compile runs once and its
// warnings are named once (FR-011).
func TestDiffOfASnapshotWithItselfIsUnchanged(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	for _, c := range []struct {
		name     string
		from, to string
		files    []api.File
	}{
		{"one file twice", "mixed.json", "mixed.json", []api.File{snapshotSent(t, "mixed.json", "mixed.json")}},
		{"the file, then its id", "mixed.json", "f3980cc735805c92c13be816c5dadd77c19f321c4c486808511b068f3a9659ff",
			[]api.File{snapshotSent(t, "mixed.json", "mixed.json")}},
	} {
		t.Run(c.name, func(t *testing.T) {
			var err error
			out := captureStdout(t, func() {
				err = runTwinDiff(t.Context(), testOptions(t, false), &diffFlags{from: c.from, to: c.to}, c.files)
			})
			code, doc := exitOf(t, err)
			if code != findings.ExitOK || doc.SnapshotFrom != doc.SnapshotTo || doc.BundleFrom != doc.BundleTo || doc.BundleFrom == "" {
				t.Fatalf("exit %d, document %+v; want 0, one snapshot and one bundle on both sides", code, doc)
			}
			if p := pairOf(t, doc); !p.Computed || p.Unchanged == nil || !*p.Unchanged {
				t.Errorf("pair %+v; want computed and unchanged", p)
			}
			if !strings.HasSuffix(out, ": unchanged; the two are one bundle\n") {
				t.Errorf("stdout:\n%s\nwant the step unchanged, one bundle", out)
			}
			seen := map[string]bool{}
			for _, f := range doc.Findings {
				key := f.Rule + " " + f.Object + " " + f.Message
				if seen[key] {
					t.Errorf("finding %+v named twice", f)
				}
				seen[key] = true
				if f.Step != findings.StepCompile || f.Severity == findings.Rejection {
					t.Errorf("finding %+v; want the compile's warnings alone", f)
				}
			}
			if len(doc.Findings) == 0 {
				t.Error("the mixed snapshot's compile warnings are not named")
			}
			validateWithShow(t, currentContract, "020", doc)
		})
	}
}

// A snapshot the compile refuses answers the compile's own finding at compile, naming the
// sides done so far: both snapshots, filed since their CTM validated, and the bundle of the
// side that compiled (FR-011). The refused side's bundle is filed nowhere.
func TestDiffOfASnapshotTheCompileRefusesIsTheCompilesFinding(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	refused := fixtureFile(t, func(d map[string]any) {
		delete(d, "snapshot_id")
		d["ctm"].(map[string]any)["devices"].([]any)[0].(map[string]any)["platform"].(map[string]any)["package"] = "nosuch"
	})[0]
	files := []api.File{snapshotSent(t, "three-node.json", "from.json"), refused}
	code, doc := exitOf(t, runTwinDiff(t.Context(), testOptions(t, true), &diffFlags{from: "from.json", to: refused.Path}, files))
	if code != findings.ExitRejected || len(doc.Findings) == 0 {
		t.Fatalf("exit %d, findings %+v; want 1 with the compile's refusal", code, doc.Findings)
	}
	for _, f := range doc.Findings {
		if f.Step != findings.StepCompile {
			t.Errorf("finding %+v; want it at compile", f)
		}
	}
	if !doc.Findings.Rejected() || !hasRule(doc.Findings, findings.RulePlatformUnsupported) {
		t.Errorf("findings %+v; want %s", doc.Findings, findings.RulePlatformUnsupported)
	}
	if doc.SnapshotFrom != fixtureSnapshotID || doc.SnapshotTo == "" || doc.BundleFrom != fixtureBundleID || doc.BundleTo != "" ||
		doc.Step != nil {
		t.Errorf("document %+v; want both snapshots, the from side's bundle and no step", doc)
	}
	if entries, err := os.ReadDir(paths.Bundles); err != nil || len(entries) != 1 || entries[0].Name() != fixtureBundleID {
		t.Errorf("bundles/ holds %v (%v); want the from side's alone", entries, err)
	}
	if _, err := os.Stat(filepath.Join(paths.Snapshots, doc.SnapshotTo+".json")); err != nil {
		t.Errorf("the refused side's snapshot is not filed: %v", err)
	}
	validateWithShow(t, currentContract, "020", doc)
}

// An id the store lacks is snapshot.unknown at resolve, as twin create --snapshot refuses it,
// naming the store; a to side's names the from side resolved before it (FR-011).
func TestDiffOfAnIdTheStoreLacksIsUnknown(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	const gone = "0000000000000000000000000000000000000000000000000000000000000000"
	for _, c := range []struct {
		name     string
		from, to string
		files    []api.File
		named    string
	}{
		{"from", gone, "to.json", []api.File{snapshotSent(t, "three-node.json", "to.json")}, ""},
		{"to", "from.json", gone, []api.File{snapshotSent(t, "three-node.json", "from.json")}, fixtureSnapshotID},
	} {
		t.Run(c.name, func(t *testing.T) {
			code, doc := exitOf(t, runTwinDiff(t.Context(), testOptions(t, true), &diffFlags{from: c.from, to: c.to}, c.files))
			if code != findings.ExitRejected || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 1 with snapshot.unknown alone", code, doc.Findings)
			}
			f := doc.Findings[0]
			if f.Rule != findings.RuleSnapshotUnknown || f.Step != findings.StepResolve || f.Object != gone ||
				!strings.Contains(f.Message, paths.Snapshots) {
				t.Errorf("finding %+v; want snapshot.unknown at resolve on the id, naming the store", f)
			}
			if doc.SnapshotFrom != c.named || doc.SnapshotTo != "" || doc.BundleFrom != "" || doc.BundleTo != "" {
				t.Errorf("document names %s → %s, bundles %s → %s; want the from side %q alone", doc.SnapshotFrom, doc.SnapshotTo,
					doc.BundleFrom, doc.BundleTo, c.named)
			}
			if _, err := os.Stat(paths.Bundles); !os.IsNotExist(err) {
				t.Errorf("bundles/ exists after a refused resolve (%v)", err)
			}
			validateWithShow(t, currentContract, "020", doc)
		})
	}
}

// The request's files are held to twin.diff's one shape before anything is parsed: a file for
// each flag that is a path, under it, once; anything else, and a flag not given, is
// operation.failed, exit 2, filing nothing.
func TestDiffHoldsTheRequestToItsShape(t *testing.T) {
	file := func(path string) api.File { return snapshotSent(t, "three-node.json", path) }
	for _, c := range []struct {
		name     string
		from, to string
		files    []api.File
		says     string
	}{
		{"no from", "", "to.json", []api.File{file("to.json")}, "--from is required"},
		{"no to", "from.json", "", []api.File{file("from.json")}, "--to is required"},
		{"a file missing", "from.json", "to.json", []api.File{file("from.json")}, "the request carries no file for --to"},
		{"a file of no flag", "from.json", "to.json", []api.File{file("from.json"), file("to.json"), file("other.json")},
			"the request carries a file under a path neither --from nor --to gives"},
		{"one file twice", "from.json", "from.json", []api.File{file("from.json"), file("from.json")},
			"the request carries a file under a path neither --from nor --to gives, or one twice"},
		{"a file beside an id", fixtureSnapshotID, "to.json", []api.File{file(fixtureSnapshotID), file("to.json")},
			"the request carries a file under a path neither --from nor --to gives"},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			code, doc := exitOf(t, runTwinDiff(t.Context(), testOptions(t, true), &diffFlags{from: c.from, to: c.to}, c.files))
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
				!strings.HasPrefix(doc.Findings[0].Message, c.says) {
				t.Errorf("exit %d, findings %+v; want 2, operation.failed saying %q", code, doc.Findings, c.says)
			}
			if entries, err := os.ReadDir(paths.Root); err != nil || len(entries) != 0 {
				t.Errorf("the state root holds %v (%v) after a refused request", entries, err)
			}
			validateWithShow(t, currentContract, "020", doc)
		})
	}
}
