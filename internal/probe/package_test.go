package probe

import (
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The shipped package is embedded, valid, and loads as format ping with every value
// data-model §6 gives it.
func TestTheShippedPackagesAreValidAndEmbedded(t *testing.T) {
	list, err := ValidateEmbedded()
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 0 {
		t.Errorf("the shipped probe packages find %v", list)
	}
	names, err := fs.Glob(fylgja.Data, "probes/*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(names, []string{"probes/ping.yaml"}) {
		t.Errorf("the embedded probe packages are %v, want probes/ping.yaml alone", names)
	}
	reg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	if got := reg.Formats(); !slices.Equal(got, []string{"ping"}) {
		t.Errorf("formats %v, want [ping]", got)
	}
	p, ok := reg.Lookup("ping")
	if !ok {
		t.Fatal("no ping package")
	}
	if p.Origin != OriginEmbedded || p.Path != "probes/ping.yaml" || p.ProbeVersion != "0.1" {
		t.Errorf("origin %q, path %q, version %q", p.Origin, p.Path, p.ProbeVersion)
	}
	img := p.Image
	if img.ClabKind != "linux" || img.Ref != "alpine:3.24.2" || img.Acquisition != "public_registry" ||
		img.Resources.CPU != 0.1 || img.Resources.MemoryMB != 32 || img.DeployTimeoutS != 60 || img.DestroyTimeoutS != 30 {
		t.Errorf("image %+v", img)
	}
	if p.Host.Interface != "eth1" ||
		!slices.Equal(p.Host.Address, []string{"ip", "addr", "add", "{address}", "dev", "{interface}"}) ||
		!slices.Equal(p.Host.Route, []string{"ip", "route", "add", "{far_address}/32", "via", "{gateway}", "dev", "{interface}"}) {
		t.Errorf("host %+v", p.Host)
	}
	if p.Readiness.Probe != ReadinessExec || p.Readiness.Expect != "{address}" || p.Readiness.TimeoutS != 30 ||
		!slices.Equal(p.Readiness.Command, []string{"ip", "-4", "-o", "addr", "show", "dev", "{interface}"}) {
		t.Errorf("readiness %+v", p.Readiness)
	}
	if p.Flow.IntervalS != 0.2 || p.Flow.StartTimeoutS != 30 || p.Flow.ReadTimeoutS != 30 ||
		!slices.Equal(p.Flow.Command, []string{"ping", "-i", "{interval}", "{far_address}"}) {
		t.Errorf("flow %+v", p.Flow)
	}
	if p.Burst.Count != 5 || p.Burst.WaitS != 2 ||
		!slices.Equal(p.Burst.Command, []string{"ping", "-c", "{count}", "-i", "{interval}", "-W", "{wait}", "{far_address}"}) {
		t.Errorf("burst %+v", p.Burst)
	}
	if p.Fidelity.Forwarding != "software" || p.Fidelity.Timing != "container" || len(p.Fidelity.Approximations) == 0 {
		t.Errorf("fidelity %+v", p.Fidelity)
	}
}

// The schema's $id moves with the format, as the PSP's does.
func TestTheProbeSchemaIDMovesWithTheFormat(t *testing.T) {
	raw, err := SchemaBytes()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), `"$id": "`+schemaID+`"`) {
		t.Errorf("probes/probe.schema.json's $id is not %s", schemaID)
	}
}

