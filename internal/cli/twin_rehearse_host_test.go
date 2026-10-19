package cli

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// US4's scenarios 4 and 5 through the harness (015, T034; contracts/server-and-host.md "The
// host: the reclaim and the refusals"): before a rehearsal starts, the twin a dead
// rehearsal left is destroyed through the destroy run, and anything else holding the host
// refuses it, as twin create is refused. Each test writes the twin directory it needs into
// a fresh state root, and pc-1 is the proposed change rehearseInfrahub serves.

// deadRun is the rehearsal run that left a twin and is no longer running.
const deadRun = "r0"

// rehearsalsTwin is the record a rehearsal's baseline wrote, twin.json 7 at change-1's
// seeded, of the rehearsal run of; nil is a hand twin of the same stage, whose rehearsal is
// null.
func rehearsalsTwin(t *testing.T, of *wire.RehearsalRef) wire.TwinRecord {
	t.Helper()
	return twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
		f.Rehearsal = of
	})
}

// reclaimingService is the fake workflow service whose destroy run removes what it says it
// removed: once it leaves nothing, the twin directory is gone and containerlab answers with
// no lab, as the host reads after a real destroy.
type reclaimingService struct {
	*fakeService
	paths lab.Paths
	clab  *fakeClab
	t     *testing.T
}

func (s *reclaimingService) StartDestroy(ctx context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	run, err := s.fakeService.StartDestroy(ctx, onEvent)
	if err == nil && len(run.Result.Cleanup.Remaining) == 0 {
		if rmErr := os.RemoveAll(s.paths.Twin); rmErr != nil {
			s.t.Error(rmErr)
		}
		empty, readErr := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-empty.json"))
		if readErr != nil {
			s.t.Error(readErr)
		}
		s.clab.stdout = empty
	}
	return run, err
}

// reclaimHost is a host holding the twin a dead rehearsal left: lab fylgja's three nodes, and
// its twin directory with record rec. It returns the state root's paths and containerlab.
func reclaimHost(t *testing.T, rec wire.TwinRecord) (lab.Paths, *fakeClab) {
	t.Helper()
	paths := useStateRoot(t)
	dryRunEnv(t)
	clab := useClab(t, "inspect-three.json")
	writeTwin(t, paths, rec)
	return paths, clab
}

// destroyOf is the reclaim's destroy run as the fake answers it, announced by its notice,
// cleaning up as cleanup says, with the run's findings list.
func destroyOf(svc *fakeService, cleanup provision.CleanupResult, list findings.List) {
	svc.destroyRun = destroyedRun(cleanup, list)
	svc.destroyEvents = []provision.Event{{Notice: "run fylgja-destroy run-d"}}
}

