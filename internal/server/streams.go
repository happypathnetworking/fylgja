package server

import (
	"os"
	"sync"
)

// streams are the interrupt channels of the runs' requests that are open, by the stream
// identity each client named in Fylgja-Stream. It is the one thing the
// server holds across requests, and only while the request it belongs to is open: the
// entry is added when a run's request begins and removed when its handler returns (the note
// under D-014). No answer is made from it, and it is not a lock: two clients are refused by
// the fixed workflow identities alone.
type streams struct {
	mu    sync.Mutex
	chans map[string]chan os.Signal
}

func newStreams() *streams {
	return &streams{chans: map[string]chan os.Signal{}}
}

// streamCapacity is the interrupts held for a handler not yet reading them, as M12's signal
// channel held them.
const streamCapacity = 2

// open registers id for a request and returns the channel its interrupts arrive on, read
// by M12's startRun and followRun as they read the signal channel, and the function that
// removes it. An identity already open is refused.
func (s *streams) open(id string) (ch chan os.Signal, release func(), ok bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, taken := s.chans[id]; taken {
		return nil, nil, false
	}
	ch = make(chan os.Signal, streamCapacity)
	s.chans[id] = ch
	return ch, func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		delete(s.chans, id)
	}, true
}

// interrupt delivers one interrupt to id's request without waiting: a full channel drops
// it, as a third signal to M12's channel was dropped. False when no request is open under
// id.
func (s *streams) interrupt(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	ch, ok := s.chans[id]
	if !ok {
		return false
	}
	select {
	case ch <- os.Interrupt:
	default:
	}
	return true
}
