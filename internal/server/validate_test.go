package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// handlerServer is testServer with each operation's own handler, as fylgja serve runs it:
// nothing a request here reaches dials the workflow service, runs containerlab or reads a
// node, so each of those fails the test.
func handlerServer(t *testing.T) *httptest.Server {
	t.Helper()
	s := New(testToken)
	s.Build = testBuild
	s.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	s.Dial = func(context.Context, *slog.Logger) (provision.Service, error) {
		t.Error("the workflow service was dialled")
		return nil, errors.New("not in this test")
	}
	s.Runner = failRunner{t}
	s.Reader = failReader{t}
	srv := httptest.NewServer(s.Handler())
	t.Cleanup(srv.Close)
	return srv
}

// handled sends req to op and returns the answer's out text and its document.
func handled(t *testing.T, srv *httptest.Server, op string, req api.Request) (string, *findings.Document) {
	t.Helper()
	body, err := api.EncodeRequest(req)
	if err != nil {
		t.Fatal(err)
	}
	resp, answer := post(t, nil, srv.URL+api.Path(op), testToken, string(body), nil)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("%s: status %d: %s", op, resp.StatusCode, answer)
	}
	var out strings.Builder
	var doc *findings.Document
	for _, line := range answerLines(t, answer) {
		f := frameOf(t, line)
		out.WriteString(f.Out)
		if f.Kind() == api.KindDocument {
			doc = &findings.Document{}
			if err := json.Unmarshal(f.Document, doc); err != nil {
				t.Fatalf("%s: the document: %v", op, err)
			}
		}
	}
	if doc == nil {
		t.Fatalf("%s: no document in %s", op, answer)
	}
	return out.String(), doc
}

// wantOperationFailed holds doc to one operation.failed with message, exit 2 and no step.
func wantOperationFailed(t *testing.T, label string, doc *findings.Document, message string) {
	t.Helper()
	if doc.Status.ExitCode() != 2 || len(doc.Findings) != 1 {
		t.Errorf("%s: exit %d, findings %+v; want one operation.failed, exit 2", label, doc.Status.ExitCode(), doc.Findings)
		return
	}
	f := doc.Findings[0]
	if f.Rule != findings.RuleOperationFailed || f.Step != "" || f.Message != message {
		t.Errorf("%s: %s at step %q: %q\nwant operation.failed, no step: %q", label, f.Rule, f.Step, f.Message, message)
	}
}

