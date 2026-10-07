package findings

import "encoding/json"

// VerifyBlock is twin verify's block (M12):
// the intent conformance report. The twin as its record names it; every assertion derived
// from the staged bundle's manifest with its outcome, by node and by link; the record's
// claims, labelled the record's; every skipped assertion with its reason; the counts by
// kind; the runs in flight as twin show reads them; and, with --wait, the wait. Every
// nullable key is written. No configuration line, artifact or bootstrap content, device
// diff, token or login anywhere: what is read is host names, admin states
// and neighbour names. Advisory: no Fylgja operation reads it.
type VerifyBlock struct {
	Twin       VerifyTwin    `json:"twin"`
	ReadAt     string        `json:"read_at"` // RFC 3339 UTC: the start of the read the block reports
	Nodes      []VerifyNode  `json:"nodes"`
	Links      []VerifyLink  `json:"links"`
	Record     []VerifyClaim `json:"record"`
	Skipped    []VerifySkip  `json:"skipped"`
	ExtraNodes []string      `json:"extra_nodes"`
	Counts     VerifyCounts  `json:"counts"`
	InFlight   []ShowRun     `json:"in_flight"`
	Service    string        `json:"service"` // ShowServiceOK or ShowServiceUnreachable
	Wait       *VerifyWait   `json:"wait,omitempty"`
}

// MarshalJSON writes every empty list as [] rather than null: the contract requires each.
func (b VerifyBlock) MarshalJSON() ([]byte, error) {
	type plain VerifyBlock
	b.Nodes = orEmpty(b.Nodes)
	b.Links = orEmpty(b.Links)
	b.Record = orEmpty(b.Record)
	b.Skipped = orEmpty(b.Skipped)
	b.ExtraNodes = orEmpty(b.ExtraNodes)
	b.InFlight = orEmpty(b.InFlight)
	return json.Marshal(plain(b))
}

func orEmpty[T any](l []T) []T {
	if l == nil {
		return []T{}
	}
	return l
}

// VerifyTwin is the twin as its record names it, and the staged bundle the assertions were
// derived from.
type VerifyTwin struct {
	BundleID string          `json:"bundle_id"` // the staged bundle's
	Waypoint *ShowWaypoint   `json:"waypoint"`
	State    string          `json:"state"` // ready or diverged; a record before 4 reads ready
	Source   string          `json:"source"`
	Nodes    int             `json:"nodes"` // the record's node count
	Diverged *VerifyDiverged `json:"diverged,omitempty"`
}

// VerifyDiverged is where a diverged twin's step was going and where it stopped.
type VerifyDiverged struct {
	Towards VerifyTowards `json:"towards"`
	Run     ShowRef       `json:"run"`
	Phase   string        `json:"phase"`
}

// VerifyTowards is the waypoint and bundle a diverged twin's step was going to.
type VerifyTowards struct {
	Waypoint *ShowWaypoint `json:"waypoint"`
	BundleID string        `json:"bundle_id"`
}

// VerifyNode is one node the staged manifest names, read or not.
type VerifyNode struct {
	Node     string          `json:"node"`
	PSP      string          `json:"psp"`
	Addr     *string         `json:"addr"` // <mgmt ipv4>:<readiness port> as dialled; nil when there was none
	Read     bool            `json:"read"` // false when any assertion of the node is unread
	Error    string          `json:"error,omitempty"`
	HostName VerifyAssertion `json:"host_name"`
	Ports    []VerifyPort    `json:"ports"`
}

// MarshalJSON writes a node with no cabled port as ports [].
func (n VerifyNode) MarshalJSON() ([]byte, error) {
	type plain VerifyNode
	n.Ports = orEmpty(n.Ports)
	return json.Marshal(plain(n))
}

// VerifyAssertion is one assertion: the path read, the value expected and what came of it.
// Read is nil when nothing was read or the read failed.
type VerifyAssertion struct {
	Path     string  `json:"path"`
	Expected string  `json:"expected"`
	Outcome  string  `json:"outcome"`
	Read     *string `json:"read"`
	Error    string  `json:"error,omitempty"`
	Reason   string  `json:"reason,omitempty"`
}

// VerifyPort is one cabled port's state, by its production name and the node's own name.
type VerifyPort struct {
	Port     string  `json:"port"`
	NodeName string  `json:"node_name"`
	Path     string  `json:"path"`
	Expected string  `json:"expected"`
	Outcome  string  `json:"outcome"`
	Read     *string `json:"read"`
	Error    string  `json:"error,omitempty"`
	Reason   string  `json:"reason,omitempty"`
}

// VerifyLink is one link of the staged manifest and what each end saw.
type VerifyLink struct {
	ID string    `json:"id"`
	A  VerifyEnd `json:"a"`
	B  VerifyEnd `json:"b"`
}

// VerifyEnd is one end of a link: which far node and far port it must see, and every
// neighbour entry it read.
type VerifyEnd struct {
	Node     string           `json:"node"`
	Port     string           `json:"port"` // the production name
	NodeName string           `json:"node_name"`
	Path     string           `json:"path"`
	Expected VerifyNodePort   `json:"expected"`
	Outcome  string           `json:"outcome"`
	Read     []VerifyNodePort `json:"read"`
	Error    string           `json:"error,omitempty"`
	Reason   string           `json:"reason,omitempty"`
}

// MarshalJSON writes an end that read nothing as read [].
func (e VerifyEnd) MarshalJSON() ([]byte, error) {
	type plain VerifyEnd
	e.Read = orEmpty(e.Read)
	return json.Marshal(plain(e))
}

// VerifyNodePort is a node and a port under that node's own name.
type VerifyNodePort struct {
	Node string `json:"node"`
	Port string `json:"port"`
}

// VerifyClaim is the record's claim of what one node holds against the staged bundle:
// recorded, never read. Holds is nil where the record writes null.
type VerifyClaim struct {
	Node    string  `json:"node"`
	Holds   *string `json:"holds"`
	Staged  string  `json:"staged"`
	Outcome string  `json:"outcome"`
}

// VerifySkip is one skipped assertion: a port intent disables (Link nil), or one end of
// the link on such a port.
type VerifySkip struct {
	Node   string  `json:"node"`
	Port   string  `json:"port"`
	Reason string  `json:"reason"`
	Link   *string `json:"link"`
}

// VerifyCounts are the assertions and claims counted by kind; Failed counts absent too.
type VerifyCounts struct {
	HostName    VerifyCount `json:"host_name"`
	PortEnabled VerifyCount `json:"port_enabled"`
	Neighbor    VerifyCount `json:"neighbor"`
	Record      VerifyCount `json:"record"`
}

// VerifyCount is one kind's count. Skipped is written for the two port kinds alone, and
// Unread for every kind read from a node; a claim is neither.
type VerifyCount struct {
	Held    int  `json:"held"`
	Failed  int  `json:"failed"`
	Skipped *int `json:"skipped,omitempty"`
	Unread  *int `json:"unread,omitempty"`
}

// VerifyWait is twin verify --wait's: the budget, the reads made, how the wait ended and
// after how many seconds from the command's first read.
type VerifyWait struct {
	BudgetS int     `json:"budget_s"`
	Reads   int     `json:"reads"`
	Outcome string  `json:"outcome"`
	AfterS  float64 `json:"after_s"`
}
