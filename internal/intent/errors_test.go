package intent

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/psp"
)

// testRegistry is the shipped platform support, which the read needs only to know which
// artifact is a platform's configuration. Every test here fails before any artifact is
// selected, so the registry's content does not matter — that it is the real one does.
func testRegistry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

// A rejected credential must be reported as a credential problem, naming the variable
// to fix. Before this was wired, a 401 surfaced as a GraphQL decoding failure — true,
// but useless to the operator holding the wrong token.
func TestRejectedCredentialIsNamed(t *testing.T) {
	for _, tc := range []struct {
		status int
		want   string
	}{
		{http.StatusUnauthorized, "was rejected by Infrahub"},
		{http.StatusForbidden, "not permitted"},
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(tc.status)
			_, _ = w.Write([]byte(`{"errors":[{"message":"Authentication is required"}]}`))
		}))
		t.Cleanup(srv.Close)

		cfg := Config{Address: srv.URL, Token: "sentinel-token", Branch: "main"}
		ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
		_, _, err := New(cfg).Fetch(ctx, nil, "2026-09-14T00:00:00.000000Z", testRegistry(t))
		cancel()

		if err == nil {
			t.Fatalf("status %d: expected an error", tc.status)
		}
		if !strings.Contains(err.Error(), tc.want) {
			t.Errorf("status %d: message %q does not mention %q", tc.status, err, tc.want)
		}
		if !strings.Contains(err.Error(), EnvToken) {
			t.Errorf("status %d: message does not name %s: %v", tc.status, EnvToken, err)
		}
		if strings.Contains(err.Error(), "sentinel-token") {
			t.Errorf("status %d: the credential leaked into the error: %v", tc.status, err)
		}
	}
}

// The REST path (the schema endpoint) must recognise it too, not just GraphQL.
func TestSchemaEndpointReportsRejectedCredential(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	_, err := New(Config{Address: srv.URL, Token: "t", Branch: "main"}).SchemaInfo(ctx)
	if err == nil || !strings.Contains(err.Error(), EnvToken) {
		t.Errorf("expected a credential error naming %s, got %v", EnvToken, err)
	}
}

// Infrahub's three refusals about the intent reference — an unknown branch, an `at`
// before the default branch, an `at` it cannot parse — are surfaced in Infrahub's own
// words, with the branch and `at` Fylgja sent named alongside. The
// bodies here are the ones the live instance returned on 2026-09-14.
func TestInfrahubRefusalsAreSurfacedWithTheReference(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		body   string
		at     string
		want   string
	}{
		{
			name:   "unknown branch",
			status: http.StatusNotFound,
			body:   `{"errors":["Branch: does-not-exist not found."]}`,
			want:   "Branch: does-not-exist not found.",
		},
		{
			name:   "at before the default branch",
			status: http.StatusUnprocessableEntity,
			body:   `{"data":null,"errors":[{"message":"Requested time '2020-01-01T00:00:00.000000Z' is before branch 'main' was created at '2026-09-08T18:05:22.715400Z'.","extensions":{"code":"UNDEFINED_ERROR","http_status":422}}]}`,
			at:     "2020-01-01T00:00:00Z",
			want:   "is before branch 'main' was created at",
		},
		{
			name:   "unparseable at",
			status: http.StatusBadRequest,
			body:   `{"data":null,"errors":[{"message":"Invalid time format for yesterday","extensions":{"code":"UNDEFINED_ERROR","http_status":400}}]}`,
			at:     "yesterday",
			want:   "Invalid time format for yesterday",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()

			cfg := Config{Address: srv.URL, Token: "sentinel-token", Branch: "does-not-exist", At: tc.at}
			ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
			defer cancel()
			_, _, err := New(cfg).Fetch(ctx, nil, "2026-09-14T00:00:00.000000Z", testRegistry(t))

			if err == nil {
				t.Fatal("expected a refusal to be reported")
			}
			msg := err.Error()
			// Infrahub's own sentence, not a JSON dump of the response.
			if !strings.Contains(msg, tc.want) {
				t.Errorf("message does not carry Infrahub's words %q: %s", tc.want, msg)
			}
			if strings.Contains(msg, `{"data"`) || strings.Contains(msg, `"extensions"`) {
				t.Errorf("message is a JSON dump rather than a sentence: %s", msg)
			}
			// The reference Fylgja actually sent, so an operator who ran several
			// reads knows which one this was about.
			if !strings.Contains(msg, "branch does-not-exist") {
				t.Errorf("message does not name the branch: %s", msg)
			}
			if tc.at != "" && !strings.Contains(msg, "at "+tc.at) {
				t.Errorf("message does not name the at: %s", msg)
			}
			if strings.Contains(msg, "sentinel-token") {
				t.Errorf("the credential leaked into the error: %s", msg)
			}
		})
	}
}

// Redaction is the last line of defence: an error is printed, logged, and pasted into
// issues.
func TestRedactRemovesToken(t *testing.T) {
	err := redact(errTest("dial failed with key sekrit-token"), "sekrit-token")
	if strings.Contains(err.Error(), "sekrit-token") {
		t.Errorf("token survived redaction: %s", err)
	}
	if !strings.Contains(err.Error(), "<redacted>") {
		t.Errorf("redaction left no marker: %s", err)
	}
}

// An unreachable address is an operational failure that still names the reference and
// still carries no credential.
func TestUnreachableAddressIsReportedWithoutTheCredential(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	addr := srv.URL
	srv.Close() // nothing is listening now

	cfg := Config{Address: addr, Token: "sentinel-token", Branch: "fylgja-fixture"}
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	_, err := New(cfg).SchemaInfo(ctx)
	if err == nil {
		t.Fatal("expected an unreachable address to be reported")
	}
	if strings.Contains(err.Error(), "sentinel-token") {
		t.Errorf("the credential leaked into the error: %v", err)
	}
	if !strings.Contains(err.Error(), "branch fylgja-fixture") {
		t.Errorf("message does not name the branch: %v", err)
	}
}

