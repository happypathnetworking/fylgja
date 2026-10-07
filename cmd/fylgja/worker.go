package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"

	"github.com/spf13/cobra"
	"go.temporal.io/sdk/worker"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// options are worker run's: the override directory of support packages, which from M13 is
// its own flag, as the API's server's is, and no client's.
type options struct {
	pspDir string
}

// resolve fills in what the environment supplies.
func (o *options) resolve() {
	if o.pspDir == "" {
		o.pspDir = os.Getenv("FYLGJA_PSP_DIR")
	}
}

func newWorkerCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "worker",
		Short: "Run the lab host worker",
	}
	run := &cobra.Command{
		Use:   "run",
		Short: "Serve task queue fylgja on this host",
		Long: "Serve task queue fylgja: both workflows and every activity, on the host where\n" +
			"the containers run. Runs until interrupted. Produces no findings document;\n" +
			"start-up lines go to stdout and logs to stderr.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			opts.resolve()
			return runWorker(cmd.Context(), opts)
		},
	}
	run.Flags().StringVar(&opts.pspDir, "psp-dir", "",
		"directory of platform support packages overriding the embedded ones (or FYLGJA_PSP_DIR)")
	cmd.AddCommand(run)
	return cmd
}

// runWorker serves the queue until SIGINT or SIGTERM. Every refusal to start is one or
// more lines on stderr and exit 2: a worker has no document to report in.
func runWorker(ctx context.Context, opts *options) error {
	if ctx == nil {
		ctx = context.Background()
	}
	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))

	paths, err := lab.ResolvePaths()
	if err != nil {
		return workerExit("%v", err)
	}

	// A worker must not serve with a package `psp validate` rejects: every run it took
	// would fail later, under the wrong identifier. Refused before dialling.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		var invalid *psp.InvalidError
		if errors.As(err, &invalid) {
			doc := findings.NewDocument(findings.OpPSPValidate, nil, invalid.Findings)
			_ = doc.WriteText(os.Stderr)
			return workerExit("refusing to serve with an invalid support package")
		}
		return workerExit("%v", err)
	}

	// An unreachable service is one line naming the address, and exit 2.
	c, err := provision.Dial(ctx, logger)
	if err != nil {
		return workerExit("%v", err)
	}
	defer c.Close()

	store := bundle.NewDirStore(paths.Bundles)
	acts := &lab.Activities{
		Clab:     &lab.Clab{Runner: lab.ExecRunner{}, Log: logger},
		Store:    store,
		Paths:    paths,
		Registry: reg,
		Prober:   lab.GNMIProber{Log: logger},
		Images:   lab.DockerImages{Runner: lab.ExecRunner{}},
		Getenv:   os.LookupEnv,
		Version:  version,
		Log:      logger,
	}
	control := &provision.ControlActivities{Store: store, Paths: paths, PSPDir: opts.pspDir, Client: c.Client}
	w := provision.NewWorker(c.Client, acts, control)

	// What the worker serves, where its state lives, and what the host already holds, before
	// it takes any task (Constitution VII).
	for _, line := range provision.StartupReport(ctx, acts, c.Address, c.Namespace) {
		_, _ = fmt.Fprintln(os.Stdout, line)
	}

	if err := w.Run(worker.InterruptCh()); err != nil {
		return workerExit("%v", err)
	}
	return nil
}

// workerExit prints one line on stderr and exits 2.
func workerExit(format string, args ...any) error {
	fmt.Fprintf(os.Stderr, "fylgja worker: "+format+"\n", args...)
	return exitStatus(findings.ExitError)
}
