//go:build contract || fixture

package testsupport

import (
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// This file is what test support still writes in the Fylgja generics' kinds (FylgjaContract,
// NetworkPlatform, NetworkDevice, NetworkInterface, NetworkLink). The tree no longer ships
// them: schema/ holds the schema library and the stage kind alone, and every seed writes the
// library's kinds. A branch made from main still holds the generics, since main does until
// its migration (017's T056), so these keep working there. They are kept only so that their
// tier-2 caller, the generics' defect test, compiles until 017's T044 rewrites or removes
// it and this file with it. The contract singleton's seed went at T036 with the
// generics' conformance tests, its last callers.

// ContractVersion is the generics contract version SeedDefects declares.
const ContractVersion = ctm.ContractVersion

// Defect names the five defects SeedDefects plants, by the rule each one trips. They
// are exactly the defects Infrahub's own schema will let a branch hold: every other
// rule Fylgja enforces is one Infrahub enforces first, and a branch cannot be made to
// violate it (verified read-only). The rest stay covered by the CTM
// fixtures under testdata/ctm/defects, which is where a hand-edited or foreign CTM is
// caught anyway.
const (
	DefectIftypeUnimplemented = "interface.iftype.unimplemented"
	DefectMgmtOnlyIftype      = "interface.mgmt_only.iftype"
	DefectPlatformUnsupported = "platform.unsupported"
	DefectLinkSameDevice      = "link.endpoints.same_device"
	DefectLinkEndpointIftype  = "link.endpoint.iftype"
)

// SeededDefects is the set of rules a branch seeded by SeedDefects must trip, all in
// one pass.
var SeededDefects = []string{
	DefectIftypeUnimplemented,
	DefectMgmtOnlyIftype,
	DefectPlatformUnsupported,
	DefectLinkSameDevice,
	DefectLinkEndpointIftype,
}

// SeededDefectObjects names the object each seeded defect is reported against, in the
// CTM's identity scheme (device, device:interface, or a canonical link id). Asserting
// on these rather than on rules alone is what proves the read names *which* thing is
// wrong, not merely that something is.
var SeededDefectObjects = map[string]string{
	DefectIftypeUnimplemented: "d1:vlan100",
	DefectMgmtOnlyIftype:      "d1:lo0",
	DefectPlatformUnsupported: "d3",
	DefectLinkSameDevice:      "d1:ethernet-1/1|d1:ethernet-1/2",
	DefectLinkEndpointIftype:  "d1:lo1|d2:ethernet-1/1",
}

// SeedDefects populates a branch with intent that is well-formed for Infrahub and
// unbuildable for Fylgja, so a read reports all five defects in one pass and writes
// no CTM.
//
// The layout is deliberate. `platform.unsupported` stops validation of that device's
// interfaces, so the unsupported platform gets a device of its own (d3) and the two
// interface defects live on a device Fylgja does support (d1). The two link defects
// need distinct links: one folded back onto a single device, one reaching a loopback.
func (c *Client) SeedDefects(branch string) error {
	if _, err := c.create(branch, "FylgjaContract",
		fmt.Sprintf(`{version: {value: %q}}`, ContractVersion)); err != nil {
		return err
	}

	supported, err := c.create(branch, "NetworkPlatform",
		`{vendor: {value: "nokia"}, nos: {value: "srlinux"}, version: {value: "24.7"}}`)
	if err != nil {
		return err
	}
	// Free text, so Infrahub stores it happily and Fylgja has no support package for
	// it — which is the whole defect.
	unsupported, err := c.create(branch, "NetworkPlatform",
		`{vendor: {value: "acme"}, nos: {value: "acme_os"}}`)
	if err != nil {
		return err
	}

	d1, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d1"}, platform: {id: %q}, role: {value: "leaf"}}`, supported))
	if err != nil {
		return err
	}
	d2, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d2"}, platform: {id: %q}, role: {value: "leaf"}}`, supported))
	if err != nil {
		return err
	}
	// platform.unsupported: nothing else about d3 is ever examined, so it needs no
	// interfaces.
	d3, err := c.create(branch, "NetworkDevice",
		fmt.Sprintf(`{name: {value: "d3"}, platform: {id: %q}, role: {value: "leaf"}}`, unsupported))
	if err != nil {
		return err
	}

	iface := func(device, name, iftype, extra string) (string, error) {
		return c.create(branch, "NetworkInterface", fmt.Sprintf(
			`{name: {value: %q}, iftype: {value: %q}, device: {id: %q}%s}`, name, iftype, device, extra))
	}

	// Two cabled ports on one device, so a link can be folded back onto it.
	d1e1, err := iface(d1, "ethernet-1/1", "physical", "")
	if err != nil {
		return err
	}
	d1e2, err := iface(d1, "ethernet-1/2", "physical", "")
	if err != nil {
		return err
	}
	// interface.iftype.unimplemented: svi is in the contract's vocabulary and is a
	// dropdown choice on the reference schema, so Infrahub accepts it.
	if _, err := iface(d1, "vlan100", "svi", ""); err != nil {
		return err
	}
	// interface.mgmt_only.iftype: mgmt_only is a plain boolean on any kind, so a
	// loopback can carry it — and means nothing when it does.
	if _, err := iface(d1, "lo0", "loopback", `, mgmt_only: {value: true}`); err != nil {
		return err
	}
	// link.endpoint.iftype: a loopback with a link on it.
	d1lo1, err := iface(d1, "lo1", "loopback", "")
	if err != nil {
		return err
	}
	d2e1, err := iface(d2, "ethernet-1/1", "physical", "")
	if err != nil {
		return err
	}

	// link.endpoints.same_device: two endpoints satisfy min 2 / max 2 even when both
	// are on one device.
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, d1e1, d1e2)); err != nil {
		return err
	}
	if _, err := c.create(branch, "NetworkLink",
		fmt.Sprintf(`{endpoints: [{id: %q}, {id: %q}]}`, d1lo1, d2e1)); err != nil {
		return err
	}
	// Every device renders its artifact, as every seed's do, so the five
	// defects are the only findings: no artifact.missing beside them. d3's is rendered
	// too and never selected, since no package names the artifact its platform takes.
	return c.generateFor(branch, []string{d1, d2, d3})
}
