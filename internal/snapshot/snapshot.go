// Package snapshot holds the snapshot, the core's one input (D-061): one document of
// version 2 wrapping an unchanged CTM 2 and the probe declarations beside it (016), with
// an id of its own. A document of version 1, which 018 wrote with an empty probes list, is
// read as a 2 with no probes: the version is not hashed, so its id is unchanged (R-05).
//
// The document has two parts. The outer part is snapshot_version, snapshot_id and
// observed_at, the take's time. The body is ctm and probes. The id hashes the body with
// the inner envelope's observed_at left out, and nothing else left out, so the same
// intent taken twice has one id whenever it was read (R-01). The stored bytes keep
// observed_at and the outer part, so the bytes the id hashes are never stored.
//
// It imports the CTM, the probe's declaration, the findings whose rules name a probe's
// fault and the standard library alone: a snapshot is the compiler's input wrapped, and
// nothing here reads a source or compiles.
//
// Struct field order is significant, as the CTM's is: it fixes the field order of the
// stored form and of the hashed bytes.
package snapshot

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// Version is the snapshot's format version, the one every document this build writes
// declares.
//
// "1" at 018: an unchanged CTM 2 and an empty probes list. "2" at 016: the list's element
// is the declaration's probe. A "1" is read as a "2" with no probes (Version1), and
// nothing converts a document of another version.
const Version = "2"

// Version1 is the version 018 wrote, read as a Version with no probes and never written.
const Version1 = "1"

// ObservedAtLayout is the take's observed_at: UTC, six fractional digits, the form the
// CTM envelope records a read's in. It was internal/stage's read's form too, until 020 moved
// the read to the orchestrator's adapter, which writes it the same way (T035).
const ObservedAtLayout = "2006-01-02T15:04:05.000000Z"

// Snapshot is one take of intent: the outer part first, then the body.
type Snapshot struct {
	Version string `json:"snapshot_version"`
	// ID is the lowercase-hex SHA-256 of the hashed bytes (Hashed). Not hashed.
	ID string `json:"snapshot_id"`
	// ObservedAt is the take's time. In version 1 a take is one read, so it is the inner
	// CTM's envelope's observed_at, copied. Not hashed: it governs nothing (Constitution VI).
	ObservedAt string `json:"observed_at"`
	// CTM is the body's intent, normalised. Hashed, its envelope's observed_at left out.
	CTM *ctm.CTM `json:"ctm"`
	// Probes is the body's probe declarations, in the declaration's order, each held to
	// the declaration's rules that read no CTM (probe.Validate): written [] and never null,
	// and empty in a document read as version 1. Hashed.
	Probes []probe.Probe `json:"probes"`
}

// Take wraps a CTM and a list of probes as a snapshot of version 2, the probes in the
// order given, none when the list is nil. It is pure: the CTM is copied before it is
// normalised, and the list copied, so the caller's are untouched, and the snapshot shares
// nothing with them. It holds the probes to no rule: Marshal and the store do, before
// anything is written.
//
// The copy is a plain encoding/json round trip, not ctm.Marshal and ctm.Unmarshal:
// ctm.Marshal normalises its argument in place, and ctm.Unmarshal refuses a CTM built in
// memory whose lists Normalize has not yet filled.
func Take(c *ctm.CTM, probes []probe.Probe) *Snapshot {
	b, err := json.Marshal(c)
	if err != nil {
		// Every field of a CTM is a string, a bool, or a slice or pointer of them, which
		// encoding/json always encodes: a failure here is a programming error.
		panic(fmt.Sprintf("snapshot: copying a CTM: %v", err))
	}
	var cp ctm.CTM
	if err := json.Unmarshal(b, &cp); err != nil {
		panic(fmt.Sprintf("snapshot: copying a CTM: %v", err))
	}
	ctm.Normalize(&cp)
	s := &Snapshot{
		Version:    Version,
		ObservedAt: cp.Envelope.ObservedAt,
		CTM:        &cp,
		// A Probe holds strings and an array of structs of strings: a shallow clone
		// shares nothing.
		Probes: listOf(slices.Clone(probes)),
	}
	id, err := ID(s)
	if err != nil {
		panic(fmt.Sprintf("snapshot: hashing a take: %v", err))
	}
	s.ID = id
	return s
}

// hashedEnvelope is ctm.Envelope without ObservedAt: every other field, in its order and
// with its tags, so the hashed envelope is encoded as ctm.Marshal encodes the envelope
// with the observed_at key left out. A test holds it to ctm.Envelope by reflection, so a
// field added to the envelope fails tier 1 until it is named here or left out on purpose.
type hashedEnvelope struct {
	Branch     string            `json:"branch"`
	At         string            `json:"at,omitempty"`
	SchemaHash string            `json:"schema_hash"`
	Scope      string            `json:"scope"`
	Mapping    ctm.Mapping       `json:"mapping"`
	Fidelity   []ctm.FidelityRow `json:"fidelity"`
}

// hashedCTM is ctm.CTM with the hashed envelope in its envelope's place, held to ctm.CTM
// by reflection as hashedEnvelope is to the envelope.
type hashedCTM struct {
	CTMVersion string         `json:"ctm_version"`
	Envelope   hashedEnvelope `json:"envelope"`
	Devices    []ctm.Device   `json:"devices"`
	Links      []ctm.Link     `json:"links"`
}

