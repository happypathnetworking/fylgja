package intent

import (
	"context"
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// pageSize is how many objects are fetched per request.
const pageSize = 100

// Generated type names carry the whole selection path, which is unreadable at every
// use site. These aliases name the two nodes the projection walks. The fragment
// interfaces genqlient derives — InterfaceFields, PlatformFields — are already short
// enough to use directly.
type (
	deviceNode = DevicesFylgjaDevicePaginatedFylgjaDeviceEdgesEdgedFylgjaDeviceNodeFylgjaDevice
	linkNode   = LinksFylgjaLinkPaginatedFylgjaLinkEdgesEdgedFylgjaLinkNodeFylgjaLink
)

// ContractVersion reads the generics contract version this branch declares.
//
// It is queried before anything else: if the branch implements a contract Fylgja does
// not understand, every other finding would be noise. The second return
// reports whether the singleton exists at all.
func (c *Client) ContractVersion(ctx context.Context) (string, bool, error) {
	resp, err := ContractVersion(ctx, c.gql)
	if err != nil {
		return "", false, c.wrap(err, "reading the contract version")
	}
	page := resp.GetFylgjaContract()
	edges := page.GetEdges()
	if len(edges) == 0 {
		return "", false, nil
	}
	// FylgjaContract is a concrete node kind rather than a generic, so genqlient
	// generates a struct here: there is no nil node to guard against.
	edge := edges[0]
	node := edge.GetNode()
	version := node.GetVersion()
	return version.GetValue(), true, nil
}

// Fetch reads a branch into the CTM and seals it with an envelope.
//
// Projection only: it copies what intent says, without judging it. Everything that
// could make intent unbuildable is checked afterwards, against the CTM, so a fixture
// and a live branch are validated by exactly the same rules.
//
// The one exception is the configuration artifact (M5, D-028), whose findings come back
// here: selecting it is a read, not a judgement — which of a device's artifacts is its
// configuration, whether its content is held, and whether the bytes served are the bytes
// Infrahub described. Those questions can only be answered with Infrahub in hand, so
// they cannot move to internal/validate, which runs against a CTM. What validation does
// mirror is what survives into the CTM: a device with no artifact, and a checksum that
// does not match its content.
//
// The registry is needed because the package says which artifact is this platform's
// configuration and which content types it accepts; nothing else about the platform is
// read here.
//
// The envelope is assembled here from what the caller already established — the
// conformance pass read the schema hash and the contract version, so Fetch does not
// re-read them — plus the `observed_at` the caller captured before the first request.
// `at` is whatever the operator supplied, verbatim, and absent when they
// supplied none: Fylgja never invents one.
func (c *Client) Fetch(ctx context.Context, conf *Conformance, observedAt string, reg *psp.Registry) (*ctm.CTM, findings.List, error) {
	out := &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:     c.cfg.Branch,
			At:         c.cfg.At,
			ObservedAt: observedAt,
		},
	}
	if conf != nil {
		out.Envelope.SchemaHash = conf.SchemaHash
		out.Envelope.ContractVersion = conf.Version
	}

	// The device nodes are kept beside the devices they projected into, so the artifact
	// pass can read what the same request listed: one query yields a device and its
	// artifacts, at the same `at`.
	var nodes []deviceNode
	for offset := 0; ; offset += pageSize {
		resp, err := Devices(ctx, c.gql, pageSize, offset)
		if err != nil {
			return nil, nil, c.wrap(err, "reading devices")
		}
		page := resp.GetFylgjaDevice()
		for _, edge := range page.GetEdges() {
			node := edge.GetNode()
			if node == nil {
				continue
			}
			out.Devices = append(out.Devices, projectDevice(node))
			nodes = append(nodes, node)
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}

	for offset := 0; ; offset += pageSize {
		resp, err := Links(ctx, c.gql, pageSize, offset)
		if err != nil {
			return nil, nil, c.wrap(err, "reading links")
		}
		page := resp.GetFylgjaLink()
		for _, edge := range page.GetEdges() {
			node := edge.GetNode()
			if node == nil {
				continue
			}
			out.Links = append(out.Links, projectLink(node))
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}

	// Before Normalize, which reorders the devices: the artifacts are matched to the
	// nodes they were listed on by position, and the pass sorts its own work by name so
	// its findings come out in the order the CTM will list the devices in.
	artifacts, list, err := c.fetchArtifacts(ctx, out.Devices, nodes, reg)
	if err != nil {
		return nil, nil, err
	}
	for i := range out.Devices {
		out.Devices[i].Artifact = artifacts[i]
	}

	relinkInterfaces(out)
	ctm.Normalize(out)
	return out, list, nil
}

// projectDevice copies one device and its interfaces. Everything read from Infrahub
// is tagged `intent`: the other provenances exist for objects Infrahub does not know
// about, which is the CTM's reason for being (D-010).
func projectDevice(n deviceNode) ctm.Device {
	name, role, site := n.GetName(), n.GetRole(), n.GetSite()
	d := ctm.Device{
		Name:       name.GetValue(),
		Role:       role.GetValue(),
		Site:       site.GetValue(),
		Provenance: ctm.ProvenanceIntent,
	}
	platformEdge := n.GetPlatform()
	if p := platformEdge.GetNode(); p != nil {
		d.Platform = projectPlatform(p)
	}
	interfaces := n.GetInterfaces()
	for _, edge := range interfaces.GetEdges() {
		in := edge.GetNode()
		if in == nil {
			continue
		}
		d.Interfaces = append(d.Interfaces, projectInterface(in))
	}
	return d
}

// projectPlatform copies the platform join key.
func projectPlatform(p PlatformFields) ctm.Platform {
	vendor, nos, ver, model := p.GetVendor(), p.GetNos(), p.GetVersion(), p.GetModel()
	return ctm.Platform{
		Vendor:  vendor.GetValue(),
		NOS:     nos.GetValue(),
		Version: ver.GetValue(),
		Model:   model.GetValue(),
	}
}

// projectInterface copies one interface in production naming.
func projectInterface(in InterfaceFields) ctm.Interface {
	ifName, ifType, mgmtOnly := in.GetName(), in.GetIftype(), in.GetMgmt_only()
	iface := ctm.Interface{
		Name:       ifName.GetValue(),
		Iftype:     ifType.GetValue(),
		MgmtOnly:   mgmtOnly.GetValue(),
		Provenance: ctm.ProvenanceIntent,
	}
	enabledAttr := in.GetEnabled()
	enabled := enabledAttr.GetValue()
	iface.Enabled = &enabled
	parentEdge := in.GetParent()
	if p := parentEdge.GetNode(); p != nil {
		pn := p.GetName()
		iface.Parent = pn.GetValue()
	}
	addresses := in.GetAddresses()
	for _, a := range addresses.GetEdges() {
		if an := a.GetNode(); an != nil {
			addr := an.GetAddress()
			iface.Addresses = append(iface.Addresses, ctm.Address{CIDR: addr.GetValue()})
		}
	}
	// An unlinked interface still carries a `link` object with a nil node; only a
	// non-nil node means the interface actually terminates a link.
	linkEdge := in.GetLink()
	if l := linkEdge.GetNode(); l != nil {
		iface.Link = l.GetId()
	}
	return iface
}

// projectLink copies one link, resolving its endpoints to (device, interface) names.
func projectLink(n linkNode) ctm.Link {
	l := ctm.Link{Provenance: ctm.ProvenanceIntent}
	endpoints := n.GetEndpoints()
	for _, edge := range endpoints.GetEdges() {
		ep := edge.GetNode()
		if ep == nil {
			continue
		}
		epName := ep.GetName()
		e := ctm.Endpoint{Interface: epName.GetValue()}
		devEdge := ep.GetDevice()
		if dev := devEdge.GetNode(); dev != nil {
			dn := dev.GetName()
			e.Device = dn.GetValue()
		}
		l.Endpoints = append(l.Endpoints, e)
	}
	if len(l.Endpoints) == 2 {
		l.ID = ctm.CanonicalLinkID(l.Endpoints[0], l.Endpoints[1])
	} else {
		// A malformed link still needs an identifier so validation can name it.
		l.ID = fmt.Sprintf("%s#%d-endpoints", n.GetId(), len(l.Endpoints))
	}
	return l
}

// relinkInterfaces rewrites interface link references from Infrahub's opaque ids to
// the CTM's canonical link ids, so a serialized CTM is self-contained and diffable
// rather than carrying identifiers only Infrahub can resolve.
func relinkInterfaces(c *ctm.CTM) {
	byEndpoint := map[string]string{}
	for _, l := range c.Links {
		for _, e := range l.Endpoints {
			byEndpoint[e.ID()] = l.ID
		}
	}
	for i := range c.Devices {
		d := &c.Devices[i]
		for j := range d.Interfaces {
			in := &d.Interfaces[j]
			if in.Link == "" {
				continue
			}
			if id, ok := byEndpoint[d.Name+":"+in.Name]; ok {
				in.Link = id
				continue
			}
			// Infrahub says this interface terminates a link that was not returned.
			// Keeping a dangling opaque id would be worse than clearing it: validation
			// reports the link, not a reference nobody can resolve.
			in.Link = ""
		}
	}
}