// The schema endpoint refuses in REST, not GraphQL, and it is what answers for a
// branch that does not exist. Its body carries Infrahub's sentence; a bare status code
// would leave an operator with a typo'd branch name holding "HTTP 400".
//
// Tier 1: the shapes are fixed by Infrahub's API, so they are asserted here rather than
// only against a live instance.
func TestExplainStatusSurfacesInfrahubsWords(t *testing.T) {
	for _, tc := range []struct {
		name, body, want string
		status           int
	}{
		{
			name:   "unknown branch",
			status: 400,
			body:   `{"data":null,"errors":[{"message":"Branch: nope not found.","extensions":{"code":400}}]}`,
			want:   "HTTP 400: Branch: nope not found.",
		},
		{
			name:   "bare string errors",
			status: 400,
			body:   `{"errors":["Branch: nope not found."]}`,
			want:   "HTTP 400: Branch: nope not found.",
		},
		{
			name:   "several messages",
			status: 422,
			body:   `{"errors":[{"message":"first"},{"message":"second"}]}`,
			want:   "HTTP 422: first; second",
		},
		{
			// A proxy in front of Infrahub, or Infrahub itself failing before it can
			// answer in JSON. The status alone beats a page of markup.
			name:   "not an error document",
			status: 502,
			body:   "<html><body>Bad Gateway</body></html>",
			want:   "HTTP 502",
		},
		{
			name:   "empty body",
			status: 500,
			body:   "",
			want:   "HTTP 500",
		},
		{
			name:   "error document with no messages",
			status: 400,
			body:   `{"errors":[]}`,
			want:   "HTTP 400",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := explainStatus(tc.status, []byte(tc.body)); got != tc.want {
				t.Errorf("explainStatus = %q, want %q", got, tc.want)
			}
		})
	}
}

// The whole point of reading the body is that the operator learns the branch does not
// exist rather than that a request failed.
//
// The server also quotes the credential back, the way a debug-mode server or a proxy
// would. Surfacing a response body is precisely how a token reaches a log, so the two
// assertions belong in one test: the body must reach the operator and the credential
// must not.
func TestUnknownBranchSaysSoAndNamesTheBranch(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"data":null,"errors":[{"message":"Branch: nope not found.",` +
			`"detail":"key ` + r.Header.Get("X-INFRAHUB-KEY") + `"},` +
			`{"message":"rejected key ` + r.Header.Get("X-INFRAHUB-KEY") + `"}]}`))
	}))
	defer srv.Close()

	cfg := Config{Address: srv.URL, Token: "sentinel-token", Branch: "nope"}
	_, err := New(cfg).SchemaInfo(t.Context())
	if err == nil {
		t.Fatal("expected an unknown branch to be reported")
	}
	for _, want := range []string{"branch nope", "not found"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("message lacks %q: %v", want, err)
		}
	}
	if strings.Contains(err.Error(), "sentinel-token") {
		t.Errorf("the credential leaked into the error: %v", err)
	}
	if !errors.Is(err, ErrBranchNotFound) {
		t.Errorf("an unknown branch is not marked ErrBranchNotFound: %v", err)
	}
}

// A following check rejects a branch that does not exist and retries later when Infrahub
// could not answer, so the mark must be on the one and not the other. Infrahub 1.11.2
// answers a deleted branch as one never created: 400 from the
// schema endpoint, 404 from GraphQL, both "Branch: <b> not found.".
func TestOnlyAMissingBranchIsMarkedNotFound(t *testing.T) {
	serve := func(status int, body string) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(body))
		}))
	}
	cases := []struct {
		name    string
		status  int
		body    string
		graphql bool
		want    bool
	}{
		{"schema endpoint, deleted branch", http.StatusBadRequest,
			`{"data":null,"errors":[{"message":"Branch: gone not found.","extensions":{"code":400}}]}`, false, true},
		{"graphql, deleted branch", http.StatusNotFound, `{"errors":["Branch: gone not found."]}`, true, true},
		{"schema endpoint, another branch named", http.StatusBadRequest,
			`{"errors":[{"message":"Branch: other not found."}]}`, false, false},
		{"schema endpoint, another refusal", http.StatusBadRequest, `{"errors":[{"message":"bad request"}]}`, false, false},
		{"schema endpoint, server error", http.StatusInternalServerError, `<html>oops</html>`, false, false},
		{"graphql, 422", http.StatusUnprocessableEntity, `{"errors":[{"message":"Branch: gone not found."}]}`, true, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := serve(tc.status, tc.body)
			defer srv.Close()
			c := New(Config{Address: srv.URL, Token: "t", Branch: "gone"})
			var err error
			if tc.graphql {
				_, _, err = c.ContractVersion(t.Context())
			} else {
				_, err = c.SchemaInfo(t.Context())
			}
			if err == nil {
				t.Fatal("expected a failure")
			}
			if got := errors.Is(err, ErrBranchNotFound); got != tc.want {
				t.Errorf("errors.Is(ErrBranchNotFound) = %v, want %v: %v", got, tc.want, err)
			}
		})
	}

	// Unreachable: nothing listens.
	srv := serve(http.StatusOK, "")
	addr := srv.URL
	srv.Close()
	_, err := New(Config{Address: addr, Token: "t", Branch: "gone"}).SchemaInfo(t.Context())
	if err == nil || errors.Is(err, ErrBranchNotFound) {
		t.Errorf("an unreachable Infrahub is marked not found, or did not fail: %v", err)
	}
}

type errTest string

func (e errTest) Error() string { return string(e) }
