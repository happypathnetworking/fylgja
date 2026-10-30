package api

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// contracts is the module root's contracts directory, whose api.schema.json is the wire's.
func contracts(name string) string {
	return filepath.Join("..", "..", "contracts", name)
}

// apiSchema compiles one definition of api.schema.json, with the findings schema and the
// blocks it refers to added under their $ids, so a document frame is checked against the
// document's own contract.
func apiSchema(t *testing.T, def string) *jsonschema.Schema {
	t.Helper()
	c := jsonschema.NewCompiler()
	for _, name := range []string{"api.schema.json", "findings.schema.json", "show.schema.json",
		"stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		f, err := os.Open(contracts(name))
		if err != nil {
			t.Fatal(err)
		}
		doc, err := jsonschema.UnmarshalJSON(f)
		_ = f.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		id, _ := doc.(map[string]any)["$id"].(string)
		if id == "" {
			t.Fatalf("%s has no $id", name)
		}
		if err := c.AddResource(id, doc); err != nil {
			t.Fatal(err)
		}
	}
	s, err := c.Compile("https://github.com/happypathnetworking/fylgja/schemas/api.schema.json#/$defs/" + def)
	if err != nil {
		t.Fatalf("compiling api.schema.json's %s: %v", def, err)
	}
	return s
}

func valid(t *testing.T, s *jsonschema.Schema, raw []byte, label string) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("%s: %v", label, err)
	}
	if err := s.Validate(v); err != nil {
		t.Errorf("%s does not satisfy the contract: %v\n%s", label, err, raw)
	}
}

