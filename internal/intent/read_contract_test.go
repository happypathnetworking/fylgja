//go:build contract

package intent

import (
	"context"
	"fmt"
	"math/rand"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
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

// read runs the conformance-then-fetch pass the command runs, and fails on anything
// the command would report as an operational failure.
func read(t *testing.T, branch, at string) (*ctm.CTM, *Conformance) {
	t.Helper()
	conf, snapshot, err := tryRead(t, branch, at)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	return snapshot, conf
}

// tryRead is read without the assertion, for the cases where the failure is the point.
func tryRead(t *testing.T, branch, at string) (*Conformance, *ctm.CTM, error) {
	t.Helper()
	cfg, err := FromEnv(branch, at)
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	client := New(cfg)
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()

	observedAt := time.Now().UTC().Format("2006-01-02T15:04:05.000000Z")
	conf, list, err := client.CheckConformance(ctx)
	if err != nil {
		return nil, nil, err
	}
	if list.Rejected() {
		return conf, nil, fmt.Errorf("branch does not conform: %v", list)
	}
	reg, err := psp.Load("")
	if err != nil {
		return conf, nil, err
	}
	// The artifact findings are the caller's business only when it is testing them; a
	// read that produced any returns a CTM whose devices are short of an artifact, which
	// is what every caller here would notice anyway.
	snapshot, _, err := client.Fetch(ctx, conf, observedAt, reg)
	return conf, snapshot, err
}

// The committed fixture is what the golden tests compile. If the read and the fixture
// ever disagree, the golden tier is testing something the product does not produce.
//
// The envelope is excluded by construction: one came from a branch at a real instant,
// the other is a file with a stand-in schema hash. Everything below the envelope must
// match byte for byte.
func TestReadReproducesTheCommittedFixture(t *testing.T) {
	harness(t) // skip early when there is no Infrahub
	got, _ := read(t, testsupport.FixtureBranch, "")

	want, err := ctm.Load(filepath.Join(repoRoot(), "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
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

// The fixture branch holds exactly the three-node topology (CLAUDE.md), and the
// success line counts what it found.
func TestReadCountsTheFixture(t *testing.T) {
	harness(t)
	got, _ := read(t, testsupport.FixtureBranch, "")
	if n := Summarize(got); n.Devices != 3 || n.Interfaces != 12 || n.Links != 3 {
		t.Errorf("read %+v, want 3 devices / 12 interfaces / 3 links", n)
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
	if e.ContractVersion != ctm.ContractVersion {
		t.Errorf("contract_version = %q, want %q", e.ContractVersion, ctm.ContractVersion)
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
// missing generic can be named.
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
	for _, generic := range ctm.RequiredGenerics {
		if len(info.Implementers(generic)) == 0 {
			t.Errorf("no concrete kind implements %s", generic)
		}
	}
	if !info.Kinds[ctm.ContractKind] {
		t.Errorf("%s node kind is absent", ctm.ContractKind)
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
