package server

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// intent read's summary counts what the profiles make of the intent beside what it holds
// (contracts/cli.md): a platform that loses nothing counts two zeros, and the
// lossy design case the record the bundle will carry. From M7 the devices are broken down
// by support package in package id order, a read of one platform in the same shape as a
// mixed one. No fake Infrahub answers a read in tier 1, so the line runRead
// prints is taken from the function it calls.
func TestReadSummaryCountsTheLossyRecord(t *testing.T) {
	for _, c := range []struct {
		fixture, pspDir, want string
	}{
		{"three-node.json", "", "wrote ctm.json: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch fylgja-fixture, at 2026-09-08T12:00:00Z, schema fixture)"},
		{"lossy.json", repoPath("testdata", "psp", "lossy"), "wrote ctm.json: 3 devices (chassisos 2, nokia_srlinux 1), " +
			"19 interfaces, 3 links, 3 artifacts, 9 lossy mappings, 3 shared ports " +
			"(branch lossy-fixture, at 2026-09-19T12:00:00Z, schema fixture)"},
		{"mixed.json", "", "wrote ctm.json: 3 devices (arista_eos 2, nokia_srlinux 1), 12 interfaces, 3 links, 3 artifacts, " +
			"0 lossy mappings, 0 shared ports (branch mixed-fixture, at 2026-09-20T12:00:00Z, schema fixture)"},
	} {
		t.Run(c.fixture, func(t *testing.T) {
			snapshot, err := ctm.Load(repoPath("testdata", "ctm", c.fixture))
			if err != nil {
				t.Fatal(err)
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
