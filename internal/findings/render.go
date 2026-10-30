package findings

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
)

// Operation names the command that produced a document. 020 moved five to the
// orchestrator (T035): intent.read, schema.check, stage.list, stage.plan and twin.rehearse
// name its documents, never the core's.
const (
	OpCompile       = "twin.compile"
	OpPSPValidate   = "psp.validate"
	OpTwinCreate    = "twin.create"
	OpTwinProvision = "twin.provision"
	OpTwinDestroy   = "twin.destroy"
	OpTwinShow      = "twin.show"

	// M11: a twin stepped to another stage of its proposed change (014), and its dry
	// run.
	OpTwinStep = "twin.step"

	// M12: the twin read and verified against intent, with no run.
	OpTwinVerify = "twin.verify"

	// 020: a run read and interrupted by its identity, and two snapshots' bundles
	// compared with no twin (data-model §1).
	OpRunRead      = "run.read"
	OpRunInterrupt = "run.interrupt"
	OpTwinDiff     = "twin.diff"
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
	// Stage is --stage as given, <branch>/<label> (014): on twin create and intent read
	// the reference supplied, on twin step the target once known. Branch and At then
	// carry the reference it resolved to, once it resolved.
	Stage string `json:"stage,omitempty"`
	// Scope is the scope a read was made under, tag:<name> (017): the request's, or the
	// server's default when the request named none, named from the moment it is resolved,
	// before the packages load. Absent on an operation that reads under none, and on a
	// request refused before its scope was resolved.
	Scope string `json:"scope,omitempty"`
	// Snapshot is --snapshot as given (018), a snapshot id or the path of the file the
	// request carried, on twin compile and twin create --snapshot.
	Snapshot string `json:"snapshot,omitempty"`
}

// Where a stage's at came from (stages.schema.json, $defs/at_source).
const (
	AtSourceGiven       = "given"        // as_of written on the mark, verbatim
	AtSourceWritten     = "written"      // the mark's own write stamp, its label's updated_at
	AtSourceBranchPoint = "branch_point" // the source branch's branched_from, read on the default branch
	AtSourceHead        = "head"         // the source branch's latest stamp or intent event plus one microsecond
)

// StageChangeRef names a proposed change as twin.json 6 records it: its id and its source
// branch.
type StageChangeRef struct {
	ID     string `json:"id"`
	Branch string `json:"branch"`
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
}

// DryRunNode is one node a real run would deploy: a device of intent, or a probe's host
// (016).
type DryRunNode struct {
	Name  string `json:"name"`
	Image string `json:"image"`
	// PSP is the device's support package; nil, written null, on a host, which has none.
	PSP *string `json:"psp"`
	// Probe is what a host is, as twin.json 11 records it: its probe, its endpoint, its
	// format and its probe package. Nil, and not written, on a device.
	Probe    *DryRunProbe `json:"probe,omitempty"`
	MemoryMB int          `json:"memory_mb"`
	// Artifact is what would be pushed to this node, as the bundle's manifest names it
	// (M5). Every M5 bundle carries one per device, so the contract requires it
	// there; it is a pointer so that a document built from an M2-era bundle, which
	// twin provision refuses as bundle.version.unsupported, marshals without it, and a
	// host, to which nothing is pushed, carries none (016).
	Artifact *DryRunArtifact `json:"artifact,omitempty"`
}

// DryRunProbe is a host's probe in a dry run (016): the probe it is an endpoint of, which
// endpoint, the probe's format and the probe package the host is built with.
type DryRunProbe struct {
	Name     string        `json:"name"`
	Endpoint string        `json:"endpoint"`
	Format   string        `json:"format"`
	Package  DryRunPackage `json:"package"`
}

