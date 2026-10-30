package provision

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"io/fs"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// inspectRunner answers every containerlab call with one recorded reply and
// remembers what it was asked.
type inspectRunner struct {
	stdout, stderr []byte
	exit           int
	calls          [][]string
}

func (r *inspectRunner) Run(_ context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	r.calls = append(r.calls, args)
	return r.stdout, r.stderr, r.exit, nil
}

// reportActivities are the host-bound activities a worker starts with: the shipped packages,
// a fresh state root, containerlab answering with the recorded output named, and env as the
// worker's environment.
func reportActivities(t *testing.T, recording string, env map[string]string) (*lab.Activities, *inspectRunner) {
	t.Helper()
	runner := &inspectRunner{}
	if recording != "" {
		b, err := os.ReadFile(filepath.Join("..", "lab", "testdata", recording))
		if err != nil {
			t.Fatal(err)
		}
		runner.stdout = b
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	probes, err := probe.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return &lab.Activities{
		Clab:     &lab.Clab{Runner: runner, Log: slog.New(slog.NewTextHandler(io.Discard, nil))},
		Paths:    lab.PathsAt(t.TempDir()),
		Registry: reg,
		Probes:   probes,
		// The host holds every imported image and the probe package's unless a test says
		// otherwise, which is the state a lab host serves in.
		Images: heldImages{"ceos:4.32.0.2F": true, "alpine:3.24.2": true},
		Getenv: func(k string) (string, bool) {
			v, ok := env[k]
			return v, ok
		},
	}, runner
}

// heldImages is the references a host is pretending to hold.
type heldImages map[string]bool

func (h heldImages) Present(_ context.Context, ref string) (bool, error) { return h[ref], nil }

// unreadableImages is a container runtime that will not answer.
type unreadableImages struct{ err error }

func (u unreadableImages) Present(context.Context, string) (bool, error) { return false, u.err }

// probeLogin is a worker environment carrying every shipped platform's probe login, as
// a lab host's must from M7 on: the two platforms name different variables, so one
// worker holds both pairs.
var probeLogin = map[string]string{
	"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": "not-the-real-one",
	"FYLGJA_EOS_USERNAME": "admin", "FYLGJA_EOS_PASSWORD": "not-the-real-one-either",
}

// On a clear host the worker says what it serves, where its state is, that no budget is
// set, that the probe login is set, and that the host holds no twin — and it only looked.
func TestStartupReportClearHost(t *testing.T) {
	acts, runner := reportActivities(t, "inspect-empty.json", probeLogin)
	root := acts.Paths.Root

	got := StartupReport(context.Background(), acts, "localhost:7233", "default")
	want := []string{
		"fylgja worker: serving task queue fylgja at localhost:7233 (namespace default)",
		"fylgja worker: state root " + root + " (bundles: " + filepath.Join(root, "bundles") + ", snapshots: " + filepath.Join(root, "snapshots") +
			", twin: " + filepath.Join(root, "twin") + ")",
		"fylgja worker: host memory budget: unset (memory sums will be warnings)",
		// Every shipped package, in NOS order, each with its own login and its own
		// mechanism: the report is written from the packages, so the second platform
		// appears here without a line of it being named in the code.
		"fylgja worker: probe login arista_eos: FYLGJA_EOS_USERNAME set, FYLGJA_EOS_PASSWORD set",
		"fylgja worker: arista_eos (embedded): image ceos:4.32.0.2F (account_gated, present on this host), " +
			"push eapi replace over https:443, login FYLGJA_EOS_USERNAME/FYLGJA_EOS_PASSWORD (probe and push)",
		"fylgja worker: probe login nokia_srlinux: FYLGJA_SRLINUX_USERNAME set, FYLGJA_SRLINUX_PASSWORD set",
		"fylgja worker: nokia_srlinux (embedded): image ghcr.io/nokia/srlinux:24.7.1, push json_rpc replace over https:443, " +
			"login FYLGJA_SRLINUX_USERNAME/FYLGJA_SRLINUX_PASSWORD (probe and push)",
		// The probe package beside them (016, R-08), its image asked after whatever its
		// acquisition, as the host check asks.
		"fylgja worker: ping (embedded): image alpine:3.24.2 (public_registry, present on this host), flow ping every 0.2s, burst 5",
		"fylgja worker: host: lab fylgja absent; twin directory absent",
	}
	if !slices.Equal(got, want) {
		t.Errorf("report:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if len(runner.calls) != 1 || !slices.Equal(runner.calls[0], []string{"clab", "inspect", "--all", "--format", "json"}) {
		t.Errorf("containerlab calls %v, want only inspect --all", runner.calls)
	}
	if entries, err := os.ReadDir(root); err != nil || len(entries) != 0 {
		t.Errorf("state root holds %v (%v) after the report, want nothing created", entries, err)
	}
}

// A probe package's image is asked after whatever its acquisition, since no run pulls it
// (016, R-12): absent, its line names the pull a create needs first; a runtime that will
// not answer is reported, never guessed at. No probe registry, no line.
func TestStartupReportNamesTheProbeImage(t *testing.T) {
	probes, err := probe.Load("")
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		label  string
		images lab.Images
		want   string
	}{
		{"present", heldImages{"alpine:3.24.2": true},
			"ping (embedded): image alpine:3.24.2 (public_registry, present on this host), flow ping every 0.2s, burst 5"},
		{"absent", heldImages{},
			"ping (embedded): image alpine:3.24.2 (public_registry, absent from this host; a create needing it is refused " +
				"until docker pull alpine:3.24.2 fetches it), flow ping every 0.2s, burst 5"},
		{"no image driver", nil,
			"ping (embedded): image alpine:3.24.2 (public_registry, image presence not checked: this worker has no image driver), " +
				"flow ping every 0.2s, burst 5"},
	} {
		t.Run(tc.label, func(t *testing.T) {
			got := ProbePackageLines(context.Background(), probes, tc.images)
			if !slices.Equal(got, []string{tc.want}) {
				t.Errorf("lines %q, want %q", got, tc.want)
			}
		})
	}
	if got := ProbePackageLines(context.Background(), nil, heldImages{}); got != nil {
		t.Errorf("no probe registry reports %q, want nothing", got)
	}
}

// A lab or a twin directory on the host is reported with the remedy, and acted on by
// nothing (Constitution VII: orphan detection at worker start).
func TestStartupReportNamesWhatTheHostHolds(t *testing.T) {
	t.Run("lab present, budget set", func(t *testing.T) {
		acts, _ := reportActivities(t, "inspect-three.json", map[string]string{
			"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": "x", "FYLGJA_HOST_MEMORY_MB": "4096",
		})
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, 2, "fylgja worker: host memory budget: 4096 MiB")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja present (3 nodes); twin directory absent; "+
			"an orphan: no twin.json records it; deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml; fylgja twin destroy clears it")
	})
	t.Run("twin directory present", func(t *testing.T) {
		acts, _ := reportActivities(t, "inspect-empty.json", probeLogin)
		if err := os.MkdirAll(acts.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja absent; twin directory present; "+
			"a leftover twin directory: no twin.json and no lab fylgja; fylgja twin destroy clears it")
		if _, err := os.Stat(acts.Paths.Twin); err != nil {
			t.Errorf("the twin directory is gone after the report: %v", err)
		}
	})
	for _, tc := range []struct{ label, at, phrase string }{
		{"twin recorded, unpinned", "", "the twin of branch fylgja-fixture" + recordedIDs + ", 3 nodes recorded"},
		{"twin recorded, pinned", "2026-09-16T14:00:00Z", "the twin of branch fylgja-fixture at 2026-09-16T14:00:00Z" + recordedIDs + ", 3 nodes recorded"},
	} {
		t.Run(tc.label, func(t *testing.T) {
			acts, runner := reportActivities(t, "inspect-three.json", probeLogin)
			before := recordTwin(t, acts, tc.at)
			got := StartupReport(context.Background(), acts, "localhost:7233", "default")
			wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja present (3 nodes); twin directory present; "+
				tc.phrase+"; fylgja twin destroy clears it")
			actedOnNothing(t, acts, runner, before)
		})
	}
	t.Run("record without a lab", func(t *testing.T) {
		acts, runner := reportActivities(t, "inspect-empty.json", probeLogin)
		before := recordTwin(t, acts, "")
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja absent; twin directory present; "+
			"the twin of branch fylgja-fixture"+recordedIDs+", 3 nodes recorded, but lab fylgja is absent; fylgja twin destroy clears it")
		actedOnNothing(t, acts, runner, before)
	})
	t.Run("budget not a number", func(t *testing.T) {
		acts, _ := reportActivities(t, "inspect-empty.json", map[string]string{"FYLGJA_HOST_MEMORY_MB": "lots"})
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		if !strings.HasPrefix(got[2], "fylgja worker: host memory budget: invalid: ") {
			t.Errorf("budget line %q, want it reported invalid", got[2])
		}
	})
	t.Run("containerlab failing", func(t *testing.T) {
		acts, runner := reportActivities(t, "", probeLogin)
		runner.exit, runner.stderr = 1, []byte("permission denied")
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		if last := got[len(got)-1]; !strings.HasPrefix(last, "fylgja worker: host: not inspected: ") || !strings.Contains(last, "permission denied") {
			t.Errorf("host line %q, want the inspection failure reported", last)
		}
	})
}

