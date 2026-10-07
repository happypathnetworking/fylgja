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
	showCheckID  = "fylgja-reconcile-2026-09-16T19:10:00Z"
)

// twinOf is the record of a three-node twin of fylgja-fixture from intent, read at
// showObserved; change adjusts it before it is built.
func twinOf(t *testing.T, change func(*lab.RecordFields)) wire.TwinRecord {
	t.Helper()
	observed := showObserved
	f := lab.RecordFields{
		BundleID:   showBundleID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "41349c3a9c582e5dd44e55d6771f79c2", ContractVersion: "1"},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      showRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 16, 19, 1, 2, 0, time.UTC),
	}
	for _, n := range []string{"n1", "n2", "n3"} {
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n,
			Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: fixtureArtifacts[n], Size: 861},
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

// writeM11Twin writes rec as M11 wrote a record that has stepped: version 4, its step block
// with no wait key. lab.NewStepRecord writes version 5 from M12, so M11's show cases write
// their records through this and still show what M11 showed.
func writeM11Twin(t *testing.T, paths lab.Paths, rec wire.TwinRecord) {
	t.Helper()
	rec.TwinVersion = "4"
	if rec.Step != nil {
		rec.Step.Wait = nil
	}
	writeTwin(t, paths, rec)
	raw, err := os.ReadFile(paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	if st, ok := m["step"].(map[string]any); ok {
		delete(st, "wait")
	}
	if raw, err = json.MarshalIndent(m, "", "  "); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
		t.Fatal(err)
	}
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
	// A record naming a waypoint (M10's record.waypoint) or a state (twin.json 4, M11's
	// record.state and record.step) is the newest contract's to validate; every other
	// document — no record, or one written before M11 — is held to M7's contract, which it
	// still satisfies.
	if r := out.doc.Show.Record; r != nil && (r.Waypoint != nil || r.State != "") {
		validateM10Document(t, out.doc)
	} else {
		validateM7Document(t, out.doc)
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
	"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config 43e8fd0c2de5f4646f74a51d34742824\n" +
	"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config ecb03029ea805a09c54d2cd6a0e59ac9\n" +
	"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config ae0c3a87085839354cbb2ca10f71e487\n"

// threeBareNodes is the twin line with no twin.json to name what the nodes were pushed.
const threeBareNodes = "twin: lab fylgja present (3 nodes); twin directory present\n" +
	"  n1  clab-fylgja-n1  running  172.20.20.2\n" +
	"  n2  clab-fylgja-n2  running  172.20.20.3\n" +
	"  n3  clab-fylgja-n3  running  172.20.20.4\n"

const recordLine = "record: branch fylgja-fixture, bundle_id " + showBundleID + ", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n"

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

// Scenario 1: no lab, no twin directory, no following.
func TestShowNoTwin(t *testing.T) {
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-empty.json", &fakeService{})
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none", "in flight: none"),
		findings.ShowKindNone, "no twin")
	if s := out.doc.Show; s.Record != nil || s.Following != nil || s.LastCheck != nil || s.Service != findings.ShowServiceOK ||
		s.Host.LabPresent || s.Host.TwinDirPresent || s.Host.Phrase != "" {
		t.Errorf("show %+v, want nothing but the empty host", s)
	}
	if out.stderr != "" {
		t.Errorf("stderr:\n%s\nwant nothing", out.stderr)
	}
}

// followingState is Schedule fylgja-follow of branch, every five minutes, next due at 19:15.
func followingState(branch string) *provision.FollowingState {
	return &provision.FollowingState{Branch: branch, IntervalS: 300, NextCheckAt: time.Date(2026, 9, 16, 19, 15, 0, 0, time.UTC)}
}

// Scenario 2: a following twin, with its last check and the next.
func TestShowFollowing(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, nil))
	svc := &fakeService{following: followingState("fylgja-fixture"), lastCheck: &provision.CheckRecord{
		WorkflowID: showCheckID, RunID: "r-c", ScheduledAt: time.Date(2026, 9, 16, 19, 10, 0, 0, time.UTC),
		ClosedAt: time.Date(2026, 9, 16, 19, 10, 3, 0, time.UTC),
		Result:   provision.ReconcileResult{Outcome: provision.CheckUnchanged, Branch: "fylgja-fixture", TwinBundleID: showBundleID, BundleID: showBundleID},
	}}
	out := showWith(t, paths, "inspect-three.json", svc)
	wantShow(t, out, threeNodes+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines(
		"kind: following branch fylgja-fixture, checked every 5m0s",
		"  last check: "+showCheckID+" at 19:10:03Z, unchanged",
		"  next check: 2026-09-16T19:15:00Z",
		"  a rebuild discards the twin's runtime state",
		"in flight: none"),
		findings.ShowKindFollowing, "a rebuild discards the twin's runtime state", bestEffortNote)
	f := out.doc.Show.Following
	if f == nil || f.Branch != "fylgja-fixture" || f.IntervalS != 300 || f.NextCheckAt != "2026-09-16T19:15:00Z" ||
		f.LastCheck == nil || f.LastCheck.Outcome != provision.CheckUnchanged || f.LastCheck.ClosedAt != "2026-09-16T19:10:03Z" {
		t.Errorf("following %+v (last check %+v)", f, f.LastCheck)
	}
	if r := out.doc.Show.Record; r == nil || r.BundleID != showBundleID || r.ObservedAt == nil || *r.ObservedAt != showObserved ||
		r.Run.RunID != showRunID || r.Nodes != 3 || r.WorkerVersion != "0.1.0-dev" {
		t.Errorf("record %+v", r)
	}
	n := out.doc.Show.Host.Nodes
	if len(n) != 3 || n[0].Name != "n1" || n[0].Container != "clab-fylgja-n1" || n[0].State != "running" || n[0].MgmtIPv4 != "172.20.20.2" ||
		n[0].Artifact == nil || *n[0].Artifact != (findings.ShowArtifact{Name: "device-config", Checksum: fixtureArtifacts["n1"]}) {
		t.Errorf("nodes %+v, want n1 first with the artifact its record names", n)
	}
	if out.stderr != "" {
		t.Errorf("stderr:\n%s\nwant nothing: the last check was unchanged", out.stderr)
	}
	if want := []string{"Following", "LastCheck", "InFlight", "Following", "LastCheck", "InFlight"}; !slices.Equal(svc.reads, want) {
		t.Errorf("reads %v, want each read once per run, text then JSON", svc.reads)
	}
}

