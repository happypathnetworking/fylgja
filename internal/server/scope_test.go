package server

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// scopeOptions are a request's options on a server whose default scope is def.
func scopeOptions(def string) *options {
	s := New("")
	s.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	s.DefaultScope = def
	return s.newCall(context.Background(), findings.OpIntentRead, api.Request{Render: api.RenderJSON},
		newFrames(io.Discard, nil), nil).options()
}

// The request's scope is the one it names, or the server's default when it names none; a
// value that is not tag:<name>, the empty one included, is scope.invalid naming it, and no
// scope beside no default is scope.unset naming the variable, each exit 2 at step start
// (contracts/scope-and-commands.md).
func TestScopeOf(t *testing.T) {
	for _, c := range []struct {
		name      string
		def       string
		given     string
		givenSet  bool
		want      string
		rule      string
		object    string
		inMessage string
	}{
		{name: "the default", def: "tag:fylgja", want: "tag:fylgja"},
		{name: "the argument over the default", def: "tag:fylgja", given: "tag:lab-b", givenSet: true, want: "tag:lab-b"},
		{name: "the argument with no default", given: "tag:fylgja", givenSet: true, want: "tag:fylgja"},
		{name: "no tag: prefix", def: "tag:fylgja", given: "fylgja", givenSet: true,
			rule: findings.RuleScopeInvalid, object: "fylgja", inMessage: "tag:<name>"},
		{name: "another prefix", def: "tag:fylgja", given: "group:x", givenSet: true,
			rule: findings.RuleScopeInvalid, object: "group:x", inMessage: "tag:<name>"},
		{name: "no name", def: "tag:fylgja", given: "tag:", givenSet: true,
			rule: findings.RuleScopeInvalid, object: "tag:", inMessage: "tag:<name>"},
		{name: "two words", def: "tag:fylgja", given: "tag:a b", givenSet: true,
			rule: findings.RuleScopeInvalid, object: "tag:a b", inMessage: "tag:<name>"},
		{name: "given empty", def: "tag:fylgja", given: "", givenSet: true,
			rule: findings.RuleScopeInvalid, object: "", inMessage: "tag:<name>"},
		{name: "unset", rule: findings.RuleScopeUnset, object: EnvDefaultScope, inMessage: EnvDefaultScope},
	} {
		t.Run(c.name, func(t *testing.T) {
			subject := &findings.Subject{Branch: "b"}
			got, err := scopeOf(scopeOptions(c.def), findings.OpIntentRead, subject, c.given, c.givenSet)
			if c.rule == "" {
				if err != nil || got != c.want {
					t.Fatalf("scopeOf = %q, %v; want %q", got, err, c.want)
				}
				return
			}
			var res *result
			if !asResult(err, &res) {
				t.Fatalf("scopeOf = %q, %v; want the document refusing %s", got, err, c.rule)
			}
			doc := res.doc
			if got != "" || doc.Status.ExitCode() != findings.ExitError || doc.Subject != subject || len(doc.Findings) != 1 {
				t.Fatalf("scopeOf = %q, exit %d, findings %+v; want no scope, exit 2 and one finding", got, doc.Status.ExitCode(), doc.Findings)
			}
			f := doc.Findings[0]
			if f.Severity != findings.Rejection || f.Rule != c.rule || f.Object != c.object || f.Step != findings.StepStart ||
				!strings.Contains(f.Message, c.inMessage) {
				t.Errorf("finding %+v; want a rejection %s of %q at step start whose message names %s", f, c.rule, c.object, c.inMessage)
			}
		})
	}
}

// The server's default is checked with the request's own rule, so fylgja serve refuses at
// start a value no request could name.
func TestValidScope(t *testing.T) {
	for value, want := range map[string]bool{
		"tag:fylgja": true, "tag:lab-b.2": true,
		"": false, "fylgja": false, "group:x": false, "tag:": false, "tag:a b": false, " tag:a": false, "tag:a\n": false,
	} {
		if got := ValidScope(value); got != want {
			t.Errorf("ValidScope(%q) = %t, want %t", value, got, want)
		}
	}
}
