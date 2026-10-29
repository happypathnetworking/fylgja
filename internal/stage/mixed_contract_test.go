//go:build contract

package stage

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

//	set -a; . local/.env; set +a; go test -tags contract ./internal/stage -run TestMixedSeedReads -v

// A branch of two platforms reads and compiles through the product's own pipelines.
// Three devices, two platforms, each device's package found by its manufacturer and
// platform as the mixed seed writes them in the schema library's kinds (017), three
// artifacts under one name, and one bundle carrying both packages' answers: the same
// claims testdata/golden/mixed asserts in tier 1, here against a real Infrahub and a real
// rendering.
//
// The read is testdata/ctm/mixed.json below the envelope (SC-001), as T060 compared them
// by hand: Infrahub's template writes each device's description, the branch's marker, into
// its artifact's header, so the throwaway's marker is replaced by the fixture's in each
// artifact and its checksum recomputed by the fixture's own rule, the MD5 of the bytes, as
// CoreArtifact.checksum is. Of the envelope, what the read is must match too: the scope it
// was read under, the mapping it read by and the fidelity list's three fixed rows, since
// the mixed fixture's cables are all placed.
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
		platforms[d.Name] = d.Platform.Package
		a := d.Artifact
		if a == nil || a.Name != "device-config" || a.ContentType != "text/plain" {
			t.Fatalf("device %s was read with artifact %+v, want a Ready device-config", d.Name, a)
		}
	}
	if want := map[string]string{"e1": "arista_eos", "e2": "arista_eos", "s1": "nokia_srlinux"}; len(platforms) != 3 ||
		platforms["e1"] != want["e1"] || platforms["e2"] != want["e2"] || platforms["s1"] != want["s1"] {
		t.Fatalf("the branch read as %v, want %v", platforms, want)
	}

	// The template branches on the platform: an EOS device's configuration opens with
	// `!`, since `#` is not a comment on that platform and its node refuses it.
	if e1 := snapshot.Device("e1").Artifact.Content; !strings.HasPrefix(e1, "! e1:") {
		t.Errorf("e1's artifact is not EOS text; e1 rendered:\n%s", e1)
	}
	mustReadAsTheMixedCTM(t, snapshot, branch)

	files, id, list := Compile(snapshot, nil, reg, nil)
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

// mustReadAsTheMixedCTM fails unless got, read from the mixed seed on branch, is
// testdata/ctm/mixed.json but for the envelope's when and where, with branch's marker in
// each artifact replaced by the fixture's and each checksum recomputed from the bytes. got
// is not changed: the caller compiles it as read.
func mustReadAsTheMixedCTM(t *testing.T, got *ctm.CTM, branch string) {
	t.Helper()
	want, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	e := got.Envelope
	if e.Scope != "tag:"+testsupport.FixtureTag || e.Scope != want.Envelope.Scope {
		t.Errorf("scope %q, want %q", e.Scope, want.Envelope.Scope)
	}
	if e.Mapping != want.Envelope.Mapping {
		t.Errorf("mapping %+v, want %+v", e.Mapping, want.Envelope.Mapping)
	}
	if len(e.Fidelity) != 3 || !reflect.DeepEqual(e.Fidelity, want.Envelope.Fidelity) {
		t.Errorf("fidelity %+v, want the three fixed rows %+v", e.Fidelity, want.Envelope.Fidelity)
	}

	b, err := ctm.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	var read ctm.CTM
	if err := json.Unmarshal(b, &read); err != nil {
		t.Fatal(err)
	}
	read.Envelope = want.Envelope
	marker, fixture := testsupport.MarkerDescription(branch), testsupport.MarkerDescription(want.Envelope.Branch)
	for i := range read.Devices {
		a := read.Devices[i].Artifact
		if a == nil {
			continue
		}
		if !strings.Contains(a.Content, marker) {
			t.Errorf("device %s's artifact does not carry the branch's marker %s", read.Devices[i].Name, marker)
		}
		a.Content = strings.ReplaceAll(a.Content, marker, fixture)
		sum := md5.Sum([]byte(a.Content))
		a.Checksum = hex.EncodeToString(sum[:])
	}

	gotJSON, err := ctm.Marshal(&read)
	if err != nil {
		t.Fatal(err)
	}
	wantJSON, err := ctm.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	if string(gotJSON) != string(wantJSON) {
		t.Errorf("the read and the committed fixture disagree:\n--- read\n%s\n--- fixture\n%s", gotJSON, wantJSON)
	}
}
