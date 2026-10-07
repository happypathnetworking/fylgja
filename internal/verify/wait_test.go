package verify

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// fakeClock is a wait's clock and sleep: a read takes perRead, a sleep takes exactly what
// it was asked, so every deadline is arithmetic and the test runs in milliseconds.
type fakeClock struct {
	now     time.Time
	perRead time.Duration
	slept   []time.Duration
	// onSleep runs at the start of each sleep, numbered from 1; an error ends the sleep.
	onSleep func(n int) error
}

var t0 = time.Date(2026, 10, 3, 18, 0, 0, 0, time.UTC)

func newClock() *fakeClock { return &fakeClock{now: t0} }

func (c *fakeClock) Now() time.Time { return c.now }

func (c *fakeClock) Sleep(ctx context.Context, d time.Duration) error {
	c.slept = append(c.slept, d)
	if c.onSleep != nil {
		if err := c.onSleep(len(c.slept)); err != nil {
			return err
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	c.now = c.now.Add(d)
	return nil
}

// waiting is the three-node twin on a fake clock, each read taking the clock's perRead.
func waiting(t *testing.T) (Input, *fakeReader, *fakeClock, []Assertion) {
	t.Helper()
	in, f := threeNode(t)
	c := newClock()
	in.Now = c.Now
	as, err := Derive(in.Manifest)
	if err != nil {
		t.Fatal(err)
	}
	// A read of the three-node twin is 15 paths; the clock moves once per read, as its
	// first path is read, so a read starts at one instant and ends perRead later.
	paths := 0
	f.onGet = func() {
		if paths%15 == 0 {
			c.now = c.now.Add(c.perRead)
		}
		paths++
	}
	return in, f, c, as
}

func waitOn(in Input, as []Assertion, c *fakeClock, o WaitOptions) WaitResult {
	o.Sleep, o.Now = c.Sleep, c.Now
	return Wait(context.Background(), in, as, o)
}

// A twin that conforms at the first read settles at once: one read, no sleep, and the
// seconds counted from the first read's start when no From is given.
func TestWaitSettledAtOnce(t *testing.T) {
	in, _, c, as := waiting(t)
	res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget})
	if res.Outcome != WaitSettled || res.Reads != 1 || res.AfterS != 0 || len(c.slept) != 0 || !res.Last.Conforms() {
		t.Errorf("result %+v after sleeping %v, want settled at the first read, at once", res, c.slept)
	}
}

// A twin that settles late is read once per ReadInterval until it does: two failing reads,
// then the third holds.
func TestWaitSettledLate(t *testing.T) {
	in, f, c, as := waiting(t)
	c.perRead = 300 * time.Millisecond
	n1 := srl(threeNodeIP["n1"])
	f.set(n1, srlNeighbor("ethernet-1/1"), Answer{}, Answer{}, srlNeighbours("ethernet-1/1", srlEntries(r4["n1 ethernet-1/1"])))
	res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget})
	if res.Outcome != WaitSettled || res.Reads != 3 || !res.Last.Conforms() {
		t.Fatalf("result %s %d reads, want settled at the third", res.Outcome, res.Reads)
	}
	// Three reads of 0.3s and two sleeps of ReadInterval, from the first read's start.
	if res.AfterS != 2.9 {
		t.Errorf("after %vs, want 2.9s", res.AfterS)
	}
	if len(c.slept) != 2 || c.slept[0] != ReadInterval || c.slept[1] != ReadInterval {
		t.Errorf("slept %v, want ReadInterval twice", c.slept)
	}
	if !res.Last.ReadAt.Equal(t0.Add(2*time.Second + 600*time.Millisecond)) {
		t.Errorf("last read at %v, want the third read's start", res.Last.ReadAt)
	}
}

