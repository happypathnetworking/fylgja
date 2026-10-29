package server

import (
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// A destroy detached (020; US4 scenario 6) still waits for what it cancels first, whose
// progress it prints as the stream does, since the destroy run starts only once that has
// closed; it then answers at the destroy run once a worker has taken it, with the run frame
// its stream never wrote, and nothing follows the destroy or reads its result.
func TestADetachedDestroyAnswersAtItsRun(t *testing.T) {
	useStateRoot(t)
	_, frames, svc := detachedAnswer(t, findings.OpTwinDestroy)
	out, doc := detachedOf(t, frames)
	id := detachedRunIDs[provision.WorkflowDestroy]
	want := "cancelling provisioning run p1; waiting for its cleanup\nstep teardown: begins\n" +
		"provisioning run p1 closed: cancelled\nrun fylgja-destroy " + id + "\n"
	if out != want {
		t.Errorf("printed\n%s\nwant\n%s", out, want)
	}
	if svc.destroys != 1 || doc.Subject.RunID != id || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunDetached {
		t.Errorf("%d destroys, document %+v; want one, answered at run %s by run.detached", svc.destroys, doc, id)
	}
	if strings.Contains(out, "removed ") || strings.Contains(out, "nothing to remove") {
		t.Errorf("a detached destroy printed a cleanup it never read:\n%s", out)
	}
}
