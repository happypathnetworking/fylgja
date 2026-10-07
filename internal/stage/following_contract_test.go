//go:build contract

package stage

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

//	set -a; . local/.env; set +a; go test -tags contract ./internal/stage -run TestFollowingDetection -v

// A check detects a change to its branch by reading and compiling, nothing else (D-026).
// Two unpinned reads of an unchanged branch compile to one
// bundle_id, so a check leaves an unchanged twin alone; after the change tier 3 rebuilds
// on (SeedThirdLink), the same read and compile give a different one. The
// reads and compiles are stage.Read and stage.Compile, the pipelines Reconcile's
// ReadIntent and Compile activities run. Each read stamps a fresh observed_at, so the
// first equality also shows a check's own read time does not move the id (D-023).
func TestFollowingDetection(t *testing.T) {
	c, branch := throwaway(t, "follow")
	if err := c.LoadSchema(branch, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s", branch)

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	check := func(what string, want intent.Counts) string {
		t.Helper()
		snapshot, list, err := Read(t.Context(), branch, "", reg, time.Now().UTC().Format(ObservedAtFormat))
		if err != nil {
			t.Fatalf("%s: reading %s: %v", what, branch, err)
		}
		if list.Rejected() {
			t.Fatalf("%s: reading %s was rejected: %v", what, branch, list)
		}
		if got := intent.Summarize(snapshot); got != want {
			t.Fatalf("%s: read %d devices, %d interfaces, %d links, %d artifacts, want %d, %d, %d, %d",
				what, got.Devices, got.Interfaces, got.Links, got.Artifacts, want.Devices, want.Interfaces, want.Links, want.Artifacts)
		}
		_, id, list := Compile(snapshot, reg)
		if list.Rejected() {
			t.Fatalf("%s: compiling %s was rejected: %v", what, branch, list)
		}
		return id
	}
	seeded := intent.Counts{Devices: 3, Interfaces: 12, Links: 3, Artifacts: 3}

	first := check("the first check", seeded)
	second := check("the second check, branch unchanged", seeded)
	if second != first {
		t.Errorf("two checks of an unchanged branch compile to %s and %s, want one bundle_id", first, second)
	}

	if err := c.SeedThirdLink(branch); err != nil {
		t.Fatalf("changing the branch: %v", err)
	}
	changed := check("the check after the change", intent.Counts{Devices: 3, Interfaces: 14, Links: 4, Artifacts: 3})
	if changed == first {
		t.Errorf("the check after the change compiles to the unchanged bundle_id %s", first)
	}

	if err := c.SeedThirdLink(branch); err == nil {
		t.Errorf("a second SeedThirdLink on %s was accepted, want it refused", branch)
	}

	t.Logf("unchanged: %s", first)
	t.Logf("changed:   %s", changed)
}
