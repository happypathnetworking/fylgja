package ctm

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

func sample() *CTM {
	f := false
	return &CTM{
		Envelope: Envelope{
			Branch:     "fylgja-fixture",
			At:         "2026-09-08T12:00:00Z",
			ObservedAt: "2026-09-08T12:00:00.000000Z",
			SchemaHash: "fixture",
			Scope:      "tag:fylgja",
			Mapping:    Mapping{Reader: ReaderInfrahubDCIM, Model: ModelSchemaLibrary, Version: ModelVersion},
			// Out of order on purpose: Normalize sorts by (disposition, object).
			Fidelity: []FidelityRow{
				{Disposition: FidelityOmitted, Object: "platform.version", Source: "DcimPlatform",
					Reason: "the library's platform carries no version"},
				{Disposition: FidelityApproximated, Object: "interface.mgmt_only", Source: "InterfacePhysical.role",
					Reason: "the management port is the port whose role is management; the library has no management-only flag"},
				{Disposition: FidelityApproximated, Object: "interface.enabled", Source: "InterfacePhysical.status",
					Reason: "a port is enabled unless its status is disabled; the library's status is not an admin state"},
			},
		},
		Devices: []Device{
			{
				Name:     "n2",
				Platform: Platform{Package: "nokia_srlinux"},
				Interfaces: []Interface{
					{Name: "mgmt0", MgmtOnly: true, Enabled: &f},
					{Name: "ethernet-1/1", Link: "n1:ethernet-1/1|n2:ethernet-1/1"},
				},
			},
			{
				Name:     "n1",
				Platform: Platform{Package: "nokia_srlinux", Version: "24.7"},
				Interfaces: []Interface{
					{Name: "ethernet-1/1", Link: "n1:ethernet-1/1|n2:ethernet-1/1"},
				},
			},
		},
		Links: []Link{{
			ID: "n1:ethernet-1/1|n2:ethernet-1/1",
			Endpoints: []Endpoint{
				{Device: "n2", Interface: "ethernet-1/1"},
				{Device: "n1", Interface: "ethernet-1/1"},
			},
		}},
	}
}

func TestMarshalIsCanonical(t *testing.T) {
	b, err := Marshal(sample())
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !bytes.HasSuffix(b, []byte("\n")) {
		t.Error("canonical JSON must end with a newline")
	}
	if bytes.Contains(b, []byte("\r")) {
		t.Error("canonical JSON must use LF endings")
	}
	s := string(b)
	// Devices sorted by name: n1 must appear before n2.
	if strings.Index(s, `"name": "n1"`) > strings.Index(s, `"name": "n2"`) {
		t.Error("devices are not sorted by name")
	}
	// Interfaces sorted within a device.
	if strings.Index(s, `"ethernet-1/1"`) > strings.Index(s, `"mgmt0"`) {
		t.Error("interfaces are not sorted by name")
	}
	// The fidelity list sorted by (disposition, object).
	enabled := strings.Index(s, `"interface.enabled"`)
	mgmt := strings.Index(s, `"interface.mgmt_only"`)
	version := strings.Index(s, `"platform.version"`)
	if enabled < 0 || enabled > mgmt || mgmt > version {
		t.Error("the fidelity list is not sorted by disposition, then object")
	}
	// Endpoints sorted within a link.
	if strings.Index(s, `"device": "n1"`) > strings.Index(s, `"device": "n2"`) {
		t.Error("link endpoints are not sorted")
	}
}

func TestMarshalIsStable(t *testing.T) {
	a, err := Marshal(sample())
	if err != nil {
		t.Fatal(err)
	}
	b, err := Marshal(sample())
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(a, b) {
		t.Error("two marshals of equal input differ")
	}
}

func TestRoundTrip(t *testing.T) {
	first, err := Marshal(sample())
	if err != nil {
		t.Fatal(err)
	}
	back, err := Unmarshal(first)
	if err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	second, err := Marshal(back)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first, second) {
		t.Errorf("round trip changed the encoding:\n--- first\n%s\n--- second\n%s", first, second)
	}
}

