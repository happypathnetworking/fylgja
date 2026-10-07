package verify

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"regexp"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
)

// describe writes an assertion as one comparable line: its kind, node and port, the node's
// own name for the port, and for a link end the far end it must see, the link and which
// end; a skip's reason last.
func describe(a Assertion) string {
	s := a.Kind + " " + a.Node
	if a.Port != "" {
		s += fmt.Sprintf(":%s (%s)", a.Port, a.NodeName)
	}
	if a.Kind == KindHostName {
		s += " is " + a.Expected
	}
	if a.Kind == KindNeighbor {
		s += fmt.Sprintf(" sees %s on %s (%s)", a.Expected, a.Link, a.End)
		if a.Expected != a.FarNode+" "+a.FarPort {
			s += " MISMATCHED FAR END"
		}
	}
	if a.Outcome != "" || a.Reason != "" {
		s += fmt.Sprintf(" [%s: %s]", a.Outcome, a.Reason)
	}
	return s
}

func describeAll(as []Assertion) []string {
	out := make([]string, len(as))
	for i, a := range as {
		out[i] = describe(a)
		if a.Path != "" {
			out[i] += " PATH SET BEFORE THE READ"
		}
	}
	return out
}

// The golden twins' assertions, each by kind, node and port, in node order and within a
// node host name, ports, neighbours: three host names, six ports and six link ends each.
// The far end's port is the far node's own name for it, so the lossy twin's chassisos
// ports are seen as Ethernet1 and Ethernet49, not as their production names.
var goldenAssertions = map[string][]string{
	"three-node": {
		"host_name n1 is n1",
		"port_enabled n1:ethernet-1/1 (ethernet-1/1)",
		"port_enabled n1:ethernet-1/2 (ethernet-1/2)",
		"neighbor n1:ethernet-1/1 (ethernet-1/1) sees n2 ethernet-1/1 on n1:ethernet-1/1|n2:ethernet-1/1 (a)",
		"neighbor n1:ethernet-1/2 (ethernet-1/2) sees n3 ethernet-1/2 on n1:ethernet-1/2|n3:ethernet-1/2 (a)",
		"host_name n2 is n2",
		"port_enabled n2:ethernet-1/1 (ethernet-1/1)",
		"port_enabled n2:ethernet-1/2 (ethernet-1/2)",
		"neighbor n2:ethernet-1/1 (ethernet-1/1) sees n1 ethernet-1/1 on n1:ethernet-1/1|n2:ethernet-1/1 (b)",
		"neighbor n2:ethernet-1/2 (ethernet-1/2) sees n3 ethernet-1/1 on n2:ethernet-1/2|n3:ethernet-1/1 (a)",
		"host_name n3 is n3",
		"port_enabled n3:ethernet-1/1 (ethernet-1/1)",
		"port_enabled n3:ethernet-1/2 (ethernet-1/2)",
		"neighbor n3:ethernet-1/1 (ethernet-1/1) sees n2 ethernet-1/2 on n2:ethernet-1/2|n3:ethernet-1/1 (b)",
		"neighbor n3:ethernet-1/2 (ethernet-1/2) sees n1 ethernet-1/2 on n1:ethernet-1/2|n3:ethernet-1/2 (b)",
	},
	"lossy": {
		"host_name c1 is c1",
		"port_enabled c1:Ethernet1/1 (Ethernet1)",
		"port_enabled c1:Ethernet1/49/1 (Ethernet49)",
		"neighbor c1:Ethernet1/1 (Ethernet1) sees s1 ethernet-1/1 on c1:Ethernet1/1|s1:ethernet-1/1 (a)",
		"neighbor c1:Ethernet1/49/1 (Ethernet49) sees c2 Ethernet49 on c1:Ethernet1/49/1|c2:Ethernet1/49/1 (a)",
		"host_name c2 is c2",
		"port_enabled c2:Ethernet1/49/1 (Ethernet49)",
		"port_enabled c2:Ethernet2/1 (Ethernet1)",
		"neighbor c2:Ethernet1/49/1 (Ethernet49) sees c1 Ethernet49 on c1:Ethernet1/49/1|c2:Ethernet1/49/1 (b)",
		"neighbor c2:Ethernet2/1 (Ethernet1) sees s1 ethernet-1/2/1 on c2:Ethernet2/1|s1:ethernet-1/2/1 (a)",
		"host_name s1 is s1",
		"port_enabled s1:ethernet-1/1 (ethernet-1/1)",
		"port_enabled s1:ethernet-1/2/1 (ethernet-1/2/1)",
		"neighbor s1:ethernet-1/1 (ethernet-1/1) sees c1 Ethernet1 on c1:Ethernet1/1|s1:ethernet-1/1 (b)",
		"neighbor s1:ethernet-1/2/1 (ethernet-1/2/1) sees c2 Ethernet1 on c2:Ethernet2/1|s1:ethernet-1/2/1 (b)",
	},
	"mixed": {
		"host_name e1 is e1",
		"port_enabled e1:Ethernet1 (Ethernet1)",
		"port_enabled e1:Ethernet2/1 (Ethernet2/1)",
		"neighbor e1:Ethernet1 (Ethernet1) sees s1 ethernet-1/1 on e1:Ethernet1|s1:ethernet-1/1 (a)",
		"neighbor e1:Ethernet2/1 (Ethernet2/1) sees e2 Ethernet1 on e1:Ethernet2/1|e2:Ethernet1 (a)",
		"host_name e2 is e2",
		"port_enabled e2:Ethernet1 (Ethernet1)",
		"port_enabled e2:Ethernet3/1/1 (Ethernet3/1/1)",
		"neighbor e2:Ethernet1 (Ethernet1) sees e1 Ethernet2/1 on e1:Ethernet2/1|e2:Ethernet1 (b)",
		"neighbor e2:Ethernet3/1/1 (Ethernet3/1/1) sees s1 ethernet-1/2 on e2:Ethernet3/1/1|s1:ethernet-1/2 (a)",
		"host_name s1 is s1",
		"port_enabled s1:ethernet-1/1 (ethernet-1/1)",
		"port_enabled s1:ethernet-1/2 (ethernet-1/2)",
		"neighbor s1:ethernet-1/1 (ethernet-1/1) sees e1 Ethernet1 on e1:Ethernet1|s1:ethernet-1/1 (b)",
		"neighbor s1:ethernet-1/2 (ethernet-1/2) sees e2 Ethernet3/1/1 on e2:Ethernet3/1/1|s1:ethernet-1/2 (b)",
	},
}

