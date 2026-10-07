package intent_test

import (
	"fmt"
	"net/http"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

const token = "sentinel-token-7c1e"

// readFake runs the read every command and activity runs, stage.Read, against the fake.
func readFake(t *testing.T, f *fakeInfrahub) (*ctm.CTM, findings.List, error) {
	t.Helper()
	return readFakeAt(t, f, "")
}

// readFakeAt is readFake pinned to at, as `--at` passes it.
func readFakeAt(t *testing.T, f *fakeInfrahub, at string) (*ctm.CTM, findings.List, error) {
	t.Helper()
	f.start(token)
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return stage.Read(t.Context(), f.branch, at, reg, "2026-09-18T00:00:00.000000Z")
}

// sentinelContent is artifact bytes that name themselves on every line, so a message
// quoting any of them is caught whichever line it quotes.
func sentinelContent(device string) []byte {
	return []byte("# CONTENT-SENTINEL " + device + "\nset / system name host-name CONTENT-SENTINEL-" + device + "\n")
}

// noContent asserts that no finding quotes a byte of any artifact the fake
// serves:
// a line of it, or the sentinel every test's content carries.
func noContent(t *testing.T, f *fakeInfrahub, list findings.List) {
	t.Helper()
	for _, fd := range list {
		if strings.Contains(fd.Message, "CONTENT-SENTINEL") {
			t.Errorf("%s quotes artifact content: %s", fd.Rule, fd.Message)
		}
		for _, obj := range f.objects {
			for _, line := range strings.Split(string(obj.Body), "\n") {
				if len(line) > 8 && strings.Contains(fd.Message, line) {
					t.Errorf("%s quotes artifact content %q: %s", fd.Rule, line, fd.Message)
				}
			}
		}
	}
}

// The fake unchanged is a clean read: every device comes back with its artifact, byte for
// byte, and nothing of Infrahub's addressing survives into the CTM. Every refusal below is
// this read with one thing changed.
func TestReadCarriesEachArtifact(t *testing.T) {
	f := newFakeInfrahub(t)
	want := map[string][]byte{}
	for _, d := range f.devices {
		want[d.Name] = f.objects["storage-"+d.Name].Body
	}

	c, list, err := readFake(t, f)
	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("a clean fake was refused: %v", list)
	}
	for _, d := range c.Devices {
		if d.Artifact == nil {
			t.Fatalf("device %s carries no artifact", d.Name)
		}
		if d.Artifact.Content != string(want[d.Name]) || d.Artifact.Name != "device-config" ||
			d.Artifact.ContentType != "text/plain" || d.Artifact.Checksum != md5Hex(want[d.Name]) {
			t.Errorf("device %s artifact %+v is not what Infrahub served", d.Name, *d.Artifact)
		}
	}
	for _, d := range f.devices {
		if n := f.count("/api/storage/object/storage-" + d.Name); n != 1 {
			t.Errorf("device %s's content was fetched %d times, want once", d.Name, n)
		}
	}
}

