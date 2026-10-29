package lab

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// flowRunner answers the flows' execs by container, start (docker exec -d) or read, and
// keeps every call. It is safe for the concurrent execs StartFlows and ReadFlows run.
type flowRunner struct {
	mu      sync.Mutex
	replies map[string]reply // by "start <container>" or "read <container>"; absent answers exit 0, nothing printed
	calls   []call
}

func (f *flowRunner) Run(_ context.Context, env []string, args ...string) ([]byte, []byte, int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, call{env: env, args: args})
	verb, container := "read", ""
	if len(args) > 3 && args[2] == "-d" {
		verb, container = "start", args[3]
	} else if len(args) > 2 {
		container = args[2]
	}
	r := f.replies[verb+" "+container]
	return r.stdout, r.stderr, r.exit, r.err
}

func (f *flowRunner) sorted() []call {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := slices.Clone(f.calls)
	slices.SortFunc(out, func(x, y call) int { return strings.Compare(strings.Join(x.args, " "), strings.Join(y.args, " ")) })
	return out
}

// twoFlows are the probed golden's two probes as the server plans them, each flow from its a
// host to its b host, the command rendered at plan time.
func twoFlows() []wire.FlowPlan {
	flow := func(far string) wire.FlowSpec {
		return wire.FlowSpec{IntervalS: 0.2, Command: []string{"ping", "-i", "0.2", far}, StartTimeoutS: 30, ReadTimeoutS: 30}
	}
	return []wire.FlowPlan{
		{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Far: "10.1.11.2", Flow: flow("10.1.11.2")},
		{Probe: "n3-loop", From: "clab-fylgja-n3-loop-a", To: "clab-fylgja-n3-loop-b", Far: "10.3.11.2", Flow: flow("10.3.11.2")},
	}
}

// pingLog is what busybox's ping writes into the flow's log once interrupted (research §1.2):
// a reply for each sequence number answered, then the summary.
func pingLog(sent int, answered ...int) []byte {
	var b strings.Builder
	b.WriteString("PING 10.1.11.2 (10.1.11.2): 56 data bytes\n")
	for _, seq := range answered {
		b.WriteString("64 bytes from 10.1.11.2: seq=" + strconv.Itoa(seq) + " ttl=63 time=0.412 ms\n")
	}
	b.WriteString("\n--- 10.1.11.2 ping statistics ---\n")
	b.WriteString(strconv.Itoa(sent) + " packets transmitted, " + strconv.Itoa(len(answered)) + " packets received, 0% packet loss\n")
	return []byte(b.String())
}

// seqs is 0..n-1 without the numbers in gap.
func seqs(n int, gap ...int) []int {
	var out []int
	for i := range n {
		if !slices.Contains(gap, i) {
			out = append(out, i)
		}
	}
	return out
}

