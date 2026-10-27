package server

import (
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The record line twin show, twin create and twin provision print names the record's
// snapshot between its reference and its bundle (018): the full id, as the bundle's is
// printed; none for a 9 naming none; and none with the version for a record of 8 or earlier,
// which names none.
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
		{"a 9 naming its snapshot", record(lab.TwinVersion, &id), "record: branch fylgja-fixture, snapshot " + id + read},
		{"a 9 naming none", record(lab.TwinVersion, nil), "record: branch fylgja-fixture, snapshot none" + read},
		{"an 8", record("8", nil), "record: branch fylgja-fixture, snapshot none (record 8)" + read},
		{"a 7", record("7", nil), "record: branch fylgja-fixture, snapshot none (record 7), bundle_id " + fixtureBundleID +
			", schema abc, scope unknown (record 7)"},
	} {
		if got := recordLine(c.rec); got != c.want {
			t.Errorf("%s: %q, want %q", c.label, got, c.want)
		}
	}
}