// shipped returns the embedded ping package as a YAML tree, for a case to change.
func shipped(t *testing.T) map[string]any {
	t.Helper()
	raw, err := fylgja.Data.ReadFile("probes/ping.yaml")
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := yaml.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

// writePackage writes a package tree to dir/name and returns its path.
func writePackage(t *testing.T, dir, name string, m map[string]any) string {
	t.Helper()
	b, err := yaml.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, b, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func block(m map[string]any, key string) map[string]any { return m[key].(map[string]any) }

// A package missing a required field, the format, the image, each mechanism block and each
// timeout among them, is refused under probe.package.schema naming the field; one of
// another version under probe.package.version.unknown alone.
func TestAPackageMissingAFieldIsRefusedNamingIt(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(m map[string]any)
		rule   string
		says   string
	}{
		{"format", func(m map[string]any) { delete(m, "format") }, findings.RuleProbePackageSchema, "format"},
		{"image", func(m map[string]any) { delete(m, "image") }, findings.RuleProbePackageSchema, "image"},
		{"host", func(m map[string]any) { delete(m, "host") }, findings.RuleProbePackageSchema, "host"},
		{"readiness", func(m map[string]any) { delete(m, "readiness") }, findings.RuleProbePackageSchema, "readiness"},
		{"flow", func(m map[string]any) { delete(m, "flow") }, findings.RuleProbePackageSchema, "flow"},
		{"burst", func(m map[string]any) { delete(m, "burst") }, findings.RuleProbePackageSchema, "burst"},
		{"fidelity", func(m map[string]any) { delete(m, "fidelity") }, findings.RuleProbePackageSchema, "fidelity"},
		{"deploy_timeout_s", func(m map[string]any) { delete(block(m, "image"), "deploy_timeout_s") }, findings.RuleProbePackageSchema, "deploy_timeout_s"},
		{"destroy_timeout_s", func(m map[string]any) { delete(block(m, "image"), "destroy_timeout_s") }, findings.RuleProbePackageSchema, "destroy_timeout_s"},
		{"readiness timeout_s", func(m map[string]any) { delete(block(m, "readiness"), "timeout_s") }, findings.RuleProbePackageSchema, "timeout_s"},
		{"start_timeout_s", func(m map[string]any) { delete(block(m, "flow"), "start_timeout_s") }, findings.RuleProbePackageSchema, "start_timeout_s"},
		{"read_timeout_s", func(m map[string]any) { delete(block(m, "flow"), "read_timeout_s") }, findings.RuleProbePackageSchema, "read_timeout_s"},
		{"an unknown field", func(m map[string]any) { block(m, "burst")["size"] = 64 }, findings.RuleProbePackageSchema, "size"},
		{"a readiness of another probe", func(m map[string]any) { block(m, "readiness")["probe"] = "gnmi_get" }, findings.RuleProbePackageSchema, "/readiness/probe"},
		{"version 0.2", func(m map[string]any) { m["probe_version"] = "0.2" }, findings.RuleProbePackageVersionUnknown, `probe_version is 0.2; this build reads probe packages of format "0.1"`},
		{"no version", func(m map[string]any) { delete(m, "probe_version") }, findings.RuleProbePackageVersionUnknown, "probe_version is none"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := shipped(t)
			tc.change(m)
			path := writePackage(t, t.TempDir(), "ping.yaml", m)
			list := ValidatePackages([]string{path})
			found := false
			for _, f := range list {
				if f.Rule != tc.rule && f.Severity == findings.Rejection {
					t.Errorf("a finding under %s besides %s: %v", f.Rule, tc.rule, f)
				}
				found = found || (f.Rule == tc.rule && f.Object == path && strings.Contains(f.Message, tc.says))
			}
			if !found {
				t.Errorf("no %s at %s naming %q among %v", tc.rule, path, tc.says, list)
			}
		})
	}
}

// A template naming a placeholder no field renders there is probe.package.template, naming
// the template and the placeholder.
func TestATemplateNamingAnUnrenderedPlaceholderIsRefused(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(m map[string]any)
		says   string
	}{
		{"an unknown placeholder", func(m map[string]any) { block(m, "flow")["command"] = []any{"ping", "-s", "{size}", "{far_address}"} },
			"flow.command names {size}, which no field renders there"},
		{"a burst's count in a host line", func(m map[string]any) { block(m, "host")["route"] = []any{"ip", "route", "add", "{count}"} },
			"host.route names {count}"},
		{"the interval in readiness's expectation", func(m map[string]any) { block(m, "readiness")["expect"] = "{interval}" },
			"readiness.expect names {interval}"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := shipped(t)
			tc.change(m)
			path := writePackage(t, t.TempDir(), "ping.yaml", m)
			list := ValidatePackages([]string{path})
			holds(t, list, want{findings.RuleProbePackageTemplate, path, tc.says})
		})
	}
}

// An override under <dir>/probes/ shadows the embedded package of its format; an override
// directory with no probes/ overrides nothing, and one that does not exist is refused.
func TestAnOverrideShadowsTheEmbeddedPackage(t *testing.T) {
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, Subdirectory), 0o700); err != nil {
		t.Fatal(err)
	}
	m := shipped(t)
	block(m, "burst")["count"] = 9
	writePackage(t, filepath.Join(dir, Subdirectory), "ping.yaml", m)
	reg, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	p, ok := reg.Lookup("ping")
	if !ok || p.Origin != OriginOverride || p.Burst.Count != 9 {
		t.Errorf("got %+v, want the override's ping with count 9", p)
	}

	bare, err := Load(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if p, _ := bare.Lookup("ping"); p == nil || p.Origin != OriginEmbedded {
		t.Errorf("an override directory with no probes/ gave %+v", p)
	}
	if _, err := Load(filepath.Join(dir, "absent")); err == nil {
		t.Error("an absent override directory loaded")
	}
}

