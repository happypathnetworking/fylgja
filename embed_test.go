package fylgja

import (
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"os"
	"path"
	"regexp"
	"slices"
	"strings"
	"testing"
)

// The stage kind ships in the binary beside the library (D-045), and beside it the probe
// kind (016): the schema/*.yaml glob takes both, and the stage file embedded is the kind,
// its label's pattern and its extension of the proposed change that --stage, stage list
// and stage plan read.
func TestTheStageKindIsEmbedded(t *testing.T) {
	names, err := fs.Glob(Data, "schema/*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(names, []string{"schema/fylgja-probe.yaml", "schema/fylgja-stage.yaml"}) {
		t.Errorf("the embedded schema files are %v; want schema/fylgja-probe.yaml and schema/fylgja-stage.yaml alone, the generics and the reference schema gone", names)
	}
	raw, err := Data.ReadFile("schema/fylgja-stage.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"name: Stage", "namespace: Fylgja", "branch: agnostic", "name: as_of",
		"name: description", `regex: "^[^/\\s]+$"`, "kind: CoreProposedChange", "name: fylgja_stages"} {
		if !strings.Contains(string(raw), want) {
			t.Errorf("the embedded schema/fylgja-stage.yaml carries no %q", want)
		}
	}
}

// The probe kind ships in the binary beside the stage kind (016, D-064): the schema/*.yaml
// glob takes it, and the file embedded is the kind, branch-agnostic, with its name's
// pattern, its format dropdown and its endpoint attributes, and no relationship or extension.
func TestTheProbeKindIsEmbedded(t *testing.T) {
	raw, err := Data.ReadFile("schema/fylgja-probe.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"name: Probe", "namespace: Fylgja", "branch: agnostic", "icon: mdi:radar",
		`regex: "^[a-z0-9][a-z0-9-]{0,23}$"`, "kind: Dropdown", "name: a_device", "name: b_gateway", "name: description"} {
		if !strings.Contains(string(raw), want) {
			t.Errorf("the embedded schema/fylgja-probe.yaml carries no %q", want)
		}
	}
	for _, refused := range []string{"relationships:", "extensions:"} {
		if strings.Contains(string(raw), refused) {
			t.Errorf("the embedded schema/fylgja-probe.yaml carries %q; the kind has no relationship and no extension", refused)
		}
	}
}

// libraryCommit is the schema library's commit the reader reads (D-057, R-12).
const libraryCommit = "26336e9026dff1907f2c58e81dd6ae7b5c3f763e"

// libraryRow is one row of schema/dcim/README.md's table: `<library path>` | `<vendored
// name>` | `<sha-256>`.
var libraryRow = regexp.MustCompile("^\\| `([^`]+)` \\| `([^`]+)` \\| `([0-9a-f]{64})` \\|$")

// The library's files are its bytes at the pinned commit (SC-007): every file the binary
// embeds from schema/dcim/ has the SHA-256 the README's table gives it, the table names
// every embedded file and nothing else, and the README names the commit in full. A file
// reformatted, edited or swapped for another commit's fails here, before any branch loads
// it.
func TestVendoredLibraryIsThePinnedCommit(t *testing.T) {
	readme, err := os.ReadFile("schema/dcim/README.md")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(readme), libraryCommit) {
		t.Errorf("schema/dcim/README.md does not name the commit %s", libraryCommit)
	}
	want := map[string]string{} // vendored name -> sha-256
	for line := range strings.SplitSeq(string(readme), "\n") {
		m := libraryRow.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if path.Base(m[1]) != m[2] {
			t.Errorf("the table vendors %s as %s; a file keeps the library's name", m[1], m[2])
		}
		if _, dup := want[m[2]]; dup {
			t.Errorf("the table names %s twice", m[2])
		}
		want[m[2]] = m[3]
	}
	if len(want) != 7 {
		t.Errorf("the table names %d files, want the six schema files and the licence", len(want))
	}

	entries, err := fs.ReadDir(Data, "schema/dcim")
	if err != nil {
		t.Fatal(err)
	}
	var embedded []string
	for _, e := range entries {
		embedded = append(embedded, e.Name())
		raw, err := Data.ReadFile("schema/dcim/" + e.Name())
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(raw)
		got := hex.EncodeToString(sum[:])
		switch w, ok := want[e.Name()]; {
		case !ok:
			t.Errorf("schema/dcim/%s is embedded and the README's table does not name it", e.Name())
		case got != w:
			t.Errorf("schema/dcim/%s has SHA-256 %s, the table's is %s: the file is not the library's at %s",
				e.Name(), got, w, libraryCommit)
		}
	}
	for name := range want {
		if !slices.Contains(embedded, name) {
			t.Errorf("the README's table names %s and the binary does not embed it", name)
		}
	}
}
