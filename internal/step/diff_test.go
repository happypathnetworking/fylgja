package step

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/compiler"
)

// goldens are the three bundles M7 left, the step's inputs; M11 never re-baselined them,
// and M12's bundle "4" moved them once.
var goldens = []string{"three-node", "lossy", "mixed"}

// golden reads testdata/golden/<name>/ into a Bundle whose id is id.
func golden(t *testing.T, name, id string) Bundle {
	t.Helper()
	root := filepath.Join("..", "..", "testdata", "golden", name)
	files := map[string][]byte{}
	err := filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		files[filepath.ToSlash(rel)] = b
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return Bundle{ID: id, Files: files}
}

// edited is a copy of b under id, its manifest decoded, changed by fn and encoded again,
// and its files changed by fn too. b is untouched.
func edited(t *testing.T, b Bundle, id string, fn func(m *compiler.Manifest, files map[string][]byte)) Bundle {
	t.Helper()
	files := make(map[string][]byte, len(b.Files))
	for k, v := range b.Files {
		files[k] = append([]byte(nil), v...)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(files[manifestFile], &m); err != nil {
		t.Fatal(err)
	}
	fn(&m, files)
	raw, err := json.MarshalIndent(&m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	files[manifestFile] = raw
	return Bundle{ID: id, Files: files}
}

// manifestOf decodes a bundle's manifest, for building what a test expects.
func manifestOf(t *testing.T, b Bundle) compiler.Manifest {
	t.Helper()
	var m compiler.Manifest
	if err := json.Unmarshal(b.Files[manifestFile], &m); err != nil {
		t.Fatal(err)
	}
	return m
}

// Two fake ids, 64 hex characters as bundle ids are: the step compares content, never
// these, and only prints them.
var (
	idA = strings.Repeat("35aea06f", 8)
	idB = strings.Repeat("9c2d01e7", 8)
)

func linkRefOf(l compiler.CabledLink) LinkRef {
	return LinkRef{ID: l.ID, A: NodePort{Node: l.A.Node, Port: l.A.Port}, B: NodePort{Node: l.B.Node, Port: l.B.Port}}
}

func strPtr(s string) *string { return &s }

// Each kind of edit, on each golden, gives the step that names exactly it: every list
// asserted whole, by name.
func TestDiffNamesEachEdit(t *testing.T) {
	for _, g := range goldens {
		t.Run(g, func(t *testing.T) {
			a := golden(t, g, idA)
			m := manifestOf(t, a)
			first := m.Nodes[0]
			link := m.Links[0]

			cases := []struct {
				name string
				b    Bundle
				want Step
			}{
				{
					name: "two identical copies",
					b:    edited(t, a, idA, func(*compiler.Manifest, map[string][]byte) {}),
					want: Step{From: idA, To: idA, Unchanged: true},
				},
				{
					name: "copies differing only in provenance.at",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Provenance.At = "2026-09-28T16:04:58.989214+00:00"
					}),
					want: Step{From: idA, To: idB, Unchanged: true},
				},
				{
					name: "copies differing in the whole provenance",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Provenance = compiler.Provenance{Branch: "change-1", SchemaHash: "fe9eca98", ContractVersion: "0.2"}
					}),
					want: Step{From: idA, To: idB, Unchanged: true},
				},
				{
					name: "a link removed",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Links = m.Links[1:]
					}),
					want: Step{From: idA, To: idB, LinksRemoved: []LinkRef{linkRefOf(link)}},
				},
				{
					name: "an artifact checksum moved",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Nodes[0].Artifact.Checksum = "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"
					}),
					want: Step{From: idA, To: idB, ArtifactsChanged: []ArtifactChange{{Node: first.Name,
						Name: first.Artifact.Name, From: first.Artifact.Checksum, To: "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}}},
				},
				{
					name: "an artifact's bytes changed under the same checksum",
					b: edited(t, a, idB, func(_ *compiler.Manifest, files map[string][]byte) {
						files[first.Artifact.File] = append(files[first.Artifact.File], "changed\n"...)
					}),
					want: Step{From: idA, To: idB, Unchanged: true},
				},
				{
					name: "a bootstrap line changed",
					b: edited(t, a, idB, func(_ *compiler.Manifest, files map[string][]byte) {
						files[first.Bootstrap.File] = append(files[first.Bootstrap.File], "one more line\n"...)
					}),
					want: Step{From: idA, To: idB, NodesChanged: []NodeChange{{Node: first.Name, Reasons: []string{ReasonBootstrap}}}},
				},
				{
					name: "a platform changed",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Nodes[0].Platform = "other"
					}),
					want: Step{From: idA, To: idB, NodesChanged: []NodeChange{{Node: first.Name, Reasons: []string{ReasonPlatform}}}},
				},
				{
					name: "an image and a package changed",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Nodes[0].Image = "registry.example/other:1"
						m.Nodes[0].PSP.ID = "other"
					}),
					want: Step{From: idA, To: idB, NodesChanged: []NodeChange{{Node: first.Name, Reasons: []string{ReasonImage, ReasonPSP}}}},
				},
				{
					name: "an interface mapped to another port",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						for i := range m.Mapping {
							if m.Mapping[i].Device == first.Name && m.Mapping[i].Port != nil {
								m.Mapping[i].Port = strPtr("e9-9")
								return
							}
						}
						t.Fatalf("%s has no mapped interface", first.Name)
					}),
					want: Step{From: idA, To: idB, NodesChanged: []NodeChange{{Node: first.Name, Reasons: []string{ReasonMapping}}}},
				},
				{
					name: "every link removed",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Links = nil
					}),
					want: Step{From: idA, To: idB, LinksRemoved: []LinkRef{linkRefOf(m.Links[0]), linkRefOf(m.Links[1]), linkRefOf(m.Links[2])}},
				},
				{
					name: "a node removed",
					b: edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
						m.Nodes = m.Nodes[1:]
					}),
					want: Step{From: idA, To: idB, NodesRemoved: []string{first.Name},
						ArtifactsRemoved: []ArtifactRef{{Node: first.Name, Name: first.Artifact.Name}}},
				},
			}
			for _, c := range cases {
				t.Run(c.name, func(t *testing.T) {
					got, err := Diff(a, c.b)
					if err != nil {
						t.Fatal(err)
					}
					if !reflect.DeepEqual(got, c.want) {
						t.Errorf("Diff:\n got %+v\nwant %+v", got, c.want)
					}
				})
			}
		})
	}
}

