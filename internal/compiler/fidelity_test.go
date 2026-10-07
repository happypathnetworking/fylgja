package compiler

import (
	"encoding/json"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// twoPlatformRegistry builds an override registry holding the shipped SR Linux package
// and a second platform derived from it, with the forwarding answer the caller wants.
//
// Deriving rather than hand-writing keeps the second package valid against
// psp.schema.json without a second fixture to maintain: every facet the schema requires
// is already there, and only the three fields that make it a different platform change.
func twoPlatformRegistry(t *testing.T, secondForwarding string) *psp.Registry {
	t.Helper()
	src, err := os.ReadFile(filepath.Join("..", "..", "psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}

	second := string(src)
	for from, to := range map[string]string{
		"id: nokia_srlinux":               "id: acme_os",
		"nos: srlinux":                    "nos: acme_os",
		"production_forwarding: hardware": "production_forwarding: " + secondForwarding,
	} {
		if !strings.Contains(second, from) {
			t.Fatalf("the shipped package no longer contains %q; update this helper", from)
		}
		second = strings.Replace(second, from, to, 1)
	}
	if err := os.WriteFile(filepath.Join(dir, "acme_os.yaml"), []byte(second), 0o644); err != nil {
		t.Fatal(err)
	}

	reg, err := psp.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reg.Lookup("acme_os"); !ok {
		t.Fatalf("the derived package did not load; platforms: %v", reg.Platforms())
	}
	return reg
}

// testArtifact gives a hand-built device the configuration every device carries from M5
// on, so a CTM built here is judged on what it is about — forwarding — and not refused
// as artifact.missing first.
func testArtifact(device string) *ctm.Artifact {
	content := "# " + device + "\nset / system name host-name " + device + "\n"
	return &ctm.Artifact{
		Name:        "device-config",
		ContentType: "text/plain",
		Checksum:    ctm.ChecksumOf(content),
		Content:     content,
	}
}

// twoPlatformCTM is two devices, one per platform, with no links: the smallest input
// that makes the twin heterogeneous.
func twoPlatformCTM() *ctm.CTM {
	return &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:          "fylgja-fixture",
			ObservedAt:      "2026-09-08T12:00:00.000000Z",
			SchemaHash:      "fixture",
			ContractVersion: ctm.ContractVersion,
		},
		Devices: []ctm.Device{
			{
				Name:     "n1",
				Platform: ctm.Platform{Vendor: "nokia", NOS: "srlinux"},
				Interfaces: []ctm.Interface{
					{Name: "ethernet-1/1", Iftype: ctm.IftypePhysical},
				},
				Artifact: testArtifact("n1"),
			},
			{
				Name:     "n2",
				Platform: ctm.Platform{Vendor: "acme", NOS: "acme_os"},
				Interfaces: []ctm.Interface{
					{Name: "ethernet-1/1", Iftype: ctm.IftypePhysical},
				},
				Artifact: testArtifact("n2"),
			},
		},
	}
}

// A bundle of two platforms that disagree about production forwarding compiles, and the
// manifest asserts each platform's own value. Until bundle "3" the field was a single
// value for the whole bundle, so a second answer had nowhere to go and the compiler
// refused such a twin outright (fidelity.forwarding.mixed, retired with the bump);
// picking either would have asserted it over the other's nodes, the one claim a fidelity
// manifest must never make (D-025, Constitution X).
//
// Unreachable with the embedded packages, since SR Linux is the only shipped platform
// until M7's second one; reachable through --psp-dir either way.
func TestTwoForwardingAnswersAreBothRecorded(t *testing.T) {
	reg := twoPlatformRegistry(t, "software")
	files, list := Compile(twoPlatformCTM(), reg)

	if list.Rejected() {
		t.Fatalf("a twin with two forwarding answers was refused: %v", list)
	}
	if files == nil {
		t.Fatal("no files returned")
	}
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"acme_os": "software", "nokia_srlinux": "hardware"}
	if !maps.Equal(m.Fidelity.ProductionForwarding, want) {
		t.Errorf("production_forwarding = %v, want %v", m.Fidelity.ProductionForwarding, want)
	}
}

// Two platforms that agree get one entry apiece all the same: the field is keyed by
// platform, so agreement is two entries with the same value, never one merged claim.
func TestMatchingForwardingCompilesAcrossPlatforms(t *testing.T) {
	reg := twoPlatformRegistry(t, "hardware")
	files, list := Compile(twoPlatformCTM(), reg)
	if list.Rejected() {
		t.Fatalf("matching forwarding was rejected: %v", list)
	}

	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"acme_os": "hardware", "nokia_srlinux": "hardware"}
	if !maps.Equal(m.Fidelity.ProductionForwarding, want) {
		t.Errorf("production_forwarding = %v, want %v", m.Fidelity.ProductionForwarding, want)
	}
	// Approximations are the half that *is* per platform: each is prefixed with the
	// package that asserts it, so both platforms are represented.
	var platforms int
	for _, prefix := range []string{"nokia_srlinux: ", "acme_os: "} {
		for _, a := range m.Fidelity.Approximations {
			if strings.HasPrefix(a, prefix) {
				platforms++
				break
			}
		}
	}
	if platforms != 2 {
		t.Errorf("approximations name %d of 2 platforms: %v", platforms, m.Fidelity.Approximations)
	}
}
