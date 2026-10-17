package intent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"net/url"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeStages is an Infrahub holding the stage kind (or not), open proposed changes with
// their marks, orphaned marks, branches and artifact validators, answering the two
// unnamed endpoints the reader uses and recording what it was asked.
type fakeStages struct {
	// attributes is the stage kind's attributes on the schema endpoint; nil means the
	// kind is absent from the default branch's schema.
	attributes []string
	// noRelationship drops the kind's proposed_change; noExtension drops the proposed
	// change's fylgja_stages.
	noRelationship, noExtension bool

	proposed   []map[string]any // CoreProposedChange nodes, each with source_branch
	orphans    []map[string]any
	branches   []map[string]any
	validators []map[string]any

	mu       sync.Mutex
	requests []stageRequest
}

// stageRequest is one request as the fake saw it.
type stageRequest struct {
	Method, Path, RawQuery, Key string
	Operation                   string
	Variables                   map[string]any
}

func (f *fakeStages) serve(w http.ResponseWriter, r *http.Request) {
	seen := stageRequest{Method: r.Method, Path: r.URL.Path, RawQuery: r.URL.RawQuery, Key: r.Header.Get("X-INFRAHUB-KEY")}
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		f.record(seen)
		nodes := []map[string]any{{"kind": "NetworkDevice", "attributes": []map[string]any{{"name": "name"}}}}
		pcRels := []map[string]any{{"name": "validations", "peer": "CoreValidator"}}
		if !f.noExtension {
			pcRels = append(pcRels, map[string]any{"name": StageExtension, "peer": StageKind})
		}
		nodes = append(nodes, map[string]any{"kind": ProposedChangeKind, "branch": "agnostic",
			"attributes": []map[string]any{{"name": "name"}, {"name": "source_branch"}}, "relationships": pcRels})
		if f.attributes != nil {
			var attrs []map[string]any
			for _, a := range f.attributes {
				attrs = append(attrs, map[string]any{"name": a})
			}
			rels := []map[string]any{{"name": "member_of_groups", "peer": "CoreGroup"}}
			if !f.noRelationship {
				rels = append(rels, map[string]any{"name": StageRelationship, "peer": ProposedChangeKind})
			}
			nodes = append(nodes, map[string]any{"kind": StageKind, "branch": "agnostic", "attributes": attrs, "relationships": rels})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"main": "a8045729", "nodes": nodes})
	case r.Method == http.MethodPost && r.URL.Path == "/graphql":
		var req struct {
			OperationName string         `json:"operationName"`
			Variables     map[string]any `json:"variables"`
		}
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &req)
		seen.Operation, seen.Variables = req.OperationName, req.Variables
		f.record(seen)
		limit, _ := req.Variables["limit"].(float64)
		offset, _ := req.Variables["offset"].(float64)
		var data map[string]any
		switch req.OperationName {
		case "ProposedChanges":
			var open []map[string]any
			for _, pc := range f.proposed {
				branch, filtered := req.Variables["branch"]
				if filtered && pc["source_branch"].(map[string]any)["value"] != branch {
					continue
				}
				open = append(open, pc)
			}
			data = map[string]any{"CoreProposedChange": stagePage(open, int(limit), int(offset))}
		case "OrphanStages":
			data = map[string]any{"FylgjaStage": stagePage(f.orphans, int(limit), int(offset))}
		case "BranchPoint":
			var out []map[string]any
			for _, b := range f.branches {
				if b["name"] == req.Variables["name"] {
					out = append(out, b)
				}
			}
			if out == nil {
				out = []map[string]any{}
			}
			data = map[string]any{"Branch": out}
		case "ArtifactValidations":
			var edges []map[string]any
			for _, v := range f.validators {
				edges = append(edges, map[string]any{"node": v})
			}
			data = map[string]any{"CoreArtifactValidator": map[string]any{"edges": edges}}
		default:
			http.Error(w, "unknown operation "+req.OperationName, http.StatusTeapot)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
	default:
		f.record(seen)
		http.NotFound(w, r)
	}
}

func (f *fakeStages) record(r stageRequest) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.requests = append(f.requests, r)
}

// asked returns what the fake was asked by one GraphQL operation, in order.
func (f *fakeStages) asked(operation string) []stageRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []stageRequest
	for _, r := range f.requests {
		if r.Operation == operation {
			out = append(out, r)
		}
	}
	return out
}

