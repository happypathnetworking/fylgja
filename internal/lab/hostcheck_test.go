package lab

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// goldenID is the fixture bundle's identity.
const goldenID = "23f86a2678a49a324a04ae458703be8252e2e30d6712d6b6094ce1ccd5c2988e"

func goldenBundle() string {
	return filepath.Join("..", "..", "testdata", "golden", "three-node")
}

// testActivities are the host-bound activities over a fake runner, the shipped packages
// and a fresh state root, with an empty environment and a silent log.
func testActivities(t *testing.T, r Runner) *Activities {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	paths := PathsAt(t.TempDir())
	return &Activities{
		Clab:     quietClab(r),
		Store:    bundle.NewDirStore(paths.Bundles),
		Paths:    paths,
		Registry: reg,
		Getenv:   mapEnv(nil),
		Version:  "0.1.0-test",
		Log:      slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func mapEnv(m map[string]string) func(string) (string, bool) {
	return func(k string) (string, bool) {
		v, ok := m[k]
		return v, ok
	}
}

// srlinuxPush is the shipped package's push, on replace from format 0.6
// (M11 D-033).
func srlinuxPush() wire.PushSpec {
	return wire.PushSpec{
		Delivery: "json_rpc", Mode: "replace", Commit: "explicit", Scheme: "https", Port: 443,
		UsernameEnv: "FYLGJA_SRLINUX_USERNAME", PasswordEnv: "FYLGJA_SRLINUX_PASSWORD", TimeoutS: 30,
	}
}

func srlinuxProbe() wire.Probe {
	return wire.Probe{
		Transport: "gnmi_get", Path: "/system/information", Encoding: "json_ietf", Port: 57400,
		UsernameEnv: "FYLGJA_SRLINUX_USERNAME", PasswordEnv: "FYLGJA_SRLINUX_PASSWORD",
	}
}

// wantProbe compares a planned probe with what the package declares. TLS is compared by
// value and separately, because the field is a pointer: nodePlan always sets it, so a
// nil here would mean the plan left the dial to be inferred from an absent key, which is
// the thing the pointer exists to make impossible.
func wantProbe(t *testing.T, node string, got, want wire.Probe, wantTLS bool) {
	t.Helper()
	gotTLS := got.TLS
	got.TLS = nil
	if got != want {
		t.Errorf("%s probe = %+v, want %+v", node, got, want)
	}
	switch {
	case gotTLS == nil:
		t.Errorf("%s probe leaves tls unset; a plan this build writes always states it", node)
	case *gotTLS != wantTLS:
		t.Errorf("%s probe tls = %v, want %v from the package", node, *gotTLS, wantTLS)
	}
}

// srlinuxLogin is a worker environment with the shipped package's probe login set.
func srlinuxLogin(extra map[string]string) map[string]string {
	m := map[string]string{"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": "not-the-real-one"}
	maps.Copy(m, extra)
	return m
}

func checkGolden(t *testing.T, a *Activities) wire.CheckHostResult {
	t.Helper()
	return checkBundle(t, a, goldenBundle())
}

func checkBundle(t *testing.T, a *Activities, dir string) wire.CheckHostResult {
	t.Helper()
	res, err := CheckHost(context.Background(), a, wire.CheckHostInput{BundlePath: dir, BundleID: goldenID})
	if err != nil {
		t.Fatal(err)
	}
	return res
}

// only returns the one finding under rule, failing the test unless there is exactly one.
func only(t *testing.T, list findings.List, rule string) findings.Finding {
	t.Helper()
	var found []findings.Finding
	for _, f := range list {
		if f.Rule == rule {
			found = append(found, f)
		}
	}
	if len(found) != 1 {
		t.Fatalf("findings %+v carry %d %s, want exactly one", list, len(found), rule)
	}
	return found[0]
}

// writeTwin writes rec as twin.json under a's state root, creating the twin directory, as
// RecordTwin leaves it.
func writeTwin(t *testing.T, a *Activities, rec *wire.TwinRecord) {
	t.Helper()
	if err := os.MkdirAll(a.Paths.Twin, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := WriteRecord(a.Paths.TwinJSON, *rec); err != nil {
		t.Fatal(err)
	}
}

// exactly checks a finding's message is exactly want.
func exactly(t *testing.T, f findings.Finding, want string) {
	t.Helper()
	if f.Message != want {
		t.Errorf("%s message =\n  %q\nwant\n  %q", f.Rule, f.Message, want)
	}
}

// absent fails the test if any finding is under rule.
func absent(t *testing.T, list findings.List, rule string) {
	t.Helper()
	for _, f := range list {
		if f.Rule == rule {
			t.Errorf("finding %+v, want no %s", f, rule)
		}
	}
}

// refusal checks a host-check rejection's object and that its message says each of says.
func refusal(t *testing.T, f findings.Finding, object string, says ...string) {
	t.Helper()
	if f.Severity != findings.Rejection || f.Step != findings.StepHostCheck || f.Object != object {
		t.Errorf("finding = %+v, want a host_check rejection on %q", f, object)
	}
	for _, s := range says {
		if !strings.Contains(f.Message, s) {
			t.Errorf("message %q does not say %q", f.Message, s)
		}
	}
}

// On a clear host the check plans three nodes with every budget and the probe from the
// shipped package, and does nothing but look.
func TestCheckHostClearHost(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}}
	a := testActivities(t, f)
	a.Getenv = mapEnv(srlinuxLogin(nil))

	res := checkGolden(t, a)
	if res.LabPresent || res.TwinDirPresent {
		t.Errorf("lab present %v, twin directory present %v; want a clear host", res.LabPresent, res.TwinDirPresent)
	}
	if len(res.Nodes) != 3 {
		t.Fatalf("nodes = %+v, want three", res.Nodes)
	}
	for i, n := range res.Nodes {
		if want := []string{"n1", "n2", "n3"}[i]; n.Name != want {
			t.Errorf("node %d = %s, want %s (sorted by name)", i, n.Name, want)
		}
		if n.MemoryMB != 2048 || n.DeployTimeoutS != 180 || n.TimeoutS != 60 || n.DestroyTimeoutS != 60 {
			t.Errorf("%s budgets = memory %d, deploy %d, readiness %d, destroy %d; want 2048/180/60/60 from the package",
				n.Name, n.MemoryMB, n.DeployTimeoutS, n.TimeoutS, n.DestroyTimeoutS)
		}
		// The shipped package omits readiness.tls, which means TLS.
		wantProbe(t, n.Name, n.Probe, srlinuxProbe(), true)
		if n.Push != srlinuxPush() {
			t.Errorf("%s push = %+v, want %+v from the package", n.Name, n.Push, srlinuxPush())
		}
		if n.Artifact == nil || n.Artifact.File != "configs/"+n.Name+".device-config" || len(n.Artifact.Checksum) != 32 {
			t.Errorf("%s artifact = %+v, want the manifest's file and checksum", n.Name, n.Artifact)
		}
		if n.PSPID != "nokia_srlinux" || n.PSPSource != "embedded" || n.Image != "ghcr.io/nokia/srlinux:24.7.1" {
			t.Errorf("%s = %+v, want the manifest's package and image", n.Name, n)
		}
	}
	if res.MemorySumMB != 6144 {
		t.Errorf("memory sum = %d, want 6144", res.MemorySumMB)
	}
	if res.HostBudgetMB != nil {
		t.Errorf("host budget = %d, want unset", *res.HostBudgetMB)
	}
	if res.Findings.Rejected() {
		t.Errorf("findings %+v refuse a clear host", res.Findings)
	}
	if res.Provenance.Branch != "fylgja-fixture" || res.Provenance.ContractVersion != "0.2" {
		t.Errorf("provenance = %+v, want the manifest's", res.Provenance)
	}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, inspectArgs) {
		t.Errorf("runner saw %+v, want only %v", f.calls, inspectArgs)
	}
}

