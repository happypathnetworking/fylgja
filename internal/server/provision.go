package server

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/tree"
)

type provisionFlags struct {
	dryRun bool
}

func runTwinProvision(ctx context.Context, opts *options, f *provisionFlags, dir string, files []api.File) error {
	const op = findings.OpTwinProvision
	subject := &findings.Subject{Bundle: dir}
	if ctx == nil {
		ctx = context.Background()
	}

	// The bundle the client sent is written into a scratch directory under the store, and
	// verified and filed from there; dir is the directory as the operator gave it, which
	// every sentence names and the server never opens. The scratch
	// directory goes once the bundle is filed, before the run, which can outlive this
	// handler's defers, and on every earlier exit. The state root's failure, and a store
	// that cannot be written, are reported where M12 reported them, after the verify, so a
	// bundle that cannot reach the store is written beside the system's temporary files
	// until then.
	paths, pathsErr := opts.paths()
	roots := []string{os.TempDir()}
	if pathsErr == nil {
		roots = []string{paths.Bundles, os.TempDir()}
	}
	src, removeUpload, err := upload(roots, dir, files)
	if err != nil {
		return failAt(op, subject, findings.StepVerify, dir, "%v", err)
	}
	defer removeUpload()

	// Verified before anything else: a directory that is not a bundle this build deploys, or
	// whose bytes are not the identity it claims, is refused by name before any run starts
	// (D-024). A directory that cannot be read at all is the operation failing.
	id, err := bundle.Verify(src)
	asGiven(err, dir)
	if list := verifyRefusal(dir, err); list != nil {
		return finish(op, subject, list)
	}
	if err != nil {
		return failAt(op, subject, findings.StepVerify, dir, "%s", namedAsGiven(err, src, dir))
	}

	// An override package `psp validate` rejects is refused under its own findings before
	// anything is filed or started.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepVerify, err)
	}

	if pathsErr != nil {
		return failAt(op, subject, findings.StepVerify, findings.StepVerify, "%v", pathsErr)
	}
	store := bundle.NewDirStore(paths.Bundles)
	if done := fileBundle(ctx, op, subject, store, dir, src, id); done != nil {
		return done
	}
	// The dry run and the run read the filed copy alone. A server stopped while the run is
	// followed exits without running this handler's defers, so the scratch copy goes now.
	removeUpload()

	// A dry run reports what the run would do from here, with no read, and starts nothing.
	if f.dryRun {
		return dryRunReport(ctx, opts, op, subject, reg, paths, store.Path(id), id, nil, nil,
			findings.DryRunFollow{Reason: findings.FollowReasonBundle})
	}

	// The stored copy's absolute path is what crosses the queue, so a worker resolves it
	// wherever it was started from.
	return runProvision(ctx, opts, op, subject, provision.ProvisionInput{
		Source:     wire.SourceBundle,
		BundlePath: store.Path(id),
		BundleID:   id,
		Version:    opts.version(),
	})
}

// verifyRefusal is the finding a bundle verification refusal is reported under, or nil when
// err is not one.
func verifyRefusal(dir string, err error) findings.List {
	var invalid *bundle.ErrInvalid
	var unsupported *bundle.ErrVersionUnsupported
	var mismatch *bundle.ErrIDMismatch
	var rule string
	switch {
	case errors.As(err, &invalid):
		rule = findings.RuleBundleInvalid
	case errors.As(err, &unsupported):
		rule = findings.RuleBundleVersionUnsupported
	case errors.As(err, &mismatch):
		rule = findings.RuleBundleIDMismatch
	default:
		return nil
	}
	var list findings.List
	list.AddStep(findings.Rejection, findings.StepVerify, rule, dir, err.Error())
	return list
}