// The identities a recorded twin carries in these tests, in full, as the phrase names them.
const (
	recordedBundleID = "893b6392da4f1de868e74e418d90f3d5982ecc06ffa1dc39a391d717a81997ad"
	recordedRunID    = "01a0a698-fc78-7cb5-b0f1-a31c8f06d7e9"
	recordedIDs      = ", bundle_id " + recordedBundleID + ", provisioned by run fylgja-provision " + recordedRunID
)

// recordTwin writes twin.json under acts' state root as RecordTwin leaves it — through
// NewRecord and WriteRecord, three nodes, the reference pinned to at unless at is empty —
// and returns the file's bytes.
func recordTwin(t *testing.T, acts *lab.Activities, at string) []byte {
	t.Helper()
	observed := "2026-09-16T13:59:30.000000Z"
	f := lab.RecordFields{
		BundleID:   recordedBundleID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: at, SchemaHash: "41349c3a", Scope: "tag:fylgja", Mapping: dcimMapping},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      recordedRunID,
		Version:    "0.1.0-test",
		RecordedAt: time.Date(2026, 9, 16, 14, 1, 2, 0, time.UTC),
	}
	for _, n := range []string{"n1", "n2", "n3"} {
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n, Image: "ghcr.io/nokia/srlinux:24.7.1",
			PSP: &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}})
	}
	rec, err := lab.NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return writeTwinJSON(t, acts, nil, &rec)
}

