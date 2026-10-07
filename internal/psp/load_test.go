package psp

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// overrideWith puts one support package file into a fresh override directory and
// returns the directory and the copy's path.
func overrideWith(t *testing.T, src string) (dir, path string) {
	t.Helper()
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	dir = t.TempDir()
	path = filepath.Join(dir, filepath.Base(src))
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir, path
}

// An override package `psp validate` rejects is refused when loaded, with the rule
// that names its defect and the file it is in, so no command accepts it and fails
// later under a different identifier.
func TestInvalidOverrideIsRefusedAtLoad(t *testing.T) {
	for _, tc := range []struct{ fixture, rule string }{
		{"version-unknown", findings.RulePSPVersionUnknown},
		{"no-encoding", findings.RulePSPReadinessEncoding},
	} {
		t.Run(tc.fixture, func(t *testing.T) {
			dir, path := overrideWith(t, repo("testdata", "psp", "defects", tc.fixture+".yaml"))
			reg, err := Load(dir)
			var inv *InvalidError
			if !errors.As(err, &inv) {
				t.Fatalf("Load = %v, %v; want *InvalidError", reg, err)
			}
			var found bool
			for _, f := range inv.Findings {
				if f.Rule != tc.rule {
					continue
				}
				found = true
				if f.Location == nil || f.Location.File != path {
					t.Errorf("%s carries location %+v, want %s", f.Rule, f.Location, path)
				}
			}
			if !found {
				t.Errorf("findings %v do not carry %s", inv.Findings, tc.rule)
			}
			if msg := err.Error(); !strings.Contains(msg, tc.rule) || !strings.Contains(msg, path) {
				t.Errorf("error %q must name the rule and the file", msg)
			}
		})
	}
}

// Only rejections refuse a load: a package with a note is usable, as `psp validate`
// says it is.
func TestOverrideWithOnlyANoteLoads(t *testing.T) {
	dir, _ := overrideWith(t, repo("testdata", "psp", "defects", "vrnetlab.yaml"))
	reg, err := Load(dir)
	if err != nil {
		t.Fatalf("a package with only a note must load: %v", err)
	}
	if p, ok := reg.Lookup("srlinux"); !ok || p.Image.Acquisition != AcquisitionVrnetlabVM {
		t.Errorf("the override did not load: %+v", p)
	}
}

// A manifest names packages by platform id and containerlab reports containers by
// kind; both joins resolve embedded and override packages alike.
func TestLookupByIDAndKind(t *testing.T) {
	reg, err := Load(repo("testdata", "psp", "heterogeneous"))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		lookup func(string) (*PSP, bool)
		key    string
		wantID string
		origin string
	}{
		{reg.LookupID, "nokia_srlinux", "nokia_srlinux", OriginEmbedded},
		{reg.LookupID, "slowos", "slowos", OriginOverride},
		{reg.LookupID, "no_such_platform", "", ""},
		{reg.LookupKind, "nokia_srlinux", "nokia_srlinux", OriginEmbedded},
		{reg.LookupKind, "fastos", "fastos", OriginOverride},
		{reg.LookupKind, "linux", "", ""},
	} {
		p, ok := tc.lookup(tc.key)
		if tc.wantID == "" {
			if ok {
				t.Errorf("%s resolved to %s; want no package", tc.key, p.Platform.ID)
			}
			continue
		}
		if !ok || p.Platform.ID != tc.wantID || p.Origin != tc.origin {
			t.Errorf("%s = %+v, %v; want id %s from %s", tc.key, p, ok, tc.wantID, tc.origin)
		}
	}
}

func TestEmbeddedLoads(t *testing.T) {
	r, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	p, ok := r.Lookup("srlinux")
	if !ok {
		t.Fatalf("srlinux not registered; have %v", r.Platforms())
	}
	if p.Config.StartupFormat != "cli" || len(p.Config.Bootstrap) == 0 {
		t.Errorf("bootstrap not loaded: %+v", p.Config)
	}
	prof, err := NewProfile(p)
	if err != nil {
		t.Fatalf("the embedded package's profile does not compile: %v", err)
	}
	if prof.ManagementPort() != "mgmt0" || p.Origin != OriginEmbedded {
		t.Errorf("unexpected: mgmt=%q origin=%q", prof.ManagementPort(), p.Origin)
	}
}

// A support package in the override directory shadows the embedded one with the same
// NOS identifier. This is how an experimental platform is tried without a rebuild
// (D-018), and how a lab host runs a locally patched package.
func TestOverrideDirectoryShadowsEmbedded(t *testing.T) {
	embedded, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	base, _ := embedded.Lookup("srlinux")

	dir := t.TempDir()
	src, err := os.ReadFile(filepath.Join("..", "..", "psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	patched := strings.Replace(string(src),
		"ref: "+base.Image.Ref, "ref: example.invalid/srlinux:override", 1)
	if patched == string(src) {
		t.Fatalf("could not patch the image reference; package format changed?")
	}
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), []byte(patched), 0o644); err != nil {
		t.Fatal(err)
	}

	reg, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	got, ok := reg.Lookup("srlinux")
	if !ok {
		t.Fatal("srlinux disappeared when an override directory was supplied")
	}
	if got.Image.Ref != "example.invalid/srlinux:override" {
		t.Errorf("image ref = %q, want the override's", got.Image.Ref)
	}
	if got.Origin != OriginOverride {
		t.Errorf("origin = %q, want %q — the manifest records this, so a twin says what it was built with", got.Origin, OriginOverride)
	}
	// Platforms the override does not mention are untouched.
	if len(reg.Platforms()) != len(embedded.Platforms()) {
		t.Errorf("override changed the platform set: %v vs %v", reg.Platforms(), embedded.Platforms())
	}
}

func TestMissingOverrideDirectoryIsReported(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "does-not-exist")); err == nil {
		t.Error("a named override directory that does not exist must be reported, not ignored")
	}
}

// `psp validate` never contacts the network: that is what makes it usable in
// CI on a contributed package, and what makes "valid" a statement about the file
// rather than about what some registry happened to answer.
//
// The check is over the whole transitive closure, not this package's own imports: a
// dependency that dialled out would break the guarantee just as surely, and only the
// closure can see that. It is scoped to internal/psp deliberately — cmd/fylgja
// necessarily imports internal/intent, so the command-level guarantee is the psp
// tests in cmd/fylgja, which touch no address at all.
func TestValidationReachesNoNetwork(t *testing.T) {
	out, err := exec.Command("go", "list", "-deps", ".").Output()
	if err != nil {
		t.Skipf("the go tool is needed to walk the import closure: %v", err)
	}
	forbidden := map[string]string{
		"net":      "network I/O",
		"net/http": "network I/O",
		"github.com/happypathnetworking/fylgja/internal/intent": "intent reaches Infrahub",
	}
	var closure int
	for _, dep := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		dep = strings.TrimSpace(dep)
		if dep == "" {
			continue
		}
		closure++
		if why, bad := forbidden[dep]; bad {
			t.Errorf("internal/psp depends on %q (%s): validation must stay offline", dep, why)
		}
	}
	if closure == 0 {
		t.Fatal("the import closure came back empty; the check proved nothing")
	}
}
