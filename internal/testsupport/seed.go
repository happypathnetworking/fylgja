//go:build contract || fixture

package testsupport

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// FixtureBranch is the durable branch the three-node fixture lives on.
const FixtureBranch = "fylgja-fixture"

// MarkerPrefix is what every seeded device's description carries, so that an artifact
// rendered from it is recognisable wherever it might leak. The definition's template writes
// the description into the artifact's header (R-11), so a grep for this string over a
// finding, a log, an event, a payload or a record proves no content escaped.
const MarkerPrefix = "FYLGJA-MARKER"

// MarkerDescription is the description the seed writes on every device of a branch, and
// the value a tier greps for. The suffix is the branch's, so two branches never share a
// marker and a leak can be traced to the branch that produced it: "fixture" for the
// durable fixture branch, whose value is fixed because the branch is written once, and the
// branch name with its fylgja- prefix stripped for a throwaway.
func MarkerDescription(branch string) string {
	suffix := "fixture"
	if branch != FixtureBranch {
		suffix = strings.TrimPrefix(branch, "fylgja-")
	}
	return MarkerPrefix + "-" + suffix
}

// FixtureTag is the tag every seeded device carries: the fixtures are read under the scope
// tag:fylgja, the server's default on the development host.
const FixtureTag = "fylgja"

// RoleManagement is the role of a device's management port, the one the CTM marks
// management-only (contracts/mapping.md §5). Every other port the seeds write has no role.
const RoleManagement = "management"

// StatusDisabled is the port status the template renders as an admin state down, and the
// CTM reads as not enabled.
const StatusDisabled = "disabled"

// siteLevels is the location every seeded device stands in, from the top: the library's
// minimal locations give a site a mandatory metro, a metro a country and a country a
// region (research §1.5), and a device a mandatory location.
var siteLevels = []struct{ kind, name string }{
	{"LocationRegion", "Lab region"},
	{"LocationCountry", "Lab country"},
	{"LocationMetro", "Lab metro"},
	{"LocationSite", "lab"},
}

// platformSpec is a platform by the names a support package matches exactly (FR-027).
type platformSpec struct {
	manufacturer, name string
}

var (
	srLinux = platformSpec{"Nokia", "SR Linux"}
	eos     = platformSpec{"Arista", "EOS"}
)

// nodeSpec describes one fixture device: its platform, the name that platform gives its
// management port, and its data ports in production naming. Every name is one a booted
// node of that platform carried.
type nodeSpec struct {
	name     string
	platform platformSpec
	mgmt     string
	ports    []string
}

// linkSpec is one fixture link, written as a cable between two ports.
type linkSpec struct {
	aDev, aPort string
	bDev, bPort string
}

// id is the link's canonical id, which the cable carries as its label.
func (l linkSpec) id() string {
	return ctm.CanonicalLinkID(ctm.Endpoint{Device: l.aDev, Interface: l.aPort}, ctm.Endpoint{Device: l.bDev, Interface: l.bPort})
}

