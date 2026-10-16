package stages

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The story of research §6.5 at one mark: the seed generated each device's artifact at
// t0; an intent edit at t1; the proposed change's validators at t2 and t3.
const (
	t0 = "2026-10-16T19:35:10.000000+00:00" // the seed's checksums
	t1 = "2026-10-16T19:35:55.000000+00:00" // -set-site, or a role edit, after the creation's validator
	t2 = "2026-10-16T19:35:52.068456Z"      // the creation's validator, before the edit reached it
	t3 = "2026-10-16T19:36:12.298111Z"      // the run-check's, after it
	tm = "2026-10-16T19:40:00.000000+00:00" // the mark
)

// TestStalePerDevice is D-046 per device at one mark: exactly the devices whose own
// intent is newer than their generation stamp, the later of their checksum's and the
// proposed change's artifact validator's completion, are named, one finding each, sorted.
func TestStalePerDevice(t *testing.T) {
	edited := func(names ...string) intent.Stamps {
		s := intent.Stamps{Latest: tm, Devices: map[string]intent.DeviceStamps{}}
		for _, n := range []string{"n1", "n2", "n3"} {
			at := "2026-10-16T19:35:00.000000+00:00"
			if slices.Contains(names, n) {
				at = t1
			}
			s.Devices[n] = device(at, t0)
		}
		return s
	}
	for _, tc := range []struct {
		name      string
		stamps    intent.Stamps
		validated string // the validator's completed_at in force at the mark
		stale     []string
		validator bool // whether the validator was read
	}{
		{name: "checksum older than intent is stale", stamps: edited("n3", "n1"), stale: []string{"n1", "n3"}, validator: true},
		{name: "a validator completed before the edit leaves it stale", stamps: edited("n1"), validated: t2,
			stale: []string{"n1"}, validator: true},
		// A hand generate rendering identical bytes moves no checksum; the run-check after
		// it re-runs the validator, whose completion clears every device.
		{name: "an identical-bytes generate then a run-check clears it", stamps: edited("n1", "n2", "n3"), validated: t3,
			validator: true},
		// -add-link's hand generate: n2's own stamps did not move, so n2 is fresh whatever
		// its neighbours did.
		{name: "a neighbour's change names no n2", stamps: edited("n1", "n3"), stale: []string{"n1", "n3"}, validator: true},
		{name: "fresh reads no validator", stamps: edited()},
		{name: "a checksum after the intent clears it", stamps: func() intent.Stamps {
			s := edited("n1")
			s.Devices["n1"] = device(t1, "2026-10-16T19:36:00.000000+00:00")
			return s
		}()},
		{name: "no artifact, no finding", stamps: func() intent.Stamps {
			s := edited("n1", "n2")
			s.Devices["n1"] = intent.DeviceStamps{Platform: s.Devices["n1"].Platform, Intent: t1, Artifacts: map[string]string{}}
			s.Devices["n2"] = intent.DeviceStamps{Platform: s.Devices["n2"].Platform, Intent: t1,
				Artifacts: map[string]string{"other-config": t0}}
			return s
		}()},
		{name: "a platform no package covers is the read's", stamps: func() intent.Stamps {
			s := edited("n1")
			d := s.Devices["n1"]
			d.Platform.NOS = "nosuch"
			s.Devices["n1"] = d
			return s
		}()},
		{name: "an unstamped checksum is judged by the validator", stamps: func() intent.Stamps {
			s := edited("n1", "n2")
			s.Devices["n1"] = device(t1, "")
			s.Devices["n2"] = device("2026-10-16T19:35:00.000000+00:00", "")
			return s
		}(), validated: t2, stale: []string{"n1"}, validator: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, s := story(change1(mark("st-m", "m", tm, nil, "")))
			r.validations = map[string]string{"pc-1@" + tm: tc.validated}
			s.at = map[string]intent.Stamps{"change-1@" + tm: tc.stamps}
			ch, list, err := Find(t.Context(), r, s, "change-1")
			if err != nil || list != nil {
				t.Fatalf("%v %+v", err, list)
			}
			st, _ := ch.first("m")
			list, err = Stale(t.Context(), r, s, registry(t), ch, st.Resolved)
			if err != nil {
				t.Fatal(err)
			}
			var stale []string
			for _, f := range list {
				if f.Rule != findings.RuleStageArtifactStale || f.Severity != findings.Rejection || f.Step != findings.StepResolve ||
					!strings.HasPrefix(f.Message, "device "+f.Object+": its intent on change-1 was written at "+t1+
						", later than its artifact device-config was generated (") ||
					!strings.Contains(f.Message, "regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the "+
						"proposed change's checks: a retry in Infrahub, or CoreProposedChangeRunCheck) and mark again") {
					t.Errorf("finding %+v", f)
				}
				stale = append(stale, f.Object)
			}
			if !reflect.DeepEqual(stale, tc.stale) {
				t.Errorf("stale %v, want %v", stale, tc.stale)
			}
			read := slices.Contains(r.calls, "Validations pc-1@"+tm)
			if read != tc.validator {
				t.Errorf("validator read %v (calls %v), want %v", read, r.calls, tc.validator)
			}
			if !slices.Contains(s.calls, "change-1@"+tm) {
				t.Errorf("stamps read %v; want the branch's pinned at the mark", s.calls)
			}
		})
	}
}