func (f *fakeStages) reader(t *testing.T) *StageReader {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(srv.Close)
	return NewStageReader(srv.URL, "sentinel-token")
}

func stagePage(nodes []map[string]any, limit, offset int) map[string]any {
	end := min(offset+limit, len(nodes))
	edges := []map[string]any{}
	for _, n := range nodes[min(offset, len(nodes)):end] {
		edges = append(edges, map[string]any{"node": n})
	}
	return map[string]any{"count": len(nodes), "edges": edges}
}

// stageNode is one mark as Infrahub's GraphQL answers it; at "" is an unwritten as_of,
// which Infrahub answers as null.
func stageNode(id, label, writtenAt, at, description string) map[string]any {
	var asOf any
	if at != "" {
		asOf = at
	}
	return map[string]any{
		"id":          id,
		"label":       map[string]any{"value": label, "updated_at": writtenAt},
		"as_of":       map[string]any{"value": asOf, "updated_at": writtenAt},
		"description": map[string]any{"value": description},
	}
}

// proposedNode is one open proposed change as Infrahub's GraphQL answers it.
func proposedNode(id, name, branch string, draft bool, stages ...map[string]any) map[string]any {
	var edges []map[string]any
	for _, s := range stages {
		edges = append(edges, map[string]any{"node": s})
	}
	return map[string]any{
		"id":                 id,
		"name":               map[string]any{"value": name},
		"source_branch":      map[string]any{"value": branch},
		"destination_branch": map[string]any{"value": "main"},
		"state":              map[string]any{"value": "open"},
		"is_draft":           map[string]any{"value": draft},
		"fylgja_stages":      map[string]any{"edges": edges},
	}
}

func validatorNode(completedAt string) map[string]any {
	var value any
	if completedAt != "" {
		value = completedAt
	}
	return map[string]any{
		"completed_at": map[string]any{"value": value},
		"definition":   map[string]any{"node": map[string]any{"name": map[string]any{"value": "srlinux_device_config"}}},
	}
}

func ctx10s(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// The kind's presence and shape are read from the schema endpoint before any query, and
// what is missing is named: the kind; each attribute this build reads, in StageFields'
// order, and the relationship to the proposed change; or the proposed change's
// extension. These are the three first halves of stage.kind.absent.
func TestStageReaderChecksTheKind(t *testing.T) {
	for _, tc := range []struct {
		name                        string
		attributes                  []string
		noRelationship, noExtension bool
		missing                     []string
		extension                   bool
		message                     string // "": present
	}{
		{name: "present", attributes: []string{"description", "as_of", "label"}},
		{name: "absent", message: "the default branch's schema has no kind FylgjaStage"},
		{name: "description missing", attributes: []string{"label", "as_of"}, missing: []string{"description"},
			message: "kind FylgjaStage on the default branch lacks the attribute description, which this build reads"},
		{name: "two missing", attributes: []string{"as_of"}, missing: []string{"label", "description"},
			message: "kind FylgjaStage on the default branch lacks the attributes label, description, which this build reads"},
		{name: "relationship missing", attributes: StageFields, noRelationship: true, missing: []string{"proposed_change"},
			message: "kind FylgjaStage on the default branch lacks the relationship proposed_change, which this build reads"},
		{name: "extension missing", attributes: StageFields, noExtension: true, extension: true,
			message: "kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds"},
		{name: "attribute and extension missing", attributes: []string{"label", "as_of"}, noExtension: true,
			missing: []string{"description"}, extension: true,
			message: "kind FylgjaStage on the default branch lacks the attribute description, which this build reads; " +
				"kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := &fakeStages{attributes: tc.attributes, noRelationship: tc.noRelationship, noExtension: tc.noExtension}
			err := f.reader(t).Check(ctx10s(t))
			if tc.message == "" {
				if err != nil {
					t.Fatalf("a kind with every attribute, its relationship and the extension: %v", err)
				}
				return
			}
			var kindErr *StageKindError
			if !errors.As(err, &kindErr) {
				t.Fatalf("want a *StageKindError, got %v", err)
			}
			if !slices.Equal(kindErr.Missing, tc.missing) {
				t.Errorf("Missing = %v, want %v", kindErr.Missing, tc.missing)
			}
			if kindErr.Extension != tc.extension {
				t.Errorf("Extension = %v, want %v", kindErr.Extension, tc.extension)
			}
			if err.Error() != tc.message {
				t.Errorf("message = %q, want %q", err, tc.message)
			}
		})
	}
}

