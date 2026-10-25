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
		validator bool   // whether the validator was read
		message   string // the one finding's whole message, when the case gives it
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
		// A platform's version edited after the checksums: intent folds the platform's
		// stamps into each device on it (TestStampsPlatform), so n1 and n3 on SR Linux are
		// stale and n2, on EOS, whose package names the same artifact, is not.
		{name: "a platform edited after the checksum names each device on it", stamps: func() intent.Stamps {
			s := edited("n1", "n3")
			d := s.Devices["n2"]
			d.Platform = ctm.Platform{Vendor: "arista", NOS: "eos", Version: "4.32.0.2F"}
			s.Devices["n2"] = d
			return s
		}(), stale: []string{"n1", "n3"}, validator: true},
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
		}(), validated: t2, stale: []string{"n1"}, validator: true,
			message: "device n1: its intent on change-1 was written at " + t1 + ", later than its artifact device-config " +
				"was generated (its checksum unstamped; the proposed change's artifact validator last completed " + t2 +
				"): stage change-1/m was marked before the artifacts were regenerated; regenerate (fylgja-fixture " +
				"-generate, POST /api/artifact/generate, or the proposed change's checks: a retry in Infrahub, or " +
				"CoreProposedChangeRunCheck) and mark again"},
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
			if tc.message != "" && (len(list) != 1 || list[0].Message != tc.message) {
				t.Errorf("findings %+v; want the one saying\n  %s", list, tc.message)
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
		"manufacturer: Nokia":          "manufacturer: Acme",
		"platform: SR Linux":           "platform: AcmeOS",
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

// The removal of research §8.17 at one mark (D-048): the seed's checksums at t0, the link
// n1:ethernet-1/1 — n2:ethernet-1/1 deleted at te, which moves no stamp, and the mark tm
// after it. The delete and its child events on each endpoint interface name n1 and n2,
// and nothing names n3.
const (
	te  = "2026-10-16T19:36:30.031152+00:00" // infrahub.node.deleted of the NetworkLink
	te1 = "2026-10-16T19:36:30.040000+00:00" // node.updated of n1's interface, link REMOVED
	te2 = "2026-10-16T19:36:30.041000+00:00" // node.updated of n2's interface, link REMOVED
)

// removal is the delete's three events, newest first, as the reader returns them.
func removal() []intent.Event {
	return []intent.Event{
		{Name: "infrahub.node.updated", OccurredAt: te2, Kind: "NetworkInterface", Nodes: []string{"if-n2-e1"}},
		{Name: "infrahub.node.updated", OccurredAt: te1, Kind: "NetworkInterface", Nodes: []string{"if-n1-e1"}},
		{Name: "infrahub.node.deleted", OccurredAt: te, Kind: "NetworkLink", Nodes: []string{"link-1", "if-n1-e1", "if-n2-e1"}},
	}
}

// ided is a device's stamps with the ids an event names it by: its own, then its
// interface's.
func ided(name string, d intent.DeviceStamps) intent.DeviceStamps {
	d.IDs = []string{"dev-" + name, "if-" + name + "-e1"}
	return d
}

// removed is the three devices read at the mark: every intent stamp before t0 and every
// checksum at t0, as the delete left them.
func removed(checksum string) intent.Stamps {
	s := intent.Stamps{Latest: checksum, Devices: map[string]intent.DeviceStamps{}}
	for _, n := range []string{"n1", "n2", "n3"} {
		s.Devices[n] = ided(n, device("2026-10-16T19:35:00.000000+00:00", checksum))
	}
	return s
}

// A removal moves no stamp, and its events make exactly the devices they name stale at a
// mark after it: n1 and n2, never n3. The latest naming event is the one the message
// names, beside the device's own latest stamp.
func TestStaleByEvent(t *testing.T) {
	for _, tc := range []struct {
		name      string
		mark      string
		stamps    intent.Stamps
		events    []intent.Event
		validated string
		stale     []string
	}{
		{name: "a mark after the removal names both endpoints", mark: tm, stamps: removed(t0), events: removal(),
			stale: []string{"n1", "n2"}},
		// The mark was made before the delete: an event later than the stage's at is not
		// its intent.
		{name: "a mark before the removal is fresh", mark: "2026-10-16T19:36:00.000000+00:00", stamps: removed(t0),
			events: removal()},
		// A regenerate after the delete moves the checksums past every event.
		{name: "a regenerate after the removal clears it", mark: tm, stamps: removed("2026-10-16T19:37:00.000000+00:00"),
			events: removal()},
		// A run-check after the delete: its validator's completion is the generation
		// stamp, whatever bytes it rendered.
		{name: "a validator completed after the removal clears it", mark: tm, stamps: removed(t0), events: removal(),
			validated: "2026-10-16T19:37:00.000000Z"},
		// The delete alone, with no child event: its peers name the endpoints.
		{name: "the delete's peers name the endpoints", mark: tm, stamps: removed(t0), events: removal()[2:],
			stale: []string{"n1", "n2"}},
		// An edit of n3 itself, by its own id.
		{name: "an event on the device names it", mark: tm, stamps: removed(t0), events: []intent.Event{
			{Name: "infrahub.node.updated", OccurredAt: te, Kind: "NetworkDevice", Nodes: []string{"dev-n3"}}},
			stale: []string{"n3"}},
		{name: "an event naming no device of the branch stales none", mark: tm, stamps: removed(t0), events: []intent.Event{
			{Name: "infrahub.node.updated", OccurredAt: te, Kind: "NetworkPlatform", Nodes: []string{"platform-1"}}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, s := story(change1(mark("st-m", "m", tc.mark, nil, "")))
			r.events = map[string][]intent.Event{"change-1": tc.events}
			r.validations = map[string]string{"pc-1@" + tc.mark: tc.validated}
			s.at = map[string]intent.Stamps{"change-1@" + tc.mark: tc.stamps}
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
				stale = append(stale, f.Object)
				if f.Rule != findings.RuleStageArtifactStale || f.Severity != findings.Rejection || f.Step != findings.StepResolve {
					t.Errorf("finding %+v", f)
				}
			}
			if !reflect.DeepEqual(stale, tc.stale) {
				t.Errorf("stale %v, want %v", stale, tc.stale)
			}
		})
	}
}

