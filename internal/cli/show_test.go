package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

const (
	showBundleID = "893b6392da4f1de868e74e418d90f3d5982ecc06ffa1dc39a391d717a81997ad"
	showRunID    = "01a0a698-fc78-7cb5-b0f1-a31c8f06d7e9"
	showObserved = "2026-09-16T19:00:00.000000Z"
	// showSnapshotID is the snapshot twinOf's record names, as every create of 018 or later
	// writes one: the live fixture's (CLAUDE.md).
	showSnapshotID = "576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482"
	// noSnapshotNote is what twin show says of a record naming no snapshot (019).
	noSnapshotNote = "the twin's record names no snapshot, so fylgja twin step refuses it; fylgja twin destroy clears it"
)

// showKind is the kind line of a twin of fylgja-fixture from intent or a snapshot (019,
// contracts/cli.md): the snapshot, short, or "none", and in brackets the branch and at, or
// the time twinOf's record was read when at is "".
func showKind(snapshot, at string) string {
	if at != "" {
		return "snapshot " + snapshot + " (branch fylgja-fixture at " + at + ")"
	}
	return "snapshot " + snapshot + " (branch fylgja-fixture, read at " + showObserved + ")"
}

// twinOf is the record of a three-node twin of fylgja-fixture from intent, read at
// showObserved and naming snapshot showSnapshotID; change adjusts it before it is built.
// dcimMapping is the mapping a twin.json 8 record's provenance names when the Infrahub
// reader read the schema library's DCIM (017).
var dcimMapping = wire.Mapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}

// showRead is the record line's last clause for such a record (contracts/cli.md, twin show).
const showRead = "scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9"

// unknownScope is the record line's last clause for a record of twin.json 7 or earlier,
// which names no scope (017).
func unknownScope(version string) string { return "scope unknown (record " + version + ")" }

// noSnapshot is the record line's snapshot for a record naming none (018): "snapshot none"
// for a record of the version this build writes, and "snapshot none (record <version>)" for
// one of 8 or earlier, which names none.
func noSnapshot(version string) string {
	if version == lab.TwinVersion {
		return "snapshot none"
	}
	return "snapshot none (record " + version + ")"
}

// contractProvenance is a record's provenance as a worker of twin.json 7 or earlier wrote
// it, in generic, a record as JSON: the generics contract's version, and no scope or
// mapping, which 017 put in its place.
func contractProvenance(generic map[string]any) {
	p := generic["provenance"].(map[string]any)
	delete(p, "scope")
	delete(p, "mapping")
	p["contract_version"] = "0.2"
}

// unsnapshotted is a record as a worker of twin.json 8 or earlier wrote it, in generic, a
// record as JSON: no snapshot_id at the top level or on a step's sides, which 018 added, and
// no step.loss, which 016 added.
func unsnapshotted(generic map[string]any) {
	unlossed(generic)
	delete(generic, "snapshot_id")
	if step, ok := generic["step"].(map[string]any); ok {
		for _, side := range []string{"from", "to"} {
			delete(step[side].(map[string]any), "snapshot_id")
		}
	}
}

// unlossed is a record as a worker of twin.json 10 or earlier wrote it, in generic, a record
// as JSON: no loss in its step block, which 016 added.
func unlossed(generic map[string]any) {
	if step, ok := generic["step"].(map[string]any); ok {
		delete(step, "loss")
	}
}

func twinOf(t *testing.T, change func(*lab.RecordFields)) wire.TwinRecord {
	t.Helper()
	observed := showObserved
	f := lab.RecordFields{
		BundleID:   showBundleID,
		SnapshotID: showSnapshotID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "41349c3a9c582e5dd44e55d6771f79c2", Scope: "tag:fylgja", Mapping: dcimMapping},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      showRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 16, 19, 1, 2, 0, time.UTC),
	}
	for _, n := range []string{"n1", "n2", "n3"} {
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n,
			Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: fixtureArtifacts[n], Size: 707},
			PushedInS: 0.7})
	}
	if change != nil {
		change(&f)
	}
	rec, err := lab.NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

// writeTwin gives the state root a twin directory holding rec as twin.json.
func writeTwin(t *testing.T, paths lab.Paths, rec wire.TwinRecord) {
	t.Helper()
	if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := lab.WriteRecord(paths.TwinJSON, rec); err != nil {
		t.Fatal(err)
	}
}

// writeM11Twin writes rec for M11's show cases with its step's wait not run. It keeps the
// current version, since a version 4 record named a waypoint, never a stage, and reads with
// no stage from 014 (TestShowRecordsBeforeStages); and a version 6 step's wait is required,
// null until it has run, so each M11 case's step line ends "wait not run", as M12's
// TestShowStepWait shows for that shape.
func writeM11Twin(t *testing.T, paths lab.Paths, rec wire.TwinRecord) {
	t.Helper()
	if rec.Step != nil {
		rec.Step.Wait = nil
	}
	writeTwin(t, paths, rec)
}

// stateRootListing is every path under root with its size, to show twin show writes nothing.
func stateRootListing(t *testing.T, root string) []string {
	t.Helper()
	var list []string
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		list = append(list, fmt.Sprintf("%s %s %d", p, info.ModTime(), info.Size()))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return list
}

// showOutput is what twin show put in front of the operator: its exit status, the text on
// stdout and stderr (the findings as main renders them included), and the JSON document.
type showOutput struct {
	code   int
	stdout string
	stderr string
	doc    *findings.Document
}

// showWith runs twin show in text and in JSON against the containerlab recording and the
// state root paths, with svc as the workflow service in read-only mode (nil: dialling fails
// the test). Every output is checked for the credentials set to sentinel values, the JSON
// against M7's schema (its nodes name their package and their artifact), and the state root
// for any change.
func showWith(t *testing.T, paths lab.Paths, recording string, svc *fakeService) showOutput {
	t.Helper()
	if svc != nil {
		svc.readOnly = t
	}
	useService(t, svc)
	return showDialled(t, paths, recording)
}

// showDialled is showWith with dialService already set by the caller.
func showDialled(t *testing.T, paths lab.Paths, recording string) showOutput {
	t.Helper()
	t.Setenv(intent.EnvToken, sentinel)
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", sentinel)
	t.Setenv(lab.EnvTemporalAddress, "")
	useClab(t, recording)
	before := stateRootListing(t, paths.Root)

	var out showOutput
	var err error
	out.stderr = captureStderr(t, func() {
		out.stdout = captureStdout(t, func() { err = runShow(context.Background(), &options{}) })
	})
	var textDoc *findings.Document
	out.code, textDoc = exitOf(t, err)
	out.stderr += renderText(t, textDoc)

	jsonOut := captureStdout(t, func() { err = runShow(context.Background(), &options{asJSON: true}) })
	if jsonOut != "" {
		t.Errorf("--json printed on stdout:\n%s", jsonOut)
	}
	_, out.doc = exitOf(t, err)
	// Every show document is the current contract's (019's kinds), and 018's and 017's as
	// validateM10Document holds them; one whose record names no stage, no state (twin.json
	// 4, M11's record.state and record.step) and no snapshot is held to M7's contract too,
	// which it still satisfies with its kind as M7 wrote it.
	validateM10Document(t, out.doc)
	if r := out.doc.Show.Record; (r == nil || (r.Stage == nil && r.State == "")) && !namesSnapshot(t, out.doc) {
		validateM7Document(t, out.doc)
	}
	// No kind line says pinned, frozen or following (019, SC-005), and no note does.
	for _, line := range append(strings.Split(out.stdout, "\n"), out.doc.Show.Notes...) {
		if !strings.HasPrefix(line, "kind: ") && !slices.Contains(out.doc.Show.Notes, line) {
			continue
		}
		for _, word := range []string{"pinned", "frozen", "following"} {
			if strings.Contains(line, word) {
				t.Errorf("a kind line or note says %q: %q", word, line)
			}
		}
	}
	b, jerr := json.Marshal(out.doc)
	if jerr != nil {
		t.Fatal(jerr)
	}
	for what, s := range map[string]string{"stdout": out.stdout, "stderr": out.stderr, "the document": string(b)} {
		if strings.Contains(s, sentinel) {
			t.Errorf("%s carries a credential:\n%s", what, s)
		}
	}
	if after := stateRootListing(t, paths.Root); !slices.Equal(before, after) {
		t.Errorf("the state root changed:\n  %v\nto\n  %v", before, after)
	}
	return out
}

func lines(l ...string) string { return strings.Join(l, "\n") + "\n" }

// threeNodes is the twin line with each node, the support package it was provisioned with
// and the artifact twin.json records for it, by name and checksum (M5
// contracts/cli.md, twin show).
const threeNodes = "twin: lab fylgja present (3 nodes); twin directory present\n" +
	"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config 597f6263eb7e0b539679b3956270876f\n" +
	"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config 5ac21560015ad6bb1e881358115d0b7a\n" +
	"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config e93df96400ddbada7daa1a0777d9d3e3\n"

// threeBareNodes is the twin line with no twin.json to name what the nodes were pushed.
const threeBareNodes = "twin: lab fylgja present (3 nodes); twin directory present\n" +
	"  n1  clab-fylgja-n1  running  172.20.20.2\n" +
	"  n2  clab-fylgja-n2  running  172.20.20.3\n" +
	"  n3  clab-fylgja-n3  running  172.20.20.4\n"

const recordLine = "record: branch fylgja-fixture, snapshot " + showSnapshotID + ", bundle_id " + showBundleID + ", schema 41349c3a9c582e5dd44e55d6771f79c2, " + showRead + "\n"

const provisionedLine = "  provisioned by run fylgja-provision " + showRunID + " (source intent), worker 0.1.0-dev, recorded 2026-09-16T19:01:02Z, 3 nodes\n"

const bestEffortNote = "reproducing the twin with --at " + showObserved + " is best-effort"

func wantShow(t *testing.T, out showOutput, stdout, kind string, notes ...string) {
	t.Helper()
	if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK || out.doc.Operation != findings.OpTwinShow {
		t.Errorf("exit %d, document %+v; want 0, twin.show, ok", out.code, out.doc)
	}
	if out.stdout != stdout {
		t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, stdout)
	}
	if s := out.doc.Show; s == nil || s.Kind != kind || !slices.Equal(s.Notes, notes) {
		t.Errorf("show %+v; want kind %s, notes %q", s, kind, notes)
	}
}

// Scenario 1: no lab, no twin directory.
func TestShowNoTwin(t *testing.T) {
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-empty.json", &fakeService{})
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none", "in flight: none"),
		findings.ShowKindNone, "no twin")
	if s := out.doc.Show; s.Record != nil || s.Service != findings.ShowServiceOK ||
		s.Host.LabPresent || s.Host.TwinDirPresent || s.Host.Phrase != "" {
		t.Errorf("show %+v, want nothing but the empty host", s)
	}
	if out.stderr != "" {
		t.Errorf("stderr:\n%s\nwant nothing", out.stderr)
	}
}

// US5 scenario 1: a twin from --branch with no --at is kind snapshot, its line naming the
// snapshot its record names and, in brackets, its branch and the time it was read, with
// the best-effort note; twin show asks the workflow service for the runs in flight alone.
func TestShowSnapshotReadAt(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, nil))
	svc := &fakeService{}
	out := showWith(t, paths, "inspect-three.json", svc)
	wantShow(t, out, threeNodes+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines("kind: snapshot 576933ec… (branch fylgja-fixture, read at "+showObserved+")", "in flight: none"),
		findings.ShowKindSnapshot, bestEffortNote)
	if r := out.doc.Show.Record; r == nil || r.BundleID != showBundleID || r.ObservedAt == nil || *r.ObservedAt != showObserved ||
		r.SnapshotID == nil || *r.SnapshotID != showSnapshotID || r.Run.RunID != showRunID || r.Nodes != 3 || r.WorkerVersion != "0.1.0-dev" {
		t.Errorf("record %+v", r)
	}
	n := out.doc.Show.Host.Nodes
	if len(n) != 3 || n[0].Name != "n1" || n[0].Container != "clab-fylgja-n1" || n[0].State != "running" || n[0].MgmtIPv4 != "172.20.20.2" ||
		n[0].Artifact == nil || *n[0].Artifact != (findings.ShowArtifact{Name: "device-config", Checksum: fixtureArtifacts["n1"]}) {
		t.Errorf("nodes %+v, want n1 first with the artifact its record names", n)
	}
	if out.stderr != "" {
		t.Errorf("stderr:\n%s\nwant nothing", out.stderr)
	}
	if want := []string{"InFlight", "InFlight"}; !slices.Equal(svc.reads, want) {
		t.Errorf("reads %v, want the runs in flight once per run, text then JSON", svc.reads)
	}
}