// A twin that never conforms expires at the first read that ends with the deadline reached,
// and the last read says what still fails. With reads that take no time, a 2s budget reads
// at 0s, 1s and 2s: the third ends at the deadline itself.
func TestWaitExpired(t *testing.T) {
	in, f, c, as := waiting(t)
	f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable"))
	res := waitOn(in, as, c, WaitOptions{Budget: 2 * time.Second})
	if res.Outcome != WaitExpired || res.Reads != 3 || res.AfterS != 2 {
		t.Fatalf("result %s, %d reads, after %vs, want expired after 3 reads at 2s", res.Outcome, res.Reads, res.AfterS)
	}
	got := res.Last.Findings()
	if len(got) != 1 || got[0].Rule != "verify.port.enabled" || got[0].Object != "n1:ethernet-1/2" || !res.Last.AllRead() {
		t.Errorf("last read's findings %v, want n1:ethernet-1/2's alone, every node read", got)
	}
}

// A node unread at expiry is still expired to the core: the callers word it from
// Last.AllRead().
func TestWaitExpiredWithANodeUnread(t *testing.T) {
	in, f, c, as := waiting(t)
	f.errs[srl(threeNodeIP["n3"])+" "+srlHostName] = errors.New("refused")
	res := waitOn(in, as, c, WaitOptions{Budget: 1500 * time.Millisecond})
	if res.Outcome != WaitExpired || res.Reads != 3 || res.Last.AllRead() || res.Last.Unread[0].Node != "n3" {
		t.Errorf("result %s, %d reads, unread %v, want expired with n3 unread", res.Outcome, res.Reads, res.Last.Unread)
	}
}

// A cancellation during a sleep ends the wait after the read before it, with the reads and
// the seconds reached; one during a read ends it after that read.
func TestWaitCancelled(t *testing.T) {
	t.Run("mid-sleep", func(t *testing.T) {
		in, f, c, as := waiting(t)
		f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), Answer{})
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		c.onSleep = func(n int) error {
			if n == 2 {
				c.now = c.now.Add(400 * time.Millisecond)
				cancel()
				return ctx.Err()
			}
			return nil
		}
		res := Wait(ctx, in, as, WaitOptions{Budget: DefaultBudget, Sleep: c.Sleep, Now: c.Now})
		if res.Outcome != WaitCancelled || res.Reads != 2 || res.AfterS != 1.4 {
			t.Errorf("result %s, %d reads, after %vs, want cancelled after 2 reads at 1.4s", res.Outcome, res.Reads, res.AfterS)
		}
	})
	t.Run("during a read", func(t *testing.T) {
		in, f, c, as := waiting(t)
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), Answer{})
		f.onGet = cancel
		res := Wait(ctx, in, as, WaitOptions{Budget: DefaultBudget, Sleep: c.Sleep, Now: c.Now})
		if res.Outcome != WaitCancelled || res.Reads != 1 || len(c.slept) != 0 {
			t.Errorf("result %s, %d reads, slept %v, want cancelled after the one read", res.Outcome, res.Reads, c.slept)
		}
	})
	t.Run("under the default sleep", func(t *testing.T) {
		in, f, _, as := waiting(t)
		f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), Answer{})
		ctx, cancel := context.WithCancel(context.Background())
		f.onGet = func() {}
		go func() { time.Sleep(50 * time.Millisecond); cancel() }()
		in.Now = nil
		start := time.Now()
		res := Wait(ctx, in, as, WaitOptions{Budget: DefaultBudget})
		if res.Outcome != WaitCancelled || res.Reads != 1 || time.Since(start) > ReadInterval {
			t.Errorf("result %s, %d reads in %v, want cancelled within the first sleep", res.Outcome, res.Reads, time.Since(start))
		}
	})
}

// A budget of 0 reads once, whatever the read finds, and never sleeps.
func TestWaitBudgetZero(t *testing.T) {
	for _, failing := range []bool{false, true} {
		in, f, c, as := waiting(t)
		want := WaitSettled
		if failing {
			f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), Answer{})
			want = WaitExpired
		}
		res := waitOn(in, as, c, WaitOptions{Budget: 0})
		if res.Outcome != want || res.Reads != 1 || len(c.slept) != 0 {
			t.Errorf("failing %v: result %s, %d reads, slept %v, want %s after one read", failing, res.Outcome, res.Reads, c.slept, want)
		}
	}
}

