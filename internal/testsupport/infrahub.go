//go:build contract || fixture

// Package testsupport is the contract-test harness.
//
// It is the one place Fylgja code writes to Infrahub — creating branches, loading
// schema, seeding fixtures. The product must never do that (Constitution III),
// so this package is build-tagged and is never imported by cmd/fylgja; a test in
// internal/compiler asserts as much.
package testsupport

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// Client talks to Infrahub with write access.
type Client struct {
	Address string
	Token   string
	HTTP    *http.Client
}

// NewClient builds a client from INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN.
func NewClient() (*Client, error) {
	addr := os.Getenv("INFRAHUB_ADDRESS")
	token := os.Getenv("INFRAHUB_API_TOKEN")
	if addr == "" || token == "" {
		return nil, fmt.Errorf("INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN must be set")
	}
	return &Client{
		Address: strings.TrimRight(addr, "/"),
		Token:   token,
		HTTP:    &http.Client{Timeout: 120 * time.Second},
	}, nil
}

func (c *Client) do(method, path string, body any) (int, []byte, error) {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return 0, nil, err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.Address+path, rdr)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-INFRAHUB-KEY", c.Token)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return 0, nil, c.redact(err)
	}
	defer func() { _ = resp.Body.Close() }()
	out, err := io.ReadAll(resp.Body)
	return resp.StatusCode, out, err
}

// redact strips the token from an error, so a harness failure cannot leak it either.
func (c *Client) redact(err error) error {
	if err == nil || c.Token == "" {
		return err
	}
	return fmt.Errorf("%s", strings.ReplaceAll(err.Error(), c.Token, "<redacted>"))
}

type gqlResponse struct {
	Data   json.RawMessage `json:"data"`
	Errors []struct {
		Message string `json:"message"`
	} `json:"errors"`
}

// GraphQL runs a query or mutation against a branch.
func (c *Client) GraphQL(branch, query string) (json.RawMessage, error) {
	status, body, err := c.do(http.MethodPost, "/graphql/"+branch, map[string]any{"query": query})
	if err != nil {
		return nil, err
	}
	var r gqlResponse
	if err := json.Unmarshal(body, &r); err != nil {
		return nil, fmt.Errorf("graphql %d: %s", status, string(body))
	}
	if len(r.Errors) > 0 {
		return r.Data, fmt.Errorf("graphql: %s", r.Errors[0].Message)
	}
	return r.Data, nil
}

// CreateBranch creates a branch, treating "already exists" as success so seeding is
// repeatable.
func (c *Client) CreateBranch(name string) error {
	q := fmt.Sprintf(`mutation { BranchCreate(data: {name: %q, sync_with_git: false}) { ok } }`, name)
	if _, err := c.GraphQL("main", q); err != nil {
		if strings.Contains(err.Error(), "already exists") {
			return nil
		}
		return err
	}
	return nil
}

// DeleteBranch removes a branch.
func (c *Client) DeleteBranch(name string) error {
	q := fmt.Sprintf(`mutation { BranchDelete(data: {name: %q}) { ok } }`, name)
	_, err := c.GraphQL("main", q)
	return err
}

// LoadSchema loads every YAML file in schemaDir onto a branch, then waits for the
// branch's GraphQL schema to be rebuilt. The rebuild is asynchronous: seeding
// immediately after a load races it.
func (c *Client) LoadSchema(branch, schemaDir string) error {
	paths, err := filepath.Glob(filepath.Join(schemaDir, "*.yaml"))
	if err != nil {
		return err
	}
	sort.Strings(paths)
	schemas := make([]any, 0, len(paths))
	for _, p := range paths {
		raw, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		var doc any
		if err := yaml.Unmarshal(raw, &doc); err != nil {
			return fmt.Errorf("%s: %w", p, err)
		}
		schemas = append(schemas, doc)
	}
	status, body, err := c.do(http.MethodPost, "/api/schema/load?branch="+branch, map[string]any{"schemas": schemas})
	if err != nil {
		return err
	}
	if status != http.StatusOK && status != http.StatusAccepted {
		return fmt.Errorf("schema load %d: %s", status, string(body))
	}
	// Wait only for what was actually loaded: a generics-only load defines
	// FylgjaContract but no concrete Network* kinds, and waiting for those would time
	// out on a branch that is deliberately incomplete.
	if _, err := os.Stat(filepath.Join(schemaDir, "reference.yaml")); err == nil {
		return c.waitForKinds(branch, "FylgjaContractCreate", "NetworkDeviceCreate", "NetworkLinkCreate")
	}
	return c.waitForKinds(branch, "FylgjaContractCreate")
}

