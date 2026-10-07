package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newSchemaCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "schema",
		Short: "Inspect the intent schema on a branch",
	}
	cmd.AddCommand(newSchemaCheckCmd(opts))
	return cmd
}

// checkFlags carries no `at`: the schema endpoint accepts
// only `branch` and `namespaces` and ignores an `at` entirely, so a flag
// here would promise a pinned answer nothing can give.
type checkFlags struct {
	branch string
}

func newSchemaCheckCmd(opts *options) *cobra.Command {
	f := &checkFlags{}
	cmd := &cobra.Command{
		Use:   "check",
		Short: "Check a branch's schema against Fylgja's contract",
		Long: "Run the conformance half of `intent read` alone: the branch declares the\n" +
			"expected contract version, and every Fylgja generic is implemented by at least\n" +
			"one concrete kind. No intent is read and nothing is written, so this is the\n" +
			"cheap question to ask while setting a branch up.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runCheck(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to check (required)")
	return cmd
}

// runCheck is schema check as one request: the server asks the branch's schema, and the
// default branch's for the waypoint kind.
func runCheck(ctx context.Context, opts *options, f *checkFlags) error {
	a := given{}
	a.string("branch", f.branch)
	return send(ctx, opts, findings.OpSchemaCheck, a, nil, handlers{})
}
