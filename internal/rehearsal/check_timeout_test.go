package rehearsal_test

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
)

// beforeStart is the time allowed the server on a rehearsal's request before the run's start:
// the plan of every stage, a reclaim and the host check, an allowance the server does not
// enforce (FR-021; data-model §4).
const beforeStart = 300 * time.Second

// commentSaves is what fylgja-twin did after its answer before 020's T029: a thread and its
// comment, each saved by the SDK with its default timeout of 60 s. The rehearse flow posts
// them now, and CLOSE_MARGIN_S still covers the bound: the check's reads of the run's
// document and out lines, each bounded by 30 s, come after it.
const commentSaves = 2 * 60 * time.Second

// fylgja-twin's bounds, held against the rehearsal's (FR-006, FR-007, FR-021; R-09, R-16).
// Its own deadline, its timeout less its margin, is where it interrupts the run, so it must
// outlast a rehearsal that uses every budget: the ceiling, the destroy's whole budget and the
// allowance before the start, which are also what a retry must still find left (DESTROY_S,
// ALLOWANCE_S). Its timeout, which Infrahub makes its task timeout at import, cuts it and
// leaves its validator in_progress (research §1.4), so the read after the interrupt, the
// margin less CLOSE_MARGIN_S, must cover the destroy the interrupted run goes on to, and
// CLOSE_MARGIN_S the comment's saves after an answer read just before it. The checks are
// Python, read from their source; the budgets are the mechanism constants and the largest
// destroy budget of the packages.
func TestTheTwinCheckOutlastsItsRehearsal(t *testing.T) {
	checks := filepath.Join("..", "..", "infrahub", "checks")
	src, err := os.ReadFile(filepath.Join(checks, "fylgja_twin.py"))
	if err != nil {
		t.Fatal(err)
	}
	shared, err := os.ReadFile(filepath.Join(checks, "fylgja_api.py"))
	if err != nil {
		t.Fatal(err)
	}
	timeout := pythonSeconds(t, src, `(?m)^    timeout = (\d+)$`, "fylgja_twin.py's timeout")
	margin := pythonSeconds(t, src, `(?m)^DEADLINE_MARGIN_S = (\d+)$`, "fylgja_twin.py's DEADLINE_MARGIN_S")
	destroyS := pythonSeconds(t, src, `(?m)^DESTROY_S = (\d+)$`, "fylgja_twin.py's DESTROY_S")
	allowance := pythonSeconds(t, src, `(?m)^ALLOWANCE_S = (\d+)$`, "fylgja_twin.py's ALLOWANCE_S")
	closeMargin := pythonSeconds(t, shared, `(?m)^CLOSE_MARGIN_S = (\d+)$`, "fylgja_api.py's CLOSE_MARGIN_S")

	pkgs, err := psp.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	largest := 0
	for _, p := range pkgs {
		largest = max(largest, p.Image.DestroyTimeoutS)
	}
	m := provision.DeadlineMechanism()
	destroy := m.PlanTeardown + time.Duration(largest)*time.Second + m.Unstage

	own := timeout - margin
	if want := rehearsal.Ceiling + destroy + beforeStart; own < want {
		t.Errorf("fylgja-twin's own deadline is %s (timeout %s less %s): a rehearsal using every budget needs %s "+
			"(the ceiling %s, the destroy %s, the allowance before the start %s), and the check would interrupt it",
			own, timeout, margin, want, rehearsal.Ceiling, destroy, beforeStart)
	}
	if destroyS < destroy || allowance != beforeStart {
		t.Errorf("fylgja-twin retries while %s, the destroy, and %s, the allowance, remain beside the run's deadline; "+
			"want at least the destroy's budget %s and the allowance %s", destroyS, allowance, destroy, beforeStart)
	}
	if own < rehearsal.Ceiling+destroyS+allowance {
		t.Errorf("fylgja-twin's own deadline %s is under the ceiling %s, DESTROY_S %s and ALLOWANCE_S %s: "+
			"its first ask could start a run it would interrupt", own, rehearsal.Ceiling, destroyS, allowance)
	}
	if read := margin - closeMargin; read < destroy {
		t.Errorf("fylgja-twin reads %s after its interrupt (DEADLINE_MARGIN_S %s less CLOSE_MARGIN_S %s), under the "+
			"destroy's budget %s: it would stop reading before the run it interrupted had destroyed its twin",
			read, margin, closeMargin, destroy)
	}
	if closeMargin < commentSaves {
		t.Errorf("CLOSE_MARGIN_S is %s, under the %s the comment's two saves may take: Infrahub would cut the check, "+
			"leaving its validator in_progress, while it posted the report", closeMargin, commentSaves)
	}
}

// pythonSeconds is the one integer pattern's group reads in a Python source, as seconds.
func pythonSeconds(t *testing.T, src []byte, pattern, what string) time.Duration {
	t.Helper()
	all := regexp.MustCompile(pattern).FindAllSubmatch(src, -1)
	if len(all) != 1 {
		t.Fatalf("%s is set %d times, want once", what, len(all))
	}
	n, err := strconv.Atoi(string(all[0][1]))
	if err != nil {
		t.Fatal(err)
	}
	return time.Duration(n) * time.Second
}
