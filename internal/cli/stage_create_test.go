package cli

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"maps"
	"net"
	"net/http/httptest"
	"os"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/spf13/cobra"
	"go.temporal.io/sdk/activity"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The stages the create tests resolve, all of one proposed change on the fixture branch,
// branched at demoBranchedFrom. sealed's at is the fixture's own, so a read of it is the
// fixture; cabled's is the time its label was written. The rest each draw one refusal.
const (
	demoWrittenAt    = "2026-09-20T10:00:00.123456+00:00"
	fixtureAt        = "2026-09-08T12:00:00Z"
	demoBranchedFrom = "2026-09-01T00:00:00.000000+00:00"
	demoChange       = "pc-demo"
)

// demoInfrahub serves the fixture branch's proposed change pc-demo and its marks: sealed
// (given), cabled (written), future (an as_of later than any clock), nine (nine fractional
// digits) and twice (held by two marks).
func demoInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	written := func(id, label, at, description string) fakeStage {
		return fakeStage{ID: id, Label: label, WrittenAt: demoWrittenAt, At: at, Description: description}
	}
	pc := f.change(demoChange, "fylgja-fixture",
		written("st-cabled", "cabled", "", "before the change"),
		written("st-sealed", "sealed", fixtureAt, "after the first cut-over"),
		written("st-future", "future", "2099-01-01T00:00:00Z", ""),
		written("st-nine", "nine", "2026-09-20T10:00:00.123456789Z", ""),
		written("st-twice-b", "twice", "", ""),
		written("st-twice-a", "twice", "", ""))
	pc.BranchedFrom, pc.CreatedAt = demoBranchedFrom, demoBranchedFrom
	// main was last written before the branch point, so no resolution warns that it moved.
	f.versions = map[string][]fakeVersion{"main": {{Since: demoMainWritten, CTM: f.branches["main"]}}}
	return f
}

// demoMainWritten is main's latest stamp in demoInfrahub: before the branch point.
const demoMainWritten = "2026-08-01T00:00:00.000000+00:00"

// demoBlock is the stage block a resolved demo stage carries.
func demoBlock(label, at, source, description string) findings.StageBlock {
	return findings.StageBlock{Ref: "fylgja-fixture/" + label, Branch: "fylgja-fixture", Label: label,
		ProposedChange: findings.StageChange{ID: demoChange, Name: "change " + demoChange, Branch: "fylgja-fixture"},
		At:             at, AtSource: source, Description: description}
}

