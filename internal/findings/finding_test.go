package findings

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"slices"
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
	// Completeness and intent rules.
	"data.required.missing",
	"device.name.duplicate",
	"platform.unsupported",
	"link.endpoints.count",
	"link.endpoints.same_device",
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

	// M4's rules: following's seven, which 019 retired (retiredWithFollowing), and this
	// one.
	"show.service.unreachable",

	// M5's rules. Appended, as M2's and M4's were.
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

	// M11's rules. Appended, as every milestone's were; a run in flight is M2's
	// run.in_flight, so it is not here.
	"step.twin.unsteppable",
	"step.twin.diverged",
	"step.target.unknown",
	"step.bundle.missing",
	"step.package.merge",
	"step.node.unapplied",
	"step.restart.required",
	"step.diverged",
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

	// 014's twelve stage rules and step.stage.skipped, and 015's nine rehearsal rules, left
	// this table at 020 (T035) with their operations: the orchestrator's
	// (TestTheOrchestratorsRulesAreRetired).

	// 017's rules (research R-21). Appended; the eight the generics left are gone from
	// both lists (FR-016; retiredWithTheGenerics below), and the scope's three and the
	// schema check's five went to the orchestrator at 020 (T035).
	"platform.missing",
	"platform.unmatched",
	"omit.cable.ends",
	"omit.cable.endpoint",
	"omit.cable.outside_scope",
	"omit.cable.kind",
	"ctm.version.unsupported",
	"psp.matches.missing",
	"psp.matches.duplicate",

	// 018's rules (research R-03, R-07). Appended; the inner CTM's faults keep their
	// identifiers (018 also had --interval beside --snapshot refused as follow.flags.conflict,
	// which 019 retired).
	"snapshot.invalid",
	"snapshot.version.unsupported",
	"snapshot.id.mismatch",
	"snapshot.unknown",

	// 016's rules (data-model §12). Appended; none retired at 016 (R-27), and snapshot.invalid
	// and snapshot.version.unsupported above are reworded, not renamed. The declaration
	// file's two, probes.version.unsupported and probes.invalid, and probe.kind.absent went
	// to the orchestrator at 020 (T035), with snapshot.flags.conflict.
	"probe.name.invalid",
	"probe.name.duplicate",
	"probe.address.invalid",
	"probe.gateway.invalid",
	"probe.gateway.outside",
	"probe.family.mixed",
	"probe.address.duplicate",
	"probe.format.unknown",
	"probe.device.unknown",
	"probe.interface.unknown",
	"probe.interface.cabled",
	"probe.interface.mgmt_only",
	"probe.port.taken",
	"probe.host.collision",
	"probe.package.schema",
	"probe.package.version.unknown",
	"probe.package.format.duplicate",
	"probe.package.template",
	"host.probe_package.missing",
	"flow.start.failed",
	"flow.read.failed",
	"verify.burst",

	// 020's rules (data-model §11, R-19). Appended; the core's runs by identity. The
	// orchestrator's left this table at T035 (TestTheOrchestratorsRulesAreRetired).
	"run.detached",
	"run.unknown",
	"run.cancel.requested",
	"run.ended",
	"run.flags.conflict",
}

// dcimMapping is the mapping a twin.json 8 record's provenance names when the Infrahub
// reader read the schema library's DCIM (017), as twin show shows it.
var dcimMapping = &ShowMapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}

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

// retiredWithFollowing are following's seven identifiers, removed with it at 019 (D-062;
// research R-12), beside the step follow.
var retiredWithFollowing = []string{
	"follow.interval.invalid",
	"follow.flags.conflict",
	"follow.start.failed",
	"follow.stop.failed",
	"check.skipped",
	"rebuild.failed",
	"follow.stopped",
}

