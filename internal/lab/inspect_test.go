package lab

import (
	"context"
	"os"
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// InspectTwin carries what InspectHost reads, field for field, and the phrase Describe
// gives the same inspection, verbatim, for each of M3's shapes. It only reads.
func TestInspectTwin(t *testing.T) {
	observed := "2026-09-16T13:59:30.000000Z"
	inspecting := func(t *testing.T, recording string) (*Activities, *fakeRunner) {
		f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, recording)}}}}
		return testActivities(t, f), f
	}
	// report runs InspectTwin and InspectHost over the same host and checks the one against
	// the other, then that nothing but clab inspect ran and the state root is as it was.
	report := func(t *testing.T, a *Activities, f *fakeRunner) wire.HostReport {
		t.Helper()
		before := tree(t, a.Paths.Root)
		got, err := a.InspectTwin(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		state, err := a.InspectHost(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if got.Phrase != state.Describe() {
			t.Errorf("phrase %q, want Describe()'s %q", got.Phrase, state.Describe())
		}
		want := wire.HostReport{LabPresent: state.Lab.Present, Nodes: state.Lab.Nodes, TopoPaths: state.Lab.TopoPaths,
			TwinDirPresent: state.TwinDirPresent, Twin: state.Twin, TwinReadError: state.TwinReadError, Phrase: state.Describe()}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("report %+v\nwant %+v", got, want)
		}
		if after := tree(t, a.Paths.Root); !reflect.DeepEqual(before, after) {
			t.Errorf("the state root changed:\nbefore %v\nafter  %v", before, after)
		}
		onlyInspected(t, f)
		return got
	}

	t.Run("nothing present", func(t *testing.T) {
		a, f := inspecting(t, "inspect-empty.json")
		got := report(t, a, f)
		if got.Phrase != "" || got.Twin != nil || got.LabPresent || got.TwinDirPresent {
			t.Errorf("report %+v, want nothing present and no phrase", got)
		}
	})

	t.Run("a readable twin.json", func(t *testing.T) {
		a, f := inspecting(t, "inspect-three.json")
		writeTwin(t, a, namedRecord(t, "", &observed, 3))
		got := report(t, a, f)
		if got.Twin == nil || got.Twin.BundleID != namingBundleID || got.Twin.Provenance.Branch != "fylgja-fixture" {
			t.Fatalf("twin %+v, want the record's bundle_id and branch", got.Twin)
		}
		if !got.LabPresent || len(got.Nodes) != 3 || got.TwinReadError != "" {
			t.Errorf("report %+v, want the lab's three nodes and no read error", got)
		}
	})

	t.Run("an orphan with no twin directory", func(t *testing.T) {
		a, f := inspecting(t, "inspect-one-orphan.json")
		got := report(t, a, f)
		if want := []string{"/tmp/scratchpad/orphan/topology.clab.yml"}; !reflect.DeepEqual(got.TopoPaths, want) {
			t.Errorf("topology paths %v, want %v", got.TopoPaths, want)
		}
		if got.Twin != nil || got.TwinDirPresent || got.Phrase == "" {
			t.Errorf("report %+v, want an orphan named by its phrase", got)
		}
	})

	t.Run("a twin.json that does not parse", func(t *testing.T) {
		a, f := inspecting(t, "inspect-three.json")
		if err := os.MkdirAll(a.Paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(a.Paths.TwinJSON, []byte("{"), 0o644); err != nil {
			t.Fatal(err)
		}
		got := report(t, a, f)
		if got.Twin != nil || got.TwinReadError == "" {
			t.Errorf("report %+v, want no record and the read error", got)
		}
	})

	t.Run("clab failing", func(t *testing.T) {
		a := testActivities(t, &fakeRunner{replies: map[string][]reply{"inspect": {{
			stderr: []byte(`   ERROR  Unknown container runtime "bogus".` + "\n"), exit: 1,
		}}}})
		_, err := a.InspectTwin(context.Background())
		f := stepFailure(t, err, findings.RuleOperationFailed)
		if f.Step != findings.StepInspect {
			t.Errorf("finding %+v, want step inspect", f)
		}
	})
}
