package cli

import (
	"context"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

type verifyFlags struct {
	// wait is --wait's value: the flag's own default when it was given bare, read only when
	// waitGiven.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule).
	waitGiven bool
	// args are the positional arguments, which only a bare --wait leaves behind.
	args []string
}

func newTwinVerifyCmd(opts *options) *cobra.Command {
	f := &verifyFlags{}
	cmd := &cobra.Command{
		Use:   "verify",
		Short: "Read the running twin and say whether it conforms to intent",
		Long: "Read the twin on the lab host and hold it to the intent its staged bundle was\n" +
			"compiled from: each node's host name is its node name, every cabled port intent\n" +
			"enables is enabled, and every link is a neighbour seen from both ends, naming the\n" +
			"far node and port. What each node holds is reported from twin.json, and said to be\n" +
			"the record's claim. Each node is read once, over its own support package's\n" +
			"transport; --wait reads again until the twin conforms, within a budget: --wait\n" +
			"alone for the default " + defaultBudget + ", --wait=<duration> for another. Needs no\n" +
			"worker and starts no run, and changes nothing on the host, in the record or in the\n" +
			"store. Exit 5 says the twin does not conform; nothing acts on it.",
		// A bare --wait leaves the word after it as an argument, since the flag takes only
		// --wait=<value>: that is the flag misused, refused as verify.wait.invalid naming the
		// word, not cobra's usage error. Any other argument is cobra's.
		Args: func(cmd *cobra.Command, args []string) error {
			if cmd.Flags().Changed("wait") {
				return nil
			}
			return cobra.NoArgs(cmd, args)
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			f.waitGiven = cmd.Flags().Changed("wait")
			f.args = args
			return runTwinVerify(cmd.Context(), opts, f)
		},
	}
	cmd.Flags().StringVar(&f.wait, "wait", "",
		"read again until the twin conforms, at most this long: --wait alone for "+defaultBudget+
			", or --wait=<duration> (0 reads once)")
	cmd.Flags().Lookup("wait").NoOptDefVal = defaultBudget
	return cmd
}

// runTwinVerify is twin verify as one request: the server reads its twin, with no run and no
// worker. No interrupt is taken: one ends the client by the signal,
// and the request's work with it.
func runTwinVerify(ctx context.Context, opts *options, f *verifyFlags) error {
	a := given{}
	if f.waitGiven {
		a["wait"] = f.wait
	}
	if len(f.args) > 0 {
		a["args"] = f.args
	}
	return send(ctx, opts, findings.OpTwinVerify, a, nil, handlers{})
}
