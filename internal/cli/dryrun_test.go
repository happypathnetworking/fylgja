package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// fakeClab answers the host's two tools with the output the real ones printed and
// records what it was asked. A docker call is answered from images, the
// references the host is pretending to hold; every other call gets stdout.
type fakeClab struct {
	stdout []byte
	images map[string]bool
	calls  [][]string
}

func (f *fakeClab) Run(_ context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	f.calls = append(f.calls, args)
	if args[0] == "docker" {
		ref := args[len(args)-1]
		if f.images[ref] {
			return []byte("sha256:58c3600aacc0c1bd385817e8028fb12f2abb850136ccd9791cec846da82633d4\n"), nil, 0, nil
		}
		return nil, []byte("Error response from daemon: No such image: " + ref + "\n"), 1, nil
	}
	return f.stdout, nil, 0, nil
}

// useClab makes the dry run's containerlab answer with a recording from internal/lab.
func useClab(t *testing.T, recording string) *fakeClab {
	t.Helper()
	b, err := os.ReadFile(repoPath("internal", "lab", "testdata", recording))
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeClab{stdout: b}
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	dryRunRunner = f
	return f
}

// dryRunEnv is the CLI's environment as an operator sets it: the probe login exported, no
// host budget.
func dryRunEnv(t *testing.T) {
	t.Helper()
	t.Setenv("FYLGJA_SRLINUX_USERNAME", "admin")
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", "not-the-real-one")
	t.Setenv(lab.EnvHostMemoryMB, "")
}

var inspectAll = []string{"clab", "inspect", "--all", "--format", "json"}

// imageInspect is the one command presence is read from.
func imageInspect(ref string) []string {
	return []string{"docker", "image", "inspect", "--format", "{{.Id}}", ref}
}

// mixedDryRunEnv adds the EOS login to the environment, as a mixed bundle's host check
// needs both packages' variables set.
func mixedDryRunEnv(t *testing.T) {
	t.Helper()
	dryRunEnv(t)
	t.Setenv("FYLGJA_EOS_USERNAME", "admin")
	t.Setenv("FYLGJA_EOS_PASSWORD", "not-the-real-one")
}

// An imported image the host does not hold refuses the dry run exactly as the run would,
// through the same presence call, and nothing is pulled.
func TestProvisionDryRunRefusesAnAbsentImage(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	mixedDryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	dir := copyGoldenBundleOf(t, "mixed", "b")

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitRejected || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused {
		t.Fatalf("exit %d, document %+v; want 1 and verdict refused", code, doc)
	}
	want := "image ceos:4.32.0.2F is not on this host: support package arista_eos (nodes e1, e2) declares it " +
		"account_gated, obtained from the vendor with an account and imported by hand under exactly that reference, " +
		"never pulled; a reference held under another tag is absent; docs/development.md says how to import it"
	var got []string
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleHostImageAbsent {
			got = append(got, f.Message)
			if f.Severity != findings.Rejection || f.Step != findings.StepHostCheck || f.Object != "ceos:4.32.0.2F" {
				t.Errorf("finding = %+v, want a host_check rejection on the reference", f)
			}
		}
	}
	if len(got) != 1 || got[0] != want {
		t.Errorf("%s findings = %q, want exactly one:\n  %q", findings.RuleHostImageAbsent, got, want)
	}
	// The verdict's own list names it, as it names every other host-check refusal.
	if line := "verdict: refused (" + findings.RuleHostImageAbsent + ")"; !strings.Contains(out, line+"\n") {
		t.Errorf("stdout does not say %q:\n%s", line, out)
	}
	validateM6Document(t, doc)

	// One presence call, for the one reference two nodes share; s1's registry image is
	// never asked after, and nothing pulls or tags.
	wantCalls := [][]string{inspectAll, imageInspect("ceos:4.32.0.2F")}
	if len(clab.calls) != 2 || !slices.Equal(clab.calls[0], wantCalls[0]) || !slices.Equal(clab.calls[1], wantCalls[1]) {
		t.Errorf("the host's tools were asked %v, want exactly %v", clab.calls, wantCalls)
	}
	// A refused dry run still files the bundle it read, and touches nothing on the host.
	if _, err := os.Stat(paths.Twin); !os.IsNotExist(err) {
		t.Errorf("a refused dry run left a twin directory at %s (%v)", paths.Twin, err)
	}
}

