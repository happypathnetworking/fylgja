package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The step's wait against a scratch twin directory
// holding the three-node golden as the staged bundle and a version 5 record whose step
// names the run, a fake node table in the suite's shape, and a fake clock, so every wait
// runs in milliseconds.

const (
	waitRunID     = "01a1b2c3-0000-7000-8000-0000000000aa"
	waitOtherRun  = "01a1b2c3-0000-7000-8000-0000000000bb"
	waitPassword  = "sentinel-wait-password"
	waitFromStamp = "2026-10-03T12:00:00Z"
)

// waitIP is each node's address, as inspect-three.json reports it and the record holds it.
var waitIP = map[string]string{"n1": "172.20.20.2", "n2": "172.20.20.3", "n3": "172.20.20.4"}

// waitFar is what SR Linux 24.7.1 reports on each cabled port of the three-node twin: the far
// node and the far port by the far node's own name.
var waitFar = map[string][2]string{
	"n1 ethernet-1/1": {"n2", "ethernet-1/1"},
	"n1 ethernet-1/2": {"n3", "ethernet-1/2"},
	"n2 ethernet-1/1": {"n1", "ethernet-1/1"},
	"n2 ethernet-1/2": {"n3", "ethernet-1/1"},
	"n3 ethernet-1/1": {"n2", "ethernet-1/2"},
	"n3 ethernet-1/2": {"n1", "ethernet-1/2"},
}

// waitReader answers each read from a table keyed by "<addr> <path>", as an SR Linux node
// answers it: the n-th read of a key gets the n-th answer of its sequence,
// the last repeating; an error is the transport's. A read the table does not hold fails, and
// so does one under a context that has ended.
type waitReader struct {
	mu      sync.Mutex
	answers map[string][]verify.Answer
	errs    map[string]error
	reads   map[string]int
	calls   int
	// onGet runs before each answer: a test cancels its context there.
	onGet func(calls int)
}

func (f *waitReader) Get(ctx context.Context, addr string, _ wire.Probe, path string, getenv func(string) (string, bool)) (verify.Answer, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	if f.onGet != nil {
		f.onGet(f.calls)
	}
	// A context that has ended is answered as gnmiGet answers it, after onGet, which may
	// have ended it.
	if err := ctx.Err(); err != nil {
		return verify.Answer{}, fmt.Errorf("gNMI Get %s at %s: code=Canceled msg=%q", path, addr, err)
	}
	// The login is read at the moment of the read, as the probe reads it.
	if p, ok := getenv("FYLGJA_SRLINUX_PASSWORD"); !ok || p != waitPassword {
		return verify.Answer{}, fmt.Errorf("the reader was not handed the probe login")
	}
	key := addr + " " + path
	n := f.reads[key]
	f.reads[key]++
	if err, ok := f.errs[key]; ok {
		return verify.Answer{}, err
	}
	seq := f.answers[key]
	if len(seq) == 0 {
		return verify.Answer{}, fmt.Errorf("the fake node has no answer for %s", key)
	}
	return seq[min(n, len(seq)-1)], nil
}

func (f *waitReader) set(addr, path string, answers ...verify.Answer) {
	f.answers[addr+" "+path] = answers
}

func srlAt(path string, v any) verify.Answer {
	return verify.Answer{Updates: []verify.Update{{Path: path, Value: v}}}
}

func srlEnabledPath(port string) string { return "/interface[name=" + port + "]/admin-state" }

func srlEnabledAnswer(port, v string) verify.Answer {
	return srlAt("srl_nokia-interfaces:interface[name="+port+"]/admin-state", v)
}

func srlNeighborPath(port string) string { return "/system/lldp/interface[name=" + port + "]/neighbor" }

// healthyTwin answers every read of the three-node twin as the live twin answers it: the 15
// paths of its assertions.
func healthyTwin() *waitReader {
	f := &waitReader{answers: map[string][]verify.Answer{}, errs: map[string]error{}, reads: map[string]int{}}
	for node, ip := range waitIP {
		addr := ip + ":57400"
		f.set(addr, "/system/name/host-name", srlAt("srl_nokia-system:system/srl_nokia-system-name:name/host-name", node))
		for _, port := range []string{"ethernet-1/1", "ethernet-1/2"} {
			far := waitFar[node+" "+port]
			f.set(addr, srlEnabledPath(port), srlEnabledAnswer(port, "enable"))
			f.set(addr, srlNeighborPath(port), srlAt("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]",
				map[string]any{"neighbor": []any{map[string]any{"id": "1A:EB:01:FF:00:00", "system-name": far[0], "port-id": far[1]}}}))
		}
	}
	return f
}

// waitClock is a clock that moves only when the wait sleeps.
type waitClock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *waitClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

