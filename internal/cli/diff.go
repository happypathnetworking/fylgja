package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// diffFlags are fylgja twin diff's two snapshots (020, R-05), each a snapshot id or the path
// of a snapshot file.
type diffFlags struct {
	from, to string
}

func newTwinDiffCmd(opts *options) *cobra.Command {
	f := &diffFlags{}
	cmd := &cobra.Command{
		Use:   "diff",
		Short: "Print the step between two snapshots, building nothing",
		Long: "Compile two snapshots, each a snapshot id the server's store holds or a snapshot\n" +
			"file, and print the step between their bundles: the nodes and links added, removed\n" +
			"and changed, and the artifacts moved, as twin step --dry-run prints it. The server\n" +
			"files both snapshots and both bundles and nothing else: no twin is read or touched\n" +
			"and no run is started. One snapshot against itself is unchanged.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runDiff(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.from, "from", "", "the snapshot the step goes from: a snapshot id or a snapshot file (required)")
	cmd.Flags().StringVar(&f.to, "to", "", "the snapshot the step goes to: a snapshot id or a snapshot file (required)")
	return cmd
}

// runDiff sends the two snapshots, each file read here and sent under its path, once for a
// path both flags name; an id is sent as it is. The files are read only once both flags are
// given, so the server's two "is required" refusals keep their order, as twin compile's do;
// a file that cannot be read is worded as twin compile words it, before any connection.
func runDiff(ctx context.Context, opts *options, f *diffFlags) error {
	a := given{}
	a.string("from", f.from)
	a.string("to", f.to)
	var files []api.File
	if f.from != "" && f.to != "" {
		for _, arg := range []string{f.from, f.to} {
			if isSnapshotID(arg) || len(files) == 1 && files[0].Path == arg {
				continue
			}
			file, err := readSnapshot(arg)
			if err != nil {
				return fail(findings.OpTwinDiff, nil, "%v", err)
			}
			files = append(files, file)
		}
	}
	return send(ctx, opts, findings.OpTwinDiff, a, files, handlers{})
}
