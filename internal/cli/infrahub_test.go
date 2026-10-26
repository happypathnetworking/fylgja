package cli

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeInfrahub answers what a command given --stage, stage list or stage plan asks of
// Infrahub, in the shapes Infrahub 1.11.2 answers them (014): the default branch's schema,
// its open proposed changes with their stages, the orphaned stages, a branch's point of
// origin and a proposed change's artifact validators on the unnamed endpoints; and each
// branch's read — its schema, GraphQL, its stamps and the object store — from a CTM, with
// the fixture's schema hash. The read is answered in the schema library's kinds (017
// research §1.6): each device of the CTM a DcimDevice tagged fylgja, on its package's
// platform and manufacturer, each interface an InterfacePhysical, each link a DcimCable
// labelled with its id. The stamps are still the generics' until 017's T047. The fixture branch reads as testdata/ctm/three-node.json, so a
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
	// schemaMutations, for a branch it names, changes that branch's schema document
	// before it is served: a branch whose DCIM is not the library's (017).
	schemaMutations map[string]func(doc map[string]any)
	// changes are the proposed changes served on the unnamed GraphQL endpoint, open or
	// not, each with its marks, its branch's point of origin and its validators.
	changes []*fakeChange
	// orphans are the stages their proposed change no longer names (D-047).
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
	// untagged names branches none of whose devices carries the scope's tag, main holding no
	// network above all: the device query answers none, and the read refuses it
	// scope.empty. Their stamps are their CTM's as before.
	untagged map[string]bool
	// stamps overrides a device's stamps on a branch, keyed "<branch>/<device>": an intent
	// written after its artifact is a stale artifact (D-046).
	stamps map[string]fakeDeviceStamps
	// events are each branch's event log, newest first, served on the unnamed endpoint:
	// a removal moves no stamp, and its event is how a stage sees it (D-048). A branch
	// with none has an empty log.
	events map[string][]fakeEvent

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

// fakeEvent is one node's write in a branch's log: Name and At as Infrahub names and
// stamps it, its primary node's Kind and ID, the Attrs it changed, and the Peers of the
// one relationship Rel it changed. A node's id is the one the read and the stamps serve:
// a device's "id-<device>" (fakeDeviceID), its port's "<device>:<interface>", a link's
// cable's "cable-<link>".
type fakeEvent struct {
	Name, At, Kind, ID, Rel string
	Attrs, Peers            []string
}

// fakeVersion is one intent of a versioned branch, in force from Since.
type fakeVersion struct {
	Since string
	CTM   *ctm.CTM
}

// fakeDeviceStamps is one device's stamps in place of its branch's: Intent every stamp of
// its own intent (the node_metadata of the device, its platform, its manufacturer and its
// interfaces), Artifact its artifacts' checksum.updated_at ("" a null one), and Link the
// node_metadata of each cable one of its ports is an end of ("" the branch's): an edit of
// the device alone leaves its cables as they were, and a re-cabling moves the intent of
// every device on the cable (017 research R-10).
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
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(f.branchSchema(q))
		default:
			writeFakeJSON(w, http.StatusBadRequest, map[string]any{"errors": []map[string]string{{"message": "Branch: " + q + " not found."}}})
		}
	case r.Method == http.MethodPost && r.URL.Path == "/graphql":
		f.serveDefault(w, seen, at)
	case r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, "/graphql/"):
		name := strings.TrimPrefix(r.URL.Path, "/graphql/")
		c, known := f.branch(name, at)
		if !known && (name != "main" || seen.Operation != "IntentStamps" && seen.Operation != "PortStamps") {
			f.t.Errorf("a command sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
			http.Error(w, "unexpected", http.StatusTeapot)
			return
		}
		switch seen.Operation {
		case "Devices":
			var devices *ctm.CTM
			if tag, _ := seen.Variables["tag"].(string); tag == fakeTag && !f.untagged[name] {
				devices = c
			}
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{
				"DcimDevice": f.devicePage(name, at, devices)}})
		case "Ports":
			ids, _ := seen.Variables["devices"].([]any)
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"InterfacePhysical": f.portPage(c, ids)}})
		case "IntentStamps":
			var devices *ctm.CTM
			if tag, _ := seen.Variables["tag"].(string); tag == fakeTag && !f.untagged[name] {
				devices = c
			}
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{
				"DcimDevice": f.stampPage(name, at, devices)}})
		case "PortStamps":
			ids, _ := seen.Variables["devices"].([]any)
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{
				"InterfacePhysical": f.portStampPage(name, at, c, ids)}})
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

