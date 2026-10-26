package server

import (
	"fmt"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// intent read's summary counts what the profiles make of the intent beside what it holds
// (contracts/cli.md): a platform that loses nothing counts two zeros, and the
// lossy design case the record the bundle will carry. From M7 the devices are broken down
// by support package in package id order, a read of one platform in the same shape as a
// mixed one. From 017 the line names the scope the read was made under, and says how many
// cables it could not place when it left any out, which the CTM's fidelity rows count.
// The line runRead prints is taken from the function it calls.
func TestReadSummaryCountsTheLossyRecord(t *testing.T) {
	for _, c := range []struct {
		fixture, pspDir, want string
		// omitted is how many cable rows the read's fidelity list gains.
		omitted int
	}{
		{"three-node.json", "", "wrote ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"lossy.json", repoPath("testdata", "psp", "lossy"), "wrote ctm.json: 3 devices (chassisos 2, nokia_srlinux 1), " +
			"16 interfaces, 3 links, 3 artifacts, 9 lossy mappings, 3 shared ports " +
			"(branch lossy-fixture, at 2026-09-19T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"mixed.json", "", "wrote ctm.json: 3 devices (arista_eos 2, nokia_srlinux 1), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch mixed-fixture, at 2026-09-20T12:00:00Z, scope tag:fylgja, schema fixture)", 0},
		{"three-node.json", "", "wrote ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports; 1 cable omitted (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 1},
		{"three-node.json", "", "wrote ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports; 2 cables omitted (branch fylgja-fixture, at 2026-09-08T12:00:00Z, scope tag:fylgja, schema fixture)", 2},
	} {
		t.Run(fmt.Sprintf("%s/%d omitted", c.fixture, c.omitted), func(t *testing.T) {
			snapshot, err := ctm.Load(repoPath("testdata", "ctm", c.fixture))
			if err != nil {
				t.Fatal(err)
			}
			for i := range c.omitted {
				snapshot.Envelope.Fidelity = append(snapshot.Envelope.Fidelity, ctm.FidelityRow{Disposition: ctm.FidelityOmitted,
					Object: fmt.Sprintf("c-%d", i), Source: "DcimCable", Reason: "other than two ends (3)"})
			}
			reg, err := psp.Load(c.pspDir)
			if err != nil {
				t.Fatal(err)
			}
			if got := readSummaryLine("ctm.json", snapshot, reg); got != c.want {
				t.Errorf("summary:\n%s\nwant:\n%s", got, c.want)
			}
		})
	}
}
