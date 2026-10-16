package intent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/Khan/genqlient/graphql"
)

// The stage kind as this build reads it (014, D-045). A Fylgja-owned concrete kind beside
// the contract, as FylgjaContract is: nobody implements it, and only --stage, stage list
// and stage plan read it. A stage belongs to a proposed change, which is Infrahub's own
// kind, extended by the same file with the stages it holds.
const (
	// StageKind is the kind the reader checks for and lists.
	StageKind = "FylgjaStage"
	// StageSchemaFile is the file that defines the kind and the extension, named by
	// stage.kind.absent and by schema check so an operator knows what to load.
	StageSchemaFile = "schema/fylgja-stage.yaml"
	// ProposedChangeKind is Infrahub's kind a stage belongs to.
	ProposedChangeKind = "CoreProposedChange"
	// StageExtension is the relationship StageSchemaFile adds to ProposedChangeKind.
	StageExtension = "fylgja_stages"
	// StageRelationship is the stage's own side of it, to its proposed change.
	StageRelationship = "proposed_change"
)

// StageFields is every attribute of the kind the build reads. The attribute that
// carries the reference's `at` is as_of, because Infrahub 1.11.2 refuses a
// two-character attribute name.
var StageFields = []string{"label", "as_of", "description"}

// ProposedChange is one open proposed change as Infrahub holds it, with its marks. Its
// Name is the operator's and is never an identity (Infrahub does not keep it unique):
// ID is, and Branch is how Fylgja finds it, one open proposed change per source branch.
type ProposedChange struct {
	ID, Name    string
	Branch      string // source_branch
	Destination string // destination_branch; main in 1.11.2
	State       string
	Draft       bool
	Stages      []Stage
}

// Stage is one mark as Infrahub holds it. Nothing here is resolved: At is the written
// as_of or nil, and LabelWrittenAt is label.updated_at verbatim, the mark's own write
// stamp, which is its `at` when no as_of is written.
type Stage struct {
	ID, Label      string
	LabelWrittenAt string  // label.updated_at, as returned: 2026-10-16T19:26:07.357145+00:00
	At             *string // as_of.value verbatim, nil when unwritten
	Description    string
}

// BranchInfo is a branch's point of origin and its creation, verbatim: the branch
// point's `at` is BranchedFrom, which a rebase moves and CreatedAt does not.
type BranchInfo struct {
	Name, BranchedFrom, CreatedAt string
}

// StageKindError says the default branch's schema cannot serve the stage commands: the
// kind is absent, or it lacks an attribute or the relationship this build reads, or the
// proposed change lacks the extension. Every caller files it as stage.kind.absent naming
// StageSchemaFile, and schema check reports it as information.
type StageKindError struct {
	// Missing names what the kind lacks, the attributes in StageFields' order and then
	// StageRelationship; empty when the kind itself is absent. A list, because schema
	// check's verified.stages.missing is one.
	Missing []string
	// Extension reports that ProposedChangeKind lacks StageExtension.
	Extension bool
}

// Error is the first half of contracts/stage-reference.md's stage.kind.absent message;
// the finding adds what to load.
func (e *StageKindError) Error() string {
	if len(e.Missing) == 0 && !e.Extension {
		return "the default branch's schema has no kind " + StageKind
	}
	var parts []string
	if len(e.Missing) > 0 {
		var attrs []string
		relationship := false
		for _, m := range e.Missing {
			if m == StageRelationship {
				relationship = true
				continue
			}
			attrs = append(attrs, m)
		}
		var lacks []string
		switch len(attrs) {
		case 0:
		case 1:
			lacks = append(lacks, "the attribute "+attrs[0])
		default:
			lacks = append(lacks, "the attributes "+strings.Join(attrs, ", "))
		}
		if relationship {
			lacks = append(lacks, "the relationship "+StageRelationship)
		}
		parts = append(parts, fmt.Sprintf("kind %s on the default branch lacks %s, which this build reads",
			StageKind, strings.Join(lacks, " and ")))
	}
	if e.Extension {
		parts = append(parts, fmt.Sprintf("kind %s on the default branch lacks %s, the extension %s adds",
			ProposedChangeKind, StageExtension, StageSchemaFile))
	}
	return strings.Join(parts, "; ")
}

// StageReader reads proposed changes, their stages and their branches from the default
// branch. It is a second client beside Client, for objects that live on no branch of
// the operator's: it names no branch at all, using Infrahub's unnamed endpoints
// (/api/schema and /graphql), so an installation whose default branch is not called
// main needs nothing of it. Client's Config.Branch stays required; a stage read never
// has one.
//
// It shares Client's transport, redaction and explanation of Infrahub's refusals, so an
// unreachable Infrahub, a refused credential or a non-200 read the same as a branch
// read's, and no credential reaches an error.
type StageReader struct {
	address string
	token   string
	gql     graphql.Client
	http    *http.Client
}

