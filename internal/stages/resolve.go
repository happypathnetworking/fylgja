package stages

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Reader is what the stages ask of Infrahub's default branch: intent.StageReader's six
// methods, faked in tier 1. Nothing here names a branch's intent: it reads the kind, the
// open proposed changes with their marks, the orphaned marks, a branch's origin, a
// proposed change's artifact validations and a branch's intent events (D-048).
type Reader interface {
	Check(ctx context.Context) error
	ProposedChanges(ctx context.Context, branch string) ([]intent.ProposedChange, error)
	Orphans(ctx context.Context) ([]intent.Stage, error)
	Branch(ctx context.Context, name string) (*intent.BranchInfo, error)
	Validations(ctx context.Context, id, at string) (string, error)
	IntentEvents(ctx context.Context, branch, since, after string) ([]intent.Event, error)
}

// Stamper reads a branch's stamps at an `at`, unpinned when it is empty: the server
// satisfies it with an intent client per (branch, at), whose Stamps reads when the intent
// and the artifacts were written and never a value of intent. Faked in tier 1.
type Stamper interface {
	Stamps(ctx context.Context, branch, at string) (intent.Stamps, error)
}

// Where a stage's at came from (FR-007).
const (
	// AtGiven: as_of is written on the mark, and is used verbatim.
	AtGiven = "given"
	// AtWritten: the mark carries no as_of, and the at is its own write stamp, its
	// label's updated_at, verbatim as Infrahub returns it.
	AtWritten = "written"
	// AtBranchPoint: the source branch's branched_from, verbatim, read on the default
	// branch.
	AtBranchPoint = "branch_point"
	// AtHead: the later of the latest stamp across the source branch's intent and artifact
	// checksums and its latest intent event (D-048), plus one microsecond.
	AtHead = "head"
)

// ProposedChange is the proposed change a stage belongs to, as the blocks name it. Its
// Name is the operator's and never an identity; ID is, and Branch, its source branch, is
// how a reference finds it among the open ones.
type ProposedChange struct {
	ID, Name string
	Branch   string
	// Destination is the branch it merges into, main in Infrahub 1.11.2: the branch the
	// branch point is read on, and whose movement stage.main.moved reports.
	Destination string
	Draft       bool
}

// Resolved is one stage resolved to the pinned intent reference it names.
type Resolved struct {
	Ref Ref
	// Branch is the branch the read is on: the destination for the branch point, the
	// source branch otherwise.
	Branch         string
	Label          string
	ProposedChange ProposedChange
	At             string // verbatim
	AtSource       string // AtGiven | AtWritten | AtBranchPoint | AtHead
	Description    string
	// ID is the mark's object id; "" for a derived stage.
	ID string
}

// Stage is one stage of a proposed change in its place, resolved to its branch and at by
// the listing's rules alone, refusing nothing: what stage list shows. Mark is the
// operator's object, nil for the two derived stages. At is "" when nothing names it: a
// mark Infrahub returned no stamp for, or the head of a branch that holds nothing
// stamped.
type Stage struct {
	Resolved
	Mark *intent.Stage
}

// Change is one open proposed change as a resolution reads it (steps 1–3 and 6): the
// proposed change, its source branch's origin, and its stages in order, the head's at
// computed from the branch's unpinned stamps, which the head's staleness reads too, and
// from its intent events.
type Change struct {
	ProposedChange ProposedChange
	// BranchedFrom is the branch point's at, which a rebase moves; CreatedAt is the
	// branch's creation, which it does not. Both verbatim.
	BranchedFrom, CreatedAt string
	// Stages are the branch point, every mark by at, and the head.
	Stages []Stage

	head intent.Stamps  // the source branch's unpinned stamps
	main *intent.Stamps // the destination's unpinned stamps, read once, for stage.main.moved

	// events are the source branch's intent events read so far, newest first: every one
	// after eventsAfter, or since the branch point when it is "". nil before any read.
	events      []intent.Event
	eventsAfter *string
}

// kindRemedy follows intent.StageKindError's sentence in every stage.kind.absent finding
// (contracts/stage-reference.md).
const kindRemedy = ": load " + intent.StageSchemaFile + " on it; only --stage, stage list and stage plan need it"