// waitForKinds polls until the named mutations appear on the branch's GraphQL schema.
func (c *Client) waitForKinds(branch string, mutations ...string) error {
	const q = `{ __type(name: "Mutation") { fields { name } } }`
	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		data, err := c.GraphQL(branch, q)
		if err == nil {
			var r struct {
				Type struct {
					Fields []struct {
						Name string `json:"name"`
					} `json:"fields"`
				} `json:"__type"`
			}
			if json.Unmarshal(data, &r) == nil {
				have := map[string]bool{}
				for _, f := range r.Type.Fields {
					have[f.Name] = true
				}
				all := true
				for _, m := range mutations {
					if !have[m] {
						all = false
						break
					}
				}
				if all {
					return nil
				}
			}
		}
		time.Sleep(time.Second)
	}
	return fmt.Errorf("branch %s: GraphQL schema did not expose %v within 90s", branch, mutations)
}

// create runs a Create mutation and returns the new object's id.
func (c *Client) create(branch, kind, data string) (string, error) {
	q := fmt.Sprintf(`mutation { %sCreate(data: %s) { ok object { id } } }`, kind, data)
	raw, err := c.GraphQL(branch, q)
	if err != nil {
		return "", fmt.Errorf("creating %s: %w", kind, err)
	}
	var r map[string]struct {
		Object struct {
			ID string `json:"id"`
		} `json:"object"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return "", err
	}
	return r[kind+"Create"].Object.ID, nil
}

// json_Unmarshal is a tiny indirection so seed.go can decode without importing
// encoding/json again under a different name.
func json_Unmarshal(data []byte, v any) error { return json.Unmarshal(data, v) }

// SDL fetches a branch's GraphQL schema definition.
func (c *Client) SDL(branch string) ([]byte, error) {
	status, body, err := c.do(http.MethodGet, "/schema.graphql?branch="+branch, nil)
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, fmt.Errorf("fetching SDL: HTTP %d", status)
	}
	return body, nil
}

// ArtifactDefinitionName is the definition in the fylgja-artifacts repository that
// renders a device's configuration. It is the name, not an id: the id differs per
// install, and a branch inherits main's definition (D-028).
const ArtifactDefinitionName = "srlinux_device_config"

// ArtifactGroupName is the standard group whose members the definition renders for. A
// device outside it has no artifact, which is a refusal the tiers prove.
const ArtifactGroupName = "fylgja-devices"

// artifactWait bounds every wait for generation: twelve times the 7.6s measured for
// three devices, the same bound the schema wait uses.
const artifactWait = 90 * time.Second

// lookupByName returns the one object of a kind with the given name, or an error naming
// how many were found. Used for the definition and the group, which are looked up by
// name because their ids differ per install.
func (c *Client) lookupByName(branch, kind, name string) (string, error) {
	found, err := c.ids(branch, kind, fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return "", err
	}
	if len(found) != 1 {
		return "", fmt.Errorf("branch %s holds %d %s named %q, want one; "+
			"the fylgja-artifacts repository must be connected and in-sync on main", branch, len(found), kind, name)
	}
	return found[0], nil
}

// ArtifactGroup returns the id of the group the artifact definition renders for, on a
// branch. A branch created before the group existed on main cannot see it, which is a
// real failure rather than an empty result: the seed would silently render nothing.
func (c *Client) ArtifactGroup(branch string) (string, error) {
	return c.lookupByName(branch, "CoreStandardGroup", ArtifactGroupName)
}

// JoinArtifactGroup adds devices to the group the definition renders for. Membership is
// what makes a device a target; it does not by itself render anything.
func (c *Client) JoinArtifactGroup(branch string, deviceIDs []string) error {
	if len(deviceIDs) == 0 {
		return nil
	}
	group, err := c.ArtifactGroup(branch)
	if err != nil {
		return err
	}
	nodes := make([]string, 0, len(deviceIDs))
	for _, id := range deviceIDs {
		nodes = append(nodes, fmt.Sprintf(`{id: %q}`, id))
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`mutation { RelationshipAdd(data: {id: %q, name: "members", nodes: [%s]}) { ok } }`,
		group, strings.Join(nodes, ", ")))
	if err != nil {
		return fmt.Errorf("adding %d device(s) to group %s on %s: %w", len(deviceIDs), ArtifactGroupName, branch, err)
	}
	var r struct {
		Add struct {
			OK bool `json:"ok"`
		} `json:"RelationshipAdd"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return err
	}
	if !r.Add.OK {
		return fmt.Errorf("adding devices to group %s on %s: mutation returned ok: false", ArtifactGroupName, branch)
	}
	return nil
}