// defaultNodes is the default branch's schema: the stage kind with its attributes and its
// relationship to its proposed change, and CoreProposedChange with the extension, each as
// far as the fake's switches leave it.
func (f *fakeInfrahub) defaultNodes() []map[string]any {
	nodes := []map[string]any{}
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
	case "IntentEvents":
		branch, _ := seen.Variables["branch"].(string)
		limit, _ := seen.Variables["limit"].(float64)
		offset, _ := seen.Variables["offset"].(float64)
		log := f.events[branch]
		nodes := []any{}
		for i := int(offset); i < len(log) && i < int(offset+limit); i++ {
			ev := log[i]
			attrs, rels := []any{}, []any{}
			for _, a := range ev.Attrs {
				attrs = append(attrs, map[string]any{"name": a})
			}
			for _, p := range ev.Peers {
				rels = append(rels, map[string]any{"name": ev.Rel, "peer": map[string]any{"id": p}})
			}
			nodes = append(nodes, map[string]any{"__typename": "NodeMutatedEvent", "event": ev.Name, "occurred_at": ev.At,
				"primary_node": map[string]any{"id": ev.ID, "kind": ev.Kind}, "attributes": attrs, "relationships": rels})
		}
		page := fakeEdges(nodes)
		page["count"] = len(log)
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"InfrahubEvent": page}})
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

// stampPage is the IntentStamps answer for c read from branch at at: every device's edge,
// its platform's, its manufacturer's and its interfaces' node_metadata the branch's stamp,
// but where stamps says otherwise for a device, each on its package's pair. A nil c is a
// scope that selects nothing.
func (f *fakeInfrahub) stampPage(branch, at string, c *ctm.CTM) map[string]any {
	stamp := f.stampOf(branch, at)
	edges := []any{}
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
				ifaces = append(ifaces, map[string]any{"node_metadata": written,
					"node": map[string]any{"__typename": "InterfacePhysical", "id": d.Name + ":" + in.Name}})
			}
			pair := f.fakePair(d.Platform.Package)
			edges = append(edges, map[string]any{
				"node_metadata": written,
				"node": map[string]any{
					"id":   fakeDeviceID(d.Name),
					"name": fakeValue(d.Name),
					"platform": map[string]any{"node_metadata": written, "node": map[string]any{
						"id":   "platform-" + d.Platform.Package,
						"name": fakeValue(pair.Platform),
						"manufacturer": map[string]any{"node_metadata": written, "node": map[string]any{
							"id": "manufacturer-" + d.Platform.Package, "name": fakeValue(pair.Manufacturer)}},
					}},
					"interfaces": map[string]any{"edges": ifaces},
					"artifacts": fakeEdges([]any{map[string]any{
						"name":     fakeValue(d.Artifact.Name),
						"checksum": map[string]any{"value": d.Artifact.Checksum, "updated_at": checksumAt},
					}}),
				},
			})
		}
	}
	return map[string]any{"count": len(edges), "edges": edges}
}

