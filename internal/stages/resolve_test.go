package stages

import (
	"context"
	"errors"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeReader is Infrahub's default branch as the stages see it. It records every call:
// the Reader interface has no way to read a branch's intent, and the record proves which
// of its six reads a rule made.
type fakeReader struct {
	checkErr, pcErr, orphanErr, branchErr, validationsErr, eventsErr error

	pcs         []intent.ProposedChange
	orphans     []intent.Stage
	branches    map[string]*intent.BranchInfo
	validations map[string]string         // id@at → the latest completed_at value in force
	events      map[string][]intent.Event // branch → its intent events since its branch point, newest first
	calls       []string
}

func (f *fakeReader) Check(context.Context) error {
	f.calls = append(f.calls, "Check")
	return f.checkErr
}

// ProposedChanges filters by source branch as the query does, every one when it is empty.
func (f *fakeReader) ProposedChanges(_ context.Context, branch string) ([]intent.ProposedChange, error) {
	f.calls = append(f.calls, "ProposedChanges "+branch)
	var out []intent.ProposedChange
	for _, pc := range f.pcs {
		if branch == "" || pc.Branch == branch {
			out = append(out, pc)
		}
	}
	return out, f.pcErr
}

func (f *fakeReader) Orphans(context.Context) ([]intent.Stage, error) {
	f.calls = append(f.calls, "Orphans")
	return f.orphans, f.orphanErr
}

func (f *fakeReader) Branch(_ context.Context, name string) (*intent.BranchInfo, error) {
	f.calls = append(f.calls, "Branch "+name)
	return f.branches[name], f.branchErr
}

func (f *fakeReader) Validations(_ context.Context, id, at string) (string, error) {
	f.calls = append(f.calls, "Validations "+id+"@"+at)
	return f.validations[id+"@"+at], f.validationsErr
}

// IntentEvents answers the branch's events after after, as the reader pages them, every
// one when it is empty; since is recorded, not applied: a case's events are all after
// the branch point.
func (f *fakeReader) IntentEvents(_ context.Context, branch, since, after string) ([]intent.Event, error) {
	f.calls = append(f.calls, "IntentEvents "+branch+" since "+since+" after "+after)
	var out []intent.Event
	for _, ev := range f.events[branch] {
		if after == "" || later(ev.OccurredAt, after) {
			out = append(out, ev)
		}
	}
	return out, f.eventsErr
}

// fakeStamper is the branches' stamps: exactly at a (branch, at) when a case gives one,
// else the branch's at any at. It records every (branch, at) it is asked for.
type fakeStamper struct {
	err      error
	at       map[string]intent.Stamps // branch@at
	byBranch map[string]intent.Stamps
	calls    []string
}

func (f *fakeStamper) Stamps(_ context.Context, branch, at string) (intent.Stamps, error) {
	f.calls = append(f.calls, branch+"@"+at)
	if f.err != nil {
		return intent.Stamps{}, f.err
	}
	if s, ok := f.at[branch+"@"+at]; ok {
		return s, nil
	}
	return f.byBranch[branch], nil
}

func str(s string) *string { return &s }

// The story of contracts/stage-commands.md: proposed change "third link" on change-1, a
// draft, with the mark cabled written and the mark live given, and a second proposed
// change on change-2 with nothing marked.
const (
	createdAt    = "2026-10-16T17:20:19.944511Z"
	branchedFrom = "2026-10-16T17:20:19.944651Z"
	cabledAt     = "2026-10-16T17:25:30.118244+00:00"
	liveAt       = "2026-10-16T17:30:00.000000+00:00"
	headLatest   = "2026-10-16T17:30:11.884301+00:00"
	headAt       = "2026-10-16T17:30:11.884302+00:00"
)

// now is the server's clock in every case.
var now = time.Date(2026, 10, 16, 18, 0, 0, 0, time.UTC)

func mark(id, label, written string, asOf *string, description string) intent.Stage {
	return intent.Stage{ID: id, Label: label, LabelWrittenAt: written, At: asOf, Description: description}
}

func change1(marks ...intent.Stage) intent.ProposedChange {
	if marks == nil {
		marks = []intent.Stage{
			mark("st-live", "live", "2026-10-16T17:31:00.000000+00:00", str(liveAt), "after its configuration is live"),
			mark("st-cabled", "cabled", cabledAt, nil, "after the link is cabled"),
		}
	}
	return intent.ProposedChange{ID: "pc-1", Name: "third link", Branch: "change-1", Destination: "main", State: "open",
		Draft: true, Stages: marks}
}

func change2() intent.ProposedChange {
	return intent.ProposedChange{ID: "pc-2", Name: "fourth link", Branch: "change-2", Destination: "main", State: "open"}
}

// device is one SR Linux device's stamps: its intent and its artifact's checksum stamp.
func device(intentAt, checksum string) intent.DeviceStamps {
	return intent.DeviceStamps{Platform: ctm.Platform{Vendor: "nokia", NOS: "srlinux"}, Intent: intentAt,
		Artifacts: map[string]string{"device-config": checksum}}
}

// freshStamps is a branch whose every artifact was generated after its device's intent,
// the latest stamp latest.
func freshStamps(latest string) intent.Stamps {
	return intent.Stamps{Latest: latest, Devices: map[string]intent.DeviceStamps{
		"n1": device("2026-10-16T17:21:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00"),
		"n2": device("2026-10-16T17:21:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00"),
		"n3": device("2026-10-16T17:21:00.000000+00:00", latest),
	}}
}

// story is the reader and stamper of the two proposed changes: both branches fresh at any
// at, and main holding nothing.
func story(pcs ...intent.ProposedChange) (*fakeReader, *fakeStamper) {
	if pcs == nil {
		pcs = []intent.ProposedChange{change1(), change2()}
	}
	r := &fakeReader{pcs: pcs, branches: map[string]*intent.BranchInfo{
		"change-1": {Name: "change-1", BranchedFrom: branchedFrom, CreatedAt: createdAt},
		"change-2": {Name: "change-2", BranchedFrom: "2026-10-16T17:40:00.000000Z", CreatedAt: "2026-10-16T17:39:59.999900Z"},
	}}
	s := &fakeStamper{byBranch: map[string]intent.Stamps{
		"change-1": freshStamps(headLatest),
		"change-2": freshStamps("2026-10-16T17:41:00.000000+00:00"),
		"main":     {},
	}}
	return r, s
}

func registry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

// pc1 is change-1's proposed change as the blocks name it.
var pc1 = ProposedChange{ID: "pc-1", Name: "third link", Branch: "change-1", Destination: "main", Draft: true}

// Every refusal of the reference contract's table, with its identifier, severity, exit,
// step, object and wording, the first one found ending the resolution. A refusal of
// steps 1–3 reads no stamp; no refusal reads a branch's intent, which neither fake can
// serve, and the stamper is asked for stamps alone.
func TestResolveRefusals(t *testing.T) {
	stale := freshStamps(headLatest)
	stale.Devices["n1"] = device("2026-10-16T17:24:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
	for _, tc := range []struct {
		name    string
		edit    func(r *fakeReader, s *fakeStamper)
		ref     Ref
		rule    string
		object  string
		message string
		stamps  bool // whether any stamp was read before the refusal
	}{
		{
			name: "kind absent", edit: func(r *fakeReader, _ *fakeStamper) { r.checkErr = &intent.StageKindError{} },
			ref: Ref{"change-1", "cabled"}, rule: findings.RuleStageKindAbsent, object: "FylgjaStage",
			message: "the default branch's schema has no kind FylgjaStage: load schema/fylgja-stage.yaml on it; " +
				"only --stage, stage list and stage plan need it",
		},
		{
			name: "an attribute missing",
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.checkErr = &intent.StageKindError{Missing: []string{"description"}}
			},
			ref: Ref{"change-1", "cabled"}, rule: findings.RuleStageKindAbsent, object: "FylgjaStage",
			message: "kind FylgjaStage on the default branch lacks the attribute description, which this build reads: " +
				"load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it",
		},
		{
			name: "the extension missing",
			edit: func(r *fakeReader, _ *fakeStamper) { r.checkErr = &intent.StageKindError{Extension: true} },
			ref:  Ref{"change-1", "cabled"}, rule: findings.RuleStageKindAbsent, object: "FylgjaStage",
			message: "kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml " +
				"adds: load schema/fylgja-stage.yaml on it; only --stage, stage list and stage plan need it",
		},
		{
			name: "no open proposed change on the branch, naming those with one",
			ref:  Ref{"nosuch", "cabled"}, rule: findings.RuleStageUnknown, object: "nosuch",
			message: "no open proposed change has source branch nosuch; the branches with one are: change-1, change-2",
		},
		{
			name: "no open proposed change at all", edit: func(r *fakeReader, _ *fakeStamper) { r.pcs = nil },
			ref: Ref{"change-1", "cabled"}, rule: findings.RuleStageUnknown, object: "change-1",
			message: "no open proposed change has source branch change-1; there is no open proposed change",
		},
		{
			name: "the branch deleted under its open proposed change",
			edit: func(r *fakeReader, _ *fakeStamper) { delete(r.branches, "change-1") },
			ref:  Ref{"change-1", "cabled"}, rule: findings.RuleStageUnknown, object: "change-1",
			message: "branch change-1 does not exist; the open proposed change pc-1 still names it " +
				"(Infrahub cancels it about sixteen seconds after a branch is deleted)",
		},
		{
			name: "no such stage, naming the proposed change's",
			ref:  Ref{"change-1", "nosuch"}, rule: findings.RuleStageUnknown, object: "change-1/nosuch", stamps: true,
			message: `proposed change "third link" (pc-1) on branch change-1 has no stage "nosuch"; ` +
				"its stages are: branch-point, cabled, live, head",
		},
		{
			name: "two marks share the label",
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.pcs[0].Stages = append(r.pcs[0].Stages, mark("st-cabled-0", "cabled", "2026-10-16T17:26:00.000000+00:00", nil, ""))
			},
			ref: Ref{"change-1", "cabled"}, rule: findings.RuleStageDuplicate, object: "change-1/cabled", stamps: true,
			message: "stage change-1/cabled is held by 2 objects (ids st-cabled, st-cabled-0), which the kind's uniqueness " +
				"constraint should have refused; none is chosen",
		},
		{
			name: "a mark labelled head",
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.pcs[0].Stages = append(r.pcs[0].Stages, mark("st-head", "head", "2026-10-16T17:26:00.000000+00:00", nil, ""))
			},
			ref: Ref{"change-1", "head"}, rule: findings.RuleStageLabelReserved, object: "change-1/head", stamps: true,
			message: `stage change-1/head is a mark labelled "head", which names the derived head of every proposed change ` +
				"and is reserved; relabel it (schema/README.md); the head of change-1 is still its derived stage",
		},
		{
			name: "a mark labelled branch-point",
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.pcs[0].Stages = append(r.pcs[0].Stages, mark("st-bp", "branch-point", "2026-10-16T17:26:00.000000+00:00", nil, ""))
			},
			ref: Ref{"change-1", "branch-point"}, rule: findings.RuleStageLabelReserved, object: "change-1/branch-point", stamps: true,
			message: `stage change-1/branch-point is a mark labelled "branch-point", which names the derived branch point of ` +
				"every proposed change and is reserved; relabel it (schema/README.md); the branch point of change-1 is still " +
				"its derived stage",
		},
		{
			// No as_of written, and a null label.updated_at, which genqlient decodes to "":
			// resolved, it would be the branch head, unpinned.
			name: "a mark with no at at all",
			edit: func(r *fakeReader, _ *fakeStamper) { r.pcs[0].Stages[1].LabelWrittenAt = "" },
			ref:  Ref{"change-1", "cabled"}, rule: findings.RuleStageAtUnresolved, object: "change-1/cabled", stamps: true,
			message: "stage change-1/cabled has no at: no as_of is written on it and Infrahub returned no updated_at for its " +
				"label, so it names no point in time",
		},
		{
			name: "the head of a branch holding neither a stamp nor an intent event",
			edit: func(_ *fakeReader, s *fakeStamper) { s.byBranch["change-1"] = intent.Stamps{} },
			ref:  Ref{"change-1", "head"}, rule: findings.RuleStageAtUnresolved, object: "change-1/head", stamps: true,
			message: "stage change-1/head has no at: branch change-1 holds no stamped device, interface, link or artifact, " +
				"so it names no point in time",
		},
		{
			name: "nine fractional digits",
			edit: func(r *fakeReader, _ *fakeStamper) { r.pcs[0].Stages[0].At = str("2026-10-16T17:30:00.123456789Z") },
			ref:  Ref{"change-1", "live"}, rule: findings.RuleAtPrecision, object: "change-1/live", stamps: true,
			message: "stage change-1/live: at 2026-10-16T17:30:00.123456789Z carries 9 fractional digits; Infrahub honours " +
				"at most 6 (microseconds). Write the stage's as_of with at most six.",
		},
		{
			name: "a given at in the future",
			edit: func(r *fakeReader, _ *fakeStamper) { r.pcs[0].Stages[0].At = str("2099-01-01T00:00:00Z") },
			ref:  Ref{"change-1", "live"}, rule: findings.RuleStageAtUnresolved, object: "change-1/live", stamps: true,
			message: "stage change-1/live has at 2099-01-01T00:00:00Z (given), later than the current time " +
				"2026-10-16T18:00:00.000000Z: it seals nothing yet, and a twin from it could differ between two creates",
		},
		{
			name: "before the branch point, after a rebase",
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.branches["change-1"].BranchedFrom = "2026-10-16T17:37:22.940060Z"
			},
			ref: Ref{"change-1", "cabled"}, rule: findings.RuleStageAtBeforeBranchPoint, object: "change-1/cabled", stamps: true,
			message: "stage change-1/cabled has at 2026-10-16T17:25:30.118244+00:00, before the branch point " +
				"2026-10-16T17:37:22.940060Z of change-1: a rebase at 2026-10-16T17:37:22.940060Z moved the branch point " +
				"past it (the branch was created at 2026-10-16T17:20:19.944511Z); mark the stage again, or delete it",
		},
		{
			name: "before the branch was created",
			edit: func(r *fakeReader, _ *fakeStamper) { r.pcs[0].Stages[0].At = str("2026-10-16T17:00:00Z") },
			ref:  Ref{"change-1", "live"}, rule: findings.RuleStageAtBeforeBranchPoint, object: "change-1/live", stamps: true,
			message: "stage change-1/live has at 2026-10-16T17:00:00Z, before the branch point 2026-10-16T17:20:19.944651Z " +
				"of change-1, and before the branch was created at 2026-10-16T17:20:19.944511Z; a stage names a moment on " +
				"its source branch",
		},
		{
			name: "stale",
			edit: func(_ *fakeReader, s *fakeStamper) { s.at = map[string]intent.Stamps{"change-1@" + cabledAt: stale} },
			ref:  Ref{"change-1", "cabled"}, rule: findings.RuleStageArtifactStale, object: "n1", stamps: true,
			message: "device n1: its intent on change-1 was written at 2026-10-16T17:24:00.000000+00:00, later than its " +
				"artifact device-config was generated (checksum stamped 2026-10-16T17:22:00.000000+00:00; no artifact " +
				"validator of the proposed change had completed): stage change-1/cabled was marked before the artifacts " +
				"were regenerated; regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed " +
				"change's checks: a retry in Infrahub, or CoreProposedChangeRunCheck) and mark again",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, s := story()
			if tc.edit != nil {
				tc.edit(r, s)
			}
			res, list, err := Resolve(t.Context(), r, s, registry(t), tc.ref, now)
			if err != nil {
				t.Fatalf("a refusal returned as an error: %v", err)
			}
			if !reflect.DeepEqual(res, Resolved{}) {
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
			// Exit 1 for each: intent.at.precision's 2 is the server's, where it ends a
			// command, as M10's was.
			if code := findings.NewDocument(findings.OpTwinCreate, nil, list).Status.ExitCode(); code != findings.ExitRejected {
				t.Errorf("exit %d, want %d", code, findings.ExitRejected)
			}
			if (len(s.calls) > 0) != tc.stamps {
				t.Errorf("stamps read %v; want any: %v", s.calls, tc.stamps)
			}
		})
	}
}