// US5 scenario 2: a twin from --branch --at is kind snapshot, its line naming the snapshot
// and, in brackets, its branch at T, verbatim, with no best-effort statement.
func TestShowSnapshotAt(t *testing.T) {
	const at = "2026-09-16T14:00:00Z"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) { f.Provenance.At = at }))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	wantShow(t, out, threeNodes+
		"record: branch fylgja-fixture at "+at+", snapshot "+showSnapshotID+", bundle_id "+showBundleID+", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: "+showKind("576933ec…", at), "in flight: none"),
		findings.ShowKindSnapshot)
	if r := out.doc.Show.Record; r == nil || r.At != at {
		t.Errorf("record %+v, want at %s verbatim", r, at)
	}
}

// US5 scenario 2: a twin created from a stage is kind snapshot at the stage's at and keeps
// ", stage <ref>" after the bracket, and its record line names the stage, and the JSON
// record carries it; a record naming none, written by 014 as an explicit null or by an
// earlier worker with no key, shows as TestShowSnapshotAt, or, naming no snapshot, as
// snapshot none (contracts/cli.md, specs/014-proposed-change-stages).
func TestShowSnapshotOfAStage(t *testing.T) {
	const at = "2026-09-20T10:00:00.123456+00:00"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = at
		f.Stage = &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "fylgja-fixture"}, Label: "cabled",
			Description: "the leaf cabled", AtSource: "written"}
	}))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := showKind("576933ec…", at) + ", stage fylgja-fixture/cabled"
	wantShow(t, out, threeNodes+
		"record: branch fylgja-fixture at "+at+" (stage fylgja-fixture/cabled, at written), snapshot "+showSnapshotID+", bundle_id "+showBundleID+
		", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: "+kind, "in flight: none"),
		findings.ShowKindSnapshot)
	want := findings.ShowStage{ProposedChange: findings.StageChangeRef{ID: "pc-1", Branch: "fylgja-fixture"}, Label: "cabled",
		Description: "the leaf cabled", AtSource: "written"}
	if r := out.doc.Show.Record; r == nil || r.At != at || r.Stage == nil || *r.Stage != want {
		t.Errorf("record %+v, want at %s and stage %+v", r, at, want)
	}

	// The same twin with no stage, from a record of this build's version and from a version
	// 2 one, which names no snapshot, is TestShowSnapshotAt's, line for line, or its
	// snapshot none.
	const pinnedAt = "2026-09-16T14:00:00Z"
	for label, record := range map[string]func() []byte{
		"this version, stage null": func() []byte {
			b, err := json.Marshal(twinOf(t, func(f *lab.RecordFields) { f.Provenance.At = pinnedAt }))
			if err != nil {
				t.Fatal(err)
			}
			return b
		},
		"version 2": func() []byte {
			var generic map[string]any
			b, err := json.Marshal(twinOf(t, func(f *lab.RecordFields) { f.Provenance.At = pinnedAt }))
			if err == nil {
				err = json.Unmarshal(b, &generic)
			}
			if err != nil {
				t.Fatal(err)
			}
			generic["twin_version"] = "2"
			unsnapshotted(generic)
			contractProvenance(generic)
			delete(generic, "stage")
			delete(generic, "rehearsal")
			if b, err = json.Marshal(generic); err != nil {
				t.Fatal(err)
			}
			return b
		},
	} {
		t.Run(label, func(t *testing.T) {
			paths := useStateRoot(t)
			if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(paths.TwinJSON, record(), 0o644); err != nil {
				t.Fatal(err)
			}
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			read, snapshot, kind, notes := showRead, "snapshot "+showSnapshotID, lines("kind: "+showKind("576933ec…", pinnedAt)), []string(nil)
			if label == "version 2" {
				read, snapshot = unknownScope("2"), noSnapshot("2")
				kind, notes = lines("kind: "+showKind("none", pinnedAt), "  "+noSnapshotNote), []string{noSnapshotNote}
			}
			wantShow(t, out, threeNodes+
				"record: branch fylgja-fixture at "+pinnedAt+", "+snapshot+", bundle_id "+showBundleID+", schema 41349c3a9c582e5dd44e55d6771f79c2, "+read+"\n"+
				"  intent read at "+showObserved+"\n"+provisionedLine+kind+lines("in flight: none"),
				findings.ShowKindSnapshot, notes...)
			if b, err := json.Marshal(out.doc); err != nil || strings.Contains(string(b), `"stage":{`) {
				t.Errorf("a record naming no stage shows one (%v): %s", err, b)
			}
		})
	}
}

// The record line ends with the record's provenance (017; contracts/cli.md, twin show): an 8
// record's scope and the mapping that read it, its JSON record carrying both; a 7 record's
// scope unknown, naming the version, its JSON record carrying neither. Both documents are
// the current contract's, and the 7 record, a rehearsal's baseline as a 015 worker wrote it,
// still shows its rehearsal.
func TestShowRecordNamesItsScope(t *testing.T) {
	rec := twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
		f.Rehearsal = &wire.RehearsalRef{WorkflowID: wire.RehearseWorkflowID, RunID: "r0"}
	})
	head := func(version string) string {
		snapshot := "snapshot " + showSnapshotID
		if version != lab.TwinVersion {
			snapshot = noSnapshot(version)
		}
		return "record: branch fylgja-fixture at " + stepFromAt + " (stage fylgja-fixture/seeded, at given), " + snapshot +
			", bundle_id " + showBundleID + ", schema 41349c3a9c582e5dd44e55d6771f79c2, "
	}
	for _, c := range []struct {
		version, line string
		mapping       *findings.ShowMapping
	}{
		{"8", head(lab.TwinVersion) + showRead,
			&findings.ShowMapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}},
		{"7", head("7") + "scope unknown (record 7)", nil},
	} {
		t.Run("twin.json "+c.version, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, rec)
			if c.version == "7" {
				raw, err := json.Marshal(rec)
				if err != nil {
					t.Fatal(err)
				}
				var generic map[string]any
				if err := json.Unmarshal(raw, &generic); err != nil {
					t.Fatal(err)
				}
				generic["twin_version"] = "7"
				unsnapshotted(generic)
				contractProvenance(generic)
				if raw, err = json.Marshal(generic); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
					t.Fatal(err)
				}
			}
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			if !strings.Contains(out.stdout, "\n"+c.line+"\n") {
				t.Errorf("stdout:\n%s\nwant the record line %q", out.stdout, c.line)
			}
			r := out.doc.Show.Record
			if r == nil {
				t.Fatal("the document carries no record")
			}
			wantScope := ""
			if c.mapping != nil {
				wantScope = "tag:fylgja"
			}
			if r.Scope != wantScope || (r.Mapping == nil) != (c.mapping == nil) || (r.Mapping != nil && *r.Mapping != *c.mapping) {
				t.Errorf("record scope %q, mapping %+v; want %q and %+v", r.Scope, r.Mapping, wantScope, c.mapping)
			}
			if r.Rehearsal == nil || r.Rehearsal.RunID != "r0" {
				t.Errorf("record rehearsal %+v, want run r0 as written", r.Rehearsal)
			}
			validateM10Document(t, out.doc)
			b, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(b), "contract_version") {
				t.Errorf("the document names a contract version: %s", b)
			}
		})
	}
}

// A record of 8 or later (here the 9 this build writes) whose scope is not tag:<name>, edited
// by hand since no build of this tree writes one, names no scope a read can be made under:
// twin show prints its scope unknown, naming the value and the record's version, as it
// prints a 7's, and its JSON record carries neither scope nor mapping, so the document stays
// the show contract's (T097). One whose mapping twin.json 8 or later
// cannot hold, a reader's name not of its form or a model or version left empty, prints its
// reader unknown, naming each field it fails, and its JSON record carries neither too, since
// the contract shows the scope only beside the mapping (T106).
func TestShowTreatsAnUnreadableScopeAsUnknown(t *testing.T) {
	rec := twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
	})
	head := "record: branch fylgja-fixture at " + stepFromAt + " (stage fylgja-fixture/seeded, at given), snapshot " + showSnapshotID +
		", bundle_id " + showBundleID + ", schema 41349c3a9c582e5dd44e55d6771f79c2, "
	// An edit sets the provenance's scope, or a field of its mapping, to value.
	type edit struct{ field, value string }
	type unreadable struct {
		name  string
		edits []edit
		want  string
	}
	var cases []unreadable
	for _, scope := range []string{"", "fylgja", "tag:"} {
		cases = append(cases, unreadable{fmt.Sprintf("scope %q", scope), []edit{{"scope", scope}},
			`scope unknown (record 11 names scope "` + scope + `", not tag:<name>)`})
	}
	cases = append(cases, []unreadable{
		{"mapping reader \"Infrahub DCIM\"", []edit{{"reader", "Infrahub DCIM"}},
			`scope tag:fylgja, read by an unknown reader (record 11 names mapping reader "Infrahub DCIM")`},
		{"an empty mapping model", []edit{{"model", ""}},
			`scope tag:fylgja, read by an unknown reader (record 11 names mapping model "")`},
		{"an empty mapping version", []edit{{"version", ""}},
			`scope tag:fylgja, read by an unknown reader (record 11 names mapping version "")`},
		{"a reader and a model", []edit{{"reader", "-dcim"}, {"model", ""}},
			`scope tag:fylgja, read by an unknown reader (record 11 names mapping reader "-dcim", model "")`},
	}...)
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, rec)
			raw, err := os.ReadFile(paths.TwinJSON)
			if err != nil {
				t.Fatal(err)
			}
			var generic map[string]any
			if err := json.Unmarshal(raw, &generic); err != nil {
				t.Fatal(err)
			}
			provenance := generic["provenance"].(map[string]any)
			for _, e := range c.edits {
				if e.field == "scope" {
					provenance["scope"] = e.value
				} else {
					provenance["mapping"].(map[string]any)[e.field] = e.value
				}
			}
			if raw, err = json.Marshal(generic); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
				t.Fatal(err)
			}
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			line := head + c.want
			if !strings.Contains(out.stdout, "\n"+line+"\n") {
				t.Errorf("stdout:\n%s\nwant the record line %q", out.stdout, line)
			}
			r := out.doc.Show.Record
			if r == nil {
				t.Fatal("the document carries no record")
			}
			if r.Scope != "" || r.Mapping != nil {
				t.Errorf("record scope %q, mapping %+v; want neither", r.Scope, r.Mapping)
			}
			validateM10Document(t, out.doc)
		})
	}
}

// A twin of two platforms: each node line names the package that node was provisioned
// with, and the JSON node carries the id the record already holds. That line
// is how an operator tells the nodes of a mixed twin apart, and twin.json gains no key
// for it.
func TestShowNamesEachNodesOwnPackage(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		f.Nodes[1].PSP = &wire.PSPRef{ID: "arista_eos", Source: "embedded"}
		f.Nodes[1].Image = "ceos:4.32.0.2F"
	}))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	mixed := strings.Replace(threeNodes,
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  ",
		"  n2  clab-fylgja-n2  running  172.20.20.3  arista_eos  ", 1)
	wantShow(t, out, mixed+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines("kind: "+showKind("576933ec…", ""), "in flight: none"),
		findings.ShowKindSnapshot, bestEffortNote)
	var got []string
	for _, n := range out.doc.Show.Host.Nodes {
		if n.PSP == nil {
			t.Fatalf("node %s carries no package; the record names one for every node", n.Name)
		}
		got = append(got, n.Name+" "+*n.PSP)
	}
	if want := []string{"n1 nokia_srlinux", "n2 arista_eos", "n3 nokia_srlinux"}; !slices.Equal(got, want) {
		t.Errorf("the document's nodes %v, want %v", got, want)
	}
}