// The three-node fixture: a triangle, so every node has two cabled ports and one
// management port. Small enough to boot on a small host, and large enough that link
// ordering and per-node port ordering are actually exercised.
var (
	fixtureNodes = []nodeSpec{
		{name: "n1", platform: srLinux, mgmt: "mgmt0", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "n2", platform: srLinux, mgmt: "mgmt0", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "n3", platform: srLinux, mgmt: "mgmt0", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
	}
	fixtureLinks = []linkSpec{
		{"n1", "ethernet-1/1", "n2", "ethernet-1/1"},
		{"n2", "ethernet-1/2", "n3", "ethernet-1/1"},
		{"n3", "ethernet-1/2", "n1", "ethernet-1/2"},
	}
)

// The mixed fixture, the live twin of testdata/ctm/mixed.json: one node of the first
// platform and two of the second, cabled in a triangle so that every link crosses
// something — the two platforms on a plain port, the second platform to itself on a
// modular port, and the platforms again on a breakout lane.
var (
	mixedNodes = []nodeSpec{
		{name: "s1", platform: srLinux, mgmt: "mgmt0", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "e1", platform: eos, mgmt: "Management1", ports: []string{"Ethernet1", "Ethernet2/1"}},
		{name: "e2", platform: eos, mgmt: "Management1", ports: []string{"Ethernet1", "Ethernet3/1/1"}},
	}
	mixedLinks = []linkSpec{
		{"s1", "ethernet-1/1", "e1", "Ethernet1"},
		{"e1", "Ethernet2/1", "e2", "Ethernet1"},
		{"e2", "Ethernet3/1/1", "s1", "ethernet-1/2"},
	}
)

// SeedThreeNode populates the three-node fixture on a branch, in the schema library's
// kinds (R-15): the tag, Nokia's SR Linux, the lab site and its hierarchy, the three
// devices with their ports and cables, then the group join and the generation every seed
// ends with. It is idempotent at the branch level: seeding a branch that already has
// devices is a no-op.
func (c *Client) SeedThreeNode(branch string) error {
	if n, err := c.count(branch, "DcimDevice"); err == nil && n > 0 {
		return nil
	}
	devices, err := c.writeTopology(branch, fixtureNodes, fixtureLinks)
	if err != nil {
		return err
	}
	// The devices are targets only once they are in the group, and Infrahub renders
	// nothing on its own, so a seed that stopped here would leave every read refusing
	// artifact.missing. The wait is what makes a seeded branch readable at once: a read that
	// follows a seed is never refused for an artifact that is merely not ready yet.
	return c.generateFor(branch, devices)
}

// SeedMixed populates the mixed fixture on a throwaway branch: beside the three-node
// seed's objects, Arista's EOS, and the three devices of two platforms with their ports and
// cables, every device under the branch's marker, then the group join and the generation.
//
// It is idempotent at the branch level, as SeedThreeNode is, and it refuses the durable
// fixture branch as every change flag does: that branch holds the three-node fixture,
// written once, and every test and twin built from it relies on its bundle_id staying put.
func (c *Client) SeedMixed(branch string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("SeedMixed refuses branch %s: it holds the three-node fixture, written once and never changed; "+
			"seed a throwaway branch instead", branch)
	}
	if n, err := c.count(branch, "DcimDevice"); err == nil && n > 0 {
		return nil
	}
	devices, err := c.writeTopology(branch, mixedNodes, mixedLinks)
	if err != nil {
		return err
	}
	return c.generateFor(branch, devices)
}

// writeTopology writes a fixture's devices, each with its management port and its data
// ports, and a cable per link, and returns the devices' ids. Every device has status
// active, the lab site, its platform, the fixture's tag and the branch's marker as its
// description.
func (c *Client) writeTopology(branch string, nodes []nodeSpec, links []linkSpec) ([]string, error) {
	tag, err := c.EnsureTag(branch, FixtureTag)
	if err != nil {
		return nil, err
	}
	site, err := c.EnsureSite(branch)
	if err != nil {
		return nil, err
	}
	platforms := map[platformSpec]string{}
	ports := map[string]string{} // "device:port" -> id
	var devices []string
	for _, n := range nodes {
		platform, ok := platforms[n.platform]
		if !ok {
			if platform, err = c.EnsurePlatform(branch, n.platform.manufacturer, n.platform.name); err != nil {
				return nil, err
			}
			platforms[n.platform] = platform
		}
		dev, err := c.createDevice(branch, n.name, platform, site, tag)
		if err != nil {
			return nil, err
		}
		devices = append(devices, dev)
		// The management port is a port like any other; its role is what marks it
		// out-of-band, never its name, so each platform calls it what it calls it.
		if _, err := c.createPort(branch, dev, n.mgmt, RoleManagement); err != nil {
			return nil, err
		}
		for _, p := range n.ports {
			id, err := c.createPort(branch, dev, p, "")
			if err != nil {
				return nil, err
			}
			ports[n.name+":"+p] = id
		}
	}
	for _, l := range links {
		a, b := ports[l.aDev+":"+l.aPort], ports[l.bDev+":"+l.bPort]
		if a == "" || b == "" {
			return nil, fmt.Errorf("fixture link references a port that was not created: %+v", l)
		}
		if _, err := c.createCable(branch, l, a, b); err != nil {
			return nil, err
		}
	}
	return devices, nil
}

// createDevice writes one device: status active, at the site, on the platform, carrying
// the tag, its description the branch's marker. An empty platform or tag is left out.
func (c *Client) createDevice(branch, name, platform, site, tag string) (string, error) {
	data := fmt.Sprintf(`{name: {value: %q}, status: {value: "active"}, location: {id: %q}, description: {value: %q}`,
		name, site, MarkerDescription(branch))
	if platform != "" {
		data += fmt.Sprintf(`, platform: {id: %q}`, platform)
	}
	if tag != "" {
		data += fmt.Sprintf(`, tags: [{id: %q}]`, tag)
	}
	return c.create(branch, "DcimDevice", data+"}")
}

