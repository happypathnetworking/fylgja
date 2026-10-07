package lab

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// TwinVersion is the twin.json format version (contracts/twin.schema.json). Version 2 named
// what each node was pushed and how long it took;
// version 3 names the waypoint the twin was created from, or null; version 4
// says whether the twin is ready or diverged, carries its last step or null, and names
// the bundle each node holds; version 5 carries the step's wait,
// step.wait, or null while it has not run.
const TwinVersion = "5"

// ObservedAtUnknown is what twin.json says when no read took place, so a null
// observed_at is an explicit statement rather than a missing value (Constitution VI).
const ObservedAtUnknown = "unknown: provisioned from an existing bundle; no read took place"

// RecordFields are the parts of a twin record that vary from twin to twin; NewRecord
// supplies the rest.
type RecordFields struct {
	BundleID   string
	Provenance wire.Provenance
	ObservedAt *string // nil when no read took place
	Source     string  // wire.SourceIntent or wire.SourceBundle
	RunID      string
	Version    string // the worker binary's --version
	RecordedAt time.Time
	Nodes      []wire.TwinNode
	Waypoint   *wire.WaypointRef // nil unless the CLI resolved the reference from a waypoint
}

// NewRecord builds twin.json's content and refuses a record the contract would not
// accept: a twin created from intent always had a read, so its observed_at is known,
// and a twin provisioned from a bundle never did, so its observed_at is null and the
// note says why. A waypoint is recorded only on a pinned twin created from intent (M10):
// a bundle carries no waypoint, and a waypoint always resolves to an at.
func NewRecord(f RecordFields) (wire.TwinRecord, error) {
	switch f.Source {
	case wire.SourceIntent:
		if f.ObservedAt == nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin created from intent must record when the intent was observed")
		}
	case wire.SourceBundle:
		if f.ObservedAt != nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin provisioned from a bundle had no read, so it cannot record observed_at %q", *f.ObservedAt)
		}
		if w := f.Waypoint; w != nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin provisioned from a bundle cannot record waypoint %s/%d: a bundle carries no waypoint", w.Series, w.Sequence)
		}
	default:
		return wire.TwinRecord{}, fmt.Errorf("unknown twin source %q", f.Source)
	}
	if w := f.Waypoint; w != nil && f.Provenance.At == "" {
		return wire.TwinRecord{}, fmt.Errorf("a twin created from waypoint %s/%d must record its at: a waypoint twin is pinned", w.Series, w.Sequence)
	}
	if !bundle.IsID(f.BundleID) {
		return wire.TwinRecord{}, fmt.Errorf("%q is not a bundle identity", f.BundleID)
	}
	if f.RunID == "" {
		return wire.TwinRecord{}, fmt.Errorf("a twin record must name its provisioning run")
	}

	nodes := append([]wire.TwinNode(nil), f.Nodes...)
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].Name < nodes[j].Name })
	if nodes == nil {
		nodes = []wire.TwinNode{}
	}
	// A create pushed every node the bundle names, so each holds the record's
	// bundle.
	for i := range nodes {
		holds := f.BundleID
		nodes[i].Holds = &holds
	}
	rec := wire.TwinRecord{
		TwinVersion:   TwinVersion,
		Lab:           LabName,
		BundleID:      f.BundleID,
		Provenance:    f.Provenance,
		ObservedAt:    f.ObservedAt,
		Source:        f.Source,
		Run:           wire.RunRef{WorkflowID: wire.ProvisionWorkflowID, RunID: f.RunID},
		ProvisionedBy: wire.ProvisionedBy{Version: f.Version},
		RecordedAt:    f.RecordedAt.UTC().Format(time.RFC3339Nano),
		Nodes:         nodes,
		Waypoint:      f.Waypoint,
		State:         wire.StateReady,
	}
	if rec.ObservedAt == nil {
		rec.ObservedAtNote = ObservedAtUnknown
	}
	return rec, nil
}

