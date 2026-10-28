package snapshot

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// document is the stored form of three-node's take, with no probes, decoded to a map for
// a case to change: the keys' order is lost, which Unmarshal does not read.
func document(t *testing.T) map[string]any {
	t.Helper()
	return documentOf(t, Take(fixture(t, "three-node"), nil))
}

// probed is the stored form of three-node's take with n1-loop's and n2-loop's probes,
// decoded to a map as document is.
func probed(t *testing.T) map[string]any {
	t.Helper()
	return documentOf(t, Take(fixture(t, "three-node"), declared(t, "n1-loop", "n2-loop")))
}

func documentOf(t *testing.T, s *Snapshot) map[string]any {
	t.Helper()
	b, err := Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

// declared is the probes of the declarations under the module root's testdata/probes/,
// in the order named.
func declared(t *testing.T, names ...string) []probe.Probe {
	t.Helper()
	var list []probe.Probe
	for _, name := range names {
		path := filepath.Join("..", "..", "testdata", "probes", name+".json")
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		d, found := probe.Parse(data, path)
		if found.Rejected() {
			t.Fatalf("%s: %v", path, found)
		}
		list = append(list, d.Probes...)
	}
	return list
}

// element is the stored form's probe i, for a case to change.
func element(m map[string]any, i int) map[string]any {
	return m["probes"].([]any)[i].(map[string]any)
}

// endpoint is the stored form's probe i's endpoint j, for a case to change.
func endpoint(m map[string]any, i, j int) map[string]any {
	return element(m, i)["endpoints"].([]any)[j].(map[string]any)
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
		{"snapshot_version 3", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_version"] = "3"
			return encode(t, m)
		}, wantVersion("3", `the snapshot declares snapshot_version "3"; this build reads "1" and "2", and nothing converts one`)},
		{"snapshot_version absent", func(t *testing.T) []byte {
			m := document(t)
			delete(m, "snapshot_version")
			return encode(t, m)
		}, wantVersion("", `the snapshot declares no snapshot_version; this build reads "1" and "2", and nothing converts one`)},
		{"snapshot_version a number", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_version"] = 2
			return encode(t, m)
		}, wantVersion("2", `the snapshot declares snapshot_version 2; this build reads "1" and "2", and nothing converts one`)},
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
		}, wantInvalid("probes", "probes is not recorded", "in snapshot 2 the list is required, [] when")},
		{"probes absent from a 1", func(t *testing.T) []byte {
			m := document(t)
			m["snapshot_version"] = "1"
			delete(m, "probes")
			return encode(t, m)
		}, wantInvalid("probes", "probes is not recorded", "in snapshot 1 the list is required and empty")},
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
		{"a 1 holding a probe", func(t *testing.T) []byte {
			m := probed(t)
			m["snapshot_version"] = "1"
			m["probes"] = m["probes"].([]any)[:1]
			return encode(t, m)
		}, wantInvalid("probes", "probes holds 1 entry; in snapshot 1 the list is required and empty; a snapshot with probes is a 2")},
		// A 2's element is the declaration's probe, decoded strictly, then held to the
		// declaration's rules that read no CTM: the first fault, at the element's field.
		{"a probe not an object", func(t *testing.T) []byte {
			m := document(t)
			m["probes"] = []any{1}
			return encode(t, m)
		}, wantInvalid("probes[0]", "probes[0] is not a JSON object")},
		{"a probe with no field", func(t *testing.T) []byte {
			m := document(t)
			m["probes"] = []any{map[string]any{}}
			return encode(t, m)
		}, wantInvalid("probes[0].name", "a probe has no name, which it requires")},
		{"a probe with an unknown key", func(t *testing.T) []byte {
			m := probed(t)
			element(m, 1)["comment"] = "a hand user's note"
			return encode(t, m)
		}, wantInvalid("probes[1].comment", `the key "comment"`, "name, format, endpoints")},
		{"a probe with one endpoint", func(t *testing.T) []byte {
			m := probed(t)
			element(m, 0)["endpoints"] = element(m, 0)["endpoints"].([]any)[:1]
			return encode(t, m)
		}, wantInvalid("probes[0].endpoints", "endpoints holds 1; a probe has exactly two")},
		{"an endpoint's field not a string", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 0, 1)["device"] = 7
			return encode(t, m)
		}, wantInvalid("probes[0].endpoints[1].device", "device is 7, not a string")},
		{"a probe's name invalid", func(t *testing.T) []byte {
			m := probed(t)
			element(m, 1)["name"] = "N2 Loop"
			return encode(t, m)
		}, wantInvalid("probes[1].name", `probe name "N2 Loop" is not`)},
		{"a probe's name taken", func(t *testing.T) []byte {
			m := probed(t)
			element(m, 1)["name"] = "n1-loop"
			return encode(t, m)
		}, wantInvalid("probes[1].name", `probe name "n1-loop" is declared at probes[0] and probes[1]`)},
		{"an address with no prefix length", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 0, 0)["address"] = "10.1.10.2"
			return encode(t, m)
		}, wantInvalid("probes[0].endpoints[0].address", `address "10.1.10.2" is not an address with a prefix length`)},
		{"a gateway with a prefix length", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 1, 1)["gateway"] = "10.2.11.1/24"
			return encode(t, m)
		}, wantInvalid("probes[1].endpoints[1].gateway", `gateway "10.2.11.1/24" carries a prefix length`)},
		{"a gateway outside its address's prefix", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 0, 1)["gateway"] = "10.1.12.1"
			return encode(t, m)
		}, wantInvalid("probes[0].endpoints[1].gateway", "gateway 10.1.12.1 is not within 10.1.11.0/24")},
		{"a probe of two families", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 0, 1)["address"] = "2001:db8::2/64"
			endpoint(m, 0, 1)["gateway"] = "2001:db8::1"
			return encode(t, m)
		}, wantInvalid("probes[0]", "probe n1-loop's addresses and gateways are of two families")},
		{"an address another probe's", func(t *testing.T) []byte {
			m := probed(t)
			endpoint(m, 1, 0)["address"] = "10.1.10.2/24"
			endpoint(m, 1, 0)["gateway"] = "10.1.10.1"
			return encode(t, m)
		}, wantInvalid("probes[1].endpoints[0].address",
			"address 10.1.10.2 of probe n2-loop endpoint a is probe n1-loop endpoint a's too")},
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
			want := Take(fixture(t, "three-node"), nil).ID
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
	m["snapshot_version"] = "3"
	m["probes"] = []any{1}
	var version *VersionError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &version) {
		t.Errorf("a version 3 with a probe: %T %v, want the version's refusal", err, err)
	}

	m = document(t)
	m["probes"] = []any{1}
	innerCTM(m)["ctm_version"] = "1"
	var invalid *InvalidError
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &invalid) || invalid.Field != "probes[0]" {
		t.Errorf("a probe not an object beside a CTM 1: %T %v, want the probe's refusal", err, err)
	}

	// The strict decode of every element before any rule across them, and the list's
	// order: probe 1's unknown key before probe 0's address, which Validate would find.
	m = probed(t)
	endpoint(m, 0, 0)["address"] = "10.1.10.2"
	element(m, 1)["comment"] = "a hand user's note"
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &invalid) || invalid.Field != "probes[1].comment" {
		t.Errorf("a bad address and an unknown key: %T %v, want the key's refusal", err, err)
	}
	m = probed(t)
	endpoint(m, 1, 0)["address"] = "10.2.10.2"
	endpoint(m, 0, 1)["gateway"] = "10.1.12.1"
	if _, err := Unmarshal(encode(t, m)); !errors.As(err, &invalid) || invalid.Field != "probes[0].endpoints[1].gateway" {
		t.Errorf("two probes' faults: %T %v, want the first probe's", err, err)
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

// A hand user wraps a bare CTM and nothing else, as a 1 or as a 2: the id is computed and
// observed_at is filled from the CTM (R-02; FR-005), and a 1 is read as a 2 with no probes
// (R-05).
func TestUnmarshalFillsTheOuterPart(t *testing.T) {
	bare, err := os.ReadFile(fixturePath("three-node"))
	if err != nil {
		t.Fatal(err)
	}
	want := Take(fixture(t, "three-node"), nil)
	stored, err := Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	for _, version := range []string{"1", "2"} {
		t.Run(version, func(t *testing.T) {
			wrapped := []byte(`{"snapshot_version": "` + version + `", "ctm": ` + string(bare) + `, "probes": []}`)
			s, err := Unmarshal(wrapped)
			if err != nil {
				t.Fatal(err)
			}
			if s.ID != want.ID {
				t.Errorf("snapshot_id = %s, want %s", s.ID, want.ID)
			}
			if s.ObservedAt != "2026-09-08T12:00:00.000000Z" || s.ObservedAt != s.CTM.Envelope.ObservedAt {
				t.Errorf("observed_at = %q, want the CTM's", s.ObservedAt)
			}
			if s.Version != Version || s.Probes == nil || len(s.Probes) != 0 {
				t.Errorf("version %q, probes %v; want %q and []", s.Version, s.Probes, Version)
			}
			// Once filled, it is the document Fylgja writes for the same take: a 2.
			got, err := Marshal(s)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(got, stored) {
				t.Error("the filled document is not the stored form of the same take")
			}
		})
	}
}

// A 1 on disk reads as a 2 with no probes and the same id, since the version is not hashed:
// the three wrapped fixtures, filed as 1 by 018, and each take's stored form with its
// version line set back to 1 (R-05; US7 scenario 1).
func TestAVersion1ReadsAsA2(t *testing.T) {
	for _, f := range wrappedFixtures {
		t.Run(f.name, func(t *testing.T) {
			path := wrappedPath(f.name)
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var declared struct {
				Version string `json:"snapshot_version"`
			}
			if err := json.Unmarshal(data, &declared); err != nil {
				t.Fatal(err)
			}
			s, err := Unmarshal(data)
			if err != nil {
				t.Fatalf("%s (snapshot_version %q): %v", path, declared.Version, err)
			}
			if s.Version != Version || len(s.Probes) != 0 || s.ID != f.id {
				t.Errorf("%s read as version %q, %d probes, id %s; want %q, none, %s",
					path, s.Version, len(s.Probes), s.ID, Version, f.id)
			}

			taken := Take(fixture(t, f.name), nil)
			stored, err := Marshal(taken)
			if err != nil {
				t.Fatal(err)
			}
			one := asVersion1(t, stored)
			read, err := Unmarshal(one)
			if err != nil {
				t.Fatalf("the take's stored form as a 1: %v", err)
			}
			if read.ID != taken.ID || read.Version != Version {
				t.Errorf("the take's stored form as a 1 reads as version %q, id %s; want %q, %s",
					read.Version, read.ID, Version, taken.ID)
			}
			if again, err := Marshal(read); err != nil || !bytes.Equal(again, stored) {
				t.Errorf("a 1 read and written again is not the take's stored form (%v)", err)
			}
		})
	}
}

// asVersion1 is a stored form with its snapshot_version line set to 1, the bytes 018 wrote
// for the same take.
func asVersion1(t *testing.T, stored []byte) []byte {
	t.Helper()
	const line2, line1 = `"snapshot_version": "2",`, `"snapshot_version": "1",`
	if bytes.Count(stored, []byte(line2)) != 1 {
		t.Fatalf("the stored form does not declare snapshot_version 2 once:\n%s", stored)
	}
	return bytes.Replace(stored, []byte(line2), []byte(line1), 1)
}

// What Marshal writes, Unmarshal reads back to the same snapshot and the same bytes, the
// probes in the order taken.
func TestStoredFormRoundTrips(t *testing.T) {
	for _, tc := range []struct {
		name   string
		probes []probe.Probe
	}{
		{"three-node", nil},
		{"lossy", nil},
		{"mixed", nil},
		{"three-node", declared(t, "n2-loop", "n1-loop")},
		{"mixed", declared(t, "e1-loop")},
	} {
		name := tc.name
		t.Run(fmt.Sprintf("%s with %d probes", name, len(tc.probes)), func(t *testing.T) {
			taken := Take(fixture(t, name), tc.probes)
			stored, err := Marshal(taken)
			if err != nil {
				t.Fatal(err)
			}
			s, err := Unmarshal(stored)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(s.Probes, listOf(tc.probes)) || s.ID != taken.ID {
				t.Errorf("read back with probes %v and id %s; taken with %v and %s", s.Probes, s.ID, tc.probes, taken.ID)
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
	stored, err := Marshal(Take(fixture(t, "three-node"), nil))
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

// Marshal refuses a snapshot that breaks version 2's invariants, so nothing writes a
// document Unmarshal would refuse.
func TestMarshalRefusesABrokenSnapshot(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(s *Snapshot)
	}{
		{"another id", func(s *Snapshot) { s.ID = strings.Repeat("0", 64) }},
		{"no id", func(s *Snapshot) { s.ID = "" }},
		{"version 1, which is read and never written", func(s *Snapshot) { s.Version = "1" }},
		{"another version", func(s *Snapshot) { s.Version = "3" }},
		{"observed_at not the CTM's", func(s *Snapshot) { s.ObservedAt = "2026-09-14T09:30:15.123456Z" }},
		// Each beside an inner CTM recording the same, so the id still hashes and the two
		// still agree: the form alone refuses it.
		{"no observed_at", func(s *Snapshot) { s.ObservedAt, s.CTM.Envelope.ObservedAt = "", "" }},
		{"observed_at not of the CTM's form", func(s *Snapshot) {
			s.ObservedAt, s.CTM.Envelope.ObservedAt = "2026-10-27T18:55:42Z", "2026-10-27T18:55:42Z"
		}},
		// Each with the id recomputed, so the probe's rule alone refuses it.
		{"a probe with no name", func(s *Snapshot) {
			s.Probes = []probe.Probe{{}}
			s.ID, _ = ID(s)
		}},
		{"a probe whose gateway is outside its prefix", func(s *Snapshot) {
			s.Probes[0].Endpoints[1].Gateway = "10.1.12.1"
			s.ID, _ = ID(s)
		}},
		{"no ctm", func(s *Snapshot) { s.CTM = nil }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := Take(fixture(t, "three-node"), declared(t, "n1-loop"))
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
	s := Take(fixture(t, "mixed"), declared(t, "e1-loop"))
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
