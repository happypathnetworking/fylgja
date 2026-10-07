//go:build e2e

package conformance

import (
	"context"
	"os"
	"slices"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// TestBootHalf is the suite's boot half on the twin this host holds (tier 3): the record under
// $FYLGJA_STATE_ROOT, the staged
// bundle's manifest, the packages as the worker loads them (embedded, or
// $FYLGJA_PSP_DIR), each node read by gNMI with the login its package names. One subtest
// per node per check; each node's success line is logged. It boots, pushes and changes
// nothing: scripts/e2e.sh runs it in case 1, on a twin that run made.
//
//	FYLGJA_STATE_ROOT=<absolute root> go test -count=1 -tags e2e ./internal/conformance -run '^TestBootHalf$' -v
func TestBootHalf(t *testing.T) {
	rec, manifest, err := readTwin(os.Getenv(lab.EnvStateRoot))
	if err != nil {
		t.Fatal(err)
	}
	pkgs, err := psp.Load(os.Getenv(lab.EnvPSPDir))
	if err != nil {
		t.Fatal(err)
	}

	reports := Boot(context.Background(), BootInput{
		Record: rec, Manifest: manifest, Packages: pkgs,
		Reader: lab.GNMIReader{}, Getenv: os.LookupEnv,
	})

	checked := 0
	for _, r := range reports {
		for _, node := range r.Nodes {
			checked++
			t.Run(node.Name, func(t *testing.T) {
				for _, check := range BootChecks {
					t.Run(check, func(t *testing.T) {
						for _, f := range r.Failures {
							// A failure of the package as a whole is every one of its nodes'.
							if f.Check == check && (f.Node == node.Name || f.Node == "") {
								t.Error(f.String())
							}
						}
					})
				}
				if node.Passed != "" {
					t.Log(node.Passed)
				}
			})
		}
	}
	names := make([]string, 0, checked)
	for _, r := range reports {
		for _, n := range r.Nodes {
			names = append(names, n.Name)
		}
	}
	t.Logf("boot half: %d nodes %v of run %s %s, bundle %s", checked, slices.Sorted(slices.Values(names)), rec.Run.WorkflowID, rec.Run.RunID, rec.BundleID)
}
