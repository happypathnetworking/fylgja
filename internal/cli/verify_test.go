package cli

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// fakeNodes answers twin verify's reads as the twin's nodes would, from a table keyed by
// "<addr> <path>" in internal/verify's test shape: the n-th read of a key gets the n-th
// answer of its sequence, the last repeating, so a node can settle late; an error is the
// transport's. A read the table does not hold is an error, so a test sees any read it did
// not expect. Every call is recorded, with the probe each address was read over.
type fakeNodes struct {
	nodes   map[string]fakeNode // by node name
	answers map[string][]verify.Answer
	errs    map[string]error
	// onGet, when set, sees each read's probe and environment before it is answered.
	onGet func(probe wire.Probe, getenv func(string) (string, bool))

	mu     sync.Mutex
	calls  []string
	probes map[string]wire.Probe
	reads  map[string]int
}

// fakeNode is where a node answers and in which platform's shapes.
type fakeNode struct {
	addr, psp string
}

func (f *fakeNodes) Get(_ context.Context, addr string, probe wire.Probe, path string, getenv func(string) (string, bool)) (verify.Answer, error) {
	if f.onGet != nil {
		f.onGet(probe, getenv)
	}
	key := addr + " " + path
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, key)
	f.probes[addr] = probe
	n := f.reads[key]
	f.reads[key]++
	if err, ok := f.errs[addr]; ok {
		return verify.Answer{}, err
	}
	seq, ok := f.answers[key]
	if !ok || len(seq) == 0 {
		return verify.Answer{}, fmt.Errorf("the fake node has no answer for %s", key)
	}
	return seq[min(n, len(seq)-1)], nil
}

// The two shipped packages' paths as their conformance facets declare them, rendered, and the
// shapes their nodes answer in: SR Linux a leaf at the leaf and a neighbour list at its list
// entry, cEOS one update per neighbour entry.
func hostNamePath(psp string) string {
	if psp == "arista_eos" {
		return "/system/state/hostname"
	}
	return "/system/name/host-name"
}

func enabledPath(psp, port string) string {
	if psp == "arista_eos" {
		return "/interfaces/interface[name=" + port + "]/state/admin-status"
	}
	return "/interface[name=" + port + "]/admin-state"
}

func neighbourPath(psp, port string) string {
	if psp == "arista_eos" {
		return "/lldp/interfaces/interface[name=" + port + "]/neighbors/neighbor"
	}
	return "/system/lldp/interface[name=" + port + "]/neighbor"
}

func at(path string, v any) verify.Answer {
	return verify.Answer{Updates: []verify.Update{{Path: path, Value: v}}}
}

// healthyNodes answers every read of the staged manifest's twin as a conforming twin
// would: each node its own name, each cabled port enabled, each link end the far node and
// port under the far node's own name. ips are the nodes' management addresses.
func healthyNodes(t *testing.T, m compiler.Manifest, ips map[string]string) *fakeNodes {
	t.Helper()
	f := &fakeNodes{nodes: map[string]fakeNode{}, answers: map[string][]verify.Answer{}, errs: map[string]error{},
		probes: map[string]wire.Probe{}, reads: map[string]int{}}
	for _, n := range m.Nodes {
		port := "57400"
		if n.PSP.ID == "arista_eos" {
			port = "6030"
		}
		f.nodes[n.Name] = fakeNode{addr: ips[n.Name] + ":" + port, psp: n.PSP.ID}
		if n.PSP.ID == "arista_eos" {
			f.set(n.Name, hostNamePath(n.PSP.ID), at("openconfig-system:system/state/hostname", n.Name))
		} else {
			f.set(n.Name, hostNamePath(n.PSP.ID), at("srl_nokia-system:system/srl_nokia-system-name:name/host-name", n.Name))
		}
	}
	type end struct{ node, port string }
	rows := map[end]compiler.MappingRow{}
	for _, r := range m.Mapping {
		if r.Disposition == compiler.DispCabled && r.Port != nil {
			rows[end{r.Device, *r.Port}] = r
		}
	}
	for _, l := range m.Links {
		a, b := rows[end{l.A.Node, l.A.Port}], rows[end{l.B.Node, l.B.Port}]
		for _, p := range [][2]compiler.MappingRow{{a, b}, {b, a}} {
			near, far := p[0], p[1]
			f.enabled(near.Device, verify.NodeName(near), "")
			f.neighbours(near.Device, verify.NodeName(near), [2]string{far.Device, verify.NodeName(far)})
		}
	}
	return f
}

// set answers one node's path with one answer, or a sequence of them.
func (f *fakeNodes) set(node, path string, answers ...verify.Answer) {
	f.answers[f.nodes[node].addr+" "+path] = answers
}

// enabled answers a port's state as its platform says enabled, or with value.
func (f *fakeNodes) enabled(node, port, value string) {
	psp := f.nodes[node].psp
	if psp == "arista_eos" {
		if value == "" {
			value = "UP"
		}
		f.set(node, enabledPath(psp, port), at("openconfig-interfaces:interfaces/interface[name="+port+"]/state/admin-status", value))
		return
	}
	if value == "" {
		value = "enable"
	}
	f.set(node, enabledPath(psp, port), at("srl_nokia-interfaces:interface[name="+port+"]/admin-state", value))
}

// neighbours answers a port's neighbour list with entries, each a far node and port.
func (f *fakeNodes) neighbours(node, port string, entries ...[2]string) {
	f.set(node, neighbourPath(f.nodes[node].psp, port), f.neighbourAnswer(node, port, entries...))
}

func (f *fakeNodes) neighbourAnswer(node, port string, entries ...[2]string) verify.Answer {
	psp := f.nodes[node].psp
	if psp == "arista_eos" {
		var a verify.Answer
		for i, e := range entries {
			a.Updates = append(a.Updates, verify.Update{
				Path: fmt.Sprintf("%s[id=%d]", strings.TrimPrefix(neighbourPath(psp, port), "/"), i+1),
				Value: map[string]any{"openconfig-lldp:id": fmt.Sprint(i + 1),
					"openconfig-lldp:state": map[string]any{"system-name": e[0], "port-id": e[1]}},
			})
		}
		return a
	}
	list := []any{}
	for i, e := range entries {
		list = append(list, map[string]any{"id": fmt.Sprintf("1A:EB:0%d:FF:00:00", i+1), "system-name": e[0], "port-id": e[1]})
	}
	return at("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]", map[string]any{"neighbor": list})
}

// unreachableNode makes every read of node fail at the transport.
func (f *fakeNodes) unreachableNode(node string, err error) { f.errs[f.nodes[node].addr] = err }

func (f *fakeNodes) called() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.calls)
}

// noNodes is a reader for a run that must read no node: any call fails the test.
type noNodes struct{ t *testing.T }

func (n noNodes) Get(_ context.Context, addr string, _ wire.Probe, path string, _ func(string) (string, bool)) (verify.Answer, error) {
	n.t.Errorf("a node was read (%s %s) before a refusal that comes before any read", addr, path)
	return verify.Answer{}, errors.New("no node may be read")
}

// The twin's nodes as tier 3's containerlab names them: each golden's nodes, in name
// order, at the addresses inspect-three.json gives n1, n2 and n3.
var verifyNodeOrder = map[string][]string{
	"three-node": {"n1", "n2", "n3"},
	"mixed":      {"e1", "e2", "s1"},
	"lossy":      {"c1", "c2", "s1"},
}

// verifyTwinHost is a host running a golden's twin, as verifyHost builds it.
type verifyTwinHost struct {
	paths  lab.Paths
	m      compiler.Manifest
	staged string
	ips    map[string]string
	svc    *fakeService
}

