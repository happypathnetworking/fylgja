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
// Counts because Counts is a comparable struct that tier 2 holds whole reads to, and
// because the count needs the registry: a device's package is the one its platform
// resolves to, not anything the CTM states.
//
// A device no package covers is counted under its platform's name. A read like that is
// refused as platform.unsupported and prints no summary at all, so this is what the line
// would say rather than what it says.
func DevicesByPackage(c *ctm.CTM, reg *psp.Registry) []PackageCount {
	if c == nil {
		return nil
	}
	n := map[string]int{}
	for _, d := range c.Devices {
		id := d.Platform.NOS
		if p, ok := reg.Lookup(d.Platform.NOS); ok {
			id = p.Platform.ID
		}
		n[id]++
	}
	out := make([]PackageCount, 0, len(n))
	for id, devices := range n {
		out = append(out, PackageCount{PSPID: id, Devices: devices})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].PSPID < out[j].PSPID })
	return out
}

// Verified describes what a clean conformance check actually verified: the contract
// version, and each required generic with the kinds implementing it by name. It is
// the success detail of `schema check`.
func (conf *Conformance) Verified() *findings.Verified {
	if conf == nil {
		return nil
	}
	return &findings.Verified{
		ContractVersion: conf.Version,
		Generics:        conf.Generics,
	}
}
