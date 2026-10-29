package intent_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

// withProbeKind adds FylgjaProbe to the fake's schema as Infrahub 1.11.2 answers it on a
// default branch holding schema/fylgja-probe.yaml (testdata/schema-fylgja-probe.json,
// recorded from the development host's main at hash 8a4f3bee… on 2026-10-29), less the
// attributes named in drop.
func withProbeKind(t *testing.T, f *fakeInfrahub, drop ...string) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(repoRoot(t), "internal", "intent", "testdata", "schema-fylgja-probe.json"))
	if err != nil {
		t.Fatal(err)
	}
	var node map[string]any
	if err := json.Unmarshal(raw, &node); err != nil {
		t.Fatal(err)
	}
	if node["kind"] != intent.ProbeKind {
		t.Fatalf("the recorded node is %v, not %s", node["kind"], intent.ProbeKind)
	}
	var kept []any
	for _, a := range node["attributes"].([]any) {
		if !slices.Contains(drop, a.(map[string]any)["name"].(string)) {
			kept = append(kept, a)
		}
	}
	node["attributes"] = kept
	f.mu.Lock()
	defer f.mu.Unlock()
	f.schema["nodes"] = append(f.schema["nodes"].([]any), node)
}

// probeNode is one FylgjaProbe as Infrahub's GraphQL answers the Probes query.
func probeNode(p probe.Probe) map[string]any {
	a, b := p.Endpoints[0], p.Endpoints[1]
	return map[string]any{
		"name": value(p.Name), "format": value(p.Format),
		"a_device": value(a.Device), "a_interface": value(a.Interface), "a_address": value(a.Address), "a_gateway": value(a.Gateway),
		"b_device": value(b.Device), "b_interface": value(b.Interface), "b_address": value(b.Address), "b_gateway": value(b.Gateway),
	}
}

// probeReader serves the fake and builds a probe reader for it.
func probeReader(f *fakeInfrahub) *intent.ProbeReader {
	srv := f.start("sentinel-token")
	return intent.NewProbeReader(srv.URL, "sentinel-token")
}

func probeCtx(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// The kind's presence and its ten attributes are read from the schema endpoint before any
// query, against the kind as Infrahub answers it for schema/fylgja-probe.yaml; what is
// missing is named, in ProbeFields' order. These are the first halves of
// probe.kind.absent. The description, which nothing reads, may be absent.
func TestProbeReaderChecksTheKind(t *testing.T) {
	for _, tc := range []struct {
		name    string
		present bool
		drop    []string
		missing []string
		message string // "": the kind serves the read
	}{
		{name: "present", present: true},
		{name: "description absent", present: true, drop: []string{"description"}},
		{name: "absent", message: "the default branch's schema has no kind FylgjaProbe"},
		{name: "one missing", present: true, drop: []string{"b_gateway"}, missing: []string{"b_gateway"},
			message: "kind FylgjaProbe on the default branch lacks the attribute b_gateway, which this build reads"},
		{name: "two missing", present: true, drop: []string{"a_address", "format"}, missing: []string{"format", "a_address"},
			message: "kind FylgjaProbe on the default branch lacks the attributes format, a_address, which this build reads"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			if tc.present {
				withProbeKind(t, f, tc.drop...)
			}
			err := probeReader(f).Check(probeCtx(t))
			if tc.message == "" {
				if err != nil {
					t.Fatalf("the kind with its ten attributes: %v", err)
				}
				return
			}
			var kindErr *intent.ProbeKindError
			if !errors.As(err, &kindErr) {
				t.Fatalf("want a *ProbeKindError, got %v", err)
			}
			if !slices.Equal(kindErr.Missing, tc.missing) {
				t.Errorf("Missing = %v, want %v", kindErr.Missing, tc.missing)
			}
			if err.Error() != tc.message {
				t.Errorf("message = %q, want %q", err, tc.message)
			}
			if f.count("/graphql") != 0 {
				t.Errorf("Check sent a query")
			}
		})
	}
}

// A page of two, answered out of name order: each object becomes the declaration's
// element, every one of its ten values verbatim in its place (name, format, endpoint a from
// the a_ attributes, b from the b_ ones), and the list comes back in name order. One page
// is asked for, of a hundred from the start, and the query selects the ten attributes and
// not the description.
func TestProbeReaderMapsAPageOfTwo(t *testing.T) {
	n1 := probe.Probe{Name: "n1-loop", Format: "ping", Endpoints: [2]probe.Endpoint{
		{Device: "n1", Interface: "ethernet-1/10", Address: "10.1.10.2/24", Gateway: "10.1.10.1"},
		{Device: "n2", Interface: "ethernet-1/11", Address: "10.1.11.2/24", Gateway: "10.1.11.1"},
	}}
	v6 := probe.Probe{Name: "v6-loop", Format: "ping-v6", Endpoints: [2]probe.Endpoint{
		{Device: "s1", Interface: "Ethernet7", Address: "2001:db8:7::2/64", Gateway: "2001:db8:7::1"},
		{Device: "e1", Interface: "Ethernet8", Address: "2001:db8:8::2/64", Gateway: "2001:db8:8::1"},
	}}
	f := newFakeInfrahub(t)
	withProbeKind(t, f)
	f.probes = []any{probeNode(v6), probeNode(n1)}

	got, err := probeReader(f).Probes(probeCtx(t))
	if err != nil {
		t.Fatal(err)
	}
	if want := []probe.Probe{n1, v6}; !reflect.DeepEqual(got, want) {
		t.Errorf("probes = %+v\nwant %+v", got, want)
	}
	asked := f.graphql("Probes")
	if len(asked) != 1 {
		t.Fatalf("asked Probes %d times, want once", len(asked))
	}
	if l, o := pageOf(asked[0].Variables); l != 100 || o != 0 {
		t.Errorf("asked limit %d offset %d, want 100 and 0", l, o)
	}
	for _, field := range intent.ProbeFields {
		if !strings.Contains(asked[0].Query, field+" ") {
			t.Errorf("the query does not select %s", field)
		}
	}
	if strings.Contains(asked[0].Query, "description") {
		t.Errorf("the query selects the description, which is never read")
	}
}

