package findings

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// dataModelRules is the rule table each milestone's design specified, transcribed. It is
// the specification's list, not the code's, which is the point: the test fails both when
// the code drops a rule a milestone promised and when the code grows one no milestone
// named. Rule identifiers are stable API,
// so neither direction is a detail.
var dataModelRules = []string{
	// Conformance.
	"contract.version.mismatch",
	"contract.node.missing",
	"schema.generic.unimplemented",
	// Completeness and intent rules.
	"data.required.missing",
	"device.name.duplicate",
	"platform.unsupported",
	"interface.iftype.unimplemented",
	"interface.mgmt_only.iftype",
	"interface.parent.missing",
	"link.endpoints.count",
	"link.endpoints.same_device",
	"link.endpoint.iftype",
	"interface.unmappable.linked",
	"ctm.devices.empty",
	// Compiler omissions.
	"omit.link.mgmt_only",
	"omit.interface.unmappable",
	"omit.mgmt.extra",
	// Platform support package validation.
	"psp.schema",
	"psp.version.unknown",
	"psp.patterns.placeholders",
	"psp.patterns.breakout",
	"psp.management.collides",
	"psp.identity.duplicate",
	"psp.resources.implausible",
	"psp.readiness.implausible",
	"psp.acquisition.kvm",
	// Operational failures.
	"operation.failed",
	"intent.at.precision",

	// M2's rules. Appended, not interleaved, so M1's list above stays as it was
	// transcribed.
	"psp.readiness.encoding",
	"host.lab.present",
	"host.twin.present",
	"host.memory.exceeded",
	"host.memory.unbudgeted",
	"host.probe.login_unset",
	"host.psp.missing",
	"bundle.invalid",
	"bundle.version.unsupported",
	"bundle.id.mismatch",
	"run.in_flight",
	"run.worker.absent",
	"run.service.unreachable",
	"run.cancelled",
	"stage.failed",
	"deploy.failed",
	"readiness.timeout",
	"record.failed",
	"cleanup.incomplete",

	// M4's rules.
	"follow.interval.invalid",
	"follow.flags.conflict",
	"follow.start.failed",
	"follow.stop.failed",
	"check.skipped",
	"rebuild.failed",
	"follow.stopped",
	"show.service.unreachable",

	// M5's rules. Appended, as M2's and M4's were.
	"schema.artifact_target.missing",
	"artifact.missing",
	"artifact.ambiguous",
	"artifact.not_ready",
	"artifact.content_type.unsupported",
	"artifact.content.unavailable",
	"artifact.checksum.mismatch",
	"push.refused",
	"push.failed",
	"psp.config.artifact_name",
	"psp.config.content_type",
	"psp.config.delivery.unimplemented",
	"psp.config.push.missing",

	// M6's rules. Appended, as M2's, M4's and M5's were.
	"interface.port.collision",
	"interface.breakout.parent_cabled",
	"interface.rule.unmatched",
	"omit.interface.shared",
	"psp.rule.name",
	"psp.management.rule",
	"psp.mappings.invalid",

	// M7's rules. Appended, as M2's, M4's, M5's and M6's were.
	"host.image.absent",
	// added with D-029
	"psp.readiness.await_push_transport",
	"artifact.interface.unrepresented",
	"psp.config.bootstrap_via",

	// M10's rules. Appended, as every milestone's were.
	"waypoint.ref.invalid",
	"waypoint.flags.conflict",
	"waypoint.kind.absent",
	"waypoint.unknown",
	"waypoint.duplicate",
	"waypoint.at.unresolved",
	"waypoint.time.reversed",
	"waypoint.twin.moved",

	// M11's rules. Appended, as every milestone's were; a run in flight is M2's
	// run.in_flight, so it is not here.
	"step.twin.unsteppable",
	"step.twin.diverged",
	"step.target.foreign",
	"step.target.unknown",
	"step.target.current",
	"step.bundle.missing",
	"step.package.merge",
	"step.node.unapplied",
	"step.restart.required",
	"step.diverged",
	"step.sequence.skipped",
	"step.restart.undeclared",

	// M12's rules. Appended; an unread node is operation.failed, and a missing package or an unset
	// login M2's, so none of those is here.
	"verify.host_name",
	"verify.port.enabled",
	"verify.neighbor",
	"verify.record.holds",
	"verify.twin.absent",
	"verify.package.unreadable",
	"verify.wait.invalid",
	"verify.wait.unsettled",

	// M13's rules. Appended; the client's own, and the build line has none.
	"api.unreachable",
	"api.token.refused",
	"api.version.unknown",
	"api.transfer.too_large",
}

// declaredRules reads the Rule* constants out of finding.go's syntax tree rather than
// a hand-kept list, so a constant added to the file cannot escape the comparison.
func declaredRules(t *testing.T) map[string]string {
	t.Helper()
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "finding.go", nil, 0)
	if err != nil {
		t.Fatalf("parsing finding.go: %v", err)
	}
	out := map[string]string{}
	for _, decl := range file.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.CONST {
			continue
		}
		for _, spec := range gen.Specs {
			vs, ok := spec.(*ast.ValueSpec)
			if !ok {
				continue
			}
			for i, name := range vs.Names {
				if !strings.HasPrefix(name.Name, "Rule") || i >= len(vs.Values) {
					continue
				}
				lit, ok := vs.Values[i].(*ast.BasicLit)
				if !ok || lit.Kind != token.STRING {
					continue
				}
				value, err := strconv.Unquote(lit.Value)
				if err != nil {
					t.Fatalf("%s: %v", name.Name, err)
				}
				out[value] = name.Name
			}
		}
	}
	return out
}

func TestEveryDataModelRuleHasAConstant(t *testing.T) {
	declared := declaredRules(t)
	for _, rule := range dataModelRules {
		if _, ok := declared[rule]; !ok {
			t.Errorf("the rule table defines %q; no constant in finding.go carries it", rule)
		}
	}
}

