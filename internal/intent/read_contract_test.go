//go:build contract

package intent

import (
	"context"
	"fmt"
	"math/rand"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// Contract tests run against a real Infrahub, never a fake (D-017). Infrahub's
// behaviour is the integration most likely to surprise us, and a fake would only
// assert what we already believe.
//
//	set -a; . local/.env; set +a; go test -tags contract ./internal/intent

// repoRoot is where schema/ and testdata/ live, relative to this package.
func repoRoot() string { return filepath.Join("..", "..") }

// harness returns a write-capable client, skipping when no Infrahub is configured.
func harness(t *testing.T) *testsupport.Client {
	t.Helper()
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	return c
}

// throwaway makes a branch that is deleted when the test ends. Every branch a contract
// test writes to is one of these: the durable fylgja-fixture branch is only ever read
// (CLAUDE.md), so a failing test can never damage it.
func throwaway(t *testing.T, prefix string) (*testsupport.Client, string) {
	t.Helper()
	c := harness(t)
	branch := fmt.Sprintf("fylgja-test-%s-%d-%d", prefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(branch); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		if err := c.DeleteBranch(branch); err != nil {
			t.Logf("could not delete branch %s: %v", branch, err)
		}
	})
	return c, branch
}

// fixtureScope is the scope every fixture is read under: the tag each seeded device carries.
const fixtureScope = ScopePrefix + testsupport.FixtureTag