// Each artifact refusal of the read, produced by the read under test from a listing or an
// object store a live branch cannot be made to hold. Each names the device and the
// artifact, and says why in words an operator can act on, with no content in it.
func TestReadRefusesEachArtifactFault(t *testing.T) {
	sum := func(f *fakeInfrahub, device string) string { return f.artifacts[device][0].Checksum }

	for _, tc := range []struct {
		name  string
		setup func(f *fakeInfrahub)
		rule  string
		want  func(f *fakeInfrahub) string // the whole message
	}{
		{
			name: "no artifact of the package's name",
			setup: func(f *fakeInfrahub) {
				// An artifact of another definition is not this platform's configuration.
				f.artifacts["n2"][0].DefinitionName = "interfaces-report"
				f.artifacts["n2"][0].Name = "interfaces-report"
			},
			rule: findings.RuleArtifactMissing,
			want: func(*fakeInfrahub) string {
				return "device n2 has no artifact named device-config on branch fylgja-fixture"
			},
		},
		{
			name:  "no artifact at all",
			setup: func(f *fakeInfrahub) { delete(f.artifacts, "n2") },
			rule:  findings.RuleArtifactMissing,
			want: func(*fakeInfrahub) string {
				return "device n2 has no artifact named device-config on branch fylgja-fixture"
			},
		},
		{
			name: "two of that name",
			setup: func(f *fakeInfrahub) {
				second := f.artifacts["n2"][0]
				second.Checksum, second.StorageID = "00000000000000000000000000000001", "storage-n2-second"
				f.artifacts["n2"] = append(f.artifacts["n2"], second)
			},
			rule: findings.RuleArtifactAmbiguous,
			want: func(f *fakeInfrahub) string {
				sums := []string{f.artifacts["n2"][0].Checksum, f.artifacts["n2"][1].Checksum}
				slices.Sort(sums)
				return "device n2 has 2 artifacts named device-config (checksums " + sums[0] + ", " + sums[1] +
					"); fylgja never chooses among them"
			},
		},
		{
			name:  "pending",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].Status = "Pending" },
			rule:  findings.RuleArtifactNotReady,
			want: func(*fakeInfrahub) string {
				return "device n2: artifact device-config is Pending, not Ready; fylgja never regenerates an artifact, " +
					"because that is a write to Infrahub"
			},
		},
		{
			name:  "a generation that failed",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].Status = "Error" },
			rule:  findings.RuleArtifactNotReady,
			want: func(*fakeInfrahub) string {
				return "device n2: artifact device-config is Error, not Ready; fylgja never regenerates an artifact, " +
					"because that is a write to Infrahub"
			},
		},
		{
			name:  "Ready with no stored content",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].StorageID = "" },
			rule:  findings.RuleArtifactNotReady,
			want: func(*fakeInfrahub) string {
				return "device n2: artifact device-config is Ready but has no stored content, so it is not held as current; " +
					"fylgja never regenerates an artifact, because that is a write to Infrahub"
			},
		},
		{
			name:  "a content type the package does not accept",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].ContentType = "application/json" },
			rule:  findings.RuleArtifactContentTypeUnsupported,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config (checksum " + sum(f, "n2") +
					") is application/json; the nokia_srlinux package accepts text/plain"
			},
		},
		{
			name: "bytes that are not text",
			setup: func(f *fakeInfrahub) {
				f.setContent("n2", append([]byte{0xff, 0xfe, 0x00}, sentinelContent("n2")...))
			},
			rule: findings.RuleArtifactContentTypeUnsupported,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config (checksum " + sum(f, "n2") +
					") is text/plain but its content is not text"
			},
		},
		{
			name: "a storage object Infrahub does not hold",
			setup: func(f *fakeInfrahub) {
				f.artifacts["n2"][0].StorageID = "18d67d7e-0000-0000-0000-000000000000"
			},
			rule: findings.RuleArtifactContentUnavailable,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config (checksum " + sum(f, "n2") +
					"): Infrahub does not serve its content: HTTP 404: Unable to find the node " +
					"18d67d7e-0000-0000-0000-000000000000 / StorageObject in the database."
			},
		},
		{
			name: "another status, with no error document",
			setup: func(f *fakeInfrahub) {
				f.objects["storage-n2"] = fakeObject{Status: http.StatusBadGateway, Body: []byte("<html>bad gateway</html>")}
			},
			rule: findings.RuleArtifactContentUnavailable,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config (checksum " + sum(f, "n2") +
					"): Infrahub does not serve its content: HTTP 502"
			},
		},
		{
			name: "bytes that are not the ones Infrahub described",
			setup: func(f *fakeInfrahub) {
				f.objects["storage-n2"] = fakeObject{Status: http.StatusOK, Body: sentinelContent("n2 altered")}
			},
			rule: findings.RuleArtifactChecksumMismatch,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config fetched with checksum " + md5Hex(sentinelContent("n2 altered")) +
					", Infrahub reports " + sum(f, "n2")
			},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			// Every device's bytes carry the sentinel, so a message quoting content from any
			// device — not only the refused one — is caught.
			for _, d := range []string{"n1", "n2", "n3"} {
				f.setContent(d, sentinelContent(d))
			}
			tc.setup(f)

			c, list, err := readFake(t, f)
			if err != nil {
				t.Fatalf("the read failed rather than refusing: %v", err)
			}
			if c != nil {
				t.Error("a refused read returned a CTM")
			}
			want := findings.Finding{
				// No step: stage.Read's callers file its findings under theirs.
				Severity: findings.Rejection, Rule: tc.rule, Object: "n2", Message: tc.want(f),
			}
			if len(list) != 1 || list[0] != want {
				t.Fatalf("findings %+v\nwant exactly %+v", list, want)
			}
			noContent(t, f, list)
		})
	}
}

