package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// runRead exercises the command flow exactly as the CLI does, up to wherever it
// stops. Every case here stops before the first request, so none of it needs Infrahub.
func runReadDoc(t *testing.T, f *readFlags) (int, *findingsDoc) {
	t.Helper()
	err := runRead(t.Context(), &options{asJSON: true}, f)
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runRead returned %v, want a findings result", err)
	}
	b, mErr := json.Marshal(res.doc)
	if mErr != nil {
		t.Fatal(mErr)
	}
	var doc findingsDoc
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatal(err)
	}
	return res.doc.Status.ExitCode(), &doc
}

// An `at` finer than Infrahub honours is refused before any query, under its own rule
// rather than the catch-all: the operator has to be told that the value was too
// precise, not merely that something failed.
func TestAtTooPreciseIsRefusedBeforeAnyQuery(t *testing.T) {
	for _, at := range []string{
		"2026-09-08T19:37:02.1234567Z",
		"2026-09-08T19:37:02.123456789Z",
	} {
		out := filepath.Join(t.TempDir(), "never.json")
		// No INFRAHUB_ADDRESS is set for this test: reaching the client at all would
		// fail with a different rule, which is exactly what must not happen.
		t.Setenv("INFRAHUB_ADDRESS", "")
		t.Setenv("INFRAHUB_API_TOKEN", "")

		code, doc := runReadDoc(t, &readFlags{branch: "fylgja-fixture", at: at, out: out})
		if code != findings.ExitError {
			t.Errorf("at %s: exit %d, want %d", at, code, findings.ExitError)
		}
		if doc.Status != string(findings.StatusError) {
			t.Errorf("at %s: status = %q, want error", at, doc.Status)
		}
		if len(doc.Findings) != 1 {
			t.Fatalf("at %s: %d findings, want exactly one: %+v", at, len(doc.Findings), doc.Findings)
		}
		f := doc.Findings[0]
		if f.Rule != findings.RuleAtPrecision {
			t.Errorf("at %s: rule = %s, want %s", at, f.Rule, findings.RuleAtPrecision)
		}
		if f.Object != at {
			t.Errorf("at %s: finding names %q, want the at", at, f.Object)
		}
		if !strings.Contains(f.Message, "microseconds") {
			t.Errorf("at %s: message does not name the precision honoured: %s", at, f.Message)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Errorf("at %s: a refused read left a file at %s", at, out)
		}
	}
}

// A missing credential is an operational failure naming the variable to set, and no
// request is sent.
func TestMissingCredentialIsNamed(t *testing.T) {
	t.Setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
	t.Setenv("INFRAHUB_API_TOKEN", "")
	out := filepath.Join(t.TempDir(), "never.json")

	code, doc := runReadDoc(t, &readFlags{branch: "fylgja-fixture", out: out})
	if code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Fatalf("want one operation.failed finding, got %+v", doc.Findings)
	}
	if !strings.Contains(doc.Findings[0].Message, "INFRAHUB_API_TOKEN") {
		t.Errorf("message does not name the variable to set: %s", doc.Findings[0].Message)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Error("a failed read left a file behind")
	}
}

// The required flags are refused as usage failures, before anything else.
func TestReadRequiresBranchAndOut(t *testing.T) {
	for _, tc := range []struct {
		name string
		f    readFlags
		want string
	}{
		{"no branch", readFlags{out: "x.json"}, "--branch or --stage is required"},
		{"no out beside a stage", readFlags{stage: "change-1/cabled"}, "--out is required"},
		{"no out", readFlags{branch: "fylgja-fixture"}, "--out is required"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			code, doc := runReadDoc(t, &tc.f)
			if code != findings.ExitError {
				t.Errorf("exit %d, want %d", code, findings.ExitError)
			}
			if len(doc.Findings) != 1 || doc.Findings[0].Message != tc.want {
				t.Errorf("want %q, got %+v", tc.want, doc.Findings)
			}
		})
	}
}

// The operation is intent.read on every document this command produces, including its
// failures: a machine reader routes on that field.
func TestReadDocumentsNameTheOperation(t *testing.T) {
	_, doc := runReadDoc(t, &readFlags{out: "x.json"})
	if doc.Operation != findings.OpIntentRead {
		t.Errorf("operation = %q, want %q", doc.Operation, findings.OpIntentRead)
	}
}

