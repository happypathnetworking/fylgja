package provision

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// ControlActivities run the read and compile stages inside a run, and start and stop
// following. They need Infrahub, the bundle store and the workflow service, not the
// containers, which is why they live here and not in internal/lab.
type ControlActivities struct {
	Store  bundle.Store
	Paths  lab.Paths
	PSPDir string // the worker's override directory, empty for embedded packages only
	// Client is the worker's connection to the workflow service, for the following
	// activities.
	Client client.Client
}

// Names maps the control activities' names to their methods, for the worker to register
// by name.
func (c *ControlActivities) Names() map[string]any {
	return map[string]any{
		wire.ActReadIntent: c.ReadIntent,
		wire.ActCompile:    c.Compile,
		ActRunsInFlight:    c.RunsInFlight,
		ActStartFollowing:  c.StartFollowing,
		ActStopFollowing:   c.StopFollowing,
	}
}

// reconcileWorkflowType is the name the worker registers Reconcile under, which the
// Schedule's action starts by.
const reconcileWorkflowType = "Reconcile"

// RunsInFlight names the operator's runs in flight, so a check skips rather than has its
// rebuild refused. A run that is absent or closed is "". A service error is returned as it is,
// so it is retried.
func (c *ControlActivities) RunsInFlight(ctx context.Context) (RunsInFlightResult, error) {
	var res RunsInFlightResult
	for _, run := range []struct {
		workflowID string
		runID      *string
	}{{WorkflowProvision, &res.Provision}, {WorkflowDestroy, &res.Destroy}} {
		desc, err := c.Client.DescribeWorkflowExecution(ctx, run.workflowID, "")
		var notFound *serviceerror.NotFound
		switch {
		case errors.As(err, &notFound):
			continue
		case err != nil:
			return RunsInFlightResult{}, err
		}
		info := desc.GetWorkflowExecutionInfo()
		if info.GetStatus() == enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING {
			*run.runID = info.GetExecution().GetRunId()
		}
	}
	return res, nil
}

// StartFollowing creates Schedule fylgja-follow: a check of the branch every interval, one
// at a time, never replaying intervals missed while the service was down. A
// Schedule that exists is deleted first, so a retry or a replacing create converges on this
// one. The Schedule holds the interval and the branch and nothing else: no memo, no search
// attribute, no credential.
func (c *ControlActivities) StartFollowing(ctx context.Context, in StartFollowingInput) (FollowingResult, error) {
	schedules := c.Client.ScheduleClient()
	err := schedules.GetHandle(ctx, FollowScheduleID).Delete(ctx)
	var notFound *serviceerror.NotFound
	if err != nil && !errors.As(err, &notFound) {
		return FollowingResult{}, fmt.Errorf("deleting the schedule it replaces: %w", err)
	}
	// The error is returned as it is: follow.start.failed's message names the schedule.
	if _, err = schedules.Create(ctx, followScheduleOptions(in)); err != nil {
		return FollowingResult{}, err
	}
	return FollowingResult{Branch: in.Branch, IntervalS: in.IntervalS, ScheduleID: FollowScheduleID}, nil
}

// followScheduleOptions is Schedule fylgja-follow for in.
func followScheduleOptions(in StartFollowingInput) client.ScheduleOptions {
	return client.ScheduleOptions{
		ID: FollowScheduleID,
		Spec: client.ScheduleSpec{
			Intervals: []client.ScheduleIntervalSpec{{Every: seconds(in.IntervalS)}},
			Jitter:    FollowJitter,
		},
		Action: &client.ScheduleWorkflowAction{
			ID:        WorkflowReconcile,
			Workflow:  reconcileWorkflowType,
			Args:      []any{ReconcileInput{Branch: in.Branch, Version: in.Version}},
			TaskQueue: TaskQueue,
		},
		Overlap:       enumspb.SCHEDULE_OVERLAP_POLICY_SKIP,
		CatchupWindow: FollowCatchupWindow,
	}
}