// Every host.* identifier, each produced once by what the host holds and what the worker's
// environment says (contracts/cli.md; Constitution X).
func TestCheckHostProducesEveryHostIdentifier(t *testing.T) {
	empty := func(t *testing.T) *fakeRunner {
		return &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}}
	}

	t.Run("lab present", func(t *testing.T) {
		a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three.json")}}}})
		a.Getenv = mapEnv(srlinuxLogin(nil))
		res := checkGolden(t, a)
		f := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, f, "lab fylgja", "3 nodes", "fylgja twin destroy")
		exactly(t, f, "lab fylgja is present (3 nodes), an orphan: no twin.json records it; deployed from "+
			"/tmp/scratchpad/twin3/bundle/topology.clab.yml; one twin exists at a time, and fylgja twin destroy clears it")
		if !res.LabPresent {
			t.Error("LabPresent is false")
		}
	})
	t.Run("twin directory present", func(t *testing.T) {
		a := testActivities(t, empty(t))
		a.Getenv = mapEnv(srlinuxLogin(nil))
		if err := os.MkdirAll(a.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		res := checkGolden(t, a)
		f := only(t, res.Findings, findings.RuleHostTwinPresent)
		refusal(t, f, a.Paths.Twin, "fylgja twin destroy")
		exactly(t, f, "twin directory "+a.Paths.Twin+" is present, a leftover twin directory: no twin.json and no lab fylgja; "+
			"fylgja twin destroy clears it")
	})
	t.Run("memory over the host budget", func(t *testing.T) {
		a := testActivities(t, empty(t))
		a.Getenv = mapEnv(srlinuxLogin(map[string]string{"FYLGJA_HOST_MEMORY_MB": "4096"}))
		res := checkGolden(t, a)
		f := only(t, res.Findings, findings.RuleHostMemoryExceeded)
		refusal(t, f, "host")
		if want := "sum 6144 MiB exceeds budget 4096 MiB (n1 2048, n2 2048, n3 2048)"; f.Message != want {
			t.Errorf("message %q, want %q", f.Message, want)
		}
		if res.HostBudgetMB == nil || *res.HostBudgetMB != 4096 {
			t.Errorf("host budget = %v, want 4096", res.HostBudgetMB)
		}
		for _, g := range res.Findings {
			if g.Rule == findings.RuleHostMemoryUnbudgeted {
				t.Errorf("a budget is set, but the check warns %+v", g)
			}
		}
	})
	t.Run("no host budget is a warning", func(t *testing.T) {
		a := testActivities(t, empty(t))
		a.Getenv = mapEnv(srlinuxLogin(nil))
		res := checkGolden(t, a)
		f := only(t, res.Findings, findings.RuleHostMemoryUnbudgeted)
		if f.Severity != findings.Warning || f.Object != "host" || !strings.Contains(f.Message, "sum 6144 MiB") ||
			!strings.Contains(f.Message, "n1 2048, n2 2048, n3 2048") {
			t.Errorf("finding = %+v, want a warning naming the sum and every node", f)
		}
		if res.Findings.Rejected() {
			t.Errorf("an unset budget refused the create: %+v", res.Findings)
		}
	})
	t.Run("probe login variable unset", func(t *testing.T) {
		const sentinel = "sentinel-username-value"
		a := testActivities(t, empty(t))
		a.Getenv = mapEnv(map[string]string{"FYLGJA_SRLINUX_USERNAME": sentinel})
		res := checkGolden(t, a)
		// The shipped package names the variable for its probe and its push: one finding,
		// naming both uses, under M2's rule (M5 contracts/cli.md).
		exactly(t, only(t, res.Findings, findings.RuleHostProbeLoginUnset),
			"FYLGJA_SRLINUX_PASSWORD is unset on this worker; support package nokia_srlinux names it for its readiness probe login and its push login")
		refusal(t, only(t, res.Findings, findings.RuleHostProbeLoginUnset), "FYLGJA_SRLINUX_PASSWORD", "nokia_srlinux")
		b, err := json.Marshal(res)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), sentinel) {
			t.Error("a probe login value reached the host check's result")
		}
	})
	t.Run("support package missing", func(t *testing.T) {
		a := testActivities(t, empty(t))
		a.Getenv = mapEnv(srlinuxLogin(nil))
		res := checkBundle(t, a, bundleNaming(t, "n2", "ghostos"))
		refusal(t, only(t, res.Findings, findings.RuleHostPSPMissing), "ghostos", "n2", "embedded")
		if len(res.Nodes) != 2 || res.MemorySumMB != 4096 {
			t.Errorf("planned %+v (sum %d), want n1 and n3 only", res.Nodes, res.MemorySumMB)
		}
	})
}