// Both flows are started, each in its a host, a stray flow killed first and the flow's
// output sent to its log, through docker exec -d; a host whose exec fails is not_started
// under flow.start.failed and the other still starts (research R-13, R-14).
func TestStartFlows(t *testing.T) {
	t.Run("both started", func(t *testing.T) {
		r := &flowRunner{}
		a := testActivities(t, r)
		res, err := a.StartFlows(context.Background(), wire.FlowsInput{TwinDir: a.Paths.Twin, Flows: twoFlows()})
		if err != nil {
			t.Fatal(err)
		}
		want := []wire.FlowOutcome{{Probe: "n1-loop", Outcome: wire.FlowStarted}, {Probe: "n3-loop", Outcome: wire.FlowStarted}}
		if !slices.Equal(res.Flows, want) {
			t.Errorf("outcomes = %+v, want %+v", res.Flows, want)
		}
		calls := r.sorted()
		if len(calls) != 2 {
			t.Fatalf("%d execs, want one a host", len(calls))
		}
		wantArgs := []string{"docker", "exec", "-d", "clab-fylgja-n1-loop-a", "sh", "-c",
			"pkill -x ping; exec 'ping' '-i' '0.2' '10.1.11.2' > /run/flow.log 2>&1"}
		if !slices.Equal(calls[0].args, wantArgs) {
			t.Errorf("the start's exec = %q\nwant %q", calls[0].args, wantArgs)
		}
		for _, c := range calls {
			if c.env != nil {
				t.Errorf("the exec overrides the environment with %q; a flow reads nothing of it", c.env)
			}
		}
	})

	t.Run("one exec failing", func(t *testing.T) {
		r := &flowRunner{replies: map[string]reply{"start clab-fylgja-n3-loop-a": {
			stderr: []byte("Error response from daemon: container clab-fylgja-n3-loop-a is not running\n"), exit: 1}}}
		a := testActivities(t, r)
		res, err := a.StartFlows(context.Background(), wire.FlowsInput{Flows: twoFlows()})
		if err != nil {
			t.Fatalf("a flow that cannot start fails the activity: %v", err)
		}
		if res.Flows[0].Outcome != wire.FlowStarted {
			t.Errorf("n1-loop = %+v, want started beside the one that failed", res.Flows[0])
		}
		got := res.Flows[1]
		want := "probe n3-loop: its flow could not be started in clab-fylgja-n3-loop-a (docker exec exited 1: " +
			"Error response from daemon: container clab-fylgja-n3-loop-a is not running); it is not measured across the step"
		if got.Outcome != wire.FlowNotStarted || got.Rule != findings.RuleFlowStartFailed || got.Message != want {
			t.Errorf("n3-loop = %+v\nwant not_started under %s: %s", got, findings.RuleFlowStartFailed, want)
		}
	})

	t.Run("an exec that cannot run", func(t *testing.T) {
		r := &flowRunner{replies: map[string]reply{"start clab-fylgja-n1-loop-a": {err: errors.New("exec: \"docker\": executable file not found in $PATH")}}}
		res, err := testActivities(t, r).StartFlows(context.Background(), wire.FlowsInput{Flows: twoFlows()})
		if err != nil {
			t.Fatal(err)
		}
		if got := res.Flows[0]; got.Outcome != wire.FlowNotStarted || !strings.Contains(got.Message, "executable file not found") {
			t.Errorf("n1-loop = %+v, want not_started naming why", got)
		}
	})

	t.Run("a cancelled context", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		if _, err := testActivities(t, &flowRunner{}).StartFlows(ctx, wire.FlowsInput{Flows: twoFlows()}); !errors.Is(err, context.Canceled) {
			t.Errorf("err = %v, want the context's", err)
		}
	})
}

