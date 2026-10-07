package cli

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// A rejection leaves nothing behind. Not a partial bundle, not an empty directory:
// M2 deploys whatever is at --out, so anything there is a claim that a twin can be
// built from it.
func TestRejectionLeavesNothingBehind(t *testing.T) {
	entries, err := os.ReadDir(repoPath("testdata", "ctm", "defects"))
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			out := filepath.Join(t.TempDir(), "b")
			code, doc := runCompileTo(t, repoPath("testdata", "ctm", "defects", e.Name()), out)
			if code != 1 {
				t.Fatalf("exit %d, want 1 (a rejection): %+v", code, doc.Findings)
			}
			if doc.Status != "rejected" {
				t.Errorf("status = %q, want rejected", doc.Status)
			}
			if doc.BundleID != "" {
				t.Errorf("a rejected compile reported bundle_id %q", doc.BundleID)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("a rejected compile left something at %s", out)
			}
			var rejections int
			for _, f := range doc.Findings {
				if f.Severity == string(findings.Rejection) {
					rejections++
				}
				if f.Object == "" {
					t.Errorf("finding %s names no object", f.Rule)
				}
			}
			if rejections == 0 {
				t.Errorf("status is rejected but no finding is a rejection: %+v", doc.Findings)
			}
		})
	}
}

// A refusal's machine-readable half: five defects, five findings, in one document, each
// naming its object.
func TestFiveDefectsGiveFiveFindings(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "defects", "five.json"), out)
	if code != 1 {
		t.Fatalf("exit %d, want 1", code)
	}
	if doc.Status != "rejected" {
		t.Errorf("status = %q, want rejected", doc.Status)
	}
	if len(doc.Findings) != 5 {
		t.Fatalf("got %d findings, want exactly 5:\n%+v", len(doc.Findings), doc.Findings)
	}

	var got []string
	for _, f := range doc.Findings {
		got = append(got, f.Rule+" "+f.Object)
	}
	sort.Strings(got)
	want := []string{
		"device.name.duplicate n1",
		"interface.iftype.unimplemented n1:lo0",
		"interface.mgmt_only.iftype n3:lo0",
		"link.endpoints.count n1:ethernet-1/1|n2:ethernet-1/1",
		"platform.unsupported n2",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("findings differ from the fixture's five defects:\n--- got\n%s\n--- want\n%s",
			strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("a rejected compile left something at %s", out)
	}
}

// An empty read names the branch it came from, because a wrong `at` is almost always
// what produced it and the branch is half of what the operator has to correct.
func TestEmptyCTMIsRefusedNamingTheBranch(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "defects", "devices-empty.json"), out)
	if code != 1 {
		t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
	}
	var found bool
	for _, f := range doc.Findings {
		if f.Rule != findings.RuleDevicesEmpty {
			continue
		}
		found = true
		if !strings.Contains(f.Object, "fylgja-fixture") {
			t.Errorf("object %q does not name the branch", f.Object)
		}
		if !strings.Contains(f.Message, "fylgja-fixture") {
			t.Errorf("message %q does not name the branch", f.Message)
		}
	}
	if !found {
		t.Errorf("expected %s, got %+v", findings.RuleDevicesEmpty, doc.Findings)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("an empty CTM wrote something to %s", out)
	}
}

// Compiling into a directory that already holds something is exit 2 and leaves it
// byte-identical: a bundle carrying files from two compiles would be a quiet lie, and
// clobbering somebody's directory because they mistyped --out would be worse.
func TestNonEmptyOutputDirectoryIsRefusedAndUntouched(t *testing.T) {
	root := t.TempDir()
	out := filepath.Join(root, "b")

	if code, doc := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), out); code != 0 {
		t.Fatalf("first compile: exit %d: %+v", code, doc.Findings)
	}
	before := snapshot(t, out)

	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), out)
	if code != 2 {
		t.Fatalf("exit %d, want 2 (an operational failure): %+v", code, doc.Findings)
	}
	if doc.Status != "error" {
		t.Errorf("status = %q, want error", doc.Status)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Errorf("expected one %s, got %+v", findings.RuleOperationFailed, doc.Findings)
	}
	if !strings.Contains(doc.Findings[0].Message, "not empty") {
		t.Errorf("message does not say the directory is not empty: %q", doc.Findings[0].Message)
	}

	if after := snapshot(t, out); after != before {
		t.Errorf("the refused compile changed the directory:\n--- before\n%s\n--- after\n%s", before, after)
	}

	// Nor may it leave a staging directory beside the target.
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.Name() != "b" {
			t.Errorf("refusal left %s beside the target", e.Name())
		}
	}
}

// snapshot renders a directory's files and bytes as one comparable string.
func snapshot(t *testing.T, dir string) string {
	t.Helper()
	var lines []string
	err := filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		lines = append(lines, filepath.ToSlash(rel)+"\n"+string(b))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}