// pinnedCTM reads the CTM at path with its observed_at pinned, as the ctm package's own
// parity test pins it, and marshals it canonically: two reads of one reference differ by
// when they were taken and by nothing else.
func pinnedCTM(t *testing.T, path string) []byte {
	t.Helper()
	c, err := ctm.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.ObservedAt = "2026-09-28T00:00:00.000000Z"
	b, err := ctm.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// compiledCTM compiles the CTM at path on the stage pipeline twin compile and a run share
// (D-011), and returns the bundle's files and its id.
func compiledCTM(t *testing.T, path string) (map[string][]byte, string) {
	t.Helper()
	c, err := ctm.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	files, id, list := stage.Compile(c, reg)
	if list.Rejected() || id == "" {
		t.Fatalf("%s did not compile: %+v", path, list)
	}
	return files, id
}

// intent read --stage writes exactly the CTM intent read --branch B --at T writes for the
// reference the stage resolves to, from the same Infrahub: the pinned read, with the at
// verbatim, given or written, and nothing of the stage in the envelope, nor in the bundle it
// compiles to, which is the pinned read's. The resolved line comes first, and the success
// line and the document name the stage (US4 scenario 1).
func TestReadFromAStageIsThePinnedRead(t *testing.T) {
	for _, c := range []struct {
		label, at, source, description string
	}{
		{"sealed", fixtureAt, findings.AtSourceGiven, "after the first cut-over"},
		{"cabled", demoWrittenAt, findings.AtSourceWritten, "before the change"},
	} {
		t.Run(c.source, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			dir := t.TempDir()
			byStage, byReference := filepath.Join(dir, "stage.json"), filepath.Join(dir, "reference.json")
			ref := "fylgja-fixture/" + c.label
			block := demoBlock(c.label, c.at, c.source, c.description)

			var err error
			out := captureStdout(t, func() {
				err = runRead(t.Context(), &options{}, &readFlags{stage: ref, out: byStage})
			})
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			want := block.Line() + "\n" +
				"wrote " + byStage + ": 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, " +
				"0 shared ports (stage " + ref + ": branch fylgja-fixture, at " + c.at + ", scope tag:fylgja, schema fixture)\n"
			if out != want {
				t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
			}
			if code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true},
				&readFlags{branch: "fylgja-fixture", at: c.at, out: byReference})); code != findings.ExitOK {
				t.Fatalf("the --branch --at read: exit %d, findings %+v", code, doc.Findings)
			}

			got, pinned := pinnedCTM(t, byStage), pinnedCTM(t, byReference)
			if !bytes.Equal(got, pinned) {
				t.Errorf("the stage's CTM differs from the pinned read's:\n%s\nwant:\n%s", got, pinned)
			}
			raw, err := os.ReadFile(byStage)
			if err != nil {
				t.Fatal(err)
			}
			named := []string{"stage", demoChange, c.label, c.source, c.description}
			for _, word := range named {
				if strings.Contains(string(raw), word) {
					t.Errorf("the CTM names %q: a stage enters no CTM", word)
				}
			}
			// Compiled, the two reads are one bundle, file for file: the same intent hashes the
			// same however it was named, and the --branch --at read knows no stage, so nothing
			// of the stage is in it (US4). A label can be a word of the compiler's own
			// ("cabled" is an interface's disposition in every manifest), so the scan names
			// what only the stage holds: its reference, its proposed change, its description.
			files, id := compiledCTM(t, byStage)
			refFiles, refID := compiledCTM(t, byReference)
			if id != refID || !reflect.DeepEqual(files, refFiles) {
				t.Errorf("the stage's CTM compiles to %s, the pinned read's to %s; want one bundle, file for file", id, refID)
			}
			for name, b := range files {
				for _, word := range []string{ref, demoChange, c.description} {
					if bytes.Contains(b, []byte(word)) {
						t.Errorf("bundle file %s names %q: a stage enters no bundle", name, word)
					}
				}
			}
			if c.source == findings.AtSourceGiven && !bytes.Equal(got, pinnedCTM(t, repoPath("testdata", "ctm", "three-node.json"))) {
				t.Error("the fixture's stage does not read as the fixture")
			}

			code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{stage: ref, out: byStage}))
			if code != findings.ExitOK || doc.Stage == nil || *doc.Stage != block ||
				doc.Subject.Stage != ref || doc.Subject.Branch != "fylgja-fixture" || doc.Subject.At != c.at {
				t.Errorf("exit %d, document %+v; want 0 naming %s resolved to fylgja-fixture at %s", code, doc, ref, c.at)
			}
			mustCarryNoToken(t, ref, doc, out)
			validateM10Document(t, doc)
		})
	}
}

