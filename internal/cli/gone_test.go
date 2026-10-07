package cli

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"regexp"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// A client that goes away.
// The request's context is the server's only news that its client has gone: it stops the
// request's work, stops following a run and never cancels one. A start still waiting for a
// worker is not the request's work: it finishes, and the run goes on, whether the client went
// or the server stopped. Like answer_test.go, these live beside
// the harness, whose fakes are this package's test code.

// goneBound is how long a fake holds what it holds when its context never ends: long enough
// that the cut always lands first, and short enough that a handler given a context no client
// can end fails its test instead of hanging it.
const goneBound = 3 * time.Second

// cutAnswer posts op's request to the harness's server as a client does, asking for text,
// reads its frames until reached is closed, then goes away with the rest of the answer unread.
// It returns the kinds of the frames read before the cut.
func cutAnswer(t *testing.T, op string, args map[string]any, reached <-chan struct{}) []string {
	t.Helper()
	return cutAnswerOn(t, harness.http.URL, op, args, reached, nil, nil)
}

// cutAnswerOn is cutAnswer to the server at url, cut by stop when it is given: the server's
// stop in place of the client's departure, the client reading on until its connection ends.
// beforeCut, when it is given, is called with the answer's stream once reached is closed,
// before the cut.
func cutAnswerOn(t *testing.T, url, op string, args map[string]any, reached <-chan struct{},
	beforeCut func(stream string), stop func()) []string {
	t.Helper()
	req := api.Request{Render: api.RenderText, Args: map[string]json.RawMessage{}}
	for k, v := range args {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		req.Args[k] = b
	}
	body, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	ctx, goAway := context.WithCancel(context.Background())
	defer goAway()
	hreq, err := http.NewRequestWithContext(ctx, http.MethodPost, url+api.Path(op), bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	hreq.Header.Set("Authorization", "Bearer "+harness.token)
	var stream string
	if takesInterrupts(op) {
		if stream, err = newStream(); err != nil {
			t.Fatal(err)
		}
		hreq.Header.Set(api.HeaderStream, stream)
	}
	resp, err := http.DefaultClient.Do(hreq)
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var kinds []string
	read := make(chan struct{})
	go func() {
		defer close(read)
		r := bufio.NewReader(resp.Body)
		for {
			line, err := r.ReadBytes('\n')
			var f api.Frame
			if len(line) > 0 && json.Unmarshal(line, &f) == nil {
				mu.Lock()
				kinds = append(kinds, f.Kind())
				mu.Unlock()
			}
			if err != nil {
				return
			}
		}
	}()
	select {
	case <-reached:
	case <-time.After(goneBound):
		t.Fatalf("%s: the server never reached the point the client goes away at", op)
	}
	mu.Lock()
	before := append([]string(nil), kinds...)
	mu.Unlock()
	if beforeCut != nil {
		beforeCut(stream)
	}
	if stop != nil {
		stop()
		select {
		case <-read:
		case <-time.After(goneBound):
			t.Errorf("%s: the answer went on after the server stopped", op)
		}
	}
	goAway()
	_ = resp.Body.Close()
	<-read
	return before
}

// stoppingServer is a second server over the harness's handlers and seams, which a test stops
// as fylgja serve stops: http.Server.Close, every connection closed at once and every
// request's context ended with it (cmd/fylgja/serve.go). Its log is the harness's.
func stoppingServer(t *testing.T) *httptest.Server {
	t.Helper()
	handler := harness.srv.Handler()
	ts := httptest.NewServer(serving(func(w http.ResponseWriter, r *http.Request) {
		if !strings.Contains(r.URL.Path, "/streams/") {
			handSeams()
		}
		handler.ServeHTTP(&wireRecorder{ResponseWriter: w, wire: harness.wire}, r)
	}))
	t.Cleanup(ts.Close)
	return ts
}

var requestLine = regexp.MustCompile(`msg=request operation=(\S+) outcome=(\S+) `)

// requestOutcomes are the outcomes the harness's server logged for op's requests, in order.
func requestOutcomes(op string) []string {
	var out []string
	for _, m := range requestLine.FindAllStringSubmatch(harness.log.String(), -1) {
		if m[1] == op {
			out = append(out, m[2])
		}
	}
	return out
}

// servedAfter waits for the server to log op's request after the first n, and returns how it
// ended: the handler has returned by then, so nothing it holds is still in use.
func servedAfter(t *testing.T, op string, n int) string {
	t.Helper()
	deadline := time.Now().Add(2 * goneBound)
	for time.Now().Before(deadline) {
		if got := requestOutcomes(op); len(got) > n {
			return got[n]
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("the server logged no end of the %s request", op)
	return ""
}

// wantGone holds the request to having ended client_gone, with no panic logged, since a
// document written to a closed connection is no answer and must not take the server down.
func wantGone(t *testing.T, op string, n, panics int) {
	t.Helper()
	if got := servedAfter(t, op, n); got != "client_gone" {
		t.Errorf("the %s request ended %s, want client_gone", op, got)
	}
	if got := strings.Count(harness.log.String(), "outcome=panic"); got != panics {
		t.Errorf("the server logged %d panics, want none", got-panics)
	}
}

// goneService is the harness's fake service, with what each case holds open until the
// request's context ends: the start waiting for a worker, or the follow of a started run.
// Each holds at most goneBound, and then answers as a service whose run went on would.
type goneService struct {
	*fakeService
	holdStart, holdFollow bool
	reached               chan struct{}

	startReturned, followReturned atomic.Bool
	results, liveResults          atomic.Int32
}

func (g *goneService) hold(ctx context.Context) bool {
	close(g.reached)
	select {
	case <-ctx.Done():
		return true
	case <-time.After(goneBound):
		return false
	}
}

func (g *goneService) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	if !g.holdStart {
		return g.fakeService.StartProvision(ctx, in)
	}
	defer g.startReturned.Store(true)
	g.mu.Lock()
	g.calls = append(g.calls, "StartProvision")
	g.mu.Unlock()
	if !g.hold(ctx) {
		return g.runID, nil
	}
	g.mu.Lock()
	g.abandoned = true
	g.mu.Unlock()
	// What the workflow service's client answers for a start abandoned before a worker took
	// the run: it has terminated that run (internal/provision/client.go).
	return "", &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
		Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: g.runID, Step: findings.StepStart,
		Message: "interrupted before a worker took run " + g.runID + ", so the run was terminated before anything in it ran",
	}}
}

