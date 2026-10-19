//go:build contract || fixture

package testsupport

import (
	"encoding/json"
	"fmt"
	"maps"
	"net/http"
	"slices"
	"strings"
	"time"
)

// TestBranchPrefix begins every branch a test opens a proposed change on. Every helper
// here refuses any other branch before it writes, so no test can mark, close or delete
// what an operator's proposed change holds; fylgja-fixture never gains one.
const TestBranchPrefix = "fylgja-test-"

// pollEvery is how often a wait here reads Infrahub again: the pipeline's steps take
// seconds each (research §2.4), so a finer poll only adds load.
const pollEvery = 2 * time.Second

// rebaseWait bounds a rebase, which returned after 67 s on a seeded branch (research
// §2.7); the client's own timeout is shorter, so the call gets its own.
const rebaseWait = 180 * time.Second

// ProposedChangeRow is one proposed change as the harness reads it back.
type ProposedChangeRow struct {
	ID    string
	Name  string
	State string
	Draft bool
}

// StageRow is one stage as the harness reads it back. At is as_of's value, nil when it
// was not written; WrittenAt is label's stamp, which a stage's write gives every
// attribute and its edge alike (research §2.2).
type StageRow struct {
	ID          string
	Label       string
	At          *string
	WrittenAt   string
	Description string
}

// ValidatorRow is one of a proposed change's validators, as its pipeline left it.
type ValidatorRow struct {
	ID          string
	Label       string
	State       string
	Conclusion  string
	CompletedAt string
}

// userPollEvery is how often RunUserChecks reads the user validators again: a user check
// starts 12–15 s after the run-check and lasts up to its own timeout (research §1.3, §1.5),
// so a finer poll only adds load.
const userPollEvery = 5 * time.Second

// UserCheckRow is one user check of a proposed change as the harness reads it back: the
// CoreStandardCheck under a CoreUserValidator, named as its definition is, with its
// validator's state. A validator with no check, as a check Infrahub timed out leaves it
// (research §1.4), reads as one row of its definition's name and its validator's
// conclusion, with no severity and no message.
type UserCheckRow struct {
	Name           string
	Conclusion     string
	Severity       string
	Message        string
	ValidatorState string
}

// CommentRow is one comment on a proposed change, as Infrahub lists them. A comment has no
// stamp and no author (research §1.2), so its text is all there is to tell two apart.
type CommentRow struct {
	ID   string
	Text string
}

// testBranch refuses a branch that is not a test's. The fixture is named first, so the
// refusal says why: it never has a proposed change.
func testBranch(branch string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture has no proposed change", branch)
	}
	if !strings.HasPrefix(branch, TestBranchPrefix) {
		return fmt.Errorf("branch %q is not a test branch: every branch a test proposes from begins %q", branch, TestBranchPrefix)
	}
	return nil
}

// testProposedChange returns a proposed change's source branch once testBranch allows
// it. A helper given an id reads this first, so the guard holds before any write.
func (c *Client) testProposedChange(id string) (string, error) {
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ CoreProposedChange(ids: [%q]) { edges { node { source_branch { value } } } } }`, id))
	if err != nil {
		return "", fmt.Errorf("reading proposed change %s: %w", id, err)
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					Source struct {
						Value string `json:"value"`
					} `json:"source_branch"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreProposedChange"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return "", err
	}
	if len(r.P.Edges) != 1 {
		return "", fmt.Errorf("proposed change %s: %d found, want one", id, len(r.P.Edges))
	}
	branch := r.P.Edges[0].Node.Source.Value
	return branch, testBranch(branch)
}

// OpenProposedChange opens a proposed change from a test branch into main and waits
// until its pipeline has concluded. Creation runs the pipeline, draft or not, and that
// regenerates the branch's artifacts (research §2.4): an intent change made before the
// wait ends could be rendered under a mark meant to precede it.
func (c *Client) OpenProposedChange(branch string, draft bool) (string, error) {
	if err := testBranch(branch); err != nil {
		return "", err
	}
	id, err := c.create("main", "CoreProposedChange", fmt.Sprintf(
		`{name: {value: %q}, source_branch: {value: %q}, destination_branch: {value: "main"}, is_draft: {value: %t}}`,
		branch, branch, draft))
	if err != nil {
		return "", err
	}
	if id == "" {
		return "", fmt.Errorf("opening a proposed change on %s: Infrahub returned no id", branch)
	}
	return id, c.AwaitValidators(id, 180*time.Second)
}

