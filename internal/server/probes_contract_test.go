//go:build contract

package server

import (
	"context"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// The kind is the second source of a request's one list (SC-005, US4's independent test),
// against a real Infrahub, never a fake (D-017): n2-loop written into FylgjaProbe on the
// default branch, then four intent reads of a seeded fylgja-test-* branch on the server's
// path, as the API runs them. With no probe file the snapshot carries the kind's n2-loop;
// with n1-loop's file it carries the file's alone, the kind's replaced; with the probe
// deleted and neither, it carries [] and the read warns of nothing; with an empty file,
// testdata/probes/none.json, it is the snapshot neither filed. Each read's document
// holds no finding, since a read compiles nothing, so no placement is judged against the
// branch's ports. The workflow service is never dialled. The probe is deleted as the test
// goes and again when it ends, and afterwards FylgjaProbe counts 0; the branch is deleted
// when the test ends. The kind must hold no probe when the test starts: the test deletes
// every one it finds there at its end, so it refuses to run over an operator's.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/server -run '^TestProbesFromTheKind$' -v
func TestProbesFromTheKind(t *testing.T) {
	c := contractClient(t)
	if n, err := c.ProbeCount(); err != nil || n != 0 {
		t.Fatalf("the default branch holds %d FylgjaProbe (%v); this test runs on an empty kind, since it deletes every "+
			"probe there", n, err)
	}
	t.Cleanup(func() {
		if n, err := c.DeleteProbes(); err != nil {
			t.Errorf("deleting the probes left on the default branch (%d deleted): %v", n, err)
		} else if n > 0 {
			t.Logf("deleted %d probe(s) left on the default branch", n)
		}
		if n, err := c.ProbeCount(); err != nil || n != 0 {
			t.Errorf("after the test the default branch holds %d FylgjaProbe (%v); want 0", n, err)
		}
	})
	paths := useStateRoot(t)
	useService(t, nil)

	n1, n2 := declaration(t, "n1-loop.json"), declaration(t, "n2-loop.json")
	if err := c.WriteProbes(n2); err != nil {
		t.Fatalf("writing n2-loop on the default branch: %v", err)
	}
	branch := seededBranch(t, c)

	// read is one intent read --out of the branch on the server's path: the snapshot it sent,
	// which must be the one it filed, and its document.
	read := func(which string, pa probesArg) (*snapshot.Snapshot, *findings.Document) {
		t.Helper()
		started := time.Now()
		var frames recordedFrames
		opts := helperServer.newCall(t.Context(), "test", api.Request{Render: api.RenderText}, newFrames(&frames, nil), nil).options()
		code, doc := exitOf(t, runRead(t.Context(), opts,
			&readFlags{branch: branch, out: "snap.json", scope: fixtureScope, scopeGiven: true, probes: pa}))
		if code != findings.ExitOK {
			t.Fatalf("the read %s: exit %d, findings %+v", which, code, doc.Findings)
		}
		if len(doc.Findings) != 0 {
			t.Errorf("the read %s reported %+v; want no finding, no warning among them", which, doc.Findings)
		}
		sent := frames.files()
		if len(sent) != 1 || len(sent[0]) != 1 {
			t.Fatalf("the read %s sent files frames %+v; want one carrying the snapshot alone", which, sent)
		}
		s, err := snapshot.Unmarshal(sent[0][0].Data)
		if err != nil {
			t.Fatalf("the read %s sent a file that is no snapshot: %v", which, err)
		}
		if s.ID != doc.SnapshotID {
			t.Errorf("the read %s sent snapshot %s and named %s", which, s.ID, doc.SnapshotID)
		}
		stored, err := snapshot.NewDirStore(paths.Snapshots).Fetch(context.Background(), s.ID)
		if err != nil || !reflect.DeepEqual(stored.Probes, s.Probes) {
			t.Errorf("the read %s filed %+v (%v); want the snapshot it sent, carrying %+v", which, stored, err, s.Probes)
		}
		t.Logf("the read %s: snapshot %s carrying %d probe(s) in %.1fs", which, s.ID, len(s.Probes),
			time.Since(started).Seconds())
		return s, doc
	}

	fromKind, _ := read("with no file", probesArg{})
	if !reflect.DeepEqual(fromKind.Probes, n2.Probes) {
		t.Errorf("with no file the snapshot carries %+v; want the kind's n2-loop, %+v", fromKind.Probes, n2.Probes)
	}

	fromFile, _ := read("with n1-loop's file", probeFile(t, "n1-loop.json"))
	if !reflect.DeepEqual(fromFile.Probes, n1.Probes) {
		t.Errorf("with n1-loop's file the snapshot carries %+v; want the file's alone, %+v", fromFile.Probes, n1.Probes)
	}

	n, err := c.DeleteProbes()
	if err != nil || n != 1 {
		t.Fatalf("deleting n2-loop: %d deleted (%v); want 1", n, err)
	}
	neither, _ := read("with neither", probesArg{})
	if neither.Probes == nil || len(neither.Probes) != 0 {
		t.Errorf("with neither the snapshot carries %#v; want []", neither.Probes)
	}

	// An empty file declares none: the take is the one with neither, its snapshot the same.
	empty, _ := read("with an empty file", probeFile(t, "none.json"))
	if empty.Probes == nil || len(empty.Probes) != 0 || empty.Version != snapshot.Version {
		t.Errorf("with an empty file the snapshot is %s carrying %#v; want a %s carrying []", empty.Version,
			empty.Probes, snapshot.Version)
	}
	if empty.ID != neither.ID {
		t.Errorf("with an empty file the snapshot is %s; want the one with neither, %s", empty.ID, neither.ID)
	}

	ids := []string{fromKind.ID, fromFile.ID, neither.ID}
	if ids[0] == ids[1] || ids[1] == ids[2] || ids[0] == ids[2] {
		t.Errorf("the three reads' snapshots are %v; want three, each list its own", ids)
	}
	if neither.CTM.Envelope.Branch != branch || fromKind.CTM.Envelope.Branch != branch {
		t.Errorf("the snapshots name branches %s and %s; want %s", fromKind.CTM.Envelope.Branch, neither.CTM.Envelope.Branch, branch)
	}
}

// declaration is a declaration under testdata/probes/, parsed as the server parses a file.
func declaration(t *testing.T, name string) *probe.Declaration {
	t.Helper()
	path := repoPath("testdata", "probes", name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	d, list := probe.Parse(data, path)
	if d == nil {
		t.Fatalf("%s: %+v", name, list)
	}
	return d
}