func (g *goneService) Follow(ctx context.Context, w, r string, onEvent func(provision.Event)) error {
	if !g.holdFollow {
		return g.fakeService.Follow(ctx, w, r, onEvent)
	}
	defer g.followReturned.Store(true)
	if g.hold(ctx) {
		return ctx.Err()
	}
	return nil
}

func (g *goneService) Result(ctx context.Context, w, r string) (provision.ProvisionResult, error) {
	g.results.Add(1)
	if ctx.Err() != nil {
		return provision.ProvisionResult{}, ctx.Err()
	}
	g.liveResults.Add(1)
	return g.fakeService.Result(ctx, w, r)
}

// A client that goes away during a run's request: before the start, after the dial and
// before the start, while the start waits for a worker, and while the started run is
// followed. The server stops the request's work and starts nothing it had not begun to
// start; a start already waiting for a worker finishes, with the server stopped too;
// it stops following, and never cancels the run.
func TestAClientGoneDuringARun(t *testing.T) {
	create := map[string]any{"branch": "fylgja-fixture", "no_follow": true}

	t.Run("before start", func(t *testing.T) {
		useStateRoot(t)
		svc := &goneService{fakeService: &fakeService{runID: "run-1", result: readyResult()}, reached: make(chan struct{})}
		var dialReturned atomic.Bool
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(ctx context.Context) (provision.Service, error) {
			defer dialReturned.Store(true)
			if svc.hold(ctx) {
				return nil, ctx.Err()
			}
			return svc, nil
		}
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		kinds := cutAnswer(t, findings.OpTwinCreate, create, svc.reached)

		wantGone(t, findings.OpTwinCreate, n, panics)
		for _, k := range kinds {
			if k == api.KindStart {
				t.Error("the server wrote start before its dial returned")
			}
		}
		svc.mu.Lock()
		defer svc.mu.Unlock()
		if len(svc.calls) != 0 || svc.cancels != 0 {
			t.Errorf("the service was asked %v and cancelled %d times; want nothing started", svc.calls, svc.cancels)
		}
		if !dialReturned.Load() {
			t.Error("the dial was left waiting")
		}
	})

	// The dial returns once the client has gone: nothing is started for a request that ended
	// before its start began (contracts/cli.md, "Runs").
	t.Run("after the dial, before start", func(t *testing.T) {
		useStateRoot(t)
		svc := &goneService{fakeService: &fakeService{runID: "run-1", result: readyResult()}, reached: make(chan struct{})}
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(ctx context.Context) (provision.Service, error) {
			svc.hold(ctx)
			return svc, nil
		}
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		kinds := cutAnswer(t, findings.OpTwinCreate, create, svc.reached)

		wantGone(t, findings.OpTwinCreate, n, panics)
		if slices.Contains(kinds, api.KindStart) {
			t.Error("the server wrote start before its dial returned")
		}
		svc.mu.Lock()
		defer svc.mu.Unlock()
		if len(svc.calls) != 0 || len(svc.started) != 0 || svc.cancels != 0 {
			t.Errorf("the service was asked %v and cancelled %d times; want nothing started", svc.calls, svc.cancels)
		}
	})

	t.Run("the start waiting for a worker", func(t *testing.T) {
		useStateRoot(t)
		svc := newStartService()
		useStartService(t, svc)
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		cutAnswer(t, findings.OpTwinCreate, create, svc.reached)

		wantGone(t, findings.OpTwinCreate, n, panics)
		svc.wantStartedAndLeft(t, "StartProvision")
	})

	// The server's stop ends every request's context as a client's departure ends one, and a
	// start waiting for a worker finishes all the same.
	t.Run("the start waiting for a worker, the server stopped", func(t *testing.T) {
		useStateRoot(t)
		svc := newStartService()
		useStartService(t, svc)
		ts := stoppingServer(t)
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		cutAnswerOn(t, ts.URL, findings.OpTwinCreate, create, svc.reached, nil, func() { _ = ts.Config.Close() })

		wantGone(t, findings.OpTwinCreate, n, panics)
		svc.wantStartedAndLeft(t, "StartProvision")
	})

	t.Run("the run followed", func(t *testing.T) {
		useStateRoot(t)
		svc := &goneService{fakeService: &fakeService{runID: "run-1", result: readyResult()}, holdFollow: true,
			reached: make(chan struct{})}
		useService(t, svc)
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		cutAnswer(t, findings.OpTwinCreate, create, svc.reached)

		wantGone(t, findings.OpTwinCreate, n, panics)
		svc.mu.Lock()
		defer svc.mu.Unlock()
		if svc.cancels != 0 {
			t.Errorf("Cancel called %d times, want none: the run goes on", svc.cancels)
		}
		if !svc.followReturned.Load() || svc.results.Load() > 1 || svc.liveResults.Load() != 0 {
			t.Errorf("follow returned %v; Result asked %d times, %d of them waiting on the run; want the follow ended "+
				"and the result not waited for", svc.followReturned.Load(), svc.results.Load(), svc.liveResults.Load())
		}
	})
}

