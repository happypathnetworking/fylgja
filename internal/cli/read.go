package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newIntentCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "intent",
		Short: "Read intent from the source of truth",
	}
	cmd.AddCommand(newIntentReadCmd(opts))
	return cmd
}

type readFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// by the server to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven bool
	out        string
}

// fromStage is whether the read names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *readFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

func newIntentReadCmd(opts *options) *cobra.Command {
	f := &readFlags{}
	cmd := &cobra.Command{
		Use:   "read",
		Short: "Read a branch into a validated intent snapshot",
		Long: "Read an Infrahub branch through Fylgja's generics and write a canonical CTM\n" +
			"file. Conformance, data completeness and the compiler's intent rules are checked\n" +
			"in one pass and reported together; any rejection means no file is written.\n" +
			"Reads only — Fylgja never writes to Infrahub.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.stageGiven = cmd.Flags().Changed("stage")
			return runRead(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to read (this or --stage is required)")
	cmd.Flags().StringVar(&f.at, "at", "",
		"point in time to read at, passed verbatim; omitted entirely when not given")
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"stage to read, <branch>/<label>: the pinned branch and at a proposed change's stage resolves to")
	cmd.Flags().StringVar(&f.out, "out", "", "path of the CTM file to write (required)")
	return cmd
}

// runRead is intent read as one request: the server reads and validates, and answers with
// the CTM in a files frame before its summary line, which the client writes to --out
// atomically, as writeCTM did. A refused read sends no CTM, and nothing is
// written.
func runRead(ctx context.Context, opts *options, f *readFlags) error {
	a := given{}
	a.string("branch", f.branch)
	a.string("at", f.at)
	if f.fromStage() {
		a["stage"] = f.stage
	}
	a.string("out", f.out)
	return send(ctx, opts, findings.OpIntentRead, a, nil, handlers{
		files: func(files []api.File) error {
			if len(files) != 1 {
				return fmt.Errorf("the answer carries %d files where intent read sends the CTM alone", len(files))
			}
			return writeCTM(files[0].Data, f.out)
		},
	})
}
