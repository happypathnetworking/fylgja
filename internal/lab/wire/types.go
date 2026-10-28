package wire

import (
	"encoding/json"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Activity names. Workflows schedule activities by these names, never by function
// reference, so no workflow file needs internal/lab to compile.
const (
	ActReadIntent     = "ReadIntent"
	ActCompile        = "Compile"
	ActCheckHost      = "CheckHost"
	ActStageBundle    = "StageBundle"
	ActDeployLab      = "DeployLab"
	ActAwaitReadiness = "AwaitReadiness"
	ActRecordTwin     = "RecordTwin"
	ActPlanTeardown   = "PlanTeardown"
	ActDestroyLab     = "DestroyLab"
	ActUnstageTwin    = "UnstageTwin"
	ActInspectTwin    = "InspectTwin"
	ActPushConfig     = "PushConfig"

	// M11: the step's own activities.
	// containerlab's plan read against the twin directory, the stage swap, the reconcile
	// of the running lab, and the step's record.
	ActPlanReconcile = "PlanReconcile"
	ActStageStep     = "StageStep"
	ActReconcileLab  = "ReconcileLab"
	ActRecordStep    = "RecordStep"

	// M12: the step's wait after its record:
	// verify's waiting form run on the lab host, which writes how the wait ended into the
	// record.
	ActVerifyTwin = "VerifyTwin"
)

// ProvisionWorkflowID is the provisioning workflow's fixed identity (Constitution VIII).
// twin.json records it, so the lab host needs it without importing internal/provision.
const ProvisionWorkflowID = "fylgja-provision"

// StepWorkflowID is the step workflow's fixed identity:
// a third short workflow of D-007's kind. The record's step.run names it, so the lab host
// needs it without importing internal/provision.
const StepWorkflowID = "fylgja-step"

// RehearseWorkflowID is the rehearsal workflow's fixed identity: a fifth short workflow
// (D-051). The record's rehearsal names it, so the lab host needs it without importing
// internal/provision.
const RehearseWorkflowID = "fylgja-rehearse"

// A record's state. twin.json 4 writes one of the two; a
// record of 3 or earlier reads as "" and is shown as ready.
const (
	StateReady    = "ready"    // the twin is at the record's stage and bundle
	StateDiverged = "diverged" // the last step failed or was cancelled after the host was touched
)

// A step's outcome as the record keeps it: rejected, error and cancelled
// before the stage write no record, so they are the workflow's and not here.
const (
	StepStepped   = "stepped"
	StepUnchanged = "unchanged"
	StepDiverged  = "diverged"
)

// One node's push outcome in a step's record: landed, refused
// (push.refused), failed (push.failed), or not attempted because an earlier phase failed.
const (
	PushLanded       = "landed"
	PushRefused      = "refused"
	PushFailed       = "failed"
	PushNotAttempted = "not_attempted"
)

// LabName is the containerlab lab every twin is, written by the compiler (Constitution
// VII). It is here, with the command that clears it, so workflow code can name the lab in
// a finding without importing internal/lab.
const LabName = "fylgja"

// ClearLabCommand removes lab fylgja by hand, whatever state it is in.
const ClearLabCommand = "clab destroy --name " + LabName + " --cleanup"

// DefaultDestroyTimeoutS is the teardown budget, in seconds, for a node whose platform
// no support package on the worker covers. It is the one stated default budget:
// every platform a package covers is budgeted by that package's
// image.destroy_timeout_s (Constitution II). Here because both internal/lab and
// internal/provision need it.
const DefaultDestroyTimeoutS = 60

// Source says how a twin came to be provisioned.
const (
	// SourceIntent is a twin created by twin create --branch or --stage: the server read and
	// compiled, or a check's rebuild did (018).
	SourceIntent = "intent"
	SourceBundle = "bundle" // twin provision: an existing bundle, no read
	// SourceSnapshot is a twin created by twin create --snapshot from a stored or sent
	// snapshot: no read (018).
	SourceSnapshot = "snapshot"
)

// Teardown plan bases: what PlanTeardown budgeted from.
const (
	BasisManifest = "manifest" // the staged bundle's manifest
	BasisInspect  = "inspect"  // the containers containerlab reports: an orphan with no twin directory
	BasisNone     = "none"     // nothing to tear down
)

// Provenance is the manifest's provenance block, carried into twin.json verbatim: it
// mirrors compiler.Provenance, which this package does not import. From twin.json 8
// (017) it names the scope the read was made under and the mapping that read it, in place
// of the generics contract's version. A record of 7 or earlier, which carries
// contract_version and neither of these, reads with both empty.
type Provenance struct {
	Branch     string  `json:"branch"`
	At         string  `json:"at,omitempty"`
	SchemaHash string  `json:"schema_hash"`
	Scope      string  `json:"scope"`
	Mapping    Mapping `json:"mapping"`
}

// Mapping names the reader that produced the CTM and the version of the model it read,
// as the CTM envelope's mapping block does (017; ctm.Mapping).
type Mapping struct {
	Reader  string `json:"reader"`
	Model   string `json:"model"`
	Version string `json:"version"`
}

// CheckHostInput names the bundle to check the host against.
type CheckHostInput struct {
	BundlePath string `json:"bundle_path"`
	BundleID   string `json:"bundle_id"`
}

// CheckHostResult is the plan for the bundle's nodes, what the host holds, and the
// refusals and warnings that follow. Rejections are findings here, not errors: a
// refusal is an answer, not a failure to answer.
type CheckHostResult struct {
	Nodes          []NodePlan    `json:"nodes"`
	MemorySumMB    int           `json:"memory_sum_mb"`
	HostBudgetMB   *int          `json:"host_budget_mb"`
	LabPresent     bool          `json:"lab_present"`
	TwinDirPresent bool          `json:"twin_dir_present"`
	Provenance     Provenance    `json:"provenance"`
	Findings       findings.List `json:"findings"`
}

// NodePlan is one node with the budgets and probe its package gives it. Every duration
// here is the package's, never a constant (Constitution II).
type NodePlan struct {
	Name            string   `json:"name"`
	PSPID           string   `json:"psp_id"`
	PSPSource       string   `json:"psp_source"`
	Image           string   `json:"image"`
	MemoryMB        int      `json:"memory_mb"`
	TimeoutS        int      `json:"timeout_s"`
	DeployTimeoutS  int      `json:"deploy_timeout_s"`
	DestroyTimeoutS int      `json:"destroy_timeout_s"`
	Probe           Probe    `json:"probe"`
	Push            PushSpec `json:"push"`
	// Artifact is the node's configuration as the bundle's manifest names it: the host
	// check reads the manifest, and the workflow, which reads no disk, takes the push's
	// file and checksum from here (M5). Nil when the manifest names none.
	Artifact *PlanArtifact `json:"artifact,omitempty"`
	// AwaitPushTransport is the node's package asking readiness to wait for the endpoint
	// Push names, not only for the probe (M7 D-029). A defaulted field, absent in every
	// recorded history, where false is the behaviour those histories recorded.
	AwaitPushTransport bool `json:"await_push_transport,omitempty"`
}

// PlanArtifact is where a node's artifact is in the bundle and what it must hash to: the
// manifest's artifact.file and artifact.checksum. A path and an identity, never bytes.
type PlanArtifact struct {
	File     string `json:"file"`
	Checksum string `json:"checksum"`
}

// PushSpec is how a node takes its configuration artifact, as its package declares
// it.
// Like Probe, the login fields are the names of environment
// variables on the worker, never their values (Constitution X).
type PushSpec struct {
	Delivery    string `json:"delivery"` // json_rpc; the mechanism the push dispatches on
	Mode        string `json:"mode"`     // merge | replace
	Commit      string `json:"commit"`   // explicit | implicit
	Scheme      string `json:"scheme"`   // http | https
	Port        int    `json:"port"`
	UsernameEnv string `json:"username_env"`
	PasswordEnv string `json:"password_env"`
	TimeoutS    int    `json:"timeout_s"` // the package's push_timeout_s, never a constant
}

// PushInput is one node's push. It names the staged file rather than carrying it: bytes
// never cross the queue (Constitution VIII).
type PushInput struct {
	Node     string   `json:"node"`
	MgmtIPv4 string   `json:"mgmt_ipv4"`
	TwinDir  string   `json:"twin_dir"` // the staged bundle is <TwinDir>/bundle
	Artifact string   `json:"artifact"` // the manifest's artifact.file, e.g. configs/n1.device-config
	Checksum string   `json:"checksum"` // the manifest's, verified against the staged bytes before sending
	Push     PushSpec `json:"push"`
}

// PushResult is what one node took and how long it took to take it.
type PushResult struct {
	Node      string  `json:"node"`
	PushedInS float64 `json:"pushed_in_s"`
	Checksum  string  `json:"checksum"`
	Size      int     `json:"size"`
	// Diff is the device's own account of what the push changed, under mode replace: the
	// request's text output on JSON-RPC, the diff command's output on eAPI. It is the push
	// activity's result and nothing else: the step and
	// provisioning workflows strip it before a PushResult enters any other input or result,
	// and no finding, document, record or log line carries it. A defaulted field, absent in
	// every recorded history and empty under merge.
	Diff string `json:"diff,omitempty"`
}

// Probe is a node's readiness probe as its package declares it. The login fields are
// the names of environment variables on the worker, never their values.
type Probe struct {
	Transport   string `json:"transport"`
	Path        string `json:"path"`
	Encoding    string `json:"encoding"`
	Port        int    `json:"port"`
	UsernameEnv string `json:"username_env"`
	PasswordEnv string `json:"password_env"`
	// TLS says whether the probe speaks TLS to the node. A pointer, and nil means TLS:
	// every plan recorded before this field omits the key, and a plain bool would decode
	// those as false and dial every replayed M2-era plan in plaintext. nodePlan always
	// sets it explicitly, so a plan this build writes is never ambiguous.
	//
	// The one addition to this package at M7: a defaulted field on an
	// existing type, absent in every recorded history, so all six replay unchanged.
	TLS *bool `json:"tls,omitempty"`
}

// ProbeTLS reads a probe's TLS with its default applied: nil means TLS, which is what
// every plan written before the field meant. One function, so no caller has to remember
// which way an absent key falls.
func ProbeTLS(p Probe) bool { return p.TLS == nil || *p.TLS }

// LabNode is one container as containerlab reports it.
type LabNode struct {
	Name      string `json:"name"`      // the node name, clab-fylgja- stripped
	Container string `json:"container"` // clab-fylgja-<name>
	Kind      string `json:"kind"`      // containerlab's kind, matched to a package's image.clab_kind
	Image     string `json:"image"`
	State     string `json:"state"`     // "running" when up
	MgmtIPv4  string `json:"mgmt_ipv4"` // without the prefix length
}

// HostReport is what the host holds of a twin, as a check sees it: InspectHost run on the
// worker and returned over the queue, so the check knows what it has to compare against
// without reading disk and names an orphan in M3's words without importing internal/lab
// (D-015).
type HostReport struct {
	LabPresent     bool        `json:"lab_present"`
	Nodes          []LabNode   `json:"nodes"`      // containerlab's, as DeployResult carries them
	TopoPaths      []string    `json:"topo_paths"` // absLabPath, distinct (M3)
	TwinDirPresent bool        `json:"twin_dir_present"`
	Twin           *TwinRecord `json:"twin"`            // twin.json when present and it parses
	TwinReadError  string      `json:"twin_read_error"` // why it could not be read; "" otherwise (M3)
	Phrase         string      `json:"phrase"`          // HostState.Describe(), verbatim
}

// StageInput names the bundle to copy into the twin directory. BundlePath is the source;
// the id is what the copy must hash to.
type StageInput struct {
	BundlePath string `json:"bundle_path"`
	BundleID   string `json:"bundle_id"`
}

// StageResult is where the bundle was staged.
type StageResult struct {
	TwinDir string `json:"twin_dir"`
}

// DeployInput is the staged twin and the plan for its nodes.
type DeployInput struct {
	TwinDir string     `json:"twin_dir"`
	Nodes   []NodePlan `json:"nodes"`
}

// DeployResult is the nodes containerlab reports after deploy.
type DeployResult struct {
	Nodes []LabNode `json:"nodes"`
}

// ReadinessInput is one node to wait for, under its own package's timeout.
type ReadinessInput struct {
	Node     string `json:"node"`
	MgmtIPv4 string `json:"mgmt_ipv4"`
	Probe    Probe  `json:"probe"`
	TimeoutS int    `json:"timeout_s"`
	// AwaitPushScheme and AwaitPushPort are the push transport readiness waits for once
	// the probe has answered, set only for a node whose package asks (D-029). Empty and
	// zero mean no wait, which is what every recorded history carries and what every
	// package before the field meant. Only a scheme and a port cross for this: the wait
	// opens a connection and closes it, so no login is needed and none is sent.
	AwaitPushScheme string `json:"await_push_scheme,omitempty"`
	AwaitPushPort   int    `json:"await_push_port,omitempty"`
}

// ReadinessResult is how long a node took to answer its probe.
type ReadinessResult struct {
	Node        string  `json:"node"`
	ReadyAfterS float64 `json:"ready_after_s"`
}

// RecordInput is everything twin.json records that the lab host cannot know itself.
// ObservedAt is nil when no read took place.
type RecordInput struct {
	TwinDir    string            `json:"twin_dir"`
	BundleID   string            `json:"bundle_id"`
	Provenance Provenance        `json:"provenance"`
	ObservedAt *string           `json:"observed_at"`
	Source     string            `json:"source"`
	RunID      string            `json:"run_id"`
	Nodes      []LabNode         `json:"nodes"`
	ReadyAfter []ReadinessResult `json:"ready_after"`
	// Pushed is each node's push result (M5). RecordTwin refuses record.failed for a
	// node the results do not name, as it refuses one the manifest does not name.
	Pushed []PushResult `json:"pushed"`
	// Stage is the stage the server resolved the run's reference from (014), copied into
	// the record as data. Nil in every input and recorded history of a run not created
	// from a stage, and omitted when nil, so their activity payloads are byte-identical.
	Stage *StageRef `json:"stage,omitempty"`
	// Rehearsal is the rehearsal run whose baseline this create is (015), copied into the
	// record as data, so a twin a dead rehearsal left can be told from a hand twin. Nil in
	// every input and recorded history of a run a rehearsal did not start, and omitted when
	// nil, as Stage is.
	Rehearsal *RehearsalRef `json:"rehearsal,omitempty"`
	// SnapshotID is the snapshot the run's bundle was compiled from (018), copied into the
	// record as data. Empty in every input and recorded history before 018, and in a
	// rebuild's and a twin provision's, and omitted when empty, as Stage is.
	SnapshotID string `json:"snapshot_id,omitempty"`
}

// RecordResult is where the record was written and the record exactly as written, so
// the workflow reports it without reading disk (Constitution VIII).
type RecordResult struct {
	Path   string     `json:"path"`
	Record TwinRecord `json:"record"`
}

// TwinRecord is twin.json. It
// lives here, not in internal/lab, because RecordTwin returns it to the workflow.
// RecordedAt is a string so this package needs no time import.
type TwinRecord struct {
	TwinVersion string `json:"twin_version"`
	Lab         string `json:"lab"`
	// SnapshotID names the snapshot the twin was built from or last stepped to, or is nil
	// (018): a twin built by twin provision, one a following check's rebuild made, and a
	// record of 8 or earlier, which has no key and reads as nil. No omitempty: version 9
	// writes an explicit null for none, as stage does.
	SnapshotID     *string       `json:"snapshot_id"`
	BundleID       string        `json:"bundle_id"`
	Provenance     Provenance    `json:"provenance"`
	ObservedAt     *string       `json:"observed_at"`
	ObservedAtNote string        `json:"observed_at_note,omitempty"`
	Source         string        `json:"source"`
	Run            RunRef        `json:"run"`
	ProvisionedBy  ProvisionedBy `json:"provisioned_by"`
	RecordedAt     string        `json:"recorded_at"`
	Nodes          []TwinNode    `json:"nodes"`
	// Stage names the stage the twin was created from or last stepped to, or is nil
	// (014). No omitempty: version 6 writes an explicit null for none, as observed_at
	// does, and a record of 5 or earlier, which has no key, reads as nil.
	Stage *StageRef `json:"stage"`
	// State is ready or diverged. A record of version 3 or
	// earlier has no key and reads as "", which is shown as ready.
	State string `json:"state,omitempty"`
	// Step is the twin's last step, or nil for a twin that has not stepped.
	// An earlier record, which has no key, reads as nil. Version 4 writes an explicit
	// null, as stage does.
	Step *StepRecord `json:"step"`
	// Rehearsal names the rehearsal run whose baseline the twin is, or is nil for a twin no
	// rehearsal created (015). A step's record keeps it. No omitempty: version 7 writes an
	// explicit null for none, as stage does, and a record of 6 or earlier, which has no key,
	// reads as nil.
	Rehearsal *RehearsalRef `json:"rehearsal"`
	// Superseded is set by lab.ReadRecord on a record of twin.json 5 or earlier that names
	// the pinned reference it was created from in M10's shape, which this build no longer
	// reads, so twin step's refusal can say so. Never written, and not carried across an
	// activity's boundary, where the refusal is the one for a record naming no stage.
	Superseded bool `json:"-"`
}

// SideName is s, the record's own stage or a side of its step, as a line names it:
// s.Name(), or, when s is nil on a record of twin.json 5 or earlier that names M10's
// waypoint (Superseded), the waypoint as twin step's refusal of the record words it, since
// a step side of such a record named a waypoint too (014, research R-11).
func (r *TwinRecord) SideName(s *StageRef) string {
	if s == nil && r.Superseded {
		return r.SupersededWaypoint()
	}
	return s.Name()
}

// SideStage is SideName for a line that says "stage" before the name: "stage
// <branch>/<label>", or a superseded record's waypoint as SideName words it.
func (r *TwinRecord) SideStage(s *StageRef) string {
	if s == nil && r.Superseded {
		return r.SupersededWaypoint()
	}
	return "stage " + s.Name()
}

// Position is where the twin is, as a step side's Name words a side, over the record's top
// level: its stage, else its snapshot, else its bundle (019, research R-05). A record of
// twin.json 5 or earlier that names M10's waypoint (Superseded) is named as SideStage names
// it.
func (r *TwinRecord) Position() string {
	if r.Stage == nil && r.Superseded {
		return r.SupersededWaypoint()
	}
	snapshot := ""
	if r.SnapshotID != nil {
		snapshot = *r.SnapshotID
	}
	return sideName(r.Stage, snapshot, r.BundleID)
}

// sideName is "stage <branch>/<label>" when stage is set, else "snapshot <short>" when
// snapshotID is, else "bundle <short>": a side of a record of twin.json 8 that stepped,
// which names neither.
func sideName(stage *StageRef, snapshotID, bundleID string) string {
	switch {
	case stage != nil:
		return "stage " + stage.Name()
	case snapshotID != "":
		return "snapshot " + shortID(snapshotID)
	}
	return "bundle " + shortID(bundleID)
}

// shortID is an id's first eight characters and an ellipsis, as every line names one.
func shortID(id string) string {
	if len(id) > 8 {
		return id[:8] + "…"
	}
	return id
}

// SupersededWaypoint is what a record of twin.json 5 or earlier was created from or stepped
// along, M10's pinned reference, which this build no longer reads: "a waypoint of a record
// version this build no longer reads (twin.json 5)".
func (r *TwinRecord) SupersededWaypoint() string {
	return "a waypoint of a record version this build no longer reads (twin.json " + r.TwinVersion + ")"
}

// StageRef is the stage a twin was created from or stepped to, as the record names it
// (014): its proposed change by id and source branch, its label (a mark's, or
// branch-point or head), the operator's description and where the at came from (given on
// the mark, written: the mark's own write stamp, branch_point or head). The at itself is
// the record's provenance.at, and provenance.branch the branch read: the default branch
// for a branch-point twin.
type StageRef struct {
	ProposedChange StageChange `json:"proposed_change"`
	Label          string      `json:"label"`
	Description    string      `json:"description"`
	AtSource       string      `json:"at_source"`
}

// StageChange names the proposed change a stage belongs to: its id, which is its
// identity, and its source branch, which is how a reference finds it.
type StageChange struct {
	ID     string `json:"id"`
	Branch string `json:"branch"`
}

// Name is the stage as a reference names it, <branch>/<label>, or "none".
func (s *StageRef) Name() string {
	if s == nil {
		return "none"
	}
	return s.ProposedChange.Branch + "/" + s.Label
}

// RunRef is the provisioning run's identity in Temporal.
type RunRef struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
}

