package server

import (
	"context"
	"errors"
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

	// Following stops first: a check could otherwise rebuild what the destroy removes, so a
	// Schedule that cannot be deleted refuses the destroy with nothing removed. A check in
	// flight is cancelled and its cleanup waited for; its progress is printed as it comes
	// (contracts/cli.md, step 1a).
	stop, err := svc.StopFollowing(ctx, func(e provision.Event) {
		opts.c.eventFrame(e)
		printEvent(opts, e)
	})
	if stop.Stopped {
		opts.note("following of branch %s stopped", stop.Branch)
	}
	if err != nil {
		// The Schedule may be gone although what followed its deletion failed: a second
		// destroy would find none to name, so this one says it stopped.
		failure := startFailure(op, subject, findings.StepFollow, err)
		if r, ok := failure.(*result); ok && stop.Stopped {
			r.doc.Following = &findings.FollowingBlock{Branch: stop.Branch, Stopped: true}
		}
		return failure
	}

	// Only the destroy run's own steps are followed for a failure to name. A provisioning run
	// or a step run (M11) it cancels and waits for first is not where the destroy is: a
	// failure while waiting for that run is a failure to start. Each is announced as it is
	// cancelled and as it closes, a step run's as "step run <id> closed: diverged" once its
	// record is written (contracts/cli.md). Following stopped again after that run closed prints
	// its own line as it comes (step 2a); failing to stop it is a failure at step follow, as
	// above.
	//
	// The destroy is started on a context the request's end does not reach, so a client that
	// goes away, or a server that stops, while the start waits for a worker leaves the destroy
	// run for that worker, as M12's killed process left it, rather than terminating it. Once the
	// destroy run's own progress is seen, it is followed on the request's context: a client gone
	// by then stops the following and nothing else.
	//
	// The start frame comes just before the start, as a create's does, so an answer the
	// server's stop cuts from here says a run may have been started and was not cancelled; one
	// cut while following stopped has none, and says nothing of a run. It opens no stream: the
	// destroy still takes no interrupt. As for every run, it is written only to a request still
	// open, and a client gone before it starts nothing.
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
	run, err := svc.StartDestroy(runCtx, func(e provision.Event) {
		opts.c.eventFrame(e)
		printEvent(opts, e)
		if e.WorkflowID == provision.WorkflowDestroy {
			followed.observe(e)
			startedOnce.Do(func() { close(started) })
		}
	})
	// The later stop names the branch when both stopped one.
	if run.FollowingStopped.Stopped {
		stop = run.FollowingStopped
	}
	if err != nil {
		step := followed.get()
		var stopFailed *provision.FollowStopError
		if errors.As(err, &stopFailed) {
			step = findings.StepFollow
		}
		failure := startFailure(op, subject, step, err)
		if r, ok := failure.(*result); ok && stop.Stopped {
			r.doc.Following = &findings.FollowingBlock{Branch: stop.Branch, Stopped: true}
		}
		return failure
	}
	subject.RunID = run.RunID

	// What was removed is printed even when something remains: the findings, on stderr,
	// say what is left and how to clear it.
	printCleanup(opts, run.Result.Cleanup)
	return &result{doc: provision.DestroyDocument(subject, run.Result, stop)}
}
