package lab

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"net"
	"strconv"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// ProbeInterval is the pause between readiness probe attempts. A mechanism constant.
const ProbeInterval = time.Second

// AwaitReadiness probes one node once a second until it answers or its package's timeout
// has passed since the activity began. Every error is treated alike — a
// refused login as much as a closed port, since a booting node produces both on the way
// up — and the last one the node gave is named if it never answers.
//
// Ready means the management plane answers an authenticated request, not that routing
// has converged (glossary). For a node whose package asks, it also means the transport
// its configuration must arrive on accepts a connection: a platform can answer its probe
// while that transport is still shut, and a push beginning a second later is refused
// (D-029). Both waits share the one timeout, and ready_after_s covers
// both.
//
// A host's readiness is keyed by its probe package's readiness.probe, exec (016): its
// command run in the host's container, ready once the output holds what the package
// expects, under the same once-a-second loop and the package's timeout, with no login.
func (a *Activities) AwaitReadiness(ctx context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
	if in.Exec != nil {
		return a.awaitExec(ctx, in)
	}
	start := time.Now()
	deadline := start.Add(time.Duration(in.TimeoutS) * time.Second)
	port := in.Probe.Port
	if port == 0 {
		port = psp.DefaultGNMIPort
	}
	addr := net.JoinHostPort(in.MgmtIPv4, strconv.Itoa(port))
	probe := describeProbe(in)
	cutShort := func() error {
		return interrupted(ctx, findings.StepReadiness, findings.RuleReadinessTimeout, in.Node, "the readiness probe of "+in.Node)
	}

	log := a.logger().With("node", in.Node)
	// The command an operator can repeat by hand, with the login named by its variables.
	log.Info("readiness probe", "addr", addr, "probe", probe, "timeout_s", in.TimeoutS,
		"by_hand", fmt.Sprintf(`gnmic -a %s -u "$%s" -p "$%s" %s -e %s get --path %s`,
			addr, in.Probe.UsernameEnv, in.Probe.PasswordEnv, gnmicTLSFlag(in.Probe), in.Probe.Encoding, in.Probe.Path))

	stop := heartbeat(ctx)
	defer stop()

	var lastErr error
	for attempts := 1; ; attempts++ {
		attemptCtx, cancel := context.WithDeadline(ctx, deadline)
		err := a.Prober.Probe(attemptCtx, addr, in.Probe, a.getenv())
		cancel()
		if err == nil {
			if err := a.awaitPushTransport(ctx, in, deadline, log); err != nil {
				return wire.ReadinessResult{}, err
			}
			after := time.Since(start).Seconds()
			log.Info("node ready", "ready_after_s", after, "attempts", attempts)
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: math.Round(after*1000) / 1000}, nil
		}
		if ctx.Err() != nil {
			return wire.ReadinessResult{}, cutShort()
		}
		// An attempt that ran into the node's deadline was cut short by the timeout, not
		// answered by the node: its "context deadline exceeded" would hide the error the node
		// did give, such as a refused login. The earlier error stands.
		if lastErr == nil || time.Now().Before(deadline) {
			lastErr = err
		}

		wait := min(time.Until(deadline), ProbeInterval)
		if wait <= 0 {
			break
		}
		select {
		case <-ctx.Done():
			return wire.ReadinessResult{}, cutShort()
		case <-time.After(wait):
		}
		if !time.Now().Before(deadline) {
			break
		}
	}

	msg := fmt.Sprintf("%s did not answer %s at %s within %ds; last error: %v",
		in.Node, probe, addr, in.TimeoutS, lastErr)
	log.Warn("readiness timeout", "error", lastErr)
	return wire.ReadinessResult{}, StepFailure(findings.StepReadiness, findings.RuleReadinessTimeout, in.Node, msg)
}

// describeProbe names a probe as the findings do: `gnmi_get /system/information json_ietf`,
// or a host's `exec ip -4 -o addr show dev eth1 expecting 10.1.10.2/24` (016).
func describeProbe(in wire.ReadinessInput) string {
	if e := in.Exec; e != nil {
		return fmt.Sprintf("exec %s expecting %s", strings.Join(e.Command, " "), e.Expect)
	}
	p := in.Probe
	return strings.Join(strings.Fields(p.Transport+" "+p.Path+" "+p.Encoding), " ")
}

// dockerExec is the command a host's exec runs through: the container runtime, reached by
// the Runner containerlab is driven through, so tier 1 substitutes its recorded behaviour.
const dockerExec = "docker exec"