// Beside --stage, --branch and --at are refused before any connection, exit 2; a
// resolution refusal is the create's, with no step, as M1's operations carry none
// (contracts/cli.md). A reference naming no open proposed change, or no stage of one, is
// refused naming what exists, before any branch's intent is read (US4 scenario 3).
func TestReadFromAStageRefusals(t *testing.T) {
	const whole = "a stage is a whole pinned reference (branch and at)"
	for _, c := range []struct {
		name       string
		flags      readFlags
		code       int
		rule, obj  string
		messageHas string
		asked      bool
	}{
		{"--branch", readFlags{stage: "fylgja-fixture/sealed", branch: "fylgja-fixture"}, findings.ExitError,
			findings.RuleStageFlagsConflict, "--branch", "--branch is meaningless with --stage: " + whole, false},
		{"--at", readFlags{stage: "fylgja-fixture/sealed", at: fixtureAt}, findings.ExitError,
			findings.RuleStageFlagsConflict, "--at", "--at is meaningless with --stage: " + whole, false},
		{"--branch and --at", readFlags{stage: "fylgja-fixture/sealed", branch: "fylgja-fixture", at: fixtureAt}, findings.ExitError,
			findings.RuleStageFlagsConflict, "--branch", "--branch is meaningless with --stage: " + whole, false},
		{"not a reference", readFlags{stage: "fylgja-fixture/"}, findings.ExitError,
			findings.RuleStageRefInvalid, "fylgja-fixture/", stageRefInvalid("fylgja-fixture/"), false},
		{"unknown proposed change", readFlags{stage: "beta/sealed"}, findings.ExitRejected, findings.RuleStageUnknown, "beta",
			"no open proposed change has source branch beta; the branches with one are: fylgja-fixture", true},
		{"unknown", readFlags{stage: "fylgja-fixture/nosuch"}, findings.ExitRejected,
			findings.RuleStageUnknown, "fylgja-fixture/nosuch", `proposed change "change pc-demo" (pc-demo) on branch fylgja-fixture ` +
				`has no stage "nosuch"; its stages are: branch-point, sealed, cabled, twice, nine, future, head`, true},
		{"nine digits", readFlags{stage: "fylgja-fixture/nine"}, findings.ExitError,
			findings.RuleAtPrecision, "fylgja-fixture/nine",
			"stage fylgja-fixture/nine: at 2026-09-20T10:00:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 (microseconds). Write the stage's as_of with at most six.", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			c.flags.out = filepath.Join(t.TempDir(), "never.json")

			code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &c.flags))
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with one %s", code, doc.Findings, c.code, c.rule)
			}
			if got := doc.Findings[0]; got.Severity != findings.Rejection || got.Rule != c.rule || got.Object != c.obj ||
				got.Step != "" || !strings.Contains(got.Message, c.messageHas) {
				t.Errorf("finding %+v; want %s naming %s with no step, saying %q", got, c.rule, c.obj, c.messageHas)
			}
			if asked := len(f.requests()) > 0; asked != c.asked {
				t.Errorf("Infrahub asked %v, want %v: %+v", asked, c.asked, f.requests())
			}
			readsNoIntent(t, c.name, f)
			if _, err := os.Stat(c.flags.out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", c.flags.out)
			}
			validateM10Document(t, doc)
		})
	}
}

