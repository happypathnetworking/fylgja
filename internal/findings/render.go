package findings

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
)

// Operation names the command that produced a document.
const (
	OpIntentRead    = "intent.read"
	OpCompile       = "twin.compile"
	OpSchemaCheck   = "schema.check"
	OpPSPValidate   = "psp.validate"
	OpTwinCreate    = "twin.create"
	OpTwinProvision = "twin.provision"
	OpTwinDestroy   = "twin.destroy"
	OpTwinShow      = "twin.show"

	// M10: a series listed and planned, with no lab.
	OpWaypointList = "waypoint.list"
	OpWaypointPlan = "waypoint.plan"

	// M11: a waypoint twin stepped to another waypoint of its series, and its dry run.
	OpTwinStep = "twin.step"

	// M12: the twin read and verified against intent, with no run.
	OpTwinVerify = "twin.verify"
)

// Status maps onto the process exit code.
type Status string

const (
	StatusOK       Status = "ok"       // exit 0
	StatusRejected Status = "rejected" // exit 1: refused before the host was touched
	StatusError    Status = "error"    // exit 2
	StatusFailed   Status = "failed"   // exit 3: failed after the host was touched; cleanup completed
	StatusUnclean  Status = "unclean"  // exit 4: something remains on the host

	// M11.
	StatusDiverged Status = "diverged" // exit 4: a step failed or was cancelled after the host was touched; the twin is up and diverged

	// M12.
	StatusNonconforming Status = "nonconforming" // exit 5: every node was read and an assertion or a record claim failed; nothing acts on it
)

// Exit codes, per contracts/cli.md.
const (
	ExitOK       = 0
	ExitRejected = 1
	ExitError    = 2
	ExitFailed   = 3
	ExitUnclean  = 4

	ExitNonconforming = 5
)

// ExitCode returns the process exit code for a status.
func (s Status) ExitCode() int {
	switch s {
	case StatusRejected:
		return ExitRejected
	case StatusError:
		return ExitError
	case StatusFailed:
		return ExitFailed
	case StatusUnclean, StatusDiverged:
		return ExitUnclean
	case StatusNonconforming:
		return ExitNonconforming
	default:
		return ExitOK
	}
}

// Subject records what was operated on.
type Subject struct {
	Branch string   `json:"branch,omitempty"`
	At     string   `json:"at,omitempty"`
	CTM    string   `json:"ctm,omitempty"`
	Files  []string `json:"files,omitempty"`
	Out    string   `json:"out,omitempty"`
	// Bundle is the directory given to twin provision, as given.
	Bundle string `json:"bundle,omitempty"`
	// RunID is the Temporal run the document reports on, once one was started or
	// attached to.
	RunID string `json:"run_id,omitempty"`
	// Waypoint is --waypoint as given, <series>/<sequence> (M10). Branch and At then
	// carry the reference it resolved to, once it resolved.
	Waypoint string `json:"waypoint,omitempty"`
}

// WaypointBlock is the reference one waypoint resolved to (M10): the waypoint block of
// twin create, its dry run and intent read given --waypoint
// ($defs/resolved). At is verbatim:
// what was written on the waypoint, or what Infrahub returned as its branch's write time.
type WaypointBlock struct {
	Series      string `json:"series"`
	Sequence    int    `json:"sequence"`
	Branch      string `json:"branch"`
	At          string `json:"at"`
	AtSource    string `json:"at_source"`
	Description string `json:"description"`
}

// Line is the one line printed wherever a reference is resolved (contracts/cli.md):
//
//	waypoint demo/2: branch change-1 at 2026-09-28T15:20:44.000000+00:00 (written), "after the first cut-over"
//
// The description is the operator's, quoted, and "" when none was written.
func (w WaypointBlock) Line() string {
	return fmt.Sprintf("waypoint %s/%d: %s", w.Series, w.Sequence, w.Resolution())
}

// Resolution is the line's part after the reference, which waypoint plan prints under its
// series heading: branch change-1 at 2026-09-28T15:20:44.000000+00:00 (written), "…".
func (w WaypointBlock) Resolution() string {
	return fmt.Sprintf("branch %s at %s (%s), %q", w.Branch, w.At, w.AtSource, w.Description)
}

// WaypointsBlock is waypoint list's block (M10; waypoints.schema.json, $defs/list): every
// waypoint Infrahub holds, or the one series asked for, sorted by series then sequence,
// each with the reference it resolves to; and the waypoint the host's record names.
type WaypointsBlock struct {
	// Series is the --series filter, or nil when every series was listed.
	Series    *string       `json:"series"`
	Waypoints []WaypointRow `json:"waypoints"`
	// Record is what twin.json names, as recorded, when it is readable and names a
	// waypoint; nil otherwise. Written as an explicit null, as the contract requires.
	Record *WaypointRecord `json:"record"`
}

// MarshalJSON writes no rows as [] rather than null: the contract requires the list.
func (b WaypointsBlock) MarshalJSON() ([]byte, error) {
	type plain WaypointsBlock
	if b.Waypoints == nil {
		b.Waypoints = []WaypointRow{}
	}
	return json.Marshal(plain(b))
}

