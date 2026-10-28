package validate

import (
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Validate runs every rule against intent and returns all findings.
//
// One pass, every finding: an operator fixing a branch should see the whole list, not
// discover the next problem on the next attempt. Nothing here writes, deploys, or
// decides — the caller looks at findings.List.Rejected to decide whether to proceed.
func Validate(c *ctm.CTM, reg *psp.Registry) findings.List {
	var list findings.List
	ctm.Normalize(c)
	checkEnvelope(c, &list)
	checkDevicesPresent(c, &list)
	checkDevices(c, reg, &list)
	checkArtifacts(c, reg, &list)
	checkLinks(c, &list)
	return list
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
