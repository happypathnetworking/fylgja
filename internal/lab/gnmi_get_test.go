package lab

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"log/slog"
	"math/big"
	"net"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/openconfig/gnmi/proto/gnmi"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The login the stub node accepts. The password is a sentinel, so a leak is unambiguous.
const (
	stubUsername = "admin"
	stubPassword = "fylgja-reader-password-sentinel-3b9d"
)

// stubGNMI answers Get as SR Linux 24.7.1 answered it, keyed by the
// requested path: a leaf at the leaf, a subtree at its list entry, and no update for a
// path that holds nothing. It refuses a wrong login and, as a careless server might,
// echoes the password in the refusal, so the reader's redaction is what is tested.
type stubGNMI struct {
	gnmi.UnimplementedGNMIServer

	answers map[string]*gnmi.Notification

	mu        sync.Mutex
	username  string
	password  string
	encodings []gnmi.Encoding
}

func (s *stubGNMI) Get(ctx context.Context, req *gnmi.GetRequest) (*gnmi.GetResponse, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	username, password := first(md.Get("username")), first(md.Get("password"))
	s.mu.Lock()
	s.username, s.password = username, password
	s.encodings = append(s.encodings, req.GetEncoding())
	s.mu.Unlock()
	if username != stubUsername || password != stubPassword {
		return nil, status.Errorf(codes.Unauthenticated, "authentication failed for %s with password %s", username, password)
	}
	asked := "/" + pathText(nil, req.GetPath()[0])
	n, ok := s.answers[asked]
	if !ok {
		return nil, status.Errorf(codes.NotFound, "the stub has no answer for %s", asked)
	}
	return &gnmi.GetResponse{Notification: []*gnmi.Notification{n}}, nil
}

func (s *stubGNMI) login() (string, string, []gnmi.Encoding) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.username, s.password, append([]gnmi.Encoding(nil), s.encodings...)
}

func first(v []string) string {
	if len(v) == 0 {
		return ""
	}
	return v[0]
}

// elems builds path elements from `name` or `name[k=v]` strings.
func elems(names ...string) *gnmi.Path {
	p := &gnmi.Path{}
	for _, n := range names {
		e := &gnmi.PathElem{Name: n}
		if name, key, ok := strings.Cut(n, "["); ok {
			k, v, _ := strings.Cut(strings.TrimSuffix(key, "]"), "=")
			e = &gnmi.PathElem{Name: name, Key: map[string]string{k: v}}
		}
		p.Elem = append(p.Elem, e)
	}
	return p
}

func jsonIETF(s string) *gnmi.TypedValue {
	return &gnmi.TypedValue{Value: &gnmi.TypedValue_JsonIetfVal{JsonIetfVal: []byte(s)}}
}

// startStubGNMI serves stub over TLS with a certificate generated here, self-signed as
// a booting node's is, and returns its address.
func startStubGNMI(t *testing.T, stub gnmi.GNMIServer) string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "stub-node"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		IPAddresses:  []net.IP{net.ParseIP("127.0.0.1")},
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := grpc.NewServer(grpc.Creds(credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}},
	})))
	gnmi.RegisterGNMIServer(srv, stub)
	go func() { _ = srv.Serve(lis) }()
	t.Cleanup(srv.Stop)
	return lis.Addr().String()
}