// A content fetch answered 401 or 403 is not a device's fault but the credential's: the
// read fails as a whole, naming the variable to fix and every device whose fetch was
// refused, each once, with the artifact and checksum it was reading, and the credential
// appears nowhere — not even when the server quotes the request's header back
// (contracts/cli.md "once per device that failed"). The fetch
// carries on past a refused device and past a served one, so n3 is named after n2 was
// read.
func TestReadContentCredentialRefusalFailsTheRead(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		for _, refused := range [][]string{{"n2"}, {"n1", "n3"}} {
			t.Run(http.StatusText(status)+"/"+strings.Join(refused, ","), func(t *testing.T) {
				f := newFakeInfrahub(t)
				for _, d := range refused {
					f.objects["storage-"+d] = fakeObject{Status: status,
						Body: []byte(`{"errors":[{"message":"key ` + token + ` refused"}]}`)}
				}

				c, list, err := readFake(t, f)
				if err == nil {
					t.Fatalf("the read did not fail: findings %v", list)
				}
				if c != nil || list != nil {
					t.Errorf("a failed read returned a CTM or findings: %v", list)
				}
				msg := err.Error()
				for _, want := range []string{intent.EnvToken, "reading the artifact content for device", "(branch fylgja-fixture)"} {
					if !strings.Contains(msg, want) {
						t.Errorf("error %q does not say %q", msg, want)
					}
				}
				for _, d := range []string{"n1", "n2", "n3"} {
					a := f.artifacts[d][0]
					named := fmt.Sprintf("device %s (artifact %s, checksum %s)", d, a.DefinitionName, a.Checksum)
					want := 0
					if slices.Contains(refused, d) {
						want = 1
					}
					if got := strings.Count(msg, "device "+d+" "); got != want || (want == 1 && !strings.Contains(msg, named)) {
						t.Errorf("error names %s %d times, want %d as %q: %s", d, got, want, named, msg)
					}
				}
				if strings.Contains(msg, token) {
					t.Errorf("the credential leaked into the error: %s", msg)
				}
			})
		}
	}
}

// Every refused device is reported in one pass, each named once, beside what validation
// finds in the intent itself — an operator fixing a branch sees everything that stops it,
// not the first thing (Constitution III).
func TestReadRefusesEveryDeviceInOnePass(t *testing.T) {
	f := newFakeInfrahub(t)
	for _, d := range []string{"n1", "n2", "n3"} {
		f.setContent(d, sentinelContent(d))
	}
	delete(f.artifacts, "n1")
	f.artifacts["n2"][0].Status = "Pending"
	f.objects["storage-n3"] = fakeObject{Status: http.StatusOK, Body: sentinelContent("n1")}
	// And a fault in the intent: a link with one endpoint.
	f.links[0].Endpoints = f.links[0].Endpoints[:1]

	c, list, err := readFake(t, f)
	if err != nil {
		t.Fatal(err)
	}
	if c != nil {
		t.Error("a refused read returned a CTM")
	}
	byDevice := map[string][]string{}
	completeness := 0
	for _, fd := range list {
		switch fd.Object {
		case "n1", "n2", "n3":
			byDevice[fd.Object] = append(byDevice[fd.Object], fd.Rule)
		}
		if fd.Rule == findings.RuleLinkEndpointsCount {
			completeness++
		}
	}
	for device, rule := range map[string]string{
		"n1": findings.RuleArtifactMissing,
		"n2": findings.RuleArtifactNotReady,
		"n3": findings.RuleArtifactChecksumMismatch,
	} {
		if !slices.Equal(byDevice[device], []string{rule}) {
			t.Errorf("device %s named by %v, want once, by %s", device, byDevice[device], rule)
		}
	}
	if completeness != 1 {
		t.Errorf("%d %s findings beside the artifact refusals, want 1: %v", completeness, findings.RuleLinkEndpointsCount, list)
	}
	noContent(t, f, list)
}

