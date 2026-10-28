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
		{"scope", c.Envelope.Scope, "the scope intent was read under is not recorded"},
		{"mapping.reader", c.Envelope.Mapping.Reader, "the reader that mapped intent is not recorded"},
		{"mapping.model", c.Envelope.Mapping.Model, "the model the reader read is not recorded"},
		{"mapping.version", c.Envelope.Mapping.Version, "the version of the model the reader read is not recorded"},
	} {
		if f.value == "" {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, "envelope."+f.name, f.why)
		}
	}
	checkEnvelopeForms(c, list)
}

// checkEnvelopeForms holds the envelope's recorded values to the forms the contracts give
// them, which reach the manifest's provenance and fidelity.read and the twin record
// unchanged (017): a CTM written by hand naming scope fylgja, a reader Infrahub DCIM or a
// row of disposition bogus would otherwise compile to a manifest its contract refuses. A
// value left empty is named once, by checkEnvelope, as not recorded. Rows are named by
// their place in the list as Normalize sorts it, the order the manifest copies.
func checkEnvelopeForms(c *ctm.CTM, list *findings.List) {
	e := c.Envelope
	if e.Scope != "" && !ctm.ValidScope(e.Scope) {
		list.Add(findings.Rejection, findings.RuleRequiredMissing, "envelope.scope", fmt.Sprintf(
			"the scope intent was read under is %q, which is not a scope: the accepted form is tag:<name>, the literal tag: and one word",
			e.Scope))
	}
	if r := e.Mapping.Reader; r != "" && !ctm.ValidReader(r) {
		list.Add(findings.Rejection, findings.RuleRequiredMissing, "envelope.mapping.reader", fmt.Sprintf(
			"the reader that mapped intent is named %q, which is not a reader's name: "+
				"lowercase letters, digits and hyphens, beginning with a letter or a digit", r))
	}
	for i, r := range e.Fidelity {
		object := fmt.Sprintf("envelope.fidelity[%d]", i)
		what := fmt.Sprintf("fidelity row %d", i)
		if r.Object != "" {
			what += " (" + r.Object + ")"
		}
		if r.Disposition != ctm.FidelityApproximated && r.Disposition != ctm.FidelityOmitted {
			list.Add(findings.Rejection, findings.RuleRequiredMissing, object+".disposition", fmt.Sprintf(
				"%s has disposition %q: a row is %s or %s", what, r.Disposition, ctm.FidelityApproximated, ctm.FidelityOmitted))
		}
		for _, f := range []struct{ name, value string }{{"object", r.Object}, {"source", r.Source}, {"reason", r.Reason}} {
			if f.value == "" {
				list.Add(findings.Rejection, findings.RuleRequiredMissing, object+"."+f.name, what+" records no "+f.name)
			}
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
		if !checkDeviceName(d, seen, list) {
			continue
		}

		p, ok := reg.LookupID(d.Platform.Package)
		if !ok {
			// Missing support is data that has not been written, not a code path
			// (Constitution II). Say which package, so the fix is obvious. A reader
			// writes the package a device's platform matched, so a CTM naming none, or
			// one this build lacks, was written by hand or by another build.
			list.Add(findings.Rejection, findings.RulePlatformUnsupported, d.Name, compiler.UnsupportedPackage(d.Platform.Package, reg))
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

// checkDeviceName refuses a device with no name and a second device of a name, the two
// faults of a device's name, and reports whether d has a name of its own to check further
// by. seen holds the names met so far.
func checkDeviceName(d ctm.Device, seen map[string]bool, list *findings.List) bool {
	if d.Name == "" {
		list.Add(findings.Rejection, findings.RuleRequiredMissing, "device",
			"a device has no name")
		return false
	}
	if seen[d.Name] {
		list.Add(findings.Rejection, findings.RuleDeviceNameDuplicate, d.Name,
			"two devices share this name; a node name must be unique")
		return false
	}
	seen[d.Name] = true
	return true
}

// addNamelessInterface refuses an interface of device with no name, naming the device.
func addNamelessInterface(device string, list *findings.List) {
	list.Add(findings.Rejection, findings.RuleRequiredMissing, device,
		"an interface has no name")
}

// checkInterfaces validates one device's interfaces.
func checkInterfaces(d ctm.Device, prof *psp.Profile, pspID string, list *findings.List) {
	// What the profile cannot map, decided by the one function the compiler also calls,
	// so a CTM that reads clean compiles and each refusal is worded alike. A refusal
	// naming one interface is filed with that interface's other findings; any other is
	// filed after them.
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

	for _, in := range d.Interfaces {
		object := d.Name + ":" + in.Name
		if in.Name == "" {
			addNamelessInterface(d.Name, list)
			continue
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

// checkLinks validates every link's shape and endpoints, then holds the links and each
// interface's link to one another by the one function the compiler's guard also calls.
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
			if dev.Interface(e.Interface) == nil {
				list.Add(findings.Rejection, findings.RuleRequiredMissing, l.ID, fmt.Sprintf(
					"endpoint names interface %q, which is not on %s", e.Interface, e.Device))
			}
		}
	}
	*list = append(*list, compiler.LinkTerminations(c)...)
}