// addFourthNode is a node added, as an edit of the three-node golden: n4 joins
// with its artifact, n1 gains a port cabled to it (a new mapping row and a new bootstrap
// line), and n1's artifact moves.
func addFourthNode(t *testing.T, a Bundle) Bundle {
	return edited(t, a, idB, func(m *compiler.Manifest, files map[string][]byte) {
		n4 := m.Nodes[0]
		n4.Name = "n4"
		n4.Artifact = &compiler.ManifestArtifact{Name: "device-config", ContentType: "text/plain",
			Checksum: "51f0aa93c2d4e6f8a0b1c3d5e7f9a1b3", Size: 12, File: "configs/n4.device-config"}
		n4.Bootstrap.File = "configs/n4.cli"
		m.Nodes = append(m.Nodes, n4)
		files["configs/n4.cli"] = []byte("# the fourth node's bootstrap\n")
		files["configs/n4.device-config"] = []byte("# the fourth\n")

		m.Nodes[0].Artifact.Checksum = "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"
		files["configs/n1.cli"] = append(files["configs/n1.cli"], "set / interface ethernet-1/3 admin-state enable\n"...)
		m.Mapping = append(m.Mapping,
			compiler.MappingRow{Device: "n1", Interface: "ethernet-1/3", Iftype: "physical", Port: strPtr("e1-3"),
				NodeName: strPtr("ethernet-1/3"), Disposition: compiler.DispCabled},
			compiler.MappingRow{Device: "n4", Interface: "ethernet-1/1", Iftype: "physical", Port: strPtr("e1-1"),
				NodeName: strPtr("ethernet-1/1"), Disposition: compiler.DispCabled})
		m.Links = append(m.Links, compiler.CabledLink{ID: "n1:ethernet-1/3|n4:ethernet-1/1",
			A: compiler.NodePort{Node: "n1", Port: "e1-3"}, B: compiler.NodePort{Node: "n4", Port: "e1-1"}})
	})
}