// A twin of the probed golden (016): each probe's host is listed among the nodes, naming its
// format where a device names its package and its probe and endpoint where a device names its
// artifact, from twin.json 11's nodes[].probe; the JSON node carries psp and artifact null,
// which the show contract accepts unmoved. The lab is inspect-three.json with the two
// hosts' linux containers added, as containerlab reports a node of that kind.
func TestShowListsAProbesHosts(t *testing.T) {
	paths := useStateRoot(t)
	ping := wire.PSPRef{ID: "ping", Source: "embedded"}
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		for i, endpoint := range []string{"a", "b"} {
			f.Nodes = append(f.Nodes, wire.TwinNode{Name: "n1-loop-" + endpoint, Container: "clab-fylgja-n1-loop-" + endpoint,
				Image: "alpine:3.24.2", Probe: &wire.TwinProbe{Name: "n1-loop", Endpoint: endpoint, Format: "ping", Package: ping},
				MgmtIPv4: fmt.Sprintf("172.20.20.%d", 5+i), ReadyAfterS: 1.2})
		}
	}))
	out := showWith(t, paths, "inspect-three-probed.json", &fakeService{})
	probed := strings.Replace(threeNodes, "present (3 nodes)", "present (5 nodes)", 1)
	probed = strings.Replace(probed, "\n  n2  ", "\n"+
		"  n1-loop-a  clab-fylgja-n1-loop-a  running  172.20.20.5  ping host  probe n1-loop a\n"+
		"  n1-loop-b  clab-fylgja-n1-loop-b  running  172.20.20.6  ping host  probe n1-loop b\n"+
		"  n2  ", 1)
	wantShow(t, out, probed+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		strings.Replace(provisionedLine, "3 nodes", "5 nodes", 1)+lines("kind: "+showKind("576933ec…", ""), "in flight: none"),
		findings.ShowKindSnapshot, bestEffortNote)
	for _, n := range out.doc.Show.Host.Nodes {
		host := strings.HasPrefix(n.Name, "n1-loop-")
		if host != (n.PSP == nil) || host != (n.Artifact == nil) {
			t.Errorf("node %s carries package %v and artifact %v; want both null on a host alone", n.Name, n.PSP, n.Artifact)
		}
	}
	validateM10Document(t, out.doc)
}

// US5 scenario 6: from a bundle, with the read time unknown and snapshot none on the record
// line, as before 019.
func TestShowFromBundle(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) { f.Source, f.ObservedAt, f.SnapshotID = wire.SourceBundle, nil, "" }))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	wantShow(t, out, threeNodes+strings.Replace(recordLine, "snapshot "+showSnapshotID, "snapshot none", 1)+
		// contracts/cli.md's words, literal: built from lab.ObservedAtUnknown this line once
		// agreed with a show that printed "unknown:" twice.
		"  intent read: unknown: provisioned from an existing bundle; no read took place\n"+
		strings.Replace(provisionedLine, "source intent", "source bundle", 1)+
		lines("kind: from a bundle", "in flight: none"),
		findings.ShowKindFromBundle, "provisioned from a bundle; read time unknown")
	b, err := json.Marshal(out.doc.Show.Record)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"observed_at":null`) {
		t.Errorf("record %s, want observed_at null", b)
	}
}

// Scenario 6: an orphan, named with M3's phrase and the remedy.
func TestShowOrphan(t *testing.T) {
	const phrase = "an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml"
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-one-orphan.json", &fakeService{})
	wantShow(t, out, lines(
		"twin: lab fylgja present (1 node); twin directory absent; "+phrase+"; fylgja twin destroy clears it",
		"  n1  clab-fylgja-n1  running  172.20.20.2",
		"kind: none",
		"in flight: none"),
		findings.ShowKindNone, phrase+"; fylgja twin destroy clears it")
	if s := out.doc.Show; s.Host.Phrase != phrase || s.Record != nil {
		t.Errorf("show %+v, want the phrase and no record", s)
	}
	// No record names the orphan's node, so it names neither an artifact nor
	// a support package, and the text line carries neither. The document says
	// so as explicit nulls, not by leaving the keys out: the contract promises
	// `{name, checksum}` or `null` and an id or `null`, and the schema alone would accept
	// either.
	if n := out.doc.Show.Host.Nodes; len(n) != 1 || n[0].Artifact != nil || n[0].PSP != nil {
		t.Errorf("nodes %+v, want the orphan's node with no artifact and no package", n)
	}
	b, err := json.Marshal(out.doc)
	if err != nil {
		t.Fatal(err)
	}
	var raw struct {
		Show struct {
			Host struct {
				Nodes []map[string]json.RawMessage `json:"nodes"`
			} `json:"host"`
		} `json:"show"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		t.Fatal(err)
	}
	n := raw.Show.Host.Nodes
	if len(n) != 1 {
		t.Fatalf("nodes %v, want one", n)
	}
	for _, key := range []string{"artifact", "psp"} {
		if v, ok := n[0][key]; !ok || string(v) != "null" {
			t.Errorf("the orphan's node marshals %s as %s (present %v), want an explicit null", key, v, ok)
		}
	}
}

// A readable twin.json whose lab was removed by hand (M3's shape b) is no twin: kind none,
// named with M3's phrase and remedy, the record still reported, no runtime-state statement,
// and no create advice, which host.twin.present would refuse (D-014).
func TestShowRecordWithoutLab(t *testing.T) {
	const phrase = "the twin of branch fylgja-fixture, bundle_id " + showBundleID +
		", provisioned by run fylgja-provision " + showRunID + ", 3 nodes recorded, but lab fylgja is absent"
	host := lines("twin: lab fylgja absent; twin directory present; " + phrase + "; fylgja twin destroy clears it")
	record := recordLine + "  intent read at " + showObserved + "; reproducing it with --at that instant is best-effort\n" + provisionedLine
	check := func(t *testing.T, out showOutput) {
		t.Helper()
		s := out.doc.Show
		if s.Host.Phrase != phrase || s.Host.LabPresent || !s.Host.TwinDirPresent || s.Record == nil || s.Record.BundleID != showBundleID {
			t.Errorf("show %+v, want the phrase, the lab absent and the record", s)
		}
		for _, text := range []string{out.stdout, strings.Join(s.Notes, "\n")} {
			for _, advice := range []string{"fylgja twin create", "runtime state"} {
				if strings.Contains(text, advice) {
					t.Errorf("says %q for a record without its lab:\n%s", advice, text)
				}
			}
		}
	}

	t.Run("without a Schedule", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		out := showWith(t, paths, "inspect-empty.json", &fakeService{})
		wantShow(t, out, host+record+lines("kind: none", "in flight: none"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it")
		check(t, out)
	})

}

// A stage's record whose lab is gone is M3's shape b, unchanged: kind none with M3's
// phrase and remedy, and no snapshot kind line. The record still names its stage, on the
// record line and in the JSON, which 014's show.schema.json validates.
func TestShowStageRecordWithoutLab(t *testing.T) {
	const at = "2026-09-20T10:00:00.123456+00:00"
	const phrase = "the twin of branch fylgja-fixture at " + at + ", bundle_id " + showBundleID +
		", provisioned by run fylgja-provision " + showRunID + ", 3 nodes recorded, but lab fylgja is absent"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = at
		f.Stage = &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "fylgja-fixture"}, Label: "cabled",
			Description: "the leaf cabled", AtSource: "written"}
	}))
	out := showWith(t, paths, "inspect-empty.json", &fakeService{})
	wantShow(t, out, lines("twin: lab fylgja absent; twin directory present; "+phrase+"; fylgja twin destroy clears it")+
		"record: branch fylgja-fixture at "+at+" (stage fylgja-fixture/cabled, at written), snapshot "+showSnapshotID+", bundle_id "+showBundleID+
		", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: none", "in flight: none"),
		findings.ShowKindNone, phrase+"; fylgja twin destroy clears it")

	s := out.doc.Show
	if s.Host.Phrase != phrase || s.Host.LabPresent || !s.Host.TwinDirPresent {
		t.Errorf("host %+v, want M3's phrase with the lab absent and the twin directory present", s.Host)
	}
	want := findings.ShowStage{ProposedChange: findings.StageChangeRef{ID: "pc-1", Branch: "fylgja-fixture"}, Label: "cabled",
		Description: "the leaf cabled", AtSource: "written"}
	if r := s.Record; r == nil || r.At != at || r.BundleID != showBundleID || r.Stage == nil || *r.Stage != want {
		t.Errorf("record %+v, want at %s and stage %+v", r, at, want)
	}
	for _, text := range []string{out.stdout, strings.Join(s.Notes, "\n")} {
		for _, not := range []string{"snapshot 576933ec…", "fylgja twin create", "runtime state"} {
			if strings.Contains(text, not) {
				t.Errorf("says %q for a stage's record without its lab:\n%s", not, text)
			}
		}
	}
}

// Scenario 7: runs in flight, each with its step: the operator's runs alone (019).
func TestShowRunsInFlight(t *testing.T) {
	paths := useStateRoot(t)
	svc := &fakeService{inFlight: []provision.RunInFlight{
		{WorkflowID: provision.WorkflowProvision, RunID: "r-p", Step: findings.StepDeploy},
		{WorkflowID: provision.WorkflowDestroy, RunID: "r-d", Step: findings.StepTeardown},
	}}
	out := showWith(t, paths, "inspect-empty.json", svc)
	// The provisioning run at deploy holds the host (TestShowProvisionInFlight).
	const holds = "run fylgja-provision r-p is at step deploy, and the host holds its work"
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none; "+holds,
		"in flight:",
		"  run fylgja-provision r-p at step deploy",
		"  run fylgja-destroy r-d at step teardown"),
		findings.ShowKindNone, holds)
	f := out.doc.Show.InFlight
	if len(f) != 2 || f[0].Step != findings.StepDeploy || f[1].Step != findings.StepTeardown {
		t.Errorf("in flight %+v", f)
	}
}

