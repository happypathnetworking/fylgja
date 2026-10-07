package bundle

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// The layout and format Verify checks, as the compiler writes them (compiler.ManifestFile,
// compiler.TopologyFile, compiler.BundleVersion). Named here rather than imported because
// the compiler's own tests import this package; TestVerifyAgreesWithTheCompiler keeps the
// two in step.
const (
	manifestFile = "manifest.json"
	topologyFile = "topology.clab.yml"
	// "2" at M5: every node gained a configuration file and a manifest entry naming it.
	// A "1" bundle deployed by this build would boot a twin running
	// bootstrap alone.
	//
	// "3" at M7: every node gains a bootstrap entry naming its file and how it reaches
	// the node. A "2" bundle deployed by this build would have no way to say that a node
	// whose topology names no startup-config is one whose bootstrap goes through the
	// push, so its nodes would boot with nothing but containerlab's default.
	//
	// "4" at M12: every mapping row says whether intent enables the interface. A "3"
	// bundle deploys the same twin, but a twin staged from it would have
	// verify assert a port intent disables, so it is refused as each earlier version is,
	// naming both.
	bundleVersion = "4"
)

// ErrInvalid reports a directory that is not a bundle this build can read: no manifest, a
// manifest that does not parse, no topology, or a manifest that names no artifact or
// bootstrap file for a node, one the bundle does not carry, or an artifact whose bytes
// are not the checksum and size the entry gives.
type ErrInvalid struct {
	Dir, Reason string
}

func (e *ErrInvalid) Error() string {
	return fmt.Sprintf("%s is not a bundle: %s", e.Dir, e.Reason)
}

// ErrVersionUnsupported reports a bundle in a format this build does not deploy.
type ErrVersionUnsupported struct {
	Dir, Have, Want string
}

func (e *ErrVersionUnsupported) Error() string {
	return fmt.Sprintf("%s is bundle_version %q; this build deploys bundle_version %q", e.Dir, e.Have, e.Want)
}

