package waypoint

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// listed is contracts/cli.md's example series and a second one, in the order a server
// might return them: shuffled.
func listed() []intent.Waypoint {
	return []intent.Waypoint{
		row("id-t2", "fylgja-test-wp-1", 2, "main", "2026-09-28T15:05:00.000000+00:00", nil, ""),
		row("id-3", "demo", 3, "change-1", "2026-09-28T15:40:00.000000+00:00", str("2026-09-28T16:00:00Z"), "after the second"),
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, "before the change"),
		row("id-t1", "fylgja-test-wp-1", 1, "main", "2026-09-28T15:04:00.000000+00:00", nil, ""),
		row("id-2", "demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00", nil, "after the first cut-over"),
	}
}

func refs(rows []Row) []string {
	var out []string
	for _, r := range rows {
		out = append(out, r.Ref.String())
	}
	return out
}

// Every waypoint, sorted by series then sequence whatever the server's order, each with the
// at it resolves to and its source; and the filter.
func TestListSortsAndFilters(t *testing.T) {
	res, list, err := List(context.Background(), &fakeReader{rows: listed()}, "", nil)
	if err != nil || list != nil {
		t.Fatalf("List: %v, %v", list, err)
	}
	if got, want := refs(res.Rows), []string{"demo/1", "demo/2", "demo/3", "fylgja-test-wp-1/1", "fylgja-test-wp-1/2"}; !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v, want %v", got, want)
	}
	if got := res.Rows[2].Resolved; got != (Resolved{Ref: Ref{"demo", 3}, ID: "id-3", Branch: "change-1",
		At: "2026-09-28T16:00:00Z", AtSource: AtGiven, Description: "after the second"}) {
		t.Errorf("demo/3 resolves to %+v", got)
	}
	if got := res.Rows[1].Resolved; got.At != "2026-09-28T15:20:44.000000+00:00" || got.AtSource != AtWritten {
		t.Errorf("demo/2 resolves to %+v; want its branch's write time, written", got)
	}
	if res.Record != nil || res.Block().Series != nil || res.Block().Record != nil {
		t.Errorf("a listing with no record and no filter carries %+v", res.Block())
	}

	res, _, err = List(context.Background(), &fakeReader{rows: listed()}, "demo", nil)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := refs(res.Rows), []string{"demo/1", "demo/2", "demo/3"}; !reflect.DeepEqual(got, want) {
		t.Errorf("--series demo lists %v, want %v", got, want)
	}
	if b := res.Block(); b.Series == nil || *b.Series != "demo" {
		t.Errorf("the block's series is %v, want demo", b.Series)
	}

	res, list, err = List(context.Background(), &fakeReader{rows: listed()}, "absent", nil)
	if err != nil || list != nil || len(res.Rows) != 0 {
		t.Errorf("a series with no waypoints: rows %v, findings %v, error %v; want none", res.Rows, list, err)
	}
}

// A nine-digit and a future at are shown with their source and refused nowhere: a listing
// resolves nothing for a run.
func TestListRefusesNoAt(t *testing.T) {
	rows := []intent.Waypoint{
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", str("2026-09-20T10:00:00.123456789Z"), ""),
		row("id-2", "demo", 2, "main", "2026-09-28T15:00:02.123456+00:00", str("2099-01-01T00:00:00Z"), ""),
	}
	res, list, err := List(context.Background(), &fakeReader{rows: rows}, "", nil)
	if err != nil || list != nil {
		t.Fatalf("List refused: %v, %v", list, err)
	}
	for i, want := range []string{"2026-09-20T10:00:00.123456789Z", "2099-01-01T00:00:00Z"} {
		if r := res.Rows[i]; r.At != want || r.AtSource != AtGiven {
			t.Errorf("row %d: %s (%s), want %s (given)", i, r.At, r.AtSource, want)
		}
	}
}