// verifyHost is a host running the golden's twin: the bundle staged in the twin directory,
// edited first by edit when given (a manifest the compiler wrote, as JSON); its twin.json 4
// naming every node at its address and holding the staged bundle, changed by change; the
// same bundle in the store; containerlab answering inspect-three.json with the golden's
// nodes; both logins set, the passwords and the token the sentinel no output may carry; and
// the fake workflow service, read-only, answering nothing in flight.
func verifyHost(t *testing.T, golden string, edit func(map[string]any), change func(*wire.TwinRecord)) *verifyTwinHost {
	t.Helper()
	paths := useStateRoot(t)
	mixedDryRunEnv(t)
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", sentinel)
	t.Setenv("FYLGJA_EOS_PASSWORD", sentinel)
	t.Setenv(intent.EnvToken, sentinel)
	t.Setenv(lab.EnvTemporalAddress, "")
	t.Setenv(lab.EnvPSPDir, "")

	copyTree(t, repoPath("testdata", "golden", golden), paths.TwinBundle)
	if edit != nil {
		editManifest(t, paths.TwinBundle, edit)
	}
	staged, err := bundle.IDOfDir(paths.TwinBundle)
	if err != nil {
		t.Fatal(err)
	}
	copyTree(t, paths.TwinBundle, bundle.NewDirStore(paths.Bundles).Path(staged))
	m, err := stagedManifest(paths.TwinBundle)
	if err != nil {
		t.Fatal(err)
	}

	ips := map[string]string{}
	f := lab.RecordFields{
		BundleID:   staged,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "41349c3a9c582e5dd44e55d6771f79c2", ContractVersion: "0.2"},
		Source:     wire.SourceIntent,
		RunID:      showRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 10, 3, 9, 1, 2, 0, time.UTC),
	}
	observed := "2026-10-03T09:00:00.000000Z"
	f.ObservedAt = &observed
	for i, name := range verifyNodeOrder[golden] {
		ips[name] = fmt.Sprintf("172.20.20.%d", i+2)
		for _, n := range m.Nodes {
			if n.Name == name {
				f.Nodes = append(f.Nodes, wire.TwinNode{Name: name, Container: "clab-fylgja-" + name, Image: n.Image,
					PSP: wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}, MgmtIPv4: ips[name], ReadyAfterS: 9})
			}
		}
	}
	rec, err := lab.NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	if change != nil {
		change(&rec)
	}
	writeTwin(t, paths, rec)

	useInspect(t, goldenInspect(t, golden, nil))

	svc := &fakeService{readOnly: t}
	useService(t, svc)
	return &verifyTwinHost{paths: paths, m: m, staged: staged, ips: ips, svc: svc}
}

// goldenInspect is containerlab's inspection of the golden's twin, inspect-three.json with its
// nodes renamed, each container's entry changed by edit first when given: an entry left out
// is a node containerlab does not report.
func goldenInspect(t *testing.T, golden string, edit func([]map[string]any) []map[string]any) []byte {
	t.Helper()
	inspect, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-three.json"))
	if err != nil {
		t.Fatal(err)
	}
	for i, name := range verifyNodeOrder[golden] {
		inspect = []byte(strings.ReplaceAll(string(inspect), fmt.Sprintf("clab-fylgja-n%d", i+1), "clab-fylgja-"+name))
	}
	if edit == nil {
		return inspect
	}
	var labs map[string][]map[string]any
	if err := json.Unmarshal(inspect, &labs); err != nil {
		t.Fatal(err)
	}
	labs[wire.LabName] = edit(labs[wire.LabName])
	if inspect, err = json.Marshal(labs); err != nil {
		t.Fatal(err)
	}
	return inspect
}

// withoutContainer leaves a node's container out of an inspection.
func withoutContainer(node string) func([]map[string]any) []map[string]any {
	return func(cs []map[string]any) []map[string]any {
		return slices.DeleteFunc(cs, func(c map[string]any) bool { return c["name"] == "clab-fylgja-"+node })
	}
}

// inspections answers containerlab's n-th inspection with the n-th answer, the last
// repeating, and counts them. runVerify runs the command twice, once in text and once with
// --json, so a test resets the count each time its reader is built.
type inspections struct {
	mu      sync.Mutex
	answers [][]byte
	n       int
}

func (f *inspections) Run(_ context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !slices.Equal(args, inspectAll) {
		return nil, []byte("inspections: only an inspection is answered"), 1, nil
	}
	f.n++
	return f.answers[min(f.n, len(f.answers))-1], nil, 0, nil
}

func (f *inspections) reset() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := f.n
	f.n = 0
	return n
}

// useInspections makes containerlab answer its inspections in turn.
func useInspections(t *testing.T, answers ...[]byte) *inspections {
	t.Helper()
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	f := &inspections{answers: answers}
	dryRunRunner = f
	return f
}

// useInspect makes containerlab answer every call with inspect.
func useInspect(t *testing.T, inspect []byte) {
	t.Helper()
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	dryRunRunner = &fakeClab{stdout: inspect}
}

// healthy is a reader answering this host's twin as a conforming one.
func (h *verifyTwinHost) healthy(t *testing.T) *fakeNodes { return healthyNodes(t, h.m, h.ips) }