// Find is steps 1–3 for one source branch, and step 6: the kind on the default branch,
// the open proposed change whose source the branch is, the branch's origin, and the
// head's at. Each refusal is a rejection at step resolve, returned as findings with a nil
// Change; a reader or a stamper that cannot reach Infrahub, or is refused its credential,
// returns its error as it is, for the caller to report as operation.failed. Nothing of the
// branch's intent is read: the head's at comes from a stamps read.
func Find(ctx context.Context, r Reader, s Stamper, branch string) (*Change, findings.List, error) {
	if list, err := checkKind(ctx, r); list != nil || err != nil {
		return nil, list, err
	}
	pcs, err := r.ProposedChanges(ctx, branch)
	if err != nil {
		return nil, nil, err
	}
	var open []intent.ProposedChange
	for _, pc := range pcs {
		if pc.Branch == branch {
			open = append(open, pc)
		}
	}
	switch {
	case len(open) == 0:
		all, err := r.ProposedChanges(ctx, "")
		if err != nil {
			return nil, nil, err
		}
		return nil, findings.List{noOpenChange(all, branch)}, nil
	case len(open) > 1:
		// Infrahub refuses a second open proposed change on one source branch
		// (research §2.3), so this is a defence: none is chosen.
		ids := make([]string, len(open))
		for i, pc := range open {
			ids[i] = pc.ID
		}
		return nil, nil, fmt.Errorf("branch %s has %d open proposed changes (ids %s), which Infrahub refuses; none is chosen",
			branch, len(open), strings.Join(ids, ", "))
	}
	pc := open[0]
	info, err := r.Branch(ctx, branch)
	if err != nil {
		return nil, nil, err
	}
	if info == nil {
		return nil, findings.List{refusal(findings.RuleStageUnknown, branch, gone(branch, pc.ID))}, nil
	}
	ch, err := newChange(ctx, r, s, pc, *info)
	if err != nil {
		return nil, nil, err
	}
	return ch, nil, nil
}

// gone is how a branch deleted under its open proposed change is named: Infrahub cancels
// the proposed change some seconds after (research §2.3), and until then it names a branch
// that does not exist.
func gone(branch, id string) string {
	return fmt.Sprintf("branch %s does not exist; the open proposed change %s still names it "+
		"(Infrahub cancels it about sixteen seconds after a branch is deleted)", branch, id)
}

// newChange builds a proposed change's stages in order: the branch point at the branch's
// branched_from, each mark at its as_of or its own write stamp, and the head one
// microsecond after the later of the branch's latest stamp, read unpinned, and its latest
// intent event, which is how a removal that moves no stamp moves the head (D-048). Only
// the events after the latest stamp can move it, so only their pages are read.
func newChange(ctx context.Context, r Reader, s Stamper, pc intent.ProposedChange, info intent.BranchInfo) (*Change, error) {
	head, err := s.Stamps(ctx, pc.Branch, "")
	if err != nil {
		return nil, err
	}
	if head.Latest != "" {
		if _, err := HeadAt(head.Latest); err != nil {
			return nil, fmt.Errorf("the head of %s: %w", pc.Branch, err)
		}
	}
	events, err := readEvents(ctx, r, pc.Branch, info.BranchedFrom, head.Latest)
	if err != nil {
		return nil, err
	}
	ch := changeOf(pc, info, head, events)
	ch.events, ch.eventsAfter = events, &head.Latest
	return ch, nil
}

// readEvents is the reader's IntentEvents for a branch, none when Infrahub returned no
// branched_from for it: nothing then bounds the log to the branch's own history, and its
// branch point is refused for having no at.
func readEvents(ctx context.Context, r Reader, branch, since, after string) ([]intent.Event, error) {
	if since == "" {
		return nil, nil
	}
	return r.IntentEvents(ctx, branch, since, after)
}

