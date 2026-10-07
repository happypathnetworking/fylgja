package server

import (
	"context"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// A create dry run says whether the twin would follow its branch, in its follow: line and in
// dry_run.follow, and schedules nothing (contracts/cli.md). No fake Infrahub answers
// a read in tier 1, so the create is taken in its two halves: createFollow, which runCreate
// derives from the flags and hands the report, and the report itself for each answer.
func TestDryRunFollowCreate(t *testing.T) {
	for _, c := range []struct {
		name  string
		flags createFlags
		want  findings.DryRunFollow
		line  string
	}{
		{"no flag", createFlags{branch: "fylgja-fixture"}, findings.DryRunFollow{Enabled: true, IntervalS: 300},
			"follow: would follow branch fylgja-fixture, checked every 5m0s"},
		{"--interval 90s", createFlags{branch: "fylgja-fixture", interval: "90s", intervalGiven: true}, findings.DryRunFollow{Enabled: true, IntervalS: 90},
			"follow: would follow branch fylgja-fixture, checked every 1m30s"},
		{"--at", createFlags{branch: "fylgja-fixture", at: "2026-09-16T14:00:00Z"},
			findings.DryRunFollow{Reason: findings.FollowReasonPinned}, "follow: would not follow (--at given)"},
		{"--no-follow", createFlags{branch: "fylgja-fixture", noFollow: true},
			findings.DryRunFollow{Reason: findings.FollowReasonNoFollow}, "follow: would not follow (--no-follow given)"},
		{"--at --no-follow", createFlags{branch: "fylgja-fixture", at: "2026-09-16T14:00:00Z", noFollow: true},
			findings.DryRunFollow{Reason: findings.FollowReasonPinned}, "follow: would not follow (--at given)"},
		// M10: a waypoint is pinned, and says so rather than "--at given".
		{"--waypoint", createFlags{waypoint: "demo/2"},
			findings.DryRunFollow{Reason: findings.FollowReasonWaypoint}, "follow: would not follow (--waypoint given: a waypoint is pinned)"},
		{"--waypoint --no-follow", createFlags{waypoint: "demo/2", noFollow: true},
			findings.DryRunFollow{Reason: findings.FollowReasonWaypoint}, "follow: would not follow (--waypoint given: a waypoint is pinned)"},
	} {
		t.Run(c.name, func(t *testing.T) {
			interval, err := followInterval(findings.OpTwinCreate, &findings.Subject{}, &c.flags)
			if err != nil {
				t.Fatal(err)
			}
			if got := createFollow(&c.flags, interval); got != c.want {
				t.Fatalf("createFollow = %+v, want %+v", got, c.want)
			}

			paths := useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			dir := copyGoldenBundle(t, "b")
			reg, err := psp.Load("")
			if err != nil {
				t.Fatal(err)
			}
			subject := &findings.Subject{Branch: c.flags.branch, At: c.flags.at}

			var runErr error
			out := captureStdout(t, func() {
				runErr = dryRunReport(context.Background(), testOptions(t, false), findings.OpTwinCreate, subject, reg, paths, dir, fixtureBundleID,
					nil, nil, c.want)
			})
			if code, _ := exitOf(t, runErr); code != findings.ExitOK || !strings.Contains(out, "\n"+c.line+"\nverdict: clear\n") {
				t.Errorf("exit %d, stdout:\n%s\nwant %q after host: and before verdict:", code, out, c.line)
			}
			_, doc := exitOf(t, dryRunReport(context.Background(), testOptions(t, true), findings.OpTwinCreate, subject, reg, paths,
				dir, fixtureBundleID, nil, nil, c.want))
			if doc.DryRun == nil || doc.DryRun.Follow == nil || *doc.DryRun.Follow != c.want {
				t.Errorf("dry_run %+v, want follow %+v", doc.DryRun, c.want)
			}
			// The reason waypoint is M10's enum's; every other document is M6's.
			if c.want.Reason == findings.FollowReasonWaypoint {
				validateM10Document(t, doc)
			} else {
				validateM6Document(t, doc)
			}
		})
	}
}

// TestDryRunCountsTheLossyRecord's helper half, beside dryRunReport: a create's read line
// counts the read's own counts, and the lossy record's from the bundle the read compiled to.
// Its command half, the provision dry run, runs in internal/cli.
func TestDryRunCountsTheLossyRecord(t *testing.T) {
	const lossyID = "5773b6bba1107076b2cde8283f92494d42b3eab89c5f297ea25f81134fd529f7"
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	// The design-case package's probe login, which the host check requires set as it
	// does SR Linux's.
	t.Setenv("FYLGJA_CHASSISOS_USERNAME", "admin")
	t.Setenv("FYLGJA_CHASSISOS_PASSWORD", "not-the-real-one")
	useClab(t, "inspect-empty.json")
	dir := copyGoldenBundleOf(t, "lossy", "b")
	var out string

	// A create's read line: the read's own counts, and the lossy record's from the bundle
	// the read compiled to.
	c, err := ctm.Load(repoPath("testdata", "ctm", "lossy.json"))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(repoPath("testdata", "psp", "lossy"))
	if err != nil {
		t.Fatal(err)
	}
	read := &readSummary{counts: intent.Summarize(c), packages: intent.DevicesByPackage(c, reg), envelope: c.Envelope}
	follow := findings.DryRunFollow{Reason: findings.FollowReasonPinned}
	out = captureStdout(t, func() {
		err = dryRunReport(context.Background(), testOptions(t, false), findings.OpTwinCreate, &findings.Subject{Branch: c.Envelope.Branch},
			reg, paths, dir, lossyID, read, nil, follow)
	})
	want := "read: 3 devices (chassisos 2, nokia_srlinux 1), 19 interfaces, 3 links, 3 artifacts, " +
		"9 lossy mappings, 3 shared ports (branch lossy-fixture, at 2026-09-19T12:00:00Z, schema fixture)\n"
	if code, _ := exitOf(t, err); code != findings.ExitOK || !strings.Contains(out, "\n"+want) {
		t.Errorf("exit %d, stdout:\n%s\nwant %q", code, out, want)
	}
}