func invalid(t *testing.T, s *jsonschema.Schema, raw, label string) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(strings.NewReader(raw))
	if err != nil {
		t.Fatalf("%s: %v", label, err)
	}
	if err := s.Validate(v); err == nil {
		t.Errorf("%s satisfied the contract: %s", label, raw)
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// A document as the server sends it: findings.WriteJSON's bytes, indented.
func documentBytes(t *testing.T, doc *findings.Document) json.RawMessage {
	t.Helper()
	var b bytes.Buffer
	if err := doc.WriteJSON(&b); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

// The eleven operations are the newest findings contract's but the five 020 moved to the
// orchestrator (D-065), which that contract's enum keeps, since the orchestrator's documents
// are findings 1 held to it (research R-13), and the core's findings declare none of
// (T035); each of the eleven is POST /v1/<noun>/<verb>. None of the five is one.
func TestOperationsAreTheContractsAndTheirPaths(t *testing.T) {
	raw, err := os.ReadFile(contracts("findings.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties struct {
			Operation struct {
				Enum []string `json:"enum"`
			} `json:"operation"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatal(err)
	}
	orchestrators := []string{"twin.rehearse", "stage.list", "stage.plan", "intent.read", "schema.check"}
	var want []string
	for _, op := range schema.Properties.Operation.Enum {
		if !slices.Contains(orchestrators, op) {
			want = append(want, op)
		}
	}
	slices.Sort(want)
	if got := slices.Sorted(slices.Values(Operations)); !slices.Equal(got, want) {
		t.Errorf("Operations = %v, the contract's enum without the orchestrator's %v", got, want)
	}
	for _, op := range orchestrators {
		if slices.Contains(Operations, op) {
			t.Errorf("Operations names %s, which 020 moved to the orchestrator", op)
		}
	}
	for op, path := range map[string]string{
		"twin.create": "/v1/twin/create", "twin.provision": "/v1/twin/provision", "twin.step": "/v1/twin/step",
		"twin.destroy": "/v1/twin/destroy", "twin.show": "/v1/twin/show", "twin.verify": "/v1/twin/verify",
		"twin.compile": "/v1/twin/compile", "psp.validate": "/v1/psp/validate",
		"run.read": "/v1/run/read", "run.interrupt": "/v1/run/interrupt",
		"twin.diff": "/v1/twin/diff",
	} {
		if got := Path(op); got != path {
			t.Errorf("Path(%s) = %s, want %s", op, got, path)
		}
	}
	if got := InterruptPath("5f1c"); got != "/v1/streams/5f1c/interrupt" {
		t.Errorf("InterruptPath = %s", got)
	}
}

// A request for each operation, with every argument it takes, is the
// contract's request, and its args are that operation's.
func TestEveryOperationsRequestSatisfiesTheContract(t *testing.T) {
	request := apiSchema(t, "request")
	str := func(s string) json.RawMessage { return mustJSON(t, s) }
	yes := json.RawMessage(`true`)
	for _, c := range []struct {
		op    string
		args  map[string]json.RawMessage
		files []File
	}{
		// 018: --snapshot as a file, the one file the request carries under its path; as an id,
		// none. From 020 it is the one argument naming a create's intent.
		{"twin.create", map[string]json.RawMessage{"snapshot": str("snap.json"), "dry_run": yes},
			[]File{{Path: "snap.json", Data: []byte(`{"snapshot_version":"1"}`)}}},
		{"twin.create", map[string]json.RawMessage{"snapshot": str(strings.Repeat("6a", 32))}, nil},
		{"twin.provision", map[string]json.RawMessage{"bundle": str("./b9d53ebc"), "dry_run": yes},
			[]File{{Path: "manifest.json", Data: []byte("{}\n")}, {Path: "configs/n1.cli", Data: []byte("set / system name host-name n1\n")}}},
		{"twin.step", map[string]json.RawMessage{"snapshot": str(strings.Repeat("6a", 32)), "allow_restart": yes, "dry_run": yes,
			"wait": str("20s")}, nil},
		{"twin.destroy", nil, nil},
		{"twin.show", nil, nil},
		{"twin.verify", map[string]json.RawMessage{"wait": str("2m0s"), "args": mustJSON(t, []string{"30s"})}, nil},
		// 018: the snapshot under the path snapshot gives, in place of the CTM under ctm's.
		{"twin.compile", map[string]json.RawMessage{"snapshot": str("snap.json"), "out": str("out")},
			[]File{{Path: "snap.json", Data: []byte(`{"snapshot_version":"1"}`)}}},
		{"psp.validate", map[string]json.RawMessage{"files": mustJSON(t, []string{"a.yaml", "b.yaml"})},
			[]File{{Path: "a.yaml", Data: []byte("psp_version: \"0.6\"\n")}, {Path: "b.yaml", Data: nil}}},
		// 020: detach on the four runs, a destroy's its one argument.
		{"twin.create", map[string]json.RawMessage{"snapshot": str(strings.Repeat("6a", 32)), "detach": yes}, nil},
		{"twin.provision", map[string]json.RawMessage{"bundle": str("./b9d53ebc"), "detach": yes},
			[]File{{Path: "manifest.json", Data: []byte("{}\n")}}},
		{"twin.step", map[string]json.RawMessage{"snapshot": str(strings.Repeat("6a", 32)), "allow_restart": yes, "detach": yes}, nil},
		{"twin.destroy", map[string]json.RawMessage{"detach": yes}, nil},
		// 020: a run by its identity, its workflow's latest run without run_id.
		{"run.read", map[string]json.RawMessage{"workflow_id": str("fylgja-provision"), "run_id": str("01a1")}, nil},
		{"run.read", map[string]json.RawMessage{"workflow_id": str("fylgja-destroy")}, nil},
		{"run.interrupt", map[string]json.RawMessage{"workflow_id": str("fylgja-step"), "run_id": str("01a1")}, nil},
		// 020: the step between two snapshots, an id and a file, the file under its path.
		{"twin.diff", map[string]json.RawMessage{"from": str(strings.Repeat("6a", 32)), "to": str("snap.json")},
			[]File{{Path: "snap.json", Data: []byte(`{"snapshot_version":"2"}`)}}},
	} {
		t.Run(c.op, func(t *testing.T) {
			// 015: markdown is a rendering every operation is asked for and accepts.
			for _, render := range []string{"", RenderText, RenderJSON, RenderMarkdown} {
				raw, err := EncodeRequest(Request{Render: render, Args: c.args, Files: c.files})
				if err != nil {
					t.Fatal(err)
				}
				if want := mustJSON(t, Request{Render: render, Args: c.args, Files: c.files}); !bytes.Equal(raw, want) {
					t.Errorf("the client sends %s, json.Marshal writes %s", raw, want)
				}
				valid(t, request, raw, c.op+" request, render "+render)
				back, err := DecodeRequest(bytes.NewReader(raw))
				if err != nil {
					t.Fatalf("DecodeRequest refuses what the client sends: %v\n%s", err, raw)
				}
				if back.Render != render || len(back.Args) != len(c.args) || len(back.Files) != len(c.files) {
					t.Errorf("decoded %+v from %s", back, raw)
				}
				for i, f := range c.files {
					if back.Files[i].Path != f.Path || !bytes.Equal(back.Files[i].Data, f.Data) {
						t.Errorf("file %d came back as %q, %q", i, back.Files[i].Path, back.Files[i].Data)
					}
				}
			}
			args := c.args
			if args == nil {
				args = map[string]json.RawMessage{}
			}
			valid(t, apiSchema(t, "args/$defs/"+c.op), mustJSON(t, args), c.op+" args")
		})
	}
	// An argument an operation does not take is not its args, and neither is twin.provision
	// without its bundle directory or twin.verify's args without wait.
	invalid(t, apiSchema(t, "args/$defs/twin.show"), `{"branch":"b"}`, "twin.show with a branch")
	// 014: the argument M10 named is gone from the operations that took it.
	for _, op := range []string{"twin.create", "twin.step"} {
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"waypoint":"demo/2"}`, op+" with a waypoint")
	}
	// 018: twin.compile's ctm is gone, renamed snapshot.
	invalid(t, apiSchema(t, "args/$defs/twin.compile"), `{"ctm":"ctm.json","out":"out"}`, "twin.compile with a ctm")
	// 019: a twin follows nothing, so twin.create takes neither the interval nor no_follow.
	invalid(t, apiSchema(t, "args/$defs/twin.create"), `{"snapshot":"s.json","interval":"30s"}`, "twin.create with an interval")
	invalid(t, apiSchema(t, "args/$defs/twin.create"), `{"snapshot":"s.json","no_follow":true}`, "twin.create with no_follow")
	invalid(t, apiSchema(t, "args/$defs/twin.provision"), `{"dry_run":true}`, "twin.provision without a bundle")
	invalid(t, apiSchema(t, "args/$defs/twin.verify"), `{"args":["30s"]}`, "twin.verify's args without wait")
	// 020: twin.create and twin.step take snapshot alone of what names their intent: branch,
	// at, stage, scope and probes are no argument of either (D-065), and the five operations
	// that read Infrahub have no args here, being no operation of the API.
	for _, op := range []string{"twin.create", "twin.step"} {
		valid(t, apiSchema(t, "args/$defs/"+op), []byte(`{"snapshot":"s.json"}`), op+" with a snapshot")
		for _, name := range []string{"branch", "at", "stage", "scope", "probes"} {
			invalid(t, apiSchema(t, "args/$defs/"+op), `{"snapshot":"s.json","`+name+`":"x"}`, op+" with "+name)
		}
	}
	for _, op := range []string{"twin.destroy", "twin.show", "twin.verify", "twin.compile", "psp.validate",
		"run.read", "run.interrupt", "twin.diff"} {
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"scope":"tag:fylgja"}`, op+" with a scope")
	}
	invalid(t, apiSchema(t, "args/$defs/twin.provision"), `{"bundle":"./b","scope":"tag:fylgja"}`, "twin.provision with a scope")
	valid(t, apiSchema(t, "args/$defs/twin.verify"), []byte(`{}`), "twin.verify with no argument")
	// 020: detach is a flag of the four runs alone; run.read and run.interrupt take the
	// workflow always, the run when given, and nothing of a run's start; twin.diff takes its
	// two snapshots and no flag of twin step's or twin compile's.
	for _, op := range []string{"twin.create", "twin.step", "twin.destroy"} {
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"detach":"yes"}`, op+" with a detach that is not a boolean")
	}
	invalid(t, apiSchema(t, "args/$defs/twin.provision"), `{"bundle":"./b","detach":"yes"}`, "twin.provision with a detach that is not a boolean")
	for _, op := range []string{"twin.show", "twin.verify", "twin.compile"} {
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"detach":true}`, op+" with detach")
	}
	for _, op := range []string{"run.read", "run.interrupt"} {
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"workflow_id":"fylgja-step","detach":true}`, op+" with detach")
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"run_id":"01a1"}`, op+" without its workflow")
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"workflow_id":"fylgja-step","run_id":null}`, op+" with a null run")
		invalid(t, apiSchema(t, "args/$defs/"+op), `{"workflow_id":"fylgja-step","stage":"change-1/head"}`, op+" with a stage")
	}
	// A workflow no read reaches is the server's run.unknown, never the transport's 400.
	valid(t, apiSchema(t, "args/$defs/run.read"), []byte(`{"workflow_id":"fylgja-rehearse"}`), "run.read of a rehearsal")
	for _, arg := range []string{`{"snapshot":"a"}`, `{"allow_restart":true}`, `{"dry_run":true}`, `{"detach":true}`, `{"out":"out"}`, `{"from":true}`} {
		invalid(t, apiSchema(t, "args/$defs/twin.diff"), arg, "twin.diff with "+arg)
	}
	valid(t, apiSchema(t, "args/$defs/twin.diff"), []byte(`{}`), "twin.diff with no argument, which the server refuses --from is required")
}

