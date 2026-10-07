package server

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// fileCompiled files a compiled bundle in the store under dir, and the CTM it was compiled
// from beside it, as a run's compile step files them: what the dry run and waypoint plan
// leave behind to inspect. Moved here from the dry run so the two file alike.
//
// A store already holding other bytes under the id is refused as bundle.id.mismatch at
// step compile, the one finding it returns; any other failure is an error the caller
// reports as operation.failed.
func fileCompiled(ctx context.Context, dir string, files map[string][]byte, id string, snapshot *ctm.CTM) (bundle.Store, findings.List, error) {
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
	if err := keepCTM(ctx, store, dir, id, snapshot); err != nil {
		return store, nil, fmt.Errorf("keeping the CTM beside bundle %s: %v", id, err)
	}
	return store, nil, nil
}

// keepCTM files the read's CTM beside bundle id through the store, overwriting an earlier
// read of the same intent, as a run's compile step does.
func keepCTM(ctx context.Context, store bundle.Store, scratch, id string, snapshot *ctm.CTM) error {
	dir, err := os.MkdirTemp(scratch, ".fylgja-ctm-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.RemoveAll(dir) }()
	path := filepath.Join(dir, "ctm.json")
	if err := writeCTM(snapshot, path); err != nil {
		return err
	}
	return store.PutCTM(ctx, id, path)
}
