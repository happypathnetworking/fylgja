package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"net"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/openconfig/gnmi/proto/gnmi"
	"go.temporal.io/sdk/temporal"
	"google.golang.org/grpc"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Every encoding the package format allows maps to its wire value, and the list here is
// the schema's list: a new enum value without a mapping fails this test, not a probe.
func TestGNMIEncodingForEverySchemaValue(t *testing.T) {
	want := map[string]gnmi.Encoding{
		"json":      gnmi.Encoding_JSON,
		"json_ietf": gnmi.Encoding_JSON_IETF,
		"proto":     gnmi.Encoding_PROTO,
		"ascii":     gnmi.Encoding_ASCII,
		"bytes":     gnmi.Encoding_BYTES,
	}
	for name, enc := range want {
		got, err := gnmiEncoding(name)
		if err != nil || got != enc {
			t.Errorf("gnmiEncoding(%q) = %v, %v; want %v", name, got, err, enc)
		}
	}
	for _, bad := range []string{"", "JSON_IETF", "cli"} {
		if _, err := gnmiEncoding(bad); err == nil {
			t.Errorf("gnmiEncoding(%q) succeeded; want an error", bad)
		}
	}

	schema, err := psp.SchemaBytes()
	if err != nil {
		t.Fatal(err)
	}
	var doc any
	if err := json.Unmarshal(schema, &doc); err != nil {
		t.Fatal(err)
	}
	enum := encodingEnum(doc)
	if enum == nil {
		t.Fatal("psp.schema.json has no readiness encoding enum")
	}
	if keys := slices.Sorted(maps.Keys(want)); !slices.Equal(keys, enum) {
		t.Errorf("mapped encodings %v, schema allows %v", keys, enum)
	}
}

// encodingEnum finds readiness.properties.encoding.enum anywhere in the schema, sorted.
func encodingEnum(node any) []string {
	switch n := node.(type) {
	case map[string]any:
		if r, ok := n["readiness"].(map[string]any); ok {
			if props, ok := r["properties"].(map[string]any); ok {
				if enc, ok := props["encoding"].(map[string]any); ok {
					if values, ok := enc["enum"].([]any); ok {
						var out []string
						for _, v := range values {
							out = append(out, fmt.Sprint(v))
						}
						slices.Sort(out)
						return out
					}
				}
			}
		}
		for _, v := range n {
			if found := encodingEnum(v); found != nil {
				return found
			}
		}
	case []any:
		for _, v := range n {
			if found := encodingEnum(v); found != nil {
				return found
			}
		}
	}
	return nil
}

func TestGNMIPath(t *testing.T) {
	type elem struct {
		name string
		keys map[string]string
	}
	for _, c := range []struct {
		in   string
		want []elem
	}{
		{"/system/information", []elem{{name: "system"}, {name: "information"}}},
		{"/interface[name=ethernet-1/1]/state", []elem{{name: "interface", keys: map[string]string{"name": "ethernet-1/1"}}, {name: "state"}}},
		{"/a[k1=v1][k2=v2]", []elem{{name: "a", keys: map[string]string{"k1": "v1", "k2": "v2"}}}},
		{"/", nil},
	} {
		p, err := gnmiPath(c.in)
		if err != nil {
			t.Errorf("gnmiPath(%q): %v", c.in, err)
			continue
		}
		var got []elem
		for _, e := range p.GetElem() {
			got = append(got, elem{name: e.GetName(), keys: e.GetKey()})
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("gnmiPath(%q) = %+v, want %+v", c.in, got, c.want)
		}
	}
	for _, bad := range []string{"system/information", "/a//b", "/a[k=v", "/a[=v]", "/a[k]", "/a/", "/a]b"} {
		if _, err := gnmiPath(bad); err == nil {
			t.Errorf("gnmiPath(%q) succeeded; want an error", bad)
		}
	}
}

// The probe password reaches no error, no readiness.timeout finding and no log line, even
// with debug logging on and the probe failing on every attempt.
func TestProbePasswordNeverReachesOutput(t *testing.T) {
	t.Parallel()
	const sentinel = "fylgja-probe-password-sentinel-7c1e"

	var logs lockedBuffer
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
	a := testActivities(t, &fakeRunner{})
	a.Log = logger
	a.Prober = GNMIProber{Log: logger}
	a.Getenv = mapEnv(map[string]string{"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": sentinel})
	probe := srlinuxProbe()
	probe.Port = 1 // nothing listens: every attempt fails
	env := activityEnv(a.AwaitReadiness, wire.ActAwaitReadiness)

	_, err := env.ExecuteActivity(wire.ActAwaitReadiness,
		wire.ReadinessInput{Node: "n1", MgmtIPv4: "127.0.0.1", Probe: probe, TimeoutS: 2})
	var appErr *temporal.ApplicationError
	if !errors.As(err, &appErr) || appErr.Type() != findings.RuleReadinessTimeout {
		t.Fatalf("error = %v, want an application error of type %s", err, findings.RuleReadinessTimeout)
	}
	var f findings.Finding
	if err := appErr.Details(&f); err != nil {
		t.Fatal(err)
	}
	if f.Object != "n1" || f.Step != findings.StepReadiness || !strings.Contains(f.Message, "gnmi_get /system/information json_ietf") {
		t.Errorf("finding = %+v, want node n1, step readiness, naming the probe", f)
	}

	log := logs.String()
	for label, text := range map[string]string{"error": err.Error(), "finding": fmt.Sprintf("%+v", f), "log": log} {
		if strings.Contains(text, sentinel) {
			t.Errorf("the probe password reached the %s:\n%s", label, text)
		}
	}
	// The check means something only if the probe ran and logged: the variable is named.
	if !strings.Contains(log, "FYLGJA_SRLINUX_PASSWORD") || !strings.Contains(log, "127.0.0.1:1") {
		t.Errorf("the log does not show the probe running against 127.0.0.1:1:\n%s", log)
	}
}

