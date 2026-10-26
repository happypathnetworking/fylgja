package ctm

import "regexp"

// The envelope's forms, as contracts/ctm.schema.json gives them and the manifest's and the
// twin record's provenance repeat them (017). They live with the type so that the reader,
// the server, validation and the record hold one form each without importing the reader:
// a CTM validation accepts compiles to a manifest its contract accepts.

// ScopePrefix begins every scope, tag:<name>.
const ScopePrefix = "tag:"

// scopeForm is the scope's one form, tag:<name>: the literal tag: and one shell word, the
// name of the BuiltinTag on every device the twin is of (017 research R-04).
var scopeForm = regexp.MustCompile(`^tag:\S+$`)

// readerForm is a reader's name, as infrahub-dcim is: lowercase letters, digits and
// hyphens, beginning with a letter or a digit.
var readerForm = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)

// ValidScope is whether value is a scope, tag:<name>; the empty value is not. The server
// refuses a request's scope by it, stage.Read a scope that reached it unchecked, and
// validation and the record a scope written by hand.
func ValidScope(value string) bool {
	return scopeForm.MatchString(value)
}

// ValidReader is whether value is a reader's name; the empty value is not.
func ValidReader(value string) bool {
	return readerForm.MatchString(value)
}
