package intent

import (
	"regexp"
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
		// M10: a Fylgja-owned concrete kind read from the default branch, as
		// FylgjaContract is; its root is Fylgja's, so the root check holds it too.
		"Waypoints": Waypoints_Operation,
	}
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

// Every root an operation selects is a Fylgja generic. The check above catches the
// reference schema's kinds by name; this one catches any root that is not ours,
// including a concrete kind from a model Fylgja has never seen.
func TestQueryRootsAreFylgjaGenerics(t *testing.T) {
	for name, doc := range operations() {
		roots := queryRoots(doc)
		if len(roots) == 0 {
			t.Errorf("operation %s selects no root", name)
		}
		for _, r := range roots {
			if !strings.HasPrefix(r, "Fylgja") {
				t.Errorf("operation %s selects the root %s, which is not a Fylgja generic", name, r)
			}
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
