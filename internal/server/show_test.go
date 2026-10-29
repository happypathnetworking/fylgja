package server

import (
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

// The record's version gates are numeric (019, research R-09): a 10 or an 11 reads as later
// than 5, 8 and 9, so its step's wait, its scope and mapping and its snapshot are read as a
// 9's are, and an earlier version or one that is no number reads as the record that lacks
// them.
func TestVersionGatesReadTen(t *testing.T) {
	if lab.TwinVersion != "11" {
		t.Fatalf("this build writes twin.json %s, want 11", lab.TwinVersion)
	}
	for _, c := range []struct {
		version               string
		wait, scope, snapshot bool
	}{
		{"11", true, true, true},
		{"10", true, true, true},
		{"9", true, true, true},
		{"8", true, true, false},
		{"5", true, false, false},
		{"4", false, false, false},
		{"1", false, false, false},
		{"", false, false, false},
	} {
		rec := &wire.TwinRecord{TwinVersion: c.version}
		if w, s, n := waitRecorded(rec), scopeRecorded(rec), snapshotRecorded(rec); w != c.wait || s != c.scope || n != c.snapshot {
			t.Errorf("twin.json %q: wait %t, scope %t, snapshot %t; want %t, %t and %t", c.version, w, s, n, c.wait, c.scope, c.snapshot)
		}
	}
}
