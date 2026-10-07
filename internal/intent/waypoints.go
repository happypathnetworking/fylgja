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
	"time"

	"github.com/Khan/genqlient/graphql"
)

// The waypoint kind as this build reads it (M10). A Fylgja-owned concrete kind beside
// the contract, as FylgjaContract is:
// nobody implements it, and only --waypoint, waypoint list and waypoint plan read it.
const (
	// WaypointKind is the kind the reader checks for and lists.
	WaypointKind = "FylgjaWaypoint"
	// WaypointSchemaFile is the file that defines it, named by waypoint.kind.absent and
	// by schema check so an operator knows what to load.
	WaypointSchemaFile = "schema/fylgja-waypoint.yaml"
)

// WaypointFields is the shape the build reads: every attribute the Waypoints query
// selects. The attribute that carries the reference's `at` is as_of, because Infrahub
// 1.11.2 refuses a two-character attribute name.
var WaypointFields = []string{"series", "sequence", "branch", "as_of", "description"}

// Waypoint is one waypoint as Infrahub holds it. Nothing here is resolved: At is the
// written as_of or nil, and BranchWrittenAt is branch.updated_at verbatim.
type Waypoint struct {
	ID, Series      string
	Sequence        int
	Branch          string
	BranchWrittenAt string  // branch.updated_at, as returned: 2026-09-28T16:04:52.482130+00:00
	At              *string // as_of.value verbatim, nil when unwritten
	Description     string
}

// WaypointKindError says the default branch's schema cannot serve the waypoint commands:
// the kind is absent, or it lacks an attribute this build reads. Every caller files it as
// waypoint.kind.absent naming WaypointSchemaFile, and schema check
// reports it as information.
type WaypointKindError struct {
	// Missing names the attributes the kind lacks, in WaypointFields' order; empty when
	// the kind itself is absent. A list, because schema check's verified.waypoints.missing
	// is one.
	Missing []string
}

// Error is the first half of contracts/cli.md's waypoint.kind.absent message; the
// finding adds what to load.
func (e *WaypointKindError) Error() string {
	switch len(e.Missing) {
	case 0:
		return "the default branch's schema has no kind " + WaypointKind
	case 1:
		return fmt.Sprintf("kind %s on the default branch lacks the attribute %s, which this build reads", WaypointKind, e.Missing[0])
	default:
		return fmt.Sprintf("kind %s on the default branch lacks the attributes %s, which this build reads", WaypointKind, strings.Join(e.Missing, ", "))
	}
}

// WaypointReader reads waypoints from the default branch. It is a second client beside
// Client, for objects that live on no branch of the operator's: it names no branch at
// all, using Infrahub's unnamed endpoints (/api/schema and /graphql), so an installation
// whose default branch is not called main needs nothing of it. Client's
// Config.Branch stays required; a waypoint read never has one.
//
// It shares Client's transport, redaction and explanation of Infrahub's refusals, so an
// unreachable Infrahub, a refused credential or a non-200 read the same as a branch
// read's, and no credential reaches an error.
type WaypointReader struct {
	address string
	token   string
	gql     graphql.Client
	http    *http.Client
}

// NewWaypointReader builds a reader for one Infrahub.
func NewWaypointReader(address, token string) *WaypointReader {
	address = strings.TrimRight(address, "/")
	hc := &http.Client{
		Timeout:   60 * time.Second,
		Transport: &authTransport{token: token, base: http.DefaultTransport},
	}
	return &WaypointReader{
		address: address,
		token:   token,
		gql:     graphql.NewClient(address+"/graphql", hc),
		http:    hc,
	}
}

// WaypointReaderFromEnv builds a reader from the variables a read uses, and refuses
// alike when one is unset.
func WaypointReaderFromEnv() (*WaypointReader, error) {
	address, token, err := envCredentials()
	if err != nil {
		return nil, err
	}
	return NewWaypointReader(address, token), nil
}

// waypointsWhere names what the reader asked, for its errors, as describe names a
// branch read's reference.
const waypointsWhere = "(the default branch)"

// Check reads the default branch's schema and requires the kind with every attribute in
// WaypointFields. It runs before any query: a query for a kind the schema lacks is an
// HTTP 200 whose message names nothing an operator can act on.
func (r *WaypointReader) Check(ctx context.Context) error {
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
		return fmt.Errorf("reading the schema %s: %w", waypointsWhere, err)
	}
	for _, n := range doc.Nodes {
		if n.Kind != WaypointKind {
			continue
		}
		have := map[string]bool{}
		for _, a := range n.Attributes {
			have[a.Name] = true
		}
		var missing []string
		for _, f := range WaypointFields {
			if !have[f] {
				missing = append(missing, f)
			}
		}
		if len(missing) > 0 {
			return &WaypointKindError{Missing: missing}
		}
		return nil
	}
	return &WaypointKindError{}
}

// List reads every waypoint, paged as Devices is, and returns them sorted by series then
// sequence. Infrahub orders them so already (the kind's order_by); the sort is repeated
// here so the output is stable whatever the server does. No filter is sent: a series is
// chosen in memory, and one page holds any series an operator writes by hand.
func (r *WaypointReader) List(ctx context.Context) ([]Waypoint, error) {
	var out []Waypoint
	for offset := 0; ; offset += pageSize {
		resp, err := Waypoints(ctx, r.gql, pageSize, offset)
		if err != nil {
			return nil, r.wrap(err, "reading waypoints")
		}
		page := resp.GetFylgjaWaypoint()
		for _, edge := range page.GetEdges() {
			n := edge.GetNode()
			w := Waypoint{
				ID:              n.GetId(),
				Series:          n.Series.GetValue(),
				Sequence:        n.Sequence.GetValue(),
				Branch:          n.Branch.GetValue(),
				BranchWrittenAt: n.Branch.GetUpdated_at(),
				Description:     n.Description.GetValue(),
			}
			// GraphQL types the DateTime attribute's value as a String, which decodes a
			// null to "". An operator cannot write "" (the kind refuses what is not a
			// time), so "" is unwritten.
			if at := n.As_of.GetValue(); at != "" {
				w.At = &at
			}
			out = append(out, w)
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Series != out[j].Series {
			return out[i].Series < out[j].Series
		}
		if out[i].Sequence != out[j].Sequence {
			return out[i].Sequence < out[j].Sequence
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}

// wrap is Client.wrap for a read that names no branch: Infrahub's own words, then the
// credential removed.
func (r *WaypointReader) wrap(err error, what string) error {
	return fmt.Errorf("%s %s: %w", what, waypointsWhere, redact(explain(err), r.token))
}