func TestNoConstantIsUnknownToTheDataModel(t *testing.T) {
	want := map[string]bool{}
	for _, rule := range dataModelRules {
		want[rule] = true
	}
	for rule, name := range declaredRules(t) {
		if !want[rule] {
			t.Errorf("%s = %q is declared but the rule table does not name it; "+
				"a rule identifier is API, so add it to the table or drop the constant", name, rule)
		}
	}
}

// Every rule identifier is one the newest findings schema accepts, read from its rule
// pattern rather than copied, so a new identifier needs no schema change (M13's four
// api.* rules are the first to lean on it).
func TestEveryRuleMatchesTheContractPattern(t *testing.T) {
	raw, err := os.ReadFile(newestSchemaPath("findings.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties struct {
			Findings struct {
				Items struct {
					Properties struct {
						Rule struct {
							Pattern string `json:"pattern"`
						} `json:"rule"`
					} `json:"properties"`
				} `json:"items"`
			} `json:"findings"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatal(err)
	}
	pattern := schema.Properties.Findings.Items.Properties.Rule.Pattern
	if pattern == "" {
		t.Fatal("findings.schema.json has no rule pattern; the test is reading the wrong place")
	}
	re := regexp.MustCompile(pattern)
	for rule, name := range declaredRules(t) {
		if !re.MatchString(rule) {
			t.Errorf("%s = %q does not match the contract's rule pattern %s", name, rule, pattern)
		}
	}
}

// Two constants sharing a value would make one of them unreachable in a report.
func TestRuleIdentifiersAreDistinct(t *testing.T) {
	seen := map[string]string{}
	for rule, name := range declaredRules(t) {
		if prior, ok := seen[rule]; ok {
			t.Errorf("%s and %s both carry %q", prior, name, rule)
		}
		seen[rule] = name
	}
}

func compileFindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	const name = "findings.schema.json"
	path := contractPath("001-read-compile", name)
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("opening %s: %v", path, err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", name, err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(name, doc); err != nil {
		t.Fatalf("adding %s: %v", name, err)
	}
	// Compilation is where an unresolvable reference surfaces: a schema that
	// describes every document correctly and cannot itself be loaded is no contract.
	s, err := c.Compile(name)
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load this schema): %v", name, err)
	}
	return s
}

func mustValidate(t *testing.T, s *jsonschema.Schema, doc *Document, label string) {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	mustValidateBytes(t, s, b, label)
}

func mustValidateBytes(t *testing.T, s *jsonschema.Schema, b []byte, label string) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("re-reading emitted JSON: %v", err)
	}
	if err := s.Validate(v); err != nil {
		t.Errorf("%s does not satisfy findings.schema.json:\n%v", label, err)
	}
}

// Every status each command can report must satisfy the contract, not just the happy
// one: an error document is the one produced when things are already going wrong.
func TestEveryOperationRendersAValidDocument(t *testing.T) {
	schema := compileFindingsSchema(t)

	rejected := List{{
		Severity: Rejection,
		Rule:     RuleIftypeUnimplemented,
		Object:   "n1:irb0",
		Message:  `iftype "svi" is reserved in the contract but not implemented at M1`,
	}}
	withLocation := List{{
		Severity: Warning,
		Rule:     RulePSPResourcesImplausible,
		Object:   "nokia_srlinux",
		Message:  "resources look implausible",
		Location: &Location{File: "psp/x.yaml", Line: 12},
	}}

	readOK := NewDocument(OpIntentRead, &Subject{Branch: "fylgja-fixture", CTM: "ctm.json"}, nil)
	readPinned := NewDocument(OpIntentRead,
		&Subject{Branch: "fylgja-fixture", At: "2026-09-14T12:00:00.000000Z", CTM: "ctm.json"}, rejected)

	compileOK := NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/bundle"}, nil)
	compileOK.BundleID = strings.Repeat("ab", 32)

	checkOK := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
	checkOK.Verified = &Verified{
		ContractVersion: "0.2",
		Generics: []GenericKinds{
			{Generic: "FylgjaDevice", Kinds: []string{"NetworkDevice"}},
			{Generic: "FylgjaInterface", Kinds: []string{"NetworkInterface"}},
		},
	}

	cases := []struct {
		label string
		doc   *Document
	}{
		{"intent read ok", readOK},
		{"intent read rejected", readPinned},
		{"intent read at too precise", RuleErrorDocument(OpIntentRead,
			&Subject{Branch: "b", At: "2026-09-14T12:00:00.123456789Z"},
			RuleAtPrecision, "2026-09-14T12:00:00.123456789Z",
			"--at carries 9 fractional digits; Infrahub honours at most six")},
		{"twin compile ok", compileOK},
		{"twin compile rejected", NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/b"}, rejected)},
		{"twin compile error", ErrorDocument(OpCompile, &Subject{Out: "/tmp/b"}, "--out is required")},
		{"schema check ok", checkOK},
		{"psp validate with location", NewDocument(OpPSPValidate, &Subject{Files: []string{"psp/x.yaml"}}, withLocation)},
	}
	for _, c := range cases {
		t.Run(c.label, func(t *testing.T) { mustValidate(t, schema, c.doc, c.label) })
	}
}

// The operation names in the schema's enum and the Op* constants are one list.
func TestOperationConstantsMatchTheContract(t *testing.T) {
	got := []string{OpIntentRead, OpCompile, OpSchemaCheck, OpPSPValidate}
	sort.Strings(got)
	want := []string{"intent.read", "psp.validate", "schema.check", "twin.compile"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Errorf("operations = %v, contract enum = %v", got, want)
	}

	// The newest schema enumerates every operation there is: M4's eight, M10's two,
	// M11's one and M12's one.
	all := []string{OpIntentRead, OpCompile, OpSchemaCheck, OpPSPValidate,
		OpTwinCreate, OpTwinProvision, OpTwinDestroy, OpTwinShow,
		OpWaypointList, OpWaypointPlan, OpTwinStep, OpTwinVerify}
	sort.Strings(all)
	raw, err := os.ReadFile(newestSchemaPath("findings.schema.json"))
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
	enum := schema.Properties.Operation.Enum
	sort.Strings(enum)
	if strings.Join(all, ",") != strings.Join(enum, ",") {
		t.Errorf("operations = %v, contract enum = %v", all, enum)
	}
}

// newestSchemaPath is the current contract's file name, under the module root's
// contracts/. The step, operation and status enums are read from it, since it carries
// observe, twin.verify and nonconforming beside M11's reconcile, twin.step and diverged;
// M4's, M5's and M6's helpers stay their milestones' validators.
func newestSchemaPath(name string) string {
	return contractPath(currentContract, name)
}

// enumOf reads one enum out of a contract file by its path of properties, so each enum
// test below names exactly the list it compares.
func enumOf(t *testing.T, file string, path ...string) []string {
	t.Helper()
	raw, err := os.ReadFile(newestSchemaPath(file))
	if err != nil {
		t.Fatal(err)
	}
	var node map[string]any
	if err := json.Unmarshal(raw, &node); err != nil {
		t.Fatal(err)
	}
	for _, key := range path {
		next, ok := node[key].(map[string]any)
		if !ok {
			t.Fatalf("%s has no %v; the test is reading the wrong place", file, path)
		}
		node = next
	}
	values, ok := node["enum"].([]any)
	if !ok || len(values) == 0 {
		t.Fatalf("%s's %v enumerates nothing; the test is reading the wrong place", file, path)
	}
	out := make([]string, 0, len(values))
	for _, v := range values {
		out = append(out, v.(string))
	}
	sort.Strings(out)
	return out
}

// A status is API: it is the document's status and it decides the exit. The Status
// constants and the contract's enum are one list (M11 adds diverged, M12
// nonconforming).
func TestStatusConstantsMatchTheContract(t *testing.T) {
	all := []string{string(StatusOK), string(StatusRejected), string(StatusError),
		string(StatusFailed), string(StatusUnclean), string(StatusDiverged),
		string(StatusNonconforming)}
	sort.Strings(all)
	enum := enumOf(t, "findings.schema.json", "properties", "status")
	if strings.Join(all, ",") != strings.Join(enum, ",") {
		t.Errorf("statuses = %v, contract enum = %v", all, enum)
	}
}

// The kinds twin show reports and show.schema.json's enum are one list (M11 adds
// diverged).
func TestShowKindConstantsMatchTheContract(t *testing.T) {
	all := []string{ShowKindNone, ShowKindPinned, ShowKindFrozen, ShowKindFromBundle,
		ShowKindFollowing, ShowKindDiverged}
	sort.Strings(all)
	enum := enumOf(t, "show.schema.json", "properties", "kind")
	if strings.Join(all, ",") != strings.Join(enum, ",") {
		t.Errorf("show kinds = %v, contract enum = %v", all, enum)
	}
}

func TestStatusExitCodes(t *testing.T) {
	for _, c := range []struct {
		status Status
		want   int
	}{
		{StatusOK, ExitOK},
		{StatusRejected, ExitRejected},
		{StatusError, ExitError},
	} {
		if got := c.status.ExitCode(); got != c.want {
			t.Errorf("%s.ExitCode() = %d, want %d", c.status, got, c.want)
		}
	}
}

// compileM2FindingsSchema loads M2's copy of the contract, which is additive to M1's.
// M1's helper above stays pointed at M1's copy: M1's documents must keep satisfying the
// contract they were written against.
func compileM2FindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	path := contractPath("002-provision-destroy", "findings.schema.json")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("opening %s: %v", path, err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("m2-findings.schema.json", doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("m2-findings.schema.json")
	if err != nil {
		t.Fatalf("compiling %s: %v", path, err)
	}
	return s
}

// Every document shape the provisioning commands produce satisfies M2's contract,
// failures included: an unclean document is written when the host is already in
// trouble, which is the worst time for it to be unreadable.
func TestM2DocumentsSatisfySchema(t *testing.T) {
	schema := compileM2FindingsSchema(t)
	docs := m2Documents()
	for _, c := range docs {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM6DryRunCounts, dropM7ShowPSP), c.label)
		})
	}

	// The two nulls and the empty list are contract, not accidents of marshalling.
	b, err := json.Marshal(docs[6].doc)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"host_budget_mb":null`) {
		t.Errorf("an unset budget must marshal as null: %s", b)
	}
	if b, _ = json.Marshal(docs[3].doc); !strings.Contains(string(b), `"remaining":[]`) {
		t.Errorf("nothing remaining must marshal as []: %s", b)
	}
	if b, _ = json.Marshal(NewDocument(OpTwinProvision, nil, nil)); strings.Contains(string(b), `"step"`) {
		t.Errorf("a finding with no step must not carry one: %s", b)
	}
}

// labelledDocument is one document a test validates, named for its failure message.
type labelledDocument struct {
	label string
	doc   *Document
}

// m2Documents are the document shapes M2's provisioning commands produce, failures
// included. Indexes 3 (provision failed) and 6 (dry run, budget unset) are read by
// TestM2DocumentsSatisfySchema.
func m2Documents() []labelledDocument {
	id := strings.Repeat("b5", 32)
	observed := "2026-09-15T14:22:12.000000Z"
	budget := 4096

	ok := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, nil)
	ok.BundleID = id
	ok.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/local/twin", RunID: "run-1", ObservedAt: &observed,
		Nodes: []TwinNode{{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9}}}

	var refusal List
	refusal.AddStep(Rejection, StepHostCheck, RuleHostLabPresent, "lab fylgja",
		"lab fylgja exists (3 nodes); fylgja twin destroy clears it")
	rejected := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture"}, refusal)
	rejected.BundleID = id

	unreachable := RuleErrorDocument(OpTwinDestroy, nil, RuleRunServiceUnreachable, "localhost:1",
		"the workflow service did not answer at localhost:1")
	unreachable.Findings[0].Step = StepStart

	var deployFailed List
	deployFailed.AddStep(Rejection, StepDeploy, RuleDeployFailed, "lab fylgja", "clab deploy exited 1")
	failed := NewDocument(OpTwinProvision, &Subject{Bundle: "/tmp/b", RunID: "run-2"}, deployFailed)
	failed.Status = StatusFailed
	failed.BundleID = id
	failed.Cleanup = &CleanupBlock{Teardown: "done", Unstage: "done",
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}

	var incomplete List
	incomplete.AddStep(Rejection, StepTeardown, RuleCleanupIncomplete, "lab fylgja",
		"lab fylgja is still present; clear it with clab destroy --name fylgja --cleanup")
	unclean := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-3"}, incomplete)
	unclean.Status = StatusUnclean
	unclean.Cleanup = &CleanupBlock{Teardown: "failed", Unstage: "done", Remaining: []string{"lab fylgja"}}

	destroyed := NewDocument(OpTwinDestroy, &Subject{RunID: "run-4"}, nil)
	destroyed.Cleanup = &CleanupBlock{Teardown: "nothing", Unstage: "nothing"}

	var unbudgeted List
	unbudgeted.AddStep(Warning, StepHostCheck, RuleHostMemoryUnbudgeted, "host", "sum 6144 MiB; no host budget set")
	dry := NewDocument(OpTwinProvision, &Subject{Bundle: "testdata/golden/three-node"}, unbudgeted)
	dry.BundleID = id
	dry.DryRun = &DryRunBlock{
		Nodes:       []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: "nokia_srlinux", MemoryMB: 2048}},
		MemorySumMB: 2048,
		Host:        DryRunHost{},
		Verdict:     VerdictClear,
	}
	dryBudgeted := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture"}, nil)
	dryBudgeted.DryRun = &DryRunBlock{Nodes: []DryRunNode{}, HostBudgetMB: &budget,
		Host: DryRunHost{LabPresent: true}, Verdict: VerdictRefused}

	return []labelledDocument{
		{"create ok", ok},
		{"create rejected by the host check", rejected},
		{"destroy error", unreachable},
		{"provision failed, cleanup complete", failed},
		{"create unclean", unclean},
		{"destroy ok", destroyed},
		{"dry run, budget unset", dry},
		{"dry run, budget set", dryBudgeted},
	}
}

