package snapshot_test

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// The snapshot keeps its own copy of the stages' observed_at form, since it imports
// nothing of the stages; this external test holds the two equal, so a take's
// observed_at and a read's are written one way.
func TestObservedAtLayoutIsTheStages(t *testing.T) {
	if snapshot.ObservedAtLayout != stage.ObservedAtFormat {
		t.Errorf("snapshot.ObservedAtLayout = %q, stage.ObservedAtFormat = %q", snapshot.ObservedAtLayout, stage.ObservedAtFormat)
	}
}
