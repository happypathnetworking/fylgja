package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

type stepFlags struct {
	// stage is --stage as given, <branch>/<label>: the target, in place of the next stage of
	// the twin's proposed change.
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit empty
	// one is a reference refused, not one left out (M4's --interval= precedent, a flag twin
	// create had until 019).
	stageGiven bool
	// snapshot is --snapshot as given (019): the target, a snapshot id, sent as it is, or the
	// path of a file the client reads and sends, as twin create's is. snapshotGiven is
	// whether it was given at all.
	snapshot      string
	snapshotGiven bool
	allowRestart  bool
	dryRun        bool
	// wait is --wait as given: the budget of the step's wait after its record.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule, a flag twin create had until 019).
	waitGiven bool
}

func newTwinStepCmd(opts *options) *cobra.Command {
	f := &stepFlags{}
	cmd := &cobra.Command{
		Use:   "step",
		Short: "Take the running twin to another stage or a snapshot, without a rebuild",
		Long: "Take the running twin to another stage of its proposed change, the next one or the one\n" +
			"--stage names, or to a snapshot of any branch, the one --snapshot names. The API's\n" +
			"server resolves the target, reads it, takes the snapshot of what it read, compiles it\n" +
			"and files the snapshot and the bundle, as stage plan builds a stage; --snapshot\n" +
			"<id|file> names one its store holds by its id, or a snapshot file sent from here, which\n" +
			"it files, and it compiles that and files the bundle, reading no branch. The step\n" +
			"between the two bundles is printed, the host is checked for the twin after the step,\n" +
			"and containerlab's own plan for the lab is read. Then one run with the fixed identity\n" +
			"fylgja-step stages the target, lets containerlab reconcile the lab, waits for every\n" +
			"node it restarted, recreated or created, pushes every node whose configuration changed\n" +
			"by replace, and records the twin. Nothing is torn down: a step that fails or is\n" +
			"cancelled after its stage leaves the twin up and diverged (exit 4), and only fylgja\n" +
			"twin destroy clears it. A plan that restarts or recreates a node needs --allow-restart.\n" +
			"After the record the run reads the twin against the target until it conforms, at most\n" +
			"--wait (default " + defaultBudget + "), and records how that ended; the step's outcome does not\n" +
			"depend on it.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.stageGiven = cmd.Flags().Changed("stage")
			f.snapshotGiven = cmd.Flags().Changed("snapshot")
			f.waitGiven = cmd.Flags().Changed("wait")
			return runTwinStep(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"the stage to step to, <branch>/<label>, of the twin's own proposed change; the next one when left out")
	cmd.Flags().StringVar(&f.snapshot, "snapshot", "",
		"the snapshot to step to, <id|file>, a snapshot of any branch: a snapshot id (64 lowercase hex characters) the "+
			"server's store holds, or a snapshot file, which is read here and sent; no branch is read")
	cmd.Flags().BoolVar(&f.allowRestart, "allow-restart", false,
		"proceed when containerlab's plan restarts or recreates a node, which loses its running state until the step pushes it again")
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"resolve and read the target, take and file its snapshot, compile and file its bundle, check the host "+
			"and read containerlab's plan; start no run (with --snapshot, nothing is read)")
	cmd.Flags().StringVar(&f.wait, "wait", "",
		"after the record, read the twin until it conforms, at most this long (default "+defaultBudget+"; 0 reads once)")
	return cmd
}

// runTwinStep is twin step as one request; the server resolves and reads the target, or
// resolves the snapshot given, compiles it and files its bundle, checks its host, reads
// containerlab's plan and starts the run. A --snapshot is sent as twin create sends one
// (snapshotSent; 019, research R-04), its file read only when --stage is not also given, so
// the server's snapshot.flags.conflict answers first, whatever the file.
func runTwinStep(ctx context.Context, opts *options, f *stepFlags) error {
	a := given{}
	fromStage := f.stageGiven || f.stage != ""
	if fromStage {
		a["stage"] = f.stage
	}
	a.bool("allow_restart", f.allowRestart)
	a.bool("dry_run", f.dryRun)
	if f.waitGiven {
		a["wait"] = f.wait
	}
	var files []api.File
	if f.snapshotGiven || f.snapshot != "" {
		a["snapshot"] = f.snapshot
		if !fromStage {
			var err error
			if files, err = snapshotSent(findings.OpTwinStep, &findings.Subject{Snapshot: f.snapshot}, f.snapshot); err != nil {
				return err
			}
		}
	}
	return send(ctx, opts, findings.OpTwinStep, a, files, handlers{})
}
