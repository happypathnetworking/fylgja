// Package ctm holds the Canonical Topology Model — the compiler's input and
// `intent read`'s output.
//
// The CTM is a thin projection of Fylgja's Infrahub generics plus provenance. It is
// deliberately not a second source of truth: it exists because synthesized nodes
// (boundary stubs, service mocks, traffic generators) are absent from Infrahub and so
// cannot live in types generated from it (D-010). At M1 it is close to a copy of the
// generated types, and should stay that thin.
//
// Struct field order is significant: it fixes the field order of the canonical JSON
// encoding, which the golden tests compare byte for byte.
package ctm

import (
	"crypto/md5"
	"encoding/hex"
)

// Interface kinds. `iftype` says what an interface *is*; use is not encoded here
// (D-003). Wiring behaviour is derived from it by the compiler.
const (
	IftypePhysical     = "physical"
	IftypeLoopback     = "loopback"
	IftypeSVI          = "svi"
	IftypeSubinterface = "subinterface"
)

// ImplementedIftypes are the kinds the M1 compiler handles. Any other declared kind
// is an explicit rejection, never a silent fall-through to physical.
var ImplementedIftypes = map[string]bool{
	IftypePhysical: true,
	IftypeLoopback: true,
}

// KnownIftypes are the kinds the contract declares, implemented or not.
var KnownIftypes = map[string]bool{
	IftypePhysical:     true,
	IftypeLoopback:     true,
	IftypeSVI:          true,
	IftypeSubinterface: true,
}

// Provenance says where one device, interface or link came from (D-010). Every object
// is Intent at M1; the other two exist because the CTM's reason for being is holding
// objects Infrahub does not know about, and a reader must be able to tell which is
// which without consulting the compiler that produced the file.
type Provenance string

const (
	// ProvenanceIntent is an object read from the source of truth. The default.
	ProvenanceIntent Provenance = "intent"
	// ProvenanceObserved is an object discovered from the running network.
	ProvenanceObserved Provenance = "observed"
	// ProvenanceSynthesized is an object Fylgja invented: a stub, a mock, a generator.
	ProvenanceSynthesized Provenance = "synthesized"
)

// IsZero makes `omitzero` on a Provenance field mean "is the default", so the tag is
// written only when it carries information. Normalize fills every object's tag in
// memory; a file that names `intent` on every object would be noise, and every CTM at
// M1 would be nothing but.
func (p Provenance) IsZero() bool { return p == "" || p == ProvenanceIntent }

// Envelope addresses the intent exactly: which branch, at what instant if the
// operator pinned one, when it was read, and against which schema and contract
// (D-012, D-023).
//
// `at` is present iff the operator supplied it — Fylgja never invents one.
// `observed_at` is recorded on every read and never reaches the bundle: it is how the
// read is reproduced, not part of what was read (Constitution VI, D-023).
type Envelope struct {
	Branch          string `json:"branch"`
	At              string `json:"at,omitempty"`
	ObservedAt      string `json:"observed_at"`
	SchemaHash      string `json:"schema_hash"`
	ContractVersion string `json:"contract_version"`
}

// Platform is the join key to a Platform Support Package.
type Platform struct {
	Vendor  string `json:"vendor"`
	NOS     string `json:"nos"`
	Version string `json:"version,omitempty"`
	Model   string `json:"model,omitempty"`
}

// Address is an interface address. Carried at M1, never configured: startup
// configuration is platform bootstrap only (Constitution IV).
type Address struct {
	CIDR   string `json:"cidr"`
	Family string `json:"family,omitempty"`
}

// Interface is one interface in production naming.
type Interface struct {
	Name       string     `json:"name"`
	Iftype     string     `json:"iftype"`
	MgmtOnly   bool       `json:"mgmt_only"`
	Enabled    *bool      `json:"enabled,omitempty"`
	Parent     string     `json:"parent,omitempty"`
	Addresses  []Address  `json:"addresses,omitempty"`
	Link       string     `json:"link,omitempty"`
	Provenance Provenance `json:"provenance,omitzero"`
}

// IsEnabled reports the interface's admin state, defaulting to true when unset.
func (i Interface) IsEnabled() bool { return i.Enabled == nil || *i.Enabled }

// Device is a network node. Name becomes the containerlab node name.
type Device struct {
	Name       string      `json:"name"`
	Platform   Platform    `json:"platform"`
	Role       string      `json:"role,omitempty"`
	Site       string      `json:"site,omitempty"`
	Interfaces []Interface `json:"interfaces"`
	// Artifact is the rendered configuration this device runs in production (M5,
	// D-028). Last before Provenance: the canonical encoding follows struct order, so
	// a field added anywhere else would move every bundle_id.
	//
	// A pointer because the codec must read a CTM written before M5, or by a read that
	// did not fetch one. Validation refuses such a CTM (artifact.missing); the codec
	// does not, so the refusal can name the device rather than failing to parse.
	Artifact   *Artifact  `json:"artifact,omitempty"`
	Provenance Provenance `json:"provenance,omitzero"`
}