// An operator's create or provision that has reached the host: the lab and twin directory with
// no twin.json are that run's work, not an orphan left by a run cut short, so twin show names
// the run and gives neither M3's remedy, which would cancel it, nor create advice, which would
// be refused. Before the run touches the host, an orphan beside it is still
// named with M3's phrase and remedy: its host check will refuse it.
func TestShowProvisionInFlight(t *testing.T) {
	const deployPhrase = "an orphan: no twin.json records it (a run cut short before it recorded the twin); " +
		"deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml"
	inFlight := func(step string) []provision.RunInFlight {
		return []provision.RunInFlight{{WorkflowID: provision.WorkflowProvision, RunID: "r-p", Step: step}}
	}
	twinDir := func(t *testing.T, paths lab.Paths) {
		t.Helper()
		if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	quiet := func(t *testing.T, out showOutput) {
		t.Helper()
		for _, text := range []string{out.stdout, strings.Join(out.doc.Show.Notes, "\n")} {
			for _, advice := range []string{"orphan", "fylgja twin destroy clears it", "fylgja twin create"} {
				if strings.Contains(text, advice) {
					t.Errorf("says %q while a provisioning run holds the host:\n%s", advice, text)
				}
			}
		}
	}
	const holds = "run fylgja-provision r-p is at step deploy, and the host holds its work"

	t.Run("at deploy, a lab and a twin directory with no twin.json", func(t *testing.T) {
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-three.json", &fakeService{inFlight: inFlight(findings.StepDeploy)})
		wantShow(t, out, threeBareNodes+lines("kind: none; "+holds, "in flight: run fylgja-provision r-p at step deploy"),
			findings.ShowKindNone, holds)
		quiet(t, out)
		// The block's host is M3's inspection as it stands; only the text's reading of it changes.
		if s := out.doc.Show; s.Host.Phrase != deployPhrase || !s.Host.LabPresent || !s.Host.TwinDirPresent || s.Record != nil ||
			len(s.InFlight) != 1 || s.InFlight[0].Step != findings.StepDeploy {
			t.Errorf("show %+v, want M3's phrase in the host block, no record, the run in flight", s)
		}
		if out.stderr != "" {
			t.Errorf("stderr:\n%s\nwant nothing", out.stderr)
		}
	})

	t.Run("at readiness", func(t *testing.T) {
		const holds = "run fylgja-provision r-p is at step readiness, and the host holds its work"
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-three.json", &fakeService{inFlight: inFlight(findings.StepReadiness)})
		wantShow(t, out, threeBareNodes+lines("kind: none; "+holds, "in flight: run fylgja-provision r-p at step readiness"),
			findings.ShowKindNone, holds)
		quiet(t, out)
	})

	// M5: the push step touches the host as deploy and readiness do.
	t.Run("at push", func(t *testing.T) {
		const holds = "run fylgja-provision r-p is at step push, and the host holds its work"
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-three.json", &fakeService{inFlight: inFlight(findings.StepPush)})
		wantShow(t, out, threeBareNodes+lines("kind: none; "+holds, "in flight: run fylgja-provision r-p at step push"),
			findings.ShowKindNone, holds)
		quiet(t, out)
	})

	t.Run("at unstage, the lab gone and the twin directory left", func(t *testing.T) {
		const holds = "run fylgja-provision r-p is at step unstage, and the host holds its work"
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-empty.json", &fakeService{inFlight: inFlight(findings.StepUnstage)})
		wantShow(t, out, lines("twin: lab fylgja absent; twin directory present", "kind: none; "+holds,
			"in flight: run fylgja-provision r-p at step unstage"),
			findings.ShowKindNone, holds)
		quiet(t, out)
	})

	t.Run("at host_check, beside an orphan", func(t *testing.T) {
		const phrase = "an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml"
		paths := useStateRoot(t)
		out := showWith(t, paths, "inspect-one-orphan.json", &fakeService{inFlight: inFlight(findings.StepHostCheck)})
		wantShow(t, out, lines(
			"twin: lab fylgja present (1 node); twin directory absent; "+phrase+"; fylgja twin destroy clears it",
			"  n1  clab-fylgja-n1  running  172.20.20.2",
			"kind: none",
			"in flight: run fylgja-provision r-p at step host_check"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it")
	})
}

// US5 scenario 5: the service unreachable: the host and the record, the runs in flight
// unknown, nothing of following, exit 0 with the warning — whether the dial or the read
// fails.
func TestShowServiceUnreachable(t *testing.T) {
	const want = "the workflow service at localhost:7233 did not answer within 5s: whether a run is in flight is unknown"
	const unknown = "in flight: unknown (workflow service unreachable at localhost:7233)"
	check := func(t *testing.T, out showOutput) {
		t.Helper()
		wantShow(t, out, threeNodes+recordLine+
			"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
			provisionedLine+lines("kind: "+showKind("576933ec…", "")+"; "+unknown, "in flight: unknown"),
			findings.ShowKindSnapshot, bestEffortNote, unknown)
		if s := out.doc.Show; s.Service != findings.ShowServiceUnreachable || s.InFlight != nil || s.Record == nil {
			t.Errorf("show %+v, want service unreachable, the record and no runs", s)
		}
		wantFinding := findings.Finding{Severity: findings.Warning, Rule: findings.RuleShowServiceUnreachable, Object: "localhost:7233", Message: want}
		if len(out.doc.Findings) != 1 || out.doc.Findings[0] != wantFinding {
			t.Errorf("findings %+v, want %+v", out.doc.Findings, wantFinding)
		}
		if !strings.Contains(out.stderr, "warning show.service.unreachable localhost:7233: "+want) {
			t.Errorf("stderr:\n%s\nwant the warning", out.stderr)
		}
		b, err := json.Marshal(out.doc)
		if err != nil {
			t.Fatal(err)
		}
		for _, text := range []string{out.stdout, out.stderr, string(b)} {
			if strings.Contains(text, "follow") {
				t.Errorf("says something of following:\n%s", text)
			}
		}
	}
	refused := &provision.UnreachableError{Address: "localhost:7233", Err: errors.New("connection refused")}

	t.Run("the read", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		check(t, showWith(t, paths, "inspect-three.json", &fakeService{readErr: refused}))
	})
	t.Run("the runs in flight, failing after some were listed", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		check(t, showWith(t, paths, "inspect-three.json", &fakeService{
			inFlight: []provision.RunInFlight{{WorkflowID: provision.WorkflowProvision, RunID: "r-p", Step: "deploy"}},
			failRead: "InFlight", failReadErr: refused}))
	})
	t.Run("the dial", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(context.Context) (provision.Service, error) { return nil, refused }
		check(t, showDialled(t, paths, "inspect-three.json"))
	})
}

// failingClab is containerlab that runs and fails.
type failingClab struct{}

func (failingClab) Run(context.Context, []string, ...string) ([]byte, []byte, int, error) {
	return nil, []byte("permission denied"), 1, nil
}

// Scenario 12: containerlab that cannot inspect the host is exit 2, operation.failed, and
// the service is never asked.
func TestShowClabFailure(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	dryRunRunner = failingClab{}

	var err error
	stdout := captureStdout(t, func() {
		captureStderr(t, func() { err = runShow(context.Background(), &options{}) })
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		!strings.Contains(doc.Findings[0].Message, "permission denied") || doc.Show != nil {
		t.Errorf("exit %d, document %+v; want 2 with operation.failed and no show block", code, doc)
	}
	if stdout != "" {
		t.Errorf("stdout:\n%s\nwant nothing reported", stdout)
	}
	validateM4Document(t, doc)
}

// Scenario 13: a service that does not answer within the budget is reported unreachable.
func TestShowServiceBudget(t *testing.T) {
	if showServiceBudget != provision.ShowServiceBudget {
		t.Fatalf("showServiceBudget = %s, want provision.ShowServiceBudget %s", showServiceBudget, provision.ShowServiceBudget)
	}
	saved := showServiceBudget
	t.Cleanup(func() { showServiceBudget = saved })
	showServiceBudget = 50 * time.Millisecond

	paths := useStateRoot(t)
	start := time.Now()
	out := showWith(t, paths, "inspect-empty.json", &fakeService{readBlocks: true})
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Errorf("twin show took %s against a 50ms budget, twice", elapsed)
	}
	if s := out.doc.Show; s.Service != findings.ShowServiceUnreachable || len(out.doc.Findings) != 1 ||
		out.doc.Findings[0].Message != "the workflow service at localhost:7233 did not answer within 50ms: whether a run is in flight is unknown" {
		t.Errorf("show %+v, findings %+v; want unreachable after no answer within 50ms", s, out.doc.Findings)
	}
}

// The step of contracts/cli.md's twin show examples, on the three-node twin of twinOf:
// from fylgja-fixture/seeded (showBundleID) to fylgja-fixture/cabled, containerlab restarting n1 for a link added between
// n1 and n2, and pushing n1 (artifact, restarted) and n2 (artifact, bootstrap); n3 is left
// alone.
const (
	stepShowRunID = "01a2b3c4-0000-7000-8000-000000000002"
	stepFromAt    = "2026-09-28T15:00:01.123456+00:00"
	stepToAt      = "2026-09-28T15:20:44.000000+00:00"
	stepEnded     = "2026-10-02T09:15:41Z"
)

var stepToID = strings.Repeat("ee291b0f", 8)

// stepToSnapshotID is the snapshot fylgja-fixture/cabled's bundle was compiled from.
var stepToSnapshotID = strings.Repeat("9c2d01e7", 8)

// stepAfter is each node's artifact checksum at fylgja-fixture/cabled: n3's does not move.
var stepAfter = map[string]string{"n1": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3", "n2": "7a9b03de7a9b03de7a9b03de7a9b03de", "n3": fixtureArtifacts["n3"]}

// showStage is the stage label of the proposed change pc-1 on the fixture's branch, its at
// given (014): the stage a twin is created from or steps to in these cases.
func showStage(label string) *wire.StageRef {
	return &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "fylgja-fixture"}, Label: label,
		Description: "the " + label + " stage", AtSource: "given"}
}

// seededTwin is the create's record of fylgja-fixture/seeded.
func seededTwin(t *testing.T) wire.TwinRecord {
	return twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
	})
}

// showStepTarget is the step's target bundle id, pinned at at, as the twin directory holds it,
// each node's artifact checksum from sums, and the three nodes as containerlab reports them
// after the step.
func showStepTarget(id, at string, sums map[string]string) (*lab.StagedTarget, []wire.LabNode) {
	staged := &lab.StagedTarget{BundleID: id,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: at, SchemaHash: "41349c3a9c582e5dd44e55d6771f79c2", Scope: "tag:fylgja", Mapping: dcimMapping},
		PSP:        map[string]wire.PSPRef{}, Artifacts: map[string]*wire.TwinArtifact{}}
	var nodes []wire.LabNode
	for i, n := range []string{"n1", "n2", "n3"} {
		staged.PSP[n] = wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}
		staged.Artifacts[n] = &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: sums[n], Size: 861}
		nodes = append(nodes, wire.LabNode{Name: n, Container: "clab-fylgja-" + n, Image: "ghcr.io/nokia/srlinux:24.7.1",
			State: "running", MgmtIPv4: fmt.Sprintf("172.20.20.%d", i+2)})
	}
	return staged, nodes
}

// steppedTwin is the record the step leaves, the step's fields changed by change first.
func steppedTwin(t *testing.T, change func(f *lab.StepFields)) wire.TwinRecord {
	t.Helper()
	took := func(s float64) *float64 { return &s }
	staged, nodes := showStepTarget(stepToID, stepToAt, stepAfter)
	f := lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Stage: showStage("seeded"), SnapshotID: showSnapshotID, BundleID: showBundleID, At: stepFromAt},
		To:         wire.StepSide{Stage: showStage("cabled"), SnapshotID: stepToSnapshotID, BundleID: stepToID, At: stepToAt},
		ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: stepShowRunID, Version: "0.1.0-dev",
		Plan: wire.ReconcilePlan{Restarted: []string{"n1"}, LinksAdded: []string{"n1:e1-3 -- n2:e1-3"},
			Reasons: map[string]string{"n1": "added link"}},
		Declared:         map[string]string{"n1": "live", "n2": "live", "n3": "live"},
		ReconcileStarted: true, ReconcileTookS: took(3.9),
		ReadyAfter: []wire.ReadinessResult{{Node: "n1", ReadyAfterS: 54.8}},
		Pushed: []wire.StepPush{
			{Node: "n1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.6)},
			{Node: "n2", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.4)},
		},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: stepEnded, RecordedAt: time.Date(2026, 10, 2, 9, 15, 41, 0, time.UTC),
		Nodes: nodes, Staged: staged,
	}
	if change != nil {
		change(&f)
	}
	rec, err := lab.NewStepRecord(seededTwin(t), f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

// divergeAtPush makes the step stop at its push: n1's refused, n2's landed.
func divergeAtPush(f *lab.StepFields) {
	var l findings.List
	l.AddStep(findings.Rejection, findings.StepPush, findings.RulePushRefused, "n1", "node n1 refused artifact device-config")
	l.AddStep(findings.Rejection, findings.StepPush, findings.RuleStepDiverged, stepShowRunID, "the step stopped")
	f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, l
	f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushRefused, findings.RulePushRefused, nil
}

// steppedShowStep is twin show --json's record.step for steppedTwin(t, nil), written out
// from the step block that record keeps: the sides, the run, the restarted node, each push
// with its reasons, outcome and time, each phase's duration, the whole from started_at to
// ended_at (71s), and both clocks.
func steppedShowStep() findings.ShowStep {
	took := func(s float64) *float64 { return &s }
	side := func(label, snapshot, id, at string) findings.StepSideBlock {
		return findings.StepSideBlock{Stage: &findings.ShowStage{ProposedChange: findings.StageChangeRef{ID: "pc-1",
			Branch: "fylgja-fixture"}, Label: label, Description: "the " + label + " stage", AtSource: "given"},
			SnapshotID: snapshot, BundleID: id, At: at}
	}
	return findings.ShowStep{
		Outcome:   wire.StepStepped,
		From:      side("seeded", showSnapshotID, showBundleID, stepFromAt),
		To:        side("cabled", stepToSnapshotID, stepToID, stepToAt),
		Run:       findings.ShowRef{WorkflowID: "fylgja-step", RunID: stepShowRunID},
		Restarted: []string{"n1"},
		Pushed: []findings.StepPushedEntry{
			{Node: "n1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.6)},
			{Node: "n2", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.4)},
		},
		Timings: &findings.StepTimingsBlock{ReconcileS: took(3.9), Readiness: map[string]float64{"n1": 54.8},
			Push: map[string]float64{"n1": 1.6, "n2": 2.4}, WholeS: 71},
		StartedAt: "2026-10-02T09:14:30Z",
		EndedAt:   stepEnded,
	}
}

// wantShowStep holds the JSON record's step block, whole and as --json writes it, to want:
// the text line reads the record directly, so the two could otherwise disagree.
func wantShowStep(t *testing.T, r *findings.ShowRecord, want findings.ShowStep) {
	t.Helper()
	if r == nil || r.Step == nil {
		t.Errorf("record %+v; want a step block", r)
		return
	}
	got, err := json.Marshal(r.Step)
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(b) {
		t.Errorf("record.step\n got %s\nwant %s", got, b)
	}
}

// US5 scenario 3: a stepped twin is kind snapshot, naming the target's snapshot, at and
// stage, and says which step took it there; the record block gains the step's line; every node shows the artifact of
// the bundle it holds, the target's; and the JSON record carries state and step
// (contracts/cli.md, twin show).
func TestShowSteppedRecord(t *testing.T) {
	paths := useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, nil))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "snapshot 9c2d01e7… (branch fylgja-fixture at " + stepToAt + "), stage fylgja-fixture/cabled (stepped from " +
		"fylgja-fixture/seeded by run fylgja-step " + stepShowRunID + ", ended " + stepEnded + ")"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+stepAfter["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+stepAfter["n3"],
		"record: branch fylgja-fixture at "+stepToAt+" (stage fylgja-fixture/cabled, at given), snapshot "+stepToSnapshotID+", bundle_id "+stepToID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead,
		"  intent read at 2026-10-02T09:14:01.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  stepped from fylgja-fixture/seeded by run fylgja-step "+stepShowRunID+", ended "+stepEnded+
			"; reconcile 3.9s (restart n1); readiness n1 54.8s; push n1 1.6s, n2 2.4s; wait not run",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindSnapshot)
	r := out.doc.Show.Record
	if r == nil || r.State != wire.StateReady || r.Step == nil || r.Step.Outcome != wire.StepStepped || r.BundleID != stepToID ||
		!slices.Equal(r.Step.Restarted, []string{"n1"}) || r.Step.Phase != "" || r.Step.Run.RunID != stepShowRunID ||
		r.Step.From.Stage == nil || r.Step.From.Stage.Label != "seeded" || len(r.Step.Pushed) != 2 {
		t.Errorf("record %+v (step %+v)", r, r.Step)
	}
	unwaited := steppedShowStep()
	unwaited.WaitKnown = true
	wantShowStep(t, r, unwaited)

	// An unchanged step is shown as stepped, and its line says nothing was applied.
	paths = useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, func(f *lab.StepFields) {
		f.Outcome, f.Plan, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter, f.Pushed = wire.StepUnchanged,
			wire.ReconcilePlan{}, false, nil, nil, nil
	}))
	out = showWith(t, paths, "inspect-three.json", &fakeService{})
	if want := "  stepped from fylgja-fixture/seeded by run fylgja-step " + stepShowRunID + ", ended " + stepEnded +
		"; unchanged: nothing reconciled, awaited or pushed; wait not run\n"; !strings.Contains(out.stdout, want) ||
		out.doc.Show.Kind != findings.ShowKindSnapshot || out.doc.Show.Record.Step.Outcome != wire.StepUnchanged {
		t.Errorf("an unchanged step:\n%s", out.stdout)
	}
}

