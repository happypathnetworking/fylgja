// Package psp loads and validates Platform Support Packages.
//
// A PSP is everything Fylgja needs to know about one network operating system,
// expressed as data. Adding a platform is a data change, never a code change
// (Constitution II) — so nothing in this package, or in the compiler that consumes it,
// may branch on a platform's identity.
package psp

// FormatVersion is the PSP format this build understands. 0.6 (M11) adds the required
// fidelity.link_change and gives mode: replace D-033's meaning; nothing of it enters a
// bundle.
const FormatVersion = "0.6"

// Acquisition says how an image is obtained, which determines what CI and lab hosts
// must have provisioned.
const (
	AcquisitionPublicRegistry = "public_registry"
	AcquisitionAccountGated   = "account_gated"
	AcquisitionLicensed       = "licensed"
	AcquisitionVrnetlabVM     = "vrnetlab_vm"
)

// DeviceClass distinguishes the intent domains and assertion classes that apply.
const (
	ClassRouter   = "router"
	ClassSwitch   = "switch"
	ClassFirewall = "firewall"
)

// ProductionForwarding records whether the real platform forwards in silicon or in
// software. Where production forwards in software the twin's data plane is a fair
// guide; where it forwards in hardware it is not (architecture §1).
const (
	ForwardingHardware = "hardware"
	ForwardingSoftware = "software"
)

// Readiness probes a package can declare. Only the gNMI ones are run at M2.
const (
	ProbeGNMIGet       = "gnmi_get"
	ProbeGNMISubscribe = "gnmi_subscribe"
)

// DefaultGNMIPort is the port a gNMI probe dials when its package names none.
const DefaultGNMIPort = 57400

// Delivery mechanisms a package can declare. DeliveryJSONRPC is implemented from M5 and
// DeliveryEAPI from M7; a package naming any other is refused at load as
// psp.config.delivery.unimplemented, never loaded and skipped at push time
// (Constitution II). The set of implemented deliveries is stated once, in
// consistency.go, and both the delivery rule and the push rule read it from there.
const (
	DeliveryJSONRPC = "json_rpc"
	DeliveryEAPI    = "eapi"
)

// Ways the bootstrap file reaches the node. The default is BootstrapViaStartupConfig,
// which a package states by omitting the field.
const (
	// BootstrapViaStartupConfig names the file in the topology and lets the lab tool
	// apply it at deploy, before the node is probed.
	BootstrapViaStartupConfig = "startup_config"
	// BootstrapViaPush sends the file's lines through the same request as the
	// artifact's, ahead of them, after the node has answered the readiness probe and
	// before the twin is reported ready. It is what a kind takes whose startup-config
	// is the whole configuration rather than a snippet merged over its default: naming
	// such a file in the topology would replace the node's management configuration,
	// and writing one that carried it would put a login in the bundle.
	BootstrapViaPush = "push"
)

// Modes a pushed artifact can be applied in. No default: guessing either way
// would be a false assertion about what the twin runs.
const (
	// ModeMerge applies the artifact over the bootstrap: a line the artifact sets
	// overrides bootstrap's, a line it does not set stands. A package on merge creates
	// but cannot step (step.package.merge).
	ModeMerge = "merge"
	// ModeReplace resets the node's candidate to the baseline containerlab left on it at
	// deploy, then sends the bundle's bootstrap and the artifact, obtains the device's diff
	// and commits, in one request with one atomic commit, per delivery (format 0.6, D-033).
	// So the node runs exactly baseline, bootstrap and artifact, whatever an earlier push
	// left on it.
	ModeReplace = "replace"
)

// How a delivery commits what it sent.
const (
	// CommitExplicit wraps the artifact's lines in a candidate and commits it.
	CommitExplicit = "explicit"
	// CommitImplicit sends the lines alone; each takes effect as it is accepted.
	CommitImplicit = "implicit"
)

// Identity names the platform and the intent domain it belongs to.
type Identity struct {
	ID          string   `yaml:"id" json:"id"`
	Vendor      string   `yaml:"vendor" json:"vendor"`
	NOS         string   `yaml:"nos" json:"nos"`
	Versions    []string `yaml:"versions,omitempty" json:"versions,omitempty"`
	DeviceClass string   `yaml:"device_class" json:"device_class"`
}