// The same bundle clears when the host holds the reference: the presence call is made and
// answered, and no image finding is raised.
func TestProvisionDryRunClearsWhenTheImageIsHeld(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	mixedDryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	clab.images = map[string]bool{"ceos:4.32.0.2F": true}
	dir := copyGoldenBundleOf(t, "mixed", "b")

	code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{dryRun: true}, dir))
	if code != findings.ExitOK || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictClear {
		t.Fatalf("exit %d, document %+v; want 0 and verdict clear", code, doc)
	}
	if carriesRule(doc.Findings, findings.RuleHostImageAbsent) {
		t.Errorf("findings %+v refuse a host that holds the image", doc.Findings)
	}
	if len(clab.calls) != 2 || !slices.Equal(clab.calls[1], imageInspect("ceos:4.32.0.2F")) {
		t.Errorf("the host's tools were asked %v, want the inspect and %v", clab.calls, imageInspect("ceos:4.32.0.2F"))
	}
}

// A dry run of a bundle on a clear host says what a create would deploy and that the host
// is clear, files the bundle, and touches nothing else: no run, no twin directory, nothing
// asked of containerlab but inspect.
func TestProvisionDryRunOnAClearHost(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	dir := copyGoldenBundle(t, "b")

	code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{dryRun: true}, dir))
	if code != findings.ExitOK || doc.DryRun == nil {
		t.Fatalf("exit %d, document %+v; want 0 with a dry_run block", code, doc)
	}
	d := doc.DryRun
	if d.Verdict != findings.VerdictClear || len(d.Nodes) != 3 || d.MemorySumMB != 6144 || d.HostBudgetMB != nil ||
		d.Host.LabPresent || d.Host.TwinDirPresent {
		t.Errorf("dry_run = %+v, want clear, three nodes, sum 6144, no budget, nothing on the host", d)
	}
	for _, n := range d.Nodes {
		if n.Image != "ghcr.io/nokia/srlinux:24.7.1" || n.PSP != "nokia_srlinux" || n.MemoryMB != 2048 {
			t.Errorf("node %+v, want the SR Linux image, package and budget", n)
		}
		// What would be pushed, as the manifest names it.
		want := findings.DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: fixtureArtifacts[n.Name], Size: 861}
		if n.Artifact == nil || *n.Artifact != want {
			t.Errorf("node %s artifact %+v, want %+v", n.Name, n.Artifact, want)
		}
	}
	if doc.BundleID != fixtureBundleID || doc.Subject.Bundle != dir || doc.Subject.RunID != "" {
		t.Errorf("document bundle %q, subject %+v; want %s, the directory as given, and no run", doc.BundleID, doc.Subject, fixtureBundleID)
	}
	if !carriesRule(doc.Findings, findings.RuleHostMemoryUnbudgeted) || findings.List(doc.Findings).Rejected() {
		t.Errorf("findings %+v, want the unbudgeted warning and no refusal", doc.Findings)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"host_budget_mb":null`) {
		t.Errorf("document %s does not say host_budget_mb null", b)
	}
	// A bundle that records nothing lossy says so with two zeros, never by leaving the
	// counts out.
	if !strings.Contains(string(b), `"lossy_mappings":0,"shared_ports":0`) {
		t.Errorf("document %s does not count 0 lossy mappings and 0 shared ports", b)
	}
	validateM6Document(t, doc)

	if got := entriesOf(t, paths.Bundles); !slices.Equal(got, []string{fixtureBundleID}) {
		t.Errorf("store holds %v, want the bundle filed as %s", got, fixtureBundleID)
	}
	if _, err := os.Stat(paths.Twin); !os.IsNotExist(err) {
		t.Errorf("a dry run left a twin directory at %s (%v)", paths.Twin, err)
	}
	if len(clab.calls) != 1 || !slices.Equal(clab.calls[0], inspectAll) {
		t.Errorf("containerlab was asked %v, want only %v", clab.calls, inspectAll)
	}
}

// The text report is the contract's shape, with no read line for a bundle.
func TestProvisionDryRunTextReport(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	dir := copyGoldenBundle(t, "b")

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	if code, _ := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, want 0", code)
	}
	want := strings.Join([]string{
		"dry run: no lab, container, twin directory or run is created",
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID),
		"nodes:",
		"  n1  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config " + fixtureArtifacts["n1"] + " (861 bytes)",
		"  n2  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config " + fixtureArtifacts["n2"] + " (861 bytes)",
		"  n3  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config " + fixtureArtifacts["n3"] + " (861 bytes)",
		"mapping: 0 lossy mappings, 0 shared ports",
		"memory: sum 6144 MiB; host budget unset",
		"host: lab fylgja absent; twin directory absent",
		"follow: would not follow (a bundle never follows)",
		"verdict: clear",
	}, "\n") + "\n"
	if out != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
	}
}

// A dry run of a lossy bundle counts its lossy record from the manifest, the one input a
// provision dry run has, and a create's read line counts it too (contracts/cli.md). The
// lossy golden holds nine lossy mappings over three shared ports
// (internal/compiler's TestLossyRecordIsComplete).
func TestDryRunCountsTheLossyRecord(t *testing.T) {
	const lossyID = "5773b6bba1107076b2cde8283f92494d42b3eab89c5f297ea25f81134fd529f7"
	useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	// The design-case package's probe login, which the host check requires set as it
	// does SR Linux's.
	t.Setenv("FYLGJA_CHASSISOS_USERNAME", "admin")
	t.Setenv("FYLGJA_CHASSISOS_PASSWORD", "not-the-real-one")
	useClab(t, "inspect-empty.json")
	dir := copyGoldenBundleOf(t, "lossy", "b")
	usePSPDir(t, repoPath("testdata", "psp", "lossy"))
	opts := options{}

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &opts, &provisionFlags{dryRun: true}, dir)
	})
	if code, _ := exitOf(t, err); code != findings.ExitOK || !strings.Contains(out, "\nmapping: 9 lossy mappings, 3 shared ports\nmemory: ") {
		t.Errorf("exit %d, stdout:\n%s\nwant the mapping: line between nodes: and memory:", code, out)
	}
	opts.asJSON = true
	code, doc := exitOf(t, runTwinProvision(context.Background(), &opts, &provisionFlags{dryRun: true}, dir))
	if code != findings.ExitOK || doc.DryRun == nil || doc.DryRun.LossyMappings != 9 || doc.DryRun.SharedPorts != 3 {
		t.Fatalf("exit %d, dry_run %+v; want 9 lossy mappings and 3 shared ports", code, doc.DryRun)
	}
	if doc.BundleID != lossyID {
		t.Errorf("bundle_id %s, want the lossy golden's %s", doc.BundleID, lossyID)
	}
	validateM6Document(t, doc)
}

// On a host where the real create would be refused, the dry run's verdict names the
// identifier the real run would refuse with, and exits as the refusal does.
func TestProvisionDryRunRefusedAsTheRunWouldBe(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-three.json")
	dir := copyGoldenBundle(t, "b")

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitRejected || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused || !doc.DryRun.Host.LabPresent {
		t.Fatalf("exit %d, document %+v; want 1, verdict refused, lab present", code, doc)
	}
	if !carriesRule(doc.Findings, findings.RuleHostLabPresent) {
		t.Errorf("findings %+v, want %s", doc.Findings, findings.RuleHostLabPresent)
	}
	for _, line := range []string{"host: lab fylgja present; twin directory absent", "verdict: refused (host.lab.present)"} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out)
		}
	}
	validateM6Document(t, doc)
	if len(clab.calls) != 1 || !slices.Equal(clab.calls[0], inspectAll) {
		t.Errorf("containerlab was asked %v, want only %v", clab.calls, inspectAll)
	}
	if _, err := os.Stat(paths.Twin); !os.IsNotExist(err) {
		t.Errorf("a dry run left a twin directory at %s (%v)", paths.Twin, err)
	}
}

// renderText is what main writes for a command's document in text mode: the findings, one
// per line, on stderr.
func renderText(t *testing.T, doc *findings.Document) string {
	t.Helper()
	var stdout, stderr strings.Builder
	findings.Render(doc, &stdout, &stderr, false)
	if stdout.Len() != 0 {
		t.Errorf("text rendering wrote %q to stdout, want the findings on stderr only", stdout.String())
	}
	return stderr.String()
}

// A dry run on a host holding a twin names it in both refusals from its twin.json, as the
// run's own host check would: the same lab.CheckHost, in the CLI's process. The document and
// the text host line are M2's.
func TestProvisionDryRunNamesTheTwin(t *testing.T) {
	const (
		bundleID = "893b6392da4f1de868e74e418d90f3d5982ecc06ffa1dc39a391d717a81997ad"
		runID    = "01a0a698-fc78-7cb5-b0f1-a31c8f06d7e9"
		phrase   = "the twin of branch fylgja-fixture at 2026-09-16T14:00:00Z, bundle_id " + bundleID +
			", provisioned by run fylgja-provision " + runID + ", 3 nodes recorded"
	)
	paths := useStateRoot(t)
	useService(t, nil)
	observed := "2026-09-16T13:59:30.000000Z"
	fields := lab.RecordFields{
		BundleID:   bundleID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: "2026-09-16T14:00:00Z", SchemaHash: "41349c3a", ContractVersion: "0.2"},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      runID,
		Version:    "0.1.0-test",
		RecordedAt: time.Date(2026, 9, 16, 14, 1, 2, 0, time.UTC),
	}
	for _, n := range []string{"n1", "n2", "n3"} {
		fields.Nodes = append(fields.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n,
			Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}})
	}
	rec, err := lab.NewRecord(fields)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := lab.WriteRecord(paths.TwinJSON, rec); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	dryRunEnv(t)
	clab := useClab(t, "inspect-three.json")
	dir := copyGoldenBundle(t, "b")

	var runErr error
	out := captureStdout(t, func() {
		runErr = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	code, doc := exitOf(t, runErr)
	if code != findings.ExitRejected || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused {
		t.Fatalf("exit %d, document %+v; want 1, verdict refused", code, doc)
	}
	labMsg := "lab fylgja is present (3 nodes), " + phrase + "; one twin exists at a time, and fylgja twin destroy clears it"
	twinMsg := "twin directory " + paths.Twin + " is present, " + phrase + "; fylgja twin destroy clears it"
	for rule, want := range map[string]string{findings.RuleHostLabPresent: labMsg, findings.RuleHostTwinPresent: twinMsg} {
		var got []string
		for _, f := range doc.Findings {
			if f.Rule == rule {
				got = append(got, f.Message)
			}
		}
		if len(got) != 1 || got[0] != want {
			t.Errorf("%s messages = %q, want exactly [%q]", rule, got, want)
		}
	}
	for _, line := range []string{"host: lab fylgja present; twin directory present", "verdict: refused (host.lab.present, host.twin.present)"} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out)
		}
	}
	text := renderText(t, doc)
	for _, line := range []string{
		"rejection host.lab.present [step host_check] lab fylgja: " + labMsg,
		"rejection host.twin.present [step host_check] " + paths.Twin + ": " + twinMsg,
	} {
		if !strings.Contains(text, line+"\n") {
			t.Errorf("findings text does not carry %q:\n%s", line, text)
		}
	}
	validateM6Document(t, doc)
	if len(clab.calls) != 1 || !slices.Equal(clab.calls[0], inspectAll) {
		t.Errorf("containerlab was asked %v, want only %v", clab.calls, inspectAll)
	}
	if after, err := os.ReadFile(paths.TwinJSON); err != nil || !bytes.Equal(after, before) {
		t.Errorf("twin.json after the dry run: %q, %v; want it unchanged", after, err)
	}
}

// A dry run beside a lab deployed from elsewhere calls it an orphan, with its node count and
// the topology it came from, under host.lab.present alone.
func TestProvisionDryRunNamesAnOrphan(t *testing.T) {
	const msg = "lab fylgja is present (1 node), an orphan: no twin.json records it; deployed from " +
		"/tmp/scratchpad/orphan/topology.clab.yml; one twin exists at a time, and fylgja twin destroy clears it"
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-one-orphan.json")
	dir := copyGoldenBundle(t, "b")

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitRejected || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused ||
		!doc.DryRun.Host.LabPresent || doc.DryRun.Host.TwinDirPresent {
		t.Fatalf("exit %d, document %+v; want 1, verdict refused, the lab alone", code, doc)
	}
	var rejections []findings.Finding
	for _, f := range doc.Findings {
		if f.Severity == findings.Rejection {
			rejections = append(rejections, f)
		}
	}
	if len(rejections) != 1 || rejections[0].Rule != findings.RuleHostLabPresent || rejections[0].Message != msg {
		t.Errorf("rejections = %+v, want exactly one %s saying %q", rejections, findings.RuleHostLabPresent, msg)
	}
	for _, line := range []string{"host: lab fylgja present; twin directory absent", "verdict: refused (host.lab.present)"} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("stdout does not say %q:\n%s", line, out)
		}
	}
	if line := "rejection host.lab.present [step host_check] lab fylgja: " + msg; !strings.Contains(renderText(t, doc), line+"\n") {
		t.Errorf("findings text does not carry %q", line)
	}
	validateM6Document(t, doc)
	if len(clab.calls) != 1 || !slices.Equal(clab.calls[0], inspectAll) {
		t.Errorf("containerlab was asked %v, want only %v", clab.calls, inspectAll)
	}
	if _, err := os.Stat(paths.Twin); !os.IsNotExist(err) {
		t.Errorf("a dry run left a twin directory at %s (%v)", paths.Twin, err)
	}
}

// A create dry run whose read cannot run reports that, exit 2, having dialled no workflow
// service and asked containerlab nothing: the read comes first.
func TestCreateDryRunNeverDials(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	t.Setenv(intent.EnvAddress, unreachable)
	t.Setenv(intent.EnvToken, "any-token")

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", dryRun: true}))
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Errorf("exit %d, findings %+v; want 2 with %s", code, doc.Findings, findings.RuleOperationFailed)
	}
	if len(clab.calls) != 0 {
		t.Errorf("containerlab was asked %v before anything was read", clab.calls)
	}
	if got := entriesOf(t, paths.Bundles); len(got) != 0 {
		t.Errorf("store holds %v after a read that could not run", got)
	}
}

// A create dry run from a waypoint resolves it, prints the waypoint line, then M2's report
// on the resolved reference: the read is the pinned read of that branch at that at, so the
// fixture's waypoint compiles to the golden bundle, and the twin would not follow. A
// refusal at resolution ends the dry run with its exit, having read,
// filed and asked containerlab nothing.
func TestCreateDryRunFromAWaypoint(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	f := demoInfrahub(t)
	f.start()

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{waypoint: "demo/2", dryRun: true})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	lines := strings.Split(out, "\n")
	for i, want := range []string{
		`waypoint demo/2: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), "after the first cut-over"`,
		"dry run: no lab, container, twin directory or run is created",
		"read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports " +
			"(branch fylgja-fixture, at 2026-09-08T12:00:00Z, schema fixture)",
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID),
	} {
		if i >= len(lines) || lines[i] != want {
			t.Errorf("stdout line %d is not %q:\n%s", i+1, want, out)
		}
	}
	if !strings.Contains(out, "\nfollow: would not follow (--waypoint given: a waypoint is pinned)\nverdict: clear\n") {
		t.Errorf("stdout:\n%s\nwant the waypoint's follow line before the verdict", out)
	}
	// Every request of the read names the resolved at, verbatim, as --at would.
	for _, r := range f.requests() {
		if strings.HasPrefix(r.Path, "/graphql/") || strings.HasPrefix(r.Path, "/api/storage/") {
			if r.Query != "at=2026-09-08T12%3A00%3A00Z" {
				t.Errorf("the read asked %+v, want the waypoint's at on it", r)
			}
		}
	}

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{waypoint: "demo/2", dryRun: true}))
	want := findings.WaypointBlock{Series: "demo", Sequence: 2, Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given",
		Description: "after the first cut-over"}
	if code != findings.ExitOK || doc.BundleID != fixtureBundleID || doc.Waypoint == nil || *doc.Waypoint != want ||
		doc.DryRun == nil || doc.DryRun.Follow == nil || doc.DryRun.Follow.Reason != findings.FollowReasonWaypoint ||
		doc.Subject.Waypoint != "demo/2" || doc.Subject.Branch != "fylgja-fixture" || doc.Subject.At != fixtureAt {
		t.Errorf("exit %d, document %+v; want 0 naming the golden bundle, the waypoint and the reason waypoint", code, doc)
	}
	mustCarryNoToken(t, "dry run", doc)
	mustNotCarryContent(t, out)
	validateM10Document(t, doc)

	t.Run("refused at resolution", func(t *testing.T) {
		paths := useStateRoot(t)
		clab.calls = nil
		code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{waypoint: "demo/5", dryRun: true}))
		if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleWaypointAtUnresolved ||
			doc.Findings[0].Step != findings.StepResolve || doc.DryRun != nil {
			t.Errorf("exit %d, document %+v; want 1 with %s at step resolve and no dry_run", code, doc, findings.RuleWaypointAtUnresolved)
		}
		if len(clab.calls) != 0 {
			t.Errorf("containerlab was asked %v after a refused resolution", clab.calls)
		}
		if got := entriesOf(t, paths.Bundles); len(got) != 0 {
			t.Errorf("store holds %v after a refused resolution", got)
		}
		validateM10Document(t, doc)
	})
}

// mustNotCarryContent fails when a line quotes an artifact: the marker the fixture's
// artifacts carry, or a line of their configuration (Constitution X).
func mustNotCarryContent(t *testing.T, out string) {
	t.Helper()
	for _, marker := range []string{"FYLGJA-MARKER", "set / interface", "enter candidate"} {
		if strings.Contains(out, marker) {
			t.Errorf("output quotes artifact content (%q):\n%s", marker, out)
		}
	}
}

// A provision dry run says a bundle never follows, through the command itself.
func TestDryRunFollowProvision(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	dir := copyGoldenBundle(t, "b")

	var err error
	out := captureStdout(t, func() {
		err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
	})
	if code, _ := exitOf(t, err); code != findings.ExitOK || !strings.Contains(out, "\nfollow: would not follow (a bundle never follows)\n") {
		t.Errorf("exit %d, stdout:\n%s\nwant the bundle's follow: line", code, out)
	}
	_, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{dryRun: true}, dir))
	want := findings.DryRunFollow{Reason: findings.FollowReasonBundle}
	if doc.DryRun == nil || doc.DryRun.Follow == nil || *doc.DryRun.Follow != want {
		t.Errorf("dry_run %+v, want follow %+v", doc.DryRun, want)
	}
	validateM6Document(t, doc)
}

// A login variable the second platform names, unset on this worker, refuses the dry run
// exactly as the run's host check would, and names that platform alone. The CLI reads the
// names from each node's own package, so a mixed bundle is the only place a check that
// took them from the first node, the first package or a constant shows (M7
// contracts/cli.md's environment table).
func TestProvisionDryRunRefusesAnUnsetLoginOfTheSecondPlatform(t *testing.T) {
	for _, variable := range []string{"FYLGJA_EOS_PASSWORD", "FYLGJA_EOS_USERNAME"} {
		t.Run(variable, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			mixedDryRunEnv(t)
			t.Setenv(variable, "")
			clab := useClab(t, "inspect-empty.json")
			clab.images = map[string]bool{"ceos:4.32.0.2F": true}
			dir := copyGoldenBundleOf(t, "mixed", "b")

			var err error
			out := captureStdout(t, func() {
				err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
			})
			code, doc := exitOf(t, err)
			if code != findings.ExitRejected || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused {
				t.Fatalf("exit %d, document %+v; want 1 and verdict refused", code, doc)
			}
			want := variable + " is unset on this worker; support package arista_eos " +
				"names it for its readiness probe login and its push login"
			var got []string
			for _, f := range doc.Findings {
				if f.Rule == findings.RuleHostProbeLoginUnset {
					got = append(got, f.Message)
					if f.Severity != findings.Rejection || f.Step != findings.StepHostCheck || f.Object != variable {
						t.Errorf("finding = %+v, want a host_check rejection on the variable", f)
					}
				}
			}
			if len(got) != 1 || got[0] != want {
				t.Errorf("%s findings = %q, want exactly one:\n  %q", findings.RuleHostProbeLoginUnset, got, want)
			}
			// The verdict's own list names it, and the platform whose pair is set is not
			// refused for anything.
			if line := "verdict: refused (" + findings.RuleHostProbeLoginUnset + ")"; !strings.Contains(out, line+"\n") {
				t.Errorf("stdout does not say %q:\n%s", line, out)
			}
			for _, f := range doc.Findings {
				if f.Severity == findings.Rejection && f.Rule != findings.RuleHostProbeLoginUnset {
					t.Errorf("finding %+v also refuses the dry run", f)
				}
			}
			validateM6Document(t, doc)
			// The refusal names the platform that needs the variable and not the one
			// whose pair is set, and no value reaches the output. The node list names
			// both packages, as it always does: that is the bundle, not the refusal.
			if len(got) == 1 && strings.Contains(got[0], "nokia_srlinux") {
				t.Errorf("the refusal %q names the platform whose login is set", got[0])
			}
			for _, name := range []string{"not-the-real-one", "FYLGJA_SRLINUX"} {
				if strings.Contains(out, name) {
					t.Errorf("stdout names %s:\n%s", name, out)
				}
			}
		})
	}
}
