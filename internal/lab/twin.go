package lab

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// TwinVersion is the twin.json format version (contracts/twin.schema.json). Version 2 named
// what each node was pushed and how long it took;
// version 3 names the pinned reference the twin was created from (M10's), or null; version 4
// says whether the twin is ready or diverged, carries its last step or null, and names
// the bundle each node holds; version 5 carries the step's wait,
// step.wait, or null while it has not run; version 6 names the stage the twin was created
// from or stepped to, with its proposed change, in place of version 3's reference (014);
// version 7 names the rehearsal run whose baseline the twin is, or null (015); version 8's
// provenance is bundle 5's, naming the scope and the mapping in place of the generics
// contract's version (017); version 9 names the snapshot the twin was built from or last
// stepped to, or null, each step side's snapshot when it is known, and a third source,
// snapshot (018); version 10 lets a stage stand beside any source, since source says how the
// twin was created and a step keeps it, so a twin created from a snapshot and stepped to a
// stage names both (019); version 11 records a probe's host among the nodes, with its probe
// in place of a support package and no artifact, and the step's loss, step.loss, or null
// while its flows have not been read (016).
const TwinVersion = "11"

// ObservedAtUnknown is what twin.json says when no read took place, so a null
// observed_at is an explicit statement rather than a missing value (Constitution VI).
const ObservedAtUnknown = "unknown: provisioned from an existing bundle; no read took place"

// RecordFields are the parts of a twin record that vary from twin to twin; NewRecord
// supplies the rest.
type RecordFields struct {
	BundleID   string
	Provenance wire.Provenance
	ObservedAt *string // nil when no read took place
	Source     string  // wire.SourceIntent, wire.SourceBundle or wire.SourceSnapshot
	// SnapshotID is the snapshot the run's bundle was compiled from (018): required on a
	// snapshot twin, refused on a bundle twin, and "" on an intent twin whose run names
	// none, as an earlier build's rebuild did.
	SnapshotID string
	RunID      string
	Version    string // the worker binary's --version
	RecordedAt time.Time
	Nodes      []wire.TwinNode
	Stage      *wire.StageRef // nil unless the server resolved the reference from a stage
	// Rehearsal is nil unless a rehearsal run started the create, as its baseline (015).
	Rehearsal *wire.RehearsalRef
}