// A twin stepped twice is shown by its second step alone: the kind line and the record's
// step line say it was stepped from fylgja-fixture/cabled by the second run, and nothing of the first step
// is shown.
func TestShowTwiceSteppedRecord(t *testing.T) {
	const (
		runB    = "01a2b3c4-0000-7000-8000-000000000003"
		thirdAt = "2026-09-28T15:41:07.500000+00:00"
		endedB  = "2026-10-02T09:26:50Z"
	)
	thirdID, thirdSnapshot := strings.Repeat("6b1d07c2", 8), strings.Repeat("2b7e90c1", 8)
	// Each node's artifact checksum at fylgja-fixture/third-link: n1's does not move from fylgja-fixture/cabled.
	later := map[string]string{"n1": stepAfter["n1"], "n2": "2d3c5e8a2d3c5e8a2d3c5e8a2d3c5e8a", "n3": "3b8f61c03b8f61c03b8f61c03b8f61c0"}
	took := func(s float64) *float64 { return &s }
	staged, nodes := showStepTarget(thirdID, thirdAt, later)
	rec, err := lab.NewStepRecord(steppedTwin(t, nil), lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Stage: showStage("cabled"), SnapshotID: stepToSnapshotID, BundleID: stepToID, At: stepToAt},
		To:         wire.StepSide{Stage: showStage("third-link"), SnapshotID: thirdSnapshot, BundleID: thirdID, At: thirdAt},
		ObservedAt: "2026-10-02T09:25:30.000000Z", RunID: runB, Version: "0.1.0-dev", AllowRestart: true,
		Plan: wire.ReconcilePlan{Restarted: []string{"n2"}, LinksAdded: []string{"n2:e1-4 -- n3:e1-4"},
			Reasons: map[string]string{"n2": "added link"}},
		Declared:         map[string]string{"n1": "live", "n2": "live", "n3": "live"},
		ReconcileStarted: true, ReconcileTookS: took(4.2),
		ReadyAfter: []wire.ReadinessResult{{Node: "n2", ReadyAfterS: 50.1}},
		Pushed: []wire.StepPush{
			{Node: "n2", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.1)},
			{Node: "n3", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(0.8)},
		},
		StartedAt: "2026-10-02T09:25:41Z", EndedAt: endedB, RecordedAt: time.Date(2026, 10, 2, 9, 26, 50, 0, time.UTC),
		Nodes: nodes, Staged: staged,
	})
	if err != nil {
		t.Fatal(err)
	}
	paths := useStateRoot(t)
	writeM11Twin(t, paths, rec)
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "snapshot 2b7e90c1… (branch fylgja-fixture at " + thirdAt + "), stage fylgja-fixture/third-link (stepped from " +
		"fylgja-fixture/cabled by run fylgja-step " + runB + ", ended " + endedB + ")"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+later["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+later["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+later["n3"],
		"record: branch fylgja-fixture at "+thirdAt+" (stage fylgja-fixture/third-link, at given), snapshot "+thirdSnapshot+", bundle_id "+thirdID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead,
		"  intent read at 2026-10-02T09:25:30.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded "+endedB+", 3 nodes",
		"  stepped from fylgja-fixture/cabled by run fylgja-step "+runB+", ended "+endedB+
			"; reconcile 4.2s (restart n2); readiness n2 50.1s; push n2 1.1s, n3 0.8s; wait not run",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindSnapshot)
	if strings.Contains(out.stdout+out.stderr, stepShowRunID) {
		t.Errorf("twin show names the first step's run %s:\n%s", stepShowRunID, out.stdout)
	}
	if r := out.doc.Show.Record; r == nil || r.Step == nil || r.Step.Run.RunID != runB || r.Step.From.Stage == nil ||
		r.Step.From.Stage.Label != "cabled" || !slices.Equal(r.Step.Restarted, []string{"n2"}) {
		t.Errorf("record %+v; want the second step's block, from fylgja-fixture/cabled", r)
	}
}

// A step whose reconcile recreated one node and created another names both lifecycles on
// the record's step line, and never a node re-cabled live; the JSON's step.restarted holds
// every node the reconcile restarted, recreated or created (contracts/cli.md, twin
// show).
func TestShowStepThatRecreatesAndCreates(t *testing.T) {
	took := func(s float64) *float64 { return &s }
	// fylgja-fixture/seeded ran n1 and n2; fylgja-fixture/cabled adds n3, cabled to n1, and changes n2's image.
	prev := twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
		f.Nodes = f.Nodes[:2]
	})
	staged, nodes := showStepTarget(stepToID, stepToAt, stepAfter)
	rec, err := lab.NewStepRecord(prev, lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Stage: showStage("seeded"), SnapshotID: showSnapshotID, BundleID: showBundleID, At: stepFromAt},
		To:         wire.StepSide{Stage: showStage("cabled"), SnapshotID: stepToSnapshotID, BundleID: stepToID, At: stepToAt},
		ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: stepShowRunID, Version: "0.1.0-dev", AllowRestart: true,
		Plan: wire.ReconcilePlan{Recreated: []string{"n2"}, Added: []string{"n3"}, LinksAdded: []string{"n1:e1-3 -- n3:e1-3"},
			Reasons: map[string]string{"n2": "image changed"}},
		Declared:         map[string]string{"n1": "live", "n2": "live"},
		ReconcileStarted: true, ReconcileTookS: took(20.3),
		ReadyAfter: []wire.ReadinessResult{{Node: "n2", ReadyAfterS: 14.1}, {Node: "n3", ReadyAfterS: 31.3}},
		Pushed: []wire.StepPush{
			{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(0.9)},
			{Node: "n2", Reasons: []string{"artifact", "recreated"}, Outcome: wire.PushLanded, TookS: took(1.6)},
			{Node: "n3", Reasons: []string{"artifact", "created"}, Outcome: wire.PushLanded, TookS: took(1.2)},
		},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: stepEnded, RecordedAt: time.Date(2026, 10, 2, 9, 15, 41, 0, time.UTC),
		Nodes: nodes, Staged: staged,
	})
	if err != nil {
		t.Fatal(err)
	}
	paths := useStateRoot(t)
	writeM11Twin(t, paths, rec)
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "snapshot 9c2d01e7… (branch fylgja-fixture at " + stepToAt + "), stage fylgja-fixture/cabled (stepped from " +
		"fylgja-fixture/seeded by run fylgja-step " + stepShowRunID + ", ended " + stepEnded + ")"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+stepAfter["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+stepAfter["n3"],
		"record: branch fylgja-fixture at "+stepToAt+" (stage fylgja-fixture/cabled, at given), snapshot "+stepToSnapshotID+", bundle_id "+stepToID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead,
		"  intent read at 2026-10-02T09:14:01.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  stepped from fylgja-fixture/seeded by run fylgja-step "+stepShowRunID+", ended "+stepEnded+
			"; reconcile 20.3s (recreate n2, create n3); readiness n2 14.1s, n3 31.3s; push n1 0.9s, n2 1.6s, n3 1.2s; wait not run",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindSnapshot)
	if r := out.doc.Show.Record; r == nil || r.Step == nil || !slices.Equal(r.Step.Restarted, []string{"n2", "n3"}) {
		t.Errorf("record %+v; want step.restarted [n2 n3], the recreated node and the created one", r)
	}
}

// A diverged twin is kind diverged: the kind line names the target, the run, the phase, the
// nodes landed and not and where the twin is, with twin destroy as the remedy and no create
// advice; the record block says where the step stopped; a node the step left on its
// baseline shows no artifact, a landed one the target's, an untouched one the previous; and
// the host block is M3's.
func TestShowDivergedRecord(t *testing.T) {
	paths := useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, divergeAtPush))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "diverged towards stage fylgja-fixture/cabled (bundle ee291b0f…): run fylgja-step " + stepShowRunID +
		" stopped at phase push; landed: n2; not landed: n1 (push.refused); the twin is at stage fylgja-fixture/seeded (bundle 893b6392…); " +
		"fylgja twin destroy clears it"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux",
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+fixtureArtifacts["n3"],
		"record: branch fylgja-fixture at "+stepFromAt+" (stage fylgja-fixture/seeded, at given), snapshot "+showSnapshotID+", bundle_id "+showBundleID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead,
		"  intent read at "+showObserved,
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  diverged: step run fylgja-step "+stepShowRunID+" towards fylgja-fixture/cabled (bundle ee291b0f…) stopped at phase push, ended "+
			stepEnded+"; landed n2; not landed n1 (push.refused); wait not run",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindDiverged, kind)
	if strings.Contains(out.stdout, "twin create") || strings.Contains(out.stdout, "following") {
		t.Errorf("a diverged twin is given create advice or names following:\n%s", out.stdout)
	}
	r := out.doc.Show.Record
	if r == nil || r.State != wire.StateDiverged || r.Step == nil || r.Step.Phase != findings.StepPush || r.BundleID != showBundleID {
		t.Errorf("record %+v (step %+v)", r, r.Step)
	}
	// The refused push carries its rule and no time, and the push timings name the landed
	// node alone.
	want := steppedShowStep()
	want.Outcome, want.Phase = wire.StepDiverged, findings.StepPush
	want.Pushed[0].Outcome, want.Pushed[0].Rule, want.Pushed[0].TookS = wire.PushRefused, findings.RulePushRefused, nil
	want.Timings.Push = map[string]float64{"n2": 2.4}
	want.WaitKnown = true
	wantShowStep(t, r, want)
	if n := out.doc.Show.Host.Nodes; len(n) != 3 || n[0].Artifact != nil || n[1].Artifact == nil || n[1].Artifact.Checksum != stepAfter["n2"] {
		t.Errorf("nodes %+v; want n1 with no artifact and n2 with the target's", n)
	}
}