// Seven statuses, six exit codes, one table (contracts/cli.md).
func TestExitCodes(t *testing.T) {
	for _, c := range []struct {
		status Status
		want   int
	}{
		{StatusOK, 0},
		{StatusRejected, 1},
		{StatusError, 2},
		{StatusFailed, 3},
		{StatusUnclean, 4},
		{StatusDiverged, 4},
		{StatusNonconforming, 5},
	} {
		if got := c.status.ExitCode(); got != c.want {
			t.Errorf("%s.ExitCode() = %d, want %d", c.status, got, c.want)
		}
	}
}

// Text mode puts rejections first and the summary last: the operator reads the top of
// the output, so burying the rejection under a page of info findings would be a
// reporting bug, not a cosmetic one.
func TestTextRenderingPutsRejectionsFirstAndSummaryLast(t *testing.T) {
	doc := NewDocument(OpCompile, nil, List{
		{Severity: Info, Rule: RuleOmitMgmtExtra, Object: "n1:mgmt1", Message: "one management connection per node"},
		{Severity: Rejection, Rule: RuleLinkEndpointsCount, Object: "n1:e1|n2:e1", Message: "link has 1 endpoint"},
		{Severity: Warning, Rule: RulePSPResourcesImplausible, Object: "nokia_srlinux", Message: "implausible"},
	})
	var buf bytes.Buffer
	if err := doc.WriteText(&buf); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimRight(buf.String(), "\n"), "\n")
	if len(lines) != 4 {
		t.Fatalf("got %d lines, want 3 findings + 1 summary:\n%s", len(lines), buf.String())
	}
	if !strings.HasPrefix(lines[0], "rejection ") {
		t.Errorf("first line is %q, want the rejection", lines[0])
	}
	if want := "3 finding(s): 1 rejection, 1 warning, 1 info"; lines[3] != want {
		t.Errorf("summary = %q, want %q", lines[3], want)
	}
}

