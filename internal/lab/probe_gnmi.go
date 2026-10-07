package lab

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/openconfig/gnmi/proto/gnmi"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// ProbeAttemptDeadline bounds one probe attempt, dial and RPC together. A mechanism
// constant, not a platform budget.
const ProbeAttemptDeadline = 5 * time.Second

// GNMIProber runs a gNMI Get readiness probe in process, as gnmic sends one:
// TLS without certificate verification (a node's certificate is generated at boot), the
// login as gRPC metadata, the path and encoding from the package. Pure Go, so a lab host
// needs no gnmic (Constitution I).
type GNMIProber struct {
	Log *slog.Logger
}

var _ Prober = GNMIProber{}

// Probe implements Prober. Success is a Get answered with at least one notification. An
// error names the gRPC code and message, and never the password.
func (g GNMIProber) Probe(ctx context.Context, addr string, p wire.Probe, getenv func(string) (string, bool)) error {
	resp, err := gnmiGet(ctx, g.Log, "gnmi probe", addr, p, p.Path, getenv)
	if err != nil {
		return err
	}
	if len(resp.GetNotification()) == 0 {
		return fmt.Errorf("gNMI Get %s at %s: answered with no notification", p.Path, addr)
	}
	return nil
}

// gnmiGet sends one gNMI Get of one path, as the readiness probe and the conformance
// reader both send it: the transport the probe's TLS says (TLS without certificate
// verification, or plaintext), the login read by the probe's variable names and sent as
// metadata, the probe's encoding, the whole call under ProbeAttemptDeadline. what names
// the call in the debug line. An error names the gRPC code and message, and never the
// password.
func gnmiGet(ctx context.Context, log *slog.Logger, what, addr string, p wire.Probe, pathText string, getenv func(string) (string, bool)) (*gnmi.GetResponse, error) {
	path, err := gnmiPath(pathText)
	if err != nil {
		return nil, err
	}
	enc, err := gnmiEncoding(p.Encoding)
	if err != nil {
		return nil, err
	}
	username, ok := getenv(p.UsernameEnv)
	if !ok {
		return nil, fmt.Errorf("probe login variable %s is unset", p.UsernameEnv)
	}
	password, ok := getenv(p.PasswordEnv)
	if !ok {
		return nil, fmt.Errorf("probe login variable %s is unset", p.PasswordEnv)
	}

	if log == nil {
		log = slog.Default()
	}
	// The login is named by its variables, so the attempt can be repeated with gnmic.
	log.Debug(what, "addr", addr, "path", pathText, "encoding", p.Encoding,
		"username_env", p.UsernameEnv, "password_env", p.PasswordEnv)

	ctx, cancel := context.WithTimeout(ctx, ProbeAttemptDeadline)
	defer cancel()

	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(gnmiCredentials(p)))
	if err != nil {
		return nil, redact(fmt.Errorf("gNMI client for %s: %w", addr, err), password)
	}
	defer func() { _ = conn.Close() }()

	ctx = metadata.AppendToOutgoingContext(ctx, "username", username, "password", password)
	resp, err := gnmi.NewGNMIClient(conn).Get(ctx, &gnmi.GetRequest{
		Path:     []*gnmi.Path{path},
		Type:     gnmi.GetRequest_ALL,
		Encoding: enc,
	})
	if err != nil {
		st, _ := status.FromError(err)
		return nil, &rpcError{code: st.Code(),
			err: redact(fmt.Errorf("gNMI Get %s at %s: code=%s msg=%q", pathText, addr, st.Code(), st.Message()), password)}
	}
	return resp, nil
}

// rpcError is a Get the node's gRPC transport failed or the node refused, its text the
// redacted sentence and its status code kept beside it, so a reader can tell a node that
// never answered from one that refused a path without parsing the text.
type rpcError struct {
	code codes.Code
	err  error
}

func (e *rpcError) Error() string { return e.err.Error() }