// Every other record shape the step workflow writes reads back through twin show, as
// lab.NewStepRecord builds it: a step diverged at reconcile before
// anything was applied (its stage failed, so every node is on the previous bundle and
// nothing landed), diverged at reconcile after the apply began and at readiness (the
// restarted n1 holding nothing and showing no artifact), and cancelled during its push (n1's
// push cut by the cancellation, n2's landed). Each kind line and record line names its
// phase, what landed and what did not; the JSON record carries the state and the phase.
func TestShowEveryDivergedShape(t *testing.T) {
	before, after := fixtureArtifacts, stepAfter
	divergedAt := func(phase, rule, step string) func(f *lab.StepFields) {
		return func(f *lab.StepFields) {
			var l findings.List
			l.AddStep(findings.Rejection, step, rule, stepShowRunID, "the phase failed")
			l.AddStep(findings.Rejection, phase, findings.RuleStepDiverged, stepShowRunID, "the step stopped")
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, phase, l
			for i := range f.Pushed {
				f.Pushed[i].Outcome, f.Pushed[i].TookS = wire.PushNotAttempted, nil
			}
		}
	}
	for _, c := range []struct {
		name   string
		change func(f *lab.StepFields)
		phase  string
		// landed and notLanded are the two lists as the kind line words them.
		landed, notLanded string
		// artifacts is each node's checksum on its line, "" for none.
		artifacts map[string]string
	}{
		{name: "diverged at reconcile from the stage", phase: findings.StepReconcile, landed: "none", notLanded: "n1, n2",
			artifacts: map[string]string{"n1": before["n1"], "n2": before["n2"], "n3": before["n3"]},
			change: func(f *lab.StepFields) {
				divergedAt(findings.StepReconcile, findings.RuleStageFailed, findings.StepStage)(f)
				f.Staged, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter = nil, false, nil, nil
			}},
		{name: "diverged at reconcile from the apply", phase: findings.StepReconcile, landed: "none", notLanded: "n1, n2",
			artifacts: map[string]string{"n1": "", "n2": before["n2"], "n3": before["n3"]},
			change: func(f *lab.StepFields) {
				divergedAt(findings.StepReconcile, findings.RuleDeployFailed, findings.StepReconcile)(f)
				f.ReconcileTookS, f.ReadyAfter = nil, nil
			}},
		{name: "diverged at readiness", phase: findings.StepReadiness, landed: "none", notLanded: "n1, n2",
			artifacts: map[string]string{"n1": "", "n2": before["n2"], "n3": before["n3"]},
			change: func(f *lab.StepFields) {
				divergedAt(findings.StepReadiness, findings.RuleReadinessTimeout, findings.StepReadiness)(f)
				f.ReadyAfter = nil
			}},
		{name: "cancelled after its stage", phase: findings.StepPush, landed: "n2", notLanded: "n1 (run.cancelled)",
			artifacts: map[string]string{"n1": "", "n2": after["n2"], "n3": before["n3"]},
			change: func(f *lab.StepFields) {
				var l findings.List
				l.AddStep(findings.Rejection, findings.StepPush, findings.RuleRunCancelled, stepShowRunID, "the run was cancelled")
				l.AddStep(findings.Rejection, findings.StepPush, findings.RuleStepDiverged, stepShowRunID, "the step stopped")
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, l
				f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushFailed, findings.RuleRunCancelled, nil
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeM11Twin(t, paths, steppedTwin(t, c.change))
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			kind := "diverged towards stage fylgja-fixture/cabled (bundle ee291b0f…): run fylgja-step " + stepShowRunID +
				" stopped at phase " + c.phase + "; landed: " + c.landed + "; not landed: " + c.notLanded +
				"; the twin is at stage fylgja-fixture/seeded (bundle 893b6392…); fylgja twin destroy clears it"
			node := func(n string, i int) string {
				line := fmt.Sprintf("  %s  clab-fylgja-%s  running  172.20.20.%d  nokia_srlinux", n, n, i+2)
				if sum := c.artifacts[n]; sum != "" {
					line += "  device-config " + sum
				}
				return line
			}
			wantShow(t, out, lines(
				"twin: lab fylgja present (3 nodes); twin directory present",
				node("n1", 0), node("n2", 1), node("n3", 2),
				"record: branch fylgja-fixture at "+stepFromAt+" (stage fylgja-fixture/seeded, at given), snapshot "+showSnapshotID+", bundle_id "+showBundleID+
					", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead,
				"  intent read at "+showObserved,
				"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
				"  diverged: step run fylgja-step "+stepShowRunID+" towards fylgja-fixture/cabled (bundle ee291b0f…) stopped at phase "+c.phase+
					", ended "+stepEnded+"; landed "+c.landed+"; not landed "+c.notLanded+"; wait not run",
				"kind: "+kind,
				"in flight: none"),
				findings.ShowKindDiverged, kind)
			r := out.doc.Show.Record
			if r == nil || r.State != wire.StateDiverged || r.Step == nil || r.Step.Outcome != wire.StepDiverged ||
				r.Step.Phase != c.phase || r.BundleID != showBundleID {
				t.Fatalf("record %+v (step %+v); want diverged at %s, at the previous bundle", r, r.Step, c.phase)
			}
			for i, n := range out.doc.Show.Host.Nodes {
				want := c.artifacts[n.Name]
				if (want == "") != (n.Artifact == nil) || (n.Artifact != nil && n.Artifact.Checksum != want) {
					t.Errorf("node %d %s carries artifact %+v; want checksum %q", i, n.Name, n.Artifact, want)
				}
			}
		})
	}
}

// A step run that has reached the host (its stage through its record) is named after the
// kind line with the side it steps towards, by its name (019): stage <ref> or snapshot
// <short>; before its stage it is only listed in flight (contracts/cli.md).
func TestShowStepInFlight(t *testing.T) {
	kind := showKind("576933ec…", stepFromAt) + ", stage fylgja-fixture/seeded"
	// Before its stage (start, inspect, host_check, and compare, the plan's second lock) a
	// step run has touched nothing on the host, and is listed under in flight: alone.
	// So is one at observe, its wait after the record: the record is already written, so the
	// kind line needs no clause.
	before := []string{findings.StepStart, findings.StepInspect, findings.StepHostCheck, findings.StepCompare,
		findings.StepObserve}
	for _, towards := range []string{"stage fylgja-fixture/cabled", "snapshot 9c2d01e7…"} {
		for _, step := range []string{findings.StepStage, findings.StepReconcile, findings.StepReadiness, findings.StepPush,
			findings.StepRecord, findings.StepStart, findings.StepInspect, findings.StepHostCheck, findings.StepCompare,
			findings.StepObserve} {
			t.Run(towards+" "+step, func(t *testing.T) {
				paths := useStateRoot(t)
				writeTwin(t, paths, seededTwin(t))
				svc := &fakeService{inFlight: []provision.RunInFlight{
					{WorkflowID: "fylgja-step", RunID: stepShowRunID, Step: step, Towards: towards}}}
				out := showWith(t, paths, "inspect-three.json", svc)
				running := "run fylgja-step " + stepShowRunID + " is at step " + step + ", stepping towards " + towards
				line, notes := kind+"; "+running, []string{running}
				if slices.Contains(before, step) {
					line, notes = kind, nil
				}
				want := "kind: " + line + "\nin flight: run fylgja-step " + stepShowRunID + " at step " + step + "\n"
				if !strings.HasSuffix(out.stdout, want) {
					t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, want)
				}
				if s := out.doc.Show; s.Kind != findings.ShowKindSnapshot || !slices.Equal(s.Notes, notes) ||
					len(s.InFlight) != 1 || s.InFlight[0].WorkflowID != "fylgja-step" || s.InFlight[0].Step != step {
					t.Errorf("show %+v", s)
				}
			})
		}
	}
	// A step run whose target the service could not read from its input (Towards "") is
	// still named at the host, without the clause naming where it steps.
	t.Run("a target that cannot be read", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, seededTwin(t))
		svc := &fakeService{inFlight: []provision.RunInFlight{
			{WorkflowID: "fylgja-step", RunID: stepShowRunID, Step: findings.StepReconcile}}}
		out := showWith(t, paths, "inspect-three.json", svc)
		running := "run fylgja-step " + stepShowRunID + " is at step " + findings.StepReconcile
		want := "kind: " + kind + "; " + running + "\nin flight: run fylgja-step " + stepShowRunID + " at step " +
			findings.StepReconcile + "\n"
		if !strings.HasSuffix(out.stdout, want) || strings.Contains(out.stdout, "stepping towards") {
			t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, want)
		}
		if s := out.doc.Show; s.Kind != findings.ShowKindSnapshot || !slices.Equal(s.Notes, []string{running}) {
			t.Errorf("show %+v; want kind snapshot, notes %q", s, []string{running})
		}
	})
}

// A record written before 014 that named M10's waypoint — version 3, written before M11,
// and versions 4 and 5 that have not stepped — reads with no stage (lab.ReadRecord), so it
// is shown as a twin naming no stage and no snapshot, line for line, and its JSON carries no stage; only
// the 4 and 5 records' JSON carries their state (014, research R-11). A version 5 record
// that stepped, or diverged, names each stage of its step as the waypoint it was, as twin
// step's refusal of such a record says, never "none": the step line's sides and a diverged
// twin's kind line, its target and where the twin is. One that stepped shows snapshot none
// with no stage and no step on its kind line, and the JSON's stages stay null.
func TestShowRecordsBeforeStages(t *testing.T) {
	kind := showKind("none", stepFromAt)
	for _, version := range []string{"3", "4", "5"} {
		want := threeNodes +
			"record: branch fylgja-fixture at " + stepFromAt + ", " + noSnapshot(version) + ", bundle_id " + showBundleID +
			", schema 41349c3a9c582e5dd44e55d6771f79c2, " + unknownScope(version) + "\n" +
			"  intent read at " + showObserved + "\n" + provisionedLine + lines("kind: "+kind, "  "+noSnapshotNote, "in flight: none")
		t.Run("version "+version, func(t *testing.T) {
			paths := useStateRoot(t)
			raw, err := json.Marshal(seededTwin(t))
			if err != nil {
				t.Fatal(err)
			}
			// NewRecord writes the current version, 8 since 017; a create's 4 or 5 differs
			// from it by the version, by the contract version in place of the scope and the
			// mapping, by M10's waypoint in place of the stage and by having no rehearsal,
			// since step is null in each.
			var generic map[string]any
			if err := json.Unmarshal(raw, &generic); err != nil {
				t.Fatal(err)
			}
			generic["twin_version"] = version
			unsnapshotted(generic)
			contractProvenance(generic)
			delete(generic, "stage")
			delete(generic, "rehearsal")
			generic["waypoint"] = map[string]any{"series": "demo", "sequence": 1, "description": "cut 1", "at_source": "given"}
			if version == "3" {
				delete(generic, "state")
				delete(generic, "step")
				for _, n := range generic["nodes"].([]any) {
					delete(n.(map[string]any), "holds")
				}
			}
			if raw, err = json.Marshal(generic); err != nil {
				t.Fatal(err)
			}
			if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
				t.Fatal(err)
			}
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			wantShow(t, out, want, findings.ShowKindSnapshot, noSnapshotNote)
			b, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			if hasState := strings.Contains(string(b), `"state":"ready"`); hasState != (version != "3") || strings.Contains(string(b), `"step":{`) ||
				strings.Contains(string(b), `"stage":{`) || strings.Contains(string(b), "waypoint") {
				t.Errorf("version %s's document: %s", version, b)
			}
		})
	}

	record := func(at, id string) string {
		return "record: branch fylgja-fixture at " + at + ", " + noSnapshot("5") + ", bundle_id " + id + ", schema 41349c3a9c582e5dd44e55d6771f79c2, " + unknownScope("5")
	}
	provisioned := "  provisioned by run fylgja-provision " + showRunID +
		" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes"
	diverged := "diverged towards " + waypoint5 + " (bundle ee291b0f…): run fylgja-step " + stepShowRunID +
		" stopped at phase push; landed: n2; not landed: n1 (push.refused); the twin is at " + waypoint5 + " (bundle 893b6392…); " +
		"fylgja twin destroy clears it"
	for _, c := range []struct {
		name   string
		change func(*lab.StepFields)
		stdout string
		kind   string
		as     string
	}{
		{name: "version 5, stepped", stdout: lines(
			"twin: lab fylgja present (3 nodes); twin directory present",
			"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+stepAfter["n1"],
			"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
			"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+stepAfter["n3"],
			record(stepToAt, stepToID),
			"  intent read at 2026-10-02T09:14:01.000000Z",
			provisioned,
			"  stepped from "+waypoint5+" by run fylgja-step "+stepShowRunID+", ended "+stepEnded+
				"; reconcile 3.9s (restart n1); readiness n1 54.8s; push n1 1.6s, n2 2.4s; wait not run",
			"kind: "+showKind("none", stepToAt),
			"  "+noSnapshotNote,
			"in flight: none"),
			kind: noSnapshotNote, as: findings.ShowKindSnapshot},
		{name: "version 5, diverged", change: divergeAtPush, stdout: lines(
			"twin: lab fylgja present (3 nodes); twin directory present",
			"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux",
			"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
			"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+fixtureArtifacts["n3"],
			record(stepFromAt, showBundleID),
			"  intent read at "+showObserved,
			provisioned,
			"  diverged: step run fylgja-step "+stepShowRunID+" towards "+waypoint5+" (bundle ee291b0f…) stopped at phase push, ended "+
				stepEnded+"; landed n2; not landed n1 (push.refused); wait not run",
			"kind: "+diverged,
			"in flight: none"),
			kind: diverged, as: findings.ShowKindDiverged},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			raw := record5(t, steppedTwin(t, c.change))
			satisfiesContract(t, twin5Contract(t), raw, "the version 5 record")
			write5(t, paths, raw)
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			wantShow(t, out, c.stdout, c.as, c.kind)
			if strings.Contains(out.stdout, "none by run") || strings.Contains(out.stdout, "stage none") ||
				strings.Contains(out.stdout, "towards none") {
				t.Errorf("a side is named none:\n%s", out.stdout)
			}
			r := out.doc.Show.Record
			if r == nil || r.Stage != nil || r.Step == nil || r.Step.From.Stage != nil || r.Step.To.Stage != nil {
				t.Errorf("record %+v; want no stage, and a step whose sides' stages are null", r)
			}
		})
	}
}