// Each flow is interrupted and its log read, parsed into the echoes sent and lost and the
// longest run unanswered; a read that fails is not_read under flow.read.failed; a flow never
// started is carried as it was; the loss is written into the run's record as the wait is
// (research R-13, R-14).
func TestReadFlows(t *testing.T) {
	// n1-loop lost seq 10–14 of 312: five echoes at 0.2 s, a 1.0 s gap. n3-loop lost none.
	measured := map[string]reply{
		"read clab-fylgja-n1-loop-a": {stdout: pingLog(312, seqs(312, 10, 11, 12, 13, 14)...)},
		"read clab-fylgja-n3-loop-a": {stdout: pingLog(310, seqs(310)...)},
	}
	in := wire.FlowsInput{RunID: waitRunID, Flows: twoFlows(), Added: []string{"n2-loop"}}

	t.Run("a read parsed to sent, lost and gap, and the record written", func(t *testing.T) {
		r := &flowRunner{replies: measured}
		a, _, log := waitingTwin(t, r, waitRunID, nil)
		res, err := a.ReadFlows(context.Background(), in)
		if err != nil {
			t.Fatal(err)
		}
		want := wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{
			{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: wire.FlowMeasured, Sent: 312, Lost: 5, LongestGapS: 1},
			{Probe: "n3-loop", From: "clab-fylgja-n3-loop-a", To: "clab-fylgja-n3-loop-b", Outcome: wire.FlowMeasured, Sent: 310},
		}, Added: []string{"n2-loop"}, Dropped: []string{}}
		if !res.Recorded || !sameJSON(t, res.Loss, want) {
			t.Errorf("result = %+v\nwant recorded %+v", res, want)
		}
		_, rec := readRecordFile(t, a)
		if rec.Step.Loss == nil || !sameJSON(t, *rec.Step.Loss, want) {
			t.Errorf("the record's step.loss = %+v, want %+v", rec.Step.Loss, want)
		}
		calls := r.sorted()
		wantArgs := []string{"docker", "exec", "clab-fylgja-n1-loop-a", "sh", "-c",
			`pkill -INT -x ping; i=0; while pgrep -x ping >/dev/null && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i+1)); done; cat /run/flow.log`}
		if len(calls) != 2 || !slices.Equal(calls[0].args, wantArgs) {
			t.Errorf("the reads = %q\nwant one a host, the first %q", calls, wantArgs)
		}
		noFlowSecret(t, a, log.String(), r, res)

		// A retry finds the run's loss written and returns it, running nothing.
		again := &flowRunner{}
		a.Clab = quietClab(again)
		res2, err := a.ReadFlows(context.Background(), in)
		if err != nil || !res2.Recorded || !sameJSON(t, res2.Loss, want) || len(again.calls) != 0 {
			t.Errorf("the retry = %+v, %v after %d execs; want the record's loss and none", res2, err, len(again.calls))
		}
	})

	t.Run("a read failing", func(t *testing.T) {
		replies := map[string]reply{
			"read clab-fylgja-n1-loop-a": {stderr: []byte("cat: can't open '/run/flow.log': No such file or directory\n"), exit: 1},
			// A ping cut off before its counters measured nothing.
			"read clab-fylgja-n3-loop-a": {stdout: []byte("PING 10.3.11.2 (10.3.11.2): 56 data bytes\n")},
		}
		a, _, _ := waitingTwin(t, &flowRunner{replies: replies}, waitRunID, nil)
		res, err := a.ReadFlows(context.Background(), in)
		if err != nil {
			t.Fatalf("a flow that cannot be read fails the activity: %v", err)
		}
		n1, n3 := res.Loss.Probes[0], res.Loss.Probes[1]
		want := "probe n1-loop: its flow in clab-fylgja-n1-loop-a could not be read (docker exec exited 1: " +
			"cat: can't open '/run/flow.log': No such file or directory); its loss across the step is not known"
		if n1.Outcome != wire.FlowNotRead || n1.Rule != findings.RuleFlowReadFailed || n1.Message != want {
			t.Errorf("n1-loop = %+v\nwant not_read under %s: %s", n1, findings.RuleFlowReadFailed, want)
		}
		if n3.Outcome != wire.FlowNotRead || !strings.Contains(n3.Message, "no summary") {
			t.Errorf("n3-loop = %+v, want not_read: its log holds no summary", n3)
		}
	})

	t.Run("a flow never started is carried as it was", func(t *testing.T) {
		r := &flowRunner{replies: measured}
		a, _, _ := waitingTwin(t, r, waitRunID, nil)
		notStarted := wire.FlowOutcome{Probe: "n3-loop", Outcome: wire.FlowNotStarted, Rule: findings.RuleFlowStartFailed, Message: "probe n3-loop: …"}
		started := in
		started.Started = []wire.FlowOutcome{{Probe: "n1-loop", Outcome: wire.FlowStarted}, notStarted}
		res, err := a.ReadFlows(context.Background(), started)
		if err != nil {
			t.Fatal(err)
		}
		if got := res.Loss.Probes[1]; got.Outcome != wire.FlowNotStarted || got.Rule != notStarted.Rule || got.Message != notStarted.Message || got.Sent != 0 {
			t.Errorf("n3-loop = %+v, want not_started as the start said", got)
		}
		if len(r.calls) != 1 || r.calls[0].args[2] != "clab-fylgja-n1-loop-a" {
			t.Errorf("execs = %q, want n1-loop's read alone", r.calls)
		}
	})

	t.Run("interrupted after the stage", func(t *testing.T) {
		replies := map[string]reply{
			"read clab-fylgja-n1-loop-a": {stdout: pingLog(40, seqs(40, 39)...)},
			"read clab-fylgja-n3-loop-a": {stderr: []byte("Error response from daemon: container is restarting\n"), exit: 1},
		}
		a, _, _ := waitingTwin(t, &flowRunner{replies: replies}, waitRunID, nil)
		stopped := in
		stopped.Interrupted = true
		res, err := a.ReadFlows(context.Background(), stopped)
		if err != nil {
			t.Fatal(err)
		}
		n1, n3 := res.Loss.Probes[0], res.Loss.Probes[1]
		if n1.Outcome != wire.FlowInterrupted || n1.Sent != 40 || n1.Lost != 1 || n1.LongestGapS != 0.2 || n1.Rule != "" {
			t.Errorf("n1-loop = %+v, want interrupted with what it lost until the read", n1)
		}
		if n3.Outcome != wire.FlowInterrupted || n3.Rule != findings.RuleFlowReadFailed {
			t.Errorf("n3-loop = %+v, want interrupted, its read's failure named", n3)
		}
	})

	t.Run("another run's record keeps what it holds", func(t *testing.T) {
		a, _, _ := waitingTwin(t, &flowRunner{replies: measured}, "01a1b2c3-0000-7000-8000-0000000000bb", nil)
		before, _ := readRecordFile(t, a)
		res, err := a.ReadFlows(context.Background(), in)
		if err != nil || res.Recorded || len(res.Loss.Probes) != 2 {
			t.Errorf("result = %+v, %v; want the loss, not recorded", res, err)
		}
		if after, _ := readRecordFile(t, a); string(after) != string(before) {
			t.Errorf("another run's record was rewritten")
		}
	})

	t.Run("a step with no flows", func(t *testing.T) {
		r := &flowRunner{}
		a, _, _ := waitingTwin(t, r, waitRunID, nil)
		res, err := a.ReadFlows(context.Background(), wire.FlowsInput{RunID: waitRunID, Dropped: []string{"n1-loop"}})
		if err != nil || len(r.calls) != 0 {
			t.Fatalf("%v after %d execs", err, len(r.calls))
		}
		b, _ := json.Marshal(res.Loss)
		if want := `{"basis":"container","probes":[],"added":[],"dropped":["n1-loop"]}`; string(b) != want {
			t.Errorf("loss = %s, want %s: every list present, empty where nothing is in it", b, want)
		}
	})
}

// noFlowSecret fails if the probe password the environment holds, or any line of a node's
// configuration, reached a flow's exec, the log, the record or the result.
func noFlowSecret(t *testing.T, a *Activities, log string, r *flowRunner, res wire.ReadFlowsResult) {
	t.Helper()
	b, _ := os.ReadFile(a.Paths.TwinJSON)
	out, _ := json.Marshal(res)
	var execs []string
	for _, c := range r.sorted() {
		execs = append(execs, strings.Join(append(c.env, c.args...), " "))
	}
	for what, text := range map[string]string{"the log": log, "twin.json": string(b), "the result": string(out),
		"the execs": strings.Join(execs, "\n")} {
		for _, secret := range []string{waitPassword, "set / interface", "admin-state"} {
			if strings.Contains(text, secret) {
				t.Errorf("%s carries %q:\n%s", what, secret, text)
			}
		}
	}
}

func sameJSON(t *testing.T, a, b any) bool {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return string(x) == string(y)
}