// advance moves the clock on by d, as a read that takes d does.
func (c *waitClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

func (c *waitClock) Sleep(ctx context.Context, d time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	c.now = c.now.Add(d)
	c.mu.Unlock()
	return nil
}

// waitingTwin is the activities with the three-node golden staged, a version 5 record of a
// step from demo/1 to the golden as demo/2 written by run, its wait not yet run, the reader
// r, a clock standing at the record's time, the probe login in the environment and every
// log line kept.
func waitingTwin(t *testing.T, runner Runner, run string, r verify.Reader) (*Activities, *waitClock, *bytes.Buffer) {
	t.Helper()
	a, _ := steppingTwin(t, runner)
	rec := waitRecord(t, run, func(*StepFields) {})
	if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
		t.Fatal(err)
	}
	from, err := time.Parse(time.RFC3339, waitFromStamp)
	if err != nil {
		t.Fatal(err)
	}
	clock := &waitClock{now: from}
	var log bytes.Buffer
	a.Log = slog.New(slog.NewTextHandler(&log, &slog.HandlerOptions{Level: slog.LevelDebug}))
	a.Getenv = mapEnv(map[string]string{"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": waitPassword})
	a.Reader, a.waitNow, a.waitSleep = r, clock.Now, clock.Sleep
	return a, clock, &log
}