// RehearsalRef is a rehearsal run's identity in Temporal, as the record names it:
// RehearseWorkflowID and the run's id (015).
type RehearsalRef struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
}

// ProvisionedBy identifies the worker binary that provisioned the twin.
type ProvisionedBy struct {
	Version string `json:"version"`
}

// TwinNode is one node of a recorded twin.
type TwinNode struct {
	Name        string  `json:"name"`
	Container   string  `json:"container"`
	Image       string  `json:"image"`
	PSP         PSPRef  `json:"psp"`
	MgmtIPv4    string  `json:"mgmt_ipv4"`
	ReadyAfterS float64 `json:"ready_after_s"`
	// Artifact is what this node was pushed, copied from the staged manifest as PSP is
	// (M5). The document projects it to a name and a checksum; the record keeps all
	// four fields. No content. Nil only in a record written before M5.
	Artifact *TwinArtifact `json:"artifact"`
	// PushedInS is how long this node's push took, from the activity's start to the
	// node's commit.
	PushedInS float64 `json:"pushed_in_s"`
	// Holds is the bundle_id whose bootstrap and artifact the node is last known to run: the
	// record's on a create, the target's on a node a step pushed and landed, the previous
	// one on a node a step left as it was or whose push did not land, and nil for a node
	// containerlab restarted, recreated or created that no push landed on, which runs its
	// baseline alone. It is not a claim that a
	// push which did not land left the node untouched: a StepPush whose Outcome is
	// PushFailed may have committed (a replace that darkens a node), and only
	// PushRefused is the node's own atomic answer. A later rollback reads the push's
	// outcome beside Holds. An earlier record, which has no key, reads as nil
	// (shown as the record's bundle_id). Version 4 writes null for that node.
	Holds *string `json:"holds"`
}

