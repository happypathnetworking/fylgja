package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"net"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
)

// A client's environment is the API's address and token, and nothing else.

// askedEnv makes the client's environment the harness's server at address and its token,
// and records every name the client asks it for.
func askedEnv(t *testing.T, address string) func() []string {
	t.Helper()
	var mu sync.Mutex
	var asked []string
	saved := getenv
	t.Cleanup(func() { getenv = saved })
	getenv = func(name string) (string, bool) {
		mu.Lock()
		asked = append(asked, name)
		mu.Unlock()
		switch name {
		case api.EnvAddress:
			return address, true
		case api.EnvToken:
			return harness.token, true
		}
		return "", false
	}
	return func() []string {
		mu.Lock()
		defer mu.Unlock()
		return slices.Clone(asked)
	}
}

// clientCommands are every client's command line, each with what it needs to send its
// request: a file or a directory where it reads one before it sends.
func clientCommands(t *testing.T) [][]string {
	t.Helper()
	return [][]string{
		{"twin", "create", "--branch", "fylgja-fixture"},
		{"twin", "provision", copyGoldenBundle(t, "bundle")},
		{"twin", "step"},
		{"twin", "destroy"},
		{"twin", "show"},
		{"twin", "verify"},
		{"twin", "compile", "--ctm", repoPath("testdata", "ctm", "three-node.json"), "--out", filepath.Join(t.TempDir(), "out")},
		{"intent", "read", "--branch", "fylgja-fixture"},
		{"waypoint", "list"},
		{"waypoint", "plan", "--series", "demo"},
		{"schema", "check", "--branch", "fylgja-fixture"},
		{"psp", "validate", repoPath("psp", "nokia_srlinux.yaml")},
	}
}

// requestsLogged is how many requests the harness's server has logged, of any operation.
func requestsLogged() int {
	return strings.Count(harness.log.String(), "msg=request ")
}

// Every client's command, run against the harness's server with Fylgja's, Infrahub's and
// the nodes' variables set to values no client may use, asks its environment for the API's
// address and token and for nothing else, and reaches the server.
func TestTheClientReadsTheAPIsTwoVariablesAlone(t *testing.T) {
	poison := t.TempDir()
	for _, name := range []string{"INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN",
		"FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD", "FYLGJA_EOS_USERNAME", "FYLGJA_EOS_PASSWORD",
		lab.EnvTemporalAddress, "FYLGJA_TEMPORAL_NAMESPACE", lab.EnvHostMemoryMB} {
		t.Setenv(name, "poison-"+name)
	}
	t.Setenv(lab.EnvStateRoot, filepath.Join(poison, "state"))
	t.Setenv(lab.EnvPSPDir, filepath.Join(poison, "no-such-packages"))
	// The server dials nothing and asks the host nothing: these values reach only it.
	countDials(t)
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	dryRunRunner = runnerFunc(func(...string) {})
	asked := askedEnv(t, strings.TrimPrefix(harness.http.URL, "http://"))

	for _, args := range clientCommands(t) {
		before := requestsLogged()
		executeClient(t, args...)
		if awaitLogged(before+1) != before+1 {
			t.Errorf("fylgja %s: the server logged %d requests, want 1", strings.Join(args, " "), requestsLogged()-before)
		}
	}
	for _, name := range asked() {
		if name != api.EnvAddress && name != api.EnvToken {
			t.Errorf("the client asked its environment for %s", name)
		}
	}
	if !slices.Contains(asked(), api.EnvAddress) || !slices.Contains(asked(), api.EnvToken) {
		t.Errorf("the client asked %v, want both of the API's variables", asked())
	}
}

