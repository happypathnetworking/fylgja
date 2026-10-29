package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// fakeKind is FylgjaProbe on the default branch, as a ProbeReader answers for it: check is
// Check's answer, probes and err Probes'. checks and reads count the calls.
type fakeKind struct {
	check         error
	probes        []probe.Probe
	err           error
	checks, reads int
}

func (k *fakeKind) Check(context.Context) error {
	k.checks++
	return k.check
}

func (k *fakeKind) Probes(context.Context) ([]probe.Probe, error) {
	k.reads++
	return k.probes, k.err
}

// kindOptions are the options of a request to a server whose kind's read is kind, under
// render json.
func kindOptions(t *testing.T, kind *fakeKind) *options {
	t.Helper()
	s := New("")
	s.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	s.Probes = func() (ProbeReader, error) { return kind, nil }
	return s.newCall(context.Background(), "test", api.Request{Render: api.RenderJSON}, newFrames(processStreams{}, nil), nil).options()
}

// probeFile is a declaration under testdata/probes/, as --probes sends it.
func probeFile(t *testing.T, name string) probesArg {
	t.Helper()
	path := repoPath("testdata", "probes", name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return probesArg{given: true, path: path, file: &api.File{Path: path, Data: data}}
}

// declared is the probes of a declaration under testdata/probes/.
func declared(t *testing.T, name string) []probe.Probe {
	t.Helper()
	pa := probeFile(t, name)
	d, list := probe.Parse(pa.file.Data, pa.path)
	if d == nil {
		t.Fatalf("%s: %+v", name, list)
	}
	return d.Probes
}

// The request's one list (FR-005): the file when one is sent, replacing the kind's, which is
// then never asked; else the kind's; else, the kind holding none, [] with no warning.
func TestReadProbesTakesTheFileElseTheKind(t *testing.T) {
	ctx := context.Background()
	n1, n2 := declared(t, "n1-loop.json"), declared(t, "n2-loop.json")

	kind := &fakeKind{probes: n2}
	got, err := readProbes(ctx, kindOptions(t, kind), findings.OpIntentRead, nil, probeFile(t, "n1-loop.json"))
	if err != nil || !reflect.DeepEqual(got, n1) {
		t.Errorf("with a file: %+v, %v; want the file's %+v", got, err, n1)
	}
	if kind.checks+kind.reads != 0 {
		t.Errorf("with a file the kind was asked %d times; want none", kind.checks+kind.reads)
	}

	got, err = readProbes(ctx, kindOptions(t, kind), findings.OpIntentRead, nil, probesArg{})
	if err != nil || !reflect.DeepEqual(got, n2) || kind.checks != 1 || kind.reads != 1 {
		t.Errorf("with no file: %+v, %v after %d checks and %d reads; want the kind's %+v, once", got, err, kind.checks,
			kind.reads, n2)
	}

	for _, empty := range [][]probe.Probe{nil, {}} {
		got, err = readProbes(ctx, kindOptions(t, &fakeKind{probes: empty}), findings.OpIntentRead, nil, probesArg{})
		if err != nil || got == nil || len(got) != 0 {
			t.Errorf("with neither (the kind answering %#v): %#v, %v; want [], no finding", empty, got, err)
		}
	}
}

// A malformed file is refused at start under its own rule, naming the file, the probe and the
// field; a format no probe package declares is refused there too, with the registry's
// formats; and the kind is never asked.
func TestReadProbesRefusesAMalformedFileAtStart(t *testing.T) {
	for _, c := range []struct {
		file, rule, object string
	}{
		{"probes.version.unsupported.json", findings.RuleProbesVersionUnsupported, ""},
		{"probe.address.invalid.json", findings.RuleProbeAddressInvalid, "n1-loop/b.address"},
		{"probe.gateway.outside.json", findings.RuleProbeGatewayOutside, ".gateway"},
		{"probe.format.unknown.json", findings.RuleProbeFormatUnknown, "n1-loop"},
	} {
		t.Run(c.file, func(t *testing.T) {
			kind := &fakeKind{}
			pa := probeFile(t, "invalid/"+c.file)
			_, err := readProbes(context.Background(), kindOptions(t, kind), findings.OpTwinCreate, &findings.Subject{Branch: "b"}, pa)
			code, doc := exitOf(t, err)
			if code != findings.ExitRejected || len(doc.Findings) == 0 {
				t.Fatalf("exit %d, findings %+v; want a rejection", code, doc.Findings)
			}
			f := doc.Findings[0]
			if f.Rule != c.rule || f.Step != findings.StepStart || !strings.Contains(f.Object, c.object) {
				t.Errorf("finding %+v; want %s at start, its object holding %q", f, c.rule, c.object)
			}
			if f.Object != pa.path && !strings.Contains(f.Message, pa.path) {
				t.Errorf("finding %+v names neither in its object nor its message the file %s", f, pa.path)
			}
			if kind.checks+kind.reads != 0 {
				t.Errorf("the kind was asked beside a file")
			}
			validateWithShow(t, currentContract, "016", doc)
		})
	}
}

// The kind absent from the default branch is probe.kind.absent at resolve, naming the
// schema file, when the read is asked for; an Infrahub that cannot be asked is
// operation.failed there; a probe the kind holds that the declaration's rules refuse is
// refused at resolve, naming the kind.
func TestReadProbesFromTheKindRefuses(t *testing.T) {
	bad := declared(t, "n1-loop.json")
	bad[0].Endpoints[0].Address = "10.1.10.2"
	for _, c := range []struct {
		name string
		kind *fakeKind
		rule string
		code int
	}{
		{"absent", &fakeKind{check: &intent.ProbeKindError{}}, findings.RuleProbeKindAbsent, findings.ExitRejected},
		{"an attribute missing", &fakeKind{check: &intent.ProbeKindError{Missing: []string{"a_gateway"}}},
			findings.RuleProbeKindAbsent, findings.ExitRejected},
		{"unreachable", &fakeKind{check: errors.New("connection refused")}, findings.RuleOperationFailed, findings.ExitError},
		{"the list unreadable", &fakeKind{err: errors.New("connection refused")}, findings.RuleOperationFailed, findings.ExitError},
		{"a probe refused", &fakeKind{probes: bad}, findings.RuleProbeAddressInvalid, findings.ExitRejected},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, err := readProbes(context.Background(), kindOptions(t, c.kind), findings.OpStagePlan, nil, probesArg{})
			code, doc := exitOf(t, err)
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want exit %d and one finding", code, doc.Findings, c.code)
			}
			f := doc.Findings[0]
			if f.Rule != c.rule || f.Step != findings.StepResolve {
				t.Errorf("finding %+v; want %s at resolve", f, c.rule)
			}
			if c.rule == findings.RuleProbeKindAbsent && (f.Object != intent.ProbeKind ||
				!strings.Contains(f.Message, intent.ProbeSchemaFile)) {
				t.Errorf("finding %+v; want it at %s, naming %s", f, intent.ProbeKind, intent.ProbeSchemaFile)
			}
			if c.rule == findings.RuleProbeAddressInvalid && !strings.Contains(f.Message, intent.ProbeKind) {
				t.Errorf("finding %+v does not name the kind", f)
			}
		})
	}
}