// createPort writes one physical port on a device, with a role when one is given. Its
// status is the library's default, active.
func (c *Client) createPort(branch, device, name, role string) (string, error) {
	data := fmt.Sprintf(`{name: {value: %q}, device: {id: %q}`, name, device)
	if role != "" {
		data += fmt.Sprintf(`, role: {value: %q}`, role)
	}
	return c.create(branch, "InterfacePhysical", data+"}")
}

// createCable writes one cable between two ports, labelled with the link's canonical id,
// which is unique among the library's cables as the link's id is among the CTM's links.
func (c *Client) createCable(branch string, l linkSpec, a, b string) (string, error) {
	return c.create(branch, "DcimCable", fmt.Sprintf(
		`{label: {value: %q}, connected_endpoints: [{id: %q}, {id: %q}]}`, l.id(), a, b))
}

// EnsureTag returns the id of the tag of a name on a branch, writing it when the branch
// holds none.
func (c *Client) EnsureTag(branch, name string) (string, error) {
	return c.ensureNamed(branch, "BuiltinTag", name, fmt.Sprintf(`{name: {value: %q}}`, name))
}

// EnsureManufacturer returns the id of the manufacturer of a name on a branch, writing it
// when the branch holds none.
func (c *Client) EnsureManufacturer(branch, name string) (string, error) {
	return c.ensureNamed(branch, "OrganizationManufacturer", name, fmt.Sprintf(`{name: {value: %q}}`, name))
}