// TwinArtifact names what a node was pushed, as the manifest names it: identity and
// size, never a byte of it.
type TwinArtifact struct {
	Name        string `json:"name"`
	ContentType string `json:"content_type"`
	Checksum    string `json:"checksum"`
	Size        int    `json:"size"`
}

// PSPRef names the support package a node was provisioned with, as the manifest does.
type PSPRef struct {
	ID     string `json:"id"`
	Source string `json:"source"`
}

// PlanTeardownResult is the teardown budget and what it was derived from. A node no
// package covers is named in Uncovered and budgeted at DefaultDestroyTimeoutS.
type PlanTeardownResult struct {
	DestroyTimeoutS int      `json:"destroy_timeout_s"`
	Basis           string   `json:"basis"`
	Uncovered       []string `json:"uncovered,omitempty"`
}

// DestroyLabInput carries the teardown budget, so the activity can say what it had.
type DestroyLabInput struct {
	DestroyTimeoutS int `json:"destroy_timeout_s"`
}

// DestroyLabResult says whether a lab was removed and how many containers it held.
type DestroyLabResult struct {
	Removed    bool `json:"removed"`
	Containers int  `json:"containers"`
}

// UnstageResult says whether the twin directory was removed, and where it is on the
// worker: the commands report the worker's path, not their own.
type UnstageResult struct {
	Removed bool   `json:"removed"`
	Path    string `json:"path"`
}

