package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newTwinCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "twin",
		Short: "Build and inspect twins",
	}
	cmd.AddCommand(newTwinCompileCmd(opts), newTwinCreateCmd(opts), newTwinProvisionCmd(opts), newTwinDestroyCmd(opts), newTwinShowCmd(opts), newTwinStepCmd(opts), newTwinVerifyCmd(opts), newTwinRehearseCmd(opts))
	return cmd
}

type compileFlags struct {
	// snapshotPath is --snapshot as given: the snapshot file to compile (018: in place of
	// --ctm, which is retired).
	snapshotPath string
	out          string
}

func newTwinCompileCmd(opts *options) *cobra.Command {
	f := &compileFlags{}
	cmd := &cobra.Command{
		Use:   "compile",
		Short: "Compile a snapshot file into an artifact bundle",
		Long: "Compile a snapshot's intent into a deterministic, self-describing artifact\n" +
			"bundle. The API's server compiles it against its platform support packages and\n" +
			"sends the bundle back, to be written here. It needs neither Infrahub nor the\n" +
			"workflow service: the compiler's only inputs are the snapshot's CTM and the\n" +
			"packages. Files nothing and creates no runtime resource — this is the stage\n" +
			"before anything is deployed.\n" +
			"\n" +
			"A snapshot is what intent read --out writes. A bare CTM is wrapped by hand as\n" +
			"{\"snapshot_version\": \"2\", \"ctm\": <the CTM>, \"probes\": []}: the server\n" +
			"computes the snapshot_id and fills the observed_at from the CTM.",
		Args: cobra.NoArgs,
		RunE: func(_ *cobra.Command, _ []string) error {
			return runCompile(opts, f)
		},
	}
	cmd.Flags().StringVar(&f.snapshotPath, "snapshot", "", "the snapshot file to compile (required)")
	cmd.Flags().StringVar(&f.out, "out", "", "directory to write the bundle into (required)")
	return cmd
}

// runCompile sends the snapshot and writes the bundle the server compiles from it to --out.
// The file is read only once both paths are given, so the server's two "is required"
// refusals keep M12's order; a snapshot that cannot be read is worded as snapshot.Load words
// it, and a bundle that cannot be written as bundle.Write worded it.
func runCompile(opts *options, f *compileFlags) error {
	a := given{}
	a.string("snapshot", f.snapshotPath)
	a.string("out", f.out)
	var files []api.File
	if f.snapshotPath != "" && f.out != "" {
		file, err := readSnapshot(f.snapshotPath)
		if err != nil {
			return fail(findings.OpCompile, &findings.Subject{Snapshot: f.snapshotPath, Out: f.out}, "%v", err)
		}
		files = []api.File{file}
	}
	return send(context.Background(), opts, findings.OpCompile, a, files, handlers{
		files: func(bundle []api.File) error { return writeBundle(bundle, f.out) },
	})
}