// The request is decoded strictly: a key not known at the top or inside a file, or not
// spelled as the schema spells it, a render not known, a file that is null or has no path,
// data that is not base64, and anything after the object are refused, each in a sentence
// that begins "the request is not one: " (contracts/api.md).
func TestDecodeRequestIsStrict(t *testing.T) {
	for _, c := range []struct{ label, raw, says string }{
		{"an unknown key at the top", `{"render":"text","branch":"b"}`, `json: unknown field "branch"`},
		{"an unknown key inside files[]", `{"files":[{"path":"a.yaml","data":"","mode":420}]}`, `json: unknown field "mode"`},
		{"a render not known", `{"render":"html"}`, `render "html" is not "text", "json" or "markdown"`},
		{"a render spelled otherwise", `{"render":"Markdown"}`, `render "Markdown" is not "text", "json" or "markdown"`},
		{"a file with no path", `{"files":[{"data":""}]}`, "files[0] has no path"},
		{"a file whose data is not base64", `{"files":[{"path":"a","data":"%%%"}]}`, "illegal base64 data at input byte 0"},
		{"a second value", `{} {}`, "more follows the object"},
		{"no body", ``, "EOF"},
		{"not an object", `[]`, "json: cannot unmarshal array into Go value of type api.Request"},
		// encoding/json matches a key to its field whatever its case.
		{"a request key in capitals", `{"ARGS":{"files":["a.yaml"]},"FILES":[{"path":"a.yaml","data":""}]}`, `unknown field "ARGS"`},
		{"a request key capitalised", `{"Render":"json"}`, `unknown field "Render"`},
		{"a file's keys capitalised", `{"files":[{"path":"a","data":""},{"PATH":"b","Data":""}]}`, `unknown field "PATH" in files[1]`},
		{"a null file", `{"files":[null]}`, "files[0] is not a file"},
		{"a null file after one whose path holds a quote and a backslash", `{"files":[{"path":"a\"b\\","data":""},null]}`,
			"files[1] is not a file"},
	} {
		req, err := DecodeRequest(strings.NewReader(c.raw))
		if want := "the request is not one: " + c.says; err == nil || err.Error() != want {
			t.Errorf("%s: %s gave %+v, %v; want %q", c.label, c.raw, req, err, want)
		}
	}
	req, err := DecodeRequest(strings.NewReader(`{"args":{"stage":"","anything":{"x":1},"BRANCH":"b"}}` + "\n"))
	if err != nil {
		t.Fatal(err)
	}
	if string(req.Args["stage"]) != `""` || string(req.Args["anything"]) != `{"x":1}` || string(req.Args["BRANCH"]) != `"b"` {
		t.Errorf("args are left raw for the handler, got %v", req.Args)
	}
	// A key spelled with an escape is the key it spells.
	if req, err := DecodeRequest(strings.NewReader(`{"\u0061rgs":{"branch":"b"}}`)); err != nil || string(req.Args["branch"]) != `"b"` {
		t.Errorf(`{"\u0061rgs":…} gave %+v, %v; want args read`, req, err)
	}
}