// A resolution that succeeds, for each kind of stage: a written mark at its label's
// updated_at, a given one at its as_of, the branch point on the destination at
// branched_from, the head one microsecond after the branch's latest stamp. Each verbatim.
func TestResolveResolves(t *testing.T) {
	for _, tc := range []struct {
		ref  Ref
		want Resolved
	}{
		{Ref{"change-1", "cabled"}, Resolved{Ref: Ref{"change-1", "cabled"}, Branch: "change-1", Label: "cabled",
			ProposedChange: pc1, At: cabledAt, AtSource: AtWritten, Description: "after the link is cabled", ID: "st-cabled"}},
		{Ref{"change-1", "live"}, Resolved{Ref: Ref{"change-1", "live"}, Branch: "change-1", Label: "live",
			ProposedChange: pc1, At: liveAt, AtSource: AtGiven, Description: "after its configuration is live", ID: "st-live"}},
		{Ref{"change-1", "branch-point"}, Resolved{Ref: Ref{"change-1", "branch-point"}, Branch: "main", Label: "branch-point",
			ProposedChange: pc1, At: branchedFrom, AtSource: AtBranchPoint}},
		{Ref{"change-1", "head"}, Resolved{Ref: Ref{"change-1", "head"}, Branch: "change-1", Label: "head",
			ProposedChange: pc1, At: headAt, AtSource: AtHead}},
	} {
		t.Run(tc.ref.String(), func(t *testing.T) {
			r, s := story()
			got, list, err := Resolve(t.Context(), r, s, registry(t), tc.ref, now)
			if err != nil || len(list) != 0 {
				t.Fatalf("%v %+v", err, list)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("resolved\n  %+v\nwant\n  %+v", got, tc.want)
			}
		})
	}
}

