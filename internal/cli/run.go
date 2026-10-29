package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// runFlags are a run's identity as fylgja run read and fylgja run interrupt name it (020,
// R-04): the workflow, and the run, its latest when left out.
type runFlags struct {
	workflow string
	run      string
}

func newRunCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "run",
		Short: "Read or interrupt a run by its identity",
	}
	cmd.AddCommand(newRunReadCmd(opts), newRunInterruptCmd(opts))
	return cmd
}

// identityFlags binds --workflow and --run to f.
func identityFlags(cmd *cobra.Command, f *runFlags) {
	cmd.Flags().StringVar(&f.workflow, "workflow", "",
		"the run's workflow: fylgja-provision, fylgja-step or fylgja-destroy")
	cmd.Flags().StringVar(&f.run, "run", "", "the run's id (default: the workflow's latest run)")
}

func newRunReadCmd(opts *options) *cobra.Command {
	f := &runFlags{}
	cmd := &cobra.Command{
		Use:   "read",
		Short: "Print a run's progress so far and, once it has ended, its result",
		Long: "Read a run by its identity from the workflow service's history: its state, a line for\n" +
			"each step so far, as twin create, twin step or twin destroy printed them while\n" +
			"following it, and, once the run has ended, the result those commands ended with,\n" +
			"which --json prints as the document. A run still running ends with no result, exit 0.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runRunRead(cmd.Context(), opts, f)
		},
	}
	identityFlags(cmd, f)
	return cmd
}

func newRunInterruptCmd(opts *options) *cobra.Command {
	f := &runFlags{}
	cmd := &cobra.Command{
		Use:   "interrupt",
		Short: "Ask a running run to cancel, as a first interrupt of its command does",
		Long: "Ask a run, named by its identity, to cancel, as the first interrupt of the command\n" +
			"that started it does: it cleans up and closes, and fylgja run read says how. Nothing\n" +
			"is waited for. A run that has already closed is refused.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return runRunInterrupt(cmd.Context(), opts, f)
		},
	}
	identityFlags(cmd, f)
	return cmd
}

// runRunRead is fylgja run read as one request, its out lines printed as a followed run's
// are; the workflow is sent as given, an empty one the server's to refuse, and the run only
// when given.
func runRunRead(ctx context.Context, opts *options, f *runFlags) error {
	return send(ctx, opts, findings.OpRunRead, f.args(), nil, handlers{})
}

// runRunInterrupt is fylgja run interrupt as one request.
func runRunInterrupt(ctx context.Context, opts *options, f *runFlags) error {
	return send(ctx, opts, findings.OpRunInterrupt, f.args(), nil, handlers{})
}

func (f *runFlags) args() given {
	a := given{"workflow_id": f.workflow}
	a.string("run_id", f.run)
	return a
}