// WaypointRow is one listed waypoint: the reference it resolves to now, with no refusal
// (a listing resolves nothing for a run), and whether it is the one the host's twin was
// built from.
type WaypointRow struct {
	WaypointBlock
	Twin bool `json:"twin"`
}

// WaypointRecord is the waypoint a version 3 twin.json names, with the reference the record
// holds: its provenance's branch and at, which the row's may since differ from.
type WaypointRecord struct {
	Series   string `json:"series"`
	Sequence int    `json:"sequence"`
	Branch   string `json:"branch"`
	At       string `json:"at"`
	AtSource string `json:"at_source"`
	// State is a version 4 record's state, ready or diverged, and "" for a version 3 one,
	// which has none (waypoints.schema.json).
	State string `json:"state,omitempty"`
	// Towards is the target of the diverged step, when State is diverged; nil otherwise.
	Towards *WaypointTowards `json:"towards"`
}

// MarshalJSON writes state and towards for a version 4 record alone, towards as an explicit
// null when the record is not diverged; a version 3 record's block is M10's, key for key.
func (r WaypointRecord) MarshalJSON() ([]byte, error) {
	type plain WaypointRecord
	if r.State != "" {
		return json.Marshal(plain(r))
	}
	type m10 struct {
		Series   string `json:"series"`
		Sequence int    `json:"sequence"`
		Branch   string `json:"branch"`
		At       string `json:"at"`
		AtSource string `json:"at_source"`
	}
	return json.Marshal(m10{Series: r.Series, Sequence: r.Sequence, Branch: r.Branch, At: r.At, AtSource: r.AtSource})
}

// WaypointTowards names the waypoint a diverged step was going to.
type WaypointTowards struct {
	Series   string `json:"series"`
	Sequence int    `json:"sequence"`
}

// PlanBlock is waypoint plan's block (M10; waypoints.schema.json, $defs/plan): each waypoint
// of the series in sequence order, as far as it got, and the step between each consecutive
// pair.
type PlanBlock struct {
	Series    string         `json:"series"`
	Waypoints []PlanWaypoint `json:"waypoints"`
	// Steps are internal/step's pairs as they marshal themselves, one fewer than the
	// waypoints, in order. Raw, because the step's shape is the step package's to render,
	// and this package imports none of Fylgja's.
	Steps []json.RawMessage `json:"steps"`
}

// MarshalJSON writes no steps as [] rather than null: a series of one waypoint has none,
// and the contract requires the list.
func (b PlanBlock) MarshalJSON() ([]byte, error) {
	type plain PlanBlock
	if b.Waypoints == nil {
		b.Waypoints = []PlanWaypoint{}
	}
	if b.Steps == nil {
		b.Steps = []json.RawMessage{}
	}
	return json.Marshal(plain(b))
}

// PlanWaypoint is one waypoint of a plan. Branch, At and AtSource are set once it resolved;
// BundleID once it compiled; Read once its read did. A waypoint refused at resolution
// carries its reference, description and findings alone.
type PlanWaypoint struct {
	Series      string      `json:"series"`
	Sequence    int         `json:"sequence"`
	Branch      string      `json:"branch,omitempty"`
	At          string      `json:"at,omitempty"`
	AtSource    string      `json:"at_source,omitempty"`
	Description string      `json:"description"`
	BundleID    *string     `json:"bundle_id"`
	Read        *ReadCounts `json:"read"`
	// Findings are this waypoint's, each also in the document's own list.
	Findings List `json:"findings"`
}

// MarshalJSON writes no findings as [] rather than null: the contract requires the list.
func (w PlanWaypoint) MarshalJSON() ([]byte, error) {
	type plain PlanWaypoint
	if w.Findings == nil {
		w.Findings = List{}
	}
	return json.Marshal(plain(w))
}

// ReadCounts is intent read's summary line as numbers: what a read holds, and what the
// packages' profiles make of it.
type ReadCounts struct {
	Devices       int `json:"devices"`
	Interfaces    int `json:"interfaces"`
	Links         int `json:"links"`
	Artifacts     int `json:"artifacts"`
	LossyMappings int `json:"lossy_mappings"`
	SharedPorts   int `json:"shared_ports"`
}

// GenericKinds names the concrete kinds implementing one generic. The first
// iteration reported only a count; naming them is what lets `schema check` show an
// operator which of their kinds satisfies the contract.
type GenericKinds struct {
	Generic string   `json:"generic"`
	Kinds   []string `json:"kinds"`
}

// Verified is the success detail of a schema check: what was verified.
type Verified struct {
	ContractVersion string         `json:"contract_version,omitempty"`
	Generics        []GenericKinds `json:"generics,omitempty"`
	// Waypoints is whether the default branch carries the waypoint kind,
	// whatever branch was checked: information beside the conformance answer, never a
	// finding.
	Waypoints *WaypointsVerified `json:"waypoints,omitempty"`
}

