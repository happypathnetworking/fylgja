// Package ctm holds the Canonical Topology Model — the compiler's input and
// `intent read`'s output.
//
// The CTM is the contract between a source of truth and the compiler (D-057): a reader
// maps one source's model onto it by one documented mapping, and the envelope names
// which reader produced it and which version of which model it read. It is
// deliberately not a second source of truth: it exists because synthesized nodes
// (boundary stubs, service mocks, traffic generators) are absent from any source and so
// cannot live in types generated from one (D-010).
//
// Struct field order is significant: it fixes the field order of the canonical JSON
// encoding, which the golden tests compare byte for byte.
package ctm

import (
	"crypto/md5"
	"encoding/hex"
)

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
// operator pinned one, when it was read, against which schema, under which scope, by
// which mapping, and what that mapping could not carry (D-012, D-023, D-057).
//
// `at` is present iff the operator supplied it — Fylgja never invents one.
// `observed_at` is recorded on every read and never reaches the bundle: it is how the
// read is reproduced, not part of what was read (Constitution VI, D-023).
type Envelope struct {
	Branch     string `json:"branch"`
	At         string `json:"at,omitempty"`
	ObservedAt string `json:"observed_at"`
	SchemaHash string `json:"schema_hash"`
	// Scope is the scope the read was made under, tag:<name> (017).
	Scope string `json:"scope"`
	// Mapping names the reader that produced this CTM and the model version it read.
	Mapping Mapping `json:"mapping"`
	// Fidelity is the reader's list of what it approximated and what it omitted, sorted
	// by (disposition, object) and written [] rather than null. The compiler copies it
	// into the manifest unchanged and holds no table of any source's rows (FR-029).
	Fidelity []FidelityRow `json:"fidelity"`
}

// Mapping says which reader produced a CTM and which version of which model it read:
// what a CTM's mapping was, which Constitution VI's version of the contract became.
type Mapping struct {
	Reader  string `json:"reader"`
	Model   string `json:"model"`
	Version string `json:"version"`
}

// The Infrahub reader of the schema library's DCIM, at the commit it was written
// against (017).
const (
	ReaderInfrahubDCIM = "infrahub-dcim"
	ModelSchemaLibrary = "opsmill/schema-library"
	ModelVersion       = "26336e9"
)

// FidelityRow is one field a reader approximated, or one source object it omitted
// (Constitution X). Its meaning is the reader's: no other package interprets a row.
type FidelityRow struct {
	// Disposition is "approximated" or "omitted".
	Disposition string `json:"disposition"`
	// Object is the CTM field approximated, or the source object omitted.
	Object string `json:"object"`
	// Source is the source field or kind the row was read from.
	Source string `json:"source"`
	Reason string `json:"reason"`
}

// The two dispositions of a fidelity row.
const (
	FidelityApproximated = "approximated"
	FidelityOmitted      = "omitted"
)

// Platform names the support package a device's platform resolved to, and the
// platform's version when the source carries one.
type Platform struct {
	// Package is the package's platform.id.
	Package string `json:"package"`
	Version string `json:"version,omitempty"`
}

// Interface is one port in production naming: cabled when it terminates a link, the
// management port when MgmtOnly, configured-not-cabled otherwise. A source's non-port
// interfaces are never read (017).
type Interface struct {
	Name       string     `json:"name"`
	MgmtOnly   bool       `json:"mgmt_only"`
	Enabled    *bool      `json:"enabled,omitempty"`
	Link       string     `json:"link,omitempty"`
	Provenance Provenance `json:"provenance,omitzero"`
}

// IsEnabled reports the interface's admin state, defaulting to true when unset.
func (i Interface) IsEnabled() bool { return i.Enabled == nil || *i.Enabled }

// Device is a network node. Name becomes the containerlab node name.
type Device struct {
	Name       string      `json:"name"`
	Platform   Platform    `json:"platform"`
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
//
// "2" at 017: the platform is the package it resolved to, every interface is a port, and
// the envelope carries the scope, the mapping and the fidelity list in place of the
// generics contract's version (D-057). Nothing converts a "1".
const Version = "2"

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