// Every golden's manifest gives exactly its assertions: one host name per node, one port
// state per cabled row and one neighbour per end of each link, in node order, with nothing
// of discovering, the version, an uncabled port or an omitted interface, and no
// path until the read knows the package.
func TestDeriveGoldens(t *testing.T) {
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			got, err := Derive(goldenManifest(t, name))
			if err != nil {
				t.Fatal(err)
			}
			if want := goldenAssertions[name]; !reflect.DeepEqual(describeAll(got), want) {
				t.Errorf("Derive =\n%s\nwant\n%s", lines(describeAll(got)), lines(want))
			}
			kinds := map[string]int{}
			for _, a := range got {
				kinds[a.Kind]++
			}
			if want := map[string]int{KindHostName: 3, KindPortEnabled: 6, KindNeighbor: 6}; !reflect.DeepEqual(kinds, want) {
				t.Errorf("kinds = %v, want %v", kinds, want)
			}
		})
	}
}

// A cabled port intent disables is skipped, and so is each end of the link on it, with
// their reasons; nothing else is. The port is still cabled, so the
// assertions are still derived: only their outcome says they are not asserted.
func TestDeriveSkipsADisabledPortAndItsLink(t *testing.T) {
	m := disable(t, goldenManifest(t, "three-node"), "n1", "ethernet-1/2")
	got, err := Derive(m)
	if err != nil {
		t.Fatal(err)
	}
	want := append([]string(nil), goldenAssertions["three-node"]...)
	const link = "link n1:ethernet-1/2|n3:ethernet-1/2 is not asserted: intent disables n1:ethernet-1/2"
	want[2] += " [skipped: intent disables n1:ethernet-1/2]"
	want[4] += " [skipped: " + link + "]"
	want[14] += " [skipped: " + link + "]"
	if !reflect.DeepEqual(describeAll(got), want) {
		t.Errorf("Derive =\n%s\nwant\n%s", lines(describeAll(got)), lines(want))
	}
}