// WaypointsVerified is the waypoint kind as the default branch's schema holds it: present
// with every attribute this build reads, or absent, or lacking the attributes Missing names
// (verified.waypoints).
type WaypointsVerified struct {
	Kind    string   `json:"kind"`
	Present bool     `json:"present"`
	Missing []string `json:"missing"`
	// File is the schema file that loads the kind.
	File string `json:"file"`
}

// MarshalJSON writes no missing attribute as [] rather than null: the contract requires
// the list.
func (w WaypointsVerified) MarshalJSON() ([]byte, error) {
	type plain WaypointsVerified
	if w.Missing == nil {
		w.Missing = []string{}
	}
	return json.Marshal(plain(w))
}

// TwinBlock is the success detail of twin create and twin provision: the twin that was
// built, mirroring twin.json's nodes.
type TwinBlock struct {
	Lab   string `json:"lab"`
	Dir   string `json:"dir"`
	RunID string `json:"run_id"`
	// ObservedAt is null when no read took place (twin provision), as in twin.json.
	ObservedAt *string    `json:"observed_at"`
	Nodes      []TwinNode `json:"nodes"`
}

// TwinNode is one ready node. It is a document type of its own, not wire.TwinNode:
// twin.json records four fields of the artifact, and the document projects them to the
// two an operator reads.
type TwinNode struct {
	Name        string  `json:"name"`
	MgmtIPv4    string  `json:"mgmt_ipv4"`
	ReadyAfterS float64 `json:"ready_after_s"`
	// Artifact is what was pushed to this node, by name and checksum (M5). The
	// content type and the size stay in twin.json; no field carries content.
	Artifact *ShowArtifact `json:"artifact,omitempty"`
	// PushedInS is how long this node's push took (M5).
	PushedInS float64 `json:"pushed_in_s,omitempty"`
}

// CleanupBlock says what teardown and unstage did: after a failed or cancelled create
// or provision, and for every destroy. Teardown and Unstage are done, nothing, failed or
// skipped.
type CleanupBlock struct {
	Teardown  string   `json:"teardown"`
	Unstage   string   `json:"unstage"`
	Removed   []string `json:"removed,omitempty"`
	Remaining []string `json:"remaining"`
}

// MarshalJSON writes an empty Remaining as [] rather than null: the contract requires
// the list, and "nothing remains" is the common case, not a missing answer.
func (c CleanupBlock) MarshalJSON() ([]byte, error) {
	type plain CleanupBlock
	if c.Remaining == nil {
		c.Remaining = []string{}
	}
	return json.Marshal(plain(c))
}

// Dry-run verdicts.
const (
	VerdictClear   = "clear"
	VerdictRefused = "refused"
)

// DryRunBlock is what a real run would do, reported by --dry-run.
type DryRunBlock struct {
	Nodes       []DryRunNode `json:"nodes"`
	MemorySumMB int          `json:"memory_sum_mb"`
	// HostBudgetMB is null when FYLGJA_HOST_MEMORY_MB is unset.
	HostBudgetMB *int       `json:"host_budget_mb"`
	Host         DryRunHost `json:"host"`
	Verdict      string     `json:"verdict"`
	// LossyMappings and SharedPorts count what the bundle's fidelity.lossy records (M6),
	// so the operator sees a lossy twin before creating it. Always present: 0 is
	// an answer, and a bundle that records nothing lossy says so by those zeros.
	LossyMappings int `json:"lossy_mappings"`
	SharedPorts   int `json:"shared_ports"`
	// Follow is whether the twin would follow its branch (M4).
	Follow *DryRunFollow `json:"follow,omitempty"`
}

// DryRunNode is one node a real run would deploy.
type DryRunNode struct {
	Name     string `json:"name"`
	Image    string `json:"image"`
	PSP      string `json:"psp"`
	MemoryMB int    `json:"memory_mb"`
	// Artifact is what would be pushed to this node, as the bundle's manifest names it
	// (M5). Every M5 bundle carries one per node, so the contract requires it
	// here; it is a pointer only so that a document built from an M2-era bundle, which
	// twin provision refuses as bundle.version.unsupported, marshals without it.
	Artifact *DryRunArtifact `json:"artifact,omitempty"`
}

// DryRunArtifact names what would be pushed: never a byte of it.
type DryRunArtifact struct {
	Name        string `json:"name"`
	ContentType string `json:"content_type"`
	Checksum    string `json:"checksum"`
	Size        int    `json:"size"`
}

// DryRunHost is what the host check saw.
type DryRunHost struct {
	LabPresent     bool `json:"lab_present"`
	TwinDirPresent bool `json:"twin_dir_present"`
}

// Following states on twin create's following block.
const (
	FollowingStarted    = "started"     // the run ended ready and schedule fylgja-follow was created
	FollowingNotStarted = "not_started" // the run ended ready but the schedule could not be created
)

// FollowingBlock is the following a twin create began, or could not begin, and the
// following a twin destroy stopped. Create sets State;
// destroy sets Stopped.
type FollowingBlock struct {
	Branch     string `json:"branch"`
	IntervalS  int    `json:"interval_s,omitempty"`
	ScheduleID string `json:"schedule_id,omitempty"`
	State      string `json:"state,omitempty"`
	Stopped    bool   `json:"stopped,omitempty"`
}

