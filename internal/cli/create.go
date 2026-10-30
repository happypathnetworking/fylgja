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
	dryRun bool
	// snapshot is --snapshot as given (018): a snapshot id, sent as it is, or the path of a
	// file the client reads and sends. snapshotGiven is whether it was given at all. It is the
	// create's one source (020): --branch, --at, --stage, --scope and --probes are the
	// orchestrator's fylgja-cli's, and no flags of this command.
	snapshot      string
	snapshotGiven bool
	// detach is --detach (020): the answer ends at the run's identity.
	detach bool
}

func newTwinCreateCmd(opts *options) *cobra.Command {
	f := &createFlags{}
	cmd := &cobra.Command{
		Use:   "create",
		Short: "Provision one twin from a snapshot",
		Long: "Provision one twin from a snapshot: --snapshot <id|file> names one the API's server's\n" +
			"store holds by its id, or a snapshot file sent from here, which the server files. The\n" +
			"server compiles it and files the bundle, before any run; no source of truth is read.\n" +
			"Then one run with the fixed identity fylgja-provision, from the host check on,\n" +
			"provisions the twin through the lab host's worker. Prints a line as each step begins\n" +
			"and ends, and blocks until every node answers its readiness probe or the run has\n" +
			"cleaned up after itself. Interrupt once to cancel the run and wait for its cleanup; a\n" +
			"second time to stop waiting. --detach ends the command once the run has started, at\n" +
			"its identity. A twin of a branch or a stage is fylgja-cli twin create's, the\n" +
			"orchestrator's, which reads it and sends this server its snapshot.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.snapshotGiven = cmd.Flags().Changed("snapshot")
			return runCreate(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"file a snapshot file sent, compile and file the bundle, and check the host; start no run")
	cmd.Flags().StringVar(&f.snapshot, "snapshot", "",
		"snapshot to build the twin from, <id|file> (required): a snapshot id (64 lowercase hex characters) the "+
			"server's store holds, or a snapshot file, which is read here and sent")
	cmd.Flags().BoolVar(&f.detach, "detach", false, detachUsage+"; refused beside --dry-run")
	return cmd
}

// fromSnapshot is whether the create names a snapshot: --snapshot given, whatever its value,
// or a value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runCreate is twin create as one request: the flags given, and the server's answer printed
// as it comes. Every guard is the server's, --snapshot left out among them (020). A
// --snapshot that is no id is a file, read here and sent as the request's one file under
// that path; one the client cannot read is its own failure, before any connection (R-07),
// and an explicit empty --snapshot= names no file, and is the client's own refusal.
func runCreate(ctx context.Context, opts *options, f *createFlags) error {
	a := given{}
	a.bool("dry_run", f.dryRun)
	a.bool("detach", f.detach)
	subject := &findings.Subject{Snapshot: f.snapshot}
	var files []api.File
	if f.fromSnapshot() {
		a["snapshot"] = f.snapshot
		var err error
		if files, err = snapshotSent(findings.OpTwinCreate, subject, f.snapshot); err != nil {
			return err
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