// intent read's snapshot carries the request's list (FR-005): the file's, the kind's, or
// none, the snapshot sent and the one filed alike.
func TestIntentReadTakesTheRequestsList(t *testing.T) {
	n1 := declared(t, "n1-loop.json")
	for _, c := range []struct {
		name   string
		probes []probe.Probe
	}{{"a list", n1}, {"none", []probe.Probe{}}} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			var rec recordedFrames
			opts := helperServer.newCall(context.Background(), "test", api.Request{Render: api.RenderText},
				newFrames(&rec, nil), nil).options()
			reads := 0
			subject := &findings.Subject{Branch: "fylgja-fixture", Out: "snap.json"}
			err := read(context.Background(), opts, subject, fakeRead(t, "three-node.json", nil, &reads), "fylgja-fixture", "",
				"tag:fylgja", "snap.json", shippedPackages(t), "2026-10-29T09:00:00.000000Z", nil, c.probes)
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v", code, doc.Findings)
			}
			sent := rec.files()
			if len(sent) != 1 || len(sent[0]) != 1 {
				t.Fatalf("files frames %+v; want one snapshot", sent)
			}
			s, err := snapshot.Unmarshal(sent[0][0].Data)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(s.Probes, c.probes) {
				t.Errorf("the snapshot sent carries %+v; want %+v", s.Probes, c.probes)
			}
			if !strings.Contains(string(sent[0][0].Data), `"snapshot_version": "2"`) {
				t.Errorf("the snapshot sent is not a 2:\n%s", sent[0][0].Data)
			}
			stored, err := snapshot.NewDirStore(paths.Snapshots).Fetch(context.Background(), s.ID)
			if err != nil || !reflect.DeepEqual(stored.Probes, c.probes) {
				t.Errorf("the snapshot filed carries %+v (%v); want %+v", stored, err, c.probes)
			}
		})
	}
}