// r3Stub answers the three shapes of an SR Linux 24.7.1 Get answer, and a leaf whose
// notification carries
// a prefix, so the reader is seen joining the two.
func r3Stub() *stubGNMI {
	return &stubGNMI{answers: map[string]*gnmi.Notification{
		"/system/name/host-name": {Update: []*gnmi.Update{{
			Path: elems("srl_nokia-system:system", "srl_nokia-system-name:name", "host-name"),
			Val:  jsonIETF(`"n1"`),
		}}},
		"/system/lldp/interface[name=ethernet-1/1]/neighbor": {Update: []*gnmi.Update{{
			Path: elems("srl_nokia-system:system", "srl_nokia-lldp:lldp", "interface[name=ethernet-1/1]"),
			Val:  jsonIETF(`{"neighbor":[{"id":"1A:EB:01:FF:00:00","system-name":"n2","port-id":"ethernet-1/1","port-id-type":"INTERFACE_NAME"}]}`),
		}}},
		"/system/lldp/interface[name=ethernet-1/3]/neighbor": {},
		"/system/information/version": {
			Prefix: elems("srl_nokia-system:system"),
			Update: []*gnmi.Update{{
				Path: elems("srl_nokia-system-info:information", "version"),
				Val:  jsonIETF(`"v24.7.1-330-g38f237abfe"`),
			}},
		},
	}}
}

// r6Stub answers the shapes cEOS 4.32.0.2F answers in: a leaf at the leaf, a list
// requested whole as one update per keyed entry, and the same list one container higher as
// one update with the list inside its value. Two entries under Ethernet2, where cEOS
// answered one, so that the order every update is kept in is visible.
func r6Stub() *stubGNMI {
	entry := func(id, farNode, farPort string) string {
		return `{"openconfig-lldp:id":"` + id + `","openconfig-lldp:state":{"system-name":"` + farNode +
			`","port-id":"` + farPort + `","port-id-type":"INTERFACE_NAME"}}`
	}
	return &stubGNMI{answers: map[string]*gnmi.Notification{
		"/system/state/hostname": {Update: []*gnmi.Update{{
			Path: elems("openconfig-system:system", "state", "hostname"),
			Val:  jsonIETF(`"e2"`),
		}}},
		"/lldp/interfaces/interface[name=Ethernet2]/neighbors/neighbor": {Update: []*gnmi.Update{
			{
				Path: elems("lldp", "interfaces", "interface[name=Ethernet2]", "neighbors", "neighbor[id=1]"),
				Val:  jsonIETF(entry("1", "s1", "ethernet-1/3")),
			},
			{
				Path: elems("lldp", "interfaces", "interface[name=Ethernet2]", "neighbors", "neighbor[id=2]"),
				Val:  jsonIETF(entry("2", "e1", "Ethernet7")),
			},
		}},
		"/lldp/interfaces/interface[name=Ethernet128]/neighbors": {Update: []*gnmi.Update{{
			Path: elems("lldp", "interfaces", "interface[name=Ethernet128]", "neighbors"),
			Val:  jsonIETF(`{"openconfig-lldp:neighbor":[` + entry("1", "s1", "ethernet-1/4") + `]}`),
		}}},
	}}
}

// stubProbe is a package's readiness probe as the reader takes it: only the encoding and
// the login's variable names are used; the path read is the caller's.
var stubProbe = wire.Probe{
	Transport:   "gnmi_get",
	Path:        "/system/information",
	Encoding:    "json_ietf",
	UsernameEnv: "FYLGJA_TEST_USERNAME",
	PasswordEnv: "FYLGJA_TEST_PASSWORD",
}

