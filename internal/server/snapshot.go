package server

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// corruptEntry is snapshot.id.mismatch's message for a store entry that hashes to another id
// than the one it is filed under, or hashes to it and declares another, worded as the bundle
// store's: the snapshot cannot be done what the caller was doing to it.
func corruptEntry(m *snapshot.ErrIDMismatch, done string) string {
	return fmt.Sprintf("store entry %v, so snapshot %s cannot be %s", m, m.Want, done)
}

// snapshotFiles holds the files of op, a create or a step, to the one shape the API gives
// them (contracts/api.md, "018: snapshots" and "019: following removed"): one file, beside a
// --snapshot that is a path and under that path, and none otherwise. given is whether
// --snapshot was given, and arg its value. Any other is refused before anything is parsed,
// operation.failed, as twin compile's are. No client's command sends another, and the
// sentence names the command and nothing of a file.
func snapshotFiles(op string, subject *findings.Subject, given bool, arg string, files []api.File) error {
	file := given && !snapshot.IsID(arg)
	command := strings.ReplaceAll(op, ".", " ")
	switch {
	case len(files) > 1 || len(files) == 1 && !file:
		return fail(op, subject, "the request carries %s where %s takes a snapshot file beside --snapshot alone",
			plural(len(files), "file"), command)
	case file && len(files) == 0:
		return fail(op, subject, "the request carries no file where %s takes the snapshot file --snapshot names, "+
			"under that path", command)
	case file && files[0].Path != arg:
		return fail(op, subject, "the request carries its snapshot file under another path than --snapshot gives, where "+
			"%s takes a snapshot file beside --snapshot alone, under that path", command)
	}
	return nil
}

// resolveSnapshot resolves --snapshot to the stored snapshot a create builds from, at
// resolve, and returns it with its store path (R-12). An argument of a snapshot id's shape
// is looked up in the store: absent is snapshot.unknown, naming the store's directory, and a
// corrupt entry snapshot.id.mismatch at its path. Anything else is the path of the file the
// request carries, which snapshotFiles has held to that path: it is read by
// snapshot.Unmarshal's rules, each refusal under its own identifier; its CTM is held to the
// rules validation applies that read no package (validate.Intrinsic), each refusal at
// compile as the compile words it, with nothing filed; and it is filed under its id.
// The store keeps an entry already there, so what is returned is always the stored document,
// read back after the filing: the twin records the first take's observed_at (US3 scenario
// 8). Nothing here reaches Infrahub.
func resolveSnapshot(ctx context.Context, paths lab.Paths, op string, subject *findings.Subject, arg string,
	files []api.File) (*snapshot.Snapshot, string, error) {
	store := snapshot.NewDirStore(paths.Snapshots)
	refuse := func(rule, object, message string) error {
		var list findings.List
		list.AddStep(findings.Rejection, findings.StepResolve, rule, object, message)
		return finish(op, subject, list)
	}
	// What the store answered, as the create's document: done is what could not be done to
	// a corrupt entry.
	refused := func(id string, err error, done string) error {
		var mismatch *snapshot.ErrIDMismatch
		switch {
		case errors.Is(err, fs.ErrNotExist):
			return refuse(findings.RuleSnapshotUnknown, id, fmt.Sprintf("the store under %s holds no snapshot %s; a snapshot id "+
				"comes from a create, a dry run, a plan or intent read --out on this server", paths.Snapshots, id))
		case errors.As(err, &mismatch):
			return refuse(findings.RuleSnapshotIDMismatch, mismatch.Path, corruptEntry(mismatch, done))
		}
		return failAt(op, subject, findings.StepResolve, paths.Snapshots, "%v", err)
	}

	id := arg
	if !snapshot.IsID(arg) {
		s, err := snapshot.Unmarshal(files[0].Data)
		if err != nil {
			if list, ok := snapshotRefusal(arg, err); ok {
				return nil, "", finish(op, subject, list.AtStep(findings.StepResolve))
			}
			// A file that is not JSON was never validated: nothing to report findings about.
			return nil, "", failAt(op, subject, findings.StepResolve, arg, "%v", err)
		}
		// The CTM's own rules before the filing: a file they refuse is filed nowhere, and is
		// refused as the compile would refuse it, at compile. What needs the packages is the
		// compile's, by which time the file is filed, as a read's take is.
		if list := validate.Intrinsic(s.CTM); list.Rejected() {
			return nil, "", finish(op, subject, list.AtStep(findings.StepCompile))
		}
		if _, err := store.Put(ctx, s); err != nil {
			return nil, "", refused(s.ID, err, "filed")
		}
		id = s.ID
	}
	s, err := store.Fetch(ctx, id)
	if err != nil {
		return nil, "", refused(id, err, "read")
	}
	return s, store.Path(id), nil
}

// snapshotRefusal is the refusal snapshot.Unmarshal returned for the file at path, under its
// own rule (R-03), with no step, which the caller places: snapshot.version.unsupported and
// snapshot.id.mismatch at the file, snapshot.invalid at the field (the file when the
// document itself is at fault), and the inner CTM's faults under the rules a bare CTM's
// take, ctm.version.unsupported at the file and data.required.missing at the field prefixed
// ctm. ok is false for an error that refuses nothing: a document that is not JSON, which the
// caller reports as operation.failed, since nothing was validated.
func snapshotRefusal(path string, err error) (list findings.List, ok bool) {
	var (
		version   *snapshot.VersionError
		invalid   *snapshot.InvalidError
		mismatch  *snapshot.IDMismatchError
		ctmVer    *ctm.VersionError
		ctmAbsent *ctm.MissingError
	)
	switch {
	case errors.As(err, &version):
		list.Add(findings.Rejection, findings.RuleSnapshotVersionUnsupported, path, version.Error())
	case errors.As(err, &invalid):
		object := invalid.Field
		if object == "" {
			object = path
		}
		list.Add(findings.Rejection, findings.RuleSnapshotInvalid, object, invalid.Message)
	case errors.As(err, &mismatch):
		list.Add(findings.Rejection, findings.RuleSnapshotIDMismatch, path, path+" "+mismatch.Error())
	case errors.As(err, &ctmVer):
		list.Add(findings.Rejection, findings.RuleCTMVersionUnsupported, path, ctmVersionMessage(ctmVer))
	case errors.As(err, &ctmAbsent):
		list.Add(findings.Rejection, findings.RuleRequiredMissing, ctmAbsent.Field, ctmAbsent.Message)
	default:
		return nil, false
	}
	return list, true
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
