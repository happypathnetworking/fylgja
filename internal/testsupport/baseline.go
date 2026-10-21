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

// baselineKinds are the kinds a baseline is made of, in the order -clear-main deletes
// them: a link before its endpoints, an interface before its device, a device before its
// platform. Each concrete kind is counted beside its generic, so that an object of
// another kind implementing the generic is seen too.
var baselineKinds = []struct{ concrete, generic string }{
	{"NetworkLink", "FylgjaLink"},
	{"NetworkInterface", "FylgjaInterface"},
	{"NetworkDevice", "FylgjaDevice"},
	{"NetworkPlatform", "FylgjaPlatform"},
	{"FylgjaContract", "FylgjaContract"},
}

// SeedMainBaseline writes D-054's baseline onto main: the three-node fixture, its
// devices joined to the artifact group and their artifacts rendered and Ready, as
// SeedThreeNode writes it on a branch. It refuses a main that holds anything of the
// baseline's kinds, so it never adds to a network and never runs twice.
func (c *Client) SeedMainBaseline() error {
	held, err := c.baselineCounts()
	if err != nil {
		return err
	}
	if len(held) > 0 {
		return fmt.Errorf("main already holds %s: the baseline is written only onto a main that holds no network (D-054); "+
			"remove it with -clear-main first", strings.Join(held, ", "))
	}
	return c.SeedThreeNode(DefaultBranch)
}

// ClearedBaseline counts what ClearMainBaseline deleted. Artifacts counts the baseline's
// artifacts it deleted itself; ArtifactsWithDevices those Infrahub had already removed
// with their devices.
type ClearedBaseline struct {
	Links, Interfaces, Devices, Platforms, Contracts int
	Artifacts, ArtifactsWithDevices                  int
}

// ClearMainBaseline deletes what SeedMainBaseline wrote, and nothing else (D-054). It
// refuses while any test branch exists, since the window closes after every demo branch
// is deleted, and when main holds anything beyond the baseline, such as a merged change,
// naming what it found; either refusal deletes nothing. Then it deletes the links, the
// interfaces, the devices, the platform and the contract, and last any of the devices'
// artifacts Infrahub left behind.
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
	inv, err := c.readBaseline()
	if err != nil {
		return done, err
	}
	if extra := inv.beyondBaseline(); len(extra) > 0 {
		return done, fmt.Errorf("main holds more than the baseline: %s; nothing was deleted", strings.Join(extra, "; "))
	}
	if len(inv.devices)+len(inv.interfaces)+len(inv.links)+len(inv.platforms)+len(inv.contracts) == 0 {
		return done, fmt.Errorf("main holds no baseline: nothing to remove")
	}

	artifacts, err := c.artifactsOf(inv.deviceIDs())
	if err != nil {
		return done, err
	}
	for _, step := range []struct {
		kind  string
		ids   []string
		count *int
	}{
		{"NetworkLink", inv.linkIDs(), &done.Links},
		{"NetworkInterface", inv.interfaceIDs(), &done.Interfaces},
		{"NetworkDevice", inv.deviceIDs(), &done.Devices},
		{"NetworkPlatform", inv.platforms, &done.Platforms},
		{"FylgjaContract", inv.contracts, &done.Contracts},
	} {
		for _, id := range step.ids {
			if err := c.deleteNode(DefaultBranch, step.kind, id); err != nil {
				return done, err
			}
			*step.count++
		}
	}
	left, err := c.existing("CoreArtifact", artifacts)
	if err != nil {
		return done, err
	}
	done.ArtifactsWithDevices = len(artifacts) - len(left)
	for _, id := range left {
		if err := c.deleteNode(DefaultBranch, "CoreArtifact", id); err != nil {
			return done, err
		}
		done.Artifacts++
	}
	return done, nil
}

