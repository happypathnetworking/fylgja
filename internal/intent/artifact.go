package intent

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// StatusReady is the one artifact status a read accepts. Infrahub's other states —
// Pending while a creation is in flight, Error for a generation that failed — mean the
// bytes on offer are not the bytes production runs, and Fylgja never regenerates an
// artifact to fix that, because generating is a write to Infrahub (D-028).
const StatusReady = "Ready"

// storageObjectPath addresses one artifact's content in Infrahub's object store. The
// id comes from the same listing the rest of the artifact's facts came from, so a
// pinned read fetches the object that was current at `at`.
func storageObjectPath(storageID string) string {
	return "/api/storage/object/" + url.PathEscape(storageID)
}

// listedArtifact is one artifact as the device query listed it, flattened out of the
// generated types. Nothing of Infrahub's addressing survives past this package:
// StorageID is used to fetch the content and then dropped, and the artifact's own id is
// never selected at all.
type listedArtifact struct {
	Name           string
	Status         string
	ContentType    string
	Checksum       string
	StorageID      string
	DefinitionName string
}

// listArtifacts flattens what the device node carries.
//
// The assertion is on ArtifactFields, the fragment's own generated interface, never on
// a concrete device kind (Constitution III): genqlient hangs the fragment's fields off
// each implementation, and the fragment's type is what Fylgja is allowed to know. A
// node that does not satisfy it belongs to a kind that does not inherit
// CoreArtifactTarget, which conformance refuses before the query runs; here it
// simply carries no artifact, which the caller reports as one.
func listArtifacts(n deviceNode) []listedArtifact {
	target, ok := any(n).(ArtifactFields)
	if !ok {
		return nil
	}
	page := target.GetArtifacts()
	var out []listedArtifact
	for _, edge := range page.GetEdges() {
		node := edge.GetNode()
		name, status := node.GetName(), node.GetStatus()
		contentType, checksum, storage := node.GetContent_type(), node.GetChecksum(), node.GetStorage_id()
		a := listedArtifact{
			Name:        name.GetValue(),
			Status:      status.GetValue(),
			ContentType: contentType.GetValue(),
			Checksum:    checksum.GetValue(),
			StorageID:   storage.GetValue(),
		}
		// CoreArtifactDefinition is a concrete node kind rather than a generic, so
		// genqlient generates a struct here: there is no nil node to guard against, as
		// with FylgjaContract's.
		definition := node.GetDefinition()
		d := definition.GetNode()
		artifactName := d.GetArtifact_name()
		a.DefinitionName = artifactName.GetValue()
		out = append(out, a)
	}
	return out
}

// pending pairs a device the projection produced with the node it came from, so
// selection can name the device as the CTM will and read the artifacts as Infrahub
// listed them.
type pending struct {
	index int // into the CTM's devices, which Normalize has not yet reordered
	name  string
	nos   string
	node  deviceNode
}

// selected is one device's artifact after steps 1–5, before its content is fetched.
type selected struct {
	index    int
	device   string
	pkg      *psp.PSP
	artifact listedArtifact
}

