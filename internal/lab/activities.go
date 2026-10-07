package lab

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"google.golang.org/grpc/status"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// HeartbeatInterval is how often a long activity tells the workflow service it is alive.
// A mechanism constant, well inside the 30s heartbeat timeout: three
// heartbeats to a timeout window.
//
// It also bounds how late a cancellation reaches a running tool, since a cancellation
// travels on the answer to a heartbeat. Raised from 5s to 10s with the worker's throttle,
// which may not exceed it (D-030).
const HeartbeatInterval = 10 * time.Second

// HeartbeatLostType is the error type of a step cut short because a heartbeat did not reach
// the workflow service. It is not a rule: the finding it carries is reported under the
// step's own rule, and the type is left out of the non-retryable types so the step is
// retried.
const HeartbeatLostType = "HeartbeatLost"

// Prober asks a node whether it is ready: one attempt against addr with the probe its
// package declares. The login is read through getenv by the variable names the probe
// carries, at the moment of the attempt, and never kept.
type Prober interface {
	Probe(ctx context.Context, addr string, p wire.Probe, getenv func(string) (string, bool)) error
}

// Activities are the host-bound activities: everything that must run where the
// containers are (D-015). The fields are the host's resources, so tests substitute a
// fake runner, prober and environment and nothing else.
type Activities struct {
	Clab     *Clab
	Store    bundle.Store
	Paths    Paths
	Registry *psp.Registry
	Prober   Prober
	// Images reports whether the host already holds an image, for the host check's
	// presence pass. The worker and the dry run set DockerImages over the host's runner;
	// tier 1 fakes it.
	Images Images
	// Getenv is os.LookupEnv on a worker and a map in tests.
	Getenv  func(string) (string, bool)
	Version string // the worker binary's --version, recorded in twin.json
	Log     *slog.Logger
	// Reader reads a booted node for the step's wait;
	// nil is GNMIReader over Log. Tier 1 fakes it, as it fakes Prober.
	Reader verify.Reader

	// waitSleep and waitNow are VerifyTwin's pause between two reads and its clock; nil is
	// a timer under the activity's context and time.Now. Only tier 1 sets them, so a wait
	// runs in milliseconds.
	waitSleep func(ctx context.Context, d time.Duration) error
	waitNow   func() time.Time
}

// Names maps each host-bound activity's wire.Act* name to its method, for the worker to
// register by name. Workflows schedule by the same names and never see these methods.
func (a *Activities) Names() map[string]any {
	return map[string]any{
		wire.ActCheckHost:      a.CheckHost,
		wire.ActStageBundle:    a.StageBundle,
		wire.ActDeployLab:      a.DeployLab,
		wire.ActAwaitReadiness: a.AwaitReadiness,
		wire.ActRecordTwin:     a.RecordTwin,
		wire.ActPlanTeardown:   a.PlanTeardown,
		wire.ActDestroyLab:     a.DestroyLab,
		wire.ActUnstageTwin:    a.UnstageTwin,
		wire.ActInspectTwin:    a.InspectTwin,
		wire.ActPushConfig:     a.PushConfig,
		// M11: the step run's own.
		wire.ActPlanReconcile: a.PlanReconcile,
		wire.ActStageStep:     a.StageStep,
		wire.ActReconcileLab:  a.ReconcileLab,
		wire.ActRecordStep:    a.RecordStep,
		// M12: the step's wait after its record.
		wire.ActVerifyTwin: a.VerifyTwin,
	}
}

// StepFailure is an activity failure that retrying cannot help: a tool that refused, a
// node that never answered, a path that would not write. Its error type is the rule it is
// reported under and its one detail is the finding, so the workflow reports the failure
// without parsing a message (the retry policy names these types as non-retryable too).
func StepFailure(step, rule, object, message string) error {
	f := findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Message: message, Step: step}
	return temporal.NewNonRetryableApplicationError(message, rule, nil, f)
}

// interrupted is what a host-bound activity returns when its context ended before its work
// did. A cancellation the workflow asked for, a deadline or a worker shutting down is
// returned as ctx.Err(), which the SDK reports as what it is.
//
// A heartbeat that did not reach the workflow service is different, and is named. The SDK
// gives up on the attempt at the first heartbeat call that fails, cancelling the context
// with that call's error as the cause; returned as ctx.Err() it would read
// "context canceled" and name nothing. It is reported under the step's own rule with
// the cause, and stays retryable, so a deploy is still retried and converges.
func interrupted(ctx context.Context, step, rule, object, what string) error {
	cause := context.Cause(ctx)
	var rpc interface{ Status() *status.Status }
	if cause == nil || temporal.IsCanceledError(cause) || !errors.As(cause, &rpc) {
		return ctx.Err()
	}
	msg := fmt.Sprintf("%s was cut short: a heartbeat from this worker did not reach the workflow service (%v), "+
		"and the attempt is abandoned at the first heartbeat that fails; a host too loaded for the worker to heartbeat "+
		"cuts steps short", what, cause)
	f := findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Message: msg, Step: step}
	return temporal.NewApplicationError(msg, HeartbeatLostType, f)
}

// heartbeat records a heartbeat every HeartbeatInterval until stop is called. A
// heartbeat is also how a running activity learns it has been cancelled,
// so it runs for exactly as long as the work does.
func heartbeat(ctx context.Context) (stop func()) {
	done := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		tick := time.NewTicker(HeartbeatInterval)
		defer tick.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				return
			case <-tick.C:
				activity.RecordHeartbeat(ctx)
			}
		}
	}()
	return func() {
		close(done)
		wg.Wait()
	}
}

func (a *Activities) getenv() func(string) (string, bool) {
	if a.Getenv == nil {
		return os.LookupEnv
	}
	return a.Getenv
}

func (a *Activities) logger() *slog.Logger {
	if a.Log == nil {
		return slog.Default()
	}
	return a.Log
}