// The node-added edit names everything that came with the node, and its text is the
// step's rendering, line for line.
func TestDiffNodeAdded(t *testing.T) {
	a := golden(t, "three-node", idA)
	b := addFourthNode(t, a)
	got, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	want := Step{From: idA, To: idB,
		NodesAdded:   []string{"n4"},
		NodesChanged: []NodeChange{{Node: "n1", Reasons: []string{ReasonBootstrap, ReasonMapping}}},
		LinksAdded: []LinkRef{{ID: "n1:ethernet-1/3|n4:ethernet-1/1",
			A: NodePort{Node: "n1", Port: "e1-3"}, B: NodePort{Node: "n4", Port: "e1-1"}}},
		ArtifactsChanged: []ArtifactChange{{Node: "n1", Name: "device-config",
			From: "43e8fd0c2de5f4646f74a51d34742824", To: "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}},
		ArtifactsAdded: []ArtifactRef{{Node: "n4", Name: "device-config"}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("Diff:\n got %+v\nwant %+v", got, want)
	}

	text := Between("demo/1", "demo/2", got).Text()
	wantText := strings.Join([]string{
		"step demo/1 → demo/2 (35aea06f… → 9c2d01e7…):",
		"  nodes: +n4; ~n1 (bootstrap, mapping)",
		"  links: +n1:e1-3 — n4:e1-1",
		"  artifacts: n1 device-config 43e8fd0c… → 9a0177b2…; n4 device-config added",
	}, "\n")
	if text != wantText {
		t.Errorf("text:\n%s\nwant:\n%s", text, wantText)
	}

	// Reversed, the same step runs the other way.
	back, err := Diff(b, a)
	if err != nil {
		t.Fatal(err)
	}
	if text := Between("demo/2", "demo/1", back).Text(); text != strings.Join([]string{
		"step demo/2 → demo/1 (9c2d01e7… → 35aea06f…):",
		"  nodes: -n4; ~n1 (bootstrap, mapping)",
		"  links: -n1:e1-3 — n4:e1-1",
		"  artifacts: n1 device-config 9a0177b2… → 43e8fd0c…; n4 device-config removed",
	}, "\n") {
		t.Errorf("reversed text:\n%s", text)
	}
}

// The artifacts line is sorted by node across the three kinds of change, and the nodes line
// puts added before removed before changed.
func TestPairTextOrder(t *testing.T) {
	a := golden(t, "three-node", idA)
	b := edited(t, a, idB, func(m *compiler.Manifest, files map[string][]byte) {
		m.Nodes[2].Artifact.Checksum = "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"
		m.Nodes = m.Nodes[1:] // n1 goes, with its artifact
		files["configs/n2.cli"] = append(files["configs/n2.cli"], "one more line\n"...)
	})
	s, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	want := strings.Join([]string{
		"step demo/1 → demo/2 (35aea06f… → 9c2d01e7…):",
		"  nodes: -n1; ~n2 (bootstrap)",
		"  links: unchanged",
		"  artifacts: n1 device-config removed; n3 device-config ae0c3a87… → 9a0177b2…",
	}, "\n")
	if got := Between("demo/1", "demo/2", s).Text(); got != want {
		t.Errorf("text:\n%s\nwant:\n%s", got, want)
	}
}

// The two one-line forms: unchanged, and not computed.
func TestPairTextOneLine(t *testing.T) {
	a := golden(t, "three-node", idA)
	b := edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) { m.Provenance.At = "2026-09-28T15:20:44Z" })
	s, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct{ got, want string }{
		{Between("demo/2", "demo/3", s).Text(),
			"step demo/2 → demo/3 (35aea06f… → 9c2d01e7…): unchanged; the ids differ by provenance alone"},
		{NotComputed("demo/3", "demo/5", idA, "", "demo/5 was refused").Text(),
			"step demo/3 → demo/5 (35aea06f… → —): not computed (demo/5 was refused)"},
	} {
		if c.got != c.want {
			t.Errorf("text:\n got %s\nwant %s", c.got, c.want)
		}
	}
	same, err := Diff(a, a)
	if err != nil {
		t.Fatal(err)
	}
	if got := Between("demo/1", "demo/2", same).Text(); got != "step demo/1 → demo/2 (35aea06f… → 35aea06f…): unchanged; the two are one bundle" {
		t.Errorf("one bundle: %s", got)
	}
}

// shuffled is b with its manifest's lists in reverse order and its file map built in
// reverse key order: the same bundle as the step must read it.
func shuffled(t *testing.T, b Bundle) Bundle {
	t.Helper()
	out := edited(t, b, b.ID, func(m *compiler.Manifest, _ map[string][]byte) {
		reverse(m.Nodes)
		reverse(m.Mapping)
		reverse(m.Links)
	})
	keys := make([]string, 0, len(out.Files))
	for k := range out.Files {
		keys = append(keys, k)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(keys)))
	files := make(map[string][]byte, len(keys))
	for _, k := range keys {
		files[k] = out.Files[k]
	}
	return Bundle{ID: out.ID, Files: files}
}

func reverse[T any](xs []T) {
	for i, j := 0, len(xs)-1; i < j; i, j = i+1, j-1 {
		xs[i], xs[j] = xs[j], xs[i]
	}
}