// hashedBody is the body the id hashes: {"ctm": …, "probes": […]}.
type hashedBody struct {
	CTM    hashedCTM     `json:"ctm"`
	Probes []probe.Probe `json:"probes"`
}

// Hashed returns the bytes a snapshot's id hashes: {"ctm": …, "probes": […]}, the probes
// in the snapshot's order and each in the declaration's field order, the version left
// out, so a 1 and a 2 with no probes hash alike (R-05); the CTM normalised (in place, as
// ctm.Marshal normalises) and its envelope written without observed_at, encoded as
// ctm.Marshal encodes a CTM: struct field order, two-space indent, LF, a trailing newline,
// Go's default escaping. They differ from the stored bytes and are never stored. By hand, over a stored snapshot, exact when no string holds <, >, &, U+2028
// or U+2029, which Go escapes and jq writes raw, or DEL (U+007F), which jq escapes and Go
// writes raw:
//
//	jq --indent 2 'del(.snapshot_version, .snapshot_id, .observed_at, .ctm.envelope.observed_at)' snapshots/<id>.json | sha256sum
func Hashed(s *Snapshot) ([]byte, error) {
	if s.CTM == nil {
		return nil, fmt.Errorf("snapshot: no ctm to hash")
	}
	ctm.Normalize(s.CTM)
	e := s.CTM.Envelope
	body := hashedBody{
		CTM: hashedCTM{
			CTMVersion: s.CTM.CTMVersion,
			Envelope: hashedEnvelope{
				Branch:     e.Branch,
				At:         e.At,
				SchemaHash: e.SchemaHash,
				Scope:      e.Scope,
				Mapping:    e.Mapping,
				Fidelity:   e.Fidelity,
			},
			Devices: s.CTM.Devices,
			Links:   s.CTM.Links,
		},
		Probes: listOf(s.Probes),
	}
	b, err := json.MarshalIndent(body, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("snapshot: encoding the hashed body: %w", err)
	}
	return append(b, '\n'), nil
}

// ID is a snapshot's content address: the lowercase-hex SHA-256 of Hashed. It is never
// read from s.ID, which is what a document declares; this is what its body hashes to.
func ID(s *Snapshot) (string, error) {
	b, err := Hashed(s)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

// IsID reports whether s has the shape of a snapshot id: 64 lowercase hex digits, the
// bundle id's shape, so a client tells an id from a file by its shape alone (R-07).
// Uppercase is rejected rather than folded — two spellings of one id would defeat the
// string comparison every caller does. bundle.IsID's rule, copied rather than imported:
// the snapshot imports nothing but the CTM.
func IsID(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, r := range s {
		digit := r >= '0' && r <= '9'
		lowerHex := r >= 'a' && r <= 'f'
		if !digit && !lowerHex {
			return false
		}
	}
	return true
}

// Marshal encodes a snapshot in its stored form: the outer part first (snapshot_version,
// snapshot_id, observed_at), then ctm, then probes; struct field order, two-space indent,
// LF, a trailing newline, the CTM normalised. It refuses a snapshot that breaks version
// 2's invariants, so nothing writes a document Unmarshal would refuse: the version is
// "2", the id is the body's hash, observed_at is the inner CTM's and of its form, and
// every probe holds to the declaration's rules that read no CTM.
func Marshal(s *Snapshot) ([]byte, error) {
	if err := check(s); err != nil {
		return nil, err
	}
	out := *s
	out.Probes = listOf(s.Probes)
	b, err := json.MarshalIndent(&out, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("snapshot: encoding: %w", err)
	}
	return append(b, '\n'), nil
}

// check holds a snapshot to version 2's invariants before it is written or filed: a
// document read as a 1 is written as a 2.
func check(s *Snapshot) error {
	if s.CTM == nil {
		return fmt.Errorf("snapshot: no ctm")
	}
	if s.Version != Version {
		return fmt.Errorf("snapshot: snapshot_version %q, where this build writes %q", s.Version, Version)
	}
	if err := probeFault(s.Probes); err != nil {
		return fmt.Errorf("snapshot: %s: %s", err.Field, err.Message)
	}
	if s.ObservedAt != s.CTM.Envelope.ObservedAt {
		return fmt.Errorf("snapshot: observed_at %q is not the inner CTM's %q", s.ObservedAt, s.CTM.Envelope.ObservedAt)
	}
	if !isObservedAt(s.ObservedAt) {
		return fmt.Errorf("snapshot: observed_at %q is not a UTC time with six fractional digits (%s)", s.ObservedAt,
			ObservedAtLayout)
	}
	id, err := ID(s)
	if err != nil {
		return err
	}
	if s.ID != id {
		return fmt.Errorf("snapshot: snapshot_id %q is not its body's hash %s", s.ID, id)
	}
	return nil
}

// listOf is the list written for p: [] and never null.
func listOf(p []probe.Probe) []probe.Probe {
	if p == nil {
		return []probe.Probe{}
	}
	return p
}

// entries counts a list's entries in words: "1 entry", "2 entries".
func entries(n int) string {
	if n == 1 {
		return "1 entry"
	}
	return fmt.Sprintf("%d entries", n)
}