// Every refusal of the resolution's later steps is the create's for intent read too, made
// before any branch's intent is read (FR-011, SC-005): a stale stage naming exactly the
// devices whose intent moved, in the words stage plan gives the same stage; an at before
// the branch point, by a rebase or not; a mark taking a reserved label; two marks sharing
// one; a given as_of later than now and a mark with no at. Each is exit 1 with no step,
// and the fake is asked no device, link or contract node on any branch, pinned or not.
func TestReadFromAStageRefusedAtResolution(t *testing.T) {
	const (
		rebasedAt = "2026-09-10T00:00:00.000000+00:00"
		earlyAt   = "2026-08-15T00:00:00Z"
	)
	add := func(st fakeStage) func(*fakeInfrahub) {
		return func(f *fakeInfrahub) { f.changes[0].Stages = append(f.changes[0].Stages, st) }
	}
	for _, c := range []struct {
		name  string
		setup func(*fakeInfrahub)
		label string
		rule  string
		// objects are the findings' objects in order; messages their words, "" for the
		// stale ones, which are stage plan's for the same stage.
		objects, messages []string
	}{
		{name: "stale", label: "sealed", rule: findings.RuleStageArtifactStale,
			setup: func(f *fakeInfrahub) {
				f.stamps = map[string]fakeDeviceStamps{
					"fylgja-fixture/n1": {Intent: "2026-09-05T00:00:00.000000+00:00", Artifact: "2026-09-02T00:00:00.000000+00:00"},
					"fylgja-fixture/n3": {Intent: "2026-09-06T00:00:00.000000+00:00", Artifact: "2026-09-02T00:00:00.000000+00:00"},
				}
			},
			objects: []string{"n1", "n3"}, messages: []string{"", ""}},
		{name: "before the branch point, after a rebase", label: "sealed", rule: findings.RuleStageAtBeforeBranchPoint,
			setup:   func(f *fakeInfrahub) { f.changes[0].BranchedFrom = rebasedAt },
			objects: []string{"fylgja-fixture/sealed"},
			messages: []string{"stage fylgja-fixture/sealed has at " + fixtureAt + ", before the branch point " + rebasedAt +
				" of fylgja-fixture: a rebase at " + rebasedAt + " moved the branch point past it (the branch was created at " +
				demoBranchedFrom + "); mark the stage again, or delete it"}},
		{name: "before the branch was created", label: "early", rule: findings.RuleStageAtBeforeBranchPoint,
			setup:   add(fakeStage{ID: "st-early", Label: "early", WrittenAt: demoWrittenAt, At: earlyAt}),
			objects: []string{"fylgja-fixture/early"},
			messages: []string{"stage fylgja-fixture/early has at " + earlyAt + ", before the branch point " + demoBranchedFrom +
				" of fylgja-fixture, and before the branch was created at " + demoBranchedFrom +
				"; a stage names a moment on its source branch"}},
		{name: "a mark labelled head", label: "head", rule: findings.RuleStageLabelReserved,
			setup:   add(fakeStage{ID: "st-head", Label: "head", WrittenAt: demoWrittenAt}),
			objects: []string{"fylgja-fixture/head"},
			messages: []string{`stage fylgja-fixture/head is a mark labelled "head", which names the derived head of every ` +
				"proposed change and is reserved; relabel it (schema/README.md); the head of fylgja-fixture is still its " +
				"derived stage"}},
		{name: "two marks share the label", label: "twice", rule: findings.RuleStageDuplicate,
			objects: []string{"fylgja-fixture/twice"},
			messages: []string{"stage fylgja-fixture/twice is held by 2 objects (ids st-twice-a, st-twice-b), which the kind's " +
				"uniqueness constraint should have refused; none is chosen"}},
		{name: "a given as_of later than now", label: "future", rule: findings.RuleStageAtUnresolved,
			objects:  []string{"fylgja-fixture/future"},
			messages: []string{"stage fylgja-fixture/future has at 2099-01-01T00:00:00Z (given), "}},
		{name: "a mark with no at", label: "none", rule: findings.RuleStageAtUnresolved,
			setup:   add(fakeStage{ID: "st-none", Label: "none"}),
			objects: []string{"fylgja-fixture/none"},
			messages: []string{"stage fylgja-fixture/none has no at: no as_of is written on it and Infrahub returned no " +
				"updated_at for its label, so it names no point in time"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := demoInfrahub(t)
			if c.setup != nil {
				c.setup(f)
			}
			f.start()
			ref := "fylgja-fixture/" + c.label
			out := filepath.Join(t.TempDir(), "never.json")

			code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{stage: ref, out: out}))
			if code != findings.ExitRejected || doc.Status != findings.StatusRejected || len(doc.Findings) != len(c.objects) {
				t.Fatalf("exit %d, status %s, findings %+v; want 1 with %d %s", code, doc.Status, doc.Findings, len(c.objects), c.rule)
			}
			// Read before anything else asks the fake: no request so far is the read's.
			readsNoIntent(t, c.name, f)
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", out)
			}
			validateM10Document(t, doc)

			var byPlan findings.List
			if c.rule == findings.RuleStageArtifactStale {
				_, plan, raw := stageDoc(t, "plan", "--branch", "fylgja-fixture")
				stages, _ := planned(t, plan)
				for _, st := range stages {
					if st.Label == c.label {
						byPlan = st.Findings
					}
				}
				if len(byPlan) != len(c.objects) {
					t.Fatalf("stage plan refused %s with %v; want %d findings\n%s", ref, rulesOf(byPlan), len(c.objects), raw)
				}
			}
			for i, got := range doc.Findings {
				want := findings.Finding{Severity: findings.Rejection, Rule: c.rule, Object: c.objects[i], Message: c.messages[i]}
				switch {
				case c.rule == findings.RuleStageArtifactStale:
					want.Message = byPlan[i].Message
				case c.label == "future" && strings.HasPrefix(got.Message, want.Message) &&
					strings.HasSuffix(got.Message, ": it seals nothing yet, and a twin from it could differ between two creates"):
					want.Message = got.Message
				}
				if got != want {
					t.Errorf("finding %d %+v\nwant %+v", i, got, want)
				}
			}
		})
	}
}

