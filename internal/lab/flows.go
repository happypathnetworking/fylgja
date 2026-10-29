package lab

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// FlowLog is where a host's flow writes what ping prints, inside the host's container: the
// replies as they come and, once interrupted, the summary ReadFlows parses (research R-14).
const FlowLog = "/run/flow.log"

// FlowExitWait is how long ReadFlows lets an interrupted ping take to print its summary and
// exit before the log is read: a mechanism constant, not the package's. busybox's ping
// printed it at once (research §1.2).
const FlowExitWait = 5 * time.Second

// flowExitPoll is the pause between two looks for the interrupted ping, inside the host.
const flowExitPoll = 100 * time.Millisecond

// StartFlows starts every flow of the step (016, research R-13, R-14): in each flow's From
// container, `docker exec -d <from> sh -c 'pkill -x ping; exec <flow.command> > /run/flow.log
// 2>&1'`, through the Runner containerlab is driven through, all at once, each within its
// package's start_timeout_s. A stray flow, a retry's or an earlier step's, is killed first, so
// a start is idempotent and each host runs one flow, logging afresh.
//
// A flow whose exec could not run or exited non-zero is not_started under the warning
// flow.start.failed, and the others are still started: a flow that cannot start is an entry
// of the loss, never a failure of the step. The activity fails only when its context ends,
// which the workflow reports at the phase flows.
//
// It heartbeats while the execs run. The commands carry the host's addresses and nothing
// else: no login, no token and no configuration is read or logged.
func (a *Activities) StartFlows(ctx context.Context, in wire.FlowsInput) (wire.FlowsResult, error) {
	stop := heartbeat(ctx)
	defer stop()

	out := make([]wire.FlowOutcome, len(in.Flows))
	var wg sync.WaitGroup
	for i, f := range in.Flows {
		wg.Go(func() { out[i] = a.startFlow(ctx, f) })
	}
	wg.Wait()
	if ctx.Err() != nil {
		return wire.FlowsResult{}, interrupted(ctx, findings.StepFlows, findings.RuleOperationFailed, "flows",
			"starting the step's flows")
	}
	slices.SortFunc(out, func(x, y wire.FlowOutcome) int { return strings.Compare(x.Probe, y.Probe) })
	return wire.FlowsResult{Flows: out}, nil
}

// startFlow starts one flow, and says whether it did.
func (a *Activities) startFlow(ctx context.Context, f wire.FlowPlan) wire.FlowOutcome {
	script := "pkill -x ping; exec " + shellLine(f.Flow.Command) + " > " + FlowLog + " 2>&1"
	args := append(strings.Fields(dockerExec), "-d", f.From, "sh", "-c", script)
	log := a.logger().With("probe", f.Probe, "container", f.From)

	execCtx, cancel := context.WithTimeout(ctx, seconds(f.Flow.StartTimeoutS))
	defer cancel()
	_, stderr, exit, err := a.Clab.Runner.Run(execCtx, nil, args...)
	if why := execFailure(stderr, exit, err); why != "" {
		log.Warn("the probe's flow was not started", "reason", why)
		return wire.FlowOutcome{Probe: f.Probe, Outcome: wire.FlowNotStarted, Rule: findings.RuleFlowStartFailed,
			Message: fmt.Sprintf("probe %s: its flow could not be started in %s (%s); it is not measured across the step",
				f.Probe, f.From, why)}
	}
	log.Info("the probe's flow started", "to", f.To, "far", f.Far, "interval_s", f.Flow.IntervalS,
		"by_hand", strings.Join(args, " "))
	return wire.FlowOutcome{Probe: f.Probe, Outcome: wire.FlowStarted}
}