// writeTwinJSON creates the twin directory and writes twin.json: raw bytes when rec is
// nil, else the record through WriteRecord. It returns the file's bytes.
func writeTwinJSON(t *testing.T, acts *lab.Activities, raw []byte, rec *wire.TwinRecord) []byte {
	t.Helper()
	if err := os.MkdirAll(acts.Paths.Twin, 0o755); err != nil {
		t.Fatal(err)
	}
	var err error
	if rec != nil {
		err = lab.WriteRecord(acts.Paths.TwinJSON, *rec)
	} else {
		err = os.WriteFile(acts.Paths.TwinJSON, raw, 0o644)
	}
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(acts.Paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// actedOnNothing checks the worker only looked: containerlab was asked nothing but
// inspect, and twin.json holds twinJSON still (nil: there was none, and there is none).
func actedOnNothing(t *testing.T, acts *lab.Activities, runner *inspectRunner, twinJSON []byte) {
	t.Helper()
	for _, c := range runner.calls {
		if !slices.Equal(c, []string{"clab", "inspect", "--all", "--format", "json"}) {
			t.Errorf("containerlab was asked %v, want only inspect --all", c)
		}
	}
	b, err := os.ReadFile(acts.Paths.TwinJSON)
	switch {
	case twinJSON == nil && !errors.Is(err, fs.ErrNotExist):
		t.Errorf("twin.json after the report: %q, %v; want none", b, err)
	case twinJSON != nil && (err != nil || !bytes.Equal(b, twinJSON)):
		t.Errorf("twin.json changed: %q, %v; want %q", b, err, twinJSON)
	}
}

// A worker started beside an orphan says so — node count, and the topology the containers
// came from — or that a run was cut short, or that twin.json could not be read and why, and
// acts on none of it.
func TestStartupReportNamesAnOrphan(t *testing.T) {
	const orphanLine = "fylgja worker: host: lab fylgja present (1 node); twin directory absent; " +
		"an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml; fylgja twin destroy clears it"

	t.Run("(c) orphan", func(t *testing.T) {
		acts, runner := reportActivities(t, "inspect-one-orphan.json", probeLogin)
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, orphanLine)
		actedOnNothing(t, acts, runner, nil)
		if _, err := os.Lstat(acts.Paths.Twin); !errors.Is(err, fs.ErrNotExist) {
			t.Errorf("a twin directory exists after the report (%v), want none", err)
		}
	})
	t.Run("(d) cut short", func(t *testing.T) {
		acts, runner := reportActivities(t, "inspect-three.json", probeLogin)
		if err := os.MkdirAll(acts.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja present (3 nodes); twin directory present; "+
			"an orphan: no twin.json records it (a run cut short before it recorded the twin); "+
			"deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml; fylgja twin destroy clears it")
		actedOnNothing(t, acts, runner, nil)
		if entries, err := os.ReadDir(acts.Paths.Twin); err != nil || len(entries) != 0 {
			t.Errorf("twin directory holds %v (%v) after the report, want it as it was: empty", entries, err)
		}
	})
	t.Run("(e) unreadable record", func(t *testing.T) {
		acts, runner := reportActivities(t, "inspect-three.json", probeLogin)
		before := writeTwinJSON(t, acts, []byte("{"), nil)
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja present (3 nodes); twin directory present; "+
			"treated as an orphan: twin.json could not be read (reading "+acts.Paths.TwinJSON+": unexpected end of JSON input); "+
			"deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml; fylgja twin destroy clears it")
		actedOnNothing(t, acts, runner, before)
	})
	t.Run("(g) leftover, unreadable record", func(t *testing.T) {
		acts, runner := reportActivities(t, "inspect-empty.json", probeLogin)
		before := writeTwinJSON(t, acts, []byte("{"), nil)
		got := StartupReport(context.Background(), acts, "localhost:7233", "default")
		wantLine(t, got, len(got)-1, "fylgja worker: host: lab fylgja absent; twin directory present; "+
			"a leftover twin directory: twin.json could not be read (reading "+acts.Paths.TwinJSON+": unexpected end of JSON input), "+
			"and lab fylgja is absent; fylgja twin destroy clears it")
		actedOnNothing(t, acts, runner, before)
	})
}

