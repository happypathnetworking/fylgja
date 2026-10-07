package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// runPSPDoc exercises the command flow exactly as the CLI does. Nothing here touches
// the network: that is the point of the command.
func runPSPDoc(t *testing.T, paths ...string) (int, *findingsDoc) {
	t.Helper()
	err := runPSPValidate(&options{asJSON: true}, paths)
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runPSPValidate returned %v, want a findings result", err)
	}
	b, mErr := json.Marshal(res.doc)
	if mErr != nil {
		t.Fatal(mErr)
	}
	var doc findingsDoc
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatal(err)
	}
	return res.doc.Status.ExitCode(), &doc
}

func defectPath(name string) string {
	return repoPath("testdata", "psp", "defects", name)
}

// The package Fylgja ships must validate with the validator Fylgja ships: M1 claims
// SR Linux is supported, and this is the structural half of that claim.
func TestShippedPackageValidatesClean(t *testing.T) {
	code, doc := runPSPDoc(t, repoPath("psp", "nokia_srlinux.yaml"))
	if code != findings.ExitOK {
		t.Fatalf("exit %d, want 0: %+v", code, doc.Findings)
	}
	if doc.Status != string(findings.StatusOK) {
		t.Errorf("status = %q, want ok", doc.Status)
	}
	for _, f := range doc.Findings {
		if f.Severity == string(findings.Rejection) {
			t.Errorf("the shipped package was rejected: %s %s", f.Rule, f.Message)
		}
	}
}

// Each defect is reported by the rule that names it, with the file it is in: a
// platform author with several files on the command line needs both.
func TestDefectFixturesAreNamedWithTheirLocation(t *testing.T) {
	for _, tc := range []struct {
		fixture string
		rule    string
	}{
		{"placeholders-disagree.yaml", findings.RulePSPPatternsPlaceholders},
		{"lossy-undeclared.yaml", findings.RulePSPPatternsPlaceholders},
		{"breakout-parent-is-match.yaml", findings.RulePSPPatternsBreakout},
		{"management-collides.yaml", findings.RulePSPManagementCollides},
		{"rule-name-duplicate.yaml", findings.RulePSPRuleName},
		{"management-rule-missing.yaml", findings.RulePSPManagementRule},
		{"mappings-unknown-rule.yaml", findings.RulePSPMappingsInvalid},
		{"facet-missing.yaml", findings.RulePSPSchema},
		{"version-unknown.yaml", findings.RulePSPVersionUnknown},
		{"version-0-5.yaml", findings.RulePSPVersionUnknown},
		{"version-0-5-m10.yaml", findings.RulePSPVersionUnknown},
		{"version-0-3-m5.yaml", findings.RulePSPVersionUnknown},
		{"fidelity-link-change-missing.yaml", findings.RulePSPSchema},
		{"bootstrap-via-no-lines.yaml", findings.RulePSPConfigBootstrapVia},
		{"tls-not-boolean.yaml", findings.RulePSPSchema},
		{"eapi-without-push.yaml", findings.RulePSPConfigPushMissing},
	} {
		t.Run(tc.fixture, func(t *testing.T) {
			path := defectPath(tc.fixture)
			code, doc := runPSPDoc(t, path)
			if code != findings.ExitRejected {
				t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
			}
			var found bool
			for _, f := range doc.Findings {
				if f.Rule == tc.rule {
					found = true
				}
				if f.Location == nil || f.Location.File != path {
					t.Errorf("finding %s carries no location in %s", f.Rule, path)
				}
			}
			if !found {
				t.Errorf("rule %s not reported: %+v", tc.rule, doc.Findings)
			}
		})
	}
}

// Implausible values are warnings, not rejections: a platform author may know
// something the validator does not, so a surprising package must stay reportable
// rather than become unusable. The fixture also trips the schema's own minimums, so
// the assertion is about the severity of these two rules, not about the exit code.
func TestImplausibleValuesAreWarnings(t *testing.T) {
	_, doc := runPSPDoc(t, defectPath("implausible-resources.yaml"))
	seen := map[string]string{}
	for _, f := range doc.Findings {
		seen[f.Rule] = f.Severity
	}
	for _, rule := range []string{
		findings.RulePSPResourcesImplausible,
		findings.RulePSPReadinessImplausible,
	} {
		sev, ok := seen[rule]
		if !ok {
			t.Errorf("rule %s not reported: %+v", rule, doc.Findings)
			continue
		}
		if sev != string(findings.Warning) {
			t.Errorf("%s severity = %s, want warning", rule, sev)
		}
	}
}