// A twin on the host is named in both refusals from its twin.json — branch, at when the
// reference was pinned, bundle_id and run in full, the recorded node count — beside
// containerlab's count, with M2's identifiers, objects and remedy.
func TestCheckHostNamesTheTwin(t *testing.T) {
	observed := "2026-09-16T13:59:30.000000Z"
	three := func(t *testing.T) *fakeRunner {
		return &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three.json")}}}}
	}
	ids := ", bundle_id " + namingBundleID + ", provisioned by run fylgja-provision " + namingRunID

	for _, tc := range []struct {
		label, at string
		twin      string // the phrase
	}{
		{"unpinned", "", "the twin of branch fylgja-fixture" + ids + ", 3 nodes recorded"},
		{"pinned", namingAt, "the twin of branch fylgja-fixture at 2026-09-16T14:00:00Z" + ids + ", 3 nodes recorded"},
	} {
		t.Run(tc.label, func(t *testing.T) {
			a := testActivities(t, three(t))
			a.Getenv = mapEnv(srlinuxLogin(nil))
			writeTwin(t, a, namedRecord(t, tc.at, &observed, 3))
			res := checkGolden(t, a)

			lab := only(t, res.Findings, findings.RuleHostLabPresent)
			refusal(t, lab, "lab fylgja")
			exactly(t, lab, "lab fylgja is present (3 nodes), "+tc.twin+"; one twin exists at a time, and fylgja twin destroy clears it")
			twin := only(t, res.Findings, findings.RuleHostTwinPresent)
			refusal(t, twin, a.Paths.Twin)
			exactly(t, twin, "twin directory "+a.Paths.Twin+" is present, "+tc.twin+"; fylgja twin destroy clears it")
			if !res.LabPresent || !res.TwinDirPresent {
				t.Errorf("lab present %v, twin directory present %v; want both", res.LabPresent, res.TwinDirPresent)
			}
		})
	}

	t.Run("record without a lab", func(t *testing.T) {
		a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}})
		a.Getenv = mapEnv(srlinuxLogin(nil))
		writeTwin(t, a, namedRecord(t, "", &observed, 3))
		res := checkGolden(t, a)

		absent(t, res.Findings, findings.RuleHostLabPresent)
		twin := only(t, res.Findings, findings.RuleHostTwinPresent)
		refusal(t, twin, a.Paths.Twin)
		exactly(t, twin, "twin directory "+a.Paths.Twin+" is present, the twin of branch fylgja-fixture"+ids+
			", 3 nodes recorded, but lab fylgja is absent; fylgja twin destroy clears it")
		if res.LabPresent || !res.TwinDirPresent {
			t.Errorf("lab present %v, twin directory present %v; want the twin directory alone", res.LabPresent, res.TwinDirPresent)
		}
	})

	// A record and containerlab that disagree are both reported as each says; nothing
	// reconciles them.
	t.Run("counts that disagree", func(t *testing.T) {
		a := testActivities(t, three(t))
		a.Getenv = mapEnv(srlinuxLogin(nil))
		writeTwin(t, a, namedRecord(t, "", &observed, 2))
		res := checkGolden(t, a)

		lab := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, lab, "lab fylgja")
		exactly(t, lab, "lab fylgja is present (3 nodes), the twin of branch fylgja-fixture"+ids+
			", 2 nodes recorded; one twin exists at a time, and fylgja twin destroy clears it")
	})
}

