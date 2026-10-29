package validate

import (
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Validate runs every rule against a snapshot's body, its CTM and its probes, and returns
// all findings. probes is the probe registry, which may be nil where decls is empty.
//
// One pass, every finding: an operator fixing a branch should see the whole list, not
// discover the next problem on the next attempt. Nothing here writes, deploys, or
// decides — the caller looks at findings.List.Rejected to decide whether to proceed.
//
// The probes are placed by the one function the compiler also calls (016, R-01), and the
// devices, the artifacts and the links are then held on the placed CTM, as the compiler
// surveys it: a port a host is cabled to is checked as a cabled port, so an intent that
// validates with its probes compiles with them. A placement refused placed nothing, and
// intent alone is checked beside its refusals. A host is the placement's, not a device of
// intent: no device rule reads it.
func Validate(c *ctm.CTM, decls []probe.Probe, reg *psp.Registry, probes *probe.Registry) findings.List {
	var list findings.List
	ctm.Normalize(c)
	checkEnvelope(c, &list)
	checkDevicesPresent(c, &list)
	placed, hosts, placing := compiler.PlaceProbes(c, decls, probes)
	list = append(list, placing...)
	if placed == nil {
		placed = c
	}
	intent := withoutHosts(placed, hosts)
	checkDevices(intent, reg, &list)
	checkArtifacts(intent, reg, &list)
	checkLinks(placed, &list)
	return list
}

// withoutHosts is c with the placement's hosts left out of its devices, for the rules of a
// device of intent; its links are c's.
func withoutHosts(c *ctm.CTM, hosts map[string]compiler.Host) *ctm.CTM {
	if len(hosts) == 0 {
		return c
	}
	out := *c
	out.Devices = make([]ctm.Device, 0, len(c.Devices))
	for _, d := range c.Devices {
		if _, host := hosts[d.Name]; !host {
			out.Devices = append(out.Devices, d)
		}
	}
	return &out
}

// Intrinsic runs the rules of Validate that read no package, as Validate words and places
// them: the envelope's, the device list's, each device's name and its interfaces' names,
// and the links'. They hold of a CTM whatever packages compile it, so the server holds a
// snapshot file a client sends to them before it files the file, and a file they refuse is
// filed nowhere. What needs the server's packages (a platform no package matches, an
// interface its profile cannot map, an artifact) is Validate's alone, at compile, by which
// time the file is filed, as a read's take is (018, T082).
//
// An interface's name is checked here on every named device, where Validate checks it only
// on a device whose package it holds: a nameless interface is the CTM's fault, whatever its
// device's platform. Every other rejection here is one Validate makes of the same CTM.
func Intrinsic(c *ctm.CTM) findings.List {
	var list findings.List
	ctm.Normalize(c)
	checkEnvelope(c, &list)
	checkDevicesPresent(c, &list)
	seen := map[string]bool{}
	for _, d := range c.Devices {
		if !checkDeviceName(d, seen, &list) {
			continue
		}
		for _, in := range d.Interfaces {
			if in.Name == "" {
				addNamelessInterface(d.Name, &list)
			}
		}
	}
	checkLinks(c, &list)
	return list
}
