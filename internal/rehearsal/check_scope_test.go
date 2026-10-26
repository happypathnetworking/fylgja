package rehearsal_test

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
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
