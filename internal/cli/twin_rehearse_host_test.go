package cli

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// US4's scenario 5 through the harness (015, T034; contracts/server-and-host.md "The host:
// the refusals"): anything holding the host refuses a rehearsal, as twin create is refused.
// A record names no rehearsal since twin.json 12, so the twin a dead rehearsal left is no
// longer reclaimed: it holds the host as any twin does (020, research R-06). Each test
// writes the twin directory it needs into a fresh state root, and pc-1 is the proposed
// change rehearseInfrahub serves.

// deadRun is the rehearsal run that left a twin and is no longer running.
const deadRun = "r0"

// rehearsalsTwin is the record a rehearsal's baseline writes, this build's twin.json at
// change-1's seeded, which names no rehearsal.
func rehearsalsTwin(t *testing.T) wire.TwinRecord {
	t.Helper()
	return twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
	})
}

// Scenario 5: whatever holds the host refuses the rehearsal, exit 1, with nothing started
// or destroyed: a rehearsal in flight, or a step run as a check's child (run.in_flight,
// naming the run, before the host is read); a twin of this build (host.twin.present, naming
// twin destroy); a record of twin.json 11 naming the dead rehearsal that left it, which is
// refused as any twin is and no longer reclaimed (020, research R-06); an orphan lab,
// refused as twin create refuses it; and a version 6 record, refused the same.
func TestRehearseRefusedByWhatHoldsTheHost(t *testing.T) {
	// earlier writes the twin's record as an earlier build wrote it, edited by edit.
	earlier := func(t *testing.T, paths lab.Paths, edit func(map[string]any)) {
		t.Helper()
		raw, err := json.Marshal(rehearsalsTwin(t))
		if err != nil {
			t.Fatal(err)
		}
		var generic map[string]any
		if err := json.Unmarshal(raw, &generic); err != nil {
			t.Fatal(err)
		}
		edit(generic)
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
	version6 := func(t *testing.T, paths lab.Paths) {
		earlier(t, paths, func(generic map[string]any) {
			generic["twin_version"] = "6"
			unsnapshotted(generic)
			contractProvenance(generic)
		})
	}
	// version11 is the record 016's build wrote for a rehearsal's baseline: its stage and the
	// rehearsal run that wrote it, r0, no longer running.
	version11 := func(t *testing.T, paths lab.Paths) {
		earlier(t, paths, func(generic map[string]any) {
			generic["twin_version"] = "11"
			generic["stage"] = map[string]any{"proposed_change": map[string]any{"id": "pc-1", "branch": lessLink},
				"label": "seeded", "description": "", "at_source": findings.AtSourceWritten}
			generic["rehearsal"] = map[string]any{"workflow_id": provision.WorkflowRehearse, "run_id": deadRun}
		})
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
				writeTwin(t, paths, rehearsalsTwin(t))
			},
			inFlight: []provision.RunInFlight{{WorkflowID: provision.WorkflowRehearse, RunID: deadRun, Step: "observe"}},
			rule:     findings.RuleRunInFlight, object: func(lab.Paths) string { return provision.WorkflowRehearse },
			message: []string{"rehearsal run r0 is already in flight", "fylgja twin destroy"}},
		{name: "a twin of this build", recording: "inspect-three.json", hostRead: true,
			twin: func(t *testing.T, paths lab.Paths) { writeTwin(t, paths, rehearsalsTwin(t)) },
			rule: findings.RuleHostTwinPresent, object: func(p lab.Paths) string { return p.Twin },
			message: []string{"is present, the twin of branch fylgja-fixture", "fylgja twin destroy clears it"}},
		{name: "a dead rehearsal's twin.json 11", recording: "inspect-three.json", hostRead: true, twin: version11,
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
			if doc.Rehearsal != nil && doc.Rehearsal.Reclaimed != nil {
				t.Errorf("the report carries a reclaimed block: %+v", doc.Rehearsal.Reclaimed)
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
