// Package probe is the one definition of a probe that the compiler, the snapshot, the
// server and the lab share without importing one another (016, D-064): the declaration an
// operator writes, the probe package that says how a format's host runs, and the pure
// reading of a mechanism's output.
//
// A probe is a pair of synthesized hosts on two uncabled ports of the intent's devices. It
// is not intent and never enters the CTM: the snapshot carries the declaration's list
// beside the CTM, and the compiler places the hosts under provenance synthesized. Nothing
// here reads a source of truth, compiles, files a bundle or reaches the lab host.
package probe

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/netip"
	"regexp"
	"slices"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Version is the declaration file's version, the one this build reads; nothing older
// exists.
const Version = "1"

// The declaration file's two rules. The core read a --probes file until 020, which moved
// the file to the orchestrator's adapter (T032, T033) and retired both from the core's
// findings (T035): orchestrator/src/fylgja_orchestrator/documents/rules.py files them.
// Parse keeps them for the fixture tool's -probes, which writes a file's probes to the
// kind, and for the tests that read testdata/probes/; no document of the core's carries
// either, since the snapshot files a probe's fault of shape as snapshot.invalid.
const (
	ruleInvalid            = "probes.invalid"
	ruleVersionUnsupported = "probes.version.unsupported"
)

// NamePattern is what a probe's name must match: short and lowercase, since it names two
// containers (<name>-a, <name>-b) and appears in every report. schema/fylgja-probe.yaml's
// name regex and contracts/probes.schema.json's pattern say the same.
var NamePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,23}$`)

// Ends names a probe's two endpoints, in order: the names the manifest gives a link's ends
// and the suffixes of the two hosts.
var Ends = [2]string{"a", "b"}

// Declaration is the file an operator writes (contracts/probes.schema.json), which the
// orchestrator's --probes sends to its adapter from 020.
// The snapshot carries Probes alone.
type Declaration struct {
	Version string  `json:"probes_version"`
	Probes  []Probe `json:"probes"`
}

// Probe is one probe: a name, the format whose package runs its hosts, and its two
// endpoints. The snapshot's element is this object.
type Probe struct {
	Name      string      `json:"name"`
	Format    string      `json:"format"`
	Endpoints [2]Endpoint `json:"endpoints"`
}

// Endpoint is one end of a probe: the device and its uncabled interface the host is
// cabled to, the host's address with its prefix length, and the gateway its route to the
// far host goes through, an address with none.
type Endpoint struct {
	Device    string `json:"device"`
	Interface string `json:"interface"`
	Address   string `json:"address"`
	Gateway   string `json:"gateway"`
}

// The keys of each object of the document, in their written order.
var (
	documentKeys = []string{"probes_version", "probes"}
	probeKeys    = []string{"name", "format", "endpoints"}
	endpointKeys = []string{"device", "interface", "address", "gateway"}
)

// Parse decodes a declaration strictly and holds it to the rules that read no CTM. Keys
// are matched exactly, never folded as a struct decode folds them, and every object's
// fields are required. The version is read first, on its own: not "1", or none, is
// probes.version.unsupported and nothing else is read. Then the shape, every fault in
// one pass, under probes.invalid at the file or at probes[<i>].<field>; then, when the
// shape holds, Validate's rules with no registry, each probe named by its name. The
// declaration is returned only when nothing is rejected.
//
// A file that is empty, or of JSON's whitespace alone, declares no probes: it is read as
// probes 1 with an empty list, with no finding (spec, Edge Cases), as a take with neither.
// Anything else that is not a JSON object is refused.
func Parse(data []byte, path string) (*Declaration, findings.List) {
	if len(bytes.Trim(data, " \t\r\n")) == 0 {
		return &Declaration{Version: Version, Probes: []Probe{}}, nil
	}
	var list findings.List
	var outer map[string]json.RawMessage
	if err := json.Unmarshal(data, &outer); err != nil || outer == nil {
		list.Add(findings.Rejection, ruleInvalid, path,
			"the probe declaration is not a JSON object")
		return nil, list
	}

	raw, present := outer["probes_version"]
	if !present || isNull(raw) {
		list.Add(findings.Rejection, ruleVersionUnsupported, path,
			"the probe declaration names no probes_version; this build reads probes "+Version)
		return nil, list
	}
	var version string
	if err := json.Unmarshal(raw, &version); err != nil || version != Version {
		// A value that is not a string is named as its JSON text, so 1 and "1" differ.
		list.Add(findings.Rejection, ruleVersionUnsupported, path, fmt.Sprintf(
			"the probe declaration is probes_version %s; this build reads probes %q", bytes.TrimSpace(raw), Version))
		return nil, list
	}

	for _, k := range unknownKeys(outer, documentKeys) {
		list.Add(findings.Rejection, ruleInvalid, path, fmt.Sprintf(
			"the probe declaration carries the key %q, which probes %s does not hold: it holds probes_version and probes", k, Version))
	}
	var elements []json.RawMessage
	rawProbes, present := outer["probes"]
	switch {
	case !present || isNull(rawProbes):
		list.Add(findings.Rejection, ruleInvalid, path,
			"the probe declaration has no probes list; write probes: [] to declare none")
	case json.Unmarshal(rawProbes, &elements) != nil:
		list.Add(findings.Rejection, ruleInvalid, path,
			"the probe declaration's probes is not a list")
	}
	d := &Declaration{Version: Version, Probes: make([]Probe, 0, len(elements))}
	for i, el := range elements {
		p, found := DecodeProbe(el, fmt.Sprintf("probes[%d]", i))
		list = append(list, found...)
		d.Probes = append(d.Probes, p)
	}
	if list.Rejected() {
		return nil, list
	}
	if found := Validate(d.Probes, nil, nil); found.Rejected() {
		return nil, append(list, found...)
	}
	return d, list
}

// DecodeProbe decodes one probe object strictly: every key exact, every field present and a
// string, exactly two endpoints. Each fault is probes.invalid at <at>.<field>, at
// <at>.endpoints[<j>].<field> for an endpoint's; the snapshot names an element probes[<i>]
// as the declaration does, and files the fault under its own rule.
func DecodeProbe(raw json.RawMessage, at string) (Probe, findings.List) {
	var list findings.List
	var p Probe
	fields, ok := object(raw, at, probeKeys, "a probe", &list)
	if !ok {
		return p, list
	}
	p.Name = str(fields, "name", at, &list)
	p.Format = str(fields, "format", at, &list)
	rawEnds, present := fields["endpoints"]
	if !present {
		return p, list
	}
	var ends []json.RawMessage
	if err := json.Unmarshal(rawEnds, &ends); err != nil || isNull(rawEnds) {
		list.Add(findings.Rejection, ruleInvalid, at+".endpoints",
			"endpoints is not a list: a probe has exactly two endpoints")
		return p, list
	}
	if len(ends) != 2 {
		list.Add(findings.Rejection, ruleInvalid, at+".endpoints", fmt.Sprintf(
			"endpoints holds %d; a probe has exactly two, a and b", len(ends)))
		return p, list
	}
	for j, e := range ends {
		where := fmt.Sprintf("%s.endpoints[%d]", at, j)
		f, ok := object(e, where, endpointKeys, "an endpoint", &list)
		if !ok {
			continue
		}
		p.Endpoints[j] = Endpoint{
			Device:    str(f, "device", where, &list),
			Interface: str(f, "interface", where, &list),
			Address:   str(f, "address", where, &list),
			Gateway:   str(f, "gateway", where, &list),
		}
	}
	return p, list
}

// object decodes raw as a JSON object of exactly keys, each required, adding a finding for
// a value that is not an object, each unknown key and each key absent.
func object(raw json.RawMessage, at string, keys []string, what string, list *findings.List) (map[string]json.RawMessage, bool) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil || fields == nil {
		list.Add(findings.Rejection, ruleInvalid, at, at+" is not a JSON object: it is "+what)
		return nil, false
	}
	for _, k := range unknownKeys(fields, keys) {
		list.Add(findings.Rejection, ruleInvalid, at+"."+k, fmt.Sprintf(
			"%s carries the key %q, which it does not hold: it holds %s", what, k, strings.Join(keys, ", ")))
	}
	for _, k := range keys {
		if _, present := fields[k]; !present {
			list.Add(findings.Rejection, ruleInvalid, at+"."+k, fmt.Sprintf(
				"%s has no %s, which it requires", what, k))
		}
	}
	return fields, true
}

// str reads a present field as a string, adding a finding when it is not one. An absent
// field reads as "", object having named it.
func str(fields map[string]json.RawMessage, key, at string, list *findings.List) string {
	raw, present := fields[key]
	if !present {
		return ""
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil || isNull(raw) {
		list.Add(findings.Rejection, ruleInvalid, at+"."+key, fmt.Sprintf(
			"%s is %s, not a string", key, bytes.TrimSpace(raw)))
	}
	return s
}

// unknownKeys lists, in byte order, the keys of fields that keys does not hold.
func unknownKeys(fields map[string]json.RawMessage, keys []string) []string {
	var out []string
	for k := range fields {
		if !slices.Contains(keys, k) {
			out = append(out, k)
		}
	}
	sort.Strings(out)
	return out
}

func isNull(raw json.RawMessage) bool {
	return bytes.Equal(bytes.TrimSpace(raw), []byte("null"))
}

// Validate holds a list of probes to the rules that read no CTM, every fault in one pass:
// probe.name.invalid, probe.name.duplicate, probe.format.unknown (only when formats is
// given, the formats a registry loaded), probe.address.invalid, probe.gateway.invalid,
// probe.gateway.outside, probe.family.mixed and probe.address.duplicate (across the whole
// list, R-20). The placement's rules, which read the CTM, are the compiler's.
//
// object names probe i in a finding; nil names it by its name. A finding about one
// endpoint's field is at <object>/<a|b>.<field>.
func Validate(probes []Probe, formats []string, object func(i int) string) findings.List {
	if object == nil {
		object = func(i int) string { return probes[i].Name }
	}
	var list findings.List
	firstByName := map[string]int{}
	type owner struct{ probe, end string }
	byAddress := map[netip.Addr]owner{}
	for i, p := range probes {
		name := object(i)
		if !NamePattern.MatchString(p.Name) {
			list.Add(findings.Rejection, findings.RuleProbeNameInvalid, name, fmt.Sprintf(
				"probe name %q is not %s: lowercase letters, digits and '-', at most 24, beginning with a letter or a digit",
				p.Name, NamePattern))
		}
		if first, taken := firstByName[p.Name]; taken {
			list.Add(findings.Rejection, findings.RuleProbeNameDuplicate, name, fmt.Sprintf(
				"probe name %q is declared at probes[%d] and probes[%d]; a name is one probe's", p.Name, first, i))
		} else {
			firstByName[p.Name] = i
		}
		if formats != nil && !slices.Contains(formats, p.Format) {
			list.Add(findings.Rejection, findings.RuleProbeFormatUnknown, name, fmt.Sprintf(
				"format %q: no probe package declares it; the formats loaded are %s", p.Format, strings.Join(formats, ", ")))
		}

		var families []string
		for j, e := range p.Endpoints {
			end := name + "/" + Ends[j]
			prefix, err := netip.ParsePrefix(e.Address)
			addressOK := err == nil
			if !addressOK {
				list.Add(findings.Rejection, findings.RuleProbeAddressInvalid, end+".address", fmt.Sprintf(
					"address %q is not an address with a prefix length, as 10.1.10.2/24", e.Address))
			}
			gateway, err := netip.ParseAddr(e.Gateway)
			gatewayOK := err == nil && gateway.Zone() == ""
			if !gatewayOK {
				why := "is not an address"
				if strings.Contains(e.Gateway, "/") {
					why = "carries a prefix length; a gateway is an address alone"
				}
				list.Add(findings.Rejection, findings.RuleProbeGatewayInvalid, end+".gateway", fmt.Sprintf(
					"gateway %q %s, as 10.1.10.1", e.Gateway, why))
			}
			if addressOK {
				families = append(families, family(prefix.Addr()))
				host := prefix.Addr()
				if prior, taken := byAddress[host]; taken {
					list.Add(findings.Rejection, findings.RuleProbeAddressDuplicate, end+".address", fmt.Sprintf(
						"address %s of probe %s endpoint %s is probe %s endpoint %s's too: two hosts on one address cannot be told apart by a ping",
						host, p.Name, Ends[j], prior.probe, prior.end))
				} else {
					byAddress[host] = owner{probe: p.Name, end: Ends[j]}
				}
			}
			if gatewayOK {
				families = append(families, family(gateway))
			}
			if addressOK && gatewayOK && family(prefix.Addr()) == family(gateway) && !prefix.Contains(gateway) {
				list.Add(findings.Rejection, findings.RuleProbeGatewayOutside, end+".gateway", fmt.Sprintf(
					"gateway %s is not within %s, so the host's route to the far host could not be added", gateway, prefix.Masked()))
			}
		}
		if slices.Contains(families, "IPv4") && slices.Contains(families, "IPv6") {
			list.Add(findings.Rejection, findings.RuleProbeFamilyMixed, name, fmt.Sprintf(
				"probe %s's addresses and gateways are of two families (%s); a probe's four are of one",
				p.Name, strings.Join(families, ", ")))
		}
	}
	return list
}

func family(a netip.Addr) string {
	if a.Is4() || a.Is4In6() {
		return "IPv4"
	}
	return "IPv6"
}