// copyTree copies the directory src to dst.
func copyTree(t *testing.T, src, dst string) {
	t.Helper()
	err := filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

// editManifest rewrites a bundle's manifest through edit, as JSON.
func editManifest(t *testing.T, dir string, edit func(map[string]any)) {
	t.Helper()
	path := filepath.Join(dir, compiler.ManifestFile)
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	edit(m)
	if b, err = json.MarshalIndent(m, "", "  "); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

// disableRow sets the mapping row of device's interface to enabled false, as bundle 4
// writes a port intent disables.
func disableRow(device, iface string) func(map[string]any) {
	return func(m map[string]any) {
		for _, r := range m["mapping"].([]any) {
			row := r.(map[string]any)
			if row["device"] == device && row["interface"] == iface {
				row["enabled"] = false
			}
		}
	}
}

// asBundle3 makes a manifest a "3" one: the version, and no enabled key on any row.
func asBundle3(m map[string]any) {
	m["bundle_version"] = "3"
	for _, r := range m["mapping"].([]any) {
		delete(r.(map[string]any), "enabled")
	}
}

// treeDigest is every path under root with its mode, size, time and content hash: what
// twin verify must leave as it found it.
func treeDigest(t *testing.T, root string) []string {
	t.Helper()
	var out []string
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		line := fmt.Sprintf("%s %s %d %s", p, info.Mode(), info.Size(), info.ModTime())
		if !d.IsDir() {
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			sum := sha256.Sum256(b)
			line += " " + hex.EncodeToString(sum[:])
		}
		out = append(out, line)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// verifyOutput is what twin verify put in front of the operator: the exit status, the text
// on stdout and on stderr (the findings as main renders them), the JSON document, and every
// read the text run made.
type verifyOutput struct {
	code   int
	stdout string
	stderr string
	doc    *findings.Document
	calls  []string
	probes map[string]wire.Probe
}

// verifyClock is --wait's fake clock: each pause moves it on by the pause.
func useVerifyClock(t *testing.T) {
	t.Helper()
	now := time.Date(2026, 10, 3, 10, 0, 0, 0, time.UTC)
	var mu sync.Mutex
	savedSleep, savedNow := verifySleep, verifyNow
	t.Cleanup(func() { verifySleep, verifyNow = savedSleep, savedNow })
	verifySleep = func(_ context.Context, d time.Duration) error {
		mu.Lock()
		defer mu.Unlock()
		now = now.Add(d)
		return nil
	}
	verifyNow = func() time.Time {
		mu.Lock()
		defer mu.Unlock()
		return now
	}
}

// runVerify runs `fylgja twin verify <args>` through the command line, once in text and
// once with --json, each over a reader of its own from nodes (nil: no node may be read) and
// --wait on a fake clock. The JSON document is validated against this feature's contracts;
// no output carries a password, the token, the marker or a configuration line; and the
// state root, the record, the staged bundle and the store with it, is left as it was.
func runVerify(t *testing.T, root string, nodes func() *fakeNodes, args ...string) verifyOutput {
	t.Helper()
	before := treeDigest(t, root)
	var out verifyOutput
	run := func(asJSON bool) (int, string, string, *fakeNodes) {
		useVerifyClock(t)
		saved := verifyReader
		t.Cleanup(func() { verifyReader = saved })
		var reader *fakeNodes
		if nodes == nil {
			verifyReader = noNodes{t}
		} else {
			reader = nodes()
			verifyReader = reader
		}
		opts := &options{}
		cmdRoot := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
		cmdRoot.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
		cmdRoot.AddCommand(newTwinCmd(opts))
		all := append([]string{"twin", "verify"}, args...)
		if asJSON {
			all = append(all, "--json")
		}
		cmdRoot.SetArgs(all)
		var code int
		var stdout string
		stderr := captureStderr(t, func() {
			stdout = captureStdout(t, func() {
				cmd, err := cmdRoot.ExecuteC()
				code = report(opts, cmd, err)
			})
		})
		return code, stdout, stderr, reader
	}
	var reader *fakeNodes
	out.code, out.stdout, out.stderr, reader = run(false)
	if reader != nil {
		out.calls, out.probes = reader.called(), reader.probes
	}
	code, jsonOut, jsonErr, _ := run(true)
	if code != out.code {
		t.Errorf("--json exits %d, text %d", code, out.code)
	}
	if jsonErr != "" {
		t.Errorf("--json wrote on stderr: %s", jsonErr)
	}
	out.doc = &findings.Document{}
	if err := json.Unmarshal([]byte(jsonOut), out.doc); err != nil {
		t.Fatalf("stdout is not one findings document: %v\n%s", err, jsonOut)
	}
	validateM10Document(t, out.doc)
	if out.doc.Operation != findings.OpTwinVerify || out.doc.Subject != nil {
		t.Errorf("operation %q, subject %+v; want %s and none", out.doc.Operation, out.doc.Subject, findings.OpTwinVerify)
	}
	if out.doc.Status.ExitCode() != out.code {
		t.Errorf("status %s, exit %d", out.doc.Status, out.code)
	}
	noContent(t, "twin verify", out.stdout, out.stderr, jsonOut)
	for what, s := range map[string]string{"stdout": out.stdout, "stderr": out.stderr, "the document": jsonOut} {
		if strings.Contains(s, sentinel) {
			t.Errorf("%s carries a password or the token:\n%s", what, s)
		}
	}
	if after := treeDigest(t, root); !slices.Equal(before, after) {
		t.Errorf("twin verify changed the state root:\n  %v\nto\n  %v", before, after)
	}
	return out
}

// wantOnly holds a document to exactly one finding, rule, step, object and message, and its
// exit status.
func wantOnly(t *testing.T, out verifyOutput, exit int, want findings.Finding) {
	t.Helper()
	if out.code != exit {
		t.Errorf("exit %d, want %d", out.code, exit)
	}
	if len(out.doc.Findings) != 1 || out.doc.Findings[0] != want {
		t.Errorf("findings %+v\nwant exactly %+v", out.doc.Findings, want)
	}
	if out.doc.Verify != nil {
		t.Errorf("a refusal carries a verify block: %+v", out.doc.Verify)
	}
	if !strings.Contains(out.stderr, want.Rule) {
		t.Errorf("stderr does not name %s:\n%s", want.Rule, out.stderr)
	}
}

// The staged bundle's three-node twin, read whole, as the text layout prints it.
func threeNodeLines(id string) []string {
	s := short(id)
	return []string{
		"twin: branch fylgja-fixture (bundle " + s + "), ready; 3 nodes",
		"staged: bundle " + s + "; 15 assertions over 3 nodes, 0 skipped",
		"n1 (172.20.20.2:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2; record: holds " + s,
		"n2 (172.20.20.3:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; record: holds " + s,
		"n3 (172.20.20.4:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2; record: holds " + s,
		"skipped: none",
		"in flight: none",
		"held: 3 host names, 6 ports, 6 link ends, 3 record claims (the record's, not read); failed: none; unread: none",
	}
}

// Every refusal of contracts/cli.md's table before any node is read, through the command
// line: its exit, step, object and message, no verify block, and not one read of a node.
func TestVerifyRefusesBeforeAnyRead(t *testing.T) {
	waitInvalid := func(message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyWaitInvalid, Object: "--wait",
			Message: message, Step: findings.StepStart}
	}
	for _, c := range []struct {
		args    []string
		message string
	}{
		{[]string{"--wait=banana"}, `--wait=banana is not a duration: time: invalid duration "banana"`},
		{[]string{"--wait=-5s"}, "--wait=-5s is not a duration: a budget cannot be negative"},
		{[]string{"--wait="}, "--wait= is empty; give a duration such as --wait=2m, or --wait alone for the default 2m0s"},
		{[]string{"--wait", "2m"}, `--wait takes its value as --wait=<duration>; "2m" was given as an argument`},
	} {
		t.Run(strings.Join(c.args, " "), func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			// Refused before the packages, the host and the service: the containerlab
			// recording is never asked.
			clab := &fakeClab{}
			saved := dryRunRunner
			t.Cleanup(func() { dryRunRunner = saved })
			dryRunRunner = clab
			useService(t, nil)
			out := runVerify(t, h.paths.Root, nil, c.args...)
			wantOnly(t, out, findings.ExitError, waitInvalid(c.message))
			if len(clab.calls) != 0 {
				t.Errorf("containerlab was asked %v before --wait was refused", clab.calls)
			}
		})
	}

	t.Run("an argument without --wait is cobra's usage error", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		useService(t, nil)
		out := runVerify(t, h.paths.Root, nil, "2m")
		if out.code != findings.ExitError || len(out.doc.Findings) != 1 || out.doc.Findings[0].Rule != findings.RuleOperationFailed ||
			!strings.Contains(out.doc.Findings[0].Message, `unknown command "2m" for "fylgja twin verify"`) {
			t.Errorf("exit %d, findings %+v; want cobra's usage error, exit 2", out.code, out.doc.Findings)
		}
	})

	t.Run("an override package psp validate rejects", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		t.Setenv(lab.EnvPSPDir, overridePackage(t, "nokia_srlinux", "probe: gnmi_get", "probe: banana"))
		useService(t, nil)
		out := runVerify(t, h.paths.Root, nil)
		if out.code != findings.ExitRejected || len(out.doc.Findings) == 0 || out.doc.Verify != nil {
			t.Fatalf("exit %d, document %+v; want 1 with the package's findings", out.code, out.doc)
		}
		for _, f := range out.doc.Findings {
			if !strings.HasPrefix(f.Rule, "psp.") || f.Step != "" {
				t.Errorf("finding %+v, want M6's psp.* rules with no step", f)
			}
		}
	})

	t.Run("a host that cannot be inspected", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		useInspect(t, []byte("not json"))
		useService(t, nil)
		out := runVerify(t, h.paths.Root, nil)
		if out.code != findings.ExitError || len(out.doc.Findings) != 1 {
			t.Fatalf("exit %d, findings %+v; want exit 2 and one finding", out.code, out.doc.Findings)
		}
		f := out.doc.Findings[0]
		if f.Rule != findings.RuleOperationFailed || f.Step != findings.StepObserve || f.Object != "lab fylgja" ||
			!strings.HasPrefix(f.Message, "inspecting the host: ") {
			t.Errorf("finding %+v; want operation.failed at observe on lab fylgja, inspecting the host", f)
		}
	})

	const orphan = "an orphan: no twin.json records it; deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml"
	absent := func(object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyTwinAbsent, Object: object,
			Message: message, Step: findings.StepObserve}
	}
	inspectThree, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-three.json"))
	if err != nil {
		t.Fatal(err)
	}
	inspectEmpty, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-empty.json"))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name     string
		inspect  []byte
		twin     func(lab.Paths) // what the twin directory holds; nil removes it
		inFlight []provision.RunInFlight
		want     func(lab.Paths) findings.Finding
	}{
		{"an empty host", inspectEmpty, nil, nil, func(lab.Paths) findings.Finding {
			return absent("lab fylgja", "no twin: no lab fylgja and no twin directory; nothing to verify")
		}},
		{"an orphan", inspectThree, nil, nil, func(lab.Paths) findings.Finding {
			return absent("lab fylgja", orphan+"; nothing to verify; fylgja twin destroy clears it")
		}},
		{"a record whose lab is absent", inspectEmpty, func(lab.Paths) {}, nil, func(p lab.Paths) findings.Finding {
			rec, err := lab.ReadRecord(p.TwinJSON)
			if err != nil {
				t.Fatal(err)
			}
			return absent(p.Twin, "the twin of branch fylgja-fixture, bundle_id "+rec.BundleID+", provisioned by run fylgja-provision "+
				showRunID+", 3 nodes recorded, but lab fylgja is absent; nothing to verify; fylgja twin destroy clears it")
		}},
		{"a leftover twin directory", inspectEmpty, func(p lab.Paths) {
			if err := os.Remove(p.TwinJSON); err != nil {
				t.Fatal(err)
			}
		}, nil, func(p lab.Paths) findings.Finding {
			return absent(p.Twin, "a leftover twin directory: no twin.json and no lab fylgja; nothing to verify; fylgja twin destroy clears it")
		}},
		{"an unreadable record", inspectThree, func(p lab.Paths) {
			if err := os.WriteFile(p.TwinJSON, []byte("{"), 0o644); err != nil {
				t.Fatal(err)
			}
		}, nil, func(p lab.Paths) findings.Finding {
			_, err := lab.ReadRecord(p.TwinJSON)
			return absent("lab fylgja", "treated as an orphan: twin.json could not be read ("+err.Error()+
				"); deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml; nothing to verify; fylgja twin destroy clears it")
		}},
		{"an orphan an operator's create is building", inspectThree, nil,
			[]provision.RunInFlight{{WorkflowID: provision.WorkflowProvision, RunID: "r-p", Step: findings.StepDeploy}},
			func(lab.Paths) findings.Finding {
				return absent("lab fylgja", orphan+"; nothing to verify; run fylgja-provision r-p is at step deploy")
			}},
		{"an empty host a check is rebuilding", inspectEmpty, nil,
			[]provision.RunInFlight{{WorkflowID: "fylgja-reconcile-2026-10-03T10:00:00Z", RunID: "r-c", Step: findings.StepProvision}},
			func(lab.Paths) findings.Finding {
				return absent("lab fylgja", "no twin: no lab fylgja and no twin directory; nothing to verify; "+
					"run fylgja-reconcile-2026-10-03T10:00:00Z r-c is at step provision")
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			if c.twin == nil {
				if err := os.RemoveAll(h.paths.Twin); err != nil {
					t.Fatal(err)
				}
			} else {
				c.twin(h.paths)
			}
			useInspect(t, c.inspect)
			h.svc.inFlight = c.inFlight
			out := runVerify(t, h.paths.Root, nil)
			wantOnly(t, out, findings.ExitRejected, c.want(h.paths))
		})
	}

	t.Run("a staged bundle that cannot be read", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		if err := os.Remove(filepath.Join(h.paths.TwinBundle, compiler.ManifestFile)); err != nil {
			t.Fatal(err)
		}
		out := runVerify(t, h.paths.Root, nil)
		wantOnly(t, out, findings.ExitError, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed,
			Object: h.paths.TwinBundle, Step: findings.StepObserve, Message: "reading the staged bundle: open " +
				filepath.Join(h.paths.TwinBundle, compiler.ManifestFile) + ": no such file or directory"})
	})

	t.Run("a manifest the compiler never emits", func(t *testing.T) {
		h := verifyHost(t, "three-node", func(m map[string]any) {
			m["links"].([]any)[0].(map[string]any)["b"].(map[string]any)["port"] = "e1-9"
		}, nil)
		out := runVerify(t, h.paths.Root, nil)
		wantOnly(t, out, findings.ExitError, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed,
			Object: "n1:ethernet-1/1|n2:ethernet-1/1", Step: findings.StepObserve,
			Message: "link n1:ethernet-1/1|n2:ethernet-1/1 names n2 port e1-9, which has no cabled mapping row"})
		if out.doc.BundleID != h.staged {
			t.Errorf("bundle_id %q, want the staged bundle's, read before the assertions", out.doc.BundleID)
		}
	})

	t.Run("a package not loaded", func(t *testing.T) {
		h := verifyHost(t, "lossy", nil, nil)
		out := runVerify(t, h.paths.Root, nil)
		wantOnly(t, out, findings.ExitRejected, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleHostPSPMissing,
			Object: "chassisos", Step: findings.StepObserve,
			Message: "support package chassisos (manifest source override), named by c1, c2, is not on this worker"})
	})

	// A package with no conformance block, and its login unset, refused together in one pass.
	t.Run("a package with no conformance block, and its login", func(t *testing.T) {
		h := verifyHost(t, "lossy", nil, nil)
		t.Setenv(lab.EnvPSPDir, repoPath("testdata", "psp", "lossy"))
		out := runVerify(t, h.paths.Root, nil)
		want := findings.List{
			{Severity: findings.Rejection, Rule: findings.RuleVerifyPackageUnreadable, Object: "chassisos", Step: findings.StepObserve,
				Message: "support package chassisos declares no conformance block; fylgja twin verify cannot read its nodes"},
			{Severity: findings.Rejection, Rule: findings.RuleHostProbeLoginUnset, Object: "FYLGJA_CHASSISOS_USERNAME", Step: findings.StepObserve,
				Message: "FYLGJA_CHASSISOS_USERNAME is unset on this worker; support package chassisos names it for its readiness probe login"},
			{Severity: findings.Rejection, Rule: findings.RuleHostProbeLoginUnset, Object: "FYLGJA_CHASSISOS_PASSWORD", Step: findings.StepObserve,
				Message: "FYLGJA_CHASSISOS_PASSWORD is unset on this worker; support package chassisos names it for its readiness probe login"},
		}
		if out.code != findings.ExitRejected || !reflect.DeepEqual(out.doc.Findings, want) {
			t.Errorf("exit %d, findings\n%+v\nwant 1 and\n%+v", out.code, out.doc.Findings, want)
		}
		if out.doc.BundleID != h.staged || out.doc.Verify != nil {
			t.Errorf("bundle_id %q, verify %+v; want the staged id and no block", out.doc.BundleID, out.doc.Verify)
		}
	})

	t.Run("a readiness probe that is not gNMI", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		t.Setenv(lab.EnvPSPDir, overridePackage(t, "nokia_srlinux", "probe: gnmi_get", "probe: netconf_get"))
		out := runVerify(t, h.paths.Root, nil)
		wantOnly(t, out, findings.ExitRejected, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyPackageUnreadable,
			Object: "nokia_srlinux", Step: findings.StepObserve,
			Message: "support package nokia_srlinux's readiness probe is netconf_get; fylgja twin verify reads by gNMI only"})
	})

	// The second package's login is read by the second package's own names (M7's
	// host.probe.login_unset rule), and only the probe's: the push's are never verify's.
	t.Run("the EOS probe login unset on the mixed twin", func(t *testing.T) {
		h := verifyHost(t, "mixed", nil, nil)
		t.Setenv("FYLGJA_EOS_PASSWORD", "")
		out := runVerify(t, h.paths.Root, nil)
		wantOnly(t, out, findings.ExitRejected, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleHostProbeLoginUnset,
			Object: "FYLGJA_EOS_PASSWORD", Step: findings.StepObserve,
			Message: "FYLGJA_EOS_PASSWORD is unset on this worker; support package arista_eos names it for its readiness probe login"})
	})
}

