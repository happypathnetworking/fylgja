//go:build contract

package intent

import (
	"encoding/json"
	"maps"
	"slices"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// A branch can hold intent Infrahub is perfectly happy with and Fylgja cannot build.
// Every such defect is reported in one pass, by name, against the object at fault, and
// no CTM is written.
//
// The three seeded here are the library's (017): a seeded branch, in the schema library's
// kinds, with a cable joining two ports of n1, a cable from n2's ethernet-1/99, which the
// SR Linux package's rule matches out of its range, and an uncabled port of n3 that no rule
// of the package matches. Infrahub accepts each, and validation refuses each, as it would a
// CTM fixture holding them. The read's own refusals, a device's platform and the scope,
// are read_contract_test.go's, and come before validation: no CTM reaches it beside them.
// The others Infrahub refuses on create (a duplicate device name, a dangling port) or the
// read cannot produce (a missing required attribute, a one-ended link, which is an omitted
// cable), so they are covered by the CTM fixtures under testdata/ctm/defects instead.
func TestSeededDefectsAreAllReportedInOnePass(t *testing.T) {
	c, branch := seeded(t, "defects")
	for _, p := range []struct{ device, port string }{
		{"n1", "ethernet-1/5"}, {"n1", "ethernet-1/6"}, {"n2", "ethernet-1/99"}, {"n3", "ethernet-1/3"}, {"n3", "console"},
	} {
		if err := c.AddInterface(branch, p.device, p.port); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddCable(branch, "c-loop", "n1:ethernet-1/5", "n1:ethernet-1/6"); err != nil {
		t.Fatal(err)
	}
	if err := c.AddCable(branch, "c-far", "n2:ethernet-1/99", "n3:ethernet-1/3"); err != nil {
		t.Fatal(err)
	}

	snapshot, list, _, err := readUnder(t, branch, "", fixtureScope)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	if list.Rejected() || snapshot == nil {
		t.Fatalf("the read itself refused the branch, before validation: %v", list)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	list = append(list, validate.Validate(snapshot, nil, reg, nil)...)

	// The --json document is the contract, so the assertions are made against the
	// serialized shape rather than the in-memory list. This is the document `intent read`
	// emits, which writes no CTM precisely when its status is "rejected".
	raw, err := json.Marshal(findings.NewDocument(findings.OpIntentRead,
		&findings.Subject{Branch: branch, Scope: fixtureScope, Out: "would-be.json"}, list))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Status   string `json:"status"`
		Findings []struct {
			Severity string `json:"severity"`
			Rule     string `json:"rule"`
			Object   string `json:"object"`
			Message  string `json:"message"`
		} `json:"findings"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Status != string(findings.StatusRejected) {
		t.Fatalf("status = %q, want rejected: %+v", doc.Status, doc.Findings)
	}

	// All three, in one pass: an operator fixing intent wants every problem at once, not
	// one problem per attempt. Nothing else is a rejection.
	got := map[string]string{}
	for _, f := range doc.Findings {
		if f.Message == "" {
			t.Errorf("finding %s on %s carries no message", f.Rule, f.Object)
		}
		if f.Severity == string(findings.Rejection) {
			if _, twice := got[f.Rule]; twice {
				t.Errorf("%s reported twice: %s and %s", f.Rule, got[f.Rule], f.Object)
			}
			got[f.Rule] = f.Object
		}
	}
	want := map[string]string{
		findings.RuleLinkEndpointsSameDev:   "n1:ethernet-1/5|n1:ethernet-1/6",
		findings.RuleUnmappableLinked:       "n2:ethernet-1/99",
		findings.RuleInterfaceRuleUnmatched: "n3:console",
	}
	if !maps.Equal(got, want) {
		t.Errorf("rejections by rule %v (%v)\nwant exactly %v", got, slices.Sorted(maps.Keys(got)), want)
	}
}