// JSON mode owns stdout: one document, nothing else (contracts/cli.md).
func TestRenderRoutesByFlag(t *testing.T) {
	doc := NewDocument(OpCompile, nil, List{
		{Severity: Rejection, Rule: RuleDevicesEmpty, Object: "fylgja-fixture", Message: "no devices"},
	})

	var stdout, stderr bytes.Buffer
	if code := Render(doc, &stdout, &stderr, true); code != ExitRejected {
		t.Errorf("exit code = %d, want %d", code, ExitRejected)
	}
	if stderr.Len() != 0 {
		t.Errorf("--json wrote to stderr: %q", stderr.String())
	}
	var round map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &round); err != nil {
		t.Fatalf("stdout is not one JSON document: %v\n%s", err, stdout.String())
	}

	stdout.Reset()
	stderr.Reset()
	if code := Render(doc, &stdout, &stderr, false); code != ExitRejected {
		t.Errorf("exit code = %d, want %d", code, ExitRejected)
	}
	if stdout.Len() != 0 {
		t.Errorf("text mode wrote findings to stdout, which success lines own: %q", stdout.String())
	}
	if !strings.Contains(stderr.String(), RuleDevicesEmpty) {
		t.Errorf("stderr = %q, want the rule named", stderr.String())
	}
}

func m4SchemaPath(name string) string {
	return contractPath("004-walking", name)
}

// compileM4FindingsSchema loads M4's copy of the contract, with the show block's schema
// added under its own $id. M2's helper stays M2's validator.
func compileM4FindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(m4SchemaPath(name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("https://fylgja.dev/schemas/show.schema.json", load("show.schema.json")); err != nil {
		t.Fatal(err)
	}
	if err := c.AddResource("m4-findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("m4-findings.schema.json")
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load it): %v", m4SchemaPath("findings.schema.json"), err)
	}
	return s
}

