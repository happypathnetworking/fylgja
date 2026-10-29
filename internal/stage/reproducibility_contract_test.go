//go:build contract

package stage

import (
	"bytes"
	"fmt"
	"maps"
	"math/rand"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// Contract tests run against a real Infrahub, never a fake (D-017).
//
//	set -a; . local/.env; set +a; go test -tags contract ./internal/stage -run Reproduc -v

// harness returns a write-capable client, skipping when no Infrahub is configured.
func harness(t *testing.T) *testsupport.Client {
	t.Helper()
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	return c
}

// throwaway makes a branch that is deleted when the test ends, in the shape of
// internal/intent's helper, which is unexported; testsupport is built into the fixture
// binary and does not import testing. The durable fylgja-fixture branch
// is never written.
func throwaway(t *testing.T, prefix string) (*testsupport.Client, string) {
	t.Helper()
	c := harness(t)
	branch := fmt.Sprintf("fylgja-test-%s-%d-%d", prefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(branch); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		if err := c.DeleteBranch(branch); err != nil {
			t.Logf("could not delete branch %s: %v", branch, err)
		}
	})
	return c, branch
}

// A pinned reference reproduces its bundle against a branch that changed (Constitution
// V, VI). Two reads pinned to T, one before and one after a change
// the compiler emits, compile to byte-identical bundles with one bundle_id; the unpinned
// read after the change differs in topology, not only in provenance. The reads and
// compiles are stage.Read and stage.Compile, the pipelines twin create runs. Each read
// stamps a fresh observed_at, so the equality also shows observed_at is outside the
// bundle (D-023).
//
// M5 extends it to configuration: between the first
// two pinned reads n1's description changes and its artifact is regenerated — new bytes,
// new checksum, a new storage object — and the read at T still fetches the artifact as it
// stood at T, so the bundle, its id and every checksum are unchanged. The test asserts
// what Infrahub 1.11.2 was seen to do: a listing pinned to `at` gives the storage id as
// of `at`, and the older object is still served. Should the live system refuse instead,
// re-verify that before changing the test.
//
// 017 extends it to the scope: the read selects its devices by the tag, and a pinned read
// by the tag as it stood at T. cs1, a device complete but for the tag, rendered before T,
// is tagged after it: the reads pinned to T never read it, and the unpinned read after
// does.
//
// 018 extends it to the snapshot (D-061): each read is taken with snapshot.Take, as the
// server takes it, and compiled from the snapshot's CTM. The three takes pinned to T have
// one snapshot_id beside their one bundle_id, though each was observed at another time, so
// the id leaves observed_at out (R-01); the unpinned take after the change has another.
func TestPinnedReadReproducesItsBundle(t *testing.T) {
	c, branch := throwaway(t, "repro")
	if err := c.LoadSchema(branch, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	cs1, err := c.AddDevice(branch, testsupport.Device{Name: "cs1", Manufacturer: "Nokia", Platform: "SR Linux",
		Ports: []string{"mgmt0"}, Management: "mgmt0"})
	if err != nil {
		t.Fatalf("adding cs1: %v", err)
	}
	if err := c.JoinArtifactGroup(branch, []string{cs1}); err != nil {
		t.Fatalf("adding cs1 to the group: %v", err)
	}
	if err := c.GenerateArtifacts(branch); err != nil {
		t.Fatalf("rendering cs1's artifact: %v", err)
	}
	// The local clock read after the seed returns sees the whole seed: Infrahub runs on
	// the same kernel clock. Six fractional digits, since intent.at.precision refuses
	// nine. The seed returns only once every artifact is Ready
	// (GenerateArtifacts waits), so T sees three current artifacts; the first read's
	// artifact count confirms it.
	at := time.Now().UTC().Format(ObservedAtFormat)
	t.Logf("branch %s, T = %s", branch, at)

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	read := func(at string) (map[string][]byte, string, *snapshot.Snapshot) {
		t.Helper()
		got, list, err := Read(t.Context(), branch, at, "tag:fylgja", reg, time.Now().UTC().Format(ObservedAtFormat))
		if err != nil {
			t.Fatalf("reading %s at %q: %v", branch, at, err)
		}
		if list.Rejected() {
			t.Fatalf("reading %s at %q was rejected: %v", branch, at, list)
		}
		taken := snapshot.Take(got, nil)
		files, id, list := Compile(taken.CTM, nil, reg, nil)
		if list.Rejected() {
			t.Fatalf("compiling %s at %q was rejected: %v", branch, at, list)
		}
		return files, id, taken
	}
	counts := func(what string, snapshot *ctm.CTM, want intent.Counts) {
		t.Helper()
		if got := intent.Summarize(snapshot); got != want {
			t.Fatalf("%s: read %d devices, %d interfaces, %d links, %d artifacts, want %d, %d, %d, %d",
				what, got.Devices, got.Interfaces, got.Links, got.Artifacts, want.Devices, want.Interfaces, want.Links, want.Artifacts)
		}
	}
	seeded := intent.Counts{Devices: 3, Interfaces: 9, Links: 3, Artifacts: 3}

	before, beforeID, beforeTake := read(at)
	counts("the read at T does not see the whole seed", beforeTake.CTM, seeded)
	sumsAtT := checksums(beforeTake.CTM)

	// The configuration change: n1's description, regenerated. Generation writes the new bytes
	// with no status transition to wait on, so the wait is for n1's
	// checksum to move on the branch.
	current := artifactsOf(t, c, branch, "device-config")
	if err := c.SetDeviceDescription(branch, "n1", testsupport.MarkerDescription(branch)+"-moved"); err != nil {
		t.Fatalf("changing n1's description after T: %v", err)
	}
	if err := c.GenerateArtifacts(branch); err != nil {
		t.Fatalf("regenerating after T: %v", err)
	}
	for deadline := time.Now().Add(90 * time.Second); artifactsOf(t, c, branch, "device-config")["n1"].Checksum == current["n1"].Checksum; {
		if time.Now().After(deadline) {
			t.Fatalf("n1's artifact checksum stayed %s for 90s after a description change was generated", current["n1"].Checksum)
		}
		time.Sleep(500 * time.Millisecond)
	}
	regenerated := artifactsOf(t, c, branch, "device-config")["n1"]
	if regenerated.StorageID == current["n1"].StorageID {
		t.Fatalf("n1's regeneration kept storage id %s; the proof needs a new object", regenerated.StorageID)
	}

	reconfigured, reconfiguredID, reconfiguredTake := read(at)
	counts("the read at T after the configuration change", reconfiguredTake.CTM, seeded)
	if got := checksums(reconfiguredTake.CTM); !maps.Equal(got, sumsAtT) {
		t.Errorf("the read at T after n1 was regenerated carries checksums %v, want T's %v", got, sumsAtT)
	}
	sameBundle(t, "the configuration change", before, reconfigured)
	if reconfiguredID != beforeID {
		t.Errorf("the reads pinned to T either side of the configuration change compile to %s and %s, want one bundle_id",
			beforeID, reconfiguredID)
	}
	if reconfiguredTake.ID != beforeTake.ID {
		t.Errorf("the takes pinned to T either side of the configuration change have snapshot_ids %s and %s, want one",
			beforeTake.ID, reconfiguredTake.ID)
	}

	if err := c.SeedFourthNode(branch, "n1"); err != nil {
		t.Fatalf("changing the branch after T: %v", err)
	}
	// SeedFourthNode's generate returns once every artifact is Ready, which can come before
	// n1's is rewritten for its new port, so the unpinned read below waits for n1's checksum
	// to move and n4's artifact to be listed, as the description change's wait above does. 240s
	// bounds it, as scripts/e2e.sh bounds the same wait on a loaded host.
	for deadline := time.Now().Add(240 * time.Second); ; {
		listed := artifactsOf(t, c, branch, "device-config")
		if listed["n1"].Checksum != regenerated.Checksum && listed["n4"].Checksum != "" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("240s after n4 was added, n1's artifact checksum is %s (still %s?) and n4's is %q",
				listed["n1"].Checksum, regenerated.Checksum, listed["n4"].Checksum)
		}
		time.Sleep(500 * time.Millisecond)
	}

	// The tag, after T: cs1 is in the scope from now on, and was not at T.
	if err := c.TagDevices(branch, testsupport.FixtureTag, "cs1"); err != nil {
		t.Fatalf("tagging cs1 after T: %v", err)
	}

	after, afterID, afterTake := read(at)
	counts("the read at T after the change", afterTake.CTM, seeded)
	if afterTake.CTM.Device("cs1") != nil {
		t.Error("the read pinned to T read cs1, which was tagged after T")
	}
	if got := checksums(afterTake.CTM); !maps.Equal(got, sumsAtT) {
		t.Errorf("the read at T after both changes carries checksums %v, want T's %v", got, sumsAtT)
	}
	sameBundle(t, "both changes", before, after)
	if afterID != beforeID {
		t.Errorf("the two reads pinned to T compile to %s and %s, want one bundle_id", beforeID, afterID)
	}
	if afterTake.ID != beforeTake.ID {
		t.Errorf("the two takes pinned to T have snapshot_ids %s and %s, want one", beforeTake.ID, afterTake.ID)
	}
	// Each take stamped its own observed_at, minutes apart, so the one id above is the id
	// leaving observed_at out, not two takes that happened to stamp one time.
	if afterTake.ObservedAt == beforeTake.ObservedAt {
		t.Errorf("the takes pinned to T either side of the change were both observed at %s; the proof needs two times",
			beforeTake.ObservedAt)
	}

	unpinned, unpinnedID, unpinnedTake := read("")
	counts("the unpinned read after the change", unpinnedTake.CTM, intent.Counts{Devices: 5, Interfaces: 13, Links: 4, Artifacts: 5})
	if unpinnedTake.CTM.Device("cs1") == nil {
		t.Error("the unpinned read after cs1 was tagged did not read it")
	}
	if unpinnedID == beforeID {
		t.Errorf("the unpinned read after the change compiles to the pinned bundle_id %s", beforeID)
	}
	if unpinnedTake.ID == beforeTake.ID {
		t.Errorf("the unpinned take after the change has the pinned snapshot_id %s", beforeTake.ID)
	}
	if bytes.Equal(unpinned[compiler.TopologyFile], before[compiler.TopologyFile]) {
		t.Errorf("the unpinned %s is the pinned one: the change did not reach the topology", compiler.TopologyFile)
	}
	// SeedFourthNode cables n1 to n4 and regenerates, so n1's artifact moved twice after
	// T; the unpinned read carries whatever Infrahub lists now, never T's.
	listed := artifactsOf(t, c, branch, "device-config")["n1"].Checksum
	if now := checksums(unpinnedTake.CTM)["n1"]; now == sumsAtT["n1"] || now != listed {
		t.Errorf("the unpinned read carries n1's checksum %s; want the current %s, not T's %s",
			now, listed, sumsAtT["n1"])
	}

	t.Logf("pinned at T before the change:      bundle %s, snapshot %s", beforeID, beforeTake.ID)
	t.Logf("pinned at T after the regeneration: bundle %s, snapshot %s (n1 %s, now %s)", reconfiguredID, reconfiguredTake.ID,
		sumsAtT["n1"], regenerated.Checksum)
	t.Logf("pinned at T after the change:       bundle %s, snapshot %s", afterID, afterTake.ID)
	t.Logf("unpinned after the change:          bundle %s, snapshot %s", unpinnedID, unpinnedTake.ID)
}

// checksums maps each device of a read to its artifact's checksum.
func checksums(c *ctm.CTM) map[string]string {
	out := map[string]string{}
	for _, d := range c.Devices {
		if d.Artifact != nil {
			out[d.Name] = d.Artifact.Checksum
		}
	}
	return out
}

// sameBundle asserts two pinned compiles hold the same files, byte for byte.
func sameBundle(t *testing.T, change string, before, after map[string][]byte) {
	t.Helper()
	if !slices.Equal(sortedNames(before), sortedNames(after)) {
		t.Errorf("the pinned bundles either side of %s hold different files: %v and %v",
			change, sortedNames(before), sortedNames(after))
	}
	for _, name := range sortedNames(before) {
		if !bytes.Equal(before[name], after[name]) {
			t.Errorf("%s differs between the reads pinned to T either side of %s", name, change)
			break
		}
	}
}

// sortedNames returns a bundle's file names in order.
func sortedNames(files map[string][]byte) []string {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	slices.Sort(names)
	return names
}