// readsNoIntent fails when a resolution read any branch's intent: the schema, the
// proposed changes, the branch's point of origin and its stamps are the resolution's; the
// devices, the links, the contract node and the artifacts' content are the read's.
func readsNoIntent(t *testing.T, label string, f *fakeInfrahub) {
	t.Helper()
	for _, r := range f.requests() {
		switch {
		case strings.HasPrefix(r.Path, "/api/storage/"),
			r.Operation == "Devices" || r.Operation == "Links" || r.Operation == "ContractVersion":
			t.Errorf("%s: the resolution asked %+v; a branch's intent is the read's", label, r)
		}
	}
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

// The stage.ref.invalid sentence for a value, as every command gives it.
func stageRefInvalid(given string) string {
	return `--stage "` + given + `" is not a stage reference: expected <branch>/<label>, ` +
		`a branch with no "/" and no whitespace and a label with neither`
}

// Before any connection, a reference that is not the form, or a flag a stage makes
// meaningless, is refused at step start, exit 2, with the workflow service never dialled
// and Infrahub never asked; neither flag given is M1's usage failure with the message both
// commands share (contracts/cli.md). An explicitly empty --stage= is a reference that is
// not the form, alone or beside --branch, and on the dry run too: never the flag left out,
// which beside --branch would start a following create. The conflict names the first of
// --branch, --at and --interval in that order, whatever order they are given in (US4
// scenario 2).
func TestCreateStageRefusedBeforeAnyConnection(t *testing.T) {
	const whole = "a stage is a whole pinned reference (branch and at)"
	emptyRef := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageRefInvalid, Object: "", Step: findings.StepStart,
		Message: stageRefInvalid("")}
	conflict := func(flag, why string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageFlagsConflict, Object: flag,
			Step: findings.StepStart, Message: flag + " is meaningless with --stage: " + why}
	}
	const sealed = "fylgja-fixture/sealed"
	for _, c := range []struct {
		name string
		args []string
		want findings.Finding
	}{
		{"neither", nil, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed,
			Object: findings.OpTwinCreate, Message: "--branch or --stage is required"}},
		{"not a reference", []string{"--stage", "demo"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleStageRefInvalid, Object: "demo", Step: findings.StepStart, Message: stageRefInvalid("demo")}},
		{"no label", []string{"--stage", "change-1/", "--branch", "x"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleStageRefInvalid, Object: "change-1/", Step: findings.StepStart, Message: stageRefInvalid("change-1/")}},
		{"no branch", []string{"--stage", "/x"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleStageRefInvalid, Object: "/x", Step: findings.StepStart, Message: stageRefInvalid("/x")}},
		{"a spaced branch", []string{"--stage", "a b/c"}, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleStageRefInvalid, Object: "a b/c", Step: findings.StepStart, Message: stageRefInvalid("a b/c")}},
		{"--stage= alone", []string{"--stage="}, emptyRef},
		{"--stage= beside --branch", []string{"--branch", "fylgja-fixture", "--stage="}, emptyRef},
		{"--stage= alone, dry run", []string{"--stage=", "--dry-run"}, emptyRef},
		{"--stage= beside --branch, dry run", []string{"--branch", "fylgja-fixture", "--stage=", "--dry-run"}, emptyRef},
		{"--branch", []string{"--stage", sealed, "--branch", "change-1"}, conflict("--branch", whole)},
		{"--at", []string{"--stage", sealed, "--at", fixtureAt}, conflict("--at", whole)},
		{"--interval", []string{"--stage", sealed, "--interval", "1m"}, conflict("--interval", "a stage twin is pinned and never follows")},
		{"--interval empty", []string{"--stage", sealed, "--interval="}, conflict("--interval", "a stage twin is pinned and never follows")},
		{"the first found", []string{"--stage", sealed, "--interval", "1m", "--at", fixtureAt, "--branch", "change-1"},
			conflict("--branch", whole)},
		{"--at before --interval", []string{"--stage", sealed, "--interval", "1m", "--at", fixtureAt}, conflict("--at", whole)},
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
			if doc.Stage != nil {
				t.Errorf("a refusal before resolution carries the stage block %+v", doc.Stage)
			}
			// A reference that parses is named in the subject; one that does not is not,
			// since it names no stage.
			wantSubject := ""
			if c.want.Rule == findings.RuleStageFlagsConflict {
				wantSubject = sealed
			}
			if got := subjectStage(doc); got != wantSubject {
				t.Errorf("subject.stage = %q, want %q", got, wantSubject)
			}
			validateM10Document(t, doc)
		})
	}
}

func subjectStage(doc *findings.Document) string {
	if doc.Subject == nil {
		return ""
	}
	return doc.Subject.Stage
}