// GenerateArtifacts renders every group member's artifact on a branch and waits until
// each is Ready.
//
// Infrahub 1.11.2 regenerates nothing on its own: not on a data change, not on a group
// join, not on a commit. Whoever changes a branch regenerates it, and
// for a test branch that is this package. Fylgja itself never generates (Constitution
// III), which is why this lives behind a build tag.
//
// The POST returns in about 0.1s, before anything exists; the artifacts appear Pending
// and reach Ready about a second later, 7.6s from the call for three devices. So
// the wait is for the count and the status, not for the call. The count is the group's
// members, since the definition renders for the group and a device that left it loses
// its artifact on this generation: counting the branch's devices instead let the
// old artifacts satisfy the wait before a removal took effect, and failed it once the
// removal had.
//
// What the wait cannot see is a rewrite. A generation after an intent change rewrites a
// member's artifact in one step, Ready before and Ready after, so it returns as
// soon as the count holds, which it already did. A caller that changed intent waits for
// the checksums to move, as scripts/e2e.sh and the tier-2 tests do.
func (c *Client) GenerateArtifacts(branch string) error {
	definition, err := c.lookupByName(branch, "CoreArtifactDefinition", ArtifactDefinitionName)
	if err != nil {
		return err
	}
	want, err := c.groupMemberCount(branch)
	if err != nil {
		return err
	}
	if want == 0 {
		return fmt.Errorf("group %s on branch %s has no members to generate artifacts for", ArtifactGroupName, branch)
	}

	code, body, err := c.do(http.MethodPost,
		"/api/artifact/generate/"+definition+"?branch="+branch, map[string]any{"nodes": []any{}})
	if err != nil {
		return err
	}
	if code != http.StatusOK {
		return fmt.Errorf("generating artifacts on %s: HTTP %d: %s", branch, code, string(body))
	}
	return c.WaitForArtifacts(branch, want)
}

// WaitForArtifacts polls until the branch holds want artifacts and every one is Ready.
// An artifact that stays Pending, or an Error, ends the wait at the deadline naming what
// it saw, so a test fails on the generation rather than later on a missing artifact.
func (c *Client) WaitForArtifacts(branch string, want int) error {
	const q = `{ CoreArtifact { count edges { node { status { value } } } } }`
	deadline := time.Now().Add(artifactWait)
	last := "nothing yet"
	for time.Now().Before(deadline) {
		raw, err := c.GraphQL(branch, q)
		if err == nil {
			var r struct {
				A struct {
					Count int `json:"count"`
					Edges []struct {
						Node struct {
							Status struct {
								Value string `json:"value"`
							} `json:"status"`
						} `json:"node"`
					} `json:"edges"`
				} `json:"CoreArtifact"`
			}
			if json.Unmarshal(raw, &r) == nil {
				states := map[string]int{}
				ready := 0
				for _, e := range r.A.Edges {
					states[e.Node.Status.Value]++
					if e.Node.Status.Value == "Ready" {
						ready++
					}
				}
				if r.A.Count == want && ready == want {
					return nil
				}
				last = fmt.Sprintf("%d artifact(s), states %v", r.A.Count, states)
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("branch %s: %d artifact(s) did not all reach Ready within %s (last saw %s)",
		branch, want, artifactWait, last)
}

// ArtifactsReadyAt returns when the branch's last artifact became Ready: the latest
// status stamp among them, which the generate that renders an artifact writes together
// with its checksum and storage id. A read pinned after it sees every artifact. It
// refuses a branch with no artifact, or with one not Ready, since no such instant exists.
func (c *Client) ArtifactsReadyAt(branch string) (time.Time, error) {
	const q = `{ CoreArtifact { edges { node { status { value updated_at } } } } }`
	raw, err := c.GraphQL(branch, q)
	if err != nil {
		return time.Time{}, err
	}
	var r struct {
		A struct {
			Edges []struct {
				Node struct {
					Status struct {
						Value     string `json:"value"`
						UpdatedAt string `json:"updated_at"`
					} `json:"status"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreArtifact"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return time.Time{}, err
	}
	if len(r.A.Edges) == 0 {
		return time.Time{}, fmt.Errorf("branch %s holds no artifact", branch)
	}
	var latest time.Time
	for _, e := range r.A.Edges {
		if e.Node.Status.Value != "Ready" {
			return time.Time{}, fmt.Errorf("branch %s holds an artifact %s, not Ready", branch, e.Node.Status.Value)
		}
		at, err := time.Parse(time.RFC3339Nano, e.Node.Status.UpdatedAt)
		if err != nil {
			return time.Time{}, fmt.Errorf("branch %s: artifact status stamp %q: %w", branch, e.Node.Status.UpdatedAt, err)
		}
		if at.After(latest) {
			latest = at
		}
	}
	return latest, nil
}

// groupMemberCount is how many artifacts a fully generated branch should hold: one per
// member of the group the definition renders for, and none for any other device.
func (c *Client) groupMemberCount(branch string) (int, error) {
	raw, err := c.GraphQL(branch, fmt.Sprintf(
		`{ CoreStandardGroup(name__value: %q) { edges { node { members { count } } } } }`, ArtifactGroupName))
	if err != nil {
		return 0, err
	}
	var r struct {
		G struct {
			Edges []struct {
				Node struct {
					Members struct {
						Count int `json:"count"`
					} `json:"members"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreStandardGroup"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return 0, err
	}
	if len(r.G.Edges) != 1 {
		return 0, fmt.Errorf("branch %s holds %d CoreStandardGroup named %q, want one; "+
			"the fylgja-artifacts repository must be connected and in-sync on main", branch, len(r.G.Edges), ArtifactGroupName)
	}
	return r.G.Edges[0].Node.Members.Count, nil
}