// A written at after the server's clock resolves, verbatim and written: it is Infrahub's
// own stamp of a write it has already made. The same instant given as the mark's as_of is
// refused.
func TestResolveWrittenAtAfterTheClock(t *testing.T) {
	const ahead = "2026-10-16T18:00:00.000001+00:00"
	r, s := story(change1(mark("st-new", "new", ahead, nil, "")))
	got, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "new"}, now)
	if err != nil || len(list) != 0 || got.At != ahead || got.AtSource != AtWritten {
		t.Fatalf("a written at after the clock: %+v %v %+v", got, err, list)
	}
	r, s = story(change1(mark("st-new", "new", ahead, str(ahead), "")))
	_, list, err = Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "new"}, now)
	if err != nil || len(list) != 1 || list[0].Rule != findings.RuleStageAtUnresolved {
		t.Errorf("the same instant given: %v %+v; want stage.at.unresolved", err, list)
	}
}

// The order's ends are fixed: the branch point first and the head last whatever the
// marks' stamps, so a mark written after the head's at still sorts before the head. The
// marks go by at, two equal ats by label, and an at Go cannot read after those it can, by
// its string.
func TestOrderEndsFixed(t *testing.T) {
	late := "2026-10-16T17:45:00.000000+00:00" // after headAt
	r, s := story(change1(
		mark("st-late", "late", late, nil, ""),
		mark("st-b", "b", "", str(liveAt), ""),
		mark("st-a", "a", "", str("2026-10-16T19:30:00+02:00"), ""), // liveAt, in another offset
		mark("st-y", "yesterday", "", str("yesterday"), ""),
		mark("st-x", "unread", "", str("the day it went live"), ""),
		mark("st-cabled", "cabled", cabledAt, nil, ""),
	))
	ch, list, err := Find(t.Context(), r, s, "change-1")
	if err != nil || list != nil {
		t.Fatalf("%v %+v", err, list)
	}
	want := []string{"branch-point", "cabled", "a", "b", "late", "unread", "yesterday", "head"}
	if got := ch.Labels(); !reflect.DeepEqual(got, want) {
		t.Errorf("order %v, want %v", got, want)
	}
	if head := ch.Stages[len(ch.Stages)-1]; head.At != headAt || head.Mark != nil {
		t.Errorf("the last stage is %+v; want the head at %s", head.Resolved, headAt)
	}
	if lateAt, _ := ParseAt(late); !lateAt.After(mustParse(t, headAt)) {
		t.Fatal("the case's late mark is not after the head's at")
	}

	// Order alone, from any order in, keeps the same.
	shuffled := slices.Clone(ch.Stages)
	slices.Reverse(shuffled)
	var labels []string
	for _, st := range Order(shuffled) {
		labels = append(labels, st.Label)
	}
	if !reflect.DeepEqual(labels, want) {
		t.Errorf("Order of the reversed stages: %v, want %v", labels, want)
	}
}

