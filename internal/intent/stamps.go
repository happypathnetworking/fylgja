package intent

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Stamps is when a scope's intent and its artifacts were last written, as one read at the
// client's (branch, at) returned them, under the client's scope (014; D-046; 017 research
// R-10). It reads stamps and never a value of intent but the names that key them: the
// platform's and its manufacturer's names, which pick each device's package, and the ids an
// intent event names a device by (D-048). A node's stamp is its updated_at, or its
// created_at when Infrahub's own account wrote it last (D-058): the account that created
// the internal groups of the queries the scope's artifacts render through, read at the same
// (branch, at) (D-060). Every stamp is kept as the string Infrahub returned; each comparison
// parses it.
type Stamps struct {
	// Latest is the latest stamp the read returned: every device's, its interfaces', its
	// platform's, its manufacturer's and its cables', each as D-058 counts it, and every
	// artifact's checksum's. The head's `at` is one microsecond after the later of it and the
	// branch's latest intent event (D-048). "" when the scope holds nothing stamped.
	Latest string
	// Devices holds each device's own stamps by its name.
	Devices map[string]DeviceStamps
}

// DeviceStamps is one device's side of the staleness rule (D-046).
type DeviceStamps struct {
	// Match is the device's manufacturer and platform pair, as the read reads it, which
	// picks its package from the registry (Registry.Match), whose config.artifact_name names
	// which of Artifacts is its configuration (Constitution II). A device with no platform,
	// or a platform with no manufacturer, has "" where it has none, and matches no package.
	Match psp.Match
	// IDs are the device's own id, then its platform's and its manufacturer's, each of its
	// interfaces' and each of its cables', as read: an intent event names the device when
	// one is its primary node or a peer of its relationships (D-048).
	IDs []string
	// Intent is the latest stamp of the device's own intent (FR-023): the node_metadata of
	// the device, of its platform and its manufacturer, of each of its interfaces, of both
	// kinds, and of each cable one of its physical ports is an end of. Each is the latest
	// write among that node's current attributes and relationship edges (017 research §1.7),
	// or the node's creation when that write was Infrahub's own account's (D-058): a
	// generation's join of its query's group, which is never intent.
	Intent string
	// Artifacts maps each of the device's artifacts by name to its checksum.updated_at,
	// which moves only when Infrahub stores bytes that differ; "" when Infrahub returned
	// no stamp for it. Two artifacts of one name keep the later, which the read refuses
	// as artifact.ambiguous anyway.
	Artifacts map[string]string
}

// stampNode is a node the stamps read for its id alone, of whatever kind implements the
// generic: an interface of a device, or a port's connector. It is bound in queries.graphql
// rather than generated, as the read's connector is, so that a kind the SDL does not name
// decodes. A null node decodes to the zero value, whose ID is empty.
type stampNode struct {
	ID string `json:"id"`
}

// stampTransformation is an artifact definition's transformation, of whichever of
// Infrahub's kinds, as far as the query it renders through. Bound in queries.graphql, as
// stampNode is, so that a transformation kind the SDL does not name decodes; a null
// decodes to the zero value, whose query's ID is empty.
type stampTransformation struct {
	Query struct {
		Node stampNode `json:"node"`
	} `json:"query"`
}

// stampMeta is a node's node_metadata as the stamps read it: when the node was last
// written, by which account, and when it was created (D-058). It is bound in
// queries.graphql rather than generated, one type for every node the stamps read. A null
// decodes to the zero value, "" where Infrahub returned none.
type stampMeta struct {
	UpdatedAt string    `json:"updated_at"`
	UpdatedBy stampNode `json:"updated_by"`
	CreatedAt string    `json:"created_at"`
}

// stamp is the node's stamp as D-058 counts it: its updated_at, or its created_at when the
// account that last wrote it is one of own, Infrahub's own (D-060). That account writes a
// node only to add it to a query's group after a generation has read it, so the node's
// creation is no later than that generation. An intent write by that account, a
// generator's, is still seen by the events (D-048).
func (m stampMeta) stamp(own map[string]bool) string {
	if m.UpdatedBy.ID != "" && own[m.UpdatedBy.ID] {
		return m.CreatedAt
	}
	return m.UpdatedAt
}

// The generated edge types, named for the walk below as project.go names the read's.
type (
	stampDeviceEdge = IntentStampsDcimDevicePaginatedDcimDeviceEdgesEdgedDcimDevice
	stampPortNode   = PortStampsInterfacePhysicalPaginatedInterfacePhysicalEdgesEdgedInterfacePhysicalNodeInterfacePhysical
)

