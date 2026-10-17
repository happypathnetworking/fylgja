package cli

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// runCheckDoc exercises the command flow exactly as the CLI does. Every case here
// stops before the first request, so none of it needs Infrahub.
func runCheckDoc(t *testing.T, f *checkFlags) (int, *findingsDoc) {
	t.Helper()
	err := runCheck(t.Context(), &options{asJSON: true}, f)
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runCheck returned %v, want a findings result", err)
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

// The one required flag is refused as a usage failure, before anything else.
func TestCheckRequiresBranch(t *testing.T) {
	code, doc := runCheckDoc(t, &checkFlags{})
	if code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Message != "--branch is required" {
		t.Fatalf("want one \"--branch is required\" finding, got %+v", doc.Findings)
	}
	if doc.Operation != findings.OpSchemaCheck {
		t.Errorf("operation = %q, want %q", doc.Operation, findings.OpSchemaCheck)
	}
}

// A missing credential is an operational failure naming the variable to set, and no
// request is sent.
func TestCheckMissingCredentialIsNamed(t *testing.T) {
	t.Setenv("INFRAHUB_ADDRESS", "http://localhost:8000")
	t.Setenv("INFRAHUB_API_TOKEN", "")

	code, doc := runCheckDoc(t, &checkFlags{branch: "fylgja-fixture"})
	if code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Fatalf("want one operation.failed finding, got %+v", doc.Findings)
	}
	if !strings.Contains(doc.Findings[0].Message, "INFRAHUB_API_TOKEN") {
		t.Errorf("message does not name the variable to set: %s", doc.Findings[0].Message)
	}
	if doc.Verified != nil {
		t.Error("a failed check reported something as verified")
	}
}

// `--at` was removed deliberately: the schema endpoint accepts only `branch` and
// `namespaces` and ignores an `at`, so a flag would promise a pinned
// answer nothing can give. The removal is asserted rather than remembered, because
// re-adding it would silently reintroduce that lie.
func TestCheckHasNoAtFlag(t *testing.T) {
	cmd := newSchemaCheckCmd(&options{})
	if f := cmd.Flags().Lookup("at"); f != nil {
		t.Error("schema check must not offer --at: the schema endpoint has no time axis")
	}
	if f := cmd.Flags().Lookup("branch"); f == nil {
		t.Error("schema check must offer --branch")
	}
}

// Every document this command produces names schema.check, including its failures: a
// machine reader routes on that field.
func TestCheckDocumentsNameTheOperation(t *testing.T) {
	t.Setenv("INFRAHUB_ADDRESS", "")
	t.Setenv("INFRAHUB_API_TOKEN", "")
	for _, f := range []*checkFlags{{}, {branch: "fylgja-fixture"}} {
		_, doc := runCheckDoc(t, f)
		if doc.Operation != findings.OpSchemaCheck {
			t.Errorf("operation = %q, want %q", doc.Operation, findings.OpSchemaCheck)
		}
	}
}

// A conforming branch's answer is followed by the stage kind and its extension as the
// default branch holds them, whatever branch was checked: present, absent, lacking an
// attribute or the relationship this build reads, or CoreProposedChange lacking the
// extension, one line and verified.stages, never a finding, the status and exit the
// conformance answer's (specs/014-proposed-change-stages/contracts/stage-commands.md). A
// refused check asks nothing of the default branch.
func TestCheckNamesTheStageKind(t *testing.T) {
	const remedy = " (load schema/fylgja-stage.yaml; needed only by --stage, stage list and stage plan)"
	const lacksExtension = "CoreProposedChange lacks fylgja_stages"
	for _, c := range []struct {
		name                        string
		kind                        []string
		noRelationship, noExtension bool
		line                        string
		present, extension          bool
		missing                     []string
	}{
		{"present", intent.StageFields, false, false,
			"stages: FylgjaStage present on the default branch, with its extension", true, true, []string{}},
		{"absent", nil, false, false,
			"stages: FylgjaStage absent from the default branch" + remedy, false, false, []string{}},
		{"lacks an attribute", []string{"label", "description"}, false, false,
			"stages: FylgjaStage on the default branch lacks as_of" + remedy, false, true, []string{"as_of"}},
		{"lacks the relationship", intent.StageFields, true, false,
			"stages: FylgjaStage on the default branch lacks proposed_change" + remedy, false, true, []string{"proposed_change"}},
		{"lacks the extension", intent.StageFields, false, true,
			"stages: FylgjaStage present on the default branch, but " + lacksExtension + remedy, true, false, []string{}},
		{"lacks an attribute and the extension", []string{"label", "description"}, false, true,
			"stages: FylgjaStage on the default branch lacks as_of, and " + lacksExtension + remedy, false, false, []string{"as_of"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			f.kind, f.noRelationship, f.noExtension = c.kind, c.noRelationship, c.noExtension
			f.start()

			var err error
			out := captureStdout(t, func() { err = runCheck(t.Context(), &options{}, &checkFlags{branch: "fylgja-fixture"}) })
			var res *result
			if !errors.As(err, &res) {
				t.Fatalf("runCheck returned %v, want a findings result", err)
			}
			lines := strings.Split(strings.TrimSuffix(out, "\n"), "\n")
			if len(lines) != 2 || !strings.HasPrefix(lines[0], "contract 0.2 ✓  FylgjaDevice ← NetworkDevice") || lines[1] != c.line {
				t.Errorf("stdout\n%s\nwant the contract line, then\n%s", out, c.line)
			}
			doc := res.doc
			if doc.Status != findings.StatusOK || len(doc.Findings) != 0 || doc.Verified == nil || doc.Verified.Stages == nil {
				t.Fatalf("status %s, findings %+v, verified %+v; want ok, none and the stages", doc.Status, doc.Findings, doc.Verified)
			}
			// As the document writes it: missing is a list, empty when nothing is missing.
			got, _ := json.Marshal(doc.Verified.Stages)
			want, _ := json.Marshal(map[string]any{"kind": "FylgjaStage", "present": c.present, "missing": c.missing,
				"extension": c.extension, "file": "schema/fylgja-stage.yaml"})
			var g, w any
			_ = json.Unmarshal(got, &g)
			_ = json.Unmarshal(want, &w)
			if !reflect.DeepEqual(g, w) {
				t.Errorf("verified.stages %s, want %s", got, want)
			}
			validateM10Document(t, doc)
			mustCarryNoToken(t, "schema check", out, doc)
		})
	}

	// The default branch no longer answering after the conformance read did is the
	// operation.failed that read would have given.
	unwell := newFakeInfrahub(t)
	unwell.defaultStatus = 500
	unwell.start()
	if code, doc := runCheckDoc(t, &checkFlags{branch: "fylgja-fixture"}); code != findings.ExitError || doc.Verified != nil ||
		len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		!strings.Contains(doc.Findings[0].Message, "the default branch") {
		t.Errorf("the default branch unwell: exit %d, %+v, verified %+v", code, doc.Findings, doc.Verified)
	}

	f := newFakeInfrahub(t)
	f.start()
	code, doc := runCheckDoc(t, &checkFlags{branch: "nosuch"})
	if code == findings.ExitOK || doc.Verified != nil {
		t.Errorf("a branch Infrahub does not know: exit %d, verified %+v", code, doc.Verified)
	}
	for _, r := range f.requests() {
		if r.Path == "/api/schema" && r.Query == "" {
			t.Errorf("a refused check asked the default branch's schema: %+v", r)
		}
	}
}
