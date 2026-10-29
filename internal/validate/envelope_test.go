package validate

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// envelopeCase is one change to the three-node fixture's envelope: the finding it is
// refused with, or none when validation accepts it.
type envelopeCase struct {
	name            string
	change          func(*ctm.Envelope)
	object, message string
}

// row is a fidelity row of the reader's shape, for a case to break one field of.
func row(disposition, object, source, reason string) ctm.FidelityRow {
	return ctm.FidelityRow{Disposition: disposition, Object: object, Source: source, Reason: reason}
}

// envelopeCases are the envelope's forms, each as the contracts give it
// (contracts/ctm.schema.json, manifest.schema.json): the scope tag:<name>, the reader's
// name, and each fidelity row's disposition and fields. Rows are named by their place in
// the list as Normalize sorts it, by (disposition, object, source, reason), the order the
// manifest copies: the three-node fixture's rows are interface.enabled,
// interface.mgmt_only (approximated) and platform.version (omitted), so a row appended for
// cable c-9 is the third, index 2, whether it is omitted or of disposition bogus, and an
// approximated row with no object the first.
var envelopeCases = []envelopeCase{
	{"scope fylgja", func(e *ctm.Envelope) { e.Scope = "fylgja" }, "envelope.scope",
		`the scope intent was read under is "fylgja", which is not a scope: the accepted form is tag:<name>, the literal tag: and one word`},
	{"scope tag:", func(e *ctm.Envelope) { e.Scope = "tag:" }, "envelope.scope",
		`the scope intent was read under is "tag:", which is not a scope: the accepted form is tag:<name>, the literal tag: and one word`},
	{"scope tag:a b", func(e *ctm.Envelope) { e.Scope = "tag:a b" }, "envelope.scope",
		`the scope intent was read under is "tag:a b", which is not a scope: the accepted form is tag:<name>, the literal tag: and one word`},
	{"scope group:x", func(e *ctm.Envelope) { e.Scope = "group:x" }, "envelope.scope",
		`the scope intent was read under is "group:x", which is not a scope: the accepted form is tag:<name>, the literal tag: and one word`},
	{"reader Infrahub DCIM", func(e *ctm.Envelope) { e.Mapping.Reader = "Infrahub DCIM" }, "envelope.mapping.reader",
		`the reader that mapped intent is named "Infrahub DCIM", which is not a reader's name: ` +
			`lowercase letters, digits and hyphens, beginning with a letter or a digit`},
	{"reader -dcim", func(e *ctm.Envelope) { e.Mapping.Reader = "-dcim" }, "envelope.mapping.reader",
		`the reader that mapped intent is named "-dcim", which is not a reader's name: ` +
			`lowercase letters, digits and hyphens, beginning with a letter or a digit`},
	{"a row of disposition bogus", func(e *ctm.Envelope) {
		e.Fidelity = append(e.Fidelity, row("bogus", "c-9", "DcimCable", "other than two ends (3)"))
	}, "envelope.fidelity[2].disposition",
		`fidelity row 2 (c-9) has disposition "bogus": a row is approximated or omitted`},
	{"a row with no reason", func(e *ctm.Envelope) {
		e.Fidelity = append(e.Fidelity, row(ctm.FidelityOmitted, "c-9", "DcimCable", ""))
	}, "envelope.fidelity[2].reason", "fidelity row 2 (c-9) records no reason"},
	{"a row with no source", func(e *ctm.Envelope) {
		e.Fidelity = append(e.Fidelity, row(ctm.FidelityOmitted, "c-9", "", "other than two ends (3)"))
	}, "envelope.fidelity[2].source", "fidelity row 2 (c-9) records no source"},
	{"a row with no object", func(e *ctm.Envelope) {
		e.Fidelity = append(e.Fidelity, row(ctm.FidelityApproximated, "", "InterfacePhysical.role", "a reason"))
	}, "envelope.fidelity[0].object", "fidelity row 0 records no object"},

	// Accepted: what the contracts accept.
	{"scope tag:other", func(e *ctm.Envelope) { e.Scope = "tag:other" }, "", ""},
	{"scope tag:a-b_c.d", func(e *ctm.Envelope) { e.Scope = "tag:a-b_c.d" }, "", ""},
	{"reader netbox-dcim", func(e *ctm.Envelope) { e.Mapping.Reader = "netbox-dcim" }, "", ""},
	{"reader 0", func(e *ctm.Envelope) { e.Mapping.Reader = "0" }, "", ""},
	{"no fidelity row", func(e *ctm.Envelope) { e.Fidelity = nil }, "", ""},
	{"an omitted cable", func(e *ctm.Envelope) {
		e.Fidelity = append(e.Fidelity, row(ctm.FidelityOmitted, "c-9", "DcimCable", "other than two ends (3)"))
	}, "", ""},
}

