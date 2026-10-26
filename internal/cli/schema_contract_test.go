//go:build contract

package cli

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// Contract tests run against a real Infrahub, never a fake (D-017):
//
//	set -a; . local/.env; set +a; go test -tags contract ./cmd/fylgja
//
// Both branches this file reads — fylgja-fixture and main — are only ever read, so a
// failing test here cannot damage either.

// live skips unless an Infrahub is configured, and returns its address.
func live(t *testing.T) string {
	t.Helper()
	addr := os.Getenv("INFRAHUB_ADDRESS")
	if addr == "" || os.Getenv("INFRAHUB_API_TOKEN") == "" {
		t.Skip("contract tests need INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN")
	}
	return strings.TrimRight(addr, "/")
}

// recorder proxies every request the command makes to the real Infrahub and keeps the
// bodies. Asserting on what was *not* asked is the only way to prove `schema check`
// reads no intent: a passing conformance result looks identical either way.
type recorder struct {
	mu        sync.Mutex
	paths     []string
	gqlBodies []string
}

func (r *recorder) record(path, body string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.paths = append(r.paths, path)
	if body != "" {
		r.gqlBodies = append(r.gqlBodies, body)
	}
}

func (r *recorder) queries() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.gqlBodies...)
}

// proxyTo returns an address the command can be pointed at that forwards to the real
// Infrahub, recording each request on the way through.
func proxyTo(t *testing.T, upstream string) (string, *recorder) {
	t.Helper()
	target, err := url.Parse(upstream)
	if err != nil {
		t.Fatalf("parsing %s: %v", upstream, err)
	}
	rec := &recorder{}
	proxy := httputil.NewSingleHostReverseProxy(target)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		var body string
		if req.Body != nil && req.Method == http.MethodPost {
			b, _ := io.ReadAll(req.Body)
			body = string(b)
			req.Body = io.NopCloser(strings.NewReader(body))
			req.ContentLength = int64(len(body))
		}
		rec.record(req.URL.Path, body)
		proxy.ServeHTTP(w, req)
	}))
	t.Cleanup(srv.Close)
	return srv.URL, rec
}

// checkBranch runs `schema check --branch <b>` against a recording proxy, in a scratch
// working directory so that anything the command writes relative to the cwd is caught.
func checkBranch(t *testing.T, branch string) (int, *findingsDoc, *recorder) {
	t.Helper()
	addr, rec := proxyTo(t, live(t))
	t.Setenv("INFRAHUB_ADDRESS", addr)

	dir := t.TempDir()
	t.Chdir(dir)

	code, doc := runCheckDoc(t, &checkFlags{branch: branch})

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	// The schema check writes nothing at all.
	if len(entries) != 0 {
		t.Errorf("schema check wrote %d entries into the working directory", len(entries))
	}
	return code, doc, rec
}

// The fixture branch conforms, and the answer says what was verified: the library's
// commit, and each kind the mapping reads with its fields by name (017). It holds the
// library once T060 re-seeds it; T044 extends this to the mixed fixture.
func TestSchemaCheckOnTheFixtureBranch(t *testing.T) {
	code, doc, _ := checkBranch(t, testsupport.FixtureBranch)
	if code != findings.ExitOK {
		t.Fatalf("exit %d, want 0: %+v", code, doc.Findings)
	}
	if doc.Status != string(findings.StatusOK) {
		t.Errorf("status = %q, want ok", doc.Status)
	}
	if doc.Verified == nil {
		t.Fatal("a clean check reported nothing as verified")
	}
	if doc.Verified.Model != intent.LibraryModel || doc.Verified.Version != intent.LibraryVersion {
		t.Errorf("verified %s@%s, want %s@%s", doc.Verified.Model, doc.Verified.Version, intent.LibraryModel, intent.LibraryVersion)
	}
	var kinds []string
	for _, k := range doc.Verified.Kinds {
		kinds = append(kinds, k.Kind)
		if len(k.Fields) == 0 {
			t.Errorf("kind %s names no field", k.Kind)
		}
	}
	var want []string
	for _, k := range intent.LibraryTables {
		want = append(want, k.Kind)
	}
	if !slices.Equal(kinds, want) {
		t.Errorf("verified kinds %v, want %v", kinds, want)
	}
}

// A branch that does not exist is an operational failure naming the branch, not a
// rejection: there was nothing to check (contracts/cli.md, exit 2).
func TestSchemaCheckOnAMissingBranch(t *testing.T) {
	const branch = "fylgja-test-no-such-branch"
	code, doc, _ := checkBranch(t, branch)
	if code != findings.ExitError {
		t.Fatalf("exit %d, want 2: %+v", code, doc.Findings)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Fatalf("want one operation.failed finding, got %+v", doc.Findings)
	}
	if !strings.Contains(doc.Findings[0].Message, branch) {
		t.Errorf("message does not name the branch: %s", doc.Findings[0].Message)
	}
	// Naming the branch is not enough: an operator needs a result that says the branch
	// does not exist. Infrahub says exactly that in the schema
	// endpoint's error body, and a bare "HTTP 400" would tell an operator with a typo
	// nothing.
	if !strings.Contains(doc.Findings[0].Message, "not found") {
		t.Errorf("message does not say the branch does not exist: %s", doc.Findings[0].Message)
	}
	if strings.Contains(doc.Findings[0].Message, os.Getenv("INFRAHUB_API_TOKEN")) {
		t.Error("the message carries the credential")
	}
}

// The schema check reads no intent. The proxy sees the schema endpoint and no GraphQL at
// all: conformance is the mapping's table against the schema endpoint alone (017).
func TestSchemaCheckIssuesNoObjectQuery(t *testing.T) {
	_, _, rec := checkBranch(t, testsupport.FixtureBranch)

	rec.mu.Lock()
	paths := append([]string(nil), rec.paths...)
	rec.mu.Unlock()
	if !slices.Contains(paths, "/api/schema") {
		t.Fatalf("the schema endpoint was not recorded (%v); the proxy is not in the path", paths)
	}
	for _, body := range rec.queries() {
		t.Errorf("schema check issued a GraphQL request; it must read no intent\n%s", body)
	}
}
