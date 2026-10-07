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
	cmd.AddCommand(newTwinCompileCmd(opts), newTwinCreateCmd(opts), newTwinProvisionCmd(opts), newTwinDestroyCmd(opts), newTwinShowCmd(opts), newTwinStepCmd(opts), newTwinVerifyCmd(opts))
	return cmd
}

type compileFlags struct {
	ctmPath string
	out     string
}

func newTwinCompileCmd(opts *options) *cobra.Command {
	f := &compileFlags{}
	cmd := &cobra.Command{
		Use:   "compile",
		Short: "Compile a CTM file into an artifact bundle",
		Long: "Compile a validated intent snapshot into a deterministic, self-describing\n" +
			"artifact bundle. The API's server compiles it against its platform support\n" +
			"packages and sends the bundle back, to be written here. It needs neither\n" +
			"Infrahub nor the workflow service: the compiler's only inputs are the CTM and\n" +
			"the packages. Creates no runtime resource — this is the stage before anything\n" +
			"is deployed.",
		Args: cobra.NoArgs,
		RunE: func(_ *cobra.Command, _ []string) error {
			return runCompile(opts, f)
		},
	}
	cmd.Flags().StringVar(&f.ctmPath, "ctm", "", "the CTM file to compile (required)")
	cmd.Flags().StringVar(&f.out, "out", "", "directory to write the bundle into (required)")
	return cmd
}

// runCompile sends the CTM and writes the bundle the server compiles from it to --out.
// The file is read only once both paths are given, so the server's two
// "is required" refusals keep M12's order; a CTM that cannot be read is worded as ctm.Load
// worded it, and a bundle that cannot be written as bundle.Write worded it.
func runCompile(opts *options, f *compileFlags) error {
	a := given{}
	a.string("ctm", f.ctmPath)
	a.string("out", f.out)
	var files []api.File
	if f.ctmPath != "" && f.out != "" {
		file, err := readCTM(f.ctmPath)
		if err != nil {
			return fail(findings.OpCompile, &findings.Subject{CTM: f.ctmPath, Out: f.out}, "%v", err)
		}
		files = []api.File{file}
	}
	return send(context.Background(), opts, findings.OpCompile, a, files, handlers{
		files: func(bundle []api.File) error { return writeBundle(bundle, f.out) },
	})
}