// The kind absent is the one refusal; any other reader error is returned as it is.
func TestListKindAbsentAndReaderErrors(t *testing.T) {
	_, list, err := List(context.Background(), &fakeReader{checkErr: &intent.WaypointKindError{}}, "", nil)
	if err != nil || len(list) != 1 {
		t.Fatalf("kind absent: %v, %v", list, err)
	}
	f := list[0]
	if f.Rule != findings.RuleWaypointKindAbsent || f.Object != intent.WaypointKind || f.Step != findings.StepResolve ||
		f.Severity != findings.Rejection {
		t.Errorf("kind absent: %+v", f)
	}
	unreachable := errors.New("Infrahub at http://infrahub.invalid is unreachable")
	for _, r := range []*fakeReader{{checkErr: unreachable}, {listErr: unreachable}} {
		if _, list, err := List(context.Background(), r, "", nil); !errors.Is(err, unreachable) || list != nil {
			t.Errorf("reader error: %v, %v; want the error as it is", list, err)
		}
	}
}

// waypoint.time.reversed once per consecutive pair of one series whose ats run backwards,
// naming both waypoints and both ats; never across series, never for a pair Go cannot
// order.
func TestListWarnsOfReversedTime(t *testing.T) {
	rows := []intent.Waypoint{
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, ""),
		row("id-2", "demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00", nil, ""),
		row("id-3", "demo", 3, "change-1", "", str("2026-09-27T09:00:00Z"), ""),
		// Unreadable, so neither pair it is in makes a claim, though 5 is earlier than 3.
		row("id-4", "demo", 4, "change-1", "", str("yesterday"), ""),
		row("id-5", "demo", 5, "change-1", "", str("2026-09-01"), ""),
		// Another series, earlier than demo/5: no pair.
		row("id-x", "echo", 1, "main", "", str("2020-01-01"), ""),
	}
	_, list, err := List(context.Background(), &fakeReader{rows: rows}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	want := findings.List{{Severity: findings.Warning, Rule: findings.RuleWaypointTimeReversed, Object: "demo/3",
		Message: "waypoint demo/3 resolves to at 2026-09-27T09:00:00Z, earlier than demo/2's 2026-09-28T15:20:44.000000+00:00; " +
			"the order is the operator's and nothing is refused"}}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings:\n%+v\nwant\n%+v", list, want)
	}
	if list.Rejected() {
		t.Error("a reversed pair refused the listing")
	}
}

// record is a version 3 twin.json built from demo/2 at the at demo/2 resolved to.
func record(series string, sequence int, branch, at string) *wire.TwinRecord {
	return &wire.TwinRecord{TwinVersion: "3", Provenance: wire.Provenance{Branch: branch, At: at},
		Waypoint: &wire.WaypointRef{Series: series, Sequence: sequence, Description: "after the first cut-over", AtSource: AtWritten}}
}