// GNMIReader.Get returns each of r3Stub's shapes as the node wrote it: the update's path with
// its module prefixes, the value decoded, and no update at all for a path that holds
// nothing. The login arrives as metadata, the encoding is the probe's.
func TestGNMIReaderReadsR3sShapes(t *testing.T) {
	t.Parallel()
	stub := r3Stub()
	addr := startStubGNMI(t, stub)
	probe := stubProbe
	getenv := mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername, "FYLGJA_TEST_PASSWORD": stubPassword})
	reader := GNMIReader{}

	for _, c := range []struct {
		path string
		want verify.Answer
	}{
		{"/system/name/host-name", verify.Answer{Updates: []verify.Update{{
			Path: "srl_nokia-system:system/srl_nokia-system-name:name/host-name", Value: "n1"}}}},
		{"/system/lldp/interface[name=ethernet-1/1]/neighbor", verify.Answer{Updates: []verify.Update{{
			Path: "srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]",
			Value: map[string]any{"neighbor": []any{map[string]any{
				"id": "1A:EB:01:FF:00:00", "system-name": "n2", "port-id": "ethernet-1/1", "port-id-type": "INTERFACE_NAME"}}},
		}}}},
		{"/system/lldp/interface[name=ethernet-1/3]/neighbor", verify.Answer{}},
		{"/system/information/version", verify.Answer{Updates: []verify.Update{{
			Path: "srl_nokia-system:system/srl_nokia-system-info:information/version", Value: "v24.7.1-330-g38f237abfe"}}}},
	} {
		got, err := reader.Get(context.Background(), addr, probe, c.path, getenv)
		if err != nil {
			t.Errorf("Get %s: %v", c.path, err)
			continue
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("Get %s = %#v, want %#v", c.path, got, c.want)
		}
	}

	username, password, encodings := stub.login()
	if username != stubUsername || password != stubPassword {
		t.Errorf("the node saw login %q/%q, want the variables' values", username, password)
	}
	for _, e := range encodings {
		if e != gnmi.Encoding_JSON_IETF {
			t.Errorf("a Get was sent with encoding %v, want the probe's JSON_IETF", e)
		}
	}
	if len(encodings) != 4 {
		t.Errorf("the node answered %d Gets, want 4: one per read, no retry", len(encodings))
	}
}

// A refused login comes back as an error naming the code, with the password the server
// echoed redacted; nor does the debug log carry it, while naming the variable.
func TestGNMIReaderNeverPrintsThePassword(t *testing.T) {
	t.Parallel()
	const wrong = "fylgja-wrong-password-sentinel-51aa"
	addr := startStubGNMI(t, r3Stub())
	probe := stubProbe

	var logs lockedBuffer
	reader := GNMIReader{Log: slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))}
	_, err := reader.Get(context.Background(), addr, probe, "/system/name/host-name",
		mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername, "FYLGJA_TEST_PASSWORD": wrong}))
	if err == nil {
		t.Fatal("Get with a wrong password succeeded")
	}
	if !strings.Contains(err.Error(), "code=Unauthenticated") || !strings.Contains(err.Error(), "[redacted]") {
		t.Errorf("error = %q, want the refusal's code with the echoed password redacted", err)
	}
	for label, text := range map[string]string{"error": err.Error(), "log": logs.String()} {
		if strings.Contains(text, wrong) {
			t.Errorf("the password reached the %s:\n%s", label, text)
		}
	}
	if !strings.Contains(logs.String(), "FYLGJA_TEST_PASSWORD") || !strings.Contains(logs.String(), addr) {
		t.Errorf("the log does not show the read against %s, naming the variable:\n%s", addr, logs.String())
	}
}

// An unset login variable is named, and nothing is dialled.
func TestGNMIReaderNamesAnUnsetLogin(t *testing.T) {
	t.Parallel()
	probe := stubProbe
	_, err := GNMIReader{}.Get(context.Background(), "127.0.0.1:1", probe, "/system/name/host-name",
		mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername}))
	if err == nil || err.Error() != "probe login variable FYLGJA_TEST_PASSWORD is unset" {
		t.Errorf("error = %v, want the unset variable named", err)
	}
}