// DryRunPackage names a probe package, as the manifest does: its id and whether it is the
// shipped one.
type DryRunPackage struct {
	ID     string `json:"id"`
	Source string `json:"source"`
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

// Kinds of twin twin show reports. 019 put snapshot in place of M4's pinned, frozen and
// following: a twin is frozen at its snapshot, and nothing rebuilds it but the operator
// (D-062).
const (
	ShowKindNone       = "none"
	ShowKindSnapshot   = "snapshot" // a twin from intent or a snapshot: its snapshot, or none for a record naming none
	ShowKindFromBundle = "from_bundle"

	// M11: a twin whose last step failed or was cancelled after the host was touched.
	ShowKindDiverged = "diverged"
)

// Whether twin show reached the workflow service.
const (
	ShowServiceOK          = "ok"
	ShowServiceUnreachable = "unreachable"
)

// ShowBlock is what twin show says about the twin: the host, the record, the kind and the
// runs in flight, from containerlab, twin.json and the workflow service. 019 removed M4's
// following and last check.
// One struct renders both the text and the
// JSON, so the two cannot disagree.
type ShowBlock struct {
	Host     ShowHost    `json:"host"`
	Record   *ShowRecord `json:"record,omitempty"`
	Kind     string      `json:"kind"`
	InFlight []ShowRun   `json:"in_flight"`
	Service  string      `json:"service"`
	Notes    []string    `json:"notes"`
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
	Branch     string  `json:"branch"`
	At         string  `json:"at,omitempty"`
	SnapshotID *string `json:"snapshot_id"` // twin.json 9's (018); null for a 9 naming none and a record of 8 or earlier
	BundleID   string  `json:"bundle_id"`
	SchemaHash string  `json:"schema_hash"`
	// Scope and Mapping are the record's provenance as twin.json 8 names it (017): the scope
	// the read was made under and the mapping that read it, in place of the generics
	// contract's version. Both are absent for a record of 7 or earlier, which names neither.
	Scope   string       `json:"scope,omitempty"`
	Mapping *ShowMapping `json:"mapping,omitempty"`
	// ObservedAt is null when no read took place, as in twin.json.
	ObservedAt     *string `json:"observed_at"`
	ObservedAtNote string  `json:"observed_at_note,omitempty"`
	Source         string  `json:"source"` // intent, bundle, or snapshot for a twin create --snapshot built (018)
	Run            ShowRef `json:"run"`
	WorkerVersion  string  `json:"worker_version"`
	RecordedAt     string  `json:"recorded_at"`
	Nodes          int     `json:"nodes"`
	// Stage is the stage a version 6 record names (014), absent when it names none and
	// for an earlier record.
	Stage *ShowStage `json:"stage,omitempty"`
	// Rehearsal is the rehearsal run whose baseline the twin is, as a version 7 record names
	// it (015); absent when it names none and for an earlier record, as Stage is, so that a
	// document of no rehearsal is the one M4 to M7's contracts accept.
	Rehearsal *ShowRef `json:"rehearsal,omitempty"`
	// State is a version 4 record's state, ready or diverged; absent for an earlier record,
	// which has none.
	State string `json:"state,omitempty"`
	// Step is a version 4 record's last step as twin show shows it; absent when the record
	// has none.
	Step *ShowStep `json:"step,omitempty"`
}

// ShowMapping is the reader that produced the twin's CTM and the version of the model it
// read, as the record's provenance.mapping names them (017).
type ShowMapping struct {
	Reader  string `json:"reader"`
	Model   string `json:"model"`
	Version string `json:"version"`
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

// ShowStage is the stage a twin was created from or stepped to, as twin.json 6 records it
// (014): its proposed change by id and source branch, its label, description and where its
// at came from. The at is the record's own.
type ShowStage struct {
	ProposedChange StageChangeRef `json:"proposed_change"`
	Label          string         `json:"label"`
	Description    string         `json:"description"`
	AtSource       string         `json:"at_source"`
}

// Ref is the stage as a reference names it: <branch>/<label>.
func (s ShowStage) Ref() string { return s.ProposedChange.Branch + "/" + s.Label }

// ShowRef is a run's identity.
type ShowRef struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
}

// ShowRun is a run in flight and the step its history has reached. A rehearsal's child run
// was its Child until 020, when the rehearsal left the core's worker (T034, T035).
type ShowRun struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
	Step       string `json:"step"`
}