// Scenario 3: pinned at T, verbatim, with no best-effort statement.
func TestShowPinned(t *testing.T) {
	const at = "2026-09-16T14:00:00Z"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) { f.Provenance.At = at }))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	wantShow(t, out, threeNodes+
		"record: branch fylgja-fixture at "+at+", bundle_id "+showBundleID+", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: pinned at "+at+"; not following", "in flight: none"),
		findings.ShowKindPinned, "pinned at "+at+"; not following")
	if r := out.doc.Show.Record; r == nil || r.At != at {
		t.Errorf("record %+v, want at %s verbatim", r, at)
	}
}

// A twin created from a waypoint is pinned and says which waypoint named its reference, on
// the record line, the kind line and in the note, and the JSON record carries it; a record
// naming none, written by M10 as an explicit null or by an earlier worker with no key,
// shows exactly as M7 shows it (contracts/cli.md).
func TestShowPinnedFromAWaypoint(t *testing.T) {
	const at = "2026-09-20T10:00:00.123456+00:00"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = at
		f.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	}))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "pinned at " + at + ", waypoint demo/2; not following"
	wantShow(t, out, threeNodes+
		"record: branch fylgja-fixture at "+at+" (waypoint demo/2, at written), bundle_id "+showBundleID+
		", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: "+kind, "in flight: none"),
		findings.ShowKindPinned, kind)
	want := findings.ShowWaypoint{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	if r := out.doc.Show.Record; r == nil || r.At != at || r.Waypoint == nil || *r.Waypoint != want {
		t.Errorf("record %+v, want at %s and waypoint %+v", r, at, want)
	}

	// The same pinned twin with no waypoint, from a version 4 record and from a version 2
	// one, is TestShowPinned's, line for line.
	const pinnedAt = "2026-09-16T14:00:00Z"
	for label, record := range map[string]func() []byte{
		"version 4, waypoint null": func() []byte {
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
			delete(generic, "waypoint")
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
			wantShow(t, out, threeNodes+
				"record: branch fylgja-fixture at "+pinnedAt+", bundle_id "+showBundleID+", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n"+
				"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: pinned at "+pinnedAt+"; not following", "in flight: none"),
				findings.ShowKindPinned, "pinned at "+pinnedAt+"; not following")
			if b, err := json.Marshal(out.doc); err != nil || strings.Contains(string(b), "waypoint") {
				t.Errorf("a record naming no waypoint shows one (%v): %s", err, b)
			}
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
		f.Nodes[1].PSP = wire.PSPRef{ID: "arista_eos", Source: "embedded"}
		f.Nodes[1].Image = "ceos:4.32.0.2F"
	}))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	mixed := strings.Replace(threeNodes,
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  ",
		"  n2  clab-fylgja-n2  running  172.20.20.3  arista_eos  ", 1)
	wantShow(t, out, mixed+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines("kind: frozen; not following", "in flight: none"),
		findings.ShowKindFrozen, "not following", bestEffortNote)
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

// Scenario 4: frozen (--no-follow), with the best-effort statement.
func TestShowFrozen(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, nil))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	wantShow(t, out, threeNodes+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines("kind: frozen; not following", "in flight: none"),
		findings.ShowKindFrozen, "not following", bestEffortNote)
}

