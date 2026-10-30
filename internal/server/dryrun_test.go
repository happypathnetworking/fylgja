package server

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
)

// A dry run says nothing of following (019; US1 scenario 1): a create's from a snapshot of
// the branch head, with no at, and twin provision's print no follow: line, the verdict
// straight after the host: line, and their documents carry no dry_run.follow.
// The provision's names no snapshot, so M6's contract, which never required the block,
// still accepts it.
func TestDryRunSaysNothingOfFollowing(t *testing.T) {
	for _, c := range []struct {
		name string
		run  func(t *testing.T, opts *options, paths lab.Paths) error
		m6   bool
	}{
		{"twin create --snapshot --dry-run", func(t *testing.T, opts *options, _ lab.Paths) error {
			return runCreate(context.Background(), opts, &createFlags{snapshot: "snap.json", snapshotGiven: true, dryRun: true},
				fixtureFile(t, nil))
		}, false},
		{"twin provision --dry-run", func(t *testing.T, opts *options, paths lab.Paths) error {
			return dryRunReport(context.Background(), opts, findings.OpTwinProvision, &findings.Subject{Bundle: "bundle"},
				shippedPackages(t), paths, nil, copyGoldenBundle(t, fixtureBundleID), fixtureBundleID, nil)
		}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")

			var err error
			out := captureStdout(t, func() { err = c.run(t, testOptions(t, false), paths) })
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			if strings.Contains(out, "\nfollow:") || !strings.Contains(out, "; twin directory absent\nverdict: clear\n") {
				t.Errorf("stdout:\n%s\nwant no follow: line, and the verdict straight after the host: line", out)
			}

			code, doc := exitOf(t, c.run(t, testOptions(t, true), paths))
			if code != findings.ExitOK || doc.DryRun == nil {
				t.Fatalf("exit %d, dry_run %+v; want 0 and the report", code, doc.DryRun)
			}
			b, err := json.Marshal(doc)
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(b), `"follow`) {
				t.Errorf("the dry run's document names following: %s", b)
			}
			validateWithShow(t, currentContract, "018", doc)
			if c.m6 {
				validateM6Document(t, doc)
			}
		})
	}
}

// A dry run of a probed bundle lists each probe's host among the nodes, naming its format
// where a device names its package and pushing it nothing, and its memory sums the hosts'
// 32 MiB beside the devices' 2048 (016; contracts/cli.md, "016: probes"). Its document
// names each host's probe with psp null and no artifact, which the findings contract
// accepts, and a host whose probe image the host lacks refuses the run.
func TestDryRunListsTheHosts(t *testing.T) {
	src := repoPath("testdata", "golden", "three-node-probed")
	id, err := bundle.IDOfDir(src)
	if err != nil {
		t.Fatal(err)
	}
	run := func(t *testing.T, opts *options, paths lab.Paths) error {
		return dryRunReport(context.Background(), opts, findings.OpTwinProvision, &findings.Subject{Bundle: "bundle"},
			shippedPackages(t), paths, nil, copyGoldenBundleOf(t, "three-node-probed", id), id, nil)
	}
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	clab := useClab(t, "inspect-empty.json")
	clab.images = map[string]bool{"alpine:3.24.2": true}

	out := captureStdout(t, func() { err = run(t, testOptions(t, false), paths) })
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	for _, want := range []string{
		"\n  n1-loop-a  alpine:3.24.2  ping host  32 MiB\n  n1-loop-b  alpine:3.24.2  ping host  32 MiB\n",
		"\nmemory: sum 6208 MiB; host budget unset\n",
		"\nverdict: clear\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("stdout:\n%s\nwant %q", out, want)
		}
	}
	if strings.Contains(out, "n1-loop-a  alpine:3.24.2  ping host  32 MiB  push") {
		t.Errorf("a host is pushed something:\n%s", out)
	}

	code, doc := exitOf(t, run(t, testOptions(t, true), paths))
	if code != findings.ExitOK || doc.DryRun == nil {
		t.Fatalf("exit %d, dry_run %+v; want 0 and the report", code, doc.DryRun)
	}
	hosts := 0
	for _, n := range doc.DryRun.Nodes {
		if n.Probe == nil {
			if n.PSP == nil || *n.PSP != "nokia_srlinux" || n.Artifact == nil {
				t.Errorf("device %+v, want its package and its artifact", n)
			}
			continue
		}
		hosts++
		want := findings.DryRunProbe{Name: "n1-loop", Endpoint: n.Name[len(n.Name)-1:], Format: "ping",
			Package: findings.DryRunPackage{ID: "ping", Source: "embedded"}}
		if *n.Probe != want || n.PSP != nil || n.Artifact != nil || n.MemoryMB != 32 {
			t.Errorf("host %+v (probe %+v), want probe %+v, no package or artifact, and 32 MiB", n, n.Probe, want)
		}
	}
	if hosts != 2 || doc.DryRun.MemorySumMB != 6208 {
		t.Errorf("%d hosts, memory_sum_mb %d; want 2 and 6208", hosts, doc.DryRun.MemorySumMB)
	}
	validateWithShow(t, currentContract, "016", doc)

	t.Run("the probe image absent", func(t *testing.T) {
		clab.images = nil
		code, doc := exitOf(t, run(t, testOptions(t, true), paths))
		if code == findings.ExitOK || doc.DryRun == nil || doc.DryRun.Verdict != findings.VerdictRefused {
			t.Fatalf("exit %d, dry_run %+v; want the run refused", code, doc.DryRun)
		}
		validateWithShow(t, currentContract, "016", doc)
	})
}
