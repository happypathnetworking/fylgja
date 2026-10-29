package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// twinSchema is the current contract the record satisfies: twin.json 12, which NewRecord and
// NewStepRecord write, under the module root's contracts/.
func twinSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return twinSchemaOf(t, "")
}

// twinSchemaOf is feature's copy of twin.schema.json: "" is the current contract, and an
// earlier feature's is its frozen copy under testdata/contracts/<feature>/, which keeps the
// records its milestone wrote, such as M11's 4 (009-stepping), M12's 5 (010-verify), 014's
// 6 (014-proposed-change-stages), 015's 7 (015-proposed-change-rehearsal), 017's 8
// (017-dcim-reader), 018's 9 (018-snapshots), 019's 10 (019-following-removed) and 016's 11
// (contract016).
func twinSchemaOf(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	path := filepath.Join("..", "..", "contracts", "twin.schema.json")
	if feature != "" {
		path = filepath.Join("testdata", "contracts", feature, "twin.schema.json")
	}
	f, err := os.Open(path)
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
	s, err := c.Compile("twin.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// contract016 is the directory 016's copy of twin.schema.json, twin.json 11, which 020 moves
// to 12, is frozen under.
const contract016 = "016-probes"

// dcimMapping is the mapping a twin.json 8 record's provenance names when the Infrahub
// reader read the schema library's DCIM (017).
var dcimMapping = wire.Mapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}

func fields(source string, observedAt *string) RecordFields {
	return RecordFields{
		BundleID:   "4d5f3e2308a8248f600c2dcf83cc360f6101ca97a9ca717dc2b6e0c02827e31a",
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc123", Scope: "tag:fylgja", Mapping: dcimMapping},
		ObservedAt: observedAt,
		Source:     source,
		RunID:      "01a0a570-0395-78ee-8d0f-9a45a97547cd",
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 15, 14, 22, 53, 390000000, time.UTC),
		Nodes: []wire.TwinNode{
			{Name: "n2", Container: "clab-fylgja-n2", Image: "ghcr.io/nokia/srlinux:24.7.1",
				PSP: &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}, MgmtIPv4: "172.20.20.3", ReadyAfterS: 0.897,
				Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: "ecb03029ea805a09c54d2cd6a0e59ac9", Size: 861},
				PushedInS: 0.7},
			{Name: "n1", Container: "clab-fylgja-n1", Image: "ghcr.io/nokia/srlinux:24.7.1",
				PSP: &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}, MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.761,
				Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: "43e8fd0c2de5f4646f74a51d34742824", Size: 861},
				PushedInS: 0.66},
		},
	}
}

func validateRecord(t *testing.T, s *jsonschema.Schema, rec wire.TwinRecord) {
	t.Helper()
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Validate(v); err != nil {
		t.Errorf("record does not satisfy twin.schema.json:\n%v\n%s", err, b)
	}
}

func TestRecordsSatisfyTheSchema(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-09-15T14:22:12.000000Z"

	intent, err := NewRecord(fields(wire.SourceIntent, &observed))
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, s, intent)
	if intent.ObservedAtNote != "" {
		t.Errorf("a record with observed_at must carry no note, got %q", intent.ObservedAtNote)
	}
	if intent.Nodes[0].Name != "n1" || intent.Nodes[1].Name != "n2" {
		t.Errorf("nodes are not sorted by name: %+v", intent.Nodes)
	}
	if intent.Run.WorkflowID != "fylgja-provision" || intent.Lab != "fylgja" {
		t.Errorf("fixed identities wrong: run %+v, lab %q", intent.Run, intent.Lab)
	}

	fromBundle, err := NewRecord(fields(wire.SourceBundle, nil))
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, s, fromBundle)
	if fromBundle.ObservedAtNote != ObservedAtUnknown {
		t.Errorf("note = %q, want %q", fromBundle.ObservedAtNote, ObservedAtUnknown)
	}
}

// A record the contract would refuse is refused when built, not discovered by whoever
// reads twin.json later (Constitution VI).
func TestNewRecordRefusesAContradictoryRecord(t *testing.T) {
	observed := "2026-09-15T14:22:12.000000Z"
	for label, f := range map[string]RecordFields{
		"intent without observed_at": fields(wire.SourceIntent, nil),
		"bundle with observed_at":    fields(wire.SourceBundle, &observed),
		"unknown source":             fields("guess", nil),
	} {
		if _, err := NewRecord(f); err == nil {
			t.Errorf("%s: NewRecord accepted it", label)
		}
	}
	bad := fields(wire.SourceBundle, nil)
	bad.BundleID = "not-an-id"
	if _, err := NewRecord(bad); err == nil {
		t.Error("NewRecord accepted a bundle_id that is not an identity")
	}
}

// jsonOf is v marshalled and read back as JSON's own values, so a test compares what is
// written rather than the type that writes it.
func jsonOf(t *testing.T, v any) any {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

// stage11 is a stage as a record of twin.json 6 to 11 names it, change-1/seeded, its at
// given on the mark (014): what 020 no longer records (research R-06).
func stage11() map[string]any {
	return map[string]any{"proposed_change": map[string]any{"id": "pc-1", "branch": "change-1"},
		"label": "seeded", "description": "the devices, no links", "at_source": findings.AtSourceGiven}
}

// rehearsal11 is a rehearsal run as a record of twin.json 7 to 11 names its baseline's (015):
// what 020 no longer records (research R-06).
func rehearsal11() map[string]any {
	return map[string]any{"workflow_id": wire.RehearseWorkflowID, "run_id": "01a1b2c3-0000-7000-8000-0000000000a1"}
}

// withStage is a record as a worker of twin.json 6 to 11 wrote it, in generic, a record as
// JSON: a stage and a rehearsal at the top level, each given or null, and a stage on each
// step side, null there; keys 020 removed (research R-06). A 6 has no rehearsal, which its
// test deletes.
func withStage(generic map[string]any, stage, rehearsal any) {
	generic["stage"], generic["rehearsal"] = stage, rehearsal
	if step, ok := generic["step"].(map[string]any); ok {
		for _, side := range []string{"from", "to"} {
			step[side].(map[string]any)["stage"] = nil
		}
	}
}

// A record of twin.json 12 names no stage and no rehearsal, which are the orchestrator's
// (020, FR-007, research R-06, SC-004): a create's record of each source, built by NewRecord,
// and a step's, built by NewStepRecord, are written, satisfy the current contract, read back
// by ReadRecord equal, and carry neither key, at the top level or on a step's side; and the
// contract refuses either key, null or not.
func TestRecord12NamesNoStageAndNoRehearsal(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-10-29T09:31:02.118842Z"
	ofSnapshot := fields(wire.SourceSnapshot, &observed)
	ofSnapshot.SnapshotID = threeNodeSnapshot
	pinned := fields(wire.SourceIntent, &observed)
	pinned.Provenance.Branch, pinned.Provenance.At, pinned.SnapshotID = "change-1", "2026-10-29T09:00:00+00:00", threeNodeSnapshot
	records := map[string]wire.TwinRecord{}
	for name, f := range map[string]RecordFields{"an intent twin": fields(wire.SourceIntent, &observed), "a pinned intent twin": pinned,
		"a snapshot twin": ofSnapshot, "a bundle twin": fields(wire.SourceBundle, nil)} {
		rec, err := NewRecord(f)
		if err != nil {
			t.Fatal(err)
		}
		records[name] = rec
	}
	f := stepFields()
	f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot
	step, err := NewStepRecord(stepPrevWith(t, func(f *RecordFields) { f.SnapshotID = lossySnapshot }), f)
	if err != nil {
		t.Fatal(err)
	}
	records["a step"] = step
	for name, rec := range records {
		t.Run(name, func(t *testing.T) {
			if TwinVersion != "12" || rec.TwinVersion != TwinVersion {
				t.Errorf("twin_version %s (this build's %s); want 12", rec.TwinVersion, TwinVersion)
			}
			path := filepath.Join(t.TempDir(), "twin.json")
			if err := WriteRecord(path, rec); err != nil {
				t.Fatal(err)
			}
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			validateBytes(t, s, b)
			got, err := ReadRecord(path)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, rec) {
				t.Errorf("read back\n%+v\nwant\n%+v", got, rec)
			}
			generic := jsonOf(t, rec).(map[string]any)
			for _, key := range []string{"stage", "rehearsal"} {
				if v, ok := generic[key]; ok {
					t.Errorf("the record writes %s: %v; twin.json 12 names none", key, v)
				}
			}
			if st, ok := generic["step"].(map[string]any); ok {
				for _, side := range []string{"from", "to"} {
					if v, ok := st[side].(map[string]any)["stage"]; ok {
						t.Errorf("step.%s writes stage: %v; twin.json 12 names none", side, v)
					}
				}
			}
		})
	}

	t.Run("the contract refuses a stage or a rehearsal", func(t *testing.T) {
		for _, c := range []struct {
			name   string
			rec    wire.TwinRecord
			change func(g map[string]any)
		}{
			{"a stage", records["a pinned intent twin"], func(g map[string]any) { g["stage"] = stage11() }},
			{"a null stage", records["an intent twin"], func(g map[string]any) { g["stage"] = nil }},
			{"a rehearsal", records["a pinned intent twin"], func(g map[string]any) { g["rehearsal"] = rehearsal11() }},
			{"a null rehearsal", records["an intent twin"], func(g map[string]any) { g["rehearsal"] = nil }},
			{"a stage on a step's side", records["a step"], func(g map[string]any) {
				g["step"].(map[string]any)["to"].(map[string]any)["stage"] = stage11()
			}},
			{"a null stage on a step's side", records["a step"], func(g map[string]any) {
				g["step"].(map[string]any)["from"].(map[string]any)["stage"] = nil
			}},
			{"twin_version 11", records["an intent twin"], func(g map[string]any) { g["twin_version"] = "11" }},
		} {
			generic := jsonOf(t, c.rec).(map[string]any)
			c.change(generic)
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Errorf("%s: twin.schema.json 12 accepts it", c.name)
			}
		}
	})
}

// A record of twin.json 11, as 016's build wrote it naming a stage and a rehearsal, is its
// frozen contract's and not the current one's; ReadRecord reads it, gating no version, with
// TwinVersion 11, so twin show shows it with its version, and its bundle, snapshot and nodes
// as written, its stage and rehearsal not read; and a step's record built from it is twin.json
// 12 (020, research R-06, SC-004). twin step refuses such a twin before any run (the server's
// step.twin.unsteppable); this is the record's own rule beneath it.
func TestRecord11StillReads(t *testing.T) {
	s, v11 := twinSchema(t), twinSchemaOf(t, contract016)
	create := stepPrevWith(t, func(f *RecordFields) { f.SnapshotID = lossySnapshot })
	f := stepFields()
	f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot
	step, err := NewStepRecord(create, f)
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait, step.Step.Loss = waits()["settled"], losses()["measured"]
	for name, rec := range map[string]wire.TwinRecord{"a rehearsal's baseline": create, "a step": step} {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "11"
			withStage(generic, stage11(), rehearsal11())
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v11, b)
			v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Error("twin.schema.json 12 accepts a record of 11 naming a stage and a rehearsal")
			}
			got := readBytes(t, b)
			if got.TwinVersion != "11" || got.BundleID != rec.BundleID || got.SnapshotID == nil ||
				*got.SnapshotID != *rec.SnapshotID || !reflect.DeepEqual(got.Nodes, rec.Nodes) {
				t.Errorf("read twin_version %s, bundle %s, snapshot %v, nodes %+v; want 11 and the record's %s, %s and %+v",
					got.TwinVersion, got.BundleID, got.SnapshotID, got.Nodes, rec.BundleID, *rec.SnapshotID, rec.Nodes)
			}
			want := rec
			want.TwinVersion = "11"
			if !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v, as written but for its stage and rehearsal", got, want)
			}
			if name != "a rehearsal's baseline" {
				return
			}
			next, err := NewStepRecord(got, f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, next)
			if next.TwinVersion != "12" {
				t.Errorf("a step from a record of 11 writes twin_version %s, want 12", next.TwinVersion)
			}
			out := jsonOf(t, next).(map[string]any)
			if _, staged := out["stage"]; staged {
				t.Errorf("a step from a record of 11 writes its stage: %v", out["stage"])
			}
			if _, rehearsed := out["rehearsal"]; rehearsed {
				t.Errorf("a step from a record of 11 writes its rehearsal: %v", out["rehearsal"])
			}
		})
	}
}

// version2Record is a record an M5 worker wrote: twin.json 2, with no key for a pinned
// reference.
const version2Record = `{
  "twin_version": "2",
  "lab": "fylgja",
  "bundle_id": "4d5f3e2308a8248f600c2dcf83cc360f6101ca97a9ca717dc2b6e0c02827e31a",
  "provenance": {"branch": "fylgja-fixture", "at": "2026-09-20T10:00:00Z", "schema_hash": "abc123", "contract_version": "0.2"},
  "observed_at": "2026-09-20T10:01:02.000000Z",
  "source": "intent",
  "run": {"workflow_id": "fylgja-provision", "run_id": "01a0a570-0395-78ee-8d0f-9a45a97547cd"},
  "provisioned_by": {"version": "0.1.0-dev"},
  "recorded_at": "2026-09-20T10:02:00Z",
  "nodes": []
}
`

// m10Waypoint is M10's pinned reference as twin.json 3 to 5 name it, which this build no
// longer reads (014, research R-11).
func m10Waypoint(sequence int) map[string]any {
	return map[string]any{"series": "demo", "sequence": sequence, "description": "after the first cut-over", "at_source": "written"}
}

