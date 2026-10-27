package snapshot

import (
	"bytes"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// document is the stored form of three-node's take, decoded to a map for a case to
// change: the keys' order is lost, which Unmarshal does not read.
func document(t *testing.T) map[string]any {
	t.Helper()
	b, err := Marshal(Take(fixture(t, "three-node")))
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func encode(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// innerCTM is the document's ctm, for a case to change.
func innerCTM(m map[string]any) map[string]any { return m["ctm"].(map[string]any) }

// The refusals, one case each, in R-03's order: the error's type, the field it names and
// its message's key words, so the server can file each under its rule and its object.
func TestUnmarshalRefusals(t *testing.T) {
	const wrongID = "1111111111111111111111111111111111111111111111111111111111111111"
	bare, err := os.ReadFile(fixturePath("three-node"))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		data  func(t *testing.T) []byte
		check func(t *testing.T, err error)
	}{
		{"snapshot_version 2", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_version"] = "2"
			return encode(t, m)
		}, wantVersion("2", `the snapshot declares snapshot_version "2"; this build reads "1", and nothing converts one`)},
		{"snapshot_version absent", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "snapshot_version")
			return encode(t, m)
		}, wantVersion("", `the snapshot declares no snapshot_version; this build reads "1", and nothing converts one`)},
		{"snapshot_version a number", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_version"] = 1
			return encode(t, m)
		}, wantVersion("1", `the snapshot declares snapshot_version 1; this build reads "1", and nothing converts one`)},
		{"a bare CTM", func(*testing.T) []byte { return bare },
			wantVersion("", "declares no snapshot_version")},
		{"an unknown outer key", func(t *testing.T) []byte {
			m := document(t)
			m["comment"] = "a hand user's note"
			return encode(t, m)
		}, wantInvalid("comment", `the key "comment"`, "snapshot_version, snapshot_id, observed_at, ctm and probes")},
		{"a key spelled another way", func(t *testing.T) []byte {
			m := document(t)
			m["Probes"] = m["probes"]
			delete(m, "probes")
			return encode(t, m)
		}, wantInvalid("Probes", `the key "Probes"`)},
		{"ctm absent", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "ctm")
			return encode(t, m)
		}, wantInvalid("ctm", "ctm is not recorded", "CTM 2")},
		{"ctm null", func(t *testing.T) []byte {
			m := document(t)
			m["ctm"] = nil
			return encode(t, m)
		}, wantInvalid("ctm", "ctm is not recorded")},
		{"ctm not an object", func(t *testing.T) []byte {
			m := document(t)
			m["ctm"] = []any{}
			return encode(t, m)
		}, wantInvalid("ctm", "ctm is not an object")},
		{"probes absent", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "probes")
			return encode(t, m)
		}, wantInvalid("probes", "probes is not recorded", "required and empty")},
		{"probes null", func(t *testing.T) []byte {
			m := document(t)
			m["probes"] = nil
			return encode(t, m)
		}, wantInvalid("probes", "probes is not recorded")},
		{"probes not a list", func(t *testing.T) []byte {
			m := document(t)
			m["probes"] = map[string]any{}
			return encode(t, m)
		}, wantInvalid("probes", "probes is not a list")},
		{"probes holding one entry", func(t *testing.T) []byte {
			m := document(t)
			m["probes"] = []any{map[string]any{}}
			return encode(t, m)
		}, wantInvalid("probes", "probes holds 1 entry; in snapshot 1 the list is required and empty, since 016 defines its element")},
		{"snapshot_id not an id", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_id"] = "ABC"
			return encode(t, m)
		}, wantInvalid("snapshot_id", `snapshot_id "ABC" is not 64 lowercase hex characters`, "leave it out")},
		{"snapshot_id uppercase", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_id"] = strings.ToUpper(m["snapshot_id"].(string))
			return encode(t, m)
		}, wantInvalid("snapshot_id", "not 64 lowercase hex characters")},
		{"snapshot_id another body's", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_id"] = wrongID
			return encode(t, m)
		}, func(t *testing.T, err error) {
			var mismatch *IDMismatchError
			if !errors.As(err, &mismatch) {
				t.Fatalf("err = %T %v, want *IDMismatchError", err, err)
			}
			want := Take(fixture(t, "three-node")).ID
			if mismatch.Declared != wrongID || mismatch.Computed != want {
				t.Errorf("IDMismatchError{%s, %s}, want {%s, %s}", mismatch.Declared, mismatch.Computed, wrongID, want)
			}
			if got := err.Error(); got != "declares snapshot_id "+wrongID+", but its body hashes to "+want+"; leave snapshot_id out to have it computed" {
				t.Errorf("message = %q", got)
			}
		}},
		{"observed_at malformed", func(t *testing.T) []byte {
			m := document(t)
			m["observed_at"] = "2026-09-08T12:00:00Z"
			return encode(t, m)
		}, wantInvalid("observed_at", `observed_at "2026-09-08T12:00:00Z" is not a UTC time with six fractional digits`)},
		{"observed_at not the inner CTM's", func(t *testing.T) []byte {
			m := document(t)
			m["observed_at"] = "2026-09-14T09:30:15.123456Z"
			return encode(t, m)
		}, wantInvalid("observed_at", "observed_at 2026-09-14T09:30:15.123456Z is not the inner CTM's", "2026-09-08T12:00:00.000000Z", "one read")},
		{"a wrapped CTM 1", func(t *testing.T) []byte {
			m := document(t)
			innerCTM(m)["ctm_version"] = "1"
			return encode(t, m)
		}, func(t *testing.T, err error) {
			var version *ctm.VersionError
			if !errors.As(err, &version) || version.Got != "1" {
				t.Fatalf("err = %T %v, want *ctm.VersionError{Got: 1}", err, err)
			}
		}},
		{"a wrapped CTM missing its fidelity list", func(t *testing.T) []byte {
			m := document(t)
			delete(innerCTM(m)["envelope"].(map[string]any), "fidelity")
			return encode(t, m)
		}, wantMissing("ctm.envelope.fidelity")},
		{"a wrapped CTM missing its links", func(t *testing.T) []byte {
			m := document(t)
			delete(innerCTM(m), "links")
			return encode(t, m)
		}, wantMissing("ctm.links")},
		{"a wrapped CTM missing a device's ports", func(t *testing.T) []byte {
			m := document(t)
			delete(innerCTM(m)["devices"].([]any)[1].(map[string]any), "interfaces")
			return encode(t, m)
		}, wantMissing("ctm.devices[1].interfaces")},
		// No outer observed_at, so step 2 has none to hold to the inner CTM's: what
		// refuses each is the inner CTM's own, after step 3.
		{"a wrapped CTM recording no observed_at", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "observed_at")
			delete(innerCTM(m)["envelope"].(map[string]any), "observed_at")
			return encode(t, m)
		}, wantMissing("ctm.envelope.observed_at")},
		{"a wrapped CTM recording an empty observed_at", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "observed_at")
			innerCTM(m)["envelope"].(map[string]any)["observed_at"] = ""
			return encode(t, m)
		}, wantMissing("ctm.envelope.observed_at")},
		{"a wrapped CTM's observed_at not of its form", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "observed_at")
			innerCTM(m)["envelope"].(map[string]any)["observed_at"] = "2026-10-27T18:55:42Z"
			return encode(t, m)
		}, wantInvalid("ctm.envelope.observed_at",
			`ctm.envelope.observed_at "2026-10-27T18:55:42Z" is not a UTC time with six fractional digits`, ObservedAtLayout)},
		{"a document not an object", func(*testing.T) []byte { return []byte(`[]`) },
			wantInvalid("", "not a JSON object")},
		{"a document null", func(*testing.T) []byte { return []byte(`null`) },
			wantInvalid("", "not a JSON object")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, err := Unmarshal(tc.data(t))
			if err == nil {
				t.Fatalf("Unmarshal accepted it: %+v", s)
			}
			if s != nil {
				t.Errorf("Unmarshal returned a snapshot beside its refusal")
			}
			tc.check(t, err)
		})
	}
}

