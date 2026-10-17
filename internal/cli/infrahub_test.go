package cli

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// fakeInfrahub answers what a command given --stage, stage list or stage plan asks of
// Infrahub, in the shapes Infrahub 1.11.2 answers them (014): the default branch's schema,
// its open proposed changes with their stages, the orphaned stages, a branch's point of
// origin and a proposed change's artifact validators on the unnamed endpoints; and each
// branch's read — its schema, GraphQL, its stamps and the object store — from a CTM, with
// the fixture's schema hash. The fixture branch reads as testdata/ctm/three-node.json, so a
// read of it at the fixture's at is the fixture itself; main reads as the fixture too until
// a test says otherwise; and any other branch a test gives it reads the same way from a CTM
// of the test's. The branch half is internal/intent's fake (conformance_test.go) and the
// stage half its stages_test.go's, which this package cannot import; like them it speaks
// Infrahub's wire format, so a change to how a command asks is caught as a request it
// cannot answer.
type fakeInfrahub struct {
	t       *testing.T
	fixture ctm.CTM
	// kind is the stage kind's attributes on the default branch's schema; nil is the kind
	// absent. noRelationship drops the kind's proposed_change, and noExtension drops
	// CoreProposedChange's fylgja_stages, each a kind-absent case of its own.
	kind                        []string
	noRelationship, noExtension bool
	// defaultStatus, when set, is how the default branch's schema answers instead: an
	// Infrahub that stopped answering there.
	defaultStatus int
	// schemaStatus, for a branch it names, is how that branch's schema answers instead,
	// while its GraphQL still does: a read that cannot run past a resolution that did.
	schemaStatus map[string]int
	// changes are the proposed changes served on the unnamed GraphQL endpoint, open or
	// not, each with its marks, its branch's point of origin and its validators.
	changes []*fakeChange
	// orphans are the stages whose proposed change was deleted under them.
	orphans []fakeStage
	// gone names branches the Branch query answers [] for: deleted, though a proposed
	// change still names them.
	gone map[string]bool
	// branches are read beside the fixture's, each its own CTM under its own name, with
	// the fixture's schema hash; a device's artifact is served from the CTM it was read
	// from (M11: a step's target renders artifacts of its own). main is one of them.
	branches map[string]*ctm.CTM
	// versions, when a branch has them, are what it reads at an at in place of branches:
	// the latest version whose Since is not after the at, and the last one unpinned. Each
	// version's Since is every stamp the branch answers while it is in force, so the head
	// of a versioned branch reads its last version (014: a step between two stages of one
	// branch reads two intents).
	versions map[string][]fakeVersion
	// contractless names branches whose contract node is absent: the read refuses them
	// as contract.node.missing.
	contractless map[string]bool
	// stamps overrides a device's stamps on a branch, keyed "<branch>/<device>": an intent
	// written after its artifact is a stale artifact (D-046).
	stamps map[string]fakeDeviceStamps

	mu      sync.Mutex
	served  []fakeRequest
	storage map[string]string
}

// fakeRequest is one request as the fake saw it.
type fakeRequest struct {
	Method, Path, Query, Operation string
	// Variables are the GraphQL request's variables, as sent.
	Variables map[string]any
}

// fakeChange is one proposed change as the fake serves it.
type fakeChange struct {
	ID, Name, Branch, Destination, State string
	Draft                                bool
	Stages                               []fakeStage
	// BranchedFrom and CreatedAt are its source branch's, as the Branch query answers
	// them; a rebase moves BranchedFrom and not CreatedAt.
	BranchedFrom, CreatedAt string
	// Validated are its artifact validators' completed_at values; one later than a
	// pinned read's at is served as not yet completed, "" as never completed.
	Validated []string
}

// fakeStage is one mark: WrittenAt is its label's updated_at ("" a null one, which no
// Infrahub was seen to answer and the resolution refuses), At its as_of ("" unwritten).
type fakeStage struct {
	ID, Label, WrittenAt, At, Description string
}

// fakeVersion is one intent of a versioned branch, in force from Since.
type fakeVersion struct {
	Since string
	CTM   *ctm.CTM
}