// The phrase the worker's host line carries is the phrase both host.* refusals carry for
// the same host, from the same inspection: three surfaces, one function.
func TestHostLineAndRefusalsCarryOnePhrase(t *testing.T) {
	ctx := context.Background()
	for _, tc := range []struct {
		label, recording string
		setup            func(t *testing.T, acts *lab.Activities)
	}{
		{"(a) twin", "inspect-three.json", func(t *testing.T, acts *lab.Activities) { recordTwin(t, acts, "2026-09-16T14:00:00Z") }},
		{"(b) record without a lab", "inspect-empty.json", func(t *testing.T, acts *lab.Activities) { recordTwin(t, acts, "") }},
		{"(c) orphan", "inspect-one-orphan.json", func(*testing.T, *lab.Activities) {}},
		{"(d) cut short", "inspect-three.json", func(t *testing.T, acts *lab.Activities) {
			if err := os.MkdirAll(acts.Paths.Twin, 0o755); err != nil {
				t.Fatal(err)
			}
		}},
		{"(e) unreadable record", "inspect-three.json", func(t *testing.T, acts *lab.Activities) { writeTwinJSON(t, acts, []byte("{"), nil) }},
		{"(f) leftover", "inspect-empty.json", func(t *testing.T, acts *lab.Activities) {
			if err := os.MkdirAll(acts.Paths.Twin, 0o755); err != nil {
				t.Fatal(err)
			}
		}},
		{"(g) leftover, unreadable record", "inspect-empty.json", func(t *testing.T, acts *lab.Activities) { writeTwinJSON(t, acts, []byte("{"), nil) }},
	} {
		t.Run(tc.label, func(t *testing.T) {
			acts, _ := reportActivities(t, tc.recording, probeLogin)
			tc.setup(t, acts)
			host, err := acts.InspectHost(ctx)
			if err != nil {
				t.Fatal(err)
			}
			phrase := host.Describe()
			if phrase == "" {
				t.Fatal("no phrase for a host that holds something")
			}

			report := StartupReport(ctx, acts, "localhost:7233", "default")
			if n := strings.Count(report[len(report)-1], phrase); n != 1 {
				t.Errorf("host line %q carries the phrase %d times, want once:\n  %q", report[len(report)-1], n, phrase)
			}
			res, err := lab.CheckHost(ctx, acts, wire.CheckHostInput{BundlePath: repoPath("testdata", "golden", "three-node")})
			if err != nil {
				t.Fatal(err)
			}
			refusals := 0
			for _, f := range res.Findings {
				if f.Rule != findings.RuleHostLabPresent && f.Rule != findings.RuleHostTwinPresent {
					continue
				}
				refusals++
				if !strings.Contains(f.Message, phrase) {
					t.Errorf("%s message %q does not carry the host line's phrase %q", f.Rule, f.Message, phrase)
				}
			}
			if refusals == 0 {
				t.Errorf("findings %+v: no host.lab.present or host.twin.present to carry the phrase", res.Findings)
			}
		})
	}
}

