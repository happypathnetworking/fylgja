package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// rehearseFlags are twin rehearse's flags (015): the proposed change's source branch, and
// whether --branch was given at all, apart from its value: an explicit empty one is a
// branch refused by the server, not one left out (M4's --interval= precedent).
type rehearseFlags struct {
	branch      string
	branchGiven bool
	// scope is --scope as given, sent only when scopeGiven: not given, the server's default
	// stands, and an explicit empty one is the server's to refuse (017).
	scope      string
	scopeGiven bool
}

func newTwinRehearseCmd(opts *options) *cobra.Command {
	f := &rehearseFlags{}
	cmd := &cobra.Command{
		Use:   "rehearse",
		Short: "Rehearse a proposed change's stages on a twin, stopping at the first that fails",
		Long: "Rehearse the open proposed change whose source branch --branch names on a twin of its\n" +
			"own. The API's server resolves, reads, compiles and files every stage first, as stage\n" +
			"plan does, so a stage that cannot be built refuses the rehearsal before anything is\n" +
			"booted; a branch point refused because the default branch holds no network is passed\n" +
			"over. Then one run with the fixed identity fylgja-rehearse creates the twin from the\n" +
			"first stage that compiled (the baseline) and verifies it, steps it to each later stage\n" +
			"in order, restarting what the step needs, waits for it to settle and verifies it, stops\n" +
			"at the first stage that diverges or whose verify finds something the baseline's did not,\n" +
			"and destroys the twin whatever happened, within a deadline the stages' budgets give.\n" +
			"The report has one line per stage and, on a failure, the commands that reproduce it by\n" +
			"hand. Interrupt once to cancel the run and wait for its destroy; a second time to stop\n" +
			"waiting. --markdown prints the report as the comment a check posts.",
		Args: cobra.NoArgs,
		PreRunE: func(cmd *cobra.Command, _ []string) error {
			// --json is the root's own flag, which this command reaches only once it hangs
			// under the root: the group is marked here, before cobra validates it.
			cmd.MarkFlagsMutuallyExclusive("markdown", "json")
			return nil
		},
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.branchGiven = cmd.Flags().Changed("branch")
			f.scopeGiven = cmd.Flags().Changed("scope")
			return runTwinRehearse(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "the source branch of the proposed change to rehearse (required)")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	cmd.Flags().BoolVar(&opts.markdown, "markdown", false,
		"emit the report as markdown on stdout and nothing else there, the progress and the findings on stderr")
	return cmd
}

// runTwinRehearse is twin rehearse as one request: the server plans the stages, checks the
// host, starts the run and follows it to its destroy, and its answer is printed as it comes.
// --branch left out is refused here, with no request (contracts/rehearse-command.md, "The
// command"), in the words the server's own guard uses; every other guard, an empty
// --branch= among them, is the server's.
func runTwinRehearse(ctx context.Context, opts *options, f *rehearseFlags) error {
	if !f.branchGiven && f.branch == "" {
		return fail(findings.OpTwinRehearse, nil, "--branch is required")
	}
	a := given{"branch": f.branch}
	a.scope(f.scope, f.scopeGiven)
	return send(ctx, opts, findings.OpTwinRehearse, a, nil, handlers{})
}