// The message names the latest event naming the device, its name and kind, beside the
// device's own latest stamp, or that it has none; a device whose stamps are later than
// every event naming it keeps the stamp's wording.
func TestStaleByEventWording(t *testing.T) {
	const created = "2026-10-16T19:36:40.000000+00:00"
	r, s := story(change1(mark("st-m", "m", tm, nil, "")))
	stamps := removed(t0)
	stamps.Devices["n2"] = ided("n2", device("2026-10-16T19:39:00.000000+00:00", t0)) // edited after the delete
	stamps.Devices["n3"] = ided("n3", device("", t0))                                 // nothing of its own stamped
	s.at = map[string]intent.Stamps{"change-1@" + tm: stamps}
	r.events = map[string][]intent.Event{"change-1": append([]intent.Event{
		{Name: "infrahub.node.created", OccurredAt: created, Kind: "NetworkInterface", Nodes: []string{"if-n3-e1"}},
	}, removal()...)}
	_, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "m"}, now)
	if err != nil || len(list) != 3 {
		t.Fatalf("%v %+v", err, list)
	}
	tail := ", later than its artifact device-config was generated (checksum stamped " + t0 + "; no artifact validator of " +
		"the proposed change had completed): stage change-1/m was marked before the artifacts were regenerated; regenerate " +
		"(fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's checks: a retry in Infrahub, or " +
		"CoreProposedChangeRunCheck) and mark again"
	for i, want := range []string{
		"device n1: its intent on change-1 was written at " + te1 + " (Infrahub's event log: infrahub.node.updated of a " +
			"NetworkInterface; its latest stamp 2026-10-16T19:35:00.000000+00:00)" + tail,
		"device n2: its intent on change-1 was written at 2026-10-16T19:39:00.000000+00:00" + tail,
		"device n3: its intent on change-1 was written at " + created + " (Infrahub's event log: infrahub.node.created " +
			"of a NetworkInterface; no stamp of its own)" + tail,
	} {
		if list[i].Message != want {
			t.Errorf("message %d\n  %s\nwant\n  %s", i, list[i].Message, want)
		}
	}
}

