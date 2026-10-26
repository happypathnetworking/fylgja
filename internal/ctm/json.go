package ctm

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

// CanonicalLinkID builds a link's identifier from its endpoints: the two endpoint
// identifiers sorted and joined. Deterministic regardless of which side is listed
// first, so the same physical link always carries the same id.
func CanonicalLinkID(a, b Endpoint) string {
	ids := []string{a.ID(), b.ID()}
	sort.Strings(ids)
	return ids[0] + "|" + ids[1]
}

// Normalize puts a CTM into canonical form: every list sorted by its canonical key,
// defaults filled in. Compilation is
// deterministic because its input is normalized first — the compiler never has to
// care what order intent arrived in.
//
// Normalize does not validate: a CTM can be canonical and still wrong. That is
// internal/validate's job.
func Normalize(c *CTM) {
	if c.CTMVersion == "" {
		c.CTMVersion = Version
	}
	// devices and links are required arrays in the contract: an empty topology is
	// [] and never null, so a reader never has to tell "none" from "not recorded".
	if c.Devices == nil {
		c.Devices = []Device{}
	}
	if c.Links == nil {
		c.Links = []Link{}
	}
	// The fidelity list is required too: [] says the reader approximated and omitted
	// nothing, which a missing list could not say. Filled here for a CTM built in memory,
	// as the reader's is; Unmarshal refuses a file that leaves it out, as one that leaves
	// out its version.
	if c.Envelope.Fidelity == nil {
		c.Envelope.Fidelity = []FidelityRow{}
	}
	sort.SliceStable(c.Envelope.Fidelity, func(x, y int) bool {
		a, b := c.Envelope.Fidelity[x], c.Envelope.Fidelity[y]
		if a.Disposition != b.Disposition {
			return a.Disposition < b.Disposition
		}
		return a.Object < b.Object
	})
	for i := range c.Devices {
		d := &c.Devices[i]
		if d.Provenance == "" {
			d.Provenance = ProvenanceIntent
		}
		for j := range d.Interfaces {
			in := &d.Interfaces[j]
			if in.Provenance == "" {
				in.Provenance = ProvenanceIntent
			}
			if in.Enabled == nil {
				t := true
				in.Enabled = &t
			}
		}
		sort.SliceStable(d.Interfaces, func(x, y int) bool {
			return d.Interfaces[x].Name < d.Interfaces[y].Name
		})
	}
	sort.SliceStable(c.Devices, func(x, y int) bool { return c.Devices[x].Name < c.Devices[y].Name })

	for i := range c.Links {
		l := &c.Links[i]
		if l.Provenance == "" {
			l.Provenance = ProvenanceIntent
		}
		sort.SliceStable(l.Endpoints, func(x, y int) bool {
			return l.Endpoints[x].ID() < l.Endpoints[y].ID()
		})
	}
	sort.SliceStable(c.Links, func(x, y int) bool { return c.Links[x].ID < c.Links[y].ID })
}

// Marshal encodes a CTM as canonical JSON: normalized ordering, fixed field order
// from the struct definitions, two-space indent, LF endings, trailing newline.
func Marshal(c *CTM) ([]byte, error) {
	Normalize(c)
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return nil, err
	}
	return append(b, '\n'), nil
}

// Unmarshal decodes a serialized CTM and normalizes it. Unknown fields are rejected:
// a typo in a fixture should fail loudly rather than be silently ignored.
//
// The version is read first, on its own: a CTM of another version carries fields this
// one does not (a "1" carries contract_version and iftype), and it is refused for its
// version, naming both, rather than for the first field the strict decode trips on.
// Nothing converts one (FR-028). A CTM declaring no version is refused alike: Normalize
// would read it as a "2", a claim the file never made.
//
// The fidelity list is required of a file: Normalize fills a missing one with [] for a
// CTM built in memory, as the reader's is, and [] says the reader approximated and
// omitted nothing, which a file leaving the list out never said (Constitution X). So a
// file's list is held here, before Normalize fills it and before validation could see
// it was missing.
func Unmarshal(data []byte) (*CTM, error) {
	var head struct {
		CTMVersion string `json:"ctm_version"`
	}
	if err := json.Unmarshal(data, &head); err != nil {
		return nil, fmt.Errorf("decoding CTM: %w", err)
	}
	if head.CTMVersion != Version {
		return nil, &VersionError{Got: head.CTMVersion}
	}
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.DisallowUnknownFields()
	var c CTM
	if err := dec.Decode(&c); err != nil {
		return nil, fmt.Errorf("decoding CTM: %w", err)
	}
	// Absent and null both decode to a nil slice; [] to an empty one.
	if c.Envelope.Fidelity == nil {
		return nil, &MissingError{Field: "envelope.fidelity", Message: "envelope.fidelity, the reader's fidelity list, is not recorded: " +
			"[] says the reader approximated and omitted nothing, which a list left out cannot say"}
	}
	Normalize(&c)
	return &c, nil
}

// VersionError is Unmarshal's refusal of a CTM of another version, or of none: Got is the
// version the file declares, empty when it declares none, and Version the one this build
// reads. twin compile files it as ctm.version.unsupported at the file, where any other
// decoding failure is the operation's (017).
type VersionError struct {
	Got string
}

func (e *VersionError) Error() string {
	if e.Got == "" {
		return fmt.Sprintf("no ctm_version, expected %q", Version)
	}
	return fmt.Sprintf("unsupported ctm_version %q, expected %q", e.Got, Version)
}

// MissingError is Unmarshal's refusal of a CTM file that leaves out a field the contract
// requires and Normalize would otherwise fill: Field is its path in the CTM, and Message
// names it and says why it cannot be filled. twin compile files it as
// data.required.missing at the field, as validation names an empty envelope field (017).
type MissingError struct {
	Field   string
	Message string
}

func (e *MissingError) Error() string { return e.Message }

// Load reads a serialized CTM from a file.
func Load(path string) (*CTM, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading CTM: %w", err)
	}
	return Unmarshal(data)
}

// Save writes a CTM as canonical JSON.
func Save(c *CTM, path string) error {
	b, err := Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o644)
}