// fileBundle files the verified bundle at src, the directory the operator gave as dir, in
// the store under id, reusing an entry already there once it has been re-verified.
// A corrupt store entry is bundle.id.mismatch naming the store path. It
// returns the command's result when filing stopped the command, and nil when the bundle is
// filed.
func fileBundle(ctx context.Context, op string, subject *findings.Subject, store bundle.Store, dir, src, id string) error {
	stored, err := store.Put(ctx, src)
	var mismatch *bundle.ErrIDMismatch
	switch {
	case errors.As(err, &mismatch):
		var list findings.List
		list.AddStep(findings.Rejection, findings.StepVerify, findings.RuleBundleIDMismatch, mismatch.Path,
			provision.StoreMismatchMessage(mismatch, id))
		return finish(op, subject, list)
	case err != nil:
		return failAt(op, subject, findings.StepVerify, dir, "filing %s in the bundle store: %s", dir, namedAsGiven(err, src, dir))
	case stored != id:
		return failAt(op, subject, findings.StepVerify, dir,
			"%s hashed to %s when verified and to %s when filed: it changed while being read", dir, id, stored)
	}
	return nil
}

// upload writes the files of a bundle the client sent into a scratch directory under the
// first of roots that can hold one, and returns that copy and the function that removes it.
// The store's root comes first, and the system's temporary directory
// after it, so a store that cannot be written does not stop the verify: M12 refused a bad
// bundle as such whatever the store, and filed a good one only after. The copy is
// named after the given directory when that is a bundle identity, so a directory that claims
// an identity still claims it (D-024), and bundle otherwise. No error names the copy: the
// files' paths are checked before anything is written, so a path that is the bundle's root,
// leads out of it, lies beneath another file or is sent twice is refused by its path inside
// the bundle, as one not in canonical form is.
func upload(roots []string, given string, files []api.File) (string, func(), error) {
	names := make([]string, len(files))
	for i, f := range files {
		names[i] = f.Path
	}
	if err := tree.CheckPaths(names); err != nil {
		return "", nil, err
	}
	var scratch string
	var err error
	for _, root := range roots {
		if scratch, err = scratchUnder(root); err == nil {
			break
		}
	}
	if err != nil {
		return "", nil, fmt.Errorf("preparing a scratch copy of %s: %w", given, err)
	}
	remove := func() { _ = os.RemoveAll(scratch) }
	name := "bundle"
	if base := filepath.Base(filepath.Clean(given)); bundle.IsID(base) {
		name = base
	}
	m := make(map[string][]byte, len(files))
	for _, f := range files {
		m[f.Path] = f.Data
	}
	src := filepath.Join(scratch, name)
	if err := tree.Write(m, src); err != nil {
		remove()
		return "", nil, errors.New(namedAsGiven(err, src, given))
	}
	return src, remove, nil
}

// scratchUnder makes a scratch directory under root. Its error names root and the reason,
// and not the scratch directory's pattern.
func scratchUnder(root string) (string, error) {
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", fmt.Errorf("%s: %w", root, reasonOf(err))
	}
	scratch, err := os.MkdirTemp(root, ".fylgja-upload-*")
	if err != nil {
		return "", fmt.Errorf("%s: %w", root, reasonOf(err))
	}
	return scratch, nil
}

// reasonOf is a path error's reason alone, without the path it names.
func reasonOf(err error) error {
	var pathErr *fs.PathError
	if errors.As(err, &pathErr) {
		return pathErr.Err
	}
	return err
}

// namedAsGiven is err's sentence with the scratch copy's path, src, named as the directory
// the operator gave: every sentence names that directory, and none the server's copy of it.
func namedAsGiven(err error, src, given string) string {
	return strings.ReplaceAll(err.Error(), src, given)
}

// asGiven names the directory the operator gave in a verification's refusal, where the
// sentence named the scratch copy: every refusal begins with that path.
func asGiven(err error, given string) {
	var invalid *bundle.ErrInvalid
	var unsupported *bundle.ErrVersionUnsupported
	var mismatch *bundle.ErrIDMismatch
	switch {
	case errors.As(err, &invalid):
		invalid.Dir = given
	case errors.As(err, &unsupported):
		unsupported.Dir = given
	case errors.As(err, &mismatch):
		mismatch.Path = given
	}
}