// NewRecord builds twin.json's content and refuses a record the contract would not
// accept: a twin created from intent always had a read, so its observed_at is known,
// and a twin provisioned from a bundle never did, so its observed_at is null and the
// note says why. A twin created from a snapshot records the snapshot's stored take as its
// observed_at and names the snapshot; a bundle twin names none, and an intent twin names
// the one its run was given, if any (018). A stage is recorded only on a pinned twin (014),
// since a stage always resolves to an at, and never on a bundle twin, which carries none;
// a snapshot twin may name one, as a snapshot twin stepped to a stage does (019). A rehearsal is recorded only as the rehearsal workflow's run, by its
// id (015). The provenance names the scope and the mapping, as every bundle 5 manifest
// does (017).
func NewRecord(f RecordFields) (wire.TwinRecord, error) {
	switch f.Source {
	case wire.SourceIntent:
		if f.ObservedAt == nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin created from intent must record when the intent was observed")
		}
	case wire.SourceSnapshot:
		if f.ObservedAt == nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin created from a snapshot must record when the snapshot's intent was observed")
		}
		if f.SnapshotID == "" {
			return wire.TwinRecord{}, fmt.Errorf("a twin created from a snapshot must name the snapshot")
		}
	case wire.SourceBundle:
		if f.ObservedAt != nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin provisioned from a bundle had no read, so it cannot record observed_at %q", *f.ObservedAt)
		}
		if f.SnapshotID != "" {
			return wire.TwinRecord{}, fmt.Errorf("a twin provisioned from a bundle had no snapshot, so it cannot record snapshot %s", f.SnapshotID)
		}
		if st := f.Stage; st != nil {
			return wire.TwinRecord{}, fmt.Errorf("a twin provisioned from a bundle cannot record stage %s: a bundle carries no stage", st.Name())
		}
	default:
		return wire.TwinRecord{}, fmt.Errorf("unknown twin source %q", f.Source)
	}
	if f.SnapshotID != "" && !snapshot.IsID(f.SnapshotID) {
		return wire.TwinRecord{}, fmt.Errorf("%q is not a snapshot identity", f.SnapshotID)
	}
	if st := f.Stage; st != nil && f.Provenance.At == "" {
		return wire.TwinRecord{}, fmt.Errorf("a twin created from stage %s must record its at: a stage twin is pinned", st.Name())
	}
	if err := provenanceNamesItsRead(f.Provenance); err != nil {
		return wire.TwinRecord{}, err
	}
	if !bundle.IsID(f.BundleID) {
		return wire.TwinRecord{}, fmt.Errorf("%q is not a bundle identity", f.BundleID)
	}
	if f.RunID == "" {
		return wire.TwinRecord{}, fmt.Errorf("a twin record must name its provisioning run")
	}
	if r := f.Rehearsal; r != nil && (r.WorkflowID != wire.RehearseWorkflowID || r.RunID == "") {
		return wire.TwinRecord{}, fmt.Errorf("a twin record names its rehearsal as a %s run by its id, not %q run %q",
			wire.RehearseWorkflowID, r.WorkflowID, r.RunID)
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
		SnapshotID:    snapshotRef(f.SnapshotID),
		BundleID:      f.BundleID,
		Provenance:    f.Provenance,
		ObservedAt:    f.ObservedAt,
		Source:        f.Source,
		Run:           wire.RunRef{WorkflowID: wire.ProvisionWorkflowID, RunID: f.RunID},
		ProvisionedBy: wire.ProvisionedBy{Version: f.Version},
		RecordedAt:    f.RecordedAt.UTC().Format(time.RFC3339Nano),
		Nodes:         nodes,
		Stage:         f.Stage,
		Rehearsal:     f.Rehearsal,
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
// artifact, and each host's probe, come from the staged manifest, verbatim; containers and
// addresses from deploy;
// how long each node took from readiness and its push; the version from this worker's
// binary. A node deploy reports that the manifest does not name, or a device no push result
// names, is refused: the record would claim a twin the run did not build. A host is pushed
// nothing, so it has no artifact and no push time (016). No
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
	staged := targetOf(m)
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
		if probe, ok := staged.Probes[n.Name]; ok {
			nodes = append(nodes, wire.TwinNode{
				Name:        n.Name,
				Container:   n.Container,
				Image:       n.Image,
				Probe:       probe,
				MgmtIPv4:    n.MgmtIPv4,
				ReadyAfterS: readyAfter[n.Name],
			})
			continue
		}
		ref, ok := staged.PSP[n.Name]
		if !ok {
			return failed("containerlab reports node %s, which the staged manifest does not name", n.Name)
		}
		artifact, ok := staged.Artifacts[n.Name]
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
			PSP:         &ref,
			MgmtIPv4:    n.MgmtIPv4,
			ReadyAfterS: readyAfter[n.Name],
			Artifact:    artifact,
			PushedInS:   took,
		})
	}

	rec, err := NewRecord(RecordFields{
		BundleID:   in.BundleID,
		Provenance: recordProvenance(m.Provenance),
		ObservedAt: in.ObservedAt,
		Source:     in.Source,
		SnapshotID: in.SnapshotID,
		RunID:      in.RunID,
		Version:    a.Version,
		RecordedAt: time.Now(),
		Nodes:      nodes,
		Stage:      in.Stage,
		Rehearsal:  in.Rehearsal,
	})
	if err != nil {
		return failed("%v", err)
	}
	if err := WriteRecord(path, rec); err != nil {
		return failed("%v", err)
	}
	return wire.RecordResult{Path: path, Record: rec}, nil
}