func wantVersion(got, message string) func(*testing.T, error) {
	return func(t *testing.T, err error) {
		t.Helper()
		var version *VersionError
		if !errors.As(err, &version) {
			t.Fatalf("err = %T %v, want *VersionError", err, err)
		}
		if version.Got != got {
			t.Errorf("VersionError.Got = %q, want %q", version.Got, got)
		}
		if !strings.Contains(err.Error(), message) {
			t.Errorf("message %q does not hold %q", err, message)
		}
	}
}

func wantInvalid(field string, words ...string) func(*testing.T, error) {
	return func(t *testing.T, err error) {
		t.Helper()
		var invalid *InvalidError
		if !errors.As(err, &invalid) {
			t.Fatalf("err = %T %v, want *InvalidError", err, err)
		}
		if invalid.Field != field {
			t.Errorf("InvalidError.Field = %q, want %q", invalid.Field, field)
		}
		for _, w := range words {
			if !strings.Contains(invalid.Message, w) {
				t.Errorf("message %q does not hold %q", invalid.Message, w)
			}
		}
	}
}

func wantMissing(field string) func(*testing.T, error) {
	return func(t *testing.T, err error) {
		t.Helper()
		var missing *ctm.MissingError
		if !errors.As(err, &missing) {
			t.Fatalf("err = %T %v, want *ctm.MissingError", err, err)
		}
		if missing.Field != field {
			t.Errorf("MissingError.Field = %q, want %q", missing.Field, field)
		}
		if !strings.HasPrefix(missing.Message, field+",") {
			t.Errorf("message %q does not begin with its field %s", missing.Message, field)
		}
	}
}