// A conforming twin: ok, exit 0, no finding; each path read once; the text layout and the
// block.
func TestVerifyConformingThreeNode(t *testing.T) {
	h := verifyHost(t, "three-node", nil, nil)
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK || len(out.doc.Findings) != 0 {
		t.Fatalf("exit %d, status %s, findings %+v; want 0, ok, none", out.code, out.doc.Status, out.doc.Findings)
	}
	if want := lines(threeNodeLines(h.staged)...); out.stdout != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, want)
	}
	if out.stderr != "" {
		t.Errorf("stderr:\n%s\nwant nothing: there is no finding", out.stderr)
	}
	if len(out.calls) != 15 || len(slices.Compact(slices.Sorted(slices.Values(out.calls)))) != 15 {
		t.Errorf("reads %v; want each of the 15 paths read once", out.calls)
	}
	v := out.doc.Verify
	if out.doc.BundleID != h.staged || v == nil || v.Twin.BundleID != h.staged || v.Twin.State != wire.StateReady ||
		v.Service != findings.ShowServiceOK || v.Wait != nil || len(v.Nodes) != 3 || len(v.Links) != 3 {
		t.Fatalf("bundle_id %s, block %+v", out.doc.BundleID, v)
	}
	three, unread := 3, 0
	six, none := 6, 0
	if want := (findings.VerifyCounts{
		HostName:    findings.VerifyCount{Held: three, Unread: &unread},
		PortEnabled: findings.VerifyCount{Held: six, Skipped: &none, Unread: &unread},
		Neighbor:    findings.VerifyCount{Held: six, Skipped: &none, Unread: &unread},
		Record:      findings.VerifyCount{Held: three},
	}); !reflect.DeepEqual(v.Counts, want) {
		t.Errorf("counts %+v, want %+v", v.Counts, want)
	}
}

// The mixed twin: each node read over its own package's transport, port and encoding, the
// SR Linux node at :57400 over TLS, the cEOS nodes at :6030 in plaintext, each with its own
// package's login names (M7's mixed twin).
func TestVerifyConformingMixed(t *testing.T) {
	h := verifyHost(t, "mixed", nil, nil)
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if out.code != findings.ExitOK || len(out.doc.Findings) != 0 {
		t.Fatalf("exit %d, findings %+v; want 0 and none", out.code, out.doc.Findings)
	}
	s := short(h.staged)
	want := lines(
		"twin: branch fylgja-fixture (bundle "+s+"), ready; 3 nodes",
		"staged: bundle "+s+"; 15 assertions over 3 nodes, 0 skipped",
		"e1 (172.20.20.2:6030, arista_eos): host name e1; Ethernet1, Ethernet2/1 enabled; neighbours s1 ethernet-1/1, e2 Ethernet1; record: holds "+s,
		"e2 (172.20.20.3:6030, arista_eos): host name e2; Ethernet1, Ethernet3/1/1 enabled; neighbours e1 Ethernet2/1, s1 ethernet-1/2; record: holds "+s,
		"s1 (172.20.20.4:57400, nokia_srlinux): host name s1; ethernet-1/1, ethernet-1/2 enabled; neighbours e1 Ethernet1, e2 Ethernet3/1/1; record: holds "+s,
		"skipped: none",
		"in flight: none",
		"held: 3 host names, 6 ports, 6 link ends, 3 record claims (the record's, not read); failed: none; unread: none",
	)
	if out.stdout != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, want)
	}
	for addr, p := range map[string]struct {
		port     int
		tls      bool
		username string
	}{
		"172.20.20.2:6030":  {6030, false, "FYLGJA_EOS_USERNAME"},
		"172.20.20.3:6030":  {6030, false, "FYLGJA_EOS_USERNAME"},
		"172.20.20.4:57400": {57400, true, "FYLGJA_SRLINUX_USERNAME"},
	} {
		// A package that omits readiness.tls means TLS (verify.ReadinessProbe).
		got, ok := out.probes[addr]
		if tls := got.TLS == nil || *got.TLS; !ok || got.Port != p.port || tls != p.tls || got.UsernameEnv != p.username {
			t.Errorf("%s read over %+v; want port %d, TLS %v, login %s", addr, got, p.port, p.tls, p.username)
		}
	}
	for _, n := range out.doc.Verify.Nodes {
		if n.Addr == nil || *n.Addr != h.healthy(t).nodes[n.Node].addr || !n.Read {
			t.Errorf("node %+v, want read at its own package's port", n)
		}
	}
}

