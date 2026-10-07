package server

import (
	"context"
	"errors"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// checkFlags carries no `at`: the schema endpoint accepts
// only `branch` and `namespaces` and ignores an `at` entirely, so a flag
// here would promise a pinned answer nothing can give.
type checkFlags struct {
	branch string
}

// runCheck answers the conformance question and nothing else. It issues no
// object query and loads no support packages: neither could change the answer, and
// asking would make `schema check` fail for reasons that are not about the schema.
func runCheck(ctx context.Context, opts *options, f *checkFlags) error {
	subject := &findings.Subject{Branch: f.branch}

	if f.branch == "" {
		return fail(findings.OpSchemaCheck, subject, "--branch is required")
	}

	cfg, err := intent.FromEnv(f.branch, "")
	if err != nil {
		return fail(findings.OpSchemaCheck, subject, "%v", err)
	}
	client := intent.New(cfg)

	if ctx == nil {
		ctx = context.Background()
	}
	ctx, cancel := context.WithTimeout(ctx, stage.ReadTimeout)
	defer cancel()

	conf, list, err := client.CheckConformance(ctx)
	if err != nil {
		return fail(findings.OpSchemaCheck, subject, "%v", err)
	}

	doc := findings.NewDocument(findings.OpSchemaCheck, subject, list)
	if list.Rejected() {
		return &result{doc: doc}
	}

	// Said only on success, and said in detail: "no findings" reads the same whether
	// every check ran or none did, so the answer names the contract version and which
	// of the operator's own kinds satisfies each generic.
	doc.Verified = conf.Verified()
	opts.note("contract %s ✓  %s", doc.Verified.ContractVersion, describeGenerics(doc.Verified.Generics))

	// The waypoint kind, from the default branch whatever branch was checked:
	// one line beside the answer, never a finding, the status and exit the conformance
	// answer's. An Infrahub that stopped answering here is the operation.failed the
	// conformance read would have given.
	waypoints, line, err := waypointsVerified(ctx)
	if err != nil {
		return fail(findings.OpSchemaCheck, subject, "%v", err)
	}
	doc.Verified.Waypoints = waypoints
	opts.note("%s", line)
	return &result{doc: doc}
}

// waypointsVerified asks the default branch's schema whether it carries the waypoint kind
// with every attribute this build reads, and says so in schema check's line
// (contracts/cli.md). Only an Infrahub that cannot be asked is an error.
func waypointsVerified(ctx context.Context) (*findings.WaypointsVerified, string, error) {
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		return nil, "", err
	}
	v := &findings.WaypointsVerified{Kind: intent.WaypointKind, Present: true, File: intent.WaypointSchemaFile}
	remedy := " (load " + intent.WaypointSchemaFile + "; needed only by the waypoint commands)"
	var kindErr *intent.WaypointKindError
	switch err := reader.Check(ctx); {
	case err == nil:
		return v, "waypoints: " + intent.WaypointKind + " present on the default branch", nil
	case !errors.As(err, &kindErr):
		return nil, "", err
	case len(kindErr.Missing) == 0:
		v.Present = false
		return v, "waypoints: " + intent.WaypointKind + " absent from the default branch" + remedy, nil
	default:
		v.Present, v.Missing = false, kindErr.Missing
		return v, "waypoints: " + intent.WaypointKind + " on the default branch lacks " + strings.Join(kindErr.Missing, ", ") + remedy, nil
	}
}

// describeGenerics renders the verified generics for the text success line, in the
// order ctm.RequiredGenerics declares them: `FylgjaDevice ← NetworkDevice; …`.
func describeGenerics(gens []findings.GenericKinds) string {
	parts := make([]string, 0, len(gens))
	for _, g := range gens {
		parts = append(parts, g.Generic+" ← "+strings.Join(g.Kinds, ", "))
	}
	return strings.Join(parts, "; ")
}