// changeOf is newChange's proposed change from what was read: the branch's origin, its
// unpinned stamps and the intent events after the latest of them, all empty when the
// branch is gone, which leaves the derived stages with no at. A head stamp HeadAt cannot
// read leaves the head with none too; newChange refuses one first, and the reader one
// of an event.
func changeOf(pc intent.ProposedChange, info intent.BranchInfo, head intent.Stamps, events []intent.Event) *Change {
	ch := &Change{
		ProposedChange: ProposedChange{ID: pc.ID, Name: pc.Name, Branch: pc.Branch, Destination: pc.Destination, Draft: pc.Draft},
		BranchedFrom:   info.BranchedFrom,
		CreatedAt:      info.CreatedAt,
		head:           head,
	}
	derived := func(label, branch, at, source string) Stage {
		return Stage{Resolved: Resolved{Ref: Ref{Branch: pc.Branch, Label: label}, Branch: branch, Label: label,
			ProposedChange: ch.ProposedChange, At: at, AtSource: source}}
	}
	stages := []Stage{derived(LabelBranchPoint, pc.Destination, info.BranchedFrom, AtBranchPoint)}
	for i := range pc.Stages {
		stages = append(stages, ch.mark(&pc.Stages[i]))
	}
	latest := head.Latest
	if ev := latestEvent(events); ev != nil && (latest == "" || later(ev.OccurredAt, latest)) {
		latest = ev.OccurredAt
	}
	headAt, _ := HeadAt(latest)
	ch.Stages = Order(append(stages, derived(LabelHead, pc.Branch, headAt, AtHead)))
	return ch
}

// intentEvents is the source branch's intent events that occurred after after, newest
// first, every one since the branch point when after is "". The events are pinned to
// nothing, so one read serves every stage of the proposed change: a read down to an
// earlier bound serves a later one, and only a bound earlier than the last read's reads
// again.
func (c *Change) intentEvents(ctx context.Context, r Reader, after string) ([]intent.Event, error) {
	if c.eventsAfter == nil || (*c.eventsAfter != "" && (after == "" || later(*c.eventsAfter, after))) {
		events, err := readEvents(ctx, r, c.ProposedChange.Branch, c.BranchedFrom, after)
		if err != nil {
			return nil, err
		}
		c.events, c.eventsAfter = events, &after
		return events, nil
	}
	if after == "" || *c.eventsAfter == after {
		return c.events, nil
	}
	var out []intent.Event
	for _, ev := range c.events {
		if later(ev.OccurredAt, after) {
			out = append(out, ev)
		}
	}
	return out, nil
}

// latestEvent is the latest of events by when each occurred, nil when there is none; two
// at one instant keep the first. The reader has parsed every one.
func latestEvent(events []intent.Event) *intent.Event {
	var latest *intent.Event
	for i := range events {
		if latest == nil || later(events[i].OccurredAt, latest.OccurredAt) {
			latest = &events[i]
		}
	}
	return latest
}

// later reports whether stamp a is later than b, both as Infrahub returned them; a stamp
// Go cannot read is later than nothing and nothing is later than it.
func later(a, b string) bool {
	ta, okA := ParseAt(a)
	tb, okB := ParseAt(b)
	return okA && okB && ta.After(tb)
}

// mark is one mark resolved by step 5 without its rules: the written as_of verbatim, or
// else the label's updated_at verbatim.
func (c *Change) mark(m *intent.Stage) Stage {
	res := Resolved{Ref: Ref{Branch: c.ProposedChange.Branch, Label: m.Label}, Branch: c.ProposedChange.Branch,
		Label: m.Label, ProposedChange: c.ProposedChange, At: m.LabelWrittenAt, AtSource: AtWritten,
		Description: m.Description, ID: m.ID}
	if m.At != nil {
		res.At, res.AtSource = *m.At, AtGiven
	}
	return Stage{Resolved: res, Mark: m}
}

// headLayout is Infrahub's own stamp layout, which the head's at keeps (research R-06):
// 2026-10-08T05:48:38.544483+00:00.
const headLayout = "2006-01-02T15:04:05.000000-07:00"

// HeadAt is the head's at: the later of the branch's latest stamp and its latest intent
// event's occurred_at, which changeOf passes it (D-048), parsed, plus one microsecond, in
// Infrahub's own layout and the stamp's own offset. A read pinned at exactly a stamp sees
// the node and not the value (research §2.6), so the head takes the first instant after.
func HeadAt(latest string) (string, error) {
	t, err := time.Parse(time.RFC3339Nano, latest)
	if err != nil {
		return "", fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", latest)
	}
	return t.Add(time.Microsecond).Format(headLayout), nil
}