// A port read disable, and the two ends of its link seeing nothing: exactly three findings,
// nonconforming, exit 5 (in tier 1).
func TestVerifyDisabledPortIsNonconforming(t *testing.T) {
	h := verifyHost(t, "three-node", nil, nil)
	out := runVerify(t, h.paths.Root, func() *fakeNodes {
		f := h.healthy(t)
		f.enabled("n1", "ethernet-1/2", "disable")
		f.neighbours("n1", "ethernet-1/2")
		f.set("n3", neighbourPath("nokia_srlinux", "ethernet-1/2"), verify.Answer{})
		return f
	})
	want := findings.List{
		{Severity: findings.Rejection, Rule: findings.RuleVerifyPortEnabled, Object: "n1:ethernet-1/2", Step: findings.StepObserve,
			Message: `node n1 (172.20.20.2:57400): port ethernet-1/2 (node name ethernet-1/2) reads "disable" at ` +
				`/interface[name=ethernet-1/2]/admin-state; intent enables it (expected "enable")`},
		{Severity: findings.Rejection, Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/2", Step: findings.StepObserve,
			Message: "node n1 (172.20.20.2:57400): port ethernet-1/2 sees no neighbour at /system/lldp/interface[name=ethernet-1/2]/neighbor; " +
				"link n1:ethernet-1/2|n3:ethernet-1/2 names n3 ethernet-1/2 at its far end"},
		{Severity: findings.Rejection, Rule: findings.RuleVerifyNeighbor, Object: "n3:ethernet-1/2", Step: findings.StepObserve,
			Message: "node n3 (172.20.20.4:57400): port ethernet-1/2 sees no neighbour at /system/lldp/interface[name=ethernet-1/2]/neighbor; " +
				"link n1:ethernet-1/2|n3:ethernet-1/2 names n1 ethernet-1/2 at its far end"},
	}
	if out.code != findings.ExitNonconforming || out.doc.Status != findings.StatusNonconforming || !reflect.DeepEqual(out.doc.Findings, want) {
		t.Fatalf("exit %d, status %s, findings\n%+v\nwant 5, nonconforming and\n%+v", out.code, out.doc.Status, out.doc.Findings, want)
	}
	s := short(h.staged)
	for _, line := range []string{
		`n1 (172.20.20.2:57400, nokia_srlinux): host name n1; ethernet-1/1 enabled; ethernet-1/2 reads "disable" (verify.port.enabled); ` +
			"neighbour n2 ethernet-1/1; ethernet-1/2 sees no neighbour (verify.neighbor); record: holds " + s,
		"n3 (172.20.20.4:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbour n2 ethernet-1/2; " +
			"ethernet-1/2 sees no neighbour (verify.neighbor); record: holds " + s,
		"held: 3 host names, 5 ports, 4 link ends, 3 record claims (the record's, not read); failed: 1 port, 2 link ends; unread: none",
	} {
		if !strings.Contains(out.stdout, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
	}
	if !strings.Contains(out.stderr, "3 finding(s): 3 rejection, 0 warning, 0 info") {
		t.Errorf("stderr does not count three findings:\n%s", out.stderr)
	}
}

// A diverged twin is verified against its staged bundle, the target: its first line and
// the block name the divergence, every read holds, and the record's claims that a node
// holds the previous bundle, or none, are findings labelled the record's: nonconforming,
// exit 5.
func TestVerifyDivergedRecord(t *testing.T) {
	const (
		prev  = "348fd9340000000000000000000000000000000000000000000000000000abcd"
		runID = "01a3c0de-0000-7000-8000-000000000003"
	)
	h := verifyHost(t, "three-node", nil, nil)
	rec, err := lab.ReadRecord(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	phase := findings.StepPush
	rec.BundleID = prev
	rec.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 1, AtSource: "given"}
	rec.State = wire.StateDiverged
	rec.Step = &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
		From: wire.StepSide{Waypoint: rec.Waypoint, BundleID: prev},
		To:   wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 2, AtSource: "given"}, BundleID: h.staged},
		Run:  wire.RunRef{WorkflowID: wire.StepWorkflowID, RunID: runID}}
	p := prev
	rec.Nodes[0].Holds = &p
	rec.Nodes[1].Holds = nil
	writeTwin(t, h.paths, rec)

	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	want := findings.List{
		{Severity: findings.Rejection, Rule: findings.RuleVerifyRecordHolds, Object: "n1", Step: findings.StepObserve,
			Message: "the record says node n1 holds bundle 348fd934…, not the staged bundle " + short(h.staged) +
				"; this is the record's claim (nodes[].holds), not a read"},
		{Severity: findings.Rejection, Rule: findings.RuleVerifyRecordHolds, Object: "n2", Step: findings.StepObserve,
			Message: "the record says node n2 holds no bundle (null): containerlab restarted, recreated or created it and no push landed; " +
				"the staged bundle is " + short(h.staged) + "; this is the record's claim, not a read"},
	}
	if out.code != findings.ExitNonconforming || !reflect.DeepEqual(out.doc.Findings, want) {
		t.Fatalf("exit %d, findings\n%+v\nwant 5 and\n%+v", out.code, out.doc.Findings, want)
	}
	for _, line := range []string{
		"twin: waypoint demo/1 (bundle 348fd934…), diverged towards demo/2 (bundle " + short(h.staged) +
			") at phase push by run fylgja-step " + runID + "; 3 nodes",
		"n1 (172.20.20.2:57400, nokia_srlinux): host name n1; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/1, n3 ethernet-1/2; " +
			"record: holds 348fd934…, not the staged bundle (verify.record.holds)",
		"n2 (172.20.20.3:57400, nokia_srlinux): host name n2; ethernet-1/1, ethernet-1/2 enabled; neighbours n1 ethernet-1/1, n3 ethernet-1/1; " +
			"record: holds no bundle (verify.record.holds)",
		"held: 3 host names, 6 ports, 6 link ends, 1 record claim (the record's, not read); failed: 2 record claims; unread: none",
	} {
		if !strings.Contains(out.stdout, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
	}
	tw := out.doc.Verify.Twin
	if tw.State != wire.StateDiverged || tw.BundleID != h.staged || tw.Diverged == nil || tw.Diverged.Phase != findings.StepPush ||
		tw.Diverged.Run.RunID != runID || tw.Diverged.Towards.BundleID != h.staged || tw.Diverged.Towards.Waypoint.Sequence != 2 {
		t.Errorf("twin %+v, diverged %+v; want the divergence named", tw, tw.Diverged)
	}
}