// WriteRecord writes twin.json atomically: a reader sees the whole record or none. Its
// presence is what distinguishes a twin from an orphan, so a half-written one would be
// worse than none (glossary).
func WriteRecord(path string, rec wire.TwinRecord) error {
	b, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".twin-*.json")
	if err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(append(b, '\n')); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("writing %s: %w", path, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	return nil
}

// RecordTwin writes twin.json, last: its presence beside a lab is what makes the lab a
// twin rather than an orphan (glossary). Provenance, each node's package and its
// artifact come from the staged manifest, verbatim; containers and addresses from deploy;
// how long each node took from readiness and its push; the version from this worker's
// binary. A node deploy reports that the manifest does not name, or that no push result
// names, is refused: the record would claim a twin the run did not build. No
// artifact's bytes are recorded, only its identity. It returns the record
// exactly as written, so the workflow reports it without reading disk (Constitution VIII).
func (a *Activities) RecordTwin(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
	path := a.Paths.TwinJSON
	failed := func(format string, args ...any) (wire.RecordResult, error) {
		return wire.RecordResult{}, StepFailure(findings.StepRecord, findings.RuleRecordFailed, path,
			fmt.Sprintf("writing %s: "+format, append([]any{path}, args...)...))
	}

	m, err := readManifest(a.Paths.TwinBundle)
	if err != nil {
		return failed("%v", err)
	}
	pspOf := make(map[string]wire.PSPRef, len(m.Nodes))
	artifactOf := make(map[string]*wire.TwinArtifact, len(m.Nodes))
	for _, n := range m.Nodes {
		pspOf[n.Name] = wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}
		if a := n.Artifact; a != nil {
			artifactOf[n.Name] = &wire.TwinArtifact{Name: a.Name, ContentType: a.ContentType, Checksum: a.Checksum, Size: a.Size}
		}
	}
	readyAfter := make(map[string]float64, len(in.ReadyAfter))
	for _, r := range in.ReadyAfter {
		readyAfter[r.Node] = r.ReadyAfterS
	}
	pushedIn := make(map[string]float64, len(in.Pushed))
	for _, p := range in.Pushed {
		pushedIn[p.Node] = p.PushedInS
	}
	nodes := make([]wire.TwinNode, 0, len(in.Nodes))
	for _, n := range in.Nodes {
		ref, ok := pspOf[n.Name]
		if !ok {
			return failed("containerlab reports node %s, which the staged manifest does not name", n.Name)
		}
		artifact, ok := artifactOf[n.Name]
		if !ok {
			return failed("the staged manifest names no artifact for node %s", n.Name)
		}
		took, ok := pushedIn[n.Name]
		if !ok {
			return failed("no push result names node %s, so it cannot be recorded as running its artifact", n.Name)
		}
		nodes = append(nodes, wire.TwinNode{
			Name:        n.Name,
			Container:   n.Container,
			Image:       n.Image,
			PSP:         ref,
			MgmtIPv4:    n.MgmtIPv4,
			ReadyAfterS: readyAfter[n.Name],
			Artifact:    artifact,
			PushedInS:   took,
		})
	}

	rec, err := NewRecord(RecordFields{
		BundleID:   in.BundleID,
		Provenance: wire.Provenance(m.Provenance),
		ObservedAt: in.ObservedAt,
		Source:     in.Source,
		RunID:      in.RunID,
		Version:    a.Version,
		RecordedAt: time.Now(),
		Nodes:      nodes,
		Waypoint:   in.Waypoint,
	})
	if err != nil {
		return failed("%v", err)
	}
	if err := WriteRecord(path, rec); err != nil {
		return failed("%v", err)
	}
	return wire.RecordResult{Path: path, Record: rec}, nil
}

