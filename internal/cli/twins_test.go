package cli

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http/httptest"
	"os"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/spf13/cobra"
	"go.temporal.io/sdk/activity"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

// The helpers a tier-1 test builds a twin with from a snapshot, and reads it back by: kept
// from the stage and intent tests 020 removed with the operations they drove (D-065), which
// the create, step and show tests share.

// fixtureAt is the fixture's at, the at its snapshot under testdata/snapshot/ names.
const fixtureAt = "2026-09-08T12:00:00Z"

// bundleIDRE is a bundle id's form.
var bundleIDRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

// snapshotCTM is the CTM of the snapshot file at path.
func snapshotCTM(t *testing.T, path string) *ctm.CTM {
	t.Helper()
	s, err := snap.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	return s.CTM
}

// executeTwin runs `fylgja <args> --json` through the command line, as an operator would,
// and returns its exit status and findings document.
func executeTwin(t *testing.T, args ...string) (int, *findings.Document) {
	t.Helper()
	opts := &options{asJSON: true}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts))
	root.SetArgs(append(args, "--json"))
	var code int
	out := captureStdout(t, func() {
		cmd, err := root.ExecuteC()
		code = report(opts, cmd, err)
	})
	var doc findings.Document
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, out)
	}
	return code, &doc
}

// writtenRecord is what twin.json says of the reference it was read at, as written; since
// twin.json 12 it names no stage (020, research R-06).
type writtenRecord struct {
	TwinVersion string           `json:"twin_version"`
	SnapshotID  *string          `json:"snapshot_id"`
	BundleID    string           `json:"bundle_id"`
	Provenance  wire.Provenance  `json:"provenance"`
	Source      string           `json:"source"`
	Step        *wire.StepRecord `json:"step"`
}

func decodeRecord(t *testing.T, record []byte) writtenRecord {
	t.Helper()
	var w writtenRecord
	if err := json.Unmarshal(record, &w); err != nil {
		t.Fatalf("twin.json does not decode: %v\n%s", err, record)
	}
	return w
}

// validateTwinJSON validates twin.json as written against the current
// contracts/twin.schema.json, version 8 since 017.
func validateTwinJSON(t *testing.T, record []byte) {
	t.Helper()
	f, err := os.Open(repoPath("contracts", "twin.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("twin.schema.json", doc); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("twin.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := validateAgainst(schema, record); err != nil {
		t.Errorf("twin.json does not satisfy contracts/twin.schema.json:\n%v\n%s", err, record)
	}
}

// provisionOnSuite runs the Provision workflow with in on Temporal's test suite, with the
// worker's own activities wherever they need no host, as
// TestConfigurationBytesGoToTheNodeAndNowhereElse drives a create: the host check over a
// recorded empty host,
// the stage, the readiness, the push to a node that commits whatever it is sent, and the
// record. Only the deploy answers as containerlab would. It returns the run's result and
// twin.json as the run wrote it.
func provisionOnSuite(t *testing.T, paths lab.Paths, in provision.ProvisionInput) (provision.ProvisionResult, []byte) {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	inspect, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-empty.json"))
	if err != nil {
		t.Fatal(err)
	}
	node := httptest.NewTLSServer(&markerNode{})
	t.Cleanup(node.Close)
	nodeHost, nodePort, err := net.SplitHostPort(strings.TrimPrefix(node.URL, "https://"))
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(nodePort)

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	store := bundle.NewDirStore(paths.Bundles)
	acts := &lab.Activities{
		Clab: &lab.Clab{Runner: &fakeClab{stdout: inspect}, Log: logger}, Store: store, Paths: paths, Registry: reg,
		Prober: readyProber{},
		Getenv: func(k string) (string, bool) {
			v, ok := map[string]string{"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": "not-the-real-one"}[k]
			return v, ok
		},
		Version: version, Log: logger,
	}
	activities := acts.Names()
	activities[wire.ActDeployLab] = func(_ context.Context, in wire.DeployInput) (wire.DeployResult, error) {
		var res wire.DeployResult
		for _, n := range in.Nodes {
			res.Nodes = append(res.Nodes, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Kind: "nokia_srlinux",
				Image: n.Image, State: "running", MgmtIPv4: nodeHost})
		}
		return res, nil
	}
	activities[wire.ActPushConfig] = func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
		// Only the port differs from the package's: the node is this test's.
		in.Push.Port = port
		return acts.PushConfig(ctx, in)
	}

	var suite testsuite.WorkflowTestSuite
	suite.SetLogger(tlog.NewStructuredLogger(logger))
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterWorkflow(provision.Provision)
	for name, fn := range activities {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	env.ExecuteWorkflow(provision.Provision, in)
	if !env.IsWorkflowCompleted() || env.GetWorkflowError() != nil {
		t.Fatalf("the run did not complete: %v", env.GetWorkflowError())
	}
	var res provision.ProvisionResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	if res.Outcome != provision.OutcomeReady {
		t.Fatalf("the run ended %s at %s: %+v", res.Outcome, res.Step, res.Findings)
	}
	record, err := os.ReadFile(paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	return res, record
}

// runRoot runs `fylgja <args>` with the twin noun, in text, and returns its exit status and
// what it printed.
func runRoot(t *testing.T, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts))
	root.SetArgs(args)
	stderr = captureStderr(t, func() {
		stdout = captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
	})
	return code, stdout, stderr
}

// storedBundles is the ids the store holds, none with a CTM beside it: the sidecar is
// retired (018).
func storedBundles(t *testing.T, bundles string) []string {
	t.Helper()
	entries, err := os.ReadDir(bundles)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, e := range entries {
		if e.IsDir() && bundleIDRE.MatchString(e.Name()) {
			ids = append(ids, e.Name())
			if _, err := os.Stat(bundles + "/" + e.Name() + ".ctm.json"); !os.IsNotExist(err) {
				t.Errorf("bundle %s is filed with a CTM beside it (%v); the sidecar is retired", e.Name(), err)
			}
		}
	}
	sort.Strings(ids)
	return ids
}

func sortedCopy(ids ...string) []string {
	out := slices.Clone(ids)
	sort.Strings(out)
	return out
}

// headSnapshotID and headBundleID are the fixture branch's head snapshot and the bundle it
// compiles to: the fixture's intent, its envelope naming no at, as an unpinned read of the
// fixture branch took it before 020 moved the read to the orchestrator.
const (
	headSnapshotID = "0d37e2ec3186bb59f58ee414a5ff34bd3e3833637c9684dfb4e6b337805a61f1"
	headBundleID   = "16141134f94cef43492b5e80dc986a19c446f647a3ed660a5b615dc525848fe0"
)

// useFixtureSnapshot points the state root at a fresh directory and files the fixture
// branch's head snapshot in its store, so a create of headSnapshotID builds the fixture with
// nothing read: since 020 a create builds from a snapshot alone (D-065).
func useFixtureSnapshot(t *testing.T) lab.Paths {
	t.Helper()
	paths := useStateRoot(t)
	c := snapshotCTM(t, repoPath("testdata", "snapshot", "three-node.json"))
	c.Envelope.At = ""
	s := snap.Take(c, nil)
	if s.ID != headSnapshotID {
		t.Fatalf("the fixture's head snapshot is %s, want %s", s.ID, headSnapshotID)
	}
	if _, err := snap.NewDirStore(paths.Snapshots).Put(context.Background(), s); err != nil {
		t.Fatal(err)
	}
	return paths
}