// The envelope is the whole of what a CTM says about where it came from, so every
// field of it has to survive a round trip -- including `at`, which is recorded
// verbatim, and `observed_at`, which is the only record of when the read happened.
func TestEnvelopeRoundTrips(t *testing.T) {
	b, err := Marshal(sample())
	if err != nil {
		t.Fatal(err)
	}
	back, err := Unmarshal(b)
	if err != nil {
		t.Fatal(err)
	}
	want := sample()
	Normalize(want)
	if got := back.Envelope; !reflect.DeepEqual(got, want.Envelope) {
		t.Errorf("envelope round trip: got %+v, want %+v", got, want.Envelope)
	}
}

// An unpinned read records no `at` at all: an empty string in the file would be a
// claim that the operator pinned to nothing.
func TestUnpinnedEnvelopeOmitsAt(t *testing.T) {
	c := sample()
	c.Envelope.At = ""
	b, err := Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte(`"at"`)) {
		t.Errorf("an unpinned CTM must carry no `at` key:\n%s", b)
	}
}

func TestNormalizeFillsDefaults(t *testing.T) {
	c, err := Unmarshal([]byte(`{
      "ctm_version": "2",
      "envelope": {"branch": "b", "observed_at": "2026-09-08T12:00:00.000000Z",
        "schema_hash": "fixture", "scope": "tag:fylgja",
        "mapping": {"reader": "infrahub-dcim", "model": "opsmill/schema-library", "version": "26336e9"}},
      "devices": [{"name": "n1", "platform": {"package": "nokia_srlinux"},
        "interfaces": [{"name": "ethernet-1/1"}]}],
      "links": []}`))
	if err != nil {
		t.Fatal(err)
	}
	in := c.Devices[0].Interfaces[0]
	if !in.IsEnabled() {
		t.Error("enabled should default to true")
	}
	if c.Envelope.Fidelity == nil || len(c.Envelope.Fidelity) != 0 {
		t.Errorf("a CTM with no fidelity list should read as [], got %#v", c.Envelope.Fidelity)
	}
	b, err := Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(b, []byte(`"fidelity": []`)) {
		t.Errorf("an empty fidelity list must be written [], never null or omitted:\n%s", b)
	}
}

// Every object carries a provenance tag in memory, so code that reads one never has
// to treat "" as a fourth case (D-010). Every object is `intent` at M1.
func TestNormalizeDefaultsProvenanceToIntent(t *testing.T) {
	c := sample()
	Normalize(c)
	for _, d := range c.Devices {
		if d.Provenance != ProvenanceIntent {
			t.Errorf("device %s: provenance = %q, want %q", d.Name, d.Provenance, ProvenanceIntent)
		}
		for _, in := range d.Interfaces {
			if in.Provenance != ProvenanceIntent {
				t.Errorf("%s:%s: provenance = %q, want %q", d.Name, in.Name, in.Provenance, ProvenanceIntent)
			}
		}
	}
	for _, l := range c.Links {
		if l.Provenance != ProvenanceIntent {
			t.Errorf("link %s: provenance = %q, want %q", l.ID, l.Provenance, ProvenanceIntent)
		}
	}
}