// waitRecord is the record a step from demo/1 to the three-node golden as demo/2 leaves,
// written by run, the step's fields changed by change first.
func waitRecord(t *testing.T, run string, change func(*StepFields)) wire.TwinRecord {
	t.Helper()
	m, err := readManifest(goldenBundle())
	if err != nil {
		t.Fatal(err)
	}
	staged := &StagedTarget{BundleID: goldenID, Provenance: wire.Provenance(m.Provenance),
		PSP: map[string]wire.PSPRef{}, Artifacts: map[string]*wire.TwinArtifact{}}
	observed := "2026-10-03T11:58:00.000000Z"
	create := RecordFields{BundleID: stepFromID, ObservedAt: &observed, Source: wire.SourceIntent, Waypoint: demo(1),
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: stepFromAt, SchemaHash: "fixture", ContractVersion: "0.2"},
		RunID:      "01a0e9e3-0000-7000-8000-000000000001", Version: "0.1.0-dev", RecordedAt: time.Date(2026, 10, 3, 11, 0, 0, 0, time.UTC)}
	var lab []wire.LabNode
	var pushed []wire.StepPush
	for _, n := range m.Nodes {
		ref := wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}
		art := &wire.TwinArtifact{Name: n.Artifact.Name, ContentType: n.Artifact.ContentType, Checksum: n.Artifact.Checksum, Size: n.Artifact.Size}
		staged.PSP[n.Name], staged.Artifacts[n.Name] = ref, art
		create.Nodes = append(create.Nodes, wire.TwinNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image,
			PSP: ref, MgmtIPv4: waitIP[n.Name], ReadyAfterS: 1, Artifact: art, PushedInS: 0.7})
		lab = append(lab, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image, State: "running",
			MgmtIPv4: waitIP[n.Name]})
		pushed = append(pushed, wire.StepPush{Node: n.Name, Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(0.8)})
	}
	prev, err := NewRecord(create)
	if err != nil {
		t.Fatal(err)
	}
	f := StepFields{Outcome: wire.StepStepped,
		From:       wire.StepSide{Waypoint: demo(1), BundleID: stepFromID, At: stepFromAt},
		To:         wire.StepSide{Waypoint: demo(2), BundleID: goldenID, At: m.Provenance.At},
		ObservedAt: "2026-10-03T11:59:00.000000Z", RunID: run, Version: "0.1.0-dev",
		Pushed: pushed, StartedAt: "2026-10-03T11:59:30Z", EndedAt: waitFromStamp,
		RecordedAt: time.Date(2026, 10, 3, 12, 0, 0, 100000000, time.UTC), Nodes: lab, Staged: staged}
	change(&f)
	rec, err := NewStepRecord(prev, f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

func waitInput(budgetS int) wire.VerifyInput {
	return wire.VerifyInput{RunID: waitRunID, From: waitFromStamp, BudgetS: budgetS}
}

// readRecordFile is twin.json's bytes and the record they hold.
func readRecordFile(t *testing.T, a *Activities) ([]byte, wire.TwinRecord) {
	t.Helper()
	b, err := os.ReadFile(a.Paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	rec, err := ReadRecord(a.Paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	return b, rec
}

// noSecret fails if the password reached the log, the record or the result.
func noSecret(t *testing.T, a *Activities, log *bytes.Buffer, res wire.VerifyResult) {
	t.Helper()
	b, _ := os.ReadFile(a.Paths.TwinJSON)
	out, _ := json.Marshal(res)
	for what, text := range map[string]string{"the log": log.String(), "twin.json": string(b), "the result": string(out)} {
		if strings.Contains(text, waitPassword) {
			t.Errorf("%s carries the probe password:\n%s", what, text)
		}
	}
}

func inspectThree(t *testing.T) *fakeRunner {
	return &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three.json")}}}}
}

// Every outcome of the wait, written into the record whose step names the run, and returned
// as the run's result.
func TestVerifyTwin(t *testing.T) {
	ctx := context.Background()
	s := twinSchema(t)
	golden, err := readManifest(goldenBundle())
	if err != nil {
		t.Fatal(err)
	}
	if len(golden.Nodes) != 3 || len(golden.Links) != 3 {
		t.Fatalf("the three-node golden has %d nodes and %d links", len(golden.Nodes), len(golden.Links))
	}
	written := func(t *testing.T, a *Activities, res wire.VerifyResult) {
		t.Helper()
		_, rec := readRecordFile(t, a)
		validateRecord(t, s, rec)
		if !res.Recorded || rec.Step == nil || rec.Step.Wait == nil || fmt.Sprint(*rec.Step.Wait) != fmt.Sprint(res.Wait) {
			t.Errorf("recorded %t, the record's wait %+v; want the result's %+v written", res.Recorded, rec.Step.Wait, res.Wait)
		}
		if rec.RecordedAt != "2026-10-03T12:00:00.1Z" {
			t.Errorf("recorded_at moved to %s: the wait is a fact added to the step, not a new record", rec.RecordedAt)
		}
	}

	t.Run("settled at once", func(t *testing.T) {
		runner, r := inspectThree(t), healthyTwin()
		a, _, log := waitingTwin(t, runner, waitRunID, r)
		val, err := activityEnv(a.VerifyTwin, wire.ActVerifyTwin).ExecuteActivity(wire.ActVerifyTwin, waitInput(120))
		if err != nil {
			t.Fatal(err)
		}
		var res wire.VerifyResult
		if err := val.Get(&res); err != nil {
			t.Fatal(err)
		}
		want := wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 1, AfterS: 0, From: waitFromStamp,
			EndedAt: waitFromStamp, Failing: []wire.StepFinding{}}
		if fmt.Sprint(res.Wait) != fmt.Sprint(want) {
			t.Errorf("wait %+v\nwant %+v", res.Wait, want)
		}
		written(t, a, res)
		// Each of the 15 paths is read once, over the record's addresses.
		if r.calls != 15 || len(r.reads) != 15 {
			t.Errorf("%d reads of %d paths; want each of the 15 once", r.calls, len(r.reads))
		}
		onlyInspected(t, runner)
		noSecret(t, a, log, res)
		b, _ := os.ReadFile(a.Paths.TwinJSON)
		if !strings.Contains(string(b), `"failing": []`) {
			t.Errorf("a settled wait's failing is not written as []:\n%s", b)
		}
	})

	t.Run("settled late", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"),
			srlEnabledAnswer("ethernet-1/2", "disable"), srlEnabledAnswer("ethernet-1/2", "disable"), srlEnabledAnswer("ethernet-1/2", "enable"))
		a, _, log := waitingTwin(t, inspectThree(t), waitRunID, r)
		res, err := a.VerifyTwin(ctx, waitInput(120))
		if err != nil {
			t.Fatal(err)
		}
		if w := res.Wait; w.Outcome != wire.WaitSettled || w.Reads != 3 || w.AfterS != 2 || len(w.Failing) != 0 ||
			w.EndedAt != "2026-10-03T12:00:02Z" {
			t.Errorf("wait %+v; want settled at the third read, 2s after the record, nothing failing", w)
		}
		written(t, a, res)
		noSecret(t, a, log, res)
	})

	t.Run("expired", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, _, log := waitingTwin(t, inspectThree(t), waitRunID, r)
		res, err := a.VerifyTwin(ctx, waitInput(3))
		if err != nil {
			t.Fatal(err)
		}
		w := res.Wait
		if w.Outcome != wire.WaitExpired || w.BudgetS != 3 || w.Reads != 4 || w.AfterS != 3 || len(w.Failing) != 1 {
			t.Fatalf("wait %+v; want expired after 4 reads, 3s, one assertion failing", w)
		}
		if f := w.Failing[0]; f.Rule != findings.RuleVerifyPortEnabled || f.Object != "n1:ethernet-1/2" ||
			!strings.Contains(f.Message, `reads "disable"`) {
			t.Errorf("failing %+v; want verify.port.enabled on n1:ethernet-1/2 reading disable", f)
		}
		written(t, a, res)
		noSecret(t, a, log, res)
	})

	t.Run("a budget of 0 reads once", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
		res, err := a.VerifyTwin(ctx, waitInput(0))
		if err != nil {
			t.Fatal(err)
		}
		if w := res.Wait; w.Outcome != wire.WaitExpired || w.BudgetS != 0 || w.Reads != 1 || r.calls != 15 {
			t.Errorf("wait %+v after %d reads of a path; want expired after one read of the twin", w, r.calls)
		}
		written(t, a, res)
	})

	// The budget runs from the record, so a wait whose From is already 2s behind
	// the clock (a retried attempt, or a slow schedule) reads twice where "expired" read
	// four times.
	t.Run("a From in the past shortens the wait", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, clock, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
		clock.now = clock.now.Add(2 * time.Second)
		res, err := a.VerifyTwin(ctx, waitInput(3))
		if err != nil {
			t.Fatal(err)
		}
		if w := res.Wait; w.Outcome != wire.WaitExpired || w.Reads != 2 || w.AfterS != 3 || w.From != waitFromStamp {
			t.Errorf("wait %+v; want expired after 2 reads, 3s from the record's time", w)
		}
		written(t, a, res)
	})

	// A node unread when the budget passes is the step's incomplete, its
	// operation.failed beside whatever else still fails.
	t.Run("incomplete with a node unread", func(t *testing.T) {
		r := healthyTwin()
		for _, path := range []string{"/system/name/host-name", srlEnabledPath("ethernet-1/1"), srlEnabledPath("ethernet-1/2"),
			srlNeighborPath("ethernet-1/1"), srlNeighborPath("ethernet-1/2")} {
			r.errs["172.20.20.3:57400 "+path] = errors.New("connection refused")
		}
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, _, log := waitingTwin(t, inspectThree(t), waitRunID, r)
		res, err := a.VerifyTwin(ctx, waitInput(2))
		if err != nil {
			t.Fatal(err)
		}
		w := res.Wait
		if w.Outcome != wire.WaitIncomplete || w.Reads != 3 || len(w.Failing) != 2 {
			t.Fatalf("wait %+v; want incomplete after 3 reads, two failing", w)
		}
		if f := w.Failing[0]; f.Rule != findings.RuleVerifyPortEnabled || f.Object != "n1:ethernet-1/2" {
			t.Errorf("failing[0] %+v; want the disabled port", f)
		}
		if f := w.Failing[1]; f.Rule != findings.RuleOperationFailed || f.Object != "n2" ||
			f.Message != "node n2 (172.20.20.3:57400) could not be read: connection refused (at /system/name/host-name)" {
			t.Errorf("failing[1] %+v; want n2's operation.failed", f)
		}
		written(t, a, res)
		noSecret(t, a, log, res)
	})

	t.Run("cancelled mid-wait", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, clock, log := waitingTwin(t, inspectThree(t), waitRunID, r)
		cctx, cancel := context.WithCancelCause(ctx)
		sleeps := 0
		a.waitSleep = func(c context.Context, d time.Duration) error {
			// The run is cancelled during the second pause: twin destroy during the pause.
			if sleeps++; sleeps == 2 {
				cancel(temporal.NewCanceledError())
			}
			return clock.Sleep(c, d)
		}
		res, err := a.VerifyTwin(cctx, waitInput(120))
		if err != nil {
			t.Fatalf("error %v; a cancelled wait is a result, never an error", err)
		}
		if w := res.Wait; w.Outcome != wire.WaitCancelled || w.Reads != 2 || w.AfterS != 1 || len(w.Failing) != 1 {
			t.Errorf("wait %+v; want cancelled after 2 reads, 1s, the disabled port still failing", w)
		}
		written(t, a, res)
		noSecret(t, a, log, res)
	})

	// An attempt cut short by anything but the run's cancellation writes nothing and fails.
	// A lost heartbeat stays retryable, under the step observe, so the retry resumes the
	// wait from the same From.
	t.Run("a lost heartbeat is retried, not recorded", func(t *testing.T) {
		r := healthyTwin()
		r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
		a, clock, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
		before, _ := readRecordFile(t, a)
		cctx, cancel := context.WithCancelCause(ctx)
		a.waitSleep = func(c context.Context, d time.Duration) error {
			cancel(serviceerror.NewDeadlineExceeded("context deadline exceeded"))
			return clock.Sleep(c, d)
		}
		_, err := a.VerifyTwin(cctx, waitInput(120))
		var appErr *temporal.ApplicationError
		if !errors.As(err, &appErr) || appErr.Type() != HeartbeatLostType || appErr.NonRetryable() {
			t.Fatalf("error %v; want a retryable %s", err, HeartbeatLostType)
		}
		var f findings.Finding
		if err := appErr.Details(&f); err != nil || f.Step != findings.StepObserve || f.Rule != findings.RuleOperationFailed {
			t.Errorf("finding %+v (%v); want operation.failed at observe", f, err)
		}
		if after, _ := readRecordFile(t, a); !bytes.Equal(before, after) {
			t.Errorf("the record moved:\n%s", after)
		}
	})

	// A record that is not this run's step keeps what it holds: one the step could not write
	// (the previous step's, or the create's), or another run's. The wait still runs, and the
	// result says it was not recorded.
	for _, c := range []struct {
		name string
		rec  func(t *testing.T) wire.TwinRecord
	}{
		{"another run's step", func(t *testing.T) wire.TwinRecord { return waitRecord(t, waitOtherRun, func(*StepFields) {}) }},
		{"a create's record, step null", func(t *testing.T) wire.TwinRecord {
			rec := waitRecord(t, waitOtherRun, func(*StepFields) {})
			observed := "2026-10-03T11:58:00.000000Z"
			create, err := NewRecord(RecordFields{BundleID: goldenID, ObservedAt: &observed, Source: wire.SourceIntent,
				Provenance: rec.Provenance, RunID: rec.Run.RunID, Version: "0.1.0-dev", Nodes: rec.Nodes,
				RecordedAt: time.Date(2026, 10, 3, 11, 0, 0, 0, time.UTC)})
			if err != nil {
				t.Fatal(err)
			}
			return create
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := healthyTwin()
			a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
			rec := c.rec(t)
			if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			before, _ := readRecordFile(t, a)
			res, err := a.VerifyTwin(ctx, waitInput(120))
			if err != nil {
				t.Fatal(err)
			}
			if res.Recorded || res.Wait.Outcome != wire.WaitSettled || res.Wait.Reads != 1 {
				t.Errorf("result %+v; want the settled wait, not recorded", res)
			}
			if after, _ := readRecordFile(t, a); !bytes.Equal(before, after) {
				t.Errorf("the record moved:\n%s\nwas\n%s", after, before)
			}
		})
	}

	// Constitution VIII: a retry that finds this run's wait written returns it as written,
	// reading no node and asking containerlab nothing.
	t.Run("a retry finds the wait written", func(t *testing.T) {
		r := healthyTwin()
		runner := inspectThree(t)
		a, _, _ := waitingTwin(t, runner, waitRunID, r)
		rec := waitRecord(t, waitRunID, func(*StepFields) {})
		rec.Step.Wait = &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 30, Reads: 29, AfterS: 30.1, From: waitFromStamp,
			EndedAt: "2026-10-03T12:00:30.1Z", Failing: []wire.StepFinding{{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/2", Message: "m"}}}
		if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
			t.Fatal(err)
		}
		before, _ := readRecordFile(t, a)
		res, err := a.VerifyTwin(ctx, waitInput(30))
		if err != nil {
			t.Fatal(err)
		}
		if !res.Recorded || fmt.Sprint(res.Wait) != fmt.Sprint(*rec.Step.Wait) {
			t.Errorf("result %+v; want the written wait %+v, recorded", res, *rec.Step.Wait)
		}
		if r.calls != 0 || len(runner.calls) != 0 {
			t.Errorf("%d reads and %d containerlab calls; want none", r.calls, len(runner.calls))
		}
		if after, _ := readRecordFile(t, a); !bytes.Equal(before, after) {
			t.Errorf("the record moved:\n%s", after)
		}
	})

	// A diverged step's record gets its wait too, and a node the record
	// says holds nothing does not keep the wait from settling: claims are never waited on,
	// and never among what fails, settled or not.
	for _, c := range []struct {
		name     string
		disabled bool
		outcome  string
	}{
		{"after a diverged step, claims are not waited on", false, wire.WaitSettled},
		{"after a diverged step, claims are not among what fails", true, wire.WaitExpired},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := healthyTwin()
			if c.disabled {
				r.set("172.20.20.3:57400", srlEnabledPath("ethernet-1/1"), srlEnabledAnswer("ethernet-1/1", "disable"))
			}
			a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
			rec := waitRecord(t, waitRunID, func(f *StepFields) {
				var l findings.List
				l.AddStep(findings.Rejection, findings.StepPush, findings.RulePushRefused, "n1", "refused")
				l.AddStep(findings.Rejection, findings.StepPush, findings.RuleStepDiverged, waitRunID, "the step stopped")
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, l
				f.Plan, f.ReconcileStarted = wire.ReconcilePlan{Restarted: []string{"n1"}}, true
				f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushRefused, findings.RulePushRefused, nil
			})
			if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
				t.Fatal(err)
			}
			res, err := a.VerifyTwin(ctx, waitInput(1))
			if err != nil {
				t.Fatal(err)
			}
			w := res.Wait
			if w.Outcome != c.outcome {
				t.Errorf("wait %+v; want %s", w, c.outcome)
			}
			for _, f := range w.Failing {
				if f.Rule != findings.RuleVerifyPortEnabled || f.Object != "n2:ethernet-1/1" {
					t.Errorf("failing %+v; only the disabled port fails, never the record's claims", f)
				}
			}
			if len(w.Failing) != map[bool]int{false: 0, true: 1}[c.disabled] {
				t.Errorf("failing %+v", w.Failing)
			}
			written(t, a, res)
			if _, back := readRecordFile(t, a); back.State != wire.StateDiverged || back.Nodes[0].Holds != nil {
				t.Errorf("state %s, n1 holds %v; the wait changes nothing but the step's wait", back.State, back.Nodes[0].Holds)
			}
		})
	}

	// A node the record names with no address is read at the address containerlab reports.
	t.Run("an address the record lacks is containerlab's", func(t *testing.T) {
		r := healthyTwin()
		a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
		_, rec := readRecordFile(t, a)
		rec.Nodes[2].MgmtIPv4 = ""
		if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
			t.Fatal(err)
		}
		res, err := a.VerifyTwin(ctx, waitInput(120))
		if err != nil {
			t.Fatal(err)
		}
		if w := res.Wait; w.Outcome != wire.WaitSettled || r.reads["172.20.20.4:57400 /system/name/host-name"] != 1 {
			t.Errorf("wait %+v; want settled, n3 read at containerlab's 172.20.20.4", w)
		}
	})

	// A lab containerlab cannot inspect is read at the record's addresses alone.
	t.Run("an inspection that fails", func(t *testing.T) {
		runner := &fakeRunner{replies: map[string][]reply{"inspect": {{stderr: []byte("permission denied"), exit: 1}}}}
		a, _, log := waitingTwin(t, runner, waitRunID, healthyTwin())
		res, err := a.VerifyTwin(ctx, waitInput(120))
		if err != nil {
			t.Fatal(err)
		}
		if res.Wait.Outcome != wire.WaitSettled {
			t.Errorf("wait %+v; want settled at the record's addresses", res.Wait)
		}
		if !strings.Contains(log.String(), "inspecting the lab for the step's wait failed") {
			t.Errorf("the log does not say the inspection failed:\n%s", log)
		}
		written(t, a, res)
	})

	// What the activity cannot read is non-retryable operation.failed at observe, which the
	// run records as incomplete: no node is read and the record is untouched.
	for _, c := range []struct {
		name   string
		break_ func(t *testing.T, a *Activities) string // returns the finding's object
		in     wire.VerifyInput
	}{
		{"no staged manifest", func(t *testing.T, a *Activities) string {
			if err := os.Remove(filepath.Join(a.Paths.TwinBundle, compiler.ManifestFile)); err != nil {
				t.Fatal(err)
			}
			return a.Paths.TwinBundle
		}, waitInput(120)},
		{"no record", func(t *testing.T, a *Activities) string {
			if err := os.Remove(a.Paths.TwinJSON); err != nil {
				t.Fatal(err)
			}
			return a.Paths.TwinJSON
		}, waitInput(120)},
		{"a From that is not RFC 3339", func(t *testing.T, a *Activities) string { return waitRunID },
			wire.VerifyInput{RunID: waitRunID, From: "yesterday", BudgetS: 120}},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := healthyTwin()
			a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
			object := c.break_(t, a)
			before, _ := os.ReadFile(a.Paths.TwinJSON)
			_, err := activityEnv(a.VerifyTwin, wire.ActVerifyTwin).ExecuteActivity(wire.ActVerifyTwin, c.in)
			f := stepFailure(t, err, findings.RuleOperationFailed)
			if f.Step != findings.StepObserve || f.Object != object {
				t.Errorf("finding %+v; want step observe, object %s", f, object)
			}
			if r.calls != 0 {
				t.Errorf("%d reads; want none", r.calls)
			}
			if after, _ := os.ReadFile(a.Paths.TwinJSON); !bytes.Equal(before, after) {
				t.Errorf("the record moved:\n%s", after)
			}
		})
	}
}