// record5 is rec as a twin.json 5 worker wrote it: the contract version in place of the
// scope and the mapping, which 8 added (017); M10's waypoint in place of the stage at
// the top level, the step's to side's for a twin that stepped and its from side's for one
// that diverged, and on each side of the step; and no rehearsal, which 7 added (015).
func record5(t *testing.T, rec wire.TwinRecord) []byte {
	t.Helper()
	raw, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		t.Fatal(err)
	}
	waypoint := func(sequence int) map[string]any {
		return map[string]any{"series": "demo", "sequence": sequence, "description": fmt.Sprintf("cut %d", sequence),
			"at_source": "given"}
	}
	generic["twin_version"] = "5"
	unsnapshotted(generic)
	contractProvenance(generic)
	delete(generic, "stage")
	delete(generic, "rehearsal")
	generic["waypoint"] = waypoint(1)
	if step, ok := generic["step"].(map[string]any); ok {
		for side, sequence := range map[string]int{"from": 1, "to": 2} {
			s := step[side].(map[string]any)
			delete(s, "stage")
			s["waypoint"] = waypoint(sequence)
		}
		if rec.State != wire.StateDiverged {
			generic["waypoint"] = waypoint(2)
		}
	}
	if raw, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return raw
}

// twin5Contract is twin.json 5's frozen contract.
func twin5Contract(t *testing.T) *jsonschema.Schema {
	t.Helper()
	f, err := os.Open(repoPath("internal", "lab", "testdata", "contracts", "010-verify", "twin.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("twin.schema.json", doc); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("twin.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	return schema
}

// write5 writes raw, a record of twin.json 5 (record5), into the twin directory.
func write5(t *testing.T, paths lab.Paths, raw []byte) {
	t.Helper()
	if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

// waypoint5 is how a line names a side of a version 5 record, the waypoint it was.
const waypoint5 = "a waypoint of a record version this build no longer reads (twin.json 5)"

// A version 5 or 6 record's step line ends with how the step's wait ended, after M11's timings or
// after a diverged step's pushes, and the JSON record.step carries the wait by identifier and
// object, or null while it has not run (contracts/cli.md, twin show). The kind line is M11's.
func TestShowStepWait(t *testing.T) {
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "node " + object + " sees no neighbour"}
	}
	stepped := "  stepped from fylgja-fixture/seeded by run fylgja-step " + stepShowRunID + ", ended " + stepEnded +
		"; reconcile 3.9s (restart n1); readiness n1 54.8s; push n1 1.6s, n2 2.4s"
	diverged := "  diverged: step run fylgja-step " + stepShowRunID + " towards fylgja-fixture/cabled (bundle " + short(stepToID) +
		") stopped at phase push, ended " + stepEnded + "; landed n2; not landed n1 (push.refused)"
	for _, c := range []struct {
		name   string
		change func(*lab.StepFields)
		wait   *wire.StepWait
		line   string
		json   string
	}{
		{"settled", nil, &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, From: stepEnded,
			EndedAt: "2026-10-02T09:15:43.400000Z", Failing: []wire.StepFinding{}},
			stepped + "; settled after 2.4s", `"wait":{"outcome":"settled","budget_s":120,"reads":2,"after_s":2.4,"failing":[]}`},
		{"expired", nil, &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58, AfterS: 120, From: stepEnded,
			EndedAt: "2026-10-02T09:17:41Z", Failing: []wire.StepFinding{neighbor("n1:ethernet-1/3"), neighbor("n2:ethernet-1/3"),
				{Rule: findings.RuleVerifyPortEnabled, Object: "n1:ethernet-1/3", Message: "reads disable"}}},
			stepped + "; wait expired after 120.0s (3 failing)",
			`"wait":{"outcome":"expired","budget_s":120,"reads":58,"after_s":120,"failing":[{"rule":"verify.neighbor","object":"n1:ethernet-1/3"},` +
				`{"rule":"verify.neighbor","object":"n2:ethernet-1/3"},{"rule":"verify.port.enabled","object":"n1:ethernet-1/3"}]}`},
		{"cancelled", nil, &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4, From: stepEnded,
			EndedAt: "2026-10-02T09:15:53.400000Z", Failing: []wire.StepFinding{}},
			stepped + "; wait cancelled after 12.4s", `"wait":{"outcome":"cancelled","budget_s":120,"reads":7,"after_s":12.4,"failing":[]}`},
		{"incomplete", nil, &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120, Reads: 58, AfterS: 120.3, From: stepEnded,
			EndedAt: "2026-10-02T09:17:41.300000Z", Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "n3",
				Message: "node n3 (172.20.20.4:57400) could not be read: …"}}},
			stepped + "; wait could not complete",
			`"wait":{"outcome":"incomplete","budget_s":120,"reads":58,"after_s":120.3,"failing":[{"rule":"operation.failed","object":"n3"}]}`},
		{"not run", nil, nil, stepped + "; wait not run", `"wait":null`},
		{"diverged, settled", divergeAtPush, &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 3, AfterS: 1.9,
			From: stepEnded, EndedAt: "2026-10-02T09:15:42.900000Z", Failing: []wire.StepFinding{}},
			diverged + "; settled after 1.9s", `"wait":{"outcome":"settled","budget_s":120,"reads":3,"after_s":1.9,"failing":[]}`},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			rec := steppedTwin(t, c.change)
			if rec.TwinVersion != "11" {
				t.Fatalf("lab.NewStepRecord wrote version %q, want 11", rec.TwinVersion)
			}
			rec.Step.Wait = c.wait
			writeTwin(t, paths, rec)
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			if !strings.Contains(out.stdout, "\n"+c.line+"\n") {
				t.Errorf("stdout:\n%s\nwant the step line %q", out.stdout, c.line)
			}
			if strings.Contains(out.stdout, "message") || strings.Contains(out.stdout, "sees no neighbour") {
				t.Errorf("the step line quotes a finding's message:\n%s", out.stdout)
			}
			r := out.doc.Show.Record
			if r == nil || r.Step == nil {
				t.Fatalf("record %+v, want a step block", r)
			}
			b, err := json.Marshal(r.Step)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.HasSuffix(string(b), ","+c.json+"}") {
				t.Errorf("record.step %s\nwant it to end with %s", b, c.json)
			}
			// The rest of the block is M11's.
			m11 := *r.Step
			m11.Wait, m11.WaitKnown = nil, false
			if c.change == nil {
				wantShowStep(t, &findings.ShowRecord{Step: &m11}, steppedShowStep())
			}
		})
	}
}

// A version 10 record written by a create (step: null) is shown exactly as the same record
// written with M11's step shape: no step line and no step key.
func TestShowCreatedVersion10RecordAsM11(t *testing.T) {
	show := func(write func(*testing.T, lab.Paths, wire.TwinRecord)) showOutput {
		paths := useStateRoot(t)
		write(t, paths, seededTwin(t))
		return showWith(t, paths, "inspect-three.json", &fakeService{})
	}
	five, four := show(writeTwin), show(writeM11Twin)
	if seededTwin(t).TwinVersion != "11" {
		t.Fatalf("a create's record is version %q, want 11", seededTwin(t).TwinVersion)
	}
	if five.stdout != four.stdout {
		t.Errorf("version 5 stdout:\n%s\nversion 4:\n%s", five.stdout, four.stdout)
	}
	b5, err := json.Marshal(five.doc.Show)
	if err != nil {
		t.Fatal(err)
	}
	b4, err := json.Marshal(four.doc.Show)
	if err != nil {
		t.Fatal(err)
	}
	if string(b5) != string(b4) || strings.Contains(string(b5), `"step"`) {
		t.Errorf("version 5 show block %s\nversion 4 %s\nwant them equal, with no step key", b5, b4)
	}
}

// US2's show scenarios through the harness (014, T037): the stage blocks of twin show and
// twin verify, beside what twin.json records, and the moved schemas holding them to the
// 6 shape.

// recordedJSON is the value under keys in twin.json at path, compacted: what the record
// says, to set beside what a document says of it.
func recordedJSON(t *testing.T, path string, keys ...string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		t.Fatal(err)
	}
	for _, k := range keys {
		m, ok := v.(map[string]any)
		if !ok {
			t.Fatalf("twin.json has no %v", keys)
		}
		v = m[k]
	}
	return compactJSON(t, v)
}

// compactJSON is v as JSON with every object's keys in order, so a struct and the record's
// decoded map of it compare equal when their keys and values are.
func compactJSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var generic any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// m10Waypoint is M10's waypoint block, the shape a stage replaced.
var m10Waypoint = map[string]any{"series": "steps", "sequence": 1, "description": "the seeded stage", "at_source": "given"}

// refusedOnceEdited fails unless the current findings contract refuses doc once edit has
// changed its JSON: the moved schemas hold the stage blocks to twin.json 6's shape.
func refusedOnceEdited(t *testing.T, label string, doc *findings.Document, edit func(m map[string]any)) {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(compactJSON(t, doc)), &m); err != nil {
		t.Fatal(err)
	}
	edit(m)
	if err := validateAgainst(findingsContract(t, currentContract), []byte(compactJSON(t, m))); err == nil {
		t.Errorf("%s: the findings contract accepts %s", label, compactJSON(t, m))
	}
}

// dig is the object under keys in a decoded document.
func dig(m map[string]any, keys ...string) map[string]any {
	for _, k := range keys {
		m, _ = m[k].(map[string]any)
	}
	return m
}