// The login is named, never shown: a password set to a sentinel appears in no line, and an
// unset username is reported as unset.
func TestStartupReportNamesLoginVariablesOnly(t *testing.T) {
	const sentinel = "sentinel-probe-password-7c1e"
	acts, _ := reportActivities(t, "inspect-empty.json", map[string]string{"FYLGJA_SRLINUX_PASSWORD": sentinel})

	got := StartupReport(context.Background(), acts, "localhost:7233", "default")
	// One line per shipped package, in NOS order: the platform whose variables this
	// worker does not carry says so of both, and nothing about either is inferred from
	// the other.
	wantLine(t, got, 3, "fylgja worker: probe login arista_eos: FYLGJA_EOS_USERNAME unset, FYLGJA_EOS_PASSWORD unset")
	wantLine(t, got, 5, "fylgja worker: probe login nokia_srlinux: FYLGJA_SRLINUX_USERNAME unset, FYLGJA_SRLINUX_PASSWORD set")
	for _, line := range got {
		if strings.Contains(line, sentinel) {
			t.Errorf("the probe password appeared in %q", line)
		}
	}
}

func wantLine(t *testing.T, lines []string, i int, want string) {
	t.Helper()
	if i < 0 || i >= len(lines) {
		t.Fatalf("report has %d lines, want line %d = %q:\n%s", len(lines), i, want, strings.Join(lines, "\n"))
	}
	if lines[i] != want {
		t.Errorf("line %d = %q, want %q", i, lines[i], want)
	}
}

