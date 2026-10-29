package lab

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// CheckHost plans the bundle's nodes from this worker's support packages, reports what the
// host already holds, and refuses a create the host cannot take. It only reads — the
// bundle's manifest, `clab inspect --all`, a stat of the twin directory, whether variables
// are set — so a refused create leaves the host exactly as it found it.
//
// Every budget and the probe come from the package the node's manifest psp.id names on
// this worker, never from a constant (Constitution II). Refusals are
// findings in the result rather than errors — a refusal is an answer — and all of them are
// gathered in one pass, so an operator clears them together: lab present, twin directory
// present, memory over the host budget, a probe or push login variable unset, a package
// missing, an image a package says is not pulled that the host does not hold; a probe
// package missing, a probe image the host does not hold whatever its acquisition (016);
// then the warning that no host budget is set.
func (a *Activities) CheckHost(ctx context.Context, in wire.CheckHostInput) (wire.CheckHostResult, error) {
	m, err := readManifest(in.BundlePath)
	if err != nil {
		return wire.CheckHostResult{}, StepFailure(findings.StepHostCheck, findings.RuleOperationFailed, in.BundlePath, err.Error())
	}
	budget, budgetSet, err := HostBudgetMB(a.getenv())
	if err != nil {
		return wire.CheckHostResult{}, StepFailure(findings.StepHostCheck, findings.RuleOperationFailed, EnvHostMemoryMB, err.Error())
	}

	res := wire.CheckHostResult{
		Provenance: recordProvenance(m.Provenance),
		Findings:   findings.List{},
	}
	if budgetSet {
		res.HostBudgetMB = &budget
	}

	planned, err := planNodes(m, a.Registry, a.Probes)
	if err != nil {
		return wire.CheckHostResult{}, StepFailure(findings.StepHostCheck, findings.RuleOperationFailed, in.BundlePath, err.Error())
	}
	res.Nodes, res.MemorySumMB = planned.nodes, planned.memoryMB

	host, err := a.InspectHost(ctx)
	if err != nil {
		return wire.CheckHostResult{}, err
	}
	res.LabPresent, res.TwinDirPresent = host.Lab.Present, host.TwinDirPresent

	add := func(sev findings.Severity, rule, object, format string, args ...any) {
		res.Findings.AddStep(sev, findings.StepHostCheck, rule, object, fmt.Sprintf(format, args...))
	}
	// Both refusals name what is on the host with the one phrase the worker's host line
	// carries too; the node count on the lab clause is containerlab's.
	phrase := host.Describe()
	if host.Lab.Present {
		add(findings.Rejection, findings.RuleHostLabPresent, "lab "+LabName,
			"lab %s is present (%s), %s; one twin exists at a time, and fylgja twin destroy clears it",
			LabName, plural(len(host.Lab.Nodes), "node"), phrase)
	}
	if res.TwinDirPresent {
		add(findings.Rejection, findings.RuleHostTwinPresent, a.Paths.Twin,
			"twin directory %s is present, %s; fylgja twin destroy clears it", a.Paths.Twin, phrase)
	}
	perNode := memoryPerNode(res.Nodes)
	if budgetSet && res.MemorySumMB > budget {
		add(findings.Rejection, findings.RuleHostMemoryExceeded, "host",
			"sum %d MiB exceeds budget %d MiB (%s)", res.MemorySumMB, budget, perNode)
	}
	for _, l := range unsetLogins(res.Nodes, a.getenv()) {
		add(findings.Rejection, findings.RuleHostProbeLoginUnset, l.variable, "%s", l.message())
	}
	for _, id := range slices.Sorted(maps.Keys(planned.missingPSP)) {
		add(findings.Rejection, findings.RuleHostPSPMissing, id,
			"support package %s (manifest source %s), named by %s, is not on this worker",
			id, planned.sources[id], strings.Join(planned.missingPSP[id], ", "))
	}
	for _, id := range slices.Sorted(maps.Keys(planned.missingProbe)) {
		add(findings.Rejection, findings.RuleHostProbePackageMissing, id,
			"probe package %s (manifest source %s), named by host %s, is not on this worker",
			id, planned.probeSources[id], strings.Join(planned.missingProbe[id], ", "))
	}
	// The presence pass. One call per distinct reference, and none for a support package
	// that says public_registry: that is the one acquisition under which a device's deploy
	// may pull, so nothing is asked of the runtime for it. A probe package's image is asked
	// after whatever its acquisition says, since a host's deploy budget is sized for a
	// container that starts in a second and a pull inside a step's reconcile would be timed
	// as the step's (016, R-12).
	for _, ref := range slices.Sorted(maps.Keys(planned.needs)) {
		need := planned.needs[ref]
		present, err := a.presence(ctx, ref)
		if err != nil {
			return wire.CheckHostResult{}, StepFailure(findings.StepHostCheck, findings.RuleOperationFailed, ref, err.Error())
		}
		if present {
			continue
		}
		add(findings.Rejection, findings.RuleHostImageAbsent, ref,
			"image %s is not on this host: %s %s (nodes %s) declares it %s, %s",
			ref, need.what, strings.Join(need.packages, ", "), strings.Join(need.nodes, ", "),
			need.acquisition, imageRemedy(need.acquisition, ref))
	}
	if !budgetSet {
		add(findings.Warning, findings.RuleHostMemoryUnbudgeted, "host",
			"sum %d MiB (%s) is not checked against a host budget: %s is unset", res.MemorySumMB, perNode, EnvHostMemoryMB)
	}
	return res, nil
}