// Both ends disabled: each end's skip names both, so the link's two skips agree.
func TestDeriveSkipsALinkBothOfWhoseEndsAreDisabled(t *testing.T) {
	m := disable(t, disable(t, goldenManifest(t, "three-node"), "n1", "ethernet-1/2"), "n3", "ethernet-1/2")
	got, err := Derive(m)
	if err != nil {
		t.Fatal(err)
	}
	const reason = "link n1:ethernet-1/2|n3:ethernet-1/2 is not asserted: intent disables n1:ethernet-1/2 and n3:ethernet-1/2"
	for _, i := range []int{4, 14} {
		if got[i].Outcome != Skipped || got[i].Reason != reason {
			t.Errorf("%s: outcome %q reason %q, want skipped: %q", describe(got[i]), got[i].Outcome, got[i].Reason, reason)
		}
	}
}

// A manifest of bundle "3" has no enabled key, and every port of it is asserted: the CTM's
// own default.
func TestDeriveAssertsEveryPortOfABundle3Manifest(t *testing.T) {
	b, err := os.ReadFile(repo("testdata", "golden", "three-node", "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	stripped := regexp.MustCompile(`(?m)^\s*"enabled": (true|false),\n`).ReplaceAll(b, nil)
	stripped = regexp.MustCompile(`"bundle_version": "4"`).ReplaceAll(stripped, []byte(`"bundle_version": "3"`))
	var m compiler.Manifest
	if err := json.Unmarshal(stripped, &m); err != nil {
		t.Fatal(err)
	}
	for _, r := range m.Mapping {
		if r.Enabled != nil {
			t.Fatalf("row %s:%s still carries enabled", r.Device, r.Interface)
		}
	}
	got, err := Derive(m)
	if err != nil {
		t.Fatal(err)
	}
	if want := goldenAssertions["three-node"]; !reflect.DeepEqual(describeAll(got), want) {
		t.Errorf("Derive =\n%s\nwant\n%s", lines(describeAll(got)), lines(want))
	}
}

// What the compiler never emits is refused, naming the link or the row.
func TestDeriveRefusesAManifestTheCompilerNeverEmits(t *testing.T) {
	t.Run("a link end with no cabled row", func(t *testing.T) {
		m := goldenManifest(t, "three-node")
		m.Links = append([]compiler.CabledLink(nil), m.Links...)
		m.Links[0].B.Port = "e1-9"
		_, err := Derive(m)
		want := "link n1:ethernet-1/1|n2:ethernet-1/1 names n2 port e1-9, which has no cabled mapping row"
		if err == nil || err.Error() != want {
			t.Errorf("err = %v, want %q", err, want)
		}
		wantObject(t, err, "n1:ethernet-1/1|n2:ethernet-1/1")
	})
	t.Run("a cabled row no link names", func(t *testing.T) {
		m := goldenManifest(t, "three-node")
		m.Links = append([]compiler.CabledLink(nil), m.Links[1:]...)
		_, err := Derive(m)
		want := "n1:ethernet-1/1 is cabled on port e1-1, which no link names"
		if err == nil || err.Error() != want {
			t.Errorf("err = %v, want %q", err, want)
		}
		wantObject(t, err, "n1:ethernet-1/1")
	})
}

// wantObject holds a Derive error to the object twin verify's finding names: the link, or
// the row.
func wantObject(t *testing.T, err error, object string) {
	t.Helper()
	var me *ManifestError
	if !errors.As(err, &me) || me.Object != object {
		t.Errorf("err = %#v, want a *ManifestError naming %q", err, object)
	}
}

func lines(l []string) string {
	s := ""
	for _, x := range l {
		s += "  " + x + "\n"
	}
	return s
}