// Order puts a proposed change's stages in order (FR-005): the branch point first, the
// marks by their at, the head last, whatever the marks' stamps. Two marks at one instant
// go by label, then id; a mark whose at Go cannot parse goes after those it can, by its
// string, and makes no time claim. A mark labelled like a derived stage is a mark here,
// ordered by its at.
func Order(stages []Stage) []Stage {
	out := append([]Stage(nil), stages...)
	rank := func(s Stage) int {
		switch {
		case s.Mark != nil:
			return 1
		case s.Label == LabelBranchPoint:
			return 0
		}
		return 2
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if ra, rb := rank(a), rank(b); ra != rb || ra != 1 {
			return ra < rb
		}
		ta, okA := ParseAt(a.At)
		tb, okB := ParseAt(b.At)
		switch {
		case okA && okB && !ta.Equal(tb):
			return ta.Before(tb)
		case okA != okB:
			return okA
		case !okA && a.At != b.At:
			return a.At < b.At
		case a.Label != b.Label:
			return a.Label < b.Label
		}
		return a.ID < b.ID
	})
	return out
}

// Labels are the proposed change's stages as references name them, in order, each once.
// A label two marks share is one stage, at its first place; a mark labelled like a derived
// stage shares the derived stage's place. The resolution refuses both.
func (c *Change) Labels() []string {
	seen := map[string]bool{}
	var out []string
	for _, st := range c.Stages {
		if seen[st.Label] || (st.Mark != nil && reserved(st.Label)) {
			continue
		}
		seen[st.Label] = true
		out = append(out, st.Label)
	}
	return out
}

// first is the stage a label names in the order: the derived stage for a reserved label,
// else the first mark of it. ok is false when no stage carries it.
func (c *Change) first(label string) (Stage, bool) {
	for _, st := range c.Stages {
		if st.Label == label && (st.Mark == nil) == reserved(label) {
			return st, true
		}
	}
	return Stage{}, false
}

// Resolve resolves one reference to its pinned (branch, at), applying the reference
// contract's nine steps in order; the first refusal ends it. Each refusal is a rejection
// at step resolve with contracts/stage-reference.md's identifier, object and wording; the
// warning of step 9 refuses nothing and comes back beside a resolution. Every read is the
// default branch's or a stamps read: no branch's intent is read before this returns.
//
// now is the server's clock, read once by the command and passed in for the future rule
// alone, which only a given as_of is held to: it is compared, never sent. reg names each
// device's package for the staleness rule (Constitution II). A reader or stamper that
// cannot reach Infrahub returns its error as it is, for the caller to report as
// operation.failed.
func Resolve(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ref Ref, now time.Time) (Resolved, findings.List, error) {
	ch, list, err := Find(ctx, r, s, ref.Branch)
	if err != nil || list != nil {
		return Resolved{}, list, err
	}
	return ResolveFrom(ctx, r, s, reg, ch, ref, now)
}

// ResolveFrom applies steps 4–9 to a proposed change already found: twin step finds the
// record's proposed change once, chooses its target, and resolves that.
func ResolveFrom(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, ref Ref, now time.Time) (Resolved, findings.List, error) {
	res, list, err := resolve(ctx, r, s, reg, ch, ref, now)
	if err != nil || list.Rejected() {
		return Resolved{}, list, err
	}
	moved, err := ch.MainMoved(ctx, s)
	if err != nil {
		return Resolved{}, nil, err
	}
	return res, append(list, moved...), nil
}

// resolve is steps 4, 5, 7 and 8: the stage named, its at, the branch point, the
// staleness rule. A plan runs it per stage and adds step 9 once.
func resolve(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, ref Ref, now time.Time) (Resolved, findings.List, error) {
	st, list := ch.pick(ref)
	if list != nil {
		return Resolved{}, list, nil
	}
	if list := ch.check(st, now); list != nil {
		return Resolved{}, list, nil
	}
	stale, err := Stale(ctx, r, s, reg, ch, st.Resolved)
	if err != nil || stale.Rejected() {
		return Resolved{}, stale, err
	}
	return st.Resolved, nil, nil
}

