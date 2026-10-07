package lab

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"slices"
	"strings"

	"github.com/openconfig/gnmi/proto/gnmi"
	"google.golang.org/grpc/codes"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// GNMIReader reads one path of a booted node by gNMI Get, over the readiness probe's
// transport, port, encoding and login, with the probe's dial (gnmiGet). It is the
// verify.Reader that reads a real node, for twin verify, the step's wait and the
// conformance suite's boot half alike (D-037). One call is one Get under
// ProbeAttemptDeadline; it retries nothing.
//
// Its answer is verify.Answer: every update of every notification, in the order the node
// sent them. A list requested whole may come back as one update per keyed entry, which
// is why every update is kept and not only the first, as M6 kept it.
type GNMIReader struct {
	Log *slog.Logger
}

var _ verify.Reader = GNMIReader{}

// Get reads path at addr. An error is the transport's or the node's refusal, redacted as
// the probe's are, or an answer whose value this reader cannot decode. A Get the node never
// answered, gRPC Unavailable (nothing accepted the connection) or DeadlineExceeded (nothing
// answered within ProbeAttemptDeadline), is a *verify.Unanswered, so verify.Read dials that
// node no further in the read. An update whose value cannot be decoded fails the
// whole read rather than being dropped: a partly read answer would be a claim about the
// node that this reader cannot support.
func (g GNMIReader) Get(ctx context.Context, addr string, probe wire.Probe, path string, getenv func(string) (string, bool)) (verify.Answer, error) {
	resp, err := gnmiGet(ctx, g.Log, "gnmi get", addr, probe, path, getenv)
	if err != nil {
		if re := (*rpcError)(nil); errors.As(err, &re) && (re.code == codes.Unavailable || re.code == codes.DeadlineExceeded) {
			return verify.Answer{}, &verify.Unanswered{Err: err}
		}
		return verify.Answer{}, err
	}
	var answer verify.Answer
	for _, n := range resp.GetNotification() {
		for _, u := range n.GetUpdate() {
			value, err := decodeTypedValue(u.GetVal())
			if err != nil {
				return verify.Answer{}, fmt.Errorf("gNMI Get %s at %s: %w", path, addr, err)
			}
			answer.Updates = append(answer.Updates, verify.Update{Path: pathText(n.GetPrefix(), u.GetPath()), Value: value})
		}
	}
	return answer, nil
}

// pathText writes a notification's prefix and an update's path as one path, the way
// gnmic prints it: elements joined by `/`, no leading `/`, each element's keys in
// brackets in key order, names verbatim with their module prefixes.
func pathText(prefix, path *gnmi.Path) string {
	var parts []string
	for _, e := range append(slices.Clone(prefix.GetElem()), path.GetElem()...) {
		var b strings.Builder
		b.WriteString(e.GetName())
		keys := e.GetKey()
		for _, k := range slices.Sorted(maps.Keys(keys)) {
			fmt.Fprintf(&b, "[%s=%s]", k, keys[k])
		}
		parts = append(parts, b.String())
	}
	return strings.Join(parts, "/")
}

// decodeTypedValue gives an update's value as JSON decodes it: a JSON or JSON-IETF value
// decoded to any, a scalar as its Go value. A kind this reader has no use for is an
// error rather than a guess.
func decodeTypedValue(v *gnmi.TypedValue) (any, error) {
	switch x := v.GetValue().(type) {
	case *gnmi.TypedValue_JsonIetfVal:
		return decodeJSON(x.JsonIetfVal)
	case *gnmi.TypedValue_JsonVal:
		return decodeJSON(x.JsonVal)
	case *gnmi.TypedValue_StringVal:
		return x.StringVal, nil
	case *gnmi.TypedValue_AsciiVal:
		return x.AsciiVal, nil
	case *gnmi.TypedValue_BoolVal:
		return x.BoolVal, nil
	case *gnmi.TypedValue_IntVal:
		return x.IntVal, nil
	case *gnmi.TypedValue_UintVal:
		return x.UintVal, nil
	case *gnmi.TypedValue_DoubleVal:
		return x.DoubleVal, nil
	case nil:
		return nil, fmt.Errorf("an update carried no value")
	}
	return nil, fmt.Errorf("an update's value is of kind %T, which the reader does not decode", v.GetValue())
}

func decodeJSON(b []byte) (any, error) {
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, fmt.Errorf("an update's JSON value does not decode: %w", err)
	}
	return out, nil
}