// pinnedAt is an operator's T with a character a query string must escape, so "verbatim"
// is shown to survive the encoding: Infrahub must receive exactly what was typed.
const pinnedAt = "2026-09-18T10:00:00.123456+00:00"

// askedOnlyAt asserts that a read asked Infrahub for nothing but the branch as of at: the
// schema endpoint with no at, and every GraphQL query and content fetch
// with at verbatim — or, unpinned, with none. A request without it would be a read of the
// branch now, the fallback a pinned read must never take.
func askedOnlyAt(t *testing.T, f *fakeInfrahub, at string) {
	t.Helper()
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, r := range f.served {
		switch {
		case r.Path == "/api/schema":
			if r.HasAt {
				t.Errorf("the schema endpoint was sent at=%q; it takes none", r.At)
			}
		case at == "":
			if r.HasAt {
				t.Errorf("an unpinned read sent %s %s with at=%q", r.Path, r.Operation, r.At)
			}
		case !r.HasAt || r.At != at:
			t.Errorf("a read pinned to %s sent %s %s with at=%q (sent: %v)", at, r.Path, r.Operation, r.At, r.HasAt)
		}
	}
}

// operations counts the GraphQL operations the fake answered, by name.
func (f *fakeInfrahub) operations(name string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := 0
	for _, r := range f.served {
		if r.Operation == name {
			n++
		}
	}
	return n
}

// A read with at carries it verbatim on the listing and on every content fetch, and a read
// without it carries none, so a pinned read's bytes are the ones Infrahub held at T.
func TestPinnedReadCarriesAtVerbatim(t *testing.T) {
	for _, at := range []string{"", pinnedAt} {
		t.Run("at="+at, func(t *testing.T) {
			f := newFakeInfrahub(t)
			c, list, err := readFakeAt(t, f, at)
			if err != nil {
				t.Fatal(err)
			}
			if list.Rejected() || c == nil {
				t.Fatalf("a clean fake was refused: %v", list)
			}
			if c.Envelope.At != at {
				t.Errorf("the CTM records at %q, want %q", c.Envelope.At, at)
			}
			for _, d := range c.Devices {
				if d.Artifact == nil {
					t.Errorf("device %s carries no artifact", d.Name)
				}
			}
			askedOnlyAt(t, f, at)
			for _, d := range f.devices {
				if n := f.count("/api/storage/object/storage-" + d.Name); n != 1 {
					t.Errorf("device %s's content was fetched %d times, want once", d.Name, n)
				}
			}
		})
	}
}