// ReconcilePlan is containerlab's plan for the running lab against a target topology:
// clab deploy --dry-run --format json, read with the twin directory's lab state.
// The lists are node names, links as
// containerlab prints them ("e1:eth3 -- s1:e1-3") and endpoints ("s1:e1-1"); Reasons is
// containerlab's own text per node ("added link", "config drift: Image", ...). It is a
// read of what containerlab would do, carried as data and acted on.
type ReconcilePlan struct {
	Added            []string          `json:"added"`
	Deleted          []string          `json:"deleted"`
	Recreated        []string          `json:"recreated"`
	Restarted        []string          `json:"restarted"`
	LinksAdded       []string          `json:"links_added"`
	EndpointsDeleted []string          `json:"endpoints_deleted"`
	Reasons          map[string]string `json:"reasons,omitempty"`
}

// What containerlab reports doing to a node a plan touches:
// restarted, recreated, created, or re-cabled in place.
const (
	ReportedRestart  = "restart"
	ReportedRecreate = "recreate"
	ReportedCreate   = "create"
	ReportedLive     = "live"
)

// Empty says the plan applies nothing: every list empty. A step whose
// plan is empty skips the reconcile.
func (p ReconcilePlan) Empty() bool {
	return len(p.Added) == 0 && len(p.Deleted) == 0 && len(p.Recreated) == 0 &&
		len(p.Restarted) == 0 && len(p.LinksAdded) == 0 && len(p.EndpointsDeleted) == 0
}

