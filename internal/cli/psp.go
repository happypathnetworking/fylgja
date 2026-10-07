package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

func newPSPCmd(opts *options) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "psp",
		Short: "Work with platform support packages",
	}
	cmd.AddCommand(newPSPValidateCmd(opts))
	return cmd
}

func newPSPValidateCmd(opts *options) *cobra.Command {
	return &cobra.Command{
		Use:   "validate <file>...",
		Short: "Validate platform support package files",
		Long: "Check support package files for structural and internal-consistency problems.\n" +
			"The API's server checks them, as the files given and nothing else: it needs\n" +
			"neither Infrahub nor the workflow service, so it runs in CI on contributed\n" +
			"packages. This is one check of the conformance suite's pure half.\n" +
			"\"Supported\" means both halves passed, the boot half against a booted node,\n" +
			"and the package's row in psp/README.md says so.",
		Args: cobra.MinimumNArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			return runPSPValidate(opts, args)
		},
	}
}

// runPSPValidate sends each package under the path given, in order, and the server validates
// them as a set, so psp.identity.duplicate still sees the set and every finding names the
// operator's path. A file that cannot be read is the operating system's
// sentence, as M12's readable gave it.
func runPSPValidate(opts *options, paths []string) error {
	subject := &findings.Subject{Files: paths}
	files, err := readPackages(paths)
	if err != nil {
		return fail(findings.OpPSPValidate, subject, "%v", err)
	}
	return send(context.Background(), opts, findings.OpPSPValidate, given{"files": paths}, files, handlers{})
}