func mustParse(t *testing.T, s string) time.Time {
	t.Helper()
	at, ok := ParseAt(s)
	if !ok {
		t.Fatalf("%q does not parse", s)
	}
	return at
}

// The head's at is the latest stamp plus one microsecond, in Infrahub's own layout and the
// stamp's own offset; a Z stamp comes back as +00:00, and a rollover carries.
func TestHeadIsLatestStampPlusOneMicrosecond(t *testing.T) {
	for in, want := range map[string]string{
		"2026-10-08T05:48:38.544482+00:00": "2026-10-08T05:48:38.544483+00:00",
		"2026-10-08T05:48:38.544482Z":      "2026-10-08T05:48:38.544483+00:00",
		"2026-10-08T05:48:59.999999+00:00": "2026-10-08T05:49:00.000000+00:00",
		"2026-12-31T23:59:59.999999Z":      "2027-01-01T00:00:00.000000+00:00",
		"2026-10-08T07:48:38.5+02:00":      "2026-10-08T07:48:38.500001+02:00",
		"2026-10-08T05:48:38Z":             "2026-10-08T05:48:38.000001+00:00",
	} {
		got, err := HeadAt(in)
		if err != nil || got != want {
			t.Errorf("HeadAt(%s) = %s, %v; want %s", in, got, err, want)
		}
	}
	if _, err := HeadAt("yesterday"); err == nil {
		t.Error("HeadAt read a stamp that is not RFC 3339")
	}
}

