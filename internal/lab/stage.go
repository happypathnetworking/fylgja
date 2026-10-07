package lab

import (
	"context"
	"fmt"
	"os"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// StageBundle copies the bundle the run was given into the twin directory, verified, so
// what deploys is exactly what was compiled (D-024).
//
// The source is BundlePath, never a lookup by id alone: the bundle is first filed in this
// worker's store (a verified no-op when the store already holds it), then fetched from
// there. A CLI and a worker on different state roots therefore stage the bundle the CLI
// sent rather than failing on an empty store, and the worker's store holds it afterwards
// afterwards. A twin/bundle/ that already hashes to BundleID is a retry finding its own
// work done, and is accepted.
//
// Every failure is stage.failed, which no retry helps: a copy that cannot be made, a
// bundle path hashing to another identity than the run was given, or a twin/bundle/
// holding a different bundle — the host check found no twin directory, so that one was
// put there by something other than this run.
func (a *Activities) StageBundle(ctx context.Context, in wire.StageInput) (wire.StageResult, error) {
	done := wire.StageResult{TwinDir: a.Paths.Twin}
	failed := func(object, format string, args ...any) (wire.StageResult, error) {
		return wire.StageResult{}, StepFailure(findings.StepStage, findings.RuleStageFailed, object, fmt.Sprintf(format, args...))
	}

	present, err := exists(a.Paths.TwinBundle)
	if err != nil {
		return failed(a.Paths.TwinBundle, "inspecting %s: %v", a.Paths.TwinBundle, err)
	}
	if present {
		got, err := bundle.IDOfDir(a.Paths.TwinBundle)
		if err != nil {
			return failed(a.Paths.TwinBundle, "reading the bundle already at %s: %v", a.Paths.TwinBundle, err)
		}
		if got != in.BundleID {
			return failed(a.Paths.TwinBundle, "%s already holds bundle %s, not %s; fylgja twin destroy clears it",
				a.Paths.TwinBundle, got, in.BundleID)
		}
		return done, nil
	}

	// Checked before anything is copied, so a bundle the run was not given is never filed.
	id, err := bundle.IDOfDir(in.BundlePath)
	if err != nil {
		return failed(in.BundlePath, "reading the bundle at %s: %v", in.BundlePath, err)
	}
	if id != in.BundleID {
		return failed(in.BundlePath, "the bundle at %s hashes to %s, but the run was given %s", in.BundlePath, id, in.BundleID)
	}
	if _, err := a.Store.Put(ctx, in.BundlePath); err != nil {
		return failed(in.BundlePath, "filing %s in the bundle store: %v", in.BundlePath, err)
	}
	if err := a.Store.Fetch(ctx, in.BundleID, a.Paths.TwinBundle); err != nil {
		return failed(a.Paths.TwinBundle, "staging bundle %s into %s: %v", in.BundleID, a.Paths.TwinBundle, err)
	}
	return done, nil
}

// UnstageTwin removes the twin directory whole: the staged bundle, containerlab's working
// directory and twin.json. It runs after teardown, once containerlab has removed what it
// owned as root, so a remnant it still cannot remove is reported as
// cleanup.incomplete with the command that clears it rather than retried. The bundle store
// is a sibling and is never touched: bundles accumulate.
func (a *Activities) UnstageTwin(_ context.Context) (wire.UnstageResult, error) {
	path := a.Paths.Twin
	incomplete := func(format string, args ...any) (wire.UnstageResult, error) {
		return wire.UnstageResult{}, StepFailure(findings.StepUnstage, findings.RuleCleanupIncomplete, path,
			fmt.Sprintf(format, args...)+"; clear it with: sudo rm -rf "+path)
	}

	present, err := exists(path)
	if err != nil {
		return incomplete("twin directory %s may remain: %v", path, err)
	}
	if !present {
		return wire.UnstageResult{Path: path}, nil
	}
	if err := os.RemoveAll(path); err != nil {
		return incomplete("twin directory %s could not be removed: %v", path, err)
	}
	return wire.UnstageResult{Removed: true, Path: path}, nil
}