// portStampPage is the PortStamps answer for c read from branch at at: every linked
// interface of the devices whose ids are given, as the query's filter asks, each with its
// cable stamped the branch's, or the Link of the device of either of its ends where stamps
// gives one.
func (f *fakeInfrahub) portStampPage(branch, at string, c *ctm.CTM, ids []any) map[string]any {
	stamp := f.stampOf(branch, at)
	links := map[string]ctm.Link{}
	if c != nil {
		for _, l := range c.Links {
			links[l.ID] = l
		}
	}
	nodes := []any{}
	for _, d := range ctmDevices(c) {
		if !slices.Contains(ids, any(fakeDeviceID(d.Name))) {
			continue
		}
		for _, in := range d.Interfaces {
			l, ok := links[in.Link]
			if !ok {
				continue
			}
			cabledAt := stamp
			for _, e := range l.Endpoints {
				if own, ok := f.stamps[branch+"/"+e.Device]; ok && own.Link != "" {
					cabledAt = own.Link
				}
			}
			nodes = append(nodes, map[string]any{
				"device": map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": fakeDeviceID(d.Name)}},
				"connector": map[string]any{"node_metadata": map[string]any{"updated_at": cabledAt},
					"node": map[string]any{"__typename": "DcimCable", "id": "cable-" + l.ID}},
			})
		}
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}

// ctmDevices is c's devices, none for a nil c.
func ctmDevices(c *ctm.CTM) []ctm.Device {
	if c == nil {
		return nil
	}
	return c.Devices
}

// branchSchema is a served branch's schema, encoded, with the fixture's schema hash: the
// library's kinds as the pinned commit loads them (internal/intent/testdata's trimmed
// document of 017's T033), so conformance passes, and the events map an event's kind
// through its used_by. A branch named in schemaMutations is served changed by its
// function: a branch that does not conform.
//
// An unchanged document is encoded once per schema hash: every read the harness serves
// asks for it, and decoding and encoding its 110 kB each time cost the package seconds.
func (f *fakeInfrahub) branchSchema(branch string) []byte {
	hash := f.fixture.Envelope.SchemaHash
	mutate := f.schemaMutations[branch]
	if mutate == nil {
		if b, ok := encodedSchemas.Load(hash); ok {
			return b.([]byte)
		}
	}
	raw, err := os.ReadFile(repoPath("internal", "intent", "testdata", "schema-26336e9.json"))
	if err != nil {
		f.t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		f.t.Fatal(err)
	}
	doc["main"] = hash
	if mutate != nil {
		mutate(doc)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		f.t.Fatal(err)
	}
	if mutate == nil {
		encodedSchemas.Store(hash, b)
	}
	return b
}

// encodedSchemas holds branchSchema's unchanged documents, by schema hash.
var encodedSchemas sync.Map

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

// fakeTag is the tag the harness's server's default scope names (tag:fylgja), which every
// device the fake serves carries.
const fakeTag = "fylgja"

// fakePairs is each package's first manufacturer and platform pair, by its id: the
// shipped packages and every one under testdata/psp/ meant to load, so a CTM's device is
// served on the platform its package matches.
var fakePairs = sync.OnceValues(func() (map[string]psp.Match, error) {
	pkgs, err := psp.Embedded()
	if err != nil {
		return nil, err
	}
	for _, dir := range []string{"lossy", "heterogeneous"} {
		more, err := psp.FromDir(repoPath("testdata", "psp", dir))
		if err != nil {
			return nil, err
		}
		pkgs = append(pkgs, more...)
	}
	out := map[string]psp.Match{}
	for _, p := range pkgs {
		out[p.Platform.ID] = p.Platform.Matches[0]
	}
	return out, nil
})

// fakePair is the platform and manufacturer a CTM's package is served as.
func (f *fakeInfrahub) fakePair(pkg string) psp.Match {
	pairs, err := fakePairs()
	if err != nil {
		f.t.Fatal(err)
	}
	pair, ok := pairs[pkg]
	if !ok {
		f.t.Fatalf("the fake has no platform for package %s", pkg)
	}
	return pair
}

// devicePage is one page holding every device of c, read from branch at at, each a
// DcimDevice on its package's platform with its artifact Ready in the object store under
// the branch, the at and its name, so a step's two reads of one branch serve two
// artifacts. A nil c is a scope that selects nothing.
func (f *fakeInfrahub) devicePage(branch, at string, c *ctm.CTM) map[string]any {
	nodes := []any{}
	if c != nil {
		for _, d := range c.Devices {
			a := d.Artifact
			storageID := "storage-" + branch + "@" + at + "~" + d.Name
			f.mu.Lock()
			if f.storage == nil {
				f.storage = map[string]string{}
			}
			f.storage[storageID] = a.Content
			f.mu.Unlock()
			pair := f.fakePair(d.Platform.Package)
			nodes = append(nodes, map[string]any{
				"id":   fakeDeviceID(d.Name),
				"name": fakeValue(d.Name),
				"platform": map[string]any{"node": map[string]any{
					"name":         fakeValue(pair.Platform),
					"manufacturer": map[string]any{"node": map[string]any{"name": fakeValue(pair.Manufacturer)}},
				}},
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
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}

// fakeDeviceID is a served device's id.
func fakeDeviceID(name string) string { return "id-" + name }

// portPage is the Ports answer for c: every interface of the devices whose ids are given,
// each an InterfacePhysical, the management port by its role and a disabled one by its
// status, and each linked one's cable with both its ends.
func (f *fakeInfrahub) portPage(c *ctm.CTM, ids []any) map[string]any {
	links := map[string]ctm.Link{}
	for _, l := range c.Links {
		links[l.ID] = l
	}
	nodes := []any{}
	for _, d := range c.Devices {
		if !slices.Contains(ids, any(fakeDeviceID(d.Name))) {
			continue
		}
		for _, in := range d.Interfaces {
			role, status := any(nil), any(nil)
			if in.MgmtOnly {
				role = "management"
			}
			if in.Enabled != nil && !*in.Enabled {
				status = "disabled"
			}
			var connector any
			if l, ok := links[in.Link]; ok {
				ends := make([]any, 0, len(l.Endpoints))
				for _, e := range l.Endpoints {
					ends = append(ends, map[string]any{
						"__typename": "InterfacePhysical",
						"id":         e.ID(),
						"name":       fakeValue(e.Interface),
						"device":     map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": fakeDeviceID(e.Device)}},
					})
				}
				endpoints := fakeEdges(ends)
				endpoints["count"] = len(ends)
				connector = map[string]any{"__typename": "DcimCable", "id": "cable-" + l.ID, "label": fakeValue(l.ID),
					"connected_endpoints": endpoints}
			}
			nodes = append(nodes, map[string]any{
				"id":        d.Name + ":" + in.Name,
				"name":      fakeValue(in.Name),
				"role":      fakeValue(role),
				"status":    fakeValue(status),
				"device":    map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": fakeDeviceID(d.Name)}},
				"connector": map[string]any{"node": connector},
			})
		}
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}
