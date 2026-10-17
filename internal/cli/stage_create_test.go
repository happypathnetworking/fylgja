package cli

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
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
// which beside --branch would start a following create.
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
			`proposed change "change pc-demo" (pc-demo) on branch fylgja-fixture has no stage "nosuch"; its stages are: branch-point, `, true},
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