// Reasons a dry run reports a twin would not follow.
const (
	FollowReasonPinned   = "pinned"    // --at given
	FollowReasonNoFollow = "no_follow" // --no-follow given
	FollowReasonBundle   = "bundle"    // twin provision: a bundle never follows
	FollowReasonWaypoint = "waypoint"  // --waypoint given: a waypoint is pinned (M10)
)

// DryRunFollow is whether the twin a real run would build follows its branch, and how
// often it would be checked, or why it would not.
type DryRunFollow struct {
	Enabled   bool   `json:"enabled"`
	IntervalS int    `json:"interval_s,omitempty"`
	Reason    string `json:"reason,omitempty"`
}

// Kinds of twin twin show reports.
const (
	ShowKindNone       = "none"
	ShowKindPinned     = "pinned"
	ShowKindFrozen     = "frozen"
	ShowKindFromBundle = "from_bundle"
	ShowKindFollowing  = "following"

	// M11: a twin whose last step failed or was cancelled after the host was touched.
	ShowKindDiverged = "diverged"
)

// Whether twin show reached the workflow service.
const (
	ShowServiceOK          = "ok"
	ShowServiceUnreachable = "unreachable"
)

// ShowBlock is what twin show says about the twin: the host, the record, the kind, the
// following and the runs in flight, from containerlab, twin.json and the workflow service.
// One struct renders both the text and the
// JSON, so the two cannot disagree.
type ShowBlock struct {
	Host      ShowHost       `json:"host"`
	Record    *ShowRecord    `json:"record,omitempty"`
	Kind      string         `json:"kind"`
	Following *ShowFollowing `json:"following,omitempty"`
	// LastCheck is the check that stopped following after a failed rebuild, reported while
	// no Schedule exists and no run has started since it closed.
	LastCheck *ShowCheck `json:"last_check,omitempty"`
	InFlight  []ShowRun  `json:"in_flight"`
	Service   string     `json:"service"`
	Notes     []string   `json:"notes"`
}

// MarshalJSON writes empty InFlight and Notes as [] rather than null: the contract
// requires both lists.
func (b ShowBlock) MarshalJSON() ([]byte, error) {
	type plain ShowBlock
	if b.InFlight == nil {
		b.InFlight = []ShowRun{}
	}
	if b.Notes == nil {
		b.Notes = []string{}
	}
	return json.Marshal(plain(b))
}

// UnmarshalJSON reads an empty in_flight or notes as none: the block is built with none
// where nothing is in flight or noted, never with an empty list, and MarshalJSON writes the
// two alike, so a decoded block is the one that was written.
func (b *ShowBlock) UnmarshalJSON(data []byte) error {
	type plain ShowBlock
	var p plain
	if err := json.Unmarshal(data, &p); err != nil {
		return err
	}
	if len(p.InFlight) == 0 {
		p.InFlight = nil
	}
	if len(p.Notes) == 0 {
		p.Notes = nil
	}
	*b = ShowBlock(p)
	return nil
}

// ShowHost is what containerlab and the state root hold, and M3's phrase for it.
type ShowHost struct {
	LabPresent     bool       `json:"lab_present"`
	TwinDirPresent bool       `json:"twin_dir_present"`
	Nodes          []ShowNode `json:"nodes"`
	Phrase         string     `json:"phrase"`
}

// MarshalJSON writes no nodes as [] rather than null.
func (h ShowHost) MarshalJSON() ([]byte, error) {
	type plain ShowHost
	if h.Nodes == nil {
		h.Nodes = []ShowNode{}
	}
	return json.Marshal(plain(h))
}

// ShowNode is one container as containerlab reports it.
type ShowNode struct {
	Name      string `json:"name"`
	Container string `json:"container"`
	State     string `json:"state"`
	MgmtIPv4  string `json:"mgmt_ipv4"`
	// Artifact is what twin.json records for this node (M5), or null for a node the
	// record does not name — an orphan's, or one recorded before M5. Written as an
	// explicit null, not omitted, as the document's other nullable fields are
	// (contracts/cli.md: "{name, checksum} or null").
	Artifact *ShowArtifact `json:"artifact"`
	// PSP is the support package the node was provisioned with, as twin.json records it
	// (nodes[].psp.id), or null for a node the record does not name. With two
	// platforms in one twin, the node line is where an operator reads which is which.
	// Written as an explicit null for the same reason Artifact is, and twin.json gains no
	// key for it.
	PSP *string `json:"psp"`
}

// ShowArtifact names an artifact by identity alone: the name it was pushed under and the
// checksum that says which bytes those were. No content, ever.
type ShowArtifact struct {
	Name     string `json:"name"`
	Checksum string `json:"checksum"`
}

