// Command fylgja builds a live digital twin of a network from intent.
//
// One binary, three roles (D-018). `serve` is the API's server and
// `worker run` serves the Temporal task queue, both on the lab host; every other command is
// the client, which reaches the core through the API alone (D-040), from internal/cli.
package main

import (
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/cli"
)

// version is what `fylgja --version` reports. The Makefile stamps it through -ldflags
// (`make build VERSION=0.2.0`) and defaults to the same string as this literal, so an
// unstamped `go build` and an ordinary `make build` agree rather than one of them
// claiming a release it is not.
//
// It identifies the binary, never the bundle: nothing derived from the build reaches a
// bundle, or every release would change bundle_id for unchanged intent and reconcile
// would rebuild every twin on upgrade (D-024). The client compares it with the
// server's, and the server sends it on every answer.
var version = "0.1.0-dev"

// exitStatus carries an exit code out of a command that has already written its own
// output and has no findings document to render: `serve` and `worker run`.
type exitStatus int

func (e exitStatus) Error() string { return fmt.Sprintf("exit status %d", int(e)) }

func main() {
	cmd, err := newRoot().ExecuteC()
	os.Exit(exitCode(cmd, err))
}

// newRoot is the command tree: the client's commands, serve and worker run.
func newRoot() *cobra.Command {
	root := &cobra.Command{
		Use:           "fylgja",
		Short:         "Build a live digital twin of a network from intent",
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       version,
	}
	cli.AddCommands(root, version)
	root.AddCommand(newServeCmd(version), newWorkerCmd(&options{}))
	return root
}

// exitCode is the process's exit status for what the root's ExecuteC returned: the status a
// command that wrote its own output carries, or the findings document Report renders.
func exitCode(cmd *cobra.Command, err error) int {
	var status exitStatus
	if errors.As(err, &status) {
		return int(status)
	}
	return cli.Report(cmd, err)
}
