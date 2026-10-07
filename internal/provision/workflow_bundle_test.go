package provision

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/stretchr/testify/mock"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// A run from a stored bundle has no read and no compile: it starts at the host check with
// the bundle it was given, and its twin records that no read took place.
func TestProvisionFromBundleSkipsReadAndCompile(t *testing.T) {
	h := newHarness(t)
	bundlePath := "/state/bundles/" + testBundleID
	var checked wire.CheckHostInput
	var staged wire.StageInput
	var recorded wire.RecordInput
	h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.CheckHostInput) (wire.CheckHostResult, error) {
			checked = in
			return h.plan, nil
		})
	h.env.OnActivity(wire.ActStageBundle, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.StageInput) (wire.StageResult, error) {
			staged = in
			return wire.StageResult{TwinDir: "/state/twin"}, nil
		})
	h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
			recorded = in
			return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
		})
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceBundle, BundlePath: bundlePath, BundleID: testBundleID})

	if h.ran(wire.ActReadIntent) || h.ran(wire.ActCompile) {
		t.Errorf("activities started: %v; a run from a bundle reads and compiles nothing", h.calls())
	}
	if calls, want := h.calls(), []string{wire.ActCheckHost, wire.ActStageBundle, wire.ActDeployLab}; len(calls) < 3 || !slices.Equal(calls[:3], want) {
		t.Errorf("activities started: %v, want the run to begin %v", calls, want)
	}
	given := wire.CheckHostInput{BundlePath: bundlePath, BundleID: testBundleID}
	if checked != given || (staged != wire.StageInput{BundlePath: bundlePath, BundleID: testBundleID}) {
		t.Errorf("host check got %+v and stage %+v, want the bundle the run was given", checked, staged)
	}
	if recorded.ObservedAt != nil || recorded.Source != wire.SourceBundle {
		t.Errorf("record input: observed_at %v, source %q; want nil and %q", recorded.ObservedAt, recorded.Source, wire.SourceBundle)
	}
	if res.Outcome != OutcomeReady || res.BundleID != testBundleID || res.ObservedAt != "" {
		t.Errorf("result: outcome %q, bundle %q, observed_at %q; want ready, the given bundle, no read time", res.Outcome, res.BundleID, res.ObservedAt)
	}
	if res.Twin == nil || res.Twin.ObservedAt != nil {
		t.Fatalf("twin = %+v, want a record whose observed_at is null", res.Twin)
	}

	// The record the lab host builds from that input is one twin.schema.json accepts, and
	// says why the read time is unknown.
	rec, err := lab.NewRecord(lab.RecordFields{
		BundleID:   recorded.BundleID,
		Provenance: recorded.Provenance,
		ObservedAt: recorded.ObservedAt,
		Source:     recorded.Source,
		RunID:      recorded.RunID,
		Version:    "0.1.0-test",
		RecordedAt: time.Date(2026, 9, 15, 14, 22, 53, 0, time.UTC),
		Nodes:      recordFor(recorded).Nodes,
	})
	if err != nil {
		t.Fatalf("the lab host would refuse this record: %v", err)
	}
	if rec.ObservedAtNote != lab.ObservedAtUnknown {
		t.Errorf("note = %q, want %q", rec.ObservedAtNote, lab.ObservedAtUnknown)
	}
	mustValidateTwin(t, rec)

	doc := ProvisionDocument(findings.OpTwinProvision, &findings.Subject{Bundle: bundlePath, RunID: recorded.RunID}, res)
	if doc.Twin == nil || doc.Twin.ObservedAt != nil {
		t.Errorf("twin block = %+v, want observed_at null", doc.Twin)
	}
	mustValidateM5(t, doc, "twin provision ready")
}

// mustValidateTwin validates a record against the newest contracts/twin.schema.json the
// record step writes (M12: twin_version 5, whose state, step and each node's holds are
// required, the last two possibly null, and whose step block requires wait, possibly
// null).
func mustValidateTwin(t *testing.T, rec wire.TwinRecord) {
	t.Helper()
	f, err := os.Open(filepath.Join("..", "..", "contracts", "twin.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	schemaDoc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("twin.schema.json", schemaDoc); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("twin.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("record does not satisfy twin.schema.json:\n%v\n%s", err, b)
	}
}