// The budget and the seconds run from From, not from the first read: a From in the past
// shortens the wait (the step's, from its record).
func TestWaitFromBeforeTheFirstRead(t *testing.T) {
	t.Run("settled", func(t *testing.T) {
		in, _, c, as := waiting(t)
		res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget, From: t0.Add(-5 * time.Second)})
		if res.Outcome != WaitSettled || res.AfterS != 5 {
			t.Errorf("result %s after %vs, want settled 5s after From", res.Outcome, res.AfterS)
		}
	})
	t.Run("expired", func(t *testing.T) {
		in, f, c, as := waiting(t)
		f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), Answer{})
		res := waitOn(in, as, c, WaitOptions{Budget: 6 * time.Second, From: t0.Add(-5 * time.Second)})
		if res.Outcome != WaitExpired || res.Reads != 2 || res.AfterS != 6 {
			t.Errorf("result %s, %d reads, after %vs, want expired after 2 reads, 6s after From", res.Outcome, res.Reads, res.AfterS)
		}
	})
	t.Run("a From after the clock's now", func(t *testing.T) {
		in, _, c, as := waiting(t)
		res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget, From: t0.Add(time.Second)})
		if res.Outcome != WaitSettled || res.AfterS != 0 {
			t.Errorf("result %s after %vs, want settled at 0s, never below", res.Outcome, res.AfterS)
		}
	})
}

// The record's claims are never waited on: a twin whose every assertion holds settles
// beside a claim that fails.
func TestWaitDoesNotWaitOnClaims(t *testing.T) {
	in, _, c, as := waiting(t)
	in.Record.Nodes[0].Holds = nil
	res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget})
	if res.Outcome != WaitSettled || res.Reads != 1 || res.Last.Claims[0].Outcome != Failed {
		t.Errorf("result %s, %d reads, claim %+v, want settled at once beside the failed claim", res.Outcome, res.Reads, res.Last.Claims[0])
	}
}

// A node a read could not dial, because containerlab did not report it, is looked up again
// before the next read: a node absent from the first inspection and present from the second
// settles on the second read, containerlab asked once. An inspection that
// fails keeps the list it had, and a wait whose every node was dialled never asks again.
func TestWaitLooksUpAnUndialledNodeAgain(t *testing.T) {
	t.Run("present from the second inspection", func(t *testing.T) {
		in, _, c, as := waiting(t)
		in.Lab = in.Lab[:2]
		asked := 0
		lab := func(context.Context) ([]wire.LabNode, error) {
			asked++
			return labOf(threeNodeIP), nil
		}
		res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget, Lab: lab})
		if res.Outcome != WaitSettled || res.Reads != 2 || !res.Last.AllRead() || asked != 1 {
			t.Errorf("result %s after %d reads, unread %v, containerlab asked %d times; want settled at the second, asked once",
				res.Outcome, res.Reads, res.Last.Unread, asked)
		}
	})
	// containerlab's N/A for an exited container, cut to N, is no address: the
	// node is not dialled, so it is looked up again, and settles once it has a real one.
	t.Run("an address from the second inspection", func(t *testing.T) {
		in, f, c, as := waiting(t)
		in.Record.Nodes[2].MgmtIPv4, in.Lab[2].MgmtIPv4 = "N", "N"
		asked := 0
		lab := func(context.Context) ([]wire.LabNode, error) {
			asked++
			return labOf(threeNodeIP), nil
		}
		res := waitOn(in, as, c, WaitOptions{Budget: DefaultBudget, Lab: lab})
		if res.Outcome != WaitSettled || res.Reads != 2 || !res.Last.AllRead() || asked != 1 || res.Last.Nodes[2].Addr != srl(threeNodeIP["n3"]) {
			t.Errorf("result %s after %d reads, unread %v, containerlab asked %d times; want settled at the second at containerlab's address, asked once",
				res.Outcome, res.Reads, res.Last.Unread, asked)
		}
		for _, call := range f.calls {
			if strings.HasPrefix(call, "N:") {
				t.Errorf("read %s, want n3 not dialled at N", call)
			}
		}
	})
	t.Run("an inspection that fails keeps the list", func(t *testing.T) {
		in, _, c, as := waiting(t)
		in.Lab = in.Lab[:2]
		asked := 0
		lab := func(context.Context) ([]wire.LabNode, error) {
			asked++
			return nil, errors.New("clab inspect exited 1: permission denied")
		}
		res := waitOn(in, as, c, WaitOptions{Budget: 2 * time.Second, Lab: lab})
		if res.Outcome != WaitExpired || res.Reads != 3 || asked != 2 || len(res.Last.Unread) != 1 ||
			res.Last.Unread[0].Error != "containerlab does not report node n3, which the staged bundle names; nothing to read" {
			t.Errorf("result %s after %d reads, unread %+v, containerlab asked %d times; want n3 still unreported, asked before each read after the first",
				res.Outcome, res.Reads, res.Last.Unread, asked)
		}
	})
	t.Run("every node dialled", func(t *testing.T) {
		in, f, c, as := waiting(t)
		f.errs[srl(threeNodeIP["n3"])+" "+srlHostName] = errors.New("refused")
		lab := func(context.Context) ([]wire.LabNode, error) {
			t.Error("containerlab was asked again, with every node dialled")
			return nil, nil
		}
		if res := waitOn(in, as, c, WaitOptions{Budget: 2 * time.Second, Lab: lab}); res.Outcome != WaitExpired {
			t.Errorf("result %s, want expired", res.Outcome)
		}
	})
}