// CheckHost runs the host check without a workflow service. The dry run calls it in the
// CLI's own process, so what it reports is what the run's host check would.
func CheckHost(ctx context.Context, a *Activities, in wire.CheckHostInput) (wire.CheckHostResult, error) {
	return a.CheckHost(ctx, in)
}

// NodePlans is each node of the bundle at bundlePath planned from reg and probes as the
// host check plans it, by name, without looking at the host: what a rehearsal's deadline
// sums from every stage's budgets before the host is read (015, research R-09). A node
// whose package reg or probes does not hold is left out, as the host check leaves it out
// of its plan; the host check refuses it.
func NodePlans(bundlePath string, reg *psp.Registry, probes *probe.Registry) ([]wire.NodePlan, error) {
	m, err := readManifest(bundlePath)
	if err != nil {
		return nil, err
	}
	planned, err := planNodes(m, reg, probes)
	if err != nil {
		return nil, err
	}
	return planned.nodes, nil
}

// plannedNodes are a manifest's nodes planned from this worker's packages, with what the
// host check refuses of them: the support and probe packages it lacks, by id with the
// nodes naming each, and the images it must find already on the host.
type plannedNodes struct {
	nodes    []wire.NodePlan // by name
	memoryMB int             // the planned nodes' memory, summed

	missingPSP   map[string][]string // psp id → the nodes naming it
	sources      map[string]string   // psp id → the manifest's source for it
	missingProbe map[string][]string // probe package id → the hosts naming it
	probeSources map[string]string   // probe package id → the manifest's source for it
	needs        map[string]*imageNeed
}

// planNodes plans every node of m: a device from the support package its psp names, a
// host from the probe package its probe names (016, R-12). An error is a host the manifest
// does not describe whole, or a template its package's validation would have refused.
func planNodes(m compiler.Manifest, reg *psp.Registry, probes *probe.Registry) (plannedNodes, error) {
	out := plannedNodes{missingPSP: map[string][]string{}, sources: map[string]string{},
		missingProbe: map[string][]string{}, probeSources: map[string]string{}, needs: map[string]*imageNeed{}}
	for _, n := range m.Nodes {
		if n.Probe != nil {
			pkg, ok := lookupProbePackage(probes, n.Probe.Package.ID)
			if !ok {
				out.missingProbe[n.Probe.Package.ID] = append(out.missingProbe[n.Probe.Package.ID], n.Name)
				out.probeSources[n.Probe.Package.ID] = n.Probe.Package.Source
				continue
			}
			plan, err := hostPlan(m, n, pkg)
			if err != nil {
				return plannedNodes{}, err
			}
			out.nodes = append(out.nodes, plan)
			out.memoryMB += plan.MemoryMB
			out.noteImage(n.Name, "probe package", pkg.Format, pkg.Image.Ref, pkg.Image.Acquisition)
			continue
		}
		if n.PSP == nil {
			return plannedNodes{}, fmt.Errorf("the manifest's node %s names neither a support package nor a probe", n.Name)
		}
		p, ok := reg.LookupID(n.PSP.ID)
		if !ok {
			out.missingPSP[n.PSP.ID] = append(out.missingPSP[n.PSP.ID], n.Name)
			out.sources[n.PSP.ID] = n.PSP.Source
			continue
		}
		out.nodes = append(out.nodes, manifestNodePlan(n, p))
		out.memoryMB += p.Image.Resources.MemoryMB
		// A device's image is asked after only when its package says it is not pulled.
		if p.Image.Acquisition != psp.AcquisitionPublicRegistry {
			out.noteImage(n.Name, "support package", p.Platform.ID, p.Image.Ref, p.Image.Acquisition)
		}
	}
	sort.Slice(out.nodes, func(i, j int) bool { return out.nodes[i].Name < out.nodes[j].Name })
	return out, nil
}

