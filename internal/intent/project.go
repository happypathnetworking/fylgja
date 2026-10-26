package intent

import (
	"context"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// pageSize is how many objects are fetched per request, and how many devices' ids one
// Ports request filters by.
const pageSize = 100

// Generated type names carry the whole selection path, which is unreadable at every
// use site. These aliases name the two nodes the projection walks. A device is held by
// pointer: its artifacts are read through the ArtifactFields fragment's interface, whose
// methods the generated struct carries on its pointer.
type (
	deviceNode = *DevicesDcimDevicePaginatedDcimDeviceEdgesEdgedDcimDeviceNodeDcimDevice
	portNode   = PortsInterfacePhysicalPaginatedInterfacePhysicalEdgesEdgedInterfacePhysicalNodeInterfacePhysical
)

// The library's values the mapping reads a port by (mapping.md §1): the role of the
// management port, and the status of a port that is not enabled.
const (
	roleManagement = "management"
	statusDisabled = "disabled"
)

// Fetch reads the scope of a branch into the CTM and seals it with an envelope, by the
// mapping (specs/017-dcim-reader/contracts/mapping.md): the DcimDevices carrying the
// scope's tag, then their physical ports by the devices' ids, each cable through its
// port's connector.
//
// Inside the scope the read is strict: a scope that selects no device is refused
// scope.empty, and a device no package can be chosen for platform.missing or
// platform.unmatched, every one in one pass and with no CTM (completeness.go). At the
// scope's edge it is not: a cable the mapping cannot place is omitted, an info finding
// beside the read and a row of the envelope's fidelity list, and never refuses it
// (cable.go).
//
// Otherwise projection only: it copies what intent says, without judging it. Everything
// else that could make intent unbuildable is checked afterwards, against the CTM, so a
// fixture and a live branch are validated by exactly the same rules.
//
// The one exception is the configuration artifact (M5, D-028), whose findings come back
// here: selecting it is a read, not a judgement — which of a device's artifacts is its
// configuration, whether its content is held, and whether the bytes served are the bytes
// Infrahub described. Those questions can only be answered with Infrahub in hand, so
// they cannot move to internal/validate, which runs against a CTM. What validation does
// mirror is what survives into the CTM: a device with no artifact, and a checksum that
// does not match its content. A device refused for its platform is not also refused for
// its artifact: there is no package to say which artifact to look for.
//
// The envelope is assembled here from what the caller already established — the
// conformance pass read the schema hash, so Fetch does not re-read it — plus the
// `observed_at` the caller captured before the first request.
// `at` is whatever the operator supplied, verbatim, and absent when they
// supplied none: Fylgja never invents one.
func (c *Client) Fetch(ctx context.Context, conf *Conformance, observedAt string, reg *psp.Registry) (*ctm.CTM, findings.List, error) {
	out := &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:     c.cfg.Branch,
			At:         c.cfg.At,
			ObservedAt: observedAt,
			Scope:      ScopePrefix + c.cfg.Scope,
			Mapping:    ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: LibraryModel, Version: LibraryVersion},
			Fidelity:   readFidelity(),
		},
	}
	if conf != nil {
		out.Envelope.SchemaHash = conf.SchemaHash
	}

	devices, err := c.devices(ctx)
	if err != nil {
		return nil, nil, err
	}
	// No device, no ports to ask for: a Ports request with no ids would filter by none.
	if len(devices) == 0 {
		return nil, findings.List{ScopeEmpty(out.Envelope.Scope, c.cfg.Branch, c.cfg.At)}, nil
	}

	ids := make([]string, 0, len(devices))
	names := make(map[string]string, len(devices))
	for _, d := range devices {
		ids = append(ids, d.id)
		names[d.id] = d.name
	}
	ports, err := c.ports(ctx, ids)
	if err != nil {
		return nil, nil, err
	}

	packages, list := completeness(devices, reg)

	// The device nodes are kept beside the devices they projected into, so the artifact
	// pass can read what the same request listed: one query yields a device and its
	// artifacts, at the same `at`.
	byID := make(map[string]int, len(devices))
	nodes := make([]deviceNode, 0, len(devices))
	for _, d := range devices {
		dev := ctm.Device{Name: d.name, Provenance: ctm.ProvenanceIntent}
		if pkg, ok := packages[d.id]; ok {
			dev.Platform = ctm.Platform{Package: pkg.Platform.ID}
		}
		byID[d.id] = len(out.Devices)
		out.Devices = append(out.Devices, dev)
		nodes = append(nodes, d.node)
	}

	cables := map[string]cableJudgement{}
	for _, p := range ports {
		device := p.GetDevice()
		owner := device.GetNode()
		if owner == nil {
			continue
		}
		i, ok := byID[owner.GetId()]
		if !ok {
			continue
		}
		out.Devices[i].Interfaces = append(out.Devices[i].Interfaces, projectPort(p))
		if n := p.GetConnector(); n.Node.ID != "" {
			if _, judged := cables[n.Node.ID]; !judged {
				cables[n.Node.ID] = judgeOf(n.Node, names)
			}
		}
	}
	var omitted findings.List
	judgeCables(out, cables, &omitted)
	list = append(list, omitted...)

	// Before Normalize, which reorders the devices: the artifacts are matched to the
	// nodes they were listed on by position, and the pass sorts its own work by name so
	// its findings come out in the order the CTM will list the devices in.
	artifacts, artifactFindings, err := c.fetchArtifacts(ctx, out.Devices, nodes, reg)
	if err != nil {
		return nil, nil, err
	}
	list = append(list, artifactFindings...)
	// A device without a package refuses the read: no CTM carries one (FR-014).
	if len(packages) < len(devices) {
		return nil, list, nil
	}
	for i := range out.Devices {
		out.Devices[i].Artifact = artifacts[i]
	}

	ctm.Normalize(out)
	return out, list, nil
}