// ShowRecord is twin.json, when it is present and readable.
type ShowRecord struct {
	Branch          string `json:"branch"`
	At              string `json:"at,omitempty"`
	BundleID        string `json:"bundle_id"`
	SchemaHash      string `json:"schema_hash"`
	ContractVersion string `json:"contract_version"`
	// ObservedAt is null when no read took place, as in twin.json.
	ObservedAt     *string `json:"observed_at"`
	ObservedAtNote string  `json:"observed_at_note,omitempty"`
	Source         string  `json:"source"`
	Run            ShowRef `json:"run"`
	WorkerVersion  string  `json:"worker_version"`
	RecordedAt     string  `json:"recorded_at"`
	Nodes          int     `json:"nodes"`
	// Waypoint is the waypoint a version 3 record names (M10), absent when it names none
	// and for an earlier record.
	Waypoint *ShowWaypoint `json:"waypoint,omitempty"`
	// State is a version 4 record's state, ready or diverged; absent for an earlier record,
	// which has none.
	State string `json:"state,omitempty"`
	// Step is a version 4 record's last step as twin show shows it; absent when the record
	// has none.
	Step *ShowStep `json:"step,omitempty"`
}

// ShowStep is twin.json 4's step block as far as twin show shows it:
// the two sides, the run, the phase a
// diverged step stopped at, the nodes containerlab restarted, recreated or created, each
// push's outcome, the timings, and when it started and ended. No content.
type ShowStep struct {
	Outcome string        `json:"outcome"`
	From    StepSideBlock `json:"from"`
	To      StepSideBlock `json:"to"`
	Run     ShowRef       `json:"run"`
	// Phase is the phase a diverged step stopped at; absent otherwise.
	Phase string `json:"phase,omitempty"`
	// Restarted is the reconcile's restarted, recreated and added nodes, sorted.
	Restarted []string          `json:"restarted"`
	Pushed    []StepPushedEntry `json:"pushed"`
	Timings   *StepTimingsBlock `json:"timings,omitempty"`
	StartedAt string            `json:"started_at"`
	EndedAt   string            `json:"ended_at"`
	// Wait is the step's wait as twin show shows it: nil while it has not run. WaitKnown says
	// the record is version 5 or later, whose
	// step block carries the wait: the key is then written, as null when Wait is nil, and left
	// out for a version 4 record, which is shown as M11 shows it.
	Wait      *ShowWait `json:"wait,omitempty"`
	WaitKnown bool      `json:"-"`
}

// MarshalJSON writes no restarted node and no push as [] rather than null: the contract
// requires both lists. A version 5 record's wait is written as null until it has run.
func (s ShowStep) MarshalJSON() ([]byte, error) {
	type plain ShowStep
	if s.Restarted == nil {
		s.Restarted = []string{}
	}
	if s.Pushed == nil {
		s.Pushed = []StepPushedEntry{}
	}
	if !s.WaitKnown {
		return json.Marshal(plain(s))
	}
	// The outer key is shallower than the embedded one, so it is the one written.
	return json.Marshal(struct {
		plain
		Wait *ShowWait `json:"wait"`
	}{plain(s), s.Wait})
}

// UnmarshalJSON reads the fields as they are, and sets WaitKnown when the object carries a
// wait key, null included: the key is how a version 5 record's step was told from a version 4
// one when it was written, so a document decoded from an API frame writes it again as it came
// (M13).
func (s *ShowStep) UnmarshalJSON(b []byte) error {
	type plain ShowStep
	var p plain
	if err := json.Unmarshal(b, &p); err != nil {
		return err
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(b, &keys); err != nil {
		return err
	}
	_, p.WaitKnown = keys["wait"]
	*s = ShowStep(p)
	return nil
}

// ShowWait is twin.json 5's step.wait as twin show shows it (contracts/
// show.schema.json): how it ended, the budget, the reads made, the seconds from the record to
// the read that settled or to its end, and what still failed by identifier and object. No
// message: the record block names, it does not report.
type ShowWait struct {
	Outcome string            `json:"outcome"`
	BudgetS int               `json:"budget_s"`
	Reads   int               `json:"reads"`
	AfterS  float64           `json:"after_s"`
	Failing []ShowWaitFailing `json:"failing"`
}

// MarshalJSON writes nothing failing as [] rather than null: the contract requires the list.
func (w ShowWait) MarshalJSON() ([]byte, error) {
	type plain ShowWait
	if w.Failing == nil {
		w.Failing = []ShowWaitFailing{}
	}
	return json.Marshal(plain(w))
}

// ShowWaitFailing is one assertion still failing at the wait's last read, or an unread node's
// operation.failed, by identifier and object.
type ShowWaitFailing struct {
	Rule   string `json:"rule"`
	Object string `json:"object"`
}

// ShowWaypoint is the waypoint a twin was created from, as twin.json records it. The at
// is the record's own.
type ShowWaypoint struct {
	Series      string `json:"series"`
	Sequence    int    `json:"sequence"`
	Description string `json:"description"`
	AtSource    string `json:"at_source"`
}

// ShowRef is a run's identity.
type ShowRef struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
}

// ShowFollowing is Schedule fylgja-follow, whatever the twin.
type ShowFollowing struct {
	Branch      string     `json:"branch"`
	IntervalS   int        `json:"interval_s"`
	ScheduleID  string     `json:"schedule_id"`
	NextCheckAt string     `json:"next_check_at,omitempty"`
	LastCheck   *ShowCheck `json:"last_check,omitempty"`
}