// fakeDeviceStamps is one device's stamps in place of its branch's: Intent every stamp of
// its own intent (its attributes, its platform edge, its interfaces), Artifact its
// artifacts' checksum.updated_at ("" a null one), and Link the stamp of each endpoints edge
// joining one of its interfaces to a link ("" the branch's): an edit of the device alone
// leaves its links as they were, and a re-cabling moves the intent of every device on the
// link (R-07).
type fakeDeviceStamps struct {
	Intent, Artifact, Link string
}

// The fake's clock: main last written before the branch point, the branch created and
// branched there, its intent and artifacts written after, and its head one microsecond
// after that.
const (
	fakeMainWritten  = "2026-10-16T07:00:00.000000+00:00"
	fakeBranchedFrom = "2026-10-16T08:00:00.000000+00:00"
	fakeWritten      = "2026-10-16T09:00:00.000000+00:00"
	fakeHeadAt       = "2026-10-16T09:00:00.000001+00:00"
	fakeMarkedAt     = "2026-10-16T10:00:00.000000+00:00"
)

// newFakeInfrahub serves the fixture branch, main as the fixture, and the stage kind with
// every attribute and both relationships, holding no proposed change.
func newFakeInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	raw, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeInfrahub{t: t, kind: intent.StageFields}
	if err := json.Unmarshal(raw, &f.fixture); err != nil {
		t.Fatal(err)
	}
	main := f.fixture
	f.branches = map[string]*ctm.CTM{"main": &main}
	return f
}

// fakeToken is the credential the fake's callers are given: a sentinel no output may
// carry (Constitution X).
const fakeToken = "sentinel-stage-token"

// start serves the fake and points the process environment at it, as the operator's shell
// would.
func (f *fakeInfrahub) start() *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	f.t.Cleanup(srv.Close)
	f.t.Setenv(intent.EnvAddress, srv.URL)
	f.t.Setenv(intent.EnvToken, fakeToken)
	return srv
}

// change adds an open proposed change on branch to main, named "change <id>", branched
// and created at fakeBranchedFrom, holding stages; the branch reads as the fixture unless
// a test has given it a CTM or versions already. It returns the change for a test to edit.
func (f *fakeInfrahub) change(id, branch string, stages ...fakeStage) *fakeChange {
	if _, ok := f.branches[branch]; !ok && f.versions[branch] == nil && branch != f.fixture.Envelope.Branch {
		c := f.fixture
		if f.branches == nil {
			f.branches = map[string]*ctm.CTM{}
		}
		f.branches[branch] = &c
	}
	pc := &fakeChange{ID: id, Name: "change " + id, Branch: branch, Destination: "main", State: "open",
		Stages: stages, BranchedFrom: fakeBranchedFrom, CreatedAt: fakeBranchedFrom}
	f.changes = append(f.changes, pc)
	return pc
}

// mark is a stage labelled label, written at fakeMarkedAt, with as_of at ("" unwritten).
func mark(id, label, at, description string) fakeStage {
	return fakeStage{ID: id, Label: label, WrittenAt: fakeMarkedAt, At: at, Description: description}
}

// requests is every request served so far.
func (f *fakeInfrahub) requests() []fakeRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeRequest(nil), f.served...)
}