// PlanNode is one node a plan touches and what containerlab reports doing to it, with
// containerlab's reason when it gave one.
type PlanNode struct {
	Node     string `json:"node"`
	Reported string `json:"reported"`
	Reason   string `json:"reason,omitempty"`
}

// Nodes is every node the plan touches, sorted by name: a node in Recreated, Restarted or
// Added, and every end of an added link or deleted endpoint, each with what containerlab
// reports doing to it. recreate outranks restart, which outranks
// create; an end in no lifecycle list is re-cabled live. A node the plan deletes is gone,
// not touched, so it is not here even when its endpoints are.
func (p ReconcilePlan) Nodes() []PlanNode {
	in := func(list []string) map[string]bool {
		m := make(map[string]bool, len(list))
		for _, n := range list {
			m[n] = true
		}
		return m
	}
	recreated, restarted, added, deleted := in(p.Recreated), in(p.Restarted), in(p.Added), in(p.Deleted)
	touched := map[string]bool{}
	for _, list := range [][]string{p.Recreated, p.Restarted, p.Added} {
		for _, n := range list {
			touched[n] = true
		}
	}
	endpointNode := func(endpoint string) string {
		node, _, _ := strings.Cut(strings.TrimSpace(endpoint), ":")
		return node
	}
	for _, link := range p.LinksAdded {
		for _, end := range strings.Split(link, " -- ") {
			if n := endpointNode(end); n != "" {
				touched[n] = true
			}
		}
	}
	for _, end := range p.EndpointsDeleted {
		if n := endpointNode(end); n != "" {
			touched[n] = true
		}
	}
	out := make([]PlanNode, 0, len(touched))
	for n := range touched {
		if deleted[n] {
			continue
		}
		reported := ReportedLive
		switch {
		case recreated[n]:
			reported = ReportedRecreate
		case restarted[n]:
			reported = ReportedRestart
		case added[n]:
			reported = ReportedCreate
		}
		out = append(out, PlanNode{Node: n, Reported: reported, Reason: p.Reasons[n]})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Node < out[j].Node })
	return out
}