// ShowCheck is one closed check and what it found.
type ShowCheck struct {
	WorkflowID   string        `json:"workflow_id"`
	RunID        string        `json:"run_id"`
	ScheduledAt  string        `json:"scheduled_at"`
	ClosedAt     string        `json:"closed_at,omitempty"`
	Outcome      string        `json:"outcome"`
	Step         string        `json:"step,omitempty"`
	TwinBundleID string        `json:"twin_bundle_id,omitempty"`
	BundleID     string        `json:"bundle_id,omitempty"`
	Findings     List          `json:"findings"`
	Cleanup      *CleanupBlock `json:"cleanup,omitempty"`
}

// MarshalJSON writes no findings as [] rather than null: the contract requires the list.
func (c ShowCheck) MarshalJSON() ([]byte, error) {
	type plain ShowCheck
	if c.Findings == nil {
		c.Findings = List{}
	}
	return json.Marshal(plain(c))
}

// ShowRun is a run in flight and the step its history has reached. A check's child run in
// flight is its Child, which has none of its own.
type ShowRun struct {
	WorkflowID string   `json:"workflow_id"`
	RunID      string   `json:"run_id"`
	Step       string   `json:"step"`
	Child      *ShowRun `json:"child,omitempty"`
}

// Document is the machine-readable result of one operation. M1's operations conform to
// M1's findings contract; M2's twin create, provision and destroy to M2's, which is
// additive, so every M1 document satisfies both. M4's operations — following on create
// and destroy, dry_run.follow, and twin show — conform to M4's, additive again. M5's
// operations — the artifact on a dry run's, a twin's and a shown host's nodes,
// `pushed_in_s`, and the step `push` — conform to M5's, with show.schema.json added as a
// resource under its $id. M10's — subject.waypoint, the waypoint block, record.waypoint in
// the show block, and the waypoints and plan blocks of waypoint list and waypoint plan —
// conform to M10's, with waypoints.schema.json added under its $id as well. Each
// milestone's copy is kept under testdata/contracts/, and the current contract is
// contracts/findings.schema.json. No field of any block carries a byte of artifact content.
type Document struct {
	FindingsVersion string          `json:"findings_version"`
	Operation       string          `json:"operation"`
	Status          Status          `json:"status"`
	Subject         *Subject        `json:"subject,omitempty"`
	BundleID        string          `json:"bundle_id,omitempty"`
	Verified        *Verified       `json:"verified,omitempty"`
	Twin            *TwinBlock      `json:"twin,omitempty"`
	Cleanup         *CleanupBlock   `json:"cleanup,omitempty"`
	DryRun          *DryRunBlock    `json:"dry_run,omitempty"`
	Following       *FollowingBlock `json:"following,omitempty"`
	Show            *ShowBlock      `json:"show,omitempty"`
	// Waypoint is the reference --waypoint resolved to (M10), present once it resolved.
	Waypoint *WaypointBlock `json:"waypoint,omitempty"`
	// Waypoints is waypoint list's block, Plan waypoint plan's (M10).
	Waypoints *WaypointsBlock `json:"waypoints,omitempty"`
	Plan      *PlanBlock      `json:"plan,omitempty"`
	// Step is twin step's block, on the dry run and the run (M11).
	Step *StepBlock `json:"step,omitempty"`
	// Verify is twin verify's block (M12),
	// present once the staged bundle was read and its assertions derived.
	Verify   *VerifyBlock `json:"verify,omitempty"`
	Findings List         `json:"findings"`
}

// NewDocument builds a document, deriving status from the findings unless the caller
// has already determined the operation failed outright.
func NewDocument(op string, subject *Subject, list List) *Document {
	status := StatusOK
	if list.Rejected() {
		status = StatusRejected
	}
	if list == nil {
		list = List{}
	}
	return &Document{
		FindingsVersion: "1",
		Operation:       op,
		Status:          status,
		Subject:         subject,
		Findings:        list,
	}
}

// ErrorDocument builds a document for a usage or system failure: the operation could
// not run at all, as distinct from running and rejecting its input.
func ErrorDocument(op string, subject *Subject, message string) *Document {
	return &Document{
		FindingsVersion: "1",
		Operation:       op,
		Status:          StatusError,
		Subject:         subject,
		Findings:        List{{Severity: Rejection, Rule: RuleOperationFailed, Object: op, Message: message}},
	}
}

// RuleErrorDocument builds an operational-failure document under a named rule, for
// the failures that have their own identifier rather than the catch-all
// operation.failed — at M1, intent.at.precision.
func RuleErrorDocument(op string, subject *Subject, rule, object, message string) *Document {
	return &Document{
		FindingsVersion: "1",
		Operation:       op,
		Status:          StatusError,
		Subject:         subject,
		Findings:        List{{Severity: Rejection, Rule: rule, Object: object, Message: message}},
	}
}