func (f *fakeInfrahub) serve(w http.ResponseWriter, r *http.Request) {
	seen := fakeRequest{Method: r.Method, Path: r.URL.Path, Query: r.URL.RawQuery}
	if r.Method == http.MethodPost {
		var req struct {
			OperationName string         `json:"operationName"`
			Variables     map[string]any `json:"variables"`
		}
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &req); err != nil {
			f.t.Errorf("GraphQL request is not JSON: %v", err)
		}
		seen.Operation, seen.Variables = req.OperationName, req.Variables
	}
	f.mu.Lock()
	f.served = append(f.served, seen)
	f.mu.Unlock()
	at := r.URL.Query().Get("at")

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		// The default branch's schema carries the stage kind or not; a served branch's is
		// the contract's, and a stage is never read from it.
		q := r.URL.Query().Get("branch")
		switch _, known := f.branch(q, ""); {
		case q == "" && f.defaultStatus != 0:
			writeFakeJSON(w, f.defaultStatus, map[string]any{"errors": []map[string]string{{"message": "the default branch is unwell"}}})
		case q == "":
			writeFakeJSON(w, http.StatusOK, map[string]any{"main": "fe9eca98", "nodes": f.defaultNodes()})
		case f.schemaStatus[q] != 0:
			writeFakeJSON(w, f.schemaStatus[q], map[string]any{"errors": []map[string]string{{"message": "the branch's schema is unwell"}}})
		case known:
			writeFakeJSON(w, http.StatusOK, f.branchSchema())
		default:
			writeFakeJSON(w, http.StatusBadRequest, map[string]any{"errors": []map[string]string{{"message": "Branch: " + q + " not found."}}})
		}
	case r.Method == http.MethodPost && r.URL.Path == "/graphql":
		f.serveDefault(w, seen, at)
	case r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, "/graphql/"):
		name := strings.TrimPrefix(r.URL.Path, "/graphql/")
		c, known := f.branch(name, at)
		if !known && (name != "main" || seen.Operation != "IntentStamps") {
			f.t.Errorf("a command sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
			http.Error(w, "unexpected", http.StatusTeapot)
			return
		}
		switch seen.Operation {
		case "ContractVersion":
			edges := []any{map[string]any{"node": map[string]any{"version": fakeValue(ctm.ContractVersion)}}}
			if f.contractless[name] {
				edges = []any{}
			}
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaContract": map[string]any{
				"edges": edges,
			}}})
		case "Devices":
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{
				"FylgjaDevice": f.devicePage(name, at, c)}})
		case "Links":
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaLink": linkPage(c)}})
		case "IntentStamps":
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": f.stampPages(name, at, c)})
		default:
			f.t.Errorf("the read sent GraphQL operation %q on %s, which the fake does not know", seen.Operation, r.URL.Path)
			http.Error(w, "unknown operation", http.StatusTeapot)
		}
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/storage/object/"):
		f.mu.Lock()
		content, ok := f.storage[strings.TrimPrefix(r.URL.Path, "/api/storage/object/")]
		f.mu.Unlock()
		if !ok {
			http.NotFound(w, r)
			return
		}
		_, _ = io.WriteString(w, content)
	default:
		f.t.Errorf("a command sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
		http.Error(w, "unexpected", http.StatusTeapot)
	}
}

// defaultNodes is the default branch's schema: the contract node, the stage kind with its
// attributes and its relationship to its proposed change, and CoreProposedChange with the
// extension, each as far as the fake's switches leave it.
func (f *fakeInfrahub) defaultNodes() []map[string]any {
	nodes := []map[string]any{{"kind": ctm.ContractKind}}
	if f.kind != nil {
		attrs := make([]map[string]any, 0, len(f.kind))
		for _, a := range f.kind {
			attrs = append(attrs, map[string]any{"name": a})
		}
		rels := []map[string]any{}
		if !f.noRelationship {
			rels = append(rels, map[string]any{"name": intent.StageRelationship, "peer": intent.ProposedChangeKind, "cardinality": "one"})
		}
		nodes = append(nodes, map[string]any{"kind": intent.StageKind, "attributes": attrs, "relationships": rels})
	}
	pcRels := []map[string]any{{"name": "source_branch_rel", "peer": "CoreBranch"}}
	if !f.noExtension {
		pcRels = append(pcRels, map[string]any{"name": intent.StageExtension, "peer": intent.StageKind, "cardinality": "many"})
	}
	return append(nodes, map[string]any{"kind": intent.ProposedChangeKind, "relationships": pcRels})
}

