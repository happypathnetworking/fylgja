package server

import (
	"context"
	"fmt"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

type createFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven bool
	dryRun     bool
	// interval is --interval's value, read only when intervalGiven; not given, the default stands.
	interval      string
	intervalGiven bool
	noFollow      bool
	// scope is --scope as given, read only when scopeGiven: not given, the server's default
	// stands (017).
	scope      string
	scopeGiven bool
}

// fromStage is whether the create names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

func runCreate(ctx context.Context, opts *options, f *createFlags) error {
	const op = findings.OpTwinCreate
	subject := &findings.Subject{Branch: f.branch, At: f.at}

	if f.branch == "" && !f.fromStage() {
		return fail(op, subject, "--branch or --stage is required")
	}
	var ref stages.Ref
	var follow findings.DryRunFollow
	if f.fromStage() {
		// A stage is a whole pinned reference: its guards stand in for --at's and
		// --interval's, before any connection. --no-follow beside it changes nothing.
		var refused error
		ref, refused = stageGuards(op, subject, findings.StepStart, f.stage, []flagConflict{
			{f.branch != "", "--branch", wholeReference},
			{f.at != "", "--at", wholeReference},
			{f.intervalGiven, "--interval", neverFollows},
		})
		if refused != nil {
			return refused
		}
		// A stage twin never follows, so no interval is read.
		follow = createFollow(f, 0)
	} else {
		// M1's precision guard, before any connection.
		if msg := intent.CheckAtPrecision(f.at); msg != "" {
			return &result{doc: findings.RuleErrorDocument(op, subject, findings.RuleAtPrecision, f.at, msg)}
		}
		// The following guards, before any connection (contracts/cli.md, create step 1).
		interval, err := followInterval(op, subject, f)
		if err != nil {
			return err
		}
		if refused := followFlagsConflict(op, subject, f); refused != nil {
			return refused
		}
		follow = createFollow(f, interval)
	}
	// The scope, after the reference's and the following's guards and before the packages
	// load: the stage's resolution, the read and the run's are made under it.
	scope, err := scopeOf(opts, op, subject, f.scope, f.scopeGiven)
	if err != nil {
		return err
	}
	subject.Scope = scope
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package `psp validate` rejects is refused under its own findings
	// before anything is read or started.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepRead, err)
	}

	// A stage resolves here, on the server, before any run starts and before any branch's
	// intent is read; what follows is the pinned create of the reference it names.
	branch, at := f.branch, f.at
	var resolved *resolvedStage
	if f.fromStage() {
		if resolved, err = resolveStage(ctx, op, subject, findings.StepResolve, ref, scope, reg); err != nil {
			return err
		}
		branch, at = resolved.block.Branch, resolved.block.At
		opts.note("%s", resolved.block.Line())
	}
	if f.dryRun {
		return withStage(runCreateDryRun(ctx, opts, op, subject, branch, at, scope, reg, follow), resolved)
	}

	in := provision.ProvisionInput{
		Source:  wire.SourceIntent,
		Branch:  branch,
		At:      at,
		Version: opts.version(),
		Scope:   scope,
	}
	// A twin built from the branch head follows it unless --no-follow; a pinned one never does.
	if follow.Enabled {
		in.Follow = &provision.FollowInput{IntervalS: follow.IntervalS}
	}
	// The run records the stage as data, and branches on nothing of it.
	if resolved != nil {
		in.Stage = resolved.record
	}
	return withStage(runProvision(ctx, opts, op, subject, in), resolved)
}

// followFlagsConflict refuses --interval given with --at or with --no-follow as
// follow.flags.conflict, before any connection: the twin would not follow, so the interval
// would mean nothing (contracts/cli.md, create step 1). --at with --no-follow is accepted.
func followFlagsConflict(op string, subject *findings.Subject, f *createFlags) error {
	if !f.intervalGiven {
		return nil
	}
	var message string
	switch {
	case f.at != "":
		message = "--interval is meaningless with --at: a pinned twin never follows"
	case f.noFollow:
		message = "--interval is meaningless with --no-follow: the twin will not follow"
	default:
		return nil
	}
	doc := findings.RuleErrorDocument(op, subject, findings.RuleFollowFlagsConflict, "--interval", message)
	doc.Findings[0].Step = findings.StepStart
	return &result{doc: doc}
}

