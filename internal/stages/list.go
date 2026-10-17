package stages

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// RecordView is what the host's readable record says of its stage, as the listing and the
// step read it: the server fills it from twin.json, so the stages read no wire type.
type RecordView struct {
	ProposedChange RecordChange
	// Label is the stage's: a mark's, or branch-point or head.
	Label string
	// Branch and At are the record's provenance: the reference the twin was built from.
	Branch, At string
	AtSource   string
	// State is the record's: ready or diverged.
	State string
	// Towards is the label of the stage a diverged step was going to; "" otherwise.
	Towards string
}

// RecordChange names the proposed change a record's stage belongs to.
type RecordChange struct {
	ID, Branch string
}

// Ref is the record's stage as a reference names it.
func (v RecordView) Ref() Ref { return Ref{Branch: v.ProposedChange.Branch, Label: v.Label} }

// derived reports whether the record's stage is one of the two derived stages.
func (v RecordView) derived() bool { return v.AtSource == AtBranchPoint || v.AtSource == AtHead }

// names reports whether a listed stage is the one the record names: of its proposed
// change, of its label, and a mark or derived as it was.
func (v RecordView) names(st Stage) bool {
	return st.ProposedChange.ID == v.ProposedChange.ID && st.Label == v.Label && (st.Mark == nil) == v.derived()
}

// Row is one listed stage, resolved by the listing's rules alone: a listing resolves
// nothing for a run, so a nine-digit, a future or a pre-branch-point at, or a stale stage,
// is shown with its source and refused nowhere.
type Row struct {
	Resolved
	// Twin is whether the host's twin was built from this stage.
	Twin bool
}

// Orphan is a stage its proposed change no longer names, removed from its fylgja_stages
// (D-047): listed, warned, never planned or created from.
type Orphan struct {
	ID, Label string
	At        string // the as_of verbatim, else the label's updated_at
	AtSource  string // AtGiven | AtWritten
}

// ListResult is what `stage list` reports: the stages of every open proposed change, or of
// the one whose source branch was asked for, each with the reference it resolves to now;
// the orphaned stages; and the stage the host's record names, when it names one.
type ListResult struct {
	// Branch is the --branch filter, "" when every open proposed change was listed.
	Branch string
	// Rows are sorted by branch, then in each proposed change's order.
	Rows    []Row
	Orphans []Orphan
	// Record is the record's stage with the reference the record holds, or nil.
	Record *RecordView
}

