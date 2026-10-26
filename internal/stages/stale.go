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

// Stale is step 8, the staleness rule as D-046 states it and D-048 widens it: at the
// stage's at, each device is stale when its intent was written later than its generation
// stamp, the later of its artifact's checksum.updated_at and the proposed change's
// artifact validator's completed_at. Its intent was written at the later of the latest
// stamp of its own intent and the latest intent event that names it, no later than the
// stage's at: a removal moves no stamp, and its event is how it is seen. The artifact is
// the one named by the device's package's config.artifact_name, the package found in the
// registry by the device's manufacturer and platform pair, exactly (Constitution II). One stage.artifact.stale per stale
// device, sorted by name, each a rejection at step resolve naming the device.
//
// The stamps are read on the stage's branch pinned at its at (the default branch for the
// branch point); the head's are the branch's unpinned stamps its at was computed from
// (research R-06). An event names a device when one of the ids its stamps read is its
// primary node or a peer: the device's own, its interfaces', its platform's, its
// manufacturer's or one of its cables' (017's FR-023). The events
// are the source branch's, read after the earliest checksum among the devices judged
// (every one since the branch point when one is unstamped), since only an event after a
// device's generation can make it stale; the branch point reads main before any of them
// and reads none. The validator is read pinned at the stage's at, and only when some
// device's checksum alone leaves it stale. For the head it is read unpinned: its
// completion is no stamp of the branch and never enters the head's at (R-06), so pinned at
// the head a run-check that regenerated identical bytes would never count, and the head
// would stay stale with no remedy, the hole D-046 closes.
//
// A device whose pair no package matches, or which carries no artifact of its package's
// name, is the read's to refuse (platform.missing, platform.unmatched, artifact.missing),
// not stale; so is one whose artifact says nothing of when it was generated. A stage's
// branch whose schema does not conform refuses it with its schema.* findings, before its
// stamps are read (017).
func Stale(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, st Resolved) (findings.List, error) {
	stamps, validatedAt := ch.head, st.At
	if st.AtSource == AtHead {
		validatedAt = ""
	} else {
		var err error
		if stamps, err = s.Stamps(ctx, st.Branch, st.At, ch.Scope); err != nil {
			if refused, ok := conformanceRefusal(err); ok {
				return refused, nil
			}
			return nil, err
		}
	}

	type judged struct {
		device, artifact, checksum string
		stamps                     intent.DeviceStamps
	}
	var devices []judged
	floor, unstamped := "", false
	for name, d := range stamps.Devices {
		pkg, ok := reg.Match(d.Match.Manufacturer, d.Match.Platform)
		if !ok {
			continue
		}
		checksum, ok := d.Artifacts[pkg.Config.ArtifactName]
		if !ok {
			continue
		}
		if checksum == "" {
			unstamped = true
		} else if _, ok := ParseAt(checksum); !ok {
			return nil, fmt.Errorf("the stamp %q Infrahub returned is not an RFC 3339 time", checksum)
		} else if floor == "" || later(floor, checksum) {
			floor = checksum
		}
		devices = append(devices, judged{device: name, artifact: pkg.Config.ArtifactName, checksum: checksum, stamps: d})
	}
	if len(devices) == 0 {
		return nil, nil
	}
	if unstamped {
		floor = ""
	}
	var events []intent.Event
	stageAt, timed := ParseAt(st.At)
	if st.Branch == ch.ProposedChange.Branch && timed {
		var err error
		if events, err = ch.intentEvents(ctx, r, floor); err != nil {
			return nil, err
		}
	}

	type candidate struct {
		device, artifact, intent, stamp, checksum string
		event                                     *intent.Event // the latest naming the device, when later than its stamps
	}
	var candidates []candidate
	for _, d := range devices {
		c := candidate{device: d.device, artifact: d.artifact, intent: d.stamps.Intent, stamp: d.stamps.Intent, checksum: d.checksum}
		for i := range events {
			ev := &events[i]
			at, _ := ParseAt(ev.OccurredAt)
			if at.After(stageAt) || !ev.Names(d.stamps.IDs) {
				continue
			}
			if c.intent == "" || later(ev.OccurredAt, c.intent) {
				c.intent, c.event = ev.OccurredAt, ev
			}
		}
		if c.intent == "" {
			continue
		}
		if c.checksum != "" {
			later, err := laterThan(c.intent, c.checksum)
			if err != nil {
				return nil, err
			}
			if !later {
				continue
			}
		}
		candidates = append(candidates, c)
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
		written := c.intent
		if c.event != nil {
			stamp := "no stamp of its own"
			if c.stamp != "" {
				stamp = "its latest stamp " + c.stamp
			}
			written = fmt.Sprintf("%s (Infrahub's event log: %s of a %s; %s)", c.intent, c.event.Name, c.event.Kind, stamp)
		}
		list = append(list, refusal(findings.RuleStageArtifactStale, c.device, fmt.Sprintf(
			"device %s: its intent on %s was written at %s, later than its artifact %s was generated (%s; %s): %s",
			c.device, st.Branch, written, c.artifact, checksum, validator, staleTail(st))))
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
// destination's stamps are read once per proposed change. A destination whose schema
// does not conform is refused with its schema.* findings instead, before its stamps are
// read (017), as each stamps read of it is.
func (c *Change) MainMoved(ctx context.Context, s Stamper) (findings.List, error) {
	if c.main == nil {
		stamps, err := s.Stamps(ctx, c.ProposedChange.Destination, "", c.Scope)
		if refused, ok := conformanceRefusal(err); ok {
			return refused, nil
		}
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