// The two validator wordings, and the checksum's.
func TestStaleWording(t *testing.T) {
	r, s := story(change1(mark("st-m", "m", tm, nil, "")))
	stamps := intent.Stamps{Latest: tm, Devices: map[string]intent.DeviceStamps{"n1": device(t1, t0)}}
	s.at = map[string]intent.Stamps{"change-1@" + tm: stamps}
	r.validations = map[string]string{"pc-1@" + tm: t2}
	_, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "m"}, now)
	if err != nil || len(list) != 1 {
		t.Fatalf("%v %+v", err, list)
	}
	want := "device n1: its intent on change-1 was written at " + t1 + ", later than its artifact device-config was " +
		"generated (checksum stamped " + t0 + "; the proposed change's artifact validator last completed " + t2 + "): " +
		"stage change-1/m was marked before the artifacts were regenerated; regenerate (fylgja-fixture -generate, POST " +
		"/api/artifact/generate, or the proposed change's checks: a retry in Infrahub, or CoreProposedChangeRunCheck) " +
		"and mark again"
	if list[0].Message != want {
		t.Errorf("message\n  %s\nwant\n  %s", list[0].Message, want)
	}
}

// The head is stale after an intent edit, judged on the branch's unpinned stamps its at
// came from, until a regenerate or a run-check; the validator is read unpinned, since its
// completion never enters the head's at.
func TestStaleHead(t *testing.T) {
	r, s := story()
	s.byBranch["change-1"] = intent.Stamps{Latest: t1, Devices: map[string]intent.DeviceStamps{"n1": device(t1, t0)}}
	_, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "head"}, now)
	if err != nil || len(list) != 1 || list[0].Rule != findings.RuleStageArtifactStale || list[0].Object != "n1" ||
		!strings.HasSuffix(list[0].Message, "the head of change-1 is later than the artifacts' last regeneration; regenerate "+
			"(fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's checks: a retry in Infrahub, "+
			"or CoreProposedChangeRunCheck)") {
		t.Fatalf("%v %+v", err, list)
	}
	if want := []string{"change-1@"}; !reflect.DeepEqual(s.calls, want) {
		t.Errorf("stamps read %v, want the branch's unpinned alone %v", s.calls, want)
	}
	if !slices.Contains(r.calls, "Validations pc-1@") {
		t.Errorf("reads %v; want the validator unpinned", r.calls)
	}

	// The run-check after the edit, identical bytes: the head's at does not move, and the
	// validator's completion clears it.
	r.validations = map[string]string{"pc-1@": t3}
	got, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "head"}, now)
	if err != nil || list.Rejected() || got.At != "2026-10-16T19:35:55.000001+00:00" {
		t.Errorf("after the run-check: %+v %v %+v", got, err, list)
	}
}

// The branch point on a destination that holds no device is fresh, and reads no validator.
func TestStaleBranchPointOnAnEmptyMain(t *testing.T) {
	r, s := story()
	got, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "branch-point"}, now)
	if err != nil || list != nil || got.Branch != "main" || got.At != branchedFrom {
		t.Fatalf("%+v %v %+v", got, err, list)
	}
	if !slices.Contains(s.calls, "main@"+branchedFrom) {
		t.Errorf("stamps read %v; want main's pinned at the branch point", s.calls)
	}
	for _, c := range r.calls {
		if strings.HasPrefix(c, "Validations") {
			t.Errorf("a fresh stage read the validator: %v", r.calls)
		}
	}
}

// The artifact a device is judged by is its package's config.artifact_name, from the
// registry by the device's platform, never a constant (Constitution II): a package naming
// another artifact makes the other artifact's checksum the one that counts.
func TestStaleNamesTheArtifactByThePackage(t *testing.T) {
	src, err := fylgja.Data.ReadFile("psp/nokia_srlinux.yaml")
	if err != nil {
		t.Fatal(err)
	}
	derived := string(src)
	for from, to := range map[string]string{
		"id: nokia_srlinux":            "id: acme_os",
		"nos: srlinux":                 "nos: acme_os",
		"artifact_name: device-config": "artifact_name: acme-config",
	} {
		if !strings.Contains(derived, from) {
			t.Fatalf("the shipped package no longer contains %q; update this test", from)
		}
		derived = strings.Replace(derived, from, to, 1)
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "acme_os.yaml"), []byte(derived), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(dir)
	if err != nil {
		t.Fatal(err)
	}

	acme := func(intentAt string, artifacts map[string]string) intent.DeviceStamps {
		return intent.DeviceStamps{Platform: ctm.Platform{Vendor: "acme", NOS: "acme_os"}, Intent: intentAt, Artifacts: artifacts}
	}
	stamps := intent.Stamps{Latest: tm, Devices: map[string]intent.DeviceStamps{
		// device-config is fresh and acme-config stale: a stale acme device.
		"a1": acme(t1, map[string]string{"device-config": tm, "acme-config": t0}),
		// device-config is stale and acme-config fresh: a fresh acme device.
		"a2": acme(t1, map[string]string{"device-config": t0, "acme-config": tm}),
		// An SR Linux device beside them is still judged by device-config.
		"n1": device(t1, t0),
	}}
	r, s := story(change1(mark("st-m", "m", tm, nil, "")))
	s.at = map[string]intent.Stamps{"change-1@" + tm: stamps}
	_, list, err := Resolve(t.Context(), r, s, reg, Ref{"change-1", "m"}, now)
	if err != nil {
		t.Fatal(err)
	}
	var stale []string
	for _, f := range list {
		stale = append(stale, f.Object)
		if f.Object == "a1" && !strings.Contains(f.Message, "its artifact acme-config was generated") {
			t.Errorf("a1: %s", f.Message)
		}
	}
	if want := []string{"a1", "n1"}; !reflect.DeepEqual(stale, want) {
		t.Errorf("stale %v, want %v", stale, want)
	}
}