// A rebase moves branched_from past every mark at once, and each is refused naming the
// rebase; the derived stages still resolve, the branch point at the new branched_from.
// A mark written before the branch was created is refused in the other wording.
func TestRebaseIsNamed(t *testing.T) {
	const rebased = "2026-10-16T17:37:22.940060Z"
	r, s := story()
	r.branches["change-1"].BranchedFrom = rebased
	s.byBranch["change-1"] = freshStamps("2026-10-16T17:37:22.940060+00:00") // a rebase re-stamps the branch
	ch, list, err := Find(t.Context(), r, s, "change-1")
	if err != nil || list != nil {
		t.Fatalf("%v %+v", err, list)
	}
	for _, label := range []string{"cabled", "live"} {
		_, list, err := ResolveFrom(t.Context(), r, s, registry(t), ch, Ref{"change-1", label}, now)
		if err != nil || len(list) != 1 || list[0].Rule != findings.RuleStageAtBeforeBranchPoint ||
			!strings.Contains(list[0].Message, ": a rebase at "+rebased+" moved the branch point past it (the branch was created at "+createdAt+")") {
			t.Errorf("%s: %v %+v", label, err, list)
		}
	}
	for label, at := range map[string]string{"branch-point": rebased, "head": "2026-10-16T17:37:22.940061+00:00"} {
		got, list, err := ResolveFrom(t.Context(), r, s, registry(t), ch, Ref{"change-1", label}, now)
		if err != nil || list.Rejected() || got.At != at {
			t.Errorf("%s after the rebase: %+v %v %+v; want at %s", label, got, err, list, at)
		}
	}

	r, s = story(change1(mark("st-old", "old", "", str("2026-10-16T17:20:19.944511Z"), "")))
	_, list, err = Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "old"}, now)
	if err != nil || len(list) != 1 || list[0].Rule != findings.RuleStageAtBeforeBranchPoint ||
		!strings.HasSuffix(list[0].Message, "and before the branch was created at "+createdAt+"; a stage names a moment on its source branch") {
		t.Errorf("a mark at the branch's creation: %v %+v", err, list)
	}
}

