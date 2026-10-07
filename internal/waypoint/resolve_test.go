package waypoint

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// fakeReader is Infrahub as the resolution sees it. It records every call: the Reader
// interface has no way to name a branch or read intent, and the record proves the
// resolution asked for nothing else.
type fakeReader struct {
	checkErr error
	listErr  error
	rows     []intent.Waypoint
	calls    []string
}

func (f *fakeReader) Check(context.Context) error {
	f.calls = append(f.calls, "Check")
	return f.checkErr
}

func (f *fakeReader) List(context.Context) ([]intent.Waypoint, error) {
	f.calls = append(f.calls, "List")
	return f.rows, f.listErr
}

func row(id, series string, sequence int, branch, writtenAt string, at *string, description string) intent.Waypoint {
	return intent.Waypoint{ID: id, Series: series, Sequence: sequence, Branch: branch,
		BranchWrittenAt: writtenAt, At: at, Description: description}
}

func str(s string) *string { return &s }

// now is the CLI's clock in every case, as contracts/cli.md's example reads it.
var now = time.Date(2026, 9, 28, 16, 10, 0, 0, time.UTC)

// Every refusal of, with its rule, step, object and contracts/cli.md's
// message, and the first one found ending the resolution.
func TestResolveRefusals(t *testing.T) {
	demo := []intent.Waypoint{
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, "before the change"),
		row("id-2", "demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00", nil, "after the first cut-over"),
		row("id-5", "demo", 5, "change-1", "2026-09-28T15:30:00.000000+00:00", nil, ""),
		row("id-a", "alpha", 1, "main", "2026-09-28T15:00:00.000000+00:00", nil, ""),
		row("id-t", "fylgja-test-wp-3", 1, "main", "2026-09-28T15:00:00.000000+00:00", nil, ""),
	}
	for _, tc := range []struct {
		name     string
		reader   *fakeReader
		ref      Ref
		rule     string
		object   string
		message  string
		wantList bool // whether List was reached
	}{
		{
			name:   "kind absent",
			reader: &fakeReader{checkErr: &intent.WaypointKindError{}},
			ref:    Ref{"demo", 1}, rule: findings.RuleWaypointKindAbsent, object: "FylgjaWaypoint",
			message: "the default branch's schema has no kind FylgjaWaypoint: load schema/fylgja-waypoint.yaml on it; " +
				"only --waypoint, waypoint list and waypoint plan need it",
		},
		{
			name:   "an attribute missing",
			reader: &fakeReader{checkErr: &intent.WaypointKindError{Missing: []string{"as_of"}}},
			ref:    Ref{"demo", 1}, rule: findings.RuleWaypointKindAbsent, object: "FylgjaWaypoint",
			message: "kind FylgjaWaypoint on the default branch lacks the attribute as_of, which this build reads: " +
				"load schema/fylgja-waypoint.yaml on it; only --waypoint, waypoint list and waypoint plan need it",
		},
		{
			name:   "unknown series, naming the series that exist",
			reader: &fakeReader{rows: demo[3:]},
			ref:    Ref{"demo", 1}, rule: findings.RuleWaypointUnknown, object: "demo", wantList: true,
			message: `no waypoint series "demo" exists; the series are: alpha, fylgja-test-wp-3`,
		},
		{
			name:   "unknown series, none at all",
			reader: &fakeReader{},
			ref:    Ref{"demo", 1}, rule: findings.RuleWaypointUnknown, object: "demo", wantList: true,
			message: `no waypoint series "demo" exists; there are no waypoints`,
		},
		{
			name: "unknown sequence, naming the series' sequences",
			// Out of order, and with a sequence twice: each is named once, ascending.
			reader: &fakeReader{rows: []intent.Waypoint{demo[2], demo[0], demo[1], demo[2], demo[3]}},
			ref:    Ref{"demo", 7}, rule: findings.RuleWaypointUnknown, object: "demo/7", wantList: true,
			message: "series demo has no waypoint 7; its sequences are 1, 2, 5",
		},
		{
			name: "duplicate, naming every id",
			reader: &fakeReader{rows: append(slices.Clone(demo),
				row("id-0", "demo", 2, "change-2", "2026-09-28T15:40:00.000000+00:00", nil, ""))},
			ref: Ref{"demo", 2}, rule: findings.RuleWaypointDuplicate, object: "demo/2", wantList: true,
			message: "waypoint demo/2 is held by 2 objects (ids id-0, id-2), which the kind's uniqueness " +
				"constraint should have refused; none is chosen",
		},
		{
			// No as_of written, and a null branch.updated_at, which genqlient decodes to "":
			// resolved, it would be the branch head, unpinned.
			name:   "no at at all",
			reader: &fakeReader{rows: []intent.Waypoint{row("id-4", "demo", 4, "change-1", "", nil, "")}},
			ref:    Ref{"demo", 4}, rule: findings.RuleWaypointAtUnresolved, object: "demo/4", wantList: true,
			message: "waypoint demo/4 has no at: no as_of is written on it and Infrahub returned no updated_at " +
				"for its branch attribute, so it names no point in time",
		},
		{
			name: "nine fractional digits",
			reader: &fakeReader{rows: []intent.Waypoint{row("id-3", "demo", 3, "change-1",
				"2026-09-28T15:50:00.000000+00:00", str("2026-09-20T10:00:00.123456789Z"), "")}},
			ref: Ref{"demo", 3}, rule: findings.RuleAtPrecision, object: "demo/3", wantList: true,
			message: "waypoint demo/3: at 2026-09-20T10:00:00.123456789Z carries 9 fractional digits; Infrahub " +
				"honours at most 6 (microseconds). Write the waypoint's as_of with at most six.",
		},
		{
			name: "a given at in the future",
			reader: &fakeReader{rows: []intent.Waypoint{row("id-3", "demo", 3, "change-1",
				"2026-09-28T15:50:00.000000+00:00", str("2099-01-01T00:00:00Z"), "")}},
			ref: Ref{"demo", 3}, rule: findings.RuleWaypointAtUnresolved, object: "demo/3", wantList: true,
			message: "waypoint demo/3 has at 2099-01-01T00:00:00Z (given), later than the current time " +
				"2026-09-28T16:10:00.000000Z: it seals nothing yet, and a twin from it could differ between two creates",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			res, list, err := Resolve(t.Context(), tc.reader, tc.ref, now)
			if err != nil {
				t.Fatalf("a refusal returned as an error: %v", err)
			}
			if res != (Resolved{}) {
				t.Errorf("a refusal resolved to %+v", res)
			}
			if len(list) != 1 {
				t.Fatalf("want exactly one finding, got %+v", list)
			}
			f := list[0]
			if f.Severity != findings.Rejection || f.Rule != tc.rule || f.Step != findings.StepResolve || f.Object != tc.object {
				t.Errorf("finding = %s %s [step %s] %s; want rejection %s [step resolve] %s",
					f.Severity, f.Rule, f.Step, f.Object, tc.rule, tc.object)
			}
			if f.Message != tc.message {
				t.Errorf("message\n  %s\nwant\n  %s", f.Message, tc.message)
			}
			want := []string{"Check"}
			if tc.wantList {
				want = append(want, "List")
			}
			if !slices.Equal(tc.reader.calls, want) {
				t.Errorf("the reader was asked %v, want %v", tc.reader.calls, want)
			}
		})
	}
}

