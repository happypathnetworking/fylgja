package validate

import (
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Validate runs every rule against intent and returns all findings.
//
// One pass, every finding: an operator fixing a branch should see the whole list, not
// discover the next problem on the next attempt. Nothing here writes, deploys, or
// decides — the caller looks at findings.List.Rejected to decide whether to proceed.
func Validate(c *ctm.CTM, reg *psp.Registry) findings.List {
	var list findings.List
	ctm.Normalize(c)
	checkEnvelope(c, &list)
	checkDevicesPresent(c, &list)
	checkDevices(c, reg, &list)
	checkArtifacts(c, reg, &list)
	checkLinks(c, &list)
	return list
}