// pick is step 4: the stage the reference names among the branch point, the marks and the
// head. A reserved label names the derived stage, and a mark carrying it refuses the
// reference until it is relabelled; a mark's label names exactly one mark.
func (c *Change) pick(ref Ref) (Stage, findings.List) {
	if ref.Branch != c.ProposedChange.Branch {
		return Stage{}, findings.List{refusal(findings.RuleStageUnknown, ref.String(), fmt.Sprintf(
			"stage %s is not of proposed change %s, whose source branch is %s", ref, c.ProposedChange.ID, c.ProposedChange.Branch))}
	}
	var marks []Stage
	for _, st := range c.Stages {
		if st.Mark != nil && st.Label == ref.Label {
			marks = append(marks, st)
		}
	}
	if ref.Derived() {
		if len(marks) > 0 {
			return Stage{}, findings.List{c.reservedRefusal(ref)}
		}
		st, _ := c.first(ref.Label)
		return st, nil
	}
	switch len(marks) {
	case 0:
		return Stage{}, findings.List{refusal(findings.RuleStageUnknown, ref.String(), fmt.Sprintf(
			"%s has no stage %q; its stages are: %s", c.describe(), ref.Label, strings.Join(c.Labels(), ", ")))}
	case 1:
		return marks[0], nil
	}
	ids := make([]string, len(marks))
	for i, st := range marks {
		ids[i] = st.ID
	}
	sort.Strings(ids)
	return Stage{}, findings.List{refusal(findings.RuleStageDuplicate, ref.String(), fmt.Sprintf(
		"stage %s is held by %d objects (ids %s), which the kind's uniqueness constraint should have refused; none is chosen",
		ref, len(marks), strings.Join(ids, ", ")))}
}

// reservedRefusal is stage.label.reserved for a mark labelled like a derived stage.
func (c *Change) reservedRefusal(ref Ref) findings.Finding {
	what := "head"
	if ref.Label == LabelBranchPoint {
		what = "branch point"
	}
	return refusal(findings.RuleStageLabelReserved, ref.String(), fmt.Sprintf(
		"stage %s is a mark labelled %q, which names the derived %s of every proposed change and is reserved; "+
			"relabel it (schema/README.md); the %s of %s is still its derived stage",
		ref, ref.Label, what, what, ref.Branch))
}

// describe names the proposed change as a refusal does.
func (c *Change) describe() string {
	return fmt.Sprintf("proposed change %q (%s) on branch %s", c.ProposedChange.Name, c.ProposedChange.ID, c.ProposedChange.Branch)
}

