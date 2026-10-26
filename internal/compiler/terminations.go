package compiler

import (
	"fmt"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// LinkTerminations holds each interface's link and the CTM's links to one another.
//
// The bundle reads a cable twice: a row's disposition and the bootstrap's cabled ports
// come from the interface's link, the topology's veths from the links alone. Where the
// two disagree the bundle misdescribes its twin, so every disagreement is refused under
// data.required.missing, as a link's missing endpoint is, naming the link id and the
// device:interface:
//
//   - an interface two links end on, whose port the topology would cable twice;
//   - a link ending on an interface that carries no link, or another link's id, whose row
//     says configured-not-cabled while the topology cables it;
//   - an interface carrying a link id that no link of the list ends on it, whose row says
//     cabled with no veth.
//
// The CTM is the contract any reader writes (D-057), so this holds of a CTM whatever wrote
// it. One function, called by validation and as the compiler's guard, so the two word each
// refusal alike. A link without two endpoints, and an endpoint naming a device or an
// interface not in intent, is refused by validation's own link rules and passed over here,
// as is a duplicated device's second entry: one fault is named once. Expects a normalized
// CTM.
func LinkTerminations(c *ctm.CTM) findings.List {
	var list findings.List

	// The link each interface carries, for the first device of each name, as c.Device
	// finds it.
	carried := map[string]string{}
	var order []string
	seen := map[string]bool{}
	for _, d := range c.Devices {
		if d.Name == "" || seen[d.Name] {
			continue
		}
		seen[d.Name] = true
		for _, in := range d.Interfaces {
			id := d.Name + ":" + in.Name
			if _, ok := carried[id]; ok || in.Name == "" {
				continue
			}
			carried[id] = in.Link
			order = append(order, id)
		}
	}

	// The links that end on each interface, by index, so a link naming one interface at
	// both ends counts once.
	byID := map[string]int{}
	ends := map[string][]int{}
	for i, l := range c.Links {
		if _, ok := byID[l.ID]; !ok {
			byID[l.ID] = i
		}
		if len(l.Endpoints) != 2 {
			continue
		}
		for _, e := range l.Endpoints {
			on, ok := ends[e.ID()]
			if _, known := carried[e.ID()]; !known || ok && on[len(on)-1] == i {
				continue
			}
			ends[e.ID()] = append(on, i)
		}
	}

	for _, id := range order {
		on, link := ends[id], carried[id]
		switch {
		case len(on) > 1:
			ids := make([]string, 0, len(on))
			for _, i := range on {
				ids = append(ids, c.Links[i].ID)
			}
			list.Add(findings.Rejection, findings.RuleRequiredMissing, id, fmt.Sprintf(
				"%s is an endpoint of %d links (%s); %s, and a bundle whose links cable one port twice is never produced",
				id, len(on), strings.Join(ids, ", "), namesItsLink))
		case len(on) == 0 && link != "":
			i, ok := byID[link]
			switch {
			case !ok:
				list.Add(findings.Rejection, findings.RuleRequiredMissing, id, fmt.Sprintf(
					"%s carries link %q, which is not in intent; %s, and a bundle that calls a port cabled with no cable on it is never produced",
					id, link, namesItsLink))
			case len(c.Links[i].Endpoints) == 2:
				list.Add(findings.Rejection, findings.RuleRequiredMissing, id, fmt.Sprintf(
					"%s carries link %q, which does not end on it; %s, and a bundle that calls a port cabled with no cable on it is never produced",
					id, link, namesItsLink))
			}
		}
	}

	for _, l := range c.Links {
		if len(l.Endpoints) != 2 {
			continue
		}
		for _, e := range l.Endpoints {
			link, ok := carried[e.ID()]
			if !ok || len(ends[e.ID()]) != 1 || link == l.ID {
				continue
			}
			if link == "" {
				list.Add(findings.Rejection, findings.RuleRequiredMissing, l.ID, fmt.Sprintf(
					"endpoint %s carries no link; %s, and a bundle that cables a port its mapping calls %s is never produced",
					e.ID(), namesItsLink, DispConfiguredNotCabled))
				continue
			}
			list.Add(findings.Rejection, findings.RuleRequiredMissing, l.ID, fmt.Sprintf(
				"endpoint %s carries link %q; %s", e.ID(), link, namesItsLink))
		}
	}
	return list
}

// namesItsLink is the rule every LinkTerminations refusal states.
const namesItsLink = "an interface names the one link it terminates"
