package validate

import (
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// checkArtifacts refuses a CTM that cannot be built into a configured twin.
//
// The read decides which artifact is a device's configuration and verifies what
// Infrahub served (internal/intent). Those questions need Infrahub, so they cannot live
// here. What can live here is what survives into the CTM, and must therefore hold of
// any CTM whatever wrote it: every device carries an artifact of the name its package
// gives its configuration, and every artifact's content is the content its checksum
// describes.
//
// Both are mirrored by the compiler's own guards, word for word, for the reason
// `ctm.devices.empty` is: a rule only the compiler knows
// would let `intent read` write a CTM that `twin compile` then refuses, and "a branch
// that reads clean will compile" is what makes the two commands one pipeline rather
// than two opinions. A test asserts the two wordings are byte-identical.
//
// A device with no artifact is named per device rather than the file rejected as an
// unknown version: a CTM written before M5 is refused by naming what it lacks, which is
// what tells an operator to read again rather than to find a converter.
//
// A device whose platform no package covers is left to platform.unsupported, as the
// compiler, which reaches its artifact guards only once it holds the device's package,
// leaves it: the artifact's name is the package's, so the read could select none, and
// naming the device again would say one fault twice.
func checkArtifacts(c *ctm.CTM, reg *psp.Registry, list *findings.List) {
	seen := map[string]bool{}
	for _, d := range c.Devices {
		if d.Name == "" {
			// checkDevices names this; an artifact finding about a nameless device
			// could not say which device it was about.
			continue
		}
		if seen[d.Name] {
			// checkDevices refuses the duplicate name itself. Naming the same device
			// twice here would say one fault twice, as it does there.
			continue
		}
		seen[d.Name] = true
		p, ok := reg.Lookup(d.Platform.NOS)
		if !ok {
			continue
		}
		if d.Artifact == nil {
			list.Add(findings.Rejection, findings.RuleArtifactMissing, d.Name,
				artifactMissingMessage(d.Name))
			continue
		}
		if d.Artifact.Name != p.Config.ArtifactName {
			// An artifact of another name is not the device's configuration, and its
			// name becomes a file name in the bundle: named as the package's
			// startup_format, it would overwrite the bootstrap and boot the node on it
			// (Constitution IV). The device has no artifact of the package's name,
			// which is what artifact.missing says; its checksum is not
			// worth checking, since nothing will be built from it.
			list.Add(findings.Rejection, findings.RuleArtifactMissing, d.Name,
				artifactMisnamedMessage(d.Name, d.Artifact.Name, p.Platform.ID, p.Config.ArtifactName))
			continue
		}
		if sum := ctm.ChecksumOf(d.Artifact.Content); sum != d.Artifact.Checksum {
			list.Add(findings.Rejection, findings.RuleArtifactChecksumMismatch, d.Name,
				checksumMismatchMessage(d.Name, d.Artifact.Name, sum, d.Artifact.Checksum))
		}
	}
}

// artifactMissingMessage, artifactMisnamedMessage and checksumMismatchMessage are
// worded exactly as the compiler's guards word them, and are deliberately a second copy
// rather than a shared helper: internal/validate imports internal/compiler, so the
// compiler cannot import back, and M1 settled this for ctm.devices.empty the same way
// (and for fidelity.forwarding.mixed, which bundle "3" retired). A test compiles and
// validates one CTM and
// asserts the two are byte for byte the same, which is the guard against them drifting
// apart.
func artifactMissingMessage(device string) string {
	return fmt.Sprintf(
		"device %q carries no configuration artifact; a CTM written before M5, or a read that did not fetch it",
		device)
}

// artifactMisnamedMessage names the device, the name its artifact carries and the name
// the package expects: an operator must see which of the CTM and the package to look at.
func artifactMisnamedMessage(device, carried, pspID, expected string) string {
	return fmt.Sprintf(
		"device %q carries no configuration artifact named %q, as the %s package names it; the artifact it carries is named %q",
		device, expected, pspID, carried)
}

// checksumMismatchMessage names both values: the one the content hashes to and the one
// the CTM records. Which is wrong is not for Fylgja to say — a hand-edited file and a
// corrupted fetch look identical here — so both are printed and neither is blamed.
func checksumMismatchMessage(device, artifact, got, recorded string) string {
	return fmt.Sprintf("device %s: artifact %s has content hashing to %s, but records checksum %s",
		device, artifact, got, recorded)
}
