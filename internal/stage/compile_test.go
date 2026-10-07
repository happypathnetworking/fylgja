package stage

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// A CTM is a file an operator can edit, and the artifact's name becomes a file name in
// the bundle. Renamed to the package's startup_format, n1's artifact was written over
// n1's bootstrap, which is the node's startup-config and the manifest's artifact file
// both, and the compile succeeded: the node would boot on intent-derived content
// (Constitution IV). The pipeline a create runs refuses it, as
// artifact.missing naming the device and both names, and returns no bundle.
func TestCompileRefusesAnArtifactNotNamedAsItsPackageNamesIt(t *testing.T) {
	c, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	for i := range c.Devices {
		if c.Devices[i].Name == "n1" {
			c.Devices[i].Artifact.Name = "cli"
		}
	}

	files, id, list := Compile(c, reg)
	if files != nil || id != "" {
		t.Errorf("compiled a bundle (%d files, id %q) from a misnamed artifact", len(files), id)
	}
	var missing []findings.Finding
	for _, f := range list {
		if f.Rule == findings.RuleArtifactMissing {
			missing = append(missing, f)
		}
	}
	if len(missing) != 1 || missing[0].Object != "n1" || missing[0].Severity != findings.Rejection {
		t.Fatalf("want one artifact.missing rejection naming n1, got %v", list)
	}
	for _, want := range []string{`"cli"`, `"device-config"`} {
		if !strings.Contains(missing[0].Message, want) {
			t.Errorf("message does not name %s: %s", want, missing[0].Message)
		}
	}
}
