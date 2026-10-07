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
		"waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
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
	s, err := c.Compile("https://fylgja.dev/schemas/api.schema.json#/$defs/" + def)
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

// The twelve operations are the newest findings contract's, every one there is, and each
// is POST /v1/<noun>/<verb>.
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
	got, want := slices.Sorted(slices.Values(Operations)), slices.Sorted(slices.Values(schema.Properties.Operation.Enum))
	if !slices.Equal(got, want) {
		t.Errorf("Operations = %v, the contract's enum %v", got, want)
	}
	for op, path := range map[string]string{
		"twin.create": "/v1/twin/create", "twin.provision": "/v1/twin/provision", "twin.step": "/v1/twin/step",
		"twin.destroy": "/v1/twin/destroy", "twin.show": "/v1/twin/show", "twin.verify": "/v1/twin/verify",
		"twin.compile": "/v1/twin/compile", "waypoint.list": "/v1/waypoint/list", "waypoint.plan": "/v1/waypoint/plan",
		"intent.read": "/v1/intent/read", "schema.check": "/v1/schema/check", "psp.validate": "/v1/psp/validate",
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
		{"twin.create", map[string]json.RawMessage{"branch": str("fylgja-fixture"), "at": str("2026-09-14T12:00:00Z"),
			"waypoint": str("demo/2"), "interval": str(""), "no_follow": yes, "dry_run": yes}, nil},
		{"twin.provision", map[string]json.RawMessage{"bundle": str("./b9d53ebc"), "dry_run": yes},
			[]File{{Path: "manifest.json", Data: []byte("{}\n")}, {Path: "configs/n1.cli", Data: []byte("set / system name host-name n1\n")}}},
		{"twin.step", map[string]json.RawMessage{"waypoint": str("demo/3"), "allow_restart": yes, "dry_run": yes, "wait": str("20s")}, nil},
		{"twin.destroy", nil, nil},
		{"twin.show", nil, nil},
		{"twin.verify", map[string]json.RawMessage{"wait": str("2m0s"), "args": mustJSON(t, []string{"30s"})}, nil},
		{"twin.compile", map[string]json.RawMessage{"ctm": str("ctm.json"), "out": str("out")},
			[]File{{Path: "ctm.json", Data: []byte(`{"ctm_version":"1"}`)}}},
		{"waypoint.list", map[string]json.RawMessage{"series": str("")}, nil},
		{"waypoint.plan", map[string]json.RawMessage{"series": str("demo")}, nil},
		{"intent.read", map[string]json.RawMessage{"branch": str("b"), "at": str("2026-09-14T12:00:00Z"), "waypoint": str("demo/1"), "out": str("ctm.json")}, nil},
		{"schema.check", map[string]json.RawMessage{"branch": str("fylgja-fixture")}, nil},
		{"psp.validate", map[string]json.RawMessage{"files": mustJSON(t, []string{"a.yaml", "b.yaml"})},
			[]File{{Path: "a.yaml", Data: []byte("psp_version: \"0.6\"\n")}, {Path: "b.yaml", Data: nil}}},
	} {
		t.Run(c.op, func(t *testing.T) {
			for _, render := range []string{"", RenderText, RenderJSON} {
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
	invalid(t, apiSchema(t, "args/$defs/twin.provision"), `{"dry_run":true}`, "twin.provision without a bundle")
	invalid(t, apiSchema(t, "args/$defs/twin.verify"), `{"args":["30s"]}`, "twin.verify's args without wait")
	valid(t, apiSchema(t, "args/$defs/twin.verify"), []byte(`{}`), "twin.verify with no argument")
}

// The request is decoded strictly: a key not known at the top or inside a file, or not
// spelled as the schema spells it, a render not known, a file that is null or has no path,
// data that is not base64, and anything after the object are refused, each in a sentence
// that begins "the request is not one: " (contracts/api.md).
func TestDecodeRequestIsStrict(t *testing.T) {
	for _, c := range []struct{ label, raw, says string }{
		{"an unknown key at the top", `{"render":"text","branch":"b"}`, `json: unknown field "branch"`},
		{"an unknown key inside files[]", `{"files":[{"path":"a.yaml","data":"","mode":420}]}`, `json: unknown field "mode"`},
		{"a render not known", `{"render":"html"}`, `render "html" is neither "text" nor "json"`},
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
	req, err := DecodeRequest(strings.NewReader(`{"args":{"interval":"","anything":{"x":1},"BRANCH":"b"}}` + "\n"))
	if err != nil {
		t.Fatal(err)
	}
	if string(req.Args["interval"]) != `""` || string(req.Args["anything"]) != `{"x":1}` || string(req.Args["BRANCH"]) != `"b"` {
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
		{"files", Frame{Files: []File{{Path: "ctm.json", Data: []byte("{}\n")}}}, KindFiles},
		{"document", Frame{Document: documentBytes(t, doc)}, KindDocument},
		{"document with text", Frame{Document: documentBytes(t, refusedDoc), Text: "rejection api.unreachable 127.0.0.1:7650: …\n"}, KindDocument},
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
	var unknown Frame
	if err := json.Unmarshal([]byte(`{"progress":{"pct":40}}`), &unknown); err != nil || unknown.Kind() != "" {
		t.Errorf("a frame of a kind this build does not know decodes as %q, %v; a client ignores it", unknown.Kind(), err)
	}
}

// The document frame's document, re-indented, is findings.WriteJSON's bytes, an escaped
// < included: the client prints --json from the frame without passing it through its own
// types.
func TestADocumentFrameReindentsToWriteJSONsBytes(t *testing.T) {
	doc := findings.ErrorDocument(findings.OpCompile, &findings.Subject{Out: "/tmp/<b>"}, "--ctm is required & --out <dir>")
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
