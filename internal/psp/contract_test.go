package psp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// contractsDir is the module root's contracts/, as internal/compiler's is: it holds the
// current contract, the only copy that describes what this build loads.
func contractsDir() string {
	return filepath.Join("..", "..", "contracts")
}

// The schema shipped in the binary and the schema the feature's contract publishes are
// one file in two places, and this holds them so.
//
// It does not say the schema is right — the fixtures under testdata/psp/ do that. It says
// the two copies cannot drift, which nothing else checks: psp.schema.json is the only
// contract schema no test reads. ctm, manifest, findings and show are compiled from
// contractsDir() by internal/compiler, and twin.schema.json by internal/lab and
// internal/provision, so a change to one of those that missed its contract fails there.
// A change to this one that missed its contract failed nowhere: `0.5` grew six additive
// fields in one feature (readiness.tls, readiness.await_push_transport,
// config.comment_prefix, config.bootstrap_via, conformance's absent and its relative
// neighbour leaves), each written into both copies by hand, with one task's `diff` as
// the only proof. Drift here leaves the contract describing a format this build does not
// load, and every reader of the feature's contracts believing it.
func TestShippedSchemaIsTheContractSchema(t *testing.T) {
	const name = "psp.schema.json"
	contract := filepath.Join(contractsDir(), name)
	shipped, err := os.ReadFile(repo("psp", name))
	if err != nil {
		t.Fatal(err)
	}
	published, err := os.ReadFile(contract)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(shipped, published) {
		return
	}
	t.Errorf("psp/%s and %s differ; they are one file in two places, so change both:\n%s",
		name, contract, firstDifference(shipped, published))
}

// The schema's `$id` names its format, as every earlier format's did (`v0.2` to `v0.5` in
// specs 002, 005, 006 and 007), and the loader registers it under the same name. `0.6`
// moved the title and psp_version and left the `$id` at `v0.5`, and nothing failed: the
// registration constant had said `v0.4` since M7, and a resource registered under one
// name compiles under it whatever its document says.
func TestSchemaIDMovesWithTheFormat(t *testing.T) {
	raw, err := SchemaBytes()
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		ID string `json:"$id"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if want := "https://fylgja.dev/psp/v" + FormatVersion; doc.ID != want || schemaID != want {
		t.Errorf("psp.schema.json's $id is %q and the loader registers it as %q; format %s wants %q in both",
			doc.ID, schemaID, FormatVersion, want)
	}
}

// firstDifference says where two copies part, by line, so the failure names the edit
// that was made to one side rather than printing two schemas.
func firstDifference(shipped, published []byte) string {
	a, b := strings.Split(string(shipped), "\n"), strings.Split(string(published), "\n")
	shared := min(len(a), len(b))
	for i := 0; i < shared; i++ {
		if a[i] != b[i] {
			return fmt.Sprintf("  line %d:\n    shipped:  %s\n    contract: %s", i+1, a[i], b[i])
		}
	}
	longer, extra := "psp/", len(a)-len(b)
	if extra < 0 {
		longer, extra = "the contract", -extra
	}
	return fmt.Sprintf("  the copies agree for %d lines; %s has %d more", shared, longer, extra)
}
