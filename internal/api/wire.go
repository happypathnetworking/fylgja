// Package api is the API's wire, version 1: what crosses between a client and fylgja serve
// beside the findings documents Fylgja already versions. It holds the version, the
// operations' paths, the headers, the request, the frames of an answer, the event, the
// problem body of a transport fault and the bounds (contracts/api.md, api.schema.json).
//
// It is shared by the server and the client, and imports the standard library and
// internal/findings alone, so a client that imports it links none of the core (D-040).
package api

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"slices"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Version is the API's version, the first element of every path (/v1/…). It is kept by a
// new operation, a new optional argument, a new frame kind and a new block of the
// document, and moves only when an existing client would misread an answer.
const Version = "1"

// The headers.
const (
	// HeaderVersion is on every answer to a request that carried the token: Version.
	HeaderVersion = "Fylgja-Api-Version"
	// HeaderVersions is on the 404 for a path under no version served: the versions the
	// server serves, comma-separated.
	HeaderVersions = "Fylgja-Api-Versions"
	// HeaderBuild is on every answer to a request that carried the token: the server's
	// --version, which a client compares with its own.
	HeaderBuild = "Fylgja-Build"
	// HeaderStream is on a run's request: the client's name for its answer, which the
	// interrupt names.
	HeaderStream = "Fylgja-Stream"
)

// The variables a client reads, and the token's, which the server reads too.
const (
	EnvAddress = "FYLGJA_API_ADDRESS"
	EnvToken   = "FYLGJA_API_TOKEN"
)

// Mechanism constants, none a platform's budget (Constitution II).
const (
	// DefaultAddress is where the server listens and a client looks, unless told.
	DefaultAddress = "127.0.0.1:7650"
	// MaxRequestBytes bounds a request body; the server refuses one over it, 413, before
	// anything is decoded or filed.
	MaxRequestBytes = 32 << 20
	// MaxFrameBytes bounds one frame of an answer a client will read; it stops reading a
	// longer one and writes nothing from that answer.
	MaxFrameBytes = 64 << 20
	// DialTimeout bounds the client's connection to the server.
	DialTimeout = 5 * time.Second
	// HeaderTimeout bounds the wait from a request sent to its answer's headers, which the
	// server sends before it works.
	HeaderTimeout = 30 * time.Second
	// ExpectContinueTimeout bounds how long a request that carries files waits for the
	// server's 100 Continue, or its refusal, before it sends its body: within it a 401 arrives
	// before any of the body is sent (contracts/api.md, "The token").
	ExpectContinueTimeout = time.Second
	// MaxProblemBytes bounds what a client reads of a transport fault's body, a
	// problem:
	// the rest is not read, and a cut body words the fault by its status alone.
	MaxProblemBytes = 64 << 10
	// StreamBytes are the random bytes of a stream identity, which a client writes in hex
	// as its Fylgja-Stream.
	StreamBytes = 16
	// MaxStreamLength bounds a Fylgja-Stream value the server takes, in characters, so the
	// interrupt's path can name it; a longer one is 400.
	MaxStreamLength = 128
)

// Operations are the twelve, named as the findings document names them. Each is POST
// Path(op). There is no other: no health check, no listing of
// runs, no fetch of a bundle.
var Operations = []string{
	findings.OpTwinCreate,
	findings.OpTwinProvision,
	findings.OpTwinStep,
	findings.OpTwinDestroy,
	findings.OpTwinShow,
	findings.OpTwinVerify,
	findings.OpCompile,
	findings.OpWaypointList,
	findings.OpWaypointPlan,
	findings.OpIntentRead,
	findings.OpSchemaCheck,
	findings.OpPSPValidate,
}

// Path is an operation's path: its noun and its verb under the version,
// /v1/twin/create for twin.create.
func Path(op string) string {
	return "/v" + Version + "/" + strings.ReplaceAll(op, ".", "/")
}

// InterruptPath is the call that delivers the operator's interrupt to the answer stream
// names.
func InterruptPath(stream string) string {
	return "/v" + Version + "/streams/" + stream + "/interrupt"
}