// createFollow is whether the twin a create builds follows its branch, and how often it is
// checked, or why it does not: what the run is started with and what a dry run reports.
func createFollow(f *createFlags, interval time.Duration) findings.DryRunFollow {
	switch {
	case f.fromStage():
		return findings.DryRunFollow{Reason: findings.FollowReasonStage}
	case f.at != "":
		return findings.DryRunFollow{Reason: findings.FollowReasonPinned}
	case f.noFollow:
		return findings.DryRunFollow{Reason: findings.FollowReasonNoFollow}
	}
	return findings.DryRunFollow{Enabled: true, IntervalS: int(interval / time.Second)}
}

// followInterval parses --interval, not given being the default, and refuses one that is not
// a duration, an empty one included, or is below the floor as follow.interval.invalid
// (contracts/cli.md).
func followInterval(op string, subject *findings.Subject, f *createFlags) (time.Duration, error) {
	if !f.intervalGiven {
		return provision.DefaultInterval, nil
	}
	value := f.interval
	refuse := func(message string) error {
		doc := findings.RuleErrorDocument(op, subject, findings.RuleFollowIntervalInvalid, value, message)
		doc.Findings[0].Step = findings.StepStart
		return &result{doc: doc}
	}
	d, err := time.ParseDuration(value)
	if err != nil {
		return 0, refuse(fmt.Sprintf("--interval %s is not a duration: %v", value, err))
	}
	if d < provision.MinInterval {
		return 0, refuse(fmt.Sprintf("--interval %s is below the floor %s", value, provision.MinInterval))
	}
	return d, nil
}

// runCreateDryRun reads, compiles and files the bundle in this process, then reports what a
// real create would do; it never dials the workflow service. Read and compile are
// the stage commands' own pipelines, so a dry run refuses exactly what `intent read` and
// `twin compile` would, under the same identifiers. The bundle is filed as a run's
// compile step files it, so the report's bundle is there to inspect.
func runCreateDryRun(ctx context.Context, opts *options, op string, subject *findings.Subject, branch, at, scope string, reg *psp.Registry,
	follow findings.DryRunFollow) error {
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, subject, findings.StepRead, findings.StepRead, "%v", err)
	}

	// Every finding is placed at its step, and a step that could not run names the object the
	// run's own read and compile name, so a dry run reports as the run does.
	//
	// Captured before the first request, so observed_at is never later than anything the
	// read could have seen.
	observedAt := time.Now().UTC().Format(stage.ObservedAtFormat)
	snapshot, list, err := stage.Read(ctx, branch, at, scope, reg, observedAt)
	if err != nil {
		return failAt(op, subject, findings.StepRead, "branch "+branch, "%v", err)
	}
	list = list.AtStep(findings.StepRead)
	if snapshot == nil {
		return finish(op, subject, list)
	}

	files, id, compiled := stage.Compile(snapshot, reg)
	compiled = compiled.AtStep(findings.StepCompile)
	list = append(list, compiled...)
	if compiled.Rejected() {
		return finish(op, subject, list)
	}

	store, filed, err := fileCompiled(ctx, paths.Bundles, files, id)
	if err != nil {
		return failAt(op, subject, findings.StepCompile, paths.Bundles, "%v", err)
	}
	if filed.Rejected() {
		return finish(op, subject, append(list, filed...))
	}

	read := &readSummary{counts: intent.Summarize(snapshot), packages: intent.DevicesByPackage(snapshot, reg),
		envelope: snapshot.Envelope}
	return dryRunReport(ctx, opts, op, subject, reg, paths, store.Path(id), id, read, list, follow)
}
