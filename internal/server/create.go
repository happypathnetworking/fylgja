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
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

type createFlags struct {
	branch string
	at     string
	// waypoint is --waypoint as given, <series>/<sequence>: a pinned reference named in
	// Infrahub, in place of --branch and --at (M10).
	waypoint string
	// waypointGiven is whether --waypoint was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	waypointGiven bool
	dryRun        bool
	// interval is --interval's value, read only when intervalGiven; not given, the default stands.
	interval      string
	intervalGiven bool
	noFollow      bool
}

// fromWaypoint is whether the create names a waypoint: --waypoint given, whatever its value,
// or a value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromWaypoint() bool {
	return f.waypointGiven || f.waypoint != ""
}

func runCreate(ctx context.Context, opts *options, f *createFlags) error {
	const op = findings.OpTwinCreate
	subject := &findings.Subject{Branch: f.branch, At: f.at}

	if f.branch == "" && !f.fromWaypoint() {
		return fail(op, subject, "--branch or --waypoint is required")
	}
	var ref waypoint.Ref
	var follow findings.DryRunFollow
	if f.fromWaypoint() {
		// A waypoint is a whole pinned reference: its guards stand in for --at's and
		// --interval's, before any connection (M10 contracts/cli.md). --no-follow beside
		// it changes nothing.
		var refused error
		ref, refused = waypointGuards(op, subject, findings.StepStart, f.waypoint, []flagConflict{
			{f.branch != "", "--branch", wholeReference},
			{f.at != "", "--at", wholeReference},
			{f.intervalGiven, "--interval", neverFollows},
		})
		if refused != nil {
			return refused
		}
		// A waypoint twin never follows, so no interval is read.
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
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package `psp validate` rejects is refused under its own findings
	// before anything is read or started.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepRead, err)
	}

	// A waypoint resolves here, in the CLI, before any run starts; what follows is the
	// pinned create of the reference it names.
	branch, at := f.branch, f.at
	var resolved *findings.WaypointBlock
	if f.fromWaypoint() {
		if resolved, err = resolveWaypoint(ctx, op, subject, findings.StepResolve, ref); err != nil {
			return err
		}
		branch, at = resolved.Branch, resolved.At
		opts.note("%s", resolved.Line())
	}
	if f.dryRun {
		return withWaypoint(runCreateDryRun(ctx, opts, op, subject, branch, at, reg, follow), resolved)
	}

	in := provision.ProvisionInput{
		Source:  wire.SourceIntent,
		Branch:  branch,
		At:      at,
		Version: opts.version(),
	}
	// A twin built from the branch head follows it unless --no-follow; a pinned one never does.
	if follow.Enabled {
		in.Follow = &provision.FollowInput{IntervalS: follow.IntervalS}
	}
	// The run records the waypoint as data, and branches on nothing of it.
	if resolved != nil {
		in.Waypoint = &provision.WaypointInput{Series: resolved.Series, Sequence: resolved.Sequence,
			Description: resolved.Description, AtSource: resolved.AtSource}
	}
	return withWaypoint(runProvision(ctx, opts, op, subject, in), resolved)
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
	case f.fromWaypoint():
		return findings.DryRunFollow{Reason: findings.FollowReasonWaypoint}
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
// `twin compile` would, under the same identifiers. The bundle, and the CTM beside
// it, are filed as a run's compile step files them, so the report's bundle is there to
// inspect.
func runCreateDryRun(ctx context.Context, opts *options, op string, subject *findings.Subject, branch, at string, reg *psp.Registry,
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
	snapshot, list, err := stage.Read(ctx, branch, at, reg, observedAt)
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

	store, filed, err := fileCompiled(ctx, paths.Bundles, files, id, snapshot)
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
