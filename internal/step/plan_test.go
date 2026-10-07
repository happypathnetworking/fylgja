package step

import (
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
)

// mixedLinkAdded is the mixed golden after case 8's change: a link
// e1:Ethernet3 — s1:ethernet-1/3, so s1 gains a mapping row and a bootstrap line, and both
// e1's and s1's artifacts move. e2 is untouched.
func mixedLinkAdded(t *testing.T, a Bundle) Bundle {
	return edited(t, a, idB, func(m *compiler.Manifest, files map[string][]byte) {
		for i := range m.Nodes {
			switch m.Nodes[i].Name {
			case "e1":
				m.Nodes[i].Artifact.Checksum = "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"
			case "s1":
				m.Nodes[i].Artifact.Checksum = "7a9b03de7a9b03de7a9b03de7a9b03de"
			}
		}
		files["configs/s1.cli"] = append(files["configs/s1.cli"], "set / interface ethernet-1/3 admin-state enable\n"...)
		m.Mapping = append(m.Mapping,
			compiler.MappingRow{Device: "e1", Interface: "Ethernet3", Iftype: "physical", Port: strPtr("eth3"),
				NodeName: strPtr("Ethernet3"), Disposition: compiler.DispCabled},
			compiler.MappingRow{Device: "s1", Interface: "ethernet-1/3", Iftype: "physical", Port: strPtr("e1-3"),
				NodeName: strPtr("ethernet-1/3"), Disposition: compiler.DispCabled})
		m.Links = append(m.Links, compiler.CabledLink{ID: "e1:Ethernet3|s1:ethernet-1/3",
			A: compiler.NodePort{Node: "e1", Port: "eth3"}, B: compiler.NodePort{Node: "s1", Port: "e1-3"}})
	})
}

func mustDiff(t *testing.T, a, b Bundle) Step {
	t.Helper()
	s, err := Diff(a, b)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// The push plan is every node whose content changed or that containerlab's lifecycle
// touches, each with its reasons sorted; the unapplied list is every change the reconcile
// would leave in place.
func TestPushPlanAndUnapplied(t *testing.T) {
	mixed := golden(t, "mixed", idA)
	three := golden(t, "three-node", idA)
	lossy := golden(t, "lossy", idA)
	first := func(b Bundle) string { return manifestOf(t, b).Nodes[0].Name }

	cases := []struct {
		name      string
		step      Step
		lifecycle Lifecycle
		plan      []NodePush
		unapplied []string
	}{
		{
			// Case 8's step: containerlab restarts e1 for the link and re-cables s1 live.
			name:      "the mixed golden with a link added",
			step:      mustDiff(t, mixed, mixedLinkAdded(t, mixed)),
			lifecycle: Lifecycle{Restarted: []string{"e1"}},
			plan: []NodePush{{Node: "e1", Reasons: []string{PushArtifact, PushRestarted}},
				{Node: "s1", Reasons: []string{PushArtifact, PushBootstrap}}},
		},
		{
			// The step back: the link's endpoint is deleted, e1 restarted again.
			name:      "the mixed golden with the link removed again",
			step:      mustDiff(t, mixedLinkAdded(t, mixed), mixed),
			lifecycle: Lifecycle{Restarted: []string{"e1"}},
			plan: []NodePush{{Node: "e1", Reasons: []string{PushArtifact, PushRestarted}},
				{Node: "s1", Reasons: []string{PushArtifact, PushBootstrap}}},
		},
		{
			name: "nothing differs and nothing is touched",
			step: mustDiff(t, three, edited(t, three, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				m.Provenance.At = "2026-09-28T16:04:58.989214+00:00"
			})),
			plan: []NodePush{},
		},
		{
			name: "a node restarted with nothing of its own changed",
			step: mustDiff(t, three, edited(t, three, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				m.Links = m.Links[1:]
			})),
			lifecycle: Lifecycle{Restarted: []string{"n2"}},
			plan:      []NodePush{{Node: "n2", Reasons: []string{PushRestarted}}},
		},
		{
			name: "an image change recreated",
			step: mustDiff(t, lossy, edited(t, lossy, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				m.Nodes[0].Image = "registry.example/other:1"
			})),
			lifecycle: Lifecycle{Recreated: []string{first(lossy)}},
			plan:      []NodePush{{Node: first(lossy), Reasons: []string{PushRecreated}}},
		},
		{
			name: "an image change the plan does not recreate",
			step: mustDiff(t, lossy, edited(t, lossy, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				m.Nodes[0].Image = "registry.example/other:1"
			})),
			plan:      []NodePush{},
			unapplied: []string{first(lossy)},
		},
		{
			name: "a platform change recreated, with its artifact and bootstrap",
			step: mustDiff(t, mixed, edited(t, mixed, idB, func(m *compiler.Manifest, files map[string][]byte) {
				m.Nodes[0].Platform = "srlinux"
				m.Nodes[0].Artifact.Checksum = "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"
				files[m.Nodes[0].Bootstrap.File] = append(files[m.Nodes[0].Bootstrap.File], "another line\n"...)
			})),
			lifecycle: Lifecycle{Recreated: []string{"e1"}, Restarted: []string{"e2"}},
			plan: []NodePush{{Node: "e1", Reasons: []string{PushArtifact, PushBootstrap, PushRecreated}},
				{Node: "e2", Reasons: []string{PushRestarted}}},
		},
		{
			// In practice the rule fires for a package change under the same image
			// and kind, which containerlab sees no drift in.
			name: "a package change under the same image",
			step: mustDiff(t, mixed, edited(t, mixed, idB, func(m *compiler.Manifest, _ map[string][]byte) {
				m.Nodes[2].PSP.ID = "nokia_srlinux_next"
			})),
			plan:      []NodePush{},
			unapplied: []string{"s1"},
		},
		{
			name:      "a node added and created",
			step:      mustDiff(t, three, addFourthNode(t, three)),
			lifecycle: Lifecycle{Created: []string{"n4"}},
			plan: []NodePush{{Node: "n1", Reasons: []string{PushArtifact, PushBootstrap}},
				{Node: "n4", Reasons: []string{PushArtifact, PushCreated}}},
		},
		{
			name: "a node added the plan does not create",
			step: mustDiff(t, three, addFourthNode(t, three)),
			plan: []NodePush{{Node: "n1", Reasons: []string{PushArtifact, PushBootstrap}},
				{Node: "n4", Reasons: []string{PushArtifact}}},
			unapplied: []string{"n4"},
		},
		{
			name:      "a node removed is never pushed",
			step:      mustDiff(t, addFourthNode(t, three), three),
			lifecycle: Lifecycle{Removed: []string{"n4"}, Restarted: []string{"n4"}},
			plan:      []NodePush{{Node: "n1", Reasons: []string{PushArtifact, PushBootstrap}}},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := PushPlan(c.step, c.lifecycle); !reflect.DeepEqual(got, c.plan) {
				t.Errorf("PushPlan:\n got %+v\nwant %+v", got, c.plan)
			}
			if got := Unapplied(c.step, c.lifecycle); !reflect.DeepEqual(got, c.unapplied) && (len(got) != 0 || len(c.unapplied) != 0) {
				t.Errorf("Unapplied: got %v, want %v", got, c.unapplied)
			}
		})
	}
}