// The renderings a request may ask for beside the document. Absent asks for none.
const (
	RenderText = "text" // what the command printed without --json at M12
	RenderJSON = "json" // what it wrote to stderr under --json
)

// Request is one operation's body.
type Request struct {
	// Render is RenderText, RenderJSON or "".
	Render string `json:"render,omitempty"`
	// Args are the command's arguments as given: an absent key is a flag not given, and a
	// present one a flag given, whatever its value. Each handler decodes them strictly.
	Args map[string]json.RawMessage `json:"args,omitempty"`
	// Files are the operator's files, on twin.compile, twin.provision and psp.validate.
	Files []File `json:"files,omitempty"`
}

// File is one file crossing whole: the path the operator gave, or its path inside the
// bundle, and its bytes, base64 on the wire.
type File struct {
	Path string `json:"path"`
	Data []byte `json:"data"`
}

// MarshalJSON writes no bytes as "" rather than null: the contract's data is a string.
func (f File) MarshalJSON() ([]byte, error) {
	type plain File
	if f.Data == nil {
		f.Data = []byte{}
	}
	return json.Marshal(plain(f))
}

// EncodeRequest is req's body as the client sends it: json.Marshal's bytes, written once
// into a slice of their exact length. json.Marshal would compact again what File's
// MarshalJSON returns, a second pass over every byte of an upload and 37% of a 32 MiB
// request's CPU, then grow its buffer and copy the whole out of it.
// Here the render and the arguments are json.Marshal's, each path is json.Marshal's, and
// each file's bytes are base64-encoded straight into the body, a file with no bytes as "",
// as MarshalJSON writes it.
func EncodeRequest(req Request) ([]byte, error) {
	head, err := json.Marshal(struct {
		Render string                     `json:"render,omitempty"`
		Args   map[string]json.RawMessage `json:"args,omitempty"`
	}{req.Render, req.Args})
	if err != nil || len(req.Files) == 0 {
		return head, err
	}
	paths := make([][]byte, len(req.Files))
	size := len(head) + len(`,"files":[]`)
	for i, f := range req.Files {
		if paths[i], err = json.Marshal(f.Path); err != nil {
			return nil, err
		}
		size += len(`{"path":,"data":""},`) + len(paths[i]) + base64.StdEncoding.EncodedLen(len(f.Data))
	}
	body := append(make([]byte, 0, size), head[:len(head)-1]...)
	if len(head) > len("{}") {
		body = append(body, ',')
	}
	body = append(body, `"files":[`...)
	for i, f := range req.Files {
		if i > 0 {
			body = append(body, ',')
		}
		body = append(append(append(body, `{"path":`...), paths[i]...), `,"data":"`...)
		body = append(base64.StdEncoding.AppendEncode(body, f.Data), `"}`...)
	}
	return append(body, "]}"...), nil
}

// DecodeRequest reads a request strictly: a key it does not know, at any depth, or one not
// spelled as the schema spells it, a render it does not know, a file that is null or has no
// path, or anything after the object is an error, which the server answers 400.
// Args' values are left to each handler, which decodes them strictly against its own
// arguments.
func DecodeRequest(r io.Reader) (Request, error) {
	// The body is kept as the decoder reads it, for the spelling's walk after it.
	var body bytes.Buffer
	dec := json.NewDecoder(io.TeeReader(r, &body))
	dec.DisallowUnknownFields()
	var req Request
	if err := dec.Decode(&req); err != nil {
		return Request{}, fmt.Errorf("the request is not one: %w", err)
	}
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return Request{}, errors.New("the request is not one: more follows the object")
	}
	if err := spelledAsTheSchema(body.Bytes()); err != nil {
		return Request{}, fmt.Errorf("the request is not one: %w", err)
	}
	switch req.Render {
	case "", RenderText, RenderJSON:
	default:
		return Request{}, fmt.Errorf("the request is not one: render %q is neither %q nor %q", req.Render, RenderText, RenderJSON)
	}
	for i, f := range req.Files {
		if f.Path == "" {
			return Request{}, fmt.Errorf("the request is not one: files[%d] has no path", i)
		}
	}
	return req, nil
}