// Scenario 5: from a bundle, with the read time unknown.
func TestShowFromBundle(t *testing.T) {
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) { f.Source, f.ObservedAt = wire.SourceBundle, nil }))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	wantShow(t, out, threeNodes+recordLine+
		// contracts/cli.md's words, literal: built from lab.ObservedAtUnknown this line once
		// agreed with a show that printed "unknown:" twice.
		"  intent read: unknown: provisioned from an existing bundle; no read took place\n"+
		strings.Replace(provisionedLine, "source intent", "source bundle", 1)+
		lines("kind: from a bundle; not following", "in flight: none"),
		findings.ShowKindFromBundle, "provisioned from a bundle; read time unknown; not following")
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

	t.Run("with a Schedule", func(t *testing.T) {
		const schedule = "following of branch fylgja-fixture exists, and a check finds nothing to compare against"
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		out := showWith(t, paths, "inspect-empty.json", &fakeService{following: followingState("fylgja-fixture")})
		wantShow(t, out, host+record+lines("kind: none; "+schedule, "in flight: none"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it", schedule)
		check(t, out)
		if out.doc.Show.Following == nil {
			t.Errorf("following %+v, want the Schedule reported", out.doc.Show.Following)
		}
	})

	// A rebuild whose destroy removed the lab but whose unstage never answered leaves this host,
	// and following stopped: the failed check is reported as it is with no record.
	const stopped = "following of branch fylgja-fixture stopped: the check " + showCheckID +
		" at 2026-09-16T19:12:00Z ended rebuild_failed at step destroy; cleanup teardown done, unstage failed; fylgja twin create starts again"

	t.Run("after a failed rebuild stopped following", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		out := showWith(t, paths, "inspect-empty.json", &fakeService{lastCheck: unstageFailedCheck()})
		wantShow(t, out, host+record+lines("kind: none; "+stopped, "in flight: none"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it", stopped)
		s := out.doc.Show
		if s.Host.Phrase != phrase || s.Record == nil || s.Record.BundleID != showBundleID || s.Following != nil {
			t.Errorf("show %+v, want the phrase, the record and no Schedule", s)
		}
		c := s.LastCheck
		if c == nil || c.Outcome != provision.CheckRebuildFailed || c.Step != findings.StepDestroy || c.Cleanup == nil ||
			c.Cleanup.Teardown != provision.CleanupDone || c.Cleanup.Unstage != provision.CleanupFailed ||
			!slices.Equal(c.Cleanup.Remaining, []string{"twin directory"}) || len(c.Findings) != 3 {
			t.Errorf("last check %+v, want the failed rebuild at destroy with its cleanup and findings", c)
		}
		for _, text := range []string{out.stdout, strings.Join(s.Notes, "\n")} {
			if strings.Contains(text, "runtime state") {
				t.Errorf("says %q for a record without its lab:\n%s", "runtime state", text)
			}
		}
		for _, line := range []string{
			"rejection cleanup.incomplete [step unstage] twin directory: activity StartToClose timeout",
			"rejection rebuild.failed [step destroy] r-cd: the rebuild's destroy r-cd ended unclean",
			"warning follow.stopped [step follow] fylgja-follow: following of branch fylgja-fixture stopped",
		} {
			if !strings.Contains(out.stderr, line) {
				t.Errorf("stderr does not carry %q:\n%s", line, out.stderr)
			}
		}
		if len(out.doc.Findings) != 0 {
			t.Errorf("document findings %+v, want none: the check's are in its block", out.doc.Findings)
		}
	})

	t.Run("after a failed rebuild, with a Schedule", func(t *testing.T) {
		const schedule = "following of branch fylgja-fixture exists, and a check finds nothing to compare against"
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		out := showWith(t, paths, "inspect-empty.json",
			&fakeService{following: followingState("fylgja-fixture"), lastCheck: unstageFailedCheck()})
		wantShow(t, out, host+record+lines("kind: none; "+schedule, "in flight: none"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it", schedule)
		check(t, out)
		if out.doc.Show.LastCheck != nil {
			t.Errorf("last check %+v, want none beside a Schedule", out.doc.Show.LastCheck)
		}
	})
}

// A waypoint's record whose lab is gone is M3's shape b, unchanged: kind none with M3's
// phrase and remedy, and no pinned kind line. The record still names its waypoint, on the
// record line and in the JSON, which M10's show.schema.json validates.
func TestShowWaypointRecordWithoutLab(t *testing.T) {
	const at = "2026-09-20T10:00:00.123456+00:00"
	const phrase = "the twin of branch fylgja-fixture at " + at + ", bundle_id " + showBundleID +
		", provisioned by run fylgja-provision " + showRunID + ", 3 nodes recorded, but lab fylgja is absent"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = at
		f.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	}))
	out := showWith(t, paths, "inspect-empty.json", &fakeService{})
	wantShow(t, out, lines("twin: lab fylgja absent; twin directory present; "+phrase+"; fylgja twin destroy clears it")+
		"record: branch fylgja-fixture at "+at+" (waypoint demo/2, at written), bundle_id "+showBundleID+
		", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n"+
		"  intent read at "+showObserved+"\n"+provisionedLine+lines("kind: none", "in flight: none"),
		findings.ShowKindNone, phrase+"; fylgja twin destroy clears it")

	s := out.doc.Show
	if s.Host.Phrase != phrase || s.Host.LabPresent || !s.Host.TwinDirPresent {
		t.Errorf("host %+v, want M3's phrase with the lab absent and the twin directory present", s.Host)
	}
	want := findings.ShowWaypoint{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	if r := s.Record; r == nil || r.At != at || r.BundleID != showBundleID || r.Waypoint == nil || *r.Waypoint != want {
		t.Errorf("record %+v, want at %s and waypoint %+v", r, at, want)
	}
	for _, text := range []string{out.stdout, strings.Join(s.Notes, "\n")} {
		for _, not := range []string{"pinned", "fylgja twin create", "runtime state"} {
			if strings.Contains(text, not) {
				t.Errorf("says %q for a waypoint's record without its lab:\n%s", not, text)
			}
		}
	}
}

// unstageFailedCheck is a check whose rebuild's destroy tore the lab down but whose unstage
// never answered, so twin.json remains and following stopped.
func unstageFailedCheck() *provision.CheckRecord {
	failed := findings.List{
		{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete, Object: "twin directory", Step: findings.StepUnstage,
			Message: "activity StartToClose timeout; the twin directory may remain: run fylgja twin destroy again once a worker is serving task queue " + provision.TaskQueue},
		{Severity: findings.Rejection, Rule: findings.RuleRebuildFailed, Object: "r-cd", Step: findings.StepDestroy,
			Message: "the rebuild's destroy r-cd ended unclean at step unstage; cleanup teardown done, unstage failed; remaining: twin directory; following stopped"},
		{Severity: findings.Warning, Rule: findings.RuleFollowStopped, Object: provision.FollowScheduleID, Step: findings.StepFollow,
			Message: "following of branch fylgja-fixture stopped after a failed rebuild; fylgja twin create starts again"},
	}
	return &provision.CheckRecord{
		WorkflowID: showCheckID, RunID: "r-c", ScheduledAt: time.Date(2026, 9, 16, 19, 10, 0, 0, time.UTC),
		ClosedAt: time.Date(2026, 9, 16, 19, 12, 0, 0, time.UTC),
		Result: provision.ReconcileResult{
			Outcome: provision.CheckRebuildFailed, Step: findings.StepDestroy, Branch: "fylgja-fixture", Findings: failed,
			TwinBundleID: showBundleID, BundleID: "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00",
			Destroy: &provision.DestroyResult{Findings: failed[:1], Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone,
				Unstage: provision.CleanupFailed, Removed: []string{"lab fylgja (3 containers)"}, Remaining: []string{"twin directory"}}},
			FollowingStopped: true,
		},
	}
}

// Scenario 7: runs in flight, each with its step; a check with its child's.
func TestShowRunsInFlight(t *testing.T) {
	paths := useStateRoot(t)
	svc := &fakeService{inFlight: []provision.RunInFlight{
		{WorkflowID: provision.WorkflowProvision, RunID: "r-p", Step: findings.StepDeploy},
		{WorkflowID: provision.WorkflowDestroy, RunID: "r-d", Step: findings.StepTeardown},
		{WorkflowID: showCheckID, RunID: "r-c", Step: findings.StepProvision,
			Child: &provision.RunInFlight{WorkflowID: provision.WorkflowProvision, RunID: "r-cp", Step: findings.StepReadiness}},
	}}
	out := showWith(t, paths, "inspect-empty.json", svc)
	// No Schedule and a check rebuilding: twin destroy stopped following and is cancelling it.
	const rebuilding = "check " + showCheckID + " is rebuilding the twin at step provision; following has stopped"
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none; "+rebuilding,
		"in flight:",
		"  run fylgja-provision r-p at step deploy",
		"  run fylgja-destroy r-d at step teardown",
		"  check "+showCheckID+" at step provision (run fylgja-provision r-cp at step readiness)"),
		findings.ShowKindNone, rebuilding)
	f := out.doc.Show.InFlight
	if len(f) != 3 || f[2].Child == nil || f[2].Child.Step != findings.StepReadiness || f[0].Step != findings.StepDeploy {
		t.Errorf("in flight %+v", f)
	}
}

