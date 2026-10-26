package rehearsal_test

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

// The checks pass no scope (FR-021): each asks its one operation with the branch alone, so
// its read is under the server's default scope. A server with no default refuses such a
// request scope.unset, exit 2 (internal/server's TestScopeOf), a document of status error,
// and each check concludes that document as failure, by log_error (spec Edge Cases, beside
// FR-018): fylgja-step's refuses passes ok alone and the branch point's lone scope.empty, and
// fylgja-twin asks again only on a rejected document naming the host held, concluding every
// status but ok by log_error. The checks are Python, read from their source as
// TestTheTwinCheckOutlastsItsRehearsal reads them.
func TestTheChecksPassNoScopeAndFailAnError(t *testing.T) {
	checks := filepath.Join("..", "..", "infrahub", "checks")
	read := func(name string) string {
		t.Helper()
		src, err := os.ReadFile(filepath.Join(checks, name))
		if err != nil {
			t.Fatal(err)
		}
		return string(src)
	}
	// Each request is fylgja_api's call(address, token, path("<operation>"), RENDER_<form>,
	// <args>, …): args is the request's arguments, the scope among them were one given.
	request := regexp.MustCompile(`\bcall\(\s*address,\s*token,\s*path\("([a-z.]+)"\),\s*RENDER_[A-Z]+,\s*(\{[^{}]*\})`)
	for name, op := range map[string]string{"fylgja_step.py": "stage.plan", "fylgja_twin.py": "twin.rehearse"} {
		src := read(name)
		calls := request.FindAllStringSubmatch(src, -1)
		if n := len(regexp.MustCompile(`\bcall\(`).FindAllString(src, -1)); len(calls) != 1 || n != 1 {
			t.Fatalf("%s: %d requests read of %d calls; want its one request, read", name, len(calls), n)
		}
		if got := calls[0]; got[1] != op || got[2] != `{"branch": self.branch_name}` {
			t.Errorf("%s asks %s with %s; want %s with the branch alone, no scope", name, got[1], got[2], op)
		}
	}
	for _, name := range []string{"fylgja_api.py", "fylgja_step.py", "fylgja_twin.py"} {
		if src := read(name); strings.Contains(src, `"scope"`) || strings.Contains(src, `'scope'`) {
			t.Errorf("%s names a scope argument; the checks pass none (FR-021)", name)
		}
	}

	// The statuses the checks compare a document's with are the findings contract's.
	if findings.StatusOK != "ok" || findings.StatusRejected != "rejected" || findings.StatusError != "error" {
		t.Fatalf("the document's statuses are %q, %q and %q; the checks compare with ok and rejected",
			findings.StatusOK, findings.StatusRejected, findings.StatusError)
	}
	for _, c := range []struct{ name, what, pattern string }{
		{"fylgja_step.py", "refuses passes ok, and fails every status but rejected, an error included",
			`status = document\.get\("status"\)\s+if status == "ok":\s+return False\s+if status != "rejected":\s+return True\n`},
		{"fylgja_step.py", "a document refuses concludes by log_error",
			`if refuses\(document\):\s+self\.log_error\(`},
		{"fylgja_twin.py", "holders names no holder of a document not rejected, so an error is final and not asked again",
			`if document\.get\("status"\) != "rejected":\s+return \[\]\n`},
		{"fylgja_twin.py", "the final answer concludes every status but ok by log_error",
			`if status == "ok" and not said:\s+if text:\s+self\.log_info\(text\)\s+return\s+` +
				`said\.append\(text or f"the rehearsal ended \{status\} with no finding"\)\s+self\.log_error\("\\n"\.join\(said\)\)`},
	} {
		if !regexp.MustCompile(c.pattern).MatchString(read(c.name)) {
			t.Errorf("%s no longer reads as: %s", c.name, c.what)
		}
	}
}

// FR-017's one exception, as the checks hold it beside the server (017's FR-015;
// contracts/scope-and-commands.md, scope.empty): fylgja_api's branch_point_refusal excuses
// a branch point whose one rejection is scope.empty at read, as internal/server's
// passedOver does, and nothing else. Its three values are the findings contract's and the
// stage's, and the excuse compares all three with the one rejection; fylgja-step and
// fylgja-twin's holders decide by it alone.
func TestTheChecksExcuseTheBranchPointAsTheServerDoes(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "..", "infrahub", "checks", "fylgja_api.py"))
	if err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{
		"RULE_SCOPE_EMPTY": findings.RuleScopeEmpty, "STEP_READ": findings.StepRead, "AT_BRANCH_POINT": stages.AtBranchPoint,
	} {
		m := regexp.MustCompile(`(?m)^` + name + ` = "([^"]*)"$`).FindSubmatch(src)
		if m == nil || string(m[1]) != want {
			t.Errorf("fylgja_api.py's %s is %q; want %q", name, m, want)
		}
	}
	fn := regexp.MustCompile(`(?s)\ndef branch_point_refusal\(.*?\n(?:def |$)`).Find(src)
	if fn == nil {
		t.Fatal("fylgja_api.py defines no branch_point_refusal")
	}
	for _, c := range []struct{ what, pattern string }{
		{"the stage is the branch point", `if stage\.get\("at_source"\) != AT_BRANCH_POINT:\s+continue\n`},
		{"its rejections are one, scope.empty at read",
			`if \(\s*len\(rejections\) == 1\s+and rejections\[0\]\.get\("rule"\) == RULE_SCOPE_EMPTY\s+` +
				`and rejections\[0\]\.get\("step"\) == STEP_READ\s*\):\s+return rejections\n`},
	} {
		if !regexp.MustCompile(c.pattern).Match(fn) {
			t.Errorf("branch_point_refusal no longer reads as: %s\n%s", c.what, fn)
		}
	}
}
