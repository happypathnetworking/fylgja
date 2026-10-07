package step

// Lifecycle is what containerlab's plan does to nodes, by name: the nodes it restarts in
// place for a link change, recreates (an image
// or kind that drifted), creates, and removes. A node re-cabled live is in none of them.
type Lifecycle struct {
	Restarted, Recreated, Created, Removed []string
}

// NodePush is one node a step pushes and why: its reasons among PushArtifact,
// PushBootstrap, PushRestarted, PushRecreated and PushCreated, sorted, each once. It crosses
// the task queue in the step run's input, under contracts/step.schema.json's keys.
type NodePush struct {
	Node    string   `json:"node"`
	Reasons []string `json:"reasons"`
}

// Why a step pushes a node (contracts/step.schema.json, push_plan). The first two are the
// node's content changing between the bundles; the last three are containerlab's
// lifecycle, after which a node runs its baseline until a push lands.
const (
	PushArtifact  = "artifact"  // its artifact's checksum differs, or it comes with the node
	PushBootstrap = "bootstrap" // its bootstrap file's bytes differ
	PushRestarted = "restarted"
	PushRecreated = "recreated"
	PushCreated   = "created"
)

// PushPlan is every node the step pushes, sorted by node: each whose artifact or bootstrap
// differs between the bundles, and each containerlab's plan restarts, recreates or creates.
// A removed node is never in it, and a node with no reason is not pushed or otherwise
// touched. A node the step adds is created only when the lifecycle creates it; one it does
// not is Unapplied's to name.
func PushPlan(s Step, l Lifecycle) []NodePush {
	removed := setOf(s.NodesRemoved, l.Removed)
	reasons := map[string]map[string]bool{}
	add := func(node, reason string) {
		if removed[node] {
			return
		}
		if reasons[node] == nil {
			reasons[node] = map[string]bool{}
		}
		reasons[node][reason] = true
	}
	for _, a := range s.ArtifactsChanged {
		add(a.Node, PushArtifact)
	}
	for _, a := range s.ArtifactsAdded {
		add(a.Node, PushArtifact)
	}
	for _, c := range s.NodesChanged {
		for _, r := range c.Reasons {
			if r == ReasonBootstrap {
				add(c.Node, PushBootstrap)
			}
		}
	}
	for reason, nodes := range map[string][]string{PushRestarted: l.Restarted, PushRecreated: l.Recreated, PushCreated: l.Created} {
		for _, n := range nodes {
			add(n, reason)
		}
	}

	plan := make([]NodePush, 0, len(reasons))
	for _, node := range sortedKeys(reasons) {
		plan = append(plan, NodePush{Node: node, Reasons: sortedKeys(reasons[node])})
	}
	return plan
}

// Unapplied is every node the step changes in a way containerlab's reconcile would leave in
// place: one changed in image, platform or psp that the plan does not recreate,
// and one the step adds that the plan does not create. A kind change is always a recreate,
// so in practice this names a psp change under the same image and kind. Sorted,
// each once.
func Unapplied(s Step, l Lifecycle) []string {
	recreated, created := setOf(l.Recreated), setOf(l.Created)
	out := map[string]bool{}
	for _, c := range s.NodesChanged {
		for _, r := range c.Reasons {
			if (r == ReasonImage || r == ReasonPlatform || r == ReasonPSP) && !recreated[c.Node] {
				out[c.Node] = true
			}
		}
	}
	for _, n := range s.NodesAdded {
		if !created[n] {
			out[n] = true
		}
	}
	return sortedKeys(out)
}

// setOf is every name in the lists, as a set.
func setOf(lists ...[]string) map[string]bool {
	set := map[string]bool{}
	for _, l := range lists {
		for _, n := range l {
			set[n] = true
		}
	}
	return set
}
