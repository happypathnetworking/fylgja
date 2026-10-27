package snapshot

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// The outer keys of a snapshot of version 1, in their stored order.
var outerKeys = []string{"snapshot_version", "snapshot_id", "observed_at", "ctm", "probes"}

// Unmarshal decodes a snapshot strictly, in R-03's order, and returns it normalised with
// its id and observed_at filled. Each refusal is typed, so the server files it under its
// rule:
//
//  1. snapshot_version, read on its own: not "1", or absent, is a *VersionError. A bare
//     CTM is refused here, for its version, rather than for the first key the strict
//     decode would trip on.
//  2. the outer shape: an unknown key; ctm absent, null or not an object; probes absent,
//     null, not a list or not empty; snapshot_id present and not an id; observed_at
//     present and not of the CTM's form or not the inner CTM's. Each is an *InvalidError
//     naming the field. A document that is not a JSON object has no version to read, and
//     is an *InvalidError naming no field.
//  3. the inner CTM under ctm.Unmarshal's own refusals: a *ctm.VersionError as it is, a
//     *ctm.MissingError with its field and message prefixed "ctm.".
//  4. observed_at filled from the inner CTM when absent.
//  5. the id computed: an *IDMismatchError when declared and different; set when absent.
//
// JSON that does not parse is a decoding error, as a CTM's is: nothing was validated.
func Unmarshal(data []byte) (*Snapshot, error) {
	// Keys are matched exactly, never folded as a struct decode folds them: a document
	// spelling a key another way carries an unknown key.
	var outer map[string]json.RawMessage
	if err := json.Unmarshal(data, &outer); err != nil {
		var notObject *json.UnmarshalTypeError
		if errors.As(err, &notObject) {
			return nil, &InvalidError{Message: "the snapshot is not a JSON object"}
		}
		return nil, fmt.Errorf("decoding snapshot: %w", err)
	}
	if outer == nil {
		return nil, &InvalidError{Message: "the snapshot is not a JSON object"}
	}

	// 1. The version, on its own.
	if err := readVersion(outer["snapshot_version"]); err != nil {
		return nil, err
	}

	// 2. The outer shape.
	if err := unknownKey(outer); err != nil {
		return nil, err
	}
	rawCTM, present := outer["ctm"]
	switch {
	case !present || isNull(rawCTM):
		return nil, &InvalidError{Field: "ctm", Message: "ctm is not recorded: a snapshot of version " + Version +
			" wraps one CTM " + ctm.Version + ", which it requires"}
	case !isObject(rawCTM):
		return nil, &InvalidError{Field: "ctm", Message: "ctm is not an object: a snapshot of version " + Version +
			" wraps one CTM " + ctm.Version + ", a JSON object"}
	}
	if err := readProbes(outer["probes"]); err != nil {
		return nil, err
	}
	declaredID, err := readID(outer)
	if err != nil {
		return nil, err
	}
	observedAt, err := readObservedAt(outer, rawCTM)
	if err != nil {
		return nil, err
	}

	// 3. The inner CTM, by its own rules, named where it sits in the file.
	c, err := ctm.Unmarshal(rawCTM)
	if err != nil {
		var missing *ctm.MissingError
		if errors.As(err, &missing) {
			return nil, &ctm.MissingError{Field: "ctm." + missing.Field, Message: "ctm." + missing.Message}
		}
		var version *ctm.VersionError
		if errors.As(err, &version) {
			return nil, version
		}
		return nil, fmt.Errorf("in the snapshot's ctm: %w", err)
	}

	// 4. observed_at, filled from the inner CTM when the document leaves it out.
	if observedAt == "" {
		observedAt = c.Envelope.ObservedAt
	}

	s := &Snapshot{Version: Version, ObservedAt: observedAt, CTM: c, Probes: []json.RawMessage{}}

	// 5. The id: computed, then held to the one declared.
	computed, err := ID(s)
	if err != nil {
		return nil, err
	}
	if declaredID != "" && declaredID != computed {
		return nil, &IDMismatchError{Declared: declaredID, Computed: computed}
	}
	s.ID = computed
	return s, nil
}

// readVersion refuses a snapshot_version that is not "1", or none. A value that is not
// a JSON string is named as its JSON text.
func readVersion(raw json.RawMessage) error {
	if raw == nil || isNull(raw) {
		return &VersionError{}
	}
	var got string
	if err := json.Unmarshal(raw, &got); err != nil {
		text := string(bytes.TrimSpace(raw))
		return &VersionError{Got: text, raw: text}
	}
	if got != Version {
		return &VersionError{Got: got}
	}
	return nil
}