// Resources is the per-node budget used for scheduling. Per-platform, never global:
// the confirmed platform set spans an order of magnitude in memory. CheckHost sums
// MemoryMB over the bundle's nodes against the operator's host budget.
type Resources struct {
	CPU      float64 `yaml:"cpu" json:"cpu"`
	MemoryMB int     `yaml:"memory_mb" json:"memory_mb"`
}

// Image says which container image realises the platform, how to get it, and how long
// containerlab may take to start and to remove a node of it.
//
// DeployTimeoutS budgets DeployLab and DestroyTimeoutS budgets DestroyLab; each step's
// budget is the largest value among the bundle's platforms, since nodes start and stop
// concurrently. Like Resources and Readiness, they describe how this host runs the
// platform rather than the intent, so none of them reaches the manifest.
type Image struct {
	ClabKind        string    `yaml:"clab_kind" json:"clab_kind"`
	Ref             string    `yaml:"ref" json:"ref"`
	Acquisition     string    `yaml:"acquisition" json:"acquisition"`
	Resources       Resources `yaml:"resources" json:"resources"`
	DeployTimeoutS  int       `yaml:"deploy_timeout_s" json:"deploy_timeout_s"`
	DestroyTimeoutS int       `yaml:"destroy_timeout_s" json:"destroy_timeout_s"`
}

// Interfaces is the mapping profile (format 0.4): how the platform's production
// interface names become containerlab ports and the node's own port names, as data.
// Rules are an ordered slice, never a map: the first rule whose match
// fits a name decides it, so order is meaning.
type Interfaces struct {
	Rules []Rule `yaml:"rules" json:"rules"`
	// Mappings are what the conformance suite holds this package to.
	// Consumed by the suite alone; the compiler never reads them.
	Mappings []DeclaredMapping `yaml:"mappings" json:"mappings"`
}

// Rule is one named mapping rule of the profile.
//
// A data rule matches production names with Match, bounds what it captures with
// Ranges, and renders Port (containerlab's endpoint name) and NodeName (what the node's
// operating system calls the port) from the captured values. The placeholders Port
// leaves out are the rule's dropped placeholders; Lossy must say whether there are any.
// The management rule has only Name, Port and NodeName, and applies to a device's
// mgmt_only interface whatever that interface is called (D-003).
type Rule struct {
	Name string `yaml:"name" json:"name"`
	// Match is M1's pattern syntax: {name} captures one path segment. Absent on the
	// management rule.
	Match string `yaml:"match,omitempty" json:"match,omitempty"`
	// Ranges bound captured values, per placeholder, inclusive. A value under a range
	// that is not a decimal integer within it is out of range under this rule: matched,
	// never passed to a later rule. A placeholder with no range accepts any value.
	Ranges   map[string][2]int `yaml:"ranges,omitempty" json:"ranges,omitempty"`
	Port     string            `yaml:"port" json:"port"`
	NodeName string            `yaml:"node_name" json:"node_name"`
	// Lossy is a checked assertion, not a switch: it must equal "Port drops a
	// placeholder Match captures" (psp.patterns.placeholders). The schema requires it on
	// every data rule, so an omission is psp.schema before the decoder sees it.
	Lossy bool `yaml:"lossy,omitempty" json:"lossy,omitempty"`
	// Breakout marks the rule's matches as breakout children of a parent.
	Breakout *Breakout `yaml:"breakout,omitempty" json:"breakout,omitempty"`
	// Management marks the one management rule (psp.management.rule).
	Management bool `yaml:"management,omitempty" json:"management,omitempty"`
}

// Breakout names a breakout child's parent. Whether children spread onto their own
// ports or collapse onto the parent's is the rule's Port pattern's business, not a flag.
type Breakout struct {
	// Parent renders the parent's production name from the child's captured values.
	Parent string `yaml:"parent" json:"parent"`
}

// DeclaredMapping is one expectation the conformance suite's pure half checks the
// profile against: either a mapping (Rule, Port, NodeName, Lossy) or an
// unmappable outcome (Unmappable, with Rule for out_of_range).
type DeclaredMapping struct {
	Production string `yaml:"production" json:"production"`
	Rule       string `yaml:"rule,omitempty" json:"rule,omitempty"`
	Port       string `yaml:"port,omitempty" json:"port,omitempty"`
	NodeName   string `yaml:"node_name,omitempty" json:"node_name,omitempty"`
	Lossy      bool   `yaml:"lossy,omitempty" json:"lossy,omitempty"`
	Unmappable string `yaml:"unmappable,omitempty" json:"unmappable,omitempty"`
}

