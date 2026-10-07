package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

type provisionFlags struct {
	dryRun bool
}

func newTwinProvisionCmd(opts *options) *cobra.Command {
	f := &provisionFlags{}
	cmd := &cobra.Command{
		Use:   "provision <bundle-dir>",
		Short: "Provision one twin from a bundle that was already compiled",
		Long: "Verify a bundle directory — from twin compile, the bundle store or a fixture — file\n" +
			"it in the bundle store under its identity, and provision it through the lab host's\n" +
			"worker from the host check onward, exactly as twin create does. No read takes\n" +
			"place, so the twin records its read time as unknown. Interrupt once to cancel the\n" +
			"run and wait for its cleanup; a second time to stop waiting.",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return runTwinProvision(cmd.Context(), opts, f, args[0])
		},
	}
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"verify, file the bundle and check the host; start no run")
	return cmd
}

// runTwinProvision sends the bundle directory's regular files, each under its path inside
// it, and the directory as given, which every sentence of the server's names. A directory
// that cannot be read is the operation failing at step verify, worded as
// bundle.Verify words it, as M12's first step refused it.
func runTwinProvision(ctx context.Context, opts *options, f *provisionFlags, dir string) error {
	const op = findings.OpTwinProvision
	files, err := readBundle(dir)
	if err != nil {
		return failAt(op, &findings.Subject{Bundle: dir}, findings.StepVerify, dir, "%v", err)
	}
	a := given{"bundle": dir}
	a.bool("dry_run", f.dryRun)
	return send(ctx, opts, op, a, files, handlers{})
}