func (e *rpcError) Unwrap() error { return e.err }

// gnmiCredentials are the transport credentials the probe's TLS asks for. A package that
// omits readiness.tls means TLS, which is what every package and
// every recorded plan written before the field meant; false is plaintext gRPC, which is
// what a node's default gRPC transport serves when no SSL profile is attached to it.
//
// Skipping verification under TLS is deliberate: the node's certificate is self-signed
// at boot, and the probe asks only whether the management plane answers.
func gnmiCredentials(p wire.Probe) credentials.TransportCredentials {
	if !wire.ProbeTLS(p) {
		return insecure.NewCredentials()
	}
	return credentials.NewTLS(&tls.Config{InsecureSkipVerify: true}) //nolint:gosec // a twin node's boot-time certificate
}

// gnmicTLSFlag is the gnmic flag for the probe's transport, so the by_hand line an
// operator repeats dials the way the probe dialled.
func gnmicTLSFlag(p wire.Probe) string {
	if !wire.ProbeTLS(p) {
		return "--insecure"
	}
	return "--skip-verify"
}

// redact removes a secret from an error's text. The probe never writes the password into
// an error itself; this is the second lock, for a transport or server that echoes
// request metadata back.
func redact(err error, secret string) error {
	if secret == "" || !strings.Contains(err.Error(), secret) {
		return err
	}
	return errors.New(strings.ReplaceAll(err.Error(), secret, "[redacted]"))
}

// gnmiEncoding maps a package's encoding name (psp.schema.json's enum) to the wire value.
func gnmiEncoding(name string) (gnmi.Encoding, error) {
	switch name {
	case "json":
		return gnmi.Encoding_JSON, nil
	case "json_ietf":
		return gnmi.Encoding_JSON_IETF, nil
	case "proto":
		return gnmi.Encoding_PROTO, nil
	case "ascii":
		return gnmi.Encoding_ASCII, nil
	case "bytes":
		return gnmi.Encoding_BYTES, nil
	}
	return 0, fmt.Errorf("unknown gNMI encoding %q", name)
}

// gnmiPath parses a package's probe path, `/elem/elem[key=value]/elem`, into path
// elements. A key's value may contain `/` (`interface[name=ethernet-1/1]`) but not `]`.
func gnmiPath(s string) (*gnmi.Path, error) {
	if !strings.HasPrefix(s, "/") {
		return nil, fmt.Errorf("probe path %q is not absolute", s)
	}
	var elems []*gnmi.PathElem
	rest := s[1:]
	for rest != "" {
		end := strings.IndexAny(rest, "/[")
		if end < 0 {
			end = len(rest)
		}
		elem := &gnmi.PathElem{Name: rest[:end]}
		if elem.Name == "" {
			return nil, fmt.Errorf("probe path %q has an empty element", s)
		}
		if strings.ContainsAny(elem.Name, "]=") {
			return nil, fmt.Errorf("probe path %q has a key outside brackets in %q", s, elem.Name)
		}
		rest = rest[end:]
		for strings.HasPrefix(rest, "[") {
			closing := strings.IndexByte(rest, ']')
			if closing < 0 {
				return nil, fmt.Errorf("probe path %q has an unclosed key", s)
			}
			k, v, ok := strings.Cut(rest[1:closing], "=")
			if !ok || k == "" {
				return nil, fmt.Errorf("probe path %q has a key that is not name=value", s)
			}
			if elem.Key == nil {
				elem.Key = map[string]string{}
			}
			elem.Key[k] = v
			rest = rest[closing+1:]
		}
		elems = append(elems, elem)
		switch {
		case rest == "":
		case strings.HasPrefix(rest, "/") && len(rest) > 1:
			rest = rest[1:]
		default:
			return nil, fmt.Errorf("probe path %q is malformed at %q", s, rest)
		}
	}
	return &gnmi.Path{Elem: elems}, nil
}