// Render writes a document in the mode --json selects and returns the process exit
// code. JSON goes to stdout and nothing else does; text findings go to stderr, which
// leaves stdout for the success lines (contracts/cli.md). Keeping the selector, the
// two renderings and the exit code in one function is what makes them a contract
// rather than a habit of each command.
func Render(doc *Document, stdout, stderr io.Writer, asJSON bool) int {
	w, write := stderr, (*Document).WriteText
	if asJSON {
		w, write = stdout, (*Document).WriteJSON
	}
	if err := write(doc, w); err != nil {
		_, _ = fmt.Fprintln(stderr, "fylgja:", err)
		return ExitError
	}
	return doc.Status.ExitCode()
}

// WriteJSON emits the document as a single JSON document, deterministically.
func (d *Document) WriteJSON(w io.Writer) error {
	b, err := json.MarshalIndent(d, "", "  ")
	if err != nil {
		return err
	}
	if _, err := w.Write(append(b, '\n')); err != nil {
		return err
	}
	return nil
}

// WriteText emits human-readable findings, one per line, with a summary last.
// Findings are ordered rejections first, then by rule and object, so the most
// consequential problem is not buried. A finding from a provisioning step names the
// step after its rule.
func (d *Document) WriteText(w io.Writer) error {
	for _, line := range d.Findings.TextLines() {
		if _, err := fmt.Fprintln(w, line); err != nil {
			return err
		}
	}
	if list := d.Findings; len(list) > 0 {
		_, err := fmt.Fprintf(w, "%d finding(s): %d rejection, %d warning, %d info\n",
			len(list), list.Count(Rejection), list.Count(Warning), list.Count(Info))
		return err
	}
	return nil
}

// TextLines is each finding as WriteText prints it, in WriteText's order, with no summary:
// the shape waypoint plan also prints under each waypoint's line.
func (l List) TextLines() []string {
	list := make(List, len(l))
	copy(list, l)
	rank := map[Severity]int{Rejection: 0, Warning: 1, Info: 2}
	sort.SliceStable(list, func(i, j int) bool {
		if rank[list[i].Severity] != rank[list[j].Severity] {
			return rank[list[i].Severity] < rank[list[j].Severity]
		}
		if list[i].Rule != list[j].Rule {
			return list[i].Rule < list[j].Rule
		}
		return list[i].Object < list[j].Object
	})
	lines := make([]string, 0, len(list))
	for _, f := range list {
		where := f.Object
		if f.Location != nil {
			where = f.Location.File
			if f.Location.Line > 0 {
				where = fmt.Sprintf("%s:%d", where, f.Location.Line)
			}
			if f.Object != "" {
				where = fmt.Sprintf("%s (%s)", where, f.Object)
			}
		}
		rule := f.Rule
		if f.Step != "" {
			rule = fmt.Sprintf("%s [step %s]", f.Rule, f.Step)
		}
		lines = append(lines, fmt.Sprintf("%s %s %s: %s", f.Severity, rule, where, f.Message))
	}
	return lines
}

// StepBlock is twin step's block (M11): the
// two sides, M10's step between their bundles, containerlab's plan with each touched
// node's package declaration beside what containerlab reported, the push plan and the
// flag; and, once a run closed, what came of it. A dry run's carries no run fields. No
// device diff, artifact or bootstrap line anywhere.
type StepBlock struct {
	From StepSideBlock `json:"from"`
	To   StepSideBlock `json:"to"`
	// Diff is M10's step between the two bundles as internal/step marshals it
	// (waypoints.schema.json, $defs/step).
	Diff         json.RawMessage     `json:"diff"`
	Reconcile    StepReconcileBlock  `json:"reconcile"`
	PushPlan     []StepPushPlanEntry `json:"push_plan"`
	AllowRestart bool                `json:"allow_restart"`
	// StepRunBlock is the run's fields, nil on a dry run and before a run started.
	*StepRunBlock
	// Wait is the step's wait after its record: its budget on the dry run and before the
	// run closed, how it ended once the run
	// closed and the wait ran; nil when the run closed without it.
	Wait *StepWaitBlock `json:"wait,omitempty"`
}

// MarshalJSON writes an empty push plan, and a run's empty pushes and awaited nodes, as []
// rather than null. StepRunBlock has no MarshalJSON of its own on purpose: embedded, it
// would be promoted to this one's alias and marshal the run fields alone.
func (b StepBlock) MarshalJSON() ([]byte, error) {
	type plain StepBlock
	if b.PushPlan == nil {
		b.PushPlan = []StepPushPlanEntry{}
	}
	if r := b.StepRunBlock; r != nil {
		run := *r
		if run.Pushed == nil {
			run.Pushed = []StepPushedEntry{}
		}
		if run.ReadyAfter == nil {
			run.ReadyAfter = []StepReadyAfter{}
		}
		b.StepRunBlock = &run
	}
	return json.Marshal(plain(b))
}

// StepRunBlock is what a step run adds to the block: the run, and once it closed its
// outcome (stepped, unchanged or diverged; absent for a run that ended before the stage),
// the phase a diverged one stopped at, the record's state, every push of the plan with its
// outcome, how long each awaited node took, the timings, and when it started and ended.
type StepRunBlock struct {
	Run        ShowRef           `json:"run"`
	Outcome    string            `json:"outcome,omitempty"`
	Phase      string            `json:"phase,omitempty"`
	State      string            `json:"state,omitempty"`
	Pushed     []StepPushedEntry `json:"pushed"`
	ReadyAfter []StepReadyAfter  `json:"ready_after"`
	Timings    StepTimingsBlock  `json:"timings"`
	StartedAt  string            `json:"started_at,omitempty"`
	EndedAt    string            `json:"ended_at,omitempty"`
}