// Values of DeclaredMapping.Unmappable.
const (
	// UnmappableNoRule: no rule of the profile matches the name.
	UnmappableNoRule = "no_rule"
	// UnmappableOutOfRange: the named rule matches, with a value outside its range.
	UnmappableOutOfRange = "out_of_range"
)

// Conformance is how the conformance suite's boot half reads a booted node, over the
// readiness probe's transport, port, encoding and login.
// Optional: nil when the package declares none, and then the boot half fails naming
// the package and the field rather than skipping. Never reaches a bundle.
type Conformance struct {
	// HostName is the path of the leaf carrying the node's host name.
	HostName string `yaml:"host_name" json:"host_name"`
	// Version is the path of the leaf carrying the software version, matched against
	// Platform.Versions.
	Version string     `yaml:"version" json:"version"`
	Port    PortChecks `yaml:"port" json:"port"`
}

// PortChecks are read for each cabled port, with {node_name} rendering the node's own
// name for it.
type PortChecks struct {
	Enabled     ValueAt    `yaml:"enabled" json:"enabled"`
	Discovering ValueAt    `yaml:"discovering" json:"discovering"`
	Neighbor    NeighborAt `yaml:"neighbor" json:"neighbor"`
}

// ValueAt is a leaf and the value it must read.
type ValueAt struct {
	Path  string `yaml:"path" json:"path"`
	Value string `yaml:"value" json:"value"`
	// Absent is the value the node means by reporting nothing at Path. A model that
	// omits a container's defaults reports no value for a leaf that holds its default,
	// so a read that comes back empty is an assertion, not a gap. A package that leaves
	// this empty keeps the earlier behaviour: nothing read fails nothing.
	Absent string `yaml:"absent,omitempty" json:"absent,omitempty"`
}

// NeighborAt is a cabled port's neighbour list and the two leaves of one entry that
// name the far node and the far port.
type NeighborAt struct {
	// Path is the neighbour list, absolute, with {node_name} rendering the node's own
	// name for the port.
	Path string `yaml:"path" json:"path"`
	// SystemName and PortID are "/"-separated paths relative to one neighbour entry,
	// not absolute ones: where one model puts the far node's name directly on the entry
	// and another puts it under a state container, the package says which by writing
	// "system-name" or "state/system-name". A single element is the one-element path,
	// so a package written before this was stated means what it always meant and does
	// not change.
	SystemName string `yaml:"system_name" json:"system_name"`
	PortID     string `yaml:"port_id" json:"port_id"`
}