// The default is filled in memory and omitted from the file: a CTM at M1 is nothing
// but `intent` objects, and writing the tag on every one of them would be noise.
// A non-default tag is written, which is the case that carries
// information.
func TestProvenanceIsWrittenOnlyWhenItIsNotTheDefault(t *testing.T) {
	c := sample()
	b, err := Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte(`"provenance"`)) {
		t.Errorf("an all-intent CTM must carry no provenance tag:\n%s", b)
	}

	c = sample()
	c.Devices[0].Provenance = ProvenanceSynthesized
	c.Links[0].Provenance = ProvenanceObserved
	b, err = Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"provenance": "synthesized"`, `"provenance": "observed"`} {
		if !bytes.Contains(b, []byte(want)) {
			t.Errorf("missing %s:\n%s", want, b)
		}
	}
	back, err := Unmarshal(b)
	if err != nil {
		t.Fatal(err)
	}
	if back.Device("n2").Provenance != ProvenanceSynthesized {
		t.Errorf("synthesized tag did not survive the round trip: %q", back.Device("n2").Provenance)
	}
}

// Normalizing an already-normal CTM must change nothing: the compiler normalizes its
// input, and a Normalize that moved things on a second pass would make compilation
// depend on how many times the CTM had been handled.
func TestNormalizeIsIdempotent(t *testing.T) {
	c := sample()
	Normalize(c)
	first, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	Normalize(c)
	second, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first, second) {
		t.Errorf("Normalize is not idempotent:\n--- first\n%s\n--- second\n%s", first, second)
	}
}

func TestUnmarshalRejectsUnknownField(t *testing.T) {
	_, err := Unmarshal([]byte(`{"ctm_version":"2","envelope":{"branch":"b","observed_at":"x",
	  "schema_hash":"h","scope":"tag:fylgja","mapping":{"reader":"r","model":"m","version":"v"},
	  "fidelity":[]},"devices":[],"links":[],"typo":true}`))
	if err == nil {
		t.Error("expected an unknown field to be rejected")
	}
}

// The old envelope key is exactly the kind of typo unknown-field rejection exists for:
// a CTM carrying the old top-level `provenance` block must fail loudly, not read as one
// with no envelope at all.
func TestUnmarshalRejectsTheOldProvenanceBlock(t *testing.T) {
	_, err := Unmarshal([]byte(`{"ctm_version":"2","provenance":{"source":"fixture","at":"x",
	  "contract_version":"0.2"},"devices":[],"links":[]}`))
	if err == nil {
		t.Error("expected the old top-level `provenance` block to be rejected")
	}
}

func TestUnmarshalRejectsUnsupportedVersion(t *testing.T) {
	_, err := Unmarshal([]byte(`{"ctm_version":"3","envelope":{"branch":"b","observed_at":"x",
	  "schema_hash":"h","scope":"tag:fylgja","mapping":{"reader":"r","model":"m","version":"v"},
	  "fidelity":[]},"devices":[],"links":[]}`))
	if err == nil {
		t.Error("expected an unsupported ctm_version to be rejected")
	}
}

// A CTM "1" is refused for its version, naming both, and not for the first of its
// fields "2" lacks (contract_version, iftype): nothing converts one (FR-028). The
// fixture is a "1" as the last build of that format wrote it, valid against the frozen
// copy of its contract, so the refusal is of a real "1" and not of a malformed file.
func TestVersion1IsRefused(t *testing.T) {
	path := filepath.Join("..", "..", "testdata", "ctm", "defects", "version-1.json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	frozen := compileSchemaAt(t, filepath.Join("testdata", "contracts", "017-dcim-reader", "ctm.schema.json"))
	if err := frozen.Validate(asAny(t, b)); err != nil {
		t.Fatalf("version-1.json must be a valid CTM 1 (the frozen contract):\n%v", err)
	}
	_, err = Unmarshal(b)
	if err == nil {
		t.Fatal("a CTM 1 must be refused")
	}
	if got, want := err.Error(), `unsupported ctm_version "1", expected "2"`; got != want {
		t.Errorf("refusal = %q, want %q", got, want)
	}
	// Typed, so twin compile files it as ctm.version.unsupported and every other decoding
	// failure as the operation's.
	var other *VersionError
	if !errors.As(err, &other) || other.Got != "1" {
		t.Errorf("refusal %v is not a VersionError naming version 1", err)
	}
	if _, err := Load(path); err == nil || !strings.Contains(err.Error(), `ctm_version "1"`) {
		t.Errorf("Load of a CTM 1 = %v, want the version refusal", err)
	}
}

func TestCanonicalLinkIDIsOrderIndependent(t *testing.T) {
	a := Endpoint{Device: "n1", Interface: "ethernet-1/1"}
	b := Endpoint{Device: "n2", Interface: "ethernet-1/2"}
	if CanonicalLinkID(a, b) != CanonicalLinkID(b, a) {
		t.Error("link id depends on endpoint order")
	}
}

func compileCTMSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	// The current contract, under the module root's contracts/: only the current copy
	// describes what this build writes. The "1" is frozen under testdata/contracts/.
	return compileSchemaAt(t, filepath.Join("..", "..", "contracts", "ctm.schema.json"))
}

func compileSchemaAt(t *testing.T, path string) *jsonschema.Schema {
	t.Helper()
	const name = "ctm.schema.json"
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("opening %s: %v", path, err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(name, doc); err != nil {
		t.Fatalf("adding %s: %v", path, err)
	}
	s, err := c.Compile(name)
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load this schema): %v", path, err)
	}
	return s
}

func asAny(t *testing.T, b []byte) any {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("re-reading emitted JSON: %v", err)
	}
	return v
}

// The fixtures are the compiler's inputs and the debugging seam between `intent read`
// and `twin compile`, so they must be valid documents of the format they claim.
func TestCTMFixturesSatisfyContract(t *testing.T) {
	schema := compileCTMSchema(t)
	root := filepath.Join("..", "..", "testdata", "ctm")
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			b, err := os.ReadFile(filepath.Join(root, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(asAny(t, b)); err != nil {
				t.Errorf("%s does not satisfy ctm.schema.json:\n%v", e.Name(), err)
			}
		})
	}
}

// What Marshal writes is the same format the fixtures are in, so it must satisfy the
// same schema -- including the shape an unpinned read produces, which no fixture on
// disk has to be.
func TestMarshalledCTMSatisfiesContract(t *testing.T) {
	schema := compileCTMSchema(t)
	for _, c := range []struct {
		label string
		ctm   *CTM
	}{
		{"pinned", sample()},
		{"unpinned", func() *CTM { c := sample(); c.Envelope.At = ""; return c }()},
		{"synthesized object", func() *CTM {
			c := sample()
			c.Devices[0].Provenance = ProvenanceSynthesized
			return c
		}()},
	} {
		t.Run(c.label, func(t *testing.T) {
			b, err := Marshal(c.ctm)
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(asAny(t, b)); err != nil {
				t.Errorf("marshalled CTM (%s) does not satisfy ctm.schema.json:\n%v", c.label, err)
			}
		})
	}
}

// deliberatelyInvalidFixtures are the defect files the CTM schema rejects on purpose.
//
// Intent arriving from Infrahub is not schema-checked on the way in, so Fylgja cannot
// rely on the serialization format to keep malformed shapes out -- it has to reject
// them itself, by rule, naming the object. These fixtures are how those rules stay
// under test: a link with one endpoint, which `minItems` forbids, a shape a branch can
// genuinely hold. version-1.json is a CTM "1", which this contract does not describe
// and Unmarshal refuses (TestVersion1IsRefused).
var deliberatelyInvalidFixtures = map[string]bool{
	"five.json":              true, // a link with one endpoint
	"link-one-endpoint.json": true, // the same, alone
	"version-1.json":         true, // a CTM "1", valid against the frozen copy alone
}

// The exemption is asserted rather than assumed: if one of these ever became schema
// valid, the rule it exercises would no longer be under test.
func TestMalformedFixturesAreDeliberatelyInvalid(t *testing.T) {
	schema := compileCTMSchema(t)
	for name := range deliberatelyInvalidFixtures {
		t.Run(name, func(t *testing.T) {
			b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "ctm", "defects", name))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(asAny(t, b)); err == nil {
				t.Errorf("%s is expected to be schema-invalid (it exercises link.endpoints.count or the "+
					"version refusal); if it has been corrected, that rule has lost its fixture", name)
			}
		})
	}
}

// Every other defect fixture is a well-formed document that is wrong about the
// network, which is the interesting case: valid JSON, valid shape, unbuildable intent.
func TestWellFormedDefectFixturesSatisfyContract(t *testing.T) {
	schema := compileCTMSchema(t)
	root := filepath.Join("..", "..", "testdata", "ctm", "defects")
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if deliberatelyInvalidFixtures[e.Name()] || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			b, err := os.ReadFile(filepath.Join(root, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(asAny(t, b)); err != nil {
				t.Errorf("%s does not satisfy ctm.schema.json:\n%v", e.Name(), err)
			}
		})
	}
}

// observed-later.json exists to prove observed_at never reaches the bundle,
// which only works if it differs from three-node.json in that one field and nothing
// else. Asserting it here means the fixture cannot drift out of that role silently.
func TestObservedLaterDiffersOnlyInObservedAt(t *testing.T) {
	root := filepath.Join("..", "..", "testdata", "ctm")
	base, err := Load(filepath.Join(root, "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	later, err := Load(filepath.Join(root, "observed-later.json"))
	if err != nil {
		t.Fatal(err)
	}
	if base.Envelope.ObservedAt == later.Envelope.ObservedAt {
		t.Error("observed-later.json must carry a different observed_at from three-node.json")
	}
	base.Envelope.ObservedAt = later.Envelope.ObservedAt
	a, err := Marshal(base)
	if err != nil {
		t.Fatal(err)
	}
	b, err := Marshal(later)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(a, b) {
		t.Errorf("observed-later.json differs from three-node.json in more than observed_at:\n--- three-node\n%s\n--- observed-later\n%s", a, b)
	}
}

// A device may carry a rendered configuration, and a device written before M5 may not.
// The codec accepts both: it is validation that refuses the second (artifact.missing),
// so the refusal can name the device rather than failing to parse the file.
func TestArtifactRoundTrips(t *testing.T) {
	want := Artifact{
		Name:        "device-config",
		ContentType: "text/plain",
		Checksum:    "18b98fda9e2b4f0c8d1a3e5b7c9d0f21",
		Content:     "# rendered for n1\nset / interface ethernet-1/1 description \"to n2\"\n",
	}
	c := sample()
	// sample()'s second device is n1; Marshal sorts, so hold the value rather than the
	// slot.
	artifact := want
	c.Devices[1].Artifact = &artifact

	first, err := Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	back, err := Unmarshal(first)
	if err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	second, err := Marshal(back)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first, second) {
		t.Errorf("round trip changed the encoding:\n--- first\n%s\n--- second\n%s", first, second)
	}

	var n1, n2 *Device
	for i := range back.Devices {
		switch back.Devices[i].Name {
		case "n1":
			n1 = &back.Devices[i]
		case "n2":
			n2 = &back.Devices[i]
		}
	}
	if n1 == nil || n1.Artifact == nil {
		t.Fatalf("n1's artifact did not survive the round trip: %+v", n1)
	}
	if *n1.Artifact != want {
		t.Errorf("artifact = %+v, want %+v", *n1.Artifact, want)
	}
	// The content is carried byte for byte: a newline dropped or a line reordered
	// would be a different configuration (Constitution IV).
	if n1.Artifact.Content != want.Content {
		t.Errorf("content changed:\n--- want\n%q\n--- got\n%q", want.Content, n1.Artifact.Content)
	}
	if n2 == nil || n2.Artifact != nil {
		t.Errorf("a device with no artifact must round-trip without one, got %+v", n2)
	}
	if bytes.Contains(first, []byte(`"artifact": null`)) {
		t.Error("a device with no artifact must omit the field, not write null")
	}
}

// The canonical encoding's field order is what bundle_id is taken over, so a field
// inserted anywhere but where the contract puts it would move every id silently.
//
// The assertion is that the encoded keys appear in the order contracts/ctm.schema.json
// declares them, skipping those a device omits, and that `artifact` sits immediately
// before `provenance`. Property order carries no meaning to a JSON
// Schema validator, so this is the only place it is checked.
func TestDeviceFieldOrderFollowsTheContract(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "contracts", "ctm.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	declared := propertyOrder(t, raw, "devices")
	if len(declared) == 0 {
		t.Fatal("the contract declares no device properties; the test is reading the wrong place")
	}

	c := sample()
	c.Devices[1].Artifact = &Artifact{Name: "device-config", ContentType: "text/plain",
		Checksum: "18b98fda9e2b4f0c8d1a3e5b7c9d0f21", Content: "# rendered\n"}
	c.Devices[1].Provenance = ProvenanceSynthesized
	b, err := Marshal(c)
	if err != nil {
		t.Fatal(err)
	}

	encoded := encodedDeviceKeys(t, b, "n1")
	position := map[string]int{}
	for i, name := range declared {
		position[name] = i
	}
	for _, key := range encoded {
		if _, ok := position[key]; !ok {
			t.Errorf("the encoding carries %q, which the contract does not declare", key)
		}
	}
	// `provenance` and `artifact` are the one pair the schema file lists in the other
	// order; the struct order is what the encoding follows, so check the pair directly
	// and the rest as a subsequence of the declared order.
	artifactAt, provenanceAt := indexOf(encoded, "artifact"), indexOf(encoded, "provenance")
	if artifactAt < 0 || provenanceAt < 0 {
		t.Fatalf("expected both artifact and provenance on the encoded device, got %v", encoded)
	}
	if artifactAt != provenanceAt-1 {
		t.Errorf("artifact must be encoded immediately before provenance, got %v", encoded)
	}
	rest := make([]string, 0, len(encoded))
	for _, key := range encoded {
		if key != "artifact" {
			rest = append(rest, key)
		}
	}
	for i := 1; i < len(rest); i++ {
		if position[rest[i-1]] > position[rest[i]] {
			t.Errorf("encoded order %v does not follow the contract's %v", encoded, declared)
			break
		}
	}
}

func indexOf(keys []string, want string) int {
	for i, k := range keys {
		if k == want {
			return i
		}
	}
	return -1
}

// propertyOrder returns the property names of the schema's array items, in the order the
// contract file writes them. encoding/json discards object key order, so the file is
// scanned for the keys of the one `properties` object under the named array.
func propertyOrder(t *testing.T, raw []byte, array string) []string {
	t.Helper()
	var doc struct {
		Properties map[string]json.RawMessage `json:"properties"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	var items struct {
		Items struct {
			Properties json.RawMessage `json:"properties"`
		} `json:"items"`
	}
	if err := json.Unmarshal(doc.Properties[array], &items); err != nil {
		t.Fatal(err)
	}
	return objectKeys(t, items.Items.Properties)
}