// PlanReconcileInput names the target bundle containerlab's plan is read for: a path and
// the id it must hash to, as StageInput does.
type PlanReconcileInput struct {
	BundlePath string `json:"bundle_path"`
	BundleID   string `json:"bundle_id"`
}

// StageStepInput names the target bundle to swap into the twin directory and the bundle
// the twin directory must hold before the swap: a twin/bundle that does
// not hash to FromBundleID is a lab running something the step did not expect.
type StageStepInput struct {
	BundlePath   string `json:"bundle_path"`
	BundleID     string `json:"bundle_id"`
	FromBundleID string `json:"from_bundle_id"`
}

// ReconcileInput is the staged twin, the plan for the target's nodes (their deploy budgets)
// and containerlab's plan the reconcile was decided on.
type ReconcileInput struct {
	TwinDir string        `json:"twin_dir"`
	Nodes   []NodePlan    `json:"nodes"`
	Plan    ReconcilePlan `json:"plan"`
}

// ReconcileResult is the nodes containerlab reports after the reconcile, as DeployResult
// carries them, and how long the apply took.
type ReconcileResult struct {
	Nodes []LabNode `json:"nodes"`
	TookS float64   `json:"took_s"`
}

// StepSide is one side of a step: the stage, the snapshot, the bundle and the pinned at,
// verbatim. Branch is the target's, for the document's to side
// (contracts/step.schema.json); the record's sides carry none (contracts/twin.schema.json),
// so a side written into a record leaves it empty. SnapshotID is the side's snapshot (018),
// empty where it is not known: the from side of a record of 8 or earlier. Empty in every
// input and recorded history before 018, and omitted when empty, so their payloads are
// byte-identical.
type StepSide struct {
	Stage      *StageRef `json:"stage"`
	SnapshotID string    `json:"snapshot_id,omitempty"`
	BundleID   string    `json:"bundle_id"`
	At         string    `json:"at"`
	Branch     string    `json:"branch,omitempty"`
}

