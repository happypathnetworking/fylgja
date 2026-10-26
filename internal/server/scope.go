package server

import (
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// EnvDefaultScope names the scope a request that names none is read under (017): read by
// fylgja serve at start into Server.DefaultScope, and never by a client or the worker,
// whose every read carries its scope in its input.
const EnvDefaultScope = "FYLGJA_DEFAULT_SCOPE"

// ValidScope is whether value is a scope, tag:<name>: the literal tag: and one shell word,
// the name of the BuiltinTag on every device the twin is of (research R-04); the empty
// value is not. The form is the reader's (intent.ValidScope), which stage.Read holds every
// read to.
func ValidScope(value string) bool {
	return intent.ValidScope(value)
}

// scopeOf is the scope a request's read is made under: the request's --scope when it was
// given, whatever its value, and otherwise the server's DefaultScope. A value given that
// is not tag:<name>, an empty one included, is scope.invalid naming it; no --scope beside
// no default is scope.unset naming the variable. Each is exit 2 at step start, refused
// before the packages load and before any connection, after the command's --branch and
// --stage guards (contracts/scope-and-commands.md). op and subject are the document's.
func scopeOf(opts *options, op string, subject *findings.Subject, given string, givenSet bool) (string, error) {
	refuse := func(rule, object, message string) error {
		doc := findings.RuleErrorDocument(op, subject, rule, object, message)
		doc.Findings[0].Step = findings.StepStart
		return &result{doc: doc}
	}
	if givenSet {
		if !ValidScope(given) {
			return "", refuse(findings.RuleScopeInvalid, given, fmt.Sprintf(
				"--scope %q is not a scope: the accepted form is tag:<name>, the literal tag: and one word, the tag every device of the twin carries",
				given))
		}
		return given, nil
	}
	if scope := opts.c.s.DefaultScope; scope != "" {
		return scope, nil
	}
	return "", refuse(findings.RuleScopeUnset, EnvDefaultScope, fmt.Sprintf(
		"no --scope was given and the server has no default: name one with --scope tag:<name>, or set %s where fylgja serve starts",
		EnvDefaultScope))
}