// A node that cannot be read: error, exit 2, its operation.failed the only finding, and the
// other nodes' assertions kept in the block.
func TestVerifyUnreadNodeIsAnError(t *testing.T) {
	refused := errors.New(`gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unavailable msg="connection refused"`)
	h := verifyHost(t, "three-node", nil, nil)
	out := runVerify(t, h.paths.Root, func() *fakeNodes {
		f := h.healthy(t)
		f.unreachableNode("n2", refused)
		return f
	})
	want := findings.List{{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: "n2", Step: findings.StepObserve,
		Message: "node n2 (172.20.20.3:57400) could not be read: " + refused.Error() + " (at /system/name/host-name)"}}
	if out.code != findings.ExitError || out.doc.Status != findings.StatusError || !reflect.DeepEqual(out.doc.Findings, want) {
		t.Fatalf("exit %d, status %s, findings\n%+v\nwant 2, error and\n%+v", out.code, out.doc.Status, out.doc.Findings, want)
	}
	for _, line := range []string{
		"n2 (172.20.20.3:57400, nokia_srlinux): not read: " + refused.Error() + " (operation.failed)",
		"held: 2 host names, 4 ports, 4 link ends, 3 record claims (the record's, not read); failed: none; unread: n2",
	} {
		if !strings.Contains(out.stdout, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
	}
	v := out.doc.Verify
	if v == nil || len(v.Nodes) != 3 {
		t.Fatalf("block %+v, want every node in it", v)
	}
	for _, n := range v.Nodes {
		if read := n.Node != "n2"; n.Read != read || (n.Node != "n2" && n.HostName.Outcome != verify.Held) {
			t.Errorf("node %+v: want n1 and n3 read and held, n2 unread", n)
		}
	}
}

// --wait reads again until the twin conforms, or the budget expires; what the last read
// says ends the command, on a fake clock.
func TestVerifyWait(t *testing.T) {
	refused := errors.New("gNMI dial 172.20.20.3:57400: connection refused")
	for _, c := range []struct {
		name  string
		args  []string
		nodes func(t *testing.T, h *verifyTwinHost) *fakeNodes
		exit  int
		last  string
		wait  findings.VerifyWait
	}{
		{"bare, at once", []string{"--wait"}, func(t *testing.T, h *verifyTwinHost) *fakeNodes { return h.healthy(t) },
			findings.ExitOK, "settled after 0.0s (1 read; budget 2m0s)", findings.VerifyWait{BudgetS: 120, Reads: 1, Outcome: verify.WaitSettled}},
		{"settling late", []string{"--wait"}, func(t *testing.T, h *verifyTwinHost) *fakeNodes {
			f := h.healthy(t)
			path := neighbourPath("nokia_srlinux", "ethernet-1/1")
			f.set("n1", path, verify.Answer{}, verify.Answer{}, f.neighbourAnswer("n1", "ethernet-1/1", [2]string{"n2", "ethernet-1/1"}))
			return f
		}, findings.ExitOK, "settled after 2.0s (3 reads; budget 2m0s)", findings.VerifyWait{BudgetS: 120, Reads: 3, Outcome: verify.WaitSettled, AfterS: 2}},
		{"a budget of 0 reads once", []string{"--wait=0"}, func(t *testing.T, h *verifyTwinHost) *fakeNodes { return h.healthy(t) },
			findings.ExitOK, "settled after 0.0s (1 read; budget 0s)", findings.VerifyWait{BudgetS: 0, Reads: 1, Outcome: verify.WaitSettled}},
		{"expiring with a node unread", []string{"--wait=30s"}, func(t *testing.T, h *verifyTwinHost) *fakeNodes {
			f := h.healthy(t)
			f.unreachableNode("n2", refused)
			return f
		}, findings.ExitError, "budget 30s expired after 30.0s (31 reads): n2 still unread",
			findings.VerifyWait{BudgetS: 30, Reads: 31, Outcome: verify.WaitExpired, AfterS: 30}},
		{"expiring with every node read", []string{"--wait=3s"}, func(t *testing.T, h *verifyTwinHost) *fakeNodes {
			f := h.healthy(t)
			f.enabled("n1", "ethernet-1/2", "disable")
			return f
		}, findings.ExitNonconforming, "budget 3s expired after 3.0s (4 reads): 1 assertion still failing",
			findings.VerifyWait{BudgetS: 3, Reads: 4, Outcome: verify.WaitExpired, AfterS: 3}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			out := runVerify(t, h.paths.Root, func() *fakeNodes { return c.nodes(t, h) }, c.args...)
			if out.code != c.exit {
				t.Errorf("exit %d, want %d; findings %+v", out.code, c.exit, out.doc.Findings)
			}
			if got := strings.Split(strings.TrimSuffix(out.stdout, "\n"), "\n"); got[len(got)-1] != c.last {
				t.Errorf("last line %q, want %q\n%s", got[len(got)-1], c.last, out.stdout)
			}
			if w := out.doc.Verify.Wait; w == nil || *w != c.wait {
				t.Errorf("wait %+v, want %+v", w, c.wait)
			}
		})
	}
}

// A port intent disables is skipped, with both ends of its link, and named with why; they
// are never read, and the twin conforms.
func TestVerifySkipsWhatIntentDisables(t *testing.T) {
	h := verifyHost(t, "three-node", disableRow("n1", "ethernet-1/2"), nil)
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if out.code != findings.ExitOK || len(out.doc.Findings) != 0 {
		t.Fatalf("exit %d, findings %+v; want 0 and none", out.code, out.doc.Findings)
	}
	s := short(h.staged)
	for _, line := range []string{
		"staged: bundle " + s + "; 15 assertions over 3 nodes, 3 skipped",
		"n1 (172.20.20.2:57400, nokia_srlinux): host name n1; ethernet-1/1 enabled; neighbour n2 ethernet-1/1; record: holds " + s,
		"n3 (172.20.20.4:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbour n2 ethernet-1/2; record: holds " + s,
		"skipped: n1:ethernet-1/2 (intent disables it); link n1:ethernet-1/2|n3:ethernet-1/2 at both ends (intent disables n1:ethernet-1/2)",
		"held: 3 host names, 5 ports, 4 link ends, 3 record claims (the record's, not read); failed: none; unread: none",
	} {
		if !strings.Contains(out.stdout, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
	}
	for _, skipped := range []string{
		"172.20.20.2:57400 " + enabledPath("nokia_srlinux", "ethernet-1/2"),
		"172.20.20.2:57400 " + neighbourPath("nokia_srlinux", "ethernet-1/2"),
		"172.20.20.4:57400 " + neighbourPath("nokia_srlinux", "ethernet-1/2"),
	} {
		if slices.Contains(out.calls, skipped) {
			t.Errorf("a skipped assertion was read: %s", skipped)
		}
	}
	if len(out.calls) != 12 {
		t.Errorf("reads %v, want the 12 asserted paths", out.calls)
	}
	c := out.doc.Verify.Counts
	if *c.PortEnabled.Skipped != 1 || *c.Neighbor.Skipped != 2 || len(out.doc.Verify.Skipped) != 3 {
		t.Errorf("counts %+v, skipped %+v; want one port and two link ends", c, out.doc.Verify.Skipped)
	}
}

// A staged bundle written before bundle 4 reads, every row enabled, every port
// asserted.
func TestVerifyReadsABundle3Manifest(t *testing.T) {
	h := verifyHost(t, "three-node", asBundle3, nil)
	if h.m.BundleVersion != "3" {
		t.Fatalf("the staged manifest is %q, want a 3 one", h.m.BundleVersion)
	}
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if out.code != findings.ExitOK || len(out.doc.Findings) != 0 {
		t.Fatalf("exit %d, findings %+v; want 0 and none", out.code, out.doc.Findings)
	}
	if want := lines(threeNodeLines(h.staged)...); out.stdout != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, want)
	}
}

// The workflow service is asked best-effort: unreachable, it is a warning and the read goes
// on, exit unchanged; answering, a run in flight is named.
func TestVerifyRunsInFlight(t *testing.T) {
	t.Run("the service unreachable", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(context.Context) (provision.Service, error) { return nil, errors.New("connection refused") }
		out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
		want := findings.List{{Severity: findings.Warning, Rule: findings.RuleShowServiceUnreachable, Object: provision.DefaultAddress,
			Message: "workflow service unreachable at " + provision.DefaultAddress + " (connection refused); whether a run is in flight is unknown"}}
		if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK || !reflect.DeepEqual(out.doc.Findings, want) {
			t.Errorf("exit %d, findings %+v; want 0 and the warning alone", out.code, out.doc.Findings)
		}
		if l := threeNodeLines(h.staged); !strings.Contains(out.stdout, "\nin flight: unknown\n") ||
			!strings.HasSuffix(out.stdout, l[len(l)-1]+"\n") {
			t.Errorf("stdout:\n%s\nwant in flight: unknown", out.stdout)
		}
		if out.doc.Verify.Service != findings.ShowServiceUnreachable {
			t.Errorf("service %q, want unreachable", out.doc.Verify.Service)
		}
	})
	t.Run("a step in flight", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		h.svc.inFlight = []provision.RunInFlight{{WorkflowID: wire.StepWorkflowID, RunID: stepRunID, Step: findings.StepReadiness}}
		out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
		if out.code != findings.ExitOK {
			t.Errorf("exit %d, want 0", out.code)
		}
		if line := "in flight: run fylgja-step " + stepRunID + " at step readiness"; !strings.Contains(out.stdout, "\n"+line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
		if f := out.doc.Verify.InFlight; len(f) != 1 || f[0].RunID != stepRunID || f[0].Step != findings.StepReadiness {
			t.Errorf("in_flight %+v", f)
		}
	})
}