// A lab without a readable twin.json is called an orphan, with containerlab's node count and
// every topology path its containers carry; a twin directory alone is a leftover; a record
// that cannot be read is reported with the reason, and never fails the check.
func TestCheckHostNamesAnOrphan(t *testing.T) {
	inspecting := func(t *testing.T, recording string) *Activities {
		a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, recording)}}}})
		a.Getenv = mapEnv(srlinuxLogin(nil))
		return a
	}
	const (
		remedyLab   = "; one twin exists at a time, and fylgja twin destroy clears it"
		remedyTwin  = "; fylgja twin destroy clears it"
		twinTopo    = "; deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml"
		unparseable = "{"
	)
	writeRaw := func(t *testing.T, a *Activities, b []byte, mode os.FileMode) {
		if err := os.MkdirAll(a.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(a.Paths.TwinJSON, b, mode); err != nil {
			t.Fatal(err)
		}
	}

	t.Run("(c) no twin directory", func(t *testing.T) {
		a := inspecting(t, "inspect-one-orphan.json")
		res := checkGolden(t, a)
		lab := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, lab, "lab fylgja")
		exactly(t, lab, "lab fylgja is present (1 node), an orphan: no twin.json records it; deployed from "+
			"/tmp/scratchpad/orphan/topology.clab.yml"+remedyLab)
		absent(t, res.Findings, findings.RuleHostTwinPresent)
		if !res.LabPresent || res.TwinDirPresent {
			t.Errorf("lab present %v, twin directory present %v; want the lab alone", res.LabPresent, res.TwinDirPresent)
		}
	})
	t.Run("(c) containers naming two topology paths", func(t *testing.T) {
		a := inspecting(t, "inspect-three-paths.json")
		res := checkGolden(t, a)
		lab := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, lab, "lab fylgja")
		exactly(t, lab, "lab fylgja is present (3 nodes), an orphan: no twin.json records it; deployed from "+
			"/tmp/scratchpad/elsewhere/topology.clab.yml, /tmp/scratchpad/twin3/bundle/topology.clab.yml"+remedyLab)
		absent(t, res.Findings, findings.RuleHostTwinPresent)
	})
	t.Run("(d) cut short: a twin directory without twin.json", func(t *testing.T) {
		a := inspecting(t, "inspect-three.json")
		if err := os.MkdirAll(a.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		res := checkGolden(t, a)
		phrase := "an orphan: no twin.json records it (a run cut short before it recorded the twin)" + twinTopo
		lab := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, lab, "lab fylgja")
		exactly(t, lab, "lab fylgja is present (3 nodes), "+phrase+remedyLab)
		twin := only(t, res.Findings, findings.RuleHostTwinPresent)
		refusal(t, twin, a.Paths.Twin)
		exactly(t, twin, "twin directory "+a.Paths.Twin+" is present, "+phrase+remedyTwin)
	})
	t.Run("(e) twin.json does not parse", func(t *testing.T) {
		a := inspecting(t, "inspect-three.json")
		writeRaw(t, a, []byte(unparseable), 0o644)
		res := checkGolden(t, a)
		phrase := "treated as an orphan: twin.json could not be read (reading " + a.Paths.TwinJSON +
			": unexpected end of JSON input)" + twinTopo
		lab := only(t, res.Findings, findings.RuleHostLabPresent)
		refusal(t, lab, "lab fylgja")
		exactly(t, lab, "lab fylgja is present (3 nodes), "+phrase+remedyLab)
		twin := only(t, res.Findings, findings.RuleHostTwinPresent)
		refusal(t, twin, a.Paths.Twin)
		exactly(t, twin, "twin directory "+a.Paths.Twin+" is present, "+phrase+remedyTwin)
	})
	t.Run("(e) twin.json does not open", func(t *testing.T) {
		if os.Geteuid() == 0 {
			t.Skip("root opens a file whatever its mode")
		}
		a := inspecting(t, "inspect-three.json")
		writeRaw(t, a, []byte(unparseable), 0o000)
		res := checkGolden(t, a)
		phrase := "treated as an orphan: twin.json could not be read (open " + a.Paths.TwinJSON +
			": permission denied)" + twinTopo
		exactly(t, only(t, res.Findings, findings.RuleHostLabPresent), "lab fylgja is present (3 nodes), "+phrase+remedyLab)
		exactly(t, only(t, res.Findings, findings.RuleHostTwinPresent), "twin directory "+a.Paths.Twin+" is present, "+phrase+remedyTwin)
	})
	t.Run("(g) leftover twin directory whose twin.json does not parse", func(t *testing.T) {
		a := inspecting(t, "inspect-empty.json")
		writeRaw(t, a, []byte(unparseable), 0o644)
		res := checkGolden(t, a)
		absent(t, res.Findings, findings.RuleHostLabPresent)
		twin := only(t, res.Findings, findings.RuleHostTwinPresent)
		refusal(t, twin, a.Paths.Twin)
		exactly(t, twin, "twin directory "+a.Paths.Twin+" is present, a leftover twin directory: twin.json could not be read (reading "+
			a.Paths.TwinJSON+": unexpected end of JSON input), and lab fylgja is absent"+remedyTwin)
	})
}

// A refused create leaves the host exactly as it found it: the check runs nothing but
// `clab inspect --all` and changes no byte, mode or modification time under the state
// root.
func TestHostCheckOnlyReads(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three.json")}}}}
	a := testActivities(t, f)
	a.Getenv = mapEnv(map[string]string{"FYLGJA_HOST_MEMORY_MB": "4096"})
	if _, err := a.StageBundle(context.Background(), wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}); err != nil {
		t.Fatal(err)
	}
	observed := "2026-09-16T13:59:30.000000Z"
	writeTwin(t, a, namedRecord(t, namingAt, &observed, 3))
	before := tree(t, a.Paths.Root)

	res := checkGolden(t, a)
	if !res.Findings.Rejected() {
		t.Fatalf("findings %+v, want refusals on a host holding a lab and a twin directory", res.Findings)
	}
	// twin.json was read, to name the twin, and left as it was.
	refusal(t, only(t, res.Findings, findings.RuleHostTwinPresent), a.Paths.Twin, "the twin of branch fylgja-fixture at "+namingAt)
	if after := tree(t, a.Paths.Root); !reflect.DeepEqual(before, after) {
		t.Errorf("the state root changed:\nbefore %v\nafter  %v", before, after)
	}
	onlyInspected(t, f)
}