// A client that goes away straight after its first interrupt was delivered: the run is asked
// to cancel all the same, on a context the client's departure does not end, since the client
// that survives to report says it was.
func TestAClientGoneAfterItsInterrupt(t *testing.T) {
	useStateRoot(t)
	svc := &cancelService{goneService: &goneService{fakeService: &fakeService{runID: "run-1", result: readyResult()},
		holdFollow: true, reached: make(chan struct{})}}
	saved := dialService
	t.Cleanup(func() { dialService = saved })
	dialService = func(ctx context.Context) (provision.Service, error) {
		svc.mu.Lock()
		defer svc.mu.Unlock()
		svc.request = ctx
		return svc, nil
	}
	awaitIdle(t)
	n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")
	delivered := len(requestOutcomes(logInterrupt))

	cutAnswerOn(t, harness.http.URL, findings.OpTwinCreate, map[string]any{"branch": "fylgja-fixture", "no_follow": true},
		svc.reached, func(stream string) {
			if code := postInterrupt(t, stream); code != http.StatusNoContent {
				t.Fatalf("the interrupt was answered %d, want 204", code)
			}
		}, nil)

	wantGone(t, findings.OpTwinCreate, n, panics)
	if got := servedAfter(t, logInterrupt, delivered); got != "delivered" {
		t.Errorf("the interrupt ended %s, want delivered", got)
	}
	if got := svc.cancelCalls.Load(); got != 1 {
		t.Errorf("Cancel called %d times, want once", got)
	}
	if svc.cancelEnded.Load() || !svc.cancelDone.Load() {
		t.Errorf("the cancel's context ended %v, the cancel completed %v; want it completed, its context not ended "+
			"with the request's", svc.cancelEnded.Load(), svc.cancelDone.Load())
	}
}

