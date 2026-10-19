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

// beforeStart is the time the server may spend on a rehearsal's request before the run's
// start: the plan of every stage, a reclaim and the host check (data-model §4).
const beforeStart = 300 * time.Second

// fylgja-twin's two bounds, held against the rehearsal's (FR-006, FR-021; R-09, R-16). Its
// own deadline, its timeout less its margin, is where it interrupts the run, so it must
// outlast a rehearsal that uses every budget: the ceiling, the destroy's whole budget and the
// work before the start. Its timeout, which Infrahub makes its task timeout at import, cuts
// it and leaves its validator in_progress (research §1.4), so the margin must cover the
// destroy the interrupted run goes on to. The check is Python, read from its source; the
// budgets are the mechanism constants and the largest destroy budget of the packages.
func TestTheTwinCheckOutlastsItsRehearsal(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "..", "infrahub", "checks", "fylgja_twin.py"))
	if err != nil {
		t.Fatal(err)
	}
	timeout := pythonSeconds(t, src, `(?m)^    timeout = (\d+)$`, "the class's timeout")
	margin := pythonSeconds(t, src, `(?m)^DEADLINE_MARGIN_S = (\d+)$`, "DEADLINE_MARGIN_S")

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
			"(the ceiling %s, the destroy %s, the work before the start %s), and the check would interrupt it",
			own, timeout, margin, want, rehearsal.Ceiling, destroy, beforeStart)
	}
	if margin < destroy {
		t.Errorf("fylgja-twin's margin is %s, under the destroy's budget %s: Infrahub would cut the check, leaving its "+
			"validator in_progress, before the run it interrupted had destroyed its twin", margin, destroy)
	}
}

// pythonSeconds is the one integer pattern's group reads in a Python source, as seconds.
func pythonSeconds(t *testing.T, src []byte, pattern, what string) time.Duration {
	t.Helper()
	all := regexp.MustCompile(pattern).FindAllSubmatch(src, -1)
	if len(all) != 1 {
		t.Fatalf("fylgja_twin.py sets %s %d times, want once", what, len(all))
	}
	n, err := strconv.Atoi(string(all[0][1]))
	if err != nil {
		t.Fatal(err)
	}
	return time.Duration(n) * time.Second
}