// What the server reads as absent: render "", "args": null and "files": null, and a file
// with no data is one with no bytes (contracts/api.md, "The request is decoded
// strictly").
func TestDecodeRequestReadsNullsAsAbsent(t *testing.T) {
	req, err := DecodeRequest(strings.NewReader(`{"render":"","args":null,"files":null}`))
	if err != nil || req.Render != "" || req.Args != nil || req.Files != nil {
		t.Errorf("got %+v, %v; want a request with nothing in it", req, err)
	}
	req, err = DecodeRequest(strings.NewReader(`{"files":[{"path":"a.yaml"}]}`))
	if err != nil || len(req.Files) != 1 || req.Files[0].Path != "a.yaml" || len(req.Files[0].Data) != 0 {
		t.Errorf("got %+v, %v; want a.yaml with no bytes", req, err)
	}
}

// A sample of every frame kind is the contract's frame; a frame of two kinds is
// not.
func TestEveryFrameKindSatisfiesTheContract(t *testing.T) {
	frame := apiSchema(t, "frame")
	doc := findings.NewDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "01a1"}, nil)
	var refused findings.List
	refused.Add(findings.Rejection, findings.RuleAPIUnreachable, "127.0.0.1:7650", "the API at 127.0.0.1:7650 cannot be reached")
	refusedDoc := findings.NewDocument(findings.OpTwinShow, nil, refused)
	// 020's documents, as internal/server writes them.
	var started findings.List
	started.AddStep(findings.Info, findings.StepStart, findings.RuleRunDetached, "fylgja-provision 01a1",
		"run fylgja-provision 01a1 started; read it with fylgja run read")
	detachedDoc := findings.NewDocument(findings.OpTwinCreate, &findings.Subject{RunID: "01a1"}, started)
	readDoc := findings.NewDocument(findings.OpRunRead, &findings.Subject{RunID: "01a1"}, nil)
	var noRun findings.List
	noRun.Add(findings.Rejection, findings.RuleRunUnknown, "fylgja-step r-gone", "the workflow service holds no run fylgja-step r-gone")
	unknownDoc := findings.NewDocument(findings.OpRunRead, &findings.Subject{RunID: "r-gone"}, noRun)
	var asked findings.List
	asked.Add(findings.Info, findings.RuleRunCancelRequested, "fylgja-step 01a1",
		"cancellation of run fylgja-step 01a1 was requested; it cleans up and closes, and fylgja run read says how")
	interruptDoc := findings.NewDocument(findings.OpRunInterrupt, &findings.Subject{RunID: "01a1"}, asked)
	const snap, bundle = "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00",
		"c70589c35899378b8343abd1ebc12ab476e2f08a33a14449eb585d21cefd9672"
	diffDoc := findings.NewDocument(findings.OpTwinDiff, nil, nil)
	diffDoc.SnapshotFrom, diffDoc.SnapshotTo, diffDoc.BundleFrom, diffDoc.BundleTo = snap, snap, bundle, bundle
	diffDoc.Step = findings.DiffBlock(json.RawMessage(`{"from":"snapshot b9db37f8…","to":"snapshot b9db37f8…",` +
		`"from_bundle_id":"` + bundle + `","to_bundle_id":"` + bundle + `","computed":true,"unchanged":true,` +
		`"nodes":{"added":[],"removed":[],"changed":[]},"links":{"added":[],"removed":[]},"artifacts":{"changed":[]}}`))
	for _, c := range []struct {
		label string
		frame Frame
		kind  string
	}{
		{"out", Frame{Out: "run fylgja-provision 01a1\n"}, KindOut},
		{"err", Frame{Err: "fylgja: requesting cancellation of run fylgja-provision 01a1\n"}, KindErr},
		{"start", Frame{Start: &RunRef{WorkflowID: "fylgja-provision"}}, KindStart},
		// A destroy's start opens no stream, and it is still a start.
		{"destroy's start", Frame{Start: &RunRef{WorkflowID: "fylgja-destroy"}}, KindStart},
		{"run", Frame{Run: &RunRef{WorkflowID: "fylgja-step", RunID: "01a1"}}, KindRun},
		{"event", Frame{Event: &Event{WorkflowID: "fylgja-provision", Step: "read", FindingStep: "read"}}, KindEvent},
		{"files", Frame{Files: []File{{Path: "snapshot.json", Data: []byte("{}\n")}}}, KindFiles},
		{"document", Frame{Document: documentBytes(t, doc)}, KindDocument},
		{"document with text", Frame{Document: documentBytes(t, refusedDoc), Text: "rejection api.unreachable 127.0.0.1:7650: …\n"}, KindDocument},
		// 020: a detached answer's run, a destroy's included, and its document; run.read's
		// document, and its refusal; run.interrupt's; twin.diff's. run.read's run frame with its
		// state is below, in each state.
		{"a detached destroy's run", Frame{Run: &RunRef{WorkflowID: "fylgja-destroy", RunID: "01a1"}}, KindRun},
		{"a detached document", Frame{Document: documentBytes(t, detachedDoc),
			Text: "info run.detached [step start] fylgja-provision 01a1: …\n"}, KindDocument},
		{"run.read's document", Frame{Document: documentBytes(t, readDoc)}, KindDocument},
		{"run.read of no run", Frame{Document: documentBytes(t, unknownDoc)}, KindDocument},
		{"run.interrupt's document", Frame{Document: documentBytes(t, interruptDoc)}, KindDocument},
		{"twin.diff's document", Frame{Document: documentBytes(t, diffDoc)}, KindDocument},
	} {
		raw := mustJSON(t, c.frame)
		valid(t, frame, raw, c.label+" frame")
		if bytes.ContainsRune(raw, '\n') {
			t.Errorf("the %s frame is more than one line: %q", c.label, raw)
		}
		var back Frame
		if err := json.Unmarshal(raw, &back); err != nil {
			t.Fatal(err)
		}
		if back.Kind() != c.kind {
			t.Errorf("the %s frame decodes as kind %q", c.label, back.Kind())
		}
	}
	invalid(t, frame, `{"out":"a\n","err":"b\n"}`, "a frame of two kinds")
	invalid(t, frame, `{"start":{"workflow_id":"fylgja-follow"}}`, "a start of a workflow no request starts")
	invalid(t, frame, `{"start":{"workflow_id":"fylgja-destroy","run_id":"01a1"}}`, "a start that names its run")
	invalid(t, frame, `{"files":[]}`, "a files frame with none")
	invalid(t, frame, `{"markdown":"## …\n"}`, "markdown with no document")
	// 020: the rehearsal left the core with twin.rehearse, so no request starts it.
	invalid(t, frame, `{"start":{"workflow_id":"fylgja-rehearse"}}`, "a rehearsal's start")
	// 020: run.read's run frame names one of the six states the workflow service describes; a
	// run frame of any other operation names none, and a start, which comes before the run,
	// never one.
	for _, state := range []string{"running", "completed", "failed", "cancelled", "terminated", "timed_out"} {
		raw := mustJSON(t, Frame{Run: &RunRef{WorkflowID: "fylgja-step", RunID: "01a1", State: state}})
		valid(t, frame, raw, "run.read's run frame, "+state)
		var back Frame
		if err := json.Unmarshal(raw, &back); err != nil || back.Kind() != KindRun || back.Run.State != state {
			t.Errorf("run.read's run frame, %s, decodes as %+v (%v)", state, back.Run, err)
		}
	}
	if raw := string(mustJSON(t, Frame{Run: &RunRef{WorkflowID: "fylgja-step", RunID: "01a1"}})); strings.Contains(raw, "state") {
		t.Errorf("a run frame with no state writes %s", raw)
	}
	if StateRunning != "running" {
		t.Errorf("StateRunning is %q, the contract's running", StateRunning)
	}
	invalid(t, frame, `{"run":{"workflow_id":"fylgja-step","run_id":"01a1","state":"paused"}}`, "a run in a state no service describes")
	invalid(t, frame, `{"run":{"workflow_id":"fylgja-step","run_id":"01a1","state":"timed out"}}`, "a run's state spelled as an event's outcome")
	invalid(t, frame, `{"run":{"workflow_id":"fylgja-step","state":"running"}}`, "a run's state with no run")
	invalid(t, frame, `{"start":{"workflow_id":"fylgja-step","state":"running"}}`, "a start with a state")
	var unknown Frame
	if err := json.Unmarshal([]byte(`{"progress":{"pct":40}}`), &unknown); err != nil || unknown.Kind() != "" {
		t.Errorf("a frame of a kind this build does not know decodes as %q, %v; a client ignores it", unknown.Kind(), err)
	}
}