// A resolution that succeeds: a written as_of verbatim and given; an unwritten one the
// branch attribute's updated_at verbatim and written; a form Go cannot
// read passed verbatim with no future claim. Nothing but Check and List
// is asked, so no branch is read and no intent.
func TestResolveResolves(t *testing.T) {
	rows := []intent.Waypoint{
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, "before the change"),
		row("id-2", "demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00", str("2026-09-20T10:00:00.5+02:00"), "after"),
		row("id-3", "demo", 3, "change-1", "2026-09-28T15:30:00.000000+00:00", str("the day the lab went live"), ""),
	}
	for _, tc := range []struct {
		ref  Ref
		want Resolved
	}{
		{Ref{"demo", 1}, Resolved{Ref: Ref{"demo", 1}, ID: "id-1", Branch: "main",
			At: "2026-09-28T15:00:01.123456+00:00", AtSource: AtWritten, Description: "before the change"}},
		{Ref{"demo", 2}, Resolved{Ref: Ref{"demo", 2}, ID: "id-2", Branch: "change-1",
			At: "2026-09-20T10:00:00.5+02:00", AtSource: AtGiven, Description: "after"}},
		{Ref{"demo", 3}, Resolved{Ref: Ref{"demo", 3}, ID: "id-3", Branch: "change-1",
			At: "the day the lab went live", AtSource: AtGiven}},
	} {
		t.Run(tc.ref.String(), func(t *testing.T) {
			r := &fakeReader{rows: rows}
			// A clock long before every at: only a given at Go can read can be refused as
			// future. A written at, and a form Go cannot read, resolve at any clock.
			got, list, err := Resolve(t.Context(), r, tc.ref, time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC))
			if _, parsed := ParseAt(tc.want.At); parsed && tc.want.AtSource == AtGiven {
				// The same clock refuses a parsed given at: the others' pass above is
				// their source's and the parse's, not the clock's.
				if len(list) != 1 || list[0].Rule != findings.RuleWaypointAtUnresolved {
					t.Fatalf("a parsed given at after the clock: %v %+v", err, list)
				}
				got, list, err = Resolve(t.Context(), r, tc.ref, now)
			}
			if err != nil || len(list) != 0 {
				t.Fatalf("%v %+v", err, list)
			}
			if got != tc.want {
				t.Errorf("resolved\n  %+v\nwant\n  %+v", got, tc.want)
			}
			for _, c := range r.calls {
				if c != "Check" && c != "List" {
					t.Errorf("the reader was asked %s", c)
				}
			}
		})
	}
}