// awaitLogged is requestsLogged once it reaches want, or after a second: the server logs a
// request when its handler returns, after the client has read the document.
func awaitLogged(want int) int {
	deadline := time.Now().Add(time.Second)
	for {
		n := requestsLogged()
		if n >= want || time.Now().After(deadline) {
			return n
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// No file of the client's code reads the environment but through getenv: the variable's own
// default, os.LookupEnv, is the one read, so nothing a test cannot see can read a name.
func TestTheClientReadsTheEnvironmentThroughGetenvAlone(t *testing.T) {
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	var reads []string
	for _, f := range files {
		if strings.HasSuffix(f, "_test.go") {
			continue
		}
		parsed, err := parser.ParseFile(token.NewFileSet(), f, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if pkg, ok := sel.X.(*ast.Ident); ok && (pkg.Name == "os" || pkg.Name == "syscall") &&
				slices.Contains([]string{"Getenv", "LookupEnv", "Environ", "ExpandEnv", "Expand"}, sel.Sel.Name) {
				reads = append(reads, f+": "+pkg.Name+"."+sel.Sel.Name)
			}
			return true
		})
	}
	if !slices.Equal(reads, []string{"root.go: os.LookupEnv"}) {
		t.Errorf("the client's code reads the environment at %v, want getenv's default in root.go alone", reads)
	}
}

// --psp-dir is no flag of a client's command: given one, each ends with cobra's own unknown
// flag, exit 2, and sends nothing.
func TestNoClientsCommandTakesPSPDir(t *testing.T) {
	askedEnv(t, strings.TrimPrefix(harness.http.URL, "http://"))
	for _, args := range clientCommands(t) {
		before := requestsLogged()
		// --json comes first: cobra stops reading flags at the unknown one.
		opts := &options{}
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
		root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
		root.AddCommand(newTwinCmd(opts), newIntentCmd(opts), newWaypointCmd(opts), newSchemaCmd(opts), newPSPCmd(opts))
		root.SetArgs(append(append([]string{"--json"}, args...), "--psp-dir", "x"))
		var code int
		out := captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
		var doc findings.Document
		if err := json.Unmarshal([]byte(out), &doc); err != nil {
			t.Fatalf("fylgja %s --psp-dir x: stdout is not one findings document: %v\n%s", strings.Join(args, " "), err, out)
		}
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Message != "unknown flag: --psp-dir" {
			t.Errorf("fylgja %s --psp-dir x: exit %d, findings %+v; want 2, cobra's unknown flag", strings.Join(args, " "), code, doc.Findings)
		}
		if got := requestsLogged(); got != before {
			t.Errorf("fylgja %s --psp-dir x: the server logged %d requests, want none", strings.Join(args, " "), got-before)
		}
	}
}

// fylgja --version and --help reach no server, with no token set: they end at cobra.
func TestVersionAndHelpReachNoServer(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	var accepted atomic.Int32
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			accepted.Add(1)
			_ = c.Close()
		}
	}()
	var asked []string
	saved := getenv
	t.Cleanup(func() { getenv = saved })
	getenv = func(name string) (string, bool) {
		asked = append(asked, name)
		if name == api.EnvAddress {
			return l.Addr().String(), true
		}
		return "", false
	}
	for _, flag := range []string{"--version", "--help"} {
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true, Version: version}
		AddCommands(root, version)
		var out bytes.Buffer
		root.SetOut(&out)
		root.SetArgs([]string{flag})
		cmd, err := root.ExecuteC()
		if code := Report(cmd, err); code != findings.ExitOK || out.Len() == 0 {
			t.Errorf("fylgja %s: exit %d, output %q; want 0 and cobra's text", flag, code, out.String())
		}
	}
	if n := accepted.Load(); n != 0 || len(asked) != 0 {
		t.Errorf("the address took %d connections and the environment was asked %v; want neither", n, asked)
	}
}

// FYLGJA_API_ADDRESS as host:port and as an http:// URL both reach the server.
func TestTheAddressIsHostPortOrAURL(t *testing.T) {
	hostPort := strings.TrimPrefix(harness.http.URL, "http://")
	for _, address := range []string{hostPort, "http://" + hostPort} {
		askedEnv(t, address)
		before := len(requestOutcomes(findings.OpTwinShow))
		useService(t, &fakeService{readOnly: t})
		useStateRoot(t)
		useInspect(t, []byte("{}"))
		printedBy(t, func() { sentDocument(t, runShow(context.Background(), &options{asJSON: true})) })
		if got := servedAfter(t, findings.OpTwinShow, before); got != string(findings.StatusOK) {
			t.Errorf("FYLGJA_API_ADDRESS=%s: the server logged %s, want ok", address, got)
		}
	}
}
