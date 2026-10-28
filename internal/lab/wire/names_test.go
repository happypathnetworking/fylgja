package wire

import "testing"

// The ids the names shorten: each name keeps the first eight characters and an ellipsis.
const (
	nameSnapshot = "576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482"
	nameBundle   = "f764e1fa0000000000000000000000000000000000000000000000000000beef"
)

// A step's side is named by what it names first: its stage, else its snapshot, else its
// bundle, the side of a record of twin.json 8 that stepped, which names neither (019,
// research R-05).
func TestStepSideName(t *testing.T) {
	stage := &StageRef{ProposedChange: StageChange{ID: "pc-1", Branch: "change-1"}, Label: "third-link"}
	for _, tc := range []struct {
		name string
		side StepSide
		want string
	}{
		{"a stage, beside its snapshot and bundle", StepSide{Stage: stage, SnapshotID: nameSnapshot, BundleID: nameBundle},
			"stage change-1/third-link"},
		{"a snapshot and no stage", StepSide{SnapshotID: nameSnapshot, BundleID: nameBundle}, "snapshot 576933ec…"},
		{"neither a stage nor a snapshot", StepSide{BundleID: nameBundle}, "bundle f764e1fa…"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.side.Name(); got != tc.want {
				t.Errorf("Name() = %q, want %q", got, tc.want)
			}
		})
	}
}

// The record's position is named as a side is, over its top level, and a record of
// twin.json 5 or earlier that names M10's waypoint keeps SideStage's wording.
func TestTwinRecordPosition(t *testing.T) {
	stage := &StageRef{ProposedChange: StageChange{ID: "pc-1", Branch: "change-1"}, Label: "seeded"}
	snapshot, empty := nameSnapshot, ""
	for _, tc := range []struct {
		name string
		rec  TwinRecord
		want string
	}{
		{"a stage, beside its snapshot and bundle",
			TwinRecord{TwinVersion: "9", Stage: stage, SnapshotID: &snapshot, BundleID: nameBundle}, "stage change-1/seeded"},
		{"a snapshot and no stage", TwinRecord{TwinVersion: "9", SnapshotID: &snapshot, BundleID: nameBundle},
			"snapshot 576933ec…"},
		{"a record of 8, which names no snapshot", TwinRecord{TwinVersion: "8", BundleID: nameBundle}, "bundle f764e1fa…"},
		{"a snapshot id that is empty", TwinRecord{TwinVersion: "9", SnapshotID: &empty, BundleID: nameBundle},
			"bundle f764e1fa…"},
		{"a record of 5 naming a waypoint", TwinRecord{TwinVersion: "5", BundleID: nameBundle, Superseded: true},
			"a waypoint of a record version this build no longer reads (twin.json 5)"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.rec.Position(); got != tc.want {
				t.Errorf("Position() = %q, want %q", got, tc.want)
			}
		})
	}

	// The waypoint's wording is SideStage's own for the record's stage.
	old := TwinRecord{TwinVersion: "5", BundleID: nameBundle, Superseded: true}
	if got, want := old.Position(), old.SideStage(old.Stage); got != want {
		t.Errorf("Position() = %q, SideStage = %q; want them equal", got, want)
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