// serveDefault answers the default branch's unnamed GraphQL endpoint: the proposed
// changes (open ones, of the source branch when the variable is sent), the orphaned
// stages, a branch's point of origin and, pinned at at, a proposed change's validators.
func (f *fakeInfrahub) serveDefault(w http.ResponseWriter, seen fakeRequest, at string) {
	switch seen.Operation {
	case "ProposedChanges":
		branch, filtered := seen.Variables["branch"].(string)
		var nodes []any
		for _, pc := range f.changes {
			if pc.State != "open" || (filtered && pc.Branch != branch) {
				continue
			}
			stages := make([]any, 0, len(pc.Stages))
			for _, s := range pc.Stages {
				stages = append(stages, fakeStageNode(s, true))
			}
			nodes = append(nodes, map[string]any{
				"id":                 pc.ID,
				"name":               fakeValue(pc.Name),
				"source_branch":      fakeValue(pc.Branch),
				"destination_branch": fakeValue(pc.Destination),
				"state":              fakeValue(pc.State),
				"is_draft":           fakeValue(pc.Draft),
				"fylgja_stages":      fakeEdges(stages),
			})
		}
		page := fakeEdges(nodes)
		page["count"] = len(nodes)
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"CoreProposedChange": page}})
	case "OrphanStages":
		nodes := make([]any, 0, len(f.orphans))
		for _, s := range f.orphans {
			nodes = append(nodes, fakeStageNode(s, false))
		}
		page := fakeEdges(nodes)
		page["count"] = len(nodes)
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaStage": page}})
	case "BranchPoint":
		name, _ := seen.Variables["name"].(string)
		branches := []any{}
		if !f.gone[name] {
			for _, pc := range f.changes {
				if pc.Branch == name {
					branches = append(branches, map[string]any{"name": name, "branched_from": pc.BranchedFrom, "created_at": pc.CreatedAt})
					break
				}
			}
		}
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"Branch": branches}})
	case "ArtifactValidations":
		id, _ := seen.Variables["id"].(string)
		nodes := []any{}
		for _, pc := range f.changes {
			if pc.ID != id {
				continue
			}
			for _, completed := range pc.Validated {
				var value any
				if completed != "" && (at == "" || !fakeAfter(completed, at)) {
					value = completed
				}
				nodes = append(nodes, map[string]any{
					"completed_at": map[string]any{"value": value},
					"definition":   map[string]any{"node": map[string]any{"name": fakeValue("srlinux_device_config")}},
				})
			}
		}
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"CoreArtifactValidator": fakeEdges(nodes)}})
	default:
		f.t.Errorf("a command sent GraphQL operation %q on the default branch, which the fake does not know", seen.Operation)
		http.Error(w, "unknown operation", http.StatusTeapot)
	}
}

// fakeStageNode is one stage as a page of stages answers it: a null updated_at and a null
// as_of where the stage has none, and its description only beside its proposed change.
func fakeStageNode(s fakeStage, described bool) map[string]any {
	var asOf, writtenAt any
	if s.At != "" {
		asOf = s.At
	}
	if s.WrittenAt != "" {
		writtenAt = s.WrittenAt
	}
	n := map[string]any{
		"id":    s.ID,
		"label": map[string]any{"value": s.Label, "updated_at": writtenAt},
		"as_of": map[string]any{"value": asOf, "updated_at": writtenAt},
	}
	if described {
		n["description"] = fakeValue(s.Description)
	}
	return n
}

// fakeAfter reports whether stamp a is later than b, each an RFC 3339 time.
func fakeAfter(a, b string) bool {
	ta, errA := time.Parse(time.RFC3339Nano, a)
	tb, errB := time.Parse(time.RFC3339Nano, b)
	return errA == nil && errB == nil && ta.After(tb)
}

// branch is the CTM a branch reads as at at ("" unpinned): a versioned branch's version in
// force, the fixture's under its own name, else one of branches.
func (f *fakeInfrahub) branch(name, at string) (*ctm.CTM, bool) {
	if v, ok := f.version(name, at); ok {
		return v.CTM, true
	}
	if name == f.fixture.Envelope.Branch {
		return &f.fixture, true
	}
	c, ok := f.branches[name]
	return c, ok
}

// version is a versioned branch's version in force at at: the latest whose Since is not
// after it, the last one unpinned, and the first one for an at before them all.
func (f *fakeInfrahub) version(name, at string) (fakeVersion, bool) {
	vs := f.versions[name]
	if len(vs) == 0 {
		return fakeVersion{}, false
	}
	if at == "" {
		return vs[len(vs)-1], true
	}
	v := vs[0]
	for _, c := range vs[1:] {
		if !fakeAfter(c.Since, at) {
			v = c
		}
	}
	return v, true
}