// olderRecord is rec as a worker of twin.json version, 4 or 5, wrote it: no snapshot is
// named (unsnapshotted), the provenance names the contract version and no scope or mapping
// (contractProvenance), the rehearsal key is not there, the stage key gives way to M10's,
// top at the top level and from and to on the step's sides (nil writes null), and a 4's
// step has no wait.
func olderRecord(t *testing.T, rec wire.TwinRecord, version string, top, from, to any) []byte {
	t.Helper()
	generic := jsonOf(t, rec).(map[string]any)
	generic["twin_version"] = version
	unsnapshotted(generic)
	contractProvenance(generic)
	delete(generic, "rehearsal")
	delete(generic, "stage")
	generic["waypoint"] = top
	if step, ok := generic["step"].(map[string]any); ok {
		for side, ref := range map[string]any{"from": from, "to": to} {
			s := step[side].(map[string]any)
			delete(s, "stage")
			s["waypoint"] = ref
		}
		if version == "4" {
			delete(step, "wait")
		}
	}
	b, err := json.MarshalIndent(generic, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return b
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

// unlossed is a record as a worker of twin.json 10 or earlier wrote it, in generic, a record
// as JSON: no loss in its step block, which 016 added.
func unlossed(generic map[string]any) {
	if step, ok := generic["step"].(map[string]any); ok {
		delete(step, "loss")
	}
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

// unsnapshot is rec as ReadRecord reads it back from a record of twin.json 8 or earlier:
// naming no snapshot, at the top level or on a step's sides (018).
func unsnapshot(rec wire.TwinRecord) wire.TwinRecord {
	rec.SnapshotID = nil
	if rec.Step != nil {
		st := *rec.Step
		st.From.SnapshotID, st.To.SnapshotID = "", ""
		rec.Step = &st
	}
	return rec
}

// unscoped is rec as ReadRecord reads it back from a record of twin.json 7 or earlier: with
// no scope and no mapping, which such a record does not name (017).
func unscoped(rec wire.TwinRecord) wire.TwinRecord {
	rec.Provenance.Scope, rec.Provenance.Mapping = "", wire.Mapping{}
	return rec
}

// validateBytes holds b, a record as some worker wrote it, to the contract s.
func validateBytes(t *testing.T, s *jsonschema.Schema, b []byte) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Validate(v); err != nil {
		t.Fatalf("the record is not its version's:\n%v\n%s", err, b)
	}
}

// readBytes is b as ReadRecord reads it from a twin directory.
func readBytes(t *testing.T, b []byte) wire.TwinRecord {
	t.Helper()
	path := filepath.Join(t.TempDir(), "twin.json")
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	rec, err := ReadRecord(path)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

// A record of 5 or earlier still reads (014, research R-11): M10's waypoint, which this
// build no longer reads, is not read, whether named or null, nor sniffed (020, research
// R-06), and a version 2 one with no key reads too. Each version 5 record is one twin.json
// 5's frozen contract accepts, and reads with everything else as written.
func TestRecord5ReadsWithNoWaypoint(t *testing.T) {
	v5 := twinSchemaOf(t, "010-verify")
	observed := "2026-09-28T15:31:02.118842Z"
	pinned := fields(wire.SourceIntent, &observed)
	pinned.Provenance.At = "2026-09-28T15:20:44.000000+00:00"
	create, err := NewRecord(pinned)
	if err != nil {
		t.Fatal(err)
	}
	step, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	unstaged := func(rec wire.TwinRecord) wire.TwinRecord {
		rec = unscoped(rec)
		rec.TwinVersion = "5"
		return rec
	}
	for _, c := range []struct {
		name string
		b    []byte
		want wire.TwinRecord
	}{
		{"a create naming a waypoint", olderRecord(t, create, "5", m10Waypoint(2), nil, nil), unstaged(create)},
		{"a create naming none", olderRecord(t, create, "5", nil, nil, nil), unstaged(create)},
		{"a step between two waypoints", olderRecord(t, step, "5", m10Waypoint(2), m10Waypoint(1), m10Waypoint(2)), unstaged(step)},
	} {
		t.Run(c.name, func(t *testing.T) {
			validateBytes(t, v5, c.b)
			got := readBytes(t, c.b)
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("read %+v\nwant %+v", got, c.want)
			}
		})
	}

	t.Run("a version 2 record", func(t *testing.T) {
		rec := readBytes(t, []byte(version2Record))
		if rec.TwinVersion != "2" || rec.Provenance.At != "2026-09-20T10:00:00Z" {
			t.Errorf("read %+v; want version 2 and its at", rec)
		}
	})
}

// mustJSON is v as JSON text.
func mustJSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// A record of 6 still reads (015): a create's and a step's record as a 014 worker wrote
// them, the create naming its stage, which twin.json 6's frozen contract accepts, read with
// everything else as written, its stage not read (020, research R-06).
func TestRecord6StillReads(t *testing.T) {
	v6 := twinSchemaOf(t, "014-proposed-change-stages")
	observed := "2026-10-16T09:31:02.118842Z"
	staged := fields(wire.SourceIntent, &observed)
	staged.Provenance.At = "2026-10-16T09:00:00+00:00"
	create, err := NewRecord(staged)
	if err != nil {
		t.Fatal(err)
	}
	step, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	for name, rec := range map[string]wire.TwinRecord{"a create": create, "a step": step} {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "6"
			unsnapshotted(generic)
			contractProvenance(generic)
			withStage(generic, nil, nil)
			if name == "a create" {
				generic["stage"] = stage11()
			}
			delete(generic, "rehearsal")
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v6, b)
			got := readBytes(t, b)
			want := unscoped(rec)
			want.TwinVersion = "6"
			if !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v", got, want)
			}
		})
	}
}

// A create's record names its provenance as twin.json 8 began to (017) and 10 still does: the
// manifest's, naming the scope the read was made under and the mapping that read it, in
// place of the contract version; a step's record carries the target's after a stepped step
// and the create's after a diverged one. The contract refuses a provenance with either left
// out or malformed, or naming the contract version 017 removed, and NewRecord refuses fields
// naming no scope or mapping.
func TestRecordNamesItsProvenance(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-10-25T09:31:02.118842Z"
	wantProvenance := map[string]any{"branch": "fylgja-fixture", "schema_hash": "abc123", "scope": "tag:fylgja",
		"mapping": map[string]any{"reader": "infrahub-dcim", "model": "opsmill/schema-library", "version": "26336e9"}}

	t.Run("a create's record", func(t *testing.T) {
		for label, f := range map[string]RecordFields{
			"intent": fields(wire.SourceIntent, &observed),
			"bundle": fields(wire.SourceBundle, nil),
		} {
			rec, err := NewRecord(f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			got := jsonOf(t, rec).(map[string]any)
			if got["twin_version"] != TwinVersion || !reflect.DeepEqual(got["provenance"], wantProvenance) {
				t.Errorf("%s: twin_version %v, provenance %v; want %s with %v", label, got["twin_version"], got["provenance"], TwinVersion, wantProvenance)
			}
		}
	})

	t.Run("a step's record", func(t *testing.T) {
		prev := stepPrev(t)
		stepped, err := NewStepRecord(prev, stepFields())
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, stepped)
		if want := stepTarget().Provenance; stepped.Provenance != want {
			t.Errorf("stepped: provenance %+v, want the target's %+v", stepped.Provenance, want)
		}
		f := stepFields()
		f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
		f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
		diverged, err := NewStepRecord(prev, f)
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, diverged)
		if diverged.Provenance != prev.Provenance {
			t.Errorf("diverged: provenance %+v, want the create's %+v", diverged.Provenance, prev.Provenance)
		}
	})

	t.Run("the contract refuses a provenance it cannot hold", func(t *testing.T) {
		rec, err := NewRecord(fields(wire.SourceIntent, &observed))
		if err != nil {
			t.Fatal(err)
		}
		for label, change := range map[string]func(p map[string]any){
			"no scope":                 func(p map[string]any) { delete(p, "scope") },
			"a scope not tag:<name>":   func(p map[string]any) { p["scope"] = "fylgja" },
			"an empty scope":           func(p map[string]any) { p["scope"] = "" },
			"no mapping":               func(p map[string]any) { delete(p, "mapping") },
			"a mapping with no reader": func(p map[string]any) { delete(p["mapping"].(map[string]any), "reader") },
			"an empty model":           func(p map[string]any) { p["mapping"].(map[string]any)["model"] = "" },
			"the contract version":     func(p map[string]any) { p["contract_version"] = "0.2" },
		} {
			generic := jsonOf(t, rec).(map[string]any)
			change(generic["provenance"].(map[string]any))
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Errorf("%s: twin.schema.json 12 accepts it", label)
			}
		}
		generic := jsonOf(t, rec).(map[string]any)
		generic["twin_version"] = "7"
		v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
		if err != nil {
			t.Fatal(err)
		}
		if err := s.Validate(v); err == nil {
			t.Error("twin_version 7: twin.schema.json 12 accepts it")
		}
	})

	t.Run("NewRecord refuses a provenance the contract would", func(t *testing.T) {
		for label, change := range map[string]func(p *wire.Provenance){
			"no scope":   func(p *wire.Provenance) { p.Scope = "" },
			"no mapping": func(p *wire.Provenance) { p.Mapping = wire.Mapping{} },
			"no version": func(p *wire.Provenance) { p.Mapping.Version = "" },
			// The contract's forms, as validation holds a CTM's envelope to them (T084).
			"a scope not tag:<name>":   func(p *wire.Provenance) { p.Scope = "fylgja" },
			"a scope naming no tag":    func(p *wire.Provenance) { p.Scope = "tag:" },
			"a scope of two words":     func(p *wire.Provenance) { p.Scope = "tag:a b" },
			"a reader not of its form": func(p *wire.Provenance) { p.Mapping.Reader = "Infrahub DCIM" },
		} {
			f := fields(wire.SourceIntent, &observed)
			change(&f.Provenance)
			if _, err := NewRecord(f); err == nil || !strings.Contains(err.Error(), "names the scope its read was made under") {
				t.Errorf("%s: err = %v, want a refusal naming the scope and the mapping", label, err)
			}
			// What NewRecord refuses, the contract refuses: the record is never written
			// to be refused by its reader.
			accepted := fields(wire.SourceIntent, &observed)
			rec, err := NewRecord(accepted)
			if err != nil {
				t.Fatal(err)
			}
			change(&rec.Provenance)
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, rec)))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Errorf("%s: NewRecord refuses it, and twin.schema.json 12 accepts it", label)
			}
		}
	})
}

// A record of 7 still reads, with no scope and no mapping (017): a create's and a step's
// record as a 015 worker wrote them, naming the contract version in their provenance and
// the create its stage and rehearsal, which twin.json 7's frozen contract accepts, read with
// Scope and Mapping empty and everything else as written, its stage and rehearsal not read
// (020, research R-06), so twin show shows the scope unknown and twin step refuses the twin.
func TestRecord7ReadsWithNoScope(t *testing.T) {
	v7 := twinSchemaOf(t, "015-proposed-change-rehearsal")
	observed := "2026-10-19T09:31:02.118842Z"
	staged := fields(wire.SourceIntent, &observed)
	staged.Provenance.Branch, staged.Provenance.At = "change-1", "2026-10-19T09:00:00+00:00"
	create, err := NewRecord(staged)
	if err != nil {
		t.Fatal(err)
	}
	step, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	for name, rec := range map[string]wire.TwinRecord{"a rehearsal's baseline": create, "a step": step} {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "7"
			unsnapshotted(generic)
			contractProvenance(generic)
			withStage(generic, nil, nil)
			if name == "a rehearsal's baseline" {
				withStage(generic, stage11(), rehearsal11())
			}
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v7, b)
			got := readBytes(t, b)
			want := unscoped(rec)
			want.TwinVersion = "7"
			if got.Provenance.Scope != "" || got.Provenance.Mapping != (wire.Mapping{}) || !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v, with no scope and no mapping", got, want)
			}
		})
	}
	t.Run("an 8 record is not a 7 one", func(t *testing.T) {
		generic := jsonOf(t, create).(map[string]any)
		generic["twin_version"] = "8"
		unsnapshotted(generic)
		withStage(generic, stage11(), rehearsal11())
		v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
		if err != nil {
			t.Fatal(err)
		}
		if err := v7.Validate(v); err == nil {
			t.Error("twin.json 7's frozen contract accepts an 8 record")
		}
	})
}

// The snapshot ids of the examples (018): the three fixture CTMs wrapped, as
// testdata/snapshot/ holds them. A record names an id and reads nothing behind it, so any
// identity serves; these are real ones.
const (
	threeNodeSnapshot = "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00"
	lossySnapshot     = "91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c"
	mixedSnapshot     = "f3980cc735805c92c13be816c5dadd77c19f321c4c486808511b068f3a9659ff"
)