// Document is the machine-readable result of one operation. M1's operations conform to
// M1's findings contract; M2's twin create, provision and destroy to M2's, which is
// additive, so every M1 document satisfies both. M4's operations — following on create
// and destroy, dry_run.follow, and twin show — conform to M4's, additive again; 019
// removed the following block and dry_run.follow, pre-1.0, under the same version. M5's
// operations — the artifact on a dry run's, a twin's and a shown host's nodes,
// `pushed_in_s`, and the step `push` — conform to M5's, with show.schema.json added as a
// resource under its $id. 014's record.stage in the show block conforms to the current
// contract, with stages.schema.json added under its $id as well; its subject.stage, stage
// block and the stages and plan blocks, 015's rehearsal block, and intent read's and
// schema check's were the five operations' 020 moved to the orchestrator (T035), whose
// documents they are. Each
// milestone's copy is kept under testdata/contracts/, and the current contract is
// contracts/findings.schema.json. No field of any block carries a byte of artifact content.
type Document struct {
	FindingsVersion string   `json:"findings_version"`
	Operation       string   `json:"operation"`
	Status          Status   `json:"status"`
	Subject         *Subject `json:"subject,omitempty"`
	SnapshotID      string   `json:"snapshot_id,omitempty"` // 018: the snapshot taken, read or stepped to, beside the bundle
	BundleID        string   `json:"bundle_id,omitempty"`
	// SnapshotFrom, SnapshotTo, BundleFrom and BundleTo are twin.diff's two sides (020): each
	// snapshot once resolved, and the bundle it compiled to once filed.
	SnapshotFrom string        `json:"snapshot_from,omitempty"`
	SnapshotTo   string        `json:"snapshot_to,omitempty"`
	BundleFrom   string        `json:"bundle_from,omitempty"`
	BundleTo     string        `json:"bundle_to,omitempty"`
	Twin         *TwinBlock    `json:"twin,omitempty"`
	Cleanup      *CleanupBlock `json:"cleanup,omitempty"`
	DryRun       *DryRunBlock  `json:"dry_run,omitempty"`
	Show         *ShowBlock    `json:"show,omitempty"`
	// Step is twin step's block, on the dry run and the run (M11), and twin.diff's, the pair
	// alone (020; StepBlock.Pair).
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
// the shape stage plan also prints under each stage's line.
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
	// (stages.schema.json, $defs/step).
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
	// WaitCounts is the wait's last read counted by kind, as twin verify counts its block
	// (015): nil on the dry run, before the run closed, and when the wait made no read.
	WaitCounts *VerifyCounts `json:"wait_counts,omitempty"`
	// Loss is what the step's probe flows lost (016), written always: null on the dry run,
	// before the run closed and when the run ended before its flows were read.
	Loss *StepLoss `json:"loss"`
	// Pair, when set, is twin.diff's block (020): the step between two snapshots' bundles as
	// internal/step marshals a pair (stages.schema.json, $defs/step), which is written alone,
	// in place of every field above. twin.diff touches no lab, so it has no side's record, no
	// containerlab plan and no push plan to write.
	Pair json.RawMessage `json:"-"`
}

// DiffBlock is twin.diff's step block (020): pair, as internal/step marshals it.
func DiffBlock(pair json.RawMessage) *StepBlock {
	return &StepBlock{Pair: pair}
}

// MarshalJSON writes an empty push plan, and a run's empty pushes and awaited nodes, as []
// rather than null. StepRunBlock has no MarshalJSON of its own on purpose: embedded, it
// would be promoted to this one's alias and marshal the run fields alone.
func (b StepBlock) MarshalJSON() ([]byte, error) {
	if b.Pair != nil {
		return b.Pair, nil
	}
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

// UnmarshalJSON reads twin step's block, or twin.diff's pair (020), which has no diff of its
// own and is kept as it came, in Pair.
func (b *StepBlock) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return nil
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(data, &keys); err != nil {
		return err
	}
	if _, ok := keys["diff"]; !ok {
		*b = StepBlock{Pair: append(json.RawMessage(nil), data...)}
		return nil
	}
	type plain StepBlock
	return json.Unmarshal(data, (*plain)(b))
}

// StepLoss is the step document's loss (contracts/step.schema.json, $defs/loss), as
// twin.json 11's step.loss keeps it: the basis, container, one entry per probe both bundles
// carry, and the probes the target adds and drops, which no flow measured across the step.
type StepLoss struct {
	Basis   string          `json:"basis"`
	Probes  []StepProbeLoss `json:"probes"`
	Added   []string        `json:"added"`
	Dropped []string        `json:"dropped"`
}

// MarshalJSON writes every list, [] for none.
func (l StepLoss) MarshalJSON() ([]byte, error) {
	type plain StepLoss
	if l.Probes == nil {
		l.Probes = []StepProbeLoss{}
	}
	if l.Added == nil {
		l.Added = []string{}
	}
	if l.Dropped == nil {
		l.Dropped = []string{}
	}
	return json.Marshal(plain(l))
}

// StepProbeLoss is one probe's flow across the step: the containers it ran from and to, how
// it ended, the requests sent and lost and the longest run of unanswered ones in seconds,
// and the rule and message of a flow not started or not read. Never a configuration line.
type StepProbeLoss struct {
	Probe       string  `json:"probe"`
	From        string  `json:"from"`
	To          string  `json:"to"`
	Outcome     string  `json:"outcome"`
	Sent        int     `json:"sent"`
	Lost        int     `json:"lost"`
	LongestGapS float64 `json:"longest_gap_s"`
	Rule        string  `json:"rule,omitempty"`
	Message     string  `json:"message,omitempty"`
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

// StepSideBlock is one side of a step: the stage, the snapshot when the side names one
// (018), the bundle and the pinned at, verbatim, and for the target the branch it resolved
// to. A from side whose record names no snapshot, a record of 8, carries none.
type StepSideBlock struct {
	Stage      *ShowStage `json:"stage"`
	SnapshotID string     `json:"snapshot_id,omitempty"`
	BundleID   string     `json:"bundle_id"`
	At         string     `json:"at"`
	Branch     string     `json:"branch,omitempty"`
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
