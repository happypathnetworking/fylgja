// An external test package: internal/validate imports the compiler, so a test that runs
// both callers of SurveyDevice cannot live inside it.
package compiler_test

import (
	"cmp"
	"fmt"
	"path/filepath"
	"slices"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// registry is the embedded packages with the design-case package beside them, as
// --psp-dir testdata/psp/lossy gives it; nothing changes for an SR Linux fixture.
func registry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load(repoPath("testdata", "psp", "lossy"))
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

func loadCTM(t *testing.T, parts ...string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath(parts...))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// refusal is what an operator reads of a finding, less the step its caller places it at.
type refusal struct{ severity, rule, object, message string }

func refusalsOf(list findings.List) []refusal {
	out := make([]refusal, 0, len(list))
	for _, f := range list {
		out = append(out, refusal{string(f.Severity), f.Rule, f.Object, f.Message})
	}
	slices.SortFunc(out, func(a, b refusal) int {
		return cmp.Or(cmp.Compare(a.object, b.object), cmp.Compare(a.rule, b.rule), cmp.Compare(a.message, b.message))
	})
	return out
}

// bothCallers runs validation and the compiler on two copies of one intent and asserts
// they refuse it alike, rule, object and message, and that the compiler builds
// nothing.
// It returns what they refused.
func bothCallers(t *testing.T, load func() *ctm.CTM) []refusal {
	t.Helper()
	reg := registry(t)
	read := validate.Validate(load(), reg)
	files, compiled := compiler.Compile(load(), reg)
	if files != nil {
		t.Error("the compiler built a bundle beside a refusal")
	}
	r, c := refusalsOf(read), refusalsOf(compiled)
	if !slices.Equal(r, c) {
		t.Errorf("validation and the compiler differ:\n read    %+v\n compile %+v", r, c)
	}
	return r
}

// wantRefusals holds the rejections both callers raised to want, exactly. Warnings are
// left out: an artifact warning never refuses anything, it is raised by the same
// pass, and it is asserted where it belongs, in the artifact-name tests below and in
// artifact_names_test.go. bothCallers has already held the two callers' whole lists,
// warnings included, to each other.
func wantRefusals(t *testing.T, got []refusal, want ...refusal) {
	t.Helper()
	for i := range want {
		want[i].severity = string(findings.Rejection)
	}
	rejections := make([]refusal, 0, len(got))
	for _, r := range got {
		if r.severity == string(findings.Rejection) {
			rejections = append(rejections, r)
		}
	}
	if !slices.Equal(rejections, want) {
		t.Errorf("refusals:\n got  %+v\n want %+v", rejections, want)
	}
}

// Every mapping defect fixture is refused by validation and by the compiler in the same
// words: one function, SurveyDevice, words each refusal for both, so an operator cannot
// tell from the message which raised it.
func TestMappingRefusalsAreWordedAlike(t *testing.T) {
	for _, tc := range []struct {
		fixture string
		want    refusal
	}{
		{"port-collision.json", refusal{rule: findings.RuleInterfacePortCollision, object: "c1:eth1",
			message: "port eth1 on c1 would be cabled twice: Ethernet1/1 (rule front) and Ethernet2/1 (rule linecard) both land on it; a bundle whose links cable one port twice is never produced"}},
		{"breakout-parent-cabled.json", refusal{rule: findings.RuleInterfaceBreakoutParentCabled, object: "n1:ethernet-1/1",
			message: "breakout parent ethernet-1/1 is cabled beside its cabled child ethernet-1/1/1 (rule breakout); no platform cables a broken-out port and its child at once"}},
		{"rule-unmatched.json", refusal{rule: findings.RuleInterfaceRuleUnmatched, object: "n1:Ethernet99",
			message: "no rule of the nokia_srlinux profile matches this production name (tried: ethernet, breakout); the profile or the intent must be fixed"}},
		{"unmappable-linked-range.json", refusal{rule: findings.RuleUnmappableLinked, object: "n1:ethernet-1/59",
			message: "rule ethernet matched this production name, but {port} is 59, outside its range 1..58, and it terminates a link"}},
		{"unmappable-linked-unmatched.json", refusal{rule: findings.RuleUnmappableLinked, object: "n1:Ethernet99",
			message: "no rule of the nokia_srlinux profile matches this production name (tried: ethernet, breakout), and it terminates a link"}},
	} {
		t.Run(tc.fixture, func(t *testing.T) {
			got := bothCallers(t, func() *ctm.CTM { return loadCTM(t, "testdata", "ctm", "defects", tc.fixture) })
			wantRefusals(t, got, tc.want)
		})
	}
}

// Under a collapsing breakout rule a parent and its child render one port, so both cabled
// is two defects at once: the port would be cabled twice, and the parent is cabled beside
// its child. One pass names both, from both callers. This is why the
// single-defect breakout fixture is SR Linux's spreading rule, where the two land apart.
func TestCollapsingParentAndChildCabledRaisesBoth(t *testing.T) {
	got := bothCallers(t, func() *ctm.CTM {
		// port-collision.json's devices and artifacts, with c1's two cabled interfaces
		// renamed to a parent and its child.
		c := loadCTM(t, "testdata", "ctm", "defects", "port-collision.json")
		parent, child := "c1:Ethernet1/49|c2:Ethernet1/1", "c1:Ethernet1/49/1|c2:Ethernet1/2"
		c.Device("c1").Interfaces = []ctm.Interface{
			{Name: "Ethernet1/49", Iftype: ctm.IftypePhysical, Link: parent},
			{Name: "Ethernet1/49/1", Iftype: ctm.IftypePhysical, Link: child},
		}
		c.Device("c2").Interfaces = []ctm.Interface{
			{Name: "Ethernet1/1", Iftype: ctm.IftypePhysical, Link: parent},
			{Name: "Ethernet1/2", Iftype: ctm.IftypePhysical, Link: child},
		}
		c.Links = []ctm.Link{
			{ID: parent, Endpoints: []ctm.Endpoint{{Device: "c1", Interface: "Ethernet1/49"}, {Device: "c2", Interface: "Ethernet1/1"}}},
			{ID: child, Endpoints: []ctm.Endpoint{{Device: "c1", Interface: "Ethernet1/49/1"}, {Device: "c2", Interface: "Ethernet1/2"}}},
		}
		return c
	})
	wantRefusals(t, got,
		refusal{rule: findings.RuleInterfaceBreakoutParentCabled, object: "c1:Ethernet1/49",
			message: "breakout parent Ethernet1/49 is cabled beside its cabled child Ethernet1/49/1 (rule breakout); no platform cables a broken-out port and its child at once"},
		refusal{rule: findings.RuleInterfacePortCollision, object: "c1:eth49",
			message: "port eth49 on c1 would be cabled twice: Ethernet1/49 (rule front) and Ethernet1/49/1 (rule breakout) both land on it; a bundle whose links cable one port twice is never produced"},
	)
}

// A collision names every interface that lands on the port, not only the cabled ones
// that collided. Ethernet3/1 falls to the linecard rule and
// renders eth1 like the other two, but no link touches it: it is named last, apart from
// the cabled pair, and from both callers alike.
func TestPortCollisionNamesItsUncabledMembers(t *testing.T) {
	got := bothCallers(t, func() *ctm.CTM {
		c := loadCTM(t, "testdata", "ctm", "defects", "port-collision.json")
		c1 := c.Device("c1")
		c1.Interfaces = append(c1.Interfaces, ctm.Interface{Name: "Ethernet3/1", Iftype: ctm.IftypePhysical})
		return c
	})
	wantRefusals(t, got, refusal{rule: findings.RuleInterfacePortCollision, object: "c1:eth1",
		message: "port eth1 on c1 would be cabled twice: Ethernet1/1 (rule front) and Ethernet2/1 (rule linecard) both land on it; " +
			"Ethernet3/1 (rule linecard) also lands on it, uncabled; a bundle whose links cable one port twice is never produced"})
}

// Every device is surveyed before the compiler returns, so defects on two devices are
// named in one pass, as validation names them: an operator fixing intent sees the whole
// list, not one device per attempt.
func TestMappingRefusalsOnTwoDevicesInOnePass(t *testing.T) {
	got := bothCallers(t, func() *ctm.CTM {
		c := loadCTM(t, "testdata", "ctm", "defects", "rule-unmatched.json")
		n3 := c.Device("n3")
		n3.Interfaces = append(n3.Interfaces, ctm.Interface{Name: "Port-Channel1", Iftype: ctm.IftypePhysical})
		return c
	})
	const tried = "no rule of the nokia_srlinux profile matches this production name (tried: ethernet, breakout); the profile or the intent must be fixed"
	wantRefusals(t, got,
		refusal{rule: findings.RuleInterfaceRuleUnmatched, object: "n1:Ethernet99", message: tried},
		refusal{rule: findings.RuleInterfaceRuleUnmatched, object: "n3:Port-Channel1", message: tried},
	)
}

// A production management name left unflagged is not management (D-003: the profile
// never infers use from a name). The data rules are applied to it like any other name,
// none of the design case's three matches `Management1`, and both callers say so in the
// rules they tried, so the operator sees the flag is missing.
func TestUnflaggedManagementNameIsRefusedAlike(t *testing.T) {
	got := bothCallers(t, func() *ctm.CTM {
		c := loadCTM(t, "testdata", "ctm", "lossy.json")
		c.Device("c1").Interface("Management1").MgmtOnly = false
		return c
	})
	wantRefusals(t, got, refusal{rule: findings.RuleInterfaceRuleUnmatched, object: "c1:Management1",
		message: "no rule of the chassisos profile matches this production name " +
			"(tried: front, linecard, breakout); the profile or the intent must be fixed"})
}

// bothCallersClean runs validation and the compiler on two copies of one intent that
// neither refuses, asserts they report it alike, and asserts the compiler built the
// bundle anyway: a warning is not a refusal. It returns what they reported.
func bothCallersClean(t *testing.T, load func() *ctm.CTM) []refusal {
	t.Helper()
	reg := registry(t)
	read := validate.Validate(load(), reg)
	files, compiled := compiler.Compile(load(), reg)
	if read.Rejected() || compiled.Rejected() {
		t.Fatalf("intent was refused:\n read    %+v\n compile %+v", read, compiled)
	}
	if files == nil {
		t.Error("the compiler returned no bundle for intent nothing refused")
	}
	r, c := reported(read), reported(compiled)
	if !slices.Equal(r, c) {
		t.Errorf("validation and the compiler differ:\n read    %+v\n compile %+v", r, c)
	}
	return r
}

// reported is what an operator is told, less the omissions. A compiler that built a
// bundle also reports every omission it recorded in the manifest, and validation reports
// none of them: an omission is the compiler's account of what it built, not a rule
// validation could have run on intent alone (M6). Everything else — the refusals and the
// warnings — both callers must word alike.
func reported(list findings.List) []refusal {
	kept := make(findings.List, 0, len(list))
	for _, f := range list {
		if f.Severity != findings.Info {
			kept = append(kept, f)
		}
	}
	return refusalsOf(kept)
}

func warning(object, message string) refusal {
	return refusal{severity: string(findings.Warning), rule: findings.RuleArtifactInterfaceUnrepresented,
		object: object, message: message}
}

// The design case's artifacts name four interfaces the node calls something else, and
// both callers say so in the same words at the same lines. The
// twin is built either way: the artifact is pushed as production wrote it, and what the
// node makes of a line naming a port it has under another name is the node's business.
//
// Both artifacts also name Loopback0, whose row has no port: the node calls it nothing at
// all, its disposition says so, and it draws no warning. Nothing here is omitted, so no
// omitted warning is possible on the fixture as it stands — that case is built below.
func TestArtifactRenamedWarningsAreWordedAlike(t *testing.T) {
	got := bothCallersClean(t, func() *ctm.CTM { return loadCTM(t, "testdata", "ctm", "lossy.json") })
	const renamed = "artifact device-config names interface %s at line %d, which the node calls %s; " +
		"the line is pushed as production wrote it"
	if !slices.Equal(got, []refusal{
		warning("c1:Ethernet1/1", fmt.Sprintf(renamed, "Ethernet1/1", 3, "Ethernet1")),
		warning("c1:Ethernet1/49/1", fmt.Sprintf(renamed, "Ethernet1/49/1", 6, "Ethernet49")),
		warning("c2:Ethernet1/49/1", fmt.Sprintf(renamed, "Ethernet1/49/1", 3, "Ethernet49")),
		warning("c2:Ethernet2/1", fmt.Sprintf(renamed, "Ethernet2/1", 6, "Ethernet1")),
	}) {
		t.Errorf("the lossy fixture's warnings:\n%+v", got)
	}
}

// An artifact naming an interface the twin omits is the warning's other case, and it
// carries the omission's own reason, word for word, so the operator reads one sentence
// rather than two accounts of one decision.
//
// The case is built here rather than on disk: editing the fixture's artifact would move
// the lossy golden for something that is not a format change, and a golden moves for a
// format change alone. c1:Ethernet1/53 is out of its rule's range and uncabled, so the mapping omits
// it; the line is appended to c1's artifact and its checksum recomputed, as the CTM's own
// guard requires.
func TestArtifactOmittedWarningCarriesTheOmissionsReason(t *testing.T) {
	got := bothCallersClean(t, func() *ctm.CTM {
		c := loadCTM(t, "testdata", "ctm", "lossy.json")
		a := c.Device("c1").Artifact
		a.Content += "interface Ethernet1/53\n   no switchport\n"
		a.Checksum = ctm.ChecksumOf(a.Content)
		return c
	})
	want := warning("c1:Ethernet1/53", "artifact device-config names interface Ethernet1/53 at line 10, "+
		"which the twin does not represent: omitted (omit.interface.unmappable: rule front matched, but {port} is 53, "+
		"outside its range 1..52; no such port on the node)")
	if !slices.Contains(got, want) {
		t.Errorf("the omitted warning is missing:\n got  %+v\n want %+v", got, want)
	}
	if len(got) != 5 {
		t.Errorf("%d warnings, want the fixture's four and the omitted one:\n%+v", len(got), got)
	}
}
