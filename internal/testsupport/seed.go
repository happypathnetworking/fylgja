//go:build contract || fixture

package testsupport

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// ContractVersion is the generics contract version the fixture declares. It is the
// version Fylgja is built against: a fixture declaring anything else would be rejected
// by every compile, which is the point of the check.
const ContractVersion = ctm.ContractVersion

// FixtureBranch is the durable branch the three-node fixture lives on.
const FixtureBranch = "fylgja-fixture"

// MarkerPrefix is what every seeded device's role carries, so that an artifact rendered
// from it is recognisable wherever it might leak. The definition's template writes the
// role into the artifact's comment line, so a grep for this string over a finding, a
// log, an event, a payload or a record proves no content escaped.
const MarkerPrefix = "FYLGJA-MARKER"

// MarkerRole is the role value the seed writes on a branch, and the value a tier greps
// for. The suffix is the branch's, so two branches never share a marker and a leak can
// be traced to the branch that produced it: "fixture" for the durable fixture branch,
// whose value is fixed because the branch is written once, and the branch name
// with its fylgja- prefix stripped for a throwaway.
func MarkerRole(branch string) string {
	suffix := "fixture"
	if branch != FixtureBranch {
		suffix = strings.TrimPrefix(branch, "fylgja-")
	}
	return "leaf-" + MarkerPrefix + "-" + suffix
}

// nodeSpec describes one fixture device.
type nodeSpec struct {
	name     string
	loopback string
	// data ports, in production naming
	ports []string
}

// linkSpec is one fixture link.
type linkSpec struct {
	aDev, aPort string
	bDev, bPort string
}

// The three-node fixture: a triangle, so every node has two cabled
// ports, one management port, and one loopback. Small enough to boot on a small host, and
// large enough that link ordering and per-node port ordering are actually exercised.
var (
	fixtureNodes = []nodeSpec{
		{name: "n1", loopback: "10.0.0.1/32", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "n2", loopback: "10.0.0.2/32", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "n3", loopback: "10.0.0.3/32", ports: []string{"ethernet-1/1", "ethernet-1/2"}},
	}
	fixtureLinks = []linkSpec{
		{"n1", "ethernet-1/1", "n2", "ethernet-1/1"},
		{"n2", "ethernet-1/2", "n3", "ethernet-1/1"},
		{"n3", "ethernet-1/2", "n1", "ethernet-1/2"},
	}
)

// SeedThreeNode populates the three-node fixture on a branch. It is idempotent at the
// branch level: seeding a branch that already has devices is a no-op.
func (c *Client) SeedThreeNode(branch string) error {
	data, err := c.GraphQL(branch, `{ FylgjaDevice { count } }`)
	if err == nil {
		var r struct {
			D struct {
				Count int `json:"count"`
			} `json:"FylgjaDevice"`
		}
		if json_Unmarshal(data, &r) == nil && r.D.Count > 0 {
			return nil
		}
	}

	if _, err := c.create(branch, "FylgjaContract",
		fmt.Sprintf(`{version: {value: %q}}`, ContractVersion)); err != nil {
		return err
	}

	platform, err := c.create(branch, "NetworkPlatform",
		`{vendor: {value: "nokia"}, nos: {value: "srlinux"}, version: {value: "24.7"}}`)
	if err != nil {
		return err
	}

	ifaceIDs := map[string]string{} // "device:interface" -> id
	var deviceIDs []string
	for _, n := range fixtureNodes {
		dev, err := c.create(branch, "NetworkDevice",
			fmt.Sprintf(`{name: {value: %q}, platform: {id: %q}, role: {value: %q}}`,
				n.name, platform, MarkerRole(branch)))
		if err != nil {
			return err
		}
		deviceIDs = append(deviceIDs, dev)
		// Management port: physical by kind, out-of-band by use (D-003).
		if _, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: "mgmt0"}, iftype: {value: "physical"}, mgmt_only: {value: true}, device: {id: %q}}`,
			dev)); err != nil {
			return err
		}
		if _, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: "lo0"}, iftype: {value: "loopback"}, device: {id: %q}}`, dev)); err != nil {
			return err
		}
		for _, p := range n.ports {
			id, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
				`{name: {value: %q}, iftype: {value: "physical"}, device: {id: %q}}`, p, dev))
			if err != nil {
				return err
			}
			ifaceIDs[n.name+":"+p] = id
		}
	}

	for _, l := range fixtureLinks {
		a, b := ifaceIDs[l.aDev+":"+l.aPort], ifaceIDs[l.bDev+":"+l.bPort]
		if a == "" || b == "" {
			return fmt.Errorf("fixture link references an interface that was not created: %+v", l)
		}
		if _, err := c.create(branch, "NetworkLink",
			fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, a, b)); err != nil {
			return err
		}
	}

	// The devices are targets only once they are in the group, and Infrahub renders
	// nothing on its own, so a seed that stopped here would leave every read refusing
	// artifact.missing. The wait is what makes a seeded branch readable at once: a read that
	// follows a seed is never refused for an artifact that is merely not ready yet.
	return c.generateFor(branch, deviceIDs)
}

