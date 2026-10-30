package server

import (
	"encoding/json"
	"net/http"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// lostOperations are the five operations 020 removes from the core (D-065; FR-002), which
// read Infrahub and are the orchestrator's.
var lostOperations = []string{findings.OpTwinRehearse, findings.OpStageList, findings.OpStagePlan, findings.OpIntentRead,
	findings.OpSchemaCheck}

// lostArguments are the five arguments 020 removes from twin.create and twin.step (FR-002),
// each of which named intent the server read.
var lostArguments = []string{"branch", "at", "stage", "scope", "probes"}

// Each lost operation's path is 404 as a path version 1 has no operation at: without
// Fylgja-Api-Versions, since its version is served, the problem body's sentence saying
// nothing was read or done, logged as no operation, and no operation runs, the workflow
// service, containerlab and docker never touched (US2 scenario 1; SC-003). Its arguments,
// whatever they are, are never read.
func TestTheLostOperationsAreNoOperation(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	for _, op := range lostOperations {
		if slices.Contains(api.Operations, op) {
			t.Errorf("api.Operations still names %s", op)
		}
		if _, ok := operationArgs[op]; ok {
			t.Errorf("operationArgs still names %s", op)
		}
		if _, ok := handlers[op]; ok {
			t.Errorf("handlers still names %s", op)
		}
		for _, body := range []string{`{}`, `{"render":"text","args":{"branch":"change-1","scope":"tag:fylgja"}}`} {
			resp, raw := post(t, nil, srv.URL+api.Path(op), testToken, body, nil)
			if resp.StatusCode != http.StatusNotFound {
				t.Errorf("%s %s: status %d, want 404", op, body, resp.StatusCode)
			}
			if got := resp.Header.Get(api.HeaderVersions); got != "" {
				t.Errorf("%s: %s %q, want none: version 1 is served", op, api.HeaderVersions, got)
			}
			if got := resp.Header.Get(api.HeaderVersion); got != api.Version {
				t.Errorf("%s: %s %q, want %s", op, api.HeaderVersion, got, api.Version)
			}
			wantNoOperation(t, op, raw)
			satisfies(t, problem, raw, op)
		}
	}
	if n := calls.Load(); n != 0 {
		t.Errorf("%d operations ran for the lost paths", n)
	}
	waitForLog(t, log, "operation=unknown", "outcome=not_found", "level=WARN")
	for _, op := range lostOperations {
		if strings.Contains(log.String(), "operation="+op) {
			t.Errorf("the log names %s, which is no operation of version 1:\n%s", op, log.String())
		}
	}
}

// Each lost argument on twin.create and twin.step is refused as any argument not taken: 400,
// "takes no argument", before any guard runs and before the answer begins, beside a snapshot
// or alone, with or without a file under its path (US2 scenario 2; SC-003).
func TestTheLostArgumentsAreNotTaken(t *testing.T) {
	_, srv, _, calls := testServer(t, answered)
	snapshot, _ := json.Marshal(strings.Repeat("6a", 32))
	for _, op := range []string{findings.OpTwinCreate, findings.OpTwinStep} {
		for _, name := range lostArguments {
			if _, ok := operationArgs[op][name]; ok {
				t.Errorf("operationArgs[%s] still takes %s", op, name)
			}
			for _, body := range []string{
				`{"args":{"` + name + `":"x"}}`,
				`{"render":"text","args":{"snapshot":` + string(snapshot) + `,"` + name + `":"x"}}`,
				`{"args":{"` + name + `":"p.json"},"files":[{"path":"p.json","data":""}]}`,
			} {
				resp, raw := post(t, nil, srv.URL+api.Path(op), testToken, body, nil)
				var p api.Problem
				want := "the request is not one: " + op + " takes no argument \"" + name + "\""
				if err := json.Unmarshal(raw, &p); err != nil || resp.StatusCode != http.StatusBadRequest || p.Message != want {
					t.Errorf("%s %s: status %d, body %s; want 400 saying %q", op, body, resp.StatusCode, raw, want)
				}
			}
		}
	}
	if n := calls.Load(); n != 0 {
		t.Errorf("%d operations ran", n)
	}
}

// A served create or step takes snapshot alone of what names its intent, and the rest of
// what it took before 020 (FR-002).
func TestCreateAndStepTakeASnapshotAlone(t *testing.T) {
	for op, want := range map[string][]string{
		findings.OpTwinCreate: {"detach", "dry_run", "snapshot"},
		findings.OpTwinStep:   {"allow_restart", "detach", "dry_run", "snapshot", "wait"},
	} {
		var got []string
		for name := range operationArgs[op] {
			got = append(got, name)
		}
		if slices.Sort(got); !slices.Equal(got, want) {
			t.Errorf("%s takes %v, want %v", op, got, want)
		}
	}
}
