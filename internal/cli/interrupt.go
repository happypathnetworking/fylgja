package cli

import (
	"context"
	"errors"
	"os"
	"os/signal"
	"sync"

	"github.com/happypathnetworking/fylgja/internal/api"
)

// notifyInterrupt delivers SIGINT to a command that is starting or following a run. A
// variable so command tests can interrupt without signalling the test process.
var notifyInterrupt = func() (<-chan os.Signal, func()) {
	ch := make(chan os.Signal, 2)
	signal.Notify(ch, os.Interrupt)
	return ch, func() { signal.Stop(ch) }
}

// interrupts carry the operator's interrupts to the server once it has begun to start a
// run: each is the interrupt call for the answer's stream, sent one at a time and in order,
// so the server's handler reads them as M12's command read its signals. Before the
// start frame nothing is installed, and an interrupt ends the client by the signal.
type interrupts struct {
	stopNotify func()
	cancel     context.CancelFunc
	done       chan struct{}
	finished   chan struct{}

	mu  sync.Mutex
	err error
	// delivered is whether an interrupt reached the server's open answer (204): the run it
	// names has been asked to cancel, or its start abandoned.
	delivered bool
}

// arm installs the interrupt handler for stream. An interrupt that cannot be delivered
// abandons the answer, whose reader then reports why.
func arm(ctx context.Context, client *api.Client, stream string, abandon func()) *interrupts {
	sigs, stopNotify := notifyInterrupt()
	ctx, cancel := context.WithCancel(ctx)
	in := &interrupts{stopNotify: stopNotify, cancel: cancel, done: make(chan struct{}), finished: make(chan struct{})}
	go func() {
		defer close(in.finished)
		for {
			select {
			case <-in.done:
				return
			case <-sigs:
				err := client.Interrupt(ctx, stream)
				if err == nil {
					in.mu.Lock()
					in.delivered = true
					in.mu.Unlock()
					continue
				}
				// An answer that has just ended is read on to its document.
				if errors.Is(err, api.ErrStreamEnded) {
					continue
				}
				if ctx.Err() != nil {
					return
				}
				in.mu.Lock()
				in.err = err
				in.mu.Unlock()
				abandon()
				return
			}
		}
	}()
	return in
}

// failure is the interrupt that could not be delivered, if one could not.
func (in *interrupts) failure() error {
	in.mu.Lock()
	defer in.mu.Unlock()
	return in.err
}

// deliveredAny is whether an interrupt reached the server.
func (in *interrupts) deliveredAny() bool {
	in.mu.Lock()
	defer in.mu.Unlock()
	return in.delivered
}

// stop uninstalls the handler and waits for an interrupt in flight to be let go.
func (in *interrupts) stop() {
	close(in.done)
	in.cancel()
	in.stopNotify()
	<-in.finished
}
