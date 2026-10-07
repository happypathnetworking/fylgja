package psp

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// artifactNamePattern is the schema's own constraint on config.artifact_name
// (psp/psp.schema.json), repeated here so the named rule fires beside psp.schema when
// the value fails it: the name becomes the bundle's file name, configs/<node>.<name>,
// and the read's selector. A test asserts the two are one string, so they cannot drift.
const artifactNamePattern = `^[a-z0-9][a-z0-9._-]*$`

var artifactNameRE = regexp.MustCompile(artifactNamePattern)

// Boot times below this are almost certainly a mistake rather than a fast platform.
// A warning, not a rejection: a platform author may know something the validator does
// not, and a package that is merely surprising should not be unusable.
const implausibleReadinessSeconds = 5

// checkConsistency applies the rules a schema cannot express: that each rule's
// patterns agree with one another and with its lossy flag, that a breakout rule names a
// parent it can render, that there is exactly one management rule and its name is not
// also a data port's, and that the declared mappings name rules the profile has.
//
// These matter because they are silent failures otherwise. A package whose patterns
// disagree validates cleanly and then maps two production interfaces onto one node
// port, producing a twin that is wrong in a way nobody notices.
func checkConsistency(p *PSP, path string, list *findings.List) {
	id := p.Platform.ID
	if id == "" {
		id = path
	}

	checkVersion(p.PSPVersion, id, path, list)

	checkRules(p, path, list)
	checkMappings(p, path, list)

	if p.Image.Resources.MemoryMB <= 0 || p.Image.Resources.CPU <= 0 {
		list.AddAt(findings.Warning, findings.RulePSPResourcesImplausible, id, fmt.Sprintf(
			"resources look implausible: %.2f cpu, %d MB", p.Image.Resources.CPU, p.Image.Resources.MemoryMB), path, 0)
	}
	if p.Readiness.TimeoutS > 0 && p.Readiness.TimeoutS < implausibleReadinessSeconds {
		list.AddAt(findings.Warning, findings.RulePSPReadinessImplausible, id, fmt.Sprintf(
			"readiness timeout of %ds is below any plausible boot time", p.Readiness.TimeoutS), path, 0)
	}

	// A gNMI probe without an encoding requests the proto default, which SR Linux
	// refuses as Unimplemented on every attempt: the package would
	// load and the twin would never be ready. The schema's conditional `required`
	// already reports the missing field as psp.schema; this rule says why it matters.
	if (p.Readiness.Probe == ProbeGNMIGet || p.Readiness.Probe == ProbeGNMISubscribe) && p.Readiness.Encoding == "" {
		list.AddAt(findings.Rejection, findings.RulePSPReadinessEncoding, id, fmt.Sprintf(
			"readiness probe %s names no encoding; the platform refuses the gNMI proto default as Unimplemented, so the probe would never succeed",
			p.Readiness.Probe), path, 0)
	}

	checkConfig(p, id, path, list)

	// Not a defect: a note, so the hardware virtualization requirement is discovered
	// here rather than at deploy time on a host that lacks it.
	if p.Image.Acquisition == AcquisitionVrnetlabVM {
		list.AddAt(findings.Info, findings.RulePSPAcquisitionKVM, id,
			"this platform is packaged as a VM and requires hardware virtualization (/dev/kvm) on the lab host", path, 0)
	}
}

// checkVersion names a package of another format version as such, beside whatever the
// schema says about its fields.
func checkVersion(version, id, path string, list *findings.List) {
	if version != "" && version != FormatVersion {
		list.AddAt(findings.Rejection, findings.RulePSPVersionUnknown, id, fmt.Sprintf(
			"package declares format version %q, this build understands %q", version, FormatVersion), path, 0)
	}
}

// declaredVersion reads only the version and platform id, ignoring every other field,
// for a package the strict decoder refused. A package of a format that retired fields
// (0.3's interface patterns, M6) fails that decoder on them, so without this it would be
// refused for its fields alone and never named as the previous version it is.
func declaredVersion(data []byte) (version, id string) {
	var head struct {
		PSPVersion string `yaml:"psp_version"`
		Platform   struct {
			ID string `yaml:"id"`
		} `yaml:"platform"`
	}
	if yaml.Unmarshal(data, &head) != nil {
		return "", ""
	}
	return head.PSPVersion, head.Platform.ID
}