// A create's record names the snapshot as twin.json 9 began to (018) and 10 still does: the
// snapshot the twin was built from, or "snapshot_id": null explicitly. An intent twin names
// the one its run was given, and none when given none, as an earlier build's rebuild was; a
// snapshot twin names its own and records the snapshot's stored take as observed_at; a
// bundle twin names none. A step's record moves the top level to the to side's snapshot after a stepped
// step, null when the to side names none, and keeps the previous record's after a diverged
// one; each side names its snapshot when it is known. NewRecord refuses what the contract
// refuses.
func TestRecord9(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-10-27T09:31:02.118842Z"
	named := func(f RecordFields, id string) RecordFields {
		f.SnapshotID = id
		return f
	}
	snapshotOf := func(t *testing.T, rec wire.TwinRecord) any {
		t.Helper()
		got, ok := jsonOf(t, rec).(map[string]any)["snapshot_id"]
		if !ok {
			t.Fatalf("the record has no snapshot_id key; a record naming none must say null explicitly")
		}
		return got
	}

	t.Run("a create's record", func(t *testing.T) {
		pinned := named(fields(wire.SourceSnapshot, &observed), threeNodeSnapshot)
		pinned.Provenance.At = "2026-10-27T09:00:00.000000+00:00"
		for _, c := range []struct {
			name string
			f    RecordFields
			want any
		}{
			{"intent, read and taken by the server", named(fields(wire.SourceIntent, &observed), threeNodeSnapshot), threeNodeSnapshot},
			{"intent, a rebuild naming none", fields(wire.SourceIntent, &observed), nil},
			{"snapshot", named(fields(wire.SourceSnapshot, &observed), threeNodeSnapshot), threeNodeSnapshot},
			{"snapshot of a pinned read", pinned, threeNodeSnapshot},
			{"bundle", fields(wire.SourceBundle, nil), nil},
		} {
			t.Run(c.name, func(t *testing.T) {
				rec, err := NewRecord(c.f)
				if err != nil {
					t.Fatal(err)
				}
				validateRecord(t, s, rec)
				got := jsonOf(t, rec).(map[string]any)
				if snap := snapshotOf(t, rec); got["twin_version"] != TwinVersion || snap != c.want || got["source"] != c.f.Source {
					t.Errorf("twin_version %v, snapshot_id %v, source %v; want %s, %v, %s", got["twin_version"], snap, got["source"], TwinVersion, c.want, c.f.Source)
				}
			})
		}
		rec, err := NewRecord(named(fields(wire.SourceSnapshot, &observed), threeNodeSnapshot))
		if err != nil {
			t.Fatal(err)
		}
		if rec.ObservedAt == nil || *rec.ObservedAt != observed || rec.ObservedAtNote != "" {
			t.Errorf("observed_at %v, note %q; want the take's %s and no note", rec.ObservedAt, rec.ObservedAtNote, observed)
		}
	})

	t.Run("NewRecord refuses a snapshot it cannot hold", func(t *testing.T) {
		for _, c := range []struct {
			name string
			f    RecordFields
			want string
		}{
			{"a snapshot twin naming none", fields(wire.SourceSnapshot, &observed), "a twin created from a snapshot must name the snapshot"},
			{"a snapshot twin with no observed_at", named(fields(wire.SourceSnapshot, nil), threeNodeSnapshot), "must record when the snapshot's intent was observed"},
			{"a bundle twin naming one", named(fields(wire.SourceBundle, nil), threeNodeSnapshot), "a twin provisioned from a bundle had no snapshot, so it cannot record snapshot " + threeNodeSnapshot},
			{"an id that is not one", named(fields(wire.SourceIntent, &observed), "6A8A77FC"), `"6A8A77FC" is not a snapshot identity`},
			{"an id of another length", named(fields(wire.SourceSnapshot, &observed), threeNodeSnapshot[:63]), "is not a snapshot identity"},
		} {
			if _, err := NewRecord(c.f); err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("%s: err = %v, want one saying %q", c.name, err, c.want)
			}
		}
	})

	t.Run("the contract refuses what NewRecord does", func(t *testing.T) {
		ofSnapshot, err := NewRecord(named(fields(wire.SourceSnapshot, &observed), threeNodeSnapshot))
		if err != nil {
			t.Fatal(err)
		}
		ofBundle, err := NewRecord(fields(wire.SourceBundle, nil))
		if err != nil {
			t.Fatal(err)
		}
		for _, c := range []struct {
			name   string
			rec    wire.TwinRecord
			change func(g map[string]any)
		}{
			{"no snapshot_id key", ofSnapshot, func(g map[string]any) { delete(g, "snapshot_id") }},
			{"a snapshot twin naming none", ofSnapshot, func(g map[string]any) { g["snapshot_id"] = nil }},
			{"a snapshot twin with no observed_at", ofSnapshot, func(g map[string]any) {
				g["observed_at"], g["observed_at_note"] = nil, ObservedAtUnknown
			}},
			{"a snapshot twin naming a stage", ofSnapshot, func(g map[string]any) { g["stage"] = stage11() }},
			{"an id that is not one", ofSnapshot, func(g map[string]any) { g["snapshot_id"] = "6A8A77FC" }},
			{"a bundle twin naming one", ofBundle, func(g map[string]any) { g["snapshot_id"] = threeNodeSnapshot }},
			{"another source", ofSnapshot, func(g map[string]any) { g["source"] = "ctm" }},
			{"twin_version 8", ofSnapshot, func(g map[string]any) { g["twin_version"] = "8" }},
			{"twin_version 9", ofSnapshot, func(g map[string]any) { g["twin_version"] = "9" }},
		} {
			generic := jsonOf(t, c.rec).(map[string]any)
			c.change(generic)
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Errorf("%s: twin.schema.json 12 accepts it", c.name)
			}
		}
	})

	t.Run("a step's record", func(t *testing.T) {
		prev := stepPrev(t)
		prev.SnapshotID = snapshotRef(lossySnapshot)
		sided := func() StepFields {
			f := stepFields()
			f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot
			return f
		}
		diverge := func(f StepFields) StepFields {
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
			f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
			return f
		}
		unnamed := sided()
		unnamed.To.SnapshotID = ""
		unchanged := sided()
		unchanged.Outcome, unchanged.Plan, unchanged.ReconcileStarted, unchanged.ReconcileTookS, unchanged.ReadyAfter, unchanged.Pushed =
			wire.StepUnchanged, wire.ReconcilePlan{}, false, nil, nil, nil
		for _, c := range []struct {
			name     string
			f        StepFields
			top      any
			from, to any
		}{
			{"stepped", sided(), mixedSnapshot, lossySnapshot, mixedSnapshot},
			{"unchanged", unchanged, mixedSnapshot, lossySnapshot, mixedSnapshot},
			{"stepped to a side naming none", unnamed, nil, lossySnapshot, nil},
			{"diverged", diverge(sided()), lossySnapshot, lossySnapshot, mixedSnapshot},
		} {
			t.Run(c.name, func(t *testing.T) {
				rec, err := NewStepRecord(prev, c.f)
				if err != nil {
					t.Fatal(err)
				}
				validateRecord(t, s, rec)
				step := jsonOf(t, rec).(map[string]any)["step"].(map[string]any)
				from, to := step["from"].(map[string]any)["snapshot_id"], step["to"].(map[string]any)["snapshot_id"]
				if top := snapshotOf(t, rec); top != c.top || from != c.from || to != c.to {
					t.Errorf("snapshot_id %v, step.from's %v, step.to's %v; want %v, %v and %v", top, from, to, c.top, c.from, c.to)
				}
			})
		}
	})

	t.Run("a step from a record of 8", func(t *testing.T) {
		generic := jsonOf(t, stepPrev(t)).(map[string]any)
		generic["twin_version"] = "8"
		unsnapshotted(generic)
		prev := readBytes(t, []byte(mustJSON(t, generic)))
		f := stepFields()
		f.To.SnapshotID = mixedSnapshot
		rec, err := NewStepRecord(prev, f)
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, rec)
		got := jsonOf(t, rec).(map[string]any)
		step := got["step"].(map[string]any)
		if _, ok := step["from"].(map[string]any)["snapshot_id"]; ok {
			t.Errorf("step.from %v names a snapshot; the record it came from named none", step["from"])
		}
		if got["twin_version"] != TwinVersion || got["snapshot_id"] != mixedSnapshot || step["to"].(map[string]any)["snapshot_id"] != mixedSnapshot {
			t.Errorf("twin_version %v, snapshot_id %v, step.to %v; want %s naming the to side's %s", got["twin_version"], got["snapshot_id"], step["to"], TwinVersion, mixedSnapshot)
		}
		f = stepFields()
		f.To.SnapshotID = mixedSnapshot
		diverged, err := NewStepRecord(prev, func() StepFields {
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
			f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
			return f
		}())
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, diverged)
		if snap := snapshotOf(t, diverged); snap != nil || diverged.TwinVersion != TwinVersion {
			t.Errorf("diverged: twin_version %s, snapshot_id %v; want %s naming none, as the record it came from", diverged.TwinVersion, snap, TwinVersion)
		}
	})

	t.Run("NewStepRecord refuses a side's id that is not one", func(t *testing.T) {
		for _, side := range []string{"from", "to"} {
			f := stepFields()
			if side == "from" {
				f.From.SnapshotID = "nope"
			} else {
				f.To.SnapshotID = "nope"
			}
			if _, err := NewStepRecord(stepPrev(t), f); err == nil || !strings.Contains(err.Error(), `"nope" is not a snapshot identity`) {
				t.Errorf("%s: err = %v, want a refusal saying it is not a snapshot identity", side, err)
			}
		}
	})
}

// A record of 8 still reads, with no snapshot (018): a create's and a step's record as a 017
// worker wrote them, the baseline naming its stage and rehearsal, which twin.json 8's frozen
// contract accepts, read with SnapshotID nil, each step side's empty, and everything else as
// written, the stage and rehearsal not read (020). A 12 is not an 8.
func TestRecord8ReadsWithNoSnapshot(t *testing.T) {
	v8 := twinSchemaOf(t, "017-dcim-reader")
	observed := "2026-10-25T09:31:02.118842Z"
	staged := fields(wire.SourceIntent, &observed)
	staged.Provenance.Branch, staged.Provenance.At = "change-1", "2026-10-25T09:00:00+00:00"
	staged.SnapshotID = threeNodeSnapshot
	create, err := NewRecord(staged)
	if err != nil {
		t.Fatal(err)
	}
	f := stepFields()
	f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot
	step, err := NewStepRecord(stepPrev(t), f)
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	fromBundle, err := NewRecord(fields(wire.SourceBundle, nil))
	if err != nil {
		t.Fatal(err)
	}
	for name, rec := range map[string]wire.TwinRecord{"a rehearsal's baseline": create, "a step": step, "a bundle twin": fromBundle} {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "8"
			unsnapshotted(generic)
			withStage(generic, nil, nil)
			if name == "a rehearsal's baseline" {
				withStage(generic, stage11(), rehearsal11())
			}
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v8, b)
			got := readBytes(t, b)
			want := unsnapshot(rec)
			want.TwinVersion = "8"
			if got.SnapshotID != nil || !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v, with no snapshot", got, want)
			}
		})
	}
	t.Run("a 12 record is not an 8 one", func(t *testing.T) {
		for name, rec := range map[string]wire.TwinRecord{"naming a snapshot": create, "naming none": fromBundle} {
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, rec)))
			if err != nil {
				t.Fatal(err)
			}
			if err := v8.Validate(v); err == nil {
				t.Errorf("%s: twin.json 8's frozen contract accepts a 12 record", name)
			}
		}
	})
}

// A step keeps the source its twin was created from, since source says how the twin was
// created (019): a twin created from a snapshot and stepped is source snapshot, and an intent
// twin stepped to a snapshot is source intent, its snapshot the target's (US6 scenario 3).
// Each is written, read back as it was written, and is the current contract's, which a 9 is
// not. A record names no stage either way (020, research R-06).
func TestStepRecordKeepsItsSource(t *testing.T) {
	s, v9 := twinSchema(t), twinSchemaOf(t, "018-snapshots")
	for _, c := range []struct {
		name   string
		prev   func(*RecordFields)
		side   func(*StepFields)
		source string
	}{
		{"a snapshot twin stepped",
			func(f *RecordFields) { f.Source, f.SnapshotID = wire.SourceSnapshot, lossySnapshot },
			func(f *StepFields) { f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot },
			wire.SourceSnapshot},
		{"an intent twin stepped to a snapshot",
			func(f *RecordFields) { f.SnapshotID = lossySnapshot },
			func(f *StepFields) { f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot },
			wire.SourceIntent},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := stepFields()
			c.side(&f)
			rec, err := NewStepRecord(stepPrevWith(t, c.prev), f)
			if err != nil {
				t.Fatal(err)
			}
			if rec.TwinVersion != TwinVersion || rec.Source != c.source || rec.SnapshotID == nil || *rec.SnapshotID != mixedSnapshot {
				t.Errorf("twin_version %s, source %s, snapshot_id %v; want %s, %s and %s", rec.TwinVersion, rec.Source,
					rec.SnapshotID, TwinVersion, c.source, mixedSnapshot)
			}
			path := filepath.Join(t.TempDir(), "twin.json")
			if err := WriteRecord(path, rec); err != nil {
				t.Fatal(err)
			}
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			validateBytes(t, s, b)
			got, err := ReadRecord(path)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, rec) {
				t.Errorf("read back\n%+v\nwant\n%+v", got, rec)
			}
			v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
			if err != nil {
				t.Fatal(err)
			}
			if err := v9.Validate(v); err == nil {
				t.Error("twin.json 9's frozen contract accepts a 12 record")
			}
		})
	}
}