// ValidatorsOf lists a proposed change's validators: one on a bare branch, three on a
// seeded one (research §6.4, §6.5).
func (c *Client) ValidatorsOf(id string) ([]ValidatorRow, error) {
	if _, err := c.testProposedChange(id); err != nil {
		return nil, err
	}
	return c.validators(id)
}

// validators reads a proposed change's validators, with no guard: the waits poll it.
func (c *Client) validators(id string) ([]ValidatorRow, error) {
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ CoreProposedChange(ids: [%q]) { edges { node {
		validations { edges { node {
			id label { value } state { value } conclusion { value } completed_at { value }
		} } }
	} } } }`, id))
	if err != nil {
		return nil, fmt.Errorf("reading proposed change %s's validators: %w", id, err)
	}
	type value struct {
		Value *string `json:"value"`
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					Validations struct {
						Edges []struct {
							Node struct {
								ID          string `json:"id"`
								Label       value  `json:"label"`
								State       value  `json:"state"`
								Conclusion  value  `json:"conclusion"`
								CompletedAt value  `json:"completed_at"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"validations"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreProposedChange"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	if len(r.P.Edges) != 1 {
		return nil, fmt.Errorf("proposed change %s: %d found, want one", id, len(r.P.Edges))
	}
	str := func(v value) string {
		if v.Value == nil {
			return ""
		}
		return *v.Value
	}
	var out []ValidatorRow
	for _, e := range r.P.Edges[0].Node.Validations.Edges {
		n := e.Node
		out = append(out, ValidatorRow{ID: n.ID, Label: str(n.Label), State: str(n.State),
			Conclusion: str(n.Conclusion), CompletedAt: str(n.CompletedAt)})
	}
	return out, nil
}

// AwaitValidators polls until the proposed change's pipeline has concluded: it has a
// validator, every one is completed, and when the branch's devices have artifacts to
// render, an artifact validator is among them. The creation re-renders the branch's
// artifacts inside that validator (research §2.4), and the wait is what keeps an intent
// change that follows from being rendered under a mark meant to precede it. The
// validators alone end too early: Infrahub creates them one after another as the pipeline
// goes, and on a seeded branch Data Integrity completed 20 s after the creation while the
// artifact validator appeared later and completed 63 s after it. Nor do the pipeline's
// tasks end it: a child task is listed only once it starts, two seconds after its parent
// has ended (research §8). None at all is not concluded either: the first validator is
// queued seconds after the creation. A read that fails is read again until the deadline:
// Infrahub has dropped a connection mid-pipeline.
func (c *Client) AwaitValidators(id string, timeout time.Duration) error {
	branch, err := c.testProposedChange(id)
	if err != nil {
		return err
	}
	members, err := c.groupMemberCount(branch)
	if err != nil {
		return err
	}
	deadline := time.Now().Add(timeout)
	last := "no validator yet"
	for {
		if done, saw, err := c.concluded(id, members > 0); err != nil {
			last = err.Error()
		} else if done {
			return nil
		} else if saw != "" {
			last = saw
		}
		if !time.Now().Add(pollEvery).Before(deadline) {
			return fmt.Errorf("proposed change %s: pipeline not concluded within %s (last saw %s)", id, timeout, last)
		}
		time.Sleep(pollEvery)
	}
}

// concluded reports whether a proposed change's pipeline has ended, as AwaitValidators
// judges it, and otherwise what is still open; nothing while it has no validator.
func (c *Client) concluded(id string, renders bool) (bool, string, error) {
	rows, err := c.validators(id)
	if err != nil {
		return false, "", err
	}
	if len(rows) == 0 {
		return false, "", nil
	}
	pending := []string{}
	for _, v := range rows {
		if v.State != "completed" {
			pending = append(pending, fmt.Sprintf("%s %s", v.Label, v.State))
		}
	}
	if len(pending) > 0 {
		return false, "validators " + strings.Join(pending, ", "), nil
	}
	if !renders {
		return true, "", nil
	}
	_, _, rendered, err := c.artifactCompletion(id)
	if err != nil {
		return false, "", err
	}
	if !rendered {
		return false, fmt.Sprintf("%d validator(s) completed, no artifact validator yet", len(rows)), nil
	}
	return true, "", nil
}