// Every document shape M4 adds satisfies M4's contract, and every M2 shape still does: the
// schema is additive.
func TestM4DocumentsSatisfySchema(t *testing.T) {
	schema := compileM4FindingsSchema(t)
	for _, c := range m4Documents() {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM5ShowArtifacts, dropM6DryRunCounts, dropM7ShowPSP), c.label)
		})
	}
	for _, c := range m2Documents() {
		t.Run("M2 "+c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM6DryRunCounts, dropM7ShowPSP), c.label)
		})
	}

	// The lists the show block requires are present when empty.
	empty := NewDocument(OpTwinShow, nil, nil)
	empty.Show = &ShowBlock{Kind: ShowKindNone, Service: ShowServiceOK}
	b, err := json.Marshal(empty)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"in_flight":[]`, `"notes":[]`, `"nodes":[]`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("an empty show block must carry %s: %s", want, b)
		}
	}
}

// asEarlier marshals a document as an earlier milestone's schema is asked to validate it:
// with the keys a later milestone always writes taken out again. Every findings.schema.json
// forbids additional properties, so what an earlier schema validates is its own
// milestone's shape; withDryRunArtifacts is the same move in the other direction.
func asEarlier(t *testing.T, doc *Document, drops ...func(doc map[string]any)) []byte {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	for _, drop := range drops {
		drop(generic)
	}
	b, err = json.Marshal(generic)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// dropM5ShowArtifacts removes M5's `artifact` key from every show node it is null on.
// M4's show.schema.json predates the key, and from M5 a show node always carries it,
// null for a node the record does not name (contracts/cli.md).
func dropM5ShowArtifacts(doc map[string]any) {
	show, _ := doc["show"].(map[string]any)
	host, _ := show["host"].(map[string]any)
	nodes, _ := host["nodes"].([]any)
	for _, n := range nodes {
		node, _ := n.(map[string]any)
		if v, ok := node["artifact"]; ok && v == nil {
			delete(node, "artifact")
		}
	}
}

// dropM7ShowPSP removes M7's `psp` key from every show node. Every schema before M7's
// predates it, and from M7 a show node always carries it, null for a node the record does
// not name (M7 contracts/cli.md) — as M5's `artifact` key is.
func dropM7ShowPSP(doc map[string]any) {
	show, _ := doc["show"].(map[string]any)
	host, _ := show["host"].(map[string]any)
	nodes, _ := host["nodes"].([]any)
	for _, n := range nodes {
		node, _ := n.(map[string]any)
		delete(node, "psp")
	}
}

// dropM6DryRunCounts removes M6's two dry_run counts. M2's, M4's and M5's contracts
// predate them, and from M6 a dry run always carries them (M6 contracts/cli.md).
func dropM6DryRunCounts(doc map[string]any) {
	if dry, ok := doc["dry_run"].(map[string]any); ok {
		delete(dry, "lossy_mappings")
		delete(dry, "shared_ports")
	}
}

// m4Documents are the document shapes M4 adds, as m2Documents are M2's: a fixture, so
// that a later milestone's schema can be held to every earlier shape.
func m4Documents() []labelledDocument {
	id := strings.Repeat("89", 32)
	twinID := strings.Repeat("b5", 32)
	observed := "2026-09-16T19:00:00.000000Z"

	createFollowing := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, nil)
	createFollowing.BundleID = id
	createFollowing.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/twin", RunID: "run-1", ObservedAt: &observed,
		Nodes: []TwinNode{{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9}}}
	createFollowing.Following = &FollowingBlock{Branch: "fylgja-fixture", IntervalS: 300,
		ScheduleID: "fylgja-follow", State: FollowingStarted}

	var startFailed List
	startFailed.AddStep(Warning, StepFollow, RuleFollowStartFailed, "fylgja-follow",
		"the twin is ready but following could not begin: creating schedule fylgja-follow failed (boom); "+
			"the twin is frozen; fylgja twin destroy and create again to follow")
	createNotStarted := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, startFailed)
	createNotStarted.Following = &FollowingBlock{Branch: "fylgja-fixture", IntervalS: 300, State: FollowingNotStarted}

	destroyStopped := NewDocument(OpTwinDestroy, &Subject{RunID: "run-4"}, nil)
	destroyStopped.Cleanup = &CleanupBlock{Teardown: "done", Unstage: "done"}
	destroyStopped.Following = &FollowingBlock{Branch: "fylgja-fixture", Stopped: true}

	dry := func(op string, follow DryRunFollow) *Document {
		d := NewDocument(op, &Subject{Branch: "fylgja-fixture"}, nil)
		d.DryRun = &DryRunBlock{Nodes: []DryRunNode{}, Host: DryRunHost{}, Verdict: VerdictClear, Follow: &follow}
		return d
	}

	host := ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch fylgja-fixture",
		Nodes: []ShowNode{{Name: "n1", Container: "clab-fylgja-n1", State: "running", MgmtIPv4: "172.20.20.2"}}}
	record := func(at string, observedAt *string, source string) *ShowRecord {
		r := &ShowRecord{Branch: "fylgja-fixture", At: at, BundleID: twinID, SchemaHash: "41349c3a",
			ContractVersion: "1", ObservedAt: observedAt, Source: source,
			Run:           ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
			WorkerVersion: "0.1.0-dev", RecordedAt: "2026-09-16T19:01:02Z", Nodes: 1}
		if observedAt == nil {
			r.ObservedAtNote = "provisioned from an existing bundle; no read took place"
		}
		return r
	}
	show := func(block ShowBlock, list List) *Document {
		d := NewDocument(OpTwinShow, nil, list)
		d.Show = &block
		return d
	}
	var rebuildFailed List
	rebuildFailed.AddStep(Rejection, StepReadiness, "readiness.timeout", "n2", "n2 did not answer")
	rebuildFailed.AddStep(Rejection, StepProvision, RuleRebuildFailed, "run-9",
		"the rebuild's provision run-9 ended failed at step readiness; cleanup teardown done, unstage done; following stopped")
	rebuildFailed.AddStep(Warning, StepFollow, RuleFollowStopped, "fylgja-follow",
		"following of branch fylgja-fixture stopped after a failed rebuild; fylgja twin create starts again")
	var unreachable List
	unreachable.Add(Warning, RuleShowServiceUnreachable, "localhost:7233",
		"workflow service unreachable at localhost:7233 (connection refused); whether the twin is following and whether a run is in flight are unknown")

	docs := []labelledDocument{
		{"create following, started", createFollowing},
		{"create following, not started", createNotStarted},
		{"destroy stopped following", destroyStopped},
		{"dry run follows", dry(OpTwinCreate, DryRunFollow{Enabled: true, IntervalS: 300})},
		{"dry run pinned", dry(OpTwinCreate, DryRunFollow{Reason: FollowReasonPinned})},
		{"dry run no follow", dry(OpTwinCreate, DryRunFollow{Reason: FollowReasonNoFollow})},
		{"dry run bundle", dry(OpTwinProvision, DryRunFollow{Reason: FollowReasonBundle})},
		{"show none", show(ShowBlock{Kind: ShowKindNone, Service: ShowServiceOK}, nil)},
		{"show pinned", show(ShowBlock{Host: host, Record: record("2026-09-16T14:00:00Z", &observed, "intent"),
			Kind: ShowKindPinned, Service: ShowServiceOK, Notes: []string{"pinned at 2026-09-16T14:00:00Z; not following"}}, nil)},
		{"show frozen", show(ShowBlock{Host: host, Record: record("", &observed, "intent"),
			Kind: ShowKindFrozen, Service: ShowServiceOK, Notes: []string{"not following"}}, nil)},
		{"show from a bundle", show(ShowBlock{Host: host, Record: record("", nil, "bundle"),
			Kind: ShowKindFromBundle, Service: ShowServiceOK}, nil)},
		{"show following", show(ShowBlock{Host: host, Record: record("", &observed, "intent"), Kind: ShowKindFollowing,
			Following: &ShowFollowing{Branch: "fylgja-fixture", IntervalS: 300, ScheduleID: "fylgja-follow",
				NextCheckAt: "2026-09-16T19:15:00Z",
				LastCheck: &ShowCheck{WorkflowID: "fylgja-reconcile-2026-09-16T19:10:00Z", RunID: "run-c",
					ScheduledAt: "2026-09-16T19:10:00Z", ClosedAt: "2026-09-16T19:11:30Z", Outcome: "rebuilt",
					TwinBundleID: twinID, BundleID: id, Findings: rebuildFailed[:1],
					Cleanup: &CleanupBlock{Teardown: "done", Unstage: "done"}}},
			InFlight: []ShowRun{{WorkflowID: "fylgja-reconcile-2026-09-16T19:15:00Z", RunID: "run-d", Step: StepProvision,
				Child: &ShowRun{WorkflowID: "fylgja-provision", RunID: "run-e", Step: StepReadiness}}},
			Service: ShowServiceOK}, nil)},
		{"show none, following stopped", show(ShowBlock{Kind: ShowKindNone, Service: ShowServiceOK,
			LastCheck: &ShowCheck{WorkflowID: "fylgja-reconcile-2026-09-16T19:10:00Z", RunID: "run-c",
				ScheduledAt: "2026-09-16T19:10:00Z", Outcome: "rebuild_failed", Step: StepProvision,
				Findings: rebuildFailed, Cleanup: &CleanupBlock{Teardown: "done", Unstage: "done"}},
			Notes: []string{"fylgja twin create starts again"}}, nil)},
		{"show service unreachable", show(ShowBlock{Host: host, Record: record("", &observed, "intent"),
			Kind: ShowKindFrozen, Service: ShowServiceUnreachable}, unreachable)},
	}
	return docs
}

// declaredSteps reads the Step* constants out of finding.go's syntax tree, as
// declaredRules reads the Rule* ones, so a constant added to the file cannot escape the
// comparison below.
func declaredSteps(t *testing.T) map[string]string {
	t.Helper()
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "finding.go", nil, 0)
	if err != nil {
		t.Fatalf("parsing finding.go: %v", err)
	}
	out := map[string]string{}
	for _, decl := range file.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.CONST {
			continue
		}
		for _, spec := range gen.Specs {
			vs, ok := spec.(*ast.ValueSpec)
			if !ok {
				continue
			}
			for i, name := range vs.Names {
				if !strings.HasPrefix(name.Name, "Step") || i >= len(vs.Values) {
					continue
				}
				lit, ok := vs.Values[i].(*ast.BasicLit)
				if !ok || lit.Kind != token.STRING {
					continue
				}
				value, err := strconv.Unquote(lit.Value)
				if err != nil {
					t.Fatalf("%s: %v", name.Name, err)
				}
				out[value] = name.Name
			}
		}
	}
	return out
}

// A step is as much API as a rule is: it is the `step` field of every finding a run
// reports, and the schema enumerates it. The two lists are one list.
func TestStepConstantsMatchTheContractEnum(t *testing.T) {
	raw, err := os.ReadFile(newestSchemaPath("findings.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties struct {
			Findings struct {
				Items struct {
					Properties struct {
						Step struct {
							Enum []string `json:"enum"`
						} `json:"step"`
					} `json:"properties"`
				} `json:"items"`
			} `json:"findings"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatal(err)
	}
	enum := schema.Properties.Findings.Items.Properties.Step.Enum
	if len(enum) == 0 {
		t.Fatal("contracts/findings.schema.json enumerates no steps; the test is reading the wrong place")
	}

	declared := declaredSteps(t)
	for _, step := range enum {
		if _, ok := declared[step]; !ok {
			t.Errorf("the contract enumerates step %q; no Step constant in finding.go carries it", step)
		}
	}
	want := map[string]bool{}
	for _, step := range enum {
		want[step] = true
	}
	for step, name := range declaredSteps(t) {
		if !want[step] {
			t.Errorf("%s = %q is declared but the contract's step enum does not name it; "+
				"a step is API, so add it to the contract or drop the constant", name, step)
		}
	}
}

