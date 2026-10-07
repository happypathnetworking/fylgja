// An external test package: it compares with internal/bundle, which imports this one.
package tree_test

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/tree"
)

func golden(t *testing.T, name string) string {
	t.Helper()
	dir, err := filepath.Abs(filepath.Join("..", "..", "testdata", "golden", name))
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

// A golden bundle read and written again is the same bundle, byte for byte and by id: the
// client sends what it read and writes what it was sent.
func TestReadThenWriteIsTheSameBundle(t *testing.T) {
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			src := golden(t, name)
			files, err := tree.Read(src)
			if err != nil {
				t.Fatal(err)
			}
			for _, want := range []string{"manifest.json", "topology.clab.yml"} {
				if _, ok := files[want]; !ok {
					t.Errorf("Read gave no %s: %v", want, keys(files))
				}
			}
			dst := filepath.Join(t.TempDir(), "out")
			if err := tree.Write(files, dst); err != nil {
				t.Fatal(err)
			}
			again, err := tree.Read(dst)
			if err != nil {
				t.Fatal(err)
			}
			if len(again) != len(files) {
				t.Fatalf("read %d files back, wrote %d", len(again), len(files))
			}
			for p, b := range files {
				if !bytes.Equal(again[p], b) {
					t.Errorf("%s: read back %d bytes that differ from the %d written", p, len(again[p]), len(b))
				}
			}
			want, err := bundle.IDOfDir(src)
			if err != nil {
				t.Fatal(err)
			}
			if got, err := bundle.IDOfDir(dst); err != nil || got != want {
				t.Errorf("the written bundle's id is %s (%v), the golden's %s", got, err, want)
			}
		})
	}
}

// Read names a directory it cannot read in bundle.Verify's own words, so a client's refusal
// reads as twin provision's did at M12.
func TestReadWordsTheDirectoryAsVerifyDoes(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "file")
	if err := os.WriteFile(file, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	locked := filepath.Join(root, "locked")
	if err := os.Mkdir(locked, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(locked, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(locked, 0o755) })
	if _, err := os.ReadDir(locked); err == nil {
		t.Skip("the test runs with permission to list a mode 000 directory")
	}

	for _, c := range []struct {
		label, dir, want string
	}{
		{"a missing path", filepath.Join(root, "missing"),
			"reading bundle directory: stat " + filepath.Join(root, "missing") + ": no such file or directory"},
		{"a file", file, "reading bundle directory: " + file + " is not a directory"},
		{"a directory that cannot be listed", locked, "reading bundle directory: open " + locked + ": permission denied"},
	} {
		t.Run(c.label, func(t *testing.T) {
			files, err := tree.Read(c.dir)
			if err == nil || files != nil {
				t.Fatalf("Read(%s) = %v, %v; want a refusal and no files", c.dir, keys(files), err)
			}
			if err.Error() != c.want {
				t.Errorf("Read says %q, want %q", err, c.want)
			}
			if _, verr := bundle.Verify(c.dir); verr == nil || verr.Error() != err.Error() {
				t.Errorf("Read says %q, bundle.Verify %q", err, verr)
			}
		})
	}
}