// A create's take carries the request's list, and its compile places it: the snapshot filed
// names the probe, and the bundle its two hosts (FR-005).
func TestCreateTakesTheRequestsList(t *testing.T) {
	paths := useStateRoot(t)
	n1 := declared(t, "n1-loop.json")
	probed := probedCTM(t)
	read := func(context.Context, string, string, string, *psp.Registry, string) (*ctm.CTM, findings.List, error) {
		return probed, nil, nil
	}
	cr, err := readTakeCompile(context.Background(), testOptions(t, true), findings.OpTwinCreate, &findings.Subject{Branch: "b"},
		read, "b", "", "tag:fylgja", shippedPackages(t), n1)
	if err != nil {
		_, doc := exitOf(t, err)
		t.Fatalf("findings %+v", doc.Findings)
	}
	stored, err := snapshot.NewDirStore(paths.Snapshots).Fetch(context.Background(), cr.snapshot.id)
	if err != nil || !reflect.DeepEqual(stored.Probes, n1) {
		t.Errorf("the snapshot filed carries %+v (%v); want %+v", stored, err, n1)
	}
	var m struct {
		Probes []struct {
			Name string `json:"name"`
		} `json:"probes"`
	}
	if err := json.Unmarshal(cr.files["manifest.json"], &m); err != nil || len(m.Probes) != 1 || m.Probes[0].Name != "n1-loop" {
		t.Errorf("the bundle's manifest names probes %+v (%v); want n1-loop", m.Probes, err)
	}
}

// probedCTM is the CTM of testdata/snapshot/three-node-probed.json: the three-node fixture
// with ethernet-1/10 and ethernet-1/11 uncabled on each device.
func probedCTM(t *testing.T) *ctm.CTM {
	t.Helper()
	b, err := os.ReadFile(repoPath("testdata", "snapshot", "three-node-probed.json"))
	if err != nil {
		t.Fatal(err)
	}
	s, err := snapshot.Unmarshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return s.CTM
}

// The stages' pipeline on the server hands every take the one list it was built with, so
// every stage of a plan, a rehearsal or a step files a snapshot carrying it (FR-007).
func TestStagePipelineTakesCarryTheOneList(t *testing.T) {
	paths := useStateRoot(t)
	n1 := declared(t, "n1-loop.json")
	p := stagePipeline(paths, n1, nil)
	store := snapshot.NewDirStore(paths.Snapshots)
	for _, observed := range []string{"2026-10-29T09:00:00.000000Z", "2026-10-29T09:01:00.000000Z"} {
		c := probedCTM(t)
		c.Envelope.ObservedAt = observed
		id, list, err := p.Take(context.Background(), c, p.Probes)
		if err != nil || list.Rejected() {
			t.Fatalf("take: %v %+v", err, list)
		}
		s, err := store.Fetch(context.Background(), id)
		if err != nil || !reflect.DeepEqual(s.Probes, n1) {
			t.Errorf("stage snapshot %s carries %+v (%v); want %+v", id, s, err, n1)
		}
	}
	if !reflect.DeepEqual(p.Probes, n1) {
		t.Errorf("the pipeline's list is %+v; want %+v", p.Probes, n1)
	}
}

// --probes beside --snapshot is snapshot.flags.conflict at --probes, at start, on a create
// and a step, after the flags a snapshot already refused; nothing is read, and the kind is
// never asked (FR-006).
func TestProbesBesideASnapshotIsTheConflict(t *testing.T) {
	useStateRoot(t)
	kind := &fakeKind{}
	opts := kindOptions(t, kind)
	id := strings.Repeat("a", 64)
	pa := probesArg{given: true, path: "p.json"}

	for _, c := range []struct {
		name string
		run  func() error
		flag string
	}{
		{"create", func() error {
			return runCreate(context.Background(), opts, &createFlags{snapshot: id, snapshotGiven: true, probes: pa}, nil)
		}, "--probes"},
		{"create beside --scope", func() error {
			return runCreate(context.Background(), opts, &createFlags{snapshot: id, snapshotGiven: true, scope: "tag:x",
				scopeGiven: true, probes: pa}, nil)
		}, "--scope"},
		{"step", func() error {
			return runTwinStep(context.Background(), opts, &stepFlags{snapshot: id, snapshotGiven: true, probes: pa}, nil)
		}, "--probes"},
		{"step beside --stage", func() error {
			return runTwinStep(context.Background(), opts, &stepFlags{snapshot: id, snapshotGiven: true, stage: "b/l",
				stageGiven: true, probes: pa}, nil)
		}, "--stage"},
	} {
		t.Run(c.name, func(t *testing.T) {
			code, doc := exitOf(t, c.run())
			if code != findings.ExitError || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want exit 2 and one finding", code, doc.Findings)
			}
			f := doc.Findings[0]
			if f.Rule != findings.RuleSnapshotFlagsConflict || f.Object != c.flag || f.Step != findings.StepStart {
				t.Errorf("finding %+v; want snapshot.flags.conflict at %s, at start", f, c.flag)
			}
			if c.flag == "--probes" && !strings.Contains(f.Message, "carries its own probes") {
				t.Errorf("message %q does not say the snapshot carries its own probes", f.Message)
			}
		})
	}
	if kind.checks+kind.reads != 0 {
		t.Errorf("the kind was asked beside a snapshot")
	}
}

