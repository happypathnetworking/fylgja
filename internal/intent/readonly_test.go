package intent

import (
	"regexp"
	"slices"
	"strings"
	"testing"
)

// operations is every GraphQL document this package can send. The generated client is
// the only thing that talks to Infrahub in the product, so this map is the whole
// surface the two tests below have to cover.
func operations() map[string]string {
	return map[string]string{
		"ContractVersion": ContractVersion_Operation,
		"Devices":         Devices_Operation,
		"Links":           Links_Operation,
		// 014: the stage reader's five, on the default branch, and the branch's stamps.
		// FylgjaStage's root is Fylgja's; the other four are infrahubRoots below.
		"ProposedChanges":     ProposedChanges_Operation,
		"OrphanStages":        OrphanStages_Operation,
		"BranchPoint":         BranchPoint_Operation,
		"ArtifactValidations": ArtifactValidations_Operation,
		"IntentEvents":        IntentEvents_Operation,
		"IntentStamps":        IntentStamps_Operation,
	}
}

// infrahubRoots are the roots an operation may select that are not Fylgja's: each is
// Infrahub's own unit, which nobody implements, and none is the operator's model of the
// network, so reading it reserves no structure of theirs (Constitution III, amended to
// 1.2.1 for D-045 and to 1.3.0 for D-048; research R-03). Each is named; anything else
// that is not Fylgja's is still refused.
var infrahubRoots = map[string]bool{
	// The proposed change is Infrahub's unit of review, and the stage's home (D-045):
	// a stage is a moment of one, found by its source branch.
	"CoreProposedChange": true,
	// The artifact validator is Infrahub's own check of a proposed change's artifacts;
	// its completion is half of a stage's generation stamp (D-046).
	"CoreArtifactValidator": true,
	// The branch is Infrahub's own: its point of origin is the branch point stage's
	// `at`, and only Infrahub can say where a branch began.
	"Branch": true,
	// The event log is Infrahub's record of a write, not the operator's model: a removal
	// moves no stamp, and its event is when intent last changed (D-048). An event's kind
	// is read only to be mapped to a generic through the schema's used_by, never queried.
	"InfrahubEvent": true,
}

// Fylgja reads from Infrahub and never writes to it (Constitution III). Proving
// every operation the generated client can send is a query proves the whole product
// read-only. This needs no running Infrahub: it inspects what was generated.
func TestEveryOperationIsAQuery(t *testing.T) {
	keyword := regexp.MustCompile(`(?m)^\s*(query|mutation|subscription)\b`)
	for name, doc := range operations() {
		found := false
		for _, m := range keyword.FindAllStringSubmatch(doc, -1) {
			found = true
			if m[1] != "query" {
				t.Errorf("operation %s contains a %s: Fylgja must only read from Infrahub", name, m[1])
			}
		}
		if !found {
			t.Errorf("operation %s declares no operation type", name)
		}
		if strings.Contains(strings.ToLower(doc), "mutation") {
			t.Errorf("operation %s mentions a mutation", name)
		}
	}
}

// Queries name generics, never concrete kinds (Constitution III). A query that reached
// past the generic would mean the contract is under-specified — the fix is the
// contract, not the query.
func TestQueriesNameOnlyGenerics(t *testing.T) {
	// Concrete kinds from the reference schema. If a query mentions one, it has
	// reached past the contract.
	concrete := []string{"NetworkDevice", "NetworkInterface", "NetworkLink", "NetworkPlatform"}
	for name, doc := range operations() {
		for _, kind := range concrete {
			if strings.Contains(doc, kind) {
				t.Errorf("operation %s names the concrete kind %s", name, kind)
			}
		}
	}
}

// Every root an operation selects is a Fylgja generic, or one of the four roots that
// are Infrahub's own, named in infrahubRoots. The check above catches the reference
// schema's kinds by name; this one catches any root that is not ours, including a
// concrete kind from a model Fylgja has never seen.
func TestQueryRootsAreFylgjaGenerics(t *testing.T) {
	for name, doc := range operations() {
		roots := queryRoots(doc)
		if len(roots) == 0 {
			t.Errorf("operation %s selects no root", name)
		}
		for _, r := range roots {
			if !strings.HasPrefix(r, "Fylgja") && !infrahubRoots[r] {
				t.Errorf("operation %s selects the root %s, which is not a Fylgja generic", name, r)
			}
		}
	}
}

// The exceptions are exactly the four, each selected by the operation that needs it:
// widening the list is a change to Constitution III, not to this file.
func TestQueryRootExceptionsAreNamed(t *testing.T) {
	want := map[string]string{
		"CoreProposedChange":    "ProposedChanges",
		"CoreArtifactValidator": "ArtifactValidations",
		"Branch":                "BranchPoint",
		"InfrahubEvent":         "IntentEvents",
	}
	if len(infrahubRoots) != len(want) {
		t.Errorf("infrahubRoots names %d roots, want the four %v", len(infrahubRoots), want)
	}
	ops := operations()
	for root, op := range want {
		if !infrahubRoots[root] {
			t.Errorf("%s is not among the named exceptions", root)
		}
		if !slices.Contains(queryRoots(ops[op]), root) {
			t.Errorf("operation %s does not select %s", op, root)
		}
	}
}

// queryRoots returns the top-level selections of every `query` block in a generated
// operation document. Fragment blocks are skipped deliberately: a fragment's own
// top-level selections are fields of the type it is declared `on`, and that type is
// checked where the fragment is spread.
func queryRoots(doc string) []string {
	var roots []string
	inQuery := false
	for _, line := range strings.Split(doc, "\n") {
		switch {
		case strings.HasPrefix(line, "query "), strings.HasPrefix(line, "query{"):
			inQuery = true
		case strings.HasPrefix(line, "}"):
			inQuery = false
		case inQuery && strings.HasPrefix(line, "\t") && !strings.HasPrefix(line, "\t\t"):
			field := strings.TrimLeft(line, "\t")
			if strings.HasPrefix(field, "}") {
				continue
			}
			if i := strings.IndexAny(field, " ({"); i >= 0 {
				field = field[:i]
			}
			if field != "" {
				roots = append(roots, field)
			}
		}
	}
	return roots
}