// A check rebuilding the twin: whatever the host holds is the rebuild's own work, so twin show
// names the rebuild, and neither calls the host an orphan with its remedy nor advises a create
// that would be refused as run.in_flight.
func TestShowRebuildInFlight(t *testing.T) {
	t.Run("at destroy, with no twin", func(t *testing.T) {
		paths := useStateRoot(t)
		svc := &fakeService{following: followingState("fylgja-fixture"), inFlight: []provision.RunInFlight{
			{WorkflowID: showCheckID, RunID: "r-c", Step: findings.StepDestroy,
				Child: &provision.RunInFlight{WorkflowID: provision.WorkflowDestroy, RunID: "r-cd", Step: findings.StepUnstage}},
		}}
		out := showWith(t, paths, "inspect-empty.json", svc)
		const rebuilding = "following of branch fylgja-fixture is rebuilding the twin: check " + showCheckID + " at step destroy"
		wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory",
			"kind: "+rebuilding,
			"  next check: 2026-09-16T19:15:00Z",
			"in flight: check "+showCheckID+" at step destroy (run fylgja-destroy r-cd at step unstage)"),
			findings.ShowKindFollowing, rebuilding)
		if s := out.doc.Show; s.Following == nil || s.Record != nil || len(s.InFlight) != 1 {
			t.Errorf("show %+v, want following, no record, the check in flight", s)
		}
	})

	t.Run("at provision, its child at deploy", func(t *testing.T) {
		const phrase = "an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml"
		paths := useStateRoot(t)
		svc := &fakeService{following: followingState("fylgja-fixture"), inFlight: []provision.RunInFlight{
			{WorkflowID: showCheckID, RunID: "r-c", Step: findings.StepProvision,
				Child: &provision.RunInFlight{WorkflowID: provision.WorkflowProvision, RunID: "r-cp", Step: findings.StepDeploy}},
		}}
		out := showWith(t, paths, "inspect-one-orphan.json", svc)
		const rebuilding = "following of branch fylgja-fixture is rebuilding the twin: check " + showCheckID + " at step provision"
		wantShow(t, out, lines(
			"twin: lab fylgja present (1 node); twin directory absent",
			"  n1  clab-fylgja-n1  running  172.20.20.2",
			"kind: "+rebuilding,
			"  next check: 2026-09-16T19:15:00Z",
			"in flight: check "+showCheckID+" at step provision (run fylgja-provision r-cp at step deploy)"),
			findings.ShowKindFollowing, rebuilding)
		// The block's host is M3's inspection as it stands; only the text's reading of it changes.
		if s := out.doc.Show; s.Host.Phrase != phrase || !s.Host.LabPresent {
			t.Errorf("host %+v, want what containerlab says, phrase included", s.Host)
		}
		for _, text := range []string{out.stdout, strings.Join(out.doc.Show.Notes, "\n")} {
			for _, advice := range []string{"orphan", "fylgja twin destroy clears it", "fylgja twin create"} {
				if strings.Contains(text, advice) {
					t.Errorf("advises %q during a rebuild:\n%s", advice, text)
				}
			}
		}
	})

	// M5: the rebuild's provision pushing its nodes is named as any other of its steps.
	t.Run("at provision, its child at push", func(t *testing.T) {
		paths := useStateRoot(t)
		svc := &fakeService{following: followingState("fylgja-fixture"), inFlight: []provision.RunInFlight{
			{WorkflowID: showCheckID, RunID: "r-c", Step: findings.StepProvision,
				Child: &provision.RunInFlight{WorkflowID: provision.WorkflowProvision, RunID: "r-cp", Step: findings.StepPush}},
		}}
		out := showWith(t, paths, "inspect-one-orphan.json", svc)
		const rebuilding = "following of branch fylgja-fixture is rebuilding the twin: check " + showCheckID + " at step provision"
		wantShow(t, out, lines(
			"twin: lab fylgja present (1 node); twin directory absent",
			"  n1  clab-fylgja-n1  running  172.20.20.2",
			"kind: "+rebuilding,
			"  next check: 2026-09-16T19:15:00Z",
			"in flight: check "+showCheckID+" at step provision (run fylgja-provision r-cp at step push)"),
			findings.ShowKindFollowing, rebuilding)
	})
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
			len(s.InFlight) != 1 || s.InFlight[0].Step != findings.StepDeploy || s.LastCheck != nil {
			t.Errorf("show %+v, want M3's phrase in the host block, no record, the run in flight", s)
		}
		if out.stderr != "" {
			t.Errorf("stderr:\n%s\nwant nothing", out.stderr)
		}
	})

	// A create that lands between a rebuild's destroy and its provision: the check
	// ended rebuild_failed and stopped following while the create runs, so no create advice.
	t.Run("at deploy, after a failed rebuild stopped following", func(t *testing.T) {
		const stopped = "following of branch fylgja-fixture stopped: the check " + showCheckID +
			" at 2026-09-16T19:12:00Z ended rebuild_failed at step provision; cleanup teardown done, unstage done"
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-three.json", &fakeService{lastCheck: stoppedCheck(), inFlight: inFlight(findings.StepDeploy)})
		wantShow(t, out, threeBareNodes+lines("kind: none; "+holds+"; "+stopped, "in flight: run fylgja-provision r-p at step deploy"),
			findings.ShowKindNone, holds, stopped)
		quiet(t, out)
		if c := out.doc.Show.LastCheck; c == nil || c.Outcome != provision.CheckRebuildFailed || len(c.Findings) != 3 {
			t.Errorf("last check %+v, want the failed rebuild reported", c)
		}
	})

	t.Run("at readiness, with a Schedule", func(t *testing.T) {
		const holds = "run fylgja-provision r-p is at step readiness, and the host holds its work"
		const schedule = "following of branch fylgja-fixture exists, and a check finds nothing to compare against"
		paths := useStateRoot(t)
		twinDir(t, paths)
		out := showWith(t, paths, "inspect-three.json",
			&fakeService{following: followingState("fylgja-fixture"), inFlight: inFlight(findings.StepReadiness)})
		wantShow(t, out, threeBareNodes+lines("kind: none; "+holds+"; "+schedule, "in flight: run fylgja-provision r-p at step readiness"),
			findings.ShowKindNone, holds, schedule)
		quiet(t, out)
		if out.doc.Show.Following == nil {
			t.Error("following not reported, want the Schedule")
		}
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

// stoppedCheck is a check whose rebuild's provision failed at deploy, so following stopped.
func stoppedCheck() *provision.CheckRecord {
	failed := findings.List{
		{Severity: findings.Rejection, Rule: findings.RuleDeployFailed, Object: "lab fylgja", Step: findings.StepDeploy, Message: "clab deploy exited 1"},
		{Severity: findings.Rejection, Rule: findings.RuleRebuildFailed, Object: "r-cp", Step: findings.StepProvision,
			Message: "the rebuild's provision r-cp ended failed at step deploy; cleanup teardown done, unstage done; following stopped"},
		{Severity: findings.Warning, Rule: findings.RuleFollowStopped, Object: provision.FollowScheduleID, Step: findings.StepFollow,
			Message: "following of branch fylgja-fixture stopped after a failed rebuild; fylgja twin create starts again"},
	}
	return &provision.CheckRecord{
		WorkflowID: showCheckID, RunID: "r-c", ScheduledAt: time.Date(2026, 9, 16, 19, 10, 0, 0, time.UTC),
		ClosedAt: time.Date(2026, 9, 16, 19, 12, 0, 0, time.UTC),
		Result: provision.ReconcileResult{
			Outcome: provision.CheckRebuildFailed, Step: findings.StepProvision, Branch: "fylgja-fixture", Findings: failed,
			Provision: &provision.ProvisionResult{Outcome: provision.OutcomeFailed, Findings: failed[:1],
				Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone}},
			FollowingStopped: true,
		},
	}
}

// Scenario 8: following stopped by a failed rebuild, and no twin.
func TestShowFollowingStopped(t *testing.T) {
	const stopped = "following of branch fylgja-fixture stopped: the check " + showCheckID +
		" at 2026-09-16T19:12:00Z ended rebuild_failed at step provision; cleanup teardown done, unstage done; fylgja twin create starts again"
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-empty.json", &fakeService{lastCheck: stoppedCheck()})
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none; "+stopped, "in flight: none"),
		findings.ShowKindNone, "no twin", stopped)
	c := out.doc.Show.LastCheck
	if c == nil || c.Outcome != provision.CheckRebuildFailed || c.Cleanup == nil || c.Cleanup.Teardown != provision.CleanupDone ||
		len(c.Findings) != 3 || out.doc.Show.Following != nil {
		t.Errorf("last check %+v, following %+v", c, out.doc.Show.Following)
	}
	for _, line := range []string{
		"rejection rebuild.failed [step provision] r-cp: the rebuild's provision r-cp ended failed",
		"warning follow.stopped [step follow] fylgja-follow: following of branch fylgja-fixture stopped",
	} {
		if !strings.Contains(out.stderr, line) {
			t.Errorf("stderr does not carry %q:\n%s", line, out.stderr)
		}
	}
	if len(out.doc.Findings) != 0 {
		t.Errorf("document findings %+v, want none: the check's are in its block", out.doc.Findings)
	}
}

