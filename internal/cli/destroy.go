package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newTwinDestroyCmd(opts *options) *cobra.Command {
	return &cobra.Command{
		Use:   "destroy",
		Short: "Tear down the twin and remove its twin directory",
		Long: "Tear down lab fylgja and remove the twin directory through the lab host's worker,\n" +
			"as one run with the fixed identity fylgja-destroy. Following stops first, and a check\n" +
			"in flight is cancelled and its cleanup waited for. A provisioning run in flight is\n" +
			"cancelled and its cleanup waited for next, and following that run began is stopped\n" +
			"too; a step run in flight is then cancelled and its record waited for, and the\n" +
			"diverged record goes with the twin directory; a destroy already running is attached\n" +
			"to. Succeeds whether or not a lab or a twin directory is there, and never touches the\n" +
			"bundle store. No arguments: there is one twin.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runDestroy(cmd.Context(), opts)
		},
	}
}

// runDestroy is twin destroy as one request, followed to the destroy run's end. It takes no
// interrupt, as M12's took none.
func runDestroy(ctx context.Context, opts *options) error {
	return send(ctx, opts, findings.OpTwinDestroy, nil, nil, handlers{})
}
