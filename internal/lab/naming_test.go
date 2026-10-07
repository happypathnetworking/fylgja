package lab

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The identities contracts/cli.md shows, so the phrases below read as the contract's.
const (
	namingBundleID = "893b6392da4f1de868e74e418d90f3d5982ecc06ffa1dc39a391d717a81997ad"
	namingRunID    = "01a0a698-fc78-7cb5-b0f1-a31c8f06d7e9"
	namingAt       = "2026-09-16T14:00:00Z"
)

// namedRecord builds a twin record as RecordTwin would: through NewRecord, with nodes
// n1…n<nodes>. at "" is an unpinned reference; observedAt nil is a twin provisioned from
// a bundle, which had no read.
func namedRecord(t *testing.T, at string, observedAt *string, nodes int) *wire.TwinRecord {
	t.Helper()
	source := wire.SourceIntent
	if observedAt == nil {
		source = wire.SourceBundle
	}
	f := RecordFields{
		BundleID:   namingBundleID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", At: at, SchemaHash: "41349c3a", ContractVersion: "0.2"},
		ObservedAt: observedAt,
		Source:     source,
		RunID:      namingRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 16, 14, 1, 2, 0, time.UTC),
	}
	for i := 1; i <= nodes; i++ {
		name := fmt.Sprintf("n%d", i)
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: name, Container: "clab-fylgja-" + name,
			Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			MgmtIPv4: fmt.Sprintf("172.20.20.%d", i+1), ReadyAfterS: 0.3})
	}
	rec, err := NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return &rec
}

// Every shape Describe names, exactly: the phrase is text an operator reads and a
// script greps, so a drift in a comma is a defect.
func TestDescribeEveryShape(t *testing.T) {
	observed := "2026-09-16T13:59:30.000000Z"
	const (
		orphanTopo    = "/tmp/scratchpad/orphan/topology.clab.yml"
		elsewhereTopo = "/tmp/scratchpad/elsewhere/topology.clab.yml"
		twinTopo      = "/tmp/scratchpad/twin3/bundle/topology.clab.yml"
		reason        = "reading /tmp/scratchpad/state/twin/twin.json: unexpected end of JSON input"
	)
	lab := func(paths ...string) LabState { return LabState{Present: true, TopoPaths: paths} }
	twin := "the twin of branch fylgja-fixture, bundle_id " + namingBundleID +
		", provisioned by run fylgja-provision " + namingRunID + ", 3 nodes recorded"

	for _, tc := range []struct {
		label string
		host  HostState
		want  string
	}{
		{"(a) unpinned",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 3)},
			twin},
		{"(a) pinned",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true, Twin: namedRecord(t, namingAt, &observed, 3)},
			"the twin of branch fylgja-fixture at 2026-09-16T14:00:00Z, bundle_id " + namingBundleID +
				", provisioned by run fylgja-provision " + namingRunID + ", 3 nodes recorded"},
		{"(a) from twin provision",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true, Twin: namedRecord(t, "", nil, 3)},
			twin},
		{"(a) one recorded node",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 1)},
			"the twin of branch fylgja-fixture, bundle_id " + namingBundleID +
				", provisioned by run fylgja-provision " + namingRunID + ", 1 node recorded"},
		{"(b) record without a lab",
			HostState{TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 3)},
			twin + ", but lab fylgja is absent"},
		{"(c) one path",
			HostState{Lab: lab(orphanTopo)},
			"an orphan: no twin.json records it; deployed from /tmp/scratchpad/orphan/topology.clab.yml"},
		{"(c) two paths",
			HostState{Lab: lab(elsewhereTopo, twinTopo)},
			"an orphan: no twin.json records it; deployed from /tmp/scratchpad/elsewhere/topology.clab.yml, /tmp/scratchpad/twin3/bundle/topology.clab.yml"},
		{"(d) cut short",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true},
			"an orphan: no twin.json records it (a run cut short before it recorded the twin); deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml"},
		{"(e) unreadable",
			HostState{Lab: lab(twinTopo), TwinDirPresent: true, TwinReadError: reason},
			"treated as an orphan: twin.json could not be read (reading /tmp/scratchpad/state/twin/twin.json: unexpected end of JSON input); deployed from /tmp/scratchpad/twin3/bundle/topology.clab.yml"},
		{"(f) leftover",
			HostState{TwinDirPresent: true},
			"a leftover twin directory: no twin.json and no lab fylgja"},
		{"(g) leftover, unreadable",
			HostState{TwinDirPresent: true, TwinReadError: reason},
			"a leftover twin directory: twin.json could not be read (reading /tmp/scratchpad/state/twin/twin.json: unexpected end of JSON input), and lab fylgja is absent"},
		{"(h) nothing",
			HostState{},
			""},
	} {
		t.Run(tc.label, func(t *testing.T) {
			if got := tc.host.Describe(); got != tc.want {
				t.Errorf("Describe() =\n  %q\nwant\n  %q", got, tc.want)
			}
		})
	}
}

// observed_at stays in twin.json: the phrase names the reference, not when it was read.
func TestDescribeCarriesNoObservedAt(t *testing.T) {
	observed := "2026-09-16T13:57:41.918273Z"
	for _, host := range []HostState{
		{Lab: LabState{Present: true}, TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 3)},
		{Lab: LabState{Present: true}, TwinDirPresent: true, Twin: namedRecord(t, namingAt, &observed, 3)},
		{TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 3)},
	} {
		if got := host.Describe(); strings.Contains(got, observed) || strings.Contains(got, "13:57:41") {
			t.Errorf("Describe() = %q carries observed_at %s", got, observed)
		}
	}
}

// The operator copies the identities into twin provision, the Temporal UI or a grep, so
// neither is abbreviated.
func TestDescribeNamesIdentitiesInFull(t *testing.T) {
	observed := "2026-09-16T13:59:30.000000Z"
	got := HostState{Lab: LabState{Present: true}, TwinDirPresent: true, Twin: namedRecord(t, "", &observed, 3)}.Describe()
	for _, id := range []string{namingBundleID, namingRunID} {
		if !strings.Contains(got, id) {
			t.Errorf("Describe() = %q does not carry %s in full", got, id)
		}
	}
}