// R-03's order decides which fault a document with several is refused for: the version
// before the shape, the shape before the inner CTM, the inner CTM before the id.
func TestUnmarshalRefusesInOrder(t *testing.T) {
	const wrongID = "1111111111111111111111111111111111111111111111111111111111111111"

	m := document(t)
	m["snapshot_version"] = "2"
	m["probes"] = []any{1}
	var version *VersionError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &version) {
		t.Errorf("a version 2 with a probe: %T %v, want the version's refusal", err, err)
	}

	m = document(t)
	m["probes"] = []any{1}
	innerCTM(m)["ctm_version"] = "1"
	var invalid *InvalidError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &invalid) || invalid.Field != "probes" {
		t.Errorf("a probe beside a CTM 1: %T %v, want probes' refusal", err, err)
	}

	m = document(t)
	m["snapshot_id"] = wrongID
	innerCTM(m)["ctm_version"] = "1"
	var ctmVersion *ctm.VersionError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &ctmVersion) {
		t.Errorf("a wrong id beside a CTM 1: %T %v, want the CTM's refusal", err, err)
	}

	// The inner CTM's own refusals before its observed_at; its observed_at before the id.
	m = document(t)
	delete(m, "observed_at")
	delete(innerCTM(m)["envelope"].(map[string]any), "observed_at")
	delete(innerCTM(m), "links")
	var missing *ctm.MissingError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &missing) || missing.Field != "ctm.links" {
		t.Errorf("no links and no observed_at: %T %v, want the links' refusal", err, err)
	}

	m = document(t)
	m["snapshot_id"] = wrongID
	delete(m, "observed_at")
	delete(innerCTM(m)["envelope"].(map[string]any), "observed_at")
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &missing) || missing.Field != "ctm.envelope.observed_at" {
		t.Errorf("a wrong id and no observed_at: %T %v, want observed_at's refusal", err, err)
	}
}

// A hand user wraps a bare CTM and nothing else: the id is computed and observed_at is
// filled from the CTM (R-02; FR-005).
func TestUnmarshalFillsTheOuterPart(t *testing.T) {
	bare, err := os.ReadFile(fixturePath("three-node"))
	if err != nil {
		t.Fatal(err)
	}
	wrapped := []byte(`{"snapshot_version": "1", "ctm": ` + string(bare) + `, "probes": []}`)
	s, err := Unmarshal(wrapped)
	if err != nil {
		t.Fatal(err)
	}
	want := Take(fixture(t, "three-node"))
	if s.ID != want.ID {
		t.Errorf("snapshot_id = %s, want %s", s.ID, want.ID)
	}
	if s.ObservedAt != "2026-09-08T12:00:00.000000Z" || s.ObservedAt != s.CTM.Envelope.ObservedAt {
		t.Errorf("observed_at = %q, want the CTM's", s.ObservedAt)
	}
	if s.Version != Version || s.Probes == nil || len(s.Probes) != 0 {
		t.Errorf("version %q, probes %v", s.Version, s.Probes)
	}
	// Once filled, it is the document Fylgja writes for the same take.
	got, err := Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	stored, err := Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, stored) {
		t.Error("the filled document is not the stored form of the same take")
	}
}

