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
			if len(lines) != 2 || lines[0] != conformantLine || lines[1] != c.line {
				t.Errorf("stdout\n%s\nwant\n%s\n%s", out, conformantLine, c.line)
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

// conformantLine is schema check's success line on a branch holding the library at the
// pinned commit (contracts/scope-and-commands.md).
const conformantLine = "conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, " +
	"OrganizationManufacturer, InterfacePhysical, DcimCable"

// A conformant branch's answer names the commit and the kinds, and --json's verified
// block names each kind's fields, valid against the current contract (FR-013; US3
// scenario 1). A branch whose DCIM differs is refused with every difference in one
// document, each naming the commit, and nothing verified; nothing is asked of the default
// branch for it (US3 scenario 2).
func TestCheckReportsTheMappingsTable(t *testing.T) {
	f := newFakeInfrahub(t)
	f.change("pc-1", "diverged")
	f.schemaMutations = map[string]func(map[string]any){"diverged": func(doc map[string]any) {
		var nodes []any
		for _, n := range doc["nodes"].([]any) {
			node := n.(map[string]any)
			switch node["kind"] {
			case "DcimCable":
				continue
			case "DcimPlatform":
				for _, a := range node["attributes"].([]any) {
					if attr := a.(map[string]any); attr["name"] == "name" {
						attr["kind"] = "Number"
					}
				}
			}
			nodes = append(nodes, node)
		}
		doc["nodes"] = nodes
	}}
	f.start()

	var err error
	out := captureStdout(t, func() { err = runCheck(t.Context(), &options{}, &checkFlags{branch: "fylgja-fixture"}) })
	if !strings.HasPrefix(out, conformantLine+"\n") {
		t.Errorf("stdout\n%s\nwant it to begin\n%s", out, conformantLine)
	}
	var res *result
	if !errors.As(err, &res) {
		t.Fatalf("runCheck returned %v, want a findings result", err)
	}

	code, doc := runCheckDoc(t, &checkFlags{branch: "fylgja-fixture"})
	if code != findings.ExitOK || len(doc.Findings) != 0 || doc.Verified == nil {
		t.Fatalf("exit %d, findings %+v, verified %+v; want 0, none and the block", code, doc.Findings, doc.Verified)
	}
	want := []findings.KindFields{
		{Kind: "DcimDevice", Fields: []string{"name", "tags", "platform", "interfaces", "artifacts"}},
		{Kind: "DcimPlatform", Fields: []string{"name", "manufacturer"}},
		{Kind: "OrganizationManufacturer", Fields: []string{"name"}},
		{Kind: "InterfacePhysical", Fields: []string{"name", "role", "status", "device", "connector"}},
		{Kind: "DcimCable", Fields: []string{"connected_endpoints"}},
	}
	if v := doc.Verified; v.Model != "opsmill/schema-library" || v.Version != "26336e9" || !reflect.DeepEqual(v.Kinds, want) {
		t.Errorf("verified %+v, want the library at 26336e9 with %+v", v, want)
	}
	if err := runCheck(t.Context(), &options{asJSON: true}, &checkFlags{branch: "fylgja-fixture"}); !asResult(err, &res) {
		t.Fatalf("runCheck returned %v, want a findings result", err)
	}
	validateM10Document(t, res.doc)

	before := len(f.requests())
	code, doc = runCheckDoc(t, &checkFlags{branch: "diverged"})
	if code != findings.ExitRejected || doc.Verified != nil {
		t.Errorf("a diverged branch: exit %d, verified %+v; want %d and nothing verified", code, doc.Verified, findings.ExitRejected)
	}
	type got struct{ rule, object string }
	var rules []got
	for _, fd := range doc.Findings {
		rules = append(rules, got{fd.Rule, fd.Object})
		if !strings.HasSuffix(fd.Message, "opsmill/schema-library@26336e9 has it") {
			t.Errorf("%s %s does not name the commit: %s", fd.Rule, fd.Object, fd.Message)
		}
	}
	if w := []got{{findings.RuleSchemaFieldMismatch, "DcimPlatform.name"}, {findings.RuleSchemaKindMissing, "DcimCable"}}; !reflect.DeepEqual(rules, w) {
		t.Errorf("findings %v, want %v in one document", rules, w)
	}
	if err := runCheck(t.Context(), &options{asJSON: true}, &checkFlags{branch: "diverged"}); !asResult(err, &res) {
		t.Fatalf("runCheck returned %v, want a findings result", err)
	}
	validateM10Document(t, res.doc)
	// No step on schema.check: the conformance rules are a read's step read alone
	// (contracts/scope-and-commands.md).
	for _, fd := range res.doc.Findings {
		if fd.Step != "" {
			t.Errorf("%s %s carries step %s on schema check", fd.Rule, fd.Object, fd.Step)
		}
	}
	for _, r := range f.requests()[before:] {
		if r.Path == "/api/schema" && r.Query == "" {
			t.Errorf("a refused check asked the default branch's schema: %+v", r)
		}
	}
}
