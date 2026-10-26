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
		Short: "Check a branch's schema against the schema library the reader reads",
		Long: "Run the conformance half of `intent read` alone: the branch's schema holds every\n" +
			"kind and field the mapping reads, with the kind, cardinality, peer and choices\n" +
			"the pinned commit of opsmill/schema-library gives them. Every difference is named\n" +
			"in one report, each naming the commit. No intent is read and nothing is written,\n" +
			"so this is the cheap question to ask while setting a branch up.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runCheck(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to check (required)")
	return cmd
}

// runCheck is schema check as one request: the server asks the branch's schema, and the
// default branch's for the stage kind and its extension.
func runCheck(ctx context.Context, opts *options, f *checkFlags) error {
	a := given{}
	a.string("branch", f.branch)
	return send(ctx, opts, findings.OpSchemaCheck, a, nil, handlers{})
}