// twin.json 11 (016, research R-22): a create of the probed golden records each probe's host
// with its probe in place of a support package, psp and artifact null and no push time,
// holding the record's bundle as every device does, from a run that pushed the devices
// alone; and twin.json 10's frozen contract refuses it, since 10 names no host. 016's frozen
// copy accepts it as an 11 naming a stage and a rehearsal, null, as the current contract
// accepts it as a 12 (020).
func TestRecord11RecordsAHost(t *testing.T) {
	ctx := context.Background()
	s, v10, v11 := twinSchema(t), twinSchemaOf(t, "019-following-removed"), twinSchemaOf(t, contract016)
	id, err := bundle.IDOfDir(probedBundle())
	if err != nil {
		t.Fatal(err)
	}
	a := testActivities(t, &fakeRunner{})
	if _, err := a.StageBundle(ctx, wire.StageInput{BundlePath: probedBundle(), BundleID: id}); err != nil {
		t.Fatal(err)
	}
	m, err := readManifest(probedBundle())
	if err != nil {
		t.Fatal(err)
	}
	observed := "2026-10-29T09:31:02.118842Z"
	in := wire.RecordInput{TwinDir: a.Paths.Twin, BundleID: id, ObservedAt: &observed, Source: wire.SourceIntent,
		RunID: "01a0a570-0395-78ee-8d0f-9a45a97547cd"}
	for i, n := range m.Nodes {
		in.Nodes = append(in.Nodes, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image,
			State: "running", MgmtIPv4: fmt.Sprintf("172.20.20.%d", i+2)})
		in.ReadyAfter = append(in.ReadyAfter, wire.ReadinessResult{Node: n.Name, ReadyAfterS: 1.5})
		if art := n.Artifact; art != nil {
			in.Pushed = append(in.Pushed, wire.PushResult{Node: n.Name, PushedInS: 0.7, Checksum: art.Checksum, Size: art.Size})
		}
	}
	res, err := a.RecordTwin(ctx, in)
	if err != nil {
		t.Fatal(err)
	}
	rec := res.Record
	validateRecord(t, s, rec)
	as11 := jsonOf(t, rec).(map[string]any)
	as11["twin_version"] = "11"
	withStage(as11, nil, nil)
	validateBytes(t, v11, []byte(mustJSON(t, as11)))
	if rec.TwinVersion != TwinVersion || len(rec.Nodes) != 5 {
		t.Fatalf("twin_version %s with %d nodes; want %s with n1, n1-loop-a, n1-loop-b, n2 and n3", rec.TwinVersion, len(rec.Nodes), TwinVersion)
	}
	ping := wire.PSPRef{ID: "ping", Source: "embedded"}
	for _, n := range rec.Nodes {
		switch n.Name {
		case "n1-loop-a", "n1-loop-b":
			want := &wire.TwinProbe{Name: "n1-loop", Endpoint: n.Name[len(n.Name)-1:], Format: "ping", Package: ping}
			if !reflect.DeepEqual(n.Probe, want) || n.PSP != nil || n.Artifact != nil || n.PushedInS != 0 ||
				n.ReadyAfterS != 1.5 || n.Image != "alpine:3.24.2" {
				t.Errorf("host %s recorded %+v (probe %+v); want probe %+v, no package, artifact or push time, ready after 1.5s",
					n.Name, n, n.Probe, want)
			}
		default:
			if n.Probe != nil || n.PSP == nil || n.PSP.ID != "nokia_srlinux" || n.Artifact == nil {
				t.Errorf("device %s recorded %+v; want its package and artifact and no probe", n.Name, n)
			}
		}
		if n.Holds == nil || *n.Holds != id {
			t.Errorf("node %s holds %v, want the record's bundle %s", n.Name, n.Holds, id)
		}
	}
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"probe":{"name":"n1-loop","endpoint":"a","format":"ping","package":{"id":"ping","source":"embedded"}},"psp":null`,
		`"artifact":null`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("the record lacks %s:\n%s", want, b)
		}
	}
	generic := jsonOf(t, rec).(map[string]any)
	generic["twin_version"] = "10"
	withStage(generic, nil, nil)
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader([]byte(mustJSON(t, generic))))
	if err != nil {
		t.Fatal(err)
	}
	if err := v10.Validate(v); err == nil {
		t.Error("twin.json 10's frozen contract accepts a record naming a host")
	}

	// A host the contract would not hold is refused: one carrying a package, and a device
	// carrying no artifact.
	for name, change := range map[string]func(map[string]any){
		"a host with a package": func(n map[string]any) {
			if n["name"] == "n1-loop-a" {
				n["psp"] = map[string]any{"id": "nokia_srlinux", "source": "embedded"}
			}
		},
		"a device with no artifact": func(n map[string]any) {
			if n["name"] == "n1" {
				n["artifact"] = nil
			}
		},
	} {
		generic := jsonOf(t, rec).(map[string]any)
		for _, n := range generic["nodes"].([]any) {
			change(n.(map[string]any))
		}
		v, err := jsonschema.UnmarshalJSON(bytes.NewReader([]byte(mustJSON(t, generic))))
		if err != nil {
			t.Fatal(err)
		}
		if err := s.Validate(v); err == nil {
			t.Errorf("twin.json 12 accepts %s", name)
		}
	}
}

// losses is a step's loss in each of a flow's outcomes, as ReadFlows writes it into the
// record (016, research R-13).
func losses() map[string]*wire.Loss {
	from, to := "clab-fylgja-s1-loop-a", "clab-fylgja-s1-loop-b"
	return map[string]*wire.Loss{
		"measured": {Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "s1-loop", From: from, To: to,
			Outcome: wire.FlowMeasured, Sent: 312, Lost: 4, LongestGapS: 0.8}}, Added: []string{}, Dropped: []string{}},
		"not started": {Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "s1-loop", From: from, To: to,
			Outcome: wire.FlowNotStarted, Rule: findings.RuleFlowStartFailed, Message: "the flow's start failed"}},
			Added: []string{"s1-loop2"}, Dropped: []string{}},
		"not read": {Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "s1-loop", From: from, To: to,
			Outcome: wire.FlowNotRead, Sent: 0, Rule: findings.RuleFlowReadFailed, Message: "the flow's read failed"}},
			Added: []string{}, Dropped: []string{"s1-loop0"}},
		"interrupted": {Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "s1-loop", From: from, To: to,
			Outcome: wire.FlowInterrupted, Sent: 40, Lost: 40, LongestGapS: 8}}, Added: []string{}, Dropped: []string{}},
	}
}

// A step's record of twin.json 11, and of 12, carries step.loss: null as NewStepRecord writes it, before
// the flows are read, and each outcome as ReadFlows writes it, after a stepped or a diverged
// step, which the contract accepts, holds the key required, and round-trips; twin.json 10's
// frozen contract refuses the key (016).
func TestRecord11CarriesTheStepsLoss(t *testing.T) {
	s, v10 := twinSchema(t), twinSchemaOf(t, "019-following-removed")
	shapes := map[string]*wire.Loss{"loss null": nil}
	maps.Copy(shapes, losses())
	for name, l := range shapes {
		for _, outcome := range []string{wire.StepStepped, wire.StepDiverged} {
			t.Run(name+" after "+outcome, func(t *testing.T) {
				f := stepFields()
				if outcome == wire.StepDiverged {
					f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepFlows, divergedFindings(findings.RuleStepDiverged, findings.StepFlows)
					f.Pushed[0].Outcome, f.Pushed[0].TookS = wire.PushNotAttempted, nil
					f.Pushed[1].Outcome, f.Pushed[1].TookS = wire.PushNotAttempted, nil
				}
				rec, err := NewStepRecord(stepPrev(t), f)
				if err != nil {
					t.Fatal(err)
				}
				if rec.Step.Loss != nil {
					t.Fatalf("NewStepRecord wrote loss %+v; want null until the flows are read", rec.Step.Loss)
				}
				rec.Step.Loss = l
				validateRecord(t, s, rec)
				path := filepath.Join(t.TempDir(), "twin.json")
				if err := WriteRecord(path, rec); err != nil {
					t.Fatal(err)
				}
				if back, err := ReadRecord(path); err != nil || !reflect.DeepEqual(back, rec) {
					t.Errorf("read back %+v (%v)\nwant %+v", back, err, rec)
				}
				generic := jsonOf(t, rec).(map[string]any)
				generic["twin_version"] = "10"
				withStage(generic, nil, nil)
				v, err := jsonschema.UnmarshalJSON(bytes.NewReader([]byte(mustJSON(t, generic))))
				if err != nil {
					t.Fatal(err)
				}
				if err := v10.Validate(v); err == nil {
					t.Error("twin.json 10's frozen contract accepts a step block with a loss key")
				}
			})
		}
	}

	rec, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	if b := mustJSON(t, jsonOf(t, rec)); !strings.Contains(b, `"loss":null`) {
		t.Errorf("a step's record writes no explicit null loss:\n%s", b)
	}
	generic := jsonOf(t, rec).(map[string]any)
	unlossed(generic)
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader([]byte(mustJSON(t, generic))))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Validate(v); err == nil {
		t.Error("twin.json 12 accepts a step block with no loss key; it is required, null while the flows have not been read")
	}
}

// A record of 10 still reads (016): a create's and a step's record as a 019 worker wrote
// them, which twin.json 10's frozen contract accepts, read with no host and step.loss nil,
// and everything else as written.
func TestRecord10StillReads(t *testing.T) {
	v10 := twinSchemaOf(t, "019-following-removed")
	create, err := NewRecord(fields(wire.SourceBundle, nil))
	if err != nil {
		t.Fatal(err)
	}
	step, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	for name, rec := range map[string]wire.TwinRecord{"a create": create, "a step": step} {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "10"
			unlossed(generic)
			withStage(generic, nil, nil)
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v10, b)
			want := rec
			want.TwinVersion = "10"
			got := readBytes(t, b)
			if !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v", got, want)
			}
			if got.Step != nil && got.Step.Loss != nil {
				t.Errorf("a 10 step reads with loss %+v, want nil", got.Step.Loss)
			}
		})
	}
}

// A host through a step (016, R-22): containerlab configures a host from its topology
// node's exec lines and no push reaches it, so a host containerlab created or recreated
// holds the staged target, one it restarted or left alone holds what it held, and after a
// stepped step every host holds the target. Each keeps its probe and no package or
// artifact, and a target whose lab lacks a host it names is refused.
func TestNewStepRecordHosts(t *testing.T) {
	ping := wire.PSPRef{ID: "ping", Source: "embedded"}
	probeOf := func(endpoint string) *wire.TwinProbe {
		return &wire.TwinProbe{Name: "s1-loop", Endpoint: endpoint, Format: "ping", Package: ping}
	}
	hostNode := func(endpoint, ip string) wire.LabNode {
		return wire.LabNode{Name: "s1-loop-" + endpoint, Container: "clab-fylgja-s1-loop-" + endpoint, Image: "alpine:3.24.2",
			State: "running", MgmtIPv4: ip}
	}
	prev := stepPrevWith(t, func(f *RecordFields) {
		for endpoint, ip := range map[string]string{"a": "172.20.20.5", "b": "172.20.20.6"} {
			n := hostNode(endpoint, ip)
			f.Nodes = append(f.Nodes, wire.TwinNode{Name: n.Name, Container: n.Container, Image: n.Image,
				Probe: probeOf(endpoint), MgmtIPv4: ip, ReadyAfterS: 1})
		}
	})
	withHosts := func(f *StepFields) {
		f.Staged.Probes = map[string]*wire.TwinProbe{"s1-loop-a": probeOf("a"), "s1-loop-b": probeOf("b")}
		f.Nodes = append(f.Nodes, hostNode("a", "172.20.20.5"), hostNode("b", "172.20.20.6"))
	}
	for _, c := range []struct {
		name   string
		change func(*StepFields)
		want   map[string]string // each host's holds
	}{
		{"diverged, one host recreated and one restarted", func(f *StepFields) {
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, divergedFindings(findings.RulePushRefused, findings.StepPush)
			f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
			f.Plan.Recreated, f.Plan.Restarted = []string{"s1-loop-a"}, []string{"e1", "s1-loop-b"}
		}, map[string]string{"s1-loop-a": stepToID, "s1-loop-b": stepFromID}},
		{"diverged, the hosts left alone", func(f *StepFields) {
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, divergedFindings(findings.RulePushRefused, findings.StepPush)
			f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
		}, map[string]string{"s1-loop-a": stepFromID, "s1-loop-b": stepFromID}},
		{"stepped, one host recreated", func(f *StepFields) {
			f.Plan.Recreated = []string{"s1-loop-b"}
		}, map[string]string{"s1-loop-a": stepToID, "s1-loop-b": stepToID}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := stepFields()
			withHosts(&f)
			c.change(&f)
			rec, err := NewStepRecord(prev, f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, twinSchema(t), rec)
			for _, n := range rec.Nodes {
				want, host := c.want[n.Name]
				if !host {
					continue
				}
				if n.Holds == nil || *n.Holds != want {
					t.Errorf("host %s holds %v, want %s", n.Name, n.Holds, want)
				}
				if !reflect.DeepEqual(n.Probe, probeOf(n.Name[len(n.Name)-1:])) || n.PSP != nil || n.Artifact != nil {
					t.Errorf("host %s recorded probe %+v, package %v and artifact %v; want its probe alone", n.Name, n.Probe, n.PSP, n.Artifact)
				}
			}
		})
	}

	t.Run("a host the target adds", func(t *testing.T) {
		f := stepFields()
		withHosts(&f)
		f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepReadiness, divergedFindings(findings.RuleReadinessTimeout, findings.StepReadiness)
		for i := range f.Pushed {
			f.Pushed[i].Outcome, f.Pushed[i].TookS = wire.PushNotAttempted, nil
		}
		f.Staged.Probes["s1-loop2-a"] = &wire.TwinProbe{Name: "s1-loop2", Endpoint: "a", Format: "ping", Package: ping}
		f.Plan.Added = []string{"s1-loop2-a"}
		f.Nodes = append(f.Nodes, wire.LabNode{Name: "s1-loop2-a", Container: "clab-fylgja-s1-loop2-a", Image: "alpine:3.24.2",
			State: "running", MgmtIPv4: "172.20.20.7"})
		rec, err := NewStepRecord(prev, f)
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, twinSchema(t), rec)
		for _, n := range rec.Nodes {
			if n.Name == "s1-loop2-a" && (n.Holds == nil || *n.Holds != stepToID || n.Probe == nil || n.Probe.Name != "s1-loop2" || n.PSP != nil) {
				t.Errorf("the added host recorded %+v; want it holding the target with its probe", n)
			}
		}
	})

	t.Run("a target's host containerlab does not report", func(t *testing.T) {
		f := stepFields()
		withHosts(&f)
		f.Nodes = f.Nodes[:len(f.Nodes)-1]
		_, err := NewStepRecord(prev, f)
		if err == nil || !strings.Contains(err.Error(), "names node s1-loop-b, which containerlab does not report") {
			t.Errorf("err = %v, want the target's host named as not reported", err)
		}
	})
}

// A record of 9 still reads (019): a create's and a step's record as an 018 worker wrote
// them, the baseline naming its stage and rehearsal, which twin.json 9's frozen contract
// accepts, read with everything as written but the stage and rehearsal, which are not read
// (020), so each reads back as this build writes it but for its version.
func TestRecord9StillReads(t *testing.T) {
	v9 := twinSchemaOf(t, "018-snapshots")
	observed := "2026-10-27T09:31:02.118842Z"
	staged := fields(wire.SourceIntent, &observed)
	staged.Provenance.Branch, staged.Provenance.At = "change-1", "2026-10-27T09:00:00+00:00"
	staged.SnapshotID = threeNodeSnapshot
	ofSnapshot := fields(wire.SourceSnapshot, &observed)
	ofSnapshot.SnapshotID = threeNodeSnapshot
	records := map[string]wire.TwinRecord{}
	for name, f := range map[string]RecordFields{"a rehearsal's baseline": staged, "a snapshot twin": ofSnapshot,
		"a bundle twin": fields(wire.SourceBundle, nil)} {
		rec, err := NewRecord(f)
		if err != nil {
			t.Fatal(err)
		}
		records[name] = rec
	}
	f := stepFields()
	f.From.SnapshotID, f.To.SnapshotID = lossySnapshot, mixedSnapshot
	step, err := NewStepRecord(stepPrevWith(t, func(f *RecordFields) { f.SnapshotID = lossySnapshot }), f)
	if err != nil {
		t.Fatal(err)
	}
	step.Step.Wait = waits()["settled"]
	records["a step"] = step
	for name, rec := range records {
		t.Run(name, func(t *testing.T) {
			generic := jsonOf(t, rec).(map[string]any)
			generic["twin_version"] = "9"
			unlossed(generic)
			withStage(generic, nil, nil)
			if name == "a rehearsal's baseline" {
				withStage(generic, stage11(), rehearsal11())
			}
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v9, b)
			want := rec
			want.TwinVersion = "9"
			if got := readBytes(t, b); !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v", got, want)
			}
		})
	}
}

func TestWriteRecordIsAtomicAndRoundTrips(t *testing.T) {
	observed := "2026-09-15T14:22:12.000000Z"
	rec, err := NewRecord(fields(wire.SourceIntent, &observed))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "twin.json")
	if err := WriteRecord(path, rec); err != nil {
		t.Fatal(err)
	}
	list, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 || list[0].Name() != "twin.json" {
		t.Errorf("directory holds %v, want twin.json alone", list)
	}
	back, err := ReadRecord(path)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(back, rec) {
		t.Errorf("round trip changed the record:\n got %+v\nwant %+v", back, rec)
	}
}

// twin.json has nowhere a credential could go: no field is named for one (Constitution
// X). A walk of the type rather than the schema, because the type is what gets written.
func TestTwinRecordHasNoCredentialField(t *testing.T) {
	var walk func(reflect.Type, string)
	walk = func(ty reflect.Type, path string) {
		switch ty.Kind() {
		case reflect.Pointer, reflect.Slice:
			walk(ty.Elem(), path)
			return
		case reflect.Struct:
		default:
			return
		}
		for i := range ty.NumField() {
			f := ty.Field(i)
			name := path + "." + f.Name
			lower := strings.ToLower(f.Name + " " + f.Tag.Get("json"))
			for _, word := range []string{"password", "token", "secret"} {
				if strings.Contains(lower, word) {
					t.Errorf("%s looks like a place for a credential (%q)", name, word)
				}
			}
			walk(f.Type, name)
		}
	}
	walk(reflect.TypeOf(wire.TwinRecord{}), "TwinRecord")
}

// RecordTwin writes twin.json last, from the staged manifest, what deploy and readiness
// reported and this worker's version, and returns the record exactly as written. Run as the
// worker runs it. Its failure identifier, record.failed, is
// produced here by the activity itself; the workflow tests fabricate it in a mock
// (contracts/cli.md: every identifier has a tier-1 test that produces it).
func TestRecordTwin(t *testing.T) {
	ctx := context.Background()
	observed := "2026-09-15T14:22:12.000000Z"
	const runID = "01a0a570-0395-78ee-8d0f-9a45a97547cd"
	const image = "ghcr.io/nokia/srlinux:24.7.1"
	srlinux := wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}
	// Deploy and readiness report nodes in whatever order they finished; twin.json sorts.
	deployed := []wire.LabNode{
		{Name: "n2", Container: "clab-fylgja-n2", Kind: "nokia_srlinux", Image: image, State: "running", MgmtIPv4: "172.20.20.3"},
		{Name: "n3", Container: "clab-fylgja-n3", Kind: "nokia_srlinux", Image: image, State: "running", MgmtIPv4: "172.20.20.4"},
		{Name: "n1", Container: "clab-fylgja-n1", Kind: "nokia_srlinux", Image: image, State: "running", MgmtIPv4: "172.20.20.2"},
	}
	ready := []wire.ReadinessResult{{Node: "n3", ReadyAfterS: 1.102}, {Node: "n1", ReadyAfterS: 0.761}, {Node: "n2", ReadyAfterS: 0.897}}
	pushed := []wire.PushResult{
		{Node: "n2", PushedInS: 0.62, Checksum: "092ca9f62fe2887add0ae679de0a7076", Size: 1327},
		{Node: "n1", PushedInS: 0.7, Checksum: "28881d3d0d61d3fe5acf1f1ee0e31a60", Size: 1327},
		{Node: "n3", PushedInS: 0.65, Checksum: "95a3a91788e63626cdb9b4ecdf56eb58", Size: 1327},
	}
	artifact := func(checksum string) *wire.TwinArtifact {
		return &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: checksum, Size: 1327}
	}
	// The golden manifest's provenance block, which the plan carries and the record copies,
	// its scope and mapping included (twin.json 8).
	provenance := wire.Provenance{Branch: "fylgja-fixture", At: "2026-09-08T12:00:00Z", SchemaHash: "fixture",
		Scope: "tag:fylgja", Mapping: dcimMapping}
	input := func(a *Activities, nodes []wire.LabNode) wire.RecordInput {
		return wire.RecordInput{
			TwinDir:    a.Paths.Twin,
			BundleID:   goldenID,
			Provenance: provenance,
			ObservedAt: &observed,
			Source:     wire.SourceIntent,
			RunID:      runID,
			Nodes:      nodes,
			ReadyAfter: ready,
			Pushed:     pushed,
		}
	}
	// staged is the activities with the golden bundle staged, as a run stages it before deploy.
	staged := func(t *testing.T) *Activities {
		t.Helper()
		a := testActivities(t, &fakeRunner{})
		if _, err := a.StageBundle(ctx, wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}); err != nil {
			t.Fatal(err)
		}
		return a
	}
	record := func(t *testing.T, a *Activities, in wire.RecordInput) (wire.RecordResult, error) {
		t.Helper()
		val, err := activityEnv(a.RecordTwin, wire.ActRecordTwin).ExecuteActivity(wire.ActRecordTwin, in)
		if err != nil {
			return wire.RecordResult{}, err
		}
		var res wire.RecordResult
		if err := val.Get(&res); err != nil {
			t.Fatal(err)
		}
		return res, nil
	}
	// noRecord asserts a failed record left the twin directory holding the staged bundle alone:
	// no twin.json, and no temporary file.
	noRecord := func(t *testing.T, a *Activities) {
		t.Helper()
		entries, err := os.ReadDir(a.Paths.Twin)
		if err != nil {
			t.Fatal(err)
		}
		for _, e := range entries {
			if e.Name() != filepath.Base(a.Paths.TwinBundle) {
				t.Errorf("%s holds %s after a failed record; want the staged bundle alone", a.Paths.Twin, e.Name())
			}
		}
	}

	t.Run("returns the record it wrote", func(t *testing.T) {
		a := staged(t)
		res, err := record(t, a, input(a, deployed))
		if err != nil {
			t.Fatal(err)
		}
		if res.Path != a.Paths.TwinJSON {
			t.Errorf("path = %q, want %q", res.Path, a.Paths.TwinJSON)
		}
		written, err := ReadRecord(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(written, res.Record) {
			t.Errorf("the record returned differs from the one written:\n got %+v\nwant %+v", res.Record, written)
		}
		validateRecord(t, twinSchema(t), res.Record)

		rec := res.Record
		if rec.Provenance != provenance {
			t.Errorf("provenance = %+v, want the staged manifest's %+v", rec.Provenance, provenance)
		}
		if rec.BundleID != goldenID || rec.Source != wire.SourceIntent || rec.ObservedAt == nil || *rec.ObservedAt != observed {
			t.Errorf("bundle_id %s, source %s, observed_at %v; want %s, intent, %s", rec.BundleID, rec.Source, rec.ObservedAt, goldenID, observed)
		}
		if want := (wire.RunRef{WorkflowID: wire.ProvisionWorkflowID, RunID: runID}); rec.Run != want {
			t.Errorf("run = %+v, want %+v", rec.Run, want)
		}
		if rec.ProvisionedBy.Version != a.Version {
			t.Errorf("provisioned_by.version = %q, want this worker's %q", rec.ProvisionedBy.Version, a.Version)
		}
		if _, err := time.Parse(time.RFC3339Nano, rec.RecordedAt); err != nil {
			t.Errorf("recorded_at %q: %v", rec.RecordedAt, err)
		}
		// Each node: container, image and address from deploy, the package and the artifact
		// from the manifest, how long it took from readiness and its push; sorted by name.
		// Each holds the bundle the create pushed it.
		holds := goldenID
		want := []wire.TwinNode{
			{Name: "n1", Container: "clab-fylgja-n1", Image: image, PSP: &srlinux, MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.761,
				Artifact: artifact("28881d3d0d61d3fe5acf1f1ee0e31a60"), PushedInS: 0.7, Holds: &holds},
			{Name: "n2", Container: "clab-fylgja-n2", Image: image, PSP: &srlinux, MgmtIPv4: "172.20.20.3", ReadyAfterS: 0.897,
				Artifact: artifact("092ca9f62fe2887add0ae679de0a7076"), PushedInS: 0.62, Holds: &holds},
			{Name: "n3", Container: "clab-fylgja-n3", Image: image, PSP: &srlinux, MgmtIPv4: "172.20.20.4", ReadyAfterS: 1.102,
				Artifact: artifact("95a3a91788e63626cdb9b4ecdf56eb58"), PushedInS: 0.65, Holds: &holds},
		}
		if !reflect.DeepEqual(rec.Nodes, want) {
			t.Errorf("nodes:\n got %+v\nwant %+v", rec.Nodes, want)
		}
		if rec.TwinVersion != TwinVersion || rec.State != wire.StateReady || rec.Step != nil {
			t.Errorf("twin_version %q, state %q, step %+v; want %s, ready and no step", rec.TwinVersion, rec.State, rec.Step, TwinVersion)
		}
		if rec.SnapshotID != nil {
			t.Errorf("snapshot_id = %v; want nil for a run given none", rec.SnapshotID)
		}
		// The record names each artifact and holds none of it: the staged files'
		// marker line is nowhere in what was written.
		b, err := os.ReadFile(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), "FYLGJA-MARKER") || strings.Contains(string(b), "set / ") {
			t.Errorf("twin.json carries artifact content:\n%s", b)
		}
	})

	// The snapshot the run's bundle was compiled from reaches the record as data (018): on a
	// create the server read and took, and on one from a snapshot.
	t.Run("names the snapshot it was given", func(t *testing.T) {
		for _, source := range []string{wire.SourceIntent, wire.SourceSnapshot} {
			a := staged(t)
			in := input(a, deployed)
			in.Source, in.SnapshotID = source, threeNodeSnapshot
			res, err := record(t, a, in)
			if err != nil {
				t.Fatal(err)
			}
			written, err := ReadRecord(a.Paths.TwinJSON)
			if err != nil {
				t.Fatal(err)
			}
			for label, got := range map[string]*string{"returned": res.Record.SnapshotID, "twin.json's": written.SnapshotID} {
				if got == nil || *got != threeNodeSnapshot {
					t.Errorf("%s: %s snapshot_id = %v, want %s", source, label, got, threeNodeSnapshot)
				}
			}
			if res.Record.Source != source {
				t.Errorf("source %q, want %q", res.Record.Source, source)
			}
			validateRecord(t, twinSchema(t), res.Record)
		}
	})

	t.Run("a twin directory that cannot be written is record.failed", func(t *testing.T) {
		if os.Geteuid() == 0 {
			t.Skip("root writes into a read-only directory")
		}
		a := staged(t)
		if err := os.Chmod(a.Paths.Twin, 0o555); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(a.Paths.Twin, 0o755) })

		_, err := record(t, a, input(a, deployed))
		f := stepFailure(t, err, findings.RuleRecordFailed)
		if f.Step != findings.StepRecord || f.Object != a.Paths.TwinJSON || !strings.Contains(f.Message, a.Paths.TwinJSON) {
			t.Errorf("finding = %+v, want step record naming %s", f, a.Paths.TwinJSON)
		}
		noRecord(t, a)
	})

	t.Run("a node no push result names is record.failed", func(t *testing.T) {
		a := staged(t)
		in := input(a, deployed)
		in.Pushed = slices.DeleteFunc(slices.Clone(pushed), func(p wire.PushResult) bool { return p.Node == "n3" })
		_, err := record(t, a, in)
		f := stepFailure(t, err, findings.RuleRecordFailed)
		if f.Step != findings.StepRecord || f.Object != a.Paths.TwinJSON || !strings.Contains(f.Message, "no push result names node n3") {
			t.Errorf("finding = %+v, want step record naming n3", f)
		}
		noRecord(t, a)
	})

	t.Run("a node the staged manifest does not name is record.failed", func(t *testing.T) {
		a := staged(t)
		stranger := wire.LabNode{Name: "n9", Container: "clab-fylgja-n9", Kind: "nokia_srlinux", Image: image, State: "running", MgmtIPv4: "172.20.20.9"}
		_, err := record(t, a, input(a, append(slices.Clone(deployed), stranger)))
		f := stepFailure(t, err, findings.RuleRecordFailed)
		if f.Step != findings.StepRecord || f.Object != a.Paths.TwinJSON || !strings.Contains(f.Message, "n9") {
			t.Errorf("finding = %+v, want step record naming n9", f)
		}
		noRecord(t, a)
	})
}

// A create writes twin.json 12: state ready, step null, and every node holding the record's
// bundle, each written out rather than left to a default; one given no snapshot says
// "snapshot_id": null (a create has no step), and none writes a stage or a rehearsal key
// (020, research R-06).
func TestCreateWritesVersion12(t *testing.T) {
	observed := "2026-09-15T14:22:12.000000Z"
	rec, err := NewRecord(fields(wire.SourceIntent, &observed))
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, twinSchema(t), rec)
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"twin_version":"12"`, `"snapshot_id":null`, `"state":"ready"`, `"step":null`,
		`"holds":"` + rec.BundleID + `"`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("a create's record lacks %s:\n%s", want, b)
		}
	}
	for _, key := range []string{`"stage":`, `"rehearsal":`} {
		if strings.Contains(string(b), key) {
			t.Errorf("a create's record writes %s:\n%s", key, b)
		}
	}
	if n := strings.Count(string(b), `"holds":"`+rec.BundleID+`"`); n != len(rec.Nodes) {
		t.Errorf("%d nodes hold the record's bundle, want all %d:\n%s", n, len(rec.Nodes), b)
	}
}