// logInterrupt is the operation the server's log names an interrupt by.
const logInterrupt = "interrupt"

// postInterrupt delivers one interrupt to stream's answer, as the client does, and returns
// the status it was answered.
func postInterrupt(t *testing.T, stream string) int {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, harness.http.URL+api.InterruptPath(stream), nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+harness.token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	return resp.StatusCode
}

// cancelService is goneService with its follow held, whose Cancel holds until the request's
// context has ended, the request's as its dial was given it, then says whether the cancel's
// own context ended with it. One that did not completes.
type cancelService struct {
	*goneService
	mu      sync.Mutex
	request context.Context

	cancelCalls             atomic.Int32
	cancelEnded, cancelDone atomic.Bool
}

func (c *cancelService) Cancel(ctx context.Context, _, _ string) error {
	c.cancelCalls.Add(1)
	c.mu.Lock()
	request := c.request
	c.mu.Unlock()
	select {
	case <-request.Done():
	case <-time.After(goneBound):
	}
	select {
	case <-ctx.Done():
		c.cancelEnded.Store(true)
		return ctx.Err()
	case <-time.After(detachGrace):
		c.cancelDone.Store(true)
		return nil
	}
}

// A twin destroy whose client goes away while the destroy run waits for a worker: the start
// finishes, the run goes on, and once its progress is seen the following stops.
func TestAClientGoneDuringADestroysStart(t *testing.T) {
	useStateRoot(t)
	svc := newStartService()
	useStartService(t, svc)
	awaitIdle(t)
	n, panics := len(requestOutcomes(findings.OpTwinDestroy)), strings.Count(harness.log.String(), "outcome=panic")

	cutAnswer(t, findings.OpTwinDestroy, nil, svc.reached)

	wantGone(t, findings.OpTwinDestroy, n, panics)
	svc.wantStartedAndLeft(t, "StartDestroy")
	if !svc.followEnded.Load() {
		t.Error("the destroy run was followed on after the client went; want the following ended on the request's context")
	}
}

