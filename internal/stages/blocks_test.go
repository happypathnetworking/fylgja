package stages

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// blocksSchema compiles one $def of contracts/stages.schema.json, the current contract the
// findings document refers to by its $id.
func blocksSchema(t *testing.T, def string) *jsonschema.Schema {
	t.Helper()
	f, err := os.Open(filepath.Join("..", "..", "contracts", "stages.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	const id = "https://github.com/happypathnetworking/fylgja/schemas/stages.schema.json"
	c := jsonschema.NewCompiler()
	if err := c.AddResource(id, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(id + "#/$defs/" + def)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// mustValidate marshals v as the document does and validates it against one $def.
func mustValidate(t *testing.T, def string, v any) string {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	inst, err := jsonschema.UnmarshalJSON(strings.NewReader(string(raw)))
	if err != nil {
		t.Fatal(err)
	}
	if err := blocksSchema(t, def).Validate(inst); err != nil {
		t.Errorf("%s does not satisfy $defs/%s:\n%v", raw, def, err)
	}
	return string(raw)
}

// Each block the surface carries validates against contracts/stages.schema.json: a
// resolved stage of each source, a listing with the record, an orphan and every row, and a
// plan with a refused stage and a step not computed.
func TestBlocksValidate(t *testing.T) {
	r, s := story()
	r.orphans = []intent.Stage{mark("st-o1", "lost", cabledAt, nil, "")}
	rec := record("cabled", cabledAt, AtWritten)
	res, _, err := List(context.Background(), r, s, "", testScope, &rec)
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Rows) != 6 {
		t.Fatalf("rows %v", rowRefs(res.Rows))
	}
	for _, row := range res.Rows {
		mustValidate(t, "resolved", row.Block())
	}
	got := mustValidate(t, "list", res.Block())
	for _, want := range []string{`"branch":null`, `"twin":true`, `"orphans":[{"id":"st-o1","label":"lost"`,
		`"record":{"ref":"change-1/cabled","proposed_change":{"id":"pc-1","branch":"change-1"}`, `"towards":null`} {
		if !strings.Contains(got, want) {
			t.Errorf("list block %s\nlacks %s", got, want)
		}
	}
	empty := ListResult{Branch: "change-9"}
	if got := mustValidate(t, "list", empty.Block()); got != `{"branch":"change-9","rows":[],"orphans":[],"record":null}` {
		t.Errorf("an empty listing %s", got)
	}
	// A row whose stage has no at carries none: a branch deleted under its proposed change.
	delete(r.branches, "change-1")
	res, _, err = List(context.Background(), r, s, "change-1", testScope, nil)
	if err != nil {
		t.Fatal(err)
	}
	got = mustValidate(t, "list", res.Block())
	if want := `{"ref":"change-1/branch-point","branch":"main","label":"branch-point","proposed_change":{"id":"pc-1",` +
		`"name":"third link","branch":"change-1","draft":true},"at_source":"branch_point","description":"","twin":false}`; !strings.Contains(got, want) {
		t.Errorf("list block %s\nlacks the branch point with no at, %s", got, want)
	}
	r.branches["change-1"] = &intent.BranchInfo{Name: "change-1", BranchedFrom: branchedFrom, CreatedAt: createdAt}

	plan, _ := planned(t, r, s, "change-1", &fakePipeline{t: t, readRefused: emptyMain})
	b, err := plan.Block()
	if err != nil {
		t.Fatal(err)
	}
	got = mustValidate(t, "plan", b)
	if !strings.Contains(got, `"proposed_change":{"id":"pc-1"`) || !strings.Contains(got, `"not_computed":"change-1/branch-point was refused"`) {
		t.Errorf("plan block %s", got)
	}
	whole := &PlanResult{Branch: "nosuch"}
	if b, err := whole.Block(); err != nil || b != nil {
		t.Errorf("a plan refused whole has block %+v, %v; want none", b, err)
	}
}

// A record view's block names its stage, its state, and a diverged step's target by label.
// twin.json 12 names no stage (020, research R-06), so the view is built here as a caller
// holding one would build it.
func TestRecordViewOf(t *testing.T) {
	r, s := story()
	res, _, err := List(context.Background(), r, s, "change-1", testScope, nil)
	if err != nil {
		t.Fatal(err)
	}
	cabled := res.Rows[1].Resolved
	v := &RecordView{ProposedChange: RecordChange{ID: cabled.ProposedChange.ID, Branch: cabled.ProposedChange.Branch},
		Label: cabled.Label, Branch: "change-1", At: cabled.At, AtSource: cabled.AtSource, State: wire.StateDiverged, Towards: "live"}
	got := mustValidate(t, "record", v.Block())
	if !strings.Contains(got, `"state":"diverged","towards":{"ref":"change-1/live"}`) {
		t.Errorf("record block %s", got)
	}
	var doc findings.StageRecord
	if err := json.Unmarshal([]byte(got), &doc); err != nil || doc.Towards == nil {
		t.Errorf("the block reads back as %+v, %v", doc, err)
	}
}