// Tier 3 reads the records its twins leave against the version this build writes: every
// .twin_version scripts/e2e.sh expects is TwinVersion, so the version cannot move without
// the script moving with it. 015 moved it to 7 and left cases 7 and 8 expecting 6, which
// only tier 3 found (T055).
func TestE2EScriptExpectsTheRecordsVersion(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "scripts", "e2e.sh"))
	if err != nil {
		t.Fatal(err)
	}
	expected := regexp.MustCompile(`\.twin_version=="([^"]*)"`).FindAllSubmatch(raw, -1)
	if len(expected) == 0 {
		t.Fatal("scripts/e2e.sh expects no record's .twin_version")
	}
	for _, m := range expected {
		if v := string(m[1]); v != TwinVersion {
			t.Errorf("scripts/e2e.sh expects a record of twin.json %s, but this build writes %s", v, TwinVersion)
		}
	}
}

// waits are the step's wait in each of its four outcomes, as VerifyTwin writes it into the
// record: settled with nothing failing; expired with a link end
// still failing; cancelled by a destroy during the pause; and incomplete, once with a node
// unread at expiry and once with the activity failing before any read.
func waits() map[string]*wire.StepWait {
	const from, ended = "2026-10-02T09:15:41.2Z", "2026-10-02T09:15:43.6Z"
	neighbour := wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "e1:Ethernet3",
		Message: "node e1 (172.20.20.2:6030): port Ethernet3 sees no neighbour at /lldp/interfaces/interface[name=Ethernet3]/neighbors/neighbor; link e1:eth3 -- s1:e1-3 names s1 ethernet-1/3 at its far end"}
	unread := wire.StepFinding{Rule: findings.RuleOperationFailed, Object: "e1",
		Message: "node e1 (172.20.20.2:6030) could not be read: connection refused (at /system/state/hostname)"}
	return map[string]*wire.StepWait{
		"settled": {Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, From: from, EndedAt: ended,
			Failing: []wire.StepFinding{}},
		"expired": {Outcome: wire.WaitExpired, BudgetS: 20, Reads: 19, AfterS: 20.3, From: from, EndedAt: "2026-10-02T09:16:01.5Z",
			Failing: []wire.StepFinding{neighbour}},
		"cancelled": {Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4, From: from, EndedAt: "2026-10-02T09:15:53.6Z",
			Failing: []wire.StepFinding{neighbour}},
		"incomplete, a node unread": {Outcome: wire.WaitIncomplete, BudgetS: 30, Reads: 29, AfterS: 30.1, From: from,
			EndedAt: "2026-10-02T09:16:11.3Z", Failing: []wire.StepFinding{neighbour, unread}},
		"incomplete, nothing read": {Outcome: wire.WaitIncomplete, BudgetS: 120, Reads: 0, AfterS: 0, From: from, EndedAt: from,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "/state/twin/bundle",
				Message: "reading the staged bundle: reading the bundle manifest: no such file or directory"}}},
	}
}

// A step's record with its wait filled, in every outcome and after a stepped or a diverged
// step, is what twin.json 10 accepts, as 5 to 9 did; and the contract holds the key required,
// so a step block with no wait is refused (contracts/twin.schema.json).
func TestVersion10RecordCarriesEachWait(t *testing.T) {
	s := twinSchema(t)
	for name, w := range waits() {
		for _, outcome := range []string{wire.StepStepped, wire.StepDiverged} {
			t.Run(name+" after "+outcome, func(t *testing.T) {
				f := stepFields()
				if outcome == wire.StepDiverged {
					f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
					f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
				}
				rec, err := NewStepRecord(stepPrev(t), f)
				if err != nil {
					t.Fatal(err)
				}
				rec.Step.Wait = w
				validateRecord(t, s, rec)
			})
		}
	}

	rec, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	delete(generic["step"].(map[string]any), "wait")
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Validate(v); err == nil {
		t.Error("twin.schema.json 12 accepts a step block with no wait key; it is required, null while the wait has not run")
	}
}

// A record M11 wrote, twin.json 4, has no wait in its step block and names M10's waypoint,
// and reads with Step.Wait nil, its waypoint not read (014, 020), and everything else as
// written. The record is a step's, as NewStepRecord built it before M12,
// and M11's own contract accepts it.
func TestVersion4RecordReadsWithNoWait(t *testing.T) {
	rec, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	b := olderRecord(t, rec, "4", m10Waypoint(2), m10Waypoint(1), m10Waypoint(2))
	validateBytes(t, twinSchemaOf(t, "009-stepping"), b)
	got := readBytes(t, b)
	if got.TwinVersion != "4" || got.Step == nil || got.Step.Wait != nil {
		t.Fatalf("read version %q, step %+v; want version 4 with a step block and no wait", got.TwinVersion, got.Step)
	}
	want := unscoped(rec)
	want.TwinVersion = "4"
	if !reflect.DeepEqual(got, want) {
		t.Errorf("read %+v\nwant %+v", got, want)
	}
}

