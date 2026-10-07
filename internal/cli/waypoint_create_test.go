package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// The waypoints the create tests resolve, on the fixture branch. demo/2's at is the
// fixture's own, so a read of it is the fixture; demo/1's is the time its branch attribute
// was written. The rest each draw one refusal.
const (
	demoWrittenAt = "2026-09-20T10:00:00.123456+00:00"
	fixtureAt     = "2026-09-08T12:00:00Z"
)

func demoInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	f.waypoint("wp-demo-1", "demo", 1, "fylgja-fixture", demoWrittenAt, "", "before the change")
	f.waypoint("wp-demo-2", "demo", 2, "fylgja-fixture", demoWrittenAt, fixtureAt, "after the first cut-over")
	f.waypoint("wp-demo-5", "demo", 5, "fylgja-fixture", demoWrittenAt, "2099-01-01T00:00:00Z", "")
	f.waypoint("wp-demo-6", "demo", 6, "fylgja-fixture", demoWrittenAt, "2026-09-20T10:00:00.123456789Z", "")
	f.waypoint("wp-demo-7b", "demo", 7, "fylgja-fixture", demoWrittenAt, "", "")
	f.waypoint("wp-demo-7a", "demo", 7, "fylgja-fixture", demoWrittenAt, "", "")
	f.waypoint("wp-alpha-1", "alpha", 1, "main", demoWrittenAt, "", "")
	return f
}

// executeTwin runs `fylgja <args> --json` through the command line, as an operator would,
// and returns its exit status and findings document.
func executeTwin(t *testing.T, args ...string) (int, *findings.Document) {
	t.Helper()
	opts := &options{asJSON: true}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts), newIntentCmd(opts))
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

// mustCarryNoToken fails when the credential reached a document or a line.
func mustCarryNoToken(t *testing.T, label string, outputs ...any) {
	t.Helper()
	for _, o := range outputs {
		b, err := json.Marshal(o)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), fakeToken) {
			t.Errorf("%s carries the credential: %s", label, b)
		}
	}
}

// Before any connection, a reference that is not the form, or a flag a waypoint makes
// meaningless, is refused at step start, exit 2, with the workflow service never dialled
// and Infrahub never asked; neither flag given is M1's usage failure with the message both
// commands now share (contracts/cli.md). An explicitly empty --waypoint= is
// a reference that is not the form, alone or beside --branch, and on the dry run too: never
// the flag left out, which beside --branch would start a following create.
func TestCreateWaypointRefusedBeforeAnyConnection(t *testing.T) {
	const whole = "a waypoint is a whole pinned reference (branch and at)"
	emptyRef := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointRefInvalid, Object: "", Step: findings.StepStart,
		Message: `--waypoint "" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`}
	for _, c := range []struct {
		name string
		args []string
		want findings.Finding
	}{
		{"neither", nil, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed,
			Object: findings.OpTwinCreate, Message: "--branch or --waypoint is required"}},
		{"not a reference", []string{"--waypoint", "demo"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointRefInvalid, Object: "demo", Step: findings.StepStart,
			Message: `--waypoint "demo" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`}},
		{"a leading zero", []string{"--waypoint", "demo/02", "--branch", "x"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointRefInvalid, Object: "demo/02", Step: findings.StepStart,
			Message: `--waypoint "demo/02" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`}},
		{"--waypoint= alone", []string{"--waypoint="}, emptyRef},
		{"--waypoint= beside --branch", []string{"--branch", "fylgja-fixture", "--waypoint="}, emptyRef},
		{"--waypoint= alone, dry run", []string{"--waypoint=", "--dry-run"}, emptyRef},
		{"--waypoint= beside --branch, dry run", []string{"--branch", "fylgja-fixture", "--waypoint=", "--dry-run"}, emptyRef},
		{"--branch", []string{"--waypoint", "demo/2", "--branch", "change-1"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointFlagsConflict, Object: "--branch", Step: findings.StepStart,
			Message: "--branch is meaningless with --waypoint: " + whole}},
		{"--at", []string{"--waypoint", "demo/2", "--at", fixtureAt}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointFlagsConflict, Object: "--at", Step: findings.StepStart,
			Message: "--at is meaningless with --waypoint: " + whole}},
		{"--interval", []string{"--waypoint", "demo/2", "--interval", "1m"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointFlagsConflict, Object: "--interval", Step: findings.StepStart,
			Message: "--interval is meaningless with --waypoint: a waypoint twin is pinned and never follows"}},
		{"--interval empty", []string{"--waypoint", "demo/2", "--interval="}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleWaypointFlagsConflict, Object: "--interval", Step: findings.StepStart,
			Message: "--interval is meaningless with --waypoint: a waypoint twin is pinned and never follows"}},
		{"the first found", []string{"--waypoint", "demo/2", "--interval", "1m", "--at", fixtureAt, "--branch", "change-1"},
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointFlagsConflict, Object: "--branch",
				Step: findings.StepStart, Message: "--branch is meaningless with --waypoint: " + whole}},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := demoInfrahub(t)
			f.start()

			code, doc := executeTwin(t, append([]string{"twin", "create"}, c.args...)...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != c.want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, c.want)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			if doc.Waypoint != nil {
				t.Errorf("a refusal before resolution carries the waypoint block %+v", doc.Waypoint)
			}
			// A reference that parses is named in the subject; one that does not is not,
			// since it names no waypoint.
			wantSubject := ""
			if c.want.Rule == findings.RuleWaypointFlagsConflict {
				wantSubject = "demo/2"
			}
			if got := subjectWaypoint(doc); got != wantSubject {
				t.Errorf("subject.waypoint = %q, want %q", got, wantSubject)
			}
			validateM10Document(t, doc)
		})
	}
}

