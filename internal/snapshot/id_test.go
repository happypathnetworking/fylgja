package snapshot

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// fixturePath is a CTM fixture under the module root's testdata/ctm/.
func fixturePath(name string) string {
	return filepath.Join("..", "..", "testdata", "ctm", name+".json")
}

// fixture loads a CTM fixture through ctm.Load, normalised.
func fixture(t *testing.T, name string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(fixturePath(name))
	if err != nil {
		t.Fatalf("loading %s: %v", name, err)
	}
	return c
}

// raw decodes a CTM fixture with encoding/json alone: its lists in the file's order, its
// defaults unfilled, as a CTM built in memory may arrive at Take.
func raw(t *testing.T, name string) *ctm.CTM {
	t.Helper()
	data, err := os.ReadFile(fixturePath(name))
	if err != nil {
		t.Fatal(err)
	}
	var c ctm.CTM
	if err := json.Unmarshal(data, &c); err != nil {
		t.Fatalf("decoding %s: %v", name, err)
	}
	return &c
}

// idOf is the id of c's take, which Take sets and ID recomputes.
func idOf(t *testing.T, c *ctm.CTM) string {
	t.Helper()
	s := Take(c)
	id, err := ID(s)
	if err != nil {
		t.Fatal(err)
	}
	if s.ID != id {
		t.Fatalf("Take set snapshot_id %s, but ID computes %s", s.ID, id)
	}
	return id
}

// mirrors holds got's fields to want's: the same names, types, tags and order, but the
// field leftOut, which got must not have, and the fields in replaced, whose type in got is
// the one given.
func mirrors(t *testing.T, want, got reflect.Type, leftOut string, replaced map[string]reflect.Type) {
	t.Helper()
	var fields []reflect.StructField
	for i := range want.NumField() {
		if f := want.Field(i); f.Name != leftOut {
			fields = append(fields, f)
		}
	}
	if got.NumField() != len(fields) {
		t.Fatalf("%s has %d fields; %s has %d but %s: name each, or leave it out on purpose",
			got, got.NumField(), want, len(fields), leftOut)
	}
	for i, w := range fields {
		g := got.Field(i)
		wantType := w.Type
		if r, ok := replaced[w.Name]; ok {
			wantType = r
		}
		if g.Name != w.Name || g.Type != wantType || g.Tag != w.Tag {
			t.Errorf("%s field %d is %s %s `%s`; %s's is %s %s `%s`",
				got, i, g.Name, g.Type, g.Tag, want, w.Name, wantType, w.Tag)
		}
	}
}

// The hashed envelope is the CTM's envelope less observed_at, field for field: a field
// added to the envelope fails here until the hashed form names it or leaves it out on
// purpose (R-01).
func TestHashedEnvelopeMirrorsTheCTMEnvelope(t *testing.T) {
	mirrors(t, reflect.TypeFor[ctm.Envelope](), reflect.TypeFor[hashedEnvelope](), "ObservedAt", nil)
}

// The hashed CTM is the CTM with the hashed envelope in its envelope's place: a field
// added to the CTM fails here as one added to the envelope does.
func TestHashedCTMMirrorsTheCTM(t *testing.T) {
	mirrors(t, reflect.TypeFor[ctm.CTM](), reflect.TypeFor[hashedCTM](), "",
		map[string]reflect.Type{"Envelope": reflect.TypeFor[hashedEnvelope]()})
}