// A version 10 record, its wait null or written, reads back and writes again byte for byte:
// nothing the wait added is lost or reshaped by a reader that writes the record again, as
// VerifyTwin does.
func TestVersion10RecordRoundTrips(t *testing.T) {
	shapes := map[string]*wire.StepWait{"wait null": nil}
	for name, w := range waits() {
		shapes[name] = w
	}
	for name, w := range shapes {
		t.Run(name, func(t *testing.T) {
			rec, err := NewStepRecord(stepPrev(t), stepFields())
			if err != nil {
				t.Fatal(err)
			}
			rec.Step.Wait = w
			dir := t.TempDir()
			first, second := filepath.Join(dir, "first.json"), filepath.Join(dir, "second.json")
			if err := WriteRecord(first, rec); err != nil {
				t.Fatal(err)
			}
			back, err := ReadRecord(first)
			if err != nil {
				t.Fatal(err)
			}
			if err := WriteRecord(second, back); err != nil {
				t.Fatal(err)
			}
			a, errA := os.ReadFile(first)
			b, errB := os.ReadFile(second)
			if errA != nil || errB != nil {
				t.Fatal(errA, errB)
			}
			if !bytes.Equal(a, b) {
				t.Errorf("the record changed on a round trip:\n%s\nthen\n%s", a, b)
			}
			if !reflect.DeepEqual(back, rec) {
				t.Errorf("read %+v\nwant %+v", back, rec)
			}
		})
	}
}

// A step from a record whose last step's wait was written starts the new step's wait at
// null: the wait is the step's, and a new step block is written whole.
func TestNewStepRecordDoesNotCarryTheLastWait(t *testing.T) {
	first, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	first.Step.Wait = waits()["settled"]
	third := wire.StepSide{BundleID: stepOther, At: "2026-09-28T15:40:00.000000+00:00"}
	f := stepFields()
	f.From, f.To = wire.StepSide{BundleID: stepToID, At: stepToAt}, third
	f.RunID = "01a1b2c3-0000-7000-8000-000000000003"
	f.Plan, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter = wire.ReconcilePlan{}, false, nil, nil
	f.Pushed = []wire.StepPush{{Node: "e1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(1.2)}}
	f.Staged = stepTarget()
	f.Staged.BundleID, f.Staged.Provenance.At = stepOther, third.At
	rec, err := NewStepRecord(first, f)
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, twinSchema(t), rec)
	if rec.Step == nil || rec.Step.Run.RunID != f.RunID || rec.Step.Wait != nil {
		t.Errorf("step %+v; want the second run's step block with its wait not yet run", rec.Step)
	}
}

// version3Record is a record M10 wrote: twin.json 3, naming its waypoint, with no state,
// no step and no holds.
const version3Record = `{
  "twin_version": "3",
  "lab": "fylgja",
  "bundle_id": "4d5f3e2308a8248f600c2dcf83cc360f6101ca97a9ca717dc2b6e0c02827e31a",
  "provenance": {"branch": "fylgja-fixture", "at": "2026-09-20T10:00:00Z", "schema_hash": "abc123", "contract_version": "0.2"},
  "observed_at": "2026-09-20T10:01:02.000000Z",
  "source": "intent",
  "run": {"workflow_id": "fylgja-provision", "run_id": "01a0a570-0395-78ee-8d0f-9a45a97547cd"},
  "provisioned_by": {"version": "0.1.0-dev"},
  "recorded_at": "2026-09-20T10:02:00Z",
  "nodes": [{"name": "n1", "container": "clab-fylgja-n1", "image": "ghcr.io/nokia/srlinux:24.7.1",
    "psp": {"id": "nokia_srlinux", "source": "embedded"}, "mgmt_ipv4": "172.20.20.2", "ready_after_s": 0.7,
    "artifact": {"name": "device-config", "content_type": "text/plain", "checksum": "43e8fd0c2de5f4646f74a51d34742824", "size": 861},
    "pushed_in_s": 0.6}],
  "waypoint": {"series": "demo", "sequence": 2, "description": "", "at_source": "given"}
}
`

// readVersion3 is version3Record as ReadRecord reads it from a twin directory.
func readVersion3(t *testing.T) wire.TwinRecord {
	t.Helper()
	path := filepath.Join(t.TempDir(), "twin.json")
	if err := os.WriteFile(path, []byte(version3Record), 0o644); err != nil {
		t.Fatal(err)
	}
	rec, err := ReadRecord(path)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

// A record M10 wrote reads with the defaults: no state (shown as ready), no step, no node
// holding anything (shown as the record's bundle_id), and its waypoint not read (014, 020).
func TestVersion3RecordReadsWithTheDefaults(t *testing.T) {
	rec := readVersion3(t)
	if rec.TwinVersion != "3" || rec.State != "" || rec.Step != nil || len(rec.Nodes) != 1 || rec.Nodes[0].Holds != nil {
		t.Errorf("read %+v; want version 3 with no state, no step and no holds", rec)
	}
}

// The mixed golden's twin, as a step from change-1/seeded to change-1/cabled sees it: e1 and e2 on
// arista_eos, s1 on nokia_srlinux; the link e1:eth3 — s1:e1-3 added, so containerlab
// restarts e1 and re-cables s1 live, and the push plan is e1 (artifact, restarted) and s1
// (artifact, bootstrap). e2 is left alone.
var (
	stepFromID = strings.Repeat("348fd934", 8)
	stepToID   = strings.Repeat("ee291b0f", 8)
	stepOther  = strings.Repeat("51f0aa93", 8)
)

const (
	stepFromAt = "2026-09-28T15:00:01.123456+00:00"
	stepToAt   = "2026-09-28T15:20:44.000000+00:00"
	ceosImage  = "ceos:4.32.0.2F"
)

func stepArtifact(checksum string) *wire.TwinArtifact {
	return &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: checksum, Size: 900}
}

var (
	eos     = wire.PSPRef{ID: "arista_eos", Source: "embedded"}
	srlinux = wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}
	// Each node's artifact checksum at change-1/seeded and at change-1/cabled: e2's does not move.
	before = map[string]string{"e1": strings.Repeat("43e8", 8), "e2": strings.Repeat("ecb0", 8), "s1": strings.Repeat("1c0e", 8)}
	after  = map[string]string{"e1": strings.Repeat("9a01", 8), "e2": strings.Repeat("ecb0", 8), "s1": strings.Repeat("7a9b", 8)}
)

// stepPrev is the create's record of change-1/seeded.
func stepPrev(t *testing.T) wire.TwinRecord {
	t.Helper()
	return stepPrevWith(t, nil)
}

// stepPrevWith is stepPrev's create with its fields changed by change before NewRecord
// builds it, when change is not nil.
func stepPrevWith(t *testing.T, change func(*RecordFields)) wire.TwinRecord {
	t.Helper()
	observed := "2026-09-28T15:31:02.118842Z"
	f := RecordFields{BundleID: stepFromID, ObservedAt: &observed, Source: wire.SourceIntent,
		Provenance: wire.Provenance{Branch: "change-1", At: stepFromAt, SchemaHash: "4d5b37aa", Scope: "tag:fylgja", Mapping: dcimMapping},
		RunID:      "01a0e9e3-0000-7000-8000-000000000001", Version: "0.1.0-dev", RecordedAt: time.Date(2026, 10, 2, 9, 0, 0, 0, time.UTC)}
	for _, n := range []struct {
		name, image, ip string
		psp             wire.PSPRef
	}{{"e1", ceosImage, "172.20.20.2", eos}, {"e2", ceosImage, "172.20.20.3", eos}, {"s1", "ghcr.io/nokia/srlinux:24.7.1", "172.20.20.4", srlinux}} {
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n.name, Container: "clab-fylgja-" + n.name, Image: n.image, PSP: &n.psp,
			MgmtIPv4: n.ip, ReadyAfterS: 10, Artifact: stepArtifact(before[n.name]), PushedInS: 1})
	}
	if change != nil {
		change(&f)
	}
	rec, err := NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

func stepTarget() *StagedTarget {
	return &StagedTarget{BundleID: stepToID,
		Provenance: wire.Provenance{Branch: "change-1", At: stepToAt, SchemaHash: "4d5b37aa", Scope: "tag:fylgja", Mapping: dcimMapping},
		PSP:        map[string]wire.PSPRef{"e1": eos, "e2": eos, "s1": srlinux},
		Artifacts: map[string]*wire.TwinArtifact{"e1": stepArtifact(after["e1"]), "e2": stepArtifact(after["e2"]),
			"s1": stepArtifact(after["s1"])}}
}

func took(s float64) *float64 { return &s }

// stepFields is the step of the example, stepped: the reconcile ran, e1 was awaited, and
// both pushes landed. Each case changes what its outcome changes.
func stepFields() StepFields {
	labNode := func(name, image, ip string) wire.LabNode {
		return wire.LabNode{Name: name, Container: "clab-fylgja-" + name, Image: image, State: "running", MgmtIPv4: ip}
	}
	return StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{BundleID: stepFromID, At: stepFromAt},
		To:         wire.StepSide{BundleID: stepToID, At: stepToAt, Branch: "change-1"},
		ObservedAt: "2026-10-02T09:14:01.000000Z",
		RunID:      "01a1b2c3-0000-7000-8000-000000000002",
		Version:    "0.1.0-dev",
		Plan: wire.ReconcilePlan{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth3 -- s1:e1-3"},
			Reasons: map[string]string{"e1": "added link"}},
		Declared:         map[string]string{"e1": "restart", "e2": "restart", "s1": "live"},
		ReconcileStarted: true,
		ReconcileTookS:   took(3.9),
		ReadyAfter:       []wire.ReadinessResult{{Node: "e1", ReadyAfterS: 54.8}},
		Pushed: []wire.StepPush{
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.4)},
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.6)},
		},
		StartedAt:  "2026-10-02T09:14:30Z",
		EndedAt:    "2026-10-02T09:15:41.2Z",
		RecordedAt: time.Date(2026, 10, 2, 9, 15, 41, 300000000, time.UTC),
		Nodes: []wire.LabNode{labNode("s1", "ghcr.io/nokia/srlinux:24.7.1", "172.20.20.4"),
			labNode("e1", ceosImage, "172.20.20.2"), labNode("e2", ceosImage, "172.20.20.3")},
		Staged: stepTarget(),
	}
}

// diverged is a finding of the failure the step stopped at, beside step.diverged.
func divergedFindings(rule, step string) findings.List {
	var l findings.List
	l.AddStep(findings.Rejection, step, rule, "e1", "the phase's own finding")
	l.AddStep(findings.Rejection, step, findings.RuleStepDiverged, "01a1b2c3-0000-7000-8000-000000000002", "the step stopped")
	return l
}

// holdsOf is each node's holds, "null" for none.
func holdsOf(rec wire.TwinRecord) map[string]string {
	out := map[string]string{}
	for _, n := range rec.Nodes {
		out[n.Name] = "null"
		if n.Holds != nil {
			out[n.Name] = *n.Holds
		}
	}
	return out
}

// Every outcome a step can end in builds a record the contract accepts, with the right top
// level, state, step block and holds.
func TestNewStepRecordOutcomes(t *testing.T) {
	s := twinSchema(t)
	cases := []struct {
		name   string
		change func(f *StepFields)
		moved  bool
		holds  map[string]string
		phase  string
		// skipped is the record's reconcile.skipped: true for an empty plan, and for an
		// unchanged step, whose run skips the reconcile whatever the plan says.
		skipped bool
	}{
		{name: "stepped", moved: true, holds: map[string]string{"e1": stepToID, "e2": stepToID, "s1": stepToID}},
		{name: "unchanged", moved: true, skipped: true, holds: map[string]string{"e1": stepToID, "e2": stepToID, "s1": stepToID},
			change: func(f *StepFields) {
				f.Outcome, f.Plan, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter, f.Pushed = wire.StepUnchanged,
					wire.ReconcilePlan{}, false, nil, nil, nil
			}},
		// TestStepUnchanged's run: a lab drifted from its stored state gives a plan that
		// would restart e1, and the run skips the reconcile all the same.
		{name: "unchanged over a plan that would restart a node", moved: true, skipped: true,
			holds: map[string]string{"e1": stepToID, "e2": stepToID, "s1": stepToID},
			change: func(f *StepFields) {
				f.Outcome, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter, f.Pushed = wire.StepUnchanged,
					false, nil, nil, nil
			}},
		{name: "diverged at its stage", phase: "reconcile",
			holds: map[string]string{"e1": stepFromID, "e2": stepFromID, "s1": stepFromID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "reconcile", divergedFindings(findings.RuleStageFailed, findings.StepStage)
				f.Staged, f.ReconcileStarted, f.ReconcileTookS, f.ReadyAfter = nil, false, nil, nil
				f.Pushed = notAttempted(f.Pushed)
			}},
		{name: "diverged at its reconcile", phase: "reconcile",
			holds: map[string]string{"e1": "null", "e2": stepFromID, "s1": stepFromID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "reconcile", divergedFindings(findings.RuleDeployFailed, findings.StepReconcile)
				f.ReconcileTookS, f.ReadyAfter = nil, nil
				f.Pushed = notAttempted(f.Pushed)
			}},
		{name: "diverged at readiness", phase: "readiness",
			holds: map[string]string{"e1": "null", "e2": stepFromID, "s1": stepFromID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "readiness", divergedFindings(findings.RuleReadinessTimeout, findings.StepReadiness)
				f.ReadyAfter = nil
				f.Pushed = notAttempted(f.Pushed)
			}},
		{name: "diverged at push, the restarted node refused", phase: "push",
			holds: map[string]string{"e1": "null", "e2": stepFromID, "s1": stepToID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
				f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
			}},
		{name: "diverged at push, the live node refused", phase: "push",
			holds: map[string]string{"e1": stepToID, "e2": stepFromID, "s1": stepFromID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushFailed, findings.StepPush)
				f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushFailed, findings.RulePushFailed, nil
			}},
		{name: "diverged at its record", phase: "record",
			holds: map[string]string{"e1": stepToID, "e2": stepFromID, "s1": stepToID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "record", divergedFindings(findings.RuleRecordFailed, findings.StepRecord)
			}},
		{name: "cancelled during its push", phase: "push",
			holds: map[string]string{"e1": "null", "e2": stepFromID, "s1": stepToID},
			change: func(f *StepFields) {
				f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RuleRunCancelled, findings.StepPush)
				f.Pushed[1].Outcome, f.Pushed[1].TookS = wire.PushNotAttempted, nil
			}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			prev := stepPrev(t)
			f := stepFields()
			if c.change != nil {
				c.change(&f)
			}
			rec, err := NewStepRecord(prev, f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			if got := holdsOf(rec); !reflect.DeepEqual(got, c.holds) {
				t.Errorf("holds %v, want %v", got, c.holds)
			}
			// The record is written before the wait, which fills it.
			if rec.Step == nil || rec.Step.Wait != nil {
				t.Errorf("step %+v; want a step block whose wait has not run", rec.Step)
			} else if b, err := json.Marshal(rec.Step); err != nil || !strings.Contains(string(b), `"wait":null`) {
				t.Errorf("the step block does not write its wait as null (%v):\n%s", err, b)
			}
			// Where the twin is: the target's after a stepped or unchanged step, the previous
			// record's after a diverged one; run and provisioned_by the create's either way.
			wantTop, wantState, wantAt := stepFromID, wire.StateDiverged, stepFromAt
			if c.moved {
				wantTop, wantState, wantAt = stepToID, wire.StateReady, stepToAt
			}
			if rec.BundleID != wantTop || rec.State != wantState || rec.Provenance.At != wantAt ||
				rec.Run != prev.Run || rec.ProvisionedBy != prev.ProvisionedBy {
				t.Errorf("top level: bundle %s, state %s, at %s, run %+v; want %s, %s, %s and the create's run",
					rec.BundleID, rec.State, rec.Provenance.At, rec.Run, wantTop, wantState, wantAt)
			}
			if c.moved && (rec.ObservedAt == nil || *rec.ObservedAt != f.ObservedAt) {
				t.Errorf("observed_at %v, want the target's read %s", rec.ObservedAt, f.ObservedAt)
			}
			if !c.moved && !reflect.DeepEqual(rec.ObservedAt, prev.ObservedAt) {
				t.Errorf("observed_at %v, want the previous record's %v", rec.ObservedAt, prev.ObservedAt)
			}
			st := rec.Step
			if st == nil || st.Outcome != f.Outcome || st.Run.WorkflowID != "fylgja-step" || st.Run.RunID != f.RunID ||
				st.From.BundleID != stepFromID || st.To.BundleID != stepToID || st.To.Branch != "" {
				t.Fatalf("step %+v", st)
			}
			if c.phase == "" && (st.Phase != nil || len(st.Findings) != 0) {
				t.Errorf("a %s step's phase %v and findings %+v; want null and none", f.Outcome, st.Phase, st.Findings)
			}
			if c.phase != "" && (st.Phase == nil || *st.Phase != c.phase || len(st.Findings) != 2 || st.Findings[1].Rule != findings.RuleStepDiverged) {
				t.Errorf("phase %v, findings %+v; want %s and the failure's findings", st.Phase, st.Findings, c.phase)
			}
			// The lists are containerlab's plan as read, skipped or not.
			r := st.Reconcile
			if r.Skipped != c.skipped || !slices.Equal(r.Restarted, f.Plan.Restarted) || !slices.Equal(r.LinksAdded, f.Plan.LinksAdded) {
				t.Errorf("reconcile skipped %t, restarted %v, links added %v; want skipped %t over the plan's %v and %v",
					r.Skipped, r.Restarted, r.LinksAdded, c.skipped, f.Plan.Restarted, f.Plan.LinksAdded)
			}
			if r.Skipped && r.TookS != nil {
				t.Errorf("a skipped reconcile carries took_s %v", *r.TookS)
			}
			// A node's artifact is what the bundle it holds names; a null holder keeps the
			// one it had.
			for _, n := range rec.Nodes {
				want := before[n.Name]
				if n.Holds != nil && *n.Holds == stepToID {
					want = after[n.Name]
				}
				if n.Artifact == nil || n.Artifact.Checksum != want {
					t.Errorf("node %s holding %v carries artifact %+v, want checksum %s", n.Name, n.Holds, n.Artifact, want)
				}
			}
		})
	}
}

