// Package verify reads a booted twin and holds it to intent: the readers of a booted
// node, shared by `twin verify`, the step run's VerifyTwin activity and the conformance
// suite's boot half (D-037).
//
// The readers were the suite's, moved here
// unchanged in behaviour so that product code can read a node without importing the
// suite, which no product code may (TestProductDoesNotImportConformance). Every path,
// value and absence rule is a package's conformance facet, and the transport, port,
// encoding, login and TLS its readiness block: the reader is one mechanism keyed by the
// facet, and nothing here knows which platform it reads (Constitution II; D-031).
//
// Its imports are drawn from compiler, psp, findings and lab/wire: never internal/lab,
// which imports it for its reader and its activity, and never internal/conformance.
package verify

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Update is one update of an answer: its path as the node wrote it, module prefixes
// kept, and its JSON value decoded.
type Update struct {
	Path  string
	Value any
}

// Answer is what a node answered for one path: every update of every notification, in the
// order the node sent them.
//
// A leaf comes back as one update at the leaf; a subtree at its list entry, with the
// requested subtree inside the value; a list requested whole may instead
// come back as one update per keyed entry. No update at all is how a node
// says the path holds nothing: an answer, not an error.
type Answer struct {
	Updates []Update
}

// Present says whether the node answered with anything at all.
func (a Answer) Present() bool { return len(a.Updates) > 0 }

// Reader reads one path of a booted node over the package's readiness transport, port,
// encoding and login. lab.GNMIReader is the one that reads a real node; tier 1 fakes it.
// One call is one read: a reader retries nothing.
type Reader interface {
	Get(ctx context.Context, addr string, probe wire.Probe, path string, getenv func(string) (string, bool)) (Answer, error)
}

// Unanswered is a read the node did not answer at all: its transport failed (gRPC
// Unavailable or DeadlineExceeded), as against a node that answered by refusing one path.
// A reader returns its error as one so that Read dials that node no further in the read:
// a node that accepts no connection then costs one attempt's deadline
// per read, not one per path. Its text is the reader's error's, unchanged.
type Unanswered struct{ Err error }

func (e *Unanswered) Error() string { return e.Err.Error() }

func (e *Unanswered) Unwrap() error { return e.Err }

// Packages finds a package by its platform id, as a manifest's nodes[].psp.id names it.
// *psp.Registry is one.
type Packages interface {
	LookupID(id string) (*psp.PSP, bool)
}

// ReadinessProbe is the package's readiness transport, port, encoding, login and TLS,
// which a node is read by, as the host check hands it to the probe:
// the reader shares the probe's dial, so a package whose nodes answer plaintext gRPC is
// read plaintext. Nil means TLS in both, so an omitted readiness.tls
// carries straight over; the pointer is copied rather than shared with the package.
func ReadinessProbe(p *psp.PSP) wire.Probe {
	r := p.Readiness
	probe := wire.Probe{
		Transport:   r.Probe,
		Path:        r.Path,
		Encoding:    r.Encoding,
		Port:        r.PortOrDefault(),
		UsernameEnv: r.Login.UsernameEnv,
		PasswordEnv: r.Login.PasswordEnv,
	}
	if r.TLS != nil {
		tls := *r.TLS
		probe.TLS = &tls
	}
	return probe
}

// NodeName is the node's own name for a row's port. From bundle "3" every row with a
// port carries it, equal to the production name where the platform keeps that name; a
// nil means the row has no port, so the node has no name for it at all. Only rows with
// ports are read, so the fallback is reached by no bundle this build writes; it is here
// so that a nil can never be printed as an empty name.
func NodeName(row compiler.MappingRow) string {
	if row.NodeName != nil {
		return *row.NodeName
	}
	return row.Interface
}

// LeafAt descends an answer to the requested path: the first update
// whose path is a prefix of the requested path is descended by the path's remaining
// elements, element names compared with any `module:` prefix stripped and list entries
// picked by their keys. A leaf comes back at the leaf, so there is nothing to descend; a
// subtree comes back at its list entry, with the requested part inside the value. ok is
// false when the node answered nothing, or answered about something
// that does not lead to the requested path.
func LeafAt(a Answer, requested string) (any, bool) {
	want, err := splitPath(requested)
	if err != nil {
		return nil, false
	}
	for _, u := range a.Updates {
		got, err := splitPath(u.Path)
		if err != nil || !isPrefix(got, want) {
			continue
		}
		return descend(u.Value, want[len(got):])
	}
	return nil, false
}

// ListOutcome is what a read of a requested list gave.
type ListOutcome int

const (
	ListNothing  ListOutcome = iota // the answer holds nothing at the path
	ListEntries                     // the list's entries, however many
	ListNotAList                    // something at the path that is not a list
)

// EntriesAt yields a requested list's entries, from either shape a node answers a whole
// list in:
//
//   - one update per keyed entry: the requested list's own path with a key on its last
//     element, each such update's value one entry (a request for `…/neighbors/neighbor`
//     answered at `…/neighbors/neighbor[id=1]`);
//   - one update at or above the list, descended as a leaf would be, whose value is the
//     list (`…/interface[name=X]`, with `neighbor` inside). A value that
//     is a container is looked into by the requested path's last element first, which is
//     how a node answering at the list path itself writes the list (`{"neighbor": […]}`).
//
// Something at the path that is neither is ListNotAList and comes back as value, so the
// caller words it as M6 did rather than calling it nothing.
func EntriesAt(a Answer, listPath string) (entries []any, value any, outcome ListOutcome) {
	want, err := splitPath(listPath)
	if err != nil || len(want) == 0 {
		return nil, nil, ListNothing
	}
	last := want[len(want)-1].name
	for _, u := range a.Updates {
		got, err := splitPath(u.Path)
		if err != nil {
			continue
		}
		if isKeyedEntryOf(got, want) {
			entries, outcome = append(entries, u.Value), ListEntries
			continue
		}
		if !isPrefix(got, want) {
			continue
		}
		v, ok := descend(u.Value, want[len(got):])
		if !ok {
			continue
		}
		if m, isMap := v.(map[string]any); isMap {
			if inner, found := field(m, last); found {
				v = inner
			}
		}
		if list, isList := v.([]any); isList {
			entries, outcome = append(entries, list...), ListEntries
			continue
		}
		if outcome == ListNothing {
			value, outcome = v, ListNotAList
		}
	}
	return entries, value, outcome
}

