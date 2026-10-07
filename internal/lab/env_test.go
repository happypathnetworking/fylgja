package lab

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolvePathsDefaultsUnderWorkingDirectory(t *testing.T) {
	t.Setenv(EnvStateRoot, "")
	t.Chdir(t.TempDir())
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	p, err := ResolvePaths()
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(wd, "local")
	want := Paths{
		Root:       root,
		Bundles:    filepath.Join(root, "bundles"),
		Twin:       filepath.Join(root, "twin"),
		TwinBundle: filepath.Join(root, "twin", "bundle"),
		TwinJSON:   filepath.Join(root, "twin", "twin.json"),
	}
	if p != want {
		t.Errorf("ResolvePaths() = %+v, want %+v", p, want)
	}
}

// A relative FYLGJA_STATE_ROOT is made absolute at once: the path crosses the task
// queue, where a relative one would mean whatever the worker's directory is.
func TestResolvePathsMakesTheEnvironmentValueAbsolute(t *testing.T) {
	t.Chdir(t.TempDir())
	t.Setenv(EnvStateRoot, "state")
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	p, err := ResolvePaths()
	if err != nil {
		t.Fatal(err)
	}
	if !filepath.IsAbs(p.Root) || p.Root != filepath.Join(wd, "state") {
		t.Errorf("root = %q, want %q", p.Root, filepath.Join(wd, "state"))
	}
	if p.TwinJSON != filepath.Join(wd, "state", "twin", "twin.json") {
		t.Errorf("twin.json = %q", p.TwinJSON)
	}
}

func TestHostBudgetMB(t *testing.T) {
	for _, tc := range []struct {
		label   string
		env     map[string]string
		mb      int
		set     bool
		wantErr bool
	}{
		{"unset", map[string]string{}, 0, false, false},
		{"empty", map[string]string{EnvHostMemoryMB: ""}, 0, false, false},
		{"set", map[string]string{EnvHostMemoryMB: "4096"}, 4096, true, false},
		{"zero", map[string]string{EnvHostMemoryMB: "0"}, 0, false, true},
		{"negative", map[string]string{EnvHostMemoryMB: "-1"}, 0, false, true},
		{"not a number", map[string]string{EnvHostMemoryMB: "4GiB"}, 0, false, true},
		{"fractional", map[string]string{EnvHostMemoryMB: "1.5"}, 0, false, true},
	} {
		t.Run(tc.label, func(t *testing.T) {
			getenv := func(k string) (string, bool) { v, ok := tc.env[k]; return v, ok }
			mb, set, err := HostBudgetMB(getenv)
			if (err != nil) != tc.wantErr {
				t.Fatalf("err = %v, want error %v", err, tc.wantErr)
			}
			if mb != tc.mb || set != tc.set {
				t.Errorf("HostBudgetMB = %d, %v; want %d, %v", mb, set, tc.mb, tc.set)
			}
		})
	}
}