// With no branch named, the request carries no branch at all, which Infrahub reads as no
// filter, so every open proposed change is listed; "" would match none (verified
// 2026-10-16). Named, the branch is sent and only its proposed change comes back. Every
// page is read, and the rows come back sorted by branch whatever order the server
// answered in.
func TestStageReaderListsOpenProposedChanges(t *testing.T) {
	var nodes []map[string]any
	for i := range 101 {
		nodes = append(nodes, proposedNode(fmt.Sprintf("pc-%03d", i), "change", fmt.Sprintf("change-%03d", i), i%2 == 0))
	}
	rand.New(rand.NewSource(7)).Shuffle(len(nodes), func(i, j int) { nodes[i], nodes[j] = nodes[j], nodes[i] })
	f := &fakeStages{proposed: nodes}
	r := f.reader(t)

	all, err := r.ProposedChanges(ctx10s(t), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 101 {
		t.Fatalf("got %d proposed changes from two pages, want 101", len(all))
	}
	if !slices.IsSortedFunc(all, func(a, b ProposedChange) int { return strings.Compare(a.Branch, b.Branch) }) {
		t.Errorf("rows are not sorted by branch: first %s, last %s", all[0].Branch, all[100].Branch)
	}
	var offsets []float64
	for _, req := range f.asked("ProposedChanges") {
		if _, sent := req.Variables["branch"]; sent {
			t.Errorf("an empty filter sent branch %v; Infrahub matches nothing for \"\"", req.Variables["branch"])
		}
		offsets = append(offsets, req.Variables["offset"].(float64))
	}
	if !slices.Equal(offsets, []float64{0, pageSize}) {
		t.Errorf("pages requested at offsets %v, want [0 %d]", offsets, pageSize)
	}

	f.requests = nil
	one, err := r.ProposedChanges(ctx10s(t), "change-042")
	if err != nil {
		t.Fatal(err)
	}
	if len(one) != 1 || one[0].ID != "pc-042" || one[0].Branch != "change-042" {
		t.Errorf("filtered by change-042: %+v", one)
	}
	asked := f.asked("ProposedChanges")
	if len(asked) != 1 || asked[0].Variables["branch"] != "change-042" {
		t.Errorf("the filtered request carried %v, want branch change-042", asked)
	}
}

// A proposed change and its marks are kept as Infrahub returned them: a written as_of
// and label.updated_at character for character, an unwritten as_of nil (Constitution
// VI). Its marks come back by label; the stages package orders them by `at`.
func TestStageReaderKeepsValuesVerbatim(t *testing.T) {
	f := &fakeStages{proposed: []map[string]any{
		proposedNode("pc-1", "rewire the leaves", "change-1", true,
			stageNode("st-2", "third-link", "2026-10-16T19:40:01.000002+00:00", "2026-10-16T19:39:00.5+02:00", ""),
			stageNode("st-1", "seeded", "2026-10-16T19:26:07.357145+00:00", "", "before the change"),
		),
	}}
	got, err := f.reader(t).ProposedChanges(ctx10s(t), "change-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 {
		t.Fatalf("got %d proposed changes, want 1", len(got))
	}
	pc := got[0]
	if pc.ID != "pc-1" || pc.Name != "rewire the leaves" || pc.Branch != "change-1" || pc.Destination != "main" ||
		pc.State != "open" || !pc.Draft {
		t.Errorf("proposed change = %+v", pc)
	}
	want := []Stage{
		{ID: "st-1", Label: "seeded", LabelWrittenAt: "2026-10-16T19:26:07.357145+00:00", Description: "before the change"},
		{ID: "st-2", Label: "third-link", LabelWrittenAt: "2026-10-16T19:40:01.000002+00:00", At: ptr("2026-10-16T19:39:00.5+02:00")},
	}
	if len(pc.Stages) != len(want) {
		t.Fatalf("stages = %+v, want %d", pc.Stages, len(want))
	}
	for i := range want {
		g, w := pc.Stages[i], want[i]
		if deref(g.At) != deref(w.At) {
			t.Errorf("stage %d At = %v, want %v", i, deref(g.At), deref(w.At))
		}
		g.At, w.At = nil, nil
		if g != w {
			t.Errorf("stage %d = %+v, want %+v", i, g, w)
		}
	}
}

// An orphaned mark, which its proposed change no longer names (removed from its
// fylgja_stages, D-047), is listed from FylgjaStage's own root, by label.
func TestStageReaderListsOrphans(t *testing.T) {
	f := &fakeStages{orphans: []map[string]any{
		stageNode("st-9", "zeta", "2026-10-16T19:26:07.357145+00:00", "", ""),
		stageNode("st-8", "alpha", "2026-10-16T19:26:08.000001+00:00", "2026-10-16T19:00:00+00:00", ""),
	}}
	got, err := f.reader(t).Orphans(ctx10s(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Label != "alpha" || deref(got[0].At) != "2026-10-16T19:00:00+00:00" ||
		got[1].Label != "zeta" || got[1].At != nil || got[1].LabelWrittenAt != "2026-10-16T19:26:07.357145+00:00" {
		t.Errorf("orphans = %+v", got)
	}
	if asked := f.asked("OrphanStages"); len(asked) != 1 {
		t.Errorf("asked OrphanStages %d times, want once", len(asked))
	}
}

// A branch's point of origin and its creation are kept verbatim, in Infrahub's own Z
// layout; a branch Infrahub does not hold is nil with no error.
func TestStageReaderReadsTheBranch(t *testing.T) {
	f := &fakeStages{branches: []map[string]any{{
		"name": "change-1", "branched_from": "2026-10-16T19:22:50.878965Z", "created_at": "2026-10-16T19:22:50.878867Z",
	}}}
	r := f.reader(t)
	got, err := r.Branch(ctx10s(t), "change-1")
	if err != nil {
		t.Fatal(err)
	}
	want := BranchInfo{Name: "change-1", BranchedFrom: "2026-10-16T19:22:50.878965Z", CreatedAt: "2026-10-16T19:22:50.878867Z"}
	if got == nil || *got != want {
		t.Errorf("branch = %+v, want %+v", got, want)
	}
	absent, err := r.Branch(ctx10s(t), "gone")
	if err != nil || absent != nil {
		t.Errorf("an absent branch = %+v, %v; want nil, nil", absent, err)
	}
}

// The validators are read pinned at the `at` given, passed verbatim and URL encoded (an
// unencoded "+" is read as a space), and the latest completed_at value wins, compared
// as times rather than strings; a validator still running is skipped, and none
// completed is "". With no `at`, none is sent.
func TestStageReaderReadsValidationsPinned(t *testing.T) {
	const at = "2026-10-16T19:36:12.298111+00:00"
	f := &fakeStages{validators: []map[string]any{
		validatorNode("2026-10-16T19:35:52.068456+00:00"),
		// Lexically after the first, an hour before it.
		validatorNode("2026-10-16T19:35:53.000000+01:00"),
		validatorNode("2026-10-16T19:36:05.1Z"),
		validatorNode(""),
	}}
	r := f.reader(t)
	got, err := r.Validations(ctx10s(t), "pc-1", at)
	if err != nil {
		t.Fatal(err)
	}
	if got != "2026-10-16T19:36:05.1Z" {
		t.Errorf("latest completed_at = %q, want the Z stamp, the latest instant, verbatim", got)
	}
	asked := f.asked("ArtifactValidations")
	if len(asked) != 1 {
		t.Fatalf("asked %d times, want once", len(asked))
	}
	if asked[0].RawQuery != "at="+url.QueryEscape(at) || !strings.Contains(asked[0].RawQuery, "%2B00%3A00") {
		t.Errorf("query string %q, want at= the stamp URL encoded", asked[0].RawQuery)
	}
	if q, _ := url.ParseQuery(asked[0].RawQuery); q.Get("at") != at {
		t.Errorf("at decoded to %q, want %q verbatim", q.Get("at"), at)
	}
	if ids, _ := asked[0].Variables["id"].(string); ids != "pc-1" {
		t.Errorf("id = %v, want pc-1", asked[0].Variables["id"])
	}

	f.validators = []map[string]any{validatorNode("")}
	f.requests = nil
	none, err := r.Validations(ctx10s(t), "pc-1", "")
	if err != nil || none != "" {
		t.Errorf("no validator completed: %q, %v; want \"\", nil", none, err)
	}
	if asked := f.asked("ArtifactValidations"); len(asked) != 1 || asked[0].RawQuery != "" {
		t.Errorf("an unpinned read sent %q", asked[0].RawQuery)
	}
}

// The reader names no branch: the schema endpoint and GraphQL are asked on their unnamed
// paths, with no query string but the validators' `at`, so the default branch answers
// whatever it is called. The credential goes in the header, as a branch read's does.
func TestStageReaderNamesNoBranch(t *testing.T) {
	f := &fakeStages{attributes: StageFields}
	r := f.reader(t)
	if err := r.Check(ctx10s(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := r.ProposedChanges(ctx10s(t), ""); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Orphans(ctx10s(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Branch(ctx10s(t), "change-1"); err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, req := range f.requests {
		paths = append(paths, req.Method+" "+req.Path)
		if req.RawQuery != "" {
			t.Errorf("%s %s carries a query string %q; the reader names no branch", req.Method, req.Path, req.RawQuery)
		}
		if req.Key != "sentinel-token" {
			t.Errorf("%s %s was sent without the credential", req.Method, req.Path)
		}
	}
	want := []string{"GET /api/schema", "POST /graphql", "POST /graphql", "POST /graphql"}
	if !slices.Equal(paths, want) {
		t.Errorf("requests = %v, want %v", paths, want)
	}
}

// An unreachable Infrahub, a refused credential and a non-200 are errors that carry no
// credential, even from a server that quotes the request's own header back (M1's
// echoing-server shape). A refused credential names the variable to fix, and a pinned
// read names its instant.
func TestStageReaderKeepsTheCredentialOut(t *testing.T) {
	echo := func(status int) string {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"errors":["rejected key ` + r.Header.Get("X-INFRAHUB-KEY") + `"]}`))
		}))
		t.Cleanup(srv.Close)
		return srv.URL
	}
	closed := httptest.NewServer(http.NotFoundHandler())
	closed.Close()

	for _, tc := range []struct {
		name    string
		address string
		want    string
	}{
		{"401", echo(http.StatusUnauthorized), EnvToken},
		{"403", echo(http.StatusForbidden), EnvToken},
		{"500 quoting the key", echo(http.StatusInternalServerError), "<redacted>"},
		{"unreachable", closed.URL, "(the default branch"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := NewStageReader(tc.address, "sentinel-token")
			_, pcErr := r.ProposedChanges(ctx10s(t), "change-1")
			_, orphanErr := r.Orphans(ctx10s(t))
			_, branchErr := r.Branch(ctx10s(t), "change-1")
			_, validationsErr := r.Validations(ctx10s(t), "pc-1", "2026-10-16T19:36:12.298111+00:00")
			for what, err := range map[string]error{
				"Check": r.Check(ctx10s(t)), "ProposedChanges": pcErr, "Orphans": orphanErr,
				"Branch": branchErr, "Validations": validationsErr,
			} {
				if err == nil {
					t.Fatalf("%s: want an error", what)
				}
				var kindErr *StageKindError
				if errors.As(err, &kindErr) {
					t.Errorf("%s: a transport failure reported as the kind's absence: %v", what, err)
				}
				if strings.Contains(err.Error(), "sentinel-token") {
					t.Errorf("%s: the credential reached the error: %v", what, err)
				}
				if !strings.Contains(err.Error(), tc.want) {
					t.Errorf("%s: error %q does not carry %q", what, err, tc.want)
				}
			}
			if !strings.Contains(validationsErr.Error(), "at 2026-10-16T19:36:12.298111+00:00") {
				t.Errorf("a pinned read's error does not name its instant: %v", validationsErr)
			}
		})
	}
}

// The reader is built from the variables a branch read uses, and refuses alike when one
// is unset.
func TestStageReaderFromEnv(t *testing.T) {
	t.Setenv(EnvAddress, "")
	t.Setenv(EnvToken, "t")
	if _, err := StageReaderFromEnv(); err == nil || err.Error() != EnvAddress+" is not set" {
		t.Errorf("address unset: %v", err)
	}
	t.Setenv(EnvAddress, "http://infrahub.invalid/")
	t.Setenv(EnvToken, "")
	if _, err := StageReaderFromEnv(); err == nil || err.Error() != EnvToken+" is not set" {
		t.Errorf("token unset: %v", err)
	}
	t.Setenv(EnvToken, "t")
	r, err := StageReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if r.address != "http://infrahub.invalid" {
		t.Errorf("address = %q, want the trailing slash trimmed", r.address)
	}
}

func ptr(s string) *string { return &s }

func deref(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}
