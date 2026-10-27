package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// intent read's summary counts what the profiles make of the intent beside what it holds
// (contracts/cli.md): a platform that loses nothing counts two zeros, and the
// lossy design case the record the bundle will carry. From M7 the devices are broken down
// by support package in package id order, a read of one platform in the same shape as a
// mixed one. From 017 the line names the scope the read was made under, and says how many
// cables it could not place when it left any out, which the CTM's fidelity rows count.
// The line runRead prints is taken from the function it calls.
func TestReadSummaryCountsTheLossyRecord(t *testing.T) {
	for _, c := range []struct {
		fixture, pspDir, want string
		// omitted is how many cable rows the read's fidelity list gains.
		omitted int
	}{
		{"three-node.json", "", "wrote snapshot.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"lossy.json", repoPath("testdata", "psp", "lossy"), "wrote snapshot.json: 3 devices (chassisos 2, nokia_srlinux 1), " +
			"16 interfaces, 3 links, 3 artifacts, 9 lossy mappings, 3 shared ports " +
			"(branch lossy-fixture, at 2026-09-19T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"mixed.json", "", "wrote snapshot.json: 3 devices (arista_eos 2, nokia_srlinux 1), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch mixed-fixture, at 2026-09-20T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"three-node.json", "", "wrote snapshot.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports; 1 cable omitted (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 1},
		{"three-node.json", "", "wrote snapshot.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports; 2 cables omitted (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 2},
	} {
		t.Run(fmt.Sprintf("%s/%d omitted", c.fixture, c.omitted), func(t *testing.T) {
			snapshot, err := ctm.Load(repoPath("testdata", "ctm", c.fixture))
			if err != nil {
				t.Fatal(err)
			}
			for i := range c.omitted {
				snapshot.Envelope.Fidelity = append(snapshot.Envelope.Fidelity, ctm.FidelityRow{Disposition: ctm.FidelityOmitted,
					Object: fmt.Sprintf("c-%d", i), Source: "DcimCable", Reason: "other than two ends (3)"})
			}
			reg, err := psp.Load(c.pspDir)
			if err != nil {
				t.Fatal(err)
			}
			if got := readSummaryLine("snapshot.json", snapshot, reg); got != c.want {
				t.Errorf("summary:\n%s\nwant:\n%s", got, c.want)
			}
		})
	}
}

// recordedFrames are an answer's frames as its client reads them, in order.
type recordedFrames struct{ frames []api.Frame }

func (r *recordedFrames) Write(p []byte) (int, error) {
	var f api.Frame
	if err := json.Unmarshal(p, &f); err != nil {
		return 0, err
	}
	r.frames = append(r.frames, f)
	return len(p), nil
}

// files are the files frames' files, a list per frame.
func (r *recordedFrames) files() [][]api.File {
	var out [][]api.File
	for _, f := range r.frames {
		if f.Files != nil {
			out = append(out, f.Files)
		}
	}
	return out
}

// out is the frames' out text, and where the first files frame fell in it: the length of
// the text written before it, or -1 when there is none.
func (r *recordedFrames) out() (text string, filesAt int) {
	var b strings.Builder
	filesAt = -1
	for _, f := range r.frames {
		if f.Files != nil && filesAt < 0 {
			filesAt = b.Len()
		}
		b.WriteString(f.Out)
	}
	return b.String(), filesAt
}

// readOf is intent read of the fixture branch, unpinned, under the fixture's scope, written
// to snap.json, through readFn, observed at observedAt, its text rendered and its frames
// recorded in rec.
func readOf(t *testing.T, rec *recordedFrames, readFn readFunc, observedAt string) error {
	t.Helper()
	opts := helperServer.newCall(context.Background(), "test", api.Request{Render: api.RenderText}, newFrames(rec, nil), nil).options()
	subject := &findings.Subject{Branch: "fylgja-fixture", Out: "snap.json", Scope: "tag:fylgja"}
	return read(context.Background(), opts, subject, readFn, "fylgja-fixture", "", "tag:fylgja", "snap.json", shippedPackages(t),
		observedAt, nil)
}

// intent read --out takes the clean read's snapshot and files it where a create files one,
// then sends it, before the summary line, which ends naming it and its store path; the
// document names it (FR-020; R-09; US4 scenario 2). The file is a snapshot 1 the server's
// own rules accept, and the store's entry is its bytes. A second read, observed later, sends
// a file differing in its two observed_at lines alone and leaves the entry as the first take
// filed it.
func TestReadWritesAndFilesTheSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	const first, later = "2026-10-27T09:00:00.000000Z", "2026-10-27T10:30:00.000000Z"
	reads := 0
	stored := filepath.Join(paths.Snapshots, fixtureSnapshotID+".json")

	var rec recordedFrames
	code, doc := exitOf(t, readOf(t, &rec, fakeRead(t, "three-node.json", nil, &reads), first))
	if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID {
		t.Fatalf("exit %d, snapshot %q, findings %+v; want 0 naming %s", code, doc.SnapshotID, doc.Findings, fixtureSnapshotID)
	}
	validateWithShow(t, currentContract, "018", doc)
	sent := rec.files()
	if len(sent) != 1 || len(sent[0]) != 1 || sent[0][0].Path != "snapshot.json" {
		t.Fatalf("files frames %+v, want one carrying snapshot.json alone", sent)
	}
	file := sent[0][0].Data
	s, err := snapshot.Unmarshal(file)
	if err != nil || s.ID != fixtureSnapshotID || s.ObservedAt != first || s.CTM.Envelope.ObservedAt != first {
		t.Fatalf("the file reads as %+v (%v); want snapshot %s observed at %s", s, err, fixtureSnapshotID, first)
	}
	if entry, err := os.ReadFile(stored); err != nil || !bytes.Equal(entry, file) {
		t.Errorf("the store's entry %s is not the file sent, byte for byte (%v)", stored, err)
	}
	reg := shippedPackages(t)
	text, filesAt := rec.out()
	want := readSummaryLine("snap.json", loadCTM(t, "three-node.json", first), reg) + "; snapshot " + fixtureSnapshotID +
		", stored at " + stored + "\n"
	if text != want || filesAt != 0 {
		t.Errorf("text:\n%s\nwant, after the files frame:\n%s", text, want)
	}

	var again recordedFrames
	if code, doc := exitOf(t, readOf(t, &again, fakeRead(t, "three-node.json", nil, &reads), later)); code != findings.ExitOK ||
		doc.SnapshotID != fixtureSnapshotID {
		t.Fatalf("the second read: exit %d, snapshot %q; want 0 naming %s", code, doc.SnapshotID, fixtureSnapshotID)
	}
	second := again.files()[0][0].Data
	oldLines, newLines := strings.Split(string(file), "\n"), strings.Split(string(second), "\n")
	if len(oldLines) != len(newLines) {
		t.Fatalf("the second file has %d lines, the first %d", len(newLines), len(oldLines))
	}
	var moved []string
	for i := range oldLines {
		if oldLines[i] != newLines[i] {
			moved = append(moved, strings.TrimSpace(newLines[i]))
		}
	}
	if len(moved) != 2 || !strings.HasPrefix(moved[0], `"observed_at": "`+later) || !strings.HasPrefix(moved[1], `"observed_at": "`+later) {
		t.Errorf("the second file differs from the first in %q; want its two observed_at lines alone", moved)
	}
	if entry, err := os.ReadFile(stored); err != nil || !bytes.Equal(entry, file) {
		t.Errorf("the second read changed the store's entry (%v); want the first take's", err)
	}
	if text, _ := again.out(); !strings.HasSuffix(text, "; snapshot "+fixtureSnapshotID+", stored at "+stored+"\n") {
		t.Errorf("the second read's line %q does not end naming the stored snapshot", text)
	}
}

// A read refused, or one that could not run, sends no file, files nothing and names no
// snapshot (FR-020): what is taken is a clean read's.
func TestARefusedReadSendsAndFilesNothing(t *testing.T) {
	refused := findings.List{{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: "tag:fylgja",
		Message: "scope tag:fylgja selects no device on branch fylgja-fixture"}}
	for _, c := range []struct {
		name string
		read readFunc
		code int
	}{
		{"refused", func(context.Context, string, string, string, *psp.Registry, string) (*ctm.CTM, findings.List, error) {
			return nil, refused, nil
		}, findings.ExitRejected},
		{"failed", func(context.Context, string, string, string, *psp.Registry, string) (*ctm.CTM, findings.List, error) {
			return nil, nil, errors.New("Infrahub answered 502")
		}, findings.ExitError},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			var rec recordedFrames
			code, doc := exitOf(t, readOf(t, &rec, c.read, "2026-10-27T09:00:00.000000Z"))
			if code != c.code || doc.SnapshotID != "" {
				t.Errorf("exit %d, snapshot %q; want %d naming none", code, doc.SnapshotID, c.code)
			}
			if sent := rec.files(); len(sent) != 0 {
				t.Errorf("files frames %+v after a %s read", sent, c.name)
			}
			if _, err := os.Stat(paths.Snapshots); !os.IsNotExist(err) {
				t.Errorf("snapshots/ exists after a %s read (%v)", c.name, err)
			}
			validateWithShow(t, currentContract, "018", doc)
		})
	}
}

