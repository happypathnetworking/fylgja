package intent

import (
	"context"
	"fmt"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Conformance describes what a conformance check verified: the branch's schema hash, the
// model and commit the mapping's table was written against, and every kind and field of
// the table, which a clean check found the branch to hold as the commit has them.
type Conformance struct {
	// SchemaHash identifies the branch's schema state.
	SchemaHash string
	// Model and Version name the schema library and its commit (LibraryModel,
	// LibraryVersion).
	Model, Version string
	// Kinds are the table's kinds with their fields, in its order. Not a count:
	// `schema check` has to show an operator which of their kinds and fields the reader
	// reads, and a number cannot.
	Kinds []findings.KindFields
}

// CheckConformance compares the branch's schema with the mapping's table (mapping.go)
// before any intent is read (Constitution III; FR-011–FR-013).
//
// Schema metadata is read over REST, not inferred from a failed query: on a branch
// without the library a query of its kinds fails as "cannot query field", a transport
// error naming nothing an operator can act on, while the schema endpoint answers which
// kind, which field and which property differs.
//
// Every finding is a rejection naming the commit, and all of them come in one pass, so
// one run shows an operator setting a branch up everything that differs (SC-004). A kind
// absent is named once: its fields, and the generics it should implement, are not named
// again beside it, since each would be a second account of the one fault. Nothing beyond
// the table is reported.
func (c *Client) CheckConformance(ctx context.Context) (*Conformance, findings.List, error) {
	info, err := c.SchemaInfo(ctx)
	if err != nil {
		return nil, nil, err
	}
	conf := &Conformance{SchemaHash: info.Hash, Model: LibraryModel, Version: LibraryVersion}
	for _, k := range LibraryTables {
		conf.Kinds = append(conf.Kinds, findings.KindFields{Kind: k.Kind, Fields: k.Fields()})
	}
	return conf, conformanceFindings(info), nil
}

// ConformanceError says a branch's schema does not hold what the mapping reads, found
// before a stamps read of the branch: the stamps' queries select the library's kinds, and
// on such a branch they fail as a GraphQL error naming nothing of the mapping's table
// (017). Findings are CheckConformance's, every one in one pass; the stages file them as
// the command's refusal, exit 1, as they file StageKindError stage.kind.absent.
type ConformanceError struct {
	Branch   string
	Findings findings.List
}

// Error names the branch, the commit and each finding's rule and object.
func (e *ConformanceError) Error() string {
	what := make([]string, len(e.Findings))
	for i, f := range e.Findings {
		what[i] = f.Rule + " " + f.Object
	}
	return fmt.Sprintf("branch %s does not conform to %s@%s: %s", e.Branch, LibraryModel, LibraryVersion, strings.Join(what, ", "))
}

// readsIt ends every conformance finding but used_by's, which says what the mapping reads
// through the generic: the commit is what an operator compares their own schema with.
const (
	asTheLibrary = "as " + LibraryModel + "@" + LibraryVersion + " has it"
	readsIt      = "; the mapping reads it " + asTheLibrary
)

// conformanceFindings walks the table against one branch's schema.
func conformanceFindings(info *SchemaInfo) findings.List {
	var list findings.List
	reject := func(rule, object, message string) {
		list.Add(findings.Rejection, rule, object, message)
	}
	absent := map[string]bool{}
	for _, k := range LibraryTables {
		node, ok := info.Nodes[k.Kind]
		if !ok {
			absent[k.Kind] = true
			reject(findings.RuleSchemaKindMissing, k.Kind, "the branch's schema has no kind "+k.Kind+readsIt)
			continue
		}
		for _, want := range k.Attributes {
			field := k.Kind + "." + want.Name
			got, ok := node.Attributes[want.Name]
			if !ok {
				reject(findings.RuleSchemaFieldMissing, field, k.Kind+" has no attribute "+want.Name+readsIt)
				continue
			}
			if differs := attributeDiffers(want, got); differs != "" {
				reject(findings.RuleSchemaFieldMismatch, field, differs+readsIt)
				continue
			}
			for _, choice := range want.Choices {
				if !slices.Contains(got.Choices, choice) {
					reject(findings.RuleSchemaChoiceMissing, field, "the dropdown has no choice "+choice+readsIt)
				}
			}
		}
		for _, want := range k.Relationships {
			field := k.Kind + "." + want.Name
			got, ok := node.Relationships[want.Name]
			if !ok {
				reject(findings.RuleSchemaFieldMissing, field, k.Kind+" has no relationship "+want.Name+readsIt)
				continue
			}
			if differs := relationshipDiffers(want, got); differs != "" {
				reject(findings.RuleSchemaFieldMismatch, field, differs+readsIt)
			}
		}
	}
	for _, want := range LibraryUsedBy {
		if absent[want.Implementer] || slices.Contains(info.UsedBy[want.Generic], want.Implementer) {
			continue
		}
		through := "; the mapping reads " + want.Implementer + " through it " + asTheLibrary
		if _, defined := info.UsedBy[want.Generic]; !defined {
			reject(findings.RuleSchemaUsedByMissing, want.Generic, "the branch's schema has no generic "+want.Generic+through)
			continue
		}
		reject(findings.RuleSchemaUsedByMissing, want.Generic, want.Implementer+" does not implement "+want.Generic+through)
	}
	return list
}

// attributeDiffers names each property of an attribute that is not the table's, expected
// first: `kind Text, found Number`, joined by "; " when more than one differs. A required attribute must read optional false; one
// the table leaves optional may read either.
func attributeDiffers(want AttributeWant, got AttributeSchema) string {
	var d differences
	d.compare("kind", want.Kind, got.Kind)
	if want.Required && got.Optional {
		d.compare("optional", "false", "true")
	}
	return strings.Join(d, "; ")
}

// relationshipDiffers names each property of a relationship that is not the table's.
func relationshipDiffers(want RelationshipWant, got RelationshipSchema) string {
	var d differences
	d.compare("peer", want.Peer, got.Peer)
	d.compare("kind", want.Kind, got.Kind)
	d.compare("cardinality", want.Cardinality, got.Cardinality)
	if want.Required && got.Optional {
		d.compare("optional", "false", "true")
	}
	return strings.Join(d, "; ")
}

// differences collects a field's differing properties, so one field is one finding
// however many of its properties differ.
type differences []string

func (d *differences) compare(property, want, got string) {
	if want != got {
		*d = append(*d, fmt.Sprintf("%s %s, found %s", property, want, got))
	}
}