// Through the command line, a reference that is not the form is stage.ref.invalid, and a
// flag beside --stage stage.flags.conflict naming the first of --branch and --at whatever
// order they are given in, each exit 2 with no step, before any connection: Infrahub is
// asked nothing and nothing is written (US4 scenario 2).
func TestReadFromAStageRefusedBeforeAnyConnection(t *testing.T) {
	const whole = "a stage is a whole pinned reference (branch and at)"
	invalid := func(given string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageRefInvalid, Object: given, Message: stageRefInvalid(given)}
	}
	conflict := func(flag string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageFlagsConflict, Object: flag,
			Message: flag + " is meaningless with --stage: " + whole}
	}
	const sealed = "fylgja-fixture/sealed"
	for _, c := range []struct {
		name string
		args []string
		want findings.Finding
	}{
		{"no slash", []string{"--stage", "x"}, invalid("x")},
		{"no branch", []string{"--stage", "/x"}, invalid("/x")},
		{"no label", []string{"--stage", "a/"}, invalid("a/")},
		{"a spaced branch", []string{"--stage", "a b/c"}, invalid("a b/c")},
		{"--at", []string{"--at", fixtureAt, "--stage", sealed}, conflict("--at")},
		{"--at before --branch", []string{"--at", fixtureAt, "--branch", "fylgja-fixture", "--stage", sealed}, conflict("--branch")},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			out := filepath.Join(t.TempDir(), "never.json")

			code, doc := executeTwin(t, append(append([]string{"intent", "read"}, c.args...), "--out", out)...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != c.want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, c.want)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			// A reference that parses is named in the subject; one that does not is not.
			wantSubject := ""
			if c.want.Rule == findings.RuleStageFlagsConflict {
				wantSubject = sealed
			}
			if doc.Stage != nil || subjectStage(doc) != wantSubject {
				t.Errorf("subject %+v, stage %+v; want subject.stage %q and no block", doc.Subject, doc.Stage, wantSubject)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", out)
			}
			validateM10Document(t, doc)
		})
	}
}

// An explicitly empty --stage= is a reference that is not the form, through the command
// line, alone or beside --branch: stage.ref.invalid, exit 2, with no step, before any
// connection and with nothing written. Beside --branch it is never the branch's read.
func TestReadEmptyStageIsRefused(t *testing.T) {
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageRefInvalid, Object: "",
		Message: stageRefInvalid("")}
	for _, c := range []struct {
		name string
		args []string
	}{
		{"alone", []string{"--stage="}},
		{"beside --branch", []string{"--branch", "fylgja-fixture", "--stage="}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := demoInfrahub(t)
			f.start()
			out := filepath.Join(t.TempDir(), "never.json")

			code, doc := executeTwin(t, append(append([]string{"intent", "read"}, c.args...), "--out", out)...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			if doc.Stage != nil || subjectStage(doc) != "" {
				t.Errorf("subject %+v, stage %+v; an empty reference names no stage", doc.Subject, doc.Stage)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("a refused read wrote %s", out)
			}
			validateM10Document(t, doc)
		})
	}
}

