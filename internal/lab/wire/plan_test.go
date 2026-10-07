package wire

import (
	"reflect"
	"testing"
)

// Nodes derives what containerlab reports doing to each node its plan touches, from plans
// of the shapes containerlab 0.79.0 printed, and two synthetic ones that pin the rule's order
// and its defence.
func TestReconcilePlanNodes(t *testing.T) {
	for _, c := range []struct {
		label string
		plan  ReconcilePlan
		want  []PlanNode
	}{
		{"nothing to apply", ReconcilePlan{}, []PlanNode{}},
		{
			// A link added between a cEOS and an SR Linux node: the cEOS
			// end restarts, and the SR Linux end, in no list, is re-cabled live.
			"a link added",
			ReconcilePlan{
				Restarted:  []string{"e1"},
				LinksAdded: []string{"e1:eth2 -- s1:e1-2"},
				Reasons:    map[string]string{"e1": "added link"},
			},
			[]PlanNode{{Node: "e1", Reported: ReportedRestart, Reason: "added link"}, {Node: "s1", Reported: ReportedLive}},
		},
		{
			// A kind change is a recreate, and its renamed endpoint makes the
			// far end restart under its own kind.
			"a kind change",
			ReconcilePlan{
				Recreated:        []string{"s1"},
				Restarted:        []string{"e1"},
				LinksAdded:       []string{"e1:eth1 -- s1:eth1"},
				EndpointsDeleted: []string{"s1:e1-1"},
				Reasons:          map[string]string{"s1": "config drift: Kind, Image", "e1": "added link"},
			},
			[]PlanNode{
				{Node: "e1", Reported: ReportedRestart, Reason: "added link"},
				{Node: "s1", Reported: ReportedRecreate, Reason: "config drift: Kind, Image"},
			},
		},
		{
			// Synthetic, the rule's order should containerlab ever name a node in both
			// lists: a recreate is the larger change, and the one the record must name.
			"recreate outranks restart",
			ReconcilePlan{Recreated: []string{"s1"}, Restarted: []string{"s1"}},
			[]PlanNode{{Node: "s1", Reported: ReportedRecreate}},
		},
		{
			// A node added with a link to a running
			// node, which is re-cabled live.
			"a node added",
			ReconcilePlan{Added: []string{"s2"}, LinksAdded: []string{"s1:e1-3 -- s2:e1-1"}},
			[]PlanNode{{Node: "s1", Reported: ReportedLive}, {Node: "s2", Reported: ReportedCreate}},
		},
		{
			// A node removed is gone, not touched; its
			// far end loses an endpoint and is re-cabled live.
			"a node removed",
			ReconcilePlan{Deleted: []string{"e1"}, EndpointsDeleted: []string{"s1:e1-1"}},
			[]PlanNode{{Node: "s1", Reported: ReportedLive}},
		},
		{
			// Synthetic, the rule's defence: should containerlab name a removed node's own
			// endpoint, the node is still gone, not re-cabled.
			"a removed node's own endpoint",
			ReconcilePlan{Deleted: []string{"e1"}, EndpointsDeleted: []string{"e1:eth1", "s1:e1-1"}},
			[]PlanNode{{Node: "s1", Reported: ReportedLive}},
		},
	} {
		t.Run(c.label, func(t *testing.T) {
			if got := c.plan.Nodes(); !reflect.DeepEqual(got, c.want) {
				t.Errorf("Nodes() = %+v, want %+v", got, c.want)
			}
		})
	}
}

// A plan is empty only when every list is: a step whose plan is empty skips the reconcile.
func TestReconcilePlanEmpty(t *testing.T) {
	if !(ReconcilePlan{Reasons: map[string]string{}}).Empty() {
		t.Error("a plan with no lists is not empty")
	}
	for _, p := range []ReconcilePlan{
		{Added: []string{"s2"}}, {Deleted: []string{"s2"}}, {Recreated: []string{"s1"}},
		{Restarted: []string{"e1"}}, {LinksAdded: []string{"e1:eth3 -- s1:e1-3"}},
		{EndpointsDeleted: []string{"s1:e1-1"}},
	} {
		if p.Empty() {
			t.Errorf("%+v is empty", p)
		}
	}
}