// EnsurePlatform returns the id of the platform of a name on a branch, writing it, and its
// manufacturer, when the branch holds none. An empty manufacturer is a platform with none,
// which the read refuses as platform.missing. A platform of the name held under another
// manufacturer is refused rather than reused, since a package matches the pair.
func (c *Client) EnsurePlatform(branch, manufacturer, name string) (string, error) {
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`{ DcimPlatform(name__value: %q) { edges { node { id manufacturer { node { name { value } } } } } } }`, name))
	if err != nil {
		return "", fmt.Errorf("looking up platform %q on %s: %w", name, branch, err)
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					ID           string `json:"id"`
					Manufacturer struct {
						Node *struct {
							Name struct {
								Value string `json:"value"`
							} `json:"name"`
						} `json:"node"`
					} `json:"manufacturer"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"DcimPlatform"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return "", err
	}
	if len(r.P.Edges) == 1 {
		held := ""
		if m := r.P.Edges[0].Node.Manufacturer.Node; m != nil {
			held = m.Name.Value
		}
		if held != manufacturer {
			return "", fmt.Errorf("branch %s holds platform %q of manufacturer %q, want %q", branch, name, held, manufacturer)
		}
		return r.P.Edges[0].Node.ID, nil
	}
	if len(r.P.Edges) > 1 {
		return "", fmt.Errorf("branch %s holds %d platforms named %q, want one", branch, len(r.P.Edges), name)
	}
	data := fmt.Sprintf(`{name: {value: %q}`, name)
	if manufacturer != "" {
		m, err := c.EnsureManufacturer(branch, manufacturer)
		if err != nil {
			return "", err
		}
		data += fmt.Sprintf(`, manufacturer: {id: %q}`, m)
	}
	return c.create(branch, "DcimPlatform", data+"}")
}

// EnsureSite returns the id of the lab site on a branch, writing it and each level above
// it the branch lacks: Lab region, Lab country, Lab metro, then lab.
func (c *Client) EnsureSite(branch string) (string, error) {
	parent := ""
	for _, level := range siteLevels {
		data := fmt.Sprintf(`{name: {value: %q}`, level.name)
		if parent != "" {
			data += fmt.Sprintf(`, parent: {id: %q}`, parent)
		}
		id, err := c.ensureNamed(branch, level.kind, level.name, data+"}")
		if err != nil {
			return "", err
		}
		parent = id
	}
	return parent, nil
}

// TagDevices adds the tag of a name, written when the branch holds none, to each named
// device on a branch: the write that brings a device into the scope tag:<name>.
func (c *Client) TagDevices(branch, tag string, devices ...string) error {
	tagID, err := c.EnsureTag(branch, tag)
	if err != nil {
		return err
	}
	for _, d := range devices {
		id, err := c.deviceID(branch, d)
		if err != nil {
			return err
		}
		raw, err := c.GraphQL(branch, fmt.Sprintf(
			`mutation { RelationshipAdd(data: {id: %q, name: "tags", nodes: [{id: %q}]}) { ok } }`, id, tagID))
		if err != nil {
			return fmt.Errorf("tagging %s/%s with %s: %w", branch, d, tag, err)
		}
		if err := okOf(raw, "RelationshipAdd", fmt.Sprintf("tagging %s/%s with %s", branch, d, tag)); err != nil {
			return err
		}
	}
	return nil
}

// ensureNamed returns the id of the one object of a kind with a name on a branch, writing
// it from data when the branch holds none.
func (c *Client) ensureNamed(branch, kind, name, data string) (string, error) {
	found, err := c.ids(branch, kind, fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return "", err
	}
	switch len(found) {
	case 0:
		return c.create(branch, kind, data)
	case 1:
		return found[0], nil
	default:
		return "", fmt.Errorf("branch %s holds %d %s named %q, want one", branch, len(found), kind, name)
	}
}

// generateFor joins devices to the artifact group and renders their artifacts, waiting
// for every artifact on the branch to be Ready. Every seed ends here: a device Fylgja
// can read is a device with a current artifact.
func (c *Client) generateFor(branch string, deviceIDs []string) error {
	if err := c.JoinArtifactGroup(branch, deviceIDs); err != nil {
		return err
	}
	return c.GenerateArtifacts(branch)
}

// SeedFourthNode changes a branch seeded by SeedThreeNode: port ethernet-1/3 on peer,
// device n4 with the peer's platform and site, the tag and the marker, with mgmt0 and
// ethernet-1/1, and a cable n4:ethernet-1/1 <-> peer:ethernet-1/3. It is the change the
// reproducibility proof makes after T, on n1, chosen because the compiler emits it — a
// node, a link and a bootstrap line — so a read that saw it compiles to a different
// topology, not only a different manifest; and a demo's last stage, on n2, beside the third
// link that takes n1's and n3's ethernet-1/3 (D-054). The change is made once per branch: a
// branch that already has n4, or whose peer already has ethernet-1/3, is refused.
func (c *Client) SeedFourthNode(branch, peer string) error {
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`{ DcimDevice(name__value: %q) { edges { node { id platform { node { id } } location { node { id } } } } } }`, peer))
	if err != nil {
		return fmt.Errorf("looking up device %s on %s: %w", peer, branch, err)
	}
	var r struct {
		D struct {
			Edges []struct {
				Node struct {
					ID       string `json:"id"`
					Platform struct {
						Node *struct {
							ID string `json:"id"`
						} `json:"node"`
					} `json:"platform"`
					Location struct {
						Node struct {
							ID string `json:"id"`
						} `json:"node"`
					} `json:"location"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"DcimDevice"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return err
	}
	if len(r.D.Edges) != 1 {
		return fmt.Errorf("branch %s holds %d devices named %s, want one", branch, len(r.D.Edges), peer)
	}
	p := r.D.Edges[0].Node
	if p.Platform.Node == nil {
		return fmt.Errorf("branch %s: device %s has no platform for n4 to share", branch, peer)
	}
	n4s, err := c.ids(branch, "DcimDevice", `(name__value: "n4")`)
	if err != nil {
		return err
	}
	if len(n4s) != 0 {
		return fmt.Errorf("branch %s already holds device n4: the change is made once per branch", branch)
	}
	taken, err := c.ids(branch, "InterfacePhysical", fmt.Sprintf(`(device__name__value: %q, name__value: "ethernet-1/3")`, peer))
	if err != nil {
		return err
	}
	if len(taken) != 0 {
		return fmt.Errorf("branch %s already holds %s:ethernet-1/3: cable n4 to another peer", branch, peer)
	}
	tag, err := c.EnsureTag(branch, FixtureTag)
	if err != nil {
		return err
	}

	peerE3, err := c.createPort(branch, p.ID, "ethernet-1/3", "")
	if err != nil {
		return err
	}
	n4, err := c.createDevice(branch, "n4", p.Platform.Node.ID, p.Location.Node.ID, tag)
	if err != nil {
		return err
	}
	if _, err := c.createPort(branch, n4, "mgmt0", RoleManagement); err != nil {
		return err
	}
	n4e1, err := c.createPort(branch, n4, "ethernet-1/1", "")
	if err != nil {
		return err
	}
	if _, err := c.createCable(branch, linkSpec{"n4", "ethernet-1/1", peer, "ethernet-1/3"}, n4e1, peerE3); err != nil {
		return err
	}
	// n4 is a device like any other: it needs its own artifact, and the peer's changes too
	// (a new cabled port is a new line in the rendering), so the whole branch is
	// regenerated rather than only the addition.
	return c.generateFor(branch, []string{n4})
}

// SeedThirdLink changes a branch seeded by SeedThreeNode without adding a node: port
// ethernet-1/3 on n1 and on n3, and a cable n1:ethernet-1/3 <-> n3:ethernet-1/3. It is the
// change following detects in tier 2 and rebuilds in tier 3, chosen because it moves every
// file a bundle has — two bootstrap lines, the manifest and the topology — so a rebuild
// deploys a different lab. The change is made once per branch: a branch whose n1 already
// has ethernet-1/3 is refused.
func (c *Client) SeedThirdLink(branch string) error {
	n1, err := c.deviceID(branch, "n1")
	if err != nil {
		return err
	}
	n3, err := c.deviceID(branch, "n3")
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "InterfacePhysical", `(device__name__value: "n1", name__value: "ethernet-1/3")`)
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds n1:ethernet-1/3: the change is made once per branch", branch)
	}
	n1e3, err := c.createPort(branch, n1, "ethernet-1/3", "")
	if err != nil {
		return err
	}
	n3e3, err := c.createPort(branch, n3, "ethernet-1/3", "")
	if err != nil {
		return err
	}
	if _, err := c.createCable(branch, linkSpec{"n1", "ethernet-1/3", "n3", "ethernet-1/3"}, n1e3, n3e3); err != nil {
		return err
	}
	// No device is added, but n1's and n3's renderings both gain a port, so both
	// artifacts must be regenerated or the read would return the pre-change bytes.
	return c.GenerateArtifacts(branch)
}

