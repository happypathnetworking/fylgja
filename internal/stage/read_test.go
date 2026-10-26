package stage

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// A read under a scope that is not tag:<name> is refused before any connection, as an
// operational failure naming the remedy (017; FR-020). The server refuses a request's
// scope at start, so the one way here is a following twin created before 017, whose
// Schedule's ReconcileInput names no scope and whose checks read under "": read, it would
// filter by an empty tag and record tag: in the envelope. Infrahub is never asked.
func TestReadRefusesAScopeNotTagged(t *testing.T) {
	var asked atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asked.Add(1)
		http.Error(w, "unexpected", http.StatusTeapot)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(intent.EnvAddress, srv.URL)
	t.Setenv(intent.EnvToken, "sentinel-read-token")
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}

	for _, scope := range []string{"", "fylgja", "tag:"} {
		snapshot, list, err := Read(t.Context(), "fylgja-fixture", "", scope, reg, time.Now().UTC().Format(ObservedAtFormat))
		if err == nil || snapshot != nil || list != nil {
			t.Fatalf("scope %q: CTM %v, findings %v, error %v; want an error alone", scope, snapshot, list, err)
		}
		if msg := err.Error(); !strings.Contains(msg, `scope "`+scope+`", which is not tag:<name>`) ||
			!strings.HasSuffix(msg, "fylgja twin destroy clears it") {
			t.Errorf("scope %q: %q; want it named and fylgja twin destroy as the remedy", scope, msg)
		}
	}
	if n := asked.Load(); n != 0 {
		t.Errorf("Infrahub was asked %d times", n)
	}
}