// The keys a request's objects take, spelled as api.schema.json spells them.
var (
	requestKeys = []string{"render", "args", "files"}
	fileKeys    = []string{"path", "data"}
)

// spelledAsTheSchema walks a request the decoder has read whole, so body is one valid JSON
// value, and refuses a key of the request or of a file that is not spelled as the schema
// spells it, and a file that is null. encoding/json matches a key to its field whatever its
// case, so "ARGS" was read as args, and reads a null file as one with no path. The keys
// inside args are the arguments' names, which each handler holds to its own,
// and their values are its to read. Strings are passed over by their closing quote, so a
// file's data costs one search.
func spelledAsTheSchema(body []byte) error {
	w := &walk{b: body}
	w.space()
	if w.peek() != '{' {
		return nil // null, which reads as no request at all
	}
	return w.object(func(key string) error {
		if !slices.Contains(requestKeys, key) {
			return fmt.Errorf("unknown field %q", key)
		}
		if key != "files" || w.peek() != '[' {
			w.value()
			return nil
		}
		return w.array(func(i int) error {
			if w.peek() != '{' {
				w.value()
				return fmt.Errorf("files[%d] is not a file", i)
			}
			return w.object(func(key string) error {
				if !slices.Contains(fileKeys, key) {
					return fmt.Errorf("unknown field %q in files[%d]", key, i)
				}
				w.value()
				return nil
			})
		})
	})
}

// walk is a position in a JSON value already known to be valid.
type walk struct {
	b []byte
	i int
}

func (w *walk) space() {
	for w.i < len(w.b) && (w.b[w.i] == ' ' || w.b[w.i] == '\t' || w.b[w.i] == '\n' || w.b[w.i] == '\r') {
		w.i++
	}
}

func (w *walk) peek() byte {
	w.space()
	if w.i < len(w.b) {
		return w.b[w.i]
	}
	return 0
}

// object calls each with each key, positioned at its value, which each must pass over.
func (w *walk) object(each func(key string) error) error {
	w.i++ // {
	for w.peek() != '}' {
		key := w.string()
		w.peek()
		w.i++ // :
		w.space()
		if err := each(key); err != nil {
			return err
		}
		if w.peek() == ',' {
			w.i++
		}
	}
	w.i++
	return nil
}

// array calls each with each element's index, positioned at the element, which each must
// pass over.
func (w *walk) array(each func(i int) error) error {
	w.i++ // [
	for n := 0; w.peek() != ']'; n++ {
		if err := each(n); err != nil {
			return err
		}
		if w.peek() == ',' {
			w.i++
		}
	}
	w.i++
	return nil
}

// string passes over a string and returns it, unquoted when it carries an escape.
func (w *walk) string() string {
	start := w.i
	w.skipString()
	raw := w.b[start+1 : w.i-1]
	if !bytes.Contains(raw, []byte{'\\'}) {
		return string(raw)
	}
	var s string
	_ = json.Unmarshal(w.b[start:w.i], &s)
	return s
}

// skipString passes over the string at w.i: to the first quote after it that no odd run of
// backslashes escapes.
func (w *walk) skipString() {
	w.i++ // "
	for {
		j := bytes.IndexByte(w.b[w.i:], '"')
		if j < 0 {
			w.i = len(w.b)
			return
		}
		end := w.i + j
		escapes := 0
		for k := end - 1; k >= w.i && w.b[k] == '\\'; k-- {
			escapes++
		}
		w.i = end + 1
		if escapes%2 == 0 {
			return
		}
	}
}

// value passes over the value at w.i, whatever it is.
func (w *walk) value() {
	switch w.peek() {
	case '"':
		w.skipString()
	case '{', '[':
		depth := 0
		for w.i < len(w.b) {
			switch w.b[w.i] {
			case '"':
				w.skipString()
				continue
			case '{', '[':
				depth++
			case '}', ']':
				depth--
			}
			w.i++
			if depth == 0 {
				return
			}
		}
	default:
		for w.i < len(w.b) && !strings.ContainsRune(",}] \t\n\r", rune(w.b[w.i])) {
			w.i++
		}
	}
}