// List lists the stages of the open proposed changes, every one when branch is empty or
// the one whose source branch it is, applying steps 1–6 and 9 to each, and marks the row
// the host's record names. record is the record as the caller read it, or nil when it is
// absent, unreadable or names no stage: the host is twin show's to report, so none of
// those is a finding here.
//
// The kind absent from the default branch is stage.kind.absent, the one refusal of the
// whole listing; an Infrahub that cannot be reached or refuses the credential returns its
// error as it is, for the caller to report as operation.failed, as does a source branch
// deleted under its open proposed change. Beside the rows: stage.label.reserved, a
// rejection, for each mark labelled like a derived stage, and stage.at.unresolved for a
// stage nothing names an at for, whose row is left out (both make the listing's status
// rejected, every other row still listed); and three warnings, which refuse nothing:
// stage.main.moved per proposed change, stage.orphaned per orphan, and stage.twin.moved
// when the record's stage no longer resolves to what the record holds, or is gone.
func List(ctx context.Context, r Reader, s Stamper, branch string, record *RecordView) (ListResult, findings.List, error) {
	if list, err := checkKind(ctx, r); list != nil || err != nil {
		return ListResult{}, list, err
	}
	pcs, err := r.ProposedChanges(ctx, branch)
	if err != nil {
		return ListResult{}, nil, err
	}
	// Sorted here whatever order the reader returned, so the same input gives the same
	// document (FR-016).
	pcs = append([]intent.ProposedChange(nil), pcs...)
	sort.SliceStable(pcs, func(i, j int) bool {
		if pcs[i].Branch != pcs[j].Branch {
			return pcs[i].Branch < pcs[j].Branch
		}
		return pcs[i].ID < pcs[j].ID
	})
	res := ListResult{Branch: branch, Record: record}
	var list findings.List
	var changes []*Change
	mains := map[string]*intent.Stamps{}
	for _, pc := range pcs {
		if branch != "" && pc.Branch != branch {
			continue
		}
		info, err := r.Branch(ctx, pc.Branch)
		if err != nil {
			return ListResult{}, nil, err
		}
		if info == nil {
			return ListResult{}, nil, errors.New(gone(pc.Branch, pc.ID))
		}
		ch, err := newChange(ctx, s, pc, *info)
		if err != nil {
			return ListResult{}, nil, err
		}
		changes = append(changes, ch)
		for _, st := range ch.Stages {
			if st.At == "" {
				// The one rule of step 5 a listing applies, which reads no clock.
				list = append(list, ch.check(st, time.Time{})...)
				continue
			}
			res.Rows = append(res.Rows, Row{Resolved: st.Resolved, Twin: record != nil && record.names(st)})
			if st.Mark != nil && reserved(st.Label) {
				list = append(list, ch.reservedRefusal(st.Ref))
			}
		}
		ch.main = mains[ch.ProposedChange.Destination]
		mainMoved, err := ch.MainMoved(ctx, s)
		if err != nil {
			return ListResult{}, nil, err
		}
		mains[ch.ProposedChange.Destination] = ch.main
		list = append(list, mainMoved...)
	}

	orphans, err := r.Orphans(ctx)
	if err != nil {
		return ListResult{}, nil, err
	}
	for _, o := range orphans {
		row := Orphan{ID: o.ID, Label: o.Label, At: o.LabelWrittenAt, AtSource: AtWritten}
		if o.At != nil {
			row.At, row.AtSource = *o.At, AtGiven
		}
		res.Orphans = append(res.Orphans, row)
		list.Add(findings.Warning, findings.RuleStageOrphaned, o.ID, fmt.Sprintf(
			"stage %q (id %s) names no proposed change: it was removed from its proposed change's fylgja_stages; delete the stage",
			o.Label, o.ID))
	}

	// A listing of another branch says nothing of the record's: its row is not shown.
	if record != nil && (branch == "" || branch == record.ProposedChange.Branch) {
		list = append(list, moved(changes, record)...)
	}
	return res, list, nil
}

// moved is stage.twin.moved when the record's stage is gone, its proposed change no longer
// open, or no longer resolves to the branch and at the record holds; nothing when it still
// does. changes is every proposed change the listing read.
func moved(changes []*Change, rec *RecordView) findings.List {
	ref := rec.Ref()
	built := fmt.Sprintf("the twin was built from stage %s at branch %s, at %s (%s)", ref, rec.Branch, rec.At, rec.AtSource)
	warn := func(what string) findings.List {
		return findings.List{{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: ref.String(),
			Message: fmt.Sprintf("%s; %s; the twin is pinned to what it was built from", built, what)}}
	}
	var ch *Change
	for _, c := range changes {
		if c.ProposedChange.ID == rec.ProposedChange.ID {
			ch = c
		}
	}
	if ch == nil {
		return warn(fmt.Sprintf("proposed change %s is no longer open, so %s is gone", rec.ProposedChange.ID, ref))
	}
	var now []Stage
	for _, st := range ch.Stages {
		if rec.names(st) {
			now = append(now, st)
		}
	}
	for _, st := range now {
		if st.Branch == rec.Branch && st.At == rec.At {
			return nil
		}
	}
	switch {
	case len(now) == 0:
		return warn(fmt.Sprintf("%s no longer exists", ref))
	case now[0].At == "":
		return warn(fmt.Sprintf("%s now names no point in time", ref))
	}
	return warn(fmt.Sprintf("%s now resolves to branch %s, at %s (%s)", ref, now[0].Branch, now[0].At, now[0].AtSource))
}
