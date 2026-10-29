package probe

import (
	"fmt"
	"regexp"
	"slices"
	"strings"

	"gopkg.in/yaml.v3"
)

// PackageVersion is the probe package format this build reads (probes/probe.schema.json).
const PackageVersion = "0.1"

// ReadinessExec is the one readiness probe a probe package declares: a command run inside
// the host's container, ready when its output holds the expected text. No login.
const ReadinessExec = "exec"

// Package is one probe format's package (probes/<format>.yaml, R-08): how its hosts are
// imaged, addressed, judged ready, and how a flow and a burst are run on them, as data. The
// lab, the host check, the compiler and verify read every budget, template and count from
// it, never from a constant (Constitution II).
type Package struct {
	ProbeVersion string    `yaml:"probe_version" json:"probe_version"`
	Format       string    `yaml:"format" json:"format"`
	Image        Image     `yaml:"image" json:"image"`
	Host         Host      `yaml:"host" json:"host"`
	Readiness    Readiness `yaml:"readiness" json:"readiness"`
	Flow         Flow      `yaml:"flow" json:"flow"`
	Burst        Burst     `yaml:"burst" json:"burst"`
	Fidelity     Fidelity  `yaml:"fidelity" json:"fidelity"`

	// Origin records where the package was loaded from: OriginEmbedded or OriginOverride,
	// as a PSP's does.
	Origin string `yaml:"-" json:"-"`
	// Path is the file the package came from, used for finding objects.
	Path string `yaml:"-" json:"-"`
}

// Image is a host's container image, how it is obtained, and its budgets: a PSP's image
// shape, so the host check and the lab budget a host as they budget a device.
type Image struct {
	ClabKind        string    `yaml:"clab_kind" json:"clab_kind"`
	Ref             string    `yaml:"ref" json:"ref"`
	Acquisition     string    `yaml:"acquisition" json:"acquisition"`
	Resources       Resources `yaml:"resources" json:"resources"`
	DeployTimeoutS  int       `yaml:"deploy_timeout_s" json:"deploy_timeout_s"`
	DestroyTimeoutS int       `yaml:"destroy_timeout_s" json:"destroy_timeout_s"`
}

// Resources is a host's budget, summed by the host check with the devices'.
type Resources struct {
	CPU      float64 `yaml:"cpu" json:"cpu"`
	MemoryMB int     `yaml:"memory_mb" json:"memory_mb"`
}

// Host is the host's data port and the topology's two exec lines: its address on the port
// and its route to the far host through the gateway.
type Host struct {
	Interface string   `yaml:"interface" json:"interface"`
	Address   []string `yaml:"address" json:"address"`
	Route     []string `yaml:"route" json:"route"`
}

// Readiness says when a host is ready: Command run inside it, its output holding Expect,
// within TimeoutS.
type Readiness struct {
	Probe    string   `yaml:"probe" json:"probe"`
	Command  []string `yaml:"command" json:"command"`
	Expect   string   `yaml:"expect" json:"expect"`
	TimeoutS int      `yaml:"timeout_s" json:"timeout_s"`
}

// Flow is a step's transient flow: Command started in host a after the stage and read after
// the wait, one echo every IntervalS, under the two budgets.
type Flow struct {
	IntervalS     float64  `yaml:"interval_s" json:"interval_s"`
	Command       []string `yaml:"command" json:"command"`
	StartTimeoutS int      `yaml:"start_timeout_s" json:"start_timeout_s"`
	ReadTimeoutS  int      `yaml:"read_timeout_s" json:"read_timeout_s"`
}

// Burst is verify's assertion of a probe: Count echoes, each waited on up to WaitS after the
// last, held when every one is answered.
type Burst struct {
	Count   int      `yaml:"count" json:"count"`
	WaitS   int      `yaml:"wait_s" json:"wait_s"`
	Command []string `yaml:"command" json:"command"`
}

// Fidelity is what the hosts cannot reproduce: they forward in software and keep the
// container's timing, which the manifest's probes[] entry carries.
type Fidelity struct {
	Forwarding     string   `yaml:"forwarding" json:"forwarding"`
	Timing         string   `yaml:"timing" json:"timing"`
	Approximations []string `yaml:"approximations" json:"approximations"`
}

// Origins, as a PSP's.
const (
	OriginEmbedded = "embedded"
	OriginOverride = "override"
)

// The placeholders a template may name, by what renders them. Every template is rendered
// for one host, so the host's four are in each; a flow adds its interval, a burst its
// interval, count and wait.
const (
	PlaceAddress    = "address"     // the host's address with its prefix length
	PlaceGateway    = "gateway"     // the host's gateway
	PlaceFarAddress = "far_address" // the far host's address, without its prefix length
	PlaceInterface  = "interface"   // the package's host.interface
	PlaceInterval   = "interval"    // flow.interval_s
	PlaceCount      = "count"       // burst.count
	PlaceWait       = "wait"        // burst.wait_s
)

var (
	hostPlaces  = []string{PlaceAddress, PlaceGateway, PlaceFarAddress, PlaceInterface}
	flowPlaces  = append(slices.Clone(hostPlaces), PlaceInterval)
	burstPlaces = append(slices.Clone(hostPlaces), PlaceInterval, PlaceCount, PlaceWait)
)

// placeholder matches one {name} of a template.
var placeholder = regexp.MustCompile(`\{([^{}]*)\}`)

// Template is one of a package's templates, named by its field, with the placeholders a
// render of it may name.
type Template struct {
	Field  string
	Args   []string
	Places []string
}

// Templates lists the package's templates in their written order: the two exec lines, the
// readiness command and its expectation, the flow's command and the burst's.
func (p *Package) Templates() []Template {
	return []Template{
		{"host.address", p.Host.Address, hostPlaces},
		{"host.route", p.Host.Route, hostPlaces},
		{"readiness.command", p.Readiness.Command, hostPlaces},
		{"readiness.expect", []string{p.Readiness.Expect}, hostPlaces},
		{"flow.command", p.Flow.Command, flowPlaces},
		{"burst.command", p.Burst.Command, burstPlaces},
	}
}

// Render renders a template's arguments, each {name} replaced by values[name]. A
// placeholder values does not hold is an error naming it, so a template a package
// validated renders whole or not at all.
func Render(template []string, values map[string]string) ([]string, error) {
	out := make([]string, len(template))
	for i, arg := range template {
		var missing []string
		out[i] = placeholder.ReplaceAllStringFunc(arg, func(m string) string {
			name := m[1 : len(m)-1]
			v, ok := values[name]
			if !ok {
				missing = append(missing, m)
			}
			return v
		})
		if len(missing) > 0 {
			return nil, fmt.Errorf("argument %q names %s, which nothing renders", arg, strings.Join(missing, ", "))
		}
	}
	return out, nil
}

// unrendered lists, in order, the placeholders of args that places does not hold.
func unrendered(args, places []string) []string {
	var out []string
	for _, arg := range args {
		for _, m := range placeholder.FindAllStringSubmatch(arg, -1) {
			if !slices.Contains(places, m[1]) {
				out = append(out, m[0])
			}
		}
	}
	return out
}

// ParsePackage decodes one package. Unknown fields are refused, so a typo in a contributed
// package fails at load rather than silently doing nothing; ValidatePackages names the
// field.
func ParsePackage(data []byte, path, origin string) (*Package, error) {
	dec := yaml.NewDecoder(strings.NewReader(string(data)))
	dec.KnownFields(true)
	var p Package
	if err := dec.Decode(&p); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	p.Origin = origin
	p.Path = path
	return &p, nil
}
