package bundle

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

// The three goldens load whole, and the map hashes to the directory's id: LoadFiles and
// IDOfDir walk alike, so a step's from bundle is the bundle the record names. The ids are
// the goldens' own, which M12's bundle "4" moved once.
func TestLoadFilesReadsEveryGolden(t *testing.T) {
	for _, c := range []struct{ golden, id string }{
		{"three-node", "23f86a26"},
		{"lossy", "5773b6bb"},
		{"mixed", "391bcb96"},
	} {
		t.Run(c.golden, func(t *testing.T) {
			dir := filepath.Join("..", "..", "testdata", "golden", c.golden)
			files, err := LoadFiles(dir)
			if err != nil {
				t.Fatal(err)
			}
			fromDir, err := IDOfDir(dir)
			if err != nil {
				t.Fatal(err)
			}
			if got := ID(files); got != fromDir {
				t.Errorf("ID(LoadFiles) = %s, IDOfDir = %s", got, fromDir)
			}
			if !strings.HasPrefix(fromDir, c.id) {
				t.Errorf("the golden's id is %s, want %s…", fromDir, c.id)
			}
			if _, ok := files["manifest.json"]; !ok {
				t.Errorf("no manifest.json among %d files", len(files))
			}
			for name, got := range files {
				if strings.Contains(name, `\`) || strings.HasPrefix(name, "/") || strings.HasPrefix(name, "./") {
					t.Errorf("%q is not a slash-separated path relative to the bundle", name)
				}
				want, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(name)))
				if err != nil || string(got) != string(want) {
					t.Errorf("%s was not read byte for byte (%v)", name, err)
				}
			}
		})
	}
}

// What a bundle cannot hold is refused, naming it, where IDOfDir would skip it: the map
// must be the directory, not a part of it.
func TestLoadFilesRefusals(t *testing.T) {
	bundle := func(t *testing.T) string {
		t.Helper()
		dir := filepath.Join(t.TempDir(), "b")
		if err := Write(sample(), dir); err != nil {
			t.Fatal(err)
		}
		return dir
	}
	for _, c := range []struct {
		label string
		make  func(t *testing.T, dir string) string // returns the directory to load
		want  string
	}{
		{"a symbolic link to a file", func(t *testing.T, dir string) string {
			if err := os.Symlink("../manifest.json", filepath.Join(dir, "configs", "extra.cli")); err != nil {
				t.Fatal(err)
			}
			return dir
		}, "configs/extra.cli is a symbolic link; a bundle holds regular files only"},
		{"a symbolic link to a directory", func(t *testing.T, dir string) string {
			if err := os.Symlink("configs", filepath.Join(dir, "more")); err != nil {
				t.Fatal(err)
			}
			return dir
		}, "more is a symbolic link; a bundle holds regular files only"},
		{"a named pipe", func(t *testing.T, dir string) string {
			pipe := filepath.Join(dir, "configs", "pipe")
			if err := syscall.Mkfifo(pipe, 0o600); err != nil {
				t.Skipf("no named pipes here: %v", err)
			}
			// A writer that opens and closes at once, so a LoadFiles that read the pipe
			// would get its end and accept it, failing this case, rather than hang the
			// suite. The cleanup opens the read end without blocking, to release the
			// writer when LoadFiles rightly never opened it.
			go func() {
				if f, err := os.OpenFile(pipe, os.O_WRONLY, 0); err == nil {
					_ = f.Close()
				}
			}()
			t.Cleanup(func() {
				if f, err := os.OpenFile(pipe, os.O_RDONLY|syscall.O_NONBLOCK, 0); err == nil {
					_ = f.Close()
				}
			})
			return dir
		}, "configs/pipe is not a regular file"},
		{"a file, not a directory", func(t *testing.T, dir string) string {
			return filepath.Join(dir, "manifest.json")
		}, "manifest.json is not a directory"},
		{"a symbolic link as the bundle", func(t *testing.T, dir string) string {
			link := filepath.Join(filepath.Dir(dir), "link")
			if err := os.Symlink(dir, link); err != nil {
				t.Fatal(err)
			}
			return link
		}, "link is not a directory"},
	} {
		t.Run(c.label, func(t *testing.T) {
			dir := c.make(t, bundle(t))
			files, err := LoadFiles(dir)
			if err == nil {
				t.Fatalf("LoadFiles accepted it: %d files", len(files))
			}
			if !strings.Contains(err.Error(), c.want) {
				t.Errorf("error = %q, want it to say %q", err, c.want)
			}
		})
	}
}

// A path the walk is handed outside the bundle is refused, naming it. WalkDir never hands
// one over, so the guard is tested where it lives.
func TestInsideBundleRefusesAPathOutOfIt(t *testing.T) {
	dir := filepath.Join("srv", "bundles", "b")
	if rel, err := insideBundle(dir, filepath.Join(dir, "configs", "s1.cli")); err != nil || rel != "configs/s1.cli" {
		t.Errorf("insideBundle = %q, %v; want configs/s1.cli", rel, err)
	}
	for _, p := range []string{filepath.Join("srv", "bundles", "other", "manifest.json"), filepath.Join("srv", "bundles")} {
		if _, err := insideBundle(dir, p); err == nil || !strings.Contains(err.Error(), "leads out of the bundle") {
			t.Errorf("insideBundle(%s) = %v, want it refused as leading out of the bundle", p, err)
		}
	}
}
