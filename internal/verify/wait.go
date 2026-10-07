package verify

import (
	"context"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// DefaultBudget is the one default budget of a wait: how long twin verify --wait and the
// step's wait read again before they give up (D-039). It bounds the operator's patience, not a platform: no package says
// how long its nodes take to settle, since a twin settles when its slowest adjacency
// forms, which no single package knows, so it is a mechanism constant overridden by the
// flag on both commands and never a package field (Constitution II).
const DefaultBudget = 120 * time.Second

// ReadInterval is the pause between two reads of a wait: the pause the readiness probe
// takes between its attempts (lab.ProbeInterval), so a wait asks a node no more often than
// readiness already does. A mechanism constant: every read itself goes over the package's
// own probe and its timeouts.
const ReadInterval = time.Second

// How a wait ended: the core's three. The step's activity derives a
// fourth, incomplete, from a last read with a node unread.
const (
	WaitSettled   = wire.WaitSettled
	WaitExpired   = wire.WaitExpired
	WaitCancelled = wire.WaitCancelled
)

// WaitOptions bound a wait.
type WaitOptions struct {
	Budget time.Duration
	// From is the instant the budget runs from: the step's record, so a
	// retried attempt computes the same deadline; zero for the first read's start.
	From time.Time
	// Sleep pauses between two reads; nil is a timer under ctx. It returns ctx's error
	// when ctx ends first.
	Sleep func(ctx context.Context, d time.Duration) error
	// Now is the wait's clock, and the reads'; nil is Input.Now, and then time.Now.
	Now func() time.Time
	// Lab asks containerlab for the lab's nodes again, never nil when it answers. Before
	// each read after the first, when the read before it left a node undialled because
	// containerlab did not report it or it had no address, the wait asks again and reads
	// with the answer; an inspection that fails keeps the list it had. Nil keeps Input.Lab
	// for every read.
	Lab func(ctx context.Context) ([]wire.LabNode, error)
}

// WaitResult is how a wait ended: the outcome, the reads made, the
// seconds from From to the end of the read that settled, or to the wait's end otherwise,
// and the last read, whose findings are what still fails.
type WaitResult struct {
	Outcome string
	Reads   int
	AfterS  float64
	// Last is the last read the cancellation did not cut: a read during which the context
	// ended found the cancellation, not the twin, at every node it had not reached. It is
	// the zero Report, with nothing failing, when the cancellation cut the first read.
	Last Report
}

// Wait reads the twin at once, then again every ReadInterval, until a read conforms
// (settled) or a read ends with the deadline From + Budget reached (expired); a budget of 0
// reads once. A context ended during a read or a sleep ends the wait after that read
// (cancelled), with the reads and seconds as reached, and a read it cut is not kept as
// Last. The record's claims are never waited on: Conforms does not count them.
// A node still unread when the budget expires is the caller's to word:
// Last.AllRead() says so, and the outcome is expired. A node a read could not dial is
// looked up again before the next (WaitOptions.Lab).
func Wait(ctx context.Context, in Input, assertions []Assertion, o WaitOptions) WaitResult {
	now := o.Now
	if now == nil {
		now = in.Now
	}
	if now == nil {
		now = time.Now
	}
	in.Now = now
	sleep := o.Sleep
	if sleep == nil {
		sleep = sleepUnder
	}
	from := o.From
	var res WaitResult
	for {
		if res.Reads > 0 && o.Lab != nil && res.Last.undialled() {
			if nodes, err := o.Lab(ctx); err == nil {
				in.Lab = nodes
			}
		}
		r := Read(ctx, in, assertions)
		res.Reads++
		if from.IsZero() {
			from = r.ReadAt
		}
		ended := now()
		res.AfterS = after(from, ended)
		switch {
		case r.Conforms():
			res.Last, res.Outcome = r, WaitSettled
			return res
		case ctx.Err() != nil:
			// The cancellation cut this read: Last stays the read before it.
			res.Outcome = WaitCancelled
			return res
		}
		res.Last = r
		if !ended.Before(from.Add(o.Budget)) {
			res.Outcome = WaitExpired
			return res
		}
		if err := sleep(ctx, ReadInterval); err != nil || ctx.Err() != nil {
			res.Outcome = WaitCancelled
			res.AfterS = after(from, now())
			return res
		}
	}
}

// after is the seconds from from to t, never below zero: a From taken on another clock
// (the workflow's, at the record) may be read a moment after it on this one.
func after(from, t time.Time) float64 {
	return max(0, t.Sub(from).Seconds())
}

// sleepUnder pauses for d, or until ctx ends.
func sleepUnder(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
