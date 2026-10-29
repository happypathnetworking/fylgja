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
// when a read was kept, the bursts among them (016).
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
		Burst:       findings.VerifyCount{Held: 1, Unread: &zero},
		Record:      findings.VerifyCount{Held: 3},
	}
	got := marshal(t, VerifyResult{Wait: wait, Counts: &counts})
	want := `"counts":{"host_name":{"held":3,"failed":0,"unread":0},` +
		`"port_enabled":{"held":10,"failed":1,"skipped":2,"unread":0},` +
		`"neighbor":{"held":6,"failed":0,"skipped":0,"unread":0},"burst":{"held":1,"failed":0,"unread":0},` +
		`"record":{"held":3,"failed":0}}`
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

// twin.json 12 names no rehearsal and no stage (020, research R-06): a record writes
// neither key, and one of 11 or earlier that names them reads with neither. A record input
// writes neither, and one recorded before 020 that carries them decodes.
func TestARecordNamesNoRehearsalAndNoStage(t *testing.T) {
	for _, got := range []string{marshal(t, TwinRecord{}), marshal(t, RecordInput{})} {
		if strings.Contains(got, `"rehearsal"`) || strings.Contains(got, `"stage"`) {
			t.Errorf("writes %s; want no rehearsal and no stage key", got)
		}
	}
	const old = `{"twin_version":"11","bundle_id":"b","stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},` +
		`"label":"seeded","description":"","at_source":"given"},` +
		`"rehearsal":{"workflow_id":"fylgja-rehearse","run_id":"01a1b2c3-0000-7000-8000-00000000000a"},"step":null}`
	var rec TwinRecord
	if err := json.Unmarshal([]byte(old), &rec); err != nil || rec.TwinVersion != "11" || rec.BundleID != "b" {
		t.Errorf("a record of 11 naming a stage and a rehearsal reads %+v (%v)", rec, err)
	}
	var in RecordInput
	if err := json.Unmarshal([]byte(`{"bundle_id":"b","stage":{"label":"seeded"},"rehearsal":{"run_id":"r"}}`), &in); err != nil ||
		in.BundleID != "b" {
		t.Errorf("a record input recorded before 020 reads %+v (%v)", in, err)
	}
}