// mixedNode is one device of the mixed fixture: its platform, the names that platform
// gives its management port and its loopback, and its data ports in production naming.
// Every name is one a booted node of that platform carried.
type mixedNode struct {
	name             string
	vendor, nos, ver string
	mgmt, loopback   string
	ports            []string
}

// The mixed fixture, the live twin of testdata/ctm/mixed.json: one
// node of the first platform and two of the second, cabled in a triangle so that every
// link crosses something — the two platforms on a plain port, the second platform to
// itself on a modular port, and the platforms again on a breakout lane.
var (
	mixedNodes = []mixedNode{
		{name: "s1", vendor: "nokia", nos: "srlinux", ver: "24.7", mgmt: "mgmt0", loopback: "lo0",
			ports: []string{"ethernet-1/1", "ethernet-1/2"}},
		{name: "e1", vendor: "arista", nos: "eos", ver: "4.32", mgmt: "Management1", loopback: "Loopback0",
			ports: []string{"Ethernet1", "Ethernet2/1"}},
		{name: "e2", vendor: "arista", nos: "eos", ver: "4.32", mgmt: "Management1", loopback: "Loopback0",
			ports: []string{"Ethernet1", "Ethernet3/1/1"}},
	}
	mixedLinks = []linkSpec{
		{"s1", "ethernet-1/1", "e1", "Ethernet1"},
		{"e1", "Ethernet2/1", "e2", "Ethernet1"},
		{"e2", "Ethernet3/1/1", "s1", "ethernet-1/2"},
	}
)

// SeedMixed populates the mixed fixture on a throwaway branch: the contract singleton,
// one NetworkPlatform per platform, the three devices with their interfaces and links,
// every device under the branch's marker role, then the group join and the generation
// every seed ends with.
//
// It is idempotent at the branch level, as SeedThreeNode is, and it refuses the durable
// fixture branch as every change flag does: that branch holds the three-node fixture,
// written once, and every test and twin built from it relies on its bundle_id staying put.
func (c *Client) SeedMixed(branch string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("SeedMixed refuses branch %s: it holds the three-node fixture, written once and never changed; "+
			"seed a throwaway branch instead", branch)
	}
	data, err := c.GraphQL(branch, `{ FylgjaDevice { count } }`)
	if err == nil {
		var r struct {
			D struct {
				Count int `json:"count"`
			} `json:"FylgjaDevice"`
		}
		if json_Unmarshal(data, &r) == nil && r.D.Count > 0 {
			return nil
		}
	}

	if _, err := c.create(branch, "FylgjaContract",
		fmt.Sprintf(`{version: {value: %q}}`, ContractVersion)); err != nil {
		return err
	}

	platforms := map[string]string{} // nos -> id
	ifaceIDs := map[string]string{}  // "device:interface" -> id
	var deviceIDs []string
	for _, n := range mixedNodes {
		if platforms[n.nos] == "" {
			id, err := c.create(branch, "NetworkPlatform", fmt.Sprintf(
				`{vendor: {value: %q}, nos: {value: %q}, version: {value: %q}}`, n.vendor, n.nos, n.ver))
			if err != nil {
				return err
			}
			platforms[n.nos] = id
		}
		dev, err := c.create(branch, "NetworkDevice",
			fmt.Sprintf(`{name: {value: %q}, platform: {id: %q}, role: {value: %q}}`,
				n.name, platforms[n.nos], MarkerRole(branch)))
		if err != nil {
			return err
		}
		deviceIDs = append(deviceIDs, dev)
		// Management port: physical by kind, out-of-band by use (D-003). Each platform
		// calls it what it calls it; the profile's management rule applies to whichever
		// interface intent marked out-of-band, never to a name.
		if _, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: "physical"}, mgmt_only: {value: true}, device: {id: %q}}`,
			n.mgmt, dev)); err != nil {
			return err
		}
		if _, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: "loopback"}, device: {id: %q}}`, n.loopback, dev)); err != nil {
			return err
		}
		for _, p := range n.ports {
			id, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
				`{name: {value: %q}, iftype: {value: "physical"}, device: {id: %q}}`, p, dev))
			if err != nil {
				return err
			}
			ifaceIDs[n.name+":"+p] = id
		}
	}

	for _, l := range mixedLinks {
		a, b := ifaceIDs[l.aDev+":"+l.aPort], ifaceIDs[l.bDev+":"+l.bPort]
		if a == "" || b == "" {
			return fmt.Errorf("mixed link references an interface that was not created: %+v", l)
		}
		if _, err := c.create(branch, "NetworkLink",
			fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, a, b)); err != nil {
			return err
		}
	}

	return c.generateFor(branch, deviceIDs)
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

