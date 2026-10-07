package server

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The success detail names the operator's own kinds, not a count: its point is to show
// which kind satisfies each generic, and a number cannot say that.
func TestVerifiedGenericsRenderAsNames(t *testing.T) {
	got := describeGenerics([]findings.GenericKinds{
		{Generic: "FylgjaDevice", Kinds: []string{"NetworkDevice"}},
		{Generic: "FylgjaInterface", Kinds: []string{"NetworkInterface", "LoopbackInterface"}},
	})
	want := "FylgjaDevice ← NetworkDevice; FylgjaInterface ← NetworkInterface, LoopbackInterface"
	if got != want {
		t.Errorf("describeGenerics() = %q, want %q", got, want)
	}
}
