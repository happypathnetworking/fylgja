package waypoint

import (
	"context"
	"fmt"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// ListResult is what `waypoint list` reports: every waypoint Infrahub
// holds, or the one series asked for, each with the reference it resolves to now; and the
// waypoint the host's record names, when it names one.
type ListResult struct {
	// Series is the --series filter, empty when every series was listed.
	Series string
	// Rows are sorted by series then sequence.
	Rows []Row
	// Record is the record's waypoint with the reference the record holds, or nil.
	Record *findings.WaypointRecord
}

// Row is one listed waypoint, resolved by step 5 alone: a listing resolves nothing for a
// run, so a nine-digit or future at is shown with its source and refused nowhere.
type Row struct {
	Resolved
	// Twin is whether the host's twin was built from this waypoint.
	Twin bool
}

// List lists the waypoints Infrahub holds, filtered to series when it is not empty, and
// marks the row the host's record names, with the record's state and, when it is diverged,
// the waypoint its step was going to. record is twin.json as the caller read it, or nil
// when it is absent or unreadable: the host is `twin show`'s to report, so neither case
// is a finding here.
//
// The kind absent from the default branch is waypoint.kind.absent, the one refusal; an
// Infrahub that cannot be reached or refuses the credential returns its error as it is,
// for the caller to report as operation.failed. Two warnings, which refuse nothing:
// waypoint.time.reversed for each consecutive pair of one series whose ats run backwards,
// and waypoint.twin.moved when the record's waypoint no longer resolves to the reference
// the twin was built from, or is gone.
func List(ctx context.Context, r Reader, series string, record *wire.TwinRecord) (ListResult, findings.List, error) {
	all, list, err := ListAll(ctx, r)
	if err != nil || list != nil {
		return ListResult{}, list, err
	}
	res := ListResult{Series: series}
	var shown []Resolved
	for _, w := range all {
		if series != "" && w.Series != series {
			continue
		}
		row := resolvedRow(w)
		shown = append(shown, row)
		res.Rows = append(res.Rows, Row{Resolved: row})
	}
	list = reversed(shown)

	if record == nil || record.Waypoint == nil {
		return res, list, nil
	}
	ref := Ref{Series: record.Waypoint.Series, Sequence: record.Waypoint.Sequence}
	res.Record = &findings.WaypointRecord{Series: ref.Series, Sequence: ref.Sequence, Branch: record.Provenance.Branch,
		At: record.Provenance.At, AtSource: record.Waypoint.AtSource, State: record.State}
	// A diverged record still names the waypoint the twin is at, and its step names the one
	// it was going to.
	if st := record.Step; record.State == wire.StateDiverged && st != nil && st.To.Waypoint != nil {
		res.Record.Towards = &findings.WaypointTowards{Series: st.To.Waypoint.Series, Sequence: st.To.Waypoint.Sequence}
	}
	for i := range res.Rows {
		if res.Rows[i].Ref == ref {
			res.Rows[i].Twin = true
		}
	}
	// A listing of another series says nothing of the record's: its row is not shown.
	if series == "" || series == ref.Series {
		list = append(list, moved(all, res.Record)...)
	}
	return res, list, nil
}

// Block is the result as waypoint list's document carries it.
func (r ListResult) Block() *findings.WaypointsBlock {
	b := &findings.WaypointsBlock{Record: r.Record}
	if r.Series != "" {
		series := r.Series
		b.Series = &series
	}
	for _, row := range r.Rows {
		b.Waypoints = append(b.Waypoints, findings.WaypointRow{WaypointBlock: row.Block(), Twin: row.Twin})
	}
	return b
}

// Block is the resolved reference as the document's waypoint block carries it.
func (r Resolved) Block() findings.WaypointBlock {
	return findings.WaypointBlock{Series: r.Ref.Series, Sequence: r.Ref.Sequence, Branch: r.Branch, At: r.At,
		AtSource: r.AtSource, Description: r.Description}
}

// ListAll is step 1 and the listing: the kind checked on the default branch, then every
// waypoint, sorted by series, sequence and id whatever order the reader returned them in.
// The kind absent is waypoint.kind.absent, returned as findings; any other reader failure
// is returned as it is. twin step lists once through it, chooses its target from the
// listing (Target) and builds that.
func ListAll(ctx context.Context, r Reader) ([]intent.Waypoint, findings.List, error) {
	if err := r.Check(ctx); err != nil {
		if list := kindAbsent(err); list != nil {
			return nil, list, nil
		}
		return nil, nil, err
	}
	all, err := r.List(ctx)
	if err != nil {
		return nil, nil, err
	}
	all = append([]intent.Waypoint(nil), all...)
	sort.SliceStable(all, func(i, j int) bool {
		a, b := all[i], all[j]
		if a.Series != b.Series {
			return a.Series < b.Series
		}
		if a.Sequence != b.Sequence {
			return a.Sequence < b.Sequence
		}
		return a.ID < b.ID
	})
	return all, nil, nil
}

// reversed is waypoint.time.reversed for each consecutive pair of one series whose later
// sequence resolves to an earlier at, rows sorted as ListAll sorts them. A pair either of
// whose ats Go cannot read makes no claim, and nothing is refused: the
// order is the operator's.
func reversed(rows []Resolved) findings.List {
	var list findings.List
	for i := 1; i < len(rows); i++ {
		prev, cur := rows[i-1], rows[i]
		if prev.Ref.Series != cur.Ref.Series || prev.Ref.Sequence == cur.Ref.Sequence {
			continue
		}
		was, ok1 := ParseAt(prev.At)
		now, ok2 := ParseAt(cur.At)
		if ok1 && ok2 && now.Before(was) {
			list.Add(findings.Warning, findings.RuleWaypointTimeReversed, cur.Ref.String(), fmt.Sprintf(
				"waypoint %s resolves to at %s, earlier than %s's %s; the order is the operator's and nothing is refused",
				cur.Ref, cur.At, prev.Ref, prev.At))
		}
	}
	return list
}

// moved is waypoint.twin.moved when the record's waypoint is gone, or no longer resolves to
// the branch and at the record holds; nothing when it still does. all is every waypoint,
// whatever the listing's filter.
func moved(all []intent.Waypoint, rec *findings.WaypointRecord) findings.List {
	ref := Ref{Series: rec.Series, Sequence: rec.Sequence}
	var now []Resolved
	for _, w := range all {
		if w.Series == ref.Series && w.Sequence == ref.Sequence {
			now = append(now, resolvedRow(w))
		}
	}
	for _, r := range now {
		if r.Branch == rec.Branch && r.At == rec.At {
			return nil
		}
	}
	built := fmt.Sprintf("the twin was built from waypoint %s at branch %s, at %s (%s)", ref, rec.Branch, rec.At, rec.AtSource)
	var list findings.List
	if len(now) == 0 {
		list.Add(findings.Warning, findings.RuleWaypointTwinMoved, ref.String(),
			fmt.Sprintf("%s; %s no longer exists; the twin is pinned to what it was built from", built, ref))
		return list
	}
	list.Add(findings.Warning, findings.RuleWaypointTwinMoved, ref.String(), fmt.Sprintf(
		"%s; %s now resolves to branch %s, at %s (%s); the twin is pinned to what it was built from",
		built, ref, now[0].Branch, now[0].At, now[0].AtSource))
	return list
}
