package intent

import (
	"fmt"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// connectorNode is a port's connector as the Ports query selects it: a DcimCable with its
// label, or another kind implementing DcimConnector, and every end it joins. It is bound
// in queries.graphql rather than generated, so that an end of any __typename decodes: the
// generated decoder refuses a type the SDL it was generated from does not name, and the
// mapping omits a cable whose end is not a physical port where that would fail the read.
// A null node, an uncabled port, decodes to the zero value, whose ID is empty.
type connectorNode struct {
	Typename string `json:"__typename"`
	ID       string `json:"id"`
	// Label is the DcimCable's; a connector of another kind has none.
	Label              textValue `json:"label"`
	ConnectedEndpoints struct {
		Count int `json:"count"`
		Edges []struct {
			Node *cableEndNode `json:"node"`
		} `json:"edges"`
	} `json:"connected_endpoints"`
}

// cableEndNode is one end of a connector: a physical port carries its name and its
// device's id, and any other endpoint its __typename and id alone.
type cableEndNode struct {
	Typename string    `json:"__typename"`
	ID       string    `json:"id"`
	Name     textValue `json:"name"`
	Device   struct {
		Node *struct {
			ID string `json:"id"`
		} `json:"node"`
	} `json:"device"`
}

// textValue is an attribute's value as GraphQL answers it; null reads as "".
type textValue struct {
	Value string `json:"value"`
}

// physicalPort is the one endpoint kind a link may end on (mapping.md §4).
const physicalPort = "InterfacePhysical"

// cableKind is the one connector kind a link may be (FR-006). A kind of the operator's own
// may implement DcimConnector beside it, which conformance allows (FR-012), and is
// omitted (T096).
const cableKind = "DcimCable"

// cableJudgement is one cable reached from a port in the scope, with every end it joins,
// judged once by its id however many of its ends were read (R-05). A connector of another
// kind is judged as one, so that it is omitted under its own reason.
type cableJudgement struct {
	// kind is the connector's __typename, and the source of its fidelity row when it is
	// omitted.
	id, label, kind string
	// count is connected_endpoints.count as Infrahub answered it, which the ends rule
	// reads, rather than the ends listed.
	count int
	ends  []cableEnd
}

// cableEnd is one end of a cable: deviceName is set when the device is among the devices
// read, and port when the end is a physical port; kind is its __typename.
type cableEnd struct {
	deviceID, deviceName, port, kind string
}

// judgeOf collects a connector into its judgement, keyed by the connector's id. The
// devices read are by id, so an end's device is named when it is in the scope and only
// then: a device outside the scope is never read (FR-002).
func judgeOf(n connectorNode, devices map[string]string) cableJudgement {
	j := cableJudgement{id: n.ID, label: n.Label.Value, kind: n.Typename, count: n.ConnectedEndpoints.Count}
	for _, edge := range n.ConnectedEndpoints.Edges {
		if edge.Node == nil {
			continue
		}
		end := cableEnd{kind: edge.Node.Typename}
		if end.kind == physicalPort {
			end.port = edge.Node.Name.Value
			if dev := edge.Node.Device.Node; dev != nil {
				end.deviceID = dev.ID
				end.deviceName = devices[dev.ID]
			}
		}
		j.ends = append(j.ends, end)
	}
	return j
}

// object names the cable as its findings and its fidelity row do: its label, or its id
// when it has none, as a connector of another kind always has, since the read selects a
// label on a DcimCable alone.
func (j cableJudgement) object() string {
	if j.label != "" {
		return j.label
	}
	return j.id
}

// noun is what a finding calls the connector: a cable, or a connector of another kind.
func (j cableJudgement) noun() string {
	if j.kind == cableKind {
		return "cable"
	}
	return "connector"
}

// omission is why the mapping cannot place a cable: its rule and its reason, the first of
// R-05's four that applies, in their order, the connector's own kind first (T096); ok is
// false for a cable that is a link.
func (j cableJudgement) omission() (rule, reason string, ok bool) {
	switch {
	case j.kind != cableKind:
		return findings.RuleOmitCableKind, fmt.Sprintf("a connector that is not a DcimCable (%s)", j.kind), true
	// The count Infrahub answered is the rule's; a cable that counts two and lists fewer,
	// an end Infrahub would not give, is not two ends either, and says how many it listed.
	case j.count != 2:
		return findings.RuleOmitCableEnds, fmt.Sprintf("other than two ends (%d)", j.count), true
	case len(j.ends) != 2:
		return findings.RuleOmitCableEnds, fmt.Sprintf("other than two ends (%d listed of %d)", len(j.ends), j.count), true
	}
	for _, e := range j.ends {
		if e.kind != physicalPort {
			return findings.RuleOmitCableEndpoint, fmt.Sprintf("an end not on a physical port (%s)", e.kind), true
		}
	}
	for _, e := range j.ends {
		if e.deviceName == "" {
			return findings.RuleOmitCableOutsideScope, fmt.Sprintf("an end outside the scope (%s)", e.name()), true
		}
	}
	return "", "", false
}

// name is an end as a finding names it, <device>:<port>. A device outside the scope is
// named by its id, since its name is never read.
func (e cableEnd) name() string {
	device := e.deviceName
	if device == "" {
		device = e.deviceID
	}
	return device + ":" + e.port
}

// knownEnds lists the ends a finding can name, <device>:<port>, sorted: every end that is a
// physical port. An end of another kind has no name or device to give.
func (j cableJudgement) knownEnds() []string {
	var out []string
	for _, e := range j.ends {
		if e.kind == physicalPort {
			out = append(out, e.name())
		}
	}
	sort.Strings(out)
	return out
}

// endpoints are a link's two ends in the CTM's terms.
func (j cableJudgement) endpoints() (ctm.Endpoint, ctm.Endpoint) {
	return ctm.Endpoint{Device: j.ends[0].deviceName, Interface: j.ends[0].port},
		ctm.Endpoint{Device: j.ends[1].deviceName, Interface: j.ends[1].port}
}

// judgeCables places every cable reached from a port in the scope (R-05). A cable with
// exactly two ends, each a physical port of a device read, is a link with the canonical
// id, both ports linked. Any other, and any connector that is not a DcimCable, is
// omitted, never refusing the read: an info finding beside the read and a fidelity row
// whose source is the connector's kind, each naming it and its reason. Cables are
// judged in object order, so two reads of one branch report them alike, whatever order
// Infrahub paged the ports in.
func judgeCables(c *ctm.CTM, cables map[string]cableJudgement, list *findings.List) {
	judged := make([]cableJudgement, 0, len(cables))
	for _, j := range cables {
		judged = append(judged, j)
	}
	sort.Slice(judged, func(a, b int) bool {
		if judged[a].object() != judged[b].object() {
			return judged[a].object() < judged[b].object()
		}
		return judged[a].id < judged[b].id
	})

	ports := map[string]*ctm.Interface{}
	for i := range c.Devices {
		d := &c.Devices[i]
		for k := range d.Interfaces {
			ports[d.Name+":"+d.Interfaces[k].Name] = &d.Interfaces[k]
		}
	}
	for _, j := range judged {
		rule, reason, omitted := j.omission()
		if omitted {
			msg := fmt.Sprintf("%s %s is omitted: %s", j.noun(), j.object(), reason)
			if ends := j.knownEnds(); len(ends) > 0 {
				msg += "; its ends are " + strings.Join(ends, ", ")
			}
			list.Add(findings.Info, rule, j.object(), msg)
			c.Envelope.Fidelity = append(c.Envelope.Fidelity, ctm.FidelityRow{
				Disposition: ctm.FidelityOmitted, Object: j.object(), Source: j.kind, Reason: reason,
			})
			continue
		}
		a, b := j.endpoints()
		id := ctm.CanonicalLinkID(a, b)
		c.Links = append(c.Links, ctm.Link{ID: id, Endpoints: []ctm.Endpoint{a, b}, Provenance: ctm.ProvenanceIntent})
		for _, e := range []ctm.Endpoint{a, b} {
			if p := ports[e.ID()]; p != nil {
				p.Link = id
			}
		}
	}
}

// readFidelity is what this reader approximates on every read (mapping.md §5): the
// management port and the admin state, each read from a field whose meaning is close to
// Fylgja's and not the same, and the platform's version, which the library does not
// carry. Each omitted cable, or connector of another kind, adds a row of its own
// (judgeCables).
func readFidelity() []ctm.FidelityRow {
	return []ctm.FidelityRow{
		{Disposition: ctm.FidelityApproximated, Object: "interface.mgmt_only", Source: "InterfacePhysical.role",
			Reason: "the management port is the port whose role is management; the library has no management-only flag"},
		{Disposition: ctm.FidelityApproximated, Object: "interface.enabled", Source: "InterfacePhysical.status",
			Reason: "a port is enabled unless its status is disabled; the library's status is not an admin state"},
		{Disposition: ctm.FidelityOmitted, Object: "platform.version", Source: "DcimPlatform",
			Reason: "the library's platform carries no version"},
	}
}