// Each resolution refusal ends the create with its document and starts nothing: the rule,
// step resolve, the object and the exit contracts/cli.md gives, and subject.stage naming
// what was asked. The kind is checked before the proposed changes are asked for, and no
// refusal reads a branch's intent.
func TestCreateStageResolutionRefusals(t *testing.T) {
	const kindRemedy = ": load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it"
	for _, c := range []struct {
		name, ref   string
		setup       func(*fakeInfrahub)
		code        int
		rule, obj   string
		messageHas  string
		wantQueried bool
	}{
		{"kind absent", "fylgja-fixture/sealed", func(f *fakeInfrahub) { f.kind = nil }, findings.ExitRejected,
			findings.RuleStageKindAbsent, intent.StageKind, "the default branch's schema has no kind FylgjaStage" + kindRemedy, false},
		{"an attribute missing", "fylgja-fixture/sealed", func(f *fakeInfrahub) { f.kind = []string{"label", "as_of"} },
			findings.ExitRejected, findings.RuleStageKindAbsent, intent.StageKind,
			"kind FylgjaStage on the default branch lacks the attribute description, which this build reads" + kindRemedy, false},
		{"the extension missing", "fylgja-fixture/sealed", func(f *fakeInfrahub) { f.noExtension = true },
			findings.ExitRejected, findings.RuleStageKindAbsent, intent.StageKind,
			"kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds" + kindRemedy, false},
		{"unknown branch", "beta/sealed", nil, findings.ExitRejected, findings.RuleStageUnknown, "beta",
			"no open proposed change has source branch beta; the branches with one are: fylgja-fixture", true},
		{"unknown label", "fylgja-fixture/nosuch", nil, findings.ExitRejected, findings.RuleStageUnknown, "fylgja-fixture/nosuch",
			`proposed change "change pc-demo" (pc-demo) on branch fylgja-fixture has no stage "nosuch"; its stages are: ` +
				"branch-point, sealed, cabled, twice, nine, future, head", true},
		{"duplicate", "fylgja-fixture/twice", nil, findings.ExitRejected, findings.RuleStageDuplicate, "fylgja-fixture/twice",
			"stage fylgja-fixture/twice is held by 2 objects (ids st-twice-a, st-twice-b), which the kind's uniqueness constraint should have refused; none is chosen", true},
		{"a future at", "fylgja-fixture/future", nil, findings.ExitRejected, findings.RuleStageAtUnresolved, "fylgja-fixture/future",
			"stage fylgja-fixture/future has at 2099-01-01T00:00:00Z (given), later than the current time ", true},
		// No as_of written and a null label updated_at: resolved, it would start a run of the
		// branch head that fails only at record.
		{"no at", "fylgja-fixture/unstamped", func(f *fakeInfrahub) {
			f.changes[0].Stages = append(f.changes[0].Stages, fakeStage{ID: "st-unstamped", Label: "unstamped"})
		}, findings.ExitRejected, findings.RuleStageAtUnresolved, "fylgja-fixture/unstamped",
			"stage fylgja-fixture/unstamped has no at: no as_of is written on it and Infrahub returned no updated_at for its label, so it names no point in time", true},
		{"nine digits", "fylgja-fixture/nine", nil, findings.ExitError, findings.RuleAtPrecision, "fylgja-fixture/nine",
			"stage fylgja-fixture/nine: at 2026-09-20T10:00:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 (microseconds). Write the stage's as_of with at most six.", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := demoInfrahub(t)
			if c.setup != nil {
				c.setup(f)
			}
			f.start()

			code, doc := executeTwin(t, "twin", "create", "--stage", c.ref)
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with one %s", code, doc.Findings, c.code, c.rule)
			}
			got := doc.Findings[0]
			if got.Rule != c.rule || got.Step != findings.StepResolve || got.Object != c.obj || !strings.Contains(got.Message, c.messageHas) {
				t.Errorf("finding %+v; want %s at step resolve naming %s, saying %q", got, c.rule, c.obj, c.messageHas)
			}
			if doc.Subject == nil || doc.Subject.Stage != c.ref || doc.Subject.Branch != "" || doc.Subject.At != "" || doc.Stage != nil {
				t.Errorf("subject %+v, stage %+v; want subject.stage %s alone and no block", doc.Subject, doc.Stage, c.ref)
			}
			var queried bool
			for _, r := range f.requests() {
				queried = queried || r.Operation == "ProposedChanges"
			}
			if queried != c.wantQueried {
				t.Errorf("proposed changes queried %v, want %v", queried, c.wantQueried)
			}
			readsNoIntent(t, c.name, f)
			mustCarryNoToken(t, c.name, doc)
			validateM10Document(t, doc)
		})
	}
}

// An Infrahub the resolution cannot reach, or a credential it lacks, is M1's
// operation.failed, exit 2, at step resolve: the reader's error as it is, never one of the
// resolution's refusals, and no credential in it.
func TestCreateStageResolutionCannotRun(t *testing.T) {
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

			code, doc := executeTwin(t, "twin", "create", "--stage", "fylgja-fixture/sealed")
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

// A resolved create starts M2–M7's pinned run for the reference the stage resolves to,
// with the stage as data and no following: the input carries branch and at as resolved and
// the stage, never Follow; --no-follow beside it changes nothing. The document names the
// stage in its subject and its block. The CLI reads nothing of the branch's intent: the
// read is the run's.
func TestCreateFromAStage(t *testing.T) {
	for _, c := range []struct {
		name  string
		args  []string
		block findings.StageBlock
	}{
		{"given", []string{"--stage", "fylgja-fixture/sealed"},
			demoBlock("sealed", fixtureAt, findings.AtSourceGiven, "after the first cut-over")},
		{"written", []string{"--stage", "fylgja-fixture/cabled"},
			demoBlock("cabled", demoWrittenAt, findings.AtSourceWritten, "before the change")},
		{"--no-follow", []string{"--stage", "fylgja-fixture/sealed", "--no-follow"},
			demoBlock("sealed", fixtureAt, findings.AtSourceGiven, "after the first cut-over")},
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
			want := provision.ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", At: c.block.At, Version: version,
				StopFollowing: true, Stage: &provision.StageInput{
					ProposedChange: wire.StageChange{ID: demoChange, Branch: "fylgja-fixture"},
					Label:          c.block.Label, Description: c.block.Description, AtSource: c.block.AtSource}}
			if len(svc.started) != 1 || !reflect.DeepEqual(svc.started[0], want) {
				t.Errorf("started %+v; want %+v", svc.started, want)
			}
			if doc.Stage == nil || *doc.Stage != c.block {
				t.Errorf("stage block %+v, want %+v", doc.Stage, c.block)
			}
			wantSubject := findings.Subject{Branch: "fylgja-fixture", At: c.block.At, Stage: c.block.Ref, RunID: "run-1"}
			if doc.Subject == nil || !reflect.DeepEqual(*doc.Subject, wantSubject) {
				t.Errorf("subject %+v, want %+v", doc.Subject, wantSubject)
			}
			if doc.Following != nil {
				t.Errorf("a stage twin carries a following block %+v", doc.Following)
			}
			readsNoIntent(t, c.name, f)
			mustCarryNoToken(t, c.name, doc, svc.started)
			validateM10Document(t, doc)
		})
	}
}

