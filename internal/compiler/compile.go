// Package compiler turns intent into deployment artifacts.
//
// Compile is a pure function: a CTM and a platform registry in, a bundle out, no I/O of
// any kind — no files, no network, no clock, no randomness (Constitution V). That is
// what lets the riskiest logic in Fylgja be golden-file tested with zero
// infrastructure, and lets `fylgja twin compile` expose exactly the function the tests
// exercise. A purity test enforces the import boundary; treat a failure there as a
// design error, not a test to relax.
package compiler

import (
	"fmt"
	"path"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Compile turns a normalized CTM into the bundle's files, keyed by their path
// relative to the bundle root.
//
// The map is the bundle: internal/bundle writes it and hashes it, and nothing about
// the compiler's internal structure reaches either. There is no error return, because
// at this point there is no failure that is not a finding — everything the compiler
// cannot build faithfully it names.
//
// It assumes validation has already run: anything that cannot be built faithfully is a
// rejection raised before this point (internal/validate). What remains here are
// decisions with an honest answer — an interface a rule matched out of range that
// carries no link is omitted and recorded, not dropped; one no rule matches is
// interface.rule.unmatched, a refusal, since the gap is the profile's or the intent's.
// When a rejection does surface here, it means a caller skipped validation or
// the two disagree; no files are returned.
func Compile(c *ctm.CTM, reg *psp.Registry) (map[string][]byte, findings.List) {
	var list findings.List
	ctm.Normalize(c)

	// A twin of nothing cannot be built, and its manifest could not satisfy its own
	// fidelity contract: production_forwarding has no value for zero nodes. `intent
	// read` and `twin compile` both reject this through internal/validate long before
	// here; the guard exists for a caller that skipped it.
	if len(c.Devices) == 0 {
		list.Add(findings.Rejection, findings.RuleDevicesEmpty, emptyObject(c.Envelope),
			fmt.Sprintf("no devices in intent for %s; a twin of nothing cannot be built and has no fidelity to report",
				emptyWhere(c.Envelope)))
		return nil, list
	}

	var (
		nodes     []TopologyNode
		mNodes    []ManifestNode
		rows      []MappingRow
		omissions []Omission
		lossy     []LossyMapping
		configs   []ConfigFile
		approx    []string
	)
	// One entry per support package in the bundle, gathered in the device loop as
	// approximations are. Go's encoder sorts map keys, so the manifest's bytes do not
	// depend on the order devices arrive in.
	forwarding := map[string]string{}
	seenApprox := map[string]bool{}
	portOf := map[string]string{} // "device:interface" -> node port, for cabled links

	// Every device is surveyed before anything is built, so what the profiles cannot map
	// is reported for every device at once, in one pass, as validation reports it.
	// The refusals are validation's, mirrored word for word: reaching one
	// means a caller skipped validation or the two disagree.
	pkgs := make([]*psp.PSP, len(c.Devices))
	profs := make([]*psp.Profile, len(c.Devices))
	surveys := make([]DeviceSurvey, len(c.Devices))
	for i, d := range c.Devices {
		p, ok := reg.Lookup(d.Platform.NOS)
		if !ok {
			// Validation rejects this first; reaching it means the two disagree.
			list.Add(findings.Rejection, findings.RulePlatformUnsupported, d.Name,
				fmt.Sprintf("no support package for platform %q", d.Platform.NOS))
			return nil, list
		}
		prof, err := psp.NewProfile(p)
		if err != nil {
			list.Add(findings.Rejection, findings.RulePSPSchema, p.Platform.ID, err.Error())
			return nil, list
		}
		survey := SurveyDevice(d, prof, p.Platform.ID)
		if survey.Err != nil {
			list.Add(findings.Rejection, findings.RuleIftypeUnimplemented, d.Name, survey.Err.Error())
			return nil, list
		}
		list = append(list, survey.Refusals...)
		// The artifact's names against the rows, filed with this device's refusals and
		// before any rejection ends the pass: a warning never refuses a bundle,
		// and validation files it here too, so a refused intent reports the same list
		// from both callers.
		list = append(list, ArtifactNames(d, survey)...)
		pkgs[i], profs[i], surveys[i] = p, prof, survey
	}
	if list.Rejected() {
		return nil, list
	}

	for i, d := range c.Devices {
		p, prof, survey := pkgs[i], profs[i], surveys[i]
		devRows := survey.Rows
		rows = append(rows, devRows...)
		omissions = append(omissions, survey.Omissions...)
		lossy = append(lossy, survey.Lossy...)

		var cabledPorts []CabledPort
		for _, r := range devRows {
			if r.Port != nil {
				portOf[r.Device+":"+r.Interface] = *r.Port
			}
			if r.Disposition == DispCabled {
				// From bundle "3" every row with a port carries the node's own name for
				// it, equal to the production name where the platform keeps it, so the
				// bootstrap's {interface} renders from the row directly. A cabled row
				// always has one.
				cabledPorts = append(cabledPorts, CabledPort{Port: *r.Port, NodeName: *r.NodeName})
			}
		}
		// Port order, as when only the port was carried: the bootstrap's line order must
		// not depend on the order intent listed the interfaces in.
		sort.SliceStable(cabledPorts, func(i, j int) bool { return cabledPorts[i].Port < cabledPorts[j].Port })

		cfgName := d.Name + "." + configExt(p.Config.StartupFormat)
		cfgFile := path.Join(ConfigsDir, cfgName)
		configs = append(configs, ConfigFile{Name: cfgName, Content: renderBootstrap(p, d.Name, cabledPorts)})

		// The bootstrap file is written either way; what the package's bootstrap_via
		// decides is who applies it. Under the default the topology names it and the lab
		// tool applies it at deploy. Under "push" the topology names no startup-config,
		// because a kind that takes such a file as the whole configuration would boot
		// with nothing but the bootstrap; the push sends its lines ahead of the
		// artifact's instead, and the manifest's entry below says so. Keyed by a format
		// value, never by a platform (Constitution II).
		via := bootstrapVia(p)
		node := TopologyNode{
			Name:  d.Name,
			Kind:  p.Image.ClabKind,
			Image: p.Image.Ref,
		}
		if via == psp.BootstrapViaStartupConfig {
			node.StartupConfig = cfgFile
		}
		nodes = append(nodes, node)

		// The configuration Infrahub rendered, beside that node's bootstrap. The file
		// is named by the artifact's name, which must be the package's artifact_name:
		// the CTM is a file an operator can edit, and an artifact named as the
		// package's startup_format would overwrite the bootstrap, which is the node's
		// startup-config, and boot the node on intent-derived content. With the name
		// held to the package's, the two cannot collide, because a package whose
		// artifact_name equals its startup_format is refused at load.
		// The bytes are written exactly as intent carried them: never reordered, never
		// reformatted, not a newline added or removed (Constitution IV).
		//
		// The guards below are validation's, mirrored word for word, as the empty-CTM
		// and mixed-forwarding guards are: reaching any means a caller skipped
		// validation or the two disagree.
		if d.Artifact == nil {
			list.Add(findings.Rejection, findings.RuleArtifactMissing, d.Name, fmt.Sprintf(
				"device %q carries no configuration artifact; a CTM written before M5, or a read that did not fetch it",
				d.Name))
			return nil, list
		}
		if d.Artifact.Name != p.Config.ArtifactName {
			list.Add(findings.Rejection, findings.RuleArtifactMissing, d.Name, fmt.Sprintf(
				"device %q carries no configuration artifact named %q, as the %s package names it; the artifact it carries is named %q",
				d.Name, p.Config.ArtifactName, p.Platform.ID, d.Artifact.Name))
			return nil, list
		}
		content := []byte(d.Artifact.Content)
		if sum := ctm.ChecksumOf(d.Artifact.Content); sum != d.Artifact.Checksum {
			list.Add(findings.Rejection, findings.RuleArtifactChecksumMismatch, d.Name, fmt.Sprintf(
				"device %s: artifact %s has content hashing to %s, but records checksum %s",
				d.Name, d.Artifact.Name, sum, d.Artifact.Checksum))
			return nil, list
		}
		artifactName := d.Name + "." + d.Artifact.Name
		configs = append(configs, ConfigFile{Name: artifactName, Content: content})

		mNodes = append(mNodes, ManifestNode{
			Name:           d.Name,
			Platform:       d.Platform.NOS,
			PSP:            ManifestPSP{ID: p.Platform.ID, Source: p.Origin},
			Image:          p.Image.Ref,
			ManagementPort: prof.ManagementPort(),
			Artifact: &ManifestArtifact{
				Name:        d.Artifact.Name,
				ContentType: d.Artifact.ContentType,
				Checksum:    d.Artifact.Checksum,
				Size:        len(content),
				File:        path.Join(ConfigsDir, artifactName),
			},
			Bootstrap: ManifestBootstrap{File: cfgFile, Via: via},
		})

		// Forwarding and approximations are both gathered per platform, so a bundle of
		// two platforms carries both answers. Until bundle "3" the manifest held one
		// production_forwarding for the whole bundle, so two platforms that disagreed
		// had nowhere to put the second answer and the compiler refused such a twin
		// outright rather than assert either over the other's nodes — the kind of claim
		// a fidelity manifest must never make (D-025). The field is now an object keyed
		// by platform, so there is nothing left to refuse: the bundle simply says what
		// each platform declares.
		forwarding[p.Platform.ID] = p.Fidelity.ProductionForwarding
		// Deduplicated on the emitted string, not on the bare approximation: the
		// prefix is there to attribute the claim, so two platforms asserting the same
		// approximation must both appear. Keying on `a` alone credited whichever
		// platform was seen first and dropped the other's assertion.
		for _, a := range p.Fidelity.Approximations {
			claim := p.Platform.ID + ": " + a
			if !seenApprox[claim] {
				seenApprox[claim] = true
				approx = append(approx, claim)
			}
		}
	}

	links, linkOmissions := cableLinks(c, rows, portOf)
	omissions = append(omissions, linkOmissions...)

	for _, o := range omissions {
		list.Add(findings.Info, o.Rule, o.Object, o.Reason)
	}

	omitted := make([]string, 0, len(omissions))
	for _, o := range omissions {
		omitted = append(omitted, o.Object)
	}

	manifest := &Manifest{
		BundleVersion: BundleVersion,
		Provenance:    provenanceOf(c.Envelope),
		Nodes:         mNodes,
		Mapping:       rows,
		Links:         links,
		Omissions:     omissions,
		Fidelity: Fidelity{
			Basis:                FidelityAsserted,
			ProductionForwarding: forwarding,
			Approximations:       approx,
			Omitted:              omitted,
			Lossy:                lossy,
		},
	}
	manifestBytes, err := marshalManifest(manifest)
	if err != nil {
		// json.Marshal of a struct of strings and slices does not fail; if it ever
		// does, the bundle is not writable and saying so beats emitting half of one.
		list.Add(findings.Rejection, findings.RuleOperationFailed, "manifest.json", err.Error())
		return nil, list
	}

	topo, err := renderTopology(nodes, links)
	if err != nil {
		list.Add(findings.Rejection, findings.RuleOperationFailed, TopologyFile, err.Error())
		return nil, list
	}

	files := map[string][]byte{
		TopologyFile: topo,
		ManifestFile: manifestBytes,
	}
	for _, cfg := range configs {
		files[path.Join(ConfigsDir, cfg.Name)] = cfg.Content
	}
	return files, list
}

// ConfigFile is one node's startup configuration within the bundle.
type ConfigFile struct {
	Name    string // file name within configs/
	Content []byte
}

// emptyObject and emptyWhere name the intent reference an empty read came from. They
// match internal/validate's wording for the same rule: an operator must not be able to
// tell from the message which of the two produced it.
func emptyObject(e ctm.Envelope) string {
	object := e.Branch
	if object == "" {
		object = "envelope"
	}
	if e.At != "" {
		object += "@" + e.At
	}
	return object
}

func emptyWhere(e ctm.Envelope) string {
	where := fmt.Sprintf("branch %q", e.Branch)
	if e.At != "" {
		where += fmt.Sprintf(" at %s", e.At)
	}
	return where
}

// cableLinks turns intent's links into veth pairs, recording the ones it will not wire.
func cableLinks(c *ctm.CTM, rows []MappingRow, portOf map[string]string) ([]CabledLink, []Omission) {
	disp := map[string]Disposition{}
	for _, r := range rows {
		disp[r.Device+":"+r.Interface] = r.Disposition
	}

	var links []CabledLink
	var omissions []Omission
	for _, l := range c.Links {
		if len(l.Endpoints) != 2 {
			continue // rejected by validation; nothing sensible to emit
		}
		a, b := l.Endpoints[0], l.Endpoints[1]
		// A link landing on an out-of-band port describes the management network, which
		// containerlab provides itself. Wiring it would invent a topology intent never
		// asked for, so it is omitted — and recorded, so nobody has to wonder.
		if disp[a.ID()] == DispManagement || disp[b.ID()] == DispManagement ||
			disp[a.ID()] == DispOmitted || disp[b.ID()] == DispOmitted {
			rule := findings.RuleOmitLinkMgmtOnly
			reason := reasonOOB
			if disp[a.ID()] == DispOmitted || disp[b.ID()] == DispOmitted {
				rule, reason = findings.RuleOmitInterfaceUnmappable, reasonUnmappable
			}
			omissions = append(omissions, Omission{rule, l.ID, reason})
			continue
		}
		pa, oka := portOf[a.ID()]
		pb, okb := portOf[b.ID()]
		if !oka || !okb {
			omissions = append(omissions, Omission{findings.RuleOmitInterfaceUnmappable, l.ID, reasonUnmappable})
			continue
		}
		links = append(links, CabledLink{
			ID: l.ID,
			A:  NodePort{Node: a.Device, Port: pa},
			B:  NodePort{Node: b.Device, Port: pb},
		})
	}
	return links, omissions
}

// bootstrapVia reads a package's config.bootstrap_via with its default applied. A
// package that omits it means startup_config, which is what every package written before
// the field meant.
func bootstrapVia(p *psp.PSP) string {
	if p.Config.BootstrapVia == "" {
		return psp.BootstrapViaStartupConfig
	}
	return p.Config.BootstrapVia
}

// configExt maps a startup-config format onto a file extension. containerlab selects
// how to apply a startup config by extension, so this is load-bearing, not cosmetic.
func configExt(format string) string {
	switch format {
	case "cli":
		return "cli"
	case "xml":
		return "xml"
	default:
		return "json"
	}
}