// devices reads every DcimDevice carrying the scope's tag, whatever its status, paged.
func (c *Client) devices(ctx context.Context) ([]readDevice, error) {
	var out []readDevice
	for offset := 0; ; offset += pageSize {
		resp, err := Devices(ctx, c.gql, c.cfg.Scope, pageSize, offset)
		if err != nil {
			return nil, c.wrap(err, "reading devices")
		}
		page := resp.GetDcimDevice()
		for _, edge := range page.GetEdges() {
			node := edge.GetNode()
			out = append(out, projectDevice(&node))
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	return out, nil
}

// projectDevice flattens one device: its id, its name, and its platform's pair as far as
// it carries one.
func projectDevice(n deviceNode) readDevice {
	name := n.GetName()
	d := readDevice{id: n.GetId(), name: name.GetValue(), node: n}
	platform := n.GetPlatform()
	p := platform.GetNode()
	if p == nil {
		return d
	}
	d.hasPlatform = true
	pname := p.GetName()
	d.platform = pname.GetValue()
	manufacturer := p.GetManufacturer()
	if m := manufacturer.GetNode(); m != nil {
		d.hasManufacturer = true
		mname := m.GetName()
		d.manufacturer = mname.GetValue()
	}
	return d
}

// ports reads the physical ports of the devices read, one Ports request per page of a
// hundred device ids, each paged itself. An InterfaceVirtual is never asked for (FR-003).
func (c *Client) ports(ctx context.Context, ids []string) ([]portNode, error) {
	var out []portNode
	for start := 0; start < len(ids); start += pageSize {
		chunk := ids[start:min(start+pageSize, len(ids))]
		for offset := 0; ; offset += pageSize {
			resp, err := Ports(ctx, c.gql, chunk, pageSize, offset)
			if err != nil {
				return nil, c.wrap(err, "reading ports")
			}
			page := resp.GetInterfacePhysical()
			for _, edge := range page.GetEdges() {
				out = append(out, edge.GetNode())
			}
			if offset+pageSize >= page.GetCount() {
				break
			}
		}
	}
	return out, nil
}

// projectPort copies one physical port in production naming. Everything read from
// Infrahub is tagged `intent`: the other provenances exist for objects Infrahub does not
// know about, which is the CTM's reason for being (D-010). The management port is the
// port whose role is management, and a port is enabled unless its status is disabled,
// a null status included: both are approximations, rows of the envelope's fidelity list.
// Its link is set when its cable is judged one.
func projectPort(p portNode) ctm.Interface {
	name, role, status := p.GetName(), p.GetRole(), p.GetStatus()
	enabled := status.GetValue() != statusDisabled
	return ctm.Interface{
		Name:       name.GetValue(),
		MgmtOnly:   role.GetValue() == roleManagement,
		Enabled:    &enabled,
		Provenance: ctm.ProvenanceIntent,
	}
}