// Name is the side as a step's lines name it (019, research R-05): "stage <branch>/<label>"
// when it names a stage, else "snapshot <first 8 of snapshot_id>…" when it names a
// snapshot, else "bundle <first 8 of bundle_id>…".
func (s StepSide) Name() string {
	return sideName(s.Stage, s.SnapshotID, s.BundleID)
}

// RecordStepInput is everything a step's record holds that the lab host cannot read for
// itself. The record activity reads the current twin.json and the
// staged manifest; the rest crosses here as data. Pushed carries no Diff: the workflow
// strips it before building this input, so no content crosses twice.
type RecordStepInput struct {
	TwinDir string   `json:"twin_dir"`
	From    StepSide `json:"from"`
	To      StepSide `json:"to"`
	Outcome string   `json:"outcome"`         // stepped | unchanged | diverged
	Phase   string   `json:"phase,omitempty"` // reconcile | readiness | push | record when diverged
	RunID   string   `json:"run_id"`
	// ObservedAt is the target's read's observed_at, which the record takes as its own
	// when the step moves it to the target: the CLI read the target, and
	// the lab host cannot know when.
	ObservedAt string `json:"observed_at"`
	// ReconcileStarted says the reconcile activity was scheduled, so containerlab may have
	// restarted, recreated or created the plan's nodes: a node of those the step never
	// pushed then holds no bundle (null). A step stopped at its stage never reconciled,
	// and every node still holds the bundle it held.
	ReconcileStarted bool            `json:"reconcile_started"`
	AllowRestart     bool            `json:"allow_restart"`
	Diff             json.RawMessage `json:"diff,omitempty"` // M10's step between the two bundles, as the pair JSON
	Plan             ReconcilePlan   `json:"plan"`
	// Declared is each node's package's fidelity.link_change, beside what containerlab
	// reported.
	Declared  map[string]string `json:"declared,omitempty"`
	Reconcile *ReconcileResult  `json:"reconcile,omitempty"` // nil when the reconcile was skipped or not reached
	Ready     []ReadinessResult `json:"ready"`
	Pushed    []PushResult      `json:"pushed"`
	// PushPlan is the step's push plan, each entry's outcome and rule set by the workflow
	// from what its push step returned.
	PushPlan  []StepPush    `json:"push_plan"`
	Findings  findings.List `json:"findings"`
	StartedAt string        `json:"started_at"` // workflow.Now() at the run's start, RFC 3339 UTC
	EndedAt   string        `json:"ended_at"`   // workflow.Now() at the record
	// Nodes is the lab's nodes after the reconcile, or as inspected before the stage when
	// none ran or it returned no report; in the second case RecordStep reads the lab again.
	Nodes []LabNode `json:"nodes"`
}

// StepRecord is twin.json's step block, from version 4: the twin's last step
// (contracts/twin.schema.json), and from version 5 its wait.
// Phase is null unless the outcome is diverged.
type StepRecord struct {
	Outcome       string           `json:"outcome"`
	From          StepSide         `json:"from"`
	To            StepSide         `json:"to"`
	Run           RunRef           `json:"run"`
	WorkerVersion string           `json:"worker_version"`
	AllowRestart  bool             `json:"allow_restart"`
	Phase         *string          `json:"phase"`
	Reconcile     StepReconcile    `json:"reconcile"`
	Pushed        []StepPush       `json:"pushed"`
	ReadyAfter    []StepReadyAfter `json:"ready_after"`
	Timings       StepTimings      `json:"timings"`
	StartedAt     string           `json:"started_at"`
	EndedAt       string           `json:"ended_at"`
	Findings      []StepFinding    `json:"findings"`
	// Wait is the step's wait, written by VerifyTwin after the record, or nil when it has
	// not run. No omitempty:
	// version 5 writes an explicit null, as step does, and a version 4 record, which has
	// no key, reads as nil.
	Wait *StepWait `json:"wait"`
}