// unknownKey names the first outer key, in byte order, that version 1 does not hold.
func unknownKey(outer map[string]json.RawMessage) error {
	var unknown []string
	for k := range outer {
		known := false
		for _, want := range outerKeys {
			if k == want {
				known = true
				break
			}
		}
		if !known {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) == 0 {
		return nil
	}
	sort.Strings(unknown)
	return &InvalidError{Field: unknown[0], Message: fmt.Sprintf(
		"the snapshot carries the key %q, which snapshot %s does not hold: it holds snapshot_version, snapshot_id, observed_at, ctm and probes",
		unknown[0], Version)}
}

// readProbes refuses a probes list that is absent, null, not a list, or not empty.
func readProbes(raw json.RawMessage) error {
	const why = "in snapshot " + Version + " the list is required and empty, since 016 defines its element"
	if raw == nil || isNull(raw) {
		return &InvalidError{Field: "probes", Message: "probes is not recorded; " + why}
	}
	var list []json.RawMessage
	if err := json.Unmarshal(raw, &list); err != nil {
		return &InvalidError{Field: "probes", Message: "probes is not a list; " + why}
	}
	if len(list) != 0 {
		return &InvalidError{Field: "probes", Message: fmt.Sprintf("probes holds %s; %s", entries(len(list)), why)}
	}
	return nil
}

// readID returns the snapshot_id a document declares, "" when it declares none, and
// refuses one that is not an id.
func readID(outer map[string]json.RawMessage) (string, error) {
	raw, present := outer["snapshot_id"]
	if !present {
		return "", nil
	}
	var id string
	if err := json.Unmarshal(raw, &id); err != nil || !IsID(id) {
		return "", &InvalidError{Field: "snapshot_id", Message: fmt.Sprintf(
			"snapshot_id %s is not 64 lowercase hex characters; leave it out to have it computed", bytes.TrimSpace(raw))}
	}
	return id, nil
}

// readObservedAt returns the observed_at a document declares, "" when it declares none,
// and refuses one that is not of the CTM's form or not the inner CTM's. The inner CTM's is
// read leniently here, before the CTM is decoded: a CTM that carries none, or is refused
// later by its own rules, has none to agree with.
func readObservedAt(outer map[string]json.RawMessage, rawCTM json.RawMessage) (string, error) {
	raw, present := outer["observed_at"]
	if !present {
		return "", nil
	}
	var at string
	if err := json.Unmarshal(raw, &at); err != nil || !isObservedAt(at) {
		return "", &InvalidError{Field: "observed_at", Message: fmt.Sprintf(
			"observed_at %s is not a UTC time with six fractional digits (%s); leave it out to have it filled from the CTM",
			bytes.TrimSpace(raw), ObservedAtLayout)}
	}
	var inner struct {
		Envelope struct {
			ObservedAt string `json:"observed_at"`
		} `json:"envelope"`
	}
	_ = json.Unmarshal(rawCTM, &inner)
	if at != inner.Envelope.ObservedAt {
		innerAt := inner.Envelope.ObservedAt
		if innerAt == "" {
			innerAt = "none recorded"
		}
		return "", &InvalidError{Field: "observed_at", Message: fmt.Sprintf(
			"observed_at %s is not the inner CTM's (%s): in snapshot %s a take is one read, so the two are equal",
			at, innerAt, Version)}
	}
	return at, nil
}

// isObservedAt reports whether s is a time in ObservedAtLayout, written as that layout
// writes it.
func isObservedAt(s string) bool {
	t, err := time.Parse(ObservedAtLayout, s)
	return err == nil && t.Format(ObservedAtLayout) == s
}

func isNull(raw json.RawMessage) bool { return string(bytes.TrimSpace(raw)) == "null" }

func isObject(raw json.RawMessage) bool {
	t := bytes.TrimSpace(raw)
	return len(t) > 0 && t[0] == '{'
}

// VersionError is Unmarshal's refusal of a snapshot of another version, or of none: Got
// is the version the document declares, empty when it declares none. The server files it
// as snapshot.version.unsupported at the file, and its message is the finding's.
type VersionError struct {
	Got string
	// raw is the declared value's JSON text when it is not a string, so the message
	// does not quote a number as if it were the string.
	raw string
}

func (e *VersionError) Error() string {
	declares := "declares no snapshot_version"
	switch {
	case e.raw != "":
		declares = "declares snapshot_version " + e.raw
	case e.Got != "":
		declares = "declares snapshot_version " + strconv.Quote(e.Got)
	}
	return fmt.Sprintf("the snapshot %s; this build reads %q, and nothing converts one", declares, Version)
}

// InvalidError is Unmarshal's refusal of a document whose outer shape is not version 1's:
// Field is the outer key at fault (probes, snapshot_id, observed_at, ctm, or an unknown
// key), empty when the document itself is at fault, and Message names it and says why.
// The server files it as snapshot.invalid at the field, or at the file when Field is
// empty.
type InvalidError struct {
	Field   string
	Message string
}

func (e *InvalidError) Error() string { return e.Message }

// IDMismatchError is Unmarshal's refusal of a document that declares a snapshot_id its
// body does not hash to. The server files it as snapshot.id.mismatch at the file, naming
// the file before the message.
type IDMismatchError struct {
	Declared, Computed string
}

func (e *IDMismatchError) Error() string {
	return fmt.Sprintf("declares snapshot_id %s, but its body hashes to %s; leave snapshot_id out to have it computed",
		e.Declared, e.Computed)
}

// Load reads a snapshot from a file, through Unmarshal.
func Load(path string) (*Snapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading snapshot: %w", err)
	}
	return Unmarshal(data)
}

// Save writes a snapshot in its stored form, to a temporary sibling renamed into place,
// so the file is whole or absent.
func Save(s *Snapshot, path string) error {
	b, err := Marshal(s)
	if err != nil {
		return err
	}
	return writeAtomic(path, b)
}

// writeAtomic writes data to a temporary sibling of path, mode 0644, and renames it into
// place.
func writeAtomic(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".fylgja-snapshot-*")
	if err != nil {
		return fmt.Errorf("writing snapshot: %w", err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if err := writeAndClose(tmp, data); err != nil {
		return fmt.Errorf("writing snapshot: %w", err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("writing snapshot: %w", err)
	}
	return nil
}

// writeAndClose writes data to a temporary file, closes it and gives it mode 0644.
func writeAndClose(f *os.File, data []byte) error {
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Chmod(f.Name(), 0o644)
}