// encodedDeviceKeys returns the keys of the named device, in the order the canonical
// encoding wrote them.
func encodedDeviceKeys(t *testing.T, encoded []byte, device string) []string {
	t.Helper()
	var doc struct {
		Devices []json.RawMessage `json:"devices"`
	}
	if err := json.Unmarshal(encoded, &doc); err != nil {
		t.Fatal(err)
	}
	for _, d := range doc.Devices {
		var named struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(d, &named); err != nil {
			t.Fatal(err)
		}
		if named.Name == device {
			return objectKeys(t, d)
		}
	}
	t.Fatalf("device %q is not in the encoding", device)
	return nil
}

// objectKeys decodes one JSON object's keys in the order they appear.
func objectKeys(t *testing.T, raw []byte) []string {
	t.Helper()
	dec := json.NewDecoder(bytes.NewReader(raw))
	tok, err := dec.Token()
	if err != nil {
		t.Fatal(err)
	}
	if delim, ok := tok.(json.Delim); !ok || delim != '{' {
		t.Fatalf("expected an object, got %v", tok)
	}
	var keys []string
	for dec.More() {
		tok, err := dec.Token()
		if err != nil {
			t.Fatal(err)
		}
		key, ok := tok.(string)
		if !ok {
			t.Fatalf("expected a key, got %v", tok)
		}
		keys = append(keys, key)
		var discard json.RawMessage
		if err := dec.Decode(&discard); err != nil {
			t.Fatal(err)
		}
	}
	return keys
}
