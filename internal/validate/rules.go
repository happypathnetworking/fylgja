// Package validate checks intent before anything is compiled.
//
// Every rule here runs against the CTM, not against Infrahub. That is deliberate: a
// fixture loaded from a file bypasses Infrahub's own constraints entirely, so rules
// Infrahub would have enforced must still exist in Fylgja — and running them on the
// CTM means a fixture and a live branch fail identically. It is also
// the only arrangement in which `intent read` and `twin compile` provably share one
// validation pass.
//
// Findings are gathered, never returned early: an operator fixing intent wants every
// problem in one pass, not one problem per attempt.
package validate

import (
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// checkEnvelope verifies the CTM records what it was read against. `at` is not among
// these: it is present iff the operator pinned one, and inventing a requirement for it
// would refuse every unpinned read.
func checkEnvelope(c *ctm.CTM, list *findings.List) {
	for _, f := range []struct {
		name, value, why string
	}{
		{"branch", c.Envelope.Branch, "the branch intent was read from is not recorded"},
		{"observed_at", c.Envelope.ObservedAt, "the instant intent was read is not recorded"},
		{"schema_hash", c.Envelope.SchemaHash, "the schema intent was read against is not recorded"},
		{"contract_version", c.Envelope.ContractVersion, "the contract version intent conforms to is not recorded"},
	} {
		if f.value == "" {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, "envelope."+f.name, f.why)
		}
	}
}

// checkDevicesPresent rejects a CTM that holds no devices.
//
// An empty read is almost always a wrong `at` — the operator learns that here rather
// than from an empty twin. It is also the one case where the manifest cannot satisfy
// its own contract: fidelity.production_forwarding has no value for zero nodes.
// Shared with `twin compile` so an empty file fails the same
// way an empty read does.
func checkDevicesPresent(c *ctm.CTM, list *findings.List) {
	if len(c.Devices) > 0 {
		return
	}
	where := fmt.Sprintf("branch %q", c.Envelope.Branch)
	object := c.Envelope.Branch
	if object == "" {
		object = "envelope"
	}
	if c.Envelope.At != "" {
		where += fmt.Sprintf(" at %s", c.Envelope.At)
		object += "@" + c.Envelope.At
	}
	list.Add(findings.Rejection, findings.RuleDevicesEmpty, object, fmt.Sprintf(
		"no devices in intent for %s; a twin of nothing cannot be built and has no fidelity to report", where))
}

// checkDevices validates each device and its interfaces.
func checkDevices(c *ctm.CTM, reg *psp.Registry, list *findings.List) {
	seen := map[string]bool{}
	for _, d := range c.Devices {
		if d.Name == "" {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, "device",
				"a device has no name")
			continue
		}
		if seen[d.Name] {
			list.Add(findings.Rejection, findings.RuleDeviceNameDuplicate, d.Name,
				"two devices share this name; a node name must be unique")
			continue
		}
		seen[d.Name] = true

		if d.Platform.NOS == "" {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, d.Name,
				"device has no platform")
			continue
		}
		p, ok := reg.Lookup(d.Platform.NOS)
		if !ok {
			// Missing support is data that has not been written, not a code path
			// (Constitution II). Say which platform, so the fix is obvious.
			list.Add(findings.Rejection, findings.RulePlatformUnsupported, d.Name, fmt.Sprintf(
				"no support package for platform %q; supported: %v", d.Platform.NOS, reg.Platforms()))
			continue
		}
		prof, err := psp.NewProfile(p)
		if err != nil {
			list.Add(findings.Rejection, findings.RulePSPSchema, p.Platform.ID, err.Error())
			continue
		}
		checkInterfaces(d, prof, p.Platform.ID, list)
	}
}

