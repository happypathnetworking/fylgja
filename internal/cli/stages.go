package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The noun stage (014, D-045): a proposed change's stages, the operator's marks between
// its two derived ends, the branch point and the head, listed and planned. The server
// dials Infrahub for both, and nothing else: no workflow service, no worker, no
// containerlab, no host budget.
func newStageCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stage",
		Short: "List and plan the stages of Infrahub's open proposed changes",
	}
	cmd.AddCommand(newStageListCmd(opts), newStagePlanCmd(opts))
	return cmd
}

type stageFlags struct {
	branch string
	// branchGiven is whether --branch was given at all, apart from its value: an explicit
	// empty one is a branch refused, not one left out (M4's --interval= precedent).
	branchGiven bool
	// scope is --scope as given, sent only when scopeGiven: not given, the server's default
	// stands, and an explicit empty one is the server's to refuse (017).
	scope      string
	scopeGiven bool
}

func newStageListCmd(opts *options) *cobra.Command {
	f := &stageFlags{}
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List every open proposed change's stages and the reference each resolves to",
		Long: "List the stages of Infrahub's open proposed changes, or of the one whose source\n" +
			"branch --branch names, in order: the branch point (the default branch at the\n" +
			"branch's branched_from), the marks by their at, and the head (the branch one\n" +
			"microsecond after its latest stamp or its latest intent event, whichever is later),\n" +
			"each with the branch and at it resolves to and where the at came from. The stage\n" +
			"the host's twin was built from is marked. Nothing is refused but a mark labelled\n" +
			"like a derived stage; a twin whose stage has since moved, a stage whose proposed\n" +
			"change is gone and a default branch written since the branch point are warnings.\n" +
			"The API's server reads them, and needs Infrahub and nothing else for it.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.branchGiven = cmd.Flags().Changed("branch")
			f.scopeGiven = cmd.Flags().Changed("scope")
			return runStageList(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "list the open proposed change of this source branch alone")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	return cmd
}

func newStagePlanCmd(opts *options) *cobra.Command {
	f := &stageFlags{}
	cmd := &cobra.Command{
		Use:   "plan",
		Short: "Read and compile each stage of a proposed change, and print the step between each pair",
		Long: "Read and compile each stage of the open proposed change whose source branch\n" +
			"--branch names, in order, on the pipeline intent read and twin compile run, and file\n" +
			"each bundle and its CTM in the store. Between each consecutive pair, print what\n" +
			"differs: nodes and links, then the configuration artifacts by checksum, never by\n" +
			"content. A stage that is refused, a stale one among them, is reported with its\n" +
			"reason and the plan goes on. The API's server reads, compiles and files them in its\n" +
			"bundle store, and needs Infrahub and the store for it: no workflow service, worker,\n" +
			"containerlab or host budget.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.branchGiven = cmd.Flags().Changed("branch")
			f.scopeGiven = cmd.Flags().Changed("scope")
			return runStagePlan(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "the source branch of the proposed change to plan (required)")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	return cmd
}

// stageArgs are --branch and --scope as given: each present whenever its flag was, an empty
// one included.
func stageArgs(f *stageFlags) given {
	a := given{}
	if f.branchGiven {
		a["branch"] = f.branch
	}
	a.scope(f.scope, f.scopeGiven)
	return a
}

// runStageList is stage list as one request.
func runStageList(ctx context.Context, opts *options, f *stageFlags) error {
	return send(ctx, opts, findings.OpStageList, stageArgs(f), nil, handlers{})
}

// runStagePlan is stage plan as one request: the server reads, compiles and files each
// stage of the proposed change, and prints each as it is known. --branch left out is the
// server's to refuse, before anything is dialled.
func runStagePlan(ctx context.Context, opts *options, f *stageFlags) error {
	return send(ctx, opts, findings.OpStagePlan, stageArgs(f), nil, handlers{})
}