// StopFollowing deletes Schedule fylgja-follow and says which branch it followed. An
// absent Schedule is Deleted false, not an error. It does not cancel a check in flight:
// inside Reconcile its caller is that check, and inside a run's stop step no check can
// touch a host the host check found clear.
func (c *ControlActivities) StopFollowing(ctx context.Context) (StopFollowingResult, error) {
	handle := c.Client.ScheduleClient().GetHandle(ctx, FollowScheduleID)
	desc, err := handle.Describe(ctx)
	var notFound *serviceerror.NotFound
	switch {
	case errors.As(err, &notFound):
		return StopFollowingResult{}, nil
	case err != nil:
		return StopFollowingResult{}, fmt.Errorf("describing it: %w", err)
	}
	branch := followedBranch(desc)
	if err := handle.Delete(ctx); err != nil {
		if errors.As(err, &notFound) {
			return StopFollowingResult{}, nil
		}
		// As it is: follow.stop.failed's message names the schedule and the delete.
		return StopFollowingResult{}, err
	}
	return StopFollowingResult{Deleted: true, Branch: branch}, nil
}

// followedBranch is the branch a Schedule's action checks, decoded from the action's first
// arg, which Describe returns as a payload. "" when it cannot be
// read.
func followedBranch(desc *client.ScheduleDescription) string {
	action, ok := desc.Schedule.Action.(*client.ScheduleWorkflowAction)
	if !ok || len(action.Args) == 0 {
		return ""
	}
	var in ReconcileInput
	switch arg := action.Args[0].(type) {
	case *commonpb.Payload:
		if converter.GetDefaultDataConverter().FromPayload(arg, &in) != nil {
			return ""
		}
	case ReconcileInput:
		in = arg
	}
	return in.Branch
}

// ReadIntent reads the branch on the worker through the pipeline `intent read` runs
// (internal/stage), so a create that stops here reports M1's findings under M1's
// identifiers. The CTM is written to bundles/.reads/<run id>.ctm.json until
// compile has named its bundle.
//
// A rejection is a result, not an error. A read that could not run at all — Infrahub
// unreachable, its address or credential unset — fails as operation.failed, which no
// retry helps; the intent client redacts its errors where it makes them.
func (c *ControlActivities) ReadIntent(ctx context.Context, in ReadIntentInput) (ReadIntentResult, error) {
	reg, refused, err := c.registry()
	if err != nil {
		return ReadIntentResult{}, operationFailed(findings.StepRead, "support packages", err)
	}
	if refused != nil {
		return ReadIntentResult{Findings: refused.AtStep(findings.StepRead)}, nil
	}

	// Captured before the first request, so observed_at is never later than anything the
	// read could have seen.
	observedAt := time.Now().UTC().Format(stage.ObservedAtFormat)
	snapshot, list, err := stage.Read(ctx, in.Branch, in.At, reg, observedAt)
	if errors.Is(err, intent.ErrBranchNotFound) {
		return ReadIntentResult{}, branchNotFound("branch "+in.Branch, err)
	}
	if err != nil {
		return ReadIntentResult{}, operationFailed(findings.StepRead, "branch "+in.Branch, err)
	}
	res := ReadIntentResult{ObservedAt: observedAt, Findings: list.AtStep(findings.StepRead)}
	if snapshot == nil {
		return res, nil
	}

	path := filepath.Join(c.readsDir(), activity.GetInfo(ctx).WorkflowExecution.RunID+".ctm.json")
	if err := writeCTM(snapshot, path); err != nil {
		return ReadIntentResult{}, operationFailed(findings.StepRead, path, err)
	}
	res.CTMPath = path
	return res, nil
}

