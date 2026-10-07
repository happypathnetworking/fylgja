//go:build contract

package stage

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"maps"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

//	set -a; . local/.env; set +a; go test -tags contract ./internal/stage -run TestArtifactOnASeededBranch -v

// listedArtifact is what Infrahub lists for one device's artifact of one name.
type listedArtifact struct{ Checksum, StorageID string }

// artifactsOf asks Infrahub, through the generic and Infrahub's target interface as the
// read does, for each device's artifact named name.
func artifactsOf(t *testing.T, c *testsupport.Client, branch, name string) map[string]listedArtifact {
	t.Helper()
	raw, err := c.GraphQL(branch, `{ FylgjaDevice { edges { node { name { value }
		... on CoreArtifactTarget { artifacts { edges { node { checksum { value } storage_id { value }
			definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }`)
	if err != nil {
		t.Fatalf("asking Infrahub for the artifacts on %s: %v", branch, err)
	}
	type value struct {
		Value string `json:"value"`
	}
	var data struct {
		FylgjaDevice struct {
			Edges []struct {
				Node struct {
					Name      value `json:"name"`
					Artifacts struct {
						Edges []struct {
							Node struct {
								Checksum   value `json:"checksum"`
								StorageID  value `json:"storage_id"`
								Definition struct {
									Node struct {
										ArtifactName value `json:"artifact_name"`
									} `json:"node"`
								} `json:"definition"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"artifacts"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaDevice"`
	}
	if err := json.Unmarshal(raw, &data); err != nil {
		t.Fatal(err)
	}
	out := map[string]listedArtifact{}
	for _, d := range data.FylgjaDevice.Edges {
		for _, a := range d.Node.Artifacts.Edges {
			if a.Node.Definition.Node.ArtifactName.Value == name {
				out[d.Node.Name.Value] = listedArtifact{Checksum: a.Node.Checksum.Value, StorageID: a.Node.StorageID.Value}
			}
		}
	}
	return out
}

// artifactChecksums is artifactsOf's checksums alone.
func artifactChecksums(t *testing.T, c *testsupport.Client, branch, name string) map[string]string {
	t.Helper()
	out := map[string]string{}
	for d, a := range artifactsOf(t, c, branch, name) {
		out[d] = a.Checksum
	}
	return out
}

// M5's tier-2 proofs share one seeded throwaway branch, in order, because seeding and
// generating is most of each proof's cost: the read and the bundle, then detection,
// then the refusals, which add devices and so come last. A proof that fails
// stops the ones after it, which would be reading a branch in a state nobody meant.
// The product's own pipelines throughout, never a hand-built CTM (Constitution V).
func TestArtifactOnASeededBranch(t *testing.T) {
	c, branch := throwaway(t, "artifact")
	if err := c.LoadSchema(branch, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s", branch)

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	for _, proof := range []struct {
		name string
		run  func(*testing.T, *testsupport.Client, string, *psp.Registry)
	}{
		{"read and bundle", artifactReadAndBundle},
		{"detection", artifactDetection},
		{"refusals", artifactRefusals},
	} {
		if !t.Run(proof.name, func(t *testing.T) { proof.run(t, c, branch, reg) }) {
			return
		}
	}
}

// read runs stage.Read with a fresh observed_at, as every caller does.
func read(t *testing.T, branch string, reg *psp.Registry) (*ctm.CTM, findings.List) {
	t.Helper()
	snapshot, list, err := Read(t.Context(), branch, "", reg, time.Now().UTC().Format(ObservedAtFormat))
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	return snapshot, list
}

// compileClean reads and compiles the branch, failing on any rejection.
func compileClean(t *testing.T, branch string, reg *psp.Registry) (*ctm.CTM, string) {
	t.Helper()
	snapshot, list := read(t, branch, reg)
	if list.Rejected() {
		t.Fatalf("reading %s was rejected: %v", branch, list)
	}
	_, id, list := Compile(snapshot, reg)
	if list.Rejected() {
		t.Fatalf("compiling %s was rejected: %v", branch, list)
	}
	return snapshot, id
}

// contentOf maps each device to its artifact's bytes.
func contentOf(c *ctm.CTM) map[string]string {
	out := map[string]string{}
	for _, d := range c.Devices {
		if d.Artifact != nil {
			out[d.Name] = d.Artifact.Content
		}
	}
	return out
}

// The read fetches every device's artifact and the bundle carries it. On a seeded
// throwaway branch — SeedThreeNode joins the devices to the target
// group and generates — stage.Read returns three devices each with an artifact whose
// checksum is Infrahub's and whose bytes hash to it, and stage.Compile's files carry
// configs/<n>.device-config, byte for byte, with the manifest's entry and the bundle
// version this build writes (M5's "2", "3" from M7's format bump, "4" from M12's).
func artifactReadAndBundle(t *testing.T, c *testsupport.Client, branch string, reg *psp.Registry) {
	snapshot, list, err := Read(t.Context(), branch, "", reg, time.Now().UTC().Format(ObservedAtFormat))
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	if list.Rejected() {
		t.Fatalf("reading %s was rejected: %v", branch, list)
	}

	infrahub := artifactChecksums(t, c, branch, "device-config")
	if len(snapshot.Devices) != 3 || len(infrahub) != 3 {
		t.Fatalf("read %d devices, Infrahub names %d artifacts (%v); want three of each", len(snapshot.Devices), len(infrahub), infrahub)
	}
	for _, d := range snapshot.Devices {
		a := d.Artifact
		if a == nil {
			t.Errorf("device %s was read with no artifact", d.Name)
			continue
		}
		sum := md5.Sum([]byte(a.Content))
		if a.Name != "device-config" || a.ContentType != "text/plain" || a.Checksum != infrahub[d.Name] ||
			hex.EncodeToString(sum[:]) != a.Checksum {
			t.Errorf("device %s artifact %s %s %s (bytes hash to %x), want device-config text/plain with Infrahub's checksum %s",
				d.Name, a.Name, a.ContentType, a.Checksum, sum, infrahub[d.Name])
		}
	}

	files, id, list := Compile(snapshot, reg)
	if list.Rejected() {
		t.Fatalf("compiling %s was rejected: %v", branch, list)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	if m.BundleVersion != "4" {
		t.Errorf("bundle_version %q, want 4", m.BundleVersion)
	}
	content := map[string]string{}
	for _, d := range snapshot.Devices {
		if d.Artifact != nil {
			content[d.Name] = d.Artifact.Content
		}
	}
	for _, n := range m.Nodes {
		file := "configs/" + n.Name + ".device-config"
		a := n.Artifact
		if a == nil || a.Name != "device-config" || a.Checksum != infrahub[n.Name] || a.File != file || a.Size != len(content[n.Name]) {
			t.Errorf("manifest node %s artifact %+v, want device-config at %s with Infrahub's checksum and its size", n.Name, a, file)
		}
		if got := string(files[file]); got != content[n.Name] {
			t.Errorf("%s holds %d bytes, want the artifact's %d, unchanged", file, len(got), len(content[n.Name]))
		}
	}
	t.Logf("bundle_id %s", id)
}

// A configuration change is detected by the read-and-compare M4 follows with, and nothing
// else is (D-026). Two reads of an unchanged branch compile to one
// bundle_id. A role change, regenerated, moves it: the template prints role in a comment
// and the compiler emits it nowhere, so only the artifact moved it. A site
// change, regenerated, leaves it exactly where it was: the template queries site and
// prints nothing from it, and Infrahub writes nothing for a regeneration whose output
// matches — not the checksum, and not the storage id either.
func artifactDetection(t *testing.T, c *testsupport.Client, branch string, reg *psp.Registry) {
	first, id := compileClean(t, branch, reg)
	_, again := compileClean(t, branch, reg)
	if again != id {
		t.Fatalf("two reads of an unchanged branch compiled to %s and %s", id, again)
	}

	// The role change. Generation writes the new bytes in one step, with no status
	// transition to wait on, so the wait is for n1's checksum to move.
	before := artifactsOf(t, c, branch, "device-config")
	if err := c.SetDeviceRole(branch, "n1", testsupport.MarkerRole(branch)+"-moved"); err != nil {
		t.Fatal(err)
	}
	if err := c.GenerateArtifacts(branch); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(90 * time.Second); artifactsOf(t, c, branch, "device-config")["n1"].Checksum == before["n1"].Checksum; {
		if time.Now().After(deadline) {
			t.Fatalf("n1's artifact checksum stayed %s for 90s after a role change was generated", before["n1"].Checksum)
		}
		time.Sleep(500 * time.Millisecond)
	}
	moved, movedID := compileClean(t, branch, reg)
	if movedID == id {
		t.Errorf("a role change, regenerated, left bundle_id at %s", id)
	}
	was, now := contentOf(first), contentOf(moved)
	if was["n1"] == now["n1"] {
		t.Error("n1's artifact bytes did not change with its role")
	}
	for _, d := range []string{"n2", "n3"} {
		if was[d] != now[d] {
			t.Errorf("%s's artifact bytes changed with n1's role", d)
		}
	}
	t.Logf("role change: bundle_id %s -> %s", id, movedID)

	// The site change. A regeneration that writes nothing gives nothing to wait for, so
	// the listing is watched for 20 seconds, well past the 7.6s a regeneration that changes
	// bytes took, and must not move.
	listed := artifactsOf(t, c, branch, "device-config")
	if err := c.SetDeviceSite(branch, "n1", "lab"); err != nil {
		t.Fatal(err)
	}
	if err := c.GenerateArtifacts(branch); err != nil {
		t.Fatal(err)
	}
	for end := time.Now().Add(20 * time.Second); time.Now().Before(end); time.Sleep(time.Second) {
		if got := artifactsOf(t, c, branch, "device-config"); !maps.Equal(got, listed) {
			t.Fatalf("a site change, regenerated, moved Infrahub's listing: %v -> %v", listed, got)
		}
	}
	unmoved, unmovedID := compileClean(t, branch, reg)
	if unmovedID != movedID {
		t.Errorf("a site change, regenerated, moved bundle_id %s -> %s", movedID, unmovedID)
	}
	if !maps.Equal(contentOf(unmoved), now) {
		t.Error("a site change, regenerated, changed an artifact's bytes")
	}
	for _, d := range unmoved.Devices {
		if d.Site != "" && d.Name != "n1" {
			t.Errorf("device %s has site %q; only n1's was set", d.Name, d.Site)
		}
	}
}

// A device with no current artifact is refused by name, and the read writes no CTM.
// Two ways a device is left without one, both in one read: n4 is not
// in the group the definition renders for, so nothing is ever rendered for it; n5 is in
// the group but nothing has been generated since it joined, and Infrahub renders nothing
// on its own. The token case has no live oracle — this Infrahub reads
// anonymously — and is tier 1's alone (internal/intent/artifact_test.go).
func artifactRefusals(t *testing.T, c *testsupport.Client, branch string, reg *psp.Registry) {
	raw, err := c.GraphQL(branch, `{ NetworkPlatform { edges { node { id } } } }`)
	if err != nil {
		t.Fatal(err)
	}
	var platforms struct {
		P struct {
			Edges []struct {
				Node struct {
					ID string `json:"id"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"NetworkPlatform"`
	}
	if err := json.Unmarshal(raw, &platforms); err != nil || len(platforms.P.Edges) != 1 {
		t.Fatalf("want the fixture's one platform on %s: %s (%v)", branch, raw, err)
	}
	platform := platforms.P.Edges[0].Node.ID

	create := func(kind, data string) string {
		t.Helper()
		raw, err := c.GraphQL(branch, fmt.Sprintf(`mutation { %sCreate(data: %s) { ok object { id } } }`, kind, data))
		if err != nil {
			t.Fatalf("creating %s on %s: %v", kind, branch, err)
		}
		var r map[string]struct {
			Object struct {
				ID string `json:"id"`
			} `json:"object"`
		}
		if err := json.Unmarshal(raw, &r); err != nil || r[kind+"Create"].Object.ID == "" {
			t.Fatalf("creating %s on %s: %s (%v)", kind, branch, raw, err)
		}
		return r[kind+"Create"].Object.ID
	}
	device := func(name string) string {
		id := create("NetworkDevice", fmt.Sprintf(`{name: {value: %q}, platform: {id: %q}, role: {value: %q}}`,
			name, platform, testsupport.MarkerRole(branch)))
		create("NetworkInterface", fmt.Sprintf(
			`{name: {value: "mgmt0"}, iftype: {value: "physical"}, mgmt_only: {value: true}, device: {id: %q}}`, id))
		create("NetworkInterface", fmt.Sprintf(`{name: {value: "lo0"}, iftype: {value: "loopback"}, device: {id: %q}}`, id))
		return id
	}
	device("n4")
	n5 := device("n5")
	if err := c.JoinArtifactGroup(branch, []string{n5}); err != nil {
		t.Fatal(err)
	}

	snapshot, list := read(t, branch, reg)
	if snapshot != nil {
		t.Error("a refused read returned a CTM")
	}
	var want findings.List
	for _, d := range []string{"n4", "n5"} {
		want.Add(findings.Rejection, findings.RuleArtifactMissing, d,
			"device "+d+" has no artifact named device-config on branch "+branch)
	}
	if !slices.Equal(list, want) {
		t.Errorf("findings %+v\nwant exactly %+v", list, want)
	}
}
