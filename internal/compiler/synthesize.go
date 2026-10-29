package compiler

import (
	"fmt"
	"slices"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// Host is one synthesized node: one endpoint of one probe, placed on the device interface
// it names (016, R-01, R-02). PlaceProbes builds the table and the topology and the
// manifest read it; nothing of it is in the CTM but the device, its one interface and its
// link.
type Host struct {
	// Node is the host's node name, <probe>-<a|b>.
	Node string
	// Probe and Endpoint name the declaration's probe and which of its two endpoints, a
	// or b, the host is.
	Probe, Endpoint string
	// Device and Interface are the intent's port the host is cabled to.
	Device, Interface string
	// Port is the host's own port, its package's host.interface, which the synthesized
	// link cables to Interface.
	Port string
	// Address is the host's address with its prefix length and Gateway its gateway, as
	// declared; FarAddress is the other endpoint's address without its prefix length, which
	// the host's route and its flows reach.
	Address, Gateway, FarAddress string
	// Package is the probe package of the probe's format, from which the host's kind,
	// image and exec lines are read: the compiler names no format and no image.
	Package *probe.Package
}

// PlaceProbes places a snapshot's probes on its CTM (016, R-01, R-09): for each probe in
// name order and each endpoint in order, a synthesized device <probe>-<a|b> of the probe's
// format, with one interface, the package's host.interface, and a synthesized link from it
// to the endpoint's device interface, whose link is set. It returns a copy of c with the
// hosts and their links added, normalized, and the hosts by node name; c itself is never
// changed.
//
// Pure, and one function for both its callers, validation and the compiler, so a refusal is
// worded alike from either, as SurveyDevice's are. Every refusal is found in one pass,
// each naming the probe and the endpoint (<probe>/<a|b>, the probe alone for its format)
// and the cause, and then nothing is placed: the copy and the table are nil. No probe is
// dropped with a finding (FR-009).
//
// The device and the interface are read from c, which the callers have normalized. A host's
// package is looked up by the probe's format in probes, which may be nil where no probe is
// declared.
func PlaceProbes(c *ctm.CTM, decls []probe.Probe, probes *probe.Registry) (*ctm.CTM, map[string]Host, findings.List) {
	var list findings.List
	placed := cloneCTM(c)
	hosts := map[string]Host{}

	sorted := slices.Clone(decls)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })

	// A host's name is free when no device of intent and no other host holds it.
	taken := map[string]string{} // "device:interface" -> "probe <name> endpoint <end>"
	names := map[string]bool{}
	for _, d := range c.Devices {
		names[d.Name] = true
	}

	for _, p := range sorted {
		pkg, known := lookupProbe(probes, p.Format)
		if !known {
			list.Add(findings.Rejection, findings.RuleProbeFormatUnknown, p.Name, fmt.Sprintf(
				"format %q: no probe package declares it; the formats loaded are %s", p.Format, formatsOf(probes)))
		}
		for j, e := range p.Endpoints {
			end := probe.Ends[j]
			object := p.Name + "/" + end
			node := p.Name + "-" + end
			port := e.Device + ":" + e.Interface

			if names[node] {
				list.Add(findings.Rejection, findings.RuleProbeHostCollision, object, fmt.Sprintf(
					"host %s, this endpoint's node, is the name of a device or of another host; a node name is one node's", node))
			}
			names[node] = true

			d := c.Device(e.Device)
			if d == nil {
				list.Add(findings.Rejection, findings.RuleProbeDeviceUnknown, object, fmt.Sprintf(
					"device %q is not in the snapshot; a probe's endpoint names a device of the intent", e.Device))
				continue
			}
			in := d.Interface(e.Interface)
			switch {
			case in == nil:
				list.Add(findings.Rejection, findings.RuleProbeInterfaceUnknown, object, fmt.Sprintf(
					"device %s has no interface %q in the snapshot", e.Device, e.Interface))
				continue
			case in.Link != "":
				list.Add(findings.Rejection, findings.RuleProbeInterfaceCabled, object, fmt.Sprintf(
					"interface %s is cabled (%s); %s", port, in.Link, takesWhat))
				continue
			case in.MgmtOnly:
				list.Add(findings.Rejection, findings.RuleProbeInterfaceMgmtOnly, object, fmt.Sprintf(
					"interface %s is mgmt_only; %s", port, takesWhat))
				continue
			}
			if first, ok := taken[port]; ok {
				list.Add(findings.Rejection, findings.RuleProbePortTaken, object, fmt.Sprintf(
					"interface %s is taken by %s; a port is one probe's", port, first))
				continue
			}
			taken[port] = fmt.Sprintf("probe %s endpoint %s", p.Name, end)
			if !known {
				continue
			}

			far := p.Endpoints[1-j].Address
			if a, _, ok := strings.Cut(far, "/"); ok {
				far = a
			}
			h := Host{Node: node, Probe: p.Name, Endpoint: end, Device: e.Device, Interface: e.Interface,
				Port: pkg.Host.Interface, Address: e.Address, Gateway: e.Gateway, FarAddress: far, Package: pkg}
			hosts[node] = h

			hostEnd := ctm.Endpoint{Device: node, Interface: h.Port}
			devEnd := ctm.Endpoint{Device: e.Device, Interface: e.Interface}
			id := ctm.CanonicalLinkID(hostEnd, devEnd)
			placed.Devices = append(placed.Devices, ctm.Device{
				Name:       node,
				Platform:   ctm.Platform{Package: p.Format},
				Interfaces: []ctm.Interface{{Name: h.Port, Link: id, Provenance: ctm.ProvenanceSynthesized}},
				Provenance: ctm.ProvenanceSynthesized,
			})
			placed.Links = append(placed.Links, ctm.Link{ID: id, Endpoints: []ctm.Endpoint{hostEnd, devEnd},
				Provenance: ctm.ProvenanceSynthesized})
			placed.Device(e.Device).Interface(e.Interface).Link = id
		}
	}
	if list.Rejected() {
		return nil, nil, list
	}
	ctm.Normalize(placed)
	return placed, hosts, list
}

