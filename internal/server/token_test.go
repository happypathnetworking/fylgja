package server

import (
	"fmt"
	"net/http"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// The API's token is in nothing the server writes. On every route, the twelve operations, the
// interrupt and the paths that
// name nothing served, with the right token, a wrong one and none: no frame, document, problem
// body, header or log line carries either token.
func TestTheTokenIsInNothingTheServerWrites(t *testing.T) {
	_, srv, log, _ := testServer(t, func(c *call) error {
		o := c.options()
		o.note("a line of progress")
		_, _ = fmt.Fprintln(o.stderr(), "a line for stderr")
		c.eventFrame(provision.Event{WorkflowID: provision.WorkflowProvision, Step: "read"})
		return &result{doc: findings.ErrorDocument(c.op, nil, "a failure of the operation's own")}
	})
	paths := append(routes(), "/v1/no/such", "/v2/twin/show", "/")
	answers := 0
	for _, path := range paths {
		for _, token := range []string{testToken, wrongToken, ""} {
			for _, render := range []string{api.RenderText, api.RenderJSON, ""} {
				header := map[string]string{api.HeaderStream: fmt.Sprintf("stream-%d", answers)}
				resp, body := post(t, nil, srv.URL+path, token, `{"render":"`+render+`"}`, header)
				answers++
				label := fmt.Sprintf("%s with token %q, render %q (%d)", path, token, render, resp.StatusCode)
				if token == testToken && path == api.Path(findings.OpTwinShow) && resp.StatusCode != http.StatusOK {
					t.Fatalf("%s: the right token was not served, so the case proves nothing", label)
				}
				carriesNoToken(t, label, string(body), headerText(resp.Header))
			}
		}
	}
	waitForLog(t, log, "operation=unknown", "outcome=version_unknown")
	if len(log.requestLines()) == 0 {
		t.Fatal("the server logged nothing, so the log's absence of a token proves nothing")
	}
	carriesNoToken(t, "the log", log.String())
}