// fetchArtifacts fills each device's configuration artifact, in the steps below.
//
// Steps 1–5 are decided from the listing for *every* device before any content is
// fetched, and every device's refusal is collected: an operator fixing a branch sees
// every device that cannot be built, not the first (Constitution III). Step 6
// then fetches one object per surviving device, sequentially — three devices, three
// requests — and steps 7 and 8 verify what came back.
//
// A 401 or 403 on a content fetch is not a finding but the read's operational failure:
// no device is at fault, the credential is. The remaining devices are still fetched, so
// the one error names every device whose fetch was refused, each once, with the artifact
// and checksum it was reading: a credential refused for some objects and not others
// shows as exactly which. It is returned through wrap, so no credential can reach the
// message (contracts/cli.md).
//
// Findings never carry a byte of content: name, checksum, content type
// and Infrahub's own sentence are the whole vocabulary.
func (c *Client) fetchArtifacts(ctx context.Context, devices []ctm.Device, nodes []deviceNode, reg *psp.Registry) (map[int]*ctm.Artifact, findings.List, error) {
	var list findings.List

	// Name order, so a read reports its devices in the order the CTM will list them and
	// two reads of one branch produce the same findings in the same order, whatever
	// order Infrahub paged them back in.
	work := make([]pending, 0, len(devices))
	for i, d := range devices {
		if i >= len(nodes) {
			break
		}
		work = append(work, pending{index: i, name: d.Name, nos: d.Platform.NOS, node: nodes[i]})
	}
	sort.SliceStable(work, func(i, j int) bool { return work[i].name < work[j].name })

	var ready []selected
	for _, p := range work {
		pkg, ok := reg.Lookup(p.nos)
		if !ok {
			// Validation names this device `platform.unsupported`; a second finding
			// about the same device would bury the one worth fixing, and there is no
			// package to say which artifact to look for.
			continue
		}
		a, ok := selectArtifact(p, pkg, c.cfg.Branch, c.cfg.At, &list)
		if !ok {
			continue
		}
		ready = append(ready, selected{index: p.index, device: p.name, pkg: pkg, artifact: a})
	}

	out := map[int]*ctm.Artifact{}
	var failed fetchFailures
	for _, s := range ready {
		body, status, err := c.getAt(ctx, storageObjectPath(s.artifact.StorageID))
		if err != nil {
			which := fmt.Sprintf("device %s (artifact %s, checksum %s)",
				s.device, s.artifact.DefinitionName, s.artifact.Checksum)
			// The refusal itself, not the *url.Error around it, whose text names each
			// object's URL: devices refused alike are one sentence.
			var refused credentialRefused
			if errors.As(err, &refused) {
				failed.add(refused, which)
				continue
			}
			// Infrahub unreachable, or the read cancelled: nothing about this device,
			// and every remaining fetch would fail the same way, a timeout each.
			failed.add(err, which)
			break
		}
		if status != 200 {
			list.Add(findings.Rejection, findings.RuleArtifactContentUnavailable, s.device, fmt.Sprintf(
				"device %s: artifact %s (checksum %s): Infrahub does not serve its content%s: %s",
				s.device, s.artifact.DefinitionName, s.artifact.Checksum, asItStood(c.cfg.At), explainStatus(status, body)))
			continue
		}
		if sum := hex.EncodeToString(hashOf(body)); sum != s.artifact.Checksum {
			// Infrahub's checksum is the MD5 of the content (verified), so
			// a difference means the bytes served are not the bytes the listing
			// described — and those bytes would become the twin's configuration.
			list.Add(findings.Rejection, findings.RuleArtifactChecksumMismatch, s.device, fmt.Sprintf(
				"device %s: artifact %s fetched with checksum %s, Infrahub reports %s",
				s.device, s.artifact.DefinitionName, sum, s.artifact.Checksum))
			continue
		}
		if !utf8.Valid(body) {
			// The accepted content types are text/* (a package consistency rule), so
			// bytes that are not text contradict what the artifact says it is. The CTM
			// carries content as a UTF-8 string, and encoding it some other way would
			// make the file the operator inspects unreadable.
			list.Add(findings.Rejection, findings.RuleArtifactContentTypeUnsupported, s.device, fmt.Sprintf(
				"device %s: artifact %s (checksum %s) is %s but its content is not text",
				s.device, s.artifact.DefinitionName, s.artifact.Checksum, s.artifact.ContentType))
			continue
		}
		out[s.index] = &ctm.Artifact{
			Name:        s.artifact.DefinitionName,
			ContentType: s.artifact.ContentType,
			Checksum:    s.artifact.Checksum,
			Content:     string(body),
		}
	}
	if len(failed) > 0 {
		return nil, nil, failed.err(c)
	}
	return out, list, nil
}

// fetchFailures are the content fetches that failed operationally, grouped by cause in
// the order first seen, so that devices refused for one reason are named in one
// sentence and a device is never named under a cause that was not its own.
type fetchFailures []fetchFailure

type fetchFailure struct {
	cause   error
	devices []string
}

func (f *fetchFailures) add(cause error, device string) {
	for i := range *f {
		if (*f)[i].cause.Error() == cause.Error() {
			(*f)[i].devices = append((*f)[i].devices, device)
			return
		}
	}
	*f = append(*f, fetchFailure{cause: cause, devices: []string{device}})
}

// err is the read's one operational failure, each cause through wrap: redacted, naming
// the reference the read was made against.
func (f fetchFailures) err(c *Client) error {
	var out error
	for _, g := range f {
		e := c.wrap(g.cause, "reading the artifact content for "+joinAnd(g.devices))
		if out == nil {
			out = e
		} else {
			out = fmt.Errorf("%w; %w", out, e)
		}
	}
	return out
}

// joinAnd lists items as a sentence does: "a", "a and b", "a, b and c".
func joinAnd(items []string) string {
	if len(items) < 2 {
		return strings.Join(items, "")
	}
	return strings.Join(items[:len(items)-1], ", ") + " and " + items[len(items)-1]
}