// Scenario 4: the twin of rehearsal run r0, which is no longer running, is reclaimed before
// the rehearsal starts. The notice and the destroy's lines come first, its event inside the
// answer before the start frame and with no run frame of its own; the warning
// rehearsal.twin.reclaimed names r0 and what the destroy removed; the report's reclaimed
// block says the same; then the rehearsal is started and runs as scenario 1's, exit 0.
func TestRehearseReclaimsADeadRehearsalsTwin(t *testing.T) {
	paths, clab := reclaimHost(t, rehearsalsTwin(t, &wire.RehearsalRef{WorkflowID: provision.WorkflowRehearse, RunID: deadRun}))
	rehearseInfrahub(t)
	svc := okRun()
	removed := []string{"lab fylgja (3 containers)", "twin directory " + paths.Twin}
	destroyOf(svc, provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone, Removed: removed}, nil)
	useService(t, &reclaimingService{fakeService: svc, paths: paths, clab: clab, t: t})

	a := ask(t, findings.OpTwinRehearse, api.RenderText, map[string]any{"branch": lessLink}, nil)
	if a.status != http.StatusOK {
		t.Fatalf("status %d", a.status)
	}
	f, doc := a.document(t, "the reclaim")
	satisfiesContract(t, findingsContract(t, currentContract), f.Document, "the reclaim's document")
	if doc.Status != findings.StatusOK {
		t.Fatalf("status %s, findings %v; want ok", doc.Status, rulesOf(doc.Findings))
	}

	// The destroy's event, then the rehearsal's own start, run and events: one run frame.
	want := append([]string{api.KindEvent}, runKinds(len(svc.rehearseEvents))...)
	if got := a.kinds(api.KindOut, api.KindErr); !slices.Equal(got, want) {
		t.Errorf("frames %v, want %v: the destroy followed before the start, with no run frame of its own", got, want)
	}
	for _, fr := range a.frames {
		if fr.Start != nil && fr.Start.WorkflowID != provision.WorkflowRehearse {
			t.Errorf("a start frame for %s; want fylgja-rehearse's alone", fr.Start.WorkflowID)
		}
	}
	if ev := a.events(); len(ev) == 0 || ev[0].Notice != "run fylgja-destroy run-d" {
		t.Errorf("the first event %+v, want the destroy's notice", ev)
	}

	out := a.text(api.KindOut)
	reclaim := "reclaiming the twin of rehearsal run " + deadRun + "\nrun fylgja-destroy run-d\n" +
		"removed lab fylgja (3 containers)\nremoved twin directory " + paths.Twin + "\n"
	at, baseline := strings.Index(out, reclaim), strings.Index(out, "stage "+seededRef+": created")
	if at < 0 || baseline < 0 || at > baseline {
		t.Errorf("the text does not reclaim before the run:\n%s", out)
	}

	reclaimed := findingOf(t, doc, findings.RuleRehearsalTwinReclaimed)
	if reclaimed.Severity != findings.Warning || reclaimed.Step != findings.StepDestroy || reclaimed.Object != deadRun ||
		reclaimed.Message != "the twin of rehearsal run r0, which is no longer running, was destroyed by destroy run run-d "+
			"before this rehearsal: it removed lab fylgja (3 containers), twin directory "+paths.Twin {
		t.Errorf("the warning %+v; want it to name r0, the destroy run and what it removed", reclaimed)
	}
	if doc.Rehearsal == nil || doc.Rehearsal.Reclaimed == nil {
		t.Fatalf("the report carries no reclaimed block: %+v", doc.Rehearsal)
	}
	if r := doc.Rehearsal.Reclaimed; r.Run != (findings.ShowRef{WorkflowID: provision.WorkflowRehearse, RunID: deadRun}) ||
		!slices.Equal(r.Cleanup.Removed, removed) || len(r.Cleanup.Remaining) != 0 ||
		r.Cleanup.Teardown != provision.CleanupDone || r.Cleanup.Unstage != provision.CleanupDone {
		t.Errorf("reclaimed %+v; want r0 and the destroy's clean cleanup", r)
	}
	if !slices.Equal(svc.calls, []string{"StartDestroy", "StartRehearse"}) || len(svc.rehearsed) != 1 {
		t.Errorf("the service was asked %v; want the destroy, then the one rehearsal", svc.calls)
	}
}

// Scenario 4, unclean: the reclaim's destroy leaves the lab. The rehearsal is refused with the
// destroy's cleanup.incomplete, exit 4, and is never started; the report's reclaimed block
// says what remains.
func TestRehearseReclaimLeavingTheHostUnclean(t *testing.T) {
	paths, clab := reclaimHost(t, rehearsalsTwin(t, &wire.RehearsalRef{WorkflowID: provision.WorkflowRehearse, RunID: deadRun}))
	rehearseInfrahub(t)
	svc := okRun()
	msg := "lab fylgja is still present after clab destroy (exited 0): n1 running; clear it with: clab destroy --name fylgja --cleanup"
	destroyOf(svc, provision.CleanupResult{Teardown: provision.CleanupFailed, Unstage: provision.CleanupDone,
		Removed: []string{"twin directory " + paths.Twin}, Remaining: []string{"lab fylgja"}},
		findings.List{{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete, Object: "lab fylgja",
			Step: findings.StepTeardown, Message: msg}})
	useService(t, &reclaimingService{fakeService: svc, paths: paths, clab: clab, t: t})
	useInterrupts(t)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	if code != findings.ExitUnclean || doc.Status != findings.StatusUnclean {
		t.Fatalf("exit %d, status %s; want 4, unclean\n%s", code, doc.Status, raw)
	}
	incomplete := findingOf(t, doc, findings.RuleCleanupIncomplete)
	if incomplete.Message != msg || incomplete.Severity != findings.Rejection {
		t.Errorf("cleanup.incomplete %+v; want the destroy's", incomplete)
	}
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleRehearsalTwinReclaimed {
			t.Errorf("an unclean reclaim filed %s: %+v", f.Rule, f)
		}
	}
	if doc.Rehearsal == nil || doc.Rehearsal.Reclaimed == nil ||
		!slices.Equal(doc.Rehearsal.Reclaimed.Cleanup.Remaining, []string{"lab fylgja"}) {
		t.Errorf("the report's reclaimed block %+v; want what remains named", doc.Rehearsal)
	}
	if !slices.Equal(svc.calls, []string{"StartDestroy"}) || len(svc.rehearsed) != 0 {
		t.Errorf("the service was asked %v; want the destroy alone, nothing started", svc.calls)
	}
}