// renderings is the text and the JSON of a pair, the two things an operator reads.
func renderings(t *testing.T, p Pair) (string, []byte) {
	t.Helper()
	j, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	return p.Text(), j
}

// The same two bundles give the same text and JSON a second time and from shuffled copies.
func TestDiffIsStable(t *testing.T) {
	a := golden(t, "three-node", idA)
	b := addFourthNode(t, a)
	first, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	text, js := renderings(t, Between("demo/1", "demo/2", first))
	for i := 0; i < 2; i++ {
		again, err := Diff(shuffled(t, a), shuffled(t, b))
		if err != nil {
			t.Fatal(err)
		}
		t2, j2 := renderings(t, Between("demo/1", "demo/2", again))
		if t2 != text || string(j2) != string(js) {
			t.Fatalf("run %d differs from the first:\n%s\n%s\nwant\n%s\n%s", i+2, t2, j2, text, js)
		}
	}
}

// No byte of an artifact or a bootstrap reaches the text or the JSON: the marker
// proof's shape (cmd/fylgja/marker_test.go), over every line of every configuration file
// either side carries.
func TestDiffCarriesNoContent(t *testing.T) {
	for _, g := range goldens {
		t.Run(g, func(t *testing.T) {
			a := golden(t, g, idA)
			m := manifestOf(t, a)
			b := edited(t, a, idB, func(m *compiler.Manifest, files map[string][]byte) {
				for i := range m.Nodes {
					n := &m.Nodes[i]
					n.Artifact.Checksum = strings.Repeat("0", 31) + string(rune('1'+i))
					files[n.Bootstrap.File] = append(files[n.Bootstrap.File], "changed on the second side\n"...)
				}
			})
			s, err := Diff(a, b)
			if err != nil {
				t.Fatal(err)
			}
			if len(s.ArtifactsChanged) != len(m.Nodes) || len(s.NodesChanged) != len(m.Nodes) {
				t.Fatalf("every node's artifact and bootstrap changed, but the step names %+v", s)
			}
			text, js := renderings(t, Between("demo/1", "demo/2", s))
			for _, side := range []Bundle{a, b} {
				for name, body := range side.Files {
					if name == manifestFile || name == "topology.clab.yml" {
						continue
					}
					for _, line := range strings.Split(string(body), "\n") {
						line = strings.TrimSpace(line)
						if len(line) < 10 {
							continue
						}
						if strings.Contains(text, line) || strings.Contains(string(js), line) {
							t.Errorf("%s's line %q reached the step's output", name, line)
						}
					}
				}
			}
			if g == "three-node" && !strings.Contains(string(a.Files["configs/n1.device-config"]), "FYLGJA-MARKER-fixture") {
				t.Fatal("the golden's artifact no longer carries the marker; the proof would prove nothing")
			}
			if strings.Contains(text+string(js), "FYLGJA-MARKER") {
				t.Error("the marker reached the step's output")
			}
		})
	}
}

// stepSchema is waypoints.schema.json's step, from the module root's contracts/.
func stepSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	f, err := os.Open(filepath.Join("..", "..", "contracts", "waypoints.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	const id = "https://fylgja.dev/schemas/waypoints.schema.json"
	c := jsonschema.NewCompiler()
	if err := c.AddResource(id, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(id + "#/$defs/step")
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// Every shape of a pair's JSON is waypoints.schema.json's step, and carries the checksums
// whole.
func TestPairJSONSatisfiesTheContract(t *testing.T) {
	schema := stepSchema(t)
	a := golden(t, "three-node", idA)
	b := addFourthNode(t, a)
	changed, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	unchanged, err := Diff(a, edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) { m.Provenance.At = "x" }))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name string
		p    Pair
	}{
		{"changed", Between("demo/1", "demo/2", changed)},
		{"unchanged", Between("demo/2", "demo/3", unchanged)},
		{"not computed, one side", NotComputed("demo/3", "demo/5", idA, "", "demo/5 was refused")},
		{"not computed, both sides", NotComputed("demo/4", "demo/5", "", "", "demo/4 and demo/5 were refused")},
	} {
		t.Run(c.name, func(t *testing.T) {
			raw, err := json.Marshal(c.p)
			if err != nil {
				t.Fatal(err)
			}
			v, err := jsonschema.UnmarshalJSON(strings.NewReader(string(raw)))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(v); err != nil {
				t.Errorf("%s does not satisfy the step contract: %v\n%s", c.name, err, raw)
			}
		})
	}
	raw, _ := json.Marshal(Between("demo/1", "demo/2", changed))
	for _, whole := range []string{idA, idB, "43e8fd0c2de5f4646f74a51d34742824", "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"} {
		if !strings.Contains(string(raw), `"`+whole+`"`) {
			t.Errorf("the JSON does not carry %s whole: %s", whole, raw)
		}
	}
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["computed"] != true || decoded["unchanged"] != false {
		t.Errorf("computed %v, unchanged %v; want true, false", decoded["computed"], decoded["unchanged"])
	}
}