// takesWhat is the rule every refusal of an interface a probe cannot take states.
const takesWhat = "a probe takes an uncabled port that is not mgmt_only"

// lookupProbe is probes.Lookup, with a nil registry holding no format.
func lookupProbe(probes *probe.Registry, format string) (*probe.Package, bool) {
	if probes == nil {
		return nil, false
	}
	return probes.Lookup(format)
}

// formatsOf lists the registry's formats as probe.format.unknown names them, as the
// declaration's read words the rule.
func formatsOf(probes *probe.Registry) string {
	if probes == nil || len(probes.Formats()) == 0 {
		return "none"
	}
	return strings.Join(probes.Formats(), ", ")
}

// cloneCTM copies a CTM deeply enough that a placement on the copy leaves the original as
// it was: the devices, their interfaces, the links and their endpoints. An artifact and an
// interface's enabled are shared, since nothing here writes either.
func cloneCTM(c *ctm.CTM) *ctm.CTM {
	out := *c
	out.Envelope.Fidelity = slices.Clone(c.Envelope.Fidelity)
	out.Devices = make([]ctm.Device, len(c.Devices))
	for i, d := range c.Devices {
		d.Interfaces = slices.Clone(d.Interfaces)
		out.Devices[i] = d
	}
	out.Links = make([]ctm.Link, len(c.Links))
	for i, l := range c.Links {
		l.Endpoints = slices.Clone(l.Endpoints)
		out.Links[i] = l
	}
	return &out
}

// hostManagementPort is the management port containerlab gives a host's container: the
// first interface of every container it creates, whatever the kind, as a node's
// management_port names its package's.
const hostManagementPort = "eth0"

// hostNode is a host's topology node and its port's mapping row. The node is its package's
// kind and image, with the package's host.address and host.route rendered for the host as
// its exec lines, and no startup-config: containerlab runs the lines once the container
// starts, and nothing is pushed to a host (R-10). The row is its one port, cabled by the
// synthesized link, under the port's own name. An error is a template the package's
// validation would have refused, naming the field.
func hostNode(h Host) (TopologyNode, MappingRow, error) {
	pkg := h.Package
	values := map[string]string{
		probe.PlaceAddress:    h.Address,
		probe.PlaceGateway:    h.Gateway,
		probe.PlaceFarAddress: h.FarAddress,
		probe.PlaceInterface:  h.Port,
	}
	node := TopologyNode{Name: h.Node, Kind: pkg.Image.ClabKind, Image: pkg.Image.Ref}
	for _, t := range []struct {
		field string
		args  []string
	}{{"host.address", pkg.Host.Address}, {"host.route", pkg.Host.Route}} {
		args, err := probe.Render(t.args, values)
		if err != nil {
			return TopologyNode{}, MappingRow{}, fmt.Errorf("%s: %w", t.field, err)
		}
		node.Exec = append(node.Exec, strings.Join(args, " "))
	}
	port, name, enabled := h.Port, h.Port, true
	row := MappingRow{Device: h.Node, Interface: h.Port, Enabled: &enabled, Port: &port, NodeName: &name,
		Disposition: DispCabled, Provenance: ProvenanceSynthesized}
	return node, row, nil
}

// hostManifestNode is a host's manifest entry: what it is in place of a platform, a
// package, an artifact and a bootstrap, each written null, since a host has none (R-11).
func hostManifestNode(h Host) ManifestNode {
	return ManifestNode{
		Name:       h.Node,
		Provenance: ProvenanceSynthesized,
		Probe: &ManifestProbe{Name: h.Probe, Endpoint: h.Endpoint, Format: h.Package.Format,
			Package: probePackageRef(h.Package)},
		Image:          h.Package.Image.Ref,
		ManagementPort: hostManagementPort,
	}
}

// probePackageRef names a probe package as a node's psp names a support package: its
// format, which keys the probe registry, and whether it was the shipped one.
func probePackageRef(p *probe.Package) ManifestPSP {
	return ManifestPSP{ID: p.Format, Source: p.Origin}
}

// addProbeEntry files a host under its probe's probes[] entry, at its endpoint's place.
func addProbeEntry(entries map[string]*ManifestProbeEntry, h Host) {
	e, ok := entries[h.Probe]
	if !ok {
		e = &ManifestProbeEntry{Name: h.Probe, Format: h.Package.Format, Package: probePackageRef(h.Package),
			Fidelity: ProbeFidelity{Forwarding: h.Package.Fidelity.Forwarding, Timing: h.Package.Fidelity.Timing}}
		entries[h.Probe] = e
	}
	e.Hosts[slices.Index(probe.Ends[:], h.Endpoint)] = ProbeHost{Endpoint: h.Endpoint, Node: h.Node, Device: h.Device,
		Interface: h.Interface, Port: h.Port, Address: h.Address, Gateway: h.Gateway}
}

// probeEntries is the manifest's probes[], in no order: marshalManifest sorts it by name.
func probeEntries(entries map[string]*ManifestProbeEntry) []ManifestProbeEntry {
	out := make([]ManifestProbeEntry, 0, len(entries))
	for _, e := range entries {
		out = append(out, *e)
	}
	return out
}