// A written at after the CLI's clock resolves, verbatim and written, with no finding: it
// is Infrahub's own stamp of a write it has already made, and against this clock it would
// test only whether the two clocks agree, which a remote Infrahub need not. The
// same instant written as the waypoint's as_of is still refused.
func TestResolveWrittenAtAfterTheClock(t *testing.T) {
	ahead := row("id-3", "demo", 3, "change-1", "2026-09-28T16:10:00.000001+00:00", nil, "just written")
	got, list, err := Resolve(t.Context(), &fakeReader{rows: []intent.Waypoint{ahead}}, Ref{"demo", 3}, now)
	if err != nil || len(list) != 0 {
		t.Fatalf("a written at after the clock was refused: %v %+v", err, list)
	}
	want := Resolved{Ref: Ref{"demo", 3}, ID: "id-3", Branch: "change-1",
		At: "2026-09-28T16:10:00.000001+00:00", AtSource: AtWritten, Description: "just written"}
	if got != want {
		t.Errorf("resolved\n  %+v\nwant\n  %+v", got, want)
	}

	given := ahead
	given.At = str(ahead.BranchWrittenAt)
	_, list, err = Resolve(t.Context(), &fakeReader{rows: []intent.Waypoint{given}}, Ref{"demo", 3}, now)
	if err != nil || len(list) != 1 || list[0].Rule != findings.RuleWaypointAtUnresolved {
		t.Errorf("the same instant given: %v %+v; want waypoint.at.unresolved", err, list)
	}
}

// A reader that cannot reach Infrahub, or is refused its credential, returns that error
// as it is: never one of the six refusals, never a finding.
func TestResolveReturnsTheReadersError(t *testing.T) {
	down := errors.New("reading the schema (the default branch): connection refused")
	for name, r := range map[string]*fakeReader{
		"Check": {checkErr: down},
		"List":  {listErr: down},
	} {
		_, list, err := Resolve(t.Context(), r, Ref{"demo", 1}, now)
		if !errors.Is(err, down) || list != nil {
			t.Errorf("%s failing: err %v, findings %+v; want the reader's error and no finding", name, err, list)
		}
	}
}

// ParseAt reads every form Infrahub was seen to accept and keep, a
// naive one as UTC, and makes no claim about a form none of its layouts reads.
func TestParseAt(t *testing.T) {
	utc := func(y int, mo time.Month, d, h, mi, s, ns int) time.Time {
		return time.Date(y, mo, d, h, mi, s, ns, time.UTC)
	}
	for s, want := range map[string]time.Time{
		"2026-09-28T16:04:52.482130+00:00": utc(2026, 9, 28, 16, 4, 52, 482130000),
		"2026-09-20T10:00:00Z":             utc(2026, 9, 20, 10, 0, 0, 0),
		"2026-09-20T10:00:00.123456789Z":   utc(2026, 9, 20, 10, 0, 0, 123456789),
		"2026-09-20T10:00:00.5+02:00":      utc(2026, 9, 20, 8, 0, 0, 500000000),
		"2026-09-20T10:00:00":              utc(2026, 9, 20, 10, 0, 0, 0),
		"2026-09-20 10:00:00+02:00":        utc(2026, 9, 20, 8, 0, 0, 0),
		"2026-09-20 10:00:00":              utc(2026, 9, 20, 10, 0, 0, 0),
		"2026-09-20":                       utc(2026, 9, 20, 0, 0, 0, 0),
	} {
		got, ok := ParseAt(s)
		if !ok || !got.Equal(want) {
			t.Errorf("ParseAt(%q) = %v, %v; want %v", s, got, ok, want)
		}
	}
	for _, s := range []string{"yesterday", "", "2026-13-01"} {
		if _, ok := ParseAt(s); ok {
			t.Errorf("ParseAt(%q) claimed an instant", s)
		}
	}
}