// A side the step cannot read is an error naming the side and the file.
func TestDiffNamesAnUnreadableSide(t *testing.T) {
	a := golden(t, "three-node", idA)
	noManifest := Bundle{ID: idB, Files: map[string][]byte{"configs/n1.cli": nil}}
	garbled := Bundle{ID: idB, Files: map[string][]byte{manifestFile: []byte("{")}}
	older := edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) { m.BundleVersion = "2" })
	noBootstrap := edited(t, a, idB, func(_ *compiler.Manifest, files map[string][]byte) { delete(files, "configs/n2.cli") })

	for _, c := range []struct {
		name     string
		a, b     Bundle
		contains []string
	}{
		{"no manifest", a, noManifest, []string{"the to bundle " + idB, "manifest.json", "not in the bundle"}},
		{"a manifest that does not parse", garbled, a, []string{"the from bundle " + idB, "manifest.json", "does not parse"}},
		{"an older bundle", a, older, []string{"the to bundle", "manifest.json", `bundle version "2"`}},
		{"a bootstrap the bundle lacks", noBootstrap, a, []string{"the from bundle", "configs/n2.cli", "node n2's bootstrap"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, err := Diff(c.a, c.b)
			if err == nil {
				t.Fatal("Diff read a side it cannot")
			}
			for _, want := range c.contains {
				if !strings.Contains(err.Error(), want) {
					t.Errorf("error %q does not name %q", err, want)
				}
			}
		})
	}
}

// A side in M11's format is refused, naming both versions, though nothing the step compares
// differs: a twin whose staged bundle is "3" was created by an earlier binary, and its
// remedy is M11's for a bundle the step cannot read, destroy and create again. The "3" side
// is a golden's
// files with the version set back and every row's enabled key removed, as M11 wrote it.
func TestDiffRefusesABundleFromFormat3(t *testing.T) {
	a := golden(t, "three-node", idA)
	var doc map[string]any
	if err := json.Unmarshal(a.Files[manifestFile], &doc); err != nil {
		t.Fatal(err)
	}
	doc["bundle_version"] = "3"
	for _, r := range doc["mapping"].([]any) {
		delete(r.(map[string]any), "enabled")
	}
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), `"enabled"`) {
		t.Fatal(`the "3" side still carries "enabled"; the test proves nothing`)
	}
	files := make(map[string][]byte, len(a.Files))
	for k, v := range a.Files {
		files[k] = v
	}
	files[manifestFile] = raw
	old := Bundle{ID: idA, Files: files}
	now := golden(t, "three-node", idB)

	_, err = Diff(old, now)
	want := "the from bundle " + idA + `: manifest.json: is bundle version "3"; this build compares "4"`
	if err == nil || err.Error() != want {
		t.Fatalf("Diff = %v, want %q", err, want)
	}
}

// A row's enabled is not part of what a step compares: on each
// golden, two "4" bundles that differ in one cabled row's enabled alone are Unchanged,
// with no node, link or artifact change. Intent's disabling reaches the node through the
// artifact, so a real change of it is a step with a pushed artifact.
func TestDiffDoesNotCompareEnabled(t *testing.T) {
	for _, g := range goldens {
		t.Run(g, func(t *testing.T) {
			a := golden(t, g, idA)
			disabled := ""
			b := edited(t, a, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				for i, r := range m.Mapping {
					if r.Disposition == compiler.DispCabled && r.IsEnabled() {
						off := false
						m.Mapping[i].Enabled = &off
						disabled = r.Device + ":" + r.Interface
						return
					}
				}
			})
			if disabled == "" {
				t.Fatalf("golden %s has no enabled cabled row; the test proves nothing", g)
			}
			if !strings.Contains(string(b.Files[manifestFile]), `"enabled": false`) {
				t.Fatalf("the edited manifest does not disable %s; the test proves nothing", disabled)
			}
			got, err := Diff(a, b)
			if err != nil {
				t.Fatal(err)
			}
			if want := (Step{From: idA, To: idB, Unchanged: true}); !reflect.DeepEqual(got, want) {
				t.Errorf("%s disabled alone: step %+v, want %+v", disabled, got, want)
			}
		})
	}
}