// ReadFlows reads every flow of the step and writes the step's loss into the record (016,
// research R-13, R-14): in each flow's From container, `docker exec <from> sh -c 'pkill -INT -x
// ping; <wait up to FlowExitWait for it to exit>; cat /run/flow.log'`, all at once, each
// within its package's read_timeout_s, the log parsed by probe.ParsePing into the echoes sent,
// those lost and the longest run unanswered.
//
//   - A flow whose start was not_started is carried as it was, and no exec is run for it.
//   - A flow whose read failed, or whose log holds no summary, is not_read under the warning
//     flow.read.failed.
//   - On a step that failed or was cancelled after its stage (in.Interrupted), every flow
//     read is interrupted: its figures are what it lost until it was read, and a read that
//     failed keeps flow.read.failed's rule and message.
//   - The probes the target adds and drops are listed as they are given: no flow measured
//     them across the step.
//
// The loss is written into the record's step block when that step is in.RunID's, as
// VerifyTwin writes the wait; a retry that finds this run's loss already written returns it
// and runs nothing. A record that is another run's, or one the step could not write, keeps
// what it holds, and the result says so (Recorded false). A record that names the run but
// will not take the loss is operation.failed, not retried. Every flow is read before the
// record is, so a record that cannot be written leaves no ping running.
func (a *Activities) ReadFlows(ctx context.Context, in wire.FlowsInput) (wire.ReadFlowsResult, error) {
	stop := heartbeat(ctx)
	defer stop()

	path := a.Paths.TwinJSON
	rec, err := ReadRecord(path)
	named := err == nil && mine(rec, in.RunID)
	if named && rec.Step.Loss != nil {
		return wire.ReadFlowsResult{Loss: *rec.Step.Loss, Recorded: true}, nil
	}

	started := make(map[string]wire.FlowOutcome, len(in.Started))
	for _, s := range in.Started {
		started[s.Probe] = s
	}
	probes := make([]wire.ProbeLoss, len(in.Flows))
	var wg sync.WaitGroup
	for i, f := range in.Flows {
		if s, ok := started[f.Probe]; ok && s.Outcome == wire.FlowNotStarted {
			probes[i] = wire.ProbeLoss{Probe: f.Probe, From: f.From, To: f.To, Outcome: wire.FlowNotStarted,
				Rule: s.Rule, Message: s.Message}
			continue
		}
		wg.Go(func() { probes[i] = a.readFlow(ctx, f, in.Interrupted) })
	}
	wg.Wait()
	if ctx.Err() != nil {
		return wire.ReadFlowsResult{}, interrupted(ctx, findings.StepFlows, findings.RuleOperationFailed, path,
			"reading the step's flows")
	}
	slices.SortFunc(probes, func(x, y wire.ProbeLoss) int { return strings.Compare(x.Probe, y.Probe) })
	loss := wire.Loss{Basis: wire.LossBasisContainer, Probes: probes,
		Added: append([]string{}, in.Added...), Dropped: append([]string{}, in.Dropped...)}

	recorded, err := a.recordInStep(path, in.RunID, named, "loss", func(s *wire.StepRecord) { s.Loss = &loss })
	if err != nil {
		return wire.ReadFlowsResult{}, StepFailure(findings.StepFlows, findings.RuleOperationFailed, path,
			fmt.Sprintf("the step's loss is not recorded: %v", err))
	}
	return wire.ReadFlowsResult{Loss: loss, Recorded: recorded}, nil
}

// readFlow interrupts one flow and reads its log: measured, or interrupted on a step that
// stopped after its stage, with its figures; not_read when the read failed, kept
// interrupted on such a step.
func (a *Activities) readFlow(ctx context.Context, f wire.FlowPlan, stopped bool) wire.ProbeLoss {
	tries := int(FlowExitWait / flowExitPoll)
	script := fmt.Sprintf(`pkill -INT -x ping; i=0; while pgrep -x ping >/dev/null && [ "$i" -lt %d ]; do sleep %g; i=$((i+1)); done; cat %s`,
		tries, flowExitPoll.Seconds(), FlowLog)
	args := append(strings.Fields(dockerExec), f.From, "sh", "-c", script)
	log := a.logger().With("probe", f.Probe, "container", f.From)
	out := wire.ProbeLoss{Probe: f.Probe, From: f.From, To: f.To, Outcome: wire.FlowMeasured}
	if stopped {
		out.Outcome = wire.FlowInterrupted
	}

	execCtx, cancel := context.WithTimeout(ctx, seconds(f.Flow.ReadTimeoutS))
	defer cancel()
	stdout, stderr, exit, err := a.Clab.Runner.Run(execCtx, nil, args...)
	why := execFailure(stderr, exit, err)
	var s probe.PingSummary
	if why == "" {
		if s, err = probe.ParsePing(stdout, f.Flow.IntervalS); err != nil {
			why = err.Error()
		}
	}
	if why != "" {
		log.Warn("the probe's flow was not read", "reason", why)
		if !stopped {
			out.Outcome = wire.FlowNotRead
		}
		out.Rule = findings.RuleFlowReadFailed
		out.Message = fmt.Sprintf("probe %s: its flow in %s could not be read (%s); its loss across the step is not known",
			f.Probe, f.From, why)
		return out
	}
	out.Sent, out.Lost, out.LongestGapS = s.Sent, s.Lost, s.LongestGapS
	log.Info("the probe's flow was read", "outcome", out.Outcome, "sent", s.Sent, "lost", s.Lost,
		"longest_gap_s", s.LongestGapS)
	return out
}

// execFailure is why an exec did not succeed — it could not run, or exited non-zero with
// what it said on stderr — or "" when it did.
func execFailure(stderr []byte, exit int, err error) string {
	switch {
	case err != nil:
		return err.Error()
	case exit != 0:
		msg := strings.TrimSpace(string(stderr))
		if msg == "" {
			msg = "no message on stderr"
		}
		return fmt.Sprintf("docker exec exited %d: %s", exit, msg)
	}
	return ""
}

// shellLine is a command as one line of sh, each argument single-quoted, so a rendered
// address or interval is passed as one word whatever it holds.
func shellLine(command []string) string {
	words := make([]string, len(command))
	for i, w := range command {
		words[i] = "'" + strings.ReplaceAll(w, "'", `'\''`) + "'"
	}
	return strings.Join(words, " ")
}

func seconds(s int) time.Duration { return time.Duration(s) * time.Second }
