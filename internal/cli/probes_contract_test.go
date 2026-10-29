//go:build contract

package cli

import (
	"bytes"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// intent read --out with a probe file writes a snapshot 2 carrying that one probe, which a
// create builds from with no read (SC-006), against a real Infrahub, never a fake (D-017):
// a fylgja-test-* branch seeded by this tree's seed, read through the harness's server with
// n1-loop's file, so the kind is never asked; the file written is a 2 whose list is n1-loop
// alone and whose envelope names the branch. Then twin create --snapshot <file> --dry-run
// compiles it, placing n1-loop's two hosts on n1's ethernet-1/10 and ethernet-1/11, and files
// its bundle, with neither Infrahub nor the workflow service asked. The read files the
// snapshot it sends, and dials nothing either. The branch is deleted
// when the test ends.
//
// The compile needs the seed's two probe-ready ports per device, which T033 writes: until
// then a seeded branch has no ethernet-1/10, and the compile is refused at
// probe.interface.unknown. So the test runs the read and skips before the compile, saying
// why; T033 removes the skip and runs it alone.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/cli -run '^TestIntentReadFilesASnapshot2$' -v
func TestIntentReadFilesASnapshot2(t *testing.T) {
	live(t)
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	paths := useStateRoot(t)
	dials := countDials(t)
	branch := fmt.Sprintf("%sprobes-%d-%d", testsupport.TestBranchPrefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(branch); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		if err := c.DeleteBranch(branch); err != nil {
			t.Errorf("could not delete branch %s: %v", branch, err)
		}
		if exists, err := c.BranchExists(branch); err != nil || exists {
			t.Errorf("after the test branch %s exists: %t (%v)", branch, exists, err)
		}
	})
	started := time.Now()
	if err := c.LoadSchema(branch, repoPath("schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s seeded in %.0fs", branch, time.Since(started).Seconds())

	n1 := declaredProbes(t, probesPath("n1-loop.json"))
	kind := &kindProbes{}
	useProbeKind(t, kind)
	out := filepath.Join(t.TempDir(), "snap.json")
	started = time.Now()
	code, doc, _ := executeClient(t, "intent", "read", "--branch", branch, "--scope", defaultScope,
		"--probes", probesPath("n1-loop.json"), "--out", out)
	if code != findings.ExitOK || len(doc.Findings) != 0 {
		t.Fatalf("intent read: exit %d, findings %+v; want 0 and none", code, doc.Findings)
	}
	validateM10Document(t, doc)
	b, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	s, err := snap.Unmarshal(b)
	if err != nil {
		t.Fatalf("the file written is no snapshot: %v", err)
	}
	if !strings.Contains(string(b), `"snapshot_version": "2"`) || !reflect.DeepEqual(s.Probes, n1) {
		t.Errorf("wrote a snapshot carrying %+v:\n%s\nwant a 2 carrying n1-loop alone, %+v", s.Probes, b, n1)
	}
	if doc.SnapshotID != s.ID || s.CTM.Envelope.Branch != branch {
		t.Errorf("the document names snapshot %s; the file is %s, of branch %s; want one id, of %s", doc.SnapshotID, s.ID,
			s.CTM.Envelope.Branch, branch)
	}
	if kind.reads.Load() != 0 {
		t.Errorf("the kind was read beside a probe file")
	}
	if stored, err := os.ReadFile(filepath.Join(paths.Snapshots, s.ID+".json")); err != nil || !bytes.Equal(stored, b) {
		t.Errorf("the server did not file the snapshot it sent as %s.json (%v)", s.ID, err)
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("the read dialled the workflow service %d times", n)
	}
	t.Logf("intent read --out: snapshot %s carrying %d probe(s) in %.1fs", s.ID, len(s.Probes), time.Since(started).Seconds())

	t.Skip("T033: this tree's seed writes no ethernet-1/10 or ethernet-1/11, so the compile of n1-loop is refused at " +
		"probe.interface.unknown until the seed's probe-ready ports land; T033 removes this skip and runs the test alone")

	dryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	clab.images = map[string]bool{"alpine:3.24.2": true}
	t.Setenv("INFRAHUB_ADDRESS", unreachable)
	started = time.Now()
	code, doc, _ = executeClient(t, "twin", "create", "--snapshot", out, "--dry-run")
	if code != findings.ExitOK || doc.SnapshotID != s.ID || doc.BundleID == "" || doc.DryRun == nil {
		t.Fatalf("twin create --snapshot --dry-run: exit %d, document %+v; want 0 naming the snapshot and a bundle", code, doc)
	}
	validateM10Document(t, doc)
	if _, err := os.Stat(filepath.Join(paths.Bundles, doc.BundleID)); err != nil {
		t.Errorf("the bundle %s is not filed: %v", doc.BundleID, err)
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("the workflow service was dialled %d times", n)
	}
	t.Logf("twin create --snapshot --dry-run: bundle %s in %.1fs", doc.BundleID, time.Since(started).Seconds())
}