// checkRules applies the profile's rules on its rules, every
// one in the same pass, so a platform author sees the whole list at once.
func checkRules(p *PSP, path string, list *findings.List) {
	reject := func(rule, msg string) { list.AddAt(findings.Rejection, rule, path, msg, path, 0) }
	rules := p.Interfaces.Rules

	// Names: what findings, the pure half and the fidelity record call a rule by.
	firstAt := map[string]int{}
	for i, r := range rules {
		if r.Name == "" {
			reject(findings.RulePSPRuleName, fmt.Sprintf(
				"rule %d has no name; every rule needs one, unique in the profile, so findings and the fidelity record can name it", i+1))
			continue
		}
		if j, dup := firstAt[r.Name]; dup {
			reject(findings.RulePSPRuleName, fmt.Sprintf(
				"rules %d and %d are both named %q; names are unique in the profile", j+1, i+1, r.Name))
			continue
		}
		firstAt[r.Name] = i
	}

	// Exactly one management rule, carrying none of a data rule's fields.
	var mgmt []int
	for i, r := range rules {
		if !r.Management {
			continue
		}
		mgmt = append(mgmt, i)
		for _, field := range managementExtras(r) {
			reject(findings.RulePSPManagementRule, fmt.Sprintf(
				"%s carries management: true and %s; a management rule has only name, port and node_name", ruleLabel(i, r), field))
		}
		if r.Breakout != nil {
			reject(findings.RulePSPPatternsBreakout, fmt.Sprintf(
				"%s is the management rule and declares breakout", ruleLabel(i, r)))
		}
		for _, f := range []struct{ field, pattern string }{{"port", r.Port}, {"node_name", r.NodeName}} {
			if ph := Placeholders(f.pattern); len(ph) > 0 {
				reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
					"%s: %s %q uses %s but the management rule captures nothing; its port and node name are literal",
					ruleLabel(i, r), f.field, f.pattern, braceSet(ph)))
			}
		}
	}
	switch {
	case len(mgmt) == 0:
		reject(findings.RulePSPManagementRule,
			"the profile has no management rule; one rule must carry management: true, naming the node's management port")
	case len(mgmt) > 1:
		for _, j := range mgmt[1:] {
			reject(findings.RulePSPManagementRule, fmt.Sprintf(
				"rules %s and %s both carry management: true; exactly one may",
				quotedName(mgmt[0], rules[mgmt[0]]), quotedName(j, rules[j])))
		}
	}

	for i, r := range rules {
		if r.Management {
			continue
		}
		checkDataRule(i, r, reject)
	}

	// The management rule bypasses matching entirely. If its node name also matches a
	// data rule, one name would mean two things on the node. So would a management port
	// or node name a data rule can render: an interface would land on the management
	// port, or take its name, and compile clean.
	for _, j := range mgmt {
		m := rules[j]
		if m.NodeName != "" {
			for i, r := range rules {
				if r.Management || r.Match == "" {
					continue
				}
				pat, err := CompilePattern(r.Match)
				if err != nil || pat.Match(m.NodeName) == nil {
					continue
				}
				reject(findings.RulePSPManagementCollides, fmt.Sprintf(
					"management node name %q also matches %s (%q); one name would mean two things",
					m.NodeName, ruleLabel(i, r), r.Match))
			}
		}
		for _, msg := range managementRenders(m, rules) {
			reject(findings.RulePSPManagementCollides, msg)
		}
	}
}