// checkInterfaces validates one device's interfaces.
func checkInterfaces(d ctm.Device, prof *psp.Profile, pspID string, list *findings.List) {
	// What the profile cannot map, decided by the one function the compiler also calls,
	// so a CTM that reads clean compiles and each refusal is worded alike. An
	// interface of an iftype no disposition exists for is the survey's Err, named below
	// as interface.iftype.unimplemented. A refusal naming one interface is filed with
	// that interface's other findings; any other is filed after them.
	refusals := map[string]findings.List{}
	var unplaced findings.List
	objects := map[string]bool{}
	for _, in := range d.Interfaces {
		if in.Name != "" {
			objects[d.Name+":"+in.Name] = true
		}
	}
	// An interface with no name has one defect worth reporting, below: it has no name.
	// The survey applies the profile to it anyway and no rule matches an empty string,
	// so it also comes back refused under an object naming no interface. Filing that
	// beside the finding to fix would give two rejections for one mistake, which is not
	// what M5 did, so it is dropped here rather than in the survey, which both
	// callers share.
	nameless := d.Name + ":"
	survey := compiler.SurveyDevice(d, prof, pspID)
	for _, f := range survey.Refusals {
		switch {
		case f.Object == nameless:
		case objects[f.Object]:
			refusals[f.Object] = append(refusals[f.Object], f)
		default:
			unplaced = append(unplaced, f)
		}
	}

	names := map[string]bool{}
	for _, in := range d.Interfaces {
		names[in.Name] = true
	}
	for _, in := range d.Interfaces {
		object := d.Name + ":" + in.Name
		if in.Name == "" {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, d.Name,
				"an interface has no name")
			continue
		}
		switch {
		case in.Iftype == "":
			list.Add(findings.Rejection, findings.RuleRequiredMissing, object,
				"interface has no iftype")
		case !ctm.KnownIftypes[in.Iftype]:
			list.Add(findings.Rejection, findings.RuleIftypeUnimplemented, object, fmt.Sprintf(
				"iftype %q is not in the contract", in.Iftype))
		case !ctm.ImplementedIftypes[in.Iftype]:
			// The contract declares the vocabulary; the compiler implements a subset.
			// An unimplemented kind rejects explicitly rather than falling through to
			// physical, which would wire a twin nobody asked for (D-004).
			list.Add(findings.Rejection, findings.RuleIftypeUnimplemented, object, fmt.Sprintf(
				"iftype %q is reserved in the contract but not implemented at M1", in.Iftype))
		}

		// `mgmt_only` marks an out-of-band *port*. On anything that is not a port it
		// says nothing meaningful, so it is a defect rather than a hint.
		if in.MgmtOnly && in.Iftype != "" && in.Iftype != ctm.IftypePhysical {
			list.Add(findings.Rejection, findings.RuleMgmtOnlyIftype, object, fmt.Sprintf(
				"mgmt_only is set on an interface of iftype %q; only a physical port can be out-of-band", in.Iftype))
		}

		if in.Parent != "" && !names[in.Parent] {
			list.Add(findings.Rejection, findings.RuleParentMissing, object, fmt.Sprintf(
				"parent %q is not an interface on %s", in.Parent, d.Name))
		}

		*list = append(*list, refusals[object]...)
		delete(refusals, object)
	}
	*list = append(*list, unplaced...)
	// What the device's configuration artifact names that the twin does not represent
	// under that name: warnings, filed after this device's refusals, worded by the one
	// function the compiler also calls. They never reject, so a read that raises
	// only these writes its CTM and exits 0.
	*list = append(*list, compiler.ArtifactNames(d, survey)...)
}

// checkLinks validates every link's shape and endpoints.
func checkLinks(c *ctm.CTM, list *findings.List) {
	for _, l := range c.Links {
		if len(l.Endpoints) != 2 {
			list.Add(findings.Rejection, findings.RuleLinkEndpointsCount, l.ID, fmt.Sprintf(
				"link has %d endpoints; a link connects exactly two interfaces", len(l.Endpoints)))
			continue
		}
		a, b := l.Endpoints[0], l.Endpoints[1]
		if a.Device == b.Device {
			list.Add(findings.Rejection, findings.RuleLinkEndpointsSameDev, l.ID,
				"both endpoints are on the same device")
		}
		for _, e := range l.Endpoints {
			dev := c.Device(e.Device)
			if dev == nil {
				list.Add(findings.Rejection, findings.RuleRequiredMissing, l.ID, fmt.Sprintf(
					"endpoint names device %q, which is not in intent", e.Device))
				continue
			}
			in := dev.Interface(e.Interface)
			if in == nil {
				list.Add(findings.Rejection, findings.RuleRequiredMissing, l.ID, fmt.Sprintf(
					"endpoint names interface %q, which is not on %s", e.Interface, e.Device))
				continue
			}
			// Only a physical port can be cabled. A loopback has nothing to plug in.
			if in.Iftype != ctm.IftypePhysical {
				list.Add(findings.Rejection, findings.RuleLinkEndpointIftype, l.ID, fmt.Sprintf(
					"endpoint %s has iftype %q; only a physical interface can be cabled", e.ID(), in.Iftype))
			}
		}
	}
}