// The document frame's document, re-indented, is findings.WriteJSON's bytes, an escaped
// < included: the client prints --json from the frame without passing it through its own
// types.
func TestADocumentFrameReindentsToWriteJSONsBytes(t *testing.T) {
	doc := findings.ErrorDocument(findings.OpCompile, &findings.Subject{Out: "/tmp/<b>"}, "--snapshot is required & --out <dir>")
	want := documentBytes(t, doc)
	raw := mustJSON(t, Frame{Document: want})
	var back Frame
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatal(err)
	}
	var got bytes.Buffer
	if err := json.Indent(&got, back.Document, "", "  "); err != nil {
		t.Fatal(err)
	}
	got.WriteByte('\n')
	if !bytes.Equal(got.Bytes(), want) {
		t.Errorf("re-indented:\n%s\nWriteJSON:\n%s", got.Bytes(), want)
	}
}

// Each shape of event is the contract's: a step begun, ended each way, and a notice.
// A begun step writes no outcome or duration, and a notice nothing beside its run.
func TestEveryEventShapeSatisfiesTheContract(t *testing.T) {
	event := apiSchema(t, "event")
	for _, c := range []struct {
		label string
		event Event
		want  string
	}{
		{"begun", Event{WorkflowID: "fylgja-provision", Step: "readiness n1", FindingStep: "readiness"},
			`{"workflow_id":"fylgja-provision","step":"readiness n1","finding_step":"readiness","end":false}`},
		{"done", Event{WorkflowID: "fylgja-provision", Step: "compile", FindingStep: "compile", End: true, Outcome: "done", DurationS: 0.4, Detail: "bundle_id b9d5"},
			`{"workflow_id":"fylgja-provision","step":"compile","finding_step":"compile","end":true,"outcome":"done","duration_s":0.4,"detail":"bundle_id b9d5"}`},
		{"done at once", Event{Step: "record", End: true, Outcome: "done"},
			`{"step":"record","end":true,"outcome":"done","duration_s":0}`},
		{"failed", Event{Step: "push n1", FindingStep: "push", End: true, Outcome: "failed", DurationS: 1.2, Rule: "push.refused", Message: "node n1 refused"},
			`{"step":"push n1","finding_step":"push","end":true,"outcome":"failed","duration_s":1.2,"rule":"push.refused","message":"node n1 refused"}`},
		{"timed out", Event{Step: "deploy", End: true, Outcome: "timed out", DurationS: 300, Message: "activity StartToClose timeout"},
			`{"step":"deploy","end":true,"outcome":"timed out","duration_s":300,"message":"activity StartToClose timeout"}`},
		{"cancelled", Event{Step: "cleanup teardown", End: true, Outcome: "cancelled", DurationS: 2},
			`{"step":"cleanup teardown","end":true,"outcome":"cancelled","duration_s":2}`},
		{"notice", Event{WorkflowID: "fylgja-provision", Notice: "following run fylgja-provision 01a1"},
			`{"workflow_id":"fylgja-provision","notice":"following run fylgja-provision 01a1"}`},
	} {
		raw := mustJSON(t, c.event)
		if string(raw) != c.want {
			t.Errorf("%s: %s, want %s", c.label, raw, c.want)
		}
		valid(t, event, raw, c.label+" event")
		var back Event
		if err := json.Unmarshal(raw, &back); err != nil || back != c.event {
			t.Errorf("%s: decoded %+v (%v), want %+v", c.label, back, err, c.event)
		}
		valid(t, apiSchema(t, "frame"), mustJSON(t, Frame{Event: &c.event}), c.label+" event frame")
	}
	invalid(t, event, `{"notice":"x","step":"read","end":false}`, "a notice with a step")
}