// A resolved create whose run refuses reports what the run reports, word for word what the
// create of the reference the stage resolves to would say, with the stage beside it: M3's
// host refusals and M1's read refusals are the run's, unchanged. No following block
// appears.
func TestCreateFromAStageWhoseRunRefuses(t *testing.T) {
	const twinDir = "/abs/local/twin"
	skipped := provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped}
	sealed := demoBlock("sealed", fixtureAt, findings.AtSourceGiven, "after the first cut-over")
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
			code, doc := executeTwin(t, "twin", "create", "--stage", "fylgja-fixture/sealed")

			useService(t, &fakeService{runID: "run-1", result: c.result})
			refCode, ref := executeTwin(t, "twin", "create", "--branch", "fylgja-fixture", "--at", fixtureAt)

			if code != c.code || refCode != c.code {
				t.Errorf("exit %d, and %d by --branch --at; want %d", code, refCode, c.code)
			}
			if !reflect.DeepEqual(doc.Findings, ref.Findings) || !reflect.DeepEqual(doc.Findings, c.result.Findings) {
				t.Errorf("findings %+v\nby --branch --at %+v\nwant the run's %+v", doc.Findings, ref.Findings, c.result.Findings)
			}
			if doc.Stage == nil || *doc.Stage != sealed {
				t.Errorf("stage block %+v, want %+v", doc.Stage, sealed)
			}
			wantSubject := *ref.Subject
			wantSubject.Stage = "fylgja-fixture/sealed"
			if doc.Subject == nil || !reflect.DeepEqual(*doc.Subject, wantSubject) {
				t.Errorf("subject %+v, want the --branch --at create's with the stage, %+v", doc.Subject, wantSubject)
			}
			if doc.Following != nil {
				t.Errorf("a stage twin's refusal carries a following block %+v", doc.Following)
			}
			if len(svc.started) != 1 || svc.started[0].Follow != nil || svc.started[0].Stage == nil {
				t.Errorf("started %+v; want one pinned run carrying the stage", svc.started)
			}
			mustCarryNoToken(t, c.name, doc, svc.started)
			validateM10Document(t, doc)
		})
	}
}

// The resolved reference is reported on one line before the run's first line (contracts/
// cli.md), and a refused one prints nothing on stdout.
func TestCreateFromAStageReportsTheReference(t *testing.T) {
	useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	demoInfrahub(t).start()

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{stage: "fylgja-fixture/sealed"})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	const line = `stage fylgja-fixture/sealed: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), "after the first cut-over"`
	if !strings.HasPrefix(out, line+"\nrun fylgja-provision run-1\n") {
		t.Errorf("stdout:\n%s\nwant it to begin with the stage line, then the run's", out)
	}
	if strings.Contains(out, fakeToken) {
		t.Errorf("stdout carries the credential:\n%s", out)
	}

	out = captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{stage: "fylgja-fixture/nosuch"})
	})
	if code, _ := exitOf(t, err); code != findings.ExitRejected || out != "" {
		t.Errorf("exit %d, stdout %q; want 1 and nothing printed", code, out)
	}
}