// selectArtifact decides which of a device's artifacts is its configuration, or names
// why none of them is (steps 1–5). It reads only the listing: nothing
// here makes a request.
//
// A pinned read (at non-empty) is refused in its own words: the listing was
// Infrahub's as of at, so a refusal describes the branch then, not now, and says so.
// There is no fallback to the current artifact on any path — a pinned twin built from
// today's configuration would be a twin of neither moment.
func selectArtifact(p pending, pkg *psp.PSP, branch, at string, list *findings.List) (listedArtifact, bool) {
	want := pkg.Config.ArtifactName

	// Step 1: the definition's artifact_name is what selects, because that is the name
	// the package declares and the artifact node's own `name` carries the same value.
	var candidates []listedArtifact
	for _, a := range listArtifacts(p.node) {
		if a.DefinitionName == want {
			candidates = append(candidates, a)
		}
	}
	if len(candidates) == 0 {
		msg := fmt.Sprintf("device %s has no artifact named %s on branch %s", p.name, want, branch)
		if at != "" {
			msg += " at " + at + "; the artifact did not exist then"
		}
		list.Add(findings.Rejection, findings.RuleArtifactMissing, p.name, msg)
		return listedArtifact{}, false
	}

	// Step 2: choosing among several would be Fylgja deciding what production runs.
	if len(candidates) > 1 {
		sums := make([]string, 0, len(candidates))
		for _, a := range candidates {
			sums = append(sums, a.Checksum)
		}
		sort.Strings(sums)
		list.Add(findings.Rejection, findings.RuleArtifactAmbiguous, p.name, fmt.Sprintf(
			"device %s has %d artifacts named %s (checksums %s); fylgja never chooses among them",
			p.name, len(candidates), want, strings.Join(sums, ", ")))
		return listedArtifact{}, false
	}

	a := candidates[0]

	// Step 3: any state but Ready, named verbatim.
	if a.Status != StatusReady {
		list.Add(findings.Rejection, findings.RuleArtifactNotReady, p.name, fmt.Sprintf(
			"device %s: artifact %s %s, not Ready; fylgja never regenerates an artifact, "+
				"because that is a write to Infrahub", p.name, want, stateThen(a.Status, at)))
		return listedArtifact{}, false
	}

	// Step 4: the package says which types it accepts for this platform.
	if !accepts(pkg.Config.ArtifactContentTypes, a.ContentType) {
		list.Add(findings.Rejection, findings.RuleArtifactContentTypeUnsupported, p.name, fmt.Sprintf(
			"device %s: artifact %s (checksum %s) is %s; the %s package accepts %s",
			p.name, want, a.Checksum, a.ContentType, pkg.Platform.ID,
			strings.Join(pkg.Config.ArtifactContentTypes, ", ")))
		return listedArtifact{}, false
	}

	// Step 5: Ready with no object or no checksum is not held as current — there is
	// nothing to fetch and nothing to verify it against — so it is refused under the
	// same rule as any other state that is not current.
	if a.StorageID == "" || a.Checksum == "" {
		held := "has no stored content, so it is not held as current"
		if at != "" {
			held = "had no stored content, so it was not held as current"
		}
		list.Add(findings.Rejection, findings.RuleArtifactNotReady, p.name, fmt.Sprintf(
			"device %s: artifact %s %s but %s; "+
				"fylgja never regenerates an artifact, because that is a write to Infrahub",
			p.name, want, stateThen(a.Status, at), held))
		return listedArtifact{}, false
	}
	return a, true
}

// stateThen names an artifact's status as the listing gave it: "is <State>" now, or
// "was <State> at <at>" for a pinned read, whose listing is Infrahub's as of at.
func stateThen(state, at string) string {
	if at == "" {
		return "is " + state
	}
	return "was " + state + " at " + at
}

// asItStood qualifies a content fetch refused on a pinned read: the object asked for is
// the one the listing at `at` named, so the refusal is about the content as it stood
// then — the case where an artifact existed at at but Infrahub no longer serves it.
func asItStood(at string) string {
	if at == "" {
		return ""
	}
	return " as it stood at " + at
}

// accepts reports whether the package accepts this content type.
func accepts(types []string, contentType string) bool {
	for _, t := range types {
		if t == contentType {
			return true
		}
	}
	return false
}

// hashOf is Infrahub's checksum algorithm: MD5 over the exact bytes served (verified).
// It is an integrity check against Infrahub's own value and nothing more
// — bundle_id is SHA-256 over the bundle's canonical bytes (D-011), which cover these.
func hashOf(b []byte) []byte {
	sum := md5.Sum(b) //nolint:gosec // integrity against Infrahub's own checksum, not a security property
	return sum[:]
}