func m5SchemaPath(name string) string {
	return contractPath("005-configuration", name)
}

// compileM5FindingsSchema loads M5's copy of the contract, with the show block's schema
// added under its own $id, as M4's helper does. M1's, M2's and M4's helpers stay their
// own milestones' validators.
func compileM5FindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(m5SchemaPath(name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("https://fylgja.dev/schemas/show.schema.json", load("show.schema.json")); err != nil {
		t.Fatal(err)
	}
	if err := c.AddResource("m5-findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("m5-findings.schema.json")
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load it): %v", m5SchemaPath("findings.schema.json"), err)
	}
	return s
}

// contentMarkers are strings that would appear in a document only if a byte of artifact
// content had reached it. No rendering carries configuration content, so a checksum and
// a size are all a document ever says about the bytes.
var contentMarkers = []string{
	"FYLGJA-MARKER",
	"set / interface",
	"enter candidate private",
	"commit now",
	"NokiaSrl1!",
}

func mustCarryNoContent(t *testing.T, doc *Document, label string) {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range contentMarkers {
		if strings.Contains(string(b), marker) {
			t.Errorf("%s carries %q, which can only have come from artifact content or a credential: %s",
				label, marker, b)
		}
	}
}

// Every document shape M5 adds satisfies M5's contract, and every M2 and M4 shape still
// does. The one shape that needs a word of explanation is the dry run: M5's contract
// *requires* dry_run.nodes[].artifact, because every M5 bundle is bundle_version "2" and
// carries one artifact per node, and twin provision refuses a "1" bundle outright
// (bundle.version.unsupported). So the M2-era dry-run fixture, whose node predates the
// artifact, is given the artifact M5's compiler always fills before it is checked here;
// its unfilled form stays M2's fixture and keeps satisfying M2's own validator. Every
// other block is additive in the plain sense.
func TestM5DocumentsSatisfySchema(t *testing.T) {
	schema := compileM5FindingsSchema(t)
	docs := m5Documents()
	for _, c := range docs {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM6DryRunCounts, dropM7ShowPSP), c.label)
			mustCarryNoContent(t, c.doc, c.label)
		})
	}

	// The contract is additive: every earlier milestone's document still satisfies it.
	for _, c := range append(m2Documents(), m4Documents()...) {
		doc := c.doc
		// See the comment above: an M5 dry run always names the artifact, so the
		// M2-era fixture is completed rather than exempted.
		if doc.DryRun != nil && len(doc.DryRun.Nodes) > 0 {
			doc = withDryRunArtifacts(doc, m5Checksum)
		}
		t.Run("earlier "+c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, doc, dropM6DryRunCounts, dropM7ShowPSP), c.label)
			mustCarryNoContent(t, doc, c.label)
		})
	}

	// A node the record does not name carries an explicit null, not a missing key: the
	// contract promises `{name, checksum}` or `null`, and the schema alone
	// would accept either.
	b, err := json.Marshal(docs[2].doc)
	if err != nil {
		t.Fatal(err)
	}
	if n := strings.Count(string(b), `"artifact"`); n != 2 {
		t.Errorf("both shown nodes carry the artifact key, got %d: %s", n, b)
	}
	// The node carries both nullable keys, written out: M5's artifact and, from M7, the
	// support package, neither of which the record names for this node.
	if !strings.Contains(string(b), `"mgmt_ipv4":"172.20.20.3","artifact":null`) {
		t.Errorf("the unrecorded node must marshal artifact as an explicit null: %s", b)
	}
	if n := strings.Count(string(b), `"psp":null`); n != 2 {
		t.Errorf("both shown nodes carry psp as an explicit null, got %d: %s", n, b)
	}
}

