package compiler

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The token rule, which decides whether an artifact names an interface at all.
// It is the whole difference between a warning an operator can act on
// and one raised about a port whose name merely begins another's — on a modular naming
// scheme, most of them.
func TestFirstLineNamingIsATokenRule(t *testing.T) {
	for _, c := range []struct {
		name, want, content string
		line                int
	}{
		{"the name alone on its line", "Ethernet1", "hostname c1\ninterface Ethernet1\n", 2},
		{"a longer name does not contain it", "Ethernet1", "interface Ethernet10\n   no shutdown\n", 0},
		{"nor does a name it is the prefix of", "Ethernet1", "interface Ethernet1/1\n", 0},
		{"nor one it is the suffix of", "Ethernet1", "interface Ethernet11\n", 0},
		{"a subinterface names its port", "ethernet-1/1", "set / network-instance default interface ethernet-1/1.0\n", 1},
		{"a quoted description names it", "ethernet-1/2", "set / interface ethernet-1/1 description \"to n2 ethernet-1/2\"\n", 1},
		{"the first occurrence is the one named", "Ethernet2/1", "! header\ninterface Ethernet2/1\n   no shutdown\ninterface Ethernet2/1\n", 2},
		{"a name the artifact never uses", "Ethernet9", "interface Ethernet1\n", 0},
		{"a name at the very start of the content", "Ethernet1", "Ethernet1\n", 1},
	} {
		t.Run(c.name, func(t *testing.T) {
			line, ok := firstLineNaming(c.content, c.want)
			if ok != (c.line != 0) || line != c.line {
				t.Errorf("firstLineNaming(%q, %q) = %d, %v; want %d", c.content, c.want, line, ok, c.line)
			}
		})
	}
}

// surveyFor builds one device on the design-case package and surveys it, as both callers
// do before they ask what its artifact names.
func surveyFor(t *testing.T, d ctm.Device) DeviceSurvey {
	t.Helper()
	p, ok := lossyRegistry(t).Lookup(d.Platform.NOS)
	if !ok {
		t.Fatalf("no package for nos %q", d.Platform.NOS)
	}
	prof, err := psp.NewProfile(p)
	if err != nil {
		t.Fatal(err)
	}
	return SurveyDevice(d, prof, p.Platform.ID)
}

func chassisDevice(artifact string, interfaces ...ctm.Interface) ctm.Device {
	return ctm.Device{
		Name:       "c1",
		Platform:   ctm.Platform{Vendor: "example", NOS: "chassisos", Version: "0"},
		Interfaces: interfaces,
		Artifact: &ctm.Artifact{
			Name: "device-config", ContentType: "text/plain",
			Checksum: ctm.ChecksumOf(artifact), Content: artifact,
		},
	}
}

func objectsWarned(t *testing.T, d ctm.Device) []string {
	t.Helper()
	var out []string
	for _, f := range ArtifactNames(d, surveyFor(t, d)) {
		out = append(out, f.Object)
	}
	return out
}

// Which rows are eligible at all, before the artifact is read: one the node calls
// something else, and one the twin does not represent. A row the twin gives no port —
// every loopback, on every platform — is neither, however often the artifact names it.
// Without that exception the tree's every artifact
// would warn about its loopback.
func TestArtifactNamesWarnsOnRenamedAndOmittedRowsOnly(t *testing.T) {
	d := chassisDevice(
		"hostname c1\n"+
			"interface Ethernet1/1\n"+ // renamed: the node calls it Ethernet1
			"interface Ethernet1/53\n"+ // omitted: out of the rule's range, uncabled
			"interface Loopback0\n"+ // portless: the node calls it nothing
			"interface Management1\n", // renamed: the node calls it Management0
		ctm.Interface{Name: "Ethernet1/1", Iftype: ctm.IftypePhysical},
		ctm.Interface{Name: "Ethernet1/53", Iftype: ctm.IftypePhysical},
		ctm.Interface{Name: "Loopback0", Iftype: ctm.IftypeLoopback},
		ctm.Interface{Name: "Management1", Iftype: ctm.IftypePhysical, MgmtOnly: true},
	)
	want := []string{"c1:Ethernet1/1", "c1:Ethernet1/53", "c1:Management1"}
	if got := objectsWarned(t, d); !equalStrings(got, want) {
		t.Errorf("warned about %v, want %v", got, want)
	}
}

// A row the artifact never names draws nothing: the warning is about a line an operator
// can go and look at, so with no such line there is nothing to say. The mapping row is
// recorded in the manifest either way.
func TestArtifactNamesSaysNothingAboutALineTheArtifactLacks(t *testing.T) {
	d := chassisDevice("hostname c1\ninterface Ethernet1/2\n",
		ctm.Interface{Name: "Ethernet1/1", Iftype: ctm.IftypePhysical},
	)
	if got := objectsWarned(t, d); len(got) != 0 {
		t.Errorf("warned about %v; the artifact names none of them", got)
	}
}

// An interface with no name is one defect, reported by validation as the missing name it
// is. Scanning an artifact for the empty string would match its first line and turn one
// mistake into two findings, which is how M6 settled it for the refusals too: the missing
// name is reported, and nothing else about that interface.
func TestArtifactNamesSkipsAnInterfaceWithNoName(t *testing.T) {
	d := chassisDevice("hostname c1\n", ctm.Interface{Name: "", Iftype: ctm.IftypePhysical})
	if got := objectsWarned(t, d); len(got) != 0 {
		t.Errorf("warned about %v for an interface with no name", got)
	}
}

// A device carrying no artifact is refused by name, by validation and by the compiler
// alike (M5). There is nothing here to read and nothing to add to that.
func TestArtifactNamesSaysNothingWithoutAnArtifact(t *testing.T) {
	d := chassisDevice("", ctm.Interface{Name: "Ethernet1/1", Iftype: ctm.IftypePhysical})
	d.Artifact = nil
	if got := ArtifactNames(d, surveyFor(t, d)); got != nil {
		t.Errorf("warnings %+v for a device with no artifact", got)
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
