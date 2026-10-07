package lab

import (
	"fmt"
	"strings"
)

// Describe returns the phrase: what the host holds, named for the operator. It is one
// function so that the three surfaces that show it —
// the host.lab.present and host.twin.present messages and the worker's start-up host
// line — embed the identical words for the identical host and cannot drift.
//
// A readable twin.json names the twin: branch, `at` verbatim when the reference was
// pinned, the bundle_id and the run's identities in full, and the node count the record
// holds. Without one, lab fylgja is an orphan, named by the topology path its containers
// carry; a twin directory alone is a leftover. The phrase never carries observed_at or a
// credential (Constitution X). It is empty when the host holds nothing.
func (h HostState) Describe() string {
	deployed := ""
	if len(h.Lab.TopoPaths) > 0 {
		deployed = "; deployed from " + strings.Join(h.Lab.TopoPaths, ", ")
	}
	switch {
	case h.Twin != nil: // (a) and (b): a readable record
		p := "the twin of branch " + h.Twin.Provenance.Branch
		if h.Twin.Provenance.At != "" {
			p += " at " + h.Twin.Provenance.At
		}
		p += fmt.Sprintf(", bundle_id %s, provisioned by run %s %s, %s recorded",
			h.Twin.BundleID, h.Twin.Run.WorkflowID, h.Twin.Run.RunID, plural(len(h.Twin.Nodes), "node"))
		if !h.Lab.Present {
			p += ", but lab " + LabName + " is absent"
		}
		return p
	case h.Lab.Present && !h.TwinDirPresent: // (c)
		return "an orphan: no twin.json records it" + deployed
	case h.Lab.Present && h.TwinReadError != "": // (e)
		return "treated as an orphan: twin.json could not be read (" + h.TwinReadError + ")" + deployed
	case h.Lab.Present: // (d)
		return "an orphan: no twin.json records it (a run cut short before it recorded the twin)" + deployed
	case h.TwinDirPresent && h.TwinReadError != "": // (g)
		return "a leftover twin directory: twin.json could not be read (" + h.TwinReadError + "), and lab " + LabName + " is absent"
	case h.TwinDirPresent: // (f)
		return "a leftover twin directory: no twin.json and no lab " + LabName
	}
	return "" // (h)
}
