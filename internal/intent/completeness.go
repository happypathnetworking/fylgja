package intent

import (
	"fmt"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// readDevice is one device the Devices query answered, flattened out of the generated
// types: its name, and its platform's pair as far as the device carries one.
type readDevice struct {
	id, name string
	// hasPlatform is whether the device has a platform at all, and hasManufacturer whether
	// that platform has a manufacturer; platform and manufacturer are their names, either
	// of which can be empty on a node that exists (queries.graphql reads each as a pointer
	// to tell the two apart).
	hasPlatform, hasManufacturer bool
	platform, manufacturer       string
	node                         deviceNode
}

// match is the device's pair, for the registry.
func (d readDevice) match() psp.Match {
	return psp.Match{Manufacturer: d.manufacturer, Platform: d.platform}
}

// ScopeEmpty refuses a read whose scope selects no device (FR-015): the tag absent from
// the branch, or on no DcimDevice, which the read does not tell apart, since telling them
// apart would read BuiltinTag itself (R-03). at is the read's, "" unpinned. The stages
// file it at resolve for a head whose stamps selected no device, in the read's words.
func ScopeEmpty(scope, branch, at string) findings.Finding {
	msg := fmt.Sprintf("scope %s selects no device on branch %s", scope, branch)
	if at != "" {
		msg += " at " + at
	}
	return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: scope, Message: msg}
}

// completeness refuses every device in the scope that no package can be chosen for, all
// in one pass and before any artifact is fetched (R-03; FR-014): one with no platform, or
// a platform with no manufacturer, is incomplete (platform.missing), and one whose pair no
// package names exactly is unmatched (platform.unmatched), a manufacturer or platform whose
// name is empty among them, since no package names an empty one (psp.matches.missing). The packages are found here, by
// the pair, so a CTM never carries a device without one. Devices are reported in name
// order, the order the CTM lists them in.
func completeness(devices []readDevice, reg *psp.Registry) (map[string]*psp.PSP, findings.List) {
	sorted := append([]readDevice(nil), devices...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].name < sorted[j].name })

	packages := map[string]*psp.PSP{}
	var list findings.List
	for _, d := range sorted {
		switch {
		case !d.hasPlatform:
			list.Add(findings.Rejection, findings.RulePlatformMissing, d.name, fmt.Sprintf(
				"device %s carries no platform; its support package is the one whose matches name its platform and manufacturer", d.name))
		case !d.hasManufacturer:
			list.Add(findings.Rejection, findings.RulePlatformMissing, d.name, fmt.Sprintf(
				"device %s carries platform %q with no manufacturer; its support package is the one whose matches name both", d.name, d.platform))
		default:
			pkg, ok := reg.Match(d.manufacturer, d.platform)
			if !ok {
				list.Add(findings.Rejection, findings.RulePlatformUnmatched, d.name, fmt.Sprintf(
					"device %s: %s; the packages match: %s", d.name, d.match(), packageMatches(reg)))
				continue
			}
			packages[d.id] = pkg
		}
	}
	return packages, list
}

// packageMatches lists every package with its pairs, in package id order, as
// platform.unmatched names them: `arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR
// Linux]`. Both names are shown as they must be written, since the match is exact.
func packageMatches(reg *psp.Registry) string {
	parts := make([]string, 0, len(reg.IDs()))
	for _, id := range reg.IDs() {
		pkg, _ := reg.LookupID(id)
		pairs := make([]string, 0, len(pkg.Platform.Matches))
		for _, m := range pkg.Platform.Matches {
			pairs = append(pairs, m.Manufacturer+" / "+m.Platform)
		}
		parts = append(parts, id+" ["+strings.Join(pairs, ", ")+"]")
	}
	return strings.Join(parts, ", ")
}
