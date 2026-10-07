package provision

import (
	"encoding/json"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// Fixed identities (Constitution VII, VIII; D-007, D-015). Workflows call activities by
// the wire.Act* names, never by function reference, so no workflow file imports
// internal/lab.
const (
	WorkflowProvision = wire.ProvisionWorkflowID // "fylgja-provision"
	WorkflowDestroy   = "fylgja-destroy"
	TaskQueue         = "fylgja"

	// FollowScheduleID is the one following: the Schedule that starts a check on an
	// interval.
	FollowScheduleID = "fylgja-follow"
	// WorkflowReconcile is a check's action id. The workflow service appends the scheduled
	// time, so a check is fylgja-reconcile-<time>; one at a time is the Schedule's overlap
	// policy, not the id.
	WorkflowReconcile = "fylgja-reconcile"
	// WorkflowStep is the one step run: a
	// third short workflow with a fixed id, D-007's kind, so a step is serialised with
	// itself by the id and refused beside a provisioning or destroy run.
	WorkflowStep = wire.StepWorkflowID // "fylgja-step"
)

// The following activities' names. They live here, not in wire, because they need the
// workflow service and nothing on the host.
const (
	ActRunsInFlight   = "RunsInFlight"
	ActStartFollowing = "StartFollowing"
	ActStopFollowing  = "StopFollowing"
)

// Outcomes of a check. Reconcile returns one in
// every case rather than failing.
const (
	CheckUnchanged     = "unchanged"      // the ids are equal; nothing was touched
	CheckRebuilt       = "rebuilt"        // the ids differ; the destroy and the provision ended ready
	CheckRejected      = "rejected"       // the read, the compile or the host check refused; nothing was touched
	CheckError         = "error"          // a step before the destroy could not run; the next check tries again
	CheckRebuildFailed = "rebuild_failed" // the destroy left something or the provision did not end ready; following stops
	CheckSkipped       = "skipped"        // nothing to compare against, a twin that does not follow, or a run in flight
	CheckCancelled     = "cancelled"      // twin destroy cancelled the check; the cancelled child's cleanup ran
)

// Outcomes of a provisioning run. The run returns one of these in every
// case rather than failing, so the CLI reads one shape.
const (
	OutcomeReady     = "ready"     // every node answered its probe; twin.json written
	OutcomeRejected  = "rejected"  // refused before the host was touched (exit 1)
	OutcomeFailed    = "failed"    // failed after the host was touched (exit 3 or 4)
	OutcomeCancelled = "cancelled" // cancelled; exit 2 before anything was staged (cleanup skipped), else 3 or 4
	OutcomeError     = "error"     // a step could not run (exit 2)
)

// The outcomes a step run adds to the provisioning run's. Step returns one in every case
// rather than failing; a step that is refused, could
// not run or was cancelled before its stage ends OutcomeRejected, OutcomeError or
// OutcomeCancelled with nothing touched, and one cancelled after its stage ends
// OutcomeCancelled with a phase, its record written diverged.
const (
	StepStepped   = wire.StepStepped   // every push landed; the record moved to the target
	StepUnchanged = wire.StepUnchanged // the two bundles' content is equal; the record moved, nothing reconciled or pushed
	StepDiverged  = wire.StepDiverged  // a phase failed after the stage; the twin is up, and its record says so
)

// What teardown and unstage did.
const (
	CleanupDone    = "done"    // something was removed
	CleanupNothing = "nothing" // nothing was there to remove
	CleanupFailed  = "failed"  // removal failed; see cleanup.incomplete
	CleanupSkipped = "skipped" // not attempted: nothing on the host was touched
)

// ProvisionInput starts a provisioning run: from intent (twin create) or from a stored
// bundle (twin provision). Paths are absolute and no bytes cross the queue.
type ProvisionInput struct {
	Source     string `json:"source"`      // wire.SourceIntent or wire.SourceBundle
	Branch     string `json:"branch"`      // intent: the branch to read
	At         string `json:"at"`          // intent: --at verbatim, empty when not given
	BundlePath string `json:"bundle_path"` // bundle: the stored copy's absolute path
	BundleID   string `json:"bundle_id"`   // bundle: its identity
	Version    string `json:"version"`     // the starting binary's version, kept in history only
	// ObservedAt is, with Source intent and BundleID set, the read that produced BundleID: a
	// rebuild's provision is already compiled, and records the check's read (M4).
	ObservedAt string `json:"observed_at,omitempty"`
	// Follow, when set, begins following the branch once the twin is recorded. Nil is no
	// following step; M2's inputs decode to nil (M4).
	Follow *FollowInput `json:"follow,omitempty"`
	// StopFollowing stops any following once the host check has passed: true on every run
	// the CLI starts, false on a rebuild's child and on M2's inputs (M4).
	StopFollowing bool `json:"stop_following,omitempty"`
	// Waypoint is the waypoint the CLI resolved Branch and At from, which the record step
	// writes into twin.json. The run branches on nothing of it. Nil in every
	// M2–M7 input and recorded history, and omitted when nil.
	Waypoint *WaypointInput `json:"waypoint,omitempty"`
}

// WaypointInput names a waypoint as the record does: series, sequence, description and
// where the at came from. It is the record input's own type, so the run copies it in one
// assignment and a nil stays nil with no branch in the workflow.
type WaypointInput = wire.WaypointRef

// FollowInput is how often a following twin is checked.
type FollowInput struct {
	IntervalS int `json:"interval_s"`
}

// ProvisionResult is how a provisioning run ended.
type ProvisionResult struct {
	Outcome    string `json:"outcome"`
	BundleID   string `json:"bundle_id,omitempty"`
	ObservedAt string `json:"observed_at,omitempty"`
	Step       string `json:"step,omitempty"` // the step the run stopped at, when it did not end ready
	// TwinDir is the twin directory as the worker resolved it, once staging began: the
	// CLI reports the worker's path, not its own.
	TwinDir  string        `json:"twin_dir,omitempty"`
	Findings findings.List `json:"findings"`
	// Twin is the record RecordTwin wrote, on ready. One record type: wire.TwinRecord.
	Twin    *wire.TwinRecord `json:"twin,omitempty"`
	Cleanup CleanupResult    `json:"cleanup"`
	// Following is the following the run began, when its input asked for one (M4).
	Following *FollowingResult `json:"following,omitempty"`
	// FollowingStopped is what the run's stop step did, when one ran (M4).
	FollowingStopped *StopFollowingResult `json:"following_stopped,omitempty"`
}

// FollowingResult is a following that began.
type FollowingResult struct {
	Branch     string `json:"branch"`
	IntervalS  int    `json:"interval_s"`
	ScheduleID string `json:"schedule_id"`
}

// ReconcileInput is a check's input: the Schedule's action args, fixed when following
// began. Version is the creating binary's, kept in history only.
type ReconcileInput struct {
	Branch  string `json:"branch"`
	Version string `json:"version"`
}

// ReconcileResult is how a check ended. One shape
// in every case, so twin show reads one.
type ReconcileResult struct {
	Outcome          string           `json:"outcome"`
	Step             string           `json:"step,omitempty"` // where the check ended, when not unchanged or rebuilt
	Branch           string           `json:"branch"`
	TwinBundleID     string           `json:"twin_bundle_id,omitempty"` // what twin.json recorded
	BundleID         string           `json:"bundle_id,omitempty"`      // what the check compiled
	ObservedAt       string           `json:"observed_at,omitempty"`    // the check's read
	Findings         findings.List    `json:"findings"`
	Destroy          *DestroyResult   `json:"destroy,omitempty"`   // the rebuild's destroy, when one ran
	Provision        *ProvisionResult `json:"provision,omitempty"` // the rebuild's provision, when one ran
	FollowingStopped bool             `json:"following_stopped,omitempty"`
}

// RunsInFlightResult names the operator's runs in flight, by run id; "" is none running.
type RunsInFlightResult struct {
	Provision string `json:"provision"`
	Destroy   string `json:"destroy"`
}

// StartFollowingInput is the following to begin.
type StartFollowingInput struct {
	Branch    string `json:"branch"`
	IntervalS int    `json:"interval_s"`
	Version   string `json:"version"`
}

// StopFollowingResult says whether a Schedule was deleted, and the branch it followed.
type StopFollowingResult struct {
	Deleted bool   `json:"deleted"`
	Branch  string `json:"branch,omitempty"`
}

// CleanupResult is what teardown and unstage did, and what is left on the host.
type CleanupResult struct {
	Teardown  string   `json:"teardown"`
	Unstage   string   `json:"unstage"`
	Removed   []string `json:"removed,omitempty"`
	Remaining []string `json:"remaining,omitempty"`
}

// DestroyResult is how a destroy run ended. Destroy takes no input: there is one twin.
type DestroyResult struct {
	Cleanup  CleanupResult `json:"cleanup"`
	Findings findings.List `json:"findings"`
}

// DestroyRun is a twin destroy as the CLI saw it: the destroy run it started, or the one
// already in flight it attached to, and that run's result.
type DestroyRun struct {
	RunID    string
	Attached bool
	Result   DestroyResult
	// FollowingStopped is what stopping following again, once no provisioning run was in
	// flight, did (contracts/cli.md, twin destroy step 2a).
	FollowingStopped FollowStop
}

// ReadIntentInput is the intent reference to read. The CTM is named by the run's id,
// which the activity takes from its own context.
type ReadIntentInput struct {
	Branch string `json:"branch"`
	At     string `json:"at"`
}

// ReadIntentResult is where the read's CTM was written, when the read began, and its
// findings; rejections are findings here, not errors.
type ReadIntentResult struct {
	CTMPath    string        `json:"ctm_path"`
	ObservedAt string        `json:"observed_at"`
	Findings   findings.List `json:"findings"`
}

// CompileInput names the CTM to compile.
type CompileInput struct {
	CTMPath string `json:"ctm_path"`
}

// CompileResult is the stored bundle's identity and absolute path, and the compile's
// findings.
type CompileResult struct {
	BundleID   string        `json:"bundle_id"`
	BundlePath string        `json:"bundle_path"`
	Findings   findings.List `json:"findings"`
}

// StepInput starts a step run: everything the CLI
// resolved, read, compiled and decided before any connection, so the run reads only the
// host. Paths are absolute and no bytes cross the queue beyond M10's step between the two
// bundles, which the record keeps.
type StepInput struct {
	// From is the record's side: its waypoint, bundle_id and at. The run's first lock holds
	// the host's record to it.
	From wire.StepSide `json:"from"`
	// To is the target's side, with its branch.
	To wire.StepSide `json:"to"`
	// ObservedAt is when the CLI read the target, which the record takes as its own once it
	// moves to the target.
	ObservedAt string `json:"observed_at"`
	// ToBundlePath is the target bundle's copy in the CLI's store; the run checks the host
	// against it, reads containerlab's plan for it and stages it, as a twin provision's
	// BundlePath is read.
	ToBundlePath string `json:"to_bundle_path"`
	// Diff is M10's step between the two bundles as its pair JSON
	// (waypoints.schema.json, $defs/step), for the record and the document.
	Diff json.RawMessage `json:"diff"`
	// Unchanged is step.Unchanged: the two bundles' content is equal and they differ by
	// provenance alone. The run then stages the target and records it, and reconciles,
	// awaits and pushes nothing.
	Unchanged bool `json:"unchanged"`
	// Plan is containerlab's plan as the CLI read and printed it. The run reads its own at
	// step 3 and acts on that; this one is the document's when the run never read one.
	Plan wire.ReconcilePlan `json:"plan"`
	// PushPlan is step.PushPlan over the CLI's plan. The run adds to it
	// every node its own plan restarts, recreates or creates, and drops every node it
	// deletes, so it pushes what its plan acts on.
	PushPlan []step.NodePush `json:"push_plan"`
	// Changed is every node the step changes in a way only containerlab's lifecycle
	// applies, with those changes (ChangesOf), for the run's own step.node.unapplied lock.
	Changed      []StepChange `json:"changed"`
	AllowRestart bool         `json:"allow_restart"`
	// Declared is each target node's package's fidelity.link_change, restart or
	// live:
	// the host check's plan does not carry it, so the CLI does.
	Declared map[string]string `json:"declared"`
	// WaitS is the budget of the step's wait after its record, in seconds:
	// verify.DefaultBudget when twin step's --wait is
	// left out, its value otherwise; 0 reads once. Absent from both M11 step histories, which
	// never reach the wait's marker.
	WaitS int `json:"wait_s"`
	// Version is the starting binary's version, kept in history only.
	Version string `json:"version"`
}

// StepChange is one node a step changes in a way containerlab applies only by its
// lifecycle: its changes among step.ReasonImage,
// step.ReasonPlatform and step.ReasonPSP, which only a recreate applies, or ChangeAdded for
// a node the step adds, which only a create does.
type StepChange struct {
	Node    string   `json:"node"`
	Changes []string `json:"changes"`
}

// ChangeAdded is a StepChange of a node the target adds.
const ChangeAdded = "added"

// StepResult is how a step run ended. One shape in every case.
type StepResult struct {
	// Outcome is StepStepped, StepUnchanged, StepDiverged, OutcomeRejected, OutcomeError or
	// OutcomeCancelled.
	Outcome string `json:"outcome"`
	// Phase is the phase a step that touched the host stopped at — reconcile, readiness,
	// push or record — on a diverged step and on one cancelled after its stage; "" otherwise.
	Phase string `json:"phase,omitempty"`
	// Step is the step the run stopped at, when it did not end stepped or unchanged.
	Step     string        `json:"step,omitempty"`
	Findings findings.List `json:"findings"`
	// Plan is containerlab's plan the run read at step 3 and acted on; nil before then.
	Plan      *wire.ReconcilePlan    `json:"plan,omitempty"`
	Reconcile *wire.ReconcileResult  `json:"reconcile,omitempty"` // nil when skipped or not reached
	Ready     []wire.ReadinessResult `json:"ready,omitempty"`
	// Pushed is each push that landed, its Diff stripped: the push activity's own result is
	// the device's diff's only home.
	Pushed []wire.PushResult `json:"pushed,omitempty"`
	// PushPlan is the run's push plan with each node's outcome; nil before the stage.
	PushPlan []wire.StepPush `json:"push_plan,omitempty"`
	// Record is the record the record step wrote, when it wrote one.
	Record    *wire.TwinRecord `json:"record,omitempty"`
	Timings   wire.StepTimings `json:"timings"`
	StartedAt string           `json:"started_at"`
	EndedAt   string           `json:"ended_at"`
	// Wait is how the step's wait after the record ended: the activity's answer, or
	// incomplete when it
	// failed outright. Nil when the wait did not run: a run that ended before its stage, one
	// cancelled before the wait began, and every run of a history from before its marker.
	// Nothing else of the result depends on it.
	Wait *wire.StepWait `json:"wait,omitempty"`
}
