//go:build contract || fixture

package testsupport

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// DefaultBranch is Infrahub's default branch, where a demo's baseline lives (D-054).
const DefaultBranch = "main"

// baselineKinds are the schema library's kinds a baseline is made of, in the order
// -clear-main deletes them: an address before its port, a cable before its ports, a port
// before its device, a device
// before its platform, its site and its tag, a platform before its manufacturer, and a
// location before its parent. Each is counted beside the generic it implements, where it
// has one, so that an object of another kind implementing the generic is seen too.
var baselineKinds = []struct{ concrete, generic string }{
	{"IpamIPAddress", "BuiltinIPAddress"},
	{"DcimCable", "DcimConnector"},
	{"InterfacePhysical", "DcimInterface"},
	{"DcimDevice", "DcimGenericDevice"},
	{"DcimPlatform", ""},
	{"OrganizationManufacturer", "OrganizationGeneric"},
	{"LocationSite", "LocationGeneric"},
	{"LocationMetro", "LocationGeneric"},
	{"LocationCountry", "LocationGeneric"},
	{"LocationRegion", "LocationGeneric"},
	{"BuiltinTag", ""},
}

// SeedMainBaseline writes D-054's baseline onto main: the three-node fixture in the schema
// library's kinds, its devices joined to the artifact group and their artifacts rendered
// and Ready, as SeedThreeNode writes it on a branch. It refuses a main that holds anything
// of the baseline's kinds (the tag, the manufacturer, the platform, the locations, the
// devices, their ports, cables and addresses), so it never adds to a network and never runs twice.
func (c *Client) SeedMainBaseline() error {
	held, err := c.baselineCounts(DefaultBranch)
	if err != nil {
		return err
	}
	if len(held) > 0 {
		return fmt.Errorf("main already holds %s: the baseline is written only onto a main that holds no network (D-054); "+
			"remove it with -clear-main first", strings.Join(held, ", "))
	}
	return c.SeedThreeNode(DefaultBranch)
}

// ClearedBaseline counts what ClearMainBaseline deleted. Locations counts the site and the
// three levels above it. Artifacts counts the baseline's artifacts it deleted itself;
// ArtifactsWithDevices those Infrahub had already removed with their devices.
type ClearedBaseline struct {
	Addresses, Cables, Interfaces, Devices, Platforms, Manufacturers, Locations, Tags int
	Artifacts, ArtifactsWithDevices                                                   int
}

// ClearMainBaseline deletes what SeedMainBaseline wrote, and nothing else (D-054). It
// refuses while any test branch exists, since the window closes after every demo branch
// is deleted, and when main holds anything beyond the baseline, such as a merged change,
// naming what it found; either refusal deletes nothing. Then it deletes the addresses, the
// cables, the ports, the devices, the platform, the manufacturer, the site and the levels above it,
// and the tag, and last any of the devices' artifacts Infrahub left behind.
func (c *Client) ClearMainBaseline() (ClearedBaseline, error) {
	var done ClearedBaseline
	open, err := c.testBranches()
	if err != nil {
		return done, err
	}
	if len(open) > 0 {
		return done, fmt.Errorf("test branches still exist (%s): delete each with -delete before the baseline is removed (D-054); "+
			"nothing was deleted", strings.Join(open, ", "))
	}
	return c.clearBaseline(DefaultBranch)
}

// clearBaseline deletes a branch's baseline, refusing, deleting nothing, a branch that
// holds anything beyond it or nothing of it. ClearMainBaseline runs it on main; on any
// other branch it is the same deletion, which is how it is proved without a window open.
func (c *Client) clearBaseline(branch string) (ClearedBaseline, error) {
	var done ClearedBaseline
	inv, err := c.readBaseline(branch)
	if err != nil {
		return done, err
	}
	if extra := inv.beyondBaseline(); len(extra) > 0 {
		return done, fmt.Errorf("%s holds more than the baseline: %s; nothing was deleted", branch, strings.Join(extra, "; "))
	}
	if inv.empty() {
		return done, fmt.Errorf("%s holds no baseline: nothing to remove", branch)
	}

	artifacts, err := c.artifactsOf(branch, values(inv.devices))
	if err != nil {
		return done, err
	}
	for _, k := range baselineKinds {
		for _, id := range values(inv.objects[k.concrete]) {
			if err := c.deleteNode(branch, k.concrete, id); err != nil {
				return done, err
			}
			*done.counter(k.concrete)++
		}
	}
	left, err := c.existing(branch, "CoreArtifact", artifacts)
	if err != nil {
		return done, err
	}
	done.ArtifactsWithDevices = len(artifacts) - len(left)
	for _, id := range left {
		if err := c.deleteNode(branch, "CoreArtifact", id); err != nil {
			return done, err
		}
		done.Artifacts++
	}
	return done, nil
}