func TestRedactRemovesTheSecret(t *testing.T) {
	err := redact(errors.New(`code=Unauthenticated msg="bad login hunter2 for admin"`), "hunter2")
	if strings.Contains(err.Error(), "hunter2") || !strings.Contains(err.Error(), "[redacted]") {
		t.Errorf("redact left %q", err)
	}
	orig := errors.New("connection refused")
	if redact(orig, "hunter2") != orig {
		t.Error("redact replaced an error that did not carry the secret")
	}
}

// lockedBuffer is a bytes.Buffer safe for the activity's goroutines and the test.
type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *lockedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// startStubGNMIPlaintext serves stub over plaintext gRPC, as containerlab's default cEOS
// configuration does — `management api gnmi` with `transport grpc default` and no SSL
// profile — and returns its address.
func startStubGNMIPlaintext(t *testing.T, stub *stubGNMI) string {
	t.Helper()
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := grpc.NewServer()
	gnmi.RegisterGNMIServer(srv, stub)
	go func() { _ = srv.Serve(lis) }()
	t.Cleanup(srv.Stop)
	return lis.Addr().String()
}

// The one dial the probe and the conformance reader share follows the probe's tls:
// false reaches a plaintext node, nil and true keep M2's TLS dial,
// and a mismatch either way is the transport's own error with the password nowhere in it.
// The by_hand line names the flag the probe dialled with, so an operator repeats the dial
// that was made and not another.
func TestProbeDialsTheTransportTheProbeNames(t *testing.T) {
	t.Parallel()
	plaintext := startStubGNMIPlaintext(t, r3Stub())
	overTLS := startStubGNMI(t, r3Stub())
	getenv := mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername, "FYLGJA_TEST_PASSWORD": stubPassword})
	no, yes := false, true

	for _, c := range []struct {
		name string
		addr string
		tls  *bool
		want string // a phrase the transport's error carries; "" when the probe succeeds
	}{
		{name: "plaintext node, tls false", addr: plaintext, tls: &no},
		{name: "TLS node, tls unset", addr: overTLS, tls: nil},
		{name: "TLS node, tls true", addr: overTLS, tls: &yes},
		{name: "plaintext node dialled TLS", addr: plaintext, tls: nil,
			want: "first record does not look like a TLS handshake"},
		{name: "TLS node dialled plaintext", addr: overTLS, tls: &no, want: "code=Unavailable"},
	} {
		t.Run(c.name, func(t *testing.T) {
			var logs lockedBuffer
			logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
			probe := stubProbe
			probe.Path = "/system/name/host-name"
			probe.TLS = c.tls

			err := GNMIProber{Log: logger}.Probe(context.Background(), c.addr, probe, getenv)
			switch {
			case c.want == "" && err != nil:
				t.Fatalf("probe of %s failed: %v", c.addr, err)
			case c.want == "":
				return
			case err == nil:
				t.Fatalf("probe of %s succeeded; want the transport's refusal", c.addr)
			case !strings.Contains(err.Error(), c.want):
				t.Errorf("error = %q, want the transport's error naming %q", err, c.want)
			}
			// The second lock: a transport or server that echoes the request's metadata
			// back does not put the password into the error or the log.
			for label, text := range map[string]string{"error": err.Error(), "log": logs.String()} {
				if strings.Contains(text, stubPassword) {
					t.Errorf("the probe password reached the %s:\n%s", label, text)
				}
			}
		})
	}
}

// The by_hand line of the readiness probe dials as the probe did: --skip-verify for TLS,
// --insecure for plaintext. Read from the flag itself, so the two
// cannot drift apart.
func TestGNMICTLSFlagFollowsTheProbe(t *testing.T) {
	no, yes := false, true
	for _, c := range []struct {
		tls  *bool
		want string
	}{{nil, "--skip-verify"}, {&yes, "--skip-verify"}, {&no, "--insecure"}} {
		probe := stubProbe
		probe.TLS = c.tls
		if got := gnmicTLSFlag(probe); got != c.want {
			t.Errorf("gnmicTLSFlag(tls=%v) = %q, want %q", c.tls, got, c.want)
		}
	}
}