// StepWaitBlock is the step document's wait (contracts/step.schema.json): the
// budget in seconds alone until the wait has ended, and then its outcome, the reads made, the
// seconds from the record to the read that settled or to its end, and what still failed, by
// identifier, object and message, never content.
type StepWaitBlock struct {
	BudgetS int               `json:"budget_s"`
	Outcome string            `json:"outcome,omitempty"`
	Reads   int               `json:"reads"`
	AfterS  float64           `json:"after_s"`
	Failing []StepWaitFailing `json:"failing"`
}

// MarshalJSON writes the budget alone for a wait that has not ended, and nothing failing as
// [] rather than null once it has.
func (w StepWaitBlock) MarshalJSON() ([]byte, error) {
	if w.Outcome == "" {
		return json.Marshal(struct {
			BudgetS int `json:"budget_s"`
		}{w.BudgetS})
	}
	type plain StepWaitBlock
	if w.Failing == nil {
		w.Failing = []StepWaitFailing{}
	}
	return json.Marshal(plain(w))
}

// StepWaitFailing is one assertion still failing at the wait's last read, or an unread node's
// operation.failed, or the activity's own failure.
type StepWaitFailing struct {
	Rule    string `json:"rule"`
	Object  string `json:"object"`
	Message string `json:"message"`
}

// StepSideBlock is one side of a step: the waypoint, the bundle and the pinned at,
// verbatim, and for the target the branch it resolved to.
type StepSideBlock struct {
	Waypoint *ShowWaypoint `json:"waypoint"`
	BundleID string        `json:"bundle_id"`
	At       string        `json:"at"`
	Branch   string        `json:"branch,omitempty"`
}

// StepReconcileBlock is containerlab's plan (clab deploy --dry-run): the
// nodes added, deleted, recreated and restarted, the links added and endpoints deleted as
// containerlab prints them, and each touched node; with skipped and the apply's time once
// a run reports them.
type StepReconcileBlock struct {
	Added            []string       `json:"added"`
	Deleted          []string       `json:"deleted"`
	Recreated        []string       `json:"recreated"`
	Restarted        []string       `json:"restarted"`
	LinksAdded       []string       `json:"links_added"`
	EndpointsDeleted []string       `json:"endpoints_deleted"`
	Nodes            []StepPlanNode `json:"nodes"`
	Skipped          bool           `json:"skipped,omitempty"`
	TookS            *float64       `json:"took_s,omitempty"`
}

// MarshalJSON writes every empty list as [] rather than null: the contract requires them.
func (b StepReconcileBlock) MarshalJSON() ([]byte, error) {
	type plain StepReconcileBlock
	for _, l := range []*[]string{&b.Added, &b.Deleted, &b.Recreated, &b.Restarted, &b.LinksAdded, &b.EndpointsDeleted} {
		if *l == nil {
			*l = []string{}
		}
	}
	if b.Nodes == nil {
		b.Nodes = []StepPlanNode{}
	}
	return json.Marshal(plain(b))
}

// StepPlanNode is one node containerlab's plan touches: its package's fidelity.link_change
// (null for a created node, which no declaration covers), what containerlab reports doing
// to it (restart, recreate, create or live) and containerlab's reason, when it gave one.
type StepPlanNode struct {
	Node     string  `json:"node"`
	Declared *string `json:"declared"`
	Reported string  `json:"reported"`
	Reason   string  `json:"reason,omitempty"`
}

// StepPushPlanEntry is one node the step pushes and why: artifact, bootstrap, restarted,
// recreated or created, sorted.
type StepPushPlanEntry struct {
	Node    string   `json:"node"`
	Reasons []string `json:"reasons"`
}

// StepPushedEntry is one push of the plan and what came of it: landed, refused, failed or
// not attempted, the finding's identifier for a refused or failed one, and how long it took.
type StepPushedEntry struct {
	Node    string   `json:"node"`
	Reasons []string `json:"reasons"`
	Outcome string   `json:"outcome"`
	Rule    string   `json:"rule,omitempty"`
	TookS   *float64 `json:"took_s,omitempty"`
}

// StepTimingsBlock is each phase's duration in seconds: the reconcile, readiness and push
// per node, and the whole; a phase not reached is absent.
type StepTimingsBlock struct {
	ReconcileS *float64           `json:"reconcile_s,omitempty"`
	Readiness  map[string]float64 `json:"readiness,omitempty"`
	Push       map[string]float64 `json:"push,omitempty"`
	WholeS     float64            `json:"whole_s"`
}

// StepReadyAfter is how long one awaited node took to answer its probe after the reconcile.
type StepReadyAfter struct {
	Node        string  `json:"node"`
	ReadyAfterS float64 `json:"ready_after_s"`
}
