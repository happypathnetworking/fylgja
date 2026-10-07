// Package stage holds the read and compile stages as pure-Go pipelines, shared by the
// stage commands (`intent read`, `twin compile`), the provisioning activities that run
// them inside a run, and the dry run. One implementation means a create that stops at
// read or compile reports exactly what the stage command would, under the same
// identifiers (Constitution V).
//
// It knows nothing of Temporal, and nothing here writes a file: callers decide where a
// CTM or a bundle goes.
package stage

import (
	"context"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// ReadTimeout bounds one whole read. Generous: a large branch pages.
const ReadTimeout = 5 * time.Minute

// ObservedAtFormat is the envelope's observed_at: UTC, six fractional digits, always the
// same width. Six because that is the precision Infrahub honours, so an observed_at can be
// handed back as --at without tripping the precision rule. Fixed width keeps
// CTM diffs aligned.
const ObservedAtFormat = "2006-01-02T15:04:05.000000Z"

// Read reads a branch into a validated CTM: conformance, fetch, then the same rules
// twin compile runs, all findings in one pass. A rejection returns a nil CTM
// with the findings; an error means the read could not run at all (Infrahub unreachable,
// its address or credential unset). observedAt is stamped by the caller before this is
// called, so it is never later than anything the read could have seen.
func Read(ctx context.Context, branch, at string, reg *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error) {
	cfg, err := intent.FromEnv(branch, at)
	if err != nil {
		return nil, nil, err
	}
	client := intent.New(cfg)

	ctx, cancel := context.WithTimeout(ctx, ReadTimeout)
	defer cancel()

	// Conformance first, over the schema endpoint: on a branch without Fylgja's schema
	// the generics are not GraphQL types at all, so a query would fail naming nothing an
	// operator can act on.
	conf, list, err := client.CheckConformance(ctx)
	if err != nil {
		return nil, nil, err
	}
	if list.Rejected() {
		return nil, list, nil
	}

	snapshot, artifactFindings, err := client.Fetch(ctx, conf, observedAt, reg)
	if err != nil {
		return nil, nil, err
	}
	list = append(list, artifactFindings...)

	// The same rules twin compile runs, on the same shape: a CTM that reads clean compiles.
	list = append(list, dedupe(validate.Validate(snapshot, reg), list)...)
	if list.Rejected() {
		return nil, list, nil
	}
	return snapshot, list, nil
}

// dedupe drops from add every finding about something have already named.
//
// A read that finds no artifact for a device says so twice: once from the read, which
// knows the artifact's name and the branch it looked on, and once from validation,
// which sees only that the CTM's device carries no artifact. Both are `artifact.missing`
// against the same device and both are right, but one fault must name a device once —
// the rule M4's convergence settled for the check's repeated host findings. The read's
// is kept, because it is the one with Infrahub in hand: it says which artifact was
// looked for and where.
//
// The key is severity, rule and object, deliberately not the message. The two wordings
// differ on purpose and must: validation's is what `twin compile` prints about a file,
// where "on branch b" would be a claim about an Infrahub the compile never asked. A
// second message under one rule about one object is a second account of one fault, and
// the read's account is the actionable one.
//
// One more pair is the same fault under two rules. A device the read refused for any
// reason — not_ready, ambiguous, a checksum that did not match — reaches validation with
// no artifact, and validation names it artifact.missing: true of the CTM, but only because
// the read refused, and the read's rule is the cause an operator can fix. So validation's
// artifact.missing is dropped for every device the read named under an artifact rule.
//
// Nothing else collides. Two devices with the same fault differ in object; a device with
// two faults differs in rule; and what validation adds that the read could not know —
// completeness, mapping, the envelope — is never a repeat and always appears.
func dedupe(add, have findings.List) findings.List {
	if len(have) == 0 {
		return add
	}
	type key struct{ severity, rule, object string }
	seen := make(map[key]bool, len(have))
	refused := map[string]bool{}
	for _, f := range have {
		seen[key{string(f.Severity), f.Rule, f.Object}] = true
		if strings.HasPrefix(f.Rule, artifactRules) {
			refused[f.Object] = true
		}
	}
	out := make(findings.List, 0, len(add))
	for _, f := range add {
		if seen[key{string(f.Severity), f.Rule, f.Object}] {
			continue
		}
		if f.Rule == findings.RuleArtifactMissing && refused[f.Object] {
			continue
		}
		out = append(out, f)
	}
	return out
}

// artifactRules prefixes every rule the read raises about a device's artifact
// (internal/findings).
const artifactRules = "artifact."

// CheckContract rejects a CTM conforming to a contract this build does not understand,
// naming object as the thing at fault. It is reported alone: every other finding would
// be about a model this build cannot interpret.
func CheckContract(c *ctm.CTM, object string) findings.List {
	if c.Envelope.ContractVersion == ctm.ContractVersion {
		return nil
	}
	var list findings.List
	list.Add(findings.Rejection, findings.RuleContractVersionMismatch, object,
		"CTM declares contract version "+c.Envelope.ContractVersion+
			", this build understands "+ctm.ContractVersion)
	return list
}

// Compile turns a CTM into a bundle's files and identity. Validation runs first and its
// rejections stop everything, so a bundle is never built from intent that could not be
// built faithfully. On a rejection files is nil and id empty. The id is computed
// from the bytes before anything is written, so it describes what was compiled.
//
// The contract check names the CTM's branch; `twin compile` runs CheckContract itself
// first, naming the file it was given.
func Compile(c *ctm.CTM, reg *psp.Registry) (files map[string][]byte, id string, list findings.List) {
	if list := CheckContract(c, c.Envelope.Branch); list.Rejected() {
		return nil, "", list
	}
	if list := validate.Validate(c, reg); list.Rejected() {
		return nil, "", list
	}
	files, list = compiler.Compile(c, reg)
	if list.Rejected() {
		return nil, "", list
	}
	return files, bundle.ID(files), list
}