// Config describes how configuration reaches a node, and the bootstrap that makes it
// reachable. Bootstrap is platform data: it carries no intent (Constitution IV).
//
// From format 0.3 the block also says which rendered artifact is this platform's
// configuration and how it is pushed to a booted node. Delivery and
// Commit, carried since 0.1 and consumed by nothing, are read from 0.3 by the push.
type Config struct {
	StartupFormat string   `yaml:"startup_format" json:"startup_format"`
	Delivery      string   `yaml:"delivery" json:"delivery"`
	Commit        string   `yaml:"commit" json:"commit"`
	Bootstrap     []string `yaml:"bootstrap" json:"bootstrap"`

	// ArtifactName is the artifact definition's artifact_name whose artifact is a
	// device's configuration on this platform (D-028). The read selects, per device,
	// the one artifact of this name. It must differ from StartupFormat, so that the
	// bundle's configs/<node>.<artifact_name> cannot collide with the bootstrap's
	// configs/<node>.<startup_format> (psp.config.artifact_name).
	ArtifactName string `yaml:"artifact_name" json:"artifact_name"`
	// ArtifactContentTypes are the content types the read accepts for this platform;
	// an artifact of any other type is refused as artifact.content_type.unsupported.
	// Text only: the CTM carries content as UTF-8 text (psp.config.content_type).
	ArtifactContentTypes []string `yaml:"artifact_content_types" json:"artifact_content_types"`
	// Mode says what the pushed artifact does to what is already on the node: merge
	// applies it over the bootstrap, replace resets the node to its baseline first and
	// sends the bootstrap and the artifact over it (D-033). Required, with no default,
	// because guessing either way would be a false assertion about what the twin runs.
	Mode string `yaml:"mode" json:"mode"`
	// PushTimeoutS is how long one node may take to accept its artifact, from the push
	// activity's start to the node's commit. The push step's budget is the largest value
	// among the bundle's platforms plus the mechanism's margin: per-platform, never a
	// shared constant (Constitution II).
	PushTimeoutS int `yaml:"push_timeout_s" json:"push_timeout_s"`
	// Push is how the node is reached for delivery. Required when Delivery is one of the
	// implemented mechanisms (psp.config.push.missing); a mechanism that needs no
	// address leaves it unset.
	Push *PushConfig `yaml:"push,omitempty" json:"push,omitempty"`
	// CommentPrefix is the marker that begins a comment line in this platform's
	// startup-config syntax. The compiler writes the bundle's bootstrap file with one
	// generated header line under it, and under BootstrapViaPush that line is sent to
	// the node as a command like every other line of the file — so a marker the node
	// does not read as a comment is refused, and with an atomic commit nothing lands at
	// all. Empty means DefaultCommentPrefix, which is what every package written before
	// this field meant, so no package, bundle or bundle_id moves for it.
	CommentPrefix string `yaml:"comment_prefix,omitempty" json:"comment_prefix,omitempty"`
	// BootstrapVia says how a deploy delivers the bootstrap file. Empty means
	// BootstrapViaStartupConfig, which is what every package written before this field
	// meant. Either way the file is written to configs/<node>.<startup_format> and named
	// in the manifest; what changes is who applies it. Under ModeReplace the push sends
	// the bootstrap after the reset whatever this says (format 0.6), because
	// containerlab's reconcile never applies a changed startup snippet to a running node.
	BootstrapVia string `yaml:"bootstrap_via,omitempty" json:"bootstrap_via,omitempty"`
}

// DefaultCommentPrefix is what a package that names no comment marker means: the marker
// M1 through M6 wrote unconditionally into every bootstrap file.
const DefaultCommentPrefix = "#"

// CommentPrefixOrDefault returns the marker the bootstrap file's generated header is
// written with: the package's own, else the format's default.
func (c Config) CommentPrefixOrDefault() string {
	if c.CommentPrefix != "" {
		return c.CommentPrefix
	}
	return DefaultCommentPrefix
}

// PushConfig is the address and login the push uses to reach a booted node. The login
// holds variable names, never values (Constitution X).
type PushConfig struct {
	// Scheme is http or https; https accepts the node's boot-time certificate
	// unverified, as the readiness probe accepts it.
	Scheme string `yaml:"scheme" json:"scheme"`
	Port   int    `yaml:"port" json:"port"`
	// Login may name the same variables as Readiness.Login: one node, one account.
	Login Login `yaml:"login" json:"login"`
}

// State describes how operational state is collected. Not consumed at
// M1;
// the state collector is later work.
type State struct {
	Transport          string `yaml:"transport" json:"transport"`
	OpenConfigCoverage string `yaml:"openconfig_coverage" json:"openconfig_coverage"`
	NativeFallback     string `yaml:"native_fallback,omitempty" json:"native_fallback,omitempty"`
	CLITemplates       string `yaml:"cli_templates,omitempty" json:"cli_templates,omitempty"`
}