// MarkStage writes one stage on a proposed change, on the default branch's GraphQL: the
// kind is branch-agnostic and lives there (D-028, D-045). An empty at leaves as_of
// unwritten, so the stage's at is the moment of this write; mark it after the writes it
// seals and after their generate has moved the artifacts. The stamp returned is label's.
func (c *Client) MarkStage(id, label, at, description string) (stageID, stamp string, err error) {
	if _, err := c.testProposedChange(id); err != nil {
		return "", "", err
	}
	data := fmt.Sprintf(`{label: {value: %q}, proposed_change: {id: %q}`, label, id)
	if at != "" {
		data += fmt.Sprintf(`, as_of: {value: %q}`, at)
	}
	if description != "" {
		data += fmt.Sprintf(`, description: {value: %q}`, description)
	}
	data += "}"
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`mutation { FylgjaStageCreate(data: %s) { ok object { id label { updated_at } } } }`, data))
	if err != nil {
		return "", "", fmt.Errorf("marking stage %s on proposed change %s: %w", label, id, err)
	}
	var r struct {
		Create struct {
			OK     bool `json:"ok"`
			Object struct {
				ID    string `json:"id"`
				Label struct {
					UpdatedAt string `json:"updated_at"`
				} `json:"label"`
			} `json:"object"`
		} `json:"FylgjaStageCreate"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return "", "", err
	}
	if !r.Create.OK || r.Create.Object.ID == "" {
		return "", "", fmt.Errorf("marking stage %s on proposed change %s: mutation returned ok: %t, id %q",
			label, id, r.Create.OK, r.Create.Object.ID)
	}
	return r.Create.Object.ID, r.Create.Object.Label.UpdatedAt, nil
}

// UpdateStage edits a stage's attributes on the default branch's GraphQL, each field
// written as its value: label, as_of or description, a nil value clearing it. The stage's
// proposed change is read first and must be a test branch's, as MarkStage checks it, so no
// test edits an operator's stage; an orphan, which names none, is refused too.
func (c *Client) UpdateStage(id string, fields map[string]any) error {
	if len(fields) == 0 {
		return fmt.Errorf("updating stage %s: no field given", id)
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ FylgjaStage(ids: [%q]) { edges { node { proposed_change { node { id } } } } } }`, id))
	if err != nil {
		return fmt.Errorf("reading stage %s: %w", id, err)
	}
	var r struct {
		S struct {
			Edges []struct {
				Node struct {
					ProposedChange struct {
						Node *struct {
							ID string `json:"id"`
						} `json:"node"`
					} `json:"proposed_change"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaStage"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return err
	}
	if len(r.S.Edges) != 1 {
		return fmt.Errorf("stage %s: %d found, want one", id, len(r.S.Edges))
	}
	pc := r.S.Edges[0].Node.ProposedChange.Node
	if pc == nil {
		return fmt.Errorf("stage %s names no proposed change", id)
	}
	if _, err := c.testProposedChange(pc.ID); err != nil {
		return err
	}
	names := slices.Sorted(maps.Keys(fields))
	data := []string{fmt.Sprintf("id: %q", id)}
	for _, name := range names {
		v, err := json.Marshal(fields[name])
		if err != nil {
			return fmt.Errorf("updating stage %s's %s: %w", id, name, err)
		}
		data = append(data, fmt.Sprintf("%s: {value: %s}", name, v))
	}
	what := fmt.Sprintf("updating stage %s's %s", id, strings.Join(names, ", "))
	raw, err = c.GraphQL("main", fmt.Sprintf(`mutation { FylgjaStageUpdate(data: {%s}) { ok } }`, strings.Join(data, ", ")))
	if err != nil {
		return fmt.Errorf("%s: %w", what, err)
	}
	return okOf(raw, "FylgjaStageUpdate", what)
}

// StagesOf lists a proposed change's stages through its fylgja_stages extension, in
// Infrahub's order (written as_of first), not Fylgja's.
func (c *Client) StagesOf(id string) ([]StageRow, error) {
	if _, err := c.testProposedChange(id); err != nil {
		return nil, err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ CoreProposedChange(ids: [%q]) { edges { node {
		fylgja_stages { edges { node {
			id label { value updated_at } as_of { value } description { value }
		} } }
	} } } }`, id))
	if err != nil {
		return nil, fmt.Errorf("listing proposed change %s's stages: %w", id, err)
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					Stages struct {
						Edges []struct {
							Node struct {
								ID    string `json:"id"`
								Label struct {
									Value     string `json:"value"`
									UpdatedAt string `json:"updated_at"`
								} `json:"label"`
								AsOf struct {
									Value *string `json:"value"`
								} `json:"as_of"`
								Description struct {
									Value *string `json:"value"`
								} `json:"description"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"fylgja_stages"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreProposedChange"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	if len(r.P.Edges) != 1 {
		return nil, fmt.Errorf("proposed change %s: %d found, want one", id, len(r.P.Edges))
	}
	var out []StageRow
	for _, e := range r.P.Edges[0].Node.Stages.Edges {
		n := e.Node
		row := StageRow{ID: n.ID, Label: n.Label.Value, At: n.AsOf.Value, WrittenAt: n.Label.UpdatedAt}
		if n.Description.Value != nil {
			row.Description = *n.Description.Value
		}
		out = append(out, row)
	}
	return out, nil
}

// StagesPresent returns which of ids still read as stages on the default branch, where
// the branch-agnostic kind lives, whatever proposed change they name or none. It writes
// nothing, so it needs no guard: a test asks it of the ids it made.
func (c *Client) StagesPresent(ids []string) ([]string, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	quoted := make([]string, len(ids))
	for i, id := range ids {
		quoted[i] = fmt.Sprintf("%q", id)
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ FylgjaStage(ids: [%s]) { edges { node { id } } } }`, strings.Join(quoted, ", ")))
	if err != nil {
		return nil, fmt.Errorf("reading stages by id: %w", err)
	}
	var r struct {
		S struct {
			Edges []struct {
				Node struct {
					ID string `json:"id"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaStage"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []string
	for _, e := range r.S.Edges {
		out = append(out, e.Node.ID)
	}
	return out, nil
}

// DeleteStagesOf deletes a proposed change's stages and returns how many. It comes before
// the proposed change's own delete, which Infrahub refuses while a stage names it, the
// relationship being required (research §8.8).
func (c *Client) DeleteStagesOf(id string) (int, error) {
	rows, err := c.StagesOf(id)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, s := range rows {
		raw, err := c.GraphQL("main", fmt.Sprintf(`mutation { FylgjaStageDelete(data: {id: %q}) { ok } }`, s.ID))
		if err != nil {
			return n, fmt.Errorf("deleting stage %s of proposed change %s: %w", s.Label, id, err)
		}
		if err := okOf(raw, "FylgjaStageDelete", fmt.Sprintf("deleting stage %s of proposed change %s", s.Label, id)); err != nil {
			return n, err
		}
		n++
	}
	return n, nil
}

// ProposedChangesOf lists every proposed change whose source is a test branch, in every
// state: a closed or canceled one still holds its stages.
func (c *Client) ProposedChangesOf(branch string) ([]ProposedChangeRow, error) {
	if err := testBranch(branch); err != nil {
		return nil, err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ CoreProposedChange(source_branch__value: %q) { edges { node {
		id name { value } state { value } is_draft { value }
	} } } }`, branch))
	if err != nil {
		return nil, fmt.Errorf("listing proposed changes on %s: %w", branch, err)
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					ID   string `json:"id"`
					Name struct {
						Value string `json:"value"`
					} `json:"name"`
					State struct {
						Value string `json:"value"`
					} `json:"state"`
					Draft struct {
						Value bool `json:"value"`
					} `json:"is_draft"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreProposedChange"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	var out []ProposedChangeRow
	for _, e := range r.P.Edges {
		n := e.Node
		out = append(out, ProposedChangeRow{ID: n.ID, Name: n.Name.Value, State: n.State.Value, Draft: n.Draft.Value})
	}
	return out, nil
}

// CloseProposedChange closes a proposed change. Its stages stay and still read through
// it, and the branch may open another (research §2.3).
func (c *Client) CloseProposedChange(id string) error {
	if _, err := c.testProposedChange(id); err != nil {
		return err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`mutation { CoreProposedChangeUpdate(data: {id: %q, state: {value: "closed"}}) { ok } }`, id))
	if err != nil {
		return fmt.Errorf("closing proposed change %s: %w", id, err)
	}
	return okOf(raw, "CoreProposedChangeUpdate", fmt.Sprintf("closing proposed change %s", id))
}

// DeleteProposedChange deletes a proposed change. Delete its stages first: Infrahub
// refuses the delete while a stage names it.
func (c *Client) DeleteProposedChange(id string) error {
	if _, err := c.testProposedChange(id); err != nil {
		return err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(`mutation { CoreProposedChangeDelete(data: {id: %q}) { ok } }`, id))
	if err != nil {
		return fmt.Errorf("deleting proposed change %s: %w", id, err)
	}
	return okOf(raw, "CoreProposedChangeDelete", fmt.Sprintf("deleting proposed change %s", id))
}

// RunCheck asks for a proposed change's artifact checks and waits until its artifact
// validator completes again, returning that completed_at's value. The run re-renders
// the branch's artifacts and re-runs the same validator node even when the bytes come out
// identical, which moves no checksum (research §6.5); its completion is what the
// generation stamp counts (D-046). The value is compared, never its updated_at.
func (c *Client) RunCheck(id string, timeout time.Duration) (string, error) {
	if _, err := c.testProposedChange(id); err != nil {
		return "", err
	}
	before, _, _, err := c.artifactCompletion(id)
	if err != nil {
		return "", err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`mutation { CoreProposedChangeRunCheck(data: {id: %q, check_type: ARTIFACT}) { ok } }`, id))
	if err != nil {
		return "", fmt.Errorf("asking proposed change %s's artifact checks: %w", id, err)
	}
	if err := okOf(raw, "CoreProposedChangeRunCheck", fmt.Sprintf("asking proposed change %s's artifact checks", id)); err != nil {
		return "", err
	}
	deadline := time.Now().Add(timeout)
	last := "no read failed"
	for {
		// A read that fails is read again until the deadline, as AwaitValidators does.
		latest, stamp, done, err := c.artifactCompletion(id)
		if err != nil {
			last = err.Error()
		} else if done && latest.After(before) {
			return stamp, nil
		}
		if !time.Now().Add(pollEvery).Before(deadline) {
			return "", fmt.Errorf("proposed change %s: no artifact validator completed after the run-check within %s (%s)",
				id, timeout, last)
		}
		time.Sleep(pollEvery)
	}
}

// MarkReady sets a proposed change's is_draft to false. It starts nothing (research §1.5):
// a caller that wants the checks to see it ready runs them again.
func (c *Client) MarkReady(id string) error {
	if _, err := c.testProposedChange(id); err != nil {
		return err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`mutation { CoreProposedChangeUpdate(data: {id: %q, is_draft: {value: false}}) { ok } }`, id))
	if err != nil {
		return fmt.Errorf("marking proposed change %s ready for review: %w", id, err)
	}
	return okOf(raw, "CoreProposedChangeUpdate", fmt.Sprintf("marking proposed change %s ready for review", id))
}

// RunUserChecks asks for a proposed change's user checks and waits until each check
// definition Infrahub runs on its source branch has run again to completed, then returns the
// checks as UserChecksOf reads them. Infrahub runs the definitions the source branch sees, as
// they were at its creation (research §1.2, §1.5), of each repository still registered
// (checkDefinitionsOn), so a branch that sees none returns at once with none. Each
// definition's validator is reused across runs and restarted by each (research §1.2), so a
// validator is done only once its started_at has moved past what it
// read before the call and it is completed: a completed one from the run before is not
// this run's. At the bound the failure names each validator not done, a check Infrahub
// timed out leaving its validator in_progress for good (research §1.4). A read that fails is
// read again until the bound, as AwaitValidators does.
func (c *Client) RunUserChecks(id string, timeout time.Duration) ([]UserCheckRow, error) {
	branch, err := c.testProposedChange(id)
	if err != nil {
		return nil, err
	}
	defs, err := c.checkDefinitionsOn(branch)
	if err != nil {
		return nil, err
	}
	before, err := c.userValidators(id)
	if err != nil {
		return nil, err
	}
	started := map[string]string{}
	for _, v := range before {
		started[v.definitionID] = v.startedAt
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`mutation { CoreProposedChangeRunCheck(data: {id: %q, check_type: USER}) { ok } }`, id))
	if err != nil {
		return nil, fmt.Errorf("asking proposed change %s's user checks: %w", id, err)
	}
	if err := okOf(raw, "CoreProposedChangeRunCheck", fmt.Sprintf("asking proposed change %s's user checks", id)); err != nil {
		return nil, err
	}
	if len(defs) == 0 {
		return c.UserChecksOf(id)
	}
	deadline := time.Now().Add(timeout)
	var last string
	for {
		if vs, err := c.userValidators(id); err != nil {
			last = err.Error()
		} else if pending := rerunPending(defs, started, vs); len(pending) == 0 {
			return userCheckRows(vs), nil
		} else {
			last = strings.Join(pending, ", ")
		}
		if !time.Now().Add(userPollEvery).Before(deadline) {
			return nil, fmt.Errorf("proposed change %s: user checks not concluded within %s (last saw %s)", id, timeout, last)
		}
		time.Sleep(userPollEvery)
	}
}

// rerunPending names each definition whose validator has not run again to completed since
// started was read: none yet, not restarted, or in a state other than completed.
func rerunPending(defs []checkDefinition, started map[string]string, vs []userValidator) []string {
	byDefinition := map[string]userValidator{}
	for _, v := range vs {
		byDefinition[v.definitionID] = v
	}
	var pending []string
	for _, d := range defs {
		v, ok := byDefinition[d.id]
		switch {
		case !ok:
			pending = append(pending, d.name+" not started")
		case v.startedAt == "" || v.startedAt == started[d.id]:
			pending = append(pending, d.name+" not restarted")
		case v.state != "completed":
			pending = append(pending, d.name+" "+v.state)
		}
	}
	return pending
}

// UserChecksOf lists a proposed change's user checks, each CoreStandardCheck under a
// CoreUserValidator with its validator's state, sorted by name.
func (c *Client) UserChecksOf(id string) ([]UserCheckRow, error) {
	if _, err := c.testProposedChange(id); err != nil {
		return nil, err
	}
	vs, err := c.userValidators(id)
	if err != nil {
		return nil, err
	}
	return userCheckRows(vs), nil
}

// userCheckRows flattens validators into their checks, a validator with none read as one
// row of its own, sorted by name.
func userCheckRows(vs []userValidator) []UserCheckRow {
	var out []UserCheckRow
	for _, v := range vs {
		if len(v.checks) == 0 {
			out = append(out, UserCheckRow{Name: v.name, Conclusion: v.conclusion, ValidatorState: v.state})
			continue
		}
		for _, ch := range v.checks {
			if ch.Name == "" {
				ch.Name = v.name
			}
			ch.ValidatorState = v.state
			out = append(out, ch)
		}
	}
	slices.SortStableFunc(out, func(a, b UserCheckRow) int { return strings.Compare(a.Name, b.Name) })
	return out
}

// userValidator is one of a proposed change's user validators: its definition, its state
// and its checks.
type userValidator struct {
	definitionID, name           string
	state, conclusion, startedAt string
	checks                       []UserCheckRow
}

// userValidators reads a proposed change's user validators with their checks, with no
// guard: the waits poll it. Validators are read on the default branch, as the artifact
// validators are.
func (c *Client) userValidators(id string) ([]userValidator, error) {
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ CoreUserValidator(proposed_change__ids: [%q]) { edges { node {
		state { value } conclusion { value } started_at { value }
		check_definition { node { id name { value } } }
		checks { edges { node { name { value } conclusion { value } severity { value } message { value } } } }
	} } } }`, id))
	if err != nil {
		return nil, fmt.Errorf("reading proposed change %s's user validators: %w", id, err)
	}
	type value struct {
		Value *string `json:"value"`
	}
	str := func(v value) string {
		if v.Value == nil {
			return ""
		}
		return *v.Value
	}
	var r struct {
		V struct {
			Edges []struct {
				Node struct {
					State      value `json:"state"`
					Conclusion value `json:"conclusion"`
					StartedAt  value `json:"started_at"`
					Definition struct {
						Node *struct {
							ID   string `json:"id"`
							Name value  `json:"name"`
						} `json:"node"`
					} `json:"check_definition"`
					Checks struct {
						Edges []struct {
							Node struct {
								Name       value `json:"name"`
								Conclusion value `json:"conclusion"`
								Severity   value `json:"severity"`
								Message    value `json:"message"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"checks"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreUserValidator"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	out := make([]userValidator, 0, len(r.V.Edges))
	for _, e := range r.V.Edges {
		n := e.Node
		v := userValidator{state: str(n.State), conclusion: str(n.Conclusion), startedAt: str(n.StartedAt)}
		if d := n.Definition.Node; d != nil {
			v.definitionID, v.name = d.ID, str(d.Name)
		}
		for _, ch := range n.Checks.Edges {
			v.checks = append(v.checks, UserCheckRow{Name: str(ch.Node.Name), Conclusion: str(ch.Node.Conclusion),
				Severity: str(ch.Node.Severity), Message: str(ch.Node.Message)})
		}
		out = append(out, v)
	}
	return out, nil
}

// checkDefinition is one check definition a branch sees.
type checkDefinition struct{ id, name string }

// checkDefinitionsOn lists the check definitions Infrahub runs on a branch's proposed
// change: main's as they were at the branch's creation (research §1.5), each of a
// repository that is still registered. Infrahub runs each registered repository's checks as
// the branch sees them, and a repository is branch-agnostic, so a definition whose
// registration was deleted after the branch was made stays on the branch with no
// repository and never runs (015's research §5.5).
func (c *Client) checkDefinitionsOn(branch string) ([]checkDefinition, error) {
	raw, err := c.GraphQL(branch, `{ CoreCheckDefinition { edges { node { id name { value } repository { node { id } } } } } }`)
	if err != nil {
		return nil, fmt.Errorf("listing the check definitions %s sees: %w", branch, err)
	}
	var r struct {
		D struct {
			Edges []struct {
				Node struct {
					ID   string `json:"id"`
					Name struct {
						Value string `json:"value"`
					} `json:"name"`
					Repository struct {
						Node *struct {
							ID string `json:"id"`
						} `json:"node"`
					} `json:"repository"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreCheckDefinition"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	out := make([]checkDefinition, 0, len(r.D.Edges))
	for _, e := range r.D.Edges {
		if e.Node.Repository.Node == nil {
			continue
		}
		out = append(out, checkDefinition{id: e.Node.ID, name: e.Node.Name.Value})
	}
	return out, nil
}

// CommentsOf lists a proposed change's comments through its comments relationship, in
// Infrahub's order.
func (c *Client) CommentsOf(id string) ([]CommentRow, error) {
	if _, err := c.testProposedChange(id); err != nil {
		return nil, err
	}
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ CoreProposedChange(ids: [%q]) { edges { node { comments { edges { node { id text { value } } } } } } } }`, id))
	if err != nil {
		return nil, fmt.Errorf("listing proposed change %s's comments: %w", id, err)
	}
	var r struct {
		P struct {
			Edges []struct {
				Node struct {
					Comments struct {
						Edges []struct {
							Node struct {
								ID   string `json:"id"`
								Text struct {
									Value string `json:"value"`
								} `json:"text"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"comments"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreProposedChange"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	if len(r.P.Edges) != 1 {
		return nil, fmt.Errorf("proposed change %s: %d found, want one", id, len(r.P.Edges))
	}
	var out []CommentRow
	for _, e := range r.P.Edges[0].Node.Comments.Edges {
		out = append(out, CommentRow{ID: e.Node.ID, Text: e.Node.Text.Value})
	}
	return out, nil
}

// AddInterface writes one physical interface on a test branch's device: enabled, not
// management, with no link. It renders nothing: Infrahub regenerates no artifact on its
// own, so the caller generates, and the artifact then names a port the compile may omit
// (research R-14). The fixture is refused, as every change is, and so is a second
// interface of the name on the device.
func (c *Client) AddInterface(branch, device, name string) error {
	if branch == FixtureBranch {
		return fmt.Errorf("branch %s: the fixture is never changed", branch)
	}
	if err := testBranch(branch); err != nil {
		return err
	}
	dev, err := c.deviceID(branch, device)
	if err != nil {
		return err
	}
	present, err := c.ids(branch, "NetworkInterface", fmt.Sprintf(`(device__name__value: %q, name__value: %q)`, device, name))
	if err != nil {
		return err
	}
	if len(present) != 0 {
		return fmt.Errorf("branch %s already holds %s:%s", branch, device, name)
	}
	id, err := c.create(branch, "NetworkInterface", fmt.Sprintf(
		`{name: {value: %q}, iftype: {value: "physical"}, enabled: {value: true}, mgmt_only: {value: false}, device: {id: %q}}`,
		name, dev))
	if err != nil {
		return err
	}
	if id == "" {
		return fmt.Errorf("adding %s:%s on %s: Infrahub returned no id", device, name, branch)
	}
	return nil
}

// artifactCompletion is the latest completed_at value among a proposed change's artifact
// validators, parsed and as Infrahub returned it, zero when none has completed, and
// whether every one of them is completed.
func (c *Client) artifactCompletion(id string) (latest time.Time, stamp string, done bool, err error) {
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ CoreArtifactValidator(proposed_change__ids: [%q]) { edges { node { state { value } completed_at { value } } } } }`, id))
	if err != nil {
		return time.Time{}, "", false, fmt.Errorf("reading proposed change %s's artifact validators: %w", id, err)
	}
	var r struct {
		V struct {
			Edges []struct {
				Node struct {
					State struct {
						Value string `json:"value"`
					} `json:"state"`
					CompletedAt struct {
						Value *string `json:"value"`
					} `json:"completed_at"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreArtifactValidator"`
	}
	if err := json_Unmarshal(raw, &r); err != nil {
		return time.Time{}, "", false, err
	}
	done = len(r.V.Edges) > 0
	for _, e := range r.V.Edges {
		if e.Node.State.Value != "completed" {
			done = false
		}
		if e.Node.CompletedAt.Value == nil || *e.Node.CompletedAt.Value == "" {
			continue
		}
		at, err := time.Parse(time.RFC3339Nano, *e.Node.CompletedAt.Value)
		if err != nil {
			return time.Time{}, "", false, fmt.Errorf("proposed change %s: artifact validator completed_at %q: %w",
				id, *e.Node.CompletedAt.Value, err)
		}
		if at.After(latest) {
			latest, stamp = at, *e.Node.CompletedAt.Value
		}
	}
	return latest, stamp, done, nil
}

// Rebase rebases a test branch on main and waits for it. Afterwards the branch's history
// before the rebase reads as nothing, and branched_from moves to the rebase (research
// §2.7), so every stage marked before it falls before the branch point.
func (c *Client) Rebase(branch string) error {
	if err := testBranch(branch); err != nil {
		return err
	}
	long := *c
	long.HTTP = &http.Client{Timeout: rebaseWait}
	raw, err := long.GraphQL("main", fmt.Sprintf(
		`mutation { BranchRebase(data: {name: %q}, wait_until_completion: true) { ok } }`, branch))
	if err != nil {
		return fmt.Errorf("rebasing %s: %w", branch, err)
	}
	return okOf(raw, "BranchRebase", fmt.Sprintf("rebasing %s", branch))
}

// DeleteTestBranch deletes a test branch and what hangs on it, in order.
func (c *Client) DeleteTestBranch(branch string) error {
	_, _, err := c.DeleteTestBranchCounting(branch)
	return err
}

// DeleteTestBranchCounting deletes each stage of each proposed change whose source is a
// test branch, then those proposed changes, then the branch, and returns how many stages
// and proposed changes went. The order is fixed: Infrahub refuses a proposed change's
// delete while a stage names it (research §8.8), and a branch deleted first cancels its
// open proposed change, which then names a branch that no longer exists (research §2.3).
func (c *Client) DeleteTestBranchCounting(branch string) (stages, proposed int, err error) {
	rows, err := c.ProposedChangesOf(branch)
	if err != nil {
		return 0, 0, err
	}
	for _, p := range rows {
		n, err := c.DeleteStagesOf(p.ID)
		stages += n
		if err != nil {
			return stages, proposed, err
		}
		if err := c.DeleteProposedChange(p.ID); err != nil {
			return stages, proposed, err
		}
		proposed++
	}
	if err := c.DeleteBranch(branch); err != nil {
		return stages, proposed, fmt.Errorf("deleting branch %s: %w", branch, err)
	}
	return stages, proposed, nil
}