// manifestNodePlan is one manifest node planned from its package, with the artifact its
// push carries.
func manifestNodePlan(n compiler.ManifestNode, p *psp.PSP) wire.NodePlan {
	plan := nodePlan(n.Name, n.Image, n.PSP.ID, n.PSP.Source, p)
	if n.Artifact != nil {
		plan.Artifact = &wire.PlanArtifact{File: n.Artifact.File, Checksum: n.Artifact.Checksum}
	}
	return plan
}

// lookupProbePackage is the probe package of a format, none when the worker holds no
// probe registry at all.
func lookupProbePackage(probes *probe.Registry, id string) (*probe.Package, bool) {
	if probes == nil {
		return nil, false
	}
	return probes.Lookup(id)
}

// hostPlan is a host's node planned from its probe package: the package's image budgets,
// memory and readiness timeout, and its readiness, flow and burst rendered for this host
// from the manifest's probes[] entry, as the compiler rendered its exec lines.
func hostPlan(m compiler.Manifest, n compiler.ManifestNode, pkg *probe.Package) (wire.NodePlan, error) {
	values, err := hostValues(m, *n.Probe)
	if err != nil {
		return wire.NodePlan{}, fmt.Errorf("host %s: %v", n.Name, err)
	}
	render := func(field string, template []string, extra map[string]string) ([]string, error) {
		v := maps.Clone(values)
		maps.Copy(v, extra)
		out, err := probe.Render(template, v)
		if err != nil {
			return nil, fmt.Errorf("host %s: probe package %s's %s: %v", n.Name, pkg.Format, field, err)
		}
		return out, nil
	}
	interval := strconv.FormatFloat(pkg.Flow.IntervalS, 'f', -1, 64)
	readiness, err := render("readiness.command", pkg.Readiness.Command, nil)
	if err != nil {
		return wire.NodePlan{}, err
	}
	expect, err := render("readiness.expect", []string{pkg.Readiness.Expect}, nil)
	if err != nil {
		return wire.NodePlan{}, err
	}
	flow, err := render("flow.command", pkg.Flow.Command, map[string]string{probe.PlaceInterval: interval})
	if err != nil {
		return wire.NodePlan{}, err
	}
	burst, err := render("burst.command", pkg.Burst.Command, map[string]string{probe.PlaceInterval: interval,
		probe.PlaceCount: strconv.Itoa(pkg.Burst.Count), probe.PlaceWait: strconv.Itoa(pkg.Burst.WaitS)})
	if err != nil {
		return wire.NodePlan{}, err
	}
	return wire.NodePlan{
		Name:            n.Name,
		Image:           n.Image,
		MemoryMB:        pkg.Image.Resources.MemoryMB,
		TimeoutS:        pkg.Readiness.TimeoutS,
		DeployTimeoutS:  pkg.Image.DeployTimeoutS,
		DestroyTimeoutS: pkg.Image.DestroyTimeoutS,
		Host: &wire.ProbePlan{
			Format:    pkg.Format,
			Package:   wire.PSPRef{ID: n.Probe.Package.ID, Source: n.Probe.Package.Source},
			Probe:     n.Probe.Name,
			Endpoint:  n.Probe.Endpoint,
			Readiness: wire.ExecProbe{Command: readiness, Expect: expect[0], TimeoutS: pkg.Readiness.TimeoutS},
			Flow: wire.FlowSpec{IntervalS: pkg.Flow.IntervalS, Command: flow,
				StartTimeoutS: pkg.Flow.StartTimeoutS, ReadTimeoutS: pkg.Flow.ReadTimeoutS},
			Burst: wire.BurstSpec{Count: pkg.Burst.Count, WaitS: pkg.Burst.WaitS, Command: burst},
		},
	}, nil
}