// None of following's seven is declared or in the rule table, and no step constant is
// follow: a document of this build names none of them, and the contract's step enum has no
// follow (TestStepConstantsMatchTheContractEnum).
func TestTheFollowingRulesAreRetired(t *testing.T) {
	declared := declaredRules(t)
	for _, rule := range retiredWithFollowing {
		if name, ok := declared[rule]; ok {
			t.Errorf("%s = %q is declared; 019 retired it with following", name, rule)
		}
		if slices.Contains(dataModelRules, rule) {
			t.Errorf("the rule table still names %q; 019 retired it with following", rule)
		}
	}
	if name, ok := declaredSteps(t)["follow"]; ok {
		t.Errorf("%s = \"follow\" is declared; 019 retired the step with following", name)
	}
}

// None of following's seven is declared or in the rule table, and neither is
// step.target.foreign, retired beside them at 019 once a step's --stage named a stage of
// any proposed change (research R-07): a document of this build names none of the eight.
func TestTheForeignTargetIsRetired(t *testing.T) {
	const rule = "step.target.foreign"
	if name, ok := declaredRules(t)[rule]; ok {
		t.Errorf("%s = %q is declared; 019 retired it", name, rule)
	}
	if slices.Contains(dataModelRules, rule) {
		t.Errorf("the rule table still names %q; 019 retired it", rule)
	}
}

// retiredWithTheGenerics are the eight identifiers that existed only for the generics
// contract, removed with it at 017 (FR-016; research R-21).
var retiredWithTheGenerics = []string{
	"contract.version.mismatch",
	"contract.node.missing",
	"schema.generic.unimplemented",
	"schema.artifact_target.missing",
	"interface.iftype.unimplemented",
	"interface.mgmt_only.iftype",
	"interface.parent.missing",
	"link.endpoint.iftype",
}

// None of the eight is declared or in the rule table: a reader or a test that still files
// one cannot compile, and a document carrying one is a rule nobody makes.
func TestTheGenericsRulesAreRetired(t *testing.T) {
	declared := declaredRules(t)
	for _, rule := range retiredWithTheGenerics {
		if name, ok := declared[rule]; ok {
			t.Errorf("%s = %q is declared; 017 retired it with the generics", name, rule)
		}
		if slices.Contains(dataModelRules, rule) {
			t.Errorf("the rule table still names %q; 017 retired it with the generics", rule)
		}
	}
}

// retiredToTheOrchestrator are the core's identifiers 020 moved to the orchestrator
// (data-model §11; research R-19, §5.13): 014's stage rules, 015's rehearsal rules, 017's
// scope and schema check rules, the read's at, the declaration file's and the probe kind's,
// the read's flags beside --snapshot, and the step's two stage rules. step.target.unknown
// and M2's stage.failed stay the core's: the first is twin step's refusal of no
// --snapshot, the second M2's staging step.
var retiredToTheOrchestrator = []string{
	"scope.invalid", "scope.unset", "scope.empty",
	"schema.kind.missing", "schema.field.missing", "schema.field.mismatch", "schema.choice.missing", "schema.used_by.missing",
	"intent.at.precision", "probe.kind.absent", "probes.version.unsupported", "probes.invalid", "snapshot.flags.conflict",
	"stage.ref.invalid", "stage.flags.conflict", "stage.kind.absent", "stage.unknown", "stage.duplicate", "stage.at.unresolved",
	"stage.at.before_branch_point", "stage.label.reserved", "stage.artifact.stale", "stage.orphaned", "stage.main.moved",
	"stage.twin.moved", "step.target.current", "step.stage.skipped",
	"rehearsal.deadline.unfit", "rehearsal.twin.reclaimed", "rehearsal.steps.none", "rehearsal.stage.failed",
	"rehearsal.stage.error", "rehearsal.baseline.failed", "rehearsal.deadline.cut", "rehearsal.stage.moved",
	"rehearsal.change.closed",
}

// rulesFile is the orchestrator's table of every rule its adapter and flows file
// (data-model §11), read as a file: this package imports nothing of the orchestrator's.
var rulesFile = filepath.Join("..", "..", "orchestrator", "src", "fylgja_orchestrator", "documents", "rules.py")

