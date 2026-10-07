package intent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"sort"
)

// SchemaInfo is what Infrahub's schema endpoint says about a branch: the schema's own
// hash, and which concrete kinds implement each generic.
//
// Conformance is read from here rather than inferred from a failed query. A failed
// query yields a transport error; the contract requires naming the generic that has no
// implementation, and only the schema endpoint knows that.
type SchemaInfo struct {
	// Hash identifies the schema state; recorded as the envelope's schema_hash.
	Hash string
	// UsedBy maps a generic's kind name to the concrete kinds implementing it.
	UsedBy map[string][]string
	// Kinds is every node kind defined on the branch.
	Kinds map[string]bool
}

// Implementers returns the concrete kinds implementing a generic, sorted.
func (s *SchemaInfo) Implementers(generic string) []string {
	out := append([]string(nil), s.UsedBy[generic]...)
	sort.Strings(out)
	return out
}

// SchemaInfo reads the branch's schema metadata.
//
// No `at` is sent: the schema endpoint has no time axis — it accepts only `branch`
// and `namespaces`, and an `at` is ignored (verified). The hash recorded
// in the envelope is therefore the branch's schema hash at the time of the read, even
// for a pinned read; that is deliberate, and is recorded here so nobody
// later reads it as "the schema as of `at`".
//
// A failure here fails the read: the envelope's schema_hash is required, so a CTM that
// cannot say
// which schema it was read against is not written at all.
func (c *Client) SchemaInfo(ctx context.Context) (*SchemaInfo, error) {
	body, status, err := c.get(ctx, "/api/schema?branch="+url.QueryEscape(c.cfg.Branch))
	if err != nil {
		return nil, c.wrap(err, "reading the schema")
	}
	if status != 200 {
		// Infrahub's own words, not just the status: this endpoint is what answers for
		// a branch that does not exist, and it says so in the body.
		//
		// Through wrap, so the body takes the same route to the operator as a GraphQL
		// failure does — named reference, then redaction. Surfacing a response body
		// without redacting it is how a credential reaches a log: a debug-mode server
		// or a proxy in front of Infrahub can quote the request's own header back
		// (cmd/fylgja's echoingServer asserts exactly this).
		refused := errors.New(explainStatus(status, body))
		if status == http.StatusBadRequest && namesBranch(unwrapErrorBody(string(body)), c.cfg.Branch) {
			refused = branchMissing{refused}
		}
		return nil, c.wrap(refused, "reading the schema")
	}
	var doc struct {
		Main     string `json:"main"`
		Generics []struct {
			Kind   string   `json:"kind"`
			UsedBy []string `json:"used_by"`
		} `json:"generics"`
		Nodes []struct {
			Kind string `json:"kind"`
		} `json:"nodes"`
	}
	if err := json.Unmarshal(body, &doc); err != nil {
		return nil, fmt.Errorf("reading the schema %s: %w", c.cfg.describe(), err)
	}
	if doc.Main == "" {
		return nil, fmt.Errorf("reading the schema %s: no schema hash reported", c.cfg.describe())
	}
	info := &SchemaInfo{Hash: doc.Main, UsedBy: map[string][]string{}, Kinds: map[string]bool{}}
	for _, g := range doc.Generics {
		info.UsedBy[g.Kind] = g.UsedBy
	}
	for _, n := range doc.Nodes {
		info.Kinds[n.Kind] = true
	}
	return info, nil
}
