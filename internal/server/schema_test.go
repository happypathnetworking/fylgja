package server

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// The success line names the library's commit and every kind the mapping reads, in the
// table's order (contracts/scope-and-commands.md): an operator sees which model their
// branch was checked against, and which of its kinds the reader reads, not a count. The
// generic DcimConnector, whose connected_endpoints the Ports query reads, is named last,
// as the table holds it beside DcimCable.
func TestConformantLineNamesTheCommitAndTheKinds(t *testing.T) {
	v := &findings.Verified{Model: intent.LibraryModel, Version: intent.LibraryVersion}
	for _, k := range intent.LibraryTables {
		v.Kinds = append(v.Kinds, findings.KindFields{Kind: k.Kind, Fields: k.Fields()})
	}
	got := conformantLine(v)
	want := "conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer, " +
		"InterfacePhysical, DcimCable, DcimConnector"
	if got != want {
		t.Errorf("conformantLine() = %q, want %q", got, want)
	}
}
