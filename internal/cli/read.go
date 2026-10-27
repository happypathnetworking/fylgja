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
	// scope is --scope as given, sent only when scopeGiven: not given, the server's default
	// stands, and an explicit empty one is the server's to refuse (017).
	scope      string
	scopeGiven bool
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
		Long: "Read the devices an Infrahub branch's scope selects, by the mapping of the schema\n" +
			"library's DCIM at 26336e9, and write a snapshot file: the canonical CTM, wrapped\n" +
			"with its snapshot_id, which the API's server also files in its store, so twin\n" +
			"create --snapshot <id> builds from it. Conformance, data completeness and the\n" +
			"compiler's intent rules are checked in one pass and reported together; any\n" +
			"rejection means no file is written and nothing is filed.\n" +
			"Reads only — Fylgja never writes to Infrahub.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			f.stageGiven = cmd.Flags().Changed("stage")
			f.scopeGiven = cmd.Flags().Changed("scope")
			return runRead(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.branch, "branch", "", "Infrahub branch to read (this or --stage is required)")
	cmd.Flags().StringVar(&f.at, "at", "",
		"point in time to read at, passed verbatim; omitted entirely when not given")
	cmd.Flags().StringVar(&f.stage, "stage", "",
		"stage to read, <branch>/<label>: the pinned branch and at a proposed change's stage resolves to")
	cmd.Flags().StringVar(&f.out, "out", "", "path of the snapshot file to write (required)")
	cmd.Flags().StringVar(&f.scope, "scope", "", scopeUsage)
	return cmd
}

// runRead is intent read as one request: the server reads and validates, takes and files
// the snapshot, and answers with it in a files frame before its summary line, which the
// client writes to --out atomically (018: in place of the CTM). A refused read sends no
// snapshot, and nothing is written.
func runRead(ctx context.Context, opts *options, f *readFlags) error {
	a := given{}
	a.string("branch", f.branch)
	a.string("at", f.at)
	if f.fromStage() {
		a["stage"] = f.stage
	}
	a.string("out", f.out)
	a.scope(f.scope, f.scopeGiven)
	return send(ctx, opts, findings.OpIntentRead, a, nil, handlers{
		files: func(files []api.File) error {
			if len(files) != 1 {
				return fmt.Errorf("the answer carries %d files where intent read sends the snapshot alone", len(files))
			}
			return writeSnapshot(files[0].Data, f.out)
		},
	})
}
