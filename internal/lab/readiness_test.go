package lab

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// flakyProber fails its first failures attempts, then answers.
type flakyProber struct {
	failures int

	mu       sync.Mutex
	attempts int
	addrs    []string
}

func (p *flakyProber) Probe(_ context.Context, addr string, _ wire.Probe, _ func(string) (string, bool)) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.attempts++
	p.addrs = append(p.addrs, addr)
	if p.attempts <= p.failures {
		return errors.New("connection refused")
	}
	return nil
}

// A node that refuses twice and then answers is ready, after at least the two probe
// intervals it took. A probe naming no port dials the gNMI default.
func TestAwaitReadinessAfterTwoFailures(t *testing.T) {
	t.Parallel()
	a := testActivities(t, &fakeRunner{})
	p := &flakyProber{failures: 2}
	a.Prober = p
	probe := srlinuxProbe()
	probe.Port = 0
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	val, err := env.ExecuteActivity(wire.ActAwaitReadiness,
		wire.ReadinessInput{Node: "n1", MgmtIPv4: "172.20.20.2", Probe: probe, TimeoutS: 30})
	if err != nil {
		t.Fatal(err)
	}
	var res wire.ReadinessResult
	if err := val.Get(&res); err != nil {
		t.Fatal(err)
	}
	if res.Node != "n1" || res.ReadyAfterS < 2 {
		t.Errorf("result = %+v, want n1 ready after at least 2s", res)
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.attempts != 3 {
		t.Errorf("attempts = %d, want 3", p.attempts)
	}
	if p.addrs[0] != "172.20.20.2:57400" {
		t.Errorf("probed %q, want the management address on the gNMI default port", p.addrs[0])
	}
}

// refusingProber refuses the login at once, as SR Linux does a wrong password, except on an
// attempt that starts too close to the node's deadline to be answered: that one is still
// waiting when the deadline cuts it off.
type refusingProber struct{}

func (refusingProber) Probe(ctx context.Context, _ string, _ wire.Probe, _ func(string) (string, bool)) error {
	if d, ok := ctx.Deadline(); ok && time.Until(d) < 1500*time.Millisecond {
		<-ctx.Done()
		return fmt.Errorf("code=DeadlineExceeded msg=%q", ctx.Err())
	}
	return errors.New(`code=Unauthenticated msg="Username or password is not valid"`)
}

// A node that refuses every login times out naming the refusal, not the deadline that cut
// off the last attempt (live, two of three nodes reported "context deadline exceeded"
// for a wrong password).
func TestAwaitReadinessTimeoutNamesTheNodesAnswer(t *testing.T) {
	t.Parallel()
	a := testActivities(t, &fakeRunner{})
	a.Prober = refusingProber{}
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	_, err := env.ExecuteActivity(wire.ActAwaitReadiness,
		wire.ReadinessInput{Node: "n1", MgmtIPv4: "172.20.20.2", Probe: srlinuxProbe(), TimeoutS: 2})
	if err == nil {
		t.Fatal("a node that refuses every login was reported ready")
	}
	if msg := err.Error(); !strings.Contains(msg, "Unauthenticated") || strings.Contains(msg, "DeadlineExceeded") {
		t.Errorf("error %q, want the refused login as the last error, not the deadline", msg)
	}
}

// lateListener is a TCP listener that starts accepting after a delay, as a node's push
// transport does when it binds later than its probe answers.
func lateListener(t *testing.T, after time.Duration) (host string, port int) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().(*net.TCPAddr)
	// Closed at once and reopened on the same port after the delay, so a dial before it is
	// refused exactly as a node that has not bound yet refuses.
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	go func() {
		time.Sleep(after)
		l, err := net.Listen("tcp", addr.String())
		if err != nil {
			return
		}
		t.Cleanup(func() { _ = l.Close() })
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	return "127.0.0.1", addr.Port
}

// A node whose package asks is ready only once BOTH its probe has answered and its push
// transport accepts a connection: the probe answering first is not enough (D-029).
func TestAwaitReadinessWaitsForThePushTransport(t *testing.T) {
	t.Parallel()
	a := testActivities(t, &fakeRunner{})
	a.Prober = &flakyProber{} // answers at once
	host, port := lateListener(t, 2*time.Second)
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	val, err := env.ExecuteActivity(wire.ActAwaitReadiness, wire.ReadinessInput{
		Node: "e1", MgmtIPv4: host, Probe: srlinuxProbe(), TimeoutS: 30,
		AwaitPushScheme: "https", AwaitPushPort: port,
	})
	if err != nil {
		t.Fatal(err)
	}
	var res wire.ReadinessResult
	if err := val.Get(&res); err != nil {
		t.Fatal(err)
	}
	// Without the wait this would return in well under a second, as the probe answers on
	// the first attempt.
	if res.ReadyAfterS < 2 {
		t.Errorf("ready_after_s = %v, want at least the 2s the transport took: readiness did not wait for it", res.ReadyAfterS)
	}
}

// A push transport that never accepts fails the step under the probe's own identifier,
// with a message that says which of the two came up and names the address.
func TestAwaitReadinessPushTransportNeverAccepts(t *testing.T) {
	t.Parallel()
	a := testActivities(t, &fakeRunner{})
	a.Prober = &flakyProber{}
	// A port nothing listens on: reserved and released, so every dial is refused.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	_, err = env.ExecuteActivity(wire.ActAwaitReadiness, wire.ReadinessInput{
		Node: "e1", MgmtIPv4: "127.0.0.1", Probe: srlinuxProbe(), TimeoutS: 3,
		AwaitPushScheme: "https", AwaitPushPort: port,
	})
	if err == nil {
		t.Fatal("a transport that never accepts did not fail the step")
	}
	f := activityFinding(t, err)
	if f.Rule != findings.RuleReadinessTimeout || f.Step != findings.StepReadiness || f.Object != "e1" {
		t.Errorf("finding = %+v, want %s at %s on the node", f, findings.RuleReadinessTimeout, findings.StepReadiness)
	}
	for _, want := range []string{
		"e1 answered its probe but its push transport at https://127.0.0.1:" + strconv.Itoa(port),
		"did not accept a connection within 3s",
		"readiness.await_push_transport",
	} {
		if !strings.Contains(f.Message, want) {
			t.Errorf("message %q does not say %q", f.Message, want)
		}
	}
}

// A node whose package does not ask never dials a push transport: the step is M2's, and
// every plan recorded before D-029 carries no scheme and no port.
func TestAwaitReadinessWithoutTheWaitNeverDials(t *testing.T) {
	t.Parallel()
	a := testActivities(t, &fakeRunner{})
	a.Prober = &flakyProber{}
	// A port nothing listens on. If the step dialled it despite the plan not asking, the
	// activity would spend its whole timeout and fail instead of returning at once.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	// The push is declared, as every SR Linux node's is; the plan simply does not ask for
	// the wait, so the two fields are empty.
	val, err := env.ExecuteActivity(wire.ActAwaitReadiness, wire.ReadinessInput{
		Node: "n1", MgmtIPv4: "127.0.0.1", Probe: srlinuxProbe(), TimeoutS: 30,
	})
	if err != nil {
		t.Fatal(err)
	}
	var res wire.ReadinessResult
	if err := val.Get(&res); err != nil {
		t.Fatal(err)
	}
	if res.ReadyAfterS > 1 {
		t.Errorf("ready_after_s = %v, want the probe's own time: the step waited for a transport nobody asked about", res.ReadyAfterS)
	}
	_ = port
}