// The head is pinned one microsecond after the later of the branch's latest stamp and its
// latest intent event (D-048): a removal as the latest write moves it past the delete, and
// the head is then stale for the devices the delete names until a regenerate. Only the
// events after the latest stamp are read for its at.
func TestHeadAfterARemoval(t *testing.T) {
	r, s := story()
	s.byBranch["change-1"] = removed(t0)
	r.events = map[string][]intent.Event{"change-1": removal()}
	got, list, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "head"}, now)
	if err != nil || !list.Rejected() {
		t.Fatalf("%+v %v %+v", got, err, list)
	}
	var stale []string
	for _, f := range list {
		if f.Rule == findings.RuleStageArtifactStale {
			stale = append(stale, f.Object)
		}
	}
	if want := []string{"n1", "n2"}; !reflect.DeepEqual(stale, want) {
		t.Errorf("stale %v, want %v", stale, want)
	}
	ch, _, err := Find(t.Context(), r, s, "change-1")
	if err != nil {
		t.Fatal(err)
	}
	if head, _ := ch.first(LabelHead); head.At != "2026-10-16T19:36:30.041001+00:00" {
		t.Errorf("the head's at is %s; want one microsecond after the latest intent event %s", head.At, te2)
	}
	if !slices.Contains(r.calls, "IntentEvents change-1 since "+branchedFrom+" after "+t0) {
		t.Errorf("reads %v; want the events after the latest stamp", r.calls)
	}

	// The regenerate: the checksums move past every event, and so does the head.
	regenerated := "2026-10-16T19:37:00.000000+00:00"
	s.byBranch["change-1"] = removed(regenerated)
	got, list, err = Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "head"}, now)
	if err != nil || list.Rejected() || got.At != "2026-10-16T19:37:00.000001+00:00" {
		t.Errorf("after the regenerate: %+v %v %+v", got, err, list)
	}
}

// An event no later than the latest stamp leaves the head where the stamps put it, and a
// branch holding nothing stamped but an event has its head after the event.
func TestHeadEvents(t *testing.T) {
	r, s := story()
	s.byBranch["change-1"] = removed("2026-10-16T19:37:00.000000+00:00")
	r.events = map[string][]intent.Event{"change-1": removal()}
	ch, _, err := Find(t.Context(), r, s, "change-1")
	if err != nil {
		t.Fatal(err)
	}
	if head, _ := ch.first(LabelHead); head.At != "2026-10-16T19:37:00.000001+00:00" {
		t.Errorf("the head's at is %s; want the stamps' alone", head.At)
	}

	s.byBranch["change-1"] = intent.Stamps{}
	ch, _, err = Find(t.Context(), r, s, "change-1")
	if err != nil {
		t.Fatal(err)
	}
	if head, _ := ch.first(LabelHead); head.At != "2026-10-16T19:36:30.041001+00:00" {
		t.Errorf("the head's at is %s; want one microsecond after the latest event", head.At)
	}
	if !slices.Contains(r.calls, "IntentEvents change-1 since "+branchedFrom+" after ") {
		t.Errorf("reads %v; want every event since the branch point", r.calls)
	}
}