// Artifact is one device's rendered configuration, as Infrahub served it.
//
// It carries no Infrahub identifier and no time of generation, only what the bytes are
// and what they hash to. That is what makes a regeneration to identical bytes move
// nothing: two reads either side of it produce the same CTM and the same bundle_id.
type Artifact struct {
	// Name is the definition's artifact_name, e.g. device-config. It is the package's
	// config.artifact_name, which is how the read selected this artifact.
	Name string `json:"name"`
	// ContentType is the artifact's own, e.g. text/plain; the package says which types
	// it accepts.
	ContentType string `json:"content_type"`
	// Checksum is Infrahub's, verbatim: the MD5 hex of Content (verified). The
	// read verifies it against the bytes it fetched, and validation and the compiler
	// verify it again, so a CTM that was edited by hand is caught before it is built.
	Checksum string `json:"checksum"`
	// Content is the bytes, UTF-8, exactly as served: never reordered, never
	// reformatted (Constitution IV). A CTM file therefore holds configuration,
	// which is why it lives in the store and never in a finding, a log or a payload.
	Content string `json:"content"`
}

// ChecksumOf is Infrahub's checksum algorithm: MD5 hex over the exact bytes (verified).
// It lives here, with the type, because three packages must agree on
// it — the read verifies what Infrahub served, validation verifies what a CTM file
// records, and the compiler verifies again before writing the bytes into a bundle.
//
// Integrity against Infrahub's own value and nothing more; it is never a security
// property. bundle_id is SHA-256 over the bundle's canonical bytes (D-011), which cover
// an artifact's content.
func ChecksumOf(content string) string {
	sum := md5.Sum([]byte(content)) //nolint:gosec // integrity against Infrahub's own checksum
	return hex.EncodeToString(sum[:])
}

// Endpoint identifies one side of a link.
type Endpoint struct {
	Device    string `json:"device"`
	Interface string `json:"interface"`
}

// ID is the endpoint's identifier, as used in findings and link ids.
func (e Endpoint) ID() string { return e.Device + ":" + e.Interface }

// Link is a point-to-point connection between exactly two interfaces.
type Link struct {
	ID         string     `json:"id"`
	Endpoints  []Endpoint `json:"endpoints"`
	Provenance Provenance `json:"provenance,omitzero"`
}

// CTM is one snapshot of intent.
type CTM struct {
	CTMVersion string   `json:"ctm_version"`
	Envelope   Envelope `json:"envelope"`
	Devices    []Device `json:"devices"`
	Links      []Link   `json:"links"`
}

// Version is the serialized CTM format version.
const Version = "1"

// ContractVersion is the generics contract this build understands. A branch declaring
// anything else is rejected before any other rule runs: findings against a contract
// Fylgja does not understand would be noise.
//
// 0.2 at M5: conformance now demands that every kind implementing FylgjaDevice also
// inherit CoreArtifactTarget, without which no artifact can be rendered for it, so an
// implementing branch has something new to declare. The generics themselves
// are unchanged.
const ContractVersion = "0.2"

// RequiredGenerics are the generics every conforming schema must have at least one
// concrete kind implementing. Kept deliberately short: each one is a constraint
// imposed on somebody else's model.
var RequiredGenerics = []string{
	DeviceGeneric,
	"FylgjaInterface",
	"FylgjaLink",
	"FylgjaPlatform",
}

// ContractKind is the singleton node kind carrying the contract version.
const ContractKind = "FylgjaContract"

// DeviceGeneric is the generic a device kind implements; it is the first of
// RequiredGenerics.
const DeviceGeneric = "FylgjaDevice"

// ArtifactTargetGeneric is Infrahub's own generic for a node an artifact can be rendered
// for. Contract 0.2 demands it of every kind implementing DeviceGeneric: it is
// not Fylgja's to require of the other generics, and not one of RequiredGenerics,
// because a kind implementing it and not DeviceGeneric is no concern of Fylgja's.
const ArtifactTargetGeneric = "CoreArtifactTarget"

// Device returns the named device, or nil.
func (c *CTM) Device(name string) *Device {
	for i := range c.Devices {
		if c.Devices[i].Name == name {
			return &c.Devices[i]
		}
	}
	return nil
}

// Interface returns the named interface on a device, or nil.
func (d *Device) Interface(name string) *Interface {
	for i := range d.Interfaces {
		if d.Interfaces[i].Name == name {
			return &d.Interfaces[i]
		}
	}
	return nil
}

// Link returns the link with the given id, or nil.
func (c *CTM) Link(id string) *Link {
	for i := range c.Links {
		if c.Links[i].ID == id {
			return &c.Links[i]
		}
	}
	return nil
}
