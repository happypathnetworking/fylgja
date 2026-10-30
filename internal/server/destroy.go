package server

import (
	"context"
	"sync"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

func runDestroy(ctx context.Context, opts *options) error {
	const op = findings.OpTwinDestroy
	subject := &findings.Subject{}

	if ctx == nil {
		ctx = context.Background()
	}
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()

	// Only the destroy run's own steps are followed for a failure to name. A provisioning run or
	// a step run (M11) it cancels and waits for first is not where the destroy is: a failure
	// while waiting for that run is a failure to start. Each is announced as it is cancelled and
	// as it closes, a step run's as "step run <id> closed: diverged" once its record is written
	// (contracts/cli.md). Nothing else is stopped first: nothing follows a branch (019), and no
	// rehearsal runs in the core (020).
	//
	// The destroy is started on a context the request's end does not reach, so a client that
	// goes away, or a server that stops, while the start waits for a worker leaves the destroy
	// run for that worker, as M12's killed process left it, rather than terminating it. Once the
	// destroy run's own progress is seen, it is followed on the request's context: a client gone
	// by then stops the following and nothing else.
	//
	// The start frame comes just before the start, as a create's does, so an answer the
	// server's stop cuts from here says a run may have been started and was not cancelled. It
	// opens no stream: the destroy still takes no interrupt. As for every run, it is written
	// only to a request still open, and a client gone before it starts nothing.
	//
	// Under detach (020, R-03) the runs it cancels first are still waited for, since the
	// destroy run starts only once they have closed, and the answer ends at the destroy run's
	// identity once a worker has taken it, or once it has attached to one in flight.
	if _, err := opts.c.startFrame(provision.WorkflowDestroy); err != nil {
		return goneBeforeStart(op, subject, provision.WorkflowDestroy, err)
	}
	runCtx, stopFollowing := context.WithCancel(context.WithoutCancel(ctx))
	defer stopFollowing()
	started := make(chan struct{})
	var startedOnce sync.Once
	go func() {
		select {
		case <-ctx.Done():
		case <-runCtx.Done():
			return
		}
		select {
		case <-started:
			stopFollowing()
		case <-runCtx.Done():
		}
	}()
	followed := &followedStep{}
	start := svc.StartDestroy
	if opts.detach {
		start = svc.StartDestroyDetached
	}
	run, err := start(runCtx, func(e provision.Event) {
		opts.c.eventFrame(e)
		printEvent(opts, e)
		if e.WorkflowID == provision.WorkflowDestroy {
			followed.observe(e)
			startedOnce.Do(func() { close(started) })
		}
	})
	if err != nil {
		return startFailure(op, subject, followed.get(), err)
	}
	subject.RunID = run.RunID
	if opts.detach {
		// The stream names the destroy run in a notice alone; the detached answer writes its
		// run frame, so the client has the identity it reads the run by (R-03).
		opts.c.runFrame(provision.WorkflowDestroy, run.RunID)
		return detached(op, subject, provision.WorkflowDestroy, run.RunID, nil)
	}

	// What was removed is printed even when something remains: the findings, on stderr,
	// say what is left and how to clear it.
	printCleanup(opts, run.Result.Cleanup)
	return &result{doc: provision.DestroyDocument(subject, run.Result)}
}
