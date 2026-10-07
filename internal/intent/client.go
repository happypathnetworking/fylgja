// Package intent reads intent from Infrahub and projects it into the CTM.
//
// Every query names a Fylgja generic, never a concrete kind (Constitution III), and
// every request is a read: Fylgja never writes to Infrahub. Queries are typed
// and generated from Infrahub's own SDL, so a schema change that breaks a query fails
// the build rather than the twin.
package intent

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/Khan/genqlient/graphql"
)

// Environment variables Fylgja reads. The credential is supplied through the process
// environment, never a file, never a flag; it is never persisted and never echoed.
const (
	EnvAddress = "INFRAHUB_ADDRESS"
	EnvToken   = "INFRAHUB_API_TOKEN"
)

// Config addresses one branch, optionally at one instant.
type Config struct {
	Address string
	Token   string
	Branch  string
	// At is the instant the operator supplied, passed verbatim on every query of the
	// read and recorded verbatim in the envelope. Empty means no `at` parameter is
	// sent at all: Fylgja never invents one (D-012). A local "now" is what `observed_at`
	// records, and it is deliberately not sent to Infrahub (D-023).
	At string
}

// FromEnv reads the address and credential from the process environment.
func FromEnv(branch, at string) (Config, error) {
	address, token, err := envCredentials()
	c := Config{Address: address, Token: token, Branch: branch, At: at}
	if err != nil {
		return c, err
	}
	if c.Branch == "" {
		return c, fmt.Errorf("no branch given")
	}
	return c, nil
}

// envCredentials reads the address and the credential, refusing when either is unset.
func envCredentials() (address, token string, err error) {
	address = strings.TrimRight(os.Getenv(EnvAddress), "/")
	token = os.Getenv(EnvToken)
	if address == "" {
		return address, token, fmt.Errorf("%s is not set", EnvAddress)
	}
	if token == "" {
		return address, token, fmt.Errorf("%s is not set", EnvToken)
	}
	return address, token, nil
}

// endpoint builds the GraphQL URL for a branch and instant. The `at` parameter is URL
// encoded: an unencoded "+" in a timezone offset is read as a space and rejected.
//
// When the operator did not ask for an instant, none is sent: the branch's current
// state is read. Pinning `at` to the local clock looked tidier and was wrong — Infrahub
// filters on created_at <= at, and a second-granularity "now" silently hides every
// object written during that same second. The contract test caught it as a fixture
// that had lost two of its three devices.
func (c Config) endpoint() string {
	u := c.Address + "/graphql/" + url.PathEscape(c.Branch)
	if c.At != "" {
		u += "?at=" + url.QueryEscape(c.At)
	}
	return u
}

// authTransport adds the credential to every request and keeps it out of every error.
type authTransport struct {
	token string
	base  http.RoundTripper
}

func (t *authTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	clone := r.Clone(r.Context())
	clone.Header.Set("X-INFRAHUB-KEY", t.token)
	resp, err := t.base.RoundTrip(clone)
	if err != nil {
		return nil, redact(err, t.token)
	}
	// Recognise a credential rejection here rather than letting it surface as a
	// GraphQL parse failure three layers up: naming INFRAHUB_API_TOKEN tells an
	// operator what to do, and a decoding error does not.
	if authErr := authFailure(resp.StatusCode); authErr != nil {
		_ = resp.Body.Close()
		return nil, authErr
	}
	return resp, nil
}

// Client reads intent from one branch.
type Client struct {
	cfg     Config
	gql     graphql.Client
	http    *http.Client
	timeout time.Duration
}

// New builds a client for a branch.
func New(cfg Config) *Client {
	hc := &http.Client{
		Timeout:   60 * time.Second,
		Transport: &authTransport{token: cfg.Token, base: http.DefaultTransport},
	}
	return &Client{
		cfg:     cfg,
		gql:     graphql.NewClient(cfg.endpoint(), hc),
		http:    hc,
		timeout: 60 * time.Second,
	}
}

// Branch reports which branch this client reads.
func (c *Client) Branch() string { return c.cfg.Branch }

// At reports the instant this client reads at, empty when the operator supplied none.
func (c *Client) At() string { return c.cfg.At }

// wrap makes a transport or GraphQL failure safe to print and says which (branch, at)
// it was about, so an operator reading exit 2 knows what Fylgja asked for.
func (c *Client) wrap(err error, what string) error {
	if err == nil {
		return nil
	}
	wrapped := fmt.Errorf("%s %s: %w", what, c.cfg.describe(), redact(explain(err), c.cfg.Token))
	if c.branchNotFound(err) {
		return branchMissing{wrapped}
	}
	return wrapped
}

// branchNotFound reports a failure that says this client's branch does not exist: already
// marked by the schema endpoint, or GraphQL's 404 in Infrahub's words. explain and redact
// rebuild the error, so wrap marks it again after them.
func (c *Client) branchNotFound(err error) bool {
	if errors.Is(err, ErrBranchNotFound) {
		return true
	}
	var httpErr *graphql.HTTPError
	return errors.As(err, &httpErr) && httpErr.StatusCode == http.StatusNotFound &&
		namesBranch(infrahubMessages(httpErr), c.cfg.Branch)
}

// getAt performs a plain REST read that carries the operator's `at`, for the endpoints
// that are not GraphQL and do have a time axis — the object store, which serves an
// artifact's content.
//
// Every request of a pinned read is made at the same instant (Constitution VI), so the
// parameter is appended here rather than left to each caller, verbatim and URL encoded
// as the GraphQL endpoint encodes it: an unencoded "+" in a timezone offset is read as
// a space and rejected. When the operator pinned nothing, nothing is appended and the
// request is byte for byte the one `get` would have made.
//
// It is separate from `get` rather than a parameter of it, because the schema endpoint
// must keep sending no `at` at all: it has no time axis and ignores one, and a shared
// parameter is an invitation to pass it there by mistake.
func (c *Client) getAt(ctx context.Context, path string) ([]byte, int, error) {
	if c.cfg.At != "" {
		sep := "?"
		if strings.Contains(path, "?") {
			sep = "&"
		}
		path += sep + "at=" + url.QueryEscape(c.cfg.At)
	}
	return c.get(ctx, path)
}

// get performs a plain REST read against Infrahub, for the endpoints that are not
// GraphQL — the schema endpoint, which reports which concrete kinds implement each
// generic.
func (c *Client) get(ctx context.Context, path string) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.cfg.Address+path, nil)
	if err != nil {
		return nil, 0, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, 0, redact(err, c.cfg.Token)
	}
	defer func() { _ = resp.Body.Close() }()
	if authErr := authFailure(resp.StatusCode); authErr != nil {
		return nil, resp.StatusCode, authErr
	}
	body := make([]byte, 0, 64*1024)
	buf := make([]byte, 32*1024)
	for {
		n, err := resp.Body.Read(buf)
		body = append(body, buf[:n]...)
		if err != nil {
			break
		}
	}
	return body, resp.StatusCode, nil
}