// A twin destroy whose server stops, as fylgja serve stops, through the client's own command
// (contracts/cli.md, "Runs"). Once the server has begun to start the destroy run, its answer
// carries fylgja-destroy's start frame, so the client says a run may have been started and
// was not cancelled, and the start finishes and the run goes on: only the operator's
// interrupt abandons a start. Stopped while following stops, before that frame, the client
// says nothing of a run, and the server starts none: a start frame is written only to a
// request still open.
// Each mode has a server of its own, since the first is stopped.
func TestAServerStoppedDuringADestroy(t *testing.T) {
	destroyCmd := func(opts *options) error { return runDestroy(context.Background(), opts) }
	// stopped runs the destroy in one mode against a server of its own over svc, which it
	// stops once reached is closed, and returns what the client printed and the address it
	// named, once the server's handler has ended.
	stopped := func(t *testing.T, asJSON bool, reached <-chan struct{}) (clientRun, string) {
		t.Helper()
		ts := stoppingServer(t)
		address := strings.TrimPrefix(ts.URL, "http://")
		useAPIAt(t, address, harness.token)
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinDestroy)), strings.Count(harness.log.String(), "outcome=panic")
		go func() {
			select {
			case <-reached:
				_ = ts.Config.Close()
			case <-time.After(goneBound):
				t.Error("the server never reached the point it stops at")
			}
		}()
		run := oneMode(t, asJSON, destroyCmd)
		wantGone(t, findings.OpTwinDestroy, n, panics)
		return run, address
	}
	// wantStopped holds each mode to the one finding its own server's address words.
	wantStopped := func(t *testing.T, runs [2]clientRun, addresses [2]string, suffix string) {
		t.Helper()
		for i := range runs {
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: addresses[i],
				Message: "the API at " + addresses[i] + " stopped answering before the command ended: unexpected EOF" + suffix}
			if i == 0 {
				// The text half of wantClientFailure, held against its own server's address.
				wantClientFailure(t, findings.OpTwinDestroy, runs[0], clientRun{code: findings.ExitError,
					doc: findings.RuleErrorDocument(findings.OpTwinDestroy, nil, want.Rule, want.Object, want.Message)}, want)
				continue
			}
			wantClientFailure(t, findings.OpTwinDestroy, clientRun{code: findings.ExitError, stderr: want.Rule + " " + want.Message},
				runs[1], want)
		}
	}

	t.Run("once the destroy's start is reached", func(t *testing.T) {
		var runs [2]clientRun
		var addresses [2]string
		for i, asJSON := range []bool{false, true} {
			useStateRoot(t)
			svc := newStartService()
			useStartService(t, svc)
			runs[i], addresses[i] = stopped(t, asJSON, svc.reached)
			svc.wantStartedAndLeft(t, "StartDestroy")
		}
		wantStopped(t, runs, addresses, "; a run may have been started and was not cancelled: fylgja twin show names it")
	})

	t.Run("while following stops", func(t *testing.T) {
		var runs [2]clientRun
		var addresses [2]string
		for i, asJSON := range []bool{false, true} {
			useStateRoot(t)
			svc := &stopHeld{fakeService: &fakeService{destroyRun: destroyedRun(provision.CleanupResult{
				Teardown: provision.CleanupNothing, Unstage: provision.CleanupNothing}, nil)}, reached: make(chan struct{})}
			useService(t, svc)
			runs[i], addresses[i] = stopped(t, asJSON, svc.reached)
			svc.mu.Lock()
			if want := []string{"StopFollowing"}; !slices.Equal(svc.calls, want) {
				t.Errorf("the service was asked %v, want %v: no destroy run is started for a request that has ended", svc.calls, want)
			}
			svc.mu.Unlock()
		}
		wantStopped(t, runs, addresses, "")
	})
}

// stopHeld is the harness's fake service with following's stop held until the request's
// context has ended, as a check's cleanup holds it. The stop then answers as one that
// completed, so that only the server's own look at the request decides whether the destroy
// run is started.
type stopHeld struct {
	*fakeService
	reached chan struct{}
}

func (s *stopHeld) StopFollowing(ctx context.Context, onEvent func(provision.Event)) (provision.FollowStop, error) {
	close(s.reached)
	select {
	case <-ctx.Done():
	case <-time.After(goneBound):
	}
	return s.fakeService.StopFollowing(context.WithoutCancel(ctx), onEvent)
}