// An entry under the read's snapshot id that hashes to another is snapshot.id.mismatch, with
// no step, as M1's operations carry none, naming the store path and both ids: the snapshot
// cannot be filed, so none is sent or named, and the entry is left as it was.
func TestAReadOverACorruptSnapshotEntry(t *testing.T) {
	ctx := context.Background()
	paths := useStateRoot(t)
	other, _, _, err := takeSnapshot(ctx, paths, "", loadCTM(t, "lossy.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(paths.Snapshots, fixtureSnapshotID+".json")
	if err := os.Rename(filepath.Join(paths.Snapshots, other.ID+".json"), path); err != nil {
		t.Fatal(err)
	}
	corrupt, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	var rec recordedFrames
	reads := 0
	code, doc := exitOf(t, readOf(t, &rec, fakeRead(t, "three-node.json", nil, &reads), "2026-10-27T10:30:00.000000Z"))
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotIDMismatch, Object: path,
		Message: "store entry " + path + " hashes to " + other.ID + ", not " + fixtureSnapshotID + ", so snapshot " +
			fixtureSnapshotID + " cannot be filed"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.SnapshotID != "" {
		t.Errorf("exit %d, snapshot %q, findings %+v; want 1 with %+v alone", code, doc.SnapshotID, doc.Findings, want)
	}
	if sent := rec.files(); len(sent) != 0 {
		t.Errorf("files frames %+v over a corrupt entry", sent)
	}
	if b, err := os.ReadFile(path); err != nil || !bytes.Equal(b, corrupt) {
		t.Errorf("the corrupt entry was changed (%v)", err)
	}
	validateWithShow(t, currentContract, "018", doc)
}