// The staleness rule reads the events after the earliest checksum it judges, every one
// when a checksum is unstamped, once per bound for every stage of a proposed change; the
// branch point, on main before the branch's history, reads none.
func TestStaleEventsRead(t *testing.T) {
	events := func(r *fakeReader) []string {
		var out []string
		for _, c := range r.calls {
			if strings.HasPrefix(c, "IntentEvents") {
				out = append(out, c)
			}
		}
		return out
	}
	// The head's latest stamp is a regenerate after the mark, so the head's read is bounded
	// later than the mark's earliest checksum, and the mark reads again, once.
	regenerated := "2026-10-16T19:41:00.000000+00:00"
	r, s := story(change1(mark("st-m", "m", tm, nil, "")))
	s.byBranch["change-1"] = removed(regenerated)
	stamps := removed(t0)
	stamps.Devices["n3"] = ided("n3", device("2026-10-16T19:35:00.000000+00:00", "2026-10-16T19:35:20.000000+00:00"))
	s.at = map[string]intent.Stamps{"change-1@" + tm: stamps}
	ch, _, err := Find(t.Context(), r, s, "change-1")
	if err != nil {
		t.Fatal(err)
	}
	st, _ := ch.first("m")
	for range 2 {
		if _, err := Stale(t.Context(), r, s, registry(t), ch, st.Resolved); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := Stale(t.Context(), r, s, registry(t), ch, ch.Stages[len(ch.Stages)-1].Resolved); err != nil {
		t.Fatal(err) // the head, served by the mark's read
	}
	want := []string{"IntentEvents change-1 since " + branchedFrom + " after " + regenerated,
		"IntentEvents change-1 since " + branchedFrom + " after " + t0}
	if got := events(r); !reflect.DeepEqual(got, want) {
		t.Errorf("event reads %v, want %v", got, want)
	}

	unstamped := removed(t0)
	unstamped.Devices["n2"] = ided("n2", device("2026-10-16T19:35:00.000000+00:00", ""))
	s.at["change-1@"+tm] = unstamped
	if _, err := Stale(t.Context(), r, s, registry(t), ch, st.Resolved); err != nil {
		t.Fatal(err)
	}
	if got := events(r); len(got) != 3 || got[2] != "IntentEvents change-1 since "+branchedFrom+" after " {
		t.Errorf("event reads %v; want every event since the branch point last", got)
	}

	r, s = story()
	s.byBranch["main"] = removed(t0)
	if _, _, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "branch-point"}, now); err != nil {
		t.Fatal(err)
	}
	if got := events(r); len(got) != 1 || !strings.HasSuffix(got[0], " after "+headLatest) {
		t.Errorf("event reads %v; want the head's alone", got)
	}
}

// A branch Infrahub returns no branched_from for reads no event: nothing bounds the log
// to its own history, and its branch point is refused for having no at.
func TestNoBranchPointNoEvents(t *testing.T) {
	r, s := story()
	r.events = map[string][]intent.Event{"change-1": removal()}
	r.branches["change-1"] = &intent.BranchInfo{Name: "change-1", CreatedAt: createdAt}
	s.byBranch["change-1"] = removed(t0)
	ch, list, err := Find(t.Context(), r, s, "change-1")
	if err != nil || list != nil {
		t.Fatalf("%v %+v", err, list)
	}
	if head, _ := ch.first(LabelHead); head.At != "2026-10-16T19:35:10.000001+00:00" {
		t.Errorf("the head's at is %s; want the stamps' alone", head.At)
	}
	_, list, err = Resolve(t.Context(), r, s, registry(t), Ref{"change-1", LabelBranchPoint}, now)
	want := "stage change-1/branch-point has no at: Infrahub returned no branched_from for branch change-1, so it " +
		"names no point in time"
	if err != nil || len(list) != 1 || list[0].Rule != findings.RuleStageAtUnresolved || list[0].Severity != findings.Rejection ||
		list[0].Step != findings.StepResolve || list[0].Object != "change-1/branch-point" || list[0].Message != want {
		t.Errorf("the branch point: %v %+v; want the one rejection %s saying\n  %s", err, list, findings.RuleStageAtUnresolved, want)
	}
	for _, c := range r.calls {
		if strings.HasPrefix(c, "IntentEvents") {
			t.Errorf("read %s with no branched_from", c)
		}
	}
}
