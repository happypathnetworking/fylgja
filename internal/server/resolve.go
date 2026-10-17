package server

import (
	"context"
	"errors"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

// flagConflict is one flag given beside --stage that a stage makes meaningless, and why
// (specs/014-proposed-change-stages/contracts/stage-reference.md).
type flagConflict struct {
	given bool
	flag  string
	why   string
}

// Why each flag is meaningless beside --stage.
const (
	wholeReference = "a stage is a whole pinned reference (branch and at)"
	neverFollows   = "a stage twin is pinned and never follows"
)

// stageGuards reads --stage and refuses what a stage makes meaningless, before any
// connection: a value that is not <branch>/<label> is stage.ref.invalid, and the first
// conflicting flag found, in the order given (--branch, --at, --interval), is
// stage.flags.conflict, each exit 2 at step. A reference that parses is named in the
// subject, so every document after it says which stage it was about.
func stageGuards(op string, subject *findings.Subject, step, given string, conflicts []flagConflict) (stages.Ref, error) {
	refuse := func(rule, object, message string) error {
		doc := findings.RuleErrorDocument(op, subject, rule, object, message)
		doc.Findings[0].Step = step
		return &result{doc: doc}
	}
	ref, err := stages.ParseRef(given)
	if err != nil {
		return stages.Ref{}, refuse(findings.RuleStageRefInvalid, given, err.Error())
	}
	subject.Stage = ref.String()
	for _, c := range conflicts {
		if c.given {
			return stages.Ref{}, refuse(findings.RuleStageFlagsConflict, c.flag,
				c.flag+" is meaningless with --stage: "+c.why)
		}
	}
	return ref, nil
}

// resolvedStage is a stage resolved on the server: the document's block, the record's
// stage, and the warnings the resolution found beside it (stage.main.moved), which every
// document after it carries.
type resolvedStage struct {
	block    findings.StageBlock
	record   *wire.StageRef
	warnings findings.List
}

// resolveStage resolves ref to the pinned reference it names, applying the reference
// contract's nine steps through stages.Resolve with the server's intent clients as the
// Stamper, and sets the subject's branch and at to it. The clock is read here, once, for
// the future rule alone, which holds a given at only, and never sent. Nothing of a
// branch's intent is read before it returns.
//
// A refusal is returned as the document the command ends with, each finding at step (none
// for intent read, whose operations carry none): exit 1, except M1's intent.at.precision,
// which keeps M1's exit 2. An Infrahub that cannot be reached or refuses the credential is
// operation.failed with M1's wording, exit 2.
func resolveStage(ctx context.Context, op string, subject *findings.Subject, step string, ref stages.Ref,
	reg *psp.Registry) (*resolvedStage, error) {
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return nil, failAt(op, subject, step, op, "%v", err)
	}
	res, list, err := stages.Resolve(ctx, reader, intentStamper{}, reg, ref, time.Now().UTC())
	if err != nil {
		return nil, failAt(op, subject, step, op, "%v", err)
	}
	for i := range list {
		list[i].Step = step
	}
	if list.Rejected() {
		doc := findings.NewDocument(op, subject, list)
		if carriesRule(list, findings.RuleAtPrecision) {
			doc.Status = findings.StatusError
		}
		return nil, &result{doc: doc}
	}
	subject.Branch, subject.At = res.Branch, res.At
	return &resolvedStage{block: res.Block(), record: res.StageRef(), warnings: list}, nil
}

// withStage carries the resolved stage on the document err holds, whatever it reports,
// with the resolution's warnings first: every document after a resolution says which stage
// the reference came from and what the resolution found beside it.
func withStage(err error, rs *resolvedStage) error {
	var res *result
	if rs != nil && errors.As(err, &res) {
		block := rs.block
		res.doc.Stage = &block
		if len(rs.warnings) > 0 {
			res.doc.Findings = append(append(findings.List{}, rs.warnings...), res.doc.Findings...)
		}
	}
	return err
}
