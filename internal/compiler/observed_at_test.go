package compiler

import (
	"bytes"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
)

// When intent was read is a property of the read, not of the intent. Two reads of an
// unchanged branch produce CTMs differing only in `observed_at`, and they must compile
// to the same bytes and the same id — otherwise every re-read would look like a change
// and M4's reconcile would rebuild a twin that nothing had changed about
// (Constitution VI; D-023).
func TestObservedAtDoesNotReachTheBundle(t *testing.T) {
	earlier := compileFixture(t, "testdata/ctm/three-node.json")
	later := compileFixture(t, "testdata/ctm/observed-later.json")

	sameBundle(t, "observed_at", earlier, later)

	if a, b := bundle.ID(earlier), bundle.ID(later); a != b {
		t.Errorf("observed_at changed the bundle id: %s vs %s", a, b)
	}

	// Not just absent from the manifest: absent from every file. A bundle is deployed
	// and diffed as a directory, so a leak anywhere in it is a leak.
	for name, content := range later {
		if bytes.Contains(content, []byte("observed_at")) {
			t.Errorf("%s mentions observed_at:\n%s", name, content)
		}
		if bytes.Contains(content, []byte("2026-09-14T09:30:15.123456Z")) {
			t.Errorf("%s carries observed-later.json's read time:\n%s", name, content)
		}
	}
}

// The other half of the same guarantee: an `at` the operator did supply *is* part of
// the intent's address, so it must reach the manifest.
func TestSuppliedAtDoesReachTheBundle(t *testing.T) {
	c := loadFixture(t, "testdata/ctm/three-node.json")
	if c.Envelope.At == "" {
		t.Fatal("three-node.json is meant to be a pinned fixture")
	}
	files := compileFixture(t, "testdata/ctm/three-node.json")
	if !bytes.Contains(files[ManifestFile], []byte(c.Envelope.At)) {
		t.Errorf("the manifest does not record the supplied at %q:\n%s", c.Envelope.At, files[ManifestFile])
	}
}

// An unpinned CTM records no `at` at all, rather than an empty one: the manifest must
// not claim a pin that was never made.
func TestUnpinnedCTMWritesNoAt(t *testing.T) {
	files := compileFixture(t, "testdata/ctm/no-mgmt.json")
	if bytes.Contains(files[ManifestFile], []byte(`"at"`)) {
		t.Errorf("an unpinned CTM produced a manifest with an `at` key:\n%s", files[ManifestFile])
	}
}