// A psp.validate request whose files are not one package for each path of args.files, in
// order and under that path, is refused before anything is validated: no path is called
// valid whose package was never sent, and no verdict is another file's. Each of these
// answered "valid", status ok, before (contracts/api.md, "Files").
func TestAPackageNotSentUnderItsPathIsRefused(t *testing.T) {
	srv := handlerServer(t)
	pkg, err := os.ReadFile(repoPath("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	other, err := os.ReadFile(repoPath("psp", "arista_eos.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	paths := func(p ...string) map[string]json.RawMessage {
		raw, _ := json.Marshal(append([]string{}, p...))
		return map[string]json.RawMessage{"files": raw}
	}
	const takes = " where psp validate takes at least one path and one package for each, in order and under that path"
	for _, c := range []struct {
		label string
		req   api.Request
		says  string
	}{
		{"no file", api.Request{Args: paths("psp/never-sent.yaml")},
			"the request carries 0 files for 1 path" + takes},
		{"a file under another path", api.Request{Args: paths("a.yaml"),
			Files: []api.File{{Path: "b.yaml", Data: pkg}}},
			"the request carries 1 file for 1 path" + takes},
		{"two files in the other order", api.Request{Args: paths("a.yaml", "b.yaml"),
			Files: []api.File{{Path: "b.yaml", Data: other}, {Path: "a.yaml", Data: pkg}}},
			"the request carries 2 files for 2 paths" + takes},
		{"a file more than the paths", api.Request{Args: paths("a.yaml"),
			Files: []api.File{{Path: "a.yaml", Data: pkg}, {Path: "a.yaml", Data: pkg}}},
			"the request carries 2 files for 1 path" + takes},
		{"no path", api.Request{Args: paths()},
			"the request carries 0 files for 0 paths" + takes},
		{"no argument", api.Request{Files: []api.File{{Path: "a.yaml", Data: pkg}}},
			"the request carries 1 file for 0 paths" + takes},
	} {
		c.req.Render = api.RenderText
		out, doc := handled(t, srv, findings.OpPSPValidate, c.req)
		if out != "" {
			t.Errorf("%s: printed %q", c.label, out)
		}
		wantOperationFailed(t, c.label, doc, c.says)
		for _, f := range doc.Findings {
			for _, p := range [][]byte{pkg, other} {
				if strings.Contains(f.Message, string(p[:40])) {
					t.Errorf("%s: the sentence carries a file's content", c.label)
				}
			}
		}
	}

	// The CLI's request, each package under its path in order, is validated as before.
	out, doc := handled(t, srv, findings.OpPSPValidate, api.Request{Render: api.RenderText,
		Args: paths("a.yaml", "b.yaml"), Files: []api.File{{Path: "a.yaml", Data: pkg}, {Path: "b.yaml", Data: other}}})
	if doc.Status != findings.StatusOK || out != "a.yaml: valid\nb.yaml: valid\n" {
		t.Errorf("the CLI's request: status %s, printed %q", doc.Status, out)
	}
}

// twin.compile takes the CTM alone, under the path --ctm gives: a request carrying no file
// or two is refused in one sentence naming the count, and one whose file is under another
// path in one saying so, before anything is parsed or loaded. The third compiled the golden
// and answered ok, naming a.json, before.
func TestACompileWithoutOneCTMIsRefused(t *testing.T) {
	srv := handlerServer(t)
	ctm, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	args := map[string]json.RawMessage{"ctm": json.RawMessage(`"a.json"`), "out": json.RawMessage(`"out"`)}
	for _, c := range []struct {
		label string
		files []api.File
		says  string
	}{
		{"no file", nil, "the request carries 0 files where twin compile takes the CTM alone"},
		{"two files", []api.File{{Path: "a.json", Data: ctm}, {Path: "a.json", Data: ctm}},
			"the request carries 2 files where twin compile takes the CTM alone"},
		{"a file under another path", []api.File{{Path: "b.json", Data: ctm}},
			"the request carries its CTM under another path than --ctm gives, where twin compile takes the CTM alone, under that path"},
	} {
		out, doc := handled(t, srv, findings.OpCompile, api.Request{Render: api.RenderText, Args: args, Files: c.files})
		if out != "" {
			t.Errorf("%s: printed %q", c.label, out)
		}
		wantOperationFailed(t, c.label, doc, c.says)
		if doc.BundleID != "" || doc.Subject == nil || doc.Subject.CTM != "a.json" || doc.Subject.Branch != "" {
			t.Errorf("%s: bundle_id %q, subject %+v; want no bundle_id and a.json alone, nothing parsed", c.label, doc.BundleID, doc.Subject)
		}
		for _, f := range doc.Findings {
			if strings.Contains(f.Message, string(ctm[:40])) || strings.Contains(f.Message, "b.json") {
				t.Errorf("%s: the sentence carries the file: %q", c.label, f.Message)
			}
		}
	}

	// The CLI's request, the CTM under the path --ctm gives, compiles as before.
	out, doc := handled(t, srv, findings.OpCompile, api.Request{Render: api.RenderText, Args: args,
		Files: []api.File{{Path: "a.json", Data: ctm}}})
	if doc.Status != findings.StatusOK || !strings.HasPrefix(out, "wrote bundle to out (3 nodes, 3 links)\n") {
		t.Errorf("the CLI's request: status %s, printed %q", doc.Status, out)
	}
}
