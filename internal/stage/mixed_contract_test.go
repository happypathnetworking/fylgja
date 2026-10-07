//go:build contract

package stage

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

//	set -a; . local/.env; set +a; go test -tags contract ./internal/stage -run TestMixedSeedReads -v

// A branch of two platforms reads and compiles through the product's own pipelines.
// Three devices, two platforms, three artifacts under one name, and one bundle
// carrying both packages' answers: the same claims testdata/golden/mixed asserts in tier
// 1, here against a real Infrahub and a real rendering.
//
// The rendering is the operator's: Infrahub's template branches on the device's
// platform,
// and until that change is pushed and imported an EOS
// device renders SR Linux text. That is not a defect in anything this test covers, so it
// skips and names the step rather than failing.
func TestMixedSeedReads(t *testing.T) {
	c, branch := throwaway(t, "mixed")
	if err := c.LoadSchema(branch, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedMixed(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s", branch)

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	snapshot, list := read(t, branch, reg)
	if list.Rejected() {
		t.Fatalf("reading %s was rejected: %v", branch, list)
	}
	if len(snapshot.Devices) != 3 {
		t.Fatalf("read %d devices, want three", len(snapshot.Devices))
	}

	platforms := map[string]string{}
	for _, d := range snapshot.Devices {
		platforms[d.Name] = d.Platform.NOS
		a := d.Artifact
		if a == nil || a.Name != "device-config" || a.ContentType != "text/plain" {
			t.Fatalf("device %s was read with artifact %+v, want a Ready device-config", d.Name, a)
		}
	}
	if want := map[string]string{"e1": "eos", "e2": "eos", "s1": "srlinux"}; len(platforms) != 3 ||
		platforms["e1"] != want["e1"] || platforms["e2"] != want["e2"] || platforms["s1"] != want["s1"] {
		t.Fatalf("the branch read as %v, want %v", platforms, want)
	}

	// The template branches on the platform: an EOS device's configuration opens with
	// `!`, since `#` is not a comment on that platform and its node refuses it.
	e1 := snapshot.Device("e1").Artifact.Content
	if !strings.HasPrefix(e1, "! e1:") {
		t.Skipf("e1's artifact is not EOS text, so the artifacts repository's template change "+
			"that renders EOS text for an eos device is not imported yet; e1 rendered:\n%s", e1)
	}
	// The rendering itself is evidence: testdata/ctm/mixed.json carries these shapes by
	// hand, and the log below lets the two be compared.
	for _, d := range snapshot.Devices {
		t.Logf("%s's rendered artifact (%d bytes, checksum %s):\n%s",
			d.Name, len(d.Artifact.Content), d.Artifact.Checksum, d.Artifact.Content)
	}

	files, id, list := Compile(snapshot, reg)
	if list.Rejected() {
		t.Fatalf("compiling %s was rejected: %v", branch, list)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	if m.BundleVersion != compiler.BundleVersion {
		t.Errorf("bundle_version %q, want %q", m.BundleVersion, compiler.BundleVersion)
	}

	// One bundle, both platforms' answers: each node deployed under its own package's
	// image and bootstrap route, and a forwarding entry per package rather than one claim
	// over nodes of two platforms (D-025).
	vias := map[string]string{}
	for _, n := range m.Nodes {
		vias[n.Name] = n.Bootstrap.Via
		if n.Artifact == nil || n.Artifact.Checksum == "" {
			t.Errorf("manifest node %s carries no artifact entry", n.Name)
		}
	}
	if want := map[string]string{"e1": psp.BootstrapViaPush, "e2": psp.BootstrapViaPush,
		"s1": psp.BootstrapViaStartupConfig}; len(vias) != 3 ||
		vias["e1"] != want["e1"] || vias["e2"] != want["e2"] || vias["s1"] != want["s1"] {
		t.Errorf("the nodes' bootstrap routes %v, want %v", vias, want)
	}
	if f := m.Fidelity.ProductionForwarding; len(f) != 2 || f["arista_eos"] == "" || f["nokia_srlinux"] == "" {
		t.Errorf("production_forwarding %v, want an entry for each package", f)
	}
	t.Logf("bundle_id %s", id)
}

// SeedMixed refuses the durable fixture branch, as every change flag does: it holds the
// three-node fixture, and every test and twin built from it relies on its bundle_id
// staying put. Nothing is written, so this needs no branch of its own.
func TestSeedMixedRefusesTheFixtureBranch(t *testing.T) {
	err := harness(t).SeedMixed(testsupport.FixtureBranch)
	if err == nil {
		t.Fatalf("SeedMixed accepted %s", testsupport.FixtureBranch)
	}
	if !strings.Contains(err.Error(), testsupport.FixtureBranch) {
		t.Errorf("refusal %q does not name the branch", err)
	}
}
