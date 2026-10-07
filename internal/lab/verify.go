package lab

import (
	"context"
	"errors"
	"fmt"
	"math"
	"time"

	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// VerifyTwin is the step's wait after its record: it reads the twin against the staged
// bundle at once,
// then again every verify.ReadInterval, until every assertion read from a node holds
// (settled) or the budget, counted from in.From, has passed (expired, or incomplete with a
// node unread), and writes how it ended into the record's step block. It changes nothing on
// a node, and no Fylgja operation reads what it writes.
//
//   - It heartbeats for its whole life: it can run for the budget (Constitution VIII), and a
//     heartbeat is how a cancellation reaches it.
//   - A retry that finds this run's wait already written returns it, reading no node and
//     asking containerlab nothing.
//   - A record, a staged bundle or a manifest it cannot read is operation.failed, not
//     retried: the run records the wait incomplete.
//   - A lab containerlab cannot inspect is read at the record's addresses alone. A node a
//     read could not dial, because containerlab did not report it or it had no address, is
//     looked up again before the next read (verify.WaitOptions.Lab).
//   - The wait is written only when the record's step names in.RunID: a record the step
//     could not write, or another run's, is left as it is, and the result says so
//     (Recorded false). One that names the run but will not take the wait, because it
//     cannot be read again or will not write, is operation.failed, not retried, so the run
//     says the wait could not complete. recorded_at does not move.
//   - A cancellation the run asked for (twin destroy during the pause) ends the wait
//     cancelled, written and returned as a result, never as an error, so the run ends as its
//     record says. An attempt cut short otherwise writes nothing and fails. One cut
//     by a lost heartbeat or the worker stopping is retried inside the one window, from the
//     same in.From. The end of the window is not retried, since VerifyOptions sets
//     the schedule-to-close equal to the start-to-close, and the run says the wait could not
//     complete, with the timeout's finding, and the record's wait stays null.
func (a *Activities) VerifyTwin(ctx context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
	stop := heartbeat(ctx)
	defer stop()

	path := a.Paths.TwinJSON
	failed := func(object, format string, args ...any) (wire.VerifyResult, error) {
		return wire.VerifyResult{}, StepFailure(findings.StepObserve, findings.RuleOperationFailed, object,
			fmt.Sprintf(format, args...))
	}
	rec, err := ReadRecord(path)
	if err != nil {
		return failed(path, "reading the twin's record for the step's wait: %v", err)
	}
	if mine(rec, in.RunID) && rec.Step.Wait != nil {
		return wire.VerifyResult{Wait: *rec.Step.Wait, Recorded: true}, nil
	}
	from, err := time.Parse(time.RFC3339Nano, in.From)
	if err != nil {
		return failed(in.RunID, "the step's wait runs from its record's time, and %q is not RFC 3339", in.From)
	}
	staged := a.Paths.TwinBundle
	m, err := readManifest(staged)
	if err != nil {
		return failed(staged, "reading the staged bundle: %v", err)
	}
	stagedID, err := bundle.IDOfDir(staged)
	if err != nil {
		return failed(staged, "reading the staged bundle: %v", err)
	}
	assertions, err := verify.Derive(m)
	if err != nil {
		// The manifest the step staged is the compiler's, so this is a defect, not a finding.
		object := staged
		if me := (*verify.ManifestError)(nil); errors.As(err, &me) {
			object = me.Object
		}
		return failed(object, "%v", err)
	}
	inspect := func(ctx context.Context) ([]wire.LabNode, error) {
		state, err := a.Clab.InspectAll(ctx)
		if err != nil {
			return nil, err
		}
		return append([]wire.LabNode{}, state.Nodes...), nil
	}
	labNodes, err := inspect(ctx)
	if err != nil {
		a.logger().Warn("inspecting the lab for the step's wait failed: each node is read at the record's address",
			"lab", LabName, "error", err)
	}

	reader := a.Reader
	if reader == nil {
		reader = GNMIReader{Log: a.logger()}
	}
	now := a.waitNow
	if now == nil {
		now = time.Now
	}
	vin := verify.Input{Manifest: m, StagedID: stagedID, Record: rec, Lab: labNodes, Packages: a.Registry,
		Reader: reader, Getenv: a.getenv(), Now: now}
	w := verify.Wait(ctx, vin, assertions, verify.WaitOptions{Budget: time.Duration(in.BudgetS) * time.Second, From: from,
		Sleep: a.waitSleep, Now: now, Lab: inspect})
	if w.Outcome == verify.WaitCancelled && !temporal.IsCanceledError(context.Cause(ctx)) {
		return wire.VerifyResult{}, interrupted(ctx, findings.StepObserve, findings.RuleOperationFailed, path, "the step's wait")
	}

	wait := wire.StepWait{Outcome: w.Outcome, BudgetS: in.BudgetS, Reads: w.Reads, AfterS: math.Round(w.AfterS*1000) / 1000,
		From: in.From, EndedAt: now().UTC().Format(time.RFC3339Nano), Failing: failing(w)}
	if w.Outcome == verify.WaitExpired && !w.Last.AllRead() {
		// What an unread node at expiry means is the caller's: for the step, the
		// wait could not complete.
		wait.Outcome = wire.WaitIncomplete
	}
	a.logger().Info("the step's wait ended", "run", in.RunID, "outcome", wait.Outcome, "reads", wait.Reads,
		"after_s", wait.AfterS, "failing", len(wait.Failing))
	recorded, err := a.recordWait(path, in.RunID, mine(rec, in.RunID), wait)
	if err != nil {
		return failed(path, "the step's wait is not recorded: %v", err)
	}
	return wire.VerifyResult{Wait: wait, Recorded: recorded}, nil
}

// failing is what still fails at the wait's last read, as the record keeps it: each failed or
// absent assertion and each unread node's operation.failed, by identifier, object and
// message.
// The record's claims are never waited on, so verify.record.holds is
// not among them, and a wait that settled has nothing else: it is empty, never null.
func failing(w verify.WaitResult) []wire.StepFinding {
	out := []wire.StepFinding{}
	for _, f := range w.Last.Findings() {
		if f.Rule == findings.RuleVerifyRecordHolds {
			continue
		}
		out = append(out, wire.StepFinding{Rule: f.Rule, Object: f.Object, Message: f.Message})
	}
	return out
}

// recordWait writes the wait into the record's step block, read again just before, when that
// step is runID's, and says whether it did. A record that is another run's keeps what it
// holds, as does one that cannot be read again when the record the wait began with was not
// runID's either: the wait is still the run's result, and the record's wait stays null.
// named says the record the wait began with was runID's: then a record that
// cannot be read again, or will not write, is the error, since the run's record would
// otherwise say the wait never ran while the run's result says it did.
func (a *Activities) recordWait(path, runID string, named bool, wait wire.StepWait) (bool, error) {
	rec, err := ReadRecord(path)
	if err != nil {
		if named {
			return false, err
		}
		a.logger().Warn("the step's wait is not recorded: the twin's record cannot be read", "run", runID, "error", err)
		return false, nil
	}
	if !mine(rec, runID) {
		return false, nil
	}
	rec.Step.Wait = &wait
	if err := WriteRecord(path, rec); err != nil {
		return false, err
	}
	return true, nil
}

// mine says whether the record's last step is the step run runID.
func mine(rec wire.TwinRecord, runID string) bool {
	s := rec.Step
	return runID != "" && s != nil && s.Run.WorkflowID == wire.StepWorkflowID && s.Run.RunID == runID
}