// awaitExec is a host's readiness: `docker exec <container> <command>` once a second until
// its output contains the package's expectation or the timeout has passed since the
// activity began. A failed exec, one that exits non-zero, and one whose output lacks the
// expectation are alike a host not yet ready, as a refused login and a closed port are a
// device not yet ready; the last is named if it never becomes ready. Nothing is logged in
// to and nothing secret is read; the command and its output are a host's own addresses.
func (a *Activities) awaitExec(ctx context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
	start := time.Now()
	deadline := start.Add(time.Duration(in.TimeoutS) * time.Second)
	container := in.Container
	if container == "" {
		container = containerPrefix + in.Node
	}
	args := append(append(strings.Fields(dockerExec), container), in.Exec.Command...)
	probe := describeProbe(in)
	cutShort := func() error {
		return interrupted(ctx, findings.StepReadiness, findings.RuleReadinessTimeout, in.Node, "the readiness probe of "+in.Node)
	}

	log := a.logger().With("node", in.Node)
	log.Info("readiness probe", "container", container, "probe", probe, "timeout_s", in.TimeoutS,
		"by_hand", strings.Join(args, " "))

	stop := heartbeat(ctx)
	defer stop()

	var lastErr error
	for attempts := 1; ; attempts++ {
		attemptCtx, cancel := context.WithDeadline(ctx, deadline)
		stdout, stderr, exit, err := a.Clab.Runner.Run(attemptCtx, nil, args...)
		cancel()
		switch {
		case err != nil:
			// An exec that ran into the deadline was cut short by it, and keeps the earlier
			// reason, as a probe attempt does.
			if lastErr == nil || time.Now().Before(deadline) {
				lastErr = err
			}
		case exit != 0:
			msg := strings.TrimSpace(string(stderr))
			if msg == "" {
				msg = "no message on stderr"
			}
			lastErr = fmt.Errorf("exited %d: %s", exit, msg)
		case !strings.Contains(string(stdout), in.Exec.Expect):
			lastErr = fmt.Errorf("its output does not contain %s", in.Exec.Expect)
		default:
			after := time.Since(start).Seconds()
			log.Info("node ready", "ready_after_s", after, "attempts", attempts)
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: math.Round(after*1000) / 1000}, nil
		}
		if ctx.Err() != nil {
			return wire.ReadinessResult{}, cutShort()
		}

		wait := min(time.Until(deadline), ProbeInterval)
		if wait <= 0 {
			break
		}
		select {
		case <-ctx.Done():
			return wire.ReadinessResult{}, cutShort()
		case <-time.After(wait):
		}
		if !time.Now().Before(deadline) {
			break
		}
	}

	msg := fmt.Sprintf("%s did not answer %s in container %s within %ds; last error: %v",
		in.Node, probe, container, in.TimeoutS, lastErr)
	log.Warn("readiness timeout", "error", lastErr)
	return wire.ReadinessResult{}, StepFailure(findings.StepReadiness, findings.RuleReadinessTimeout, in.Node, msg)
}

// awaitPushTransport waits, once the probe has answered, for the endpoint the node's
// package names for its push to accept a connection (D-029). A node whose package does not
// ask returns at once, which is every node planned before the field and every node of a
// platform whose push transport is up when its probe answers.
//
// It opens a connection and closes it: no request is made and no login is read, so nothing
// secret is needed here and nothing is sent. The wait shares the probe's deadline, so a
// package's readiness.timeout_s still bounds the whole step.
func (a *Activities) awaitPushTransport(ctx context.Context, in wire.ReadinessInput, deadline time.Time, log *slog.Logger) error {
	if in.AwaitPushScheme == "" || in.AwaitPushPort == 0 {
		return nil
	}
	addr := net.JoinHostPort(in.MgmtIPv4, strconv.Itoa(in.AwaitPushPort))
	start := time.Now()
	var lastErr error
	for {
		dialCtx, cancel := context.WithDeadline(ctx, deadline)
		conn, err := (&net.Dialer{}).DialContext(dialCtx, "tcp", addr)
		cancel()
		if err == nil {
			_ = conn.Close()
			log.Info("push transport accepting", "addr", addr, "scheme", in.AwaitPushScheme,
				"after_s", math.Round(time.Since(start).Seconds()*1000)/1000)
			return nil
		}
		if ctx.Err() != nil {
			return interrupted(ctx, findings.StepReadiness, findings.RuleReadinessTimeout, in.Node,
				"the readiness probe of "+in.Node)
		}
		lastErr = err

		wait := min(time.Until(deadline), ProbeInterval)
		if wait <= 0 {
			break
		}
		select {
		case <-ctx.Done():
			return interrupted(ctx, findings.StepReadiness, findings.RuleReadinessTimeout, in.Node,
				"the readiness probe of "+in.Node)
		case <-time.After(wait):
		}
		if !time.Now().Before(deadline) {
			break
		}
	}

	// The probe answered and this did not, so the message says which of the two came up
	// and which did not: the identifier and the step are the probe's (contracts/cli.md).
	msg := fmt.Sprintf("%s answered its probe but its push transport at %s://%s did not accept a connection within %ds "+
		"(readiness.await_push_transport); last error: %v", in.Node, in.AwaitPushScheme, addr, in.TimeoutS, lastErr)
	log.Warn("push transport never accepted", "addr", addr, "error", lastErr)
	return StepFailure(findings.StepReadiness, findings.RuleReadinessTimeout, in.Node, msg)
}