// Only regular files are read, at their slash-separated path: a sub-directory is descended
// and is no entry of its own, and a symlink is skipped, as bundle.IDOfDir hashes regular
// files alone.
func TestReadTakesRegularFilesAlone(t *testing.T) {
	dir := t.TempDir()
	write := func(rel, body string) {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("manifest.json", "{}\n")
	write("configs/n1.cli", "set / system name host-name n1\n")
	if err := os.Mkdir(filepath.Join(dir, "empty"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(dir, "manifest.json"), filepath.Join(dir, "link.json")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(dir, "configs"), filepath.Join(dir, "configs-link")); err != nil {
		t.Fatal(err)
	}

	files, err := tree.Read(dir)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"manifest.json": "{}\n", "configs/n1.cli": "set / system name host-name n1\n"}
	if len(files) != len(want) {
		t.Errorf("Read gave %v, want %v", keys(files), keys(toBytes(want)))
	}
	for p, body := range want {
		if string(files[p]) != body {
			t.Errorf("%s = %q, want %q", p, files[p], body)
		}
	}
}

// A sub-directory that cannot be listed is skipped, with what it holds, and the read goes on:
// M12's verify read a file it could not reach as one not in the bundle, so the server answers
// as it did. The root's own refusal stays bundle.Verify's (above).
func TestReadSkipsASubDirectoryItCannotList(t *testing.T) {
	dir := t.TempDir()
	for _, rel := range []string{"manifest.json", "configs/n1.cli", "z/n2.cli"} {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(rel), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	locked := filepath.Join(dir, "configs")
	if err := os.Chmod(locked, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(locked, 0o755) })
	if _, err := os.ReadDir(locked); err == nil {
		t.Skip("the test runs with permission to list a mode 000 directory")
	}

	files, err := tree.Read(dir)
	if err != nil {
		t.Fatalf("Read = %v, want the directory read without configs", err)
	}
	want := map[string]string{"manifest.json": "manifest.json", "z/n2.cli": "z/n2.cli"}
	if len(files) != len(want) {
		t.Errorf("Read gave %v, want %v", keys(files), keys(toBytes(want)))
	}
	for p, body := range want {
		if string(files[p]) != body {
			t.Errorf("%s = %q, want %q", p, files[p], body)
		}
	}
}

// A symlink given as the bundle directory is followed: the directory it names is read whole,
// and its bundle written again has its own id. Every sentence still names the link, which is
// the path the operator gave.
func TestReadFollowsASymlinkedRoot(t *testing.T) {
	src := golden(t, "three-node")
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(src, link); err != nil {
		t.Fatal(err)
	}
	want, err := tree.Read(src)
	if err != nil {
		t.Fatal(err)
	}
	files, err := tree.Read(link)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != len(want) {
		t.Fatalf("Read through the link gave %v, want %v", keys(files), keys(want))
	}
	for p, b := range want {
		if !bytes.Equal(files[p], b) {
			t.Errorf("%s: read %d bytes through the link that differ from the %d read directly", p, len(files[p]), len(b))
		}
	}
	dst := filepath.Join(t.TempDir(), "out")
	if err := tree.Write(files, dst); err != nil {
		t.Fatal(err)
	}
	id, err := bundle.IDOfDir(src)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := bundle.IDOfDir(dst); err != nil || got != id {
		t.Errorf("the bundle read through the link has id %s (%v), the golden's %s", got, err, id)
	}

	t.Run("to a directory that cannot be listed", func(t *testing.T) {
		locked := filepath.Join(t.TempDir(), "locked")
		if err := os.Mkdir(locked, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(locked, 0o000); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(locked, 0o755) })
		if _, err := os.ReadDir(locked); err == nil {
			t.Skip("the test runs with permission to list a mode 000 directory")
		}
		link := filepath.Join(t.TempDir(), "link")
		if err := os.Symlink(locked, link); err != nil {
			t.Fatal(err)
		}
		_, err := tree.Read(link)
		if want := "reading bundle directory: open " + link + ": permission denied"; err == nil || err.Error() != want {
			t.Errorf("Read = %v, want %q", err, want)
		}
	})

	t.Run("an unreadable file through it", func(t *testing.T) {
		dir := t.TempDir()
		p := filepath.Join(dir, "manifest.json")
		if err := os.WriteFile(p, []byte("{}\n"), 0o000); err != nil {
			t.Fatal(err)
		}
		if _, err := os.ReadFile(p); err == nil {
			t.Skip("the test runs with permission to read a mode 000 file")
		}
		link := filepath.Join(t.TempDir(), "link")
		if err := os.Symlink(dir, link); err != nil {
			t.Fatal(err)
		}
		_, err := tree.Read(link)
		want := "reading manifest.json: open " + filepath.Join(link, "manifest.json") + ": permission denied"
		if err == nil || err.Error() != want {
			t.Errorf("Read = %v, want %q", err, want)
		}
	})
}

// A file that cannot be read is named by its path in the bundle, the first in path order,
// whichever it is.
func TestReadNamesAnUnreadableFile(t *testing.T) {
	dir := t.TempDir()
	for _, rel := range []string{"manifest.json", "configs/n1.cli", "configs/n2.cli"} {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(rel), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, rel := range []string{"configs/n2.cli", "manifest.json"} {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.Chmod(p, 0o000); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(p, 0o644) })
	}
	if _, err := os.ReadFile(filepath.Join(dir, "manifest.json")); err == nil {
		t.Skip("the test runs with permission to read a mode 000 file")
	}

	files, err := tree.Read(dir)
	want := "reading configs/n2.cli: open " + filepath.Join(dir, "configs", "n2.cli") + ": permission denied"
	if err == nil || err.Error() != want || files != nil {
		t.Errorf("Read = %v, %v; want no files and %q", keys(files), err, want)
	}
}