// EntryLeaf gives one leaf of a neighbour entry, found by the facet's path relative to
// the entry: `/`-separated, element by element, each member looked up with or without its
// module prefix. A single element (`system-name`) is the one-element path, which is why no
// package changed when the relative form arrived. A leaf the entry does
// not carry shows as the relative path verbatim, so a failure says which leaf was missing.
func EntryLeaf(entry map[string]any, relative string) string {
	var v any = entry
	for _, name := range strings.Split(relative, "/") {
		m, ok := v.(map[string]any)
		if !ok {
			return "(no " + relative + ")"
		}
		if v, ok = field(m, name); !ok {
			return "(no " + relative + ")"
		}
	}
	return Text(v)
}

// Text gives a decoded value as a message quotes it: a string as itself, anything else
// as its JSON.
func Text(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprint(v)
	}
	return string(b)
}

// isKeyedEntryOf says whether got is one keyed entry of the list want names: the same
// path, with a key on the last element where the request carried none. A request that
// names a list whole is answered this way by a node that reports its entries one update
// at a time; the keys themselves are the node's own and are not compared
// with anything.
func isKeyedEntryOf(got, want []pathElem) bool {
	if len(got) != len(want) || len(want) == 0 {
		return false
	}
	last := len(want) - 1
	return len(want[last].keys) == 0 && len(got[last].keys) > 0 &&
		got[last].name == want[last].name && isPrefix(got[:last], want[:last])
}

// isPrefix says whether got is a prefix of want, elements compared without their module
// prefixes and list entries by their keys.
func isPrefix(got, want []pathElem) bool {
	if len(got) > len(want) {
		return false
	}
	for i := range got {
		if !got[i].equal(want[i]) {
			return false
		}
	}
	return true
}

// descend follows a path's remaining elements into an update's value: each member by
// name, with or without a module prefix, and each keyed element's list entry by its keys.
func descend(v any, rest []pathElem) (any, bool) {
	for _, e := range rest {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, false
		}
		if v, ok = field(m, e.name); !ok {
			return nil, false
		}
		if len(e.keys) == 0 {
			continue
		}
		list, ok := v.([]any)
		if !ok {
			return nil, false
		}
		i := slices.IndexFunc(list, func(item any) bool {
			entry, ok := item.(map[string]any)
			if !ok {
				return false
			}
			for k, want := range e.keys {
				if got, ok := field(entry, k); !ok || Text(got) != want {
					return false
				}
			}
			return true
		})
		if i < 0 {
			return nil, false
		}
		v = list[i]
	}
	return v, true
}

// pathElem is one element of a path: its name without a module prefix, and its keys.
type pathElem struct {
	name string
	keys map[string]string
}

func (e pathElem) equal(o pathElem) bool {
	if e.name != o.name || len(e.keys) != len(o.keys) {
		return false
	}
	for k, v := range e.keys {
		if o.keys[k] != v {
			return false
		}
	}
	return true
}

// splitPath parses `/a/b[k=v]/c` or `mod:a/mod:b[k=v]/c`, stripping module prefixes from
// element and key names. A key's value may hold `/` (`ethernet-1/1`) but not `]`.
func splitPath(s string) ([]pathElem, error) {
	rest := strings.TrimPrefix(s, "/")
	var out []pathElem
	for rest != "" {
		end := strings.IndexAny(rest, "/[")
		if end < 0 {
			end = len(rest)
		}
		e := pathElem{name: unprefixed(rest[:end])}
		if e.name == "" {
			return nil, fmt.Errorf("path %q has an empty element", s)
		}
		rest = rest[end:]
		for strings.HasPrefix(rest, "[") {
			closing := strings.IndexByte(rest, ']')
			if closing < 0 {
				return nil, fmt.Errorf("path %q has an unclosed key", s)
			}
			k, v, ok := strings.Cut(rest[1:closing], "=")
			if !ok || k == "" {
				return nil, fmt.Errorf("path %q has a key that is not name=value", s)
			}
			if e.keys == nil {
				e.keys = map[string]string{}
			}
			e.keys[unprefixed(k)] = v
			rest = rest[closing+1:]
		}
		out = append(out, e)
		switch {
		case rest == "":
		case strings.HasPrefix(rest, "/") && len(rest) > 1:
			rest = rest[1:]
		default:
			return nil, fmt.Errorf("path %q is malformed at %q", s, rest)
		}
	}
	return out, nil
}

// unprefixed strips a `module:` prefix from a name.
func unprefixed(name string) string {
	if i := strings.LastIndexByte(name, ':'); i >= 0 {
		return name[i+1:]
	}
	return name
}

// field finds a member of a decoded JSON object by name, with or without a module
// prefix: the exact name first, then the first member, in name order, whose unprefixed
// name is it.
func field(m map[string]any, name string) (any, bool) {
	if v, ok := m[name]; ok {
		return v, true
	}
	for _, k := range slices.Sorted(maps.Keys(m)) {
		if unprefixed(k) == name {
			return m[k], true
		}
	}
	return nil, false
}