// checkDataRule applies the placeholder and breakout rules to one data rule.
func checkDataRule(i int, r Rule, reject func(rule, msg string)) {
	label := ruleLabel(i, r)
	if r.Match == "" {
		// The schema requires match on a data rule and says so as psp.schema; nothing
		// below can be judged without it.
		return
	}
	captured := Placeholders(r.Match)
	kept := Placeholders(r.Port)

	if extra := minus(kept, captured); len(extra) > 0 {
		reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
			"%s: port %q uses %s but match %q captures only %s",
			label, r.Port, braceSet(extra), r.Match, braceSet(captured)))
	}
	if extra := minus(Placeholders(r.NodeName), kept); len(extra) > 0 {
		reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
			"%s: node_name %q uses %s but port %q keeps only %s; one port has one node name",
			label, r.NodeName, braceSet(extra), r.Port, braceSet(intersect(kept, captured))))
	}
	var ranged []string
	for ph := range r.Ranges {
		ranged = append(ranged, ph)
	}
	sort.Strings(ranged)
	if extra := minus(ranged, captured); len(extra) > 0 {
		reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
			"%s: ranges name %s, which match %q does not capture", label, braceSet(extra), r.Match))
	}

	// lossy is the author's checked assertion about the dropped set, not a switch.
	dropped := minus(captured, kept)
	switch {
	case len(dropped) > 0 && !r.Lossy:
		reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
			"%s: port %q drops %s that match %q captures, so two production names land on one port; declare lossy: true, or keep %s in port",
			label, r.Port, braceSet(dropped), r.Match, braceSet(dropped)))
	case len(dropped) == 0 && r.Lossy:
		reject(findings.RulePSPPatternsPlaceholders, fmt.Sprintf(
			"%s is declared lossy but port %q drops nothing match %q captures; a rule that only renames inverts and is not lossy",
			label, r.Port, r.Match))
	}

	if r.Breakout != nil {
		parent := r.Breakout.Parent
		if extra := minus(Placeholders(parent), captured); len(extra) > 0 {
			reject(findings.RulePSPPatternsBreakout, fmt.Sprintf(
				"%s: breakout.parent %q uses %s but match %q captures only %s",
				label, parent, braceSet(extra), r.Match, braceSet(captured)))
		}
		if parent == r.Match {
			reject(findings.RulePSPPatternsBreakout, fmt.Sprintf(
				"%s: breakout.parent equals match; a child cannot be its own parent", label))
		}
	}
}

// checkMappings applies psp.mappings.invalid to the declared mappings.
// The schema says most of this as psp.schema too; the named rule says what the
// declarations are for.
func checkMappings(p *PSP, path string, list *findings.List) {
	reject := func(msg string) { list.AddAt(findings.Rejection, findings.RulePSPMappingsInvalid, path, msg, path, 0) }
	decls := p.Interfaces.Mappings
	if len(decls) == 0 {
		reject("interfaces.mappings is empty; a package declares the mappings the conformance suite checks it against, or it cannot be supported")
		return
	}
	names := map[string]bool{}
	for _, r := range p.Interfaces.Rules {
		if r.Name != "" {
			names[r.Name] = true
		}
	}
	for i, d := range decls {
		where := fmt.Sprintf("mapping %d (%q)", i+1, d.Production)
		if d.Rule != "" && !names[d.Rule] {
			reject(fmt.Sprintf("%s names rule %q, which the profile has not", where, d.Rule))
		}
		if d.Unmappable != "" {
			if d.Port != "" || d.NodeName != "" {
				reject(fmt.Sprintf("%s declares both a port and unmappable: %s; a declaration is one or the other", where, d.Unmappable))
			}
			if d.Unmappable == UnmappableOutOfRange && d.Rule == "" {
				reject(fmt.Sprintf("%s declares out_of_range without the rule that matches", where))
			}
			continue
		}
		var missing []string
		for _, f := range []struct{ name, value string }{{"rule", d.Rule}, {"port", d.Port}, {"node_name", d.NodeName}} {
			if f.value == "" {
				missing = append(missing, f.name)
			}
		}
		if len(missing) > 0 {
			reject(fmt.Sprintf("%s is a mapped declaration without %s; it needs rule, port and node_name",
				where, strings.Join(missing, ", ")))
		}
	}
}

// managementExtras names the data-rule fields a management rule carries.
func managementExtras(r Rule) []string {
	var out []string
	if r.Match != "" {
		out = append(out, "match")
	}
	if len(r.Ranges) > 0 {
		out = append(out, "ranges")
	}
	if r.Lossy {
		out = append(out, "lossy")
	}
	if r.Breakout != nil {
		out = append(out, "breakout")
	}
	return out
}

// quotedName names a rule by its quoted name, or by position when it has none.
func quotedName(i int, r Rule) string {
	if r.Name == "" {
		return fmt.Sprintf("%d", i+1)
	}
	return fmt.Sprintf("%q", r.Name)
}

// intersect returns the members of a also in b, in a's order.
func intersect(a, b []string) []string {
	in := map[string]bool{}
	for _, x := range b {
		in[x] = true
	}
	var out []string
	for _, x := range a {
		if in[x] {
			out = append(out, x)
		}
	}
	return out
}