// main written after the branch point warns stage.main.moved beside the resolution and
// refuses nothing; main written before it, or holding nothing, warns of nothing.
func TestMainMovedWarns(t *testing.T) {
	r, s := story()
	s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:50:00.000000+00:00"}
	got, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "cabled"}, now)
	if err != nil || got.At != cabledAt {
		t.Fatalf("%+v %v", got, err)
	}
	want := findings.List{{Severity: findings.Warning, Rule: findings.RuleStageMainMoved, Object: "change-1", Step: findings.StepResolve,
		Message: "main has moved since change-1's branch point: its latest write is 2026-10-16T17:50:00.000000+00:00, " +
			"the branch point " + branchedFrom + "; the branch point stage still reads main as it was then, and nothing is refused"}}
	if !reflect.DeepEqual(list, want) || list.Rejected() {
		t.Errorf("findings:\n%+v\nwant\n%+v", list, want)
	}
	if !slices.Contains(s.calls, "main@") {
		t.Errorf("stamps read %v; want main's unpinned", s.calls)
	}

	for name, latest := range map[string]string{"before": "2026-10-16T17:00:00.000000+00:00", "empty": ""} {
		r, s := story()
		s.byBranch["main"] = intent.Stamps{Latest: latest}
		if _, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "cabled"}, now); err != nil || list != nil {
			t.Errorf("main %s: %v %+v", name, err, list)
		}
	}
}