// hostValues are the four placeholders every template of a host renders: its address and
// gateway as declared, the far host's address without its prefix length, and its own port,
// read from the manifest's probes[] entry of the host's probe.
func hostValues(m compiler.Manifest, p compiler.ManifestProbe) (map[string]string, error) {
	for _, e := range m.Probes {
		if e.Name != p.Name {
			continue
		}
		for i, h := range e.Hosts {
			if h.Endpoint != p.Endpoint {
				continue
			}
			far, _, _ := strings.Cut(e.Hosts[1-i].Address, "/")
			return map[string]string{
				probe.PlaceAddress:    h.Address,
				probe.PlaceGateway:    h.Gateway,
				probe.PlaceFarAddress: far,
				probe.PlaceInterface:  h.Port,
			}, nil
		}
		return nil, fmt.Errorf("the manifest's probe %s has no endpoint %s", p.Name, p.Endpoint)
	}
	return nil, fmt.Errorf("the manifest's probes name no probe %s", p.Name)
}

// HostState is what the host holds of a twin: lab fylgja as containerlab reports it,
// whether a twin directory is present, and the twin record beside it, read only to
// describe what was detected.
//
// Twin == nil && TwinReadError == "" means no twin.json. A record that parses is taken
// as written: nothing in it is validated against containerlab, and nothing is reconciled.
type HostState struct {
	Lab            LabState
	TwinDirPresent bool
	Twin           *wire.TwinRecord // twin.json, when present and it parses
	TwinReadError  string           // why twin.json could not be read, when present but it does not open or parse; empty otherwise
}

// InspectHost reads what the host holds and changes nothing: `clab inspect --all` and a
// stat of the twin directory decide what is present, and twin.json is then read only to
// describe what was detected. The host check and the worker's start-up report both look
// through it, so what a worker reports at start is exactly what a create would be refused
// for (Constitution VII: orphan detection at create and at worker start).
//
// A record that cannot be read never fails the inspection: detection is unchanged, the
// host check must still run, and the reason is carried in TwinReadError instead.
func (a *Activities) InspectHost(ctx context.Context) (HostState, error) {
	state, err := a.Clab.InspectAll(ctx)
	if err != nil {
		return HostState{}, err
	}
	present, err := exists(a.Paths.Twin)
	if err != nil {
		return HostState{}, fmt.Errorf("inspecting the twin directory: %w", err)
	}
	host := HostState{Lab: state, TwinDirPresent: present}
	if !present {
		return host, nil
	}
	rec, err := ReadRecord(a.Paths.TwinJSON)
	switch {
	case err == nil:
		host.Twin = &rec
	case errors.Is(err, fs.ErrNotExist):
		// no twin.json: an orphan, or a run cut short before it recorded the twin
	default:
		host.TwinReadError = err.Error() // names the path, never a credential
	}
	return host, nil
}

// nodePlan is one manifest node with the budgets, probe and push its package gives it.
func nodePlan(name, image, pspID, pspSource string, p *psp.PSP) wire.NodePlan {
	r, c := p.Readiness, p.Config
	// A package that omits readiness.tls means TLS, which is what every package written
	// before the field meant.
	tls := true
	if r.TLS != nil {
		tls = *r.TLS
	}
	push := wire.PushSpec{
		Delivery: c.Delivery,
		Mode:     c.Mode,
		Commit:   c.Commit,
		TimeoutS: c.PushTimeoutS,
	}
	// A package whose delivery needs no address leaves push unset.
	if c.Push != nil {
		push.Scheme, push.Port = c.Push.Scheme, c.Push.Port
		push.UsernameEnv, push.PasswordEnv = c.Push.Login.UsernameEnv, c.Push.Login.PasswordEnv
	}
	return wire.NodePlan{
		Name:            name,
		PSPID:           pspID,
		PSPSource:       pspSource,
		Image:           image,
		MemoryMB:        p.Image.Resources.MemoryMB,
		TimeoutS:        r.TimeoutS,
		DeployTimeoutS:  p.Image.DeployTimeoutS,
		DestroyTimeoutS: p.Image.DestroyTimeoutS,
		Probe: wire.Probe{
			Transport:   r.Probe,
			Path:        r.Path,
			Encoding:    r.Encoding,
			Port:        r.PortOrDefault(),
			UsernameEnv: r.Login.UsernameEnv,
			PasswordEnv: r.Login.PasswordEnv,
			// Set explicitly, with the package's default applied, so a plan this build
			// writes never leaves the dial to be inferred from an absent key.
			TLS: &tls,
		},
		Push: push,
		// The package's own answer to whether its probe answering means the node can be
		// configured (D-029).
		AwaitPushTransport: r.AwaitPushTransport,
	}
}