// Verify checks that dir is a bundle this build deploys and returns the identity its bytes
// hash to (contracts/cli.md, twin provision steps 1–3). In order:
//
//   - a directory that cannot be read is a plain error: nothing was examined, so there is
//     nothing to call invalid;
//   - no manifest.json, a manifest that does not parse, or one with no bundle_version is
//     *ErrInvalid;
//   - any bundle_version other than the one the compiler writes is *ErrVersionUnsupported,
//     checked before the topology, since another format may lay its files out differently;
//   - no topology.clab.yml is *ErrInvalid;
//   - a node whose manifest entry names no artifact or no bootstrap, or names a file that is not a regular
//     file inside the bundle, is *ErrInvalid naming the node and what is missing: the
//     format promises every node a configuration file, and the push step's own guard is
//     only the second lock;
//   - an artifact file whose bytes do not hash to the entry's checksum, or whose length is
//     not the entry's size, is *ErrInvalid naming the node, the file and both values: the
//     manifest describes what the run will push and record, so it must describe the bytes
//     it carries. With this passed, the push step's own hash of the staged copy
//     can fail only for a change since staging;
//   - a directory named like a bundle identity, as a store entry is, claims that identity:
//     bytes hashing to another is *ErrIDMismatch naming what they do hash to (D-024). Any
//     other name claims nothing.
func Verify(dir string) (string, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return "", fmt.Errorf("reading bundle directory: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("reading bundle directory: %s is not a directory", dir)
	}
	if _, err := os.ReadDir(dir); err != nil {
		return "", fmt.Errorf("reading bundle directory: %w", err)
	}

	b, err := os.ReadFile(filepath.Join(dir, manifestFile))
	if errors.Is(err, fs.ErrNotExist) {
		return "", &ErrInvalid{Dir: dir, Reason: "no " + manifestFile}
	}
	if err != nil {
		return "", fmt.Errorf("reading %s: %w", manifestFile, err)
	}
	var m struct {
		BundleVersion *string `json:"bundle_version"`
		Nodes         []struct {
			Name     string `json:"name"`
			Artifact *struct {
				File     string `json:"file"`
				Checksum string `json:"checksum"`
				Size     int64  `json:"size"`
			} `json:"artifact"`
			Bootstrap *struct {
				File string `json:"file"`
				Via  string `json:"via"`
			} `json:"bootstrap"`
		} `json:"nodes"`
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return "", &ErrInvalid{Dir: dir, Reason: manifestFile + " does not parse: " + err.Error()}
	}
	if m.BundleVersion == nil {
		return "", &ErrInvalid{Dir: dir, Reason: manifestFile + " has no bundle_version"}
	}
	if *m.BundleVersion != bundleVersion {
		return "", &ErrVersionUnsupported{Dir: dir, Have: *m.BundleVersion, Want: bundleVersion}
	}

	topo, err := os.Stat(filepath.Join(dir, topologyFile))
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return "", &ErrInvalid{Dir: dir, Reason: "no " + topologyFile}
	case err != nil:
		return "", fmt.Errorf("reading %s: %w", topologyFile, err)
	case !topo.Mode().IsRegular():
		return "", &ErrInvalid{Dir: dir, Reason: topologyFile + " is not a file"}
	}

	// The format's promise: every node has a configuration file and a manifest entry
	// naming it (bundleVersion). A manifest that breaks it would otherwise stage, deploy
	// and reach readiness before the push step refused it (the workflow's guard, the
	// second lock), a minute and a teardown after a refusal was possible.
	for _, n := range m.Nodes {
		if n.Artifact == nil {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf("%s names no artifact for node %s", manifestFile, n.Name)}
		}
		if !fileInBundle(dir, n.Artifact.File) {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf(
				"%s names artifact file %s for node %s, which is not in the bundle", manifestFile, n.Artifact.File, n.Name)}
		}
		// The entry's checksum and size are what the run pushes by and records in
		// twin.json; a file they do not describe is not the bundle's own. IDOfDir reads
		// the same bytes just after, so this costs one more hash per node.
		content, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(path.Clean(n.Artifact.File))))
		if err != nil {
			return "", fmt.Errorf("reading %s: %w", n.Artifact.File, err)
		}
		if sum := md5.Sum(content); hex.EncodeToString(sum[:]) != n.Artifact.Checksum {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf(
				"artifact file %s for node %s hashes to %s, not the checksum %s its %s entry gives",
				n.Artifact.File, n.Name, hex.EncodeToString(sum[:]), n.Artifact.Checksum, manifestFile)}
		}
		if int64(len(content)) != n.Artifact.Size {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf(
				"artifact file %s for node %s is %d bytes, not the size %d its %s entry gives",
				n.Artifact.File, n.Name, len(content), n.Artifact.Size, manifestFile)}
		}

		// The same promise for the bootstrap, which "3" added: every node has one and
		// the manifest names it. A node whose bootstrap reaches it through the push
		// carries no startup-config in the topology, so the manifest's entry is the
		// only thing that says the file exists at all — and the run reads it from
		// there. No checksum: the bootstrap is rendered from the package, not fetched,
		// so the bundle's own identity already covers its bytes.
		if n.Bootstrap == nil || n.Bootstrap.File == "" {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf("%s names no bootstrap for node %s", manifestFile, n.Name)}
		}
		if !fileInBundle(dir, n.Bootstrap.File) {
			return "", &ErrInvalid{Dir: dir, Reason: fmt.Sprintf(
				"%s names bootstrap file %s for node %s, which is not in the bundle", manifestFile, n.Bootstrap.File, n.Name)}
		}
	}

	id, err := IDOfDir(dir)
	if err != nil {
		return "", err
	}
	if claimed := filepath.Base(filepath.Clean(dir)); IsID(claimed) && claimed != id {
		return "", &ErrIDMismatch{Path: dir, Want: claimed, Got: id}
	}
	return id, nil
}

// fileInBundle reports whether file, a manifest's slash-separated path, names a regular
// file under dir. A path that is empty, absolute or leads out of dir names nothing the
// bundle carries, whatever it might resolve to.
func fileInBundle(dir, file string) bool {
	if file == "" || path.IsAbs(file) {
		return false
	}
	rel := path.Clean(file)
	if rel == "." || rel == ".." || strings.HasPrefix(rel, "../") {
		return false
	}
	info, err := os.Stat(filepath.Join(dir, filepath.FromSlash(rel)))
	return err == nil && info.Mode().IsRegular()
}