// m5Checksum stands for a device's artifact: MD5 hex, as Infrahub's checksum is.
const m5Checksum = "18b98fda9e2b4f0c8d1a3e5b7c9d0f21"

// m5Documents are the document shapes M5 adds, as m2Documents and m4Documents are
// theirs. Index 2 (show, one node recorded and one not) is read by
// TestM5DocumentsSatisfySchema.
func m5Documents() []labelledDocument {
	id := strings.Repeat("89", 32)
	twinID := strings.Repeat("b5", 32)
	// Two checksums standing for two devices' artifacts: MD5 hex, as Infrahub's
	// checksum is.
	sum1 := m5Checksum
	sum2 := "2c4e6a8b0d1f3579bdf02468ace13579"
	observed := "2026-09-18T19:00:00.000000Z"

	// A create that pushed: each ready node names what it was given and how long the
	// push took.
	created := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, nil)
	created.BundleID = id
	created.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/twin", RunID: "run-1", ObservedAt: &observed,
		Nodes: []TwinNode{
			{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9,
				Artifact: &ShowArtifact{Name: "device-config", Checksum: sum1}, PushedInS: 0.71},
			{Name: "n2", MgmtIPv4: "172.20.20.3", ReadyAfterS: 1.1,
				Artifact: &ShowArtifact{Name: "device-config", Checksum: sum2}, PushedInS: 0.68},
		}}

	// A dry run names what would be pushed and pushes nothing.
	budget := 4096
	dry := NewDocument(OpTwinProvision, &Subject{Bundle: "testdata/golden/three-node"}, nil)
	dry.BundleID = id
	dry.DryRun = &DryRunBlock{
		Nodes: []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: "nokia_srlinux", MemoryMB: 2048,
			Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: sum1, Size: 1462}}},
		MemorySumMB: 2048, HostBudgetMB: &budget, Host: DryRunHost{}, Verdict: VerdictClear,
	}

	// twin show: one node the record names, one it does not (an orphan's).
	host := ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch fylgja-fixture",
		Nodes: []ShowNode{
			{Name: "n1", Container: "clab-fylgja-n1", State: "running", MgmtIPv4: "172.20.20.2",
				Artifact: &ShowArtifact{Name: "device-config", Checksum: sum1}},
			{Name: "n2", Container: "clab-fylgja-n2", State: "running", MgmtIPv4: "172.20.20.3"},
		}}
	shown := NewDocument(OpTwinShow, nil, nil)
	shown.Show = &ShowBlock{Host: host, Kind: ShowKindFrozen, Service: ShowServiceOK,
		Record: &ShowRecord{Branch: "fylgja-fixture", BundleID: twinID, SchemaHash: "41349c3a",
			ContractVersion: "0.2", ObservedAt: &observed, Source: "intent",
			Run:           ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
			WorkerVersion: "0.1.0-dev", RecordedAt: "2026-09-18T19:01:02Z", Nodes: 2}}

	// A run that failed at the push: every node's outcome, then M2's cleanup. The
	// refusal names the node's own reason and the artifact's line, never the line.
	var pushFailed List
	pushFailed.AddStep(Rejection, StepPush, RulePushRefused, "n1",
		"n1 refused device-config 18b98fda… at line 14: Error: Path not valid; nothing was committed")
	pushFailed.AddStep(Rejection, StepPush, RulePushFailed, "n2",
		"n2 did not take device-config 2c4e6a8b… within 30s; n1 was pushed")
	failed := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-2"}, pushFailed)
	failed.Status = StatusFailed
	failed.BundleID = id
	failed.Cleanup = &CleanupBlock{Teardown: "done", Unstage: "done",
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}

	// A cancellation that reached the push.
	var cancelled List
	cancelled.AddStep(Rejection, StepPush, RuleRunCancelled, "run-3",
		"run run-3 was cancelled at step push; the lab and the twin directory were removed")
	stopped := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-3"}, cancelled)
	stopped.Status = StatusFailed
	stopped.Cleanup = &CleanupBlock{Teardown: "done", Unstage: "done"}

	return []labelledDocument{
		{"create pushed", created},
		{"dry run names what would be pushed", dry},
		{"show, one node recorded and one not", shown},
		{"create failed at the push", failed},
		{"create cancelled at the push", stopped},
	}
}