// bundleNaming copies the golden bundle with one node's manifest psp.id replaced.
func bundleNaming(t *testing.T, node, pspID string) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "bundle")
	copyTree(t, goldenBundle(), dir)
	path := filepath.Join(dir, "manifest.json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	for _, n := range m["nodes"].([]any) {
		if nm := n.(map[string]any); nm["name"] == node {
			nm["psp"].(map[string]any)["id"] = pspID
		}
	}
	if b, err = json.Marshal(m); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func copyTree(t *testing.T, src, dst string) {
	t.Helper()
	err := filepath.WalkDir(src, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

// tree records every entry under root with its mode, size, modification time and, for a
// file, the hash of its content.
func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		sum := ""
		if d.Type().IsRegular() {
			b, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			sum = fmt.Sprintf("%x", sha256.Sum256(b))
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		out[rel] = fmt.Sprintf("%v %d %d %s", info.Mode(), info.Size(), info.ModTime().UnixNano(), sum)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// A login variable is listed once however many uses name it, with each use it is named for:
// the probe's alone keeps M2's wording, and a push login is named as such (one
// rule; the wording gains the second use).
func TestUnsetLoginsNameEachUse(t *testing.T) {
	probeOnly := wire.NodePlan{Name: "n1", PSPID: "a", Probe: wire.Probe{UsernameEnv: "PROBE_U", PasswordEnv: "SHARED_P"}}
	pushOnly := wire.NodePlan{Name: "n2", PSPID: "b", Push: wire.PushSpec{UsernameEnv: "PUSH_U", PasswordEnv: "SHARED_P"}}
	got := unsetLogins([]wire.NodePlan{pushOnly, probeOnly}, mapEnv(nil))
	want := []unsetLogin{
		{variable: "PUSH_U", platforms: []string{"b"}, uses: []string{usePushLogin}},
		{variable: "SHARED_P", platforms: []string{"b", "a"}, uses: []string{useProbeLogin, usePushLogin}},
		{variable: "PROBE_U", platforms: []string{"a"}, uses: []string{useProbeLogin}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("unsetLogins = %+v, want %+v", got, want)
	}
}

// fakeImages answers presence from a set of references the host is pretending to hold,
// and records what it was asked, so a test sees both the answer and the calls.
type fakeImages struct {
	held map[string]bool
	err  error
	asks []string
}

func (f *fakeImages) Present(_ context.Context, ref string) (bool, error) {
	f.asks = append(f.asks, ref)
	if f.err != nil {
		return false, f.err
	}
	return f.held[ref], nil
}

func mixedBundle() string {
	return filepath.Join("..", "..", "testdata", "golden", "mixed")
}

// bothLogins is a worker environment with both shipped packages' logins set, as the mixed
// bundle needs.
func bothLogins() map[string]string {
	return srlinuxLogin(map[string]string{"FYLGJA_EOS_USERNAME": "admin", "FYLGJA_EOS_PASSWORD": "not-the-real-one"})
}

func mixedActivities(t *testing.T, images Images) *Activities {
	t.Helper()
	a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}})
	a.Getenv = mapEnv(bothLogins())
	a.Images = images
	return a
}

// An image a package says is not pulled, absent from the host, refuses the run before
// anything is staged, naming the reference, the package, its nodes, how it is obtained and
// the guide.
func TestCheckHostImageAbsent(t *testing.T) {
	images := &fakeImages{held: map[string]bool{}}
	res := checkBundle(t, mixedActivities(t, images), mixedBundle())

	f := only(t, res.Findings, findings.RuleHostImageAbsent)
	refusal(t, f, "ceos:4.32.0.2F")
	exactly(t, f, "image ceos:4.32.0.2F is not on this host: support package arista_eos (nodes e1, e2) declares it "+
		"account_gated, obtained from the vendor with an account and imported by hand under exactly that reference, "+
		"never pulled; a reference held under another tag is absent; docs/development.md says how to import it")
	// One call per distinct reference: e1 and e2 share one, and s1's is a registry image
	// nobody asks after.
	if want := []string{"ceos:4.32.0.2F"}; !reflect.DeepEqual(images.asks, want) {
		t.Errorf("the image driver was asked %v, want %v", images.asks, want)
	}
	// The refusal is in the one pass, beside the others, and nothing else is refused.
	if rules := rejectedRules(res.Findings); !reflect.DeepEqual(rules, []string{findings.RuleHostImageAbsent}) {
		t.Errorf("rejections %v, want only %s", rules, findings.RuleHostImageAbsent)
	}
}

// The same bundle clears when the host holds the reference.
func TestCheckHostImagePresent(t *testing.T) {
	images := &fakeImages{held: map[string]bool{"ceos:4.32.0.2F": true}}
	res := checkBundle(t, mixedActivities(t, images), mixedBundle())

	absent(t, res.Findings, findings.RuleHostImageAbsent)
	if res.Findings.Rejected() {
		t.Errorf("findings %+v refuse a host that holds the image", res.Findings)
	}
	if want := []string{"ceos:4.32.0.2F"}; !reflect.DeepEqual(images.asks, want) {
		t.Errorf("the image driver was asked %v, want %v", images.asks, want)
	}
}

// A bundle whose packages all say public_registry asks the runtime nothing at all: that
// is the one acquisition a deploy may pull under.
func TestImagePresenceIsNotAskedOfARegistryBundle(t *testing.T) {
	images := &fakeImages{held: map[string]bool{}}
	a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}})
	a.Getenv = mapEnv(srlinuxLogin(nil))
	a.Images = images

	res := checkGolden(t, a)
	absent(t, res.Findings, findings.RuleHostImageAbsent)
	if len(images.asks) != 0 {
		t.Errorf("the image driver was asked %v for a bundle of registry images, want nothing", images.asks)
	}
}