// A pinned read refused says which case applies in its own words — the artifact did not
// exist at T, was not Ready at T, or existed at T but is not served — and never falls back
// to the current artifact: no request of the read went without at, the listing was asked
// once, and the refused device's content was fetched no more than the listing at T named
// (contracts/cli.md).
func TestPinnedReadRefusesInItsOwnWords(t *testing.T) {
	sum := func(f *fakeInfrahub, device string) string { return f.artifacts[device][0].Checksum }

	for _, tc := range []struct {
		name    string
		setup   func(f *fakeInfrahub)
		rule    string
		fetched int // requests for n2's content
		want    func(f *fakeInfrahub) string
	}{
		{
			name:  "no artifact then",
			setup: func(f *fakeInfrahub) { delete(f.artifacts, "n2") },
			rule:  findings.RuleArtifactMissing,
			want: func(*fakeInfrahub) string {
				return "device n2 has no artifact named device-config on branch fylgja-fixture at " + pinnedAt +
					"; the artifact did not exist then"
			},
		},
		{
			name:  "not Ready then",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].Status = "Pending" },
			rule:  findings.RuleArtifactNotReady,
			want: func(*fakeInfrahub) string {
				return "device n2: artifact device-config was Pending at " + pinnedAt +
					", not Ready; fylgja never regenerates an artifact, because that is a write to Infrahub"
			},
		},
		{
			name:  "Ready then with no stored content",
			setup: func(f *fakeInfrahub) { f.artifacts["n2"][0].StorageID = "" },
			rule:  findings.RuleArtifactNotReady,
			want: func(*fakeInfrahub) string {
				return "device n2: artifact device-config was Ready at " + pinnedAt +
					" but had no stored content, so it was not held as current; " +
					"fylgja never regenerates an artifact, because that is a write to Infrahub"
			},
		},
		{
			name: "existed then but is not served",
			setup: func(f *fakeInfrahub) {
				f.artifacts["n2"][0].StorageID = "18d67d7e-0000-0000-0000-000000000000"
			},
			rule:    findings.RuleArtifactContentUnavailable,
			fetched: 1,
			want: func(f *fakeInfrahub) string {
				return "device n2: artifact device-config (checksum " + sum(f, "n2") +
					"): Infrahub does not serve its content as it stood at " + pinnedAt +
					": HTTP 404: Unable to find the node 18d67d7e-0000-0000-0000-000000000000 / StorageObject in the database."
			},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			for _, d := range []string{"n1", "n2", "n3"} {
				f.setContent(d, sentinelContent(d))
			}
			tc.setup(f)
			// Where the fallback would come from, were there one: the current artifact is
			// served under its own id, ready to be fetched instead.
			f.objects["storage-n2-current"] = fakeObject{Status: http.StatusOK, Body: sentinelContent("n2 current")}

			c, list, err := readFakeAt(t, f, pinnedAt)
			if err != nil {
				t.Fatalf("the read failed rather than refusing: %v", err)
			}
			if c != nil {
				t.Error("a refused read returned a CTM")
			}
			want := findings.Finding{Severity: findings.Rejection, Rule: tc.rule, Object: "n2", Message: tc.want(f)}
			if len(list) != 1 || list[0] != want {
				t.Fatalf("findings %+v\nwant exactly %+v", list, want)
			}
			noContent(t, f, list)

			askedOnlyAt(t, f, pinnedAt)
			if n := f.operations("Devices"); n != 1 {
				t.Errorf("the listing was asked %d times, want once", n)
			}
			// Every content fetch not of n1's or n3's is of n2's: whatever id it asked for.
			n2 := -f.count("/api/storage/object/storage-n1") - f.count("/api/storage/object/storage-n3")
			f.mu.Lock()
			for _, r := range f.served {
				if strings.HasPrefix(r.Path, "/api/storage/object/") {
					n2++
				}
			}
			f.mu.Unlock()
			if n2 != tc.fetched {
				t.Errorf("n2's content was fetched %d times, want %d", n2, tc.fetched)
			}
			if f.count("/api/storage/object/storage-n2-current") != 0 {
				t.Error("the pinned read fetched the current artifact")
			}
		})
	}
}

// Unpinned, the same refusals keep M5's present-tense wording, with no at in them: the
// pinned words are the pinned read's alone.
func TestUnpinnedRefusalsNameNoInstant(t *testing.T) {
	f := newFakeInfrahub(t)
	delete(f.artifacts, "n1")
	f.artifacts["n2"][0].Status = "Pending"
	f.artifacts["n3"][0].StorageID = "18d67d7e-0000-0000-0000-000000000000"

	_, list, err := readFake(t, f)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 3 {
		t.Fatalf("findings %v, want three", list)
	}
	for _, fd := range list {
		for _, pinned := range []string{" at ", "did not exist then", " was ", "as it stood"} {
			if strings.Contains(fd.Message, pinned) {
				t.Errorf("unpinned %s says %q: %s", fd.Rule, pinned, fd.Message)
			}
		}
	}
	askedOnlyAt(t, f, "")
}