// What Marshal writes, Unmarshal reads back to the same snapshot and the same bytes.
func TestStoredFormRoundTrips(t *testing.T) {
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			stored, err := Marshal(Take(fixture(t, name)))
			if err != nil {
				t.Fatal(err)
			}
			s, err := Unmarshal(stored)
			if err != nil {
				t.Fatal(err)
			}
			again, err := Marshal(s)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(stored, again) {
				t.Errorf("the stored form did not survive a round trip:\n%s\n---\n%s", stored, again)
			}
		})
	}
}

// The stored form is the outer part first, then the body: snapshot_version, snapshot_id,
// observed_at, ctm, probes, the probes list written [] (data-model §1).
func TestStoredFormOrder(t *testing.T) {
	stored, err := Marshal(Take(fixture(t, "three-node")))
	if err != nil {
		t.Fatal(err)
	}
	doc := decodeOrdered(t, stored).(*ordered)
	if got := strings.Join(doc.keys, ","); got != strings.Join(outerKeys, ",") {
		t.Errorf("stored keys %s, want %s", got, strings.Join(outerKeys, ","))
	}
	if !bytes.HasSuffix(stored, []byte("  \"probes\": []\n}\n")) {
		t.Errorf("the stored form does not end with an empty probes list and a newline:\n%s", stored[len(stored)-40:])
	}
}

// Marshal refuses a snapshot that breaks version 1's invariants, so nothing writes a
// document Unmarshal would refuse.
func TestMarshalRefusesABrokenSnapshot(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(s *Snapshot)
	}{
		{"another id", func(s *Snapshot) { s.ID = strings.Repeat("0", 64) }},
		{"no id", func(s *Snapshot) { s.ID = "" }},
		{"another version", func(s *Snapshot) { s.Version = "2" }},
		{"observed_at not the CTM's", func(s *Snapshot) { s.ObservedAt = "2026-09-14T09:30:15.123456Z" }},
		// Each beside an inner CTM recording the same, so the id still hashes and the two
		// still agree: the form alone refuses it.
		{"no observed_at", func(s *Snapshot) { s.ObservedAt, s.CTM.Envelope.ObservedAt = "", "" }},
		{"observed_at not of the CTM's form", func(s *Snapshot) {
			s.ObservedAt, s.CTM.Envelope.ObservedAt = "2026-10-27T18:55:42Z", "2026-10-27T18:55:42Z"
		}},
		{"a probe", func(s *Snapshot) { s.Probes = []json.RawMessage{json.RawMessage(`{}`)} }},
		{"no ctm", func(s *Snapshot) { s.CTM = nil }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := Take(fixture(t, "three-node"))
			tc.change(s)
			if b, err := Marshal(s); err == nil {
				t.Errorf("Marshal wrote it:\n%s", b)
			}
		})
	}
}

// Save writes the stored form whole, mode 0644, and Load reads it back; a file that is not
// there is fs.ErrNotExist.
func TestSaveAndLoad(t *testing.T) {
	s := Take(fixture(t, "mixed"))
	path := filepath.Join(t.TempDir(), "snap.json")
	if err := Save(s, path); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o644 {
		t.Errorf("mode %v, want 0644", info.Mode().Perm())
	}
	data, _ := os.ReadFile(path)
	if want, _ := Marshal(s); !bytes.Equal(data, want) {
		t.Error("Save did not write the stored form")
	}
	loaded, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.ID != s.ID || loaded.ObservedAt != s.ObservedAt {
		t.Errorf("Load = %s at %s, want %s at %s", loaded.ID, loaded.ObservedAt, s.ID, s.ObservedAt)
	}
	if entries, _ := os.ReadDir(filepath.Dir(path)); len(entries) != 1 {
		t.Errorf("Save left %d files beside the snapshot", len(entries)-1)
	}
	if _, err := Load(filepath.Join(t.TempDir(), "absent.json")); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("Load of an absent file = %v, want fs.ErrNotExist", err)
	}
}
