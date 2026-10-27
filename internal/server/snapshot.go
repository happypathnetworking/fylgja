package server

import (
	"context"
	"errors"
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// takeSnapshot wraps a CTM a read produced as a snapshot and files it in the store under
// the state root, returning the snapshot and its store path (data-model §4; R-05). Where
// the server takes a snapshot is here alone, so the create, its dry run, intent read and
// the stages' pipeline take and file alike (D-011's one code path). Called after a clean
// read and before the compile: a refused read files nothing, and a compile refused after
// it leaves the snapshot filed, since its CTM validated.
//
// The store never overwrites: a second take of the same intent keeps the first take's
// entry, and its observed_at, and returns the snapshot as taken now. An entry already
// under the id that hashes to another is snapshot.id.mismatch at step, naming the store
// path and both ids, the one finding it returns, with no snapshot, since none was filed;
// any other failure is an error the caller reports as operation.failed.
func takeSnapshot(ctx context.Context, paths lab.Paths, step string, c *ctm.CTM) (*snapshot.Snapshot, string, findings.List, error) {
	s := snapshot.Take(c)
	store := snapshot.NewDirStore(paths.Snapshots)
	_, err := store.Put(ctx, s)
	var mismatch *snapshot.ErrIDMismatch
	switch {
	case errors.As(err, &mismatch):
		var list findings.List
		list.AddStep(findings.Rejection, step, findings.RuleSnapshotIDMismatch, mismatch.Path,
			fmt.Sprintf("store entry %s hashes to %s, not %s, so snapshot %s cannot be filed", mismatch.Path, mismatch.Got,
				mismatch.Want, s.ID))
		return nil, "", list, nil
	case err != nil:
		return nil, "", nil, fmt.Errorf("filing snapshot %s: %v", s.ID, err)
	}
	return s, store.Path(s.ID), nil, nil
}

// snapshotStoredLine is the line a create and its dry run print for the snapshot they
// filed, above the bundle's (R-09).
func snapshotStoredLine(id, path string) string {
	return fmt.Sprintf("snapshot_id %s  stored: %s", id, path)
}

// bundleStoredLine is the line a create and a dry run print for the bundle they filed,
// below the snapshot's, worded beside it.
func bundleStoredLine(id, path string) string {
	return fmt.Sprintf("bundle_id %s  stored: %s", id, path)
}