// Stamps reads the stamps of the scope's devices at the client's `at`, which is sent on
// every page iff it is set, as the read sends it, and aggregates them per device: the
// DcimDevices carrying the scope's tag, then their cabled physical ports by the devices'
// ids, each with its cable, as the read reads them (R-10), then the internal groups of the
// queries their artifacts render through, whose creator is Infrahub's own account (D-060).
// Only then is each stamp folded, as D-058 counts it. Each request is paged by 100.
func (c *Client) Stamps(ctx context.Context) (Stamps, error) {
	r := stampReader{devices: map[string]*deviceFold{}, byID: map[string]*deviceFold{}}
	var ids []string
	for offset := 0; ; offset += pageSize {
		resp, err := IntentStamps(ctx, c.gql, c.cfg.Scope, pageSize, offset)
		if err != nil {
			return Stamps{}, c.wrap(err, "reading stamps")
		}
		page := resp.GetDcimDevice()
		for _, edge := range page.GetEdges() {
			ids = append(ids, r.device(edge))
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	// No device, no ports to ask for: a request with no ids would filter by none.
	for start := 0; start < len(ids); start += pageSize {
		chunk := ids[start:min(start+pageSize, len(ids))]
		for offset := 0; ; offset += pageSize {
			resp, err := PortStamps(ctx, c.gql, chunk, pageSize, offset)
			if err != nil {
				return Stamps{}, c.wrap(err, "reading stamps")
			}
			page := resp.GetInterfacePhysical()
			for _, edge := range page.GetEdges() {
				r.port(edge.GetNode())
			}
			if offset+pageSize >= page.GetCount() {
				break
			}
		}
	}
	own, err := c.ownAccounts(ctx, r.queries)
	if err != nil {
		return Stamps{}, err
	}
	r.fold(own)
	if r.err != nil {
		return Stamps{}, fmt.Errorf("reading stamps %s: %w", c.cfg.describe(), r.err)
	}

	out := Stamps{Latest: r.all.stamp, Devices: make(map[string]DeviceStamps, len(r.devices))}
	for name, d := range r.devices {
		artifacts := make(map[string]string, len(d.artifacts))
		for a, fold := range d.artifacts {
			artifacts[a] = fold.stamp
		}
		out.Devices[name] = DeviceStamps{Match: d.match, IDs: d.ids, Intent: d.intent.stamp, Artifacts: artifacts}
	}
	return out, nil
}

// ownAccounts is Infrahub's own account in D-058's sense, read at the client's (branch, at):
// the creator of each internal group of the queries given, by its id (D-059, D-060). No
// query, or no group, is no account: nothing has been generated through the query there,
// so no stamp is a generation's. A scope's artifacts render through a query or two, so the
// ids go in one request, paged.
func (c *Client) ownAccounts(ctx context.Context, queries []string) (map[string]bool, error) {
	own := map[string]bool{}
	if len(queries) == 0 {
		return own, nil
	}
	for offset := 0; ; offset += pageSize {
		resp, err := QueryGroups(ctx, c.gql, queries, pageSize, offset)
		if err != nil {
			return nil, c.wrap(err, "reading stamps")
		}
		page := resp.GetCoreGraphQLQueryGroup()
		for _, edge := range page.GetEdges() {
			meta := edge.GetNode_metadata()
			if by := meta.GetCreated_by(); by.ID != "" {
				own[by.ID] = true
			}
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	return own, nil
}

// stampFold keeps the latest of the stamps it is shown, as the string Infrahub returned.
// Two stamps naming one instant keep the first.
type stampFold struct {
	stamp string
	at    time.Time
}

func (f *stampFold) take(stamp string, at time.Time) {
	if f.stamp == "" || at.After(f.at) {
		f.stamp, f.at = stamp, at
	}
}

// deviceFold is one device's stamps while the pages are read.
type deviceFold struct {
	match     psp.Match
	ids       []string
	intent    stampFold
	artifacts map[string]*stampFold
}

// stampReader folds one read's stamps: each into the branch's latest and into the folds
// it belongs to. The walk keeps each node's metadata with its folds, in the order read,
// and folds them once Infrahub's own account is known (fold). The first stamp that does
// not parse is kept and returned after the read, so the walk below stays a walk.
type stampReader struct {
	all     stampFold
	devices map[string]*deviceFold
	// byID finds a device's fold by its id, by which a port names its device.
	byID map[string]*deviceFold
	// pending is each stamp read, with the folds it belongs to, until fold.
	pending []pendingStamp
	// queries are the ids of the queries the artifacts' definitions render through, once
	// each, in the order read.
	queries []string
	err     error
}

// pendingStamp is one node's metadata, or one checksum's stamp, and the folds it belongs to.
type pendingStamp struct {
	meta stampMeta
	into []*stampFold
}

// node keeps one node's metadata for its folds.
func (r *stampReader) node(meta stampMeta, into ...*stampFold) {
	r.pending = append(r.pending, pendingStamp{meta: meta, into: into})
}

// fold folds every stamp kept, in the order read, each as D-058 counts it under own.
func (r *stampReader) fold(own map[string]bool) {
	for _, p := range r.pending {
		r.see(p.meta.stamp(own), p.into...)
	}
	r.pending = nil
}

// see folds one stamp. "" is a null, a node not set, and is skipped.
func (r *stampReader) see(stamp string, into ...*stampFold) {
	if stamp == "" {
		return
	}
	at, err := parseStamp(stamp)
	if err != nil {
		if r.err == nil {
			r.err = err
		}
		return
	}
	r.all.take(stamp, at)
	for _, f := range into {
		f.take(stamp, at)
	}
}

// device folds one device's edge and returns the device's id. Each generated getter
// returns a value, so each is held in a variable before its own getters are called, as
// project.go does.
func (r *stampReader) device(edge stampDeviceEdge) string {
	n := edge.GetNode()
	nameAttr := n.GetName()
	name := nameAttr.GetValue()
	d, ok := r.devices[name]
	if !ok {
		d = &deviceFold{artifacts: map[string]*stampFold{}}
		r.devices[name] = d
	}
	id := n.GetId()
	r.byID[id] = d
	d.ids = append(d.ids, id)
	r.node(edge.GetNode_metadata(), &d.intent)

	// The platform and its manufacturer reach every device on them: their names pick the
	// device's package, and the template renders them into its artifact (R-11).
	platform := n.GetPlatform()
	r.node(platform.GetNode_metadata(), &d.intent)
	if p := platform.GetNode(); p != nil {
		pname := p.GetName()
		d.match.Platform = pname.GetValue()
		d.ids = append(d.ids, p.GetId())
		manufacturer := p.GetManufacturer()
		r.node(manufacturer.GetNode_metadata(), &d.intent)
		if m := manufacturer.GetNode(); m != nil {
			mname := m.GetName()
			d.match.Manufacturer = mname.GetValue()
			d.ids = append(d.ids, m.GetId())
		}
	}

	interfaces := n.GetInterfaces()
	for _, e := range interfaces.GetEdges() {
		r.node(e.GetNode_metadata(), &d.intent)
		if in := e.GetNode(); in.ID != "" {
			d.ids = append(d.ids, in.ID)
		}
	}

	// The artifacts come through the fragment's own interface, as the read's do. A
	// checksum's stamp is the branch's latest and the artifact's, never the device's intent,
	// and names no account. Its definition's query is where Infrahub's own account is read.
	if target, ok := any(&n).(ArtifactStamps); ok {
		artifacts := target.GetArtifacts()
		for _, e := range artifacts.GetEdges() {
			a := e.GetNode()
			artifactName, checksum := a.GetName(), a.GetChecksum()
			fold, ok := d.artifacts[artifactName.GetValue()]
			if !ok {
				fold = &stampFold{}
				d.artifacts[artifactName.GetValue()] = fold
			}
			r.node(stampMeta{UpdatedAt: checksum.GetUpdated_at()}, fold)
			definition := a.GetDefinition()
			def := definition.GetNode()
			transformation := def.GetTransformation()
			if q := transformation.GetNode().Query.Node.ID; q != "" && !slices.Contains(r.queries, q) {
				r.queries = append(r.queries, q)
			}
		}
	}
	return id
}

// port folds one physical port's cable into its device's intent: a cable's stamp is the
// intent of the device of each of its ends in the scope, and of no third (FR-023). A cable
// whose two ends are on one device is that device's once. The port's own stamp is its
// device's interfaces edge's, already folded.
func (r *stampReader) port(p stampPortNode) {
	device := p.GetDevice()
	owner := device.GetNode()
	if owner == nil {
		return
	}
	d, ok := r.byID[owner.GetId()]
	if !ok {
		return
	}
	connector := p.GetConnector()
	cable := connector.GetNode()
	if cable.ID == "" {
		return // uncabled: the query asks for none, and a null node is skipped anyway
	}
	r.node(connector.GetNode_metadata(), &d.intent)
	if !slices.Contains(d.ids, cable.ID) {
		d.ids = append(d.ids, cable.ID)
	}
}

// parseStamp reads a stamp Infrahub returned: RFC 3339, six fractional digits as
// Infrahub writes them, the offset +00:00 or Z.
func parseStamp(s string) (time.Time, error) {
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", s)
	}
	return t, nil
}