// A request's files are held to the shape probes gives them before the answer begins, 400 and
// never a document: the one file probes names, under that path, and on the three operations
// whose only file is a probe file, none without it. Beside snapshot the handler's conflict
// answers instead.
func TestProbeFilesAreHeldToTheirShape(t *testing.T) {
	_, srv, _, calls := testServer(t, answered)
	file := `{"path":"p.json","data":""}`
	for _, c := range []struct{ op, body, says string }{
		{findings.OpIntentRead, `{"args":{"branch":"b","out":"o","probes":"p.json"}}`,
			`intent.read carries 0 files where it takes the probe file its argument "probes" names, under that path, alone`},
		{findings.OpTwinCreate, `{"args":{"branch":"b","probes":"p.json"},"files":[` + file + `,` + file + `]}`,
			`twin.create carries 2 files where it takes the probe file its argument "probes" names, under that path, alone`},
		{findings.OpStagePlan, `{"args":{"branch":"b","probes":"q.json"},"files":[` + file + `]}`,
			`stage.plan carries its probe file under another path than its argument "probes" gives`},
		{findings.OpTwinRehearse, `{"args":{"branch":"b"},"files":[` + file + `]}`,
			`twin.rehearse carries 1 file where it takes a probe file beside its argument "probes" alone`},
		{findings.OpTwinStep, `{"args":{"probes":true}}`, `twin.step's argument "probes" is not a string`},
		{findings.OpCompile, `{"args":{"snapshot":"s.json","probes":"p.json"}}`, `twin.compile takes no argument "probes"`},
		{findings.OpTwinProvision, `{"args":{"bundle":"b","probes":"p.json"}}`, `twin.provision takes no argument "probes"`},
		{findings.OpStageList, `{"args":{"probes":"p.json"}}`, `stage.list takes no argument "probes"`},
	} {
		resp, body := post(t, nil, srv.URL+api.Path(c.op), testToken, c.body, nil)
		var p api.Problem
		if err := json.Unmarshal(body, &p); err != nil || resp.StatusCode != http.StatusBadRequest ||
			p.Message != "the request is not one: "+c.says {
			t.Errorf("%s %s: status %d, body %s; want 400 saying %q", c.op, c.body, resp.StatusCode, body, c.says)
		}
	}
	if n := calls.Load(); n != 0 {
		t.Errorf("%d operations ran", n)
	}

	// The shapes a client sends are admitted, and reach their operation.
	for _, c := range []struct{ op, body string }{
		{findings.OpIntentRead, `{"args":{"branch":"b","out":"o","probes":"p.json"},"files":[` + file + `]}`},
		{findings.OpTwinRehearse, `{"args":{"branch":"b","probes":"p.json"},"files":[` + file + `]}`},
		{findings.OpTwinCreate, `{"args":{"snapshot":"s.json","probes":"p.json"}}`},
		{findings.OpTwinStep, `{"args":{"snapshot":"s.json","probes":"p.json"}}`},
	} {
		if resp, body := post(t, nil, srv.URL+api.Path(c.op), testToken, c.body, nil); resp.StatusCode != http.StatusOK {
			t.Errorf("%s %s: status %d, body %s; want 200", c.op, c.body, resp.StatusCode, body)
		}
	}
	if n := calls.Load(); n != 4 {
		t.Errorf("%d operations ran; want 4", n)
	}
}

// probesOf takes the probe file out of the files the operation holds to its own shape, but
// beside a snapshot, where the conflict answers.
func TestProbesOfTakesTheFileOut(t *testing.T) {
	f := api.File{Path: "p.json", Data: []byte("{}")}
	a := args{"probes": json.RawMessage(`"p.json"`)}
	pa, rest := probesOf(a, []api.File{f})
	if !pa.given || pa.path != "p.json" || pa.file == nil || pa.file.Path != "p.json" || rest != nil {
		t.Errorf("probesOf = %+v, %+v; want the file taken out", pa, rest)
	}
	a["snapshot"] = json.RawMessage(`"s.json"`)
	if pa, rest := probesOf(a, []api.File{f}); pa.file != nil || len(rest) != 1 {
		t.Errorf("beside a snapshot probesOf = %+v, %+v; want the files left", pa, rest)
	}
	if pa, rest := probesOf(args{}, []api.File{f}); pa.given || len(rest) != 1 {
		t.Errorf("with no probes probesOf = %+v, %+v; want the files left", pa, rest)
	}
}