// Take is pure: the caller's CTM is neither normalised nor shared, so a caller can take a
// snapshot of a CTM and go on to use it as it was.
func TestTakeLeavesItsInputAlone(t *testing.T) {
	c := raw(t, "three-node.shuffled")
	before, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	s := Take(c)
	after, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("Take changed the CTM it was given")
	}

	// The take holds the CTM normalised: the shuffled fixture as the unshuffled one reads.
	want, err := ctm.Marshal(fixture(t, "three-node"))
	if err != nil {
		t.Fatal(err)
	}
	got, err := ctm.Marshal(s.CTM)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Error("the take's CTM is not the fixture normalised")
	}

	// And shares nothing with the caller's: a change to one reaches the other in no field.
	s.CTM.Envelope.Fidelity[0].Reason = "changed"
	s.CTM.Devices[0].Interfaces[0].Name = "changed"
	s.CTM.Devices[0].Artifact.Content = "changed"
	s.CTM.Links[0].Endpoints[0].Device = "changed"
	if again, _ := json.Marshal(c); !bytes.Equal(before, again) {
		t.Error("the take shares a list or a pointer with the CTM it was given")
	}

	if s.Version != Version || s.ObservedAt != c.Envelope.ObservedAt || s.Probes == nil || len(s.Probes) != 0 {
		t.Errorf("Take = version %q, observed_at %q, probes %v; want %q, the CTM's %q, []",
			s.Version, s.ObservedAt, s.Probes, Version, c.Envelope.ObservedAt)
	}
}

// observed_at is not hashed: two reads of one intent, six days apart, are one snapshot,
// while the stored documents keep each read's time (R-01; US2 scenario 1).
func TestObservedAtIsNotHashed(t *testing.T) {
	first, later := Take(fixture(t, "three-node")), Take(fixture(t, "observed-later"))
	if first.ID != later.ID {
		t.Fatalf("three-node %s and observed-later %s: observed_at moved the id", first.ID, later.ID)
	}
	a, err := Marshal(first)
	if err != nil {
		t.Fatal(err)
	}
	b, err := Marshal(later)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(a, b) {
		t.Error("the two takes' stored bytes are equal; each must keep its own observed_at")
	}
	t.Logf("three-node and observed-later: %s", first.ID)
}

// The order of a list is not hashed: each fixture and its shuffled copy, decoded with no
// normalising, are one snapshot (US2 scenario 2).
func TestOrderIsNotHashed(t *testing.T) {
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			id, shuffled := idOf(t, fixture(t, name)), idOf(t, raw(t, name+".shuffled"))
			if id != shuffled {
				t.Errorf("%s %s, shuffled %s: the order of a list moved the id", name, id, shuffled)
			}
			t.Logf("%s: %s", name, id)
		})
	}
}

// One byte of one artifact moves the id: the configuration a twin runs is intent (US2
// scenario 3).
func TestAnArtifactByteMovesTheID(t *testing.T) {
	base := idOf(t, fixture(t, "three-node"))
	c := fixture(t, "three-node")
	a := c.Devices[0].Artifact
	b := []byte(a.Content)
	b[len(b)/2] ^= 0x01
	a.Content = string(b)
	a.Checksum = ctm.ChecksumOf(a.Content)
	if got := idOf(t, c); got == base {
		t.Errorf("an artifact byte changed and the id stayed %s", base)
	}
}

// A fidelity row moves the id: what the reader approximated or omitted is part of what
// was read (US2 scenario 4).
func TestAFidelityRowMovesTheID(t *testing.T) {
	base := idOf(t, fixture(t, "three-node"))

	added := fixture(t, "three-node")
	added.Envelope.Fidelity = append(added.Envelope.Fidelity, ctm.FidelityRow{
		Disposition: ctm.FidelityOmitted, Object: "device.serial", Source: "DcimDevice.serial", Reason: "a test's row"})
	if got := idOf(t, added); got == base {
		t.Error("a fidelity row was added and the id did not move")
	}

	altered := fixture(t, "three-node")
	altered.Envelope.Fidelity[0].Reason += "."
	if got := idOf(t, altered); got == base {
		t.Error("a fidelity row's reason was altered and the id did not move")
	}
}