// counter is the count a deletion of a kind adds to.
func (d *ClearedBaseline) counter(kind string) *int {
	switch kind {
	case "IpamIPAddress":
		return &d.Addresses
	case "DcimCable":
		return &d.Cables
	case "InterfacePhysical":
		return &d.Interfaces
	case "DcimDevice":
		return &d.Devices
	case "DcimPlatform":
		return &d.Platforms
	case "OrganizationManufacturer":
		return &d.Manufacturers
	case "BuiltinTag":
		return &d.Tags
	default:
		return &d.Locations
	}
}

// baselineCounts names each baseline kind a branch holds objects of, with how many.
func (c *Client) baselineCounts(branch string) ([]string, error) {
	var held []string
	seen := map[string]bool{}
	for _, k := range baselineKinds {
		for _, kind := range []string{k.concrete, k.generic} {
			if kind == "" || seen[kind] {
				continue
			}
			seen[kind] = true
			n, err := c.count(branch, kind)
			if err != nil {
				return nil, err
			}
			if n > 0 {
				held = append(held, fmt.Sprintf("%d %s", n, kind))
			}
		}
	}
	return held, nil
}

// count returns how many objects of a kind a branch holds.
func (c *Client) count(branch, kind string) (int, error) {
	raw, err := c.GraphQL(branch, fmt.Sprintf(`{ %s { count } }`, kind))
	if err != nil {
		return 0, fmt.Errorf("counting %s on %s: %w", kind, branch, err)
	}
	var r map[string]struct {
		Count int `json:"count"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return 0, err
	}
	return r[kind].Count, nil
}

// testBranches lists the branches that begin with the test prefix.
func (c *Client) testBranches() ([]string, error) {
	raw, err := c.GraphQL(DefaultBranch, `{ Branch { name } }`)
	if err != nil {
		return nil, fmt.Errorf("listing branches: %w", err)
	}
	var r struct {
		Branch []struct {
			Name string `json:"name"`
		} `json:"Branch"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []string
	for _, b := range r.Branch {
		if strings.HasPrefix(b.Name, TestBranchPrefix) {
			out = append(out, b.Name)
		}
	}
	sort.Strings(out)
	return out, nil
}

// baselineInventory is what a branch holds of the baseline's kinds, read by name.
type baselineInventory struct {
	branch string

	// objects holds each concrete kind's objects by key: a tag, a manufacturer or a
	// location by name, a platform as "<manufacturer>/<name>", a device by name, a port as
	// "device:port", an address as "device:port:address", and a cable by its ends'
	// canonical id.
	objects      map[string]map[string]string // kind -> key -> id
	devices      map[string]string            // name -> id
	descriptions map[string]string            // device name -> description
	counts       map[string]int               // kind or generic -> count
}

const baselineQuery = `{
  BuiltinTag { count edges { node { id name { value } } } }
  OrganizationManufacturer { count edges { node { id name { value } } } }
  DcimPlatform { count edges { node { id name { value } manufacturer { node { name { value } } } } } }
  LocationRegion { count edges { node { id name { value } } } }
  LocationCountry { count edges { node { id name { value } } } }
  LocationMetro { count edges { node { id name { value } } } }
  LocationSite { count edges { node { id name { value } } } }
  DcimDevice { count edges { node { id name { value } description { value } } } }
  InterfacePhysical { count edges { node { id name { value } device { node { name { value } } } } } }
  DcimCable { count edges { node { id connected_endpoints { edges { node { id } } } } } }
  IpamIPAddress { count edges { node { id address { value } interface { node { id } } } } }
  BuiltinIPAddress { count } DcimConnector { count } DcimInterface { count } DcimGenericDevice { count }
  OrganizationGeneric { count } LocationGeneric { count }
}`

// readBaseline reads a branch's objects of the baseline's kinds in one query.
func (c *Client) readBaseline(branch string) (*baselineInventory, error) {
	raw, err := c.GraphQL(branch, baselineQuery)
	if err != nil {
		return nil, fmt.Errorf("reading %s's network: %w", branch, err)
	}
	type value struct {
		Value string `json:"value"`
	}
	type named struct {
		Node *struct {
			Name value `json:"name"`
		} `json:"node"`
	}
	type node struct {
		ID           string `json:"id"`
		Name         value  `json:"name"`
		Description  value  `json:"description"`
		Manufacturer named  `json:"manufacturer"`
		Device       named  `json:"device"`
		Address      value  `json:"address"`
		Interface    struct {
			Node *struct {
				ID string `json:"id"`
			} `json:"node"`
		} `json:"interface"`
		Endpoints struct {
			Edges []struct {
				Node struct {
					ID string `json:"id"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"connected_endpoints"`
	}
	var r map[string]struct {
		Count int `json:"count"`
		Edges []struct {
			Node node `json:"node"`
		} `json:"edges"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	inv := &baselineInventory{
		branch:  branch,
		objects: map[string]map[string]string{}, devices: map[string]string{},
		descriptions: map[string]string{}, counts: map[string]int{},
	}
	for kind, v := range r {
		inv.counts[kind] = v.Count
	}
	nameOf := func(n named) string {
		if n.Node == nil {
			return ""
		}
		return n.Node.Name.Value
	}
	byID := map[string]string{} // port id -> "device:port"
	for _, kind := range []string{"BuiltinTag", "OrganizationManufacturer", "DcimPlatform", "LocationRegion",
		"LocationCountry", "LocationMetro", "LocationSite", "DcimDevice", "InterfacePhysical"} {
		inv.objects[kind] = map[string]string{}
		for _, e := range r[kind].Edges {
			key := e.Node.Name.Value
			switch kind {
			case "DcimPlatform":
				key = nameOf(e.Node.Manufacturer) + "/" + key
			case "DcimDevice":
				inv.devices[key] = e.Node.ID
				inv.descriptions[key] = e.Node.Description.Value
			case "InterfacePhysical":
				key = nameOf(e.Node.Device) + ":" + key
				byID[e.Node.ID] = key
			}
			inv.objects[kind][key] = e.Node.ID
		}
	}
	inv.objects["DcimCable"] = map[string]string{}
	for _, e := range r["DcimCable"].Edges {
		var ends []string
		for _, p := range e.Node.Endpoints.Edges {
			end := byID[p.Node.ID]
			if end == "" {
				end = "interface " + p.Node.ID
			}
			ends = append(ends, end)
		}
		sort.Strings(ends)
		inv.objects["DcimCable"][strings.Join(ends, "|")] = e.Node.ID
	}
	inv.objects["IpamIPAddress"] = map[string]string{}
	for _, e := range r["IpamIPAddress"].Edges {
		port := "no interface"
		if e.Node.Interface.Node != nil {
			if port = byID[e.Node.Interface.Node.ID]; port == "" {
				port = "interface " + e.Node.Interface.Node.ID
			}
		}
		inv.objects["IpamIPAddress"][port+":"+e.Node.Address.Value] = e.Node.ID
	}
	return inv, nil
}

// empty reports whether the branch holds nothing of the baseline's kinds.
func (inv *baselineInventory) empty() bool {
	for _, objects := range inv.objects {
		if len(objects) > 0 {
			return false
		}
	}
	return true
}

// beyondBaseline names everything the branch holds that the baseline does not, and any of the
// baseline's devices whose description has changed. What the baseline lacks is not named:
// a seed that failed partway leaves part of it, which -clear-main still removes.
func (inv *baselineInventory) beyondBaseline() []string {
	var out []string
	for _, g := range []struct {
		generic   string
		concretes []string
	}{
		{"BuiltinIPAddress", []string{"IpamIPAddress"}},
		{"DcimConnector", []string{"DcimCable"}},
		{"DcimInterface", []string{"InterfacePhysical"}},
		{"DcimGenericDevice", []string{"DcimDevice"}},
		{"OrganizationGeneric", []string{"OrganizationManufacturer"}},
		{"LocationGeneric", []string{"LocationRegion", "LocationCountry", "LocationMetro", "LocationSite"}},
	} {
		sum := 0
		for _, k := range g.concretes {
			sum += inv.counts[k]
		}
		if inv.counts[g.generic] != sum {
			out = append(out, fmt.Sprintf("%d %s but %d %s", inv.counts[g.generic], g.generic, sum, strings.Join(g.concretes, " and ")))
		}
	}
	for kind, objects := range inv.objects {
		if inv.counts[kind] > len(objects) {
			out = append(out, fmt.Sprintf("%d %s, of which %d were read", inv.counts[kind], kind, len(objects)))
		}
	}

	want := map[string]map[string]bool{
		"BuiltinTag":               {FixtureTag: true},
		"OrganizationManufacturer": {srLinux.manufacturer: true},
		"DcimPlatform":             {srLinux.manufacturer + "/" + srLinux.name: true},
		"DcimDevice":               {},
		"InterfacePhysical":        {},
		"DcimCable":                {},
		"IpamIPAddress":            {},
	}
	for _, level := range siteLevels {
		want[level.kind] = map[string]bool{level.name: true}
	}
	for _, n := range fixtureNodes {
		want["DcimDevice"][n.name] = true
		for _, p := range append([]string{n.mgmt}, n.ports...) {
			want["InterfacePhysical"][n.name+":"+p] = true
		}
		for _, p := range n.addressed {
			want["InterfacePhysical"][n.name+":"+p.name] = true
			want["IpamIPAddress"][n.name+":"+p.name+":"+p.address] = true
		}
	}
	for _, l := range fixtureLinks {
		want["DcimCable"][l.id()] = true
	}
	for _, k := range baselineKinds {
		out = append(out, differ(k.concrete, inv.objects[k.concrete], want[k.concrete])...)
	}
	for name, description := range inv.descriptions {
		if want["DcimDevice"][name] && description != MarkerDescription(inv.branch) {
			out = append(out, fmt.Sprintf("device %s has description %q, want %q", name, description, MarkerDescription(inv.branch)))
		}
	}
	sort.Strings(out)
	return out
}

// differ names what held has beyond want.
func differ(what string, held map[string]string, want map[string]bool) []string {
	var out []string
	for k := range held {
		if !want[k] {
			out = append(out, fmt.Sprintf("%s %s is not the baseline's", what, k))
		}
	}
	return out
}

func values(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for _, v := range m {
		out = append(out, v)
	}
	sort.Strings(out)
	return out
}

// artifactsOf returns the ids of a branch's artifacts whose target is one of the devices.
func (c *Client) artifactsOf(branch string, deviceIDs []string) ([]string, error) {
	raw, err := c.GraphQL(branch, `{ CoreArtifact { edges { node { id object { node { id } } } } } }`)
	if err != nil {
		return nil, fmt.Errorf("listing %s's artifacts: %w", branch, err)
	}
	var r struct {
		A struct {
			Edges []struct {
				Node struct {
					ID     string `json:"id"`
					Object struct {
						Node struct {
							ID string `json:"id"`
						} `json:"node"`
					} `json:"object"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreArtifact"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	targets := map[string]bool{}
	for _, id := range deviceIDs {
		targets[id] = true
	}
	var out []string
	for _, e := range r.A.Edges {
		if targets[e.Node.Object.Node.ID] {
			out = append(out, e.Node.ID)
		}
	}
	return out, nil
}

// existing returns which of the ids a branch still holds as objects of a kind.
func (c *Client) existing(branch, kind string, ids []string) ([]string, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	quoted := make([]string, len(ids))
	for i, id := range ids {
		quoted[i] = fmt.Sprintf("%q", id)
	}
	return c.ids(branch, kind, fmt.Sprintf(`(ids: [%s])`, strings.Join(quoted, ", ")))
}

// deleteNode deletes one object by its kind's own delete mutation.
func (c *Client) deleteNode(branch, kind, id string) error {
	mutation := kind + "Delete"
	raw, err := c.GraphQL(branch, fmt.Sprintf(`mutation { %s(data: {id: %q}) { ok } }`, mutation, id))
	if err != nil {
		return fmt.Errorf("deleting %s %s on %s: %w", kind, id, branch, err)
	}
	return okOf(raw, mutation, fmt.Sprintf("deleting %s %s on %s", kind, id, branch))
}