func subjectWaypoint(doc *findings.Document) string {
	if doc.Subject == nil {
		return ""
	}
	return doc.Subject.Waypoint
}

// Each resolution refusal ends the create with its document and starts nothing: the rule,
// step resolve, the object and the exit contracts/cli.md gives, and subject.waypoint naming
// what was asked.
func TestCreateWaypointResolutionRefusals(t *testing.T) {
	for _, c := range []struct {
		name, ref   string
		setup       func(*fakeInfrahub)
		code        int
		rule, obj   string
		messageHas  string
		wantQueried bool
	}{
		{"kind absent", "demo/2", func(f *fakeInfrahub) { f.kind = nil }, findings.ExitRejected,
			findings.RuleWaypointKindAbsent, intent.WaypointKind,
			"the default branch's schema has no kind FylgjaWaypoint: load schema/fylgja-waypoint.yaml on it; only --waypoint, waypoint list and waypoint plan need it", false},
		{"a field missing", "demo/2", func(f *fakeInfrahub) { f.kind = []string{"series", "sequence", "branch", "description"} },
			findings.ExitRejected, findings.RuleWaypointKindAbsent, intent.WaypointKind,
			"kind FylgjaWaypoint on the default branch lacks the attribute as_of, which this build reads: load schema/fylgja-waypoint.yaml on it", false},
		{"unknown series", "beta/1", nil, findings.ExitRejected, findings.RuleWaypointUnknown, "beta",
			`no waypoint series "beta" exists; the series are: alpha, demo`, true},
		{"unknown sequence", "demo/3", nil, findings.ExitRejected, findings.RuleWaypointUnknown, "demo/3",
			"series demo has no waypoint 3; its sequences are 1, 2, 5, 6, 7", true},
		{"duplicate", "demo/7", nil, findings.ExitRejected, findings.RuleWaypointDuplicate, "demo/7",
			"waypoint demo/7 is held by 2 objects (ids wp-demo-7a, wp-demo-7b), which the kind's uniqueness constraint should have refused; none is chosen", true},
		{"a future at", "demo/5", nil, findings.ExitRejected, findings.RuleWaypointAtUnresolved, "demo/5",
			"waypoint demo/5 has at 2099-01-01T00:00:00Z (given), later than the current time ", true},
		// No as_of written and a null branch.updated_at: resolved, it would start a run of the
		// branch head that fails only at record.
		{"no at", "demo/8", func(f *fakeInfrahub) { f.waypoint("wp-demo-8", "demo", 8, "fylgja-fixture", "", "", "") },
			findings.ExitRejected, findings.RuleWaypointAtUnresolved, "demo/8",
			"waypoint demo/8 has no at: no as_of is written on it and Infrahub returned no updated_at for its branch attribute, so it names no point in time", true},
		{"nine digits", "demo/6", nil, findings.ExitError, findings.RuleAtPrecision, "demo/6",
			"waypoint demo/6: at 2026-09-20T10:00:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 (microseconds). Write the waypoint's as_of with at most six.", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := demoInfrahub(t)
			if c.setup != nil {
				c.setup(f)
			}
			f.start()

			code, doc := executeTwin(t, "twin", "create", "--waypoint", c.ref)
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with one %s", code, doc.Findings, c.code, c.rule)
			}
			got := doc.Findings[0]
			if got.Rule != c.rule || got.Step != findings.StepResolve || got.Object != c.obj || !strings.Contains(got.Message, c.messageHas) {
				t.Errorf("finding %+v; want %s at step resolve naming %s, saying %q", got, c.rule, c.obj, c.messageHas)
			}
			if doc.Subject == nil || doc.Subject.Waypoint != c.ref || doc.Subject.Branch != "" || doc.Subject.At != "" || doc.Waypoint != nil {
				t.Errorf("subject %+v, waypoint %+v; want subject.waypoint %s alone and no block", doc.Subject, doc.Waypoint, c.ref)
			}
			// The kind is checked before any query; nothing names a branch.
			var queried bool
			for _, r := range f.requests() {
				if r.Query != "" || (r.Path != "/api/schema" && r.Path != "/graphql") {
					t.Errorf("the resolution asked %+v; it reads the default branch alone", r)
				}
				queried = queried || r.Operation == "Waypoints"
			}
			if queried != c.wantQueried {
				t.Errorf("waypoints queried %v, want %v", queried, c.wantQueried)
			}
			mustCarryNoToken(t, c.name, doc)
			validateM10Document(t, doc)
		})
	}
}

