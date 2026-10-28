package stages

import (
	"context"
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
	// Scope is the record's provenance's scope, tag:<name>, or "" for a record that names
	// none this build reads under (a 7, or an 8 edited by hand), which is judged under the
	// listing's scope (017).
	Scope string
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

// headInOtherScope reports whether the record's stage is the head of proposed change id
// and the record names a scope other than scope: the head is the one stage whose at a
// scope moves, since its stamps are the scope's devices', so the listing resolves it again
// under the record's scope for stage.twin.moved, as twin step resolves it (017).
func (v *RecordView) headInOtherScope(id, scope string) bool {
	return v != nil && v.ProposedChange.ID == id && v.AtSource == AtHead && v.Scope != "" && v.Scope != scope
}

// names reports whether a listed stage is the one the record names: of its proposed
// change, of its label, and a mark or derived as it was.
func (v RecordView) names(st Stage) bool {
	return st.ProposedChange.ID == v.ProposedChange.ID && st.Label == v.Label && (st.Mark == nil) == v.derived()
}

// Row is one listed stage, resolved by the listing's rules alone: a listing resolves
// nothing for a run, so a nine-digit, a future or a pre-branch-point at, or a stale stage,
// is shown with its source and refused nowhere. Every stage has its row: one nothing names
// an at for has its At empty.
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
// error as it is, for the caller to report as operation.failed. Every stage of every
// proposed change listed has its row. Beside the rows: stage.label.reserved, a rejection,
// for each mark labelled like a derived stage (the listing's status rejected, every row
// still listed); the schema.* findings of a branch whose schema does not conform, the
// source's or the destination's, rejections filed once per branch before its stamps are
// read, the source's head listed with no at (017); and warnings, which refuse nothing:
// stage.at.unresolved for a stage nothing names an at for, or scope.empty for a head whose
// scope selects no device (017), whose row has none; stage.unknown for a source branch deleted
// under its open proposed change, whose marks are listed at their own ats and whose two
// derived stages have none, until Infrahub cancels it; stage.main.moved per proposed
// change; stage.orphaned per orphan; and stage.twin.moved when the record's stage no
// longer resolves to what the record holds, or is gone.
//
// Every stamps read is under scope, tag:<name> (017), but one: a record's head is judged
// under the scope the record names, as twin step judges it, so a twin built under another
// scope reads its proposed change's stamps once more under that scope, for
// stage.twin.moved alone. A record naming no scope is judged under the listing's.
func List(ctx context.Context, r Reader, s Stamper, branch, scope string, record *RecordView) (ListResult, findings.List, error) {
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
	// recorded is the record's proposed change resolved under the record's scope, when its
	// stage is a head the listing's scope would resolve elsewhere; nil otherwise.
	var recorded *Change
	mains := map[string]*intent.Stamps{}
	for _, pc := range pcs {
		if branch != "" && pc.Branch != branch {
			continue
		}
		info, err := r.Branch(ctx, pc.Branch)
		if err != nil {
			return ListResult{}, nil, err
		}
		var ch *Change
		// refused is whether the source branch's schema refused its stamps: its head has
		// no at, and the refusal says why.
		refused := false
		if info == nil {
			// Its stages still list until Infrahub cancels it, the branch's warning saying
			// why its two derived stages have no at.
			ch = changeOf(pc, intent.BranchInfo{Name: pc.Branch}, intent.Stamps{}, nil)
			ch.Scope = scope
			list = append(list, warning(refusal(findings.RuleStageUnknown, pc.Branch, gone(pc.Branch, pc.ID)+
				"; until then its branch point and head have no at")))
		} else if ch, err = newChange(ctx, r, s, pc, *info, scope); err != nil {
			schema, ok := conformanceRefusal(err)
			if !ok {
				return ListResult{}, nil, err
			}
			ch = changeOf(pc, *info, intent.Stamps{}, nil)
			ch.Scope = scope
			list = append(list, schema...)
			refused = true
		} else if record.headInOtherScope(pc.ID, scope) {
			// For stage.twin.moved alone: the row, the mark and every other stage stay the
			// listing scope's.
			if recorded, err = newChange(ctx, r, s, pc, *info, record.Scope); err != nil {
				return ListResult{}, nil, err
			}
		}
		changes = append(changes, ch)
		for _, st := range ch.Stages {
			res.Rows = append(res.Rows, Row{Resolved: st.Resolved, Twin: record != nil && record.names(st)})
			if st.Mark != nil && reserved(st.Label) {
				list = append(list, ch.reservedRefusal(st.Ref))
			}
			if st.At == "" && info != nil && !refused {
				// The one rule of step 5 a listing applies, which reads no clock, and
				// refuses nothing.
				for _, f := range ch.check(st, time.Time{}) {
					list = append(list, warning(f))
				}
			}
		}
		if info == nil {
			continue
		}
		ch.main = mains[ch.ProposedChange.Destination]
		mainMoved, err := ch.MainMoved(ctx, s)
		if err != nil {
			return ListResult{}, nil, err
		}
		mains[ch.ProposedChange.Destination] = ch.main
		list = append(list, unfiled(mainMoved, list)...)
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
		var ch *Change
		for _, c := range changes {
			if c.ProposedChange.ID == record.ProposedChange.ID {
				ch = c
			}
		}
		if recorded != nil {
			ch = recorded
		}
		list = append(list, Moved(ch, *record)...)
	}
	return res, list, nil
}

// warning is a resolution's refusal as a listing files it: the same rule, object and
// wording, refusing nothing.
func warning(f findings.Finding) findings.Finding {
	f.Severity = findings.Warning
	return f
}

// Moved is stage.twin.moved when the record's stage is gone, its proposed change no longer
// open, or no longer resolves to the branch and at the record holds; nothing when it still
// does. ch is the proposed change the listing read as the record's, nil when no open
// proposed change of the record's was read on its source branch, or the one twin step
// found its target in. stage list files it beside the record's row and twin step beside
// its target's findings, in the same words: a warning that refuses nothing, since a twin
// steps from the bundle its record holds. It applies only when ch is the record's own
// proposed change (019, research R-07): a target found in another, of another branch or
// opened on the record's since, is a step out of the record's proposed change, whose
// stage the step does not read, and nothing is said of it. A record naming no stage has
// no view, and nothing to have moved.
func Moved(ch *Change, rec RecordView) findings.List {
	ref := rec.Ref()
	built := fmt.Sprintf("the twin was built from stage %s at branch %s, at %s (%s)", ref, rec.Branch, rec.At, rec.AtSource)
	warn := func(what string) findings.List {
		return findings.List{{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: ref.String(),
			Message: fmt.Sprintf("%s; %s; the twin is pinned to what it was built from", built, what)}}
	}
	if ch == nil {
		return warn(fmt.Sprintf("proposed change %s is no longer open, so %s is gone", rec.ProposedChange.ID, ref))
	}
	if ch.ProposedChange.ID != rec.ProposedChange.ID {
		return nil
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
