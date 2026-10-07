package compiler

// Disposition is what the compiler decided to do with one interface.
type Disposition string

const (
	// DispCabled becomes a veth link in the twin.
	DispCabled Disposition = "cabled"
	// DispManagement becomes the node's management connection.
	DispManagement Disposition = "management"
	// DispConfiguredNotCabled exists on the node but is never wired.
	DispConfiguredNotCabled Disposition = "configured-not-cabled"
	// DispOmitted is not represented in the twin at all, and says so in the manifest.
	DispOmitted Disposition = "omitted"
)

// MappingRow is one interface's fate: what it was, where it landed, and why.
// One row exists for every interface in intent — that is the invariant that makes
// "never silently dropped" checkable.
type MappingRow struct {
	Device    string `json:"device"`
	Interface string `json:"interface"`
	Iftype    string `json:"iftype"`
	MgmtOnly  bool   `json:"mgmt_only"`
	// Enabled is the interface's intent admin state (ctm.Interface.IsEnabled), written
	// true or false on every row from bundle "4". A row read from a "3" manifest has no
	// key and reads nil, which IsEnabled takes as enabled: the CTM's own default. Verify
	// asserts nothing of a cabled port whose row says false.
	// The topology and the bootstrap never read it: a disabled port is
	// still cabled and still enabled at boot, and intent's disabling reaches the node
	// through the artifact alone.
	//
	// Beside mgmt_only, with what intent says of the interface, before what the compiler
	// decided of it; the canonical encoding follows struct order, so the re-baseline
	// inserted one line per row and changed no other.
	Enabled *bool   `json:"enabled"`
	Port    *string `json:"port"`
	// NodeName is what the node's operating system calls the port, as the profile's rule
	// renders it. On every row from bundle "3": the node's own name for the
	// port, equal to Interface where the platform keeps production's name, and nil —
	// written as null — on a row with no port, where the node calls the interface
	// nothing at all because the twin gives it no port. A nil is never the empty string
	// in a message: it means "the node has no name for this", not "the name is blank".
	//
	// M6 wrote it only where it differed, so that a platform naming its ports as
	// production does emitted nothing new and its bundles kept their bytes; that
	// exception was written to expire with the next bundle_version bump, and this is it
	// (D-025).
	NodeName    *string     `json:"node_name"`
	Disposition Disposition `json:"disposition"`
}

// IsEnabled reports the row's intent admin state, nil being enabled, as
// ctm.Interface.IsEnabled reads an unset one.
func (r MappingRow) IsEnabled() bool { return r.Enabled == nil || *r.Enabled }

// Omission records something intent asked for that the twin does not represent.
// Omissions are informational, never rejections — but they are always recorded, which
// is the difference between an approximation and a lie (Constitution X).
type Omission struct {
	Rule   string `json:"rule"`
	Object string `json:"object"`
	Reason string `json:"reason"`
}

// Reasons given in the manifest. Written for an operator reading a report, not for a
// developer reading a stack trace.
const (
	reasonOOB        = "out-of-band network not modelled"
	reasonUnmappable = "no node port for production name"
	reasonExtraMgmt  = "one management connection per node"
)