// Each retired identifier is neither declared nor in the rule table, so no document of the
// core's carries one, and each is the orchestrator's: a _r("<id>", …) row of its rules.py
// that does not say core=True. step.target.unknown and stage.failed stay declared.
func TestTheOrchestratorsRulesAreRetired(t *testing.T) {
	raw, err := os.ReadFile(rulesFile)
	if err != nil {
		t.Fatal(err)
	}
	rows := map[string]string{}
	for _, m := range regexp.MustCompile(`(?s)_r\("([a-z_.]+)",(.*?)\),\n`).FindAllStringSubmatch(string(raw), -1) {
		rows[m[1]] = m[2]
	}
	if len(rows) < len(retiredToTheOrchestrator) {
		t.Fatalf("%s holds %d rows; the test is reading the wrong place", rulesFile, len(rows))
	}
	declared := declaredRules(t)
	for _, rule := range retiredToTheOrchestrator {
		if name, ok := declared[rule]; ok {
			t.Errorf("%s = %q is declared; 020 moved it to the orchestrator", name, rule)
		}
		if slices.Contains(dataModelRules, rule) {
			t.Errorf("the rule table still names %q; 020 moved it to the orchestrator", rule)
		}
		row, ok := rows[rule]
		switch {
		case !ok:
			t.Errorf("%s has no row for %q, which the core no longer files", rulesFile, rule)
		case strings.Contains(row, "core=True"):
			t.Errorf("%s marks %q the core's; 020 retired it from the core", rulesFile, rule)
		}
	}
	for _, kept := range []string{"step.target.unknown", "stage.failed"} {
		if _, ok := declared[kept]; !ok {
			t.Errorf("%q is not declared; the core keeps it", kept)
		}
	}
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
		Rule:     RuleInterfaceRuleUnmatched,
		Object:   "n1:Ethernet99",
		Message:  "no rule of the nokia_srlinux profile matches this production name (tried: ethernet, mgmt); the profile or the intent must be fixed",
	}}
	withLocation := List{{
		Severity: Warning,
		Rule:     RulePSPResourcesImplausible,
		Object:   "nokia_srlinux",
		Message:  "resources look implausible",
		Location: &Location{File: "psp/x.yaml", Line: 12},
	}}

	compileOK := NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/bundle"}, nil)
	compileOK.BundleID = strings.Repeat("ab", 32)

	cases := []struct {
		label string
		doc   *Document
	}{
		{"twin compile ok", compileOK},
		{"twin compile rejected", NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/b"}, rejected)},
		{"twin compile error", ErrorDocument(OpCompile, &Subject{Out: "/tmp/b"}, "--out is required")},
		{"psp validate with location", NewDocument(OpPSPValidate, &Subject{Files: []string{"psp/x.yaml"}}, withLocation)},
	}
	for _, c := range cases {
		t.Run(c.label, func(t *testing.T) { mustValidate(t, schema, c.doc, c.label) })
	}
}

// orchestratorOperations are the five operations 020 moved to the orchestrator (D-065;
// data-model §11): its fylgja-cli prints findings 1 documents under them, held to the same
// contract (orchestrator/src/fylgja_orchestrator/documents/findings.py), so they stay in the
// contract's enum (research R-13) while the core declares none of them (T035).
var orchestratorOperations = []string{"intent.read", "schema.check", "stage.list", "stage.plan", "twin.rehearse"}

// declaredOperations reads the Op* constants out of render.go's syntax tree, as
// declaredRules reads the rules, so a constant added to the file cannot escape the
// comparison.
func declaredOperations(t *testing.T) map[string]string {
	t.Helper()
	file, err := parser.ParseFile(token.NewFileSet(), "render.go", nil, 0)
	if err != nil {
		t.Fatalf("parsing render.go: %v", err)
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
				if !strings.HasPrefix(name.Name, "Op") || i >= len(vs.Values) {
					continue
				}
				if lit, ok := vs.Values[i].(*ast.BasicLit); ok && lit.Kind == token.STRING {
					value, err := strconv.Unquote(lit.Value)
					if err != nil {
						t.Fatalf("%s: %v", name.Name, err)
					}
					out[value] = name.Name
				}
			}
		}
	}
	return out
}