// A read the resolved reference refuses keeps M1's wording, word for word what --branch and
// --at would say, and the document names the stage that resolved to it: a stage of a branch
// whose devices' tags were removed resolves, and its read is refused as the branch's is.
func TestReadFromAStageKeepsTheReadsRefusal(t *testing.T) {
	f := demoInfrahub(t)
	f.change("pc-bare", "bare", mark("st-bare", "bare", "", "its devices untagged"))
	f.untagged = map[string]bool{"bare": true}
	f.start()
	dir := t.TempDir()

	code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{stage: "bare/bare", out: filepath.Join(dir, "a.json")}))
	_, ref := exitOf(t, runRead(t.Context(), &options{asJSON: true},
		&readFlags{branch: "bare", at: fakeMarkedAt, out: filepath.Join(dir, "b.json")}))
	if code != findings.ExitRejected || len(doc.Findings) != 1 || len(ref.Findings) != 1 || doc.Findings[0] != ref.Findings[0] ||
		doc.Findings[0].Rule != findings.RuleScopeEmpty {
		t.Errorf("exit %d, findings %+v; want 1 with the --branch --at read's %+v", code, doc.Findings, ref.Findings)
	}
	want := findings.StageBlock{Ref: "bare/bare", Branch: "bare", Label: "bare",
		ProposedChange: findings.StageChange{ID: "pc-bare", Name: "change pc-bare", Branch: "bare"},
		At:             fakeMarkedAt, AtSource: findings.AtSourceWritten, Description: "its devices untagged"}
	if doc.Stage == nil || *doc.Stage != want {
		t.Errorf("stage block %+v, want %+v", doc.Stage, want)
	}
	validateM10Document(t, doc)
}

// cableLabel is a schema mutation of DcimCable's label: gone when kind is "", else held
// as kind.
func cableLabel(kind string) func(map[string]any) {
	return func(doc map[string]any) {
		for _, n := range doc["nodes"].([]any) {
			node := n.(map[string]any)
			if node["kind"] != "DcimCable" {
				continue
			}
			var attrs []any
			for _, a := range node["attributes"].([]any) {
				attr := a.(map[string]any)
				if attr["name"] == "label" {
					if kind == "" {
						continue
					}
					attr["kind"] = kind
				}
				attrs = append(attrs, attr)
			}
			node["attributes"] = attrs
		}
	}
}

// The cable's label is in the mapping's table, since the Ports query selects it and every
// omitted cable is named by it (contracts/mapping.md §2–§4): a branch whose DcimCable
// lacks it, or holds it as another kind, is refused by conformance naming the commit, as
// schema check refuses it, before any query, where the Ports query would have failed
// operation.failed naming nothing of the table (FR-012; US3 scenario 4). A conformant
// branch reads as before.
func TestReadHoldsTheCablesLabelToTheTable(t *testing.T) {
	const branch = "fylgja-fixture"
	for _, c := range []struct {
		name   string
		mutate func(map[string]any)
		want   findings.Finding
	}{
		{"label gone", cableLabel(""), findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSchemaFieldMissing,
			Object: "DcimCable.label", Message: "DcimCable has no attribute label; the mapping reads it as " +
				"opsmill/schema-library@26336e9 has it"}},
		{"label a Number", cableLabel("Number"), findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSchemaFieldMismatch,
			Object: "DcimCable.label", Message: "kind Text, found Number; the mapping reads it as " +
				"opsmill/schema-library@26336e9 has it"}},
	} {
		t.Run(c.name, func(t *testing.T) { readAndCheckRefusedAlike(t, branch, c.mutate, c.want) })
	}
	t.Run("conformant", func(t *testing.T) { readsDevicesAndPorts(t, branch) })
}