// notAttempted is the push plan with every push not attempted, as when an earlier phase
// failed.
func notAttempted(plan []wire.StepPush) []wire.StepPush {
	out := make([]wire.StepPush, len(plan))
	for i, p := range plan {
		p.Outcome, p.TookS = wire.PushNotAttempted, nil
		out[i] = p
	}
	return out
}

// The stepped record's step block carries containerlab's plan with each node's declaration
// beside what it reported, the pushes, the readiness and the timings.
func TestNewStepRecordStepBlock(t *testing.T) {
	rec, err := NewStepRecord(stepPrev(t), stepFields())
	if err != nil {
		t.Fatal(err)
	}
	restart, live := "restart", "live"
	want := wire.StepRecord{
		Outcome: wire.StepStepped,
		From:    wire.StepSide{BundleID: stepFromID, At: stepFromAt},
		To:      wire.StepSide{BundleID: stepToID, At: stepToAt},
		Run:     wire.RunRef{WorkflowID: "fylgja-step", RunID: "01a1b2c3-0000-7000-8000-000000000002"}, WorkerVersion: "0.1.0-dev",
		Reconcile: wire.StepReconcile{Added: []string{}, Deleted: []string{}, Recreated: []string{}, Restarted: []string{"e1"},
			LinksAdded: []string{"e1:eth3 -- s1:e1-3"}, EndpointsDeleted: []string{},
			Nodes: []wire.StepReconcileNode{{Node: "e1", Declared: &restart, Reported: "restart", Reason: "added link"},
				{Node: "s1", Declared: &live, Reported: "live"}},
			TookS: took(3.9)},
		Pushed: []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.6)},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.4)},
		},
		ReadyAfter: []wire.StepReadyAfter{{Node: "e1", ReadyAfterS: 54.8}},
		Timings: wire.StepTimings{ReconcileS: took(3.9), Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41.2Z", Findings: []wire.StepFinding{},
	}
	if !reflect.DeepEqual(*rec.Step, want) {
		t.Errorf("step block:\n got %+v\nwant %+v", *rec.Step, want)
	}
	// The pushed nodes' times are this step's; e2's are the create's.
	for _, n := range rec.Nodes {
		wantPush, wantReady := map[string]float64{"e1": 1.6, "e2": 1, "s1": 2.4}[n.Name], map[string]float64{"e1": 54.8, "e2": 10, "s1": 10}[n.Name]
		if n.PushedInS != wantPush || n.ReadyAfterS != wantReady {
			t.Errorf("node %s pushed in %v, ready after %v; want %v and %v", n.Name, n.PushedInS, n.ReadyAfterS, wantPush, wantReady)
		}
	}
	if rec.RecordedAt != "2026-10-02T09:15:41.3Z" {
		t.Errorf("recorded_at %s, want the record's own time", rec.RecordedAt)
	}

	// A node whose package declares live and that containerlab's plan restarts keeps both:
	// the record says what was declared beside what containerlab did, never one in place of
	// the other.
	f := stepFields()
	f.Plan.Restarted = []string{"e1", "s1"}
	f.Plan.Reasons = map[string]string{"e1": "added link", "s1": "added link"}
	rec, err = NewStepRecord(stepPrev(t), f)
	if err != nil {
		t.Fatal(err)
	}
	wantNodes := []wire.StepReconcileNode{{Node: "e1", Declared: &restart, Reported: "restart", Reason: "added link"},
		{Node: "s1", Declared: &live, Reported: "restart", Reason: "added link"}}
	if got := rec.Step.Reconcile.Nodes; !reflect.DeepEqual(got, wantNodes) {
		t.Errorf("reconcile nodes %+v; want %+v, s1 declared live and reported restart", got, wantNodes)
	}
}

// A node the step neither awaited nor pushed keeps the previous record's ready_after_s and
// pushed_in_s, whether the step moved it to the target or left it on the previous bundle; a
// node the step awaited or whose push landed takes that time from the step and keeps the
// other (contracts/twin.schema.json).
func TestNewStepRecordKeepsTheTimesOfNodesItLeftAlone(t *testing.T) {
	// Each node its own times, so a time taken from another node, or from no record, shows.
	was := map[string][2]float64{"e1": {10.4, 1.1}, "e2": {12.7, 0.8}, "s1": {9.3, 2.2}}
	for _, c := range []struct {
		name   string
		change func(f *StepFields)
		want   map[string][2]float64 // ready_after_s, pushed_in_s
	}{
		// e2 is left alone and moves to the target; s1 is pushed, not awaited.
		{name: "stepped", want: map[string][2]float64{"e1": {54.8, 1.6}, "e2": {12.7, 0.8}, "s1": {9.3, 2.4}}},
		// e2 is not reached and stays on the previous bundle; s1's push failed, so its push
		// time is the previous record's too.
		{name: "diverged at push", change: func(f *StepFields) {
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushFailed, findings.StepPush)
			f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushFailed, findings.RulePushFailed, nil
		}, want: map[string][2]float64{"e1": {54.8, 1.6}, "e2": {12.7, 0.8}, "s1": {9.3, 2.2}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			prev := stepPrev(t)
			for i, n := range prev.Nodes {
				prev.Nodes[i].ReadyAfterS, prev.Nodes[i].PushedInS = was[n.Name][0], was[n.Name][1]
			}
			f := stepFields()
			if c.change != nil {
				c.change(&f)
			}
			rec, err := NewStepRecord(prev, f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, twinSchema(t), rec)
			for _, n := range rec.Nodes {
				if got := [2]float64{n.ReadyAfterS, n.PushedInS}; got != c.want[n.Name] {
					t.Errorf("node %s holding %v: ready after %v, pushed in %v; want %v", n.Name, n.Holds, got[0], got[1], c.want[n.Name])
				}
			}
		})
	}
}

// A node containerlab created or recreated that no push reached holds nothing, runs the
// target's image and package, and carries the artifact it had, or the target's when it had
// none.
func TestNewStepRecordCreatedAndRecreatedNodes(t *testing.T) {
	prev := stepPrev(t)
	f := stepFields()
	f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "readiness", divergedFindings(findings.RuleReadinessTimeout, findings.StepReadiness)
	f.Plan = wire.ReconcilePlan{Added: []string{"s2"}, Recreated: []string{"e1"}, LinksAdded: []string{"s1:e1-5 -- s2:e1-1"},
		Reasons: map[string]string{"e1": "config drift: Image"}}
	f.Declared["s2"] = "live" // its package's, which a created node's plan entry does not carry
	f.Staged.PSP["s2"] = srlinux
	f.Staged.PSP["e1"] = wire.PSPRef{ID: "arista_eos", Source: "override"}
	f.Staged.Artifacts["s2"] = stepArtifact(strings.Repeat("5252", 8))
	f.Nodes = append(f.Nodes, wire.LabNode{Name: "s2", Container: "clab-fylgja-s2", Image: "ghcr.io/nokia/srlinux:24.7.1",
		State: "running", MgmtIPv4: "172.20.20.5"})
	f.Nodes[1].Image = "ceos:4.33.0F"
	f.ReadyAfter = nil
	f.Pushed = notAttempted([]wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "recreated"}},
		{Node: "s1", Reasons: []string{"artifact", "bootstrap"}}, {Node: "s2", Reasons: []string{"artifact", "created"}}})
	rec, err := NewStepRecord(prev, f)
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, twinSchema(t), rec)
	byName := map[string]wire.TwinNode{}
	for _, n := range rec.Nodes {
		byName[n.Name] = n
	}
	if e1 := byName["e1"]; e1.Holds != nil || e1.Image != "ceos:4.33.0F" || e1.PSP.Source != "override" ||
		e1.Artifact.Checksum != before["e1"] || e1.PushedInS != 0 {
		t.Errorf("recreated e1: %+v (holds %v); want no holds, the new image and package, its old artifact", e1, e1.Holds)
	}
	if s2 := byName["s2"]; s2.Holds != nil || s2.PSP == nil || *s2.PSP != srlinux || s2.Artifact == nil || s2.Artifact.Checksum != strings.Repeat("5252", 8) {
		t.Errorf("created s2: %+v (holds %v); want no holds, its package and the target's artifact", s2, s2.Holds)
	}
	if got := holdsOf(rec); got["e2"] != stepFromID || got["s1"] != stepFromID {
		t.Errorf("holds %v; e2 and s1 untouched hold the previous bundle", got)
	}
	var created *wire.StepReconcileNode
	for i, n := range rec.Step.Reconcile.Nodes {
		if n.Node == "s2" {
			created = &rec.Step.Reconcile.Nodes[i]
		}
	}
	if created == nil || created.Declared != nil || created.Reported != wire.ReportedCreate {
		t.Errorf("created s2 in the plan: %+v; want no declaration, reported create", created)
	}
}

// A step whose plan deletes e2 records containerlab's deletion and no node e2: stepped, to a
// target that drops e2, and diverged after the reconcile removed it.
func TestNewStepRecordDeletedNode(t *testing.T) {
	for _, c := range []struct {
		name   string
		change func(f *StepFields)
		holds  map[string]string
	}{
		{name: "stepped", holds: map[string]string{"e1": stepToID, "s1": stepToID}},
		{name: "diverged at readiness", change: func(f *StepFields) {
			f.Outcome, f.Phase = wire.StepDiverged, "readiness"
			f.Findings = divergedFindings(findings.RuleReadinessTimeout, findings.StepReadiness)
			f.ReadyAfter, f.Pushed = nil, notAttempted(f.Pushed)
		}, holds: map[string]string{"e1": "null", "s1": stepFromID}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := stepFields()
			f.Plan.Deleted = []string{"e2"}
			delete(f.Staged.PSP, "e2")
			delete(f.Staged.Artifacts, "e2")
			f.Nodes = slices.DeleteFunc(f.Nodes, func(n wire.LabNode) bool { return n.Name == "e2" })
			if c.change != nil {
				c.change(&f)
			}
			rec, err := NewStepRecord(stepPrev(t), f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, twinSchema(t), rec)
			if got := rec.Step.Reconcile.Deleted; !slices.Equal(got, []string{"e2"}) {
				t.Errorf("reconcile deleted %v, want [e2]", got)
			}
			if got := holdsOf(rec); !maps.Equal(got, c.holds) {
				t.Errorf("nodes' holds %v, want %v and no e2", got, c.holds)
			}
		})
	}
}

// The second step of the example, change-1/cabled → change-1/third-link by run B over the record run A left, ten
// minutes after run A ended: the link e2:eth4 — s1:e1-4 added, so containerlab
// restarts e2 and re-cables s1 live, and the push plan is e2 (artifact, restarted) and s1
// (artifact, bootstrap). e1, which run A restarted and pushed, is left alone this time.
var stepThirdID = strings.Repeat("6b1d07c2", 8)

const (
	stepThirdAt = "2026-09-28T15:41:07.500000+00:00"
	stepRunB    = "01a1b2c3-0000-7000-8000-000000000003"
)

// later is each node's artifact checksum at change-1/third-link: e1's does not move from change-1/cabled.
var later = map[string]string{"e1": after["e1"], "e2": strings.Repeat("e2d3", 8), "s1": strings.Repeat("5d3c", 8)}

func thirdTarget() *StagedTarget {
	return &StagedTarget{BundleID: stepThirdID,
		Provenance: wire.Provenance{Branch: "change-1", At: stepThirdAt, SchemaHash: "4d5b37aa", Scope: "tag:fylgja", Mapping: dcimMapping},
		PSP:        map[string]wire.PSPRef{"e1": eos, "e2": eos, "s1": srlinux},
		Artifacts: map[string]*wire.TwinArtifact{"e1": stepArtifact(later["e1"]), "e2": stepArtifact(later["e2"]),
			"s1": stepArtifact(later["s1"])}}
}