// Scenario 8a: the failed rebuild superseded by a later run (LastCheck answers nil) is an
// empty host, with no stopped sentence.
func TestShowFollowingStoppedSuperseded(t *testing.T) {
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-empty.json", &fakeService{})
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none", "in flight: none"),
		findings.ShowKindNone, "no twin")
	if out.doc.Show.LastCheck != nil || out.stderr != "" {
		t.Errorf("last check %+v, stderr %q; want neither", out.doc.Show.LastCheck, out.stderr)
	}
}

// Scenario 9: the service unreachable: the host and the record, following and runs in flight
// unknown, exit 0 with the warning — whether the dial or a read fails.
func TestShowServiceUnreachable(t *testing.T) {
	const want = "workflow service unreachable at localhost:7233 (connection refused); " +
		"whether the twin is following and whether a run is in flight are unknown"
	check := func(t *testing.T, out showOutput) {
		t.Helper()
		wantShow(t, out, threeNodes+recordLine+
			"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
			provisionedLine+lines("kind: frozen; following: unknown (workflow service unreachable at localhost:7233)", "in flight: unknown"),
			findings.ShowKindFrozen, bestEffortNote, "following: unknown (workflow service unreachable at localhost:7233)")
		if s := out.doc.Show; s.Service != findings.ShowServiceUnreachable || s.Following != nil || s.InFlight != nil {
			t.Errorf("show %+v, want service unreachable and no following or runs", s)
		}
		wantFinding := findings.Finding{Severity: findings.Warning, Rule: findings.RuleShowServiceUnreachable, Object: "localhost:7233", Message: want}
		if len(out.doc.Findings) != 1 || out.doc.Findings[0] != wantFinding {
			t.Errorf("findings %+v, want %+v", out.doc.Findings, wantFinding)
		}
		if !strings.Contains(out.stderr, "warning show.service.unreachable localhost:7233: "+want) {
			t.Errorf("stderr:\n%s\nwant the warning", out.stderr)
		}
	}
	refused := &provision.UnreachableError{Address: "localhost:7233", Err: errors.New("connection refused")}

	t.Run("a read", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		check(t, showWith(t, paths, "inspect-three.json", &fakeService{readErr: refused}))
	})
	t.Run("the last check, after following answered", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		check(t, showWith(t, paths, "inspect-three.json", &fakeService{following: followingState("fylgja-fixture"),
			lastCheck: &provision.CheckRecord{WorkflowID: showCheckID}, failRead: "LastCheck", failReadErr: refused}))
	})
	t.Run("the runs in flight, after the others answered", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		check(t, showWith(t, paths, "inspect-three.json", &fakeService{following: followingState("fylgja-fixture"),
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

// Scenario 10: following of another branch: the twin is frozen, and checks skip.
func TestShowFollowingOtherBranch(t *testing.T) {
	const other = "following of branch other exists, but the twin is of branch fylgja-fixture: checks skip"
	paths := useStateRoot(t)
	writeTwin(t, paths, twinOf(t, nil))
	out := showWith(t, paths, "inspect-three.json", &fakeService{following: followingState("other")})
	wantShow(t, out, threeNodes+recordLine+
		"  intent read at "+showObserved+"; reproducing it with --at that instant is best-effort\n"+
		provisionedLine+lines("kind: frozen; "+other, "in flight: none"),
		findings.ShowKindFrozen, other, bestEffortNote)
	if f := out.doc.Show.Following; f == nil || f.Branch != "other" {
		t.Errorf("following %+v, want the Schedule reported whatever the twin", f)
	}
}

// Scenario 11: a Schedule with no twin.
func TestShowScheduleWithoutTwin(t *testing.T) {
	const s = "following of branch fylgja-fixture exists, and a check finds nothing to compare against; fylgja twin create replaces it"
	paths := useStateRoot(t)
	out := showWith(t, paths, "inspect-empty.json", &fakeService{following: followingState("fylgja-fixture")})
	wantShow(t, out, lines("twin: none: no lab fylgja, no twin directory", "kind: none; "+s, "in flight: none"),
		findings.ShowKindNone, "no twin", s)
}

// A Schedule beside an orphan, or beside a twin directory whose twin.json cannot be read, gets
// no create advice: a create would be refused as host.lab.present or host.twin.present, as for
// a record whose lab is absent.
func TestShowOrphanWithSchedule(t *testing.T) {
	const schedule = "following of branch fylgja-fixture exists, and a check finds nothing to compare against"
	check := func(t *testing.T, out showOutput, phrase, twinLine string) {
		t.Helper()
		wantShow(t, out, twinLine+lines("kind: none; "+schedule, "in flight: none"),
			findings.ShowKindNone, phrase+"; fylgja twin destroy clears it", schedule)
		s := out.doc.Show
		if s.Record != nil || s.Following == nil || s.Following.Branch != "fylgja-fixture" {
			t.Errorf("show %+v, want no record and the Schedule reported", s)
		}
		for _, text := range []string{out.stdout, strings.Join(s.Notes, "\n")} {
			if strings.Contains(text, "fylgja twin create") {
				t.Errorf("advises a create that host check would refuse:\n%s", text)
			}
		}
	}

	t.Run("an orphan", func(t *testing.T) {
		const phrase = "an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml"
		paths := useStateRoot(t)
		out := showWith(t, paths, "inspect-one-orphan.json", &fakeService{following: followingState("fylgja-fixture")})
		check(t, out, phrase, lines(
			"twin: lab fylgja present (1 node); twin directory absent; "+phrase+"; fylgja twin destroy clears it",
			"  n1  clab-fylgja-n1  running  172.20.20.2"))
	})

	t.Run("an unparseable twin.json", func(t *testing.T) {
		paths := useStateRoot(t)
		if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(paths.TwinJSON, []byte("{not json"), 0o644); err != nil {
			t.Fatal(err)
		}
		out := showWith(t, paths, "inspect-empty.json", &fakeService{following: followingState("fylgja-fixture")})
		phrase := out.doc.Show.Host.Phrase
		if !strings.HasPrefix(phrase, "a leftover twin directory: twin.json could not be read (") {
			t.Fatalf("phrase %q, want M3's unreadable-record shape", phrase)
		}
		check(t, out, phrase, lines("twin: lab fylgja absent; twin directory present; "+phrase+"; fylgja twin destroy clears it"))
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
		out.doc.Findings[0].Message != "workflow service unreachable at localhost:7233 (no answer within 50ms); "+
			"whether the twin is following and whether a run is in flight are unknown" {
		t.Errorf("show %+v, findings %+v; want unreachable after no answer within 50ms", s, out.doc.Findings)
	}
}

// The step of contracts/cli.md's twin show examples, on the three-node twin of twinOf:
// from demo/1 (showBundleID) to demo/2, containerlab restarting n1 for a link added between
// n1 and n2, and pushing n1 (artifact, restarted) and n2 (artifact, bootstrap); n3 is left
// alone.
const (
	stepShowRunID = "01a2b3c4-0000-7000-8000-000000000002"
	stepFromAt    = "2026-09-28T15:00:01.123456+00:00"
	stepToAt      = "2026-09-28T15:20:44.000000+00:00"
	stepEnded     = "2026-10-02T09:15:41Z"
)

var stepToID = strings.Repeat("ee291b0f", 8)

// stepAfter is each node's artifact checksum at demo/2: n3's does not move.
var stepAfter = map[string]string{"n1": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3", "n2": "7a9b03de7a9b03de7a9b03de7a9b03de", "n3": fixtureArtifacts["n3"]}

func showDemo(sequence int) *wire.WaypointRef {
	return &wire.WaypointRef{Series: "demo", Sequence: sequence, Description: fmt.Sprintf("cut %d", sequence), AtSource: "given"}
}

// demo1Twin is the create's record of demo/1.
func demo1Twin(t *testing.T) wire.TwinRecord {
	return twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Waypoint = showDemo(1)
	})
}

// showStepTarget is the step's target bundle id, pinned at at, as the twin directory holds it,
// each node's artifact checksum from sums, and the three nodes as containerlab reports them
// after the step.
func showStepTarget(id, at string, sums map[string]string) (*lab.StagedTarget, []wire.LabNode) {
	staged := &lab.StagedTarget{BundleID: id,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: at, SchemaHash: "41349c3a9c582e5dd44e55d6771f79c2", ContractVersion: "1"},
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
		From:       wire.StepSide{Waypoint: showDemo(1), BundleID: showBundleID, At: stepFromAt},
		To:         wire.StepSide{Waypoint: showDemo(2), BundleID: stepToID, At: stepToAt},
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
	rec, err := lab.NewStepRecord(demo1Twin(t), f)
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
	side := func(sequence int, id, at string) findings.StepSideBlock {
		return findings.StepSideBlock{Waypoint: &findings.ShowWaypoint{Series: "demo", Sequence: sequence,
			Description: fmt.Sprintf("cut %d", sequence), AtSource: "given"}, BundleID: id, At: at}
	}
	return findings.ShowStep{
		Outcome:   wire.StepStepped,
		From:      side(1, showBundleID, stepFromAt),
		To:        side(2, stepToID, stepToAt),
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

// A stepped twin keeps kind pinned, at the target's at and waypoint, and says which step
// took it there; the record block gains the step's line; every node shows the artifact of
// the bundle it holds, the target's; and the JSON record carries state and step
// (contracts/cli.md, twin show).
func TestShowSteppedRecord(t *testing.T) {
	paths := useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, nil))
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	kind := "pinned at " + stepToAt + ", waypoint demo/2 (stepped from demo/1 by run fylgja-step " + stepShowRunID +
		", ended " + stepEnded + "); not following"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+stepAfter["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+stepAfter["n3"],
		"record: branch fylgja-fixture at "+stepToAt+" (waypoint demo/2, at given), bundle_id "+stepToID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1",
		"  intent read at 2026-10-02T09:14:01.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  stepped from demo/1 by run fylgja-step "+stepShowRunID+", ended "+stepEnded+
			"; reconcile 3.9s (restart n1); readiness n1 54.8s; push n1 1.6s, n2 2.4s",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindPinned, kind)
	r := out.doc.Show.Record
	if r == nil || r.State != wire.StateReady || r.Step == nil || r.Step.Outcome != wire.StepStepped || r.BundleID != stepToID ||
		!slices.Equal(r.Step.Restarted, []string{"n1"}) || r.Step.Phase != "" || r.Step.Run.RunID != stepShowRunID ||
		r.Step.From.Waypoint == nil || r.Step.From.Waypoint.Sequence != 1 || len(r.Step.Pushed) != 2 {
		t.Errorf("record %+v (step %+v)", r, r.Step)
	}
	wantShowStep(t, r, steppedShowStep())

	// An unchanged step is shown as stepped, and its line says nothing was applied.
	paths = useStateRoot(t)
	writeM11Twin(t, paths, steppedTwin(t, func(f *lab.StepFields) {
		f.Outcome, f.Plan, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter, f.Pushed = wire.StepUnchanged,
			wire.ReconcilePlan{}, false, nil, nil, nil
	}))
	out = showWith(t, paths, "inspect-three.json", &fakeService{})
	if want := "  stepped from demo/1 by run fylgja-step " + stepShowRunID + ", ended " + stepEnded +
		"; unchanged: nothing reconciled, awaited or pushed\n"; !strings.Contains(out.stdout, want) ||
		out.doc.Show.Kind != findings.ShowKindPinned || out.doc.Show.Record.Step.Outcome != wire.StepUnchanged {
		t.Errorf("an unchanged step:\n%s", out.stdout)
	}
}

// A twin stepped twice is shown by its second step alone: the kind line and the record's
// step line say it was stepped from demo/2 by the second run, and nothing of the first step
// is shown.
func TestShowTwiceSteppedRecord(t *testing.T) {
	const (
		runB    = "01a2b3c4-0000-7000-8000-000000000003"
		thirdAt = "2026-09-28T15:41:07.500000+00:00"
		endedB  = "2026-10-02T09:26:50Z"
	)
	thirdID := strings.Repeat("6b1d07c2", 8)
	// Each node's artifact checksum at demo/3: n1's does not move from demo/2.
	later := map[string]string{"n1": stepAfter["n1"], "n2": "2d3c5e8a2d3c5e8a2d3c5e8a2d3c5e8a", "n3": "3b8f61c03b8f61c03b8f61c03b8f61c0"}
	took := func(s float64) *float64 { return &s }
	staged, nodes := showStepTarget(thirdID, thirdAt, later)
	rec, err := lab.NewStepRecord(steppedTwin(t, nil), lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Waypoint: showDemo(2), BundleID: stepToID, At: stepToAt},
		To:         wire.StepSide{Waypoint: showDemo(3), BundleID: thirdID, At: thirdAt},
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
	kind := "pinned at " + thirdAt + ", waypoint demo/3 (stepped from demo/2 by run fylgja-step " + runB +
		", ended " + endedB + "); not following"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+later["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+later["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+later["n3"],
		"record: branch fylgja-fixture at "+thirdAt+" (waypoint demo/3, at given), bundle_id "+thirdID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1",
		"  intent read at 2026-10-02T09:25:30.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded "+endedB+", 3 nodes",
		"  stepped from demo/2 by run fylgja-step "+runB+", ended "+endedB+
			"; reconcile 4.2s (restart n2); readiness n2 50.1s; push n2 1.1s, n3 0.8s",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindPinned, kind)
	if strings.Contains(out.stdout+out.stderr, stepShowRunID) {
		t.Errorf("twin show names the first step's run %s:\n%s", stepShowRunID, out.stdout)
	}
	if r := out.doc.Show.Record; r == nil || r.Step == nil || r.Step.Run.RunID != runB || r.Step.From.Waypoint == nil ||
		r.Step.From.Waypoint.Sequence != 2 || !slices.Equal(r.Step.Restarted, []string{"n2"}) {
		t.Errorf("record %+v; want the second step's block, from demo/2", r)
	}
}

// A step whose reconcile recreated one node and created another names both lifecycles on
// the record's step line, and never a node re-cabled live; the JSON's step.restarted holds
// every node the reconcile restarted, recreated or created (contracts/cli.md, twin
// show).
func TestShowStepThatRecreatesAndCreates(t *testing.T) {
	took := func(s float64) *float64 { return &s }
	// demo/1 ran n1 and n2; demo/2 adds n3, cabled to n1, and changes n2's image.
	prev := twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At = stepFromAt
		f.Waypoint = showDemo(1)
		f.Nodes = f.Nodes[:2]
	})
	staged, nodes := showStepTarget(stepToID, stepToAt, stepAfter)
	rec, err := lab.NewStepRecord(prev, lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Waypoint: showDemo(1), BundleID: showBundleID, At: stepFromAt},
		To:         wire.StepSide{Waypoint: showDemo(2), BundleID: stepToID, At: stepToAt},
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
	kind := "pinned at " + stepToAt + ", waypoint demo/2 (stepped from demo/1 by run fylgja-step " + stepShowRunID +
		", ended " + stepEnded + "); not following"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux  device-config "+stepAfter["n1"],
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+stepAfter["n3"],
		"record: branch fylgja-fixture at "+stepToAt+" (waypoint demo/2, at given), bundle_id "+stepToID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1",
		"  intent read at 2026-10-02T09:14:01.000000Z",
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  stepped from demo/1 by run fylgja-step "+stepShowRunID+", ended "+stepEnded+
			"; reconcile 20.3s (recreate n2, create n3); readiness n2 14.1s, n3 31.3s; push n1 0.9s, n2 1.6s, n3 1.2s",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindPinned, kind)
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
	out := showWith(t, paths, "inspect-three.json", &fakeService{following: followingState("fylgja-fixture")})
	kind := "diverged towards waypoint demo/2 (bundle ee291b0f…): run fylgja-step " + stepShowRunID +
		" stopped at phase push; landed: n2; not landed: n1 (push.refused); the twin is at waypoint demo/1 (bundle 893b6392…); " +
		"fylgja twin destroy clears it"
	wantShow(t, out, lines(
		"twin: lab fylgja present (3 nodes); twin directory present",
		"  n1  clab-fylgja-n1  running  172.20.20.2  nokia_srlinux",
		"  n2  clab-fylgja-n2  running  172.20.20.3  nokia_srlinux  device-config "+stepAfter["n2"],
		"  n3  clab-fylgja-n3  running  172.20.20.4  nokia_srlinux  device-config "+fixtureArtifacts["n3"],
		"record: branch fylgja-fixture at "+stepFromAt+" (waypoint demo/1, at given), bundle_id "+showBundleID+
			", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1",
		"  intent read at "+showObserved,
		"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
		"  diverged: step run fylgja-step "+stepShowRunID+" towards demo/2 (bundle ee291b0f…) stopped at phase push, ended "+
			stepEnded+"; landed n2; not landed n1 (push.refused)",
		"kind: "+kind,
		"in flight: none"),
		findings.ShowKindDiverged, kind)
	if strings.Contains(out.stdout, "twin create") || strings.Contains(out.stdout, "following") {
		t.Errorf("a diverged twin is given create advice or a following line:\n%s", out.stdout)
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
			kind := "diverged towards waypoint demo/2 (bundle ee291b0f…): run fylgja-step " + stepShowRunID +
				" stopped at phase " + c.phase + "; landed: " + c.landed + "; not landed: " + c.notLanded +
				"; the twin is at waypoint demo/1 (bundle 893b6392…); fylgja twin destroy clears it"
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
				"record: branch fylgja-fixture at "+stepFromAt+" (waypoint demo/1, at given), bundle_id "+showBundleID+
					", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1",
				"  intent read at "+showObserved,
				"  provisioned by run fylgja-provision "+showRunID+" (source intent), worker 0.1.0-dev, recorded 2026-10-02T09:15:41Z, 3 nodes",
				"  diverged: step run fylgja-step "+stepShowRunID+" towards demo/2 (bundle ee291b0f…) stopped at phase "+c.phase+
					", ended "+stepEnded+"; landed "+c.landed+"; not landed "+c.notLanded,
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
// kind line, as M4 names a rebuild, with the waypoint it steps towards; before its stage it
// is only listed in flight (contracts/cli.md).
func TestShowStepInFlight(t *testing.T) {
	const pinned = "pinned at " + stepFromAt + ", waypoint demo/1; not following"
	// Before its stage (start, inspect, host_check, and compare, the plan's second lock) a
	// step run has touched nothing on the host, and is listed under in flight: alone.
	// So is one at observe, its wait after the record: the record is already written, so the
	// kind line needs no clause.
	before := []string{findings.StepStart, findings.StepInspect, findings.StepHostCheck, findings.StepCompare,
		findings.StepObserve}
	for _, step := range []string{findings.StepStage, findings.StepReconcile, findings.StepReadiness, findings.StepPush,
		findings.StepRecord, findings.StepStart, findings.StepInspect, findings.StepHostCheck, findings.StepCompare,
		findings.StepObserve} {
		t.Run(step, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, demo1Twin(t))
			svc := &fakeService{inFlight: []provision.RunInFlight{
				{WorkflowID: "fylgja-step", RunID: stepShowRunID, Step: step, Towards: "demo/2"}}}
			out := showWith(t, paths, "inspect-three.json", svc)
			running := "run fylgja-step " + stepShowRunID + " is at step " + step + ", stepping towards waypoint demo/2"
			kind, notes := pinned+"; "+running, []string{pinned, running}
			if slices.Contains(before, step) {
				kind, notes = pinned, []string{pinned}
			}
			want := "kind: " + kind + "\nin flight: run fylgja-step " + stepShowRunID + " at step " + step + "\n"
			if !strings.HasSuffix(out.stdout, want) {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, want)
			}
			if s := out.doc.Show; s.Kind != findings.ShowKindPinned || !slices.Equal(s.Notes, notes) ||
				len(s.InFlight) != 1 || s.InFlight[0].WorkflowID != "fylgja-step" || s.InFlight[0].Step != step {
				t.Errorf("show %+v", s)
			}
		})
	}
	// A step run whose target the service could not read from its input (Towards "") is
	// still named at the host, without the clause naming where it steps.
	t.Run("a target that cannot be read", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, demo1Twin(t))
		svc := &fakeService{inFlight: []provision.RunInFlight{
			{WorkflowID: "fylgja-step", RunID: stepShowRunID, Step: findings.StepReconcile}}}
		out := showWith(t, paths, "inspect-three.json", svc)
		running := "run fylgja-step " + stepShowRunID + " is at step " + findings.StepReconcile
		want := "kind: " + pinned + "; " + running + "\nin flight: run fylgja-step " + stepShowRunID + " at step " +
			findings.StepReconcile + "\n"
		if !strings.HasSuffix(out.stdout, want) || strings.Contains(out.stdout, "stepping towards") {
			t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, want)
		}
		if s := out.doc.Show; s.Kind != findings.ShowKindPinned || !slices.Equal(s.Notes, []string{pinned, running}) {
			t.Errorf("show %+v; want kind pinned, notes %q", s, []string{pinned, running})
		}
	})
}

