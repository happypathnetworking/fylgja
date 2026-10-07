package provision

import (
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab"
)

// The worker's heartbeat throttle is pinned because nothing else would notice it change.
// At the SDK's default, 80% of the heartbeat timeout, a cancellation reaches a running clab
// about 24s late. At 2s, the SDK gave up on a heartbeat call after 1s, and
// one stall cut a deploy short on a host with nothing else running; at 5s it waited
// 2.5s, and four of six tier-3 runs still lost a working deploy to it once the host also
// carried Infrahub; at 10s it waits about 5s (D-030). It must not
// exceed the heartbeat interval, or it would delay the heartbeats a cancellation travels
// on, and it must stay well inside the heartbeat timeout.
func TestWorkerHeartbeatThrottle(t *testing.T) {
	if got := workerOptions().MaxHeartbeatThrottleInterval; got != 10*time.Second {
		t.Errorf("MaxHeartbeatThrottleInterval = %v, want 10s", got)
	}
	if HeartbeatThrottle > lab.HeartbeatInterval {
		t.Errorf("throttle %v exceeds the heartbeat interval %v: cancellations would wait on it", HeartbeatThrottle, lab.HeartbeatInterval)
	}
	if HeartbeatThrottle >= HeartbeatTimeout/2 {
		t.Errorf("throttle %v is not well inside the heartbeat timeout %v", HeartbeatThrottle, HeartbeatTimeout)
	}
}