// A transport fault's body is the contract's problem, with limit_bytes on 413 alone.
func TestProblemBodiesSatisfyTheContract(t *testing.T) {
	problem := apiSchema(t, "problem")
	for _, p := range []Problem{
		{Message: "the API's token is missing or wrong"},
		{Message: "the request is larger than this server's transfer bound of 33554432 bytes (32 MiB); nothing was read or filed", LimitBytes: MaxRequestBytes},
	} {
		valid(t, problem, mustJSON(t, p), "problem "+p.Message)
	}
	if got := string(mustJSON(t, Problem{Message: "m"})); got != `{"message":"m"}` {
		t.Errorf("a problem with no bound writes %s", got)
	}
}

// A file with no bytes is "" on the wire, never null, and comes back as no bytes.
func TestAnEmptyFileIsAnEmptyString(t *testing.T) {
	raw := mustJSON(t, File{Path: "empty"})
	if string(raw) != `{"path":"empty","data":""}` {
		t.Errorf("an empty file is %s", raw)
	}
	valid(t, apiSchema(t, "file"), raw, "an empty file")
	sent, err := EncodeRequest(Request{Files: []File{{Path: "empty"}, {Path: "none", Data: []byte{}}}})
	if err != nil {
		t.Fatal(err)
	}
	if want := `{"files":[{"path":"empty","data":""},{"path":"none","data":""}]}`; string(sent) != want {
		t.Errorf("the client sends %s, want %s", sent, want)
	}
}

// The client's body is json.Marshal's bytes, though it encodes each file once: HTML
// characters escaped in a path and in an argument, an argument compacted, a file's bytes
// whatever they are, and no files written when there are none.
func TestEncodeRequestIsJSONMarshalsBytes(t *testing.T) {
	binary := make([]byte, 3<<20+1)
	for i := range binary {
		binary[i] = byte(i * 7)
	}
	for _, req := range []Request{
		{},
		{Render: RenderText, Files: []File{}},
		{Args: map[string]json.RawMessage{"out": json.RawMessage(`"a<b>&c"`), "files": json.RawMessage("[ \"x\",\n \"y\" ]")}},
		{Render: RenderJSON, Files: []File{{Path: "configs/<n1>&.cli", Data: []byte("<set>& \n")}, {Path: "é/nil"}, {Path: "big", Data: binary}}},
	} {
		got, err := EncodeRequest(req)
		if err != nil {
			t.Fatal(err)
		}
		want := mustJSON(t, req)
		if !bytes.Equal(got, want) {
			n := min(len(got), len(want), 200)
			t.Errorf("the client sends %d bytes beginning %s, json.Marshal writes %d beginning %s", len(got), got[:n], len(want), want[:n])
		}
	}
}