// ReadRecord reads twin.json. A version 1 or 2 record has no waypoint key and reads with
// Waypoint nil; a version 3 or earlier one has no state, step or holds, and reads with
// State "" (shown as ready), Step nil and every Holds nil (shown as the record's
// bundle_id); a version 4 one's step has no wait and reads with Step.Wait nil, as a
// version 5 one's does while its wait has not run.
func ReadRecord(path string) (wire.TwinRecord, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return wire.TwinRecord{}, err
	}
	var rec wire.TwinRecord
	if err := json.Unmarshal(b, &rec); err != nil {
		return wire.TwinRecord{}, fmt.Errorf("reading %s: %w", path, err)
	}
	return rec, nil
}

// StepFields are what a step's record is built from beside the previous record:
// the two sides and the outcome, the run, containerlab's plan and
// what came of it, each push of the plan with its outcome, the timings, and the target
// as the twin directory holds it.
type StepFields struct {
	Outcome      string // wire.StepStepped, StepUnchanged or StepDiverged
	Phase        string // reconcile, readiness, push or record when diverged; "" otherwise
	From, To     wire.StepSide
	ObservedAt   string // the target's read's observed_at, the record's own once it moves
	RunID        string // the fylgja-step run
	Version      string // the worker binary's --version
	AllowRestart bool
	Plan         wire.ReconcilePlan
	// Declared is each node's package's fidelity.link_change, beside what containerlab
	// reported.
	Declared map[string]string
	// ReconcileStarted says containerlab's reconcile ran, or may have: the plan's
	// restarted, recreated and created nodes then run their baseline until a push lands.
	ReconcileStarted bool
	// ReconcileTookS is the apply's time; nil when the reconcile was skipped or the apply
	// failed.
	ReconcileTookS *float64
	ReadyAfter     []wire.ReadinessResult
	// Pushed is the push plan, each node with its reasons and what came of its push.
	Pushed     []wire.StepPush
	Findings   findings.List // the failure's, for a diverged step
	StartedAt  string        // RFC 3339, the run's start
	EndedAt    string        // RFC 3339, the record step's start
	RecordedAt time.Time
	// Nodes are the lab's nodes after the step, as containerlab reported them.
	Nodes []wire.LabNode
	// Staged is the target as the twin directory holds it, or nil when the twin directory
	// does not hold the target: a step stopped at its stage.
	Staged *StagedTarget
}

// StagedTarget is the target bundle as it is staged: the identity it hashes to and what
// its manifest says of provenance, packages and artifacts.
type StagedTarget struct {
	BundleID   string
	Provenance wire.Provenance
	PSP        map[string]wire.PSPRef
	Artifacts  map[string]*wire.TwinArtifact
}

