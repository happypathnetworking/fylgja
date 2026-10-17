package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

type stepFlags struct {
	// stage is --stage as given, <branch>/<label>: the target, in place of the next stage of
	// the twin's proposed change.
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven   bool
	allowRestart bool
	dryRun       bool
	// wait is --wait as given: the budget of the step's wait after its record.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule).
	waitGiven bool
}

func newTwinStepCmd(opts *options) *cobra.Command {
	f := &stepFlags{}
	cmd := &cobra.Command{
		Use:   "step",
		Short: "Take the stage twin to another stage of its proposed change, without a rebuild",
		Long: "Take the running twin, built from a stage, to another stage of its proposed change:\n" +
			"the next one, or the one --stage names. The API's server resolves, reads, compiles and\n" +
			"files the target; the step between the two bundles is printed, the host is checked for\n" +
			"the twin after the step, and containerlab's own plan for the lab is read. Then one run\n" +
			"with the fixed identity fylgja-step stages the target, lets containerlab reconcile the\n" +
			"lab, waits for every node it restarted, recreated or created, pushes every node whose\n" +
			"configuration changed by replace, and records the twin. Nothing is torn down: a step\n" +
			"that fails or is cancelled after its stage leaves the twin up and diverged (exit 4),\n" +
			"and only fylgja twin destroy clears it. A plan that restarts or recreates a node needs\n" +
			"--allow-restart.\n" +
			"After the record the run reads the twin against the target until it conforms, at most\n" +
			"--wait (default " + defaultBudget + "), and records how that ended; the step's outcome does not\n" +
			"depend on it.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.stageGiven = cmd.Flags().Changed("stage")
			f.waitGiven = cmd.Flags().Changed("wait")
			return runTwinStep(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"the stage to step to, <branch>/<label>, of the twin's own proposed change; the next one when left out")
	cmd.Flags().BoolVar(&f.allowRestart, "allow-restart", false,
		"proceed when containerlab's plan restarts or recreates a node, which loses its running state until the step pushes it again")
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"resolve, read, compile and file the target, check the host and read containerlab's plan; start no run")
	cmd.Flags().StringVar(&f.wait, "wait", "",
		"after the record, read the twin until it conforms, at most this long (default "+defaultBudget+"; 0 reads once)")
	return cmd
}

// runTwinStep is twin step as one request; the server resolves, reads, compiles and files
// the target, checks its host, reads containerlab's plan and starts the run.
func runTwinStep(ctx context.Context, opts *options, f *stepFlags) error {
	a := given{}
	if f.stageGiven || f.stage != "" {
		a["stage"] = f.stage
	}
	a.bool("allow_restart", f.allowRestart)
	a.bool("dry_run", f.dryRun)
	if f.waitGiven {
		a["wait"] = f.wait
	}
	return send(ctx, opts, findings.OpTwinStep, a, nil, handlers{})
}