// Every page is read, a hundred at a time, and the list is in name order whatever the
// server answered.
func TestProbeReaderReadsEveryPage(t *testing.T) {
	f := newFakeInfrahub(t)
	withProbeKind(t, f)
	for i := 100; i >= 0; i-- {
		f.probes = append(f.probes, probeNode(probe.Probe{Name: fmt.Sprintf("p%03d", i), Format: "ping"}))
	}
	got, err := probeReader(f).Probes(probeCtx(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 101 || got[0].Name != "p000" || got[100].Name != "p100" {
		t.Fatalf("got %d probes from two pages, first %q, want 101 from p000", len(got), got[0].Name)
	}
	var offsets []int
	for _, req := range f.graphql("Probes") {
		_, o := pageOf(req.Variables)
		offsets = append(offsets, o)
	}
	if !slices.Equal(offsets, []int{0, 100}) {
		t.Errorf("pages asked at offsets %v, want [0 100]", offsets)
	}
}

// The kind with no object is an empty list, not nil: a snapshot's probes is a list, and
// [] is what it carries when the take has none.
func TestProbeReaderReadsAnEmptyList(t *testing.T) {
	f := newFakeInfrahub(t)
	withProbeKind(t, f)
	got, err := probeReader(f).Probes(probeCtx(t))
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "[]" {
		t.Errorf("no probe encodes as %s, want []", b)
	}
}

// The reader names no branch and pins nothing: the schema endpoint and GraphQL on their
// unnamed paths, with no query string, so the default branch answers whatever it is
// called.
func TestProbeReaderNamesNoBranch(t *testing.T) {
	f := newFakeInfrahub(t)
	withProbeKind(t, f)
	r := probeReader(f)
	if err := r.Check(probeCtx(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Probes(probeCtx(t)); err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, req := range f.served {
		paths = append(paths, req.Path)
		if req.RawQuery != "" {
			t.Errorf("%s carries a query string %q; the reader names no branch and pins nothing", req.Path, req.RawQuery)
		}
	}
	if want := []string{"/api/schema", "/graphql"}; !slices.Equal(paths, want) {
		t.Errorf("requests = %v, want %v", paths, want)
	}
}

// An unreachable Infrahub, a refused credential and a non-200 are errors that carry no
// credential, even from a server that quotes the request's own header back, and none is
// taken for the kind's absence. A refused credential names the variable to fix.
func TestProbeReaderKeepsTheCredentialOut(t *testing.T) {
	echo := func(status int) string {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"errors":["rejected key ` + r.Header.Get("X-INFRAHUB-KEY") + `"]}`))
		}))
		t.Cleanup(srv.Close)
		return srv.URL
	}
	closed := httptest.NewServer(http.NotFoundHandler())
	closed.Close()

	for _, tc := range []struct {
		name, address, want string
	}{
		{"401", echo(http.StatusUnauthorized), intent.EnvToken},
		{"500 quoting the key", echo(http.StatusInternalServerError), "<redacted>"},
		{"unreachable", closed.URL, "(the default branch)"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := intent.NewProbeReader(tc.address, "sentinel-token")
			_, probesErr := r.Probes(probeCtx(t))
			for what, err := range map[string]error{"Check": r.Check(probeCtx(t)), "Probes": probesErr} {
				if err == nil {
					t.Fatalf("%s: want an error", what)
				}
				var kindErr *intent.ProbeKindError
				if errors.As(err, &kindErr) {
					t.Errorf("%s: a transport failure reported as the kind's absence: %v", what, err)
				}
				if strings.Contains(err.Error(), "sentinel-token") {
					t.Errorf("%s: the credential reached the error: %v", what, err)
				}
				if !strings.Contains(err.Error(), tc.want) {
					t.Errorf("%s: error %q does not carry %q", what, err, tc.want)
				}
			}
		})
	}
}

// The reader is built from the variables a read uses, and refuses alike when one is unset.
func TestProbeReaderFromEnv(t *testing.T) {
	t.Setenv(intent.EnvAddress, "")
	t.Setenv(intent.EnvToken, "t")
	if _, err := intent.ProbeReaderFromEnv(); err == nil || err.Error() != intent.EnvAddress+" is not set" {
		t.Errorf("address unset: %v", err)
	}
	t.Setenv(intent.EnvAddress, "http://infrahub.invalid/")
	t.Setenv(intent.EnvToken, "")
	if _, err := intent.ProbeReaderFromEnv(); err == nil || err.Error() != intent.EnvToken+" is not set" {
		t.Errorf("token unset: %v", err)
	}
}