// US2's create scenarios through the harness (014, T035): a twin from each kind of stage,
// the stage refusals that start nothing, and a create along main's own history after a
// stage twin. The proposed change is stage plan's, pc-1 on change-1 (stage_plan_test.go):
// its branch point reads main, the fixture, at the branch's branched_from; cabled, written
// and unwritten, reads change-1 less its last link; live, given, and the head read the whole
// fixture. Each create is the command the operator runs; where it starts a run, the run is
// the Provision workflow on Temporal's test suite, given the input the server started, so
// the record and the bundle it deploys are the run's own.

// provisionOnSuite runs the Provision workflow with in on Temporal's test suite, with the
// worker's own activities wherever they need no host, as
// TestConfigurationBytesGoToTheNodeAndNowhereElse drives a create: the read and the compile
// against the fake Infrahub the test started, the host check over a recorded empty host,
// the stage, the readiness, the push to a node that commits whatever it is sent, and the
// record. Only the deploy answers as containerlab would, and the stop of a following finds
// none. It returns the run's result and twin.json as the run wrote it.
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
	activities := (&provision.ControlActivities{Store: store, Paths: paths}).Names()
	maps.Copy(activities, acts.Names())
	activities[provision.ActStopFollowing] = func(context.Context) (provision.StopFollowingResult, error) {
		return provision.StopFollowingResult{}, nil
	}
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

// validateTwinJSON validates twin.json as written against the current
// contracts/twin.schema.json, version 6 since 014.
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

// writtenRecord is what twin.json says of the stage and the reference it was read at, as
// written.
type writtenRecord struct {
	TwinVersion string           `json:"twin_version"`
	BundleID    string           `json:"bundle_id"`
	Provenance  wire.Provenance  `json:"provenance"`
	Source      string           `json:"source"`
	Stage       *wire.StageRef   `json:"stage"`
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

// Scenario 1 and SC-002: a twin from each kind of stage — a mark written and one given, the
// branch point on a main that carries the contract, and the head — deploys the bundle id
// stage plan printed for that stage, is pinned at the stage's at and never follows, and
// twin.json 6 names its proposed change by id and branch, its label, its description and
// where its at came from, with provenance.at the resolved at and provenance.branch the
// branch read: main for the branch point. The branch point's dry run, read on another
// branch than its proposed change's, says the same id and that the twin would not follow,
// because of the stage; which kind of stage it is changes neither. The text's closing line
// names the stage: pinned at <at>, stage <branch>/<label>; not following.
func TestCreateFromEachKindOfStage(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	if code != findings.ExitOK || len(compiledRefs(stages)) != 4 {
		t.Fatalf("exit %d, compiled %v; want 0 and four stages compiled\n%s", code, compiledRefs(stages), raw)
	}
	printed := map[string]findings.PlanStage{}
	for _, st := range stages {
		printed[st.Label] = st
	}
	var ids []string
	for _, c := range []struct {
		label, branch, at, source, description string
	}{
		{"branch-point", "main", fakeBranchedFrom, findings.AtSourceBranchPoint, ""},
		{"cabled", lessLink, cabledAt, findings.AtSourceWritten, "the leaf cabled"},
		{"live", lessLink, planLiveAt, findings.AtSourceGiven, "the leaf live"},
		{"head", lessLink, planHeadAt, findings.AtSourceHead, ""},
	} {
		t.Run(c.label, func(t *testing.T) {
			paths := useStateRoot(t)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			plan := printed[c.label]
			if plan.Branch != c.branch || plan.At != c.at || plan.AtSource != c.source || plan.BundleID == nil {
				t.Fatalf("stage plan printed %+v; want %s at %s (%s), compiled", plan, c.branch, c.at, c.source)
			}
			id := *plan.BundleID
			ids = append(ids, id)
			ref := lessLink + "/" + c.label
			stage := wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: lessLink}, Label: c.label,
				Description: c.description, AtSource: c.source}
			block := findings.StageBlock{Ref: ref, Branch: c.branch, Label: c.label,
				ProposedChange: findings.StageChange{ID: "pc-1", Name: "change pc-1", Branch: lessLink, Draft: true},
				At:             c.at, AtSource: c.source, Description: c.description}

			if c.source == findings.AtSourceBranchPoint {
				code, dry := executeTwin(t, "twin", "create", "--stage", ref, "--dry-run")
				if code != findings.ExitOK || dry.BundleID != id || dry.DryRun == nil || dry.DryRun.Follow == nil ||
					dry.DryRun.Follow.Enabled || dry.DryRun.Follow.Reason != findings.FollowReasonStage ||
					dry.Stage == nil || *dry.Stage != block {
					t.Errorf("dry run exit %d, bundle_id %s, dry_run %+v, stage %+v; want 0, the plan's %s, not following "+
						"(reason stage), and %+v", code, dry.BundleID, dry.DryRun, dry.Stage, id, block)
				}
				mustCarryNoToken(t, "the dry run", dry)
			}

			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			useInterrupts(t)
			code, created := executeTwin(t, "twin", "create", "--stage", ref)
			want := provision.ProvisionInput{Source: wire.SourceIntent, Branch: c.branch, At: c.at, Version: version,
				StopFollowing: true, Stage: &stage}
			if code != findings.ExitOK || len(svc.started) != 1 || !reflect.DeepEqual(svc.started[0], want) {
				t.Fatalf("exit %d, started %+v; want 0 and one run of %+v", code, svc.started, want)
			}
			if created.Stage == nil || *created.Stage != block || created.Following != nil {
				t.Errorf("stage block %+v, following %+v; want %+v and none", created.Stage, created.Following, block)
			}

			res, record := provisionOnSuite(t, paths, svc.started[0])
			validateTwinJSON(t, record)
			w := decodeRecord(t, record)
			if res.BundleID != id || w.BundleID != id || w.TwinVersion != "6" || w.Source != wire.SourceIntent ||
				w.Provenance.Branch != c.branch || w.Provenance.At != c.at || !reflect.DeepEqual(w.Stage, &stage) || w.Step != nil {
				t.Errorf("the run deployed %s and recorded\n%s\nwant %s, twin_version 6, provenance %s at %s, stage %+v, step null",
					res.BundleID, record, id, c.branch, c.at, stage)
			}
			if res.FollowingStopped != nil || res.Following != nil {
				t.Errorf("the run's following %+v, stopped %+v; a stage twin never follows", res.Following, res.FollowingStopped)
			}
			mustCarryNoToken(t, c.label, created, svc.started)

			// In text, the closing line names the stage, as twin show's kind line does.
			useService(t, &fakeService{runID: "run-2", result: readyResult()})
			var err error
			out := captureStdout(t, func() {
				err = runCreate(context.Background(), &options{}, &createFlags{stage: ref})
			})
			if code, _ := exitOf(t, err); code != findings.ExitOK ||
				!strings.HasSuffix(out, "\npinned at "+c.at+", stage "+ref+"; not following\n") {
				t.Errorf("the text create: exit %d, stdout:\n%s\nwant it to end \"pinned at %s, stage %s; not following\"",
					code, out, c.at, ref)
			}
		})
	}
	if distinct := slices.Compact(slices.Sorted(slices.Values(ids))); len(distinct) != 4 {
		t.Errorf("the four stages deployed %v; want four bundles", ids)
	}
}