// A version 3 record, written before M11, and a version 4 record that has not stepped are
// shown as M10 shows them, line for line; only the 4 record's JSON carries its state.
func TestShowVersion3And4RecordsAsM10(t *testing.T) {
	const kind = "pinned at " + stepFromAt + ", waypoint demo/1; not following"
	want := threeNodes +
		"record: branch fylgja-fixture at " + stepFromAt + " (waypoint demo/1, at given), bundle_id " + showBundleID +
		", schema 41349c3a9c582e5dd44e55d6771f79c2, contract 1\n" +
		"  intent read at " + showObserved + "\n" + provisionedLine + lines("kind: "+kind, "in flight: none")
	for _, version := range []string{"3", "4"} {
		t.Run("version "+version, func(t *testing.T) {
			paths := useStateRoot(t)
			raw, err := json.Marshal(demo1Twin(t))
			if err != nil {
				t.Fatal(err)
			}
			// NewRecord writes the current version, 5 since M12; a create's 4 differs from
			// it by the version alone, since step is null in both.
			var generic map[string]any
			if err := json.Unmarshal(raw, &generic); err != nil {
				t.Fatal(err)
			}
			generic["twin_version"] = version
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
			wantShow(t, out, want, findings.ShowKindPinned, kind)
			b, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			if hasState := strings.Contains(string(b), `"state":"ready"`); hasState != (version == "4") || strings.Contains(string(b), `"step":{`) {
				t.Errorf("version %s's document: %s", version, b)
			}
		})
	}
}

