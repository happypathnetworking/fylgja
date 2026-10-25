package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The defaults and floors a client's help names, which are the core's: provision's
// DefaultInterval and MinInterval, and verify's DefaultBudget. The client links neither
// package, so they are written here, and a test holds each to the core's own
// (TestFlagDefaultsAreTheCoresOwn).
const (
	defaultInterval = "5m0s"
	minInterval     = "10s"
	defaultBudget   = "2m0s"
)

type createFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// by the server to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven bool
	dryRun     bool
	// interval is --interval's value, read only when intervalGiven; not given, the default stands.
	interval      string
	intervalGiven bool
	noFollow      bool
	// scope is --scope as given, sent only when scopeGiven: not given, the server's default
	// stands, and an explicit empty one is the server's to refuse (017).
	scope      string
	scopeGiven bool
}

func newTwinCreateCmd(opts *options) *cobra.Command {
	f := &createFlags{}
	cmd := &cobra.Command{
		Use:   "create",
		Short: "Read, compile and provision one twin from a branch",
		Long: "Read an Infrahub branch, compile it and provision the twin through the lab host's\n" +
			"worker, as one run with the fixed identity fylgja-provision. Prints a line as each\n" +
			"step begins and ends, and blocks until every node answers its readiness probe or\n" +
			"the run has cleaned up after itself. Interrupt once to cancel the run and wait for\n" +
			"its cleanup; a second time to stop waiting.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			// Whether --interval was given is kept apart from its value, so a given value is
			// parsed whatever it is, even empty, and the conflict guard sees only a flag the
			// operator gave; the flag's default is shown in the help alone.
			f.intervalGiven = cmd.Flags().Changed("interval")
			f.stageGiven = cmd.Flags().Changed("stage")
			f.scopeGiven = cmd.Flags().Changed("scope")
			return runCreate(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to read (this or --stage is required)")
	cmd.Flags().StringVar(&f.at, "at", "",
		"point in time to read at, passed verbatim; omitted entirely when not given")
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"stage to build the twin from, <branch>/<label>: the pinned branch and at a proposed change's stage resolves to, never followed")
	cmd.Flags().StringVar(&f.interval, "interval", defaultInterval,
		"how often a following twin is checked, as a Go duration (5m, 90s); floor "+minInterval)
	cmd.Flags().BoolVar(&f.noFollow, "no-follow", false,
		"build the twin from the branch head and never check it: a frozen twin")
	cmd.Flags().BoolVar(&f.dryRun, "dry-run", false,
		"read, compile, file the bundle and check the host; start no run")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	return cmd
}

// fromStage is whether the create names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

// runCreate is twin create as one request: the flags given, and the server's answer printed
// as it comes. Every guard, the stage's and the following's among them,
// is the server's.
func runCreate(ctx context.Context, opts *options, f *createFlags) error {
	a := given{}
	a.string("branch", f.branch)
	a.string("at", f.at)
	if f.fromStage() {
		a["stage"] = f.stage
	}
	if f.intervalGiven {
		a["interval"] = f.interval
	}
	a.bool("no_follow", f.noFollow)
	a.bool("dry_run", f.dryRun)
	a.scope(f.scope, f.scopeGiven)
	return send(ctx, opts, findings.OpTwinCreate, a, nil, handlers{})
}