// seeded makes a throwaway branch holding the schema library and the three-node fixture,
// rendered: what the read's live cases change.
func seeded(t *testing.T, prefix string) (*testsupport.Client, string) {
	t.Helper()
	c, branch := throwaway(t, prefix)
	if err := c.LoadSchema(branch, filepath.Join(repoRoot(), "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(branch); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s", branch)
	return c, branch
}

// read runs the read the command runs under the fixtures' scope and fails on anything the
// command would not write a CTM for: an operational failure or a rejection.
func read(t *testing.T, branch, at string) (*ctm.CTM, *Conformance) {
	t.Helper()
	snapshot, list, conf, err := readUnder(t, branch, at, fixtureScope)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	if list.Rejected() {
		t.Fatalf("reading %s was rejected: %v", branch, list)
	}
	return snapshot, conf
}

// tryRead is read without the assertions, for the cases where the failure is the point.
func tryRead(t *testing.T, branch, at string) (*Conformance, *ctm.CTM, error) {
	t.Helper()
	snapshot, list, conf, err := readUnder(t, branch, at, fixtureScope)
	if err == nil && list.Rejected() {
		return conf, nil, fmt.Errorf("the read of %s was rejected: %v", branch, list)
	}
	return conf, snapshot, err
}

// readUnder runs the conformance-then-fetch pass `intent read` runs, under scope: the CTM,
// nil when the read refused to write one; every finding of both passes, conformance's, the
// scope's, the platforms', the omitted cables' and the artifacts'; and an operational
// failure, when the read could not run at all.
func readUnder(t *testing.T, branch, at, scope string) (*ctm.CTM, findings.List, *Conformance, error) {
	t.Helper()
	cfg, err := FromEnv(branch, at)
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	cfg.Scope = ScopeTag(scope)
	client := New(cfg)
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()

	observedAt := time.Now().UTC().Format("2006-01-02T15:04:05.000000Z")
	conf, list, err := client.CheckConformance(ctx)
	if err != nil {
		return nil, nil, nil, err
	}
	if list.Rejected() {
		return nil, list, conf, nil
	}
	reg, err := psp.Load("")
	if err != nil {
		return nil, nil, conf, err
	}
	snapshot, fetched, err := client.Fetch(ctx, conf, observedAt, reg)
	return snapshot, append(list, fetched...), conf, err
}

// The committed fixture is what the golden tests compile. If the read and the fixture
// ever disagree, the golden tier is testing something the product does not produce.
//
// Everything below the envelope must match byte for byte: one came from a branch at a real
// instant, the other is a file with a stand-in schema hash. Of the envelope, what the read
// is and not when it was made must match too: the scope it was read under, the mapping it
// read by and the fidelity list's three fixed rows, since the fixture's cables are all
// placed and none is omitted.
func TestFixtureReadsToTheThreeNodeCTM(t *testing.T) {
	harness(t) // skip early when there is no Infrahub
	got, _ := read(t, testsupport.FixtureBranch, "")

	want, err := ctm.Load(filepath.Join(repoRoot(), "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	e := got.Envelope
	if e.Scope != fixtureScope || e.Scope != want.Envelope.Scope {
		t.Errorf("scope %q, want %q", e.Scope, fixtureScope)
	}
	if lib := (ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: LibraryModel, Version: LibraryVersion}); e.Mapping != lib ||
		e.Mapping != want.Envelope.Mapping {
		t.Errorf("mapping %+v, want %+v", e.Mapping, lib)
	}
	if len(e.Fidelity) != 3 || !reflect.DeepEqual(e.Fidelity, want.Envelope.Fidelity) {
		t.Errorf("fidelity %+v, want the three fixed rows %+v", e.Fidelity, want.Envelope.Fidelity)
	}
	got.Envelope = want.Envelope

	gotJSON, err := ctm.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	wantJSON, err := ctm.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	if string(gotJSON) != string(wantJSON) {
		t.Errorf("the read and the committed fixture disagree:\n--- read\n%s\n--- fixture\n%s", gotJSON, wantJSON)
	}
}

// The fixture branch holds exactly the three-node topology (CLAUDE.md): three devices,
// each with its management port and two cabled ports, three cables and three artifacts.
// The success line counts what it found.
func TestReadCountsTheFixture(t *testing.T) {
	harness(t)
	got, _ := read(t, testsupport.FixtureBranch, "")
	if n, want := Summarize(got), (Counts{Devices: 3, Interfaces: 9, Links: 3, Artifacts: 3}); n != want {
		t.Errorf("read %+v, want %+v", n, want)
	}
}

// The cables the read cannot place are omitted, each a finding and a fidelity row, and
// refuse nothing (US2 scenarios 2 and 3; FR-006; R-05), against a real Infrahub: on a seeded
// branch, a console server cs1 that carries no tag, with a port, and a cable from a new
// n1:ethernet-1/3 to it; and a cable joining three new ports, n1:ethernet-1/4,
// n2:ethernet-1/3 and n3:ethernet-1/3. The read is the fixture's three devices and three
// links, the new ports cabled to nothing, and cs1 is never read: the end outside the scope
// is named by its device's id, which is all Ports selects of a device it was not given.
func TestCablesTheReadCannotPlace(t *testing.T) {
	c, branch := seeded(t, "omit")
	cs1, err := c.AddDevice(branch, testsupport.Device{Name: "cs1", Ports: []string{"port1"}})
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []struct{ device, port string }{
		{"n1", "ethernet-1/3"}, {"n1", "ethernet-1/4"}, {"n2", "ethernet-1/3"}, {"n3", "ethernet-1/3"},
	} {
		if err := c.AddInterface(branch, p.device, p.port); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddCable(branch, "c-out", "n1:ethernet-1/3", "cs1:port1"); err != nil {
		t.Fatal(err)
	}
	if err := c.AddCable(branch, "c-three", "n1:ethernet-1/4", "n2:ethernet-1/3", "n3:ethernet-1/3"); err != nil {
		t.Fatal(err)
	}

	got, list, _, err := readUnder(t, branch, "", fixtureScope)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	// The artifacts were rendered before the ports were added, and are read as they stand:
	// Infrahub renders nothing on its own, and a port the artifact does not name is no
	// finding. So the omissions are the read's only findings.
	outside := cs1 + ":port1"
	want := findings.List{
		{Severity: findings.Info, Rule: findings.RuleOmitCableOutsideScope, Object: "c-out",
			Message: "cable c-out is omitted: an end outside the scope (" + outside + "); its ends are " + outside + ", n1:ethernet-1/3"},
		{Severity: findings.Info, Rule: findings.RuleOmitCableEnds, Object: "c-three",
			Message: "cable c-three is omitted: other than two ends (3); its ends are n1:ethernet-1/4, n2:ethernet-1/3, n3:ethernet-1/3"},
	}
	if !reflect.DeepEqual(list, want) || got == nil {
		t.Fatalf("findings\n%v\nwant\n%v (and a CTM)", list, want)
	}
	rows := []ctm.FidelityRow{
		{Disposition: ctm.FidelityOmitted, Object: "c-out", Source: "DcimCable", Reason: "an end outside the scope (" + outside + ")"},
		{Disposition: ctm.FidelityOmitted, Object: "c-three", Source: "DcimCable", Reason: "other than two ends (3)"},
	}
	for _, r := range rows {
		if !slices.Contains(got.Envelope.Fidelity, r) {
			t.Errorf("fidelity %+v holds no row %+v", got.Envelope.Fidelity, r)
		}
	}
	if len(got.Envelope.Fidelity) != 5 {
		t.Errorf("fidelity %+v, want the three fixed rows and the two omissions", got.Envelope.Fidelity)
	}
	if n, want := Summarize(got), (Counts{Devices: 3, Interfaces: 13, Links: 3, Artifacts: 3, CablesOmitted: 2}); n != want {
		t.Errorf("read %+v, want %+v", n, want)
	}
	if got.Device("cs1") != nil {
		t.Error("cs1 carries no tag and was read")
	}
	for _, p := range []string{"n1:ethernet-1/3", "n1:ethernet-1/4", "n2:ethernet-1/3", "n3:ethernet-1/3"} {
		device, port, _ := strings.Cut(p, ":")
		d := got.Device(device)
		if d == nil {
			t.Fatalf("device %s was not read", device)
		}
		i := d.Interface(port)
		if i == nil || i.Link != "" {
			t.Errorf("port %s read as %+v, want it read and cabled to nothing", p, i)
		}
	}
}

// A device whose platform no package matches is refused by name, and so is one with no
// platform, in one pass and with no CTM (US2; FR-014): on a seeded branch, n1 moved onto
// the platform nokia / SR-Linux, which differs from Nokia / SR Linux in letter case and
// spelling, and n2's platform taken away. n3 is read as before, and its artifact is no
// finding.
func TestPlatformsTheReadRefuses(t *testing.T) {
	c, branch := seeded(t, "platform")
	if err := c.SetDevicePlatform(branch, "n1", "nokia", "SR-Linux"); err != nil {
		t.Fatal(err)
	}
	if err := c.SetDevicePlatform(branch, "n2", "", ""); err != nil {
		t.Fatal(err)
	}

	got, list, _, err := readUnder(t, branch, "", fixtureScope)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	if got != nil {
		t.Error("a refused read returned a CTM")
	}
	want := findings.List{
		{Severity: findings.Rejection, Rule: findings.RulePlatformUnmatched, Object: "n1",
			Message: `device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: ` +
				`arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]`},
		{Severity: findings.Rejection, Rule: findings.RulePlatformMissing, Object: "n2"},
	}
	if len(list) != len(want) {
		t.Fatalf("findings\n%v\nwant two, in one pass:\n%v", list, want)
	}
	for i, w := range want {
		f := list[i]
		if f.Severity != w.Severity || f.Rule != w.Rule || f.Object != w.Object {
			t.Errorf("finding %d: %+v, want %s %s on %s", i, f, w.Severity, w.Rule, w.Object)
		}
		if w.Message != "" && !strings.HasPrefix(f.Message, w.Message) {
			t.Errorf("finding %d's message %q, want it to begin %q", i, f.Message, w.Message)
		}
	}
	if !strings.Contains(list[1].Message, "device n2 carries no platform") {
		t.Errorf("platform.missing's message %q does not say what n2 carries", list[1].Message)
	}
}

// A scope that selects no device is refused scope.empty, naming the scope and the branch,
// with no CTM (FR-015): the fixture read under tag:nothing, a tag none of its devices
// carries.
func TestScopeSelectsNothing(t *testing.T) {
	harness(t)
	got, list, _, err := readUnder(t, testsupport.FixtureBranch, "", "tag:nothing")
	if err != nil {
		t.Fatalf("reading %s: %v", testsupport.FixtureBranch, err)
	}
	want := findings.List{{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: "tag:nothing",
		Message: "scope tag:nothing selects no device on branch " + testsupport.FixtureBranch}}
	if got != nil || !reflect.DeepEqual(list, want) {
		t.Errorf("CTM %v, findings %v; want no CTM and %v", got != nil, list, want)
	}
}

// An unpinned read records observed_at and no at: Fylgja never invents an instant.
func TestUnpinnedReadRecordsObservedAtAndNoAt(t *testing.T) {
	harness(t)
	before := time.Now().UTC().Add(-time.Second)
	got, conf := read(t, testsupport.FixtureBranch, "")

	e := got.Envelope
	if e.Branch != testsupport.FixtureBranch {
		t.Errorf("branch = %q, want %q", e.Branch, testsupport.FixtureBranch)
	}
	if e.At != "" {
		t.Errorf("no at was supplied, so none may be recorded: %q", e.At)
	}
	if e.ObservedAt == "" {
		t.Fatal("observed_at is not recorded")
	}
	// Six fractional digits, always, so an observed_at can be handed back as --at
	// without tripping the precision rule.
	observed, err := time.Parse("2006-01-02T15:04:05.000000Z", e.ObservedAt)
	if err != nil {
		t.Errorf("observed_at %q does not carry six fractional digits and a Z: %v", e.ObservedAt, err)
	}
	if observed.Before(before) {
		t.Errorf("observed_at %s predates the start of the test", e.ObservedAt)
	}
	if msg := CheckAtPrecision(e.ObservedAt); msg != "" {
		t.Errorf("observed_at is too precise to be replayed as --at: %s", msg)
	}
	if e.SchemaHash == "" || e.SchemaHash != conf.SchemaHash {
		t.Errorf("schema_hash = %q, conformance saw %q", e.SchemaHash, conf.SchemaHash)
	}
	// The library's mapping, which the fixture holds once re-seeded in the library's kinds.
	if want := (ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: LibraryModel, Version: LibraryVersion}); e.Mapping != want {
		t.Errorf("mapping = %+v, want %+v", e.Mapping, want)
	}
}

// A pinned read sends the operator's at verbatim and records it verbatim. Nothing
// normalises it: the envelope has to name the instant Infrahub was actually asked about.
func TestPinnedReadSendsAndRecordsAtVerbatim(t *testing.T) {
	c := harness(t)
	// The whole second after the fixture's last artifact became Ready, so the read is
	// complete, with six fractional digits that nothing may normalise. Taken from the
	// running Infrahub: a constant names one install's fixture, and an Infrahub installed
	// later refuses it as before its default branch.
	ready, err := c.ArtifactsReadyAt(testsupport.FixtureBranch)
	if err != nil {
		t.Fatalf("finding when the fixture was complete: %v", err)
	}
	pinned := ready.UTC().Truncate(time.Second).Add(time.Second)
	at := pinned.Format("2006-01-02T15:04:05") + ".123456Z"
	// In the past, so Infrahub is not asked about the future; only a fixture rendered
	// within the last second makes this wait.
	time.Sleep(time.Until(pinned.Add(123456 * time.Microsecond)))

	cfg, err := FromEnv(testsupport.FixtureBranch, at)
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	if got := cfg.endpoint(); !strings.Contains(got, "at="+strings.ReplaceAll(at, ":", "%3A")) {
		t.Errorf("endpoint does not carry the at verbatim: %s", got)
	}

	got, _ := read(t, testsupport.FixtureBranch, at)
	if got.Envelope.At != at {
		t.Errorf("envelope records at %q, want %q verbatim", got.Envelope.At, at)
	}
	if got.Envelope.ObservedAt == "" {
		t.Error("observed_at is recorded on every read, pinned or not")
	}
	if len(got.Devices) != 3 {
		t.Errorf("read %d devices at %s, want the whole fixture", len(got.Devices), at)
	}
}

// An at before the default branch was created is Infrahub's own refusal, surfaced as
// an operational failure naming the branch and the at — never a finding about intent,
// because nothing was read.
func TestAtBeforeTheDefaultBranchIsAnOperationalFailure(t *testing.T) {
	harness(t)
	const at = "2000-01-01T00:00:00Z"
	_, snapshot, err := tryRead(t, testsupport.FixtureBranch, at)
	if err == nil {
		t.Fatal("expected an instant before the default branch to be refused")
	}
	if snapshot != nil {
		t.Error("a refused read produced a CTM")
	}
	msg := err.Error()
	for _, want := range []string{testsupport.FixtureBranch, at, "before branch"} {
		if !strings.Contains(msg, want) {
			t.Errorf("message does not mention %q: %s", want, msg)
		}
	}
}

// An at Infrahub cannot parse is its refusal too, surfaced the same way.
func TestUnparseableAtIsAnOperationalFailure(t *testing.T) {
	harness(t)
	_, snapshot, err := tryRead(t, testsupport.FixtureBranch, "yesterday")
	if err == nil {
		t.Fatal("expected an unparseable at to be refused")
	}
	if snapshot != nil {
		t.Error("a refused read produced a CTM")
	}
	if !strings.Contains(err.Error(), "Invalid time format") {
		t.Errorf("Infrahub's own message is not surfaced: %v", err)
	}
}

// An unknown branch is a 404 naming the branch.
func TestUnknownBranchIsReported(t *testing.T) {
	harness(t)
	const branch = "fylgja-no-such-branch"
	_, snapshot, err := tryRead(t, branch, "")
	if err == nil {
		t.Fatal("expected an unknown branch to be reported")
	}
	if snapshot != nil {
		t.Error("an unknown branch produced a CTM")
	}
	if !strings.Contains(err.Error(), branch) {
		t.Errorf("message does not name the branch: %v", err)
	}
	// An unknown branch is reported as such, naming the branch — both halves. The
	// schema endpoint is the first thing a read touches, so it is what refuses an
	// unknown branch, and its body carries the sentence.
	if !strings.Contains(err.Error(), "not found") {
		t.Errorf("message does not say the branch does not exist: %v", err)
	}
}

// The schema endpoint is what conformance is read from, and it is the only place a
// generic's implementers and its own fields can be named: on the fixture branch, every
// kind the mapping reads is there, the generic it reads a field of among them with the
// relationships it reads, and every generic the mapping reads through is implemented as
// the table says.
func TestSchemaInfoReportsImplementers(t *testing.T) {
	harness(t)
	cfg, err := FromEnv(testsupport.FixtureBranch, "")
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	info, err := New(cfg).SchemaInfo(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range LibraryTables {
		kinds := info.Nodes
		if k.Generic {
			kinds = info.Generics
		}
		kind, ok := kinds[k.Kind]
		if !ok {
			t.Errorf("kind %s is absent", k.Kind)
			continue
		}
		// The generic's own fields are what the Ports query reads through its interface.
		for _, r := range k.Relationships {
			if _, ok := kind.Relationships[r.Name]; !ok {
				t.Errorf("%s has no relationship %s", k.Kind, r.Name)
			}
		}
	}
	for _, u := range LibraryUsedBy {
		if !slices.Contains(info.Implementers(u.Generic), u.Implementer) {
			t.Errorf("%s is not implemented by %s: %v", u.Generic, u.Implementer, info.Implementers(u.Generic))
		}
	}
	if info.Hash == "" {
		t.Error("schema hash is empty")
	}
}

// A deliberately wrong credential must never appear in an error —
// including when the credential is what failed.
func TestBadCredentialDoesNotLeak(t *testing.T) {
	c := harness(t)
	const bogus = "deliberately-wrong-token-9f3a"
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	_, err := New(Config{Address: c.Address, Token: bogus, Branch: testsupport.FixtureBranch}).SchemaInfo(ctx)
	if err == nil {
		t.Skip("instance allows anonymous reads; nothing to assert")
	}
	if strings.Contains(err.Error(), bogus) {
		t.Errorf("the credential leaked into an error: %v", err)
	}
	if !strings.Contains(err.Error(), EnvToken) {
		t.Errorf("message does not name the variable to fix: %v", err)
	}
}
