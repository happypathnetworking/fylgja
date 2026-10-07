package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// refusingStore is a store whose Put fails naming the directory it was asked to file, as an
// operating system error inside the copy does.
type refusingStore struct{ bundle.Store }

func (refusingStore) Put(_ context.Context, src string) (string, error) {
	return "", fmt.Errorf("copying bundle: open %s: input/output error", filepath.Join(src, "manifest.json"))
}

// Every sentence a sent bundle's filing gives names the directory the operator gave, and
// never the server's scratch copy of it, whose path an operating system error carries.
func TestFilingNamesTheDirectoryAsGiven(t *testing.T) {
	const dir = "/home/operator/bundles/b"
	src := filepath.Join(t.TempDir(), ".fylgja-upload-123", "bundle")
	err := fileBundle(context.Background(), findings.OpTwinProvision, &findings.Subject{Bundle: dir}, refusingStore{}, dir, src,
		fixtureBundleID)
	_, doc := exitOf(t, err)
	want := "filing " + dir + " in the bundle store: copying bundle: open " + dir + "/manifest.json: input/output error"
	if len(doc.Findings) != 1 || doc.Findings[0].Message != want || doc.Findings[0].Object != dir {
		t.Errorf("findings %+v, want one on %s saying %q", doc.Findings, dir, want)
	}
}

// The upload's scratch copy is made under the first root that can hold one, and a failure to
// make one under any names the roots and the reason, never the copy's pattern.
func TestUploadFallsBackAndNamesNoScratch(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root writes a directory whatever its mode")
	}
	readOnly := t.TempDir()
	if err := os.Chmod(readOnly, 0o555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(readOnly, 0o755) })
	files := []api.File{{Path: "manifest.json", Data: []byte("{}\n")}}

	writable := t.TempDir()
	src, remove, err := upload([]string{filepath.Join(readOnly, "bundles"), writable}, "/given/b", files)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(src, writable+string(filepath.Separator)) {
		t.Errorf("the copy is at %s, want it under %s", src, writable)
	}
	remove()
	if _, err := os.Stat(filepath.Dir(src)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the copy's scratch directory is still there: %v", err)
	}

	_, _, err = upload([]string{filepath.Join(readOnly, "bundles")}, "/given/b", files)
	if err == nil || strings.Contains(err.Error(), ".fylgja-upload-") ||
		err.Error() != "preparing a scratch copy of /given/b: "+filepath.Join(readOnly, "bundles")+": permission denied" {
		t.Errorf("upload with no root that can hold a copy: %v", err)
	}
}

// A sent bundle's paths are checked before anything is written: one that is the bundle's
// root, leads out of it, lies beneath another file or is sent twice is operation.failed at
// step verify on the directory as given, in a sentence naming the path inside the bundle and
// nothing on the lab host. Each named the server's scratch copy, or kept the last copy of a
// path silently (contracts/api.md "Files").
func TestASentPathThatIsNoFileOfTheBundleIsRefused(t *testing.T) {
	paths := useStateRoot(t)
	srv := handlerServer(t)
	manifest := api.File{Path: "manifest.json", Data: []byte("{}\n")}
	for _, c := range []struct {
		label string
		files []api.File
		want  string
	}{
		{"a file at ..", []api.File{manifest, {Path: "..", Data: []byte("x")}},
			`bundle path ".." escapes the bundle root`},
		{"a file at .", []api.File{manifest, {Path: ".", Data: []byte("x")}},
			`bundle path "." is the bundle root, not a file in it`},
		{"a file beneath a file", []api.File{manifest, {Path: "manifest.json/x", Data: []byte("x")}},
			`bundle path "manifest.json/x" lies beneath "manifest.json", which is a file`},
		{"a path sent twice", []api.File{manifest, {Path: "manifest.json", Data: []byte("{\"a\":1}\n")}},
			`bundle path "manifest.json" is given twice`},
	} {
		t.Run(c.label, func(t *testing.T) {
			_, doc := handled(t, srv, findings.OpTwinProvision, api.Request{
				Args: map[string]json.RawMessage{"bundle": json.RawMessage(`"mybundle"`)}, Files: c.files})
			if doc.Status.ExitCode() != 2 || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want one operation.failed, exit 2", doc.Status.ExitCode(), doc.Findings)
			}
			f := doc.Findings[0]
			if f.Rule != findings.RuleOperationFailed || f.Step != findings.StepVerify || f.Object != "mybundle" || f.Message != c.want {
				t.Errorf("%s at step %q on %q: %q\nwant operation.failed at verify on mybundle: %q", f.Rule, f.Step, f.Object, f.Message, c.want)
			}
			if entries, err := os.ReadDir(paths.Bundles); err == nil && len(entries) > 0 {
				t.Errorf("the refusal left %d entries under the store", len(entries))
			}
		})
	}
}