// The envelope's scope, reader and fidelity rows are held to the forms their contracts
// give them, each refusal a rejection naming the field and the accepted form, as an
// envelope field left empty is: a CTM naming scope fylgja, reader Infrahub DCIM or a row
// of disposition bogus would otherwise compile to a manifest its contract refuses (017,
// T084; FR-019, FR-029). Nothing else is refused.
func TestEnvelopeFormsAreHeld(t *testing.T) {
	for _, c := range envelopeCases {
		t.Run(c.name, func(t *testing.T) {
			snapshot, reg := load(t, "three-node.json")
			c.change(&snapshot.Envelope)

			list := Validate(snapshot, nil, reg, nil)

			if c.object == "" {
				if len(list) != 0 {
					t.Errorf("findings %v, want none", list)
				}
				return
			}
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRequiredMissing, Object: c.object, Message: c.message}
			if len(list) != 1 || list[0] != want {
				t.Errorf("findings %+v\nwant exactly %+v", list, want)
			}
		})
	}
}

// A field left empty is named once, as missing, and not again for its form.
func TestAnEmptyEnvelopeFieldIsNamedOnce(t *testing.T) {
	for _, change := range []func(*ctm.Envelope){
		func(e *ctm.Envelope) { e.Scope = "" },
		func(e *ctm.Envelope) { e.Mapping.Reader = "" },
	} {
		snapshot, reg := load(t, "three-node.json")
		change(&snapshot.Envelope)
		if list := Validate(snapshot, nil, reg, nil); len(list) != 1 || list[0].Message == "" {
			t.Errorf("findings %v, want the one saying it is not recorded", list)
		}
	}
}

// What validation accepts compiles to a manifest contracts/manifest.schema.json accepts,
// and what it refuses would have compiled to one the contract refuses: the envelope's
// rules are the contract's, neither stricter nor looser (Constitution X). Every case
// compiles, the refused ones too, since the compiler copies the envelope unread.
func TestValidationAcceptsWhatTheManifestContractAccepts(t *testing.T) {
	schema := manifestSchema(t)
	for _, c := range envelopeCases {
		t.Run(c.name, func(t *testing.T) {
			snapshot, reg := load(t, "three-node.json")
			c.change(&snapshot.Envelope)
			accepted := !Validate(snapshot, nil, reg, nil).Rejected()

			files, list := compiler.Compile(snapshot, nil, reg, nil)
			if list.Rejected() {
				t.Fatalf("the compiler refused it: %v", list)
			}
			doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(files[compiler.ManifestFile]))
			if err != nil {
				t.Fatal(err)
			}
			err = schema.Validate(doc)
			if accepted && err != nil {
				t.Errorf("validation accepts it, and its manifest does not satisfy the contract:\n%v", err)
			}
			if !accepted && err == nil {
				t.Error("validation refuses it, and its manifest satisfies the contract")
			}
		})
	}
}

// An artifact's content type reaches the manifest unchanged, and the manifest contract
// holds it to text/*: validation refuses a type its package does not accept, in the read's
// words, so no CTM it accepts compiles to a manifest naming application/json (T084). The
// compiler's guard refuses it too, so the manifest the contract would refuse is the
// clean fixture's with the one field changed.
func TestValidationRefusesAnArtifactTypeTheManifestContractRefuses(t *testing.T) {
	snapshot, reg := load(t, "three-node.json")
	n1 := snapshot.Device("n1")
	n1.Artifact.ContentType = "application/json"
	list := Validate(snapshot, nil, reg, nil)
	want := "device n1: artifact device-config (checksum " + n1.Artifact.Checksum +
		") is application/json; the nokia_srlinux package accepts text/plain"
	if len(list) != 1 || list[0].Severity != findings.Rejection || list[0].Rule != findings.RuleArtifactContentTypeUnsupported ||
		list[0].Object != "n1" || list[0].Message != want {
		t.Errorf("findings %v\nwant one rejection %s on n1: %q", list, findings.RuleArtifactContentTypeUnsupported, want)
	}

	clean, reg := load(t, "three-node.json")
	files, compiled := compiler.Compile(clean, nil, reg, nil)
	if compiled.Rejected() {
		t.Fatalf("the compiler refused the clean fixture: %v", compiled)
	}
	var manifest map[string]any
	if err := json.Unmarshal(files[compiler.ManifestFile], &manifest); err != nil {
		t.Fatal(err)
	}
	for _, node := range manifest["nodes"].([]any) {
		if node := node.(map[string]any); node["name"] == "n1" {
			node["artifact"].(map[string]any)["content_type"] = "application/json"
		}
	}
	if err := manifestSchema(t).Validate(manifest); err == nil {
		t.Error("validation refuses it, and a manifest naming it satisfies the contract")
	}
}

// manifestSchema is the current manifest contract, under the module root's contracts/.
func manifestSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	path := filepath.Join("..", "..", "contracts", "manifest.schema.json")
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(path, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(path)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
