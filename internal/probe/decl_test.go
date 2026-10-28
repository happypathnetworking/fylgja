package probe

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// repoPath is a path from the repository root.
func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

func readFixture(t *testing.T, parts ...string) []byte {
	t.Helper()
	b, err := os.ReadFile(repoPath(parts...))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// The declarations tier 1 reads parse, each to one probe of two endpoints, R-19's ports and
// addresses.
func TestTheFixturesParse(t *testing.T) {
	for _, tc := range []struct {
		file, name, device, a, b string
	}{
		{"n1-loop.json", "n1-loop", "n1", "ethernet-1/10", "ethernet-1/11"},
		{"n2-loop.json", "n2-loop", "n2", "ethernet-1/10", "ethernet-1/11"},
		{"e1-loop.json", "e1-loop", "e1", "Ethernet10", "Ethernet11"},
	} {
		t.Run(tc.file, func(t *testing.T) {
			d, list := Parse(readFixture(t, "testdata", "probes", tc.file), tc.file)
			if list.Rejected() || d == nil {
				t.Fatalf("refused: %v", list)
			}
			if d.Version != Version || len(d.Probes) != 1 {
				t.Fatalf("got %+v, want probes 1 with one probe", d)
			}
			p := d.Probes[0]
			if p.Name != tc.name || p.Format != "ping" || p.Endpoints[0].Device != tc.device ||
				p.Endpoints[1].Device != tc.device || p.Endpoints[0].Interface != tc.a || p.Endpoints[1].Interface != tc.b {
				t.Errorf("got %+v", p)
			}
		})
	}
}

const good = `{"probes_version": "1", "probes": [
  {"name": "n1-loop", "format": "ping", "endpoints": [
    {"device": "n1", "interface": "ethernet-1/10", "address": "10.1.10.2/24", "gateway": "10.1.10.1"},
    {"device": "n1", "interface": "ethernet-1/11", "address": "10.1.11.2/24", "gateway": "10.1.11.1"}]}]}`

// want is one expected finding: its rule and object, and text its message holds.
type want struct{ rule, object, says string }

func holds(t *testing.T, list findings.List, w want) {
	t.Helper()
	for _, f := range list {
		if f.Rule == w.rule && f.Object == w.object && strings.Contains(f.Message, w.says) && f.Severity == findings.Rejection {
			return
		}
	}
	t.Errorf("no rejection %s at %q saying %q among %v", w.rule, w.object, w.says, list)
}

// Each fault of the document's shape is probes.invalid at the file or at
// probes[<i>].<field>, and the version is read first, on its own.
func TestParseRefusesTheShape(t *testing.T) {
	const file = "probes.json"
	for _, tc := range []struct {
		name, doc string
		want      want
	}{
		{"not an object", `[]`, want{findings.RuleProbesInvalid, file, "not a JSON object"}},
		{"not JSON", `{`, want{findings.RuleProbesInvalid, file, "not a JSON object"}},
		{"no version", `{"probes": []}`, want{findings.RuleProbesVersionUnsupported, file, "names no probes_version"}},
		{"version 2", `{"probes_version": "2", "probes": []}`, want{findings.RuleProbesVersionUnsupported, file, `probes_version "2"; this build reads probes "1"`}},
		{"version a number", `{"probes_version": 1, "probes": []}`, want{findings.RuleProbesVersionUnsupported, file, "probes_version 1;"}},
		{"an unknown key", `{"probes_version": "1", "probes": [], "hosts": []}`, want{findings.RuleProbesInvalid, file, `the key "hosts"`}},
		{"no probes", `{"probes_version": "1"}`, want{findings.RuleProbesInvalid, file, "no probes list"}},
		{"probes null", `{"probes_version": "1", "probes": null}`, want{findings.RuleProbesInvalid, file, "no probes list"}},
		{"probes not a list", `{"probes_version": "1", "probes": {}}`, want{findings.RuleProbesInvalid, file, "not a list"}},
		{"a probe not an object", `{"probes_version": "1", "probes": ["n1-loop"]}`, want{findings.RuleProbesInvalid, "probes[0]", "not a JSON object"}},
		{"a probe's unknown key", strings.Replace(good, `"format": "ping"`, `"format": "ping", "count": 5`, 1),
			want{findings.RuleProbesInvalid, "probes[0].count", `the key "count"`}},
		{"a probe's missing field", strings.Replace(good, `"format": "ping", `, ``, 1),
			want{findings.RuleProbesInvalid, "probes[0].format", "has no format"}},
		{"a field not a string", strings.Replace(good, `"name": "n1-loop"`, `"name": 7`, 1),
			want{findings.RuleProbesInvalid, "probes[0].name", "not a string"}},
		{"one endpoint", `{"probes_version": "1", "probes": [{"name": "x", "format": "ping", "endpoints": [
			{"device": "n1", "interface": "e", "address": "10.0.0.2/24", "gateway": "10.0.0.1"}]}]}`,
			want{findings.RuleProbesInvalid, "probes[0].endpoints", "endpoints holds 1; a probe has exactly two"}},
		{"three endpoints", readFixtureString(t, "probes.invalid.json"),
			want{findings.RuleProbesInvalid, "probes[0].endpoints", "endpoints holds 3"}},
		{"endpoints not a list", `{"probes_version": "1", "probes": [{"name": "x", "format": "ping", "endpoints": {}}]}`,
			want{findings.RuleProbesInvalid, "probes[0].endpoints", "not a list"}},
		{"an endpoint's unknown key", strings.Replace(good, `"gateway": "10.1.11.1"`, `"gateway": "10.1.11.1", "vlan": 10`, 1),
			want{findings.RuleProbesInvalid, "probes[0].endpoints[1].vlan", `the key "vlan"`}},
		{"an endpoint's missing field", strings.Replace(good, `, "gateway": "10.1.11.1"`, ``, 1),
			want{findings.RuleProbesInvalid, "probes[0].endpoints[1].gateway", "has no gateway"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			d, list := Parse([]byte(tc.doc), file)
			if d != nil {
				t.Errorf("a refused declaration was returned: %+v", d)
			}
			holds(t, list, tc.want)
		})
	}
}

func readFixtureString(t *testing.T, name string) string {
	t.Helper()
	return string(readFixture(t, "testdata", "probes", "invalid", name))
}

// Each rule that reads no CTM names the probe, the endpoint and the field. Parse holds a
// declaration to them with no registry; the format is held where a registry is at hand.
func TestValidateNamesTheProbeTheEndpointAndTheField(t *testing.T) {
	for _, tc := range []struct {
		file    string
		formats []string
		want    want
	}{
		{"probe.name.invalid.json", nil, want{findings.RuleProbeNameInvalid, "N1_loop", `probe name "N1_loop" is not`}},
		{"probe.name.duplicate.json", nil, want{findings.RuleProbeNameDuplicate, "n1-loop", "declared at probes[0] and probes[1]"}},
		{"probe.format.unknown.json", []string{"ping"}, want{findings.RuleProbeFormatUnknown, "n1-loop", `format "traceroute": no probe package declares it; the formats loaded are ping`}},
		{"probe.address.invalid.json", nil, want{findings.RuleProbeAddressInvalid, "n1-loop/b.address", `address "10.1.11.2" is not an address with a prefix length`}},
		{"probe.gateway.invalid.json", nil, want{findings.RuleProbeGatewayInvalid, "n1-loop/b.gateway", `gateway "10.1.11.1/24" carries a prefix length`}},
		{"probe.gateway.outside.json", nil, want{findings.RuleProbeGatewayOutside, "n1-loop/b.gateway", "gateway 10.1.12.1 is not within 10.1.11.0/24"}},
		{"probe.family.mixed.json", nil, want{findings.RuleProbeFamilyMixed, "n1-loop", "two families (IPv4, IPv4, IPv6, IPv6)"}},
		{"probe.address.duplicate.json", nil, want{findings.RuleProbeAddressDuplicate, "n2-loop/a.address",
			"address 10.1.10.2 of probe n2-loop endpoint a is probe n1-loop endpoint a's too"}},
	} {
		t.Run(tc.file, func(t *testing.T) {
			raw := readFixture(t, "testdata", "probes", "invalid", tc.file)
			decl, list := Parse(raw, tc.file)
			if tc.formats == nil {
				if decl != nil {
					t.Errorf("Parse returned a declaration it refused: %+v", decl)
				}
				holds(t, list, tc.want)
				return
			}
			// The format is the one rule Parse leaves to a registry.
			if list.Rejected() {
				t.Fatalf("Parse refused a declaration only a registry refuses: %v", list)
			}
			holds(t, Validate(decl.Probes, tc.formats, nil), tc.want)
		})
	}
}

// An endpoint's other faults: a gateway that is no address, an address of a gateway's
// family mismatched without a prefix, and every fault of one probe in one pass.
func TestValidateReportsEveryFaultInOnePass(t *testing.T) {
	p := Probe{Name: "x", Format: "ping", Endpoints: [2]Endpoint{
		{Device: "n1", Interface: "e1", Address: "nonsense", Gateway: "also nonsense"},
		{Device: "n1", Interface: "e2", Address: "10.0.0.2/24", Gateway: "fe80::1%eth1"},
	}}
	list := Validate([]Probe{p}, nil, nil)
	holds(t, list, want{findings.RuleProbeAddressInvalid, "x/a.address", `"nonsense"`})
	holds(t, list, want{findings.RuleProbeGatewayInvalid, "x/a.gateway", `gateway "also nonsense" is not an address`})
	holds(t, list, want{findings.RuleProbeGatewayInvalid, "x/b.gateway", `"fe80::1%eth1"`})
	if n := list.Count(findings.Rejection); n != 3 {
		t.Errorf("%d rejections, want 3: %v", n, list)
	}
}

// object names a probe as the caller does: the snapshot by its position.
func TestValidateNamesAProbeAsTheCallerDoes(t *testing.T) {
	p := Probe{Name: "x", Format: "ping", Endpoints: [2]Endpoint{
		{Device: "n1", Interface: "e1", Address: "10.0.0.2/24", Gateway: "10.0.1.1"},
		{Device: "n1", Interface: "e2", Address: "10.0.1.2/24", Gateway: "10.0.1.1"},
	}}
	list := Validate([]Probe{p}, nil, func(i int) string { return "probes[0]" })
	holds(t, list, want{findings.RuleProbeGatewayOutside, "probes[0]/a.gateway", "not within 10.0.0.0/24"})
}

// A good declaration passes every rule, the format included, and an empty list is a
// declaration of none.
func TestValidateAcceptsAGoodDeclaration(t *testing.T) {
	d, list := Parse([]byte(good), "probes.json")
	if list.Rejected() {
		t.Fatalf("refused: %v", list)
	}
	if found := Validate(d.Probes, []string{"ping"}, nil); len(found) != 0 {
		t.Errorf("a good declaration found %v", found)
	}
	none, list := Parse([]byte(`{"probes_version": "1", "probes": []}`), "none.json")
	if list.Rejected() || none == nil || len(none.Probes) != 0 {
		t.Errorf("an empty declaration: %+v, %v", none, list)
	}
}