// A runtime that will not answer is an operational failure naming the reference, not an
// absent image: the check does not refuse a create over a question it could not ask.
func TestCheckHostImagePresenceUnreadable(t *testing.T) {
	images := &fakeImages{err: errors.New("docker image inspect --format {{.Id}} ceos:4.32.0.2F: exec: \"docker\": executable file not found in $PATH")}
	_, err := CheckHost(context.Background(), mixedActivities(t, images), wire.CheckHostInput{BundlePath: mixedBundle(), BundleID: goldenID})
	if err == nil {
		t.Fatal("CheckHost returned no error when the image driver could not answer")
	}
	f := activityFinding(t, err)
	if f.Rule != findings.RuleOperationFailed || f.Step != findings.StepHostCheck || f.Object != "ceos:4.32.0.2F" {
		t.Errorf("finding = %+v, want %s at %s on the reference", f, findings.RuleOperationFailed, findings.StepHostCheck)
	}
	if !strings.Contains(f.Message, "executable file not found") {
		t.Errorf("message %q does not carry what the runtime said", f.Message)
	}
}

// An Activities with no image driver says so rather than reaching for a runtime nobody
// named; a registry-only bundle still checks, since it asks nothing.
func TestCheckHostWithoutAnImageDriver(t *testing.T) {
	a := mixedActivities(t, nil)
	_, err := CheckHost(context.Background(), a, wire.CheckHostInput{BundlePath: mixedBundle(), BundleID: goldenID})
	if err == nil || !strings.Contains(err.Error(), "no image driver") {
		t.Fatalf("CheckHost error = %v, want one naming the missing image driver", err)
	}
	a.Getenv = mapEnv(srlinuxLogin(nil))
	if res := checkGolden(t, a); res.Findings.Rejected() {
		t.Errorf("findings %+v refuse a registry-only bundle that asks the runtime nothing", res.Findings)
	}
}

// fastosImage is the reference the heterogeneous test package declares.
const fastosImage = "example.invalid/fastos:0"

// The clause is per value, and an acquisition that is not account_gated is checked at
// all: the shipped EOS package is the only non-registry one any bundle here names, so
// without these cases a presence pass narrowed to account_gated, or a mis-worded clause
// for either other value, would pass every tier. The override package is the
// heterogeneous fixture with its acquisition line alone moved, so a case varies the value
// and nothing else (contracts/cli.md's clause table).
func TestCheckHostImageAbsentWordsEachAcquisition(t *testing.T) {
	for _, tc := range []struct{ acquisition, clause string }{
		{psp.AcquisitionLicensed, "obtained under a licence and imported by hand under exactly that reference, never pulled"},
		{psp.AcquisitionVrnetlabVM, "built locally from a vendor VM image with vrnetlab under exactly that reference, never pulled"},
	} {
		t.Run(tc.acquisition, func(t *testing.T) {
			images := &fakeImages{held: map[string]bool{}}
			a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}})
			a.Registry = registryAcquiring(t, tc.acquisition)
			a.Getenv = mapEnv(srlinuxLogin(map[string]string{
				"FYLGJA_FASTOS_USERNAME": "admin", "FYLGJA_FASTOS_PASSWORD": "not-the-real-one",
			}))
			a.Images = images

			res := checkBundle(t, a, bundleNaming(t, "n2", "fastos"))
			f := only(t, res.Findings, findings.RuleHostImageAbsent)
			refusal(t, f, fastosImage)
			exactly(t, f, "image "+fastosImage+" is not on this host: support package fastos (nodes n2) declares it "+
				tc.acquisition+", "+tc.clause+"; a reference held under another tag is absent; "+
				"docs/development.md says how to import it")
			// The presence pass ran for this acquisition, and for nothing else: n1 and n3
			// keep the shipped package, which says public_registry.
			if want := []string{fastosImage}; !reflect.DeepEqual(images.asks, want) {
				t.Errorf("the image driver was asked %v, want %v", images.asks, want)
			}
			if rules := rejectedRules(res.Findings); !reflect.DeepEqual(rules, []string{findings.RuleHostImageAbsent}) {
				t.Errorf("rejections %v, want only %s", rules, findings.RuleHostImageAbsent)
			}
		})
	}
}

