// Package bundle writes an artifact bundle to disk and identifies it.
//
// Writing is separated from compiling so the compiler can stay pure (Constitution V).
// It is also where two guarantees live that matter more than they look: a rejected
// compile leaves nothing behind, and an existing bundle is never half-overwritten.
// A partially written bundle would be worse than none, because M2 would
// deploy it.
//
// The currency is the compiler's file map — path relative to the bundle root, and
// bytes. The layout names those paths use are the compiler's (compiler.TopologyFile,
// compiler.ManifestFile, compiler.ConfigsDir); nothing here needs to know them, which
// is what lets a new file appear in a bundle without touching this package.
package bundle

import "github.com/happypathnetworking/fylgja/internal/tree"

// The writing itself is internal/tree's from M13, shared with the API's client, which
// must not link this package. The names stay here, so
// no caller and no test of this package moves.

// ErrNotEmpty reports that the target directory already holds something.
type ErrNotEmpty = tree.ErrNotEmpty

// Write materialises a bundle at dir: built in a temporary sibling directory and moved
// into place, so the target either does not exist or is complete, and a target that
// exists and is non-empty is refused (tree.Write).
func Write(files map[string][]byte, dir string) error { return tree.Write(files, dir) }

// checkTarget allows a missing directory or an empty one, and nothing else.
func checkTarget(dir string) error { return tree.CheckTarget(dir) }