// The record's row is marked, and waypoint.twin.moved names what changed under it: its at,
// its branch, or the waypoint itself gone. A description edit changes nothing the twin was
// built from, and a record naming no waypoint marks nothing.
func TestListMarksTheRecord(t *testing.T) {
	built := record("demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00")
	const prefix = "the twin was built from waypoint demo/2 at branch change-1, at 2026-09-28T15:20:44.000000+00:00 (written); "
	const suffix = "; the twin is pinned to what it was built from"

	edit := func(fn func(w *intent.Waypoint)) []intent.Waypoint {
		rows := listed()
		for i := range rows {
			if rows[i].ID == "id-2" {
				fn(&rows[i])
			}
		}
		return rows
	}
	gone := func() []intent.Waypoint {
		var rows []intent.Waypoint
		for _, w := range listed() {
			if w.ID != "id-2" {
				rows = append(rows, w)
			}
		}
		return rows
	}

	for _, c := range []struct {
		name    string
		rows    []intent.Waypoint
		record  *wire.TwinRecord
		series  string
		marked  []string
		message string // the one waypoint.twin.moved expected, or none
	}{
		{name: "unchanged", rows: listed(), record: built, marked: []string{"demo/2"}},
		{name: "its description edited", rows: edit(func(w *intent.Waypoint) { w.Description = "renamed" }),
			record: built, marked: []string{"demo/2"}},
		{name: "an as_of written on it", rows: edit(func(w *intent.Waypoint) { w.At = str("2026-09-28T15:31:02.123456+00:00") }),
			record: built, marked: []string{"demo/2"},
			message: prefix + "demo/2 now resolves to branch change-1, at 2026-09-28T15:31:02.123456+00:00 (given)" + suffix},
		{name: "re-pointed at another branch", rows: edit(func(w *intent.Waypoint) {
			w.Branch, w.BranchWrittenAt = "change-2", "2026-09-28T15:31:02.123456+00:00"
		}), record: built, marked: []string{"demo/2"},
			message: prefix + "demo/2 now resolves to branch change-2, at 2026-09-28T15:31:02.123456+00:00 (written)" + suffix},
		{name: "the record's branch another at the same at", rows: listed(),
			record: record("demo", 2, "change-0", "2026-09-28T15:20:44.000000+00:00"), marked: []string{"demo/2"},
			message: "the twin was built from waypoint demo/2 at branch change-0, at 2026-09-28T15:20:44.000000+00:00 (written); " +
				"demo/2 now resolves to branch change-1, at 2026-09-28T15:20:44.000000+00:00 (written)" + suffix},
		{name: "gone", rows: gone(), record: built, marked: nil,
			message: prefix + "demo/2 no longer exists" + suffix},
		{name: "gone, listing its series", rows: gone(), record: built, series: "demo", marked: nil,
			message: prefix + "demo/2 no longer exists" + suffix},
		{name: "gone, listing another series", rows: gone(), record: built, series: "fylgja-test-wp-1", marked: nil},
		{name: "a record naming no waypoint", rows: listed(),
			record: &wire.TwinRecord{TwinVersion: "3", Provenance: wire.Provenance{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00"}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			res, list, err := List(context.Background(), &fakeReader{rows: c.rows}, c.series, c.record)
			if err != nil {
				t.Fatal(err)
			}
			var marked []string
			for _, r := range res.Rows {
				if r.Twin {
					marked = append(marked, r.Ref.String())
				}
			}
			if !reflect.DeepEqual(marked, c.marked) {
				t.Errorf("marked %v, want %v", marked, c.marked)
			}
			var want findings.List
			if c.message != "" {
				want = findings.List{{Severity: findings.Warning, Rule: findings.RuleWaypointTwinMoved, Object: "demo/2", Message: c.message}}
			}
			if !reflect.DeepEqual(list, want) {
				t.Errorf("findings:\n%+v\nwant\n%+v", list, want)
			}
			if c.record.Waypoint == nil {
				if res.Record != nil {
					t.Errorf("a record naming no waypoint gave %+v", res.Record)
				}
				return
			}
			wantRecord := &findings.WaypointRecord{Series: "demo", Sequence: 2, Branch: c.record.Provenance.Branch,
				At: "2026-09-28T15:20:44.000000+00:00", AtSource: AtWritten}
			if !reflect.DeepEqual(res.Record, wantRecord) || !reflect.DeepEqual(res.Block().Record, wantRecord) {
				t.Errorf("record %+v, want %+v", res.Record, wantRecord)
			}
		})
	}
}

// The block carries each row as its resolved reference with twin beside it.
func TestListBlock(t *testing.T) {
	res, _, err := List(context.Background(), &fakeReader{rows: listed()}, "demo",
		record("demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00"))
	if err != nil {
		t.Fatal(err)
	}
	b := res.Block()
	want := findings.WaypointRow{WaypointBlock: findings.WaypointBlock{Series: "demo", Sequence: 2, Branch: "change-1",
		At: "2026-09-28T15:20:44.000000+00:00", AtSource: AtWritten, Description: "after the first cut-over"}, Twin: true}
	if len(b.Waypoints) != 3 || b.Waypoints[1] != want || b.Waypoints[0].Twin || b.Waypoints[2].Twin {
		t.Errorf("block rows %+v; want the second %+v and only it marked", b.Waypoints, want)
	}
}
