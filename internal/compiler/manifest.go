package compiler

import (
	"encoding/json"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// BundleVersion is the artifact bundle format version — the contract M2 consumes.
//
// "2" at M5: every node gains a configuration file and a manifest entry naming it, so a
// deploy that read a "1" bundle would boot a twin running bootstrap alone and say
// nothing about it.
//
// "3" at M7: fidelity.production_forwarding becomes an object keyed by platform, so a
// bundle of two platforms asserts each one's own value rather than a single claim that
// could only be true of one of them (D-025); nodes[].bootstrap says which file carries
// each node's bootstrap and how it reaches it, which a reader could not otherwise tell
// from a topology that names no startup-config; and mapping[].node_name and
// fidelity.lossy become unconditional, ending M6's deliberate exception to the rule that
// an empty list is emitted as [].
//
// "4" at M12: mapping[].enabled carries each interface's intent admin state on every
// row, so `twin verify` can tell a port intent disables, which it skips, from one the
// node lost. A reader of a "3" manifest takes every row as enabled, the
// CTM's own default; the deploy refuses one, as it refused each earlier format.
//
// bundle.Verify accepts this version alone and refuses any other naming both.
const BundleVersion = "4"

// FidelityAsserted is the only basis Fylgja can claim at M1.
const FidelityAsserted = "asserted"

// Provenance is the intent's address: which branch, pinned to what instant if the
// operator pinned one, against which schema and contract.
//
// It is the CTM envelope minus `observed_at`. When the read happened is a property of
// the read, not of the intent, and putting it here would make every bundle of the same
// intent a different bundle (Constitution VI; D-023). Nothing about the host, the
// clock or the build appears either — a version stamp would change bundle_id on every
// release.
type Provenance struct {
	Branch          string `json:"branch"`
	At              string `json:"at,omitempty"`
	SchemaHash      string `json:"schema_hash"`
	ContractVersion string `json:"contract_version"`
}

// provenanceOf copies the addressing half of a CTM envelope into the manifest.
func provenanceOf(e ctm.Envelope) Provenance {
	return Provenance{
		Branch:          e.Branch,
		At:              e.At,
		SchemaHash:      e.SchemaHash,
		ContractVersion: e.ContractVersion,
	}
}

// ManifestNode records one node and the platform support it was built with.
type ManifestNode struct {
	Name           string      `json:"name"`
	Platform       string      `json:"platform"`
	PSP            ManifestPSP `json:"psp"`
	Image          string      `json:"image"`
	ManagementPort string      `json:"management_port"`
	// Artifact names the configuration file this node is pushed after it boots (M5,
	// D-028). A pointer only so the field's absence is expressible; the compiler refuses
	// a device without one, so every node of a bundle this build writes has it.
	Artifact *ManifestArtifact `json:"artifact,omitempty"`
	// Bootstrap names the node's bootstrap file and how it reaches the node. On every
	// node, because a reader of a "3" bundle cannot otherwise tell a node whose topology
	// names no startup-config from one whose bootstrap was forgotten.
	Bootstrap ManifestBootstrap `json:"bootstrap"`
}

// ManifestBootstrap is the bootstrap file of one node, and the way it is applied.
//
// File is written for every node either way; what Via says is who applies it. A reader
// of the topology alone would see no startup-config on a push node and be unable to tell
// that from a node with no bootstrap at all, which is why the manifest states it.
type ManifestBootstrap struct {
	File string `json:"file"`
	// Via is the package's config.bootstrap_via, defaulted: "startup_config" when the
	// lab tool applies the file at deploy, "push" when the push sends its lines ahead
	// of the artifact's.
	Via string `json:"via"`
}

// ManifestArtifact says what a node's configuration is, without repeating it.
//
// Name, content type and checksum are Infrahub's, verbatim; size and file describe where
// the bytes landed in the bundle. No Infrahub identifier and no time of generation, so a
// regeneration to identical bytes moves nothing. The checksum is
// Infrahub's own MD5: there is no second checksum, and the algorithm's name lives
// in the contract rather than in the data.
type ManifestArtifact struct {
	Name        string `json:"name"`
	ContentType string `json:"content_type"`
	Checksum    string `json:"checksum"`
	Size        int    `json:"size"`
	File        string `json:"file"`
}

// ManifestPSP identifies the support package used, and whether it was the shipped one.
type ManifestPSP struct {
	ID     string `json:"id"`
	Source string `json:"source"`
}

// Fidelity is what the twin does not reproduce.
//
// With no production state collection, fidelity is asserted and never measured
// (D-022). That makes this the only trust signal Fylgja has, so it is emitted on
// every build and says plainly where the twin stops resembling the network.
//
// Basis is first and always "asserted": Constitution X requires every surface that
// reports fidelity to say it is asserted rather than measured, and the manifest is
// that surface. A reader who sees only this block must not have to know the milestone
// to know how much the numbers are worth.
type Fidelity struct {
	Basis string `json:"basis"`
	// ProductionForwarding is one entry per support package in the bundle, platform id
	// to "hardware" or "software". An object rather than a single value because a
	// bundle can hold nodes of platforms that answer differently, and one value could
	// then only be true of some of them: before "3" the compiler refused such a bundle
	// outright rather than describe it (D-025). Go's encoder sorts map keys, so the
	// bytes are deterministic without the compiler sorting anything.
	ProductionForwarding map[string]string `json:"production_forwarding"`
	Approximations       []string          `json:"approximations"`
	Omitted              []string          `json:"omitted"`
	// Lossy records every lossy mapping and every shared port: the places where
	// the twin's ports are fewer than production's interfaces.
	//
	// Always present, [] when empty, like every other list here. M6 emitted it only
	// with content, so that a bundle with nothing lossy in it stayed byte-identical to
	// M5's and no golden or following twin moved for the upgrade; that exception was
	// written to expire with the next bundle_version bump, and this is it (D-025).
	Lossy []LossyMapping `json:"lossy"`
}

// LossyMapping is one interface a lossy rule mapped, or whose port another interface of
// the same device also renders to, whichever rule.
type LossyMapping struct {
	Device    string `json:"device"`
	Interface string `json:"interface"`
	// Port is the rendered port, also for an interface the mapping table shows omitted
	// because a cabled one holds it.
	Port     string `json:"port"`
	NodeName string `json:"node_name"`
	// Rule is the rule's name, never its position or pattern.
	Rule string `json:"rule"`
	// Lossy is whether that rule is declared lossy; false only for an interface recorded
	// because its port is shared.
	Lossy bool `json:"lossy"`
	// Shares lists every other interface of the device rendering to Port. Always a list:
	// the exception is the field `lossy`, not its members' lists.
	Shares []Share `json:"shares"`
}

// Share is one other interface rendering to a recorded interface's port.
type Share struct {
	Interface string `json:"interface"`
	Rule      string `json:"rule"`
	Cabled    bool   `json:"cabled"`
}

// Manifest is the bundle's self-description: where the intent came from, what each
// interface became, what was left out, and how far any of it can be trusted.
type Manifest struct {
	BundleVersion string         `json:"bundle_version"`
	Provenance    Provenance     `json:"provenance"`
	Nodes         []ManifestNode `json:"nodes"`
	Mapping       []MappingRow   `json:"mapping"`
	Links         []CabledLink   `json:"links"`
	Omissions     []Omission     `json:"omissions"`
	Fidelity      Fidelity       `json:"fidelity"`
}

// marshalManifest encodes the manifest deterministically: every list sorted, fixed
// field order from the struct definitions, two-space indent, trailing newline.
func marshalManifest(m *Manifest) ([]byte, error) {
	sort.SliceStable(m.Nodes, func(i, j int) bool { return m.Nodes[i].Name < m.Nodes[j].Name })
	sort.SliceStable(m.Mapping, func(i, j int) bool {
		if m.Mapping[i].Device != m.Mapping[j].Device {
			return m.Mapping[i].Device < m.Mapping[j].Device
		}
		return m.Mapping[i].Interface < m.Mapping[j].Interface
	})
	sort.SliceStable(m.Links, func(i, j int) bool { return m.Links[i].ID < m.Links[j].ID })
	sort.SliceStable(m.Omissions, func(i, j int) bool {
		if m.Omissions[i].Object != m.Omissions[j].Object {
			return m.Omissions[i].Object < m.Omissions[j].Object
		}
		return m.Omissions[i].Rule < m.Omissions[j].Rule
	})
	sort.Strings(m.Fidelity.Omitted)
	sort.SliceStable(m.Fidelity.Lossy, func(i, j int) bool {
		a, b := m.Fidelity.Lossy[i], m.Fidelity.Lossy[j]
		if a.Device != b.Device {
			return a.Device < b.Device
		}
		return a.Interface < b.Interface
	})
	for i := range m.Fidelity.Lossy {
		shares := m.Fidelity.Lossy[i].Shares
		sort.SliceStable(shares, func(x, y int) bool { return shares[x].Interface < shares[y].Interface })
		if shares == nil {
			m.Fidelity.Lossy[i].Shares = []Share{}
		}
	}

	// Empty lists are emitted as [] rather than null: a reader should not have to
	// distinguish "nothing was omitted" from "omissions were not recorded".
	if m.Nodes == nil {
		m.Nodes = []ManifestNode{}
	}
	if m.Mapping == nil {
		m.Mapping = []MappingRow{}
	}
	if m.Links == nil {
		m.Links = []CabledLink{}
	}
	if m.Omissions == nil {
		m.Omissions = []Omission{}
	}
	if m.Fidelity.Approximations == nil {
		m.Fidelity.Approximations = []string{}
	}
	if m.Fidelity.Omitted == nil {
		m.Fidelity.Omitted = []string{}
	}
	if m.Fidelity.Lossy == nil {
		m.Fidelity.Lossy = []LossyMapping{}
	}

	b, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return nil, err
	}
	return append(b, '\n'), nil
}