// NewStepRecord builds the record a step leaves (contracts/twin.schema.json
// version 5) from the record the step started from, and refuses what the contract would
// not accept, or what would claim more than the step did:
//
//   - a previous record that is not the step's from side (another bundle or waypoint), or
//     is diverged, which no step starts from;
//   - a phase given to a stepped or unchanged step, or none, or another, to a diverged one;
//   - a stepped or unchanged step whose staged target is absent, hashes to another
//     identity than its to side, or carries another at; or whose push plan holds a push
//     that did not land; or whose lab runs a node the target does not name, or lacks one
//     it does;
//   - a node of the previous record holding a bundle that is neither side.
//
// After a stepped or unchanged step the top level is the target's and every node holds
// it: a pushed node landed its bundle, and a node the step left alone runs what both
// bundles give it. After a diverged step the top level stays the previous record's; a
// node whose push landed holds the target, one containerlab restarted, recreated or
// created that no push reached holds nothing (null) and runs its baseline, and
// every other node holds what it held. run and provisioned_by stay the create's. The
// step's wait is null: the record is written before the wait, which VerifyTwin then
// writes into it.
func NewStepRecord(prev wire.TwinRecord, f StepFields) (wire.TwinRecord, error) {
	if !bundle.IsID(f.From.BundleID) || !bundle.IsID(f.To.BundleID) {
		return wire.TwinRecord{}, fmt.Errorf("a step is between two bundle identities, not %q and %q", f.From.BundleID, f.To.BundleID)
	}
	if prev.BundleID != f.From.BundleID {
		return wire.TwinRecord{}, fmt.Errorf("the record names bundle %s, not bundle %s the step started from", prev.BundleID, f.From.BundleID)
	}
	if !sameWaypoint(prev.Waypoint, f.From.Waypoint) {
		return wire.TwinRecord{}, fmt.Errorf("the record names waypoint %s, not waypoint %s the step started from",
			waypointName(prev.Waypoint), waypointName(f.From.Waypoint))
	}
	if prev.State == wire.StateDiverged {
		return wire.TwinRecord{}, fmt.Errorf("the record is diverged; no step starts from a diverged twin")
	}
	if f.RunID == "" {
		return wire.TwinRecord{}, fmt.Errorf("a step's record must name its step run")
	}
	started, err1 := time.Parse(time.RFC3339Nano, f.StartedAt)
	ended, err2 := time.Parse(time.RFC3339Nano, f.EndedAt)
	if err1 != nil || err2 != nil {
		return wire.TwinRecord{}, fmt.Errorf("a step's started_at %q and ended_at %q must be RFC 3339", f.StartedAt, f.EndedAt)
	}
	for _, n := range prev.Nodes {
		if h := n.Holds; h != nil && *h != f.From.BundleID && *h != f.To.BundleID {
			return wire.TwinRecord{}, fmt.Errorf("node %s holds bundle %s, which is neither side of the step (%s, %s)",
				n.Name, *h, f.From.BundleID, f.To.BundleID)
		}
	}

	outcome := map[string]wire.StepPush{}
	for _, p := range f.Pushed {
		outcome[p.Node] = p
	}
	moved := false
	switch f.Outcome {
	case wire.StepStepped, wire.StepUnchanged:
		moved = true
		if f.Phase != "" {
			return wire.TwinRecord{}, fmt.Errorf("a %s step has no failed phase, but %q was given", f.Outcome, f.Phase)
		}
		if err := targetStaged(f); err != nil {
			return wire.TwinRecord{}, err
		}
		for _, p := range f.Pushed {
			if p.Outcome != wire.PushLanded {
				return wire.TwinRecord{}, fmt.Errorf("a %s step landed every push, but node %s's is %s", f.Outcome, p.Node, p.Outcome)
			}
		}
		if err := labIsTarget(f); err != nil {
			return wire.TwinRecord{}, err
		}
	case wire.StepDiverged:
		switch f.Phase {
		case findings.StepReconcile, findings.StepReadiness, findings.StepPush, findings.StepRecord:
		default:
			return wire.TwinRecord{}, fmt.Errorf("a diverged step names the phase it stopped at, one of reconcile, readiness, push or record, not %q", f.Phase)
		}
		for _, p := range f.Pushed {
			if p.Outcome == wire.PushLanded && (f.Staged == nil || f.Staged.BundleID != f.To.BundleID) {
				return wire.TwinRecord{}, fmt.Errorf("node %s's push landed, but the twin directory does not hold the target bundle %s", p.Node, f.To.BundleID)
			}
		}
	default:
		return wire.TwinRecord{}, fmt.Errorf("unknown step outcome %q", f.Outcome)
	}

	rec := prev
	rec.TwinVersion = TwinVersion
	rec.Lab = LabName
	rec.RecordedAt = f.RecordedAt.UTC().Format(time.RFC3339Nano)
	rec.State = wire.StateDiverged
	if moved {
		observed := f.ObservedAt
		rec.BundleID = f.To.BundleID
		rec.Provenance = f.Staged.Provenance
		rec.ObservedAt = &observed
		rec.ObservedAtNote = ""
		rec.Waypoint = f.To.Waypoint
		rec.State = wire.StateReady
	}
	rec.Nodes = stepNodes(prev, f, moved, outcome)
	rec.Step = stepBlock(f, ended.Sub(started))
	return rec, nil
}