// SeedMixedLink changes a branch seeded by SeedMixed without adding a node: port
// ethernet-1/3 on s1 and Ethernet3 on e1, and a cable between them. It is the change tier
// 3's step case steps over, chosen because it moves the two platforms differently: s1
// gains a bootstrap line and is re-cabled live, while e1 is restarted in place by
// containerlab and returns on its startup configuration, so a step across it needs
// --allow-restart and pushes both. It refuses the durable fixture branch, which holds the
// three-node fixture, and is made once per branch: a branch whose s1 already has
// ethernet-1/3 is refused.
func (c *Client) SeedMixedLink(branch string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("SeedMixedLink refuses branch %s: it holds the three-node fixture, written once and never changed; "+
			"seed a throwaway branch with the mixed fixture instead", branch)
	}
	s1, err := c.deviceID(branch, "s1")
	if err != nil {
		return err
	}
	e1, err := c.deviceID(branch, "e1")
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "InterfacePhysical", `(device__name__value: "s1", name__value: "ethernet-1/3")`)
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds s1:ethernet-1/3: the change is made once per branch", branch)
	}
	s1e3, err := c.createPort(branch, s1, "ethernet-1/3", "")
	if err != nil {
		return err
	}
	e1e3, err := c.createPort(branch, e1, "Ethernet3", "")
	if err != nil {
		return err
	}
	if _, err := c.createCable(branch, linkSpec{"s1", "ethernet-1/3", "e1", "Ethernet3"}, s1e3, e1e3); err != nil {
		return err
	}
	// As SeedThirdLink: no device is added, but s1's and e1's renderings both gain a port,
	// so both artifacts are regenerated. The generate returns before a changed artifact is
	// rewritten; a caller that seals the change waits for the checksums.
	return c.GenerateArtifacts(branch)
}

// ids returns the ids of the kind's objects a filter selects on a branch.
func (c *Client) ids(branch, kind, filter string) ([]string, error) {
	raw, err := c.GraphQL(branch, fmt.Sprintf(`{ %s%s { edges { node { id } } } }`, kind, filter))
	if err != nil {
		return nil, fmt.Errorf("looking up %s%s: %w", kind, filter, err)
	}
	var r map[string]struct {
		Edges []struct {
			Node struct {
				ID string `json:"id"`
			} `json:"node"`
		} `json:"edges"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []string
	for _, e := range r[kind].Edges {
		out = append(out, e.Node.ID)
	}
	return out, nil
}

// SetDeviceDescription changes one device's description on a branch.
//
// The description is the artifact-only change: the CTM carries it nowhere, so the
// topology and the manifest are untouched, while the definition's template prints it in
// the artifact's header (R-11), so the rendered bytes and their checksum move. That makes
// it the cheapest way for a tier to change what a twin runs without changing what it is.
//
// It writes intent and nothing else: the caller regenerates, because Infrahub 1.11.2
// regenerates nothing on its own.
func (c *Client) SetDeviceDescription(branch, device, description string) error {
	return c.setDeviceAttribute(branch, device, "description", description)
}

// SetDeviceSerial changes one device's serial number on a branch.
//
// The serial number is the change that regenerates to identical bytes: neither the CTM nor
// the template reads it, so a regeneration after this leaves every checksum and storage id
// where they were. That is what shows a regeneration alone moves no bundle_id (R-15).
func (c *Client) SetDeviceSerial(branch, device, serial string) error {
	return c.setDeviceAttribute(branch, device, "serial_number", serial)
}

// setDeviceAttribute updates one text attribute of one device, by name.
func (c *Client) setDeviceAttribute(branch, device, attribute, value string) error {
	id, err := c.deviceID(branch, device)
	if err != nil {
		return err
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { DcimDeviceUpdate(data: {id: %q, %s: {value: %q}}) { ok } }`, id, attribute, value))
	if err != nil {
		return fmt.Errorf("setting %s on %s/%s: %w", attribute, branch, device, err)
	}
	return okOf(raw, "DcimDeviceUpdate", fmt.Sprintf("setting %s on %s/%s", attribute, branch, device))
}

