package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"errors"
	"fmt"
	"strings"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// teardown runs DestroyLab under a teardown budget, awaits it, and records what it did.
// It is the first half of every cleanup: a provisioning run's after a failure or a
// cancellation, and the whole point of a destroy run. A teardown that fails leaves the lab
// in Remaining, so the report says what is still on the host.
func teardown(ctx workflow.Context, destroyTimeoutS int, c *CleanupResult, list *findings.List) {
	var out wire.DestroyLabResult
	err := execute(ctx, DestroyOptions(destroyTimeoutS), wire.ActDestroyLab, &out,
		wire.DestroyLabInput{DestroyTimeoutS: destroyTimeoutS})
	lab := "lab " + wire.LabName
	switch {
	case err != nil:
		f := failureFinding(err, findings.StepTeardown, findings.RuleCleanupIncomplete, lab)
		if !strings.Contains(f.Message, wire.ClearLabCommand) {
			f.Message += "; clear it with: " + wire.ClearLabCommand
		}
		*list = append(*list, f)
		c.Teardown = CleanupFailed
		c.Remaining = append(c.Remaining, lab)
	case out.Removed:
		c.Teardown = CleanupDone
		c.Removed = append(c.Removed, fmt.Sprintf("%s (%s)", lab, plural(out.Containers, "container")))
	default:
		c.Teardown = CleanupNothing
	}
}

// unstage runs UnstageTwin, awaits it, and records what it did: the second half of every
// cleanup, run whether or not the teardown succeeded. twinDir is the twin directory's path
// on the worker when the run knows it (a provisioning run that staged), and empty otherwise.
func unstage(ctx workflow.Context, twinDir string, c *CleanupResult, list *findings.List) {
	var out wire.UnstageResult
	err := execute(ctx, UnstageOptions(), wire.ActUnstageTwin, &out)
	switch {
	case err != nil:
		const dir = "twin directory"
		f := failureFinding(err, findings.StepUnstage, findings.RuleCleanupIncomplete, dir)
		c.Unstage = CleanupFailed
		if f.Object == dir {
			// The unstage never answered — it timed out, or its worker was lost — so nothing on
			// the worker said what remains or how to clear it. Say it here.
			where := dir
			if twinDir != "" {
				where, f.Object = dir+" "+twinDir, twinDir
			}
			f.Message += "; the " + where + " may remain: run fylgja twin destroy again once a worker is serving task queue " + TaskQueue
			c.Remaining = append(c.Remaining, where)
		} else {
			c.Remaining = append(c.Remaining, dir+" "+f.Object)
		}
		*list = append(*list, f)
	case out.Removed:
		c.Unstage = CleanupDone
		c.Removed = append(c.Removed, "twin directory "+out.Path)
	default:
		c.Unstage = CleanupNothing
	}
}

// failureFinding is the finding an activity failure is reported under. An activity that
// fails for a reason retrying cannot help, or that was cut short by a lost heartbeat,
// carries its finding as the ApplicationError's detail (lab.StepFailure). Any other failure
// — a timeout, a worker that died, retries exhausted — is reported under the rule the caller
// gives for the step, with the underlying error's message; a heartbeat timeout is named for
// what it says about the worker.
func failureFinding(err error, step, rule, object string) findings.Finding {
	var appErr *temporal.ApplicationError
	if errors.As(err, &appErr) && appErr.HasDetails() {
		var f findings.Finding
		if appErr.Details(&f) == nil && f.Rule != "" {
			if f.Step == "" {
				f.Step = step
			}
			return f
		}
	}
	message := activityMessage(err)
	var timeout *temporal.TimeoutError
	if errors.As(err, &timeout) && timeout.TimeoutType() == enumspb.TIMEOUT_TYPE_HEARTBEAT {
		message = "no heartbeat from the worker reached the workflow service within the heartbeat timeout, so the attempt was " +
			"presumed lost: the worker was stopped or killed, or the host was too loaded for it to heartbeat"
	}
	return findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Message: message, Step: step}
}

// activityMessage is what an activity's failure says, without the ActivityError wrapping.
// An ApplicationError's text still carries its type and retryability, as M2's findings
// always have.
func activityMessage(err error) string {
	var actErr *temporal.ActivityError
	if errors.As(err, &actErr) && actErr.Unwrap() != nil {
		return actErr.Unwrap().Error()
	}
	return err.Error()
}

// causeMessage is an activity's or child's failure as the M4 messages quote it: the
// ApplicationError's own message, without the type and retryability the SDK appends, so a
// cause reads as the activity worded it (contracts/cli.md, "(<err>)").
func causeMessage(err error) string {
	var appErr *temporal.ApplicationError
	if errors.As(err, &appErr) {
		return appErr.Message()
	}
	return activityMessage(err)
}

// plural counts a noun: "1 container", "3 containers".
func plural(n int, noun string) string {
	if n == 1 {
		return "1 " + noun
	}
	return fmt.Sprintf("%d %ss", n, noun)
}