// targetStaged refuses a step that moves the record to a target the twin directory does
// not hold: the record would name what does not run.
func targetStaged(f StepFields) error {
	switch s := f.Staged; {
	case s == nil:
		return fmt.Errorf("a %s step moves the record to bundle %s, but the twin directory does not hold it", f.Outcome, f.To.BundleID)
	case s.BundleID != f.To.BundleID:
		return fmt.Errorf("the twin directory holds bundle %s, not bundle %s the step went to", s.BundleID, f.To.BundleID)
	case s.Provenance.At != f.To.At:
		return fmt.Errorf("the staged manifest is pinned at %q, not at %q the step went to", s.Provenance.At, f.To.At)
	}
	return nil
}

// labIsTarget refuses a stepped or unchanged step whose lab is not the target's: a node
// containerlab runs that the target does not name, or one the target names that is not
// running. The record would claim a twin the step did not leave.
func labIsTarget(f StepFields) error {
	running := map[string]bool{}
	for _, n := range f.Nodes {
		if _, ok := f.Staged.PSP[n.Name]; !ok {
			return fmt.Errorf("containerlab reports node %s, which the target bundle %s does not name", n.Name, f.To.BundleID)
		}
		running[n.Name] = true
	}
	for name := range f.Staged.PSP {
		if !running[name] {
			return fmt.Errorf("the target bundle %s names node %s, which containerlab does not report", f.To.BundleID, name)
		}
	}
	return nil
}

// stepNodes is the record's nodes after the step, in name order: one per node containerlab
// reports, each holding the bundle it runs.
func stepNodes(prev wire.TwinRecord, f StepFields, moved bool, pushes map[string]wire.StepPush) []wire.TwinNode {
	before := map[string]wire.TwinNode{}
	for _, n := range prev.Nodes {
		before[n.Name] = n
	}
	baseline := map[string]bool{}
	if f.ReconcileStarted {
		for _, list := range [][]string{f.Plan.Restarted, f.Plan.Recreated, f.Plan.Added} {
			for _, n := range list {
				baseline[n] = true
			}
		}
	}
	ready := map[string]float64{}
	for _, r := range f.ReadyAfter {
		ready[r.Node] = r.ReadyAfterS
	}
	nodes := make([]wire.TwinNode, 0, len(f.Nodes))
	for _, lab := range f.Nodes {
		was, existed := before[lab.Name]
		n := wire.TwinNode{Name: lab.Name, Container: lab.Container, Image: lab.Image, MgmtIPv4: lab.MgmtIPv4,
			PSP: was.PSP, Artifact: was.Artifact, ReadyAfterS: was.ReadyAfterS, PushedInS: was.PushedInS}
		if s, ok := ready[lab.Name]; ok {
			n.ReadyAfterS = s
		}
		target := func() {
			if f.Staged == nil {
				return
			}
			if ref, ok := f.Staged.PSP[lab.Name]; ok {
				n.PSP = ref
			}
			if a := f.Staged.Artifacts[lab.Name]; a != nil {
				n.Artifact = a
			}
		}
		p := pushes[lab.Name]
		switch {
		case p.Outcome == wire.PushLanded || moved:
			to := f.To.BundleID
			n.Holds = &to
			target()
			if p.Outcome == wire.PushLanded && p.TookS != nil {
				n.PushedInS = *p.TookS
			}
		case baseline[lab.Name]:
			// Restarted, recreated or created, and no push reached it: it runs the baseline
			// containerlab left. A recreated or created node runs the target's image and
			// package; its artifact is the one it held before, or the target's for a node
			// that had none.
			n.Holds = nil
			n.PushedInS = 0
			if !existed || slices.Contains(f.Plan.Recreated, lab.Name) {
				target()
				if existed && was.Artifact != nil {
					n.Artifact = was.Artifact
				}
			}
		default:
			from := f.From.BundleID
			n.Holds = &from
		}
		nodes = append(nodes, n)
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].Name < nodes[j].Name })
	return nodes
}

