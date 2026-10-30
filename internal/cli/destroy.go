package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

type destroyFlags struct {
	// detach is --detach (020): the answer ends at the destroy run's identity.
	detach bool
}

func newTwinDestroyCmd(opts *options) *cobra.Command {
	f := &destroyFlags{}
	cmd := &cobra.Command{
		Use:   "destroy",
		Short: "Tear down the twin and remove its twin directory",
		Long: "Tear down lab fylgja and remove the twin directory through the lab host's worker,\n" +
			"as one run with the fixed identity fylgja-destroy. A provisioning run in flight is\n" +
			"cancelled and its cleanup waited for first; a step run in flight is then cancelled and\n" +
			"its record waited for, and the diverged record goes with the twin directory; a destroy\n" +
			"already running is attached to. Succeeds whether or not a lab or a twin directory is\n" +
			"there, and never touches the bundle store. No arguments: there is one twin. --detach\n" +
			"ends the command once the destroy run has started, at its identity, after what it\n" +
			"cancels first has closed.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runDestroy(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().BoolVar(&f.detach, "detach", false, detachUsage)
	return cmd
}

// runDestroy is twin destroy as one request, followed to the destroy run's end, or to its
// start under --detach. It takes no interrupt, as M12's took none.
func runDestroy(ctx context.Context, opts *options, f *destroyFlags) error {
	a := given{}
	a.bool("detach", f.detach)
	return send(ctx, opts, findings.OpTwinDestroy, a, nil, handlers{})
}
