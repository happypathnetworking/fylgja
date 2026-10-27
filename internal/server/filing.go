package server

import (
	"context"
	"errors"
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// fileCompiled files a compiled bundle in the store under dir, as a run's compile step
// files it: what the create, its dry run and stage plan leave behind to inspect. Moved
// here from the dry run so they file alike. No CTM is filed beside it: the sidecar is
// retired (018), and the input is the snapshot, filed by takeSnapshot before the compile.
//
// A store already holding other bytes under the id is refused as bundle.id.mismatch at
// step compile, the one finding it returns; any other failure is an error the caller
// reports as operation.failed.
func fileCompiled(ctx context.Context, dir string, files map[string][]byte, id string) (bundle.Store, findings.List, error) {
	var list findings.List
	store := bundle.NewDirStore(dir)
	stored, err := bundle.PutFiles(ctx, store, files, dir)
	var mismatch *bundle.ErrIDMismatch
	switch {
	case errors.As(err, &mismatch):
		list.AddStep(findings.Rejection, findings.StepCompile, findings.RuleBundleIDMismatch, mismatch.Path,
			provision.StoreMismatchMessage(mismatch, id))
		return store, list, nil
	case err != nil:
		return store, nil, fmt.Errorf("filing bundle %s: %v", id, err)
	case stored != id:
		return store, nil, fmt.Errorf("the written bundle hashes to %s, but compiled to %s", stored, id)
	}
	return store, nil, nil
}