// The workflows schedule activities by the wire.Act* names and NewWorker registers them
// from one table, lab.Activities.Names; nothing joins the two sides before a live run. The workflow tests register their own mocks by name, so a name
// dropped from the table would pass every tier-1 and tier-2 test and fail at the first
// live run with the SDK's "unable to find activityType", which only tier 3 — never run in
// CI — would show. This pins the seam without a server.
func TestWorkerRegistersEveryScheduledActivity(t *testing.T) {
	// Every activity name constant, by identifier, so a name parsed from a workflow file can
	// be matched to its value. A new wire.Act* constant must be added here too, which the
	// scheduled-names check below enforces.
	constants := map[string]string{
		"ActCheckHost":      wire.ActCheckHost,
		"ActStageBundle":    wire.ActStageBundle,
		"ActDeployLab":      wire.ActDeployLab,
		"ActAwaitReadiness": wire.ActAwaitReadiness,
		"ActRecordTwin":     wire.ActRecordTwin,
		"ActPlanTeardown":   wire.ActPlanTeardown,
		"ActDestroyLab":     wire.ActDestroyLab,
		"ActUnstageTwin":    wire.ActUnstageTwin,
		// M4.
		"ActInspectTwin": wire.ActInspectTwin,
		// M5.
		"ActPushConfig": wire.ActPushConfig,
		// M11: the step run's own.
		"ActPlanReconcile": wire.ActPlanReconcile,
		"ActStageStep":     wire.ActStageStep,
		"ActReconcileLab":  wire.ActReconcileLab,
		"ActRecordStep":    wire.ActRecordStep,
		// M12: the step's wait.
		"ActVerifyTwin": wire.ActVerifyTwin,
		// 016: the step's flows.
		"ActStartFlows": wire.ActStartFlows,
		"ActReadFlows":  wire.ActReadFlows,
	}
	all := slices.Sorted(maps.Values(constants))
	if len(all) != 17 {
		t.Fatalf("%d activity names, want the seventeen: M2's eight host-bound, M4's InspectTwin, M5's push, "+
			"M11's four (PlanReconcile, StageStep, ReconcileLab, RecordStep), M12's VerifyTwin and 016's "+
			"StartFlows and ReadFlows", len(all))
	}
	// The table, from a zero-value receiver: registration needs the method values only.
	registered := map[string]bool{}
	for name, method := range (&lab.Activities{}).Names() {
		if method == nil {
			t.Errorf("activity %q is registered as nil", name)
		}
		registered[name] = true
	}
	if got := slices.Sorted(maps.Keys(registered)); !slices.Equal(got, all) {
		t.Errorf("the worker registers %v\nwant every activity name: %v", got, all)
	}

	// The names the workflow files schedule, by the identifiers they use.
	scheduled := map[string]bool{}
	files, err := filepath.Glob("workflow_*.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range files {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		fset := token.NewFileSet()
		f, err := parser.ParseFile(fset, name, nil, 0)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		ast.Inspect(f, func(n ast.Node) bool {
			// wire.Act*: every activity is host-bound since 019.
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			pkg, ok := sel.X.(*ast.Ident)
			if !ok || pkg.Name != "wire" || !strings.HasPrefix(sel.Sel.Name, "Act") {
				return true
			}
			value, known := constants[sel.Sel.Name]
			if !known {
				t.Errorf("%s schedules wire.%s, which this test does not know; add it to constants",
					fset.Position(sel.Pos()), sel.Sel.Name)
				return true
			}
			scheduled[value] = true
			return false
		})
	}
	if got := slices.Sorted(maps.Keys(scheduled)); !slices.Equal(got, all) {
		t.Errorf("the workflow files schedule %v\nwant every activity name: %v", got, all)
	}
	for name := range scheduled {
		if !registered[name] {
			t.Errorf("the workflows schedule %q, which the table does not register", name)
		}
	}

	// The three workflows the server starts, and no other (M11 adds the step; 019 removes the
	// check; 020 the rehearsal, which the orchestrator runs). The SDK offers no listing, but it refuses to register a workflow name
	// twice (SDK v1.49.0, internal/internal_worker.go, RegisterWorkflowWithOptions: a
	// present workflowFuncMap entry panics "workflow name ... is already registered"), so a
	// refused second registration is its word that the first happened. A lazy client dials
	// nothing, and worker.New accepts it (internal/worker.go, NewWorker).
	c, err := client.NewLazyClient(client.Options{HostPort: "localhost:1"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	w := NewWorker(c, &lab.Activities{})
	for name, wf := range map[string]any{"Provision": Provision, "Destroy": Destroy, "Step": Step} {
		if msg := panics(func() { w.RegisterWorkflow(wf) }); !strings.Contains(msg, fmt.Sprintf("workflow name %q is already registered", name)) {
			t.Errorf("registering %s again: %q; want the SDK to refuse it as already registered by NewWorker", name, msg)
		}
	}
	// The check an earlier build's Schedule started, by the type name Reconcile, and the
	// rehearsal an earlier build served, by the type name Rehearse, are not served: the SDK
	// takes a first registration under either name.
	for _, name := range []string{"Reconcile", "Rehearse"} {
		gone := func(workflow.Context) error { return nil }
		if msg := panics(func() { w.RegisterWorkflowWithOptions(gone, workflow.RegisterOptions{Name: name}) }); msg != "" {
			t.Errorf("registering a workflow as %s: %q; want it taken, since NewWorker registers none", name, msg)
		}
	}
}

// panics runs fn and returns what it panicked with, or "" when it returned.
func panics(fn func()) (msg string) {
	defer func() {
		if r := recover(); r != nil {
			msg = fmt.Sprint(r)
		}
	}()
	fn()
	return ""
}

// A push login of its own is named with whether each variable is set, as the probe's is;
// one shared with the probe is named once (M5 contracts/cli.md, worker run).
// The image an operator must import by hand is reported present, absent or unreadable,
// and the worker serves in all three: a create that needs it is refused at its host
// check, not by refusing to start. A registry image's line is
// M5's, with no state at all.
func TestStartupReportNamesTheImportedImagesState(t *testing.T) {
	const eos = "fylgja worker: arista_eos (embedded): image ceos:4.32.0.2F (account_gated, %s), " +
		"push eapi replace over https:443, login FYLGJA_EOS_USERNAME/FYLGJA_EOS_PASSWORD (probe and push)"
	const srlinux = "fylgja worker: nokia_srlinux (embedded): image ghcr.io/nokia/srlinux:24.7.1, " +
		"push json_rpc replace over https:443, login FYLGJA_SRLINUX_USERNAME/FYLGJA_SRLINUX_PASSWORD (probe and push)"

	for _, c := range []struct {
		name   string
		images lab.Images
		want   string
	}{
		{"present", heldImages{"ceos:4.32.0.2F": true}, fmt.Sprintf(eos, "present on this host")},
		{"absent", heldImages{}, fmt.Sprintf(eos, "absent from this host; a create needing it is refused")},
		{"the runtime would not answer", unreadableImages{errors.New(`docker image inspect --format {{.Id}} ceos:4.32.0.2F: exec: "docker": executable file not found in $PATH`)},
			fmt.Sprintf(eos, `image presence not checked: docker image inspect --format {{.Id}} ceos:4.32.0.2F: exec: "docker": executable file not found in $PATH`)},
		{"no image driver at all", nil, fmt.Sprintf(eos, "image presence not checked: this worker has no image driver")},
	} {
		t.Run(c.name, func(t *testing.T) {
			acts, _ := reportActivities(t, "inspect-empty.json", probeLogin)
			acts.Images = c.images
			got := StartupReport(context.Background(), acts, "localhost:7233", "default")
			if !slices.Contains(got, c.want) {
				t.Errorf("report:\n%s\ndoes not carry:\n%s", strings.Join(got, "\n"), c.want)
			}
			// The worker still reports everything else and serves: the queue line opens the
			// report and the host line closes it, whatever the runtime said.
			if !slices.Contains(got, srlinux) {
				t.Errorf("report:\n%s\ndoes not carry the registry package's M5 line:\n%s", strings.Join(got, "\n"), srlinux)
			}
			if got[len(got)-1] != "fylgja worker: host: lab fylgja absent; twin directory absent" {
				t.Errorf("last line %q, want the host line: the report is complete either way", got[len(got)-1])
			}
		})
	}
}

func TestPackageLineNamesAPushLoginOfItsOwn(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	shipped, _ := reg.LookupID("nokia_srlinux")
	p := *shipped
	push := *p.Config.Push
	push.Login = psp.Login{UsernameEnv: "PUSH_USER", PasswordEnv: "PUSH_PASS"}
	p.Config.Push = &push
	got := packageLine(context.Background(), &p, heldImages{}, func(k string) (string, bool) { return "x", k == "PUSH_USER" })
	want := "nokia_srlinux (embedded): image ghcr.io/nokia/srlinux:24.7.1, push json_rpc replace over https:443, " +
		"login PUSH_USER set, PUSH_PASS unset (push)"
	if got != want {
		t.Errorf("package line = %q\nwant %q", got, want)
	}
}

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}