func m6SchemaPath(name string) string {
	return contractPath("006-psp-lossy-mapping", name)
}

// compileM6FindingsSchema loads M6's copy of the contract, with the show block's schema
// added under its own $id, as M5's helper does.
func compileM6FindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(m6SchemaPath(name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("https://fylgja.dev/schemas/show.schema.json", load("show.schema.json")); err != nil {
		t.Fatal(err)
	}
	if err := c.AddResource("m6-findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("m6-findings.schema.json")
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load it): %v", m6SchemaPath("findings.schema.json"), err)
	}
	return s
}

// M6 adds two integers to the dry run, required: the lossy record's entries and its
// shared ports, counted from the bundle. Every document M5 and the milestones
// before it build satisfies M6's contract as it is, the dry runs carrying their zeros;
// M2's dry run is completed with the artifact every "2" bundle names, as M5's test does.
func TestM6DocumentsSatisfySchema(t *testing.T) {
	schema := compileM6FindingsSchema(t)
	budget := 8192
	lossy := NewDocument(OpTwinProvision, &Subject{Bundle: "testdata/golden/lossy"}, nil)
	lossy.BundleID = strings.Repeat("81", 32)
	lossy.DryRun = &DryRunBlock{
		Nodes: []DryRunNode{{Name: "c1", Image: "example.invalid/chassisos:0", PSP: "chassisos", MemoryMB: 2048,
			Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 245}}},
		MemorySumMB: 2048, HostBudgetMB: &budget, Host: DryRunHost{}, Verdict: VerdictClear,
		LossyMappings: 9, SharedPorts: 3,
		Follow: &DryRunFollow{Reason: FollowReasonBundle},
	}
	mustValidate(t, schema, lossy, "dry run of a lossy bundle")
	b, err := json.Marshal(lossy)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"lossy_mappings":9,"shared_ports":3`) {
		t.Errorf("the dry run does not carry its counts: %s", b)
	}

	// Without them the document is M5's, which M6's contract refuses: the counts are
	// required, so a dry run can never leave them out.
	if err := schema.Validate(mustAny(t, asEarlier(t, lossy, dropM6DryRunCounts))); err == nil {
		t.Error("a dry run without lossy_mappings and shared_ports satisfied M6's findings.schema.json")
	}

	earlier := append(append(m2Documents(), m4Documents()...), m5Documents()...)
	for _, c := range earlier {
		doc := c.doc
		if doc.DryRun != nil && len(doc.DryRun.Nodes) > 0 && doc.DryRun.Nodes[0].Artifact == nil {
			doc = withDryRunArtifacts(doc, m5Checksum)
		}
		t.Run("earlier "+c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, doc, dropM7ShowPSP), c.label)
			mustCarryNoContent(t, doc, c.label)
			if doc.DryRun == nil {
				return
			}
			b, err := json.Marshal(doc)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(b), `"lossy_mappings":0,"shared_ports":0`) {
				t.Errorf("a dry run with nothing lossy must say 0 and 0, not leave the counts out: %s", b)
			}
		})
	}
}

func mustAny(t *testing.T, b []byte) any {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

// withDryRunArtifacts copies a document, giving every dry-run node the artifact an M5
// bundle always carries. It copies rather than mutates: m2Documents and m4Documents are
// shared with the tests that validate against M2's and M4's own schemas, which have
// additionalProperties: false and would reject the field.
func withDryRunArtifacts(doc *Document, checksum string) *Document {
	out := *doc
	block := *doc.DryRun
	nodes := make([]DryRunNode, len(block.Nodes))
	copy(nodes, block.Nodes)
	for i := range nodes {
		nodes[i].Artifact = &DryRunArtifact{
			Name: "device-config", ContentType: "text/plain", Checksum: checksum, Size: 1462,
		}
	}
	block.Nodes = nodes
	out.DryRun = &block
	return &out
}