// Write keeps M12's wordings: a non-empty target is *ErrNotEmpty, the sentence twin compile
// prints, and leaves what is there; a target that is a file cannot be inspected.
func TestWriteRefusesATargetInM12sWords(t *testing.T) {
	root := t.TempDir()
	full := filepath.Join(root, "full")
	if err := os.MkdirAll(full, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(full, "keep.txt"), []byte("mine\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	files := map[string][]byte{"manifest.json": []byte("{}\n")}

	err := tree.Write(files, full)
	var notEmpty *tree.ErrNotEmpty
	if !errors.As(err, &notEmpty) || err.Error() != "output directory "+full+" is not empty" {
		t.Errorf("Write into a non-empty directory = %v, want ErrNotEmpty in M12's words", err)
	}
	// bundle.ErrNotEmpty is the same type, so its callers' errors.As still match.
	var viaBundle *bundle.ErrNotEmpty
	if !errors.As(err, &viaBundle) {
		t.Errorf("bundle.ErrNotEmpty does not match %T", err)
	}
	if entries, _ := os.ReadDir(full); len(entries) != 1 {
		t.Errorf("the refusal left %d entries, want the original 1", len(entries))
	}

	file := filepath.Join(root, "file")
	if err := os.WriteFile(file, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, inspect := os.ReadDir(file)
	err = tree.Write(files, file)
	if want := "inspecting output directory: " + inspect.Error(); err == nil || err.Error() != want {
		t.Errorf("Write onto a file = %v, want %q", err, want)
	}
	if b, _ := os.ReadFile(file); string(b) != "x" {
		t.Errorf("the refusal changed the file to %q", b)
	}
}

// CheckPaths refuses a path that is the bundle's root or leads out of it, as checkPath
// refuses one not in canonical form, and a set in which a path is given twice or lies beneath
// another; each sentence names the path inside the bundle alone, the first refused in path
// order. Write refuses the same before it writes anything.
func TestCheckPathsRefusesWhatIsNoFileOfTheBundle(t *testing.T) {
	for _, c := range []struct {
		label string
		names []string
		want  string
	}{
		{"the root", []string{"manifest.json", "."}, `bundle path "." is the bundle root, not a file in it`},
		{"the root's parent", []string{"manifest.json", ".."}, `bundle path ".." escapes the bundle root`},
		{"beneath the root's parent", []string{"../x"}, `bundle path "../x" escapes the bundle root`},
		{"not canonical", []string{"configs/../x"}, `bundle path "configs/../x" is not in canonical form`},
		{"a path given twice", []string{"manifest.json", "configs/n1.cli", "manifest.json"},
			`bundle path "manifest.json" is given twice`},
		{"beneath a file", []string{"manifest.json", "manifest.json/x"},
			`bundle path "manifest.json/x" lies beneath "manifest.json", which is a file`},
		{"deep beneath a file", []string{"configs/n1.cli/a/b", "configs/n1.cli"},
			`bundle path "configs/n1.cli/a/b" lies beneath "configs/n1.cli", which is a file`},
		{"the first in path order", []string{"z/..", "a/.."}, `bundle path "a/.." is not in canonical form`},
	} {
		t.Run(c.label, func(t *testing.T) {
			if err := tree.CheckPaths(c.names); err == nil || err.Error() != c.want {
				t.Errorf("CheckPaths(%q) = %v, want %q", c.names, err, c.want)
			}
		})
	}
	for _, ok := range [][]string{nil, {"manifest.json", "configs/n1.cli", "configs/n2.cli"}, {"a", "a.b", "a-b/c"}} {
		if err := tree.CheckPaths(ok); err != nil {
			t.Errorf("CheckPaths(%q) = %v, want nil", ok, err)
		}
	}

	for _, c := range []struct {
		files map[string][]byte
		want  string
	}{
		{map[string][]byte{"manifest.json": nil, "..": []byte("x")}, `bundle path ".." escapes the bundle root`},
		{map[string][]byte{"manifest.json": nil, ".": []byte("x")}, `bundle path "." is the bundle root, not a file in it`},
		{map[string][]byte{"manifest.json": nil, "manifest.json/x": []byte("x")},
			`bundle path "manifest.json/x" lies beneath "manifest.json", which is a file`},
	} {
		root := t.TempDir()
		dir := filepath.Join(root, "out")
		if err := tree.Write(c.files, dir); err == nil || err.Error() != c.want {
			t.Errorf("Write(%v) = %v, want %q", keys(c.files), err, c.want)
		}
		if entries, _ := os.ReadDir(root); len(entries) != 0 {
			t.Errorf("Write(%v) left %d entries beside the target", keys(c.files), len(entries))
		}
	}
}

func keys(m map[string][]byte) []string {
	var out []string
	for k := range m {
		out = append(out, k)
	}
	return out
}

func toBytes(m map[string]string) map[string][]byte {
	out := map[string][]byte{}
	for k, v := range m {
		out[k] = []byte(v)
	}
	return out
}
