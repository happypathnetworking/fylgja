package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

type stepFlags struct {
	// snapshot is --snapshot as given (019): the target, a snapshot id, sent as it is, or the
	// path of a file the client reads and sends, as twin create's is. snapshotGiven is
	// whether it was given at all. It is the step's one target (020): --stage and --probes
	// are the orchestrator's fylgja-cli's, and no flags of this command.
	snapshot      string
	snapshotGiven bool
	allowRestart  bool
	dryRun        bool
	// wait is --wait as given: the budget of the step's wait after its record.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule, a flag twin create had until 019).
	waitGiven bool
	// detach is --detach (020): the answer ends at the run's identity.
	detach bool
}

func newTwinStepCmd(opts *options) *cobra.Command {
	f := &stepFlags{}
	cmd := &cobra.Command{
		Use:   "step",
		Short: "Take the running twin to a snapshot, without a rebuild",
		Long: "Take the running twin to the snapshot --snapshot <id|file> names, a snapshot of any\n" +
			"branch: one the API's server's store holds by its id, or a snapshot file sent from\n" +
			"here, which it files. The server compiles it and files the bundle; no source of truth\n" +
			"is read. The step between the two bundles is printed, the host is checked for the twin\n" +
			"after the step, and containerlab's own plan for the lab is read. Then one run with the\n" +
			"fixed identity fylgja-step stages the target, lets containerlab reconcile the lab,\n" +
			"waits for every node it restarted, recreated or created, pushes every node whose\n" +
			"configuration changed by replace, and records the twin. Nothing is torn down: a step\n" +
			"that fails or is cancelled after its stage leaves the twin up and diverged (exit 4),\n" +
			"and only fylgja twin destroy clears it. A plan that restarts or recreates a node needs\n" +
			"--allow-restart. After the record the run reads the twin against the target until it\n" +
			"conforms, at most --wait (default " + defaultBudget + "), and records how that ended; the step's\n" +
			"outcome does not depend on it. --detach ends the command once the run has started, at\n" +
			"its identity. A step to a stage is fylgja-cli twin step's, the orchestrator's, which\n" +
			"reads the stage and sends this server its snapshot.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.snapshotGiven = cmd.Flags().Changed("snapshot")
			f.waitGiven = cmd.Flags().Changed("wait")
			return runTwinStep(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.snapshot, "snapshot", "",
		"the snapshot to step to, <id|file>, a snapshot of any branch (required): a snapshot id (64 lowercase hex "+
			"characters) the server's store holds, or a snapshot file, which is read here and sent")
	cmd.Flags().BoolVar(&f.allowRestart, "allow-restart", false,
		"proceed when containerlab's plan restarts or recreates a node, which loses its running state until the step pushes it again")
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"file a snapshot file sent, compile and file its bundle, check the host and read containerlab's plan; start no run")
	cmd.Flags().StringVar(&f.wait, "wait", "",
		"after the record, read the twin until it conforms, at most this long (default "+defaultBudget+"; 0 reads once)")
	cmd.Flags().BoolVar(&f.detach, "detach", false, detachUsage+"; refused beside --dry-run")
	return cmd
}

// runTwinStep is twin step as one request; the server resolves the snapshot given, compiles
// it and files its bundle, checks its host, reads containerlab's plan and starts the run. A
// --snapshot is sent as twin create sends one (snapshotSent; 019, research R-04); left out,
// the server refuses the step step.target.unknown (020).
func runTwinStep(ctx context.Context, opts *options, f *stepFlags) error {
	a := given{}
	a.bool("allow_restart", f.allowRestart)
	a.bool("dry_run", f.dryRun)
	a.bool("detach", f.detach)
	if f.waitGiven {
		a["wait"] = f.wait
	}
	subject := &findings.Subject{Snapshot: f.snapshot}
	var files []api.File
	if f.snapshotGiven || f.snapshot != "" {
		a["snapshot"] = f.snapshot
		var err error
		if files, err = snapshotSent(findings.OpTwinStep, subject, f.snapshot); err != nil {
			return err
		}
	}
	return send(ctx, opts, findings.OpTwinStep, a, files, handlers{})
}