// NewStageReader builds a reader for one Infrahub.
func NewStageReader(address, token string) *StageReader {
	address = strings.TrimRight(address, "/")
	hc := &http.Client{
		Timeout:   60 * time.Second,
		Transport: &authTransport{token: token, base: http.DefaultTransport},
	}
	return &StageReader{
		address: address,
		token:   token,
		gql:     graphql.NewClient(address+"/graphql", hc),
		http:    hc,
	}
}

// StageReaderFromEnv builds a reader from the variables a read uses, and refuses alike
// when one is unset.
func StageReaderFromEnv() (*StageReader, error) {
	address, token, err := envCredentials()
	if err != nil {
		return nil, err
	}
	return NewStageReader(address, token), nil
}

// stagesWhere names what the reader asked, for its errors, as describe names a branch
// read's reference.
const stagesWhere = "(the default branch)"

// Check reads the default branch's schema and requires the kind with every attribute in
// StageFields and its relationship to its proposed change, and the proposed change's
// extension back. It runs before any query: a query for a kind the schema lacks is an
// HTTP 200 whose message names nothing an operator can act on.
func (r *StageReader) Check(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, r.address+"/api/schema", nil)
	if err != nil {
		return err
	}
	resp, err := r.http.Do(req)
	if err != nil {
		return r.wrap(err, "reading the schema", "")
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return r.wrap(err, "reading the schema", "")
	}
	if resp.StatusCode != http.StatusOK {
		return r.wrap(errors.New(explainStatus(resp.StatusCode, body)), "reading the schema", "")
	}
	type relationship struct {
		Name string `json:"name"`
		Peer string `json:"peer"`
	}
	var doc struct {
		Nodes []struct {
			Kind       string `json:"kind"`
			Attributes []struct {
				Name string `json:"name"`
			} `json:"attributes"`
			Relationships []relationship `json:"relationships"`
		} `json:"nodes"`
	}
	if err := json.Unmarshal(body, &doc); err != nil {
		return fmt.Errorf("reading the schema %s: %w", stagesWhere, err)
	}
	has := func(rels []relationship, name, peer string) bool {
		for _, rel := range rels {
			if rel.Name == name && rel.Peer == peer {
				return true
			}
		}
		return false
	}
	var kindErr StageKindError
	found, extension := false, false
	for _, n := range doc.Nodes {
		switch n.Kind {
		case StageKind:
			found = true
			have := map[string]bool{}
			for _, a := range n.Attributes {
				have[a.Name] = true
			}
			for _, f := range StageFields {
				if !have[f] {
					kindErr.Missing = append(kindErr.Missing, f)
				}
			}
			if !has(n.Relationships, StageRelationship, ProposedChangeKind) {
				kindErr.Missing = append(kindErr.Missing, StageRelationship)
			}
		case ProposedChangeKind:
			extension = has(n.Relationships, StageExtension, StageKind)
		}
	}
	// Without the kind there is nothing for the extension to name: the kind's absence is
	// the one thing said.
	if !found {
		return &StageKindError{}
	}
	kindErr.Extension = !extension
	if len(kindErr.Missing) > 0 || kindErr.Extension {
		return &kindErr
	}
	return nil
}