// startService holds a start until the request's context has ended, the request's as its dial
// was given it, then says whether the start's own context ended with it. A start whose context
// ended answers as the workflow service's client does once it has terminated a run no worker
// took; one that goes on answers as a worker that took the run, and a destroy run is then
// followed until its context ends. The rest is goneService's, with nothing held.
type startService struct {
	*goneService
	mu      sync.Mutex
	request context.Context

	startEnded, started, followEnded atomic.Bool
}

// detachGrace is how long a start's context is watched once the request's has ended: a start
// on a context derived from the request's has ended with it by then.
const detachGrace = 200 * time.Millisecond

func newStartService() *startService {
	return &startService{goneService: &goneService{fakeService: &fakeService{runID: "run-1", result: readyResult()},
		reached: make(chan struct{})}}
}

// useStartService makes svc what the server dials, and keeps the request's context it is
// dialled with.
func useStartService(t *testing.T, svc *startService) {
	t.Helper()
	saved := dialService
	t.Cleanup(func() { dialService = saved })
	dialService = func(ctx context.Context) (provision.Service, error) {
		svc.mu.Lock()
		defer svc.mu.Unlock()
		if svc.request == nil {
			svc.request = ctx
		}
		return svc, nil
	}
}

// waitForTheCut holds the start until the request's context has ended, and reports whether
// the start's context ended with it.
func (s *startService) waitForTheCut(ctx context.Context) bool {
	close(s.reached)
	s.mu.Lock()
	request := s.request
	s.mu.Unlock()
	select {
	case <-request.Done():
	case <-time.After(goneBound):
	}
	select {
	case <-ctx.Done():
		s.startEnded.Store(true)
		return true
	case <-time.After(detachGrace):
		s.started.Store(true)
		return false
	}
}

func (s *startService) terminated() error {
	return &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
		Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: s.runID, Step: findings.StepStart,
		Message: "interrupted before a worker took run " + s.runID + ", so the run was terminated before anything in it ran",
	}}
}

func (s *startService) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	s.fakeService.mu.Lock()
	s.calls = append(s.calls, "StartProvision")
	s.fakeService.mu.Unlock()
	if s.waitForTheCut(ctx) {
		return "", s.terminated()
	}
	return s.runID, nil
}

func (s *startService) StartDestroy(ctx context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	s.fakeService.mu.Lock()
	s.calls = append(s.calls, "StartDestroy")
	s.fakeService.mu.Unlock()
	if s.waitForTheCut(ctx) {
		return provision.DestroyRun{}, s.terminated()
	}
	onEvent(provision.Event{Notice: "run " + provision.WorkflowDestroy + " " + s.runID})
	onEvent(provision.Event{WorkflowID: provision.WorkflowDestroy, Step: "teardown", FindingStep: findings.StepTeardown})
	select {
	case <-ctx.Done():
		s.followEnded.Store(true)
		return provision.DestroyRun{RunID: s.runID}, ctx.Err()
	case <-time.After(goneBound):
		return provision.DestroyRun{RunID: s.runID}, nil
	}
}

// wantStartedAndLeft holds the start to having finished with its context intact, and the run
// to having been neither cancelled nor waited for on a context the request's end reached.
func (s *startService) wantStartedAndLeft(t *testing.T, start string) {
	t.Helper()
	if s.startEnded.Load() || !s.started.Load() {
		t.Errorf("the start's context ended %v, the start finished %v; want the start finished, its context "+
			"not ended with the request's", s.startEnded.Load(), s.started.Load())
	}
	s.fakeService.mu.Lock()
	defer s.fakeService.mu.Unlock()
	if !slices.Contains(s.calls, start) {
		t.Errorf("the service was asked %v, want %s", s.calls, start)
	}
	if s.cancels != 0 || s.liveResults.Load() != 0 {
		t.Errorf("Cancel called %d times, Result waited for on a live context %d times; want neither: the run goes on",
			s.cancels, s.liveResults.Load())
	}
}