// stampOf is when a branch read at at says its intent and artifacts were written: its
// version's Since, fakeMainWritten on main and fakeWritten elsewhere.
func (f *fakeInfrahub) stampOf(name, at string) string {
	if v, ok := f.version(name, at); ok {
		return v.Since
	}
	if name == "main" {
		return fakeMainWritten
	}
	return fakeWritten
}

// stampPages is the IntentStamps answer for c read from branch at at: every device's,
// interface's and link's stamp the branch's, but where stamps says otherwise for a device.
// A nil c is a branch holding nothing.
func (f *fakeInfrahub) stampPages(branch, at string, c *ctm.CTM) map[string]any {
	stamp := f.stampOf(branch, at)
	devices, links := []any{}, []any{}
	if c != nil {
		for _, d := range c.Devices {
			own, ok := f.stamps[branch+"/"+d.Name]
			intentAt, artifactAt := stamp, stamp
			if ok {
				intentAt, artifactAt = own.Intent, own.Artifact
			}
			var checksumAt any
			if artifactAt != "" {
				checksumAt = artifactAt
			}
			written := map[string]any{"updated_at": intentAt}
			ifaces := make([]any, 0, len(d.Interfaces))
			for _, in := range d.Interfaces {
				ifaces = append(ifaces, map[string]any{
					"properties": written,
					"node": map[string]any{
						"__typename": "NetworkInterface",
						"name":       map[string]any{"value": in.Name, "updated_at": intentAt},
						"iftype":     written, "mgmt_only": written, "enabled": written,
						"link":   map[string]any{"properties": map[string]any{"updated_at": nil}},
						"parent": map[string]any{"properties": map[string]any{"updated_at": nil}},
					},
				})
			}
			devices = append(devices, map[string]any{
				"__typename": "NetworkDevice",
				"name":       map[string]any{"value": d.Name, "updated_at": intentAt},
				"role":       written,
				"site":       written,
				"platform": map[string]any{"properties": written, "node": map[string]any{
					"__typename": "NetworkPlatform",
					"vendor":     fakeValue(d.Platform.Vendor),
					"nos":        fakeValue(d.Platform.NOS),
					"version":    fakeValue(d.Platform.Version),
					"model":      fakeValue(d.Platform.Model),
				}},
				"interfaces": map[string]any{"edges": ifaces},
				"artifacts": fakeEdges([]any{map[string]any{
					"name":     fakeValue(d.Artifact.Name),
					"checksum": map[string]any{"value": d.Artifact.Checksum, "updated_at": checksumAt},
				}}),
			})
		}
		for _, l := range c.Links {
			eps := make([]any, 0, len(l.Endpoints))
			for _, e := range l.Endpoints {
				intentAt := stamp
				if own, ok := f.stamps[branch+"/"+e.Device]; ok && own.Link != "" {
					intentAt = own.Link
				}
				eps = append(eps, map[string]any{
					"properties": map[string]any{"updated_at": intentAt},
					"node": map[string]any{"__typename": "NetworkInterface", "device": map[string]any{"node": map[string]any{
						"__typename": "NetworkDevice", "name": fakeValue(e.Device),
					}}},
				})
			}
			links = append(links, map[string]any{"__typename": "NetworkLink", "endpoints": map[string]any{"edges": eps}})
		}
	}
	devicePage, linkPage := fakeEdges(devices), fakeEdges(links)
	devicePage["count"], linkPage["count"] = len(devices), len(links)
	return map[string]any{"FylgjaDevice": devicePage, "FylgjaLink": linkPage}
}