// Scenario 5: whatever else holds the host refuses the rehearsal, exit 1, with nothing
// started or destroyed: a rehearsal in flight, or a step run as a check's child
// (run.in_flight, naming the run, before the host is read); a hand twin, whose record's rehearsal is null (host.twin.present, naming
// twin destroy); an orphan lab, refused as twin create refuses it; and a version 6 record,
// which reads with no rehearsal and is refused, not reclaimed.
func TestRehearseRefusedByWhatHoldsTheHost(t *testing.T) {
	version6 := func(t *testing.T, paths lab.Paths) {
		t.Helper()
		raw, err := json.Marshal(rehearsalsTwin(t, nil))
		if err != nil {
			t.Fatal(err)
		}
		var generic map[string]any
		if err := json.Unmarshal(raw, &generic); err != nil {
			t.Fatal(err)
		}
		generic["twin_version"] = "6"
		delete(generic, "rehearsal")
		if raw, err = json.Marshal(generic); err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, c := range []struct {
		name      string
		recording string
		twin      func(t *testing.T, paths lab.Paths)
		inFlight  []provision.RunInFlight
		rule      string
		// object and message are the refusal's object and what its message must hold.
		object  func(paths lab.Paths) string
		message []string
		// hostRead is whether the host was inspected before the refusal.
		hostRead bool
	}{
		{name: "a rehearsal in flight", recording: "inspect-three.json",
			twin: func(t *testing.T, paths lab.Paths) {
				writeTwin(t, paths, rehearsalsTwin(t, &wire.RehearsalRef{WorkflowID: provision.WorkflowRehearse, RunID: deadRun}))
			},
			inFlight: []provision.RunInFlight{{WorkflowID: provision.WorkflowRehearse, RunID: deadRun, Step: "observe"}},
			rule:     findings.RuleRunInFlight, object: func(lab.Paths) string { return provision.WorkflowRehearse },
			message: []string{"rehearsal run r0 is already in flight", "fylgja twin destroy"}},
		{name: "a step run in flight under a check", recording: "inspect-three.json",
			inFlight: []provision.RunInFlight{{WorkflowID: "fylgja-reconcile", RunID: "c1",
				Child: &provision.RunInFlight{WorkflowID: provision.WorkflowStep, RunID: "s1", Step: "push"}}},
			rule: findings.RuleRunInFlight, object: func(lab.Paths) string { return provision.WorkflowStep },
			message: []string{"step run s1 is already in flight"}},
		{name: "a hand twin", recording: "inspect-three.json", hostRead: true,
			twin: func(t *testing.T, paths lab.Paths) { writeTwin(t, paths, rehearsalsTwin(t, nil)) },
			rule: findings.RuleHostTwinPresent, object: func(p lab.Paths) string { return p.Twin },
			message: []string{"is present, the twin of branch fylgja-fixture", "fylgja twin destroy clears it"}},
		{name: "an orphan lab", recording: "inspect-one-orphan.json", hostRead: true,
			rule: findings.RuleHostLabPresent, object: func(lab.Paths) string { return "lab fylgja" },
			message: []string{"lab fylgja is present (1 node), an orphan: no twin.json records it", "fylgja twin destroy clears it"}},
		{name: "a version 6 record", recording: "inspect-three.json", hostRead: true, twin: version6,
			rule: findings.RuleHostTwinPresent, object: func(p lab.Paths) string { return p.Twin },
			message: []string{"is present, the twin of branch fylgja-fixture", "fylgja twin destroy clears it"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			dryRunEnv(t)
			clab := useClab(t, c.recording)
			if c.twin != nil {
				c.twin(t, paths)
			}
			rehearseInfrahub(t)
			svc := okRun()
			svc.inFlight = c.inFlight
			useService(t, svc)
			useInterrupts(t)

			code, doc, raw := rehearseDoc(t, "--branch", lessLink)
			if code != findings.ExitRejected || doc.Status != findings.StatusRejected {
				t.Fatalf("exit %d, status %s; want 1, rejected\n%s", code, doc.Status, raw)
			}
			refusal := findingOf(t, doc, c.rule)
			if refusal.Severity != findings.Rejection || refusal.Object != c.object(paths) {
				t.Errorf("%s %+v; want a rejection on %s", c.rule, refusal, c.object(paths))
			}
			for _, part := range c.message {
				if !strings.Contains(refusal.Message, part) {
					t.Errorf("%s's message %q lacks %q", c.rule, refusal.Message, part)
				}
			}
			for _, f := range doc.Findings {
				if f.Rule == findings.RuleRehearsalTwinReclaimed {
					t.Errorf("the host was reclaimed: %+v", f)
				}
			}
			if len(svc.calls) != 0 || len(svc.rehearsed) != 0 || svc.destroys != 0 {
				t.Errorf("the service was asked %v; want nothing started or destroyed", svc.calls)
			}
			if read := len(clab.calls) != 0; read != c.hostRead {
				t.Errorf("the host was read %v (%v); want %v", read, clab.calls, c.hostRead)
			}
			if c.twin != nil {
				if _, err := os.Stat(paths.TwinJSON); err != nil {
					t.Errorf("the twin record is gone: %v", err)
				}
			}
		})
	}
}