// A version 5 record's step line ends with how the step's wait ended, after M11's timings or
// after a diverged step's pushes, and the JSON record.step carries the wait by identifier and
// object, or null while it has not run (contracts/cli.md, twin show). The kind line is M11's.
func TestShowStepWait(t *testing.T) {
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "node " + object + " sees no neighbour"}
	}
	stepped := "  stepped from demo/1 by run fylgja-step " + stepShowRunID + ", ended " + stepEnded +
		"; reconcile 3.9s (restart n1); readiness n1 54.8s; push n1 1.6s, n2 2.4s"
	diverged := "  diverged: step run fylgja-step " + stepShowRunID + " towards demo/2 (bundle " + short(stepToID) +
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
			if rec.TwinVersion != "5" {
				t.Fatalf("lab.NewStepRecord wrote version %q, want 5", rec.TwinVersion)
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

// A version 5 record written by a create (step: null) is shown exactly as the same record
// written as version 4: no step line and no step key.
func TestShowCreatedVersion5RecordAsM11(t *testing.T) {
	show := func(write func(*testing.T, lab.Paths, wire.TwinRecord)) showOutput {
		paths := useStateRoot(t)
		write(t, paths, demo1Twin(t))
		return showWith(t, paths, "inspect-three.json", &fakeService{})
	}
	five, four := show(writeTwin), show(writeM11Twin)
	if demo1Twin(t).TwinVersion != "5" {
		t.Fatalf("a create's record is version %q, want 5", demo1Twin(t).TwinVersion)
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