// branchSchema is the reference schema as it stands on main since M5, with the fixture's
// schema hash: each generic implemented by its reference kind, the device kind an
// artifact target, and the contract node defined.
func (f *fakeInfrahub) branchSchema() map[string]any {
	generic := func(kind, usedBy string) map[string]any {
		return map[string]any{"kind": kind, "used_by": []string{usedBy}}
	}
	return map[string]any{
		"main": f.fixture.Envelope.SchemaHash,
		"generics": []any{
			generic(ctm.DeviceGeneric, "NetworkDevice"),
			generic("FylgjaInterface", "NetworkInterface"),
			generic("FylgjaLink", "NetworkLink"),
			generic("FylgjaPlatform", "NetworkPlatform"),
			generic(ctm.ArtifactTargetGeneric, "NetworkDevice"),
		},
		"nodes": []any{map[string]any{"kind": ctm.ContractKind}, map[string]any{"kind": "NetworkDevice"}},
	}
}

func writeFakeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func fakeValue(v any) map[string]any { return map[string]any{"value": v} }

func fakeEdges[T any](nodes []T) map[string]any {
	out := make([]any, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, map[string]any{"node": n})
	}
	return map[string]any{"edges": out}
}

// devicePage is one page holding every device of c, read from branch at at, each as the
// reference kind NetworkDevice with its artifact Ready in the object store under the
// branch, the at and its name, so a step's two reads of one branch serve two artifacts.
func (f *fakeInfrahub) devicePage(branch, at string, c *ctm.CTM) map[string]any {
	nodes := make([]any, 0, len(c.Devices))
	for _, d := range c.Devices {
		ifaces := make([]any, 0, len(d.Interfaces))
		for _, in := range d.Interfaces {
			var link any
			if in.Link != "" {
				link = map[string]any{"__typename": "NetworkLink", "id": in.Link}
			}
			var parent any
			if in.Parent != "" {
				parent = map[string]any{"__typename": "NetworkInterface", "name": fakeValue(in.Parent)}
			}
			ifaces = append(ifaces, map[string]any{
				"__typename": "NetworkInterface",
				"id":         d.Name + ":" + in.Name,
				"name":       fakeValue(in.Name),
				"iftype":     fakeValue(in.Iftype),
				"mgmt_only":  fakeValue(in.MgmtOnly),
				"enabled":    fakeValue(in.Enabled == nil || *in.Enabled),
				"parent":     map[string]any{"node": parent},
				"addresses":  fakeEdges[any](nil),
				"link":       map[string]any{"node": link},
			})
		}
		a := d.Artifact
		storageID := "storage-" + branch + "@" + at + "~" + d.Name
		f.mu.Lock()
		if f.storage == nil {
			f.storage = map[string]string{}
		}
		f.storage[storageID] = a.Content
		f.mu.Unlock()
		nodes = append(nodes, map[string]any{
			"__typename": "NetworkDevice",
			"id":         "id-" + d.Name,
			"name":       fakeValue(d.Name),
			"role":       fakeValue(d.Role),
			"site":       fakeValue(d.Site),
			"platform": map[string]any{"node": map[string]any{
				"__typename": "NetworkPlatform",
				"vendor":     fakeValue(d.Platform.Vendor),
				"nos":        fakeValue(d.Platform.NOS),
				"version":    fakeValue(d.Platform.Version),
				"model":      fakeValue(d.Platform.Model),
			}},
			"interfaces": fakeEdges(ifaces),
			"artifacts": fakeEdges([]any{map[string]any{
				"name":         fakeValue(a.Name),
				"status":       fakeValue(intent.StatusReady),
				"content_type": fakeValue(a.ContentType),
				"checksum":     fakeValue(a.Checksum),
				"storage_id":   fakeValue(storageID),
				"definition":   map[string]any{"node": map[string]any{"artifact_name": fakeValue(a.Name)}},
			}}),
		})
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}

func linkPage(c *ctm.CTM) map[string]any {
	nodes := make([]any, 0, len(c.Links))
	for _, l := range c.Links {
		eps := make([]any, 0, len(l.Endpoints))
		for _, e := range l.Endpoints {
			eps = append(eps, map[string]any{
				"__typename": "NetworkInterface",
				"name":       fakeValue(e.Interface),
				"device": map[string]any{"node": map[string]any{
					"__typename": "NetworkDevice", "name": fakeValue(e.Device),
				}},
			})
		}
		nodes = append(nodes, map[string]any{"__typename": "NetworkLink", "id": l.ID, "endpoints": fakeEdges(eps)})
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}
