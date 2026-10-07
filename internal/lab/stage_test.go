package lab

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The bundle path the run sends lies outside the worker's state root and the worker's
// store is empty: the bundle is staged anyway, and filed in the worker's store. Staging
// again accepts the identical copy.
func TestStageBundleFromOutsideTheStateRoot(t *testing.T) {
	ctx := context.Background()
	a := testActivities(t, &fakeRunner{})
	in := wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}

	res, err := a.StageBundle(ctx, in)
	if err != nil {
		t.Fatal(err)
	}
	if res.TwinDir != a.Paths.Twin {
		t.Errorf("twin directory = %q, want %q", res.TwinDir, a.Paths.Twin)
	}
	if got, err := bundle.IDOfDir(a.Paths.TwinBundle); err != nil || got != goldenID {
		t.Errorf("staged copy hashes to %q (%v), want %s", got, err, goldenID)
	}
	if has, err := a.Store.Has(ctx, goldenID); err != nil || !has {
		t.Errorf("the worker's store does not hold the staged bundle (has %v, %v)", has, err)
	}

	t.Run("an identical copy already staged is accepted", func(t *testing.T) {
		before, err := os.Stat(a.Paths.TwinBundle)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := a.StageBundle(ctx, in); err != nil {
			t.Fatalf("restaging: %v", err)
		}
		after, err := os.Stat(a.Paths.TwinBundle)
		if err != nil {
			t.Fatal(err)
		}
		if !os.SameFile(before, after) || !before.ModTime().Equal(after.ModTime()) {
			t.Error("restaging replaced a copy that already hashed to the bundle id")
		}
	})
}

// A bundle path that hashes to another identity than the run was given is stage.failed
// naming both, and nothing is filed or staged.
func TestStageBundleRefusesAnotherIdentity(t *testing.T) {
	ctx := context.Background()
	a := testActivities(t, &fakeRunner{})
	claimed := strings.Repeat("0", 64)

	_, err := a.StageBundle(ctx, wire.StageInput{BundlePath: goldenBundle(), BundleID: claimed})
	f := stepFailure(t, err, findings.RuleStageFailed)
	if f.Step != findings.StepStage || !strings.Contains(f.Message, goldenID) || !strings.Contains(f.Message, claimed) {
		t.Errorf("finding = %+v, want step stage naming %s and %s", f, goldenID, claimed)
	}
	if has, _ := a.Store.Has(ctx, goldenID); has {
		t.Error("a refused bundle was filed in the store")
	}
	if _, err := os.Stat(a.Paths.Twin); !os.IsNotExist(err) {
		t.Errorf("a refused stage created %s", a.Paths.Twin)
	}
}

// A twin/bundle/ holding a different bundle was put there by something other than this
// run: stage.failed naming the directory, never overwritten.
func TestStageBundleRefusesAForeignTwinBundle(t *testing.T) {
	a := testActivities(t, &fakeRunner{})
	if err := os.MkdirAll(a.Paths.TwinBundle, 0o755); err != nil {
		t.Fatal(err)
	}
	foreign := filepath.Join(a.Paths.TwinBundle, "manifest.json")
	if err := os.WriteFile(foreign, []byte("{}\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := a.StageBundle(context.Background(), wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID})
	f := stepFailure(t, err, findings.RuleStageFailed)
	if f.Object != a.Paths.TwinBundle || !strings.Contains(f.Message, goldenID) {
		t.Errorf("finding = %+v, want the twin bundle directory named with the expected id", f)
	}
	if b, err := os.ReadFile(foreign); err != nil || string(b) != "{}\n" {
		t.Error("the foreign directory was overwritten")
	}
}

func TestUnstageTwin(t *testing.T) {
	ctx := context.Background()
	// keepInStore puts a file in the bundle store and returns how to check it is untouched.
	keepInStore := func(t *testing.T, a *Activities) func() {
		t.Helper()
		if err := os.MkdirAll(a.Paths.Bundles, 0o755); err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(a.Paths.Bundles, "kept.txt")
		if err := os.WriteFile(path, []byte("kept"), 0o644); err != nil {
			t.Fatal(err)
		}
		before := tree(t, a.Paths.Bundles)
		return func() {
			t.Helper()
			if after := tree(t, a.Paths.Bundles); len(after) != len(before) || !sameTree(before, after) {
				t.Errorf("the bundle store changed:\nbefore %v\nafter  %v", before, after)
			}
		}
	}

	t.Run("absent", func(t *testing.T) {
		a := testActivities(t, &fakeRunner{})
		res, err := a.UnstageTwin(ctx)
		if err != nil || res.Removed || res.Path != a.Paths.Twin {
			t.Errorf("result %+v, %v; want nothing removed, naming %s", res, err, a.Paths.Twin)
		}
	})
	t.Run("present", func(t *testing.T) {
		a := testActivities(t, &fakeRunner{})
		if _, err := a.StageBundle(ctx, wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(a.Paths.TwinJSON, []byte("{}\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		unchanged := keepInStore(t, a)

		res, err := a.UnstageTwin(ctx)
		if err != nil || !res.Removed || res.Path != a.Paths.Twin {
			t.Errorf("result %+v, %v; want %s removed", res, err, a.Paths.Twin)
		}
		if _, err := os.Stat(a.Paths.Twin); !os.IsNotExist(err) {
			t.Errorf("%s still exists", a.Paths.Twin)
		}
		unchanged()
		if has, err := a.Store.Has(ctx, goldenID); err != nil || !has {
			t.Errorf("the store lost bundle %s (has %v, %v)", goldenID, has, err)
		}
	})
	t.Run("unremovable", func(t *testing.T) {
		if os.Geteuid() == 0 {
			t.Skip("root removes entries from a read-only directory")
		}
		a := testActivities(t, &fakeRunner{})
		locked := a.Paths.TwinBundle
		if err := os.MkdirAll(locked, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(locked, "root-owned"), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(locked, 0o555); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(locked, 0o755) })
		unchanged := keepInStore(t, a)

		_, err := a.UnstageTwin(ctx)
		f := stepFailure(t, err, findings.RuleCleanupIncomplete)
		if f.Step != findings.StepUnstage || f.Object != a.Paths.Twin ||
			!strings.Contains(f.Message, "sudo rm -rf "+a.Paths.Twin) {
			t.Errorf("finding = %+v, want step unstage naming %s and the clearing command", f, a.Paths.Twin)
		}
		unchanged()
	})
}

func sameTree(a, b map[string]string) bool {
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}
