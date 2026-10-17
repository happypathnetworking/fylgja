// Package stages holds a proposed change's stages (014, D-045): the moments of a proposed
// change that a twin is built from, planned through and stepped along. Every proposed
// change has two derived stages, the branch point (the default branch pinned at the
// source branch's branched_from) and the head (the source branch pinned one microsecond
// after its latest stamp or intent event), and between them the operator's marks,
// FylgjaStage objects ordered by their `at`. The package holds the reference syntax, the
// order with its ends derived, every resolution rule and its refusal, the staleness rule
// (D-046, D-048), the list, the plan and the step's target.
//
// A stage is read, never written: the product's every request to Infrahub is a query
// (Constitution III). It resolves on the server, before any run starts and before any
// branch's intent is read, and the run it starts is the pinned create; nothing of the
// stage enters a CTM or a bundle.
package stages

import (
	"fmt"
	"regexp"
	"strings"
)

// The reference syntax <branch>/<label>.
const (
	// BranchPattern is a source branch as a reference names one: no "/" and no
	// whitespace, so a reference is one shell word.
	BranchPattern = `^[^/\s]+$`
	// LabelPattern is a mark's label. It equals the regex the kind enforces at write
	// (schema/fylgja-stage.yaml), and a test holds the two equal, so the command line
	// refuses exactly what Infrahub would.
	LabelPattern = `^[^/\s]+$`
	// BranchForm is how a refusal names a branch, the same words in Form and in the
	// refusal of stage list's and stage plan's --branch.
	BranchForm = `a branch with no "/" and no whitespace`
	// Form is how a refusal names the syntax, the same words wherever a reference is
	// refused.
	Form = `<branch>/<label>, ` + BranchForm + ` and a label with neither`
)

// The labels of the two derived stages. Infrahub accepts a mark labelled either; Fylgja
// refuses one wherever stages are listed or resolved (stage.label.reserved), and the
// reference keeps naming the derived stage.
const (
	// LabelBranchPoint names the branch point: the default branch pinned at the source
	// branch's branched_from.
	LabelBranchPoint = "branch-point"
	// LabelHead names the head: the source branch pinned one microsecond after the later
	// of its latest stamp and its latest intent event (D-048).
	LabelHead = "head"
)

var (
	branchRE = regexp.MustCompile(BranchPattern)
	labelRE  = regexp.MustCompile(LabelPattern)
)

// Ref names one stage: the proposed change by its source branch, then the label.
type Ref struct {
	Branch string
	Label  string
}

// String is the reference as an operator writes it: change-1/cabled, change-1/head.
func (r Ref) String() string { return r.Branch + "/" + r.Label }

// Derived reports whether the reference names one of the two derived stages.
func (r Ref) Derived() bool { return reserved(r.Label) }

// reserved reports whether a label names a derived stage.
func reserved(label string) bool { return label == LabelBranchPoint || label == LabelHead }

// ParseRef reads --stage's value, split at its first "/". Anything but one branch and
// one label, each one shell word, is refused with contracts/stage-reference.md's
// stage.ref.invalid sentence, which names the form; the caller files it before any
// connection. A second "/" goes to the label, whose pattern refuses it.
func ParseRef(s string) (Ref, error) {
	branch, label, ok := strings.Cut(s, "/")
	if ok && branchRE.MatchString(branch) && labelRE.MatchString(label) {
		return Ref{Branch: branch, Label: label}, nil
	}
	return Ref{}, fmt.Errorf("--stage %q is not a stage reference: expected %s", s, Form)
}

// CheckBranch reads --branch's value on stage list and stage plan: a branch as the
// reference names one. Anything else is refused in the shape of ParseRef's sentence,
// naming the form of a branch; the caller files it as stage.ref.invalid before any
// connection.
func CheckBranch(b string) error {
	if branchRE.MatchString(b) {
		return nil
	}
	return fmt.Errorf("--branch %q is not a branch: expected %s", b, BranchForm)
}
