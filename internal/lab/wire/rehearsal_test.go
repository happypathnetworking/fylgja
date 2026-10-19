package wire

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// marshal is v as JSON, failing the test when it cannot be written.
func marshal(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// The verify result's counts ride beside the wait (015, research R-07): absent when nil, so
// every recorded history's VerifyTwin result reads and writes as it was, and written by kind
// when a read was kept.
func TestVerifyResultCounts(t *testing.T) {
	wait := StepWait{Outcome: WaitSettled, BudgetS: 120, Reads: 1, From: "2026-10-19T10:00:00Z",
		EndedAt: "2026-10-19T10:00:01Z", Failing: []StepFinding{}}
	if got := marshal(t, VerifyResult{Wait: wait, Recorded: true}); strings.Contains(got, `"counts"`) {
		t.Errorf("a result with no counts writes %s; want no counts key", got)
	}

	zero, two := 0, 2
	counts := VerifyCounts{
		HostName:    findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: 10, Failed: 1, Skipped: &two, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero},
		Record:      findings.VerifyCount{Held: 3},
	}
	got := marshal(t, VerifyResult{Wait: wait, Counts: &counts})
	want := `"counts":{"host_name":{"held":3,"failed":0,"unread":0},` +
		`"port_enabled":{"held":10,"failed":1,"skipped":2,"unread":0},` +
		`"neighbor":{"held":6,"failed":0,"skipped":0,"unread":0},"record":{"held":3,"failed":0}}`
	if !strings.HasSuffix(got, ","+want+"}") {
		t.Errorf("result %s\nwant it to end with %s", got, want)
	}
	var back VerifyResult
	if err := json.Unmarshal([]byte(got), &back); err != nil {
		t.Fatal(err)
	}
	if back.Counts == nil || marshal(t, back) != got {
		t.Errorf("read back %s, want %s", marshal(t, back), got)
	}
}

// A record names the rehearsal run whose baseline it is, or says null (twin.json 7, 015),
// and one of 6 or earlier, which has no key, reads as nil. The record input omits a nil
// rehearsal, so the input of every run a rehearsal did not start is as it was.
func TestRehearsalRef(t *testing.T) {
	if got := marshal(t, TwinRecord{}); !strings.Contains(got, `"rehearsal":null`) {
		t.Errorf("a record of no rehearsal writes %s; want an explicit null", got)
	}
	ref := &RehearsalRef{WorkflowID: RehearseWorkflowID, RunID: "01a1b2c3-0000-7000-8000-00000000000a"}
	if got, want := marshal(t, TwinRecord{Rehearsal: ref}),
		`"rehearsal":{"workflow_id":"fylgja-rehearse","run_id":"01a1b2c3-0000-7000-8000-00000000000a"}`; !strings.Contains(got, want) {
		t.Errorf("a rehearsal's record writes %s; want %s", got, want)
	}

	var old TwinRecord
	if err := json.Unmarshal([]byte(`{"twin_version":"6","stage":null,"step":null}`), &old); err != nil {
		t.Fatal(err)
	}
	if old.Rehearsal != nil {
		t.Errorf("a version 6 record reads rehearsal %+v; want nil", old.Rehearsal)
	}

	if got := marshal(t, RecordInput{}); strings.Contains(got, `"rehearsal"`) {
		t.Errorf("a record input of no rehearsal writes %s; want no rehearsal key", got)
	}
	if got := marshal(t, RecordInput{Rehearsal: ref}); !strings.Contains(got, `"rehearsal":{"workflow_id":"fylgja-rehearse"`) {
		t.Errorf("a rehearsal's record input writes %s; want its rehearsal", got)
	}
}