// untimed is a finding with the clock cut from its message: a given at later than now
// names the time the server read its clock, which no two commands share.
func untimed(f findings.Finding) findings.Finding {
	if i := strings.Index(f.Message, "later than the current time "); i >= 0 {
		f.Message = f.Message[:i]
	}
	return f
}

// Scenario 8, and every other refusal at resolution: a stage marked after an intent change
// and before its regenerate, one before the branch point, one in the future, one a rebase
// moved the branch point past and a mark taking the head's label are each refused at step
// resolve with the finding stage plan gives that stage, word for word, by the create and by
// its dry run. No run is started: the workflow service is asked nothing, containerlab is
// asked nothing, no branch's intent is read at the stage's at, and nothing is filed.
func TestCreateFromARefusedStageStartsNothing(t *testing.T) {
	const (
		editedAt = "2026-10-16T09:30:00.000000+00:00"
		markedAt = "2026-10-16T09:40:00.000000+00:00"
		earlyAt  = "2026-10-16T07:30:00.000000+00:00"
		futureAt = "2099-01-01T00:00:00.000000+00:00"
		rebaseAt = "2026-10-16T08:55:00.000000+00:00"
	)
	// refused is one stage a create is refused, with its refusals' rule and object as
	// rulesOf gives them, and its at, which no read may name ("" for one refused before it
	// has an at of its own).
	type refused struct {
		label string
		rules []string
		at    string
	}
	for _, c := range []struct {
		name  string
		marks []fakeStage
		setup func(*fakeInfrahub)
		// planned is whether the expected findings are stage plan's; the reserved label's
		// are the reference contract's step 4, written out.
		planned bool
		stages  []refused
	}{
		{name: "marks refused", planned: true,
			marks: []fakeStage{mark("st-edited", "edited", markedAt, "before the regenerate"), mark("st-early", "early", earlyAt, ""),
				mark("st-future", "future", futureAt, "")},
			// n1 and n2 are edited after their artifacts were generated, and nothing is
			// regenerated or checked after; a stage at or before the edit is not stale.
			setup: func(f *fakeInfrahub) {
				f.stamps = map[string]fakeDeviceStamps{
					lessLink + "/n1": {Intent: editedAt, Artifact: fakeWritten},
					lessLink + "/n2": {Intent: editedAt, Artifact: fakeWritten},
				}
			},
			stages: []refused{
				{"edited", []string{findings.RuleStageArtifactStale + " n1", findings.RuleStageArtifactStale + " n2"}, markedAt},
				{"early", []string{findings.RuleStageAtBeforeBranchPoint + " change-1/early"}, earlyAt},
				{"future", []string{findings.RuleStageAtUnresolved + " change-1/future"}, futureAt},
			}},
		{name: "after a rebase", planned: true, marks: []fakeStage{mark("st-cabled", "cabled", cabledAt, "")},
			setup:  func(f *fakeInfrahub) { f.changes[0].BranchedFrom = rebaseAt },
			stages: []refused{{"cabled", []string{findings.RuleStageAtBeforeBranchPoint + " change-1/cabled"}, cabledAt}}},
		{name: "a mark labelled head", marks: []fakeStage{mark("st-head", "head", cabledAt, "")},
			stages: []refused{{"head", []string{findings.RuleStageLabelReserved + " change-1/head"}, ""}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			dryRunEnv(t)
			clab := useClab(t, "inspect-empty.json")
			useService(t, nil)
			f := planInfrahub(t, c.marks...)
			if c.setup != nil {
				c.setup(f)
			}
			f.start()

			want := map[string]findings.List{"head": {{Severity: findings.Rejection, Rule: findings.RuleStageLabelReserved,
				Object: "change-1/head", Step: findings.StepResolve, Message: `stage change-1/head is a mark labelled "head", ` +
					"which names the derived head of every proposed change and is reserved; relabel it (schema/README.md); " +
					"the head of change-1 is still its derived stage"}}}
			if c.planned {
				_, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
				stages, _ := planned(t, doc)
				for _, st := range stages {
					if st.BundleID == nil {
						want[st.Label] = st.Findings
					}
				}
				if len(want) != len(c.stages)+1 {
					t.Fatalf("stage plan refused %d stages; want %d\n%s", len(want)-1, len(c.stages), raw)
				}
			}
			filed := storedBundles(t, paths.Bundles)

			for _, st := range c.stages {
				ref := lessLink + "/" + st.label
				if got := rulesOf(want[st.label]); !slices.Equal(got, st.rules) {
					t.Fatalf("%s's refusals are %v; want %v", ref, got, st.rules)
				}
				for _, args := range [][]string{{"--stage", ref}, {"--stage", ref, "--dry-run"}} {
					svc := &fakeService{runID: "run-1", result: readyResult()}
					useService(t, svc)
					useInterrupts(t)
					clab.calls = nil
					code, doc := executeTwin(t, append([]string{"twin", "create"}, args...)...)
					got, w := doc.Findings, want[st.label]
					if code != findings.ExitRejected || doc.Status != findings.StatusRejected || len(got) != len(w) {
						t.Fatalf("%v: exit %d, findings %+v; want 1 with %+v", args, code, got, w)
					}
					for i := range got {
						if untimed(got[i]) != untimed(w[i]) || got[i].Step != findings.StepResolve {
							t.Errorf("%v: finding %+v\nwant stage plan's %+v", args, got[i], w[i])
						}
					}
					if len(svc.calls) != 0 || len(svc.started) != 0 || doc.Subject.RunID != "" || doc.DryRun != nil || doc.Stage != nil {
						t.Errorf("%v: the service was asked %v and started %d runs; run %q, dry_run %+v, stage %+v; want nothing",
							args, svc.calls, len(svc.started), doc.Subject.RunID, doc.DryRun, doc.Stage)
					}
					if len(clab.calls) != 0 {
						t.Errorf("%v: containerlab was asked %v", args, clab.calls)
					}
					validateM10Document(t, doc)
				}
				if st.at != "" && readAt(f, st.at) {
					t.Errorf("a branch's intent was read at %s, refused %s's at", st.at, ref)
				}
			}
			if got := storedBundles(t, paths.Bundles); !slices.Equal(got, filed) {
				t.Errorf("the store holds %v, and held %v before the creates; a refused create files nothing", got, filed)
			}
		})
	}
}