// check is steps 5 and 7: the stage has an at, honoured by Infrahub, not in the future
// when given, and not before the branch point. The branch point's at is branched_from and
// the head's after every stamp, so neither can be refused but for having none.
func (c *Change) check(st Stage, now time.Time) findings.List {
	ref := st.Ref
	if st.At == "" {
		why := "no as_of is written on it and Infrahub returned no updated_at for its label"
		switch {
		case st.Mark != nil:
		case st.AtSource == AtHead:
			why = "branch " + ref.Branch + " holds no stamped device, interface, link or artifact"
		default:
			why = "Infrahub returned no branched_from for branch " + ref.Branch
		}
		return findings.List{refusal(findings.RuleStageAtUnresolved, ref.String(), fmt.Sprintf(
			"stage %s has no at: %s, so it names no point in time", ref, why))}
	}
	if st.Mark == nil {
		return nil
	}
	if intent.CheckAtPrecision(st.At) != "" {
		return findings.List{refusal(findings.RuleAtPrecision, ref.String(), fmt.Sprintf(
			"stage %s: at %s carries %d fractional digits; Infrahub honours at most %d (microseconds). "+
				"Write the stage's as_of with at most six.",
			ref, st.At, intent.AtFractionDigits(st.At), intent.MaxAtFractionDigits))}
	}
	at, ok := ParseAt(st.At)
	if !ok {
		// A form Go cannot read makes no claim and is passed verbatim, as M1's --at is.
		return nil
	}
	// The future rule, for a given at alone: a written at is Infrahub's own stamp of a
	// write it has already made, and against the server's clock it would test only
	// whether the two clocks agree.
	if st.AtSource == AtGiven && at.After(now) {
		return findings.List{refusal(findings.RuleStageAtUnresolved, ref.String(), fmt.Sprintf(
			"stage %s has at %s (%s), later than the current time %s: it seals nothing yet, "+
				"and a twin from it could differ between two creates",
			ref, st.At, st.AtSource, now.UTC().Format(nowLayout)))}
	}
	branched, ok := ParseAt(c.BranchedFrom)
	if !ok || !at.Before(branched) {
		return nil
	}
	if created, ok := ParseAt(c.CreatedAt); ok && at.After(created) {
		return findings.List{refusal(findings.RuleStageAtBeforeBranchPoint, ref.String(), fmt.Sprintf(
			"stage %s has at %s, before the branch point %s of %s: a rebase at %s moved the branch point past it "+
				"(the branch was created at %s); mark the stage again, or delete it",
			ref, st.At, c.BranchedFrom, ref.Branch, c.BranchedFrom, c.CreatedAt))}
	}
	return findings.List{refusal(findings.RuleStageAtBeforeBranchPoint, ref.String(), fmt.Sprintf(
		"stage %s has at %s, before the branch point %s of %s, and before the branch was created at %s; "+
			"a stage names a moment on its source branch",
		ref, st.At, c.BranchedFrom, ref.Branch, c.CreatedAt))}
}

// nowLayout is how the server's clock is named in a refusal: UTC, six fractional digits.
const nowLayout = "2006-01-02T15:04:05.000000Z"

// checkKind is step 1: the reader's StageKindError filed as stage.kind.absent, any other
// error returned as it is.
func checkKind(ctx context.Context, r Reader) (findings.List, error) {
	err := r.Check(ctx)
	if err == nil {
		return nil, nil
	}
	var kindErr *intent.StageKindError
	if !errors.As(err, &kindErr) {
		return nil, err
	}
	return findings.List{refusal(findings.RuleStageKindAbsent, intent.StageKind, kindErr.Error()+kindRemedy)}, nil
}

// noOpenChange refuses a branch no open proposed change has as its source, naming the
// branches that have one.
func noOpenChange(all []intent.ProposedChange, branch string) findings.Finding {
	exist := "there is no open proposed change"
	if names := branchesOf(all); len(names) > 0 {
		exist = "the branches with one are: " + strings.Join(names, ", ")
	}
	return refusal(findings.RuleStageUnknown, branch, fmt.Sprintf("no open proposed change has source branch %s; %s", branch, exist))
}

// branchesOf is every source branch of the proposed changes, sorted, each once.
func branchesOf(all []intent.ProposedChange) []string {
	seen := map[string]bool{}
	var out []string
	for _, pc := range all {
		if !seen[pc.Branch] {
			seen[pc.Branch] = true
			out = append(out, pc.Branch)
		}
	}
	sort.Strings(out)
	return out
}

func refusal(rule, object, message string) findings.Finding {
	return findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Message: message, Step: findings.StepResolve}
}

// atLayouts are the forms ParseAt reads, in order: RFC 3339 with any fraction and a Z or
// an offset, the same with a space for the T, the naive forms of both, and a date. Every
// form Infrahub was seen to accept and keep is among them.
var atLayouts = []string{
	time.RFC3339Nano,
	"2006-01-02T15:04:05.999999999",
	"2006-01-02 15:04:05.999999999Z07:00",
	"2006-01-02 15:04:05.999999999",
	"2006-01-02",
}

// ParseAt reads an at for the comparisons that need an instant: the order, the future
// rule, the branch point, the staleness rule. A naive form is read as UTC, which is how
// Infrahub renders one back in its own refusals. A form none of the layouts reads returns
// false, and the caller makes no claim about it. Nothing parsed here is ever sent: a query
// carries the at as written, and the head's as HeadAt formats it.
func ParseAt(s string) (time.Time, bool) {
	for _, layout := range atLayouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}
