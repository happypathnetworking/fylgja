package intent

import (
	"context"
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Conformance reports whether a branch implements the contract Fylgja was built
// against, and describes what was verified when it does.
type Conformance struct {
	// Version is the contract version the branch declares.
	Version string
	// SchemaHash identifies the branch's schema state.
	SchemaHash string
	// Generics lists each required generic with the kinds implementing it, by name,
	// then ctm.ArtifactTargetGeneric's row, so the device kinds' artifact targets show
	// beside them (M5).
	// Not a count: `schema check` has to show an operator which of their own kinds
	// satisfies the contract, and a number cannot.
	Generics []findings.GenericKinds
}

// CheckConformance verifies the branch before any intent is read.
//
// Schema metadata is read first, over REST. That ordering is not incidental: on a
// branch with no Fylgja schema the generics do not exist as GraphQL types at all, so
// querying them yields "cannot query field FylgjaContract" — a transport error naming
// nothing an operator can act on. The schema endpoint answers the same question and
// can name the missing generic, which is what the contract requires.
//
// Only a version mismatch short-circuits: against a contract Fylgja does not
// understand, a list of findings would mislead rather than help. A branch
// that has no FylgjaContract at all is a different case — there is no rival contract
// to misread, so the missing node and every unimplemented generic are reported
// together, which is what an operator setting a branch up needs to see.
func (c *Client) CheckConformance(ctx context.Context) (*Conformance, findings.List, error) {
	var list findings.List

	info, err := c.SchemaInfo(ctx)
	if err != nil {
		return nil, nil, err
	}
	conf := &Conformance{SchemaHash: info.Hash}

	switch {
	case !info.Kinds[ctm.ContractKind]:
		list.Add(findings.Rejection, findings.RuleContractNodeMissing, c.cfg.Branch, fmt.Sprintf(
			"branch declares no %s; it does not implement Fylgja's generics contract", ctm.ContractKind))
	default:
		version, present, err := c.ContractVersion(ctx)
		if err != nil {
			return nil, nil, err
		}
		switch {
		case !present:
			list.Add(findings.Rejection, findings.RuleContractNodeMissing, c.cfg.Branch, fmt.Sprintf(
				"branch defines %s but holds no instance of it", ctm.ContractKind))
		case version != ctm.ContractVersion:
			// Reported alone: every other finding would be about a model this build
			// cannot interpret, so listing them beside this one would be noise
			// dressed as detail.
			var only findings.List
			only.Add(findings.Rejection, findings.RuleContractVersionMismatch, c.cfg.Branch, fmt.Sprintf(
				"branch declares contract version %q, this build understands %q", version, ctm.ContractVersion))
			return conf, only, nil
		default:
			conf.Version = version
		}
	}

	for _, generic := range ctm.RequiredGenerics {
		kinds := info.Implementers(generic)
		conf.Generics = append(conf.Generics, findings.GenericKinds{Generic: generic, Kinds: kinds})
		if len(kinds) == 0 {
			// Naming the generic is the whole point of reading the schema endpoint
			// rather than letting a query fail: a transport error cannot say this.
			list.Add(findings.Rejection, findings.RuleGenericUnimplemented, generic,
				"no concrete kind implements this generic on the branch")
		}
	}

	// Contract 0.2: a device kind that is not an artifact target can have no
	// configuration rendered for it, so every one of its devices would be refused
	// artifact.missing — one finding per device, none naming the cause. Naming the kind
	// here, before any data is read, says the one thing to fix. The row beside the
	// generics shows `schema check`'s reader which of their kinds carry artifacts.
	targets := info.Implementers(ctm.ArtifactTargetGeneric)
	conf.Generics = append(conf.Generics, findings.GenericKinds{Generic: ctm.ArtifactTargetGeneric, Kinds: targets})
	isTarget := map[string]bool{}
	for _, k := range targets {
		isTarget[k] = true
	}
	for _, kind := range info.Implementers(ctm.DeviceGeneric) {
		if !isTarget[kind] {
			list.Add(findings.Rejection, findings.RuleSchemaArtifactTargetMissing, kind, fmt.Sprintf(
				"kind %s implements %s but does not inherit %s, so its devices can carry no configuration artifact",
				kind, ctm.DeviceGeneric, ctm.ArtifactTargetGeneric))
		}
	}
	return conf, list, nil
}
