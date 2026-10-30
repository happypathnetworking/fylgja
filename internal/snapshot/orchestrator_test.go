package snapshot

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// escapesPath is the snapshot the orchestrator's snapshot module is held to beside the
// four wrapped fixtures (020's T015): its strings carry every character Go's encoder
// writes otherwise than Python's json.dumps does unaided, which no fixture carries.
func escapesPath() string {
	return filepath.Join("..", "..", "orchestrator", "tests", "data", "snapshot", "escapes.json")
}

// escapesID is escapesPath's id, which the orchestrator's test names too.
const escapesID = "38e0ced3c6f63a1dc2963f1841080beddfabe99e3731839d14043cf954c67538"

// escaped is every character the hashed bytes escape or write raw where a naive encoder
// might differ: HTML's three, U+2028 and U+2029 (escaped by Go), the control characters
// with a short form and two without, the quote, the backslash and the slash, DEL (raw in
// Go), and two characters beyond ASCII, one of them beyond the BMP.
const escaped = "a<b>c&d\u2028e\u2029f\x01g\bh\fi\nj\rk\tl\x1fm\"n\\o/p\x7fq\u00e9r\U0001F600s"

// escapesCTM is a CTM whose lists arrive out of order and whose fields cover each omitted
// and written default: a device not of intent, a platform version, a disabled port, an
// absent at, and the escaped string in an artifact, a fidelity row and a reason.
func escapesCTM() *ctm.CTM {
	off := false
	content := "hostname n1\n" + escaped + "\n"
	return &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:     "fylgja-fixture",
			ObservedAt: "2026-10-29T12:00:00.000000Z",
			SchemaHash: "fixture",
			Scope:      "tag:fylgja",
			Mapping:    ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion},
			Fidelity: []ctm.FidelityRow{
				{Disposition: ctm.FidelityOmitted, Object: "platform.version", Source: "DcimPlatform", Reason: escaped},
				{Disposition: ctm.FidelityApproximated, Object: "interface.enabled", Source: "InterfacePhysical.status",
					Reason: "b"},
				{Disposition: ctm.FidelityApproximated, Object: "interface.enabled", Source: "InterfacePhysical.status",
					Reason: "a"},
			},
		},
		Devices: []ctm.Device{
			{
				Name:     "n2",
				Platform: ctm.Platform{Package: "arista_ceos", Version: "4.32.0.2F"},
				Interfaces: []ctm.Interface{
					{Name: "mgmt0", MgmtOnly: true},
					{Name: "Ethernet1", Enabled: &off, Link: "n1:ethernet-1/1|n2:Ethernet1"},
				},
				Provenance: ctm.ProvenanceSynthesized,
			},
			{
				Name:     "n1",
				Platform: ctm.Platform{Package: "nokia_srlinux"},
				Interfaces: []ctm.Interface{
					{Name: "mgmt0", MgmtOnly: true},
					{Name: "ethernet-1/1", Link: "n1:ethernet-1/1|n2:Ethernet1"},
				},
				Artifact: &ctm.Artifact{Name: "device-config", ContentType: "text/plain",
					Checksum: ctm.ChecksumOf(content), Content: content},
			},
		},
		Links: []ctm.Link{{
			ID: "n1:ethernet-1/1|n2:Ethernet1",
			Endpoints: []ctm.Endpoint{
				{Device: "n2", Interface: "Ethernet1"},
				{Device: "n1", Interface: "ethernet-1/1"},
			},
		}},
	}
}

// orchestrator/tests/data/snapshot/escapes.json is a fresh take of escapesCTM, byte for
// byte, or is rewritten under -update: the Go-written file the orchestrator's encoder
// reproduces (020's T015). Its id moves only with the hashed bytes' encoding, as the
// wrapped fixtures' do.
func TestTheOrchestratorsEscapesFixture(t *testing.T) {
	want, err := Marshal(Take(escapesCTM(), nil))
	if err != nil {
		t.Fatal(err)
	}
	path := escapesPath()
	if *update {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, want, 0o644); err != nil {
			t.Fatal(err)
		}
		t.Logf("%s rewritten", path)
		return
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v (run: go test ./internal/snapshot -run TestTheOrchestratorsEscapesFixture -update)", path, err)
	}
	if !bytes.Equal(got, want) {
		t.Errorf("%s is not a fresh take of escapesCTM (run with -update and review the diff)", path)
	}
	s, err := Load(path)
	if err != nil {
		t.Fatalf("loading %s: %v", path, err)
	}
	if s.ID != escapesID {
		t.Errorf("%s's snapshot_id is %s, want %s", path, s.ID, escapesID)
	}
	for _, raw := range []string{`\u003c`, `\u003e`, `\u0026`, `\u2028`, `\u2029`, `\u0001`, `\b`, `\f`, `\u001f`, "\x7f"} {
		if !bytes.Contains(got, []byte(raw)) {
			t.Errorf("%s does not carry %q, which the escaped string should have written", path, raw)
		}
	}
}
