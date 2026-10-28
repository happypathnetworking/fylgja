package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The default a client's help names, which is the core's: verify's DefaultBudget. The
// client does not link the package, so it is written here, and a test holds it to the
// core's own (TestFlagDefaultsAreTheCoresOwn).
const defaultBudget = "2m0s"

type createFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// by the server to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent, a
	// flag twin create had until 019).
	stageGiven bool
	dryRun     bool
	// scope is --scope as given, sent only when scopeGiven: not given, the server's default
	// stands, and an explicit empty one is the server's to refuse (017).
	scope      string
	scopeGiven bool
	// snapshot is --snapshot as given (018): a snapshot id, sent as it is, or the path of a
	// file the client reads and sends. snapshotGiven is whether it was given at all.
	snapshot      string
	snapshotGiven bool
}

func newTwinCreateCmd(opts *options) *cobra.Command {
	f := &createFlags{}
	cmd := &cobra.Command{
		Use:   "create",
		Short: "Provision one twin from a branch, a stage or a snapshot",
		Long: "Provision one twin from an Infrahub branch, a proposed change's stage or a snapshot.\n" +
			"The API's server resolves the stage, reads the branch, takes the snapshot of what it\n" +
			"read, compiles it and files the snapshot and the bundle, before any run. --snapshot\n" +
			"<id|file> builds the twin from a snapshot instead, one the server's store holds by its\n" +
			"id or a snapshot file sent from here, which the server files: no branch is read. Then\n" +
			"one run with the fixed identity fylgja-provision, from the host check on, provisions\n" +
			"the twin through the lab host's worker. Prints a line as each step begins and ends,\n" +
			"and blocks until every node answers its readiness probe or the run has cleaned up\n" +
			"after itself. Interrupt once to cancel the run and wait for its cleanup; a second time\n" +
			"to stop waiting.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.stageGiven = cmd.Flags().Changed("stage")
			f.scopeGiven = cmd.Flags().Changed("scope")
			f.snapshotGiven = cmd.Flags().Changed("snapshot")
			return runCreate(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to read (this, --stage or --snapshot is required)")
	cmd.Flags().StringVar(&f.at, "at", "",
		"point in time to read at, passed verbatim; omitted entirely when not given")
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"stage to build the twin from, <branch>/<label>: the pinned branch and at a proposed change's stage resolves to")
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"read, take and file the snapshot, compile and file the bundle, and check the host; start no run "+
			"(with --snapshot, nothing is read)")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	cmd.Flags().StringVar(&f.snapshot, "snapshot", "",
		"snapshot to build the twin from, <id|file>: a snapshot id (64 lowercase hex characters) the server's store holds, "+
			"or a snapshot file, which is read here and sent; no branch is read")
	return cmd
}

// fromStage is whether the create names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

// fromSnapshot is whether the create names a snapshot, as fromStage is whether it names a
// stage.
func (f *createFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runCreate is twin create as one request: the flags given, and the server's answer printed
// as it comes. Every guard, the stage's and the snapshot's among them, is the server's. A --snapshot that is no id is a file, read here and sent as the
// request's one file under that path; one the client cannot read is its own failure,
// before any connection (R-07). The file is read only when no flag beside --snapshot would
// be refused by the snapshot's guards, so those refusals come first, whatever the file, as
// twin compile holds its read back for the server's; an explicit empty --snapshot= with
// none beside it names no file, and is the client's own refusal.
func runCreate(ctx context.Context, opts *options, f *createFlags) error {
	a := given{}
	a.string("branch", f.branch)
	a.string("at", f.at)
	if f.fromStage() {
		a["stage"] = f.stage
	}
	a.bool("dry_run", f.dryRun)
	a.scope(f.scope, f.scopeGiven)
	var files []api.File
	if f.fromSnapshot() {
		a["snapshot"] = f.snapshot
		if !f.snapshotConflicts() {
			var err error
			subject := &findings.Subject{Branch: f.branch, At: f.at, Snapshot: f.snapshot}
			if files, err = snapshotSent(findings.OpTwinCreate, subject, f.snapshot); err != nil {
				return err
			}
		}
	}
	return send(ctx, opts, findings.OpTwinCreate, a, files, handlers{})
}

// snapshotSent is the request's files for a --snapshot given as arg, which twin create and
// twin step send alike (018; 019, research R-04): none for a snapshot id, which is sent as it
// is, and otherwise the file at that path, read here, under it. A file the client cannot
// read is its own failure, before any connection, as an explicit empty --snapshot= is, which
// names no file.
func snapshotSent(op string, subject *findings.Subject, arg string) ([]api.File, error) {
	if isSnapshotID(arg) {
		return nil, nil
	}
	if arg == "" {
		return nil, fail(op, subject, "--snapshot= is empty; give a snapshot id or the path of a snapshot file")
	}
	file, err := readSnapshot(arg)
	if err != nil {
		return nil, fail(op, subject, "%v", err)
	}
	return []api.File{file}, nil
}

// snapshotConflicts is whether a flag is given beside --snapshot that the server's snapshot
// guards refuse: --branch, --stage, --at or --scope, as the server's snapshotGuards reads
// them. The request then carries no file, and the guard answers.
func (f *createFlags) snapshotConflicts() bool {
	return f.branch != "" || f.fromStage() || f.at != "" || f.scopeGiven
}

// isSnapshotID is whether --snapshot's value is a snapshot id, 64 lowercase hex characters,
// and not a file's path: the core's snapshot.IsID, written here because the client links
// nothing of the core's but the findings, and held to it by a test
// (TestSnapshotIDShapeIsTheCoresOwn).
func isSnapshotID(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, r := range s {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	return true
}
