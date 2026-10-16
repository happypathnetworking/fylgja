package stages

import (
	"context"
	"fmt"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// remedy names both ways to regenerate a proposed change's artifacts (D-046).
const remedy = "regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's checks: " +
	"a retry in Infrahub, or CoreProposedChangeRunCheck)"

// Stale is step 8, the staleness rule as D-046 states it: at the stage's at, each device
// is stale when the latest stamp of its own intent is later than its generation stamp, the
// later of its artifact's checksum.updated_at and the proposed change's artifact
// validator's completed_at. The artifact is the one named by the device's package's
// config.artifact_name, the package found in the registry by the device's platform
// (Constitution II). One stage.artifact.stale per stale device, sorted by name, each a
// rejection at step resolve naming the device.
//
// The stamps are read on the stage's branch pinned at its at (the default branch for the
// branch point); the head's are the branch's unpinned stamps its at was computed from
// (research R-06). The validator is read pinned at the stage's at, and only when some
// device's checksum alone leaves it stale. For the head it is read unpinned: its
// completion is no stamp of the branch and never enters the head's at (R-06), so pinned at
// the head a run-check that regenerated identical bytes would never count, and the head
// would stay stale with no remedy, the hole D-046 closes.
//
// A device whose package this build lacks, or which carries no artifact of its package's
// name, is the read's to refuse (platform.unsupported, artifact.missing), not stale; so is
// one whose artifact says nothing of when it was generated.
func Stale(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, st Resolved) (findings.List, error) {
	stamps, validatedAt := ch.head, st.At
	if st.AtSource == AtHead {
		validatedAt = ""
	} else {
		var err error
		if stamps, err = s.Stamps(ctx, st.Branch, st.At); err != nil {
			return nil, err
		}
	}

	type candidate struct {
		device, artifact, intent, checksum string
	}
	var candidates []candidate
	for name, d := range stamps.Devices {
		pkg, ok := reg.Lookup(d.Platform.NOS)
		if !ok {
			continue
		}
		checksum, ok := d.Artifacts[pkg.Config.ArtifactName]
		if !ok || d.Intent == "" {
			continue
		}
		if checksum != "" {
			later, err := laterThan(d.Intent, checksum)
			if err != nil {
				return nil, err
			}
			if !later {
				continue
			}
		}
		candidates = append(candidates, candidate{device: name, artifact: pkg.Config.ArtifactName, intent: d.Intent, checksum: checksum})
	}
	if len(candidates) == 0 {
		return nil, nil
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].device < candidates[j].device })

	validated, err := r.Validations(ctx, st.ProposedChange.ID, validatedAt)
	if err != nil {
		return nil, err
	}
	var list findings.List
	for _, c := range candidates {
		generated := c.checksum
		if validated != "" {
			if generated == "" {
				generated = validated
			} else if later, err := laterThan(validated, generated); err != nil {
				return nil, err
			} else if later {
				generated = validated
			}
		}
		if generated == "" {
			continue // nothing says when it was generated: the read judges the artifact
		}
		later, err := laterThan(c.intent, generated)
		if err != nil {
			return nil, err
		}
		if !later {
			continue
		}
		checksum := "its checksum unstamped"
		if c.checksum != "" {
			checksum = "checksum stamped " + c.checksum
		}
		validator := "no artifact validator of the proposed change had completed"
		if validated != "" {
			validator = "the proposed change's artifact validator last completed " + validated
		}
		list = append(list, refusal(findings.RuleStageArtifactStale, c.device, fmt.Sprintf(
			"device %s: its intent on %s was written at %s, later than its artifact %s was generated (%s; %s): %s",
			c.device, st.Branch, c.intent, c.artifact, checksum, validator, staleTail(st))))
	}
	return list, nil
}

// staleTail says what a stale stage is and what to do, by the kind of stage.
func staleTail(st Resolved) string {
	switch st.AtSource {
	case AtHead:
		return fmt.Sprintf("the head of %s is later than the artifacts' last regeneration; %s", st.Ref.Branch, remedy)
	case AtBranchPoint:
		return fmt.Sprintf("stage %s reads %s as it was at the branch point, before its artifacts were regenerated", st.Ref, st.Branch)
	}
	return fmt.Sprintf("stage %s was marked before the artifacts were regenerated; %s and mark again", st.Ref, remedy)
}

// laterThan reports whether stamp a is later than stamp b, both as Infrahub returned them.
func laterThan(a, b string) (bool, error) {
	ta, ok := ParseAt(a)
	if !ok {
		return false, fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", a)
	}
	tb, ok := ParseAt(b)
	if !ok {
		return false, fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", b)
	}
	return ta.After(tb), nil
}

// MainMoved is step 9: the warning stage.main.moved when the destination's latest stamp,
// read unpinned as the head's is, is later than the branch's branched_from (FR-012). It
// refuses nothing: the branch point still reads the destination as it was then. The
// destination's stamps are read once per proposed change.
func (c *Change) MainMoved(ctx context.Context, s Stamper) (findings.List, error) {
	if c.main == nil {
		stamps, err := s.Stamps(ctx, c.ProposedChange.Destination, "")
		if err != nil {
			return nil, err
		}
		c.main = &stamps
	}
	return mainMoved(c, *c.main), nil
}

// mainMoved compares the destination's stamps with the branch point.
func mainMoved(c *Change, main intent.Stamps) findings.List {
	latest, ok := ParseAt(main.Latest)
	if main.Latest == "" || !ok {
		return nil
	}
	branched, ok := ParseAt(c.BranchedFrom)
	if !ok || !latest.After(branched) {
		return nil
	}
	b, dest := c.ProposedChange.Branch, c.ProposedChange.Destination
	return findings.List{{Severity: findings.Warning, Rule: findings.RuleStageMainMoved, Object: b, Step: findings.StepResolve,
		Message: fmt.Sprintf("%s has moved since %s's branch point: its latest write is %s, the branch point %s; "+
			"the branch point stage still reads %s as it was then, and nothing is refused", dest, b, main.Latest, c.BranchedFrom, dest)}}
}