// checkConfig applies format 0.3's rules on the config block: which artifact is this
// platform's configuration, and whether this build can push it.
//
// The schema catches the missing required fields and a `mode` outside merge | replace.
// Four of these are what a schema cannot say: that two fields do not collide, that a
// content type is text, that this build implements the named mechanism, and that the
// fields the mechanism needs are there. The first names the schema's pattern under the
// rule the contract assigns it, as psp.readiness.encoding does for its `required`.
// implementedDeliveries is the one place in this build that says which delivery
// mechanisms the lab-host driver can push by. Both the delivery rule and the push rule
// read it from here, so a mechanism added to the driver is admitted by changing this
// list alone, and the two rules can never disagree about what is implemented. Order is
// the order the messages name them in.
var implementedDeliveries = []string{DeliveryJSONRPC, DeliveryEAPI}

func isImplementedDelivery(d string) bool {
	for _, impl := range implementedDeliveries {
		if d == impl {
			return true
		}
	}
	return false
}

// quotedDeliveries and plainDeliveries render the list for the two message shapes the
// contract gives: `only "json_rpc" and "eapi" are implemented`, and `only json_rpc and
// eapi do`.
func quotedDeliveries() string { return joinAnd(implementedDeliveries, true) }
func plainDeliveries() string  { return joinAnd(implementedDeliveries, false) }

func joinAnd(items []string, quote bool) string {
	out := make([]string, len(items))
	for i, it := range items {
		if quote {
			out[i] = strconv.Quote(it)
		} else {
			out[i] = it
		}
	}
	switch len(out) {
	case 0:
		return ""
	case 1:
		return out[0]
	case 2:
		return out[0] + " and " + out[1]
	default:
		return strings.Join(out[:len(out)-1], ", ") + " and " + out[len(out)-1]
	}
}

func checkConfig(p *PSP, id, path string, list *findings.List) {
	c := p.Config

	// A readiness that waits for the push transport needs one to wait on. The request is
	// unsatisfiable without it, and a package that makes it would leave every node of this
	// platform waiting out its readiness budget for an endpoint nothing declares (D-029).
	if p.Readiness.AwaitPushTransport && c.Push == nil {
		list.AddAt(findings.Rejection, findings.RulePSPReadinessAwaitPushTransport, path, fmt.Sprintf(
			"support package %s sets readiness.await_push_transport and declares no config.push: "+
				"there is no endpoint for readiness to wait on", id), path, 0)
	}

	// The name is the bundle's file name and the read's selector, so a name outside
	// the pattern is refused under the rule the contract names for artifact_name,
	// beside the schema's own refusal (contracts/cli.md).
	if c.ArtifactName != "" && !artifactNameRE.MatchString(c.ArtifactName) {
		list.AddAt(findings.Rejection, findings.RulePSPConfigArtifactName, path, fmt.Sprintf(
			"artifact_name %q does not match the pattern %s; it names the bundle's configs/<node>.<artifact_name> file and the artifact the read selects",
			c.ArtifactName, artifactNamePattern), path, 0)
	}

	// The bundle writes configs/<node>.<artifact_name> beside the bootstrap's
	// configs/<node>.<startup_format>. One name for both would make the second write
	// silently overwrite the first.
	if c.ArtifactName != "" && c.ArtifactName == c.StartupFormat {
		list.AddAt(findings.Rejection, findings.RulePSPConfigArtifactName, path, fmt.Sprintf(
			"artifact_name %q is also startup_format; the bundle would write one file for both the bootstrap and the artifact",
			c.ArtifactName), path, 0)
	}

	// The CTM carries artifact content as UTF-8 text, so a package that accepts a
	// non-text type is asking the read to put bytes somewhere they cannot go.
	for _, ct := range c.ArtifactContentTypes {
		if !strings.HasPrefix(ct, "text/") {
			list.AddAt(findings.Rejection, findings.RulePSPConfigContentType, path, fmt.Sprintf(
				"artifact_content_types names %q; the CTM carries artifact content as text, so every accepted type must be text/*",
				ct), path, 0)
		}
	}

	// A platform is supported only when its package passes (Constitution II): a
	// delivery this build cannot make is refused at load, so no twin is ever built
	// whose nodes would be silently left unconfigured.
	if c.Delivery != "" && !isImplementedDelivery(c.Delivery) {
		list.AddAt(findings.Rejection, findings.RulePSPConfigDeliveryUnimplemented, path, fmt.Sprintf(
			"delivery %q is not a mechanism this build pushes by; only %s are implemented",
			c.Delivery, quotedDeliveries()), path, 0)
	}

	// Every implemented mechanism reaches the node over the network, so each needs an
	// address and a login to reach it with.
	if isImplementedDelivery(c.Delivery) && c.Push == nil {
		list.AddAt(findings.Rejection, findings.RulePSPConfigPushMissing, path, fmt.Sprintf(
			"delivery is %s but no push block says how to reach the node", c.Delivery), path, 0)
	}

	// bootstrap_via: push sends the bootstrap's lines through the same request as the
	// artifact's, ahead of them. Format 0.5 refused it beside mode replace as well, when
	// replace was M5's `delete /`; D-033's replace resets before the bootstrap is sent, so
	// that pairing is a shipped package's and the clause is retired (format 0.6).
	if c.BootstrapVia == BootstrapViaPush {
		// A mechanism that carries no configuration lines has nothing to send the
		// bootstrap's lines through, so the file would be written and never applied.
		if c.Delivery != "" && !isImplementedDelivery(c.Delivery) {
			list.AddAt(findings.Rejection, findings.RulePSPConfigBootstrapVia, path, fmt.Sprintf(
				"bootstrap_via is push but delivery %q carries no configuration lines; only %s do",
				c.Delivery, plainDeliveries()), path, 0)
		}
	}

	// replace loads the node's baseline into a candidate, sends the lines over it and
	// commits once (D-033): there is no command list for replace without a candidate.
	if c.Mode == ModeReplace && c.Commit == CommitImplicit {
		list.AddAt(findings.Rejection, findings.RulePSPConfigPushMissing, path,
			"mode is replace with commit implicit; the reset loads the baseline into a candidate and commits it, which an implicit commit has none of, so no command list is defined for this pair",
			path, 0)
	}
}

