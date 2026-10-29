package bundle

import (
	"bytes"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/santhosh-tekuri/jsonschema/v6"
)

// goldenThreeNode is the fixture bundle's directory and the identity it hashes to.
const goldenThreeNodeID = "43d917158d2b601cd2cdeb6aafd56d367224d757c4ce3f67fdf3c206e2c5a386"

func goldenThreeNode() string {
	return filepath.Join("..", "..", "testdata", "golden", "three-node")
}

// copyGolden copies the golden bundle into a fresh directory named name.
func copyGolden(t *testing.T, name string) string {
	t.Helper()
	dst := filepath.Join(t.TempDir(), name)
	src := goldenThreeNode()
	err := filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	return dst
}

// Verify names the compiler's layout and format itself (the compiler's tests import this
// package); this keeps the two from drifting.
func TestVerifyAgreesWithTheCompiler(t *testing.T) {
	if manifestFile != compiler.ManifestFile || topologyFile != compiler.TopologyFile || bundleVersion != compiler.BundleVersion {
		t.Errorf("Verify checks %s, %s and bundle_version %q; the compiler writes %s, %s and %q",
			manifestFile, topologyFile, bundleVersion, compiler.ManifestFile, compiler.TopologyFile, compiler.BundleVersion)
	}
}

func TestVerifyAcceptsTheGoldenBundle(t *testing.T) {
	id, err := Verify(goldenThreeNode())
	if err != nil {
		t.Fatal(err)
	}
	if id != goldenThreeNodeID {
		t.Errorf("id = %s, want %s", id, goldenThreeNodeID)
	}
}

// goldenLossyID is the lossy design case's bundle: a bundle whose
// fidelity.lossy has content, where the three-node golden's is empty.
const goldenLossyID = "4213b3cfd532f896d476c67c21f54e5375effdbec18f4376360471fd03f50b03"

// Both goldens verify, whether fidelity.lossy has content or not. M6 emitted node_name
// and lossy only with content, so this test guarded a field a bundle might not carry;
// from bundle "3" both are unconditional, and what it proves now is that a bundle whose
// lossy record is populated verifies exactly as one whose record is empty.
func TestVerifyAcceptsTheLossyGolden(t *testing.T) {
	dir := filepath.Join("..", "..", "testdata", "golden", "lossy")
	b, err := os.ReadFile(filepath.Join(dir, manifestFile))
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{`"node_name"`, `"lossy": [`} {
		if !strings.Contains(string(b), field) {
			t.Fatalf("the lossy golden's manifest carries no %s; the test proves nothing", field)
		}
	}
	id, err := Verify(dir)
	if err != nil {
		t.Fatal(err)
	}
	if id != goldenLossyID {
		t.Errorf("id = %s, want %s", id, goldenLossyID)
	}
}