// An override the validation rejects is an *InvalidError carrying the rule, as serve and
// worker run report it at start; a second format alongside loads beside ping.
func TestAnInvalidOverrideRefusesTheLoad(t *testing.T) {
	dir := t.TempDir()
	probes := filepath.Join(dir, Subdirectory)
	if err := os.Mkdir(probes, 0o700); err != nil {
		t.Fatal(err)
	}
	m := shipped(t)
	delete(block(m, "image"), "ref")
	writePackage(t, probes, "ping.yaml", m)
	_, err := Load(dir)
	invalid, ok := err.(*InvalidError)
	if !ok || len(invalid.Findings) == 0 || invalid.Findings[0].Rule != findings.RuleProbePackageSchema {
		t.Fatalf("got %v, want an *InvalidError under %s", err, findings.RuleProbePackageSchema)
	}
	if !strings.Contains(err.Error(), "invalid probe package: ") || !strings.Contains(err.Error(), "ref") {
		t.Errorf("error %q", err)
	}

	m = shipped(t)
	m["format"] = "ping2"
	writePackage(t, probes, "ping.yaml", m)
	reg, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got := reg.Formats(); !slices.Equal(got, []string{"ping", "ping2"}) {
		t.Errorf("formats %v, want ping beside the override's ping2", got)
	}
}

// Two files declaring one format are refused, by the validation and by the load.
func TestTwoPackagesOfOneFormatAreRefused(t *testing.T) {
	dir := t.TempDir()
	probes := filepath.Join(dir, Subdirectory)
	if err := os.Mkdir(probes, 0o700); err != nil {
		t.Fatal(err)
	}
	a := writePackage(t, probes, "a.yaml", shipped(t))
	b := writePackage(t, probes, "b.yaml", shipped(t))
	holds(t, ValidatePackages([]string{a, b}), want{findings.RuleProbePackageFormatDuplicate, b,
		`format "ping" is declared by ` + a + " and " + b})
	if _, err := Load(dir); err == nil || !strings.Contains(err.Error(), findings.RuleProbePackageFormatDuplicate) {
		t.Errorf("Load: %v, want %s", err, findings.RuleProbePackageFormatDuplicate)
	}
}

// Every placeholder renders, an argument may hold one among other text, and a placeholder
// the values lack is an error naming it.
func TestRenderRendersEveryPlaceholder(t *testing.T) {
	values := map[string]string{
		PlaceAddress: "10.1.10.2/24", PlaceGateway: "10.1.10.1", PlaceFarAddress: "10.1.11.2",
		PlaceInterface: "eth1", PlaceInterval: "0.2", PlaceCount: "5", PlaceWait: "2",
	}
	reg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	p, _ := reg.Lookup("ping")
	for _, tc := range []struct {
		template []string
		want     string
	}{
		{p.Host.Address, "ip addr add 10.1.10.2/24 dev eth1"},
		{p.Host.Route, "ip route add 10.1.11.2/32 via 10.1.10.1 dev eth1"},
		{p.Readiness.Command, "ip -4 -o addr show dev eth1"},
		{[]string{p.Readiness.Expect}, "10.1.10.2/24"},
		{p.Flow.Command, "ping -i 0.2 10.1.11.2"},
		{p.Burst.Command, "ping -c 5 -i 0.2 -W 2 10.1.11.2"},
	} {
		got, err := Render(tc.template, values)
		if err != nil {
			t.Errorf("%v: %v", tc.template, err)
			continue
		}
		if strings.Join(got, " ") != tc.want {
			t.Errorf("%v renders %q, want %q", tc.template, strings.Join(got, " "), tc.want)
		}
	}
	if _, err := Render([]string{"ping", "-s", "{size}"}, values); err == nil || !strings.Contains(err.Error(), "{size}") {
		t.Errorf("an unknown placeholder: %v", err)
	}
	// Every template of the shipped package renders with the seven values.
	for _, tmpl := range p.Templates() {
		if _, err := Render(tmpl.Args, values); err != nil {
			t.Errorf("%s: %v", tmpl.Field, err)
		}
	}
}

// research §4.3: psp.Load globs the override directory's own *.yaml alone and never walks
// into probes/, so one directory holds both kinds of package and the PSP loader reads none
// of the probe packages (internal/psp/load.go's filepath.Glob(dir, "*.yaml")).
func TestThePSPLoaderSkipsTheProbesSubdirectory(t *testing.T) {
	dir := t.TempDir()
	probes := filepath.Join(dir, Subdirectory)
	if err := os.Mkdir(probes, 0o700); err != nil {
		t.Fatal(err)
	}
	writePackage(t, probes, "ping.yaml", shipped(t))
	pspReg, err := psp.Load(dir)
	if err != nil {
		t.Fatalf("psp.Load with a probes/ subdirectory: %v", err)
	}
	embedded, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(pspReg.Platforms(), embedded.Platforms()) {
		t.Errorf("psp.Load read %v, want the embedded %v alone", pspReg.Platforms(), embedded.Platforms())
	}
	if _, err := Load(dir); err != nil {
		t.Errorf("probe.Load of the same directory: %v", err)
	}
}
