package server

import (
	"context"
	"errors"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

// flagConflict is one flag given beside --waypoint that a waypoint makes meaningless, and
// why (contracts/cli.md).
type flagConflict struct {
	given bool
	flag  string
	why   string
}

// Why each flag is meaningless beside --waypoint (contracts/cli.md).
const (
	wholeReference = "a waypoint is a whole pinned reference (branch and at)"
	neverFollows   = "a waypoint twin is pinned and never follows"
)

// waypointGuards reads --waypoint and refuses what a waypoint makes meaningless, before any
// connection: a value that is not <series>/<sequence> is waypoint.ref.invalid, and the
// first conflicting flag found is waypoint.flags.conflict, each exit 2 at step. A reference
// that parses is named in the subject, so every
// document after it says which waypoint it was about.
func waypointGuards(op string, subject *findings.Subject, step, given string, conflicts []flagConflict) (waypoint.Ref, error) {
	refuse := func(rule, object, message string) error {
		doc := findings.RuleErrorDocument(op, subject, rule, object, message)
		doc.Findings[0].Step = step
		return &result{doc: doc}
	}
	ref, err := waypoint.ParseRef(given)
	if err != nil {
		return waypoint.Ref{}, refuse(findings.RuleWaypointRefInvalid, given, err.Error())
	}
	subject.Waypoint = ref.String()
	for _, c := range conflicts {
		if c.given {
			return waypoint.Ref{}, refuse(findings.RuleWaypointFlagsConflict, c.flag,
				c.flag+" is meaningless with --waypoint: "+c.why)
		}
	}
	return ref, nil
}

// resolveWaypoint resolves ref to the pinned reference it names, from Infrahub's default
// branch, and sets the subject's branch and at to it. The clock is read here, once, for
// the future rule alone, which holds a given at only, and never sent.
//
// A refusal is returned as the document the command ends with, each finding at step (none
// for intent read, whose operations carry none): exit 1, except M1's intent.at.precision,
// which keeps M1's exit 2. An Infrahub that cannot be reached or refuses the credential is
// operation.failed with M1's wording, exit 2.
func resolveWaypoint(ctx context.Context, op string, subject *findings.Subject, step string, ref waypoint.Ref) (*findings.WaypointBlock, error) {
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		return nil, failAt(op, subject, step, op, "%v", err)
	}
	res, list, err := waypoint.Resolve(ctx, reader, ref, time.Now().UTC())
	if err != nil {
		return nil, failAt(op, subject, step, op, "%v", err)
	}
	if len(list) > 0 {
		for i := range list {
			list[i].Step = step
		}
		doc := findings.NewDocument(op, subject, list)
		if carriesRule(list, findings.RuleAtPrecision) {
			doc.Status = findings.StatusError
		}
		return nil, &result{doc: doc}
	}
	subject.Branch, subject.At = res.Branch, res.At
	return &findings.WaypointBlock{Series: ref.Series, Sequence: ref.Sequence, Branch: res.Branch, At: res.At,
		AtSource: res.AtSource, Description: res.Description}, nil
}

// withWaypoint carries the resolved waypoint on the document err holds, whatever it
// reports: every document after a resolution says which waypoint the reference came from.
func withWaypoint(err error, block *findings.WaypointBlock) error {
	var res *result
	if block != nil && errors.As(err, &res) {
		res.doc.Waypoint = block
	}
	return err
}