// SeedFourthNode changes a branch seeded by SeedThreeNode: interface ethernet-1/3 on n1,
// device n4 on the same platform with mgmt0, lo0 and ethernet-1/1, and a link
// n4:ethernet-1/1 <-> n1:ethernet-1/3. It is the change the reproducibility proof makes
// after T, chosen because the compiler emits it — a node, a link and a bootstrap line —
// so a read that saw it compiles to a different topology, not only a different manifest.
// The change is made once per branch: a branch that already has n4 is
// refused.
func (c *Client) SeedFourthNode(branch string) error {
	ids := func(kind, filter string) ([]string, error) { return c.ids(branch, kind, filter) }

	platforms, err := ids("NetworkPlatform", "")
	if err != nil {
		return err
	}
	if len(platforms) != 1 {
		return fmt.Errorf("branch %s holds %d platforms, want the fixture's one", branch, len(platforms))
	}
	n1s, err := ids("NetworkDevice", `(name__value: "n1")`)
	if err != nil {
		return err
	}
	if len(n1s) != 1 {
		return fmt.Errorf("branch %s holds %d devices named n1, want one", branch, len(n1s))
	}
	n4s, err := ids("NetworkDevice", `(name__value: "n4")`)
	if err != nil {
		return err
	}
	if len(n4s) != 0 {
		return fmt.Errorf("branch %s already holds device n4: the change is made once per branch", branch)
	}

	iface := func(device, name, iftype, extra string) (string, error) {
		return c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: %q}, device: {id: %q}%s}`, name, iftype, device, extra))
	}

	n1e3, err := iface(n1s[0], "ethernet-1/3", "physical", "")
	if err != nil {
		return err
	}
	n4, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "n4"}, platform: {id: %q}, role: {value: %q}}`,
			platforms[0], MarkerRole(branch)))
	if err != nil {
		return err
	}
	if _, err := iface(n4, "mgmt0", "physical", `, mgmt_only: {value: true}`); err != nil {
		return err
	}
	if _, err := iface(n4, "lo0", "loopback", ""); err != nil {
		return err
	}
	n4e1, err := iface(n4, "ethernet-1/1", "physical", "")
	if err != nil {
		return err
	}
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, n4e1, n1e3)); err != nil {
		return err
	}
	// n4 is a device like any other: it needs its own artifact, and n1's changes too
	// (a new cabled port is a new line in the rendering), so the whole branch is
	// regenerated rather than only the addition.
	return c.generateFor(branch, []string{n4})
}