// baselineCounts names each baseline kind main holds objects of, with how many.
func (c *Client) baselineCounts() ([]string, error) {
	var held []string
	seen := map[string]bool{}
	for _, k := range baselineKinds {
		for _, kind := range []string{k.concrete, k.generic} {
			if seen[kind] {
				continue
			}
			seen[kind] = true
			n, err := c.count(DefaultBranch, kind)
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

// baselineInventory is what main holds of the baseline's kinds, read by name.
type baselineInventory struct {
	contracts, platforms []string
	contractVersions     []string
	platformNames        []string
	devices              map[string]string // name -> id
	roles                map[string]string // name -> role
	interfaces           map[string]string // "device:interface" -> id
	links                map[string]string // canonical "a|b" -> id
	generics             map[string]int    // generic -> count
	concretes            map[string]int    // concrete -> count
}

const baselineQuery = `{
  FylgjaContract { count edges { node { id version { value } } } }
  NetworkPlatform { count edges { node { id vendor { value } nos { value } version { value } } } }
  NetworkDevice { count edges { node { id name { value } role { value } } } }
  NetworkInterface { count edges { node { id name { value } device { node { name { value } } } } } }
  NetworkLink { count edges { node { id endpoints { edges { node { id } } } } } }
  FylgjaPlatform { count } FylgjaDevice { count } FylgjaInterface { count } FylgjaLink { count }
}`

// readBaseline reads main's objects of the baseline's kinds in one query.
func (c *Client) readBaseline() (*baselineInventory, error) {
	raw, err := c.GraphQL(DefaultBranch, baselineQuery)
	if err != nil {
		return nil, fmt.Errorf("reading main's network: %w", err)
	}
	type value struct {
		Value string `json:"value"`
	}
	var r struct {
		Contract struct {
			Count int `json:"count"`
			Edges []struct {
				Node struct {
					ID      string `json:"id"`
					Version value  `json:"version"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaContract"`
		Platform struct {
			Count int `json:"count"`
			Edges []struct {
				Node struct {
					ID      string `json:"id"`
					Vendor  value  `json:"vendor"`
					NOS     value  `json:"nos"`
					Version value  `json:"version"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"NetworkPlatform"`
		Device struct {
			Count int `json:"count"`
			Edges []struct {
				Node struct {
					ID   string `json:"id"`
					Name value  `json:"name"`
					Role value  `json:"role"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"NetworkDevice"`
		Interface struct {
			Count int `json:"count"`
			Edges []struct {
				Node struct {
					ID     string `json:"id"`
					Name   value  `json:"name"`
					Device struct {
						Node struct {
							Name value `json:"name"`
						} `json:"node"`
					} `json:"device"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"NetworkInterface"`
		Link struct {
			Count int `json:"count"`
			Edges []struct {
				Node struct {
					ID        string `json:"id"`
					Endpoints struct {
						Edges []struct {
							Node struct {
								ID string `json:"id"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"endpoints"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"NetworkLink"`
		GPlatform struct{ Count int } `json:"FylgjaPlatform"`
		GDevice   struct{ Count int } `json:"FylgjaDevice"`
		GIface    struct{ Count int } `json:"FylgjaInterface"`
		GLink     struct{ Count int } `json:"FylgjaLink"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	inv := &baselineInventory{
		devices: map[string]string{}, roles: map[string]string{},
		interfaces: map[string]string{}, links: map[string]string{},
		generics: map[string]int{
			"FylgjaPlatform": r.GPlatform.Count, "FylgjaDevice": r.GDevice.Count,
			"FylgjaInterface": r.GIface.Count, "FylgjaLink": r.GLink.Count,
		},
		concretes: map[string]int{
			"NetworkPlatform": r.Platform.Count, "NetworkDevice": r.Device.Count,
			"NetworkInterface": r.Interface.Count, "NetworkLink": r.Link.Count,
		},
	}
	for _, e := range r.Contract.Edges {
		inv.contracts = append(inv.contracts, e.Node.ID)
		inv.contractVersions = append(inv.contractVersions, e.Node.Version.Value)
	}
	for _, e := range r.Platform.Edges {
		inv.platforms = append(inv.platforms, e.Node.ID)
		inv.platformNames = append(inv.platformNames,
			e.Node.Vendor.Value+"/"+e.Node.NOS.Value+"/"+e.Node.Version.Value)
	}
	for _, e := range r.Device.Edges {
		inv.devices[e.Node.Name.Value] = e.Node.ID
		inv.roles[e.Node.Name.Value] = e.Node.Role.Value
	}
	byID := map[string]string{} // interface id -> "device:interface"
	for _, e := range r.Interface.Edges {
		key := e.Node.Device.Node.Name.Value + ":" + e.Node.Name.Value
		inv.interfaces[key] = e.Node.ID
		byID[e.Node.ID] = key
	}
	for _, e := range r.Link.Edges {
		var ends []string
		for _, p := range e.Node.Endpoints.Edges {
			end := byID[p.Node.ID]
			if end == "" {
				end = "interface " + p.Node.ID
			}
			ends = append(ends, end)
		}
		sort.Strings(ends)
		inv.links[strings.Join(ends, "|")] = e.Node.ID
	}
	return inv, nil
}

// beyondBaseline names everything main holds that the baseline does not, and any of the
// baseline's objects that has changed. What the baseline lacks is not named: a seed that
// failed partway leaves part of it, which -clear-main still removes.
func (inv *baselineInventory) beyondBaseline() []string {
	var out []string
	for generic, n := range inv.generics {
		concrete := "Network" + strings.TrimPrefix(generic, "Fylgja")
		if n != inv.concretes[concrete] {
			out = append(out, fmt.Sprintf("%d %s but %d %s", n, generic, inv.concretes[concrete], concrete))
		}
	}
	if len(inv.contracts) > 1 || (len(inv.contracts) == 1 && inv.contractVersions[0] != ContractVersion) {
		out = append(out, fmt.Sprintf("contract(s) %v, want one at %s", inv.contractVersions, ContractVersion))
	}
	if len(inv.platforms) > 1 || (len(inv.platforms) == 1 && inv.platformNames[0] != "nokia/srlinux/24.7") {
		out = append(out, fmt.Sprintf("platform(s) %v, want nokia/srlinux/24.7 alone", inv.platformNames))
	}
	devices, interfaces, links := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, n := range fixtureNodes {
		devices[n.name] = true
		for _, p := range append([]string{"mgmt0", "lo0"}, n.ports...) {
			interfaces[n.name+":"+p] = true
		}
	}
	for _, l := range fixtureLinks {
		ends := []string{l.aDev + ":" + l.aPort, l.bDev + ":" + l.bPort}
		sort.Strings(ends)
		links[strings.Join(ends, "|")] = true
	}
	out = append(out, differ("device", inv.devices, devices)...)
	for name, role := range inv.roles {
		if devices[name] && role != MarkerRole(DefaultBranch) {
			out = append(out, fmt.Sprintf("device %s has role %q, want %q", name, role, MarkerRole(DefaultBranch)))
		}
	}
	out = append(out, differ("interface", inv.interfaces, interfaces)...)
	out = append(out, differ("link", inv.links, links)...)
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

func (inv *baselineInventory) deviceIDs() []string    { return values(inv.devices) }
func (inv *baselineInventory) interfaceIDs() []string { return values(inv.interfaces) }
func (inv *baselineInventory) linkIDs() []string      { return values(inv.links) }

// artifactsOf returns the ids of main's artifacts whose target is one of the devices.
func (c *Client) artifactsOf(deviceIDs []string) ([]string, error) {
	raw, err := c.GraphQL(DefaultBranch, `{ CoreArtifact { edges { node { id object { node { id } } } } } }`)
	if err != nil {
		return nil, fmt.Errorf("listing main's artifacts: %w", err)
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

// existing returns which of the ids main still holds as objects of a kind.
func (c *Client) existing(kind string, ids []string) ([]string, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	quoted := make([]string, len(ids))
	for i, id := range ids {
		quoted[i] = fmt.Sprintf("%q", id)
	}
	return c.ids(DefaultBranch, kind, fmt.Sprintf(`(ids: [%s])`, strings.Join(quoted, ", ")))
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