// Two reads of a conforming twin change nothing, and say the same but for when they
// read.
func TestVerifyTwiceChangesNothing(t *testing.T) {
	h := verifyHost(t, "mixed", nil, nil)
	before := treeDigest(t, h.paths.Root)
	first := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	second := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if after := treeDigest(t, h.paths.Root); !slices.Equal(before, after) {
		t.Errorf("two reads changed the state root:\n  %v\nto\n  %v", before, after)
	}
	if first.stdout != second.stdout || first.code != second.code {
		t.Errorf("the two reads print\n%s\nand\n%s", first.stdout, second.stdout)
	}
	a, b := *first.doc, *second.doc
	va, vb := *a.Verify, *b.Verify
	va.ReadAt, vb.ReadAt = "", ""
	a.Verify, b.Verify = &va, &vb
	if !reflect.DeepEqual(a, b) {
		t.Errorf("the two documents differ beyond read_at:\n%+v\n%+v", a, b)
	}
}

// --wait looks up again a node containerlab did not report: absent from the first
// inspection and present from the second, it is read and the twin settles on the second
// read; one read without --wait inspects once, and a wait whose every node was dialled never
// asks again.
func TestVerifyWaitLooksUpAnUnreportedNodeAgain(t *testing.T) {
	for _, c := range []struct {
		name        string
		args        []string
		inspections int
		exit        int
		last        string
	}{
		{"--wait", []string{"--wait"}, 2, findings.ExitOK, "settled after 1.0s (2 reads; budget 2m0s)"},
		{"one read", nil, 1, findings.ExitError,
			"held: 2 host names, 4 ports, 4 link ends, 3 record claims (the record's, not read); failed: none; unread: n3"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			clab := useInspections(t, goldenInspect(t, "three-node", withoutContainer("n3")), goldenInspect(t, "three-node", nil))
			var counted []int
			out := runVerify(t, h.paths.Root, func() *fakeNodes {
				counted = append(counted, clab.reset())
				return h.healthy(t)
			}, c.args...)
			counted = append(counted, clab.reset())
			if out.code != c.exit {
				t.Errorf("exit %d, want %d; findings %+v", out.code, c.exit, out.doc.Findings)
			}
			if got := strings.Split(strings.TrimSuffix(out.stdout, "\n"), "\n"); got[len(got)-1] != c.last {
				t.Errorf("last line %q, want %q\n%s", got[len(got)-1], c.last, out.stdout)
			}
			// The count before the first run is zero; each run's is its own.
			if want := []int{0, c.inspections, c.inspections}; !slices.Equal(counted, want) {
				t.Errorf("inspections per run %v, want %v", counted[1:], want[1:])
			}
		})
	}
	t.Run("every node dialled", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		clab := useInspections(t, goldenInspect(t, "three-node", nil))
		out := runVerify(t, h.paths.Root, func() *fakeNodes {
			clab.reset()
			f := h.healthy(t)
			f.enabled("n1", "ethernet-1/2", "disable")
			return f
		}, "--wait=3s")
		if n := clab.reset(); out.code != findings.ExitNonconforming || n != 1 {
			t.Errorf("exit %d after %d inspections; want 5 after the host's one", out.code, n)
		}
	})
}

// A node the staged bundle names that the record does not, which containerlab reports, is
// read at containerlab's address; its claim fails as the record's, and the twin is
// nonconforming.
func TestVerifyNodeTheRecordDoesNotName(t *testing.T) {
	h := verifyHost(t, "three-node", nil, func(rec *wire.TwinRecord) {
		rec.Nodes = slices.DeleteFunc(rec.Nodes, func(n wire.TwinNode) bool { return n.Name == "n3" })
	})
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	want := findings.List{{Severity: findings.Rejection, Rule: findings.RuleVerifyRecordHolds, Object: "n3", Step: findings.StepObserve,
		Message: "the record does not name node n3, which the staged bundle names; this is the record's claim, not a read"}}
	if out.code != findings.ExitNonconforming || out.doc.Status != findings.StatusNonconforming || !reflect.DeepEqual(out.doc.Findings, want) {
		t.Fatalf("exit %d, status %s, findings\n%+v\nwant 5, nonconforming and\n%+v", out.code, out.doc.Status, out.doc.Findings, want)
	}
	s := short(h.staged)
	for _, line := range []string{
		"twin: branch fylgja-fixture (bundle " + s + "), ready; 2 nodes",
		"n3 (172.20.20.4:57400, nokia_srlinux): host name n3; ethernet-1/1, ethernet-1/2 enabled; neighbours n2 ethernet-1/2, n1 ethernet-1/2; " +
			"record: does not name it (verify.record.holds)",
		"held: 3 host names, 6 ports, 6 link ends, 2 record claims (the record's, not read); failed: 1 record claim; unread: none",
	} {
		if !strings.Contains(out.stdout, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
		}
	}
	if len(out.calls) != 15 {
		t.Errorf("reads %v, want every node's 15 paths, n3's at containerlab's address", out.calls)
	}
	if r := out.doc.Verify.Record; len(r) != 3 || r[2].Node != "n3" || r[2].Holds != nil || r[2].Outcome != verify.Failed {
		t.Errorf("record claims %+v, want n3's failed, holding nothing", r)
	}
}

// A part of a second counts as a whole one, as twin step --wait counts it: the wait, the
// block's budget_s and the last line agree, and --wait=0 still reads once.
func TestVerifyWaitRoundsItsBudgetUp(t *testing.T) {
	for _, c := range []struct {
		name  string
		arg   string
		fails bool
		last  string
		wait  findings.VerifyWait
	}{
		{"half a second, settled", "--wait=500ms", false, "settled after 0.0s (1 read; budget 1s)",
			findings.VerifyWait{BudgetS: 1, Reads: 1, Outcome: verify.WaitSettled}},
		{"half a second, expired", "--wait=500ms", true, "budget 1s expired after 1.0s (2 reads): 1 assertion still failing",
			findings.VerifyWait{BudgetS: 1, Reads: 2, Outcome: verify.WaitExpired, AfterS: 1}},
		{"a second and a half", "--wait=1500ms", true, "budget 2s expired after 2.0s (3 reads): 1 assertion still failing",
			findings.VerifyWait{BudgetS: 2, Reads: 3, Outcome: verify.WaitExpired, AfterS: 2}},
		{"zero", "--wait=0", true, "budget 0s expired after 0.0s (1 read): 1 assertion still failing",
			findings.VerifyWait{BudgetS: 0, Reads: 1, Outcome: verify.WaitExpired}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			out := runVerify(t, h.paths.Root, func() *fakeNodes {
				f := h.healthy(t)
				if c.fails {
					f.enabled("n1", "ethernet-1/2", "disable")
				}
				return f
			}, c.arg)
			if got := strings.Split(strings.TrimSuffix(out.stdout, "\n"), "\n"); got[len(got)-1] != c.last {
				t.Errorf("last line %q, want %q", got[len(got)-1], c.last)
			}
			if w := out.doc.Verify.Wait; w == nil || *w != c.wait {
				t.Errorf("wait %+v, want %+v", w, c.wait)
			}
		})
	}
}

// Nodes containerlab reports that the bundle does not name are one line and the block's
// extra_nodes; nothing is asserted of them, and the twin still conforms.
func TestVerifyNamesNodesNotInTheBundle(t *testing.T) {
	h := verifyHost(t, "three-node", nil, nil)
	useInspect(t, goldenInspect(t, "three-node", func(cs []map[string]any) []map[string]any {
		x1 := maps.Clone(cs[0])
		x1["name"], x1["ipv4_address"] = "clab-fylgja-x1", "172.20.20.9/24"
		return append(cs, x1)
	}))
	out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
	if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK || len(out.doc.Findings) != 0 {
		t.Fatalf("exit %d, status %s, findings %+v; want 0, ok, none", out.code, out.doc.Status, out.doc.Findings)
	}
	lines := threeNodeLines(h.staged)
	want := append(append(slices.Clone(lines[:len(lines)-1]), "not in the bundle: x1"), lines[len(lines)-1])
	if got := lines2(out.stdout); !slices.Equal(got, want) {
		t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, strings.Join(want, "\n"))
	}
	if v := out.doc.Verify; !slices.Equal(v.ExtraNodes, []string{"x1"}) || len(v.Nodes) != 3 {
		t.Errorf("extra_nodes %v, nodes %d; want x1 alone, and three nodes asserted", v.ExtraNodes, len(v.Nodes))
	}
	for _, c := range out.calls {
		if strings.HasPrefix(c, "172.20.20.9:") {
			t.Errorf("x1 was read: %s", c)
		}
	}
}

// lines2 is text output split into its lines.
func lines2(s string) []string { return strings.Split(strings.TrimSuffix(s, "\n"), "\n") }