// imageNeed is one image reference planned nodes need already on this host: the packages
// that declare it, what kind of package they are, how they say it is obtained, and the
// nodes that would run it. Keyed by the reference the package declares, which is the
// reference the compiler wrote into the manifest and the topology, so the worker's
// start-up report and this check look for the same thing.
type imageNeed struct {
	what        string // "support package", or "probe package" (016)
	acquisition string
	packages    []string // the package ids declaring it, in name order; one, but for a reference two packages share
	nodes       []string // the nodes running it, in the order the manifest lists them, which is name order
}

// noteImage records that node runs ref, declared by the package id of kind what under
// acquisition. The caller decides which images are asked after: every probe package's, and
// a support package's unless it says public_registry.
func (p *plannedNodes) noteImage(node, what, id, ref, acquisition string) {
	need, seen := p.needs[ref]
	if !seen {
		need = &imageNeed{what: what, acquisition: acquisition}
		p.needs[ref] = need
	}
	if !slices.Contains(need.packages, id) {
		need.packages = append(need.packages, id)
		slices.Sort(need.packages)
	}
	need.nodes = append(need.nodes, node)
}

// imageRemedy is what host.image.absent says after the acquisition: how an image of it is
// obtained, then that another tag is no match. A public_registry image reaches here only
// from a probe package, and its remedy is the pull the run never makes (016, R-12).
func imageRemedy(acquisition, ref string) string {
	if acquisition == psp.AcquisitionPublicRegistry {
		return "which a run never pulls, since a host's deploy budget is sized for a container already held: " +
			"docker pull " + ref + " fetches it; a reference held under another tag is absent"
	}
	return acquisitionClause(acquisition) + "; a reference held under another tag is absent; " +
		"docs/development.md says how to import it"
}

// acquisitionClause says how an image of this acquisition is obtained, as the refusal
// words it (contracts/cli.md). One clause per value: the refusal must not
// claim "with an account" of a value that is not account_gated. public_registry never
// reaches here: imageRemedy words it.
func acquisitionClause(acquisition string) string {
	switch acquisition {
	case psp.AcquisitionAccountGated:
		return "obtained from the vendor with an account and imported by hand under exactly that reference, never pulled"
	case psp.AcquisitionLicensed:
		return "obtained under a licence and imported by hand under exactly that reference, never pulled"
	case psp.AcquisitionVrnetlabVM:
		return "built locally from a vendor VM image with vrnetlab under exactly that reference, never pulled"
	default:
		// The format's enum names no other value, so a package that reaches here was not
		// read through the schema. It is named without claiming how it is obtained.
		return "obtained as its acquisition says and imported by hand under exactly that reference, never pulled"
	}
}

// presence asks the image driver whether the host holds ref. An Activities built without
// one — a caller that only ever checks public_registry bundles, where nothing is asked —
// reports that rather than reaching for a runtime nobody named.
func (a *Activities) presence(ctx context.Context, ref string) (bool, error) {
	if a.Images == nil {
		return false, fmt.Errorf("whether image %s is on this host cannot be read: this worker has no image driver", ref)
	}
	return a.Images.Present(ctx, ref)
}

// memoryPerNode names each node with its memory budget: "n1 2048, n2 2048".
func memoryPerNode(nodes []wire.NodePlan) string {
	if len(nodes) == 0 {
		return "no node planned"
	}
	parts := make([]string, len(nodes))
	for i, n := range nodes {
		parts[i] = fmt.Sprintf("%s %d", n.Name, n.MemoryMB)
	}
	return strings.Join(parts, ", ")
}

// The uses a login variable is named for, as host.probe.login_unset words them.
const (
	useProbeLogin = "readiness probe login"
	usePushLogin  = "push login"
)

// unsetLogin is a login variable unset on the worker, the packages naming it, and what
// they name it for: the readiness probe, the push, or both (M5 contracts/cli.md).
type unsetLogin struct {
	variable  string
	platforms []string
	uses      []string // useProbeLogin before usePushLogin
}