// Scenario 7: after a twin built from a stage is destroyed, a story along main's own
// history still works as before and names no stage. A proposed change cannot have main as
// its source, so main has no stage to name; the create of main at a time is M3's pinned
// create, its run's input carrying no stage, its dry run not following because of the at,
// and twin.json 6 recording stage null.
func TestCreateAlongMainAfterAStageTwin(t *testing.T) {
	const mainAt = "2026-10-16T07:30:00.000000+00:00"
	paths := useStateRoot(t)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.start()

	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	useInterrupts(t)
	if code, doc := executeTwin(t, "twin", "create", "--stage", lessLink+"/cabled"); code != findings.ExitOK || len(svc.started) != 1 {
		t.Fatalf("exit %d, findings %+v, started %d; want 0 and one run", code, doc.Findings, len(svc.started))
	}
	_, record := provisionOnSuite(t, paths, svc.started[0])
	if w := decodeRecord(t, record); w.Stage == nil || w.Stage.Label != "cabled" {
		t.Fatalf("the stage twin recorded stage %+v; want cabled", w.Stage)
	}

	// twin destroy, whose run removes the lab and the twin directory; the directory is
	// removed here as the run's unstage removes it.
	useService(t, &fakeService{destroyRun: destroyedRun(provision.CleanupResult{Teardown: provision.CleanupDone,
		Unstage: provision.CleanupDone, Removed: []string{"lab fylgja (3 containers)", "twin directory " + paths.Twin}}, nil)})
	if code, doc := executeTwin(t, "twin", "destroy"); code != findings.ExitOK {
		t.Fatalf("twin destroy exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if err := os.RemoveAll(paths.Twin); err != nil {
		t.Fatal(err)
	}

	// main has no stage: no proposed change has it as its source.
	useService(t, nil)
	code, doc := executeTwin(t, "twin", "create", "--stage", "main/cabled")
	if want := (findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageUnknown, Object: "main", Step: findings.StepResolve,
		Message: "no open proposed change has source branch main; the branches with one are: change-1"}); code != findings.ExitRejected ||
		len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("--stage main/cabled: exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}

	code, dry := executeTwin(t, "twin", "create", "--branch", "main", "--at", mainAt, "--dry-run")
	if code != findings.ExitOK || dry.Stage != nil || dry.DryRun == nil || dry.DryRun.Follow == nil ||
		dry.DryRun.Follow.Reason != findings.FollowReasonPinned || dry.Subject.Stage != "" {
		t.Errorf("the dry run along main: exit %d, stage %+v, dry_run %+v, subject %+v; want 0, no stage, not following "+
			"(reason pinned)", code, dry.Stage, dry.DryRun, dry.Subject)
	}

	svc = &fakeService{runID: "run-2", result: readyResult()}
	useService(t, svc)
	code, created := executeTwin(t, "twin", "create", "--branch", "main", "--at", mainAt)
	want := provision.ProvisionInput{Source: wire.SourceIntent, Branch: "main", At: mainAt, Version: version, StopFollowing: true}
	if code != findings.ExitOK || len(svc.started) != 1 || !reflect.DeepEqual(svc.started[0], want) ||
		created.Stage != nil || created.Subject.Stage != "" {
		t.Fatalf("exit %d, started %+v, stage %+v, subject %+v; want 0, one run of %+v and no stage",
			code, svc.started, created.Stage, created.Subject, want)
	}
	res, record := provisionOnSuite(t, paths, svc.started[0])
	validateTwinJSON(t, record)
	w := decodeRecord(t, record)
	if res.BundleID != dry.BundleID || w.TwinVersion != "6" || w.Provenance.Branch != "main" || w.Provenance.At != mainAt ||
		w.Stage != nil || !strings.Contains(string(record), `"stage": null`) {
		t.Errorf("the run deployed %s (the dry run %s) and recorded\n%s\nwant main at %s, stage null", res.BundleID, dry.BundleID,
			record, mainAt)
	}
}