// ProposedChanges reads the open proposed changes, every one when branch is empty or
// the one whose source branch it is, each with its marks, paged as Devices is. They come
// back sorted by branch then id, and each one's marks by label then id, so the output is
// stable whatever the server does; the marks' order as stages is the stages package's,
// by `at`. Only `open` is asked for: a closed, merged or canceled proposed change is not
// visible to Fylgja (FR-009), draft or not.
func (r *StageReader) ProposedChanges(ctx context.Context, branch string) ([]ProposedChange, error) {
	var out []ProposedChange
	for offset := 0; ; offset += pageSize {
		resp, err := ProposedChanges(ctx, r.gql, branch, pageSize, offset)
		if err != nil {
			return nil, r.wrap(err, "reading proposed changes", "")
		}
		page := resp.GetCoreProposedChange()
		for _, edge := range page.GetEdges() {
			n := edge.GetNode()
			pc := ProposedChange{
				ID:          n.GetId(),
				Name:        n.Name.GetValue(),
				Branch:      n.Source_branch.GetValue(),
				Destination: n.Destination_branch.GetValue(),
				State:       n.State.GetValue(),
				Draft:       n.Is_draft.GetValue(),
			}
			for _, se := range n.Fylgja_stages.GetEdges() {
				s := se.GetNode()
				pc.Stages = append(pc.Stages, stageOf(s.GetId(), s.Label.GetValue(), s.Label.GetUpdated_at(),
					s.As_of.GetValue(), s.Description.GetValue()))
			}
			sortStages(pc.Stages)
			out = append(out, pc)
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Branch != out[j].Branch {
			return out[i].Branch < out[j].Branch
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}

// Orphans reads every stage whose proposed change was deleted under it, sorted by label
// then id. Nothing is planned from one; stage list warns of each (stage.orphaned).
func (r *StageReader) Orphans(ctx context.Context) ([]Stage, error) {
	var out []Stage
	for offset := 0; ; offset += pageSize {
		resp, err := OrphanStages(ctx, r.gql, pageSize, offset)
		if err != nil {
			return nil, r.wrap(err, "reading orphaned stages", "")
		}
		page := resp.GetFylgjaStage()
		for _, edge := range page.GetEdges() {
			s := edge.GetNode()
			out = append(out, stageOf(s.GetId(), s.Label.GetValue(), s.Label.GetUpdated_at(), s.As_of.GetValue(), ""))
		}
		if offset+pageSize >= page.GetCount() {
			break
		}
	}
	sortStages(out)
	return out, nil
}

// Branch reads a branch's point of origin and its creation; nil, nil when Infrahub holds
// no branch of that name.
func (r *StageReader) Branch(ctx context.Context, name string) (*BranchInfo, error) {
	resp, err := BranchPoint(ctx, r.gql, name)
	if err != nil {
		return nil, r.wrap(err, "reading branch "+name, "")
	}
	for _, b := range resp.GetBranch() {
		if b.GetName() == name {
			return &BranchInfo{Name: b.GetName(), BranchedFrom: b.GetBranched_from(), CreatedAt: b.GetCreated_at()}, nil
		}
	}
	return nil, nil
}

// Validations reads, pinned at at, when the proposed change's artifact validators last
// completed: the latest completed_at value across them (one per artifact definition),
// "" when none has. at is passed verbatim as the URL's at parameter, as a branch read's
// is, and not at all when empty. The value is read, never its updated_at: pinned, the
// value is the one in force at at and the metadata the current one (research §6.5).
func (r *StageReader) Validations(ctx context.Context, id, at string) (string, error) {
	endpoint := r.address + "/graphql"
	if at != "" {
		endpoint += "?at=" + url.QueryEscape(at)
	}
	resp, err := ArtifactValidations(ctx, graphql.NewClient(endpoint, r.http), id)
	if err != nil {
		return "", r.wrap(err, "reading the artifact validations of proposed change "+id, at)
	}
	var latest string
	var latestTime time.Time
	page := resp.GetCoreArtifactValidator()
	for _, edge := range page.GetEdges() {
		n := edge.GetNode()
		completed := n.Completed_at.GetValue()
		if completed == "" {
			continue // queued or running: not completed at at
		}
		t, err := parseStamp(completed)
		if err != nil {
			return "", fmt.Errorf("reading the artifact validations of proposed change %s %s: %w", id, stagesAt(at), err)
		}
		if latest == "" || t.After(latestTime) {
			latest, latestTime = completed, t
		}
	}
	return latest, nil
}

// stageOf builds one mark from what Infrahub returned. GraphQL types the DateTime
// attribute's value as a String, which decodes a null to "". An operator cannot write
// "" (the kind refuses what is not a time), so "" is unwritten.
func stageOf(id, label, labelWrittenAt, asOf, description string) Stage {
	s := Stage{ID: id, Label: label, LabelWrittenAt: labelWrittenAt, Description: description}
	if asOf != "" {
		s.At = &asOf
	}
	return s
}

func sortStages(stages []Stage) {
	sort.SliceStable(stages, func(i, j int) bool {
		if stages[i].Label != stages[j].Label {
			return stages[i].Label < stages[j].Label
		}
		return stages[i].ID < stages[j].ID
	})
}

// stagesAt names what a reader's request asked: the default branch, at an instant when
// one was sent.
func stagesAt(at string) string {
	if at == "" {
		return stagesWhere
	}
	return "(the default branch at " + at + ")"
}

// wrap is Client.wrap for a read that names no branch: Infrahub's own words, then the
// credential removed.
func (r *StageReader) wrap(err error, what, at string) error {
	return fmt.Errorf("%s %s: %w", what, stagesAt(at), redact(explain(err), r.token))
}