// The twin: line names the record's reference in each form contracts/cli.md gives it: a
// branch twin pinned at T keeps its at in the reference; a ready waypoint twin, stepped or
// not, says pinned at T after its state, never diverged; a bundle twin names its manifest's
// branch and at, as a branch twin's.
func TestVerifyTwinLine(t *testing.T) {
	const at = "2026-09-28T15:20:44.000000+00:00"
	for _, c := range []struct {
		name   string
		change func(*wire.TwinRecord)
		line   string // %s is the bundle
	}{
		{"a branch twin pinned at T", func(rec *wire.TwinRecord) { rec.Provenance.At = at },
			"twin: branch fylgja-fixture at " + at + " (bundle %s), ready; 3 nodes"},
		{"a ready waypoint twin", func(rec *wire.TwinRecord) {
			rec.Provenance.At = at
			rec.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 2, AtSource: "given"}
		}, "twin: waypoint demo/2 (bundle %s), ready, pinned at " + at + "; 3 nodes"},
		{"a waypoint twin that has stepped and is ready", func(rec *wire.TwinRecord) {
			rec.Provenance.At = at
			rec.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 2, AtSource: "given"}
			rec.Step = &wire.StepRecord{Outcome: wire.StepStepped,
				From: wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 1, AtSource: "given"},
					BundleID: "348fd9340000000000000000000000000000000000000000000000000000abcd"},
				To:  wire.StepSide{Waypoint: rec.Waypoint, BundleID: rec.BundleID, At: at},
				Run: wire.RunRef{WorkflowID: wire.StepWorkflowID, RunID: stepRunID}}
		}, "twin: waypoint demo/2 (bundle %s), ready, pinned at " + at + "; 3 nodes"},
		{"a bundle twin", func(rec *wire.TwinRecord) {
			rec.Source, rec.ObservedAt, rec.Provenance.At = wire.SourceBundle, nil, "2026-09-08T12:00:00Z"
		}, "twin: branch fylgja-fixture at 2026-09-08T12:00:00Z (bundle %s), ready; 3 nodes"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, c.change)
			out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
			if out.code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", out.code, out.doc.Findings)
			}
			if got, want := lines2(out.stdout)[0], fmt.Sprintf(c.line, short(h.staged)); got != want {
				t.Errorf("first line %q\nwant %q", got, want)
			}
		})
	}
}

// Each failed form a node's line names in place of its held one, word for word as
// contracts/cli.md quotes it, and the head of a node with no address (contracts/cli.md
// "The read").
func TestVerifyNodeLineForms(t *testing.T) {
	srl := func(port string, neighbour any) verify.Answer {
		return at("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]", map[string]any{"neighbor": neighbour})
	}
	for _, c := range []struct {
		name    string
		nodes   func(f *fakeNodes)
		inspect func([]map[string]any) []map[string]any
		record  func(*wire.TwinRecord)
		line    string // %s is the staged bundle
	}{
		{"a host name another", func(f *fakeNodes) {
			f.set("s1", hostNamePath("nokia_srlinux"), at("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "s2"))
		}, nil, nil, `s1 (172.20.20.4:57400, nokia_srlinux): host name "s2" (verify.host_name); ethernet-1/1, ethernet-1/2 enabled; ` +
			"neighbours e1 Ethernet1, e2 Ethernet3/1/1; record: holds %s"},
		{"a host name absent", func(f *fakeNodes) { f.set("e1", hostNamePath("arista_eos"), verify.Answer{}) }, nil, nil,
			"e1 (172.20.20.2:6030, arista_eos): host name reads nothing (verify.host_name); Ethernet1, Ethernet2/1 enabled; " +
				"neighbours s1 ethernet-1/1, e2 Ethernet1; record: holds %s"},
		{"a port absent", func(f *fakeNodes) { f.set("s1", enabledPath("nokia_srlinux", "ethernet-1/2"), verify.Answer{}) }, nil, nil,
			"s1 (172.20.20.4:57400, nokia_srlinux): host name s1; ethernet-1/1 enabled; ethernet-1/2 reads nothing (verify.port.enabled); " +
				"neighbours e1 Ethernet1, e2 Ethernet3/1/1; record: holds %s"},
		{"a neighbour list that is not a list", func(f *fakeNodes) {
			f.set("s1", neighbourPath("nokia_srlinux", "ethernet-1/1"), srl("ethernet-1/1", map[string]any{"x": 1}))
		}, nil, nil, "s1 (172.20.20.4:57400, nokia_srlinux): host name s1; ethernet-1/1, ethernet-1/2 enabled; neighbour e2 Ethernet3/1/1; " +
			`ethernet-1/1 reads {"x":1}, not a list (verify.neighbor); record: holds %s`},
		{"another neighbour", func(f *fakeNodes) { f.neighbours("s1", "ethernet-1/2", [2]string{"e1", "Ethernet4"}) }, nil, nil,
			"s1 (172.20.20.4:57400, nokia_srlinux): host name s1; ethernet-1/1, ethernet-1/2 enabled; neighbour e1 Ethernet1; " +
				"ethernet-1/2 sees e1 Ethernet4 (verify.neighbor); record: holds %s"},
		{"two neighbours", func(f *fakeNodes) {
			f.neighbours("s1", "ethernet-1/2", [2]string{"e2", "Ethernet3/1/1"}, [2]string{"e1", "Ethernet4"})
		}, nil, nil, "s1 (172.20.20.4:57400, nokia_srlinux): host name s1; ethernet-1/1, ethernet-1/2 enabled; neighbour e1 Ethernet1; " +
			"ethernet-1/2 sees 2 entries: e2 Ethernet3/1/1, e1 Ethernet4 (verify.neighbor); record: holds %s"},
		{"a node containerlab does not report", nil, withoutContainer("s1"), nil,
			"s1 (no address, nokia_srlinux): not read: containerlab does not report node s1, which the staged bundle names; " +
				"nothing to read (operation.failed)"},
		{"a node with no address", nil, func(cs []map[string]any) []map[string]any {
			for _, c := range cs {
				if c["name"] == "clab-fylgja-s1" {
					c["ipv4_address"] = ""
				}
			}
			return cs
		}, func(rec *wire.TwinRecord) {
			for i := range rec.Nodes {
				if rec.Nodes[i].Name == "s1" {
					rec.Nodes[i].MgmtIPv4 = ""
				}
			}
		}, "s1 (no address, nokia_srlinux): not read: node s1 has no address in the record or from containerlab (operation.failed)"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := verifyHost(t, "mixed", nil, c.record)
			if c.inspect != nil {
				useInspect(t, goldenInspect(t, "mixed", c.inspect))
			}
			out := runVerify(t, h.paths.Root, func() *fakeNodes {
				f := h.healthy(t)
				if c.nodes != nil {
					c.nodes(f)
				}
				return f
			})
			line := c.line
			if strings.Contains(line, "%s") {
				line = fmt.Sprintf(line, short(h.staged))
			}
			if !slices.Contains(lines2(out.stdout), line) {
				t.Errorf("stdout does not say\n%s\n%s", line, out.stdout)
			}
		})
	}
}

// --wait's two edges: with two refusal shapes at once, the one checked first is named, and
// a bare --wait names the first word it left behind; and the expiry line counts an absent
// assertion beside a failed one (contracts/cli.md).
func TestVerifyWaitEdges(t *testing.T) {
	for _, c := range []struct {
		args    []string
		message string
	}{
		{[]string{"--wait=banana", "x"}, `--wait=banana is not a duration: time: invalid duration "banana"`},
		{[]string{"--wait", "x", "y"}, `--wait takes its value as --wait=<duration>; "x" was given as an argument`},
	} {
		t.Run(strings.Join(c.args, " "), func(t *testing.T) {
			h := verifyHost(t, "three-node", nil, nil)
			useService(t, nil)
			out := runVerify(t, h.paths.Root, nil, c.args...)
			wantOnly(t, out, findings.ExitError, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyWaitInvalid,
				Object: "--wait", Message: c.message, Step: findings.StepStart})
		})
	}
	t.Run("an absent assertion beside a failed one", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		out := runVerify(t, h.paths.Root, func() *fakeNodes {
			f := h.healthy(t)
			f.enabled("n1", "ethernet-1/2", "disable")
			f.neighbours("n1", "ethernet-1/2")
			return f
		}, "--wait=3s")
		if last := lines2(out.stdout)[len(lines2(out.stdout))-1]; out.code != findings.ExitNonconforming ||
			last != "budget 3s expired after 3.0s (4 reads): 2 assertions still failing" {
			t.Errorf("exit %d, last line %q; want 5 and 2 assertions still failing", out.code, last)
		}
	})
}