// The answer carries every update of every notification, in order:
// a list a node answers one keyed entry at a time comes back as that many updates, where
// M6's reader kept only the first and would have read one neighbour of two. The leaf and
// the container-with-the-list-inside shapes come back as one update each, as M6 read them.
func TestGNMIReaderCarriesEveryUpdate(t *testing.T) {
	t.Parallel()
	addr := startStubGNMI(t, r6Stub())
	getenv := mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername, "FYLGJA_TEST_PASSWORD": stubPassword})

	entry := func(id, farNode, farPort string) map[string]any {
		return map[string]any{"openconfig-lldp:id": id, "openconfig-lldp:state": map[string]any{
			"system-name": farNode, "port-id": farPort, "port-id-type": "INTERFACE_NAME"}}
	}
	for _, c := range []struct {
		name, path string
		want       verify.Answer
	}{
		{name: "a leaf", path: "/system/state/hostname", want: verify.Answer{Updates: []verify.Update{{
			Path: "openconfig-system:system/state/hostname", Value: "e2"}}}},
		{name: "one update per keyed entry", path: "/lldp/interfaces/interface[name=Ethernet2]/neighbors/neighbor",
			want: verify.Answer{Updates: []verify.Update{
				{Path: "lldp/interfaces/interface[name=Ethernet2]/neighbors/neighbor[id=1]", Value: entry("1", "s1", "ethernet-1/3")},
				{Path: "lldp/interfaces/interface[name=Ethernet2]/neighbors/neighbor[id=2]", Value: entry("2", "e1", "Ethernet7")},
			}}},
		{name: "one update with the list inside", path: "/lldp/interfaces/interface[name=Ethernet128]/neighbors",
			want: verify.Answer{Updates: []verify.Update{{
				Path:  "lldp/interfaces/interface[name=Ethernet128]/neighbors",
				Value: map[string]any{"openconfig-lldp:neighbor": []any{entry("1", "s1", "ethernet-1/4")}},
			}}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			got, err := GNMIReader{}.Get(context.Background(), addr, stubProbe, c.path, getenv)
			if err != nil {
				t.Fatalf("Get %s: %v", c.path, err)
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("Get %s = %#v,\nwant %#v", c.path, got, c.want)
			}
			if !got.Present() {
				t.Error("Present() is false on an answer with updates")
			}
		})
	}
	if (verify.Answer{}).Present() {
		t.Error("Present() is true on an answer with no update")
	}
}

// silentGNMI accepts the connection and never answers a Get, as a stalled node's gNMI server
// does: the Get ends when the caller's deadline does.
type silentGNMI struct{ gnmi.UnimplementedGNMIServer }

func (silentGNMI) Get(ctx context.Context, _ *gnmi.GetRequest) (*gnmi.GetResponse, error) {
	<-ctx.Done()
	return nil, ctx.Err()
}

// A Get the node never answered, nothing accepting the connection (Unavailable) or nothing
// answering before the deadline (DeadlineExceeded), is a *verify.Unanswered, so a read dials
// that node no further; a node's refusal of the path is not. Its text is gnmiGet's either
// way.
func TestGNMIReaderMarksAnUnansweredGet(t *testing.T) {
	t.Parallel()
	getenv := mapEnv(map[string]string{"FYLGJA_TEST_USERNAME": stubUsername, "FYLGJA_TEST_PASSWORD": stubPassword})
	closed, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	refusing := closed.Addr().String()
	_ = closed.Close()
	short := func() context.Context {
		ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
		t.Cleanup(cancel)
		return ctx
	}
	for _, c := range []struct {
		name       string
		ctx        context.Context
		addr       string
		code       string
		unanswered bool
	}{
		{"nothing accepts the connection", context.Background(), refusing, "code=Unavailable", true},
		{"nothing answers before the deadline", short(), startStubGNMI(t, silentGNMI{}), "code=DeadlineExceeded", true},
		{"the node refuses the path", context.Background(), startStubGNMI(t, r3Stub()), "code=NotFound", false},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, err := GNMIReader{}.Get(c.ctx, c.addr, stubProbe, "/system/no/such/path", getenv)
			if err == nil || !strings.HasPrefix(err.Error(), "gNMI Get /system/no/such/path at "+c.addr+": "+c.code+" ") {
				t.Fatalf("error = %v, want gnmiGet's sentence with %s", err, c.code)
			}
			if u := (*verify.Unanswered)(nil); errors.As(err, &u) != c.unanswered {
				t.Errorf("unanswered %t for %v, want %t", !c.unanswered, err, c.unanswered)
			}
		})
	}
}
