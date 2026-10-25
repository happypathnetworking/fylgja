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
	// nothing, which a missing list could not say.
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
// Nothing converts one (FR-028).
func Unmarshal(data []byte) (*CTM, error) {
	var head struct {
		CTMVersion string `json:"ctm_version"`
	}
	if err := json.Unmarshal(data, &head); err != nil {
		return nil, fmt.Errorf("decoding CTM: %w", err)
	}
	if head.CTMVersion != "" && head.CTMVersion != Version {
		return nil, fmt.Errorf("unsupported ctm_version %q, expected %q", head.CTMVersion, Version)
	}
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.DisallowUnknownFields()
	var c CTM
	if err := dec.Decode(&c); err != nil {
		return nil, fmt.Errorf("decoding CTM: %w", err)
	}
	Normalize(&c)
	return &c, nil
}

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
