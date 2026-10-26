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
	// every check ran or none did, so the answer names the library's commit the branch
	// conforms with and every kind the mapping reads (--json adds each kind's fields).
	doc.Verified = conf.Verified()
	opts.note("%s", conformantLine(doc.Verified))

	// The stage kind and its extension, from the default branch whatever branch was
	// checked: one line beside the answer, never a finding, the status and exit the
	// conformance answer's. An Infrahub that stopped answering here is the
	// operation.failed the conformance read would have given.
	verified, line, err := stagesVerified(ctx)
	if err != nil {
		return fail(findings.OpSchemaCheck, subject, "%v", err)
	}
	doc.Verified.Stages = verified
	opts.note("%s", line)
	return &result{doc: doc}
}

// stagesVerified asks the default branch's schema whether it carries the stage kind with
// every attribute and the relationship this build reads, and CoreProposedChange the
// extension, and says so in schema check's last line
// (specs/014-proposed-change-stages/contracts/stage-commands.md). Only an Infrahub that
// cannot be asked is an error.
func stagesVerified(ctx context.Context) (*findings.StagesVerified, string, error) {
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return nil, "", err
	}
	v := &findings.StagesVerified{Kind: intent.StageKind, Present: true, Extension: true, File: intent.StageSchemaFile}
	remedy := " (load " + intent.StageSchemaFile + "; needed only by --stage, stage list and stage plan)"
	lacksExtension := intent.ProposedChangeKind + " lacks " + intent.StageExtension
	var kindErr *intent.StageKindError
	switch err := reader.Check(ctx); {
	case err == nil:
		return v, "stages: " + intent.StageKind + " present on the default branch, with its extension", nil
	case !errors.As(err, &kindErr):
		return nil, "", err
	case len(kindErr.Missing) == 0 && !kindErr.Extension:
		v.Present, v.Extension = false, false
		return v, "stages: " + intent.StageKind + " absent from the default branch" + remedy, nil
	case len(kindErr.Missing) == 0:
		v.Extension = false
		return v, "stages: " + intent.StageKind + " present on the default branch, but " + lacksExtension + remedy, nil
	}
	v.Present, v.Missing, v.Extension = false, kindErr.Missing, !kindErr.Extension
	line := "stages: " + intent.StageKind + " on the default branch lacks " + strings.Join(kindErr.Missing, ", ")
	if kindErr.Extension {
		line += ", and " + lacksExtension
	}
	return v, line + remedy, nil
}

// conformantLine is the text success line, naming the commit and the kinds in the
// mapping's table's order: `conformant with opsmill/schema-library@26336e9: DcimDevice,
// DcimPlatform, …`.
func conformantLine(v *findings.Verified) string {
	kinds := make([]string, 0, len(v.Kinds))
	for _, k := range v.Kinds {
		kinds = append(kinds, k.Kind)
	}
	return "conformant with " + v.Model + "@" + v.Version + ": " + strings.Join(kinds, ", ")
}
