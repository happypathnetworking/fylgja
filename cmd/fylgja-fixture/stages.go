//go:build fixture

package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// writeFlags are the stages' tier-2 changes (020, T021): the writes internal/stages' and
// internal/stage's contract tests made through testsupport, which the orchestrator's tier 2
// makes through this tool, since internal/testsupport is not ported. -update-stage is not
// among them: it edits a proposed change's stage, and goes with the proposal flags.
type writeFlags struct {
	serial, describe, cableStatus, reEnd, deleteLink, virtual, tag string
	rebase                                                         bool
}

// given names the write flags set, in the order their help lists them.
func (f writeFlags) given() []string {
	var out []string
	for _, g := range []struct {
		name string
		set  bool
	}{{"set-serial", f.serial != ""}, {"describe", f.describe != ""}, {"set-cable-status", f.cableStatus != ""},
		{"re-end-cable", f.reEnd != ""}, {"delete-link", f.deleteLink != ""}, {"add-virtual-interface", f.virtual != ""},
		{"tag-devices", f.tag != ""}, {"rebase", f.rebase}} {
		if g.set {
			out = append(out, "-"+g.name)
		}
	}
	return out
}

// deviceFlags are -add-device's own: what AddDevice gives a device beyond its name and
// ports, and whether it joins the group the definition renders for. Each is refused without
// -add-device.
type deviceFlags struct {
	platform, tag, management string
	group                     bool
}

// given names the device flags set.
func (f deviceFlags) given() []string {
	var out []string
	for _, g := range []struct {
		name string
		set  bool
	}{{"device-platform", f.platform != ""}, {"device-tag", f.tag != ""},
		{"device-management", f.management != ""}, {"device-group", f.group}} {
		if g.set {
			out = append(out, "-"+g.name)
		}
	}
	return out
}

// throwawayOnly refuses, before any request, the fixture and a branch outside the test
// prefix, as every change flag since 020 does.
func throwawayOnly(flagName, branch string) error {
	if branch == testsupport.FixtureBranch {
		return fmt.Errorf("%s refuses branch %s: the fixture is written once and never changed; "+
			"seed a throwaway branch and name it with -branch", flagName, branch)
	}
	if !strings.HasPrefix(branch, testsupport.TestBranchPrefix) {
		return fmt.Errorf("%s refuses branch %s: every branch it changes begins %s; "+
			"seed a throwaway branch and name it with -branch", flagName, branch, testsupport.TestBranchPrefix)
	}
	return nil
}

// port parses <device>:<name>, naming the flag when it is not of that form.
func port(flagName, value string) (string, string, error) {
	d, p, ok := strings.Cut(value, ":")
	if !ok || d == "" || p == "" {
		return "", "", fmt.Errorf("%s takes <device>:<name>, got %q", flagName, value)
	}
	return d, p, nil
}

// names parses a comma-separated list of device names, none empty.
func names(flagName, form, value string) ([]string, error) {
	list := strings.Split(value, ",")
	for _, n := range list {
		if n == "" || strings.ContainsAny(n, ": \t/") {
			return nil, fmt.Errorf("%s takes %s, got %q", flagName, form, value)
		}
	}
	return list, nil
}