// The operation names in the schema's enum are the core's Op* constants and the
// orchestrator's five, each once: M4's eight less intent.read and schema.check, M11's one,
// M12's one and 020's three are the core's.
func TestOperationConstantsMatchTheContract(t *testing.T) {
	declared := declaredOperations(t)
	all := []string{OpCompile, OpPSPValidate, OpTwinCreate, OpTwinProvision, OpTwinDestroy, OpTwinShow,
		OpTwinStep, OpTwinVerify, OpRunRead, OpRunInterrupt, OpTwinDiff}
	if len(declared) != len(all) {
		t.Errorf("render.go declares %d operations, %v; the test names %d", len(declared), declared, len(all))
	}
	for _, op := range orchestratorOperations {
		if name, ok := declared[op]; ok {
			t.Errorf("%s = %q is declared; 020 moved it to the orchestrator", name, op)
		}
	}
	all = append(all, orchestratorOperations...)
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
// diverged; 019 puts snapshot in place of pinned, frozen and following).
func TestShowKindConstantsMatchTheContract(t *testing.T) {
	all := []string{ShowKindNone, ShowKindSnapshot, ShowKindFromBundle, ShowKindDiverged}
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
		Nodes:       []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: ptr("nokia_srlinux"), MemoryMB: 2048}},
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
	if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/show.schema.json", load("show.schema.json")); err != nil {
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
	for _, c := range m4FollowingDocuments() {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM5ShowArtifacts, dropM6DryRunCounts, dropM7ShowPSP, c.restore), c.label)
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
// milestone's shape; withDryRunArtifacts is the same move in the other direction. Every
// schema it serves predates 017, so the show record's provenance is always put back as
// they read it (drop017ShowProvenance), and the snapshot ids 018 always writes are taken
// out (drop018Snapshots).
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
	restore018Kind(generic)
	for _, drop := range append(drops, drop018Snapshots, drop017ShowProvenance) {
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

// drop017ShowProvenance gives a show record the provenance every contract before 017's
// requires: 017 removed record.contract_version and put the record's scope and mapping in
// its place (contracts/formats.md, "The findings blocks"), a removal no earlier contract
// accepts, so an earlier schema is asked to validate the record as its milestone wrote it.
func drop017ShowProvenance(doc map[string]any) {
	show, _ := doc["show"].(map[string]any)
	record, _ := show["record"].(map[string]any)
	if record == nil {
		return
	}
	delete(record, "scope")
	delete(record, "mapping")
	record["contract_version"] = "0.2"
}

// drop018Snapshots removes the snapshot ids 018 writes as null wherever a block names none:
// the show record's, each plan stage's and each rehearsal stage's. Every contract before
// 018's predates the key and forbids additional properties, and from 018 each of them is
// always written. An id that is set is left, so a document that names a snapshot is still
// refused by an earlier contract, as it should be.
func drop018Snapshots(doc map[string]any) {
	dropNull := func(m any) {
		if o, ok := m.(map[string]any); ok {
			if v, ok := o["snapshot_id"]; ok && v == nil {
				delete(o, "snapshot_id")
			}
		}
	}
	if show, ok := doc["show"].(map[string]any); ok {
		dropNull(show["record"])
	}
	for _, block := range []string{"plan", "rehearsal"} {
		if b, ok := doc[block].(map[string]any); ok {
			stages, _ := b["stages"].([]any)
			for _, st := range stages {
				dropNull(st)
			}
		}
	}
}

// drop016NullLoss removes the step block's loss when it is null, as the dry run and a run
// closed before its flows were read write it (016), and each rehearsal stage's, null on
// every stage whose step read no flow, and the burst count of a read that ran no burst
// (016): the verify block's counts, the step's wait_counts and each rehearsed stage's
// verify. Every contract before 016's forbids the keys, and from 016 they are always
// written. A loss that is set, and a burst count that counted a burst, are left, so an
// earlier contract still refuses a document carrying one.
func drop016NullLoss(doc map[string]any) {
	dropNoBurst := func(counts any) {
		c, ok := counts.(map[string]any)
		if !ok {
			return
		}
		if b, ok := c["burst"].(map[string]any); ok && b["held"] == 0.0 && b["failed"] == 0.0 && (b["unread"] == nil || b["unread"] == 0.0) {
			delete(c, "burst")
		}
	}
	if step, ok := doc["step"].(map[string]any); ok {
		if v, ok := step["loss"]; ok && v == nil {
			delete(step, "loss")
		}
		dropNoBurst(step["wait_counts"])
	}
	if v, ok := doc["verify"].(map[string]any); ok {
		dropNoBurst(v["counts"])
	}
	if r, ok := doc["rehearsal"].(map[string]any); ok {
		stages, _ := r["stages"].([]any)
		for _, st := range stages {
			if st, ok := st.(map[string]any); ok {
				dropNoBurst(st["verify"])
				if v, ok := st["loss"]; ok && v == nil {
					delete(st, "loss")
				}
			}
		}
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
// that a later milestone's schema can be held to every earlier shape. The shapes that carry
// following, which 019 removed from Document, are m4FollowingDocuments.
func m4Documents() []labelledDocument {
	twinID := strings.Repeat("b5", 32)
	observed := "2026-09-16T19:00:00.000000Z"

	host := ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch fylgja-fixture",
		Nodes: []ShowNode{{Name: "n1", Container: "clab-fylgja-n1", State: "running", MgmtIPv4: "172.20.20.2"}}}
	record := func(at string, observedAt *string, source string) *ShowRecord {
		r := &ShowRecord{Branch: "fylgja-fixture", At: at, BundleID: twinID, SchemaHash: "41349c3a",
			Scope: "tag:fylgja", Mapping: dcimMapping, ObservedAt: observedAt, Source: source,
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
	var unreachable List
	unreachable.Add(Warning, RuleShowServiceUnreachable, "localhost:7233",
		"the workflow service at localhost:7233 did not answer within 5s: whether a run is in flight is unknown")

	// 019 put kind snapshot in place of M4's pinned and frozen (restore018Kind gives an
	// earlier contract the kind that build wrote), and the shows of a following twin and of
	// a following stopped are m4FollowingDocuments.
	docs := []labelledDocument{
		{"show none", show(ShowBlock{Kind: ShowKindNone, Service: ShowServiceOK}, nil)},
		{"show a snapshot, at", show(ShowBlock{Host: host, Record: record("2026-09-16T14:00:00Z", &observed, "intent"),
			Kind: ShowKindSnapshot, Service: ShowServiceOK}, nil)},
		{"show a snapshot, read at", show(ShowBlock{Host: host, Record: record("", &observed, "intent"),
			Kind: ShowKindSnapshot, Service: ShowServiceOK, Notes: []string{"reproducing the twin with --at " + observed + " is best-effort"}}, nil)},
		{"show from a bundle", show(ShowBlock{Host: host, Record: record("", nil, "bundle"),
			Kind: ShowKindFromBundle, Service: ShowServiceOK}, nil)},
		{"show service unreachable", show(ShowBlock{Host: host, Record: record("", &observed, "intent"),
			Kind: ShowKindSnapshot, Service: ShowServiceUnreachable}, unreachable)},
	}
	return docs
}

// earlierDocument is a document an earlier build wrote that this build's Document can no
// longer hold: doc is what this build writes in its place, and restore puts back, in the
// document as a generic object, what 019 removed from the type, M4's following block,
// dry_run.follow, the show kinds pinned, frozen and following, the show's following and
// last check, and following's rules (D-062). Each contract that defined them, up to 018's,
// is held to it.
type earlierDocument struct {
	label   string
	doc     *Document
	restore func(doc map[string]any)
}

// m4FollowingDocuments are the shapes M4 added that carry following: a create that began
// following and one that could not, with its warning, a destroy that stopped it, a dry run
// of each answer M4 gave, and twin show's: a twin pinned, one frozen, one following with
// its last check and a check rebuilding it, and no twin after a failed rebuild stopped
// following.
func m4FollowingDocuments() []earlierDocument {
	id := strings.Repeat("89", 32)
	observed := "2026-09-16T19:00:00.000000Z"
	following := func(block map[string]any) func(map[string]any) {
		return func(doc map[string]any) { doc["following"] = block }
	}

	created := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, nil)
	created.BundleID = id
	created.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/twin", RunID: "run-1", ObservedAt: &observed,
		Nodes: []TwinNode{{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9}}}

	notStarted := NewDocument(OpTwinCreate, &Subject{Branch: "fylgja-fixture", RunID: "run-1"}, nil)
	startFailed := map[string]any{"severity": "warning", "rule": "follow.start.failed", "object": "fylgja-follow", "step": "follow",
		"message": "the twin is ready but following could not begin: creating schedule fylgja-follow failed (boom); " +
			"the twin is frozen; fylgja twin destroy and create again to follow"}

	destroyed := NewDocument(OpTwinDestroy, &Subject{RunID: "run-4"}, nil)
	destroyed.Cleanup = &CleanupBlock{Teardown: "done", Unstage: "done"}

	twinID := strings.Repeat("b5", 32)
	shown := map[string]*Document{}
	for _, c := range m4Documents() {
		shown[c.label] = c.doc
	}
	readinessTimeout := map[string]any{"severity": "rejection", "rule": "readiness.timeout", "object": "n2", "step": "readiness",
		"message": "n2 did not answer"}

	return []earlierDocument{
		{"create following, started", created, following(map[string]any{"branch": "fylgja-fixture", "interval_s": 300,
			"schedule_id": "fylgja-follow", "state": "started"})},
		{"create following, not started", notStarted, func(doc map[string]any) {
			following(map[string]any{"branch": "fylgja-fixture", "interval_s": 300, "state": "not_started"})(doc)
			doc["findings"] = []any{startFailed}
		}},
		{"destroy stopped following", destroyed, following(map[string]any{"branch": "fylgja-fixture", "stopped": true})},
		followingDryRun("dry run follows", OpTwinCreate, map[string]any{"enabled": true, "interval_s": 300}),
		followingDryRun("dry run pinned", OpTwinCreate, map[string]any{"enabled": false, "reason": "pinned"}),
		followingDryRun("dry run no follow", OpTwinCreate, map[string]any{"enabled": false, "reason": "no_follow"}),
		followingDryRun("dry run bundle", OpTwinProvision, map[string]any{"enabled": false, "reason": "bundle"}),
		{"show pinned", shown["show a snapshot, at"], showKindWas("pinned", "pinned at 2026-09-16T14:00:00Z; not following")},
		{"show frozen", shown["show a snapshot, read at"], showKindWas("frozen", "not following")},
		{"show following", shown["show a snapshot, read at"], func(doc map[string]any) {
			showKindWas("following", "a rebuild discards the twin's runtime state")(doc)
			show := doc["show"].(map[string]any)
			show["following"] = map[string]any{"branch": "fylgja-fixture", "interval_s": 300, "schedule_id": "fylgja-follow",
				"next_check_at": "2026-09-16T19:15:00Z", "last_check": map[string]any{
					"workflow_id": "fylgja-reconcile-2026-09-16T19:10:00Z", "run_id": "run-c",
					"scheduled_at": "2026-09-16T19:10:00Z", "closed_at": "2026-09-16T19:11:30Z", "outcome": "rebuilt",
					"twin_bundle_id": twinID, "bundle_id": id, "findings": []any{readinessTimeout},
					"cleanup": map[string]any{"teardown": "done", "unstage": "done", "remaining": []any{}}}}
			show["in_flight"] = []any{map[string]any{"workflow_id": "fylgja-reconcile-2026-09-16T19:15:00Z", "run_id": "run-d",
				"step": "provision", "child": map[string]any{"workflow_id": "fylgja-provision", "run_id": "run-e", "step": "readiness"}}}
		}},
		{"show none, following stopped", shown["show none"], func(doc map[string]any) {
			show := doc["show"].(map[string]any)
			show["last_check"] = map[string]any{"workflow_id": "fylgja-reconcile-2026-09-16T19:10:00Z", "run_id": "run-c",
				"scheduled_at": "2026-09-16T19:10:00Z", "outcome": "rebuild_failed", "step": "provision",
				"findings": []any{readinessTimeout,
					map[string]any{"severity": "rejection", "rule": "rebuild.failed", "object": "run-9", "step": "provision",
						"message": "the rebuild's provision run-9 ended failed at step readiness; cleanup teardown done, unstage done; following stopped"},
					map[string]any{"severity": "warning", "rule": "follow.stopped", "object": "fylgja-follow", "step": "follow",
						"message": "following of branch fylgja-fixture stopped after a failed rebuild; fylgja twin create starts again"}},
				"cleanup": map[string]any{"teardown": "done", "unstage": "done", "remaining": []any{}}}
			show["notes"] = []any{"fylgja twin create starts again"}
		}},
	}
}

// showKindWas restores a show block's kind and notes as an earlier build wrote them for
// the twin this build shows with kind snapshot.
func showKindWas(kind string, notes ...string) func(map[string]any) {
	return func(doc map[string]any) {
		show := doc["show"].(map[string]any)
		show["kind"] = kind
		var n []any
		for _, s := range notes {
			n = append(n, s)
		}
		show["notes"] = n
	}
}

// followingDryRun is a dry run of op that names no node, as an earlier build wrote it with
// dry_run.follow.
func followingDryRun(label, op string, follow map[string]any) earlierDocument {
	doc := NewDocument(op, &Subject{Branch: "fylgja-fixture"}, nil)
	doc.DryRun = &DryRunBlock{Nodes: []DryRunNode{}, Host: DryRunHost{}, Verdict: VerdictClear}
	return earlierDocument{label, doc, func(doc map[string]any) {
		doc["dry_run"].(map[string]any)["follow"] = follow
	}}
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
	if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/show.schema.json", load("show.schema.json")); err != nil {
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
	for _, c := range m4FollowingDocuments() {
		t.Run("earlier "+c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM6DryRunCounts, dropM7ShowPSP, c.restore), c.label)
			mustCarryNoContent(t, c.doc, c.label)
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
		Nodes: []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: ptr("nokia_srlinux"), MemoryMB: 2048,
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
	shown.Show = &ShowBlock{Host: host, Kind: ShowKindSnapshot, Service: ShowServiceOK,
		Record: &ShowRecord{Branch: "fylgja-fixture", BundleID: twinID, SchemaHash: "41349c3a",
			Scope: "tag:fylgja", Mapping: dcimMapping, ObservedAt: &observed, Source: "intent",
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
	if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/show.schema.json", load("show.schema.json")); err != nil {
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
		Nodes: []DryRunNode{{Name: "c1", Image: "example.invalid/chassisos:0", PSP: ptr("chassisos"), MemoryMB: 2048,
			Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 245}}},
		MemorySumMB: 2048, HostBudgetMB: &budget, Host: DryRunHost{}, Verdict: VerdictClear,
		LossyMappings: 9, SharedPorts: 3,
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
	for _, c := range m4FollowingDocuments() {
		t.Run("earlier "+c.label, func(t *testing.T) {
			mustValidateBytes(t, schema, asEarlier(t, c.doc, dropM7ShowPSP, c.restore), c.label)
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

// 020's five run rules (data-model §1, §11) in documents of the operations that file them,
// each held to the current contract with the status and exit the data model gives it: a
// detached start is ok, an unknown or ended identity and a detach beside a dry run are
// refusals (exit 1), an interrupt asked is ok; twin.diff's document carries no rule of its
// own (TestATwinDiffDocumentCarriesItsSidesAndItsPair holds its fields).
func TestTheRunRulesRenderValidDocuments(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	const runID = "0199a3c4-5b6d-7e8f-9a0b-1c2d3e4f5a6b"
	identity := "fylgja-provision " + runID

	var detached List
	detached.AddStep(Info, StepStart, RuleRunDetached, identity,
		"run "+identity+" started; read it with fylgja run read")
	var conflict List
	conflict.AddStep(Rejection, StepStart, RuleRunFlagsConflict, "dry_run",
		"detach was given beside dry_run; a dry run starts no run to detach from")
	var unknown, requested, ended List
	unknown.Add(Rejection, RuleRunUnknown, identity, "the workflow service holds no run "+identity)
	requested.Add(Info, RuleRunCancelRequested, identity, "cancellation of run "+identity+" was requested")
	ended.Add(Rejection, RuleRunEnded, identity, "run "+identity+" has already closed: completed")

	cases := []struct {
		label string
		doc   *Document
		exit  int
	}{
		{"twin create detached", NewDocument(OpTwinCreate, &Subject{RunID: runID}, detached), ExitOK},
		{"twin step detach beside dry_run", NewDocument(OpTwinStep, nil, conflict), ExitRejected},
		{"run read unknown", NewDocument(OpRunRead, &Subject{RunID: runID}, unknown), ExitRejected},
		{"run interrupt requested", NewDocument(OpRunInterrupt, &Subject{RunID: runID}, requested), ExitOK},
		{"run interrupt ended", NewDocument(OpRunInterrupt, &Subject{RunID: runID}, ended), ExitRejected},
		{"twin diff ok", NewDocument(OpTwinDiff, nil, nil), ExitOK},
	}
	for _, c := range cases {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			if got := c.doc.Status.ExitCode(); got != c.exit {
				t.Errorf("exit = %d (status %s), want %d", got, c.doc.Status, c.exit)
			}
		})
	}
}

// twin.diff's document (020, R-05) names its two sides and carries the step between their
// bundles as its step block, the pair as internal/step marshals it (stages.schema.json's
// $defs/step) and nothing of twin step's block, which the current contract holds; read back,
// the block is the pair as written, and written again it is the same bytes.
func TestATwinDiffDocumentCarriesItsSidesAndItsPair(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	const a, b = "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00",
		"c70589c35899378b8343abd1ebc12ab476e2f08a33a14449eb585d21cefd9672"
	pair := `{"from":"snapshot b9db37f8…","to":"snapshot b9db37f8…","from_bundle_id":"` + b + `","to_bundle_id":"` + b +
		`","computed":true,"unchanged":true,"nodes":{"added":[],"removed":[],"changed":[]},` +
		`"links":{"added":[],"removed":[]},"artifacts":{"changed":[]}}`
	doc := NewDocument(OpTwinDiff, nil, nil)
	doc.SnapshotFrom, doc.SnapshotTo, doc.BundleFrom, doc.BundleTo = a, a, b, b
	doc.Step = DiffBlock(json.RawMessage(pair))
	mustValidate(t, schema, doc, "twin diff")

	written, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var read Document
	if err := json.Unmarshal(written, &read); err != nil {
		t.Fatal(err)
	}
	if read.Step == nil || string(read.Step.Pair) != pair || read.SnapshotFrom != a || read.BundleTo != b {
		t.Fatalf("read back %+v, step %+v; want the sides and the pair as written", read, read.Step)
	}
	again, err := json.Marshal(&read)
	if err != nil {
		t.Fatal(err)
	}
	if string(again) != string(written) {
		t.Errorf("written again:\n%s\nwant:\n%s", again, written)
	}

	// Twin step's block is read as one still: its diff is what tells the two apart.
	var step StepBlock
	if err := json.Unmarshal([]byte(`{"from":{"stage":null,"bundle_id":"`+b+`","at":""},"to":{"stage":null,"bundle_id":"`+b+
		`","at":""},"diff":`+pair+`,"reconcile":{},"push_plan":[],"allow_restart":false,"loss":null}`), &step); err != nil {
		t.Fatal(err)
	}
	if step.Pair != nil || step.From.BundleID != b || string(step.Diff) != pair {
		t.Errorf("twin step's block read as %+v; want its sides and its diff", step)
	}
}