// DisablePort sets one port's status to disabled on a branch.
//
// This is the artifact-only change tier 3 makes: the compiler emits no interface's
// `enabled`, so the topology is unchanged, while the template renders `admin-state
// disable` (or `shutdown`) for a disabled port where it rendered it enabled. It is visible
// over gNMI after the push, which is what makes it a read-back rather than a file
// comparison — and it is the artifact taking precedence over the bootstrap, seen live,
// since the bootstrap enables every cabled port and the artifact overrides it.
func (c *Client) DisablePort(branch, device, iface string) error {
	port, err := c.portID(branch, device, iface)
	if err != nil {
		return err
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { InterfacePhysicalUpdate(data: {id: %q, status: {value: %q}}) { ok } }`, port, StatusDisabled))
	if err != nil {
		return fmt.Errorf("disabling %s/%s:%s: %w", branch, device, iface, err)
	}
	return okOf(raw, "InterfacePhysicalUpdate", fmt.Sprintf("disabling %s/%s:%s", branch, device, iface))
}

// DeleteLink deletes the one cable that ends at device's port on a branch, by the cable
// kind's own delete mutation, as the seed creates it. It writes intent and nothing else:
// the ports stay, and each reads no connector. It returns when the delete returned, which a
// test compares with what the event log records (D-048).
func (c *Client) DeleteLink(branch, device, iface string) (time.Time, error) {
	port, err := c.portID(branch, device, iface)
	if err != nil {
		return time.Time{}, err
	}
	cables, err := c.ids(branch, "DcimCable", fmt.Sprintf(`(connected_endpoints__ids: [%q])`, port))
	if err != nil {
		return time.Time{}, err
	}
	if len(cables) != 1 {
		return time.Time{}, fmt.Errorf("branch %s holds %d cables ending at %s:%s, want one", branch, len(cables), device, iface)
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(`mutation { DcimCableDelete(data: {id: %q}) { ok } }`, cables[0]))
	returned := time.Now().UTC()
	if err != nil {
		return time.Time{}, fmt.Errorf("deleting the cable at %s/%s:%s: %w", branch, device, iface, err)
	}
	return returned, okOf(raw, "DcimCableDelete", fmt.Sprintf("deleting the cable at %s/%s:%s", branch, device, iface))
}

// Device is one device a test adds to a branch (AddDevice): its name; the pair of its
// platform, which a package matches exactly, none when Platform is empty and no
// manufacturer when Manufacturer is; the tag it carries, none when empty; its physical ports
// by name, uncabled; and which of them is its management port, none when empty.
type Device struct {
	Name                   string
	Manufacturer, Platform string
	Tag                    string
	Ports                  []string
	Management             string
}

// AddDevice writes one device on a test branch: status active, at the lab site, its
// description the branch's marker, with its platform, its tag and its ports as d gives them.
// It joins no group and renders nothing. It returns the device's id, which is how the read
// names an end on a device it never reads (017; R-05). The fixture is refused, as every
// change is, and so is a device of a name the branch holds.
func (c *Client) AddDevice(branch string, d Device) (string, error) {
	if branch == FixtureBranch {
		return "", fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return "", err
	}
	present, err := c.ids(branch, "DcimDevice", fmt.Sprintf(`(name__value: %q)`, d.Name))
	if err != nil {
		return "", err
	}
	if len(present) != 0 {
		return "", fmt.Errorf("branch %s already holds device %s", branch, d.Name)
	}
	site, err := c.EnsureSite(branch)
	if err != nil {
		return "", err
	}
	platform, tag := "", ""
	if d.Platform != "" {
		if platform, err = c.EnsurePlatform(branch, d.Manufacturer, d.Platform); err != nil {
			return "", err
		}
	}
	if d.Tag != "" {
		if tag, err = c.EnsureTag(branch, d.Tag); err != nil {
			return "", err
		}
	}
	id, err := c.createDevice(branch, d.Name, platform, site, tag)
	if err != nil {
		return "", err
	}
	if id == "" {
		return "", fmt.Errorf("adding device %s on %s: Infrahub returned no id", d.Name, branch)
	}
	for _, p := range d.Ports {
		role := ""
		if p == d.Management {
			role = RoleManagement
		}
		if _, err := c.createPort(branch, id, p, role); err != nil {
			return "", err
		}
	}
	return id, nil
}

// AddCable writes one cable on a test branch, labelled label, joining the physical ports
// named as device:port, any number of them: the cables the read cannot place, of other than
// two ends, beside the two-ended one that reaches outside the scope (017; R-05). It renders
// nothing. The fixture is refused, as every change is.
func (c *Client) AddCable(branch, label string, ends ...string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	peers := make([]string, 0, len(ends))
	for _, e := range ends {
		device, port, ok := strings.Cut(e, ":")
		if !ok {
			return fmt.Errorf("cable %s: end %q is not device:port", label, e)
		}
		id, err := c.portID(branch, device, port)
		if err != nil {
			return err
		}
		peers = append(peers, fmt.Sprintf(`{id: %q}`, id))
	}
	id, err := c.create(branch, "DcimCable", fmt.Sprintf(`{label: {value: %q}, connected_endpoints: [%s]}`,
		label, strings.Join(peers, ", ")))
	if err != nil {
		return err
	}
	if id == "" {
		return fmt.Errorf("adding cable %s on %s: Infrahub returned no id", label, branch)
	}
	return nil
}

// SetDevicePlatform moves one device of a test branch onto the platform of a pair, written
// with its manufacturer when the branch holds neither, or, with an empty platform, takes
// the device's platform away: the writes the read refuses as platform.unmatched and
// platform.missing (017; FR-014). It renders nothing. The fixture is refused, as every
// change is.
func (c *Client) SetDevicePlatform(branch, device, manufacturer, platform string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	id, err := c.deviceID(branch, device)
	if err != nil {
		return err
	}
	// A cardinality-one relationship is taken away by sending it null.
	peer := "null"
	if platform != "" {
		p, err := c.EnsurePlatform(branch, manufacturer, platform)
		if err != nil {
			return err
		}
		peer = fmt.Sprintf(`{id: %q}`, p)
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(`mutation { DcimDeviceUpdate(data: {id: %q, platform: %s}) { ok } }`, id, peer))
	if err != nil {
		return fmt.Errorf("setting the platform of %s/%s: %w", branch, device, err)
	}
	return okOf(raw, "DcimDeviceUpdate", fmt.Sprintf("setting the platform of %s/%s", branch, device))
}

// AddVirtualInterface writes one InterfaceVirtual on a test branch's device, with no parent
// and no role. The read never reads it (FR-003), but it is the device's intent: its stamp is
// among the device's, since a transform may render it (FR-023; 017 research R-10). It renders
// nothing. The fixture is refused, as every change is, and so is a second interface of the
// name on the device.
func (c *Client) AddVirtualInterface(branch, device, name string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	dev, err := c.deviceID(branch, device)
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "DcimInterface", fmt.Sprintf(`(device__name__value: %q, name__value: %q)`, device, name))
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds %s:%s", branch, device, name)
	}
	id, err := c.create(branch, "InterfaceVirtual", fmt.Sprintf(`{name: {value: %q}, device: {id: %q}}`, name, dev))
	if err != nil {
		return err
	}
	if id == "" {
		return fmt.Errorf("adding %s:%s on %s: Infrahub returned no id", device, name, branch)
	}
	return nil
}

// SetPlatformDescription changes the description of the one platform of a name on a test
// branch: a write on a node every device on the platform reaches, which the template does
// not render (017 research R-10, §5.8). The fixture is refused, as every change is.
func (c *Client) SetPlatformDescription(branch, platform, description string) error {
	return c.setNamedDescription(branch, "DcimPlatform", platform, description)
}

// SetManufacturerDescription changes the description of the one manufacturer of a name on
// a test branch: a write every device reaches through its platform, which the template does
// not render (017 research R-10, §5.8). The fixture is refused, as every change is.
func (c *Client) SetManufacturerDescription(branch, manufacturer, description string) error {
	return c.setNamedDescription(branch, "OrganizationManufacturer", manufacturer, description)
}

// setNamedDescription updates the description of the one object of a kind with a name on a
// test branch.
func (c *Client) setNamedDescription(branch, kind, name, description string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	found, err := c.ids(branch, kind, fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return err
	}
	if len(found) != 1 {
		return fmt.Errorf("branch %s holds %d %s named %q, want one", branch, len(found), kind, name)
	}
	what := fmt.Sprintf("setting the description of %s %q on %s", kind, name, branch)
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { %sUpdate(data: {id: %q, description: {value: %q}}) { ok } }`, kind, found[0], description))
	if err != nil {
		return fmt.Errorf("%s: %w", what, err)
	}
	return okOf(raw, kind+"Update", what)
}

