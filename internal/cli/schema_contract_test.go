//go:build contract

package cli

import (
	"encoding/json"
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

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
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

// The fixture branch conforms, and the answer says what was verified: the contract
// version and each generic with the kinds implementing it by name.
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
	if doc.Verified.ContractVersion != ctm.ContractVersion {
		t.Errorf("contract_version = %q, want %q", doc.Verified.ContractVersion, ctm.ContractVersion)
	}
	// Each required generic, then the artifact target's row (M5, contracts/cli.md).
	if len(doc.Verified.Generics) != len(ctm.RequiredGenerics)+1 {
		t.Fatalf("verified %d generics, want %d: %+v",
			len(doc.Verified.Generics), len(ctm.RequiredGenerics)+1, doc.Verified.Generics)
	}
	if last := doc.Verified.Generics[len(doc.Verified.Generics)-1]; last.Generic != ctm.ArtifactTargetGeneric ||
		!slices.Contains(last.Kinds, "NetworkDevice") {
		t.Errorf("last verified row %+v, want %s naming NetworkDevice", last, ctm.ArtifactTargetGeneric)
	}
	for _, g := range doc.Verified.Generics {
		if len(g.Kinds) == 0 {
			t.Errorf("generic %s names no implementing kind", g.Generic)
		}
		for _, k := range g.Kinds {
			if k == "" {
				t.Errorf("generic %s names an unnamed kind", g.Generic)
			}
		}
	}
}

// A branch that implements the generics but holds no contract node is rejected by rule,
// not by a transport error, and the rule names the branch. Since M5 put Fylgja's schema on
// main no branch is without it, so main is that branch: its kinds implement
// every generic and it holds no FylgjaContract, and no generic is named unimplemented. What
// the M1 test proved of a bare branch is tier 1's since M5 (intent's conformance_test.go,
// against a faked schema).
func TestSchemaCheckOnABranchWithoutAContractNode(t *testing.T) {
	code, doc, _ := checkBranch(t, "main")
	if code != findings.ExitRejected {
		t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
	}
	byRule := map[string]int{}
	for _, f := range doc.Findings {
		byRule[f.Rule]++
		if f.Object == "" {
			t.Errorf("finding %s names no object", f.Rule)
		}
		if f.Rule == findings.RuleContractNodeMissing && f.Object != "main" {
			t.Errorf("finding %+v, want the branch main named", f)
		}
	}
	if byRule[findings.RuleContractNodeMissing] != 1 {
		t.Errorf("%d %s findings, want 1: %+v", byRule[findings.RuleContractNodeMissing],
			findings.RuleContractNodeMissing, doc.Findings)
	}
	if byRule[findings.RuleGenericUnimplemented] != 0 {
		t.Errorf("%d %s findings on main, whose schema implements every generic: %+v", byRule[findings.RuleGenericUnimplemented],
			findings.RuleGenericUnimplemented, doc.Findings)
	}
	if doc.Verified != nil {
		t.Error("a rejected check reported something as verified")
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

// The schema check reads no intent. The proxy sees the schema endpoint and the
// contract-version query, and nothing that asks for a device, an interface or a link.
func TestSchemaCheckIssuesNoObjectQuery(t *testing.T) {
	_, _, rec := checkBranch(t, testsupport.FixtureBranch)

	queries := rec.queries()
	if len(queries) == 0 {
		t.Fatal("no GraphQL request was recorded; the proxy is not in the path")
	}
	for _, body := range queries {
		var req struct {
			Query string `json:"query"`
		}
		if err := json.Unmarshal([]byte(body), &req); err != nil {
			t.Fatalf("unreadable GraphQL request: %v", err)
		}
		if !strings.Contains(req.Query, ctm.ContractKind) {
			t.Errorf("schema check issued a query that is not the contract version: %s", req.Query)
		}
		for _, generic := range ctm.RequiredGenerics {
			if strings.Contains(req.Query, generic) {
				t.Errorf("schema check queried %s: it must read no intent\n%s", generic, req.Query)
			}
		}
	}
}