// The server's clock is compared with a given as_of alone and never sent: whatever a
// resolution reads, no at it asks for is now's, and a future as_of is refused before any
// pinned read.
func TestFutureAsOfNeverSent(t *testing.T) {
	sent := func(r *fakeReader, s *fakeStamper) []string {
		var ats []string
		for _, c := range s.calls {
			ats = append(ats, c[strings.Index(c, "@")+1:])
		}
		for _, c := range r.calls {
			if at, ok := strings.CutPrefix(c, "Validations pc-1@"); ok {
				ats = append(ats, at)
			}
		}
		return ats
	}
	stale := freshStamps(headLatest)
	stale.Devices["n1"] = device("2026-10-16T17:24:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
	for _, ref := range []Ref{{"change-1", "cabled"}, {"change-1", "live"}, {"change-1", "head"}, {"change-1", "branch-point"}, {"change-1", "future"}} {
		r, s := story(change1(append(change1().Stages, mark("st-f", "future", cabledAt, str("2099-01-01T00:00:00Z"), ""))...))
		s.byBranch["change-1"] = stale // every stage read reaches the validator
		_, _, err := Resolve(t.Context(), r, s, registry(t), ref, now)
		if err != nil {
			t.Fatal(err)
		}
		for _, at := range sent(r, s) {
			if t2, ok := ParseAt(at); ok && t2.Equal(now) {
				t.Errorf("%s: the server's clock was sent as %s", ref, at)
			}
			if at == "2099-01-01T00:00:00Z" {
				t.Errorf("%s: the future as_of was sent", ref)
			}
		}
	}
}

// A reader or stamper that cannot reach Infrahub, or is refused its credential, returns
// that error as it is: never a refusal, never a finding.
func TestResolveReturnsTheReadersError(t *testing.T) {
	down := errors.New("reading the schema (the default branch): connection refused")
	stale := freshStamps(headLatest)
	stale.Devices["n1"] = device("2026-10-16T17:24:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
	for name, edit := range map[string]func(r *fakeReader, s *fakeStamper){
		"Check":           func(r *fakeReader, _ *fakeStamper) { r.checkErr = down },
		"ProposedChanges": func(r *fakeReader, _ *fakeStamper) { r.pcErr = down },
		"Branch":          func(r *fakeReader, _ *fakeStamper) { r.branchErr = down },
		"Stamps":          func(_ *fakeReader, s *fakeStamper) { s.err = down },
		"Validations": func(r *fakeReader, s *fakeStamper) {
			r.validationsErr = down
			s.at = map[string]intent.Stamps{"change-1@" + cabledAt: stale}
		},
	} {
		r, s := story()
		edit(r, s)
		_, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "cabled"}, now)
		if !errors.Is(err, down) || list != nil {
			t.Errorf("%s failing: err %v, findings %+v; want the reader's error and no finding", name, err, list)
		}
	}
	// Two open proposed changes on one branch, which Infrahub refuses: none is chosen.
	r, s := story(change1(), change1())
	if _, _, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "cabled"}, now); err == nil ||
		!strings.Contains(err.Error(), "has 2 open proposed changes (ids pc-1, pc-1), which Infrahub refuses; none is chosen") {
		t.Errorf("two open proposed changes: %v", err)
	}
}

// ParseAt reads every form Infrahub was seen to accept and keep, a naive one as UTC, and
// makes no claim about a form none of its layouts reads.
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