// Readiness says how to tell a node is ready: which probe, where, in what encoding, as
// whom, and within how long. Per-platform, never a shared timeout.
//
// CheckHost checks that the Login variables are set; AwaitReadiness runs the probe
// against each node under that node's TimeoutS. Ready means the management plane
// answers an authenticated request, not that routing has converged.
// None of these fields reaches the manifest.
type Readiness struct {
	Probe    string `yaml:"probe" json:"probe"`
	Path     string `yaml:"path,omitempty" json:"path,omitempty"`
	Encoding string `yaml:"encoding,omitempty" json:"encoding,omitempty"`
	Port     int    `yaml:"port,omitempty" json:"port,omitempty"`
	TimeoutS int    `yaml:"timeout_s" json:"timeout_s"`
	Login    Login  `yaml:"login" json:"login"`

	// TLS says whether the probe (and the conformance suite's reader, which shares the
	// dial) speaks TLS to the node. A package that omits it leaves this nil, which
	// means TLS: that is what every package written before this field meant, and the
	// pointer is what keeps an absent key from reading as false. A non-nil false dials
	// plaintext gRPC, which is what a node's default gRPC transport serves when no SSL
	// profile is attached to it.
	TLS *bool `yaml:"tls,omitempty" json:"tls,omitempty"`

	// AwaitPushTransport says the node is ready only once the endpoint config.push names
	// also accepts a connection, not merely once the probe has answered. Absent means
	// false, which is what every package written before this field meant.
	//
	// It exists because a platform can answer its probe while the transport its
	// configuration must arrive on is still shut: one measured platform bound its probe
	// eleven seconds after its deploy returned and its push transport a second or two
	// later, and a push that began just after the probe succeeded was refused three times
	// over nine seconds. A package whose push transport is up when its
	// probe answers leaves this absent (D-029).
	AwaitPushTransport bool `yaml:"await_push_transport,omitempty" json:"await_push_transport,omitempty"`
}

// Login names the environment variables that carry a login's username and password on
// the worker: the readiness probe's, and from format 0.3 the push's, which may be the
// same two variables. Names only: a value never belongs in a package, a bundle, a
// finding or a log line (Constitution X).
type Login struct {
	UsernameEnv string `yaml:"username_env" json:"username_env"`
	PasswordEnv string `yaml:"password_env" json:"password_env"`
}

// PortOrDefault returns the port the probe dials: the package's own, else its
// transport's default. Only gNMI has a default; any other probe naming no port gets 0.
func (r Readiness) PortOrDefault() int {
	if r.Port > 0 {
		return r.Port
	}
	switch r.Probe {
	case ProbeGNMIGet, ProbeGNMISubscribe:
		return DefaultGNMIPort
	}
	return 0
}

// What containerlab's reconcile does to a node of a kind when a link of its is added or
// removed (Fidelity.LinkChange, format 0.6).
const (
	// LinkChangeRestart: the node is restarted in place and returns on its startup
	// configuration, its push lost.
	LinkChangeRestart = "restart"
	// LinkChangeLive: the node is re-cabled with no lifecycle action and keeps its push.
	LinkChangeLive = "live"
)

// Fidelity declares what the container cannot reproduce, feeding the manifest that is
// Fylgja's only trust signal (Constitution VI).
type Fidelity struct {
	ProductionForwarding string   `yaml:"production_forwarding" json:"production_forwarding"`
	Approximations       []string `yaml:"approximations" json:"approximations"`
	// LinkChange is what containerlab's reconcile does to a node of this kind when a link
	// of its is added or removed: LinkChangeRestart or LinkChangeLive. Required from
	// format 0.6. It is fidelity: asserted by the package, measured by
	// containerlab's dry-run plan at every step, both recorded, and a difference warned
	// as step.restart.undeclared. The step acts on the plan, never on this.
	// Re-verified on a containerlab or image upgrade. Never reaches a bundle (D-033's
	// second note), so no bundle_id moves for it.
	LinkChange string `yaml:"link_change" json:"link_change"`
}

// PSP is one platform's support package.
type PSP struct {
	PSPVersion   string     `yaml:"psp_version" json:"psp_version"`
	Platform     Identity   `yaml:"platform" json:"platform"`
	Image        Image      `yaml:"image" json:"image"`
	Interfaces   Interfaces `yaml:"interfaces" json:"interfaces"`
	Config       Config     `yaml:"config" json:"config"`
	State        State      `yaml:"state" json:"state"`
	Readiness    Readiness  `yaml:"readiness" json:"readiness"`
	Capabilities []string   `yaml:"capabilities" json:"capabilities"`
	Fidelity     Fidelity   `yaml:"fidelity" json:"fidelity"`
	// Conformance is new in 0.4 and optional.
	Conformance *Conformance `yaml:"conformance,omitempty" json:"conformance,omitempty"`

	// Origin records where this package was loaded from: "embedded" or "override".
	// Recorded in the bundle manifest so a twin says which support it was built with.
	Origin string `yaml:"-" json:"-"`
	// Path is the file the package came from, used for finding locations.
	Path string `yaml:"-" json:"-"`
}

// Source values for Origin.
const (
	OriginEmbedded = "embedded"
	OriginOverride = "override"
)