// ReadRecord reads twin.json. A record of version 5 or earlier has no stage key and reads
// with Stage nil; the waypoint block versions 3 to 5 carry, M10's pinned reference, is not
// read, and a record that names one reads with Superseded set, so twin step can say why it
// refuses it (014, research R-11). A version 3 or earlier one has no state, step or holds,
// and reads with State "" (shown as ready), Step nil and every Holds nil (shown as the
// record's bundle_id); a version 4 one's step has no wait and reads with Step.Wait nil, as
// a version 5, 6 or 7 one's does while its wait has not run. A record of version 6 or
// earlier has no rehearsal key and reads with Rehearsal nil, as a hand twin's 7 does (015).
// A record of 8 or earlier has no snapshot key, at the top level or on a step's sides, and
// reads with SnapshotID nil and each side's empty (018). A record of 10 or earlier has no
// host and no step.loss, and its step reads with Loss nil, as an 11's does while its flows
// have not been read (016).
func ReadRecord(path string) (wire.TwinRecord, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return wire.TwinRecord{}, err
	}
	var rec wire.TwinRecord
	if err := json.Unmarshal(b, &rec); err != nil {
		return wire.TwinRecord{}, fmt.Errorf("reading %s: %w", path, err)
	}
	if rec.Stage == nil {
		var old struct {
			Waypoint *struct{} `json:"waypoint"`
		}
		rec.Superseded = json.Unmarshal(b, &old) == nil && old.Waypoint != nil
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
// its manifest says of provenance, packages and artifacts, and of each host's probe (016).
// A device is named in PSP and a host in Probes, never both.
type StagedTarget struct {
	BundleID   string
	Provenance wire.Provenance
	PSP        map[string]wire.PSPRef
	Artifacts  map[string]*wire.TwinArtifact
	Probes     map[string]*wire.TwinProbe
}

// names says whether the target names node as a device or as a host.
func (t *StagedTarget) names(node string) bool {
	_, device := t.PSP[node]
	_, host := t.Probes[node]
	return device || host
}

// targetOf is what manifest m says of each node, as a StagedTarget with no identity: a
// device's package and artifact, a host's probe (016).
func targetOf(m compiler.Manifest) *StagedTarget {
	t := &StagedTarget{Provenance: recordProvenance(m.Provenance), PSP: map[string]wire.PSPRef{},
		Artifacts: map[string]*wire.TwinArtifact{}, Probes: map[string]*wire.TwinProbe{}}
	for _, n := range m.Nodes {
		if p := n.Probe; p != nil {
			// A host has no support package: containerlab configures it from its topology
			// node's exec lines, and nothing is pushed to it.
			t.Probes[n.Name] = &wire.TwinProbe{Name: p.Name, Endpoint: p.Endpoint, Format: p.Format,
				Package: wire.PSPRef{ID: p.Package.ID, Source: p.Package.Source}}
			continue
		}
		if n.PSP != nil {
			t.PSP[n.Name] = wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}
		}
		if a := n.Artifact; a != nil {
			t.Artifacts[n.Name] = &wire.TwinArtifact{Name: a.Name, ContentType: a.ContentType, Checksum: a.Checksum, Size: a.Size}
		}
	}
	return t
}

// NewStepRecord builds the record a step leaves (contracts/twin.schema.json
// version 11) from the record the step started from, and refuses what the contract would
// not accept, or what would claim more than the step did:
//
//   - a previous record that is not the step's from side (another bundle or stage), or
//     is diverged, which no step starts from;
//   - a diverged step from a record of 7 or earlier, whose provenance it would keep with
//     no scope and no mapping (017);
//   - a phase given to a stepped or unchanged step, or none, or another, to a diverged one
//     (flows among them, from 016);
//   - a stepped or unchanged step whose staged target is absent, hashes to another
//     identity than its to side, or carries another at; or whose push plan holds a push
//     that did not land; or whose lab runs a node the target does not name, or lacks one
//     it does;
//   - a node of the previous record holding a bundle that is neither side.
//
// After a stepped or unchanged step the top level is the target's, its snapshot included
// (none when the to side names none), and every node holds it: a pushed node landed its
// bundle, and a node the step left alone runs what both bundles give it. After a diverged step the top level stays the previous record's; a
// node whose push landed holds the target, one containerlab restarted, recreated or
// created that no push reached holds nothing (null) and runs its baseline, and
// every other node holds what it held, but a host containerlab created or recreated, which
// holds the target, since its configuration is its topology node's and no push reaches it
// (016). run, provisioned_by and rehearsal stay the
// create's. The step's wait and loss are null: the record is written before the wait, which
// VerifyTwin then writes into it, and before the flows are read, which ReadFlows writes.
func NewStepRecord(prev wire.TwinRecord, f StepFields) (wire.TwinRecord, error) {
	if !bundle.IsID(f.From.BundleID) || !bundle.IsID(f.To.BundleID) {
		return wire.TwinRecord{}, fmt.Errorf("a step is between two bundle identities, not %q and %q", f.From.BundleID, f.To.BundleID)
	}
	for _, id := range []string{f.From.SnapshotID, f.To.SnapshotID} {
		if id != "" && !snapshot.IsID(id) {
			return wire.TwinRecord{}, fmt.Errorf("%q is not a snapshot identity", id)
		}
	}
	if prev.BundleID != f.From.BundleID {
		return wire.TwinRecord{}, fmt.Errorf("the record names bundle %s, not bundle %s the step started from", prev.BundleID, f.From.BundleID)
	}
	if !SameStage(prev.Stage, f.From.Stage) {
		return wire.TwinRecord{}, fmt.Errorf("the record names stage %s, not stage %s the step started from",
			prev.Stage.Name(), f.From.Stage.Name())
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
		case findings.StepFlows, findings.StepReconcile, findings.StepReadiness, findings.StepPush, findings.StepRecord:
		default:
			return wire.TwinRecord{}, fmt.Errorf("a diverged step names the phase it stopped at, one of flows, reconcile, readiness, push or record, not %q", f.Phase)
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
		rec.SnapshotID = snapshotRef(f.To.SnapshotID)
		rec.BundleID = f.To.BundleID
		rec.Provenance = f.Staged.Provenance
		rec.ObservedAt = &observed
		rec.ObservedAtNote = ""
		rec.Stage = f.To.Stage
		rec.State = wire.StateReady
	}
	// A diverged step keeps the previous record's provenance, which twin.json 8 cannot hold
	// when the previous record is a 7 or earlier, written with no scope and no mapping, or
	// an 8 edited by hand to name a scope that is not tag:<name> or a mapping 8 cannot hold
	// (017). twin step refuses each before any run, so only a record that changed under the
	// run reaches here.
	if err := provenanceNamesItsRead(rec.Provenance); err != nil {
		return wire.TwinRecord{}, fmt.Errorf("the step's record keeps the provenance of twin.json %s: %w", prev.TwinVersion, err)
	}
	rec.Nodes = stepNodes(prev, f, moved, outcome)
	rec.Step = stepBlock(f, ended.Sub(started))
	return rec, nil
}