// verifyMargin is provision.VerifyMargin, which internal/lab cannot import: what VerifyTwin's
// start-to-close adds to the budget. provision's options test holds
// the constant at 30s.
const verifyMargin = 30 * time.Second

// silentNodes is a twin some of whose nodes accept no connection: each read of one takes
// ProbeAttemptDeadline on the wait's clock and fails as gnmiGet's deadline fails it, an
// unanswered read. The others answer through r. Its deadline is the activity's start-to-close
// as the workflow service enforces it: a read that ends past it ends the activity's context,
// as the service's timeout does, with no cancellation the run asked for.
type silentNodes struct {
	r        verify.Reader
	clock    *waitClock
	silent   map[string]bool // by address
	deadline time.Time
	cancel   context.CancelCauseFunc

	mu   sync.Mutex
	gets map[string]int
}

func (s *silentNodes) Get(ctx context.Context, addr string, probe wire.Probe, path string, getenv func(string) (string, bool)) (verify.Answer, error) {
	if !s.silent[addr] {
		return s.r.Get(ctx, addr, probe, path, getenv)
	}
	s.mu.Lock()
	s.gets[addr]++
	s.mu.Unlock()
	s.clock.advance(ProbeAttemptDeadline)
	if !s.clock.Now().Before(s.deadline) {
		s.cancel(context.DeadlineExceeded)
	}
	return verify.Answer{}, &verify.Unanswered{Err: fmt.Errorf("gNMI Get %s at %s: code=DeadlineExceeded msg=%q", path, addr,
		"context deadline exceeded")}
}