// A twin of each kind of stage — a mark written, a mark given, the branch point, read on
// main, and the head — is shown at its at and naming its stage, on the record line
// and the kind line, and the show block's record.stage is what twin.json 6 records, key for
// key. The contract refuses a record.stage in M10's waypoint shape, one lacking its
// proposed change, and one whose at came from nowhere it names.
func TestShowNamesTheStageAsRecorded(t *testing.T) {
	for _, c := range []struct {
		label, description, source, branch, at string
	}{
		{"cabled", "the leaf cabled", findings.AtSourceWritten, "change-1", "2026-10-16T08:30:00.000000+00:00"},
		{"live", "the leaf live", findings.AtSourceGiven, "change-1", "2026-10-16T08:50:00.000000+00:00"},
		{"branch-point", "", findings.AtSourceBranchPoint, "main", "2026-10-16T08:00:00.000000+00:00"},
		{"head", "", findings.AtSourceHead, "change-1", "2026-10-16T08:40:00.000001+00:00"},
	} {
		t.Run(c.label, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
				f.Provenance.Branch, f.Provenance.At = c.branch, c.at
				f.Stage = &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "change-1"}, Label: c.label,
					Description: c.description, AtSource: c.source}
			}))
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			kind := "snapshot 576933ec… (branch " + c.branch + " at " + c.at + "), stage change-1/" + c.label
			wantShow(t, out, threeNodes+
				"record: branch "+c.branch+" at "+c.at+" (stage change-1/"+c.label+", at "+c.source+"), snapshot "+showSnapshotID+", bundle_id "+showBundleID+
				", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n"+
				"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: "+kind, "in flight: none"),
				findings.ShowKindSnapshot)
			if got, want := compactJSON(t, out.doc.Show.Record.Stage), recordedJSON(t, paths.TwinJSON, "stage"); got != want {
				t.Errorf("show.record.stage %s\nwant twin.json's %s", got, want)
			}
			refusedOnceEdited(t, "a waypoint for the stage", out.doc, func(m map[string]any) {
				dig(m, "show", "record")["stage"] = m10Waypoint
			})
			refusedOnceEdited(t, "a stage naming no proposed change", out.doc, func(m map[string]any) {
				delete(dig(m, "show", "record", "stage"), "proposed_change")
			})
			refusedOnceEdited(t, "an at_source the stage has not", out.doc, func(m map[string]any) {
				dig(m, "show", "record", "stage")["at_source"] = "sequence"
			})
		})
	}
}

// A stepped twin's step sides name the stages it stepped between as twin.json 6's step
// block records them, and the contract refuses a side naming M10's waypoint; a step in
// flight names the stage it steps towards.
func TestShowNamesTheStepsStagesAsRecorded(t *testing.T) {
	paths := useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, nil))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	r := out.doc.Show.Record
	if r == nil || r.Step == nil {
		t.Fatalf("record %+v; want a step", r)
	}
	for side, got := range map[string]any{"from": r.Step.From.Stage, "to": r.Step.To.Stage} {
		if want := recordedJSON(t, paths.TwinJSON, "step", side, "stage"); compactJSON(t, got) != want {
			t.Errorf("show.record.step.%s.stage %s\nwant twin.json's %s", side, compactJSON(t, got), want)
		}
	}
	if got, want := compactJSON(t, r.Stage), recordedJSON(t, paths.TwinJSON, "stage"); got != want || r.Stage.Label != "cabled" {
		t.Errorf("show.record.stage %s, want the step's target as twin.json records it, %s", got, want)
	}
	refusedOnceEdited(t, "a step side naming a waypoint", out.doc, func(m map[string]any) {
		dig(m, "show", "record", "step", "to")["stage"] = m10Waypoint
	})

	paths = useStateRoot(t)
	writeTwin(t, paths, seededTwin(t))
	out = showWith(t, paths, "inspect-three.json", &fakeService{inFlight: []provision.RunInFlight{
		{WorkflowID: "fylgja-step", RunID: stepShowRunID, Step: findings.StepPush, Towards: "stage fylgja-fixture/cabled"}}})
	running := "run fylgja-step " + stepShowRunID + " is at step push, stepping towards stage fylgja-fixture/cabled"
	if s := out.doc.Show; !slices.Contains(s.Notes, running) ||
		!strings.Contains(out.stdout, "kind: "+showKind("576933ec…", stepFromAt)+", stage fylgja-fixture/seeded; "+running+"\n") {
		t.Errorf("notes %q, stdout:\n%s\nwant the kind line naming the stage it steps towards", s.Notes, out.stdout)
	}
}

// The record line names the record's snapshot between its reference and its bundle (018;
// specs/018-snapshots/data-model.md §8), its full id as the bundle's is printed: a 9 naming
// one names it, a 9 naming none says none, and a record of 8 or earlier, which names none,
// says none with its version. The JSON record carries the id, or null for both kinds of
// none, and a step's sides carry each side's when the record's step names it.
func TestShowRecordNamesItsSnapshot(t *testing.T) {
	const fromSnapshot, toSnapshot = "6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6",
		"37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf"
	head := "record: branch fylgja-fixture at " + stepFromAt + " (stage fylgja-fixture/seeded, at given), "
	named := twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Stage = showStage("seeded")
		f.SnapshotID = fromSnapshot
	})
	eight := func() []byte {
		raw, err := json.Marshal(seededTwin(t))
		if err != nil {
			t.Fatal(err)
		}
		var generic map[string]any
		if err := json.Unmarshal(raw, &generic); err != nil {
			t.Fatal(err)
		}
		generic["twin_version"] = "8"
		unsnapshotted(generic)
		if raw, err = json.Marshal(generic); err != nil {
			t.Fatal(err)
		}
		return raw
	}
	for _, c := range []struct {
		label string
		write func(paths lab.Paths)
		line  string
		id    *string
	}{
		{"a 9 naming its snapshot", func(paths lab.Paths) { writeTwin(t, paths, named) },
			head + "snapshot " + fromSnapshot + ", bundle_id " + showBundleID, named.SnapshotID},
		{"a 9 naming none", func(paths lab.Paths) {
			writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
				f.Provenance.At, f.Stage, f.SnapshotID = stepFromAt, showStage("seeded"), ""
			}))
		},
			head + "snapshot none, bundle_id " + showBundleID, nil},
		{"an 8", func(paths lab.Paths) {
			if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(paths.TwinJSON, eight(), 0o644); err != nil {
				t.Fatal(err)
			}
		}, head + "snapshot none (record 8), bundle_id " + showBundleID, nil},
	} {
		t.Run(c.label, func(t *testing.T) {
			paths := useStateRoot(t)
			c.write(paths)
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			if !strings.Contains(out.stdout, "\n"+c.line+", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n") {
				t.Errorf("stdout:\n%s\nwant the record line %q", out.stdout, c.line)
			}
			r := out.doc.Show.Record
			if r == nil {
				t.Fatal("the document carries no record")
			}
			if (r.SnapshotID == nil) != (c.id == nil) || (r.SnapshotID != nil && *r.SnapshotID != *c.id) {
				t.Errorf("record snapshot_id %v, want %v", r.SnapshotID, c.id)
			}
			b, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			if c.id == nil && !strings.Contains(string(b), `"snapshot_id":null,"bundle_id":`) {
				t.Errorf("a record naming no snapshot does not say so: %s", b)
			}
			validateM10Document(t, out.doc)
		})
	}

	// A step's sides name their snapshots as the record's step block records them, and the
	// record's own is the target's.
	paths := useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, func(f *lab.StepFields) {
		f.From.SnapshotID, f.To.SnapshotID = fromSnapshot, toSnapshot
	}))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	r := out.doc.Show.Record
	if r == nil || r.SnapshotID == nil || *r.SnapshotID != toSnapshot || r.Step == nil ||
		r.Step.From.SnapshotID != fromSnapshot || r.Step.To.SnapshotID != toSnapshot {
		t.Errorf("a stepped record's snapshots: %+v (step %+v)", r, r.Step)
	}
	if !strings.Contains(out.stdout, "(stage fylgja-fixture/cabled, at given), snapshot "+toSnapshot+", bundle_id ") {
		t.Errorf("stdout:\n%s\nwant the target's snapshot on the record line", out.stdout)
	}
	validateM10Document(t, out.doc)
}

// A twin whose record names no snapshot, an earlier build's rebuild or a record of 8, is
// kind snapshot none, its line in brackets naming its branch and its at, or the time it was
// read, followed by the note that twin step refuses it and the remedy (019, R-10).
func TestShowSnapshotNone(t *testing.T) {
	const at = "2026-09-16T14:00:00Z"
	for _, c := range []struct {
		name, at, read string
		notes          []string
	}{
		{"read at", "", "  intent read at " + showObserved + "; reproducing it with --at that instant is best-effort\n",
			[]string{noSnapshotNote, bestEffortNote}},
		{"at", at, "  intent read at " + showObserved + "\n", []string{noSnapshotNote}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) { f.SnapshotID, f.Provenance.At = "", c.at }))
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			ref := "fylgja-fixture"
			if c.at != "" {
				ref += " at " + c.at
			}
			wantShow(t, out, threeNodes+
				"record: branch "+ref+", snapshot none, bundle_id "+showBundleID+", schema 41349c3a9c582e5dd44e55d6771f79c2, "+showRead+"\n"+
				c.read+provisionedLine+lines("kind: "+showKind("none", c.at), "  "+noSnapshotNote, "in flight: none"),
				findings.ShowKindSnapshot, c.notes...)
			if r := out.doc.Show.Record; r == nil || r.SnapshotID != nil {
				t.Errorf("record %+v, want snapshot_id null", r)
			}
		})
	}
}

// US5 scenario 3: a twin stepped from one snapshot to another, neither a stage, is kind
// snapshot, naming the new snapshot and its read time, and says it stepped from the old one
// by its short id; the record block's step line names both sides so.
func TestShowSteppedFromASnapshot(t *testing.T) {
	staged, nodes := showStepTarget(stepToID, "", stepAfter)
	f := lab.StepFields{
		Outcome:    wire.StepUnchanged,
		From:       wire.StepSide{SnapshotID: showSnapshotID, BundleID: showBundleID},
		To:         wire.StepSide{SnapshotID: stepToSnapshotID, BundleID: stepToID},
		ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: stepShowRunID, Version: "0.1.0-dev",
		Declared:  map[string]string{"n1": "live", "n2": "live", "n3": "live"},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: stepEnded, RecordedAt: time.Date(2026, 10, 2, 9, 15, 41, 0, time.UTC),
		Nodes: nodes, Staged: staged,
	}
	rec, err := lab.NewStepRecord(twinOf(t, nil), f)
	if err != nil {
		t.Fatal(err)
	}
	paths := useStateRoot(t)
	writeTwin(t, paths, rec)
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "snapshot 9c2d01e7… (branch fylgja-fixture, read at 2026-10-02T09:14:01.000000Z) (stepped from snapshot 576933ec… by run " +
		"fylgja-step " + stepShowRunID + ", ended " + stepEnded + ")"
	if !strings.Contains(out.stdout, "\nkind: "+kind+"\n") {
		t.Errorf("stdout:\n%s\nwant the kind line %q", out.stdout, kind)
	}
	step := "  stepped from snapshot 576933ec… by run fylgja-step " + stepShowRunID + ", ended " + stepEnded +
		"; unchanged: nothing reconciled, awaited or pushed; wait not run\n"
	if !strings.Contains(out.stdout, step) || strings.Contains(out.stdout, "none by run") {
		t.Errorf("stdout:\n%s\nwant the step line %q", out.stdout, step)
	}
	if s := out.doc.Show; s.Kind != findings.ShowKindSnapshot || s.Record == nil || s.Record.SnapshotID == nil ||
		*s.Record.SnapshotID != stepToSnapshotID || s.Record.Stage != nil {
		t.Errorf("show %+v; want kind snapshot naming %s and no stage", s, stepToSnapshotID)
	}
}

// SC-005: no kind line twin show prints, of any shape, says pinned, frozen or following
// (showDialled checks every line and note of every case), and each JSON kind is one of the
// four: snapshot for a twin from intent or a snapshot, from_bundle for a provisioned one.
func TestNoKindLineNamesFollowing(t *testing.T) {
	for _, c := range []struct {
		name   string
		change func(*lab.RecordFields)
		kind   string
	}{
		{"from --branch", nil, findings.ShowKindSnapshot},
		{"from --branch --at", func(f *lab.RecordFields) { f.Provenance.At = stepFromAt }, findings.ShowKindSnapshot},
		{"from a stage", func(f *lab.RecordFields) { f.Provenance.At, f.Stage = stepFromAt, showStage("seeded") }, findings.ShowKindSnapshot},
		{"from --snapshot", func(f *lab.RecordFields) { f.Source = wire.SourceSnapshot }, findings.ShowKindSnapshot},
		{"naming no snapshot", func(f *lab.RecordFields) { f.SnapshotID = "" }, findings.ShowKindSnapshot},
		{"from a bundle", func(f *lab.RecordFields) { f.Source, f.ObservedAt, f.SnapshotID = wire.SourceBundle, nil, "" }, findings.ShowKindFromBundle},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, twinOf(t, c.change))
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			if out.doc.Show.Kind != c.kind {
				t.Errorf("kind %s, want %s", out.doc.Show.Kind, c.kind)
			}
			if !strings.Contains(out.stdout, "\nkind: ") {
				t.Errorf("stdout:\n%s\nwant a kind line", out.stdout)
			}
		})
	}
}