// A VM-packaged image is a note, not a defect: the hardware virtualization
// requirement has to surface here rather than at deploy time on a host that lacks it.
func TestVMPackagingIsANoteNotADefect(t *testing.T) {
	code, doc := runPSPDoc(t, defectPath("vrnetlab.yaml"))
	if code != findings.ExitOK {
		t.Fatalf("exit %d, want 0: %+v", code, doc.Findings)
	}
	var found bool
	for _, f := range doc.Findings {
		if f.Rule == findings.RulePSPAcquisitionKVM {
			found = true
			if f.Severity != string(findings.Info) {
				t.Errorf("%s severity = %s, want info", f.Rule, f.Severity)
			}
		}
	}
	if !found {
		t.Errorf("VM packaging produced no note at all: %+v", doc.Findings)
	}
}

// Every defect in one pass: a platform author fixes the file once rather than
// discovering the next problem after each fix.
func TestSeveralDefectsInOnePass(t *testing.T) {
	code, doc := runPSPDoc(t, defectPath("several.yaml"))
	if code != findings.ExitRejected {
		t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
	}
	byRule := map[string]int{}
	for _, f := range doc.Findings {
		byRule[f.Rule]++
	}
	for _, want := range []string{
		findings.RulePSPPatternsPlaceholders,
		findings.RulePSPManagementCollides,
		findings.RulePSPVersionUnknown,
	} {
		if byRule[want] == 0 {
			t.Errorf("rule %s missing from a single pass: %+v", want, doc.Findings)
		}
	}
}

// The cross-file rule is why validate takes a set: two packages each valid alone are
// a defect side by side, and only a command that sees both can say so.
func TestDuplicateIdentityIsFoundAcrossTheSet(t *testing.T) {
	shipped := repoPath("psp", "nokia_srlinux.yaml")
	copied := defectPath("duplicate-identity.yaml")

	code, doc := runPSPDoc(t, shipped, copied)
	if code != findings.ExitRejected {
		t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
	}
	var found bool
	for _, f := range doc.Findings {
		if f.Rule == findings.RulePSPIdentityDuplicate {
			found = true
		}
	}
	if !found {
		t.Fatalf("duplicate identity not reported across the set: %+v", doc.Findings)
	}
	// Each file alone is fine; only the pair is a problem.
	if code, _ := runPSPDoc(t, copied); code != findings.ExitOK {
		t.Errorf("the second copy was rejected on its own (exit %d)", code)
	}
}

// A file Fylgja cannot read, or that holds more than one YAML document, is an
// operational failure naming the file — not a finding about a package nothing has
// seen (contracts/cli.md, exit 2).
func TestUnreadableAndMultiDocumentFilesAreOperationalFailures(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "no-such-package.yaml")

	multi := filepath.Join(t.TempDir(), "two-documents.yaml")
	shipped, err := os.ReadFile(repoPath("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(multi, append(append([]byte{}, shipped...), append([]byte("\n---\n"), shipped...)...), 0o644); err != nil {
		t.Fatal(err)
	}

	for _, tc := range []struct {
		name string
		path string
	}{
		{"unreadable", missing},
		{"multi-document", multi},
	} {
		t.Run(tc.name, func(t *testing.T) {
			code, doc := runPSPDoc(t, tc.path)
			if code != findings.ExitError {
				t.Fatalf("exit %d, want 2: %+v", code, doc.Findings)
			}
			if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
				t.Fatalf("want one operation.failed finding, got %+v", doc.Findings)
			}
			if !strings.Contains(doc.Findings[0].Message, filepath.Base(tc.path)) {
				t.Errorf("message does not name the file: %s", doc.Findings[0].Message)
			}
		})
	}
}

// An unreadable file in a set stops the whole run: the cross-file rules are about the
// set, so a partial set would give an answer about a different question.
func TestOneUnreadableFileFailsTheWholeSet(t *testing.T) {
	code, _ := runPSPDoc(t,
		repoPath("psp", "nokia_srlinux.yaml"),
		filepath.Join(t.TempDir(), "absent.yaml"))
	if code != findings.ExitError {
		t.Errorf("exit %d, want 2", code)
	}
}

// Every document this command produces names psp.validate, including its failures.
func TestPSPDocumentsNameTheOperation(t *testing.T) {
	for _, paths := range [][]string{
		{repoPath("psp", "nokia_srlinux.yaml")},
		{defectPath("several.yaml")},
		{filepath.Join(t.TempDir(), "absent.yaml")},
	} {
		_, doc := runPSPDoc(t, paths...)
		if doc.Operation != findings.OpPSPValidate {
			t.Errorf("operation = %q, want %q", doc.Operation, findings.OpPSPValidate)
		}
	}
}
