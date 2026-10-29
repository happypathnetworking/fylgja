package server

import (
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The record line twin show, twin create and twin provision print names the record's
// snapshot between its reference and its bundle (018): the full id, as the bundle's is
// printed; none for a 9 or a 10 naming none; and none with the version for a record of 8 or
// earlier, which names none.
func TestRecordLineNamesTheSnapshot(t *testing.T) {
	id := strings.Repeat("6a", 32)
	record := func(version string, snapshot *string) *wire.TwinRecord {
		return &wire.TwinRecord{TwinVersion: version, SnapshotID: snapshot, BundleID: fixtureBundleID,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc", Scope: "tag:fylgja", Mapping: dcimMapping}}
	}
	const read = ", bundle_id " + fixtureBundleID + ", schema abc, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9"
	for _, c := range []struct {
		label string
		rec   *wire.TwinRecord
		want  string
	}{
		{"a 10 naming its snapshot", record(lab.TwinVersion, &id), "record: branch fylgja-fixture, snapshot " + id + read},
		{"a 10 naming none", record(lab.TwinVersion, nil), "record: branch fylgja-fixture, snapshot none" + read},
		{"a 9 naming its snapshot", record("9", &id), "record: branch fylgja-fixture, snapshot " + id + read},
		{"a 9 naming none", record("9", nil), "record: branch fylgja-fixture, snapshot none" + read},
		{"an 8", record("8", nil), "record: branch fylgja-fixture, snapshot none (record 8)" + read},
		{"a 7", record("7", nil), "record: branch fylgja-fixture, snapshot none (record 7), bundle_id " + fixtureBundleID +
			", schema abc, scope unknown (record 7)"},
	} {
		if got := recordLine(c.rec); got != c.want {
			t.Errorf("%s: %q, want %q", c.label, got, c.want)
		}
	}
}

// The record's version gates are numeric (019, research R-09): a 10, an 11 or a 12 reads as
// later than 5, 8 and 9, so its step's wait, its scope and mapping and its snapshot are read
// as a 9's are, and an earlier version or one that is no number reads as the record that
// lacks them; only a 12 or later is one twin step steps (020, research R-06).
func TestVersionGatesReadTen(t *testing.T) {
	if lab.TwinVersion != "12" {
		t.Fatalf("this build writes twin.json %s, want 12", lab.TwinVersion)
	}
	for _, c := range []struct {
		version                      string
		wait, scope, snapshot, steps bool
	}{
		{"13", true, true, true, true},
		{"12", true, true, true, true},
		{"11", true, true, true, false},
		{"10", true, true, true, false},
		{"9", true, true, true, false},
		{"8", true, true, false, false},
		{"5", true, false, false, false},
		{"4", false, false, false, false},
		{"1", false, false, false, false},
		{"", false, false, false, false},
	} {
		rec := &wire.TwinRecord{TwinVersion: c.version}
		w, s, n, st := waitRecorded(rec), scopeRecorded(rec), snapshotRecorded(rec), recordSteps(rec)
		if w != c.wait || s != c.scope || n != c.snapshot || st != c.steps {
			t.Errorf("twin.json %q: wait %t, scope %t, snapshot %t, steps %t; want %t, %t, %t and %t", c.version, w, s, n, st,
				c.wait, c.scope, c.snapshot, c.steps)
		}
	}
}

// A record of twin.json 11 or earlier whose lab is there is shown naming its version, in the
// details and the notes, and not as a record naming no snapshot, since twin step refuses it by
// its version first (020, research R-06; US2 scenario 8); a 12 naming no snapshot says that
// alone, and a 12 naming one says neither.
func TestShowNamesAnEarlierRecordsVersion(t *testing.T) {
	id := strings.Repeat("6a", 32)
	lab1 := lab.LabState{Present: true, Nodes: []wire.LabNode{{Name: "n1", Container: "clab-fylgja-n1", State: "running"}}}
	old := func(v string) string {
		return "the twin's record is twin.json " + v + ", a version this build no longer steps; fylgja twin destroy clears it"
	}
	for _, c := range []struct {
		label    string
		version  string
		snapshot *string
		want     []string
	}{
		{"an 11 naming its snapshot", "11", &id, []string{old("11")}},
		{"an 11 naming none", "11", nil, []string{old("11")}},
		{"an 8", "8", nil, []string{old("8")}},
		{"a 12 naming none", lab.TwinVersion, nil, []string{noSnapshotNote}},
		{"a 12 naming its snapshot", lab.TwinVersion, &id, nil},
	} {
		rec := &wire.TwinRecord{TwinVersion: c.version, Lab: wire.LabName, SnapshotID: c.snapshot, BundleID: fixtureBundleID,
			Source: wire.SourceIntent, State: wire.StateReady, Nodes: []wire.TwinNode{{Name: "n1"}},
			Provenance: wire.Provenance{Branch: "fylgja-fixture", At: "2026-10-29T09:00:00Z", Scope: "tag:fylgja", Mapping: dcimMapping}}
		block, text := decideShow(lab.HostState{Lab: lab1, TwinDirPresent: true, Twin: rec}, serviceReads{}, "")
		var got []string
		for _, n := range block.Notes {
			if n == noSnapshotNote || strings.Contains(n, "no longer steps") {
				got = append(got, n)
			}
		}
		if !slices.Equal(got, c.want) {
			t.Errorf("%s: notes %q; want %q", c.label, block.Notes, c.want)
		}
		for _, w := range c.want {
			if !slices.Contains(text.details, w) {
				t.Errorf("%s: details %q lack %q", c.label, text.details, w)
			}
		}
	}
}