// An Infrahub the resolution cannot reach, or a credential it lacks, is M1's
// operation.failed, exit 2, at step resolve: the reader's error as it is, never one of the
// six refusals, and no credential in it.
func TestCreateWaypointResolutionCannotRun(t *testing.T) {
	for _, c := range []struct {
		name, address, token, messageHas string
	}{
		{"unreachable", unreachable, fakeToken, "127.0.0.1:1"},
		{"no token", "http://127.0.0.1:1", "", "INFRAHUB_API_TOKEN is not set"},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			t.Setenv(intent.EnvAddress, c.address)
			t.Setenv(intent.EnvToken, c.token)

			code, doc := executeTwin(t, "twin", "create", "--waypoint", "demo/2")
			if code != findings.ExitError || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 2 with one operation.failed", code, doc.Findings)
			}
			got := doc.Findings[0]
			if got.Rule != findings.RuleOperationFailed || got.Step != findings.StepResolve || got.Object != findings.OpTwinCreate ||
				!strings.Contains(got.Message, c.messageHas) {
				t.Errorf("finding %+v; want operation.failed at step resolve saying %q", got, c.messageHas)
			}
			mustCarryNoToken(t, c.name, doc)
			validateM10Document(t, doc)
		})
	}
}

// A resolved create starts M2–M7's pinned run for the reference the waypoint names, with
// the waypoint as data and no following: the input carries branch and at as resolved and
// the waypoint, never Follow; --no-follow beside it changes nothing. The document names the
// waypoint in its subject and its block. The CLI reads nothing of the branch: the read is
// the run's.
func TestCreateFromAWaypoint(t *testing.T) {
	for _, c := range []struct {
		name  string
		args  []string
		at    string
		block findings.WaypointBlock
	}{
		{"given", []string{"--waypoint", "demo/2"}, fixtureAt, findings.WaypointBlock{Series: "demo", Sequence: 2,
			Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given", Description: "after the first cut-over"}},
		{"written", []string{"--waypoint", "demo/1"}, demoWrittenAt, findings.WaypointBlock{Series: "demo", Sequence: 1,
			Branch: "fylgja-fixture", At: demoWrittenAt, AtSource: "written", Description: "before the change"}},
		{"--no-follow", []string{"--waypoint", "demo/2", "--no-follow"}, fixtureAt, findings.WaypointBlock{Series: "demo", Sequence: 2,
			Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given", Description: "after the first cut-over"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useInterrupts(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			f := demoInfrahub(t)
			f.start()

			code, doc := executeTwin(t, append([]string{"twin", "create"}, c.args...)...)
			if code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			want := provision.ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", At: c.at, Version: version,
				StopFollowing: true, Waypoint: &provision.WaypointInput{Series: c.block.Series, Sequence: c.block.Sequence,
					Description: c.block.Description, AtSource: c.block.AtSource}}
			if len(svc.started) != 1 || !reflect.DeepEqual(svc.started[0], want) {
				t.Errorf("started %+v; want %+v", svc.started, want)
			}
			if doc.Waypoint == nil || *doc.Waypoint != c.block {
				t.Errorf("waypoint block %+v, want %+v", doc.Waypoint, c.block)
			}
			wantSubject := findings.Subject{Branch: "fylgja-fixture", At: c.at, Waypoint: fmt.Sprintf("%s/%d", c.block.Series, c.block.Sequence), RunID: "run-1"}
			if doc.Subject == nil || !reflect.DeepEqual(*doc.Subject, wantSubject) {
				t.Errorf("subject %+v, want %+v", doc.Subject, wantSubject)
			}
			if doc.Following != nil {
				t.Errorf("a waypoint twin carries a following block %+v", doc.Following)
			}
			for _, r := range f.requests() {
				if r.Path != "/api/schema" && r.Path != "/graphql" {
					t.Errorf("the CLI asked %+v; a create's read is the run's", r)
				}
			}
			mustCarryNoToken(t, c.name, doc, svc.started)
			validateM10Document(t, doc)
		})
	}
}

// A resolved create whose run refuses reports what the run reports, word for word what the
// create of the reference the waypoint names would say, with the waypoint beside it: M3's
// host refusals are the run's, unchanged, and a branch the waypoint still
// names after it was deleted is M1's refusal as the run reports it (a
// waypoint outlives its branch). No following block appears.
func TestCreateFromAWaypointWhoseRunRefuses(t *testing.T) {
	const twinDir = "/abs/local/twin"
	skipped := provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped}
	demo2 := findings.WaypointBlock{Series: "demo", Sequence: 2, Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given",
		Description: "after the first cut-over"}
	for _, c := range []struct {
		name   string
		result provision.ProvisionResult
		code   int
	}{
		{"host_check", provision.ProvisionResult{Outcome: provision.OutcomeRejected, BundleID: fixtureBundleID,
			Step: findings.StepHostCheck, Cleanup: skipped, Findings: findings.List{{Severity: findings.Rejection,
				Rule: findings.RuleHostTwinPresent, Object: twinDir, Step: findings.StepHostCheck,
				Message: "twin directory " + twinDir + " is present, the twin of branch fylgja-fixture at " + demoWrittenAt +
					", bundle_id " + fixtureBundleID + ", provisioned by run fylgja-provision run-0, 3 nodes recorded; " +
					"fylgja twin destroy clears it"}}}, findings.ExitRejected},
		{"read", provision.ProvisionResult{Outcome: provision.OutcomeError, Step: findings.StepRead, Cleanup: skipped,
			Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleOperationFailed,
				Object: "branch fylgja-fixture", Step: findings.StepRead,
				Message: "reading the schema (branch fylgja-fixture): HTTP 400: Branch: fylgja-fixture not found."}}},
			findings.ExitError},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useInterrupts(t)
			demoInfrahub(t).start()

			svc := &fakeService{runID: "run-1", result: c.result}
			useService(t, svc)
			code, doc := executeTwin(t, "twin", "create", "--waypoint", "demo/2")

			useService(t, &fakeService{runID: "run-1", result: c.result})
			refCode, ref := executeTwin(t, "twin", "create", "--branch", "fylgja-fixture", "--at", fixtureAt)

			if code != c.code || refCode != c.code {
				t.Errorf("exit %d, and %d by --branch --at; want %d", code, refCode, c.code)
			}
			if !reflect.DeepEqual(doc.Findings, ref.Findings) || !reflect.DeepEqual(doc.Findings, c.result.Findings) {
				t.Errorf("findings %+v\nby --branch --at %+v\nwant the run's %+v", doc.Findings, ref.Findings, c.result.Findings)
			}
			if doc.Waypoint == nil || *doc.Waypoint != demo2 {
				t.Errorf("waypoint block %+v, want %+v", doc.Waypoint, demo2)
			}
			wantSubject := *ref.Subject
			wantSubject.Waypoint = "demo/2"
			if doc.Subject == nil || !reflect.DeepEqual(*doc.Subject, wantSubject) {
				t.Errorf("subject %+v, want the --branch --at create's with the waypoint, %+v", doc.Subject, wantSubject)
			}
			if doc.Following != nil {
				t.Errorf("a waypoint twin's refusal carries a following block %+v", doc.Following)
			}
			if len(svc.started) != 1 || svc.started[0].Follow != nil || svc.started[0].Waypoint == nil {
				t.Errorf("started %+v; want one pinned run carrying the waypoint", svc.started)
			}
			mustCarryNoToken(t, c.name, doc, svc.started)
			validateM10Document(t, doc)
		})
	}
}

// The resolved reference is reported on one line before the run's first line (contracts/
// cli.md), and a refused one prints nothing on stdout.
func TestCreateFromAWaypointReportsTheReference(t *testing.T) {
	useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	demoInfrahub(t).start()

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{waypoint: "demo/2"})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	const line = `waypoint demo/2: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), "after the first cut-over"`
	if !strings.HasPrefix(out, line+"\nrun fylgja-provision run-1\n") {
		t.Errorf("stdout:\n%s\nwant it to begin with the waypoint line, then the run's", out)
	}
	if strings.Contains(out, fakeToken) {
		t.Errorf("stdout carries the credential:\n%s", out)
	}

	out = captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{waypoint: "demo/3"})
	})
	if code, _ := exitOf(t, err); code != findings.ExitRejected || out != "" {
		t.Errorf("exit %d, stdout %q; want 1 and nothing printed", code, out)
	}
}
