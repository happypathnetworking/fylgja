package server

import (
	"context"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// rehearseFlags are twin rehearse's arguments (015): the proposed change's source branch,
// and whether --branch was given at all.
type rehearseFlags struct {
	branch      string
	branchGiven bool
}

// runTwinRehearse is twin rehearse (015; specs/015-proposed-change-rehearsal/contracts/
// rehearse-command.md): its guards, before any connection, as stage plan's are: --branch
// absent is --branch is required, and one that is not a branch is stage.ref.invalid at
// start.
//
// The API lists the operation before the server's order behind the guards (the plan, the
// baseline, the deadline, the host, the start, the follow and the report) is built, so a
// request the guards pass is refused, operation.failed at start, with nothing read, dialled
// or started.
func runTwinRehearse(_ context.Context, _ *options, f *rehearseFlags) error {
	const op = findings.OpTwinRehearse
	if !f.branchGiven && f.branch == "" {
		return fail(op, nil, "--branch is required")
	}
	if refused := branchGuard(op, f.branch); refused != nil {
		return refused
	}
	return failAt(op, &findings.Subject{Branch: f.branch}, findings.StepStart, op,
		"this server does not rehearse yet: twin rehearse is listed before its run is built")
}
