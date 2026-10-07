package compiler

import (
	"fmt"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// ArtifactNames warns where the configuration intent carries names an interface the twin
// does not represent under that name.
//
// The artifact is pushed byte for byte as production wrote it: the compiler never
// rewrites a line of it, because a rendering Fylgja edited would no longer be what
// production runs, which is the whole point of pushing it (D-009, Constitution IV). So a
// production name the twin renders to another port name, or does not render at all, is
// pushed unchanged and the node does with it whatever it does — accept it for a port it
// has under that name, refuse it, or take a stanza for a port that is not there. None of
// that is a reason to refuse the twin: the mapping is honest and recorded, and the
// operator is told which lines this concerns before anything runs.
//
// One warning per row of the device whose disposition is omitted, or whose node name is
// present and differs from the production name, and only where the artifact actually
// names it. A row with no port draws nothing even though its node name is nil: the twin
// gives it no port, so the node calls it nothing at all, and its own disposition already
// says so. Without that exception every loopback in
// every artifact would warn.
//
// It is worded here, once, for both callers: validation files these at step read and the
// compiler at step compile, and an operator must not be able to tell from the message
// which raised it.
func ArtifactNames(d ctm.Device, s DeviceSurvey) findings.List {
	if d.Artifact == nil || d.Artifact.Content == "" {
		return nil
	}
	reasons := make(map[string]Omission, len(s.Omissions))
	for _, o := range s.Omissions {
		reasons[o.Object] = o
	}

	var list findings.List
	for _, r := range s.Rows {
		if r.Interface == "" {
			// An interface with no name has one defect worth reporting, and validation
			// reports it: it has no name. Scanning for the empty string would match
			// every line of every artifact.
			continue
		}
		renamed := r.NodeName != nil && *r.NodeName != r.Interface
		if r.Disposition != DispOmitted && !renamed {
			continue
		}
		line, ok := firstLineNaming(d.Artifact.Content, r.Interface)
		if !ok {
			continue
		}
		object := r.Device + ":" + r.Interface
		if r.Disposition == DispOmitted {
			// The omission's own words, verbatim: the reason an operator reads here and
			// the reason the manifest records must be the same sentence.
			detail := "omitted"
			if o, ok := reasons[object]; ok {
				detail = fmt.Sprintf("omitted (%s: %s)", o.Rule, o.Reason)
			}
			list.Add(findings.Warning, findings.RuleArtifactInterfaceUnrepresented, object, fmt.Sprintf(
				"artifact %s names interface %s at line %d, which the twin does not represent: %s",
				d.Artifact.Name, r.Interface, line, detail))
			continue
		}
		list.Add(findings.Warning, findings.RuleArtifactInterfaceUnrepresented, object, fmt.Sprintf(
			"artifact %s names interface %s at line %d, which the node calls %s; the line is pushed as production wrote it",
			d.Artifact.Name, r.Interface, line, *r.NodeName))
	}
	return list
}

// firstLineNaming returns the number of the first line naming want as a token, counting
// from 1.
//
// A token is an occurrence whose neighbouring bytes are not name bytes, so
// `ethernet-1/1.0` names `ethernet-1/1` — the subinterface is that port — while
// `Ethernet1/1` and `Ethernet10` do not name `Ethernet1`. Substring matching alone would
// warn about a port whose name is the prefix of another's, which on a modular naming
// scheme is most of them.
//
// The line's text is never returned and never quoted: a finding says which line, so the
// operator can look, and carries no byte of the configuration itself.
func firstLineNaming(content, want string) (int, bool) {
	for i, line := range strings.Split(content, "\n") {
		for at := 0; ; {
			j := strings.Index(line[at:], want)
			if j < 0 {
				break
			}
			start := at + j
			end := start + len(want)
			before := start == 0 || !isNameByte(line[start-1])
			after := end == len(line) || !isNameByte(line[end])
			if before && after {
				return i + 1, true
			}
			at = start + 1
		}
	}
	return 0, false
}

// isNameByte reports whether b can be part of an interface name, for the token rule
// above. Letters, digits, underscore, slash and hyphen: the bytes every naming scheme in
// the tree builds its names from.
func isNameByte(b byte) bool {
	switch {
	case b >= 'a' && b <= 'z', b >= 'A' && b <= 'Z', b >= '0' && b <= '9':
		return true
	case b == '_' || b == '/' || b == '-':
		return true
	}
	return false
}
