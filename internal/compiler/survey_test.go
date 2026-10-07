package compiler

import (
	"encoding/json"
	"testing"
)

// intent read counts the lossy record before any bundle exists, and a dry run counts it
// from the bundle; the operator must read one number from both.
// Counted here against the manifest's own record: its entries, and the distinct ports
// its sharing entries name.
func TestSurveyAgreesWithTheManifest(t *testing.T) {
	for _, c := range []struct {
		fixture string
		want    SurveyCounts
	}{
		{"testdata/ctm/lossy.json", SurveyCounts{LossyMappings: 9, SharedPorts: 3}},
		{"testdata/ctm/three-node.json", SurveyCounts{}},
	} {
		t.Run(c.fixture, func(t *testing.T) {
			reg := lossyRegistry(t)
			var m Manifest
			if err := json.Unmarshal(compileFixtureWith(t, c.fixture, reg)[ManifestFile], &m); err != nil {
				t.Fatal(err)
			}
			shared := map[string]bool{}
			for _, e := range m.Fidelity.Lossy {
				if len(e.Shares) > 0 {
					shared[e.Device+":"+e.Port] = true
				}
			}
			fromManifest := SurveyCounts{LossyMappings: len(m.Fidelity.Lossy), SharedPorts: len(shared)}

			if got := Survey(loadFixture(t, c.fixture), reg); got != c.want || got != fromManifest {
				t.Errorf("Survey = %+v; the manifest records %+v; want %+v", got, fromManifest, c.want)
			}
			if got := m.LossyCounts(); got != fromManifest {
				t.Errorf("Manifest.LossyCounts = %+v; the manifest records %+v", got, fromManifest)
			}
		})
	}
}
