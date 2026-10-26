package intent

import (
	"regexp"
	"slices"
	"strings"
	"testing"
)

// operations is every GraphQL document this package can send. The generated client is
// the only thing that talks to Infrahub in the product, so this map is the whole
// surface the tests below have to cover.
func operations() map[string]string {
	return map[string]string{
		// 017: the read, by the mapping (contracts/mapping.md §2).
		"Devices": Devices_Operation,
		"Ports":   Ports_Operation,
		// 014: the stage reader's five, on the default branch, and the branch's stamps.
		// FylgjaStage's root is Fylgja's; it and the other four are ownedRoots below.
		"ProposedChanges":     ProposedChanges_Operation,
		"OrphanStages":        OrphanStages_Operation,
		"BranchPoint":         BranchPoint_Operation,
		"ArtifactValidations": ArtifactValidations_Operation,
		"IntentEvents":        IntentEvents_Operation,
		"IntentStamps":        IntentStamps_Operation,
		"PortStamps":          PortStamps_Operation,
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

// mappingRoots are the read's two roots, the library's kinds the mapping reads devices and
// ports from (D-057; contracts/mapping.md §2), each with the operations that select it: the
// read's and the stamps', which are shaped like it (017 research R-10).
var mappingRoots = map[string][]string{
	"DcimDevice":        {"Devices", "IntentStamps"},
	"InterfacePhysical": {"Ports", "PortStamps"},
}

// ownedRoot is a root that is not the operator's model of the network: the operation that
// selects it, and why reading it reserves no structure of theirs.
type ownedRoot struct{ operation, reason string }

// ownedRoots are the five roots an operation may select beside the mapping's: Fylgja's own
// stage kind, and four of Infrahub's own units, which nobody implements (Constitution III,
// 2.0.0). Each is named; anything else is refused.
var ownedRoots = map[string]ownedRoot{
	"FylgjaStage": {"OrphanStages",
		"Fylgja's own kind, a moment of a proposed change, the one kind Fylgja loads (D-045); " +
			"read alone for the stages whose proposed change no longer names them (D-047)"},
	"CoreProposedChange": {"ProposedChanges",
		"Infrahub's unit of review and the stage's home (D-045): a stage is a moment of one, found by its source branch"},
	"CoreArtifactValidator": {"ArtifactValidations",
		"Infrahub's own check of a proposed change's artifacts: its completion is half of a stage's generation stamp (D-046)"},
	"Branch": {"BranchPoint",
		"Infrahub's own: its point of origin is the branch point stage's at, and only Infrahub can say where a branch began"},
	"InfrahubEvent": {"IntentEvents",
		"Infrahub's record of a write, not the operator's model: a removal moves no stamp, and its event is when " +
			"intent last changed (D-048); an event's kind is read only to be mapped through the schema's used_by, never queried"},
}

// Every root an operation selects is one of the mapping's, selected by an operation that
// reads it, or one of the five owned roots, selected by its own operation; and each of them is
// selected where it is named. A kind of the operator's model beyond the mapping's, or any
// other root, fails here (FR-001, SC-002): widening either list is a change to the mapping
// and to Constitution III, not to this file.
func TestQueryRootsAreTheMappings(t *testing.T) {
	ops := operations()
	for name, doc := range ops {
		roots := queryRoots(doc)
		if len(roots) == 0 {
			t.Errorf("operation %s selects no root", name)
		}
		for _, r := range roots {
			if readers, ok := mappingRoots[r]; ok {
				if !slices.Contains(readers, name) {
					t.Errorf("operation %s selects the mapping's root %s, which only %v read", name, r, readers)
				}
				continue
			}
			owned, ok := ownedRoots[r]
			switch {
			case !ok:
				t.Errorf("operation %s selects the root %s, which is neither the mapping's nor one of the named owned roots", name, r)
			case owned.operation != name:
				t.Errorf("operation %s selects the owned root %s, which only %s reads (%s)", name, r, owned.operation, owned.reason)
			}
		}
	}
	for root, readers := range mappingRoots {
		for _, op := range readers {
			if !slices.Contains(queryRoots(ops[op]), root) {
				t.Errorf("operation %s does not select the mapping's root %s", op, root)
			}
		}
	}
	for root, owned := range ownedRoots {
		if owned.reason == "" {
			t.Errorf("the owned root %s is named with no reason", root)
		}
		if !slices.Contains(queryRoots(ops[owned.operation]), root) {
			t.Errorf("operation %s does not select %s", owned.operation, root)
		}
	}
}

// fragmentTargets are the types a fragment may be declared on or an inline fragment may
// narrow to: the mapping's four kinds of the operator's model (FR-001; mapping.md §2), and
// two of Infrahub's own, each with its reason.
var fragmentTargets = map[string]string{
	"DcimDevice":        "the mapping's device",
	"DcimPlatform":      "the mapping's platform, which carries its manufacturer",
	"InterfacePhysical": "the mapping's port, and a cable's end on one",
	"DcimCable":         "the mapping's cable, reached through a port's connector",
	"CoreArtifactTarget": "Infrahub's own target of an artifact, which nobody implements but the device kind " +
		"conformance holds to inherit it (mapping.md §3)",
	"NodeMutatedEvent": "Infrahub's own event type, whose attributes and relationships tell intent from churn (D-048)",
}

// Every fragment's type condition, named (`fragment … on T`) or inline (`... on T`), is one
// of fragmentTargets. A fragment is how an operation names a kind without selecting it as a
// root, so a fifth kind of the operator's model reached that way fails here (SC-002). Each
// of Infrahub's two is a condition some operation uses.
func TestFragmentTargetsAreTheMappings(t *testing.T) {
	condition := regexp.MustCompile(`(?:\bfragment\s+\w+|\.\.\.)\s+on\s+(\w+)`)
	used := map[string]bool{}
	for name, doc := range operations() {
		for _, m := range condition.FindAllStringSubmatch(doc, -1) {
			used[m[1]] = true
			if _, ok := fragmentTargets[m[1]]; !ok {
				t.Errorf("operation %s has a fragment on %s, which is neither one of the mapping's kinds nor a named one of Infrahub's", name, m[1])
			}
		}
	}
	for _, owned := range []string{"CoreArtifactTarget", "NodeMutatedEvent"} {
		if !used[owned] {
			t.Errorf("no operation has a fragment on %s, named among the targets (%s)", owned, fragmentTargets[owned])
		}
	}
}

// filterRead is a kind an operation reads by one filter argument alone, never selecting it:
// the filter, the operations that pass it, and why.
type filterRead struct {
	filter     string
	operations []string
	reason     string
}

// filterReads are the kinds read by a filter alone. BuiltinTag is Infrahub's own: the scope's
// tag, matched by its name on the mapping's device root, the read's and the stamps'
// (FR-001; Constitution III; 017 research R-04). No tag is ever a root, a fragment's target
// or a selection.
var filterReads = map[string]filterRead{
	"BuiltinTag": {"tags__name__value", []string{"Devices", "IntentStamps"},
		"Infrahub's own tag, the scope's: a device is in the scope tag:<name> when it carries the tag of that name"},
}

// Each filter read is named nowhere but by its filter, and only by the operations named
// beside it: no operation names the kind, selects a tags field, or filters by a tag but these.
func TestTheTagIsReadByItsFilterAlone(t *testing.T) {
	tags := regexp.MustCompile(`\btags\w*`)
	for kind, read := range filterReads {
		for name, doc := range operations() {
			if strings.Contains(doc, kind) {
				t.Errorf("operation %s names %s, which is read by its filter %s alone (%s)", name, kind, read.filter, read.reason)
			}
			found := tags.FindAllString(doc, -1)
			for _, f := range found {
				if f != read.filter {
					t.Errorf("operation %s reads %s, where a tag is read by %s alone", name, f, read.filter)
				}
			}
			if passes := slices.Contains(found, read.filter); passes != slices.Contains(read.operations, name) {
				t.Errorf("operation %s passes %s: %t; want it passed by %v alone", name, read.filter, passes, read.operations)
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