// Two nodes that accept no connection, as a node stopped during a step is, cost one attempt's
// deadline each per read, so the wait ends inside VerifyTwin's start-to-close and records
// incomplete with each node's operation.failed. Were every path of a silent
// node dialled, one read of the twin would take 50s and the service's timeout would cut the
// activity, leaving the record's wait null and naming no node.
func TestVerifyTwinWithSilentNodesEndsInsideItsBound(t *testing.T) {
	const budgetS = 20
	reader := &silentNodes{r: healthyTwin(), gets: map[string]int{},
		silent: map[string]bool{"172.20.20.3:57400": true, "172.20.20.4:57400": true}}
	a, c, log := waitingTwin(t, inspectThree(t), waitRunID, reader)
	reader.clock = c
	from := c.Now()
	reader.deadline = from.Add(budgetS*time.Second + verifyMargin)
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	reader.cancel = cancel

	res, err := a.VerifyTwin(ctx, waitInput(budgetS))
	if err != nil {
		t.Fatalf("error %v; the wait must end inside its start-to-close, %s after the record", err, budgetS*time.Second+verifyMargin)
	}
	if end := c.Now(); end.After(reader.deadline) {
		t.Errorf("the wait ended %s after the record, past its bound %s", end.Sub(from), budgetS*time.Second+verifyMargin)
	}
	w := res.Wait
	if w.Outcome != wire.WaitIncomplete || w.Reads != 2 || w.AfterS != 21 || len(w.Failing) != 2 {
		t.Fatalf("wait %+v; want incomplete after 2 reads, 21s, the two silent nodes failing", w)
	}
	for i, node := range []string{"n2", "n3"} {
		addr := waitIP[node] + ":57400"
		want := wire.StepFinding{Rule: findings.RuleOperationFailed, Object: node, Message: fmt.Sprintf("node %s (%s) could not be read: "+
			`gNMI Get /system/name/host-name at %s: code=DeadlineExceeded msg="context deadline exceeded" (at /system/name/host-name)`, node, addr, addr)}
		if w.Failing[i] != want {
			t.Errorf("failing[%d] %+v\nwant %+v", i, w.Failing[i], want)
		}
		if n := reader.gets[addr]; n != 2 {
			t.Errorf("%s dialled %d times, want once per read", node, n)
		}
	}
	_, rec := readRecordFile(t, a)
	if rec.Step.Wait == nil || rec.Step.Wait.Outcome != wire.WaitIncomplete || len(rec.Step.Wait.Failing) != 2 {
		t.Errorf("the record's wait %+v; want incomplete with both nodes' operation.failed", rec.Step.Wait)
	}
	noSecret(t, a, log, res)
}

