//go:build contract || fixture

package testsupport

import (
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
)

// A test's own registration: a repository served from the lab host's Docker bridge, where
// Infrahub's task workers fetch it, registered read-only under a fylgja-test- name and
// deleted by the test that made it (research R-18). The registration Infrahub renders from,
// RepositoryName, is never one of them.

// CheckDefinitionRow is one check definition on main, as the harness reads it back.
type CheckDefinitionRow struct {
	Name    string
	Timeout int
}

// BridgeAddress is the host's Docker bridge gateway, read as scripts/bring-up.sh reads it:
// the address host-gateway resolves to inside Infrahub's task workers (D-050). It is an
// error when Docker or the network is absent, for a test to skip on.
func BridgeAddress() (string, error) {
	cmd := exec.Command("docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}")
	out, err := cmd.Output()
	if err != nil {
		var exit *exec.ExitError
		if errors.As(err, &exit) && len(exit.Stderr) > 0 {
			return "", fmt.Errorf("reading the Docker bridge's gateway (docker network inspect bridge): %w: %s",
				err, strings.TrimSpace(string(exit.Stderr)))
		}
		return "", fmt.Errorf("reading the Docker bridge's gateway (docker network inspect bridge): %w", err)
	}
	addr := strings.TrimSpace(string(out))
	if net.ParseIP(addr) == nil {
		return "", fmt.Errorf("the Docker bridge's gateway reads %q, not an address", addr)
	}
	return addr, nil
}

// repositoryName is what a served repository's directory may be called: one path element,
// which the location names.
var repositoryName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// ServeRepository serves dir's files as a git repository over git's dumb HTTP on the
// Docker bridge, as research §1.3's probe served its own: dir is copied into a work tree
// under a scratch directory, committed on main, cloned bare and given update-server-info,
// and the bare clone is served by net/http on <bridge>:0. location is
// http://<bridge>:<port>/<name>.git, name being dir's base; stop closes the server and
// removes the scratch directory. Nothing is written under dir, and git reads neither the
// system's nor the user's configuration, so no hook or signing setting of the host's runs.
func ServeRepository(dir string) (location string, stop func(), err error) {
	name := filepath.Base(filepath.Clean(dir))
	if !repositoryName.MatchString(name) {
		return "", nil, fmt.Errorf("serving %s: its name %q is not one path element a location can carry", dir, name)
	}
	bridge, err := BridgeAddress()
	if err != nil {
		return "", nil, err
	}
	scratch, err := os.MkdirTemp("", "fylgja-test-repository-*")
	if err != nil {
		return "", nil, err
	}
	remove := func() { _ = os.RemoveAll(scratch) }
	work := filepath.Join(scratch, "work")
	served := filepath.Join(scratch, "served")
	bare := filepath.Join(served, name+".git")
	if err := os.CopyFS(work, os.DirFS(dir)); err != nil {
		remove()
		return "", nil, fmt.Errorf("copying %s to serve it: %w", dir, err)
	}
	for _, step := range []struct {
		dir  string
		args []string
	}{
		{work, []string{"init", "-q", "-b", "main"}},
		{work, []string{"add", "-A"}},
		{work, []string{"commit", "-q", "-m", "A test's repository, served from the Docker bridge"}},
		{scratch, []string{"clone", "-q", "--bare", work, bare}},
		{bare, []string{"update-server-info"}},
	} {
		if err := git(step.dir, step.args...); err != nil {
			remove()
			return "", nil, err
		}
	}
	ln, err := net.Listen("tcp", net.JoinHostPort(bridge, "0"))
	if err != nil {
		remove()
		return "", nil, fmt.Errorf("listening on the Docker bridge %s: %w", bridge, err)
	}
	srv := &http.Server{Handler: http.FileServer(http.Dir(served)), ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = srv.Serve(ln) }()
	port := strconv.Itoa(ln.Addr().(*net.TCPAddr).Port)
	return fmt.Sprintf("http://%s/%s.git", net.JoinHostPort(bridge, port), name), func() {
		_ = srv.Close()
		remove()
	}, nil
}

// git runs one git command in dir, with no system or global configuration and a fixed
// author, and with none of the caller's GIT_ variables, which could point it elsewhere.
func git(dir string, args ...string) error {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	env := slices.DeleteFunc(os.Environ(), func(kv string) bool { return strings.HasPrefix(kv, "GIT_") })
	cmd.Env = append(env, "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL="+os.DevNull,
		"GIT_AUTHOR_NAME=fylgja-test", "GIT_AUTHOR_EMAIL=fylgja-test@localhost",
		"GIT_COMMITTER_NAME=fylgja-test", "GIT_COMMITTER_EMAIL=fylgja-test@localhost")
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("git %s in %s: %w: %s", strings.Join(args, " "), dir, err, strings.TrimSpace(string(out)))
	}
	return nil
}

// DeleteRepository deletes a test's read-only registration on main, by name; its check
// definitions and its query go with it (research §1.6). A name outside the test prefix is
// refused before any request, so the registration Infrahub renders from is never deleted,
// and an absent one is an error, so a cleanup that runs twice says so.
func (c *Client) DeleteRepository(name string) error {
	if !strings.HasPrefix(name, TestBranchPrefix) {
		return fmt.Errorf("repository %q is not a test's: every registration a test deletes begins %q", name, TestBranchPrefix)
	}
	found, err := c.ids("main", "CoreReadOnlyRepository", fmt.Sprintf(`(name__value: %q)`, name))
	if err != nil {
		return err
	}
	if len(found) != 1 {
		return fmt.Errorf("main holds %d read-only repositories named %q, want one", len(found), name)
	}
	what := fmt.Sprintf("deleting repository %s", name)
	raw, err := c.GraphQL("main", fmt.Sprintf(`mutation { CoreReadOnlyRepositoryDelete(data: {id: %q}) { ok } }`, found[0]))
	if err != nil {
		return fmt.Errorf("%s: %w", what, err)
	}
	return okOf(raw, "CoreReadOnlyRepositoryDelete", what)
}

// CheckDefinitions lists the check definitions on main, each name with its timeout, sorted
// by name: what every registration's import put there, for a test's assertions and its
// cleanup. It writes nothing.
func (c *Client) CheckDefinitions() ([]CheckDefinitionRow, error) {
	raw, err := c.GraphQL("main", `{ CoreCheckDefinition { edges { node { name { value } timeout { value } } } } }`)
	if err != nil {
		return nil, fmt.Errorf("listing the check definitions on main: %w", err)
	}
	var r struct {
		D struct {
			Edges []struct {
				Node struct {
					Name struct {
						Value string `json:"value"`
					} `json:"name"`
					Timeout struct {
						Value *int `json:"value"`
					} `json:"timeout"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreCheckDefinition"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	out := make([]CheckDefinitionRow, 0, len(r.D.Edges))
	for _, e := range r.D.Edges {
		row := CheckDefinitionRow{Name: e.Node.Name.Value}
		if e.Node.Timeout.Value != nil {
			row.Timeout = *e.Node.Timeout.Value
		}
		out = append(out, row)
	}
	slices.SortFunc(out, func(a, b CheckDefinitionRow) int { return strings.Compare(a.Name, b.Name) })
	return out, nil
}