// The connector's connected_endpoints are in the mapping's table on the generic
// DcimConnector, since the Ports query selects them on the generic, outside the DcimCable
// fragment: a branch whose DcimConnector lacks them, DcimCable declaring them itself as a
// later library commit could, or holds them to another peer, is refused by conformance
// naming the commit, as schema check refuses it, before any query, where the Ports query
// would have failed operation.failed naming nothing of the table (FR-012; US3 scenario
// 4). A conformant branch reads as before.
func TestReadHoldsTheConnectorsEndpointsToTheTable(t *testing.T) {
	const branch = "fylgja-fixture"
	for _, c := range []struct {
		name   string
		mutate func(map[string]any)
		want   findings.Finding
	}{
		{"moved to DcimCable", connectorEndpoints(""), findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSchemaFieldMissing,
			Object: "DcimConnector.connected_endpoints", Message: "DcimConnector has no relationship connected_endpoints; " +
				"the mapping reads it as opsmill/schema-library@26336e9 has it"}},
		{"to DcimInterface", connectorEndpoints("DcimInterface"), findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleSchemaFieldMismatch, Object: "DcimConnector.connected_endpoints",
			Message: "peer DcimEndpoint, found DcimInterface; the mapping reads it as opsmill/schema-library@26336e9 has it"}},
	} {
		t.Run(c.name, func(t *testing.T) { readAndCheckRefusedAlike(t, branch, c.mutate, c.want) })
	}
	t.Run("conformant", func(t *testing.T) { readsDevicesAndPorts(t, branch) })
}

// connectorEndpoints changes the generic DcimConnector's connected_endpoints: gone, with
// DcimCable declaring them itself rather than inheriting them, when peer is empty; to peer
// otherwise.
func connectorEndpoints(peer string) func(map[string]any) {
	return func(doc map[string]any) {
		for _, g := range doc["generics"].([]any) {
			generic := g.(map[string]any)
			if generic["kind"] != "DcimConnector" {
				continue
			}
			var rels []any
			for _, r := range generic["relationships"].([]any) {
				rel := r.(map[string]any)
				if rel["name"] == "connected_endpoints" {
					if peer == "" {
						continue
					}
					rel["peer"] = peer
				}
				rels = append(rels, rel)
			}
			generic["relationships"] = rels
		}
		if peer != "" {
			return
		}
		for _, n := range doc["nodes"].([]any) {
			if node := n.(map[string]any); node["kind"] == "DcimCable" {
				for _, r := range node["relationships"].([]any) {
					if rel := r.(map[string]any); rel["name"] == "connected_endpoints" {
						rel["inherited"] = false
					}
				}
			}
		}
	}
}

// readAndCheckRefusedAlike holds intent read and schema check of branch, its schema changed
// by mutate, to the one finding want: the read sends nothing past the schema, the Ports
// query above all, and writes no file.
func readAndCheckRefusedAlike(t *testing.T, branch string, mutate func(map[string]any), want findings.Finding) {
	t.Helper()
	f := newFakeInfrahub(t)
	f.schemaMutations = map[string]func(map[string]any){branch: mutate}
	f.start()
	out := filepath.Join(t.TempDir(), "ctm.json")

	code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{branch: branch, out: out}))
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Fatalf("exit %d, findings %+v; want 1 with exactly %+v", code, doc.Findings, want)
	}
	if ops := operations(f, branch); len(ops) != 0 {
		t.Errorf("%s was sent %v; want nothing past its schema, no Ports above all", branch, ops)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Error("a refused read left a file behind")
	}

	code, doc = exitOf(t, runCheck(t.Context(), &options{asJSON: true}, &checkFlags{branch: branch}))
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("schema check: exit %d, findings %+v; want the read's %+v", code, doc.Findings, want)
	}
}

// readsDevicesAndPorts holds a read of the conformant branch to its Devices and Ports.
func readsDevicesAndPorts(t *testing.T, branch string) {
	t.Helper()
	f := newFakeInfrahub(t)
	f.start()
	out := filepath.Join(t.TempDir(), "ctm.json")

	code, doc := exitOf(t, runRead(t.Context(), &options{asJSON: true}, &readFlags{branch: branch, out: out}))
	if code != findings.ExitOK || len(doc.Findings) != 0 {
		t.Fatalf("exit %d, findings %+v; want 0 and none", code, doc.Findings)
	}
	if ops := operations(f, branch); ops["Devices"] == 0 || ops["Ports"] == 0 {
		t.Errorf("%s was sent %v; want its Devices and Ports", branch, ops)
	}
}
