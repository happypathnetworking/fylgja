package intent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"

	"github.com/Khan/genqlient/graphql"

	"github.com/happypathnetworking/fylgja/internal/probe"
)

// The probe kind as this build reads it (016, D-064; R-06, R-07): Fylgja's own, concrete,
// branch-agnostic, beside the stage kind on the default branch. It is the second source of
// a declaration, after a --probes file, read only when a request names no file. One object
// is one probe, its two endpoints flat attributes, so a read yields the declaration's
// element by renaming alone.
const (
	// ProbeKind is the kind the reader checks for and lists.
	ProbeKind = "FylgjaProbe"
	// ProbeSchemaFile is the file that defines the kind, named by probe.kind.absent so an
	// operator knows what to load.
	ProbeSchemaFile = "schema/fylgja-probe.yaml"
)

// ProbeFields is every attribute of the kind the build reads, in the declaration's order:
// the name, the format, then endpoint a's four and endpoint b's. The kind's description is
// never read.
var ProbeFields = []string{
	"name", "format",
	"a_device", "a_interface", "a_address", "a_gateway",
	"b_device", "b_interface", "b_address", "b_gateway",
}

// ProbeKindError says the default branch's schema cannot serve a read of the kind: the
// kind is absent, or it lacks an attribute this build reads. The server files it as
// probe.kind.absent naming ProbeSchemaFile, and only when the kind's read is asked for.
type ProbeKindError struct {
	// Missing names the attributes the kind lacks, in ProbeFields' order; empty when the
	// kind itself is absent.
	Missing []string
}

// Error is the first half of probe.kind.absent's message; the finding adds what to load.
func (e *ProbeKindError) Error() string {
	switch len(e.Missing) {
	case 0:
		return "the default branch's schema has no kind " + ProbeKind
	case 1:
		return fmt.Sprintf("kind %s on the default branch lacks the attribute %s, which this build reads", ProbeKind, e.Missing[0])
	default:
		return fmt.Sprintf("kind %s on the default branch lacks the attributes %s, which this build reads",
			ProbeKind, strings.Join(e.Missing, ", "))
	}
}

// ProbeReader reads the probes declared in Infrahub from the default branch. It is
// StageReader's pattern: Infrahub's unnamed endpoints (/api/schema and /graphql), so it
// names no branch, and an installation whose default branch is not called main needs
// nothing of it; nothing is pinned, since the kind is branch-agnostic and a probe is not
// intent. It shares Client's transport, redaction and explanation of Infrahub's refusals,
// so no credential reaches an error.
type ProbeReader struct {
	address string
	token   string
	gql     graphql.Client
	http    *http.Client
}

// NewProbeReader builds a reader for one Infrahub.
func NewProbeReader(address, token string) *ProbeReader {
	s := NewStageReader(address, token)
	return &ProbeReader{address: s.address, token: s.token, gql: s.gql, http: s.http}
}

// ProbeReaderFromEnv builds a reader from the variables a read uses, and refuses alike
// when one is unset.
func ProbeReaderFromEnv() (*ProbeReader, error) {
	address, token, err := envCredentials()
	if err != nil {
		return nil, err
	}
	return NewProbeReader(address, token), nil
}

// Check reads the default branch's schema and requires the kind with every attribute in
// ProbeFields. It runs before the query: a query for a kind the schema lacks is an HTTP
// 200 whose message names nothing an operator can act on.
func (r *ProbeReader) Check(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, r.address+"/api/schema", nil)
	if err != nil {
		return err
	}
	resp, err := r.http.Do(req)
	if err != nil {
		return r.wrap(err, "reading the schema")
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return r.wrap(err, "reading the schema")
	}
	if resp.StatusCode != http.StatusOK {
		return r.wrap(errors.New(explainStatus(resp.StatusCode, body)), "reading the schema")
	}
	var doc struct {
		Nodes []struct {
			Kind       string `json:"kind"`
			Attributes []struct {
				Name string `json:"name"`
			} `json:"attributes"`
		} `json:"nodes"`
	}
	if err := json.Unmarshal(body, &doc); err != nil {
		return fmt.Errorf("reading the schema %s: %w", stagesWhere, err)
	}
	for _, n := range doc.Nodes {
		if n.Kind != ProbeKind {
			continue
		}
		have := map[string]bool{}
		for _, a := range n.Attributes {
			have[a.Name] = true
		}
		var kindErr ProbeKindError
		for _, f := range ProbeFields {
			if !have[f] {
				kindErr.Missing = append(kindErr.Missing, f)
			}
		}
		if len(kindErr.Missing) > 0 {
			return &kindErr
		}
		return nil
	}
	return &ProbeKindError{}
}

// Probes reads every object of the kind, paged as Devices is, each mapped to the
// declaration's element: name and format, then endpoint a from the a_ attributes and
// endpoint b from the b_ ones, every value verbatim. They come back sorted by name, the
// kind's order_by, whatever order the server answers in; none is an empty list, never
// nil, since a snapshot's probes is a list. Nothing here holds a probe to the
// declaration's rules: the server does, as it does a file's.
func (r *ProbeReader) Probes(ctx context.Context) ([]probe.Probe, error) {
	out := []probe.Probe{}
	for offset := 0; ; offset += pageSize {
		resp, err := Probes(ctx, r.gql, pageSize, offset)
		if err != nil {
			return nil, r.wrap(err, "reading the probes of kind "+ProbeKind)
		}
		page := resp.GetFylgjaProbe()
		for _, edge := range page.GetEdges() {
			n := edge.GetNode()
			out = append(out, probe.Probe{
				Name:   n.Name.GetValue(),
				Format: n.Format.GetValue(),
				Endpoints: [2]probe.Endpoint{
					{Device: n.A_device.GetValue(), Interface: n.A_interface.GetValue(),
						Address: n.A_address.GetValue(), Gateway: n.A_gateway.GetValue()},
					{Device: n.B_device.GetValue(), Interface: n.B_interface.GetValue(),
						Address: n.B_address.GetValue(), Gateway: n.B_gateway.GetValue()},
				},
			})
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

// wrap is StageReader.wrap: what was asked of the default branch, Infrahub's own words,
// then the credential removed.
func (r *ProbeReader) wrap(err error, what string) error {
	return fmt.Errorf("%s %s: %w", what, stagesWhere, redact(explain(err), r.token))
}