// ReEndCable gives the one cable that ends at device's port on a test branch the ends
// named as device:port, in place of the ones it had: a port dropped from it reads no
// connector after. It moves no stamp, and the cable's and the dropped port's events are how
// it is seen (017 research §5.8). It renders nothing. The fixture is refused, as every change
// is.
func (c *Client) ReEndCable(branch, device, iface string, ends ...string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	port, err := c.portID(branch, device, iface)
	if err != nil {
		return err
	}
	cables, err := c.ids(branch, "DcimCable", fmt.Sprintf(`(connected_endpoints__ids: [%q])`, port))
	if err != nil {
		return err
	}
	if len(cables) != 1 {
		return fmt.Errorf("branch %s holds %d cables ending at %s:%s, want one", branch, len(cables), device, iface)
	}
	peers := make([]string, 0, len(ends))
	for _, e := range ends {
		d, p, ok := strings.Cut(e, ":")
		if !ok {
			return fmt.Errorf("re-ending the cable at %s:%s: end %q is not device:port", device, iface, e)
		}
		id, err := c.portID(branch, d, p)
		if err != nil {
			return err
		}
		peers = append(peers, fmt.Sprintf(`{id: %q}`, id))
	}
	what := fmt.Sprintf("re-ending the cable at %s/%s:%s to %v", branch, device, iface, ends)
	raw, err := c.GraphQL(branch, fmt.Sprintf(`mutation { DcimCableUpdate(data: {id: %q, connected_endpoints: [%s]}) { ok } }`,
		cables[0], strings.Join(peers, ", ")))
	if err != nil {
		return fmt.Errorf("%s: %w", what, err)
	}
	return okOf(raw, "DcimCableUpdate", what)
}