// stepBlock is the record's step block. whole is the run's duration from
// its start to its record.
func stepBlock(f StepFields, whole time.Duration) *wire.StepRecord {
	side := func(s wire.StepSide) wire.StepSide {
		s.Branch = "" // a record's sides carry no branch (twin.schema.json)
		return s
	}
	list := func(l []string) []string {
		out := append([]string{}, l...)
		sort.Strings(out)
		return out
	}
	block := &wire.StepRecord{
		Outcome:       f.Outcome,
		From:          side(f.From),
		To:            side(f.To),
		Run:           wire.RunRef{WorkflowID: wire.StepWorkflowID, RunID: f.RunID},
		WorkerVersion: f.Version,
		AllowRestart:  f.AllowRestart,
		Reconcile: wire.StepReconcile{
			// An unchanged step's run skips the reconcile whatever containerlab's plan
			// says; the lists stay the plan as read.
			Skipped:          f.Plan.Empty() || f.Outcome == wire.StepUnchanged,
			Added:            list(f.Plan.Added),
			Deleted:          list(f.Plan.Deleted),
			Recreated:        list(f.Plan.Recreated),
			Restarted:        list(f.Plan.Restarted),
			LinksAdded:       list(f.Plan.LinksAdded),
			EndpointsDeleted: list(f.Plan.EndpointsDeleted),
			Nodes:            []wire.StepReconcileNode{},
			TookS:            f.ReconcileTookS,
		},
		Pushed:     append([]wire.StepPush{}, f.Pushed...),
		ReadyAfter: []wire.StepReadyAfter{},
		Timings:    wire.StepTimings{ReconcileS: f.ReconcileTookS, WholeS: whole.Seconds()},
		StartedAt:  f.StartedAt,
		EndedAt:    f.EndedAt,
		Findings:   []wire.StepFinding{},
	}
	if f.Outcome == wire.StepDiverged {
		phase := f.Phase
		block.Phase = &phase
		for _, x := range f.Findings {
			block.Findings = append(block.Findings, wire.StepFinding{Rule: x.Rule, Object: x.Object, Message: x.Message})
		}
	}
	for _, n := range f.Plan.Nodes() {
		node := wire.StepReconcileNode{Node: n.Node, Reported: n.Reported, Reason: n.Reason}
		if d, ok := f.Declared[n.Node]; ok && n.Reported != wire.ReportedCreate {
			node.Declared = &d
		}
		block.Reconcile.Nodes = append(block.Reconcile.Nodes, node)
	}
	sort.Slice(block.Pushed, func(i, j int) bool { return block.Pushed[i].Node < block.Pushed[j].Node })
	for _, r := range f.ReadyAfter {
		block.ReadyAfter = append(block.ReadyAfter, wire.StepReadyAfter(r))
		if block.Timings.Readiness == nil {
			block.Timings.Readiness = map[string]float64{}
		}
		block.Timings.Readiness[r.Node] = r.ReadyAfterS
	}
	sort.Slice(block.ReadyAfter, func(i, j int) bool { return block.ReadyAfter[i].Node < block.ReadyAfter[j].Node })
	for _, p := range block.Pushed {
		if p.TookS == nil {
			continue
		}
		if block.Timings.Push == nil {
			block.Timings.Push = map[string]float64{}
		}
		block.Timings.Push[p.Node] = *p.TookS
	}
	return block
}

// sameWaypoint says whether two records name the same waypoint, nil included.
func sameWaypoint(a, b *wire.WaypointRef) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// waypointName is a waypoint as a refusal names it.
func waypointName(w *wire.WaypointRef) string {
	if w == nil {
		return "none"
	}
	return fmt.Sprintf("%s/%d", w.Series, w.Sequence)
}