// A read the cancellation cut is not what the record keeps: a twin destroy during the second
// read records the wait cancelled with the first read's failing, and one before the first
// read records nothing failing.
func TestVerifyTwinKeepsNoReadACancellationCut(t *testing.T) {
	for _, c := range []struct {
		name    string
		at      int // the read call the run is cancelled at; 0 before the activity starts
		reads   int
		failing []string
	}{
		{"during the second read", 15 + 2, 2, []string{"verify.port.enabled n1:ethernet-1/2"}},
		{"before the first read", 0, 1, []string{}},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := healthyTwin()
			r.set("172.20.20.2:57400", srlEnabledPath("ethernet-1/2"), srlEnabledAnswer("ethernet-1/2", "disable"))
			a, _, log := waitingTwin(t, inspectThree(t), waitRunID, r)
			ctx, cancel := context.WithCancelCause(context.Background())
			defer cancel(nil)
			if c.at == 0 {
				cancel(temporal.NewCanceledError())
			}
			r.onGet = func(calls int) {
				if calls == c.at {
					cancel(temporal.NewCanceledError())
				}
			}
			res, err := a.VerifyTwin(ctx, waitInput(120))
			if err != nil {
				t.Fatalf("error %v; a cancelled wait is a result", err)
			}
			w := res.Wait
			failing := []string{}
			for _, f := range w.Failing {
				failing = append(failing, f.Rule+" "+f.Object)
				if strings.Contains(f.Message, "Canceled") {
					t.Errorf("failing %+v carries the cancellation", f)
				}
			}
			if w.Outcome != wire.WaitCancelled || w.Reads != c.reads || fmt.Sprint(failing) != fmt.Sprint(c.failing) {
				t.Errorf("wait %+v; want cancelled after %d reads, failing %v", w, c.reads, c.failing)
			}
			_, rec := readRecordFile(t, a)
			if rec.Step.Wait == nil || len(rec.Step.Wait.Failing) != len(c.failing) || !res.Recorded {
				t.Errorf("the record's wait %+v; want the result's written", rec.Step.Wait)
			}
			noSecret(t, a, log, res)
		})
	}
}