// A client that goes away during a command that is one answer stops its work too: twin
// verify's wait
// reads and sleeps no more, and a create's dry run, cut while Infrahub holds its read open,
// files nothing and asks the host nothing.
func TestAClientGoneDuringOneAnswer(t *testing.T) {
	t.Run("twin verify --wait", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		nodes := h.healthy(t)
		// n1 sees no neighbour on ethernet-1/1, so the first read leaves the twin unsettled.
		nodes.set("n1", neighbourPath("nokia_srlinux", "ethernet-1/1"), verify.Answer{})
		saved := verifyReader
		t.Cleanup(func() { verifyReader = saved })
		verifyReader = nodes

		reached := make(chan struct{})
		var sleeps atomic.Int32
		var readsAtSleep atomic.Int64
		var mu sync.Mutex
		now := time.Date(2026, 10, 4, 10, 0, 0, 0, time.UTC)
		savedSleep, savedNow := verifySleep, verifyNow
		t.Cleanup(func() { verifySleep, verifyNow = savedSleep, savedNow })
		verifyNow = func() time.Time {
			mu.Lock()
			defer mu.Unlock()
			return now
		}
		verifySleep = func(ctx context.Context, d time.Duration) error {
			if sleeps.Add(1) == 1 {
				readsAtSleep.Store(int64(len(nodes.called())))
				close(reached)
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(goneBound):
				}
			}
			mu.Lock()
			defer mu.Unlock()
			now = now.Add(d)
			return nil
		}
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinVerify)), strings.Count(harness.log.String(), "outcome=panic")

		cutAnswer(t, findings.OpTwinVerify, map[string]any{"wait": "5s"}, reached)

		wantGone(t, findings.OpTwinVerify, n, panics)
		if got, first := len(nodes.called()), readsAtSleep.Load(); first == 0 || int64(got) != first {
			t.Errorf("the nodes were read %d times, %d of them before the client went; want no read after it", got, first)
		}
		if got := sleeps.Load(); got != 1 {
			t.Errorf("verify slept %d times, want once: no pause after the client went", got)
		}
	})

	t.Run("twin create --dry-run", func(t *testing.T) {
		paths := useStateRoot(t)
		useService(t, nil)
		dryRunEnv(t)
		var asked atomic.Int32
		saved := dryRunRunner
		t.Cleanup(func() { dryRunRunner = saved })
		dryRunRunner = runnerFunc(func(args ...string) {
			asked.Add(1)
		})

		f := newFakeInfrahub(t)
		reached := make(chan struct{})
		var held atomic.Bool
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if held.CompareAndSwap(false, true) {
				close(reached)
				select {
				case <-r.Context().Done():
					return
				case <-time.After(goneBound):
				}
			}
			f.serve(w, r)
		}))
		t.Cleanup(srv.Close)
		t.Setenv(intent.EnvAddress, srv.URL)
		t.Setenv(intent.EnvToken, fakeToken)
		awaitIdle(t)
		n, panics := len(requestOutcomes(findings.OpTwinCreate)), strings.Count(harness.log.String(), "outcome=panic")

		cutAnswer(t, findings.OpTwinCreate, map[string]any{"branch": "fylgja-fixture", "dry_run": true}, reached)

		wantGone(t, findings.OpTwinCreate, n, panics)
		if got := entriesOf(t, paths.Bundles); len(got) != 0 {
			t.Errorf("the store holds %v after a dry run whose client went during its read", got)
		}
		if got := asked.Load(); got != 0 {
			t.Errorf("the host was asked %d times after the client went", got)
		}
	})
}

// runnerFunc is a host runner that tells the test it was asked, and answers nothing.
type runnerFunc func(args ...string)

func (f runnerFunc) Run(_ context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	f(args...)
	return []byte("{}"), nil, 0, nil
}