// SeedThirdLink changes a branch seeded by SeedThreeNode without adding a node:
// interface ethernet-1/3 on n1 and on n3, and a link n1:ethernet-1/3 <-> n3:ethernet-1/3.
// It is the change following detects in tier 2 and rebuilds in tier 3, chosen because it
// moves every file a bundle has — two bootstrap lines, the manifest and the topology — so
// a rebuild deploys a different lab. The change is made once per branch:
// a branch whose n1 already has ethernet-1/3 is refused.
func (c *Client) SeedThirdLink(branch string) error {
	device := func(name string) (string, error) {
		found, err := c.ids(branch, "NetworkDevice", fmt.Sprintf(`(name__value: %q)`, name))
		if err != nil {
			return "", err
		}
		if len(found) != 1 {
			return "", fmt.Errorf("branch %s holds %d devices named %s, want one", branch, len(found), name)
		}
		return found[0], nil
	}
	n1, err := device("n1")
	if err != nil {
		return err
	}
	n3, err := device("n3")
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "NetworkInterface", `(device__name__value: "n1", name__value: "ethernet-1/3")`)
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds n1:ethernet-1/3: the change is made once per branch", branch)
	}

	iface := func(device string) (string, error) {
		return c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: "ethernet-1/3"}, iftype: {value: "physical"}, device: {id: %q}}`, device))
	}
	n1e3, err := iface(n1)
	if err != nil {
		return err
	}
	n3e3, err := iface(n3)
	if err != nil {
		return err
	}
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, n1e3, n3e3)); err != nil {
		return err
	}
	// No device is added, but n1's and n3's renderings both gain a port, so both
	// artifacts must be regenerated or the read would return the pre-change bytes.
	return c.GenerateArtifacts(branch)
}

// SeedMixedLink changes a branch seeded by SeedMixed without adding a node: interface
// ethernet-1/3 on s1 and Ethernet3 on e1, and a link between them. It is the change tier 3's
// step case steps over, chosen because it
// moves the two platforms differently: s1 gains a bootstrap line and is re-cabled live,
// while e1 is restarted in place by containerlab and returns on its startup configuration,
// so a step across it needs --allow-restart and pushes both. It refuses the
// durable fixture branch, which holds the three-node fixture, and is made once per branch:
// a branch whose s1 already has ethernet-1/3 is refused.
func (c *Client) SeedMixedLink(branch string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("SeedMixedLink refuses branch %s: it holds the three-node fixture, written once and never changed; "+
			"seed a throwaway branch with the mixed fixture instead", branch)
	}
	device := func(name string) (string, error) {
		found, err := c.ids(branch, "NetworkDevice", fmt.Sprintf(`(name__value: %q)`, name))
		if err != nil {
			return "", err
		}
		if len(found) != 1 {
			return "", fmt.Errorf("branch %s holds %d devices named %s, want the mixed fixture's one", branch, len(found), name)
		}
		return found[0], nil
	}
	s1, err := device("s1")
	if err != nil {
		return err
	}
	e1, err := device("e1")
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "NetworkInterface", `(device__name__value: "s1", name__value: "ethernet-1/3")`)
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds s1:ethernet-1/3: the change is made once per branch", branch)
	}

	iface := func(device, name string) (string, error) {
		return c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: "physical"}, device: {id: %q}}`, name, device))
	}
	s1e3, err := iface(s1, "ethernet-1/3")
	if err != nil {
		return err
	}
	e1e3, err := iface(e1, "Ethernet3")
	if err != nil {
		return err
	}
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, s1e3, e1e3)); err != nil {
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

// SeedContractVersion creates the contract singleton with a chosen version. Used by
// tests that need a branch declaring a contract Fylgja does not understand.
func (c *Client) SeedContractVersion(branch, version string) error {
	_, err := c.create(branch, "FylgjaContract", fmt.Sprintf(`{version: {value: %q}}`, version))
	return err
}

// LoadGenericsOnly loads just the generics contract, without the reference schema that
// provides concrete kinds. The result is a branch that defines Fylgja's generics but
// has nothing implementing them.
func (c *Client) LoadGenericsOnly(branch, schemaDir string) error {
	dir, err := os.MkdirTemp("", "fylgja-generics-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.RemoveAll(dir) }()
	src, err := os.ReadFile(filepath.Join(schemaDir, "fylgja-generics.yaml"))
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "fylgja-generics.yaml"), src, 0o644); err != nil {
		return err
	}
	return c.LoadSchema(branch, dir)
}