// Every envelope field but observed_at moves the id, each changed alone.
func TestEnvelopeFieldsMoveTheID(t *testing.T) {
	base := idOf(t, fixture(t, "three-node"))
	for _, tc := range []struct {
		field  string
		change func(e *ctm.Envelope)
	}{
		{"branch", func(e *ctm.Envelope) { e.Branch = "another" }},
		{"at", func(e *ctm.Envelope) { e.At = "2026-09-08T12:00:01Z" }},
		{"at left out", func(e *ctm.Envelope) { e.At = "" }},
		{"schema_hash", func(e *ctm.Envelope) { e.SchemaHash = "another" }},
		{"scope", func(e *ctm.Envelope) { e.Scope = "tag:another" }},
		{"mapping.version", func(e *ctm.Envelope) { e.Mapping.Version = "0000000" }},
	} {
		t.Run(tc.field, func(t *testing.T) {
			c := fixture(t, "three-node")
			tc.change(&c.Envelope)
			if got := idOf(t, c); got == base {
				t.Errorf("%s changed and the id stayed %s", tc.field, base)
			}
		})
	}
}

// The id the store names is the hash of the stored body less observed_at, computed here
// without Hashed or any of its types: the stored document read as ordered JSON, the
// recipe's four keys deleted, the rest written back in the file's order with two-space
// indent and a trailing newline, as jq --indent 2 'del(…)' writes it (R-01; FR-004).
func TestStoredIDIsTheBodysHash(t *testing.T) {
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			s := Take(fixture(t, name))
			stored, err := Marshal(s)
			if err != nil {
				t.Fatal(err)
			}
			doc := decodeOrdered(t, stored).(*ordered)
			doc.delete("snapshot_version")
			doc.delete("snapshot_id")
			doc.delete("observed_at")
			doc.get("ctm").(*ordered).get("envelope").(*ordered).delete("observed_at")
			body, err := json.MarshalIndent(doc, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			sum := sha256.Sum256(append(body, '\n'))
			if got := hex.EncodeToString(sum[:]); got != s.ID {
				t.Errorf("the stored body less observed_at hashes to %s; the snapshot's id is %s", got, s.ID)
			}
		})
	}
}

// ordered is a JSON object that keeps its keys in the order it read them, as jq does.
type ordered struct {
	keys []string
	vals map[string]any
}

func (o *ordered) get(k string) any { return o.vals[k] }

func (o *ordered) delete(k string) {
	if _, ok := o.vals[k]; !ok {
		panic("no key " + k)
	}
	delete(o.vals, k)
	for i, key := range o.keys {
		if key == k {
			o.keys = append(o.keys[:i], o.keys[i+1:]...)
			return
		}
	}
}

func (o *ordered) MarshalJSON() ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('{')
	for i, k := range o.keys {
		if i > 0 {
			b.WriteByte(',')
		}
		key, err := json.Marshal(k)
		if err != nil {
			return nil, err
		}
		val, err := json.Marshal(o.vals[k])
		if err != nil {
			return nil, err
		}
		b.Write(key)
		b.WriteByte(':')
		b.Write(val)
	}
	b.WriteByte('}')
	return b.Bytes(), nil
}

// decodeOrdered reads one JSON value with its objects' keys in order.
func decodeOrdered(t *testing.T, data []byte) any {
	t.Helper()
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := readValue(dec)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := dec.Token(); err != io.EOF {
		t.Fatalf("trailing data after the document: %v", err)
	}
	return v
}

func readValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	switch tok {
	case json.Delim('{'):
		o := &ordered{vals: map[string]any{}}
		for dec.More() {
			k, err := dec.Token()
			if err != nil {
				return nil, err
			}
			v, err := readValue(dec)
			if err != nil {
				return nil, err
			}
			o.keys = append(o.keys, k.(string))
			o.vals[k.(string)] = v
		}
		_, err := dec.Token()
		return o, err
	case json.Delim('['):
		list := []any{}
		for dec.More() {
			v, err := readValue(dec)
			if err != nil {
				return nil, err
			}
			list = append(list, v)
		}
		_, err := dec.Token()
		return list, err
	}
	return tok, nil
}