// StepReconcile is containerlab's plan as the record keeps it, with each touched node's
// package declaration beside what containerlab reported, and the apply's time. Skipped,
// with no time, when the plan was empty (its lists empty) or the step was unchanged, whose
// run applies nothing (its lists still containerlab's plan as read).
type StepReconcile struct {
	Skipped          bool                `json:"skipped"`
	Added            []string            `json:"added"`
	Deleted          []string            `json:"deleted"`
	Recreated        []string            `json:"recreated"`
	Restarted        []string            `json:"restarted"`
	LinksAdded       []string            `json:"links_added"`
	EndpointsDeleted []string            `json:"endpoints_deleted"`
	Nodes            []StepReconcileNode `json:"nodes"`
	TookS            *float64            `json:"took_s,omitempty"`
}

// StepReconcileNode is one touched node: its package's declaration (nil for a created
// node, which no declaration covers), what containerlab reported and containerlab's reason.
type StepReconcileNode struct {
	Node     string  `json:"node"`
	Declared *string `json:"declared"`
	Reported string  `json:"reported"`
	Reason   string  `json:"reason,omitempty"`
}

// StepPush is one node of a step's push plan with why it was pushed and what came of it:
// landed, refused, failed or not_attempted, and the finding's identifier for a refused or
// failed push.
type StepPush struct {
	Node    string   `json:"node"`
	Reasons []string `json:"reasons"`
	Outcome string   `json:"outcome"`
	Rule    string   `json:"rule,omitempty"`
	TookS   *float64 `json:"took_s,omitempty"`
}

// StepReadyAfter is how long one awaited node took to answer its probe after the
// reconcile.
type StepReadyAfter struct {
	Node        string  `json:"node"`
	ReadyAfterS float64 `json:"ready_after_s"`
}

// StepTimings is each phase's duration in seconds. A phase the step did not
// reach is absent.
type StepTimings struct {
	ReconcileS *float64           `json:"reconcile_s,omitempty"`
	Readiness  map[string]float64 `json:"readiness,omitempty"`
	Push       map[string]float64 `json:"push,omitempty"`
	WholeS     float64            `json:"whole_s"`
}

// StepFinding is one of a diverged step's findings as the record keeps it: the
// identifier, the object and the message, and no content.
type StepFinding struct {
	Rule    string `json:"rule"`
	Object  string `json:"object"`
	Message string `json:"message"`
}

// How a step's wait ended.
// Settled: every assertion read from a node held at a read. Expired: the budget passed
// with every node read and an assertion still failing. Cancelled: the run was cancelled
// during the wait. Incomplete: the budget passed with a node unread, or the activity
// itself failed.
const (
	WaitSettled    = "settled"
	WaitExpired    = "expired"
	WaitCancelled  = "cancelled"
	WaitIncomplete = "incomplete"
)

// VerifyInput is what the step's wait needs that the lab host cannot read for itself:
// the run it waits for,
// the record's time the budget runs from (RFC 3339 UTC), so a retried attempt computes the
// same deadline, and the budget in seconds. The record, the staged bundle and the lab are
// read from the twin directory.
type VerifyInput struct {
	RunID   string `json:"run_id"`
	From    string `json:"from"`
	BudgetS int    `json:"budget_s"`
}

// StepWait is how the step's wait ended, as twin.json 5's step.wait keeps it
// (contracts/twin.schema.json): the outcome, the
// budget used, the reads made, the seconds from From to the read that settled or to the
// wait's end, and the assertions still failing at the last read, by identifier and object,
// with an unread node's operation.failed. Failing is empty when settled, and never content.
type StepWait struct {
	Outcome string        `json:"outcome"`
	BudgetS int           `json:"budget_s"`
	Reads   int           `json:"reads"`
	AfterS  float64       `json:"after_s"`
	From    string        `json:"from"`
	EndedAt string        `json:"ended_at"`
	Failing []StepFinding `json:"failing"`
}

// VerifyResult is the step's wait as the activity returns it: the wait, in every case a
// read began, a
// cancellation included, and whether it was written into the record, which happens only
// when the record's step names the run.
type VerifyResult struct {
	Wait     StepWait `json:"wait"`
	Recorded bool     `json:"recorded"`
	// Counts is the wait's last read counted by assertion kind, for a rehearsal's report
	// (015, research R-07). Nil when no read was kept, and when a retry returned the wait
	// the record already held, which keeps no counts; omitted when nil, so every recorded
	// history replays.
	Counts *VerifyCounts `json:"counts,omitempty"`
}

// VerifyCounts are a read's assertions and claims counted by kind, host_name,
// port_enabled, neighbor and record, each held, failed (absent too), skipped and unread:
// twin verify's own counts (contracts/verify.schema.json), which a rehearsal's stage
// carries as its verify (contracts/rehearsal.schema.json). It is the verify block's type,
// so the two are one shape and the wait's crosses in one assignment.
type VerifyCounts = findings.VerifyCounts
