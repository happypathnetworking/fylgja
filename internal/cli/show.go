package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newTwinShowCmd(opts *options) *cobra.Command {
	return &cobra.Command{
		Use:   "show",
		Short: "Say what twin there is and what it was built from",
		Long: "Report the twin from containerlab, the twin directory and twin.json, then from the\n" +
			"workflow service any run in flight with its step. The API's server reports it from the\n" +
			"lab host, needs no worker, and changes nothing. When the workflow service does not\n" +
			"answer, the host and the record are still reported. No arguments: there is one twin.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runShow(cmd.Context(), opts)
		},
	}
}

// runShow is twin show as one request: the server inspects its host and asks the workflow
// service, best-effort (D-041).
func runShow(ctx context.Context, opts *options) error {
	return send(ctx, opts, findings.OpTwinShow, nil, nil, handlers{})
}