// snapshotRef is a record's snapshot_id for id: nil, written null, when id is "" (018).
func snapshotRef(id string) *string {
	if id == "" {
		return nil
	}
	return &id
}

// provenanceNamesItsRead refuses a provenance twin.json 8 cannot hold (017): one naming no
// scope or a scope not tag:<name>, or a mapping with a field left empty or a reader's name
// not of its form, as validation refuses such an envelope (ctm.ValidScope,
// ctm.ValidReader).
func provenanceNamesItsRead(p wire.Provenance) error {
	if m := p.Mapping; !ctm.ValidScope(p.Scope) || !ctm.ValidReader(m.Reader) || m.Model == "" || m.Version == "" {
		return fmt.Errorf("a twin record names the scope its read was made under, tag:<name>, and the mapping that read it, "+
			"not scope %q and mapping %q, %q, %q", p.Scope, m.Reader, m.Model, m.Version)
	}
	return nil
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
		if !f.Staged.names(n.Name) {
			return fmt.Errorf("containerlab reports node %s, which the target bundle %s does not name", n.Name, f.To.BundleID)
		}
		running[n.Name] = true
	}
	named := append(slices.Collect(maps.Keys(f.Staged.PSP)), slices.Collect(maps.Keys(f.Staged.Probes))...)
	slices.Sort(named)
	for _, name := range named {
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
			Probe: was.Probe, PSP: was.PSP, Artifact: was.Artifact, ReadyAfterS: was.ReadyAfterS, PushedInS: was.PushedInS}
		if s, ok := ready[lab.Name]; ok {
			n.ReadyAfterS = s
		}
		target := func() {
			if f.Staged == nil {
				return
			}
			if probe, ok := f.Staged.Probes[lab.Name]; ok {
				n.Probe, n.PSP, n.Artifact = probe, nil, nil
				return
			}
			if ref, ok := f.Staged.PSP[lab.Name]; ok {
				n.PSP = &ref
			}
			if a := f.Staged.Artifacts[lab.Name]; a != nil {
				n.Artifact = a
			}
		}
		p := pushes[lab.Name]
		host := was.Probe != nil || (f.Staged != nil && f.Staged.Probes[lab.Name] != nil)
		made := slices.Contains(f.Plan.Added, lab.Name) || slices.Contains(f.Plan.Recreated, lab.Name)
		switch {
		case p.Outcome == wire.PushLanded || moved:
			to := f.To.BundleID
			n.Holds = &to
			target()
			if p.Outcome == wire.PushLanded && p.TookS != nil {
				n.PushedInS = *p.TookS
			}
		case host && made && baseline[lab.Name] && f.Staged != nil:
			// A host containerlab created or recreated runs the staged topology's
			// configuration, which is all a host has: no push reaches it (016).
			staged := f.Staged.BundleID
			n.Holds = &staged
			n.PushedInS = 0
			target()
		case host && !made:
			// A host restarted, or left as it was, runs its topology node's configuration,
			// which a step that changed it would have recreated: what it held.
			from := f.From.BundleID
			n.Holds = &from
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

// SameStage says whether two records name the same stage, nil included.
func SameStage(a, b *wire.StageRef) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}