// Frame is one line of an answer: exactly one kind, which is its key. A frame of a
// kind this build does not know decodes to no kind, and a client ignores it.
type Frame struct {
	// Out is text for stdout, whole lines, under RenderText alone.
	Out string `json:"out,omitempty"`
	// Err is text for stderr, whole lines, under either rendering.
	Err string `json:"err,omitempty"`
	// Start says the server begins to start this run; from here an interrupt reaches it.
	// It carries the workflow id alone.
	Start *RunRef `json:"start,omitempty"`
	// Run is the run's identity, once it is started.
	Run *RunRef `json:"run,omitempty"`
	// Event is one step boundary of a run, or one notice about a run.
	Event *Event `json:"event,omitempty"`
	// Files are the CTM (intent.read's ctm.json) or every file of a compiled bundle.
	Files []File `json:"files,omitempty"`
	// Document is the findings document, always the last frame; Text, beside it under
	// RenderText, is its findings as text.
	Document json.RawMessage `json:"document,omitempty"`
	Text     string          `json:"text,omitempty"`
}

// The frames' kinds, as Frame.Kind names them.
const (
	KindOut      = "out"
	KindErr      = "err"
	KindStart    = "start"
	KindRun      = "run"
	KindEvent    = "event"
	KindFiles    = "files"
	KindDocument = "document"
)

// Kind is the frame's kind, or "" for one this build does not know.
func (f Frame) Kind() string {
	switch {
	case len(f.Document) > 0:
		return KindDocument
	case f.Out != "":
		return KindOut
	case f.Err != "":
		return KindErr
	case f.Start != nil:
		return KindStart
	case f.Run != nil:
		return KindRun
	case f.Event != nil:
		return KindEvent
	case f.Files != nil:
		return KindFiles
	}
	return ""
}

// RunRef is a run's identity. A start frame carries the workflow id alone, since the run
// has none yet.
type RunRef struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id,omitempty"`
}

// Event is M2's progress event as JSON: one step boundary of a run, or one notice
// about a run, read from the run's history.
type Event struct {
	WorkflowID  string  `json:"workflow_id,omitempty"`
	Step        string  `json:"step,omitempty"`
	FindingStep string  `json:"finding_step,omitempty"`
	End         bool    `json:"end"`
	Outcome     string  `json:"outcome,omitempty"`
	DurationS   float64 `json:"duration_s"`
	Detail      string  `json:"detail,omitempty"`
	Rule        string  `json:"rule,omitempty"`
	Message     string  `json:"message,omitempty"`
	// Notice is a line about a run rather than a step; an event that carries one carries
	// nothing else but the workflow id.
	Notice string `json:"notice,omitempty"`
}

// MarshalJSON writes a notice with its workflow id alone, and a step boundary with end
// always, and its outcome and duration on an end alone.
func (e Event) MarshalJSON() ([]byte, error) {
	if e.Notice != "" {
		return json.Marshal(struct {
			WorkflowID string `json:"workflow_id,omitempty"`
			Notice     string `json:"notice"`
		}{e.WorkflowID, e.Notice})
	}
	type boundary struct {
		WorkflowID  string   `json:"workflow_id,omitempty"`
		Step        string   `json:"step"`
		FindingStep string   `json:"finding_step,omitempty"`
		End         bool     `json:"end"`
		Outcome     string   `json:"outcome,omitempty"`
		DurationS   *float64 `json:"duration_s,omitempty"`
		Detail      string   `json:"detail,omitempty"`
		Rule        string   `json:"rule,omitempty"`
		Message     string   `json:"message,omitempty"`
	}
	b := boundary{WorkflowID: e.WorkflowID, Step: e.Step, FindingStep: e.FindingStep, End: e.End,
		Detail: e.Detail, Rule: e.Rule, Message: e.Message}
	if e.End {
		d := e.DurationS
		b.Outcome, b.DurationS = e.Outcome, &d
	}
	return json.Marshal(b)
}

// Problem is the body of a transport fault: 401, 404, 413, 400 or 409, the status saying
// which. Its message names no token.
type Problem struct {
	Message string `json:"message"`
	// LimitBytes is the transfer bound, on 413 alone.
	LimitBytes int64 `json:"limit_bytes,omitempty"`
}
