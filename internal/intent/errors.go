package intent

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
)

// redact removes the credential from an error. Transport errors can carry a request
// dump, and an error message is printed, logged, and pasted into issues.
func redact(err error, token string) error {
	if err == nil || token == "" {
		return err
	}
	msg := err.Error()
	if !strings.Contains(msg, token) {
		return err
	}
	return fmt.Errorf("%s", strings.ReplaceAll(msg, token, "<redacted>"))
}

// ErrBranchNotFound marks a read that could not run because Infrahub has no such branch:
// one never created, or deleted since (verified on 1.11.2). errors.Is finds it on the
// error a read returns; the error's text is Infrahub's own
// sentence, unchanged, so the stage commands still report operation.failed as M1 did.
// A following check tells it from an unreachable Infrahub by this mark, never by the text.
var ErrBranchNotFound = errors.New("branch not found")

// branchMissing carries ErrBranchNotFound on a failure without changing what it says.
type branchMissing struct{ error }

func (e branchMissing) Is(target error) bool { return target == ErrBranchNotFound }
func (e branchMissing) Unwrap() error        { return e.error }

// notFound is Infrahub's sentence for a branch it does not have, from both the schema
// endpoint (HTTP 400) and GraphQL (HTTP 404).
func notFound(branch string) string { return "Branch: " + branch + " not found." }

// namesBranch reports whether one of Infrahub's messages says branch does not exist.
func namesBranch(msgs []string, branch string) bool {
	for _, m := range msgs {
		if m == notFound(branch) {
			return true
		}
	}
	return false
}

// authFailure recognises an authentication rejection and says what to do about it
// without quoting anything from the environment.
func authFailure(status int) error {
	switch status {
	case 401:
		return credentialRefused{fmt.Sprintf("the credential in %s was rejected by Infrahub", EnvToken)}
	case 403:
		return credentialRefused{fmt.Sprintf("the credential in %s is not permitted to read this branch", EnvToken)}
	default:
		return nil
	}
}

// credentialRefused is authFailure's error. Its type lets a caller tell a refused
// credential from an unreachable Infrahub without reading the text, through the
// *url.Error the HTTP client wraps it in.
type credentialRefused struct{ reason string }

func (e credentialRefused) Error() string { return e.reason }

// describe names the intent reference a failure was about. Infrahub's refusals are
// exact but context-free — "Branch: x not found", "Requested time … is before branch
// 'main' was created at …" — and an operator who ran several reads needs to know which
// (branch, at) Fylgja actually sent. It never carries the credential: it is
// built from the reference the operator gave.
func (c Config) describe() string {
	if c.At == "" {
		return "(branch " + c.Branch + ")"
	}
	return "(branch " + c.Branch + ", at " + c.At + ")"
}

// explain turns a GraphQL transport failure into Infrahub's own words.
//
// The three refusals this maps are the ones an operator can act on: 404 for a branch
// that does not exist, 422 for an `at` before the default branch was created, and 400
// for an `at` Infrahub cannot parse. All three arrive as a genqlient HTTPError
// whose Error() is a JSON dump of the whole response, which buries the one sentence
// that matters. Surfacing Infrahub's message verbatim is deliberate: Fylgja
// does not paraphrase what the server said about time travel, because the server is
// the authority on it.
func explain(err error) error {
	var httpErr *graphql.HTTPError
	if !errors.As(err, &httpErr) {
		return err
	}
	msgs := infrahubMessages(httpErr)
	if len(msgs) == 0 {
		return err
	}
	return fmt.Errorf("HTTP %d: %s", httpErr.StatusCode, strings.Join(msgs, "; "))
}

// explainStatus is explain for a REST response, which arrives as a status and a body
// rather than a genqlient error.
//
// The schema endpoint is where a read first touches Infrahub, so it — not the GraphQL
// query — is what answers for a branch that does not exist, and it answers 400 with
// `{"errors":[{"message":"Branch: x not found."}]}`. Reporting only the status code
// would leave an operator with `HTTP 400` for a typo'd branch name, which names the
// problem for nobody. The same decision applies to both transports: surface Infrahub's
// own sentence and let the server be the authority on its own refusals.
//
// Returns "HTTP <code>" unchanged when the body is not an error document — an HTML
// error page from a proxy in front of Infrahub, say — because a status code is still
// better than a page of markup.
func explainStatus(status int, body []byte) string {
	msgs := unwrapErrorBody(string(body))
	if len(msgs) == 0 {
		return fmt.Sprintf("HTTP %d", status)
	}
	return fmt.Sprintf("HTTP %d: %s", status, strings.Join(msgs, "; "))
}

// infrahubMessages pulls the human-readable messages out of an error response.
//
// Infrahub answers in two shapes: GraphQL's `errors: [{message: …}]`, and — for a
// branch that does not exist — a bare `errors: ["…"]` of strings, which genqlient
// cannot decode into its own type and so hands back as one message holding the raw
// body. Both are unwrapped here, so the caller gets sentences rather than JSON.
func infrahubMessages(httpErr *graphql.HTTPError) []string {
	var out []string
	for _, e := range httpErr.Response.Errors {
		if e == nil {
			continue
		}
		if nested := unwrapErrorBody(e.Message); len(nested) > 0 {
			out = append(out, nested...)
			continue
		}
		if m := strings.TrimSpace(e.Message); m != "" {
			out = append(out, m)
		}
	}
	return out
}

// unwrapErrorBody reads a message that is itself an error document, returning the
// messages inside it. Empty when the message is ordinary prose.
func unwrapErrorBody(message string) []string {
	if !strings.HasPrefix(strings.TrimSpace(message), "{") {
		return nil
	}
	var body struct {
		Errors []json.RawMessage `json:"errors"`
	}
	if err := json.Unmarshal([]byte(message), &body); err != nil {
		return nil
	}
	var out []string
	for _, raw := range body.Errors {
		var text string
		if err := json.Unmarshal(raw, &text); err == nil {
			if text = strings.TrimSpace(text); text != "" {
				out = append(out, text)
			}
			continue
		}
		var obj struct {
			Message string `json:"message"`
		}
		if err := json.Unmarshal(raw, &obj); err == nil {
			if obj.Message = strings.TrimSpace(obj.Message); obj.Message != "" {
				out = append(out, obj.Message)
			}
		}
	}
	return out
}
