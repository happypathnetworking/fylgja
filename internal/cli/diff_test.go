package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// fylgja twin diff through the command line and the harness's server (020, R-05; FR-011):
// two snapshot files print the step between their bundles, after each side's filed snapshot
// and bundle, exit 0, starting nothing; --json prints the twin.diff document, its two sides
// named and the step its pair, which the current contract holds; a snapshot named by its id
// is sent as one; one file named twice is sent once and the step is unchanged.
func TestTwinDiffPrintsTheStepBetweenTwoSnapshots(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	from, to := wrappedFixture("three-node"), wrappedFixture("three-node-probed")

	code, stdout, stderr := runCommandLine(t, "twin", "diff", "--from", from, "--to", to)
	if code != findings.ExitOK || stderr != "" {
		t.Fatalf("twin diff: exit %d, stderr\n%s\nwant 0 and nothing", code, stderr)
	}
	for _, want := range append(storedLines(paths, fixtureSnapshotID, fixtureBundleID),
		"from: snapshot b9db37f8… (branch fylgja-fixture at 2026-09-08T12:00:00Z)",
		"to: snapshot aef03f5d… (branch fylgja-fixture at 2026-09-08T12:00:00Z)",
		"step snapshot b9db37f8… → snapshot aef03f5d… (c70589c3… → 5222063b…):\n"+
			"  nodes: +n1-loop-a; +n1-loop-b; ~n1 (bootstrap)\n"+
			"  links: +n1-loop-a:eth1 — n1:e1-10; +n1-loop-b:eth1 — n1:e1-11\n"+
			"  artifacts: unchanged\n") {
		if !strings.Contains(stdout, want) {
			t.Errorf("twin diff: stdout\n%s\nlacks %q", stdout, want)
		}
	}

	// The from side by the id the first diff filed it under.
	code, stdout, _ = runCommandLine(t, "twin", "diff", "--from", fixtureSnapshotID, "--to", to, "--json")
	var doc findings.Document
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("twin diff --json: stdout is not one document: %v\n%s", err, stdout)
	}
	if code != findings.ExitOK || doc.Operation != findings.OpTwinDiff || doc.SnapshotFrom != fixtureSnapshotID ||
		doc.BundleFrom != fixtureBundleID || doc.SnapshotTo == "" || doc.BundleTo == "" || doc.Step == nil || doc.Step.Pair == nil {
		t.Fatalf("twin diff --json: exit %d, document %+v; want 0, twin.diff naming both sides and the pair", code, doc)
	}
	var pair struct {
		From, To  string
		Unchanged bool
		Nodes     struct{ Added []string }
	}
	if err := json.Unmarshal(doc.Step.Pair, &pair); err != nil || pair.From != "snapshot b9db37f8…" ||
		pair.To != "snapshot aef03f5d…" || pair.Unchanged || strings.Join(pair.Nodes.Added, ",") != "n1-loop-a,n1-loop-b" {
		t.Errorf("twin diff --json: pair %s (%v); want the two snapshots, the two hosts added", doc.Step.Pair, err)
	}
	validateWithShow(t, currentContract, "020", &doc)

	code, stdout, _ = runCommandLine(t, "twin", "diff", "--from", to, "--to", to)
	if code != findings.ExitOK || !strings.HasSuffix(stdout, "(5222063b… → 5222063b…): unchanged; the two are one bundle\n") {
		t.Errorf("twin diff of one file: exit %d, stdout\n%s\nwant 0 and the step unchanged, one bundle", code, stdout)
	}
}

// A flag not given is the server's operation.failed, --from's first, as twin compile's are;
// a file the client cannot read is its own, before any connection, exit 2.
func TestTwinDiffRefusesWhatItCannotSend(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	missing := filepath.Join(t.TempDir(), "absent.json")
	for _, c := range []struct {
		name string
		args []string
		says string
	}{
		{"no flags", nil, "--from is required"},
		{"no --to", []string{"--from", wrappedFixture("three-node")}, "--to is required"},
		{"an unreadable file", []string{"--from", wrappedFixture("three-node"), "--to", missing}, "reading snapshot: open " + missing},
	} {
		t.Run(c.name, func(t *testing.T) {
			code, stdout, _ := runCommandLine(t, append([]string{"twin", "diff", "--json"}, c.args...)...)
			var doc findings.Document
			if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
				t.Fatalf("stdout is not one document: %v\n%s", err, stdout)
			}
			if code != findings.ExitError || doc.Operation != findings.OpTwinDiff || len(doc.Findings) != 1 ||
				doc.Findings[0].Rule != findings.RuleOperationFailed || !strings.HasPrefix(doc.Findings[0].Message, c.says) {
				t.Errorf("exit %d, document %+v; want 2, operation.failed saying %q", code, doc, c.says)
			}
		})
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Errorf("the unreadable file exists: %v", err)
	}
}