// registryAcquiring loads the shipped packages beside the heterogeneous fastos fixture
// with its acquisition line alone moved to value. The fixture is copied, never edited in
// place, as bundleNaming copies the golden bundle to move one manifest field.
func registryAcquiring(t *testing.T, acquisition string) *psp.Registry {
	t.Helper()
	src := filepath.Join("..", "..", "testdata", "psp", "heterogeneous", "fastos.yaml")
	b, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	const declared = "acquisition: " + psp.AcquisitionPublicRegistry
	if !strings.Contains(string(b), declared) {
		t.Fatalf("%s no longer declares %q; these cases move that line alone", src, declared)
	}
	dir := t.TempDir()
	moved := strings.Replace(string(b), declared, "acquisition: "+acquisition, 1)
	if err := os.WriteFile(filepath.Join(dir, "fastos.yaml"), []byte(moved), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	p, ok := reg.LookupID("fastos")
	if !ok || p.Image.Acquisition != acquisition || p.Image.Ref != fastosImage {
		t.Fatalf("the override registry answers fastos with %+v, want %s at %s", p, acquisition, fastosImage)
	}
	return reg
}

// Every clause the contract tabulates, from the one function that words them, and the
// default branch's sentence for a value the format's enum does not name — reachable only
// by a package that was not read through the schema, which is why no fixture produces it.
// The enum is read from the shipped schema, so an acquisition added to the format without
// a clause of its own fails here rather than reaching an operator wearing another value's
// sentence (contracts/cli.md).
func TestAcquisitionClauseIsPerValue(t *testing.T) {
	clauses := map[string]string{
		psp.AcquisitionAccountGated: "obtained from the vendor with an account and imported by hand under exactly that reference, never pulled",
		psp.AcquisitionLicensed:     "obtained under a licence and imported by hand under exactly that reference, never pulled",
		psp.AcquisitionVrnetlabVM:   "built locally from a vendor VM image with vrnetlab under exactly that reference, never pulled",
	}
	for value, want := range clauses {
		if got := acquisitionClause(value); got != want {
			t.Errorf("%s clause =\n  %q\nwant\n  %q", value, got, want)
		}
	}
	const unnamed = "obtained as its acquisition says and imported by hand under exactly that reference, never pulled"
	if got := acquisitionClause("smuggled-in"); got != unnamed {
		t.Errorf("an acquisition outside the enum =\n  %q\nwant\n  %q", got, unnamed)
	}
	for _, value := range schemaAcquisitions(t) {
		// public_registry never reaches a clause: no presence call is made for it, so no
		// finding is possible (contracts/cli.md's table says so in that row).
		if value == psp.AcquisitionPublicRegistry {
			continue
		}
		if _, worded := clauses[value]; !worded {
			t.Errorf("the format's enum names %s, which no case here words: the refusal would give it the unnamed value's clause", value)
		}
	}
}

// schemaAcquisitions reads image.acquisition's enum from the shipped PSP schema, so this
// test is held to the format rather than to a list kept beside it.
func schemaAcquisitions(t *testing.T) []string {
	t.Helper()
	b, err := psp.SchemaBytes()
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties struct {
			Image struct {
				Properties struct {
					Acquisition struct {
						Enum []string `json:"enum"`
					} `json:"acquisition"`
				} `json:"properties"`
			} `json:"image"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(b, &schema); err != nil {
		t.Fatal(err)
	}
	enum := schema.Properties.Image.Properties.Acquisition.Enum
	if len(enum) < 2 {
		t.Fatalf("the schema's acquisition enum is %v; this check would prove nothing", enum)
	}
	return enum
}

// activityFinding is the finding a host-check step failure carries.
func activityFinding(t *testing.T, err error) findings.Finding {
	t.Helper()
	var appErr *temporal.ApplicationError
	if !errors.As(err, &appErr) {
		t.Fatalf("error = %v, want an application error", err)
	}
	var f findings.Finding
	if err := appErr.Details(&f); err != nil {
		t.Fatal(err)
	}
	return f
}

// rejectedRules lists the rules of a list's rejections, in order.
func rejectedRules(list findings.List) []string {
	var out []string
	for _, f := range list {
		if f.Severity == findings.Rejection {
			out = append(out, f.Rule)
		}
	}
	return out
}

// The plan carries the package's own answer to whether its probe answering means the node
// can be configured (D-029): EOS asks for the wait, SR Linux does not.
func TestNodePlanCarriesAwaitPushTransport(t *testing.T) {
	images := &fakeImages{held: map[string]bool{"ceos:4.32.0.2F": true}}
	res := checkBundle(t, mixedActivities(t, images), mixedBundle())

	want := map[string]bool{"e1": true, "e2": true, "s1": false}
	for _, n := range res.Nodes {
		if n.AwaitPushTransport != want[n.Name] {
			t.Errorf("%s await_push_transport = %v, want %v from its package",
				n.Name, n.AwaitPushTransport, want[n.Name])
		}
	}
}

// eosProbeLogin and eosPushLogin are the second shipped package's variable names, which
// are its own pair and not SR Linux's (M7 contracts/cli.md's environment table).
const (
	eosUsernameEnv = "FYLGJA_EOS_USERNAME"
	eosPasswordEnv = "FYLGJA_EOS_PASSWORD"
)

// A login variable is read from the package of the node that needs it, so an unset one of
// the second platform is refused and named for that platform alone, while the platform
// whose pair is set draws nothing. Without a mixed bundle here, a check that took the
// names from the bundle's first node, from the first package in the registry or from a
// constant would pass every tier (M2 contracts/cli.md's rule, M5's wording).
func TestCheckHostNamesAnUnsetLoginOfTheSecondPlatform(t *testing.T) {
	for _, variable := range []string{eosPasswordEnv, eosUsernameEnv} {
		t.Run(variable, func(t *testing.T) {
			env := bothLogins()
			delete(env, variable)
			a := mixedActivities(t, &fakeImages{held: map[string]bool{"ceos:4.32.0.2F": true}})
			a.Getenv = mapEnv(env)

			res := checkBundle(t, a, mixedBundle())
			f := only(t, res.Findings, findings.RuleHostProbeLoginUnset)
			refusal(t, f, variable, "arista_eos")
			// The package names one pair for both uses, as SR Linux's does, so the one
			// finding says both.
			exactly(t, f, variable+" is unset on this worker; support package arista_eos "+
				"names it for its readiness probe login and its push login")
			// Nothing is said of the platform whose pair is set, and this is the only
			// thing the host is refused for.
			for _, name := range []string{"nokia_srlinux", "FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD"} {
				if strings.Contains(f.Message, name) {
					t.Errorf("message %q names %s, whose login is set", f.Message, name)
				}
			}
			if rules := rejectedRules(res.Findings); !reflect.DeepEqual(rules, []string{findings.RuleHostProbeLoginUnset}) {
				t.Errorf("rejections %v, want only %s", rules, findings.RuleHostProbeLoginUnset)
			}
			// What the refusal rests on: every planned node carries its own package's
			// pair, for both uses, in name order.
			wantPair := map[string][2]string{
				"e1": {eosUsernameEnv, eosPasswordEnv},
				"e2": {eosUsernameEnv, eosPasswordEnv},
				"s1": {"FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD"},
			}
			if len(res.Nodes) != 3 {
				t.Fatalf("nodes = %+v, want e1, e2 and s1", res.Nodes)
			}
			for i, n := range res.Nodes {
				if want := []string{"e1", "e2", "s1"}[i]; n.Name != want {
					t.Errorf("node %d = %s, want %s (sorted by name)", i, n.Name, want)
				}
				pair := wantPair[n.Name]
				got := [2]string{n.Probe.UsernameEnv, n.Probe.PasswordEnv}
				if got != pair {
					t.Errorf("%s probe login = %v, want %v from its own package", n.Name, got, pair)
				}
				if got := [2]string{n.Push.UsernameEnv, n.Push.PasswordEnv}; got != pair {
					t.Errorf("%s push login = %v, want %v from its own package", n.Name, got, pair)
				}
			}
		})
	}
}

// probePlans are the mixed golden's nodes as twin verify hands them to ProbeLoginsUnset: each
// node's own package's readiness probe, and no push.
func probePlans(t *testing.T) []wire.NodePlan {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	m, err := readManifest(mixedBundle())
	if err != nil {
		t.Fatal(err)
	}
	var plans []wire.NodePlan
	for _, n := range m.Nodes {
		p, ok := reg.LookupID(n.PSP.ID)
		if !ok {
			t.Fatalf("no package %s", n.PSP.ID)
		}
		plans = append(plans, wire.NodePlan{Name: n.Name, PSPID: n.PSP.ID, Probe: verify.ReadinessProbe(p)})
	}
	return plans
}

// twin verify refuses an unset probe login in the host check's words, through the one
// sentence both give, naming the variable and the package whose nodes need it and never a
// value; a push login is not its business.
func TestProbeLoginsUnset(t *testing.T) {
	t.Run("the second platform's password unset", func(t *testing.T) {
		env := bothLogins()
		delete(env, eosPasswordEnv)
		got := ProbeLoginsUnset(probePlans(t), mapEnv(env))
		if len(got) != 1 {
			t.Fatalf("findings %v, want one", got)
		}
		f := got[0]
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleHostProbeLoginUnset, Object: eosPasswordEnv,
			Message: eosPasswordEnv + " is unset on this worker; support package arista_eos names it for its readiness probe login"}
		if f != want {
			t.Errorf("finding = %+v\nwant      %+v (its step the caller's)", f, want)
		}
		// The host check's sentence for the same environment is the same sentence, with the
		// push use the package names the variable for too.
		a := mixedActivities(t, &fakeImages{held: map[string]bool{"ceos:4.32.0.2F": true}})
		a.Getenv = mapEnv(env)
		res := checkBundle(t, a, mixedBundle())
		if hc := only(t, res.Findings, findings.RuleHostProbeLoginUnset); hc.Message != f.Message+" and its push login" {
			t.Errorf("the host check says\n  %q\nProbeLoginsUnset\n  %q", hc.Message, f.Message)
		}
		// Given the plans the host check builds, push and all, it names the probe alone.
		if full := ProbeLoginsUnset(res.Nodes, mapEnv(env)); len(full) != 1 || full[0] != want {
			t.Errorf("over the host check's plans: %v, want %+v", full, want)
		}
		for _, v := range []string{"admin", "not-the-real-one"} {
			if strings.Contains(f.Message, v) {
				t.Errorf("message %q carries a value", f.Message)
			}
		}
	})
	t.Run("both set", func(t *testing.T) {
		if got := ProbeLoginsUnset(probePlans(t), mapEnv(bothLogins())); len(got) != 0 {
			t.Errorf("findings %v, want none", got)
		}
	})
	t.Run("a push login alone unset", func(t *testing.T) {
		plans := probePlans(t)
		for i := range plans {
			plans[i].Push = wire.PushSpec{UsernameEnv: "PUSH_ONLY_USERNAME", PasswordEnv: "PUSH_ONLY_PASSWORD"}
		}
		if got := ProbeLoginsUnset(plans, mapEnv(bothLogins())); len(got) != 0 {
			t.Errorf("findings %v, want none: a push login is not the probe's", got)
		}
	})
}