// A record whose step names the run, but which will not take the wait, is operation.failed at
// observe, not retried, on twin.json: the run then says the wait could not complete, where the
// record would otherwise say it never ran. A record that was another run's
// when the wait began keeps M12's Recorded false, even when it cannot be read again.
func TestVerifyTwinRecordThatWillNotTakeTheWait(t *testing.T) {
	t.Run("a record that will not write", func(t *testing.T) {
		if os.Geteuid() == 0 {
			t.Skip("root writes into a read-only directory")
		}
		a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, healthyTwin())
		if err := os.Chmod(a.Paths.Twin, 0o555); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(a.Paths.Twin, 0o755) })
		before, _ := readRecordFile(t, a)
		_, err := activityEnv(a.VerifyTwin, wire.ActVerifyTwin).ExecuteActivity(wire.ActVerifyTwin, waitInput(120))
		f := stepFailure(t, err, findings.RuleOperationFailed)
		if f.Step != findings.StepObserve || f.Object != a.Paths.TwinJSON ||
			!strings.HasPrefix(f.Message, "the step's wait is not recorded: writing "+a.Paths.TwinJSON+": ") ||
			!strings.Contains(f.Message, "permission denied") {
			t.Errorf("finding %+v; want operation.failed at observe on twin.json, the write's error", f)
		}
		if after, _ := readRecordFile(t, a); !bytes.Equal(before, after) {
			t.Errorf("the record moved:\n%s", after)
		}
	})
	for _, c := range []struct {
		name  string
		run   string // the run the record's step names
		fails bool
	}{
		{"a record that cannot be read again", waitRunID, true},
		{"another run's record that cannot be read again", waitOtherRun, false},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := healthyTwin()
			a, _, _ := waitingTwin(t, inspectThree(t), waitRunID, r)
			if err := WriteRecord(a.Paths.TwinJSON, waitRecord(t, c.run, func(*StepFields) {})); err != nil {
				t.Fatal(err)
			}
			// The record is torn while the twin is read: the wait began with it whole.
			r.onGet = func(calls int) {
				if calls == 1 {
					if err := os.WriteFile(a.Paths.TwinJSON, []byte("{"), 0o644); err != nil {
						t.Error(err)
					}
				}
			}
			res, err := a.VerifyTwin(context.Background(), waitInput(120))
			if !c.fails {
				if err != nil || res.Recorded || res.Wait.Outcome != wire.WaitSettled {
					t.Errorf("result %+v, error %v; want the settled wait, not recorded, and no error", res, err)
				}
				return
			}
			f := stepFailure(t, err, findings.RuleOperationFailed)
			if f.Step != findings.StepObserve || f.Object != a.Paths.TwinJSON || !strings.HasPrefix(f.Message, "the step's wait is not recorded: ") {
				t.Errorf("finding %+v; want operation.failed at observe on twin.json", f)
			}
		})
	}
}

// A node containerlab did not report at the first inspection is looked up again before the
// next read, and the wait settles once containerlab reports it.
func TestVerifyTwinLooksUpAnUnreportedNodeAgain(t *testing.T) {
	var labs map[string][]map[string]any
	if err := json.Unmarshal(recorded(t, "inspect-three.json"), &labs); err != nil {
		t.Fatal(err)
	}
	labs[LabName] = labs[LabName][:2]
	withoutN3, err := json.Marshal(labs)
	if err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: withoutN3}, {stdout: recorded(t, "inspect-three.json")}}}}
	a, _, _ := waitingTwin(t, runner, waitRunID, healthyTwin())
	res, err := a.VerifyTwin(context.Background(), waitInput(120))
	if err != nil {
		t.Fatal(err)
	}
	if w := res.Wait; w.Outcome != wire.WaitSettled || w.Reads != 2 || len(runner.calls) != 2 {
		t.Errorf("wait %+v after %d inspections; want settled at the second read, containerlab asked twice", w, len(runner.calls))
	}
	onlyInspected(t, runner)
}
