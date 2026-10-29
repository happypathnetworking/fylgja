package wire

import (
	"encoding/json"
	"testing"
)

// The ids the names shorten: each name keeps the first eight characters and an ellipsis.
const (
	nameSnapshot = "576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482"
	nameBundle   = "f764e1fa0000000000000000000000000000000000000000000000000000beef"
)

// A step's side is named by its snapshot, else its bundle, the side of a record of
// twin.json 8 that stepped, which names none (019, research R-05); a side names no stage
// from 020 (research R-06), and one an input recorded before it carries decodes to nothing.
func TestStepSideName(t *testing.T) {
	for _, tc := range []struct {
		name string
		side StepSide
		want string
	}{
		{"a snapshot", StepSide{SnapshotID: nameSnapshot, BundleID: nameBundle}, "snapshot 576933ec…"},
		{"no snapshot", StepSide{BundleID: nameBundle}, "bundle f764e1fa…"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.side.Name(); got != tc.want {
				t.Errorf("Name() = %q, want %q", got, tc.want)
			}
		})
	}
	var old StepSide
	if err := json.Unmarshal([]byte(`{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"third-link",`+
		`"description":"","at_source":"given"},"snapshot_id":"`+nameSnapshot+`","bundle_id":"`+nameBundle+`","at":""}`), &old); err != nil {
		t.Fatal(err)
	}
	if got := old.Name(); got != "snapshot 576933ec…" {
		t.Errorf("a side recorded with a stage is named %q, want its snapshot", got)
	}
}

// The record's position is named as a side is, over its top level, whatever stage or
// waypoint a record of 11 or earlier names.
func TestTwinRecordPosition(t *testing.T) {
	snapshot, empty := nameSnapshot, ""
	for _, tc := range []struct {
		name string
		rec  TwinRecord
		want string
	}{
		{"a snapshot", TwinRecord{TwinVersion: "12", SnapshotID: &snapshot, BundleID: nameBundle}, "snapshot 576933ec…"},
		{"a record of 8, which names no snapshot", TwinRecord{TwinVersion: "8", BundleID: nameBundle}, "bundle f764e1fa…"},
		{"a snapshot id that is empty", TwinRecord{TwinVersion: "9", SnapshotID: &empty, BundleID: nameBundle},
			"bundle f764e1fa…"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.rec.Position(); got != tc.want {
				t.Errorf("Position() = %q, want %q", got, tc.want)
			}
		})
	}
}

// An id is shortened to its first eight characters and an ellipsis, and one of eight or
// fewer is named whole.
func TestShortID(t *testing.T) {
	for in, want := range map[string]string{
		nameSnapshot: "576933ec…",
		"576933ec9":  "576933ec…",
		"576933ec":   "576933ec",
		"5769":       "5769",
	} {
		if got := shortID(in); got != want {
			t.Errorf("shortID(%q) = %q, want %q", in, got, want)
		}
	}
}
