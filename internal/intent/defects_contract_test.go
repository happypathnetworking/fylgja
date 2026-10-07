//go:build contract

package intent

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// A branch can hold intent Infrahub is perfectly happy with and Fylgja cannot build.
// Every such defect is reported in one pass, by name, against the object at fault, and
// no CTM is written.
//
// The five seeded here are exactly the five the reference schema will accept: the
// others — a missing required attribute, a duplicate device name, a one-endpoint link,
// a dangling parent — Infrahub refuses on create, so they are covered by the CTM
// fixtures under testdata/ctm/defects instead.
func TestSeededDefectsAreAllReportedInOnePass(t *testing.T) {
	c, branch := throwaway(t, "defects")
	if err := c.LoadSchema(branch, filepath.Join(repoRoot(), "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedDefects(branch); err != nil {
		t.Fatalf("seeding defects: %v", err)
	}

	cfg, err := FromEnv(branch, "")
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	client := New(cfg)
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()

	observedAt := time.Now().UTC().Format("2006-01-02T15:04:05.000000Z")
	conf, list, err := client.CheckConformance(ctx)
	if err != nil {
		t.Fatalf("checking conformance: %v", err)
	}
	if list.Rejected() {
		t.Fatalf("the seeded branch must conform; the defects are in intent, not the schema: %v", list)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	snapshot, artifactFindings, err := client.Fetch(ctx, conf, observedAt, reg)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	list = append(list, artifactFindings...)
	list = append(list, validate.Validate(snapshot, reg)...)

	// The --json document is the contract, so the assertions are made against
	// the serialized shape rather than the in-memory list. This is the document
	// `intent read` emits: the command builds it the same way, and writes no CTM
	// precisely when its status is "rejected" (cmd/fylgja/intent.go).
	raw, err := json.Marshal(findings.NewDocument(findings.OpIntentRead,
		&findings.Subject{Branch: branch, Out: "would-be.json"}, list))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Operation string `json:"operation"`
		Status    string `json:"status"`
		Findings  []struct {
			Severity string `json:"severity"`
			Rule     string `json:"rule"`
			Object   string `json:"object"`
			Message  string `json:"message"`
		} `json:"findings"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}

	if doc.Operation != findings.OpIntentRead {
		t.Errorf("operation = %q, want %q", doc.Operation, findings.OpIntentRead)
	}
	// Rejected is what makes the read write nothing: a CTM is written only when no
	// finding is a rejection.
	if doc.Status != string(findings.StatusRejected) {
		t.Fatalf("status = %q, want rejected: %+v", doc.Status, doc.Findings)
	}

	// One of the seeded defects draws a warning beside its rejection from M7 on, and it
	// is named here rather than tolerated in general: d1:lo0 is a loopback marked
	// out-of-band, so the profile's management rule renders it to the management port and
	// the node's name for it is not lo0 — which is what artifact.interface.unrepresented
	// says of an artifact that names it. The warning changes
	// nothing about the read: the document is still rejected and no CTM is written.
	byRule := map[string][]string{}
	for _, f := range doc.Findings {
		if f.Object == "" {
			t.Errorf("finding %s names no object", f.Rule)
		}
		if f.Message == "" {
			t.Errorf("finding %s carries no message", f.Rule)
		}
		if f.Severity != string(findings.Rejection) {
			if f.Severity != string(findings.Warning) || f.Rule != findings.RuleArtifactInterfaceUnrepresented ||
				f.Object != testsupport.SeededDefectObjects[findings.RuleMgmtOnlyIftype] {
				t.Errorf("finding %s on %s is %s; the only finding here that is not a rejection is "+
					"%s on the out-of-band loopback", f.Rule, f.Object, f.Severity, findings.RuleArtifactInterfaceUnrepresented)
			}
			continue
		}
		byRule[f.Rule] = append(byRule[f.Rule], f.Object)
	}

	// All five, in one pass: an operator fixing intent wants every problem at once,
	// not one problem per attempt.
	for _, rule := range testsupport.SeededDefects {
		objects, ok := byRule[rule]
		if !ok {
			t.Errorf("%s was not reported; reported: %v", rule, byRule)
			continue
		}
		if len(objects) != 1 {
			t.Errorf("%s reported %d times, want once: %v", rule, len(objects), objects)
		}
		want := testsupport.SeededDefectObjects[rule]
		if len(objects) > 0 && objects[0] != want {
			t.Errorf("%s names %q, want %q", rule, objects[0], want)
		}
	}
	if len(byRule) != len(testsupport.SeededDefects) {
		t.Errorf("%d rules rejected, want exactly the %d seeded defects: %v",
			len(byRule), len(testsupport.SeededDefects), byRule)
	}
}
