package compiler

import (
	"fmt"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// DeviceSurvey is what applying a platform's mapping profile to one device decided:
// a row for every interface, what was omitted and why, and what cannot be built at all.
type DeviceSurvey struct {
	Rows      []MappingRow
	Omissions []Omission
	// Lossy is this device's part of the fidelity record: every interface a lossy rule
	// mapped, and every interface whose port another interface of the device renders to.
	Lossy []LossyMapping
	// Refusals are rejections: validation files every one of them, and the compiler
	// reports them as its guards, word for word, and builds nothing.
	Refusals findings.List
	// Err is an interface no disposition exists for: an iftype validation rejects
	// before compilation. Validation has already named it; the compiler fails loudly
	// rather than guess (D-004). The survey carries on past it, so validation still
	// hears every other interface's refusal.
	Err error
}

// SurveyDevice decides every interface on one device through the platform's profile.
//
// One function, called by validation and by the compiler, so a CTM that reads clean
// compiles, and a refusal is worded the same whichever raised it.
//
// Wiring is derived here, never declared in the contract: intent says what an interface
// *is* (`iftype`) and how it is used (`mgmt_only`), and the compiler decides what that
// means for a twin. Putting the decision in the schema would push Fylgja's
// implementation into someone else's model (D-003).
//
// The translation is data: the rules come from the platform's support package, and
// this code never branches on which platform it is holding (Constitution II). pspID is
// the package's platform id, for the messages that name its profile.
func SurveyDevice(d ctm.Device, prof *psp.Profile, pspID string) DeviceSurvey {
	var s DeviceSurvey
	s.Rows = make([]MappingRow, 0, len(d.Interfaces))
	var placed []placement
	managementTaken := false

	for _, in := range d.Interfaces {
		enabled := in.IsEnabled()
		row := MappingRow{Device: d.Name, Interface: in.Name, Iftype: in.Iftype, MgmtOnly: in.MgmtOnly, Enabled: &enabled}
		object := d.Name + ":" + in.Name

		switch {
		case in.MgmtOnly:
			// A node has exactly one management connection. Intent may describe more
			// than one out-of-band port; the rest are recorded rather than invented.
			if managementTaken {
				row.Disposition = DispOmitted
				s.Omissions = append(s.Omissions, Omission{findings.RuleOmitMgmtExtra, object, reasonExtraMgmt})
				break
			}
			managementTaken = true
			// Never placed for sharing: a data rule that can render the management port
			// is refused when its package loads, so no other row lands here.
			out := prof.Apply(in.Name, true)
			port := out.Port
			row.Port, row.NodeName, row.Disposition = &port, nodeName(out), DispManagement

		case in.Iftype == ctm.IftypeLoopback:
			// Configured by the platform, never cabled. It has no node port, because a
			// loopback is not a port.
			row.Disposition = DispConfiguredNotCabled

		case in.Iftype == ctm.IftypePhysical:
			out := prof.Apply(in.Name, false)
			if out.Kind != psp.Mapped {
				row.Disposition = DispOmitted
				s.unmappable(object, pspID, out, in.Link != "")
				break
			}
			port := out.Port
			row.Port, row.NodeName = &port, nodeName(out)
			if in.Link != "" {
				row.Disposition = DispCabled
			} else {
				row.Disposition = DispConfiguredNotCabled
			}
			placed = append(placed, placement{row: len(s.Rows), out: out, cabled: in.Link != ""})

		default:
			// Validation rejects unimplemented kinds before compilation, so reaching
			// here means the two disagree.
			if s.Err == nil {
				s.Err = fmt.Errorf("interface %s: unhandled iftype %q reached the compiler", object, in.Iftype)
			}
			continue
		}
		s.Rows = append(s.Rows, row)
	}
	s.share(d.Name, placed)
	s.breakout(d, placed)
	// Both callers report the refusals in one order: validation files each beside its
	// interface's other findings, and the compiler returns them as they stand.
	sort.SliceStable(s.Refusals, func(i, j int) bool {
		a, b := s.Refusals[i], s.Refusals[j]
		if a.Object != b.Object {
			return a.Object < b.Object
		}
		return a.Rule < b.Rule
	})
	return s
}

// unmappable decides an interface the profile gave no port. Only a
// name a rule matched out of range and no link touches is omitted: the rule says the
// node has no such port, so there is nothing of it to build. Every other case is a
// refusal. A cabled one would lose a connection silently. One no rule matches
// is a gap in the profile or a mistake in intent, and guessing which would be the
// silent drop this code exists to prevent.
func (s *DeviceSurvey) unmappable(object, pspID string, out psp.Outcome, cabled bool) {
	switch {
	case out.Kind == psp.OutOfRange && !cabled:
		s.Omissions = append(s.Omissions, Omission{findings.RuleOmitInterfaceUnmappable, object,
			fmt.Sprintf("rule %s matched, but {%s} is %s, outside its range %d..%d; no such port on the node",
				out.Rule, out.Placeholder, out.Value, out.Range[0], out.Range[1])})
	case out.Kind == psp.OutOfRange:
		s.Refusals.Add(findings.Rejection, findings.RuleUnmappableLinked, object, fmt.Sprintf(
			"rule %s matched this production name, but {%s} is %s, outside its range %d..%d, and it terminates a link",
			out.Rule, out.Placeholder, out.Value, out.Range[0], out.Range[1]))
	case cabled:
		s.Refusals.Add(findings.Rejection, findings.RuleUnmappableLinked, object, fmt.Sprintf(
			"no rule of the %s profile matches this production name (tried: %s), and it terminates a link",
			pspID, strings.Join(out.Tried, ", ")))
	default:
		s.Refusals.Add(findings.Rejection, findings.RuleInterfaceRuleUnmatched, object, fmt.Sprintf(
			"no rule of the %s profile matches this production name (tried: %s); the profile or the intent must be fixed",
			pspID, strings.Join(out.Tried, ", ")))
	}
}

// placement is one row the profile gave a port, with what decided it. Sharing and the
// lossy record are decided from these once every interface of the device is applied.
type placement struct {
	row    int // index into DeviceSurvey.Rows
	out    psp.Outcome
	cabled bool
}

// share groups a device's ports and decides what more than one interface on one port
// means.
//
// Several interfaces render to one port when a rule drops a placeholder (many-to-one, a
// collapsing breakout) or when two rules render alike. With two or more of them cabled,
// the twin would cable one port twice, and no bundle is built; the refusal names
// every interface that lands on the port, the uncabled ones too. With exactly one
// cabled, it holds the port and every other is omitted and recorded: the twin has one
// port where production has several interfaces, and says which. With none cabled, every
// one keeps the port as configured-not-cabled, and the sharing is recorded. Either way
// each member is in the lossy record with every other member beside it, as is every
// interface a lossy rule mapped, though it shares nothing in this intent: the rule is
// still lossy.
//
// Groups are built from the rows in name order, since both callers normalize the CTM
// first, so an intent listed in another order decides the same things.
func (s *DeviceSurvey) share(device string, placed []placement) {
	groups := map[string][]placement{}
	var ports []string
	for _, p := range placed {
		if _, ok := groups[p.out.Port]; !ok {
			ports = append(ports, p.out.Port)
		}
		groups[p.out.Port] = append(groups[p.out.Port], p)
	}

	for _, port := range ports {
		members := groups[port]
		var holders []placement
		for _, m := range members {
			if m.cabled {
				holders = append(holders, m)
			}
		}
		if len(holders) > 1 {
			s.Refusals.Add(findings.Rejection, findings.RuleInterfacePortCollision, device+":"+port, fmt.Sprintf(
				"port %s on %s would be cabled %s: %s %s land on it%s; a bundle whose links cable one port twice is never produced",
				port, device, times(len(holders)), s.named(holders), bothOrAll(len(holders)), s.alsoUncabled(members)))
		}
		if len(members) > 1 && len(holders) == 1 {
			h := holders[0]
			for _, m := range members {
				if m.row == h.row {
					continue
				}
				row := &s.Rows[m.row]
				row.Port, row.NodeName, row.Disposition = nil, nil, DispOmitted
				s.Omissions = append(s.Omissions, Omission{findings.RuleOmitInterfaceShared, device + ":" + row.Interface,
					fmt.Sprintf("port %s is held by cabled %s (rule %s); this interface maps to it under rule %s and is not represented",
						port, s.Rows[h.row].Interface, h.out.Rule, m.out.Rule)})
			}
		}

		for _, m := range members {
			if !m.out.Lossy && len(members) == 1 {
				continue
			}
			entry := LossyMapping{Device: device, Interface: s.Rows[m.row].Interface, Port: port,
				NodeName: m.out.NodeName, Rule: m.out.Rule, Lossy: m.out.Lossy, Shares: []Share{}}
			for _, o := range members {
				if o.row != m.row {
					entry.Shares = append(entry.Shares, Share{Interface: s.Rows[o.row].Interface, Rule: o.out.Rule, Cabled: o.cabled})
				}
			}
			s.Lossy = append(s.Lossy, entry)
		}
	}
}

// breakout refuses a breakout parent cabled beside a cabled child: no
// platform cables a broken-out port and one of its lanes at once, so the twin could
// honour only one of the two links intent asks for. The parent is the name the
// child's rule renders from the child's own values; intent's parent field is not
// consulted (D-004). One finding per parent, naming every cabled child.
func (s *DeviceSurvey) breakout(d ctm.Device, placed []placement) {
	cabled := map[string]bool{}
	for _, in := range d.Interfaces {
		if in.Link != "" {
			cabled[in.Name] = true
		}
	}
	children := map[string][]placement{}
	var parents []string
	for _, p := range placed {
		if p.out.Parent == "" || !p.cabled || !cabled[p.out.Parent] {
			continue
		}
		if _, ok := children[p.out.Parent]; !ok {
			parents = append(parents, p.out.Parent)
		}
		children[p.out.Parent] = append(children[p.out.Parent], p)
	}
	for _, parent := range parents {
		kids := children[parent]
		noun := "child"
		if len(kids) > 1 {
			noun = "children"
		}
		s.Refusals.Add(findings.Rejection, findings.RuleInterfaceBreakoutParentCabled, d.Name+":"+parent, fmt.Sprintf(
			"breakout parent %s is cabled beside its cabled %s %s; no platform cables a broken-out port and its child at once",
			parent, noun, s.named(kids)))
	}
}

// named lists placed interfaces as the refusals name them, each with the rule that
// decided it, in name order (the rows are, since both callers normalize the CTM):
// "a (rule r)", "a (rule r) and b (rule s)", "a (rule r), b (rule s) and c (rule t)".
func (s *DeviceSurvey) named(ps []placement) string {
	parts := make([]string, len(ps))
	for i, p := range ps {
		parts[i] = fmt.Sprintf("%s (rule %s)", s.Rows[p.row].Interface, p.out.Rule)
	}
	if len(parts) == 1 {
		return parts[0]
	}
	return strings.Join(parts[:len(parts)-1], ", ") + " and " + parts[len(parts)-1]
}

// alsoUncabled names the members of a collided group that no link touches, so the
// refusal names every interface that lands on the port and not only the cabled ones
// that collided. They are not themselves the defect — each would have been
// omitted and recorded had one interface held the port — but an author reading the
// message is deciding what to do with the port, and the rest of what renders to it is
// part of that. A group with no uncabled member adds nothing.
func (s *DeviceSurvey) alsoUncabled(members []placement) string {
	var rest []placement
	for _, m := range members {
		if !m.cabled {
			rest = append(rest, m)
		}
	}
	if len(rest) == 0 {
		return ""
	}
	verb := "lands"
	if len(rest) > 1 {
		verb = "land"
	}
	return fmt.Sprintf("; %s also %s on it, uncabled", s.named(rest), verb)
}

func times(n int) string {
	if n == 2 {
		return "twice"
	}
	return fmt.Sprintf("%d times", n)
}

func bothOrAll(n int) string {
	if n == 2 {
		return "both"
	}
	return "all"
}

// nodeName is what a row records as the node's name for its port: the rendered name
// where it differs from the production name, and nothing where the node calls the port
// as production does.
// nodeName is the node's own name for a rendered port, for a row that has one. From
// bundle "3" it is written on every such row, equal to the production name where the
// platform keeps it: M6 wrote it only where it differed, so that a platform naming its
// ports as production does left its bundles byte-identical (D-025, now expired).
//
// A row with no port never calls this: its name is nil, which is not the empty string.
func nodeName(out psp.Outcome) *string {
	name := out.NodeName
	return &name
}

// SurveyCounts is the lossy record in two numbers, for the operator: its
// entries, and the distinct ports of a device that more than one interface renders to.
type SurveyCounts struct {
	LossyMappings int
	SharedPorts   int
}

// Survey counts what the profiles make of an intent before any bundle exists, for
// `intent read`'s summary. It is pure, and it runs the survey Compile runs, so its counts
// are the ones the bundle's fidelity.lossy will carry (TestSurveyAgreesWithTheManifest).
// A device whose platform has no package, or whose profile does not build, counts
// nothing: the read has refused it before any summary is written.
func Survey(c *ctm.CTM, reg *psp.Registry) SurveyCounts {
	ctm.Normalize(c)
	var entries []LossyMapping
	for _, d := range c.Devices {
		p, ok := reg.Lookup(d.Platform.NOS)
		if !ok {
			continue
		}
		prof, err := psp.NewProfile(p)
		if err != nil {
			continue
		}
		entries = append(entries, SurveyDevice(d, prof, p.Platform.ID).Lossy...)
	}
	return countLossy(entries)
}

// LossyCounts counts a bundle's lossy record as Survey counts intent's, for a dry run,
// which has only the bundle. A "2" bundle written before the record existed counts 0
// and 0, which is what it says by carrying none.
func (m *Manifest) LossyCounts() SurveyCounts {
	return countLossy(m.Fidelity.Lossy)
}

func countLossy(entries []LossyMapping) SurveyCounts {
	shared := map[string]bool{}
	for _, e := range entries {
		if len(e.Shares) > 0 {
			shared[e.Device+":"+e.Port] = true
		}
	}
	return SurveyCounts{LossyMappings: len(entries), SharedPorts: len(shared)}
}