// secondStepFields is run B's step, stepped. Each case changes what its outcome changes.
func secondStepFields() StepFields {
	f := stepFields()
	f.From = wire.StepSide{BundleID: stepToID, At: stepToAt}
	f.To = wire.StepSide{BundleID: stepThirdID, At: stepThirdAt, Branch: "change-1"}
	f.ObservedAt = "2026-10-02T09:25:30.000000Z"
	f.RunID = stepRunB
	f.AllowRestart = true
	f.Plan = wire.ReconcilePlan{Restarted: []string{"e2"}, LinksAdded: []string{"e2:eth4 -- s1:e1-4"},
		Reasons: map[string]string{"e2": "added link"}}
	f.ReconcileTookS = took(4.2)
	f.ReadyAfter = []wire.ReadinessResult{{Node: "e2", ReadyAfterS: 51.3}}
	f.Pushed = []wire.StepPush{
		{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.1)},
		{Node: "e2", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.9)},
	}
	f.StartedAt, f.EndedAt = "2026-10-02T09:25:41.2Z", "2026-10-02T09:26:50.7Z"
	f.RecordedAt = time.Date(2026, 10, 2, 9, 26, 50, 800000000, time.UTC)
	f.Staged = thirdTarget()
	return f
}

// A step from a record that has already stepped keeps nothing of the previous step but the
// bundle it came from: the step block is the second run's alone, the top level is the new
// target's (or stays the first target's when the second step diverged), run and
// provisioned_by stay the create's, each node holds one side of the second step and keeps
// the times the first step gave it where the second left it alone, and the pause between
// the two steps is read from the two records.
func TestNewStepRecordFromASteppedRecord(t *testing.T) {
	s := twinSchema(t)
	create := stepPrev(t)
	first, err := NewStepRecord(create, stepFields())
	if err != nil {
		t.Fatal(err)
	}
	validateRecord(t, s, first)
	restart, live := "restart", "live"

	for _, c := range []struct {
		name   string
		change func(f *StepFields)
		moved  bool
		holds  map[string]string
		times  map[string][2]float64 // ready_after_s, pushed_in_s
		block  func(want *wire.StepRecord)
	}{
		{name: "stepped", moved: true,
			holds: map[string]string{"e1": stepThirdID, "e2": stepThirdID, "s1": stepThirdID},
			// e1 keeps run A's times; s1's readiness is the create's, which neither step awaited.
			times: map[string][2]float64{"e1": {54.8, 1.6}, "e2": {51.3, 1.9}, "s1": {10, 2.1}}},
		{name: "diverged at push, the live node failed", change: func(f *StepFields) {
			var l findings.List
			l.AddStep(findings.Rejection, findings.StepPush, findings.RulePushFailed, "s1", "the push did not answer")
			l.AddStep(findings.Rejection, findings.StepPush, findings.RuleStepDiverged, stepRunB, "the step stopped")
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, l
			f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushFailed, findings.RulePushFailed, nil
		},
			holds: map[string]string{"e1": stepToID, "e2": stepThirdID, "s1": stepToID},
			times: map[string][2]float64{"e1": {54.8, 1.6}, "e2": {51.3, 1.9}, "s1": {10, 2.4}},
			block: func(want *wire.StepRecord) {
				phase := findings.StepPush
				want.Outcome, want.Phase = wire.StepDiverged, &phase
				want.Pushed[1].Outcome, want.Pushed[1].Rule, want.Pushed[1].TookS = wire.PushFailed, findings.RulePushFailed, nil
				want.Timings.Push = map[string]float64{"e2": 1.9}
				want.Findings = []wire.StepFinding{{Rule: findings.RulePushFailed, Object: "s1", Message: "the push did not answer"},
					{Rule: findings.RuleStepDiverged, Object: stepRunB, Message: "the step stopped"}}
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := secondStepFields()
			if c.change != nil {
				c.change(&f)
			}
			rec, err := NewStepRecord(first, f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)

			wantTop, wantState, wantAt, wantObserved := stepToID, wire.StateDiverged, stepToAt, first.ObservedAt
			if c.moved {
				wantTop, wantState, wantAt, wantObserved = stepThirdID, wire.StateReady, stepThirdAt, &f.ObservedAt
			}
			if rec.BundleID != wantTop || rec.State != wantState || rec.Provenance.At != wantAt ||
				!reflect.DeepEqual(rec.ObservedAt, wantObserved) {
				t.Errorf("top level: bundle %s, state %s, at %s, observed_at %v; want %s, %s, %s, %v",
					rec.BundleID, rec.State, rec.Provenance.At, rec.ObservedAt, wantTop, wantState, wantAt, wantObserved)
			}
			if rec.Run != create.Run || rec.ProvisionedBy != create.ProvisionedBy {
				t.Errorf("run %+v, provisioned_by %+v; want the create's, %+v and %+v", rec.Run, rec.ProvisionedBy, create.Run, create.ProvisionedBy)
			}

			// The step block is run B's, field for field.
			want := wire.StepRecord{
				Outcome: wire.StepStepped,
				From:    wire.StepSide{BundleID: stepToID, At: stepToAt},
				To:      wire.StepSide{BundleID: stepThirdID, At: stepThirdAt},
				Run:     wire.RunRef{WorkflowID: "fylgja-step", RunID: stepRunB}, WorkerVersion: "0.1.0-dev", AllowRestart: true,
				Reconcile: wire.StepReconcile{Added: []string{}, Deleted: []string{}, Recreated: []string{}, Restarted: []string{"e2"},
					LinksAdded: []string{"e2:eth4 -- s1:e1-4"}, EndpointsDeleted: []string{},
					Nodes: []wire.StepReconcileNode{{Node: "e2", Declared: &restart, Reported: "restart", Reason: "added link"},
						{Node: "s1", Declared: &live, Reported: "live"}},
					TookS: took(4.2)},
				Pushed: []wire.StepPush{
					{Node: "e2", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: took(1.9)},
					{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: took(2.1)},
				},
				ReadyAfter: []wire.StepReadyAfter{{Node: "e2", ReadyAfterS: 51.3}},
				Timings: wire.StepTimings{ReconcileS: took(4.2), Readiness: map[string]float64{"e2": 51.3},
					Push: map[string]float64{"e2": 1.9, "s1": 2.1}, WholeS: 69.5},
				StartedAt: "2026-10-02T09:25:41.2Z", EndedAt: "2026-10-02T09:26:50.7Z", Findings: []wire.StepFinding{},
			}
			if c.block != nil {
				c.block(&want)
			}
			if !reflect.DeepEqual(*rec.Step, want) {
				t.Errorf("step block:\n got %+v\nwant %+v", *rec.Step, want)
			}
			// Nothing of run A's block survives anywhere in the record: its run, its times and
			// the link its reconcile added are its block's alone.
			b, err := json.Marshal(rec)
			if err != nil {
				t.Fatal(err)
			}
			for _, a := range []string{first.Step.Run.RunID, first.Step.StartedAt, first.Step.EndedAt, "e1:eth3 -- s1:e1-3"} {
				if strings.Contains(string(b), a) {
					t.Errorf("the record carries %q of the first step:\n%s", a, b)
				}
			}
			// The bundle it came from is the first record's.
			if rec.Step.From.BundleID != first.BundleID {
				t.Errorf("from bundle %s, want the first record's %s", rec.Step.From.BundleID, first.BundleID)
			}
			// The pause at change-1/cabled is run B's start less run A's end, each read from its record.
			startedB, err1 := time.Parse(time.RFC3339Nano, rec.Step.StartedAt)
			endedA, err2 := time.Parse(time.RFC3339Nano, first.Step.EndedAt)
			if err1 != nil || err2 != nil || startedB.Sub(endedA) != 10*time.Minute {
				t.Errorf("pause %s (%v, %v), want 10m0s", startedB.Sub(endedA), err1, err2)
			}

			if got := holdsOf(rec); !reflect.DeepEqual(got, c.holds) {
				t.Errorf("holds %v, want %v", got, c.holds)
			}
			for _, n := range rec.Nodes {
				if got := [2]float64{n.ReadyAfterS, n.PushedInS}; got != c.times[n.Name] {
					t.Errorf("node %s: ready after %v, pushed in %v; want %v", n.Name, got[0], got[1], c.times[n.Name])
				}
				want := after[n.Name]
				if n.Holds != nil && *n.Holds == stepThirdID {
					want = later[n.Name]
				}
				if n.Artifact == nil || n.Artifact.Checksum != want {
					t.Errorf("node %s holding %v carries artifact %+v, want checksum %s", n.Name, n.Holds, n.Artifact, want)
				}
			}
		})
	}
}

// A step from a record M10 wrote, which reads with no state and no scope, writes the current
// version, 12 since 020: a step's record carries state, step and holds, which version 3 does
// not have, and the target's provenance, scope and mapping included
// (contracts/twin.schema.json). twin step refuses such a twin before any run (the server's
// refusal of a record of 11 or earlier, step.twin.unsteppable); this is the record's own rule
// beneath it. Stepped, n1 holds the target. Diverged at a refused push, the record would keep
// version 3's provenance, which names no scope, so it is refused: twin.json 12 cannot hold it.
func TestNewStepRecordFromAVersion3Record(t *testing.T) {
	s := twinSchema(t)
	from := readVersion3(t)
	n1 := strings.Repeat("9a01", 8)
	fields := func() StepFields {
		return StepFields{
			Outcome:    wire.StepStepped,
			From:       wire.StepSide{BundleID: from.BundleID, At: from.Provenance.At},
			To:         wire.StepSide{BundleID: stepToID, At: stepToAt},
			ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: "01a1b2c3-0000-7000-8000-000000000004", Version: "0.1.0-dev",
			Declared:  map[string]string{"n1": "live"},
			Pushed:    []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(0.8)}},
			StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:33Z",
			RecordedAt: time.Date(2026, 10, 2, 9, 14, 33, 0, time.UTC),
			Nodes: []wire.LabNode{{Name: "n1", Container: "clab-fylgja-n1", Image: "ghcr.io/nokia/srlinux:24.7.1",
				State: "running", MgmtIPv4: "172.20.20.2"}},
			Staged: &StagedTarget{BundleID: stepToID,
				Provenance: wire.Provenance{Branch: "fylgja-fixture", At: stepToAt, SchemaHash: "abc123", Scope: "tag:fylgja", Mapping: dcimMapping},
				PSP:        map[string]wire.PSPRef{"n1": srlinux}, Artifacts: map[string]*wire.TwinArtifact{"n1": stepArtifact(n1)}},
		}
	}
	t.Run("stepped", func(t *testing.T) {
		rec, err := NewStepRecord(from, fields())
		if err != nil {
			t.Fatal(err)
		}
		if rec.TwinVersion != TwinVersion || TwinVersion != "12" || rec.State != wire.StateReady || rec.Step == nil {
			t.Errorf("record version %q, state %q, step %v; want version 12, state ready and a step block",
				rec.TwinVersion, rec.State, rec.Step != nil)
		}
		if got := holdsOf(rec); !maps.Equal(got, map[string]string{"n1": stepToID}) {
			t.Errorf("holds %v, want n1 holding %s", got, stepToID)
		}
		if rec.Provenance != fields().Staged.Provenance {
			t.Errorf("provenance %+v, want the target's %+v", rec.Provenance, fields().Staged.Provenance)
		}
		validateRecord(t, s, rec)
	})
	t.Run("diverged at a refused push", func(t *testing.T) {
		f := fields()
		f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, divergedFindings(findings.RulePushRefused, findings.StepPush)
		f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushRefused, findings.RulePushRefused, nil
		_, err := NewStepRecord(from, f)
		if err == nil || !strings.Contains(err.Error(), "keeps the provenance of twin.json 3") ||
			!strings.Contains(err.Error(), "names the scope its read was made under") {
			t.Errorf("err = %v, want the refusal of a record keeping twin.json 3's provenance, which names no scope", err)
		}
	})
}

// NewStepRecord refuses a record the contract would refuse, or one that would claim more
// than the step did.
func TestNewStepRecordRefuses(t *testing.T) {
	for _, c := range []struct {
		name   string
		prev   func(r *wire.TwinRecord)
		change func(f *StepFields)
		want   string
	}{
		{name: "the record names another bundle", prev: func(r *wire.TwinRecord) { r.BundleID = stepOther },
			want: "the record names bundle " + stepOther + ", not bundle " + stepFromID},
		{name: "the record is diverged", prev: func(r *wire.TwinRecord) { r.State = wire.StateDiverged },
			want: "no step starts from a diverged twin"},
		{name: "a node of the record holds a third bundle", prev: func(r *wire.TwinRecord) { r.Nodes[1].Holds = &stepOther },
			want: "node e2 holds bundle " + stepOther + ", which is neither side"},
		{name: "no run", change: func(f *StepFields) { f.RunID = "" }, want: "must name its step run"},
		{name: "no identity", change: func(f *StepFields) { f.To.BundleID = "nope" }, want: "between two bundle identities"},
		{name: "a time that is not RFC 3339", change: func(f *StepFields) { f.EndedAt = "later" }, want: "must be RFC 3339"},
		{name: "an outcome of no record", change: func(f *StepFields) { f.Outcome = "rejected" }, want: `unknown step outcome "rejected"`},
		{name: "a stepped step with a phase", change: func(f *StepFields) { f.Phase = "push" }, want: `a stepped step has no failed phase, but "push" was given`},
		{name: "a diverged step with no phase", change: func(f *StepFields) { f.Outcome = wire.StepDiverged },
			want: `one of flows, reconcile, readiness, push or record, not ""`},
		{name: "a diverged step at a phase a step lacks", change: func(f *StepFields) { f.Outcome, f.Phase = wire.StepDiverged, "teardown" },
			want: `not "teardown"`},
		{name: "a stepped step whose target is not staged", change: func(f *StepFields) { f.Staged = nil },
			want: "but the twin directory does not hold it"},
		{name: "a stepped step whose staged bundle is another", change: func(f *StepFields) { f.Staged.BundleID = stepOther },
			want: "the twin directory holds bundle " + stepOther + ", not bundle " + stepToID},
		{name: "a stepped step whose manifest is pinned elsewhere", change: func(f *StepFields) { f.Staged.Provenance.At = stepFromAt },
			want: `the staged manifest is pinned at "` + stepFromAt + `", not at "` + stepToAt + `"`},
		{name: "a stepped step with a push that did not land", change: func(f *StepFields) { f.Pushed[0].Outcome = wire.PushRefused },
			want: "a stepped step landed every push, but node s1's is refused"},
		{name: "a stepped step whose lab runs a node the target lacks", change: func(f *StepFields) { delete(f.Staged.PSP, "e2") },
			want: "containerlab reports node e2, which the target bundle " + stepToID + " does not name"},
		{name: "a stepped step whose lab lacks a node of the target", change: func(f *StepFields) { f.Nodes = f.Nodes[:2] },
			want: "names node e2, which containerlab does not report"},
		{name: "a diverged step that landed a push with nothing staged", change: func(f *StepFields) {
			f.Outcome, f.Phase, f.Staged = wire.StepDiverged, "push", nil
		}, want: "node s1's push landed, but the twin directory does not hold the target bundle"},
	} {
		t.Run(c.name, func(t *testing.T) {
			prev := stepPrev(t)
			if c.prev != nil {
				c.prev(&prev)
			}
			f := stepFields()
			if c.change != nil {
				c.change(&f)
			}
			if _, err := NewStepRecord(prev, f); err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("err = %v, want one saying %q", err, c.want)
			}
		})
	}
}