// write applies the one write flag given. Each is refused, before any request, on the
// fixture and on a branch outside the test prefix, and so is more than one at once, or a
// value not of the flag's form. None renders: -generate follows a write a test wants
// rendered, since Infrahub 1.11.2 regenerates nothing on its own.
func write(branch string, f writeFlags) error {
	given := f.given()
	if len(given) > 1 {
		return fmt.Errorf("%s change a branch one at a time; give one", strings.Join(given, " and "))
	}
	flagName := given[0]
	if err := throwawayOnly(flagName, branch); err != nil {
		return err
	}

	// Every value is parsed before the client is made, so a malformed one sends nothing.
	var devices, ends []string
	var device, name, kind, value string
	var err error
	switch {
	case f.serial != "":
		var list string
		var ok bool
		list, value, ok = strings.Cut(f.serial, "=")
		if !ok || value == "" {
			return fmt.Errorf("-set-serial takes <device>[,<device>...]=<serial>, got %q", f.serial)
		}
		if devices, err = names(flagName, "<device>[,<device>...]=<serial>", list); err != nil {
			return err
		}
	case f.describe != "":
		var what string
		var ok bool
		what, value, ok = strings.Cut(f.describe, "=")
		if kind, name, ok = cut(ok, what); !ok || value == "" {
			return fmt.Errorf("-describe takes device:<name>=<text>, platform:<name>=<text>, manufacturer:<name>=<text> "+
				"or virtual:<device>:<name>=<text>, got %q", f.describe)
		}
		switch kind {
		case "device", "platform", "manufacturer":
		case "virtual":
			if device, name, err = port(flagName, name); err != nil {
				return fmt.Errorf("-describe virtual: takes virtual:<device>:<name>=<text>, got %q", f.describe)
			}
		default:
			return fmt.Errorf("-describe describes a device, a platform, a manufacturer or a virtual interface, got %q", kind)
		}
	case f.cableStatus != "":
		var ok bool
		name, value, ok = strings.Cut(f.cableStatus, "=")
		if !ok || name == "" || value == "" {
			return fmt.Errorf("-set-cable-status takes <label>=<status>, got %q", f.cableStatus)
		}
	case f.reEnd != "":
		at, list, ok := strings.Cut(f.reEnd, "=")
		if !ok || list == "" {
			return fmt.Errorf("-re-end-cable takes <device>:<port>=<device>:<port>[,...], got %q", f.reEnd)
		}
		if device, name, err = port(flagName, at); err != nil {
			return err
		}
		ends = strings.Split(list, ",")
		for _, e := range ends {
			if _, _, err := port(flagName+"'s end", e); err != nil {
				return err
			}
		}
	case f.deleteLink != "":
		if device, name, err = port(flagName, f.deleteLink); err != nil {
			return err
		}
	case f.virtual != "":
		if device, name, err = port(flagName, f.virtual); err != nil {
			return err
		}
	case f.tag != "":
		if devices, err = names(flagName, "<device>[,<device>...]", f.tag); err != nil {
			return err
		}
	}

	c, err := testsupport.NewClient()
	if err != nil {
		return err
	}
	switch {
	case f.serial != "":
		for _, d := range devices {
			if err := c.SetDeviceSerial(branch, d, value); err != nil {
				return err
			}
		}
		fmt.Printf("serial number set to %q on %s on %s; it renders nothing\n", value, strings.Join(devices, ", "), branch)
	case f.describe != "":
		switch kind {
		case "device":
			err = c.SetDeviceDescription(branch, name, value)
		case "platform":
			err = c.SetPlatformDescription(branch, name, value)
		case "manufacturer":
			err = c.SetManufacturerDescription(branch, name, value)
		default:
			err = c.SetVirtualInterfaceDescription(branch, device, name, value)
		}
		if err != nil {
			return err
		}
		fmt.Printf("description of %s set to %q on %s\n", strings.SplitN(f.describe, "=", 2)[0], value, branch)
	case f.cableStatus != "":
		if err := c.SetCableStatus(branch, name, value); err != nil {
			return err
		}
		stamp, err := c.CableStamp(branch, name)
		if err != nil {
			return err
		}
		fmt.Printf("cable %s on %s set to %s, stamped at %s\n", name, branch, value, stamp)
	case f.reEnd != "":
		if err := c.ReEndCable(branch, device, name, ends...); err != nil {
			return err
		}
		fmt.Printf("the cable at %s:%s on %s re-ended to %s\n", device, name, branch, strings.Join(ends, ", "))
	case f.deleteLink != "":
		returned, err := c.DeleteLink(branch, device, name)
		if err != nil {
			return err
		}
		fmt.Printf("the cable at %s:%s on %s deleted, returned at %s\n", device, name, branch,
			returned.Format(time.RFC3339Nano))
	case f.virtual != "":
		if err := c.AddVirtualInterface(branch, device, name); err != nil {
			return err
		}
		fmt.Printf("virtual interface %s added on %s on %s\n", name, device, branch)
	case f.tag != "":
		if err := c.TagDevices(branch, testsupport.FixtureTag, devices...); err != nil {
			return err
		}
		fmt.Printf("tag %s added to %s on %s\n", testsupport.FixtureTag, strings.Join(devices, ", "), branch)
	default:
		began := time.Now()
		if err := c.Rebase(branch); err != nil {
			return err
		}
		fmt.Printf("branch %s rebased on %s in %.0fs\n", branch, testsupport.DefaultBranch, time.Since(began).Seconds())
	}
	return nil
}

// cut splits <kind>:<rest> when ok, reporting whether both halves are there.
func cut(ok bool, what string) (string, string, bool) {
	if !ok {
		return "", "", false
	}
	kind, rest, found := strings.Cut(what, ":")
	return kind, rest, found && kind != "" && rest != ""
}

// stageFields parses -update-stage's <label>:<field>=<value> into the stage's label and the
// one field UpdateStage writes: label, as_of or description.
func stageFields(value string) (string, map[string]any, error) {
	label, assignment, ok := strings.Cut(value, ":")
	field, v, set := strings.Cut(assignment, "=")
	if !ok || !set || label == "" || v == "" {
		return "", nil, fmt.Errorf("-update-stage takes <label>:<field>=<value>, got %q", value)
	}
	switch field {
	case "label", "as_of", "description":
	default:
		return "", nil, fmt.Errorf("-update-stage edits a stage's label, as_of or description, got %q", field)
	}
	return label, map[string]any{field: v}, nil
}

// updateStage edits one stage of a throwaway branch's open proposed change, found by its
// label, and prints the stage's id: the edits a test makes to see what a twin built from it
// holds (D-047).
func updateStage(c *testsupport.Client, branch, id, label string, fields map[string]any) error {
	rows, err := c.StagesOf(id)
	if err != nil {
		return err
	}
	var stageID string
	for _, r := range rows {
		if r.Label == label {
			stageID = r.ID
		}
	}
	if stageID == "" {
		return fmt.Errorf("proposed change %s on %s has no stage labelled %q", id, branch, label)
	}
	if err := c.UpdateStage(stageID, fields); err != nil {
		return err
	}
	for field, v := range fields {
		fmt.Printf("stage %s/%s (stage id %s) on proposed change %s: %s set to %v\n", branch, label, stageID, id, field, v)
	}
	return nil
}