// unsetLogins lists, in the order the nodes first name them, the probe and push login
// variables the bundle's packages name that are unset or empty on this worker. A variable
// named for both uses is listed once. Only presence is looked at; no value is kept, so
// none can reach a finding.
func unsetLogins(nodes []wire.NodePlan, getenv func(string) (string, bool)) []unsetLogin {
	var out []unsetLogin
	index := map[string]int{}
	for _, n := range nodes {
		// A host logs in nowhere: its readiness is an exec in its container (016).
		if n.Host != nil {
			continue
		}
		named := []struct{ variable, use string }{
			{n.Probe.UsernameEnv, useProbeLogin}, {n.Probe.PasswordEnv, useProbeLogin},
			{n.Push.UsernameEnv, usePushLogin}, {n.Push.PasswordEnv, usePushLogin},
		}
		for _, v := range named {
			if v.variable == "" || isSet(getenv, v.variable) {
				continue
			}
			i, seen := index[v.variable]
			if !seen {
				i = len(out)
				index[v.variable] = i
				out = append(out, unsetLogin{variable: v.variable})
			}
			if !slices.Contains(out[i].platforms, n.PSPID) {
				out[i].platforms = append(out[i].platforms, n.PSPID)
			}
			if !slices.Contains(out[i].uses, v.use) {
				out[i].uses = append(out[i].uses, v.use)
			}
		}
	}
	for i := range out {
		slices.SortFunc(out[i].uses, func(a, b string) int { return useOrder(a) - useOrder(b) })
	}
	return out
}

// message words host.probe.login_unset as the host check has since M2, with M5's uses: the
// one sentence the host check and ProbeLoginsUnset both give, so the two cannot drift.
func (l unsetLogin) message() string {
	return fmt.Sprintf("%s is unset on this worker; support package %s names it for its %s",
		l.variable, strings.Join(l.platforms, ", "), strings.Join(l.uses, " and its "))
}

// ProbeLoginsUnset refuses the readiness probe login variables the nodes' packages name that
// are unset or empty, as the host check refuses them: twin verify reads
// each node over its package's probe, and a read without its login would fail at every node
// for a reason the operator can clear before any is read. Each finding is a rejection under
// host.probe.login_unset, object the variable, worded as the host check words it; its step is
// the caller's to set (observe, in twin verify). Only the probe's uses are looked at, each
// node's Push set aside, so a push login is neither reported nor named beside a probe one.
// No value is kept.
func ProbeLoginsUnset(nodes []wire.NodePlan, getenv func(string) (string, bool)) findings.List {
	probes := make([]wire.NodePlan, len(nodes))
	for i, n := range nodes {
		probes[i] = wire.NodePlan{Name: n.Name, PSPID: n.PSPID, Probe: n.Probe}
	}
	var out findings.List
	for _, l := range unsetLogins(probes, getenv) {
		out.Add(findings.Rejection, findings.RuleHostProbeLoginUnset, l.variable, l.message())
	}
	return out
}

func useOrder(use string) int {
	if use == useProbeLogin {
		return 0
	}
	return 1
}

func isSet(getenv func(string) (string, bool), name string) bool {
	v, ok := getenv(name)
	return ok && v != ""
}

// plural counts a noun: "1 node", "3 nodes".
func plural(n int, noun string) string {
	if n == 1 {
		return "1 " + noun
	}
	return fmt.Sprintf("%d %ss", n, noun)
}

// readManifest reads a bundle's manifest.json.
func readManifest(bundleDir string) (compiler.Manifest, error) {
	path := filepath.Join(bundleDir, compiler.ManifestFile)
	b, err := os.ReadFile(path)
	if err != nil {
		return compiler.Manifest{}, fmt.Errorf("reading the bundle manifest: %w", err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return compiler.Manifest{}, fmt.Errorf("reading %s: %w", path, err)
	}
	return m, nil
}

// recordProvenance is the manifest's provenance as twin.json 8 records it: the block
// verbatim, the scope and the mapping included (017).
func recordProvenance(p compiler.Provenance) wire.Provenance {
	return wire.Provenance{Branch: p.Branch, At: p.At, SchemaHash: p.SchemaHash, Scope: p.Scope,
		Mapping: wire.Mapping{Reader: p.Mapping.Reader, Model: p.Mapping.Model, Version: p.Mapping.Version}}
}

// exists reports whether anything is at path, without following a final symlink.
func exists(path string) (bool, error) {
	_, err := os.Lstat(path)
	switch {
	case err == nil:
		return true, nil
	case errors.Is(err, fs.ErrNotExist):
		return false, nil
	default:
		return false, err
	}
}