// A read the cancellation cut is not kept: Last is the read before it, with no cancellation
// among its errors, and the reads and seconds are as reached; one that cut the first read
// leaves Last empty, nothing failing. The reader honours its context,
// as a real one does.
func TestWaitKeepsNoReadACancellationCut(t *testing.T) {
	cancelledAt := func(call int) (Input, *fakeClock, []Assertion, context.Context) {
		in, f, c, as := waiting(t)
		in.Now = c.Now
		f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable"))
		ctx, cancel := context.WithCancel(context.Background())
		t.Cleanup(cancel)
		calls := 0
		f.onGet = func() {
			if calls++; calls == call {
				cancel()
			}
		}
		return in, c, as, ctx
	}
	t.Run("during the second read", func(t *testing.T) {
		in, c, as, ctx := cancelledAt(15 + 2)
		res := Wait(ctx, in, as, WaitOptions{Budget: DefaultBudget, Sleep: c.Sleep, Now: c.Now})
		if res.Outcome != WaitCancelled || res.Reads != 2 || res.AfterS != 1 {
			t.Fatalf("result %s, %d reads, after %vs; want cancelled after 2 reads, 1s", res.Outcome, res.Reads, res.AfterS)
		}
		if !res.Last.ReadAt.Equal(t0) || !res.Last.AllRead() {
			t.Errorf("last read at %v, unread %+v; want the first read, every node read", res.Last.ReadAt, res.Last.Unread)
		}
		got := res.Last.Findings()
		if len(got) != 1 || got[0].Object != "n1:ethernet-1/2" {
			t.Errorf("last read's findings %v, want the disabled port's alone", got)
		}
		for _, a := range res.Last.Assertions {
			if strings.Contains(a.Error, "Canceled") {
				t.Errorf("%s carries the cancellation: %s", describe(a), a.Error)
			}
		}
	})
	t.Run("during the first read", func(t *testing.T) {
		in, c, as, ctx := cancelledAt(2)
		res := Wait(ctx, in, as, WaitOptions{Budget: DefaultBudget, Sleep: c.Sleep, Now: c.Now})
		if res.Outcome != WaitCancelled || res.Reads != 1 || len(res.Last.Findings()) != 0 || len(res.Last.Assertions) != 0 {
			t.Errorf("result %s, %d reads, last %+v; want cancelled after the one read, nothing kept", res.Outcome, res.Reads, res.Last)
		}
	})
}
