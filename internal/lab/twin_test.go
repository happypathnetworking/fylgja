package lab

import (
	"bytes"
	"context"
	"encoding/json"
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

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// twinSchema is the current contract the record satisfies: twin.json 7, which NewRecord and
// NewStepRecord write, under the module root's contracts/.
func twinSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return twinSchemaOf(t, "")
}

// twinSchemaOf is feature's copy of twin.schema.json: "" is the current contract, and an
// earlier feature's is its frozen copy under testdata/contracts/<feature>/, which keeps the
// records its milestone wrote, such as M11's 4 (009-stepping), M12's 5 (010-verify) and
// 014's 6 (014-proposed-change-stages).
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

func fields(source string, observedAt *string) RecordFields {
	return RecordFields{
		BundleID:   "4d5f3e2308a8248f600c2dcf83cc360f6101ca97a9ca717dc2b6e0c02827e31a",
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc123", ContractVersion: "0.2"},
		ObservedAt: observedAt,
		Source:     source,
		RunID:      "01a0a570-0395-78ee-8d0f-9a45a97547cd",
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 15, 14, 22, 53, 390000000, time.UTC),
		Nodes: []wire.TwinNode{
			{Name: "n2", Container: "clab-fylgja-n2", Image: "ghcr.io/nokia/srlinux:24.7.1",
				PSP: wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}, MgmtIPv4: "172.20.20.3", ReadyAfterS: 0.897,
				Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: "ecb03029ea805a09c54d2cd6a0e59ac9", Size: 861},
				PushedInS: 0.7},
			{Name: "n1", Container: "clab-fylgja-n1", Image: "ghcr.io/nokia/srlinux:24.7.1",
				PSP: wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"}, MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.761,
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

// change1 is the proposed change of the examples, pc-1, whose source branch is change-1
// (014).
var change1 = wire.StageChange{ID: "pc-1", Branch: "change-1"}

// cabled is the stage of contracts/stage-commands.md's examples, change-1/cabled, as the
// record names it: a mark whose at is its own write stamp.
func cabled() *wire.StageRef {
	return &wire.StageRef{ProposedChange: change1, Label: "cabled", Description: "after the first cut-over", AtSource: findings.AtSourceWritten}
}

// mark is change-1's mark label, its at given on the mark, as the record names it.
func mark(label string) *wire.StageRef {
	return &wire.StageRef{ProposedChange: change1, Label: label, Description: "cut " + label, AtSource: findings.AtSourceGiven}
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

// A create's record names the stage the twin was created from (twin.json 6, 014, which 7
// keeps): its proposed change by id and source branch, its label, its description and where
// its at came from, for each of the four sources, with step null; a branch-point twin reads
// the default branch, so its provenance.branch is main. A record written with --branch or
// from a bundle says "stage": null explicitly, and a step's record carries the same shape on
// each side.
func TestRecordNamesItsStage(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-10-16T09:31:02.118842Z"
	for _, c := range []struct {
		source, label, description, branch, at string
	}{
		{findings.AtSourceWritten, "cabled", "after the first cut-over", "change-1", "2026-10-16T09:20:44.000000+00:00"},
		{findings.AtSourceGiven, "seeded", "the devices, no links", "change-1", "2026-10-16T09:00:00+00:00"},
		{findings.AtSourceHead, "head", "", "change-1", "2026-10-16T09:25:00.000001+00:00"},
		{findings.AtSourceBranchPoint, "branch-point", "", "main", "2026-10-16T08:00:00.123456+00:00"},
	} {
		t.Run(c.source, func(t *testing.T) {
			f := fields(wire.SourceIntent, &observed)
			f.Provenance.Branch, f.Provenance.At = c.branch, c.at
			f.Stage = &wire.StageRef{ProposedChange: change1, Label: c.label, Description: c.description, AtSource: c.source}
			rec, err := NewRecord(f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			got := jsonOf(t, rec).(map[string]any)
			want := map[string]any{"proposed_change": map[string]any{"id": "pc-1", "branch": "change-1"},
				"label": c.label, "description": c.description, "at_source": c.source}
			if got["twin_version"] != "7" || !reflect.DeepEqual(got["stage"], want) {
				t.Errorf("twin_version %v, stage %v; want 7 naming %v", got["twin_version"], got["stage"], want)
			}
			if step, ok := got["step"]; !ok || step != nil {
				t.Errorf("step %v (present %t); want an explicit null", step, ok)
			}
			if p := got["provenance"].(map[string]any); p["branch"] != c.branch || p["at"] != c.at {
				t.Errorf("provenance %v; want branch %s at %s", p, c.branch, c.at)
			}
		})
	}

	t.Run("branch-sourced and bundle-sourced records name no stage", func(t *testing.T) {
		for label, f := range map[string]RecordFields{
			"intent": fields(wire.SourceIntent, &observed),
			"bundle": fields(wire.SourceBundle, nil),
		} {
			rec, err := NewRecord(f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			if got, ok := jsonOf(t, rec).(map[string]any)["stage"]; !ok || got != nil {
				t.Errorf("%s: stage %v (present %t); a record naming no stage must say null explicitly", label, got, ok)
			}
		}
	})

	t.Run("a step's record names the stage on each side", func(t *testing.T) {
		f := stepFields()
		f.To.Stage = &wire.StageRef{ProposedChange: change1, Label: "head", AtSource: findings.AtSourceHead}
		rec, err := NewStepRecord(stepPrev(t), f)
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, rec)
		got := jsonOf(t, rec).(map[string]any)
		step := got["step"].(map[string]any)
		from, to := step["from"].(map[string]any), step["to"].(map[string]any)
		if !reflect.DeepEqual(from["stage"], jsonOf(t, mark("seeded"))) || !reflect.DeepEqual(to["stage"], jsonOf(t, f.To.Stage)) {
			t.Errorf("step.from.stage %v, step.to.stage %v; want %v and %v", from["stage"], to["stage"],
				jsonOf(t, mark("seeded")), jsonOf(t, f.To.Stage))
		}
		if !reflect.DeepEqual(got["stage"], to["stage"]) || got["twin_version"] != "7" {
			t.Errorf("twin_version %v, stage %v; want 7 naming the stage the step went to", got["twin_version"], got["stage"])
		}
	})
}

// A stage is recorded only on a pinned twin created from intent: the record NewRecord
// refuses is the one twin.schema.json's conditional refuses.
func TestNewRecordRefusesAStageItCannotHold(t *testing.T) {
	onBundle := fields(wire.SourceBundle, nil)
	onBundle.Provenance.At = "2026-09-28T15:20:44.000000+00:00"
	onBundle.Stage = cabled()
	if _, err := NewRecord(onBundle); err == nil || !strings.Contains(err.Error(), "cannot record stage change-1/cabled: a bundle carries no stage") {
		t.Errorf("a stage on a bundle record: err = %v, want a refusal naming change-1/cabled and saying a bundle carries no stage", err)
	}

	observed := "2026-09-28T15:31:02.118842Z"
	unpinned := fields(wire.SourceIntent, &observed)
	unpinned.Stage = cabled()
	if _, err := NewRecord(unpinned); err == nil || !strings.Contains(err.Error(), "stage change-1/cabled must record its at: a stage twin is pinned") {
		t.Errorf("a stage with no at: err = %v, want a refusal naming change-1/cabled and saying a stage twin is pinned", err)
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

// olderRecord is rec as a worker of twin.json version, 4 or 5, wrote it: the rehearsal key
// is not there, the stage key gives way to M10's, top at the top level and from and to on
// the step's sides (nil writes null), and a 4's step has no wait.
func olderRecord(t *testing.T, rec wire.TwinRecord, version string, top, from, to any) []byte {
	t.Helper()
	generic := jsonOf(t, rec).(map[string]any)
	generic["twin_version"] = version
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

// A record of 5 or earlier still reads, with no stage (014, research R-11): one that names
// M10's waypoint, which this build no longer reads, reads Superseded, so twin step can say
// why it refuses it; one whose waypoint is null, or a version 2 one with no key, does not.
// Each version 5 record is one twin.json 5's frozen contract accepts, and reads with
// everything else as written; Superseded is never written.
func TestRecord5ReadsWithNoStage(t *testing.T) {
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
	unstaged := func(rec wire.TwinRecord, superseded bool) wire.TwinRecord {
		rec.TwinVersion, rec.Stage, rec.Superseded = "5", nil, superseded
		if rec.Step != nil {
			st := *rec.Step
			st.From.Stage, st.To.Stage = nil, nil
			rec.Step = &st
		}
		return rec
	}
	for _, c := range []struct {
		name string
		b    []byte
		want wire.TwinRecord
	}{
		{"a create naming a waypoint", olderRecord(t, create, "5", m10Waypoint(2), nil, nil), unstaged(create, true)},
		{"a create naming none", olderRecord(t, create, "5", nil, nil, nil), unstaged(create, false)},
		{"a step between two waypoints", olderRecord(t, step, "5", m10Waypoint(2), m10Waypoint(1), m10Waypoint(2)), unstaged(step, true)},
	} {
		t.Run(c.name, func(t *testing.T) {
			validateBytes(t, v5, c.b)
			got := readBytes(t, c.b)
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("read %+v\nwant %+v", got, c.want)
			}
			if _, ok := jsonOf(t, got).(map[string]any)["superseded"]; ok {
				t.Error("the record writes superseded; it is the reader's alone")
			}
		})
	}

	t.Run("a version 2 record", func(t *testing.T) {
		rec := readBytes(t, []byte(version2Record))
		if rec.TwinVersion != "2" || rec.Provenance.At != "2026-09-20T10:00:00Z" || rec.Stage != nil || rec.Superseded {
			t.Errorf("read %+v; want version 2, its at, no stage and not superseded", rec)
		}
	})
	t.Run("a version 3 record naming a waypoint", func(t *testing.T) {
		if rec := readVersion3(t); rec.Stage != nil || !rec.Superseded {
			t.Errorf("read stage %+v, superseded %t; want no stage, superseded", rec.Stage, rec.Superseded)
		}
	})
}

// rehearsal is the rehearsal run of contracts/rehearse-command.md's examples, as the record
// names it (015).
func rehearsal() *wire.RehearsalRef {
	return &wire.RehearsalRef{WorkflowID: wire.RehearseWorkflowID, RunID: "01a1b2c3-0000-7000-8000-0000000000a1"}
}

// A create's record is twin.json 7 (015): a rehearsal's baseline names the rehearsal run, the
// workflow fylgja-rehearse and its run id, and a twin no rehearsal created says "rehearsal":
// null explicitly; a step's record keeps the create's, whichever it is. The contract refuses
// a 7 record with no rehearsal key, or one naming another workflow or no run, and so does
// NewRecord.
func TestRecord7(t *testing.T) {
	s := twinSchema(t)
	observed := "2026-10-19T09:31:02.118842Z"
	baseline := func() RecordFields {
		f := fields(wire.SourceIntent, &observed)
		f.Provenance.Branch, f.Provenance.At = "change-1", "2026-10-19T09:00:00+00:00"
		f.Stage, f.Rehearsal = mark("seeded"), rehearsal()
		return f
	}

	t.Run("a rehearsal's baseline", func(t *testing.T) {
		rec, err := NewRecord(baseline())
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, s, rec)
		got := jsonOf(t, rec).(map[string]any)
		want := map[string]any{"workflow_id": "fylgja-rehearse", "run_id": "01a1b2c3-0000-7000-8000-0000000000a1"}
		if got["twin_version"] != "7" || !reflect.DeepEqual(got["rehearsal"], want) {
			t.Errorf("twin_version %v, rehearsal %v; want 7 naming %v", got["twin_version"], got["rehearsal"], want)
		}
		if got["run"].(map[string]any)["workflow_id"] != wire.ProvisionWorkflowID {
			t.Errorf("run %v; the record's run stays the provisioning run's", got["run"])
		}
	})

	t.Run("a hand twin", func(t *testing.T) {
		for label, f := range map[string]RecordFields{
			"intent": fields(wire.SourceIntent, &observed),
			"bundle": fields(wire.SourceBundle, nil),
		} {
			rec, err := NewRecord(f)
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, s, rec)
			if got, ok := jsonOf(t, rec).(map[string]any)["rehearsal"]; !ok || got != nil {
				t.Errorf("%s: rehearsal %v (present %t); a record naming no rehearsal must say null explicitly", label, got, ok)
			}
		}
	})

	t.Run("a step's record keeps the create's", func(t *testing.T) {
		for label, ref := range map[string]*wire.RehearsalRef{"a rehearsal's": rehearsal(), "none": nil} {
			prev := stepPrev(t)
			prev.Rehearsal = ref
			for _, outcome := range []string{wire.StepStepped, wire.StepDiverged} {
				f := stepFields()
				if outcome == wire.StepDiverged {
					f.Outcome, f.Phase, f.Findings = wire.StepDiverged, "push", divergedFindings(findings.RulePushRefused, findings.StepPush)
					f.Pushed[1].Outcome, f.Pushed[1].Rule, f.Pushed[1].TookS = wire.PushRefused, findings.RulePushRefused, nil
				}
				rec, err := NewStepRecord(prev, f)
				if err != nil {
					t.Fatal(err)
				}
				validateRecord(t, s, rec)
				if !reflect.DeepEqual(rec.Rehearsal, ref) {
					t.Errorf("%s, %s: rehearsal %+v, want the create's %+v", label, outcome, rec.Rehearsal, ref)
				}
			}
		}
	})

	t.Run("the contract refuses a rehearsal it cannot hold", func(t *testing.T) {
		rec, err := NewRecord(baseline())
		if err != nil {
			t.Fatal(err)
		}
		for label, change := range map[string]func(map[string]any){
			"no rehearsal key": func(g map[string]any) { delete(g, "rehearsal") },
			"another workflow": func(g map[string]any) { g["rehearsal"].(map[string]any)["workflow_id"] = "fylgja-step" },
			"no run":           func(g map[string]any) { g["rehearsal"].(map[string]any)["run_id"] = "" },
			"another key":      func(g map[string]any) { g["rehearsal"].(map[string]any)["stage"] = "change-1/seeded" },
			"twin_version 6":   func(g map[string]any) { g["twin_version"] = "6" },
		} {
			generic := jsonOf(t, rec).(map[string]any)
			change(generic)
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(mustJSON(t, generic)))
			if err != nil {
				t.Fatal(err)
			}
			if err := s.Validate(v); err == nil {
				t.Errorf("%s: twin.schema.json 7 accepts it", label)
			}
		}
	})

	t.Run("NewRecord refuses a rehearsal the contract would", func(t *testing.T) {
		for label, ref := range map[string]*wire.RehearsalRef{
			"another workflow": {WorkflowID: wire.StepWorkflowID, RunID: "01a1b2c3-0000-7000-8000-0000000000a1"},
			"no run":           {WorkflowID: wire.RehearseWorkflowID},
		} {
			f := baseline()
			f.Rehearsal = ref
			if _, err := NewRecord(f); err == nil || !strings.Contains(err.Error(), "names its rehearsal as a fylgja-rehearse run by its id") {
				t.Errorf("%s: err = %v, want a refusal saying a rehearsal is a fylgja-rehearse run by its id", label, err)
			}
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

// A record of 6 or earlier still reads, with no rehearsal (015): a create's and a step's
// record as a 014 worker wrote them, which twin.json 6's frozen contract accepts, read with
// Rehearsal nil and everything else as written, so twin rehearse refuses such a twin and
// never reclaims it.
func TestRecord6ReadsWithNoRehearsal(t *testing.T) {
	v6 := twinSchemaOf(t, "014-proposed-change-stages")
	observed := "2026-10-16T09:31:02.118842Z"
	staged := fields(wire.SourceIntent, &observed)
	staged.Provenance.At, staged.Stage = "2026-10-16T09:00:00+00:00", mark("seeded")
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
			delete(generic, "rehearsal")
			b := []byte(mustJSON(t, generic))
			validateBytes(t, v6, b)
			got := readBytes(t, b)
			want := rec
			want.TwinVersion = "6"
			if got.Rehearsal != nil || !reflect.DeepEqual(got, want) {
				t.Errorf("read %+v\nwant %+v, with no rehearsal", got, want)
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
		{Node: "n2", PushedInS: 0.62, Checksum: "5ac21560015ad6bb1e881358115d0b7a", Size: 707},
		{Node: "n1", PushedInS: 0.7, Checksum: "597f6263eb7e0b539679b3956270876f", Size: 707},
		{Node: "n3", PushedInS: 0.65, Checksum: "e93df96400ddbada7daa1a0777d9d3e3", Size: 707},
	}
	artifact := func(checksum string) *wire.TwinArtifact {
		return &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: checksum, Size: 707}
	}
	// The golden manifest's provenance block, which the plan carries and the record copies:
	// until twin.json 8 (017's T025), without the scope and the mapping record 7 has no
	// place for, and with no contract version, since a bundle "5" read none.
	provenance := wire.Provenance{Branch: "fylgja-fixture", At: "2026-09-08T12:00:00Z", SchemaHash: "fixture"}
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
			{Name: "n1", Container: "clab-fylgja-n1", Image: image, PSP: srlinux, MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.761,
				Artifact: artifact("597f6263eb7e0b539679b3956270876f"), PushedInS: 0.7, Holds: &holds},
			{Name: "n2", Container: "clab-fylgja-n2", Image: image, PSP: srlinux, MgmtIPv4: "172.20.20.3", ReadyAfterS: 0.897,
				Artifact: artifact("5ac21560015ad6bb1e881358115d0b7a"), PushedInS: 0.62, Holds: &holds},
			{Name: "n3", Container: "clab-fylgja-n3", Image: image, PSP: srlinux, MgmtIPv4: "172.20.20.4", ReadyAfterS: 1.102,
				Artifact: artifact("e93df96400ddbada7daa1a0777d9d3e3"), PushedInS: 0.65, Holds: &holds},
		}
		if !reflect.DeepEqual(rec.Nodes, want) {
			t.Errorf("nodes:\n got %+v\nwant %+v", rec.Nodes, want)
		}
		if rec.TwinVersion != "7" || rec.State != wire.StateReady || rec.Step != nil {
			t.Errorf("twin_version %q, state %q, step %+v; want 7, ready and no step", rec.TwinVersion, rec.State, rec.Step)
		}
		if rec.Stage != nil || rec.Rehearsal != nil {
			t.Errorf("stage = %+v, rehearsal = %+v; want nil for a run given neither", rec.Stage, rec.Rehearsal)
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

	// The stage the server resolved reaches the record as data (014): RecordTwin copies it
	// and judges nothing of it.
	t.Run("names the stage it was given", func(t *testing.T) {
		a := staged(t)
		in := input(a, deployed)
		in.Stage = cabled()
		res, err := record(t, a, in)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(res.Record.Stage, cabled()) {
			t.Errorf("stage = %+v, want %+v", res.Record.Stage, cabled())
		}
		written, err := ReadRecord(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(written.Stage, cabled()) {
			t.Errorf("twin.json's stage = %+v, want %+v", written.Stage, cabled())
		}
		validateRecord(t, twinSchema(t), res.Record)
	})

	// The rehearsal whose baseline the create is reaches the record as data (015), as the
	// stage does.
	t.Run("names the rehearsal it was given", func(t *testing.T) {
		a := staged(t)
		in := input(a, deployed)
		in.Stage, in.Rehearsal = cabled(), rehearsal()
		res, err := record(t, a, in)
		if err != nil {
			t.Fatal(err)
		}
		written, err := ReadRecord(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(res.Record.Rehearsal, rehearsal()) || !reflect.DeepEqual(written.Rehearsal, rehearsal()) {
			t.Errorf("rehearsal = %+v, twin.json's %+v; want %+v", res.Record.Rehearsal, written.Rehearsal, rehearsal())
		}
		validateRecord(t, twinSchema(t), res.Record)
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

// A create writes twin.json 7: state ready, step null, and every node holding the record's
// bundle, each written out rather than left to a default; a create given no stage says
// "stage": null, and one no rehearsal started "rehearsal": null (the version moves for the
// rehearsal, 015, and a create has no step).
func TestCreateWritesVersion7(t *testing.T) {
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
	for _, want := range []string{`"twin_version":"7"`, `"stage":null`, `"rehearsal":null`, `"state":"ready"`, `"step":null`,
		`"holds":"` + rec.BundleID + `"`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("a create's record lacks %s:\n%s", want, b)
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
// step, is what twin.json 7 accepts, as 5 and 6 did; and the contract holds the key required,
// so a step block with no wait is refused (contracts/twin.schema.json).
func TestVersion7RecordCarriesEachWait(t *testing.T) {
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
		t.Error("twin.schema.json 7 accepts a step block with no wait key; it is required, null while the wait has not run")
	}
}

// A record M11 wrote, twin.json 4, has no wait in its step block and names M10's waypoint,
// and reads with Step.Wait nil, no stage on either side and Superseded set (014), and
// everything else as written. The record is a step's, as NewStepRecord built it before M12,
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
	want := rec
	want.TwinVersion, want.Stage, want.Superseded = "4", nil, true
	st := *rec.Step
	st.From.Stage, st.To.Stage = nil, nil
	want.Step = &st
	if !reflect.DeepEqual(got, want) {
		t.Errorf("read %+v\nwant %+v", got, want)
	}
}

// A version 7 record, its wait null or written, reads back and writes again byte for byte:
// nothing the wait added is lost or reshaped by a reader that writes the record again, as
// VerifyTwin does.
func TestVersion7RecordRoundTrips(t *testing.T) {
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
	third := wire.StepSide{Stage: mark("third-link"), BundleID: stepOther, At: "2026-09-28T15:40:00.000000+00:00"}
	f := stepFields()
	f.From, f.To = wire.StepSide{Stage: mark("cabled"), BundleID: stepToID, At: stepToAt}, third
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
// holding anything (shown as the record's bundle_id), and no stage, its waypoint superseded
// (014).
func TestVersion3RecordReadsWithTheDefaults(t *testing.T) {
	rec := readVersion3(t)
	if rec.TwinVersion != "3" || rec.State != "" || rec.Step != nil || len(rec.Nodes) != 1 || rec.Nodes[0].Holds != nil ||
		rec.Stage != nil || !rec.Superseded {
		t.Errorf("read %+v; want version 3 with no state, no step, no holds, no stage, and superseded", rec)
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
	observed := "2026-09-28T15:31:02.118842Z"
	f := RecordFields{BundleID: stepFromID, ObservedAt: &observed, Source: wire.SourceIntent, Stage: mark("seeded"),
		Provenance: wire.Provenance{Branch: "change-1", At: stepFromAt, SchemaHash: "4d5b37aa", ContractVersion: "0.2"},
		RunID:      "01a0e9e3-0000-7000-8000-000000000001", Version: "0.1.0-dev", RecordedAt: time.Date(2026, 10, 2, 9, 0, 0, 0, time.UTC)}
	for _, n := range []struct {
		name, image, ip string
		psp             wire.PSPRef
	}{{"e1", ceosImage, "172.20.20.2", eos}, {"e2", ceosImage, "172.20.20.3", eos}, {"s1", "ghcr.io/nokia/srlinux:24.7.1", "172.20.20.4", srlinux}} {
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n.name, Container: "clab-fylgja-" + n.name, Image: n.image, PSP: n.psp,
			MgmtIPv4: n.ip, ReadyAfterS: 10, Artifact: stepArtifact(before[n.name]), PushedInS: 1})
	}
	rec, err := NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

func stepTarget() *StagedTarget {
	return &StagedTarget{BundleID: stepToID,
		Provenance: wire.Provenance{Branch: "change-1", At: stepToAt, SchemaHash: "4d5b37aa", ContractVersion: "0.2"},
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
		From:       wire.StepSide{Stage: mark("seeded"), BundleID: stepFromID, At: stepFromAt},
		To:         wire.StepSide{Stage: mark("cabled"), BundleID: stepToID, At: stepToAt, Branch: "change-1"},
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
			wantTop, wantState, wantAt, wantStage := stepFromID, wire.StateDiverged, stepFromAt, mark("seeded")
			if c.moved {
				wantTop, wantState, wantAt, wantStage = stepToID, wire.StateReady, stepToAt, mark("cabled")
			}
			if rec.BundleID != wantTop || rec.State != wantState || rec.Provenance.At != wantAt ||
				!reflect.DeepEqual(rec.Stage, wantStage) || rec.Run != prev.Run || rec.ProvisionedBy != prev.ProvisionedBy {
				t.Errorf("top level: bundle %s, state %s, at %s, stage %+v, run %+v; want %s, %s, %s, %+v and the create's run",
					rec.BundleID, rec.State, rec.Provenance.At, rec.Stage, rec.Run, wantTop, wantState, wantAt, wantStage)
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
		From:    wire.StepSide{Stage: mark("seeded"), BundleID: stepFromID, At: stepFromAt},
		To:      wire.StepSide{Stage: mark("cabled"), BundleID: stepToID, At: stepToAt},
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
	if s2 := byName["s2"]; s2.Holds != nil || s2.PSP != srlinux || s2.Artifact == nil || s2.Artifact.Checksum != strings.Repeat("5252", 8) {
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
		Provenance: wire.Provenance{Branch: "change-1", At: stepThirdAt, SchemaHash: "4d5b37aa", ContractVersion: "0.2"},
		PSP:        map[string]wire.PSPRef{"e1": eos, "e2": eos, "s1": srlinux},
		Artifacts: map[string]*wire.TwinArtifact{"e1": stepArtifact(later["e1"]), "e2": stepArtifact(later["e2"]),
			"s1": stepArtifact(later["s1"])}}
}

// secondStepFields is run B's step, stepped. Each case changes what its outcome changes.
func secondStepFields() StepFields {
	f := stepFields()
	f.From = wire.StepSide{Stage: mark("cabled"), BundleID: stepToID, At: stepToAt}
	f.To = wire.StepSide{Stage: mark("third-link"), BundleID: stepThirdID, At: stepThirdAt, Branch: "change-1"}
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
// stage it came from: the step block is the second run's alone, the top level is the new
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

			wantTop, wantState, wantAt, wantStage, wantObserved := stepToID, wire.StateDiverged, stepToAt, mark("cabled"), first.ObservedAt
			if c.moved {
				wantTop, wantState, wantAt, wantStage, wantObserved = stepThirdID, wire.StateReady, stepThirdAt, mark("third-link"), &f.ObservedAt
			}
			if rec.BundleID != wantTop || rec.State != wantState || rec.Provenance.At != wantAt ||
				!reflect.DeepEqual(rec.Stage, wantStage) || !reflect.DeepEqual(rec.ObservedAt, wantObserved) {
				t.Errorf("top level: bundle %s, state %s, at %s, stage %+v, observed_at %v; want %s, %s, %s, %+v, %v",
					rec.BundleID, rec.State, rec.Provenance.At, rec.Stage, rec.ObservedAt, wantTop, wantState, wantAt, wantStage, wantObserved)
			}
			if rec.Run != create.Run || rec.ProvisionedBy != create.ProvisionedBy {
				t.Errorf("run %+v, provisioned_by %+v; want the create's, %+v and %+v", rec.Run, rec.ProvisionedBy, create.Run, create.ProvisionedBy)
			}

			// The step block is run B's, field for field.
			want := wire.StepRecord{
				Outcome: wire.StepStepped,
				From:    wire.StepSide{Stage: mark("cabled"), BundleID: stepToID, At: stepToAt},
				To:      wire.StepSide{Stage: mark("third-link"), BundleID: stepThirdID, At: stepThirdAt},
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
			// The stage it came from is the first record's.
			if !reflect.DeepEqual(rec.Step.From.Stage, first.Stage) {
				t.Errorf("from stage %+v, want the first record's %+v", rec.Step.From.Stage, first.Stage)
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

// A step from a record M10 wrote, which reads with no stage and no state, writes the current
// version, 6 since 014: a step's record carries stage, state, step and holds, which version 3
// does not have (contracts/twin.schema.json). twin step refuses such a twin before any run
// (provision's Ineligible, for a record naming no stage or a superseded one); this is the
// record's own rule beneath it. Stepped, n1 holds the target; diverged at a refused push, it
// holds the bundle it was built from.
func TestNewStepRecordFromAVersion3Record(t *testing.T) {
	s := twinSchema(t)
	from := readVersion3(t)
	n1 := strings.Repeat("9a01", 8)
	fields := func() StepFields {
		return StepFields{
			Outcome:    wire.StepStepped,
			From:       wire.StepSide{Stage: from.Stage, BundleID: from.BundleID, At: from.Provenance.At},
			To:         wire.StepSide{Stage: &wire.StageRef{ProposedChange: change1, Label: "third-link", AtSource: findings.AtSourceWritten}, BundleID: stepToID, At: stepToAt},
			ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: "01a1b2c3-0000-7000-8000-000000000004", Version: "0.1.0-dev",
			Declared:  map[string]string{"n1": "live"},
			Pushed:    []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(0.8)}},
			StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:33Z",
			RecordedAt: time.Date(2026, 10, 2, 9, 14, 33, 0, time.UTC),
			Nodes: []wire.LabNode{{Name: "n1", Container: "clab-fylgja-n1", Image: "ghcr.io/nokia/srlinux:24.7.1",
				State: "running", MgmtIPv4: "172.20.20.2"}},
			Staged: &StagedTarget{BundleID: stepToID,
				Provenance: wire.Provenance{Branch: "fylgja-fixture", At: stepToAt, SchemaHash: "abc123", ContractVersion: "0.2"},
				PSP:        map[string]wire.PSPRef{"n1": srlinux}, Artifacts: map[string]*wire.TwinArtifact{"n1": stepArtifact(n1)}},
		}
	}
	for _, c := range []struct {
		name   string
		change func(f *StepFields)
		state  string
		holds  string
	}{
		{"stepped", func(*StepFields) {}, wire.StateReady, stepToID},
		{"diverged at a refused push", func(f *StepFields) {
			l := divergedFindings(findings.RulePushRefused, findings.StepPush)
			f.Outcome, f.Phase, f.Findings = wire.StepDiverged, findings.StepPush, l
			f.Pushed[0].Outcome, f.Pushed[0].Rule, f.Pushed[0].TookS = wire.PushRefused, findings.RulePushRefused, nil
		}, wire.StateDiverged, from.BundleID},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := fields()
			c.change(&f)
			rec, err := NewStepRecord(from, f)
			if err != nil {
				t.Fatal(err)
			}
			if rec.TwinVersion != TwinVersion || TwinVersion != "7" || rec.State != c.state || rec.Step == nil {
				t.Errorf("record version %q, state %q, step %v; want version 7, state %s and a step block",
					rec.TwinVersion, rec.State, rec.Step != nil, c.state)
			}
			if got := holdsOf(rec); !maps.Equal(got, map[string]string{"n1": c.holds}) {
				t.Errorf("holds %v, want n1 holding %s", got, c.holds)
			}
			validateRecord(t, s, rec)
		})
	}
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
		{name: "the record names another stage", prev: func(r *wire.TwinRecord) { r.Stage = mark("third-link") },
			want: "the record names stage change-1/third-link, not stage change-1/seeded the step started from"},
		{name: "the record names another proposed change's stage", prev: func(r *wire.TwinRecord) { r.Stage.ProposedChange.ID = "pc-2" },
			want: "the record names stage change-1/seeded, not stage change-1/seeded the step started from"},
		{name: "the record names no stage", prev: func(r *wire.TwinRecord) { r.Stage = nil },
			want: "the record names stage none, not stage change-1/seeded the step started from"},
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
			want: `one of reconcile, readiness, push or record, not ""`},
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