// A directory whose name is not an identity claims nothing, and is filed under what its
// bytes hash to.
func TestVerifyAnyOtherNameClaimsNothing(t *testing.T) {
	dir := copyGolden(t, "b")
	if err := os.WriteFile(filepath.Join(dir, "configs", "n1.cli"), []byte("changed\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	want, err := IDOfDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	id, err := Verify(dir)
	if err != nil {
		t.Fatalf("Verify refused a directory claiming nothing: %v", err)
	}
	if id != want || id == goldenThreeNodeID {
		t.Errorf("id = %s, want the altered bytes' %s", id, want)
	}
}

func TestVerifyRefusals(t *testing.T) {
	t.Run("no manifest", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustRemove(t, filepath.Join(dir, "manifest.json"))
		wantInvalid(t, dir, "manifest.json")
	})
	t.Run("manifest does not parse", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustWrite(t, filepath.Join(dir, "manifest.json"), "{not json")
		wantInvalid(t, dir, "does not parse")
	})
	t.Run("manifest without bundle_version", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustWrite(t, filepath.Join(dir, "manifest.json"), `{"nodes": []}`)
		wantInvalid(t, dir, "bundle_version")
	})
	t.Run("no topology", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustRemove(t, filepath.Join(dir, "topology.clab.yml"))
		wantInvalid(t, dir, "topology.clab.yml")
	})
	// A "2" manifest promises a configuration file for every node
	// (manifest.schema.json requires `artifact`). One that does not keep the promise
	// would otherwise stage, deploy and reach readiness before the push step refused
	// it, a minute and a teardown after a refusal was possible.
	t.Run("a node without an artifact entry", func(t *testing.T) {
		dir := copyGolden(t, "b")
		editManifest(t, dir, func(m map[string]any) {
			delete(m["nodes"].([]any)[1].(map[string]any), "artifact")
		})
		wantInvalid(t, dir, "no artifact", "n2")
	})
	t.Run("an artifact entry naming a file the bundle lacks", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustRemove(t, filepath.Join(dir, "configs", "n3.device-config"))
		wantInvalid(t, dir, "not in the bundle", "n3", "configs/n3.device-config")
	})
	t.Run("an artifact entry naming a file outside the bundle", func(t *testing.T) {
		dir := copyGolden(t, "b")
		outside := filepath.Join(filepath.Dir(dir), "outside.cli")
		mustWrite(t, outside, "set / system name host-name outside\n")
		editManifest(t, dir, func(m map[string]any) {
			m["nodes"].([]any)[0].(map[string]any)["artifact"].(map[string]any)["file"] = "../outside.cli"
		})
		wantInvalid(t, dir, "not in the bundle", "n1", "../outside.cli")
	})
	// The entry's checksum and size are what the run pushes by and records in twin.json.
	// A manifest that does not describe its own bytes would otherwise
	// pass here, be filed under the id its bytes hash to, and fail at the push step with a
	// message blaming a change after staging that never happened.
	t.Run("an artifact file that does not hash to its entry's checksum", func(t *testing.T) {
		dir := copyGolden(t, "b")
		editManifest(t, dir, func(m map[string]any) {
			m["nodes"].([]any)[0].(map[string]any)["artifact"].(map[string]any)["checksum"] = strings.Repeat("0", 32)
		})
		wantInvalid(t, dir, "n1", "configs/n1.device-config", "hashes to 597f6263eb7e0b539679b3956270876f",
			"not the checksum 00000000000000000000000000000000")
	})
	t.Run("an artifact file whose length is not its entry's size", func(t *testing.T) {
		dir := copyGolden(t, "b")
		editManifest(t, dir, func(m map[string]any) {
			m["nodes"].([]any)[2].(map[string]any)["artifact"].(map[string]any)["size"] = 706
		})
		wantInvalid(t, dir, "n3", "configs/n3.device-config", "is 707 bytes", "not the size 706")
	})
	// A "3" manifest promises a bootstrap entry for every node (manifest.schema.json
	// requires `bootstrap`). On a node whose bootstrap reaches it
	// through the push, the topology names no startup-config, so the manifest's entry is
	// the only thing that says the file exists at all — and the run reads it from there.
	t.Run("a node without a bootstrap entry", func(t *testing.T) {
		dir := copyGolden(t, "b")
		editManifest(t, dir, func(m map[string]any) {
			delete(m["nodes"].([]any)[1].(map[string]any), "bootstrap")
		})
		wantInvalid(t, dir, "no bootstrap", "n2")
	})
	t.Run("a bootstrap entry naming a file the bundle lacks", func(t *testing.T) {
		dir := copyGolden(t, "b")
		mustRemove(t, filepath.Join(dir, "configs", "n3.cli"))
		wantInvalid(t, dir, "not in the bundle", "n3", "configs/n3.cli")
	})
	t.Run("a bootstrap entry naming a file outside the bundle", func(t *testing.T) {
		dir := copyGolden(t, "b")
		outside := filepath.Join(filepath.Dir(dir), "outside.cli")
		mustWrite(t, outside, "set / system name host-name outside\n")
		editManifest(t, dir, func(m map[string]any) {
			m["nodes"].([]any)[0].(map[string]any)["bootstrap"].(map[string]any)["file"] = "../outside.cli"
		})
		wantInvalid(t, dir, "not in the bundle", "n1", "../outside.cli")
	})
	// M4's format. A "1" bundle carries no configuration file and no artifact entry, so
	// deploying it would boot a twin running bootstrap alone and say nothing about it.
	// The golden directory this copies is this build's format,
	// which TestVerifyAcceptsTheGoldenBundle is the matching half of.
	// Each earlier format is refused naming both versions. A "1" bundle carries no
	// configuration file at all; a "2" carries one but nothing that says how each node's
	// bootstrap reaches it, so its push nodes would boot with containerlab's default
	// alone; a "3" says nothing of which ports intent disables, so verify would assert
	// them; a "4" was read through the generics and names no scope or mapping; a "5" cannot
	// say which of its nodes is a synthesized host. None is deployable by this build, and
	// none may fail late.
	for _, have := range []string{"1", "2", "3", "4", "5"} {
		t.Run("a bundle from format "+have, func(t *testing.T) {
			dir := copyGolden(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			mustWrite(t, path, strings.Replace(string(b),
				`"bundle_version": "`+bundleVersion+`"`, `"bundle_version": "`+have+`"`, 1))
			_, err = Verify(dir)
			var unsupported *ErrVersionUnsupported
			if !errors.As(err, &unsupported) || unsupported.Have != have || unsupported.Want != bundleVersion {
				t.Fatalf("Verify = %v, want *ErrVersionUnsupported naming %s and %s", err, have, bundleVersion)
			}
			if msg := err.Error(); !strings.Contains(msg, `"`+have+`"`) || !strings.Contains(msg, `"`+bundleVersion+`"`) {
				t.Errorf("message %q does not name both versions", msg)
			}
		})
	}
	// The bundle M11's binary deploys, word for word as contracts/cli.md's `twin
	// provision` row gives the refusal.
	t.Run("the contract's sentence for a bundle from format 3", func(t *testing.T) {
		dir := copyGolden(t, "b")
		path := filepath.Join(dir, "manifest.json")
		b, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		mustWrite(t, path, strings.Replace(string(b), `"bundle_version": "6"`, `"bundle_version": "3"`, 1))
		_, err = Verify(dir)
		if want := dir + ` is bundle_version "3"; this build deploys bundle_version "6"`; err == nil || err.Error() != want {
			t.Fatalf("Verify = %v, want %q", err, want)
		}
	})
	// A format from ahead of this build is refused by the same rule: the check is that
	// the version is the one written, not that it is not an old one.
	t.Run("a bundle from a later format", func(t *testing.T) {
		dir := copyGolden(t, "b")
		path := filepath.Join(dir, "manifest.json")
		b, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		mustWrite(t, path, strings.Replace(string(b),
			`"bundle_version": "`+bundleVersion+`"`, `"bundle_version": "7"`, 1))
		_, err = Verify(dir)
		var unsupported *ErrVersionUnsupported
		if !errors.As(err, &unsupported) || unsupported.Have != "7" || unsupported.Want != bundleVersion {
			t.Fatalf("Verify = %v, want *ErrVersionUnsupported naming 7 and %s", err, bundleVersion)
		}
	})
	// A real "4": the three-node golden's manifest as the last build of that format wrote
	// it (contract 0.2, an iftype on every row), valid against the frozen copy of its
	// contract, so the refusal is of a bundle a v0.2 host deployed and not of an edited
	// "5". twin provision reports it as bundle.version.unsupported naming both.
	t.Run("a manifest 4 as the last build of that format wrote it", func(t *testing.T) {
		b, err := os.ReadFile(filepath.Join("testdata", "three-node-4.manifest.json"))
		if err != nil {
			t.Fatal(err)
		}
		frozen := compileManifestSchema(t, filepath.Join("testdata", "contracts", "017-dcim-reader", "manifest.schema.json"))
		v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
		if err != nil {
			t.Fatal(err)
		}
		if err := frozen.Validate(v); err != nil {
			t.Fatalf("three-node-4.manifest.json is not a valid manifest 4:\n%v", err)
		}
		dir := copyGolden(t, "b")
		mustWrite(t, filepath.Join(dir, "manifest.json"), string(b))
		_, err = Verify(dir)
		var unsupported *ErrVersionUnsupported
		if !errors.As(err, &unsupported) || unsupported.Have != "4" || unsupported.Want != bundleVersion {
			t.Fatalf("Verify = %v, want *ErrVersionUnsupported naming 4 and %s", err, bundleVersion)
		}
		if want := dir + ` is bundle_version "4"; this build deploys bundle_version "6"`; err.Error() != want {
			t.Errorf("Verify = %q, want %q", err, want)
		}
	})
	// A real "5": the three-node golden's manifest as the last build of that format wrote it,
	// valid against 019's frozen copy of its contract, so the refusal is of a bundle a host of
	// 019 staged and not of an edited "6" (016, US7 scenario 2). twin provision reports it as
	// bundle.version.unsupported naming both.
	t.Run("a manifest 5 as the last build of that format wrote it", func(t *testing.T) {
		b, err := os.ReadFile(filepath.Join("testdata", "three-node-5.manifest.json"))
		if err != nil {
			t.Fatal(err)
		}
		frozen := compileManifestSchema(t, filepath.Join("testdata", "contracts", "019-following-removed", "manifest.schema.json"))
		v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
		if err != nil {
			t.Fatal(err)
		}
		if err := frozen.Validate(v); err != nil {
			t.Fatalf("three-node-5.manifest.json is not a valid manifest 5:\n%v", err)
		}
		dir := copyGolden(t, "b")
		mustWrite(t, filepath.Join(dir, "manifest.json"), string(b))
		_, err = Verify(dir)
		var unsupported *ErrVersionUnsupported
		if !errors.As(err, &unsupported) || unsupported.Have != "5" || unsupported.Want != bundleVersion {
			t.Fatalf("Verify = %v, want *ErrVersionUnsupported naming 5 and %s", err, bundleVersion)
		}
		if want := dir + ` is bundle_version "5"; this build deploys bundle_version "6"`; err.Error() != want {
			t.Errorf("Verify = %q, want %q", err, want)
		}
	})
	// A synthesized host carries its probe in place of a platform, and no artifact and no
	// bootstrap: no file of the bundle is its, so it is accepted without either (016). A node
	// with neither and no probe is a device's that lost its file, refused as before.
	t.Run("a host names no artifact and no bootstrap", func(t *testing.T) {
		dir := copyGolden(t, "b")
		editManifest(t, dir, func(m map[string]any) {
			m["nodes"] = append(m["nodes"].([]any), map[string]any{
				"name": "n1-loop-a", "provenance": "synthesized",
				"probe":    map[string]any{"name": "n1-loop", "endpoint": "a", "format": "ping", "package": map[string]any{"id": "ping", "source": "embedded"}},
				"platform": nil, "psp": nil, "image": "alpine:3.24.2", "management_port": "eth0", "artifact": nil, "bootstrap": nil,
			})
		})
		if _, err := Verify(dir); err != nil {
			t.Fatalf("Verify = %v, want a host accepted with no artifact and no bootstrap", err)
		}
		editManifest(t, dir, func(m map[string]any) {
			nodes := m["nodes"].([]any)
			delete(nodes[len(nodes)-1].(map[string]any), "probe")
		})
		wantInvalid(t, dir, "names no artifact", "n1-loop-a")
	})
	t.Run("bytes altered under the identity they were stored as", func(t *testing.T) {
		dir := copyGolden(t, goldenThreeNodeID)
		mustWrite(t, filepath.Join(dir, "configs", "n2.cli"), "set / system name host-name altered\n")
		computed, err := IDOfDir(dir)
		if err != nil {
			t.Fatal(err)
		}
		_, err = Verify(dir)
		var mismatch *ErrIDMismatch
		if !errors.As(err, &mismatch) || mismatch.Want != goldenThreeNodeID || mismatch.Got != computed {
			t.Fatalf("Verify = %v, want *ErrIDMismatch claiming %s, hashing to %s", err, goldenThreeNodeID, computed)
		}
		if !strings.Contains(err.Error(), computed) {
			t.Errorf("message %q does not name the identity the bytes hash to", err)
		}
	})
	t.Run("missing directory is not a refusal", func(t *testing.T) {
		_, err := Verify(filepath.Join(t.TempDir(), "absent"))
		var invalid *ErrInvalid
		var unsupported *ErrVersionUnsupported
		var mismatch *ErrIDMismatch
		if err == nil || errors.As(err, &invalid) || errors.As(err, &unsupported) || errors.As(err, &mismatch) {
			t.Errorf("Verify = %v, want a plain error: nothing was examined", err)
		}
	})
}

func compileManifestSchema(t *testing.T, path string) *jsonschema.Schema {
	t.Helper()
	const name = "manifest.schema.json"
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(name, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(name)
	if err != nil {
		t.Fatalf("compiling %s: %v", path, err)
	}
	return s
}

func wantInvalid(t *testing.T, dir string, says ...string) {
	t.Helper()
	_, err := Verify(dir)
	var invalid *ErrInvalid
	if !errors.As(err, &invalid) {
		t.Fatalf("Verify = %v, want *ErrInvalid", err)
	}
	for _, s := range says {
		if !strings.Contains(err.Error(), s) {
			t.Errorf("message %q does not say %q", err, s)
		}
	}
}

// editManifest rewrites dir's manifest through edit, as a generic document, so a test
// can drop or alter one entry without naming the compiler's types.
func editManifest(t *testing.T, dir string, edit func(m map[string]any)) {
	t.Helper()
	path := filepath.Join(dir, "manifest.json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	edit(m)
	out, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	mustWrite(t, path, string(out)+"\n")
}

func mustRemove(t *testing.T, path string) {
	t.Helper()
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
}

func mustWrite(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