// deviceID returns the one device of a name on a branch.
func (c *Client) deviceID(branch, name string) (string, error) {
	found, err := c.ids(branch, "DcimDevice", fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return "", err
	}
	if len(found) != 1 {
		return "", fmt.Errorf("branch %s holds %d devices named %s, want one", branch, len(found), name)
	}
	return found[0], nil
}

// portID returns the one physical port of a name on a device on a branch.
func (c *Client) portID(branch, device, name string) (string, error) {
	found, err := c.ids(branch, "InterfacePhysical", fmt.Sprintf(`(device__name__value: %q, name__value: %q)`, device, name))
	if err != nil {
		return "", err
	}
	if len(found) != 1 {
		return "", fmt.Errorf("branch %s holds %d ports named %s on %s, want one", branch, len(found), name, device)
	}
	return found[0], nil
}

// okOf reports whether a mutation returned ok, so a write that Infrahub accepted but did
// not apply is not mistaken for a success.
func okOf(raw []byte, mutation, what string) error {
	var r map[string]struct {
		OK bool `json:"ok"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return err
	}
	if !r[mutation].OK {
		return fmt.Errorf("%s: mutation returned ok: false", what)
	}
	return nil
}

// DeviceNames returns every device's name on a branch, sorted, so a change flag can act
// on all of them without the caller naming each.
func (c *Client) DeviceNames(branch string) ([]string, error) {
	raw, err := c.GraphQL(branch, `{ DcimDevice { edges { node { name { value } } } } }`)
	if err != nil {
		return nil, fmt.Errorf("listing devices on %s: %w", branch, err)
	}
	var r struct {
		D struct {
			Edges []struct {
				Node struct {
					Name struct {
						Value string `json:"value"`
					} `json:"name"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"DcimDevice"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []string
	for _, e := range r.D.Edges {
		out = append(out, e.Node.Name.Value)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("branch %s holds no devices; seed it first", branch)
	}
	sort.Strings(out)
	return out, nil
}