// checkDuplicateIdentity reports two packages claiming the same platform.
func checkDuplicateIdentity(pkgs []*PSP, list *findings.List) {
	seen := map[string]string{}
	for _, p := range pkgs {
		if p.Platform.ID == "" {
			continue
		}
		if first, dup := seen[p.Platform.ID]; dup {
			list.AddAt(findings.Rejection, findings.RulePSPIdentityDuplicate, p.Platform.ID, fmt.Sprintf(
				"platform %q is already declared by %s", p.Platform.ID, first), p.Path, 0)
			continue
		}
		seen[p.Platform.ID] = p.Path
	}
}

// Validate checks one or more support package files.
//
// Entirely local: no Infrahub, no branch, no network. That is what makes it usable in
// CI for contributed packages. It is one check of what "supported" means, the
// conformance suite's `validates`: "supported" is both halves of the suite passing (the
// pure half in tier 1, the boot half against a booted node in tier 3) and the package's
// row in psp/README.md saying so (Constitution II).
//
// Validate reads each path and validates the set as ValidateFiles does; a file it cannot
// read is a psp.schema finding at its place in the list.
func Validate(paths []string) findings.List {
	files := make([]File, len(paths))
	unread := make([]error, len(paths))
	for i, path := range paths {
		files[i].Path = path
		files[i].Data, unread[i] = readFile(path)
	}
	return validate(files, unread)
}

// File is one support package to validate: its bytes, and the path every finding about it
// names.
type File struct {
	Path string
	Data []byte
}

// ValidateFiles checks one or more support packages as Validate checks the files they were
// read from, every finding naming the path given and none read from disk: fylgja serve
// validates the files a client sent under the paths the operator gave (M13). It is a set,
// so psp.identity.duplicate still sees two
// files that claim one platform.
func ValidateFiles(files []File) findings.List {
	return validate(files, nil)
}

// validate is Validate's loop over files already read; unread, when not nil, holds each
// file's read error at its index.
func validate(files []File, unread []error) findings.List {
	var list findings.List
	var parsed []*PSP
	for i, f := range files {
		path, data := f.Path, f.Data
		if unread != nil && unread[i] != nil {
			list.AddAt(findings.Rejection, findings.RulePSPSchema, "", unread[i].Error(), path, 0)
			continue
		}
		_, ok := validateShape(data, path, &list)
		p, err := Parse(data, path, OriginOverride)
		if err != nil {
			if ok {
				list.AddAt(findings.Rejection, findings.RulePSPSchema, "", err.Error(), path, 0)
			}
			if version, id := declaredVersion(data); version != "" {
				if id == "" {
					id = path
				}
				checkVersion(version, id, path, &list)
			}
			continue
		}
		parsed = append(parsed, p)
		checkConsistency(p, path, &list)
	}
	checkDuplicateIdentity(parsed, &list)
	return list
}

func readFile(path string) ([]byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("%s", strings.TrimPrefix(err.Error(), "open "))
	}
	return data, nil
}
