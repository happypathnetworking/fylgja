package intent

import (
	"sort"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Counts describes the size of what was read, for the success line.
//
// "No findings" on its own is a weak result: it reads the same whether every rule ran
// or none did. Saying how many devices, interfaces and links were read makes a clean
// result legible evidence rather than an absence of complaint.
type Counts struct {
	Devices    int
	Interfaces int
	Links      int
	// Artifacts is how many devices came back with their configuration (M5). It is the
	// count of devices, on a clean read, and saying so is the only positive evidence
	// that the twin will run what production runs rather than bootstrap alone.
	Artifacts int
	// CablesOmitted is how many cables the read reached and could not place (017; R-05):
	// each is a row of the envelope's fidelity list, so a read that left cables out says so
	// on its success line and not only in its findings.
	CablesOmitted int
}

// Summarize counts what a read produced.
func Summarize(c *ctm.CTM) Counts {
	if c == nil {
		return Counts{}
	}
	n := Counts{Devices: len(c.Devices), Links: len(c.Links)}
	for _, d := range c.Devices {
		n.Interfaces += len(d.Interfaces)
		if d.Artifact != nil {
			n.Artifacts++
		}
	}
	for _, r := range c.Envelope.Fidelity {
		if r.Disposition == ctm.FidelityOmitted && r.Source == cableSource {
			n.CablesOmitted++
		}
	}
	return n
}

// PackageCount is how many of a read's devices one support package covers.
type PackageCount struct {
	PSPID   string
	Devices int
}

// DevicesByPackage counts the read's devices per support package, in package id order.
//
// A twin of one platform is the same sentence with one entry, so the reader never has to
// know whether this read was mixed to know what the line means. It is kept apart from
// Counts because Counts is a comparable struct that tier 2 holds whole reads to. A
// device's package is the one its platform matched, which CTM 2 states
// (platform.package).
//
// The read refuses a device no package matches (platform.unmatched), so no read's line
// counts one. A hand-written CTM can still name a package this build lacks; it is counted
// under the name it gives, and validation refuses it as platform.unsupported.
func DevicesByPackage(c *ctm.CTM, reg *psp.Registry) []PackageCount {
	if c == nil {
		return nil
	}
	n := map[string]int{}
	for _, d := range c.Devices {
		n[d.Platform.Package]++
	}
	out := make([]PackageCount, 0, len(n))
	for id, devices := range n {
		out = append(out, PackageCount{PSPID: id, Devices: devices})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].PSPID < out[j].PSPID })
	return out
}

// Verified describes what a clean conformance check actually verified: the library and
// its commit, and each kind the mapping reads with its fields by name. It is the success
// detail of `schema check`.
func (conf *Conformance) Verified() *findings.Verified {
	if conf == nil {
		return nil
	}
	return &findings.Verified{
		Model:   conf.Model,
		Version: conf.Version,
		Kinds:   conf.Kinds,
	}
}