// Defect names the five defects SeedDefects plants, by the rule each one trips. They
// are exactly the defects Infrahub's own schema will let a branch hold: every other
// rule Fylgja enforces is one Infrahub enforces first, and a branch cannot be made to
// violate it (verified read-only). The rest stay covered by the CTM
// fixtures under testdata/ctm/defects, which is where a hand-edited or foreign CTM is
// caught anyway.
const (
	DefectIftypeUnimplemented = "interface.iftype.unimplemented"
	DefectMgmtOnlyIftype      = "interface.mgmt_only.iftype"
	DefectPlatformUnsupported = "platform.unsupported"
	DefectLinkSameDevice      = "link.endpoints.same_device"
	DefectLinkEndpointIftype  = "link.endpoint.iftype"
)

// SeededDefects is the set of rules a branch seeded by SeedDefects must trip, all in
// one pass.
var SeededDefects = []string{
	DefectIftypeUnimplemented,
	DefectMgmtOnlyIftype,
	DefectPlatformUnsupported,
	DefectLinkSameDevice,
	DefectLinkEndpointIftype,
}

// SeededDefectObjects names the object each seeded defect is reported against, in the
// CTM's identity scheme (device, device:interface, or a canonical link id). Asserting
// on these rather than on rules alone is what proves the read names *which* thing is
// wrong, not merely that something is.
var SeededDefectObjects = map[string]string{
	DefectIftypeUnimplemented: "d1:vlan100",
	DefectMgmtOnlyIftype:      "d1:lo0",
	DefectPlatformUnsupported: "d3",
	DefectLinkSameDevice:      "d1:ethernet-1/1|d1:ethernet-1/2",
	DefectLinkEndpointIftype:  "d1:lo1|d2:ethernet-1/1",
}

// SeedDefects populates a branch with intent that is well-formed for Infrahub and
// unbuildable for Fylgja, so a read reports all five defects in one pass and writes
// no CTM.
//
// The layout is deliberate. `platform.unsupported` stops validation of that device's
// interfaces, so the unsupported platform gets a device of its own (d3) and the two
// interface defects live on a device Fylgja does support (d1). The two link defects
// need distinct links: one folded back onto a single device, one reaching a loopback.
func (c *Client) SeedDefects(branch string) error {
	if _, err := c.create(branch, "FylgjaContract",
		fmt.Sprintf(`{version: {value: %q}}`, ContractVersion)); err != nil {
		return err
	}

	supported, err := c.create(branch, "NetworkPlatform",
		`{vendor: {value: "nokia"}, nos: {value: "srlinux"}, version: {value: "24.7"}}`)
	if err != nil {
		return err
	}
	// Free text, so Infrahub stores it happily and Fylgja has no support package for
	// it — which is the whole defect.
	unsupported, err := c.create(branch, "NetworkPlatform",
		`{vendor: {value: "acme"}, nos: {value: "acme_os"}}`)
	if err != nil {
		return err
	}

	d1, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d1"}, platform: {id: %q}, role: {value: "leaf"}}`, supported))
	if err != nil {
		return err
	}
	d2, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d2"}, platform: {id: %q}, role: {value: "leaf"}}`, supported))
	if err != nil {
		return err
	}
	// platform.unsupported: nothing else about d3 is ever examined, so it needs no
	// interfaces.
	d3, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d3"}, platform: {id: %q}, role: {value: "leaf"}}`, unsupported))
	if err != nil {
		return err
	}

	iface := func(device, name, iftype, extra string) (string, error) {
		return c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: %q}, device: {id: %q}%s}`, name, iftype, device, extra))
	}

	// Two cabled ports on one device, so a link can be folded back onto it.
	d1e1, err := iface(d1, "ethernet-1/1", "physical", "")
	if err != nil {
		return err
	}
	d1e2, err := iface(d1, "ethernet-1/2", "physical", "")
	if err != nil {
		return err
	}
	// interface.iftype.unimplemented: svi is in the contract's vocabulary and is a
	// dropdown choice on the reference schema, so Infrahub accepts it.
	if _, err := iface(d1, "vlan100", "svi", ""); err != nil {
		return err
	}
	// interface.mgmt_only.iftype: mgmt_only is a plain boolean on any kind, so a
	// loopback can carry it — and means nothing when it does.
	if _, err := iface(d1, "lo0", "loopback", `, mgmt_only: {value: true}`); err != nil {
		return err
	}
	// link.endpoint.iftype: a loopback with a link on it.
	d1lo1, err := iface(d1, "lo1", "loopback", "")
	if err != nil {
		return err
	}
	d2e1, err := iface(d2, "ethernet-1/1", "physical", "")
	if err != nil {
		return err
	}

	// link.endpoints.same_device: two endpoints satisfy min 2 / max 2 even when both
	// are on one device.
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, d1e1, d1e2)); err != nil {
		return err
	}
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, d1lo1, d2e1)); err != nil {
		return err
	}
	// Every device renders its artifact, as every seed's do, so the five
	// defects are the only findings: no artifact.missing beside them. d3's is rendered
	// too and never selected, since no package names the artifact its platform takes.
	return c.generateFor(branch, []string{d1, d2, d3})
}

// SetDeviceRole changes one device's role on a branch.
//
// Role is the artifact-only change: the compiler emits it nowhere, so
// the topology and the manifest are untouched, while the definition's template prints it
// in the artifact's comment line, so the rendered bytes and their checksum move. That
// makes it the cheapest way for a tier to change what a twin runs without changing what
// it is.
//
// It writes intent and nothing else: the caller regenerates, because Infrahub 1.11.2
// regenerates nothing on its own.
func (c *Client) SetDeviceRole(branch, device, role string) error {
	return c.setDeviceAttribute(branch, device, "role", role)
}

// SetDeviceSite changes one device's site on a branch.
//
// Site is the change that regenerates to identical bytes: the template queries it
// and prints nothing from it, so a regeneration after this leaves every checksum and
// storage id where they were. That is what shows a regeneration alone moves no bundle_id.
func (c *Client) SetDeviceSite(branch, device, site string) error {
	return c.setDeviceAttribute(branch, device, "site", site)
}

// setDeviceAttribute updates one string attribute of one device, by name.
func (c *Client) setDeviceAttribute(branch, device, attribute, value string) error {
	id, err := c.deviceID(branch, device)
	if err != nil {
		return err
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { NetworkDeviceUpdate(data: {id: %q, %s: {value: %q}}) { ok } }`, id, attribute, value))
	if err != nil {
		return fmt.Errorf("setting %s on %s/%s: %w", attribute, branch, device, err)
	}
	return okOf(raw, "NetworkDeviceUpdate", fmt.Sprintf("setting %s on %s/%s", attribute, branch, device))
}