// Compile compiles the read's CTM through the pipeline `twin compile` runs, files the
// bundle in the store under its identity (reused, never duplicated) with the CTM
// beside it, and returns the stored copy's absolute path, which is what crosses the queue.
// A corrupt store entry blocking the filing is bundle.id.mismatch, a rejection.
//
// The read's transient copy under bundles/.reads/ is removed on every exit once it has
// been read: each exit ends the run — a filing, a rejection, or a failure
// no retry helps — so nothing reads it again. Only a .reads file is removed, never a CTM
// the activity was pointed at elsewhere. A copy that cannot be removed fails a filing that
// otherwise succeeded, so the run says so; on an exit that already reports a rejection or
// a failure, that report stands and the copy is left. A cancellation between the read and
// the compile steps leaves the copy too: the compile never runs, and a run cancelled before
// the host check schedules nothing more — a window as narrow as the compile step's own
// retry window.
func (c *ControlActivities) Compile(ctx context.Context, in CompileInput) (res CompileResult, err error) {
	snapshot, err := ctm.Load(in.CTMPath)
	if err != nil {
		return CompileResult{}, operationFailed(findings.StepCompile, in.CTMPath, err)
	}
	defer func() {
		if rmErr := c.discardRead(in.CTMPath); rmErr != nil && err == nil && !res.Findings.Rejected() {
			res, err = CompileResult{}, operationFailed(findings.StepCompile, in.CTMPath, rmErr)
		}
	}()
	reg, refused, err := c.registry()
	if err != nil {
		return CompileResult{}, operationFailed(findings.StepCompile, "support packages", err)
	}
	if refused != nil {
		return CompileResult{Findings: refused.AtStep(findings.StepCompile)}, nil
	}

	files, id, list := stage.Compile(snapshot, reg)
	list = list.AtStep(findings.StepCompile)
	if list.Rejected() {
		return CompileResult{Findings: list}, nil
	}

	stored, err := bundle.PutFiles(ctx, c.Store, files, c.Paths.Bundles)
	var mismatch *bundle.ErrIDMismatch
	switch {
	case errors.As(err, &mismatch):
		list.AddStep(findings.Rejection, findings.StepCompile, findings.RuleBundleIDMismatch, mismatch.Path,
			StoreMismatchMessage(mismatch, id))
		return CompileResult{BundleID: id, Findings: list}, nil
	case err != nil:
		return CompileResult{}, operationFailed(findings.StepCompile, c.Paths.Bundles, err)
	case stored != id:
		return CompileResult{}, operationFailed(findings.StepCompile, c.Paths.Bundles,
			fmt.Errorf("the written bundle hashes to %s, but compiled to %s", stored, id))
	}

	if err := c.Store.PutCTM(ctx, id, in.CTMPath); err != nil {
		return CompileResult{}, operationFailed(findings.StepCompile, in.CTMPath, err)
	}
	// The read's CTM is now filed beside its bundle; its transient copy has served, and the
	// deferred removal takes it.
	return CompileResult{BundleID: id, BundlePath: c.Store.Path(id), Findings: list}, nil
}

// StoreMismatchMessage is bundle.id.mismatch's message for a corrupt store entry that
// blocks filing bundle id: the entry's path, what it claims and what it hashes to. Shared
// with the commands that file a bundle before any run, so both word it alike.
func StoreMismatchMessage(m *bundle.ErrIDMismatch, id string) string {
	return fmt.Sprintf("store entry %s hashes to %s, not %s, so bundle %s cannot be filed", m.Path, m.Got, m.Want, id)
}

func (c *ControlActivities) readsDir() string {
	return filepath.Join(c.Paths.Bundles, ".reads")
}

// discardRead removes a read's transient CTM and nothing else: a path outside
// bundles/.reads/ is left where it is, and a copy already gone is not an error.
func (c *ControlActivities) discardRead(path string) error {
	if filepath.Dir(path) != c.readsDir() {
		return nil
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return nil
}

// registry loads this worker's packages. A package `psp validate` rejects is reported
// under its own psp.* findings, as the stage commands report it, rather than as a failure
// to run. The worker refuses to start with one, so this is reached only if the
// override directory changed underneath a running worker.
func (c *ControlActivities) registry() (*psp.Registry, findings.List, error) {
	reg, err := psp.Load(c.PSPDir)
	var invalid *psp.InvalidError
	if errors.As(err, &invalid) {
		return nil, invalid.Findings, nil
	}
	return reg, nil, err
}

// operationFailed is a step that could not run: exit 2, no retry.
func operationFailed(step, object string, err error) error {
	return lab.StepFailure(step, findings.RuleOperationFailed, object, err.Error())
}

// BranchNotFoundType is the error type of a read Infrahub refused because the branch does
// not exist. Its finding is operation.failed's, word for word, so a create reports an
// unknown branch as M1–M3 did; the type is what lets a following check end
// rejected rather than error. Like HeartbeatLostType it is not a rule.
const BranchNotFoundType = "BranchNotFound"

// branchNotFound is operationFailed at step read under BranchNotFoundType.
func branchNotFound(object string, err error) error {
	f := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: object,
		Message: err.Error(), Step: findings.StepRead}
	return temporal.NewNonRetryableApplicationError(f.Message, BranchNotFoundType, nil, f)
}

// writeCTM writes a CTM atomically: a reader sees the whole file or none.
func writeCTM(c *ctm.CTM, path string) error {
	b, err := ctm.Marshal(c)
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".fylgja-ctm-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(b); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
