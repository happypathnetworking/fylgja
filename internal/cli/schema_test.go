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

// A conforming branch's answer is followed by the waypoint kind as the default branch holds
// it, whatever branch was checked: present, absent, or lacking what this build reads, one
// line and verified.waypoints, never a finding, the status and exit the conformance
// answer's (contracts/cli.md). A refused check asks nothing of the default
// branch.
func TestCheckNamesTheWaypointKind(t *testing.T) {
	const remedy = " (load schema/fylgja-waypoint.yaml; needed only by the waypoint commands)"
	for _, c := range []struct {
		name    string
		kind    []string
		line    string
		present bool
		missing []string
	}{
		{"present", intent.WaypointFields, "waypoints: FylgjaWaypoint present on the default branch", true, []string{}},
		{"absent", nil, "waypoints: FylgjaWaypoint absent from the default branch" + remedy, false, []string{}},
		{"lacks one", []string{"series", "sequence", "branch", "description"},
			"waypoints: FylgjaWaypoint on the default branch lacks as_of" + remedy, false, []string{"as_of"}},
		{"lacks two", []string{"series", "sequence", "branch"},
			"waypoints: FylgjaWaypoint on the default branch lacks as_of, description" + remedy, false, []string{"as_of", "description"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			f.kind = c.kind
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
			if doc.Status != findings.StatusOK || len(doc.Findings) != 0 || doc.Verified == nil || doc.Verified.Waypoints == nil {
				t.Fatalf("status %s, findings %+v, verified %+v; want ok, none and the waypoints", doc.Status, doc.Findings, doc.Verified)
			}
			// As the document writes it: missing is a list, empty when nothing is missing.
			got, _ := json.Marshal(doc.Verified.Waypoints)
			want, _ := json.Marshal(map[string]any{"kind": "FylgjaWaypoint", "present": c.present, "missing": c.missing,
				"file": "schema/fylgja-waypoint.yaml"})
			var g, w any
			_ = json.Unmarshal(got, &g)
			_ = json.Unmarshal(want, &w)
			if !reflect.DeepEqual(g, w) {
				t.Errorf("verified.waypoints %s, want %s", got, want)
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