// DisablePort sets one interface's admin state to disabled on a branch.
//
// This is the artifact-only change tier 3 makes: the compiler emits no interface's
// `enabled`, so the topology is unchanged, while the template renders `admin-state
// disable` where it rendered `enable`. It is visible over gNMI after the push, which is
// what makes it a read-back rather than a file comparison — and it is the artifact
// taking precedence over the bootstrap, seen live, since the bootstrap enables every cabled port and the artifact
// overrides it.
func (c *Client) DisablePort(branch, device, iface string) error {
	found, err := c.ids(branch, "NetworkInterface",
		fmt.Sprintf(`(device__name__value: %q, name__value: %q)`, device, iface))
	if err != nil {
		return err
	}
	if len(found) != 1 {
		return fmt.Errorf("branch %s holds %d interfaces named %s on %s, want one", branch, len(found), iface, device)
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { NetworkInterfaceUpdate(data: {id: %q, enabled: {value: false}}) { ok } }`, found[0]))
	if err != nil {
		return fmt.Errorf("disabling %s/%s:%s: %w", branch, device, iface, err)
	}
	return okOf(raw, "NetworkInterfaceUpdate", fmt.Sprintf("disabling %s/%s:%s", branch, device, iface))
}

// deviceID returns the one device of a name on a branch.
func (c *Client) deviceID(branch, name string) (string, error) {
	found, err := c.ids(branch, "NetworkDevice", fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return "", err
	}
	if len(found) != 1 {
		return "", fmt.Errorf("branch %s holds %d devices named %s, want one", branch, len(found), name)
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
	raw, err := c.GraphQL(branch, `{ NetworkDevice { edges { node { name { value } } } } }`)
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
		} `json:"NetworkDevice"`
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
